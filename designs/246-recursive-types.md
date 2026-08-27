# Design 246 — Recursive Nominal Types via Indirection

**Status: AUTHORED + DISPATCHED Aug 27 2026** (lead; user directed same day —
"write a recursive brief and launch it where you think appropriate, sooner is
better". Runs in a concurrent worktree, disjoint from the DF-215f transform
work and design 245's scalar work). **Motivating consumer: std.json's
`JsonValue`** (design 215 stage D) — the json dispatch hit this wall Aug 27 and
pivoted to the serde-seam half; the tree half is deferred behind this brief.

## The finding — DF-260a (filed Aug 27, lead-probed)

Every CYCLIC nominal-type shape is an internal compiler error, including the
shapes whose layout is finite because the cycle crosses a heap indirection.
Probed on main (`.build/scratch/probe_rec_*.saw`), all five rows two-stage:
first the copy-policy diagnostic ("pick a copy policy"), then — with the
demanded `NoCopy` declared — `internal compiler error: Undefined enum: X`:

| shape | today |
|---|---|
| enum with `Vector<Self>` payload | ICE |
| enum with `Box<Self>` payload | ICE |
| struct with `Box<Self>?` field | ICE |
| mutually recursive enum pair via `Vector` | ICE |
| enum with DIRECT inline `Self` payload (genuinely infinite) | ICE (same message — not distinguished from the finite rows) |

Acyclic forward references (`Outer` using `Inner` declared later) compile and
run fine — the gap is cycles, not declaration order.

**Mechanism (obligation 4).** `_register_types` (`sawc/codegen/core.py:~2360`)
topologically sorts declarations by member dependency and its own comment
concedes the case at `core.py:2404` — "may have cycles - just add them" — so a
cycle reaches registration unresolved in arbitrary order. Registration then
lowers member LLVM types EAGERLY before publishing the type:
`_register_struct` computes every field type (`core.py:2427`) before inserting
into `struct_types` (`core.py:2435`); `_register_concrete_enum` lowers every
payload type to size the variants (`core.py:2504`) before inserting into
`enum_types` (`core.py:2537`); monomorphized instances
(`generics.py:406` and the enum twin) follow the same lower-then-publish
order. Any self-demand therefore arrives at `_get_llvm_type`'s lookup while
the type is still unpublished and raises `Undefined enum/struct: X`
(`codegen/types.py:322`, `:292`). The class is total: every cyclic shape,
legal-to-be and illegal alike, dies at the same lookup, which is why the
matrix above needs no further siblings — there is exactly one mechanism.

## The rule (ruled by dispatch, Aug 27)

The Rust/Swift line, stated structurally rather than by container allowlist:

1. **A cyclic reference among nominal types is LEGAL exactly when every cycle
   passes through at least one heap indirection** — i.e. no type's storage
   transitively contains its own storage INLINE. `Box<Self>`, `Vector<Self>`,
   `Map<String, Self>` payloads are legal; so is a mutual cycle where one leg
   is indirected and the other inline (`Expr` holds `Vector<Term>`, `Term`
   holds `Expr` inline — finite: `Term` embeds `Expr`'s storage, `Expr`'s leg
   is a pointer).
2. **An all-inline cycle is a CLEAN, located error**, never an ICE:
   `error: recursive type 'X' has infinite size`, naming the cycle path
   member-by-member (`X.field -> Y.payload -> X`), with a hint to indirect
   through a heap-allocating container (`Box`, `Vector`, `Map`). Diagnostic
   prose per the saw-docs skill; no abbreviations.
3. **What counts as inline is discovered STRUCTURALLY, never by an allowlist
   of blessed container names.** Struct fields, enum payloads, tuple elements,
   `Optional` payloads (`{i1, T}`) and `[T; N]` elements embed inline; a
   pointer-kinded member (`UnsafePointer`, function pointers, the erased
   existential's box) embeds nothing. A user generic `struct Pair<T> { a: T }`
   embeds `T` inline because its declaration says so; `Vector<T>` does not
   because its stored field is a pointer — both facts fall out of the same
   walk into the member declarations with substitution, which is what keeps
   the rule correct for every future container without maintenance.

Copy-policy interaction: unchanged. A recursive type carries owning payloads,
so the existing policy demand (NoCopy / `@synthesize` ExplicitCopy) applies
exactly as today; `@synthesize`d ExplicitCopy/Equatable bodies on a recursive
type simply recurse, and deinit synthesis likewise. Deep-structure drops
recurse to data depth — same accepted behavior as Rust/Swift; the spec notes
it, nothing engineers around it in v1.

## Unit A — the finite-size check (typechecker), and the clean diagnostic

A cycle detector over the inline-embedding graph of nominal declarations,
running before codegen. Edges come from ONE walk (obligation 1: this is a
position-quantified rule — "every position a type embeds storage inline" —
so it is a FUNNEL): a single helper enumerating a declaration's inline member
types, whose docstring NAMES its entry points (struct fields, enum payloads,
tuple/named-tuple elements, Optional payload, `[T; N]` element; and by
recursion with substitution, the corresponding positions of any generic
declaration a member instantiates). Generic references expand symbolically —
walk the referenced declaration with type arguments substituted; memoize on
(declaration identity, substituted args as written) so the walk terminates,
and treat a revisit of an IN-PROGRESS node as the cycle it is. (DF-258b's
recursive-instantiation GROWTH — `List<List<...>>` — is a different disease
with its own fix in the ratified 218c spec; this walk detects same-node
cycles and must not be confused with unbounded fresh-node chains. If the
walk meets a growth chain, bound the depth and error cleanly rather than
hang; note it in the report.)

An all-inline cycle reports at the declaration of the first cycle member in
source order, shape per rule 2 above. `EXPECT-ERROR-ABSENT: internal compiler
error` on every illegal-row test.

## Unit B — two-phase registration (codegen)

Publish-before-lower, so a legal cycle's self-demand resolves:

- **Structs** already use LLVM identified types (`core.py:2430`): create the
  identified type and PUBLISH it in `struct_types` BEFORE lowering field
  types, then `set_body(...)` after. A self-reference during field lowering
  then finds the (possibly still-opaque) identified type — which is exactly
  what identified types exist for; a pointer to an opaque body is legal and
  sized.
- **Payload-carrying enums** become identified structs too (today they are
  `ir.LiteralStructType([i32, [N x i8]])` — `core.py:2523`): create + publish
  the identified type, lower and size payloads, then set the body to
  `{i32, [N x i8]}`. Payload-free and raw-backed enums stay bare ints
  (they cannot be recursive — no payload, no member edge). The stored handle
  in `enum_types` is used uniformly downstream, so the representation change
  should be transparent; the reemit/irdet lanes will catch anywhere it is not.
- **Monomorphized instances** (`_ensure_monomorphized_struct/enum`) adopt the
  same publish-before-lower discipline IN THE REGISTRATION HELPERS themselves,
  not at call sites — design 218 unit 1.5 (HELD, ratified spec `218c`) will
  relocate the callers, and the discipline must travel with the helpers, not
  the call sites. Note the overlap in the landing report so the 1.5 dispatch
  reads it.
- **Inline SIZE demands** (`_abi_size` of a variant struct embedding another
  not-yet-finalized type) recurse into registering the demanded type first,
  with an in-progress set. Hitting an in-progress type on a SIZE path is the
  all-inline cycle — unreachable given Unit A; guard it with a breadcrumbed
  assertion (per the `icebreadcrumb` lane's conventions), never a bare
  KeyError.
- The toposort in `_register_types` may stay as an ordering heuristic or be
  retired in favor of pure demand-driven registration — implementer's choice;
  if retired, its cycle-concession comment (`core.py:2404`) goes with it.

## Unit C — tests + docs

Tests in `examples/` (compile-run rows) and the error-diagnostic convention
the suite already uses for refusals. The matrix, every row its own file named
for the behavior:

Legal — compile, run, and where marked (†) verify destruction by
deinit-instrumented payloads (the Arc-print idiom the DF-215f pin uses):
1. enum self via `Vector<Self>` payload — the JsonValue shape: build a small
   tree, match on it, drop it †
2. enum self via `Box<Self>` — build a 3-node list, traverse, drop †
3. struct self via `Box<Self>?` — push/walk/drop †
4. mutual enum pair, both legs via `Vector`
5. mixed mutual cycle: `Expr` holds `Vector<Term>`, `Term` holds `Expr`
   INLINE — the one-indirection-is-enough row
6. generic interposition: `struct Pair<T> { a: T }`;
   `enum E { case K(v: Vector<Pair<E>>) }` — inline through the user generic,
   indirected overall
7. `@synthesize` ExplicitCopy + Equatable on a recursive enum — synthesized
   recursion works; copy is deep, equality is structural †
8. recursion under a suspending function touching the type (a task builds and
   drops a tree) — the coro transform meets the new types

Illegal — clean located diagnostic naming the cycle, `EXPECT-ERROR-ABSENT:
internal compiler error`:
9. enum direct inline `Self` payload
10. struct direct inline `Self` field
11. cycle through `Optional<Self>` (inline)
12. cycle through `[Self; N]` (inline)
13. inline cycle through a user generic (`Pair<E>` as the only path)
14. mutual ALL-inline cycle (`A.b: B`, `B.a: A`)

The five lead probes (`.build/scratch/probe_rec_*.saw`) seed rows 1-4 and 9.
No conformance rows owed (obligation 3 considered: the refusal is a
compile-time size rule, not a runtime safety guarantee; nothing unsound ships
today — the ICE fails closed).

Docs (design 125 convention): LANGUAGE_SPEC gains the recursive-types section
(the rule, the structural inline definition, the deep-drop note);
the saw-lang skill gains the idiom (recursive enums via Vector/Box, the copy
policy demand); README gains its line (recursive types via indirection). All
per the saw-docs skill.

## Gates

Compiler branch: per-commit full suite + `tools/freestanding_runner.py` (both
arches), through the machine-wide suite lock. Terminal: the full battery
(`tools/battery.sh` with `SAW_PYTHON`), which carries the reemit/irdet lanes
that police Unit B's representation change corpus-wide. New findings filed by
this brief's agent take DF-261a+ (range assigned at dispatch; DF-260 is this
brief's own finding).

## Obligations ledger

1. Funnel: Unit A's single inline-member walk, entry points named in its
   docstring. 2. No behavioral contract flips — every affected program ICEs
   today; nothing can rely on it (the consumer sweep is vacuous by
   construction). 3. No conformance rows (rationale in Unit C). 4. Mechanism
   named and total (one lookup, one lower-then-publish order); matrix above.

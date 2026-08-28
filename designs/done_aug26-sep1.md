# Saw Tracker — Archived Recaps (Aug 26 – Sep 1, 2026)

Landed / closed / decided entries moved VERBATIM out of designs/todo.md,
opened at the Aug-26 split (first move Aug 27). Section order and text
are as found there; every open item stayed in todo.md — including the
design-215 section (its DF-215f bullet closed but the section holds open
items), the DF-261a..f section (a/b fixed, c-f open), and the DF-242b
and DF-257c entries (closed with recorded open residue). Queue/backlog
records for moved work travel here with their entries. Append-only
history.

## Queue records (moved Aug 27)

- ~~DF-215f fix — the suspending-match moved-payload double release~~ **LANDED Aug 27** (designs/247-scrutinee-temp-migration.md, all three units; entry under design 215 below carries the landing note). `FAM_SCRUTINEE_TEMP` retired, every hoist temp take-read, the DF-218w residue SUBSUMED as predicted and DF-262a dissolved as a side effect. DF-242a/DF-255a were not subsumed and stay open
- ~~Design 246~~ — recursive nominal types via indirection — LANDED Aug 27, entry below. `JsonValue` is writable; design 215 stage D unblocked
- ~~DF-265a fix — MODULE-KEY the free-function registry~~ **LANDED Aug 27** (designs/249-module-keyed-functions.md, all three units; entry below carries the landing note). DF-242b CLOSED with it as predicted; DF-242c SURVIVED as predicted and stays open. `std.json.encode` has its natural name back, and DF-268a (std.json never joined the prelude gate) was found and fixed on the way
- ~~std.json unit 1 — the `JsonValue` tree~~ **LANDED Aug 27** (e2464f70 on main, integration gate green; the design-215 stage-D note carries the landing detail — `Object` serialization parks behind DF-267d, combined accessors behind DF-267c, `Number` Int-only pending a std Float text story; the build filed DF-267a-d). Original record: (parse-to-DOM, DOM-to-text, Optional-returning accessors), EVENT-GATED on design 246 integrating rather than queue-ordered (user, Aug 27: resume once the recursive-types fix lands). GATE FIRED + DISPATCHED Aug 27, minutes after 246's integration gate went green — a FRESH Sonnet agent (the unit-2 agent could not be resumed once its integrated worktree was removed; the dispatch carries the context, and the lexical layer in sawc/std/json.saw was built for this reuse). MODEL RULING (user, Aug 27): the continuation stays SONNET deliberately — dogfood value, the design-203 logic (a simpler model surfaces more language pain as findings). Agent DF range DF-267a+. Pinned defaults carry over from the original dispatch: numbers Int-when-lexically-integral-and-in-range else Float, duplicate keys last-wins (matching the landed seam decode), get-shaped accessors return Optional; pretty-printing stays OUT of unit 1 (open). Landing owes the design-215 stage-D note an update

## Backlog records (moved Aug 27)

- ~~DF-262a — the container-head hoist's move-only refusal diagnostic names the compiler-internal frame field (`self.__head0…`) to the user~~ **DISSOLVED Aug 27 by design 247; LEAD-CONFIRMED CLOSED same day (probe re-run on main post-integration — both shapes compile, single release).** The refusal was the head temp's `value()` LEND meeting a move-only element; the head temp is take-read now, so there is no place to refuse and both filed shapes (`match get_maker("h0").build()` at a move-only tier, `if let r = try? suspending()` at `Res?`) compile and release exactly once. Probe: `.build/scratch/df262a.saw` on branch `worktree-agent-a15c1414bca26ee3b`

## Design 246 — recursive nominal types via indirection — LANDED Aug 27
## (DF-260a CLOSED; authored + dispatched Aug 27)

- STATUS: LANDED, four commits. All 14 matrix rows are
  `examples/recursive_*.saw`; per-commit gate (full suite + freestanding, both
  arches) green on each, and the terminal battery is 22 stages GREEN — including
  the `reemit` and `irdet` lanes that police unit B's representation change
  corpus-wide.
  - Unit A — the typechecker inline-embedding funnel
    (`_inline_embedding_edges` in `typechecker/types.py`, entry points named in
    its docstring) plus `ErrorKind.RECURSIVE_TYPE` and the located diagnostic;
    runs AHEAD of the containment checks in both `check` and `check_module`.
    Staged so ONLY all-inline cycles changed behavior — the legal shapes still
    ICEd after this commit, which is what kept it honest.
  - Unit B — publish-before-lower in all four registration helpers
    (`_register_struct`, `_register_concrete_enum`,
    `_ensure_monomorphized_struct`, and `_ensure_monomorphized_enum` through
    the concrete one), `_demand_register_type` for the cycle member the
    ordering cannot reach, and `_finish_or_defer` for the body whose members
    are not sized yet. Payload-carrying enums are IDENTIFIED structs now.
  - Unit C — spec section "Recursive types", README, saw-lang skill, this
    entry.
  - Unit B follow-up — the catch union's LLVM name. `reemitdiff` caught two
    files after unit B; the synthesized `_CatchError_{node_id}` name comes from
    a process-global allocator (DF-164a's class) and unit B is what put it in
    the IR text by making the enum an identified type. The name is the variant
    SEQUENCE now, which identifies the union exactly.
- THE TOPOSORT STAYS, as an ordering heuristic only. Its `get_deps` edge set
  states a hard edge for every type ARGUMENT of a generic field, including the
  ones a container reaches only through a pointer — a strict SUPERSET of the
  layout relation, and what used to drop a cyclic type into the concession at
  `core.py:2404`. Left overstated deliberately: registration no longer depends
  on the order at all, and narrowing the edges to Unit A's inline relation
  would reshuffle emitted type order corpus-wide for no correctness gain. The
  comment at the sort says so, so the edge set is not mistaken for a layout
  claim again.
- DESIGN 218 UNIT 1.5 OVERLAP: the publish-before-lower discipline lives IN
  `_register_struct` / `_register_concrete_enum` /
  `_ensure_monomorphized_struct` and in the shared `_finish_or_defer`, never at
  a call site, so relocating the monomorphization callers carries it along. The
  ONE thing 1.5 must not lose is `_get_llvm_type`'s two demand hooks
  (`codegen/types.py`, the `Undefined struct:` and `Undefined enum:` arms):
  those are what register a cycle member the caller reached before the loop did.
- FOUND ALONGSIDE: DF-261a and DF-261b (both FIXED here — a helper re-entering
  a guarded structural walk with a FRESH visiting set, twice: `copy_tier`'s
  `_has_abstract_type_arg` and `_send_sync`'s `_satisfies_thread_bound`);
  DF-261c/d/e (filed, open); DF-261f (filed, open, pre-existing). DF-257c
  closed as a side effect — see its entry.
- Brief: designs/246-recursive-types.md. Filed when the std.json dispatch hit
  the wall Aug 27: EVERY cyclic nominal shape is `internal compiler error:
  Undefined enum/struct: X` once the demanded copy policy is declared —
  including the finite ones (`Vector<Self>`/`Box<Self>` payloads, mutual
  cycles through a container); acyclic forward references are fine. ONE
  mechanism, lead-probed (five probes in the brief): registration lowers
  member LLVM types BEFORE publishing the type, and the toposort concedes
  cycles at `codegen/core.py:2404`. Rule (ruled by dispatch): a cycle is
  legal iff it crosses a heap indirection, discovered STRUCTURALLY — no
  container allowlist; an all-inline cycle is a clean located infinite-size
  diagnostic, never an ICE. Units: A the typechecker inline-embedding funnel,
  B publish-before-lower registration (payload enums become identified
  structs), C the 14-row matrix + spec/skill/README. The json dispatch
  pivoted to the serde-seam half meanwhile; `JsonValue` plugs into its
  lexical layer when this lands. Agent DF range: DF-261a+.

## DF-265a — same-named public generic free functions in two std files are a
## flat-namespace collision (filed Aug 27 by the std.json build)
## **CLOSED Aug 27 — designs/249-module-keyed-functions.md, all three units**

- Adding `public func encode<T: Serialize>(value: &T) sync -> Result<String,
  EncodeError>` to `sawc/std/json.saw` while `sawc/std/cbor.saw` holds
  `public func encode<T: Serialize>(value: &T) sync -> Result<Data,
  EncodeError>` (different module, different return type) fails EVERY build:
  `internal compiler error: builtins failed to type-check` / ``function
  `encode` is already defined with an indistinguishable signature`` at
  `builtins:1114:8`. The two are import-gated members of separate design-82
  file-modules; nothing should collide. MECHANISM VERIFIED (lead, Aug 27):
  `namespace.function_overloads` is ONE FLAT dict keyed by bare name
  (`sawc/namespace.py:762-774`) — free-function symbols carry no module
  key — and the design-53/55 declaration-site ambiguity check
  (`typechecker/registration.py:925-949`) compares shape keys (params/arity
  only; return type rightly excluded) against EVERY registration under the
  name, cross-module. "builtins" in the message is only the reporting wrapper
  (`sawc.py:467`) because std typechecks in the builtins pass — the registry
  is compilation-wide, so the mechanism reaches USER modules too, where
  DF-242b/c (cross-module overload sets bound bare as a single overload;
  suffixed literals not disambiguating) are already-filed faces of the same
  unkeyed-symbol family. The contrast is in the same file: STATICS got the
  per-module overlay at DF-140h (`namespace.py:776-789`) and TYPE identity
  is (module, name) since design 144 — free functions are the last unkeyed
  symbol kind. Fix shape: module-key the function registry the way DF-140h
  keyed statics; scope the ambiguity check to same-module declarations plus
  genuine one-scope collisions (bare-import overlap reports at the
  import/call, per design 150), and re-probe DF-242b/c against it — the fix
  brief should treat all three as one family. std.json shipped `encode_json`
  meanwhile — a rename, not a semantic workaround; the fix frees the
  natural name. SCHEDULED Aug 27 (user): queued directly after DF-215f;
  the fix brief is owed at dispatch, with DF-242b as an expected closure
  and DF-242c re-probed (its same-module cell is likely a separate
  resolution mechanism, not this registry).
- **LANDED Aug 27, design 249.** The registry keeps design 144's two acts
  apart: `module_function_overloads[def_module][name]` is the identity half,
  `function_name_modules[name]` is which modules a bare name is bound to in
  each namespace, and `register_function` files both so every binding path
  records itself. `lookup_function_overloads` is the one funnel over the two
  (docstring names its entry points); its filter engages only when candidates
  span 2+ modules, so a single-owner name resolves exactly as before, and
  `lookup_function` then applies design 150's ladder — a module's own
  declaration outranks anything merged in under the same name. Codegen
  naming follows: a `free_function_owners` census over the parsed module set
  (std folded in) decides each declaration's `symbol_base` before any module
  is checked, so a name more than one module owns is `$M$`-tagged per module
  with no dependence on check order. Unit 2 renamed `std.json.encode_json`
  back to `encode` — the live proof, `examples/d249_std_json_and_cbor_both_
  name_encode.saw`. Ten new examples cover the matrix: qualified twins,
  bare-import merge, selective-of-one, the call-site tie naming both origins,
  DF-242b's two bare forms, and four design-150 ladder rungs.

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

## Queue + backlog records (moved Aug 28, second rotation)

- ~~Design 252 — the DF-270d fix~~ **LANDED Aug 28** (designs/252-unsigned-comparison.md; three commits, per-commit suite+freestanding gates, terminal battery green). Unsigned ordered comparisons lower unsigned at both faces, design 250's two held cbor rows are back, and the pin flipped. See the DF-270d entry below for the mechanism and the sweep. Agent DF range DF-275a+ — nothing filed by the branch itself; ONE unrelated candidate reported for the lead to file (a distinct alias over a primitive satisfies a `Comparable` bound through a std extension's receiver type argument but NOT through a free generic function's own bound, and the fixit the refusal offers is then rejected by the orphan rule as `std.builtin`'s to write — repro in the landing report)
- ~~Design 253 — the Float↔text story~~ **LANDED Aug 28** (designs/253-float-text.md; four units, per-commit suite + freestanding green, terminal battery in the landing report). `sawc/std/float.saw` is new and owns the whole story: Ryū for shortest round-trip formatting, Eisel-Lemire over an exact decimal fallback (Clinger/Steele-White, no `leftcheats` table) for correctly-rounded parsing, `Float.to_bits`/`from(bits:)`, `String.to_float` (moved out of string.saw, naive body deleted) and `StringBuilder.append(value: Float)`. The SIX Float→text positions were TWO renderings that disagreed (`printf("%f")` for `print(f)`, `snprintf("%g")` for the rest, neither round-tripping); all six funnel through `_render_float_value` now, and the layout is CPython `repr`'s, which is also the vectors' oracle. The freestanding refusal is GONE — it was written at two of the six positions, so interpolation/`to_string()`/`format(into:)` left an undefined `snprintf` in a freestanding object; `tests/freestanding/cases/float_text.saw` replaces it on both arches, and `.fsmark` moved to ORIGIN + 512 KiB because the float image overlapped it. `JsonValue` gained a `Float` case under the pinned rule (the TOKEN decides: `1` is `Number`, `1.0` is `Float`), with `as_float`, a json-private `write_float` refusing non-finite values as `EncodeFault.Unsupported`, and JSON.md updated; the serde SEAM still has no `write_float`, as scoped. Oracle: `tools/sawfloat.py` (`gen`/`tables`/`verify`) + `tests/float_vectors/` (2897 round-trip + 175 parse rows, seed 253, byte-identical on regeneration) + the `floatvectors` battery lane, which also re-derives the 1236 committed Ryū table entries. Five EXPECT-OUTPUT files updated (the `%f` padding). Findings filed: DF-276a/b/c below. Agent DF range DF-276a+
- ~~The sos RIDERS batch~~ **STRUCK Aug 28 — the line was STALE ON ARRIVAL** (lead recon error, caught by the dispatched verification agent): all three riders LANDED Aug 21-20 (`dcbd6ea2` clock_get `type:`, `ff3c9c5f`+`ee88d72d` the shift spellings, `718a9784` kcore re-narrowing; recorded at done_aug18-aug25.md:1841). The Aug-28 dispatch became a VERIFICATION run instead: all sites confirmed at HEAD, 99 abi + 6 imgformat case values probe-verified identical across the conversion, and an independent `battery.sh suite sos` gate green (2289/6 + 80 sos both arches) — which IS design 238's settled-tree precondition, now evidenced. One record correction from the run: the done-file entry's "all 46 rights-enum cases" is an insertion-line count; the true scope is 39 rights cases + 4 SegFlag = 43 (noted here per the never-rewrite-archives rule)
- ~~Design 250 — the `Byte` type~~ **LANDED Aug 27 except one row** (designs/250-byte-type.md; census in its §8). `public type Byte = UInt8` lives in `sawc/builtin.saw` and needed NO compiler change — builtin is identity-exempt, loaded first, not import-required, and the only home that also works under `--runtime-build`. Landed: the String/StringBuilder flip through one read funnel (`byte_at`) and one write funnel per file, `append_char` -> `append(b: Byte)` (with `index_of`/`last_index_of` taking a `UInt8` needle per §5 Q4), three sign corrections deleted, `Data`/`FixedBuf` strict on reads and internals with `UInt8` sinks, and the serde/cbor/json `read_byte` family. **ONE ROW HELD: `std.cbor`'s `byte_at` + its UTF-8 boundary table stay `UInt8`** — its two callers ORDER bytes, and an ordered comparison on an alias over an unsigned underlying is lowered SIGNED today. That defect is DF-270d in the landing report, pinned by `examples/unsigned_ordered_comparison.saw` (XFAIL) and owed a tracker entry; it is one mechanism with a second, PRE-EXISTING face (`Comparable.compare()` is wrong on any unsigned integer), so it wants its own brief. Three brief errata are recorded in §8.6, the sharpest being that §4's stated digits spelling `append(b as UInt8)` is ambiguous (`as Int` is the working one). Agent DF range DF-270a+, all five findings in the landing report
- Design 251 — Map and Set join the ExplicitCopy tier (designs/251-std-copyability.md; user-directed Aug 27: value containers copyable when their contents are, so containing types like `JsonValue` can be ExplicitCopy — the unit-1 landing was FORCED NoCopy by Map's blanket). Vector is the oracle (conditional conformance + unconditional deinit + panicking copy/reporting try_copy); Data/Arc/String already done; builders + resource types STAY NoCopy. ~~DISPATCHED Aug 27 IN PARALLEL with 250~~ **LANDED Aug 27** (four commits integrated at ca079494..1971dc3a; per-commit gates + terminal battery 22/22 green on the branch). Map + Set carry Vector's conditional-ExplicitCopy shape — with one earned divergence: Map's enum-payload copies go through private `_key_ref`/`_value_ref` `borrows` lends (DF-146d pattern; a match-arm binding's `.copy()` is a refused value-read at the tier, unlike Vector's pointer place). JsonValue is `@synthesize ExplicitCopy` with ZERO accessor-spelling changes; conformance rows A18/A19 beside Vector's A17; consumer-sweep cells a-d probed clean. Filed DF-271a (below). Sonnet, per-task model approval
- ~~DF-267b fix + std.json `Object` serialization~~ **BOTH STAGES LANDED Aug 28.** Stage 1 (the typechecker default-type-arg fill at binding construction): see the DF-267b entry below for the funnel + sweep matrix. **STAGE 2 LANDED** (commit "std.json: Object serialization for JsonValue (DF-267b/DF-267d stage 2)"): `JsonValue._write`'s `Object` arm walks `Map.each`, writing each key via `write_text` and recursing into the value, with a `first_err: EncodeError?` capture standing in for the visitor's missing error channel (`each`'s closure is `Void`-returning and cannot short-circuit; every invocation past the first failure is a no-op). Routes around DF-272c exactly as scoped: `each` hands the key/value PAIR to the closure BY VALUE, never a `borrows` lend, so no place window is ever open while `_write` recurses. ONE THING THE DISPATCH DIDN'T ANTICIPATE: DF-267d's dissolution turned out to be shape-sensitive, not unconditional — `_write` recursing DIRECTLY (the `Array` arm's old `while` loop over `items[i]`) in ONE match arm while ALSO recursing THROUGH a visitor closure (the new `Object` arm) in ANOTHER still hit the builtins-pre-check refusal, reported at the DIRECT-call arm's line even though that arm is untouched — confirmed by direct probe (`cannot suspend in a sync closure context: closure calls JsonValue._write → Map.each → a call through a non-sync function value`). Fix: `Array` now ALSO recurses through `Vector.each`'s closure rather than a `while` loop, matching the THIRD dissolution probe shape the DF-267d entry already recorded ("Array arm recursing inside `Vector.each`'s closure") — once BOTH arms are closure-based, it compiles clean. No new DF filed: same "one effect signature per self-recursive function depending on a non-sync leaf API" mechanism DF-267d already names, not a new one — this is the shape that reaches it. Module header's stale "no `JsonValue` tree type in this file" paragraph rewritten (seam + tree, honestly describing the current file); JSON.md's status/OPEN list updated (Object closes; `Number` Float, pretty-printing, `max_items` parity stay open) — also caught JSON.md's stale `NoCopy` line (predated design 251's ExplicitCopy flip) on the same pass. Tests: `examples/json_value_object_serialize.saw` (basic/empty/nested/array-in-object/escaped-key/duplicate-key-survives-roundtrip/writer's-own-64-level-limit), `examples/json_value_object_deinit_no_copy.saw` (Carrier+Tag idiom, exactly-once deinit, twice-called `to_json_string` proving no consume/copy of the tree), `examples/json_value_roundtrip.saw`'s `check_object` flipped from expecting `Unsupported` to the real serialized text (that test IS the exact behavior landing here, so "stays green" meant updating it, not leaving it red). cbor: unaffected (checked at stage-1 landing, no sibling fix owed there either)
- ~~DF-270d — ordered comparison over an UNSIGNED integer lowers SIGNED~~ **CLOSED Aug 28 by design 252**, entry below

## ~~DF-270d — ordered comparison over an unsigned integer lowers SIGNED~~
## FIXED Aug 28 by design 252 (filed Aug 28 by design 250; CORRECTNESS)

- ONE mechanism (`_emit_int_compare`, `sawc/codegen/operators.py:818`,
  hard-coded `icmp_signed`), TWO faces: (a) `<`/`<=`/`>`/`>=` with a
  DISTINCT ALIAS over an unsigned underlying on the LEFT — the alias
  carries `TypeKind.STRUCT`, so the dispatch at `operators.py:478` routes
  it to the `compare()` path instead of the icmp branch that does consult
  `_int_is_signed`: `Byte(255) <= Byte(127)` is TRUE. (b)
  `Comparable.compare()` on ANY unsigned integer, no alias involved:
  `UInt.max.compare(&1)` is `Less` — PRE-EXISTING, reaching every
  `Comparable`-bounded generic, any sort over unsigned keys, and
  `sos/kernel/abi`'s eight `type XHandle = UInt` (kernel handles order
  wrongly today). Sound on the same values: `==`/`!=`, `/`, `%`, `>>`,
  widening casts, printing. Pin: `examples/unsigned_ordered_comparison.saw`
  (XFAIL, cited).
- CONSEQUENCE HELD IN 250: `std.cbor`'s `byte_at` + UTF-8 table stay
  `UInt8` — flipping them made `cbor169_vectors` accept `bad_utf8`, and
  `compare_in`'s canonical map-key ordering sits on the same edge; both
  call sites carry a comment naming the pin. The fix REOPENS those two
  rows and completes 250's cbor flip.
- Fix shape: signedness consulted at both faces' chokepoints
  (`_emit_int_compare` gains the unsigned branch; the alias dispatch stops
  mis-kinding a primitive-underlying alias into the struct path).
  Obligation-4 sweep owed at dispatch: any OTHER operator lowering that
  hard-codes signedness (shifts are recorded sound; the sweep proves the
  rest), and the alias-mis-kinding dispatch's other consumers.
- **LANDED Aug 28 as design 252, three commits.** `_int_type_is_signed` is the
  one signedness authority (substitute THEN resolve aliases; `None` is signed),
  its docstring naming every entry point per obligation 1 — `_int_is_signed`,
  the two compare emitters, and `_widen_int_value`/`_coerce_int_to_field`, which
  had their own copies of the same three lines in two different orders.
  `_comparison_operand_type` resolves the alias before the dispatch reads its
  kind (face a); `_emit_int_compare` takes the operand's signedness (face b).
  The sweep found TWO further wrong cells at the same emitter, both fixed here:
  an unsigned struct FIELD / enum PAYLOAD compared through a derived memberwise
  compare, and a raw-backed `enum E: UInt8` whose case value passes 127
  (`Backed.High(200) > Backed.Low(1)` was false) — the tag now reads its
  DECLARED BACKING. Everything else the sweep probed is unchanged and re-proved
  at the boundary values (`==`/`!=`, `/`, `%`, shifts, bitwise, wrapping and
  checked arithmetic, casts both ways, `Vector.sort`); unary negation on
  unsigned and an unsigned range `for` are clean refusals, and no unsigned
  `min`/`max`/`abs` helper exists. Design 250's held cbor row is IN (see its
  entry's "ONE ROW HELD", now superseded): `byte_at -> Byte` plus the eleven
  UTF-8 boundary statics, proved by running THAT cbor.saw against the pre-fix
  codegen, where `cbor169_vectors` reports `reject bad_utf8: accepted`. Pin
  flipped (marker removed, header rewritten); matrix at
  `examples/unsigned_ordered_comparison_matrix.saw`,
  `unsigned_comparable_compare.saw` and `unsigned_handle_ordering.saw`;
  conformance rows W25/W26 with rule 4 added to the W preamble.


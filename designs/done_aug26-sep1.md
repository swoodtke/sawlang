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


## Queue + DF records (moved Aug 31, third rotation)

- Design 254 — extension scope follows `public import` — **ALL UNITS LANDED Aug 30** (agent worktree, per-unit gates green: full suite 2296→2303 passed / 6 xfailed + freestanding 33 both arches at each commit). Unit 1: the per-file direct-import set is closed over the module-level public-import graph at ONE chokepoint before any body is checked, so a facade republishes its dependencies' extension neighbourhood and sawos design 8's ruled `Waiter.add(process:, key:)` is writable; every re-export form contributes the edge, the closure is transitive and cycle-safe, and nothing else moves (name binding, conformance coherence, the design-80 member gate, and a PLAIN import in a facade forwarding nothing). Unit 2: the two "hands on the NAME" hints, the spec's three-place list + §"Import form and extension visibility" + the re-export section, the saw-lang skill (whose bullet said the opposite), README, conformance row B25. Unit 3: `SAWC_VERSION` 0.2.0, `bin/sawc --version` verified, `toolchain` lane green. Consumer sweep: every `public import` in the tree is an examples/ fixture. Filed DF-280a (below), found writing unit 1's row-1 test and PRE-EXISTING. **The sawos-side consumption is USER-OWNED and still open** (pin bump, the fourth `Waiter.add` overload, death-notify's call site, lib.saw's paragraph) — brief: designs/254-extension-scope-public-import.md
- Design 255 — explicit imports shadow the gated std tier + real ambiguity spans — **ALL UNITS LANDED Aug 30** (same worktree, gate as above). Unit 0's sweep is recorded IN THE BRIEF (designs/255-prelude-shadow-precedence.md, "SWEEP RESULTS"), one row per cell: the FUNCTION row is already symmetric (design 249), the STATIC row has no collision surface (DF-140h's overlay), and PRELUDE and GATED are two tiers of which only the gated one is asymmetric — so the ruling lands there and conformance B12's reserved-prelude fence stands. The mechanism was wider than `bind_type_name`'s first-wins: the identity-first type lookup handed the import binder std's own symbol for every std public type whose identity is its spelling, which is why `File`/`Instant`/`SpinLock`/the enums bound STD's type SILENTLY while `Thread` (compiler-emitted, qualified) reached the ambiguity path. Units 1+2 landed as ONE commit (the brief's own shape: the shadow rule needs prelude bindings identifiable, which IS SL-4's fix). SL-4 closed: the report anchors on design 192's ICE breadcrumb, routes through `_error` for the file, and both sides carry real labels. Conformance row B26. Filed DF-280b (below): the PRELUDE tier's collision is recorded and not reported at the construction site, so its refusal names a missing initializer rather than the collision — the wording is the open half
- ~~DF-281a — a try form that MERGES or WRAPS the Ok payload is a codegen ICE over `Result<Void, E>`~~ **FILED + FIXED Aug 31 (lead, fix-on-discovery; found writing sawos code, reported by the user)**: a Void Ok extracts to no value, and three codegen sites read `.type` off it — the inline catch's merge phi (`results.py`, whose DF-196c guard covered the diverging-catch half of the same merge but not this one), `try?`'s `_wrap_in_optional` (`optionals.py` — its VoidType branch handled a void VALUE, not an absent one) and `try?`'s None-side type. MECHANISM SWEEP (obligation 4, all probed): inline catch diverging body ICE, inline catch fallback body ICE, `try?` ICE, the SPAWNED twin ICE (same funnel); `try!` and plain `try` return the raw extraction and always worked, statement position tolerating None. Fix: the merge returns control-only for a Void Ok, `_wrap_in_optional` accepts the absent value as the existing `{i1, i8}` `Void?`, the None side matches. Tests: `try_catch_void_result.saw`, `try_optional_void_result.saw`, `try_catch_void_result_spawned.saw`. Rides with the 0.2.1 bump (user, Aug 31: found during sos development, so sawos needs a pinnable release). No entry below, this line is the record

CLOSED BY USER RULING Aug 31 ("we can remove 238 and the M3 ladder — sawos is
up and running"), moved in the same rotation. The 238 remainders — the D-b
$PATH-executables-only ruling question, cold-fetch acceptance pending the
public sha, unit 6's negative tests — pass to the sawos side with it; re-file
here only if one resurfaces as sawlang work:

- Design 238 — the sawos split, **MOVED TO HEAD-AFTER-RIDERS Aug 28 (user), SUPERSEDING the Aug-24 "1.5 first" ordering** — rationale + five fresh rulings recorded in the brief's Aug-28 section (designs/238-sawos-split.md): independent development is the goal, the freestanding suite makes the sos lane non-essential for 218/1.5, D-c/D-d ratified as recommended, D-e ruled FLATTEN (sos/'s contents to the new repo's ROOT, unit 5 absorbs the path-dep rewrite), D-f ruled global skill symlink (created). UNITS 0-1 LANDED Aug 21; **UNITS 2-4 LANDED Aug 28** (30bfa960/b34cec35/590a3883 fast-forwarded; per-unit battery gates green incl. the named `bootstrap` stage) — imgformat is `libs/imgformat` with its own tests joining `LIB_DIRS`, a FIFTH crossing (freestanding_runner.py:102, created by unit 1 after the sweep) handled, and TWO pre-existing repairs: CI's library-tests lane had built Blade WITHOUT `--module-path imgformat=` since design 140 (red the whole time) and README's build command had the same hole — both fixed; `bin/` shims + `make install` + `sawc --version` (`sawc 0.1.0`, self-identifying — lead-ratified over bare semver, the resolver parses it); `tools/toolchain.py` resolver (38/38 unit tests, new `toolchain` battery lane + CI step, cache at `~/.cache/saw-toolchain/<sha>` — lead-ratified repo-neutral spelling). DF-277a filed (below); ONE RULING OPEN for the user before unit 6's acceptance rows: step 2 ($PATH) supplies EXECUTABLES only, so a $PATH-only environment can build sawc/blade consumers but NOT an SOS kernel (imgformat/toml/semver are source packages needing a ROOT via SAWLANG_ROOT or the fetch — the resolver refuses explicitly). **UNITS 5 + 7 LANDED Aug 28 (lead-driven, user's go with the SAWLANG_ROOT ruling): THE SPLIT IS DONE.** `../sawos` exists — filter-repo'd (111 commits of sos history), FLATTENED to its root per D-e (internal path deps survived untouched; sos_runner's 8 REPO_ROOT joins lost the sos/ level), stitched (Makefile, CLAUDE.md with its own lock path `sawos-suite-lock`, CI on the pinned-fetch path, sawlang.pin at a82e06f4, tools/{sos_runner,toolchain}.py), plus README (saw-docs voice, embedded-developer audience; user ruling recorded: the name is SawOS, NOT a placeholder — spec.md line 3 amended) and LICENSE. ACCEPTANCE: 80/80 both arches via SAWLANG_ROOT, transcript ROW-IDENTICAL to the Aug-21 unit-0 oracle; the SAWC-only needs-a-root refusal verified verbatim; cold-fetch acceptance PENDS the pinned sha becoming public (unit 6's negative tests also pend — the sawos-side remainder, small). sawlang side: sos/ deleted, sos-test target + sos battery stage + sos CI job + tools/sos_runner.py gone, framesizes' sos group deleted with a note; unit 7 docs done (CLAUDE.md repo map/gate policy/lock paragraph — which also CODIFIED the sandboxed-worktree SPLIT-LOCK pattern this week proved — TESTING.md, README). sawlang references sawos nowhere. sawos repo PARKED for user inspection at 8527beb; nothing pushed anywhere by the lead
- M3 ladder — designs/232-sos-m3-sketch.md: unit 1.5 interruptibility, 2 CreateProcess, 2.75 handle lifecycle, 3 give, 4 Memory/IoMemory, 5 quotas, 5.5 death notifications, 6 money shot — runs IN sawos, after design 238

RESOLVED Aug 20 (user): the 234 carve-out is WITHDRAWN — M3 unit 1.5 waits
for sawos; "238 before more M3 work" is absolute. SATISFIED Aug 28: the
split landed; M3 runs in the sawos repo from here.


Moved Aug 31 with the same user ruling (238 closed, sawos up and running) — the QUEUE line moved earlier the same day; this is the body entry, verbatim:

## Design 238 — the sawos split (AUTHORED Aug 19, FOUR RULINGS same day;
## QUEUED after the sos riders batch, BEFORE the M3 ladder)

designs/238-sawos-split.md is the plan of record: `sos/` leaves this repo for
`../sawos`, keeping its tests and building through Blade. The Aug-19 coupling
sweep (obligation 2, evidence in the brief) found the tree self-contained on
the package axis — every path dep under `sos/` resolves inside `sos/` — with
FOUR crossings out: `blade/Saw.toml:10`'s `imgformat` path dep,
`sos_runner.py`'s REPO_ROOT constants, `blade_bootstrap.py:42` (imgformat for
stage0 — THIS ONE GATES, battery's `bootstrap` stage), and `framesizes.py`'s
`sos` measurement group (design 163, hand-run, no gate). sawc has no dependency
on sos (comments plus the `sos-hosted` runtime-variant NAME). Blade's sos
fixtures are self-contained and STAY, `sosimg.saw` with them.

SWEEP CORRECTION Aug 19 (obligation 4 — the miss was a MECHANISM, recorded
because the same form will recur). The first pass said TWO crossings and "seven
packages"; both wrong. It grepped the literal string `sos/`, so every path
BUILT from components — `os.path.join(REPO, "sos", …)` — was invisible, which
hid `blade_bootstrap.py` and `framesizes.py`; and `sort -u` over `grep -hn`
output collapsed by line NUMBER, not by package, which invented the seven. Real
counts: 20 sysapi consumers (1 at `../kernel/sysapi`, 19 at
`../../kernel/sysapi`), 21 sosrt consumers. The re-sweep searched the
CONSTRUCTION (`join([^)]*"sos"`) across every .py/.sh and is the sweep of
record; a later audit should repeat THAT form, not the string form. The
conclusion (self-contained on the package axis) survived — but unit 2's and
unit 5's file lists changed, which is why it mattered.

RULED Aug 19 (user): (1) D-a — imgformat → `libs/imgformat`, with the Blade
target-plugin mechanism recorded as the probable future direction that
SUPERSEDES it ([BACKLOG]); unit 2 must add no sawlang-ward dependency so the
reversal stays cheap. (2) sawlang NEVER references sawos — the downstream-CI
gate is replaced by a standalone freestanding suite here. (3) No shared suite
lock across repos. (4) Toolchain discovery is `$PATH` first, pinned GitHub
fetch as fallback.

THE GATE, RE-FOUNDED. sos is a COMPILER gate today (CLAUDE.md — the suite alone
does not cover sos/; battery's `sos` stage), and it is a SYSTEM test doing a
UNIT gate's job: red says "the OS did not boot", not which feature regressed.
Unit 1 replaces it with `tools/freestanding_runner.py` — the generic half of
sos_runner (tool probing, `_run_qemu`, the ARCHES table, the transcript
matcher) kept as the engine — FORKED into sawos at unit 5, not shared (the
resolver does not resolve Python modules, and in the `$PATH` steady state there
is no sawlang tree on disk) — a new case table of tiny QEMU-EXECUTED programs
over the named inventory: `--freestanding`, `--no-hidden-alloc`,
`--runtime-provider` + ABI check, riscv32/aarch64 cross-codegen (32-bit target
from a 64-bit host), fixed-address linking, `--module-path` composition,
Blade's non-host target path. Compile-only would not do: calling-convention,
struct-layout and trap-frame bugs all survive a clean link. It adds a
`freestanding` battery stage ALONGSIDE `sos` (not a rename — units 2-4 still
need `sos` runnable) AND a `freestanding` CI job: `.github/workflows/ci.yml`'s
sos job runs `make sos-test` directly, not through battery, so a stage alone
would leave the suite running on nobody's machine but a developer's once unit 5
deletes the sos job. IT LANDS FIRST — once sawos pins a SHA, compiler churn
cannot break sawos, but nobody LEARNS it did until someone bumps the pin; the
pin is only safe because this suite exists.

Resolution is one funnel (obligation 1), `sawos/tools/toolchain.py`: explicit
env (`SAWC`/`BLADE`/`SAWLANG_ROOT`) → `$PATH` → pinned fetch → refusal.
`SAWLANG_ROOT` sits WITH the explicit group, not below `$PATH`: beneath it, a
dev standing in a sawlang checkout with any sawc installed globally silently
gets the installed one — D-b2's failure reachable from inside sawlang, and it
would break unit 4's in-repo default. The user's ruling holds where it applies
(a sawos user who sets nothing gets `$PATH` then fetch). Unit 0 captures the
current both-arch transcript as the acceptance oracle; unit 2 (imgformat,
in-repo, and it must carry `blade_bootstrap.py` with it) de-risks the rest.
Units 1, 2 and 4 all edit `sos_runner.py` and are STRICTLY SERIAL; only unit 3
parallelizes. No compiler change lands in this brief — a sawc defect surfaced
by the split exits as a DF.

THREE GAPS the `$PATH` ruling opens, all OPEN: D-b1 — there is no `sawc` or
`blade` BINARY to find (sawc is `python sawc/sawc.py` + llvmlite; no pyproject,
setup.py, bin/, or console script; blade is built from Saw source), so step 2
is dead code until sawlang gains an install story (unit 3, exits to its own
brief if it grows). D-b2 — a `$PATH`-found sawc is UNPINNED, inverting the
goal: the pin guards the fallback while the common path is whatever the dev has
installed. Needs `sawc --version` (none today) + a pin check that refuses
loudly on mismatch — AND a granularity ruling, since step 3 pins a SHA while
`--version` can only print a version, and a semver cannot separate two commits
sharing it (the normal case for an unreleased compiler): either `--version`
emits the build SHA and both paths check the same thing, or the asymmetry is
accepted and documented. Owed before unit 3 writes `--version`. D-b3 — the fallback is a clone-and-bootstrap, not a
download: SHA-keyed cache, build once, bootstrap shape (venv for llvmlite?)
still open. Reachability settled Aug 19 — `swoodtke/sawlang` is PUBLIC, so
HTTPS with no credentials and the fresh-machine promise holds.

Four more decisions open: D-c the sos briefs' disposition, D-d filter-repo vs
squash (history does NOT split cleanly — sos commits also touch blade/,
designs/, examples/, CLAUDE.md), D-e sawos layout, D-f the saw-lang skill.
Recommendations recorded in the brief. [238, 232, 140, 112]

UNITS 0-1 LANDED Aug 21 (branch `design-238-u1`). Unit 0:
`designs/238-sos-oracle-2026-08-21.txt`, the both-arch `sos_runner` transcript
at 47c9c7f8 — 40 cases per architecture, 80 passed — which every later unit is
diffed against. Unit 1: `tools/freestanding_runner.py` + `make
freestanding-test` + a `freestanding` battery stage ALONGSIDE `sos` + a
`freestanding` CI job cloning the sos job's toolchain install, over
`tests/freestanding/` — three arch-free Saw modules (`fsrt` the runtime
provider, `fscore` the vocabulary, `fsdata` the shared record), two forked
per-arch stubs (`boot.S` + `link.ld`), a Blade package, and a case table of
tiny QEMU-EXECUTED programs, one or more per row of the brief's inventory.
`tools/sos_runner.py` is UNTOUCHED — the generic half was COPIED, per the
brief's fork ruling. Units 2-7 remain open and are user-reserved.


## Queue + DF records (moved Aug 31, fourth rotation — the 256/257 landing)

- Design 256 — the overload set of a RESOLVED receiver, the DF-280a fix — **LANDED Aug 31** (agent worktree, per-unit gates green: full suite 2303→2310→2312 passed / 6 xfailed + freestanding 33 both arches at each commit). `_receiver_method_overloads` is the funnel — the set off the resolved `struct_info`, filtered by design 142's scope predicate alone, docstring naming its entry points — and `Namespace.lookup_method_overloads` is DELETED with its zero callers, so nothing is left to key an overload set on a spelling. `_check_resolved_static_call` is the static side's own meeting point for all FOUR routes: bare struct, bare enum, qualified struct, and the qualified-ENUM one that did not EXIST (the qualified arm answered variants only, so `mod.Grade.of(seed: 1)` fell through to the instance path and came back as DF-217q's "cannot be called on a value" for a call naming the type). Two codegen halves followed: the module-qualified static dispatch reads the call node's `resolved_type_identity` beside the member access's struct-only `resolved_struct_name`, and the funnel stamps that identity for BOTH resolvers (the overloaded twin never did). The ambiguity face is the one real flip and it is the finding's soundness half — silently took `dup_a`'s method and printed 1, now reports the design-142 error. Filed + fixed DF-283a on the way (enum extension overloads were an ICE, so the enum dimension was untestable). Tests: `overload_set_reaches_qualified_receiver`, `_qualified_static`, `_qualified_enum`, `ext142_two_modules_duplicate_qualified_error`, `enum_extension_overloads`, the `_unnamed_receiver` XFAIL REMOVED, and `ext254_facade_forwards`' DF-280a restriction replaced by the forwarded-overload calls. Docs: spec §"Extension scoping" (the three rules are answered against the TYPE) + the design-150 position list, saw-lang skill (import bullet + the enum-extension bullet); README states neither rule, untouched. **Closes sawos SL-11 upstream; the sawos-side pin bump is USER-OWNED** — brief: designs/256-resolved-receiver-overloads.md
- Design 257 — const-adoption ladder completeness, the DF-282a/b fix — **LANDED Aug 31** (same worktree as 256, per-unit gates green: full suite 2317 passed / 6 xfailed + freestanding 33 both arches). The ladder IS a funnel and both widenings are one edit each in it, as the brief hoped: `_const_adoption_slot` is the slot predicate (widened from the fixed widths to EVERY integer kind — DF-235a/b's "a platform expectation is what the expression already had" is true of `Int` and false of `UInt`) and `_const_adoption_shape` the leaf/operator one (widened to the LONE raw-backed case, which matched no operator shape and so reached no arm). The range check follows the slot through `_int_range_for`, the `BinaryOp`/`UnaryOp` folded-constant early returns gained a `MemberAccess` twin with its `const_folded_value` annotation and codegen arm, and `_flag_enum_backing` reached the COMPARISON operands so a lone case works in a `static_assert` where a combination always did. The old case (2c) — the platform half of the shift-forward — folded into (2b), which now owns every integer slot. Regressions all proved by test: design 205's runtime-operand refusal, `1 << 63` into `UInt64`, an enum-typed VALUE needing `as`, a runtime comparison against a case. Rows in `examples/coercion/` with the ledger updated (two supplementary bullets, one per axis). **TWO FINDINGS FROM THE CORPUS SWEEP, both entered below: DF-283b (filed + FIXED)** — the funnel folded a FORWARD-referencing static past design 186 unit 7, which the fixed-width slot had done silently since DF-235a/b — **and DF-283c (filed, RULING OPEN for the user)**, the dispatch's one works→refusal: `~(0 as UInt)` now folds signed and is refused as its `UInt32` twin always was, which the brief's §1 ruling covers explicitly but obligation 2 did not predict. One in-tree casualty, `examples/shift_signed_unsigned.saw`, now `UInt.max`. **Closes sawos SL-2/SL-9 upstream; the sawos-side pin bump is USER-OWNED** — brief: designs/257-const-adoption-completeness.md
- ~~DF-282a — a PLATFORM-WIDTH slot does not adopt a const expression~~ (sawos SL-2, filed upstream Aug 31) **CLOSED Aug 31 by design 257 §1**: the slot predicate takes every integer kind now, so `static M: UInt = (1 << BITS) - 1` folds and range-checks like its `UInt32` twin, at the static, the annotated `let`, the argument, the `return`, the arm and the compound-assign RHS (`examples/coercion/adopt_platform_width_slot_const.saw`, `_range_error.saw`). The sos-side `as UInt` workarounds stay legal and are the user's to remove. Original line, for the record: `static M: UInt = (1 << BITS) - 1` is refused where the `UInt32` twin folds — the DF-235/240 adoption ladder reaches FIXED-WIDTH slots only
- ~~DF-282b — a LONE raw-backed enum case does not adopt where a COMBINATION does~~ (sawos SL-9, filed upstream Aug 31) **CLOSED Aug 31 by design 257 §2**: the leaf predicate takes a lone case, so `static Y: UInt32 = E.A` is 1 wherever `E.A | E.B` is 3 — including the `static_assert` operand, which needed `_flag_enum_backing` at the comparison arm (`examples/coercion/adopt_lone_enum_case.saw` puts each lone case beside its combination; `_range_error.saw` is the check, `_value_error.saw` the fence). Original line, for the record: `static X: UInt32 = E.A | E.B` folds to 3, `static Y: UInt32 = E.A` is refused naming the enum type — the operator result is typed as the backing, a bare case is not, so adding a second flag REMOVES a cast
- ~~DF-280a — a receiver reached through a module QUALIFIER loses its method OVERLOAD SET~~ **CLOSED Aug 31 by design 256** (entry below, struck): one identity-keyed funnel behind every entry point, the qualified-enum static route added, `lookup_method_overloads` deleted. All five positions the entry's matrix names have tests — the instance call, `_instance_method_alternative`, the qualified static, the design-142 ambiguity (the silent-wrong-answer face, now an error) and the unbound-name receiver, whose XFAIL pin was removed in the landing. Original line, for the record: so only the first-registered overload is a candidate and a labeled call to any other is ``` `add` has no parameter named `knob` ``` (entry below, filed Aug 30 by design 254's unit-1 tests; PRE-EXISTING and independent of that brief — no `public import` is involved in the repro). Instance and static faces both; the mechanism is a lookup keyed on the receiver's WRITTEN SPELLING where its sibling path reads the resolved symbol, and the design-142 call-site ambiguity rides the same list. **Aug 31: sawos hit the THIRD face in the wild** — a receiver whose type NAME is not bound in the importing file at all (`import dep.{hand}`; the value arrived through the call) loses the set the same way, and the workaround is importing a name the file never writes, DF-247b's phantom-dependency shape. Pinned by `examples/overload_set_reaches_unnamed_receiver.saw` (cited XFAIL; the fix's XPASS flip validates it). User asked whether the fix is a better diagnostic — ruled-by-the-rules NO (lead, Aug 31): the selective import makes the module a DIRECT import and the receiver's inherent API travels with the value, so the program is legal and must resolve; the fix stays the entry's funnel shape
- ~~DF-283b — the const-adoption funnel folds a FORWARD-REFERENCING static, past design 186 unit 7's refusal~~ **FILED + FIXED Aug 31 (design 257's agent, fix-on-discovery)**: found by the corpus sweep — widening the ladder to platform slots (design 257 §1) broke `examples/errors/static_forward_reference.saw`, and the probe showed the FIXED-WIDTH spelling had the hole all along. `static EARLY: UInt32 = LATER * 2` above `static LATER: Int = 64` COMPILES and prints 128, reading a static "declared after this point" — the exact program design 186 unit 7 exists to refuse, and the refusal is still raised for the platform spelling one line away. MECHANISM (obligation 4): `_const_static_decls` is built WHOLE before registration (it has to be — a length in TYPE position resolves before any symbol exists), and `_const_static_lookup` falls back to it for "a static of this module not registered yet". Inside a static's OWN registration that phrase means the opposite: registration runs in declaration order, so the only names the fallback can answer for are the ones declared BELOW. The fold then succeeded and `_check_binary_op`'s folded-constant early return meant `_check_identifier` — where the diagnostic lives — never ran. Sweep of the fallback's other readers: the type-position length (`_const_length`) and the enum-case-value fold both run BEFORE registration and legitimately need it; `_check_identifier`'s own forward-reference report reads the table directly and is unaffected. Fix: a declaration-order fence around `_register_static`, so the symbol table is the sole authority while a static is being registered. Pinned by the existing `examples/errors/static_forward_reference.saw` (which now also covers the fixed-width slot through the shared mechanism). This line is the record
- ~~DF-283a — an ENUM extension's OVERLOADED methods are a codegen ICE~~ **FILED + FIXED Aug 31 (design 256's agent, fix-on-discovery)**: found probing the brief's "enums take the same treatment — probe, don't assume" clause, and PRE-EXISTING back to design 145. `enum Tone` with two `note` overloads (or two `of` statics) dies at the DECLARATION with `internal compiler error: Tone_note`, in a single file with no module or qualifier involved — so the enum dimension of design 256 was untestable until it landed. MECHANISM (obligation 4): design 145 gave enums the same `methods`/`method_overloads` tables and `Namespace.method_owner` is written once for both, but `_stamp_overload_symbols` (registration.py) walks `namespace.structs` ALONE, so no enum overload set ever gets its design-55 signature symbols, both members are declared under the plain `E_name` mangling and `_declare_extension_methods` raises `DuplicatedNameError`. Sweep of the same walk's siblings: the free-function half is module-keyed and covers everything; `_stamp_module_private_symbols` is free-functions-only by construction; the design-142 `$M$` module discrimination sits INSIDE the same loop and was equally enum-blind. Fix: the loop walks structs and enums. Tests: `examples/enum_extension_overloads.saw` (instance + static, single file), `examples/overload_set_reaches_qualified_enum.saw` (the design-256 enum row). This line is the record

## ~~DF-280a — a module-QUALIFIED receiver loses its method overload set~~
## (filed Aug 30 by design 254 unit 1; PRE-EXISTING, and nothing to do with
## `public import` — the repro is one module and one plain import)
## **CLOSED Aug 31 by design 256** — the mechanism and the position matrix
## below are what the fix targeted, row by row; kept verbatim as the record.

MECHANISM (obligation 4). TWO paths answer "which methods does this receiver
have", and they key on different things. `_scoped_method`
(`sawc/typechecker/expressions.py:8025`) reads `struct_info.methods` /
`struct_info.method_overloads` off the SYMBOL the call already resolved;
`_scoped_method_overloads` (`expressions.py:8039`) re-resolves the set by NAME
through `Namespace.lookup_method_overloads(struct_name, …)`, where
`struct_name` is `obj_type.struct_name` — the spelling as WRITTEN. A qualified
spelling resolves in the first and nowhere in the second (`method_owner` does a
simple-name `lookup_struct`), so the overload list comes back EMPTY, the
`len(...) > 1` guard at `expressions.py:10135` is False, and the call collapses
onto the representative in `methods`, which is whichever overload registered
first. Every sibling in the set is unreachable.

POSITIONS the mechanism reaches (each probed by direct compile,
`.build/scratch/p254c/`):

* **the INSTANCE call.** `pc_leaf.Panel(raw: 10)` then
  `p.add(knob: &k, key: 5)` against `{add(&self, n: Int), add(&self, knob:
  &Knob, key: Int)}` is ``` `add` has no parameter named `knob` ```;
  `p.add(n: 4)` (the representative) resolves, and so does the whole set in a
  file that imports the names bare. One hop or two through a facade makes no
  difference.
* **`_instance_method_alternative`** (DF-217q's static-vs-instance
  disambiguation) asks the same helper, so a qualified receiver whose
  representative is a static has no instance alternative to find.
* **the STATIC call.** `pc_stat.Bag.make(from: &a, bump: 3)` is
  ``` `Bag.make` has no parameter named `from` ```. Different code — the
  qualified-type route at `expressions.py:9730` — same shape: it takes
  `struct_info.methods[name]` and never consults an overload set AT ALL. The
  BARE static route one arm down (`expressions.py:9896`) does resolve
  overloads, which is exactly why only the qualified spelling is broken.
* **the design-142 call-site ambiguity** rides that same list, so a qualified
  receiver silently takes one of two indistinguishable extension methods where
  the bare receiver reports the ambiguity.
* **the UNBOUND-NAME receiver** (third face, hit in the wild by sawos Aug 31).
  `import dep.{hand}` and `let c = hand()`: the value is a `Crate`, both
  scoping rules put its whole extension surface in scope (the selective form
  is a direct import; the inherent API travels with the value), but nothing
  binds the SPELLING `Crate` in the file, so the name-keyed re-resolution
  misses and `c.make(top: 1)` is ``missing argument for parameter `entry` ``
  — the two-parameter sibling is the sole candidate. Adding `Crate` to the
  import braces "fixes" it, which is how the mechanism was confirmed: the
  fix imported a name the file never writes.

Repro, one module, no facade:

```saw
// modules/pc_leaf.saw
public struct Knob { public id: Int }
public struct Panel { public raw: Int }
extension Panel {
    public func add(&self, n: Int) -> Int { self.raw + n }
    public func add(&self, knob: &Knob, key: Int) -> Int { self.raw + knob.id + key }
}

// entry
import modules.pc_leaf
func main() {
    let p = pc_leaf.Panel(raw: 10)
    let k = pc_leaf.Knob(id: 3)
    print(p.add(n: 4))                 // 14 — the representative
    print(p.add(knob: &k, key: 5))     // error: `add` has no parameter named `knob`
}
```

THE FIX SHAPE: one chokepoint answering "the overloads of this receiver, in
scope here" off the resolved `struct_info`, with the qualified-static route
joining it instead of keeping its representative-only lookup. Design 150
promises a qualifier works in every position a name appears, so this is that
promise at the method-call position.

Design 254's row-1 test (`examples/ext254_facade_forwards.saw`) calls only
un-overloaded methods for this reason and says so in its header; the
forwarded-OVERLOAD dimension is row 8's, over a facade whose names arrive bare
(`examples/ext254_facade_overload_set.saw`).

## Rotated Sep 1 (218 unit 1.5 stages 3a/3b integration + the design-259 census)

- ~~DF-273a — a module-QUALIFIED static call on an ENUM type (`json.JsonValue.parse(text: …)`) is refused ``` `parse` is a static method of `JsonValue` and cannot be called on a value``` while the STRUCT twin (`time.Instant.now()`) resolves in the same file — the qualifier.Type.static path misses enums (design 145 gave enums statics; design 150 promises qualifiers work at every position a name appears). Observed by the DF-267b fix agent, lead-probed + narrowed Aug 28 (`.build/scratch/probe_qual_static.saw`); the bare spelling works. No entry below, this line is the record~~ **CLOSED Sep 1: NO LONGER REPRODUCES — the design-259 census swept it with two direct compile/run probes (a plain enum+struct control AND the entry's own Box-recursive NoCopy shape with a fallible `parse`); both compile and run. Most plausibly fixed by designs 249/255 (design 256 is the same family). Evidence preserved verbatim in `designs/reviews/parser-census-sep1.md` §5**
- ~~DF-285a — a type parameter CONSTRUCTED in the template (`A()`) survives substitution unrewritten, so a spliced instance names a function that does not exist~~ **FILED + FIXED Sep 1 (design 218 unit 1.5's stage-3 agent, fix-on-discovery)**: a REGRESSION THIS BRANCH INTRODUCED at stage 2 and invisible to the whole battery — main compiles the repro and prints `8`, the branch refused it with ``undefined function `M` `` carrying §3's own instantiation note. MECHANISM (obligation 4): `substitute_ast_types` rewrites `SawType`s, and a call's name is a `str`, so the one position where a type parameter is spelled OUTSIDE a type annotation — design 37's zero-argument construction `A()`, which `Vector._reserve` and `Box.make` are written around — is unreachable however completely the walker walks. While an instance's diagnostics were deleted this cost nothing (codegen re-derived the body from the template under `type_param_context`, reading the SUBSTITUTED `resolved_type` rather than the name); stage 2 made them real and turned it into a refusal of a legal program. POSITION MATRIX: the two neighbouring spellings are refused ABSTRACTLY, in the template, on this tree and on main alike — `M.seed()` (a static call on a parameter) is ``undefined variable `M` `` with no instance involved, and an enum-case spelling the same — so the mechanism has exactly one position. FIX: the funnel rewrites the call's NAME to the concrete type, which makes the clone an ordinary concrete program (`_check_function_call` then takes its struct-construction branch and stamps `resolved_type_identity`, and codegen lowers it as it lowers a hand-written `GlobalAllocator()`); gated on the argument list, since a construction takes none and function lookup wins over the type-param arm anyway. Pinned by `examples/generic_instance_constructs_type_param.saw`, which puts the spliced (spawned) instance and the ordinary codegen path side by side. This line is the record
- ~~DF-285b — the PRISTINE TEMPLATE STORE design 218c T1 names as the monomorphization phase's template source is EMPTY in an entry compile (entry below, filed Sep 1 by design 218 unit 1.5's stage-3 agent; PRE-EXISTING, and load-bearing for stage 3). Measured on `examples/hello.saw`: the three stores are 0 / 0 / 0 and `_module_scope_by_file` holds ONE entry, while the same compile demands 111 instances — every one of them std's~~ **CLOSED Sep 1 by stage 3a (main `1889c507`): A1's recommended path — the capture extended to the builtin checker, both stores riding the one stdcache blob; stop condition did not fire (0.022 s per cache build, blob +16.0%)**
- ~~DF-285c — design 218c stage 3's splice-all fails §5's OWN acceptance test before it is built, by ~8x, and the instance check at type-closure granularity is not zero-delta (entry below, same filer). §5's rule for exactly this outcome is that the staging PAUSES for the lead, which is what stages 3-5 have done~~ **CLOSED Sep 1: both halves resolved by ruling. The cost half — the copier (3b) cut ~8x to +18.8% suite-median and the USER ACCEPTED it, overriding A5(b)'s lazy selection (splice-all anyway; spec A5(b) OUTCOME section). The diagnostic half — 6 of 30 were DF-286a's false positives, the `Box<any Trait>.value` 6 are a REAL catch fixed by the user-ruled borrows accessor, the 24 rest go to §1c per-rule skips at 3c (spec A3 OUTCOME)**
- ~~DF-286a — the monomorphization registry calls EVERY specialized extension generic, because it decides from `Extension.type_args` and the parser never fills that field~~ **FILED + FIXED Sep 1 (design 218 unit 1.5's stage-3a/3b agent, fix-on-discovery)**: a stage-1 defect, invisible to shadow mode because it makes the registry OVER-approximate and shadow only proves codegen's demands are a SUBSET of it. MECHANISM (obligation 4): an extension head is parsed as type PARAMETERS whichever it is — the parser cannot tell `<String>` (a type) from `<T>` (a parameter), so it fills `type_params` and leaves `type_args` EMPTY, and the classification is re-decided later by asking whether each parameter's NAME denotes a known type. The typechecker (`_get_specialization_key`) and codegen (`_get_extension_specialization`) each do that; `monomorphize._build_tables` asked `specialization_key(ext.type_args)` instead, which answers `()` for every extension in the program. MEASURED on `examples/hello.saw`: `mono.specialized_extensions` held ZERO entries, std's one specialization (`extension Vector<String>`, string.saw:883) sat in `generic_extensions`, `join` was walked onto every `Vector<T>` instantiation, and the type-closure work was 306 (type instance, method) pairs instead of 295 — six of which produced FALSE instance diagnostics at A3's triage (`Vector<Box<any Resumable>?>.join`). The specialized-extension OVERRIDE rule (census M5's second) was inert for the same reason. POSITION MATRIX: `Extension.type_args` is read in exactly three places in `sawc/` — `_build_tables` (this bug), `_roots` (a second reading of the same wrong field, dead because the `type_params` test above it already covers specialized heads; deleted), and `place_uses._ext_self_type` (which FALLS BACK to `type_params` when `type_args` is empty and so is not this shape). FIX: `mono_identity.extension_specialization_key(env, ext)` — the DECLARATION-side twin of `ast_nodes.specialization_key`, one definition both sides call, `is_known_type` behind `IdentityEnv`; codegen's copy becomes a delegator and `BUILTIN_TYPE_NAMES` becomes the funnel's `PRIMITIVE_TYPE_NAMES`. RECORDED, NOT RESOLVED: the typechecker's third copy accepts ENUMS where codegen's does not, so `extension Foo<SomeEnum>` is a specialization to the checker and generic to codegen — a latent DF-190c-shaped divergence with no corpus instance (the tree contains exactly one specialized extension). This line is the record
- ~~DF-284a — the corodiff PRELUDE stopped compiling, so all 2408 pairs refused on both twins and the lane scored them CLEAN~~ **FILED + FIXED Aug 31 (design 218 unit 1.5's agent, stage 0, fix-on-discovery)**: design 234's fallible `Arc(value:)` left the harness's `mk_tag`/`mk_tag_s`/`derive_tag` building a `Tag` out of a `Result<Arc<Res>, AllocError>`, so EVERY generated program refused identically and check 2 exempts exactly that. `corodiff --quick` was green in the battery while testing nothing. MECHANISM (obligation 4): the corpus is GENERATED, so nothing else in the tree ever compiles the shared declarations, and the one oracle that could notice ("both twins refuse") is the one deliberately turned off. Not one-off — it is the SECOND time (commit 2e62f55d, "the corodiff harness survives the rename (its lane had gone dead)", design 219 wave B), and the sibling harnesses do not admit it: sawfuzz mutates the tracked `examples/` corpus, which the suite gates, and irdet compiles that same corpus, so only corodiff owns a corpus nothing else compiles. FIX, both halves in the same commit: `try!` on the three `Arc<Res>(value:)` sites, and a COMPILE FLOOR — `check_prelude` compiles `PRELUDE + func main() { }` before any combo is judged and fails the run outright with the compiler's own output, which is the assertion the refusal exemption was missing. Baselined by the stage-0 `corodiff --all`; this line is the record
## DF-285b — the PRISTINE TEMPLATE STORE is EMPTY in an entry compile, so the
## artifact design 218c T1 hands the monomorphization phase does not exist for
## the library that supplies almost every instance (filed Sep 1 by design 218
## unit 1.5's stage-3 agent; PRE-EXISTING)

MEASURED, `examples/hello.saw`, at the end of the entry module's check:

```
PRISTINE generics               : 0
PRISTINE generic methods        : 0
PRISTINE generic-struct methods : 0
_module_scope_by_file entries   : 1        (the entry file)
registry                        : 111 instances
```

Every one of those 111 instances is a std instantiation — `Vector<Int,
GlobalAllocator>`, `Optional<Box<any Resumable>>`, `Result<…>` — and there is
no template in the store for any of them, nor a home-module scope to check one
in.

MECHANISM (obligation 4). The pristine snapshot is taken by `check_module`, and
`check_module` is run by the ENTRY typechecker over the entry file and the
user modules it imports. std bodies are checked exactly once, by a DIFFERENT
typechecker inside `build_builtin_namespace`, whose result is cached; the entry
compile receives a namespace and an AST, never that typechecker. So the store
spans every module the entry typechecker checks, which is what T1 says, and
that set excludes std, which is where the instances are. `_module_scope_by_file`
is the same fact in its second costume — `_home_module_scope`'s docstring
already records "a std template … falls back to the current scope", which is
the fallback rather than the scope.

NOT ONE-OFF, and the siblings are already in the tree: `_build_fn_mono` returns
False when `pristine is None` with the comment "Cross-module generic template:
not supported for effect re-inference here (design 68 territory)" — i.e. the
existing per-instantiation effect re-inference has never covered a std generic
either, and could not have. This finding is that limitation seen from the
other side, at the moment a stage wanted to depend on the store being complete.

WHAT IT COSTS 218c. §7 stage 3 splices every demanded instance as a CHECKED
concrete declaration and §1c/§4 write that check against a clone of the
PRISTINE template — an artifact captured before any body check mutates an
annotation, which is what §4's "invalidation: none" argument is about. For a
std instance there is no such artifact, so stage 3 has to clone the CHECKED
template out of the merged AST instead. That is viable — probed: 276 of 306
substituted std method clones check clean in the merged namespace — but it is
a different artifact with a different invalidation story, and §4 is written
about the other one. A lead/user correction to T1 and §4, not an
implementation detail. [218c T1/§1c/§4]
## DF-285c — design 218c stage 3's splice-all fails §5's own acceptance test
## before it is built, by ~8x, and the instance check at type-closure
## granularity is not zero-delta (filed Sep 1 by design 218 unit 1.5's
## stage-3 agent)

THE INSTRUMENT is the stage-1 registry, which is what makes the number
measurable for the first time: for every registered type instance, clone each
applicable extension method (the same three rules `_applicable_extensions`
already applies), `substitute_ast_types` it under the instance's binding, and
`_check_method` it. That IS stage 3's per-compile work, run against the
registry the branch already computes.

`examples/hello.saw` — a four-line program; total compile 1.13 s:

```
registry                       111 instances
(type instance, method) pairs  306
deepcopy                       0.76 s
substitute_ast_types           0.08 s
_check_method                  0.09 s
                               ------
TOTAL                          0.94 s   =  +83% on the compile
```

`examples/serde169_derived.saw` (119 instances / 323 pairs) and
`examples/json_value_object_serialize.saw` (119 / 306) both land within a few
percent of the same ABSOLUTE second, because the cost is std's type closure and
every program drags the same one in. So this is ~1 s added to EVERY compile in
the corpus, not a proportion of it. §5's envelope is +10% on suite and
bootstrap wall time; §5 remedy 1 is already applied (the phase runs once per
settled front half), remedy 2 can only remove the 0.09 s check, and remedy 3
plus the design-168 narrowing of the type closure are both unauthorized. §5's
own instruction for exceeding the envelope is that the staging PAUSES for the
lead rather than growing an optimization inside the migration.

THE COST IS `copy.deepcopy`, 81% of the total and 8x the whole budget on its
own. Two constructive directions, neither of them this agent's to choose:
(a) a purpose-built substituting AST copier in place of deepcopy-then-rewrite
— plausibly several times faster, and the one lever that could bring the
splice back toward the envelope; (b) LAZY BODY MATERIALIZATION — the registry
still DECIDES every instance (the unit's thesis is about deciding, not about
when an AST is built), splices eagerly only the instances the coroutine
transform must see, and materializes the rest at design 168's body demand,
which for an executable is a small fraction of 306. (b) preserves "no abstract
body reaches the transform" and costs the `-c` hosted object the full bill,
which is the case §1b already says the registry over-approximates for.

THE SECOND HALF, and the reason the perf number is not the only question. With
the check on at type-closure granularity, hello.saw reports ~30 diagnostics
over std's OWN bodies (276 of 306 clean). Sampled and verified against running
programs, two of the largest classes are diagnostics against CORRECT code:

  * `Vector<String>.copy` — ``type `String` is not Copy; `.copy()` requires a
    trivially-copyable, Copy, or ExplicitCopy type``, while
    `Vector<String>().copy()` compiles and runs today;
  * `Vector<Item>.push` for an `@synthesize`d ExplicitCopy `Item` — ``cannot
    copy value of type `Item` which implements ExplicitCopy``, while the same
    program compiles and prints its element.

Both are the abstract judgment failing to survive substitution — §3's "a rule
that should migrate up" class, one per rule, each owing a ruling. §7 stage 2's
gate rule ("any new diagnostic is a triaged finding … kept and pinned, or moved
to the skip list with the lead's sign-off") applies to every one of them, and
the per-program floor is ~30 before the corpus is considered. The count is
approximate — the probe checks in the merged namespace without
`current_type_params` — but its floor is not: two verified false positives are
two rules the §1c list does not yet name. [218c §1c/§3/§5/§7]
## ~~DF-284c — a trait REQUIREMENT has no callable method on a PRIMITIVE
## receiver, so a bound-resolved call stops resolving the moment the type
## argument is concrete~~ (filed Sep 1 by design 218 unit 1.5 stage 2, the
## first thing ever to look at an instance's diagnostics; PRE-EXISTING)
## **CLOSED Sep 1 by the minimal unit-3 slice the USER RULED forward into 1.5**
## — `_builtin_requirement_call` (typechecker/expressions.py) stamps the SAME
## `comparison_dispatch` design 239 built for the bound, so a concrete receiver
## lowers through `_emit_equals`/`_emit_compare`, the emitters `==` and `<`
## already use. No symbol is minted and no body moves, which is what makes
## behavioural identity a property of the code rather than a claim.
## EVIDENCE: the four formerly-refused corpus tests pass with the flip on —
## `unsigned_comparable_compare`, `unsigned_ordered_comparison`,
## `unsigned_handle_ordering`, `comparison_requirement_call_through_bound` —
## and `examples/comparison_requirement_concrete_receiver.saw` puts the
## operator, the requirement and the bound side by side at design 252's own
## boundary values (255 vs 127 at `UInt8`, `UInt.max` vs 1), where a signed
## lowering answers wrongly; all three columns agree. Full suite 2320 passed /
## 8 xfailed, freestanding 33 both arches, bench checksums unmoved.
## **SCOPE CORRECTION, USER-RATIFIED Sep 1.** The ruling
## scoped the slice to "the integer family, Float, Bool", which is what THIS
## entry's original matrix probed. Two of the four blocked tests walked past
## that fence, so the set is a PREDICATE — "the conformance has no callable
## method here" — and it has three members, each probed: primitives and any
## distinct ALIAS over one (`type_satisfies_bound` resolves aliases — design
## 252's lesson restated); `@synthesize`d ENUM conformances, derived by
## `_emit_enum_compare` and equally method-less (a `@synthesize`d STRUCT is
## NOT — it gets a real method and never reaches the arm); and `String`, the
## one member that HAS a same-named method, whose `equals`/`compare` take
## `other` BY VALUE and are therefore a different function from the
## requirement. String's own API is untouched at every spelling that works
## today: the arm requires the `&`, so `s.equals(t)` still resolves to
## String's method. `hash` is deliberately NOT in the slice — it has the same
## shape but is not part of the blocker (`k.hash(&var h)` through a
## `T: Hashable` bound compiles AND lowers at a primitive today, probed), so
## it stays with the rest of unit 3. Reversing the widening is one predicate.
## Kept below as the record.

```saw
let a: Int = 3
let b: Int = 9
a.compare(&b)            // error: type `Int` has no method `compare`
                         // hint: available methods: abs, clamp, is_even, …
a.equals(&b)             // error: type `Int` has no method `equals`
```

THE MATRIX, probed cell by cell (`.build/scratch/spec218c/p11_matrix.saw`):
`equals`, `compare` and `hash` are ALL missing on `Int`, `UInt8`, `Float` and
`Bool` — and by the same mechanism on every other fixed-width integer.
`String` is the exception and has them, because they are its OWN API rather
than a conformance (design 239 records that asymmetry deliberately). A USER
type is unaffected in both spellings: a hand-written conformance has a real
method, and a `@synthesize`d one has a synthesized real method, so
`p.equals(&q)` compiles on a concrete receiver.

MECHANISM (obligation 4): a primitive conforms to Equatable/Comparable/
Hashable BUILTIN, and the bodies for those conformances are synthesized in
CODEGEN (`_emit_equals` / `_emit_compare`) with no AST call node and no
checker-visible method — design 218's own charter names this as one of the
three shapes it exists to end ("Codegen decides"). The ABSTRACT path never
notices, because `<T: Comparable>` resolves the call against the TRAIT's
requirement signature rather than against the receiver; the concrete path has
only the receiver. So the gap is invisible in every position except one: a
generic body whose bound-resolved call is re-checked with the type argument
substituted in.

WHY IT SURFACED NOW. Design 218 unit 1.5 stage 2 makes a monomorphized
instance's diagnostics real (they were deleted, unread, by four sites in
effects.py). The instance clone has no type parameters and therefore no
bounds, so `rank<T: Comparable>`'s `a.compare(&b)` at `T = UInt8` is refused —
in a program that compiles and runs correctly today, because codegen supplies
the body the checker cannot see. FOUR corpus tests are exactly this:
`unsigned_comparable_compare`, `unsigned_ordered_comparison`,
`unsigned_handle_ordering`, `comparison_requirement_call_through_bound`.

NOT 1.5's TO FIX, and the reason is a SEQUENCING fact worth having: moving
those bodies out of codegen and into checked AST synthesis IS design 218 unit
3 in its own words ("`a > b` becomes `a.compare(b)` as an AST rewrite BEFORE
checking … Memberwise/enum/tuple equality synthesis moves from codegen
emitters to synthesized AST bodies checked like any `@synthesize` output").
1.5's instance check needs unit 3's desugar underneath it — the brief ordered
1.5 before 3 because 1.5 "defines the validated form", and this is the one
place that ordering costs something.

STATUS: stage 2's machinery is BUILT AND LANDED — the four deletion sites are
gone, §3's attribution note is attached, the §1c provenance skips are named
per rule — with the last step held behind `INSTANCE_ERRORS_ARE_REAL` in
typechecker/core.py, a module constant whose comment names this finding.
Flipping it to True is stage 2's landing, and it is a one-line change once
this closes. Held rather than pinned: an XFAIL here would be a brief xfailing
breakage IT introduced, which the policy forbids. [218, 218c §1c/§3, 239]

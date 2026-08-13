# Design 218 — enforcement architecture: the compiler obeys its own unsafe contract

**Status: RULED (user, Aug 13 2026), staged, not yet dispatched.** Unit 0 is
dispatchable now; units 1-2 are the core migration; units 3-4 close the codegen
half; unit 5 is future work gated on measurement. The ruling this brief
records, in the user's framing: *all transforms happen before codegen; the
transforms use unsafe machinery that is manually verified to be safe rather
than generating unsafe code directly — the same contract Saw imposes on all
Saw code; the typechecker's checks then validate the generated transformations
and rely on the uncheckable unsafe core to work as expected.*

## The problem this closes (evidence, Aug 13)

One day of obligation-4 sweeps produced nine findings (DF-216a/b/c, DF-217a-i
minus the redraws) and every soundness-class member fits ONE shape: **the
language's semantics are enforced in one phase but decided in three.** The
typechecker owns the rules; two producers downstream of it create behavior
that never passes back through them:

- **Codegen decides.** `==`/`!=`/`<`/`>`/`<=`/`>=` on user conformances are
  synthesized directly in codegen (`_emit_equals`/`_emit_compare` and their
  memberwise/enum/tuple recursion) with no AST call node — so
  `_check_value_transfer` never sees the operand, which is the whole DF-216b
  matrix (eight positions and counting: C12 found the ImplicitCopy
  over-release after the stopgap landed).
- **The transform exits the checkable language.** The coro transform lowers
  ownership-tracked locals into `UnsafePointer`-typed frame fields, where
  ownership tracking stops BY DESIGN. Exactly-once release is then enforced by
  hand bookkeeping (`__release` synthesis, `forgets`, `read_policy` calls) that
  the post-transform re-check structurally cannot police. That is the entire
  DF-217 frame family (a/b/c/h), and DF-206f/210a/b/f before it.
- **The re-check is coarsely weakened.** `post_transform=True` is one bool
  exempting several unrelated gates (hidden-alloc, prelude, a closure-scope
  rule; core.py:570, 1297-1301, statements.py:2025). Each exemption is
  individually justified; nothing stops a new gate from being swept in
  unaudited.

The pipeline is NOT the problem. It already runs transform → full re-check
(recursive `_prepare_codegen` re-entry, design 192's wrapping) — the right
skeleton. What is missing is that the transforms' OUTPUT is not ordinary safe
Saw, so the re-check cannot hold it to the ordinary rules.

## The architecture (three named layers, each with a trust story)

1. **The typechecker verifies ownership of generated code.** Transform output
   is ordinary safe Saw; moves, exclusivity, and copy tiers apply to it with
   no exemptions. The DF-217 class becomes compile errors in generated code.
2. **A small verified-unsafe core carries what the checker cannot see.** The
   frame primitive module (unit 1): `Slot<T>` and friends, ~hundreds of lines,
   manually verified once, conformance-rowed, never regenerated. This is
   design 130's contract applied to ourselves: unsafety is DECLARED in small
   named units; a safe signature must be sound for every input. Precedent:
   the runtime is already Saw behind the frozen `__saw_rt_*` seam (113/117),
   and sosrt extends it — this adds one more consumer of the same trust shape.
3. **Testing oracles carry control-flow equivalence.** Ownership checking does
   not cover resume-point correctness, ANF evaluation order, suspend-across-
   borrow scheduling, or closure scope construction (the DF-216a family).
   Those keep the differential twin-parity lane (unit 0) and conformance rows.
   Calibration matters: this brief converts the OWNERSHIP class into checked
   territory; it does not promise the control-flow class away.

## Units

**Unit 0 — the differential lane lands FIRST (independent, dispatchable now).**
Promote the coro differential harness (`.build/scratch/coro_diff/gen.py`,
Aug 13: 336 twin pairs, 672 programs, found DF-217f/g/h) to `devtools/corodiff/`
with a `tools/battery.sh` stage. Twin-parity (suspending vs non-suspending:
diagnostics, stdout incl. deinit counts, exit codes) becomes a standing gate.
This is the net under every later unit; the migration does not start until it
is a battery lane. Close the harness's own named gaps as part of the port:
ImplicitCopy leak witnessing, the match-arm-retain axis, non-main contexts.

**Unit 1 — the frame primitive module (the verified-unsafe core).**
FIRST a census: enumerate every store/read/release/temp shape the transform
emits today (`_store_binding_in_slot`, `_slot_store_consumes`,
`_optbind_dispatch` forgets, `_hoist_temps`, `_materialize_closure_captures`,
the `__release` synthesis) — the API is designed against that list, not
invented. Expected surface: `Slot<T>` with `put(&var self, v: T)` (consumes),
`take(&var self) -> T` (moves out, empties), place-style read accessors, and a
deinit that drops the payload iff occupied — occupancy as an Optional-like
tag, exactly-once release a property of the TYPE. Compiler-internal std
module; verification story = conformance rows + Guard Malloc tests + the
design-130 review bar (this module is the one place "manually verified" is
load-bearing). PERF RULING (user, Aug 13): the tag cost is ACCEPTED for the
migration; no unchecked variant until measurement demands one, and any such
variant is itself a named unsafe primitive used only where the transform can
cite the invariant.

**Unit 2 — the transform emits safe code over the core.**
Migrate the coro transform's generated stores/reads/releases to `Slot` ops,
staged (bindings, then hoisted temps, then closure envs), each stage gated by
unit 0's lane plus the full battery. The synthesized `__release` machinery
retires in favor of the frame struct's ordinary structural deinit. As each
generated construct becomes ordinary safe code, the corresponding
`post_transform` exemption is REMOVED — split the bool into named per-gate
exemptions first, then delete them one by one, each deletion its own commit
with the newly-applicable gate green. Exit criterion: the re-check runs the
transfer/exclusivity rules over transformed output with zero ownership
exemptions, and the DF-217a/b/h reproducer shapes are compile-time-impossible
to regenerate (a conformance row asserts each).

**Unit 3 — comparisons desugar at the AST (coordinates with the `other: &Self`
brief).** `a > b` becomes `a.compare(b)` (and `==` family likewise) as an AST
rewrite BEFORE checking, so the transfer checkpoint judges the real call and
the DF-216b stopgap's parallel rule can retire. Memberwise/enum/tuple equality
synthesis moves from codegen emitters to synthesized AST bodies checked like
any `@synthesize` output. Sequencing: land with or after `&Self`, since that
signature change rewrites the same lowering and doing them together avoids
migrating the by-value form only to delete it.

**Unit 4 — the decides-vs-lowers census (completeness check).**
Audit codegen for every remaining `_emit_*` that DECIDES semantics rather than
lowering checked AST (optionals machinery is the first suspect after
comparisons). Each finding either migrates up into a transform/desugar or gets
a documented justification in a standing ledger — the codegen twin of rt/ABI.md:
what codegen is allowed to know about the language, frozen and reviewable.

**Unit 5 — FUTURE, gated on measurement: checked `Slot` elision.**
Occupancy in a coroutine frame is a function of the resume index — today's
hand-written `__release` already encodes exactly that. So the optimized form
is not new machinery; it is the CURRENT pattern re-derived as a proved
refinement of the `Slot` model: a late codegen/IR pass proves per-frame that
tag state = f(resume index) (statically decidable where generated resume
bodies are straight-line about their put/take sites), then drops the tags and
keys teardown on the index. Where the proof does not discharge, the tag stays
— no unchecked mode exists to misuse. Unit 0's lane extends to model-vs-elided
twin parity. Do not start this unit without a measured regression attributable
to the tags (perf-via-measurement policy).

## Obligations mapping (design 190)

- Obligation 1: `Slot<T>` IS the funnel for frame ownership — the entry-point
  list problem (DF-217c's unfunneled `.copy()`) dissolves because there is no
  second way to touch a slot. Unit 4's ledger is the funnel for codegen
  knowledge.
- Obligation 2: unit 2 is a behavioral-contract flip for anything reading
  transform output (irdet determinism, gmgate, frame-layout dumps,
  `--emit-frame-layout` consumers) — the consumer sweep is owed per stage.
- Obligation 3: units 1 and 2 write their conformance rows first (the
  DF-217a/b/h impossibility rows, the Slot exactly-once rows).

## What stays trusted (the explicit list)

The `Slot` implementation and any unit-5 unchecked variant; the executor and
reactor (already Saw, already seam-frozen); the state-machine resume dispatch;
`rt/shim.c`'s three bodies; `sos/rt/common_c/support.c`. Everything else that
is generated must pass the ordinary checks. This list is the brief's most
important artifact — additions to it are design decisions, not implementation
details.

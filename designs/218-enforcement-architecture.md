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

**WHICH FORM THE GUARANTEE VALIDATES (added Aug 13 after sweep S1):** "the
generated code typechecks" must name the form — S1 row p08a proved a generic
COROUTINE's laundering leak passes the post-transform re-check VACUOUSLY,
because the re-check sees only abstract `T` (DF-217i's boundary). So unit 2's
guarantee is stated as: transformed output passes the ownership rules AT THE
FORM THE CHECKER ACTUALLY JUDGES, and the abstract-T gap is closed by the
DF-217i ruling — either post-monomorphization re-judgement (the Send lane,
p03a/c2/d2, is the existence proof that this machinery is built and wired to
frames) or tiered least-permissive body checking (the design-146 place rule
is the diagnostic model; `T: Copy` alone is NOT a sufficient license, S1 row
9d). The 217i ruling therefore lands BEFORE or WITH unit 2, else generic
driven functions remain the soft spot under the new architecture too.

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
PROCESS RULING (user, Aug 13): this is a tricky rewrite, so a FABLE spec agent
documents the exact form FIRST, as `designs/218a-slot-spec.md` — the emission
census (every store/read/release/temp shape the transform emits:
`_store_binding_in_slot`, `_slot_store_consumes`, `_optbind_dispatch` forgets,
`_hoist_temps`, `_materialize_closure_captures`, the `__release` synthesis;
one table row per site, current shape → exact new safe form), the exact
`Slot<T>` signatures with ownership contracts and panic conditions, worked
before/after examples from real transformed programs, the `post_transform`
exemption inventory mapped to the unit-2 stage that retires each, and a
per-bug impossibility argument for DF-217a/b/h (which becomes the conformance
row set). The spec runs AFTER the DF-217 fixes land (their confirmed root
causes are its input), is reviewed by the lead, ruled by the user, and only
then do Opus implementers dispatch against it. The API is designed against
the census, not invented.

**DF-216g folds in here WHOLE (user ruling, Aug 13 — no interim diagnostic):**
a closure naming `self` in a SUSPENDING method ICEs because the capture is
judged pre-transform (where `self` is the receiver) and the rewrite rebinds
`self` to the frame, leaving the receiver behind the `__recv` pointer with no
expressible borrow to capture. The census gets two rows from it: the receiver
borrow-capture (`[&self]` as legal user syntax the transform can also emit —
the deep fix; the transform generates what a user could have written, so the
post-transform re-check validates it as ordinary source), and `__recv` itself
as a primitive-module candidate (today a bare `UnsafePointer` + rewrite
convention whose validity argument lives in a comment). Pin:
`examples/closure_captures_self_suspending.saw`, pre-registered on unit 2's
flip list. Expected surface: `Slot<T>` with `put(&var self, v: T)` (consumes),
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
with the newly-applicable gate green. Exit criterion — THE PIN GATE (user, Aug 13): before this unit dispatches,
every still-open finding the rewrite claims to fix is a cited XFAIL pin
(standard policy: DF-cited reason, minimal repro, EXPECT directives stating
intended behavior), and 218a's impossibility arguments map 1:1 to those pin
FILENAMES — the flip list is pre-registered in the spec, so unit 2 lands by
flipping exactly the pins it promised (XPASS markers removed in the landing;
an unflipped promised pin means a missed case, an unpromised flip means an
unclaimed fix — both are review findings, not silent events). Additionally:
the re-check runs the transfer/exclusivity rules over transformed output with
zero ownership exemptions. Pins the OTHER briefs own flip there instead
(position pins → the 120-matrix fix; C07/C12 → `other: &Self`); a
pin-promotion batch converts every open DF repro out of gitignored
`.build/scratch/` once the current fix wave and sweeps S1/S2 report.

**Unit 1.5 — monomorphization becomes a pre-codegen transform (RULED, user,
Aug 13; sequenced BEFORE unit 2 because it defines the validated form).**
Today monomorphization is codegen-side (`codegen/generics.py`,
`_ensure_monomorphized_*`, lazily during lowering) — the largest single thing
codegen DECIDES, and no judgment ever runs on the instances (the one re-check
that exists, effects.py:500-510, deletes its own errors — it is a
type-stamping device). This unit lifts it into the transform pipeline:
typecheck (abstract — KEPT as the definition-site UX/inference layer) →
monomorphize (demand-driven reachability fixpoint over the AST, replacing
codegen's lazy discovery; the census of every `_ensure_monomorphized_*` call
site is spec material) → instances RE-ENTER the checker with errors REAL →
place/coro transforms then run on CONCRETE ASTs only (deleting the coro
transform's private generic-instance machinery incl. the error-deleting
re-check) → codegen lowers. Closes DF-217i/j/k at the right boundary and
S1 row p08a with them. Known cost: instance-check error attribution (cite
the instantiating call site + definition line; migrate rules into abstract
bound vocabulary over time so the instance check rarely fires) and re-check
cost per instance (cache per (template, type-arg tuple); consider tier-shape
sharing; measure before optimizing). INTERIM STEP, dispatchable ahead of the
full unit: generalize the Send lane (which already re-judges monomorphized
frames with concrete-type diagnostics) to the ownership rules — the fast
DF-217i fix inside the current architecture, so the migration lands as
architecture rather than as an emergency soundness patch.

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

## Self-hosting interaction (user, Aug 13)

Moving semantics out of codegen ENLARGES the pre-codegen surface — which is
exactly the surface the self-hosted compiler's initial phases were planned to
cover (the port was always going to stop before codegen). Both sides of that:

- **The cost:** the self-hosted front-end now owes desugaring, monomorphization
  and the transforms, not just lex/parse/check — more to port before a Saw
  front-end "means anything".
- **The payoff, and it dominates:** every phase 218 moves up is an AST-to-AST
  transformation — pure data in, pure data out — which is the EASIEST kind of
  phase to port and to verify: each ported phase gets a lexdiff/astdiff-style
  parity lane against the Python implementation (the selfhost lexer + lexdiff
  precedent, already in the battery). Codegen, the hardest thing to port,
  stays Python/llvmlite the longest behind a frozen boundary.
- **The concrete deliverable this adds:** the checked, monomorphized,
  transformed AST becomes a DEFINED ARTIFACT — a stable, serializable contract
  (the rt/ABI.md move applied to the compiler's own midpoint). That one
  contract is simultaneously (a) codegen's input spec, which unit 4's ledger
  documents, (b) the self-hosting handoff point — a Saw front-end can feed the
  Python codegen across it during the transition, making the port incremental
  per-phase rather than all-or-nothing, and (c) the differential-testing
  interface each ported phase is validated against. 218 does not compete with
  self-hosting; it defines its milestones.

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

**RULED (user, Aug 13, at 218a review):** the receiver handle is
`UnsafeRef<T>`, an `unsafe struct` in a new PUBLIC `std.compiler.frame`
module (with `Slot<T>`, which stays ordinary safe Saw). Generated resume
methods emit honest `unsafe` declarations instead of riding an exemption;
users who touch an `UnsafeRef` carry the obligation via their own declared
`unsafe` — design 130's contract, applied uniformly to compiler and user
alike. Details + consequences in 218a's RULINGS header.

## What stays trusted (the explicit list)

The `Slot` implementation and any unit-5 unchecked variant; the executor and
reactor (already Saw, already seam-frozen); the state-machine resume dispatch;
`rt/shim.c`'s three bodies; `sos/rt/common_c/support.c`. Everything else that
is generated must pass the ordinary checks. This list is the brief's most
important artifact — additions to it are design decisions, not implementation
details.

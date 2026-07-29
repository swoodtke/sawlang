# Design Brief 44 — Async stage 2a: the source-level coroutine transform

**Source:** D11 decided (source-level, AST-level formulation) + the
no-forced-destroy ruling (paper 18, Jul 29) + paper 18 Axis B′ (the
colorless model) + `designs/43` (probe findings; its stage-2 skeleton
informs this brief). Runtime (executor, suspending primitives,
cancellation surface) is brief 45 — NOT here.
**Scope:** the transform alone, testable without any executor via a
synthetic suspend intrinsic (the brief-22 trick). Functions that do not
suspend compile EXACTLY as before — the transform activates only for
effect-inferred suspending functions.
**Exit criteria:** suspending functions round-trip through the
transform correctly (locals, moves, deinit, nesting per the test
matrix); non-suspending code byte-identical in behavior; full suite
green; zero xfails.

## Governing rules (all decided; do not re-open)
- Colorless: no async/await keywords; suspendability is effect-inferred
  (the design-22/24 graph knows every suspension point).
- No forced destroy: NO per-suspension-point destroy paths. Frames die
  only via their own control flow. The single special case: a
  completed frame's unconsumed result slot (final-state drop).
- D6: references may span suspension points (task confinement); a
  callee frame may hold pointers into its caller's frame.
- Deinit stays a `sync` context (suspension in deinit = compile error —
  should already fall out of the effect check; add the test).

## Design section (settle in-brief, document choices)

**Frame = ordinary Saw-level struct** (synthesized in the compiler's
front-end, compiled by existing machinery): fields = parameters +
locals live across any suspension + state Int + drop-flag Bools (brief
42's flags, now frame-resident) + result slot. `sizeof(Frame)` is
ordinary struct sizeof (the .bss static-frames enabler — not exercised
in this brief, but do nothing that would break it).

**Liveness, v1 = conservative-by-scope:** any local whose lexical scope
spans a suspension point is frame-resident. Correct and simple; larger
frames than optimal. A true live-range analysis is a LATER optimization
— note it, don't build it.

**State machine:** body split at suspension points into states; resume
method dispatches on the state field (ordinary match compiled by
ordinary codegen). Resume signature/protocol: your design — document it
(suggested: `resume(&var frame) -> Poll`-shape where Poll is an enum
{Pending, Done} with the result read from the frame's slot; pick what
composes with brief 45's executor and say why).

**Nested suspending calls: callee frames embedded BY VALUE in the
caller's frame** (the flat-frame composition that makes whole-task
size a compile-time constant — the Embassy enabler). Consequence:
**suspending recursion is a compile error** (detect via a cycle in the
suspending-call graph — the effect machinery has the edges; clear
diagnostic naming the cycle). Direct non-suspending recursion stays
legal as always.

**Cleanup:** normal-path only (the ruling): early returns and
completions inside states run ordinary early-return cleanup (brief 23
machinery) against frame fields. Drop flags for conditional moves
across suspends live in the frame and are consulted by that same
generated cleanup. The frame struct's own Deinit: final-state result
slot only (+ assert states cannot otherwise be dropped mid-flight —
there is no API to do so in this brief).

## Items

### 1. Synthetic suspend intrinsic
`__suspend()` (compiler-known, hosted-test-only): marks a suspension
point, effect-inferred as suspending (wire into the design-22 effect
sources). Under the transform it becomes a state boundary; a test
driver (compiler-known or generated harness) can step a frame:
create → resume → Pending → resume → ... → Done. Keep the driver
surface minimal and clearly test-only; brief 45 replaces it with the
real executor.

### 2. The transform
Front-end pass (post-typecheck, pre-codegen) rewriting each suspending
function per the design section: frame synthesis, state split, local →
frame-field rewriting (body + cleanup + drop flags), resume dispatch.
Non-suspending functions untouched (assert: compile pipeline for a
program with zero suspending functions takes the identical path —
the whole existing suite is that proof).

### 3. Nested calls + recursion diagnostic
Embedded callee frames; the suspending-recursion cycle error with a
test naming the cycle. A D6 test: a suspending method mutating
`&var self` across a suspension (self lives in the caller frame /
task root) — works.

### 4. Test matrix (each with -O0 spot check)
- Locals across suspends: values correct after resume (Int, String —
  refcount balanced, deinit oracle).
- Conditional move across a suspend: moved-on-one-branch → drop flag
  in frame → exactly-once deinit on both paths.
- Early return after resume (cleanup of live frame fields, LIFO).
- Nested suspending calls two deep; values flow through.
- Suspending recursion → compile error.
- Suspension attempt in deinit → compile error (effect check).
- Completed-frame unconsumed result → dropped exactly once
  (final-state Deinit).
- Non-suspending program: entire existing suite green (the transform
  is invisible).

### 5. Docs
LANGUAGE_SPEC.md concurrency section: transform semantics as
observable behavior (what suspends, frame lifetime rules, recursion
restriction). CLAUDE.md bullet. Design 43 annotated "path B adopted,
brief 44".

## Hazards
The biggest transform in the compiler's history: keep it OFF for
non-suspending code by construction, not by luck. The deinit/string/
implicit_copy/exclusivity families are the oracle at every checkpoint.
If the AST-level formulation hits a wall mid-brief (something the
existing machinery cannot express), STOP and report the wall precisely
rather than hacking around it — the fallback design discussion belongs
with the user.

## Report back
The resume-protocol shape chosen and why; the liveness conservatism's
observed frame sizes on the tests; the recursion-cycle diagnostic;
any wall hit (per the hazard note); suite tally; deviations;
non-allowlisted commands.

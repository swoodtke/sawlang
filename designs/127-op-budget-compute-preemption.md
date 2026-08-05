# Design 127 — Op-budget covers pure-compute loops (make the README claim true)

Source: `designs/reviews/2026-08-04-language-design-claims.md`
(DOES-NOT-HOLD #2). User decision Aug 4: fix the runtime/compiler (keep the
claim), rather than soften the README.

## Problem
The design-89 op-count budget only decrements on non-parking I/O-ish ops, so
a spawned task in a pure-compute loop (`while true { n = n + 1 }`) never
yields: the probe prints `spin start / spin end / sibling ran` — the sibling
is starved for the spinner's whole life. The README says the budget "stops a
spinning task from starving the others".

## Approach (pin in implementation, stop-and-record if it fights back)
- The coroutine transform inserts a budget check on LOOP BACKEDGES of every
  spawned task body (`while`/`for`/`loop` desugarings): decrement the
  existing op-budget counter; on exhaustion, yield through the existing
  `yield_now` park path (wake reason 0 = ready — round-robin continues).
- Scope v1: backedges in the task's own (transformed) body and in any
  function the transform already embeds (suspending callees). SYNC callees
  are not instrumented in v1 — a compute loop inside a never-suspending
  helper called from a task stays unpreempted; DOCUMENT this bound
  explicitly in spec + skill ("the budget is checked at loop backedges of
  task bodies and suspending callees").
- A spawned body that today compiles as a straight sync run-to-completion
  frame BECOMES suspending by virtue of the inserted checks — that is the
  point; verify the never-silently-blocks invariants (96/101/104 fence)
  still hold.
- Cost: the check is a decrement + branch on the frame's existing budget
  word. Measure: the suite's timing plus one micro-benchmark noted in the
  commit message (a tight loop's slowdown factor). If the cost is
  embarrassing, gate insertion to loops the typechecker cannot prove finite
  — but ONLY with the measurement recorded first (no speculative cleverness).
- Sleep/io parks already reset the budget (design 89) — keep that behavior;
  yield-on-exhaustion resets it too.

## Tests
- The review's starvation probe becomes the regression test: spinner +
  sibling in one ST group — sibling output interleaves before the spinner
  finishes (bound the spinner so the test terminates).
- MT (`threads: N`) variant keeps working (budget yield must not confuse the
  worker claim protocol).
- A `for` over a Vector and a `while` with a suspending body keep exact
  iteration counts (the check must not perturb loop semantics).

## Docs
Spec + skill: budget section gains the backedge rule + the sync-callee
bound. README: claim stands as written once this lands.

## Exit criteria
Starvation test green; suite + bootstrap + sos green; measured overhead
recorded; tracker RC-3 closed.

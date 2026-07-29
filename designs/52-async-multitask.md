# Design Brief 52 — Async stage 2c: CFG split + the multi-task runtime

**Source:** the brief-45 deferred items (A1b), now unblocked by design
51 (`any Trait` — the type-erased run queue), plus A1a (suspension in
nested control flow), which MUST land first: the runtime tests
(producer loops) require suspending inside loops. Governing rules
unchanged: paper 18 (structured concurrency C1, explicit-only
cancellation, NO forced destroy), designs 44/45 (frame + resume +
__Poll + __wake protocol).

## Part 0 — CFG-based suspension split (A1a)
Lift brief-45's honest rejection: suspensions inside `while`/`for`/
`if`/`match` bodies. Mechanism: extend the state split from
top-level-statement granularity to a CFG walk — loop back-edges and
branch merges become state transitions (the state field encodes the
resume point INSIDE the construct; loop-carried locals are already
frame-resident under conservative-by-scope liveness). Keep the same
frame/optional-encoding cleanup machinery. Tests: suspend in while
body (counted iterations across resumes); suspend in for-over-range;
suspend in one branch of if (both paths); suspend in a match arm;
nested loop+if suspend; the existing rejection test flips to a
passing test. -O0 spot checks.

## Part 1 — the multi-task runtime (brief-45 items 2/3/4/5 on `any`)
- **`Resumable` erasure:** frames conform (compiler-synthesized) to a
  builtin trait with the resume/__wake surface; the run queue is
  `Vector<Box<any Resumable>>` (or equivalent erased handle) — design
  51's machinery, no new erasure code. Report the exact trait shape.
- **Cooperative spawn:** spawning a suspending function/closure →
  heap frame (`Box<any Resumable>` via Global) + `TaskHandle<T>`;
  result delivery through the frame's __result slot on Done.
- **Structured join (C1):** scope exit joins spawned children
  (runs the executor until each completes); `spawn_detached` NOT in
  this brief.
- **Cancellation surface:** `cancel()` sets a frame flag;
  `cancelled() -> Bool` reads it inside the task; cancellation-aware
  waits return through normal control flow. NO forced destroy — the
  no-forced-destroy ruling is load-bearing; the only frame drop is
  after Done (unconsumed result, already handled).
- **Suspending Channel.receive** + cancellation-aware
  `receive_or_cancelled() -> T?` variant (spelling yours; must return
  through normal control flow). The 21b thread engine stays untouched
  and coexisting.
- **Executor:** extend the brief-45 single-task entry executor to the
  run queue: round-robin over ready tasks; honor __wake reasons
  (yield = requeue; sleep = time-ordered wake, simplest correct;
  channel-wait = wake on send). Single-threaded, hosted. Do not
  preclude the freestanding static-task variant (no allocation inside
  the executor core beyond spawn itself).
- **Tests:** two tasks deterministically interleaving via yield;
  sleep ordering across tasks; producer/consumer over suspending
  channel (requires Part 0); cooperative cancel observed at a check
  AND at a cancellation-aware receive, cleanup verified by deinit
  oracle; structured join at scope exit (parent waits); suspending
  main spawning tasks. -O0 spot checks on lifetime tests.
- **Docs:** LANGUAGE_SPEC concurrency section rewritten to the shipped
  model (spawn/join/cancel/channel, the two-engine coexistence);
  CLAUDE.md.

## Hazards
Part 0 is transform surgery — the entire coro_* test family plus the
deinit oracle at every checkpoint; if the CFG walk hits a genuinely
unsplittable construct, reject honestly and report (the 44/45
discipline). Part 1: frame lifetimes now cross scopes via the queue —
the Box-erased teardown (51) is the safety net; every cancel/join path
gets a deinit-oracle test. Full suite per commit; zero xfails end
state.

## Report back
Part 0: the CFG state-encoding chosen; which constructs lifted vs
rejected. Part 1: the Resumable trait shape; spawn/join/cancel
mechanisms; executor wake handling; whether the 44/45 protocol needed
further extension. Suite tally; deviations; non-allowlisted commands.

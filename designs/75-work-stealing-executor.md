# Design 75 — A2: multi-threaded work-stealing executor + Send-on-frames (queued Jul 31)

**Status (Jul 31): LANDED.** `TaskGroup(threads: N)` (N>=2) runs N OS worker
threads over a SINGLE mutex-protected shared run queue (the sanctioned "one
injector + N workers" — deliberately NOT per-worker lock-free deques; simplicity
and soundness over throughput v1). Model = fork-join: a drain is triggered lazily
by `join()`/`Deinit`, spawns N workers (via the 21b engine, passing the group's
address as a `Send` `Int`), each of which claims a runnable frame under the lock,
`resume()`s it OUTSIDE the lock, and records the outcome; the drain joins all
workers (a full barrier making every `__result` visible). D6 confinement holds via
a per-task `active` flag (one worker per frame) and a size-stable queue during a
drain (enqueue is main-thread-only). The Send-on-frames gate rejects the first
non-Send value a spawned frame carries across a suspension (params + across-suspend
locals + embedded callee sub-frames + the result type), anchored + named; the
default `TaskGroup()`/`threads: 1` skip the gate and stay byte-identical. Shared
earliest-deadline timer under the lock; cross-task cancellation via
`TaskHandle.cancel_addr() -> Int`. Constrained/deviations (documented): mt-ness is
tracked on the group's binding (spawn into it directly for the gate); a `spawn { }`
with a Void body ICEs pre-existing (workers return a dummy Int); no per-worker
deques or work-stealing-proper (single injector). Battery of 7 deterministic,
time-bounded tests (`taskgroup_threads_*`, each verified stable 30-50x). Suite 818,
bootstrap 17+17, libs 4+4.

---


Stage 3 of the async plan (paper 18 — read it first; the model there
is decided). The cooperative TaskGroup gains an OPT-IN multi-threaded
mode; the single-threaded default stays exactly as-is.

## Pinned shape (orchestrator; user may veto)
- `TaskGroup(threads: N)` (labeled-arg overload/default param; N=1 ≡
  today's group, byte-identical path). N worker threads run a
  work-stealing deque of `Box<any Resumable>` frames.
- **Send gate:** a frame crossing to another thread must be Send —
  every across-suspend live value in the frame must be Send
  (structural check at spawn of a multi-threaded group; diagnostic
  names the non-Send value and its type). Single-threaded groups skip
  the gate (unchanged).
- Structured join unchanged: group Deinit drains ALL workers to
  completion; cancellation words become atomic; sleep wakeups use the
  earliest-deadline discipline across workers (a simple shared
  timer heap is fine v1 — no per-worker timer wheels).
- Steal discipline: per-worker deque, owner pops LIFO, thieves steal
  FIFO; a parked worker wakes on new work or earliest deadline.
  Simplicity over throughput v1 — one mutex-protected injector +
  per-worker deques is acceptable if lock-free deques are
  disproportionate (report the choice).
- Channel interaction: cooperative `receive` works from any worker
  (channel is already Send/Sync); channel-yield wake reason honored.
- NO task migration guarantees beyond Send-correctness; `&var self`
  driven methods stay task-confined (paper 18's D6 confinement model
  — a frame runs on one thread AT A TIME; stealing moves frames only
  BETWEEN suspensions).

## Scope
1. Send-on-frames structural check + diagnostics + tests (non-Send
   capture rejected with names; Send closure/Arc/channel accepted).
2. Executor: workers, deques, injector, parking, timer heap;
   group(threads: N) surface; Deinit drain.
3. Exactly-once + soundness battery: N-thread producer/consumer via
   receive; sleep ordering across workers; cancellation from another
   task; frame deinit exactly-once under stealing (Deinit-count);
   stress test (many tiny tasks) run with a bounded time budget.
4. Docs: spec concurrency (threads: N, Send gate, confinement),
   saw-lang skill, tracker (A2 closed, design 75 landed).

Escape hatch: if frame-stealing soundness cannot be established for
some shape, constrain it (e.g. steal only never-started frames) and
document precisely — honest subset over subtle races. Bars: full
suite + blade/libs + bootstrap green per commit; zero xfails. The
taskgroup_*/channel_*/coro_* families are the oracle. Standing policy
applies.

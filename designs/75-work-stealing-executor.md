# Design 75 — A2: multi-threaded work-stealing executor + Send-on-frames (queued Jul 31)

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

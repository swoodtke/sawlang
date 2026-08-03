# Design 103 — A6 runtime offload: `extern blocking` calls run in tasks (queued Aug 2)

Final pre-SOS batch, part 2 of 6. The biggest item: make a blocking
FFI call actually RUN inside a driven/spawned task instead of being
rejected. The worked-out design is already ledgered in the tracker
(design-76 A6 remainder) — follow it; deviations get a tracker flag.

## As ledgered
C shims (hosted-only, codegen/core.py runtime):
`saw_offload_start(fnptr, arg) -> job` (spawns a thread that runs the
extern, stores the result, writes a byte to the job's pipe),
`saw_offload_pipe_fd(job)` (the readable fd), `saw_offload_done(job)`,
`saw_offload_take(job)` (result + free). Coro lowering: a blocking-
extern call site inside a suspending context becomes start → io_wait
(pipe fd, read) → take — i.e. the task PARKS on the job's pipe like
any socket read; the reactor wakes it when the thread finishes. All
existing infra (io_wait, precise wakeup tokens, budget reset-on-park)
applies unchanged.

## Scope
1. The shims (thread-per-call is acceptable v1 — flag pooling as
   future work; result marshalling per the extern's C ABI whitelist).
2. The lowering at blocking-extern call sites inside suspending
   bodies (driven + spawned, both group kinds); the `sync`-context
   rejection and the freestanding rejection STAY (they are correct).
3. FIX THE ANCHOR (the flagged diagnostic): any remaining rejection
   must name the USER call site, not `__Frame_*.resume`.
4. Blocking extern args/returns: enforce the design-58 C-ABI
   whitelist at the boundary (already enforced for externs generally
   — verify it holds through the offload path; the arg must outlive
   the call — a moved-in owned arg is held by the job until take).
5. Tests: a real blocking libc call (e.g. a `read(2)` on a pipe fed
   after a delay by a sibling task, or `usleep` via a shim) inside a
   spawned task — siblings keep running while it blocks (the
   acceptance: interleave proof, time-bounded); result round-trips;
   cancellation of a task parked on an offload job (compose with
   design 102 item 2 if landed — else observe-at-park semantics);
   sync/freestanding rejections stay green with user-anchored
   messages.
6. Docs: skill + spec (`extern blocking` now RUNS; the pending-pool
   caveat replaced), tracker (A6 closed).

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit. Standing policy; foreground suites; watchdog; interruption-
safe; saw-lang skill self-review. HAZARD: threads + the cooperative
reactor — keep the reactor single-owner (the offload thread touches
ONLY its job + pipe write; all wake routing stays in the reactor).

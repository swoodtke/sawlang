# Design 76 — A4 IO reactor + A6 blocking offload + A3 remainder (queued Jul 31)

Read paper 18 first — the models are decided there: **poller-only v1
reactor** (kqueue on macOS / epoll on Linux; never-block invariant:
the executor thread never blocks in a syscall while runnable frames
exist), and **`extern blocking` offload** (hosted thread pool for
calls that must block). A9 actors: DROPPED from the roadmap (user,
Jul 31) — remove from tracker.

## Scope
1. **A4 reactor (v1):** a per-group (or per-executor) poller owning
   registered fds. Cooperative `read`/`write`/`accept` on a new
   nonblocking socket/pipe surface (minimal std.net or std.io
   additions — SMALLEST useful surface: TCP listen/accept/connect,
   read, write; pin names to the existing std style and report) —
   would-block registers the fd + parks the frame (new wake reason:
   io-ready); the executor polls when no frame is runnable (never
   busy-waits: poll timeout = earliest sleep deadline). Works in
   single-threaded groups first; multi-threaded (design 75) waking is
   the injector's problem — one poller thread or poll-on-idle-worker,
   simplest sound choice, report it.
2. **A6 `extern blocking`:** an extern fn may be declared `blocking`;
   calling it from a task offloads to a small hosted thread pool and
   suspends the frame until completion (wake reason: offload-done).
   Effects: a blocking call is a suspend point (not legal in `sync`).
   Freestanding: `blocking` externs are rejected (no pool).
3. **A3 remainder:** cancellation observed at the new suspension
   points (a parked-on-io/offloaded frame whose task is cancelled
   wakes and observes `cancelled()` at resume — cooperative, no
   forced destroy, unchanged philosophy). Verify + tests; close A3.
4. Tests: echo round-trip over a local socketpair/loopback within a
   TaskGroup (single- and multi-threaded); would-block park/wake;
   two tasks io+sleep interleaving; blocking-extern offload (a
   deliberate slow C call) with concurrency observed; cancellation
   during io-park and during offload; never-block invariant probe
   (sleep deadline honored while an fd is idle). NO external network
   in tests (loopback/socketpair only).
5. Docs: spec (reactor model, blocking externs, cancellation points),
   saw-lang skill (io + blocking gotchas), tracker (A4/A6/A3 closed,
   A9 dropped, design 76 landed).

Escape hatch per part: land the honest subset with precise
diagnostics; re-ledger remainders with analysis. Bars: full suite +
blade/libs + bootstrap green per commit; zero xfails. Standing policy
applies.

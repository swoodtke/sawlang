# Design 91 — Precise reactor wakeup (not wake-all) (queued Aug 1)

The design-76 reactor wakes ALL io-parked frames on ANY readiness
event (coarse level-triggered retry); each op re-verifies its own fd
and re-parks on a spurious wake. Two problems: O(N) thundering herd
per event, and correctness depends on EVERY op defensively
re-verifying — the trap `connect` fell into (design 90). Route
wakeups precisely instead. Land AFTER design 89-b (it touches the
reactor↔executor seam 89-b rewrites).

## The fix
- kqueue/epoll events already carry a USER-DATA pointer
  (`kevent.udata` / `epoll_data.ptr`). Register each `io_wait(fd, dir)`
  with the PARKED FRAME'S wake-word address (or a small park-record
  address) as that udata.
- On a readiness event, the reactor wakes EXACTLY the frame(s)
  registered for that (fd, direction) — O(1) per event, no herd.
- A woken frame IS ready → the defensive re-verify loops in
  read/write/accept/connect become belt-and-suspenders (keep them —
  harmless and robust — but they are no longer load-bearing).
- Preserve: never-block invariant, earliest-deadline poll timeout,
  the design-90 connect correctness, level-vs-edge posture (document
  which the precise scheme uses; if switching to one-shot per park,
  ensure re-park re-registers).
- fd-number reuse across connection turnover: the park-record/udata
  must be per-PARK, not per-fd-number, so a reused fd number can't
  route a wake to a stale record (design-90 fd-reuse tests stay
  green).

## Scope
1. Reactor register/poll seam: carry the park-record pointer as udata;
   deliver wakeups to exactly the registered frame(s). Handle the
   many-frames-one-fd case (unusual, but define: e.g. two frames
   waiting different directions on one fd).
2. Executor integration: the reactor sets the specific frame's
   io-ready word / enqueues exactly it — coordinate with design-89b's
   shared queue (that's why this is after 89-b).
3. Tests: precise wakeup (a parked reader on fd A is NOT woken by fd
   B's event — assert via a counter that only the right frame
   progresses); the design-90 multi-connection + fd-reuse suite stays
   green; a many-parked-frames stress (N readers on N fds, each fired
   individually, only the fired one wakes) — deterministic, time-
   bounded.
4. Docs: spec concurrency reactor note (precise wakeup); tracker
   (design 91 landed; wake-all retired).

Bars: full suite (baseline = post-89b) + blade/libs + bootstrap green
per commit; zero xfails. Standing policy; interruption-safe; saw-lang
skill self-review.

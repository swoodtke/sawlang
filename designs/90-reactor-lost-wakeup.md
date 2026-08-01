# Design 90 — Reactor lost-wakeup on the 2nd sequential connection (queued Aug 1)

Design-76 reactor bug, isolated by design 89's investigation. It
independently gates any multi-connection server (accept → serve →
accept → serve …), separate from the executor split. Fix FIRST so the
design-89-b executor-unification acceptance isn't blocked by it.

## Repro / symptom
`.build/scratch/probe_loopdiag.saw` (kept by design 89): a server task
serves N=2 connections sequentially with 2 clients in ONE group (a
shape the CURRENT per-group executor already co-schedules, so this is
NOT the executor gap). It accepts conn#0, serves it fully, accepts
conn#1 — then the **read on the 2nd connection never wakes** (markers
reach 911, never 921); the program hangs. A SINGLE accept+read+write
round-trip works (`net_accept_roundtrip`). So the fault is the second
io-park on a freshly-accepted fd not being delivered a wakeup.

## Investigation direction (verify, don't assume)
The design-76 reactor is one-shot-register (EV_ONESHOT / EPOLLONESHOT)
+ wake-all-io-parked. Likely suspects:
- a fd registered ONCE stays de-registered after its first oneshot
  fire, so the SECOND io_wait on the same/parallel fd never
  re-registers (or re-registers but a stale registration masks it);
- the wake-all pass clearing/parking the wrong frame's io-ready word
  on the second park;
- the newly-accepted conn#1 fd colliding in the reactor's fd→frame
  map with conn#0's closed fd (fd number reuse) so the wakeup routes
  to a dead entry;
- the poll timeout / earliest-deadline recompute skipping a re-poll
  after the first connection's completion.
Instrument with the repro (run under a watchdog — macOS has no
`timeout`; background+sleep+kill). Pin the exact mechanism.

## Scope
1. Root-cause + fix so an arbitrary SEQUENCE of io-parks across
   multiple accepted fds each get their wakeup (register/one-shot/
   fd-map/wake discipline correct across connection turnover incl. fd
   reuse). Keep the never-block invariant + earliest-deadline poll.
2. Tests (deterministic, socketpair/loopback, time-bounded — the
   design-86 runner timeout catches a regression as a failure not a
   wedge): a server task serving N=2 then N=3 sequential connections
   (each read+write round-trips, assert contents); fd-reuse across
   connections (close conn#0, accept conn#1 that reuses the fd number,
   its read wakes); two concurrent parked reads on different fds both
   wake. Keep net_*/coro_*/taskgroup_* green.
3. Docs: saw-lang skill (if it carried a multi-connection caveat,
   remove); tracker (design 90 landed; the design-89 flagged reactor
   lost-wakeup closed; note it unblocks the 89-b acceptance).

Bars: full suite (baseline 884) + blade/libs + bootstrap green per
commit; zero xfails. Standing policy; interruption-safe commits;
saw-lang skill self-review.

# Design 85 — Runtime hang: second nested suspend after first parks (queued Jul 31)

Pre-existing coroutine/executor bug (confirmed NOT design-84:
reproduces on the prior tree with plain suspending FREE functions).
It's the last thing between the safe net API and a working echo/httpd
at RUNTIME (the design-84 net API compiles and single-round-trips,
but a real read-then-write worker hangs).

## Characterization (from design 84's investigation)
- A spawned TaskGroup worker whose body makes a nested suspending
  call that PARKS on io_wait, and THEN makes a SECOND nested
  suspending call, HANGS at runtime.
- WORKS: two nested calls where neither parks; two `yield_now` nested
  calls; a SINGLE nested (parking) call per worker (`net_owning_echo`
  is reliable 5/5 on exactly this boundary).
- FAILS: first-parks-then-second-call, under the TaskGroup executor +
  reactor. The reactor itself is fine (raw inline echo works). The
  fault is the transform's sub-frame drive across a worker RE-ENTRY:
  after the executor re-enters the worker frame post-wake, the second
  nested sub-frame is mis-driven / the wake state is lost.
- Repro: `.build/scratch/probe_freefn.saw` (two free-fn suspending
  calls in `server`, first parks on io_wait; socketpair). Hangs.

## Scope
1. Root-cause with the repro: instrument the resume() state machine +
   the executor re-entry path. Likely suspects (verify, don't
   assume): the `__state`/`__wake` word not advancing (or being
   reset) when the FIRST sub-frame completes and control should move
   to the SECOND nested call; the embedded sub-frame's own
   `__state` not distinguished from the parent's on re-entry; or the
   reactor wake delivering to the parent frame but the parent
   resuming into the wrong resume-point. Pin which.
2. Fix so an arbitrary SEQUENCE of nested suspending calls (each
   possibly parking) in one driven/spawned body drives correctly:
   park → wake → complete sub-frame 1 → enter sub-frame 2 → park →
   wake → ... → return. Both free-fn and METHOD nested calls (design
   84 added method embedding — cover both).
3. Tests (deterministic, socketpair/loopback, time-bounded via the
   existing net test harness pattern):
   - the reduced repro: worker does read_n (parks) THEN write (parks),
     round-trips a byte, exact result.
   - a TRUE echo: `accept → loop { read (park) → write (park) }` for a
     bounded N messages, asserting echoed contents — the design-84
     `net_owning_echo` extended to multi-message read-then-write.
   - three-in-sequence nested parking calls in one worker.
   - keep coro_*/taskgroup_*/net_* green.
4. Once green, migrate `.build/scratch/httpd_sw.saw`'s handler to the
   real read→build→write flow and confirm it RUNS (a scripted client
   GET returns the response) — or, if httpd-as-a-server isn't a
   deterministic suite test, a socketpair HTTP-shaped round-trip is.
   Report.
5. Docs: saw-lang skill (remove the design-84 runtime-limit warning
   if now false); tracker (design 85 landed; the design-84 flagged
   hang closed).

## Hazards
- Drop-flag / deinit-exactly-once across the multi-park sequence:
  owning values live across BOTH parks must drop once (Arc/Deinit-
  counter through a read-then-write worker).
- Don't regress the single-park boundary (net_owning_echo) or the
  design-83 tail/statement nesting.
- Time-bound every concurrency test; assert counts/contents, never
  orderings; a hang must fail as a timeout, not wedge the suite
  (the runner's per-test timeout must cover it — verify).
Bars: full suite (baseline 870) + blade/libs + bootstrap green per
commit; zero xfails. Standing policy; interruption-safe commits;
saw-lang skill self-review.

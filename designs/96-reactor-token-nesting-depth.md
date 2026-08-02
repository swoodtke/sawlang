# Design 96 — Reactor/coroutine token propagation past one nesting level (queued Aug 2)

Pre-existing limitation surfaced by design 88 (confirmed NOT a design-88
regression — a value-based control hangs identically). A suspending io/
reactor call buried TWO frames deep hangs: spawn-root → nested free fn →
nested METHOD whose body suspends on the reactor (`stream.read()`). The
parked frame's wake TOKEN (design 91 — the `__wake`-word address carried
as the reactor event's user-data) propagates only ONE nesting level, so
a sub-sub-frame's park registers a token the executor can't route back,
and the frame never wakes.

## Repro
Reduce from design 88's `read_into`-over-a-real-socket attempt: a
spawned worker calling a nested free fn calling a suspending method that
does `io_wait`/`stream.read()` — hangs. `yield_now`-only nesting works
(design 83/84 tail/method nesting); the gap is specifically the REACTOR
token threading through 2+ embedded sub-frames. (Contrast design 89-b's
executor unification, which fixed the SCHEDULER re-entry; this is the
reactor TOKEN threading, distinct.)

## Scope
1. Root-cause how the reactor token (the parked frame's wake-word /
   park-record address, design 91) is threaded when a park happens
   inside an embedded sub-frame 2+ levels deep. Likely: the token is
   captured at the outermost drive, not re-derived at the actual
   parking sub-frame, so the deep park registers the wrong/absent
   token. Instrument with the repro under a watchdog.
2. Fix so a park at ANY nesting depth registers the CORRECT wake token
   (the currently-running root task's wake-word), and the executor
   routes the reactor readiness event to it. Both driven-in-place and
   spawned roots.
3. Then RE-VISIT the design-88-deferred net `read_into(&var Data)` over
   a real socket (2-deep suspending read) — it should now round-trip;
   add the test. Report whether to offer `read_into` alongside value
   `read()` (design 88 recommended keeping value-based until this
   landed).
4. Tests: 2-deep and 3-deep suspending reactor calls from a spawned
   worker round-trip (socketpair, deterministic, time-bounded — the
   design-86 runner timeout catches a hang as a failure); keep coro_*/
   taskgroup_*/net_* green.
5. Docs: saw-lang skill (remove any nesting-depth reactor caveat);
   tracker (design 96 landed; the depth limit closed).

Bars: full suite + blade/libs + bootstrap green per commit; zero
xfails. Standing policy; foreground suites; watchdog hangs;
interruption-safe; saw-lang skill self-review.

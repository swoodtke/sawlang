# Design 102 — runtime edge bugs: spawn-Void ICE + cancel wakes an io-parked task (queued Aug 2)

Final pre-SOS batch, part 1 of 6 (102-107). Two known runtime bugs.

## Item 1 — `spawn { void_body }` ICE (design-75 flag)
A spawn closure returning `Void` builds a task control block
`{i8*, i8*, void}` — invalid LLVM ("void type only allowed for
function results"). Worked around in the executor (worker bodies
return Int). FIX PROPERLY: omit the result slot for a Void spawn body
(and make `join()` on such a handle return Void cleanly). Sweep for
the same void-slot hazard in the other frame/TCB layouts (driven
frames, MT groups, channels of Void if expressible). Test: a
`spawn { print(...) }` void body spawns/joins under both TaskGroup()
and TaskGroup(threads: 2); remove the executor workaround if it
becomes dead.

## Item 2 — cancel must wake an ALREADY-io-parked task (A3 remainder)
A task parked in `io_wait` on a permanently-idle fd, cancelled by a
peer, does not observe `cancelled()` until the reactor poll returns
(possibly never). Landed model observes cancel only at the check
BEFORE parking. FIX with the ledgered design: a reactor self-wake
(self-pipe on kqueue/portable; eventfd where available) — `cancel()`
writes the wake byte, the reactor poll returns, the cancelled task's
park is roused (its wake token fired), it re-checks `cancelled()` at
the park loop top (the design-90/91 re-check discipline already
handles spurious wakes, so rousing extra tasks is safe but PREFER
precise: only rouse the cancelled task's token if the plumbing
allows). Tests: peer-cancel of a task parked on an idle fd unblocks
and cleans up (time-bounded; deinit oracle — the stream closes exactly
once); a NON-cancelled sibling parked on another idle fd stays parked
(no herd wake regression, net_precise_* stay green); cancel of an
io-parked task in an MT group.

Bars: full suite (baseline 932, zero xfails) +
`tools/blade_bootstrap.py` "BOOTSTRAP: ok" (incl. libs 4+4) green per
commit. Standing policy; foreground suites; watchdog anything that can
hang; interruption-safe; saw-lang skill self-review; docs = skill
(cancel liveness note replaced) + tracker (both flags closed).

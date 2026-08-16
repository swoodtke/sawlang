# Design 230 — channel waits become real parks

**Status: BUILT (Aug 16). Units landed A, then C, then B — C ahead of B
deliberately, because unit B's report has to name the cooperative path it
is the backstop for, and `close()` is that path. Conformance rows K63-K68.
Two findings filed rather than decided here: DF-230a (a task suspended in
`receive()` cannot be cancelled — pre-existing, and the fix wants a ruling
on whether `ChannelError` grows a `Cancelled` case) and DQ-230b
(`try_send` has two failure modes and one error slot).**

**Direction RULED (user, Aug 16) — DQ-225n's option (a). Sequenced
AFTER design 225's integration (it builds on the live pool's engines).
One surface decision open (unit C). D-e's deadlock-report deliverable
TRANSFERS here from 225 (recorded blocked-not-skipped there).**

## What it looks like as built

The wake word's NEGATIVE HALF is the vocabulary, rather than a new field on
the frame: `-1` stays the io park, and every value below it is a park on a
READINESS WORD, spelled as that word's negated address. The executor's whole
rule is "resume the frame once the word it named is nonzero", so it needs no
channel import, no channel-layout knowledge and no per-channel bookkeeping —
and "a send wakes exactly the parked receivers of that channel" is true by
construction, since no other frame's wake word names that address. The channel
maintains the word under its own mutex at one place (`_publish_ready`);
`__park_is_io` / `__park_is_flag` / `__park_flag_set` are the funnel every scan
asks through.

Measured on the DQ-225n probe trio, 3 wall seconds each: sole waiter 0.02s of
CPU (was 100% of a core), MT waiter 0.033s (was 143%).

Unit B's walk needed one thing the frame scan cannot recover. Of the three
kinds of thread in the process, WORKERS are fully accounted (a mid-resume
worker sets its slot's `active`; an idle one has nothing to run) and
THREAD-ENGINE tasks are counted (no run queue knows about one). The third is
the OWNER thread, which runs ordinary program code between its calls into the
executor, and an MT worker holding a channel-parked task would have reported a
deadlock while the owner was computing its way to the send.
`__saw_exec_in_executor` closes it: a depth counter entered by the ambient
sweep, the single-frame park, an MT `join` and an MT `Deinit`, with the report
requiring it nonzero. Row K68 carries that case.

## The finding this fixes (DQ-225n, measured)

`Channel.receive()` is a try/yield loop; `yield_now` suspends READY, so a
channel waiter is re-resumed as fast as the scheduler spins — 100% of a
core for a sole waiter (143% across two MT workers), and the ratified
deadlock-report state is dead code because "nothing runnable" never holds.
No deadlock analysis exists today; nothing even parks.

## Unit A — the park (no analysis needed)

A channel wait parks with an identifiable wake source: a distinct wake
reason carrying the channel's identity, through `Resumable`'s wake
vocabulary, the transform's receive lowering, and both engines' scans
(ambient phase-2 + the MT workers' idle path via the design-225 wake
broadcast). A send wakes exactly the parked receivers of that channel.
Idle channel waiters go from 100% CPU to 0%. The op-budget doctrine is
untouched (parking is not wall-clock fairness).

## Unit B — the global quiescent report (D-e, transferred and now simple)

At the state: every live task parked + no io registrations + no timer
deadlines + nothing runnable → report and abort with the teaching text.
SOUND BY CONSTRUCTION with no channel-specific reasoning: sender-creation
requires running code, and nothing can run — the eager-per-channel
undecidability worry does not apply to the quiescent state. The report
prints `dump_tasks()` (design 158) so the parked-on-what is visible.

## Unit C — disconnection semantics via EXPLICIT close() (user-corrected)

**The refcount model does not work here and the user caught why: Saw's
channels are UNIFIED Copy handles — no Sender/Receiver role split — so
"sender count" is not a countable thing, and a waiting receiver's own
handle keeps the count nonzero forever.** (The Rust disconnection model
silently assumes Rust's split-role handles.) The mechanism is therefore
the Go pairing: unified handles + EXPLICIT `close()`:

- `close()` callable by ANY holder (typically the producer side, by
  convention); sets the shared closed flag; IDEMPOTENT via the same
  Result surface (a second close returns Err(Closed), no panic).
- Close WAKES every parked receiver (and any parked sender, if the
  channel is or becomes bounded).
- Receive-after-close DRAINS buffered messages first, then Err(Closed)
  (the Go drain-then-closed rule — pin it; losing buffered messages on
  close is the classic mistake).
- Send-after-close → Err(Closed).
- NO automatic close on last-handle deinit (roles are uncountable —
  the whole point); the forgot-to-close deadlock is exactly what UNIT
  B's quiescent report catches. The layering is deliberate: close() is
  the cooperative path, unit B the backstop.
- Recorded as future work, not this brief: a split Sender<T>/Receiver<T>
  surface (which would make disconnection automatic again) — a std
  surface redesign to weigh on its own merits someday.

The ruling converts a deadlock class into handleable errors. **RULED (user, Aug 16): `receive() -> Result<T, ChannelError>`** — closed
is a legitimate error, and the error type is an EXTENSIBLE enum because a
future receive TIMEOUT is another legitimate case (`ChannelError` starts
with `Closed`; `TimedOut` is the reserved next case — this is also the
design-214 gap "receive-with-timeout on Channel" acquiring its surface,
and the eventual timeout composes with the Clock/Timer M3 shape).
`send()` follows the symmetric shape — `Result<Void, ChannelError>`,
`Closed` after an explicit `close()` (NOT on any refcount — roles are
uncountable with unified handles, the same correction unit C carries) —
recorded as the natural symmetric reading; the user may amend at
dispatch if send-on-closed should differ. Consumer sweep is unit C's first step (every
receive/send call site in tree adapts — `try`/`try!`/match per the
never-hide doctrine).

## Gates

The DQ-225n probe trio (sole waiter, ST-task waiter, MT-task waiter)
flips from 100%-CPU hang to 0%-CPU park (unit A) and then to the report
(unit B) — pinned both ways; the ck15-family K-rows stay green; gmgate
both lanes (executor state change); corodiff --all MT axis; soak case
re-run; terminal full battery. STOP-DON'T-WORKAROUND doubly, as with
225.

## Named successor (noted Aug 16, unnumbered until scoped): CHANNEL SELECT

The design-214 standing question resolves on this brief's substrate: once
a wait is a park whose wake reason carries the channel's identity, a
multi-channel park is the same mechanism with a list — park on
{C1, C2, deadline}, wake with which-one. Ruled framing from the
conversation: NO posix-select/epoll/kqueue wrapper ever — the reactor IS
that wrapper and colorless tasks are its interface (the Go lesson);
SELECT IS OVER CHANNELS ONLY, and everything heterogeneous (sockets,
files, signals someday) adapts to channels via a pumping task. The
timeout arm arrives free from ChannelError.TimedOut; the return shape
should consult the SOS WaitResult { key, payload } — hosted select and
the kernel Waiter converging on one vocabulary from both ends. Do not
design it before this brief's park vocabulary is real.

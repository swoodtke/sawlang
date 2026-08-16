# Design 230 — channel waits become real parks

**Status: DIRECTION RULED (user, Aug 16) — DQ-225n's option (a). Sequenced
AFTER design 225's integration (it builds on the live pool's engines).
One surface decision open (unit C). D-e's deadlock-report deliverable
TRANSFERS here from 225 (recorded blocked-not-skipped there).**

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

## Unit C — disconnection semantics (THE OPEN DECISION)

Channel handles are Copy; live-sender counting is refcounting the runtime
already does. Sender count → 0 means NO send can ever occur — the honest
response is waking receivers with a CLOSED outcome (the Rust
Disconnected / Go closed-channel model), converting a deadlock class
into handleable errors. Requires a surface ruling, since `receive()`
returns bare `T` today:
  (i) PANIC on closed — never-hide, loudest, no signature change; a
      closed channel is treated as a bug;
  (ii) `receive() -> T?` — None = closed; quiet, composes with `if let`;
  (iii) `receive() -> Result<T, ChannelClosed>` — the most explicit;
      matches the never-hide doctrine's Result preference.
Consumer sweep owed either way (every receive call site in tree adapts
under ii/iii). Send-on-closed (receiver count → 0) is the symmetric
question and should be ruled in the same breath.

## Gates

The DQ-225n probe trio (sole waiter, ST-task waiter, MT-task waiter)
flips from 100%-CPU hang to 0%-CPU park (unit A) and then to the report
(unit B) — pinned both ways; the ck15-family K-rows stay green; gmgate
both lanes (executor state change); corodiff --all MT axis; soak case
re-run; terminal full battery. STOP-DON'T-WORKAROUND doubly, as with
225.

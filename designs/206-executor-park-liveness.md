# Design 206 — the executor's park paths keep the eager-spawn promise

**Status: AUTHORED Aug 10 from dogfood wave 1's two probe-confirmed
liveness hangs (DF-203a, DF-203b). No ruling needed — both violate
DOCUMENTED contracts (design 89-b's "spawn enqueues a task and it runs
EAGERLY — whenever the executor runs"; designs 96/104's "a suspending
reactor method drives correctly at ANY NESTING DEPTH"), so this is
fix-on-discovery work under the standing policy. Dispatch AHEAD of 201
(same executor/spawn surface, serial). Both pins cost the 30-second
runner timeout on every suite run until fixed — urgency is structural.**

## The two hangs

1. **DF-203a — a reactor park blocks without draining the run queue.**
   `group.spawn(worker())` then `listener.accept()` as main's first
   suspension: the accept path registers with the reactor and blocks on
   it directly; the queued, never-started worker gets no first turn, so
   a worker that would CONNECT to that very listener never runs. The
   TIMER path (`sleep`) drains correctly — the asymmetry is the bug.
   PIN: `examples/spawned_task_runs_before_reactor_park.saw`.
2. **DF-203b — the inline `receive()` lowering does not compose with an
   embedding callee frame.** `ch.receive()` direct in a task body works;
   the same call behind ONE helper frame (free function or method — the
   frame is the trigger, isolated by the dogfood agent's five-probe
   ladder) prints its first entry and hangs. Suspected root: design 62
   G3 lowers `receive()` INLINE into the caller's frame's
   try_receive/yield loop, and that inlining lands wrongly when the
   caller is itself an embedded sub-frame. PIN:
   `examples/channel_receive_through_helper.saw`.

## Units

1. **Diagnose before fixing, and write the failure down.** For each
   hang: which loop/park primitive holds the thread, what the run queue
   held, why the timer path differs (203a) / what the embedded frame's
   receive-loop actually compiled to (203b — `--emit-ir` on the repro).
   The two may share a fix or not; the diagnosis decides the unit split
   and goes in the commit.
2. **DF-203a fix: every park primitive drains ready tasks before
   OS-blocking.** The reactor park joins whatever discipline the timer
   park already follows — ONE funnel for "about to block the executor's
   thread" whose docstring names every park path (accept/read/write/
   connect/offload-join/sleep/channel-park; process rule 1). Flip the
   pin; add the spawn-then-accept shape to the gmgate concurrency lane.
3. **DF-203b fix: the receive lowering composes at depth.** Either the
   inline lowering learns to target the ACTIVE frame correctly when its
   caller is embedded, or a helper-frame `receive()` takes the ordinary
   embedded-sub-frame path other suspending methods use (the
   any-depth machinery 96/101/104 already built) — whichever the unit-1
   diagnosis says is the real seam. Flip the pin; gmgate entry (the
   semaphore-wrapper shape).
4. **Contract sweep (obligation 2-shaped, cheap).** The two fixed paths
   are load-bearing for every net/channel test: full battery is the
   sweep. Verify the op-budget fairness backstop and design 91's precise
   wakeup still hold (their tests exist; name them in the commit).
   Docs: no user-facing rule changes — the docs were RIGHT and the code
   wrong; the skill's accept-loop section gains nothing new unless the
   diagnosis reveals a genuine fence, in which case STOP and file.

## Gates

Per-unit commits, full tracked battery each; gmgate both lanes at -n 5
mandatory (these are scheduler changes — the flaky-surface discipline
applies); irdet --all. Ten-repeat stability on the two flipped pins plus
the two net-adjacent gmgate additions. Zero uncited xfails.

## Explicitly out

Design 201 (spawn reference parameters — dispatches after this, same
surface); any scheduler policy change beyond the drain/compose fixes
(fairness budgets, wakeup precision, MT paths untouched unless the
diagnosis implicates them — then STOP and file).

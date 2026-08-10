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

## Unit 1 — the diagnosis (Aug 10, from the probes)

**Both hangs are ONE bug, and it is neither of the two the brief guessed.**
The park primitives are innocent; so is the design-62 G3 receive lowering.
What is wrong is upstream of both: **the entry compile's effect graph has no
node for any std METHOD, so "does this body suspend?" answers NO for a body
whose only suspension is a std method call** — and every consumer of that
answer then lowers the body as if it never suspended.

`sawc.py:417-430` says so in as many words: *"The main compile typechecker
never checks std bodies (they are pre-checked here), so it cannot infer these
on its own"*. It therefore carries `_std_suspending_methods` (a set of
`(struct, method)` name pairs) across for the coroutine transform. But
`typechecker._suspend_nodes` — the graph the effect FIXPOINT walks — gets
nothing. `_effect_call_method` records an edge to the callee's
`Method.node_id`; that key names no node; `nodes.get(e.target)` is `None`; the
edge propagates nothing.

**Why the timer path looked like it "drained".** It never drains anything.
`sleep(...)` is an INTRINSIC, not a std function — `expressions.py:3311`
records it as a DIRECT source on the caller's own node — so `_main_suspends`
(`effects.py:669-695`) is true, `main` is wrapped in the entry executor, and
the suspension is an ordinary task park the ambient sweep already handles.
`listener.accept()` is a std METHOD, so `_main_suspends` is false and `main`
is never wrapped at all. Verified in the IR: the DF-203a repro emits
`define i32 @main(...)` calling `TcpListener_accept` straight through — no
frame, no `__saw_exec_run_root`. Insert one `yield_now()` into that same
`main` and the whole program runs correctly (`worker connecting / worker done
/ accepted / done`). The asymmetry is intrinsic-vs-method, not timer-vs-reactor.

**DF-203a, precisely.** `main` is not a coroutine, so `accept`'s internal
`io_wait` reaches the OUTSIDE-FRAME lowering (`codegen/calls.py:475-495`):
`__saw_exec_io_register(fd, dir, 0)` then `__saw_exec_park(-1)`, i.e.
`__saw_host_reactor().poll(-1)`. That call blocks the one thread the ambient
scheduler runs on, forever, with a ready worker sitting in the run queue.

**DF-203b, precisely — the same blind spot, one consumer further along.**
`worker` is a spawn root, so it IS transformed; `acquire` is not. Design 96
already found this exact gap and patched ONE consumer of it: the transform's
`structurally_susp_fns` seed (`coro_transform.py:5966-6003`) marks a free
function suspending when `_scan_method_callees` finds a suspending std method
in its body. But `_scan_method_callees` SKIPS `is_chan_recv` calls
(`coro_transform.py:5946`) — correctly, since a channel `receive()` is lowered
inline and never becomes a method sub-frame — and `acquire`'s only suspension
IS a channel `receive()`. So `acquire` joins no closure, gets no frame, and
its `receive()` lowers as an ordinary call to the monomorphized
`Channel$1$Int_receive` body. That body is
`while not __done { if let v = try_receive() { return v } ; yield_now() }`
and OUTSIDE a frame `yield_now()` codegens to NOTHING
(`codegen/calls.py:473`). The emitted IR is a bare infinite spin over
`try_receive` — worker 1 enters it with an empty channel and pins the thread
at 100% forever, which is exactly `in 0` and then silence. std/channel.saw:199
states the belief that fails here: *"it reaches `yield_now`, so it — and any
caller — suspends"* — true in the builtin typechecker, false in the entry one.

**So the fix is shared and it is at the root**, not at either symptom: give
the entry graph the std methods' suspension facts, through ONE definition of
"really suspends" used by both typecheckers. Everything downstream — the
entry-executor gate, the driven closure, the sync-context check — then reads a
graph that is simply correct, and neither park primitive nor the G3 lowering
needs to change. Unit 2 does that; unit 3 closes the chan-recv hole in the
design-96 structural seed as well, so closure discovery is not single-sourced.

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

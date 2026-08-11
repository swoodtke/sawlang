# Design 206 — the executor's park paths keep the eager-spawn promise

**LANDED VIA DESIGN 210, Aug 11.** The five commits are design 210's unit 0,
cherry-picked onto main and integrated with design 201's spawn-reference
lowering (no textual conflicts; both sides' rows green in one tree). The blocker
below — DF-206e — was ruled on and fixed by design 210 rather than worked
around: an embed carries its declaration-time answers, so a spliced body keeps
its own module's meaning and blade compiles again. Both liveness pins are
passing and the brief's own units are unchanged from what is written here.

The record of why it was blocked follows, because the diagnosis is the durable
part and the blocker is the reason 210 exists.

**BLOCKED Aug 10 — DO NOT INTEGRATE THIS BRANCH AS IT STANDS.** Units 1-4 are
written and both hangs are closed on the `examples/` corpus (suite 1730 passed /
8 xfailed, gmgate both lanes green, ten-repeat stable), but the FULL battery is
RED: `bootstrap` and `sos` both fail, because **blade no longer compiles**.

The cause is unit 2's blast radius, and it is a genuine design question rather
than a slip in the patch — see DF-206e in the tracker. Making `main` suspending
whenever it REALLY suspends is correct and is what LANGUAGE_SPEC:5053 already
promised; the consequence is that the coroutine transform now runs on programs
it has never run on, and it does not support one of them. blade's `main` reaches
`Command.run` through `builder.Builder.build` — a method of an imported USER
module — so the transform embeds that method as a sub-frame, and the spliced
body is re-typechecked in the ENTRY module's namespace, where the callee
module's own private functions are not visible. blade dies on `resolve`,
`read_file`, `sos_clang` and friends: "function `resolve` is not directly
accessible". Cross-module embedding works for a STD method (design 84 built it
for exactly that, and std is one scoping domain the entry compile has fully
registered) and not for a user-module one.

Minimal repro, two files, no blade:

    // util.saw
    import std.process.{Command}
    public struct Runner { public tag: Int }
    func inner() -> Int { 7 }
    extension Runner {
        public func run_echo(&self) -> Int {
            var c = Command(program: "/bin/echo")
            c.arg("hi")
            let _ = try! c.run()
            inner() + self.tag                  // error: undefined function `inner`
        }
    }
    // main.saw
    import util.*
    func main() { let r = Runner(tag: 1)  print(r.run_echo()) }

This needs a ruling before the brief can land: fix the transform's cross-module
splice (its own brief), or scope the entry-executor gate, or accept it and
change blade. What is NOT acceptable is the current tree, which fixes two hangs
and breaks the package manager.

*(Ruled Aug 11: the first. `designs/210-annotated-embedding.md`.)*

The unit-1 diagnosis below stands unchanged and is the durable part of this
work: both hangs are ONE bug and neither park primitive nor the G3 lowering is
implicated. DF-206a and DF-206b were fixed on discovery and are independently
good; DF-206c, DF-206d and DF-206e are filed. No user-facing doc change is
owed — LANGUAGE_SPEC:5053 already says the compiler wraps `main` when it
"transitively reaches" a cooperative primitive, and the skill's
any-nesting-depth guarantee already covered the helper-frame case.

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

## What landed, unit by unit

1. The diagnosis above, in the brief and in the commit.
2. `really_suspending(nodes)` as ONE definition shared by both typecheckers;
   `_std_really_suspending_methods` (node-id-keyed) computed by the builtin
   compile and seeded into the entry graph by `_effect_seed_std_methods`.
   DF-203a closes. gmgate concurrency lane gains the spawn-then-accept shape.
   Beside it: DF-206a's third classifier (`_classify_recv` guarding `let _`).
3. `_body_has_chan_recv` splits the structural-suspension seed's question from
   `_scan_method_callees`'s, so the transform's own discovery route agrees with
   the effect graph rather than being covered by it. DF-203b closes.
   `examples/channel_receive_in_main.saw` adds the `main`-waits-on-a-channel
   position (direct and behind a helper). gmgate gains the semaphore shape.
4. Contract sweep (this section). No user-facing doc change owed.

Before unit 2 could land, two prerequisite compiler bugs had to go (both
pre-existing, both fix-on-discovery, both blocking a program this brief needed
to compile): DF-206a (`let _` discards shared one frame field) and DF-206b
(destructuring a tuple of owning elements in a frame was a copy). Their pins are
`examples/coro_wildcard_discards_own_slots.saw` and
`examples/coro_destructure_nocopy_into_frame.saw`.

## The contract sweep (unit 4)

The two fixed paths are load-bearing for every net and channel test, so the full
battery IS the sweep. Named verifications, all passing:

* **Op-budget fairness (design 89-c + 127)** — `net_budget_fairness`,
  `taskgroup_compute_preemption`, `taskgroup_compute_preemption_unbounded`,
  `taskgroup_compute_preemption_mt`, `taskgroup_budget_loop_semantics`.
* **Precise reactor wakeup (design 91)** — `net_precise_wakeup`,
  `net_precise_n_readers`, `net_two_concurrent_parked_reads`,
  `net_cancel_precise`, `net_cancel_parked_read`, `net_cancel_unregisters_token`.
* **Cancellation + interleaving (designs 102, 180, 89-b)** —
  `taskgroup_cancel_during_sleep`, `taskgroup_cancel_receive`,
  `channel_recv_cancel`, `net_io_sleep_interleave`, `taskgroup_spawn_and_loop`.

MT paths were not implicated by the diagnosis and are untouched: the seeded
nodes change what the ENTRY typechecker infers, and every executor body is
unchanged Saw.

Obligation 3 (conformance rows first) does not bind: no safety guarantee is
touched. Nothing became more permitted — the two prerequisite fixes each
stopped the compiler REFUSING a legal program (DF-206a's second discard,
DF-206b's owning-tuple destructuring), and DF-206b's replacement semantics are
exactly what the non-frame path already did. The guarantees this brief restores
are LIVENESS promises (design 89-b's eager spawn, designs 96/104's any-depth
drive), which the conformance ledger does not carry rows for; their pins are
the two `examples/` programs above.

Ten-repeat stability, 10/10 byte-identical output and exit code each:
`spawned_task_runs_before_reactor_park`, `channel_receive_through_helper`,
`channel_receive_in_main`, `coro_wildcard_discards_own_slots`,
`coro_destructure_nocopy_into_frame`.

## Explicitly out

Design 201 (spawn reference parameters — dispatches after this, same
surface); any scheduler policy change beyond the drain/compose fixes
(fairness budgets, wakeup precision, MT paths untouched unless the
diagnosis implicates them — then STOP and file).

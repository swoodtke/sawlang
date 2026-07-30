# Design 62 — Async v1 gaps: G1/G2/G3 from the 52b deferral list (queued Jul 30)

Close the three cooperative-async gaps design 59 scoped (reproductions
in its report; estimates: G3 small-medium, G2 medium, G1 medium-large).
The 52b model is settled — this brief COMPLETES it, no new semantics
decisions: frames stay self-contained, cleanup stays normal-control-flow
(no forced destroy), cancellation stays cooperative, the group's Deinit
still runs children to completion (structured join via LIFO).

## G3 — first-class suspending channel receive (do FIRST, smallest)
Today the idiom is hand-written `try_receive() -> T?` + `yield_now()`
loop. Ship it as a real suspending method on Channel: cooperative
`recv() -> T` — internally the same try/yield loop (wake reason:
channel-yield as 52b defined), driven like any suspending method by
the transform. Naming: the blocking thread-engine `receive()` keeps
its name and semantics untouched (same signature, so overloading can't
distinguish them — hence the distinct name `recv`; note the naming
choice in the report and docs). Tests: producer/consumer via `recv()`
in a TaskGroup; recv-then-cancel observation; recv inside nested
control flow (exercises the 52 Part-0 CFG machinery).

## G2 — if-let over a suspending call
`if let x = suspending_call() { ... }` is currently rejected. Implement
via the hoist 59 scoped: the transform rewrites the condition into a
preceding driven temp (`let __t = suspending_call()` — itself the
already-supported suspending-call-in-let form) then an ordinary if-let
over `__t`. Same for `guard let` if the machinery is shared (probe;
report if guard needs separate handling or stays rejected — if it
stays rejected, the diagnostic must say so cleanly). Drop-flag
correctness: the temp's Optional payload must deinit exactly once on
both branches (deinit-count test). Also cover `while let` if it exists
in the grammar (probe; likely not — report).

## G1 — TaskGroup inside a suspending function (the big one)
Today a TaskGroup can only live in a non-suspending frame (e.g. main's
executor). Per 59's scoping: the group (and its erased run queue —
`Vector<Box<any Resumable>>`) must become FRAME-RESIDENT state when
declared in a suspending function, and `group.spawn(f(args))`'s
synthesized `__spawn_f` receiver must resolve through the frame
pointer. Constraints that must keep holding:
- The group's Deinit (which runs the executor to completion) fires
  during the frame's normal-control-flow cleanup — including when the
  OWNING frame is itself suspended and resumed across the group's
  lifetime (a parent suspension point between spawn and group-drop is
  the key new shape; the child executor runs nested within a parent
  resume).
- NO executor re-entrancy hazards: a child task must not drive its own
  parent's frame. The nested group's executor drives ONLY its own
  queue (this falls out of the group owning its queue — assert it with
  a test where parent and child both sleep).
- Cancellation words stay frame-resident and reachable.
- If a genuinely fundamental blocker emerges (e.g. re-entrancy that
  the v1 model cannot express), STOP on G1: keep the rejection but
  upgrade the diagnostic to name the limitation precisely, record the
  blocker in the tracker under A1c with your analysis, and land
  G2+G3 — an honest partial landing beats a subtly unsound G1.
Tests: suspending fn owning a group (spawn/join/sleep/yield inside),
parent suspends between spawns and after, nested groups (group in a
suspending fn called from a task of an outer group) if the model
allows — else clean rejection test; cancellation through the frame.

## Docs
Spec concurrency section: recv(), if-let-over-suspending, TaskGroup-
in-suspending-fn (or its precise limitation). CLAUDE.md TaskGroup
bullet updated. Tracker A1c: G1/G2/G3 closed (or G1 blocker recorded).

## Items (suggested commit units)
1. G3 recv() + tests.
2. G2 if-let hoist + tests.
3. G1 frame-resident TaskGroup + tests (or the honest-blocker
   diagnostic + analysis).
4. Docs + tracker-edit report.

## Hazards
- coro_transform.py is the surface for G1/G2 — the entire coro_* +
  taskgroup_* + sync_* effect families are the regression oracle.
- G2's hoist interacts with move-in-condition rejections (52 Part 0
  kept those as honest errors) — do not accidentally legalize a
  rejected shape; the hoist applies only to the plain call form.
- Frame layout changes (G1) touch drop flags and embedded sub-frames —
  design 61 is concurrently fixing enum drop-glue tagging on main;
  do NOT fix that bug here even if you trip on it (leave a note
  instead; integration reconciles).
Full suite per commit; zero xfails.

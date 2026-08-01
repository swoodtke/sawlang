# Design 89 — Executor unification: one ambient cooperative scheduler (DECIDED Aug 1)

Close the last async-architecture gap before the kernel. Today TWO
executors don't cooperate: the auto-wrapped ENTRY executor (design 45
— drives only `main`'s frame + its sleep/io waits) and each
TaskGroup's executor (design 52b — drives spawned children only at
`join`/`Deinit`). So a long-running `accept`-loop server
(`while true { let conn = accept(); group.spawn(handle(conn)) }`)
never runs its handlers: main parks on accept, and nothing drives the
group. Fix = the ambient-executor model.

## Model (pinned; user-vetoable)
- ONE cooperative executor per OS thread (the main thread's entry
  executor is THE scheduler; design-75 MT worker threads keep their
  own — see below). It owns a single shared RUN QUEUE of
  `Box<any Resumable>` frames.
- `spawn(f(args)) -> TaskHandle<T>` ENQUEUES the frame into the
  current thread's executor run queue and returns the handle. It runs
  whenever the executor runs — NOT only at join. (Same frame
  synthesis/boxing as today; only the enqueue TARGET changes: the
  ambient executor's queue, not a group-private queue.)
- The executor LOOP: while any frame is runnable, drive round-robin,
  honoring yield_now / earliest sleep deadline / io-ready (reactor,
  design 76) / channel-yield; when ALL are parked, block on the
  reactor+timer until one is ready. `main` is just the root frame in
  the queue.
- A **TaskGroup is now a LIFETIME/JOIN SCOPE**, not a separate
  scheduler: spawn-into-a-group records the frame's MEMBERSHIP in
  that group (a group id / list); the group's `Deinit` (LIFO scope
  exit) cooperatively drives the shared executor UNTIL all its
  members complete (structured join preserved) — but members have
  usually already run because the executor ran them eagerly.
- **Structured concurrency preserved, NOT weakened:** every spawn is
  still into a group; a `main` that spawns and returns still waits
  for its children at the group's Deinit. NO detached-task escape.
  (An infinite-loop server never reaches Deinit → handlers run
  forever, correct.) `TaskHandle.join()` = drive the shared executor
  until THIS handle's result is ready, running siblings meanwhile,
  then take the result exactly-once.
- **Cancellation** (design 52b/A3): unchanged — cooperative
  frame-word, observed at suspension points; group cancel sets its
  members' words.

## Nested TaskGroups (single-threaded) — handled by construction
Because a group is a scope over the ONE shared queue (not its own
executor), nested groups are natural: an inner group created inside a
task enqueues its spawns into the SAME ambient queue tagged with the
inner group's membership; inner-group `Deinit` (LIFO scope exit)
drives-until-its-members-done, THEN the outer group's does. No
per-group executor = no executor-nesting problem (this dissolves the
design-62 G1 TaskGroup-in-a-suspending-fn pain rather than
special-casing it). REQUIRED tests: a group nested inside a task of an
outer group (inner children + outer children interleave on the shared
scheduler; both scopes join correctly, LIFO); a task in an inner group
that spawns into ITS group while the outer accept-loop keeps running.

## Implicit yield at suspension points (semantics to document)
A suspending call IS a yield point: when a task's read/accept/sleep/
channel-receive PARKS (would-block / empty / deadline-not-reached), it
cedes to the scheduler automatically — a task doing real I/O NEVER
needs explicit `yield_now`. Precision: it yields ONLY when it actually
needs to wait — a read() with data already ready returns WITHOUT
parking (no spurious yield). Therefore `yield_now` is only for a
CPU-bound loop that makes no suspending calls (or whose calls never
park) and wants to cede voluntarily. STARVATION caveat (document): a
task that never parks and never yields monopolizes the single-threaded
scheduler — inherent to cooperation; `yield_now` is the escape.
Test: a task whose only suspension is an io read (no explicit
yield_now) interleaves correctly with a sibling while it parks.

## MT interaction (design 75)
`TaskGroup(threads: N)` keeps its own worker pool + queue (a separate
scheduler) — this brief unifies only the DEFAULT single-threaded
executor into a persistent ambient scheduler. A single-threaded group
(default / `threads: 1`) uses the ambient thread executor (the change
here); an MT group uses its worker pool as today. Report the seam and
keep both green. (Nested: an MT group inside an ambient-scheduled task
is design-75 territory — verify it still composes; if it strains,
constrain + report.)

## Scope
1. Refactor the runtime so `main`'s entry executor is a PERSISTENT
   scheduler over a shared run queue (not a drive-main-only wrapper);
   spawn enqueues into it; the loop drives all runnable frames with
   the existing wake disciplines. (Runtime is largely codegen-emitted
   Saw/IR — designs 45/52b; extend, don't rewrite from scratch.)
2. TaskGroup becomes membership+lifetime over the shared queue: track
   members, Deinit drives-until-members-done (cooperative, cedes to
   the shared loop), exactly-once join/result, unjoined-drop-once.
3. `join()` drives the shared executor to this-handle-ready (siblings
   progress meanwhile). No busy-wait; park when nothing runnable.
4. THE ACCEPTANCE: the live `.build/scratch/httpd_sw.saw` accept-loop
   server, driven by a scripted client, SERVES a GET end to end
   (a socketpair/loopback-reduced deterministic version is the suite
   test — a server task that accept-loops + N client tasks that
   connect/GET/read, all in one program, asserting responses; time-
   bounded; the design-86 net_http_roundtrip generalized to
   concurrent-connections-while-accepting).
5. Tests: spawn-and-loop (main parks, child runs — the core fix);
   accept-loop server + concurrent clients round-trip; interleaving
   (task A parks on io while task B runs); structured join still waits
   at scope exit (a spawn-then-return main drains children — exact
   count); sleep-ordering across the shared queue; cancellation of a
   queued task; MT group still works (design-75 suite green);
   deinit-exactly-once across the shared queue. The design-45/52b/76
   families are the oracle.
6. **Cooperative budget (LAST commit unit — gated behind items 1-5
   being green; DEFER to a follow-on brief if the core executor work
   proves large/risky, re-ledger with analysis).** A per-task work
   budget bounds how long an I/O task runs between yields, fixing the
   ready-io-loop starvation caveat without preemption:
   - Each frame carries a budget word (a frame-resident counter, like
     the design-52b `__cancel` word), seeded to **128** at
     (re)schedule.
   - Every suspending primitive (read/accept/write/receive/etc.) that
     completes WITHOUT parking decrements the budget; when it reaches
     0, the NEXT suspending call yields anyway (park-and-immediately-
     reschedule — a forced cooperative yield) and the budget resets.
   - A call that ACTUALLY parks resets the budget (it already yielded).
   - **Operation-count, NOT wall-clock** (decided): no clock read per
     suspend — kernel-friendly (no cheap wall-clock on App-2 early),
     cheap, and DETERMINISTIC (tests assert exact interleavings; a
     time budget would be flaky).
   - Purely at existing suspension points — still cooperative,
     colorless, no new yield points / signals / language surface.
   - Honest limit (document): only helps tasks that make SOME
     suspending calls; a pure-compute-no-suspend loop still needs
     `yield_now` or an MT thread (same as every cooperative runtime).
   - Test (deterministic): two tasks, one doing a long run of
     ALWAYS-READY reads (socketpair pre-filled) with no yield_now, the
     other counting — assert the counter task makes progress bounded
     by the budget (the ready-reader can't monopolize); budget-resets-
     on-park case; the design-89 core tests unaffected.
7. Docs: spec concurrency (the single ambient executor + TaskGroup-as-
   scope model; the structured-join guarantee; implicit-yield +
   cooperative-budget fairness); saw-lang skill (the server pattern
   now works — update; remove the design-86 live-httpd limitation
   note; note the budget so hot-loop authors understand fairness);
   CLAUDE.md digest; tracker (design 89 landed; executor-unification /
   live-server gap closed; cooperative budget landed or deferred).

## Hazards
- Structured-join correctness: main returning must still drain its
  groups' children exactly-once (no leak, no double-drive). The
  shared queue must not drop a group's member on group Deinit if it's
  already mid-flight elsewhere — membership + done-flag discipline.
- Reentrancy: join() driving the shared executor while ALREADY inside
  the executor loop (a task joining another task) — must not
  recursively re-enter the loop unsoundly; a task that joins yields
  to the scheduler until the target is done, it does NOT nest a
  second loop. Get this right (it's the classic bug); test task-
  joins-task.
- Fairness: round-robin, cooperative; a non-yielding CPU task starves
  siblings — document, don't try to preempt.
- Do NOT regress single-task suspending main (design 45) or the
  design-75 MT path.
Bars: full suite (baseline = post-87) + blade/libs + bootstrap green
per commit; zero xfails; concurrency tests deterministic (counts/
contents, never orderings) + time-bounded (the design-86 runner
timeout now protects hangs). Standing policy; interruption-safe
commits; saw-lang skill self-review.

---

## STATUS (Aug 1) — prep landed; core unification RE-LEDGERED (deferred)

Landed (green, committed): the coro-transform **static-visibility fix** —
a suspending std method that names a module-private `static` (e.g.
`TcpListener.accept` -> `INVALID_FD`) now compiles when spawned/driven
(the const initializer is inlined at the reference site during the
transform). Before this, `accept()` could not even be embedded, so no
accept-loop program could compile. Test: `net_accept_roundtrip.saw` (a
spawned server task accepts ONE loopback connection + serves a GET;
deterministic). Suite 884, bootstrap 17+17, libs 4+4.

The **core executor unification (items 1-6) is DEFERRED** to a focused
follow-on, on an evidence-based risk call (the "defer if large/risky,
re-ledger with analysis" escape). Two things were PROVEN this session:

1. The core gap is real and reproduces minimally (`probe_gap`: main
   `spawn`s a child, then runs a `sleep`-loop; the child prints only at
   the final `join`, never during main's parks — output `0,1,2,100,101,
   102,7`). Confirms today's split executors: entry-executor drives main's
   frame ONLY; the group's children run only at `join`/`Deinit`.

2. **A SECOND, INDEPENDENT blocker gates the accept-loop acceptance** — a
   design-76 REACTOR bug in the multi-connection accept-loop, NOT the
   executor split. `probe_loopdiag` (server serves N=2 sequentially + 2
   clients, ONE group — a shape the current per-group executor already
   co-schedules): it accepts conn#0, serves it fully, accepts conn#1, then
   the **read on the 2nd connection never wakes** (markers reach 911, never
   921) and the program hangs. A single accept+read+write round-trip works
   (`net_accept_roundtrip`); the second sequential connection's read-park
   is a lost wakeup in the one-shot-register + wake-all-io-parked reactor.
   **Unifying the executor does NOT fix this** — so the accept-loop
   acceptance needs BOTH the unification AND this reactor fix. Treat the
   reactor lost-wakeup as its own item (likely design-76 follow-up).

Why the core is large/risky (the honest assessment):
- **No small slice.** Making `probe_gap` pass requires the whole ambient
  machinery at once: a thread-global run queue reachable from any frame
  (a `static` pointer, since a group buried in main's frame is otherwise
  unreachable from a deep `spawn`), per-frame **group-id membership**
  tagging (so a group's `Deinit` can drive-until-ITS-members-done), a
  **reentrancy guard** (a nested `join`/`Deinit` pump must skip frames
  active on the C stack — the sound realization of "yield to the one
  scheduler, don't re-enter a live coroutine"), **deinit-exactly-once**
  across the shared queue (ownership of the boxes must move from the group
  to the ambient queue without shifting `TaskHandle` frame pointers or
  double-dropping an unconsumed `__result`), and an **MT bifurcation**
  (design-75 `TaskGroup(threads:N)` keeps its own pool — only the ST
  default routes to the ambient scheduler, so `TaskGroup` must support
  BOTH a shared-queue ST mode and an own-queue MT mode).
- **Regression surface.** 884 tests + bootstrap + libs; several concurrency
  tests print interleaved output — a scheduler change can reorder those
  even where results are stable. Re-verifying the whole matrix per
  increment is required and cannot be done piecemeal (the queue swap is
  global). The existing per-group tests (`taskgroup_nested_groups`,
  `net_http_roundtrip`, `taskgroup_in_suspending_fn`) explicitly encode
  the per-group-executor model in their comments and assert results; those
  RESULTS survive unification but the machinery under them all changes.

Recommended follow-on plan (design 89-b), correctness-first, per-commit:
  a. Introduce the ambient scheduler as a heap singleton reachable via a
     `static __saw_exec: Atomic<Int>` (address; 0 = none), reusing the
     proven `TaskGroup.__run_all_st` round-robin + design-76 reactor
     integration verbatim as the loop body. Add a per-frame `group` id
     column and an `active` reentrancy column (the MT `active` flag is the
     precedent). Parameterize the loop's termination: run-until-all (entry),
     run-until-frame-done (`join`), run-until-group-members-done (`Deinit`),
     each SKIPPING active frames.
  b. Entry executor: create the ambient scheduler, enqueue main's frame as
     the root member, run-until-all. (Keeps design-45 single-task main a
     one-member special case — verify byte-identical where no `spawn`.)
  c. `__spawn_f`: enqueue into the ambient scheduler tagged with the
     caller group's id; `TaskHandle` frame pointers stay heap-stable (the
     box's data word never moves). `TaskGroup` becomes a membership id +
     an own-queue MT fallback; its `Deinit` drives ambient-until-members-
     done then drops exactly its members' boxes (exactly-once).
  d. Then, AND SEPARATELY, fix the design-76 multi-connection reactor
     lost-wakeup so the accept-loop acceptance (server task accept-loops N
     + N clients, one program) round-trips deterministically.
  e. Item 6 (cooperative op-count budget, default 128) rides on top once
     a-d are green — unchanged from the brief.
Repro files kept under `.build/scratch/` (`probe_gap.saw`,
`probe_loopdiag.saw`, `probe_accept*.saw`) for the follow-on.

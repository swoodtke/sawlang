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
6. Docs: spec concurrency (the single ambient executor + TaskGroup-as-
   scope model; the structured-join guarantee; fairness note);
   saw-lang skill (the server pattern now works — update; remove the
   design-86 live-httpd limitation note); CLAUDE.md digest; tracker
   (design 89 landed; executor-unification / live-server gap closed).

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

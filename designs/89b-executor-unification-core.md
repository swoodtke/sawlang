# Design 89-b — Executor unification core (WORKTREE) (queued Aug 1)

The core executor unification design 89 deferred with analysis. Do it
in an ISOLATED WORKTREE (the "queue swap is global, cannot be done
piecemeal" warning = main can't stay green mid-rewrite; isolate,
cherry-pick when the acceptance passes). Follows design 89's model +
the a–e plan recorded in designs/89-executor-unification.md STATUS —
READ THAT FIRST (it is the authoritative decomposition). Prereq:
design 90 (reactor lost-wakeup) landed on main FIRST — this worktree
forks after it, so the acceptance can actually pass.

## The a–e plan (from design 89 STATUS — authoritative)
a. Ambient scheduler as a heap singleton reachable via
   `static __saw_exec` (address; 0 = none), reusing the proven
   `TaskGroup.__run_all_st` round-robin + design-76 reactor loop body
   VERBATIM. Per-frame `group` id column + `active` reentrancy column
   (MT `active` flag is the precedent). Parameterize the loop's
   termination: run-until-all (entry) / run-until-frame-done (join) /
   run-until-group-members-done (Deinit), each SKIPPING active frames.
b. Entry executor creates the ambient scheduler, enqueues main's frame
   as root member, run-until-all. Design-45 single-task main = a
   one-member special case — VERIFY byte-identical where no spawn.
c. `__spawn_f` enqueues into the ambient scheduler tagged with the
   caller group's id; TaskHandle frame pointers stay heap-stable (box
   data word never moves). TaskGroup = membership id + own-queue MT
   fallback; its Deinit drives ambient-until-members-done then drops
   exactly its members' boxes (exactly-once).
d. (design 90 already did the reactor fix on main — inherited.)
e. Cooperative op-count budget (default 128, frame-resident counter,
   forced yield at 0, reset on park) rides on top once a–c green —
   the design-89 item 6, unchanged.

## THE TWO HAZARDS (design 89 — the classic executor bugs)
- Structured-join exactly-once: main returning drains its groups'
  children exactly-once (no leak, no double-drive); a member
  mid-flight elsewhere isn't dropped on group Deinit (membership +
  done-flag).
- Join-reentrancy: a task joining another task YIELDS to the one
  scheduler until the target is done — the nested join/Deinit pump
  SKIPS frames active on the C stack; it does NOT re-enter a live
  coroutine / nest a second loop. Test task-joins-task explicitly.

## Acceptance + tests
- ACCEPTANCE: a live accept-loop server (server task accept-loops +
  N client tasks connect/GET/read, ONE program, socketpair/loopback,
  time-bounded) round-trips all N — the design-89 acceptance, now
  reachable (reactor fixed by 90).
- spawn-and-loop (main parks, child runs — `probe_gap` must now print
  interleaved, not only at join); nested groups (design-89 required
  tests); implicit-yield (io-parking task interleaves with a sibling,
  no yield_now); structured join waits at scope exit (spawn-then-return
  main drains children, exact count); task-joins-task reentrancy;
  sleep-ordering; cancellation of a queued task; deinit-exactly-once
  across the shared queue; MT group still green (design 75); the
  existing taskgroup_*/net_*/coro_* results survive (their MACHINERY
  changes — report which tests' comments describe the old per-group
  model and update the comments, keep the asserts).
- Budget test (item e): a task doing always-ready reads (pre-filled
  socketpair) with no yield_now cannot starve a counting sibling.

## Integration (orchestrator)
Worktree agent commits on its branch; orchestrator cherry-picks the
coherent series onto main ONLY when the full a–e + acceptance +
regression is green (linear history, no merge commit). If an
increment genuinely can't be green even in the worktree, that's a
finding — report, don't force.

## Docs (in the worktree, cherry-picked with the code)
Spec concurrency (single ambient executor + TaskGroup-as-scope +
structured-join + implicit-yield + budget); saw-lang skill (server
pattern works; remove the design-86/89 live-httpd limitation notes);
CLAUDE.md digest; tracker (design 89/89-b landed; executor-unification
+ live-server gap closed; budget landed).

Bars: full suite (baseline = post-90, in the worktree with its own
.venv) + blade/libs + bootstrap green per commit; zero xfails;
concurrency tests deterministic + time-bounded. Standing policy;
interruption-safe per-commit; saw-lang skill self-review.

# Design 124 — TaskGroup eager teardown (a group is a scope, not an extender)

Source: `designs/reviews/2026-08-04-language-design-claims.md` (RS-3 /
DOES-NOT-HOLD #1 + the EOF-deadlock caveat). User decision Aug 4: eager
teardown — a completed task's owned values are released AT COMPLETION, not at
group teardown. This makes the deterministic-destruction claim true for tasks
and fixes the two proven defects:
- the README's accept-loop server leaks one fd + frame per served connection
  for the group's life;
- the sibling reader/writer pattern deadlocks: the reader waits for EOF that
  only arrives when the writer's stream drops, which today happens at group
  Deinit, which waits for the reader.

## Semantics to pin
1. When a frame transitions Done, its owned locals are dropped THEN (the
   frame's normal end-of-scope Deinit path — this mostly already runs; the
   defect is what the frame BOX retains afterward). What must survive until
   `join()` or group teardown is exactly the `__result` slot.
2. Result ownership: joined → the result moves out at `join()` (already
   true); never-joined → the result drops at group teardown (already true).
   Neither path may double-drop after the eager teardown lands (the design-67
   read-out-of-container class is the hazard — regression-test both).
3. Frame storage: the `tasks` vector slot must become reclaimable at Done
   (drop the Box eagerly, keep the bookkeeping slot; do NOT compact the
   vector — indices are handles) without disturbing `active`/`done`/
   `remaining` invariants in either the ST sweep or the MT worker.
4. Reactor hygiene: a task that completes with io registrations armed (its
   fds now closed by the eager drop) must not leave stale one-shot
   registrations that a reused fd number could collide with (interacts with
   the design-91 token contract; the fd_reuse test family covers the shape).
5. Cancellation: a cancelled-then-completed task follows the same eager path.

## Tests
- The review's probe becomes a test: 5 spawned+joined tasks in a loop print
  their deinits BEFORE the post-loop marker (today: after).
- Accept-loop: serve N connections, assert each stream's Deinit (fd close)
  lands before the next accept completes (observable via the probe pattern).
- The reader/writer EOF pattern completes instead of deadlocking.
- MT (`threads: N`) variants of the first two.
- Existing suite: the 88/106 reference-across-suspend and 102 cancel tests
  are the regression fence for the ownership edges.

## Docs
Spec + skill: the TaskGroup section states eager per-task destruction and
what `join()` returns ownership of; README's concurrency claims section
needs no softening once this lands.

## Exit criteria
All new tests green; full suite + bootstrap + sos green; no leak of the
`__result` double-drop class (explicit tests); tracker RS-3 closed.

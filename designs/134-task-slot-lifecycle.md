# Design 134 — task slot lifecycle: reclaimable frames, O(live) groups

STATUS: APPROVED (user, Aug 5). Deliberately sequenced LAST (after 133):
this rewrites the spawn protocol in the same executor code designs 130
(unsafe migration) and 131 (`join` onto `take()`) are touching — the tree
must be quiet there first. Closes DF-124c.

## Problem

After design 124 every RESOURCE a task owns is released at Done, but the
frame ALLOCATION (result slot + scheduler words) survives until group
teardown, and 124's own bookkeeping rule ("do NOT compact, indices are
handles") makes the `tasks`/`done`/`active` vectors O(tasks-ever-spawned)
too. A long-lived accept-loop group therefore grows without bound in task
COUNT even though per-task resources are reclaimed. Why the box cannot
simply be dropped at Done (DF-124c): `__result` lives INSIDE the frame;
`TaskHandle.result_ptr`/`cancel_ptr` are raw pointers into it; and
`cancel_addr()` deliberately hands a PEER task a raw frame address to write
later — no done-check can guard that write. The erased `Box<any Resumable>`
also cannot free a payload it no longer describes.

## The design (protocol change, three moves)

1. **Group-owned result and cancel cells.** `__result` and `__cancel` move
   OUT of the frame into type-aware cells owned by the group (per-task,
   allocated at spawn beside the slot). `TaskHandle` points at the cells,
   never into the frame; design-102's `__is_cancelled` reads the cell. The
   frame keeps only what resume needs. With no outside pointers into the
   frame, the Box drops eagerly at Done — the 124 brief's item 3, now
   implementable.
2. **Slot free-list with generation-counted handles.** A Done task's slot
   (frame box gone, result cell consumed-or-dropped, cancel cell retired)
   goes on a free-list for reuse. Handles become (index, generation);
   a stale handle's generation mismatch is a defined error, preserving the
   "indices are handles" safety that motivated no-compaction. Group memory
   becomes O(live + unconsumed-result tasks).
3. **Teardown simplifies.** Group teardown drops remaining cells and live
   frames exactly once; the design-124 eager-teardown fences and the
   result-dropped-exactly-once tests must stay green throughout.

Touches: spawn lowering (codegen calls.py control block), std/taskgroup.saw,
TaskHandle, cancellation (102), MT claim protocol (89b) — the cells must be
safe for the cross-thread cancel write (the existing wake-word/atomic
discipline applies). Respect the design-130 unsafe model as migrated: new
raw-pointer seams get the type-carried spelling, not line markers.

## Tests
The 124 fences stay green (eager teardown, result joined/unjoined exactly
once, cancel wakes an io-parked task); new: accept-loop-shaped group where
memory/slot count is asserted O(live) across many spawn/finish waves (the
live-count oracle from 124's tests extended to slot reuse); stale-handle
generation mismatch is a defined error test; MT variant; cancel-after-Done
through a stale handle is safe and defined.

## Exit criteria
Full gate battery green; DF-124c closed with the mechanism recorded;
spec/skill updated where the TaskGroup/TaskHandle surface changed.

# Design 163 — frame-overlay sizing: the investigation

**Status: APPROVED as an INVESTIGATION (user, Aug 7: "we should
launch an investigation to see if we can reduce the size of the
task's frame using the high-water mark mechanism"). Measurement and
constraints analysis ONLY — the implement/decline decision comes back
to the user with numbers. No transform lands from this brief.**

## The hypothesis

Frames are sized SUM-OF-ALL-EMBEDS today: every suspending call
site's callee frame owns a distinct offset, even where two callees
can never be live at once. Sub-frame liveness is strictly nested, so
sequential awaits at one level and exclusive branch arms can SHARE
storage — sizing the frame by the DEEPEST LIVE CHAIN (the high-water
mark) instead of the sum. Rust/C++ coroutines both do this.

## Units

1. **Measure reality.** A debug flag or analysis tool
   (`--emit-frame-layout` or `tools/framesizes.py` driving the
   compiler's existing frame builder) reporting, per monomorphized
   suspending function: total frame size, own-locals size, each
   embedded child (callee, offset, size), and per-task spawn cost.
   Sweep the corpus + blade + sos; report the distribution and the
   top offenders.
2. **Compute the hypothetical.** From the existing state machine,
   compute the overlay-feasible size per function (max over
   simultaneously-live sets rather than sum), WITHOUT building the
   transform — the state graph already says which children can be
   live together. Report absolute and relative savings, corpus-wide
   and for the flagship shapes (accept-loop server, blade's deps
   walk, sos root).
3. **Enumerate the correctness constraints** — the Saw-specific ones
   especially, each with a verdict (compatible / needs work / blocks):
   - `lend` windows: a borrows-accessor frame is live THROUGH its
     suspension until the epilogue — liveness is lend-until-epilogue.
   - State-aware teardown: design 124/134's `__release` drops owned
     across-suspend values on cancellation — with overlay, slot
     contents depend on the state index; establish whether release is
     already state-keyed or would need to become so.
   - Design 158's backtrace tables: (function, state) → child offset
     stays static per state under overlay — confirm the encoding
     survives.
   - Held references (design 88/106) and re-borrows: pointers into a
     sub-frame must not outlive it — establish whether any legal
     program can hold one across the reuse boundary.
   - The DF-138a spawn trampoline and generation-checked slots (134).
4. **Recommendation.** Implement / decline / partial (e.g. overlay
   only branch arms, which dodges the sequential-liveness analysis),
   with the numbers attached and a sketch of the transform's shape
   and test plan if implementing. The user decides.

## Constraints

Read-mostly: the measurement tooling may land (it is generally
useful — 152's task-frame-size warning wants the same data), but no
layout change ships from this brief. Full battery only if tooling
lands (suite zero xfails, lexdiff, astdiff, irdet --all, bootstrap,
sos_runner, gmgate).

## OUTCOME (Aug 7) — investigation complete, awaiting the user's call

Full report: **`designs/todo.md`, "Design 163 — frame-overlay sizing:
the INVESTIGATION REPORT"**. Summary:

**Landed (tooling only, no behavior change):** `sawc
--emit-frame-layout` (`sawc/frame_layout.py`) and
`tools/framesizes.py`, plus two read-only stashes in
`coro_transform.py` (`info['drive_state']`,
`frame_struct.coro_frame_info`).

**Unit 1 — reality.** 339 monomorphized frames across the 103
`examples/` programs that suspend. **blade and the SOS kernel have NO
coroutine frames at all** (both are entirely synchronous), so two of
the three flagship shapes do not exist. Sizes: p50 72 B, p99 672 B,
max 688 B. 80% of frames have zero embedded children; only 9% have the
two-or-more that overlay needs. Nothing exceeds three children.

**Unit 2 — the hypothetical.** Every `__subN` is live in exactly ONE
resume state; the tool checks this rather than assuming it, and found
**zero violations across all 339 frames**. Corpus-wide saving
**13.1%**; restricted to frames that can shrink, **35.6%**. 83% of
spawn roots do not move. The accept-loop server saves **0%** (one call
site; its bulk is a 296-byte `TaskGroup` local). But a synthetic probe
shows the model is O(branching^depth) where the overlay is O(depth):
depth alone saves nothing, while a branching-2 tree goes 45% -> 69% ->
82% over three levels and a 6-call-site root is **6768 B -> 928 B,
7.3x**.

**Unit 3 — constraints.** Five of six are **compatible**: lend windows
(a `borrows` accessor is force-`sync`, so it has no frame and a window
makes zero children live), design 158's tables (they get simpler — the
offset becomes constant and only the child type varies by state), held
references (seeded pointers always run child -> parent, and the
suspending `-> &T` case is closed on both the spawn and driven paths),
the DF-138a trampoline, and generation-checked slots (entirely in
`TaskGroup.gen`/`TaskHandle`, never in a frame). The one that
**needs work** is teardown: `__release` is NOT state-keyed and
deliberately excludes sub-frames — child storage is reclaimed by the
frame struct's MEMBERWISE drop, which recurses by static field type.
Three enumerated sites would need state-keying.

**Unit 4 — recommendation: DECLINE now, with a trigger.** The brief's
suggested cheap partial (branch-arms-only) should be declined on its
own terms — it exists to dodge a sequential-liveness analysis that
turns out to be already exact and free, so it is more work for less
saving. The real choice is implement-in-full vs decline, and the
corpus does not justify paying for state-keyed teardown (the path that
produced a silent double-free in each of 124/131/134/146) to fix a
problem no program in the tree has. Instead: hang **design 152's
task-frame-size warning** off this tooling's data (suggested: warn
above ~1 KB, and when `sub_bytes` exceed `own_bytes` by >2x — the
corpus trips neither), and revisit 163 the first time a real program
trips it. The transform sketch and a test plan are recorded in the
tracker so picking it up later is cheap.

**Three DF findings**, all pre-existing and none blocking: **DF-163a**
`-> &T` escapes the parameters-only rule (`return &local` compiles and
dangles); **DF-163b** a nested `yield_now()`/`sleep()` silently does
not cede (the helper is suspending when spawned directly but is
emitted as a plain sync call when called from another suspending
function — worth its own brief); **DF-163c** an unanchored `0:0`
diagnostic on the driven `-> &T` path.

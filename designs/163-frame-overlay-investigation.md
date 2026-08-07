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

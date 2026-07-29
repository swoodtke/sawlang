# Design Brief 45 — Async stage 2b: cooperative executor, suspending primitives, cancellation

**Source:** paper 18 (core executor design, never-block invariant,
structured concurrency C1, explicit-only cancellation + the
no-forced-destroy ruling) on top of brief 44's transform. QUEUED —
write-time refinement expected after 44's report (the resume protocol
it chose is this brief's interface).
**Scope:** hosted, single-threaded cooperative executor + the minimal
suspending primitive set + the cancellation surface. NOT here:
multi-threaded work-stealing (A2), IO reactor (A4), freestanding
static-task executor (stage 2c — but do nothing to preclude it: the
executor core must not assume an allocator beyond task spawn itself),
effect-polymorphism re-inference (A5 — only if 44/45 hit a concrete
need, else next stage).

## REFINED (Jul 29, post-44): 44's landed protocol is the interface —
frame struct + `resume(&var self) -> __Poll {Pending, Done}` with the
result frame-resident in `__result` (read after Done; never returned by
move). The transform triggers on driven roots. 44 left three CLEAN
COMPILE-ERROR BOUNDARIES that are prerequisites for real async
programs — they are now Part 0 of this brief:

### 0a. Conditional move of a frame local across a suspend
The stated Bool-drop-flag design: frame-resident `Bool` flags cleared
WITHOUT dropping (the optional-encoding can't express clear-without-
drop). Extends brief 42's drop-flag codegen to frame fields. Flip 44's
boundary rejection into working code + the deferred matrix test.

### 0b. Nested suspending calls (by-value frame embedding)
Callee frame embedded in caller frame; caller state machine drives the
callee sub-frame to Done across its own suspensions. Two-deep test
from 44's matrix.

### 0c. Driving methods (`&var self` across suspension — the D6 case)
Receiver reference held in the frame (a pointer into the task root's
storage — sound per D6 task confinement). The 44 matrix's D6 test.

Also lift, if they fall out of 0a–0c naturally (report if not):
suspends inside loops/matches spanning a suspension; generic driven
functions (note: the effect-polymorphism item A5 may be the real
blocker there — do not build A5 here, just report).

## Items (original sketch, now on the landed protocol)
1. **Executor core:** single-threaded run queue draining resumable
   frames (paper 18: "a few hundred lines"); park/wake via the
   simplest hosted mechanism; entry point runs a root task to
   completion (`main` may suspend — the compiler provides the entry
   executor when main is inferred suspending, per paper 18).
2. **Cooperative task spawn:** spawn of a suspending closure →
   heap-allocated frame (Global) + handle; structured join (scope exit
   joins — C1); the existing pthread spawn/Task from 21b stays
   untouched (thread-vs-task unification is stage 3; name the
   coexistence honestly in docs).
3. **Cancellation surface:** `Task.cancel()` sets the flag;
   `Task.cancelled() -> Bool` checks it; cancellation-aware waits
   return through normal control flow. No forced destroy exists.
4. **Suspending primitives (minimal forcing set):** `yield_now()`;
   `sleep(ms)` (simplest correct hosted timer); a suspending
   `Channel.receive` form with a cancellation-aware variant
   (Optional-returning). Wire as real effect sources (replacing
   brief-44's synthetic `__suspend` in user-facing code; the synthetic
   stays test-only).
5. **Tests:** two tasks interleaving deterministically via yield;
   sleep ordering; producer/consumer over the suspending channel;
   cooperative cancel observed at a check and at a cancellation-aware
   receive (cleanup verified by deinit oracle); structured join at
   scope exit; main-suspends entry path.
6. **Docs:** LANGUAGE_SPEC concurrency section (the runtime model as
   shipped); CLAUDE.md.

## Hazards
Executor + transform integration is where stage-2 reality bites — if
44's resume protocol needs adjustment, adjust 44's protocol in a
follow-up commit rather than contorting the executor; report it.
Deinit oracle + concurrency families at every checkpoint.

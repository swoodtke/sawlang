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

## Items (sketch — refine against 44's landed shape)
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

# Design 183 — the offload story, made real (design 103 v2)

**Status: APPROVED direction (user, Aug 8: "this is a good test case for
the offload story. let's offload the libc sync call properly"). This brief
is the MACHINERY half; design 184 (resolution) is its first real consumer
and the acceptance test. Closes DF-181e (the whitelist) and DF-181f (the
silently-ignored annotation) — the audit's gating finding becomes unit 1.**

## Units

1. **DF-181f — the contract holds everywhere.** `blocking` on a
   `__saw_rt_*` seam either offloads or errors cleanly, exactly as design
   103 promises for every other extern; the silent-ignore path dies. Pin
   with the audit's own control probe shape (annotated seam, sibling's
   first tick at ~0ms).
2. **The signature whitelist widens to the C-ABI export set.** An
   `extern blocking func` may take any signature whose types the @export
   whitelist already admits (fixed-width ints, Int/UInt, UnsafePointer,
   Void/Never return — no String/Bool/aggregates by value): the offload
   thunk marshals N argument slots instead of one, reusing the compiler's
   existing C-ABI lowering. Return stays one slot. The (Int)->Int
   restriction and its error message are deleted; a signature OUTSIDE the
   export set gets the same clean error @export gives.
3. **Pointer-argument lifetime discipline (the sharp edge — decide it,
   write it down).** An offloaded call's pointer arguments must outlive
   the call: the RULE is that they point into storage owned by the
   suspended frame or the heap (both survive the park by construction —
   frames are heap-resident across suspends since design 88). A stack
   temporary in a sync caller cannot reach an offload (blocking is illegal
   in sync contexts already — verify the fence holds and state it in the
   spec's unsafe/extern section).
4. **Cancellation semantics restated for v2**: cancel wakes the parked
   task; the in-flight C call is never aborted (`take()` joins first —
   design 103's existing rule, now with pointers in flight it matters
   more: the frame must not release pointed-to storage until the join).
   Test the cancel-during-offload path with a multi-arg call.
5. **Docs**: spec (extern blocking section rewritten for v2), skill
   (the offload idiom + the pointer rule), rt/ABI.md note. Tracker:
   DF-181e/f closed.

## Gates

Full battery per unit + the 180-style stability standard for scheduler
tests (ten repeats). QUEUE: after DF-172j's agent lands (shared codegen
surface). Design 184 dispatches only after this brief is green on main.

## Explicitly out

Thread-pool tuning (thread-per-call stays, per design 103 v1); offloading
anything in std (184 owns the first consumer); Bool/String/aggregate
marshalling; async cancellation of in-flight C calls.

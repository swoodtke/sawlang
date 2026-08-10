# Design 196 — the coroutine transform meets erased errors and captures

**Status: RULED + AUTHORED Aug 10 (morning review, cluster A), ready to
queue. Four capability gaps, one subsystem: the coroutine transform does
not yet handle shapes the language's stated position (colorless
concurrency composes with erased errors and closures) says must work.
All four are pinned XFAIL; none is a design question — the design is
settled, the transform has not caught up. coro_transform + codegen
result-cell surface; serial with anything touching either.**

## Units

1. **DF-192b — spawning an erased-error function.** `group.spawn(f)`
   where `f -> Result<T, Box<any Error>>` dies filling the result
   cell's vtable; the concrete `Result<Int, MyErr>` spawn works. Fix
   the result-cell lowering for the erased payload. PIN to flip:
   `examples/erased_error_spawned_task.saw`.
2. **DF-192c — an erased-error return in a suspending body.** The
   transform moves the auto-box wrap out of return position and
   `_create_result_err_for_return` finds a state-machine step where it
   expects the wrap. PIN to flip:
   `examples/erased_error_across_suspension.saw`.
3. **DF-193a — a suspension inside a `try { } catch { }` block.** The
   big one: the state machine needs error-path states (the catch arm
   is a resume target reachable from every suspending call in the try
   body). `try { let d = try stream.read() } catch { ... }` is the
   natural erased-error spelling of task I/O, so this gap bites real
   code. Follow design 120's ANF discipline: evaluation order and
   short-circuits preserved; a shape the state machine genuinely
   cannot express STOPS and files rather than silently blocking
   (design 96's law). PIN to flip:
   `examples/coro_try_block_suspending.saw`.
4. **DF-191a — a sync closure capturing frame-resident locals.** A
   `Mutex.lock` body that captures a local of the driven function is
   refused by the transform, and the hint's workaround (bind the
   closure to a `let`) trips the sync-closure-literal rule — no legal
   spelling for the canonical shared-counter idiom. Teach the
   transform the position: a closure literal passed directly to a
   sync-closure parameter inside a driven body, its captures reading
   frame slots. PIN to flip: `examples/conformance/K13_mt_sum_under_mutex.saw`
   (+ its INDEX row updates from XFAIL to covered).
5. **Docs + lane.** Spec/skill wherever a "not yet" fence is now
   capability (the skill's concurrency section names none of these
   four as fences — verify nothing else does either); each fixed shape
   gets a gmgate concurrency-lane entry (they are exactly the
   frame-handoff shapes the lane exists for).

## Gates

Per-unit commits, tracked battery each; irdet --all (transform changes
are lowering changes); the gmgate concurrency lane at -n 5 on the new
entries. Zero uncited xfails at the end. A unit whose fix reveals a
genuine design question (unit 3 is the candidate) STOPS and files.

## Explicitly out

DF-192d (separate ruling, design 198); the suspension-spanning `match`
move-scrutinee fence and tuple-pattern `if let` fence (documented v1
fences, not in these findings); any executor/scheduler change.

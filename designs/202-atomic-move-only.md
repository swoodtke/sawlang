# Design 202 — `Atomic` is move-only

**Status: RULED + AUTHORED Aug 10 (morning review). DF-186a decided by
census: copying an `Atomic` silently forks the counter and has been
footgun-shaped since design 41; Rust agrees (`AtomicUsize` is `!Copy`);
and the migration is SMALL — the Aug-10 census found, outside examples,
exactly TWO holder structs without a policy (`std/slab.saw SlabHead`,
`rt/common/offload.saw Job`; SpinLock/Once/TaskGroup already declare
NoCopy), THREE example counter structs, ZERO non-static Atomic locals,
and statics are unaffected (a NoCopy static is legal — SpinLock statics
prove it). Ruling: an `Atomic` FIELD contributes `NoCopy` to its
container, so holders declare a policy like any other NoCopy-containing
type. The general cell clause is UNTOUCHED: design 186's "a cell field
contributes its T's copy class" stays for user `UnsafeMutableInterior`
wrappers — this brief moves ONE type, not the property.**

## Units

1. **Conformance rows first (obligation 3).** V-family rows: `let b =
   a` on an `Atomic<Int>` local (reject, names NoCopy); an undeclared
   struct holding an `Atomic` field (reject, the containment error
   naming the field); the declared-NoCopy holder (accept); a `static
   N: Atomic<Int> = Atomic(0)` with `fetch_add` through `&` access
   (accept — statics unaffected); `move` of an Atomic local (accept).
2. **The tier change.** `Atomic` declares/derives `NoCopy` (whichever
   spelling fits its builtin.saw declaration — mirror how SpinLock
   carries it), and `member_copy_tier`'s cell clause is verified to
   let the declared policy WIN for Atomic while user cell wrappers
   keep the design-186 behavior. One clause, negative-tested both
   ways.
3. **The migration.** `extension SlabHead: NoCopy {}` +
   `extension Job: NoCopy {}` + the three example counter structs
   (`atomic_field_self_method`, `shared_self_field_call_exemption`,
   `static_atomic_counter`); fix whatever copies the suite then
   refuses (census predicts: none — every current use is a static, a
   `&` param, or construction-in-place). The consumer sweep
   (obligation 2) IS this unit: record what the suite flushed.
4. **Docs.** Spec Atomic section ("move-only; share via `&`/static, a
   copied counter was never one counter"); skill global-state bullet
   gains "NoCopy" beside Atomic; tracker DF-186a entry closes.

## Gates

Per-unit commits, tracked battery each; irdet --all. Unit 3's
flush-list is the review surface — if it is NOT small (census wrong
again), STOP and report before migrating the world.

## Explicitly out

`Atomic<T>` beyond `Atomic<Int>` (the v1 limit stands — DF-186c's
pointer-atomics gap is separate); `NoMove` for Atomic (nothing pins its
address today — the futex word is reached through statics); any change
to the design-186 cell-carrying property or `UnsafeSync` rules.

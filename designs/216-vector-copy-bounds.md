# Design 216 — lifting `T: Copy` off the Vector closure and sort APIs

**Status: PROPOSAL, not scheduled, no units authored.** Every claim below is
probe-verified against the current tree; the probes are named per section and
live in `.build/scratch/` until they become tests.

## The finding

Five `Vector` methods carry a `T: Copy` bound their algorithms do not need:
`map`, `each`, `each_indexed`, `fold` and `sort`. The bound is real for
`iter`/`enumerated` and inherited by everything sharing their extension block —
the code says so itself, above `iter()`:

```
// `T: Copy` — the SAME bound `each`/`map`/`enumerated` carry, and for the
```

The consequence is that a `Vector` of move-only elements — a `Vector<File>`, a
`Vector<Job>` where `Job` owns a handle — cannot be mapped, iterated with a
closure, folded or sorted at all. That is a large hole in the collection API,
and it is not one the ownership model requires.

## Where the bound actually comes from

**For the closure methods, the SIGNATURE, not the body.** `map` is declared
`transform: (T) -> U`, taking the element BY VALUE, so its body reads the
element out of the vector:

```saw
if let elem = self.get(i) {
    result.push(transform(move elem))
}
```

A value read out of a place consults the copy tier, which is what demands
`T: Copy`. Nothing else in `map` needs it.

**For `sort`, one helper.** `sort` itself only calls `swap` — which lives in the
UNBOUNDED extension and moves bytes without duplicating — and `_greater_at`,
which reads both operands out by value:

```saw
func _greater_at(&self, i: Int, j: Int) -> Bool {
    if let a = self.get(i) {
        if let b = self.get(j) { return a > b }
```

So the movement half of sorting was never the problem. The comparison half is.

## What the probes establish

1. **A by-reference `map` works over NoCopy elements** (`map_ref_probe.saw`).
   Written from OUTSIDE std over the public `with_ref`, so it needs no compiler
   change and no new internals. The vector still owns its elements afterwards.

2. **The transform need not be `sync`** (`refclosure_probe.saw`). A closure
   parameter `(&T) -> U` typechecks unmarked and its body may suspend — a
   transform calling `yield_now()` runs correctly. So switching to `&T` does NOT
   trade away suspending transforms. The `sync` on `with_ref` is that method's
   own scoped-window constraint, not a language limit on reference-taking
   closures.

3. **NoCopy elements APPEAR to compare through borrows — via a compiler hole**
   (`sort_cmp_probe.saw`, `sort_cmp_sound.saw`, then `cmp_consume_probe.saw`).
   `a > b` on two `&T` bindings compiles and runs, and 200 repeats leave
   elements holding a refcounted `String` intact. That looked like a capability.
   It is not: see DF-216b. The operator bypasses the transfer checkpoint that
   the identical direct call `a.compare(b)` correctly refuses, and the bypass is
   unsound. **The `sort` half of this proposal cannot rest on it.**

4. **A NoCopy `Vector` sorts end to end** (`sort_nocopy.saw`) using only `swap`
   and borrowed comparison — the same insertion sort std already has, with the
   by-value reads replaced. Five `Job` elements, correct order out, no `Copy`
   anywhere. Correct as written, but it is standing on DF-216b: it compiles only
   because the operator skips the check, and a `Comparable` conformance that
   moved its `other` would corrupt the vector under it.

## Proposal

- Move `map`, `each`, `each_indexed` and `fold`'s element parameter to the
  unbounded extension, with `&T` element closures.
- Rewrite `_greater_at` to compare through borrows and drop `Copy` from `sort`'s
  extension, leaving `T: Comparable` — **but only after DF-216b is fixed.**
  Today that rewrite compiles for the wrong reason, and shipping it would build
  std on top of the hole. `Comparable`/`Equatable` taking `other: &Self` is the
  fix that makes it legitimate, and it is a prerequisite rather than a
  follow-up.
- `iter`, `enumerated` and `VectorIterator` KEEP `T: Copy`: `Iterator.next()`
  yields an element the consumer owns, which is a real constraint (design 122),
  not an inherited one.

## DF-216a — ICE: a closure naming `self` inside a method

Found while writing the borrow-based comparison, and it blocks the natural
spelling of it.

```saw
extension Counter {
    func viaFree(&self) -> Int {
        call({ v in self.n + v })
    }
}
// internal compiler error at N:C (SelfExpr): 'self' not found in current scope
```

Twenty-line repro (`ice_self_closure.saw`, `ice_self_variants.saw`). ANY closure
whose body names `self`, inside any method, fails this way. NOT specific to the
closure being an argument to a method on `self` — handing it to a free function
fails identically, so the trigger is the identifier, not the receiver.

Two workarounds, both verified (`ice_workaround.saw`, `self_param_probe.saw`):
hoist `self.field` into a local before the closure, or hand `&self` to the
closure as an explicit parameter (`body: (&Counter, Int) sync -> R` called as
`self.run({ c, v in c.n + v })`). The second is what makes a std-side
`_greater_at` rewrite expressible.

A corpus grep found ZERO closures naming `self` anywhere in std, which is why
this has gone unseen. It is an ICE, so by the design-192 fuzzing oracle it is a
finding on its own terms regardless of this brief.

## DF-216b — SOUNDNESS: the comparison operators bypass the transfer checkpoint

The sharp one, and it is independent of everything above.

`Comparable.compare(&self, other: Self)` and `Equatable.equals(&self, other: Self)`
take the second operand BY VALUE. On a NoCopy type the two spellings of the same
call disagree:

```saw
a.compare(b)    // correctly refused: "cannot copy value of type `Tag`
                //   which implements NoCopy"; hint: use `move`
a > b           // COMPILES — same call, same operands
```

The operator path then passes `other` by REFERENCE: ten comparisons of a
two-element vector produce exactly two deinits, so nothing is being consumed
(`cmp_consume_probe.saw`). That is why it looked harmless.

It is not harmless, because the signature entitles the callee to own what it was
given. A conformance that exercises that right corrupts the caller
(`cmp_move_probe.saw`):

```saw
func compare(&self, other: Tag) -> Ordering {
    let taken = move other      // legal for a by-value parameter
    ...
}
```

Three comparisons of a two-element vector, and the run prints FIVE deinits —
three during the comparisons, two at teardown. The same element is destroyed
four times, from fully safe code with no `unsafe` at the call site. With a
refcounted or heap-owning field that is a use-after-free. It is the DF-132a
shape (`Vector.get`'s own regression note) reappearing at the operator lowering.

Two things are wrong and they want fixing together:

1. **The check is missing on the operator path.** Whatever `a.compare(b)` runs
   through, `a > b` does not. That is a funnel problem in design 190
   obligation 1's terms: one rule, two entry points, and the second bypasses it.
2. **The signature is wrong.** `other: Self` claims ownership the lowering never
   transfers. `other: &Self` on `Comparable` and `Equatable` would make the
   declaration describe what actually happens, legitimise NoCopy comparison, and
   remove the callee's ability to move the operand — closing the hole by
   construction rather than by adding a check.

Fixing only (1) would make `a > b` a clean error on NoCopy types and leave them
uncomparable. Fixing (2) is what the collection API wants. It changes a core
trait signature and every conformer with it, so it is its own brief; this one
records the evidence and the dependency.

## Open questions

- **Source compatibility of the `&T` switch.** `{ $0 * 2 }` and
  `{ $0.to_string() }` are unaffected: reading a reference binding yields the
  value, and method calls work through it. The sharp edge is forwarding — a
  closure passing its element to another `&T` parameter needs `&n`, not `n`
  (hit while writing `refclosure_probe.saw`). A corpus sweep is owed before the
  change, per obligation 2.
- **Borrow across suspension.** A non-`sync` transform lets a borrow into the
  vector's buffer span a suspend. Exclusivity should cover it — `map` holds
  `&self`, so no concurrent `&var self` — but that is a ruling, not something
  these probes establish.
- **Does DF-216b reach further than the comparison operators?** The same
  question applies anywhere an operator lowers to a trait method with a
  by-value `Self` parameter — arithmetic operators over user conformances are
  the obvious place to look. A position matrix is owed before the fix, per
  obligation 1.
- **Sequencing.** The `map`/`each`/`fold` half stands alone and could land
  first; the `sort` half is blocked on the `&Self` change. Splitting them is
  probably right.

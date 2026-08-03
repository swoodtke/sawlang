# Design 108 — ICE: generic parameter with a default VALUE (queued Aug 3)

Found by the design-105 agent while probing labeled-reorder cases
(pre-existing on the clean tree, out of 105's scope; queued per
fix-on-discovery as the tail of the 102-107 batch).

## The bug
`func f<T>(a: Int, b: T = 0)` — a generic function whose type-param-
typed parameter carries a DEFAULT VALUE — ICEs with
`list index out of range` (instead of either working or a clean
diagnostic). Distinguish from default TYPE params (`<T = Int>`,
design 37 — those work).

## Scope
1. Root-cause the index error (likely the defaults machinery indexing
   the param list against a call's explicit args without accounting
   for the generic param, or the default expression being checked
   before `T` is bound).
2. Decide the semantics and implement: the expected behavior is that
   the default expression type-checks AGAINST THE INSTANTIATED `T`
   per call (`f(1)` with `T` uninferable from remaining args -> the
   default's own literal can drive inference: `b: T = 0` at a call
   `f(1)` should either infer `T = Int` from the default (preferred —
   it is the expected thing) or error cleanly naming `T` as
   underdetermined. If default-drives-inference is disproportionate,
   the clean underdetermined error is acceptable v1 — flag which
   landed.
3. Never an ICE: whatever lands, the failure mode is a clean anchored
   diagnostic.
4. Tests: `f(1)` (default used) and `f(1, 2)` (default overridden)
   for `b: T = 0`; a non-inferable default (`b: T = 0` with
   `T: SomeTrait` Int doesn't satisfy -> bound error naming the
   inferred type); explicit `f<Float>(1)` type-checks the default
   against Float (0 adopts Float per literal rules or errors
   cleanly); interaction with design 105 overloads (a defaulted
   generic overload in a set).
5. Docs: skill/spec only if semantics are user-visible beyond the
   fix; tracker (flag closed).

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit. Standing policy; foreground suites; interruption-safe; skill
self-review.

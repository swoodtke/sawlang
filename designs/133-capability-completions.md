# Design 133 — capability completions: Arc method-generic forwarding + nested short-circuit suspension

STATUS: APPROVED (user, Aug 5). Two self-contained "finish what an earlier
design started" units (the 122 grab-bag mold). Dispatch order: after design
132 (pipeline 130 → 131 → 132 → 133 → 134). Closes DF-123c (unblocking
review M1) and DF-125a.

## Units

- **A. Arc payload-method forwarding learns method-level generics
  (DF-123c), then `Mutex.lock` returns the closure's own type (review M1).**
  Today `_resolve_arc_forward` (typechecker) does not solve method-level
  type arguments at a forward site, and `calls.py::
  _generate_arc_forward_call` mangles the payload method with the
  NON-generic `_mangle_method_name(base, name)` — so a method-generic
  payload method forwarded through `Arc<T>` looks up a symbol the
  monomorphizer never emits and ICEs (`internal compiler error:
  'Mutex$1$Int_lock'`). Fix both ends: the forward resolution runs the same
  method-generic inference the ordinary call path already has (designs
  36/93/105 machinery), and codegen mangles with the resolved arguments so
  the right monomorph is requested/emitted. Regression: a method-generic
  method on a struct held in an `Arc`, called through the Arc, for at least
  two distinct instantiations.

  Then the payoff, as its own commit: `Mutex.lock` becomes generic over the
  closure result (`lock<R>(body: (T) -> R) -> R` shape — final signature per
  the existing lock API conventions), so a value can be computed under the
  lock and returned ("expected, not easy"). Existing `-> Bool` callers keep
  compiling (R = Bool). Same treatment for any sibling std API the sweep
  finds locked to a fixed result type for the same reason. Spec + skill +
  README where the mutex examples change. Closes M1 in the tracker.

- **B. The ANF hoist lifts NESTED short-circuits (DF-125a).** Design 120
  transforms a suspending call in a `??`/`&&`/`||` operand only when the
  operator is the OUTERMOST expression of its statement; `f(a ?? slow())`,
  `return 1 + (a ?? slow())` and `not (a && slow())` error cleanly today
  (same for a blocking extern in those positions). Close the gap with the
  mechanism 120 already uses: hoist the ENTIRE short-circuit expression to a
  statement-level temp (the already-supported outermost form — laziness and
  evaluation order preserved by construction), substitute the temp, recurse
  for nesting. Regression tests: the four tracker repro shapes, a
  doubly-nested case (`g(f(a ?? slow()))`), a blocking-extern variant, and
  short-circuit laziness asserted (the RHS must NOT run when the LHS
  decides). Delete the "nested short-circuit" limitation notes design 125
  added to spec + skill. Closes DF-125a.

## Exit criteria
Fail-before/pass-after tests per unit; full gate battery green (suite,
lexdiff, irdet, astdiff, bootstrap, sos); tracker DF-123c, M1, DF-125a
closed; docs updated per the design-125 convention.

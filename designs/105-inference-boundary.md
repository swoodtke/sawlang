# Design 105 — generic inference: overloads, later-arg solve, labeled args (queued Aug 2)

Final pre-SOS batch, part 4 of 6. Extend design 93's inference past
its three explicit-args-still-required boundaries.

DECISION MADE WITHOUT THE USER (review tomorrow): design 93 excluded
overload sets to avoid manufacturing ambiguity. Resolution chosen:
run inference PER CANDIDATE across the overload set; if EXACTLY ONE
candidate both solves and type-matches, pick it (this cannot change
the meaning of any currently-compiling call — those needed explicit
args); if two or more solve, a clean ambiguity error listing the
solving candidates and their solved type args ("give explicit type
arguments or labels"). Never a silent pick — design 55's exact-match
model and never-hide-errors hold.

## Scope
1. Overload sets (the decision above) — free fns and methods.
2. Later-arg solve: replace the single left-to-right pass with a
   fixpoint over the argument list (repeat passes until no new
   solutions; closures still solved after non-closure args within
   each pass, matching design 93's closure-return ordering). A param
   gated by an argument to its RIGHT then solves. Termination: bounded
   by param count.
3. Labeled + out-of-order args: map arguments to parameters BY LABEL
   first (the design-38 labeled-call machinery), THEN unify — so
   inference sees the correct param<->arg pairing regardless of call
   order. A labeled call must never mis-map positionally again (the
   design-93 report's known wrong-mapping case becomes a test).
4. Diagnostics: ambiguity error as specified; underdetermined/conflict
   errors unchanged from 93.
5. Tests: unique-solve overload picked (Data vs String style);
   ambiguous overload errors listing candidates; explicit args still
   win; later-arg solve (T only determined by arg 2/3, incl. a
   closure-before-value ordering); labeled out-of-order inferred call;
   design-93 suite stays green; driven/spawned inferred overloads
   (design 95 frame keying must see the resolved candidate).
6. Docs: skill + spec inference-boundary story updated; tracker.

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit. Standing policy; foreground; interruption-safe; skill
self-review.

# Design 166 — diagnostics unification

**Status: APPROVED (user, Aug 7, from the repo-review triage).
Sequence: after [M1b ∥ 155 ∥ 165], before 167.**

## The problem (review findings, verified citations as of beabe78)

97 bare `raise ValueError` sites in `codegen/` funnel into the
catch-all at sawc.py (~:532) and print as `internal compiler error`
with NO source location — and a meaningful fraction are plainly USER
errors: "Type {X} does not implement Iterator" (codegen/loops.py),
"cannot copy value of type X: it is not Copy" (codegen/calls.py),
five separate copies of "Undefined variable". sawc.py (~:513) already
documents the gap. Beyond that: SIX competing error mechanisms
(ErrorReporter; parser/lexer plain SyntaxError with first-error abort
and no caret; the codegen ValueErrors; five bespoke exception
classes; ~16 hand-formatted print+sys.exit sites in sawc.py; and a
SyntaxError subclass used as parser BACKTRACKING control flow —
GenericListTrailingComma — that any intervening `except SyntaxError`
would swallow).

## Units

1. **Codegen user-errors become real diagnostics.** Triage all 97
   sites: USER-error sites route through ErrorReporter with the
   node's source location (the resolved_type/line stamps are there —
   design 122's ICE-vs-diagnostic line is the precedent); genuine
   invariant violations stay exceptions but say "internal compiler
   error" honestly WITH the node context. Every reclassified site
   gets an error test (examples/errors/) proving location + message.
2. **The silent typechecker fallthroughs RAISE.** Unknown expression
   node → `return None` (typechecker/expressions.py ~:63) becomes a
   loud ICE like codegen's equivalent — a missing visitor fails at
   the front, not as a back-end ICE at a distance. Same for the
   statement-side twin if one exists.
3. **Visitor-drift audit**: LendStatement/RangeExpr have checker
   visitors but no codegen visitor, ErasedErrWrap the reverse —
   establish for each whether the asymmetry is by-design (lowered
   away before codegen — document it where the visitor would be) or
   a latent hole (add the visitor + a test).
4. **Mechanism consolidation where cheap**: the bespoke exception
   classes and print+exit sites in sawc.py collapse toward
   ErrorReporter where they carry user-facing text; the
   backtracking-control-flow SyntaxError subclass gets its own
   exception type that nothing else can accidentally catch.
   Parser/lexer multi-error recovery is OUT of scope (first-error
   abort stands — that is a separate, larger design).

## Gates

Full battery via ./.venv/bin/python: suite (zero xfails), lexdiff,
astdiff, irdet --all, bootstrap, sos_runner, gmgate. Error tests for
every reclassified diagnostic. Tracker: findings as DF-166x.

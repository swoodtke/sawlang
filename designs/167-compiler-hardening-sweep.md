# Design 167 — compiler hardening sweep

**Status: APPROVED (user, Aug 7, from the repo-review triage).
Sequence: after 166. The expressions.py god-file SPLIT is explicitly
OUT — deferred to the rewrite-track conversation.**

## Units (review findings, citations as of beabe78)

1. **Unify the must-agree duplications — the scary ones first.**
   `_make_specialization_key` exists independently in the typechecker
   (~expressions.py:5669) and codegen (~generics.py:534) at 14 vs 15
   branches: FIRST establish whether the branch delta is drift (a
   shape one side keys and the other does not = generic
   instantiations silently diverging — if so that is a live bug,
   fix + test before unifying); then ONE shared implementation both
   sides import. Same treatment for `_pointer_size_bits`
   (target_info.py vs codegen/core.py) and `_pattern_binding_names`
   (×3).
2. **Close the fail-opens.** typechecker/types.py ~:1287 returns
   "compatible" when either type is None (make it raise — a None
   type reaching compatibility is a missing-stamp bug); ~:189's
   str(t) mangling fallback (a mangling bug becomes a WRONG-IDENTITY
   comparison — raise instead); the TWO visibility-checker fail-open
   defaults (namespace.py ~:1839, ~:1951 — the design-80 gate must
   fail CLOSED); codegen/structs.py ~:274 reverse-engineering the Saw
   type from the LLVM type instead of reading resolved_type. Each
   closure validated by the full suite — if closing one turns up
   in-tree reliance, that reliance is a bug to fix, not a reason to
   stay open (record as DF-167x).
3. **FunctionContext extraction.** Per-function codegen state is
   saved/reset/restored by hand in closures.py, generics.py,
   methods.py with inconsistent discipline (one finally, one not, one
   resets without saving). One context object, one enter/exit
   discipline, behavior-identical (irdet --all is the oracle).
4. **Dead-code + tombstone sweep (~270 lines)**: visitor.py (entirely
   dead, its dispatch re-implemented four times — delete or adopt,
   do not keep both); the 11 dead functions the review lists; the 6
   stale pre-split tombstone comments in codegen/core.py. Verify
   each is genuinely dead (grep + suite) before deletion.

## Gates

Full battery via ./.venv/bin/python: suite (zero xfails), lexdiff,
astdiff, irdet --all (the decisive oracle for units 1/3), bootstrap,
sos_runner, gmgate. Per-unit commits. Tracker: DF-167x findings,
especially the unit-1 drift verdict — report it PROMINENTLY either
way, since "14 vs 15 branches, no divergence" is load-bearing good
news and "drift found" is a P0-adjacent catch.

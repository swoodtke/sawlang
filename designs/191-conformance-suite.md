# Design 191 — the standing conformance suite

**Status: AUTHORED from design 190's analysis (Aug 9), awaiting user
approval to queue. Payoff (matrix evidence): 13 of the week's ~32 findings
were catchable by exactly this suite at the landing of the offending
design — the Aug-8 audit found 9 holes in ONE pass; this makes it every
pass. Cost (census-priced): 1-2 agent sessions, ~+10 seconds on the ~60s
suite, ZERO test-runner code changes required.**

## Units

1. **The corpus lands.** `examples/conformance/<ID>_<slug>.saw` — the
   audit's 247 rows, curated: (a) rows already equivalent to an existing
   examples/ test are NOT duplicated — the row's entry in the INDEX
   (below) points at the existing test instead (census: ~60-70% overlap);
   (b) genuinely new rows (~80-100 after dedup) port with content
   assertions synthesized from the audit's `results.json` (each reject
   row's actual first error line → `EXPECT-ERROR-CONTAINS`; `panic at`
   for panic rows; a print line for run rows); (c) rows whose
   expectations the 186-189 RULINGS superseded are re-authored to the
   RATIFIED behavior (the spawn-capture family per 189, the NoMove move
   errors, the exclusivity diagnostics that replaced copy-policy
   refusals) — the audit's original guess is never the oracle; (d) the
   three helper modules move to `examples/conformance/modules/{dep,mid,deep}`
   (auto-excluded from discovery, reached via `{TESTDIR}`).
2. **The index.** `examples/conformance/INDEX.md`: one line per audit
   row — id, claim source (spec section or design NN), and either its
   conformance file or the existing test that covers it. This is the
   auditable "every claimed guarantee has a checked row" ledger, and the
   dedup decision record.
3. **The `EXPECT: compiles` directive** (small runner addition, the one
   optional nicety the census identified): compile-success-only
   assertion for the ~30 accept-shape rows where running adds nothing.
   If the implementation turns out disproportionate, the fallback is a
   print line per accept row — decide in-unit, note the choice.
4. **Battery + policy wiring.** The suite runs as part of test_runner
   discovery automatically (recursive rglob — verified); `-f conformance/`
   is the subset switch. XFAIL policy applies unchanged: a regressing
   conformance row is a red FAIL until a DF is filed and cited. CLAUDE.md
   testing section gains two sentences (the directory, the subset
   switch); TESTING.md gains the INDEX convention.
5. **The standing obligation** (already stated in 190's process rules,
   restated here as the brief's contract): every future safety-surface
   brief adds/updates its conformance rows as its FIRST unit, and the
   fixing commit of any conformance regression updates the row, never
   deletes it.

## Gates

Full battery per unit; the new rows must be green (or DF-cited XFAIL)
before the unit commits; irdet --all unaffected in principle but run as
usual. The dedup decisions in unit 1 are the review surface — the report
lists every row judged "already covered" with the covering test named,
so over-optimistic dedup is auditable.

## Explicitly out

New probe content beyond the audit's rows (future briefs add their own
rows); porting drive.py (retired once the suite lands); a separate CI
lane (the battery IS the lane); sanitizer integration (brief 192's
gmgate lane).

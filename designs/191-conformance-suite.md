# Design 191 — the standing conformance suite

**Status: LANDED (Aug 10), all five units — see the landing report at the
bottom. The record below is the brief as ratified.**

**Status when written: AUTHORED from design 190's analysis (Aug 9), awaiting user
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

## The standing obligation (unit 5 — the brief's contract)

Design 190's third process rule lands in CLAUDE.md as one sentence. Here is
what it means in practice, now that there is a suite for it to mean anything
about. It binds every brief from here on:

1. **A brief touching a safety guarantee adds or updates its
   `examples/conformance/` rows as its FIRST unit** — before the
   implementation, not beside it and not after. The rows are how the brief
   states what it is about to guarantee; writing them first is what makes the
   flip from red to green the evidence that it did.
2. **A row is added to `INDEX.md` in the same commit that adds its file**, and
   a row that moves, dedups or is superseded updates the INDEX in the commit
   that moves it. The INDEX is the coverage view — the directory only shows
   what somebody happened to write — so a stale pointer reads as covered and
   is worse than a missing row.
3. **The fixing commit of a conformance regression UPDATES the row, never
   deletes it.** A row that goes red has found something; deleting it converts
   a caught bug into an uncaught one. If the row's expectation was wrong, it is
   re-authored to the ruling with the ruling named in its header — which is
   exactly what twenty-four of this brief's own rows needed, because designs
   186-189 and 193 had re-decided them between the audit and the port.
4. **A row may be XFAIL only as the pin of a filed DF, cited in its reason**,
   with its EXPECT directives stating the INTENDED behavior so the XPASS flip
   validates the fix. This is the standing policy, restated here because a
   conformance row is exactly the kind of test somebody would reach for `skip`
   on.
5. **Deduping to an existing test is legitimate and must be visible.** A row
   ports when no existing test asserts its rule AT ITS POSITION; sharing a
   diagnostic is not enough. Where an existing test does cover it, the row
   points at that test in the INDEX rather than growing a second copy — and
   the pointer is what makes the judgement reviewable later.

The suite's value is entirely in the second and third rules. A corpus of
safety tests is ordinary; a LEDGER that says which claimed guarantee each one
checks, and which claims are checked by something else, is what turns "we have
tests" into "every guarantee we make is checked, and here is where".

## Landing report (Aug 10)

Five units, five commits, the full suite green at each: 1667 passed, 6 xfailed
(one of them this brief's own, cited). The conformance subset costs ~9s and the
whole battery went ~160s to ~164s, inside the census's ~+10s estimate.

**54 rows ported, 193 deduped** — a much higher dedup rate than the census's
60-70% estimate, and the reason is the queue order: designs 188, 189 and 193
landed between the census and this port, and 188 alone added fifteen tests
straight out of this audit (its landing report counts six of them as
accept-side boundary tests). The census priced a corpus that no longer needed
porting.

**Twenty-four rows are authored to a RULING rather than to the audit's
expectation**, listed row by row in the INDEX's closing section. All twelve of
the audit's deviation rows and six of its seven note rows are closed by designs
186-189 and 193; the seventh is this brief's one finding.

Three things worth keeping with the brief:

- **The oracle rule earned itself immediately.** Re-compiling every row against
  the tree rather than trusting the audit caught two rows whose expectation the
  rulings INVERTED — U25 (an `unsafe`-declared impl of a safe requirement) is
  legal under rule 7 where the audit expected a refusal, and U26 (a safe
  conformer of an `unsafe` requirement) is refused where the audit expected
  acceptance. Both would have landed backwards from the audit's own table.
- **Two of the audit's rows were not testing what they claimed**, which
  re-running found and re-reading would not have. N05 could not enter the
  freestanding profile at all on this host — `--freestanding` alone rejects the
  Mach-O triple first, so the row was asserting a triple check and calling it a
  module gate. K01-K03 probed non-Send with `Vector<Int>`, which design 186's
  container ruling made `Send`. Both are fixed rather than copied.
- **`EXPECT: compiles` was implemented and earns almost nothing here** (two
  rows), because the census's ~30 accept-shape rows deduped to accept-side
  tests designs 188/189 had already landed. It pays forward instead: obligation
  1 puts accept rows in every future safety brief, and without the directive
  each one invents a `print("ok")` to satisfy the success-test shape check.
  Unit 3's message records the reasoning.

# Design 125 — Docs consistency sweep + README catch-up

Source: `designs/reviews/2026-08-04-docs-consistency.md` (20 findings, each
with file:line on both sides and probe-verified ground truth). User decisions
Aug 4: fix all; README JOINS the mandatory docs-update convention; soften the
"no hidden allocations" claim.

## Scope
1. **Fix all 20 findings** exactly as the report's "which side is right"
   column resolves them (the probes are the authority; re-run any you doubt).
   Includes at minimum: the spec's stale pre-110 "`a = b` through `&var` is
   rejected" text; the wrong `-o` default in the spec's CLI appendix AND in
   `sawc --help` (code string); the keyword-table / §6-preamble / example
   stale spots the report lists.
2. **README catch-up through design 121**: to_uint/append_scalar (119),
   expression-position suspension (120), doc comments + `--emit-docs` (121),
   and the design-111 optional-chaining wording the report flags as lagging.
3. **README joins the docs convention.** CLAUDE.md's workflow section now
   names README alongside spec + skill as feature-update surfaces; delete
   README's claim that CLAUDE.md is "the authoritative, always-current
   feature list" (CLAUDE.md digest is an orientation summary, spec is
   authoritative — say so); fix the digest header ("Landed through design
   109" → current).
4. **Soften "no hidden allocations"** (user decision): name the two real
   exceptions — closure environments and string interpolation buffers — and
   keep the claim precise for everything else. Do NOT touch the op-budget
   fairness claim (design 127 is making it true; leave as is).
5. Also from the claims report: the saw-lang skill still says a BURIED
   blocking-extern call is a compile error — stale since 120 (probe-verified
   that it offloads). Fix with the 120 wording.

## Constraints
Docs + the one --help string only — no behavior changes (the `-o` fix is to
the TEXT to match behavior, not the reverse). Every factual edit cites its
probe (reuse the report's). Where the report marks "cosmetic", batch them in
one commit; would-mislead items get their own commits with the probe named.

## Exit criteria
All 20 findings closed; README current through 121 and inside the
convention going forward; suite green (docs sweep must not break the
doc_emit golden or EXPECT tests); tracker P3 block closed.

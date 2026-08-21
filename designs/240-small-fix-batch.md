# Design 240 — The Small-Fix Batch (eight ruled/mechanism-read items)

**Status: AUTHORED Aug 21 2026** (lead; every item's ruling or mechanism was
settled Aug 17-21 — this brief only collects them into one branch). One
commit per item, full suite + sos_runner both arches each; terminal full
battery. Items ordered by priority; each cites its tracker entry, which
carries the evidence.

## 1. DF-235b + 2. DF-235a — constant expressions at adoption positions

The priority items: a constant EXPRESSION (`2 + 3`, shifts, arithmetic —
anything that is not a bare/suffixed literal) is never range-checked at most
fixed-width adoption positions (silent truncation or silent over-width
storage — against the "bounds/overflow checks always on" claim), is
spuriously refused at compound-assign's RHS, and ICEs at two positions
(mixed array literal element, Result payload slot). One funnel gap:
`_apply_literal_expected_type` has no arm for a const-foldable `BinaryOp`.
Fix: fold (const_eval exists), then run the SAME literal-adoption +
range-check path a bare literal takes — one arm, not per-position patches
(obligation 1: the existing funnel gains the case; its docstring already
names the positions). The design-235 coercion ledger's red cells are the
test plan: flip the five pins (`const_expression_range_unchecked_narrow/
wide`, `compound_assign_const_expression_refused`,
`array_literal_const_element_ice`, `result_slot_const_expression_ice`),
update `examples/coercion/INDEX.md` rows from RED to green.

## 3. Extension-head visibility ban (~107 sites)

RULED Aug 20: a visibility marker on an extension head is a
declaration-site error — "visibility belongs on members — mark each
member". Parser refusal with that fixit; the dead `Extension.visibility`
field and plumbing go; the docs emitter drops the prefix from extension
signatures (goldens regenerate — the doc_emit tests' expected JSON blocks);
corpus migration removes every head marker (compiler-driven, 236-style; the
grep count Aug 20 was ~105 corpus + diag.saw's `public(package)` head);
LANGUAGE_SPEC's 4 example sites + the saw-lang skill's 2 lose theirs, and
the member-visibility section states the rule; `visibility_package.saw`/
`_public.saw`/`_parent.saw` drop their extension lines; a new error pin
covers the refusal.

## 4. DF-225c compiler half — the `Float64` name dies

RULED Aug 20: Float only. The spec half landed same day; this removes the
`Float64` type-name registration so the spelling errors cleanly (an
unknown-type diagnostic, ideally hinting `Float`). Pin from real output.

## 5. DF-225e — `std/` off the bare-import search path

RULED Aug 20: only `std.`-prefixed imports reach std sources.
`module_resolver.py`'s search-path list drops `std/` for bare imports; a
user module named `data` resolves to the user module alone, and the spec's
documented duplicate-qualifier diagnostic becomes reachable. Pin: a user
module named after a std leaf compiles clean; `import std.data` still works.

## 6. DF-232d — writes through a module qualifier

Corrected scope (design 235): EVERY write/reference shape through
`mod.STATIC` fails (plain assign errors; compound-assign, `&var` arg, and
write-through ICE). Mechanism read: `_check_assign_statement` type-checks a
`MemberAccess` target's OBJECT as an expression — right for values, wrong
for a module qualifier. Fix: the assignment/reference target path asks the
DF-236a stamp's question (does this member access name a module-qualified
static?) and routes to the static path. Flip the four 235-ledger pins;
update the qualified-name grid's rows.

## 7. DF-232e — the import-cycle diagnostic

Mechanism read: `_topological_sort` detects the cycle, returns arbitrary
order, and the downstream failure blames an innocent module. Fix is the
DIAGNOSTIC: `import cycle: a -> b -> a`, naming the participating import
lines; whether cycles should ever be SUPPORTED stays an un-asked question
(the kernel is a DAG). Flip the two 235-ledger cycle pins (2-cycle,
3-cycle); the graph-shapes grid rows go green.

## 8. DF-232g — a local static derived from an imported const

Mechanism + matrix in the entry: the const-static collector
(`_collect_const_statics`) resolves local names only, so `static N = A + B`
with imported `A`/`B` is "not a compile-time constant" while the same
expression folds inline. Fix: the collector resolves imported consts
through the same lookup the inline path uses. The entry's fold/refuse
matrix is the test plan.

## Gates and conduct

Compiler branch: per-commit full suite + sos_runner both arches; terminal
full battery. Design 236/239 grammar is law in every new test. The
design-235 ledgers' INDEX rows are part of each item's flip. Tracker
entries close in place per item; queue lists stay unnumbered; done files
untouched. Any item whose fix turns out to need a ruling STOPS and reports
rather than inventing policy.

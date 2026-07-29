# Design Brief 39 — Array element mutation: field assignment + overwrite deinit

**Source:** the two remaining ledger xfails (brief-33 observations,
tracker L5). Both are element-mutation gaps in fixed arrays.
**Exit criteria:** BOTH xfails flip (markers removed) —
`array_elem_field_assign.saw` and `array_elem_overwrite_deinit.saw` —
leaving the suite at ZERO xfails; full suite green; no regressions in
the array/deinit families.

## Items

### 1. `a[0].v = 99` silently no-ops (wrong-answer bug)
Root-cause in the assignment-target lowering (codegen/statements.py /
calls.py `_get_member_pointer` path): an ArrayIndex base under a
MemberAccess target apparently produces a pointer into a temporary
copy (or is dropped entirely) instead of a GEP into the array storage.
Fix so the target path composes: array storage → element GEP → field
GEP → store. Verify nested forms too: `a[i].inner.v = x` (add a test)
and through a `&var` array... if arrays can be reference params today
(probe; test if so, note if not). Mutability enforcement: assigning
through a `let` array must error (probe current behavior; align with
struct-field assignment rules; test).

### 2. `a[0] = elem` never deinits the overwritten element (leak)
Whole-element assignment must release the old element before the store
when the element type needs cleanup — same rule ordinary variable
assignment already follows (the Identifier-target path releases; the
pointer-store placement path deliberately does not — array element
slots are LIVE, so they take the releasing path). Compose with the
value-transfer checkpoint: the incoming element is a transfer site
(move for NoCopy/ExplicitCopy, retain for ImplicitCopy — probe that
the checkpoint already fires for index-target assignment; if not, wire
it and test the missing-move error). Ordering per the xfail test:
"deinit 1" (overwrite) then reverse-index scope exit "deinit 2",
"deinit 3".

### 3. The tuple sibling (probe)
Tuples are the adjacent aggregate: does `t.0 = x` / field-through-tuple
mutation exist, and does it deinit overwritten elements? Probe; if the
same gaps exist and the fix generalizes mechanically, cover them with
tests; if tuple mutation is simply unsupported (parse error), note it
and stop — do not build new tuple features.

## Hazards
Double-free family (the usual): deinit_*/implicit_copy_*/string_*/
array_* ordering suites at every checkpoint; -O0 spot checks on the
flipped tests. The placement-write contract (brief 28 docs) draws the
live-slot vs uninitialized-slot line — item 2 is the LIVE side; do not
touch Vector's internal placement stores.

## Report back
Root cause per item; the checkpoint verdict for index-target transfers
(item 2); the tuple probe verdict (item 3); confirmation the ledger is
at zero xfails; suite tally; deviations; non-allowlisted commands.

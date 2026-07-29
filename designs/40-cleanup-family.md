# Design Brief 40 — Cleanup family: lookups, diagnostics, small gaps

**Source:** tracker items L3, L4(verify), L6, L9, L10, L11(new), M1, M3,
C6 — the accumulated small-to-medium follow-ups from briefs 26–39.
Items are independent; land each with its own commit; if one proves
deeper than expected, note-and-skip rather than stall the family.
**Exit criteria:** each item fixed-with-tests or explicitly reported as
verified-fine/skipped-with-reason; full suite green; ZERO xfails
maintained (or new deliberate ledger xfails only for anything found but
out of scope).

## Items

### 1. (L3) Cross-module fallback lookup: visibility + ambiguity
`typechecker/types.py` `get_struct_info`/`get_enum_info` fall back to
scanning ALL module namespaces, ignoring visibility, resolving by dict
order. Fix: honor visibility (private symbols of other modules are not
candidates) and, when two modules both export the matching name, emit
an ambiguity error naming both (mirror brief 26's collision
diagnostic). Tests: private-symbol non-resolution; two-module
ambiguity error; qualified access still works.

### 2. (L4, verify-first) `Vector<File>.copy()` diagnostic
Brief-09 reported a Python traceback; briefs 14/26 may have already
fixed the path (bound-gated extensions; ICE wrapper). Probe
`Vector<File>` copy today: if a clean "bound not satisfied" diagnostic
fires, add the locking test and close the item; if any ICE/traceback
remains, fix to a proper diagnostic + test.

### 3. (L6) `resolved_type` on module-qualified MemberAccess
`mod.value.field` reaches codegen without `resolved_type` (brief-31
workaround defaults signedness). Annotate in the module member-access
checker; remove the "defaults to signed" fallback ONLY if every path
then annotates (otherwise keep it and say so). Test: UInt arithmetic
through a module-qualified struct field (the case the fallback would
get wrong).

### 4. (L9) Equality over Optional and array members
Extend the Equatable derivation (brief 32) to member kinds it excludes:
Optional fields (None==None true, None vs Some false, payload-deep
otherwise) and fixed-array fields (element loop). Lift the
auto-conform restriction correspondingly (trivial struct with `Int?`
field auto-conforms again). Tests per kind + the previously-erroring
cases now working.

### 5. (L10) Auto-wrap premature free on implicit ImplicitCopy returns
Red test first: minimal repro of brief-38's finding — a function whose
implicit tail expression is an owned ImplicitCopy value auto-wrapped
into `Ok(...)`; scope exit releases the owned buffer while the payload
still references it (use a deinit-observing wrapper or String contents
check to prove the premature free). Fix: the auto-wrap consumes the
value — treat it as transferred at the wrap site so scope cleanup
skips it. Check the Err auto-wrap path and Optional auto-wrap for the
same hole. The explicit `return move x` form keeps working.

### 6. (L11) `let`-struct field mutation unenforced
`let p = Point(...); p.x = 5` compiles today (brief-39 finding).
Enforce: field assignment through a `let` binding errors like element
assignment does ("cannot assign to field of immutable ..."). Probe how
deep (nested fields, through methods taking &var self on a let — that
one should already error at the call). Migration: fix any existing
tests relying on the hole honestly (report each).

### 7. (M1) `swapAt` — the dynamic-index exclusivity escape hatch
Design 08 promised a stdlib method for the `swap(&a[i], &a[j])` shape
the static exclusivity check must reject for same-container dynamic
indices. Ship `Vector.swap(&var self, i: Int, j: Int)` (bounds-checked,
no-op when i==j, raw-pointer internals — placement-safe: pure bitwise
exchange, no deinit/copy) and the fixed-array equivalent if it fits
the extension model (probe; skip with note if fixed arrays can't take
methods yet). Tests incl. owning element types (String) — refcount
neutral.

### 8. (M3) Parser top-level dispatch dedup — only if natural
The ~40-line dispatch duplicated between parse() and inline-module
parsing (brief 26 skipped as invasive). Attempt a shared helper; if it
threatens error-recovery behavior (the sync points), skip with a note.
Existing parse/recovery tests are the oracle.

### 9. (C6) Generic methods on non-generic-type extensions
`extension String { func f<R>(...) }` fails ("Undefined struct: R") —
brief-36's machinery only monomorphizes method type params on
generic-typed extensions. Extend to plain extensions (mangling:
`String_f$1$Int` — the existing scheme with an empty struct-arg part).
Forcing consumer: make `withCString<R>` value-returning in
std/string.saw (brief 38's deferral) with a test returning Int through
it. If this proves deep, note-and-skip with the blocker described.

## Hazards
Items 4/5/6 touch equality/cleanup/transfer machinery — the
equatable_*/deinit_*/string_*/implicit_copy_* families are the oracle.
Item 1 touches symbol resolution — module family is the oracle. Full
suite per commit; -O0 spot checks on items 5/7.

## Report back
Per item: fixed/verified/skipped verdict + mechanism + tests. Item 2's
probe verdict. Item 5's red-proof. Item 6's migration list. Suite
tally; deviations; non-allowlisted commands.

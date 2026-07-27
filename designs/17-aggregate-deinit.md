# Design Brief 17 — Aggregate deinit (drop glue)

**Source:** three tech-debt ledger entries (briefs 04/11/12 reports) that
share one root theme: cleanup only fires for *named, top-level, concrete*
bindings. This brief makes destruction compositional.
**Exit criteria — these XFAIL tests flip (markers removed):**
- `generic_struct_deinit.saw` — generic-struct deinit never fires
- `vector_elem_deinit.saw` — Vector elements not deinit'd
- `deinit_temp_receiver.saw` — method-result temporary receivers never cleaned
Plus new tests below; full suite green (baseline 254 / 9); no unexplained
xfail movement.

## Work items (commit order; each is a green checkpoint)

### 1. Fix the conformance-name mismatch (unblocks generic structs)
Brief 04's report documented it: `_get_type_name_for_conformance`
(`codegen/resources.py`) builds its own name form, used both for namespace
conformance lookups and to build the deinit/copy method symbol for scope
cleanup — and the method-symbol half doesn't match the canonical
monomorphized names (`mangle_method`-produced, e.g. `Box$1$Int_deinit`).
Result: monomorphized `Box<Int>: Deinit` cleanup silently misses. Unify on
the canonical mangler (`codegen/mangle.py`) for the method symbol, keeping
the conformance-registry key self-consistent (the registry side may
legitimately use the generic name — `Box` conforms for all instantiations;
understand it before touching it). This alone should flip
`generic_struct_deinit`.

### 2. Recursive field cleanup (struct drop glue)
When a struct value is destroyed, run: its own `deinit` body (if declared),
THEN release each field that needs cleanup (Deinit-conforming fields
recursively, `String`/`ImplicitCopy` fields via release/deinit), in reverse
field order. Fields moved out beforehand must not be double-released —
probe whether moving out of struct fields is even expressible (brief 15
found `move p.x` doesn't parse; if fields can't be moved out, this hazard
is moot — say so). The existing `deinit_*` tests assert exact print
ordering: they are the regression oracle for "own body first, fields
after, LIFO overall". Note: containment rules force a Deinit declaration
when a struct holds Deinit fields, EXCEPT `String` fields (exempted in
brief 11) — after this item, a struct holding only String fields needs
cleanup without any declared deinit; make the cleanup-behavior logic
treat "has fields needing cleanup" as sufficient, not just declared
conformance.

### 3. Container element cleanup
`Vector<T>`'s hand-written deinit frees the buffer; elements needing
cleanup must be released first. Manual `deinit()` calls are banned in the
language, so stdlib code cannot express this today. Preferred design: a
compiler-known intrinsic for stdlib use — e.g. `__deinit_in_place(ptr)` /
`__deinit_value(move v)` — restricted so it never becomes a user-facing
manual-deinit unlock (restrict to `deinit` method bodies, or to `sawc/std`
modules; pick the cheapest sound gate and document it). Vector's deinit
then loops elements before freeing; `Map` (delegating storage to Vectors)
should come along for free — verify. If the intrinsic route turns out
disproportionate, a codegen-special-cased Vector element loop (String-style
compiler knowledge) is acceptable — document the choice and its debt.
Elements popped/moved out must not double-free: probe `pop()` semantics
before and after.

### 4. Statement-scoped temporaries
`makeResource().use()` — the receiver temporary is never registered for
cleanup. Register Deinit-needing intermediate results that are NOT bound,
returned, or transferred onward as statement-scoped temporaries, released
LIFO at the end of the enclosing full statement. Known-correct cases to
preserve: `consume(makeResource())` (callee already cleans the argument —
brief 12 verified; do not double-free), `let x = makeResource()` (binding
owns it), `return makeResource()` (caller owns it). Chained calls
(`a().b().c()`) produce multiple temporaries — all die at statement end,
LIFO.

### 5. Probe (don't fix): enum payloads
Check whether a Deinit-conforming enum payload value is released when the
enum value dies. If broken: add a verify-twice XFAIL test extending the
ledger and report; fix only if it falls out of item 2's machinery for free.

## Hazard notes
- Double-free is the failure mode of this whole brief. Every existing
  `deinit_*`, `implicit_copy_*`, `nocopy_*_with_move`, and `string_*` test
  asserts exact output — run the full suite at every checkpoint.
- The escape-retain logic from brief 11 (`_gen_transfer_value` retaining
  aliasing ImplicitCopy values that escape blocks) interacts with item 4:
  a String returned out of a block must not be released as a "temporary".
- The O1 pipeline reorders nothing observable, but run a spot check with
  `-O0` on the new tests to make sure cleanup isn't relying on optimizer
  behavior.

## Tests (beyond the three flips)
- `struct_field_deinit.saw` — struct with own deinit + Deinit-printing
  field: both print, own-body-then-field order.
- `struct_field_deinit_nested.saw` — two levels of nesting, full LIFO chain.
- `struct_string_field_release.saw` — struct holding a String, no declared
  deinit; if no printable observable exists, an interp-heavy loop test in
  the spirit of `string_lifetime.saw` (stable completion) is acceptable —
  or document why no test is expressible.
- `vector_elem_deinit_pop.saw` — popped element deinits exactly once (at
  its own scope end, not again at vector death).
- `deinit_temp_chain.saw` — chained temporaries, LIFO at statement end.
- Enum-payload xfail from item 5 if applicable.

## Report back
Per item: the mechanism, where it lives, how double-free was ruled out.
The intrinsic-vs-special-case choice (3) and its gate. What `pop`/moved
elements do. Enum-payload verdict. Suite tally movement. Deviations;
non-allowlisted commands (ideally none).

# Design Brief 03 — Value-transfer checkpoint (copy/move enforcement)

**Source:** `todo_jul26.md` must-fix #1 (the language's core promise), plus the
array-bounds item from must-fix #7.
**Prerequisite (already landed):** brief 02 — every checked expression carries
`resolved_type`; codegen consumes annotations via `_expr_type`.
**Exit criteria — these XFAIL tests flip to passing (remove their markers):**
- `nocopy_call_arg_requires_move.saw`
- `nocopy_explicit_return_requires_move.saw`
- `nocopy_struct_field_init.saw`
- `custom_copy_call_arg.saw`
- `array_const_index_out_of_bounds.saw`
Plus: full suite green, and new positive tests proving the `move` forms compile
and run with exactly one `deinit`.

## Problem

`NoCopy` is checked only for identifiers in `let`/`var` and implicit tail
returns (`sawc/typechecker/statements.py`, around the existing
`_check_no_copy_*` helpers). Function-call arguments, explicit `return x`, and
struct-field init are never checked — the double-free repros in the XFAIL tests
compile today. `CustomCopy` has the mirror gap: `copy()` fires at only 3 sites
(let, assignment, struct-field init), never for call args, returns,
array/tuple elements, or enum payloads.

## Design

### 1. One checkpoint function in the typechecker

Add a single function, e.g.:

```python
def _check_value_transfer(self, expr, target_type, context: str, line, column):
    """Every site where a value is copied or moved into a new home funnels
    through here. Enforces NoCopy move-discipline and marks CustomCopy sites
    for codegen."""
```

Behavior by the source expression and its `resolved_type`:
- **NoCopy type** (per the existing conformance lookup): the expression must be
  a `move x` (`MoveExpr`), a freshly constructed value (struct/enum init,
  function/method call result — a temporary has no second owner), or otherwise
  non-aliasing. A plain identifier (or field access) of a NoCopy type is an
  error: reuse/extend the existing diagnostic phrasing (the tests expect
  substrings `NoCopy` / `cannot return NoCopy type` — check the existing
  messages first and stay consistent).
- **CustomCopy type**: if the source is an existing binding (identifier, field
  access, index — not a fresh temporary), mark the site so codegen invokes
  `copy()`. Annotate the AST node (e.g. `expr.needs_copy = True`) — codegen
  already has copy-insertion logic for let/assign/field-init; extend it to
  consume this annotation uniformly instead of re-deciding per site.
- **Everything else**: no-op.

Also handle `move x` bookkeeping consistently: after a `move`, the source
binding is dead. If the typechecker already tracks moved-from state for the
sites it covers, extend that tracking to the new sites; if it doesn't track
use-after-move at all, do NOT build full dataflow analysis in this package —
enforcing move-required at transfer sites is the scope; note the gap in your
report.

### 2. Funnel every transfer site through it

Sites to route (find each in `typechecker/expressions.py` / `statements.py`):
1. `let` / `var` binding initializers (replace the existing inline NoCopy check
   with a checkpoint call — no behavior change expected).
2. Assignment RHS.
3. **Function/method call arguments** (including init-call arguments and the
   variadic tail — see the variadic loop added by brief 02).
4. **Explicit `return expr`** and implicit tail returns (unify both paths).
5. **Struct-field initializers** in struct init expressions.
6. Array and tuple literal elements.
7. Enum payload values (`EnumInit`).

`var` (by-reference) parameters are NOT transfers — the callee mutates the
caller's value in place. Make sure the checkpoint skips arguments bound to
`var` parameters (`foo(&x)` call sites).

### 3. Codegen: copy() at the new sites

Codegen consumes `needs_copy` where it materializes the value (call-arg
lowering in `codegen/calls.py`, return lowering, aggregate construction).
Model on the existing let-binding copy insertion. The `custom_copy_call_arg`
test's expected output tells you exactly when `copy()` must fire.

### 4. Array constant-index bounds check (small, adjacent)

`typechecker/expressions.py` — the tuple-index path already rejects constant
out-of-range indices (~line 852-865); mirror that for fixed-size-array
indexing with a constant index. Use error phrasing containing `out of range`
(what the XFAIL test expects). Dynamic indices stay unchecked in this package.

## Tests

- Flip the five XFAIL tests (remove markers — the runner fails on stale ones).
- Add positive companions, e.g. `nocopy_call_arg_with_move.saw` (passing with
  `move` compiles; output shows exactly one `deinit`), same for return and
  struct-field init; `custom_copy_array_elem.saw` if you implement aggregate
  copy sites — every new enforcement site needs one error test and one positive
  test. Follow TESTING.md directive conventions.
- Watch the existing `deinit_*`, `custom_copy_*`, `nocopy_*` tests: their exact
  outputs are the regression oracle for double-copy/double-free.

## Report back

Sites routed through the checkpoint (with any you found beyond the list),
diagnostics added/changed, the use-after-move tracking status (existing?
extended? absent — noted as gap), copy-insertion sites added in codegen, and
any test whose expected output you had to change (with justification).

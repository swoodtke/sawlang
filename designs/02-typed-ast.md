# Design Brief 02 — Typed AST: single source of type truth

**Source:** `todo_jul26.md` must-fix #2 (highest-leverage item), subsumes part
of must-fix #3.
**Scope:** typechecker + codegen. No language-visible behavior changes except
bugs fixed (leaks gone, errors surfacing earlier).
**Exit criteria:**
- `sawc/codegen/statements.py::_infer_saw_type` is **deleted**.
- Typechecker stamps `resolved_type` on every successfully-checked expression.
- Codegen never infers types; it reads annotations (plus generic-param
  substitution).
- Full `make test` green (existing xfails stay xfail unless your change
  legitimately fixes one — then remove that XFAIL marker and say so).

## Problem (from the critique)

The typechecker computes a type for every expression but writes
`Expression.resolved_type` (`sawc/ast_nodes.py:520`) in only ~5 places. Codegen
therefore carries its own ~80-line weaker inference,
`_infer_saw_type` (`sawc/codegen/statements.py:139-221`), which returns `None`
for match/if/index/closure/try expressions. That `None` silently disables
cleanup registration and copy insertion — `let x = someMatchExpr()` binding a
`Deinit` type just leaks. Two inference engines will keep diverging; the fix is
to make the typechecker the single source of type truth.

## Design

### 1. One chokepoint stamps annotations

`ExpressionsMixin._check_expression` (`sawc/typechecker/expressions.py:32`) is
the single dispatch point for all expression checking. Stamp there:

```python
def _check_expression(self, expr):
    method_name = f'visit_{expr.__class__.__name__}'
    visitor = getattr(self, method_name, None)
    if visitor is None:
        return None
    result = visitor(expr)
    if result is not None:
        expr.resolved_type = result
    return result
```

Do **not** hand-edit the ~35 `visit_*` methods.

Interaction to preserve: a few sites annotate *contextually* after checking —
e.g. `_annotate_none_in_expr` / `_propagate_optional_type`
(`typechecker/expressions.py:1123-1182`) push an expected optional type down
into `None` literals, and `codegen/optionals.py:67-92` consumes that. Those
run *after* the child's `_check_expression` returns, so their (more specific)
annotation must win. With the chokepoint stamping at return time this ordering
already holds — but verify the `optional_*` / `none`-related tests explicitly,
and add a comment at the chokepoint stating the "later contextual annotation
wins" rule.

Statements are checked via their own paths (`typechecker/statements.py`); the
chokepoint covers expressions, which is what codegen's inference is used for.
Check whether any statement path computes an expression type *without* going
through `_check_expression` (e.g. hand-rolled handling in `visit_LetStatement`)
and route those through the chokepoint.

### 2. Generic function bodies get abstractly checked (subset of must-fix #3)

Today `typechecker/statements.py:196` skips generic function bodies entirely,
so their expressions would carry no annotations, and codegen monomorphizes the
*shared* AST per instantiation. Two consequences shape the design:

- **The shared-AST problem:** annotations on a generic body must be stable
  across instantiations. Therefore they are stamped in terms of the function's
  **type parameters** (abstract: `T`, `Box<T>`, …), never in terms of any one
  instantiation's bindings.
- **The abstract check:** add a pass that type-checks each generic
  function/extension body once, with its type parameters bound to opaque
  type-param types (respecting trait bounds for method/trait lookups). This
  both produces the annotations and fixes "an unused generic with a type error
  compiles clean." Keep it conservative: where a check genuinely can't be
  decided abstractly (e.g. an operation whose validity depends on the concrete
  type and today's tests rely on it), don't error — leave looseness for a
  follow-up rather than breaking existing tests.

### 3. Codegen consumes annotations through one accessor

Replace every `_infer_saw_type(expr)` call with a single accessor, e.g.
`self._expr_type(expr)`:

- Reads `expr.resolved_type`.
- If the type mentions generic type parameters, substitutes them via the
  current monomorphization binding map (codegen already has one for
  specialization — reuse it; a small recursive `substitute(type, bindings)`
  helper likely already half-exists in `codegen/generics.py`).
- **Fails loud, not silent**: if `resolved_type` is `None`, raise an internal
  compiler error naming the node type and line — do *not* return `None`.
  Silent `None` is exactly what caused the leak bug. Exception: if there are
  AST nodes that legitimately reach codegen unchecked (find out — e.g.
  synthesized nodes created *by* codegen), synthesize them with
  `resolved_type` set at creation instead of weakening the accessor.

Then delete `_infer_saw_type` entirely. Also grep codegen for other ad-hoc
inference (`namespace.get_return_type`-style lookups used to guess an
expression's type) and route through the accessor where appropriate —
`codegen/optionals.py:71-92`'s priority chain is a known consumer to simplify.

## Suggested order of work (commit at each green checkpoint)

1. Chokepoint stamping + verify no regressions (`make test`). Small commit.
2. Abstract checking of generic bodies (annotations only at first; report
   errors it finds — if any existing example fails the new check, fix the
   example if it's a real latent bug, or loosen the check if it's a
   false positive). Commit.
3. The `_expr_type` accessor + substitution; migrate codegen call sites one
   cluster at a time (statements → resources/cleanup → optionals → the rest),
   running the suite at each step. Delete `_infer_saw_type`. Commit.

## Consequences to expect (and check for)

- Cleanup registration (`codegen/statements.py:133-137`,
  `codegen/resources.py`) will start seeing types for match/if/try/index
  expressions it previously missed. That means `Deinit` types bound from those
  expressions start getting destroyed — watch the `deinit_*` tests; if any
  xfail-style leak test exists, it may start passing (good — update markers).
  Conversely watch for **double-free regressions**: an expression result that
  codegen now tracks for cleanup but that is *also* cleaned elsewhere.
- Some `custom_copy_*` behavior may change for the same reason. Existing tests
  are the oracle; do not change expected outputs without being able to argue
  the old output was a manifestation of the leak/skip bug.
- Do **not** attempt must-fix #1 (move/copy enforcement at all transfer sites)
  in this change — that lands next, on top of these annotations. Avoid
  design choices that would block a later single "value transfer" checkpoint
  in the typechecker.

## Report back

- The invariant achieved ("every expression reaching codegen has
  resolved_type" — true/false, with exceptions listed).
- What the abstract generic check found in existing code (errors, loosenings).
- Codegen sites whose behavior changed (cleanup/copy now firing) and how you
  verified each is a fix, not a regression.
- Any `_infer_saw_type` behaviors that were load-bearing and how you preserved
  them.

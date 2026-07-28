# Design Brief 27 — Follow-ups family: symbol-object split, closure field inference, dead init branch

**Source:** the three remaining follow-ups recorded in `todo_jul26.md` after
the brief 23–26 sweep (brief-24 report findings + the brief-26 explicitly
out-of-scope refactor). The suite-timing item is RESOLVED (measured 24s
wall-clock uncontended; earlier >10min observations were contention between
concurrent suite runs) — no work needed there.
**Exit criteria:** each item lands with tests proving the new behavior;
full suite green (currently 311 passed, 0 xfailed — keep it at zero);
no unexplained xfail movement.

## Items

### 1. Split codegen-mutable state off shared symbol objects
`namespace.py` symbols carry declaration data AND codegen-populated
mutable fields (`FunctionSymbol.llvm_func` line ~49,
`StructSymbol.specialized_methods` ~68, `llvm_type` ~70/83). Builtin
symbols are shared BY REFERENCE into every module namespace via
`merge_into`, so codegen writes onto one module's view leak into all
views. Masked today because codegen runs once on one merged namespace;
it blocks per-module/incremental codegen and is a latent aliasing trap.

Fix direction (architect-reviewed): separate immutable declaration data
from per-compilation codegen artifacts. Prefer moving the mutable fields
into codegen-owned side tables keyed by symbol identity or canonical
mangled name (the codegen already has dict machinery — probe
`enum_types`/`struct_types` style tables in codegen/core.py) over
deep-copying symbols per module. Keep `merge_into`'s identity-based
collision detection (brief 26) intact. The full suite (especially the
module/reexport/visibility family and generic monomorphization tests) is
the regression oracle. Do NOT change diagnostic text.

### 2. Closure literal as struct-init field argument: infer param types
`Point(handler: { $0 * 2 })` fails to infer the closure's param types
from the field's function type; today it demands explicit annotations.
Call arguments already do this: `_check_method_call` routes ClosureExpr
args through `_check_closure(arg.value, expected_type,
as_call_argument=True)` (typechecker/expressions.py:1823). Mirror that
in `_check_struct_init` (:1288) and `_check_module_struct_init` (:2145)
arg loops — when the field type is a function type and the arg is a
ClosureExpr, pass the expected type through. Verify-twice: test first
(shorthand closure in struct init, currently errors), prove red, fix,
prove green. Also cover the trailing-closure-into-init form if the
grammar allows it; skip with a note if it doesn't.

### 3. `_check_init_method_call` is referenced but undefined
`typechecker/expressions.py:1852` calls `self._check_init_method_call`
on the module-qualified-struct MethodCall branch when the resolved
method `is_init`. Reachable from parseable source (e.g.
`module.Struct.init(...)`-shaped calls) → AttributeError crash. Decide:
if module-qualified custom inits already flow through
`_check_module_struct_init` (probe how `mymodule.Point(magnitude: 5)`
parses and checks), then this branch should emit a clean diagnostic
telling the user to call the initializer as `module.Struct(...)` — not
implement a redundant path. If they do NOT flow anywhere (custom init
through a module is simply unsupported), implement the branch by
delegating to the existing init-resolution logic instead. Either way:
error test or acceptance test proving the chosen behavior, and no bare
Python traceback.

## Hazards
Item 1 touches the load-bearing symbol plumbing shared by typechecker
and codegen — small steps, run the module + generic families after each
step, full suite at the end. Items 2/3 are localized; the usual
false-positive rule applies (breaking a passing test means the change is
wrong, not the test).

## Report back
Per item: mechanism, where (file:line), verification. Item 1: where the
mutable state now lives and why per-module codegen is no longer blocked
by aliasing. Item 3: the probe verdict on how module-qualified custom
inits actually flow. Deviations; non-allowlisted commands.

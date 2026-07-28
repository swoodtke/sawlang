# Design Brief 26 — Structural family: module collisions, one pipeline, parser recovery, diagnostics

**Source:** the critique's remaining structural issues (`todo_jul26.md`)
+ the module-collision ledger xfail.
**Exit criteria:** `module_import_collision` XFAIL flips (marker removed);
`--emit-ir` works on builtin-using programs (verify-twice test not
possible in-harness — scratch-verify and report); multi-error syntax
reporting demonstrated; codegen internal errors surface as diagnostics;
full suite green.

## Items

### 1. Module symbol collision → real diagnostic
Two modules exporting the same name, importer uses it: today
`merge_into` (namespace.py) resolves silently and codegen dies with
`DuplicatedNameError`. Emit a typechecker-time ambiguity error naming the
symbol and both source modules. While in `merge_into`: address the
first-wins silent resolution generally (collision on ANY symbol category
→ error or explicit shadowing rule — pick ERROR for now, simplest honest
rule; document). Do NOT attempt the deeper shared-mutable-symbol-objects
refactor (`llvm_type` leakage) — out of scope, note it stays on the
ledger.

### 2. One compile pipeline
Collapse `compile_saw` vs `compile_with_modules` (sawc.py) into one path
(a single file = module graph of size 1), removing the hand-inlined
third registration copy that reaches into private methods. Consequence
to verify: `--emit-ir` loads builtins and works on programs using
String/Vector/Result (the long-standing breakage) — scratch-verify,
record in report. The full suite exercising both former paths is the
regression oracle.

### 3. Parser error recovery
First syntax error currently aborts (`parser/core.py`). Batch multiple
syntax errors per file: on error, synchronize to the next top-level
declaration boundary (`func`/`struct`/`enum`/`extension`/`trait`/
`import`/`module`/`type` at depth 0) and continue; cap at ~10 before
bailing. Existing single-error tests must keep passing (first error text
unchanged); add a test with two independent syntax errors asserting BOTH
messages (EXPECT-ERROR-CONTAINS twice). Also de-duplicate the ~40-line
top-level dispatch copied between `parse()` and inline-module parsing if
it falls out naturally; skip if invasive.

### 4. Codegen internal errors as diagnostics
Wrap the `codegen.generate()` call the way parser calls are wrapped: a
`ValueError`/internal failure surfaces as `internal compiler error:
<message>` through the ErrorReporter (with the standard exit code), not
a Python traceback. Do NOT rewrite the 76 raise sites — the single
wrapper is the fix; raise-site message quality stays as is.

## Report back
Per item: mechanism + verification. Item 2: confirm --emit-ir works on
a String/Vector program (paste the scratch command result summary).
Item 3: recovery-point choices and any cascade-error suppression needed.
Deviations; non-allowlisted commands.

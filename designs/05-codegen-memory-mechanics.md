# Design Brief 05 — Codegen memory mechanics: allocas, passes, interpolation, div-zero

**Source:** `todo_jul26.md` must-fix #5, #6, and the div-by-zero half of #7.
**Exit criteria — these XFAIL tests flip to passing (remove their markers):**
- `interp_large_string.saw` (>1KB interpolation SIGSEGVs today)
- `interp_escapes_scope.saw` (returned interpolated string dangles today)
- `interp_hot_loop.saw` (1M-iteration interp loop SIGSEGVs in ~0.3s today)
- `div_by_zero_panics.saw` (on arm64, div-by-zero silently returns garbage
  today — no SIGFPE — the test expects a panic containing `division by zero`)
Plus: full suite green.

Four contained fixes, one theme: stop lying to the stack. Do them as separate
commits in this order (each is a green checkpoint).

## A. Entry-block allocas

Loop lowering (`codegen/loops.py:99-285`) and other sites emit `alloca` at the
point of use — inside loop bodies, fresh slots every iteration, unbounded
stack growth.

Add one helper on the code generator, e.g.:

```python
def _entry_alloca(self, llvm_type, name=""):
    """Create an alloca in the current function's entry block (required for
    mem2reg and for loop-safety: allocas in loop bodies grow the stack every
    iteration)."""
```

It saves the builder position, positions at the entry block's first
instruction (or its terminator-free insert point), creates the alloca, and
restores. Migrate ALL `builder.alloca` call sites in `codegen/` to it —
grep for `.alloca(`; there should be zero direct calls left outside the
helper. This alone may fix `interp_hot_loop` (the interp buffer alloca stops
accumulating); the buffer overflow and dangling-pointer bugs still need
part C.

## B. Optimization pass pipeline

`codegen/core.py:814-828` emits object code from raw IR — no passes at all.
llvmlite 0.48 (the pinned version — check its docs/API, the legacy pass
manager may be gone) exposes the new pass manager. Run a default `O1`-level
module pipeline (must include mem2reg/SROA) on the module before
`emit_object`, and also before `--emit-ir` output so emitted IR reflects
reality. Add a `-O0` CLI flag to `sawc.py` to disable optimization for
debugging codegen. Verify: compile a small example with `--emit-ir` and
confirm allocas are promoted (no `alloca` for simple scalars).

## C. Memory-safe string interpolation

`codegen/core.py:613-650`: fixed 1024-byte stack buffer + unbounded
`strcpy`/`strcat`, and the buffer is an alloca whose address escapes (returns/
stores dangle). Replace with a correctly-sized HEAP allocation:

1. First pass over the segments to compute the total byte length:
   `strlen` for string parts; for numeric parts use
   `snprintf(NULL, 0, fmt, val)` (returns the would-be length).
2. `malloc(total + 1)`, then build the string (`snprintf`/`memcpy` into
   offsets, or `strcat` is acceptable now that the buffer is exact-size).
3. The result is a heap pointer: storing/returning it is safe.

**Interim leak is accepted and documented**: Saw's `String` is not yet an
owned type (that redesign is gated on the copy-semantics decision — see
todo_jul26.md priority #4), so these heap strings are not freed. Put a
comment at the allocation site saying exactly that, with a reference to the
todo item. Leak > memory corruption. Do NOT invent an ownership scheme here.

## D. Division-by-zero panic

Integer `/` and `%` lowering (`codegen/operators.py`): emit a zero-check on
the divisor first; on zero, branch to a panic block reusing the existing
`try!` panic machinery (`codegen/results.py:77-98`) with message
`panic: division by zero` (must contain `division by zero` — the XFAIL test's
directive). Non-zero path proceeds with the raw instruction. Also handle
INT_MIN / -1 overflow trapping? NO — out of scope; integer-overflow semantics
are an open spec question (todo #5's list). Divide-by-zero only.

Float division is untouched (IEEE inf/nan semantics stay).

## Tests

- Flip the four XFAIL tests (remove their markers; the runner fails on stale
  markers, so you can't forget).
- Add: `div_by_zero_modulo.saw` (`%` panics too); an interp test mixing many
  segment types at boundary sizes if the existing three leave a gap you
  notice. Correct-behavior EXPECT directives per TESTING.md.
- Perf sanity (not a test): `interp_hot_loop` should now run in reasonable
  time with stable memory; note its runtime in your report.

## Report back

Per fix: what changed, how verified. Plus: total `builder.alloca` sites
migrated (and confirmation none remain), which pass pipeline/API you used for
llvmlite 0.48, measured effect of O1 on the test suite's compile+run time if
noticeable, and any test whose behavior changed under optimization (that
would be a real codegen bug the passes exposed — report, don't paper over).

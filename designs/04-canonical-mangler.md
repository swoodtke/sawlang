# Design Brief 04 — One canonical name mangler

**Source:** `todo_jul26.md` must-fix #4.
**Exit criteria — these XFAIL tests flip to passing (remove their markers):**
- `generic_tuple_result_single.saw` (currently a compiler crash:
  `KeyError: 'Result_TUPLE_MyErr'` in `codegen/results.py` — even ONE
  tuple-payload Result breaks; producer and consumer mangle differently)
- `generic_nested_tuple_mangling.saw` (two tuple-payload Results must get
  distinct LLVM structs and correct outputs)
Plus: full suite green.

## Problem

Three divergent mangling implementations, all lossy in different ways:
- `codegen/generics.py:125` recurses into type args correctly (the best one).
- `codegen/types.py:256-263` ignores type args entirely —
  `identity<Box<Int>>` and `identity<Box<String>>` collide.
- `codegen/results.py:484-507` mangles every tuple to the literal `"TUPLE"` —
  `Result<(Int,Int),E>` and `Result<(String,Bool),E>` alias one LLVM struct.
- `_wrap_error_in_union` (`codegen/results.py:548`) *parses type info back out
  of a mangled name* via `mangled.split("_")[-1]` — breaks on any
  multi-segment name.
- Init overloads mangle by parameter NAMES, so same names + different types
  collide.

## Design

### 1. One module: `sawc/codegen/mangle.py`

A single canonical function, roughly:

```python
def mangle_type(t: SawType) -> str: ...      # recursive, collision-free
def mangle_function(name, type_args) -> str: ...
def mangle_init(struct, param_types) -> str: ...   # types, not names
```

Requirements for `mangle_type`:
- **Total**: handles every `TypeKind` — primitives, struct/enum with type
  args, tuple (element-wise recursion, arity included), array (elem + size),
  optional, Result, function/closure types, type aliases (decide: mangle the
  alias name or the underlying — pick one, document it, apply everywhere).
- **Injective**: two structurally different types never produce the same
  string. Length-prefix or otherwise delimit segments so concatenation is
  unambiguous (`3Int` style à la Itanium, or a separator that cannot appear in
  type names). `Box_Box_Int` vs `Box<Box<Int>>`-style ambiguities are exactly
  the bug class being killed.
- **Deterministic** and order-preserving for type args.
- Emits valid LLVM identifier characters only.

### 2. Replace all three implementations

Migrate every mangling call site in `codegen/` (grep for name-building string
concatenation around `generics.py`, `types.py`, `results.py`, and init/method
specialization in `methods.py`/`structs.py`) to the canonical module. Delete
the local implementations. The typechecker must not need mangled names; if you
find a site that does, flag it in your report.

### 3. Kill the parse-back hack

`_wrap_error_in_union` must receive the error type as a structured `SawType`
(it's available at the call site or via `resolved_type` annotations from
brief 02) instead of recovering it from a mangled string. No code anywhere
should ever *parse* a mangled name.

### 4. Registry symmetry

The `KeyError` crash shows producers and consumers computing names
independently. After unification, keys used to REGISTER a specialized
struct/function and keys used to LOOK IT UP must both come from the canonical
functions. Audit the dict accesses that raised (`results.py` specialized-
Result registry) and any similar registries in `generics.py`.

## Tests

- Flip the two XFAIL tests (remove markers).
- Add: `generic_nested_type_args.saw` — `identity<Box<Int>>` vs
  `identity<Box<String>>` (or equivalent with existing generic machinery)
  exercising the types.py collision; an init-overload test with same param
  names / different types if the language can express it today. Every new test
  needs correct-behavior EXPECT directives per TESTING.md.
- The whole existing suite is the regression oracle — mangled names appear in
  IR only, so no expected outputs should change.

## Notes

- Do this cleanly now: these names become a de-facto ABI the moment separate
  compilation lands.
- Don't rename beyond necessity — if the canonical scheme changes names for
  already-working monomorphizations, that's fine (they're internal), but keep
  `main` and non-generic functions' symbols unmangled so the linker/entry
  behavior is untouched.

## Report back

The canonical scheme (grammar sketch), call sites migrated per file, what
`_wrap_error_in_union` consumes now, any asymmetric register/lookup pairs
found beyond the known KeyError, and any latent collisions the unification
exposed in the existing suite.

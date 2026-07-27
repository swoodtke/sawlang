# Design Brief 09 — Implement the `Copy` trait family

**Source:** the DECISION section of `designs/06-copy-semantics.md` — read it
first; it is the specification. This brief adds sequencing and mechanics.
**Prerequisites (landed):** typed AST (02), value-transfer checkpoint (03).
**Do not start while brief 05's agent is running** (touches `collections.py`).

## Work items, in commit order

### 1. Rename `CustomCopy` → `ImplicitCopy`
Mechanical, everywhere: typechecker, namespace, codegen, stdlib (`sawc/std/`),
examples (`custom_copy_*.saw` → `implicit_copy_*.saw`, update contents),
LANGUAGE_SPEC.md, CLAUDE.md, TESTING.md mentions. No compatibility alias —
pre-1.0, clean break. Suite green at this commit (pure rename).

### 2. `ExplicitCopy` trait, enforcement, and `.copy()`
- Register `ExplicitCopy` as a compiler-known trait alongside
  `Deinit`/`NoCopy`/`ImplicitCopy` (sibling implementation, hierarchy is
  conceptual — see 06).
- Value-transfer checkpoint: `ExplicitCopy` gets exactly the `NoCopy`
  move-required treatment, with its own diagnostic:
  `cannot copy value of type \`Vector<Int>\` which implements ExplicitCopy` +
  hint `use .copy() for an explicit deep copy, or \`move\` to transfer ownership`.
- `v1.copy()` — a user-declared `func copy(self) -> Self` in the type's
  extension satisfies the requirement; conformance checking enforces the
  signature. Declaring both `ImplicitCopy` and `ExplicitCopy` is an error.
- Containment: struct with an `ExplicitCopy` field must declare
  `ExplicitCopy` or `NoCopy` (mirror the existing NoCopy containment check;
  error + hint).

### 3. Memberwise `copy()` derivation
For a struct declaring `ExplicitCopy` (or `ImplicitCopy`) without a
hand-written `copy()`: synthesize memberwise — POD fields bitwise,
`ImplicitCopy`/`ExplicitCopy` fields call their `copy()`, `NoCopy` field ⇒
compile error naming the field. Synthesis happens where method bodies are
generated (typechecker registers the signature; codegen emits the body — model
on existing derived machinery like auto-deinit if present, else generate an
AST-level method before registration, whichever is less invasive — your call,
document it).

### 4. Auto-`Copy` for trivial types + the `T: Copy` bound
- A type is trivially copyable iff all fields are, and it has no `Deinit`
  and no declared `NoCopy`/`ImplicitCopy`/`ExplicitCopy`. Such types satisfy
  `Copy` implicitly; `x.copy()` on them is legal and compiles to a bitwise
  copy (support at least direct calls and through generics; a full method
  materialization isn't required if call sites lower it inline).
- `Copy` as a generic bound: satisfied by trivial | `ImplicitCopy` |
  `ExplicitCopy`. Inside a `T: Copy` body, `x.copy()` type-checks (abstract
  check: returns `T`) and monomorphization emits the right synthesis per
  instantiation. `T: ImplicitCopy` / `T: ExplicitCopy` work as ordinary
  narrower bounds.
- An unbounded `T` does NOT get `.copy()` (abstract check rejects it).

### 5. Stdlib: `Vector.copy()` and `Map.copy()`
Switch `Vector`/`Map` from `NoCopy` to `ExplicitCopy` with hand-written
element-wise `copy()`. The element-duplication inside needs `T`'s copy path —
if bounded extensions (`extension Vector<T: Copy>`) aren't expressible today,
implement `copy()` unbounded and let monomorphization error when `T` has no
copy path (e.g. `Vector<File>.copy()`), with a readable diagnostic naming `T`.
Document which route you took. `File`/`Mutex`-style types stay `NoCopy`.

## Tests (each item lands with its tests)
- Rename: existing suite is the oracle (green = done).
- `explicit_copy_requires_move.saw` (transfer without move/copy → error with
  the new message), `explicit_copy_basic.saw` (`.copy()` yields an independent
  deep value — mutate one, print both), `explicit_copy_derive.saw` (memberwise
  derivation), `explicit_copy_containment.saw` (undeclared containment →
  error), `explicit_copy_both_traits_error.saw`.
- `copy_bound_generic.saw` (`func dup<T: Copy>(x: T) -> T { x.copy() }` works
  for Int + an ExplicitCopy struct), `copy_bound_missing.saw` (unbounded `T`
  calling `.copy()` → error), `vector_copy.saw` (independence after copy),
  `vector_copy_nocopy_elem.saw` (`Vector<File>.copy()` → readable error).

## Report back
Standard: per-item status, the synthesis route chosen (3), the
bounded-extension situation (5), diagnostics added, any existing tests whose
meaning changed under the rename, deviations.

# Design Brief 37 — Allocator stage 4: default type parameters + public A

**Source:** paper 19 §6 stage 4 under the ratified D4 decision; tracker
F2. Builds directly on brief 28 (trait + Global + internal threading)
and brief 36 (generics machinery, substitution walk, canonical
mangler).
**Scope guard:** default type parameters + exposing `A` publicly ONLY.
Slab allocators (F3) and module-level statics (F4) are a LATER brief —
do not start them. A probe allocator for tests must not need statics
(see item 4).
**Exit criteria:** `Vector<Int>` and `Vector<Int, Global>` are the SAME
type (one identity, one mangled name); a custom allocator type works
end to end through the type parameter; hosted code compiles unchanged;
full suite green; exactly the 2 sanctioned ledger xfails.

## Items

### 1. Default type parameters (the generics feature)
`struct Vector<T: Copy, A: Allocator = Global>`-style declarations:
parser (default expr after `=` in a type-param list — TYPES only, no
value defaults), typechecker (omitted trailing args filled from
defaults at every reference site — annotations, inits, bounds checks,
extension matching), mangling (CANONICAL IDENTITY: defaults are applied
BEFORE mangling, so `Vector<Int>` and `Vector<Int, Global>` produce the
same mangled name and the same monomorphized struct — no dual
identities; extend the shared substitution walk from brief 36).
Defaults may reference earlier params only if trivially needed; skip
that generality if unused (report the choice). Error cases: too few
args with no default; a default that fails the param's bound.

### 2. Thread `A` publicly through Vector
`Vector<T, A: Allocator = Global>`: the brief-28 internal `Global()`
calls become `A()` calls (zero-sized construction, monomorphized direct
dispatch — verify the IR stays a direct call to the right allocator's
function, per brief 28's evidence pattern). `deinit`, `grow`,
`try_with_capacity`, and the iteration extensions carry `A` through.
Extension matching: `extension Vector<T: Copy>` must keep applying to
`Vector<T, A>` for any A (probe how extension-to-struct matching
handles arity now that the struct has 2 params — this is the risky
mechanical bit; the bounded-extension machinery from brief 14 is the
place to look).

### 3. Map (and any other alloc-layer type with a clean seam)
Same treatment for `Map<K, V, A = Global>` IF it falls out mechanically
from item 2's machinery; if Map's structure (Vectors inside) makes A
threading nontrivial, keep Map internal-Global and report — do not
force it.

### 4. Proof allocator + tests (no statics needed)
`struct LoudAlloc {}` in the test's own file: forwards to
saw_alloc/saw_dealloc but prints "alloc <size>" / "dealloc" — dispatch
observable without mutable state. Tests: default omission ≡ explicit
Global (same behavior, and a type-identity check — a function taking
`Vector<Int>` accepts a `Vector<Int, Global>` argument); custom
`Vector<Int, LoudAlloc>` prints on grow/deinit; type distinctness —
passing `Vector<Int, LoudAlloc>` where `Vector<Int>` is expected is a
TYPE ERROR (the D4 cross-heap-unrepresentable property, now testable);
deinit routes to the element's allocator (LoudAlloc prints dealloc,
not Global's silence).

### 5. Docs
LANGUAGE_SPEC.md generics (default type params) + memory sections
(public allocator param); CLAUDE.md key-decisions bullet. Paper 19
stage-4 line annotated as landed-except-slabs/statics.

## Hazards
The type-identity rule (defaults applied before mangling) is the
miscompile-class risk — if `Vector<Int>` and `Vector<Int, Global>` ever
diverge into two struct identities, every existing Vector test is the
oracle. Extension/bounded-extension matching across the new arity is
the false-positive risk (brief-14 machinery). Run
vector,map,equatable,generic,array,alloc,deinit families at every
checkpoint; full suite per commit. Freestanding must not regress.

## Report back
Per item: mechanism, verification. The identity guarantee stated with
mangling evidence. Item 3's Map verdict. Whether extension matching
needed changes (item 2). Suite tally; deviations; non-allowlisted
commands.

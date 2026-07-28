# Design Brief 28 — Allocator stage 3: trait, Global, internal threading

**Source:** paper 19 §6 stage 3, under the ratified D4 decision (A + C:
global seam + allocator-as-type-parameter model). Stage 4 (default type
parameters, public `A`, slabs, `static` declarations) is a LATER brief —
do not start it here.
**Exit criteria:** `Allocator` trait + `Global` in the stdlib; alloc-layer
types (`Vector`, `Map`, `Box` if introduced, String internals where
applicable) route allocation through `Global` via the trait rather than
calling `saw_alloc` directly; `alignof<T>()` builtin lands; placement-write
contract documented; full suite green, zero xfails.

## Items

### 1. `alignof<T>()` builtin
Sibling of `sizeof<T>()` (same plumbing: typechecker special-case +
codegen via llvmlite target data ABI alignment). Vector currently
hardcodes alignment 16 (`std/vector.saw` grow/init); switch those sites
to `alignof<T>()`-derived values (preserving the >= max_align_t behavior
of the hosted seam where required). Tests: alignof on primitives, a
struct with mixed fields, a generic T at two instantiations.

### 2. `Allocator` trait + `Global`
Per paper 19 §4: trait with `alloc(&self, size: Int, align: Int) ->
UnsafePointer<Int8>?` and `dealloc(&self, ptr, size, align)`. `Global` is
a zero-field unit struct whose impl wraps the `saw_alloc`/`saw_dealloc`
seams. Lives in the stdlib (builtin.saw or a new std/alloc.saw — pick
what fits the layering; note the paper's core/alloc/std layer split is
future work, don't build layer enforcement here).

### 3. Thread `A` internally, hardcoded to `Global`
Alloc-layer stdlib types call `Global().alloc(...)`/`.dealloc(...)`
instead of the bare seam symbols. NO public type-parameter change yet
(that needs default type params, stage 4) — the goal is that stage 4
becomes a mechanical parameter exposure. Zero-sized-struct calls must
monomorphize to direct calls with no runtime cost — verify via
`--emit-ir` spot check (no allocator value materialized beyond a
zero-size placeholder).

### 4. Placement-write contract documentation
Document (in LANGUAGE_SPEC.md's unsafe/pointer section and a comment at
the pointer-store codegen site): a store through `UnsafePointer<T>`
(`ptr[i] = value`) is the placement-move primitive — bitwise move,
source consumed (value-transfer checkpoint applies), NO destination
release; using it on a slot holding a live value leaks that value; using
ordinary assignment semantics on uninitialized memory is the bug it
avoids. Cite Vector.push as the canonical user.

### 5. Fallible factory proof-of-mechanism (small)
One `Vector.try_with_capacity(n) -> Result<Vector<T>, AllocError>`-style
factory (or MakeBox if Box exists by then) exercising the decided
three-tier failure model end to end: allocator returns None → factory
returns Err carrying size context; success path unchanged. `AllocError`
struct introduced (allocator/size context fields per paper 19). Test:
force failure deterministically (e.g. absurd capacity under the hosted
allocator returning None — probe how saw_alloc behaves on huge sizes; if
not reliably None, test via a tiny custom probe allocator in the test's
own module instead).

## Hazards
Item 3 touches every stdlib allocation site — the deinit/copy/string
ordering families plus concurrency tests are the oracle; run at every
checkpoint. Do not regress freestanding: `--freestanding` programs using
only core features must still compile (brief 20's seam tests).

## Report back
Per item: mechanism, where, verification. Item 3: confirm zero-cost
dispatch (IR evidence). Item 5: how failure was forced deterministically.
Deviations; non-allowlisted commands.

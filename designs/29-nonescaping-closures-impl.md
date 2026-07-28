# Design Brief 29 — Non-escaping closures: implementation

**Source:** paper 16, now FULLY DECIDED (Jul 28): default-non-escaping
closure parameters; `escaping` marker in the function type's
post-parameter slot (`(Int) escaping -> Void`, composing `() sync
escaping -> Void`); fully explicit reference captures in a bracketed
capture list (`{ [&var sum] x in ... }`); captures follow call-argument
transfer-site rules exactly.
**Exit criteria:** the accumulation idiom works
(`var sum = 0; vec.each { [&var sum] in sum += $0 }` mutates the real
`sum`); escape violations are compile errors; capture exclusivity joins
the call-site check (`v.each { [&var v] in ... }` rejected); stdlib gains
`Vector.each`/`map`/`fold`; full suite green, zero xfails.

## Items

### 1. Type-level escaping bit + parser
Function types carry escaping/non-escaping. Parser: accept `escaping` in
the post-parameter slot of function TYPES (contextual keyword, exactly
like `sync` after commit 00918b3 — copy that mechanism; canonical order
`sync escaping` if both). Parameter position defaults non-escaping;
field/binding/return closure types are implicitly escaping (marker there
is an error: "redundant — closure types outside parameter position are
always escaping"). Type display, `_types_compatible`, and the effect
machinery updated (an escaping bit mismatch: passing an escaping-typed
value where a non-escaping param is expected is FINE — it's a subtype
direction; the reverse is the error direction. Think it through and
document the variance rule with tests both ways).

### 2. Bracketed capture list + explicit capture checking
Parser: optional `[cap, cap, ...]` immediately after `{` in closure
literals, before params/`in`. Capture forms: `&name` (immutable borrow),
`&var name` (mutable borrow), `move name`, `name.copy()` spelled as
`copy name` or plain `name` per transfer rules — IMPORTANT: plain `name`
capture keeps today's semantics (trivial bitwise / ImplicitCopy retain /
error for ExplicitCopy+NoCopy demanding move or copy) — route capture
initialization through the value-transfer checkpoint so the rules are
literally shared, not duplicated. Borrow captures (`&`/`&var`) are legal
ONLY in closure literals in non-escaping parameter position; anywhere
else: error naming the escape reason.

### 3. Dual capture lowering
Non-escaping closures with borrow captures lower to env-of-references
(pointers into the enclosing frame — safe because the closure cannot
outlive the call, same guarantee as & params). Value/move captures keep
the existing env-of-values path (including the brief-21b heap envs for
escaping closures — untouched). A closure may mix both.

### 4. Exclusivity join
The borrow captures of a non-escaping closure argument join that call's
access set in the brief-10 disjointness check: receiver, other args, and
other closure captures all pairwise-checked. `v.each { [&var v] in ... }`
(mutably capturing the iterated collection) must be a compile error with
the standard exclusivity diagnostic. Test the immutable-capture-allowed
case too (`[&total]` alongside a disjoint `&var` arg).

### 5. Callee-side forwarding rules
A callee holding a non-escaping closure param may call it or pass it as
another non-escaping argument; storing it (field, binding that outlives,
return) or capturing it in an escaping closure is an error, checked
locally (mirror the &-param no-escape checks). Tests per violation.

### 6. Stdlib iteration API (the forcing consumer)
`Vector.each(f: (T) -> Void)`, `Vector.map<U>(f: (T) -> U) -> Vector<U>`,
`Vector.fold<A>(init: A, f: (A, T) -> A) -> A` — non-escaping params,
implemented in std/vector.saw over the existing buffer. Element access
must respect the Copy family (each passes elements appropriately for
T's copy class — probe what get/iteration does today and match; do not
introduce silent copies of ExplicitCopy elements). Bounded to `T: Copy`
initially if element extraction demands it — note the bound and why in
the report if so.

## Hazards
Env-of-references must never leak past the call — audit every place a
closure value can flow (the brief-21b escape positions list). The
existing closure suite + concurrency suite (spawn uses escaping heap
envs) is the regression oracle. Exclusivity false positives: the
existing exclusivity_* acceptance tests must stay green.

## Report back
Per item: mechanism, where, verification. The variance rule chosen for
the escaping bit (item 1) stated explicitly. Whether iteration APIs
needed a Copy bound (item 6). Deviations; non-allowlisted commands.

## Landed (Jul 28) — outcomes and deviations
- Variance: escaping-typed values are accepted in non-escaping slots
  (safe direction); non-escaping values into escaping slots error at
  the value-transfer checkpoint; closure literals lower to the slot.
- `Vector.each` shipped with `T: Copy` bound (one element copy per
  visit via `get`; never a silent ExplicitCopy duplicate). The
  accumulation idiom verified end to end.
- **`map`/`fold` deferred**: they need method-level generic type
  parameters (`map<U>`), which the compiler lacks, and the free-function
  fallback hits the pre-existing monomorphization recursion on
  `&Vector<T>` params (tracker L8). `each` + borrow-captured
  accumulators subsumes both meanwhile (demonstrated in
  `vector_each_fold_map.saw`).
- Enabling fixes kept: `Void` as a builtin type name; `$N` scanning
  through compound assignments.

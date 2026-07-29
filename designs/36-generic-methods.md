# Design Brief 36 — Generics family: generic methods + monomorphization recursion fixes

**Source:** tracker C5 (brief-29 blocker) + L7/L8 (brief-30/32 findings).
The three are one family: L7/L8 are monomorphization gaps on
generic-container parameters; C5 (method-level generic type parameters)
is both a missing feature and the clean fix path for the API shapes
those gaps block.
**Exit criteria:** `Vector.map<U>`/`fold<A>` land and work (the brief-29
deferral clears); L7 and L8 repros compile and run correctly (red-proven
tests first); full suite green; exactly the 2 sanctioned ledger xfails
remain (array_elem_field_assign, array_elem_overwrite_deinit).

## Items

### 0. Red tests for the known gaps (verify-twice)
- **L8:** a generic function taking a generic container by parameter —
  `func unbox<T>(b: Box<T>) -> T` (brief-32's exact repro) and a
  `&Vector<T>`-parameter variant (brief-29's) — currently recurses in
  monomorphization. Prove red, keep as tests.
- **L7:** consuming a generic-instantiated `Result<T,E>` via direct
  `match`/`try!` at the call site ("Undefined struct: T", brief-30's
  finding). Prove red, keep as tests.

### 1. Fix the monomorphization recursion (L8) and deferred-substitution
gap (L7)
Root-cause in codegen/generics.py + calls.py: when instantiating
`f<Int>` whose parameter/return types mention `Box<T>`/`Vector<T>`/
`Result<T,E>`, the nested generic must be monomorphized with the
SUBSTITUTED args (Box<Int>) — not re-entered abstractly (recursion) or
left unsubstituted (undefined T). Likely one shared substitution walk
used by both param-type and return-type instantiation paths. The
brief-24 abstract body checks and brief-28's static-method
substitution fix are adjacent machinery — reuse, don't duplicate.

### 2. Method-level generic type parameters (C5)
`func map<U>(&self, transform: (T) -> U) -> Vector<U>` inside
`extension Vector<T>`: a method introduces type params beyond the
extension's. Scope: parser (type-param list on extension methods),
typechecker (params in scope for the signature/body; abstract body
checking per brief 24 covers the new params; explicit call-site type
args `v.map<Int>(...)` — type-argument INFERENCE remains out of scope,
consistent with free functions), codegen (mangling composes struct
specialization + method type args — extend the canonical mangler, no
new scheme), monomorphization (instantiate per (struct args, method
args) pair via the existing pending-body queue).

### 3. The forcing consumers: Vector.map / Vector.fold
`map<U>(&self, transform: (T) -> U) -> Vector<U>` and
`fold<A>(&self, initial: A, combine: (A, T) -> A) -> A` in
std/vector.saw, non-escaping closure params, same `T: Copy` element
discipline as `each` (no silent ExplicitCopy duplication; the copy
bound story per brief-29's landed notes). Tests: map Int->Int and
Int->String (crossing type families), fold to Int and to a struct
accumulator, plus the brief-29 `each`-subsumption test still passing
(no regression in the workaround pattern).

### 4. Docs
CLAUDE.md + LANGUAGE_SPEC.md generics sections: method-level type
params with the explicit-instantiation syntax; note inference is still
future work.

## Hazards
Mangling and monomorphization are the miscompile-class areas — the
whole generic suite plus brief-33's array tests are the oracle; run
generic,vector,box,result,equatable families at every checkpoint. Do
not regress the L7 workaround pattern (concrete-typed consumer) or
brief-28's static-method-on-generic-struct path.

## Report back
Item-0 red verdicts; root cause of the recursion (item 1) precisely;
the (struct×method) mangling scheme chosen (item 2); whether map/fold
needed anything beyond C5 (item 3); suite tally; deviations;
non-allowlisted commands.

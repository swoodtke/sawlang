# Design Brief 24 — Typechecker family: generic-body deferred checks + effect-graph gaps

**Source:** the two generic-body ledger xfails (brief 02's sanctioned
deferrals, now due) and the effect-prototype's documented gaps (brief 22
report / paper 18).
**Exit criteria:** `generic_body_unbound_method` and
`generic_body_wrong_return` XFAILs flip (markers removed); the effect-gap
tests below land and pass; full suite green; no unexplained xfail
movement. HAZARD: conservativeness must be preserved where genuinely
undecidable — the existing generic suite (identity/first/getItem/
printDescription/bounded extensions/Vector/Map) is the false-positive
oracle; breaking any of it means your check is too eager.

## Items

### 1. Bound-aware method resolution on opaque type params
In a generic body, `x.method()` where `x: T`: resolve against the methods
of `T`'s declared trait bounds (including `Copy`-family implications —
`T: Copy` grants `.copy() -> T`, already special-cased; unify if clean).
Found in a bound's trait → type-check against that signature (associated
types stay abstract). NOT found in any bound → compile error naming the
method and the bounds (`type parameter T has no method frobnicate; its
bounds are [...]`) — this flips `generic_body_unbound_method`. Unbounded
T calling any method: error.

### 2. Abstract return-type reconciliation
Reconcile a generic body's return type where DECIDABLE: a concrete
mismatch (`-> Int`, body yields `Bool`) errors — flips
`generic_body_wrong_return`. Anything involving type params/associated
types stays deferred (document the rule in a comment). Result/Optional
auto-wrap: apply when the declared return is concrete
Result/Optional-of-concrete; defer otherwise.

### 3. Effect-graph completeness (brief-22 gaps)
Wire suspendability edges for: module-qualified calls, static-method and
custom-init calls, calls through function-typed STRUCT FIELDS
(conservative: non-sync field type ⇒ suspending call), and reject a
non-literal function VALUE passed where a `sync` function type is
expected unless its type is sync (the boundary gap). `sync` methods in
extensions: parse + check (the `Method.is_sync` machinery exists per the
report). Tests for each (error + acceptance where sensible), extending
the existing effect-test naming.

## Report back
Per item: rule implemented, decidability boundary chosen (item 2),
false-positive scan results against the generic suite, effect edges
added and how verified. Deviations; non-allowlisted commands.

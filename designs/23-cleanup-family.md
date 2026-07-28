# Design Brief 23 — Cleanup family: enum payloads, if-let bindings, return-chain temps

**Source:** tech-debt ledger + brief-17 report discoveries. All three are
destruction gaps; the drop-glue machinery from brief 17 is the foundation.
**Exit criteria:** `enum_payload_deinit` XFAIL flips (marker removed); the
two new gaps get verify-twice ledger tests that are then FIXED in the same
brief (test lands red-proven, fix lands, test passes — no new xfails
remain); full suite green; no unexplained xfail movement.

## Items

### 1. Enum payload deinit (the ledger xfail)
When an enum value dies, its ACTIVE variant's payload fields needing
cleanup must be released. Extend the drop-glue path
(`codegen/resources.py::_emit_drop_at` and the needs-cleanup detection,
which currently bail for non-struct aggregates): switch on the tag, per
variant release payload fields via `__deinit_in_place`/String release, in
reverse field order. Containment: verify the typechecker's containment
rules cover enums holding Deinit/ExplicitCopy payloads (a struct must
declare; does an enum? — probe; if enums dodge containment entirely,
apply the struct rule to enums, with tests). Also cover `Optional<T>`
payloads if they flow through the same enum machinery — probe
`let x: Resource? = Resource(...)` scope exit.

### 2. `if let` / `guard let` bindings of Deinit values (brief-17 finding)
Bindings introduced by `if let`/`if var`/`guard let` branches are never
registered for cleanup. Verify-twice test first (deinit-printing type
bound via if-let, must print at branch-scope exit), then fix: register
the binding in the branch's cleanup scope (codegen conditionals/guard
lowering). Watch: `guard let` binding lives in the ENCLOSING scope (the
whole point of guard) — its cleanup belongs to the enclosing scope, not
the guard body. Both cases tested. Also probe `while let` if it exists.

### 3. Receiver temporaries in `return f().g()` (brief-17 limitation)
The statement-temp drain is skipped when the block terminates. Fix:
drain statement temps BEFORE emitting the return's terminator (the
returned value itself must be exempted/transferred first — no
release-what-you-return). Verify-twice test: `return makeR().value()`
where R prints on deinit — R's deinit must print before the caller
resumes, exactly once.

## Hazards
Double-free, as always with this family: the full deinit_*/string_*/
implicit_copy_* ordering suite is the oracle; run at every checkpoint;
-O0 spot check on new tests.

## Report back
Per item: mechanism, where, double-free ruled out how. The enum
containment probe verdict. Optional-payload verdict. Deviations;
non-allowlisted commands.

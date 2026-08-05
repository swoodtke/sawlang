# Design 128 — DRAFT: structural Deinit/ExplicitCopy synthesis (DO NOT DISPATCH)

STATUS: DRAFT for user review (Aug 4). Language-change brief; needs a user
decision on the model before dispatch.

## Problem (from the claims review, HOLDS-WITH-CAVEATS)
The most common resource-owning shape — `struct Holder { v: Vector<Int> }` —
does not compile without a hand-written conformance whose body is pure
transcription: a `Deinit` that deinits each owning field in order, and/or an
`ExplicitCopy` that copies each field. The compiler already knows every
field's ownership class (it enforces them everywhere else). This is
explicitness where the compiler knows the answer — pure tax, and it fails
the "expected, not easy" bar. `Equatable`'s empty-conformance synthesis
(`extension Holder: Equatable {}` derives memberwise ==) is the established
model.

## Proposed model (mirror Equatable)
1. **Deinit: fully implicit.** A struct/enum with owning fields gets a
   synthesized memberwise deinit (declaration-order fields, reverse drop
   order — match locals). A hand-written `Deinit` REPLACES the synthesized
   one and must consume every owning field itself (current rule) — no
   before/after hooks, no mixing. Rationale: destruction is not optional
   behavior; requiring a conformance to make ownership compile is the tax.
2. **ExplicitCopy: opt-in empty conformance.** `extension Holder:
   ExplicitCopy {}` synthesizes memberwise `copy()` when every field is
   copyable (ImplicitCopy or ExplicitCopy); a non-copyable field makes the
   empty conformance a compile error naming the field. Not implicit —
   copyability is a semantic promise (matches the Copy-family design).

## Open questions for the user
- Is implicit Deinit right, or should it be the same empty-conformance
  opt-in as copy? (Implicit changes drop behavior of EXISTING code that
  today fails to compile — so it is strictly additive — but enums with
  payload mixes need a rule statement.)
- Interaction with design 17 aggregate-deinit ordering and the design 65
  deep-copy path: synthesis should LOWER onto those existing paths, not
  duplicate them — confirm.
- `NoCopy` fields: ExplicitCopy synthesis obviously errors; does Deinit
  synthesis cover NoCopy fields (it must — they still drop)?

## Shape of the work once approved
Typechecker: conformance synthesis pass (Equatable's machinery
generalized). Codegen: none new (lower onto existing deinit/copy paths).
Tests: the review's `Holder` probe compiles; drop-order test; error-message
tests for the non-copyable-field case. Spec + skill sections.

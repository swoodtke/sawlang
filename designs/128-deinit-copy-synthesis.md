# Design 128 — structural Deinit synthesis + @synthesize ExplicitCopy

STATUS: DECIDED (user, Aug 4-5) — model fully specified below, all open
questions closed. Dispatch-ready; dispatches with the pending queue
(129/130), not before the parked-branch integration.

## Problem (from the claims review, HOLDS-WITH-CAVEATS)
The most common resource-owning shape — `struct Holder { v: Vector<Int> }` —
does not compile without a hand-written conformance whose body is pure
transcription: a `Deinit` that deinits each owning field in order, and/or an
`ExplicitCopy` that copies each field. The compiler already knows every
field's ownership class (it enforces them everywhere else). This is
explicitness where the compiler knows the answer — pure tax, and it fails
the "expected, not easy" bar. The review rates it the single biggest
ergonomic tax in the language: it hits every struct that owns a collection,
i.e. most structs.

## Decided model

1. **Deinit: fully implicit.** `[user]` The compiler knows what to do with
   every field type. A struct/enum with owning fields gets a synthesized
   memberwise deinit (declaration-order fields, reverse drop order — match
   locals). Covers `NoCopy` fields (they drop like anything else). Enums:
   the synthesized deinit switches on the tag and deinits the active
   variant's owning payload fields (payload-deep, mirroring Equatable's
   synthesis model); variants without owning payload are no-ops. A
   hand-written `Deinit` REPLACES the synthesized one and must consume every
   owning field itself (current rule) — no before/after hooks, no mixing.

2. **A bare owning struct still does not compile.** `[user]` The compiler
   doesn't know what the user WANTS copy-wise, so the existing copy-policy
   containment rule is unchanged: a struct with an `ExplicitCopy`/`NoCopy`
   field must declare its own policy (`NoCopy` = move-only, or
   `ExplicitCopy`). Only the `does not implement Deinit` error disappears;
   the remaining error's hint names the policy choice.

3. **ExplicitCopy synthesis requires explicit buy-in: `@synthesize`.**
   `[user]` A bare empty `extension Holder: ExplicitCopy {}` is a compile
   error (hint: add `@synthesize`, or write `copy()` by hand). With the
   marker:
   ```saw
   @synthesize
   extension Holder: ExplicitCopy {}
   ```
   the compiler derives memberwise `copy()` when every field is copyable
   (ImplicitCopy or ExplicitCopy); a non-copyable field makes it a compile
   error naming the field. The marker is the user's acknowledgment that a
   deep memberwise copy of all fields is being generated. `@synthesize` is
   deliberately generic — extensible to future synthesized conformances.

4. **Equatable is unchanged.** `[user]` Empty-conformance synthesis
   (`extension T: Equatable {}`) keeps working with no marker — equality has
   no ownership/allocation cost, which is what the marker exists to flag.
   Whether `@synthesize` later unifies the derive story is out of scope.

5. **Riders (review §2.2 diagnostic bugs).** `[user]` The conformance-error
   hints currently teach `func deinit(var self)` / `func copy(self)` —
   receiver spellings the spec doesn't have. Fix the hints to the spec
   forms (`&var self` / `&self`), and make the undocumented `var self`
   receiver spelling a compile error with a fixit suggesting `&var self`
   (audit in-tree code for uses first; expected none).

6. **Lowering constraint.** Synthesis LOWERS onto the existing design-17
   aggregate-deinit ordering and design-65 deep-copy paths — no duplicate
   destruction/copy logic in codegen.

## Shape of the work
Parser: `@synthesize` joins the attribute vocabulary (design 58 machinery),
valid on extensions. Typechecker: conformance synthesis pass (Equatable's
machinery generalized) — implicit deinit synthesis, marker-gated
ExplicitCopy synthesis, bare-empty-ExplicitCopy error, non-copyable-field
error, `var self` rejection + fixit, hint spelling fixes. Codegen: none new
(lower onto existing deinit/copy paths). Tests: the review's `Holder` probe
compiles under both `NoCopy` and `@synthesize ExplicitCopy`; drop-order
test (declaration order, reverse); enum payload-mix deinit; bare empty
ExplicitCopy conformance errors; non-copyable-field error names the field;
`var self` fixit. Spec + skill sections (load saw-docs for the prose).

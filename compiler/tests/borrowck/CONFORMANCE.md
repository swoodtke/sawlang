# The borrow check's conformance matrix

Every row of `examples/conformance/INDEX.md`'s five borrow-check sections, and
what in sawc2 answers it. A row's verdict was read from `sawc2 mir --check`
over its covering file's migrated copy in `tests/corpus/`. The borrowck lane
fails when a row of those sections is missing here, when a row here is not in
INDEX.md, or when an owner is not one of the words below.

| Owner | Meaning |
|---|---|
| `U6d1` | the borrow check's initialisation analysis (SL-460 U6d1): a refusal fixture or golden under `compiler/tests/borrowck/` |
| `U6d2` | the borrow check's loans and conflicts (SL-460 U6d2), not written yet |
| `typecheck` | refused or accepted by typecheck today: the named fixture in `compiler/tests/typecheck/` |
| `SL-462` | a typecheck rule SL-462 owns and has not written; SL-462 wrote reference positions, mutability and moving out of a part or through a borrow, so no row names it |
| `typecheck-gap` | a typecheck rule that refuses nothing today, which no issue owns yet (a finding of this unit) |
| `parse` | the parser refuses the spelling: the named fixture in `compiler/tests/parse/` |
| `mir` | the MIR stage: the named golden in `compiler/tests/mir/` |
| `§3.7` | drop elaboration: how many times a value is released, and where |
| `§3.8` | the lifecycle glue generated per concrete type: retains and copies |
| `§3.9` | coroutine lowering |
| `slice.not-yet` | sawc2 refuses a construct in the row's file as outside the bootstrap slice; the construct is named, and the owner the row reaches after it in parentheses |

## Mutability

| Row | Owner | Covered by, or why not |
|---|---|---|
| M01 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.saw` |
| M02 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.compound.saw` |
| M03 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.exclusive-ref.saw` |
| M04 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.field.saw` |
| M05 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.exclusive-receiver.saw` |
| M06 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.vector-push.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| M07 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.array-element.saw` |
| M08 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.vector-element.saw` |
| M09 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.tuple-element.saw` |
| M10 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-reference.saw` |
| M11 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-reference-replace.saw` |
| M12 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-reference-receiver.saw` |
| M13 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver.saw` |
| M14 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-call.saw` |
| M15 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-field-call.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| M16 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-projection.saw` |
| M17 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.for-binding.saw` |
| M18 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.if-let.saw` |
| M19 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.parameter.saw` |
| M20 | typecheck | `mutability.immutable`, a by-value capture is a `let` in every closure (SL-472): `compiler/tests/typecheck/refuse/mutability.immutable.value-capture.saw`, the write-kind matrix `mutability.immutable.capture-*` (plain, `move`, `copy` × escaping, non-escaping), and the shared heap counter, `compiler/tests/typecheck/refuse/mutability.immutable.capture-shared-environment.saw`; the accepted rows, typecheck golden `capture_rules.saw`; the non-escaping `[&var v]` writer's loan, U6d2's `loan.closure-carrier.*` |
| M21 | typecheck | `mutability.immutable` (SL-472): `compiler/tests/typecheck/refuse/mutability.immutable.value-capture-field.saw`, and the field cells of the write-kind matrix |
| M22 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.accessor-root.saw` |
| M23 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-closure-parameter.saw` |
| M24 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-epilogue.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| M25 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.map-force.saw`; the migrated file is refused first by `member.unknown`, a migration artifact |
| M26 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.copy-receiver.saw` |
| M27 | slice.not-yet | a method call on `any Trait` (then typecheck: a `&self` method of an interior cell borrows shared, which the writability funnel never asks about) |
| M28 | slice.not-yet | a `borrow` block over `SpinLock.lock`, which lends through a closure parameter (then typecheck: the indirection carve-out, accepted in `compiler/tests/typecheck/golden/mutability.saw`) |
| M29 | typecheck | accepted: a `&var` parameter's writes; typecheck golden `borrow_arguments.saw` |
| M30 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.static.saw` |
| M31 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-window.saw`; the migrated file is refused first by `subscript.role`, a migration artifact |
| M32 | typecheck | accepted: the indirection carve-out through a window, `self.rows[0][0] += 100` in `compiler/tests/typecheck/golden/mutability.saw` |
| M33 | typecheck | accepted: a window write in a `&self` accessor's prologue, inline (`Log.at`) and heap (`Rows.peek`), in `compiler/tests/typecheck/golden/mutability.saw` |
| M34 | typecheck | accepted: a `&var self` accessor's writes, as any `&var self` body's (`compiler/tests/typecheck/golden/mutability.saw`); `#lend_var` is not modelled |
| M35 | typecheck | accepted: writes under `&var self`, `compiler/tests/typecheck/golden/mutability.saw` |
| M36 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-capture-self.saw` |
| M37 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.array-element.saw` and `compiler/tests/typecheck/refuse/mutability.immutable.array-element-compound.saw` |
| M38 | U6d2 | a compound assignment's right side borrowing the path it writes |
| M39 | slice.not-yet | `syntax.stmt.optional-assign.plain` (then typecheck, `mutability.immutable`) |
| M40 | slice.not-yet | `syntax.stmt.optional-assign.compound` (then typecheck, `mutability.immutable`) |
| M41 | typecheck | accepted: the indirection carve-out at a `Vector` subscript, nested, and a hand-written accessor over a `Vector`, in `compiler/tests/typecheck/golden/mutability.saw`; the migrated file is refused first by `operator.undefined`, a migration artifact |
| M42 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.shared-receiver-array.saw` |
| M43 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.optional-payload.saw` |
| M44 | typecheck | `mutability.immutable`: `compiler/tests/typecheck/refuse/mutability.immutable.array-element-receiver.saw` |

## References are parameters only

| Row | Owner | Covered by, or why not |
|---|---|---|
| R01 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.return.saw` |
| R02 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.method-return.saw` |
| R03 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.requirement-return.saw` |
| R04 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.extern-return.saw` |
| R05 | slice.not-yet | `syntax.expr.shorthand-param` in the migrated file (then typecheck, `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.function-type-return.saw`) |
| R06 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.return-tuple.saw` |
| R07 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.return-optional.saw` |
| R08 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.return-vector.saw` |
| R09 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.field.saw` |
| R10 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.payload.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| R11 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.saw` |
| R12 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.exclusive-binding.saw` |
| R13 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.type-argument.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| R14 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.explicit-instantiation.saw` |
| R15 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.closure-return.saw` |
| R16 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.array-literal.saw` |
| R17 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.tuple-literal.saw` |
| R18 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.map-value.saw` |
| R19 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.static.saw` |
| R20 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.alias-field.saw` |
| R21 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.alias-return.saw` |
| R22 | slice.not-yet | the `Thread.spawn` and `Task.spawn` forms (then typecheck `capture.escaping-borrow`) |
| R23 | typecheck | `capture.escaping-borrow`: `compiler/tests/typecheck/refuse/capture.escaping-borrow.saw` |
| R24 | slice.not-yet | `TaskGroup.spawn` (then typecheck) |
| R25 | slice.not-yet | `TaskGroup.spawn` (then typecheck and U6d2: the task borrows its root) |
| R26 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.optional-written.saw` |
| R27 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.nested-generic.saw` |
| R28 | typecheck | accepted: the sanctioned `(&var n) as UnsafePointer<Int>`, `address` in `compiler/tests/typecheck/golden/reference_positions.saw` |
| R29 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.cast-to-integer.saw` |
| R30 | typecheck | accepted: a non-escaping borrow capture; typecheck golden `captures.saw` |
| R31 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.operand.saw` |
| R32 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.box.saw` |
| R33 | typecheck | accepted: `borrows` lends in `compiler/tests/typecheck/golden/reference_positions.saw`; the same result without `borrows` is `compiler/tests/typecheck/refuse/type.reference-position.method-return.saw` |
| R34 | typecheck | `type.reference-position`: `compiler/tests/typecheck/refuse/type.reference-position.field-function-type.saw` |
| R35 | typecheck | `capture.escaping-borrow`: `compiler/tests/typecheck/refuse/capture.escaping-borrow.reference.saw` |
| R36 | typecheck | `capture.escaping-borrow`: `compiler/tests/typecheck/refuse/capture.escaping-borrow.saw` |
| R37 | typecheck | accepted: a non-escaping closure naming `self`; typecheck golden `captures.saw` |
| R38 | typecheck | accepted: the same in a suspending method (then §3.9) |
| R39 | typecheck | accepted: `[&self]` and `[&var self]`; typecheck golden `captures.saw` |
| R40 | typecheck | `capture.exclusive-self`: `compiler/tests/typecheck/refuse/capture.exclusive-self.saw` |
| R41 | typecheck | `capture.escaping-borrow`: `compiler/tests/typecheck/refuse/capture.escaping-borrow.explicit.saw` |
| R42 | parse | `[self]` and `[move self]` are no spellings: `compiler/tests/parse/negative/cells.saw` |
| R43 | typecheck-gap | a borrow-capturing closure stored through a `&var` parameter; the migrated file is refused first by `result.discarded`, a migration artifact |
| R44 | typecheck-gap | the same into a local container; the migrated file is refused first by `result.discarded`, a migration artifact |

## The Law of Exclusivity

| Row | Owner | Covered by, or why not |
|---|---|---|
| X01 | U6d2 | `f(&var x, &var x)` |
| X02 | U6d2 | `f(&var x, &x)` |
| X03 | U6d2 | whole overlapping its field |
| X04 | U6d2 | accepted: disjoint fields |
| X05 | U6d2 | accepted: two shared reads |
| X06 | U6d2 | dynamic indices overlap |
| X07 | U6d2 | accepted: distinct constant indices |
| X08 | U6d2 | the same tuple element twice |
| X09 | U6d2 | accepted: disjoint tuple elements |
| X10 | U6d2 | a `move` argument aliasing a reference argument |
| X11 | U6d2 | `&var self` with a `&self.field` argument |
| X12 | typecheck | forwarding `&` as `&var`: `type.not-a-place`, `compiler/tests/typecheck/refuse/type.not-a-place.saw` |
| X13 | U6d2 | `g(&var r, &r)` from one `&var` |
| X14 | U6d2 | `v.push` inside a window on the same vector |
| X15 | U6d2 | `v.push` inside a place window |
| X16 | U6d2 | two exclusive place windows in one call |
| X17 | U6d2 | accepted: nested windows |
| X18 | U6d2 | accepted: a `&var` across a suspension (then §3.9) |
| X19 | U6d2 | accepted: a `&var` forwarded three deep |
| X20 | U6d2 | a named accessor's place charging its root |
| X30 | U6d2 | two exclusive windows on a trivial struct |
| X31 | U6d2 | a window beside a `&var` of its root |
| X33 | U6d2 | two exclusive windows on a Copy-tier struct |
| X40 | U6d2 | two windows on `Data`; the migrated file is refused first by `result.discarded`, a migration artifact |
| X41 | U6d2 | a place through a `!` head charging its root |
| X41 | U6d2 | a nested call's `&var` overlapping a sibling |
| X42 | U6d2 | accepted: a nested reference onto a disjoint root |
| X43 | U6d2 | accepted: a nested reference disjoint from every sibling |
| X44 | U6d2 | a nested call's `&var` overlapping the receiver |
| X45 | U6d2 | two nested calls borrowing one root |

## Moves and use-after-move

| Row | Owner | Covered by, or why not |
|---|---|---|
| V01 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.saw` |
| V02 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.double.saw` |
| V03 | typecheck | `transfer.move-from-borrow`: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.saw` |
| V04 | typecheck | `transfer.move-from-borrow`: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.shared.saw` |
| V05 | typecheck | `transfer.partial-move`: `compiler/tests/typecheck/refuse/transfer.partial-move.saw` |
| V06 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.loop.saw` |
| V07 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.branch.saw` |
| V08 | U6d1 | accepted: a moved `var` revived by assignment, `compiler/tests/borrowck/golden/reinit.saw` |
| V09 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.explicit.saw` |
| V10 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.saw` |
| V11 | typecheck-gap | `.copy()` on a NoCopy type is not refused today |
| V12 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.capture.saw` |
| V13 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.field-init.saw` |
| V14 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.loop.saw`, `compiler/tests/borrowck/refuse/move.use-after.field-init.saw` |
| V15 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.force.saw` |
| V16 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.projection.saw` |
| V17 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.payload.saw` |
| V18 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.saw` |
| V19 | typecheck | `copy.undeclared-policy`: `compiler/tests/typecheck/refuse/copy.undeclared-policy.saw` |
| V20 | typecheck | `copy.undeclared-policy`: `compiler/tests/typecheck/refuse/copy.undeclared-policy.enum.saw` |
| V21 | typecheck | `transfer.implicit-copy`: `compiler/tests/typecheck/refuse/transfer.implicit-copy.payload.saw` |
| V22 | typecheck-gap | `.copy()` on a tuple with a NoCopy element is not refused today |
| V23 | typecheck | `conformance.deinit`: `compiler/tests/typecheck/refuse/conformance.deinit.saw` |
| V24 | typecheck-gap | a manual `deinit()` call is not refused today |
| V25 | §3.7 | a Copy-tier struct's deinit runs once: one static drop per value, `compiler/tests/drops/conformance.tsv` (the retain is §3.8's glue) |
| V26 | slice.not-yet | constructing the builtin type `Atomic` (then typecheck: `Atomic` is move-only) |
| V27 | typecheck | `copy.undeclared-policy`: `compiler/tests/typecheck/refuse/copy.undeclared-policy.saw` |
| V28 | slice.not-yet | constructing the builtin type `Atomic` (then typecheck, accepted) |
| V29 | slice.not-yet | constructing the builtin type `Atomic` (then typecheck, accepted) |
| V30 | slice.not-yet | constructing the builtin type `Atomic` (then U6d1, accepted moves) |
| V31 | typecheck | `transfer.partial-move`: `compiler/tests/typecheck/refuse/transfer.partial-move.vector-element.saw`; the migrated file is refused first by `result.discarded`, a migration artifact |
| V32 | typecheck | accepted: a Copy bound met by the derived tier; typecheck golden `tiers.saw` |
| V33 | typecheck | `copy.requirement` at a silent-copy bound; the migrated file is refused first by `result.discarded`, a migration artifact |
| V34 | typecheck | accepted: `T: ExplicitCopy` licenses `.copy()`; typecheck golden `tiers.saw` |
| V35 | typecheck | accepted: nested Vectors iterated by borrow |
| V36 | typecheck | `copy.requirement`: `compiler/tests/typecheck/refuse/copy.requirement.saw` |
| V37 | typecheck | `copy.requirement`: `compiler/tests/typecheck/refuse/copy.requirement.saw` |
| V38 | typecheck | `copy.requirement`: `compiler/tests/typecheck/refuse/copy.requirement.saw` |
| V39 | typecheck | `copy.requirement`: `compiler/tests/typecheck/refuse/copy.requirement.saw` |
| V40 | slice.not-yet | `TaskGroup.spawn` (then typecheck `copy.requirement`) |
| V41 | typecheck | accepted: branch-exclusive uses stay move-only |
| V42 | typecheck | accepted: a duplicating body at every tier that satisfies it |
| V43 | typecheck-gap | `.copy()` through wrappers without a bound is not refused today |
| V44 | typecheck | accepted: bounded wrapper copies (then §3.8) |
| V45 | typecheck-gap | a public generic exceeding move-only without declaring its bound is not refused today |
| V46 | typecheck-gap | a declared bound the body exceeds is not refused today |
| V47 | typecheck | accepted: returning a whole binding out of a generic body is a move |
| V48 | slice.not-yet | `syntax.expr.optional-member` (then §3.7: a non-escaping `move` capture transfers when the body runs) |
| V49 | typecheck | `capture.escaping-consume`, an escaping closure may not consume a capture (SL-469): `compiler/tests/typecheck/refuse/capture.escaping-consume.saw`, and the matrix `capture.escaping-consume.*` (returned, stored, bound, `escaping` parameter × each consuming use); the non-escaping consume is accepted, typecheck golden `capture_rules.saw` |
| V50 | slice.not-yet | the intrinsic `__saw_drive` (then §3.9 and §3.7) |
| V51 | U6d1 | `move.use-after`, the rule a second consuming call meets: `compiler/tests/borrowck/refuse/move.use-after.double.saw` |
| V52 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.consumed.saw` |
| V53 | typecheck-gap | a `NoMove` receiver at a consuming call is not refused today |
| V54 | U6d1 | `consumes.some-paths`: `compiler/tests/borrowck/refuse/consumes.some-paths.saw`; every path, none, and a diverging path exempt, `compiler/tests/borrowck/golden/consumes.saw` |
| V55 | typecheck | `consumes.move`: `compiler/tests/typecheck/refuse/consumes.move.saw` |
| V56 | §3.7 | a consuming body replaces the hand-written deinit body: the fields that stay drop statically, `compiler/tests/drops/golden/consumes.saw`, `compiler/tests/drops/conformance.tsv` |
| V117 | slice.not-yet | the release of a consumed receiver that moves out whole, `compiler/tests/mir/refuse/consumes-whole.saw` (then U6d1 and §3.7) |
| V118 | slice.not-yet | the release of a consumed receiver that moves out whole, `compiler/tests/mir/refuse/consumes-whole.saw` (then U6d1: `consumes.some-paths` covers the receiver itself) |
| V119 | slice.not-yet | the release of a consumed receiver that moves out whole, `compiler/tests/mir/refuse/consumes-whole.saw` (then U6d1; the field form, a use of `self` after `move self.f`, is `compiler/tests/borrowck/refuse/move.use-after.partial.saw`) |
| V120 | typecheck | `consumes.move-self`: `compiler/tests/typecheck/refuse/consumes.move-self.saw` |
| V57 | slice.not-yet | the intrinsic `__saw_deinit_in_place` (then §3.7) |
| V58 | typecheck-gap | a `NoMove` placement after a borrow is not refused today |
| V59 | typecheck-gap | a bound `NoMove` value moved into an argument is not refused today |
| V60 | typecheck | `transfer.move-from-borrow`: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.match-payload.saw` |
| V61 | typecheck | `transfer.move-from-borrow`: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.match-self.saw` |
| V62 | typecheck | `transfer.move-from-borrow`, a Copy-tier payload: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.match-payload.saw` |
| V63 | §3.7 | an owned match still consumes, released once: `compiler/tests/drops/golden/dissolves.saw`, `compiler/tests/drops/conformance.tsv` |
| V64 | typecheck | `transfer.implicit-copy` at a forwarding cast; tests/corpus file refused by it |
| V65 | §3.8 | the Copy tier retains through a forwarding cast |
| V66 | typecheck | a forwarding alias projection; refused today by `type.mismatch` first |
| V67 | typecheck | accepted: building casts are untouched |
| V68 | typecheck | `transfer.move-from-borrow`: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.closure-parameter.saw` |
| V69 | slice.not-yet | a `borrow` block over `Mutex.lock`, which lends through a closure parameter (then typecheck, `transfer.move-from-borrow`) |
| V70 | typecheck | `transfer.move-from-borrow`, a Copy-tier referent: `compiler/tests/typecheck/refuse/transfer.move-from-borrow.closure-parameter.saw` |
| V71 | §3.7 | the borrowed-binding fence is narrow, each value released once: `compiler/tests/drops/conformance.tsv` |
| V72 | §3.7 | std visitors lend: `compiler/tests/drops/conformance.tsv`; its error file is refused first by `result.discarded`, a migration artifact |
| V73 | §3.7 | a by-value closure parameter is released once: `compiler/tests/drops/conformance.tsv` |
| V74 | §3.7 | a moved closure parameter, released once: `compiler/tests/drops/conformance.tsv` |
| V75 | §3.7 | escaping and non-escaping release identically: `compiler/tests/drops/conformance.tsv` |
| V76 | §3.7 | `fold` threads its accumulator: `compiler/tests/drops/conformance.tsv` |
| V77 | typecheck | `transfer.implicit-copy` at a value branch arm; tests/corpus file refused by it |
| V78 | typecheck | `transfer.implicit-copy` at every value-arm position; tests/corpus file refused by it |
| V79 | typecheck | `transfer.implicit-copy` at every block-tail construct; tests/corpus file refused by it |
| V80 | §3.8 | the Copy tier through a value arm retains once |
| V81 | typecheck | accepted: the value-arm fence is narrow |
| V82 | typecheck | `transfer.implicit-copy` at a closure tail; tests/corpus file refused by it |
| V83 | typecheck | `transfer.implicit-copy` at every closure-tail source; tests/corpus file refused by it |
| V84 | §3.8 | the Copy tier through a closure tail retains once |
| V85 | typecheck | accepted: the closure-tail fence is narrow |
| V86 | typecheck | `transfer.implicit-copy` reading `self` into a new owner; tests/corpus file refused by it |
| V87 | typecheck | `transfer.implicit-copy` at a `try` subject; tests/corpus file refused by it |
| V88 | typecheck | `transfer.implicit-copy` before an auto-wrap; tests/corpus file refused by it |
| V89 | §3.8 | forwarding positions duplicate once; the migrated file is refused by `transfer.implicit-copy`, a migration artifact |
| V90 | slice.not-yet | `syntax.stmt.break` with a value (then §3.7) |
| V91 | slice.not-yet | `syntax.expr.try.catch` (then §3.8) |
| V92 | slice.not-yet | `syntax.expr.try-block` (then §3.8) |
| V93 | typecheck | accepted: a generic transfer judged at the instance |
| V94 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V95 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V96 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V97 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V98 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V99 | §3.8 | every payload read retains once |
| V100 | §3.8 | a bounded `copy()` at the automatic tier retains |
| V101 | §3.8 | the copy family carries the tier |
| V102 | §3.8 | a derived `copy()` duplicates every field at its tier |
| V103 | §3.8 | one copy funnel duplicates once |
| V104 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.7) |
| V105 | §3.8 | a `[copy x]` capture releases its duplicate |
| V106 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V107 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.9) |
| V108 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.8) |
| V109 | U6d1 | `move.use-after`: `compiler/tests/borrowck/refuse/move.use-after.while-condition.saw` |
| V110 | U6d1 | accepted: a condition move the body revives, `compiler/tests/borrowck/golden/loops.saw` |
| V111 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.8) |
| V112 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.8) |
| V113 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.8) |
| V114 | slice.not-yet | the intrinsic `__saw_suspend` (then §3.8) |
| V115 | §3.7 | a stored closure owns its captures; the migrated file is refused first by `type.mismatch`, a migration artifact, `compiler/tests/drops/conformance.tsv` |
| V116 | §3.7 | a non-escaping closure keeps its stack environment: `compiler/tests/drops/conformance.tsv` |

## Places (`borrows` / `lend`)

| Row | Owner | Covered by, or why not |
|---|---|---|
| P01 | U6d2 | `return` of a value in a `borrows` body (inside an accessor) |
| P02 | slice.not-yet | an accessor whose code after `lend` is reachable without lending (then U6d2) |
| P03 | U6d2 | two `lend`s on one path (inside an accessor) |
| P04 | slice.not-yet | an accessor whose code after `lend` is reachable without lending (then U6d2) |
| P05 | U6d2 | `lend` of an accessor's local: the lent place's root |
| P06 | parse | `#lend_var` is removed syntax: `compiler/tests/parse/negative/removed.saw` |
| P07 | parse | `#lend_var` is removed syntax: `compiler/tests/parse/negative/removed.saw` |
| P08 | mir | superseded: an accessor body may suspend (SL:borrowing §2.5); `compiler/tests/mir/golden/accessors.saw`, `Grid.waited` |
| P09 | U6d2 | an assignment target that is no place; the migrated file is refused first by `result.discarded`, a migration artifact |
| P10 | mir | the absent path opens no window: `compiler/tests/mir/golden/accessors.saw`, `Grid.find` |
| P11 | U6d2 | accepted: a shared window on a `let` root |
| P12 | typecheck-gap | a place read by value in a generic body without a `Copy` bound is not refused today |
| P13 | mir | epilogues run at close, last opened first: `compiler/tests/mir/golden/windows.saw` |
| P14 | U6d2 | a write through a window over an accessor-local |
| P15 | U6d2 | a read through a window over an accessor-local |
| P16 | U6d2 | lending the accessor's own parameter; refused today only by `type.mismatch` |
| P17 | U6d2 | accepted: a window body reaches enclosing locals by borrow |
| P18 | U6d2 | the window's root is not borrowed inside the extent |
| P21 | slice.not-yet | `syntax.stmt.optional-assign.borrow-plain` (then U6d2) |
| P19 | U6d2 | accepted: rendering a place is a borrow; the migrated file is refused first by `member.unknown`, a migration artifact |
| P20 | U6d2 | accepted: comparing a place is a borrow |
| P22 | typecheck | `transfer.implicit-copy` for a move-only `Box.value()` read; tests/corpus file refused by it |

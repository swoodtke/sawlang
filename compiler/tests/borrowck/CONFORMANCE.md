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
| `SL-462` | a typecheck rule not written yet, owned by SL-462: reference positions, mutability, moving out of a part or through a borrow |
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
| M01 | SL-462 | assignment to a `let` local |
| M02 | SL-462 | compound assignment to a `let` local |
| M03 | SL-462 | `&var` of a `let` |
| M04 | SL-462 | field write on a `let` struct |
| M05 | SL-462 | `&var self` call on a `let` receiver |
| M06 | SL-462 | `push` on a `let` Vector; the migrated file is refused first by `result.discarded`, a migration artifact |
| M07 | SL-462 | fixed-array element write on a `let` |
| M08 | SL-462 | a place window writing a `let` root |
| M09 | SL-462 | tuple element write on a `let` root |
| M10 | SL-462 | write through `&T` |
| M11 | SL-462 | whole-referent replacement through `&T` |
| M12 | SL-462 | `&var self` call through `&T` |
| M13 | SL-462 | `&self` method writing its field |
| M14 | SL-462 | `&self` method calling a `&var self` method |
| M15 | SL-462 | the same on a field; the migrated file is refused first by `result.discarded`, a migration artifact |
| M16 | SL-462 | `&var self.field` in a `&self` method |
| M17 | SL-462 | assignment to a `for` variable |
| M18 | SL-462 | assignment to an `if let` binding |
| M19 | SL-462 | assignment to a by-value parameter |
| M20 | SL-462 | write to a by-value capture |
| M21 | SL-462 | field write on a by-value capture |
| M22 | SL-462 | a `borrows` place write on a `let` root |
| M23 | SL-462 | write through a shared borrow's `&T` |
| M24 | SL-462 | `&self` accessor writing a field in its epilogue; the migrated file is refused first by `result.discarded`, a migration artifact |
| M25 | SL-462 | `m[k]! = v` on a `let` Map; the migrated file is refused first by `member.unknown`, a migration artifact |
| M26 | SL-462 | `&var self` call on a `let` of the Copy tier |
| M27 | slice.not-yet | a method call on `any Trait` (then SL-462: an `Atomic` field is interior mutability, accepted) |
| M28 | slice.not-yet | a `borrow` block over `SpinLock.lock`, which lends through a closure parameter (then SL-462: the indirection carve-out, accepted) |
| M29 | typecheck | accepted: a `&var` parameter's writes; typecheck golden `borrow_arguments.saw` |
| M30 | SL-462 | assignment to an immutable `static` |
| M31 | SL-462 | `&self` method writing through a window on inline storage; the migrated file is refused first by `subscript.role`, a migration artifact |
| M32 | SL-462 | accepted side: the indirection carve-out through a window |
| M33 | SL-462 | a place write in a `&self` accessor's prologue |
| M34 | SL-462 | accepted: a place write in the exclusive accessor's prologue |
| M35 | SL-462 | accepted: the same write declared `&var self` |
| M36 | SL-462 | a `[&self]` capture narrowing a `&var self` receiver |
| M37 | SL-462 | `let` inline-array immutability at every write shape |
| M38 | U6d2 | a compound assignment's right side borrowing the path it writes |
| M39 | slice.not-yet | `syntax.stmt.optional-assign.plain` (then SL-462) |
| M40 | slice.not-yet | `syntax.stmt.optional-assign.compound` (then SL-462) |
| M41 | SL-462 | accepted side of the indirection carve-out; the migrated file is refused first by `operator.undefined`, a migration artifact |
| M42 | SL-462 | `&self` method writing an inline `[T; N]` element |
| M43 | SL-462 | write to the payload of a `let` optional |
| M44 | SL-462 | `&var self` call through an inline array element of a `let` root |

## References are parameters only

| Row | Owner | Covered by, or why not |
|---|---|---|
| R01 | SL-462 | a free function returning `&Int` |
| R02 | SL-462 | a method returning `&Int` |
| R03 | SL-462 | a requirement returning `&Int` |
| R04 | SL-462 | an extern returning `&Int` |
| R05 | slice.not-yet | `syntax.expr.shorthand-param` (then SL-462) |
| R06 | SL-462 | `(Int, &Int)` result |
| R07 | SL-462 | `&Int?` result; refused today only by `type.mismatch` on the returned value |
| R08 | SL-462 | `Vector<&Int>` result |
| R09 | SL-462 | a struct field of reference type |
| R10 | SL-462 | a case payload of reference type; the migrated file is refused first by `result.discarded`, a migration artifact |
| R11 | SL-462 | `let r = &x` |
| R12 | SL-462 | `var r = &var x` |
| R13 | SL-462 | `Vector<&Int>` in a type position; the migrated file is refused first by `result.discarded`, a migration artifact |
| R14 | SL-462 | `idn<&Int>(&x)` |
| R15 | SL-462 | a closure inferring a reference result |
| R16 | SL-462 | an array literal of references |
| R17 | SL-462 | a tuple literal holding a reference |
| R18 | SL-462 | a Map with a reference value |
| R19 | SL-462 | a `static` of reference type; refused today only by `type.mismatch` |
| R20 | SL-462 | an alias laundering a reference into a field |
| R21 | SL-462 | an alias laundering a reference into a result |
| R22 | slice.not-yet | the `Thread.spawn` and `Task.spawn` forms (then typecheck `capture.escaping-borrow`) |
| R23 | typecheck | `capture.escaping-borrow`: `compiler/tests/typecheck/refuse/capture.escaping-borrow.saw` |
| R24 | slice.not-yet | `TaskGroup.spawn` (then typecheck) |
| R25 | slice.not-yet | `TaskGroup.spawn` (then typecheck and U6d2: the task borrows its root) |
| R26 | SL-462 | `Optional<&Int>` spelled out |
| R27 | SL-462 | a reference in a nested generic |
| R28 | SL-462 | accepted: the sanctioned `(&var n) as UnsafePointer<Int>` |
| R29 | typecheck-gap | `(&x) as Int` is not refused by `type.cast` today |
| R30 | typecheck | accepted: a non-escaping borrow capture; typecheck golden `captures.saw` |
| R31 | SL-462 | `&` as a binary operand |
| R32 | SL-462 | a reference in a `Box` |
| R33 | SL-462 | a reference result legal iff `borrows` |
| R34 | SL-462 | a field of a reference-returning function type |
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
| V03 | SL-462 | `move` out of a `&var` parameter: moving through a borrow; refused today only by `type.mismatch` |
| V04 | SL-462 | `move` out of a `&` parameter |
| V05 | SL-462 | `move h.v`, a partial move; MIR reads a trivially copyable part as `copy`, so only the source sees it |
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
| V31 | SL-462 | `move v[0]`, a partial move out of an element; the migrated file is refused first by `result.discarded`, a migration artifact |
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
| V49 | §3.7 | an escaping closure consuming its `move` capture frees it once: the environment's drop is placed, `compiler/tests/drops/conformance.tsv`; the body's move out through its `&` environment, which the environment's glue then frees again, is DF-255a's shape, still open in the MIR |
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
| V60 | SL-462 | a payload moved out of a match through a reference: moving through a borrow |
| V61 | SL-462 | `match self` in a reference receiver moving a payload |
| V62 | SL-462 | the same refusal at every tier and on a field scrutinee |
| V63 | §3.7 | an owned match still consumes, released once: `compiler/tests/drops/golden/dissolves.saw`, `compiler/tests/drops/conformance.tsv` |
| V64 | typecheck | `transfer.implicit-copy` at a forwarding cast; tests/corpus file refused by it |
| V65 | §3.8 | the Copy tier retains through a forwarding cast |
| V66 | typecheck | a forwarding alias projection; refused today by `type.mismatch` first |
| V67 | typecheck | accepted: building casts are untouched |
| V68 | SL-462 | a closure's reference parameter moved out: moving through a borrow |
| V69 | slice.not-yet | a `borrow` block over `Mutex.lock`, which lends through a closure parameter (then SL-462) |
| V70 | SL-462 | the borrowed closure binding refusal at every tier |
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

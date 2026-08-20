# Design 239 — Comparable/Equatable Take `other: &Self`

**Status: RATIFIED Aug 20 2026** (user ruling: `&Self`, over retain-at-lowering
and blanket refusal — the by-construction closure of DF-216b's class and C12).
**Queue slot: after design 236 LANDS** (two corpus migrations cannot overlap),
**BEFORE design 235** so the matrix ledgers pin the new signatures once.

## The decision

```saw
trait Equatable {
    func equals(&self, other: &Self) -> Bool
}
trait Comparable {
    func compare(&self, other: &Self) -> Ordering
}
```

The right operand is a shared reference at every tier. A hand-written body
can no longer `move other` — the spelling that over-released is a compile
error against `&Self` — and NoCopy comparison becomes legitimate instead of
refused. Explicit call sites spell the borrow (`a.equals(&b)`), the
call-site-`&` reader-visibility precedent; operator spellings (`a == b`,
`a < b`) are compiler-lowered and change nothing in source.

## Why (the short form — designs/216-vector-copy-bounds.md has the full matrix)

The operator lowering never builds a call node: `_check_binary_op` returns
`Bool` directly and `_emit_equals`/`_emit_compare` hand the callee two
already-loaded values, so `_check_value_transfer` never sees the right
operand. Seven source positions fall together (the `>`-family, `==`/`!=`,
match guards, `@synthesize` memberwise, enum payload, tuple, generic bodies),
and an eighth — an ImplicitCopy operand — over-releases on every comparison
because the tier carve-out assumed a retain the lowering does not perform
(200 comparisons SIGTRAP a heap String; row C12). The landed stopgap refuses
six positions; C07 (abstract `T` — the operand never reaches the gate) and
C12 are open, pinned XFAIL. `&Self` closes every row at once: no transfer
exists, so no checkpoint is needed and no retain is owed.

## Units

0. **Conformance rows first (obligation 3).** C12 restates the guarantee (a
   comparison destroys no operand) and flips to a passing row; C07 flips;
   C01-C06/C11 re-state under the new signatures — the stopgap refusals they
   pinned become POSITIVE rows (NoCopy comparison compiles and is sound).
   Every row's covering test updates in `examples/conformance/INDEX.md`.
1. **The signature change.** builtin.saw's two traits; conformance MATCHING
   requires `&Self` (a by-value `other` conformance is a declaration-site
   error with a fixit naming the new signature); synthesized bodies
   (memberwise, enum payload, tuple, optional/array recursions) read through
   the reference; `_emit_equals`/`_emit_compare` pass by reference. The
   stopgap (`_consuming_comparison_conformer`) is DELETED in the same
   landing — its refusal is unrepresentable now. `_check_binary_op` remains
   the funnel (obligation 1) and its docstring keeps naming its entry points.
2. **Corpus migration.** 216's consumer sweep (obligation 2) already ran:
   exactly five hand-written bodies — `String` (std/string.saw:324, 347) and
   four example types (`Doc`, `Reverse`, two `AK`s). Re-grep at dispatch for
   growth, migrate each signature, and sweep explicit `.equals(`/`.compare(`
   call sites to the `&` spelling. Suite + sos gated per commit.
3. **Docs** (design 125): LANGUAGE_SPEC.md trait signatures + worked
   examples, the saw-lang skill's cheat sheet, README's trait mention if the
   surface appears there. Load saw-docs before prose.

## Interactions

- **Design 218 unit 3** plans comparison/equality desugar to real AST calls,
  "coordinated with the `&Self` brief" — landing 239 first means the desugar
  emits borrowing calls from day one; no coordination debt remains.
- **216's `sort` half** unblocks (it was gated on this ruling).
- **Design 236's migration** touches the same example files; hence the queue
  ordering — 239 rebases on the post-236 corpus.
- `Hashable` is untouched (`hash(&self, into: &var Hasher)` — already
  by-reference).

## Gates

Compiler branch: full suite + sos_runner both arches per commit; terminal
full battery. XFAIL flips (C07/C12 pins) remove their markers in the landing
that fixes them.

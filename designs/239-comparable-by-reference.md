# Design 239 — Comparable/Equatable Take `other: &Self`

**Status: BUILT Aug 20 2026**, branch `design-239` (ratified the same day; user
ruling: `&Self`, over retain-at-lowering and blanket refusal — the
by-construction closure of DF-216b's class and C12). Landed in four commits:
1a the DF-239a fix, 1b the conformance rows, 1c+2 the signature change and the
corpus, 3 the docs. What the units found is recorded under *What the build
found* at the end.

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
1. **The signature change — FIRST fixing DF-239a**, the pre-check's finding
   (Aug 20): substituting `Self` inside a reference type drops the `&`, so a
   `&Self` requirement ICEs on the generic-bound call path and mistypes in
   default bodies — the exact paths generic `T: Comparable` code takes. Two
   XFAIL pins (`trait_self_ref_param_generic_call.saw`, `_default_body.saw`)
   flip with the fix; four passing controls fence the working subset (direct
   call, `Self?` nesting, by-value Self, erasure refusal). Then
   builtin.saw's two traits; conformance MATCHING
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

## What the build found

Three things the plan above did not anticipate. Each is recorded here rather
than in the tracker because each corrects a claim this brief made.

**1. DF-239a was misdiagnosed, and the real mechanism is bigger.** Substituting
`Self` inside a reference never dropped the `&`: both pinned faces work under
the spelling Saw actually has (`a.merge(&b)`, `self.merge(&other)`), and
`Bag_doubled` really does take `%Bag*`. What the pins hit was a plain MISSING
BORROW — Saw has no implicit re-borrow at any type, and the default-body face
reproduces identically for a `&Bag` parameter with no `Self` anywhere. The
mechanism is `_check_type_param_method_call`, the one call form in the language
with no argument-compatibility loop: it checks argument COUNT and defers deep
typing (a trait signature may name associated types), so everything it defers
reaches codegen, where a mismatch is an ICE rather than a diagnostic. Three
probed rows ICEd; the reference-spelling axis is fixed (a spelling question, so
decidable whatever `Self` denotes), the deep-typing residue is filed as
**DF-239b** with a pin. The erasure diagnostic's wart went with it.

**2. `String.equals`/`String.compare` do NOT migrate**, and the consumer sweep
could not have seen why. `String` conforms builtin — there is no `extension
String: Equatable` whose signature the matching rule judges — so those methods
are String's own public API, called as `s.equals("literal")` at 200 sites in the
tree, and a literal has no address for `&` to take (`&"literal"` is
``can only take reference to a variable, field, or array element``). They stay
by value, the declaration carries the reason, and neither path that needs the
requirement's shape comes through them.

**3. That left a hole the brief's units did not cover, and closing it fixed a
pre-existing ICE.** A call BY NAME through an `Equatable`/`Comparable` bound had
to keep working at `T = String`, where the mangled symbol now had the wrong ABI.
The requirements have no single callable body at all — a primitive has none, and
String's is its own API — so the call lowers with the OPERATOR's emitter
(`comparison_dispatch`), which is total over the conforming surface. That also
closes `same<Int>`, an `Undefined method: Int.equals` ICE that predates this
brief. Pinned by `examples/comparison_requirement_call_through_bound.saw` across
four instantiations (primitive, String, hand-written, derived).

Two conformance rows landed WITH the mechanism rather than ahead of it, because
they name diagnostics that did not exist to pin: **C13** (a by-value `other` is
a declaration-site error) and **C14** (`move other` is "cannot move out of
reference"). The conformance-matching rule they pin is general — a conformance's
parameters mirror the requirement's borrows, both directions, `&` against `&var`
included — which is the funnel version of what the brief asked for; parameter
types were previously not compared at all. `_resolve_trait_type` grew the
REFERENCE arm it needed to render `&Self` as `&Tag`.

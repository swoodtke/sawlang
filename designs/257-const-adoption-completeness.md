# Design 257 — Const-Adoption Ladder Completeness (the SL-2/SL-9 Fix)

**Status: AUTHORED Aug 31 2026** (lead; user-approved "fix those issues" same
day — rides design 256's worktree, runs second; the 0.3.0 bump is the
dispatch's final commit). Fix brief for DF-282a/DF-282b (the sawos SL-2/SL-9
findings, filed upstream with this brief). Agent DF range: continues
**DF-283a+**.

## The findings (sawos designs/todo.md SL-2 and SL-9, probed there against
pinned sawc; both refusals, no silent wrong answers)

- **DF-282a (SL-2) — a PLATFORM-WIDTH slot does not adopt a const
  expression.** `static M: UInt = (1 << BITS) - 1` over `static BITS: Int` is
  refused; DF-240a/DF-235's adoption reaches FIXED-WIDTH slots only, so a
  `UInt` static needs an `as UInt` a `UInt32` static does not (sawos
  kernel/abi HANDLE_INDEX_MASK carries the workaround with a note).
- **DF-282b (SL-9) — a LONE raw-backed enum case does not adopt where a
  COMBINATION of them does.** `enum E: UInt32 { case A = 1, case B = 2 }`:
  `static X: UInt32 = E.A | E.B` compiles and folds to 3 (DF-240a's flag-enum
  rule types the OPERATOR result as the backing), while `static Y: UInt32 =
  E.A` is ``static `Y` has type `UInt32` but its initializer has type `E` ``
  — a bare case keeps its enum type and the transfer is refused. "Adding a
  second flag REMOVES a cast" (sawos's line), which is backwards.

## The ruling encoded (user-approved: widen, do not document the asymmetry)

1. **A platform `Int`/`UInt` slot is an adoption target for a CONST
   EXPRESSION, exactly as a fixed-width slot is.** The fold stays in design
   185's signed platform-`Int` domain; the FOLDED value range-checks against
   the slot's type, so a negative fold into a `UInt` is the same clean "does
   not fit" a bare literal gives, and the documented `1 << 63`-into-`UInt64`
   gotcha is UNCHANGED (the fold is `Int.min` and does not fit — mask or
   write the literal, as the skill already teaches). ONLY const expressions
   adopt: a RUNTIME `Int`/`UInt` operand keeps design 205's written-conversion
   rule untouched (`let i: Int = u` on a runtime `u: UInt` stays refused).
2. **A lone raw-backed enum case is a constant of its backing in every const
   position a combination already reaches** — a `static` initializer, an
   annotated `let`, a field, an argument, a `return`, an arm, a
   `static_assert` operand — projecting to its declared value, then the
   ordinary folded-value range check against the slot (a `UInt32`-backed
   case into a `UInt8` slot is legal iff the value fits, same as the
   combination). Outside a const/adoption position nothing changes: an
   enum-typed VALUE still needs `as` (design 185's rule that keeps
   `from(raw:)` and exhaustiveness honest).

## Obligation 1 — the funnel

Adoption is a position-quantified rule with an existing ladder (the
DF-235a/b → DF-240a → DF-243a chain in the typechecker's expected-type
machinery). Both widenings land IN that mechanism — the same code that
answers "is this slot an adoption target" and "is this leaf a constant" —
never as per-position patches. The agent's first job is locating those two
predicates and confirming each change is one edit there; if the ladder turns
out to be scattered, THAT is a finding to report before proceeding
(obligation 1 says funnel it or matrix it, and the DF-243a position matrix is
the test-plan template either way).

## Obligation 2 — consumer sweep

Both changes are refusal→works; no program could rely on either refusal, and
the in-tree/sos `as UInt` / `as UInt32` workarounds remain legal (a redundant
cast is not an error). Corpus run is the sweep. The one boundary to prove
UNCHANGED by test: design 205's runtime-transfer refusals and the design-185
signed-domain gotchas.

## Test matrix (rows per cell, examples/)

| leaf \ slot | `UInt` static | `Int` static | fixed-width (regression) | annotated let / arg / return / arm |
|---|---|---|---|---|
| const arithmetic (`(1 << B) - 1`) | adopts (NEW) | adopts (NEW) | adopts (existing row) | adopts (NEW at platform width) |
| lone raw-backed case | adopts (NEW) | adopts (NEW) | adopts (NEW — SL-9's literal cell) | adopts (NEW) |
| case combination / arithmetic | adopts (regression) | adopts | adopts (regression) | adopts (regression) |
| negative fold | "does not fit" into `UInt` (NEW refusal row) | value | — | — |
| runtime operand | still design-205 refusal (regression) | same | same | same |
| `1 << 63` | still refused into `UInt64` (regression) | `Int.min` | — | — |

Undetermined cells probed, never guessed; every NEW cell gets a test, plus
one derived-statics chain (`static BITS: Int` → `static M: UInt`) mirroring
sawos's HANDLE_INDEX_MASK shape.

## Docs

Spec + skill: the DF-240a passages say "a fixed-width slot" — widen to name
platform-width slots; the FLAG ENUMS passage says a combination folds —
add the lone case. The skill's SL-2-shaped workaround advice (none exists
today — verify) and the `as UInt32` single-bit example, if present, update.
README untouched.

## Version (dispatch's final commit, after 256's units)

`SAWC_VERSION` 0.2.1 → **0.3.0** — both briefs make previously-refused
programs legal, a language-semantics widening. `bin/sawc --version` verified,
`toolchain` lane green. The sawos pin bump that consumes it is USER-OWNED
(SL-2/SL-9/SL-11/SL-12 all close there).

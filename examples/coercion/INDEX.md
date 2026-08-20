# The coercion ledger — design 235 unit 1

Two grids, on the `examples/conformance/` template (design 191): every cell
maps to a covering file — an existing `examples/` test cited rather than
duplicated, or a file in this directory — and a red cell (compiles when it
should refuse, refuses when it should work, ICEs, or mis-executes) is a DF
entry in `designs/todo.md` plus a cited XFAIL pin. See `designs/235-position-
matrices.md` for the brief and `designs/todo.md`'s DF-235a/b entries for the
mechanism this unit found.

Grid 1 lands in this commit; grid 2 ("Qualified-name-as-target") lands in
the next.

## Conventions

- **Cell format**: `file.saw` (a file in this directory), `existing:
  path/to/file.saw` (an `examples/` test elsewhere that already covers the
  cell — cited, not duplicated), `N/A — reason` (structurally inapplicable),
  or `OPEN — needs ruling` (the authority does not determine the expected
  outcome; never invented).
- **RED cells** are marked `RED (DF-xxx): file.saw` and take priority over
  any GREEN evidence for the same cell — a position that demonstrably works
  for an IN-RANGE value but does not range-check is still a red cell, with
  both files cited (the green one for "the value flows when it fits", the
  red pin for "the missing check").
- **Sources S4-S8 are a SWEEP, not a per-position re-test.** S4 (local
  read), S5 (field read), S6 (qualified/module static read), S7 (call
  result), and S8 (place read, `v[i]`) are all ALREADY concretely typed
  before they reach a position — none of them is literal-shaped, so none
  routes through `_apply_literal_expected_type` (design 87's adoption
  funnel) at all. Flowing an already-typed value into a slot of the same
  type is ordinary type equality, not a position-specific coercion
  question, so a gap there would be a general type-equality bug rather
  than an adoption-funnel one. `adopt_typed_source_sweep.saw` demonstrates
  all five at a representative span of positions (let, argument, return,
  struct-literal field, array element) once; every grid-1 row's S4-S8
  columns cite it rather than repeating the demonstration ~20 more times.

## Grid 1 — Adoption: target position × source template

Rule authorities: LANGUAGE_SPEC's literal-adoption section (design 87),
integer-agreement + value-branch transfers (design 195), optional/Result
payload adoption (DF-226d/e), enum raw values (DF-232c), assignment
adoption (DF-232a). Sources: **S1** bare literal, **S2** suffixed literal,
**S3** const expression (shift/arith, design 185), **S4** local read, **S5**
field read, **S6** qualified static read, **S7** call result, **S8** place
read (`v[i]`).

S2 and S4-S8 are never literal-shaped (S2 is already exact-typed, S4-S8 are
covered by the sweep above), so their cells across every row cite
`adopt_typed_source_sweep.saw` / the row's own S1 file (whichever already
demonstrates a same-type value flowing through) rather than growing eight
separate columns of near-identical citations. The table below carries S1
and S3, the two columns the adoption funnel actually governs; S2/S4-S8 are
covered once, here.

| Position | S1 bare literal | S3 const expression |
|---|---|---|
| annotated `let` | `adopt_let.saw` | RED (DF-235b): `adopt_let.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| assign — local | `existing: assignment_target_adopts_fixed_width.saw` | RED (DF-235b): `existing: assignment_target_adopts_fixed_width.saw` ("folded" row, in-range) + `const_expression_range_unchecked_narrow.saw` |
| assign — field | `existing: assignment_target_adopts_fixed_width.saw` | RED (DF-235b): `adopt_assign_field_const.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| assign — field-through-element | `existing: assignment_target_adopts_fixed_width.saw` | RED (DF-235b): `adopt_assign_field_const.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| module-qualified static assign | RED (DF-232d): see grid 2, `mod.STATIC` × assign | RED (DF-232d): see grid 2 — the assign target itself never reaches an RHS-source question |
| static initializer | `adopt_static_initializer.saw` | RED (DF-235b): `adopt_static_initializer.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| argument — positional | `adopt_argument_return.saw` | RED (DF-235b): `adopt_argument_return.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| argument — labeled | `adopt_argument_return.saw` | RED (DF-235b): `adopt_argument_return.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| `return` | `adopt_argument_return.saw` | RED (DF-235b): `adopt_argument_return.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| bare tail | `adopt_argument_return.saw` | RED (DF-235b): `adopt_argument_return.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| struct-literal field | `adopt_struct_literal_field.saw` | RED (DF-235b): `adopt_struct_literal_field.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| array element | `existing: literal_coercion_positions.saw` | RED (DF-235a/b): `array_literal_const_element_ice.saw` (mixed, ICE) + `const_expression_range_unchecked_wide.saw` (uniform, wrong width) |
| repeat literal `[v; N]` | `existing:` saw-lang skill / corpus `[0; N]` usage (see `LANGUAGE_SPEC.md`) | RED (DF-235b): `adopt_repeat_literal_const.saw` (in-range) + `const_expression_range_unchecked_wide.saw` |
| compound-assign RHS | `existing: literal_coercion_positions.saw` | RED (DF-235b): `compound_assign_const_expression_refused.saw` |
| value `if` arm | `existing: literal_coercion_positions.saw` | RED (DF-235b): `adopt_compound_and_arms_const.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| `match` arm | `existing: literal_coercion_positions.saw` | RED (DF-235b): `adopt_compound_and_arms_const.saw` (in-range) + `const_expression_range_unchecked_narrow.saw` |
| `??` operand | `adopt_coalesce_operand.saw` | RED (DF-235b): `adopt_coalesce_operand.saw` (in-range) + `const_expression_range_unchecked_wide.saw` |
| Optional payload slot | `existing: optional_slot_literal_adopts_payload_width.saw` | RED (DF-235b): `const_expression_range_unchecked_wide.saw` |
| Result payload slot — unique-adopt | `existing: result_slot_literal_adopts_payload_width.saw` | RED (DF-235a): `result_slot_const_expression_ice.saw` |
| Result payload slot — ambiguous refusal | `existing: result_slot_literal_ambiguous_payloads.saw` | `adopt_result_ambiguous_const.saw` (correctly refused — GREEN) |
| enum raw value | `existing:` corpus-wide (`enum145_*.saw`, `sos/`) | `existing: enum_raw_value_takes_const_expression.saw` |
| default parameter value | `existing: literal_coercion_positions.saw` | RED (DF-235b): `const_expression_range_unchecked_narrow.saw` |

Two supplementary rows, not part of the position × source cross but part of
the same funnel's coverage:

- Enum raw value against S6 (qualified static read) and S7 (call result) —
  neither is a constant expression, and BOTH are refused cleanly (no ICE):
  `adopt_enum_raw_value_non_constant_refused.saw`. S4/S5 (local/field read)
  are N/A — no enclosing function scope or receiver exists inside an enum
  declaration, so the position cannot be written. S8 (place read) is the
  same clean refusal as S6/S7 (not a constant expression either); not
  separately pinned since it is the identical diagnostic.
- S4-S8 sweep: `adopt_typed_source_sweep.saw` (see Conventions above).

**Cell counts, grid 1** (22 positions × 8 sources = 176 nominal cells): 23
green (own file or a same-shape existing-file cite: 21 on S1 + 2 on S3 —
Result's ambiguous refusal and enum raw value), 21 red (1 on S1 — the
module-qualified static assign row, which points at grid 2's DF-232d cells
rather than duplicating them — + 20 on S3, all DF-235a/b), 132 cited (S2's
22 cells plus S4-S8's 110 cells, all pointing at
`adopt_typed_source_sweep.saw` or the row's own S1 file per the Conventions
note above), 0 OPEN. Two SUPPLEMENTARY cells outside the 176 (enum raw
value × S6/S7) are green (correctly refused, no ICE); two more (enum raw
value × S4/S5) are N/A — no enclosing function scope or receiver exists
inside an enum declaration, so those sources cannot be written at all.
21 red cells resolve to 9 distinct XFAIL pins (DF-235b's silent-narrow and
silent-wide families each cover several positions from one canonical
repro, per the file-granularity XFAIL rule and "cite it, don't duplicate").

## Findings filed by this ledger (grid 1)

- **DF-235a** — a constant-expression element/payload ICEs at codegen (a
  plain array literal, mixed with an adopted sibling; a `Result` payload
  slot). Pins: `array_literal_const_element_ice.saw`,
  `result_slot_const_expression_ice.saw`.
- **DF-235b** — a constant-expression source is never range-checked at
  most fixed-width positions (silent narrow truncation, silent wide
  storage, or — one position — a spurious refusal). Pins:
  `const_expression_range_unchecked_narrow.saw`,
  `const_expression_range_unchecked_wide.saw`,
  `compound_assign_const_expression_refused.saw`.

Grid 1 has no OPEN cells — every cell it names was determined by direct
compile/run evidence.

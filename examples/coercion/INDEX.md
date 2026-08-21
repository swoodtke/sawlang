# The coercion ledger — design 235 unit 1

Two grids, on the `examples/conformance/` template (design 191): every cell
maps to a covering file — an existing `examples/` test cited rather than
duplicated, or a file in this directory — and a red cell (compiles when it
should refuse, refuses when it should work, ICEs, or mis-executes) is a DF
entry in `designs/todo.md` plus a cited XFAIL pin. See `designs/235-position-
matrices.md` for the brief and `designs/todo.md`'s DF-235a/b entries for the
mechanism this unit found.

## Conventions

- **Cell format**: `file.saw` (a file in this directory), `existing:
  path/to/file.saw` (an `examples/` test elsewhere that already covers the
  cell — cited, not duplicated), `N/A — reason` (structurally inapplicable),
  or `OPEN — needs ruling` (the authority does not determine the expected
  outcome; never invented).
- **A cell whose RED was FIXED keeps both files** — the in-range one that
  showed the value flowing and the one that pins the check — with the DF
  recorded under "Findings filed by this ledger" rather than in the cell, so
  the grid reads as coverage and the history stays one paragraph away.
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
- **A `mod.STATIC` access path needs a fixture module.** Grid 2's fourth
  row imports `examples/coercion/modules/qualname_static_dep.saw` (a plain
  relative import — `modules/` is excluded from test discovery, same
  convention every other cross-module `examples/` test already uses).

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
| annotated `let` | `adopt_let.saw` | `adopt_let.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| assign — local | `existing: assignment_target_adopts_fixed_width.saw` | `existing: assignment_target_adopts_fixed_width.saw` ("folded" row, in-range) + `const_expression_range_checked_narrow.saw` |
| assign — field | `existing: assignment_target_adopts_fixed_width.saw` | `adopt_assign_field_const.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| assign — field-through-element | `existing: assignment_target_adopts_fixed_width.saw` | `adopt_assign_field_const.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| module-qualified static assign | RED (DF-232d): see grid 2, `mod.STATIC` × assign | RED (DF-232d): see grid 2 — the assign target itself never reaches an RHS-source question |
| static initializer | `adopt_static_initializer.saw` | `adopt_static_initializer.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| argument — positional | `adopt_argument_return.saw` | `adopt_argument_return.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| argument — labeled | `adopt_argument_return.saw` | `adopt_argument_return.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| `return` | `adopt_argument_return.saw` | `adopt_argument_return.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| bare tail | `adopt_argument_return.saw` | `adopt_argument_return.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| struct-literal field | `adopt_struct_literal_field.saw` | `adopt_struct_literal_field.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| array element | `existing: literal_coercion_positions.saw` | `array_literal_const_element_mixed.saw` (mixed widths) + `array_literal_const_element_range_check.saw` (uniform, range) |
| repeat literal `[v; N]` | `existing:` saw-lang skill / corpus `[0; N]` usage (see `LANGUAGE_SPEC.md`) | `adopt_repeat_literal_const.saw` (in-range) + `const_expression_range_checked_wide.saw` |
| compound-assign RHS | `existing: literal_coercion_positions.saw` | `compound_assign_const_expression.saw` |
| value `if` arm | `existing: literal_coercion_positions.saw` | `adopt_compound_and_arms_const.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| `match` arm | `existing: literal_coercion_positions.saw` | `adopt_compound_and_arms_const.saw` (in-range) + `const_expression_range_checked_narrow.saw` |
| `??` operand | `adopt_coalesce_operand.saw` | `adopt_coalesce_operand.saw` (in-range) + `const_expression_range_checked_wide.saw` |
| Optional payload slot | `existing: optional_slot_literal_adopts_payload_width.saw` | `const_expression_range_checked_wide.saw` |
| Result payload slot — unique-adopt | `existing: result_slot_literal_adopts_payload_width.saw` | `result_slot_const_expression.saw` |
| Result payload slot — ambiguous refusal | `existing: result_slot_literal_ambiguous_payloads.saw` | `adopt_result_ambiguous_const.saw` (correctly refused — GREEN) |
| enum raw value | `existing:` corpus-wide (`enum145_*.saw`, `sos/`) | `existing: enum_raw_value_takes_const_expression.saw` |
| default parameter value | `existing: literal_coercion_positions.saw` | `const_expression_range_checked_narrow.saw` |

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
- The UNARY shapes of an S3 source, which the funnel folds through the same
  case: a negated const expression (`-(1 << 7)` at `Int8` — the value fits only
  once negated, so the whole expression is folded rather than its operand) and a
  `~` mask, both in `const_expression_unary_adopts.saw`. Design 185's fold
  domain is the SIGNED platform `Int`, so an unmasked `1 << 63` at a `UInt64`
  slot is a refusal, not a bit-pattern reinterpretation:
  `const_expression_signed_domain_error.saw`.
- **RED (DF-240a)**: an S3 source whose LEAF is a module `static`
  (`1 << PAGE_SHIFT`) is the one const-expression shape that still does not
  adopt, so it is not range-checked either — pin
  `const_expression_named_static_operand.saw` (XFAIL). It wants a ruling, not a
  patch: supplying the name's value at this point also supplies a raw-backed
  enum case's, and design 185 unit 4 says a flag-enum read is a constant only IN
  a const position.

**Cell counts, grid 1** (22 positions × 8 sources = 176 nominal cells): 43
green (own file or a same-shape existing-file cite: 21 on S1 + 22 on S3 —
every position the adoption funnel serves, since design 240 gave it the
const-expression case), 1 red (on S1 — the module-qualified static assign
row, which points at grid 2's DF-232d cells rather than duplicating them),
132 cited (S2's 22 cells plus S4-S8's 110 cells, all pointing at
`adopt_typed_source_sweep.saw` or the row's own S1 file per the Conventions
note above), 0 OPEN. Two SUPPLEMENTARY cells outside the 176 (enum raw
value × S6/S7) are green (correctly refused, no ICE); two more (enum raw
value × S4/S5) are N/A — no enclosing function scope or receiver exists
inside an enum declaration, so those sources cannot be written at all.
The 20 S3 cells this ledger filed RED went green together (design 240 items
1-2): they were one funnel gap, and one arm closed all of them, so the S3
column cites two canonical repros — the narrow and wide families — plus the
per-position in-range file, exactly as the S1 column always did.

## Grid 2 — Qualified-name-as-target: access path × operation

Rule authority: DF-232d's mechanism (member-access assignment routing) plus
its Aug 20 correction (design 235's own sweep — see `designs/todo.md`).
Operations: read, assign, compound-assign, `&var` argument, place window
(an accessor-mediated exclusive/shared window — design 141/146; NOT plain
fixed-array indexing, which is exempt from the place mechanism by the
saw-lang skill's own note).

| Access path | read | assign | compound-assign | `&var` argument | place window |
|---|---|---|---|---|---|
| local | `qualname_local.saw` | `qualname_local.saw` | `qualname_local.saw` | `qualname_local.saw` | `qualname_local.saw` |
| `obj.field` | `qualname_obj_field.saw` | `qualname_obj_field.saw` | `qualname_obj_field.saw` | `qualname_obj_field.saw` | `qualname_obj_field.saw` |
| `arr[i].field` | `qualname_arr_elem_field.saw` | `qualname_arr_elem_field.saw` | `qualname_arr_elem_field.saw` | `qualname_arr_elem_field.saw` | `qualname_arr_elem_field.saw` |
| `mod.STATIC` | `qualname_mod_static.saw` | RED (DF-232d): `qualname_mod_static_assign_error.saw` | RED (DF-232d): `qualname_mod_static_compound_assign_ice.saw` | RED (DF-232d): `qualname_mod_static_refarg_ice.saw` | RED (DF-232d): `qualname_mod_static_write_ice.saw` |

**Cell counts, grid 2**: 16 green, 4 red (all DF-232d, all pinned above), 0
N/A, 0 OPEN. The `mod.STATIC` row is the one DF-232d's Aug 20 correction
widened: the finding's original matrix marked three of these four
operations working; design 235's direct compile evidence found only READ
actually is, on today's tree, via a plain relative import AND via
`--module-path` alike.

**Why `mod.STATIC`'s place-window cell has no Vector/Map fixture.** A
`borrows`-accessor-backed container (`Vector`, `Map`) cannot BE a module
static — only trivially-destructible types can (`unsafe static var`'s own
rule; `Vector`/`Map` own a `Deinit`), confirmed by direct compile
(`static CELLS: Vector<Int>` is refused: "owns a resource (Deinit);
statics are immortal and never run deinit"). So the row's place-window
cell is tested through a fixed-array ELEMENT WRITE instead
(`mod.ARR[i] = v`) — the same shape DF-232d's own original matrix used for
this row, kept for continuity even though a plain fixed-array index is,
strictly, outside the `borrows`-window mechanism the other three access
paths exercise through a `Vector`.

## Findings filed by this ledger

- **DF-235a** (FIXED, design 240 items 1-2) — a constant-expression
  element/payload ICEd at codegen (a plain array literal, mixed with an
  adopted sibling; a `Result` payload slot). Regression tests:
  `array_literal_const_element_mixed.saw`,
  `array_literal_const_element_range_check.saw`,
  `result_slot_const_expression.saw`.
- **DF-235b** (FIXED, design 240 items 1-2) — a constant-expression source was
  never range-checked at most fixed-width positions (silent narrow truncation,
  silent wide storage, or — one position — a spurious refusal). Regression
  tests: `const_expression_range_checked_narrow.saw`,
  `const_expression_range_checked_wide.saw`,
  `compound_assign_const_expression.saw`, plus
  `const_expression_unary_adopts.saw` and
  `const_expression_signed_domain_error.saw` for the unary shapes and the
  fold domain's boundary.
- **DF-232d correction** — the finding's "writes"/"refs" rows for
  `mod.STATIC` do not hold; every write/reference shape through a
  qualifier ICEs at codegen, not just the originally-filed plain
  assignment (which refuses cleanly at typecheck). Pins:
  `qualname_mod_static_assign_error.saw` (original),
  `qualname_mod_static_compound_assign_ice.saw`,
  `qualname_mod_static_refarg_ice.saw`, `qualname_mod_static_write_ice.saw`.

- **DF-240a** (OPEN, filed by design 240's own sweep) — a const expression whose
  leaf is a module `static` does not adopt, so it is not range-checked. Pin:
  `const_expression_named_static_operand.saw`.

No OPEN cells in either grid — every cell this brief's grids name was
determined by direct compile/run evidence.

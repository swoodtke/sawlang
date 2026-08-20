# The module ledger — design 235 unit 2

Three grids, on the `examples/conformance/` template (design 191). Named
`module_matrix/`, not `modules/`, DELIBERATELY: `test_runner.py`'s
`discover_tests` hard-codes `skip_dirs = {'modules'}` and excludes ANY path
component named `modules` at any depth, corpus-wide — a `examples/modules/`
ledger's own test files would never run, silently. `examples/modules/`
already exists as the corpus-wide fixture directory every cross-module test
reaches with a plain relative import (`import modules.X`); this ledger's own
fixtures live in `module_matrix/modules/` instead (excluded the same way,
scoped to this ledger) so its *test* files can sit in `module_matrix/`
itself and actually run. See `designs/235-position-matrices.md` for the
brief.

Grid 1 lands in this commit; grids 2 and 3 land in the next two.

## Conventions

Same as `examples/coercion/INDEX.md` (design 235 unit 1): `file.saw` (a file
here), `existing: path.saw` (cited, not duplicated), `N/A — reason`, `OPEN —
needs ruling`. A RED cell is `RED (DF-xxx): file.saw`.

## Grid 1 — Import forms × name positions

Import forms: qualified whole-module, glob (`*`), selective (`{A, B}`),
`as`-renamed. Positions: (a) annotation, (b) expression, (c) extension
receiver, (d) generic bound, (e) existential (`&any` / `Box<any>`), (f)
match pattern, (g) interpolation, (h) default parameter value.

A pre-write survey (grep across ~2000 `examples/*.saw` files) found strong
existing coverage for the QUALIFIED form's (a)/(b)/(d)/(e)/(g) positions
(`import150_std_qualified_positions.saw`, `l18_module_qualified_annotation.saw`,
`qualified_type_declaration_slots.saw`, `import150_qualified_trait.saw`,
`l6_module_qualified_signedness.saw`), weaker/incidental coverage for glob
and selective, and ZERO hits anywhere in the corpus for (c), (f), and (h) —
in ANY form. Rather than write scattered single-cell files to patch three
holes across four forms, this ledger writes ONE comprehensive file PER
FORM (a "row-family" file, matching the brief's own allowance) that
exercises all eight positions freshly against one shared fixture
(`modules/importforms/lib.saw`) — which also means every cell below is
backed by a compile this session ran, not by re-reading an older file's
comment.

**Two positions turned out to be grammar-level N/A for two of the four
forms**, confirmed by direct compile, not assumed: an extension receiver
(`extension mod.Type {}`) and a match pattern (`case mod.Enum.Case ->`)
both require a BARE name at the parser level —
`extension lib.Widget {}` is `Parse error: Expected LBRACE, got DOT` and
`case lib.Shape.Circle ->` is `Parse error: Expected '->' after match
pattern`. Neither the qualified form nor the `as`-renamed form ever
produces a bare name, so (c) and (f) are structurally unreachable for
those two forms in every case, not a gap this brief's probing could close
by trying harder.

| Form | (a) annotation | (b) expression | (c) ext. receiver | (d) generic bound | (e) existential | (f) match pattern | (g) interpolation | (h) default param |
|---|---|---|---|---|---|---|---|---|
| qualified | `import_form_qualified_positions.saw` | same | N/A — grammar requires a bare receiver | same | same | N/A — grammar requires a bare pattern | same | same |
| glob | `import_form_glob_positions.saw` | same | same | same | same | same | same | same |
| selective | `import_form_selective_positions.saw` | same | same | same | same | same | same | same |
| `as`-renamed | `import_form_renamed_positions.saw` | same | N/A — same reason as qualified | same | same | N/A — same reason as qualified | same | same |

`import_form_selective_positions.saw` additionally confirms selective's own
second promise (design 150 pin 2): the qualifier still reaches a name the
`{...}` list did NOT select (`lib.other_widget(9)`, never imported bare in
that file).

**Cell counts, grid 1** (4 forms × 8 positions = 32 nominal cells): 28
green (7 per form × 4 — every position the grammar admits), 4 N/A (the
extension-receiver and match-pattern columns × the qualified and
`as`-renamed forms — grammar-level, not a compiler gap), 0 red, 0 OPEN.

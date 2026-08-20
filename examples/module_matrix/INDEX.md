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

Grids 1 and 2 have landed; grid 3 lands next.

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

## Grid 2 — Visibility

Tier (`public` / `public(package)` / private) × relation (same module /
same package / cross package) × member kind (struct field, extension
method, static, type, enum case) × access form (qualified path, bare via
selective, bare via `*`). Rule authority: design 80 (member visibility),
design 229 (import privacy + re-export), the DF-232j/f/n family (the
package tier's own history — see `designs/todo.md`).

Full cross-product is 135 nominal cells; as `examples/conformance/`'s own
B15-B17 rows already do for this exact tier, this ledger consolidates by
TIER × RELATION (9 core cells) and notes kind/access-form coverage WITHIN
each — the kind axis is confirmed general rather than re-tested per kind:
`module_path_reexport_kinds_no_widen_error.saw` tests a `static` AND a
`struct` under one refusal, `df229c_package_selection_binds.saw` binds a
struct, an enum(+case), a function, a static AND a type-alias bare in one
file, so the mechanism is not re-derived per kind five more times.

| Tier | Relation | Access forms covered | Cell |
|---|---|---|---|
| private | same module | n/a (unrestricted) | `existing: vis80_same_module_ok.saw` (field, method, static) |
| private | cross module (incl. package) | qualified | `existing: vis80_field_read_error.saw` (field); `visibility_private_method_static_cross_module_error.saw` (method + static, the two kinds the survey found not separately isolated) |
| `public` | cross module | qualified | `existing: vis80_public_members_ok.saw` (field, static, method, init, trait-conformance method) |
| `public` | cross module, re-export chain | qualifier chain, value position | `existing: export229_whole_chain_call.saw` (conformance row B17) |
| `public(package)` | same package (sibling) | qualified, selective, glob | `existing: module_path_package_visibility.saw`, `df229c_package_selection_binds.saw`, `module_path_glob_facade_sibling.saw` (conformance row B16) |
| `public(package)` | cross package (`--module-path`-mapped) | qualified, selective, one-hop facade, two-hop facade, glob facade, whole-module facade | `existing: module_path_package_visibility_error.saw`, `module_path_qualified_no_widen_error.saw`, `module_path_reexport_no_widen_error.saw`, `module_path_reexport_twohop_no_widen_error.saw`, `module_path_reexport_kinds_no_widen_error.saw`, `module_path_glob_facade_no_widen_error.saw`, `module_path_whole_facade_no_widen_error.saw`, `module_path_facade_selection_error.saw` (conformance row B15 — every spelling refuses, no widening) |
| `public(package)` | reached via a RELATIVE-path import (no `--module-path`, no package-root identity on either side) | qualified | RED (DF-232n): `visibility_package_relative_import_fails_open.saw` |

**The DF-232n row is the one genuine red cell this grid adds.** Every
`public(package)` row above that refuses correctly does so because BOTH
sides carry a `--module-path`-mapped package-root identity; the moment
neither side does (a plain `import modules.X`, which is how the vast
majority of this repo's own cross-module tests — and every fixture this
unit's OTHER two grids use — reach each other), `check_visibility`'s
`if not package_root: return True` fail-open default answers ALLOW instead
of refusing. Already filed (`libs/toml/tests/*.saw` proved it live against
`TomlDoc`/`semver.Version`); this ledger's file is the minimal two-file
pin.

**Supplementary, not part of the brief's named 3-tier axis**:
`public(parent)` (design 80's fourth tier) has its own strong existing
coverage — `visibility_parent.saw` (same-file positive), `visibility_parent_access_error.saw`
(non-parent module, negative), `df229c_parent_selection_error.saw` (same
PACKAGE but not parent — the control that proves the tier is distinct from
`public(package)`). Not re-tested here since the brief's grid names three
tiers, not four, but flagged so the coverage is not lost from view.

**Enum-case-level visibility is N/A by design, not undetermined**: design
80's own brief (`designs/80-member-visibility.md`) rules per-case
visibility out of scope — "Enum variants: follow the enum's visibility as
today" — so there is no independent case-level tier to probe; a case's
reachability is exactly its enum's.

**A struct-level `static`'s visibility at `public(package)`/`public(parent)`
specifically** (as opposed to a MODULE-level `static`, which IS covered at
`public(package)` above) is not independently tested. Reasoned N/A, not a
gap: the tier is stamped on the symbol by the SAME visibility mechanism
regardless of whether the symbol is a module-level or struct-level member
(`module_path_reexport_kinds_no_widen_error.saw` already establishes the
kind-generality directly), so a struct-scoped static is not expected to
exercise a different code path than the module-level static or the
struct's own instance method already covered.

**Cell counts, grid 2** (9 core tier×relation cells, the grid's own
consolidation unit): 8 green (all cited existing, 1 new
private/cross-module supplementary file), 1 red (DF-232n, new pin), 0 OPEN.
Two supplementary notes (enum-case tier, struct-static-at-package/parent
tier) are N/A with reasons recorded in place, per the brief's own
discipline.

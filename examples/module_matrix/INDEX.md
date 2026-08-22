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

All three grids have landed.

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
| `public(package)` | reached via a RELATIVE-path import, inside a MANIFEST-LESS tree | qualified | `visibility_package_adhoc_tree_is_one_package.saw` — GREEN since DF-232n closed (Aug 20), and green by ALLOWING: the entry file's tree is the package |
| `public(package)` | reached via a RELATIVE-path import, ACROSS a `Saw.toml` root | qualified, selective | `existing: package_tier_foreign_relative_reach_error.saw`, `…_selection_error.saw` (the refusal); `existing: module_tests/pkg232n/tests/package_tier_same_package_reach.saw` (the same-manifest accept side) |

**A SECOND QUESTION joined this grid on Aug 21** ("a public API needs public
types"). Every row above asks whether an ACCESS may reach a name; the ruling
adds whether a DECLARATION may name one — a declaration may not name a type
less visible than its own effective reach, refused where it is written. It is
the same tier relation (`Namespace.visibility_relation_allows`) asked from the
declaration side, so it belongs here rather than in a grid of its own; the
position axis (which declared slots name a type) is the funnel's own matrix,
`SignatureVisibilityMixin.SIGNATURE_VISIBILITY_POSITIONS` in
`sawc/typechecker/sigvis.py`.

| Tier of the declaration | Tier of the type it names | Cell |
|---|---|---|
| `public` | private, same module | `existing: conformance/B20_private_type_in_public_signature_error.saw`; all sixteen declared positions at `existing: private_in_public_positions_error.saw` + `private_in_public_extension_surface_error.saw` |
| `public` | private, across a module boundary (value path AND design-141 place path) | `existing: conformance/B22_private_type_escapes_module_error.saw` |
| `public` | `public(package)` | `existing: private_in_public_positions_error.saw` (`pkg`) |
| `public(package)` | `public(package)`, same package | `existing: module_tests/pkg232n/tests/package_tier_same_package_reach.saw` (`make_box`, narrowed to the tier of what it returns by this ruling) |
| private | anything | `existing: conformance/B21_private_declaration_names_anything.saw` |
| `public` member | of a NON-public type (design 80's "legal but inert" cap) | `existing: conformance/B21_private_declaration_names_anything.saw` |

**Cell counts, the declaration-side rows**: 6 green, 0 red, 0 N/A, 0 OPEN.

**The DF-232n row WAS this grid's one genuine red cell, and it went green on
Aug 20 — by allowing, not by refusing.** When the grid was written, every
`public(package)` row that refused correctly did so because BOTH sides carried
a `--module-path`-mapped package-root identity; the moment neither did (a plain
`import modules.X`, which is how the vast majority of this repo's own
cross-module tests reach each other), `check_visibility`'s `if not
package_root: return True` fail-open default answered ALLOW. DF-232n's fix gave
every module a PACKAGE IDENTITY instead of flipping that default, and the
identity a manifest-less file gets is the entry file's directory TREE — so two
relative siblings in one tree are one package and the reach is right. The row
above says so now, and the arm that does refuse (across a `Saw.toml` root) got
a row of its own.

**A NOTE ON HOW LONG THAT TOOK TO NOTICE (DF-248c).** The pin kept asserting
the old intended behavior — `EXPECT: error`, citing DF-232n — for two days
after DF-232n closed, and no gate said a word: a stale XFAIL breaks the build
only in the XPASS direction, and this one still FAILED, because it asked for a
refusal the language deliberately does not give. Nothing cross-checks an
`// XFAIL: DF-xxx` citation against whether that DF is still open.

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

**Cell counts, grid 2** (10 core tier×relation cells — the relative-path row
split in two when DF-232n closed, since the manifest-less tree and the
across-a-`Saw.toml` reach take opposite answers): 10 green, 0 red, 0 OPEN.
Two supplementary notes (enum-case tier, struct-static-at-package/parent
tier) are N/A with reasons recorded in place, per the brief's own
discipline.

## Grid 3 — Graph shapes

2-cycle, 3-cycle, self-import, diamond (legal, must stay green), re-export
chain (`public import` facade), `@export` symbol reachability through a
facade.

| Shape | Cell |
|---|---|
| 2-cycle (`a` <-> `b`) | `graph_2cycle_error.saw` — the loop is NAMED (`import cycle: a -> b -> a`), anchored on the first participating import line, with each edge's line in the hint; the innocent third module the error used to land on is asserted away by `EXPECT-ERROR-ABSENT` |
| 3-cycle (`a` -> `b` -> `c` -> `a`) | `graph_3cycle_error.saw` — same diagnostic, confirmed rather than assumed at a longer cycle length |
| self-import (`a` imports `a`) | `graph_self_import.saw` — STILL legal: a degenerate length-one loop asks for names the module already has, so a module is simply never its own dependency (the edge is dropped where the graph is built) |
| diamond (`main` -> `b`,`c`; `b`,`c` -> `d`) | `graph_diamond.saw` |
| re-export chain (`public import` facade) | `existing: export229_whole_chain_call.saw` (also cited at grid 2's `public(package)` cross-module row for its visibility angle; this row is its GRAPH-SHAPE angle — a two-hop facade chain reaching a value) |
| `@export` symbol reachability through a facade | `graph_export_through_facade.saw` — an `@export`ed C-ABI symbol is a link-time fact independent of Saw-level import visibility, confirmed to survive being reached ONLY through a `public import` facade, both via the Saw-level call and the raw `extern "C"` symbol |

**Cell counts, grid 3**: 6 green (4 own file + 2 cited), 0 red, 0 N/A, 0 OPEN.
The two cycle rows went green with design 240 item 7, which replaced the
arbitrary check order's silence with the diagnostic.

## Findings filed by this unit

- **DF-232e** (filed by design 232's kcore-split probe; FIXED, design 240
  item 7) — import cycles were undiagnosed; this unit's pins were its first
  `examples/` fixtures (the finding was previously pinned by nothing — no
  harness shape existed for a two-module cycle before this ledger), and they
  are now its regression tests. Confirmed the same mechanism at 3-cycle
  length, not assumed.
- **DF-232n** (already filed, the re-narrowing audit; FIXED Aug 20, branch
  `df-batch-232n`) — `public(package)` fell open across a relative-path
  import; this unit's file was its first minimal two-file pin (the finding's
  own evidence was `libs/toml/tests/`, a larger fixture). The pin is now the
  ACCEPT row of the ruling that closed it, under the behavior's own name.
- **DF-248c** (filed Aug 22, auditing this file) — an XFAIL whose cited DF has
  CLOSED is invisible to every gate, so a pin can keep asserting a superseded
  intended behavior indefinitely. Found here, and here only: the corpus's
  other eight citations were all still open when swept.

No new DF numbers were filed by unit 2 itself — both red cells were
already-filed, not-yet-fixed findings this unit's grids happened to reach and
pin for the first time. DF-232e's two cells are green as of Aug 21, DF-232n's
as of Aug 20.

No OPEN cells in any of the three grids.

# Design 235 — The Position-Matrix Ledgers (coercion + modules)

**Status: RATIFIED Aug 17 2026.** **Queued: dispatches after the three
Aug-17 in-flight branches integrate** (kcore split, literal/const family,
small-fix batch) — they carry the seed rows and the DF-229c/232a/226 fixes
whose cells must land green, and this brief must enumerate against the
post-fix tree. Runs BEFORE design 234's migration units, which churn exactly
these positions and want a green matrix under them.

**Dispatch note (user ruling, Aug 17): a Sonnet-class agent builds this** —
the construction is mechanical once the grids and their rule authorities are
fixed, which this brief does. The intelligence budget was spent here; the
agent transcribes, compiles, verifies, and files.

## Why

The Aug-17 finding cluster (DF-232a/b/c/d, DF-226d/e/f, DF-229c) was found
by real work tripping over cells one at a time — none had a pre-existing
pin, because the XFAIL policy is reactive by design (a pin records a FILED
finding). Obligation 1 already demands a matrix per position-quantified
rule; this brief promotes that from a per-brief duty to a STANDING CORPUS
ARTIFACT, on the `examples/conformance/` (design 191) template: an
enumerated grid, an auditable INDEX, and — the point — the xfail set for
these families becomes the RED-CELL SET of an enumeration, not the trail of
what we happened to step on.

## The ledgers

Same discipline as conformance/ in both: `INDEX.md` maps EVERY cell to its
covering file — including cells an existing `examples/` test already covers
(cite it, do not duplicate) and N/A cells with the reason written in place.
A red cell (compiles when it should refuse, refuses when it should work,
ICEs, or mis-executes) becomes a DF entry in designs/todo.md (minimal repro,
observed vs expected, the authority section cited) plus a cited XFAIL pin
file named for the BEHAVIOR it pins. Green rows group into one file per
row-family; red cells split out (XFAIL is file-granularity).

### Unit 1 — `examples/coercion/`

Two grids. Rule authorities: LANGUAGE_SPEC's literal-adoption section
(design 87), integer-agreement + value-branch transfers (design 195),
optional/Result payload adoption (DF-226d/e as fixed), enum raw values
(DF-232c as fixed), assignment adoption (DF-232a as fixed).

1. **Adoption**: target position × source template.
   Positions: annotated `let`; plain assignment to a local, a field, a
   field-through-element; module-qualified static assignment; static
   initializer; argument (positional and labeled); return and bare tail;
   struct-literal field; array element; repeat literal `[v; N]`; compound-
   assign RHS; value if/match arm; `??` operand; Optional payload slot;
   Result payload slot (unique-adopt and the ambiguous refusal); enum raw
   value; default parameter value.
   Sources: bare literal; suffixed literal; const expression (shift, arith);
   local read; field read; qualified static read; call result; place read
   (`v[i]`).
2. **Qualified-name-as-target**: access path (`local` / `obj.field` /
   `arr[i].field` / `mod.STATIC`) × operation (read, assign,
   compound-assign, `&var` argument, place window). DF-232d is a known red
   cell (`mod.STATIC = v` → `undefined variable mod`) — pin it if its fix
   has not landed by dispatch time; cite the fix's test if it has.

Seeds: the DF-232a pin's ADOPTS/ICEs rows, the DF-226d/e pins, the
DF-232c pin — inherit and extend, do not rewrite.

### Unit 2 — `examples/modules/`

Three grids. Rule authorities: member visibility (design 80), file=module
(design 82/204), extensions vs conformances scoping (design 142), type
identity (design 144), import forms (design 150), the kcore-split probe
findings (DF-232d/e/f context).

1. **Import forms × name positions**: qualified / `*` / selective
   `{A, B as C}` / `as`-renamed × annotation, expression, extension
   receiver, generic bound, `&any mod.Trait`, match pattern, interpolation,
   default value. Design 150's rule text quantifies over exactly this; the
   grid makes its coverage auditable.
2. **Visibility**: tier (`public` / `public(package)` / private) × relation
   (same module / same package / cross package) × member kind (struct
   field, extension method, static, type, enum case) × access form
   (qualified path, bare via selective, bare via `*`). DF-229c's fixed cell
   lands green with its test cited; DF-232f (no package-internal tier for
   `--module-path` packages) is a known missing-COLUMN finding — its rows
   record current behavior with the DF cited, not an invented tier.
3. **Graph shapes**: 2-cycle, 3-cycle, self-import, diamond (legal — must
   stay green), re-export chain (`public import` facade), `@export` symbol
   reachability through a facade. DF-232e (cycles undiagnosed —
   `_topological_sort` returns arbitrary order and the error blames an
   innocent module) is the known red family. The kcore agent's ten unit-0
   probe programs are the seed rows — harvest them from the split branch.

Note `// COMPILE-FLAGS:` with `{TESTDIR}` + `--module-path` is the existing
mechanism for multi-module tests; follow the current examples that use it.

## The no-guessing rule

A cell whose expected outcome the cited authority does not DETERMINE is not
filled by judgment: record it in the INDEX as `OPEN — needs ruling`, with
the two candidate readings in one line each, and list every such cell in
the final report. Zero invented expectations — a wrong EXPECT is worse than
a missing row, because it pins the bug as the contract.

## Gates

Examples-only branch (pin files and matrix tests do not make it a compiler
branch): per-commit `battery.sh suite`; terminal
`battery.sh suite lexdiff astdiff irdet` — the new files join those three
corpora, which must stay clean over them. sos untouched, not owed.

## Report shape

Cell counts per grid (green / red / cited-existing / N/A / OPEN), every DF
filed with its pin, the OPEN list for rulings, and suite timing delta.

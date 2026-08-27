# Design 248 — A Saw Linter, SCOPING: Both Shapes

**Status: AUTHORED Aug 27 2026** (lead, on the user's "draft the linter
scoping brief - both shapes"). Scoping only — nothing here is ruled; §5 is
the ruling sheet. No linter brief existed before this one (checked: every
"lint" hit in designs/ is CLINT hardware, the internal compiler-tree hygiene
lanes, or design 54's one stray note).

## 1. Why now, and what already exists

Three separate pressures point at the same tool-shaped hole:

- **Design 150 built the compiler's warning infrastructure and stopped at one
  category.** `-W NAME` / `-W all`: off by default, repeatable, never affects
  the exit code, no `-Werror` — all ruled. `shadowed-qualifier` is the sole
  occupant. The infrastructure is the cheap half of any linter story and it
  is already paid for.
- **Recorded candidates have nowhere to go.** Design 54 noted "map literal
  with constant duplicate keys — possible lint later" and it never became a
  tracker entry; the POST-LANDING IDIOM REVIEW (the lead hand-skims every
  integrated agent's .saw for idiom against the saw-lang skill) is a standing
  manual workflow whose catches grow the skill but mechanize nothing; the
  Aug-27 comment census/trim enforced the comment bar by hand over eight
  files and produced exactly the kind of category grid a checker would want.
- **The devtools doctrine wants a second citizen.** Design 155 ruled devtools
  are written IN Saw (`devtools/irdet/` is the port precedent, still driving
  the Python sawc); a linter is the classic next devtool, and a big honest
  dogfood program in the design-203 spirit.

## 2. The two shapes

**Shape A — compiler-integrated: grow design 150's `-W` categories.** Right
for anything needing what the compiler already knows: name resolution, types,
reachability, overload sets. Zero new infrastructure; each category is a
small brief-unit against the existing warning machinery, reported on the
SUCCESS path, testable with `// EXPECT-WARNING-CONTAINS:` /
`// EXPECT-NO-WARNINGS` (both exist since 150). Constraint inherited from
150's rulings: off by default, never exit-affecting, no -Werror — a -W
category can inform a CI gate only through text, not status.

**Shape B — a standalone `sawlint` devtool, written in Saw.** Right for
style and idiom: judgments the compiler should NOT hard-code (naming
conventions, skill idioms, the comment bar) and checks that want a
tool-owned exit code for CI use — which the compiler's warning tier is ruled
never to have. Lives in `devtools/sawlint/`; distribution question rides
design 238's sawos split the way every devtool does.

The conventional split — semantics in A, style in B — is the lead's
recommendation, but it is a ruling (§5 Q1), not a given: the all-in-one
alternatives are "everything is a -W" (style opinions inside the compiler,
against the grain of 150's neutrality) and "everything is sawlint"
(reimplementing name/type analysis outside the compiler, which the
architecture section says is not close).

## 3. Shape B architecture — what sawlint can actually see

The honest constraint: **there is no Saw parser in Saw.** The selfhost tree
has a LEXER only (`selfhost/lexer/`, its own tests run as the battery's
`selfhostlex` lane). So sawlint's input access is one of:

- **B1 — drive the Python sawc, consume `--emit-ast`** (canonical JSON dump;
  `--ids` exists for stable node ids). The irdet precedent exactly: a Saw
  binary orchestrating the Python compiler. Full syntax tree, no semantic
  annotations (the dump is the PARSED surface) — enough for naming, idiom
  shapes, import hygiene at the syntax level; not enough for type-aware
  checks (those stay Shape A). Cost: sawlint inherits the Python toolchain
  at lint time, same as irdet.
- **B2 — the selfhost lexer as the token source.** Pure-Saw, fast, and the
  lexer's second real consumer (dogfood value). Token-level checks only:
  comment-bar heuristics, spacing/formatting conventions, doc-comment
  placement smells. Cannot see declarations.
- **B3 — wait for a selfhost parser.** Not scheduled anywhere; design 231
  (native compiler, a v1.0 gate) will eventually force one. Parking sawlint
  behind it costs the tool years of usefulness.

Lead recommendation: **B1 + B2 together** — `--emit-ast` for structure,
the selfhost lexer for trivia-level checks (the AST dump does not carry
comment trivia; the lexer does, per design 121's `--docs` work). A later
selfhost parser slots in without changing sawlint's check inventory.

## 4. Candidate inventory (starting set — every row VERIFY-gated)

Per tracker convention, each candidate needs a probe against current
behavior before it is treated as real work; some may already be errors.

**Shape A (-W categories):**
- `duplicate-literal-key` — map/set literal with equal CONSTANT keys
  (design 54's recorded note; VERIFY current behavior — last-wins silently?).
- `unused-import` — an import binding (qualifier or selective name) never
  used. Real interaction with 150's weak-qualifier rule: a local silently
  shadows a qualifier, so an import can become dead invisibly — this
  category is the counterpart of `shadowed-qualifier`.
- `discarded-optional` — an Optional-returning call in implicit-discard
  position. Design 151 deliberately ruled Result-only for the ERROR; whether
  Optional deserves the warning tier is its own small ruling.
- `unreachable-arm` — a match arm shadowed by an earlier covering pattern
  (VERIFY: may already be an error via exhaustiveness work).
- `suspicious-none-compare` — `x == None` where `.is_none()` is the idiom
  (DF-215g's workaround; retire or re-scope if the DF's fix lands inference).

**Shape B (sawlint checks):**
- `api-abbreviation` — public API names against the no-abbreviations
  doctrine (term-of-art allowlist seeded from the doctrine's own examples).
- `naming-convention` — case conventions per declaration kind.
- `comment-bar` — narration/restatement heuristics over `//` trivia (the
  Aug-27 census categories f/g); ADVISORY tier permanently — a heuristic
  that flags for a human, never a gate.
- `doc-comment-coverage` — public declarations lacking `///` in a package
  that opts in (std would).
- idiom set seeded from the saw-lang skill's gotchas, grown by the
  POST-LANDING IDIOM REVIEW's future catches — the review keeps its human
  judgment; sawlint mechanizes yesterday's catches.

## 5. The ruling sheet (nothing below is decided)

- **Q1 — the split.** Semantics→A, style→B (recommended)? Or one home?
- **Q2 — exit codes.** Ratify that 150's never-exit-affecting rule is a
  COMPILER property, and sawlint (Shape B) MAY gate CI with its exit code —
  the reason B exists as a separate tool. If instead NO lint anywhere may
  gate, B loses most of its point and A absorbs the inventory.
- **Q3 — suppression.** A CI-gating sawlint needs a per-site suppression
  spelling (a comment directive? which grammar?); -W categories, being
  opt-in, have deliberately none today. Suppression syntax is user-facing
  surface and wants a real ruling.
- **Q4 — v1 inventory.** Which §4 rows are in the first landing (lead
  suggestion: A = `unused-import` + `duplicate-literal-key`; B = skeleton +
  `api-abbreviation` + `comment-bar`-advisory, proving the B1+B2 spine).
- **Q5 — blade integration.** `blade lint` as the porcelain (mirroring
  `blade test`)? And does the battery grow a lane that runs sawlint over the
  tree's own .saw (self-application — the strongest dogfood, but a new
  standing gate)?
- **Q6 — the B1 contract.** Is `--emit-ast`'s JSON a STABLE surface sawlint
  may depend on, or does taking that dependency need the dump promoted to a
  documented contract (it is currently a debugging aid; irdet already leans
  on it, so promotion has two customers)?

## 6. What this brief does not do

No implementation staging beyond §5 Q4's suggestion, no schedule position
(BACKLOG until ruled), and no claim that the inventory is complete — §4 is
seeded from RECORDED pain only (design 54, DF-215g, the doctrine, the
Aug-27 census). A ruled v1 would open with its own obligation-1 pass: a
linter is one funnel per check by construction, but the CATEGORY REGISTRY
(what `-W all` and `sawlint --list` enumerate) is the position-quantified
surface that must not fork between the two shapes.

# Design 262 — Docs Consistency Sweep II, and the `docverify` Lane

**Status: USER-RULED Sep 3 2026** ("we should probably do another docs
sweep — missing / wrong features and consistency between the readme,
claude, spec and skill; all examples must be verified to compile").
Three rulings taken at scoping: the verifier is a STANDING BATTERY LANE,
not a one-off audit; the census (U0) runs NOW, in parallel with design
261; Opus throughout (no Sonnet grid). A fourth ruling, same session:
**all user-facing doc prose written or corrected under this design
follows the saw-docs skill** — the fix agent loads it before touching
README/spec/skill text. Briefs and tracker entries stay in lead voice
(the saw-docs skill's own charter excludes them).

## 0. Motivation, and where the drift risk is

The last all-sources sweep was design 138 (Aug 6). Roughly a hundred
designs have landed since — the Thread/Task split (242), the allocator
flip and `try_` retirement (234), places maturation (141/146/176/188/
200), import completion (247b/249/254/255/256), consuming receivers
(260), Float↔text (253), splice-all (218/1.5) — and no gate has ever
compiled a single documentation example. Risk ranking, from the scoping
probes:

- **README (991 lines, 23 tagged blocks)** — highest. Design 125 makes
  it a required landing target but it gets the least attention; it
  carries CLI/stdlib surface lists that the 234 retirements and 242's
  deleted `spawn { }` could have stranded.
- **CLAUDE.md orientation digest (542 lines, no code blocks)** — a
  patchwork: opens "Landed through design 161" with amendments bolted
  on through 260. Orientation-only by convention (125), but a wrong
  digest misleads every dispatch. Corrections only; it is not a feature
  doc and does not become one here.
- **LANGUAGE_SPEC (11,918 lines, 316 tagged blocks of 708 fences)** —
  authoritative and edited per landing, so the failure mode is STALE
  CORNERS: prose written before a later design amended the behavior
  without touching that section (the DF-230a two-stale-sentences
  class), not wholesale gaps.
- **saw-lang skill (3,987 lines, 15 tagged blocks of 30 fences)** —
  freshest (maintained continuously), but it is the densest example
  corpus per line and many of its fences are UNTAGGED, which the
  marker migration must close.

## 1. The marker convention (lead-recommended, ratified with the brief)

Fence-info strings — invisible in rendered output, greppable, and the
extractor's classification input. Three markers:

- ` ```saw ` — a COMPLETE PROGRAM. The lane compiles it; failure is a
  lane failure. (Compile only — run-verification of stated outputs is a
  future tightening, deliberately out of v1: the user's bar is "all
  examples must be verified to compile".)
- ` ```saw-error ` — a program the compiler must REFUSE. The lane
  compiles it and fails on SUCCESS. An optional first-line
  `// error-contains: <substring>` pins the diagnostic; without it, any
  clean refusal passes (a traceback/ICE never does — the fuzz oracle's
  standard).
- ` ```saw-fragment ` — deliberately incomplete (elisions, signature
  sketches, multi-file halves). EXEMPT from compilation, but COUNTED:
  the lane reports the exempt fraction per document, so erosion toward
  "everything is a fragment" is loud (the no-silent-caps doctrine).
  No hidden-scaffolding lines — these docs are read raw, so rustdoc's
  `#`-prefix trick would pollute the visible text; exempt-and-count is
  the honest v1.

Untagged fences holding Saw code get tagged by the migration; untagged
non-Saw fences (shell, output transcripts, grammar sketches) stay bare
and the extractor ignores them.

## 2. Units

- **U0 — the census (sweep agent, Opus, read-only, DISPATCHES NOW).**
  Two grids, one report:
  (a) BLOCK INVENTORY: every fence in the four sources, classified
  complete / error-demo / fragment / non-Saw, with the proposed marker
  and — for would-be-complete blocks — a compile probe under
  `.build/scratch/` (single compiles, not suite-shaped; no lock owed).
  A block that fails its probe is a FINDING: either the doc is wrong or
  the compiler is (the DF-276a class — design 253 filed three real
  compiler bugs out of doc examples).
  (b) CLAIMS DIFF: each document's feature claims against the landed
  set (done files + spec + tracker), three columns — MISSING (landed,
  undocumented where 125 requires it), WRONG (documents retired or
  amended behavior; every WRONG entry carries direct compile/run
  evidence, never a grep-only claim), INCONSISTENT (two sources
  disagree; cite both spans). The 38 "SUSPECT in older builds" callouts
  (34 skill, 4 spec) are checked for currency where the census has
  evidence in hand, not exhaustively re-probed.
  Report to `.build/scratch/docs_census_sep3.md`; the lead reviews and
  commits it to `designs/reviews/`. Findings are census-numbered
  (C1..Cn); the lead assigns DF numbers at triage (DF-294a+ — 293a+ is
  the 261 agent's range).
- **U1 — the `docverify` harness + battery lane (Opus worktree, AFTER
  261 INTEGRATES, one dispatch with U2).** `tools/docverify.py`: ONE
  extraction funnel over the four sources (obligation 1 — the docstring
  names its entry points; adding a fifth source is editing one list),
  emitting each block to a scratch tree and compiling per marker.
  Battery gains a `docverify` stage (edit `STAGES`); the stage reports
  compiled/refused/exempt counts per source and fails on any
  wrong-outcome block. Fast tier (~350 single compiles — minutes), not
  one of the slow five.
- **U2 — marker migration + the fix landing (same dispatch as U1).**
  Tag every fence per the census's inventory; promote fragments that
  are one cheap edit from complete (the census marks these); land the
  triaged corrections from the claims diff per the user's rulings; the
  CLAUDE.md digest gets its corrections in place (patchwork accepted —
  it is a digest, not a narrative). ALL doc prose under the saw-docs
  skill, loaded before the first edit. The lane goes green in this
  unit's terminal commit — U1's harness is unfailable before the
  migration exists, which is why the two ship together.

## 3. Sequencing and collision fences

U0 is read-only and collides with nothing — it runs while 261 builds.
U1/U2 touch the spec and skill, which 261's U3 is editing (the
`FixedBuf.ptr()` gotcha retirement), so they dispatch only after 261
integrates, and the census's spec/skill rows in that section are
re-checked against post-261 text at dispatch (the census report notes
which rows 261 will invalidate). The queue slot is the user's call at
that point; nothing here blocks 218 stages 4/5 or the perf batch — the
U1/U2 surface is docs + tools/battery.sh, not compiler internals.

## 4. Fences and non-goals

- Compile-gate only in v1 — no output/run verification of examples.
- Scope is the four named sources. TESTING.md, rt/ABI.md (the `abidoc`
  lane's beat), designs/, and docstrings in std are OUT.
- No prose rewrites beyond corrections — voice fixes ride only on text
  a correction already touches.
- The census does not re-probe all 38 SUSPECT callouts; the lane does
  not execute examples; neither owes conformance rows (obligation 3
  does not trigger — no safety guarantee moves; the docs DESCRIBE
  guarantees, and a wrong description is a finding, not a rule change).
- A census finding that is a COMPILER bug files as an ordinary DF
  (mechanism named, obligation 4) and is NOT worked around in the doc —
  the example stays, marked with its DF citation, exactly as an XFAIL
  pins a finding.

## Amendment A (Sep 3, post-census — lead, on U0's evidence; report:
## designs/reviews/docs-census-sep3.md)

The census (1,664 sawc invocations over 440 Saw-tagged blocks; zero
ICEs) corrects §1's marker design in three places and §0's sizing:

- **`saw-error` REQUIRES `// error-contains:`** (census C1). sawc says
  ``no `main` function found`` before reaching most claimed checks, so
  the exit-code-only form passes ~300 of 440 blocks without testing
  anything — of 115 error-marked blocks only 8 refuse at the marked
  line cleanly. The lane additionally REJECTS an error-demo whose only
  diagnostics are `no main` / a line-1 parse error, unless the pinned
  substring names exactly that.
- **The lane's compile spelling is `-c`** (census C2): object-only, no
  main required, no link — 72 blocks accept under it vs 19 under the
  default, with zero doc edits. A `saw` block must compile under `-c`
  as written.
- **A fourth marker, ` ```saw-body `** (census C3): a statement
  sequence the HARNESS wraps in a synthesized `func main() { }` (plus
  hoisted imports) before compiling — scaffold in the harness, never in
  the doc text, which keeps §1's no-hidden-lines rule intact. The
  census found 20 such blocks; with `-c` covering the 50 append-main
  blocks as plain `saw`, the four markers cover 92 blocks verified
  today, and U2's cheap promotions grow that.
- Sizing corrections (C10/C11): CLAUDE.md has 5 fences (4 bash + the
  repo map — all non-Saw, so nothing owed); the skill has 88 blocks /
  87 tagged, not 30/15; SUSPECT callouts are 44 (39 skill + 5 spec).

Also recorded here: the census's headline is INVERTED from §0's risk
ranking — the 234/242 priority checks came back CLEAN in all four
sources and 40 spec error demos quote real diagnostics near-verbatim;
the debt is block verifiability (348/440 refused by every spelling),
which is exactly what the standing lane exists to hold.

## 5. Gates

U0: none (read-only; probes are single compiles). U1/U2 per-commit:
full suite + the new lane's own run (docs/tools edits are not a
compiler branch, so freestanding is not owed per commit). Terminal: the
FULL battery with `docverify` in the stage list, green, and the
census-to-triage ledger (every C-number resolved: fixed, DF-filed, or
user-waived) recorded in the landing note.

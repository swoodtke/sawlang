# Docs consistency review — 2026-08-04

Cross-check of the four documentation surfaces at `main` = `f764b75`:

1. `README.md` (pitch / overview)
2. `LANGUAGE_SPEC.md` (normative reference)
3. `.claude/skills/saw-lang/SKILL.md` (working digest)
4. `CLAUDE.md` (dev guide; "Language state" orientation digest)

Every disagreement below was adjudicated against the compiler, not against
another document. Probe programs live in `.build/scratch/docrev_*.saw`
(gitignored); each row names the one that settles it.

Differences of *depth* (README summarizes, SPEC is normative, SKILL compresses)
are not findings. Differences of *fact* are.

---

## Findings

| # | Side A | Side B | What each says | Which is right (evidence) | Severity |
|---|--------|--------|----------------|---------------------------|----------|
| 1 | `LANGUAGE_SPEC.md:152-157` | `LANGUAGE_SPEC.md:1462`, `:1501-1520`; `README.md:442-449`; `SKILL.md:98-111` | A: the `swap<T>(a: &var T, b: &var T)` example comment — "mutation through a `&var` reference uses compound assignment or mutating methods; **direct `a = b` is rejected**". B: design 110 — whole-referent replacement `x = v` / `self = v` through `&var` is legal. | **B.** `docrev_refassign.saw` compiles clean and prints `2 / 99 / 0`: `a = b` between two `&var Int` params, `a = 99` through a `&var`, and `self = Counter(n: 0)` in a `&var self` method all work. A:152-157 is pre-110 text the spec never swept. | would-mislead-a-user |
| 2 | `README.md:544` | `LANGUAGE_SPEC.md:3946` | A: "`-o` names the output; default is `.build/<source>`". B: "`-o <file>` Output executable name (**default: `./<source>`**)". | **A (README).** With no `-o`, `sawc .build/scratch/docrev_readme_quick.saw` wrote `.build/docrev_readme_quick`; `./docrev_readme_quick` does not exist. `sawc/sawc.py:1191-1199` hardcodes the `.build/` directory. (`sawc`'s own `--help` epilog, `sawc.py:1119`, repeats the spec's wrong claim — worth fixing with it.) | would-mislead-a-user |
| 3 | `LANGUAGE_SPEC.md:705-713`; `SKILL.md:62-66` | compiler | Both: `--emit-docs` JSON carries "the two things a signature does not show: whether the function **suspends**, and whether a method borrows / mutably borrows / consumes `self`". | **Neither — the implementation is wrong.** `docrev_effect.saw`: `slow_double` calls `yield_now()` and the effect checker proves it suspends (`error: cannot suspend in 'sync func' ... 'slow_double' suspends at line 7`), yet `--emit-docs` emits `"effect": "sync"` for it. Same for `napper` (calls `sleep`) even when both are `group.spawn`ed (`docrev_effect2.saw`). Only names on the hardcoded std lists in `sawc/docs_emit.py:410-418` ever report `"suspending"` (`yield_now` does). A generated docs site would label every suspending *user* function `sync`. | would-mislead-a-user |
| 4 | `README.md:598-600` | `CLAUDE.md:103-104`, `:5-8` | A: "The authoritative, always-current feature list lives in **CLAUDE.md**". B: "Docs convention: spec + saw-lang skill get feature updates (**NOT this file**)"; and CLAUDE.md's own header points at `LANGUAGE_SPEC.md` as "the authoritative language reference". | **B.** The README sends readers to the one surface the project's own workflow exempts from feature updates — and finding 6 shows that surface is in fact stale. The authoritative pointer should be `LANGUAGE_SPEC.md`. | would-mislead-a-user |
| 5 | `LANGUAGE_SPEC.md:1148` | compiler | Spec: "`Int`/`UInt` and the fixed-width integers ... conform `Printable` **builtin** — the compiler renders them inline." | **Spec is right in intent; the compiler is broken for unsigned `print`.** `docrev_uint_print.saw`: `print(a)` for `a: UInt = 18446744073709551615` prints `-1`, `print(UInt.max)` prints `-1`, `print(c)` for `c: UInt64 = 18446744073709551615u64` prints `-1` — while `print("{a}")` (interpolation) correctly prints `18446744073709551615`. `print()` takes the signed formatter; interpolation takes the unsigned one. This directly defeats design 119: `SKILL.md:553-557` sells `to_uint()` for reaching `2^63..2^64-1`, and `docrev_119.saw` shows you cannot `print` the result you parsed. **Compiler bug found during the review — not a doc fix.** | would-mislead-a-user |
| 6 | `CLAUDE.md:109` | `CLAUDE.md:118-123`, `:136-140`, `:164-169` | A: "Landed through **design 109** (Aug 3)". B: the same paragraph then describes 110, 111, 114, 119, 120 and 121. | **B.** Internal contradiction: only the leading claim is stale. Bump it to "Landed through design 121 (Aug 4)". | minor-staleness |
| 7 | `LANGUAGE_SPEC.md:3651`, `:3976-3977`, `:3996-3998` | `LANGUAGE_SPEC.md:3637-3699` (§10, "Status: implemented"); `SKILL.md:490-500`; `CLAUDE.md:157-163` | A: §10 calls `unsafe` "a **contextual** keyword"; Appendix A's contextual list is `any escaping sync` only, and `unsafe` sits under "**Planned / reserved**". B: the `unsafe` expression marker is implemented (design 81). | **B on implemented; both A claims wrong on the mechanics.** `docrev_unsafe_ident.saw` (`let unsafe = 5`) → `Parse error at 6:9: Expected variable name`; `sawc/lexer.py:192` puts `'unsafe'` in `KEYWORDS`. So `unsafe` is a **hard reserved word for an implemented feature** — Appendix A files it as planned, and §10 mislabels it contextual. | minor-staleness |
| 8 | `LANGUAGE_SPEC.md:3990` | `sawc/lexer.py:198-204` | A: Appendix A ("Reserved words") lists `import`, `module`, `package`, `parent` under **Implemented**. B: the lexer comments state these are deliberately *not* keywords, "handled specially by the parser only in specific syntactic positions to avoid conflicts with user code". | **B.** `docrev_keywords.saw` binds `package`, `parent`, `sync`, `escaping`, `any` as ordinary locals and prints `15`. Appendix A over-reserves four names while under-reserving `unsafe` (finding 7) — the table has the inversion in both directions. | minor-staleness |
| 9 | `README.md:520-521` | `LANGUAGE_SPEC.md:2348-2356` | A: one bullet — "**Numeric extensions** — `Int`/`Float` methods: `abs`, `pow`, `min`/`max`/`clamp`, `sqrt`, `floor`/`ceil`/`round`, `is_even`/`is_odd`, `signum`". B: the sets are disjoint — `Int`: `abs`/`min`/`max`/`clamp`/`pow`/`is_even`/`is_odd`/`signum`; `Float`: `abs`/`floor`/`ceil`/`round`/`sqrt`/`min`/`max`. | **B.** `docrev_numeric.saw` (`9.sqrt()`) fails with `hint: available methods: abs, clamp, is_even, is_odd, max, min, pow, signum`. The README's merged list reads as "both types have all of these"; neither `Int.sqrt()` nor `Float.pow()` exists (`sawc/std/numeric.saw:30-124`). | minor-staleness |
| 10 | `README.md:556-563` | `LANGUAGE_SPEC.md:3944-3958`; `CLAUDE.md:49-52`; `sawc/sawc.py:1125-1156` | Three different subsets of the same CLI. README lists `-o -c -v --emit-ir --emit-ast -O0`. SPEC adds `--emit-docs`/`--emit-docs-all` but omits `--module-path`/`--freestanding`/`--runtime-build`/`--target`. CLAUDE.md lists `--module-path`/`--freestanding`/`--runtime-build` but omits `--emit-docs*`/`--target`. | **The compiler.** The real set is `-o -v -c --emit-ir --emit-ast --emit-docs --emit-docs-all -O0 --target --freestanding --runtime-build --module-path`. **No document lists `--target`.** CLAUDE.md's omission of `--emit-docs` is self-contradictory — its own digest at `:164-167` cites the flag. README's omission of `--module-path` is self-contradictory too — README uses it at `:611-613`. | minor-staleness |
| 11 | `README.md:496-501` | `LANGUAGE_SPEC.md:585-590`, `:611-618`; `SKILL.md:549-557` | A: String bullet lists `to_int`/`to_float` parsing; StringBuilder bullet lists "`append` (overloaded for `String`/`Int`), `build`". B: design 119 added `to_uint()`/`to_uint(radix:)` and `StringBuilder.append_scalar`. | **B.** `docrev_119.saw` prints `255` (`"ff".to_uint(radix: 16)`), `3` (`append_scalar(0x2713)`), and `surrogate rejected` (`append_scalar(0xD800) -> None`). `sawc/std/stringbuilder.saw` also carries `append_char`, `clear`, `as_str` — none in the README bullet. README never got the 119 sweep. | minor-staleness |
| 12 | `README.md:259-291` | `LANGUAGE_SPEC.md:2594-2607`; `SKILL.md:396-404`; `CLAUDE.md:136-140` | A: "Colorless Concurrency" never mentions that a suspending call may sit in an arbitrary expression. B: design 120 — chain heads/hops, arguments, receivers, operands, literal elements, interpolation, `return`, `try!`, `?.` hops, `Channel.receive()`, with order and short-circuit preserved. | **B.** `docrev_120_expr.saw` prints `14 / interp 10 / 6 / 14` — suspending calls as binop operands, inside interpolation, as `Vector` literal elements, and as a `??` RHS. README lags 120. | minor-staleness |
| 13 | `README.md` (no mention anywhere) | `LANGUAGE_SPEC.md:663-714`; `SKILL.md:54-66`; `CLAUDE.md:164-169` | A: silent on doc comments. B: design 121 — `///` / `//!`, stray-doc error, `--emit-docs` JSON. | **B.** `docrev_120_expr.saw --emit-docs` emits a populated JSON tree including the `//!` module doc and each `///` body. README lags 121 entirely (the CLI block at `:556-563` is the natural home, per finding 10). | minor-staleness |
| 14 | `README.md:588-596` | `README.md:82-84`, `:442-449`; `CLAUDE.md:118-123` | A: the "Current Status" roll-up omits optional chaining (111) and whole-referent replacement (110). B: the README's *own body* documents both, as does CLAUDE.md. | **B.** Internal README staleness: the summary paragraph was not swept when the feature sections were. | minor-staleness |
| 15 | `README.md:502-503` | `SKILL.md:546-548`; `LANGUAGE_SPEC.md:3701-3705` | A: Vector bullet — `push`, `pop`, `get`, `len`, `map`/`fold`, `sort`/`sort_by`, `swap`. B: `with_ref`/`with_var_ref` are the design-81 scoped element borrow that *replaced* `ref_at`, and the only way to reach a `NoCopy` element. | **B.** Not a contradiction, but the README's list omits the one Vector API a `NoCopy` element type requires. | cosmetic |
| 16 | `README.md:617-622` | `SKILL.md:577`; `blade/src/main.saw:29` | A: lists `new`, `build`, `run`, `test`, `tree`, `add`. B: also `update` ("Re-resolve dependencies and rewrite Saw.lock"). | **B.** README's Blade command list is one subcommand short. | cosmetic |
| 17 | `LANGUAGE_SPEC.md:2467-2470` | `LANGUAGE_SPEC.md:2461-2466` | A: "Any call may suspend (**once the cooperative engine lands**)". B: five lines above — "Cooperative engine — **implemented**". | **B.** Internal spec staleness; drop the parenthetical. | cosmetic |
| 18 | `LANGUAGE_SPEC.md:2369-2370` | `LANGUAGE_SPEC.md:2705-2711` | A: §6 preamble names the second engine "the cooperative **single-threaded** executor". B: `TaskGroup(threads: N)` (design 75) makes it optionally multi-threaded. | **B.** The preamble predates 75; it should say "cooperative executor (single-threaded by default)". | cosmetic |
| 19 | `LANGUAGE_SPEC.md:3456` | `LANGUAGE_SPEC.md:875-876` | A: §9 "Core Types" sketch writes `std.option.{Option, Some, None}` (also `std.vec.Vec`, `std.collections.{Map, Set, Deque}`). B: "the empty case is the keyword `None` (there is **no** `some(...)`/`none` constructor)"; the type is `Vector`, and `Deque` does not exist. | **B.** §9 is flagged "largely *illustrative*" at `:3441-3442`, which covers it — but `Some` as a named export contradicts a normative rule elsewhere in the same document. | cosmetic |
| 20 | `LANGUAGE_SPEC.md:474-487` | `LANGUAGE_SPEC.md:463-465`, `:582-583`; `SKILL.md:549` | A: the primitives code block lists `Int128`, `UInt128`, `Float32`, and `Char // Unicode scalar value` with no marker. B: the prose immediately above says `Int128`/`UInt128`, `Float32`, and `Char` are *planned*, and the String section says "there is no `Char` primitive type yet (a scalar is just an `Int`)". | **B.** The prose caveat carries it, but the unmarked code block is the part a reader copies. Inline `// (planned)` markers would close it. | cosmetic |

**Counts:** 5 would-mislead-a-user · 9 minor-staleness · 6 cosmetic · **20 total**.

---

## Systemic

**README is the consistent laggard.** It is fully current through design 111
(optional chaining and whole-referent replacement both have prose and examples)
and then stops: 119 (`to_uint` / `append_scalar`), 120 (expression-position
suspension) and 121 (doc comments, `--emit-docs`) are absent, and its own
"Current Status" roll-up (#14) trails its own body. The `Docs convention: spec +
saw-lang skill get feature updates` line in `CLAUDE.md:103-104` explains why —
the workflow names two surfaces, and the README is neither. That is a defensible
policy for a pitch document, but it collides head-on with `README.md:598-600`
telling readers the always-current list lives in `CLAUDE.md` (#4), a third
surface the same policy also exempts. Net effect: the README points at a stale
map, and nothing in the workflow schedules a README sweep. Either fold the
README into the docs convention or change its pointer to `LANGUAGE_SPEC.md`.

**Spec drift is local to unswept examples and appendices, not to normative
prose.** Every design-110-through-121 feature has correct, current normative
text in `LANGUAGE_SPEC.md`. The spec's four wrong claims all live in *older*
material the feature landings did not revisit: an illustrative comment from
before 110 (#1), the CLI appendix (#2, #10), the keyword appendix (#7, #8), and
pre-75/pre-89 preamble sentences (#17, #18). Landing agents update the section
they own and nothing else. A cheap mitigation: treat Appendix A/B and Appendix 0
as a mandatory checklist item on any brief that touches syntax, keywords, or the
CLI.

**SKILL.md is the most current surface and disagreed with nothing.** It carried
110, 111, 114, 119, 120 and 121 correctly, and its only gap versus the spec is
deliberate compression. Where SKILL and SPEC agree against the implementation
(#3), the implementation is the bug.

**Two of the five would-mislead findings are compiler bugs surfaced by the
docs, not doc errors.** #3 (`--emit-docs` reports `"effect": "sync"` for
suspending user functions) and #5 (`print` renders `UInt` as signed) both
describe behavior the docs promise and the compiler does not deliver. Per the
spec's own rule at `LANGUAGE_SPEC.md:22-23` — "when the implementation and this
document disagree, the implementation wins and this document is the bug" — the
literal reading would demote the docs, but both are plainly implementation
defects and should be filed as such. #5 is the more urgent of the two: it makes
design 119's headline capability (parsing the `2^63..2^64-1` range) unprintable
through `print()`, while the interpolation path prints it correctly.

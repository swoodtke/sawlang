# Design 121 — doc comments + --emit-docs (queued Aug 4)

USER DECISION (Aug 4): the sawlang.com docs site (tracker Milestones)
gets its API reference FROM stdlib source. This brief lands the two
foundation pieces: a doc-comment syntax and a compiler extraction
mode. The site generator (`sawdoc` in Saw), the std docstring-writing
pass, and the site itself are LATER designs — this brief only proves
the pipeline end-to-end on a small std sample.

## Syntax (pinned, veto-able)

- **`///` documents the FOLLOWING declaration.** A contiguous block of
  `///` lines (no blank line inside) attaches to the next documentable
  item: top-level func/struct/enum/trait/static/type alias/extension,
  extension members (func/init), enum cases, struct fields. Blank line
  or non-doc comment breaks the block.
- **`//!` documents the ENCLOSING module** (file); allowed only before
  the first declaration; multiple contiguous `//!` lines form one
  module doc.
- Doc-comment bodies are Markdown by convention; the compiler treats
  them as opaque text (no Markdown validation in this design).
- **An unattached `///` block is a clean error** ("doc comment is not
  followed by a documentable declaration"), anchored at the block —
  consistent with the no-silent-drop culture. `//!` after the first
  decl likewise.
- Ordinary `//` comments are untouched. `////` (4+) is an ordinary
  comment (rules out banner lines).

## Lexing + the parity contract

- Doc comments are captured as TRIVIA (out-of-band records attached to
  the token stream / next token), not ordinary skipped comments and
  not regular tokens — the token stream seen by the parser is
  otherwise UNCHANGED (no ripple into existing positions).
- **Both lexers, same commit** (sawc/lexer.py AND selfhost/lexer —
  the lexdiff parity contract): equivalent capture (text with the
  `///`/`//!` prefix stripped, start line:col per line, kind
  doc/module-doc). The canonical dump format is UNCHANGED by default
  (parity baselines stay); both dumpers gain a `--docs` mode emitting
  doc-trivia records, and tools/lexdiff.py gains a `--docs` sweep
  comparing them over the corpus (run in CI alongside the normal
  sweep). NOTE: coordinate with design 119's dumper changes (suffix
  column) — 121 dispatches after 119 integrates, so build on its
  format.
- Parser: attach collected trivia to the AST declaration nodes
  (a `doc: Optional[str]` field family); module doc on the Program
  node. The typechecker carries docs into the namespace entries it
  builds (so extraction reads RESOLVED items, not raw AST).

## --emit-docs (extraction)

- `sawc <entry> --emit-docs [-o out.json]`: type-checks as usual, then
  emits JSON instead of code. Works for a single module and for std
  itself (a driver enumerates the std modules; each std FILE is its
  own module per design 82).
- **Public surface only by default** (design-80 visibility is the
  filter — fields/methods/inits not visible outside the module are
  omitted); `--emit-docs-all` includes private items (for internal
  tooling).
- JSON schema (pin the shape in the brief commit; versioned field):
  per module — name, module doc; per item — kind, name, RENDERED Saw
  signature (from resolved types, not source text), visibility,
  generic params + bounds, params (name/label/type/default), return
  type, **effect (suspending | sync)**, **ownership notes the
  compiler knows** (consumes/borrows self, `&var` params), trait
  conformances (for types), enum cases + payloads, doc text (raw),
  source file:line. The effect and ownership fields are the
  Saw-specific documentation value — surface them.
- Deterministic output (stable ordering) — the JSON is diffable and
  goldens-testable.

## Scope

1. Lexer trivia capture (both lexers) + `--docs` dump/lexdiff modes.
2. Parser/AST attachment + the unattached-doc errors.
3. Typechecker: carry docs onto namespace entries.
4. `--emit-docs` + JSON schema + determinism.
5. Demonstration + tests: docstring TWO std modules as the
   end-to-end sample — `std/task.saw` and `std/time.saw` (small,
   stable surfaces) — following `.claude/skills/saw-docs/SKILL.md`
   (the Saw docs-writing skill; load it before writing ANY doc
   text). Tests: attachment shapes (each documentable item kind);
   the unattached-`///` and misplaced-`//!` error tests; a golden
   `--emit-docs` JSON test (COMPILE-FLAGS + expected output);
   `--docs` lexdiff sweep green over the corpus; the NORMAL lexdiff
   sweep unchanged (dump format untouched by default).
6. Docs: LANGUAGE_SPEC gains the doc-comment section (syntax,
   attachment, errors); saw-lang skill gets a doc-comment bullet;
   CLAUDE.md digest line; tracker vision entry updated (pipeline
   foundation DONE, next = sawdoc generator + std docs pass).

## Non-goals

The sawdoc HTML generator (own design, in Saw); the full std
docstring pass (own design — content work); Markdown validation or
doc-example testing (a future `sawdoc test` question); doc comments
in blade/libs sources; hosting.

LANGUAGE-ISSUE POLICY (user, Aug 4): do NOT work around language
bugs/limitations. Unambiguous compiler bug → fix with tests. A design
gap that blocks a unit → STOP it, DF-121 tracker entry with repro +
wanted code, report prominently. (This brief is mostly Python-side;
the Saw exposure is the selfhost/lexer change and the std docstring
samples.)

Bars: full suite zero xfails per commit (except any design-120
stage-0 xfails present on main — those are expected and not yours);
both lexdiff sweeps green at the final commit; bootstrap before the
final commit; per-unit commits; linear history; no attribution
trailers; foreground suites; interruption-safe. SEQUENCING: dispatch
AFTER design 119 integrates (shared files: both lexers + both
dumpers + lexdiff); MAY run concurrent with design 120 (disjoint:
120 is coro_transform/typechecker-effects; the one shared surface is
examples/ filenames — keep them distinct).

# Design 116 — self-hosting pilot: the lexer in Saw (queued Aug 4)

USER DECISION (Aug 4): a full compiler rewrite in Saw is the recorded
end goal but is deferred until the language's design churn slows; the
chosen strategy is to GROW SAW'S SURFACE AREA so latent issues surface
and get fixed now (the churn-slowing mechanism). This pilot is step
one: port sawc's lexer to Saw as the first PERMANENT module of the
eventual stage1 compiler, and as a measurement instrument for the
rewrite decision.

Why the lexer: it is the most stable compiler layer (design churn
lives in the typechecker/semantics; the token grammar has barely moved
across 115 designs), so the port will not rot while the language
evolves above it. It also exercises Saw surface nothing else does:
heavy String/scalar processing, large payload-enum match sets,
source-located error modeling, growable buffers, file IO in a CLI
tool.

## Deliverables

1. **`selfhost/lexer/` — a Blade package** (new top-level `selfhost/`
   tree marks the stage1 compiler's home). `src/lib.saw` (the lexer
   library: token model + lex function) and `src/main.saw` (the
   `sawlex` CLI). Depends on std only. Built/tested via `blade build`
   / `blade test` like libs/.
2. **Token model mirroring `sawc/lexer.py`.** Same token kinds, same
   boundaries, same line:col positions (1-based, matching the Python
   lexer). The Saw enum is the model; a README table documents the
   kind-name mapping. The reference for CORRECTNESS is the Python
   lexer's observable output (the spec's lexical section is
   authoritative where they disagree — flag any such disagreement as
   a finding rather than silently picking).
3. **Canonical token-dump format** (pinned in the package README;
   stable, diffable, one record per line):
   `KIND<TAB>line:col<TAB>escaped-text`. Lex errors emit an
   `ERROR<TAB>line:col<TAB>message` record and the CLI exits nonzero
   after emitting them. Error POSITIONS and kinds must match the
   Python lexer; message PROSE need not (message-for-message parity
   is not the bar — position/kind parity is).
4. **`tools/dump_tokens.py`** — emits the SAME format from sawc's
   Python lexer (testing tool only; no sawc CLI changes).
5. **Differential harness: `tools/lexdiff.py` + `make lexdiff`.**
   Sweeps EVERY tracked `.saw` file in the repo (examples/ incl.
   errors/, sawc/std, sawc/builtin.saw, sawc/rt, blade/, libs/, sos/,
   selfhost/ itself) through both lexers and diffs the dumps. Zero
   mismatches over the full corpus is the acceptance bar. Files the
   PYTHON lexer itself rejects are compared on their error records.
   Also wire a CI job (cheap; runs lexdiff after building the Saw
   lexer).
6. **Blade unit tests** (`selfhost/lexer/tests/`): targeted cases per
   token family — every literal form (hex/binary/underscores/
   width-suffixed, range-checked forms), every escape incl. `\u{...}`
   and the brace forms, interpolation delimiters, `#file`/`#line`/
   `#function`, comments, range operators vs float dots (`0..5`,
   `0..=5`, the `7.` float-prefix behavior — matching the Python
   lexer's current INT `.` handling exactly; see the tracker's punted
   integer-literal-receiver DECIDE), operators/punctuation, lex-error
   cases (bad escape, unterminated string, stray `#name`).
7. **Metrics in the final report** (the rewrite-decision inputs):
   Python-lexer LOC vs Saw-lexer LOC; rough tokens/sec for both over
   the corpus; and the DF-finding list.

## The explicit product: DF-findings

Language pain hit while writing a 1-2k-line real Saw program IS the
pilot's primary product, not a side effect. Every workaround, missing
std affordance (e.g. string slicing/scalar-iteration gaps, char
classification, growable-buffer ergonomics), confusing diagnostic, or
outright bug goes into designs/todo.md as a DF-116 finding with a
minimal repro — fix-on-discovery ONLY for unambiguous compiler bugs
per standing policy, never silent workarounds. The churn-slowing
thesis only works if findings convert to tracker entries.

## Non-goals

The parser or anything above tokens; incremental/streaming lexing;
performance tuning beyond honest measurement; ANY sawc compiler
changes (this is a pure Saw package + two Python testing tools); a
shared token interchange with the parser port (future design decides
whether the parser consumes dumps or links the library — the library
API should merely not preclude linking).

Bars: full suite zero xfails before every commit (the compiler is
untouched, but the bar stands and the suite is fast now); blade test
green for the package; `make lexdiff` zero mismatches over the full
corpus at the final commit; per-unit commits; linear history; no
attribution trailers; foreground suites; interruption-safe;
discoveries tracker-flagged, not scope-crept. Load the saw-lang skill
before writing any .saw code. SEQUENCING: independent of everything
else in flight; may run concurrently with any compiler-track brief
(disjoint trees: selfhost/ + tools/ additions only).

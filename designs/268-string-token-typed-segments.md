# Design 268 — String tokens carry typed segments (SL-238)

**Status:** ruled Sep 11 2026 (user): fix SL-238 properly NOW via option (c) —
typed segments — not deferred to the design-259 token/AST reconciliation.
**Issue:** SL-238 (queued). **Seam:** lexer/parser string layer, BOTH lexers.

## The defect

The lexers encode an escaped brace as the two bytes `0x01`+brace inside the
token's flat value string (`sawc/lexer.py:381-383`;
`selfhost/lexer/src/lib.saw:730-737`, `B_MARKER`). Two parser sites decode it:
`sawc/parser/expressions.py:731` (plain STRING: chained `.replace`) and
`:1878-1883` (INTERP_STRING re-scan: `0x01`+brace = content, bare `{` =
interpolation start). But `"\u{1}\u{7b}"` — or a raw U+0001 byte typed in the
source — legitimately produces the same two bytes, and the decode deletes the
real U+0001. Silent content corruption, exit 0 (repro + expected output in
SL-238's body).

## The design

Delete the marker protocol from both lexers. The lexer already knows, at lex
time, which braces open interpolations (it runs the brace-depth scan today) —
so it emits that knowledge as structure instead of re-encoding it into bytes
the parser must re-discover:

- **Plain `STRING` token:** value is the fully-decoded content; braces are
  ordinary bytes (a plain string can only contain a brace via an escape, so no
  disambiguation is ever needed). The `:731` marker strip is deleted.
- **`INTERP_STRING` token:** carries an ordered **segment list** instead of a
  flat value. Segment kinds:
  - `text(bytes)` — decoded literal content (escaped braces are plain `{`/`}`
    bytes here; escapes decoded exactly as today);
  - `expr(raw_text, line, col)` — the RAW source text between an
    interpolation's braces (no escape decoding inside `{...}`, unchanged),
    with the EXACT source position of its opening `{`. Empty/blank raw_text is
    the design-137 format placeholder.
- **Parser:** `_parse_interpolated_string`'s byte re-scan
  (`expressions.py:1864+`) is replaced by direct segment consumption;
  `_parse_expression_from_string` sub-parses `expr` segments as today, but
  seeded with the segment's exact position. The design-99 position contract
  improves: lines stay exact, columns become exact even under escape
  sequences (the current code documents them as approximate). Sweep EXPECT
  tests for column drift; if the churn is more than a handful of files,
  STOP and report the count before proceeding.
- **Selfhost lexer:** same segmentation in `read_string`; the Saw `Token`
  gains the segment representation for InterpString (shape chosen to fit the
  existing struct idiom — a `Vector` of a small segment struct is the obvious
  form). `B_MARKER` and both `err_at` marker mentions of the old protocol go.
- **Dump/parity:** `tools/dump_tokens.py` and the selfhost dumper emit ONE
  canonical record form for segments; `tools/lexdiff.py` compares it. Both
  lexers and both dumpers change in the SAME patch — lexdiff is the lockstep
  gate. The `--docs` trivia sweep is untouched.

## Obligations

1. (Funnel) Segment decoding/consumption has ONE consumer path per side; the
   two scattered marker-decode sites are deleted, none added. The segment
   record form is defined in one place per lexer (named in docstrings).
2. (Contract flip → consumer sweep) BEFORE coding, sweep every consumer of
   `TokenType.STRING` / `INTERP_STRING` token values across `sawc/`, `tools/`,
   `selfhost/`, `devtools/` (grep + one paragraph in the report). Known:
   the two parser sites, `dump_tokens.py`, lexdiff, the selfhost dumper.
   Anything else found joins the matrix.
3. Not a safety-guarantee surface — no conformance rows owed.
4. The SL-238 repro is one face; the mechanism is "content bytes overloaded
   as metadata". The matrix must cover: `\u{1}` and raw 0x01 before `{`, `}`,
   escaped braces, and interpolation, in plain AND interpolated strings;
   escaped braces adjacent to real interpolations; `\u{1}` inside
   interpolation raw text; multi-line interpolated strings (position checks);
   format placeholders beside escaped braces.

## Tests

- SL-238's repro verbatim as a regression (`1`, `2`, `1`).
- The obligation-4 matrix as examples/ tests with exact expected output.
- Existing interpolation/format/brace tests must pass unchanged except
  documented column-exactness diffs.
- Gates: per-commit compiler gate; TERMINAL battery — `lexdiff`,
  `selfhostlex`, `astdiff`, `reemit`, `irdet --all` are the load-bearing
  lanes for a token-shape change.

## Out of scope

Nested string literals inside interpolation expressions confusing the
brace-depth scan (pre-existing, unchanged by segmentation — file separately
if probed). The minivm prototype's own string handling (SL-242 side).

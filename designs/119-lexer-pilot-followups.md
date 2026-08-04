# Design 119 — lexer-pilot follow-ups: text/numeric affordances + fidelity (queued Aug 4)

USER DECISION (Aug 4): close the remaining design-116 findings — the
churn-slowing strategy's value is realized when findings CLOSE, not
when they're catalogued — and finish the pilot's token fidelity. Four
parts, all small, all also de-risking the future parser port.

## A. Checked numeric parsing + integer bounds (closes DF-116b)

- Saw's always-panic overflow arithmetic means user code CANNOT write
  the naive accumulate-and-check parse loop — an overflow-safe parse
  is an API hole, not a nicety (memory: APIs do the expected thing).
- Add a radix-aware, overflow-checked string→integer parse returning
  Optional. Proposed surface (agent refines to what the language
  supports cleanly; spec/skill document whatever lands):
  `s.to_int(radix: Int) -> Int?` overloading/extending the existing
  whole-string `to_int()` (design 53 family) — ONE story, not two:
  same no-trimming rule, same Optional contract; overflow → None
  (never a panic, never a wrap). A `to_uint64`-shaped variant only if
  the lexer's 2^64-1 ceiling genuinely needs it (it checks magnitude
  against unsigned 64-bit max) — prefer the smallest surface that
  kills the digit-string comparison workaround.
- Integer bounds: expose min/max for the fixed-width integer types +
  platform Int/UInt (spelling per language capability — static
  members/constants on primitive types; if THAT is inexpressible,
  it is a DF-119 finding, not a workaround site).
- Replace selfhost/lexer's digit-count + lexicographic magnitude
  check with the new parse; the DF-116b tracker entry closes with a
  pointer here. std-level tests for radixes 2/8/10/16, boundary
  values (max, max+1, u64 max), rejection (empty, junk, overflow).

## B. Scalar→UTF-8 building (closes DF-116c)

- `chars()` decodes; nothing encodes — a one-way string API. Add
  `StringBuilder.append_scalar(scalar: Int)` (UTF-8 encode + append;
  invalid scalar (surrogate range, > 0x10FFFF) → a clean failure
  surfaced per the never-hide-errors rule — proposed: return Bool? NO
  — a genuine QUESTION is Bool, but this is an OPERATION that can
  fail: `-> Result<Void, Utf8Error>`? Agent proposes; the cheap
  honest option is Optional/Result, panic is acceptable ONLY if spec
  documents scalar validity as a precondition like index bounds —
  pick one, document, test).
- Replace selfhost/lexer's hand-rolled encoder. std tests at the
  encoding boundaries (0x7F/0x80/0x7FF/0x800/0xFFFF/0x10000/
  0x10FFFF) + the invalid cases.

## C. Interpolation-brace diagnostic locality (closes DF-116d)

- An unbalanced `{` in a string literal currently reports
  "Unterminated string" AT EOF. Report it at the OFFENDING BRACE
  (line:col of the `{` whose interpolation never closed) with a
  message naming the interpolation (and the `\{` escape).
- MUST land in BOTH lexers in the same commit: error positions are
  part of the lexdiff parity contract (error records compare
  position+kind). Update affected error tests; lexdiff stays zero-
  mismatch over the corpus.

## D. Token suffix fidelity (closes the DF-116a stopped unit)

- DF-116a is fixed (Aug 4, examples/optional_field_store_retain.saw
  guards it). Restore the `suffix` field in selfhost/lexer's `Token`
  and the canonical dump's 4th column IN BOTH DUMPERS
  (tools/dump_tokens.py + sawlex); README format section updated;
  lexdiff re-swept zero-mismatch. Finalizing the format BEFORE the
  parser port consumes it is the point.

## Non-goals

The parser port; bignum/arbitrary precision (DF-116b's tracker entry
notes it as future if ever needed); float parsing changes; any
lexer behavior change beyond the brace diagnostic's position/message.

LANGUAGE-ISSUE POLICY (user, Aug 4): do NOT work around language
bugs/limitations. Unambiguous compiler bug → fix with tests (sawc/ is
in scope). Language design gap that blocks a unit (e.g. no way to
express per-type integer-bound constants) → STOP that unit, record a
DF-119 tracker entry with a minimal repro AND the wanted code,
continue on independent units, report prominently.

Bars: full suite zero xfails per commit; blade tests for
selfhost/lexer green; `make lexdiff` zero mismatches at the final
commit; bootstrap before the final commit (std changes); per-unit
commits (A/B/C/D separable); linear history; no attribution trailers;
foreground suites; interruption-safe. Docs: spec + skill get the new
std affordances; tracker entries DF-116b/c/d + the suffix follow-up
close. SEQUENCING: dispatch only AFTER design 118 lands and
integrates (118 is mid-flight heavy surgery; this brief touches std +
both lexers and wants a calm tree).

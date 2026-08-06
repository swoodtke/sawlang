# Design 161 — `t.0.name`: the tuple-index float-eating lex bug (DF-159a)

**Status: APPROVED (user, Aug 6: "let's brief and run 159a").
Concurrent-eligible (lexer surface only — disjoint from the 160 and
DF-151a agents). Found by design 159's audit.**

## The bug

`t.0.name` is a lex error ("got FLOAT"): the number scanner, having
started on the `0` after a member-access dot, sees the SECOND `.` and
keeps consuming — `0.` lexes as a float and the member access falls
apart. Not interpolation-specific. Workaround today: `(t.0).name`.

## The rule (pinned)

A numeric literal scanned when the immediately-preceding emitted
token is a member-access DOT is a TUPLE INDEX: a bare integer, never
a float, never a suffixed literal — the scanner stops at any second
`.` or suffix character. One-token lookback is the mechanism (both
lexers already track their last emitted token or can trivially).
This makes the nested case right too: `t.0.1` is DOT 0 DOT 1 (two
index hops), not `0.1` the float. Everything else about number
scanning is untouched: `1.5`, `x + 0.5`, range patterns `1..=9` /
`0..5`, suffixed literals `255u8` in ordinary position, and float
literals inside interpolation all lex exactly as before.

## Units

1. BOTH lexers, same commit — error positions and token streams are
   lexdiff contract (the design-116 discipline): `sawc/lexer.py` and
   the selfhost Saw lexer (`selfhost/lexer`), identical rule,
   identical token output. The canonical token dump for `t.0.1.name`
   is part of the review.
2. Tests (value-asserting where they run): `t.0.name`, nested
   `t.0.1` and `t.0.1.name`, a method after the projection
   (`t.0.name.len()`), interpolation `"{t.0.name}"`, the old
   workaround `(t.0).name` still fine, floats/ranges/suffixes
   unaffected (control examples), and — per DF-159a's origin — a
   named-tuple field after an index (`pair.0.x`).

## Addendum — the trailing-dot float (scope addition, user-approved Aug 6)

Probed and confirmed broken alongside DF-159a: `7.to_string()` fails with
"undefined function to_string", because the scanner accepted a
TRAILING-DOT float. `7.` lexed as a float with no digits after the point
and swallowed the member-access dot.

**The companion rule — LOOKAHEAD, the mirror of the lookback above.** A
`.` encountered while scanning a number continues the float only if the
next character is a DIGIT. Dot-then-anything-else ends the number and
the dot is lexed on its own: a member access (`7.to_string()`), a range
(`1..=9`), or a trailing dot. Same scanner, both lexers, same commit.

Decisions and findings from the implementation:

- **The corpus is clean, so the trailing-dot error is pinned.** A probe
  over all 1460 tracked `.saw` files found ZERO trailing-dot floats,
  zero FLOATs after a DOT, and zero suffixed integers after a DOT —
  nothing in the tree relied on either old behavior.
- **`7.` is now a parse error that names the spelling.** It arrives at
  the parser as INT + DOT, where the postfix `.` branch reported a bare
  "got NEWLINE". With an `IntLiteral` receiver it now reads
  ``Expected field name or tuple index after '.', got NEWLINE — a float
  literal needs a digit after the point (write `7.0`)``. That is the
  only parser change in the brief; `examples/errors/trailing_dot_float.saw`
  pins it.
- **No exponent grammar exists**, so there is no interaction to decide:
  `e` was never scanned as part of a number, and `7e5` is the integer
  `7` followed by the identifier `e5` before and after. `7.e5` follows
  the identifier rule (member access on `7`).
- **The parser already accepted postfix calls on literal primaries** —
  `7.to_string()`, `7.to_string().len()` and `7.5.to_string()` all work
  with the tokens fixed. No parser unit was needed.
- **Design 116's parity test asserted the old behavior** and was
  updated: `selfhost/lexer/tests/ranges.saw` pinned `7.foo` as
  FLOAT `7.` + IDENT, and now pins INT + DOT + IDENT. The "`7.`
  float-prefix behavior" named in the 116 brief is superseded here.
- **The lookback rule reads the previous EMITTED token**, so whitespace
  between the dot and the digits does not matter (`t. 0` is still an
  index). One consequence worth knowing when writing lexer tests: in a
  spliced stream like `"7. 7.5"`, the second number follows a DOT token
  and is therefore an index, not a float.

Tests added for the addendum: `7.to_string()`, `7.5.to_string()`, the
chained `7.to_string().len()`, a suffixed `255u8.to_string()`, the
trailing-dot error case, and the `7e5` control.

## Gates

Full battery via ./.venv/bin/python: test_runner.py (zero xfails),
lexdiff (BOTH sweeps — the whole point), astdiff, irdet --all,
blade_bootstrap, sos_runner, gmgate. Tracker: close DF-159a.

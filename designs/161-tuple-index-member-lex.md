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

## Gates

Full battery via ./.venv/bin/python: test_runner.py (zero xfails),
lexdiff (BOTH sweeps — the whole point), astdiff, irdet --all,
blade_bootstrap, sos_runner, gmgate. Tracker: close DF-159a.

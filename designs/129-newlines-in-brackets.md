# Design 129 — newlines inside brackets

STATUS: LANDED (Aug 5) — rule as proposed, both recommendations adopted (see
Decided). Closed DF-121a. Implemented as a parser-side bracket-depth discipline
in `sawc/parser/` (the lexer is untouched, so lexdiff parity never entered it);
regression tests are `examples/newline_*.saw`; the dogfood rewrap is the
`blade/src/resolver.saw` `visit` signature and its two call sites.

## Problem
A newline anywhere inside a call/parameter list is a parse error
(`Unexpected token: NEWLINE`), so no argument list, collection literal, or
signature can wrap. Concrete costs on record: the DF-121a `assert(cond,
"msg")` hit in the selfhost lexer tests, and `blade/src/resolver.saw:271` —
a 210-character single-line function signature (flagged by the claims
review as the measurable cost of the rule).

## Proposed rule (the conventional one)
NEWLINE tokens are insignificant between an opening bracket and its match:
- `(` `)` — calls, parameter lists, tuple literals/types, grouping
- `[` `]` — collection literals, indexing
- generic `<` `>` — argument/parameter lists ONLY where the parser already
  commits to the generic interpretation (the lexer keeps emitting `<` as an
  operator; suppression is a PARSER-mode decision, so lexdiff parity is
  untouched)
`{` `}` stays newline-significant (blocks and closures are statement
containers; trailing-closure and collection-vs-block ambiguities stay out
of scope).

## Mechanism + constraints
- Parser-side bracket-depth counter that skips NEWLINE while depth > 0 for
  the three bracket kinds — the LEXER does not change (token stream identity
  is the lexdiff parity contract with selfhost/lexer; a lexer-side rule
  would have to be mirrored there for zero benefit).
- Statement-termination semantics elsewhere unchanged; a newline after the
  CLOSING bracket still terminates as today.
- Error quality: an unclosed `(` at EOF should point at the opener (mirror
  the design-119 interpolation-brace precedent), since newline-suppression
  makes runaway-consumption errors otherwise drift to EOF.

## Decided (user, Aug 4)
- **Trailing comma: allowed** `[user]` for `()`/`[]` literals, calls, and
  parameter lists — it is the wrapping style the rule exists to serve. NOT
  for generic `<>` lists (no wrapping idiom served there).
- **`<` suppression applies in BOTH positions** `[user]` — type position and
  expression-position generic calls `f<Int>(x)` — since the parser already
  disambiguates; the risk case `a < b\n > c` never enters generic
  commitment. Comparisons must stay comparisons (test this).

## Shape of the work
parser/core.py newline-skip discipline + opener-anchored unclosed errors;
tests: wrapped calls/params/literals/generics, trailing commas in `()`/`[]`
(and rejected in `<>`), the DF-121a repro compiles,
unclosed-bracket error position, `a < b` comparisons unaffected; rewrap
resolver.saw:271 as the dogfood proof; spec grammar note + skill; DF-121a
closed.

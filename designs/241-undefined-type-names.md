# Design 241 — Undefined Type Names Diagnose, and Adoption Slots Are Const
# Positions

**Status: AUTHORED Aug 21 2026** (lead; both rulings user-made same day).
**Queue: FIRST ON RESUME, before design 205.** Two units, one small branch.

## Unit 1 — DF-225b: an undefined type NAME gets a located diagnostic

The class (entry in designs/todo.md, swept Aug 21 by design 240 item 4): a
name in type position that resolves to nothing is today either a SILENT
OPAQUE TYPE (annotated `let`, struct field — downstream mismatches name a
type that does not exist; how `Float64` masqueraded for months) or an ICE
at codegen (enum payload type, `sizeof<>` argument, function signature —
three positions). Every other undefined-name kind already errors cleanly;
types are the exception.

THE FIX: one diagnostic at type-name resolution, inside the design-194
written-type funnel (obligation 1 satisfied by construction — that funnel
already claims every position a type is written; its docstring names its
entries). Fire when the name is none of: a declared type visible under
design 80/150 rules, an in-scope type parameter, a prelude/builtin name, a
qualified name that resolves. The hard part the brief settles: TYPE
PARAMETERS — the parser leaves them as bare struct-typed names and
`_is_abstract_type_param` disambiguates later, so the check must run where
the current type-parameter set is KNOWN (the funnel's resolution point has
it) and must never fire on a generic extension/method's own parameters,
including design 148 const parameters. Diagnostic shape: located,
`error: undefined type `X``, with a did-you-mean hint only if a cheap
near-match exists (reuse the existing hint machinery; do not build new
fuzzy matching). The pin
(`examples/unknown_type_name_diagnostic.saw`, XFAIL) asserts a located
diagnostic + `EXPECT-ERROR-ABSENT: internal compiler error` and flips with
this unit; extend it (or add siblings) to cover ALL swept positions: let
annotation, struct field, enum payload, `sizeof<>`, function signature,
alias RHS, generic bound, trait requirement signature.

## Unit 2 — DF-240a: adoption slots are FULL const positions (ruled Aug 21)

The ruling: a fixed-width adoption slot is a const position for name
resolution — integer STATICS and raw-backed ENUM CASES both fold there.
This is a deliberate AMENDMENT to design 185 unit 4, not a side effect:
`let mask: UInt8 = Perm.Read | Perm.Write` becomes legal with the result
the backing integer (185's own reading in every const position); the
refusal of operators on enum-typed VALUES outside const/adoption positions
is unchanged. Implementation: design 240 items 1-2's funnel arm gains name
supply — run the const-name stamping (statics + enum cases, the full
`_stamp_const_names` semantics) over the expression BEFORE the fold, at
adoption positions. Mind design 240's recorded mechanism trap: read the
annotation pair, never `resolved_type` (the place lowering unchecks
between front-half passes). Tests: flip
`examples/coercion/const_expression_named_static_operand.saw`; add the
enum-case row (`let mask: UInt8 = Perm.Read | Perm.Write` compiles, value
3; the enum-typed-value refusal outside these positions still pinned by
185's existing tests); update `examples/coercion/INDEX.md` rows. Docs:
LANGUAGE_SPEC's 185 section gains the amendment sentence (adoption slots
join const positions; dated); saw-lang skill if it states the old rule.

## Gates

Compiler branch: per-commit full suite + sos_runner both arches; terminal
full battery. Designs 236/239 + signature-visibility are law in new tests.
Tracker entries close in place; queue lists unnumbered; done_* untouched.

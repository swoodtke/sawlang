# Design 208 — implicit enum members: `.Bad` where the type is in force

**Status: RULED Aug 10 (user, continuing the infer-when-accurate
doctrine: "inferring the enum type from the member ... same as Swift")
+ AUTHORED; queue after 207 (both are inference briefs — serial).
Swift's implicit member expression, adopted: in an expression position
whose EXPECTED TYPE is an enum, `.Bad` resolves to `State.Bad` and
`.ToPickup(o: 3)` constructs the variant, payloads and labels as
normal. Rust deliberately lacks this (qualified paths or `use`-imports
only; the `_::Variant` RFC was never accepted) — this is a
Swift-ergonomics point Saw takes. Patterns are UNTOUCHED: match arms
already bind bare variant names and stay exactly as they are.**

## The rule

The LEADING-DOT spelling, not a bare name: `.Bad` is unambiguous by
construction (no collision with locals, statics, or the weak-qualifier
resolution order — a bare `Bad` would re-open exactly the shadowing
questions designs 100/150 settled). Resolution: the expected type in
force must resolve to an enum (through aliases, through `?`-optionals
to the payload enum per the existing adoption rule’s spirit); `.Member`
then names its variant, with payload construction identical to the
qualified spelling. No expected type, or a non-enum expected type, or
no such member = clean errors naming the qualified spelling.

Positions, v1 — exactly where design 87's expected-type propagation
already carries a type (the funnel exists; process rule 1 applies to
its docstring): annotations' initializers, parameters (call arguments
against declared params), struct-field inits, RETURN position (the
motivating example), default values, value-`if`/`match` arms against
the reconciled type, array/tuple/collection elements with an element
type in force, compound/plain assignment RHS against the target's
type, and `==`/`!=` OPERANDS where the other operand is already
enum-typed (the design-195 operand funnel knows both sides; `if state
== .Good` is the idiom this buys). Generic enums: the expected type
supplies the instantiation (`let w: Wrap<Int> = .Some(v: 5)`), and an
expected BASE with open params defers to 207's argument solver —
conflicts are clean errors.

## Units

1. **Conformance/examples first**: the position matrix above, one
   accept row per position + the error rows (no expected type —
   `let x = .Bad` refused naming `State.Bad`; wrong-type expected;
   unknown member — reuse the existing "has no variant" diagnostic
   family; raw-backed enums unchanged in `as`/`from(raw:)` behavior).
2. **The resolution**: a leading-dot member expression node (parser —
   note the design-161 rule that a float literal needs digits both
   sides already keeps `.5` lexing separate; verify `.Bad` parses
   cleanly after `(`, `,`, `=`, `return`, `->` arms, `==`) resolved in
   the typechecker at the design-87 expected-type funnel; the 195
   operand funnel feeds the comparison case.
3. **Consumer sweep** (additive — expect zero breaks; the sweep is the
   suite plus parser-ambiguity probes: member access `x.Bad`, tuple
   indices `.0`, and float literals must all lex/parse exactly as
   before — the matrix carries a row for each).
4. **Docs**: spec enums + inference sections; skill patterns/enums
   bullets (with the Swift-parity note and the "patterns were already
   bare" clarification); README enums example gains one `.Bad` line.

## Gates

Per-unit commits, full tracked battery each; irdet --all. Lexer parity
(`lexdiff`) matters — the leading-dot token path touches the lexer's
number/dot handling; the selfhost lexer must agree (selfhostlex stage
+ lexdiff both gate it). Anything revealing grammar ambiguity beyond
the matrix STOPS and files.

## Explicitly out

Bare-name members (no leading dot — rejected above); implicit members
for struct statics/inits (Swift allows `.init(...)`/static members —
a separate decision, not taken here; enums only); expected-type-driven
CONSTRUCTOR inference in general (207's noted future step, still its
own brief).

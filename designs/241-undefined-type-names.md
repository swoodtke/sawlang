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

## LANDED Aug 21 2026 (branch `design-241`, two commits)

### Unit 1 — the diagnostic, and the three things it needed

`_gate_resolved_type` (the design-194 funnel's decision procedure) now asks
THREE questions in one order: the hidden-std name (82/194), the imported-but-
not-re-exported name (229), and — last, as the residue — does the name denote a
type at all. `_report_undefined_type_name` / `_type_name_is_defined` are the new
pair; the diagnostic is `error: undefined type \`X\`` with DF-174d's own hint
text (check the spelling, check the import).

WHEN IT DOES NOT FIRE, which is the whole difficulty, since the parser leaves a
type parameter and a typo as the same node:
  * the type parameters in force — `current_type_params` at the funnel proper,
    and the DECLARATION's own list (design 148 const parameters included) at the
    registration entries, which run outside any body;
  * `_unit_type_names`, the names this compilation unit DECLARES, collected
    before registration starts. Registration is ordered and Saw is not, so a
    struct field naming an enum is judged three passes before that enum exists.
    Trait associated-type names and an extension's `type X = ...` assignments
    ride the same set, since both denote a type and neither lands in a table;
  * the namespace (imports + everything registered), and `Optional`, the one
    prelude spelling resolved rather than registered (DF-174d);
  * a bare name in a `<...>` ARGUMENT that names a const-foldable `static`
    (`Ring<CAP>`), because `_fold_const_type_args_in_program` turns that node
    into a value only AFTER the registration passes this funnel fires from;
  * THE SCOPE FENCE, which the corpus found: only the file currently being
    checked may be judged. A foreign generic signature's own parameter reaches
    resolution in the CALLER's body — `m.lock({ … })` against std's
    `func lock<R>(&self, body: (&var T) sync -> R)` resolves that `R` while
    checking `main` — where `R` is nothing. This is why the pre-existing
    `<std>`-source exemption existed at all; generalizing it to "the file being
    checked" covers the cross-USER-module case the old test did not.

THREE SUPPORTING CHANGES:
  * `_register_trait` becomes the funnel's FIFTH declaration-slot entry (the
    docstring's entry list is updated). A requirement's parameter and return
    types are stored raw on the `TraitMethodSymbol` and nothing resolved them,
    which is why that position was silent. Its scope is the trait's own type
    parameters plus its associated types, own and inherited, plus each method's.
  * `_register_extension` now states its type parameters while it resolves its
    method signatures (saved/restored around the loop). It is the one place a
    generic signature is resolved OUTSIDE a body — a free generic function
    defers resolution to its body check, where the set is built — so
    `extension Wrap<T> { func f<U>(...) }` had nothing telling the checker that
    `T` and `U` are parameters. This also gives `_funcpointer_arg_is_abstract`
    and every other `current_type_params` reader the right answer there.
  * DF-174d's `_check_type_name_resolves` / `_unknown_generic_type_name` are
    RETIRED (obligation 1). They answered the same question for the one shape
    decidable with no scope in hand — a name carrying type ARGUMENTS — from two
    hand-placed call sites; with both live, one name printed two diagnostics.
    `examples/errors/unknown_generic_type_name.saw` keeps its repro and expects
    the funnel's wording.

POSITION MATRIX, all nine rows in one pin
(`examples/unknown_type_name_diagnostic.saw`, un-XFAIL'd): alias RHS, struct
field, enum case payload, trait requirement signature, function parameter,
function return, `let` annotation, `sizeof<>` argument — plus the generic BOUND
row, which already had a clean diagnostic and is pinned here so the matrix is
whole. Before: three ICEs with no location, one ICE with a location, three
silent opaque types, one silently accepted program.

BOUNDARY, deliberately: the diagnostic does not suppress the downstream
cascade. `let x: Nonesuch = 1` reports the undefined type AND the assignment
mismatch it causes; poisoning the opaque type would be a separate change with
its own blast radius.

### Unit 2 — adoption slots are full const positions

One line at design 240's own funnel arm: `_fold_const_expression_into` runs
`_stamp_const_names` over the expression before calling `const_eval`. That is
the whole fix — the walk is the same one every other const position uses, so
statics and raw-backed enum cases fold here on identical terms, and the range
check design 240 already installed applies to the result.

The 185-unit-4 refusal is untouched because `_check_binary_op` answers from the
`const_folded_value` + `expected_type` stamp pair and never descends into the
operands once the funnel has folded. Outside an adoption or const position the
funnel arm never runs, the operands are enum-typed values, and the refusal is
the same one `enum_bitwise_value_error.saw` pins.

Stamping an expression that turns out NOT to be constant is safe: the walk
writes `const_static_value` / `enum_raw_value` onto its own nodes, `const_eval`
is the only reader of either, and `LIMIT + n` still raises and falls through.

SCOPE: the arm folds a `BinaryOp` or a `~`/negated `UnaryOp`, so a BARE
`Perm.Read` at a `UInt8` slot is still the ordinary enum-vs-integer mismatch and
still wants `Perm.Read as UInt8`. That is unchanged by the ruling, which is
about the names a constant EXPRESSION may read.

Tests: `examples/coercion/const_expression_named_static_operand.saw` un-XFAIL'd,
`examples/coercion/const_expression_named_enum_case_operand.saw` added (the
accept side plus the out-of-range refusal), `examples/coercion/INDEX.md` rows
flipped. Docs: LANGUAGE_SPEC's flag-enum section and the constant-grammar
section both carry the dated amendment; the saw-lang skill's two statements of
the old rule are updated.

FIXED ON DISCOVERY (unambiguous, DF-225c was ruled Aug 20): eleven
LANGUAGE_SPEC worked-example occurrences of `Float64` still named a type that
does not exist — the doc half recorded as done Aug 20 missed them, and unit 1
turns each into a hard error rather than a cascade. They now read `Float`. The
two remaining occurrences are prose ABOUT the name and are correct.

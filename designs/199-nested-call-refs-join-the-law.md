# Design 199 — nested-call references join the Law of Exclusivity

**Status: RULED + AUTHORED Aug 10 (morning review), ready to queue.
Closes DF-188j with the ruling: a by-reference argument created by a
NESTED call in the same argument list joins the OUTER call's access
set, so overlapping roots are an exclusivity error on every copy tier —
mirroring the place rule design 188 unit 2 already landed. Disjoint
roots stay legal (`f(&var x, g(&y))` compiles). Today
`sink(&var p.a, reset(&var p))` compiles with no place in sight and the
answer depends on argument evaluation order (probed: a=107 b=200);
memory-safe but order-dependent, which is exactly what the Law exists
to prevent — and the same shape spelled through an accessor is already
refused, an inconsistency with no principle behind it.**

## Units

1. **Conformance rows first (obligation 3 — exclusivity is a safety
   surface).** X-family rows: the DF-188j shape (reject), the disjoint
   shape (accept), a nested call whose ref targets a DIFFERENT root
   than every sibling (accept), the receiver-position variant
   (`p.m(reset(&var p))` — probe whether the receiver borrow already
   catches it), and the two-nested-calls-one-root shape (reject).
2. **Consumer sweep (obligation 2 — this flips legal-today code).**
   Sweep examples/ + sawc/std + blade/ + libs/ + devtools/ for
   argument lists where a `&`/`&var` argument's root overlaps a
   nested call's `&`/`&var` argument root. Record the list; fix
   offenders in the landing (each is order-dependent code and each fix
   is a hoisted `let`). Expect few; `Vector.fold`'s
   `acc = combine(move acc, ...)` shape is a MOVE, not a borrow, and
   is untouched — 193 u4 already proved that distinction matters.
3. **The check.** Extend 193 u4's `_check_call_exclusivity` funnel:
   argument collection descends into nested calls' by-ref arguments
   (via the `ast_walk` shared walk), each joining the outer access set
   with its own path root. Same overlap test, same diagnostic family,
   naming the two references and their one root. Docstring's entry
   list updates (process rule 1).
4. **Pin + docs.** The DF-188j repro lands as the reject conformance
   row; spec (Law of Exclusivity section: an argument's borrow extends
   over the whole call expression, nested calls included) + skill
   bullet under the 188 exclusivity entry.

## Gates

Per-unit commits, tracked battery each; irdet --all (typechecker-only,
byte-identity expected). The sweep list is the review surface.

## Consumer sweep — the record (unit 2, obligation 2)

Run Aug 10, BEFORE the flip. This rule refuses code that compiles today,
so the sweep is the review surface and it is recorded here rather than
only in a commit message.

**Method — two passes, because a grep cannot see nesting.** The first is
a parse-only AST scan of every tracked `.saw` file (`git ls-files
'*.saw'`, 1890 files, ZERO parse failures outside the `examples/`
parse-error fixtures): for each call it collects the by-reference
accesses the new access set holds — the receiver, the direct `&`/`&var`
arguments, and every `&`/`&var` written strictly BELOW an argument — and
flags the call when two of them share a ROOT and at least one is
mutable. Root granularity, so it deliberately OVER-reports against the
real path test. The second pass is the compiler itself, with the unit-3
check in the working tree, over every corpus that compiles Saw.

**Population.** 262 argument lists in the tree create a reference inside
a nested call at all. Almost all are one shared `&` under an `assert`
comparison (`assert(kind(&a, 16) == TokenKind.CaretAssign, "^=")` in
`selfhost/lexer/tests/`), which is a single access and cannot conflict
with anything.

**Plausible conflicts: 7, and every one is a test of this rule or its
neighbours.** Nothing in `sawc/std`, `blade/` (incl. `blade/tests`),
`libs/` (incl. `libs/*/tests`), `devtools/`, `sos/` or `selfhost/`.

| Site | Disposition |
|------|-------------|
| `examples/conformance/X41_nested_call_ref_overlaps_sibling.saw:32` | this brief's reject row |
| `examples/conformance/X44_nested_call_ref_overlaps_receiver.saw:32` | this brief's reject row |
| `examples/conformance/X45_two_nested_calls_one_root.saw:29` (two accesses) | this brief's reject row |
| `examples/conformance/X43_nested_ref_disjoint_from_every_sibling.saw:39` | this brief's ACCEPT row — `scale(&var r.b, bump(&var r.a))`, over-reported by root granularity and correctly accepted by the path test |
| `examples/conformance/Z03_replace_container_during_window.saw:17` | already an error row (design 188 unit 2's place-window half) |
| `examples/errors/df151j_tuple_element_exclusivity.saw:20` | already an error row (DF-151j) |

**Compile pass, with the check in.** `suite` (1696 tests), `bootstrap`
(sawc builds blade, blade builds and tests blade, then `blade test` in
`libs/toml` and `libs/semver` — which is what typechecks those test
trees), `sos` (32 tests, riscv32 + arm64), `irdet --all`, `bench`,
`lexdiff`, `astdiff`, `astgraft`, `ircontract`, `preludegate`, `abidoc`,
`bttable`, `fuzz`, `gmgate`, `icebreadcrumb`: all GREEN. The only
failures anywhere were the three XPASS the brief's own unit-1 pins
expect.

**Offenders fixed: none — there were none.** No hoisted `let` is owed
anywhere in the tree. The rule's blast radius on existing code is empty,
which is the answer the ruling was betting on and the reason it could be
made without a grandfathering clause.

`Vector.fold`'s `acc = combine(move acc, e)` is untouched as the brief
predicted: a `move` is not a borrow, and the scan classifies it as
neither of the two by-reference kinds.

## Explicitly out

Borrow lifetimes/regions in general (the Law stays per-statement); the
DF-176c receiver-copy half (design 200); any place-machinery change
(188/193 already cover places).

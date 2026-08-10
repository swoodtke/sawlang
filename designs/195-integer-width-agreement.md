# Design 195 — integer width agreement: operands match, transfers widen

**Status: RULED + AUTHORED Aug 10, ready to queue. Fixes one confirmed
WRONG ANSWER (DF-192g), one ICE (DF-192f), and the silent signedness
mix the ruling discussion's probe found (`Int + UInt` compiles today).
Typechecker internals — keep serial with anything else touching them.**

## Decision [user, Aug 10]

Two rules, both reusing machinery the language already has:

1. **All typed operands of an operation must be the SAME type.** A
   binary/comparison operator over two typed integer operands of
   different width OR different signedness is a clean error naming both
   types and the two ways out (an explicit `as`/`from(truncating:)`
   conversion, or dropping a suffix so the literal adopts). Implicit
   promotion happens ONLY from bare literals, which adopt the other
   operand's type exactly as documented today — `n * 2` stays legal,
   `n * 2i16` and `i + u` do not. No promotion ladder: a binop has two
   peers, and picking a winner is policy Saw does not adopt.
2. **Value-branch arms are TRANSFERS.** Each arm of a value
   `if`/`match` (and each `??` operand, and every position the matrix
   below names) routes through the existing value-transfer checkpoint
   against the reconciled type — so lossless widening (same-sign up,
   unsigned into strictly-wider signed) is legal there exactly as it is
   at a `return` or a `let`, and a narrowing or sign-flip arm is the
   ordinary transfer error. `if a > 0 { 11 } else { 7i16 }` in an
   `-> Int` function is LEGAL and prints 7 on the else path. Bare
   literals keep adopting in arm position (unchanged), so the same
   arms at `-> Int16` stay legal too; only a typed arm that cannot
   widen losslessly (an `11i64` arm at `-> Int16`) is the transfer
   error.

Rationale recorded from the ruling discussion: transfer sites already
widen losslessly today (probed: `let wide: Int = narrow16` and
`return 7i16` from `-> Int` both compile and answer correctly), so arms
joining them adds zero new policy; operands staying strict matches
exact-type overloads and design 170's stance that arithmetic width
changes are written, not inferred.

## The position matrix (brief obligation 1)

One funnel for rule 1 — a single operand-agreement check the operator
checkpoint calls, its docstring naming every entry — and rule 2 rides
the EXISTING transfer funnel (`_check_value_transfer`), extended to the
arm positions. Rows, each with a conformance row in unit 1:

| # | position | rule | today |
|---|---|---|---|
| 1 | arith binop, mixed width (`n * 2i16`) | error (1) | ICE — DF-192f |
| 2 | arith binop, same-width sign mix (`i + u`) | error (1) | compiles silently (probe, Aug 10) |
| 3 | comparison, mixed width (`n < m16`) | error (1) | unprobed — probe in-unit |
| 4 | comparison, sign mix (`i < u`) | error (1) | unprobed — probe in-unit |
| 5 | wrapping ops `&+ &- &*`, mixed | error (1) | unprobed — probe in-unit |
| 6 | shift counts | EXEMPT — a shift's count is not required to match the shiftee's width today; keep, document | works |
| 7 | value-`if` arms, widenable (`{ 11 } else { 7i16 }` at `-> Int`) | legal, widens (2) | WRONG ANSWER — DF-192g |
| 8 | value-`if` arms, narrowing/sign-flip typed arm | transfer error (2) | unprobed — probe in-unit |
| 9 | value-`match` arms, same two shapes | same as 7/8 | unprobed |
| 10 | `??` RHS vs LHS payload | transfer rule (2) | unprobed |
| 11 | range bounds `a..b`, mixed typed | error (1) | unprobed |
| 12 | bare-literal adoption in every row above | UNCHANGED — adopts, range-checked | works |

Every "unprobed" row gets probed before its fix lands; a row that turns
out already-correct becomes an accept/reject conformance row with no
code change.

## Units

1. **Conformance rows FIRST (brief obligation 3):** the matrix above as
   `examples/conformance/` rows (next free W ids) + INDEX entries,
   XFAIL-cited where the fix has not landed yet within this brief's own
   sequence.
2. **Rule 1 funnel:** the operand-agreement check at the operator
   checkpoint (arith, comparison, wrapping, range bounds), docstring
   naming its entries. Closes DF-192f (row 1) + rows 2-5, 11. Error
   text names both types + the two outs.
3. **Rule 2 arms-as-transfers:** route value-`if`/`match` arm
   reconciliation and `??` operands through `_check_value_transfer`
   against the reconciled type; the codegen phi takes the widened
   value. Closes DF-192g (row 7), rows 8-10.
4. **Pins + fuzz ledger:** `binop_mixed_width_operands.saw` flips to a
   passing error test; `if_value_mismatched_width_arms.saw` re-authors
   to the RULING (EXPECT: success, prints 11 then 7 — its comment
   already names this flip); delete the DF-192f signature from
   `tools/sawfuzz_known.txt` in the same landing.
5. **Consumer sweep (brief obligation 2) + docs:** rows 1-5/11 flip
   "compiles today" code to errors — sweep examples/ + sawc/std +
   blade/ + libs/ + devtools/ for mixed TYPED binops (the suite is the
   backstop; record the sweep in the commit). Spec (integer conversion
   + operators sections) + saw-lang skill state both rules; saw-docs
   voice.

## Gates

Per-unit commits, full tracked battery each (`tools/battery.sh`), zero
uncited xfails. irdet --all matters for unit 3 (phi lowering changes).
Any row whose probe reveals a shape needing a NEW ruling stops and
files rather than guessing.

## Explicitly out

Any promotion ladder (ruled out); float/integer mixing (no implicit
conversion exists, unchanged); `as`/`from` semantics (design 170,
untouched); the DF-192d duplicate-arm question (separate ruling).

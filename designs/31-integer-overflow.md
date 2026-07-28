# Design 31 — Integer overflow: checked by default, explicit wrap operators

**Status: DECIDED (Jul 28, user).** Source: tracker D1 (critique concern
5; brief 05 parked INT_MIN/-1 pending this). Rulings:

1. **Overflow panics — always, in every profile.** `+`, `-`, `*` on all
   integer types (signed and unsigned), unary negation of a signed
   minimum, and `INT_MIN / -1` panic with "integer overflow" through the
   standard panic path (`saw_panic` seam — works freestanding). Same
   semantics at -O0 and the default O1 pipeline: no build-dependent
   meaning. Joins the existing panic family (div-by-zero, force-unwrap,
   `try!`).
2. **Intentional wraparound is spelled with Swift-style wrapping
   operators: `&+`, `&-`, `&*`** — defined two's-complement wrap, no
   check, integer types only, same precedence as their checked
   counterparts. Lexed as single tokens (no interior whitespace);
   unambiguous vs call-site `&x` (those are unary/prefix positions) and
   vs future bitwise `&` (binary `&` alone remains available).
   Named `wrapping_*`/`checked_*` methods explicitly NOT shipped now —
   revisit if operator-free contexts demand them.

## Implementation items

1. **Checked arithmetic codegen.** Replace plain add/sub/mul for integer
   types with `llvm.{s,u}{add,sub,mul}.with.overflow` + branch-to-panic
   (reuse the brief-05 div-by-zero panic-block pattern in
   codegen/operators.py). Unary `-x` on signed types: overflow check for
   negating the minimum. Float ops untouched.
2. **`INT_MIN / -1`** check added beside the existing zero-divisor check
   (both div and mod; C UB case — for `%` the mathematically-zero result
   is fine to define via the same panic for consistency with division;
   state the choice in the report).
3. **Wrapping operators end to end.** Lexer tokens `&+ &- &*`; parser at
   the same precedence tier as `+ - *`; typechecker: integer operands
   only (error otherwise, including Float); codegen: plain wrap-defined
   add/sub/mul. Probe interaction with existing uses of `&`: call-site
   reference args (`foo(&x)`) and `&var` must be unaffected — add a
   parser test mixing them in one expression.
4. **Boundary tests** (panic family + wrap family): `Int.max + 1`-style
   via literal boundary values (probe whether Int.max/min constants
   exist; if not, use literals — 9223372036854775807 etc. — and note
   whether the lexer accepts Int.min's magnitude), signed and at least
   one unsigned type, mul overflow, `Int.min / -1`, unary `-Int.min`;
   `&+`/`&-`/`&*` wrapping correctly at the same boundaries; ordinary
   arithmetic acceptance unchanged. Check the existing suite for tests
   that accidentally rely on silent wrap and fix them honestly (report
   any found).
5. **Docs.** LANGUAGE_SPEC.md: arithmetic semantics subsection (overflow
   panics; wrap operators; div/mod rules incl. INT_MIN/-1) + operators
   appendix row. CLAUDE.md: replace "Integer overflow is unspecified
   (open question)" with the decided rule.

## Hazards
Every integer binary op in every existing test now takes the checked
path — the full suite is the correctness oracle and also a smoke
perf-check (note suite wall-clock before/after in the report; expect
noise-level change). Loop induction variables (`for i in 0..n`) go
through the same codegen — verify range-loop internals don't
double-check or panic spuriously at the boundary (`0..Int.max`-style
probe if cheap).

## Report back
Per item: mechanism, verification. The `%` INT_MIN/-1 choice. Any
wrap-reliant tests found. Suite wall-clock before/after. Deviations;
non-allowlisted commands.

# Design 227 — the write-target funnel: DF-225i/j/k/l

**Status: AUTHORED Aug 15 from the DF-225g obligation-4 sweep
(`.build/scratch/sweep225g/RESULTS.md`, probes p01-p61, GITIGNORED — the
matrices below are its findings and the fix's test plan). No rulings
needed; two of the four findings are SOUNDNESS, which puts this at the
front of the compiler queue. The DF-225g carve-out itself is CLOSED
not-a-bug (design 200's ruled behavior, M32-pinned) — its accept table is
this brief's must-not-flip regression set.**

## The findings

- **DF-225i (SOUNDNESS)** — compound assignment skips design 193 unit 4's
  write-path RHS-exclusivity check: `b.n += grow(b: &var b)` compiles and
  silently LOSES grow's write (p21 prints 3; plain twin p20 refused with
  the full teaching diagnostic). statements.py:2269 calls the check, the
  compound path :2756 does not — while the check's own docstring claims
  covered-by-construction with two named entry points. Compound is worse
  than plain: it also READS the target, so the overlap is read+write
  against an exclusive borrow.
- **DF-225j (SOUNDNESS)** — `let`-immutability of INLINE array storage is
  shape-dependent: only literal `ident[i]` is protected. `a[0].n`
  (compound), `a[0].0` (compound), `a[0][0]` (both spellings),
  `h.arr[0]` (both) all write a `let` — and the sharpest cells (p54/p60)
  mutate the caller's inline array through a SHARED `&` parameter, the
  exact storage class the `&self` spelling refuses (p61). Mechanism: two
  lvalue-root walks each stop one hop short —
  `_assign_target_immutable_array` (statements.py:1666) requires a bare
  Identifier container; `_assign_target_immutable_struct_root` (:1694)
  breaks at the first ArrayIndex. The plain rows are NOT
  compound-specific.
- **DF-225k** — `self.c?.n = 99` in a `&self` method is a SILENT NO-OP
  (p50; the `!` sibling refused). `_check_chain_assign_head_mutable`
  (expressions.py:6965) defers SelfExpr to "governed by &var self" and
  nothing downstream governs it — DF-175a's vanishing-write class, fifth
  spelling.
- **DF-225l** — `o?.n += 5` is a parse error while `o?.n = 5` works:
  parser/statements.py:205 routes OptionalEvalExpr to OptionalChainAssign
  only on the plain branch.

## Units

**Unit 0 — the DF-225j consumer sweep (obligation 2).** Census every
tracked `.saw` for writes whose target chains through an ArrayIndex to a
`let` or shared-`&` root (the shapes p27/p28/p54/p55/p57/p59/p60 accept
today), compile-verify each hit's shape. A HIT means in-tree code relies
on a soundness hole — STOP and report it for triage before unit 2 lands;
zero hits (expected — the suite is green with these unwritten) is the
recorded result.

**Unit 1 — rows first (obligation 3; this is a safety surface).**
Conformance rows for every matrix cell, cited-XFAIL-pinned before the
fixes: the p20/p21 exclusivity pair; the twelve inline-immutability
cells (six shapes × plain/compound, incl. the shared-`&`-param rows); the
p50/p51 chain-assign pair; the p30/p31 parser pair. PLUS the
must-not-flip accept pins: the section-1 carve-out table
(p01/p06/p10/p32/p33/p35/p48 accepted; p04/p61 refused) — extend
M31/M32's rows where they don't already cover a spelling.

**Unit 2 — the write-target funnel (obligation 1).** Extract
`_check_assign_statement`'s guard prelude (statements.py:2229-2269 —
static root, capture write, shared-self write, task-borrow write, RHS
exclusivity, both immutable-root walks) into ONE
`_check_write_target(target, line, col, compound:)` whose docstring
NAMES its entry points: `_check_assign_statement`,
`_check_compound_assign_statement`, `_check_optional_chain_assign`,
`_check_place_target_assign`. Fixes DF-225i, DF-225j's compound rows,
and DF-225k (the chain-assign path now asks the shared-self rule).

**Unit 3 — one root walk.** Merge `_assign_target_immutable_array` +
`_assign_target_immutable_struct_root` into one walk transparent through
MemberAccess/TupleIndex/ArrayIndex/ForceUnwrap (the shape
`_self_storage_type` :1954-1972 already has), returning
(root, mutability). Fixes DF-225j's plain rows. The design-200
indirection carve-out is UNTOUCHED — heap-reaching hops still stop the
walk exactly as ruled; the carve-out pins prove it.

**Unit 4 — the parser hoist.** OptionalEvalExpr recognized above the
plain/compound split (parser/statements.py:205) → DF-225l; the compound
chain-assign then flows through unit 2's funnel like every other write.

OUT OF SCOPE: DF-224a's G3 (the transform's compound ANF arm — design
224's territory); the sweep's unprobed sibling classes (DestructuringLet,
LendStatement, IfLetExpr) — noted for a future census, not this brief.

## Gates

Per-unit full suite; unit 1's pins flip across units 2-4 (markers off in
the fixing commit); terminal gate the full tracked battery. The carve-out
accept pins must hold at every commit — a flip there is a STOP (it means
the funnel reached ruled design-200 territory).

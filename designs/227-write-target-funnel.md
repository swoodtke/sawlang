# Design 227 — the write-target funnel: DF-225i/j/k/l

**BUILT Aug 15, five commits, suite 1873 passed / 25 xfailed (baseline
1862/25; the four cited pins flipped and eleven tests are new). What landed,
against the units below:**

- **Unit 0 (census): ZERO.** 96 tracked writes chain through an ArrayIndex, 26
  of them from a non-mutable or non-binding root, and every one stops at an
  indirection the merged walk must not cross — `p[0].field` through an
  `UnsafePointer` (the runtime's job/reactor/proc records, taskgroup's
  intrusive list), a `Vector`/`Map` element the place system already refuses by
  name, or a module `static`. No tracked `.saw` writes through a `self`-rooted
  optional chain at all, so DF-225k's fix reaches nothing existing either.
- **Unit 1:** rows M37 (the twelve-cell inline matrix), M38, M39, M40 as cited
  XFAIL pins; M41/M42 as the must-not-flip carve-out pair. All four pins
  flipped in the units below, markers off in the fixing commits.
- **Unit 2:** `_check_write_target(target, line, column, compound:)`, six
  questions, entry points named in its docstring —
  `_check_assign_statement`, `_check_compound_assign_statement`,
  `_check_optional_chain_assign` (with `immutable_root=False`, since design
  111's head check owns that question there) and `_check_place_target_assign`,
  an ARM of the first that inherits the call. Closed DF-225i and DF-225k, plus
  four of DF-225j's twelve cells. `_check_assign_rhs_exclusivity` is gone as a
  separate entry; `_self_storage_type` gained BindOptional/OptionalEvalExpr
  transparency. The immutable-root question is asked only THROUGH a hop — a
  write of the binding itself keeps the target-shape arms' diagnostics.
- **Unit 3:** `_immutable_lvalue_root` replaces both old walks, transparent
  through MemberAccess/TupleIndex/ForceUnwrap/BindOptional/ArrayIndex and
  type-directed at the ArrayIndex hop, which is exactly where design 200's
  carve-out lives. The three RECEIVER sites (a `&var self` call, an exclusive
  place window, `take()`) ask the same walk now, which found two unprobed
  siblings — rows M43 (`o!.n = 5` on a `let`) and M44 (`h.cells[0].bump()`).
- **Unit 4:** the parser hoist plus `OptionalChainAssign.op`, carried through
  the typechecker (operand rules shared with the compound statement via
  `_check_compound_operands`), codegen, `place_uses` and the coro transform.
  BOUNDARY: a compound assignment whose RHS suspends is refused cleanly —
  DF-224a's G3, pinned as an error test that names what it becomes when 224
  fixes it.

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

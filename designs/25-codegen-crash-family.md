# Design Brief 25 — Codegen crash family + noalias

**Source:** tech-debt ledger crashes + small logged follow-ups.
**Exit criteria:** `nested_if_iflet_tail` and `field_assign_through_ref_param`
XFAILs flip (markers removed); the bare-return-in-main and sizeof items get
verify-twice tests + fixes; noalias stretch landed; full suite green.

## Items

### 1. Nested no-else `if` as if-let branch tail (SSA dominance crash)
`codegen` emits an undominated store ("Instruction does not dominate all
uses") for a valid `Int?` program. Root-cause in the if/if-let expression
lowering (`codegen/conditionals.py`) — the result-slot store for the
valueless path doesn't dominate the merge. Fix via entry-block result
alloca + stores on every path (the `_entry_alloca` idiom) rather than phi
gymnastics. Verify with the xfail's exact repro plus `-O0`.

### 2. Field assignment through `&var` struct param
`r.field = 5` where `r: &var Box` raises "Cannot determine struct type for
field assignment" (`codegen/statements.py` — the struct-type lookup doesn't
dereference the reference). Fix the lookup to unwrap REFERENCE types (and
verify nested: `r.inner.field = v` through the ref). Flips the xfail.

### 3. Bare `return` in `main` (brief-15 finding)
`main` lowers to i32 but a bare `return` emits `ret void` → crash.
Verify-twice test, then fix: bare return in `main` emits `ret i32 0`
(matching the implicit-fallthrough behavior).

### 4. `sizeof` error-handler ErrorKind typo (brief-20 finding)
`typechecker/expressions.py` references nonexistent `ErrorKind.TYPE_ERROR`
(correct: `TYPE_MISMATCH`). Fix; add the error test that exercises that
handler path (whatever input reaches it — probe; if unreachable, delete
the dead branch instead and say so).

### 5. `noalias` on `&var` parameters (brief-10 stretch, now unblocked)
With static exclusivity guaranteeing non-aliased `&var` params, mark them
`noalias` in function/method/closure param emission. Verify via
`--emit-ir` (attribute present) and a full-suite run under O1 (the suite
is the miscompile oracle — if ANY test changes behavior, the exclusivity
guarantee has a hole; report it as a finding, don't paper over).

## Report back
Per item: root cause confirmed, fix, verification. Item 5's O1 sweep
verdict is the interesting one — state it explicitly. Deviations;
non-allowlisted commands.

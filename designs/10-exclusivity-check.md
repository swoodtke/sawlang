# Design Brief 10 — Static exclusivity check for `&var`

**Source:** the DECISION in `designs/08-var-exclusivity.md` (option A as
refined) — read it first; it is the semantic spec, including the soundness
argument (no-escape references ⇒ call-site checking suffices) and the three
invariant-preserving constraints.
**Prerequisite:** brief 09 (Copy trait family) must land first — this brief
edits the same typechecker call-argument paths.
**Rule being implemented — many readers XOR one writer, per call:** an access
path passed mutably (`&var x`, or the receiver of a `var self` method) must be
disjoint from every other by-reference path in the same call. Immutable `&`
paths may overlap each other freely.

## Work items

### 1. Access-path model (typechecker)
A small value: root (local/param name, or `self`) + projection list, where a
projection is `.field`, `.N` (tuple index), or `[i]` with `i` either a
compile-time constant or DYNAMIC. Build one from the expression under a
`ReferenceExpr` (and from a mutable method receiver). Non-path expressions
(call results, literals) cannot appear under `&`/`&var` — if the parser
currently allows that, reject with a clear error and note it.

Overlap(p, q): different roots → disjoint. Same root → walk projections in
parallel: differing fields / differing tuple indices / differing *constant*
array indices at the same position → disjoint; a DYNAMIC index position
overlaps anything at that position; running out of projections on either side
(prefix) → overlap.

### 2. The call-site check
In the typechecker's call-argument walk (the same traversal the value-transfer
checkpoint hooks — function calls, method calls, init calls, closure-variable
calls), collect per call:
- mutable paths: every `&var` argument + the receiver of a `var self` method;
- immutable paths: every `&` argument;
- moved paths: every `move x` argument;
- (by-value arguments: NOT collected — snapshot semantics, see item 4).

Errors:
- a mutable path overlapping ANY other collected path (mutable, immutable, or
  moved): `exclusive access violation: \`<path>\` is passed as \`&var\` while
  also being accessed in the same call` + hint about disjoint fields being
  allowed;
- a moved path overlapping any reference path (either direction):
  `cannot \`move\` \`<path>\` while it is also passed by reference in the same
  call`.
Immutable×immutable overlap: explicitly no error. Dynamic-index conservatism
applies only when one side is mutable/moved (per the decision).

### 3. Forwarding is free — but verify it
No inter-procedural work: inside a callee, its `var` params are distinct
roots, and the caller's own call-site check is what prevents aliased roots
from arriving. Add the forwarding test (outer forwards two `var` params to
`inner(&a, &b)`; caller does `outer(&x, &x)`) and confirm the error surfaces
at the `outer(&x, &x)` call site.

### 4. Spec: argument evaluation order
Add to LANGUAGE_SPEC.md (new short subsection near calls): arguments evaluate
left-to-right, method receiver before arguments; by-value arguments are
copied/moved at evaluation time (snapshot), which is what makes a by-value
argument overlapping a `&var` well-defined. Keep it to a few sentences; also
add the exclusivity rule itself to the spec's references section, citing the
reader/writer law. (Spec is drifty overall — concern 4 — so scope this to
inserting the two new subsections, not reconciling the document.)

### 5. Optional stretch — `noalias` (skip if anything above runs long)
With the check in place, mark `&var`-backed LLVM params `noalias` in codegen
and verify with `--emit-ir` on a scratch program. Separate commit; skip
freely — the safety win doesn't depend on it.

## Tests
Rejections (`// EXPECT: error` + message substrings):
- `exclusivity_swap_same_var.saw` — `swap(&x, &x)`
- `exclusivity_parent_child.saw` — `f(&var p, &p.x)` and the reverse order
- `exclusivity_var_self_receiver.saw` — `v.mutate(&v)`-shaped (receiver vs arg)
- `exclusivity_forwarding.saw` — the item-3 case, error at outer call site
- `exclusivity_dynamic_index.saw` — `f(&var a[i], &a[j])`
- `exclusivity_move_and_ref.saw` — `f(move x, &x)`
Acceptances (`// EXPECT: success` with output):
- `exclusivity_disjoint_fields.saw` — `f(&var p.x, &p.y)` (also `&var`+`&var`
  on disjoint fields)
- `exclusivity_shared_reads.saw` — `f(&x, &x)` both immutable
- `exclusivity_const_indices.saw` — `f(&var a[0], &a[1])`
- `exclusivity_byvalue_snapshot.saw` — `f(v, &var v)` runs; output asserts the
  by-value side saw the pre-call snapshot (this pins evaluation order).

## Report back
Standard: the path model's final shape, where the check hooks relative to
`_check_value_transfer`, any parser surprises under `&`, whether the
by-value-snapshot test exposed evaluation-order bugs in codegen (report,
don't silently fix unrelated ones), stretch-item status, deviations.

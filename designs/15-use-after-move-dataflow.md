# Design Brief 15 — Use-after-move dataflow

**Source:** the use-after-move gap noted in briefs 03 and 12 (`todo_jul26.md`
follow-ups). Read the brief-03 design (`designs/03`) for why move-recording
was gated to let/assign: the tracker is a single flat set with no
scope/function lifetime, and extending it naively broke 148 tests.
**Exit criteria:** `errors/use_after_move_call_arg.saw` and
`errors/use_after_move_field_init.saw` flip to passing (markers removed);
the new tests below pass; full suite green; no other xfail flips
(investigate if one does).

## Semantics to implement (the spec of the analysis)

Per-function, scope-aware **may-move** analysis in the typechecker:

1. **Function-local.** State is created at function/method/closure-body entry
   and discarded at exit. Same-named locals in different functions can never
   interact (the flat-set bug).
2. **Per-binding, not per-name.** A new `let`/`var` declaration *shadows*:
   it clears moved-state for that name in the new binding's scope; scope exit
   restores the outer binding's state. (If the existing `Scope` machinery in
   `typechecker/core.py` gives you binding identity, key on that; otherwise
   name + scope-depth with save/restore at scope boundaries is acceptable.)
3. **Revival by assignment.** Assigning to a moved `var` (`v = fresh()`)
   clears its moved-state. The assignment RHS is still checked first (a moved
   var can't appear in its own revival RHS).
4. **Every transfer site records.** Remove the `track_move` gating in
   `_check_value_transfer` — call arguments, struct-field init, enum
   payloads, array/tuple elements, and explicit/implicit returns all record
   a `move x` into the state, in addition to today's let/assign.
5. **Uses that error on a moved binding:** identifier reads, `move x` again
   (double-move), `&x`/`&var x` references, method receivers. Assignment TO
   the binding is not a use (rule 3). Reuse the existing "use of moved
   variable" diagnostic; add a "moved here" hint with the move's line if the
   error machinery makes that cheap.
6. **Branches merge as union (may-moved), excluding diverged paths.** After
   `if`/`else`, `match`, `if let`/`guard let`: a binding is moved if ANY
   completed branch moved it. A branch that *diverges* (ends in `return`,
   `break`, `continue`, or a panic-typed expression) does NOT contribute to
   the merge — this is what keeps the idiom
   `guard let x = ... else { consume(move v); return }` from poisoning the
   fall-through. The typechecker already tracks whether blocks
   return-with-value; probe how divergence is visible and use it.
7. **Loops are may-repeat.** A `move` of a binding declared OUTSIDE the loop,
   inside the loop body, is an error at the move site — unless the binding is
   definitely reassigned on every path from the move to the end of the body.
   Simplest sound implementation: check the body with entry-state = (state
   after one abstract iteration merged with the initial state); if that's too
   invasive, the conservative "outer binding moved in loop body without
   definite reassignment before body end → error immediately" rule is
   acceptable — document which you shipped.
8. **Out of scope:** partial moves of fields (`move p.x`) — if the parser
   even accepts it, keep whatever behavior exists and note it; `&var`
   reference params (moving out of a reference should already be rejected —
   verify, add a test if it's cheap, don't redesign).

## Implementation notes

- All in the typechecker (`typechecker/types.py` / `statements.py` /
  `expressions.py` around `_check_value_transfer` and identifier checking).
  Codegen already suppresses cleanup for moved-at-call-site values (the
  `nocopy_*_with_move` tests prove single-deinit behavior) — verify no
  codegen change is needed; if one is, keep it minimal and report.
- The existing flat `self.moved_variables` set has consumers — migrate them
  onto the new state rather than maintaining both.
- Watch the stdlib: `std/file.saw`'s `move data` pattern was the brief-03
  breaker. The full suite is the oracle.

## Tests (all new, plus the two flips)

Errors (`// EXPECT: error`, use-after-move message):
- `errors/use_after_move_double_move.saw` — `move v` twice.
- `errors/use_after_move_branch.saw` — moved in one `if` arm (no divergence),
  used after the merge.
- `errors/use_after_move_loop.saw` — outer binding moved inside a loop body.
- `errors/use_after_move_reference.saw` — `&v` after `move v`.
Acceptances (`// EXPECT: success` + output):
- `use_after_move_revive.saw` — move, reassign, use.
- `use_after_move_shadow.saw` — move outer `v`; inner scope declares its own
  `v` and uses it; after inner scope, using outer `v` still errors →
  actually split: the success half (shadowed inner use OK) here, and the
  error half as its own file if needed to keep one-concept-per-test.
- `use_after_move_guard_diverge.saw` — `guard`/`if` arm that moves and
  returns; fall-through path uses the binding successfully.
- `use_after_move_loop_reassign.saw` — move + definite reassign inside the
  loop body, loop runs multiple iterations successfully.
- `use_after_move_branches_both_return.saw` — both arms move+return,
  code after is unreachable-but-checked; whatever your merge does here must
  be deliberate — document it in the test comment.

## Report back

The state representation chosen (binding identity vs name+depth); how
divergence is detected for rule 6; which loop rule shipped (7); consumers of
the old flat set and how each migrated; any stdlib code that needed `move`
fixes the way `file_simple.saw` did in brief 03; false positives encountered
and how resolved; deviations; non-allowlisted commands (ideally none).

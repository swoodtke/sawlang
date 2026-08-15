# Design 224 — suspension-position coverage: the six silent-hang cells

**Status: LANDED Aug 15 (authored the same day from the DF-224 sweep;
verdict + matrices in the tracker's DF-224a entry and
`.build/scratch/sweep224/RESULTS.md`, GITIGNORED). No rulings needed.
Sequenced BEFORE design 225 (the live pool) — its cells had to become
honest parks before executor work. What landed is at the bottom.**

## The four gaps (all in coro_transform.py; tracker entry has the detail)

- **G1**: `_collect_calls` (:3732-3798) never visits container HEAD
  expressions (if/while conditions, for range, match scrutinee) — its own
  docstring asserts the opposite invariant.
- **G2**: the narrow-hoist predicate `_call_suspends_expr` (:2005) OMITS
  `is_chan_recv` while its ANF twin `_is_suspending_call_node` (:2377)
  includes it — two disagreeing suspension predicates in one file.
- **G3**: `CompoundAssignStatement` missing from `_anf_stmt` (:2138) —
  227's rider pinned the clean-refusal error test that names what the
  cell becomes when this lands.
- **G4**: `_classify_recv` (:4210) lacks the ReturnStatement arm its
  free-fn twin (:4121) has.

Effect: a `Channel.receive()` in a match scrutinee, if/while condition,
for range, or `&&`/`||` condition RHS is neither embedded nor refused —
it lowers to a plain call whose `yield_now` no-ops → 100%-CPU silent spin
(measured, identical in main and spawned bodies). The same cells for
fn/method callees are loud ICEs, same mechanism.

## The fix (obligation 1)

ONE suspension predicate — "is this expression a suspension point, of any
of the three kinds (suspending call, suspending method, channel
receive)?" — with a docstring naming its entry points, consumed by every
hoist and both classifiers (G2 dies); PLUS a position enumeration in
`_collect_calls` listing the four container HEAD slots beside the
container blocks, so a new container cannot add a head silently (G1
dies); the `_anf_stmt` compound arm (G3 — flips 227's pinned refusal to
working, and the DF-224a G3 rider cells); the ReturnStatement arm in
`_classify_recv` (G4). The 223 precedent applies: cells become WORKING
where the mechanism exists (the general ANF hoist already handles these
expressions in `let` position — extending it to the head slots is the
same machinery), CLEAN REFUSAL where it genuinely doesn't (say which,
with the reason).

## Rows first (obligation 3 — silent hangs are a safety surface)

Conformance rows from the sweep's position matrix: three suspension
kinds × the six hang cells + the ICE cells + the working controls, in
BOTH a driven main and a spawned body. The hang rows assert completion
under a bounded harness run (a hang is the failure mode — the runner's
timeout is the oracle) plus the interleave check where cooperative
behavior is the claim. Pins for the five cells the 224 sweep could not
probe (if let/guard let/try!/try/try? for a receive — blocked then by
DF-224c) get probed now and pinned per verdict.

## Gates

Per-unit full suite; corodiff --quick + the generic axis; irdet --all at
the classifier change; terminal full tracked battery. The DF-203b spin
shape is the regression risk — the op-budget backstop tests must stay
green.

OUT OF SCOPE: DF-224b/design 225 (the live pool — next); DF-224c (the
auto-wrap ICE in driven bodies — its own fix, the DF-218f family);
the deadlock report (rides 225).

## What landed (Aug 15)

Two commits. **Unit 1** = rows first: `examples/conformance/K40-K47`, the
head slots plus the compound-assign RHS, `return <receive>` and the
binding/`try` heads, three suspension kinds per row in a driven main and a
spawned body, pinned XFAIL to DF-224a. The `yield_now()` in every feeder is
LOAD-BEARING and the unit's own finding: K40 passed on first authoring, on a
compiler where the cell hangs, because the executor ran the feeder to
completion before the receiver's first `try_receive` — the same confound the
sweep hit in its gen_b pass.

**Unit 2** = the four gaps. G2's two predicates became
`_is_suspension_point`, whose docstring names its four entry points and says
why `_spans_suspension` is not one. G1's enumeration is
`ast_walk.control_heads` beside `control_blocks` — six slots, with the two
containers that have no head saying so — consumed by
`_hoist_container_heads` (the lift) and by `_collect_calls` (the backstop
that refuses a head still spanning, which is the invariant its docstring
already claimed). G3 is the `CompoundAssignStatement` arm in `_anf_stmt`
plus the `_vc_stmt` arm that lifts a short-circuit RHS whole. G4 is the
`ReturnStatement` arm in `_classify_recv` plus `_emit_recv_call` ending the
coroutine with the received value.

**The `while` condition is the one head that could not be a lift** and the
brief did not predict how it would be answered: it is evaluated per
iteration, so it moves INTO the loop body under a conditionless loop whose
else-arm is a `break`. That needed no new machinery — `_split_while` has
lowered the conditionless form since design 52 — and `continue` re-evaluates
it because the loop top IS the lifted `let`.

CELL VERDICTS: 135 probes (three kinds × every statement and expression
position × main and spawned) all WORK; none refuses. Nothing became a clean
refusal that was not one already. ONE boundary is refused and pinned
(`examples/errors/coro_value_while_suspending_condition.saw`): a
VALUE-position `while` whose condition suspends, and the reason is not the
head — a value `while` yields through `break <value>`, which a
suspension-spanning loop does not support. DF-217f closed as a rider (a
suspending call inside a constructor that IS a match scrutinee), its own pin
having predicted this fix. Design 227's pinned compound-chain refusal became
`examples/expr_suspend_optchain_compound_assign.saw`.

Gates: suite 1883 passed / 24 xfailed (was 1873 / 25); corodiff --quick and
its generic-driven axis 0 new findings; irdet --all clean over 1189
examples; full tracked battery green.

# Design 224 — suspension-position coverage: the six silent-hang cells

**Status: AUTHORED Aug 15 from the DF-224 sweep (verdict + matrices in the
tracker's DF-224a entry and `.build/scratch/sweep224/RESULTS.md`,
GITIGNORED). No rulings needed. Sequenced BEFORE design 225 (the live
pool) — its cells must become honest parks/refusals before executor work.**

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

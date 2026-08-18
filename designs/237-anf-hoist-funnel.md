# Design 237 — The ANF-Hoist Funnel: One Entry Set, One Temp-Ownership Rule

**Status: RATIFIED Aug 18 2026** (user: "brief 237 as described and queue it
before 234"). **Queue slot: BEFORE design 234** — the fallibility flip
multiplies suspending calls in expression positions (every `try(as …)` site,
every Result-returning std op inside larger expressions), and it should land
on a transform whose position coverage is a funnel, not a hand-kept list.
Independent of 235/236 (no file overlap with examples/ ledgers or the
static-keyword migration); may run beside 235 if worktree scheduling wants.

## The finding cluster this closes

The Aug-13 corodiff battery (336 twin pairs interim, 1514 full cross) plus
its lead triage produced one FUNNEL VERDICT (recorded in the tracker's
DF-217 battery section, whose matrix is this brief's row-by-row test plan):

Design 120 promises suspending calls embed in ANY expression position via
the ANF hoist. The hoist's child-position funnel `_uncond_children`
(coro_transform.py:1481) is sound where it RUNS — but it is ENTERED from a
hand-enumerated statement set covering 4 of ~8 statement classes and 0 of 3
head positions, is missing 3-5 node classes, and is flanked by three narrow
per-construct hoists plus a SECOND position map in stage 2. Every gap is a
filed finding:

- **ICE family (statement-HEAD entry gaps)** — reach codegen unhoisted and
  die `Undefined function` at the user's line: `if`/`while` CONDITIONS,
  `&&`/`||` LHS (RHS works), `for`-range BOUNDS, and match/if-let
  scrutinees whose ctor args suspend (DF-217f + its struct-init sibling).
  Pins: `expr_suspend_match_scrutinee.saw`, `expr_suspend_iflet_scrutinee.saw`.
- **Bogus-refusal family (missing statement classes / node classes)** —
  refused with the nested/expression-position error design 120 says cannot
  apply: `??` LHS, `?.` HEAD, compound-assign RHS, `return f()` under
  Result auto-wrap, and DestructuringLet RHS (**DF-217g**, pin
  `coro_destructuring_let_suspending_rhs.saw`).
- **DF-217h (DOUBLE-FREE — the temp-ownership half):** `v.set(i,
  <suspending call>)` frees the REPLACEMENT twice; the `??` RHS is its
  tenth consuming position. The hoisted temp keeps its ownership claim
  after the consumer takes the value (the DF-210f mechanism).
- **DF-218n:** an explicit `__saw_drive(f())` inside a body that itself
  suspends is an ICE — a drive SITE is one more entry the funnel must own.
  Pin: `drive_site_in_suspending_body.saw`.
- **DF-218e (verify-mechanism-first):** a GENERIC function spawned as a
  task cannot contain a nested suspending call (callee reported undefined
  at the user's line). PLAUSIBLY the same entry gap reached through
  monomorphized bodies — unit 1 must confirm the mechanism before this
  rides; if it is its own bug, it exits to a separate filing rather than
  stretching this brief. Pin:
  `coro_generic_spawn_root_nested_suspending_call.saw`.

## Explicitly OUT of scope

- **DF-217p** (frame-resident locals released at teardown, 61 cells) and
  DF-217m's COROUTINE face (`coro_hoisted_receiver_temp_released_once.saw`)
  — those are deinit-TIMING questions owing a design ruling, not hoist
  coverage. This brief must not change when correctly-hoisted temps die,
  except where DF-217h's double-free makes the current behavior wrong.
- DF-217m's SYNC face (`sync_call_temp_released_once.saw`) — sync-path
  codegen, no coro involvement; separately fixable (user shortlist).

## Units

1. **The census, then the funnel.** Enumerate every statement class and
   every head position in coro_transform's two stages against the tracker
   matrix; confirm DF-218e's mechanism. Output: the position matrix as the
   brief's test plan (obligation 1 — the funnel's docstring NAMES its entry
   points), with any non-member finding re-filed, not absorbed.
2. **Unify the entries.** Every statement class routes through
   `_uncond_children`; the three per-construct hoists fold in; stage 2's
   second position map derives from the same table. Add the missing node
   classes (EnumInit, RangeExpr, the ResultWrap family, and whatever unit
   1's census adds). ICE family and bogus-refusal family fall together;
   each matrix row lands as a test (the pins flip; new rows get new tests).
3. **Temp ownership (`_anf_lift`).** A hoisted temp's claim transfers to
   its consumer exactly once — DF-217h's double-free and its ten consuming
   positions are the rows. The over-release detector (Aug 17) turns any
   overshoot here into a deterministic panic — build against it.
4. **Drive sites + spawn roots.** DF-218n's drive-in-suspending-body and
   (if unit 1 confirmed membership) DF-218e's generic spawn root, through
   the same funnel. corodiff ledger rows for every closed finding retire
   WITH their fixes (the three-artifacts rule).
5. **The differential re-run.** `corodiff --quick` per commit;
   the FULL cross (the battery that found the cluster) once at the end —
   the funnel's claim is position-quantified, and the harness that
   falsified it is the only honest verifier. Terminal full battery.

## Gates

Compiler brief: per-commit `battery.sh suite sos`; unit 5's full cross +
terminal full battery. Every pin flip removes its XFAIL and its
`tools/corodiff_known.txt` block in the same commit.

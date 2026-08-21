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

---

# LANDING (Aug 21, branch `design-237`)

## Unit 1 — the census, run first

Probed 25 cells against the tree as it stands, compile+run evidence for every
row (`.build/scratch/census237/`). The brief was written Aug 18 against the
Aug-13 battery, and **design 224 (Aug 15) had already closed most of the ICE
family** — the census is what said so rather than the brief's list.

**WORKING, no gap (design 224's container-HEAD hoist owns them):** `if`
condition, `while` condition, `for`-range bound, `match` scrutinee whose
constructor argument suspends (DF-217f's exact cell), `if let`/`guard let`
subject, `&&` LHS, `||` LHS. And, from the same landing, `??` LHS, `?.` HEAD
and compound-assign RHS — three of the five bogus refusals the brief lists.

**WORKING, no gap (already in the funnel):** `EnumInit` arguments, including
DF-133a evaluation order against a side-effecting sibling; `StructInit` field
values; a `&var v[<suspending>]` reference operand. `RangeExpr` is not a
missing node class: it is a head and never a value (`let r = 0..n` names no
type), and `_head_lift` owns its endpoints.

**REAL GAPS, four:**

- **G1 — `DestructuringLet`** (DF-217g). The one leaf statement class missing
  from the hoist's entry set. Both spellings refused. *Unit 2.*
- **G2 — the RESULT WRAP family** (`ResultOkWrap`/`ResultErrWrap`/
  `ErasedErrWrap`), the node classes actually missing from
  `_map_uncond_children`. This is what "return f() under Result auto-wrap"
  was. *Unit 2.*
- **G3 — the call-site auto-wrap MARK dropped by every substitution.** DF-224c
  and a `Result` twin the census found beside it. Not a coverage gap at all:
  the wrap is an ANNOTATION on the argument expression, the transform replaces
  that expression (a hoisted temp, a frame-field read), and in a DRIVEN body
  design 210's `embed_preserved` means the post-transform pass never re-derives
  it. `Type of #1 arg mismatch: {i1, i64} != i64` at the author's line.
  *Unit 3.*
- **G4 — DF-218n's drive site.** *Unit 4, as the user ruled it: a clean
  refusal.*

**DF-218e EXITS the brief**, per the unit-1 clause. Mechanism confirmed and it
is not this one: the error comes from the POST-TRANSFORM RE-CHECK (`-v` places
it after "Applied coroutine transform; re-checking…"), a suspending nested
callee is CONSUMED by the transform (frame + driver, plain function dropped),
and a generic declaration leaves its un-transformed TEMPLATE behind still
naming it. Driving one generic at TWO type arguments produces exactly ONE
`undefined function` error, which is the template and not the instantiations.
The boundary is also WIDER than the original filing: the AMBIENT-entry cell
fails identically, so it is not the spawn path. Pin rewritten with both cells
and the mechanism; entry re-filed in the tracker.

## Units 2-4, as landed

| commit | closes |
|---|---|
| `design 237 unit 2` | DF-217g; return-under-Result-auto-wrap; retires the DF-217f ledger row design 224 left behind |
| `design 237 unit 3` | DF-224c + its `Result` twin |
| `design 237 unit 4` | DF-218n |

Unit 2 replaced the hand-enumerated if-chain with `_ANF_STMT_ENTRIES`, a table
whose rows are `(statement class, value field, lift_self)` and whose comment
says why each absent class is absent. `_map_uncond_children` gained the Result
wrap family and a docstring naming its three entries plus the completeness
argument for every node type not in it.

Unit 3 is the temp-ownership unit, restated for what the tree actually still
had wrong: DF-217h's double-free was already closed by design 218 stage 2 (the
hoisted temp is a `Slot` read by `take()`), and what remained un-transferred at
a substitution was the POSITION's own answer. `_substitute(old, new)` MOVES the
auto-wrap marks and clears the source — exactly once, for the same reason the
ownership rule is exactly once: after the substitution the old node is the
initializer of `let __anfN = …`, which is a transfer site that would apply the
wrapper a second time into a temp typed for the unwrapped value. Seven entries,
named in its docstring. The annotation set was swept rather than guessed
(obligation 4): the auto-wrap trio is the position family, `expected_type`
reaches no substitutable node, everything else describes the value.

Unit 4 refuses at the top of `_FrameBuilder.prepare`, on the untouched body —
one entry, covering every drive spelling and every root kind, because every
body the transform frames passes through there.

## Tests

- `examples/coro_destructuring_let_suspending_rhs.saw` — XFAIL flipped, grown
  into the statement class's matrix (7 rows).
- `examples/coro_return_autowrap_result_suspending.saw` — new, 6 rows.
- `examples/coro_autowrap_argument_in_driven_body.saw` — new, 10 rows: the
  wrap kinds crossed with the two substitution shapes and the callee kinds.
- `examples/drive_site_in_suspending_body.saw` — XFAIL flipped to the refusal;
  `examples/drive_site_in_suspending_function.saw` — new second row.
- `examples/coro_generic_spawn_root_nested_suspending_call.saw` — still XFAIL
  (DF-218e), rewritten with the confirmed mechanism and the ambient cell.

## Consumer sweep (obligation 2)

No behavioral contract flipped. `run()` semantics, the op budget, and every
throttle are untouched — the DF-182f fork-bomb's neighbourhood was read and not
edited. `_rewrite_expr` became a thin wrapper over `_rewrite_expr_node` so the
carry has one exit; every existing caller is unchanged. The one deliberate
narrowing is unit 4's refusal, and its consumer set is programs writing
`__saw_drive` in a suspending body: the corpus had exactly one, the DF-218n pin
itself, which is now the refusal's test.

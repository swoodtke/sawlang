# Design 218b — unit 2 remainder: the scope-end release migration spec

**Status: RULED (user, Aug 21 2026) — ALL SIX open questions RATIFIED as
recommended; implementation dispatched same day. IMPLEMENTED Aug 21 on branch
`design-218-u2`, stages 0/A+B/C/D/E — with ONE stage that did not deliver its
promised flip at the time: see "STAGE C: the DF-218s flip is NOT reachable as
specified" below. That stage's residue was RULED the same evening (OPTION 3,
forced frame residency) and LANDED on branch `df-218s-218w`, which flipped the
pin; stage D's `match_nobinding` residue (DF-218w) landed with it, narrowed to
the mixed `case Two(v, _)` shape. The contract this spec states is unchanged —
both were emission gaps under it, not amendments to it.**

## Landing note (Aug 21)

Stages 0, A+B, D and E landed. Four deviations, recorded here rather than in
the report alone:

- **Stages A and B landed as ONE commit.** The spec staged the linear face
  ahead of the loop face, but both are the same funnel entered from the same
  chokepoint (`_lower_block`), and the split would have required an intermediate
  commit in which `break`/`continue` unwound PAST the loop boundary — a
  deliberately wrong compiler — because E-BRK/E-CNT need the loop marker the
  loop face installs. The linear and loop cells of the ledger retire together
  for the same reason.
- **STAGE C: the DF-218s flip is NOT reachable as specified, and the pin stays
  XFAIL.** Row E-RET landed (scope clears innermost-first ahead of `release()`),
  which is what restores scope order AMONG FRAME FIELDS. It cannot reorder a
  frame field against a REAL local, which is what DF-218s measures: codegen's
  `_cleanup_all_scopes` — the thing that drops `inner` — runs at the lowered
  `return Poll.Done`, i.e. after EVERY statement the transform can put in front
  of it, so no emission the transform is able to make lands after that drop.
  Moving the frame's release later means one of three things, each a ruling:
  call `release()` from the DRIVER after `resume` reports Done (correct order by
  construction, but the scheduler is the third driver and design 124's eager
  timing lives there); route every nested `return` through a shared DONE STATE
  reached by a state assignment plus a dispatch `continue` (correct where no
  enclosing non-spanning loop swallows the `continue`, wrong where one does);
  or force frame residency on the real locals of any block containing a
  `return`, via the `force` mechanism split try/catch already uses (correct,
  and it changes frame layout for every driven body with a nested return).
  Reported to the lead for the user; the pin carries the mechanism and the
  containment fact that bounds it (a frame-resident scope is always an ANCESTOR
  of a real-local scope, so "all real locals, then all frame fields" would be
  exactly sync-LIFO if the two could be ordered that way).
  **RESOLVED the same evening — the user ruled OPTION 3 and it landed on branch
  `df-218s-218w`.** `_collect_frame_locals` gained a second residency reason:
  the OWNING locals of a block that (transitively) contains a `return` are
  frame fields, so E-RET's scope walk is the total authority and the two
  systems no longer meet. Scoped to owning locals (by KIND, not by encoding —
  the encoding calls an `UnsafePointer` owning, and forcing one resident made a
  spawned frame non-`Send`), to return-containing blocks, and to bodies that
  suspend. `_lower_block_in_place` became a scope with it, so the stack E-RET
  walks follows the in-place descent too. Pin flipped, with the block-kind
  matrix added.
- **Section 2c retires three of its four cells, not four.** The merge-point
  release cleared `match_consume/in_rhs` at both context classes. The
  `match_nobinding` cells — an arm binding a payload to `_` — did not: sync
  drops a discarded payload INLINE at extraction, because a `_` binding is
  registered in no cleanup scope and no scope exit could reach it, and the
  driven twin has no consume mode to be in (its scrutinee is the frame temp
  the head hoist made, not an owned local). What is left is intra-statement
  timing, one position late, never a leak. Re-filed as DF-218w with its own
  pin and its own two ledger rows; the fix is per-ARM emission and owes a rule
  for the mixed `case Two(v, _)` shape.
- **Section 4's soundness argument needed one guard.** It reasons that every
  driven use of such a template was promoted to a concrete function first, so
  nothing can still name it. That premise fails where
  `_promote_nested_generic_calls` DECLINES — a template suspending
  unconditionally without calling a type-parameter method has no instantiation
  effect node — and there the call site still names the template while codegen
  serves it by late monomorphization. A probe caught it as a codegen ICE where
  the old behavior was a clean diagnostic. So a template is consumed only when
  nothing surviving the splice still calls it. Section 4 also under-specified
  the METHOD half: a generic method TEMPLATE in an extension errors the same
  way and needs the same removal, through design 223's strip funnel so a
  conformance-required method is refused.

Three findings the work surfaced, all pre-existing, filed rather than worked
around: DF-218t (a value-position loop at a non-integer result type is a
codegen ICE — the `None` sentinel is built for an integer), DF-218v (a
`try { } catch { }` BLOCK leaks the try body's locals on its error edge, which
CORRECTS DF-218r's class statement — that error edge is a third nonlocal exit
that is not a return), and DF-218w above. One was fixed on discovery: DF-218u,
a design-107 redefinition losing its drop point in any body the transform
RENAMES but does not make frame-resident, which the stage-A/B `--all` run
reported as a new cell the moment the driven twin started dropping on time.

## RULINGS (user, Aug 21 — section 7's questions, ratified wholesale)

1. Sync-LIFO is the contract at the done path — the scope-end ruling covers
   ORDER, not only timing; DF-218s's inversion is fixed in stage C.
2. DF-218r (the sync break/continue leak) lands as STAGE 0 of this unit —
   the oracle is corrected before the loop face rests on it.
3. The no-scope-structure boundary stands: panic releases nothing (sync
   parity); box-teardown of a never-completed frame keeps reverse-declaration
   order (it already exceeds the sync analog, process death).
4. The scrutinee-temp pairing: the DF-210f forget survives on consuming
   arms, the idempotent merge-point release closes the non-consuming half,
   FAM_SCRUTINEE_TEMP stays a cited deferral, narrowed.
5. DF-218e's fix is CONSUMPTION SYMMETRY — a generic template naming a
   consumed suspending callee is itself consumed at the splice; the
   obligation-4 sweep in section 4 is owed with it.
6. Scope-end covers EVERY owning field, deferred families included, in the
   legacy spelling via the shared release-shape helper — deterministic
   destruction is UNCONDITIONAL, not gated on the Slot migration.

Charter: design 218 unit 2's REMAINDER, per the process ruling that a spec
agent documents the exact form first (218a is the precedent and the model),
the lead reviews it, the USER rules on it, and Opus implementers dispatch
against it. Inputs: the DF-217p ruling (Aug 20: SCOPE-END REQUIRED — a driven
frame local releases at its scope's end exactly as the sync twin does;
deterministic destruction is unconditional; the corodiff ledger's DF-217p
block is the acceptance matrix), the DF-217m coro face (rides, per the same
ruling), DF-218e (same transform; mechanism confirmed by design 237's
census), and a fresh line-level read of `sawc/coro_transform.py` post-237.

Probes live in `.build/scratch/spec218b/` (gitignored), every one compiled
and run against this worktree's sawc with the main venv; outputs are quoted
where load-bearing. Line anchors are THIS tree's (main @ 8fb1d687).

**TWO NEW FINDINGS the probes surfaced, filed as DF-218r and DF-218s**
(tracker entries point here; evidence in sections 1b and 1c):

- **DF-218r — the SYNC twin LEAKS a loop-body local on the `break` and
  `continue` edges.** Probe P1b: `while i < 3 { let b = Res(..); if i == 1 {
  break } .. }` never deinits `b1`; the continue twin never deinits `c0`; the
  `return`-inside-loop control drops both. MECHANISM:
  `_generate_break_statement` / `_generate_continue_statement`
  (`sawc/codegen/loops.py:460-505`) branch to the loop's exit/continue block
  and run NO `_cleanup_scope` for the block scopes between the statement and
  the loop, while `visit_ReturnStatement` runs `_cleanup_all_scopes`
  (`sawc/codegen/statements.py:1046`). Obligation-4 class statement: the
  mechanism is "a nonlocal exit that is not a return skips the cleanup
  stack"; the positions it reaches are `break` and `continue` (from any
  block depth inside the loop, including the design-65 owning loop variable
  of a `for`, whose per-iteration pop at loops.py:191 is skipped when the
  block is already terminated); `return` is covered and `guard`'s else
  must exit via one of the three, so it adds no fourth edge. This matters
  to THIS spec twice: the sync twin is the migration's oracle, and on these
  two edges the oracle is wrong (twin parity would demand matching a leak) —
  so the sync fix lands BEFORE the loop-face stage (staging, section 6).
- **DF-218s — the driven done path releases in REVERSE-DECLARATION order,
  inverting the sync twin's scope-LIFO order when a real local is in
  flight.** Probe P2 `early_return` (a frame-resident `outer`, a
  non-spanning inner scope's REAL local `inner`, `return` inside the inner
  scope): sync prints `DEINIT inner, DEINIT outer` (P1); driven prints
  `DEINIT outer, DEINIT inner`. MECHANISM: `_done_seq`
  (coro_transform.py:7326) calls `release()` — which drops every owned
  FRAME field in reverse declaration order (`_release_seq`, 7407) — and the
  lowered `return Poll.Done` statement's own `_cleanup_all_scopes` then
  drops the surviving REAL locals, so the two release systems run in the
  wrong relative order. Not in the 68-cell matrix (needs a mixed
  frame-field/real-local return path, which corodiff's single-binding
  programs never build). Fixed structurally by this migration's done-path
  stage (section 1c, row E-RET).

## 1. The scope model

### 1a. Which locals the transform owns, and which scopes exist

Frame-residency (design 52 Part 0, `_collect_frame_locals`,
coro_transform.py:3621): every `let`/`var` declared DIRECTLY in a block that
(transitively) contains a suspension point is a frame field, plus a split
`if let`/`guard let`'s binding, a suspension-spanning `match`'s payload/
scrutinee-pattern bindings, a suspending range-`for`'s induction variable and
synthesized bound, a split try/catch's error binding and (via `force`) every
local under a split try/catch. Everything else stays a REAL local with
ordinary codegen scope cleanup — so the migration's emission duty covers
exactly the `encmap` members, and the real-local layer's own scope-end
correctness is codegen's (where DF-218r lives).

The scopes a driven body can have, with probe evidence for each row
(P1 = sync `.build/scratch/spec218b/p1_sync_scopes.saw`, P2/P3 = driven
`p2_driven_scopes.saw` / `p3_linear_faces.saw`):

| # | scope | sync twin releases (probed) | transform today (probed) | ruled emission point |
|---|-------|------------------------------|--------------------------|----------------------|
| SC1 | function body | at return/tail, LIFO after inner scopes | `release()` at every Done exit (design 124) — timing right, ORDER wrong beside real locals (DF-218s) | unchanged point; ordering fixed by row E-RET |
| SC2 | loop body (`while`, `while let`, range `for`), per iteration | end of each iteration, before the backedge (P1: `DEINIT a0` before `iter a1`) | the NEXT iteration's `put` drops the previous occupant (replace semantics, `_store_field` 5348), the LAST iteration's survives to teardown (P2 `brk`/`cont`; the pin's loop face) | end of the loop body, before the backedge `_goto` (E-FALL at the body block) |
| SC3 | loop exit via `break` | scope end at the break — WHAT THE RULE SAYS; today sync LEAKS it (DF-218r) | survives to teardown | on the break edge, before `_goto(loop_ctx[1])` (E-BRK) |
| SC4 | loop exit via `continue` | scope end at the continue — same DF-218r caveat | survives to teardown | on the continue edge, before `_goto(loop_ctx[0])` (E-CNT) |
| SC5 | `if`/`else` branch | at branch end (P1 early_return's `inner` under sync is LIFO-correct) | branch locals that span are frame fields, released at teardown (P3 `nested_block_scope`: `after if` prints before `DEINIT inner`) | end of the branch's `_lower_block`, before the merge `_goto` (E-FALL) |
| SC6 | `if let`/`guard let` then-branch (split; the binding + branch locals) | binding dies at body end (P1: `DEINIT p1` before `after iflet`) | teardown (P3 `iflet_spanning`: `after iflet` first) | end of the then-branch block (E-FALL); the guard binding belongs to the ENCLOSING scope (P1 `guard_body`: drops at function end) and needs no new point |
| SC7 | `match` arm (payload binding + arm locals) | binding at arm end (P1: `DEINIT m1` before `after match`; DF-217n pinned the named-binding-at-arm-end / `_` payload-at-extraction split) | teardown (P3 `match_spanning`) | end of the arm's entry-block lowering (E-FALL) |
| SC8 | design-107 same-scope redefinition (the REPLACED binding) | drops AT the redefinition, after the deriving initializer (P1: `DEINIT s1` before `now s1-2`; codegen `_drop_redefined_same_scope`, resources.py:1827) | teardown (the pin's shadow face) | immediately after the replacing binding's store (E-REDEF) |
| SC9 | destructuring `let` leaves | leaves drop at their scope's end, LIFO (P1: `DEINIT d2, DEINIT d1`) | leaves are ordinary frame fields of the declaring scope | covered by the declaring scope's row — no separate point |
| SC10 | split try/catch (try body, catch body, the error binding) | try-body locals at block end; the caught binding at catch end | teardown (all `force`-marked locals are frame fields) | end of each of the two `_lower_block`s (E-FALL); the error field clears at catch end |
| SC11 | transform temps: `__anfN`/`__trycallN`/`__vchN`/`__obN` (non-consumed face), `__rcvN` discard holder | a statement temporary drops at STATEMENT end (design 240 item 9; the sync pin passes: `deinit 3` before the result print) | non-consumed `__anfN` and `__rcvN` survive to teardown (the DF-217m pin: `n=44` before `deinit 44`) | end of the statement the hoist lifted them from (E-STMT; section 3) |
| SC12 | scrutinee temps `__hoistN`/`__matchN` (FAM_SCRUTINEE_TEMP) | a match/if-let scrutinee temporary drops at the end of the statement | consuming arm: DF-210f forget; NON-consuming arm: teardown | at the construct's MERGE point (E-STMT variant; section 2c) |

Cancel and panic need no rows of their own, probed rather than assumed
(P4, `p4_cancel.saw`): a task cancelled mid-suspend that OBSERVES exits via
its own `return` (scope edges run normally — `DEINIT obsA` lands at the
observation return); an OBLIVIOUS one runs to completion; and a task
cancelled BEFORE its first poll still RUNS (cancellation is cooperative;
`C ran cC` printed) — so every cancel path exits through ordinary control
flow and the scope edges above cover it. The paths with NO control flow —
panic (aborts, releases nothing, by design) and box teardown of a
never-completed frame (the deadlock-panic report path, `Resumable.release`
at group teardown) — keep reverse-declaration-order release; open question
OQ3 asks the user to ratify that boundary.

### 1b. The exit-edge funnel (obligation 1)

"Release at every scope exit" is a position-quantified rule, so it is a
FUNNEL: one `_FrameBuilder._scope_release_seq(fields)` whose docstring names
its entry points, which are exactly the edges:

- **E-FALL** — fallthrough out of a lowered block: the end of `_lower_block`
  (5481) before the merge/backedge `_goto`, for `_split_if` (5636),
  `_split_if_let` (5732), `_split_guard_let` (5775), `_split_while` (5791),
  `_split_for` (5822), `_split_match` (5891), `_split_try_catch` (5981).
- **E-BRK / E-CNT** — the `break`/`continue` arms of `_lower_stmt`
  (5567/5579): clears for every open scope from the innermost out TO AND
  INCLUDING the loop body's, emitted before the `_goto`.
- **E-RET** — the done path: `_done_seq` (7326) gains, BEFORE the
  `release()` call, clears for every open scope innermost-first. `release()`
  survives unchanged (218a ruling: design 124's eager timing needs it) and
  becomes the backstop that drops what no scope owned — params, and any
  field on a path the scope walk could not prove — restoring the sync LIFO
  order DF-218s shows inverted (scope clears run first, then the remainder;
  a cleared slot is a no-op there).
- **E-REDEF** — the same-scope redefinition point: after the replacing
  binding's store in `_lower_inplace`'s LetStatement arm (7161) or
  `_store_binding_in_slot` callers, a clear of the REPLACED binding's field.
  `_uniq_bind` (3270) is where the transform KNOWS a let replaced a
  same-scope binding (the mint-on-collision arm); it records
  (statement, replaced effective name) for the walk to consume.
- **E-STMT** — statement-end temp release (section 3) and the scrutinee-temp
  merge release (section 2c).

The scope→fields map is built where the scopes are already reified:
`_uniq_walk_block` (3301) walks per-block scope dicts and today discards
them; it will record, per AST block, the ORDERED effective names bound
there. At emission time the walk keeps a scope STACK in `_FrameBuilder`
(pushed by `_lower_block` and each split entry, with a loop marker so
E-BRK/E-CNT know how far to unwind), filters each scope's names to `encmap`
members, and emits clears in reverse declaration order — the same LIFO
`_release_seq` and codegen's `_cleanup_scope` (resources.py:1778) both use.

### 1c. Suspension interaction and the exactly-once story

A scope that spans a suspend releases on the RESUME path by construction:
the clears are ordinary statements appended to whatever CFG block the scope
exits in, which is a resume-state block — no new mechanism. The
cancel/teardown path is covered because `release()` (every Done exit) and
the frame's deinit (box death) both drop **iff occupied** — and occupancy is
the EXISTING exactly-once mechanism this spec leans on, exactly as the
charter directs:

- a migrated field's clear is `Slot.clear()` — idempotent by the type
  (218a section 2's four-exit argument, conformance K28);
- a deferred-family field's clear is the design-44 assignment `self.x =
  None` — the same idempotent tag-drop `_release_seq` (7449-7457) emits at
  teardown;
- a `plain` TaskGroup's is the placeholder overwrite (218a ruling 5) — the
  overwrite IS the join and the fresh group's later drop is a no-op.

So a scope-end clear followed by `release()` followed by box teardown drops
the payload exactly once whichever of the three reaches it first, and a
MISSED edge degrades to today's behavior (a late release, loud in the
corodiff lane as DEINIT-ORDER) — never a double free. That is the calibrated
claim, same shape as 218a's: the migration cannot introduce the DF-217
ownership class; what it can get wrong is timing, which is precisely what
the twin-parity lane measures.

One consequence worth naming: after E-FALL lands, the loop face's
accidental drop-at-next-`put` (SC2) becomes unreachable — the `put` always
finds an empty slot — but `put`'s replace semantics stay, as the backstop
for any path the walk misses.

### 1d. Release shapes: ONE authority shared with teardown

The per-encoding release shape (Slot → `clear()`, legacy cleanup encodings →
`= None`, TaskGroup → placeholder, `ref`/`__recv`/`plain`-POD/`Void` →
nothing, `__result` → NEVER touched: it survives to `join`/teardown and is
excluded exactly as `_owned_frame_fields` (7387) excludes it) is today
written once, inside `_release_seq`. The migration extracts it into a
per-field helper both `_release_seq` and `_scope_release_seq` call, so the
scope-end path cannot drift from the teardown path — the two are one
decision about WHAT a release is, differing only in WHEN and over WHICH
fields.

## 2. Emission census

### 2a. Sites that currently defer a release to teardown

Every site whose current behavior is "the drop happens in `release()` /
box teardown" and which this migration moves to a scope edge:

| # | site | file:line | current shape | new form | moves to |
|---|------|-----------|---------------|----------|----------|
| C1 | `_lower_block` fallthrough (all split constructs) | 5481, callers 5636-6009 | block ends with `_goto(merge)`; locals stay occupied | `_scope_release_seq(scope)` appended before the `_goto` | E-FALL (SC2/5/6/7/10) |
| C2 | `_lower_stmt` BreakStatement | 5567 | bare `_goto(loop_ctx[1])` | clears for scopes down to the loop body, then the goto | E-BRK (SC3) |
| C3 | `_lower_stmt` ContinueStatement | 5579 | bare `_goto(loop_ctx[0])` | same, then the goto | E-CNT (SC4) |
| C4 | `_done_seq` | 7326 | result store → forgets → `release()` | result store → forgets → scope clears innermost-first → `release()` | E-RET (SC1, DF-218s) |
| C5 | `_lower_inplace` LetStatement, the design-107 mint | 7161 / `_uniq_bind` 3270 | replaced binding's field survives to teardown | clear of the replaced field, after the replacing store | E-REDEF (SC8) |
| C6 | `_store_field` put-replace | 5348 | the ACCIDENTAL late drop of a loop-carried rebind | unchanged code; becomes a backstop (finds an empty slot once C1 lands) | — |
| C7 | `_anf_lift` temps read non-consumingly | 2348 / `_takes_temp` 5756 / `_read_field` 1182 | `value()` borrow; husk to teardown (the DF-217m pin) | `clear()` after the lifted-from statement | E-STMT (section 3) |
| C8 | `_emit_recv_call` discard holder `__rcvN` | 4573 region; owned per `_owned_frame_fields` 7399-7404 | "owns it until teardown" (design 62 G3) | clear after the receive statement completes | E-STMT |
| C9 | scrutinee temps `__hoistN`/`__matchN`, the non-consuming arms | `_optbind_dispatch` 5660 / `_split_match` 5936-5951 | consuming arm forgets (DF-210f, FAM_SCRUTINEE_TEMP); non-consuming arm holds to teardown | `= None` at the construct's merge point (2c) | E-STMT |
| C10 | `_release_seq` / `_release_call` / `Resumable.release` | 7407 / 7383 | the teardown release | UNCHANGED — becomes the backstop + the cancel/teardown/box path | — |

NOT touched, and why: `__result` (survives to join — trusted-list item 2 /
FAM_SPAWN_CELL); the scheduler words and `__io_fd`/`__io_dir`
(design 91/134a, released by `release()`'s `io_unwait` prologue only);
sub-frame fields (each sub-frame releases itself at ITS Done —
`_owned_frame_fields`'s documented exclusion); `__recv` and `ref` fields
(non-owning `UnsafeRef`s); the spawn cell plumbing (trusted list); and
`_forget_stmt`/`_forgets` (6642-6661), whose emissions are the deferred
families' and are NOT releases — the forget funnel, its citations and the
`forgetgate` lane are untouched by this migration except where 2c narrows
one family's reach.

### 2b. The deferred families' disposition

The charter asks, per family stage 1 held back: does scope-end retire it,
depend on it, or leave it? Answer, and the reason it is uniform: **scope-end
releases a field BY ITS ENCODING'S SHAPE (section 1d), so it neither
retires nor depends on any family — a deferred field gets its scope-end
release in the legacy spelling, and migrates to `clear()` whenever its
family lands, with no change to WHERE the release sits.** Deterministic
destruction is thereby unconditional (the ruling's word) rather than
gated on the Slot migration finishing. Per family:

| family | anchor | disposition |
|--------|--------|-------------|
| FAM_OPT_CLOSURE (a) | coro_transform.py:759, 797-804 | LEFT. Scope-end emits the legacy `= None` for a frame-resident closure local at its scope's exit; calls all precede the exit, so nothing changes for the call rewrite |
| FAM_ADDRESSED (b) | 760, 805-810 | LEFT. `= None` at scope exit is safe: the pointers taken into the field belong to sub-frame drives that complete before the scope exits (LIFO, 218a ruling 7) |
| FAM_VOID (c) | 761 | LEFT; nothing to release, scope-end emits nothing (same test `_release_seq` uses) |
| FAM_FIXED_ARRAY (d) | 762 | LEFT; release shape = whatever `_release_seq` emits for the encoding today, via the shared helper |
| FAM_WINDOW_MOVE (e, DF-218h) | 763 | LEFT; same |
| FAM_RENDERED (f, DF-218i) | 764 | LEFT; same |
| FAM_SCRUTINEE_TEMP | 765 | NARROWED, not retired — section 2c. The DF-210f forget STAYS; the merge-point release closes the non-consuming half's timing. The family's citation in the forget funnel is unchanged |
| FAM_SPAWN_CELL | 766 | UNTOUCHED (trusted list; `__result` excluded from every scope) |

Consequence for the gates: `forgetgate` (`tools/test_forget_purge.py`) sees
no new `__saw_forget` emissions and no deletions; the M1/M3 marks and
`_read_field`'s legacy branch (1259-1281) survive exactly as before, still
retiring with the last family, not here.

### 2c. The scrutinee-temp merge release (the one family interaction)

Today (`_optbind_dispatch` 5685-5716, `_split_match` 5936-5951): when an
arm's binding store CONSUMES, the hoisted scrutinee temp gets a `__saw_forget`
(DF-210f — the payload left through the binding, so the temp's claim must
clear WITHOUT dropping). When no arm consumes (a `_` arm, a non-binding
wildcard, a Copy-tier binding), the temp stays occupied and drops at
teardown — the ledger's `match_consume/in_rhs @ linear`,
`match_nobinding/in_rhs @ linear+loop` cells.

The new form adds ONE statement at the construct's merge block: the temp's
release in its encoding's shape (`= None` for the opt-encoded legacy temp).
The two paths compose through the tag, exactly-once:

- consuming arm: forget cleared the tag → the merge release is a no-op —
  emitting a DROP there instead of relying on the forget would double-free,
  which is why the forget SURVIVES and the merge release must be the
  idempotent tag-drop, never an unconditional drop;
- non-consuming arm: tag still set → the merge release drops the temp where
  the sync twin drops its statement temporary.

This is deliberately NOT `take()`-ahead-of-dispatch (218a S3's shape): the
stage-2 landing measured why that cannot work for these two temps (the
binding's consumption is per-arm and neither spelling is expressible —
`take()` leaks on the non-consuming dispatch, `value()` refuses a NoCopy
named binding: the half of DF-218a its `_`-only desugar left open). The
merge release gets the sync TIMING without touching the dispatch reads.

## 3. DF-217m coro face — statement-end temps

Design 240 item 9 closed the sync half: an instance method (and `init`)
pushes a PARAM cleanup scope (codegen/methods.py:129/444/512), and a field
read off an owned temporary registers the receiver — so the sync twin now
drops a by-value method argument in the callee and a call-result receiver
temp at its statement's end (`examples/sync_call_temp_released_once.saw`
passes: probed this tree, `deinit N` precedes each use line).

How that maps into the frame model — the rows:

| # | shape | sync (probed) | driven today (probed) | new form |
|---|-------|---------------|------------------------|----------|
| M1 | by-value owning param of a DRIVEN function/method | callee owns; drops at callee return | frame field, dropped by `release()` at Done — the SAME point (a frame's Done is its return) | NO CHANGE OWED. The param rows converge already; corodiff's sync-leak ledger rows came out with design 240 (none existed for the driven side) |
| M2 | call-result receiver temp, plain (`mk(10).describe()`) | drops at statement end | ALREADY statement-end since stage 2 (`_takes_temp`: the single-use temp's read is `take()`, so the value dies as an owned temporary — the pin's first half, probed green) | NO CHANGE OWED |
| M3 | call-result receiver temp, UNWRAPPED (`mk_opt(44)!.describe()`) | drops at statement end | the `self_opt`-slot temp is read by `value()` borrow (stage 2 row (g) kept it deliberately while the sync twin leaked); husk survives to teardown — probed: `n=44` then `deinit 44` | `self.__anfN.clear()` emitted after the statement the ANF hoist lifted the temp from (E-STMT). The borrow read is UNCHANGED — only the husk's lifetime moves |
| M4 | `__rcvN` discard holder (census C8) | a discarded receive's value drops at the statement | teardown | clear after the receive statement (E-STMT) |

E-STMT's implementation surface: the hoists already know the statement each
temp belongs to (`_anf_lift`'s per-statement processing; the `_hoist_temps`
registration that DF-210f built). The emission is one clear per
non-consumed temp, appended after the rewritten statement — in
`_lower_stmt`/`_lower_inplace` where the statement's `cap_lets`/forgets
already attach. A CONSUMED temp (read by `take()`) needs nothing: the take
emptied it, and the clear behind it would be a no-op — emitting it anyway
is acceptable and simpler; the implementer may emit per-temp clears
unconditionally on the statement's fallthrough path.

The pin that flips: `examples/coro_hoisted_receiver_temp_released_once.saw`
(XFAIL DF-217m). Impossibility argument: the temp's clear is emitted at the
end of the statement it was lifted from, in the same CFG block, so no
suspension, arm, or later statement can observe the husk; a double release
is unrepresentable because the clear is the idempotent tag-drop and the only
consuming read (`take()`) already empties the same tag (K28's argument,
applied at a new point).

## 4. DF-218e — the un-transformed generic template (SEPARABLE)

**It is genuinely separable from scope-end** — a program-composition bug,
not a release-timing one — and gets its own stage (section 6), orderable
first or last with no interaction.

Mechanism (design 237's census, re-probed this tree — the pin compiles to
exactly ``error: undefined function `mk` `` at the author's line 53 plus the
`undefined variable `v1`` cascade): the transform CONSUMES a suspending
callee — frame + driver synthesized, the plain function removed at the
splice (`program.functions` filter, coro_transform.py:9817) — while a
GENERIC caller leaves its un-transformed TEMPLATE in `program.functions`
beside the promoted concrete instantiations
(`_promote_nested_generic_calls`, 8742). The post-transform re-check walks
the template's body, which still names the consumed callee. It is the
template and not the instantiations (two type arguments, ONE error), and
the ambient-entry cell fails identically (the pin carries both cells) —
consumption happens at the splice, not per drive spelling.

**The fix shape: consumption symmetry.** The rule the non-generic twin
already follows is "a body the transform replaced with a frame is removed";
its generic analog is *a generic TEMPLATE whose body contains a call to a
consumed (suspending) callee is itself consumed at the splice* — every
instantiation of such a template is unconditionally suspending (the callee
is concrete and suspending, so effect inference suspends every
instantiation), every driven use was promoted to a concrete function before
the transform ran, and no sync instantiation can exist to need the template
at codegen's late monomorphization. Implementation: at the splice, extend
`removed` with generic templates whose bodies name a member of `removed`
(the direct-call walk `_rewrite_drive_sites` already does over these same
bodies). Templates that suspend only CONDITIONALLY (via a type-parameter
method) name no consumed callee and are untouched — their sync
instantiations stay reachable.

Two alternatives considered and not recommended: excluding the template
from the re-check only (leaves a dead template for codegen to trip over,
and weakens the re-check by provenance rather than by a structural
argument); waiting for unit 1.5 (monomorphization-as-transform dissolves
templates entirely — the right end state, but the ruling queued this
finding with unit 2's remainder, and the interim fix is small). OQ5 asks
for the ruling.

The obligation-4 sweep the fix owes (from the pin's header, unchanged):
generic roots that are METHODS, MT spawn, a generic root whose nested
callee is itself generic, and any other way a surviving template can name a
declaration the transform consumed. Flip: the pin
`examples/coro_generic_spawn_root_nested_suspending_call.saw` + the
DF-218e ledger row. Impossibility argument: the template that named the
consumed callee no longer exists in the checked program, so the re-check
has no body in which the name is dangling; the instantiations were checked
concrete (and transformed), which is where the checking belongs.

## 5. The flip list, pre-registered (the pin gate)

### 5a. Ledger rows this migration retires

The ENTIRE `DF-217p-2026-08-13` block in `tools/corodiff_known.txt` — **68
rows** (the ruling's "61+2+3" plus the two DF-225m-context `in_rhs @ loop`
cells the ledger records as gaps of the same mechanism at lines 148-153;
the acceptance matrix is the block as it stands, counted, not the summary
arithmetic). Grouped by the stage that retires them (section 6):

- the `@ linear` cells (if_let_payload, if_let_move_local,
  let_shadow_rebind, match_consume incl. `in_rhs @ linear`) — stages A + B;
- the `@ loop` cells (every binding kind × after/before/between/in_rhs,
  incl. the two match `in_rhs @ loop` rows and the destructuring pair) —
  stage B;
- rows are removed from the ledger IN THE LANDING that turns their cell
  clean, per the harness-ledger rule (three artifacts move together).

Cell-to-encoding expectation, stated so an unflipped row is diagnosable:
every binding kind in the block lowers to Slot-encoded fields or scrutinee
temps under today's `_deferred_family` (none of the harness's shapes takes
a literal `move` method argument, renders a whole move-only local, or takes
an address — verified against `_collect_move_arg_receivers`/
`_collect_rendered_names`'s triggers, 877-939) — so no cell waits on a
deferred family, consistent with 2b's disposition. The per-cell proof is
`corodiff --all` at each stage gate, which is the acceptance instrument.

Also retired, with DF-218e's stage: the `DF-218e-2026-08-14` row.

**And one row this migration does NOT claim — the ledger's DF-216g row is
STALE and should be retired NOW, separately.** Probed:
`tools/corodiff.py --filter closure_capture_self --all` and
`--filter method_driven --all` both report 0 hits on that signature (the
only known hits in method_driven are two DF-217p cells) — the stage-3
landing that fixed DF-216g (Aug 14, pin flipped) missed the ledger
retirement, the same miss the DF-217n entry records. A lead hygiene commit
removes it (this spec's worktree does not touch the ledger); if it instead
rides unit 2's first landing, it must be labeled a staleness retirement,
not a fix — an unpromised flip otherwise.

### 5b. Pins that flip, by filename

| pin | DF | flips at | impossibility argument |
|-----|----|----------|------------------------|
| `examples/coro_frame_local_released_at_scope_end.saw` | DF-217p | stage B | Both faces: the loop face because E-FALL clears the iteration's fields before the backedge, so no occupant can survive into the next iteration or past the loop (`after loop` cannot precede the last `DEINIT`); the shadow face because E-REDEF clears the replaced field at the redefinition statement. A missed edge reproduces LATE release (DEINIT-ORDER in the lane), never a double free — `clear()` is the idempotent tag-drop and teardown drops iff occupied (K28) |
| `examples/coro_hoisted_receiver_temp_released_once.saw` | DF-217m | stage D | Section 3 — the statement-end clear leaves no husk for any later statement to hold; exactly-once by the tag |
| `examples/coro_generic_spawn_root_nested_suspending_call.saw` | DF-218e | stage E | Section 4 — no template survives that names a consumed callee, so the re-check has nothing to report; both cells (spawn + ambient) share the one splice |

New pins this spec DEFINES for the pin-promotion batch (XFAIL citing their
DF until their stage lands; behavior-named per policy):

| pin (to create) | pins | source shape |
|-----------------|------|--------------|
| `examples/loop_exit_releases_body_local.saw` | DF-218r (SYNC — no coroutine) | P1b's three cells: break, continue, return-in-loop, deinit-count EXPECTs; flips at stage 0 |
| `examples/coro_done_path_releases_in_scope_order.saw` | DF-218s | P2 `early_return`'s mixed frame-field/real-local shape, EXPECT-OUTPUT `DEINIT inner` before `DEINIT outer`; flips at stage C |
| `examples/conformance/K7x_driven_scope_end_release_matrix.saw` (K-number assigned at landing) | the obligation-3 row: deterministic destruction in a driven body, per scope kind | P1/P2/P3 merged into one matrix file — the scope table's rows SC2-SC8 with the sync outputs as the EXPECTs; lands XFAIL with stage A's dispatch and flips as stages A/B land (or splits into linear/loop halves so each stage flips its half — implementer's choice, declared in the landing) |

Pin-gate accounting: 3 existing pins promised above; 3 new pins defined; 68
+ 1 ledger rows pre-registered; 1 stale ledger row named as NOT-a-flip. An
unflipped promised pin is a missed case; an unpromised flip is an unclaimed
fix; both are review findings.

## 6. Staging

Ordered, each stage its own commit(s), each gated `corodiff --quick` +
full suite + sos both arches per the per-commit policy, with
`corodiff --all` + `irdet --all` at the stage boundaries named below.
Sequential, one implementer — every stage edits the same CFG walk.

| stage | content | flips / retires | gate specifics |
|-------|---------|-----------------|----------------|
| **0 — the oracle fix (DF-218r, sync codegen)** | break/continue run `_cleanup_scope` for the scopes they exit (loops.py:460-505), mirroring return's `_cleanup_all_scopes` down to the loop boundary; the `for` owning-loop-var pop included | flips `loop_exit_releases_body_local.saw` (new pin, lands XFAIL in the same branch first) | full suite + sos; corodiff (the control twins change on break/continue shapes — the lane must stay 0-new); gmgate (release-path change) |
| **A — the scope map + funnel + linear face** | `_uniq_walk_block` records per-block ordered names; the scope stack in `_FrameBuilder`; the shared release-shape helper (1d); E-FALL at the non-loop constructs (SC5/6/7/10) | retires the `@ linear` ledger cells EXCEPT the two scrutinee-temp `in_rhs` rows (stage D's) | `corodiff --all` at stage end; conformance matrix pin lands XFAIL first (obligation 3) |
| **B — the loop face** | E-FALL at loop bodies (SC2), E-BRK/E-CNT (SC3/4), E-REDEF (SC8) | **flips `coro_frame_local_released_at_scope_end.saw`**; retires the `@ loop` cells; the conformance matrix row goes green | `corodiff --all`; the op-budget non-interaction note (section 8) verified by the loop cells themselves |
| **C — the done path (DF-218s)** | E-RET: scope clears innermost-first ahead of `release()` in `_done_seq` | flips `coro_done_path_releases_in_scope_order.saw` | `corodiff --all` (cancel contexts exercise the observed-cancel return path) |
| **D — statement-end temps** | E-STMT: the non-consumed ANF/receiver husk (M3), `__rcvN` (M4), the scrutinee-temp merge release (2c) | **flips `coro_hoisted_receiver_temp_released_once.saw`**; retires `match_consume/in_rhs @ linear` + `match_nobinding/in_rhs @ linear+loop` rows if stage B has not already turned them (the loop halves fall to B; the retirement lands with whichever stage's `--all` run shows the cell clean) | `corodiff --all`; forgetgate (must be byte-identical in emissions — 2b) |
| **E — DF-218e (separable; may also run FIRST or concurrently in its own worktree)** | consumption symmetry at the splice (section 4) + the obligation-4 sweep | **flips `coro_generic_spawn_root_nested_suspending_call.saw`** + the DF-218e ledger row | full suite + sos; corodiff generic contexts (`generic_spawn`/`generic_ambient` gain the nested-call shape — extend the harness's generic axis in the same landing, per the unit-0 precedent that the lane grows with the fix) |
| terminal | — | ledger's DF-217p block count reaches ZERO; the pin gate reconciles (5b) | the FULL battery (compiler branch: every lane incl. reemit/irdet-all/gmgate/bootstrap/sos) |

Consumer sweep (obligation 2 — this migration flips a behavioral contract:
teardown-late → scope-end release in every driven body). Who relies on the
old timing, grepped and reasoned: corodiff ITSELF (the known-list rows ARE
the reliance — retired per stage); the examples corpus (deinit-order
EXPECT-OUTPUT tests — the suite run at every stage is the sweep; any test
that ASSERTED late release is a pin of this bug and flips, none besides the
named pins is known); bench (checksums gate — its programs' stdout must not
depend on deinit order; the lane runs in the terminal battery); blade/libs
(`bootstrap` lane — no deinit-order-observing code known; a driven loop's
`File`/`TcpStream` now closes EARLIER, which is the ruling's point and
strictly widens what works); `--emit-frame-layout` (unchanged — no field
set changes); irdet (IR changes at every stage; determinism, not stability,
is the gate). The op-budget instrumentation interaction is section 8's.

## 7. Open questions for the user's ruling

1. **Done-path ordering (E-RET): ratify sync-LIFO as the contract.** The
   ruling says "exactly as the sync twin does"; probe P2 shows the driven
   done path inverts sync's order today (DF-218s: `DEINIT outer` before
   `DEINIT inner`). The spec reads the ruling as covering ORDER, not only
   scope timing, and stages the fix (C). Ratify — or rule that
   reverse-declaration order at a Done exit is acceptable and the DF-218s
   pin is not owed.
2. **DF-218r sequencing: the sync twin leaks on break/continue, and the fix
   is a SYNC codegen change.** The spec stages it FIRST (stage 0) so the
   twin-parity oracle is right before the loop face lands. Ratify stage 0
   as part of this unit vs splitting it out as its own small fix item
   (it is user-facing and fix-on-discovery-shaped; either way it precedes
   stage B).
3. **The no-control-flow paths keep teardown order.** Probe P4: every
   cancel path exits via ordinary control flow (even cancel-before-start
   runs the body), so scope order holds there with no extra mechanism. The
   paths that release with NO scope structure are panic (releases nothing,
   by design) and the box-teardown of a never-completed frame (the
   deadlock-panic report path and MT teardown of a parked frame) — those
   keep `release()`'s reverse-declaration order. Ratify that boundary (the
   sync analog of those paths is process death, which drops nothing at
   all, so any order there is more than the analog provides).
4. **The scrutinee-temp merge release (2c): ratify the pairing** — the
   DF-210f forget SURVIVES on the consuming arms, the merge-point
   idempotent release closes the non-consuming half, and FAM_SCRUTINEE_TEMP
   stays a cited deferral (narrowed in reach, not retired).
5. **DF-218e fix shape: consumption symmetry** (a generic template naming a
   consumed callee is consumed at the splice) vs re-check exclusion vs
   deferring to unit 1.5. Section 4 recommends the first; rule it.
6. **Scope-end for the DEFERRED families in the legacy spelling (2b).**
   The spec has scope-end cover every owning field, deferred families
   included, via the shared release-shape helper — deterministic
   destruction unconditional, not gated on the Slot migration. The
   conservative alternative (clears for Slot fields only; deferred fields
   keep teardown timing until their family migrates) shrinks the change
   but leaves the guarantee conditional on an encoding detail. Ratify the
   recommended reading.

## 8. Perf note (no measurement owed; what to watch)

The DF-217p ruling accepted the tag cost; scope-end adds RELEASE CODE per
scope exit edge: one idempotent tag-drop per frame-resident binding per
exit (a load, a compare, a conditional drop — the same sequence
`_release_seq` runs once at teardown, now also at each scope edge that owns
fields). The loop face is the hot shape: one clear per frame-resident
loop-body binding per ITERATION, on the fallthrough edge — against which
the accidental put-replace drop it displaces was already paying the drop
half at the same rate, so the net add is the tag test on the
already-cleared path. Statement-end temp clears (stage D) add one tag-drop
per hoisted-temp statement.

Non-interaction with the op-budget instrumentation, stated so nobody
re-derives it: design 127's check sits at the TOP of each loop body
(`_instrument_loop_backedges`, coro_transform.py:419-465 — top placement
covers `continue`), and E-FALL's clears sit at the body's END — so a
budget-forced park at iteration k+1's head holds NO stale iteration-k
locals, which is itself a small win over today (where a park at the head
held the previous iteration's binding until the `put` further down). The
budget `if` is a synthesized statement with no owning locals, so the scope
walk emits nothing for it. No cell where the two mechanisms conflict was
found; if one appears in the stage-B `--all` run it goes to the user, per
the charter.

What to watch, if measurement is ever taken: the bench lane's timing
report (report-only, checksums gate) across stages B and D, and design
127's 1.53x tight-loop figure — the loop-face clear is the only addition
on that path.

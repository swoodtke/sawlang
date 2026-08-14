# Design 218a — the frame primitive module: `Slot<T>` / `Receiver<T>` spec

**Status: DRAFT (spec agent, Aug 13 2026). SPEC ONLY — no implementation.**

## RULINGS (user, Aug 13 — post-review; these supersede the matching text below)

1. **`Receiver<T>` is renamed `UnsafeRef<T>` and becomes an `unsafe struct`**
   (design 130's compiler-enforced `Unsafe*` naming). Read every `Receiver`
   below as `UnsafeRef`. Consequences, ruled with it:
   - Generated resume methods that bind an `UnsafeRef` (or the cell/reactor
     pointers) EMIT the honest `unsafe` declaration — the design-130 rule is
     SATISFIED, not exempted, so **E2 (section 6) DELETES entirely** instead
     of narrowing. Ownership checking inside those bodies is unaffected
     (`unsafe` marks the domain; it relaxes no move/exclusivity rule).
   - **P10b's escape (section 3a) is answered by the marking contract, not
     confinement**: a user who binds an `UnsafeRef` must declare `unsafe`,
     which puts the validity obligation visibly on them — the language's own
     "a precondition is spelled as an unsafe-typed parameter" rule.
   - Calibration note: user closures embedded in an `unsafe`-declared resume
     inherit its unsafe domain on the RE-check (closures inherit the
     enclosing domain, by rule); their pre-transform check ran in the user's
     safe domain, so no user-facing rule weakens.
2. **Module: `std.compiler.frame` (a new `std.compiler.*` namespace for
   compiler-support types), PUBLIC from the start** — `Slot` and `UnsafeRef`
   both, public constructors included. The brief's litmus is thereby
   satisfied COMPLETELY: generated code, minting included, is code a user
   could legally write (in an honestly `unsafe`-declared function). NOT in
   the prelude. Recorded cost (design 144): type identity is
   (module, name), so any future re-homing of `UnsafeRef` to general std is
   a breaking identity change — a deliberate versioned decision if ever.
3. **OQ1 is RATIFIED as recommended** (one type, mode = binding mutability —
   unaffected by the rename). **OQ2 is superseded by ruling 2.**
4. **OQ3 RULED, AMENDED (user, Aug 13): the eager-teardown mechanism becomes
   a TRAIT CONFORMANCE, not a bare synthesized method.** `Resumable` (the
   existing frame-driving trait) RELOCATES to `std.compiler.frame` (public,
   ruling 2) and gains `func release(&var self) sync`; the transform
   synthesizes each frame's conformance body (the safe `clear()` loop of
   census D2); generated Done paths call it directly and group teardown
   dispatches through the `any Resumable` existential it already holds. The
   design-124 eager-timing constraint is unchanged — what changes is the
   mechanism has a NAME in the language, with the invariant documented on
   the trait ("release may run before deinit; deinit is a no-op
   afterward"). One trait, not two: existentials do not cross-cast, and
   every frame needs both capabilities. Costs recorded: the relocation is a
   type-identity move riding obligation 2 (consumer sweep over
   taskgroup.saw's uses), and public `Resumable` is INERT for users
   (conformance grants nothing — the spawn/enqueue surface stays
   compiler-lowered; the docstring says so). D2/D3 and stage 4 read
   accordingly.
5. **OQ4 RULED (user, Aug 13), REFRAMED from carve-out to CORRECT-BY-KIND.**
   A NoMove value needs no occupancy tracking at all: its position is fixed
   at birth, no move in or out is expressible, so exactly-once is
   STRUCTURAL — born in the frame field, dies in the frame field. Slot's
   move-based API is not merely unnecessary for it; it is the wrong shape
   for a pinned value. The plain field is the correct representation, not a
   compromise. The one thing eager teardown still owes (design 124: the
   group's JOIN runs at Done, and the box may outlive Done via an unjoined
   handle) is deinit-in-place at Done plus no second deinit at box death —
   and the placeholder overwrite provides both in one statement:
   `self.g = TaskGroup()` joins the old group where it was born and leaves a
   fresh empty group whose later structural deinit is a cheap no-op. The
   placeholder IS the occupancy mechanism, encoded as value-freshness
   instead of a tag. PROBE-PROVEN (lead, `nomove_replace_probe.saw`):
   whole-value replacement of a NoMove conformer is ORDINARY LEGAL USER
   CODE — old value deinits at the replacement point, exactly once each —
   so the pattern passes the litmus with no exemption and no trust item;
   the D2 TaskGroup row upgrades from "trusted pattern" to "ordinary
   checked code". Unchanged: `Slot<T>` at a NoMove `T` must be REFUSED, and
   that refusal is convention until DF-217j / unit 1.5 lands (the
   enforcement dependency stands).
6. **OQ6 RATIFIED (user, Aug 13):** `self_opt` locals become `Slot<T?>` —
   the extra tag word is accepted; the DF-217b pun (one tag doing double
   duty as optionality and drop flag) becomes unrepresentable.
7. **OQ5 RULED, AMENDED BY THE USER'S LIFO ARGUMENT (Aug 13).** S9's ref
   arguments to sub-frames are STACK-SHAPED and therefore in the SAME
   validity class as `__recv`, not a new manual argument: (a) the sub-frame
   is a FIELD of the caller's frame — outlives-by-construction; (b) the
   caller executes no statement while the call is in flight (its state
   machine is "drive sub to Done"), so nothing can `take`/`clear` the lent
   slot mid-call — suspension parks the whole LIFO chain, it does not
   interleave the caller; (c) spawn, the one construct that breaks LIFO,
   already REJECTS ref arguments (`_reject_spawn_frame_refs`). The
   "occupied and untaken while the handle lives" condition is IMPLIED by
   LIFO + no-statements-mid-call + the spawn rule. CONSEQUENCE: S9
   migrates to `UnsafeRef` in stage 4 under the `__recv` contract
   ("constructed only over storage the drive structure keeps alive") — no
   generation machinery needed; the ledger entry cites this paragraph as
   an INHERITED-from-structure argument, not an asserted one. What stays
   deferred, narrowed to its honest reason: general `[&x]` capture — not
   validity (the direct-to-non-escaping closure kind is LIFO too, and a
   borrow capture cannot consume the slot from inside the body) but
   EXCLUSIVITY DESIGN: the bound-then-called closure kind is genuinely
   non-LIFO (invoked after arbitrary statements, including a `take()` of
   the captured slot) and needs generation-checked handles (the design-134
   `__stale` precedent) or a refusal, plus the two-`[&var x]`-handles
   ordering rules. That is the follow-up brief, if demand appears.
8. **OQ7 RATIFIED (user, Aug 13):** the S10 channel-receive suspect is
   probed BEFORE stage 1 dispatches; if it reproduces it gets a DF and a
   pin on stage 1's flip list.
9. **OQ8 RATIFIED (user, Aug 13):** stage 3 is strictly SEQUENTIAL after
   stage 2. All ten open questions are now RULED; the spec is the
   build-against document.
10. **`dup()` RENAMED `copy()` — as a PLAIN METHOD; the ExplicitCopy
   conformance is DEFERRED to design 219's implementation (user, Aug 13,
   two-step ruling at unit-1 review — post-dates the spec body; read every
   `dup()` below as `copy()`).** The name honors 219's vocabulary now
   (`UnsafeRef` is exactly the trait's shape: move-only, duplicable on
   request, spelled at the call site). The CONFORMANCE waits, for two
   reasons: declaring ExplicitCopy under TODAY'S tier semantics would make
   `UnsafeRef` satisfy current `T: Copy` bounds — admitting it into
   silently-copying generic bodies, benign for a pointer type (a bitwise
   copy IS a valid duplicate under the lifetime-based contract) but
   unruled surface — and the trait-requirement effect-matching question
   (unmarked `copy(&self) -> Self` vs the `unsafe`-marked conformer) is
   219's to answer once, for `Arc` and the blanket Copy-satisfies-
   ExplicitCopy rule too. Nothing in 218 needs the conformance: the
   `[&self]` lowering calls `self.__recv.copy()` by direct method lookup.
   `UnsafeRef` stays NoCopy; 219 adds the one-line conformance when the
   collapse lands.
11a. **OQ7's PROBE RAN (Aug 13, `.build/scratch/probe_s10/` — 17 cells,
   mechanism traced not inferred): S10 is NOT unsound.** The bare alias
   store is tier-CHECKED by the post-transform re-check, so every
   ExplicitCopy/NoCopy channel element is REFUSED (at a 0:0 phantom
   location, wrong noun — filed as DF-218c) rather than double-freed;
   ImplicitCopy elements are retain-balanced (measured, strong-count
   1/2/2/1). CONSEQUENCE FOR STAGE 1: the S10 migration to
   `put(move __rvN)` is the census's one FEATURE FLIP — it makes
   `Channel<Vector<Int>>`/NoCopy receive compile for the first time
   (blocking `recv()` already works; only the driven path refuses). Its
   acceptance tests are the probe's cells 1/1e/10 (compile-error today →
   correct-output after), with cells 1s/4/5 as the unchanged balance
   oracles. No soundness pin owed.
11. **THE TRAIT'S FULL SIGNATURE BECOMES SPELLABLE (user, Aug 13, at
   unit-1 review): `__Poll` → `Poll`, public in `std.compiler.frame`, and
   `Resumable`'s remaining requirements un-prefix in the same relocation**
   (`__wake_reason` → `wake_reason`, `__is_cancelled` → `is_cancelled`,
   the design-158 backtrace method by the same pattern). Principle: a
   public trait's signature must be spellable by its readers — types and
   names both; leaving `__` names would enforce "conformance is inert"
   by UNSPELLABILITY, the wrong mechanism (the enqueue gate is the right
   one, ruling 4). The `__` convention keeps meaning compiler-synthesized/
   not-user-nameable — which a public trait's requirements no longer are.
   Same rename class as `__release` → `release()`; consumer sweep extends
   to the executor/transform references; the taskgroup workaround for the
   unnameable `__Poll` (taskgroup.saw:372-374) should simplify or vanish
   — verify and note.
Charter: design 218 unit 1's pre-step. This document is the exact form the
Opus implementers build against, reviewed by the lead, ruled by the user.
Inputs: the 218 brief (constitution), the DF-217a/b/c/l landed fixes (root
causes confirmed), sweeps S1/S2 + the frame sweep + the coro differential
harness, and a fresh line-level read of `sawc/coro_transform.py`.

Sections 1-10 are the charter's required set; all ten are complete. Probes
live in `.build/scratch/spec218a/` (gitignored), every one compiled and run
against this worktree's sawc with the main checkout's venv; verdicts are
quoted where they are load-bearing.

## 1. Emission census

Every site in `sawc/coro_transform.py` (this branch, post-DF-217a/b/c/l) that
emits a store, read, release, temp, or raw pointer into or out of frame state.
Line numbers are THIS tree's; sweep S2's anchors (`_anf_lift` 1417,
`_uncond_children` 1481) drifted to 1432/1496 here — the DF-217 fixes added
lines above them. Same functions, no contradiction.

Background the rows assume — the FOUR encodings (`_enc_of`,
coro_transform.py:501): `plain` (POD, and TaskGroup for addressability), `opt`
(field is `T?`, the None/Some tag IS the drop flag, read `self.x!`),
`self_opt` (the local is already a `T?`; the field is that same `T?`, its own
tag the flag, read bare — the shape that hid DF-217b), `opt_closure` (`opt`
plus call-rewrite), `ref` (`UnsafePointer<T>`, read `self.x[0]`, never owns).
In the NEW form the three owning encodings (`opt`/`self_opt`/`opt_closure`)
collapse into ONE field shape, `Slot<T>` (section 2); `plain` stays a plain
field; `ref` and `__recv` become `Receiver<T>` (section 3).

### 1a. Stores into frame state

| # | site | file:line | emits today | exact new safe form |
|---|------|-----------|-------------|---------------------|
| S1 | `_store_binding_in_slot` — THE pattern-binding store (entries: `_optbind_dispatch`, `_split_match`) | 3732 | `self.x = move x` when `_frame_read_policy in (nocopy, explicit)`, else `self.x = x`; assignment auto-wraps to `Some` | `self.x.put(move x)` / `self.x.put(x.copy())` / `self.x.put(x)` — `put` takes `T` BY VALUE, so the ordinary call-argument transfer checkpoint demands the tier-correct spelling; a wrong policy answer becomes a compile error on generated code instead of a silent alias/double-move. The policy branch stays only to PICK the spelling; it stops being trusted |
| S2 | `_optbind_dispatch` — `if let`/`guard let` dispatch arm | 4055 | `IfLetExpr` whose Some-arm does S1's store, then `_forgets(...)` incl. the DF-210f hoist-temp forget (4098-4103); both arms run the `move`-scrutinee forgets | Some-arm: `self.x.put(<binding>)`; the scrutinee, when it is a transform temp, is read as `self.__anfN.take()` so no post-hoc forget exists to forget — DF-210f's rule dissolves into the take (see S9/T4). A `move opt` scrutinee reads `self.opt.take()` (one move, tag cleared in the same operation the value leaves by), replacing read + paired `__saw_forget` |
| S3 | `_split_match` — per-arm payload-binding stores + per-arm scrutinee-temp forget | 4225 (stores 4263-4269, forget 4276-4279) | one S1 store per deduped binding name; `_forgets([temp])` on a consuming arm | one `put` per binding; the hoisted scrutinee enters the match as `self.__matchN.take()` ONCE ahead of the dispatch — consuming it before the arms removes the per-arm asymmetry (only the binding arm forgot; a non-binding wildcard arm left the temp occupied, correctly today, but by a rule nobody checks). NOTE: take-ahead-of-dispatch changes WHEN a non-matching value drops (at dispatch, not teardown) — flag for the differential lane |
| S4 | `_split_for` — range-bound stores | 4190 (4201-4204) | `self.i = <lo>; self.__end_i = <hi>` + forgets for `move`d bounds | bounds are `Int`s in practice (`plain`); a non-POD bound is `self.__end_i.put(<hi>)`. Low-risk row |
| S5 | `_lower_inplace` LetStatement — straight-line `let` of a frame local | 5154 | `self.x = <rewritten value>` (+ trailing forgets) | `self.x.put(<value>)` — put's replace semantics (drop old occupant iff occupied) exactly reproduce the optional-assign drop of a rebound `var` |
| S6 | `_lower_inplace` AssignStatement whole-binding target via `_rewrite_assign_target` | 5166 / 4884 | writes the FIELD (`self.out = v`, auto-wrap drops old payload) — a `!` target was DF-196a | same `self.out.put(v)`; the special-cased target rewrite (4902-4906) dissolves — there is no unwrapped spelling to accidentally write through |
| S7 | `_lower_inplace` DestructuringLet | 5130 (5140-5152) | `let __destrsrcN = <v>`; ordinary destructure of `move __destrsrcN` into per-leaf temps; per-leaf moves into fields | unchanged shape, leaf stores become `put`s. The `__destrsrcN` temp is a REAL local (not frame-resident), already checked ordinarily |
| S8 | `_build_frame_init` — frame construction | 5471 | `StructInit` seeding params (`move p` via `_frame_param_arg`, 5453), locals zeroed (`None`/null-ptr/`TaskGroup()`/`_zero_of`), sub-frames zero-init recursively | params: `p: Slot.of(move p)`; locals: `Slot.empty()` — the "not-yet-live = None" convention becomes the type's own empty state, and `_zeroed_value`'s per-encoding branching (5433) collapses. `ref` fields and `__recv` seed `Receiver`s; `plain`/scheduler words unchanged |
| S9 | `_build_sub_frame` — nested-call arguments | 4732 | `self.__subN = __Frame_g(<rewritten args>)` + forgets for args moved out of the caller frame; `ref` args cast `&self.x` → `UnsafePointer<T>` (4750-4752) | args that consume a caller slot read `self.x.take()` — the forget list empties; `ref` args build `Receiver(&var self.x.value())`? NO — see section 3 open question OQ5: a Receiver over a slot payload needs the lend machinery, and the interim form keeps the cast but sources it from a place lend. Ref-arg rows are the LAST migration stage for this reason |
| S10 | `_emit_recv_call` — channel-receive result store | 4573 (4606-4607) | `self.<target> = __rvN` — a BARE alias store of the `if let __rvN = try_receive()` binding; does NOT go through `_store_binding_in_slot`, so it is TIER-BLIND | `self.<target>.put(move __rvN)` — and the census flags this row as a SUSPECT today: for a NoCopy/ExplicitCopy channel element the alias store + the binding's own scope-exit drop look like the DF-210b shape in reverse. UNVERIFIED (no probe run — S3-pending; the differential lane's channel axis should carry it). Recorded per charter: census findings are recorded, not fixed here |
| S11 | `_make_spawn_helper` — spawn-argument stores + cell wiring | 5808 | `__Frame_f(<move p>..., __cellp: __cellp)` boxed and `move`d into `__enqueue`; `__rp`/`__cp` raw pointers into the cell (5820-5821) | param stores become `Slot.of(move p)` like S8. The CELL pointers stay raw and stay TRUSTED (they cross the executor seam; the cell is design 134's stable heap slot) — they move to the section-2 trusted list, not to Slot |
| S12 | `_emit_blk_call` — offload job handle store | 4504 (4533) | `self.__blkjobN = __saw_blk_start(...)` — an `Int` job word | unchanged (`plain` POD); the runtime seam owns the job's lifecycle |

### 1b. Reads out of frame state

| # | site | file:line | emits today | exact new safe form |
|---|------|-----------|-------------|---------------------|
| R1 | `_read_field` — THE frame read funnel | 600 | `self.x` / `self.x!` / `self.x[0]` per encoding; stamps `frame_place_read` always, `frame_owning_read` (non-move whole-binding read), `frame_move_read` (paired with `__saw_forget`) | three Slot forms replace the marks: borrow → `self.x.value()` (a `borrows` lend, the place system does what `frame_place_read` hand-asserts); owning non-move read → the use site's own tier spelling against the lend (`self.x.value()` copies at the tier, exactly design 131's table — `frame_owning_read` retires); move read → `self.x.take()` (`frame_move_read` + `__saw_forget` retire as one unit). `ref` encoding → `Receiver.deref()` |
| R2 | `_rewrite_expr` MoveExpr arm | 4854 | field read with `move_read=True`, appends to `forgets`; re-applies `!` for `move o!` | `self.x.take()`; `move o!` becomes `self.o.take().take()!`? No — the local IS the optional (`self_opt`): `self.o.take()` yields the `T?`, then ordinary `!`/`take()` on it. One `take`, then source-level optional consumption — both checkable |
| R3 | `_rewrite_expr` Identifier arm | 4874 | field read, `owning_read=True` | `self.x.value()` lend; a transfer position then copies out of the window at the payload's tier — the checker judges it, codegen's `_frame_owning_read_copy` (codegen/resources.py:1616) retires |
| R4 | `_rewrite_expr` SelfExpr arm — the method receiver | 4843 | `self.__recv[0]` raw deref, `frame_place_read` stamped by hand | `self.__recv.deref()` — the Receiver lend; forwarding to methods/fields is the places system (section 3) |
| R5 | `_sub_result_read` + its two callers in `_emit_nested_call` | 821 / 4649-4692 | `self.__subN.__result` (+`!`) with a paired `__saw_forget`; discarded result: `self.__subN.__result = None` | `self.__subN.__result.take()`; the discard is `self.__subN.__result.clear()` — the drop happens at the statement that discards, same as today, but idempotence is the type's, not the tag convention's |
| R6 | driver result move-out (`_make_driver`) | 5661-5675 | `__f.__result` read (+`!`), `__saw_forget`, `move __res` | `let __res = __f.__result.take()` then `move __res` — the forget vanishes |
| R7 | `_materialize_closure_captures` — capture reads | 5008 (policy branch 5072-5100) | per-`_frame_read_policy`: nocopy → move-read + forget; retain/trivial → `frame_owning_read` read; explicit → `.copy()`; then `let __capN_x = <read>` + `[move __capN_x]` spec | `let __capN_x = self.x.take()` / a tier copy out of `self.x.value()` / `self.x.value().copy()` — the branch picks the SPELLING, the checker enforces it; DF-217c's class (a caller inventing its own read discipline) has no unchecked spelling left to invent. `[&self]` captures skip materialization entirely (section 4) |
| R8 | `_result_place` / `_cancel_place` — spawn-root cell access | 3205 / 3213 | `self.__cellp[0].__result` / `.__cancel` raw derefs | stays TRUSTED (design-134 seam, same status as S11's pointers). Census row exists so the trusted list is complete, not to migrate it |

### 1c. Temps (the transform's own bindings)

| # | site | file:line | emits today | exact new safe form |
|---|------|-----------|-------------|---------------------|
| T1 | `_hoist_cond` `__hoistN` | 1195 | `let __hoistN = f()`; registered in `_hoist_temps` so `_optbind_dispatch` can forget it (DF-210f) | the temp becomes an ordinary frame slot; the binding store reads `self.__hoistN.take()` — registration dissolves (S2) |
| T2 | `_maybe_hoist_try` `__trycallN` | 1263 | `let __trycallN = <call>`; the try consumes it via a synthesized `MoveExpr` — the ONE temp family that already has consume bookkeeping in the source shape | unchanged in shape; the `move` lowers to `take()` like every user move (R2) |
| T3 | `_maybe_hoist_match` `__matchN` | 1319 | `let __matchN = <call>`, registered in `_hoist_temps`; consuming ARMS forget it (S3) | `self.__matchN.take()` ahead of dispatch (S3) |
| T4 | `_anf_lift` `__anfN` — the DF-217h class | 1432 | `let __anfN = <suspending call>` with NO consume bookkeeping: not in `_hoist_temps`, no forget when a parent call consumes it by value — the nine-position double-drop (S2 sweep a1/a3/a5/a6/b1-b4, d4, m7, m13/14/16/17, n3b, p4) | the temp is a `Slot`; the parent position reads `self.__anfN.take()` when the parameter consumes and `self.__anfN.value()` (borrow) when it does not. The which-positions-consume matrix DF-217h's fix owes becomes a per-argument tier question the CHECKER answers: emitting `take()` for a non-consuming position leaves an emptied slot whose later read panics loudly; emitting a borrow for a consuming position is the transfer error. No silent double-drop is expressible — teardown drops iff occupied, and `take` made it unoccupied. Contrast row: `_vc_hoist_to_temp` (1753) registers its temp as a typed frame local; the asymmetry S2's funnel analysis named disappears because BOTH become Slots with the same read discipline |
| T5 | `_vc_hoist_to_temp` `__vchN` + `_vc_stmt` `__vcN` | 1753 / 2009-2042 | `let __vchN = <conditional>` registered in `_extra_frame_locals`; `__vcN` binds a `??`/`?.` payload in the branch lowering | Slot rows like T4; the `__vcN` binding is a pattern binding → S1/S2 territory |
| T6 | `_lower_inplace` `__destrsrcN` | 5140 | fresh straight-line local, consumed by `move` in the same statement list | already ordinary checked code; no change |
| T7 | `_emit_recv_call` `__rvN`/`__haveN`/`__rcvN` | 4573 / fields 3149-3154 | `__haveN: Bool` (plain), `__rcvN: T?` discard holder (self_opt, dropped by `__release`) | `__haveN` unchanged; `__rcvN` a `Slot<T>` whose occupant the teardown drops; `__rvN` see S10 |
| T8 | `_emit_blk_call` `__blkjobN` | 4504 | `Int` handle | unchanged |

### 1d. Releases, teardown, cancel, panic

| # | site | file:line | emits today | exact new safe form |
|---|------|-----------|-------------|---------------------|
| D1 | `_forget_stmt` / `_forgets` | 4783 | `__saw_forget(self.x)` — clears the drop flag WITHOUT reading; correctness rests on being paired with exactly one prior consuming read | RETIRES ENTIRELY. Every pairing becomes a single `take()`. `__saw_forget` remains only if a non-Slot consumer exists after unit 2; the migration's exit criterion includes grepping the transform for zero emissions |
| D2 | `_release_seq` — the `__release` body | 5365 | per owned field, reversed: `self.x = None` (opt encodings); TaskGroup placeholder overwrite `self.g = TaskGroup()` (5399); `io_unwait` first (DF-134a) | per owned field: `self.x.clear()` — idempotent by the type (clear of empty is a no-op), so the box's later memberwise teardown stays a no-op double-drop-free, now by construction. `io_unwait` unchanged (scheduler seam). TaskGroup row unchanged — a NoMove value cannot live in a Slot (section 2, tier table) and keeps its plain-field + placeholder pattern |
| D3 | `_release_call` sites — `_done_seq` (every `return`), `_emit_nested_call` is_ret tail | 5308 / 4664 | `self.__release()` at both Done exits | unchanged wiring; the BODY is D2's. Long-term (unit 2's last stage) `__release` could become the frame's ordinary deinit prefix, but eager-at-Done vs box-death timing (design 124) requires the explicit early call to survive — the spec KEEPS `__release`, migrated to safe code, and does NOT promise its deletion. This narrows the 218 brief's "retires in favor of ordinary structural deinit": structural deinit covers the box-death path; the eager path keeps a synthesized-but-safe `__release`. Recorded as a deliberate deviation for the lead |
| D4 | cancel path — `_cancel_place` reads, sub-frame cancel propagation, blk park-loop bail | 3213 / 4710 / 4539-4541 | cancel is COOPERATIVE: flag reads, no forced teardown; a cancelled task exits via its own control flow → `__release` runs | unchanged mechanism. S3-PENDING: no sweep has verified slot states on cancel-mid-suspend / io-parked-cancel paths; rows carried as unverified behavior, to be pinned when sweep S3 runs |
| D5 | panic path | (no transform site) | a Saw panic aborts the process — no unwinding, no frame teardown runs | out of scope for Slot; S3-PENDING row for group/MT contexts (a panic on a worker thread) |
| D6 | box teardown of a completed-but-unjoined frame (memberwise struct deinit over the frame fields) | codegen/resources.py (struct teardown; not a transform site) | opt-encoded fields drop iff Some; `__result` survives to `join`/teardown | Slot's synthesized deinit (drop iff occupied) is EXACTLY this; the convention becomes a type property. `__result` remains a Slot the cell/join machinery takes from |

### 1e. Raw pointers into/out of frame state

| # | site | file:line | emits today | exact new safe form |
|---|------|-----------|-------------|---------------------|
| P1 | `__recv` field + seed + deref | 3134 / 4756-4766 / 4843 | `UnsafePointer<Struct>` field; seeded `&(<rewritten receiver>) as recv_type`; read `self.__recv[0]` | `Receiver<Struct>` (section 3): field is the safe struct; seed `Receiver(&<place>)` (construction is the verified-unsafe part); read `self.__recv.deref()` |
| P2 | `ref`-encoded locals/params (design 88) | 501-515 / 4750-4752 / 5680-5683 | `UnsafePointer<T>` fields, null-init, driver params take raw pointers, spawn REJECTS refs (`_reject_spawn_frame_refs`, 5707) | `Receiver<T>` in mut/shared mode (section 3a); the drive-site cast remains the verified construction site; spawn confinement rule unchanged |
| P3 | `__io_tok` — address of `__wake` as Int | 3597-3607 | `(&self.__wake) as UnsafePointer<Int> as Int` | TRUSTED (reactor seam, design 91). Listed for completeness |
| P4 | `__cellp` / `__rp` / `__cp` | 3182 / 5819-5821 | cell pointer plumbing (design 134) | TRUSTED (S11/R8) |

Completeness: the census covers every emission the charter names plus S4, S6,
S10, S12, T5-T8, D4-D6, P3-P4 found by the read. NOT covered, and why: the
generic-instance machinery (`_promote_nested_generic_calls`, 6280) — unit 1.5
deletes it, so specifying its Slot form would spec dead code; the spawn
trampoline (`_make_spawn_trampoline`, 5975) — its body is already "ordinary
Saw that the post-transform typecheck reads" (its own docstring) and it owns
no slots; and codegen-side emitters (design 218 units 3-4's territory).

## 2. `Slot<T>` — exact API

```saw
/// A coroutine frame's owning storage cell. Occupancy is the `T?` tag —
/// design 44's "the None/Some tag IS the drop flag", promoted from a
/// per-emission convention to a type invariant.
struct Slot<T> {
    v: T?                                  // PRIVATE (design 80)
}

extension Slot<T>: NoCopy {}               // a slot is storage, never a value

extension Slot<T> {
    /// An empty slot — the not-yet-live state every frame local starts in.
    static func empty() -> Slot<T> { Slot<T>(v: None) }

    /// A slot born holding `value` — the frame-init state of a parameter.
    static func of(value: T) -> Slot<T> { Slot<T>(v: move value) }  // auto-wraps

    /// Install `value`. Drops the previous occupant iff occupied (replace
    /// semantics — a rebound `var` across suspends re-puts). Never panics.
    /// The `move` is REQUIRED, not style: probe P4's first run omitted it,
    /// compiled (abstract `T` demands nothing — DF-217i), and triple-freed
    /// at runtime. Explicit `move` is correct at every tier (section 3b).
    func put(&var self, value: T) { self.v = move value }           // auto-wraps

    /// Move the occupant out, leaving the slot empty.
    /// PANICS (`panic at FILE:LINE: Slot.take: slot is empty`) on an empty
    /// slot — the transform's state machine is the proof of occupancy, and a
    /// wrong proof must be LOUD, not a silent husk read.
    func take(&var self) -> T { self.v.take()! }

    /// Drop the occupant iff occupied; empty afterwards. Idempotent — this is
    /// `__release`'s per-field body, and re-running it is a no-op.
    func clear(&var self) { self.v = None }

    func is_occupied(&self) -> Bool { self.v.is_some() }

    /// Lend the occupant as a PLACE (design 141/146): reads, writes, method
    /// calls and nested place hops happen in the slot's own storage. The use
    /// site picks shared vs exclusive out of this one `&self` declaration.
    /// PANICS on an empty slot (direct accessors panic — the accessor rule).
    func value(&self) borrows -> T {
        if not self.v.is_some() { panic("Slot.value: slot is empty") }
        lend self.v!
    }
}
```

Bodies shown are NORMATIVE shape, not final code (probe P7, section 3b, must
confirm `lend self.v!` is a legal receiver-rooted lend; if not, the fallback
is a one-case-enum payload lend per DF-146d, same surface). Note what is NOT
here: **`Slot` is ordinary safe Saw.** The type carries no `unsafe` anywhere —
the manually-verified part of unit 1 is (a) the USE contract the transform
compiles against (occupancy proofs from the state machine) and (b) `Receiver`
(section 3), which is where the raw pointer actually lives. That is a
narrower trusted base than the 218 brief sketched, and it is a finding of
this spec, not a deviation: the brief's "Slot and friends, manually verified"
becomes "Slot verified BY THE CHECKER like any user type; Receiver manually
verified".

**Occupancy representation.** The private `T?`. Same layout and same tag the
`opt` encoding uses today, so frame size does not change for the migrated
fields; `self_opt` locals (the local is already a `T?`) become
`Slot<T?>` — one honest extra tag instead of the pun that caused DF-217b
(the pun made "the field is the local" and "the field wraps the local"
indistinguishable to every downstream consumer).

**Panic conditions.** `take` and `value` panic on empty, with `panic at
FILE:LINE:` naming the method (design 122). `put`/`clear`/`is_occupied`/
`empty`/`of` never panic. No allocation happens in any method (`T?` of a
sized `T` is inline), so design 123 owes no `try_` twins.

**Excluded, per the perf ruling (user, Aug 13):** no `try_take`, no
`unchecked_take`/`unchecked_put`, no tag-elided variant of anything. The tag
cost is accepted for the migration; the earn-back is unit 5's PROOF-driven
elision (occupancy = f(resume index), derived per frame by a late pass, tags
dropped only where the proof discharges) — an optimization of this exact
model, not an API the transform can reach for and misuse.

**Tier interactions.**

| tier of `T` | `put` argument | read out of `value()` | `take` |
|---|---|---|---|
| trivial | bare | bare (bitwise) | yes |
| ImplicitCopy | bare (arg transfer retains) | free retain | yes |
| ExplicitCopy | `move x` / `x.copy()` | `.copy()` or clean error | yes |
| NoCopy | `move x` | borrow only; value read is a clean error naming `take` | yes |
| NoMove | **REFUSED — a NoMove value never enters a Slot.** `put`/`take` are moves, which NoMove forbids (design 188) | — | — |

The NoMove row is load-bearing twice. First, it keeps the census's D2 rule:
a frame-resident `TaskGroup` stays a PLAIN field with the design-62-G1
placeholder pattern — Slot does not replace it. Second, it depends on the
containment cascade being derived per instantiation, which DF-217j says it
is NOT today: `Slot<TaskGroup>` would currently compile (the exact
`Wrap<TaskGroup>` shape of S1 row 4d/4f2). The transform never emits one —
but "the transform never emits one" is precisely the kind of trusted
bookkeeping this design exists to retire, so the spec records the
dependency: DF-217j's fix (or unit 1.5's instance re-check) is what makes
the NoMove row COMPILER-enforced rather than convention-enforced.

**The exactly-once-release argument (the property of the type).** A payload
leaves a slot by exactly four operations, and every one of them updates the
tag IN THE SAME METHOD BODY that moves or drops the payload:

1. `take` — payload moves out, tag goes None, one expression;
2. `clear` — payload drops, tag goes None, one assignment;
3. `put` on an occupied slot — old payload drops as part of the optional
   assign, new payload installs;
4. deinit — the SYNTHESIZED structural deinit of the `v: T?` field drops the
   payload iff the tag says Some. No hand-written deinit exists to get wrong;
   design 139's wrapper rule is the whole mechanism.

The field is private, so no caller can reach the tag or the payload except
through 1-4. Therefore "released exactly once" stops being a THEOREM ABOUT
EMISSION PAIRS — today's model, where the read (`self.x!`) and the tag clear
(`__saw_forget(self.x)`) are two separate statements any site can mispair,
and DF-206f, DF-210f and DF-217h are three sites that mispaired them — and
becomes a local property checked once at the type: no sequence of Slot calls
double-drops (the tag gates every drop) and no sequence leaks past deinit
(the tag was live, deinit fires). What a WRONG transform emission can still
do is panic (take on empty) or drop earlier/later than intended (clear vs
take choice) — liveness/timing bugs, loud or observable in the unit-0
differential lane, never memory unsafety. That is the calibrated claim: the
DF-217 OWNERSHIP class becomes unexpressible; the timing class stays testing
territory, exactly as the 218 brief's layer 3 says.

## 3. `Receiver<T>` — exact API

The ruled direction (the brief's DF-216g paragraph): a SAFE struct holding
the raw pointer — the Vector pattern — with ONE verified-unsafe `borrows`
accessor lending the referent as a PLACE, so forwarding is the places system,
not delegation magic.

```saw
/// A non-owning handle to a value that outlives it — the coroutine frame's
/// receiver (`__recv`) and its `ref`-encoded locals, as a type instead of a
/// rewrite convention. The VALIDITY argument (the pointee outlives every
/// deref) is the manually-verified part of design 218 unit 1: it holds
/// because the transform only constructs one over storage the drive
/// structure keeps alive (a driven frame's referent outlives the drive —
/// design 88's confinement, unchanged), and because no user code can
/// construct one at all (private field, no public init — see CONFINEMENT).
unsafe struct UnsafeRef<T> {               // RULED name+marking (header block)
    p: UnsafePointer<T>
}

extension UnsafeRef<T>: NoCopy {}

extension UnsafeRef<T> {
    /// Lend the referent as a place. The use site picks shared vs exclusive
    /// out of this one `&self` declaration; the WINDOW MODE is governed by
    /// the mutability of the receiver-typed BINDING (see 3a). `unsafe` in
    /// the effect slot because the body names the pointer — the same
    /// declaration `Vector.[]` and `Data.[]` carry (std/vector.saw:127).
    func deref(&self) unsafe borrows -> T { lend self.p[0] }

    /// Mint a second handle to the same referent. Named and countable —
    /// Receiver is NoCopy precisely so duplication is never silent; this is
    /// the one sanctioned spelling, used by the `[&self]` lowering (section
    /// 4), where the frame must KEEP `__recv` and the closure env needs its
    /// own handle. Sound because validity is lifetime-based, not
    /// uniqueness-based: a duplicate constrains nothing the original did not.
    func dup(&self) unsafe -> UnsafeRef<T> { UnsafeRef<T>(p: self.p) }
}
```

Construction: `UnsafeRef<T>(p: <ptr>)`, PUBLIC (ruling 2) — the constructor
receives an unsafe-typed value, so any minting function is `unsafe`-declared
by the design-130 rule, which is the obligation carrier. The
transform's seed sites (census P1/P2) build the pointer exactly as today
(`&(<place>) as UnsafePointer<T>` / the drive-site cast) and wrap it; the
cast is the unsafe crossing the skill already documents as the language's
only address-of.

### 3a. Receiver-mode typing — settled, with a recommendation

The constraint: a `&self` method's receiver must not obtain an exclusive
window. Two designs considered:

- **Two types** (`Receiver<T>` shared / `ReceiverMut<T>` exclusive). Honest
  in the type, but blocked twice today: an accessor cannot be declared
  SHARED-ONLY (the design-146 v1 fence — the flavor is always the use
  site's), and pointer mutability does NOT survive the surface cast — probe
  **P6** (`p6_shared_mode.saw`): a pointer built from a shared `&t` writes
  through the lend under a `var` root, cleanly compiled. So the shared type
  would have no mechanism to refuse the write short of new language surface.
- **One type, mode = binding mutability** — RECOMMENDED, because the
  machinery already exists and refuses correctly, probe-proven:
  - **P3** (`p3_let_write.saw`): a write through a `let`-rooted receiver is
    refused — `cannot open an exclusive place window on immutable variable
    'cap'` — the place system's own root-mutability rule.
  - **P8** (`p8_closure_write.saw`): the refusal SURVIVES value-capture into
    a closure — a `let`-captured receiver refuses the write inside the body.
  - **P8b**: a `var`-captured receiver writes and the write persists.
  So the transform (and the `[&self]` rule) emits: `&self` method →
  let-bound Receiver (shared: reads, `&self` method calls); `&var self`
  method → var-bound (exclusive available). The mode is CHECKED, not
  trusted: a wrong emission is P3's compile error.

**The escape that makes confinement load-bearing — probe P10b**
(`p10b_move_reroot_spec.saw`): a body holding a `[move cap]` capture can
`var c2 = move cap` and write through the re-rooted binding. Binding
mutability alone therefore cannot hold the shared mode against arbitrary
user code. It does not need to: (1) Receiver is std-internal with NO public
constructor, so the only Receivers in existence are transform-built; (2) in
the `[&self]` surface the handle's NAME is transform-minted (`__capN_self`)
— the user's body says `self.n`, and you cannot `move` a name you cannot
spell; (3) any hand-rolled equivalent requires the `as UnsafePointer<T>`
cast, which forces `unsafe` onto the author's own declaration (design 130),
putting the soundness obligation where it belongs. Recorded so the
implementer knows the private field IS the security boundary.

### 3b. Lend coverage — probe results (`.build/scratch/spec218a/`, main venv
against this worktree's sawc)

| # | postfix form the rewrite needs | probe | verdict |
|---|-------------------------------|-------|---------|
| 1 | field read `r.deref().a` | p1_read.saw | COMPILES, correct value |
| 2 | `&self` method call `r.deref().get_a()` | p1_read.saw | COMPILES, correct |
| 3 | nested place hop, read `r.deref().inner.n` | p1_read.saw | COMPILES, correct |
| 4 | field write `r.deref().a = 7` (var root) | p2_write.saw | COMPILES, persists |
| 5 | compound assign `r.deref().a += 1` | p2_write.saw | COMPILES, persists |
| 6 | `&var self` method call `r.deref().bump()` | p2_write.saw | COMPILES, persists |
| 7 | nested place hop, write `r.deref().inner.n = 42` | p2_write.saw | COMPILES, persists |
| 8 | write under a LET root | p3_let_write.saw | CLEAN REFUSAL (the mode carrier) |
| 9 | generic receiver `Recv2<T>` | p7_generic_recv.saw | COMPILES, both read and write |
| 10 | by-value closure capture, read in body | p5_closure_cap.saw | COMPILES, reads the live referent (the DF-216g shape) |
| 11 | closure write, let capture | p8_closure_write.saw | CLEAN REFUSAL |
| 12 | closure write, var capture | p8b_closure_write_var.saw | COMPILES, persists |
| 13 | suspending call inside the window expression | p9_window_suspend.saw | CLEAN REFUSAL (`cannot suspend in a sync closure context`) |
| 14 | Slot's own lend `lend self.v!` (optional payload, generic) | p4_slot_lend.saw | COMPILES; full put/take/replace/clear round trip deinit-exact |

**No gaps.** Every postfix form the receiver rewrite needs is supported by
one `borrows` lend today. The one thing the probes CHANGED in section 2:
`Slot.of`/`put` generic bodies MUST spell `move value` — the first P4 run
omitted it, compiled (abstract `T` demands nothing — DF-217i), and
triple-freed r1 at runtime. The trusted core is itself inside DF-217i's
blast radius until the abstract-T ruling lands; explicit `move` is correct
at every tier and is the required spelling. `take`'s normative body, for the
named panic (a bare `self.v.take()!` would panic as `force unwrap of None`):

```saw
func take(&var self) -> T {
    guard let out = self.v.take() else { panic("Slot.take: slot is empty") }
    move out
}
```

### 3c. The window-never-spans-a-suspend invariant

Stated: **a `Receiver.deref()` (or `Slot.value()`) window is a place window,
its extent is the smallest enclosing expression, and no suspension point may
occur inside that extent.** Already enforced by the design-146 v1 fence (a
`borrows` body is `sync`, and the window expression is a sync region) —
probe P13 above shows the refusal firing on `r.deref().a = slow()`. The
transform must therefore never emit a deref window whose expression contains
a hoistable suspend — which it cannot, because the ANF hoist runs FIRST and
leaves only sync residue in expression positions; the invariant is
belt-and-suspenders, checked by the compiler either way. Conformance row
(obligation 3, written with unit 1): `examples/conformance/
K27_receiver_window_never_spans_suspend.saw` — the P9 shape with EXPECT
directives on the refusal text.

## 4. The `[&self]` capture (DF-216g, folded in whole — no interim diagnostic)

**Grammar.** `_parse_capture_list` (parser/expressions.py:1503) accepts only
`IDENT` as the capture name, so `[&self]` is a parse error today. The change:
after the `&` / `&var` mode markers, accept the `self` keyword —
`CaptureSpec(name="self", mode="ref"/"ref_var")`. ONLY behind a `&` sigil:
bare `[self]` and `[move self]` stay parse errors, preserving design 216's
decision (the receiver's own mode dictates the capture mode; a spelling that
could contradict it is not offered — a consuming `self` receiver is an owned
binding and takes the ordinary implicit value capture with no list). Scope of
the grammar change: one arm in `_parse_capture_list`; both lexers already
tokenize `self` (keyword), so lexdiff/astdiff parity costs are nil beyond the
new AST shape.

**What the typechecker rules.** The design-216 predicate — *a capture that
lowers to a pointer into the enclosing frame is legal only in a closure
passed directly to a non-escaping parameter* — gains `[&self]`/`[&var self]`
as a fourth SPELLING of the same rule (beside implicit `self`, explicit
`[&x]`, and reference-typed bindings). Two added checks: (1) `[&var self]`
requires a `&var self` method — in a `&self` method it is refused with a
fixit naming `[&self]`; (2) `[&self]` in a method whose closure body WRITES
through `self` gets the mode error at the write (which the place system
already produces — probe P8's refusal text — the check only needs to anchor
it well). An explicit `[&self]` and an implicit `self` in one closure are the
same capture; the explicit spelling exists so the transform can EMIT what a
user could have written (the brief's litmus), not to mean anything new.

**What the transform emits.** In a SYNC method nothing changes — the landed
216 env-of-reference lowering already serves both spellings. In a SUSPENDING
method (the DF-216g ICE), `_materialize_closure_captures` (census R7) gains a
receiver arm that REPLACES value-snapshot materialization for `self`:

```saw
// method frame, __recv: Receiver<Counter>; method declared &self
let __cap0_self = self.__recv.dup()          // shared mode: LET binding
run_int({ [move __cap0_self] in __cap0_self.deref().n + 1 })
```

- the closure env captures the `Receiver` HANDLE by value (`[move
  __cap0_self]` — the same move-capture discipline every materialized
  capture uses, DF-196e's fresh-name rule included);
- every `SelfExpr` inside the closure body rewrites to
  `__cap0_self.deref()` — so `self.n` becomes `__cap0_self.deref().n`, and
  the whole postfix zoo (section 3b's 14 rows) is the places system doing
  what the receiver rewrite needs, with no new lowering;
- mode: `&self` method → `let` materialized binding (P8: writes refuse);
  `&var self` method → `var` (P8b: writes persist);
- `dup()` exists exactly for this site: the frame KEEPS `__recv` for later
  resumes, so the handle cannot be moved out — it is duplicated, visibly.

Probe P5 (`p5_closure_cap.saw`) is this lowering hand-written: a Receiver
captured by value, `deref().a` read in the body, correct value out. The
generated form is code a user could legally write, modulo the module gate on
`Receiver` construction — the handle it duplicates was built by the
transform, and `dup`/`deref` are ordinary method calls.

**Acceptance test:** the existing pin
`examples/closure_captures_self_suspending.saw` (XFAIL: DF-216g) — two
closures reading `self.n` across two suspends in a `&self` method, expected
output `16`. Pre-registered on unit 2's flip list (section 7).

**`[&x]` of arbitrary frame locals in suspending bodies: DEFERRED.** The
receiver case stands on `__recv` — a pointer that exists for the frame's
whole life and never moves. A general `[&x]` over a frame LOCAL would need a
pointer INTO a slot's payload storage (a `payload_ptr` on Slot), whose
validity condition — the slot stays occupied and un-taken while the handle
lives — is a NEW manual argument the receiver case does not need, and whose
aliasing is invisible to exclusivity (the Law cannot see through a raw
pointer, so `self.x.take()` while a derived Receiver window is open would be
a silent invalidation the checker cannot refuse). That is a real design, not
a rider. The exclusivity row it owes, stated now per the charter: **a
Receiver derived from slot storage aliases the slot, and no checked rule
orders their accesses — deferring keeps the trusted validity argument at
"pointee outlives the frame body", which `__recv` satisfies structurally and
slot payloads do not.** Today's behavior for `[&x]` of a frame local
(materialize-a-copy, then borrow the copy — `_materialize_closure_captures`
5044-5051 keeps a spec'd name and materializes under it) is itself
suspicious — a `[&var x]` writes the materialized copy, not the frame slot —
but that is a pre-existing question for the tracker, not this unit (flagged
for the lead; not verified by probe here).

## 5. Worked examples

Current forms are derived from the transform read (anchors per line) and
validated with `--emit-frame-layout` + runs on
`.build/scratch/spec218a/ex_a_owning_local.saw` / `ex_c_hoisted_arg.saw`;
both dumps confirm the field sets shown. The new forms are code a user could
legally write (the brief's litmus) — every one of their operations is probed
green in section 3b.

### A. A suspending function with an owning local

```saw
func work() -> Int {
    let r = Res(name: "r1")     // NoCopy
    yield_now()
    let n = r.name.len()
    n
}
```

CURRENT (frame `__Frame_work`: `r: Res?` — opt encoding; run confirms one
DEINIT, before the result prints — eager release at Done):

```saw
struct __Frame_work { r: Res?, __state: Int, __wake: Int, __io_tok: Int,
                      __cancel: Bool, __result: Int }
// resume, state 0:                                  anchors
self.r = Res(name: "r1")        // _lower_inplace let  (5158; auto-wrap Some)
// suspend (__wake = 0, __state = 1, return Pending)
// state 1:
let n = self.r!.name.len()      // _read_field opt     (665; frame_place_read)
self.__result = n
self.__release()                // _done_seq            (5308)
// __release body: self.r = None // _release_seq        (5389)
```

Every `self.r!` read is trusted: the `!` hides the place from the checkpoint,
`frame_place_read` tells the re-check to look away (types.py:2665, 3235).

NEW:

```saw
struct __Frame_work { r: Slot<Res>, __state: Int, __wake: Int, __io_tok: Int,
                      __cancel: Bool, __result: Slot<Int> }
// state 0:
self.r.put(Res(name: "r1"))
// state 1:
let n = self.r.value().name.len()   // shared window; borrow is free
self.__result.put(n)
self.__release()                    // body: self.r.clear()
```

No mark, no forget, no `!`. A wrong emission — say `put(r)` where `r` is a
NoCopy local — is the transfer checkpoint's ordinary error, in generated
code.

### B. The DF-216g shape (the pin, `closure_captures_self_suspending.saw`)

```saw
extension Counter {
    func slow(&self) -> Int {
        task.yield_now()
        let a = run_int({ self.n + 1 })
        task.yield_now()
        a + run_int({ self.n * 2 })
    }
}
```

CURRENT: ICE. The capture is judged pre-transform where `self` is the
receiver; the rewrite rebinds `self` to the frame (`self.__recv[0]`,
_rewrite_expr:4843), and `_materialize_closure_captures` (5008) has only a
VALUE-snapshot answer, which contradicts the 216 borrow ruling and cannot
work for a NoCopy receiver. There is no current generated form to show —
that absence is the finding.

NEW (frame `__Frame_Counter_slow`: `__recv: Receiver<Counter>`, `a:
Slot<Int>`):

```saw
// state 1 (after the first suspend):
let __cap0_self = self.__recv.dup()               // &self method -> LET
let __anf_a = run_int({ [move __cap0_self] in
    __cap0_self.deref().n + 1 })                  // probe P5's exact shape
self.a.put(__anf_a)
// state 2 (after the second suspend):
let __cap1_self = self.__recv.dup()
self.__result.put(self.a.value()
    + run_int({ [move __cap1_self] in __cap1_self.deref().n * 2 }))
```

The pin's expected output (16) is the acceptance test; the closure reads the
LIVE receiver both times.

### C. The DF-217h shape (the pin, `coro_hoisted_call_arg_consumed_once.saw`)

```saw
func main() { sink(mk_res_s(3)); print("done") }   // sink consumes by value
```

CURRENT (frame `__Frame_main`: `__anf0: Res?` own field + `__sub0:
__Frame_mk_res_s`, layout dump confirms; run reproduces the bug — `sink r3`,
`DEINIT r3`, `done`, then `DEINIT ` reading a husk):

```saw
// ANF hoist (pre-CFG): sink(mk_res_s(3)) => let __anf0 = mk_res_s(3); sink(__anf0)
//   _anf_lift (1432) — NO consume bookkeeping, not in _hoist_temps
// drive __sub0 to Done, then:
self.__anf0 = self.__sub0.__result      // move-out...
__saw_forget(self.__sub0.__result)      // ...sub slot correctly forgotten (4677)
sink(self.__anf0!)                      // owning read; sink consumes the value
// NOTHING forgets __anf0 — at teardown:
self.__release()                        // self.__anf0 = None  => SECOND drop
```

NEW:

```saw
self.__anf0.put(self.__sub0.__result.take())
sink(self.__anf0.take())                // take empties the slot as it hands over
self.__release()                        // self.__anf0.clear() — empty, no-op
```

The double drop is not expressible: the only consuming read is `take`, and
`take` is what clears the tag. Had the transform emitted `value()` (a borrow)
instead, `sink`'s by-value NoCopy parameter would be the ordinary
copy-refusal — the position matrix DF-217h's fix owes (which argument
positions consume) becomes the checker's question, per-position, forever.

## 6. `post_transform` exemption inventory

Every read of the flag (grep, this branch). The flag is SET in one place:
`sawc.py:1307`, the recursive `_prepare_codegen` re-entry (design 192's
wrapping). Per the 218 brief, unit 2 first SPLITS the bool into named
per-gate exemptions, then deletes them one by one.

| # | read site | what it relaxes | why today | disposition |
|---|-----------|-----------------|-----------|-------------|
| E1 | core.py:570 `_hidden_alloc_gate` | design 135's `--no-hidden-alloc` skips transform output | the gate judges USER SOURCE on the first pass; re-counting the same construct after the rewrite would double-report (a spawn's frame box is counted once, at the `spawn` the user wrote) | PERMANENT — provenance rule, not a soundness gate. Renamed exemption keeps its docstring |
| E2 | core.py:752 `_unsafe_check_exempt` | design 130's unsafe trigger rule skips transformed bodies | resume bodies NAME `UnsafePointer` today (`__recv`, `ref` fields, `__cellp`, `__io_tok`), so every driven method's resume would owe an `unsafe` declaration | NARROWS at stage 3 (Receiver replaces `__recv`/`ref` raw pointers), to exactly the cell/reactor plumbing (`__cellp` deref in `_result_place`/`_cancel_place`, `__io_tok`). Full retirement needs a safe cell wrapper — future work, recorded, not promised here. The narrowed exemption is per-construct, not per-pass |
| E3 | core.py:857 `_ext_scope_allows` | design 142 extension import-scoping | the transform splices bodies from every module into one AST; provenance no longer describes an import graph | PERMANENT — source-level rule, checked correctly on pass 1; the splice cannot reconstruct import graphs and does not need to |
| E4 | core.py:924 `_warn_shadowed_qualifier` | the design-150 warning | warnings describe what an author wrote | PERMANENT — trivially |
| E5 | core.py:1297-1301 `_gate_exempt` | design 82's prelude gate | synthesized frames hold std types (`TaskGroup`, `Box`) in fields without imports | PERMANENT — source-level rule, same class as E3 |
| E6 | statements.py:2025 lost-write-to-capture check | design 132 unit A's refusal of writes a value-env would discard | transform-emitted closures and env rewrites trip the source-shape heuristic | RETIRES at stage 3: once capture materialization emits ordinary checked code (and `[&self]` writes go through Receiver windows, which the place system judges — probes P8/P8b), generated closures must PASS the real check. Deletion commit gated on the closure-env stage's battery |
| E7 | sawc.py:787/1068/1256 | plumbing (parameter threading) | — | follows the split mechanically |

**The ownership exemptions are NOT on this bool** — they ride per-node marks
the transform stamps, and they are what unit 2's "zero ownership exemptions"
exit criterion actually deletes:

| # | mark | consumer | retires |
|---|------|----------|---------|
| M1 | `frame_place_read` | types.py:2665 + 3235 — the transfer checkpoint SKIPS the node ("ownership already settled") | per census stage, as `_read_field` stops emitting it; the skip rule itself deletes when the last emitter goes (end of stage 3) |
| M2 | `frame_move_read` | codegen/conditionals.py:216 (`_optional_binding_owns`) | stage 1 — a `take()` result is an owned temporary the predicate already answers correctly, no mark needed |
| M3 | `frame_owning_read` | codegen/resources.py:1548/1616/1699 — codegen supplies the retain the checkpoint never saw | stages 1-3, per read site; deletes with M1 |
| M4 | `embed_preserved` / `_answered` (design 210) | expressions.py:110 — re-check skips resolved subtrees | KEPT — a resolution/namespace device, not an ownership device; unit 1.5 may subsume it when instances re-enter the checker, out of unit 2's scope |

## 7. Impossibility arguments + the flip list

One paragraph per finding: why the new form CANNOT express the bug, anchored
to the API property that forbids it. Fixed findings keep their regression
tests; the OPEN ones map to pin filenames — this list IS unit 2's
pre-registered flip list (the pin gate).

**DF-217a (fixed — same-name shadow rebind shared a frame field).** The bug
was a forget-then-overwrite mispairing on a shared field: the `move` half
cleared the flag, the store overwrote the payload, teardown released the
original a second time, and the rebound name read a cleared flag. In the new
form the slot's tag is never separately addressable from its payload —
`take` empties and `put` fills in single operations, so even the same
degenerate one-field lowering executes as take-then-put and tears down once:
the tag cannot disagree with the content, which is the API property
(section 2's four-exit argument). The identity fix (`_uniq_bind
second_view`) stays right on its own terms; Slot removes the memory-safety
consequence of any future identity bug. Regression tests: S09 rows +
`coro_same_scope_redefinition_owning_across_suspend.saw` (already green).

**DF-217b (fixed — the rewrite deleted the `MoveExpr` shape a codegen
predicate keyed on).** The class is "a downstream consumer asks the AST
SHAPE a question the transform answered and erased". `take()` does not have
that failure mode: the scrutinee `self.opt.take()` is a CALL whose result is
an owned temporary, and `_optional_binding_owns`' ordinary owned-temporary
test answers correctly with no transform-specific mark (`frame_move_read`,
M2, deletes). There is no erased shape because ownership is carried by the
operation, not by an annotation about a shape that no longer exists.
Regression: O12 + `coro_iflet_move_scrutinee_releases_payload.saw`.

**DF-217c (fixed — a third caller invented its own read discipline).** The
class is "a site spells the read itself instead of asking the funnel". In
the new form there is nothing to spell: the only reads that EXIST on a slot
are `take()` and the `value()` window, and a tier-wrong choice between them
is a compile error on generated code (probe P4's first run is the live
demonstration: the missing `move` inside a generic body compiled today ONLY
because of DF-217i — at concrete types the checker refuses it). The funnel
obligation is satisfied by the type: there is no second way to touch a slot
(218 brief, obligations mapping). Regression: K26 +
`coro_closure_capture_reads_by_policy.saw`.

**DF-217h (OPEN — the ANF temp never gives up its claim).** The bug needs a
consuming read that leaves the drop flag set — two facts recorded in two
places. `Slot` stores both facts in one place: `take()` IS the consuming
read and IS the tag clear, one method body, so "consumed but still flagged
live" is not a representable state. The residual failure is emitting
`value()` where the callee consumes — refused by the transfer checkpoint
(by-value NoCopy parameter fed from a borrow) — or `take()` where nothing
consumes, which leaves an empty slot whose next read PANICS loudly rather
than double-freeing. Pin (exists):
`examples/coro_hoisted_call_arg_consumed_once.saw` — **PROMISED FLIP**.

**DF-217l (fixed — `if let _ = move opt` leaked, no coroutine involved).**
Honestly out of `Slot`'s jurisdiction: a codegen `_`-rider bug on plain
source. Its class — codegen deciding drop policy from source-shape
predicates (`_is_owned_temporary`) — is the decides-vs-lowers family that
units 3-4 audit, and the fix's shared `_optional_source_hands_over` is
already the funnel form. Claimed by this spec only insofar as stage-1
lowering feeds that funnel ordinary calls (take results are owned
temporaries — the easy case). Regression: O13 +
`iflet_guard_optional_binding_releases_moved_payload.saw`.

**DF-216g (OPEN — no expressible borrow for a frame-resident receiver).**
The ICE existed because the transform had no VALUE that could carry "borrow
of the receiver" into an env. `Receiver<T>` is that value: `dup()` mints it,
the env owns it by move, `deref()` lends the referent as a place — probes
P5/P7/P8/P8b cover the shape end to end. The bug is unexpressible because
the capture no longer needs a local reference binding (the thing Saw lacks):
it needs a NoCopy handle, which is ordinary. Pin (exists):
`examples/closure_captures_self_suspending.saw` — **PROMISED FLIP**.

**Ancestors — DF-206f / DF-210a / DF-210b / DF-210f (all fixed).** One
argument covers all four, because they are the same coin: 206f and 210f were
missing forgets (double release), 210a/b were tier-wrong stores (refusal /
over-release). Forgets do not exist in the new form (D1) — the pairing
obligation `__saw_forget` imposed is absorbed into `take` — and a tier-wrong
store is a checked transfer into `put`'s by-value parameter. The property
doing the work in every case: **tag transitions are private to the four
methods, each of which moves or drops the payload in the same body that
writes the tag** (section 2).

**The flip list, closed form.** Unit 2 lands by flipping EXACTLY these pins,
each named here per the pin gate:

| pin filename | DF | flips at |
|---|---|---|
| `examples/coro_hoisted_call_arg_consumed_once.saw` | DF-217h | stage 2 (hoisted temps) |
| `examples/closure_captures_self_suspending.saw` | DF-216g | stage 3 (closure envs / `[&self]`) |

Pins that do NOT exist yet and are DEFINED here for the pin-promotion batch
(behavior-named, XFAIL citing their DF until their stage lands — these pin
the WIDENED 217h class from sweep S2, so the flip validates the class, not
just the found instance):

| pin filename (to create) | pins | source shape |
|---|---|---|
| `examples/coro_hoisted_struct_init_arg_consumed_once.saw` | DF-217h class, S2 rows a5/a6 | `let h = Holder(r: mk_res_s(1))` — struct-init / enum-ctor payload |
| `examples/coro_hoisted_receiver_temp_released_once.saw` | DF-217h class, S2 rows b1-b4/m7 | `mk_res_s(1).name` — call-result receiver temp |
| `examples/coro_hoisted_push_arg_consumed_once.saw` | DF-217h class, S2 rows m14/h4 | `v.push(mk_res_s(1))` / `v.set(i, mk_res_s(1))` |
| `examples/coro_hoisted_tuple_element_consumed_once.saw` | DF-217h class, S2 row p4 | `let t = (mk_res_s(1), mk_res_s(2))` |
| `examples/conformance/K28_slot_payload_released_exactly_once.saw` | the Slot exactly-once guarantee (obligation 3, unit 1's row) | the P4 round trip with deinit-count EXPECTs |
| `examples/conformance/K27_receiver_window_never_spans_suspend.saw` | section 3c's invariant | the P9 refusal shape |

Conformance rows K27/K28 are unit 1's obligation-3 rows and land WITH the
module (green immediately, not XFAIL). The four class pins are XFAIL DF-217h
on creation and flip at stage 2. Pins owned by OTHER briefs (the S2 ICE
family DF-217f/g, statement-head gaps; C07/C12 → `other: &Self`) flip there,
not here — listed to keep the boundary explicit.

## 8. The validated form (DF-217i constraint, restated — not solved here)

The 218 brief's ruling, restated: "the generated code typechecks" is a
guarantee only AT THE FORM THE CHECKER ACTUALLY JUDGES. Sweep S1 row p08a
proved a generic coroutine's laundering passes the post-transform re-check
VACUOUSLY — the re-check sees abstract `T`, and abstract `T` is treated as
the most permissive tier (DF-217i). Unit 2's checks are therefore only as
strong as the boundary the DF-217i ruling closes: either unit 1.5
(monomorphization becomes a pre-codegen transform; instances re-enter the
checker with errors real; the coro transform then runs on CONCRETE ASTs
only) or the interim Send-lane generalization. **The ruling lands BEFORE or
WITH unit 2** — the brief already sequences unit 1.5 ahead of unit 2 for
exactly this reason.

What this spec ASSUMES about it, and the one thing it adds:

1. The transform sees concrete types when it emits `put`/`take`/`value`
   spellings, so the tier is knowable at emission (today's
   `_frame_read_policy` answers None for an abstract slot type — under 1.5
   that case disappears rather than being trusted).
2. The re-check judges the emitted spelling at the same concrete form, so a
   wrong spelling is refused, which is the entire enforcement story of
   sections 1-5.
3. NEW EVIDENCE from this spec's own probes: the constraint reaches the
   TRUSTED CORE too. P4's first run omitted `move` inside `Slot.put`'s
   generic body, compiled clean, and triple-freed at runtime — the Slot
   implementation itself is a generic whose body the abstract check cannot
   currently hold to the least-permissive tier. Until 217i's ruling lands,
   the module's correctness rests on review + its conformance rows (K28's
   deinit counts), which is the design-130 bar unit 1 already carries — but
   the spec records that the "manually verified" surface is bigger by
   exactly one generic-body-checking gap than the brief assumed.

## 9. Migration staging

Stages are orderable, smallest-coherent; each gate = the unit-0 differential
lane (corodiff) + the full suite + `irdet --all` at stage end, plus the named
exemption/mark deletions. Census rows per stage:

| stage | census rows | flips / retires | gate specifics |
|---|---|---|---|
| **0 (pre)** — unit 0 lane + unit 1 module + pin batch | — | K27/K28 land green; the four class pins land XFAIL | module conformance rows; Guard Malloc run over P4's shape |
| **1 — bindings & straight-line stores/reads** | S1-S8, S12, R1-R3, R6, T6 | M2 deletes; `frame_move_read` gone; S3's take-ahead-of-dispatch timing change is this stage's consumer-sweep item (obligation 2: deinit-timing observers, the corodiff oracle itself) | twin parity on the binding axes; O12/S09/K26 stay green |
| **2 — hoisted temps** | T1-T5, R5, S9's argument half | **flips `coro_hoisted_call_arg_consumed_once.saw` + the four class pins**; `_hoist_temps` registration and the DF-210f forget logic delete | the S2 117-row matrix re-run (the fix brief's test plan feeds this stage) |
| **3 — closure envs, `[&self]`, Receiver** | R4, R7, P1, P2, section 4 (parser + typechecker + transform) | **flips `closure_captures_self_suspending.saw`**; E6 deletes; E2 narrows to cell/reactor plumbing; M1/M3 delete (last `_read_field` emitter goes) | lexdiff/astdiff (grammar change); the 216 conformance rows R30/R35-37; P5/P8/P8b shapes as tests |
| **4 — teardown & the forget purge** | D1-D3, R8/P3/P4 trusted-list ratification | `__saw_forget` emission count hits ZERO in the transform (grep-gated); `__release` body = `clear()` loop | full battery incl. gmgate/bootstrap/sos; the trusted list in the 218 brief updated to its final form |

**Stage 4's exit criterion was ADAPTED at dispatch (lead, Aug 14), and the row
above is superseded on one word.** "Emission count hits ZERO" was written before
stages 1-3 measured the SIX deferred census families (`opt_closure`,
address-taken locals, `Void`, fixed arrays, DF-218h's window-move, DF-218i's
rendering operand) and the two scrutinee-temp rows where the DF-210f forget
deliberately stays. A legacy encoding is exactly a field that still owes its
forget, so zero emissions would mean zero deferrals. The criterion as landed:
**zero emissions OUTSIDE those named deferrals, each survivor citing its family,
gate-checked** — `tools/test_forget_purge.py`, the `forgetgate` battery lane.
The citation is an argument the emission funnel refuses to go without, not a
comment. See the brief's STAGE 4 LANDED section.

Dispatch: stages 1-2 are ONE implementer (same funnels — `_read_field`,
`_store_binding_in_slot`, the temp machinery all interlock; splitting them
concurrently would collide in worktree merges). Stage 3 is separately
dispatchable AFTER stage 1 lands (different files: parser/expressions.py,
typechecker capture rules, the closure arm of the transform), running
concurrent with stage 2 only if the lead accepts a rebase burden on
`_materialize_closure_captures` — recommend sequential. Stage 4 is small and
must be last. Unit 1 (the module itself + its conformance rows) is
dispatchable NOW, gated only on this spec's ruling — it adds tracked std
files and touches no transform code.

## 10. Open questions for the user's ruling

1. **Receiver mode: one type with mode = binding mutability, or two types?**
   Recommendation: ONE type (section 3a). Evidence: P3/P8 prove the shared
   mode refuses writes, P8b proves the exclusive mode works, and the
   two-types design is blocked by the no-shared-only-accessor v1 fence plus
   P6 (pointer mutability does not survive the surface cast). Cost: the
   P10b move-reroot escape, held shut by module confinement (no public
   constructor) — acceptable for a compiler-internal type.
2. **Module placement + visibility.** Recommendation: a new std-internal
   module (`std.frame` or similar), NOT in the prelude, no public
   constructors; `Slot`/`Receiver` method surface public within the gate so
   the SYNTHESIZED frames (which are visibility-exempt, E-class) and std
   itself can use them, while user code cannot mint a Receiver. The
   brief's litmus ("code a user could legally write") is then satisfied for
   the OWNERSHIP rules, with the module gate as the confinement boundary —
   ratify that reading of the litmus.
3. **`__release` survives (deviation from the brief).** The brief says the
   `__release` machinery "retires in favor of ordinary structural deinit";
   census D3 finds design 124's EAGER-at-Done timing requires an explicit
   early release that structural deinit (box death) cannot provide.
   Recommendation: keep a synthesized `__release` whose body is ordinary
   safe `clear()` calls — the trust retires, the mechanism stays. Ratify.
4. **NoMove / TaskGroup carve-out.** A NoMove value cannot enter a Slot
   (`put`/`take` are moves); TaskGroup keeps its plain-field placeholder
   pattern (D2). This leans on DF-217j (the containment cascade is not yet
   derived per instantiation — `Slot<TaskGroup>` would compile today).
   Recommendation: ratify the carve-out and record 217j (or unit 1.5) as
   the enforcement dependency.
5. **Ref-encoded arguments to sub-frames (S9) and the general `[&x]`
   capture.** Both need a pointer into SLOT PAYLOAD storage, whose validity
   ("slot stays occupied while the handle lives") is a new manual argument
   invisible to exclusivity. Recommendation: defer both — S9's ref args
   stay on the existing cast in stages 1-3 and migrate in stage 4 or a
   follow-up ruling; `[&x]` general capture is future work (section 4).
6. **`self_opt` becomes `Slot<T?>` — one honest extra tag** (section 2).
   Frame grows by one word per optional-typed local held across a suspend.
   Recommendation: accept (the perf ruling's tag-cost acceptance extends
   naturally; unit 5's elision is the earn-back). Ratify.
7. **The S10 suspect** (channel-receive store bypasses the tier funnel,
   coro_transform.py:4606). Recommendation: dispatch a probe (NoCopy
   channel element, deinit counts) BEFORE stage 1 so the migration doesn't
   silently fix-or-carry an unfiled soundness bug; if it reproduces, it is
   a DF with its own pin on stage 1's flip list.
8. **Stage-3 concurrency.** May stage 3 (closures/Receiver) dispatch to a
   second Opus implementer concurrent with stage 2, or strictly sequential?
   Recommendation: sequential (section 9's rebase-collision argument), at
   the cost of calendar time.

# Design 193 — checker funnels: close the position gaps, fix two confirmed holes

**Status: AUTHORED from design 190's analysis (Aug 9), awaiting user
approval to queue. This is the LARGEST of the four and the highest
soundness value: it closes one CONFIRMED double-free (DF-190a) and one
capability+diagnostic gap (DF-190b), fixes four live tuple-holed walks,
and funnels the scattered position rules the census ranked. Payoff
(matrix evidence): the 14-finding position-incompleteness family gets
funnels-or-matrices so its future members are caught at design review.
Queue FIRST of the four — it fixes reachable soundness bugs. Keep serial
with 194 (both touch typechecker internals).**

## Units — ranked by the census's risk order; soundness first

1. **DF-190a — match-arm payload bindings join the transfer checkpoint
   (CONFIRMED double-free).** Two sequential `match s` on one owned
   NoCopy enum compile silently and the payload deinits TWICE (probe:
   `deinit 7` twice, exit 0) — codegen marks the scrutinee moved
   (codegen/match.py), the typechecker binds payloads
   (expressions.py:8795-8814) with no `_check_value_transfer`, no move
   state. Route match-arm consumption through the checkpoint so the
   scrutinee is move-marked and the second match is a clean
   use-after-move error; a borrowing/place match (design 146) stays a
   borrow, only an OWNING scrutinee consumes. PIN:
   `examples/match_owned_enum_double_consume.saw`. Check the
   copy-tier oracle unification here too (the census's three disagreeing
   answers: `namespace.copy_tier`, `_payload_read_policy`,
   `place_uses._value_read_ok`).
2. **DF-190b — TryCatchExpr in the coro spine walks (capability +
   nonsense diagnostic).** A suspending callee inside `try ... catch` in
   a task body is rejected with ``undefined struct `compute` `` (the
   DF-184a face); the sync shape compiles. The 11 coro spine walks do
   not descend TryCatchExpr (only `_uniq_walk` does). Make the shared
   child-walk (unit 3) cover it, then verify the design-120 ANF hoist /
   CFG split reaches a try-body suspension. PIN:
   `examples/coro_try_catch_suspending.saw`.
3. **The shared child-walk module + the four tuple holes.** Promote
   coro_transform's file-private `_child_nodes` (+ a `structural_fields`
   companion) to a shared module; delete the dead `sawc/visitor.py`;
   convert the FOUR walks with the live DF-187b tuple hole first
   (place_uses `uncheck`/`_unchecked`, `_mentions_move`,
   `_escapes_control_flow` — two are place-legality/exclusivity
   checks — and typechecker `_check_chain_assign_exclusivity`, which
   skips tuple fields so `p?.f = Foo(a: move x)` is invisible to the
   Law). Each conversion is mechanical; the exclusivity ones get a pin.
   The 21 control-flow SPINE walks are NOT force-unified (each encodes
   pass-specific per-container semantics) — instead they get a shared
   "container kinds" enumeration so a new container can't be silently
   missed; TryCatchExpr (unit 2) is the first entry proving it.
4. **Exclusivity satellites.** Existential (`any Trait`) and type-param
   method-call arguments never join an access set (live in
   std/serde.saw); plain-assignment RHS is unchecked while the
   optional-chain spelling of the same statement is (`p.x = f(&var p)`
   vs `p.x? = ...`). Route each through `_check_call_exclusivity` — the
   census marks these one funnel-call each at known sites; assign-RHS is
   a ~45-line mirror of the chain checker. DF-188j (nested refs, no
   window) stays filed pending its ruling — do NOT change it here.
5. **No-escape consolidation + position table.** Collapse the THREE
   duplicate walks (`_first_reference_in`, `_first_laundered_reference`,
   `_first_reference_in_type`) to ONE walk parameterized on an alias
   resolver — the parser/typechecker split stays (188 architectural
   note), but each pass calls the one walk. Replace the six hand-written
   position loops with a POSITION TABLE (the process rule, applied to
   its own worst offender), and add the uncovered rows: `static N: &T`,
   associated-type RHS, and the generic-param DEFAULT `<T = &Int>` (the
   DF-163d shape by another route). Pins for the three new positions.
6. **Send helper + the spawn gaps.** A `require_send(type, position)`
   helper absorbs the ~7 direct consult sites; it mechanically exposes
   the two masked gaps — `spawn {}` result type (guarded only via
   `Task<T: Send>` today) and capture MODE (`&var` vs value, masked by
   closures-never-Send). Decide whether to close them or file+pin as
   ruled-future (they are masked, not open, today — a probe says which).
7. **Unsafe-contact intake + std gate through the funnel.** Two small
   intake lines (bind-and-never-use pattern bindings that name an unsafe
   type; the default-arg ordering that overwrites `_unsafe_contact`);
   and route the std import gate through `_resolve_type` with a
   user-written-type provenance bit (closing DF-188k across every
   annotation position without the over-rejection hazard the census
   names). Retire the 188-u7 mini-walk once the funnel covers statics.
8. **Docs + tests.** Spec/skill for any behavior a user can observe (the
   match-consume rule is the notable one); every unit that funnels a
   rule adds the funnel's entry-point docstring per the process rule;
   conformance rows (once 191 lands) or examples pins otherwise.

## Gates

Per-unit commits, full battery each incl. the new gmgate lane (192) if
landed by then; irdet --all (the match and no-escape changes touch
lowering-adjacent typing — byte-identity is the check). Zero uncited
xfails. This brief will find more than it fixes — DF-193x findings as
usual, and any unit that turns out to need a ruling STOPS and files
rather than guessing.

## Explicitly out

DF-188j and the DF-176c receiver-copy half (both await user rulings);
the parse_type trait/receiver bypasses (rule 7 — UX debt, loud wrong
errors not wrong programs, its own smaller brief); parser-port work;
any const-grammar unification (186 settled the live drift; the split
stays deliberate).

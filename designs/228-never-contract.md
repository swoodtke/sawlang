# Design 228 — the Never contract: one divergence question, asked everywhere

**Status: AUTHORED Aug 15 from the DF-178d isolation sweep
(`.build/scratch/sweep178d/RESULTS.md` + matrices, GITIGNORED — the
essentials are inline here). ONE open ruling (unit 5). Queue: after 227
and 224.**

## The verdict

DF-178d is one mechanism with four faces. The trigger axis the standalone
repros missed: codegen's `expr.resolved_symbol` fast path
(calls.py:592-601) is the ONE of five call-emitting sites that never asks
`_terminate_after_noreturn` (:728, correct, used by the other four) — and
that path is taken when the `-> Never` callee is OVERLOADED ($OL$) or
MODULE-PRIVATE called in-module ($m$). `fault_process` is the latter.
Hosted vs freestanding is NOT an axis (58 cells × 2 profiles, 100%
agreement). Two faces are position-level and break for `panic` too
(`return <diverging>`, `f(<diverging>)`). Minimal repro: 26 lines, one
overloaded `-> Never` fn, no flags (h_overload.saw shape).

## The six legs (fix-brief inputs, sweep-confirmed)

1. **One `_diverges(expr)` predicate, TYPE-based.** Replace
   registration.py:176 `_expr_diverges` (a NAME test: `expr.name ==
   "panic"` — the only syntax-list judgment among 20+ correct type-based
   `TypeKind.NEVER` tests) with coro_transform.py:191 `_is_never_expr`'s
   test, keeping the statement forms in `_block_has_early_exit`. Entry
   points to name: statements.py:1628/1630 (guard-else),
   expressions.py:4478/4484 + 4686/4693 (if-arm), registration.py:263
   (match-arm), :156/172. Ordering hazard: needs `resolved_type` stamped
   (guard caller checks the block first; :158-161 documents the same for
   WhileExpr.diverges). Lands P1 (guard-else) for every callee kind.
2. **Funnel the two unchecked call sites**: calls.py:601
   (resolved_symbol) and :613 (closure calls) get
   `_terminate_after_noreturn`. NO phi fix owed — match.py:440 already
   drops terminated arms; the poisoned phi was a symptom.
3. **The declaration leg**: core.py:2601 `_declare_extension_methods`
   lacks the is_never arm (`void` + `noreturn`) that `_declare_function`
   (:2492) and `_declare_extern_function` (:2569, DF-172h) have — a
   `-> Never` METHOD is emitted as `i8`, so leg 2 can never fire on it.
   Same for diverging CLOSURES. Probe (grep-found, unprobed — the brief
   probes them): generics.py:678/858 (mono methods),
   existentials.py:141 (vtable thunks); also trait default bodies.
4. **`return <diverging>`**: codegen/statements.py:997-1020 never asks
   the divergence question — emit nothing when the operand diverged or
   the block is terminated. Fixes P4 for panic AND -> Never (legs 2+3
   alone do not).
5. **Argument position**: calls.py:220 `_coerce_call_args` gets None
   from a diverging argument — same question, third consumer.
   Pre-existing for panic.
6. **`?? <diverging>`**: expressions.py:6739 asks
   `_types_compatible(inner, default)` with the diverging expr in the
   TARGET slot; the bottom-type escape (types.py:2311) only fires in the
   SOURCE slot. One-line direction fix.

Plus DOCS: LANGUAGE_SPEC gains the Never section (bottom type; an
expression of type Never satisfies any expected type; the divergence
positions). Test plan = the sweep's 12-position × 6-callee matrix, both
profiles, plus method/closure/generic/vtable callee kinds.

## Unit 5 — the one ruling (user): `suspending -> Never`

It is ACCEPTED today and mints `TaskHandle<Never>` with a result cell
for an uninhabitable value, mangled through the escape hatch as
`$Unknown$NEVER` (mangle.py:172 has no NEVER case; the hatch's docstring
says reaching it flags a compiler bug). `join` on it would hang by
construction. Options: (a) REFUSE `suspending -> Never` spawn/drive in
v1 with a teaching diagnostic (a forever-task is `-> Void` with a loop;
join-that-cannot-return is a hang the type system can see coming); or
(b) bless the never-Done frame as the honest forever-server type, which
owes: a NEVER mangle case, a Slot<Never>/zero-size story (DF-221a + the
Void census family), and a ruling on what join means. Lean: (a) —
refuse now, (b) re-proposable with the Void/zero-size family fix.

## What this retires in-tree

The three load-bearing sos workarounds (kernel/core/lib.saw:805-808,
:839-845, :919-927) + three cosmetic Never→Never loops (:713, :723,
:645). At-risk-but-fine-today: every module-private `-> Never` in sos/
std (list in the sweep §5) — one refactor from the fast path.

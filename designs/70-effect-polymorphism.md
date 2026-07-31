# Design 70 — A5: effect polymorphism (generic suspending functions) (queued Jul 31)

Model was decided in papers 18/22: **monomorphization-time
re-inference**. A generic function's suspend-bit is not fixed at its
declaration — each monomorphized instantiation re-runs effect
inference with the concrete types bound, so `func drive<T: Worker>(w:
&var T)` suspends iff the instantiated `T`'s methods do. This closes
"generic driven functions blocked on A5" (designs 44/45/52's honest
rejection).

## Scope
1. Effect inference per INSTANTIATION: thread the effect pass through
   the existing monomorphization machinery (the instantiation already
   re-typechecks bodies — attach effect edges there, keyed by the
   mangled instantiation symbol, mirroring design 55's per-overload
   effect nodes).
2. The coroutine transform accepts a suspending INSTANTIATION of a
   generic function/method: frame synthesis runs per instantiation
   (frame struct named by the mangled symbol). Lift the "generic
   driven functions are a compile error" rejections in
   coro_transform.py; keep rejections for shapes still unsupported,
   with diagnostics naming what remains.
3. `sync` bounds interaction: a `sync` context calling a generic
   function whose instantiation suspends = the normal sync violation,
   reported AT the call site naming the instantiation and the
   suspension path (A8's diagnostic-anchor wish — do the minimal
   version here).
4. Trait objects: `any Trait` dispatch keeps the trait signature's
   effect (unchanged — declared, not inferred). Note in spec.
5. TaskGroup.spawn of a generic suspending call; generic suspending
   METHOD driven via `&var self`; a generic that suspends for T=A but
   is sync for T=B (both instantiations coexist, each correct — the
   key test).
6. Docs: spec concurrency section (effect polymorphism semantics),
   saw-lang skill (remove the "generic suspending functions not yet
   supported" gotcha), tracker (A5 closed, design 70 landed).

Bars: full suite + blade/libs + bootstrap green per commit; zero
xfails; coro_*/taskgroup_*/sync_* families are the oracle. Standing
policy applies. If a fundamental blocker emerges, land the honest
subset + precise diagnostics and re-ledger the remainder with
analysis.

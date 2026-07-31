# Design 74 — A5-rest: finish effect-polymorphism shapes + A8 anchors (queued Jul 31)

Close the four shapes design 70 left as clean rejections, plus the A8
diagnostic remainder. Model unchanged (per-instantiation re-inference,
design 70); this brief extends the coroutine transform's coverage.

## Scope (fix each or, if fundamentally unsound, keep the rejection
with a diagnostic that names the workaround — re-ledger with analysis)
1. **Buried suspending method-on-T call** inside a driven body: the
   transform should treat a method call whose per-instantiation effect
   node suspends as a suspend point (consult effect monos instead of
   rejecting at resume). Also fixes A8's indirect diagnostic (the
   error, where still needed, points at the USER call site, not the
   synthesized resume).
2. **Driven suspending method on a generic STRUCT** (`Worker<T>`):
   frame `__recv` uses the monomorphized concrete receiver layout —
   per-instantiation frames already exist; wire the receiver.
3. **Nested suspending generic call from a driven body**: embed the
   callee instantiation's sub-frame by value (the design-44 0b
   machinery, keyed by mangled instantiation).
4. **Cross-module generic driven templates**: lift the conservative
   block (the pristine-template capture must include imported-module
   templates; mind the design-68 canonicalization lessons — mangled
   keys must agree across modules).
5. **A8**: sync-violation and rejection diagnostics anchor at the
   user's source line (file:line now exists via design 69 — use it),
   naming the instantiation and the suspension path.
6. Docs: spec concurrency limits list updated; saw-lang skill limits
   note updated; tracker (A5-rest closed or re-ledgered per item, A8
   closed, design 74 landed).

Tests: one runnable example per lifted shape (both-instantiations
pattern where meaningful) + error tests for anything still rejected +
an anchor-position test. Bars: full suite (baseline = post-73) +
blade/libs + bootstrap green per commit; zero xfails; coro_*/
taskgroup_*/sync_* families are the oracle. Standing policy applies.

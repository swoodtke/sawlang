# Design 77 — Generics & closures completion (queued Jul 31)

One coherent batch over the shared monomorphization/transform surface;
closes the five feature-shaped rejections accumulated by designs 73-75
plus the one ICE. Order by dependency, each with the standing per-item
escape hatch (land honest subsets; re-ledger precisely).

1. **spawn-Void ICE (fix FIRST, small):** `spawn { void_body }` ICEs
   on the `{i8*, i8*, void}` control block — omit the result slot for
   a Void spawn body. Locking test. [75]
2. **Generic-bound propagation:** a generic forwarding its own type
   param to another generic's bound (`inner<T>(w)` inside
   `middle<T: Seed>`) errors "T does not implement Seed" — the caller's
   bound set must satisfy the callee's bound check during template
   checking (bounds-environment lookup, standard rule). Un-workaround
   design 74's shape-3 tests (concrete args → generic). [74]
3. **DF-C2 — closures satisfy `Copy`:** ImplicitCopy closures (73)
   pass the generic `T: Copy` bound; wire container element-copy
   (`Vector<() -> Int>.get/copy`) to the env retain (the naive enable
   crashed exit 133 — the retain glue must run on every element-copy
   path). Exact-count tests. [73]
4. **DF-C1 — closures in coroutine frames:** implement design 74's
   3-part plan — closure-typed frame fields (the 3-word repr in the
   frame struct), indirect-call rewrite through the frame slot, env
   retain/release across suspend (drop flags). Tests: closure local
   called inside a driven fn; closure held across a suspend (deinit
   exactly-once); TaskGroup frame owning a closure. [73, 74]
5. **A5-rest shape 1 — buried suspending method-on-T:** method
   sub-frame embedding (the Part-0b method twin): phase-1 frame-prep
   fixpoint + receiver addressing (`_build_frame_init` already
   accepts a method `__recv`). The design-74 anchored rejection and
   its workaround note retire on success. [74]
6. **A5-rest shape 4 — cross-module generic driven templates:**
   pristine-template capture includes imported modules; mangled keys
   agree cross-module (design-68 canonicalization discipline). [74]
7. Docs: spec limits lists updated; saw-lang skill limits updated;
   tracker (each item closed or re-ledgered; design 77 landed).

Bars: full suite (baseline = post-76) + blade/libs + bootstrap green
per commit; zero xfails; coro_*/taskgroup_*/closure_*/generic_*
families are the oracle. Standing policy applies. Interruption-safe
per-item commits with tracker progress notes.

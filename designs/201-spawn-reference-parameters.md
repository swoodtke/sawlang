# Design 201 — spawn reference parameters ride the extent model

**LANDED Aug 10, all four units, one commit each, full suite green at every
one (1725 → 1729 → 1733 passed; the ten pre-existing xfails are the ten this
brief started with). The relaxation cost three edits to the lowering — a
reference parameter has been a frame-resident pointer since design 88, and what
a spawn root lacked was only the way IN.**

**The declared-after-group probe (the brief's "verify, row either way"): it does
NOT fall out of design 188's rule, and the shape is a silent use-after-free.**
188's check walks a spawn's capture LISTS and never looks at its arguments, so
with the confinement refusal lifted a root declared after its group compiled and
the task pushed into it AFTER the enclosing scope ended, exit 0. Unit 2 extends
the check rather than merely pinning it. Same for the `move`-while-borrowed
route (design 189 probe 5, one position over): `consumed 0`, buffer dropped,
three pushes into freed storage. Both are DF-201a, filed at unit 1 and closed by
units 2-3.

**Cancel paths: settled, nothing filed.** `cancel()` does not release the
borrow (design 189's ratified edge) and the cancelled task reaches the referent
through the same pointer on its cancel path — probed and pinned in
`examples/spawn_ref_param_dual_role_and_cancel.saw`. Deinit is exactly-once on
the referent: the frame owns nothing through the parameter, so a task's eager
teardown (design 124) leaves a borrowed referent alone and the caller destroys
it at its own scope end (`examples/spawn_ref_param_referent_deinit_once.saw`).

**One regression the units introduced and fixed inside unit 3:** the DF-138a
dual-role trampoline passed a reference parameter as a BARE NAME to the function
it wraps, so the sub-frame builder cast the DEREF to a pointer and the callee
frame's pointer field was seeded with the referent's value — a segfault on the
first read through it. It forwards (`f(&var m)`) now.

**Status: RATIFIED + AUTHORED Aug 10 (morning review; this is design
189's unbuilt unit 4, ratified separately as 189 required). The
relaxation: `group.spawn(f(&var buf))` becomes legal in a
single-threaded group, on exactly the machinery design 189 built for
captures — the argument's ROOT is borrowed for the TASK's life, the
handle carries the borrow, `join()` releases it, a discarded/stored
handle holds it to group death, and a capture live at a loop-body end
is refused. One rule where today there is a legal spelling (the
capture) and a rejected twin (the parameter). Design 88's original
refusal ("it would point into the dead spawner stack") is answered the
same way the capture's was: the borrow pins the root binding for the
task's reachable life, and LIFO destruction plus the
declared-before-group rule (design 188) keep the frame alive.**

## Units

1. **Conformance/pins first (obligation 3 — this is borrow-soundness
   surface).** K-family rows: the legal shape (spawn with `&var` arg,
   join, then touch the root — accept, write visible); the exclusion
   window (caller read/write between spawn and join — reject, both);
   the shared `&` arg composing with caller reads (accept); the
   loop-body liveness refusal; declared-after-group refusal (should
   fall out of 188's rule — verify, row either way); the MT-group
   refusal (a reference param is not Send — the existing clean error,
   regression row).
2. **Typechecker.** Extend 189's task-borrow intake: a `&`/`&var`
   argument in a spawn-position call registers a task borrow of its
   root on the handle, exactly as a capture does (same
   `_task_borrow_for` machinery, same diagnostics naming spawn line
   and release point). The design-88 refusal for ST groups is deleted;
   the MT refusal stays (Send).
3. **Codegen/coro.** The spawned frame's reference parameter becomes a
   frame-resident pointer to the root (design 88's held-ref machinery
   in spawn position). Verify mutation visibility after join and
   deinit-exactly-once on the referent (the frame never drops what it
   does not own).
4. **Docs.** Spec design-88/189 sections (the param/capture asymmetry
   paragraph is REPLACED by the one rule); skill concurrency section
   (the "a SPAWNED task may NOT take a reference PARAM" bullet
   rewrites to the extent rule + MT exception).

## Gates

Per-unit commits, tracked battery each; irdet --all; the gmgate
concurrency lane gains the legal shape + the join-release shape at
-n 5 (frame-handoff family). Any interaction with cancel paths that
the probe reveals as unsettled STOPS and files.

## Explicitly out

MT-group reference params (Send refuses them, correctly); reference
RETURNS from tasks (`join()` moves a value, unchanged); any change to
capture semantics (189 landed, untouched).

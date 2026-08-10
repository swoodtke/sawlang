# Design 201 — spawn reference parameters ride the extent model

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

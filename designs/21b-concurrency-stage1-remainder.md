# Design Brief 21b — Concurrency stage 1 remainder: escaping closures, spawn, Channel

**Source:** `designs/21-concurrency-stage1.md` items 5–7 (unlanded — see the
stage-1 report's "Scope reached / not reached") plus the two enablers it
identified. Items 1–4 and 8 are on main (Send/Sync, Arc, reference-param
closures, Mutex, spec note). Suite baseline when written: 269 / 7.

## The two enablers (do these first — they gate everything)

### E1. Escaping-closure lowering: heap environments
Today closure environments are stack-allocated and closure return types
were until recently hardcoded — a closure cannot outlive its creating
frame, which `spawn` requires. Implement: when a closure value escapes
(stored, returned, or passed to `spawn`) its environment is allocated via
`saw_alloc` with the captured values moved/copied in per the established
transfer rules (trivial copy / ImplicitCopy retain / ExplicitCopy-NoCopy
demand `move` — the checkpoint already governs captures as call-argument
transfers), and freed after the closure's final invocation (for spawn:
after the task body returns; general stored-closure lifetime can be
conservative v1 — spawn is the forcing consumer; document what you ship
for non-spawn escapes, deferring full closure-Deinit if needed).

### E2. Arc payload access
The stage-1 report deferred method forwarding. Minimum needed for the
`Arc<Mutex<T>>` idiom: calling a method on the payload through the Arc
(`arc.lock { ... }` forwarding to `Mutex.lock`) with an immutable-borrow
receiver into the control block's payload slot. Implement forwarding for
`&self`-receiver methods (sound: payload is pinned while any strong ref
lives); `&var self`-receiver forwarding through Arc is REJECTED with a
clear message (aliased mutation — that's what Mutex is for).

## Then the deferred items, per the original brief's specs

- **Item 5 — `spawn` + `Task<T>`** (pthread engine, trampoline through
  void*, result in a saw_alloc slot; Send capture-audit exactly as the
  stage-1 report sketched: walk `expr.captures`, resolve each type,
  reject non-Send naming the capture; Task<T> NoCopy, `join(move self)`,
  join-on-deinit; never expose thread identity). Re-add the pthread
  create/join wrappers the stage-1 agent trimmed.
- **Item 6 — `Channel<T: Send>`** (ImplicitCopy refcounted handle;
  unbounded MPMC, internal mutex + condvar via the same opaque-buffer
  approach — probe condvar sizes as was done for mutex; `send(move v)`,
  `recv() -> T` blocking in this engine, documented as a future
  suspension point).
- **Item 7 — the threaded tests**, deterministic by construction:
  `spawn_join`, `spawn_multi` (join-ordered output), `mutex_counter`
  (N×M exact — THE flagship), `channel_pipeline` (sum exact),
  `task_join_on_deinit`, `errors/spawn_capture_not_send`,
  `errors/channel_not_send`. The stage-1 standard applies: 5 consecutive
  full-suite green runs; a flaky test is worse than no test — if a test
  cannot be made deterministic, redesign it around joins/final values or
  drop it with justification.

## Hazards
Same as stage 1 (nondeterminism; Arc/env teardown double-free — env
release must run captured values' drop glue exactly once, on the task
thread, after the body; verify with deinit-printing captures). Also new:
E1 must not regress the existing closure tests (stack envs remain fine
for non-escaping uses — don't heap-allocate what doesn't escape).

## Report back
E1 design (escape detection, env layout, free point, non-spawn escapes
policy); E2 forwarding mechanics; per-item mechanisms; condvar sizing;
capture-audit walk; determinism measures; the 5×-green evidence;
deviations; non-allowlisted commands.

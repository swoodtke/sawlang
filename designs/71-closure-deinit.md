# Design 71 — Closure Deinit: env teardown at closure drop (queued Jul 31)

Close the C4 remainder (verified in design 59: no leak/double-free
today, but semantics are "early": an escaping closure's owned captures
are released at the CREATING frame's exit, not at the closure value's
own drop, and the heap env block is not freed on the non-spawn path —
the generated `codegen_env_dtor` only runs from the spawn trampoline).

## Semantics (pinned)
- An escaping closure value is an OWNING value: dropping it runs its
  env destructor (releases owned captures exactly once) and frees the
  heap env block. LIFO/drop-flag rules apply like any owning binding
  (conditional moves, use-after-move already enforced).
- The creating frame no longer releases captures the closure took
  ownership of (the current early-release path must be REMOVED in the
  same commit that wires the drop — leak<->double-free flip hazard;
  exact-count tests gate every step).
- Copying a closure value: closures are NoCopy (verify current class;
  if they are implicitly copyable today, that is a bug this brief
  fixes — a closure with owned captures must be move-only).
- Spawn path unchanged in behavior (trampoline already runs the dtor;
  ensure it doesn't now run twice — exactly-once via the same drop
  flags).
- Non-escaping closures: unchanged (no env ownership).

## Scope
1. Wire `codegen_env_dtor` into the closure-typed value's drop glue
   (drop flags, LIFO order); remove the creating-frame early release;
   free the env block.
2. Exact-count tests: NoCopy capture dropped once at closure drop
   (not frame exit — observable ordering test); Arc capture refcount
   balanced; closure moved into a struct field / Vector / returned —
   drops where the owner drops; closure dropped without being called;
   called-then-dropped; conditional move of a closure.
3. Tracker: C4/closure-Deinit closed; design 71 landed. Spec: closures
   section ownership note; saw-lang skill gotcha update.

Bars: full suite + blade/libs + bootstrap green per commit; zero
xfails; the C1/design-29 closure family + spawn tests are the oracle.
Standing policy applies.

## Landed (Jul 30)
- Closure representation is now `{ fn_ptr, env_ptr, dtor_ptr }` — an escaping
  closure carries its own env destructor. `_needs_cleanup(FUNCTION-escaping)` +
  `_emit_closure_drop_at` (null-dtor no-op) run it at the closure's own drop
  (LIFO + drop flags), releasing owned captures exactly once and freeing the
  heap env. The closure literal's resolved FUNCTION type records its escaping
  bit so codegen sees the owning binding.
- Early release REMOVED in the same commit: a `move` capture clears the source
  binding's drop flag. This also fixed a latent thread-`spawn` double-free of a
  move-captured NoCopy (deinit had run at frame exit AND in the trampoline).
- Copy class: escaping closures are NoCopy (move-only) — a bitwise copy aliased
  the shared heap env (double free, observed exit 133). Forwarding an escaping
  closure into a non-escaping/borrowing slot stays a lend (no move). Closure
  FIELDS excluded from NoCopy CONTAINMENT so capture-less-closure structs stay
  copyable.
- Spawn path unchanged in behavior: the trampoline runs the destructor exactly
  once (the spawn closure is consumed, never bound).
- Tests: `closure_deinit_{drop_order, arc_balance, struct_field, vector,
  returned, dropped_uncalled, called_then_dropped, conditional_move}` +
  `closure_copy_requires_move_error`. Suite 789, bootstrap 17+17, libs 4+4.
- RESIDUAL GAP (documented): an owning closure stored in a COPYABLE struct that
  is then copied still double-frees — the declared field type cannot say a
  stored value owns an env; closing it needs value-flow (not type) analysis.

# Design 114 — intrinsic scoping + naming: std.task, __saw_* rename (queued Aug 4)

User direction (Aug 4): two related cleanups of the compiler-intrinsic
surface.

## A. Public wrapper for yield_now: std.task (surface change)

Audit (Aug 4): exactly TWO name-based intrinsics are reachable from
user code — `yield_now` (typechecker special-cases the bare name
globally, expressions.py ~2145) and `io_wait` (same mechanism; used
by std.net). Everything else runtime-ish is already properly scoped
(`sleep_ms` behind `import std.time`) or compiler-emitted only.

- New std module `std/task.saw` (NOT in the prelude — design-82
  discipline; requires `import std.task`) exposing public
  `yield_now()`. Implementation: a thin wrapper over the gated
  intrinsic. The wrapper is a one-suspend helper — the design-96/101/
  104 embedding machinery handles it at any call depth; if that
  indirection proves a problem, fall back to typechecker-recognizing
  the QUALIFIED name `std.task.yield_now` as the intrinsic directly
  (either is acceptable; pick one, test both claims).
- The BARE names `yield_now` / `io_wait` become stdlib-internal
  (the `__deinit_in_place` gating precedent: usable only from std
  modules). User code calling bare `yield_now` gets a clean error
  NAMING the replacement ("use `import std.task` +
  `std.task`'s `yield_now()`") — diagnostic quality is part of the
  brief. `io_wait` gets NO public wrapper (users get std.net; a
  public low-level fd-wait, if ever wanted, is its own design).
- Naming decision (user + lead, Aug 4): `std.task.yield_now()`, not
  `std.sched.yield` — "task" matches the user-facing vocabulary
  (TaskGroup; Swift `Task.yield()`, tokio `task::yield_now`);
  "sched" is about to mean the SOS KERNEL scheduler; `yield` stays
  free as a possible future generator keyword.
- Migration: update every .saw user of bare `yield_now` (examples/,
  libs/, blade/ if any) to import + call the wrapper. std-internal
  uses (channel.saw, net.saw) keep the bare intrinsic.

## B. Uniform __saw_ prefix for compiler-recognized names (internal)

Inventory (Aug 4): `__suspend`, `__test_suspend`, `__io_park`,
`__blk_start`, `__blk_done`, `__blk_pipe_fd`, `__blk_take`,
`__exec_sleep`, `__box_data`, `__drive`, `__drive_steps`,
`__deinit_in_place`, `__forget` (+ sweep for stragglers — grep
typechecker/coro_transform/codegen for quoted `__` names).

- Rename each to `__saw_<name>` (`__saw_deinit_in_place`,
  `__saw_suspend`, ...). Decision (user, Aug 4): plain `__saw_`, NOT
  `__saw_rt_` — these are compiler-layer spellings, not runtime-ABI
  symbols; the design-113 tier rule stays two-tier
  (`__saw_rt_*` = runtime-implemented, `__saw_*` = compiler-layer).
- Stdlib-PRIVATE Saw helpers (`__tg_worker`, `__wake_reason`,
  `__is_cancelled`, `__run_all`, `__drain_mt`, `__enqueue`,
  `__register`, `__unregister`) are NOT compiler magic — plain
  identifiers under design-80 privacy. Leave them (rename optional,
  only if trivially mechanical in the same sweep; no obligation).
- Update every reference: typechecker recognition sites,
  coro_transform emission/matching, codegen, std .saw sources,
  any tests that name them. End-state grep-audit: no
  compiler-recognized quoted name outside the `__saw_` prefix.

## Scope summary

1. `std/task.saw` + prelude/import wiring + the intrinsic gating +
   the bare-name diagnostic.
2. The rename sweep (B), reference-complete.
3. Tests: bare `yield_now` in user code errors with the guiding
   message; `io_wait` outside std errors; `std.task.yield_now()`
   works in every embedding position the suite exercises for
   suspending helpers (statement, nested if/loop, MT TaskGroup);
   existing suite green throughout (examples migrated in the same
   commit as the gating, so no intermediate red).
4. Docs: LANGUAGE_SPEC concurrency section (yield_now spelling +
   import), saw-lang skill (same), README if it shows yield_now,
   CLAUDE.md digest line (std.task joins the import-needed list),
   tracker entry closed.

Bars: full suite zero xfails + bootstrap green per commit; per-unit
commits (A and B are separate commits at minimum); linear history;
no attribution trailers; foreground suites; interruption-safe; new
discoveries tracker-flagged, not scope-crept. SEQUENCING: dispatch
AFTER design 113 lands (both touch the intrinsic surface); no
conflict with 112.

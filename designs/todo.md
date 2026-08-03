# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.

## Milestones
- **App-1 Blade: DONE** (design 64 + 67; real resolver/lock/git/
  incremental/self-hosting bootstrap; `make blade-bootstrap`).
- **App-2 SOS kernel (ESP32-P4, riscv32): NEXT.** Milestone: UART
  "blink" from a Saw kernel on the P4. See sos/spec.md.

## Design 102 — runtime edge bugs: spawn-Void ICE + cancel wakes an io-parked task (LANDED)
- **Item 2 (cancel wakes an ALREADY-io-parked task — A3 remainder) — LANDED.** A task
  parked in `io_wait` on a permanently-idle fd, cancelled by a peer, never observed the
  cancel (the landed model only checked BEFORE parking; a blocked reactor poll never
  returned). FIX, layered + precise (no herd wake):
  1. Reactor self-wake pipe (portable self-pipe on kqueue/epoll; codegen/core.py):
     `saw_reactor_wake()` writes one byte to a process-global self-pipe whose read end
     `saw_reactor_poll` registers (one-shot, token 0 -> the latch loop skips it) each
     cycle and drains on return. `handle.cancel()` / `VoidTaskHandle.cancel()` call it,
     so a blocked poll returns promptly.
  2. Precise wake by cancel flag: a new `Resumable.__is_cancelled()` frame reader (reads
     `__cancel`); `__ambient_wake_io` + the MT worker wake scan now make an io-parked
     frame runnable when `__wake_reason() >= 0 OR __is_cancelled()` — so ONLY the
     reactor-latched frame(s) and the cancelled frame(s) wake; a non-cancelled sibling
     parked on another idle fd stays parked (net_precise_* unaffected).
  3. ST liveness for a `cancel_addr` peer cancel (which sets the flag WITHOUT a
     self-wake): `__ambient_run` scans (`__ambient_any_cancelled_io`) BEFORE blocking in
     poll and wakes a cancelled parked frame instead of polling an idle fd forever.
  4. Cancel propagation down the frame chain: the nested-sub-frame drive now copies the
     root's `__cancel` into the sub-frame each drive (mirroring the design-91 `__io_tok`
     propagation), so a `cancelled()` check INSIDE a nested `stream.read()` sub-frame
     observes a cancel set on the ROOT frame the handle points at. Without this the
     parked reader re-parked forever.
  5. net.saw: `read`/`read_into`/`write` (both overloads)/`connect` now re-check
     `cancelled()` at their park-loop top (accept already did) and return `Err(IoError)`.
  Tests (time-bounded; a hang -> runner failure): `net_cancel_parked_read` (ST parked
  reader peer-cancelled via cancel_addr; deinit-once oracle), `net_cancel_precise`
  (cancelled reader wakes while a sibling on another idle fd stays parked until its own
  data arrives -> `-1 2`), `net_cancel_parked_mt` (`TaskGroup(threads: 2)`, stable 5x).
  Closes the design-76 A3-remainder flag. Suite 937, bootstrap 17+17, libs 4+4. [76, 18, 90, 91, 89-b]
- **Item 1 (spawn-Void ICE — cooperative TaskGroup) — LANDED.** `group.spawn(void_body)`
  ICE'd: the frame correctly omits `__result` for a Void body (a `{..., void}` struct
  field is illegal LLVM), but the `__spawn_<f>` helper still built `__rp =
  &__fp[0].__result` and the handle was `TaskHandle<Void>` (join force-unwraps a
  zero-size `T?`). FIX (proper omission, no placeholder): a Void spawn now yields a
  dedicated non-generic `VoidTaskHandle` (cancel_ptr + group_ptr + slot, no
  result_ptr) whose `join()` drives to completion and returns Void; the spawn helper
  skips the `__rp` capture entirely for a Void frame. Typechecker `_check_taskgroup_spawn`
  returns `VoidTaskHandle` when the body is Void. SWEEP: `__drive_<f>` had the same
  hazard (read `__f.__result` unconditionally) — now returns Void with no result read
  for a Void driven body. The design-75 executor return-Int workaround is now DEAD and
  removed: `__tg_worker` returns `Void` (21b `spawn { void }` works since design 77) and
  `__drain_mt` holds `Vector<Task<Void>>`. Channels of Void are not a void-slot hazard
  (the type constructs; there's just no Void literal to `send` — a front-end value gap,
  orthogonal). Tests `taskgroup_spawn_void` (single- + multi-threaded, explicit-join +
  drop-drain, sum oracle 60), `coro_drive_void_body`. Closes the design-75 spawn-Void
  flag. Suite 934, bootstrap 17+17, libs 4+4. [75, 77, 21b]

## Design 103 — A6 runtime offload: `extern blocking` calls RUN in tasks (LANDED)
- **The last A6 half.** A blocking FFI call inside a suspending body (driven /
  spawned / a suspending `main`) no longer REJECTS — it OFFLOADS to a worker thread
  and PARKS on the job's pipe like any socket read, so siblings keep running while
  it blocks and the single cooperative reactor thread is never wedged. Closes the
  design-76 A6 remainder (thread-per-call v1 in place of the ledgered "pool").
- **Runtime shims** (`codegen/core.py _declare_io_runtime`, hosted-only weak seams).
  `saw_offload_start(fn, arg) -> job` mallocs a job record `{ fn, arg, result, done,
  pipe_r, pipe_w, thread }`, pipes it, and `pthread_create`s a worker running
  `__saw_offload_thread`: it calls the extern via the raw fnptr (`i64(i64)` thunk),
  stores the result, PUBLISHES `done` (atomic release), then writes one byte to the
  job's self-pipe. `saw_offload_done` (acquire-load the flag), `saw_offload_pipe_fd`
  (the readable fd), `saw_offload_take` (pthread_join = full barrier -> read result
  -> close pipe -> free). HAZARD discipline: the worker touches ONLY its own job +
  pipe write end; ALL wake routing stays in the reactor; the pipe byte + the join
  are the release/acquire boundary, so the result transfers single-owner with no
  data race (start owns -> thread fills -> take transfers). `saw_blocking_sleep(ms)
  -> ms` is the reference blocking primitive the tests drive via a `blocking func`.
- **Lowering** (`coro_transform.py`). A top-level blocking-extern call boundary
  (`let x = slow(arg)`, a bare/`let _` discard, or a design-83 tail `return
  slow(arg)`) is classified (`_classify_blk`) BEFORE frame layout and desugars in
  `_emit_blk_call` to `self.__blkjobN = __blk_start(slow(arg))` -> park loop
  `while __blk_done(job)==0 { saw_reactor_register(__blk_pipe_fd(job), read);
  suspend(IO_PARK) }` -> `<x> = __blk_take(job)`. `__blk_start` is a CODEGEN
  intrinsic (calls.py) that resolves the extern's `ir.Function` (a function address
  is not expressible in Saw) and bitcasts it to i64 + evaluates the Int arg; the
  three wrappers thin over the shims. The blocking-extern call is now a suspension
  point for `_spans_suspension` (its result local becomes frame-resident) and gets a
  frame-resident `__blkjobN: Int` handle (+ `_build_frame_init` seeds it 0). The
  typechecker (`__blk_start`/`__blk_done`/`__blk_pipe_fd`/`__blk_take` handlers)
  types them as Int and — crucially — `__blk_start` does NOT re-record the blocking
  effect (the offload REPLACES the direct call), so the synthesized `resume` stays
  suspension-free of the blocking source. Precise wake tokens + budget reset-on-park
  apply unchanged (the park reuses the design-91 `__io_tok` routing).
- **Cancel compose (design 102).** The park loop re-checks `__cancel` at its loop
  top and BAILS — a peer cancel writes the reactor self-pipe (design 102 item 1) or
  is caught by the pre-poll cancelled scan (item 3), which rouses the poll; the
  re-check exits the loop. The in-flight blocking call cannot be aborted, so take()
  still joins its worker on the cancel path (documented v1 limit: no leak, no race).
- **Anchor fix (item 3).** A blocking-extern call in a position the desugar cannot
  occupy (buried in an expression, a `try!`, an `if let`/`guard` body) is rejected
  in the transform ANCHORED AT THE USER CALL SITE (source_file threaded), never left
  to lower as a direct call and trip the synthesized `resume`'s sync check anchored
  at `__Frame_*.resume`. v1 also rejects a non-`(Int) -> Int` blocking extern
  (`_check_blk_whitelist`, anchored) — the offload thunk is `i64(i64)`; multi-arg +
  non-Int + a real pool are future work. The `sync`-context + freestanding
  rejections are UNCHANGED (correct).
- **Tests.** `offload_spawn_interleave` (a spawned task blocks on a real offload
  call while main's sleep-loop provably runs — 0,1,2 then 61; the 60 -> 61
  round-trip proves the Int flowed into the worker and back; a plain block would
  hang -> runner-timeout FAILURE; stable 8x), `offload_cancel_parked` (a task parked
  on an offload job is peer-cancelled via `cancel_addr`, wakes, observes cancel ->
  -1, deinit-once oracle; stable 8x), `errors/offload_buried_reject` (buried call ->
  user-anchored error, asserts the source basename), `errors/offload_freestanding_
  reject` (`--freestanding` COMPILE-FLAGS). Suite 941 (937 + 4), bootstrap 17+17,
  libs toml 4 + semver 4, zero xfails. [103, 76, 18, 22, 58, 102, 90, 91, 89-b]

## Design 101 — DF7: no silent blocking for suspending method calls in nested/trailing positions (LANDED)
- **Root cause (precise boundary).** The coro transform's wrapper hoists
  (`_hoist_suspending_conditions`/`_hoist_suspending_try`/`_hoist_suspending_match`)
  and the collect/reject walk key on `block.statements` and never look at
  `block.final_expr`. The parser parks a block's LAST bare expression there, so a
  suspending METHOD call buried in a TRAILING `if`/`else`/`match`/nested-`if` (the
  loop body's `final_expr`, e.g. `while going { …; if c { let x = try! s.read() } }`)
  was never statementized in time for the try/condition/match hoist to see it —
  it stayed wrapped in a `TryExpr` `_collect_calls` could not classify, slipped past
  every rejection, and lowered as a PLAIN blocking call (`call @TcpStream_read`), the
  silent DF7 miscompile (cooperative park a no-op). `_normalize_suspending_tails`
  (design 83) lifts trailing exprs to statements but ran AFTER two of the three hoists.
- **Fix (one canonical structural pass).** (1) Run `_normalize_suspending_tails`
  FIRST in `prepare`, before all three wrapper hoists — every suspending call then
  sits in statement position within some block, so the hoists + collect/split walk
  are exhaustive by construction. (2) `_split_match`: preserve the design-63
  `pattern` + `guard` (and carry pattern-derived binding names via a new
  `_pattern_binding_names`) — reconstructing arms from `variant_name`/`bindings`
  alone DROPPED literal/range/tuple patterns, so a suspension-spanning `match` over
  literal/range arms lost its patterns → spurious "match is not exhaustive" at 0:0.
  (3) `_reject_buried_suspend_call`: also flag suspending METHOD calls (not only
  free-fn/`receive()`) — a buried method call in an `if let`/`guard let` body
  (branches the split does NOT CFG-split) slipped through here and lowered plain;
  now a clean anchored rejection. Split-capable containers (if/while/for/match)
  never reach that method, so no over-rejection.
- **Shape matrix — every position now EMBEDS or ERRORS cleanly; no silent third
  outcome.** top-level stmt / trailing if / trailing else / trailing match arm
  (literal+range) / if-in-if depth 2 / if-in-while → EMBED (`net_nested_shape_matrix`,
  exact per-shape recirc counts). `if let` body / `guard let` body → clean anchored
  ERROR (`errors/coro_suspending_method_in_{iflet,guardlet}_body`). Closure body
  capturing a stream → clean NoCopy-capture ERROR. Verified with IR
  (`@__Frame_TcpStream_read_resume` drive, not `call @TcpStream_read`), not just exit
  codes.
- **Acceptance.** `net_budget_fairness` re-simplified from the DF7 workaround
  (read/write hoisted to the loop top level) back to the natural nested form (under a
  trailing `if`); still prints 5, still cedes to the sibling on the op-count budget
  (IR: driven sub-frames — a plain block would hang). Suite 932 (929 + 3); bootstrap
  ok (blade 17+17, libs toml 4 + semver 4); zero xfails. Docs: saw-lang skill's
  supported-shape story corrected (nested/trailing control-flow method calls now
  work; only if-let/guard BODIES reject). [101, 96, 84, 83, 74, 89-c, 92]

## Design 100 — shadowing: error unless derived from the shadowed binding (LANDED)
- **Rule.** A `let`/`var`/pattern/param binding that SHADOWS an enclosing binding
  (an outer local/param/capture in a parent scope, or an accessible module
  `static`) is a compile error UNLESS it is a visible refinement. Typechecker
  helpers in `statements.py` (`_shadowed_binding_pos` walks the current scope's
  PARENT chain + `namespace.get_static`; `_init_mentions_name` is a generic
  dataclass walk for any `Identifier`/`MoveExpr` use of the name; `_check_shadowing`
  the entry, `site=binding|pattern|param`). Wired at every binding-introduction
  site: let/var (`_check_let_statement`, main rule on the initializer), destructuring
  let (per bound name), single-name if-let/guard-let (main rule on the scrutinee —
  so `if let x = x` / `guard let x = x` stay legal), tuple/match PATTERN bindings
  (flat error — patterns bind, not compare; the hint says so), function/method
  params vs module statics, closure params vs enclosing locals. Same-scope
  redefinition is unchanged (still the pre-existing DUPLICATE_VARIABLE error);
  prelude/std names are not bindings. Diagnostic: `` `x` shadows the binding
  declared at FILE:L:C `` + a rename/derive (or patterns-bind) hint; positions
  exact (design 99).
- **MIGRATION AUDIT: only 1 illegal shadow in the ENTIRE corpus** (std + blade +
  libs + examples all compiled green; only `examples/use_after_move_shadow.saw`,
  a test that DELIBERATELY shadowed a moved-from binding to prove move-state is
  per-identity — migrated to a distinct inner name, intent preserved). Accidental
  shadowing was effectively nonexistent — the codebase was already clean.
- **CODEGEN double-free FIXED (pre-existing, fix-on-discovery).** Design 100 makes
  a derived SAME-name shadow of an OWNING binding idiomatic (`let nums = nums.copy()`,
  `if let x = x`), which exposed a latent codegen bug: scope-exit cleanup and the
  if-let path resolved a binding's storage/drop-flag by NAME, so a shadowing inner
  binding redirected the OUTER scope's cleanup to the inner (already-dropped)
  storage → double-free (SIGABRT/SIGTRAP), and `if let x = x` deleted the outer
  binding outright (ICE on later use). Repro'd on the clean tree (not my change —
  typecheck-only). Fix: (1) `_register_cleanup`/`_cleanup_scope` (resources.py) +
  the guard-let producer (conditionals.py) now CAPTURE the alloca+flag at
  registration and `_emit_drop_at` the captured pointer (never re-resolve by name);
  (2) if-let restores the shadowed enclosing binding instead of deleting it
  (conditionals.py); (3) `_generate_block` (methods.py) snapshots + restores the
  name→storage maps at block exit so a use of the outer name after a shadowing
  block is sound. Tests: `shadow_owning_lifetime` (derived owning shadow + outer
  reused; `if let x = x` + outer reused).
- **FLAG for the user (rule friction, not weakened).** The design brief's headline
  example `var data = read(); let data = parse(move data)` — if literally in ONE
  scope — remains a pre-existing "already defined in this scope" error, because the
  dispatch scope pinned "same-scope redefinition: if already an error, unchanged"
  and same-scope redefinition is currently an error. The derived-shadow leniency
  therefore applies only ACROSS scopes today. If you want `let data = parse(move
  data)` to be legal in the SAME scope (the design example reads that way), that's
  a deliberate follow-up (open up same-scope redefinition under the same
  mentions-rule). Also DEFERRED by scope: for-loop iteration variables are NOT
  covered (the brief enumerated let/var, patterns, params, closure params; for-loop
  vars were not listed) — a `for x in xs` under an outer `x` is still allowed; flag
  if you want it included.
- Tests (OK): `shadow_derived` (derived let bare/move/call-wrapped/`.copy()`, var,
  if-let, guard-let unwrap — all run). Tests (ERROR, exact positions on both the
  shadowed decl and the shadow site): `errors/shadow_inner_let`,
  `errors/shadow_match_pattern`, `errors/shadow_param`, `errors/shadow_closure_param`.
  Docs: LANGUAGE_SPEC bindings section + saw-lang skill (rule bullet + gotcha).
  Suite 928 (922 + 6), bootstrap ok (blade 17+17, libs 4+4). [100, 99, 15, 42]

## Design 98 — `#file`/`#line`/`#function` source-location literals (LANDED)
- Magic literals expanding at their DEFINITION site to compile-time constants
  (zero runtime cost, freestanding-safe): `#file` → source basename (String,
  matches the design-69 panic prefix), `#line` → 1-based token line (Int),
  `#function` → enclosing fn/method BARE name (String; module scope → `<module>`).
  Lexer reads `#`-directives (unknown `#foo` = clean lex error); parser emits a
  `SourceLocationLiteral` atom carrying the file (stamped from the parser's
  source_file; interpolation sub-parser now inherits it) + token line; typechecker
  `visit_SourceLocationLiteral` freezes the value ONCE (idempotent — the post-coro
  re-check must not re-resolve, so `#line`/`#function` in a suspending body report
  the ORIGINAL source, not the frame method), returns String/Int; codegen emits a
  plain Int/String literal; `#line` is const-init-able (`_is_const_init` +
  `_const_from_expr`) so a top-level `static X: Int = #line` works. Generics report
  the generic's own file/line identically across instantiations; defaults report
  the default's definition site. Builds on design 99 (interpolation position
  rebasing) so `#line` inside `{...}` reports the real line. Tests:
  source_location_literals (method/generic×2/closure/default/top-static/main, exact
  pinned lines), source_location_suspending (spawned worker straddling two suspends
  → original line + bare name), errors/unknown_directive. Docs: spec Source-location
  literals section + skill debug-print idiom. Suite 922 (919+3), bootstrap ok. [98, 99, 69]

## Design 96 — nested suspending reactor methods at any depth (LANDED)
- The depth-2+ hang was NOT the design-91 wake token (token threading is correct
  at every depth). ROOT CAUSE: the effect fixpoint cannot see suspension arising
  SOLELY from a nested std METHOD call (a std method's effect node is absent — the
  gap `_scan_method_callees` works around), so a FREE fn whose only suspension
  source is a buried `stream.read()` was left `suspends=False`; the driven-closure
  walk skipped the caller→callee edge, the fn never joined the closure or got a
  frame, and it was emitted as a PLAIN blocking call whose buried `io_wait` wedged
  the single thread. 1-deep worked only because `_scan_method_callees` sees a
  method call directly in the root body. FIX (coro_transform.py): compute
  `structurally_susp_fns` (a free fn structurally suspends if its body calls a
  suspending method or reaches — via free-fn edges — one that does; transitive
  fixpoint) and follow such edges in the closure walk even when `suspends=False`.
- SECOND gap fixed same area: a suspending call in a `match <call> { … }`
  SCRUTINEE was never hoisted (hung even at DEPTH 1) — added
  `_hoist_suspending_match` mirroring the if-let/try hoists.
- DF6 (break/continue in a non-spanning if inside a spanning loop) root-caused +
  fixed here — see the DF6 entry below (now CLOSED).
- read_into: design-88-deferred `TcpStream.read_into(&var Data) -> Result<Int,
  IoError>` now works (the depth limit was the blocker) — OFFERED alongside value
  `read()` (accumulate into one buffer, no per-chunk alloc). Value read() NOT
  migrated.
- Tests: net_nested_method_two_deep / _three_deep (spawned worker → free fn(s) →
  read(), socketpair, deterministic), net_read_into, coro_break_reentered_in_loop.
  Suite 919 (was 915 + 4); bootstrap ok.

## Design 97 — libs/semver + libs/toml `blade test` harness fix (LANDED)
- Root cause of the recurring "libs blade test fail on a clean tree" flag
  (noted by designs 84/88/92): candidate (a). `blade test` compiles each test
  with `sawc` unless SAWC overrides it; the tester ran that compile through
  `system()` with `> /dev/null 2>&1`, so on a clean tree (no SAWC, no installed
  `sawc`) the "command not found" was swallowed and all tests reported FAILED.
  The tests + `import src.lib.*` self-path were always fine — the invocation hid a
  missing compiler.
- Fix (tester.saw, never-hide-errors): loud preflight — SAWC unset AND no `sawc`
  on PATH → one clear actionable error, stop (not N silent FAILEDs); compile+run
  via `shell_ok_loud` which suppresses only stdout and lets stderr through (sawc
  writes success to stdout, diagnostics to stderr; panic/failed-assert aborts to
  stderr) → a passing run stays clean, a compile error or a test's failure reason
  is surfaced.
- Coverage gap closed (blade_bootstrap.py): `libs/toml` + `libs/semver`
  `blade test` now run as a standard bar (SAWC set via ENV, as the main build
  already does), green (toml 4, semver 4); their gitignored `.blade/` cleaned
  after. TESTING.md updated. A user runs a lib's tests with nothing but
  `blade test` when `sawc` is installed / SAWC is set; on a clean tree the
  bootstrap sets SAWC for them.
- Suite 919 / 0 xfail; bootstrap ok incl. both lib suites.

## Design 93 — generic type-argument inference (LANDED)
- **NOTE:** no `designs/93-*.md` brief file exists on disk (the dispatch brief was
  the authoritative spec; recorded here). Retired the "type inference is not yet
  supported" rejection for generic free functions AND methods. `v.map({ $0.to_
  string() })` / `v.fold(0){...}` / `wrap(5)` / `first(7,"hi")` now infer their
  `<...>` from argument types; a method's own `<U>` is solved from the closure's
  inferred RETURN type (closure params come from the struct + phase-1 arg
  solutions). Commit 1 (feature + tests): unify abstract param types against
  actual arg types (`_unify_infer`, structural over function/optional/ref/ptr/
  array/tuple/struct-enum-args); a sandboxed pre-pass (`_infer_snapshot`/`_infer_
  restore` roll back moves + per-instantiation mono queues + `_poly_call_edges`,
  a throwaway suspend node catches enclosing-node effect edges) discovers arg
  types, then the SOLVED args are stamped onto `expr.type_args` (default-filled)
  so the existing explicit-path machinery (bounds, effect-poly recording, codegen
  monomorphization, coro-transform driven/spawned rewrite) runs BYTE-IDENTICALLY
  to an explicit call. Explicit `<...>` always allowed + wins; a partial explicit
  prefix pins its leading params and the rest infer; an unconstrained trailing
  param with a default type fills from the default. Clean diagnosable failure:
  underdetermined ("cannot infer type argument `T`" + explicit-args hint) and
  conflict ("required to be both `Int` and `String`") — never a silent wrong pick.
  Inferred args are bound-checked naming the inferred type; the generic-METHOD
  path previously did NO bound checking at all — added `_check_type_param_bounds`
  (Copy structural + `_bound_satisfied` for the rest), run on BOTH explicit and
  inferred method calls (fix-on-discovery). Driven (`__drive(run(move s))`) +
  spawned (`group.spawn(work(x))`) inferred generics monomorphize per INFERRED
  instantiation identically to explicit (the `__drive`/`spawn` handlers check the
  inner call first, so inference stamps `inner.type_args` before the mono
  rewrite). BOUNDARY (for the skill/spec): inference is single-pass left-to-right
  (non-closure args, then closures) — a param determinable only by a LATER arg
  than one it gates is not solved (give it explicitly); labeled + out-of-order +
  inferred is treated positionally (rare; give explicit args if it mis-maps).
  Overloaded-call generic inference (design-55 `_check_overloaded_*` paths) NOT
  wired — those still require explicit `<...>` on a generic overload (the design-55
  concrete-beats-generic model is unchanged; inference there would risk new
  cross-overload ambiguity — deferred). Retired obsolete
  `generic_method_requires_explicit_args` test. Tests: `infer_type_args` (free
  single/multi, method map/fold, mixed explicit+inferred, defaults, explicit-wins),
  `errors/infer_underdetermined`, `errors/infer_conflict`,
  `errors/infer_bound_violation`, `infer_generic_driven`, `infer_generic_spawned`.
  Suite 915 (910 −1 obsolete +6), bootstrap ok. [93, 36, 55, 70, 74, 37]

## Design 82 — per-file std visibility + prelude discipline (IN PROGRESS)
- **Part A (per-file std visibility) — LANDED.** Retired design 80's std-as-one-
  module deviation: `_vis_module_for_source` now keys each std/builtin file to its
  OWN member-gate module `("<std>", "<leaf>")` (was the single `("<std>",)`), so a
  private field/method of one std file is invisible to another — same rule as user
  modules. `_member_gate_allows` roots the package at `("<std>",)` for std-defined
  members so `public(package)` shares across std files (and excludes user code).
  Synthesized-provenance exemption unchanged; codegen/compiler-known-ness untouched
  (ACCESS check only). ABUSE AUDIT: **ZERO restructures / zero new `public(package)`
  needed** — design 80's public sweep already exposed every legitimate cross-std-
  file surface, so per-file gating is a pure tightening with no code churn. Gate
  verified live: temporarily un-`public`-ing `Vector.push` makes the builtin check
  reject its cross-file callers (directory.saw/env.saw/…) with a clean member-
  visibility error naming both std files; restored. Suite 905 (unchanged), bootstrap
  17+17 green. [82, 80]

## Design 82 Part B — prelude discipline (LANDED)
- **The prelude is now a CURATED ALLOWLIST, not "all std auto-merged".** Defined
  by its complement in sawc.py: `IMPORT_REQUIRED_STD_MODULES` (file, directory,
  path, data, channel, mutex, time, net, process, env, task — whole modules) +
  `IMPORT_REQUIRED_STD_SYMBOLS` (`Utf8Error` from string). `build_builtin_namespace`
  makes ONLY prelude symbols `directly_accessible`; the rest stay registered
  (compiler-known) but hidden. `import std.<mod>[.{A,B}|.*]` is a PRELUDE import —
  resolution is SKIPPED in the resolver (`imp.path[0]=='std'` → `continue`, symbols
  already in builtins) and `_process_std_import` un-gates the requested names (no
  `mod.Name` module alias — it would shadow common locals like `data`).
- **Gate + hint.** A bare source reference to a hidden std symbol (static call,
  struct init, free-fn call) errors: "`X` is not in the prelude and must be
  imported" + hint `add import std.<owner>.{X}`. `_std_name_gated` is exempt for
  std's own bodies (`_checking_builtins`) and synthesized coro output. A std-
  sourced method/function body re-checked in a user compile (design-84 spliced
  suspending std method) is checked permissively (`_decl_is_std_sourced` →
  allow_all_access) so it reaches its own internals.
- **No codegen collision (the design-84 IoError clash CLOSED).** Non-imported
  import-required std modules are EXCLUDED from codegen: `compute_std_codegen_exclusions`
  computes the compiled set = prelude ∪ imported ∪ transitive-dep-closure (comment-
  stripped source scan; `string`→`data`, `taskgroup`→`task` stay), `_filter_std_ast`
  drops excluded decls, and the merged-ns collision check skips them (`merge_into`
  `exclude=`). So a user may define its own `struct IoError`/`File`; `_shadows_hidden_std`
  lets the user decl replace the (uncompiled) merged builtin without a "defined
  multiple times" error. StringBuilder VERDICT: KEPT in prelude (borderline, common).
- **Migration.** 56 examples + 8 blade/src + 15 blade/tests gained `import std.X.{...}`
  for the non-prelude types they use (libs/sos needed none). New suite tests:
  `prelude_user_ioerror` (user IoError+File compiles/runs), `errors/prelude_tcp_needs_import`
  (bare TcpStream → clean import error), `prelude_import_makes_visible` (import
  un-gates Duration; Vector bare works). Suite 908 (905→+3), bootstrap 17+17. [82, 84, 80]

## Design 88 — references across suspension points (implement D6) (IN PROGRESS)
- **Core LANDED (commit 1).** A reference PARAM/LOCAL of a suspending function
  is now a frame-resident RAW POINTER across suspensions (`_enc_of` REFERENCE ->
  "ref"; field `UnsafePointer<T>`, pointer mut mirrors the ref; read rewritten to
  `self.name[0]` — the `__recv[0]` mechanism of 45-0c generalized). Drive site
  casts `&x`/`&var x` -> `UnsafePointer<T>` (`_ref_arg_to_ptr`), driver param is
  the pointer, frame seeds it directly. Re-typecheck ACCEPTS it (member access /
  mutation / method calls flow through the deref lvalue); synthesized resume is
  exempt from the design-81 `unsafe` marker. Ref field is NON-owning — exempt from
  drop flags, never dropped (deinit stays exactly-once). Both `&T`/`&var T` and
  `&var self`. Frame kinds allowing held refs: **DRIVEN-in-place = YES;
  SPAWNED-cross-task = NO** (`_reject_spawn_frame_refs` — a spawned frame with a
  ref param/across-suspend ref local is a hard error for BOTH single- and
  multi-threaded groups, confinement not merely Send). Tests:
  coro_ref_param_read/_mut/_self_method/_deinit_once + coro_spawn_ref_rejected.
  Suite 904 (was 899); bootstrap green.
- **Item 5 (nested ref + capability) LANDED (commit 2).** A NESTED suspending
  call's reference argument is seeded into the callee sub-frame as a pointer into
  the TASK frame (`_build_sub_frame` casts `&self.<field>` -> `UnsafePointer<T>`);
  a reference to a task-CONFINED local inside a spawned body is sound and allowed.
  The spawn rejection now fires ONLY on the spawn ROOT's own ref params/locals
  (its referent is the dead spawner stack) — NOT on embedded callees (refs can't
  escape owned values, so a nested callee can only get a task-frame pointer once
  the root carries none). Tests: coro_spawn_nested_ref (read_into-shaped helper
  holding a `&var` across a `yield_now` in a spawned worker, through the real
  multi-task scheduler). NET `read_into` over a real socket is BLOCKED by an
  orthogonal PRE-EXISTING limit: a suspending `stream.read()` buried TWO frames
  deep (spawn-root -> nested free fn -> nested method) HANGS — reactor token
  propagation reaches only one nesting level (value-based control hangs
  identically; NOT a design-88 issue). VERDICT: keep the value-based `read()`;
  defer a `&var Data` net read until that depth limit is fixed. Suite 905.
- **Items 4 + 7 LANDED (commit 3).** Item 4 VERDICT: KEEP the `sync`-body
  restriction on `Vector.with_ref`/`with_var_ref` — unlike a D6 held reference
  (task-confined stack/frame referent unreachable by other tasks), a container
  borrow projects into shared reachable storage a concurrent task could realloc
  across a suspension (iterator invalidation); confinement does not cover it.
  Documented in vector.saw. Item 7: spec concurrency updated (D6 implemented +
  driven/spawned boundary + with_ref caveat); saw-lang skill concurrency note
  added (references-across-suspend capability + spawn-root rejection + net stays
  value-based). **Design 88 COMPLETE** (scope items 1-7 all addressed).
- **FLAG (pre-existing, unrelated) — CLOSED by design 97.** `libs/semver` +
  `libs/toml` `blade test` suites fail on a CLEAN tree. Root cause: the tester ran
  the compile through `system()` with `> /dev/null 2>&1`, so with no SAWC set it
  silently fell back to a `sawc` that isn't on a clean PATH and swallowed the
  "command not found" — every test reported a mysterious FAILED. Not the
  `import src.lib.*` self-path (fine). See the design 97 entry.

## Design 94 — enum/Result payload sizing + temp-drop-at-merge (IN PROGRESS)
- **Codegen chain LANDED (commit 1).** Two frame-layout-sensitive bugs, both
  root-caused with a deterministic `-O0` repro (`blade build --force` 12/12
  SIGBUS at -O0; ~40% at -O1) + the design-85/86 discipline. (1) enum/Result
  CREATE paths (`_create_result_ok/err_for_return`, `_wrap_error_in_union`,
  `_generate_enum_init`) alloca'd the SMALLER variant struct but bitcast-LOADED
  the FULL `[N x i8]` payload — an OOB stack read past the slot; fixed to alloca
  the full payload (align 8), store the variant struct into its front, load the
  whole array. (2) The create-fix shifted the frame and exposed the real
  `Builder_build` crash: a statement TEMP created in a block's `final_expr` (an
  unbound method receiver — here `read_file(".blade/build-hash")` in the inner
  `if …equals(hash)`, itself the tail-expr of the outer `if not force` body) was
  registered in the ENCLOSING statement's temp list and dropped at the outer
  `if`'s MERGE block — reachable from the not-taken `else` where the temp was
  never initialized → `String_deinit` released an uninitialized (garbage) pointer
  → EXC_ARM_DA_ALIGN on the refcount atomic. Fix: `_generate_block` now drains
  the statement temps created during its `final_expr` at block end, on the paths
  that create them, before the merge. Suite 897 green; bootstrap green; `blade
  build`/`--force` reliable 15x + under libgmalloc (0 faults, O1 and O0).
- **Process module LANDED (commit 2 — the acceptance).** `Command.run() ->
  Result<Int32, ProcessError>`: Ok(code)=the command launched and exited with
  `code` (signal death still decodes to 128+signum via decode_wait_status);
  Err(ProcessError)=could not launch (`system()` returned -1, or the shell
  reported 127 "command not found"). `ProcessError` conforms to `Error`
  (Printable), names the failed program. Callers migrated: blade `builder.build`/
  `builder.run` (match; a launch failure → BuildError), `git` clone/checkout
  (Err → false). Forced-failure test `examples/process_error_surfaced.saw`
  (nonexistent command → Err, error names the program). Suite 898; bootstrap
  green; blade `build`/`--force` reliable 10x + gmalloc 6x at O1 AND O0, zero
  faults — that reliability WITH the process module back in build()'s frame (the
  original design-92 trigger) is the proof the codegen chain is fixed. The
  design-92 `write(s: String)` overloaded-suspending-method fix stays deferred
  (design 95).

## Design 92 — failable calls return Result: no silent swallow (IN PROGRESS)
- **net module LANDED** (commit 1): `TcpStream.write(bytes: Data)`,
  `read() -> Result<Data, IoError>`, `TcpListener.accept() -> Result<TcpStream,
  IoError>` all surface failure; the swallowing `write_all`/`write_all_str`
  removed. read's EOF is `Ok(empty)`, DISTINCT from `Err` (was: empty Data meant
  both). Forced-failure test `net_error_surfaced` (connect-to-closed-port → Err;
  peer-closed read → Ok empty). Enabling compiler work: `Result<Void, E>` support
  (enum void-payload filter + Ok/void create/extract + bare `return`→Ok(Void) +
  match `Ok(_)` on void); `ResultOkWrap`/`ResultErrWrap` re-typecheck visitors (the
  post-coro-transform re-check was skipping their rewritten inner expr → ICE);
  coro-transform TRY-HOIST (a `try! recv.m()` in a driven body now hoists to a
  driven temp + `try move __t` — the tried suspending call was hidden inside a
  `TryExpr` the nested-call scan couldn't see, so its `io_wait` park never
  integrated with the executor → hang; the `move` consumes the temp so its owning
  payload is not double-dropped/closed).
- **CLOSED by design 95 — coro-transform now drives OVERLOADED suspending
  methods.** Driven/embedded suspending-method frames are keyed by the design-55
  RESOLVED SIGNATURE (the overload-mangled `$OL$`/`$LB$` symbol the typechecker
  stamps: `mangled_symbol` on the method AST, `resolved_symbol` on the MethodCall)
  via one canonical `_method_frame_key` helper — a non-overloaded method has no
  symbol and keeps its plain `{struct}_{method}` key (unchanged). `write(s: String)`
  is re-added as the text overload of `write(bytes: Data)`; the `.to_data()` call-
  site workarounds are reverted (httpd/echo/net examples).
- **file/directory/env LANDED** (TIER 2, Bool→`Result<Void, IoError>`): `file`
  {`remove`,`rename`}, `directory` {`create`,`remove`,`set_current`}, `env`
  {`set`,`unset`,`set_cwd`} now surface the errno; `exists`/`contains` stay
  genuine boolean questions, `list`/`current`/`get` stay `T?`. Public
  `IoError.from_errno(syscall)` factory added (net.saw) as the cross-std-module
  constructor. blade callers migrated (`match`/`let _` on the Result). Forced-
  failure tests: file/directory/env `_error_surfaced`.
- **codegen LANDED (design-92 dogfood):** enum/Result payload SCRATCH allocas are
  now 8-aligned (`_entry_alloca(..., align=8)` on the extract byte-arrays). The
  payload is `[N x i8]` (ABI align 1) but is bitcast-and-loaded as the variant's
  field struct (8-aligned pointers/i64); the 1-aligned slot faulted on arm64
  depending on frame layout — a heisenbug the added Result monomorphizations
  tipped (`blade build --force` SIGBUS ~1/3; deterministic under MallocScribble).
  This alone made the bootstrap reliably green again.
- **process DEFERRED — a SECOND, DEEPER latent codegen bug.** `Command.run() ->
  Result<Int32, ProcessError>` is implemented + all callers migrated (blade
  git/builder, process examples + `process_error_surfaced`) and the full suite
  passes 898 — BUT it re-tips a distinct crash in blade's large `build` frame (a
  garbage-POINTER read / translation fault at teardown, ~40% normal). ROOT (found,
  NOT yet safely fixed): the enum/Result CREATE paths (`_create_result_ok/err`,
  `_wrap_error_in_union`, `_generate_enum_init`) alloc the (smaller) VARIANT struct
  but bitcast-load the FULL `[N x i8]` payload → an out-of-bounds stack read past
  the slot. The obvious fix (alloc the full payload, store the variant into its
  front) is suite-green but shifts the frame and tips YET ANOTHER latent issue in
  `Builder_build` (blade went 8→20/20) — so it needs a focused codegen
  investigation, not a design-92 rider. Process change is reverted; std stays at
  `run() -> Int32` until the codegen bug is fixed. (Evidence: crash reports show
  `Builder_build` garbage/alignment reads at teardown; masked under lldb + normal
  heaps; MallocScribble makes it deterministic.)
- **TODO:** land process once the codegen OOB/uninit bug is fixed; borderline
  `file.write`/`seek` `Int?`→Result (report); the overloaded-suspending-method
  fix that restored `write(s: String)` is DONE (design 95, below).

## Design 95 — driven-method frames keyed by resolved signature (LANDED)
- Coroutine transform keyed a driven suspending METHOD's frame by
  `(struct, method-name)`, so two OVERLOADS of one name collapsed to a single
  frame (design 92's deferred `write(s: String)`). Fix: one canonical
  `_method_frame_key(struct, name, resolved_symbol)` helper keys every driven/
  embedded/direct-drive method frame by the design-55 resolved-signature symbol
  (`mangled_symbol` on the method AST at the definition side; `resolved_symbol` on
  the MethodCall at call sites); non-overloaded methods carry no symbol → plain
  key, byte-for-byte unchanged (coro_*/taskgroup_*/net_* families untouched).
  `_driven_method_roots` re-keyed by frame key so a directly-driven overload also
  gets its own frame; `_find_method` disambiguates by symbol. `net.TcpStream`
  re-gains `write(s: String)` (whole-string bytes) alongside `write(bytes: Data)`;
  `.to_data()` workarounds reverted at the net examples. New regression test
  `net_write_overloads` (spawned worker calls BOTH overloads back to back).
  Suite 899 (+1), bootstrap green, libs (toml/semver) green.

## Design 90 — reactor lost-wakeup on the 2nd sequential connection (LANDED)
- **Root cause (VERIFIED with an instrumented repro, NOT the brief's guessed
  suspects).** It was NOT one-shot re-registration, wake-all clearing the wrong
  frame, an fd-map collision on a reused fd, or a poll/deadline skip. The reactor
  wakes ALL io-parked frames on ANY readiness event (coarse level-triggered
  retry), so EVERY parking op must re-verify its OWN fd and re-park on a spurious
  wake. `read`/`write`/`accept` already loop on would-block; **`TcpStream.connect`
  did NOT** — it parked ONCE on `io_wait(fd, 1)` then called `tcp_connect_check`,
  a v1 STUB that unconditionally returned 0 (success). In a multi-connection
  workload a client's connect-park was spuriously roused by the reactor's wake-all
  on a DIFFERENT fd's event (the listener becoming readable) BEFORE its own socket
  was writable; it trusted the wake, wrote on the still-unconnected socket →
  ENOTCONN (errno 57, confirmed via instrumentation), and `write_all_str` silently
  bailed on the hard error. The request was never sent, so the accepting server
  parked forever on the read of that connection. Single-connection round-trips
  (`net_accept_roundtrip`) work because no other fd triggers an early spurious wake.
- **Fix.** `connect` now LOOPS like the other ops: after each `io_wait(fd, 1)` it
  RE-VERIFIES completion by re-issuing the nonblocking `connect()` and classifying
  the result — connected (`EISCONN`/0), still-connecting (`EINPROGRESS`/`EALREADY`
  → re-park), or a real failure. Classification lives in a new compiler shim
  `saw_errno_connect_state()` (OS-divergent errno values stay in the compiler,
  mirroring `saw_errno_would_block`); `tcp_connect_check(fd, port)` gained the port
  arg to rebuild the sockaddr for the re-connect. This makes an arbitrary SEQUENCE
  of io-parks across multiple accepted fds (incl. fd-number reuse across connection
  turnover) each get their wakeup; the never-block invariant + earliest-deadline
  poll are untouched (no scheduler change).
- **FLAG (pre-existing, orthogonal — NOT fixed here, API-change scope):**
  `TcpStream.write_all`/`write_all_str` SILENTLY bail on a hard write error
  (`w < 0` -> `going = false`, no signal) — this is exactly what MASKED the connect
  bug (the ENOTCONN write vanished with no error). Their return type is `Void`, so
  surfacing the error means changing the signature to `Result<Void, IoError>` (a
  public-API change touching every call site) — deferred as a genuine design
  decision rather than silently widened here. With connect fixed the socket is
  connected before any write, so this path no longer fires in practice, but a real
  broken-pipe mid-stream would still be swallowed. [90, 84]
- **Result.** `probe_loopdiag` (server serves N=2 + 2 clients, one group) now
  round-trips fully (both connections read+write; result 2,1,1). Tests (all
  deterministic on content, time-bounded — the design-86 runner timeout catches a
  regression as a FAILURE not a wedge): `net_serve_two_connections` (N=2),
  `net_serve_three_connections` (N=3), `net_fd_reuse_across_connections` (one
  client, two strictly-sequential connections reusing the freed fd number on both
  ends), `net_two_concurrent_parked_reads` (two readers parked on different
  socketpair fds both wake). Updated `examples/net_loopback_echo.saw` to the new
  `tcp_connect_check(fd, port)` re-verify loop. Docs: saw-lang skill net note
  rewritten (multi-connection accept-loop now works; the per-op re-check is
  internal). Suite 888 (from 884), all net_*/coro_*/taskgroup_* green, bootstrap +
  libs green. [90, 76, 84, 89]

## Design 91 — precise reactor wakeup (retire wake-all) (IN PROGRESS)
- **Core landed.** The reactor no longer wakes ALL io-parked frames on any
  readiness event. `saw_reactor_register(fd, write, token)` carries a udata
  pointer (kevent.udata / epoll_event.data) = the parked frame's `__wake`-word
  address; `saw_reactor_poll` reads back each ready event's udata and LATCHES
  that word to 0 (ready), so only the frame(s) whose (fd, direction) fired wake.
  The latch is a persistent word (not an edge) → a fire that races the park is
  caught on the next scan (no lost wakeup, ST or MT). The scheduler
  (`__ambient_wake_io` + MT `__tg_worker`) wakes an io-parked frame only when its
  `__wake_reason()` has become >= 0. Nested-call routing: a new frame field
  `__io_tok` holds the ROOT frame's `__wake` address (a driven root sets it on
  first resume; each nested drive propagates it down), so an `io_wait` buried in a
  sub-frame routes its wakeup to the top-level frame the scheduler schedules.
  design-90 connect re-verify KEPT (belt-and-suspenders). Many-frames-one-fd:
  different directions = independent registrations (both precise); same direction
  = last-registrant-wins (documented, unsupported pattern). [91, 76, 90, 89b]

## Design 89 — executor unification: one ambient scheduler (IN PROGRESS)
- **Prep — LANDED (612e53d).** Coro-transform **static-visibility fix**: a
  suspending std method that names a module-private `static` (e.g.
  `TcpListener.accept` -> `INVALID_FD`) now compiles when spawned/driven — the
  const initializer is inlined at the reference site during the transform
  (`_inline_static_refs`). Before this, `accept()` could not be embedded at all,
  so NO accept-loop program compiled (`net_fd_leak` never exercised `accept()`,
  masking it). `read`/`write` reference only free functions, hence unaffected.
  Test: `net_accept_roundtrip.saw` (spawned server accepts ONE loopback conn +
  serves a GET; deterministic). Suite 884, bootstrap 17+17, libs 4+4. [89, 84]
- **Core unification (items 1-6) — DEFERRED to a follow-on (design 89-b),
  re-ledgered with analysis.** Evidence-based risk call (the brief's "defer if
  large/risky" escape). PROVEN this session: (1) the gap is real — `probe_gap`:
  a spawned child runs ONLY at `join`, never while main parks (today's split
  executors). (2) A SECOND, INDEPENDENT blocker gates the accept-loop
  acceptance: a **design-76 reactor lost-wakeup** in the multi-connection
  accept-loop — `probe_loopdiag` (server serves N=2 + 2 clients, ONE group)
  accepts conn#0, serves it, accepts conn#1, then the **read on the 2nd
  connection never wakes** (hangs at marker 911). A SINGLE accept round-trip
  works. Unifying the executor does NOT fix this — the accept-loop acceptance
  needs BOTH the unification AND the reactor fix. **The reactor lost-wakeup is
  now CLOSED (design 90, LANDED — see below); it unblocks the 89-b accept-loop
  acceptance, which now only needs the executor unification.** Why the core is large/risky + the recommended per-commit
  plan (ambient heap-singleton via a `static Atomic<Int>` addr, per-frame
  group-id membership, active-frame reentrancy skip, deinit-exactly-once box
  hand-off, MT bifurcation, then the reactor fix, then the op-count budget):
  see the STATUS section of `designs/89-executor-unification.md`. Repro files
  under `.build/scratch/` (`probe_gap`, `probe_loopdiag`, `probe_accept*`).
  [89, 45, 52b, 76, 75, 86]

## Design 89-b — executor unification core (WORKTREE, IN PROGRESS)
- **Steps a+b+c — LANDED (worktree).** The ambient cooperative scheduler:
  ONE per-thread sweep over an intrusive list of every live single-threaded
  TaskGroup (`static __saw_exec_head`, threaded through a new group `next`/
  `registered` field pair). Realized the design-89 "one shared run queue" as a
  registry-of-group-queues (each group keeps owning its boxes) — this keeps the
  battle-tested per-group deinit-exactly-once machinery intact and DISSOLVES the
  flat-queue box-ownership-hand-off hazard the STATUS flagged, while being
  behaviorally the pinned model (eager spawn, structured join, nested groups,
  reentrancy). One parameterized sweep `__ambient_run(term_group, term_slot)`
  reused verbatim at all three drive points: ALL (entry), GROUP (Deinit),
  FRAME (join); each SKIPS frames `active` on the C stack (reentrancy guard —
  task-joins-task yields to the one scheduler, never re-enters a live coroutine).
  A suspending `main` that also spawns is boxed as the ROOT member and driven by
  the shared sweep (`__exec_run_root`), so a spawned sibling runs whenever main
  parks (the core gap: `probe_gap` now INTERLEAVES `0,100,101,1,102,2,7` instead
  of `0,1,2,100,101,102,7`). Design-45 single-task main (no spawn) keeps the
  lighter single-frame executor; MT groups (workers>=2, design 75) keep their own
  worker pool + queue and never join the ambient list (bifurcation preserved).
  Bars green: suite 888, bootstrap 17+17, libs toml 4/4 + semver 4/4. NOTE: one
  non-reproducible `dep_build` SIGABRT flake observed under load (that test shells
  out to compile+run subprocesses; its path uses no concurrency, so unrelated to
  this change — baseline + reruns all green). [89, 45, 52b, 76, 75]
- **Test matrix — LANDED (worktree).** Three NEW tests for behavior the old split
  executors could not produce (suite 888->891): `net_accept_loop_concurrent`
  (ACCEPTANCE — a server task accept-loops N=3, SPAWNING a handler per connection
  into its OWN group that runs eagerly on the shared scheduler while the server
  parks, + 3 concurrent client tasks; round-trips all N, deterministic 3/3);
  `taskgroup_spawn_and_loop` (the core gap — main parks in a sleep-loop while its
  spawned child INTERLEAVES `0,100,101,1,102,2,7`, not the old
  `0,1,2,100,101,102,7`); `taskgroup_nested_ambient` (nested groups + a task
  joining its own inner children = the reentrancy hazard, cross-group eager
  interleave). Existing coverage survives and validates the rest under the ambient
  scheduler: `taskgroup_sleep_ordering`/`structured_join`/`unjoined_drop`/
  `two_task_yield`/`cancel_check`, `net_io_sleep_interleave`, `net_serve_two/three_
  connections`. Updated the now-stale per-group-executor comments in
  `taskgroup_nested_groups` + `taskgroup_suspending_parent_sleep` (results kept).
  **DF finding (pre-existing, reproduces on parent):** spawning a function whose
  param transitively references a std struct (e.g. `f(h: TaskHandle<Int>)`) ICEs
  "Undefined struct: TaskGroup" during frame layout — unrelated to executor
  unification; reentrancy is instead tested via nested-group joins. [89, 52b, 76]

## Design 89-c — cooperative op-count budget (LANDED — CLOSES the 89 family)
- **The fairness backstop.** A task that keeps completing suspending io ops WITHOUT
  ever parking (an always-ready socket) can no longer monopolize the single-threaded
  ambient scheduler — the design-89 item-6 starvation caveat. Op-count, not
  wall-clock (kernel-friendly, deterministic); no preemption, no language surface,
  purely at existing suspension points.
- **Mechanism (codegen/core.py `_declare_io_runtime`).** A process-global op counter
  `__saw_op_budget` (default 128) + two weak/monotonic-atomic seams: `saw_op_budget_
  tick()` decrements and returns non-zero (self-resetting to the default) when
  exhausted; `saw_op_budget_reset()` restores it. Each net io primitive
  (accept/connect/read/read_into/write×2), on its NON-parking success path, ticks and
  force-`yield_now()`s when the tick fires (park-and-immediately-reschedule → cede to
  siblings), and calls reset after a genuine `io_wait` park (already ceded). The
  counter is self-resetting on exhaustion, so it works uniformly under the
  ambient/MT/single-task/`__drive` executors with NO scheduler or synthesized-executor
  edits; monotonic-atomic keeps MT workers race-free (shared budget there, benign).
- **Zero overhead for sync code.** Only a suspending io primitive ever charges the
  counter — code that makes no such calls never touches it. Well-behaved tasks (<128
  non-parking ops between parks, which reset the budget) never hit the forced yield,
  so existing coro_*/taskgroup_*/net_* interleavings are UNCHANGED (suite green, no
  interleaving test needed adjustment). Channel receive was deliberately NOT
  instrumented: in the ST cooperative runtime a channel consumer that outruns its
  producer DRAINS the channel and then parks on empty (the producer only runs when
  the consumer cedes), so an always-ready channel monopoly is impossible — only io,
  fed by the kernel/peer independent of the local scheduler, is the real vector.
- **Test `net_budget_fairness`.** A `recirc` task reads one socketpair end and writes
  the bytes back into the OTHER (refilling the read side) → every read is always-ready
  and never parks, an endless io loop whose only exit is a stop flag a sibling sets
  after its own turns. Without the budget `recirc` never cedes → the program hangs
  (the design-86 runner timeout turns that into a FAILURE); with it, `recirc`
  force-yields every 128 ops, the sibling completes and sets stop, and it prints 5.
  Deterministic (pure op-count) + time-bounded. Verified discriminating: neutering
  the tick makes it hang (SIGKILL 137), the real budget prints 5.
- ~~**DF7 (pre-existing coro-transform silent miscompile).**~~ CLOSED (design 101). A
  suspending METHOD call buried under a nested/TRAILING `if`/`else`/`match` in a
  driven/spawned body lowered as a PLAIN blocking call (cooperative park a no-op).
  Root cause: the wrapper hoists + collect/reject walk ignored `block.final_expr`
  and ran before `_normalize_suspending_tails`, so a call in a trailing-expression
  position was never statementized in time to be hoisted/classified/rejected.
  Fixed by running tail normalization FIRST; also preserved match `pattern`/`guard`
  in `_split_match` and taught `_reject_buried_suspend_call` to flag buried
  suspending METHOD calls (if-let/guard bodies now reject cleanly). See the design
  101 section above. [101, 96, 84, 83, 74, 89-c]
- Suite 929 (928 + `net_budget_fairness`); bootstrap ok (blade 17+17, libs toml 4 +
  semver 4); zero xfails. Docs: saw-lang skill concurrency caveat replaced with the
  landed backstop + residual pure-compute limit; LANGUAGE_SPEC concurrency gained an
  implicit-yield + op-count-budget bullet. **The design-89 executor-unification family
  (89 / 89-b / 89-c) is now COMPLETE.** [89-c, 89, 89-b, 45, 52b, 76]

## Design 87 — consolidate literal coercion + stable type-ids (IN PROGRESS)
- **Item 1 (ONE literal-coercion pass) — LANDED.** Integer-literal fixed-width
  typing now routes through the EXISTING expected-type propagation
  (`_apply_literal_expected_type`), which became the single recursive pass that
  pushes a fixed-width expectation to a bare literal AND through the transparent
  constructs that forward a value: unary minus (range-checks the FOLDED value so
  Int32.min's magnitude is admitted), if/match/block arm results, and
  array/tuple/map/set element positions. `visit_IntLiteral` (typechecker) adopts
  the expectation; codegen `visit_IntLiteral` materializes at the resolved
  fixed-width width. AUDIT (all were BROKEN pre-87): array-literal elements into
  `[IntN;M]` (stored platform-wide, no range check), tuple elements (same),
  if/match arm results (narrowed but NO range check), compound-assign RHS
  (`x += 1`, Int8 → i8-vs-i64 ICE), default parameter values (silently wrapped),
  Map/Set literal keys+values (unchecked) — now all coerce + range-check
  uniformly. DELETED the per-position `_check_fixed_width_literal` calls the
  central pass subsumes: method/func tail-return, `return <expr>`, regular +
  overloaded call args, struct-field + custom-init args, enum payload. KEPT
  `_check_fixed_width_literal` + `_fixed_width_binop_type` for the two
  SIBLING-OPERAND positions (comparison `b < 200`, arithmetic `b + 0`) — the
  expectation there is the other operand's type, discovered only AFTER checking,
  so it genuinely can't route through a declared-slot expected type. INVARIANT
  held: no fixed-width expectation ⇒ platform Int (`let x = 5`, Int/Int
  arithmetic byte-identical); full suite is the oracle. Tests:
  `literal_coercion_positions` (all positions round-trip) +
  `array_element/tuple_element/compound_assign/if_arm/default_param/map_literal_key`
  `_..._out_of_range_error` (6 clean range errors). Suite 883 (from 876),
  bootstrap 17+17, libs 4+4. [87, 65, 53, 77, 81, 54, 29]
- **Item 2 (stable erased-error type-ids) — LANDED.** Replaced design-72's
  per-compilation MONOTONIC COUNTER (memoized by mangled name, order-dependent)
  with a deterministic FNV-1a 64-bit hash of the mangled type name (same
  constants as the runtime Hasher in builtin.saw), masked to the platform word so
  it fits the vtable's `int_type` type_id slot. The id is now a pure function of
  the type NAME, so the SAME concrete type gets the SAME id in EVERY compilation —
  a future separate-compilation boundary would agree on `is<T>()`/`take<T>()`, not
  just the current whole-program build. `is<T>`/`take<T>` behavior identical (both
  the vtable bake and the downcast compare call the one `_type_id_for`); existing
  downcast tests green. COLLISION POSTURE (documented in `_type_id_for`): a 64-bit
  FNV space over distinct mangled names makes an accidental clash negligible (a
  birthday clash needs ~2^32 conformers in one program); ids are compared only for
  EQUALITY (never as a sentinel), so `0` is now a legal id (the old counter
  reserved it). Test: `tools/test_stable_type_id.py` (IR-level, in the
  `test_debug_info.py` family) — compiles two programs that conform `Circle: Shape`
  in DIFFERENT declaration positions among DIFFERENT companion types, extracts the
  type_id baked into Circle's vtable from `-O0` IR, and asserts (a) the two are
  IDENTICAL (the old counter would give Circle id 1 vs id 3 → order-dependent, and
  this test would fail) and (b) it equals FNV-1a("Circle") (pins the scheme).
  Docs: spec Integer-Types section (a bare literal adopts a fixed-width expected
  type everywhere) + saw-lang skill literal note. Suite 883, bootstrap 17+17,
  libs 4+4. [87, 72, 51, 48]

## Design 86 — httpd-runtime cleanup (IN PROGRESS)
- **Item 3 (`&var self` mutation on an opt-encoded frame-local across a suspend)
  — LANDED.** ROOT CAUSE: in `_generate_method_call` (codegen/calls.py), the
  `is_mutable_self` receiver-addressing chain handled `Identifier`/`SelfExpr`/
  `MemberAccess`/`ArrayIndex` but NOT `ForceUnwrap`. A `Data`/`StringBuilder`
  frame-local accumulated across a suspend is opt-encoded (design 62), and the
  transform rewrites a bare receiver `acc` → `self.acc!` (`_rewrite_node` →
  `ForceUnwrap`). That `ForceUnwrap` receiver fell through to the `else` branch
  that STORES a loaded copy into a fresh `self_temp` alloca and mutates the copy —
  so `acc.push(...)` / `req.append(move chunk)` across a park wrote to a discarded
  temporary and the real frame slot never changed. Silent in a pure loop (probe
  printed 0 instead of 3); a HANG in net_http_roundtrip (the empty `req` never
  matched the request terminator, so the handler re-`read()`s forever while the
  peer waits for a response → deadlock). FIX: add a `ForceUnwrap` branch that
  addresses the optional payload IN PLACE via `_generate_reference_expr(Reference
  Expr(mutable=True))` — the design-84 `&(opt!)` addressing (None-checked GEP to
  the payload slot) — so the `&var self` mutation lands on the real frame field
  and survives the suspend. Safe: `ForceUnwrap` is not an owned-temporary, so no
  stmt-temp double-free. TESTS: `net_accumulate_across_reads` (server appends 5
  lock-step "abc" chunks into a frame-resident Data across read+ack parks, asserts
  the FULL "abcabcabcabcabc" buffer + len 15) and the UN-QUARANTINED
  `net_http_roundtrip` (moved scratch → examples/; a socketpair read→build→write
  HTTP round-trip, now RUNS 5/1). Suite 876 (from 874), bootstrap 17+17, libs 4+4,
  zero xfails. [86, 84, 62, 44]
  - **httpd acceptance = the socketpair-reduced suite test (net_http_roundtrip).**
    The live `.build/scratch/httpd_sw.saw` now COMPILES + its `handle_connection`
    (`req.append(move chunk)` across `read()`) is unblocked, but the infinite
    `accept`-loop server as written does NOT serve a live GET — verified: it binds
    + prints "Serving …", but a `curl` GET returns empty. FLAG (separate
    architectural gap, NOT item 3): the loop does `let _ = group.spawn(handle…)`
    and NEVER `join()`s, so the spawned handlers only run at the group's Deinit
    (never, the loop is infinite); main's `accept`-park entry-executor does not
    drive a sibling group's run queue. net_http_roundtrip works because it
    `join()`s (which drives the group to completion). The fix is executor
    unification (main's park should drive spawned siblings) — a real concurrency-
    architecture design, out of scope here; the brief explicitly accepts the
    socketpair-reduced form as the acceptance. Skill runtime-limit note rewritten. [86]
- **Item 2 (variadic libc declaration audit) — LANDED (CLEAN, no fix needed).**
  Swept every libc declaration the compiler/std makes: all `_libc_func` call
  sites + all direct `ir.Function` decls in `sawc/codegen/*.py`, and every
  `extern "C"` func across `sawc/std/*.saw`. Cross-referenced each name against
  its C prototype. The COMPLETE set of variadic-in-C functions the toolchain
  declares is exactly FOUR — all ALREADY declared variadic:
  - `printf` — codegen core.py:336, `var_arg=True` ✓ (Float print path; Saw
    Float is f64 so no float→double promotion gap).
  - `snprintf` — codegen core.py:348, `var_arg=True` ✓ (int/float→string; ints
    promoted to i64 for `%lld`/`%llu`).
  - `fcntl` — codegen core.py:1354, `var_arg=True` ✓ (fixed in design 85 — the
    bug that motivated this audit).
  - `open` — std/file.saw:13, declared `func open(path, flags: Int32, ...)` ✓
    (variadic since introduction f6ebd80; called with the variadic mode arg by
    File.create/append `open(ptr, 577, 420)`).
  Every OTHER extern is genuinely fixed-arity in C and correctly declared
  non-variadic (malloc/free/fwrite/fflush/usleep/clock_gettime/memcpy/pthread_*/
  close/kqueue/epoll_*/kevent/strlen/strcpy/strcat/abort/socket/bind/listen/
  accept/connect/read/write/lseek/access/unlink/rename/mkdir/rmdir/opendir/
  readdir/getenv/setenv/system/popen/fread/strlcpy/strlcat/fabs/… + the saw_*
  seams). NO mis-declared variadic function remains after the design-85 fcntl
  fix — nothing to change. Behavioral variadic coverage already in the suite:
  the design-85 net tests (fcntl→O_NONBLOCK, the load-bearing case),
  `file_simple` (open-with-mode create→write→reopen→read-back roundtrip), and
  the float print/format tests (printf/snprintf varargs). Suite 874 unchanged. [86, 85]
- **Item 1 (test-runner run-phase timeout) — LANDED.** `run_executable` now
  runs each test's binary under a hard, process-GROUP-aware wall-clock cap
  (`RUN_TIMEOUT_SECS = 30`): `subprocess.Popen(..., start_new_session=True)` +
  `communicate(timeout=)`, and on expiry `os.killpg(SIGKILL)` the whole group
  (not just the child) then reap. This closes the wedge where a hung test that
  spawned OS threads / a grandchild holding the inherited stdout pipe would
  block the post-timeout reaper forever — a live hazard for every concurrency
  brief. A timed-out test is recorded FAILED (timeout), the runner never hangs.
  Proof: `tools/test_runner_selftest.py` (NOT globbed by the .saw suite) — 4
  cases incl. the grandchild-inherited-pipe wedge, all return < 10s under a 2s
  cap; plain hang + nonzero-exit + normal-exit paths covered. Suite 874,
  bootstrap 17+17, libs 4+4. [86]

## Design 84 — Safe net API: TcpListener/TcpStream owning types (IN PROGRESS)
- **Coro lift landed (commit 1):** nested suspending METHOD call embedded
  as a sub-frame in a driven/spawned body (`let s = recv.m()`, bare
  `recv.m(...)`, tail `return recv.m(...)`), driven across the caller's
  resumes exactly like a nested free-function call. Method frame keyed
  `{struct}_{method}`, `__recv` points at the receiver's caller-frame
  storage; `&self`/`&var self` both work; result threading + Deinit-once
  verified. CLOSES design 74 A5-rest shape 1 (the old `examples/errors/
  coro_buried_suspending_method.saw` rejection became the positive
  `examples/coro_nested_suspend_method.saw`, value 1012). Enabler: `&(opt!)`
  is now an addressable lvalue (address of the optional payload, None-checked)
  — a general language addition (typechecker `_is_lvalue` + codegen
  `_generate_reference_expr`) that lets an opt-encoded owning receiver in a
  frame be addressed.
- **Cross-module std method embedding landed (commit 2):** `TcpStream.read` /
  `TcpListener.accept` etc. live in std.net (imported), which is checked under a
  SEPARATE builtin typechecker — so the main one cannot infer their suspendability
  or reach their effect nodes. Fixes: (a) `build_builtin_namespace` computes the
  suspending (struct, method) set from the builtin typechecker's finalized graph
  and carries it forward (`typechecker._std_suspending_methods`); (b) the transform
  scans the MERGED extensions (not just entry_ast) for method ASTs + a structural
  body-scan (`_iter_method_calls`) discovers std method callees the edge-walk can't
  reach; (c) the std method frame + resume splice into entry_ast; the original std
  method stays as harmless dead code. Verified: a spawned worker's `stream.read()`
  parks on io_wait internally and wakes via the reactor (single-nested-call
  round-trip `examples/net_owning_echo.saw` — reliable, 5/5).
- **std.net owning types landed:** `TcpListener` (listen/local_port/accept) +
  `TcpStream` (connect/pair/read/write_all/write_all_str), both NoCopy with
  Deinit-closes-once; `IoError: Error` (errno via a new `saw_errno` seam). fd is a
  private `Int32`; the public surface has ZERO raw fds/pointers. Raw `tcp_*`/`net_*`
  layer kept as the private impl. `Data.append_bytes(ptr,len)` + `Data.byte_ptr()`
  added (pointer-signature = design-81 marked domain) for the socket read/write path.
- **DEVIATION from the pinned read/write signatures (flag):** `read(&self) -> Data`
  (empty = peer closed) + `write_all(&self, bytes: Data)` by move +
  `write_all_str(&self, s: String)`, NOT the brief's `read(&self, into: &var Data)
  -> Int` / `write_all(&self, bytes: &Data)`. Reason: a `&`/`&var`-reference PARAM
  cannot yet live in a coroutine frame (references opt-encode to a struct field of
  reference type, which the re-typecheck rejects). Reference-params-across-suspend
  is a separate, larger coro lift; deferred. The value API meets the GOAL.
- **⚠ PRE-EXISTING coroutine bug BLOCKS a true echo / the httpd runtime (FLAG,
  fix-on-discovery deferred with analysis):** a driven/SPAWNED worker whose body
  makes a SECOND nested suspending call AFTER the FIRST one PARKS on io_wait hangs
  at runtime (heisenbug — a `print` in the worker body perturbs it away). CONFIRMED
  PRE-EXISTING and NOT design-84: it reproduces with plain suspending FREE functions
  (`.build/scratch/probe_freefn.saw`) and hangs on the tree BEFORE this brief's first
  commit (checked out HEAD~1). Two nested calls where neither parks work
  (`probe_two_write`), and TWO nested yield_now calls work (`probe_two_nested`); the
  failing combination is specifically first-call-parks-then-second-call under the
  TaskGroup executor + reactor. Almost certainly an uninitialized frame field / run-
  queue re-entry issue (design 52b/76 territory). Effect: the socketpair ECHO
  (server: read→write) and the httpd worker (read_request→write) hang at RUNTIME; the
  deterministic suite test is therefore a single-nested-call-per-worker send+verify
  round-trip (reliable). Needs a dedicated fix pass.
- **httpd migrated (commit 3):** `.build/scratch/httpd_sw.saw` rewritten to the
  owning API — accept-and-`group.spawn`-per-connection, handler reads the request +
  writes the response over `TcpStream` methods. Compiles + reaches codegen with ZERO
  `unsafe`, ZERO raw fds, ZERO pointers (acceptance met). Kept in scratch (not
  examples/): it is an infinite accept-loop server AND its handler hits the
  read→write two-nested-call runtime bug, so it is not a suite smoke.
- **Tests landed:** `examples/net_owning_echo.saw` (single-nested-call send+verify
  round-trip in a TaskGroup, reliable) + `examples/net_fd_leak.saw` (Deinit-closes-
  exactly-once probe: 600 open+drop with no fd exhaustion). Suite 870.
- Deferred tests (blocked by structure / the pre-existing bug): peer-close→read 0
  (a completed child's fd only closes at group teardown, so a parked reader can't
  observe EOF in-flight); connect-failure→IoError (design-76 `tcp_connect_check` is
  a v1 stub that never reports failure); full echo (read→write = the two-nested-call
  bug). IoError:Error is exercised by the httpd's `{e}` interpolation (compiles).
- Docs: LANGUAGE_SPEC net section rewritten to the owning API (raw layer = private);
  saw-lang skill net section rewritten (+ the runtime-limit warning). CLAUDE.md not
  touched (it never documented std.net).

## Design 81 — Unsafe surface (`unsafe` marker + escape rules + with_ref) (IN PROGRESS)
- **String-escape rider (silent backslash-drop) — LANDED.** `"\r\n"` mis-lexed as
  `"r\n"` (len 2, bytes 114/10): the lexer dropped the backslash on any UNKNOWN
  escape and kept the raw char. Fixed in `read_string`: added `\r` (CR 13) and
  `\0` (NUL 0, counted by len — interior NULs are representable), and any OTHER
  unknown escape is now a clean lex error (``unknown escape `\d` ``) — never a
  silent drop. Supported set is exactly `\\ \" \n \t \r \0 \u{...}` + `\{ \}`.
  CRLF-in-SOURCE already lexes cleanly (a `\r` between tokens is skip_whitespace);
  verified (a real-CRLF .saw compiles + runs). Tests: `string_escapes` (\r\n =
  13/10, \0 counted, \t = 9), `errors/string_unknown_escape`. Docs: spec string
  section + saw-lang skill escape list. Suite 856, bootstrap 17+17, libs 4+4. [81, 07]
- **Fixed-width arithmetic literal-coercion rider — LANDED.** Arithmetic mixing a
  fixed-width local with a bare int literal (`b + 0` for `b: Int32`; suffix locals
  too) ICE'd "i32 != i64" (the checked-arith intrinsic saw i32 vs the platform i64
  literal). Design-77 item 9 covered COMPARISON position only; now extended to
  general ARITHMETIC (`+ - * / %`, both operand orders, all fixed-width kinds): the
  literal adopts the fixed-width operand's type (typechecker `_fixed_width_binop_type`
  range-checks it + types the result as the fixed-width type; codegen reconciles the
  literal's width via the existing `_reconcile_int_width`). Out-of-range literal =
  clean error; Int/Int mixing unchanged. Tests: `fixed_width_arith_literal` (5 ops,
  both orders, suffix local, Int/Int untouched), `errors/fixed_width_arith_literal_
  out_of_range`. Un-flags the design-77 item-8 note. Suite 858, bootstrap 17+17,
  libs 4+4. [77, 65, 53, 81]
- **CORE (marker + escape rules + with_ref) + std/example sweep — LANDED** (commit
  da64eb0). `unsafe <expr>` marks a raw-pointer op whose pointer flows INVISIBLY
  (deref/index/write, pointer arith, binding a pointer produced by a call) in a
  function whose own signature carries no `Unsafe*` type; a cast naming
  `UnsafePointer<T>` (and any op transitively inside it), a pointer field/param/arg
  are already VISIBLE (no marker). Marked domain = signature carries a raw pointer
  OR a `self`-receiver method of a struct with a raw-pointer field (field decl is
  the marker → container access methods stay marker-free; a no-`self` factory like
  Box.make shows the marker). `unsafe`-on-nothing = clean error. Grammar: `unsafe`
  just below assignment, looser than every operator; `unsafe p[0] = 5` marks the
  whole store (parser lifts off the lvalue). `Vector.with_ref`/`with_var_ref`
  (generic-R, `sync` body, non-escaping lend) REPLACE the removed `ref_at`;
  taskgroup executor migrated (returns a `__ResumeOutcome` struct out of the
  borrow). Synthesized coro code exempt by provenance. TESTS (commit follows):
  unsafe_surface_ok + errors/unsafe_{deref,write,arith,binding}_no_marker +
  unsafe_marker_on_nothing (rule rows), vector_with_ref + errors/
  with_var_ref_invalidation + vector_ref_at_removed. DOCS: spec Unsafe Code
  section rewritten (visibility rule + table; the `poke` example now marks its
  store), saw-lang skill unsafe section + ref_at gotcha, CLAUDE.md digest.
  DEVIATION (documented + defensible): the `self`-method-of-a-pointer-field-struct
  domain rule is a faithful reading of "the field decl is the visible marker" that
  keeps the sweep proportionate (container ACCESS methods marker-free, factories
  marked) — it matches the brief's item-3 list exactly (Box.make marked; Vector/
  Arc access not). Suite 867, bootstrap 17+17, libs 4+4. [81, 80, 46, 42, 29]
- **CI rider (Linux `_NSGetArgc`/`_NSGetArgv` link failure) — LANDED.** The first
  GitHub Actions run failed on ubuntu: `std/env.saw` used Apple-only crt_externs
  `_NSGetArgc`/`_NSGetArgv`, so every Linux link died with "undefined reference to
  `_NSGetArgc`". Fixed by UNIFYING (not forking per-OS): the C entry `main` is now
  declared `main(i32 argc, i8** argv)` and its codegen prologue stashes both into
  private module globals `@__saw_argc`/`@__saw_argv` at startup; two seam functions
  `__saw_get_argc()`/`__saw_get_argv()` (in `_declare_argv_runtime`) read them on
  EVERY platform. env.saw's `argc`/`arg` read those seams; the `_NSGet*` externs are
  deleted. Verified: env_simple + an args probe run correctly on macOS (argc/argv +
  argv[i] strings); `--target x86_64-unknown-linux-gnu --emit-ir` shows ZERO
  `_NSGet*` references and `main(i32, ptr)` + the argv globals. Suite 854, bootstrap
  17+17, libs 4+4 green (macOS). Remaining CI verdict awaits the next Actions run
  (Linux link). [81, 41]

## Design 80 — Member visibility (fields + methods) + std under the gate (LANDED)
- **Commit 1 (feature + std/libs/blade sweep + tests) — LANDED.** Struct FIELDS
  and extension METHODS (incl. init/static) are now private-by-default OUTSIDE
  the defining module, same modifier family as top-level (`public`/
  `public(package)`/`public(parent)` per member); same-module unrestricted.
  **Probe verdict: the hole was REAL** — on baseline `v.length = 1000` was
  accepted and a bounds-checked `v.get(500)` read OOB through safe code
  (returned garbage, exit 0). Now a clean compile error (headline lock
  `vis80_vector_length_invariant`). Mechanics: parser/AST visibility on
  StructField + Method; namespace StructSymbol.field_visibility+def_module,
  FunctionSymbol.def_module+satisfies_trait; typechecker gate at field read
  (`_check_member_access`), field WRITE (assignment lvalue in statements.py —
  the headline), memberwise struct literal (after design-66 reinterpretation),
  and method/static/init calls. Module identity keyed on SOURCE FILE so the
  merged prelude is distinguishable: std/builtin = one module `("<std>",)`,
  user code keeps its module_path — kills the prelude bypass for the ACCESS
  check only (codegen compiler-known-ness untouched). Trait-conformance methods
  exempt (satisfies_trait). SYNTHESIZED-ACCESS EXEMPTION BY PROVENANCE:
  coro-transform output (spawn/drive wrappers, synthesized main, frame
  resume/__wake_reason) carries `is_synthesized`; its member access skips the
  gate (reaches std/frame internals by construction — this cleared ALL the
  taskgroup/coro/net breakage: 66× TaskGroup.__enqueue + 66× TaskHandle.result_ptr
  were the tell). **Bypass audit (worked only via the prelude bypass before):**
  every std public method (Vector/Map/Set/String/StringBuilder/Data/Path/Arc/
  Box/Channel/Mutex/Task/TaskGroup/numeric/net/…, 231 methods annotated
  `public`), plus public error/result FIELDS that user code reads — AllocError
  (size/align), Utf8Error (offset), CommandOutput (stdout/exit_code), SlabHead
  (bump/free), Range/RangeInclusive; and cross-module fields in libs+blade —
  semver Version (major/minor/patch), toml TomlError (message/line), blade
  Dependency/Manifest.root_dir/Cli/BuildError/ParseError/LockData.manifest_hash.
  **DEVIATION (documented):** std is ONE module for its internal boundary — the
  user↔std boundary is what closes the hole; std-internal cross-file access
  stays unrestricted rather than per-file-gated (per-file surfaced 182 mostly
  public-API cross-references; the single-module choice is lower churn/risk with
  the identical security guarantee). NOTE: Saw has no struct-destructuring
  patterns, so the brief's "pattern" case reduces to enum-variant matching
  (follows enum visibility, unchanged). Tests: vis80_field_read/write/literal
  _error, vis80_method/static_private_error, vis80_public_members_ok
  (public field/method/static/init + public(package) + trait-conformance),
  vis80_same_module_ok, vis80_vector_length_invariant. Suite 851 (from 843),
  bootstrap 17+17, libs 4+4. [80, 66, 44, 52b]

## Design 77 — Generics & closures completion + accumulated riders (LANDED, subset)
**Status:** items 1 (spawn-Void), 2 (generic-bound propagation), 3 (DF-C2 closures
satisfy Copy) + its get-UAF follow-up, 4 (DF-C1 closures in frames), 7 (Global
rename), 8 (unary minus fixed-width), 9 (comparison literal coercion), 10 (tuple/
destructure across suspend) — **LANDED**. Items 5 (buried suspending method
sub-frame) and 6 (cross-module generic driven) — **RE-LEDGERED** (central
transform surgery, budget spent on item 4; rejections stay clean + anchored).
Item 11 (docs) — spec + skill limits updated below. Two pre-existing bugs FLAGGED
(not regressions): `__drive(f(move owning_arc))` double-frees the moved param
(gmalloc-only; item 4 note); a bare-literal fixed-width LOCAL stores at platform
width (item 8 note). Suite 843 (from 825 baseline), bootstrap 17+17, libs 4+4,
zero xfails throughout.
- **Item 7 RIDER (rename `Global` -> `GlobalAllocator`) — LANDED.** TRUE rename
  (not a `type` alias — that would shatter allocator identity). Swept all `.saw`
  (std alloc.saw struct + `Allocator` conformance, every `= GlobalAllocator`
  default and `GlobalAllocator()` construction across vector/map/set/box/arc/
  channel/mutex/task/taskgroup/stringbuilder/data/net, blade/manifest, libs,
  examples) and the compiler's hardcoded `struct_name="Global"` sites
  (existentials/results/generics/expressions/statements) -> `"GlobalAllocator"`.
  Mangled names shift `$Global` -> `$GlobalAllocator` uniformly (nothing external
  links them; registration + lookup agree since the mangler keys on the struct
  name). `Global` no longer resolves (clean `undefined function` /
  does-not-conform error). Spec + saw-lang skill updated (CLAUDE.md on disk
  carries no `Global` mention). Test `errors/global_renamed_unknown`. Suite 835,
  bootstrap 17+17, libs 4+4. Standing policy oracle: whole suite green.
- **Item 8 RIDER (unary minus on fixed-width ints) — LANDED.** `_check_unary_op`
  now accepts signed fixed-width `Int8`..`Int64` (was `Int`/`Float` only);
  unsigned negation is a clean error ("an unsigned integer has no negation").
  Codegen negates via the existing checked subtract at the operand's WIDTH, so
  `-Int8.min` panics ("integer overflow") like `Int`. A negated integer LITERAL
  const-folds to the negated constant at width (`-128i8` = Int8.min directly,
  not a runtime negation of the bit pattern), and the typechecker range-checks
  the FOLDED value (`-200i8` is a clean error). Un-dodged the platform-Int
  `0 - 1` sites (map/taskgroup) and `0.0 - mantissa` (string) to `-1`/`-mantissa`.
  Tests: `unary_minus_fixed_width`, `unary_minus_int8_min_panics`,
  `errors/unary_minus_unsigned`, `errors/unary_minus_literal_out_of_range`.
  - **FIXED (design 80 run, rider):** a fixed-width int LOCAL from a BARE literal
    is now NARROWED to its annotated storage width. `_generate_let_statement`
    coerces the RHS int value to the annotation's LLVM width before the alloca
    (trunc/sext/zext by signedness); the typechecker already range-checked the
    literal, so it is value-preserving. `-a` on a bare-literal Int32.min local now
    overflow-panics at i32; a wire-format struct built from narrowed locals
    round-trips. Tests fixed_width_let_narrow, fixed_width_let_negate_panic. STILL
    FLAGGED (separate pre-existing): arithmetic mixing a fixed-width local with a
    bare literal (`b + 0` for `b: Int32`) ICEs "i32 != i64" — reproduces with a
    suffix local too; belongs with a fixed-width arithmetic-coercion pass. [53, 65, 80]
  Suite 839, bootstrap 17+17, libs 4+4. [59, 76, 53]
- **Item 9 RIDER (comparison-position literal coercion) — LANDED.** Codegen
  already coerced a bare literal to the other comparison operand's fixed-width
  type, but WITHOUT a range check — `fd < 200` for `fd: Int8` silently compared
  against the wrapped value -56. The comparison typecheck now runs the design-65
  `_check_fixed_width_literal` range check on both operands (a no-op unless one
  side is a bare literal and the other a fixed-width int), so an out-of-range
  literal is a clean error. Un-dodged the seven `(0 as Int32)` comparison casts in
  std/net.saw (`fd < 0`, `!= 0`, `>= 0`, `== 0`). Tests
  `comparison_literal_coercion`, `errors/comparison_literal_out_of_range`. Suite
  841, bootstrap 17+17, libs 4+4. [65, 76]
- **Item 10 RIDER (tuple / destructuring across a suspend) — LANDED.** Two frame
  opt-encoding gaps from design 76: (a) a TUPLE local held across a suspend ICE'd
  ("cannot store {i64,i64} to {i1,{i64,i64}}*") — already fixed incidentally by
  item 4's `_is_optional_type` optional-wrap change (a tuple is a
  LiteralStructType the old "not a struct" guard skipped); locked by
  `coro_tuple_across_suspend`. (b) `let (a,b) = f()` destructuring across a
  suspend DROPPED the bindings ("undefined variable a") — the transform's
  `_collect_frame_locals` only saw plain `let name`, not `DestructuringLet`.
  Now each tuple-pattern leaf is collected as a frame local (typed from the
  source tuple's position) and `let (a,b)=v` lowers to a fresh temp +
  `self.a = __t.0; self.b = __t.1` (auto-wrapping opt-encoded fields). Wildcards,
  nested patterns, and direct-tuple sources all work. Test
  `coro_destructure_across_suspend`. Suite 843, bootstrap 17+17, libs 4+4. [44, 62, 76]
- **Item 5 (A5-rest shape 1: buried suspending method sub-frame) — RE-LEDGERED
  (per the brief's escape hatch; rejection stays clean + anchored).** The FEATURE
  (embed a nested suspending METHOD call `let r = c.step()` as a sub-frame — the
  Part-0b method twin) still needs the design-74 triad: (a) make the phase-1
  frame-prep a FIXPOINT that discovers method callees while preparing (today
  `_collect_calls`/`closure` is a fixed set of free-function names; method
  sub-frames aren't in `fbs`), (b) receiver addressing — `__recv = (&var
  self.recv) as UnsafePointer<Struct>` into the CALLER frame's field (only a
  simple frame-local receiver is addressable; `foo().m()` / `self.f.m()` need
  spilling), (c) build the method frame + thread it into `fbs` so
  `_build_sub_frame`/`_emit_nested_call` (which already accept a `recv_value`)
  drive it. `_build_frame_init` already supports a method `__recv`. Bounded but
  it touches the central transform flow — and item 4's closure-in-frame surgery
  (this same territory) surfaced several subtle exactly-once/UAF hazards that took
  the bulk of this brief's budget, so bundling shape 1 too risks the 834-test bar.
  Workaround is exact and the rejection names it (drive the method directly, or
  wrap in a nested free fn). [74, 44, 45]
- **Item 6 (A5-rest shape 4: cross-module generic driven) — RE-LEDGERED (per the
  escape hatch; rejection stays clean + anchored).** `_pristine_generics` /
  `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and
  the nested/driven generic call is rejected (anchored) by `_classify_call`.
  Lifting needs: (a) snapshot imported-module generic templates into the pristine
  maps (keyed to avoid cross-module name clashes), (b) design-68 canonicalization
  — the mangled instantiation key computed in the transform must agree
  byte-for-byte with codegen's cross-module monomorphization symbol, or the
  frame's callee and codegen's mono double-define / mismatch. The
  mangling-agreement surface is exactly design-68 territory and risky against
  bootstrap (blade is generic- and multi-module-heavy). Deferred with the same
  budget reasoning as shape 1. [74, 68]
- **Item 1 (spawn-Void ICE) — LANDED.** `spawn { void_body }` ICE'd building the
  `{i8*, i8*, void}` control block (a `void` struct field is illegal LLVM). The
  result slot becomes a 1-byte placeholder for a Void body (never stored/read in
  the trampoline); `UnsafePointer<Void>` now lowers to `i8*` (C `void*`) and
  `sizeof<Void>()` folds to 0, so the GENERIC `Task<Void>.join`/`deinit` stdlib
  paths (result cast/load/dealloc-size) monomorphize cleanly. Both explicit-join
  and drop-joins-it exercised. Test `spawn_void_body`. Suite 826, bootstrap 17+17,
  libs 4+4. [75]
- **Item 2 (generic-bound propagation) — LANDED.** A generic forwarding its own
  bounded type param to another generic's bound (`inner<T>(w)` inside
  `middle<T: Seed>`) errored "type `T` does not implement trait `Seed`". Fix:
  the general-trait bound check in `_check_generic_call` now routes an ABSTRACT
  type-param argument through `_bound_satisfied` (bounds-environment lookup —
  satisfied iff the enclosing signature declares the bound), matching the
  existing Send/Sync/Equatable handling. Codegen twin: a generic call inside a
  generic body substitutes its type args through the monomorphization context
  before instantiating (else it recursed over the abstract `T`). Negative case
  (forward without declaring the bound) still a clean anchored error. Tests
  `generic_bound_propagation`, `errors/generic_bound_propagation_unmet`. Note:
  un-dodging design-74 shape-3 tests to forward a type param into the coro
  promotion path is left to items 5/6 (that combines with the promotion surface,
  not the standalone bound check fixed here). Suite 828, bootstrap 17+17, libs
  4+4. [74]
- **Item 3 (DF-C2: closures satisfy `Copy`) — LANDED.** An escaping closure is
  ImplicitCopy (design 73) and now satisfies the umbrella `Copy` bound
  (`type_satisfies_copy_bound` accepts `TypeKind.FUNCTION`), so
  `Vector<() -> Int>` is ExplicitCopy and its `.copy()`/`.get()` work. Three
  wiring fixes to make it BALANCED (the naive enable exit-133'd): (a) codegen
  `.copy()` on a closure receiver emits the env retain (`_emit_closure_env_retain`)
  instead of a bitwise alias; (b) the ROOT cause of the leak/double-free — the
  `escaping` bit is not part of the mangling and was lost when a container's
  closure type arg was reconstructed from the mangled key, so `_needs_cleanup`
  and the Copy-bound predicate (both gate on `func_is_escaping`) treated the
  element as non-owning. `_ensure_monomorphized_struct` now re-marks a stored
  closure type arg escaping (`_mark_stored_closure_escaping`, recursing through
  Optional/array/tuple), which is safe (a function type reaching a container
  type-param slot is always a stored value, never a borrowed param). Exact-count
  Arc-capture probe: deinit runs exactly ONCE through copy+get. Tests
  `closure_vector_copy_get`, `closure_vector_deinit_once`,
  `closure_satisfies_copy_bound`. Suite 831, bootstrap 17+17, libs 4+4. [73, 54]
- **Item 3 follow-up (get use-after-free) — LANDED.** The item-3 commit had a
  latent flake: `Vector<() -> Int>.get` returned a closure element WITHOUT
  retaining its env, because `_transfer_needs_copy`'s copy-with-retain branch
  only covered ImplicitCopy STRUCT/ENUM/OPTIONAL — a closure (no conformance
  name, so `_get_cleanup_behavior` = "none") fell through to bitwise. The
  read-out copy's teardown released an env it never retained: a use-after-free
  that intermittently crashed (exit 133 under load; deterministic under
  libgmalloc). Fix: `_transfer_needs_copy` retains an escaping-closure element
  read out of a container slot (ArrayIndex/MemberAccess/TupleIndex), mirroring
  the design-65 aggregate copy-with-retain; a bare Identifier closure
  (move/borrow-lend) is untouched. Verified deterministic-clean under
  libgmalloc + MallocScribble (20x). Suite 831, bootstrap 17+17, libs 4+4. [73]
- **Item 4 (DF-C1: closures in coroutine frames) — LANDED.** A closure created in
  a driven body is now supported: (1) closure-typed frame field via a new
  `opt_closure` encoding (Optional-wrapped, drop-flag = None/Some, forced `sync`
  since a stored closure cannot be driven; frame re-registration no longer trips
  "redundant escaping" — `_clear_escaping` clears the bit on the field type so
  re-stamping is clean); (2) a CALL `f(args)` on a frame closure local rewrites to
  an indirect field call `self.f(args)` (typechecker force-unwraps the opt field
  on a `__Frame_*` struct; codegen extracts the inner closure); (3) captured frame
  locals are MATERIALIZED as real locals before the closure (`let x = self.x!.copy()`
  + a `move` capture) so the closure captures by value — crucially `move`, not a
  persistent function-local, because a resume state machine would re-drop an owning
  local on every re-entry. Codegen `MemberAccess`-to-optional wrap now uses
  `_is_optional_type` so a struct/closure inner wraps to Some. Tests
  `coro_closure_local_call`, `coro_closure_deinit_once` (exact deinit-once,
  gmalloc-clean), `coro_closure_taskgroup` (spawned frames own closures). All 3
  verified clean under libgmalloc. Suite 834, bootstrap 17+17, libs 4+4. [73, 74, 44, 52b]
  - **FIXED (design 80 run, rider): `__drive(f(move owning_arc))` no longer
    double-frees the moved param.** The `__drive_<f>`/`__spawn_<f>` wrapper now
    `move`s each non-reference param into the frame (`_frame_param_arg`), so the
    frame is the sole owner (dropped once at teardown) and the wrapper param's drop
    flag is cleared. Exact-count lock coro_moved_arc_param_deinit_once (3 refs, no
    UB); single-ref case verified clean under libgmalloc. Original note follows.
  - **FOUND (pre-existing, FLAGGED): `__drive(f(move owning_arc))` double-frees the
    moved param.** A driven function taking an owning ImplicitCopy value (Arc) as a
    param, moved in at the drive site, DOUBLE-DROPS it: the synthesized
    `__drive_<f>` wrapper builds the frame from the param `Identifier` WITHOUT
    retaining into the opt-encoded field (`_needs_copy_for_struct_init` sees the
    field type `Arc?` = Optional -> `_get_cleanup_behavior` = "none", so no retain),
    yet the param binding keeps its drop flag AND the frame drops its field. Benign
    under the normal/scribble allocator (the 2nd Arc deinit reads a freed-but-mapped
    strong word and no-ops), but a real read-after-free (deterministic SIGSEGV under
    libgmalloc). Repro: `func run(a: Arc<Res>){...__suspend()...}; __drive(run(move a))`
    — NO closure needed. Reproduces at HEAD (pre-item-77-4). An owning value created
    as a frame LOCAL (not a moved param) is clean. Fix belongs with the frame-init
    retain path (opt-encoded ImplicitCopy field construction must retain, or the
    driver must move-clear the param). Deferred from item 4 (orthogonal to closures;
    the deinit-once test uses a frame-local Arc to stay clean). [44, 52b]

## Design 76 — A4 IO reactor + A6 extern-blocking + A3 remainder (IN PROGRESS)
- **Commit 1 (A4 reactor + std.net + A3 io-cancel; ST + entry executor):** A
  process-global **kqueue (macOS) / epoll (Linux)** reactor (compiler seams in
  codegen/core.py, `_declare_io_runtime`): a single lazily-created, race-safe
  (atomic cmpxchg) reactor fd; `saw_reactor_register(fd, write)` arms ONE-SHOT
  read/write interest; `saw_reactor_poll(timeout_ms)` blocks in kevent/epoll_wait
  (< 0 = forever) and returns the ready count — the kernel owns the interest set,
  so register/poll are each ONE syscall (why kqueue/epoll beats poll(2) for a
  global reactor). OS-divergent socket bits stay in shims (`saw_set_nonblocking`,
  `saw_errno_would_block`, `saw_sin_set_family`); hosted-only (freestanding: extern
  decls, net never loaded). **`io_wait(fd, write)`** is a new suspend INTRINSIC
  (like `yield_now`): the coro transform lowers it to `saw_reactor_register` +
  suspend with a NEGATIVE (io-park) wake reason; codegen fallback (outside a frame)
  is register + blocking poll. The ST group executor (`__run_all_st`) + the entry
  executor gained an io phase: when nothing is runnable, poll the reactor with the
  earliest sleep deadline as the timeout (never busy-wait, never block while a
  frame is runnable), wake ALL io-parked tasks on return (coarse level-triggered
  retry — a still-not-ready task re-registers via oneshot), advance sleepers only
  when the poll TIMED OUT (events==0). **std/net.saw**: minimal nonblocking TCP as
  the channel-style idiom (NON-suspending `tcp_try_read`/`tcp_try_write`/
  `tcp_try_accept` + `io_wait` in the caller task body — a suspending std free fn
  CANNOT embed as a sub-frame since the transform is entry-module-only, same reason
  `Channel.receive()` is inline-lowered); `tcp_listen`/`tcp_local_port`/
  `tcp_connect_start`/`tcp_connect_check`/`tcp_socketpair`/`tcp_close`/
  `net_buffer`/`net_bytes_to_string`. Zero per-call heap in the socket paths: a
  typed `SockAddrIn` stack struct (design-58 natural layout) + `(&sa) as
  UnsafePointer` (design-42), htons/ntohs in Saw. A3: cancellation observed at the
  io suspension point via the cancel-check-before-`io_wait` idiom (mirrors the
  channel cancellation-aware receive). Tests (loopback/socketpair only,
  deterministic on counts/contents, time-bounded): `net_socketpair_echo`,
  `net_loopback_echo` (listen/accept/connect/read/write), `net_io_sleep_interleave`
  (never-block: sleeper honored while an fd is idle + io wake), `net_io_main_entry`
  (entry-executor reactor path), `net_io_cancel` (A3 + deinit oracle). Suite 823,
  bootstrap 17+17, libs 4+4.
  - **FOUND (pre-existing, flagged): a TUPLE local held across a suspend ICEs**
    ("cannot store {i64,i64} to {i1,{i64,i64}}*") — the coro frame opt-encodes the
    tuple slot but the store site doesn't wrap it; reproduces with plain
    `yield_now` (NO io). `let (a,b) = f()` DESTRUCTURING across a suspend also
    drops bindings. Orthogonal to design 76 (frame opt-encoding of non-POD-but-
    cleanup-free locals). Worked around in tests (keep only `Int` across the
    suspend; confine tuples to non-suspending helpers). Fix belongs with the coro
    frame-encoding work. [44, 76]
  - **DEFERRED (A4 remainder, re-ledgered): first-class inline-lowered
    `tcp_read`/`tcp_accept`/`tcp_write`/`tcp_connect`** (receive()-style, so the
    park loop is not hand-written in the task body). The transform being
    entry-module-only forces the channel-idiom shape today; the ergonomic lift is a
    `recv_by_id`-style recognition + `_emit_io_call` inline lowering. [62, 76]
  - **DEFERRED (A3 remainder): waking an ALREADY-io-parked task on cancel.** A task
    parked in `io_wait` on a permanently-idle fd, cancelled by a peer, won't observe
    `cancelled()` until the reactor poll returns (needs a self-pipe/eventfd wake).
    Same liveness class as the design's "join on a task that never observes
    cancellation blocks"; the landed model observes cancel at the check BEFORE
    parking. [18, 76]
    - **CLOSED** by design 102 item 2 (reactor self-wake pipe + `__is_cancelled()`
      precise wake + pre-poll cancelled scan + cancel propagation into sub-frames).
- **Commit 3 (A6 honest subset: `extern blocking` sync-reject + freestanding
  reject):** the A6 FRONT-END was already wired (parse `extern "C" { blocking func
  ... }`, `is_blocking` on the AST, blocking-extern as an effect suspension
  source). This commit closes the two type-system halves: (1) a blocking-extern
  call in a `sync` context is rejected by the effect checker, anchored, naming the
  extern + suspension path (locked by `errors/blocking_extern_sync_reject`); (2)
  declaring an `extern blocking func` in the FREESTANDING profile is a clean
  registration-time error (no hosted pool). Suite 825, bootstrap 17+17, libs 4+4.
  - **CLOSED by design 103** (thread-per-call offload + coro lowering; see the design
    103 entry). The worked-out design below is what landed (thread-per-call v1 in
    place of a pool; `__blk_start` codegen intrinsic + pre-frame-builder classify).
  - **DEFERRED (A6 runtime offload — re-ledgered with the worked-out design):** the
    hosted pool + coro lowering that makes a blocking call actually RUN in a task.
    Today a blocking call inside a driven/spawned body is REJECTED (the synthesized
    `resume` is `sync`, so the blocking suspension source trips the sync check — an
    honest rejection, not a miscompile, though the message points at
    `__Frame_*.resume`). Design (reuses ALL the A4 infra): C shims
    `saw_offload_start(fnptr, arg) -> job` / `saw_offload_done(job)` /
    `saw_offload_pipe_fd(job)` / `saw_offload_take(job)` — start spawns a
    thread-per-call that runs the extern, stores the result, and writes a byte to
    the job's pipe; the call site desugars (BEFORE typecheck, so the frame builder
    sees the new locals) to `let j = __blk_start(slow(arg)); while __blk_done(j)==0
    { io_wait(__blk_fd(j), 0) }; let r = __blk_take(j)`. The two frictions that make
    it non-trivial: (a) function-address is NOT expressible in Saw (`slow as Int`
    errors), so `__blk_start` must be a CODEGEN intrinsic that resolves the extern's
    ir.Function and bitcasts it to i64; (b) the desugar must run pre-typecheck (or
    register `__job` with the frame builder) so the offload locals are
    frame-resident. v1 restriction: blocking externs typed `(Int) -> Int` (the
    offload thunk is `i64(*)(i64)`); multi-arg is future. [18, 22, 76]
- **Commit 2 (MT reactor integration + std.net named constants):** the design-75
  multi-threaded worker (`__tg_worker`) gained the io phase. CHOICE (reported):
  **poll on an idle worker with a BOUNDED timeout** (earliest sleep deadline, else
  a 50 ms cap) — bounded because with EV_ONESHOT + concurrent pollers only one
  worker receives each event, so a worker that missed it must retry rather than
  block forever (no lost-wakeup hang). The scan tracks io-parked (`remaining < 0`)
  separately from sleepers; when nothing is runnable and no peer is resuming, an
  idle worker polls the reactor OUTSIDE the lock, then (idempotently) wakes ALL
  io-parked tasks and advances sleepers only if the poll timed out. Redundant
  concurrent polls are harmless (wake-all is idempotent); a dedicated single poller
  thread is a future refinement. NOTE: the Send-on-frames gate poisons
  `UnsafePointer`, so an MT-spawned frame cannot hold a read buffer across a
  suspension — MT io parks on write-readiness (Int-only frame). std.net magic
  numbers are now named module statics (`AF_INET`/`SOCK_STREAM`/`WOULD_BLOCK`/
  `LOOPBACK_BE`/...); std-module statics are NOT visible cross-module (a known
  export gap), so the `io_wait` direction stays a literal 0/1 in user code. Test:
  `net_threads_io` (`TaskGroup(threads: 2)`, two io-parked frames woken; stable
  25x). Suite 824, bootstrap 17+17, libs 4+4.

## Design 75 — A2: multi-threaded work-stealing executor + Send-on-frames (LANDED)
- **Commit 1 (surface + Send-on-frames gate; execution still single-threaded):**
  `TaskGroup(threads: N)` labeled init landed (a second `init(threads: Int)`; the
  default `TaskGroup()` and `threads: 1` stay the byte-identical single-threaded
  engine — `workers` field clamps to >=1). The Send-on-frames gate: a `let/var
  group = TaskGroup(threads: ...)` binding is flagged `is_mt_group` in the
  typechecker (`_check_let_statement` via `_is_multithreaded_taskgroup_init`,
  handles the `StructInit [resolved: init(threads)]` form); `group.spawn(f(...))`
  into such a binding records `f` in `typechecker._mt_spawn_roots`; the coroutine
  transform (`_check_spawn_frame_send`) then walks the spawn root frame's params +
  across-suspend locals + embedded callee sub-frames and rejects the FIRST non-Send
  value, naming it + its type, anchored at the function (design 74 A8). Reuses the
  same structural `namespace.is_send` as the 21b `spawn { }` capture audit
  (`UnsafePointer`/bare `Vector` poison; Int/Bool/Float/String/Arc/Mutex/Channel
  pass). Single-threaded groups skip the gate entirely. DEVIATION (documented):
  mt-ness is tracked on the group's local binding, so a `TaskGroup(threads:)`
  spawned into DIRECTLY is gated; passing the group through an opaque helper before
  spawning is not yet traced (spawn directly for the gate — future interprocedural
  lift). Tests: `taskgroup_threads_send_accept` (Int/String/Channel accepted, sum
  oracle), `errors/taskgroup_threads_nonsend_reject` (Vector param named). Suite
  813, bootstrap 17+17, libs 4+4.
- **Commit 2 (the multi-threaded fork-join executor):** `TaskGroup(threads: N)`
  with N>=2 now really runs on N OS threads. CHOICE (reported): the sanctioned
  simpler shape — ONE mutex-protected SHARED run queue (injector) drained by N
  workers, NOT per-worker lock-free deques (simplicity/soundness over throughput
  v1). Model = FORK-JOIN: a drain is triggered lazily by `join()`/Deinit (via
  `__run_all` -> `__drain_mt` when workers>=2 && lock present), spawns N `Task<Int>`
  workers through the 21b engine (each running the free fn `__tg_worker(addr: Int)`;
  the group's own address crosses the `spawn` boundary as a Send `Int`), then joins
  them all — pthread_join is a full barrier making every `__result` visible before
  `join()` force-unwraps. Each worker LOCKS, claims the first runnable (not-done,
  not-active, remaining==0) frame by setting an `active[i]` flag, UNLOCKS, calls
  `resume()` outside the lock, then re-locks to record Pending(remaining=wake) /
  Done. D6 confinement holds: `active[i]` guarantees one worker per frame; `tasks`
  is read-only during a drain (enqueue is main-thread-only, main is blocked joining
  workers, so the queue never resizes) — only done/remaining/active are mutated,
  always under the lock; frames live at stable heap addresses inside their boxes.
  Sleep: when no frame is runnable and none active, ONE worker advances the clock by
  the earliest deadline UNDER the lock and subtracts it from all sleepers (shared
  timer, no per-worker wheel); when a peer is mid-resume, free workers spin+nap 1ms
  (no cond var -> no lost-wakeup class). Cancellation across tasks:
  `TaskHandle.cancel_addr() -> Int` hands the `__cancel` word's address (Send) to a
  canceller task, which sets it; the victim observes via `cancelled()` (set-once
  monotonic byte -> race-free, eventually consistent). The default `TaskGroup()` and
  `threads: 1` still route to `__run_all_st` (the byte-identical pre-75 loop, no
  threads/lock). Send gate extended to the spawn root's RETURN type (it crosses
  worker->main via join). Battery (all deterministic on counts/sums, time-bounded,
  each verified stable 30-50x): `taskgroup_threads_parallel_sum` (100 tasks/4
  workers, sum 4950 — stress), `_producer_consumer` (channel receive across
  workers), `_sleep` (cross-worker earliest-deadline), `_cancel` (cancel from
  another task), `_deinit_once` (result dropped exactly once under stealing, static
  atomic count = 6). Suite 818, bootstrap 17+17, libs 4+4, -O0 spot-checked.
- **FOUND (pre-existing, flagged): `spawn { void_body }` ICEs.** A 21b `spawn { }`
  whose closure returns `Void` builds a task control block `{i8*, i8*, void}` — an
  invalid LLVM struct ("void type only allowed for function results"). Worked
  around in the executor (worker bodies return `Int`); a proper fix is to omit the
  result slot for a Void spawn body. [21b, 75]
  - **CLOSED** — 21b `spawn { void }` fixed by design 77 item 1; the cooperative
    `group.spawn(void)` + the executor return-Int workaround closed by design 102 item 1.

## Design 74 — A5-rest: finish effect-polymorphism shapes + A8 anchors (IN PROGRESS)
- **Commit 1 (A8 — diagnostic anchoring):** A coroutine-transform rejection
  (`CoroTransformError`) now anchors at the user's `file:line:col` with a source
  snippet through the shared `ErrorReporter`, exactly like a type error — it was
  a bare message pointing nowhere. `CoroTransformError` carries `source_file`;
  `_FrameBuilder` stashes `self.src_file` from its function; sawc.py surfaces the
  rejection via `reporter.error(...)` (falling back to the entry file for a
  single-file program). Locked by `examples/errors/coro_reject_anchored.saw`
  (asserts the `file:line:col` anchor on a buried-suspend rejection). Suite 808,
  bootstrap 17+17, libs 4+4. [74, 69]
- **Commit 2 (shape 2 — driven method on a GENERIC struct):** `__drive(b.run())`
  for `b: Holder<Int>` now works. The typechecker monomorphizes the method over
  the STRUCT's type params (T->Int): pristine generic-struct-extension methods are
  snapshotted (`_pristine_generic_struct_methods`), the drive site queues a
  clone+substitute+re-check (deferred to `_process_effect_monos` so it never
  clobbers the mid-body scope), and records the concrete driven method carrying
  the concrete receiver SawType (`Holder<Int>`). The coro transform reads that
  table, builds the frame with `__recv: UnsafePointer<Holder<Int>>` (new
  `recv_saw_type` param on `_FrameBuilder`), and `_rewrite_drive_sites` casts to
  the type-arg-preserving pointer. Two instantiations coexist (Int + Bool). A
  general fix fell out: member access on a concrete instantiation of a generic
  struct whose `struct_info` is the generic symbol now substitutes the field type
  by the receiver's type args (`self.value: T` -> `Int`) — normal instantiations
  keep their monomorphized symbol and skip it. Combined struct-generic AND
  method-generic driven methods stay a clean, anchored rejection (still A5-rest).
  Tests: `coro_generic_struct_method` (both instantiations),
  `errors/coro_generic_struct_and_method_generic_unsupported`. Suite 809,
  bootstrap 17+17, libs 4+4. [74, 70]
- **Commit 3 (shape 3 — nested suspending generic calls):** A driven body can now
  make NESTED suspending generic calls (`let a = leaf<Slow>(...)`). A new
  transform pre-pass `_promote_nested_generic_calls` runs after the effect fixpoint
  (so per-instantiation `.suspends` is known): it walks each driven body (and,
  transitively, spliced instantiation bodies) for a drivable-position generic call
  whose instantiation suspends, splices the concrete instantiation via a new
  typechecker helper `_splice_fn_mono` (clone+substitute+register+re-check under
  the stashed entry-module namespace `_entry_module_ns`, so locals get resolved
  types), rewrites the call site to the mangled symbol, and seeds it into the
  driven closure. The existing Part-0b sub-frame embedding then handles it. The
  closure walk now SKIPS a template reached via an effect edge (its suspending
  instantiations were promoted + seeded); an un-promotable nested generic call
  (cross-module = shape 4) keeps its generic call and is rejected — with a
  workaround + user-anchored line — by `_classify_call`. Multiple instantiations of
  one generic coexist; non-suspending nested generic calls are left for codegen.
  Tests: `coro_nested_generic_call` (two instantiations + a non-suspending generic
  left alone), `coro_nested_generic_deep` (two-deep nesting). Suite 810,
  bootstrap 17+17, libs 4+4. [74, 44]
- **DISCOVERED (pre-existing, NOT shape 3): generic-bound propagation gap.** A
  generic fn forwarding its own type param to another generic (`func middle<T:
  Seed>(w: T) { inner<T>(w) }`) errors "type `T` does not implement trait `Seed`"
  even though the bound is declared — reproduces with NO driving (orthogonal to
  coroutines; a typechecker generics issue). Nested shape-3 tests use concrete type
  args at each level to avoid it. Fix is disproportionate to design 74 — flagged
  for a generics brief. [74]
- **Commit 4 (shape 1 rejection + A8 for methods + docs):** A BURIED suspending
  METHOD call in a driven body (`let r = c.step()`, `Counter.step` suspends) is now
  a CLEAN, user-anchored rejection at the exact call site naming the workaround
  (`__drive(recv.step())` directly, or wrap in a nested free fn) — it previously
  lowered in place and tripped a confusing sync-violation on the synthesized
  `__Frame_*.resume`. The transform builds a (struct, method) suspend set from the
  effect nodes and `_collect_calls` detects the buried call. Docs: spec concurrency
  limits + saw-lang skill limits updated for shapes 2/3 landed and shapes 1/4 (+
  combined struct-and-method-generic) remaining. Test:
  `errors/coro_buried_suspending_method` (asserts message + `file:line:col`). [74]

## Design 74 — RE-LEDGERED remainder (attempted, deferred with analysis)
- **Shape 1 FEATURE (method sub-frame embedding) — DEFERRED.** The rejection is now
  clean + anchored (commit 4). The FEATURE (embed a nested suspending method call
  as a sub-frame, the Part-0b method twin) needs: (a) making the phase-1 frame-prep
  a FIXPOINT that discovers method callees while preparing (today `closure` is a
  fixed set of free-function names; method sub-frames aren't in `fbs`), (b)
  receiver addressing — `__recv = (&var self.recv) as UnsafePointer<Struct>` into
  the CALLER frame's field for the receiver (only a simple frame-local-identifier
  receiver is addressable; `foo().m()` / `self.f.m()` need spilling), (c) building
  the method frame + threading it into `fbs` so `_build_sub_frame`/`_emit_nested_
  call` (which already accept a `recv_value`, see `_build_frame_init`) drive it.
  `_build_frame_init` already supports a method `__recv`; the missing piece is the
  discovery/prep fixpoint + receiver addressing. Bounded but touches the central
  transform flow — deferred to keep the 810-test bar safe; workaround is exact and
  the rejection names it. [74, 44, 45]
- **Shape 4 (cross-module generic driven templates) — DEFERRED.** `_pristine_
  generics` / `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and the
  nested/driven generic call is rejected (anchored) by `_classify_call`. Lifting
  needs: (a) snapshot imported-module generic templates into the pristine maps
  (keyed to avoid cross-module name clashes), (b) design-68 canonicalization — the
  mangled instantiation key computed in the transform must agree byte-for-byte with
  codegen's cross-module monomorphization symbol, or the frame's callee and
  codegen's mono double-define / mismatch. Deferred: the mangling-agreement surface
  is exactly design-68 territory and risky against bootstrap (blade is generic- and
  multi-module-heavy). Rejection stands with a workaround. [74, 68]
- **Rider DF-C1 (closures inside driven/suspending frames) — DEFERRED (attempted).**
  Confirmed both shapes still error on this tree (as design 73 flagged): a closure
  local CALLED in a driven body errors "undefined function `f`" (the resume method
  doesn't rewrite `f(n)` on a frame-local closure to an indirect `self.f(n)` call),
  and a closure HELD across a suspend errors "redundant `escaping`" (the frame
  struct field for a closure trips the typechecker's "closure types outside
  parameter position are always escaping" check). The fix is a genuine multi-part
  feature: (1) type the closure frame field without tripping the escaping check,
  (2) rewrite a frame-local-closure CALL to an indirect closure call on `self.f`,
  (3) closure env retain/release exactly-once across the suspend + at frame drop.
  This is closure-in-frame representation surgery in both the typechecker and the
  transform — disproportionate to bundle safely here; re-ledgered per the rider's
  own escape clause. Blocks a TaskGroup frame that OWNS a closure. [73, 74, 44, 52b]
- **Rider DF-C2 (`Vector<closure>` satisfies the generic `Copy` bound) — DEFERRED.**
  Unchanged from design 73: the container element-copy path must route through the
  closure-env retain (a naive enable crashed exit 133). Independent of the coroutine
  transform work in this brief; belongs with the container-Copy-glue work. [73, 54]

## Design 72 — Small fixes: L12/M1, L9, erased-error downcasting (LANDED)
- **Commit 1 (L12/M1 — fixed-array builtins):** Fixed arrays `[T; N]` gained two
  builtin members and only these two: `.len()` (folds to the compile-time
  constant N as `Int`) and `.swap(i, j)` (the M1 escape hatch — bounds-checked
  in-place element swap, mirroring `Vector.swap`; requires a `var` receiver). The
  typechecker intercepts array-typed method calls (`_check_array_method`) before
  the old "non-struct type" error: `len`/`swap` typed + tagged, anything else a
  clean "fixed array has no method X; only .len()/.swap are available, user
  extensions on array types are not supported" error. Constant `swap` index OOB is
  a compile error (mirrors `a[const]`); dynamic index gets the always-on runtime
  bounds check. Parser: `extension [Int; N]` now emits "extension methods on array
  types are not supported" instead of the generic "Expected type name". Codegen
  `_generate_array_builtin`: `len` -> const; `swap` addresses the array in place
  via `_get_lvalue_pointer` + GEP, loads/stores the two slots (no element copy).
  Spec fixed-array section updated; `.len()` de-illustrativized. Tests:
  `array_len_builtin`, `array_swap_builtin`, `array_swap_immutable_error`,
  `array_no_extension_error`, `array_unknown_method_error`,
  `array_swap_const_oob_error`, `array_swap_dynamic_oob_panic`. Suite 796,
  bootstrap 17+17, libs 4+4. [72]
- **Commit 2 (L9 — Equatable over Optional/array members):** The synthesis
  widening was ALREADY landed (commit e60d189: `is_equatable` holds for `T?` iff
  `T` is and `[T; N]` iff its element is; codegen `_emit_optional_equals` /
  `_emit_array_equals` wired into the recursive `_emit_equals`, so struct-field,
  tuple, and direct comparisons all reach them; tests
  equatable_optional_field/_direct/_string_synth/_array_field). Design 72 closes
  the remaining brief case — an enum whose payload is an Optional — with
  `equatable_enum_optional_payload` (`Filled(value: Int?)`: Some==Some,
  Some!=Some-diff, None==None, None vs Some). Suite 797. [72]
- **Commit 3 (erased-error downcasting via type-ids):** Every vtable gains a
  `type_id` HEADER slot (layout now `[dtor, size, align, type_id, methods…]`;
  dispatch base 3->4). Type-id scheme: a monotonic counter memoized by MANGLED
  NAME (`_type_id_for`), so the id the vtable bakes in matches the id `is`/`take`
  compute for the same concrete type in this module (simplest stable scheme; no
  reflection surface). Builtins on `Box<any Trait>` (explicit type arg, no
  inference): `b.is<T>() -> Bool` (loads/compares the vtable type-id; a borrow)
  and `b.take<T>() -> T?` — CONSUMES the box: on an id hit it moves the payload
  out and frees the shell WITHOUT the dtor, `Some(T)`; on a miss it runs the full
  box drop, `None`. take-on-miss CHOICE: consumes UNCONDITIONALLY (leave-intact
  fights the move checkpoint), so `is<T>()` first is the branch-without-consume
  path — the typechecker marks the receiver moved, codegen clears its drop flag.
  Deinit is exactly-once on both paths (hit: at the moved-out value's scope; miss:
  in take). T must be a concrete conforming type (clean error otherwise). Codegen
  drop refactored into `_erased_run_dtor` + `_erased_dealloc_shell`. Catch-side
  match-on-concrete sugar OUT (future). Tests: erased_downcast_is_take,
  _deinit_once (hit+miss balance), _error_retry (Box<any Error> from an erased
  Result — the motivated case), _generic (downcast in a monomorphized body),
  _nonconforming_error, _use_after_take_error. Spec existentials + error sections
  + saw-lang skill updated. Suite 803, bootstrap 17+17, libs 4+4. [72, 51, 56]

## Design 73 — Closures become ImplicitCopy (refcounted env) (LANDED)
- **Commit 1 (core + tests):** An escaping closure's heap env now leads with an
  atomic refcount word (platform-width, String-style monotonic retain / release
  ordering + acquire fence at zero). Closures joined the **ImplicitCopy** family:
  `_is_no_copy_type(FUNCTION)` -> False, `_is_implicit_copy_type`/`_check_*_containment`
  treat an escaping closure like `String`. `let g = f` is legal again (retired
  71's NoCopy binding rejection + `closure_copy_requires_move_error`). Retain
  (`_generate_copy`/`_emit_retain_at` FUNCTION) bumps the env refcount; drop
  (`_emit_closure_drop_at`, now via `_emit_closure_env_release`) decrements and
  runs the dtor (captures release + free) only at zero; the spawn trampoline uses
  the SAME release (frame owns +1, exactly-once across the thread boundary). Null
  env (capture-less) => no refcount word, trivially copyable (retain/drop null-
  guarded). **RESIDUAL GAP CLOSED:** an owning closure in a copyable struct copied
  N times -> dtor once at the last owner (positive test). Also fixed a pre-existing
  leak the model surfaced: an escaping closure LENT into a non-escaping param must
  not clear the caller's drop flag (`closure_lend` marker). Tests:
  `closure_copy_binding`, `closure_copyable_struct_copied`, `closure_spawn_arc_balance`,
  `closure_captureless_copyable`, `closure_borrow_lend_balance`; 71's battery
  updated to refcounted expectations (all exactly-once). Suite 807, bootstrap
  17+17, libs 4+4. [73, 71]
- **Commit 2 (docs):** spec closures section rewritten (ImplicitCopy, refcounted
  env, exactly-once teardown, lend, null-env fast path); saw-lang skill Copy-tier
  table + gotcha updated. [73]
- **Findings (flagged, NOT fixed — out of design-73 scope):**
  - **DF-C1 (pre-existing coro-transform gap).** A closure LOCAL called inside a
    driven/suspending function (`let f = {...}; ... f()`) errors "undefined
    function f"; a closure held across a suspend in a frame errors "redundant
    `escaping`". Both fail identically on baseline (confirmed via stash) — a
    coroutine-transform frame-building limitation, unrelated to refcounting. Blocks
    expressing a TaskGroup frame that OWNS a closure; the thread-`spawn` balance
    test covers the cross-boundary exactly-once claim instead. [44, 45, 52b, 73]
  - **DF-C2 (deferred).** Closures deliberately do NOT satisfy the umbrella `Copy`
    bound yet: `Vector<() -> Int>.copy()`/`.get()`, Set/Map with closure elements
    need the container element-copy path routed through the refcount retain (a
    naive enable crashed exit 133). Clean compile error until wired. [54, 73]

## Design 71 — Closure Deinit (LANDED)
- **Commit 1 (core):** Closures now carry their own env destructor
  (`{fn_ptr, env_ptr, dtor_ptr}`, design 71). An escaping closure binding is an
  OWNING value: `_needs_cleanup(FUNCTION-escaping)` + `_emit_closure_drop_at`
  (null-dtor no-op) run the env destructor at the closure's own drop (LIFO +
  drop flags), releasing owned captures exactly once and freeing the heap env.
  Removed the creating-frame EARLY RELEASE: a `move` capture now clears the
  source binding's drop flag (this ALSO fixed a latent thread-`spawn`
  double-free of a move-captured NoCopy — deinit ran at frame exit AND in the
  trampoline). Copy class: escaping closures are NoCopy (move-only) — a bitwise
  copy aliased the heap env (double free, exit 133); forwarding an escaping
  closure into a NON-escaping/borrowing slot stays a lend (no move). Closure
  FIELDS excluded from NoCopy CONTAINMENT so capture-less-closure structs stay
  copyable. Exact-count battery: `closure_deinit_{drop_order,arc_balance,
  struct_field,vector,returned,dropped_uncalled,called_then_dropped,
  conditional_move}` + `closure_copy_requires_move_error`. Suite 789, bootstrap
  17+17, libs 4+4 green. RESIDUAL GAP (was: an owning closure in a COPYABLE
  struct that is then copied double-freed) — **CLOSED by design 73**: closures
  became ImplicitCopy (refcounted env), so the struct copy retains the env and the
  dtor runs once at the last owner. The NoCopy binding rejection above was retired
  in the same move. [71, 73]

## Decisions needed (user input required)
- **D10.** Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with
  the first such port. [19, 20]
- **SOS**: boot protocol + syscall ABI (sos/spec.md §5) — the next
  design session.

- **DF4 (meta).** Blade bit-rots as the compiler tightens — re-validate
  periodically (the bootstrap target is the canary). [49]
- **DF5.** Keywords (`extension` etc.) can't be identifiers — fine, but
  an eventual contextual-keyword sweep is noted. [49]
- ~~**DF6 (latent coro-transform bug, found in the post-92 net idiom
  skim, Aug 2).**~~ CLOSED (design 96). Root cause was NOT the
  infinite-loop shape but a `break`/`continue` inside a NON-spanning
  `if`/`match` nested in a suspension-spanning loop: `_lower_inplace`
  kept the raw jump, which breaks the resume method's `while true`
  DISPATCH loop instead of the logical loop → re-entry hangs. net
  read()'s break form triggered it via its `else if …else {break}`
  (a non-spanning inner if in the else of the spanning io_wait if).
  Fix: `_has_loop_ctrl` forces a CFG split of such an if/match when in
  a spanning loop, routing the jump to the loop state via `loop_ctx`.
  read() converted to the break form, NOTE removed; regression
  `coro_break_reentered_in_loop`.
- **B4 limit.** A git dep's locked REV isn't pinned without
  re-resolution (build-from-lock path reconstruction is future work);
  path deps unaffected. [64, 67]
- ~~**L18 — module-qualified type annotations (found in design 68).**~~
  FIXED (design 69). The typechecker resolved a dotted annotation
  (`v: mod.Type` / `let x: mod.Type` / `-> mod.Type`) for checking but
  left the dotted `struct_name` on the AST, so codegen ICE'd "Undefined
  struct: mod.Type". Fix at the source: write the resolved (qualifier-
  stripped) type back onto the AST — free-function params (registration),
  let annotations + method params/return (a guarded `_resolve_type` when
  `_annotation_has_module_qualifier` holds, so generic/Self are untouched).
  A related typechecker gap fell out (a method with a qualified param
  errored "body has no value" because the param scope kept the dotted
  type) — fixed by the same write-back. Locked by
  `examples/l18_module_qualified_annotation.saw`. [68, 69]
- **L2.** Return-type reconciliation for type-param/associated-type
  returns in generic bodies — documented deferred looseness. [02, 24]
- ~~**L9.** `==` over Optional-/array-bearing members: deliberate clean
  error; extend the equals derivation when needed.~~ CLOSED (landed e60d189;
  enum-Optional-payload case closed under design 72): the Equatable synthesis
  lowers `T?` (None/Some-aware) and `[T; N]` (element-wise) members. [32, 72]
- ~~**L12.** Fixed arrays can't take extension methods (parse error);
  also blocks fixed-array `.len()` (spec-illustrative).~~ CLOSED (design 72):
  fixed arrays get builtin `.len()` + `.swap(i, j)` (M1 escape hatch); user
  extensions on array types stay rejected with a clear diagnostic. [40, 72]

## Deferred features (decided or triaged, not scheduled)
- ~~Erased-error DOWNCASTING (needs a type-id design; catch-all boxes are
  opaque until then).~~ CLOSED (design 72): vtable `type_id` slot + `Box<any
  Trait>.is<T>()`/`take<T>()`. Catch-side match-on-concrete sugar still deferred
  (future). [56, 72]
- Debug trait (synthesized structural formatting) — own design. [56]
- Enum-direct Printable (enum method dispatch is a general gap). [56]
- Named tuple PATTERN form `(x: a, y: b)`. [63]
- Map `entries()` snapshot; Map ExplicitCopy/.copy(). [54, 57]
- Labeled-arg `_` opt-out; labeled-only enforcement. [66]
- Integer range-cover exhaustiveness. [63]
- Generic-method type-arg inference. [36]
- ~~Closure-Deinit: wire `codegen_env_dtor` into closure drop glue (C4).~~
  **CLOSED (design 71 landed):** escaping closures carry their env destructor
  and drop it at the closure's own drop (exactly once); early frame release
  removed; escaping closures are NoCopy. Residual owning-closure-in-copyable-
  struct-then-copied gap tracked under the design-71 section. [21b, 59, 71]
- `Weak<T>` (Arc slot reserved). [16, 21]
- Slices (needs own design vs no-escape refs); `\x` byte escapes;
  where clauses; extension sugar (computed properties, conditional
  extensions); submodule directories; std.io traits (Blade-driven).
  [user triage Jul 29]
- S5 small-string optimization — ABI-gated ("before separate
  compilation or never"). [07]
- Registry for Blade (salvaged sketch, old pm design): static HTTP
  index or git repo; `GET /api/v1/crates/{name}` metadata +
  `/{version}/download` tarball; `blade login/publish`. [pm_design,
  deleted Jul 30 — see git history]

## Async (post-52b roadmap)
- ~~**A5.** Effect polymorphism via monomorphization-time re-inference —
  BLOCKS generic suspending/driven functions.~~ DONE (design 70): effect
  inference runs PER instantiation (keyed by mangled symbol); the coroutine
  transform accepts suspending instantiations of generic functions/methods by
  monomorphizing them to concrete functions/methods before frame synthesis
  (driven free fn, `TaskGroup.spawn`, and `&var self` method all land). A `sync`
  context calling an instantiation that suspends is a violation reported AT the
  call, naming the instantiation + suspension path (minimal A8). Still rejected
  with precise diagnostics: a buried suspending method-on-`T` call inside a
  driven body, nested suspending generic calls, generic-struct-extension driven
  methods, and cross-module generic templates (re-ledgered below). [18, 22]
  - **A5-rest.** PARTLY DONE (design 74): driven methods on GENERIC structs
    (shape 2) and nested suspending generic calls (shape 3) LANDED; A8 diagnostic
    anchors LANDED (coroutine-transform rejections anchor at the user's
    file:line:col). Remaining, now CLEAN user-anchored rejections (re-ledgered
    under the design-74 section with analysis): buried suspending METHOD-call
    embedding (shape 1, the Part-0b method twin); cross-module generic driven
    templates (shape 4, design 68 territory). [70, 74]
- ~~**A2.** Multi-threaded work-stealing executor + Send-on-frames check.~~ DONE
  (design 75): `TaskGroup(threads: N)` runs N OS workers over a single
  mutex-protected shared queue (fork-join drain; per-worker lock-free deques
  deferred as documented — the sanctioned simpler shape). Send-on-frames gate on
  spawn into a multi-threaded group (params + across-suspend locals + result). D6
  confinement preserved (one worker per frame; frames move only between
  suspensions). Cross-task cancel via `TaskHandle.cancel_addr()`. [18, 52b, 75]
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
  MOSTLY DONE (design 76): cancellation observed at the io suspension point via the
  cancel-check-before-`io_wait` idiom (+ the existing channel/yield checks).
  Remainder: waking an ALREADY-io-parked task on cancel (self-pipe) — re-ledgered
  under design 76.
- ~~**A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).~~ MOSTLY DONE
  (design 76): global kqueue/epoll reactor + `io_wait` intrinsic + std.net
  nonblocking TCP; ST group + entry executor never-block poll. Remainders
  re-ledgered under design 76 (MT integration, first-class inline-lowered
  read/accept/write). [18, 76]
- ~~**A6.** `extern blocking` offload pool.~~ DONE (design 76 front-end + the two
  type-system rejections; design 103 the runtime offload + coro lowering — a
  blocking call inside a suspending body now RUNS on a worker thread and parks on
  its pipe; see the design 103 entry). **A7.**
  Separate-compilation interface format w/ suspends bit. ~~**A8.** Suspension-path
  diagnostic anchors.~~ DONE (design 74): coroutine-transform rejections + sync
  violations anchor at the user's file:line:col with a source snippet, naming the
  instantiation + suspension path. ~~**A9.** Actor sugar.~~ DROPPED from the
  roadmap (user, Jul 31). [18, 74, 76]
- Two runtimes coexist (thread-engine spawn/Task vs cooperative
  TaskGroup) — unification unscheduled. [21b, 52b]

## App-2 / freestanding path
- **F7** remainder: assembly boot shim + wiring (compiler surface DONE
  — @export/@section/Never, design 58). **F8** linker scripts. **F9**
  QEMU riscv32 smoke ("blink") + CI. **F10** fence/barrier primitives
  for DMA ordering. [20, 46, 58]
- ISR conventions; riscv32 target completion (i32 word landed, 47).
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, UnsafeCell-equivalent story.
- **F6.** dtoa/Float printing under freestanding. [20]
- ~~**T1f.** Debug info (line tables → backtraces).~~ DONE (design 69):
  DWARF line tables on by default; lldb breakpoints + `file:line`
  backtraces; panics/asserts name their source location. [tier-1]
- `AllocatedBy<Slab>` sugar. [19, 42]

## Testing & infra
- **M2.** Unit tests for lexer/parser/typechecker internals; fuzz/
  differential testing; property tests over copy/move rules. [critique]
- ~~CI: GitHub Actions workflow for suite + bootstrap.~~ DONE (design 69):
  `.github/workflows/ci.yml` (ubuntu + macos) runs the compiler suite,
  the debug-info test, the blade bootstrap, and semver/toml lib tests;
  README badge. Linux is a new target — first CI run may surface small
  follow-ups (PIC-reloc + sys.executable portability fixes landed).
- ~~Runtime error messages with source locations (subsumed by T1f).~~
  DONE (design 69): panics carry `FILE:LINE`.

## Research tier (post-both-apps)
Const generics; const fn; macros; compile-time reflection (PMP
generation consumer, 46); Char/Int128/Float32; `**`/`::` operators;
Deque; RwLock/Barrier; std.net (after A4); async select;
Sender/Receiver split; §11 futures (effect system, dependent/linear/
refinement types, first-class modules); REPL/LSP/formatter; `defer`/
`do` reserved-word decisions.

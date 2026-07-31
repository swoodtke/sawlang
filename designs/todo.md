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
- **Commit 3 (A6 honest subset: `extern blocking` sync-reject + freestanding
  reject):** the A6 FRONT-END was already wired (parse `extern "C" { blocking func
  ... }`, `is_blocking` on the AST, blocking-extern as an effect suspension
  source). This commit closes the two type-system halves: (1) a blocking-extern
  call in a `sync` context is rejected by the effect checker, anchored, naming the
  extern + suspension path (locked by `errors/blocking_extern_sync_reject`); (2)
  declaring an `extern blocking func` in the FREESTANDING profile is a clean
  registration-time error (no hosted pool). Suite 825, bootstrap 17+17, libs 4+4.
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
- **A6.** `extern blocking` offload pool. PARTLY DONE (design 76): front-end
  (parse/effect) + the two type-system rejections landed — a blocking call in a
  `sync` context is rejected (anchored), and a blocking extern in the freestanding
  profile is rejected at registration. Runtime offload pool + coro lowering
  DEFERRED with the worked-out design (re-ledgered under design 76). **A7.**
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

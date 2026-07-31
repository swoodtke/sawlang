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
  - **A5-rest.** Buried suspending method-call embedding (drive `w.step()`
    nested in a driven body as a method sub-frame — needs Part-0c embedding, the
    method twin of Part-0b); driven methods on GENERIC structs; cross-module
    generic driven templates (design 68 territory). [70]
- **A2.** Multi-threaded work-stealing executor + Send-on-frames check.
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
- **A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).
- **A6.** `extern blocking` offload pool. **A7.** Separate-compilation
  interface format w/ suspends bit. **A8.** Suspension-path diagnostic
  anchors. **A9.** Actor sugar. [18]
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

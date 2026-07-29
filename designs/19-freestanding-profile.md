# Option Paper 19 — Freestanding profile and allocators

**Status: DECIDED (Jul 28, user) — Option A + C ratified.** The `saw_alloc`
global seam (landed, brief 20) stays as the floor; **allocator as a type
parameter** (`Vector<T, A: Allocator = Global>`, zero-sized static-backed
allocator unit structs) is the committed model, which entails default type
parameters as a staged generics feature. Stage 3 is briefed in
`designs/28-allocator-stage3.md`. Decision discussion also pinned the
placement-write mechanism for fallible factories (`MakeBox`): typed
raw-pointer store (`ptr[0] = move value`) IS the placement-move primitive
(bitwise move, source consumed, NO destination release — stdlib author's
obligation to use only on uninitialized slots), and surfaced that
`alignof<T>()` does not exist yet (Vector hardcodes align 16) — both folded
into the stage-3 brief. Driven by the project's initial targets:
kernels and small embedded (see memory note + `designs/18`'s Freestanding
profile section). Today Saw links libc unconditionally: String/Vector/Arc
buffers use `malloc`, panics are `printf`+`abort`, `print` is `printf`.
This paper defines how Saw runs with no OS and no libc, and how allocation
becomes pluggable — including per-type slab allocators.

## 1. Stdlib layering (the Rust-proven split)

- **`core`** — freestanding, allocation-free: primitives, structs/enums,
  traits, Copy family, Optionals/Result, match, fixed arrays, tuples,
  string LITERALS (static, immortal — no alloc needed), Deinit machinery.
- **`alloc`** — needs an Allocator, no OS: String (dynamic), Vector, Map,
  Arc, Box (future), interpolation/concat.
- **`std`** — hosted: file, process, env, directory, hosted IO.
Programs declare (or the target implies) their layer; importing above your
layer is a compile error naming the layer. Existing code is unaffected —
hosted remains the default profile.

## 2. The seams (symbols, not designs)

All hosted defaults become weak/default implementations of named symbols a
freestanding program must (or may) replace at link time:
- **`saw_alloc(size, align) -> ptr` / `saw_dealloc(ptr, size, align)`** —
  the global allocator. Hosted default wraps malloc/free. Freestanding:
  user provides (bump, buddy, kernel heap). Rust `GlobalAlloc` precedent.
- **`saw_panic(msg_ptr, msg_len) -> !`** — hosted default prints + aborts;
  freestanding: user provides (log-and-halt, reboot). Panic strategy stays
  **abort-only, forever** (no unwinding — deterministic destruction does
  not survive unwinding complexity; Rust panic=abort mode as precedent).
- **`saw_write(bytes_ptr, len)`** — the output primitive behind `print`.
  Hosted default: stdout. Freestanding: UART/serial/framebuffer.
- Existing FFI (`extern`) is unchanged — it is the mechanism, not a seam.

## 3. Target/profile mechanics

- `--target <triple>` (cross-compilation — llvmlite emits for any LLVM
  triple; needed for ARM MCUs regardless of the rest of this paper).
- `--freestanding`: no default libs, no libc externs declared, `core`
  (+`alloc` if an allocator symbol is provided) only, entry symbol is the
  user's (`_start`/vector table), and kernel-relevant codegen flags become
  available: `-mno-red-zone` equivalent (x86-64 interrupt safety),
  soft-float, code model. These are target-attribute plumbing, not design.
- **Atomics caveat (real, must decide per target):** String/Arc refcounts
  use `atomicrmw`. Cortex-M0/M0+ (ARMv6-M) has no CAS — LLVM lowers to
  `__atomic_*` libcalls that need a runtime. Freestanding ports to such
  cores need a per-target lowering (disable-interrupts critical section) or
  restriction to `core` (no refcounted types). Flag now, decide with the
  first such port.

## 4. Allocator model — and per-type slab allocators

### The trait
```saw
trait Allocator {
    func alloc(&self, size: Int, align: Int) -> UnsafePointer<Int8>?
    func dealloc(&self, ptr: UnsafePointer<Int8>, size: Int, align: Int)
}
```

### Options for wiring allocators to allocations

**A. Global-only.** Just the `saw_alloc` seam; every allocation goes to one
allocator. Simplest; kernels multiplex inside their one allocator.
- Pro: zero language change. Con: the kernel pattern (per-type slabs) is
  invisible to the type system; multiplexing by size at runtime is exactly
  what slabs exist to avoid.

**B. Zig-style value passing.** Every allocating API takes an allocator
argument (`Vector.init(a)`), stored in the container.
- Con: storing an allocator *reference* violates no-escape; storing a fat
  value bloats every container; infects every signature. Wrong fit.

**C. Allocator as a TYPE parameter, zero-sized static-backed allocators** ⭐
`Vector<T, A: Allocator = Global>`, `Arc<T, A = Global>`, `Box<T, A>`.
An allocator like a kernel slab is a **unit struct** (zero fields) whose
methods reference its own static storage region:
```saw
struct TaskSlab {}   // zero-sized; storage is a static region
extension TaskSlab: Allocator { ... }        // fixed chunk = sizeof(Task)
type TaskBox = Box<Task, TaskSlab>           // the kernel idiom
```
- **Why it fits Saw exactly:** the allocator "handle" is a type, not a
  stored reference — no escape problem, nothing stored per container,
  dispatch monomorphizes to direct calls (zero overhead), and `sizeof(T)`
  is known at monomorphization time, which is precisely what a slab needs.
  Deallocation on Deinit statically knows its allocator. Mixing containers
  from different allocators is a *type error*, not a runtime corruption.
- **Cost:** needs **default type parameters** (`A = Global`) so hosted code
  never writes `A` — a real but contained generics feature. Until it
  lands, `alloc`-layer types can hardcode `Global` with the parameter
  threaded internally (mechanical migration later).
- **Per-type sugar (later, optional):** `extension Task: AllocatedBy<TaskSlab>`
  making `Box<Task>`/`Arc<Task>` default their `A` to `TaskSlab`. Pure
  sugar over C; decide when kernel code exists to justify it.

**D. Scoped/ambient allocators (arenas by context).** Implicit region
allocator for a dynamic scope. Powerful but implicit — against the house
philosophy; revisit only if arena patterns become pervasive.

**DECIDED (Jul 28, user): A now (the seam is needed regardless) + C as the model**
— C degenerates to A when only `Global` exists, so they compose rather
than compete. Statics note: Saw has no global variables today; a slab's
static region needs either module-level `static` declarations (small,
contained language addition — kernels need statics anyway) or an unsafe
extern-region escape hatch initially.

## 5. What stays hosted-only (honest list)
`std.process/file/env/directory`, dynamic `spawn` (allocator-backed),
blocking-compensation executor. The freestanding async core (18) pairs
with this paper: static tasks + `core`(+`alloc`) + these seams = a kernel
runtime.

## 6. Staging
1. Seams (`saw_alloc`/`saw_panic`/`saw_write`) with hosted defaults —
   invisible refactor, immediately testable in the existing suite.
2. `--target` + `--freestanding` + layer enforcement; a QEMU-or-similar
   smoke target in CI ("blink"-equivalent: boot, print via saw_write,
   halt).
3. `Allocator` trait + `Global`; thread `A` through alloc-layer types
   internally (hardcoded `Global`).
4. Default type parameters; expose `A` publicly; slab allocator in the
   stdlib (in Saw, over a static region) + `static` declarations design.
   **LANDED (brief 37) except slabs/statics:** default type parameters
   (`struct Vector<T, A: Allocator = Global>`) ship, and `A` is now a public
   type parameter on `Vector` and `Map` — `Vector<T>` fills `A = Global`
   before mangling (one identity, one monomorphization), `A().alloc(...)`
   monomorphizes to a direct seam call, and a custom allocator
   (`Vector<Int, LoudAlloc>`) is a distinct type that routes alloc/grow/deinit
   through its own `A`. Still open here: per-type **slab allocators** (F3) and
   module-level **`static`** declarations (F4) — a later brief.

## Open questions (flagged, not decided)
- ~~`static` mutable data semantics~~ **DECIDED (Jul 28, user — Rust's
  rule): statics must be `Sync`, const-initialized, immortal (never
  deinit), and there is NO `static mut`, ever.** Mutation of global state
  flows only through interior-synchronized types (`Mutex<T>`, `Atomic<T>`,
  future `Once`/`Lazy<T>`). This satisfies paper 08's recorded global-
  reachability constraint and makes "all shared mutable state is mediated"
  a language-level theorem — the enabling condition for paper 18's
  colorless option. Known implications (none unrepresentable, three need
  dedicated types): runtime-initialized globals need `Once`/`Lazy<T>`
  stdlib types; kernel per-CPU data needs a purpose-built `PerCpu<T>`
  abstraction (not expressible as a plain Sync static); user-built
  lock-free structures need a future `UnsafeCell`-equivalent + unsafe
  story (until then the interior-mutable primitive set is closed and
  compiler-known). Const-init starts minimal (literals/POD/byte arrays —
  sufficient for slab regions); hosted `Mutex` in a static needs
  const-friendly init (`PTHREAD_MUTEX_INITIALIZER` or first-lock atomic
  lazy-init). Statics holding `Deinit` types never run deinit (immortal;
  OS/reset reclaims) — standard, documented.
- Cortex-M0-class atomics lowering (see §3).
- ~~Whether `alloc` failure is optional or panic~~ **RESOLVED (Jul 27,
  refined from user proposal): three tiers, identical in both profiles.**
  (1) Default allocating APIs are infallible; on final failure they panic
  into `saw_panic` (the kernel's own handler: oops/kill-task/reboot —
  noting a killed task's held resources leak unless tracked externally,
  as in real kernels). (2) Explicit fallible **factory functions** (refined
  Jul 27, user): `MakeBox(...) -> Result<Box<T,A>, AllocError>`,
  `try_push -> Result` — for sites that genuinely handle OOM locally.
  A single allocation needs NO nonlocal machinery: the allocator returns
  null, the factory checks and returns `Err` (reclaim hook still runs
  underneath); `AllocError` carries allocator/size context for oops logs.
  Compound construction propagates `Result` through its internals (the
  Zig model). Accepted: kernel code reads differently from hosted code —
  fallible factories at allocation boundaries; same language, different
  idiom density, congruent with the core/alloc layering.
  Future/research (NOT v1): "fallible construction regions" — a
  transactional scratch-arena scope whose deep failure returns to the
  boundary with wholesale region teardown, keeping compound internals
  uncolored; sound ONLY with compiler-enforced "no external resource
  effects inside the region" (else skipped deinits leak external
  refcounts/locks). Revisit after statics + allocators exist.
  (3) Underneath both, a
  **per-allocator reclaim hook**: on exhaustion the allocator synchronously
  calls its registered handler (flush/evict/kill-a-task) and retries —
  Linux direct-reclaim as a plain call, centralizing OOM policy in the
  allocator. **Explicitly rejected: non-local jump ("exception") to a
  registered handler** — a longjmp-style transfer skips deinits (leaks,
  held locks — breaks deterministic destruction), and jump-with-cleanup is
  C++-style unwinding, which stays rejected (abort-only; kernels compile
  without unwinding for good reason).

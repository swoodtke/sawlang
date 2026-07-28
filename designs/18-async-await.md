# Option Paper 18 — Async/await and the concurrency model

**Status: DECISION NEEDED (user).** Builds on: `designs/16` (escaping/
non-escaping closures — spawn's API), `designs/08` (exclusivity), the
Send/Arc/Mutex analyses recorded in 16, and the atomic-String decision in
`designs/07`. Spec currently tags all of §6 Concurrency as planned.

## The soundness centerpiece (theorem to write into the spec)

**Structured awaiting keeps borrows sound; spawning strips references.**
- An `await` parks the entire caller chain: the caller cannot execute until
  the awaited callee completes. Therefore a `&`/`&var` parameter held by an
  async callee remains valid and *exclusive* across its suspension points —
  no aliasing can arise, because the only frame that could alias it is
  parked. References across `await` in awaited callees are sound with NO
  new machinery (the coroutine frame storing them internally is
  compiler-internal, justified by the parked-caller argument).
- Concurrency begins only at `spawn`, and `spawn` takes an **escaping**
  closure — which by paper 16 cannot capture references. So references
  never cross task boundaries; inter-task sharing is exclusively
  `Arc`/`Mutex`/channels (with `T: Send` once that lands).
- Consequence: **no actor system is required for memory safety.** Swift
  needed actor isolation because `self` is a shared mutable reference;
  Saw's async mutation of local state is linear (post-`await`, in the frame
  that owns it). Actors remain available later as pure ergonomics sugar
  over Arc+Mutex+queue.

## Axis A — execution model

### A1. Stackless coroutines (state-machine transform)  ⭐ recommended target
Each `async func` compiles to a state machine; suspension stores live locals
in a frame; an executor resumes it. Rust/Swift/C++ standard; no runtime
stacks; zero cost when not suspended.
- **Cost:** the biggest compiler work item to date — a CPS/state-machine
  transform over the typed AST, or LLVM's coroutine intrinsics. **Probe
  required before the brief:** whether llvmlite 0.48 exposes the coro
  intrinsics + passes usably; if not, the transform is hand-rolled at AST
  level (more work, more control, no llvmlite dependency).

### A2. Stackful coroutines (green threads)
Functions stay functions; a runtime switches stacks.
- Simpler codegen, but brings a real runtime (stack allocation/sizing,
  context switching, FFI hazards with foreign code on growable stacks).
  Wrong fit for a language whose runtime is currently malloc+free+printf.

### A3. Threads + channels only (no async syntax)
`spawn` + channels + Mutex, blocking calls, no `await`.
- Not the destination, but a legitimate **stage**: it exercises Send,
  channels, Arc/Mutex, and the spawn-strips-references rule with zero
  compiler-transform risk.

**Recommendation: stage it — behind a task-only API (see Axis A′).**
1. **Stage 1 — tasks/channels/Mutex, thread-per-task engine**: `spawn`
   (escaping closure) creates a TASK — implemented as an OS thread today,
   never named as one. `Channel<T>` with `send(move v)`, `Mutex.lock { }`.
   Forces Send/Sync machinery (structural auto-derivation, the auto-Copy
   pattern) and validates the sharing model. No new syntax.
2. **Stage 2 — `async`/`await` on a single-threaded executor** (A1):
   the state-machine transform lands without Send-on-frames complexity
   (frames never cross threads). Structured concurrency primitives here.
3. **Stage 3 — multi-threaded (work-stealing) executor**: requires
   coroutine frames to be `Send` (a structural check over live-across-await
   state — the machinery from stage 1 applies). Opt-in per task group if
   we want to keep single-threaded simplicity as a mode.

## Axis A′ — tasks are the ONLY concurrency primitive  ⭐ DECIDED-LEANING
(raised Jul 27): **no user-facing thread API, ever.** Go's posture (one
primitive, runtime owns threads) with Saw's safety model; avoids Rust's
permanent sync/async ecosystem split. Rules that make it hold:
- `spawn` is defined as creating a *task*; the engine (thread-per-task in
  stage 1 → work-stealing coroutines in stage 3) is an implementation
  detail users cannot observe. **The API must never leak thread identity:
  no thread IDs, no thread-locals, no thread-join semantics** — this
  prohibition binds from stage 1, or engine swaps break code.
- **Blocking is legal in tasks.** FFI and long compute must not be
  hazards; the executor compensates (grow the pool when tasks block —
  simplified Go model), with `spawn_blocking`-style hinting as an
  optimization, never a correctness requirement.
- ~~Async-only concurrency ≠ async-only IO; sync blocking IO stays~~
  **REVISED (Jul 28, user proposal + refinement): "tasks never block on
  the outside world." The invariant is latency-UNBOUNDEDNESS, not IO-ness
  — `await` means "may wait indefinitely on outside input."**
  - **Async-only (unbounded external waits):** sockets, accept, channel
    receive, timers/sleep (deliberate waiting is waiting), process-wait,
    stdin. A task blocked on these is a liveness hazard.
  - **Sync stays for bounded local operations:** regular-file read/write,
    console — completion guaranteed by the local machine in bounded time.
    Scripts keep unceremonious sync `File.read`. Documented wart shared
    by every system with this split: network filesystems make "local
    disk" secretly unbounded.
  - **Reactor consequence — poller-only v1:** with bounded file IO
    accepted as sync, the hidden worker-pool offload is NOT needed for
    correctness; hosted reactor = kqueue/epoll over genuinely unbounded
    sources only. The pool returns later solely as optimization
    (io_uring-backed async file IO) or for `extern blocking` FFI.
  - Embedded reads identically: flash reads bounded/sync; UART/radio
    receive unbounded/async.
  - **Coloring STAYS** (this does not reopen colorless): implicit
    suspension everywhere would force every function into a state machine
    (whole-program CPS) or stackful tasks — the latter rejected for
    KB-RAM targets. Colored `await` + async-only waiting APIs = Go's
    invariant with visible markers.
  - **Freestanding unification:** same Waker abstraction, reactor =
    interrupts/WFI (the Embassy model verbatim) — hosted and kernel
    runtimes are one design with different event sources plugged in.
  - **FFI is the unclosable hole — annotate it:** `extern blocking func`
    → offloaded to the pool on hosted, compile-error (or documented
    hazard) freestanding; unannotated externs promise promptness.
  - **`print` exempted** (console/UART treated as prompt) so trivial
    programs need no executor.
  - Residual, unfixable by IO design: long compute still starves a
    cooperative executor — hosted mitigates via the multi-threaded
    executor; embedded lives by cooperative discipline.
  The runtime still links only into programs that spawn/await;
  pure-compute programs pay nothing.
- ~~Accepted scope cost: no-runtime environments get no concurrency~~
  **REVERSED (Jul 27): kernels and small embedded are the project's INITIAL
  targets** — freestanding support is a first-class requirement, and
  stackless tasks-only is the model that serves it best (existence proof:
  Rust's Embassy — full async on KB-scale microcontrollers, no OS/heap/
  threads; tasks are compile-time-sized frames, not stacks). See
  "Freestanding profile" below.
- Simplifications bought: Send audit surface = exactly two doors (spawn
  captures, channel sends); no thread lifecycle API; structured
  concurrency has no unstructured rival; one stdlib model forever.

## Axis B — function coloring

### B1. Colored (`async func` / `await`, async callable only from async)  ⭐
Industry standard (Rust/Swift/JS/C#/Python). Composes with paper 16's
`escaping` marker — colors surface at the same boundaries. Blocking-from-
sync escape hatch: a `block_on` entry point (main can be async, or calls
`block_on`).
### B2. Colorless (Go/Zig-style)
Every call is potentially suspending. Requires green threads (A2) or global
CPS — conflicts with A1 recommendation and with readable cost-at-use-site
philosophy (`await` marks suspension exactly like `move`/`.copy()` mark
transfers; Saw is the language that marks things).
**Recommendation: B1.** `await` is a cost/reentrancy marker in exactly the
spirit of the rest of the language.

## Axis C — task discipline

### C1. Structured concurrency by default  ⭐
Task groups / nursery-style: spawned children are joined or cancelled by
scope exit; a task's lifetime is a value's lifetime. This is the natural
mate for deterministic destruction — LIFO scope cleanup extends to tasks.
Detached tasks exist but are explicit (`spawn_detached`), for the rare
daemon case.
### C2. Free-floating tasks (JS/tokio-default style)
Simpler to implement first, but leaks the lifetime discipline the whole
language is built on.
**Recommendation: C1**, with cooperative cancellation checked at suspension
points (Swift model); cancellation is a thrown/Result-style signal, not
preemption.

## Smaller decisions bundled here
- **Futures are not user-facing values initially** (no `poll`, no `Future`
  trait): `async func` + `await` + task groups only. Exposing a Future
  abstraction is a later, compatible addition if combinators demand it.
- `try await` ordering: `try await f()` (Swift order), `await` binds
  tighter in the grammar; async closures are `escaping async` and follow
  paper 16's capture rules (value/move/ImplicitCopy only — they're
  escaping by definition).
- `main` may be declared `async` (compiler wraps in `block_on`).
- Async `deinit` is **forbidden** (deinit is synchronous, always — anything
  else breaks deterministic destruction; Swift's async deinit pain is a
  cautionary tale).

## Freestanding profile (added Jul 27 — initial-target requirement)

The runtime is layered so the core is freestanding:
- **Core executor (the permanent foundation, not a stepping stone):**
  single-threaded cooperative run queue + wake mechanism; a few hundred
  lines, single-digit KB of code. The only platform hook is "sleep/wake":
  `WFI` on bare metal, futex/condvar hosted. ISR wake = atomic ready-bit +
  queue insert. **Static task allocation** (tasks declared up front, frames
  in .bss) makes it allocation-free; per-task cost = compile-time-sized
  frame + ~2 words of linkage. Useful minimum shipped with it: structured
  join, bounded static channels, one hardware-timer hook.
- **Hosted layer (on top):** thread pool, blocking compensation, dynamic
  spawn (allocator-backed), IO reactor.
- The "blocking is legal" rule is profile-split: hosted compensates with
  threads; freestanding has none — cooperative discipline is documented
  reality there (standard embedded practice).
- **Broader flag (own workstream, more urgent than async itself):** Saw
  today assumes libc — String/Vector call malloc, panic is printf+abort.
  The freestanding profile needs pluggable allocator + panic-handler seams
  (linkage-level) and a heap-free stdlib subset story. Deserves its own
  option paper before any Stage-2 work.

## What this paper does NOT decide
- Executor implementation details (queue discipline, timers, IO reactor) —
  stage-2 brief territory. IO integration (epoll/kqueue vs blocking-pool)
  is genuinely open and can be deferred: stage 1 uses blocking IO on
  threads; stage 2 can too (async compute first, async IO later).
- Actor sugar — explicitly deferred until Arc+Mutex+queue patterns prove
  common enough to deserve syntax.

## Sequencing
Stage 1 has no compiler-transform risk and two prerequisites already landed
(Arc-ready refcount protocol, escaping closures pending paper 16's
implementation). Realistic order: paper-16 implementation → Send/Sync +
Stage 1 → Stage 2. Nothing here blocks current briefs.

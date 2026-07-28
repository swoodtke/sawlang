# Design Brief 21 — Concurrency stage 1: Send/Sync, Arc, spawn, Channel, Mutex

**Source:** `designs/18-async-await.md` (staging: stage 1 — the task API on
a thread-per-task engine, NO new syntax) plus the Arc design notes in
`designs/16` ("Weak/Arc design notes") and the atomic protocol in
`designs/07`. Read all three sections first.
**Scope guard:** stage 1 is deliberately independent of the still-open
paper-18 coloring refinements and of statics (none used — sharing is
Arc-borne). NO async/await syntax, NO executor, NO Weak, NO freestanding
concurrency (hosted pthread engine only; the task API is
engine-agnostic by design — never expose thread identity).
**Prereqs landed:** runtime seams (allocate via `saw_alloc`, never malloc),
`__deinit_in_place`, ImplicitCopy machinery, String atomic protocol.

## Work items (commit order; each green)

### 1. `Send`/`Sync` marker traits with structural derivation
Compiler-known, auto-derived structurally (the auto-Copy pattern):
- Primitives, `Bool`, `Float`: Send+Sync. `String`: Send+Sync (immutable
  buffer, atomic refcount — the designed payoff).
- Struct/enum: Send iff all fields/payloads Send; same for Sync.
- `UnsafePointer<T>`: neither (poisons containing types structurally).
- `Mutex<T>`: Send iff `T: Send`; Sync iff `T: Send`.
- `Arc<T>`: Send and Sync iff `T: Send + Sync`.
- References/closures: not user-nameable as bounds v1; closure-env
  Send-ness is checked structurally at `spawn` sites (item 5).
Usable as generic bounds (`T: Send`). No explicit conformance declarations
accepted v1 (no unsafe-impl story yet) — derivation only; reject
`extension X: Send` with a clear message.

### 2. `Arc<T>`
Per designs/16 notes: one control block `{strong: i64, weak: i64,
payload}` allocated via `saw_alloc`. **Weak count reserved NOW** (init 1 =
the strong refs' collective weak) even though `Weak` doesn't ship — the
layout is ABI. `ImplicitCopy + Deinit`: retain = atomicrmw add monotonic;
release = atomicrmw sub release, and the releasing thread that took
strong to 0 issues fence acquire, runs `__deinit_in_place` on the payload,
then decrements weak (release; at 0: fence acquire, `saw_dealloc` the
block). Constructor `Arc(move v)` — value-transfer rules apply to moving
the payload in. `arc.get { &data in ... }`-style read access? NO — v1
Arc exposes the payload ONLY via method forwarding for `Sync` payloads…
keep it minimal: v1 Arc is a dumb owner; the useful composition is
`Arc<Mutex<T>>` (item 4 gives access) and `Arc<T>` where T's methods are
called via an immutable-borrow receiver. Probe what receiver lowering
needs; document what works.

### 3. Reference-typed closure parameters (enabler for Mutex.lock)
Closures must support `&`/`&var` parameters: `{ &var data in ... }`
receives a pointer, body mutates through it. Typechecker: such params are
reference-typed VariableInfo (existing `&var` param machinery); the
CLOSURE VALUE itself becomes non-storable: a closure whose signature
contains reference params may only appear as a direct call argument —
reject binding/returning/capturing it (conservative gate, consistent with
designs/16 direction; full non-escaping closures come later).
Exclusivity: passing `&x` into the closure call follows the existing
call-site rules.

### 4. `Mutex<T>`
`NoCopy + Deinit`. Hosted engine: pthread_mutex_t allocated via saw_alloc
(size via a small C-probe constant per platform is NOT acceptable —
instead call `pthread_mutex_init` on a conservatively-sized opaque buffer;
probe the real sizes on macOS/Linux and document the chosen buffer size).
API v1: `Mutex(move value)`, `lock(closure)` where the closure takes
`&var T` (item 3) and returns the closure's result;
lock is NON-REENTRANT (self-deadlock; document in spec note). No
try_lock/timeouts v1. The closure is called exactly once, synchronously.
Payload deinit on Mutex deinit via `__deinit_in_place`.

### 5. `spawn` and `Task<T>`
`spawn { ... } -> Task<T>` (closure returns T). Engine: pthread_create
with a trampoline passing the closure `{fn, env}` through void*; result
written to a saw_alloc'd slot. **Send check:** every captured value's
type must be Send (structural, at the spawn site; error names the
offending capture and type). `Task<T>`: `NoCopy`; `join(move self) -> T`;
deinit of an unjoined Task JOINS (structured-by-default — a task's
lifetime is a value's lifetime; document). No detach v1. Never expose
thread ids/handles.

### 6. `Channel<T>`
`Channel<T>` is an `ImplicitCopy` HANDLE (internally refcounted like
Arc — Go-style: cloning the handle shares the queue). Unbounded MPMC
queue guarded by an internal mutex + condvar (pthread_cond, same
opaque-buffer approach). API v1: `Channel<T>()`, `send(move v)` (requires
`T: Send` — checked at the generic bound on Channel itself:
`Channel<T: Send>`), `recv() -> T` (blocks the calling thread in this
engine — DOCUMENT: becomes a suspension point when the cooperative engine
lands; API shape unchanged). Queue nodes via saw_alloc; drain + free on
last handle release.

### 7. Tests (deterministic only)
- `spawn_join.saw` — spawn computes, join returns value.
- `spawn_multi.saw` — N tasks joined, sum of results exact.
- `mutex_counter.saw` — Arc<Mutex<Int>>, N tasks × M increments, final
  count N*M exact.
- `channel_pipeline.saw` — producer task sends 1..k, consumer sums, exact.
- `task_join_on_deinit.saw` — unjoined task completes before scope exit
  observably (order-independent output design — be careful: only assert
  what is deterministic).
- Error tests: `errors/spawn_capture_not_send.saw` (captured
  UnsafePointer-holding struct → error naming capture),
  `errors/channel_not_send.saw`, `errors/mutex_closure_stored.saw`
  (item-3 gate), `errors/send_explicit_conformance.saw` (item-1 rejection).
- Nondeterministic scheduling must not leak into EXPECT-OUTPUT — design
  every test so output order is forced (joins/channel acks), or assert
  only final values.

### 8. Spec
Concurrency section: mark stage-1 subset implemented (tasks, channels,
Mutex, Send/Sync derivation), pointing at designs/18 for the model and
noting recv/lock semantics under the future cooperative engine.

## Report back
Per item: mechanism + where. The pthread opaque-buffer sizes chosen and
how probed. Arc teardown ordering verification (no leak/double-free —
how proven). Send derivation table as implemented. How spawn's env
Send-check walks capture types. Any nondeterminism encountered in tests
and how eliminated. Deviations; non-allowlisted commands (ideally none).

# The Saw runtime ABI (`__saw_rt_*`) — design 113

This is the frozen contract between compiled Saw code and its host runtime.
The compiler DECLARES and CALLS these symbols; a linked runtime IMPLEMENTS
them. Freezing the set here is what lets a runtime be a **link-time swap**
(host_macos, host_linux, sos-hosted, kernel/none) instead of compiler surgery.

Two symbol tiers exist (design 113); only the first is this ABI:

- **`__saw_rt_*` — the runtime ABI (THIS document).** Implemented by a linked
  runtime. The compiler emits them as external declarations under every
  profile. In the hosted profile a runtime object is linked automatically; in
  the freestanding profile the environment (kernel/bootloader/RTOS) supplies
  them.
- **`__saw_*` — compiler-internal synthesized helpers (NOT this ABI).** Emitted
  as IR bodies by codegen, carry no host-OS knowledge, and a runtime must NOT
  provide them: string retain/release/alloc/from_bytes/len
  (`__saw_string_*`), the Arc/Channel atomic helpers
  (`__saw_atomic_add_i64`, `__saw_atomic_sub_i64_release`,
  `__saw_atomic_fence_acquire`), and integer print (`__saw_print_int`).

Widths follow design 47. `word` below = the platform `Int`/`UInt` width
(pointer-width: 64-bit on x86-64/aarch64, 32-bit on riscv32). The stdlib types
the seams that carry sizes/counts/fds as `Int`, so they are `word`-wide; the
clock seams return `Int64` explicitly. On the 64-bit hosted targets `word` is
`i64`, so the ABI is byte-identical to the pre-113 synthesized seams.

Every C-ABI signature below fits the design-58 `@export` whitelist (fixed-width
ints, `Int`/`UInt`, `UnsafePointer`, `Void`/`Never`) — a runtime written in Saw
exports each body under its `__saw_rt_*` name.

---

## Allocation / output / panic

### `__saw_rt_alloc(size: word, align: word) -> i8*`
Global allocator. Returns a block of at least `size` bytes, or NULL on failure.
The hosted default is `malloc(size)`; `align` is currently ignored (malloc
guarantees `alignof(max_align_t)` >= 16, which covers every Saw allocation).
A runtime that honors alignment may use `align`.

### `__saw_rt_dealloc(ptr: i8*, size: word, align: word) -> void`
Free a block previously returned by `__saw_rt_alloc`. The hosted default is
`free(ptr)`; `size`/`align` are passed for allocators that need them.

### `__saw_rt_write(ptr: i8*, len: word) -> void`
The output primitive behind `print`. Writes `len` bytes from `ptr` to standard
output. The hosted default routes through C stdio (`fwrite(ptr,1,len,stdout)`
then `fflush(stdout)`) so that `print` output stays on the SAME buffered stream
as the still-`printf`-based `Float` path — interleaved int/float/string prints
keep program order and flush semantics. A runtime that replaces this MUST
preserve that ordering guarantee if the Float path still uses stdio.

### `__saw_rt_panic(ptr: i8*, len: word) -> ! (noreturn)`
The infallible-tier panic sink (design 19). Emits the `len`-byte message at
`ptr` (via `__saw_rt_write`) and does not return. The hosted default aborts
(`abort()`); a kernel decides policy (oops / reset / halt). Marked `noreturn`.

## Time

### `__saw_rt_sleep_ms(ms: word) -> void`
Park the current OS thread for `ms` milliseconds (behind `sleep(ms)` and the
executor's timed waits). A non-positive request returns at once. Hosted default:
`usleep(ms * 1000)`.

### `__saw_rt_clock_monotonic_nanos() -> Int64`
A monotonic clock as nanoseconds since an arbitrary epoch (behind
`Instant.now()`). Hosted default: `clock_gettime(CLOCK_MONOTONIC, &ts)` folded
to `ts.tv_sec*1e9 + ts.tv_nsec`. **OS-divergent:** the `CLOCK_MONOTONIC` id is 6
on macOS, 1 on Linux — this constant is host-runtime material.

### `__saw_rt_unix_timestamp_secs() -> Int64`
Wall clock as seconds since the Unix epoch. Hosted default:
`clock_gettime(CLOCK_REALTIME=0, &ts)` returning `ts.tv_sec`.

## errno family

Read the calling thread's `errno`, which lives behind `__error()` on macOS and
`__errno_location()` on Linux (**OS-divergent** accessor name = runtime
material). All errno VALUES below are OS-divergent and belong to the runtime.

### `__saw_rt_errno() -> Int`
The current `errno`, so `IoError` can carry the failing syscall's code
(design 84).

### `__saw_rt_errno_would_block() -> Int  (1/0)`
1 iff `errno` is `EAGAIN`/`EWOULDBLOCK` (35 macOS / 11 Linux) or `EINPROGRESS`
(36 / 115) — i.e. a nonblocking op that must park.

### `__saw_rt_errno_connect_state() -> Int  (0/1/2)`
Classify `errno` after a re-issued nonblocking `connect()` (design 90):
`0` = connected (`EISCONN` 56/106); `1` = still in progress (`EINPROGRESS`
36/115 or `EALREADY` 37/114); `2` = a real failure. Lets the cooperative
connect distinguish done from still-connecting and re-park on a spurious wake.

## Sockets

### `__saw_rt_set_nonblocking(fd: word) -> Int  (0/-1)`
Set `O_NONBLOCK` on `fd` (`fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) |
O_NONBLOCK)`). **OS-divergent:** `O_NONBLOCK` is `0x0004` on macOS, `0x0800` on
Linux (`F_GETFL=3`/`F_SETFL=4` on both). `fcntl` is variadic in C and MUST be
called with the flag as the variadic argument (an arm64 ABI requirement).

### `__saw_rt_sin_set_family(buf: i8*) -> void`
Stamp the OS-divergent prefix of a `struct sockaddr_in` at `buf`. This is the
ONLY part of `sockaddr_in` whose layout differs by OS; the rest (port, addr —
network-order data) is filled by the Saw `SockAddrIn` struct directly.
**OS-divergent:** macOS is `{ u8 sin_len = 16; u8 sin_family = AF_INET }`
(family at byte 1); Linux is `{ u16 sin_family = AF_INET }` (bytes 0–1, LE).
`AF_INET == 2` on both.

## Cooperative-scheduler fairness (design 89-c)

A backstop for the single-threaded cooperative scheduler: an io op that
completes WITHOUT parking charges a process-global budget; when it is exhausted
the io primitive force-yields once so a busy always-ready socket cannot
monopolize the executor. Op-count, not wall-clock (kernel-friendly,
deterministic). Default budget 128. The counter is process-global with
monotonic-atomic access (benign shared budget across MT workers).

### `__saw_rt_op_budget_tick() -> Int  (1/0)`
Decrement the budget. Returns `1` (and resets to the default) when it reaches
zero — the caller then force-yields — else `0`.

### `__saw_rt_op_budget_reset() -> void`
Restore the default budget (a genuine park already ceded, so the count resets).

## The IO reactor (designs 76 / 91 / 102)

A process-global readiness reactor: a **kqueue** fd on macOS, an **epoll** fd on
Linux, created lazily and race-safely (an atomic CAS publishes the fd; a loser
closes its spare). The kernel owns the interest set, so register/poll are each a
single syscall with no user-space fd array — this is why kqueue/epoll fits a
global reactor where `poll(2)` would not.

### `__saw_rt_reactor_register(fd: word, write: word, token: word) -> void`
Arm **one-shot** readiness interest on `fd` for read (`write==0`) or write
(`write!=0`). `token` is carried as the event's user-data
(`kevent.udata` / `epoll_event.data`) and is **the parked frame's `__wake`-word
ADDRESS** (design 91) — this is the precise-routing contract: a readiness event
carries the exact frame to wake, not a herd. One-shot (`EV_ONESHOT` /
`EPOLLONESHOT`) plus fd close both drop the registration, so a reused fd number
can never route a wake to a stale frame. epoll re-arms an already-known fd with
`EPOLL_CTL_MOD` on `EEXIST`.

Many frames on one fd: kqueue/epoll key the interest set by `(fd, filter)`, so
two frames waiting DIFFERENT directions on one fd are two independent
registrations, each precisely woken. Two frames on the SAME `(fd, direction)`
collapse to one kernel registration (last-writer-wins token); a belt-and-braces
re-verify keeps that safe. Concurrent same-direction waiters on one fd are not a
supported pattern.

### `__saw_rt_reactor_poll(timeout_ms: word) -> Int  (ready count)`
Block in `kevent`/`epoll_wait` up to `timeout_ms` (`< 0` = forever). For EACH
ready event, **LATCH its token word to 0 (ready)** — waking exactly the frame(s)
that registered for that `(fd, direction)`. The latch is a persistent word (not
an edge), so a poll that fires before the scheduler finished recording the park
is never lost: the next wake scan reads the latched word. A token of `0` is
skipped (the self-wake pipe registers with token 0, so it wakes no frame). A
negative return (EINTR) latches nothing. Also drains the self-wake pipe on
return so a level of readiness does not busy-fire the next poll.

### `__saw_rt_reactor_wake() -> void`
Write one byte to a process-global **self-wake pipe** whose read end
`__saw_rt_reactor_poll` registers each cycle (design 102 item 2). This makes a
blocked poll return promptly so a `cancel()` on an already-io-parked task is
observed — otherwise a task parked on a permanently-idle fd would never see the
cancel. Both pipe ends are nonblocking (a full pipe drops the byte harmlessly —
one pending byte already rouses; the drain never blocks). If the pipe is not up
yet (rare MT init race) the wake is skipped: the scheduler's re-check of
cancellation on any poll return, plus MT workers' bounded poll timeout, still
observe the cancel.

**Cancel-wake path (design 102):** a canceller calls `handle.cancel()` (or
writes a `cancel_addr`) → `__saw_rt_reactor_wake()` → the blocked poll returns →
the scheduler re-checks `cancelled()` and wakes the parked frame → it returns
`Err(IoError)` at its loop top. So a cancelled idle-fd wait no longer hangs,
while a non-cancelled sibling parked on another idle fd stays parked (precise, no
herd wake).

## Threads (pthread wrappers, design 21)

Thin wrappers so the stdlib never has to spell a NULL attr pointer at the Saw
level (Saw has no null-pointer literal). pthread symbols resolve from libSystem
(macOS) / libc+libpthread (Linux); the default clang link line pulls them in.

### `__saw_rt_pthread_create(tid: i8*, start: void*(*)(void*), arg: i8*) -> void`
`pthread_create((pthread_t*)tid, NULL, start, arg)`. `tid` points at the task
control block's 8-byte `pthread_t` slot; `start` is the spawn/offload trampoline
(a C-ABI `void*(void*)`); `arg` is its argument.

### `__saw_rt_pthread_join(tid: i8*) -> void`
Load the 8-byte `pthread_t` at `tid` and `pthread_join(t, NULL)`. `pthread_t` is
pointer-sized on macOS and glibc, passed by value.

### `__saw_rt_pthread_mutex_init_default(m: i8*) -> void`
`pthread_mutex_init(m, NULL)`. The Saw side reserves a conservative slot
(`pthread_mutex_t` is <= 64 bytes on the hosted targets) and inits within it.

### `__saw_rt_pthread_cond_init_default(c: i8*) -> void`
`pthread_cond_init(c, NULL)`. `pthread_cond_t` is 48 bytes on macOS and glibc;
std reserves 64.

## Blocking-extern offload (design 103)

A blocking FFI call inside a suspending task is offloaded to a thread-per-call
(v1) so the cooperative reactor thread never blocks; the task parks on the job's
self-pipe like any socket read. A job is a heap record `{ word fn, word arg,
word result, word done, i32 pipe_r, i32 pipe_w, word thread }`. Hazard
discipline: the offload thread touches ONLY its own job + the pipe write end; all
wake routing stays in the reactor. Single-owner throughout: `start` owns the
job → the thread fills it → `take` joins the thread (a full happens-before
barrier) then reads/closes/frees. The offload thunk `fn` is a C-ABI `word(word)`
(the design-58 whitelist restriction the coro transform enforces at the call
site).

### `__saw_rt_offload_start(fn: word, arg: word) -> Int  (job handle)`
Allocate a job, spawn a thread that runs `fn(arg)`, stores the result,
publishes `done` (atomic release), then writes one byte to the job pipe. Returns
the job record's address as an `Int` handle.

### `__saw_rt_offload_done(job: word) -> Int  (0/1)`
Acquire-load the published `done` flag.

### `__saw_rt_offload_pipe_fd(job: word) -> Int`
The job's readable pipe fd (the parked task registers this with the reactor).

### `__saw_rt_offload_take(job: word) -> Int  (result)`
Join the worker (full barrier → result visible), read the result, close the
pipe, free the job, and return the result.

### `__saw_rt_blocking_sleep(ms: word) -> Int  (ms)`
The reference blocking primitive: a real thread-blocking sleep that returns its
argument. The offload path and its tests exercise it via an
`extern "C" { blocking func __saw_rt_blocking_sleep(ms: Int) -> Int }`.

## Program arguments (design 81 CI rider)

The C entry `main(argc, argv)` stashes its two arguments into runtime storage at
startup; `Env.argc`/`Env.arg` read them through these accessors on every target
(this replaced the Apple-only `_NSGetArgc`/`_NSGetArgv` externs that failed to
link on Linux).

### `__saw_rt_get_argc() -> i32`
The `argc` main received.

### `__saw_rt_get_argv() -> i8**`
The `argv` main received.

---

## The four intended implementations

1. **host_macos** — kqueue reactor, libSystem pthreads, macOS errno/clock ids,
   `__error`, `__stdoutp`, `sin_len` sockaddr prefix.
2. **host_linux** — epoll reactor, glibc pthreads, Linux errno/clock ids,
   `__errno_location`, `stdout`, u16 sockaddr family.
3. **sos-hosted** — the SOS userland runtime (a sibling Saw runtime; kernel
   briefs).
4. **kernel / none** — the freestanding profile: the compiler emits these as
   external declarations only and links no runtime; a kernel supplies the bodies
   (a reactor built on interrupts/WFI, its own allocator, etc.). This is already
   the freestanding contract today.

## Authoring a runtime in Saw (design 113b)

The hosted runtime is **authored in Saw** under `sawc/rt/`, compiled with a
dedicated compile mode, plus one small C shim for the three bodies a Saw FFI gap
blocks. Layout:

```
sawc/rt/
  common/       OS-independent seam bodies (alloc, sleep, op-budget, pthread
                mutex/cond/join, offload)
  host_macos/   kqueue/macOS specifics (clocks, errno, sin_set_family)
  host_linux/   epoll/Linux specifics (clocks, errno, sin_set_family)
  shim.c        the three FFI-blocked bodies (below)
```

**The `--runtime-build` compile mode.** A runtime source is compiled with
`sawc <file>.saw --runtime-build`. Under it:

- `@export("__saw_rt_<name>")` is allowed for EXACTLY the frozen ABI set above —
  the compiler validates against the list it declares, so a misspelled / non-ABI
  `__saw_rt_*` export is a clean error naming the valid set. Every OTHER reserved
  name (`main`, `saw_*`, the `__saw_*` compiler-internal helpers) stays rejected,
  in this mode and out.
- The compiler emits the seams as external DECLARATIONS (never synthesized
  bodies); a module's own `@export` of a seam collapses into the declaration
  (the design-58 declaration/definition unify), so the runtime provides the body.
- The module is **sync-only** — every seam is an `@export` function, which the
  effect system already treats as a sync context, so a suspending seam body
  (`yield_now`, a blocking extern, a channel/TaskGroup op) is a clean error. A
  runtime sits BELOW the machinery that suspends.
- Only `builtin.saw` is loaded (no std): a runtime declares its own libc externs
  and uses only the core builtins (UnsafePointer/Atomic/Optional/…).
- Composes with the hosted target here; the freestanding profile (SOS) will
  author its own seams the same way.

The runtime objects are built + cached under `.build/rt/<key>/` (key = a hash of
every rt source + the target triple), flock-guarded for parallel builds, and
added to hosted link lines automatically (`sawc -v` lists them). A build failure
is a hard, named error. The freestanding profile links NO runtime — it EXTERNS
the seams for the kernel/environment to supply (verified by the
`freestanding_seams_extern_no_runtime` negative test).

**The `shim.c` exceptions.** Three bodies cannot be authored in Saw today; each
is a tracked language gap (a future design shrinks the shim to zero):

- `__saw_rt_write` / `__saw_rt_panic` — **DF-113a (no extern C global).** They
  route through libc's `stdout` FILE* (`fwrite` + `fflush`, keeping `print`
  ordered against the printf Float path). Saw cannot name an extern global.
- `__saw_rt_pthread_create` + the offload thread thunk — **DF-113b (no C
  function-pointer type).** Both pass/call a raw C function pointer (the start
  routine / the `long(long)` blocking extern). Saw's surface has no bare C
  function-pointer type (closures are fat pointers).
- `__saw_rt_set_nonblocking` — **DF-113c (no variadic extern).** It calls the
  variadic `fcntl(fd, F_SETFL, ...)` (an arm64 ABI requirement). Saw extern
  declarations have no `...`.

## Implementation status (design 113 / 113b)

- **Landed:** the ABI is FROZEN and renamed (both tiers). All seam bodies are
  relocated to Saw under `sawc/rt/` + the three-body `shim.c`, built + cached
  under `.build/rt/` and linked automatically for hosted builds — the IR
  synthesis is deleted — EXCEPT the **IO reactor** (`__saw_rt_reactor_register`
  / `_poll` / `_wake`), which stays compiler-synthesized: the reactor's poll
  needs a per-call, MT-safe stack event buffer (`kevent`/`epoll_event`[64]) that
  Saw cannot express today (no uninitialized locals, no `[expr; N]` array-repeat
  initializer), and register/poll/wake share the reactor's fd globals so they
  cannot be split from poll. Recorded as a DF-finding in `designs/todo.md`; the
  reactor graduates to Saw when that gap (or a per-call heap buffer decision)
  lands, riding a later brief.

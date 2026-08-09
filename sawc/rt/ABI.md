# The Saw runtime ABI (`__saw_rt_*`) — v2 (design 117)

This is the frozen contract between compiled Saw code and its host runtime.
The compiler DECLARES and CALLS these symbols; a linked runtime IMPLEMENTS
them. Freezing the set here is what lets a runtime be a **link-time swap**
(host_macos, host_linux, sos-hosted, kernel/none) instead of compiler surgery.

**Minimization principle (design 117).** The ABI was frozen at v1 by design 113;
this is the sanctioned v2 revision, made deliberately while the only
implementations are our two host runtimes. The target of the minimization is
**not** raw symbol count — it is the *floor of C-expressed and globals-coupled
surface*: hidden channels of state in the contract (the POSIX errno global) and
bodies that could not be written in Saw. So v2 DELETES the errno accessors (ops
carry their own status), makes the reactor an INSTANCE rather than process-global
seam state, and shrinks the thread surface to spawn/join — while ADDING
status-carrying OS ops where an operation crosses the boundary. More symbols,
less hidden coupling; the whole reactor now lives in Saw and the C floor is only
the three DF-113a/b/c shim bodies.

Two symbol tiers exist (design 113); only the first is this ABI:

- **`__saw_rt_*` — the runtime ABI (THIS document).** Implemented by a linked
  runtime. The compiler emits them as external declarations under every
  profile. In the hosted profile a runtime object is linked automatically; in
  the freestanding profile the environment (kernel/bootloader/RTOS) supplies
  them.
- **`__saw_*` — compiler-internal synthesized helpers (NOT this ABI).** Emitted
  as IR bodies by codegen, carry no host-OS knowledge, and a runtime must NOT
  provide them: string retain/release/alloc/from_bytes/len (`__saw_string_*`),
  the Arc/Channel atomic helpers (`__saw_atomic_*`), and integer print
  (`__saw_print_int` / `__saw_print_uint`). (Design 118 stage 3 RETIRED the compiler's last reactor
  helper — the `__saw_reactor` instance getter — into the Saw executor's
  `__saw_host_reactor()`; codegen no longer emits any reactor-instance code.)

Widths follow design 47. `word` below = the platform `Int`/`UInt` width
(pointer-width: 64-bit on x86-64/aarch64, 32-bit on riscv32). The stdlib types
the seams that carry sizes/counts/fds/handles/tokens as `Int`, so they are
`word`-wide; the clock seams return `Int64` explicitly. On the 64-bit hosted
targets `word` is `i64`, so the ABI is byte-identical to the pre-113 synthesized
seams.

Every C-ABI signature below fits the design-58 `@export` whitelist (fixed-width
ints, `Int`/`UInt`, `UnsafePointer`, `Void`/`Never`) — a runtime written in Saw
exports each body under its `__saw_rt_*` name.

**The signatures below are MACHINE-CHECKED (design 149).** `runtime_abi.py`
parses them out of this file, and a compile that builds a runtime — `sawc
--runtime-build` for `sawc/rt/`, or `--runtime-provider` for a package declaring
`[package] runtime = true` — checks every exported seam against the signature
written here. A mismatch is a compile error naming this document. Arity and
machine WIDTH are what is compared: `word`, `ptr` and every `i8*`/`i8**`/`word*`
spelling are one pointer-width class (the C ABI does not distinguish them at this
width, and this document uses `word` and `ptr` for the same handles), while
`Int64` and `i32` are their own, because those differ from `word` on a 32-bit
target. So editing a signature here changes what implementations are accepted —
which is the point, and the reason an edit is an ABI change.

`make abidoc` checks the other direction: that this document describes exactly
the frozen symbol set, with no seam left undescribed and none described that the
compiler would refuse to let anyone export.

---

## Allocation / output / panic

### `__saw_rt_alloc(size: word, align: word) -> i8*`
Global allocator. Returns a block of at least `size` bytes, or NULL on failure.
The hosted default is `malloc(size)`; `align` is currently ignored (malloc
guarantees `alignof(max_align_t)` >= 16). A runtime that honors alignment may use
`align`.

### `__saw_rt_dealloc(ptr: i8*, size: word, align: word) -> void`
Free a block previously returned by `__saw_rt_alloc`. Hosted default: `free(ptr)`.

### `__saw_rt_alloc_deny_after(allow: word) -> void`
**Hosted test facility (design 123), OPTIONAL for a runtime to provide.**
Permits `allow` more allocations and refuses every one after (returning NULL); a
NEGATIVE `allow` disarms the limit. This is how the three-tier
allocation-failure policy reaches the OOM path of a type that takes no allocator
type parameter (`String`, `StringBuilder`, `Data`, `Arc`, `Mutex`, `Channel`).
Denial is a MODE, armed and disarmed. Design 137 dropped the second parameter, a
bounded window that re-armed the allocator by itself: it existed because a Saw
`panic(msg)` assembled its message into a fresh allocation, so under blanket
denial every panic reported "string allocation failed" rather than the one the
failing method raised. Panic messages are assembled in stack scratch now, so a
test can deny everything and still read the real message; one that wants to keep
running afterward calls `deny_after(-1)`. Nothing in std calls it (a test
declares the `extern` itself), so a freestanding runtime may omit the symbol.

### `__saw_rt_write(ptr: i8*, len: word) -> void`
The output primitive behind `print`. Writes `len` bytes from `ptr` to standard
output. The hosted default routes through C stdio (`fwrite`+`fflush`) so `print`
output stays ordered against the still-`printf`-based `Float` path. A runtime that
replaces this MUST preserve that ordering if the Float path still uses stdio.

### `__saw_rt_panic(ptr: i8*, len: word) -> ! (noreturn)`
The infallible-tier panic sink (design 19). Emits the message at `ptr` (via
`__saw_rt_write`) and does not return. Hosted default aborts; a kernel decides
policy. Marked `noreturn`.

## Time

### `__saw_rt_sleep_ns(ns: i64) -> void`
Park the current OS thread for `ns` nanoseconds, read as UNSIGNED — the whole
u64 range is a valid request. Zero returns at once.

Hosted default: a loop of `usleep` calls, one whole second per chunk plus a
remainder rounded UP to a whole microsecond. A park is a floor, so returning
early is the one wrong answer; over-sleeping by under a microsecond is not.
Chunking is what makes the whole range honest: `usleep` takes a 32-bit
microsecond count, so the v1 `__saw_rt_sleep_ms` seam this REPLACES (design 180)
multiplied and narrowed in one step and wrapped a request past about 35 minutes
into a short nap (DF-170a).

Not interruptible: it returns when the span has elapsed and nothing can cut it
short. The executor therefore parks in the reactor, not here, whenever it may
need to abandon the wait — `__saw_rt_reactor_poll` takes the same deadline as
its timeout and the design-102 self-wake pipe can rouse it. This seam is the
no-reactor fallback and the body behind a `sleep` reached outside any executor.

### `__saw_rt_clock_monotonic_nanos() -> Int64`
A monotonic clock as nanoseconds since an arbitrary epoch (behind `Instant.now()`).
Hosted default: `clock_gettime(CLOCK_MONOTONIC, &ts)`. **OS-divergent:** the
`CLOCK_MONOTONIC` id is 6 on macOS, 1 on Linux.

### `__saw_rt_unix_timestamp_secs() -> Int64`
Wall clock as seconds since the Unix epoch. Hosted default:
`clock_gettime(CLOCK_REALTIME=0, &ts)` returning `ts.tv_sec`.

## Errors — the portable `SysError` tag space (design 117)

v2 DELETES the three v1 errno accessors (`__saw_rt_errno` /
`__saw_rt_errno_would_block` / `__saw_rt_errno_connect_state`). Reading a
thread-local errno global *after the fact* is a POSIX-ism: fragile (anything
clobbers errno between op and read — v1's `tcp_listen` did exactly that, calling
`close()` between a failed `bind()` and the caller's errno read) and
unimplementable on SOS, whose ratified syscall ABI is a `(status, value)` pair
with a small SysError tag (sos/spec.md §5.7).

**`SysError`** is a small fixed-ABI tag space. `0` = ok; a failing operation
returns the NEGATED tag (the Linux-kernel `-errno` convention), so one word
carries success/count (`>= 0`) or `-tag` (`< 0`) — no aggregate return, mapping
1:1 onto the SOS `(status, value)` register pair. The set is deliberately
convergent with the SOS SysError enum, so hosted and SOS runtimes share one error
vocabulary.

| tag | name                | mapped hosted errno(s)                     |
|-----|---------------------|--------------------------------------------|
| 0   | Ok                  | (success — never returned as `-0`)         |
| 1   | WouldBlock          | EAGAIN / EWOULDBLOCK                        |
| 2   | InProgress          | EINPROGRESS / EALREADY                      |
| 3   | IsConnected         | EISCONN                                    |
| 4   | Interrupted         | EINTR (also std cooperative cancellation)  |
| 5   | ConnReset           | ECONNRESET                                 |
| 6   | ConnRefused         | ECONNREFUSED                               |
| 7   | ConnAborted         | ECONNABORTED                               |
| 8   | BrokenPipe          | EPIPE                                      |
| 9   | NotConnected        | ENOTCONN                                   |
| 10  | NotFound            | ENOENT                                     |
| 11  | PermissionDenied    | EACCES / EPERM                             |
| 12  | Exists              | EEXIST                                     |
| 13  | AddrInUse           | EADDRINUSE                                 |
| 14  | Invalid             | EINVAL                                     |
| 15  | Exhausted           | EMFILE / ENFILE / ENOMEM / ENOSPC          |
| 16  | Other               | any other errno                            |

`IsConnected` (3) and `InProgress` (2) exist so a re-issued nonblocking
`connect()` can be classified (done / still-connecting / failed) without an errno
accessor. **Pin deviation (recorded):** the brief suggested `Other(errno)` carry
the raw hosted errno for diagnostics. A single negated-word return cannot carry a
tag AND a raw errno, and SOS has no errno to preserve, so `Other` is tagless;
diagnostic richness is instead achieved by mapping the common failure errnos to
named tags (so `Other` is rare). std wraps the tag into `IoError` at the Saw
level (`IoError.of(syscall, tag)`); the observable behavior and the *shape* of
the error text are unchanged — the parenthetical is now the tag's human name
(`"io error: mkdir failed (not found)"`) rather than a raw errno number (no test
observed the number).

### `__saw_rt_last_syserror() -> word`
Read the calling thread's errno and return the portable SysError TAG. This is the
single host-divergent errno→tag mapping (errno lives behind `__error()` on macOS,
`__errno_location()` on Linux; the errno VALUES diverge). It is a runtime-INTERNAL
seam: the status-carrying OS ops below call it IMMEDIATELY after a failing syscall
(nothing runs between, so errno is never clobbered), and std NEVER calls it after
a bare libc op. Not an errno accessor across the std boundary — std sees tags.

## Sockets — OS-divergent helpers

### `__saw_rt_set_nonblocking(fd: word) -> word  (0/-1)`
Set `O_NONBLOCK` on `fd`. **OS-divergent** flag value; C shim (DF-113c — variadic
`fcntl`). Returns 0 on success, -1 on the `F_GETFL` failure.

### `__saw_rt_sin_set_family(buf: i8*) -> void`
Stamp the OS-divergent prefix of a `struct sockaddr_in` at `buf` — the ONLY part
whose layout differs by OS. macOS: `{ u8 sin_len=16; u8 sin_family=AF_INET }`;
Linux: `{ u16 sin_family=AF_INET }` (LE). `AF_INET==2` on both.

## Status-carrying network ops (design 117)

Each does its syscall(s) and returns `>= 0` on success/count or `-tag` on failure.
OS-INDEPENDENT bodies (identical libc calls on both hosts; only the errno→tag
mapping and `sin_set_family` diverge). The sockaddr is built internally; the errno
is captured with `__saw_rt_last_syserror()` right after the failing syscall.

### `__saw_rt_tcp_listen(port: word) -> word`
Socket+set_nonblocking+bind+listen on 127.0.0.1:`port` (0 = ephemeral). Returns
the listen fd or `-tag`. errno is captured BEFORE the cleanup `close()`.

### `__saw_rt_tcp_local_port(fd: word) -> word`
`getsockname` → the bound local port (resolves an ephemeral 0).

### `__saw_rt_tcp_accept(listen_fd: word) -> word`
Nonblocking accept → a nonblocking conn fd, or `-tag` (`-WouldBlock` when no
client is waiting).

### `__saw_rt_tcp_connect_start(addr_be: word, port: word) -> word`
Start a nonblocking connect to `addr_be`:`port` → the connecting fd (`>= 0`,
including the EINPROGRESS "wait for writable" case) or `-tag` on a real failure.
`addr_be` is the IPv4 address as it sits in `sockaddr_in.sin_addr` — network
byte order — which is what both std's dotted-quad parser and
`__saw_rt_resolve_ipv4` produce.

It took only the port until design 184 and dialled a hardcoded 127.0.0.1, which
is why `TcpStream.connect` ignored its `host` argument and reported success on
the wrong peer (DF-181d).

### `__saw_rt_tcp_connect_check(fd: word, addr_be: word, port: word) -> word`
Re-issue the nonblocking connect to learn the true state (design 90). `0` =
connected; `-InProgress` = still connecting (re-park); `-tag` = a real failure.
`addr_be` must be the address `connect_start` was given — re-issuing against a
different peer asks a different question.

### `__saw_rt_resolve_ipv4(host: i8*, out: u32*, max: word) -> word`
**BLOCKING — the first seam in this document that says so, and it says so
because it is (design 184).** Resolve the NUL-terminated hostname at `host` to
IPv4 addresses, writing at most `max` of them to `out` in NETWORK byte order,
ready to drop into `sockaddr_in.sin_addr`. Returns the COUNT written (`0` = the
resolver succeeded and offered no IPv4 address, which is not a failure) or
`-tag`. `max <= 0` is `-Invalid`.

**The blocking contract.** This call is UNBOUNDED. The hosted body is
`getaddrinfo(3)` with `AF_INET`/`SOCK_STREAM` hints, which may read
`/etc/hosts`, ask mDNS, query LDAP or wait out a DNS timeout — microseconds to
tens of seconds, decided by configuration this process does not control. It is
therefore the one seam std declares `extern blocking`: every call is OFFLOADED
to a worker thread by design 183's machinery and the calling task PARKS, so a
resolution in flight never stops a sibling and never wedges the cooperative
executor. A runtime implementing this seam may take as long as it needs; what it
may NOT do is assume a caller is willing to wait on the calling thread.

Two consequences for an implementer. The body itself is ORDINARY SYNC CODE — the
offload happens on the std side, so `--runtime-build`'s sync-only discipline
applies here exactly as to every other seam. And both pointers obey design 183's
rule: they address the parked task's frame or the heap, so the worker thread may
still be reading and writing through them for the whole call, cancellation
included (`take` joins the worker before the task takes its cancel path).

`EAI_SYSTEM` is reported through errno, so the hosted body maps it with
`__saw_rt_last_syserror()`; `EAI_AGAIN` — a TEMPORARY resolver failure — maps to
`WouldBlock`, the tag whose errno (`EAGAIN`) means the same thing. A name with no
address is `-NotFound`.

### `__saw_rt_tcp_read(fd: word, buf: i8*, len: word) -> word`
Nonblocking read → byte count (0 = EOF) or `-tag` (`-WouldBlock` on would-block).

### `__saw_rt_tcp_write(fd: word, buf: i8*, len: word) -> word`
Nonblocking write → bytes written (may be `< len`) or `-tag`.

## Status-carrying filesystem / environment ops (design 117)

Each does its libc call and returns `0` on success or `-tag` on failure (errno
captured right after). C-string args.

- `__saw_rt_fs_unlink(path: i8*) -> word`
- `__saw_rt_fs_rename(old: i8*, new: i8*) -> word`
- `__saw_rt_fs_mkdir(path: i8*, mode: word) -> word`
- `__saw_rt_fs_rmdir(path: i8*) -> word`
- `__saw_rt_fs_chdir(path: i8*) -> word`
- `__saw_rt_fs_dirent_name(entry: i8*) -> i8*` — **OS-divergent** (design 122).
  The NUL-terminated name inside a `struct dirent` returned by `readdir`: the
  `d_name` offset is 21 on macOS and 19 on Linux, and it is the ONLY divergent
  part of a readdir walk, so std keeps `opendir`/`readdir`/`closedir` and only
  the projection is a seam. `entry` is non-NULL (std checks readdir's result).
- `__saw_rt_env_set(name: i8*, value: i8*, overwrite: word) -> word`
- `__saw_rt_env_unset(name: i8*) -> word`

## Status-carrying file I/O (design 132 unit G — additive)

The same convention applied to the read/write surface. These were bare libc
calls in std, where the failure CAUSE was unreadable — `__saw_rt_last_syserror`
is runtime-internal and must not be called after a bare libc op — so
`File.open`/`read`/`write` could only answer `None`. Each returns its natural
non-negative result or `-tag`.

- `__saw_rt_fs_open(path: i8*, mode: word, perm: word) -> word` — the fd, or
  `-tag`. `mode` is a **PORTABLE OPEN MODE**, not a POSIX flag word: `0` read an
  existing file, `1` write from the beginning creating-or-emptying, `2` append
  creating-if-absent. An unrecognized mode is `-Invalid`. `perm` is the creation
  permission (`0644` from std), read by the kernel only when the mode creates.

  It carried the raw `O_*` flag word until design 155, and could not: those bits
  are per-host C macros, and std spelled them as the LINUX decimal values for
  BOTH hosts. On macOS that silently made `File.create` omit `O_TRUNC` (a short
  write over a long file left the old tail in place) and `File.open_append` omit
  `O_CREAT` while gaining `O_TRUNC`. A runtime translates the mode into its own
  host's bits — the hosted one in `shim.c`, which is the only place that can see
  `<fcntl.h>`.
- `__saw_rt_fs_read(fd: word, buf: i8*, count: word) -> word` — bytes read
  (`0` = end of file), or `-tag`.
- `__saw_rt_fs_write(fd: word, buf: i8*, count: word) -> word` — bytes written,
  or `-tag`.
- `__saw_rt_fs_lseek(fd: word, offset: word, whence: word) -> word` — the new
  absolute offset, or `-tag`. A negative result is the only failure signal, as
  it is for `lseek(2)` itself.
- `__saw_rt_fs_opendir(path: i8*, status_out: word*) -> i8*` — the `DIR*`, or
  NULL. A `DIR*` cannot fold a tag into its return, so the status goes to the
  out-parameter: `0` on success, the POSITIVE tag on failure. The pointer comes
  back raw because an exported return may not be optional (design 113b); std's
  `extern` declaration does the `?`-wrapping. `readdir`/`closedir` stay bare —
  readdir's end-of-stream is not an error, and closedir's status is not
  actionable.

## Process spawn (design 122 — additive)

Seams added after v2 froze, for the same reason the fs/env ops exist: the
operation crosses the boundary and its status has to come back with it. They
replace `std.process.Command`'s old `system()`/`popen()` shell command line —
which re-split every argument and executed anything after a `;` — with a real
argv spawn. **No shell is involved at any point**, on any implementation: one
`argv` element is one argument, whatever bytes it holds.

A **job** is an opaque heap record owning the child's pid and, when capturing,
the read end of its stdout pipe. Single-owner discipline, exactly like the
offload family: `spawn` creates the job, the reap destroys it. The hosted bodies
are `fork` + `execvp` (`rt/common/proc.saw`, OS-independent); between fork and
exec the child touches only async-signal-safe calls
(`close`/`dup2`/`execvp`/`_exit`).

**The child WAIT is zero-thread (design 182).** The v1 shape had two seams that
blocked the calling thread — a `read` on a blocking pipe and a `waitpid` with no
options — and design 181 measured what that costs: a sibling task's first tick
landed only when the child exited, because the one cooperative executor thread was
inside the wait. The wait half is fixed. `try_wait` reaps with `WNOHANG` and
answers `-WouldBlock` while the child lives, and a caller that has to wait asks
for a DESCRIPTOR — `wait_fd` — and parks it on the reactor with the ordinary
read-interest registration. A runtime that cannot hand out a wait descriptor is
still correct: `try_wait` alone is a poll, slower but never wedging anything.

`__saw_rt_proc_wait` and `read_stdout` still block, and are documented as such
below. They are the drain half of DF-181a, blocked on DF-182e rather than on
anything in this contract.

### `__saw_rt_proc_spawn(path: i8*, argv: i8**, flags: word) -> word`
Spawn `path` with the NULL-terminated `argv` array (`argv[0]` is the program
name, as `execvp` expects). Returns the job handle (`> 0`) or `-tag`. A child
that cannot exec exits **127** (the POSIX "command not found" convention), which
std maps back to a launch failure.

`flags` is a REDIRECTION BIT SET, one bit per stream (design 155 widened what
design 122 called `capture`; `0` and `1` still mean what they always meant, so
nothing that predates the bits changes):

| bit | value | meaning |
|-----|-------|---------|
| 0   | 1     | the child's stdout goes into a pipe the job owns (`read_stdout` drains it) |
| 1   | 2     | the child's stderr goes wherever its stdout goes — into the pipe with bit 0, and plain `2>&1` without it |

Bit 1 exists because a spawner that captures a child's output but INHERITS its
diagnostics cannot keep its own output clean, and had no way to say so: a tool
that runs hundreds of children it expects some of to fail (the design-155 irdet
port over a corpus with negative tests in it) would interleave their error text
with its own report. Discarding stderr and capturing it SEPARATELY are both
still unexpressible — see DF-155a.

### `__saw_rt_proc_spawn_env(path: i8*, argv: i8**, envp: i8**, flags: word) -> word`
The same spawn with environment OVERRIDES (design 155 — additive; the seam
`std.process.Command.env(name:value:)` needs, and the reason it is a seam at all
is that only the runtime can reach the process environment). `envp` is a
NULL-terminated `NAME=VALUE` array; the child gets the spawning process's
environment **with each of those names set to the given value and everything
else inherited** — not a replacement environment. Names are unique (std replaces
rather than appends), so no precedence question reaches the seam. Returns the
job handle (`> 0`) or `-tag`, and `-Exhausted` when the merged array cannot be
allocated.

The merge runs in the PARENT, before the fork; the child does nothing but point
`environ` at the result before `execvp`. That ordering is the contract, not an
implementation detail: a spawning process may be multi-threaded, and the window
between fork and exec may only touch async-signal-safe calls, which a merge that
allocates is not. Pointing `environ` at a pre-built array is how a portable
`execvpe` is written, and it is what keeps the PATH search (`execvp` takes the
new image's environment from `environ`).

### `__saw_rt_proc_read_stdout(job: word, buf: i8*, len: word) -> word`
Read up to `len` bytes of the child's captured stdout: the byte count (`0` =
EOF, and `0` immediately for a job spawned without capture) or `-tag`. **BLOCKS**
until the child writes or closes.

### `__saw_rt_proc_wait(job: word) -> word`
Reap the child, close the capture pipe, free the job, and return the **RAW POSIX
wait status** (`>= 0`) or `-tag`. Raw, not an exit code: std decodes it, because
the signal bits are what distinguish a crashed child from a clean exit 0 (design
59 DF2). Retries on `Interrupted`. **BLOCKS** for the child's whole lifetime.

The v1 reap, and the last blocking seam in the family. `Command.run` parks on
`wait_fd` + `try_wait` instead; only `Command.output` still calls this, because
its drain cannot become a suspension yet (DF-182e). A new runtime should treat it
as deprecated and implement it as a `try_wait` loop around its own park.

### `__saw_rt_proc_wait_fd(job: word) -> word`
A descriptor that becomes **readable once the child has exited**, or `-tag`.
Acquired on the first ask (a spawn nobody waits on costs no descriptor), cached
in the job, and owned by the job. This is what turns the child wait into an
ordinary reactor park: register it for read interest, and the poll that would
have blocked in `waitpid` blocks in `kevent`/`epoll_wait` alongside every other
parked task.

`-tag` is not a failure of the wait — it means only that this child cannot be
waited for by descriptor right now, and the caller falls back to polling
`try_wait`. The common reason is benign: on macOS the child became a zombie
between the caller's poll and this call, and there is no exit left to register
for (see `__saw_rt_proc_exit_fd`).

### `__saw_rt_proc_exit_fd(pid: word) -> word`
**OS-DIVERGENT** — the one host-specific piece of the wait, and the seam
`wait_fd` is built on. A descriptor readable once process `pid` has exited, or
`-tag`.

- **Linux** (`rt/host_linux/proc_wait.saw`): `pidfd_open(pid, 0)`. epoll reports
  a pidfd readable when the process exits; a zombie is fine (the descriptor opens
  and is readable at once).
- **macOS** (`rt/host_macos/proc_wait.saw`): a dedicated `kqueue()` armed with
  `EVFILT_PROC`/`NOTE_EXIT` on `pid`. A kqueue IS a descriptor, and another kqueue
  reports it readable as soon as it has an event pending — so the reactor watches
  it with a plain `EVFILT_READ` registration and needs no new filter. `EV_ADD`
  without `EV_ONESHOT`/`EV_CLEAR` keeps the event pending, so the descriptor stays
  readable from the exit onward and a re-park fires again instead of hanging.
  Attaching to a process that is ALREADY a zombie fails with `ESRCH`, which is
  reported as `-tag`: there is no exit left to wait for, and the caller's next
  `try_wait` reaps immediately.

### `__saw_rt_proc_try_wait(job: word) -> word`
Reap the child **if it has already exited**: the **RAW POSIX wait status**
(`>= 0`), `-WouldBlock` while it is still running, or `-tag`. Raw, not an exit
code: std decodes it, because the signal bits are what distinguish a crashed
child from a clean exit 0 (design 59 DF2). Retries on `Interrupted`.

The job is **destroyed** — descriptors closed, record freed — on every answer but
`-WouldBlock`, which leaves it intact so the caller can park and ask again.

### `__saw_rt_proc_release(job: word) -> void`
Abandon the job without waiting: one `WNOHANG` reap (so a child that already
exited does not linger as a zombie), then close its descriptors and free the
record. The cancellation exit — design 102 cancels the WAIT, not the CHILD, so a
child still running keeps running and this process never collects its status.

## Cooperative-scheduler fairness (design 89-c)

A backstop for the single-threaded cooperative scheduler: an io op that completes
WITHOUT parking charges a process-global budget; when it is exhausted the io
primitive force-yields once so a busy always-ready socket cannot monopolize the
executor. Op-count, not wall-clock. Default budget 128.

### `__saw_rt_op_budget_tick() -> word  (1/0)`
Decrement the budget. Returns `1` (and resets to the default) when it reaches zero
— the caller then force-yields — else `0`.

### `__saw_rt_op_budget_reset() -> void`
Restore the default budget (a genuine park already ceded).

## The IO reactor — INSTANCE-based (designs 76 / 91 / 102 / 117)

v2 makes the reactor an opaque INSTANCE created through the ABI, not process-global
seam state. `__saw_rt_reactor_create()` allocates an instance owning its
kqueue/epoll fd AND its self-wake pipe; register/poll/wake/destroy take the
instance. This dissolves DF-113d (the poll event buffer was a per-call MT-safe
STACK array Saw could not express): the reactor now lives in Saw
(`rt/host_macos/reactor.saw` kqueue, `rt/host_linux/reactor.saw` epoll) and each
poll heap-allocates its own event buffer.

**The process-global singleton is EXECUTOR policy, not runtime state.** _Design 118
stage 3 moved this fully into Saw:_ the singleton is `__saw_host_reactor()`
(std/taskgroup.saw) — a lazy, race-safe getter over an `Atomic<Int>` static
(`reactor_create` on first use, published via `compare_exchange`; a loser
`reactor_destroy`s its spare) that returns the `SystemReactor` value conforming to
the Saw `Reactor` trait. The executor threads the instance EXPLICITLY (each seam
call passes `self.instance`), so the reactor seams are plain externs and there is no
compiler-injected instance. (Through design 117 this was the compiler-synthesized
`__saw_reactor()` getter + a per-call-site instance injection; both are retired.)

**Concurrency (design 117 pin — match v1 observable semantics exactly).** MT
TaskGroups poll from several worker threads concurrently. v1's poll used a
per-call STACK event buffer, so concurrent polls were independent. v2 preserves
this EXACTLY with a per-call HEAP event buffer (`malloc`/`free` inside `poll`) —
no shared buffer, no poll mutex. The design-91 token contract, one-shot rearm, and
the design-102 self-wake pipe are byte-identical to v1 (the net suite is the
regression harness).

### `__saw_rt_reactor_create() -> ptr`
Create a reactor instance: a kqueue (macOS) / epoll (Linux) fd + a nonblocking
self-wake pipe. Returns an opaque instance pointer (as a `word`).

### `__saw_rt_reactor_register(r: ptr, fd: word, write: word, token: word) -> void`
Arm **one-shot** readiness interest on `fd` in `r` for read (`write==0`) or write
(`write!=0`). `token` is carried as the event's user-data and is **the parked
frame's `__wake`-word ADDRESS** (design 91) — the precise-routing contract. One-shot
(`EV_ONESHOT`/`EPOLLONESHOT`) plus fd close drop the registration; epoll re-arms a
known fd with `EPOLL_CTL_MOD` on `EEXIST`.

### `__saw_rt_reactor_unregister(r: ptr, fd: word, write: word) -> void`
Drop readiness interest on `fd` in `r` for read (`write==0`) or write
(`write!=0`) — `EV_DELETE` on kqueue, `EPOLL_CTL_DEL` on epoll. **Idempotent:**
an already-fired one-shot, a closed fd, and an fd that was never armed all
return `ENOENT`/`EBADF`, which is the state the caller asked for, so the result
is ignored. (Linux keeps ONE interest per `(epfd, fd)` covering both directions,
so `write` is accepted for uniformity and unused there.)

Added by design 147 (DF-134a), the first widening of the frozen set since v2.
The token a registration carries is the parked frame's `__wake`-word ADDRESS, so
a registration that outlives its frame is a dangling write, not a leak — and
since design 134 the frame box is released at task completion, which makes the
window real. Two callers: std.net's park loops call it on their cancellation
exit (the one path that leaves a loop with an event still armed), and a
coroutine frame's synthesized `__release` calls it for the last `(fd, dir)` the
frame armed, ahead of its own field drops so the fd is still open and still the
frame's. A frame whose body contains no `io_wait` arms nothing and gets neither
the bookkeeping fields nor the call.

### `__saw_rt_reactor_poll(r: ptr, timeout_ms: word) -> word  (ready count)`
Block in `kevent`/`epoll_wait` on `r` up to `timeout_ms` (`< 0` = forever). For
EACH ready event, **LATCH its token word to 0 (ready)** — waking exactly the
frame(s) that registered for that `(fd, direction)`. The latch is a persistent word
(not an edge), so a poll that fires before the scheduler finished recording the
park is never lost. Token `0` is skipped (the self-wake pipe registers with token
0). Drains the self-wake pipe on return so a level of readiness does not busy-fire.
The event buffer is a per-call heap allocation (concurrency pin above).

### `__saw_rt_reactor_wake(r: ptr) -> void`
Write one byte to `r`'s self-wake pipe so a blocked `poll` returns promptly — the
design-102 cancel-wake path (a `cancel()` on an already-io-parked task rouses the
poll; the scheduler re-checks `cancelled()` and wakes the parked frame, which
returns `Err(IoError)` at its loop top). A non-cancelled sibling parked on another
idle fd stays parked (precise, no herd wake).

### `__saw_rt_reactor_destroy(r: ptr) -> void`
Close the instance's fd + pipe ends and free it. (Called by the singleton getter
on the CAS-loser's spare; the process-lifetime instance itself is never destroyed.)

## Threads — spawn/join (designs 21 / 117)

v2 consolidates the thread surface to spawn/join (v1's `__saw_rt_pthread_create` /
`__saw_rt_pthread_join` are gone). The DF-113b fn-pointer thunk stays in `shim.c`.
pthread symbols resolve from libSystem (macOS) / libc+libpthread (Linux).

### `__saw_rt_thread_spawn(entry: void*(*)(void*), env: i8*) -> word  (handle)`
`pthread_create(&t, NULL, entry, env)`; RETURN the OS thread handle (`pthread_t`,
pointer-sized on both hosts) as a word. Spawn codegen stores the returned handle
into the task control block's first 8-byte slot (byte-identical control-block
layout to the v1 `pthread_create`-writes-the-slot form). C shim (DF-113b — a raw C
function pointer).

### `__saw_rt_thread_join(handle: word) -> void`
`pthread_join((pthread_t)handle, NULL)` — join by the handle VALUE. Saw body
(`rt/common/pthread.saw`).

### `__saw_rt_pthread_mutex_init_default(m: i8*) -> void`
`pthread_mutex_init(m, NULL)`. Saw reserves a conservative slot (<= 64 bytes).

### `__saw_rt_pthread_cond_init_default(c: i8*) -> void`
`pthread_cond_init(c, NULL)`. `pthread_cond_t` is 48 bytes on macOS/glibc; std
reserves 64. (Full Thread traitification is design 118; these init seams stay.)

## Blocking-extern offload (design 103, widened by design 183)

A blocking FFI call inside a suspending task is offloaded to a thread-per-call so
the cooperative reactor thread never blocks; the task parks on the job's self-pipe
like any socket read. A job is a heap record; single-owner discipline throughout.
The offload thunk `fn` is a C-ABI `word(word)`.

That one word is a pointer to the call's ARGUMENT SLOTS — one `word`-sized slot
per parameter, in declaration order — and `fn` is a thunk the COMPILER synthesizes
for each offloaded extern, which reads the slots back at their declared types and
makes the real call. So the extern's own C ABI is the compiler's ordinary
extern-call lowering, this seam family knows nothing about arity, and every
signature the C-ABI whitelist admits (fixed-width integers, Int/UInt, Float,
UnsafePointer, plus Void/Never returns) can be offloaded.

**Lifetime rule for the runtime**: the worker reads the slots at a time `start`
cannot bound, so `start` COPIES them into storage the job owns and `take` frees
that storage after the join. What a pointer slot POINTS AT is the caller's
obligation (LANGUAGE_SPEC, "Blocking externs and the offload"): it must live in
the suspended frame or the heap, both of which outlive the park.

### `__saw_rt_offload_start(fn: word, argp: ptr, argc: word) -> word  (job handle)`
Copy `argc` argument slots from `argp` into the job, then spawn a thread that runs
`fn(<the job's copy>)`, stores the result, publishes `done` (atomic release), and
writes one byte to the job pipe. `argc == 0` copies nothing and passes a null
pointer. Returns the job record's address as a handle.

### `__saw_rt_offload_done(job: word) -> word  (0/1)`
Acquire-load the published `done` flag.

### `__saw_rt_offload_pipe_fd(job: word) -> word`
The job's readable pipe fd (the parked task registers this with the reactor).

### `__saw_rt_offload_take(job: word) -> word  (result)`
Join the worker (full barrier), read the result, close the pipe, free the argument
slots and the job. One result word; a Void/Never extern's caller ignores it. The
join is unconditional — a cancelled task still takes, which is what makes freeing
the slots safe.

### `__saw_rt_blocking_sleep(ms: word) -> word  (ms)`
The reference blocking primitive: a real thread-blocking sleep returning its
argument, exercised by the offload tests via a `blocking func` extern.

## Program arguments (design 81 CI rider)

The C entry `main(argc, argv)` stashes its two arguments into runtime storage at
startup; `Env.argc`/`Env.arg` read them through these accessors on every target.

### `__saw_rt_get_argc() -> i32`
The `argc` main received.

### `__saw_rt_get_argv() -> i8**`
The `argv` main received.

---

## v1 → v2 deprecation table (design 117)

| v1 symbol                        | v2                                                        |
|----------------------------------|-----------------------------------------------------------|
| `__saw_rt_errno`                 | **removed** — ops carry status; diagnostics via the tag   |
| `__saw_rt_errno_would_block`     | **removed** — folded into the status-carrying ops         |
| `__saw_rt_errno_connect_state`   | **removed** — folded into `__saw_rt_tcp_connect_check`     |
| —                                | **new** `__saw_rt_last_syserror` (runtime-internal mapper) |
| —                                | **new** `__saw_rt_tcp_{listen,local_port,accept,connect_start,connect_check,read,write}` |
| —                                | **new** `__saw_rt_fs_{unlink,rename,mkdir,rmdir,chdir}`    |
| —                                | **new** `__saw_rt_env_{set,unset}`                        |
| `__saw_rt_reactor_register(fd,write,token)` | signature +instance: `(r,fd,write,token)`      |
| `__saw_rt_reactor_poll(timeout)` | signature +instance: `(r,timeout)`                        |
| `__saw_rt_reactor_wake()`        | signature +instance: `(r)`                                |
| —                                | **new** `__saw_rt_reactor_create`, `__saw_rt_reactor_destroy` |
| —                                | **new (design 147)** `__saw_rt_reactor_unregister` — DF-134a |
| `__saw_rt_pthread_create(tid,start,arg)` | **renamed** `__saw_rt_thread_spawn(entry,env) -> handle` |
| `__saw_rt_pthread_join(tid)`     | **renamed** `__saw_rt_thread_join(handle)` (value handle) |

Everything else (alloc/dealloc/write/panic, sleep, clocks, set_nonblocking,
sin_set_family, op-budget, mutex/cond init, the offload family, get_argc/argv) is
unchanged from v1.

Additions since v2, each purely additive (no existing symbol changed):

| design | added                                                          |
|--------|----------------------------------------------------------------|
| 122    | `__saw_rt_fs_dirent_name`                                      |
| 122    | `__saw_rt_proc_{spawn,read_stdout,wait}`                       |
| 132    | `__saw_rt_fs_{open,read,write,lseek,opendir}`                  |
| 182    | `__saw_rt_proc_{exit_fd,wait_fd,try_wait,release}` — the zero-thread child wait. `__saw_rt_proc_wait` stays, deprecated, for the one caller left |

## The compiler → executor entry-point boundary (design 118, stage 1: map + carve)

This section pins the SECOND boundary design 118 works against: not the
`__saw_rt_*` runtime ABI above (Saw ↔ host OS), but the seam between
**compiler-synthesized IR** (coroutine frames + the transform) and the
**cooperative executor**. Design 118 relocates the executor fully into Saw
behind `Reactor`/`Thread` traits; this map is the doc commit that fixes the
boundary shape BEFORE any code moves (per the staging plan). It is descriptive
of the code as it stands at stage-1 start plus the carve it proposes; the
symbols marked NEW do not exist yet.

### Three tiers, not two

The design-113 intro names two symbol tiers. There is in fact a third, and
design 118 is about making it a clean, small, Saw-authored boundary:

1. **`__saw_rt_*`** — the runtime ABI (Saw ↔ host OS), documented above.
2. **`__saw_*` compiler-internal helpers** — string/atomic/box/print glue and
   the `__saw_reactor` instance getter. Emitted as IR bodies by codegen.
3. **The executor** — the cooperative scheduler, run queue, park/wake, MT
   engine. **Most of it is ALREADY Saw** (designs 89/75/91/102 put it in
   `std/taskgroup.saw` + `std/task.saw`); design 118 relocates the last
   synthesized pieces and routes reactor/thread access through traits.

### What the compiler still synthesizes (stage-1 inventory)

Emitted as Saw AST by `coro_transform.py` or as IR by `codegen/`:

- **Frame layout + transform** (KEPT synthesized — a non-goal to move): per
  suspending fn/method a `__Frame_<f>` struct with fields, in order,
  `__state:Int`, `__wake:Int`, `__io_tok:Int`, `__cancel:Bool`,
  `__result:R?` (omitted for a `Void` body); the `resume() -> __Poll`
  state machine; the `__wake_reason()->Int` and `__is_cancelled()->Bool`
  read accessors; the `Resumable` conformance (vtable for `Box<any Resumable>`
  erasure). A suspension is just `__wake=<reason>; __state=<n>; return Pending`
  — no executor call. Wake reason: `>0` sleep NANOSECONDS (design 180), `0`
  yield/ready, `-1`
  (`IO_PARK_WAKE`) io-parked.
- **Entry executor** — a suspending `main` is replaced by a synthesized `main`:
  - no spawns → `_make_entry_executor`: an INLINE drive loop over main's own
    stack frame that on `Pending` calls `__saw_exec_sleep_ns(ns)` (wake>0) or
    `__saw_rt_reactor_poll(-1)` (wake<0) or resumes at once (wake==0).
  - spawns → `_make_ambient_entry_executor`: box main erased, call
    `__saw_exec_run_root(box)` (Saw).
- **Drivers** `__saw_drive_<f>` / `__saw_drive_steps_<f>` (design 44/45,
  test-only) — an INLINE resume loop over a stack frame, same park inline as
  the single-frame entry executor, then reads `__f.__result`.
- **Spawn helper** `__spawn_<f>(&group, args) -> TaskHandle<T>|VoidTaskHandle`
  — builds the frame, `Box<any Resumable>.make`, captures `__result`/`__cancel`
  slot pointers, calls `group.__enqueue(move box)`, returns the handle.
- **io park lowering** (inside `resume`, both the `io_wait` primitive and the
  design-103 offload park loop) — emits a direct
  `__saw_rt_reactor_register(fd, dir, self.__io_tok)` then suspends `IO_PARK_WAKE`.
- **Offload lowering** — `let x = slow(a, b)` (blocking extern) desugars to
  `__saw_blk_start` + an `io_wait` park loop on the job pipe + `__saw_blk_take`;
  codegen lowers `__saw_blk_*` to the `__saw_rt_offload_*` seams. `start` also
  emits `__saw_blk_thunk$<extern>` (internal, one per offloaded extern, design
  183): `word(word)`, reads the argument slots back at their declared types and
  makes the real C call.
- **`spawn { } -> Task<T>` thread engine** (`codegen/calls.py::_generate_spawn`)
  — control block `{tid, env, result}`, a per-site `i8*(i8*)` trampoline, and a
  `__saw_rt_thread_spawn(tramp, cb)` launch (the SPAWN half stays codegen — the raw
  C trampoline pointer is DF-113b). Task join/deinit (`std/task.saw`, Saw) join
  through the design-118 stage-4 `Thread` trait / `PosixThread` over
  `__saw_rt_thread_join`.
- ~~**`__saw_reactor()`** reactor-instance getter + injection~~ — RETIRED (design
  118 stage 3). The process-global reactor singleton is now the Saw
  `__saw_host_reactor()` (lazy CAS over an `Atomic<Int>` static in
  std/taskgroup.saw) returning the `SystemReactor` `Reactor` impl; the reactor seams
  are plain externs the executor calls at full arity.
- **Intrinsic lowerings** (`codegen/calls.py`): `sleep`→`__saw_rt_sleep_ns` (the
  `Duration` argument's nanosecond field, extracted in IR — design 180);
  `io_wait` outside a frame → `__saw_exec_io_register` + `__saw_exec_park(-1)`
  (design 118 stage 2/3, routed through the trait); `cancelled()`→false,
  `yield_now`/`__saw_io_park`→no-op outside a frame; `__saw_box_data`,
  `__saw_forget`.

### What is ALREADY Saw (the executor proper)

`std/taskgroup.saw` + `std/task.saw`: the `TaskGroup` run queue (parallel
`tasks`/`cells`/`done`/`remaining`/`active`/`gen`/`pin` vectors + the `free` slot
list, design 134), the ambient scheduler
`__saw_exec_run(term_group, term_slot, term_gen)` + its sweep helpers, `__enqueue`,
`__saw_exec_run_root`, the MT fork-join drain `__drain_mt`/`__saw_exec_worker`,
`TaskHandle`/`VoidTaskHandle` `join`/`cancel`/`cancel_addr`, `yield_now`, and
the `Task<T>` join/deinit. These call the reactor externs
(`__saw_rt_reactor_poll`, `__saw_rt_reactor_wake`) and `__saw_exec_sleep_ns`
DIRECTLY today — those direct calls are exactly what stage 3 routes through the
`Reactor` trait.

### The proposed entry-point boundary (spawn / enqueue / drive / park / wake / join)

The minimal set of Saw-authored executor entry points the synthesized IR calls
by name. The compiler emits calls; the Saw executor implements them. After the
carve, synthesized IR contains NO scheduler-loop or park-policy body — only
frame code + these calls.

| concern  | entry point (shape)                                   | status |
|----------|-------------------------------------------------------|--------|
| enqueue  | `__enqueue(&var TaskGroup, box: Box<any Resumable>, cell: Box<any __TaskCell>) -> Int` | exists (Saw) |
| drive    | `__saw_exec_run_root(box: Box<any Resumable>)`            | exists (Saw) |
| join     | `__saw_exec_run(term_group: Int, term_slot: Int, term_gen: Int)` | exists (Saw) |
| drive/park (single-frame) | `__saw_exec_park(wake: Int)`             | stage 2 ✓ — carved the `_make_entry_executor` `Pending` body into this one Saw call (wake>0 → sleep; wake<0 → reactor poll -1; 0 → return). The trivial resume-until-done loop STAYS synthesized (lead pin: the design-45 allocation-free fast path is contract, and post-carve the loop carries zero policy). |
| park (io) | `__saw_exec_io_register(fd: Int, dir: Int, token: Int)`  | stage 2 ✓ — Saw wrapper the `io_wait`/offload park lowerings + the outside-frame `io_wait` codegen path call instead of the raw `__saw_rt_reactor_register` extern |
| wake     | `__saw_exec_reactor_wake()`                                | stage 2 ✓ — Saw wrapper over `__saw_rt_reactor_wake` (`TaskHandle`/`VoidTaskHandle.cancel` call it) |
| sleep    | `__saw_exec_sleep_ns(ns: Int)`                             | stage 2 ✓ — promoted from a codegen intrinsic to a real Saw fn over `__saw_rt_sleep_ns`. Design 180 moved the unit to nanoseconds (the executor's whole deadline bookkeeping follows `Duration`) and moved every ABANDONABLE park off it onto the reactor poll. |

`spawn` itself stays the synthesized `__spawn_<f>` helper (frame-shaped, cannot
be generic-erased) whose executor touches are `__enqueue` and the `__gen_at`
read that completes the handle's `(slot, generation)` identity. The `Task<T>`
thread engine's only executor touch is `__saw_rt_thread_spawn`/`_join`
(stage 4 routes these through a `Thread` surface).

**Why these:** every reactor/timer touch by synthesized IR OR by the existing
Saw executor is funnelled through `__saw_exec_park` / `__saw_exec_io_register` /
`__saw_exec_reactor_wake` / `__saw_exec_sleep_ns` and the poll inside `__saw_exec_run`. Stage
3 then swaps ONLY those bodies to dispatch through a `Reactor` trait object held
as the executor's singleton (replacing the compiler-injected `__saw_reactor()`
instance), without touching a single synthesized call site.

### Stage carve plan (each lands suite-green)

- **Stage 2 (ST core) — LANDED:** added `__saw_exec_park`/`__saw_exec_sleep_ns` (Saw);
  `_make_entry_executor`'s `Pending` arm now calls `__saw_exec_park(__f.__wake)`;
  the resume-until-done loop STAYS synthesized (lead pin — do NOT box main onto
  `__saw_exec_run_root`; the design-45 allocation-free fast path is part of the
  byte-identical behavior contract, and after the carve the residual loop carries
  zero policy). A monomorphized generic `__saw_exec_run_single(box)` that removes
  even the loop (no box, per-frame instantiation) is the DEFERRED option if the
  synthesized loop is ever unwanted. REFINEMENT of the stage-1 map: the
  `__saw_drive_*` drivers have an EMPTY `Pending` body (design-44 test-only
  busy-resume — they never park), so there is no park body to carve there; leaving
  them untouched is what preserves byte-identical behavior (adding a park would be
  a behavior change, not a relocation). The reactor is still consumed via the
  direct externs (funnelled through the stage-2 `__saw_exec_*` wrappers).
- **Stage 3 (reactor trait) — LANDED:** the `Reactor` trait (`register`/`poll`/
  `wake`, token = the parked frame's `__wake`-word address, design 91) is defined in
  std/taskgroup.saw, with `SystemReactor { instance: Int }` conforming over the
  design-117 `__saw_rt_reactor_*` instance seams. Every executor reactor touch —
  `__saw_exec_io_register`, `__saw_exec_reactor_wake`, `__saw_exec_park`'s poll, the
  `__saw_exec_run` sweep poll, and the MT-worker poll — now goes through the trait
  via `__saw_host_reactor()`, a Saw lazy-CAS singleton over an `Atomic<Int>` static
  (create-on-first-use, publish via `compare_exchange`, loser destroys its spare).
  The compiler-synthesized `__saw_reactor()` getter AND its per-seam instance
  injection are RETIRED — the executor threads the instance explicitly, so the
  reactor seams are now plain externs the Saw executor calls at full arity.
  DEVIATIONS (recorded, rationale in taskgroup.saw): (1) ONE `SystemReactor` wrapper,
  not two `KqueueReactor`/`EpollReactor` — the host divergence (kqueue vs epoll)
  already lives in the rt/ bodies behind the seams, so two Saw wrappers would be
  identical duplication. (2) STATIC dispatch through the `Reactor` conformance, not a
  singleton `any Reactor` existential — a per-call `Box<any Reactor>` would add an
  allocation (behavior-profile change) with no benefit, since the reactor impl is
  selected at LINK/compile time, not runtime; the trait is the source-level contract
  the SOS runtime implements as its own conforming type + `__saw_host_reactor()`.
  IO_WAIT-GATING RESOLUTION (deferred design-114 question): `io_wait` stays a
  std-INTERNAL suspension intrinsic — it is not prelude, and the raw net primitives
  it partners (`tcp_try_read`/`net_buffer`/…) require an explicit
  `import std.net.{…}`, so it is already gated out of ordinary user code. The
  white-box reactor tests (`net_precise_*`, the `io_wait` echo examples) REMAIN the
  reactor's contract regression suite in examples/ (the only test harness) — they
  now exercise exactly the `(fd, direction, token)` semantics `SystemReactor` wraps,
  so they ARE the `Reactor`-contract unit tests. No harder gating was added (that
  would need a new visibility mechanism — out of scope; a follow-up if wanted).
- **Stage 4 (threads/MT/offload) — LANDED:** the `Thread` trait (`join`) +
  `struct PosixThread { handle: Int }` conforming over `__saw_rt_thread_join` are
  defined in std/task.saw; `Task<T>.join`/`deinit` join through the trait, and the
  MT `TaskGroup` drain (`__drain_mt`) joins its workers as `Task`s, so both the
  `spawn{}`/`Task` engine and the MT engine go through the Thread surface. The SPAWN
  half stays the compiler-emitted `__saw_rt_thread_spawn` primitive — spawn codegen
  (`_generate_spawn`) builds the task control block + a raw C-ABI trampoline pointer
  (DF-113b, a value Saw cannot express), the thread analog of the coroutine frame
  layout the compiler keeps. Offload PARKING already goes through the reactor (the
  `io_wait` on the job pipe, stage 2/3); the offload worker's own thread spawn lives
  in the rt/ runtime (rt/common/offload.saw), not the executor, so it needs no
  executor-side Thread routing. DEVIATION (same as stage 3): STATIC dispatch through
  the `Thread` conformance, not an `any Thread` existential (no per-join box; the
  impl is link/compile-time selected). Send checks + design-103 semantics unchanged
  (byte-identical; the MT/offload/Send regression tests are the ratchet).

## The four intended implementations

1. **host_macos** — kqueue reactor, libSystem pthreads, macOS errno/clock ids,
   `__error`, `__stdoutp`, `sin_len` sockaddr prefix.
2. **host_linux** — epoll reactor, glibc pthreads, Linux errno/clock ids,
   `__errno_location`, `stdout`, u16 sockaddr family.
3. **sos-hosted** — the SOS userland runtime (a sibling Saw runtime; kernel briefs).
   The SysError tag space and the negated-word status convention are its native
   `(status, value)` shape.
4. **kernel / none** — the freestanding profile: the compiler emits these as
   external declarations only and links no runtime; a kernel supplies the bodies.

## Authoring a runtime in Saw (design 113b / 117)

The hosted runtime is **authored in Saw** under `sawc/rt/`, compiled with
`--runtime-build`, plus one small C shim for the three bodies a Saw FFI gap
blocks. Layout:

```
sawc/rt/
  common/       OS-independent bodies: alloc/sleep/op-budget, pthread mutex/cond
                init + thread_join, offload, process spawn (proc.saw — fork/exec
                argv spawn, WNOHANG reap), and the status-carrying OS ops
                (os_ops.saw — tcp_* + fs_* + env_*)
  host_macos/   kqueue reactor + macOS specifics (clock, net_os = errno→tag +
                sin_set_family, dirent = the d_name offset, proc_wait = the
                EVFILT_PROC child-exit descriptor)
  host_linux/   epoll reactor + Linux specifics (proc_wait = pidfd_open)
  shim.c        the three FFI-blocked bodies (below)
```

**The `--runtime-build` compile mode.** `@export("__saw_rt_<name>")` is allowed for
EXACTLY the frozen ABI set (the compiler validates against `sawc/runtime_abi.py`);
a misspelled/non-ABI `__saw_rt_*` export is a clean error naming the valid set.
The module is sync-only; only `builtin.saw` is loaded. Objects are built + cached
under `.build/rt/<key>/` (key = hash of every rt source + the triple), auto-linked
for hosted builds (`sawc -v` lists them). The freestanding profile links NO runtime
(verified by `freestanding_seams_extern_no_runtime`).

**The C floor — `shim.c` (design 117: unchanged from v1; the last non-Saw bodies).**
Each is a tracked language gap; a future design shrinks the shim to zero:

- `__saw_rt_write` / `__saw_rt_panic` — **DF-113a (no extern C global).** They
  route through libc's `stdout` FILE* (`fwrite`+`fflush`, keeping `print` ordered
  against the printf Float path). Saw cannot name an extern global.
- `__saw_rt_thread_spawn` + the offload thread thunk — **DF-113b (no C
  function-pointer type).** Both pass/call a raw C function pointer.
- `__saw_rt_set_nonblocking` — **DF-113c (no variadic extern).** It calls the
  variadic `fcntl(fd, F_SETFL, ...)` (an arm64 ABI requirement).

## Implementation status (design 117)

- **Landed:** ABI v2. The reactor is instance-based and RELOCATED TO SAW (the last
  synthesized seam is gone — the compiler now synthesizes only the `__saw_reactor`
  process-global getter, which is executor policy, not a seam body). The errno
  accessors are deleted; every errno-reading OS op is a status-carrying runtime
  function returning the portable SysError tag. The thread surface is spawn/join.
  The C floor is exactly the three DF-113a/b/c shim bodies. Full compiler suite,
  blade bootstrap, and sos_runner green on macOS; the Linux runtime variant is
  written against the documented glibc/epoll ABI and verified in CI.

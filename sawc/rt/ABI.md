# The Saw runtime ABI (`__saw_rt_*`) — v2 (design 117)

This is the frozen contract between compiled Saw code and its host runtime.
The compiler declares and calls these symbols; a linked runtime implements
them. Freezing the set here is what lets a runtime be a **link-time swap**
(host_macos, host_linux, sos-hosted, kernel/none) instead of compiler surgery.

**Minimization principle (v2, design 117).** The target is not raw symbol
count but the surface expressed in C or coupled through globals: hidden
channels of state in the contract (the POSIX errno global) and bodies that
cannot be written in Saw. So v2 has no errno accessors (ops carry their own
status), makes the reactor an instance rather than process-global seam state,
and reduces the v1 thread surface to spawn/join, while adding status-carrying
OS ops where an operation crosses the boundary. More symbols, less hidden
coupling. The reactor is written in Saw; C is left for the bodies a Saw FFI gap
blocks (`shim.c`, listed under "Authoring a runtime in Saw").

Two symbol tiers exist (design 113); only the first is this ABI:

- **`__saw_rt_*` — the runtime ABI (this document).** Implemented by a linked
  runtime. The compiler emits them as external declarations under every
  profile. In the hosted profile a runtime object is linked automatically; in
  the freestanding profile the environment (kernel/bootloader/RTOS) supplies
  them. (`__saw_rt_get_argc`/`_get_argv` are the exception; see "Program
  arguments".)
- **`__saw_*` — compiler-internal synthesized helpers (not this ABI).** Emitted
  as IR bodies by codegen, they carry no host-OS knowledge, and a runtime must
  not provide them: string retain/release/alloc/from_bytes/len
  (`__saw_string_*`), the atomic helpers (`__saw_atomic_*`), and integer print
  (`__saw_print_int` / `__saw_print_uint`). The process-wide reactor instance
  is not a compiler helper: it is the executor's `__saw_host_reactor()` in
  std/taskgroup.saw, and codegen emits no reactor-instance code.

Widths follow design 47. `word` below = the platform `Int`/`UInt` width
(pointer-width: 64-bit on x86-64/aarch64, 32-bit on riscv32). The stdlib types
the seams that carry sizes/counts/fds/handles/tokens as `Int`, so they are
`word`-wide; the clock seams return `Int64` explicitly. On the 64-bit hosted
targets `word` is `i64`.

Every C-ABI signature below fits the design-58 `@export` whitelist (fixed-width
ints, `Int`/`UInt`, `UnsafePointer`, `Void`/`Never`) — a runtime written in Saw
exports each body under its `__saw_rt_*` name.

**The signatures below are machine-checked (design 149).** `runtime_abi.py`
parses them out of this file, and a compile that builds a runtime — `sawc
--runtime-build` for `sawc/rt/`, or `--runtime-provider` for a package declaring
`[package] runtime = true` — checks every exported seam against the signature
written here. A mismatch is a compile error naming this document. Arity and
machine width are what is compared: `word`, `ptr` and every `i8*`/`i8**`/`word*`
spelling are one pointer-width class (the C ABI does not distinguish them at this
width, and this document uses `word` and `ptr` for the same handles), while
`Int64` and `i32` are their own, because those differ from `word` on a 32-bit
target. So editing a signature here changes what implementations are accepted,
which is why an edit is an ABI change.

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
**Hosted test facility (design 123), optional for a runtime to provide.**
Permits `allow` more allocations and refuses every one after (returning NULL); a
negative `allow` disarms the limit. This is how a test reaches the OOM path of a
type that takes no allocator type parameter (`String`, `StringBuilder`, `Data`,
`Arc`, `Channel`). Denial is a mode, armed and disarmed; it does not re-arm
itself. A test that denies everything still reads the failing method's real
panic message, because panic messages are assembled in stack scratch rather
than allocated; one that wants to keep running afterward calls
`deny_after(-1)`. Nothing in std calls it (a test declares the `extern`
itself), so a freestanding runtime may omit the symbol.

### `__saw_rt_write(ptr: i8*, len: word) -> void`
The output primitive behind `print`. Writes `len` bytes from `ptr` to standard
output. The hosted default writes through C stdio (`fwrite`, then `fflush`), so
each call's bytes are flushed before it returns.

### `__saw_rt_panic(ptr: i8*, len: word) -> ! (noreturn)`
The panic sink. Emits the message at `ptr` (via `__saw_rt_write`) and does not
return. Hosted default aborts; a kernel decides policy. Marked `noreturn`.

## Time

### `__saw_rt_sleep_ns(ns: i64) -> void`
Park the current OS thread for `ns` nanoseconds, read as unsigned: the whole
u64 range is a valid request. Zero returns at once.

Hosted default: a clock-corrected loop of `usleep` calls, at most one second
per call, each rounded up to a whole microsecond. A park is a floor, so
returning early is the one wrong answer; over-sleeping by under a microsecond
is not. Chunking is what makes the whole range honest: `usleep` takes a 32-bit
microsecond count. (This seam replaces v1's `__saw_rt_sleep_ms`; see the change
table.)

Not interruptible: it returns when the span has elapsed and nothing can cut it
short. The executor therefore parks in the reactor, not here, whenever it may
need to abandon the wait: `__saw_rt_reactor_poll` takes the same deadline as
its timeout and `__saw_rt_reactor_wake` can rouse it. This seam is the body
behind a park that never needs abandoning and behind a `sleep` reached outside
any executor.

### `__saw_rt_clock_monotonic_nanos() -> Int64`
A monotonic clock as nanoseconds since an arbitrary epoch (behind `Instant.now()`).
Hosted default: `clock_gettime(CLOCK_MONOTONIC, &ts)`. **OS-divergent:** the
`CLOCK_MONOTONIC` id is 6 on macOS, 1 on Linux.

### `__saw_rt_unix_timestamp_secs() -> Int64`
Wall clock as seconds since the Unix epoch. Hosted default:
`clock_gettime(CLOCK_REALTIME=0, &ts)` returning `ts.tv_sec`.

## Errors — the portable `SysError` tag space (design 117)

v2 has no errno accessors (v1's three are in the migration table). Reading a
thread-local errno after the fact is fragile (anything that runs between the
op and the read can overwrite errno) and unimplementable on SOS, whose syscall
ABI is a `(status, value)` pair with a small SysError tag (SOS spec §5.7).

**`SysError`** is a small fixed-ABI tag space. `0` = ok; a failing operation
returns the negated tag (the Linux-kernel `-errno` convention), so one word
carries success/count (`>= 0`) or `-tag` (`< 0`), with no aggregate return,
mapping 1:1 onto the SOS `(status, value)` register pair. The set is
convergent with the SOS SysError enum, so hosted and SOS runtimes share one
error vocabulary.

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
| 17  | HostUnreachable     | EHOSTUNREACH                               |
| 18  | NetUnreachable      | ENETUNREACH                                |
| 19  | TimedOut            | ETIMEDOUT                                  |
| 20  | HostDown            | EHOSTDOWN                                  |
| 21  | NetDown             | ENETDOWN                                   |

`IsConnected` (3) and `InProgress` (2) exist so a re-issued nonblocking
`connect()` can be classified (done / still connecting / failed) without an
errno accessor.

**The status word carries no errno.** A single negated-word return cannot
carry a tag and a raw errno, and SOS has no errno to preserve, so a failing op
returns only the tag, and `Other` carries nothing extra. Diagnostic detail
comes from mapping the common failure errnos to named tags, so `Other` is rare,
and from the separate `__saw_rt_last_raw_code` seam below. std wraps the tag
into `IoError` (`IoError.of(syscall:tag:)`), whose text names the kind
(`"io error: mkdir failed (not found)"`).

**Adding tags.** Tags 17-21 are the failures that can only happen off loopback
(DF-215a). Widening this table is additive, not an ABI change: no existing tag
is renumbered (`Other` keeps 16, which is why 17-21 sit after it rather than
beside their neighbours), and no seam signature moves, so `runtime_abi.py`'s
arity/width check and `make abidoc`'s symbol-set check are unaffected. A
runtime that never returns 17-21 is still correct, and a consumer that does not
know a tag degrades to a catch-all: std turns a tag into an `IoErrorKind`
through `IoErrorKind.of(tag:)`, which answers `Unknown` for a tag it does not
know. Reusing or renumbering a tag would be an ABI change; a new tag takes the
next free number. The SOS `SosStatus` enum is a separate contract (SOS spec
§5.7) and is unaffected.

### `__saw_rt_last_syserror() -> word`
Read the calling thread's errno and return the portable SysError tag. This is the
single host-divergent errno→tag mapping (errno lives behind `__error()` on macOS,
`__errno_location()` on Linux; the errno values diverge). It is a runtime-internal
seam: the status-carrying OS ops below call it immediately after a failing syscall
(nothing runs between, so errno is not overwritten), and std never calls it after
a bare libc op. Not an errno accessor across the std boundary: std sees tags.

It also stamps the raw code the next seam hands back. That stamp is part of this
seam's contract, not an implementation detail: a runtime whose classifier
forgets it answers a stale number.

### `__saw_rt_last_raw_code() -> word`
The raw platform error code behind this thread's most recent
`__saw_rt_last_syserror()` classification: the hosted errno itself, not a tag.
`0` where the platform has none, and `0` on a thread that has classified
nothing.

This seam is consistent with "The status word carries no errno" above
(design 234):

- *The status word still carries only the tag.* A failing op still returns one
  negated word holding a tag, so the `(status, value)` correspondence with the
  SOS syscall ABI is untouched. This is a separate symbol, and adding it moved
  no signature.
- *std still never reads errno after the fact.* The value is captured inside
  the runtime, in the same call that classifies, and this seam hands back what
  was already captured; nothing that runs between the failing op and the read
  can overwrite it.

Classification is lossy by design (EACCES and EPERM are both
`PermissionDenied`), so `IoError` carries the portable kind and this raw
number, and a log can name the real code. The tag table is still the portable
half and still grows as described above.

**Per thread.** errno is per-thread, MT TaskGroups classify on several threads at
once, and a process-global slot would hand one thread's refusal to another. Both
hosted bodies use pthread thread-specific data, which is what
`rt/common/op_budget.saw` uses for the same reason (Saw has no thread-local
storage).

**Freshness is the caller's obligation.** The value is valid immediately after
a failing op returned `-tag`, on the same thread. A tag the runtime synthesizes
without consulting errno leaves the slot alone (`-Invalid` for an unrecognized
open mode, `-NotFound` for a name the resolver answered with no IPv4 address),
so a caller pairing one of those with a raw code must supply `0` itself. std
does: `IoError.of(syscall:tag:)` reads this seam and is used only where a
runtime op just classified, while the synthesized paths build their error
through `IoError.of(syscall:kind:)`, whose `code` is `0`. The blocking
`__saw_rt_resolve_ipv4` is on the synthesized side for a second reason: it runs
on an offload worker thread (design 183), so its classification is not on the
calling thread's slot at all.

**SOS / freestanding.** A SOS or kernel runtime answers its native status word,
which on SOS coincides numerically with the SysError tag (the SOS syscall ABI's
status half is that same tag space), so an SOS runtime need store nothing extra,
and `code` reads back as the number `kind` was built from. A freestanding runtime with no
status of its own answers `0` ("`0` where the platform has none").

## Sockets — OS-divergent helpers

### `__saw_rt_set_nonblocking(fd: word) -> word  (0/-1)`
Set `O_NONBLOCK` on `fd`. **OS-divergent** flag value; C shim (DF-113c: variadic
`fcntl`). Returns 0 on success, -1 on the `F_GETFL` failure.

### `__saw_rt_sin_set_family(buf: i8*) -> void`
Stamp the OS-divergent prefix of a `struct sockaddr_in` at `buf`, the only part
whose layout differs by OS. macOS: `{ u8 sin_len=16; u8 sin_family=AF_INET }`;
Linux: `{ u16 sin_family=AF_INET }` (LE). `AF_INET==2` on both.

### Runtime-internal socket helpers (design 272)
Not `__saw_rt_*` and not part of the frozen seam set: these are how
`rt/common/os_ops.saw` stays OS-independent, the same arrangement
`__saw_epoll_event_size` uses. A runtime provider supplies them for its own
host, and nothing outside `rt/` may call them.

They live in `shim.c`, for the reason `__saw_open_flags` does: every value here
is a C macro whose number differs by host, and C is the only language in the
build that can read it. Writing them into the Saw runtime would mean hardcoding
`SOL_SOCKET` as `0xffff` on one host and `1` on the other and hoping every
future platform agreed; asking the headers cannot drift.

`__saw_sockopt_level(option) -> word` / `__saw_sockopt_name(option) -> word`
map a portable option tag to this host's `(level, name)`, or `-1` for an option
this host lacks.

`__saw_socket_suppress_sigpipe(fd) -> void` and
`__saw_socket_send_flags() -> word` are the two halves of one contract: **a
write to a socket whose peer has gone reports `EPIPE` rather than raising
SIGPIPE.** Linux gets this per send (`MSG_NOSIGNAL`); macOS sets
`SO_NOSIGPIPE` on each socket and sends with flags `0`. The macOS
`setsockopt` result is ignored: if a kernel refused it, that socket would still
work but could raise SIGPIPE on a dead peer. Every socket the runtime creates
(listener, accepted connection, dialled connection) gets the suppression, and
`__saw_rt_tcp_write` passes the flags.

This is per socket rather than the process-wide `SIG_IGN` many runtimes
install at startup. An ignored disposition is inherited across `execve`, and
`rt/common/proc.saw` does not reset dispositions before `execvp`, so a
process-wide ignore would be handed to every child a Saw program spawns,
including shells and pipelines it did not write. Pipes keep their behaviour;
only sockets change. The user-visible consequence is that a write to a hung-up
client is an ordinary `Err(IoError)` with kind `BrokenPipe`.

### Runtime-internal signal helpers (design 272)
Also `shim.c`, also outside the frozen set, for the same reason: signal numbers
are per-host macros (`SIGUSR1` is 30 on macOS and 10 on Linux).

`__saw_signal_number(tag) -> word` maps a portable tag to this host's number,
`-1` for a signal this host lacks. The tag space:

| Tag | Signal          | C name     |
|-----|-----------------|------------|
| 1   | Terminate       | `SIGTERM`  |
| 2   | Interrupt       | `SIGINT`   |
| 3   | Hangup          | `SIGHUP`   |
| 4   | Quit            | `SIGQUIT`  |
| 5   | User1           | `SIGUSR1`  |
| 6   | User2           | `SIGUSR2`  |
| 7   | WindowChanged   | `SIGWINCH` |

`__saw_signal_watch(signo) -> word` installs a handler and returns the watch
pipe's read end, or `-1` (bad signal) / `-2` (already watched) / `-3` (the pipe
or the handler could not be installed). `__saw_signal_unwatch(signo)` restores
the disposition and drains. `__saw_signal_raise(signo) -> word` sends the signal
to this process. `__saw_signal_drain(signo) -> word` takes the deliveries
belonging to the current watch off that signal's pipe: a positive count, or
`-1` for nothing pending.

**Three invariants this family rests on** (design 272 records the race each one
closes):

1. **The watch transaction is serialized.** Initialization, the already-watched
   check, descriptor publication and `sigaction` installation are one
   transaction under a mutex. Unsynchronized, two callers could both acquire one
   signal and each save the other's handler as the "previous" disposition. The
   handler takes no lock and must not: it can interrupt a thread already inside
   that mutex.
2. **Nothing a handler can reach is ever reclaimed.** A signal's pipe is created
   at its first watch and lives for the process; `unwatch` closes nothing.
   Restoring a disposition stops future handler entries but not one already past
   its descriptor load, and closing the pipe under such a handler frees the
   descriptor number for reuse, so the delayed write would land in an unrelated
   resource. Costs at most two descriptors per watched signal.

3. **The handler takes exactly one snapshot, and the tag does not recur.** A
   single word per signal packs the generation (bits 63..1) and the watched flag
   (bit 0); the handler derives both from one atomic acquire load and stamps its
   record with the generation it saw. The drain validates against the word it
   loads itself.

   Both halves are needed, and neither substitutes for the other. With separate
   loads, a handler paused after observing `watched` could read a later watch's
   generation and label its old delivery current. A short tag recurs (a 7-bit
   one after 128 watch cycles). One snapshot fixes the first; 63 monotonic
   bits, never reset, fix the second: recurrence would need 2^63 (~9.2e18)
   complete watch cycles while one handler stays paused, which at a nanosecond
   each is over 290 years.

   The handler stamps and the reader validates, never the other way round: a
   handler that validated before writing would have a window between the two.
   Records are eight bytes, far under `PIPE_BUF`, so a pipe write is atomic and
   records never interleave or split.

A runtime provider replacing these must keep all three invariants; they are
contract, not implementation detail.

**No reactor seam.** The handler writes an 8-byte record to a pipe, and a pipe
read end is an ordinary readable descriptor that
`__saw_rt_reactor_register(r, fd, write, token)` already carries, so a watcher
parks like any io park. kqueue's `EVFILT_SIGNAL` and Linux's `signalfd` would
each need a signal-shaped registration the frozen `(fd, write, token)` seam
cannot express, and they would be two mechanisms rather than one:
`EVFILT_SIGNAL` observes delivery and needs the disposition set to `SIG_IGN`,
while `signalfd` consumes a blocked signal and needs a mask. The decisive
difference is thread ordering. `signalfd` requires the signal blocked in every
thread, and a thread that already existed when the watch began cannot be made
to block it, so a process-directed signal delivered there takes the default
action, which for most watched signals terminates the process. A handler runs
on whichever thread takes the signal and has no such requirement.

## Status-carrying network ops (design 117)

Each does its syscall(s) and returns `>= 0` on success/count or `-tag` on failure.
OS-independent bodies (identical libc calls on both hosts; only the errno→tag
mapping and `sin_set_family` diverge). The sockaddr is built internally; the errno
is captured with `__saw_rt_last_syserror()` right after the failing syscall.

### `__saw_rt_tcp_listen(port: word) -> word`
Socket+set_nonblocking+bind+listen on 127.0.0.1:`port` (0 = ephemeral). Returns
the listen fd or `-tag`. errno is captured before the cleanup `close()`.

### `__saw_rt_tcp_listen_on(addr_be: word, port: word) -> word`
The same nonblocking listener and error contract, bound to the supplied IPv4
address (network-order bits in a platform word). Address zero binds all IPv4
interfaces. `__saw_rt_tcp_listen` delegates here with loopback.
`TcpListener.listen(port, host: "0.0.0.0")` exposes the explicit address path;
the host must be a dotted IPv4 literal and the port 0..65535.

### `__saw_rt_tcp_listen_with(addr_be: word, port: word, reuse_address: word, backlog: word) -> word`
(design 272) The same nonblocking listener and error contract, carrying the
options a listening socket can only be given between `socket()` and `bind()`,
which is why they cannot be setters on the listener the two seams above return:
by then the window has closed. `reuse_address` non-zero sets `SO_REUSEADDR`
before the bind; `backlog` is the `listen(2)` queue depth.
`__saw_rt_tcp_listen_on` delegates here with `reuse_address = 1` and backlog
16, and `__saw_rt_tcp_listen` delegates to that with loopback.

Reuse does not make a genuine collision quiet: two sockets bound to the same
address and port still refuse the second with `AddrInUse`. What it permits is
binding over the remains of a connection that has already closed.

### `__saw_rt_socket_set_option(fd: word, option: word, value: word) -> word`
(design 272) Sets one socket option by portable tag → `0` or `-tag`. The option
tag space is the table below; the host maps each tag to its own `(level, name)`
pair, as it maps its errno numbers to the `SysError` space, because the
platform constants disagree (`SOL_SOCKET` is `0xffff` on macOS and `1` on
Linux; `SO_REUSEADDR` is `4` and `2`). `value` is a C `int`; an option needing a
different value shape would take its own seam.

An option this host does not have returns `-Invalid` rather than succeeding
quietly: a setting that silently did nothing is the silent degradation the
never-hide-errors rule forbids.

| Tag | Option        | macOS                      | Linux                    |
|-----|---------------|----------------------------|--------------------------|
| 1   | NoDelay       | `IPPROTO_TCP`/`TCP_NODELAY` | `IPPROTO_TCP`/`TCP_NODELAY` |
| 2   | KeepAlive     | `SOL_SOCKET`/`SO_KEEPALIVE` | `SOL_SOCKET`/`SO_KEEPALIVE` |
| 3   | ReuseAddress  | `SOL_SOCKET`/`SO_REUSEADDR` | `SOL_SOCKET`/`SO_REUSEADDR` |

### `__saw_rt_tcp_local_port(fd: word) -> word`
`getsockname` → the bound local port (resolves an ephemeral 0).

### `__saw_rt_tcp_accept(listen_fd: word) -> word`
Nonblocking accept → a nonblocking conn fd, or `-tag` (`-WouldBlock` when no
client is waiting).

### `__saw_rt_tcp_connect_start(addr_be: word, port: word) -> word`
Start a nonblocking connect to `addr_be`:`port` → the connecting fd (`>= 0`,
including the EINPROGRESS "wait for writable" case) or `-tag` on a real failure.
`addr_be` is the IPv4 address as it sits in `sockaddr_in.sin_addr` (network
byte order), which is what both std's dotted-quad parser and
`__saw_rt_resolve_ipv4` produce.

### `__saw_rt_tcp_connect_check(fd: word, addr_be: word, port: word) -> word`
Re-issue the nonblocking connect to learn the true state (design 90). `0` =
connected; `-InProgress` = still connecting (re-park); `-tag` = a real failure.
`addr_be` must be the address `connect_start` was given: re-issuing against a
different peer asks a different question.

### `__saw_rt_resolve_ipv4(host: i8*, out: u32*, max: word) -> word`
**Blocking (design 184).** Resolve the NUL-terminated hostname at `host` to
IPv4 addresses, writing at most `max` of them to `out` in network byte order,
ready to drop into `sockaddr_in.sin_addr`. Returns the count written (`0` = the
resolver succeeded and offered no IPv4 address, which is not a failure) or
`-tag`. `max <= 0` is `-Invalid`.

**The blocking contract.** This call is unbounded. The hosted body is
`getaddrinfo(3)` with `AF_INET`/`SOCK_STREAM` hints, which may read
`/etc/hosts`, ask mDNS, query LDAP or wait out a DNS timeout: microseconds to
tens of seconds, decided by configuration this process does not control. std
therefore declares it `extern blocking`: every call is offloaded to a worker
thread by design 183's machinery and the calling task parks, so a resolution in
flight never stops a sibling and never wedges the cooperative executor. A
runtime implementing this seam may take as long as it needs; what it may not do
is assume a caller is willing to wait on the calling thread.

Two consequences for an implementer. The body itself is ordinary sync code (the
offload happens on the std side), so `--runtime-build`'s sync-only discipline
applies here as to every other seam. And both pointers obey design 183's rule:
they address the parked task's frame or the heap, so the worker thread may
still be reading and writing through them for the whole call, cancellation
included (`take` joins the worker before the task takes its cancel path).

`EAI_SYSTEM` is reported through errno, so the hosted body maps it with
`__saw_rt_last_syserror()`; `EAI_AGAIN` (a temporary resolver failure) maps to
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
  `d_name` offset is 21 on macOS and 19 on Linux, and it is the only divergent
  part of a readdir walk, so std keeps `opendir`/`readdir`/`closedir` and only
  the projection is a seam. `entry` is non-NULL (std checks readdir's result).
- `__saw_rt_env_set(name: i8*, value: i8*, overwrite: word) -> word`
- `__saw_rt_env_unset(name: i8*) -> word`

## Status-carrying file I/O (design 132)

The same convention applied to the read/write surface, so the failure cause
reaches std as a tag (`__saw_rt_last_syserror` is runtime-internal and must not
be called after a bare libc op). Each returns its natural non-negative result
or `-tag`.

- `__saw_rt_fs_open(path: i8*, mode: word, perm: word) -> word` — the fd, or
  `-tag`. `mode` is a **portable open mode**, not a POSIX flag word: `0` read an
  existing file, `1` write from the beginning creating-or-emptying, `2` append
  creating-if-absent. An unrecognized mode is `-Invalid`. `perm` is the creation
  permission (`0644` from std), read by the kernel only when the mode creates.

  The mode is portable because the `O_*` bits are per-host C macros. A runtime
  translates it into its own host's bits; the hosted runtime does so in
  `shim.c` (`__saw_open_flags`), the only place that can see `<fcntl.h>`.
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

## Process spawn (design 122)

The operation crosses the boundary and its status has to come back with it, as
for the fs/env ops. The spawn is a real argv spawn: **no shell is involved at
any point**, on any implementation, and one `argv` element is one argument,
whatever bytes it holds.

A **job** is an opaque heap record owning the child's pid and, when capturing,
the read end of its stdout pipe. Single-owner discipline, as in the offload
family: `spawn` creates the job, the reap destroys it. The hosted bodies are
`fork` + `execvp` (`rt/common/proc.saw`, OS-independent); between fork and exec
the child touches only async-signal-safe calls (`close`/`dup2`/`execvp`/`_exit`).

**The child wait uses no thread (design 182).** `try_wait` reaps with `WNOHANG`
and answers `-WouldBlock` while the child lives, and a caller that has to wait
asks for a descriptor (`wait_fd`) and parks it on the reactor with the ordinary
read-interest registration. A runtime that cannot hand out a wait descriptor is
still correct: `try_wait` alone is a poll, slower but never wedging anything.

The stdout drain still blocks (a pipe read has nothing else to be), but std
declares `read_stdout` `blocking`, so every call is offloaded to a worker
thread and the task parks. The v1 blocking reap `__saw_rt_proc_wait` is not
part of this contract (see the change table).

### `__saw_rt_proc_spawn(path: i8*, argv: i8**, flags: word) -> word`
Spawn `path` with the NULL-terminated `argv` array (`argv[0]` is the program
name, as `execvp` expects). Returns the job handle (`> 0`) or `-tag`. A child
that cannot exec exits **127** (the POSIX "command not found" convention), which
std maps back to a launch failure.

`flags` is a redirection bit set, one bit per stream (`0` and `1` mean what
they meant before bit 1 existed):

| bit | value | meaning |
|-----|-------|---------|
| 0   | 1     | the child's stdout goes into a pipe the job owns (`read_stdout` drains it) |
| 1   | 2     | the child's stderr goes wherever its stdout goes — into the pipe with bit 0, and plain `2>&1` without it |

Bit 1 exists because a spawner that captures a child's output but inherits its
diagnostics cannot keep its own output clean: a tool that runs many children it
expects some of to fail would interleave their error text with its own report.
Discarding stderr and capturing it separately are not expressible (DF-155a).

### `__saw_rt_proc_spawn_env(path: i8*, argv: i8**, envp: i8**, flags: word) -> word`
The same spawn with environment overrides (design 155): the seam behind
`std.process.Command.env(name:value:)`, a seam because only the runtime can
reach the process environment. `envp` is a NULL-terminated `NAME=VALUE` array;
the child gets the spawning process's environment **with each of those names
set to the given value and everything else inherited**, not a replacement
environment. Names are unique (std replaces rather than appends), so no
precedence question reaches the seam. Returns the job handle (`> 0`) or
`-tag`, and `-Exhausted` when the merged array cannot be allocated.

The merge runs in the parent, before the fork; the child does nothing but point
`environ` at the result before `execvp`. That ordering is the contract, not an
implementation detail: a spawning process may be multi-threaded, and the window
between fork and exec may only touch async-signal-safe calls, which a merge that
allocates is not. Pointing `environ` at a pre-built array is how a portable
`execvpe` is written, and it is what keeps the PATH search (`execvp` takes the
new image's environment from `environ`).

### `__saw_rt_proc_read_stdout(job: word, buf: i8*, len: word) -> word`
Read up to `len` bytes of the child's captured stdout: the byte count (`0` =
EOF, and `0` immediately for a job spawned without capture) or `-tag`.

**Blocking (design 187).** The pipe is a blocking descriptor and a child may
write nothing for as long as it likes, so this call is unbounded. std declares
it `extern blocking`, so every call is offloaded to a worker thread by design
183's machinery and the calling task parks; a runtime implementing this seam
may take as long as it needs, and what it may not do is assume a caller is
willing to wait on the calling thread. `buf` obeys design 183's pointer rule:
it addresses the parked task's frame or the heap, so the worker may write
through it for the whole call, cancellation included.

### `__saw_rt_proc_wait_fd(job: word) -> word`
A descriptor that becomes **readable once the child has exited**, or `-tag`.
Acquired on the first ask (a spawn nobody waits on costs no descriptor), cached
in the job, and owned by the job. This is what turns the child wait into an
ordinary reactor park: register it for read interest, and the poll that would
have blocked in `waitpid` blocks in `kevent`/`epoll_wait` alongside every other
parked task.

`-tag` is not a failure of the wait: it means only that this child cannot be
waited for by descriptor right now, and the caller falls back to polling
`try_wait`. The common reason is benign: on macOS the child became a zombie
between the caller's poll and this call, and there is no exit left to register
for (see `__saw_rt_proc_exit_fd`).

### `__saw_rt_proc_exit_fd(pid: word) -> word`
**OS-divergent**: the one host-specific piece of the wait, and the seam
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
record. The cancellation exit: cancellation cancels the wait, not the child, so
a child still running keeps running and this process never collects its status.

## Cooperative-scheduler fairness (design 89-c)

A backstop for the cooperative scheduler: an io op that completes without
parking charges a budget; when it is exhausted the io primitive force-yields
once so a busy always-ready socket cannot monopolize the executor. The budget
is per thread, so each MT worker has its own allowance and reset. Op-count, not
wall-clock. Default budget 128.

### `__saw_rt_op_budget_tick() -> word  (1/0)`
Decrement the budget. Returns `1` (and resets to the default) when it reaches zero
— the caller then force-yields — else `0`.

### `__saw_rt_op_budget_reset() -> void`
Restore the default budget (a genuine park already ceded).

## The IO reactor (instance-based)

The reactor is an opaque instance created through the ABI, not process-global
seam state. `__saw_rt_reactor_create()` allocates an instance owning its
kqueue/epoll fd and its wake source; register/unregister/poll/wake/destroy take
the instance. The hosted reactor is Saw (`rt/host_macos/reactor.saw` for
kqueue, `rt/host_linux/reactor.saw` for epoll).

**The process-wide instance is executor policy, not runtime state.** It is
`__saw_host_reactor()` (std/taskgroup.saw), a lazy getter over an
`Atomic<Int>` static: `reactor_create` on first use, published by
`compare_exchange`, and a thread that loses the race `reactor_destroy`s its
spare. It returns the `SystemReactor` value that conforms to the Saw `Reactor`
trait, and the executor passes the instance explicitly on every seam call.

**Concurrency.** Several threads poll one instance at once (MT TaskGroup
workers and the ambient scheduler), so concurrent polls must be independent.
The hosted bodies allocate the event buffer per call (`malloc`/`free` inside
`poll`): no shared buffer, no poll mutex.

**The wake is a broadcast (design 225).** `__saw_rt_reactor_wake` makes every
thread blocked in `poll` return, not one of them. The hosted bodies use a
kqueue `EVFILT_USER` event / a Linux `eventfd`, armed once at create and never
deleted, so a blocked poller's registration cannot be consumed out from under
it. A wake source armed one-shot inside each poll would not do: concurrent
pollers would share one registration, and the first delivery would remove it
for all of them. Reaching every poller is a cascade over a per-instance count
of the threads at the blocking call: a poller that consumed the wake re-posts
it while that count is positive, and the chain stops when a consumer reads
zero. `examples/reactor_cross_thread_wake.saw` is the seam-level test.

### `__saw_rt_reactor_create() -> ptr`
Create a reactor instance: a kqueue (macOS) / epoll (Linux) fd + its wake source
(an armed `EVFILT_USER` event / a nonblocking `eventfd`). Returns an opaque
instance pointer (as a `word`).

### `__saw_rt_reactor_register(r: ptr, fd: word, write: word, token: word) -> void`
Arm **one-shot** readiness interest on `fd` in `r` for read (`write==0`) or write
(`write!=0`). `token` is carried as the event's user-data and is **the parked
frame's `__wake`-word address** (design 91), the precise-routing contract, or
`0` for a registration made outside any frame (never latched). One-shot
(`EV_ONESHOT`/`EPOLLONESHOT`) plus fd close drop the registration; epoll re-arms a
known fd with `EPOLL_CTL_MOD` when the `EPOLL_CTL_ADD` fails.

### `__saw_rt_reactor_unregister(r: ptr, fd: word, write: word) -> void`
Drop readiness interest on `fd` in `r` for read (`write==0`) or write
(`write!=0`): `EV_DELETE` on kqueue, `EPOLL_CTL_DEL` on epoll. **Idempotent:**
an already-fired one-shot, a closed fd, and an fd that was never armed all
return `ENOENT`/`EBADF`, which is the state the caller asked for, so the result
is ignored. (Linux keeps one interest per `(epfd, fd)` covering both directions,
so `write` is accepted for uniformity and unused there.)

The token a registration carries is the parked frame's `__wake`-word address,
so a registration that outlives its frame is a dangling write, not a leak, and
the frame box is released at task completion, which makes the window real
(DF-134a). Two callers: std's park loops call it when they leave without their
event firing (a cancellation or a timeout), and a coroutine frame's synthesized
`release` calls it for the last `(fd, dir)` the frame armed, ahead of its own
field drops so the fd is still open and still the frame's. A frame whose body
contains no literal `io_wait` gets neither the bookkeeping fields nor the call.

### `__saw_rt_reactor_poll(r: ptr, timeout_ms: word) -> word  (ready count)`
Block in `kevent`/`epoll_wait` on `r` up to `timeout_ms` (`< 0` = forever). For
each ready event with a nonzero token, **latch its token word to 0 (ready)**,
waking the task whose frame registered for that `(fd, direction)`. The latch
is a persistent word, not an edge, so a latch that lands after the frame has
stored its park word is seen at the next scan. (One that lands between the
arm and that store is overwritten today: SL-353.) Token `0` is never latched:
it belongs to the wake source and to registrations made outside any frame.
Consuming the wake event makes the poll re-post the wake while another poller
is blocked (the cascade above) and clear the source so it does not busy-fire.
Returns the number of events delivered, a consumed wake event included. The
event buffer is a per-call heap allocation (see Concurrency above).

### `__saw_rt_reactor_wake(r: ptr) -> void`
Rouse every thread blocked in `poll` on `r`, from any thread, including one the
executor knows nothing about. Its callers: the cancel wake (a `cancel()` on an
already io-parked task rouses the poll; the scheduler re-checks `cancelled()`
and wakes the parked frame, which returns `Err(IoError)` at its loop top), the
MT worker pool, where a worker's progress has to reach a scheduler parked on
another thread, and a channel send's poke. A wake fired with nothing parked is
not lost: the source is state rather than an edge, so the next `poll` returns
on it at once. Which frames are woken stays precise (a non-cancelled sibling
parked on an idle fd stays parked); the broadcast is over pollers, not frames.

### `__saw_rt_reactor_destroy(r: ptr) -> void`
Close the instance's fds and free it. (Called by the singleton getter on the
CAS-loser's spare; the process-lifetime instance itself is never destroyed.)

## Threads — spawn/join/detach (designs 21 / 117 / 242)

v1's `__saw_rt_pthread_create`/`__saw_rt_pthread_join` are replaced by
spawn/join (see the migration table); detach was added later. pthread symbols
resolve from libSystem (macOS) / libc+libpthread (Linux).

### `__saw_rt_thread_spawn(entry: void*(*)(void*), env: i8*) -> word  (handle)`
`pthread_create(&t, NULL, entry, env)`; return the OS thread handle (`pthread_t`,
pointer-sized on both hosts) as a word. Spawn codegen stores the returned handle
into the control block's first slot. C shim (DF-113b: a raw C function
pointer).

### `__saw_rt_thread_join(handle: word) -> void`
`pthread_join((pthread_t)handle, NULL)`: join by the handle value. Saw body
(`rt/common/pthread.saw`).

### `__saw_rt_thread_detach(ctrl: i8*) -> void`
`pthread_detach` on the thread whose control block is `ctrl`, and the handoff of
that block's ownership to the thread's own exit path. C shim (DF-113b's reason
plus one of its own, below). The daemon-thread fate (design 242): the values a
thread owns deinit if it completes, and the OS terminates it at process exit.

**Why it takes the block and not the handle.** Its twin `__saw_rt_thread_join`
takes the handle by value, and symmetry would say this should too. It cannot,
because detaching is two jobs rather than one: the OS thread must be detached,
and somebody must eventually free the control block, and after a detach there
is no join left to do it. The two parties who could are the detacher and the
thread's own exit path, they run concurrently, and exactly one must free. That
handshake needs a word both can reach, which means the block.

**The handshake, frozen.** The control block is
`{ pthread_t tid, i8* env, word state, T result }`; spawn codegen owns that
layout and this document freezes exactly one word of it, `state`, at offset
`2 * sizeof(void*)`. Spawn codegen seeds it with the block's own size (a
positive number) before the thread exists. Then:

| party | exchange | what a returned value means |
|-------|----------|-----------------------------|
| this seam | `prev = xchg(state, 0)` | `prev > 0` — the thread is still running and its exit will free the block. `prev < 0` — the thread already finished and left `-size`; **free it here**, `size = -prev` |
| the thread's exit path (the per-spawn trampoline, after the result is stored and the env released) | `prev = xchg(state, -size)` | `prev == 0` — the detacher already ran; **free it there**. Otherwise the detacher has not run and will |

Both exchanges are acquire-release. Exactly one side frees, always, with no lock
and no wait. **The size travels in the word** so this seam can call
`__saw_rt_dealloc` without knowing `T`: the block's layout is the compiler's,
and the seam learns one word of it and nothing else.

`join` never touches `state`: a joined thread was never detached, so the joiner
is the block's only owner and frees it.

**Why C.** DF-113b's reason (the block's first slot holds a `pthread_t`, which
Saw has no type for) plus one of this seam's own: the handshake is an atomic
exchange over raw memory, and Saw's atomics are a type (`Atomic<Int>`) rather
than an operation a pointer can carry.

**SOS / freestanding.** A runtime with no threads implements neither this seam
nor `__saw_rt_thread_spawn`/`_join`. It must refuse rather than provide a
no-op `detach`: a silent no-op would leak the control block of every detached
thread and would tell a caller its thread was detached when no thread exists.
Without the spawn seam, a `Thread.spawn` fails at link before a `detach` could
be reached, which is that refusal.

### `__saw_rt_pthread_mutex_init_default(m: i8*) -> void`
`pthread_mutex_init(m, NULL)`. Saw reserves a conservative slot (<= 64 bytes).

### `__saw_rt_pthread_cond_init_default(c: i8*) -> void`
`pthread_cond_init(c, NULL)`. `pthread_cond_t` is 48 bytes on macOS/glibc; std
reserves 64.

### `__saw_rt_lock_acquire(state: word*) -> void`
### `__saw_rt_lock_release(state: word*) -> void`
**The one-word lock (design 186).** `state` addresses one platform word that
`Mutex<T>` carries inline, and **zero means unlocked**: that is the contract on
every host, and it is what lets `static M: Mutex<T>` be declared with no
initializer and land in .bss. A runtime may use as much of the word as it likes
(both hosted implementations use its low four bytes, and both hosted targets are
little-endian) but must accept all-zero as the initial unlocked state.

`acquire` blocks the calling thread until the lock is held; `release` hands it
on. Neither is recursive: acquiring a lock this thread already holds is a
program bug, and a runtime may trap or deadlock. Both are `sync` (a seam never
suspends a task), which is why `Mutex.lock` takes a `sync` closure.

Host bodies: macOS is `os_unfair_lock_lock`/`_unlock` in Saw
(`rt/host_macos/lock.saw`); Linux is a three-state futex in `rt/shim.c`, which
stays C because a futex needs 32-bit atomics through a pointer, which Saw
cannot spell (DF-186c).

## Blocking-extern offload (design 183)

A blocking FFI call inside a suspending task runs on a thread of its own, one
per call; normally the task parks on the job's pipe like any socket read, so no
executor thread blocks. Cancellation goes straight to `take`, which joins the
call's thread, so it can block the executor thread running it until the call
returns. A job is a heap record; single-owner discipline
throughout. The offload thunk `fn` is a C-ABI `word(word)`.

That one word is a pointer to the call's argument slots (one `word`-sized slot
per parameter, in declaration order), and `fn` is a thunk the compiler
synthesizes for each offloaded extern, which reads the slots back at their
declared types and makes the real call. So the extern's own C ABI is the
compiler's ordinary extern-call lowering, this seam family knows nothing about
arity, and every signature the C-ABI whitelist admits (fixed-width integers,
Int/UInt, Float, UnsafePointer, plus Void/Never returns) can be offloaded.

**Lifetime rule for the runtime**: the worker reads the slots at a time `start`
cannot bound, so `start` copies them into storage the job owns and `take` frees
that storage after the join. What a pointer slot points at is the caller's
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
join is unconditional: a cancelled task still takes, which is what makes freeing
the slots safe.

### `__saw_rt_blocking_sleep(ms: word) -> word  (ms)`
The reference blocking primitive: a thread-blocking sleep that returns its
argument, which the offload tests call through a `blocking func` extern.

## Program arguments (design 81)

The C entry `main(argc, argv)` stashes its two arguments in two module-private
globals at startup, and `Env.argc`/`Env.arg` read them through these accessors
on every target. The compiler emits both accessors, and the globals, into
every program; the hosted runtime does not export them.

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
| `__saw_rt_pthread_create(tid,start,arg)` | **renamed** `__saw_rt_thread_spawn(entry,env) -> handle` |
| `__saw_rt_pthread_join(tid)`     | **renamed** `__saw_rt_thread_join(handle)` (value handle) |

Everything else (alloc/dealloc/write/panic, sleep, clocks, set_nonblocking,
sin_set_family, op-budget, mutex/cond init, the offload family, get_argc/argv)
carried over from v1 into v2 unchanged; later changes are in the next table.

Changes since v2. Rows marked **changed**, **replaced** or **removed** alter
something an older runtime already implements; the rest add a symbol, a tag or
a flag bit.

| design | change                                                          |
|--------|----------------------------------------------------------------|
| 122    | `__saw_rt_fs_dirent_name`                                      |
| 122    | `__saw_rt_proc_{spawn,read_stdout,wait}`                       |
| 123    | `__saw_rt_alloc_deny_after` (optional hosted test facility)    |
| 132    | `__saw_rt_fs_{open,read,write,lseek,opendir}`                  |
| 137    | `__saw_rt_alloc_deny_after` **changed**: one parameter, `(allow)`; the second (a window that re-armed the allocator) is gone |
| 147    | `__saw_rt_reactor_unregister` (DF-134a)                        |
| 155    | `__saw_rt_proc_spawn_env`; `__saw_rt_proc_spawn`'s `flags` gains bit 1 (stderr follows stdout); `__saw_rt_fs_open`'s `mode` **changed** from a raw `O_*` flag word to the portable open mode, with the same signature |
| 180    | `__saw_rt_sleep_ms(ms)` **replaced** by `__saw_rt_sleep_ns(ns)`: nanoseconds, read as unsigned |
| 182    | `__saw_rt_proc_{exit_fd,wait_fd,try_wait,release}`: the child wait with no thread |
| 183    | `__saw_rt_offload_start` **changed** from `(fn, arg)` to `(fn, argp, argc)`: the thunk's word points at argument slots the job copies |
| 184    | `__saw_rt_resolve_ipv4`; `__saw_rt_tcp_connect_start` **changed** from `(port)` to `(addr_be, port)` and `__saw_rt_tcp_connect_check` from `(fd, port)` to `(fd, addr_be, port)` (they dialled a hardcoded 127.0.0.1) |
| 186    | `__saw_rt_lock_{acquire,release}`                              |
| 187    | `__saw_rt_proc_wait` **removed**: its last caller (`Command.output`) went cooperative, so the v1 blocking reap has none, and a runtime need not provide it |
| DF-215a | SysError tags 17-21 (`HostUnreachable`/`NetUnreachable`/`TimedOut`/`HostDown`/`NetDown`), the five off-loopback errnos the map omitted. No symbol, no signature, no renumbering; see the tag table above |
| 225    | `__saw_rt_reactor_wake` **changed** contract: it rouses every blocked poller, not one. No signature change; see the reactor section |
| 234    | `__saw_rt_last_raw_code`: the raw platform code beside the tag, stamped by `__saw_rt_last_syserror` and read by std's `IoError`. One new symbol, no existing signature moved; the status word still carries only the tag (see that seam's entry) |
| 242    | `__saw_rt_thread_detach`: `pthread_detach` plus the control block's ownership handshake with the thread's own exit path. One new symbol, no existing signature moved. It takes the control block rather than a handle, and it freezes exactly one word of that block's layout (`state`, at `2 * sizeof(void*)`); see its entry |
| 272    | `__saw_rt_tcp_listen_with`, `__saw_rt_socket_set_option`      |
| —      | `__saw_rt_tcp_listen_on`                                       |

## The compiler → executor boundary (design 118)

A second boundary, separate from the runtime ABI above (Saw ↔ host OS): the
one between the code the compiler synthesizes (coroutine frames and the
transform) and the cooperative executor, which is Saw (`std/taskgroup.saw` and
`std/task.saw`). Synthesized code holds no scheduler loop or park policy of its
own; it calls the executor by name through the entry points below. These are
not `__saw_rt_*` seams: a runtime does not provide them, and nothing here is
machine-checked.

| concern | entry point | called from |
|---------|-------------|-------------|
| enqueue | `TaskGroup.__enqueue(task: Box<any Resumable>, cell: Box<any __TaskCell>) -> Int` | the spawn helper `__spawn_<f>` |
| handle identity | `TaskGroup.__gen_at(slot: Int) -> Int` | the spawn helper, after `__enqueue` |
| background group | `__saw_bg_group() -> UnsafePointer<TaskGroup>`, `__saw_bg_close()` | the `Task.spawn` helper; the synthesized `main` of a program with a background spawn |
| drive with spawns | `__saw_exec_run_root(rootbox)`, `__saw_exec_run_root_status(rootbox, cellbox, cellp) -> Int` | the entry executor of a suspending `main` in a program that spawns |
| single-frame park | `__saw_exec_park(wake: Int, deadline: Int)` | the entry executor of a suspending `main` with no spawns; an `io_wait` or channel park outside any frame |
| arm io | `__saw_exec_io_register(fd: Int, dir: Int, token: Int)` | the `io_wait` and offload park lowerings; `io_wait` outside a frame (token `0`) |
| disarm io | `__saw_exec_io_unregister(fd: Int, dir: Int)` | the `io_unwait` lowering, including a frame's synthesized `release` |
| thread-engine count | `__saw_exec_thread_task_started()` | `Thread.spawn` codegen |
| panic sink | `__saw_bt_panic(message, length)` | the panic path of a program that links the executor |

In the other direction, the compiler emits the `__saw_bt_table()` blob that the
executor's task dump reads.

What stays synthesized:

- **Frame layout and the transform.** Per suspending function or method, a
  `__Frame_<f>` struct and its `resume() -> Poll` state machine, with the
  `Resumable` conformance (`wake_reason`, `is_cancelled`, `io_deadline`,
  `bt_desc`, `release`) that `Box<any Resumable>` erasure dispatches through.
  A suspension writes the frame's `__wake` reason and returns `Pending` (an io
  park first arms the reactor through `__saw_exec_io_register`). Wake reasons
  follow the park word vocabulary in std/taskgroup.saw: `> 0` sleep
  nanoseconds, `0` ready, `-1` io park, `< -1` readiness-word park.
- **The single-frame entry executor** keeps its resume-until-done loop over
  `main`'s own stack frame, with no box and no scheduler list; its only park is
  the call to `__saw_exec_park`. A monomorphized `__saw_exec_run_single(box)`
  that would remove even that loop is a deferred option.
- **The test-only drivers** `__saw_drive_<f>` / `__saw_drive_steps_<f>` resume
  in a loop and never park.
- **The offload lowering.** A `blocking` extern call becomes
  `__saw_blk_start`, a park loop on the job pipe, and `__saw_blk_take`; codegen
  lowers `__saw_blk_*` to the `__saw_rt_offload_*` seams and emits one
  `__saw_blk_thunk$<extern>` per offloaded extern (design 183).
- **The spawn half of the thread engine.** `Thread.spawn { }` codegen builds
  the control block and a per-site trampoline and launches it through
  `__saw_rt_thread_spawn` (a raw C function pointer, DF-113b). Joins go
  through the `NativeThread` trait (`PosixThread` over `__saw_rt_thread_join`,
  in std/task.saw).

The executor reaches register/unregister/poll/wake only through the `Reactor`
trait, implemented for the hosted runtime by `SystemReactor` over the instance
seams, with static dispatch rather than an `any Reactor` existential: the
implementation is chosen at link time, so a box would cost an allocation and
buy nothing. An SOS-hosted runtime would implement the same trait. The
white-box reactor tests (`net_precise_*` and the `io_wait` echo examples)
exercise the `(fd, direction, token)` semantics `SystemReactor` wraps, so they
are the `Reactor` contract's tests.

## The four intended implementations

1. **host_macos** — kqueue reactor, libSystem pthreads, macOS errno/clock ids,
   `__error`, `__stdoutp`, `sin_len` sockaddr prefix.
2. **host_linux** — epoll reactor, glibc pthreads, Linux errno/clock ids,
   `__errno_location`, `stdout`, u16 sockaddr family.
3. **sos-hosted** — the SOS userland runtime, a Saw runtime in the sawos
   repository. The SysError tag space and the negated-word status convention
   are its native `(status, value)` shape.
4. **kernel / none** — the freestanding profile: the compiler emits these as
   external declarations only and links no runtime; a kernel supplies the bodies.

## Authoring a runtime in Saw (design 113b)

The hosted runtime is **authored in Saw** under `sawc/rt/`, compiled with
`--runtime-build`, plus a C shim for the bodies a Saw FFI gap blocks. Layout:

```
sawc/rt/
  common/       OS-independent bodies: mem.saw (alloc, dealloc, deny_after),
                sleep.saw, op_budget.saw, pthread.saw (mutex/cond init,
                thread_join), offload.saw, proc.saw (fork/exec argv spawn,
                WNOHANG reap), os_ops.saw (the status-carrying tcp_*/fs_*/env_*
                ops, socket options, resolve_ipv4)
  host_macos/   kqueue reactor + macOS specifics: clock, net_os (errno→tag,
                raw code, sin_set_family), dirent (the d_name offset), lock
                (os_unfair_lock), proc_wait (the EVFILT_PROC child-exit
                descriptor)
  host_linux/   epoll reactor + Linux specifics: clock, net_os, dirent,
                proc_wait (pidfd_open); the Linux lock is in shim.c
  shim.c        the bodies a Saw FFI gap blocks (below)
```

**The `--runtime-build` compile mode.** `@export("__saw_rt_<name>")` is allowed for
exactly the frozen ABI set (the compiler validates against `sawc/runtime_abi.py`);
a misspelled/non-ABI `__saw_rt_*` export is a clean error naming the valid set.
The module is sync-only; only `builtin.saw` is loaded. Objects are built and
cached under `.build/rt/<key>/` (the key hashes every input that can change the
built runtime: the rt sources, `shim.c`, the triple, and the compiler and std
sources) and auto-linked for hosted builds (`sawc -v` lists them). The
freestanding profile links no runtime (verified by
`freestanding_seams_extern_no_runtime`).

**The C floor: `shim.c`.** Each body there is C because of a named Saw FFI gap,
and moves to Saw when its gap closes:

- `__saw_rt_write` / `__saw_rt_panic`: no extern C global (DF-113a). They write
  through libc's `stdout` `FILE*` (`fwrite`, then `fflush`), which Saw cannot
  name.
- `__saw_rt_thread_spawn` and the offload thread body: no C function-pointer
  type (DF-113b). Both pass or call a raw C function pointer.
- `__saw_rt_thread_detach`: DF-113b's reason plus an atomic exchange over raw
  memory (see its entry).
- `__saw_rt_set_nonblocking`: calls the variadic `fcntl(fd, F_SETFL, ...)`.
  It is in C for a reason that no longer holds (DF-113c): Saw does declare
  variadic externs now (`open` in `rt/common/os_ops.saw`).
- `__saw_rt_lock_acquire` / `_release` on Linux: a futex needs 32-bit atomics
  through a pointer (DF-186c).
- Runtime-internal helpers the Saw bodies call, for the same gaps (per-host C
  macros and struct layouts, an extern global, a signal handler's function
  pointer): `__saw_open_flags`, the `getaddrinfo` projections
  (`__saw_ai_next`, `__saw_ai_ipv4`, `__saw_gai_tag`),
  `__saw_environ_get`/`_set`, the socket-option and SIGPIPE helpers, the
  signal family, and on Linux `__saw_epoll_event_size`/`_data_offset`.

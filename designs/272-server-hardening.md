# Design 272 — server hardening: io deadlines, socket options, signals

Issues: **SL-204** (io_wait needs a deadline), **SL-229** (std.net socket
options), **SL-228** (std.signal). One brief, three units, landing in that
order. Each issue carries a RULED DESIGN section (user, Sep 10 2026) that is
binding.

The thirteen points those rulings left open were taken at brief time and are all
RULED as of **Sep 11 2026** — see the DECISIONS section, where each carries its
authority. The four judgment-laden ones (D1-1, D2-2, D3-1, D3-3) are USER
rulings recorded as comments on SL-204 / SL-229 / SL-228; the remaining nine are
lead rulings on doctrine the brief argued from. Nothing in this brief is open.

The three compose more than the pairing anticipated. Unit 2's setsockopt op is
what makes SIGPIPE inexpressible-by-construction (see D3-3), so the trio removes
an entire signal from unit 3's surface rather than arguing about its default
disposition — and the per-socket suppression that does it lands in UNIT 2, on
both platforms, with unit 3 documenting why `SIGPIPE` is deliberately not a
`Signal` case.

---

## Landing order and why

1. **Unit 1 (SL-204)** — the executor's park vocabulary. Touches the compiler
   (one new intrinsic, one frame field, one `Resumable` accessor) and
   `std/taskgroup.saw`. Nothing else depends on it, but it is the riskiest, so
   it goes first while the branch is empty.
2. **Unit 2 (SL-229)** — `rt/` seam addition + `std/net.saw` surface. Depends on
   nothing in unit 1; ordered second because unit 3 consumes its setsockopt op.
3. **Unit 3 (SL-228)** — `std/signal.saw`, both host reactors, `shim.c`. The
   biggest, and the only one that adds a module.

---

## UNIT 1 — SL-204: a deadline on a parked io wait

### The problem, stated as mechanism

`io_wait(fd, dir)` is register-then-park sugar (`coro_transform.py:6150-6182`):
it stamps `__io_fd`/`__io_dir`, calls `__saw_exec_io_register(fd, dir,
__io_tok)`, and suspends the frame with `IO_PARK_WAKE` (-1). The executor's park
word vocabulary (design 230, `std/taskgroup.saw:242-284`) is ONE `Int` with four
states:

```
 > 0   a SLEEP deadline in nanoseconds
== 0   READY
== -1  the IO PARK          <- an io park carries no deadline; this is the gap
 < -1  a park on a READINESS WORD (negated address)
```

So an io-parked frame waits forever, and there is nowhere in the encoding to put
"…but no longer than 30 seconds". That block's own comment says a fifth state
"would be added here and nowhere else", which is the invitation this unit takes.

`SO_RCVTIMEO` is not an answer: the fd is nonblocking and the wait happens in
`kevent`/`epoll_wait`, not in `recv`.

### The mechanism — a PAIR, not a fifth number

Do not try to encode a deadline in the one word. The io park keeps `-1`; the
deadline moves to a **second frame field**, and the fifth state is the PAIR:

```
__wake == -1  &&  __io_deadline == 0   ->  the io park (unchanged, design 76)
__wake == -1  &&  __io_deadline >  0   ->  the DEADLINE-BOUNDED io park (new)
```

`__io_deadline` is an ABSOLUTE monotonic nanosecond instant
(`__saw_rt_clock_monotonic_nanos()`), never a countdown. Absolute is not a
detail: the executor's existing `remaining` bookkeeping is RELATIVE and is
decremented by whichever thread just polled, which two concurrent MT workers
would double-charge. An absolute instant is idempotent — every reader computes
`now >= deadline` and gets the same answer — so the MT path needs no accounting
at all.

Concretely:

* **Compiler.** A new intrinsic `io_wait_until(fd, dir, deadline_ns)` beside
  `io_wait`, lowered in the same branch: stamp `__io_fd`, `__io_dir`,
  `__io_deadline`, register, suspend with `IO_PARK_WAKE`. `io_wait` stamps
  `__io_deadline = 0` (so a later untimed park cannot inherit an earlier timed
  one's deadline). `io_unwait(fd, dir)` additionally clears `__io_deadline` —
  which is why NO new release hook is needed: the synthesized frame `release`
  already emits `io_unwait` (`coro_transform.py:8579`), so DF-134a's
  belt-and-braces disarm covers the timer for free.
* **Frame.** One new `Int` field and one new `Resumable` accessor,
  `io_deadline()`, synthesized exactly as `wake_reason()`/`is_cancelled()` are.
* **Executor.** One funnel (below) consulted at the four park sites.
* **rt/ABI.md.** **UNCHANGED.** No seam is added, renamed or re-signed. The
  clock seam `__saw_rt_clock_monotonic_nanos()` already exists and is already
  exported; `std/net.saw` declares it in its `extern "C"` block the way
  `std/taskgroup.saw` already does. The `abidoc` lane has nothing to gate here.

### Obligation 1 — the funnel and its named entry points

The rule "an io-parked frame with a deadline is runnable once its deadline has
passed" quantifies over every position the executor decides whether an io park
is still a park. That is a funnel, not a matrix:

```saw
// The design-272 park-deadline funnel. The ONLY place the deadline half of the
// design-230 vocabulary is interpreted. Entry points, all in std/taskgroup.saw:
//   1. __saw_exec_run_inner   phase 2 (the ambient sweep's poll-bound scan)
//   2. __saw_exec_wake_io                 (the ambient sweep's post-poll promote)
//   3. __saw_exec_worker      io branch   (the MT worker's bound + promote)
//   4. __saw_exec_park                    (the single-frame drive)
func __park_deadline_remaining(deadline: Int, now: Int) sync -> Int   // -1 = none
func __park_deadline_expired(deadline: Int, now: Int) sync -> Bool
```

Each entry point reads the clock ONCE per scan, not once per slot.

* **Poll bound.** An io-parked frame with a deadline contributes
  `max(0, deadline - now)` to the same earliest-deadline variable a sleeper
  contributes to, so the existing `__saw_exec_poll_ms` /
  `__saw_exec_flag_bound` chain bounds the poll with no new arithmetic. The
  single-frame drive's `__saw_exec_park` stops passing a hardcoded `-1` for an
  io park and passes this bound instead — the one line that makes a timed read
  work in a suspending `main` with no spawns.
* **Promote.** After the poll, an io-parked slot is made runnable if the reactor
  latched it (`wake_reason() >= 0`, unchanged), OR it is cancelled (unchanged),
  OR `__park_deadline_expired`. Order matters only for reporting, and the frame
  re-issues its syscall either way.
* **Lost-wakeup guards.** `__saw_exec_any_latched_io` and
  `__saw_exec_any_cancelled_io` are untouched: a deadline never makes a park
  *less* wakeable, and the pre-poll guard already covers the latched case.

The frame itself decides "readable" vs "timed out" — it re-issues the syscall at
the loop top. Only if that still answers would-block AND `now >= deadline` does
it report a timeout. So a wake that is both (bytes arrived exactly at the
deadline) reports the bytes, which is the answer a caller wants.

### The surface (D1-1, ruled)

```saw
/// The outcome of an operation that was given a deadline.
public enum Timed<T> {
    /// It finished before the deadline.
    case Value(T)
    /// The deadline elapsed first. Nothing was read, accepted or connected.
    case TimedOut
}

extension TcpListener {
    public func accept(timeout: Duration) -> Result<Timed<TcpStream>, IoError>
}
extension TcpStream {
    public static func connect(host: String, port: Int, timeout: Duration)
        -> Result<Timed<TcpStream>, IoError>
    public func read(timeout: Duration) -> Result<Timed<Data>, IoError>
    public func read_into(into: &var Data, timeout: Duration)
        -> Result<Timed<Int>, IoError>
}
```

The untimed `accept()`/`read()`/`read_into()`/`connect()` are UNCHANGED — no
contract flip, no consumer sweep debt on the existing surface. A timed call is a
new overload with a `timeout:` label, which is also what makes it readable at the
call site.

Worked call site — the motivating idle-connection timeout:

```saw
while true {
    match try stream.read(timeout: Duration.secs(30)) {
        case Value(bytes) -> {
            if bytes.len() == 0 { break }        // the peer closed
            try handle(bytes)
        }
        case TimedOut -> break                    // idle too long; drop it
    }
}
```

Three outcomes, three arms, and `Err` is still the fourth thing that can happen.
That is the shape the dispatch asked for: a timeout is distinct from EOF (an
empty `Value`) and distinct from an error (`Err`).

### Cancellation and the budget

A deadline-bounded park keeps every design-102 property: `cancelled()` is checked
at the loop top before the syscall, the cancellation exit calls `io_unwait`
(which now also clears the deadline), and `cancel()` still self-wakes the
reactor. `__saw_rt_op_budget_reset()` is called on the park exactly as the
untimed loops do. A task cancelled while parked with a deadline takes the cancel
path, not the timeout path — `cancelled()` is tested first.

---

## UNIT 2 — SL-229: socket options, `reuse_address` default ON

### Ruled (binding)

`reuse_address` defaults ON at listener bind; it stays a visible labeled
parameter so `reuse_address: false` opts out. No builder object — labeled
arguments with defaults ARE the options surface. Curated, not exhaustive. No raw
`setsockopt` escape hatch. Full words.

### The surface — D2-1 (ruled) keeps `listen`, not `bind`

The existing public surface is `TcpListener.listen(port:)` and
`listen(port:host:)` (`std/net.saw:649-670`); there is no `bind`. Renaming to
`bind` would churn every consumer for no gain and would be less accurate — the
call binds AND listens. The two overloads collapse into ONE default-carrying
signature, which removes an overload rather than adding a surface:

```saw
extension TcpListener {
    public static func listen(port: Int,
                              host: String = "127.0.0.1",
                              reuse_address: Bool = true,
                              backlog: Int = 16) -> Result<TcpListener, IoError>
}
```

Every existing call site keeps compiling unchanged (`listen(port: 0)`,
`listen(port: 8080, host: "0.0.0.0")`). Default parameter values on a plain
`func` are already in the language and already used in std
(`std/cbor.saw:492`, `std/env.saw:99`, `std/file.saw:143`, `std/json.saw:470`).

Per-connection, `Result`-returning setters on `TcpStream`:

```saw
extension TcpStream {
    public func set_no_delay(&self, on: Bool) -> Result<Void, IoError>
    public func set_keepalive(&self, on: Bool) -> Result<Void, IoError>
}
```

### The mechanism

`reuse_address` must be set BETWEEN `socket()` and `bind()`, so it cannot be a
post-hoc setter on the listen fd; the rt seam has to carry it. Additive, nothing
removed or re-signed:

* **New seam** `__saw_rt_tcp_listen_with(addr_be, port, reuse_address, backlog)
  -> word`. `__saw_rt_tcp_listen` and `__saw_rt_tcp_listen_on` stay, as thin
  forwarders with the ruled defaults — so an out-of-tree runtime provider that
  implements only the v2 set keeps working and gets the new default for free.
* **New seam** `__saw_rt_socket_set_option(fd, option, value) -> word`, the one
  status-carrying setsockopt-shaped op the issue asked for. `option` is a
  PORTABLE TAG, not a host `SO_*` number — the same shape as the `SysError` tag
  space and `__saw_open_flags`'s portable mode word, and for the same reason:
  the constants diverge per host. The tag space gets its own small table in
  `rt/ABI.md` beside the `SysError` one.
* **Host mapping** in `rt/host_*/net_os.saw`: portable tag -> `(level, optname)`
  for this host, plus the existing errno -> `SysError` mapper on failure.
* **`rt/ABI.md` CHANGES** — two new sections and one new tag table. The `abidoc`
  lane gates it and the ABI.md edit travels in the same commit. **FLAGGED** per
  the dispatch; the issue's RULED DESIGN anticipates exactly this.

### Doctrine check

Every setter returns `Result`. There is no silent degradation: a host that
refuses `TCP_NODELAY` reports it. `reuse_address: false` at bind still surfaces
`EADDRINUSE` as `Err(IoError{AddressInUse})`, unchanged.

---

## UNIT 3 — SL-228: `std.signal`

### Ruled (binding)

Hosted-only. Surface is a SUSPENDING WATCH, no callbacks anywhere: `watch(...)`
returns a `Result` handle whose `next()` suspends until delivery, parking on the
reactor exactly like a socket read. Watching replaces the default disposition;
unwatched signals keep OS behavior; `SIGKILL`/`SIGSTOP` are inexpressible. NO
exit registry — cleanup rides cancellation and deinits; `process.exit(code)` is
the documented no-cleanup escape hatch.

### The surface

```saw
//! std.signal — OS signals as suspending reactor events. Hosted only.

public enum Signal {
    case Terminate      // SIGTERM
    case Interrupt      // SIGINT
    case Hangup         // SIGHUP
    case Quit           // SIGQUIT
    case User1          // SIGUSR1
    case User2          // SIGUSR2
    case WindowChanged  // SIGWINCH
}

public struct SignalWatch { ... }        // NoCopy; Deinit restores the disposition

extension SignalWatch {
    /// Begin watching `which`. Replaces its default disposition for as long as
    /// the returned handle lives.
    public static func watch(which: Signal) -> Result<SignalWatch, IoError>
    /// Suspend until the watched signal is delivered.
    public func next(&self) -> Result<Void, IoError>
}

/// Send `which` to this process. The deterministic way to exercise a handler,
/// and the way a program triggers its own shutdown path.
public func raise(which: Signal) -> Result<Void, IoError>
```

Case spellings are CamelCase because that is what every std enum uses
(`IoErrorKind.TimedOut`, `SysError.WouldBlock`, `Poll.Pending`); the issue's
`.terminate` was sketch shorthand. Errors reuse `IoError`/`IoErrorKind` rather
than inventing a `SignalError` — registration failures are `PermissionDenied` /
`InvalidArgument` / `AlreadyExists`, all of which `IoErrorKind` already spells,
and a second error vocabulary for six call sites is not worth its weight
(D3-5, ruled).

`SIGKILL`/`SIGSTOP` are inexpressible because they are not cases — there is no
runtime refusal to write and no way to spell the request.

`SIGPIPE` is likewise not a case, and that ABSENCE is documented in the module
docstring rather than left to be noticed: sockets never raise it (unit 2
suppresses it per socket, D3-3), a socket write to a closed peer surfaces as
`IoErrorKind.BrokenPipe` on a `Result`, and the process-wide disposition is
deliberately untouched so pipes and child processes behave exactly as they do
today. A reader looking for `Signal.BrokenPipe` finds the reason at the point
they look for it.

The shutdown pattern, which is what the surface is for:

```saw
var group = try TaskGroup()
let server = group.spawn(serve(&listener))
let shutdown = group.spawn(wait_for_stop())
try shutdown.join()          // returns when SIGTERM arrives
server.cancel()              // design 102 wakes the io-parked accept loop
// values deinit as the tasks unwind; main returns normally
```

### The mechanism

Both hosts deliver NATIVELY — no `sigaction` callback, no self-pipe, no
async-signal-safe handler to audit:

* **macOS** — `EVFILT_SIGNAL`, `ident = signo`, `udata = token`, armed
  `EV_ADD|EV_CLEAR`. The signal's default action must first be disabled
  (`sigaction` to `SIG_IGN`), because `EVFILT_SIGNAL` observes delivery and does
  not suppress it.
* **Linux** — `signalfd`, registered with the reactor as an ordinary read fd,
  with the signal blocked via `pthread_sigmask` in EVERY thread. "Every thread"
  includes threads spawned after the watch begins, so `__saw_rt_thread_spawn`
  and the offload thunk inherit the mask — a `shim.c` change (a new thread
  inherits its creator's mask, so masking at `watch` time plus masking in the
  spawn path covers both orders).

Both are hidden behind ONE portable seam pair, so the host divergence lives
where design 117 put every other one:

* **New seam** `__saw_rt_reactor_register_signal(r, signo, token) -> word`
  (0 or `-tag`; registration is fallible, which is why `watch` returns
  `Result`).
* **New seam** `__saw_rt_reactor_unregister_signal(r, signo) -> void`.
* `signo` is a PORTABLE TAG, not a host signal number — the `SysError` /
  socket-option pattern again, and necessary because the numbers diverge
  (`SIGUSR1` is 30 on macOS, 10 on Linux).
* **`rt/ABI.md` CHANGES** — reactor section grows two entries plus a signal tag
  table. **FLAGGED**; `abidoc` gates it and the edit travels in the same commit.

`next()` is an ordinary io park (`io_wait` on the Linux signalfd; on macOS the
`EVFILT_SIGNAL` knote latches the same `__wake` token), so it inherits
cancellation, the budget reset, and — for free — unit 1's `next(timeout:)` if we
want one later. A lone parked watcher keeps `anyio` true, so the
design-230 quiescent walk never reports a deadlock on "a server waiting for
SIGTERM", which is exactly right: a signal can still arrive.

---

## DECISIONS — all thirteen RULED, Sep 11 2026

Each names the options, what doctrine determined, and the ruling. Every one was
taken as the brief argued it.

**AUTHORITY.** D1-1, D2-2, D3-1 and D3-3 are USER rulings, recorded as comments
on SL-204 (D1-1), SL-229 (D2-2, D3-3) and SL-228 (D3-1, D3-3). The other nine —
D1-2, D1-3, D1-4, D2-1, D2-3, D2-4, D2-5, D3-2, D3-4, D3-5, D3-6 — are LEAD
rulings on doctrine already settled, endorsed Sep 11 as argued. Nothing below is
open; the option tables are kept because the reasons are the record.

### D1-1 — how a timeout is spelled (SL-204's open point)

**RULED: A** (user, Sep 11 2026, SL-204).

| Option | Shape | Against |
|---|---|---|
| **A — RULED** | `Result<Timed<T>, IoError>`, `Timed<T>` = `Value(T)` \| `TimedOut` | one new generic type in std.net |
| B | `Err(IoError{kind: TimedOut})` | `IoErrorKind.TimedOut` ALREADY means `ETIMEDOUT` (`std/net.saw:454`, ABI.md tag 19) — a deadline elapsing would be indistinguishable from the OS's own connection timeout. That is a sentinel collision, which doctrine forbids outright |
| C | `Result<Data?, IoError>`, `None` = timed out | `None` does not say "timed out" at the call site, and it sits one layer away from the empty-`Data` EOF sentinel. Reader-visibility loses |

A is the only one that makes the three outcomes three arms, and B was
disqualified on evidence rather than taste. The spelling is CONFIRMED, so the
rename contingency the brief priced is moot — unit 1 builds against `Timed<T>`
directly.

### D1-2 — which ops get a timed twin

**RULED** (lead, doctrine-determined). IN: `accept`, `read`, `read_into`,
`connect`. OUT for this brief: `write`.

A timed `write` that gives up partway MUST report how many bytes went, or the
caller cannot resume and the error is hidden — so it cannot share `Timed<T>`
(whose `TimedOut` arm carries nothing) and needs its own
`WriteOutcome { Sent, TimedOut(sent: Int) }`. That is a second outcome type for
a case no consumer has asked for; the motivating report is idle READS. **If the
user wants write in now**, `WriteOutcome` above is the shape, and it is
half a day.

### D1-3 — granularity (recorded, then RULED as recorded)

Both reactor seams take a MILLISECOND timeout
(`__saw_rt_reactor_poll(r, timeout_ms)`), and `__saw_exec_poll_ms` rounds UP.
So a `Duration` finer than a millisecond is honoured to the nearest millisecond
ABOVE it — a deadline never fires early, only late. That is the right direction
(an early timeout would be a lie) and it is DOCUMENTED on every timed op rather
than silently rounded. No seam change is proposed to sharpen it: nothing asked
for sub-millisecond idle timeouts, and "perf via measurement" applies.

### D1-4 — `Duration` or an instant

`timeout: Duration` (a span from the call), not a deadline instant. `Duration`
is the prelude's unit vocabulary and what `sleep` takes; `std.time.Instant`
needs an import. The ABSOLUTE instant exists only inside the frame, where the
executor reads it. No decision needed beyond recording it.

### D2-1 — `listen` vs `bind` as the name

**RULED: keep `listen`** (lead, doctrine-determined), collapsing its two
overloads into one default-carrying signature. Renaming to `bind` (the issue's
sketch) churns every consumer, is less accurate, and buys nothing.

### D2-2 — `no_delay` default

**RULED: ON** (user, Sep 11 2026, SL-229).

| Option | Argument |
|---|---|
| **ON — RULED** | Nagle + delayed ACK produces 40ms stalls on exactly the request/response traffic the motivating server serves. Go, Rust's `TcpStream` wrappers, libuv and node all default it on. It is the same argument the user ALREADY accepted for `reuse_address`: the thing a server author expects should just work |
| OFF (OS default) | "Perf via measurement — no speculative perf work." We have no profile showing the stall in a Saw program |

`no_delay: true` is applied to accepted and connected streams, with the setter
available to turn it back off. The doctrine tension was named at brief time and
resolved the same way `reuse_address` was: this is a LATENCY PATHOLOGY, not a
throughput optimization, so "perf via measurement" does not govern it.

### D2-3 — `v6_only` / dual-stack

**RULED: OUT** (lead, doctrine-determined) — and not a real question yet.
`std.net` is IPv4-only end to end:
`AF_INET`, a 16-byte `SockAddrIn`, `parse_ipv4_literal`, and
`__saw_rt_resolve_ipv4` which returns IPv4 addresses only
(`rt/common/os_ops.saw:88-101`, `std/net.saw:140`). There is no dual stack to be
`v6_only` about. It becomes a decision the day IPv6 lands, and the tracker's
design-184 happy-eyeballs note is where that already lives.

### D2-4 — the rest of the option set

**RULED as tabled** (lead, doctrine-determined).

| Option | Verdict | Why |
|---|---|---|
| `reuse_address` | IN, default true | ruled |
| `backlog` | IN, default 16 | it is already a hardcoded `listen(2)` argument (`os_ops.saw:91`); exposing it costs one parameter and 16 is low for a real server |
| `no_delay` | IN, setter | D2-2 decides the default |
| `keepalive` (enable) | IN, setter | `SO_KEEPALIVE` is portable and one boolean |
| SIGPIPE suppression | IN, **not user-facing** | D3-3's per-socket ruling lands here: an option tag set by the runtime on every socket it creates, with no Saw-visible parameter. There is no reason a caller would ever want a socket write to kill the process, so this is a fact about sockets, not a choice |
| keepalive INTERVAL | **OUT** | `TCP_KEEPINTVL`/`TCP_KEEPIDLE` (Linux) vs `TCP_KEEPALIVE` (macOS, idle only) do not have the same meaning, and unit 1 gives the application-level deadline that was the actual need |
| `reuse_port` | **OUT** | `SO_REUSEPORT` means load-balancing on Linux and something else on BSD. A portable name with divergent semantics is the kind of silent surprise doctrine forbids |
| send/receive buffer sizes | **OUT** | pure tuning; "perf via measurement"; nobody asked |
| `linger` | **OUT** | it changes what `close()` means in a way that interacts with deterministic destruction; needs its own design, not a checkbox |
| raw `setsockopt` | **OUT** | ruled out unless a consumer demands it, and none does |

### D2-5 — what `net_listen_bind_address.saw` should assert after the flip

The sweep found exactly one test the ruled default breaks, and the fix is a
choice about WHICH guarantee that row is for. Its line 15 currently binds
`0.0.0.0:P` and then asserts `127.0.0.1:P` is refused — an OVERLAP, which
`SO_REUSEADDR` on the second socket legitimately permits.

| Option | |
|---|---|
| **A — RULED** | Re-point the row at an EXACT-address collision (`127.0.0.1:P` twice). Still refused with reuse on both sockets, on both kernels, so the row keeps asserting the thing it was written for — "this exact address is taken is still an honest error" — and stops asserting a wildcard-overlap rule the default flip deliberately relaxes |
| B | Add `reuse_address: false` to line 15 and keep the overlap | Preserves the literal text but the row then tests the opt-out rather than the default, and the default is what everything else will use |
| C | Keep the overlap and flip the expectation to `wrong conflict` | Renames a passing assertion into a confusing one |

**RULED: A** (lead, doctrine-determined), plus a SECOND row (option B's content,
spelled honestly) so the opt-out is covered too. Both rows are written to the
EXACT-address shape, which is the case the two kernels agree on — and that is
what keeps sweep B's unverified-Linux gap off the critical path. The gap is
still live and is reported rather than guessed: see "Linux verification" in the
sweep-B section.

### D3-1 — `Signal` membership

**RULED: the seven-member set** (user, Sep 11 2026, SL-228) — `Terminate`,
`Interrupt`, `Hangup`, `Quit`, `User1`, `User2`, `WindowChanged`, with SIGCHLD
explicitly out.

OUT, each with its reason:

* `SIGCHLD` — `std.process` owns child reaping (`__saw_rt_proc_wait_fd`); a
  watcher would race it, and two owners of one disposition is the bug D3-2 is
  about.
* `SIGALRM` — nothing in the language exposes an interval timer, and unit 1 is
  the deadline mechanism.
* `SIGPIPE` — **structurally removed by D3-3**, not merely omitted.
* `SIGTSTP`/`SIGCONT` — job control, no consumer, and stopping a cooperative
  scheduler mid-park has its own design.
* `SIGKILL`/`SIGSTOP` — ruled inexpressible.

### D3-2 — double-watch policy

**RULED: error at the second watch** (lead, doctrine-determined).

| Option | Argument |
|---|---|
| **Error at the second watch — RULED** | The disposition is process-global state, and a global with two owners is exactly what the language makes explicit everywhere else. `SignalWatch` is NoCopy and its `Deinit` restores the previous disposition, which is only well-defined if ownership is unique. A program that genuinely needs fan-out builds it from one watch and a `Channel` — a composition Saw already has |
| Broadcast | "APIs do the expected thing" — nobody expects a second watch to fail. But it also means no one owns the restore, and two subsystems both thinking they handle shutdown is a real bug this would hide |

`watch` returns `Err(IoError{AlreadyExists})` for a second live watch of the
same signal. Ownership is the primitive; fan-out is a library.

### D3-3 — SIGPIPE default-ignore

The question as posed was whether the hosted runtime should set `SIGPIPE` to
`SIG_IGN` at startup.

**RULED** (user, Sep 11 2026, SL-229 + SL-228): **NEITHER a process-wide
default-ignore NOR a `Signal` case — suppress it PER SOCKET**, with `EPIPE`
surfacing as an ordinary `IoError`. The suppression is UNIT 2 scope on BOTH
platforms (it is an option-op consumer); unit 3 documents why `SIGPIPE` is
deliberately not a `Signal` case and points here.

* macOS: `SO_NOSIGPIPE` via unit 2's `__saw_rt_socket_set_option`, set on every
  socket `rt_tcp_listen_with` / `rt_tcp_accept` / `rt_tcp_connect_start`
  produces.
* Linux: `MSG_NOSIGNAL` on the socket write, i.e. `rt_tcp_write` uses `send(2)`
  with that flag instead of `write(2)`.

Why this and not the process-global ignore every other runtime does:

* It is precise. A socket write to a closed peer returns `EPIPE`, which std.net
  already classifies as `IoErrorKind.BrokenPipe` — so the failure becomes a
  `Result` instead of an unhandleable death. That is "never hide errors" applied
  literally.
* It leaves PIPE behavior alone. A process-global `SIG_IGN` silently changes what
  `saw-program | head` does: probed, a Saw producer into `head -2` returns `-13`
  today, and after a global ignore it would keep producing output into a `write`
  that fails and that `print` has no channel to report. Trading a visible death
  for a silent infinite loop is a bad trade.
* An ignored disposition is INHERITED ACROSS `execve`, and
  `rt/common/proc.saw:263-285` does not reset dispositions before `execvp` — so
  a process-global ignore would be handed to every child a Saw program spawns,
  including the shells and pipelines it did not write. The blast radius is not
  the Saw process; it is the process tree.
* It removes `SIGPIPE` from the `Signal` enum entirely rather than arguing about
  its default, which is the better kind of answer.

This is the decision that makes the trio compose: unit 2 builds the mechanism,
unit 3 loses a member it would otherwise have had to argue about.

### D3-4 — the op budget while a watcher parks

**RULED: no special case** (lead, doctrine-determined). A parked watcher is an ordinary io park: `next()` calls
`__saw_rt_op_budget_reset()` on the park exactly as `read`/`accept` do, and
because it is an io park the design-230 quiescent walk sees `anyio` and does not
report a deadlock. Documented explicitly, because "every task is parked and one
of them is waiting for SIGTERM" is a CORRECT state that looks like a hang.

### D3-5 — `IoError` or a new `SignalError`

**RULED: `IoError`** (lead, doctrine-determined). Every failure mode a signal watch has —
`PermissionDenied`, `InvalidArgument`, `AlreadyExists` (D3-2), `Interrupted`
(cancellation) — is already an `IoErrorKind` case, the module is hosted-only
like `std.net`, and `IoErrorKind` is already the prelude-adjacent vocabulary.
A second error type for six call sites earns nothing.

### D3-6 — what `next()` returns

**RULED: `Result<Void, IoError>`** (lead, doctrine-determined) with coalescing
DOCUMENTED. POSIX
non-realtime signals coalesce: three `SIGTERM`s delivered between two `next()`
calls may surface as one. Returning a delivery COUNT (`Result<Int, IoError>`) is
available on both hosts (kqueue's `data`, one `signalfd_siginfo` per read) but
invites callers to build logic on a number the OS does not promise. Say it in
the docstring instead.

---

## Obligation 2 — consumer sweeps

Three behavioral-contract questions, swept before dispatch, with compile and run
evidence rather than grep alone.

### Sweep A — who relies on un-timeboxed reads

Readers enumerated: 5 park sites in `std/net.saw` (`accept` 693, `dial` 807,
`read` 849, `read_into` 894, both `write` overloads 927/964) plus ONE non-net
reactor park at `std/process.saw:494` (`Command.run`/`output` parks on the
child-exit fd) — so anything that changes the io-park ENCODING reaches
`std.process` too, which unit 1's pair encoding deliberately does not. Beyond
std: 28 `examples/` files use the owning-type ops, 12 more use the raw
`io_wait`/`tcp_try_read` white-box loops, and two `devtools/dogfood/programs/`
clients (`llm_client.saw`, `w1_chatroom.saw`). `blade/`, `libs/`, `selfhost/`
and `tools/` contain ZERO listener or stream sites.

**Verdict: an OPT-IN deadline touches none of them; a DEFAULT one would break
five.** The five are the cancellation pins that assert "parks forever until
cancelled" as the behavior under test — `net_cancel_parked_read.saw` (whose
header says the pre-fix poll "blocked forever"), `net_cancel_parked_mt.saw:18`
(`io_wait(fd, 0) // park on an idle read fd (never ready)`),
`net_cancel_precise.saw`, `net_cancel_unregisters_token.saw`,
`net_io_cancel.saw` — plus every `if chunk.len() == 0` EOF drain
(`net_sibling_eof_no_deadlock.saw`, `net_two_concurrent_parked_reads.saw`)
which would misread a timeout as a clean close if a timeout were spelled as an
empty `Ok`. Both hazards are exactly what D1-1 option A and the
new-overload-only surface avoid: **no existing signature changes.**

`devtools/dogfood/programs/llm_client.saw` is the one real consumer whose logic
would have read a timeout as EOF (`read_head:408` reports an empty chunk as
`"connection closed before the response headers arrived"`). It compiles clean
today and is untouched by an opt-in deadline.

### Sweep B — the bind default flip

`setsockopt` appears NOWHERE in the repository (whole-tree search over `.saw`,
`.c`, `.py`, `.md`, `.sh`). The single bind is `rt_tcp_listen_on`
(`rt/common/os_ops.saw:156-175`); `rt_tcp_listen` forwards to it.

Every listener site was enumerated: 18 in `examples/`, one in `devtools/`, zero
in `blade`/`libs`/`selfhost`/`tools`. **All but one use ephemeral port 0**,
where `SO_REUSEADDR` changes nothing — so the "two tests race the same fixed
port" hazard does not exist in this corpus.

**ONE HARD BREAKAGE, probe-confirmed.**
`examples/net_listen_bind_address.saw:13-16` binds a WILDCARD listener
(`0.0.0.0:P`) and then asserts that binding `127.0.0.1:P` is refused
(`EXPECT-OUTPUT: conflict refused`). A direct probe of the kernel on this macOS
host:

```
A(reuse=False bind=0.0.0.0  ) B(reuse=False bind=127.0.0.1) -> BIND-FAILED errno=48
A(reuse=False bind=0.0.0.0  ) B(reuse=True  bind=127.0.0.1) -> BIND-SUCCEEDED   <- the flip
A(reuse=True  bind=127.0.0.1) B(reuse=True  bind=127.0.0.1) -> BIND-FAILED errno=48
```

Three facts: an overlapping wildcard/specific pair SUCCEEDS once the SECOND
socket sets `SO_REUSEADDR`; it is the second socket's flag that decides, so the
pre-existing wildcard listener does not protect the test; and an EXACT-address
duplicate still refuses even with reuse on both. So the default flip turns that
row's `conflict refused` into `wrong conflict`. **D2-5 decides what the row
should assert instead.**

**Linux verification — STILL OPEN, reported not guessed.** The probe ran on
darwin only. No Linux userland is reachable from this checkout: the freestanding
runner boots bare-metal ELFs under QEMU (`-nographic`, no kernel, no libc), so
there is nowhere here to run a `socket`/`bind` probe against a Linux stack. And
Linux's `SO_REUSEADDR` rules for a wildcard/specific overlap on LISTENING
sockets are NOT the same as BSD's, so the darwin result does not carry over.

`.build/scratch/probe_reuseaddr.py` is the instrument, and it is
self-contained — it needs only CPython and prints the three-row table quoted
above. The Linux answer is needed for ONE thing only: whether an overlapping
wildcard/specific pair is permitted there too. It is NOT on the critical path,
because D2-5 rewrites the row to the EXACT-address shape, which both kernels
refuse and which the darwin probe confirms directly. So the gap is recorded as
a FOLLOW-UP for the lead to close on the server gate's evidence, not a
blocker, and nothing in unit 2 is written against an assumption about it.

### Sweep C — default signal dispositions

**SIGTERM: no consumer at all.** Repo-wide search for
`SIGTERM|SIGINT|SIGHUP|SIGQUIT|SIGUSR` across `.py`/`.sh`/`.saw`/`.c`/`Makefile`
returns ZERO hits. Every harness timeout reaches for SIGKILL, which is
uncatchable: `test_runner.py:1155-1164` (`os.killpg(..., SIGKILL)`, children
spawned `start_new_session=True`), `tools/test_worker.py:474-477` (same shape),
`tools/sawfuzz.py:490-498` and `tools/corodiff.py:1496-1500`
(`proc.kill()`), `tools/freestanding_runner.py:793-808` (kills QEMU, and the
freestanding target has no `std.net` or `std.signal` at all),
`tools/remote_worker_selftest.py:139-144`. **A Saw program that watches SIGTERM
breaks nothing in this repo** — and the corollary is that nothing here would
ever exercise a graceful shutdown, which is why unit 3's oracle is
`raise(which:)` against the process itself rather than an external signaller.

**SIGPIPE: a real dependency, and it argues against the global ignore.** A probe
piping a Saw producer into `head -2` returns `-13` — the program dies on
SIGPIPE today, silently. Two facts make the process-global `SIG_IGN` worse than
it looks: `print`'s seam `__saw_rt_write` has no error channel, so an ignored
SIGPIPE turns a visible death into a silent loop writing into a failing `write`;
and `rt/common/proc.saw:263-285` does NOT reset dispositions before `execvp`, so
an IGNORED signal is inherited by every child a Saw program spawns — a Saw
program that spawned `sh -c '... | head'` would hand it the ignore. Both
disappear under D3-3's per-socket suppression, which is the recommendation.

**SIGCHLD: a hard dependency — which is why it is not a `Signal` case.**
`rt/common/proc.saw:376-409` reaps with `waitpid(..., WNOHANG)` and an explicit
EINTR retry; under `SIG_IGN`/`SA_NOCLDWAIT` the kernel auto-reaps and `waitpid`
fails `ECHILD`, which that code would report as a launch failure. Consumers:
`examples/process_signal_death.saw` (the one signal-death decoding test),
`std/process.saw:114-130` `decode_wait_status`, `blade/src/tester.saw:18-24`
(`blade test` judges a test by the raw wait status precisely to catch SIGABRT —
and runs in the `bootstrap` lane), plus `devtools/irdet`, `devtools/bench` and
`selfhost/lexer`, all of which drive `sawc` through `Command`/`system`. D3-1's
exclusion of SIGCHLD is load-bearing, not tidiness.

`rt/shim.c` references NO signal API today (no `<signal.h>` in its include
list); the only occurrences are `abort()` in the panic path and one comment
about async-signal-safety. Both reactors are signal-free. So unit 3 adds
genuinely new host surface rather than reshaping existing surface.

### Incidental finding (filed, not fixed here)

`devtools/dogfood/programs/w1_chatroom.saw` does not compile: 16 errors at lines
113-119, all design-234 `Channel` fallible-constructor drift
(`argument 'ch3' expects 'Channel<String>' but got 'Result<Channel<String>,
AllocError>'`). `tools/battery.sh` has NO stage that typechecks
`devtools/dogfood/programs/*.saw` — `lexdiff`/`astdiff` lex and parse them but
check no semantics — so the rot went unnoticed. Filed as its own SL issue;
unrelated to this brief and deliberately not repaired inside it.

---

## Obligation 3 — conformance rows FIRST

All three units touch liveness contracts the language claims, so the rows land
as each unit's first commit, before the mechanism. New rows in the K
(concurrency) block, continuing from K92:

| ID | Guarantee | Unit |
|---|---|---|
| K93 | a deadline-bounded io park still observes cancellation, and takes the CANCEL path rather than the timeout path | 1 |
| K94 | a deadline-bounded io park that never becomes ready reports `TimedOut` and does not hang, in the ambient sweep, an MT group, and a single-frame drive alike | 1 |
| K95 | a deadline-bounded park that becomes ready BEFORE its deadline reports the bytes, not `TimedOut` | 1 |
| K96 | a timed park never loses an io wakeup a concurrent inline poll consumed (the DF-134a / `any_latched_io` interaction) | 1 |
| K97 | a timed park leaves NO reactor registration behind on any exit — ready, timeout, cancel, or frame release | 1 |
| K98 | a signal delivered to a parked watcher wakes it; an UNWATCHED signal keeps the OS default disposition | 3 |
| K99 | a watched signal's disposition is restored when the watch handle is destroyed | 3 |
| K100 | a lone parked signal watcher is not reported as a deadlock | 3 |

Unit 2 adds no liveness row — a bind refusal surfacing as `Err` is already
covered by the design-92 "no silent error swallow" rows — but its default flip
gets an ordinary `examples/` test asserting that a restart against a TIME_WAIT
socket now succeeds and that `reuse_address: false` still fails honestly.

## Test plan

Live-server fixtures are DETERMINISTIC, per the SL-208 io_wake precedent: a
READY handshake, never a sleep as synchronization. Concretely, the timeout
fixtures FORCE the park — the client connects and provably sends nothing until
it has read the server's greeting — so "the read is parked" is a fact of the
program, not a race. Timeout ASSERTIONS are one-sided (elapsed >= the deadline,
never an upper bound), because an upper bound is a property of the machine.

* Unit 1: driven + sync twins where the op has both; the three engines (ambient
  sweep, MT group, single-frame drive) are three separate files, because the
  funnel has three entry points and a single file would exercise one.
* Unit 2: an ephemeral-port listener, closed and rebound immediately, proving the
  default; the `reuse_address: false` control; each setter's `Result` on a live
  stream. `examples/net_listen_bind_address.saw` is rewritten per D2-5 and the
  Linux `SO_REUSEADDR` probe is re-run before that row is finalised.

One hazard the sweep surfaced for unit 1's tests: driven-method frames are keyed
by `(type name, method name)`, and
`examples/conformance/K38_std_name_collision_no_frame_on_sync_method.saw`
asserts `EXPECT-IR-ABSENT: __Frame_TcpStream_read` against a USER type named
`TcpStream` with its own `read`. Design 95 keys overloads by RESOLVED signature,
so `read(timeout:)` must land on a distinct frame symbol; K38 stays green as
written, and unit 1 checks it explicitly rather than assuming.
* Unit 3: `raise(which:)` against the process itself is the oracle — deterministic,
  needs no external signaller, and works under the suite runner and in a sandbox.
  Both hosts run it; the Linux mask-inheritance case gets its own file that
  spawns a thread AFTER the watch begins.

Freestanding stays green throughout: `std.signal` joins `HOSTED_STD_MODULES`
beside `std.net`, and the freestanding suite proves the absence costs nothing.

## Docs (design 125)

`LANGUAGE_SPEC.md`, the saw-lang skill, and `README.md` get the three new
surfaces; prose follows the saw-docs skill; `--emit-docs` docstrings on every
new public declaration.

## Gates

Per-unit: full compiler suite + `tools/freestanding_runner.py` (both arches).
Terminal, after all three: rebase onto `origin/main`, full 27-stage
`tools/battery.sh`. Units 2 and 3 change `rt/ABI.md`, so `abidoc` is a
first-class lane for them and the ABI.md edit travels in the same commit as the
seam.

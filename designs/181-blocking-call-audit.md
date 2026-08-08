# Design 181 — investigation: the blocking-call audit

**Status: APPROVED (user, Aug 7 evening: "a sweep of the stdlib to ensure
there are no additional blocking calls which could block our async
runtime"). PROBE/READ-ONLY — the product is an inventory, findings, and
per-class policy recommendations; fixes are follow-up dispatches. Runs
concurrent with anything (no std/rt edits).**

## The contract being audited

Design 103: `extern blocking` marks an unbounded call — it suspends, is
offloaded to a worker thread in suspending bodies, and is illegal in sync
contexts. An UNANNOTATED extern PROMISES promptness. The audit question:
which unannotated externs across sawc/std/ + sawc/rt/ break that promise —
a libc call that can block unboundedly (or for human-visible time) while a
cooperative executor thread is inside it, starving every sibling task.

## Method

1. **Inventory EVERY `extern` declaration** in sawc/std/*.saw, sawc/rt/
   (common + both hosts), and builtin.saw if any. For each: the libc call,
   its worst-case blocking behavior (unbounded / bounded-slow / prompt),
   which std surfaces reach it, and whether the reaching path is
   (a) reactor-integrated (non-blocking fd + park — the net pattern),
   (b) `blocking`-annotated (offload), (c) executor-internal by design
   (the sleep park — being unified by design 180), or (d) NAKED — an
   unannotated potentially-blocking call reachable from a task.
2. **Class (d) is the findings list.** Seeded suspicions to verify first,
   then sweep for the rest: `Command.run`/`output` child-wait (waitpid is
   unbounded — a task running a subprocess may wedge its thread);
   hostname/DNS resolution if any path does it (getaddrinfo has no
   non-blocking form — the classic); std.file/std.directory disk I/O
   (open/read/write/fsync/stat/list — bounded-slow on local disk,
   unbounded on network filesystems); pipe reads in Command.output;
   Mutex (pthread block — bounded by the lock discipline, but VERIFY a
   task-context lock cannot deadlock the executor); Channel's blocking
   `recv` twin (documented — confirm the docs fence it from task context);
   anything in env/process/time.
3. **Verify empirically where cheap**: a two-task probe per suspect — task
   A enters the suspect call (e.g. runs `sleep 5` via Command), task B
   increments a counter — does B starve? Probes under .build/scratch/.
4. **Per-class policy recommendations for the user** (the deliverable's
   spine): which calls should gain the `blocking` annotation (= automatic
   offload; note the design-103 v1 signature whitelist may need widening —
   file that as its own finding if so); which should be reactor-integrated
   properly (fd-shaped ones); which stay prompt-by-policy with a docs
   sentence (local-disk file I/O is the industry-standard candidate — cite
   the tradeoff honestly: offloading file I/O costs a thread hop on every
   read; kernels-first Saw may prefer Rust/Go's "files are prompt" stance
   over tokio's spawn_blocking); and which are executor-internal and
   covered by design 180.

## Deliverables

The inventory table + verdicts appended to this brief; DF-181x findings
for every class-(d) call (severity by starvation impact: unbounded from a
common API = P0-adjacent); the policy menu for the user's ruling; xfail or
pin tests ONLY where a probe demonstrates starvation cheaply and
deterministically (a Command-wait starvation probe is likely pinnable; a
DNS one is not — note, don't flake the suite). NO std/rt edits.

## Explicitly out

Implementing offloads or annotations (follow-up after the user's policy
ruling); the design-103 multi-arg offload widening (file it if needed);
design 180's sleep work.

---

# THE REPORT (Aug 7, probe/read-only run — no std/rt/compiler edits)

## Headline

**169 `extern` declarations across 30 files in `sawc/std/` + `sawc/rt/`.
NOT ONE carries the `blocking` annotation.** The design-103 offload
machinery works correctly and is demonstrably never used by the standard
library. Three things are P0-adjacent, and the third is the one that
decides how expensive the other two are to fix.

### P0-adjacent, in priority order

1. **`Command.run()` / `Command.output()` wedge the whole executor for the
   child's entire lifetime.** DEMONSTRATED, not inferred: a sibling task's
   first tick lands at 2012 ms while task A runs `/bin/sleep 2`, then it
   completes 20 cooperative yields in 0 ms — it was runnable the whole
   time and could not be scheduled. `Command` is a common, documented,
   user-facing API and the block is UNBOUNDED (the child may never exit).
   This is the worst finding in the audit. Pinned:
   `examples/process_run_starvation_xfail.saw` (XFAIL, cites DF-181a).

2. **Every `std.file` / `std.directory` seam is naked.** `__saw_rt_fs_open`
   / `_read` / `_write` / `_lseek` / `_opendir` / `readdir` / `_mkdir` /
   `_rmdir` / `_chdir` / `getcwd` / `_unlink` / `_rename` / `access` — no
   annotation, and (unlike the reactor and sleep seams) not one comment
   anywhere in the tree acknowledges that they block. Bounded-slow on a
   healthy local disk, genuinely unbounded on a network mount, a FUSE
   filesystem, or a FIFO. Reachable from `File.open`/`read`/`write`/`seek`
   and the whole `Directory` surface.

3. **The `blocking` annotation is SILENTLY IGNORED on `__saw_rt_*` runtime
   seams — so "just annotate the seams" does not work today.** Design 103
   promises an offload or "a clean anchored error, never a silent
   miscompile". Both fail on exactly the symbols this audit would annotate.
   See DF-181f: this gates the remediation for findings 1 and 2.

## Inventory by class

All 169 declarations, grouped. Class (d) is itemized in full; the other
classes are grouped because within each the verdict is uniform.

| # | Call(s) | Worst case | Reaching API | Class | Verdict |
|---|---|---|---|---|---|
| 1 | `__saw_rt_tcp_listen/accept/read/write/connect_start/connect_check/local_port`, `socketpair`, `close` | prompt (fds set nonblocking, park on reactor) | `TcpListener`, `TcpStream` | **(a) reactor-integrated** | CORRECT — the model the rest should follow |
| 2 | `__saw_rt_reactor_poll` (`epoll_wait`/`kevent`), `__saw_rt_reactor_wake`, `__saw_rt_reactor_create/destroy/register/unregister` | blocks by design (this IS the park) | executor internals | **(c) executor-internal** | CORRECT — annotating would offload the executor onto a thread |
| 3 | `__saw_rt_sleep_ms`, `usleep` | bounded by the requested nap | `sleep()`, MT-worker re-scan | **(c) executor-internal** | CORRECT — design 180 owns the unification |
| 4 | `__saw_rt_thread_join` / `pthread_join` inside `rt_offload_take` | bounded — joins only after the pipe says done | offload completion | **(c) executor-internal** | CORRECT |
| 5 | `pthread_mutex_lock/unlock`, `pthread_cond_signal` (executor run queue) | bounded by a short sync critical section | TaskGroup internals | **(c) executor-internal** | CORRECT |
| 6 | `malloc`/`realloc`/`free`/`__saw_rt_alloc`/`__saw_rt_dealloc`, `memcpy`, `strlen`, `__saw_string_*`, `fabs`…`fmax`, atomics, `clock_gettime`, `__saw_rt_unix_timestamp_secs`, `getenv`/`__saw_rt_env_set`/`_unset`, `__saw_rt_get_argc`/`argv`, `__saw_rt_last_syserror`, `__saw_open_flags`, `__saw_rt_sin_set_family`, `__saw_rt_dirent_name`, `__saw_environ_get/set`, `__saw_rt_set_nonblocking`, `__saw_rt_op_budget_*`, `socket`/`bind`/`listen`/`getsockname`/`pipe`/`dup2`/`_exit`, `__saw_rt_thread_spawn`, `__saw_offload_thread_ptr` | genuinely prompt | everywhere | **prompt** | CORRECT — no action |
| 7 | **`__saw_rt_proc_wait`** (`waitpid`) | **UNBOUNDED** — child may never exit | **`Command.run`, `Command.output`** | **(d) NAKED** | **DF-181a — P0-adjacent. DEMONSTRATED.** |
| 8 | **`__saw_rt_proc_read_stdout`** (`read` on a blocking pipe) | **UNBOUNDED** — child may never write | **`Command.output`** | **(d) NAKED** | **DF-181a — P0-adjacent. DEMONSTRATED.** |
| 9 | **`__saw_rt_fs_open`/`_read`/`_write`/`_lseek`** (+ libc `open`/`read`/`write`/`lseek` in os_ops) | bounded-slow local; **unbounded** on network fs / FIFO / device | **`File.open`/`create`/`read`/`write`/`seek_*`/`position`** | **(d) NAKED** | **DF-181b — P0-adjacent by reach** |
| 10 | **`__saw_rt_fs_opendir`/`readdir`/`closedir`/`_mkdir`/`_rmdir`/`_chdir`/`getcwd`/`_unlink`/`_rename`/`access`** | same as 9 | **`Directory.list`/`create`/`remove`/`current`/`set_current`, `File.remove`/`rename`/`exists`** | **(d) NAKED** | **DF-181b — P0-adjacent by reach** |
| 11 | **`pthread_cond_wait`** via `Channel.recv` | **UNBOUNDED** — no sender ⇒ never returns | **`Channel.recv`** (the thread-engine twin) | **(d) NAKED** | **DF-181c — docs name the engine but never the consequence** |
| 12 | `fork`, `execvp` | bounded (address-space copy) | `Command` spawn | **prompt-by-policy** | acceptable — note only |
| 13 | `pthread_mutex_lock` via `Mutex.lock` | bounded by the critical section | `Mutex.lock` | **prompt-by-policy** | **VERIFIED SAFE — see below** |

### The two negative results (verified, not assumed)

**Mutex is NOT a hazard.** `Mutex.lock` is
`lock<R>(&self, body: (&var T) sync -> R) unsafe -> R` (`mutex.saw:84`) —
the body is a **`sync` function type**, so a task physically cannot
suspend while holding the lock. The lock is therefore always released
before the task yields, and no two cooperative tasks can hold it across a
scheduling point. In a single-threaded group contention is impossible; in
a `threads: N` group a worker can contend, but only for the duration of
another worker's `sync` critical section. The seeded suspicion is closed:
a task-context lock cannot deadlock the executor.

**There is NO DNS anywhere in the tree.** `getaddrinfo`, `gethostbyname`,
`inet_pton`, `inet_addr`, `gethostname` — zero hits across all of `sawc/`.
The classic unbounded-resolver hazard does not exist today. It does not
exist for a reason worth its own finding, though: `TcpStream.connect(host:
String, port: Int)` **ignores its `host` argument entirely** and always
dials 127.0.0.1 (`net.saw:389-390` → `__saw_rt_tcp_connect_start(port)`,
whose body builds a `loopback_sockaddr`). See DF-181d. When hostname
support lands, resolution will instantly become the worst blocking call in
the library — it should be designed offloaded or reactor-integrated from
day one, never added as a naked seam.

## Probe results

All probes under `.build/scratch/`, run on macOS. Every one is
reproducible; none is flaky (each margin is ~2000 ms against a 400–1000 ms
threshold).

| Probe | Result |
|---|---|
| `probe_cmd_starve.saw` — task A runs `/bin/sleep 2` via `Command.run`, task B timestamps its first tick | **STARVED.** A entered at 0 ms, returned at 2012 ms; **B's first tick at 2012 ms**, then 20 yields in 0 ms |
| `probe_output_starve.saw` — same with `Command.output` over `sh -c "sleep 2; echo done"` | **STARVED.** B's first tick at 2029 ms; 5 bytes captured |
| `probe_whitelist2.saw` — CONTROL: an annotated `blocking` extern fitting `(Int) -> Int` | **OFFLOAD WORKS.** A blocked 2009 ms; **B's first tick at 0 ms** — the machinery is sound and simply unused by std |
| `probe_whitelist5/6.saw` — off-whitelist `blocking` on plain libc symbols (`getpid`, `getppid`), in `let` and statement position | **CLEAN ERROR**, as design 103 promises |
| `probe_whitelist7.saw` — the identical off-whitelist shape on `__saw_rt_last_syserror` | **COMPILES SILENTLY** — annotation dropped |
| `probe_whitelist4.saw` — `blocking func __saw_rt_sleep_ms(ms: Int)` (off-whitelist, Void return), really sleeping | **SILENT THREAD BLOCK.** No offload, no error; B's first tick at 2010 ms |

The last three together are DF-181f: the whitelist check is correct and
fires properly for ordinary symbols, and does not fire at all for
`__saw_rt_*` seams.

## THE POLICY MENU (the ruling this brief exists to get)

### Class 1 — child process wait + stdout drain (`Command`)

| Option | Cost | Verdict |
|---|---|---|
| **Reactor-integrate** — `pidfd_open`+epoll (Linux 5.3+), `EVFILT_PROC` (macOS/BSD); set the stdout pipe nonblocking and park it exactly like a socket | two host-specific paths for the wait; the pipe half is nearly free | **RECOMMENDED (target state)** |
| **Blocking-annotate** — offload the wait to a worker thread | one thread per child wait | **RECOMMENDED as v1 for the wait only** |
| Prompt-by-policy + docs | — | **REJECT** — an unbounded wait on a common API is not a promise anyone can keep |

**Recommendation: do both, in that order.** The stdout pipe is a plain fd
and `std.net` already owns every piece of machinery it needs — parking it
on the reactor is the cheap, obviously-correct half and should just be
done. For the wait, `__saw_rt_proc_wait(job: Int) -> Int` **fits the
design-103 whitelist exactly** (one `Int`, returns `Int`), so the
annotation is a one-word change *once DF-181f is fixed* — and a thread per
child wait is proportionate, since spawning a process is already far more
expensive than a thread. Then replace it with pidfd/EVFILT_PROC when
someone wants the thread back.

Honest tradeoff: the pipe-drain half cannot be fixed by annotation at all
— `__saw_rt_proc_read_stdout` takes three arguments and is off-whitelist
(DF-181e). Reactor-integrating it is genuinely the shorter path.

### Class 2 — filesystem I/O (`std.file`, `std.directory`) — the contested one

| Option | Cost | Verdict |
|---|---|---|
| **Prompt-by-policy + a documented sentence** (Rust std, Go) | a network-mount stall wedges the executor | **RECOMMENDED** |
| Offload every fs call (tokio `spawn_blocking`) | a thread hop on EVERY read; under design-103 v1 that is a thread *creation* per read | **REJECT for v1** |
| Reactor-integrate | POSIX AIO is a dead end; `io_uring` is Linux-only and a large project | **REJECT (revisit if Linux-only io_uring ever becomes acceptable)** |

**Recommendation: prompt-by-policy, documented — do NOT offload file I/O.**
Three reasons, and one honest cost.

- Offloading costs a thread hop on every read. With thread-per-call v1 it
  is a thread *creation* per read, which would make a read loop
  catastrophically slower than the blocking call it replaced. Even with a
  real pool it is the wrong default for the common case (a local file that
  returns in microseconds from page cache).
- **Saw is kernels-and-embedded-first, and the freestanding profile has no
  threads at all** — design 103 explicitly rejects `blocking` externs
  there. A file API whose correctness depends on an offload cannot exist
  freestanding, so choosing offload splits the stdlib in two.
- Rust and Go have both held the "files are prompt" line for a decade and
  it has proved acceptable in practice.

The cost, stated plainly rather than hidden: **on NFS with a dead server,
on a FUSE mount, or on a FIFO, a read is unbounded and WILL wedge the
executor** — and `File.open` on a FIFO blocks until a writer appears even
locally. The docs must say this, in `std.file`/`std.directory` docstrings
and in LANGUAGE_SPEC, rather than leaving today's silence. Users who know
they are on a network mount need a real escape hatch, which is the offload
— so this recommendation is contingent on DF-181e (whitelist widening)
being available to them, even though std itself should not use it.

### Class 3 — `Channel.recv`

**Recommendation: prompt-by-policy with a real fence, not just a
mention.** `recv` is the thread-engine twin of the cooperative `receive`;
calling it from a task blocks the executor thread forever if no sender
ever arrives. Today's comment says which engine it belongs to but never
states the consequence. Since `receive` is a drop-in replacement, the
guidance is unambiguous and cheap: document it loudly, and consider making
`recv` inside a suspending body a compile error (it is exactly the kind of
mistake the type system could catch, and there is no legitimate reason to
call it from a task).

### Class 4 — executor-internal

No action. The reactor poll and the sleep park block on purpose; design
180 owns the sleep unification.

### Class 5 — `Mutex`

No action. Verified above: `sync`-enforced bodies make executor deadlock
unreachable.

## Findings filed

- **DF-181a** — `Command.run`/`output` starve every sibling task
  (P0-adjacent, DEMONSTRATED, pinned).
- **DF-181b** — every `std.file`/`std.directory` seam is naked and
  undocumented (P0-adjacent by reach).
- **DF-181c** — `Channel.recv` from a task wedges the executor unboundedly;
  docs do not fence it.
- **DF-181d** — `TcpStream.connect` silently ignores its `host` argument
  and always dials loopback; no DNS exists in the tree.
- **DF-181e** — the design-103 `(Int) -> Int` whitelist is too narrow to
  express the annotations this audit recommends.
- **DF-181f** — the `blocking` annotation is silently ignored on
  `__saw_rt_*` seams (compiler bug; gates the remediation).

## Suggested remediation order

1. **DF-181f first** — nothing else can be annotated until it is fixed.
2. DF-181a: reactor-integrate the stdout pipe; annotate the wait.
3. DF-181b: the docs sentence (cheap, honest, unblocks nothing else).
4. DF-181e: widen the whitelist so users have the escape hatch class 2
   assumes.
5. DF-181c / DF-181d: independent, small, and neither is urgent.

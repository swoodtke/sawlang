# Design 117 — runtime ABI v2: minimization (queued Aug 4)

USER DIRECTION (Aug 4): keep the `__saw_rt_*` ABI as SMALL as
possible. Three concrete reshapes: (1) errno accessors go away —
operations carry their own failure status; (2) the reactor becomes an
INSTANCE created through the ABI, not process-global seam state;
(3) the thread surface shrinks toward spawn/join. The Saw-level
TRAIT surface (Reactor/Thread objects consumed via dynamic dispatch)
is design 118 — it requires the executor itself to be Saw and is NOT
this brief; 117 reshapes the C boundary so 118 has the right floor.

The ABI was frozen at v1 (113); this is the sanctioned v2 revision —
made now, deliberately, while the only implementations are our two
host runtimes. ABI.md is rewritten as v2; v1 symbols removed here are
listed in a deprecation section. Behavior stays observably identical.

## 1. Errno accessors OUT — status-carrying operations

- DELETE `__saw_rt_errno`, `__saw_rt_errno_would_block`,
  `__saw_rt_errno_connect_state` from the ABI.
- Reading a thread-local global after the fact is a POSIX-ism: fragile
  (anything clobbers errno between op and read) and unimplementable on
  SOS, whose ratified syscall ABI is a (status, value) register pair
  with a small SysError tag space (sos/spec.md §5.7). Hosted runtimes
  must capture errno INSIDE the operation and return it.
- **Portable error tags.** Define `SysError` — a small fixed-ABI tag
  space documented in ABI.md (0 = ok; then WouldBlock, InProgress,
  Interrupted, ConnReset, BrokenPipe, NotFound, PermissionDenied,
  Exhausted, Other(hosted errno preserved for diagnostics), ... —
  agent proposes the exact set from what std actually consumes,
  pinned in ABI.md; deliberately convergent with the SOS SysError
  enum so hosted and SOS runtimes share one error vocabulary).
  The host runtime owns the errno→SysError mapping (per-host Saw
  code); std NEVER sees a raw errno again.
- **Every errno-reading call site moves inside the runtime.** Sweep
  std for callers of the three accessors (net is the known consumer;
  check file/process/env/time). Each such OS operation becomes a
  runtime function returning its status directly — pin (veto-able):
  the Linux-kernel convention, a word return that is >= 0 for
  success/count and a NEGATED SysError tag on failure (fits the
  @export whitelist, no aggregate returns needed, maps 1:1 onto the
  SOS (status, value) pair). std wraps into `Result<T, IoError>` at
  the Saw level exactly as today — user-visible behavior and error
  TEXTS unchanged where observable.
- The moved operations live in sawc/rt (Saw, per-host where
  divergent). This grows the ABI symbol count where an op crosses the
  boundary — acceptable; the MINIMIZATION target is the floor of
  C-expressed and globals-coupled surface, not raw symbol count; the
  errno CHANNEL (hidden global state in the contract) is what dies.

## 2. Reactor: instance-based, and finally in Saw

- New shape: `__saw_rt_reactor_create() -> ptr` returns an opaque
  reactor instance (owning its kqueue/epoll fd, wake pipe, AND its
  poll event buffer); `__saw_rt_reactor_register(r, fd, write, token)`,
  `__saw_rt_reactor_poll(r, timeout_ms)`, `__saw_rt_reactor_wake(r)`,
  `__saw_rt_reactor_destroy(r)` take the instance. The executor
  (still synthesized IR in this design) holds the process-global
  instance in the slot where it holds the reactor fd today —
  process-global becomes EXECUTOR policy, not runtime state.
- This dissolves DF-113d's blocker: the poll buffer is instance state
  allocated at create, so the reactor RELOCATES TO SAW (completing
  113b's one unfinished seam; delete the synthesized bodies). The
  per-call-stack-buffer language gap remains recorded as a future
  nicety, no longer load-bearing.
- Concurrency pin: match today's observable semantics exactly. If
  concurrent polls are possible today (MT groups), the instance
  buffer must be made safe the simplest way that preserves behavior
  (a poll mutex, or per-poll heap buffer — measure nothing, pick the
  simplest correct one, document in ABI.md). Design-91 token
  semantics, one-shot rearm, and design-102 cancel-wake are contract
  — regression-covered by the existing net suite.

## 3. Threads: shrink toward spawn/join

- Consolidate to `__saw_rt_thread_spawn(entry, env) -> handle` and
  `__saw_rt_thread_join(handle)`; the DF-113b fn-ptr thunk stays in
  shim.c (sanctioned). pthread_mutex/cond init seams stay (Saw-
  authored already, std.mutex consumers unchanged) — full Thread
  traitification is design 118. get_argc/get_argv stay (trivial,
  env-module consumers).
- Task/TaskGroup/spawn codegen call sites update to the new names;
  control-block layout unchanged (byte-identical behavior).

## 4. Docs + tests

- ABI.md rewritten as v2: the minimization principle, the SysError
  tag table, instance-reactor contract, the C floor (shim.c: DF-113a/
  b/c) with its deletion path, a v1→v2 deprecation table.
- Suite is the ratchet (998, zero xfails, every commit); bootstrap
  after net/reactor/thread groups; sos_runner per the standing bar
  (freestanding externs unaffected by design, but verify). New error
  tests only where the reshape creates new error surfaces.

## Non-goals

Saw-level Reactor/Thread TRAITS and executor relocation (118); any
std.net public API change; SOS runtimes; touching the frozen
`__saw_*` compiler-internal tier; new language features.

LANGUAGE-ISSUE POLICY (user, Aug 4 — supersedes "work around
visibly"): do NOT work around language bugs/limitations. Unambiguous
compiler bug in your scope → fix it with tests (sawc/ IS in this
brief's scope). Language design gap that blocks a unit → STOP that
unit, record a DF-117 tracker entry with a minimal repro AND the code
you wanted to write, continue only on independent units, and put the
blocker prominently in your final report. Pre-sanctioned exceptions
(the DF-113a/b/c shim floor) remain valid.

Bars: full suite zero xfails + bootstrap + sos_runner green per the
schedule above; per-unit commits (errno group per std module, reactor,
threads, docs); linear history; no attribution trailers; foreground
suites; interruption-safe. SEQUENCING: dispatch immediately (116 runs
concurrently in disjoint trees — selfhost/ + tools vs sawc/); design
118 dispatches only after THIS lands and integrates.

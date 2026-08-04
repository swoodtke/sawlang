# Design 118 — the executor in Saw: Reactor/Thread traits (queued Aug 4)

USER DIRECTION (Aug 4): the runtime's OS objects should be Saw
objects — `__saw_rt_reactor_create` returning something that conforms
to a Saw `Reactor` trait, threads likewise — with the `__saw_rt_*` C
floor as small as possible. The enabler is relocating the LAST
compiler-synthesized runtime layer, the cooperative executor/
scheduler, into Saw: synthesized IR can call C symbols but cannot
sanely do Saw trait dispatch, so trait-object runtimes require a Saw
executor. This is the riskiest compiler surgery since the coroutine
transform itself — it is STAGED, each stage suite-green, and stopping
clean at a stage boundary with a report is an acceptable outcome.

PREREQUISITE: design 117 landed (instance-based reactor, status-
carrying ops, minimized thread seams). Read 117's landed state and
ABI.md v2 before starting.

## Target architecture

- **Traits (in sawc/rt, Saw):** `Reactor` — register/deregister/
  poll/wake, token-based per the design-91 contract; `Thread` (or the
  minimal spawn/join surface the executor actually needs). Concrete
  per-host types (`KqueueReactor`/`EpollReactor`, `PosixThread`)
  implement them over the 117 seams or directly over externs. A
  future SOS-hosted runtime implements the SAME traits over syscalls
  (the kernel Waiter's word-sized key maps 1:1 onto the Reactor
  token) — that is the payoff being built here.
- **The executor moves to Saw** (sawc/rt or a std-internal runtime
  module — agent proposes placement): run queue, frame driving, wake
  words, sleep/timer queue, op-budget fairness, offload parking, MT
  TaskGroup engine — consuming the reactor through the trait.
- **The compiler keeps:** coroutine frame layout, the transform, and
  a SMALL documented set of entry points it emits calls to
  (spawn/enqueue/drive/park/wake — the executor's C-ABI face,
  Saw-authored under `--runtime-build` like every other seam). The
  synthesized-IR surface SHRINKS to those calls; the `__saw_rt_*`
  floor shrinks toward: alloc, write/panic + thread-thunk +
  set_nonblocking (the DF shim floor), and whatever the executor
  entry points need. ABI.md updated accordingly.

## Stages (each lands suite-green before the next; commit per stage)

1. **Map + carve.** Inventory every synthesized executor structure
   (run queue, wake words, budget, sleep handling, offload pipe
   parking, MT queue + workers) and every IR call site into it.
   Produce the entry-point list (the new boundary) as a doc commit in
   ABI.md BEFORE moving code — the lead reviews the boundary shape in
   the commit history.
2. **ST cooperative core.** Single-threaded executor (spawn/enqueue/
   drive/join, yield, sleep) in Saw behind the entry points;
   synthesized IR now calls the entry points only. Suite green.
3. **Reactor via trait.** `Reactor` trait + per-host concrete types;
   the executor's park/wake path goes through the trait (io_wait,
   design-91 precise wakeup, design-102 cancel-wake, op-budget
   force-yield). The white-box reactor tests (net_precise_*, io_wait
   examples) are the contract suite here — and the deferred design-
   114 io_wait-gating decision resolves NOW: those tests become
   std-internal unit tests of the concrete reactor types (relocate
   them or keep io_wait gated-to-std with the tests moved inside the
   gate — agent proposes, lead reviews).
4. **Threads + MT + offload.** MT TaskGroup engine, spawn/Task
   thread engine, blocking-extern offload parking — through the
   Thread surface. Send-checking and design-103 semantics unchanged.

## Behavior contract

Byte-identical observable behavior throughout: every design 21-115
concurrency semantic (structured join, eager spawn, fairness budget,
precise wakeup, cancel-wake, offload single-owner, Send checks, MT
counts-not-interleavings) is regression-covered by the existing 998
suite + bootstrap + sos_runner; those are the ratchet. No new public
API. No scheduler redesign — this is a RELOCATION.

## Non-goals

SOS runtimes themselves; scheduler algorithm changes; new concurrency
features; touching the coroutine transform's frame layout; Windows.

LANGUAGE-ISSUE POLICY (user, Aug 4): do NOT work around language
bugs/limitations. Unambiguous compiler bug in scope → fix with tests
(sawc/ is in scope). Language design gap that blocks a stage → STOP
at the previous stage boundary, record a DF-118 tracker entry with a
minimal repro AND the wanted code, report prominently. An executor
that cannot be expressed in Saw is itself a first-class finding —
expect gaps (this is the point); do not contort the design to hide
them. Pre-sanctioned exceptions: the DF-113a/b/c shim floor.

Bars: full suite zero xfails + bootstrap + sos_runner green per
stage; per-unit commits; linear history; no attribution trailers;
foreground suites; interruption-safe. SEQUENCING: dispatch ONLY
after design 117 lands and integrates; concurrent with 116 is fine
(disjoint trees).

# Design 225 — TaskGroup(threads: N) becomes a live pool

**Status: FULLY RULED — D-a..D-f RATIFIED AS WRITTEN WITH THE RECORDED
LEANS (user, Aug 16): workers start at FIRST SPAWN (D-a); idle workers
PARK immediately (D-b); the Send gate stays armed at construction (D-c);
op budgets are PER-WORKER (D-d); the deadlock report fires at the
nothing-runnable/nothing-parked/no-wake-source state and teaches both
engines (D-e); the determinism delta is STATED in docs, consumer sweep
pre-done by the DF-224 wake matrix (D-f). Units below; dispatched.**

**Earlier status: DIRECTION RULED (user, Aug 15) — option B, the live pool: workers
run concurrently with the owning thread from first spawn; fork-join is
retired as the contract. Ruled on the api-expected-not-easy doctrine plus
two evidence lines: `threads: N` is the ONLY fork-join member of its family
(`spawn {}` is live; a cooperative group's tasks progress whenever main
suspends), and two independent fresh writers hit the surprise within hours
(the cookbook's unwritable example; ck15 written naively). The sub-decisions
below are the agenda for the ruling session that precedes dispatch. This is
SMP-era runtime work pulled forward deliberately — hosted-first, where
gmgate and corodiff's MT axis are the existing oracles, ahead of the
kernel's IntrSpinLock-era equivalent.**

SEQUENCING: design 224 (the transform coverage gaps) lands FIRST — its six
silent-hang cells currently SPIN and must become honest parks/refusals
before executor work; and the deadlock report (a park with no possible wake
source) lands with 225 as the backstop, since a live pool does not make
every park satisfiable.

## What changes (from the DF-224 sweep's mechanism map)

- `TaskGroup.__enqueue` (taskgroup.saw:457-460): MT groups join the
  scheduling world instead of staying out of it; workers start at first
  spawn (or group creation — D-a below).
- The drain-time invariants RETIRE and their replacements are derived:
  "enqueue is main-thread-only" (taskgroup.saw:50-53) becomes a locked or
  lock-free enqueue; the unlocked slot-identity trio (:492-505) gets the
  same treatment.
- `join()` redefines: wait until the group's tasks are complete, workers
  persisting across joins; `Deinit` = signal no-more-work + join workers +
  eager teardown per design 124 — still deterministic, still a scope by
  ownership extent (DQ-222b's ruling carries over unchanged).
- The design-91 reactor gains a CROSS-THREAD WAKE (kqueue user event /
  eventfd / self-pipe per host) so a worker's `send` wakes a parked
  ambient scheduler on another thread. This is the piece SMP needs anyway.
- Op-budget fairness (design 127) gets a cross-thread answer (D-d).

## The decisions agenda (rule before dispatch)

- **D-a: worker lifetime.** Start N workers at group CREATION vs at FIRST
  spawn (lazy). Lean: first spawn — a group that never spawns costs
  nothing, matching the all-zero-static ethos.
- **D-b: idle workers.** Park on the queue's condvar/futex vs spin-then-
  park. Lean: park immediately; latency is not M2-era critical.
- **D-c: the Send gate timing.** Today the Send-on-frames gate arms at
  group construction (threads: N literal). Unchanged under B? Lean: yes —
  the gate is about frames crossing threads, which B makes MORE true.
- **D-d: op-budget across threads.** Per-worker budgets (lean — simple,
  preserves the backstop per thread) vs a shared pool.
- **D-e: what the deadlock report says and where it fires** (the ambient
  scheduler's nothing-runnable/nothing-parked/no-wake-source state), and
  its wording teaching both engines.
- **D-f: determinism story.** MT execution order was never deterministic
  (design 75); B widens WHEN nondeterminism can occur (before join, not
  only inside it). Consumer sweep per obligation 2: corodiff's MT axis +
  the two tracked MT-channel examples (both stay correct — same-group
  cells were green in the sweep's matrix); state the delta in the brief.

## Test plan seeds

The DF-224 sweep's 15-cell wake matrix flips to all-OK except genuinely
unsatisfiable parks (which report, not hang); ck15 becomes the headline
pin; the cookbook's Channel-fallback example gains the cross-thread
variant it could not honestly claim; corodiff --all MT axis; gmgate both
lanes (executor state under Guard Malloc); a soak case (N producers, M
consumers, main streaming) with bounded wall-clock.

## Units (staged — the biggest executor change since design 89)

**Unit 0 — rows + pins first (obligations 2+3).** The DF-224 wake matrix's
15 cells as conformance rows: the currently-hanging cells cited-XFAIL
against DF-224b (ck15 is the headline pin); the working cells as
must-keep accepts (same-MT-group receive/send; the spawn{} sender). D-f's
delta statement drafted here for unit 5's docs.

**Unit 1 — the cross-thread reactor wake.** The design-91 reactor gains a
wake primitive (kqueue EVFILT_USER / Linux eventfd; the rt/ABI.md seam is
NOT reopened — this is reactor.saw per-host code behind the existing
instance API). Standalone hosted test: a plain OS thread wakes a parked
reactor. This is the SMP-era piece, built first and alone.

**Unit 2 — workers live at first spawn (D-a), parking idle (D-b).** The
enqueue path goes concurrent (the run-queue mutex now guards enqueue as
well as claim); the unlocked slot-identity trio is re-derived or locked;
MT groups REGISTER with the ambient world enough that a worker's send
can wake it (via unit 1). The main-thread-only-enqueue and
size-stable-during-drain invariants RETIRE with their comments.

**Unit 3 — join/Deinit redefinition.** Workers persist across joins;
join = wait until this group's tasks complete; Deinit = signal
no-more-work + join workers + design-124 eager teardown. DQ-222b's
ownership-extent ruling carries over unchanged. Send gate unchanged (D-c).

**Unit 4 — the deadlock report (D-e).** At the ambient scheduler's
nothing-runnable/nothing-parked/no-wake-source state: report and abort
with the teaching text (both engines named). The ck15-shaped park that
unit 2 makes wakeable no longer trips it; a genuinely unsatisfiable park
does.

> **UNIT 4 IS BLOCKED — NOT BUILT, RULING OWED (Aug 16, dispatch report).**
> The state D-e names is UNREACHABLE, and the states that are the real
> deadlocks are not decidable without a change to what a channel wait IS.
> Evidence and the proposal are in the tracker under DQ-225n; the one-line
> version: **a cooperative channel wait is not a park.** `Channel.receive`
> loops on `try_receive` + `yield_now`, so a task waiting forever on a
> channel reports `remaining == 0` — READY — and the scheduler resumes it
> again immediately. Measured on the three deadlock shapes: main waiting on
> a channel nobody feeds, an ST task doing the same, and an MT task doing
> the same all spin at 100%-143% of a core indefinitely; a task that only
> sleeps parks at 1% and exits. So the scheduler never observes
> "nothing-runnable", and a report placed at that state would be dead code.
> A progress heuristic ("resumed N times with no state change") is not an
> acceptable substitute — a compute loop ceding through design 127's op
> budget is indistinguishable from it, so the abort would fire on correct
> programs. Building this needs the channel wait to become a park with an
> IDENTIFIABLE wake source first; that is a design decision about the wake
> vocabulary, not an executor detail, and it is exactly what
> STOP-DON'T-WORKAROUND says to report.

**Unit 5 — budgets (D-d) + docs.** Per-worker op budgets; LANGUAGE_SPEC's
TaskGroup section rewritten (the fork-join caveat dies; the ownership
paragraph stays; D-f's delta stated); the cookbook's Channel fallback
gains the cross-thread variant it could not honestly claim; skill digest.

## D-f — the determinism delta, as unit 5 will state it (drafted in unit 0)

MT execution order was never deterministic: design 75 said so from the start,
and the standing test rule — assert on counts and sums, never on interleaving —
is that statement's operational form. What the live pool widens is WHEN the
nondeterminism is observable, not whether it exists.

- **Before:** an MT group's tasks ran only INSIDE a `join()` or `Deinit` drain,
  and the drain joined every worker before returning. So the owning thread saw
  the group as a single atomic step: nothing of the group had happened before
  the drain, and all of it had happened after. Order among the group's own tasks
  was already unspecified; order relative to the owning thread was not, because
  there was nothing to interleave with.
- **After:** the workers run concurrently with the owning thread from the first
  spawn, so a task's effects — a channel send, an `Arc<Mutex<T>>` update, a
  print — become visible to the owning thread at an unspecified point between
  the spawn and the join. That is the point of the change, and it is what
  `spawn {}` and a cooperative group already did.

Three things do NOT change, and the conformance rows say so: `join()` is still
a barrier for the task it names (K58/K62), `Deinit` is still a barrier for the
whole group (K59), and `TaskGroup()` / `threads: 1` are still the deterministic
single-threaded engine (K60). What a program may rely on is therefore
unchanged in kind: results through handles, and shared state through
`Arc`/`Mutex`/`Channel`. What a program may NOT rely on — and could
accidentally have relied on before — is that a `threads: N` group has not
started yet.

Consumer sweep (obligation 2), pre-done by the DF-224b matrix: the same-group
cells were already green and stay green (K54/K55); the two tracked MT-channel
examples and `corodiff`'s MT axis exercise exactly those cells; nothing in the
tree reads an MT group's shared state between a spawn and its join, because
until now there was never anything to read.

## Gates

Per-unit suite; corodiff --all's MT axis + gmgate BOTH LANES at units 2-3
(executor state under Guard Malloc is the oracle for the locking work);
the unit-0 pins flip as units land; a soak case (N producers, M
consumers, main streaming, bounded wall-clock) lands with unit 3;
terminal full tracked battery. STOP-DON'T-WORKAROUND applies doubly: any
re-derivation of the slot trio that needs a language feature (atomics
shapes, lock granularity) is a report, not an improvisation.

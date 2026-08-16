# Design 178 — SOS M2 SKETCH (slicing RULED, agenda in progress)

**Status: FULLY RULED (user, Aug 15). Option A — the concurrent kernel:
interrupts + timers + threads + scheduler + Event + Waiter; channels and
memory objects are M3. D1-D6 RATIFIED AS WRITTEN, plus the carried
fault-don't-status item: BadHandle, BadOp and AccessDenied ALL become
faults — none survives as a status; statuses are reserved for exhaustion
and peer-death classes; `Unknown` stays a userspace mapping artifact.
D2's cost sentence is the recorded M3 tripwire: syscall latency bounds
interrupt latency — re-examine when any M3 syscall grows a loop.
The deliverable ladder below is now the M2 plan of record; every unit
per-arch-gated, branch parked for user review per SOS policy.
CORRECTION (Aug 15): pin 1 is ALREADY SATISFIED — design 158 landed
Aug 8 whole (the `__saw_bt_table` blob, tools/lldb_saw.py, the
in-process post-panic dump hosted + freestanding; the `bttable`
battery lane is its gate). The sketch's "first M2-track dispatch"
phrasing predated that landing by a day. The first REAL M2 dispatch is
therefore the trap/timer/interrupt-controller HAL unit.**

**Original sketch header (Aug 7):** M1+M1b+172 are landed: one arch-free
kernel, two HALs, typed handles / SosStatus / kind-scoped rights, sosimg v3,
the C floor at 207 stated-reason lines. This document proposes M2's SCOPE
for the user conversation — the decisions section is the agenda, not a
ruling. Standing pins that shape it are cited from ratified spec sections.

## The three candidate slicings

**Option A — the concurrent kernel (RECOMMENDED).** Interrupts + timers +
threads + scheduler + Event + Waiter. Channels and memory objects wait for
M3. The milestone proof is the microkernel money shot: a USERSPACE UART
echo driver — root server holds an Interrupt handle (§2 object table),
waits on it through a Waiter (§2.2), reads the device through the
design-112 driver idiom, no kernel driver code at all.

**Option B — IPC first.** Channels (§2.1 rendezvous + ReplyHandle) + Waiter
+ Event over the existing single-threaded kernel; interrupts M3. Cheaper
bring-up, but a blocking `receive` wants a real scheduler underneath, so
half of A gets built implicitly and unnamed.

**Option C — memory first.** MemoryObject/Mapping (§2.3/2.5 typed pools) +
loading a SECOND process; interrupts M3. Exercises the handle table
hardest, but defers everything that makes a kernel feel alive, and M1's
static grant window already covers the single-root case.

Why A: interrupts are the hairy foundation the 172 C-diet was explicitly
bought for; the design-158 pin (below) already sequences the debugger
tooling ahead of it; timers force the preemption questions while the
kernel is still small; and Event/Waiter are the two SMALLEST objects that
prove the handle machinery generalizes past System.

## Standing pins that bind M2 (already ratified/recorded)

1. **Design 158 unit (c) lands BEFORE interrupt bring-up** (approved Aug 6:
   in-binary task state tables + panic-time dump — "the sos task dump
   sells it"). This is the first M2-track dispatch, and it is compiler/
   tooling surface, not sos/.
2. **Every syscall is an object op** (§5.7) — new objects mean new op
   tables + rights enums (145 backed-enum idiom), never new syscall shapes.
3. **Handles are (slot, generation)**; new object kinds join the typed-
   handle scheme (M1's ratified asymmetry: alias flows out, construction
   gated in dispatch).
4. **IntrSpinLock (§9b)** is the M2-era lock; v1 proposal below avoids
   needing it immediately.
5. **arm64 FP state is not saved across traps** (M1b's recorded
   inheritance).
6. **Fault, don't status (ratified Aug 8, from the 180 review).** A caller
   error the process could have checked — an invalid or stale handle, a
   malformed op, a rights violation — TERMINATES the offending process
   (the kernel stays up; it is the process's bug, the same line the
   language-level accessor rule draws). SosStatus returns are reserved for
   conditions the caller could not reasonably know: memory exhaustion, a
   peer process dying mid-operation. This cuts userspace error handling to
   the cases that are real. M2 agenda item: restate the op tables under
   this rule and decide which of BadHandle/BadOp/AccessDenied survive as
   statuses at all (candidate: none — all three become faults; `Unknown`
   stays a userspace mapping artifact per §5.7).

## Proposed simplifications to ratify (the decisions agenda)

- **D1: processes stay integer-only in M2.** DF-162a made freestanding
  aarch64 NO-FP by default, and the root server builds under exactly that —
  so the FP-context-switch question can be DEFERRED WHOLE: no FP state to
  save because no process may generate any. Revisit when the Float family
  (173) meets userspace. riscv32 mirrors (no F extension enabled).
- **D2: kernel is non-preemptible in v1** — interrupts taken from USER mode
  only (kernel runs with interrupts masked, M1's discipline retained inside
  syscalls). Kills the IntrSpinLock dependency for M2; §9b implements in
  M3/SMP. Cost: syscall latency bounds interrupt latency — fine at M2's
  syscall lengths.
- **D3: the scheduler is round-robin over runnable threads, timer-driven,
  ONE core.** No priorities in M2 (the §7 priority map stays a loader
  artifact until M3); `yield` op + block-on-wait + timer preemption only.
- **D4: Thread and Process become real objects** (spec §2 table rows) with
  create/start/exit/join ops, teardown per the ratified §2 Process row
  (close-all, free-owned); still ONE address space domain per process via
  the M1 grant mechanism (real Mapping objects are M3, per option A).
- **D5: Event (OR + saturating-sum, §2.4) and Waiter (level-triggered,
  persistent attach, §2.2) exactly as ratified — no deviations proposed.**
- **D6: Interrupt object** binds an IRQ line to a waitable (§2 table);
  ack via the handle; PLIC (riscv32) and GIC (arm64) bring-up live in the
  HALs behind the seam 172 hardened — kcore stays arch-free.

## Deliverable shape (if A + D1-D6 ratify)

Units roughly: 158(c) first (separate dispatch, compiler surface) →
trap/timer/PLIC/GIC HAL work → Thread/Process objects + scheduler →
Event/Waiter → Interrupt object + the userspace UART echo proof → spec
updates + the M2 test set (both arches, sos_runner grows again). Every
unit per-arch-gated like M1b; SOS policy: branch parks for user review.

## UNIT 1 — trap / timer / interrupt controller (BUILT Aug 15, branch PARKED)

The first real M2 dispatch, and the foundation the next three units stand on.
Both profiles, gated together, 38 harness cases.

**The seam.** Each HAL gained twelve names and the kernel reaches interrupts
through those and nothing else: `is_interrupt(cause)`, `IRQ_NONE`, `IRQ_TIMER`,
`intc_init`, `irq_unmask`, `irq_mask`, `irq_claim(cause)`, `irq_complete(line)`,
`timer_start(period_us)`, `timer_rearm`, `timer_pending`, and
`irq_raise_selftest_line`. `fault_pc` became `trap_pc` — the value never was
fault-specific and the tick path reports it. Both `ABI.md` files carry the
table and what each machine does differently.

**One funnel, two hooks (obligation 1).** `ktrap` decides interrupt / fault /
syscall IN THAT ORDER — an interrupt is not the running program's business and
its instruction has not run, so it must never reach the syscall return path,
which steps the saved PC. An interrupt goes to `service_irq`, the single
arch-free entry: claim the line, rearm the timer OR mask the device line (spec
§9), run the hook, complete. The hooks are `on_timer_tick(frame)` — where the
scheduler's timeslice accounting goes — and `on_external_irq(line)` — where the
Interrupt object will mark itself ready. Both are empty of policy today and say
in their docstrings what they must not grow into: they run with interrupts
masked, so their length IS interrupt latency.

**D2 is enforced by the machines, not intended by the kernel.** Profile A never
sets the global interrupt enable, and its architecture delivers to a lower
privilege mode regardless of it — so that bit staying clear IS "user mode only",
and a wrongly-arrived interrupt hits the mode witness and the kernel-bug path.
Profile B masks at EL1 throughout, unmasks only in the SPSR the user-mode return
loads, and routes all four current-EL vectors to the kernel-bug path. Neither
kernel needs a critical section; `IntrSpinLock` (§9b) stays unbuilt and unneeded.

**What each machine does differently**, because the seam hides it and a porter
should not have to rediscover it: Profile A's timer is a memory-mapped core-local
comparator that is NOT one of its controller's sources (so `IRQ_TIMER` there is a
number one past the last real source, and `irq_complete` does nothing for it),
its counter is 64 bits on a 32-bit machine (carry-safe read, all-ones-first write
order), and a line is masked by PRIORITY because that controller ignores a
completion for a disabled source. Profile B's timer IS a controller line, so
every tick runs the ordinary claim/complete cycle; its controller version is
pinned on the emulator command line rather than defaulted; and its interrupt
vector calls `ktrap` with a cause the syndrome register cannot hold.

**The proof** (`make sos-test`, 19 cases per machine): `timer_tick` — armed,
into user mode, tick 1 and tick 2 land in the arch-free hook with the
interrupted user-mode address on each line; `timer_masked_in_kernel` — the
kernel spins until the timer is DUE, reports `ticks taken=0`, and the tick
arrives only after the entry to user mode (D2, read from the order);
`external_irq` — a line raised in the kernel, claimed, masked and completed in
user mode, which is the only coverage Profile A's controller gets since its
timer never reaches it.

**C floor: 135 to 140 code lines.** One line on Profile A (the interrupt-class
mask register), four on Profile B (its timer is system registers, one
instruction each) — reason 1 in every case. Everything else is Saw: both
controllers, the comparator arithmetic, the periods, the policy. Assembly: +13
lines on Profile B (an interrupt vector entry that shares the frame save, now a
macro, and the return path with the syscall entry), none on Profile A, whose
trap entry already handled every trap from user mode.

**Not built here, deliberately:** Thread/Process, the scheduler, Event/Waiter,
the Interrupt object — the next three units. `sos/kernel/main.saw` arms no timer,
so the real kernel boots exactly as it did.

## UNIT 2 — Thread / Process objects + the scheduler (BUILT Aug 15, branch PARKED)

D3 and D4 as ratified, over unit 1's tick. Both profiles, 22 harness cases each,
44 total.

**The trap frame IS the thread context, and that is the whole context switch.**
A thread's saved registers are the frame the HAL's trap entry already wrote on
the way in and read on the way out, so a switch is `ktrap` RETURNING A DIFFERENT
FRAME ADDRESS than it was called with. One switch point; at the user-return
boundary by construction, which is D2 enforced by the shape rather than
promised; no half-saved state to protect, because the kernel never holds one.
Entering user mode for the FIRST time is the same operation with a frame nothing
has run in, so `enter_user` — a context built by zeroing thirty registers in
assembly — is gone from both HALs, replaced by `frame_init` (Saw) and
`resume_frame` (a mode select and a branch into the trap entry's own restore
path). Each machine already had a "current thread" register to carry the frame
between traps and neither needed a new one: `mscratch` on Profile A, `SP_EL1` on
Profile B.

**One way into user mode.** `kcore.start_process` reifies a program as a Process
with one Thread and resumes its frame; the loader reaches it with a root image,
and the four harness kernels that grant a hand-written payload its own bytes
reach it with theirs. A kernel that could enter user mode WITHOUT a Process
would be a kernel with syscalls no handle table answers, which is what M1 was.

**The faults ruling, applied whole.** BadHandle, BadOp and AccessDenied are gone
from `SosStatus` — they are `FaultReason` tags now, keeping their numbers — and
meeting one terminates the process while the kernel stays up to report it and
the ratified teardown (close all handles, free every thread and frame). It had
to be uniform: an unbound handle names no KIND, so there is no op table to ask
which rule applies. `umode_bad_calls` therefore asserts the opposite of what it
asserted the day before, and both payloads say so. What is left as a status is
`NoResource` — a full slab, which a caller could not have known.

**Naming, ruled at review (user, Aug 15).** An op table or a rights set is named
for the spec §2 OBJECT it belongs to, spelled out, plus §5.7's own suffix:
`SystemOp` / `ProcessOp` / `ThreadOp`, `SystemRight` / `ProcessRight` /
`ThreadRight`. No abbreviated object prefix — the four characters `Sys` saves in
a file nobody types into cost every reader the question of whether it means the
System object or the syscall. The rule extends to anything else named after an
object, and `sos/kernel/abi/`'s module docstring carries it so the next object
kind cannot drift.

**Two ops per object, and derivation doing work.** System gained `SelfProcess`;
Process has `CreateThread` / `SelfThread` / `Exit` / `GetStatus`; Thread has
`Start` / `Join` / `Exit` / `Yield`. Root's boot register is still ONE handle
wide and everything else arrives through it, which is §3's derivation rule
earning its place rather than being quoted. `Process.Kill` and `CreateProcess`
are deliberately absent: with one process the first is `Exit` under a second
name and the second has nothing to load, and an op whose only reachable use is
degenerate is an op nothing tests.

**The proof, per machine.** `thread_basics` boots under a kernel that arms NO
timer: two workers print and yield, and the transcript reads `ABABABAB` — one
substring, eight switches, nothing but a `yield` able to cause any of them —
then joins both for 11 and 22, each worker's own value. `thread_preempt` is the
same shape with the yields REMOVED and the tick armed: `BABABABABABABABA` on
Profile A, `AABBAABABABABABB` on Profile B, sixteen switches nobody asked for.
`thread_fault` joins a handle it never held and is terminated for it, reported,
torn down, exit status 5.

**The native floor: assembly 342 to 268 code lines, C 140 to 166, total 482 to
434.** The assembly went DOWN because a context built in Saw needs no
register-clearing prologue in either HAL. The C went UP by exactly one function
per profile — `sos_syscall3`, three arguments in and the value register back out
through a pointer, because the ops that answer with a value need one and the C
ABI the Saw side declares against has no aggregate return. Reason 1 in both
cases, and the diet's direction is unchanged.

**Three findings, filed rather than worked around silently: DF-178c** (a process
cannot name a function's address, so `create_thread` has no entry a Saw program
can compute — the M2 API answers it with an image-entry overload and the real
fix is DF-172a's reason 3), **DF-178d** (a `-> Never` call is not accepted as a
`guard ... else` exit and emits malformed IR in some value positions), and
**DF-178e** (a bare literal does not adopt an annotated type through a `match`).

**Not built here, deliberately:** Event and Waiter — the wait/wake SUBSTRATE is
in (block, joiner lists, a wake that writes the sleeper's syscall return exactly
once) and the objects that will attach to it are the next unit. No priorities:
D3 keeps the §7 map a loader artifact, and the kernel still parses and reports
it. No idle loop: with no external wake source, "nothing runnable" is a genuine
deadlock in M2 and is reported as one; the wait-for-interrupt loop arrives with
the first object that can be signalled from outside.

## UNIT 3 — Event and Waiter (BUILT Aug 15, branch PARKED)

D5 as ratified, no deviations. Both profiles, 25 harness cases each, 50 total.

**Five object kinds where there were three, and the dispatch did not move.** An
Event and a Waiter cost one `struct`, one `allows`, one arm in `dispatch` and
one op table each — which is the claim §3 has been making since M1, tested for
the first time by objects that are neither singletons nor scheduler internals.
The handle table, the typed-handle construction after validation, the per-kind
rights scoping and the ratified teardown all took them with no shape change.

**Level-triggered is an ABSENCE, and that is the implementation.** Nothing
records that a waiter has been told about a ready event, so `Wait` SCANS the
attachment set for a non-zero word. Three ratified sentences fall out of that
one decision rather than being coded separately: a signal that lands before
anyone waits is not lost (§2.2's no-lost-edges), an event still ready after one
waiter has been woken is still ready for the next, and attaching an
ALREADY-ready handle reports it immediately — which is the order "signal, then
attach, then wait" that an edge design drops on the floor. An edge-triggered
Waiter would have needed a reported-flag per attachment and would have lost the
first of them.

**§2.4's saturation is a correctness requirement, not a nicety**, and it is
worth stating why in one place: zero is what "not ready" MEANS, so a counting
event that wrapped would go quiet exactly when its producer was fastest. The sum
uses the wrapping add and a carry test; the OR mode saturates by being
idempotent.

**The result shape.** SUPERSEDED BY RIDER 3 (below): the unit first widened the
ABI with a second value register and a `sos_syscall1_pair` per profile. The
ruling replaced that with a validated copy-out, which is both the smaller ABI
and the shape §2.1's message body needs anyway. What survives unchanged is the
key: handed back unread, because §2.2's point is that a word can encode the
waiting task's identity.

**One funnel for a syscall's answer (obligation 1).** `write_result` is now the
only place an answer reaches a frame, and its docstring names its three entry
points: the return path, a joiner wake, a waiter wake. Two of the three write
for a caller that was answered by nobody when it blocked, which is the invariant
the parking protocol rests on — exactly one write per syscall, or the saved PC
steps twice on the profile that steps it at all. **Waitability is the second
funnel**: `waitable_slot` decides in ONE exhaustive match both whether a kind
can be attached and whether the holder may, because which enum a rights word is
read against is decided by the kind — the two questions are one question, and
every case is spelled out so the next waitable kind cannot be added silently.

**Creation authority answers a §12 open pin.** `CreateEvent` / `CreateWaiter`
are Process ops on their own rights bits, so the Process handle IS the factory
capability rather than a quota — §3's derivation rule instead of a new
mechanism. A quota stays additive: a field on the process slot, checked where
`NoResource` is returned today.

**Faults, per the ruling**, with two new tags: `NotWaitable` (attaching
something that is not) and `BadArg` (a creation mode that is not a mode).
Attaching an already-attached handle and removing one this Waiter does not hold
are `BadState`. Every one is a mistake only the caller could have made.

**The proof, per machine.** `event_basics` is one thread and no timer, so
nothing in it is about scheduling: signal-then-wait answers with the right key,
a second attachment is told apart by its key alone, `1|2|1` is 3, five counted
signals are 5, and two signals of the largest word there is saturate instead of
wrapping. `event_wake` is the parking half and is read as an ORDER — the
worker's line lands BETWEEN the initial thread's "parking" and its "woke",
which it could only do if the first thread blocked, since that kernel arms no
timer and `start` does not switch. `umode_not_waitable` is a hand-written
payload, for the same reason `umode_bad_handle` is one: `Waiter.add` takes an
`&Event`, so attaching the System object is not a thing a Saw process can spell
— the typed layer's guarantee putting the kernel's own validation test at the
raw altitude.

**How two threads of one process share a kernel object**, since `event_wake` is
the first program that needs to: not by passing a handle word, which the ruled
typed layer makes unspellable, but by parking the `Event` VALUE in the process's
own memory. The kernel is not involved — the handle TABLE is the process's and
both threads were already inside it.

**Native floor: UNCHANGED, 268 assembly and 166 C code lines** — the pair stubs
that briefly took C to 194 are gone with rider 3, so the whole unit's native
delta is zero. An object model grew by two kinds and the machine-specific code
did not move.

**Not built here, deliberately:** the Interrupt object and the userspace UART
echo proof — the next unit, and the one that turns `pick_next`'s deadlock report
into an idle loop, since an Interrupt is the first readiness that arrives from
outside the set of runnable threads.

### Unit 3 rider — an argument encoding is API (ruled Aug 16, user)

The unit first offered `create_event()` / `create_counting_event()` to keep
`EventMode`'s wire value inside kernel-internal `sosabi`. **Reversed**: the mode
is a value the CALLER chooses, so it is spelled as one —
`create_event(mode: EventMode.SaturatingSum)`, with `EventMode.Or` as a default
so the common call stays `create_event()`. A method per mode reads fine at two
and stops scaling at the next object: M3's Mapping brings an access mode AND a
memory type, and a method per combination is a matrix rather than a list.

**The line, recorded in the `sos` module docstring for Mapping to inherit: the
vDSO discipline is about OP NUMBERS, not argument encodings.** An enum whose
values a process chooses and passes as a syscall argument is public,
single-declaration API; op numbers, rights bits, `ObjType` and `FaultReason`
stay kernel-internal, which is what keeps renumbering free.

**Mechanism: Saw's imports RE-EXPORT, so one declaration serves both halves.**
`sosabi` keeps the declaration the kernel's dispatch decodes, `sos` imports it,
and a process writes `import sos.{EventMode}` — no redeclaration, no new module,
no kernel change. Two things learned by probing rather than assuming, both worth
having on record:

- **The re-export is INDISCRIMINATE.** Everything a module imports is reachable
  through it, op numbers included — and `sosabi` is on a process's module path
  as a transitive dependency anyway. So the split above is held by what
  userspace is TOLD to write, not by a wall. That was already true before this
  rule; the rule only decides which side each family sits on.
- **The enum cannot MOVE into `sos` instead.** A Saw import compiles the whole
  module into the unit, and `sos` and the kernel HAL export the two runtime
  hooks under the same C names for their two sides — so a kernel importing `sos`
  is a duplicate-`@export` error on `sos_rt_write` and `sos_rt_abort`, before
  any question of the undefined `sos_syscall1` it would also pull in. Probed
  directly.

### Unit 3 rider 3 — the wait answer becomes a validated copy-out (ruled Aug 16, user)

The unit's `(key, readiness)` register pair is REPLACED, and with it the two C
stubs it needed. `Waiter.Wait` now takes a buffer and a capacity on the ordinary
three-argument syscall shape, and the kernel COPIES OUT a record. **This is the
one place a ratified spec section has changed** — §2.2 carries the amendment and
cites this rider.

**Why the record wins.** The KEY is universal and the PAYLOAD is not: a
Channel's readiness is not a Timer's is not an Event's. A register pair would
have had to be the union of every waitable's answer forever, and the register
file is the one thing that cannot grow. So the shape is `key` word, `tag` word,
payload words — the tag a raw-backed enum with an extensible space, the sizes
and offsets public constants, one declaration serving the kernel that writes it
and the `sos` module that decodes it (the re-export convention rider 2
established, now covering records as well as argument enums).

**The Event's payload is its accumulated word, and it is a SNAPSHOT.** That
makes the common wait one syscall instead of two, and the `event_wake`
transcript shows the seam honestly: the worker signals five times, the FIRST
wakes the sleeper, so the record reads 1 and the following `receive` drains 5.
Neither is wrong — the record says what the wait was woken FOR, `receive` says
what has accumulated — and filling the record at resume instead would move a
user-memory write away from the wake and buy nothing, since the count can go
stale again before the thread reads it.

**COPY-OUT IS A FUNNEL BUILT ON ITS FIRST USE (obligation 1)**, because the
second use is already specified: §2.1's Channel `receive` is this operation with
a bigger length. `copy_out(p, dst, src, bytes)` is the ONLY place the kernel
dereferences a user address; it refuses a destination that is not word-aligned
(`BadAlign`) or not inside the process's writable window (`BadBuffer`), and both
are FAULTS — a process linked its own image and knows where its data is. Its
docstring names its consumers: Waiter now, the Interrupt object's result next,
M3's Channel body after. Two things follow from having exactly one door: the
per-address-space mapping switch M3 needs is a one-place change, and the
writable window is one field pair on the process rather than a check scattered
per op.

**The window comes from the loader**, which now records where a process's
writable grants are (its `Write`-flagged segments, plus the stack it is given).
The four harness kernels that grant a payload its own bytes read+execute pass
NOTHING and get an empty window — which is the honest answer for a process with
nowhere to receive a record, and is what makes the two fault payloads need no
particular address.

**AN UNKNOWN TAG PANICS** in the userspace decode rather than becoming an `Err`.
The kernel wrote that tag, out of the same declaration the decode reads, so a
tag userspace cannot name is a kernel/`sos` skew — a bug in the pair, not data
from an untrusted source — and never-hide says it should be loud.

**C delta: NET NEGATIVE, back to the pre-pair floor.** `sos_syscall1_pair` is
deleted from both profiles and `syscall_return_pair` from both kernel HALs; C
goes 194 -> 166 and assembly stays 268, so the whole unit's native delta is
zero. The seam has the shape it had in M1, and an op whose answer does not fit a
word grows a buffer argument rather than a register.

**Proof: 27 cases per machine, 54 total.** The two new ones are the funnel's two
rejection rows — a destination outside the writable window and one that is not
word-aligned — each a payload, because the typed `Waiter.wait` supplies its own
buffer out of its frame and never lets a caller name one. They are told apart by
the CHECK ORDER (alignment first), which is stated in `copy_out_check` and
asserted by the pair.

**One finding: DF-178f** — `sizeof<T>()` does not fold in a static initializer,
though design 186's own diagnostic lists it among the things that do. Filed, and
routed around in the open: the two sizes that wanted it are small functions with
the reason written beside them.

### Unit 3 rider 4 — `remove` names the attachment, not the waitable (ruled Aug 16, user)

`WaiterOp.Remove` takes the KEY. Detaching edits the WAITER's own attachment
table and never touches the waitable, so the authority it spends is the Waiter
handle the dispatch already validated plus the key — asking for the waitable's
handle as well would be asking for authority the operation does not use, and the
old form spent an `EventRight.Wait` it had no business spending. It is also the
only form that survives M3: once handles can be CLOSED, a closed waitable's
stale attachment has no handle left to name it with, and a handle-based remove
could never reach it. §2.2 carries the amendment.

**The invariant it forces, now stated: KEYS ARE UNIQUE PER WAITER.** `Add` with
a key the Waiter already uses is a FAULT (`DuplicateKey`). It has to be refused
rather than tolerated because a duplicate makes two questions ambiguous at once
— which attachment a `remove` names, and which one a wait answer came from — and
the attacher chose both keys, so it is caller-checkable in the strongest sense.
The attachment set is walked BY KEY for both operations, which is the same walk
and therefore one place to be wrong.

**Its test is the one fault case in this unit written in ordinary Saw**, and
that is worth noticing rather than incidental. The others are hand-written
payloads because the typed layer makes their mistakes unspellable — you cannot
name a handle you were not given, and `wait` supplies its own buffer. A
duplicate key is different: both Events are real and both keys are the caller's
own words, so no type can catch it and the check must be the kernel's. The test
therefore lives at the altitude a real process would hit it from.

**A harness defect surfaced with it and was fixed rather than worked around.**
The arch-free seam scan is substring-based, and `plic` is inside "duplicate" —
also "explicit", "implicit", "complicated", "replica". A check that exists to
police the kernel's DEPENDENCIES was about to dictate the kernel's VOCABULARY,
which is backwards. The scan now suppresses a hit only when the token has a
letter on BOTH sides: real leaks are prefixes or suffixes of longer identifiers
(`mtimecmp`, `csrw`, `PLIC_BASE`, `gicd_ctlr`, `cntfrq_el0`) and all still fire,
while a token buried mid-word is English. Verified against eighteen real leak
spellings and seven English sentences before it was trusted.

### Why `Waiter.add` is OVERLOADED per waitable kind, and not generic

Recorded because the alternative is the obvious one and the reason it is refused
is a LANGUAGE fact rather than a taste (ruled Aug 16, user).

The tempting shape is `add<T: Waitable>(_ w: &T, key: UInt)` over a public
`Waitable` trait. It cannot be that, because the requirement such a trait needs
is one that PRODUCES A HANDLE — that is the only thing `add` wants from its
argument — and under Saw's ORPHAN RULE a public trait in the `sos` module can be
conformed by any module that owns a type. So any process could declare its own
`struct Forged`, conform it, and return whatever handle word it liked from the
requirement: a forged-handle door straight through the guarantee the typed layer
exists to provide. Saw has no SEALED traits, so there is no way to publish the
trait and withhold the ability to conform to it.

Overloads have no such door and cost nothing here, because **kinds are a LIST**:
Event now; Channel, Timer, Interrupt and ReplyHandle as they land; a method
each. That is the same list-vs-matrix rule that pushed `create_event`'s MODE the
other way — modes multiply (M3's Mapping has access × memory type), so a mode is
a value, while kinds enumerate, so kinds are overloads.

**The future shape, when it is earned:** a WITNESS-SEALED trait — the
requirement returns a module-private type with no public constructor, so only
`sos` can satisfy it and the trait is effectively sealed without language
support. The trigger is a real consumer that is generic over waitables, which is
M3 wait-library territory (a `HandlerGroup`-shaped dispatcher, §10). At that
point the language question worth ruling is whether Saw wants sealed traits
outright, since the witness idiom is a workaround for their absence and would
read better spelled.

## Explicitly out (M3+ candidates)

Channels + ReplyHandle IPC; MemoryObject/Mapping + multi-process loading;
SMP + IntrSpinLock; priorities; FP in userspace; the vDSO true-mapping
upgrade; big-endian anything.

## M3 memory notes (Aug 15 conversation, user + lead — seed for the M3 sketch)

PMP facts that shape MemoryObject/Mapping, established in conversation
after unit 1's DF-178b work:

- **The kernel costs ZERO slots.** M-mode is unchecked by PMP (absent
  L-bit entries) — exception entry always reaches kernel code/stacks —
  and S/U default-deny protects kernel memory with no entry at all.
  L-bit hardening (kernel code RO even from M-mode) is an optional 1-2
  entries, not architecture.
- **Slots are per-hart, reloaded at context switch** — the 16-entry
  budget is the RUNNING process's concurrent-region cap, not a
  system-wide partition. Switch cost: a dozen CSR writes.
- **The region model** (user-proposed, fits): contiguous image layout
  code|rodata|rw, TOR-chained = ~4 entries per process (base + 3);
  stack at the RW edge gets overflow faults free from default-deny;
  +1 NAPOT entry per granted device window (driver processes only).
- **Shared memory needs no MMU** under switch-reload: 1 entry in each
  sharer's loaded set. The real PMP limit is NO TRANSLATION — one
  physical address for every sharer — so Mapping ADDRESSES ARE
  KERNEL-ASSIGNED (returned from map, never process-chosen).
- **Portable contract = the PMP floor**: page-granular (G may be
  page-size on real silicon — byte-tight grants are not portable),
  identity-mapped, contiguous objects. Translation hardware (arm64's
  MMU today, an ESP32-P4-style minimal MMU someday) is a HAL bonus
  behind the same seam, never the contract.
- **Open for the M3 sketch**: (a) heap growth under contiguity —
  per-process arenas sized at spawn vs grow-by-relocation;
  (b) the documented per-process mapping cap (candidate 8), with
  over-cap map() a FAULT per the ratified faults rule
  (caller-checkable against a documented cap).

## FINALE UNIT CONSTRAINTS (ruled in conversation, user, Aug 16 — the
## Interrupt + userspace-UART-echo dispatch folds these in)

1. **The UART MMIO grant is a STATIC BOOT-TIME DEVICE GRANT** — M1's
   grant machinery extended by one declarative device window (named in
   the root's image/boot config, not hardcoded in kernel logic), and
   explicitly marked as the placeholder M3's Mapping retires (device
   memory then = a MemoryObject with device attributes; this grant is
   its migration case).
2. **riscv32**: one PAGE-ALIGNED NAPOT PMP entry over the UART page
   (virt NS16550, 0x1000_0000) — the DF-178b lesson applies literally
   (a byte-tight device grant puts every register access on QEMU's
   slow path).
3. **arm64**: the EL0 mapping carries DEVICE memory attributes (nGnRE),
   never Normal-cacheable — a cacheable PL011 mapping is a correctness
   bug — plus device-memory access-size discipline (32-bit registers).
4. **UART ownership handover protocol**: both machines have ONE console
   UART and the kernel currently owns it (debug_print board sink).
   After boot handover the kernel goes QUIET on the device — root
   drives it — and the kernel reclaims only on panic, where
   interleaving is acceptable because the test already failed. State
   the protocol in the unit; unstated it is a flaky-test mystery.
5. The Interrupt object consumes unit 3's copy-out funnel with its own
   WaitPayload variant, per the wait() redesign.

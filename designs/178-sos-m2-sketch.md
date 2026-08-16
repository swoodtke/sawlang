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

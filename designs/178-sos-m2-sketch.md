# Design 178 — SOS M2 SKETCH (slicing RULED, agenda in progress)

**Status: OPTION A RULED (user, Aug 15) — M2 is the concurrent kernel:
interrupts + timers + threads + scheduler + Event + Waiter; channels and
memory objects are M3. The D1-D6 agenda below is being taken with the user;
each item's ruling is recorded inline as it lands. Design 158 (the task-dump
pin, unit c before interrupt bring-up) dispatches at 223's integration —
its unit 1 shares coro_transform with the in-flight 223 agent.**

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

## Explicitly out (M3+ candidates)

Channels + ReplyHandle IPC; MemoryObject/Mapping + multi-process loading;
SMP + IntrSpinLock; priorities; FP in userspace; the vDSO true-mapping
upgrade; big-endian anything.

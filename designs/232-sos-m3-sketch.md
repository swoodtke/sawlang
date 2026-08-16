# Design 232 — SOS M3 SKETCH (agenda for the scoping session)

**Status: SKETCH.** This document proposes M3's SCOPE for the user
conversation — the decisions agenda at the bottom is the session, worked
item by item. What it does NOT reopen: the Aug-16 seed rounds in
designs/178 ("M3 TIME NOTES", "M3 device-grant + memory-surface
rulings", rounds one through four) are RULINGS, carried in here by
reference and lifted only where slicing needs them. M2 is integrated
and verified on main (Interrupt + userspace UART echo, both arches);
the M2 spec-recap unit (§11 refresh) is still owed and is proposed
below as unit 0.

## What M3 has on its plate (the full candidate surface)

From spec §2's unratified rows, 178's "Explicitly out (M3+ candidates)"
list, and the seed rulings:

1. **Clock/Timer** — API shape user-ruled (178 time notes): granted
   Clock capability, clock-bound Timer, drift-free interval re-arm,
   coalesced fires via WaitPayload.Timer(fires:), the COPY-IN funnel
   (arm()'s 64-bit inputs exceed rv32 registers). Closes the
   process-sleep gap.
2. **CreateProcess + multi-process loading** — a second address space,
   the launch flow. Everything the device-grant rulings assume (root
   LAUNCHES children) rests on this.
3. **The device grant + memory surface** — fully ruled (178 rounds 1-4):
   `bind_iomem`/`bind_interrupt`/`alloc_memory` as rights-gated System
   ops, stripped from children by construction; Memory / IoMemory /
   MemoryMapping with inverted drop semantics; `give` + `boot_handles`;
   manifest device NAMES over root's board table. Retires the M2
   loader device-window grant (pinned as its migration case) and
   ProcessOp.BindInterrupt (op 6, bit 8192).
4. **Quotas** — ruled: per-process, dynamic-creation kinds only, hard
   limits only, `QuotaExceeded` status, creator pays, orphan written
   off.
5. **Channels + ReplyHandle IPC** (§2.1, ratified semantics).
6. **Process-death notifications** — new from round 4; two named
   consumers (root supervision now, the M4+ IOMMU driver later).
7. **Priorities / §7 band map, SMP + IntrSpinLock, FP in userspace,
   vDSO true-mapping** — the standing M3+ tail.

Items 1-4 form a coherent milestone; 5-7 do not fit beside them.

## The three candidate slicings

**Option A — the multiprocess kernel (RECOMMENDED).** Units 0-7 below:
Clock/Timer, then CreateProcess + the launch flow, then the ruled
device/memory surface, then quotas. IPC waits for M4. The milestone
proof is the natural sequel to M2's money shot: **the same UART echo
driver, launched as a CHILD of root from config** — root reads
`devices = ["uart"]`, binds the window and the line, gives both to a
process it created, and the child maps its own registers and echoes.
No driver in the kernel (M2's proof) and now no driver in root either.
A second, cheaper proof rides along free: two processes sharing memory
through `give` — the token-travels property demonstrated live.

**Option B — IPC first.** Channels + ReplyHandle over the M2
single-process kernel; CreateProcess deferred. Rejected shape: with one
process there are no interesting peers (root rendezvousing with itself),
so the tests prove plumbing rather than IPC — and the device-grant
rulings, which are hot and complete, would sit unbuilt for a milestone.

**Option C — A plus channels.** Everything at once. M2's surface took
the full ladder to land well; A alone is already M2-sized. Rejected on
size.

Why A: the seed rulings ARE most of its design work — the scoping
session inherits four ruled rounds and spends itself on the genuinely
open items instead; Timer heads the ladder per the time notes (process
sleep, and IPC's select-with-timeout shape needs it REGARDLESS, so it
is M4-enabling too); and CreateProcess is the load-bearing prerequisite
everything ruled this week quietly assumes.

## Standing pins carried into M3

1. **D2's tripwire FIRES in M3, and the answer is RULED (user, Aug
   16): M3 TAKES KERNEL INTERRUPTIBILITY EARLY.** "Syscall latency
   bounds interrupt latency — re-examine when any M3 syscall grows a
   loop" — CreateProcess's image copy IS a loop, and so is the arm()
   copy-in validation. Ruling: add interruptibility to (long) kernel
   operations NOW, while the kernel surface is at its smallest — this
   is a bug class to iron out early, not one to meet at SMP scale.
   SMP itself WAITS FOR CHANNELS (meaningful concurrent actions to
   exercise it with). The MECHANISM is the implementing brief's one
   big open: (a) explicit PREEMPTION POINTS — interrupts stay masked
   in kernel mode except at named points inside long loops where no
   IRQ-shared invariant is in flight; the interrupt is taken,
   serviced, and the op resumes. No IntrSpinLock needed, because a
   point IS the assertion that state is consistent — auditable in a
   kernel this size, and the placement rule ("no in-flight invariant
   over state the IRQ path touches") is a reviewable sentence per
   site. (b) full kernel preemption — interrupts unmasked throughout,
   IntrSpinLock around every IRQ-shared structure. LEAN: (a) for M3;
   (b) is what SMP forces anyway, and by then the point placements
   are a map of exactly where the locks must go — the points become
   documentation for the SMP conversion rather than waste.
2. **D1 carries**: processes stay integer-only (no FP in userspace).
3. **One core**; round-robin unchanged. The §7 band map stays a loader
   artifact (agenda item 10 confirms or moves it).
4. **Faults rule as sharpened in round 4**: programmer errors fault
   loudly; dynamic resource conditions return errors.
5. **SOS policy unchanged**: every unit per-arch-gated, branch parks
   for user review, sos_runner grows per unit.

## Proposed unit ladder (option A)

0. **M2 spec recap** — the deferred §11 refresh plus the M2 rows'
   status flips (§2 Interrupt row is BUILT, §2.5's placeholder note,
   §9a handover). Docs-only, dispatchable first and separately.
1. **Clock/Timer** per the time notes: `System.get_clock(type:)`,
   `clock.create_timer()`, `clock.now()` via copy-out, `timer.arm`
   via the NEW COPY-IN FUNNEL (the wait() copy-out's mirror twin —
   built here, consumed by IPC later), WaitPayload.Timer(fires:),
   waitable_slot arm. Files collide with the finale's wait machinery
   (waitable_slot, WaitPayload) — never parallel with another SOS
   unit touching them.
1.5. **Kernel interruptibility** (pin 1's ruling) — the mechanism
   (lean: preemption points), a synthetic long-op + selftest-line
   proof on both arches, and the placement audit of every existing
   loop (zero_bytes, the loader's segment walk, the PLIC/GIC reset
   loops). Lands BEFORE CreateProcess so the image-copy loop is born
   with its points rather than retrofitted.
2. **CreateProcess** — second address space, image load (points from
   unit 1.5 in its copy loop), teardown generalized (M2's close-all/
   free-owned per process), the idle/deadlock report generalized to N
   processes. Child image provenance per agenda item 2.
   **THE LIFECYCLE IS TWO-PHASE, INERT UNTIL STARTED (ruled Aug 16):**
   `create_process(image: Memory)` populates the address space, RECORDS
   the image's entry point and initial stack in the process slot (the
   sosimg declares both — how root itself boots), and returns a
   Process with NO thread. Root gives handles; then `process.start()`
   mints and runs the FIRST thread at the recorded entry on the
   recorded stack — root supplies neither, which is what keeps "root
   never parses" airtight. The give-before-start ORDERING is the
   soundness argument: boot_handles must answer completely at the
   child's first instruction, and the start call IS the barrier that
   makes a half-populated table unrepresentable, with no
   synchronization invented. Subsequent threads are the child's own
   CreateThread with stacks in its own memory, unchanged from M2.
   A SECOND start() is a FAULT (broken code, the sharpened line).
   start() with no System handle given is legal-but-doomed — a fully
   sandboxed compute process is a feature, not an error to detect.
   (Zircon's process_create/process_start is the precedent, including
   the bootstrap-handle-at-start convention.)
3. **The launch flow (shape ruled Aug 16; give-return AMENDED same
   day)** — `give(handle, tag:)` on the CHILD's Process handle, gated
   by the universal Transfer right: MOVES the handle into a fresh
   child-table slot and returns ONLY ITS STATUS — the child-side word
   is irrelevant to root (root can call no op through it), so nothing
   returns it. THE TAG IS THE IDENTITY, and tags are the ONLY
   cross-process vocabulary: the giver's own word handed back unread
   (the Waiter.add key precedent — the kernel is a courier, never an
   interpreter; root and child agree on meaning through config +
   manifest). A DUPLICATE tag is REFUSED at the give (fault — an
   identity naming two handles is broken config, caller-checkable,
   and it would make the record a multimap and the boot lookup below
   ambiguous). `start(boot_tag:)` completes the principle: the KERNEL
   resolves the tag to the child-table word and puts it in a0, so
   `_start(boot_handle)` is unchanged from M2 and root never sees a
   child-relative word at any point. start() with NO boot_tag puts
   the no-handle word in a0 — the sandboxed compute process stays a
   feature. **DELIVERY IS THE RETRIEVAL OP, NOT A BOOTINFO
   SECTION**: a bootinfo section written into the address space would
   freeze a struct layout in raw memory as permanent ABI — the exact
   disease the vDSO discipline exists to prevent (seL4's BootInfo
   frame is the cautionary precedent; Zircon went message-based for
   this reason) — where a copy-out record rides sysapi and evolves
   with the kernel. **THE OP IS AN ITERATOR (user, Aug 16, third
   refinement — supersedes the batch-buffer + one-shot-call
   shapes)**: `self_process()` then
   `proc.next_boot_handle() -> BootHandleRecord?` — each successful
   call hands out ONE `{tag, kind, handle}` record and CONSUMES it
   (the kernel frees that entry's bookkeeping immediately — it
   tracked tags for DELIVERY, not as a registry); EXHAUSTION IS
   `None` AND STAYS `None` — asking again is a loop's termination
   check, not broken code, so nothing here faults and nothing can be
   lost or truncated. This dissolved the whole buffer question (no
   capacity argument, no count protocol, no too-small policy) AND
   the new kernel machinery: one record per call is exactly the
   FIXED-SIZE record shape the wait() funnel already has — the
   variable-length array copy-out is never built. Per-record
   consumption is the no-stale-re-answer property at its natural
   grain: a word handed out once is never re-answered after the
   child drops or (M4) gives it onward. Records come back in give
   order (deterministic for free; tags stay the identity, nothing
   semantic rides on order), and the child asserts its drained count
   against its manifest with no protocol owed. The child's boot
   sequence is thereby literally a receive loop — the exact shape
   M4's channel receive will have (Zircon's processargs message,
   drained one record at a time). Unchanged: `give` AFTER start() is
   REFUSED in v1 (the boot set freezes at start; dynamic transfer is
   M4 IPC's job, over channels, to a process expecting it); the op
   lives on Process, not System (the handles are process state).
4. **Memory/IoMemory/MemoryMapping + map** — the ruled surface;
   SystemRights + stripping; manifest `devices = [names]` over root's
   board table; the M2 loader grant retired (its NAPOT/nGnRE
   discipline moves into map()'s implementation).
5. **Quotas** — the table, the counted kinds, `QuotaExceeded`,
   creator-pays, orphan write-off.
6. **The money shot** — the child echo driver from config, both
   arches; plus the shared-memory give demonstration.
7. **Spec updates** — §2.3 Memory rename, §5.7 amendment (rights-gated
   ops, boot set stays one handle wide), the DMA-TCB note (round 4),
   §11 refresh for M3.

Death notifications: PROPOSED unit 5.5 IF cheap after CreateProcess's
lifecycle work (a Process handle becomes waitable — the waitable_slot
pattern's third consumer), ELSE first unit of M4. Agenda item 9.

## The decisions agenda (the scoping session, in order)

1. **The slicing: RATIFIED (user, Aug 16)** — option A, the unit
   ladder as ordered (with 1.5 and 5.5 in place).
2. **Child image provenance: RULED (user, Aug 16) — the HYBRID.**
   The STITCHER appends child images to the boot blob and records a
   region table (offsets + lengths, nothing more); the KERNEL at boot
   mints one Memory per region, delivered through boot_handles tagged
   by region ordinal — it never interprets the bytes there; ROOT
   correlates ordinals to its config (which image, which child, which
   link range, devices, quotas) and calls `create_process(image:
   Memory)`; the KERNEL is the ONLY sosimg parser, at create_process,
   reusing the loader that loads root today — it re-validates
   unconditionally (root MAY parse via the imgformat library for
   diagnostics; nothing depends on it). One door from M3 static
   children through M4 dynamic loading. Two small flags for the
   CreateProcess brief: (i) a malformed image from root — fault or
   status? LEAN: STATUS (`BadImage`) — image bytes are DATA on the
   `from(raw:)` precedent (an unknown wire byte is data, never a
   trap), and M4's dynamically-fetched images make that unambiguous;
   (ii) image-region reclamation — after loading, the blob region is
   dead bytes; LEAN: v1 accepts the waste (static systems, small
   images), noted rather than engineered around.
   THE BUILD-TIME CONSTRAINT the unit designs around: under the PMP
   no-translation contract all processes share one physical address
   space, so every child image is LINKED at a distinct base assigned
   in config — blade/the stitcher emit per-child link addresses, and
   create_process validates segments against the assigned range.
3. **ClockType set for v1** (lean: Monotonic only; Boot/Realtime
   reserved in the enum, per the raw-backing wire idiom).
4. **The arm() copy-in record layout** + its validation rules (the
   funnel's first consumer sets the pattern IPC inherits).
5. **boot_handles record layout + tags** (178 flag c).
6. **Child AllocMemory right** (178 flag a; lean: stripped, root-only).
7. **Double-map one Memory in one process** (178 flag b; lean: allow).
8. **Quota defaults per kind** — the documented small defaults, and
   the mapping-quota ceiling's relation to the per-arch PMP budget
   (the quota is the POLICY cap; the PMP slot count is the PHYSICAL
   one; map() meeting the physical wall with quota headroom is a
   kernel bug to assert against, not a user-visible state).
9. **Death notifications: IN M3 (ruled Aug 16), unit 5.5.** The
    user's read is right with one sharpening: it is not a new object
    KIND — the existing Process object becomes the THIRD WAITABLE
    (waitable_slot's pattern, Waiter.add(process:key:), a
    WaitTag/WaitPayload.ProcessDeath variant carrying the exit
    status/fault reason). The parent already holds the child's
    Process handle from CreateProcess, which is what it attaches.
    Two small semantics to pin in the brief: death is a TERMINAL
    LEVEL (stays signaled — a waiter attaching after the death still
    wakes, matching the level-triggered Waiter contract), and the
    payload distinguishes clean exit from fault.
10. **Scheduler: RULED (Aug 16)** — round-robin stays for M3; SMP
    will require something more, designed when SMP arrives (after
    channels, per pin 1).
11. **D2 tripwire: RULED** — see pin 1 (kernel interruptibility in
    M3, unit 1.5; SMP waits for channels).
12. **Op/right numbering + §5.7 amendment wording** (178 flags d/e —
    mechanical, may be delegated to the implementing brief).

## Explicitly out (M4+ candidates)

Channels + ReplyHandle IPC (with select-with-timeout via unit 1's
Timer); the IOMMU driver + critical processes (round 4's architecture;
death notifications now land IN M3, so only the driver work remains);
priorities/§7 bands; SMP + IntrSpinLock — EXPLICITLY SEQUENCED AFTER
CHANNELS (ruled Aug 16: SMP wants meaningful concurrent actions to
exercise, and unit 1.5's preemption-point map is its conversion
guide); FP in userspace; vDSO true-mapping; program loading beyond
root's children; big-endian anything.

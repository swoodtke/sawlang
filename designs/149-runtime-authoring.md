# Design 149 — DRAFT: runtime authoring in Saw (DF-140g)

STATUS: DRAFT — deliberately scheduled for the FIRST post-M1b design
conversation (user: the arm64 HAL evidence shapes this). Two of the
three capabilities carry decisions already made in the Aug-5 review;
the brief finalizes after M1b. Closes DF-140g (filed on the parked SOS
M1 branch; refile on main at landing).

## The gap
A freestanding package cannot BE its own runtime: no mutable module
state, no zero-cost bulk storage, and the `__saw_rt_*` seams are
exportable only under `--runtime-build`. Hence sos' support.c carries
ordinary systems code (arena, bookkeeping) that should be reviewed Saw.

## (a) `unsafe static var` — mutable statics for AGGREGATES
[shape settled with the user, Aug 5] NOT an Atomic replacement. The
rule: single-word independently-updated state uses `Atomic` (still the
recommendation everywhere); `unsafe static var` exists for COMPOUND
state whose consistency comes from a serialization argument the
`unsafe` declaration forces its functions to own (interrupts-off,
single-core, boot-only — stated in the reviewed contract). The
motivating shapes Atomics cannot express: the kernel handle table
(`[HandleSlot; 64]` — multi-word slots, cross-word invariants), the
scheduler's bitmap+queues pair (compound invariant spans words), PMP
shadow state, and the arena BACKING STORAGE (a region, not a value).
Note the rv32i irony: `Atomic` lowers to the very `__atomic_*` C
libcalls this design deletes, buying atomicity a serialized kernel does
not want. Naming an unsafe static triggers the 130 trigger rule —
every touching function is declared `unsafe` and reviewed. v1
restriction: trivially-destructible types only (statics stay immortal
and deinit-free).

## (b) `.bss` placement for zero statics — DECIDED (user, Aug 5)
A static declared with an all-zero initializer — canonically 148's
`[0; N]` repeat literal — lowers to zerofill (.bss-class) storage, no
bytes in the image. Rides LLVM's zeroinitializer-global handling once
writable statics exist ((a)); the 64 KiB arena becomes
`unsafe static var ARENA: [UInt8; 65536] = [0; 65536]` with a
zero-byte image cost. Size-accounting test: the M1 kernel's
text/data/bss split.

## (c) Runtime-provider status — sketch, undecided
Manifest-level declaration (`[package] runtime = true`; Blade passes
it) replacing the `--runtime-build`-only export gate for freestanding
packages: permits `@export("__saw_rt_*")`, suppresses hosted-rt
auto-linking, and — the value-add — CHECKS the exported seam signatures
against rt/ABI.md's contract at compile time. Sync-only discipline
applies to the exports as it does under --runtime-build.

## Payoff
support.c shrinks to the two stays-C-forever categories (mem* — the
loop-idiom-recursion trap; atomics until the A-extension story) and
CSR/trap asm; the hosted rt loses the compiler-synthesized
`__saw_reactor` getter special case (becomes a plain unsafe static);
the kernels-first claim drops its asterisk.

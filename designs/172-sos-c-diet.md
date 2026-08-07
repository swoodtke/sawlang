# Design 172 — the SOS C diet: rewrite into Saw what is expressible today

**Status: APPROVED (user, Aug 7: "let's rewrite into saw what is expressible
today. if there are legit unexpressible items (that don't require asm) we
should note it for future work") — the foundation pass BEFORE M2's interrupt/
scheduling work. SOS policy: the branch PARKS for user review. Queue:
dispatches after M1b's integration battery is green; sos/ surface, disjoint
from 169/170.**

## Why

M1b landed 803 lines of C across the two HALs + common runtime. Post-audit,
the C sorts into three buckets; only the first is legitimate. The end state
this brief buys: **every remaining C line carries a one-line stated reason it
is C** — an auditable unsafe floor before the OS work gets hairy (M2).

1. **Legitimately C (stays, each with its reason comment):** inline-asm-bound
   bodies — semihosting exit (`hlt` + pinned registers), `wfi` loops, riscv32
   CSR writes (assembly-time immediates), the arm64 MSR/TLBI/barrier MMU
   activation sequence, both user-side syscall stubs (`ecall`/`svc`) — plus
   `memcpy`/`memset` (LLVM loop-idiom recognition rewrites a Saw byte loop
   INTO memcpy — self-recursion, permanent, already in the tracker).
2. **Saw-able today (this brief moves it):** see units.
3. **Expressible-looking but gapped:** anything that turns out to need a
   language feature (not asm) gets a DF-172x finding and STAYS C for now —
   noted for future work, per the user's rule. The known candidate is the
   linker-symbol accessors (below).

## Units

1. **arm64 page-table construction → Saw.** The static identity map's
   descriptor building is u64 stores through the design-112 `UnsafeMemory`
   machinery; only the activation sequence (MSR/TLBI/barriers) stays as a
   C/asm leaf taking the finished table's address. The table builder joins
   `sos/hal/arm64/kernel/lib.saw`. The grant-window alignment check comes
   with it (it is logic, not hardware).
2. **The arena allocator → Saw.** `support.c`'s early arena is compound
   global state — design 149's `unsafe static var` + SpinLock machinery was
   built for exactly this. One arch-free implementation in Saw serving both
   kernel and processes (the DF-140g direction, first concrete step).
3. **Kernel-bug printing → Saw.** `put_str`/hex dumping in the sinks
   duplicates `sos/rt/common/` helpers that already exist in Saw — the ktrap
   report path composes them instead.
4. **UART write loops → Saw, with the panic-recursion pin.** Both consoles
   already have Saw drivers (design 112) for the normal path; the C copies
   exist only for the panic seam. The Saw replacement MUST be check-free by
   construction — raw pointer stores, wrapping arithmetic (`&+`), no
   allocation, no indexing — so a panic inside the reporter cannot re-enter
   it. Verification is a test: a deliberately-panicking kernel entry whose
   panic output must arrive intact on both arches (panic-in-panic cannot
   hang or garble). If check-freedom cannot be GUARANTEED by inspection of
   the emitted IR (`--emit-ir` on the writer), this unit STOPS and files the
   finding — the panic path does not get best-effort.
5. **Linker-symbol accessors — probe, then move or file.** The C functions
   returning `__kernel_end`-class addresses exist because Saw has no way to
   name an externally-defined symbol's ADDRESS. Probe whether `extern` +
   the DF-163f-blessed `(&sym) as UnsafePointer<T>` shape can express it
   today; if not, file **DF-172a: extern static declarations** (the address
   of a linker symbol as a first-class value) as the future-work note and
   keep these C bodies — they are the "legit unexpressible without a
   language feature" case the user named.
6. **The reason-comment sweep + docs.** Every surviving C line's file gets
   its bucket-1 reason stated at the top; `sos/rt/common_c/support.c`'s
   header comment and the two HAL ABI.md files updated; sos/spec.md notes
   the C floor; tracker records the before/after line counts.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff, astdiff,
Saw-irdet --all, bootstrap, gmgate, sos_runner BOTH ARCHES — either arch
failing is red). The panic-in-panic test from unit 4 joins the sos test set
permanently. DF-172x findings for gaps, fixed or filed, never worked around.
Branch PARKS for user review (SOS policy).

## Explicitly out

Inline asm or per-instruction intrinsics in Saw (a separate design
conversation if ever); touching `memcpy`/`memset`; the syscall stubs and
exit/CSR/MSR leaves; test payloads (`sos/tests/*/payload_*.S`,
`fault_target.c` — fixtures simulating foreign binaries, non-Saw on
purpose); any M2 feature.

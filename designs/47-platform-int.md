# Design 47 — Platform-width Int/UInt (D13, DECIDED Jul 29)

**Ruling (user):** `Int`/`UInt` are pointer-width — 32-bit on riscv32
(ESP32-P4), 64-bit on x86-64/aarch64 — as the spec always promised
(Swift's model). Fixed-width Int8..64/UInt8..64 remain for stable
layouts. D1's checked arithmetic makes narrower-width overflow loud.
Rejected: always-64 (RV32 instruction pairs everywhere + __divdi3
compiler-rt libcalls that freestanding forbids).

## Items
1. Thread the target word size through codegen: one
   `self.int_type` (from the target machine's pointer size /
   --target triple) replacing hardcoded `ir.IntType(64)` for
   Int/UInt lowering — literals, arithmetic + overflow intrinsics
   (width-parametric already), sizeof/alignof results, array/loop
   indices, refcounts... audit every IntType(64) site and classify:
   platform-Int vs genuinely-64 (e.g. Int64 fields, String refcount
   layout — DECIDE per site, document the split).
2. Hosted targets stay 64-bit: the entire suite is the
   no-behavior-change oracle.
3. riscv32 verification (compile-only, brief-20 style): --target
   riscv32-unknown-none-elf --freestanding on core+alloc programs;
   objdump: 32-bit ops, no __divdi3/compiler-rt symbols, statics
   sized per 32-bit layout. Int literals exceeding 32 bits under a
   32-bit target: compile error at the literal (test).
4. Spec/CLAUDE.md: the width rule, Int.max/min per target note,
   guidance to use fixed-width types in wire formats.

## Hazards
The classification audit (item 1) is the correctness core — a missed
site is a silent width mismatch. String/Arc runtime layouts must be
explicitly pinned (refcount width documented per decision). Full suite
per commit.

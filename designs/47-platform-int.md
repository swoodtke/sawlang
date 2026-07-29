# Design 47 — Platform-width Int/UInt (D13, DECIDED Jul 29 — LANDED)

**Landed:** all four items. One `self.int_type`/`self.int_width` derived from the
target datalayout's address-space-0 pointer size drives every platform-`Int`
lowering; hosted (64-bit) codegen is byte-identical (488/488 suite green, zero
xfails). **Audit split:** platform-Int = literals (+ oversized-literal error at
the literal), arithmetic/overflow intrinsics (already operand-width), sizeof/
alignof/`len()` results, Range items + loop indices, `UnsafeMemory` addresses,
the runtime seams (`saw_alloc`/`dealloc`/`write`/`panic` sizes/lengths), the
String header `{ isize refcount, isize len, bytes }` (offsets word-parametric)
and its helpers, and the Arc/Channel atomic refcount — every one of these the
stdlib already types `Int`, so no stdlib change was needed. Genuinely-64 =
**only** the fixed-width `Int64`/`UInt64` types. String/Arc refcount width is
**pinned to the platform word** (documented decision): a handle/refcount never
approaches 2^31, and a word-width atomic is the native AMO on a 32-bit target —
no forced 64-bit atomic libcall. The coroutine frame state/`__wake` words are
`SawType(TypeKind.INT)` at the AST level, so they follow the platform word
automatically. **riscv32 verification:** `--target riscv32-unknown-none-elf
--freestanding` produces an ELF32 RISC-V object; Int div/mod lower to 32-bit
`__divsi3`/`__modsi3`/`__udivsi3`/`__umodsi3` (never 64-bit `__divdi3`), and on
the ESP32-P4 ISA (`+m,+a,+c`) to native `div`/`rem`/`mul` with zero arithmetic
libcalls; `Int` statics are `i32` (4 bytes) while `Int32` statics and the
String literal header `{ i32, i32, bytes }` confirm the 32-bit layout; a literal
beyond the 32-bit word errors at the literal.


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

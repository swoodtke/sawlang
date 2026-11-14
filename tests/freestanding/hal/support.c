// Freestanding-suite C floor (design 238 unit 1) — the C that must stay C.
//
// Forked from `sos/rt/common_c/support.c` and deliberately smaller. It is a
// fork for the reason the boot stubs are: the two trees separate at design
// 238 unit 5, and a shared file across two repos with no package relation
// between them would be a distribution problem invented to avoid forty lines.
//
// EVERY LINE HERE IS C FOR ONE OF THREE REASONS. The first two are permanent;
// the third (the `saw_table` bounds at the end of the file) waits on Saw naming
// a linker-defined symbol's address (SL-136):
//
//  1. mem* : a byte-copy loop written in Saw is exactly the pattern LLVM's
//     loop-idiom recognizer rewrites into a call to `memcpy` — which, in a
//     freestanding build where this IS memcpy, is a call to itself. Keeping
//     these in C lets them be compiled with `-fno-builtin`, which is the
//     supported way to say "do not do that".
//
//  2. the 64-bit division libcalls : a compiler-generated LIBCALL, so it must
//     exist under the name and signature the BACKEND emits. rv32 has no 64-bit
//     divide instruction even with `+m`, so a `UInt64 / UInt64` in Saw lowers
//     to a call no source names; arm64 divides 64 bits natively and
//     `--gc-sections` drops both there. That asymmetry is one of the
//     cross-target hazards this suite exists to gate, so
//     `cases/int_widths.saw` divides on purpose.
//
// WHAT IS DELIBERATELY ABSENT, where sos's copy carries it: the `__atomic_*`
// family. The suite's default builds name an atomics-capable ISA (riscv32
// through `--target-features +m,+a,+c`, arm64 natively), so the backend emits
// instructions rather than libcalls, and an unreferenced fallback linked into
// every image is a thing that can rot without anything noticing. The cases
// built without `+a` link `riscv32/atomics.c` instead, and the runner checks
// their objects reference exactly its routines.

typedef unsigned char      u8;
typedef unsigned long      usize;   // ilp32: 32-bit; lp64: 64-bit. size_t on both.
typedef unsigned long long u64;

// ---- mem* (the compiler's implicit block-copy / zero helpers) --------------

void *memset(void *dst, int c, usize n) {
    u8 *d = (u8 *)dst;
    for (usize i = 0; i < n; i++) d[i] = (u8)c;
    return dst;
}

void *memcpy(void *dst, const void *src, usize n) {
    u8 *d = (u8 *)dst; const u8 *s = (const u8 *)src;
    for (usize i = 0; i < n; i++) d[i] = s[i];
    return dst;
}

void *memmove(void *dst, const void *src, usize n) {
    u8 *d = (u8 *)dst; const u8 *s = (const u8 *)src;
    if (d < s) {
        for (usize i = 0; i < n; i++) d[i] = s[i];
    } else {
        for (usize i = n; i > 0; i--) d[i - 1] = s[i - 1];
    }
    return dst;
}

// ---- 64-bit division libcalls ---------------------------------------------
//
// Shift-subtract, most significant bit first: the schoolbook algorithm, and
// deliberately the simple one. A fixed 64 iterations, no table, no wide
// intermediate — and, the part that matters, no `/` or `%` on a 64-bit value,
// which would be a call back into this function.

static u64 udivmod64(u64 n, u64 d, u64 *rem) {
    // Division by zero is undefined, and the freestanding convention is
    // all-ones rather than a trap: Saw's own divide-by-zero check is what a
    // caller meets first, so this is the unreachable floor.
    if (d == 0) {
        if (rem) *rem = 0;
        return ~(u64)0;
    }
    u64 q = 0, r = 0;
    for (int i = 63; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1ULL);
        if (r >= d) {
            r -= d;
            q |= (1ULL << i);
        }
    }
    if (rem) *rem = r;
    return q;
}

u64 __udivdi3(u64 n, u64 d) { return udivmod64(n, d, 0); }

u64 __umoddi3(u64 n, u64 d) { u64 r; udivmod64(n, d, &r); return r; }

// ---- the `saw_table` section's bounds ---------------------------------------
//
// Saw cannot name a linker-defined data symbol, so the two addresses
// `cases/section_walk.saw` walks between come from here. The linker defines
// `__start_saw_table` and `__stop_saw_table` for a section named like a C
// identifier, and only when the section exists; weak, so every other case's
// link (which has no such section) still resolves. Both read as null then.
extern char __start_saw_table[] __attribute__((weak));
extern char __stop_saw_table[] __attribute__((weak));

char *fs_section_table_start(void) { return __start_saw_table; }

char *fs_section_table_stop(void) { return __stop_saw_table; }

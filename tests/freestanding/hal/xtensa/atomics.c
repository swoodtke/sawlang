// The atomic routines an ESP32-S3 build WITHOUT `s32c1i` references, and
// nothing else: exactly the five the spec lists (Profiles), at the 4-byte
// word, linked only into the cases the runner builds without that feature.
//
// A single core runs every case, so an operation is atomic when nothing can
// interrupt it: each body raises PS.INTLEVEL to its maximum around its plain
// loads and stores and puts the old PS back, which is what a kernel's HAL does
// on such a part. The memory-order argument is ignored, since one core with
// interrupts masked is sequentially consistent.
//
// The runner compiles this file without `s32c1i`, so clang cannot answer one
// of these with the compare-and-swap instruction: the image would then not be
// the part the case claims to run on.

typedef unsigned int u32;

static inline u32 interrupts_off(void) {
    u32 previous;
    __asm__ volatile("rsil %0, 15" : "=a"(previous) : : "memory");
    return previous;
}

static inline void interrupts_restore(u32 previous) {
    __asm__ volatile("wsr %0, ps\n\trsync" : : "a"(previous) : "memory");
}

u32 __atomic_load_4(const volatile void *ptr, int order) {
    (void)order;
    u32 saved = interrupts_off();
    u32 value = *(const volatile u32 *)ptr;
    interrupts_restore(saved);
    return value;
}

void __atomic_store_4(volatile void *ptr, u32 value, int order) {
    (void)order;
    u32 saved = interrupts_off();
    *(volatile u32 *)ptr = value;
    interrupts_restore(saved);
}

u32 __atomic_fetch_add_4(volatile void *ptr, u32 value, int order) {
    (void)order;
    u32 saved = interrupts_off();
    u32 before = *(volatile u32 *)ptr;
    *(volatile u32 *)ptr = before + value;
    interrupts_restore(saved);
    return before;
}

u32 __atomic_fetch_sub_4(volatile void *ptr, u32 value, int order) {
    (void)order;
    u32 saved = interrupts_off();
    u32 before = *(volatile u32 *)ptr;
    *(volatile u32 *)ptr = before - value;
    interrupts_restore(saved);
    return before;
}

// On a mismatch the current value is written back through `expected`, as the
// libcall contract requires.
_Bool __atomic_compare_exchange_4(volatile void *ptr, void *expected, u32 desired, int success, int failure) {
    (void)success;
    (void)failure;
    u32 saved = interrupts_off();
    u32 current = *(volatile u32 *)ptr;
    _Bool matched = current == *(u32 *)expected;
    if (matched) {
        *(volatile u32 *)ptr = desired;
    } else {
        *(u32 *)expected = current;
    }
    interrupts_restore(saved);
    return matched;
}

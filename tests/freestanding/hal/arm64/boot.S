/* Freestanding-suite boot stub (design 238 unit 1) — arm64, QEMU `virt`, EL1.
 *
 * A TEST STUB IS NOT A KERNEL. Forked from `sos/hal/arm64/kernel/boot.S` and
 * deliberately divergent: no exception vectors, no trap frame, no EL1->EL0
 * transition, no grant editing. Every case runs at EL1 from `_start` to the exit
 * device. The two files are NOT kept in step.
 *
 * The same three symbols the riscv32 stub exports, for the same reasons:
 *
 *   _start                          the reset target link.ld places first
 *   fs_console_write(ptr, len)      bytes out of the board's UART
 *   fs_platform_exit(code)          stop the machine carrying `code`
 *
 * WHAT IS NOT STRIPPED, AND WHY: the identity map. With `SCTLR_EL1.M` clear
 * every access at EL1 is Device-nGnRnE, which faults on an UNALIGNED access —
 * and LLVM is free to emit one for a struct copy or a packed field read, which
 * this suite's layout cases do on purpose. So the stub turns the MMU on for its
 * memory ATTRIBUTES, not for protection: two level-1 block descriptors, device
 * below 1 GiB and Normal write-back above it, EL1 read/write/execute, EL0 never
 * entered. That is twenty instructions rather than the kernel's page-table
 * builder, and it is the difference between a suite and a flake generator.
 */

    .equ UART_BASE,     0x09000000  /* PL011 */
    .equ UART_FR,       0x18        /* flag register */
    .equ UART_FR_TXFF,  0x20        /* bit 5: transmit FIFO full */

    .equ SYS_EXIT,      0x18
    .equ ADP_STOPPED_APPLICATION_EXIT, 0x20026
    .equ EXIT_FELL_OFF, 70          /* fs_main returned without reporting */

    .equ CPACR_FPEN,    (3 << 20)

    /* Level-1 block descriptors, 1 GiB each. Bit 0 = valid, bit 1 = 0 = block,
     * bit 10 = AF, bits 8:9 = SH, bits 2:4 = MAIR index, AP = 0b00 (EL1 RW,
     * EL0 none). MAIR: Attr0 = Device-nGnRnE, Attr1 = Normal write-back. */
    .equ BLOCK_DEVICE,  0x00000401  /* 0x0000_0000, AF, Attr0            */
    .equ BLOCK_NORMAL,  0x40000705  /* 0x4000_0000, AF, inner-sh, Attr1  */
    .equ MAIR_VALUE,    0xFF00      /* Attr1 = 0xFF, Attr0 = 0x00        */
    /* T0SZ=25 (39-bit VA, level 1 first), IRGN0/ORGN0 write-back, SH0 inner,
     * TG0 4 KiB, EPD1 (no TTBR1 walks), TG1 4 KiB, IPS 32-bit. */
    .equ TCR_VALUE,     0x80993519

    .section .text.boot, "ax", @progbits
    .globl _start
_start:
    /* Stack: the 64 KiB reservation below (in .bss), top-aligned. */
    ldr     x0, =_stack_top
    mov     sp, x0

    /* FP/SIMD access. `--freestanding` implies `-neon,-fp-armv8` for the Saw
     * half (design 172), so nothing here should need it — but a case may ask
     * for the features back with `--target-features`, and a trap taken with no
     * vectors installed is a silent hang rather than a diagnostic. */
    mov     x0, #CPACR_FPEN
    msr     cpacr_el1, x0
    isb

    /* Zero .bss [_bss_start, _bss_end) a doubleword at a time. The page table
     * below lives there, so this must come first. */
    ldr     x0, =_bss_start
    ldr     x1, =_bss_end
.Lbss:
    cmp     x0, x1
    b.hs    .Lbss_done
    str     xzr, [x0], #8
    b       .Lbss
.Lbss_done:

    /* The identity map — see the header note. */
    ldr     x0, =_page_table
    mov     x1, #BLOCK_DEVICE
    str     x1, [x0]
    ldr     x1, =BLOCK_NORMAL
    str     x1, [x0, #8]

    mov     x1, #MAIR_VALUE
    msr     mair_el1, x1
    ldr     x1, =TCR_VALUE
    msr     tcr_el1, x1
    msr     ttbr0_el1, x0
    dsb     ish
    isb

    /* Read-modify-write: the reset value carries the stack-alignment and
     * endianness bits this stub has no opinion about. */
    mrs     x1, sctlr_el1
    orr     x1, x1, #(1 << 0)       /* M: enable the MMU        */
    orr     x1, x1, #(1 << 2)       /* C: data cache            */
    orr     x1, x1, #(1 << 12)      /* I: instruction cache     */
    msr     sctlr_el1, x1
    isb

    /* Enter the case. A case reports its own verdict and exits through
     * `fs_platform_exit`; RETURNING here is a case that never said anything,
     * which must not read as a pass. */
    bl      fs_main
    mov     x0, #EXIT_FELL_OFF
    bl      fs_platform_exit
.Lhang:
    wfi
    b       .Lhang

/* ---- the console ---------------------------------------------------------- */

/* void fs_console_write(const char *ptr, unsigned long len)
 *
 * Assembly rather than the design-112 Saw MMIO idiom for the reason stated in
 * the riscv32 stub: the Blade case reaches this file through
 * `[sos.<triple>] native`, and a Blade path dependency cannot vary by target.
 */
    .section .text.console, "ax", @progbits
    .globl fs_console_write
fs_console_write:
    ldr     x2, =UART_BASE
    cbz     x1, .Lwrite_done
.Lbyte:
.Lwait:
    ldr     w3, [x2, #UART_FR]
    tst     w3, #UART_FR_TXFF
    b.ne    .Lwait
    ldrb    w4, [x0], #1
    str     w4, [x2]
    subs    x1, x1, #1
    b.ne    .Lbyte
.Lwrite_done:
    ret

/* ---- the exit device ------------------------------------------------------ */

/* void fs_platform_exit(unsigned code) — never returns.
 *
 * ARM semihosting SYS_EXIT, for the reason `sos/hal/arm64/kernel/sink.c` gives:
 * PSCI SYSTEM_OFF always exits the emulator with status 0, and this suite
 * asserts on exit STATUS — a failing case that exits 0 reads as a passing run.
 * SYS_EXIT carries a status the emulator exits with, so it is the only
 * mechanism with the RISC-V finisher's shape. It needs `-semihosting` on the
 * QEMU command line, which `tools/freestanding_runner.py` passes.
 *
 * No zero-promotion is owed here: unlike the finisher, the status travels whole
 * and a non-zero code arrives non-zero.
 */
    .globl fs_platform_exit
fs_platform_exit:
    /* The A64 form takes a two-word parameter block; the second word is the
     * status. Build it on the stack. */
    sub     sp, sp, #16
    ldr     x2, =ADP_STOPPED_APPLICATION_EXIT
    str     x2, [sp]
    str     x0, [sp, #8]
    mov     x1, sp
    mov     x0, #SYS_EXIT
    hlt     #0xf000
.Lstopped:
    wfi
    b       .Lstopped

/* ---- reservations --------------------------------------------------------- */

/* 64 KiB stack + the one level-1 page table, reserved in .bss (zeroed by the
 * loop above — the table's 510 unused entries must read as invalid). */
    .section .bss.stack, "aw", @nobits
    .balign 4096
    .globl _page_table
_page_table:
    .skip 4096
_stack_bottom:
    .skip 0x10000
    .globl _stack_top
_stack_top:

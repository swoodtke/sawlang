/* Freestanding-suite boot stub (design 238 unit 1) — riscv32, QEMU `virt`, M-mode.
 *
 * A TEST STUB IS NOT A KERNEL. This is forked from `sos/hal/riscv32/kernel/boot.S`
 * and deliberately diverges: there is no trap vector, no mode witness, no trap
 * frame, no M->U transition and no PMP — every case in this suite runs in M-mode
 * from `_start` to the exit device and never traps on purpose. What is left is
 * the three things the brief names — stack, call, exit device — plus the console
 * write, because a case that cannot print cannot assert anything.
 *
 * The two files are NOT kept in step. sos's grows with the kernel; this one
 * grows only if a case needs something the machine can do and Saw cannot say.
 *
 * The three symbols below are the WHOLE native surface of the suite. Everything
 * above them is Saw:
 *
 *   _start                          the reset target virt.ld places first
 *   fs_console_write(ptr, len)      bytes out of the board's UART
 *   fs_platform_exit(code)          stop the machine carrying `code`
 *
 * `fsrt` (tests/freestanding/rt/src/lib.saw) is the Saw module that turns the
 * last two into the four frozen `__saw_rt_*` seams.
 */

    .equ SIFIVE_TEST,   0x00100000  /* the board's exit device */
    .equ FINISHER_PASS, 0x5555
    .equ FINISHER_FAIL, 0x3333
    .equ EXIT_FELL_OFF, 70          /* fs_main returned without reporting */

    .equ UART_BASE,     0x10000000  /* NS16550A */
    .equ UART_LSR,      5           /* line status register */
    .equ UART_LSR_THRE, 0x20        /* bit 5: transmit holding register empty */

    .section .text.boot, "ax", @progbits
    .globl _start
_start:
    /* Stack: the 64 KiB reservation below (in .bss), top-aligned. */
    la      sp, _stack_top

    /* Zero .bss [_bss_start, _bss_end) a word at a time. The Saw side's
     * statics and the arena live there. */
    la      t0, _bss_start
    la      t1, _bss_end
.Lbss:
    bgeu    t0, t1, .Lbss_done
    sw      zero, 0(t0)
    addi    t0, t0, 4
    j       .Lbss
.Lbss_done:

    /* Enter the case. A case reports its own verdict and exits through
     * `fs_platform_exit`; RETURNING here is a case that never said anything,
     * which must not read as a pass. */
    call    fs_main
    li      a0, EXIT_FELL_OFF
    call    fs_platform_exit
.Lhang:
    wfi
    j       .Lhang

/* ---- the console ---------------------------------------------------------- */

/* void fs_console_write(const char *ptr, unsigned long len)
 *
 * Poll the transmitter and place one byte at a time. Assembly rather than the
 * design-112 Saw MMIO idiom for ONE reason: the Blade case builds against the
 * same stub through `[sos.<triple>] native`, and a Blade path dependency cannot
 * vary by target — so a per-architecture SAW console module could not be reached
 * from that row, while a per-architecture native unit can. The MMIO idiom is
 * exercised by `cases/struct_layout.saw` instead, over a typed view of RAM.
 */
    .section .text.console, "ax", @progbits
    .globl fs_console_write
fs_console_write:
    li      t2, UART_BASE
    beqz    a1, .Lwrite_done
.Lbyte:
.Lwait:
    lbu     t3, UART_LSR(t2)
    andi    t3, t3, UART_LSR_THRE
    beqz    t3, .Lwait
    lbu     t4, 0(a0)
    sb      t4, 0(t2)
    addi    a0, a0, 1
    addi    a1, a1, -1
    bnez    a1, .Lbyte
.Lwrite_done:
    ret

/* ---- the exit device ------------------------------------------------------ */

/* void fs_platform_exit(unsigned code) — never returns.
 *
 * The SiFive test finisher takes the status in its upper half. A FAILING exit
 * must never read as a passing one, so a non-zero `code` whose low byte is zero
 * is promoted to 1 — the finisher exits with `code >> 16`, and a zero there is
 * indistinguishable from FINISHER_PASS. (`sosrt`'s `abort_status` states the
 * same rule on the Saw side; this stub states it here because it is the file
 * that owns the mechanism.)
 */
    .globl fs_platform_exit
fs_platform_exit:
    li      t2, SIFIVE_TEST
    beqz    a0, .Lpass
    andi    a0, a0, 0xFF
    bnez    a0, .Lfail
    li      a0, 1
.Lfail:
    slli    a0, a0, 16
    li      t1, FINISHER_FAIL
    or      a0, a0, t1
    sw      a0, 0(t2)
    j       .Lstopped
.Lpass:
    li      t1, FINISHER_PASS
    sw      t1, 0(t2)
.Lstopped:
    wfi
    j       .Lstopped

/* ---- reservations --------------------------------------------------------- */

/* 64 KiB stack, reserved in .bss (zeroed by the loop above). */
    .section .bss.stack, "aw", @nobits
    .balign 16
_stack_bottom:
    .skip 0x10000
    .globl _stack_top
_stack_top:

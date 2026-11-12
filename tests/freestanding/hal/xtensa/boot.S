/* Freestanding-suite boot stub: ESP32-S3 under Espressif's QEMU, call0, flash image.
 *
 * A TEST STUB IS NOT A KERNEL. It owns the reset path, a vector table that
 * only reports a fault, and the hooks every case needs. Everything above
 * them is Saw. The whole native surface:
 *
 *   _entry                          the first instruction the ROM runs
 *   fs_console_write(ptr, len)      bytes out of UART0
 *   fs_platform_exit(code)          stop the machine carrying `code`
 *   fs_clock_ticks()                SYSTIMER's counter, 64 bits
 *   fs_clock_frequency()            the rate it counts at, in ticks per second
 *
 * The image boots from flash, the way the part does. The ROM looks for two
 * magic words at flash offsets 0x400 and 0x404, and enters at 0x408 with
 * `callx8`, windowed, PS.WOE set and WINDOWBASE nonzero. All code here and in
 * the cases is call0, so the first act is to give up the window: writing
 * WINDOWBASE renames every address register, which is why nothing is kept in
 * one across it. Code executes in place from flash; the vector table, which
 * needs a 1 KiB-aligned address, runs from IRAM, and .data and .bss live in
 * DRAM (link.ld).
 */

    .equ UART0_FIFO,     0x60000000
    .equ SYSTIMER,       0x60023000
    .equ ST_UNIT0_OP,    0x04       /* bit 30 requests a snapshot, bit 29 says it is valid */
    .equ ST_UNIT0_HI,    0x40
    .equ ST_UNIT0_LO,    0x44
    .equ SYSTIMER_HZ,    16000000
    .equ SYS_EXIT,       1          /* simcall's exit service */
    .equ EXIT_FELL_OFF,  70         /* fs_main returned without reporting */
    .equ EXIT_FAULT,     71         /* an exception reached a vector */

    /* The emulator reads ATOMCTL's low two bits and makes `s32c1i` fault when
     * they are zero. Booted from flash it inherits the ROM's 0x15; booted with
     * -kernel it starts at 0x28, which faults. Setting it here keeps the
     * image from depending on which way it was booted. */
    .equ ATOMCTL_VALUE,  0x15

    .section .magic, "a"
    .word 0xAEDB041D
    .word 0xAEDB041D

    .section .entry, "ax"
    .global _entry
_entry:
    j       _start

    .section .text.start, "ax"
    .literal .Liram_load, _iram_load
    .literal .Liram_start, _iram_start
    .literal .Liram_end, _iram_end
    .literal .Ldata_load, _data_load
    .literal .Ldata_start, _data_start
    .literal .Ldata_end, _data_end
    .literal .Lbss_start, _bss_start
    .literal .Lbss_end, _bss_end
    .literal .Lvecbase, _vector_base
    .literal .Lstack, _stack_top
    .literal .Lmain, fs_main
    .align 4
    .global _start
_start:
    movi    a9, 1
    wsr     a9, windowstart
    movi    a9, 0
    wsr     a9, windowbase
    rsync
    movi    a9, 0x0F                /* INTLEVEL 15, EXCM 0, UM 0, WOE 0 */
    wsr     a9, ps
    rsync
    movi    a9, ATOMCTL_VALUE
    wsr     a9, atomctl

    l32r    a2, .Liram_load         /* the vector table, flash -> IRAM */
    l32r    a3, .Liram_start
    l32r    a4, .Liram_end
1:  bgeu    a3, a4, 2f
    l32i    a5, a2, 0
    s32i    a5, a3, 0
    addi    a2, a2, 4
    addi    a3, a3, 4
    j       1b
2:  l32r    a2, .Ldata_load         /* .data, flash -> DRAM */
    l32r    a3, .Ldata_start
    l32r    a4, .Ldata_end
3:  bgeu    a3, a4, 4f
    l32i    a5, a2, 0
    s32i    a5, a3, 0
    addi    a2, a2, 4
    addi    a3, a3, 4
    j       3b
4:  l32r    a3, .Lbss_start         /* .bss, zeroed a word at a time */
    l32r    a4, .Lbss_end
    movi    a5, 0
5:  bgeu    a3, a4, 6f
    s32i    a5, a3, 0
    addi    a3, a3, 4
    j       5b
6:  l32r    a9, .Lvecbase
    wsr     a9, vecbase
    isync
    l32r    a1, .Lstack

    /* Enter the case. A case reports its own verdict and exits through
     * `fs_platform_exit`; RETURNING here is a case that never said anything,
     * which must not read as a pass. */
    l32r    a8, .Lmain
    callx0  a8
    movi    a2, EXIT_FELL_OFF
    call0   fs_platform_exit

/* ---- vectors, IRAM; VECBASE must be the table's first byte ---------------- */

/* Nothing here is meant to run: every entry reports itself and ends the
 * machine. A case that faults prints one line naming the vector, the cause
 * and where, and exits non-zero. */
    .section .iram.vectors, "ax"
    .literal .Lkstack, _stack_top
    .literal .Lreport, fs_fault_report

    .align 1024
    .global _vector_base
_vector_base:
    .org 0x000
    movi    a2, 0x000               /* WindowOverflow4  */
    j       vec_fatal
    .org 0x040
    movi    a2, 0x040               /* WindowUnderflow4 */
    j       vec_fatal
    .org 0x080
    movi    a2, 0x080               /* WindowOverflow8  */
    j       vec_fatal
    .org 0x0C0
    movi    a2, 0x0C0               /* WindowUnderflow8 */
    j       vec_fatal
    .org 0x100
    movi    a2, 0x100               /* WindowOverflow12 */
    j       vec_fatal
    .org 0x140
    movi    a2, 0x140               /* WindowUnderflow12 */
    j       vec_fatal
    .org 0x180
    movi    a2, 0x180               /* Level2 */
    j       vec_fatal
    .org 0x1C0
    movi    a2, 0x1C0               /* Level3 */
    j       vec_fatal
    .org 0x200
    movi    a2, 0x200               /* Level4 */
    j       vec_fatal
    .org 0x240
    movi    a2, 0x240               /* Level5 */
    j       vec_fatal
    .org 0x280
    movi    a2, 0x280               /* Debug */
    j       vec_fatal
    .org 0x2C0
    movi    a2, 0x2C0               /* NMI */
    j       vec_fatal
    .org 0x300
    movi    a2, 0x300               /* Kernel: an exception with PS.UM=0 */
    j       vec_fatal
    .org 0x340
    movi    a2, 0x340               /* User: an exception with PS.UM=1 */
    j       vec_fatal
    .org 0x3C0
    movi    a2, 0x3C0               /* Double: an exception with PS.EXCM=1 */
    j       vec_fatal
    .org 0x400

vec_fatal:
    rsr     a3, exccause
    rsr     a4, epc1
    rsr     a5, excvaddr
    l32r    a1, .Lkstack
    l32r    a8, .Lreport
    callx0  a8
1:  j       1b

/* ---- the fault report ----------------------------------------------------- */

/* fs_fault_report(vector, exccause, epc1, excvaddr) — never returns. The
 * four values wait in callee-saved registers while the line is written. The
 * cause is named for the ones a bare program meets; the numbers are the
 * ISA's. */
    .section .text.fault, "ax"
    .literal .Lfault_intro, .Lintro
    .literal .Lfault_cause, .Lcause_label
    .literal .Lfault_epc, .Lepc_label
    .literal .Lfault_addr, .Laddr_label
    .literal .Lfault_end, .Lnewline
    .align 4
    .global fs_fault_report
fs_fault_report:
    mov     a12, a2
    mov     a13, a3
    mov     a14, a4
    mov     a15, a5
    l32r    a2, .Lfault_intro
    call0   put_text
    mov     a2, a12
    call0   put_hex
    l32r    a2, .Lfault_cause
    call0   put_text
    mov     a2, a13
    call0   put_hex
    movi    a2, 0x20
    call0   put_byte
    mov     a2, a13
    call0   cause_name
    call0   put_text
    l32r    a2, .Lfault_epc
    call0   put_text
    mov     a2, a14
    call0   put_hex
    l32r    a2, .Lfault_addr
    call0   put_text
    mov     a2, a15
    call0   put_hex
    l32r    a2, .Lfault_end
    call0   put_text
    movi    a2, EXIT_FAULT
    call0   fs_platform_exit

/* The text of an ISA exception cause, or an empty string. A `call0` target
 * must be 4-byte aligned, so each routine below starts on that boundary. */
    .section .text.fault_name, "ax"
    .literal .Lnames, .Lcause_table
    .literal .Lunnamed, .Lno_name
    .align 4
cause_name:
    l32r    a8, .Lnames
1:  l32i    a9, a8, 0
    bltz    a9, 2f
    beq     a9, a2, 3f
    addi    a8, a8, 8
    j       1b
2:  l32r    a2, .Lunnamed
    ret
3:  l32i    a2, a8, 4
    ret

/* put_byte(a2): one byte to the console. */
    .section .text.put, "ax"
    .literal .Luart_put, UART0_FIFO
    .align 4
put_byte:
    l32r    a8, .Luart_put
    s8i     a2, a8, 0
    ret

/* put_text(a2): a NUL-terminated string. */
    .align 4
put_text:
    l32r    a8, .Luart_put
1:  l8ui    a9, a2, 0
    beqz    a9, 2f
    s8i     a9, a8, 0
    addi    a2, a2, 1
    j       1b
2:  ret

/* put_hex(a2): `0x` and eight hex digits. */
    .align 4
put_hex:
    l32r    a8, .Luart_put
    movi    a9, 0x30
    s8i     a9, a8, 0
    movi    a9, 0x78
    s8i     a9, a8, 0
    movi    a10, 28
1:  ssr     a10
    srl     a9, a2
    movi    a11, 15
    and     a9, a9, a11
    movi    a11, 10
    bltu    a9, a11, 2f
    addi    a9, a9, 39              /* 'a' - 10 - '0' */
2:  addi    a9, a9, 0x30
    s8i     a9, a8, 0
    addi    a10, a10, -4
    bgez    a10, 1b
    ret

    .section .rodata.fault, "a"
.Lintro:       .asciz "fs: fault vector="
.Lcause_label: .asciz " exccause="
.Lepc_label:   .asciz " epc1="
.Laddr_label:  .asciz " excvaddr="
.Lnewline:     .asciz "\n"
.Lno_name:     .asciz ""
.Lname_0:      .asciz "IllegalInstruction"
.Lname_1:      .asciz "Syscall"
.Lname_2:      .asciz "InstrFetchError"
.Lname_3:      .asciz "LoadStoreError"
.Lname_4:      .asciz "Level1Interrupt"
.Lname_5:      .asciz "Alloca"
.Lname_6:      .asciz "IntegerDivideByZero"
.Lname_9:      .asciz "Unaligned"
.Lname_12:     .asciz "InstrDataError"
.Lname_13:     .asciz "LoadStoreDataError"
.Lname_14:     .asciz "InstrAddrError"
.Lname_15:     .asciz "LoadStoreAddrError"
.Lname_20:     .asciz "InstrProhibited"
.Lname_28:     .asciz "LoadProhibited"
.Lname_29:     .asciz "StoreProhibited"
.Lname_32:     .asciz "Coprocessor0Disabled"
    .align 4
.Lcause_table:
    .word 0, .Lname_0
    .word 1, .Lname_1
    .word 2, .Lname_2
    .word 3, .Lname_3
    .word 4, .Lname_4
    .word 5, .Lname_5
    .word 6, .Lname_6
    .word 9, .Lname_9
    .word 12, .Lname_12
    .word 13, .Lname_13
    .word 14, .Lname_14
    .word 15, .Lname_15
    .word 20, .Lname_20
    .word 28, .Lname_28
    .word 29, .Lname_29
    .word 32, .Lname_32
    .word -1, 0

/* ---- the console ---------------------------------------------------------- */

/* void fs_console_write(const char *ptr, unsigned len)
 *
 * One byte store per character: the UART's FIFO never reports full under the
 * emulator, so there is nothing to poll. */
    .section .text.console, "ax"
    .literal .Luart_write, UART0_FIFO
    .align 4
    .global fs_console_write
fs_console_write:
    beqz    a3, 2f
    l32r    a8, .Luart_write
1:  l8ui    a9, a2, 0
    s8i     a9, a8, 0
    addi    a2, a2, 1
    addi    a3, a3, -1
    bnez    a3, 1b
2:  ret

/* ---- the exit ------------------------------------------------------------- */

/* void fs_platform_exit(unsigned code) — never returns.
 *
 * `simcall` with a2 = SYS_EXIT and a3 = the status ends QEMU when it runs with
 * -semihosting. A FAILING exit must never read as a passing one, so a nonzero
 * `code` whose low byte is zero is promoted to 1: the host sees the low
 * byte of the status. */
    .section .text.exit, "ax"
    .align 4
    .global fs_platform_exit
fs_platform_exit:
    mov     a3, a2
    beqz    a3, 1f
    movi    a8, 0xFF
    and     a3, a3, a8
    bnez    a3, 1f
    movi    a3, 1
1:  movi    a2, SYS_EXIT
    simcall
2:  waiti   15
    j       2b

/* ---- the clock ------------------------------------------------------------ */

/* unsigned long long fs_clock_ticks(void)
 *
 * SYSTIMER's unit 0, a 64-bit counter at 16 MHz. Its value registers hold a
 * snapshot: request one with bit 30 of UNIT0_OP, wait for bit 29, read both
 * halves, which cannot tear because the snapshot is one moment. */
    .section .text.clock, "ax"
    .literal .Lsystimer, SYSTIMER
    .literal .Lsystimer_hz, SYSTIMER_HZ
    .align 4
    .global fs_clock_ticks
fs_clock_ticks:
    l32r    a8, .Lsystimer
    movi    a9, 1
    slli    a9, a9, 30
    s32i    a9, a8, ST_UNIT0_OP
    movi    a10, 1
    slli    a10, a10, 29
1:  l32i    a9, a8, ST_UNIT0_OP
    and     a9, a9, a10
    beqz    a9, 1b
    l32i    a2, a8, ST_UNIT0_LO
    l32i    a3, a8, ST_UNIT0_HI
    ret

/* unsigned long long fs_clock_frequency(void) */
    .align 4
    .global fs_clock_frequency
fs_clock_frequency:
    l32r    a2, .Lsystimer_hz
    movi    a3, 0
    ret

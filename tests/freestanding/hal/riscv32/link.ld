/* Freestanding-suite linker script (design 238 unit 1) — QEMU `virt`, riscv32.
 *
 * Forked from `sos/hal/riscv32/kernel/virt.ld` and deliberately smaller: no
 * `.payload` section (nothing is appended to a case image), no root region, no
 * PMP map. What it keeps is the part the suite is a gate for — a FIXED LOAD
 * ADDRESS reached through a custom script, with `.text.boot` placed first so
 * the ELF entry is the reset target QEMU jumps to under `-bios none -kernel`.
 *
 * `.fsmark` IS THE ASSERTION. `cases/link_address.saw` puts an `@section`
 * static in it and checks the address it reads back against the number written
 * below — so "the script placed this where it said" is a claim a running
 * program makes, not something a reader takes on trust. Editing the address
 * here without editing that case's expectation is a red case, which is the
 * point.
 *
 * NO `MEMORY` BLOCK, unlike the sos script it forks from, and that is not
 * tidying: a section carrying `> RAM` takes its address from the REGION's
 * allocation pointer, which silently ignores a `.` assignment above it — so
 * `.fsmark` landed immediately after `.data` and the case reported an address
 * 64 KiB below the one this file names. Plain dot arithmetic is what makes an
 * explicit placement mean what it says.
 */

OUTPUT_ARCH(riscv)
ENTRY(_start)

SECTIONS {
    . = 0x80000000;

    .text : {
        KEEP(*(.text.boot))
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
    }

    .data : {
        *(.data .data.*)
        *(.sdata .sdata.*)
    }

    /* The placement assertion, 512 KiB into the image — well clear of the text
     * and data of any case in this suite, and a round number a test can spell.
     *
     * It was 64 KiB until design 253 added `float_text`, whose image is ~118
     * KiB: std's float formatter carries two 128-bit power-of-five tables and
     * pulls the String layer in behind `to_string`. The overlap was a LINK
     * error naming both sections, which is the failure mode a fixed placement
     * should have — so the number moved rather than the case shrinking. Four
     * places spell it; see `cases/link_address.saw`. */
    . = 0x80080000;
    .fsmark : {
        KEEP(*(.fsmark))
    }

    .bss (NOLOAD) : {
        _bss_start = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        _bss_end = .;
    }

    /DISCARD/ : {
        *(.riscv.attributes)
        *(.comment)
        *(.eh_frame .eh_frame_hdr)
        *(.note .note.*)
    }
}

/* Freestanding-suite linker script (design 238 unit 1) — QEMU `virt`, arm64.
 *
 * Forked from `sos/hal/arm64/kernel/virt.ld` and deliberately smaller: no
 * `.payload` section, no root region, no grant window. What it keeps is the
 * part the suite is a gate for — a FIXED LOAD ADDRESS reached through a custom
 * script, with `.text.boot` placed first so the ELF entry is where QEMU starts.
 *
 * `.fsmark` IS THE ASSERTION; see the riscv32 script's note, including why
 * there is no `MEMORY` block. The address here differs from that one's, which
 * is what makes the case's per-architecture expectation a real comparison
 * rather than a constant that happens to match.
 */

OUTPUT_ARCH(aarch64)
ENTRY(_start)

SECTIONS {
    . = 0x40000000;

    .text : {
        KEEP(*(.text.boot))
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
    }

    .data : {
        *(.data .data.*)
    }

    /* The placement assertion, 512 KiB into the image — see the riscv32
     * script for why it is not 64 KiB any more. */
    . = 0x40080000;
    .fsmark : {
        KEEP(*(.fsmark))
    }

    .bss (NOLOAD) : ALIGN(4096) {
        _bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        _bss_end = .;
    }

    /DISCARD/ : {
        *(.comment)
        *(.eh_frame .eh_frame_hdr)
        *(.note .note.*)
        *(.ARM.attributes)
        *(.ARM.exidx*)
    }
}

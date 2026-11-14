/* Freestanding-suite linker script: ESP32-S3, executing in place from flash.
 *
 * Code and read-only data run from the flash window at 0x4200_0000; the
 * vector table is copied into IRAM, and .data and .bss live in DRAM. The flash
 * image the runner writes puts each segment at its LMA minus 0x4200_0000, so
 * the ROM's direct-boot words sit at 0x4200_0400 and the first instruction at
 * 0x4200_0408.
 *
 * L32R reaches only backwards, up to 256 KiB, so every output section that
 * holds code places each function's literal pool just ahead of that function's
 * code, which one input pattern does.
 *
 * IRAM starts at 0x4037_8000 and DRAM at 0x3FC8_C000: on silicon the two are
 * one SRAM seen through two buses, and these ranges stay disjoint under that
 * reading. DRAM ends below the ROM's own data (0x3FCD_7E04 up to 0x3FCE_FFFF),
 * which the other core's ROM loop may still be using.
 *
 * `.fsmark` IS THE ASSERTION. `cases/link_address.saw` puts an `@section`
 * static in it and checks the address it reads back against the number written
 * below. No `MEMORY` block: a section placed `> REGION` takes its address from
 * the region's cursor, which would ignore the explicit address this section
 * exists to test.
 */

OUTPUT_ARCH(xtensa)
ENTRY(_entry)

SECTIONS {
    .magic 0x42000400 : {
        KEEP(*(.magic))
    }

    .entry 0x42000408 : {
        KEEP(*(.entry))
    }

    .text : ALIGN(4) {
        *(.literal.start) *(.text.start)
        *(.literal .literal.* .text .text.*)
    }

    .rodata : ALIGN(4) {
        *(.rodata .rodata.*)
    }

    /* A table `@section("saw_table")` places, kept in flash with the read-only
     * data it is read beside. The name is a C identifier, so the linker
     * defines `__start_saw_table` and `__stop_saw_table` around it
     * (`cases/section_walk.saw`). Left to the default placement, the
     * orphan section lands at the cursor `.bss` also starts from. */
    saw_table : ALIGN(4) {
        *(saw_table)
    }

    /* 512 KiB into the flash window, the offset the runner's FSMARK_OFFSET and
     * `cases/link_address.saw` also state. */
    .fsmark 0x42080000 : {
        KEEP(*(.fsmark))
    }

    /* The sections that run elsewhere are stored behind the flash ones. */
    _iram_load = ALIGN(ADDR(.fsmark) + SIZEOF(.fsmark), 4);
    .iram 0x40378000 : AT(_iram_load) {
        _iram_start = .;
        *(.iram.vectors.literal)
        KEEP(*(.iram.vectors))
        . = ALIGN(4);
        _iram_end = .;
    }

    _data_load = ALIGN(_iram_load + SIZEOF(.iram), 4);
    .data 0x3FC8C000 : AT(_data_load) {
        _data_start = .;
        *(.data .data.*)
        . = ALIGN(4);
        _data_end = .;
    }

    .bss (NOLOAD) : ALIGN(16) {
        _bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        _bss_end = .;
    }

    .stack (NOLOAD) : ALIGN(16) {
        . += 0x10000;
        _stack_top = .;
    }

    ASSERT(_stack_top <= 0x3FCD0000, "the image's DRAM overruns the region below the ROM's data")
    ASSERT(_iram_end <= 0x4037C000, "the vector table overruns the 16 KiB of IRAM")

    /DISCARD/ : {
        *(.comment)
        *(.eh_frame .eh_frame_hdr)
        *(.note .note.*)
        *(.xtensa.info)
        *(.xt.prop .xt.prop.* .xt.lit .xt.lit.*)
    }
}

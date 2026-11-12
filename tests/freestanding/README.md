# The freestanding suite

These programs name the compiler's freestanding features directly
(`--freestanding`, `--no-hidden-alloc`, `--runtime`, cross-target codegen,
fixed-address linking) and run under QEMU. `sawc` builds them, and
`tools/freestanding_runner.py` is the harness: it compiles each case with the
three modules here (`rt` is `fsrt`, the runtime provider; `core` is `fscore`;
`data` is `fsdata`) through `--module-path`, links it with `hal/<arch>/boot.S`,
`hal/support.c` and `hal/<arch>/link.ld`, boots it, and matches its console
transcript and exit status. The refusal cases stop at the compile and match
sawc's diagnostic. `link_two_objects` links a second sawc object beside its
own and requires the link to fail on the duplicate `__saw_bt_table`, since an
image holds at most one object built by sawc.

```
tools/freestanding_runner.py                # every architecture that is on
tools/freestanding_runner.py hello          # named cases
tools/freestanding_runner.py --tools        # the prerequisite decision alone
```

Each architecture needs an emulator, `ld.lld` and a clang that compiles for
its target, and finds them itself. riscv32 and arm64 take `qemu-system-riscv32`,
`qemu-system-aarch64` and `ld.lld` from PATH, and the clang sawc's own record
beside the stages names (on macOS Apple's clang has no RISC-V backend, so
riscv32's is Homebrew's LLVM). xtensa takes Espressif's: the clang under
`$IDF_TOOLS_PATH` or `~/.espressif` (`tools/esp-clang`), the `ld.lld` beside it,
and the newest `tools/qemu-xtensa/*/qemu/bin/qemu-system-xtensa` from the same
roots, which must list an `esp32s3` machine. PATH's `qemu-system-xtensa` is never
used: Homebrew's has no such machine. An architecture with a tool known absent
is skipped, with a line naming it and the tool, and the others run; when no
architecture has its tools the suite skips and passes. When a tool's presence
cannot be determined (no PATH, a tool that does not answer, a `SAWC_CLANG` that
names no usable clang, an Espressif emulator without the machine) it fails. It
is the battery's `freestanding` stage and a part of the per-patch gate.

Three architectures run: riscv32 (`+m,+a,+c`, QEMU `virt -bios none`), arm64
and xtensa (the ESP32-S3, call0, no FPU, QEMU `-machine esp32s3`). The xtensa
row boots from a flash image the runner writes from the linked ELF: 4 MiB of
0xFF with each `PT_LOAD` segment at its load address minus 0x4200_0000, as the
ROM's direct boot expects (the magic words at 0x400, the first instruction at
0x408). Code runs in place from flash, the vector table runs from IRAM, and
`.data` and `.bss` live in DRAM (`hal/xtensa/link.ld`); a segment outside the
flash window fails the build. `hal/xtensa/boot.S` sets `ATOMCTL` itself, since
the emulator makes `s32c1i` fault under values a `-kernel` boot leaves.

The cases marked `no_atomics` build for a part without native atomics (riscv32
without the `A` extension, xtensa without `s32c1i`), where sawc's atomics are
`__atomic_*` libcalls: the object must reference exactly the five routines the
spec lists, and `hal/<arch>/atomics.c` supplies them, linked into those cases
alone. A case blocked by a sawc gap is marked `due` in the runner, citing the issue that
owns the gap, and must fail with that gap's diagnostic until the gap closes;
a gap on one architecture marks that row alone (`due_on`).

Each case object defines `memcpy`, `memset`, `memmove`, on riscv32 the
64-bit integer helpers (and on xtensa), and on every target, none of which has
an FP unit here, the soft-float routines itself, weakly (the spec's Profiles), so
the object leaves none of them undefined and the link carries no C library for
them. `hal/support.c` still defines the memory routines, `__udivdi3` and
`__umoddi3`, and its strong definitions win at the link. `integer_helpers`
runs each helper on the rows of `cases/integer_vectors.saw`, which
`tools/test_freestanding_runner.py` recomputes on the host; `int64_operators`
reaches them through Saw's operators at the suite's level and at `-Oz`.
`soft_float_vectors` runs each soft-float routine on the operands of
`compiler/tests/run/softfloat/vectors.txt`, compiler-rt's answers, and
checks each routine's checksum against the vectors'; `soft_float` reaches
them through Saw's `Float` operations.

`bladepkg/` is the Blade case (`blade build --target T`): the runner builds
Blade with sawc, then builds the package through it.

#!/usr/bin/env python3
"""The freestanding QEMU suite: sawc's freestanding output, built and run.

    tools/freestanding_runner.py [--arch NAME] [CASE...]
    tools/freestanding_runner.py --tools     # the tool decision alone

Each RUN case is compiled by sawc (`--freestanding --runtime
--no-hidden-alloc --target T`, with the suite's three modules through
`--module-path`), its object's undefined symbols read with `nm` (runtime
seams, the HAL's symbols and its atomic routines alone), linked by ld.lld
with a boot stub and a C floor at a fixed address, booted under
QEMU, and judged by its console transcript and exit status. A REFUSAL case stops at the compile and is judged by sawc's
diagnostic. A LINK-REFUSAL case links a second sawc object beside its own and
is judged by ld.lld's error. A case marked `due` is blocked by a sawc gap and cites the issue
that owns it; it must fail, and passing fails the run so the marker comes off.

Each architecture needs an emulator, ld.lld and a clang that compiles for its
target, found per architecture (`probe_arch`). An architecture whose tool is
known absent is SKIPPED, with a line naming it and the tool, and the others
run; the suite passes as a whole only if one ran or every one was skipped. It
FAILS when presence cannot be determined: no PATH at all, a tool that is
found but does not answer `--version`, a `SAWC_CLANG` that names no usable
clang, or an Espressif emulator that lists no `esp32s3` machine
(tools/test_freestanding_runner.py).

The suite lock is not taken here: the battery and the patch gate run this
inside the lock their caller already holds.
"""

import argparse
import glob
import os
import re
import shutil
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import blade_lane  # noqa: E402
import build  # noqa: E402
import child_groups  # noqa: E402
import gate_jobs  # noqa: E402
import patch_gate  # noqa: E402

FS_DIR = os.path.join(REPO, "tests", "freestanding")
CASES_DIR = os.path.join(FS_DIR, "cases")
HAL_DIR = os.path.join(FS_DIR, "hal")
SUPPORT_C = os.path.join(HAL_DIR, "support.c")

# The three modules every case composes, reached the way a kernel reaches its
# own: through `--module-path`, from a directory.
MODULES = {
    "fsrt": os.path.join(FS_DIR, "rt", "src"),
    "fscore": os.path.join(FS_DIR, "core", "src"),
    "fsdata": os.path.join(FS_DIR, "data", "src"),
}

QEMU_TIMEOUT_S = 20

# The optimization level every case is compiled at unless it is ABOUT another
# (`extra_flags`): the O1 pipeline the expectations were written against. At
# -O1 most of a case's constant float arithmetic folds away, so the soft-float
# routines are exercised by `soft_float`, which is built at -O0.
SUITE_LEVEL = "-O1"
BUILD_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 60

# A tool found but unable to answer: the suite cannot tell whether it may run.
EXIT_UNKNOWN = 4

# =============================================================================
# The architectures
# =============================================================================
#
# Everything that differs between the targets is here, as data. `word_bytes`,
# `int_max` and `mark_address` are what the per-architecture expectations are
# written against: a case's source is shared, so a target-dependent number is
# printed by the program and matched here rather than asserted there. An arch
# with `off` set is described but not run, and the reason says what it waits on.

# The soft-float routines a case object defines itself, neither target having
# an FPU here (LANGUAGE_SPEC.md, Profiles), in the order `soft_float_vectors`
# checks them; tools/test_freestanding_runner.py holds the list equal to the
# spec's.
SOFT_FLOAT_ROUTINES = (
    "__adddf3", "__subdf3", "__muldf3", "__divdf3",
    "__eqdf2", "__nedf2", "__ltdf2", "__ledf2", "__gtdf2", "__gedf2", "__unorddf2",
    "__fixdfsi", "__fixdfdi", "__fixunsdfsi", "__fixunsdfdi",
    "__floatsidf", "__floatdidf", "__floatunsidf", "__floatundidf",
)

# The Xtensa C half names each feature as a clang cc1 flag, since clang has no
# driver spelling for them.
XTENSA_FEATURES = ("-windowed", "-fp", "-loop", "-mac16", "-bool")


def xtensa_features(features):
    return [flag for feature in features for flag in ("-Xclang", "-target-feature", "-Xclang", feature)]


# Where each row finds its tools, and how it boots. `qemu_from`: "path" is the
# `qemu` binary on PATH, "espressif" the newest one under an Espressif tools
# root (`espressif_qemus`). `lld_from`: "path" is PATH's `ld.lld`, "clang" the
# one beside the row's clang, which is the only one that links its objects.
# `boot`: "kernel" hands QEMU the ELF, "flash" a flash image built from its
# `PT_LOAD` segments (`flash_image`), `flash_base` being where flash executes.
# `machine` names the board in the report. `ram_reads_negative` is whether a
# stack address read as an `Int` is below zero: true only where RAM starts above
# 2^31 on a 32-bit word.
ARCHES = [
    {
        "name": "riscv32",
        "triple": "riscv32-unknown-none-elf",
        "qemu": "qemu-system-riscv32",
        "qemu_from": "path",
        "lld_from": "path",
        "boot": "kernel",
        "machine": "virt",
        # `-bios none`: no OpenSBI, the case IS the reset target.
        "qemu_args": ["-M", "virt", "-bios", "none"],
        # Without `+m` the Saw half is built for base rv32i and formatting an
        # integer emits `__divsi3` calls this link cannot satisfy. The C half
        # gets the same set through `-march`.
        "cc_args": ["-march=rv32imac_zicsr", "-mabi=ilp32"],
        "features": "+m,+a,+c",
        # The part with no `A` extension (an ESP32-C3's shape), for the cases
        # marked `no_atomics`: the Saw half built without `+a`, and the
        # environment's atomic routines compiled for the same ISA and linked
        # beside the case.
        "no_atomics": {"features": "+m,+c", "cc_args": ["-march=rv32imc_zicsr", "-mabi=ilp32"],
                       "support": os.path.join(HAL_DIR, "riscv32", "atomics.c")},
        "word_bytes": 4,
        "load_base": 0x8000_0000,
        "ram_reads_negative": True,
        "off": None,
    },
    {
        "name": "arm64",
        "triple": "aarch64-unknown-none-elf",
        "qemu": "qemu-system-aarch64",
        "qemu_from": "path",
        "lld_from": "path",
        "boot": "kernel",
        "machine": "virt",
        # `-semihosting` is what makes SYS_EXIT carry a status code (see
        # hal/arm64/boot.S for why not PSCI); `gic-version=2` is pinned so a
        # newer emulator changing its default cannot swap the machine.
        "qemu_args": ["-M", "virt,gic-version=2", "-cpu", "cortex-a53", "-semihosting"],
        # The C half gets the Saw half's `-neon,-fp-armv8` too: general
        # registers only, and `aapcs-soft` so a `double` travels in the integer
        # registers, which is where the Saw half passes one to a soft-float
        # routine.
        "cc_args": ["-mgeneral-regs-only", "-mabi=aapcs-soft"],
        # None keeps sawc's freestanding default (`-neon,-fp-armv8`).
        "features": None,
        "no_atomics": None,
        "word_bytes": 8,
        "load_base": 0x4000_0000,
        "ram_reads_negative": False,
        "off": None,
    },
    {
        "name": "xtensa",
        "triple": "xtensa-esp-unknown-elf",
        # Espressif's build of QEMU, the only one with an ESP32-S3 machine; it
        # boots the flash image the runner writes, as the part does, and
        # `-semihosting` is what makes `simcall` carry an exit status.
        "qemu": "qemu-system-xtensa",
        "qemu_from": "espressif",
        "lld_from": "clang",
        "boot": "flash",
        "flash_base": 0x4200_0000,
        "machine": "esp32s3",
        "qemu_args": ["-machine", "esp32s3", "-semihosting"],
        # The C half gets the five features sawc's default for the triple
        # states: call0 (`-windowed`), no FPU (`-fp`), and the three the
        # compiler never uses. `-fintegrated-as` is for boot.S: the external
        # assembler writes compressed debug sections the linker refuses.
        "cc_args": ["-mcpu=esp32s3"] + xtensa_features(XTENSA_FEATURES) + ["-fintegrated-as"],
        # None keeps sawc's default for the triple.
        "features": None,
        # The part without `s32c1i`: its word atomics are `__atomic_*`
        # libcalls, which hal/xtensa/atomics.c supplies.
        "no_atomics": {"features": "-s32c1i",
                       "cc_args": ["-mcpu=esp32s3"] + xtensa_features(XTENSA_FEATURES + ("-s32c1i",))
                                  + ["-fintegrated-as"],
                       "support": os.path.join(HAL_DIR, "xtensa", "atomics.c")},
        "word_bytes": 4,
        "load_base": 0x4200_0000,
        "ram_reads_negative": False,
        "off": None,
    },
]

# The offset `hal/<arch>/link.ld` places `.fsmark` at: one number, two
# scripts, and `cases/link_address.saw` reads the resulting ADDRESS back.
FSMARK_OFFSET = 0x8_0000


def build_dir(arch):
    return os.path.join(build.BUILD_DIR, "freestanding", arch["triple"])


def expectations(arch):
    """The per-architecture substitutions a case's expected output is written in."""
    word = arch["word_bytes"]
    return {
        "word": str(word),
        "int_max": str(2 ** (word * 8 - 1) - 1),
        "mark_address": str(arch["load_base"] + FSMARK_OFFSET),
        "ram_reads_negative": "1" if arch["ram_reads_negative"] else "0",
    }


# What a RUN case's object may leave undefined besides its atomic routines:
# the runtime's seams, which fsrt defines, and the boot stub's `fs_*` hooks.
# The memory routines, the 64-bit integer helpers and the soft-float routines
# are not here: sawc's freestanding object defines them itself, weakly, so one
# it leaves undefined is a stray (SL-948). support.c still defines the memory
# routines, `__udivdi3` and `__umoddi3`, and its strong definitions win.
HAL_PREFIXES = ("__saw_rt_", "fs_")

# A name shaped like a compiler-rt floating-point builtin: an operation on a
# float mode (`__adddf3`, `__unorddf2`, `__extendsfdf2`), a float-to-integer
# conversion (`__fixunsdfsi`) or an integer-to-float one (`__floatundidf`). An
# object leaves none undefined: it defines the spec's soft-float routines
# itself, and no environment is told to supply any other.
FLOAT_MODE = "(?:hf|sf|df|tf|xf)"
SOFT_FLOAT_SHAPE = re.compile(r"^__(?:[a-z]+%s[0-9]|fix(?:uns)?%s(?:si|di|ti)|float(?:un)?(?:si|di|ti)%s)$"
                              % (FLOAT_MODE, FLOAT_MODE, FLOAT_MODE))


def atomic_routines(case, arch):
    """The `__atomic_*` routines a RUN case's object must reference: built
    without native atomics, exactly the five the spec lists at the word's
    width (Profiles); else none, since the target's instructions answer."""
    if not case.get("no_atomics"):
        return set()
    return {"__atomic_%s_%d" % (op, arch["word_bytes"])
            for op in ("load", "store", "fetch_add", "fetch_sub", "compare_exchange")}


# =============================================================================
# The architecture-free scan
# =============================================================================
#
# The suite's Saw modules compile unchanged for every target, and the
# `--module-path` claim rests on that. An architecture name in one of them
# would still compile and only be wrong on the profile nobody happened to be
# building, so the check is mechanical. Comments count.

ARCH_FREE_DIRS = [MODULES["fsrt"], MODULES["fscore"], MODULES["fsdata"]]

ARCH_WORDS = [
    "riscv", "rv32", "rv64", "aarch64", "arm64", "armv8",
    "mcause", "mepc", "mstatus", "mtvec", "mscratch", "ecall", "pmp",
    "ns16550", "pl011", "sifive", "semihost", "csr", "m-mode", "u-mode",
    "esr_el", "elr_el", "vbar", "ttbr", "sctlr", "tcr_el", "mair",
    "el0", "el1",
    "xtensa", "esp32", "simcall", "excsave", "vecbase", "windowbase",
]


def _is_english_embedding(line, token, at):
    """A token with a letter on BOTH sides is English, not a leak: the real
    usages are prefixes and suffixes of longer identifiers (`csrw`,
    `sctlr_el1`), which a word boundary on both sides would miss."""
    before = line[at - 1] if at > 0 else ""
    after_index = at + len(token)
    after = line[after_index] if after_index < len(line) else ""
    return before.isalpha() and after.isalpha()


def _sources_under(path):
    found = []
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            if name.endswith(".saw"):
                found.append(os.path.join(root, name))
    return found


def arch_free_problems():
    """Each line of a shared module that names an architecture."""
    bad = []
    for path in ARCH_FREE_DIRS:
        for src in _sources_under(path):
            with open(src, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    low = line.lower()
                    for word in ARCH_WORDS:
                        at = low.find(word)
                        while at >= 0:
                            if not _is_english_embedding(low, word, at):
                                bad.append("%s:%d: %r in: %s" % (os.path.relpath(src, REPO), lineno, word,
                                                                 line.strip()))
                                break
                            at = low.find(word, at + 1)
    return bad


# =============================================================================
# The cases
# =============================================================================
#
# A RUN case: the entry source, console substrings matched IN ORDER (each
# `str.format`ed with `expectations(arch)`), and whether the emulator exits 0.
# A REFUSAL case carries `expect_compile_error` instead: the compile must fail
# with exactly one diagnostic, holding those substrings in order. `runtime: False` withholds
# `--runtime` and `modules: False` the `--module-path` arguments, which is how
# the two provider refusals isolate what they are about. `arches` limits a
# case to the architectures it is about. `extra_flags` appends sawc flags for
# a case that is ABOUT a level, and `source` names the case file another case
# holds, built again at another level. `due` marks a case blocked by a sawc gap,
# citing the issue that owns the gap, and `due_shows` is the gap's own
# diagnostic: the case must fail saying it, so another failure is not hidden.
# `due_on` limits the marker to the arches it names, the case's other rows
# being real ones.
# `no_atomics` builds the case for the arch's part without native atomics
# (the arch's `no_atomics` entry), linking the environment's atomic routines;
# every RUN case's object is read with `nm` first and must reference exactly
# `atomic_routines`, and nothing else but runtime seams and the HAL's symbols
# (`references_problem`). `no_hidden_alloc: False` withholds `--no-hidden-alloc`
# from a case that is about an allocation the flag refuses.
# A LINK-REFUSAL case carries `expect_link_error` and `second_object`, the
# source of another sawc object compiled with no runtime and no suite module:
# the two objects and the HAL's must fail to link, the error holding those
# substrings in order, and nothing is booted.
#
# The Blade case (`"blade": True`) is `blade build --target T` over
# `tests/freestanding/bladepkg`: Blade, built by sawc, resolves the package,
# drives sawc, the cross clang and ld.lld, and the runner boots the ELF it
# leaves under the package's `.build/T/`. Its `expect_out` is the program's.

# The checks `float_methods` and its -O0 twin print, in order.
FLOAT_METHOD_CHECKS = ["fs check %s=1" % claim for claim in (
    "abs_negative", "abs_negative_zero", "abs_nan_sign_only",
    "floor_fraction", "floor_negative", "floor_negative_half", "floor_half", "floor_negative_zero",
    "floor_last_half", "floor_nan",
    "ceil_fraction", "ceil_negative", "ceil_negative_half",
    "round_tie_up", "round_tie_down", "round_negative_small", "round_below_half", "round_last_half",
    "sqrt_two", "sqrt_square", "sqrt_negative_zero", "sqrt_negative", "sqrt_subnormal", "sqrt_infinity",
    "min_zeros", "min_zeros_reversed", "min_quiet_nan", "min_signalling_nan", "min_two_nans",
    "max_zeros", "max_zeros_reversed", "max_signalling_nan", "max_ordered")]

# The checks `integer_helpers` prints at each level, in order.
INTEGER_HELPER_CHECKS = ["fs check %s_vectors=1" % helper for helper in (
    "udivdi3", "umoddi3", "divdi3", "moddi3", "ashldi3", "lshrdi3", "ashrdi3")]

# The checks `int64_operators` prints at each level, in order.
INT64_OPERATOR_CHECKS = ["fs check %s_operator_rows=1" % kind for kind in ("signed", "unsigned", "shift")]

# The checks `soft_float_vectors` prints at each level, in order.
SOFT_FLOAT_VECTOR_CHECKS = ["fs check %s_vectors=1" % routine[2:] for routine in SOFT_FLOAT_ROUTINES]

TEST_CASES = [
    {
        # The floor. If this is red nothing else here means anything.
        "name": "hello",
        "expect_out": ["fs: hello from freestanding Saw",
                       "fs check entered=1",
                       "fs done hello ok"],
        "expect_clean_exit": True,
    },
    # --- cross-target codegen -------------------------------------------------
    {
        # Platform-width `Int` and pointer size: the `fs value` lines carry the
        # per-architecture expectation, every `fs check` holds on every target.
        "name": "int_widths",
        "expect_out": ["fs value sizeof_int={word}",
                       "fs value sizeof_uint={word}",
                       "fs value alignof_int={word}",
                       "fs value int_max={int_max}",
                       "fs check int_matches_uint=1",
                       "fs check int_is_pointer_width=1",
                       "fs check sizeof_int8=1",
                       "fs check sizeof_int16=1",
                       "fs check sizeof_int32=1",
                       "fs check sizeof_int64=1",
                       "fs check sizeof_uint64=1",
                       "fs check alignof_int64=1",
                       "fs check wide_high_half=1",
                       "fs check wide_low_half=1",
                       "fs check wide_sum=1",
                       "fs check wide_compare=1",
                       "fs check wide_roundtrip=1",
                       "fs check wide_divide=1",
                       "fs check wide_modulo=1",
                       "fs done int_widths ok"],
        "expect_clean_exit": True,
    },
    {
        # Struct layout asserted at RUN time through a typed view over bytes
        # written by hand, plus the aggregate-by-value ABI.
        "name": "struct_layout",
        "expect_out": ["fs check descriptor_size=1",
                       "fs check descriptor_align=1",
                       "fs check field_magic=1",
                       "fs check field_version=1",
                       "fs check field_flags=1",
                       "fs check field_length=1",
                       "fs check field_origin=1",
                       "fs check record_is_current=1",
                       "fs check flag_readable=1",
                       "fs check flag_writable=1",
                       "fs check flag_executable_clear=1",
                       "fs check by_value_length=1",
                       "fs check by_value_magic=1",
                       "fs check by_value_origin=1",
                       "fs check by_value_checksum=1",
                       "fs done struct_layout ok"],
        "expect_clean_exit": True,
    },
    {
        # Twelve mixed-width arguments past the register budget, negative
        # narrow arguments, an aggregate return, one aggregate forwarded three
        # frames by value.
        "name": "call_convention",
        "expect_out": ["fs check twelve_arguments=1",
                       "fs check bool_argument=1",
                       "fs check signed_narrow_arguments=1",
                       "fs check aggregate_return_length=1",
                       "fs check aggregate_return_magic=1",
                       "fs check aggregate_three_frames=1",
                       "fs done call_convention ok"],
        "expect_clean_exit": True,
    },
    # --- module composition ---------------------------------------------------
    {
        # Three modules in a diamond: a `static` folded across a module
        # boundary into an array length, a method and a raw-backed enum from a
        # third module, a generic instantiated at a type declared elsewhere.
        "name": "module_compose",
        "expect_out": ["fs check static_crossed_modules=1",
                       "fs check mirror_is_writable=1",
                       "fs check method_crossed_modules=1",
                       "fs check enum_crossed_modules=1",
                       "fs summary descriptor=1146569241",
                       "fs check summary_matches_checksum=1",
                       "fs check wide_literal_through_qualifier=1",
                       "fs check narrow_literal_through_qualifier=1",
                       "fs done module_compose ok"],
        "expect_clean_exit": True,
    },
    {
        # A `FuncPointer` table in a `static`, called through in place, the
        # boot hook an optional field of a bare `unsafe static var`, and a
        # pointer's `address()` round trip through `from_raw` (SL-940).
        "name": "func_pointer_table",
        "expect_out": ["fs check table_run=1",
                       "fs check table_alt=1",
                       "fs check table_zero=1",
                       "fs check hook_before_boot=1",
                       "fs check hook_after_boot=1",
                       "fs check address_nonzero=1",
                       "fs check address_round_trip=1",
                       "fs check thread_entry_nonzero=1",
                       "fs check thread_entry_stable=1",
                       "fs done func_pointer_table ok"],
        "expect_clean_exit": True,
    },
    # --- the runtime provider -------------------------------------------------
    {
        # The seams REACHED by a running program: the line writer, alloc and
        # dealloc (the Vectors the source names) and the executable path's
        # NULL stub. The arena cursor turns "it did not crash" into "the seam
        # answered".
        "name": "runtime_seams",
        "expect_out": ["fs check arena_starts_empty=1",
                       "fs check vector_length=1",
                       "fs check vector_sum=1",
                       "fs check alloc_seam_answered=1",
                       "fs check second_vector_length=1",
                       "fs check alloc_seam_advanced=1",
                       "fs check executable_path_seam_is_null=1",
                       "fs check executable_path_status_not_found=1",
                       "fs done runtime_seams ok"],
        "expect_clean_exit": True,
    },
    {
        # The panic seam, which ends the machine. The STATUS is asserted as
        # well as the message: `fsrt`'s ExitCode.Panic.
        "name": "runtime_panic",
        "expect_out": ["fs check reached_panic_case=1",
                       "fs: about to panic",
                       "panic at runtime_panic.saw:",
                       "fs: deliberate panic"],
        "expect_clean_exit": False,
        "expect_status": 64,
    },
    {
        # The provider refused: the same export, `--runtime` withheld.
        "name": "runtime_export_ungated",
        "runtime": False,
        "modules": False,
        "expect_compile_error": ["export.reserved",
                                 "`@export` symbol `__saw_rt_write` collides with a reserved runtime symbol"],
    },
    {
        # The provider granted, and the signature checked against the frozen
        # contract. Arity rather than width: a width mismatch that is wrong on
        # one target can be right on the other.
        "name": "runtime_seam_signature",
        "modules": False,
        "expect_compile_error": ["export.seam-signature",
                                 "`@export` seam `__saw_rt_write` does not match the runtime ABI",
                                 "it is `(word) -> word`",
                                 "runtime/ABI.md freezes it as `(word, word) -> word`"],
    },
    # --- no hidden allocations ------------------------------------------------
    #
    # Three refusals and one green control: three rows that must not compile
    # are satisfied by a flag that rejects everything, and the fourth is what
    # says the flag discriminates.
    {
        "name": "hidden_alloc_interpolation",
        "expect_compile_error": ["alloc.hidden", "hidden_alloc_interpolation.saw:15:",
                                 "string interpolation allocates a String", "--no-hidden-alloc"],
    },
    {
        "name": "hidden_alloc_escaping_closure",
        "expect_compile_error": ["alloc.hidden", "hidden_alloc_escaping_closure.saw:21:",
                                 "an escaping closure heap-allocates its captured environment",
                                 "--no-hidden-alloc"],
    },
    {
        "name": "hidden_alloc_print_printable",
        "expect_compile_error": ["alloc.hidden", "hidden_alloc_print_printable.saw:25:",
                                 "renders `hidden_alloc_print_printable.Tag` through `to_string()`, which "
                                 "allocates a String", "--no-hidden-alloc"],
    },
    {
        "name": "format_no_alloc",
        "expect_out": ["fs: n = 42",
                       "fs: 42 and 43",
                       "fs: text 7 true",
                       "fs check closure_captures_on_the_stack=1",
                       "fs check escaping_closure_without_captures=1",
                       "fs done format_no_alloc ok"],
        "expect_clean_exit": True,
    },
    {
        # Float text with no libc: the formatter is Saw over integer tables.
        "name": "float_text",
        "expect_out": ["fs check integral=1",
                       "fs check negative=1",
                       "fs check drift=1",
                       "fs check thirds=1",
                       "fs check fixed_high=1",
                       "fs check exp_high=1",
                       "fs check fixed_low=1",
                       "fs check exp_low=1",
                       "fs check min_subnormal=1",
                       "fs check max_finite=1",
                       "fs check infinity=1",
                       "fs check negative_infinity=1",
                       "fs check not_a_number=1",
                       "fs check zero=1",
                       "fs check negative_zero=1",
                       "fs value fmt_arg=0.30000000000000004",
                       "fs value print_arm=\n1.5",
                       "fs done float_text ok"],
        "expect_clean_exit": True,
    },
    {
        # The 64-bit serialization data model on a bare machine: Int64/UInt64
        # round-trip whole through a slot and through std.json's text, and a
        # value past the platform Int (or past 64 bits) is OutOfRange, never
        # a panic. Every check is the same line on every target.
        "name": "serialize_int64",
        "expect_out": ["fs check int64_max_round_trip=1",
                       "fs check int64_min_round_trip=1",
                       "fs check uint64_max_round_trip=1",
                       "fs check int_reads_small=1",
                       "fs check int_reads_int_min=1",
                       "fs check int_reads_int64_max=1",
                       "fs check int_reads_int64_min=1",
                       "fs check uint_reads_small=1",
                       "fs check uint_reads_uint_max=1",
                       "fs check uint_reads_uint64_max=1",
                       "fs check int32_reads_just_over=1",
                       "fs check int32_reads_min=1",
                       "fs check json_int64_max_round_trip=1",
                       "fs check json_int64_min_round_trip=1",
                       "fs check json_uint64_max_round_trip=1",
                       "fs check json_uint64_past_range=1",
                       "fs check json_int64_past_range=1",
                       "fs done serialize_int64 ok"],
        "expect_clean_exit": True,
    },
    {
        # Every Float operation as a soft-float call: at -O0 nothing folds, so
        # each of the spec's routines runs, the ones the object defines
        # itself.
        "name": "soft_float",
        "extra_flags": ["-O0"],
        "expect_out": ["fs value add=0.30000000000000004",
                       "fs value sub=0.19999999999999998",
                       "fs value mul=0.30000000000000004",
                       "fs value div=0.3333333333333333",
                       "fs value negate=-2.5",
                       "fs value negate_zero=-0.0",
                       "fs value compound=1.625",
                       "fs value add_tie_even=9007199254740992.0",
                       "fs value mul_underflow=0.0",
                       "fs value mul_subnormal=1e-323",
                       "fs value mul_overflow=inf",
                       "fs value div_by_zero=inf",
                       "fs value div_negative_by_zero=-inf",
                       "fs value div_zero_by_zero=nan",
                       "fs check lt_holds=1",
                       "fs check lt_refused=1",
                       "fs check le_equal=1",
                       "fs check le_refused=1",
                       "fs check gt_holds=1",
                       "fs check gt_refused=1",
                       "fs check ge_equal=1",
                       "fs check ge_refused=1",
                       "fs check eq_holds=1",
                       "fs check eq_signed_zeros=1",
                       "fs check eq_refused=1",
                       "fs check ne_holds=1",
                       "fs check ne_refused=1",
                       "fs check nan_lt=1",
                       "fs check nan_le=1",
                       "fs check nan_gt=1",
                       "fs check nan_ge=1",
                       "fs check nan_eq=1",
                       "fs check nan_ne=1",
                       "fs check nan_is_nan=1",
                       "fs check one_is_not_nan=1",
                       "fs value as_i8=127",
                       "fs value as_i8_negative=-128",
                       "fs value as_i16=-32768",
                       "fs value as_i32=2147483647",
                       "fs value as_i32_negative=-2147483648",
                       "fs value as_i64=-9223372036854775808",
                       "fs value as_i64_large=4611686018427387904",
                       "fs value as_int=-123456",
                       "fs value as_u8=255",
                       "fs value as_u16=65535",
                       "fs value as_u32=4294967295",
                       "fs value as_u64=18446744073709549568",
                       "fs value as_uint=3000000000",
                       "fs value as_uint_negative_fraction=0",
                       "fs check from_i8_fits=1",
                       "fs check from_i8_above=1",
                       "fs check from_i16_fits=1",
                       "fs check from_i32_nan=1",
                       "fs check from_i64_min=1",
                       "fs check from_i64_above=1",
                       "fs check from_int_infinity=1",
                       "fs check from_u8_negative=1",
                       "fs check from_u8_negative_fraction=1",
                       "fs check from_u16_fits=1",
                       "fs check from_u32_above=1",
                       "fs check from_u64_fits=1",
                       "fs check from_u64_above=1",
                       "fs check from_uint_fits=1",
                       "fs value from_i8=-128.0",
                       "fs value from_i16=32767.0",
                       "fs value from_i32=-2147483648.0",
                       "fs value from_i64=-1.0",
                       "fs value from_i64_rounded=9007199254740992.0",
                       "fs value from_int=-1000.0",
                       "fs value from_u8=255.0",
                       "fs value from_u16=65535.0",
                       "fs value from_u32=4294967295.0",
                       "fs value from_u64=1.8446744073709552e+19",
                       "fs value from_uint=4000000000.0",
                       "fs check exact_i64_absent=1",
                       "fs check exact_i64_present=1",
                       "fs check exact_u64_absent=1",
                       "fs check exact_i32_present=1",
                       "fs done soft_float ok"],
        "expect_clean_exit": True,
    },
    {
        # std.numeric's Float methods as their Saw bodies, with no libm: a
        # libm name the object references is a stray (SL-944).
        "name": "float_methods",
        "expect_out": FLOAT_METHOD_CHECKS + ["fs done float_methods ok"],
        "expect_clean_exit": True,
    },
    {
        # The same checks at -O0, where every method is a call.
        "name": "float_methods_unoptimized",
        "extra_flags": ["-O0"],
        "expect_out": FLOAT_METHOD_CHECKS + ["fs done float_methods_unoptimized ok"],
        "expect_clean_exit": True,
    },
    {
        # `@align(N)` reaches the object at `-Oz`, on the arch and level where
        # an optimizer's repacking made a missing alignment a fault.
        "name": "align_attribute",
        "extra_flags": ["-Oz"],
        "arches": ["riscv32", "xtensa"],
        "expect_out": ["fs check local_align_8=1",
                       "fs check local_align_64=1",
                       "fs check local_align_by_ref=1",
                       "fs check static_align_64=1",
                       "fs check static_align_16=1",
                       "fs check seeded_value=1",
                       "fs done align_attribute ok"],
        "expect_clean_exit": True,
    },
    {
        # An entry-module `@export` (bare, renamed, and on a static) in a
        # program whose coroutine transform runs.
        "name": "export_with_coroutine",
        "expect_out": ["fs check bare_export_callable=1",
                       "fs check renamed_export_callable=1",
                       "fs check exported_static_readable=1",
                       "fs check coroutine_ran=1",
                       "fs done export_with_coroutine ok"],
        "expect_clean_exit": True,
    },
    # --- the cooperative executor ---------------------------------------------
    {
        # A cooperative `TaskGroup` on `fsrt`'s executor set: a yielding task
        # and one asleep on a timer, both joined.
        "name": "cooperative_group",
        "expect_out": ["fs check yielding_task_joined=1",
                       "fs check sleeping_task_joined=1",
                       "fs check group_empty_after_joins=1",
                       "fs done cooperative_group ok"],
        "expect_clean_exit": True,
    },
    {
        # The deadlock report: the panic line, then the task dump naming the
        # channel-parked task and its frame, and `fsrt`'s panic status. On
        # riscv32 the channel's word lies above 2^31, so its park word is a
        # negative `Int`.
        "name": "cooperative_deadlock",
        "expect_out": ["fs check reached_the_join=1",
                       "panic at ",
                       "deadlock: every task is waiting to receive from a channel",
                       "saw tasks: 1 live (as-of panic, unsynchronized)",
                       "task group 1 slot 0 gen 1 channel-parked",
                       "at cooperative_deadlock.saw:",
                       " in drained"],
        "expect_clean_exit": False,
        "expect_status": 64,
    },
    {
        # A channel park that wakes: a receiver parked on an empty channel,
        # resumed with a sibling's message.
        "name": "cooperative_channel_park",
        "expect_out": ["fs value ram_reads_negative={ram_reads_negative}",
                       "fs check receiver_took_the_message=1",
                       "fs check sender_sent=1",
                       "fs done cooperative_channel_park ok"],
        "expect_clean_exit": True,
    },
    {
        # A drive point whose frame parks on a channel, resumed once the
        # group's sender sets the channel's word.
        "name": "cooperative_drive",
        "expect_out": ["fs value ram_reads_negative={ram_reads_negative}",
                       "fs check drive_point_received=1",
                       "fs check sender_sent=1",
                       "fs done cooperative_drive ok"],
        "expect_clean_exit": True,
    },
    # --- the linker script ----------------------------------------------------
    {
        # `@section` plus a fixed address: the OFFSET is the program's claim,
        # the ADDRESS the runner's, and the VALUE says the section was loaded.
        "name": "link_address",
        "expect_out": ["fs check fsmark_offset=1",
                       "fs value fsmark_address={mark_address}",
                       "fs check fsmark_value=1",
                       "fs check ordinary_static_below_fsmark=1",
                       "fs done link_address ok"],
        "expect_clean_exit": True,
    },
    {
        # Four `@section("saw_table")` statics nothing names, one also
        # `@export`ed, walked between the linker's `__start_`/`__stop_`
        # symbols: every placement survives the link and lies in the range.
        "name": "section_walk",
        "expect_out": ["fs check table_bytes_whole_entries=1",
                       "fs check table_count=1",
                       "fs entry 0 id=1 weight=100",
                       "fs entry 1 id=2 weight=200",
                       "fs entry 2 id=4 weight=400",
                       "fs entry 3 id=8 weight=800",
                       "fs check table_ids_all_present=1",
                       "fs check table_weight_total=1",
                       "fs done section_walk ok"],
        "expect_clean_exit": True,
    },
    {
        # An image holds at most one sawc object (LANGUAGE_SPEC.md, Profiles):
        # a second one fails the link on the backtrace table both define. The
        # pin becomes a RUN case with SL-955's one final link per image.
        "name": "link_two_objects",
        "second_object": "link_two_objects_second",
        "expect_link_error": ["duplicate symbol: __saw_bt_table\n", "link_two_objects.o",
                              "link_two_objects_second.o"],
    },
    {
        # A wider-than-word integer renders whole; riscv32 only, since on arm64
        # the word already is 64 bits.
        "name": "wide_value_rendering",
        "arches": ["riscv32", "xtensa"],
        "expect_out": ["fs value signed=20014547621496",
                       "fs value unsigned=20014547621496",
                       "fs value negative=-20014547621496",
                       "fs value max=18446744073709551615",
                       "fs done wide_value_rendering ok"],
        "expect_clean_exit": True,
    },
    {
        # Integers wider than the word rendered by a `{}` argument, an
        # interpolation and `to_string()`, a `UInt32` above 2^31, and both
        # hashed. On riscv32 this is the 64-bit renderers' and the Printable
        # glue's execution; arm64, where every value is at most the word, is
        # the control.
        "name": "wide_hash_format",
        "no_hidden_alloc": False,
        "expect_out": ["fs value arg_signed=20014547621496",
                       "fs value arg_negative=-20014547621496",
                       "fs value arg_largest=9223372036854775807",
                       "fs value arg_smallest=-9223372036854775808",
                       "fs value arg_unsigned_max=18446744073709551615",
                       "fs value arg_above_half=3000000000",
                       "fs value arg_all_ones=4294967295",
                       "fs value arg_narrow_min=-2147483648",
                       "fs value interpolated=20014547621496 -20014547621496 9223372036854775807 "
                       "-9223372036854775808 18446744073709551615 3000000000 4294967295 -2147483648",
                       "fs value to_string_smallest=-9223372036854775808",
                       "fs check interpolated_matches_arguments=1",
                       "fs check equal_wide_values_hash_alike=1",
                       "fs check equal_narrow_values_hash_alike=1",
                       "fs check wide_keys_distinct=1",
                       "fs check wide_key_low_twin=1",
                       "fs check wide_key_high_twin=1",
                       "fs check wide_key_negative=1",
                       "fs check narrow_keys_distinct=1",
                       "fs check narrow_key_above_half=1",
                       "fs check narrow_key_below_half=1",
                       "fs done wide_hash_format ok"],
        "expect_clean_exit": True,
    },
    # --- the builtin routines -------------------------------------------------
    {
        # std's 64-bit integer helpers, each called by its C symbol on
        # host-computed rows, at -O0 and, below, at -O2 (SL-948).
        "name": "integer_helpers",
        "extra_flags": ["-O0"],
        "arches": ["riscv32", "xtensa"],
        "expect_out": INTEGER_HELPER_CHECKS + ["fs done integer_helpers ok"],
        "expect_clean_exit": True,
    },
    {
        "name": "integer_helpers_optimized",
        "source": "integer_helpers",
        "extra_flags": ["-O2"],
        "arches": ["riscv32", "xtensa"],
        "expect_out": INTEGER_HELPER_CHECKS + ["fs done integer_helpers ok"],
        "expect_clean_exit": True,
    },
    {
        # std's soft-float routines, each called by its C symbol on the
        # soft-float vectors' operands, their results folded into checksums
        # the vectors hold, at -O0 and, below, at -O2 (SL-948).
        "name": "soft_float_vectors",
        "extra_flags": ["-O0"],
        "expect_out": SOFT_FLOAT_VECTOR_CHECKS + ["fs done soft_float_vectors ok"],
        "expect_clean_exit": True,
    },
    {
        "name": "soft_float_vectors_optimized",
        "source": "soft_float_vectors",
        "extra_flags": ["-O2"],
        "expect_out": SOFT_FLOAT_VECTOR_CHECKS + ["fs done soft_float_vectors ok"],
        "expect_clean_exit": True,
    },
    {
        # 64-bit `/`, `%` and variable shifts through the operators: on riscv32
        # the object calls the integer helpers it defines, and leaves none of
        # them undefined (SL-947).
        "name": "int64_operators",
        "expect_out": INT64_OPERATOR_CHECKS + ["fs done int64_operators ok"],
        "expect_clean_exit": True,
    },
    {
        # The same at -Oz, where the shifts become helper calls too.
        "name": "int64_operators_size",
        "source": "int64_operators",
        "extra_flags": ["-Oz"],
        "arches": ["riscv32", "xtensa"],
        "expect_out": INT64_OPERATOR_CHECKS + ["fs done int64_operators ok"],
        "expect_clean_exit": True,
    },
    {
        # Saw's divide-by-zero check fires before the division reaches a
        # helper, and ends the machine with `fsrt`'s panic status.
        "name": "int64_divide_by_zero",
        "expect_out": ["fs check reached_the_division=1",
                       "panic at int64_divide_by_zero.saw:",
                       "division by zero"],
        "expect_clean_exit": False,
        "expect_status": 64,
    },
    {
        # `Int64.min / -1` likewise, at Saw's overflow check.
        "name": "int64_divide_overflow",
        "expect_out": ["fs check reached_the_division=1",
                       "panic at int64_divide_overflow.saw:",
                       "integer overflow"],
        "expect_clean_exit": False,
        "expect_status": 64,
    },
    # --- atomics --------------------------------------------------------------
    {
        # The word's atomics where the target has them: `Atomic<Int>`, a
        # String's refcount and a `SpinLock`, with no `__atomic_*` routine
        # referenced.
        "name": "atomics_word",
        "expect_out": ["fs check load_after_store=1",
                       "fs check fetch_add_returns_before=1",
                       "fs check fetch_add_applied=1",
                       "fs check fetch_add_negative_returns_before=1",
                       "fs check fetch_add_negative_applied=1",
                       "fs check compare_exchange_matches=1",
                       "fs check compare_exchange_stored=1",
                       "fs check compare_exchange_mismatch_refused=1",
                       "fs check compare_exchange_mismatch_kept=1",
                       "fs check string_copy_shares=1",
                       "fs check string_copy_length=1",
                       "fs check spinlock_released_after_lock=1",
                       "fs check spinlock_try_lock_taken=1",
                       "fs check spinlock_released_after_try_lock=1",
                       "fs check spinlock_guarded_value=1",
                       "fs done atomics_word ok"],
        "expect_clean_exit": True,
    },
    {
        # The same atomics on the part without them: the object references
        # exactly the spec's five routines, which `hal/riscv32/atomics.c`
        # supplies (the user's ruling: the environment provides them).
        "name": "atomics_libcall",
        "arches": ["riscv32", "xtensa"],
        "no_atomics": True,
        "expect_out": ["fs check load_after_store=1",
                       "fs check fetch_add_returns_before=1",
                       "fs check fetch_add_applied=1",
                       "fs check fetch_add_negative_returns_before=1",
                       "fs check fetch_add_negative_applied=1",
                       "fs check compare_exchange_matches=1",
                       "fs check compare_exchange_stored=1",
                       "fs check compare_exchange_mismatch_refused=1",
                       "fs check compare_exchange_mismatch_kept=1",
                       "fs check string_copy_shares=1",
                       "fs check string_copy_length=1",
                       "fs done atomics_libcall ok"],
        "expect_clean_exit": True,
    },
    {
        # A `SpinLock` stays refused on the part without atomics.
        "name": "spinlock_without_atomics",
        # The refusal's wording names the target and the feature that restores
        # atomics, so Xtensa's own wording is pinned by the typechecker's fixture.
        "arches": ["riscv32"],
        "no_atomics": True,
        "expect_compile_error": ["atomics.target", "spinlock_without_atomics.saw:10:",
                                 "`SpinLock` needs target atomics, and `riscv32-unknown-none-elf` has none",
                                 "a `SpinLock` spins on a hardware read-modify-write, so it needs native atomics",
                                 "add `+a` to the `--target-features` list"],
    },
    {
        # The non-host build path reached through a manifest, on every arch.
        "name": "bladepkg",
        "blade": True,
        "package": "bladepkg",
        "image": "fsblade",
        "expect_out": ["fs: hello from a Blade-built image",
                       "fs check blade_built_image_ran=1",
                       "fs check blade_arithmetic=1",
                       "fs done blade_target ok"],
        "expect_clean_exit": True,
    },
]

ESPRESSIF_HINT = "install Espressif's tools: idf_tools.py install esp-clang qemu-xtensa"

INSTALL_HINTS = {
    "qemu-system-riscv32": "brew install qemu (macOS) | apt install qemu-system-misc (Debian/Ubuntu)",
    "qemu-system-aarch64": "brew install qemu (macOS) | apt install qemu-system-arm (Debian/Ubuntu)",
    "ld.lld": "brew install lld (macOS) | apt install lld (Debian/Ubuntu)",
    "clang": "brew install llvm (macOS) | apt install clang-19 (Debian/Ubuntu)",
}


# =============================================================================
# Child processes
# =============================================================================

def run(cmd, timeout, cwd=REPO):
    """(exit status or None on a timeout, combined output) of `cmd`, started
    through child_groups so a TERM to this runner ends it."""
    try:
        proc = child_groups.start(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as e:
        return 127, "%s: %s" % (cmd[0], e)
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        out, _ = proc.communicate()
        code = None
    finally:
        child_groups.forget(proc)
    return code, out or ""


class ToolError(Exception):
    pass


def checked(cmd, timeout=BUILD_TIMEOUT_S):
    code, out = run(cmd, timeout)
    if code != 0:
        why = "timed out after %ds" % timeout if code is None else "exit %d" % code
        raise ToolError("command failed (%s): %s\n%s" % (why, " ".join(cmd), out))
    return out


# =============================================================================
# The tools
# =============================================================================

class Absent(Exception):
    """A prerequisite known not to be installed: the suite skips."""


class Unknown(Exception):
    """A prerequisite whose presence cannot be determined: the suite fails."""


def check_answers(path, name):
    """`path`, which must answer `--version`."""
    code, out = run([path, "--version"], PROBE_TIMEOUT_S)
    if code != 0:
        why = "timed out" if code is None else "exited %d" % code
        raise Unknown("%s is found at %s but `%s --version` %s, so whether it runs is unknown: %s"
                      % (name, path, path, why, out.strip()[:300] or "no output"))
    return path


def find_tool(name):
    """The absolute path of `name` on PATH, which answers `--version`."""
    if os.environ.get("PATH") is None:
        raise Unknown("PATH is not set, so whether %s is installed is unknown" % name)
    path = shutil.which(name)
    if path is None:
        raise Absent("%s is not on PATH (%s)" % (name, INSTALL_HINTS.get(name, "install it")))
    return check_answers(path, name)


def find_clang(arch):
    """The clang `build.choose_clang` picks for the arch's target: the one
    sawc's own record names. A `SAWC_CLANG` that names no usable clang is a
    configuration error, not an absence."""
    if os.environ.get("PATH") is None:
        raise Unknown("PATH is not set, so whether a clang is installed is unknown")
    clang, why = build.choose_clang(arch["triple"])
    if clang is None:
        if os.environ.get("SAWC_CLANG"):
            raise Unknown("SAWC_CLANG names no clang that compiles for %s: %s" % (arch["triple"], why))
        hint = ESPRESSIF_HINT if arch["triple"].startswith("xtensa-") else INSTALL_HINTS["clang"]
        raise Absent("no clang compiles for %s (%s): %s" % (arch["triple"], hint, why))
    return clang


def find_lld(arch, clang):
    """The linker for the arch: PATH's `ld.lld`, or for a row whose objects
    only the clang's own LLVM links, the one beside that clang."""
    if arch["lld_from"] == "path":
        return find_tool("ld.lld")
    said = build.clang_tool(clang, "ld.lld")
    if not os.path.isabs(said) or not os.path.exists(said):
        raise Absent("ld.lld is not beside %s (%s)" % (clang, ESPRESSIF_HINT))
    return check_answers(said, "ld.lld")


def espressif_qemus():
    """Every `qemu-system-xtensa` under an Espressif tools root, the newest
    version of a root first: `$IDF_TOOLS_PATH` when set, then `~/.espressif`.
    PATH's `qemu-system-xtensa` is never one: Homebrew's has no ESP32 machine."""
    roots = [os.environ.get("IDF_TOOLS_PATH") or "", os.path.join(os.path.expanduser("~"), ".espressif")]
    found = []
    for root in roots:
        if root:
            pattern = os.path.join(root, "tools", "qemu-xtensa", "*", "qemu", "bin", "qemu-system-xtensa")
            found.extend(sorted(glob.glob(pattern), reverse=True))
    return found


def find_qemu(arch):
    """The emulator for the arch. An Espressif build must list the arch's
    machine under `-machine help`; one that does not is an install that is not
    what it claims, which is not an absence."""
    if arch["qemu_from"] == "path":
        return find_tool(arch["qemu"])
    candidates = espressif_qemus()
    if not candidates:
        raise Absent("%s is not under $IDF_TOOLS_PATH or ~/.espressif (%s)" % (arch["qemu"], ESPRESSIF_HINT))
    refused = []
    for path in candidates:
        code, out = run([path, "-machine", "help"], PROBE_TIMEOUT_S)
        if code != 0:
            why = "timed out" if code is None else "exited %d" % code
            raise Unknown("%s is found but `-machine help` %s, so whether it runs is unknown: %s"
                          % (path, why, out.strip()[:300] or "no output"))
        if arch["machine"] in out.split():
            return path
        refused.append(path)
    raise Unknown("%s lists no `%s` machine, so it is not the Espressif emulator" % (", ".join(refused),
                                                                                    arch["machine"]))


def probe_arch(arch):
    """{"qemu", "lld", "clang"} for one architecture, or Absent/Unknown. A row
    whose linker is beside its clang looks for the clang first."""
    found = {}
    if arch["lld_from"] == "clang":
        found["clang"] = find_clang(arch)
        found["lld"] = find_lld(arch, found["clang"])
        found["qemu"] = find_qemu(arch)
    else:
        found["lld"] = find_lld(arch, None)
        found["qemu"] = find_qemu(arch)
        found["clang"] = find_clang(arch)
    return found


def probe_tools(arches):
    """({arch name: tools}, {arch name: why it is skipped}). A known-absent
    tool skips that architecture alone; a tool whose presence cannot be
    determined raises Unknown, which fails the suite whatever the others hold."""
    found = {}
    skipped = {}
    for arch in arches:
        try:
            found[arch["name"]] = probe_arch(arch)
        except Absent as e:
            skipped[arch["name"]] = str(e)
    return found, skipped


def record_clang(arch):
    """The clang the target's record beside the stages names, which sawc
    compiles its `.ll` with."""
    path = build.runtime_manifest(arch["triple"])
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for line in fh:
            key, _, value = line.strip().partition(" ")
            if key == "clang":
                return value
    return None


# =============================================================================
# Building and running
# =============================================================================

def build_shared(arch, clang):
    """The boot stub and the C floor every image links, built once per arch."""
    out = build_dir(arch)
    os.makedirs(out, exist_ok=True)
    boot_o = os.path.join(out, "boot.o")
    support_o = os.path.join(out, "support.o")
    target = "--target=%s" % arch["triple"]
    checked([clang, target] + arch["cc_args"] + ["-nostdlib", "-c", os.path.join(HAL_DIR, arch["name"], "boot.S"),
                                                 "-o", boot_o])
    # -fno-builtin: support.c DEFINES memcpy, and without it LLVM may rewrite
    # its byte loop into a call to itself.
    floor = ["-ffreestanding", "-fno-builtin", "-ffunction-sections", "-fdata-sections", "-nostdlib", "-O2", "-c"]
    checked([clang, target] + arch["cc_args"] + floor + [SUPPORT_C, "-o", support_o])
    shared = {"all": [boot_o, support_o], "no_atomics": None}
    if arch["no_atomics"]:
        atomics_o = os.path.join(out, "atomics.o")
        checked([clang, target] + arch["no_atomics"]["cc_args"] + floor + [arch["no_atomics"]["support"],
                                                                          "-o", atomics_o])
        shared["no_atomics"] = atomics_o
    return shared


def nm_tool(clang):
    """The `nm` that reads the arch's objects: the LLVM one beside its clang,
    else one on PATH."""
    beside = os.path.join(os.path.dirname(clang), "llvm-nm")
    if os.path.exists(beside):
        return beside
    return shutil.which("llvm-nm") or "nm"


def references_problem(case, arch, obj, clang):
    """None when every symbol the object leaves undefined is a runtime seam,
    a symbol the HAL defines (`HAL_PREFIXES`), or one of `atomic_routines`,
    and it references exactly those atomic routines; else why
    (`undefined_problem`)."""
    code, out = run([nm_tool(clang), "-u", obj], PROBE_TIMEOUT_S)
    if code != 0:
        return "nm cannot read %s: %s" % (obj, out.strip()[:300])
    return undefined_problem(case, arch, {line.split()[-1] for line in out.splitlines() if line.strip()})


def undefined_problem(case, arch, found):
    """Why the symbols `found`, the ones a case object leaves undefined, are
    not exactly what the environment supplies, or None. A routine the object
    defines itself (the memory routines, the 64-bit integer helpers, the
    soft-float routines) is not undefined there, so a soft-float name among
    them is refused like any stray. A host library's name here is a call past
    the runtime ABI (SL-933)."""
    referenced = {name for name in found if name.startswith("__atomic_")}
    wanted = atomic_routines(case, arch)
    if referenced != wanted:
        return "the object references the atomic routines %s, not exactly %s" % (sorted(referenced), sorted(wanted))
    soft = sorted(name for name in found if SOFT_FLOAT_SHAPE.match(name))
    if soft:
        return ("the object references the soft-float routine(s) %s, which no environment supplies: the object "
                "defines the spec's soft-float routines itself (LANGUAGE_SPEC.md, Profiles)" % ", ".join(soft))
    stray = sorted(name for name in found - referenced if not name.startswith(HAL_PREFIXES))
    if stray:
        return ("the object references %s, which neither the runtime ABI (`__saw_rt_*`), the HAL (`fs_*`) nor "
                "the object itself defines" % ", ".join(stray))
    return None


def sawc_command(case, arch, obj):
    """The compile a case asks for: the flags are half of what is under test."""
    cmd = [build.SAWC, "build", os.path.join(CASES_DIR, case.get("source", case["name"]) + ".saw"), "-o", obj,
           "--freestanding", "--target", arch["triple"]]
    if case.get("no_hidden_alloc", True):
        cmd.append("--no-hidden-alloc")
    if case.get("runtime", True):
        cmd.append("--runtime")
    features = arch["no_atomics"]["features"] if case.get("no_atomics") else arch["features"]
    if features:
        cmd += ["--target-features", features]
    if case.get("modules", True):
        for name in sorted(MODULES):
            cmd += ["--module-path", "%s=%s" % (name, MODULES[name])]
    extra = case.get("extra_flags", [])
    if not any(flag.startswith("-O") for flag in extra):
        cmd.append(SUITE_LEVEL)
    return cmd + extra


def in_order(output, wanted, what):
    """None when `output` holds each of `wanted` in order, else the reason."""
    cursor = 0
    for want in wanted:
        at = output.find(want, cursor)
        if at < 0:
            where = "out of order" if want in output else "missing"
            return "%s expected %s %r (got %r)" % (where, what, want, output)
        cursor = at + len(want)
    return None


def check_refusal(case, arch):
    obj = os.path.join(build_dir(arch), case["name"] + ".o")
    code, out = run(sawc_command(case, arch, obj), BUILD_TIMEOUT_S)
    if code == 0:
        return "expected the compile to be REFUSED, but it succeeded"
    if code is None:
        return "the compile timed out after %ds" % BUILD_TIMEOUT_S
    errors = [line for line in out.splitlines() if line.startswith("ERROR\t")]
    if len(errors) != 1:
        return "expected exactly one diagnostic, got %d (%r)" % (len(errors), out)
    return in_order(out, case["expect_compile_error"], "diagnostic")


def check_link_refusal(case, arch, shared, lld):
    out_dir = build_dir(arch)
    obj = os.path.join(out_dir, case["name"] + ".o")
    second = os.path.join(out_dir, case["second_object"] + ".o")
    elf = os.path.join(out_dir, case["name"] + ".elf")
    for stale in (obj, second, elf):
        if os.path.exists(stale):
            os.remove(stale)
    plain = {"name": case["second_object"], "runtime": False, "modules": False}
    try:
        checked(sawc_command(case, arch, obj))
        checked(sawc_command(plain, arch, second))
    except ToolError as e:
        return "build error\n%s" % e
    code, out = run([lld, "-T", os.path.join(HAL_DIR, arch["name"], "link.ld"), "--gc-sections", "-o", elf]
                    + shared["all"] + [obj, second], BUILD_TIMEOUT_S)
    if code == 0:
        return "expected the link to be REFUSED, but it succeeded"
    if code is None:
        return "the link timed out after %ds" % BUILD_TIMEOUT_S
    return in_order(out, case["expect_link_error"], "link error")


def build_with_blade(case, arch, lld, clang):
    """Build the case's package for the arch's triple through Blade, which is
    itself built by sawc. Returns the ELF's path; raises ToolError."""
    package = os.path.join(FS_DIR, case["package"])
    target_dir = os.path.join(package, ".build", arch["triple"])
    elf = os.path.join(target_dir, case["image"] + ".elf")
    # Blade skips a target whose outputs are current, so a stale ELF must go
    # with everything else it left.
    shutil.rmtree(target_dir, ignore_errors=True)
    try:
        blade = blade_lane.ensure_blade()
    except RuntimeError as e:
        raise ToolError(str(e))
    # Blade's emitter reads the toolchain from these two, defaulting to whatever
    # `clang` is first on PATH, which on macOS cannot drive the riscv assembler.
    env = blade_lane.blade_environment({"SOS_CLANG": clang, "SOS_LD": lld})
    code, out = blade_lane.run([blade, "build", "--target", arch["triple"]], BUILD_TIMEOUT_S,
                               cwd=package, env=env)
    if code != 0:
        why = "timed out after %ds" % BUILD_TIMEOUT_S if code is None else "exit %d" % code
        raise ToolError("command failed (%s): blade build --target %s\n%s" % (why, arch["triple"], out))
    if not os.path.exists(elf):
        raise ToolError("blade build --target %s left no %s\n%s" % (arch["triple"], elf, out))
    return elf


FLASH_BYTES = 4 * 1024 * 1024
# What the ROM looks for at flash offsets 0x400 and 0x404 before it enters
# the image at 0x408; the boot stub's `.magic` section holds it.
FLASH_MAGIC = b"\x1d\x04\xdb\xae" * 2
FLASH_MAGIC_OFFSET = 0x400
ELF_PT_LOAD = 1


def flash_image(elf, arch, path):
    """Write the flash image the ESP32-S3's ROM boots to `path`: 4 MiB of
    0xFF with each `PT_LOAD` segment of the 32-bit little-endian `elf` at its
    load address minus the arch's `flash_base`. A segment loading outside the
    flash window, or an image without the ROM's magic words, raises ToolError
    naming what is wrong. An image whose first byte is 0xE9 would read as an
    esptool header, so that is refused too."""
    base = arch["flash_base"]
    with open(elf, "rb") as fh:
        data = fh.read()
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ToolError("%s is not a 32-bit little-endian ELF" % elf)
    phoff, = struct.unpack_from("<I", data, 28)
    phentsize, phnum = struct.unpack_from("<HH", data, 42)
    image = bytearray(b"\xff" * FLASH_BYTES)
    for i in range(phnum):
        p_type, offset, vaddr, paddr, filesz, _memsz, _flags, _align = struct.unpack_from(
            "<8I", data, phoff + phentsize * i)
        if p_type != ELF_PT_LOAD or filesz == 0:
            continue
        if not (base <= paddr and paddr + filesz <= base + FLASH_BYTES):
            raise ToolError("segment %d of %s loads %d bytes at %#x (virtual %#x), outside the flash window "
                            "%#x..%#x" % (i, elf, filesz, paddr, vaddr, base, base + FLASH_BYTES))
        image[paddr - base:paddr - base + filesz] = data[offset:offset + filesz]
    if bytes(image[FLASH_MAGIC_OFFSET:FLASH_MAGIC_OFFSET + 8]) != FLASH_MAGIC:
        raise ToolError("%s loads nothing at flash offset %#x, where the ROM looks for its magic words"
                        % (elf, FLASH_MAGIC_OFFSET))
    if image[0] == 0xE9:
        raise ToolError("%s puts 0xE9 at flash offset 0, which the ROM reads as an esptool header" % elf)
    with open(path, "wb") as fh:
        fh.write(image)


def boot_arguments(arch, elf):
    """The QEMU arguments that boot the linked `elf`: the ELF itself, or the
    flash image built from it. Raises ToolError."""
    if arch["boot"] == "kernel":
        return ["-kernel", elf]
    image = os.path.splitext(elf)[0] + ".flash.bin"
    flash_image(elf, arch, image)
    return ["-drive", "file=%s,if=mtd,format=raw" % image]


def check_run(case, arch, shared, tools):
    lld, qemu, clang = tools["lld"], tools["qemu"], tools["clang"]
    out_dir = build_dir(arch)
    obj = os.path.join(out_dir, case["name"] + ".o")
    elf = os.path.join(out_dir, case["name"] + ".elf")
    for stale in (obj, elf):
        if os.path.exists(stale):
            os.remove(stale)
    objects = list(shared["all"])
    if case.get("no_atomics"):
        objects.append(shared["no_atomics"])
    try:
        if case.get("blade"):
            elf = build_with_blade(case, arch, lld, clang)
        else:
            checked(sawc_command(case, arch, obj))
            problem = references_problem(case, arch, obj, clang)
            if problem:
                return problem
            checked([lld, "-T", os.path.join(HAL_DIR, arch["name"], "link.ld"), "--gc-sections", "-o", elf]
                    + objects + [obj])
    except ToolError as e:
        return "build error\n%s" % e
    try:
        booting = boot_arguments(arch, elf)
    except ToolError as e:
        return "build error\n%s" % e
    status, out = run([qemu] + arch["qemu_args"] + ["-nographic"] + booting, QEMU_TIMEOUT_S)
    if status is None:
        return "QEMU hung (> %ds), no exit through the exit device\n%s" % (QEMU_TIMEOUT_S, out)
    fmt = expectations(arch)
    problem = in_order(out, [want.format(**fmt) for want in case["expect_out"]], "output")
    if problem:
        return problem
    if case["expect_clean_exit"] and status != 0:
        return "expected a clean exit (0), got status %d\n%s" % (status, out)
    if not case["expect_clean_exit"] and status == 0:
        return "expected a failing (non-zero) exit, got 0\n%s" % out
    want = case.get("expect_status")
    if want is not None and status != want:
        return "expected exit status %d, got %d\n%s" % (want, status, out)
    return None


def case_due(case, arch):
    """The gap a case's run on `arch` is due on, or None: its `due`, on the
    arches `due_on` names, or on every arch when it names none."""
    if not case.get("due"):
        return None
    if arch["name"] not in case.get("due_on", (arch["name"],)):
        return None
    return case["due"]


def run_arch(arch, cases, tools):
    """(passed, failed, due) for one architecture, each case printed."""
    lld = tools["lld"]
    print("%s  (%s, %s `%s`)" % (arch["name"], arch["triple"], os.path.basename(tools["qemu"]), arch["machine"]),
          flush=True)
    try:
        shared = build_shared(arch, tools["clang"])
    except ToolError as e:
        print("FAIL: the %s boot stub or C floor does not build\n%s" % (arch["name"], e))
        return 0, len(cases), 0

    def one(case):
        if case.get("expect_compile_error"):
            return check_refusal(case, arch)
        if case.get("expect_link_error"):
            return check_link_refusal(case, arch, shared, lld)
        return check_run(case, arch, shared, tools)

    problems = gate_jobs.map_ordered(one, cases)
    passed = failed = due = 0
    for i, (case, problem) in enumerate(zip(cases, problems), 1):
        marker = "[%d/%d]" % (i, len(cases))
        owed = case_due(case, arch)
        if owed and problem and case["due_shows"] not in problem:
            print("%s FAIL  %s  (due: %s, but it fails without saying %r)"
                  % (marker, case["name"], owed, case["due_shows"]))
            for line in problem.splitlines():
                print("    " + line)
            failed += 1
        elif owed and problem:
            print("%s due   %s  (%s)" % (marker, case["name"], owed))
            due += 1
        elif owed:
            print("%s FAIL  %s  (it passes, so its `due` marker is stale; remove it: %s)"
                  % (marker, case["name"], owed))
            failed += 1
        elif problem is None:
            print("%s ok    %s" % (marker, case["name"]))
            passed += 1
        else:
            print("%s FAIL  %s" % (marker, case["name"]))
            for line in problem.splitlines():
                print("    " + line)
            failed += 1
    print()
    return passed, failed, due


def main(argv):
    # Every case's build shares the run's sawc cache, never the user's.
    patch_gate.gate_cache()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arch", metavar="NAME", help="run one architecture (default: every one not off)")
    ap.add_argument("--tools", action="store_true", help="decide the prerequisites, print the decision, run nothing")
    ap.add_argument("cases", nargs="*", metavar="CASE", help="run only these cases")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    child_groups.install()

    arches = [a for a in ARCHES if not a["off"]]
    if args.arch:
        named = [a for a in ARCHES if a["name"] == args.arch]
        if not named:
            print("freestanding: unknown --arch %r; known: %s" % (args.arch, ", ".join(a["name"] for a in ARCHES)))
            return 2
        if named[0]["off"]:
            print("freestanding: --arch %s is off: %s" % (args.arch, named[0]["off"]))
            return 2
        arches = named
    known = set(c["name"] for c in TEST_CASES)
    unknown = [c for c in args.cases if c not in known]
    if unknown:
        print("freestanding: unknown case(s) %s" % ", ".join(unknown))
        return 2

    problems = arch_free_problems()
    if problems:
        print("freestanding: FAIL: architecture names in a shared module (fsrt/fscore/fsdata compile unchanged "
              "for every target; a machine name belongs in tests/freestanding/hal/):")
        for line in problems:
            print("  " + line)
        return 1

    try:
        tools, skipped = probe_tools(arches)
    except Unknown as e:
        print("freestanding: FAIL: %s" % e)
        return EXIT_UNKNOWN
    for name, why in skipped.items():
        print("freestanding: SKIPPED %s: %s" % (name, why))
    arches = [a for a in arches if a["name"] in tools]
    if not arches:
        print("freestanding: SKIPPED, not failed: no architecture has its tools")
        return 0
    for arch in arches:
        found = tools[arch["name"]]
        print("freestanding: %s: %s, %s, %s" % (arch["name"], found["qemu"], found["lld"], found["clang"]))
    skipped_note = "%d ran, %d skipped" % (len(arches), len(skipped))
    if skipped:
        skipped_note += " (%s)" % ", ".join(skipped)
    if args.tools:
        print("freestanding: every prerequisite is present" if not skipped
              else "freestanding: %s" % skipped_note)
        return 0

    ok, output = (True, "") if build.handed_down() else build.build_sawc()
    if not ok:
        print("%s\nfreestanding: FAIL: sawc does not build" % output)
        return 1
    build.configure_bare_metal_targets()
    for arch in arches:
        named = record_clang(arch)
        if named != tools[arch["name"]]["clang"]:
            print("freestanding: FAIL: sawc's record for %s names clang %s, and build.choose_clang picks %s"
                  % (arch["triple"], named, tools[arch["name"]]["clang"]))
            return 1

    passed = failed = due = 0
    for arch in arches:
        cases = [c for c in TEST_CASES if arch["name"] in c.get("arches", (arch["name"],))
                 and (not args.cases or c["name"] in args.cases)]
        p, f, d = run_arch(arch, cases, tools[arch["name"]])
        passed, failed, due = passed + p, failed + f, due + d
    off = ["%s (%s)" % (a["name"], a["off"]) for a in ARCHES if a["off"] and a not in arches]
    note = "%d passed, %d failed, %d due; architectures: %s" % (passed, failed, due, skipped_note)
    if off:
        note += "; off: " + "; ".join(off)
    if failed:
        print("freestanding: FAIL: %s" % note)
        return 1
    print("freestanding: ok: %s" % note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

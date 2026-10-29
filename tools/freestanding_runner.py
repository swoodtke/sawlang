#!/usr/bin/env python3
"""The freestanding QEMU suite: sawc's freestanding output, built and run.

    tools/freestanding_runner.py [--arch NAME] [CASE...]
    tools/freestanding_runner.py --tools     # the tool decision alone

Each RUN case is compiled by sawc (`--freestanding --runtime
--no-hidden-alloc --target T`, with the suite's three modules through
`--module-path`), linked by ld.lld with a boot stub and a C floor at a fixed
address, booted under QEMU, and judged by its console transcript and exit
status. A REFUSAL case stops at the compile and is judged by sawc's
diagnostic. A case marked `due` is blocked by a sawc gap and cites the issue
that owns it; it must fail, and passing fails the run so the marker comes off.

QEMU, ld.lld and a clang that compiles for the target are host prerequisites.
The suite SKIPS, and passes, when one is known absent: not on PATH, or no clang
`build.pick_clang` would choose. It FAILS when presence cannot be determined:
no PATH at all, a tool that is found but does not answer `--version`, or a
`SAWC_CLANG` that names no usable clang (tools/test_freestanding_runner.py).

The suite lock is not taken here: the battery and the patch gate run this
inside the lock their caller already holds.
"""

import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build  # noqa: E402
import child_groups  # noqa: E402
import gate_jobs  # noqa: E402

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
# (`extra_flags`): the O1 pipeline the expectations were written against.
# `float_text` links at -O1 only because its float operations fold away; at
# sawc's default -O0, under aarch64's `-fp-armv8` default, it needs soft-float
# libcalls (`__subdf3`) that the support code does not provide yet (SL-929).
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

ARCHES = [
    {
        "name": "riscv32",
        "triple": "riscv32-unknown-none-elf",
        "qemu": "qemu-system-riscv32",
        # `-bios none`: no OpenSBI, the case IS the reset target.
        "qemu_args": ["-M", "virt", "-bios", "none"],
        # Without `+m` the Saw half is built for base rv32i and formatting an
        # integer emits `__divsi3` calls this link cannot satisfy. The C half
        # gets the same set through `-march`.
        "cc_args": ["-march=rv32imac_zicsr", "-mabi=ilp32"],
        "features": "+m,+a,+c",
        "word_bytes": 4,
        "load_base": 0x8000_0000,
        "off": "sawc builds no riscv32 object yet (SL-865 U6c)",
    },
    {
        "name": "arm64",
        "triple": "aarch64-unknown-none-elf",
        "qemu": "qemu-system-aarch64",
        # `-semihosting` is what makes SYS_EXIT carry a status code (see
        # hal/arm64/boot.S for why not PSCI); `gic-version=2` is pinned so a
        # newer emulator changing its default cannot swap the machine.
        "qemu_args": ["-M", "virt,gic-version=2", "-cpu", "cortex-a53", "-semihosting"],
        "cc_args": [],
        # None keeps sawc's freestanding default (`-neon,-fp-armv8`).
        "features": None,
        "word_bytes": 8,
        "load_base": 0x4000_0000,
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
    }


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
# a case that is ABOUT a level. `due` marks a case blocked by a sawc gap,
# citing the issue that owns the gap, and `due_shows` is the gap's own
# diagnostic: the case must fail saying it, so another failure is not hidden.
#
# The Blade case (`blade build --target T` over `tests/freestanding/bladepkg`)
# is not run: Blade is frozen in v0.18.0's language and sawc cannot build it
# until its port (SL-661).

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
        # `@align(N)` reaches the object at `-Oz`, on the arch and level where
        # an optimizer's repacking made a missing alignment a fault.
        "name": "align_attribute",
        "extra_flags": ["-Oz"],
        "arches": ["riscv32"],
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
        "due": "sawc's backend refuses an exported static (SL-884)",
        "due_shows": "an exported static is not in the backend slice yet",
        "expect_out": ["fs check bare_export_callable=1",
                       "fs check renamed_export_callable=1",
                       "fs check exported_static_readable=1",
                       "fs check coroutine_ran=1",
                       "fs done export_with_coroutine ok"],
        "expect_clean_exit": True,
    },
    # --- the linker script ----------------------------------------------------
    {
        # `@section` plus a fixed address: the OFFSET is the program's claim,
        # the ADDRESS the runner's, and the VALUE says the section was loaded.
        "name": "link_address",
        "due": "sawc's backend refuses `@section` (SL-875)",
        "due_shows": "`@section` is not in the backend slice yet",
        "expect_out": ["fs check fsmark_offset=1",
                       "fs value fsmark_address={mark_address}",
                       "fs check fsmark_value=1",
                       "fs check ordinary_static_below_fsmark=1",
                       "fs done link_address ok"],
        "expect_clean_exit": True,
    },
    {
        # A wider-than-word integer renders whole; riscv32 only, since on arm64
        # the word already is 64 bits.
        "name": "wide_value_rendering",
        "arches": ["riscv32"],
        "expect_out": ["fs value signed=20014547621496",
                       "fs value unsigned=20014547621496",
                       "fs value negative=-20014547621496",
                       "fs value max=18446744073709551615",
                       "fs done wide_value_rendering ok"],
        "expect_clean_exit": True,
    },
]

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


def find_tool(name):
    """The absolute path of `name`, which answers `--version`."""
    if os.environ.get("PATH") is None:
        raise Unknown("PATH is not set, so whether %s is installed is unknown" % name)
    path = shutil.which(name)
    if path is None:
        raise Absent("%s is not on PATH (%s)" % (name, INSTALL_HINTS.get(name, "install it")))
    code, out = run([path, "--version"], PROBE_TIMEOUT_S)
    if code != 0:
        why = "timed out" if code is None else "exited %d" % code
        raise Unknown("%s is on PATH but `%s --version` %s, so whether it runs is unknown: %s"
                      % (name, path, why, out.strip()[:300] or "no output"))
    return path


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
        raise Absent("no clang compiles for %s (%s): %s" % (arch["triple"], INSTALL_HINTS["clang"], why))
    return clang


def probe_tools(arches):
    """{arch name: (qemu, clang)} and ld.lld, or Absent/Unknown."""
    lld = find_tool("ld.lld")
    found = {}
    for arch in arches:
        found[arch["name"]] = (find_tool(arch["qemu"]), find_clang(arch))
    return found, lld


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
    checked([clang, target] + arch["cc_args"] + ["-ffreestanding", "-fno-builtin", "-ffunction-sections",
                                                 "-fdata-sections", "-nostdlib", "-O2", "-c", SUPPORT_C,
                                                 "-o", support_o])
    return [boot_o, support_o]


def sawc_command(case, arch, obj):
    """The compile a case asks for: the flags are half of what is under test."""
    cmd = [build.SAWC, "build", os.path.join(CASES_DIR, case["name"] + ".saw"), "-o", obj,
           "--freestanding", "--no-hidden-alloc", "--target", arch["triple"]]
    if case.get("runtime", True):
        cmd.append("--runtime")
    if arch["features"]:
        cmd += ["--target-features", arch["features"]]
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


def check_run(case, arch, shared, lld, qemu):
    out_dir = build_dir(arch)
    obj = os.path.join(out_dir, case["name"] + ".o")
    elf = os.path.join(out_dir, case["name"] + ".elf")
    for stale in (obj, elf):
        if os.path.exists(stale):
            os.remove(stale)
    try:
        checked(sawc_command(case, arch, obj))
        checked([lld, "-T", os.path.join(HAL_DIR, arch["name"], "link.ld"), "--gc-sections", "-o", elf]
                + shared + [obj])
    except ToolError as e:
        return "build error\n%s" % e
    status, out = run([qemu] + arch["qemu_args"] + ["-nographic", "-kernel", elf], QEMU_TIMEOUT_S)
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


def run_arch(arch, cases, qemu, clang, lld):
    """(passed, failed, due) for one architecture, each case printed."""
    print("%s  (%s, %s `virt`)" % (arch["name"], arch["triple"], os.path.basename(qemu)), flush=True)
    try:
        shared = build_shared(arch, clang)
    except ToolError as e:
        print("FAIL: the %s boot stub or C floor does not build\n%s" % (arch["name"], e))
        return 0, len(cases), 0

    def one(case):
        if case.get("expect_compile_error"):
            return check_refusal(case, arch)
        return check_run(case, arch, shared, lld, qemu)

    problems = gate_jobs.map_ordered(one, cases)
    passed = failed = due = 0
    for i, (case, problem) in enumerate(zip(cases, problems), 1):
        marker = "[%d/%d]" % (i, len(cases))
        if case.get("due") and problem and case["due_shows"] not in problem:
            print("%s FAIL  %s  (due: %s, but it fails without saying %r)"
                  % (marker, case["name"], case["due"], case["due_shows"]))
            for line in problem.splitlines():
                print("    " + line)
            failed += 1
        elif case.get("due") and problem:
            print("%s due   %s  (%s)" % (marker, case["name"], case["due"]))
            due += 1
        elif case.get("due"):
            print("%s FAIL  %s  (it passes, so its `due` marker is stale; remove it: %s)"
                  % (marker, case["name"], case["due"]))
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
        tools, lld = probe_tools(arches)
    except Absent as e:
        print("freestanding: SKIPPED, not failed: %s" % e)
        return 0
    except Unknown as e:
        print("freestanding: FAIL: %s" % e)
        return EXIT_UNKNOWN
    for arch in arches:
        qemu, clang = tools[arch["name"]]
        print("freestanding: %s: %s, %s, %s" % (arch["name"], qemu, lld, clang))
    if args.tools:
        print("freestanding: every prerequisite is present")
        return 0

    ok, output = (True, "") if build.handed_down() else build.build_sawc()
    if not ok:
        print("%s\nfreestanding: FAIL: sawc does not build" % output)
        return 1
    build.configure_bare_metal_targets()
    for arch in arches:
        named = record_clang(arch)
        if named != tools[arch["name"]][1]:
            print("freestanding: FAIL: sawc's record for %s names clang %s, and build.choose_clang picks %s"
                  % (arch["triple"], named, tools[arch["name"]][1]))
            return 1

    passed = failed = due = 0
    for arch in arches:
        cases = [c for c in TEST_CASES if arch["name"] in c.get("arches", (arch["name"],))
                 and (not args.cases or c["name"] in args.cases)]
        qemu, clang = tools[arch["name"]]
        p, f, d = run_arch(arch, cases, qemu, clang, lld)
        passed, failed, due = passed + p, failed + f, due + d
    off = ["%s (%s)" % (a["name"], a["off"]) for a in ARCHES if a["off"] and a not in arches]
    note = "%d passed, %d failed, %d due" % (passed, failed, due)
    if off:
        note += "; off: " + "; ".join(off)
    if failed:
        print("freestanding: FAIL: %s" % note)
        return 1
    print("freestanding: ok: %s" % note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

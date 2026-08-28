#!/usr/bin/env python3
"""The freestanding QEMU suite (design 238 unit 1).

WHAT THIS REPLACES, AND WHY IT IS NOT `sos_runner`. `tools/sos_runner.py` is
the compiler's freestanding gate today: it is the only exercise the codegen has
that is `--freestanding`, `--no-hidden-alloc`, cross-architecture and
user-mode-crossing. It is also a SYSTEM test doing a UNIT gate's job — when it
goes red it says "the OS did not boot", not "the `--no-hidden-alloc` check
regressed on enum init" — and design 238 moves `sos/` to its own repository,
which would take that coverage with it.

So the features are named DIRECTLY here, one or more cases each, over the
inventory design 238 ratified:

  * `--freestanding` codegen: no host runtime, no libc, nothing linked but the
    case, three Saw modules and an assembly stub
  * `--no-hidden-alloc`: the refusal surface per construct, plus a green
    control — three rows that must NOT compile and one that must
  * `--runtime-provider`: a package supplying the four frozen `__saw_rt_*`
    seams, signature-checked against `sawc/rt/ABI.md`, reached through BOTH of
    the flag's doors (this runner's command line, and `[package] runtime =
    true` in a Blade manifest) — plus the two refusals
  * cross-target codegen from a 64-bit host: platform-width `Int`, pointer
    size, struct layout, calling convention, 64-bit values on a 32-bit target
  * linking at a fixed load address with a custom linker script
  * `--module-path` composition — the kcore/imgformat/sosrt shape in miniature
  * Blade's non-host target path: `blade build --target <triple>`

IT RUNS, IT DOES NOT MERELY LINK. A suite that compiled and linked freestanding
riscv32 would prove the compiler emitted something, not that the something is
correct: calling convention, struct layout and trap bugs all survive a clean
link. Every non-refusal case boots under QEMU, prints, and stops through the
board's exit device with an asserted status.

THE ENGINE IS COPIED FROM `sos_runner`, NOT SHARED — the ARCHES table, the tool
probe, `_run_qemu`, the ordered transcript matcher, the architecture-name scan.
Design 238 makes the same call for the boot stubs and for sawos's own harness,
and for the same reason: the two diverge immediately (this one grows feature
rows, that one grows sosimg stitching), and a shared engine across two repos
with no package relation between them would be a distribution problem invented
to avoid a couple of hundred lines. `sos_runner.py` is untouched by this unit.

Pipeline per RUN case, per architecture:
  1. sawc   : cases/<name>.saw -> <name>.o  (--freestanding --no-hidden-alloc
              --runtime-provider --target <triple>, --module-path fsrt= fscore=
              fsdata=)
  2. clang  : hal/<arch>/boot.S -> boot.o   (assembled once per architecture)
     clang  : hal/support.c     -> support.o (mem* + the 64-bit division
              libcalls — the C that must stay C, compiled once)
  3. ld.lld : link with hal/<arch>/link.ld --gc-sections -> <name>.elf
  4. qemu   : run with a hard timeout; capture console stdout + exit status

A REFUSAL case stops at step 1 and asserts the diagnostic. The BLADE case
replaces steps 1-3 with one `blade build --target <triple>` and boots the ELF
Blade produced on its way to a `.sosimg`.

QEMU / ld.lld / clang are HOST PREREQUISITES (like the Python venv), not
Blade-managed; the harness probes for them up front and fails with an install
hint.

THE SUITE LOCK IS NOT TAKEN HERE, deliberately. It is an agent protocol in
CLAUDE.md rather than a harness feature — `test_runner.py`, `sos_runner.py` and
the Makefile implement nothing of it — and a runner that acquired it would
DEADLOCK the ordinary case, where an agent already holds the lock around
`tools/battery.sh` and the battery then runs this stage inside it.

`--arch <name>` runs one architecture, for development. The GATE is both.
"""

import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO_ROOT, "sawc", "sawc.py")

FS_DIR = os.path.join(REPO_ROOT, "tests", "freestanding")
CASES_DIR = os.path.join(FS_DIR, "cases")
HAL_DIR = os.path.join(FS_DIR, "hal")
SUPPORT_C = os.path.join(HAL_DIR, "support.c")
BLADE_PKG = os.path.join(FS_DIR, "bladepkg")

# The three modules every case composes, reached the way a kernel reaches
# `kcore`/`imgformat`/`sosrt` — through `--module-path`, from a directory.
MODULES = {
    "fsrt": os.path.join(FS_DIR, "rt", "src"),
    "fscore": os.path.join(FS_DIR, "core", "src"),
    "fsdata": os.path.join(FS_DIR, "data", "src"),
}

# Blade is BUILT here with the in-tree compiler, exactly as `sos_runner` builds
# it, because the Blade case needs a Blade to drive.
BLADE_DIR = os.path.join(REPO_ROOT, "blade")
TOML_SRC = os.path.join(REPO_ROOT, "libs", "toml", "src")
SEMVER_SRC = os.path.join(REPO_ROOT, "libs", "semver", "src")
# `imgformat` is a Blade dependency, and since design 238 unit 2 (D-a) it lives
# in `libs/` beside toml and semver rather than under `sos/` — so this harness
# builds Blade with no SOS tree present, which is the state after unit 5.
IMGFORMAT_SRC = os.path.join(REPO_ROOT, "libs", "imgformat", "src")

QEMU_TIMEOUT_S = 20

# =============================================================================
# The architectures
# =============================================================================
#
# One entry per machine the suite targets — the same two `sos_runner` targets,
# because the pair is the point: a 32-bit target driven from a 64-bit host is
# the live cross-codegen hazard, and one of each is what makes a width
# disagreement visible.
#
# Everything that differs between them is HERE, in data. `word_bytes`,
# `int_max` and `mark_address` are what the per-architecture expectations are
# written against: a case's source is shared, so a target-dependent number is
# printed by the program and matched here rather than asserted there.

ARCHES = [
    {
        "name": "riscv32",
        "triple": "riscv32-unknown-none-elf",
        "qemu": "qemu-system-riscv32",
        # `-bios none`: no OpenSBI, the case IS the reset target.
        "qemu_args": ["-M", "virt", "-bios", "none"],
        # A triple names the architecture but not which optional extensions the
        # part has: without `+m` the Saw half is built for base rv32i and
        # formatting an integer emits `__divsi3` calls this link cannot satisfy.
        # The C half gets the same set through `-march`.
        "cc_args": ["-march=rv32imac_zicsr", "-mabi=ilp32"],
        "features": "+m,+a,+c",
        "word_bytes": 4,
        "load_base": 0x8000_0000,
    },
    {
        "name": "arm64",
        "triple": "aarch64-unknown-none-elf",
        "qemu": "qemu-system-aarch64",
        # `-cpu cortex-a53`: ubiquitous, EL1 well-exercised. `-semihosting` is
        # what makes SYS_EXIT carry a status code — see hal/arm64/boot.S for why
        # not PSCI. `gic-version=2` is pinned rather than defaulted so a newer
        # emulator changing its default cannot swap the machine underneath.
        "qemu_args": ["-M", "virt,gic-version=2", "-cpu", "cortex-a53",
                      "-semihosting"],
        # The base aarch64 triple already has everything these cases use, and
        # there is no ABI variant to select.
        "cc_args": [],
        "features": None,
        "word_bytes": 8,
        "load_base": 0x4000_0000,
    },
]

# The offset `hal/<arch>/link.ld` places `.fsmark` at. One number, two scripts,
# and `cases/link_address.saw` reads the resulting ADDRESS back — so this is the
# harness's half of a claim the program makes.
#
# It was 64 KiB until design 253's `float_text` case, whose image is ~118 KiB
# (std's float formatter carries two power-of-five tables and pulls the String
# layer in). The overlap was a clean LINK error naming both sections, which is
# what a fixed placement is supposed to do; the number moved rather than the
# case shrinking to fit a bound that was only ever "big enough so far".
FSMARK_OFFSET = 0x8_0000


def arch_dirs(arch):
    """The per-architecture directories a build reaches into."""
    return {
        "hal": os.path.join(HAL_DIR, arch["name"]),
        "build": os.path.join(REPO_ROOT, ".build", arch["triple"], "freestanding"),
    }


def expectations(arch):
    """The per-architecture substitutions a case's expected output is written in.

    A case says `sizeof_int={word}`, not `sizeof_int=4`, because the FACT under
    test is "the compiler used the TARGET's word size" and the digit is the
    target's. Same for the platform integer bound and for the address a linker
    script placed a section at.
    """
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
# The suite's Saw modules are arch-free by construction — one `fsrt`, one
# `fscore`, one `fsdata`, compiled unchanged for both targets — and the whole
# `--module-path` claim rests on that. An architecture name in one of them would
# still COMPILE, and would only be wrong on the profile nobody happened to be
# building, so the check that keeps the seam honest has to be mechanical.
# Comments count: a note that says `mepc` is a note that will be wrong on the
# profile that has no `mepc`. (Design 162 unit 1 makes the same check for
# `sos/kernel/core`; this is the miniature's copy of it.)

ARCH_FREE_DIRS = [MODULES["fsrt"], MODULES["fscore"], MODULES["fsdata"]]

# Deliberately shorter than `sos_runner`'s: that list grew with a kernel's
# vocabulary (interrupt controllers, timers, page-table registers), and none of
# it is reachable from three modules that print and add. What is here is the
# names a case author would plausibly reach for.
ARCH_WORDS = [
    "riscv", "rv32", "rv64", "aarch64", "arm64", "armv8",
    "mcause", "mepc", "mstatus", "mtvec", "mscratch", "ecall", "pmp",
    "ns16550", "pl011", "sifive", "semihost", "csr", "m-mode", "u-mode",
    "esr_el", "elr_el", "vbar", "ttbr", "sctlr", "tcr_el", "mair",
    "el0", "el1",
]


# A token that is BURIED IN A LONGER ENGLISH WORD is not a leak. THE RULE: a hit
# is suppressed only when the token has a letter on BOTH sides. That is
# deliberately weaker than a word boundary, because the real usages are prefixes
# and suffixes of longer identifiers — `csrw`, `PMP_BASE`, `sctlr_el1` — and
# requiring a boundary on both sides would miss every one of them. An arch token
# in the MIDDLE of an otherwise-alphabetic word is English; at either END of one
# it is an identifier.
def _is_english_embedding(line, token, at):
    before = line[at - 1] if at > 0 else ""
    after_index = at + len(token)
    after = line[after_index] if after_index < len(line) else ""
    return before.isalpha() and after.isalpha()


# ANSI colors (matched to test_runner.py's style; disabled when not a TTY).
_TTY = sys.stdout.isatty()
GREEN = "\033[92m" if _TTY else ""
RED = "\033[91m" if _TTY else ""
YELLOW = "\033[93m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
RESET = "\033[0m" if _TTY else ""
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"
XMARK = f"{YELLOW}x{RESET}"

# =============================================================================
# The cases
# =============================================================================
#
# Each RUN case: the entry source, one or more expected console substrings
# matched IN ORDER, and whether the emulator should exit cleanly (True → status
# 0) or fail (False). Expected strings are `str.format`ed with
# `expectations(arch)`.
#
# Each REFUSAL case carries `expect_compile_error` instead: the compile must
# FAIL, its diagnostic must contain the listed substrings in order, and the case
# never runs. `runtime_provider: False` withholds the flag and `modules: False`
# withholds the `--module-path` arguments, which is how the two runtime-provider
# refusals isolate the thing they are about.
#
# `arches` names the architectures a case applies to; the default is every one
# and stays that way — an arch list is a claim that the case is about something
# architecture-specific, or that it is blocked on one, and each says which in a
# comment beside it.
#
# `xfail` marks a case as a PIN of a filed finding, on `examples/`' terms: the
# reason MUST cite a DF number, the expectations state the INTENDED behavior,
# and an xfail case that PASSES fails the run so the marker cannot go stale.
#
# ONE NOTE ON WHAT THE CASES DELIBERATELY DO NOT DO: none of them divides or
# checked-multiplies a 64-bit value beyond what `hal/support.c` supplies
# libcalls for, because the rest reach compiler-rt entries a freestanding link
# does not carry. (`float_text` is the case that comes closest and is the one
# that now HOLDS that rule honest: std's float formatter divides `UInt64`s, and
# `__udivdi3` is supplied. If a future change to it reaches, say, `__muldi3`,
# this suite fails at the LINK rather than in the answer.) (The cases used to prefer `import fscore.*` / `import
# fscore.{…}` over the qualifier for a second reason — a module-qualified call
# carried neither its parameter's width nor its type arguments — which DF-238a
# closed on Aug 21. The mixed spellings stay: they exercise both.)

TEST_CASES = [
    {
        # The floor. If this is red nothing else here means anything.
        "name": "hello",
        "src": "hello.saw",
        "expect_out": ["fs: hello from freestanding Saw",
                       "fs check entered=1",
                       "fs done hello ok"],
        "expect_clean_exit": True,
    },
    # --- cross-target codegen -------------------------------------------------
    {
        # Platform-width `Int` and pointer size. The four `fs value` lines carry
        # the per-architecture expectation; every `fs check` below them is a
        # claim that holds on BOTH, so the two halves fail independently.
        "name": "int_widths",
        "src": "int_widths.saw",
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
        # Struct layout, asserted at RUN time through a typed view over bytes
        # written by hand — plus the aggregate-by-value ABI.
        "name": "struct_layout",
        "src": "struct_layout.saw",
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
        # The calling convention: twelve mixed-width arguments past the register
        # budget, negative narrow arguments, an aggregate return, and one
        # aggregate forwarded three frames by value.
        "name": "call_convention",
        "src": "call_convention.saw",
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
        # Three modules through `--module-path`, in a diamond: a `static` folded
        # across a module boundary into an array length, a method and a
        # raw-backed enum from a third module, and a generic monomorphized here
        # at a type declared elsewhere through a conformance declared in a third
        # place. The summary word is arithmetic over constants, so it is the
        # same number on both targets.
        "name": "module_compose",
        "src": "module_compose.saw",
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
        # Three of the four seams REACHED by a running program: write (every
        # line), alloc (the Vectors, which the source names) and dealloc (their
        # drop). The arena cursor is what turns "it did not crash" into "the
        # seam answered".
        "name": "runtime_seams",
        "src": "runtime_seams.saw",
        "expect_out": ["fs check arena_starts_empty=1",
                       "fs check vector_length=1",
                       "fs check vector_sum=1",
                       "fs check alloc_seam_answered=1",
                       "fs check second_vector_length=1",
                       "fs check alloc_seam_advanced=1",
                       "fs done runtime_seams ok"],
        "expect_clean_exit": True,
    },
    {
        # The fourth seam, which ends the machine — so it is its own case. The
        # STATUS is asserted as well as the message: on the riscv32 board a
        # failing exit that reached the finisher with a zero code would exit 0,
        # which is what the stub's promotion exists to stop.
        "name": "runtime_panic",
        "src": "runtime_panic.saw",
        "expect_out": ["fs check reached_panic_case=1",
                       "fs: about to panic",
                       "panic at runtime_panic.saw:",
                       "fs: deliberate panic"],
        "expect_clean_exit": False,
        "expect_status": 64,        # `fsrt`'s ExitCode.Panic
    },
    {
        # `--runtime-provider` refused: the same export, the flag withheld.
        "name": "runtime_export_ungated",
        "src": "runtime_export_ungated.saw",
        "runtime_provider": False,
        "modules": False,
        "expect_compile_error": ["`@export` symbol `__saw_rt_write` collides "
                                 "with a reserved runtime symbol"],
    },
    {
        # `--runtime-provider` granted, and the signature checked against the
        # frozen contract. Arity rather than width: a width mismatch that is
        # wrong on one of these targets can be RIGHT on the other.
        "name": "runtime_seam_signature",
        "src": "runtime_seam_signature.saw",
        "modules": False,
        "expect_compile_error": ["`@export` seam `__saw_rt_write` does not "
                                 "match the runtime ABI",
                                 "takes 1 parameter(s) where the ABI takes 2",
                                 "sawc/rt/ABI.md"],
    },
    # --- no hidden allocations ------------------------------------------------
    #
    # Three refusals and one green control. The control is not decoration: three
    # rows that must not compile are satisfied by a flag that rejects
    # everything, and the fourth is what says the flag discriminates.
    {
        "name": "hidden_alloc_interpolation",
        "src": "hidden_alloc_interpolation.saw",
        "expect_compile_error": ["string interpolation allocates a String",
                                 "--no-hidden-alloc"],
    },
    {
        "name": "hidden_alloc_escaping_closure",
        "src": "hidden_alloc_escaping_closure.saw",
        "expect_compile_error": ["an escaping closure heap-allocates its "
                                 "captured environment",
                                 "--no-hidden-alloc"],
    },
    {
        "name": "hidden_alloc_print_printable",
        "src": "hidden_alloc_print_printable.saw",
        "expect_compile_error": ["renders `Tag` through `to_string()`, which "
                                 "allocates a String",
                                 "--no-hidden-alloc"],
    },
    {
        "name": "format_no_alloc",
        "src": "format_no_alloc.saw",
        "expect_out": ["fs: n = 42",
                       "fs: 42 and 43",
                       "fs: text 7 true",
                       "fs check closure_captures_on_the_stack=1",
                       "fs check escaping_closure_without_captures=1",
                       "fs done format_no_alloc ok"],
        "expect_clean_exit": True,
    },
    {
        # Float TEXT with no libc (design 253). The profile used to refuse
        # `print(f)` and a `{}` float argument outright — the renderer was
        # snprintf — while leaving interpolation, `to_string()` and
        # `format(into:)` ungated on the same snprintf, so an object could
        # carry an undefined libc symbol. The formatter is Saw now, so the
        # refusal is gone and this is what stands in its place.
        #
        # It also holds the case list's 64-bit note honest at the one place
        # that reaches for it: the formatter divides `UInt64`s, and
        # `hal/support.c` supplies `__udivdi3`. A violation of that rule is a
        # link failure, not a wrong answer.
        "name": "float_text",
        "src": "float_text.saw",
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
    # --- the linker script ----------------------------------------------------
    {
        # `@section` + a fixed address. The OFFSET is a claim the program makes
        # (both scripts agree about it); the ADDRESS is one only the harness
        # knows; and the VALUE reading back is what says the section was LOADED
        # rather than merely placed.
        "name": "link_address",
        "src": "link_address.saw",
        "expect_out": ["fs check fsmark_offset=1",
                       "fs value fsmark_address={mark_address}",
                       "fs check fsmark_value=1",
                       "fs check ordinary_static_below_fsmark=1",
                       "fs done link_address ok"],
        "expect_clean_exit": True,
    },
    # --- Blade's non-host target path -----------------------------------------
    {
        # `blade build --target <triple>`: a path-dependency GRAPH resolved for
        # a non-host triple, `--runtime-provider` out of `[package] runtime =
        # true`, the cross clang over an assembly stub and a C floor named by
        # `[sos.<triple>] native`, `ld.lld` with that section's linker script,
        # and a `.sosimg` emitted from the ELF this runner then boots.
        "name": "blade_target",
        "blade_pkg": BLADE_PKG,
        "expect_out": ["fs: hello from a Blade-built image",
                       "fs check blade_built_image_ran=1",
                       "fs check blade_arithmetic=1",
                       "fs done blade_target ok"],
        "expect_clean_exit": True,
    },
    # --- pins -----------------------------------------------------------------
    {
        # riscv32 ONLY: the same source renders correctly on arm64, where the
        # platform word already is 64 bits, and a case marked xfail on a target
        # it passes on is a stale marker. DF-238b's XFAIL came off Aug 22 when
        # the wide formatter landed; the case stays as the regression test.
        "name": "wide_value_rendering",
        "src": "wide_value_rendering.saw",
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
    "qemu-system-riscv32": "brew install qemu   (macOS)  |  apt install qemu-system-misc   (Debian/Ubuntu)",
    "qemu-system-aarch64": "brew install qemu   (macOS)  |  apt install qemu-system-arm    (Debian/Ubuntu)",
    "ld.lld": "brew install lld    (macOS)  |  apt install lld                (Debian/Ubuntu)",
    "clang": "install Xcode/`brew install llvm` (macOS)  |  apt install clang  (Debian/Ubuntu)",
}


class ToolError(Exception):
    pass


def _run(cmd, **kw):
    """Run a build command, raising ToolError with captured output on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        out = (proc.stdout or "") + (proc.stderr or "")
        raise ToolError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{out}")
    return proc


def _find_clang(arches):
    """Return the first clang that can assemble EVERY target's boot code.

    macOS's Apple clang mis-drives the riscv integrated assembler, so a real
    LLVM clang (Homebrew `llvm`) is preferred there; on Linux CI plain `clang`
    (apt) works. `SOS_CLANG` overrides the search — the same variable
    `sos_runner` reads, because a developer who has set it for one suite means
    it for the other. The probe assembles each architecture's own `boot.S`,
    because "can target riscv32" and "can target aarch64" are separate questions
    and one harness needs both answered yes.
    """
    candidates = []
    if os.environ.get("SOS_CLANG"):
        candidates.append(os.environ["SOS_CLANG"])
    candidates += ["clang", "/opt/homebrew/opt/llvm/bin/clang",
                   "/usr/local/opt/llvm/bin/clang"]
    for cand in candidates:
        path = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if not path:
            continue
        ok = True
        for arch in arches:
            dirs = arch_dirs(arch)
            os.makedirs(dirs["build"], exist_ok=True)
            probe_src = os.path.join(dirs["hal"], "boot.S")
            try:
                _run([path, f"--target={arch['triple']}", *arch["cc_args"],
                      "-nostdlib", "-c", probe_src,
                      "-o", os.path.join(dirs["build"], "_probe.o")])
            except ToolError:
                ok = False
                break
        if ok:
            return path
    return None


def _probe_tools(arches):
    """Locate every qemu, ld.lld and a clang; print hints and exit on any miss."""
    missing = []

    qemus = {}
    for arch in arches:
        found = shutil.which(arch["qemu"])
        if not found:
            missing.append(arch["qemu"])
        qemus[arch["name"]] = found

    lld = shutil.which("ld.lld")
    if not lld:
        missing.append("ld.lld")
    clang = _find_clang(arches)
    if not clang:
        missing.append("clang")

    if missing:
        print(f"{RED}{BOLD}freestanding-test: missing host prerequisites{RESET}",
              file=sys.stderr)
        for tool in missing:
            print(f"  - {tool}: {INSTALL_HINTS[tool]}", file=sys.stderr)
        sys.exit(2)

    return qemus, lld, clang


def _sources_under(path):
    """Every `.saw` file at or under `path`."""
    if os.path.isfile(path):
        return [path]
    found = []
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            if name.endswith(".saw"):
                found.append(os.path.join(root, name))
    return found


def _check_arch_free():
    """Fail the run if an architecture name appears in a shared Saw module."""
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
                                rel = os.path.relpath(src, REPO_ROOT)
                                bad.append(f"{rel}:{lineno}: {word!r} in: "
                                           f"{line.strip()}")
                                break
                            at = low.find(word, at + 1)
    if bad:
        print(f"{RED}{BOLD}freestanding-test: architecture names in a shared "
              f"module{RESET}", file=sys.stderr)
        for line in bad:
            print(f"  {line}", file=sys.stderr)
        print("  (fsrt/fscore/fsdata compile unchanged for every target; a "
              "machine name belongs in tests/freestanding/hal/)", file=sys.stderr)
        return False
    return True


def _build_shared(arch, clang):
    """Build one architecture's native objects once; return them as a list.

    The boot stub (stack, console, exit device) plus the C floor every image
    links — `mem*` and the 64-bit division libcalls, the C that must stay C.
    """
    dirs = arch_dirs(arch)
    build = dirs["build"]
    os.makedirs(build, exist_ok=True)
    boot_o = os.path.join(build, "boot.o")
    support_o = os.path.join(build, "support.o")
    _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
          "-nostdlib", "-c", os.path.join(dirs["hal"], "boot.S"),
          "-o", boot_o])
    # -fno-builtin: support.c DEFINES memcpy, and without it LLVM may rewrite
    # its byte loop into a call to itself.
    _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
          "-ffreestanding", "-fno-builtin", "-ffunction-sections",
          "-fdata-sections", "-nostdlib", "-O2", "-c", SUPPORT_C,
          "-o", support_o])
    return [boot_o, support_o]


def _sawc_command(case, arch, obj):
    """The compile a case asks for — the flags ARE half of what is under test."""
    cmd = [sys.executable, SAWC, os.path.join(CASES_DIR, case["src"]),
           "-o", obj, "--freestanding", "--no-hidden-alloc",
           "--target", arch["triple"]]
    if case.get("runtime_provider", True):
        cmd.append("--runtime-provider")
    if arch["features"]:
        cmd += ["--target-features", arch["features"]]
    if case.get("modules", True):
        for name in sorted(MODULES):
            cmd += ["--module-path", f"{name}={MODULES[name]}"]
    return cmd


def _build_elf(case, arch, shared_objs, lld, clang):
    """Compile + link one RUN case for one architecture; return its ELF path."""
    dirs = arch_dirs(arch)
    os.makedirs(dirs["build"], exist_ok=True)
    name = case["name"]
    obj = os.path.join(dirs["build"], f"{name}.o")
    elf = os.path.join(dirs["build"], f"{name}.elf")
    _run(_sawc_command(case, arch, obj))
    _run([lld, "-T", os.path.join(dirs["hal"], "link.ld"), "--gc-sections",
          "-o", elf, *shared_objs, obj])
    return elf


def _check_refusal(case, arch):
    """Run a REFUSAL case's compile; return (ok, reason).

    The compile must FAIL and say the expected thing. A compile that SUCCEEDS is
    the interesting failure — it means the flag or the check the row is about
    stopped working — so it is reported as such rather than as a missing string.
    """
    dirs = arch_dirs(arch)
    os.makedirs(dirs["build"], exist_ok=True)
    obj = os.path.join(dirs["build"], f"{case['name']}.o")
    proc = subprocess.run(_sawc_command(case, arch, obj), capture_output=True,
                          text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return False, "expected the compile to be REFUSED, but it succeeded"
    cursor = 0
    for want in case["expect_compile_error"]:
        at = output.find(want, cursor)
        if at < 0:
            where = "out of order" if want in output else "missing"
            return False, (f"{where} expected diagnostic {want!r} "
                           f"(got {output!r})")
        cursor = at + len(want)
    return True, ""


def _run_qemu(qemu, arch, elf):
    """Run the ELF under QEMU with a hard timeout.

    Returns (exit_status, stdout, timed_out). A timeout is a hang — every case
    here reaches the exit device on every path, so nothing should ever park.
    """
    cmd = [qemu, *arch["qemu_args"], "-nographic", "-kernel", elf]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=QEMU_TIMEOUT_S)
        return proc.returncode, proc.stdout, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return None, out, True


def _check(case, arch, status, out, timed_out):
    """Return (ok, reason). Validates console output and exit expectations."""
    if timed_out:
        return False, f"QEMU hung (> {QEMU_TIMEOUT_S}s) — no clean exit"
    if isinstance(out, bytes):
        out = out.decode(errors="replace")
    expected = case["expect_out"]
    if expected is not None:
        if isinstance(expected, str):
            expected = [expected]
        fmt = expectations(arch)
        # Matched IN ORDER — each expectation starts where the previous one
        # ended. A console transcript is a sequence, and several of these cases
        # are asserting that one line comes AFTER another, which an unordered
        # `in` cannot see.
        cursor = 0
        for want in expected:
            want = want.format(**fmt)
            at = out.find(want, cursor)
            if at < 0:
                where = "out of order" if want in out else "missing"
                return False, (f"{where} expected output {want!r} "
                               f"(got {out!r})")
            cursor = at + len(want)
    if case["expect_clean_exit"]:
        if status != 0:
            return False, f"expected clean exit (0), got status {status}"
    else:
        if status == 0:
            return False, "expected a failing (non-zero) exit, got 0"
    want_status = case.get("expect_status")
    if want_status is not None and status != want_status:
        return False, f"expected exit status {want_status}, got {status}"
    return True, ""


def _build_blade(build_dir):
    """Build Blade once with the in-tree compiler; return the binary path.

    The `blade_bootstrap.py` stage0 step, reused: the Blade case is BUILT BY
    BLADE, so the harness needs a Blade to drive.
    """
    blade_bin = os.path.join(build_dir, "blade")
    _run([sys.executable, SAWC, os.path.join(BLADE_DIR, "src", "main.saw"),
          "-o", blade_bin,
          "--module-path", f"toml={TOML_SRC}",
          "--module-path", f"semver={SEMVER_SRC}",
          "--module-path", f"imgformat={IMGFORMAT_SRC}"])
    return blade_bin


def _blade_env(clang):
    env = dict(os.environ)
    env["SAWC"] = f"{sys.executable} {SAWC}"
    # macOS's Apple clang mis-drives the riscv integrated assembler; hand Blade
    # the same clang this harness probed for.
    env["SOS_CLANG"] = clang
    return env


def _build_blade_elf(blade_bin, pkg_dir, arch, clang):
    """`blade build --target <triple>` a package; return the ELF it linked.

    Always `--force`: the harness's job is to prove the CURRENT tree builds, and
    Blade's build avoidance keys on content it cannot see change here (the boot
    stub, the linker script's meaning).

    The `.sosimg` beside the ELF is checked for EXISTENCE and not booted. It is
    the emitter's own output and Blade's tests own its bytes; what this row
    needs from it is that the whole target path ran to the end rather than
    stopping after the link.
    """
    out_dir = os.path.join(pkg_dir, ".build", arch["triple"])

    # Delete first: a build that fails must not leave the PREVIOUS artifacts
    # lying around to be booted as if they were current.
    if os.path.isdir(out_dir):
        for stale in os.listdir(out_dir):
            if stale.endswith(".elf") or stale.endswith(".sosimg"):
                os.remove(os.path.join(out_dir, stale))

    _run([blade_bin, "build", "--force", "--target", arch["triple"]],
         cwd=pkg_dir, env=_blade_env(clang))

    elves = []
    images = []
    if os.path.isdir(out_dir):
        elves = [f for f in os.listdir(out_dir) if f.endswith(".elf")]
        images = [f for f in os.listdir(out_dir) if f.endswith(".sosimg")]
    if len(elves) != 1:
        raise ToolError(f"expected exactly one .elf in {out_dir}, found {elves}")
    if len(images) != 1:
        raise ToolError(f"expected exactly one .sosimg in {out_dir}, "
                        f"found {images}")
    return os.path.join(out_dir, elves[0])


def _run_arch(arch, qemu, lld, clang, blade_bin):
    """Build and run every case for one architecture.

    Returns (passed, failed, xfailed).
    """
    dirs = arch_dirs(arch)
    print(f"{BOLD}{arch['name']}{RESET}  ({arch['triple']}, "
          f"{os.path.basename(qemu)} `virt`)")

    cases = [c for c in TEST_CASES
             if arch["name"] in c.get("arches", (arch["name"],))]

    try:
        shared_objs = _build_shared(arch, clang)
    except ToolError as e:
        print(f"{CROSS} failed to build the {arch['name']} boot stub / C floor\n{e}",
              file=sys.stderr)
        return 0, len(cases), 0

    passed = 0
    failed = 0
    xfailed = 0
    for i, case in enumerate(cases, 1):
        name = case["name"]
        marker = f"[{i}/{len(cases)}]"

        if case.get("expect_compile_error"):
            ok, reason = _check_refusal(case, arch)
        elif case.get("blade_pkg"):
            try:
                elf = _build_blade_elf(blade_bin, case["blade_pkg"], arch, clang)
            except ToolError as e:
                ok, reason = False, f"blade build failed\n{e}"
            else:
                status, out, timed_out = _run_qemu(qemu, arch, elf)
                ok, reason = _check(case, arch, status, out, timed_out)
        else:
            try:
                elf = _build_elf(case, arch, shared_objs, lld, clang)
            except ToolError as e:
                ok, reason = False, f"build error\n{e}"
            else:
                status, out, timed_out = _run_qemu(qemu, arch, elf)
                ok, reason = _check(case, arch, status, out, timed_out)

        xfail = case.get("xfail")
        if xfail and not ok:
            print(f"{marker} {XMARK} {name}  (xfail: {xfail})")
            xfailed += 1
        elif xfail and ok:
            print(f"{marker} {CROSS} {name}  (STALE xfail — it passed; remove "
                  f"the marker, which cites: {xfail})")
            failed += 1
        elif ok:
            print(f"{marker} {CHECK} {name}")
            passed += 1
        else:
            print(f"{marker} {CROSS} {name}")
            for line in str(reason).splitlines():
                print(f"    {line}")
            failed += 1
    print()
    return passed, failed, xfailed


def main():
    parser = argparse.ArgumentParser(
        description="The freestanding QEMU suite (design 238)")
    parser.add_argument("--arch", metavar="NAME",
                        help="run one architecture (default: every one — the "
                             "GATE is every one)")
    args = parser.parse_args()

    arches = ARCHES
    if args.arch:
        arches = [a for a in ARCHES if a["name"] == args.arch]
        if not arches:
            names = ", ".join(a["name"] for a in ARCHES)
            print(f"{RED}unknown --arch {args.arch!r}; known: {names}{RESET}",
                  file=sys.stderr)
            sys.exit(2)

    qemus, lld, clang = _probe_tools(arches)
    if not _check_arch_free():
        sys.exit(1)

    print(f"{BOLD}Freestanding QEMU tests{RESET}")
    print(f"  clang: {clang}")
    print(f"  lld  : {lld}")
    for arch in arches:
        print(f"  qemu : {qemus[arch['name']]}")
    print()

    # Blade is architecture-neutral (a host binary), so it is built once and
    # driven per target.
    blade_bin = None
    if any(case.get("blade_pkg") for case in TEST_CASES):
        shared_build = os.path.join(REPO_ROOT, ".build", "freestanding-host")
        os.makedirs(shared_build, exist_ok=True)
        try:
            print(f"{BOLD}building blade{RESET}")
            blade_bin = _build_blade(shared_build)
        except ToolError as e:
            print(f"{CROSS} failed to build blade\n{e}", file=sys.stderr)
            sys.exit(1)
        print()

    total_passed = 0
    total_failed = 0
    total_xfailed = 0
    for arch in arches:
        passed, failed, xfailed = _run_arch(arch, qemus[arch["name"]], lld,
                                            clang, blade_bin)
        total_passed += passed
        total_failed += failed
        total_xfailed += xfailed

    print("=" * 60)
    xnote = f", {total_xfailed} xfailed" if total_xfailed else ""
    if total_failed == 0:
        names = " + ".join(a["name"] for a in arches)
        print(f"{GREEN}{BOLD}ALL FREESTANDING TESTS PASSED{RESET} "
              f"({total_passed} passed across {names}{xnote})")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}FREESTANDING TESTS FAILED{RESET} "
              f"({total_passed} passed, {total_failed} failed{xnote})")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

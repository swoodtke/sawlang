#!/usr/bin/env python3
"""SOS QEMU test harness (designs 112, 140, 162).

Builds the freestanding SOS kernel — and, for the cases that need one, a root
server image — runs them under QEMU `virt` on EVERY architecture SOS targets,
and asserts the console transcript and the emulator's exit status. `make
sos-test` green means "sawc-built code boots, crosses into user mode, and gets
the right answer or the right diagnostic", on BOTH profiles; either failing is
red.

Design 162 made this two-architecture. The shape that makes it cheap is the HAL
seam: one arch-free kernel (`sos/kernel/core/`) plus one directory per machine
(`sos/hal/<arch>/kernel/`), so adding a target here is a table entry and a
directory rather than a second harness. The scan in `_check_arch_free` is what
keeps that true — an architecture name in the arch-free kernel would still
COMPILE, and would only be wrong on the profile nobody happened to be building.

Every kernel source builds under `--no-hidden-alloc` (design 135): a kernel is
the audience for that flag, so the gate carries it permanently and any
compiler-inserted allocation the source does not name breaks the build here
rather than shipping.

Pipeline per test case, per architecture:
  1. sawc   : <src>.saw  -> <name>.o   (--freestanding --no-hidden-alloc
              --target <triple>, --module-path kcore=… hal=… — the arch-free
              kernel and the HAL it reaches the machine through)
  2. clang  : boot.S     -> boot.o     (kernel HAL; assembled once)
  3. clang  : sink.c     -> sink.o     (kernel HAL: board hooks + protection)
     clang  : support.c  -> support.o  (shared runtime seams, compiled once)
  4. the `.payload` blob, if the case has one — EITHER a hand-written `.S` from
     `sos/tests/<arch>/` (unit A's user-mode code, unit B's hand-assembled
     sosimgs) OR a root package built by Blade and pulled in through
     sos/kernel/rootimg.S's `.incbin`
  5. ld.lld : link with the HAL's virt.ld --gc-sections -> <name>.elf
  6. qemu   : run with a hard timeout; capture console stdout + exit status

A root package (`root_pkg`) is a real Blade package with `[sos] emit =
"sosimg"` in its manifest and a `[sos.<triple>]` section per machine, so the
two-image cases exercise the same build path any later SOS process will use
rather than a rule written here — and prove that ONE unchanged `src/` builds
for both profiles.

QEMU / ld.lld / clang are HOST PREREQUISITES (like the Python venv), not
Blade-managed; the harness probes for them up front and fails with an install
hint. It is deliberately separate from test_runner.py (a different execution
model) but reports in the same pass/fail style.

`--arch <name>` runs one architecture, for development. The GATE is both.
"""

import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO_ROOT, "sawc", "sawc.py")
KERNEL_DIR = os.path.join(REPO_ROOT, "sos", "kernel")
CORE_DIR = os.path.join(KERNEL_DIR, "core")
TESTS_DIR = os.path.join(REPO_ROOT, "sos", "tests")
HAL_DIR = os.path.join(REPO_ROOT, "sos", "hal")

# The arch-free kernel module every image shares. It carries the trap handler
# the HAL's boot code calls, so the module path is not optional for any case.
CORE_MODULE = f"kcore={CORE_DIR}"

# The sosimg layout, shared with the Blade target that emits images. The kernel
# reaches it through --module-path; Blade reaches the same sources through a
# manifest path-dependency. One definition, two consumption mechanisms.
IMGFORMAT_DIR = os.path.join(REPO_ROOT, "sos", "imgformat", "src")
IMGFORMAT_MODULE = f"imgformat={IMGFORMAT_DIR}"

# Arch-free, role-free Saw runtime helpers, shared with every process build.
SOSRT_DIR = os.path.join(REPO_ROOT, "sos", "rt", "common", "src")
SOSRT_MODULE = f"sosrt={SOSRT_DIR}"

# The call numbers. Kernel-INTERNAL (sos/spec.md §5.7's vDSO discipline): the
# dispatch tables here and the `sos` module the kernel exports to userspace
# share it, and nothing else does. A process links `sos` and never sees a
# number, so it never needs this path.
SOSABI_DIR = os.path.join(KERNEL_DIR, "abi", "src")
SOSABI_MODULE = f"sosabi={SOSABI_DIR}"

RT_COMMON_C_DIR = os.path.join(REPO_ROOT, "sos", "rt", "common_c")

# sos/tests/<arch>/payload_badcall.S shuts down with this when all of its own
# checks passed. Kept in step with the `.equ EXPECTED_CODE` there.
PAYLOAD_CHECKS_PASSED = 7

# Root-server packages. These are real Blade packages built by Blade — the
# whole point of unit C is that root goes through the same package pipeline any
# SOS process will, not a bespoke rule in this file.
BLADE_DIR = os.path.join(REPO_ROOT, "blade")
TOML_SRC = os.path.join(REPO_ROOT, "libs", "toml", "src")
SEMVER_SRC = os.path.join(REPO_ROOT, "libs", "semver", "src")
ROOT_PKG = os.path.join(REPO_ROOT, "sos", "root")
FAULT_ROOT_PKG = os.path.join(TESTS_DIR, "faulting-root")

QEMU_TIMEOUT_S = 10

# =============================================================================
# The architectures
# =============================================================================
#
# One entry per machine SOS targets (spec §5b). Everything that differs between
# them is HERE, in data, which is the harness-level statement of the same claim
# the HAL makes in code: a second architecture is a table row and a directory.
#
# `hex_width` is how many digits the kernel's `write_hex` prints — one per
# nibble of a MACHINE WORD, so eight on a 32-bit profile and sixteen on a
# 64-bit one. Expectations below are written with placeholders and formatted
# per architecture rather than duplicated, so a case asserts the same FACT on
# both and the widths follow the target.

ARCHES = [
    {
        "name": "riscv32",
        "triple": "riscv32-unknown-none-elf",
        "qemu": "qemu-system-riscv32",
        # `-bios none`: no OpenSBI, the kernel IS the reset target.
        "qemu_args": ["-M", "virt", "-bios", "none"],
        # A triple names the architecture but not which optional extensions the
        # part has: without `+m` the Saw half is built for base rv32i and
        # formatting an integer emits `__divsi3` calls this link cannot satisfy.
        # The C half gets the same set through `-march`.
        "cc_args": ["-march=rv32imac_zicsr", "-mabi=ilp32"],
        "features": "+m,+a,+c",
        "hex_width": 8,
        "root_entry": 0x80200000,
    },
    {
        "name": "arm64",
        "triple": "aarch64-unknown-none-elf",
        "qemu": "qemu-system-aarch64",
        # `-cpu cortex-a53` (design 162 decision 3): ubiquitous, EL1
        # well-exercised. `-semihosting` is what makes SYS_EXIT carry a status
        # code — see sos/hal/arm64/kernel/sink.c for why not PSCI.
        "qemu_args": ["-M", "virt", "-cpu", "cortex-a53", "-semihosting"],
        # The base aarch64 triple already has everything this kernel uses, and
        # there is no ABI variant to select.
        "cc_args": [],
        "features": None,
        "hex_width": 16,
        "root_entry": 0x40200000,
    },
]


def arch_dirs(arch):
    """The per-architecture directories a build reaches into."""
    return {
        "hal_kernel": os.path.join(HAL_DIR, arch["name"], "kernel"),
        "tests": os.path.join(TESTS_DIR, arch["name"]),
        "build": os.path.join(REPO_ROOT, ".build", arch["triple"], "sos"),
    }


def expectations(arch):
    """The per-architecture substitutions a case's expected output is written in.

    A case says `entry={entry}`, not `entry=0x80200000`, because the FACT under
    test is "the entry the image declared came through intact" and the digits
    are the target's word width.
    """
    width = arch["hex_width"]
    return {
        "banner": f"SOS M1: kernel up on {arch['name']}",
        "entry": f"0x{arch['root_entry']:0{width}x}",
        "one": f"0x{1:0{width}x}",
        "two": f"0x{2:0{width}x}",
        "prio": f"0x{0x01010100:0{width}x}",
    }


# =============================================================================
# The seam check (design 162 unit 1)
# =============================================================================

ARCH_FREE_DIRS = [
    os.path.join(REPO_ROOT, "sos", "kernel", "core"),
    os.path.join(REPO_ROOT, "sos", "kernel", "main.saw"),
]
ARCH_WORDS = [
    "riscv", "rv32", "rv64", "aarch64", "arm64", "armv8",
    "mcause", "mepc", "mtval", "mstatus", "mscratch", "mtvec", "ecall", "pmp",
    "sifive", "ns16550", "csr", "m-mode", "u-mode",
    "esr_el", "elr_el", "far_el", "vbar", "ttbr", "sctlr", "tcr_el", "mair",
    "pl011", "psci", "semihost", " svc ", "el0", "el1",
]

# ANSI colors (matched to test_runner.py's style; disabled when not a TTY).
_TTY = sys.stdout.isatty()
GREEN = "\033[92m" if _TTY else ""
RED = "\033[91m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
RESET = "\033[0m" if _TTY else ""
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"

# =============================================================================
# The cases
# =============================================================================
#
# Each test: the entry source, an optional payload assembled from the running
# architecture's own `sos/tests/<arch>/` directory, one or more expected console
# substrings (or None), and whether the emulator should exit cleanly (True →
# status 0) or fail (False). Expected strings are `str.format`ed with
# `expectations(arch)`.

TEST_CASES = [
    {
        # The kernel exists to hand control to root. Built with no image
        # appended it must say so and FAIL — never exit quietly as if the
        # system had run.
        "name": "no_root_image",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "expect_out": ["{banner}", "bad root image: no root image appended"],
        "expect_clean_exit": False,
    },
    {
        "name": "trap_fault",
        "src": os.path.join(TESTS_DIR, "trap.saw"),
        "expect_out": None,             # a fault produces no banner
        "expect_clean_exit": False,     # the HAL's kernel-bug path
    },
    {
        "name": "panic_seam",
        "src": os.path.join(TESTS_DIR, "panic.saw"),
        "expect_out": "SOS M0: deliberate panic",
        "expect_clean_exit": False,     # __saw_rt_panic → console + abort
    },
    {
        # Design 172 unit 4: the panic-recursion pin. The message comes from
        # the COMPILER's bounds check, so the reporter is entered from the trap
        # path — the one that would recurse if the writer under it could panic.
        # Asserting the prefix AND the reason is what catches a garbled report;
        # asserting a non-zero exit is what catches a hung one.
        # The location is the TRAPPING expression's own (design 122), which for
        # an indexed accessor is inside std — so this asserts `vector.saw`, not
        # the test's file. That is the point: three independent pieces (prefix,
        # location, reason) all arriving means nothing re-entered the writer
        # mid-report.
        "name": "panic_from_check",
        "src": os.path.join(TESTS_DIR, "panic_from_check.saw"),
        "expect_out": ["panic at ", "vector.saw:",
                       "Vector.[]: index out of range"],
        "expect_clean_exit": False,
    },
    # --- design 140 unit A: the privilege split, without any image format ----
    {
        "name": "umode_syscall",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_ok.S",
        # "SOS-U" is written one character at a time through `debug_print`, so
        # seeing it at all proves the syscall round trip resumed correctly.
        "expect_out": ["SOS M1: entering U-mode", "SOS-U"],
        "expect_clean_exit": True,      # shutdown(0)
    },
    {
        "name": "umode_access_fault",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_fault.S",
        # Both HALs report the same name for the same event, which is why one
        # string serves two architectures.
        "expect_out": "fault store-access-fault",
        "expect_clean_exit": False,
    },
    {
        # A caller's mistake is an ERROR, not a fault: an unknown op and an
        # unknown handle each come back as a status word and the process runs
        # on. The payload checks all three statuses itself and shuts down with
        # PAYLOAD_CHECKS_PASSED only if every one matched, so the emulator's
        # exit code IS the assertion.
        "name": "umode_bad_calls",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_badcall.S",
        "expect_out": "SOS M1: entering U-mode",
        "expect_clean_exit": False,
        "expect_status": PAYLOAD_CHECKS_PASSED,
    },
    # --- design 140 unit B: the sosimg format and the kernel's loader -------
    # These images are assembled by hand (sos/tests/<arch>/payload_*.S), so they
    # pin the format independently of Blade's emitter — two producers, one
    # loader, and on two architectures the SAME 16-byte header.
    {
        "name": "root_image_load",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": "payload_sosimg.S",
        "expect_out": ["{banner}",
                       "root image ok segments={one} entry={entry} prio={prio}",
                       "SOS-R"],
        "expect_clean_exit": True,
    },
    {
        "name": "root_image_bad_magic",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": "payload_badmagic.S",
        "expect_out": "bad root image: bad magic",
        "expect_clean_exit": False,
    },
    {
        # Design 172 unit 8: a version bump is a REFUSAL boundary. The payload
        # is a real v2 image — correct magic, right arch, sane permissions —
        # and a v3 loader must stop at the version rather than guess at a
        # record whose address field is a different width in a different place.
        "name": "root_image_bad_version",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": "payload_badversion.S",
        "expect_out": "bad root image: unsupported version",
        "expect_clean_exit": False,
    },
    {
        # Design 162 unit 3: one format, two profiles. An image whose header is
        # correct in every other way but says it was built for the other
        # machine is refused on the tag, before a byte is copied.
        "name": "root_image_wrong_arch",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": "payload_wrongarch.S",
        "expect_out": "bad root image: image is for another architecture",
        "expect_clean_exit": False,
    },
    {
        # The check that matters most: an image may not aim a segment at the
        # kernel. Rejected before a byte is copied.
        "name": "root_image_bad_segment",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": "payload_badsegment.S",
        "expect_out": "bad root image: segment loads below the root region",
        "expect_clean_exit": False,
    },
    # --- design 140 unit C: the real two-image boot ------------------------
    # Kernel and root are separate builds — separate linker scripts, separate
    # load addresses, root built by Blade from its own package manifest — and
    # meet only as an appended blob the kernel parses. Since design 162 the
    # SAME root sources build for both profiles: only the manifest's
    # `[sos.<triple>]` section differs.
    {
        "name": "root_server_boot",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": ROOT_PKG,
        "expect_out": ["{banner}",
                       "root image ok segments={two}",
                       "prio={prio}",
                       # The typed SAW altitude.
                       "SOS root: hello from U-mode via a System op",
                       # The typed C altitude: `print` -> `__saw_rt_write` ->
                       # the HAL sink -> the exported `sos_system_debug_print`.
                       # Also design 137 formatting with no allocator present.
                       "SOS root: boot handle 1"],
        "expect_clean_exit": True,
    },
    {
        # The grant has to hold against a root that is merely WRONG, not just
        # against one that behaves.
        "name": "root_server_oversteps",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": FAULT_ROOT_PKG,
        "expect_out": ["SOS root: reaching for the kernel",
                       "fault store-access-fault"],
        "expect_clean_exit": False,
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
    (apt) works. `SOS_CLANG` overrides the search. The probe compiles each
    architecture's own `boot.S`, because "can target riscv32" and "can target
    aarch64" are separate questions and one harness needs both answered yes.
    """
    candidates = []
    if os.environ.get("SOS_CLANG"):
        candidates.append(os.environ["SOS_CLANG"])
    candidates += ["clang", "/opt/homebrew/opt/llvm/bin/clang", "/usr/local/opt/llvm/bin/clang"]
    for cand in candidates:
        path = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if not path:
            continue
        ok = True
        for arch in arches:
            dirs = arch_dirs(arch)
            os.makedirs(dirs["build"], exist_ok=True)
            probe_src = os.path.join(dirs["hal_kernel"], "boot.S")
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
        print(f"{RED}{BOLD}sos-test: missing host prerequisites{RESET}", file=sys.stderr)
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
    """Fail the run if an architecture name appears in the arch-free kernel.

    Design 162 unit 1: the deliverable is as much the SEAM as the port. A
    kernel that names its architecture still compiles — the leak only shows up
    on the OTHER target, whenever someone next ports — so the check that keeps
    the seam honest has to be mechanical. Comments count: a note that says
    `mepc` is a note that will be wrong on the profile that has no `mepc`.
    """
    bad = []
    for path in ARCH_FREE_DIRS:
        for src in _sources_under(path):
            with open(src, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    low = line.lower()
                    for word in ARCH_WORDS:
                        if word in low:
                            rel = os.path.relpath(src, REPO_ROOT)
                            bad.append(f"{rel}:{lineno}: {word!r} in: {line.strip()}")
    if bad:
        print(f"{RED}{BOLD}sos-test: architecture names in the arch-free kernel"
              f"{RESET}", file=sys.stderr)
        for line in bad:
            print(f"  {line}", file=sys.stderr)
        print("  (design 162 unit 1: kcore reaches the machine through `hal` "
              "only)", file=sys.stderr)
        return False
    return True


def _build_shared(arch, clang):
    """Build one architecture's native objects once; return them as a list.

    A kernel image is that architecture's kernel HAL (boot + trap entry, the
    board sinks, the protection primitive) plus the shared runtime support every
    SOS build links — the same `support.c` a root package names in its
    `[sos.<triple>] native`.
    """
    dirs = arch_dirs(arch)
    build = dirs["build"]
    # Ensure our own output directory rather than relying on the tool probe
    # having made it: a cold tree with `SOS_CLANG` set skips that probe path
    # entirely, and a build step should not depend on a search for its side
    # effects.
    os.makedirs(build, exist_ok=True)
    boot_o = os.path.join(build, "boot.o")
    sink_o = os.path.join(build, "sink.o")
    support_o = os.path.join(build, "support.o")
    _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
          "-nostdlib", "-c", os.path.join(dirs["hal_kernel"], "boot.S"),
          "-o", boot_o])
    for src, obj in ((os.path.join(dirs["hal_kernel"], "sink.c"), sink_o),
                     (os.path.join(RT_COMMON_C_DIR, "support.c"), support_o)):
        # -fno-builtin: support.c DEFINES memcpy, and without it LLVM may
        # rewrite its byte loop into a call to itself.
        _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
              "-ffreestanding", "-fno-builtin", "-ffunction-sections",
              "-fdata-sections", "-nostdlib", "-O2", "-c", src, "-o", obj])
    return [boot_o, sink_o, support_o]


def _build_blade(build_dir):
    """Build Blade once with the in-tree compiler; return the binary path.

    The `blade_bootstrap.py` stage0 step, reused: the SOS root packages are
    built BY BLADE, so the harness needs a Blade to drive.
    """
    blade_bin = os.path.join(build_dir, "blade")
    _run([sys.executable, SAWC, os.path.join(BLADE_DIR, "src", "main.saw"),
          "-o", blade_bin,
          "--module-path", f"toml={TOML_SRC}",
          "--module-path", f"semver={SEMVER_SRC}",
          "--module-path", IMGFORMAT_MODULE])
    return blade_bin


def _blade_env(clang):
    env = dict(os.environ)
    env["SAWC"] = f"{sys.executable} {SAWC}"
    # macOS's Apple clang mis-drives the riscv integrated assembler; hand Blade
    # the same clang this harness probed for.
    env["SOS_CLANG"] = clang
    return env


def _build_root_image(blade_bin, pkg_dir, arch, clang):
    """`blade build --target <triple>` a root package; return its sosimg path.

    Always `--force`: the harness's job is to prove the CURRENT tree boots, and
    Blade's build avoidance keys on content it cannot see change here (the
    kernel side, the linker script's meaning).
    """
    # Design 143: artifacts live under `<package>/.build/<target>/`, never
    # beside the source — which is also what lets one package hold two
    # architectures' images at once.
    out_dir = os.path.join(pkg_dir, ".build", arch["triple"])

    # Delete first: a build that fails must not leave the PREVIOUS image lying
    # around to be booted as if it were current. (Blade used to exit 0 on a
    # failed build, which is exactly how a stale image once passed this suite.)
    if os.path.isdir(out_dir):
        for stale in os.listdir(out_dir):
            if stale.endswith(".sosimg"):
                os.remove(os.path.join(out_dir, stale))

    _run([blade_bin, "build", "--force", "--target", arch["triple"]],
         cwd=pkg_dir, env=_blade_env(clang))

    # The image is named for the PACKAGE, which need not match its directory.
    images = []
    if os.path.isdir(out_dir):
        images = [f for f in os.listdir(out_dir) if f.endswith(".sosimg")]
    if len(images) != 1:
        raise ToolError(f"expected exactly one .sosimg in {out_dir}, found {images}")
    return os.path.join(out_dir, images[0])


def _stitch_root_image(image, arch, clang):
    """Assemble the `.incbin` stub that pulls `image` into `.payload`.

    The stub names `root.sosimg` and is assembled with `-I` pointing at this
    architecture's build directory, so one committed stub stitches whichever
    root image the case asked for.
    """
    dirs = arch_dirs(arch)
    os.makedirs(dirs["build"], exist_ok=True)
    staged = os.path.join(dirs["build"], "root.sosimg")
    shutil.copyfile(image, staged)
    stub_o = os.path.join(dirs["build"], "rootimg.o")
    _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
          "-nostdlib", "-I", dirs["build"], "-c",
          os.path.join(KERNEL_DIR, "rootimg.S"), "-o", stub_o])
    return stub_o


def _build_elf(case, arch, shared_objs, lld, clang):
    """Compile + link one test case for one architecture; return its ELF path.

    A case may name an extra `.S` payload, taken from THIS architecture's test
    directory, which lands in the `.payload` section the HAL's linker script
    bounds — unit A's raw user-mode code, and from unit B on the `.incbin` stub
    that carries the root sosimg.
    """
    dirs = arch_dirs(arch)
    os.makedirs(dirs["build"], exist_ok=True)
    name = case["name"]
    obj = os.path.join(dirs["build"], f"{name}.o")
    elf = os.path.join(dirs["build"], f"{name}.elf")
    # design 135: `--no-hidden-alloc` rides along on every kernel build. The
    # kernel logs through the alloc-free formatting path already (design 137's
    # dogfood), so this costs nothing today and is what keeps it that way — an
    # interpolated log line or an escaping closure added later fails the gate
    # instead of quietly reaching for an allocator the kernel may not have.
    # design 172 part 2: `--runtime-provider` (design 149) says this compile
    # IMPLEMENTS the frozen `__saw_rt_*` seams rather than merely calling them.
    # It has to be here rather than in a manifest because a kernel image is not
    # a Blade package: `sosrt` carries the seam bodies and rides in on
    # --module-path, so THIS is the compile that defines them. Without it the
    # `@export`s are refused by name; with it every signature is checked against
    # sawc/rt/ABI.md.
    cmd = [sys.executable, SAWC, case["src"], "-o", obj,
           "--freestanding", "--no-hidden-alloc", "--runtime-provider",
           "--target", arch["triple"]]
    if arch["features"]:
        cmd += ["--target-features", arch["features"]]
    cmd += ["--module-path", CORE_MODULE,
            "--module-path", f"hal={dirs['hal_kernel']}",
            "--module-path", IMGFORMAT_MODULE,
            "--module-path", SOSRT_MODULE,
            "--module-path", SOSABI_MODULE]
    _run(cmd)

    objs = list(shared_objs) + [obj]
    if case.get("asm"):
        payload_src = os.path.join(dirs["tests"], case["asm"])
        payload_o = os.path.join(dirs["build"], f"{name}.payload.o")
        _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
              "-nostdlib", "-c", payload_src, "-o", payload_o])
        objs.append(payload_o)
    if case.get("root_pkg"):
        objs.append(_stitch_root_image(case["_root_image"][arch["name"]], arch, clang))

    _run([lld, "-T", os.path.join(dirs["hal_kernel"], "virt.ld"), "--gc-sections",
          "-o", elf, *objs])
    return elf


def _run_qemu(qemu, arch, elf):
    """Run the ELF under QEMU with a hard timeout.

    Returns (exit_status, stdout, timed_out). A timeout is a hang — the whole
    point of the kernel-bug path is that faults never reach it.
    """
    try:
        proc = subprocess.run(
            [qemu, *arch["qemu_args"], "-nographic", "-kernel", elf],
            capture_output=True, text=True, timeout=QEMU_TIMEOUT_S)
        return proc.returncode, proc.stdout, False
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or (e.stdout and e.stdout.decode()) or ""), True


def _check(case, arch, status, out, timed_out):
    """Return (ok, reason). Validates console output and exit expectations."""
    if timed_out:
        return False, f"QEMU hung (> {QEMU_TIMEOUT_S}s) — no clean exit"
    if isinstance(out, bytes):
        out = out.decode(errors="replace")
    expected = case["expect_out"]
    if expected is not None:
        # A single substring or a list of them — one boot can assert several
        # lines without rebuilding the kernel once per assertion.
        if isinstance(expected, str):
            expected = [expected]
        fmt = expectations(arch)
        for want in expected:
            want = want.format(**fmt)
            if want not in out:
                return False, f"missing expected output {want!r} (got {out!r})"
    if case["expect_clean_exit"]:
        if status != 0:
            return False, f"expected clean exit (0), got status {status}"
    else:
        if status == 0:
            return False, "expected a failing (non-zero) exit, got 0"
    # An exact status, where the payload encodes its own verdict in one.
    want_status = case.get("expect_status")
    if want_status is not None and status != want_status:
        return False, f"expected exit status {want_status}, got {status}"
    return True, ""


def _run_arch(arch, qemu, lld, clang, blade_bin):
    """Build and run every case for one architecture. Returns (passed, failed)."""
    dirs = arch_dirs(arch)
    print(f"{BOLD}{arch['name']}{RESET}  ({arch['triple']}, {os.path.basename(qemu)} `virt`)")

    try:
        shared_objs = _build_shared(arch, clang)
    except ToolError as e:
        print(f"{CROSS} failed to build the {arch['name']} kernel HAL / runtime support\n{e}",
              file=sys.stderr)
        return 0, len(TEST_CASES)

    # Root packages are built by Blade, per architecture, so build them first —
    # but only if some case actually needs one.
    root_pkgs = []
    for case in TEST_CASES:
        if case.get("root_pkg") and case["root_pkg"] not in root_pkgs:
            root_pkgs.append(case["root_pkg"])
    if root_pkgs:
        try:
            for pkg in root_pkgs:
                image = _build_root_image(blade_bin, pkg, arch, clang)
                size = os.path.getsize(image)
                print(f"  {os.path.relpath(image, REPO_ROOT)}  ({size} bytes)")
            for case in TEST_CASES:
                if case.get("root_pkg"):
                    holder = case.setdefault("_root_image", {})
                    holder[arch["name"]] = _root_image_path(case["root_pkg"], arch)
        except ToolError as e:
            print(f"{CROSS} failed to build a {arch['name']} root image\n{e}",
                  file=sys.stderr)
            return 0, len(TEST_CASES)

    passed = 0
    failed = 0
    for i, case in enumerate(TEST_CASES, 1):
        name = case["name"]
        try:
            elf = _build_elf(case, arch, shared_objs, lld, clang)
        except ToolError as e:
            print(f"[{i}/{len(TEST_CASES)}] {CROSS} {name}  (build error)")
            for line in str(e).splitlines():
                print(f"    {line}")
            failed += 1
            continue
        status, out, timed_out = _run_qemu(qemu, arch, elf)
        ok, reason = _check(case, arch, status, out, timed_out)
        if ok:
            print(f"[{i}/{len(TEST_CASES)}] {CHECK} {name}")
            passed += 1
        else:
            print(f"[{i}/{len(TEST_CASES)}] {CROSS} {name}  ({reason})")
            failed += 1
    print()
    return passed, failed


def _root_image_path(pkg_dir, arch):
    out_dir = os.path.join(pkg_dir, ".build", arch["triple"])
    images = [f for f in os.listdir(out_dir) if f.endswith(".sosimg")]
    return os.path.join(out_dir, images[0])


def main():
    parser = argparse.ArgumentParser(description="SOS QEMU test harness")
    parser.add_argument("--arch", metavar="NAME",
                        help="run one architecture (default: every one — the GATE is every one)")
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

    print(f"{BOLD}SOS QEMU tests{RESET}")
    print(f"  clang: {clang}")
    print(f"  lld  : {lld}")
    for arch in arches:
        print(f"  qemu : {qemus[arch['name']]}")
    print()

    # Blade is architecture-neutral (a host binary), so it is built once and
    # driven per target.
    blade_bin = None
    if any(case.get("root_pkg") for case in TEST_CASES):
        shared_build = os.path.join(REPO_ROOT, ".build", "sos-host")
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
    for arch in arches:
        passed, failed = _run_arch(arch, qemus[arch["name"]], lld, clang, blade_bin)
        total_passed += passed
        total_failed += failed

    print("=" * 60)
    if total_failed == 0:
        names = " + ".join(a["name"] for a in arches)
        print(f"{GREEN}{BOLD}ALL SOS TESTS PASSED{RESET} "
              f"({total_passed} passed across {names})")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}SOS TESTS FAILED{RESET} "
              f"({total_passed} passed, {total_failed} failed)")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

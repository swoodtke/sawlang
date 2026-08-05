#!/usr/bin/env python3
"""SOS QEMU test harness (designs 112, 140).

Builds the freestanding SOS kernel — and, for the cases that need one, a root
server image — runs them under QEMU `virt` (riscv32), and asserts the UART
transcript and the emulator's exit status. `make sos-test` green means
"sawc-built code boots, crosses into U-mode, and gets the right answer or the
right diagnostic".

Every kernel source builds under `--no-hidden-alloc` (design 135): a kernel is
the audience for that flag, so the gate carries it permanently and any
compiler-inserted allocation the source does not name breaks the build here
rather than shipping.

Pipeline per test case:
  1. sawc   : <src>.saw  -> <name>.o   (--freestanding --no-hidden-alloc
              --target riscv32-..., --module-path kcore=sos/kernel/core — the
              shared kernel module carrying the trap handler boot.S calls)
  2. clang  : boot.S     -> boot.o     (shared; assembled once)
  3. clang  : rt.c       -> rt.o       (shared; runtime seams, compiled once)
  4. the `.payload` blob, if the case has one — EITHER a hand-written `.S`
     (unit A's U-mode code, unit B's hand-assembled sosimgs) OR a root package
     built by Blade and pulled in through sos/kernel/rootimg.S's `.incbin`
  5. ld.lld : link with sos/kernel/virt.ld --gc-sections -> <name>.elf
  6. qemu   : run with a hard timeout; capture UART stdout + exit status

A root package (`root_pkg`) is a real Blade package with `[sos] emit =
"sosimg"` in its manifest, so the two-image cases exercise the same build path
any later SOS process will use rather than a rule written here.

QEMU / ld.lld / clang are HOST PREREQUISITES (like the Python venv), not
Blade-managed; the harness probes for them up front and fails with an install
hint. It is deliberately separate from test_runner.py (a different execution
model) but reports in the same pass/fail style.
"""

import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO_ROOT, "sawc", "sawc.py")
KERNEL_DIR = os.path.join(REPO_ROOT, "sos", "kernel")
CORE_DIR = os.path.join(KERNEL_DIR, "core")
TESTS_DIR = os.path.join(REPO_ROOT, "sos", "tests")

# Every kernel image is `boot.S` + `rt.c` + the shared kernel core + one entry
# `.saw` defining `kmain`. The core carries the trap handler boot.S calls, so
# the module path is not optional for any case.
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

# The per-architecture, per-role native halves. M1b adds sos/hal/arm64/...
# beside these without moving anything here.
HAL_KERNEL_DIR = os.path.join(REPO_ROOT, "sos", "hal", "riscv32", "kernel")
RT_COMMON_C_DIR = os.path.join(REPO_ROOT, "sos", "rt", "common_c")

# sos/tests/payload_badcall.S shuts down with this when all of its own checks
# passed. Kept in step with the `.equ EXPECTED_CODE` there.
PAYLOAD_CHECKS_PASSED = 7

# Root-server packages. These are real Blade packages built by Blade — the
# whole point of unit C is that root goes through the same package pipeline any
# SOS process will, not a bespoke rule in this file.
BLADE_DIR = os.path.join(REPO_ROOT, "blade")
TOML_SRC = os.path.join(REPO_ROOT, "libs", "toml", "src")
SEMVER_SRC = os.path.join(REPO_ROOT, "libs", "semver", "src")
ROOT_PKG = os.path.join(REPO_ROOT, "sos", "root")
FAULT_ROOT_PKG = os.path.join(TESTS_DIR, "faulting-root")

TRIPLE = "riscv32-unknown-none-elf"
MARCH = "rv32imac_zicsr"
MABI = "ilp32"
# The same extensions as MARCH, in LLVM subtarget-feature form, for sawc's
# `--target-features`. A triple names the architecture but not which optional
# extensions the part has: without `+m` the Saw half of the kernel is built for
# base rv32i, and formatting an integer (which needs division) emits `__divsi3`
# calls that this link has no library to satisfy. The C half already gets these
# through `-march`; this keeps the two halves on one subtarget.
MFEATURES = "+m,+a,+c"
QEMU_TIMEOUT_S = 10

# Build output goes under `.build/<target>/` (design 143), the same per-target
# shape Blade uses. Every object here is compiled for TRIPLE — the Saw half, the
# assembled boot code, and the C runtime seams alike — so a second architecture
# (arm64 is on the roadmap) gets its own directory instead of overwriting this
# one's `boot.o` with something that will not link.
BUILD_DIR = os.path.join(REPO_ROOT, ".build", TRIPLE, "sos")

# ANSI colors (matched to test_runner.py's style; disabled when not a TTY).
_TTY = sys.stdout.isatty()
GREEN = "\033[92m" if _TTY else ""
RED = "\033[91m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
RESET = "\033[0m" if _TTY else ""
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"

# Each test: the entry source, an optional extra assembly payload linked into
# the `.payload` section, one or more expected UART substrings (or None), and
# whether the emulator should exit cleanly (True → status 0) or fail (False).
TEST_CASES = [
    {
        # The kernel exists to hand control to root. Built with no image
        # appended it must say so and FAIL — never exit quietly as if the
        # system had run.
        "name": "no_root_image",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "expect_out": ["SOS M1: kernel up on riscv32",
                       "bad root image: no root image appended"],
        "expect_clean_exit": False,
    },
    {
        "name": "trap_fault",
        "src": os.path.join(TESTS_DIR, "trap.saw"),
        "expect_out": None,             # a fault produces no banner
        "expect_clean_exit": False,     # kernel_fault → FINISHER_FAIL
    },
    {
        "name": "panic_seam",
        "src": os.path.join(TESTS_DIR, "panic.saw"),
        "expect_out": "SOS M0: deliberate panic",
        "expect_clean_exit": False,     # __saw_rt_panic → UART + FINISHER_FAIL
    },
    # --- design 140 unit A: the M/U split, without any image format ----------
    {
        "name": "umode_syscall",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_ok.S"),
        # "SOS-U" is written one character at a time through `debug_putc`, so
        # seeing it at all proves the ecall round trip resumed correctly.
        "expect_out": ["SOS M1: entering U-mode", "SOS-U"],
        "expect_clean_exit": True,      # sys_exit(0) → FINISHER_PASS
    },
    {
        "name": "umode_access_fault",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_fault.S"),
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
        "asm": os.path.join(TESTS_DIR, "payload_badcall.S"),
        "expect_out": "SOS M1: entering U-mode",
        "expect_clean_exit": False,
        "expect_status": PAYLOAD_CHECKS_PASSED,
    },
    # --- design 140 unit B: the sosimg format and the kernel's loader -------
    # These images are assembled by hand (sos/tests/payload_*.S), so they pin
    # the format independently of Blade's emitter — two producers, one loader.
    {
        "name": "root_image_load",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_sosimg.S"),
        "expect_out": ["SOS M1: kernel up on riscv32",
                       "root image ok segments=0x00000001 entry=0x80200000 prio=0x01010100",
                       "SOS-R"],
        "expect_clean_exit": True,
    },
    {
        "name": "root_image_bad_magic",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_badmagic.S"),
        "expect_out": "bad root image: bad magic",
        "expect_clean_exit": False,
    },
    {
        # The check that matters most: an image may not aim a segment at the
        # kernel. Rejected before a byte is copied.
        "name": "root_image_bad_segment",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_badsegment.S"),
        "expect_out": "bad root image: segment loads below the root region",
        "expect_clean_exit": False,
    },
    # --- design 140 unit C: the real two-image boot ------------------------
    # Kernel and root are separate builds — separate linker scripts, separate
    # load addresses, root built by Blade from its own package manifest — and
    # meet only as an appended blob the kernel parses.
    {
        "name": "root_server_boot",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": ROOT_PKG,
        "expect_out": ["SOS M1: kernel up on riscv32",
                       "root image ok segments=0x00000002",
                       "prio=0x01010100",
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


def _find_clang():
    """Return the first clang that can target riscv32, or None.

    macOS's Apple clang mis-drives the riscv integrated assembler, so a real
    LLVM clang (Homebrew `llvm`) is preferred there; on Linux CI plain `clang`
    (apt) works. `SOS_CLANG` overrides the search.
    """
    candidates = []
    if os.environ.get("SOS_CLANG"):
        candidates.append(os.environ["SOS_CLANG"])
    candidates += ["clang", "/opt/homebrew/opt/llvm/bin/clang", "/usr/local/opt/llvm/bin/clang"]
    probe_src = os.path.join(HAL_KERNEL_DIR, "boot.S")
    for cand in candidates:
        path = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if not path:
            continue
        try:
            _run([path, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
                  "-nostdlib", "-c", probe_src, "-o", os.path.join(BUILD_DIR, "_probe.o")])
            return path
        except ToolError:
            continue
    return None


def _probe_tools():
    """Locate qemu/ld.lld/clang; print install hints and exit on any miss."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    missing = []

    qemu = shutil.which("qemu-system-riscv32")
    if not qemu:
        missing.append("qemu-system-riscv32")
    lld = shutil.which("ld.lld")
    if not lld:
        missing.append("ld.lld")
    clang = _find_clang()
    if not clang:
        missing.append("clang")

    if missing:
        print(f"{RED}{BOLD}sos-test: missing host prerequisites{RESET}", file=sys.stderr)
        for tool in missing:
            print(f"  - {tool}: {INSTALL_HINTS[tool]}", file=sys.stderr)
        sys.exit(2)

    return qemu, lld, clang


def _build_shared(clang):
    """Build the kernel's native objects once; return them as a list.

    The kernel's C/asm is the riscv32 kernel HAL (boot + trap entry, the board
    sinks, the PMP helpers) plus the shared runtime support every SOS build
    links — the same `support.c` a root package names in its `[sos] native`.
    """
    boot_o = os.path.join(BUILD_DIR, "boot.o")
    sink_o = os.path.join(BUILD_DIR, "sink.o")
    support_o = os.path.join(BUILD_DIR, "support.o")
    _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
          "-nostdlib", "-c", os.path.join(HAL_KERNEL_DIR, "boot.S"), "-o", boot_o])
    for src, obj in ((os.path.join(HAL_KERNEL_DIR, "sink.c"), sink_o),
                     (os.path.join(RT_COMMON_C_DIR, "support.c"), support_o)):
        # -fno-builtin: support.c DEFINES memcpy, and without it LLVM may
        # rewrite its byte loop into a call to itself.
        _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
              "-ffreestanding", "-fno-builtin", "-ffunction-sections",
              "-fdata-sections", "-nostdlib", "-O2", "-c", src, "-o", obj])
    return [boot_o, sink_o, support_o]


def _build_blade(clang):
    """Build Blade once with the in-tree compiler; return the binary path.

    The `blade_bootstrap.py` stage0 step, reused: the SOS root packages are
    built BY BLADE, so the harness needs a Blade to drive.
    """
    blade_bin = os.path.join(BUILD_DIR, "blade")
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


def _build_root_image(blade_bin, pkg_dir, clang):
    """`blade build` a root package; return the path to its sosimg.

    Always `--force`: the harness's job is to prove the CURRENT tree boots, and
    Blade's build avoidance keys on content it cannot see change here (the
    kernel side, the linker script's meaning).
    """
    # Design 143: artifacts live under `<package>/.build/<target>/`, never
    # beside the source.
    out_dir = os.path.join(pkg_dir, ".build", TRIPLE)

    # Delete first: a build that fails must not leave the PREVIOUS image lying
    # around to be booted as if it were current. (Blade used to exit 0 on a
    # failed build, which is exactly how a stale image once passed this suite.)
    if os.path.isdir(out_dir):
        for stale in os.listdir(out_dir):
            if stale.endswith(".sosimg"):
                os.remove(os.path.join(out_dir, stale))

    _run([blade_bin, "build", "--force"], cwd=pkg_dir, env=_blade_env(clang))

    # The image is named for the PACKAGE, which need not match its directory.
    images = []
    if os.path.isdir(out_dir):
        images = [f for f in os.listdir(out_dir) if f.endswith(".sosimg")]
    if len(images) != 1:
        raise ToolError(f"expected exactly one .sosimg in {out_dir}, found {images}")
    return os.path.join(out_dir, images[0])


def _stitch_root_image(image, clang):
    """Assemble the `.incbin` stub that pulls `image` into `.payload`.

    The stub names `root.sosimg` and is assembled with `-I` pointing at the
    build directory, so one committed stub stitches whichever root image the
    case asked for.
    """
    staged = os.path.join(BUILD_DIR, "root.sosimg")
    shutil.copyfile(image, staged)
    stub_o = os.path.join(BUILD_DIR, "rootimg.o")
    _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
          "-nostdlib", "-I", BUILD_DIR, "-c",
          os.path.join(KERNEL_DIR, "rootimg.S"), "-o", stub_o])
    return stub_o


def _build_elf(case, shared_objs, lld, clang):
    """Compile + link one test case to an ELF; return its path.

    A case may name an extra `.S` payload, which lands in the `.payload` section
    virt.ld bounds — unit A's raw U-mode code, and from unit B on the `.incbin`
    stub that carries the root sosimg.
    """
    name = case["name"]
    obj = os.path.join(BUILD_DIR, f"{name}.o")
    elf = os.path.join(BUILD_DIR, f"{name}.elf")
    # design 135: `--no-hidden-alloc` rides along on every kernel build. The
    # kernel logs through the alloc-free formatting path already (design 137's
    # dogfood), so this costs nothing today and is what keeps it that way — an
    # interpolated log line or an escaping closure added later fails the gate
    # instead of quietly reaching for an allocator the kernel may not have.
    _run([sys.executable, SAWC, case["src"], "-o", obj,
          "--freestanding", "--no-hidden-alloc", "--target", TRIPLE,
          "--target-features", MFEATURES,
          "--module-path", CORE_MODULE,
          "--module-path", IMGFORMAT_MODULE,
          "--module-path", SOSRT_MODULE,
          "--module-path", SOSABI_MODULE])

    objs = list(shared_objs) + [obj]
    if case.get("asm"):
        payload_o = os.path.join(BUILD_DIR, f"{name}.payload.o")
        _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
              "-nostdlib", "-c", case["asm"], "-o", payload_o])
        objs.append(payload_o)
    if case.get("root_pkg"):
        objs.append(_stitch_root_image(case["_root_image"], clang))

    _run([lld, "-T", os.path.join(KERNEL_DIR, "virt.ld"), "--gc-sections",
          "-o", elf, *objs])
    return elf


def _run_qemu(qemu, elf):
    """Run the ELF under QEMU with a hard timeout.

    Returns (exit_status, stdout, timed_out). A timeout is a hang — the whole
    point of the trap stub is that faults never reach it.
    """
    try:
        proc = subprocess.run(
            [qemu, "-M", "virt", "-nographic", "-bios", "none", "-kernel", elf],
            capture_output=True, text=True, timeout=QEMU_TIMEOUT_S)
        return proc.returncode, proc.stdout, False
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or (e.stdout and e.stdout.decode()) or ""), True


def _check(case, status, out, timed_out):
    """Return (ok, reason). Validates UART output and exit status expectations."""
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
        for want in expected:
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


def main():
    qemu, lld, clang = _probe_tools()
    print(f"{BOLD}SOS QEMU tests{RESET} (riscv32 `virt`)")
    print(f"  qemu : {qemu}")
    print(f"  clang: {clang}")
    print(f"  lld  : {lld}\n")

    try:
        shared_objs = _build_shared(clang)
    except ToolError as e:
        print(f"{CROSS} failed to build the kernel HAL / runtime support\n{e}",
              file=sys.stderr)
        sys.exit(1)

    # Root packages are built by Blade, so build Blade first — but only if some
    # case actually needs one.
    root_pkgs = []
    for case in TEST_CASES:
        if case.get("root_pkg") and case["root_pkg"] not in root_pkgs:
            root_pkgs.append(case["root_pkg"])
    if root_pkgs:
        try:
            blade_bin = _build_blade(clang)
            print(f"{BOLD}building root images with blade{RESET}")
            images = {}
            for pkg in root_pkgs:
                images[pkg] = _build_root_image(blade_bin, pkg, clang)
                size = os.path.getsize(images[pkg])
                print(f"  {os.path.relpath(images[pkg], REPO_ROOT)}  ({size} bytes)")
            for case in TEST_CASES:
                if case.get("root_pkg"):
                    case["_root_image"] = images[case["root_pkg"]]
            print()
        except ToolError as e:
            print(f"{CROSS} failed to build a root image\n{e}", file=sys.stderr)
            sys.exit(1)

    passed = 0
    failed = 0
    for i, case in enumerate(TEST_CASES, 1):
        name = case["name"]
        try:
            elf = _build_elf(case, shared_objs, lld, clang)
        except ToolError as e:
            print(f"[{i}/{len(TEST_CASES)}] {CROSS} {name}  (build error)")
            for line in str(e).splitlines():
                print(f"    {line}")
            failed += 1
            continue
        status, out, timed_out = _run_qemu(qemu, elf)
        ok, reason = _check(case, status, out, timed_out)
        if ok:
            print(f"[{i}/{len(TEST_CASES)}] {CHECK} {name}")
            passed += 1
        else:
            print(f"[{i}/{len(TEST_CASES)}] {CROSS} {name}  ({reason})")
            failed += 1

    print()
    print("=" * 60)
    if failed == 0:
        print(f"{GREEN}{BOLD}ALL SOS TESTS PASSED{RESET} ({passed} passed)")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}SOS TESTS FAILED{RESET} ({passed} passed, {failed} failed)")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""SOS M0 QEMU test harness (design 112).

Builds and runs the freestanding SOS kernel under QEMU `virt` (riscv32) and
asserts its UART output and emulator exit status. This is the mechanical test
loop the kernel briefs build on — `make sos-test` green means "sawc-built code
boots, prints, and exits cleanly under QEMU".

Every kernel source builds under `--no-hidden-alloc` (design 135): a kernel is
the audience for that flag, so the gate carries it permanently and any
compiler-inserted allocation the source does not name breaks the build here
rather than shipping.

Pipeline per test case:
  1. sawc   : <src>.saw  -> <name>.o   (--freestanding --no-hidden-alloc
              --target riscv32-...)
  2. clang  : boot.S     -> boot.o     (shared; assembled once)
  3. clang  : rt.c       -> rt.o       (shared; runtime seams, compiled once)
  4. ld.lld : link with sos/kernel/virt.ld --gc-sections -> <name>.elf
  5. qemu   : run with a hard timeout; capture UART stdout + exit status

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
        "name": "umode_bad_syscall",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": os.path.join(TESTS_DIR, "payload_badcall.S"),
        "expect_out": "fault bad-syscall-number",
        "expect_clean_exit": False,
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
    probe_src = os.path.join(KERNEL_DIR, "boot.S")
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
    """Assemble boot.S and compile rt.c once; return (boot.o, rt.o)."""
    boot_o = os.path.join(BUILD_DIR, "boot.o")
    rt_o = os.path.join(BUILD_DIR, "rt.o")
    _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
          "-nostdlib", "-c", os.path.join(KERNEL_DIR, "boot.S"), "-o", boot_o])
    _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
          "-ffreestanding", "-fno-builtin", "-ffunction-sections", "-fdata-sections",
          "-nostdlib", "-O2", "-c", os.path.join(KERNEL_DIR, "rt.c"), "-o", rt_o])
    return boot_o, rt_o


def _build_elf(case, boot_o, rt_o, lld, clang):
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
          "--module-path", CORE_MODULE])

    objs = [boot_o, rt_o, obj]
    if case.get("asm"):
        payload_o = os.path.join(BUILD_DIR, f"{name}.payload.o")
        _run([clang, f"--target={TRIPLE}", f"-march={MARCH}", f"-mabi={MABI}",
              "-nostdlib", "-c", case["asm"], "-o", payload_o])
        objs.append(payload_o)

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
    return True, ""


def main():
    qemu, lld, clang = _probe_tools()
    print(f"{BOLD}SOS QEMU tests{RESET} (riscv32 `virt`)")
    print(f"  qemu : {qemu}")
    print(f"  clang: {clang}")
    print(f"  lld  : {lld}\n")

    try:
        boot_o, rt_o = _build_shared(clang)
    except ToolError as e:
        print(f"{CROSS} failed to build boot.S / rt.c\n{e}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    for i, case in enumerate(TEST_CASES, 1):
        name = case["name"]
        try:
            elf = _build_elf(case, boot_o, rt_o, lld, clang)
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

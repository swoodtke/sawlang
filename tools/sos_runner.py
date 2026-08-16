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
     clang  : support.c  -> support.o  (mem* + the atomic libcalls — the C that
                                        must stay C, compiled once)
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

# `ExitCode.ProcessFault` in sos/kernel/core/lib.saw: what the machine exits
# with when the kernel TERMINATES a process for a caller error it could have
# checked (design 178's faults ruling). Kept in step with that enum.
EXIT_PROCESS_FAULT = 5

# Root-server packages. These are real Blade packages built by Blade — the
# whole point of unit C is that root goes through the same package pipeline any
# SOS process will, not a bespoke rule in this file.
BLADE_DIR = os.path.join(REPO_ROOT, "blade")
TOML_SRC = os.path.join(REPO_ROOT, "libs", "toml", "src")
SEMVER_SRC = os.path.join(REPO_ROOT, "libs", "semver", "src")
ROOT_PKG = os.path.join(REPO_ROOT, "sos", "root")
FAULT_ROOT_PKG = os.path.join(TESTS_DIR, "faulting-root")
# design 178 M2 unit 2: three root servers that exercise Thread and Process
# objects. They are real Blade packages for the same reason sos/root is — a
# process that makes threads should go through the pipeline every SOS process
# goes through, and should reach the kernel through the `sos` module and never
# through an op number.
THREAD_BASICS_PKG = os.path.join(TESTS_DIR, "thread-basics")
THREAD_PREEMPT_PKG = os.path.join(TESTS_DIR, "thread-preempt")
# design 178 M2 unit 3: two more, for the Event and Waiter objects. Same
# reasoning — a process that makes Events reaches the kernel through the `sos`
# module and never through an op number, so the test is written the way a real
# one would be.
EVENT_BASICS_PKG = os.path.join(TESTS_DIR, "event-basics")
EVENT_WAKE_PKG = os.path.join(TESTS_DIR, "event-wake")
# rider 4: the one fault in this unit that a SAW process can reach, so the test
# is written the way a real process would be rather than as a payload.
EVENT_DUPKEY_PKG = os.path.join(TESTS_DIR, "event-dupkey")

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
        # The line `hal.irq_raise_selftest_line()` raises (design 178 M2 unit
        # 1). It is per-machine because WHAT a board can interrupt itself with
        # is: this one has no software trigger, so the HAL makes the console
        # interrupt, on the line this board wires it to.
        "selftest_line": 10,
    },
    {
        "name": "arm64",
        "triple": "aarch64-unknown-none-elf",
        "qemu": "qemu-system-aarch64",
        # `-cpu cortex-a53` (design 162 decision 3): ubiquitous, EL1
        # well-exercised. `-semihosting` is what makes SYS_EXIT carry a status
        # code — see sos/hal/arm64/kernel/sink.c for why not PSCI.
        # `gic-version=2` is PINNED rather than defaulted (design 178 M2 unit
        # 1): the HAL programs a v2 controller, which is what this machine has
        # given us so far, and a newer emulator changing its default would swap
        # the hardware under a kernel that cannot say so.
        "qemu_args": ["-M", "virt,gic-version=2", "-cpu", "cortex-a53",
                      "-semihosting"],
        # The base aarch64 triple already has everything this kernel uses, and
        # there is no ABI variant to select.
        "cc_args": [],
        "features": None,
        "hex_width": 16,
        "root_entry": 0x40200000,
        # This controller HAS a software trigger, so the selftest line is a
        # software-generated one and no device is involved.
        "selftest_line": 5,
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
        "zero": f"0x{0:0{width}x}",
        "one": f"0x{1:0{width}x}",
        "two": f"0x{2:0{width}x}",
        "three": f"0x{3:0{width}x}",
        "four": f"0x{4:0{width}x}",
        "five": f"0x{5:0{width}x}",
        "six": f"0x{6:0{width}x}",
        "seven": f"0x{7:0{width}x}",
        "prio": f"0x{0x01010100:0{width}x}",
        "irq_line": f"0x{arch['selftest_line']:0{width}x}",
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
    # Design 178 M2 unit 1 brought two more classes of machine name within
    # reach of the arch-free kernel — the interrupt controllers and the timers
    # — so the scan learns them at the same time as the code that could leak
    # them. Each is spelled tightly enough not to fire on English: `gic` alone
    # would match "magic", which the loader's own diagnostics say.
    "plic", "clint", "gicd", "gicc", "gicv", "sgir",
    "mtime", "cntp", "cntfrq", "sstc",
]

# A token that is BURIED IN A LONGER ENGLISH WORD is not a leak — and the note
# above turned out to be optimistic about how tight these spellings are. `plic`
# is inside "duplicate", "explicit", "implicit", "complicated" and "replica";
# design 178 M2 unit 3 rider 4 hit the first of those, and the check would
# otherwise have dictated the kernel's vocabulary, which is exactly backwards
# for a check that exists to police the kernel's DEPENDENCIES.
#
# THE RULE: a hit is suppressed only when the token has a letter on BOTH sides.
# That is deliberately weaker than a word boundary, because the real usages are
# prefixes and suffixes of longer identifiers — `mtimecmp`, `csrw`, `PLIC_BASE`,
# `gicd_ctlr`, `cntfrq_el0` — and requiring a boundary on both sides would miss
# every one of them. An arch token in the MIDDLE of an otherwise-alphabetic word
# is English; at either END of one it is an identifier.
def _is_english_embedding(line, token, at):
    before = line[at - 1] if at > 0 else ""
    after_index = at + len(token)
    after = line[after_index] if after_index < len(line) else ""
    return before.isalpha() and after.isalpha()

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
    {
        # design 158 unit 3: the in-process task dump, freestanding. The kernel
        # walks its OWN task slots through the in-binary backtrace table and
        # writes each parked task's logical stack to the serial port — the whole
        # reason the design exists, since a kernel has no debugger to attach and
        # no core to open. Both halves are asserted, in order: the explicit
        # `dump_tasks()` with its two-frame nest, then the panic line, then the
        # dump the PANIC PATH emits by itself. The nest is two frames deep since
        # design 187 closed DF-158e — a freestanding compile now embeds a nested
        # suspending callee exactly as a hosted one does, so the dump has a
        # logical stack to reconstruct rather than a single frame. It also
        # closed DF-158c, which had made this case arm64-only: an `@export`ed
        # `Int64`-returning seam came out `i32` on a 32-bit target, so the clock
        # stub and the executor's own `Int64` clock arithmetic disagreed and
        # LLVM rejected the module. BOTH arches run it now.
        "name": "task_dump",
        "src": os.path.join(TESTS_DIR, "taskdump.saw"),
        "csrc": "taskdump_stubs.c",
        "expect_out": ["saw tasks: 2 live (unsynchronized snapshot)",
                       "at taskdump.saw:93 in knap",
                       "at taskdump.saw:98 in ksleeper",
                       "panic at taskdump.saw:114: SOS task dump: deliberate panic",
                       "saw tasks: 1 live (as-of panic, unsynchronized)",
                       "at taskdump.saw:93 in knap",
                       "at taskdump.saw:98 in ksleeper"],
        "expect_clean_exit": False,
    },
    {
        # design 158 unit 3: the dump path on EVERY architecture — the table is
        # in the image, the walker links and runs freestanding, and a panic with
        # no live task still prints exactly its own message and nothing else.
        "name": "task_dump_empty",
        "src": os.path.join(TESTS_DIR, "taskdump_empty.saw"),
        "expect_out": ["saw tasks: none live",
                       "panic at taskdump_empty.saw:21: "
                       "SOS task dump: no tasks here"],
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
        # design 178's faults ruling (Aug 15), which REVERSED this case: a
        # caller's mistake is a FAULT, not a status. The payload makes a good
        # call (the '!' proves the round trip resumed) and then an op the
        # System object does not have, which terminates it — so the transcript
        # is the ruling in three lines, in order, and the exit status is the
        # kernel's own `ExitCode.ProcessFault` rather than anything the process
        # chose. The teardown line is what says the KERNEL stayed up to report.
        "name": "umode_bad_calls",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_badcall.S",
        "expect_out": ["SOS M1: entering U-mode", "!",
                       "SOS: process fault: bad op",
                       "SOS: process teardown handles={three} threads={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
    },
    # --- design 178 M2 unit 1: interrupts -----------------------------------
    # Three claims, one per case, and each is read from the ORDER of the
    # transcript rather than from any single line: a tick lands in the
    # arch-free hook once user mode is running; a tick that comes due in the
    # kernel is not taken there; and a device line goes round the interrupt
    # controller's claim/complete cycle. All three run the same spinning
    # payload, which shuts the machine down cleanly when it is done — so a
    # kernel that wedged in its handler shows up as a timeout, not a pass.
    {
        "name": "timer_tick",
        "src": os.path.join(TESTS_DIR, "timer.saw"),
        "asm": "payload_spin.S",
        # The tick count comes from the kernel's counter and the address from
        # the interrupted frame, so both halves of "a tick was taken from user
        # mode" are in the line. The address itself is the payload's and is not
        # asserted — what matters is that the kernel had already left.
        "expect_out": ["SOS M2: timer armed",
                       "SOS M2: entering U-mode",
                       "SOS: timer tick {one} at ",
                       "SOS: timer tick {two} at "],
        "expect_clean_exit": True,
    },
    {
        "name": "timer_masked_in_kernel",
        "src": os.path.join(TESTS_DIR, "timer_mask.saw"),
        "asm": "payload_spin.S",
        # design 178 D2. The middle line is the whole case: the kernel spun
        # until the timer was DUE, and the tick counter is still zero — so the
        # interrupt was pending and untaken while the kernel ran. The tick
        # arrives after the entry to user mode, and ordered matching is what
        # makes "after" an assertion.
        "expect_out": ["SOS M2: kernel section begin",
                       "SOS M2: kernel section end, timer expired, "
                       "ticks taken={zero}",
                       "SOS M2: entering U-mode",
                       "SOS: timer tick {one} at "],
        "expect_clean_exit": True,
    },
    {
        "name": "external_irq",
        "src": os.path.join(TESTS_DIR, "extirq.saw"),
        "asm": "payload_spin.S",
        # The line is raised in the kernel and serviced in user mode, which is
        # the same masking claim the case above makes about the timer — and
        # the line number crossing from the raise to the hook is what says the
        # controller's claim gave back the line that was raised.
        "expect_out": ["SOS M2: raised external irq {irq_line}",
                       "SOS M2: entering U-mode",
                       "SOS: external irq {irq_line}"],
        "expect_clean_exit": True,
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
                       # The typed SAW altitude: a method on a handle.
                       "SOS root: hello from U-mode via a System op",
                       # The RUNTIME SEAM altitude, end to end: `print` ->
                       # `__saw_rt_write` (sosrt) -> `sos_rt_write` (sysapi) ->
                       # `sos_system_debug_print` -> `sos_syscall1` -> `ecall`.
                       # Every hop but the last is Saw since design 172 part 2;
                       # before it, the middle of that chain was C and this line
                       # was described as exercising the C altitude. It no
                       # longer does — see DF-172i.
                       # Also design 137 formatting with no allocator present.
                       "SOS root: boot handle 1"],
        "expect_clean_exit": True,
    },
    # --- design 178 M2 unit 2: Thread and Process objects + the scheduler ----
    # Three claims, one per case, and the three root servers are real Blade
    # packages that reach the kernel through the `sos` module — so what is under
    # test is the object surface a process actually has, not an op number
    # written into an assembler payload.
    {
        # (a) + (c): create two threads, start them, join them for THEIR OWN
        # exit values — and, in between, cooperative alternation. The kernel
        # here arms NO timer, so nothing can take the processor away and the
        # eight-character run is exactly eight `yield` calls in a row. That one
        # substring is the strongest form the claim has: any missed switch, any
        # extra one, and it is not `ABABABAB`.
        "name": "thread_basics",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": THREAD_BASICS_PKG,
        "expect_out": ["{banner}",
                       "SOS threads: two workers, status word 0",
                       "ABABABAB",
                       "SOS threads: joined a=11 b=22",
                       # The ratified Process teardown, reported: three handles
                       # (System, Process, the initial Thread) plus the two the
                       # process made, and three thread slots. The two trailing
                       # counts arrived with M2 unit 3 and are asserted here too
                       # — a process that made no Event and no Waiter must
                       # report none, which is the null row of the same claim
                       # the Event cases below make with real objects.
                       "SOS: process teardown handles={five} threads={three} "
                       "events={zero} waiters={zero}"],
        "expect_clean_exit": True,
    },
    {
        # (b) PREEMPTION. The same shape with the yields REMOVED and the timer
        # armed: two workers that print and then spin, making no call that could
        # give the processor up. Every alternation in the transcript is the
        # scheduler taking it away at a tick, which is the whole of design 178
        # D3 that a cooperative test cannot show.
        #
        # The root's own banner is deliberately NOT asserted: it is written a
        # byte per syscall while the kernel is still narrating its first ticks,
        # so the two interleave mid-word on the console. That is real and
        # harmless — a shared serial port with no locking — but it is not
        # something a substring can match. The tick narration stops after four,
        # so everything below is written in the quiet that follows.
        "name": "thread_preempt",
        "src": os.path.join(TESTS_DIR, "threads_timer.saw"),
        "root_pkg": THREAD_PREEMPT_PKG,
        #
        # THE ALTERNATION IS ASSERTED AS DIRECTION CHANGES, not as a fixed
        # sequence, and that is not a weakening. WHICH worker runs first depends
        # on where the first tick lands relative to the two `start` calls, so a
        # sequence starting `A` fails half the time on a claim it was never
        # making. `AB` then `BA` then `AB` says the processor crossed between
        # the two threads at least three times, whoever went first — and a run
        # with no preemption at all reads `AAAAAAAABBBBBBBB`, which has one `AB`
        # in it and no `BA` after it.
        "expect_out": ["SOS M2: preemptive kernel up on",
                       "AB", "BA", "AB",
                       "SOS preempt: joined a=33 b=44"],
        "expect_clean_exit": True,
    },
    {
        # (d) THE FAULTS RULING, on a handle the process never held. It ends the
        # process; the kernel reports the reason, reports the teardown, and
        # stops the machine with its OWN exit code.
        #
        # IT IS A PAYLOAD RATHER THAN A ROOT SERVER, and that is the second
        # review round showing up in the harness: the `sos` module's typed layer
        # has no way to build a `Thread` from a word, so a handle the process
        # was never given is not a thing a Saw program can spell. The test of
        # the kernel's validation therefore lives at the altitude where raw
        # handles legitimately live, beside `umode_bad_calls`.
        "name": "umode_bad_handle",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_badhandle.S",
        "expect_out": ["SOS M1: entering U-mode",
                       "SOS: process fault: bad handle",
                       "SOS: process teardown handles={three} threads={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
    },
    # --- design 178 M2 unit 3: the Event and Waiter objects -----------------
    # Three claims, and the split between the first two is deliberate: what an
    # Event ACCUMULATES and what a Waiter REPORTS is one question, and whether a
    # wait PARKS is another. Testing them together would let a scheduling bug
    # hide behind an accumulation bug and the other way round.
    {
        # Level-triggered attach (§2.2), OR and saturating-sum accumulation
        # (§2.4), and the key identifying WHICH of several attachments became
        # ready. One thread, no timer: every wait here answers immediately, and
        # a wait that did not would park the only thread in the system, which
        # the kernel reports as the deadlock it is — so a regression fails in
        # microseconds rather than at the timeout.
        "name": "event_basics",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": EVENT_BASICS_PKG,
        "expect_out": ["{banner}",
                       # The signal came BEFORE the wait and was not lost.
                       # `at-wait` is read out of the RECORD the kernel copied
                       # into the process's memory and `drained` out of the
                       # following `receive`; they agree on every line below,
                       # which is what says the record's payload is the real
                       # accumulated word rather than a readiness flag.
                       "SOS events: signal-then-wait key=11 at-wait=4 drained=4",
                       # A second attachment on the same Waiter, told apart by
                       # its key alone.
                       "SOS events: second key=22 at-wait=8 drained=8",
                       # 1 | 2 | 1 is 3, which is what a flag set answers and a
                       # counter does not.
                       "SOS events: or key=11 at-wait=3 drained=3",
                       # Removed from the wait set, still an Event.
                       "SOS events: detached word=8",
                       # Five signals of one, counted; then two of the largest
                       # word there is, which SATURATE instead of wrapping back
                       # through zero — the value that means "not ready".
                       "SOS events: counting key=33 at-wait=5 drained=5 "
                       "saturated=1",
                       "SOS events: done",
                       # Teardown reports the two new object kinds: three events
                       # and one waiter, beside seven handles and one thread.
                       "SOS: process teardown handles={seven} threads={one} "
                       "events={three} waiters={one}"],
        "expect_clean_exit": True,
    },
    {
        # THE PARK AND THE WAKE. Read from the ORDER: the middle line is written
        # by a thread that could only have run because the first one blocked,
        # since this kernel arms no timer and `start` does not switch. The line
        # after it carries the record back into the woken thread's own stack
        # buffer, written by the SIGNALLING thread through the copy-out funnel —
        # unit 2's block-on-wait substrate answering a syscall it did not answer
        # when the call was made.
        "name": "event_wake",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": EVENT_WAKE_PKG,
        "expect_out": ["{banner}",
                       "SOS wake: worker started, parking",
                       "SOS wake: worker signalling",
                       # The two numbers DIFFER on purpose and that gap is the
                       # third claim: the worker signals five times, the FIRST
                       # wakes the parked thread, so the record it copied out is
                       # a SNAPSHOT reading 1 — and the other four land while
                       # the woken thread is merely runnable, so the `receive`
                       # after it drains 5. The record says what the wait was
                       # woken for; `receive` says what has accumulated.
                       "SOS wake: woke key=77 at-wait=1 drained=5",
                       "SOS wake: joined worker=99"],
        "expect_clean_exit": True,
    },
    {
        # THE FAULT CASE: attaching something that is not a waitable. A payload
        # rather than a root server, for the reason `umode_bad_handle` is one —
        # `Waiter.add` takes an `&Event` and the typed layer has no way to build
        # one from a word, so this is not a thing a Saw process can spell. The
        # teardown line is the second half: the Waiter the process DID make goes
        # back to the kernel's slab.
        "name": "umode_not_waitable",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_notwaitable.S",
        "expect_out": ["SOS M1: entering U-mode",
                       "SOS: process fault: not a waitable",
                       "SOS: process teardown handles={four} threads={one} "
                       "events={zero} waiters={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
    },
    {
        # KEYS ARE UNIQUE PER WAITER (rider 4). Two Events, one key, and the
        # second `add` terminates the process — the invariant that `remove(key)`
        # and the wait record both rest on.
        #
        # A ROOT SERVER RATHER THAN A PAYLOAD, and it is the only fault case in
        # this unit that can be one: the typed layer makes the others
        # unspellable (no handle you were not given, no buffer you name), while
        # a duplicate key is two real Events and two of the caller's own words,
        # which no type can catch. So the check is the kernel's, and the test
        # lives where a real process would hit it.
        "name": "event_dupkey",
        "src": os.path.join(KERNEL_DIR, "main.saw"),
        "root_pkg": EVENT_DUPKEY_PKG,
        "expect_out": ["{banner}",
                       "SOS dupkey: first attach ok",
                       "SOS: process fault: an attachment already uses that key",
                       # Six handles — the three it was given plus a waiter and
                       # two events — and both events and the waiter still go
                       # back to their slabs.
                       "SOS: process teardown handles={six} threads={one} "
                       "events={two} waiters={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
    },
    # THE COPY-OUT FUNNEL'S TWO REJECTION ROWS. `Waiter.Wait` answers by writing
    # a record into memory the caller supplies — SOS's first
    # kernel-writes-userspace path — and the funnel that validates the
    # destination is the only door. One case per row, because a funnel with a
    # matrix owes its tests row by row.
    #
    # Both are payloads for the reason `umode_bad_handle` is one: the typed
    # `Waiter.wait` supplies its own buffer out of its frame and never lets a
    # caller name one, so neither mistake is a thing a Saw process can spell.
    {
        # ROW 1 — outside the process's writable memory. This payload has NO
        # writable grant at all (umode.saw gives it its own bytes read+execute),
        # so every address is outside its window and zero says so plainly.
        "name": "umode_bad_wait_buffer",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_badbuffer.S",
        "expect_out": ["SOS M1: entering U-mode",
                       "SOS: process fault: buffer is not in the process's "
                       "writable memory",
                       "SOS: process teardown handles={four} threads={one} "
                       "events={zero} waiters={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
    },
    {
        # ROW 2 — not word-aligned. The kernel writes machine words, so this is
        # refused before the range is even looked at; the two cases are told
        # apart by that ORDER, since this payload's address would fail the range
        # check too.
        "name": "umode_misaligned_wait_buffer",
        "src": os.path.join(TESTS_DIR, "umode.saw"),
        "asm": "payload_misalignbuf.S",
        "expect_out": ["SOS M1: entering U-mode",
                       "SOS: process fault: buffer is not word-aligned",
                       "SOS: process teardown handles={four} threads={one} "
                       "events={zero} waiters={one}"],
        "expect_clean_exit": False,
        "expect_status": EXIT_PROCESS_FAULT,
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
                        at = low.find(word)
                        while at >= 0:
                            if not _is_english_embedding(low, word, at):
                                rel = os.path.relpath(src, REPO_ROOT)
                                bad.append(f"{rel}:{lineno}: {word!r} in: "
                                           f"{line.strip()}")
                                break
                            at = low.find(word, at + 1)
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
    board sinks, the protection primitive) plus the shared C floor every SOS
    build links — the same `support.c` a root package names in its
    `[sos.<triple>] native`, which since design 172 part 2 is `mem*` and the
    atomic libcalls and nothing else. The runtime seams it used to carry are
    Saw, and reach the image through `--module-path sosrt=` below.
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
    # design 158: a case may bring ONE C file of its own, for the bodies Saw
    # cannot write (a raw C function pointer, DF-113b). Per-case rather than in
    # the shared `support.c` every image links: a stand-in that satisfies one
    # test must not satisfy another kernel's accidental reference to a facility
    # that is not there.
    if case.get("csrc"):
        c_src = os.path.join(TESTS_DIR, case["csrc"])
        c_obj = os.path.join(dirs["build"], f"{name}.stubs.o")
        _run([clang, f"--target={arch['triple']}", *arch["cc_args"],
              "-nostdlib", "-ffreestanding", "-O2", "-c", c_src, "-o", c_obj])
        objs.append(c_obj)
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
        # design 158: matched IN ORDER — each expectation starts where the
        # previous one ended. A console transcript is a sequence, and a case
        # like the task dump is asserting that the dump comes AFTER the panic
        # line, which an unordered `in` cannot see. Every list already reads in
        # output order, so this only adds what they were already claiming.
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

    # design 158: a case may name the architectures it applies to. The default
    # is EVERY architecture and stays that way — an arch list is a claim that
    # the case is about something arch-specific, or that it is blocked on one,
    # and each one says which in a comment beside it.
    cases = [c for c in TEST_CASES
             if arch["name"] in c.get("arches", (arch["name"],))]
    passed = 0
    failed = 0
    for i, case in enumerate(cases, 1):
        name = case["name"]
        try:
            elf = _build_elf(case, arch, shared_objs, lld, clang)
        except ToolError as e:
            print(f"[{i}/{len(cases)}] {CROSS} {name}  (build error)")
            for line in str(e).splitlines():
                print(f"    {line}")
            failed += 1
            continue
        status, out, timed_out = _run_qemu(qemu, arch, elf)
        ok, reason = _check(case, arch, status, out, timed_out)
        if ok:
            print(f"[{i}/{len(cases)}] {CHECK} {name}")
            passed += 1
        else:
            print(f"[{i}/{len(cases)}] {CROSS} {name}  ({reason})")
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

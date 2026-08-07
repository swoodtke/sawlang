#!/usr/bin/env python3
"""
Saw Language Test Runner

Runs all .saw example files and verifies they behave as expected.
Test expectations are specified via comments in the source files:

    // EXPECT: success        - Should compile and run without error
    // EXPECT: error          - Should fail to compile
    // EXPECT: panic          - Should compile but panic at runtime
    // EXPECT: object         - Should compile to an object file; do NOT run it
                                (for --freestanding / -c compiles). Inspect the
                                object's symbols with EXPECT-SYMBOL-UNDEFINED.
    // EXPECT-SYMBOL-UNDEFINED: sym  - `nm` shows `sym` as an UNDEFINED (external)
                                symbol in the compiled object — never a local
                                definition. Used to prove the freestanding profile
                                still EXTERNS the runtime seams and links no runtime
                                (design 113 / 113b negative test).
    // EXPECT-OBJECT-MAX-BYTES: n  - The compiled object is at most `n` bytes.
                                A size assertion, not a symbol one: it is how a
                                static that must cost NO IMAGE BYTES is proven to
                                cost none (design 149 unit b — an all-zero
                                initializer lands in zerofill storage). Declare a
                                region far larger than the bound and the check
                                fails by the width of the region if it ever
                                regresses into a data section.
    // EXPECT: docs           - Compile with `// COMPILE-FLAGS: --emit-docs` and
                                compare the COMPILER's stdout (the design-121
                                documentation JSON) against EXPECT-OUTPUT; never
                                run anything. Lines are compared with leading and
                                trailing whitespace stripped, since the directive
                                comments cannot carry the JSON's indentation.
    // EXPECT: skip           - Skip this file (library modules, etc.)
    // EXPECT-OUTPUT:         - Next lines are expected stdout (until next directive or code)
    // some output
    // more output
    // EXPECT-ERROR-CONTAINS: text  - Error message should contain "text"
    // EXPECT-PANIC-CONTAINS: text  - Panic message should contain "text"
    // EXPECT-WARNING-CONTAINS: text - Compiler output should contain "text"
                                (design 150: warnings are reported on the
                                SUCCESS path and never affect the exit code,
                                so EXPECT-ERROR-CONTAINS cannot see one)
    // EXPECT-NO-WARNINGS    - The compile emits no warning at all — how a
                                `-W` category's SILENCE without its flag is
                                pinned
    // XFAIL: reason         - Known-broken test; still runs, but a failure is
                              reported as xfail instead of breaking the build.
                              Keep the EXPECT directives above accurate: if the
                              test starts passing it is reported as XPASS and
                              fails the run, prompting you to drop the marker.
"""

import os
import sys
import json
import signal
import subprocess
import itertools
import time
import io
import copy
import collections
import contextlib
import multiprocessing
import multiprocessing.connection
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


class ExpectType(Enum):
    SUCCESS = "success"
    ERROR = "error"
    PANIC = "panic"  # Runtime panic (compiles but aborts at runtime)
    OBJECT = "object"  # Compile to a .o and inspect symbols; do not run
    DOCS = "docs"  # Compare the compiler's --emit-docs JSON; do not run


class TestStatus(Enum):
    """Outcome of a test, after accounting for any XFAIL marker."""
    PASS = "pass"
    FAIL = "fail"
    XFAIL = "xfail"   # Marked XFAIL and did fail - expected, does not break the build
    XPASS = "xpass"   # Marked XFAIL but passed - the marker is now stale

    @property
    def is_ok(self) -> bool:
        """Whether this outcome should leave the build green."""
        return self in (TestStatus.PASS, TestStatus.XFAIL)


@dataclass
class TestCase:
    """Represents a single test case"""
    path: Path
    name: str
    expect_type: Optional[ExpectType]  # None if not specified
    expected_output: List[str]
    expected_error_contains: List[str]
    expected_panic_contains: List[str]  # For panic tests
    xfail_reason: Optional[str] = None  # Set by '// XFAIL: reason'
    compile_flags: List[str] = None  # Extra sawc flags from '// COMPILE-FLAGS:'
    expected_undefined_symbols: List[str] = None  # '// EXPECT-SYMBOL-UNDEFINED:'
    object_max_bytes: Optional[int] = None  # '// EXPECT-OBJECT-MAX-BYTES:'
    # design 150: compiler WARNINGS, which are reported on the SUCCESS path and
    # never affect the exit code — so no existing directive can see one.
    expected_warning_contains: List[str] = None  # '// EXPECT-WARNING-CONTAINS:'
    expect_no_warnings: bool = False  # '// EXPECT-NO-WARNINGS'
    out_name: Optional[str] = None  # unique build-output stem; see `binary_stem`

    @property
    def binary_stem(self) -> str:
        """The name this test's build products get under `.build/`.

        `name` (the file stem) is NOT unique: `examples/int_types.saw` and
        `examples/ffi/int_types.saw` share one. Two tests writing `.build/foo`,
        `.build/foo.o` and `.build/foo.ll` concurrently race over all three —
        and once compilation is a separate PHASE from execution, the second
        compile simply overwrites the first and both tests execute the same
        binary. `discover_tests` therefore hands every test a stem derived from
        its path relative to `examples/` (`ffi/int_types` -> `ffi_int_types`),
        which leaves the common case — a test directly in `examples/` — spelled
        exactly as before.
        """
        return self.out_name or self.name


class Colors:
    """ANSI color codes"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


STATUS_SYMBOLS = {
    TestStatus.PASS: f"{Colors.GREEN}✓{Colors.RESET}",
    TestStatus.FAIL: f"{Colors.RED}✗{Colors.RESET}",
    TestStatus.XFAIL: f"{Colors.YELLOW}x{Colors.RESET}",
    TestStatus.XPASS: f"{Colors.RED}!{Colors.RESET}",
}

# Marker for a test that compiled and is queued for execution. It is not a
# verdict — that comes when the binary runs.
COMPILED_SYMBOL = f"{Colors.DIM}·{Colors.RESET}"


def parse_test_metadata(file_path: Path) -> Optional[TestCase]:
    """Parse test metadata from comments in a .saw file.

    Returns None for files marked with '// EXPECT: skip' (library modules, etc.)
    """
    name = file_path.stem
    expect_type = None  # Must be explicitly set
    expected_output = []
    expected_error_contains = []
    expected_panic_contains = []
    xfail_reason = None
    compile_flags = []
    expected_undefined_symbols = []
    object_max_bytes = None
    expected_warning_contains = []
    expect_no_warnings = False

    with open(file_path, 'r') as f:
        in_output_block = False
        for line in f:
            line = line.rstrip('\n')

            # Stop parsing when we hit non-comment code
            if line and not line.strip().startswith('//'):
                break

            # Parse directives
            if '// EXPECT:' in line:
                directive = line.split('// EXPECT:')[1].strip()
                if directive == 'success':
                    expect_type = ExpectType.SUCCESS
                elif directive == 'error':
                    expect_type = ExpectType.ERROR
                elif directive == 'panic':
                    expect_type = ExpectType.PANIC
                elif directive == 'object':
                    expect_type = ExpectType.OBJECT
                elif directive == 'docs':
                    expect_type = ExpectType.DOCS
                elif directive == 'skip':
                    return None  # Skip this file entirely
                in_output_block = False

            elif '// EXPECT-SYMBOL-UNDEFINED:' in line:
                sym = line.split('// EXPECT-SYMBOL-UNDEFINED:')[1].strip()
                if sym:
                    expected_undefined_symbols.append(sym)
                in_output_block = False

            elif '// EXPECT-OBJECT-MAX-BYTES:' in line:
                raw = line.split('// EXPECT-OBJECT-MAX-BYTES:')[1].strip()
                object_max_bytes = int(raw.replace('_', ''))
                in_output_block = False

            elif '// EXPECT-OUTPUT:' in line:
                in_output_block = True
                # Check if output is on the same line
                rest = line.split('// EXPECT-OUTPUT:')[1].strip()
                if rest:
                    expected_output.append(rest)

            elif '// EXPECT-ERROR-CONTAINS:' in line:
                error_text = line.split('// EXPECT-ERROR-CONTAINS:')[1].strip()
                expected_error_contains.append(error_text)
                in_output_block = False

            elif '// EXPECT-PANIC-CONTAINS:' in line:
                panic_text = line.split('// EXPECT-PANIC-CONTAINS:')[1].strip()
                expected_panic_contains.append(panic_text)
                in_output_block = False

            elif '// EXPECT-WARNING-CONTAINS:' in line:
                warn_text = line.split('// EXPECT-WARNING-CONTAINS:')[1].strip()
                expected_warning_contains.append(warn_text)
                in_output_block = False

            elif '// EXPECT-NO-WARNINGS' in line:
                expect_no_warnings = True
                in_output_block = False

            elif '// XFAIL:' in line:
                xfail_reason = line.split('// XFAIL:')[1].strip()
                in_output_block = False

            elif '// COMPILE-FLAGS:' in line:
                # Extra flags passed to sawc for this test. `{TESTDIR}` expands
                # to the directory containing the test file (for --module-path).
                raw = line.split('// COMPILE-FLAGS:')[1].strip()
                raw = raw.replace('{TESTDIR}', str(file_path.parent))
                compile_flags = raw.split()
                in_output_block = False

            elif in_output_block:
                if line.strip().startswith('//'):
                    # Continuation of output block
                    output_line = line.strip()[2:].strip()
                    if output_line or expected_output:  # Allow empty lines in output
                        expected_output.append(output_line)
                elif line.strip() == '':
                    # Blank line ends output block
                    in_output_block = False

    return TestCase(
        path=file_path,
        name=name,
        expect_type=expect_type,
        expected_output=expected_output,
        expected_error_contains=expected_error_contains,
        expected_panic_contains=expected_panic_contains,
        xfail_reason=xfail_reason,
        compile_flags=compile_flags,
        expected_undefined_symbols=expected_undefined_symbols,
        object_max_bytes=object_max_bytes,
        expected_warning_contains=expected_warning_contains,
        expect_no_warnings=expect_no_warnings
    )


def compile_saw_file(file_path: Path, output_path: Path,
                     compile_flags: Optional[List[str]] = None) -> tuple[bool, str, str]:
    """
    Compile a .saw file using sawc.py

    Returns: (success, stdout, stderr)
    """
    sawc_path = Path(__file__).parent / 'sawc' / 'sawc.py'
    cmd = [sys.executable, str(sawc_path), str(file_path), '-o', str(output_path)]
    if compile_flags:
        cmd.extend(compile_flags)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Compilation timed out"
    except Exception as e:
        return False, "", f"Failed to run compiler: {e}"


def emit_docs_file(file_path: Path,
                   compile_flags: Optional[List[str]] = None) -> tuple[bool, str, str]:
    """Run sawc with the test's flags and NO `-o`, so `--emit-docs` writes its
    JSON to stdout instead of a file (design 121).

    Returns: (success, stdout, stderr)
    """
    sawc_path = Path(__file__).parent / 'sawc' / 'sawc.py'
    cmd = [sys.executable, str(sawc_path), str(file_path)]
    if compile_flags:
        cmd.extend(compile_flags)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Documentation extraction timed out"
    except Exception as e:
        return False, "", f"Failed to run compiler: {e}"


# ===========================================================================
# In-process compilation (design 115).
#
# Spawning a fresh `sawc.py` subprocess per test repeats ~250 ms of FIXED
# bootstrap overhead every time — Python startup, the llvmlite/sawc imports,
# and (the dominant slice) rebuilding the builtin + std namespace. A persistent
# worker PROCESS imports sawc once, builds that namespace once, and then invokes
# the compiler in-process via `compile_saw()` for its share of tests. Only
# compiler BOOTSTRAP is amortized: each test still produces its own binary and
# still RUNS it as a separate, timeout-and-process-group-guarded subprocess
# (see run_executable), so execution isolation is unchanged.
#
# Correctness rests on two things audited for design 115:
#   * the compiler is re-entrant in one long-lived process — a fresh
#     TypeChecker/CodeGenerator per compile, and codegen now isolates each
#     compile in its own llvmlite `ir.Context` (the identified-type registry
#     was the one true global leak);
#   * the builtin namespace is rebuilt ONCE per worker and deep-copied per
#     compile (measured ~2.4x cheaper than re-parsing+re-checking std, and
#     bit-identical — the full suite is diffed against --subprocess).
# ===========================================================================

_SAWC = None                 # the imported `sawc` module (per worker process)
_WORKER_VERBOSE = False


def _install_builtin_cache(sawc_mod):
    """Monkeypatch `sawc.build_builtin_namespace` so the (expensive) builtin +
    std parse/type-check happens ONCE per worker; every compile gets a fresh
    deep copy of that result.

    `build_builtin_namespace` returns `(builtin_ast, builtin_ns)` whose namespace
    shares AST-node identity with the ast (the ns points at the same decl
    nodes). Both are then mutated downstream — type-checking mutates namespaces,
    codegen annotates AST nodes — so a compile needs its OWN copies. Deep-copying
    the PAIR together (one memo) preserves that shared-identity invariant while
    isolating each compile. The cache is keyed on the two flags that change what
    gets loaded (freestanding drops hosted std; runtime-build loads no std) plus
    the target triple, which since DF-137d changes what the checked result MEANS:
    platform `Int`/`UInt` are pointer-width, so a literal std accepts for a
    64-bit host can be a range error for riscv32.
    """
    orig = sawc_mod.build_builtin_namespace
    cache = {}

    def cached(verbose=False, freestanding=False, runtime_build=False,
               builtin_ast=None, target_triple=None):
        # design 146: a re-entry hands its own already-parsed builtin AST back —
        # the one a source-level transform just rewrote. That AST is the program's
        # std, so check it rather than serving a pristine copy from the cache.
        if builtin_ast is not None:
            return orig(verbose, freestanding, runtime_build,
                        builtin_ast=builtin_ast, target_triple=target_triple)
        key = (freestanding, runtime_build, target_triple)
        if key not in cache:
            cache[key] = orig(verbose, freestanding, runtime_build,
                              target_triple=target_triple)
        return copy.deepcopy(cache[key])

    sawc_mod.build_builtin_namespace = cached


def _init_in_process(verbose: bool = False):
    """Import sawc into THIS process and install the builtin-namespace cache.

    Used both as the multiprocessing.Pool initializer (once per worker) and, for
    --sequential, directly in the main process.
    """
    global _SAWC, _WORKER_VERBOSE
    _WORKER_VERBOSE = verbose
    if _SAWC is None:
        sawc_dir = str(Path(__file__).parent / 'sawc')
        if sawc_dir not in sys.path:
            sys.path.insert(0, sawc_dir)
        import sawc as _s
        _SAWC = _s
        _install_builtin_cache(_s)


def _parse_compile_flags(flags: List[str]):
    """Translate a test's `// COMPILE-FLAGS:` list into `compile_saw()` kwargs.

    Mirrors the subset of sawc's own CLI handling that any test uses. Returns
    None for a flag the in-process path does not model, so the caller can fall
    back to a faithful subprocess compile rather than silently diverge.
    """
    kwargs = {'object_only': False, 'freestanding': False, 'runtime_build': False,
              'runtime_provider': False, 'target_triple': None, 'module_paths': {}}
    i, n = 0, len(flags)
    while i < n:
        f = flags[i]
        if f == '-c':
            kwargs['object_only'] = True
        elif f == '--freestanding':
            kwargs['freestanding'] = True
        elif f == '--runtime-build':
            kwargs['runtime_build'] = True
        elif f == '--runtime-provider':
            kwargs['runtime_provider'] = True
        elif f == '--target':
            i += 1
            if i >= n:
                return None
            kwargs['target_triple'] = flags[i]
        elif f == '--module-path':
            i += 1
            if i >= n or '=' not in flags[i]:
                return None
            name, _, d = flags[i].partition('=')
            name, d = name.strip(), d.strip()
            if not name or not d:
                return None
            kwargs['module_paths'][name] = d
        else:
            return None  # unmodeled flag -> caller falls back to subprocess
        i += 1
    return kwargs


def compile_saw_in_process(file_path: Path, output_path: Path,
                           compile_flags: Optional[List[str]] = None
                           ) -> tuple[bool, str, str]:
    """Compile `file_path` in this process via the cached `compile_saw()`.

    Returns `(success, stdout, stderr)` with the SAME shape as
    `compile_saw_file`. All compiler output (stdout + the diagnostic reporter's
    stderr) is captured into the stderr slot: the reporter and every `error:`
    line render unconditional ANSI text (no isatty gating), so the captured text
    is byte-identical to what the CLI subprocess would emit — the invariant that
    lets error tests (examples/errors/) run in-process without losing assertion
    fidelity. `compile_saw` signals failure by `sys.exit(1)` (parse/type/codegen
    errors) which surfaces here as SystemExit.
    """
    kwargs = _parse_compile_flags(compile_flags or [])
    if kwargs is None:
        # A flag the in-process path does not model: compile via subprocess so
        # the result is exactly the CLI's, never a silent divergence.
        return compile_saw_file(file_path, output_path, compile_flags)

    buf = io.StringIO()
    ok = True
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            _SAWC.compile_saw(str(file_path), str(output_path), verbose=False,
                              **kwargs)
        except SystemExit as e:
            ok = e.code in (None, 0)
        except Exception as e:  # a compiler bug: fail the test, don't kill the worker
            ok = False
            print(f"\033[1;31merror\033[0m: internal compiler error: {e}",
                  file=sys.stderr)
    return ok, "", buf.getvalue()


# ---------------------------------------------------------------------------
# Writing build products (DF-149b backstop (a): write elsewhere, rename in).
# ---------------------------------------------------------------------------

# Everything a compile can leave beside its output path: the `.ll` IR sidecar
# (at `<out>.ll` in-process, at `<out>.o.ll` when the CLI appended `.o` to the
# output path first), the object file, and the linked executable (no suffix).
_PRODUCT_SUFFIXES = ('.ll', '.o.ll', '.o', '')

_TMP_PREFIX = '.tmp-'
_tmp_counter = itertools.count()


def compile_into_place(compile_fn, test: TestCase, exe_path: Path
                       ) -> tuple[bool, str, str, set]:
    """Compile `test` to a UNIQUE temporary path, then rename its products onto
    `exe_path`. Returns the compiler's `(success, stdout, stderr)` unchanged,
    plus the set of product suffixes THIS compile placed (`''` is the
    executable, `'.o'` the object). The caller needs that set rather than a
    `Path.exists()` check, which a leftover binary from an earlier run would
    satisfy just as well.

    DF-149b backstop (a). A binary written under the very path it is then
    exec'd from can be exec'd while the kernel still holds an unsettled
    code-signature judgement for that path's vnode; on macOS/arm64 that
    surfaces as an immediate SIGTRAP with no output at all. Writing to a fresh
    name and renaming means the path a test execs is always a vnode the kernel
    has never judged before. `os.replace` is atomic within a directory, so the
    final path holds either the previous binary or the whole new one — never a
    partially written image.
    """
    tmp = exe_path.with_name(
        f"{_TMP_PREFIX}{os.getpid()}-{next(_tmp_counter)}-{exe_path.name}")
    ok, out, err = compile_fn(test.path, tmp, test.compile_flags)

    placed = set()
    for suffix in _PRODUCT_SUFFIXES:
        src = Path(str(tmp) + suffix)
        if not src.exists():
            continue
        if ok:
            os.replace(src, str(exe_path) + suffix)
            placed.add(suffix)
        else:
            # A failed compile's leftovers are noise, and a half-built binary
            # must never be left where a later phase would try to execute it.
            try:
                src.unlink()
            except OSError:
                pass

    if '' not in placed:
        # This compile produced no executable. Anything already sitting at that
        # path is a stranded binary from an earlier run, and phase 2 executing
        # it would report a verdict about code nobody just compiled.
        try:
            exe_path.unlink()
        except OSError:
            pass

    return ok, out, err, placed


def sweep_stale_temp_products(build_dir: Path) -> None:
    """Delete compile products stranded under `.tmp-…` by an interrupted run."""
    if not build_dir.is_dir():
        return
    for entry in build_dir.iterdir():
        if entry.name.startswith(_TMP_PREFIX) and entry.is_file():
            try:
                entry.unlink()
            except OSError:
                pass


# Hard wall-clock cap on a single test's RUN phase. Generous vs. the
# ~seconds a real test takes; its whole job is to stop a test that HANGS
# AT RUNTIME (a live hazard for every concurrency brief) from wedging the
# whole suite. On expiry the process GROUP is killed and the test is
# recorded FAILED (timeout) — the runner never hangs.
RUN_TIMEOUT_SECS = 30


def _run_once(exe_path: Path, timeout: float) -> tuple[Optional[int], str, str]:
    """One execution attempt under a hard, process-group-aware timeout.

    The child is launched in its OWN process group (start_new_session=True) so
    that on timeout we can SIGKILL the entire group — not just the direct
    child. This matters because a hung test may have spawned OS threads or
    child processes that inherited the stdout/stderr pipes; killing only the
    parent would leave those holding the pipe open and `communicate()` would
    block forever, wedging the runner. Killing the group guarantees the pipes
    close and the runner moves on.

    Returns `(returncode, stdout, stderr)` exactly as the child left them, with
    nothing synthesized — the caller needs to tell a child that died silently
    from one that reported its own failure. `returncode` is None when the child
    never ran to completion (launch failure, or a timeout kill); `stderr` then
    carries the reason.
    """
    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # new process group; enables group kill
        )
    except Exception as e:
        return None, "", f"Failed to run executable: {e}"

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        # Hard-kill the whole process group, then reap so no zombie/pipe leaks.
        _kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return None, stdout, (
            f"Execution timed out after {timeout:.0f}s (killed) — the test HANGS at runtime"
        )
    except Exception as e:
        _kill_process_group(proc)
        return None, "", f"Failed to run executable: {e}"


def _died_silently_by_signal(rc: Optional[int], stdout: str, stderr: str) -> bool:
    """Whether a run looks like DF-149b's exec-settling death rather than a
    real failure: killed by a signal, having written NOTHING on either stream.

    Every failure the suite actually asserts on speaks before it dies — a Saw
    panic prints `panic at FILE:LINE:` first, and a success test that exits
    nonzero has printed its output — so this window is narrow. Anything that
    does fall in it is retried at most once and the retry is REPORTED either
    way, so a genuine crash is never papered over: it costs one extra run and
    says so in the test's line.
    """
    return rc is not None and rc < 0 and not stdout and not stderr


def run_executable(exe_path: Path, timeout: float = RUN_TIMEOUT_SECS
                   ) -> tuple[bool, str, str, Optional[str]]:
    """Run a compiled executable, retrying once if it dies silently by signal.

    Returns `(success, stdout, stderr, note)`. `note` is None unless the run
    was retried — DF-149b backstop (b). A silent retry could hide a real crash
    behind a lucky second run, so the note is not optional decoration: callers
    must print it, on a pass as well as a failure.
    """
    rc, stdout, stderr = _run_once(exe_path, timeout)
    note = None

    if _died_silently_by_signal(rc, stdout, stderr):
        first = rc
        rc, stdout, stderr = _run_once(exe_path, timeout)
        outcome = ("the re-run succeeded" if rc == 0
                   else f"the re-run failed too (status {rc})")
        note = (f"{Colors.YELLOW}RE-RAN{Colors.RESET} {Path(exe_path).name}: "
                f"the first exec died of signal {-first} having written "
                f"nothing, which is what a binary the kernel has not finished "
                f"validating looks like (DF-149b); {outcome}.")

    if rc is not None and rc != 0 and not stderr:
        # A child that exits non-zero having written NOTHING leaves the report
        # with no evidence in it at all (DF-149b: an intermittent
        # `Execution failed:` followed by a blank line). A negative code is a
        # signal death, which is a different story from a Saw panic or a
        # nonzero `main`, so say which one happened.
        stderr = (f"exited with status {rc}"
                  + (f" (killed by signal {-rc})" if rc < 0 else "")
                  + " and wrote nothing")

    return rc == 0, stdout, stderr, note


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL the process group led by `proc` (best-effort), then the proc."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # Group already gone or not a group leader — fall back to the child.
        try:
            proc.kill()
        except OSError:
            pass


# ===========================================================================
# Compile and execute, pipelined behind a settle lag (design 156, DF-156a).
#
# Compilation and execution are separate stages: a test is COMPILED, and only
# after its binary has had time to SETTLE is it executed. That ordering is the
# fix for DF-149b — the in-process compiler wrote a Mach-O and exec'd it
# microseconds later, and on macOS/arm64 the kernel had not always finished
# assessing the fresh image; the child died of SIGTRAP having written nothing,
# about one run in twelve on a saturated machine.
#
# The stages RUN CONCURRENTLY, which is the DF-156a correction. Strictly
# separating them (compile every test, then execute every binary) cost +32%
# wall clock, because the kernel's assessment of a never-run file — ~0.4s,
# and it barely parallelises — was work the old interleaved runner had HIDDEN:
# a process parked in that assessment burns no CPU, so the other workers'
# compiles filled the cores. Serialising the stages exposed it as a second
# serial stretch. Pipelining them puts it back under the compile stream while
# `SETTLE_LAG_SECS` keeps the window DF-149b actually needs.
#
# The split still sorts the suite's verdicts by what they need: everything
# decidable without running anything — an error test, an object test, a docs
# test, a compile that failed when it should have succeeded — settles at
# compile time and never reaches the execution side.
# ===========================================================================

# How long a freshly renamed binary is held back before it may be executed.
#
# TIME is the mechanism, rather than "wait for N further compiles", for three
# reasons the DF-156a measurements make plain:
#
#   * The hazard is a wall-clock one. What the kernel is doing is assessing a
#     file it has never run (our binaries carry `com.apple.provenance`); that
#     costs ~0.4s and barely parallelises. What a binary needs before its exec
#     is elapsed time. A compile count is only a proxy for it, and one that
#     drifts the wrong way under load: a loaded machine compiles slower AND
#     settles slower, yet the count says "fewer seconds of waiting".
#   * A count has no answer at the ends. The last few compiles have no
#     successors to wait for, and a filtered `-f two_tests` run has no window
#     at all. A deadline just works, and costs those runs the lag once.
#   * The lag is nearly free. Compilation produces ~2 binaries/s (856 over
#     ~420s) and the execution side drains ~3.9/s (856 in 219s at width 40),
#     so the queue runs empty and each binary execs at almost exactly
#     lag-after-rename, concurrently with the compiles that follow it. The
#     only wall clock the lag costs the whole run is the tail — the LAST
#     binary compiled still has to wait it out.
#
# 5s is therefore ~1% of a suite run, spent against a hazard whose observed
# form was an exec microseconds after the write. Both DF-149b backstops stay
# in place underneath it (unique-temp-write-then-rename, and the
# retry-once-on-silent-signal-death that reports itself), so the lag is the
# margin, not the guarantee.
SETTLE_LAG_SECS = 5.0


class SettleQueue:
    """A FIFO of compiled binaries that hands each one out only once it has
    settled — `lag` seconds after it was pushed (DF-156a).

    Producers (the compile side) call `push`, then `close` when the last
    compile is in. Consumers (the execution workers) call `pop`, which blocks
    until an item is due and returns None once the queue is closed and drained.

    `lag` is constant, so pushes arrive in deadline order and the deque head is
    always the next item due — no heap, and a waiter only ever has one deadline
    to sleep on.
    """

    def __init__(self, lag: float = SETTLE_LAG_SECS):
        self.lag = lag
        self._items = collections.deque()
        self._cv = threading.Condition()
        self._closed = False

    def push(self, item) -> None:
        with self._cv:
            self._items.append((time.monotonic() + self.lag, item))
            # notify_all, not notify. A single notify is enough only if the
            # thread it picks is an IDLE worker rather than one already
            # sleeping on the current head's deadline — which happens to hold
            # in CPython, whose waiter queue is FIFO and whose re-waiters go to
            # the back, but is nowhere in the documented contract of
            # `Condition.notify`. Waking everyone costs a few wakeups a second
            # (compilation pushes ~2 binaries/s) and rests on nothing.
            self._cv.notify_all()

    def close(self) -> None:
        """No more items will be pushed; drained consumers may now exit."""
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def pop(self):
        """Block until the oldest item has settled and return it, or return
        None once the queue is both closed and empty."""
        with self._cv:
            while True:
                if self._items:
                    ready_at, item = self._items[0]
                    delay = ready_at - time.monotonic()
                    if delay <= 0:
                        self._items.popleft()
                        return item
                    # Wake at the deadline; a push cannot beat it to the head,
                    # and close() notifies, so this never oversleeps its work.
                    self._cv.wait(delay)
                elif self._closed:
                    return None
                else:
                    self._cv.wait()


@dataclass
class CompileOutcome:
    """What phase 1 concluded about one test.

    `settled` means the verdict is final and no binary will be run; `passed`
    and `msg` are then the test's result. Otherwise the test compiled and
    `exe_path` names the binary the execution stage runs once it has settled.
    """
    settled: bool
    passed: bool = False
    msg: str = ""
    exe_path: Optional[str] = None


def directive_shape_error(test: TestCase) -> Optional[str]:
    """Why this test's EXPECT directives cannot be judged, or None if they can.

    A test with nothing to assert is a test that passes forever without
    checking anything, so a missing directive is a failure and not a skip.
    """
    if test.expect_type is None:
        return "Missing '// EXPECT: success', '// EXPECT: error', or '// EXPECT: panic' directive"
    if test.expect_type == ExpectType.SUCCESS and not test.expected_output:
        return "Success test must have '// EXPECT-OUTPUT:' with expected output"
    if test.expect_type == ExpectType.ERROR and not test.expected_error_contains:
        return "Error test must have at least one '// EXPECT-ERROR-CONTAINS:' directive"
    if test.expect_type == ExpectType.PANIC and not test.expected_panic_contains:
        return "Panic test must have at least one '// EXPECT-PANIC-CONTAINS:' directive"
    if (test.expect_type == ExpectType.OBJECT
            and not test.expected_undefined_symbols
            and test.object_max_bytes is None):
        return ("Object test must have at least one "
                "'// EXPECT-SYMBOL-UNDEFINED:' or "
                "'// EXPECT-OBJECT-MAX-BYTES:' directive")
    if test.expect_type == ExpectType.DOCS and not test.expected_output:
        return "Docs test must have '// EXPECT-OUTPUT:' with the expected JSON"
    return None


def compile_test(test: TestCase, compile_fn=None) -> CompileOutcome:
    """COMPILE STAGE: compile one test, and judge everything that needs no
    execution.

    `compile_fn(path, output_path, compile_flags) -> (success, stdout, stderr)`
    performs the compilation; it defaults to the spawn-a-subprocess compiler
    (`compile_saw_file`). The persistent-worker path passes the in-process
    compiler (`compile_saw_in_process`) instead. Everything else — `nm`
    inspection, docs comparison — is identical either way.
    """
    if compile_fn is None:
        compile_fn = compile_saw_file

    shape_error = directive_shape_error(test)
    if shape_error is not None:
        return CompileOutcome(settled=True, passed=False, msg=shape_error)

    if test.expect_type == ExpectType.DOCS:
        # design 121: the compiler emits documentation JSON on stdout instead of
        # code. Nothing is compiled to a binary and nothing is run; the JSON is
        # the assertion. Lines are compared with whitespace stripped, because a
        # `//` directive line cannot preserve the JSON's indentation.
        ok, out, err = emit_docs_file(test.path, test.compile_flags)
        if not ok:
            return CompileOutcome(True, False,
                                  f"Documentation extraction failed:\n{err[:500]}")
        actual = [ln.strip() for ln in out.splitlines() if ln.strip()]
        expected = [ln.strip() for ln in test.expected_output if ln.strip()]
        if actual != expected:
            msg = "Docs JSON mismatch:\n"
            msg += "Expected:\n  " + "\n  ".join(expected) + "\n"
            msg += "Got:\n  " + "\n  ".join(actual)
            return CompileOutcome(True, False, msg)
        return CompileOutcome(True, True, "Docs as expected")

    exe_path = Path('.build') / test.binary_stem
    exe_path.parent.mkdir(exist_ok=True)

    # Compile
    compile_success, compile_stdout, compile_stderr, placed = compile_into_place(
        compile_fn, test, exe_path)

    if test.expect_type == ExpectType.ERROR:
        # Should fail to compile — decided entirely here.
        if compile_success:
            return CompileOutcome(True, False,
                                  "Expected compilation to fail, but it succeeded")

        # Check error message contains expected text
        combined_output = compile_stdout + compile_stderr
        for expected_text in test.expected_error_contains:
            if expected_text not in combined_output:
                return CompileOutcome(True, False,
                                      f"Error message should contain '{expected_text}'\nGot: {combined_output[:300]}")

        return CompileOutcome(True, True, "Failed as expected")

    elif test.expect_type == ExpectType.PANIC:
        # Should compile successfully but panic at runtime: the execution
        # stage judges it.
        if not compile_success:
            msg = f"Compilation failed (expected to compile):\n{compile_stderr[:500]}"
            return CompileOutcome(True, False, msg)

        return _to_run(exe_path, placed)

    elif test.expect_type == ExpectType.OBJECT:
        # Compile to an object file (e.g. --freestanding / -c) and inspect its
        # symbol table with `nm`; never run it. Proves the compiled object
        # EXTERNS the given symbols (undefined references) rather than defining
        # them — the design-113/113b freestanding-still-externs negative test.
        if not compile_success:
            return CompileOutcome(True, False,
                                  f"Compilation failed (expected to compile):\n{compile_stderr[:500]}")

        # sawc appends `.o` for -c / --freestanding output paths.
        obj = exe_path if exe_path.suffix == '.o' else Path(str(exe_path) + '.o')
        if not obj.exists():
            return CompileOutcome(True, False, f"Expected object file not found: {obj}")

        if test.object_max_bytes is not None:
            actual = obj.stat().st_size
            if actual > test.object_max_bytes:
                return CompileOutcome(True, False, (
                    f"{obj.name} is {actual} bytes, over the "
                    f"{test.object_max_bytes}-byte bound — a static that "
                    f"should cost no image bytes is carrying them."))

        if not test.expected_undefined_symbols:
            return CompileOutcome(True, True, "Object size as expected")

        nm = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
        if nm.returncode != 0:
            return CompileOutcome(True, False, f"`nm` failed on {obj}:\n{nm.stderr[:300]}")

        # Parse `nm` lines: "<addr?> <type> <name>". A `U` type is undefined
        # (an external reference); any other type is a local definition.
        undefined = set()
        defined = set()
        for ln in nm.stdout.splitlines():
            parts = ln.split()
            if len(parts) < 2:
                continue
            sym_type, name = parts[-2], parts[-1]
            (undefined if sym_type in ('U', 'u') else defined).add(name)

        def _present(sym, names):
            # macOS nm prefixes C symbols with `_`; match either spelling.
            return sym in names or ('_' + sym) in names or ('__' + sym) in names

        for sym in test.expected_undefined_symbols:
            if _present(sym, defined):
                return CompileOutcome(True, False,
                                      (f"Symbol `{sym}` is DEFINED in {obj.name} but was "
                                       f"expected to be an undefined external reference "
                                       f"(the freestanding profile must not bake in a "
                                       f"runtime body)."))
            if not _present(sym, undefined):
                return CompileOutcome(True, False,
                                      (f"Symbol `{sym}` is neither undefined nor defined "
                                       f"in {obj.name} — expected an undefined external "
                                       f"reference. `nm` output:\n{nm.stdout[:400]}"))

        return CompileOutcome(True, True, "Object symbols as expected")

    else:  # ExpectType.SUCCESS — the execution stage runs it and judges output.
        if not compile_success:
            msg = f"Compilation failed:\n{compile_stderr[:500]}"
            return CompileOutcome(True, False, msg)

        # design 150: compiler warnings are reported on the SUCCESS path and
        # never affect the exit code, so this is the only stage that can see
        # one. Judged here, before the binary is queued to run.
        warn_outcome = _check_warnings(test, compile_stdout + compile_stderr)
        if warn_outcome is not None:
            return warn_outcome

        return _to_run(exe_path, placed)


def _check_warnings(test: TestCase, output: str) -> Optional[CompileOutcome]:
    """Judge a test's warning directives, or None if they hold (design 150)."""
    for expected in (test.expected_warning_contains or []):
        if expected not in output:
            return CompileOutcome(True, False, (
                f"Warning output should contain '{expected}'\n"
                f"Got: {output[:400] or '<nothing on stderr>'}"))
    if test.expect_no_warnings and 'warning' in output:
        return CompileOutcome(True, False, (
            f"Expected no warnings, but the compiler emitted:\n{output[:400]}"))
    return None


def _to_run(exe_path: Path, placed: set) -> CompileOutcome:
    """Queue a compiled test for execution, first proving there is something
    to run.

    A compile that reports success but writes no executable — a runnable test
    carrying `-c`, say — would otherwise leave the execution stage running
    whatever stale binary the LAST run left at that path, and quietly passing
    on it. Separating the stages is what makes that reachable. The test is on what
    THIS compile placed, not on whether a file exists, because a stale binary
    satisfies `exists()` perfectly well.
    """
    if '' not in placed:
        return CompileOutcome(True, False, (
            f"The compiler reported success but wrote no executable to "
            f"{exe_path}. A test that runs must produce a binary; check its "
            f"'// COMPILE-FLAGS:' for a flag (-c, --freestanding) that emits "
            f"an object instead, and mark it '// EXPECT: object' if so."))
    return CompileOutcome(settled=False, exe_path=str(exe_path))


def execute_test(test: TestCase, exe_path: str) -> tuple[bool, str, Optional[str]]:
    """EXECUTION STAGE: run one compiled binary and judge how it behaved.

    Only SUCCESS and PANIC tests get here; every other verdict was settled at
    compile time. Returns `(passed, message, note)`, where `note` is anything the
    runner did that the reader must be told about even when the test passed.
    """
    run_success, run_stdout, run_stderr, note = run_executable(Path(exe_path))

    if test.expect_type == ExpectType.PANIC:
        if run_success:
            return False, (f"Expected runtime panic, but execution succeeded "
                           f"with output:\n{run_stdout[:300]}"), note

        # Check panic message contains expected text
        combined_output = run_stdout + run_stderr
        for expected_text in test.expected_panic_contains:
            if expected_text not in combined_output:
                return False, f"Panic message should contain '{expected_text}'\nGot: {combined_output[:300]}", note

        return True, "Panicked as expected", note

    # ExpectType.SUCCESS
    if not run_success:
        return False, f"Execution failed:\n{run_stderr[:500]}", note

    # Check expected output if specified
    if test.expected_output:
        actual_lines = run_stdout.strip().split('\n')
        expected_lines = test.expected_output

        if actual_lines != expected_lines:
            msg = "Output mismatch:\n"
            msg += f"Expected:\n  " + "\n  ".join(expected_lines) + "\n"
            msg += f"Got:\n  " + "\n  ".join(actual_lines)
            return False, msg, note

    return True, "Passed", note


def discover_tests(examples_dir: Path) -> List[TestCase]:
    """Discover all .saw test files, skipping library modules"""
    # Directories containing library modules (not standalone tests)
    skip_dirs = {'modules'}

    tests = []
    for saw_file in sorted(examples_dir.rglob('*.saw')):
        # Skip files in library module directories
        relative_parts = saw_file.relative_to(examples_dir).parts
        if any(part in skip_dirs for part in relative_parts[:-1]):
            continue
        test = parse_test_metadata(saw_file)
        if test is not None:  # Skip files marked with '// EXPECT: skip'
            # Build products are named after the test's path relative to
            # examples/, which — unlike the file stem — is unique. See
            # TestCase.binary_stem.
            test.out_name = '_'.join(saw_file.relative_to(examples_dir)
                                     .with_suffix('').parts)
            tests.append(test)
    return tests


def print_summary(results: List[tuple[TestCase, TestStatus, str, Optional[str]]],
                  verbose: bool, origins=None, notes=None):
    """Print test results summary.

    `origins` maps a test's repo-relative path to the machine that judged it,
    and is only populated by a `--remote` run. It annotates the failures,
    because the first question about a red test on a split run is which machine
    saw it — a failure that reproduces on only one of them is a different bug
    from one that reproduces on both.

    `notes` are the run's degradation notes: everything the worker did or
    failed to do. They print with the summary rather than scrolling past
    mid-run, since a run that quietly completed locally after the worker died
    still needs to say so.
    """
    counts = {status: 0 for status in TestStatus}
    for _, status, _, _ in results:
        counts[status] += 1

    broken = counts[TestStatus.FAIL] + counts[TestStatus.XPASS]

    def where(test):
        origin = (origins or {}).get(repo_path(test))
        return f" {Colors.DIM}[{origin}]{Colors.RESET}" if origin else ""

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}Test Results{Colors.RESET}")
    print("=" * 70)

    # Show real failures first
    if counts[TestStatus.FAIL]:
        print(f"\n{Colors.RED}{Colors.BOLD}FAILED TESTS:{Colors.RESET}")
        for test, status, msg, _ in results:
            if status is TestStatus.FAIL:
                print(f"\n  {Colors.RED}✗{Colors.RESET} {test.name}{where(test)}")
                # Indent the message
                for line in msg.split('\n'):
                    print(f"    {line}")

    # Stale XFAIL markers also break the build - they mean a bug got fixed
    if counts[TestStatus.XPASS]:
        print(f"\n{Colors.RED}{Colors.BOLD}UNEXPECTEDLY PASSING (stale XFAIL):{Colors.RESET}")
        for test, status, msg, _ in results:
            if status is TestStatus.XPASS:
                print(f"\n  {Colors.RED}!{Colors.RESET} {test.name}{where(test)}")
                for line in msg.split('\n'):
                    print(f"    {line}")

    # Known-broken tests are informational
    if counts[TestStatus.XFAIL]:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}KNOWN FAILURES (xfail):{Colors.RESET}")
        for test, status, msg, _ in results:
            if status is TestStatus.XFAIL:
                reason = test.xfail_reason or ""
                print(f"  {Colors.YELLOW}x{Colors.RESET} {test.name}: {reason}")
                if verbose:
                    # msg's first line repeats the reason; show the rest
                    for line in msg.split('\n')[1:]:
                        print(f"      {line}")

    # Show successes if verbose
    if verbose and counts[TestStatus.PASS]:
        print(f"\n{Colors.GREEN}{Colors.BOLD}PASSED TESTS:{Colors.RESET}")
        for test, status, msg, _ in results:
            if status is TestStatus.PASS:
                print(f"  {Colors.GREEN}✓{Colors.RESET} {test.name}")

    # Retries are collected here as well as printed live: a green run that
    # quietly re-ran forty binaries is telling you something about the machine,
    # and scrolled-past progress lines are easy to miss.
    retried = [(test, note) for test, _, _, note in results if note]
    if retried:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}RE-RAN:{Colors.RESET}")
        for test, note in retried:
            print(f"  {test.name}: {note}")

    # What the remote worker did, or failed to do. Printed on a green run too:
    # a run that completed locally because the worker was unreachable looks
    # exactly like an ordinary run unless it says otherwise.
    if notes:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}REMOTE:{Colors.RESET}")
        for note in notes:
            print(f"  {note}")
    elif origins:
        split = collections.Counter(origins.values())
        print(f"\n{Colors.BOLD}REMOTE:{Colors.RESET} " +
              ", ".join(f"{n} {name}" for name, n in sorted(split.items())))

    # Summary line
    print("\n" + "=" * 70)
    tally = f"{counts[TestStatus.PASS]} passed"
    if counts[TestStatus.XFAIL]:
        tally += f", {counts[TestStatus.XFAIL]} xfailed"
    if counts[TestStatus.FAIL]:
        tally += f", {counts[TestStatus.FAIL]} failed"
    if counts[TestStatus.XPASS]:
        tally += f", {counts[TestStatus.XPASS]} unexpectedly passed"

    if broken == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED{Colors.RESET} ({tally})")
    else:
        print(f"{Colors.RED}{Colors.BOLD}SOME TESTS FAILED{Colors.RESET} ({tally})")
    print("=" * 70 + "\n")

    return broken == 0


def resolve_status(test: TestCase, raw_passed: bool, msg: str) -> tuple[TestStatus, str]:
    """Fold a raw pass/fail result together with any XFAIL marker."""
    if test.xfail_reason is None:
        return (TestStatus.PASS if raw_passed else TestStatus.FAIL), msg

    if raw_passed:
        return TestStatus.XPASS, (
            f"Marked '// XFAIL: {test.xfail_reason}' but the test passed.\n"
            f"Remove the XFAIL marker from {test.path}."
        )
    return TestStatus.XFAIL, f"{test.xfail_reason}\n{msg}"


# ---------------------------------------------------------------------------
# Persistent-worker pool (design 115), built on Process + Pipe.
#
# NOT multiprocessing.Pool: Pool's task/result queues rest on POSIX named
# semaphores (`SemLock`), which some sandboxes and locked-down CI containers
# refuse to create (`sem_open` -> EPERM), and there is no need for them. Each
# worker instead owns ONE duplex Pipe (a socketpair — no semaphore) to the main
# process, and the main process multiplexes across those pipes with
# `connection.wait` (select/poll on fds). Work is handed out dynamically in a
# strict per-worker ping-pong (main sends a task, worker replies with its
# result, main sends the next), so a worker that draws several slow tests never
# starves the others — the same load-balancing the old ThreadPool had.
# ---------------------------------------------------------------------------

_WORKER_DONE = None  # sentinel: no more work, exit the loop


def _worker_loop(conn, verbose: bool):
    """Persistent worker body: import sawc + build the builtin namespace once,
    then COMPILE tasks in-process until the sentinel arrives. A worker never
    executes a test binary — that happens back in the main process, on the
    execution threads, once the binary has settled.

    Each task is `(index, TestCase)`; each reply is `(index, CompileOutcome)`.
    The index lets the main process match a reply to its test without shipping
    the (already-known) TestCase back."""
    _init_in_process(verbose)
    try:
        while True:
            task = conn.recv()
            if task is _WORKER_DONE:
                break
            index, test = task
            conn.send((index, compile_test(test, compile_saw_in_process)))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        conn.close()


def _compile_parallel_in_process(tests, num_workers, verbose, on_result):
    """COMPILE-STAGE driver: compile `tests` across `num_workers` persistent
    workers.

    Returns a `CompileOutcome` list aligned with `tests`. `on_result(index,
    outcome)` is called on the main process as each compile finishes, for live
    progress. A worker that dies mid-task (e.g. an LLVM-level abort on a
    compiler bug) leaves its task's slot filled with a synthesized settled
    failure, so the run never hangs and never silently drops a test."""
    ctx = multiprocessing.get_context('spawn')
    results = [None] * len(tests)
    tasks = iter(enumerate(tests))

    conns, procs = [], []
    for _ in range(min(num_workers, len(tests))):
        parent, child = ctx.Pipe()
        p = ctx.Process(target=_worker_loop, args=(child, verbose), daemon=True)
        p.start()
        child.close()  # only the worker holds the child end
        conns.append(parent)
        procs.append(p)

    def feed(conn) -> bool:
        """Send the next task to `conn`; return False (and send the sentinel) if
        the work is exhausted."""
        nxt = next(tasks, None)
        if nxt is None:
            conn.send(_WORKER_DONE)
            return False
        conn.send(nxt)
        return True

    active = set()
    for conn in conns:
        if feed(conn):
            active.add(conn)
        else:
            conn.close()

    received = 0
    while active:
        for conn in multiprocessing.connection.wait(list(active)):
            try:
                index, outcome = conn.recv()
            except EOFError:
                # Worker exited unexpectedly with a task outstanding.
                active.discard(conn)
                continue
            results[index] = outcome
            received += 1
            on_result(index, outcome)
            if not feed(conn):
                active.discard(conn)
                conn.close()

    for p in procs:
        p.join()

    # Fill any holes left by a crashed worker so the caller sees a definite,
    # build-breaking result rather than a None.
    if received != len(tests):
        for i, slot in enumerate(results):
            if slot is None:
                results[i] = CompileOutcome(
                    settled=True, passed=False,
                    msg="worker process died during compilation "
                        "(no result returned)")
                on_result(i, results[i])
    return results


REPO_ROOT = Path(__file__).resolve().parent


def repo_path(test: TestCase) -> str:
    """A test's path relative to the repo root — `examples/ffi/casting.saw`.

    This is the name a test has on the wire. Both machines are running the same
    tree, so it identifies the same test on either of them, which the `name`
    field does not: `examples/int_types.saw` and `examples/ffi/int_types.saw`
    share a name.
    """
    return str(Path(test.path).resolve().relative_to(REPO_ROOT))


class JsonlSink:
    """Append one record per verdict, flushed as it lands.

    A remote worker tails this file while the run is still going, which is what
    lets a shard stream its verdicts home instead of delivering them in one
    lump at the end. Flushing per line is the whole contract; the offset-based
    tailer on the other side only consumes complete lines, so a partial write
    is never misread.
    """

    def __init__(self, path):
        self._fh = open(path, "a", encoding="utf-8") if path else None
        self._lock = threading.Lock()

    def verdict(self, test: TestCase, status: 'TestStatus', msg: str,
                note) -> None:
        if self._fh is None:
            return
        record = {"kind": "test", "path": repo_path(test), "name": test.name,
                  "status": status.value, "msg": msg, "note": note}
        with self._lock:
            self._fh.write(json.dumps(record, sort_keys=True) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Run Saw language tests')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-f', '--filter', action='append',
                        help='Run only tests matching this pattern '
                             '(repeatable; each may be comma-separated)')
    parser.add_argument('-j', '--jobs', type=int, default=None,
                        help='Number of parallel jobs (default: CPU count)')
    parser.add_argument('--sequential', action='store_true',
                        help='Run tests sequentially (no parallelism)')
    parser.add_argument('--subprocess', action='store_true',
                        help='Compile each test by spawning a fresh sawc.py '
                             'subprocess (the pre-design-115 path). The default '
                             'compiles in-process in persistent worker processes; '
                             'use this to debug any runner-vs-compiler discrepancy.')
    parser.add_argument('--settle-lag', type=float, default=SETTLE_LAG_SECS,
                        metavar='SECS',
                        help=f'Seconds a freshly compiled binary is held back '
                             f'before it may be executed (default '
                             f'{SETTLE_LAG_SECS:g}; DF-149b/DF-156a). 0 executes '
                             f'each binary the moment it lands.')
    # --- the remote worker (design 160) ---------------------------------
    parser.add_argument('--remote', metavar='URL',
                        help='Run a core-weighted share of the tests on a '
                             'remote test worker (tools/test_worker.py), '
                             'concurrently with the share kept here. A worker '
                             'that is unreachable, refuses the token, or dies '
                             'mid-run costs a note: this machine finishes the '
                             'tests it did not answer for.')
    parser.add_argument('--remote-token-file', metavar='PATH',
                        help='The shared secret to present to the worker '
                             '(default ~/.config/saw-worker/token).')
    parser.add_argument('--remote-connect-timeout', type=float, default=10.0,
                        metavar='SECS',
                        help='How long to wait for the worker to answer '
                             '/health before giving up on it (default 10).')
    parser.add_argument('--only-paths', metavar='FILE',
                        help='Run exactly the repo-relative paths listed in '
                             'FILE, one per line. This is how a worker is '
                             'handed its shard; the order and the filters are '
                             'ignored.')
    parser.add_argument('--jsonl', metavar='FILE',
                        help='Append one JSON record per verdict to FILE, '
                             'flushed as each lands.')
    return parser.parse_args(argv)


def select_tests(args, examples_dir):
    """Discover the tests this invocation is about, or None if it is empty."""
    tests = discover_tests(examples_dir)

    if args.only_paths:
        wanted = [ln.strip() for ln in
                  Path(args.only_paths).read_text(encoding='utf-8').splitlines()
                  if ln.strip()]
        by_path = {repo_path(t): t for t in tests}
        missing = [p for p in wanted if p not in by_path]
        if missing:
            # Never silently run fewer tests than asked for: a shard that
            # quietly shrinks is a shard whose verdicts mean nothing.
            print(f"{Colors.RED}--only-paths names {len(missing)} path(s) that "
                  f"are not tests in this tree:{Colors.RESET}")
            for p in missing[:10]:
                print(f"  {p}")
            return None
        return [by_path[p] for p in wanted]

    # Filter tests if requested (match against relative path or name)
    if args.filter:
        patterns = [p for arg in args.filter for p in arg.split(',') if p]
        def matches_filter(test):
            # Get relative path from examples dir (e.g., "ffi/casting")
            rel_path = str(test.path.relative_to(examples_dir).with_suffix(''))
            return any(p in rel_path or p in test.name for p in patterns)
        tests = [t for t in tests if matches_filter(t)]
    return tests


def run_tests_locally(tests, args, in_process, compile_fn, jsonl=None):
    """Compile and run `tests` on THIS machine, returning one
    `(test, status, msg, note)` per test.

    This is the whole pre-design-160 runner, unchanged in what it does and now
    callable more than once: a `--remote` run calls it for the local shard, and
    again for whatever the worker did not answer for.
    """
    num_workers = args.jobs if args.jobs else os.cpu_count()
    if args.sequential:
        num_workers = 1

    # The execution side runs WIDER than the core count, because it is not CPU
    # work. The FIRST exec of a freshly written binary costs macOS ~0.4s of
    # kernel code-signature/provenance assessment (a re-exec of the same file
    # costs ~0.007s — 90x less), and that assessment barely parallelises.
    # Measured over the suite's 856 binaries: width 10 -> 375s, width 20 ->
    # 272s, width 40 -> 219s. The extra width is what keeps the DRAIN RATE
    # (~3.9 binaries/s at 40) comfortably above the rate compilation produces
    # binaries (~2/s), which is what lets the queue run empty and the settle
    # lag stay the only wait. These processes are asleep in the kernel, not
    # competing for cores, so the width costs the compile stream nothing.
    run_workers = 1 if args.sequential else min(num_workers * 4, len(tests))

    results = [None] * len(tests)          # (test, status, msg, note), by index
    settle_queue = SettleQueue(max(0.0, args.settle_lag))
    queued = [0]                           # binaries handed to the execution side
    print_lock = threading.Lock()

    def _settle(index, passed, msg, prefix, note=None):
        """Record a test's final verdict and print its progress line."""
        test = tests[index]
        status, msg = resolve_status(test, passed, msg)
        results[index] = (test, status, msg, note)
        if jsonl is not None:
            jsonl.verdict(test, status, msg, note)
        print(f"{prefix}{STATUS_SYMBOLS[status]} {test.name}")
        if note:
            # Printed on a PASS too: a retry the reader never sees is a retry
            # that can hide a real crash.
            print(f"      {note}")
        if not status.is_ok and not args.verbose:
            for line in msg.split('\n'):
                print(f"      {line}")

    # Two counters, both out of the same total: `(n/N)` counts compiles, and
    # `[n/N]` counts verdicts. They advance independently because the stages
    # overlap — a binary's verdict lands a settle lag after its compile, while
    # later compiles are still going.
    compiled = [0]
    verdicts = [0]

    def _verdict(index, passed, msg, note=None):
        with print_lock:
            verdicts[0] += 1
            _settle(index, passed, msg, f"[{verdicts[0]}/{len(tests)}] ", note)

    def _on_compiled(index, outcome):
        """Called on the main thread as each compile finishes."""
        with print_lock:
            compiled[0] += 1
            if outcome.settled:
                verdicts[0] += 1
                _settle(index, outcome.passed, outcome.msg,
                        f"[{verdicts[0]}/{len(tests)}] ")
                return
            queued[0] += 1
            print(f"{Colors.DIM}({compiled[0]}/{len(tests)}){Colors.RESET} "
                  f"{COMPILED_SYMBOL} {tests[index].name}")
        # Pushed OUTSIDE the print lock: the settle deadline starts here, and
        # an execution worker taking the lock to report a verdict must never
        # be able to delay it.
        settle_queue.push((index, outcome.exe_path))

    def _execution_worker():
        """Take settled binaries off the queue, run them, record the verdict.

        Exits when the queue is closed and drained. A crash in here would
        otherwise cost a test its verdict silently, so it is reported as that
        test's failure."""
        while True:
            item = settle_queue.pop()
            if item is None:
                return
            index, exe_path = item
            try:
                passed, msg, note = execute_test(tests[index], exe_path)
            except Exception as e:  # pragma: no cover - runner bug guard
                passed, msg, note = False, f"the runner failed to execute this test: {e}", None
            _verdict(index, passed, msg, note)

    # How the work is spread. The compile side's "persistent workers" are
    # compiler processes (design 115); the execution side is plain threads,
    # since running a binary is a subprocess wait and needs no compiler in the
    # loop.
    if args.sequential:
        how = "sequential"
    elif in_process:
        how = f"{num_workers} persistent workers"
    else:
        how = f"{num_workers} workers, subprocess compile"
    lag = settle_queue.lag

    t0 = time.monotonic()
    print(f"{Colors.BOLD}Compiling{Colors.RESET} {len(tests)} test(s) ({how}); "
          f"each binary runs {lag:g}s after it lands "
          f"({'sequentially' if args.sequential else f'{run_workers} execution workers'}).")
    print(f"{Colors.DIM}(n/N) compiled   [n/N] verdict{Colors.RESET}\n")

    # Execution threads run CONCURRENTLY with the compiles (DF-156a); they park
    # on the queue until a binary has settled. In --sequential there is one
    # thread of control by definition, so the queue is drained after the
    # compiles instead — which still honours the lag, and for the full suite
    # every binary is long past its deadline by then.
    exec_threads = []
    if not args.sequential:
        exec_threads = [threading.Thread(target=_execution_worker, daemon=True)
                        for _ in range(run_workers)]
        for t in exec_threads:
            t.start()

    try:
        if args.sequential:
            # Sequential. In-process still amortizes bootstrap: sawc is imported
            # and the builtin namespace built once in THIS process.
            if in_process:
                _init_in_process(args.verbose)
            for index, test in enumerate(tests):
                _on_compiled(index, compile_test(test, compile_fn))
        elif in_process:
            # PERSISTENT worker processes, each importing sawc + building the
            # builtin namespace once and then compiling many tests in-process.
            _compile_parallel_in_process(tests, num_workers, args.verbose,
                                         _on_compiled)
        else:
            # --subprocess: the pre-design-115 path. Each compile spawns a sawc.py
            # subprocess, so threads (not processes) suffice to overlap them.
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(compile_test, test, compile_fn): i
                           for i, test in enumerate(tests)}
                for future in as_completed(futures):
                    _on_compiled(futures[future], future.result())
    finally:
        # However the compile side ended, the execution side must be told, or
        # its workers park on an empty queue forever.
        settle_queue.close()

    t1 = time.monotonic()
    with print_lock:
        run_done = verdicts[0] - (len(tests) - queued[0])
    print(f"\n{Colors.BOLD}Compiles complete{Colors.RESET} in {t1 - t0:.1f}s — "
          f"{len(tests) - queued[0]} settled without running, "
          f"{queued[0]} binaries queued for execution "
          f"({run_done} of them already run).\n")

    if args.sequential:
        _execution_worker()
    else:
        for t in exec_threads:
            t.join()

    t2 = time.monotonic()
    print(f"\ncompile {t1 - t0:.1f}s + {t2 - t1:.1f}s draining "
          f"= {t2 - t0:.1f}s total")

    # Nothing may fall between the stages: a test that reached neither verdict
    # is a runner bug, and must break the build rather than vanish from it.
    for i, slot in enumerate(results):
        if slot is None:
            results[i] = (tests[i], TestStatus.FAIL,
                          "the runner produced no verdict for this test", None)

    return results


# ---------------------------------------------------------------------------
# Splitting a run across this machine and a remote worker (design 160).
# ---------------------------------------------------------------------------

# Once the local shard is finished, how long the worker gets to deliver the
# rest before this machine stops waiting and runs them itself. Generous against
# a worker that is merely slow (a shard is sized by cores, so it should finish
# around when the local one does), and finite against one that has stopped
# answering without dropping the connection — the case a heartbeat cannot see,
# because the heartbeat is alive and the job is not.
REMOTE_GRACE_FLOOR_SECS = 300.0


def run_split(tests, args, in_process, compile_fn, jsonl, notes, origins):
    """Run `tests` across this machine and a worker, and return every verdict.

    The shape of this function is the design's hard requirement: nothing about
    the worker may cost the run a verdict. Each step that can fail — resolving
    the token, reaching the worker, packing the tree, streaming results —
    appends a note and falls back to running the work here.
    """
    sys.path.insert(0, str(REPO_ROOT / 'tools'))
    import worker_client
    import worker_proto

    def all_local(why):
        notes.append(why)
        results = run_tests_locally(tests, args, in_process, compile_fn, jsonl)
        for test, *_ in results:
            origins[repo_path(test)] = 'local'
        return results

    worker, info, why = worker_client.connect(
        args.remote, args.remote_token_file, args.remote_connect_timeout)
    if worker is None:
        return all_local(f"{why} — every test ran here")

    weights = [os.cpu_count() or 1, info.cores]
    by_path = {repo_path(t): t for t in tests}
    local_keys, remote_keys = worker_proto.split_by_shard(list(by_path), weights)
    if not remote_keys:
        return all_local(f"the split sent nothing to {info.describe()}")

    snapshot, why = worker_client.snapshot(REPO_ROOT)
    if snapshot is None:
        return all_local(f"{why} — every test ran here")

    print(f"{Colors.BOLD}Remote{Colors.RESET} {info.describe()}: "
          f"{len(local_keys)} test(s) here, {len(remote_keys)} there "
          f"(weighted {weights[0]}:{weights[1]} by cores).")
    if not info.sandboxed:
        print(f"{Colors.YELLOW}  that worker is NOT running under a sandbox "
              f"profile{Colors.RESET}")

    remote_records = {}
    outcome = {}

    def collect():
        outcome['run'] = worker.submit(
            {"kind": "suite", "paths": remote_keys,
             "settle_lag": args.settle_lag},
            snapshot, {"result": lambda e: remote_records.__setitem__(
                e.get("path"), e)})

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()

    started = time.monotonic()
    results = run_tests_locally([by_path[k] for k in local_keys], args,
                                in_process, compile_fn, jsonl)
    for test, *_ in results:
        origins[repo_path(test)] = 'local'
    local_seconds = time.monotonic() - started

    grace = max(REMOTE_GRACE_FLOOR_SECS, 2.0 * local_seconds)
    thread.join(timeout=grace)
    if thread.is_alive():
        notes.append(f"the worker was still going {grace:.0f}s after this "
                     f"machine finished; giving up on it")
    else:
        run = outcome.get('run')
        if run is not None:
            notes.extend(run.notes)

    # A snapshot: the abandoned thread may still be writing into the dict, and
    # a test must be decided by exactly one of the two machines.
    delivered = dict(remote_records)
    for key in remote_keys:
        record = delivered.get(key)
        if record is None:
            continue
        test = by_path[key]
        try:
            status = TestStatus(record.get('status'))
        except ValueError:
            status = TestStatus.FAIL
        results.append((test, status, record.get('msg') or '',
                        record.get('note')))
        origins[key] = 'remote'
        if jsonl is not None:
            jsonl.verdict(test, status, record.get('msg') or '',
                          record.get('note'))

    missing = [k for k in remote_keys if k not in delivered]
    if missing:
        notes.append(f"the worker answered for {len(remote_keys) - len(missing)} "
                     f"of {len(remote_keys)} test(s); running the other "
                     f"{len(missing)} here")
        print(f"\n{Colors.YELLOW}{Colors.BOLD}The worker did not finish "
              f"{len(missing)} test(s) — running them here.{Colors.RESET}")
        recovered = run_tests_locally([by_path[k] for k in missing], args,
                                      in_process, compile_fn, jsonl)
        results.extend(recovered)
        for test, *_ in recovered:
            origins[repo_path(test)] = 'local (the worker did not answer)'
    return results


def main():
    args = parse_args()

    # Default: compile in-process in persistent worker processes (design 115).
    # --subprocess restores the spawn-a-sawc.py-per-test path for debugging.
    in_process = not args.subprocess
    compile_fn = compile_saw_in_process if in_process else compile_saw_file

    examples_dir = REPO_ROOT / 'examples'
    sweep_stale_temp_products(Path('.build'))

    print(f"{Colors.BLUE}{Colors.BOLD}Discovering tests...{Colors.RESET}")
    tests = select_tests(args, examples_dir)
    if tests is None:
        return 1

    print(f"Found {len(tests)} test(s)\n")

    if not tests:
        print("No tests found!")
        return 1

    jsonl = JsonlSink(args.jsonl)
    notes, origins = [], {}
    try:
        if args.remote:
            results = run_split(tests, args, in_process, compile_fn, jsonl,
                                notes, origins)
        else:
            results = run_tests_locally(tests, args, in_process, compile_fn,
                                        jsonl)
    finally:
        jsonl.close()

    results.sort(key=lambda r: r[0].name)

    # Print summary
    all_passed = print_summary(results, args.verbose, origins=origins,
                               notes=notes)

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

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
    // XFAIL: reason         - Known-broken test; still runs, but a failure is
                              reported as xfail instead of breaking the build.
                              Keep the EXPECT directives above accurate: if the
                              test starts passing it is reported as XPASS and
                              fails the run, prompting you to drop the marker.
"""

import os
import sys
import signal
import subprocess
import tempfile
import io
import copy
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


class Colors:
    """ANSI color codes"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


STATUS_SYMBOLS = {
    TestStatus.PASS: f"{Colors.GREEN}✓{Colors.RESET}",
    TestStatus.FAIL: f"{Colors.RED}✗{Colors.RESET}",
    TestStatus.XFAIL: f"{Colors.YELLOW}x{Colors.RESET}",
    TestStatus.XPASS: f"{Colors.RED}!{Colors.RESET}",
}


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
        expected_undefined_symbols=expected_undefined_symbols
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
    gets loaded (freestanding drops hosted std; runtime-build loads no std).
    """
    orig = sawc_mod.build_builtin_namespace
    cache = {}

    def cached(verbose=False, freestanding=False, runtime_build=False):
        key = (freestanding, runtime_build)
        if key not in cache:
            cache[key] = orig(verbose, freestanding, runtime_build)
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
              'target_triple': None, 'module_paths': {}}
    i, n = 0, len(flags)
    while i < n:
        f = flags[i]
        if f == '-c':
            kwargs['object_only'] = True
        elif f == '--freestanding':
            kwargs['freestanding'] = True
        elif f == '--runtime-build':
            kwargs['runtime_build'] = True
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


# Hard wall-clock cap on a single test's RUN phase. Generous vs. the
# ~seconds a real test takes; its whole job is to stop a test that HANGS
# AT RUNTIME (a live hazard for every concurrency brief) from wedging the
# whole suite. On expiry the process GROUP is killed and the test is
# recorded FAILED (timeout) — the runner never hangs.
RUN_TIMEOUT_SECS = 30


def run_executable(exe_path: Path, timeout: float = RUN_TIMEOUT_SECS) -> tuple[bool, str, str]:
    """
    Run a compiled executable under a hard, process-group-aware timeout.

    The child is launched in its OWN process group (start_new_session=True) so
    that on timeout we can SIGKILL the entire group — not just the direct
    child. This matters because a hung test may have spawned OS threads or
    child processes that inherited the stdout/stderr pipes; killing only the
    parent would leave those holding the pipe open and `communicate()` would
    block forever, wedging the runner. Killing the group guarantees the pipes
    close and the runner moves on.

    Returns: (success, stdout, stderr)
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
        return False, "", f"Failed to run executable: {e}"

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode == 0, stdout, stderr
    except subprocess.TimeoutExpired:
        # Hard-kill the whole process group, then reap so no zombie/pipe leaks.
        _kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return False, stdout, (
            f"Execution timed out after {timeout:.0f}s (killed) — the test HANGS at runtime"
        )
    except Exception as e:
        _kill_process_group(proc)
        return False, "", f"Failed to run executable: {e}"


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


def run_test(test: TestCase, verbose: bool = False, compile_fn=None) -> tuple[bool, str]:
    """
    Run a single test case

    `compile_fn(path, output_path, compile_flags) -> (success, stdout, stderr)`
    performs the compilation; it defaults to the spawn-a-subprocess compiler
    (`compile_saw_file`). The persistent-worker path passes the in-process
    compiler (`compile_saw_in_process`) instead. Everything else — running the
    produced binary, `nm` inspection, output matching — is identical either way.

    Returns: (passed, message)
    """
    if compile_fn is None:
        compile_fn = compile_saw_file
    # Require explicit EXPECT: directive
    if test.expect_type is None:
        return False, "Missing '// EXPECT: success', '// EXPECT: error', or '// EXPECT: panic' directive"

    # Require at least one output expectation
    if test.expect_type == ExpectType.SUCCESS and not test.expected_output:
        return False, "Success test must have '// EXPECT-OUTPUT:' with expected output"
    if test.expect_type == ExpectType.ERROR and not test.expected_error_contains:
        return False, "Error test must have at least one '// EXPECT-ERROR-CONTAINS:' directive"
    if test.expect_type == ExpectType.PANIC and not test.expected_panic_contains:
        return False, "Panic test must have at least one '// EXPECT-PANIC-CONTAINS:' directive"
    if test.expect_type == ExpectType.OBJECT and not test.expected_undefined_symbols:
        return False, "Object test must have at least one '// EXPECT-SYMBOL-UNDEFINED:' directive"
    if test.expect_type == ExpectType.DOCS and not test.expected_output:
        return False, "Docs test must have '// EXPECT-OUTPUT:' with the expected JSON"

    if test.expect_type == ExpectType.DOCS:
        # design 121: the compiler emits documentation JSON on stdout instead of
        # code. Nothing is compiled to a binary and nothing is run; the JSON is
        # the assertion. Lines are compared with whitespace stripped, because a
        # `//` directive line cannot preserve the JSON's indentation.
        ok, out, err = emit_docs_file(test.path, test.compile_flags)
        if not ok:
            return False, f"Documentation extraction failed:\n{err[:500]}"
        actual = [ln.strip() for ln in out.splitlines() if ln.strip()]
        expected = [ln.strip() for ln in test.expected_output if ln.strip()]
        if actual != expected:
            msg = "Docs JSON mismatch:\n"
            msg += "Expected:\n  " + "\n  ".join(expected) + "\n"
            msg += "Got:\n  " + "\n  ".join(actual)
            return False, msg
        return True, "Docs as expected"

    with tempfile.TemporaryDirectory() as tmpdir:
        exe_path = Path('.build') / test.name
        exe_path.parent.mkdir(exist_ok=True)

        # Compile
        compile_success, compile_stdout, compile_stderr = compile_fn(test.path, exe_path, test.compile_flags)

        if test.expect_type == ExpectType.ERROR:
            # Should fail to compile
            if compile_success:
                return False, "Expected compilation to fail, but it succeeded"

            # Check error message contains expected text
            combined_output = compile_stdout + compile_stderr
            for expected_text in test.expected_error_contains:
                if expected_text not in combined_output:
                    return False, f"Error message should contain '{expected_text}'\nGot: {combined_output[:300]}"

            return True, "Failed as expected"

        elif test.expect_type == ExpectType.PANIC:
            # Should compile successfully but panic at runtime
            if not compile_success:
                msg = f"Compilation failed (expected to compile):\n{compile_stderr[:500]}"
                return False, msg

            # Run the executable - expect it to fail (panic)
            run_success, run_stdout, run_stderr = run_executable(exe_path)

            if run_success:
                return False, f"Expected runtime panic, but execution succeeded with output:\n{run_stdout[:300]}"

            # Check panic message contains expected text
            combined_output = run_stdout + run_stderr
            for expected_text in test.expected_panic_contains:
                if expected_text not in combined_output:
                    return False, f"Panic message should contain '{expected_text}'\nGot: {combined_output[:300]}"

            return True, "Panicked as expected"

        elif test.expect_type == ExpectType.OBJECT:
            # Compile to an object file (e.g. --freestanding / -c) and inspect its
            # symbol table with `nm`; never run it. Proves the compiled object
            # EXTERNS the given symbols (undefined references) rather than defining
            # them — the design-113/113b freestanding-still-externs negative test.
            if not compile_success:
                return False, f"Compilation failed (expected to compile):\n{compile_stderr[:500]}"

            # sawc appends `.o` for -c / --freestanding output paths.
            obj = exe_path if exe_path.suffix == '.o' else Path(str(exe_path) + '.o')
            if not obj.exists():
                return False, f"Expected object file not found: {obj}"

            nm = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
            if nm.returncode != 0:
                return False, f"`nm` failed on {obj}:\n{nm.stderr[:300]}"

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
                    return False, (f"Symbol `{sym}` is DEFINED in {obj.name} but was "
                                   f"expected to be an undefined external reference "
                                   f"(the freestanding profile must not bake in a "
                                   f"runtime body).")
                if not _present(sym, undefined):
                    return False, (f"Symbol `{sym}` is neither undefined nor defined "
                                   f"in {obj.name} — expected an undefined external "
                                   f"reference. `nm` output:\n{nm.stdout[:400]}")

            return True, "Object symbols as expected"

        else:  # ExpectType.SUCCESS
            # Should compile successfully
            if not compile_success:
                msg = f"Compilation failed:\n{compile_stderr[:500]}"
                return False, msg

            # Run the executable
            run_success, run_stdout, run_stderr = run_executable(exe_path)

            if not run_success:
                return False, f"Execution failed:\n{run_stderr[:500]}"

            # Check expected output if specified
            if test.expected_output:
                actual_lines = run_stdout.strip().split('\n')
                expected_lines = test.expected_output

                if actual_lines != expected_lines:
                    msg = "Output mismatch:\n"
                    msg += f"Expected:\n  " + "\n  ".join(expected_lines) + "\n"
                    msg += f"Got:\n  " + "\n  ".join(actual_lines)
                    return False, msg

            return True, "Passed"


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
            tests.append(test)
    return tests


def print_summary(results: List[tuple[TestCase, TestStatus, str]], verbose: bool):
    """Print test results summary"""
    counts = {status: 0 for status in TestStatus}
    for _, status, _ in results:
        counts[status] += 1

    broken = counts[TestStatus.FAIL] + counts[TestStatus.XPASS]

    print("\n" + "=" * 70)
    print(f"{Colors.BOLD}Test Results{Colors.RESET}")
    print("=" * 70)

    # Show real failures first
    if counts[TestStatus.FAIL]:
        print(f"\n{Colors.RED}{Colors.BOLD}FAILED TESTS:{Colors.RESET}")
        for test, status, msg in results:
            if status is TestStatus.FAIL:
                print(f"\n  {Colors.RED}✗{Colors.RESET} {test.name}")
                # Indent the message
                for line in msg.split('\n'):
                    print(f"    {line}")

    # Stale XFAIL markers also break the build - they mean a bug got fixed
    if counts[TestStatus.XPASS]:
        print(f"\n{Colors.RED}{Colors.BOLD}UNEXPECTEDLY PASSING (stale XFAIL):{Colors.RESET}")
        for test, status, msg in results:
            if status is TestStatus.XPASS:
                print(f"\n  {Colors.RED}!{Colors.RESET} {test.name}")
                for line in msg.split('\n'):
                    print(f"    {line}")

    # Known-broken tests are informational
    if counts[TestStatus.XFAIL]:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}KNOWN FAILURES (xfail):{Colors.RESET}")
        for test, status, msg in results:
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
        for test, status, msg in results:
            if status is TestStatus.PASS:
                print(f"  {Colors.GREEN}✓{Colors.RESET} {test.name}")

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


def run_test_wrapper(test: TestCase, verbose: bool, compile_fn=None) -> tuple[TestCase, TestStatus, str]:
    """Wrapper to run a test and return all needed info for results"""
    raw_passed, msg = run_test(test, verbose, compile_fn)
    status, msg = resolve_status(test, raw_passed, msg)
    return (test, status, msg)


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
    then compile-and-run tasks in-process until the sentinel arrives.

    Each task is `(index, TestCase)`; each reply is `(index, TestStatus, msg)`.
    The index lets the main process match a reply to its test without shipping
    the (already-known) TestCase back."""
    _init_in_process(verbose)
    try:
        while True:
            task = conn.recv()
            if task is _WORKER_DONE:
                break
            index, test = task
            _, status, msg = run_test_wrapper(test, verbose, compile_saw_in_process)
            conn.send((index, status, msg))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        conn.close()


def _run_parallel_in_process(tests, num_workers, verbose, on_result):
    """Drive `tests` across `num_workers` persistent worker processes.

    Returns a results list aligned with `tests`. `on_result(index, status, msg)`
    is called on the main process as each test finishes, for live progress. A
    worker that dies mid-task (e.g. an LLVM-level abort on a compiler bug) leaves
    its task's slot filled with a synthesized FAIL, so the run never hangs and
    never silently drops a test."""
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
                index, status, msg = conn.recv()
            except EOFError:
                # Worker exited unexpectedly with a task outstanding.
                active.discard(conn)
                continue
            results[index] = (tests[index], status, msg)
            received += 1
            on_result(index, status, msg)
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
                results[i] = (tests[i], TestStatus.FAIL,
                              "worker process died during compilation "
                              "(no result returned)")
    return results


def main():
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
    args = parser.parse_args()

    # Default: compile in-process in persistent worker processes (design 115).
    # --subprocess restores the spawn-a-sawc.py-per-test path for debugging.
    in_process = not args.subprocess
    compile_fn = compile_saw_in_process if in_process else compile_saw_file

    examples_dir = Path(__file__).parent / 'examples'

    print(f"{Colors.BLUE}{Colors.BOLD}Discovering tests...{Colors.RESET}")
    tests = discover_tests(examples_dir)

    # Filter tests if requested (match against relative path or name)
    if args.filter:
        patterns = [p for arg in args.filter for p in arg.split(',') if p]
        def matches_filter(test):
            # Get relative path from examples dir (e.g., "ffi/casting")
            rel_path = str(test.path.relative_to(examples_dir).with_suffix(''))
            return any(p in rel_path or p in test.name for p in patterns)
        tests = [t for t in tests if matches_filter(t)]

    print(f"Found {len(tests)} test(s)\n")

    if not tests:
        print("No tests found!")
        return 1

    def _report(completed, total, test, status, msg):
        """Emit the one-line progress record for a finished test."""
        print(f"[{completed}/{total}] {STATUS_SYMBOLS[status]} {test.name}")
        if not status.is_ok and not args.verbose:
            for line in msg.split('\n'):
                print(f"      {line}")

    if args.sequential:
        # Sequential execution. In-process still amortizes bootstrap: sawc is
        # imported and the builtin namespace built once in THIS process.
        if in_process:
            _init_in_process(args.verbose)
        results = []
        for i, test in enumerate(tests, 1):
            print(f"[{i}/{len(tests)}] Running {test.name}...", end=' ', flush=True)
            raw_passed, msg = run_test(test, args.verbose, compile_fn)
            status, msg = resolve_status(test, raw_passed, msg)
            results.append((test, status, msg))
            print(STATUS_SYMBOLS[status])
            if not status.is_ok and not args.verbose:
                print(f"  {msg}")
    elif in_process:
        # Parallel, in-process: PERSISTENT worker processes, each importing sawc
        # + building the builtin namespace once and then compiling many tests
        # in-process. Test binaries are still RUN as separate subprocesses inside
        # run_test.
        num_workers = args.jobs if args.jobs else os.cpu_count()
        print(f"Running tests in parallel ({num_workers} persistent workers)...\n")
        completed = [0]

        def _on_result(index, status, msg):
            completed[0] += 1
            _report(completed[0], len(tests), tests[index], status, msg)

        results = _run_parallel_in_process(tests, num_workers, args.verbose,
                                           _on_result)
        results.sort(key=lambda r: r[0].name)
    else:
        # Parallel, --subprocess: the pre-design-115 path. Each compile spawns a
        # sawc.py subprocess, so threads (not processes) suffice to overlap them.
        num_workers = args.jobs if args.jobs else os.cpu_count()
        print(f"Running tests in parallel ({num_workers} workers, subprocess compile)...\n")
        results = []
        completed = 0
        print_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_test = {
                executor.submit(run_test_wrapper, test, args.verbose, compile_fn): test
                for test in tests
            }
            for future in as_completed(future_to_test):
                test, status, msg = future.result()
                results.append((test, status, msg))
                with print_lock:
                    completed += 1
                    _report(completed, len(tests), test, status, msg)
        results.sort(key=lambda r: r[0].name)

    # Print summary
    all_passed = print_summary(results, args.verbose)

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

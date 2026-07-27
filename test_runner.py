#!/usr/bin/env python3
"""
Saw Language Test Runner

Runs all .saw example files and verifies they behave as expected.
Test expectations are specified via comments in the source files:

    // EXPECT: success        - Should compile and run without error
    // EXPECT: error          - Should fail to compile
    // EXPECT: panic          - Should compile but panic at runtime
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
import subprocess
import tempfile
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
                elif directive == 'skip':
                    return None  # Skip this file entirely
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
        xfail_reason=xfail_reason
    )


def compile_saw_file(file_path: Path, output_path: Path) -> tuple[bool, str, str]:
    """
    Compile a .saw file using sawc.py

    Returns: (success, stdout, stderr)
    """
    sawc_path = Path(__file__).parent / 'sawc' / 'sawc.py'

    try:
        result = subprocess.run(
            [sys.executable, str(sawc_path), str(file_path), '-o', str(output_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Compilation timed out"
    except Exception as e:
        return False, "", f"Failed to run compiler: {e}"


def run_executable(exe_path: Path) -> tuple[bool, str, str]:
    """
    Run a compiled executable

    Returns: (success, stdout, stderr)
    """
    try:
        result = subprocess.run(
            [str(exe_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Execution timed out"
    except Exception as e:
        return False, "", f"Failed to run executable: {e}"


def run_test(test: TestCase, verbose: bool = False) -> tuple[bool, str]:
    """
    Run a single test case

    Returns: (passed, message)
    """
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

    with tempfile.TemporaryDirectory() as tmpdir:
        exe_path = Path('.build') / test.name

        # Compile
        compile_success, compile_stdout, compile_stderr = compile_saw_file(test.path, exe_path)

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


def run_test_wrapper(test: TestCase, verbose: bool) -> tuple[TestCase, TestStatus, str]:
    """Wrapper to run a test and return all needed info for results"""
    raw_passed, msg = run_test(test, verbose)
    status, msg = resolve_status(test, raw_passed, msg)
    return (test, status, msg)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run Saw language tests')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-f', '--filter', help='Run only tests matching this pattern')
    parser.add_argument('-j', '--jobs', type=int, default=None,
                        help='Number of parallel jobs (default: CPU count)')
    parser.add_argument('--sequential', action='store_true',
                        help='Run tests sequentially (no parallelism)')
    args = parser.parse_args()

    examples_dir = Path(__file__).parent / 'examples'

    print(f"{Colors.BLUE}{Colors.BOLD}Discovering tests...{Colors.RESET}")
    tests = discover_tests(examples_dir)

    # Filter tests if requested (match against relative path or name)
    if args.filter:
        def matches_filter(test):
            # Get relative path from examples dir (e.g., "ffi/casting")
            rel_path = str(test.path.relative_to(examples_dir).with_suffix(''))
            return args.filter in rel_path or args.filter in test.name
        tests = [t for t in tests if matches_filter(t)]

    print(f"Found {len(tests)} test(s)\n")

    if not tests:
        print("No tests found!")
        return 1

    if args.sequential:
        # Sequential execution (original behavior)
        results = []
        for i, test in enumerate(tests, 1):
            status = f"[{i}/{len(tests)}]"
            print(f"{status} Running {test.name}...", end=' ', flush=True)

            raw_passed, msg = run_test(test, args.verbose)
            status, msg = resolve_status(test, raw_passed, msg)
            results.append((test, status, msg))

            print(STATUS_SYMBOLS[status])
            if not status.is_ok and not args.verbose:
                print(f"  {msg}")
    else:
        # Parallel execution
        num_workers = args.jobs if args.jobs else os.cpu_count()
        print(f"Running tests in parallel ({num_workers} workers)...\n")

        results = []
        completed = 0
        passed_count = 0
        failed_count = 0
        print_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Submit all tests
            future_to_test = {
                executor.submit(run_test_wrapper, test, args.verbose): test
                for test in tests
            }

            # Process results as they complete
            for future in as_completed(future_to_test):
                test, status, msg = future.result()
                results.append((test, status, msg))

                with print_lock:
                    completed += 1
                    if status.is_ok:
                        passed_count += 1
                    else:
                        failed_count += 1

                    # Show progress with test name
                    progress = f"[{completed}/{len(tests)}]"
                    print(f"{progress} {STATUS_SYMBOLS[status]} {test.name}")

                    # Show error immediately for tests that break the build
                    if not status.is_ok and not args.verbose:
                        for line in msg.split('\n'):
                            print(f"      {line}")

        # Sort results by test name for consistent summary output
        results.sort(key=lambda r: r[0].name)

    # Print summary
    all_passed = print_summary(results, args.verbose)

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

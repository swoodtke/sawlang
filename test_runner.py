#!/usr/bin/env python3
"""
Saw Language Test Runner

Runs all .saw example files and verifies they behave as expected.
Test expectations are specified via comments in the source files:

    // EXPECT: success        - Should compile and run without error
    // EXPECT: error          - Should fail to compile
    // EXPECT: compiles       - Should compile; do NOT run it. For a test whose
                                whole claim is that the compiler ACCEPTS a
                                shape — the accept side of a rule, where the
                                program has nothing to say at runtime. Prefer
                                `success` whenever the run asserts something
                                real (a write landed, a value came back); this
                                is for the rows that would otherwise have to
                                invent output to satisfy the shape check.
                                Takes no output assertion and rejects one, so a
                                test that means to check behavior cannot
                                silently stop checking it. Warning directives
                                still apply (warnings are a success-path
                                report).
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
    // EXPECT-EXIT: n         - The run exits with EXACTLY status `n` (design 221
                                / DF-220b: the process exit status is a
                                user-visible contract of `main`'s return value,
                                and `EXPECT: success` alone only ever asserted
                                `rc == 0`). Success tests only; it satisfies the
                                "a success test must assert something" rule on
                                its own, because the status IS the assertion.
                                A panicking run is `EXPECT: panic`, not this.
    // EXPECT-IR-CONTAINS: text - The compile's optimized LLVM IR sidecar
                                (`<binary>.ll`) contains `text`. Design 223: a
                                cooperative-contract row has to assert that the
                                suspending callee got a FRAME
                                (`__Frame_<owner>_<method>`), not merely that
                                the program printed the right answer — a
                                silently-sync call site produces exactly the
                                right answer and no frame. Success/compiles
                                tests only; it is a compile-stage assertion, so
                                it composes with EXPECT-OUTPUT rather than
                                replacing it.
    // EXPECT-IR-ABSENT: text  - The same sidecar does NOT contain `text`. The
                                other half of the frame question: a body that
                                does not suspend must not be given a frame, and
                                over-inclusion is invisible to every runtime
                                assertion because the program still prints the
                                right answer.
    // EXPECT-OUTPUT:         - Next lines are expected stdout (until next directive or code)
    // some output
    // more output
    // EXPECT-ERROR-CONTAINS: text  - Error message should contain "text"
    // EXPECT-ERROR-ABSENT: text  - ...and must NOT contain "text" (DF-232o:
                                a diagnostic fix is often about the lines that
                                are GONE — a refusal buried under a cascade of
                                its own consequences is only pinned by
                                asserting the cascade away)
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
    // XFAIL-IF: plat reason - Platform-conditional XFAIL. `plat` is `macos`
                              (alias `darwin`) or `linux`; the marker applies
                              only on that OS. Use for tests whose pass/fail
                              depends on host behavior (e.g. allocator policy).
"""

from __future__ import annotations
import os
import re
import sys
import json
import shutil
import random
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
    COMPILES = "compiles"  # Compiles, and that is the whole assertion; do not run
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
    # DF-232o: text the compile's diagnostics must NOT contain. Some fixes are
    # about what is NO LONGER said — a refusal that used to bury itself under a
    # cascade of its own consequences is only pinned by asserting the cascade is
    # gone, and `EXPECT-ERROR-CONTAINS` cannot say that. Same shape as
    # `EXPECT-IR-ABSENT`, on the diagnostics rather than the IR.
    expected_error_absent: List[str] = None  # '// EXPECT-ERROR-ABSENT:'
    xfail_reason: Optional[str] = None  # Set by '// XFAIL: reason'
    compile_flags: List[str] = None  # Extra sawc flags from '// COMPILE-FLAGS:'
    expected_undefined_symbols: List[str] = None  # '// EXPECT-SYMBOL-UNDEFINED:'
    object_max_bytes: Optional[int] = None  # '// EXPECT-OBJECT-MAX-BYTES:'
    # design 150: compiler WARNINGS, which are reported on the SUCCESS path and
    # never affect the exit code — so no existing directive can see one.
    expected_warning_contains: List[str] = None  # '// EXPECT-WARNING-CONTAINS:'
    expect_no_warnings: bool = False  # '// EXPECT-NO-WARNINGS'
    # design 158: a SUBSTRING of a successful run's stdout. `EXPECT-OUTPUT`
    # cannot express one, and not only because it is whole-output: the parser
    # strips each expected line, so INDENTED output — a task dump, a tree, a
    # table — is unmatchable by it however the rest is written. The
    # error/panic/warning paths all had a CONTAINS twin; the success path did
    # not.
    expected_output_contains: List[str] = None  # '// EXPECT-OUTPUT-CONTAINS:'
    # design 221: the exact process exit status. `EXPECT: success` asserts only
    # `rc == 0`, which is precisely the assertion DF-220b's bug satisfied while
    # throwing `main`'s value away.
    expected_exit: Optional[int] = None  # '// EXPECT-EXIT: n'
    # design 223: a substring of the compile's optimized IR sidecar. The
    # cooperative contract is a claim about the CODE THE COMPILER EMITTED — a
    # suspending method call has to become an embedded frame — and every
    # runtime assertion is blind to it: a silently-sync call site computes the
    # same value, in the same order, and only stops interleaving with its
    # siblings. `__Frame_<owner>_<method>` in the IR is the direct evidence.
    expected_ir_contains: List[str] = None  # '// EXPECT-IR-CONTAINS:'
    expected_ir_absent: List[str] = None  # '// EXPECT-IR-ABSENT:'
    out_name: Optional[str] = None  # unique build-output stem; see `binary_stem`

    @property
    def binary_stem(self) -> str:
        """The name this test's build products get under this run's build
        directory (`.build/test_runner_<stamp>/`, design 220 D2 — a flat
        `.build/` before that).

        `name` (the file stem) is NOT unique: `examples/int_types.saw` and
        `examples/ffi/int_types.saw` share one. Two tests writing `<dir>/foo`,
        `<dir>/foo.o` and `<dir>/foo.ll` concurrently race over all three —
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
# Marker for a test whose binary was HARDLINKED forward from the previous
# run instead of recompiled (design 220 D3) — still queued for execution the
# same as a fresh compile, just visibly distinguished so a reuse rate is
# readable straight out of the suite's own progress lines.
REUSED_SYMBOL = f"{Colors.DIM}↻{Colors.RESET}"


def parse_test_metadata(file_path: Path) -> Optional[TestCase]:
    """Parse test metadata from comments in a .saw file.

    Returns None for files marked with '// EXPECT: skip' (library modules, etc.)
    """
    name = file_path.stem
    expect_type = None  # Must be explicitly set
    expected_output = []
    expected_error_contains = []
    expected_error_absent = []
    expected_panic_contains = []
    xfail_reason = None
    compile_flags = []
    expected_undefined_symbols = []
    object_max_bytes = None
    expected_warning_contains = []
    expect_no_warnings = False
    expected_output_contains = []
    expected_exit = None
    expected_ir_contains = []
    expected_ir_absent = []

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
                elif directive == 'compiles':
                    expect_type = ExpectType.COMPILES
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

            elif '// EXPECT-EXIT:' in line:
                expected_exit = int(line.split('// EXPECT-EXIT:')[1].strip())
                in_output_block = False

            elif '// EXPECT-IR-CONTAINS:' in line:
                ir_text = line.split('// EXPECT-IR-CONTAINS:')[1].strip()
                if ir_text:
                    expected_ir_contains.append(ir_text)
                in_output_block = False

            elif '// EXPECT-IR-ABSENT:' in line:
                ir_text = line.split('// EXPECT-IR-ABSENT:')[1].strip()
                if ir_text:
                    expected_ir_absent.append(ir_text)
                in_output_block = False

            elif '// EXPECT-OUTPUT-CONTAINS:' in line:
                # Checked BEFORE `EXPECT-OUTPUT:`, which is a prefix of it.
                #
                # ONE space after the colon is the separator and everything
                # after it is content, LEADING WHITESPACE INCLUDED — which is
                # the point of the directive: indented output is what
                # `EXPECT-OUTPUT` cannot express.
                out_text = line.split('// EXPECT-OUTPUT-CONTAINS:')[1].rstrip()
                if out_text.startswith(' '):
                    out_text = out_text[1:]
                if out_text:
                    expected_output_contains.append(out_text)
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

            elif '// EXPECT-ERROR-ABSENT:' in line:
                error_text = line.split('// EXPECT-ERROR-ABSENT:')[1].strip()
                expected_error_absent.append(error_text)
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

            elif '// XFAIL-IF:' in line:
                rest = line.split('// XFAIL-IF:')[1].strip()
                parts = rest.split(None, 1)
                plat = parts[0].lower() if parts else ''
                reason = parts[1] if len(parts) > 1 else ''
                cur = sys.platform
                if ((plat in ('macos', 'darwin') and cur == 'darwin')
                        or (plat == 'linux' and cur == 'linux')):
                    xfail_reason = reason
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
        expected_error_absent=expected_error_absent,
        expected_panic_contains=expected_panic_contains,
        xfail_reason=xfail_reason,
        compile_flags=compile_flags,
        expected_undefined_symbols=expected_undefined_symbols,
        object_max_bytes=object_max_bytes,
        expected_warning_contains=expected_warning_contains,
        expect_no_warnings=expect_no_warnings,
        expected_output_contains=expected_output_contains,
        expected_exit=expected_exit,
        expected_ir_contains=expected_ir_contains,
        expected_ir_absent=expected_ir_absent
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
        elif f in ('-O0', '-O1', '-O2', '-Os', '-Oz'):
            # design 265 U1: the level set, modelled so a level-pinned test
            # runs in-process (and joins the reuse manifest) rather than
            # falling through to a subprocess. `optimize` is the pipeline
            # gate; `opt_level` is which pipeline.
            kwargs['opt_level'] = f[2:]
            kwargs['optimize'] = f != '-O0'
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

    Always requests the optimized-IR sidecar (design 220 D5): cheap relative
    to the rest of a compile (unit 0 measured +3.2%), and it is what makes a
    SUCCESS/PANIC compile's `.ll` a candidate for the reuse manifest at all —
    see `compile_test`'s `_manifest_fields`.
    """
    kwargs = _parse_compile_flags(compile_flags or [])
    if kwargs is None:
        # A flag the in-process path does not model: compile via subprocess so
        # the result is exactly the CLI's, never a silent divergence. No
        # optimized sidecar either way — the CLI has no flag for it, so this
        # falls outside the manifest (design 220 D4's existing carve-out for
        # unmodeled COMPILE-FLAGS).
        return compile_saw_file(file_path, output_path, compile_flags)
    kwargs['emit_optimized_ir'] = True

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


# ---------------------------------------------------------------------------
# Per-run output directories + atomic publish (design 220 D2).
#
# Every invocation of this file gets its own `.build/test_runner_<stamp>/`
# rather than sharing one flat `.build/`. A run that dies mid-compile leaves
# its half-written products stranded in ITS OWN directory — nothing under
# the currently PUBLISHED run is ever touched — which is what makes the old
# `sweep_stale_temp_products` (deleting `.tmp-…` leftovers from an
# interrupted run before starting a new one) unnecessary: a fresh directory
# has nothing to sweep. `compile_into_place`'s unique-temp-name-then-rename
# trick (DF-149b backstop (a)) is unchanged and still needed WITHIN a run.
#
# Publishing is a symlink flip, never `ln -sfn` (which is unlink-then-create
# and exposes a window with no `test_runner_last` at all): a distinctly named
# temporary symlink is created pointing at the run directory's bare NAME
# (relative — so `test_runner_last` stays valid if `.build/` is ever moved),
# then `os.replace` renames it over `test_runner_last` atomically. A reader
# either sees the old target or the new one, never neither.
# ---------------------------------------------------------------------------

RUN_DIR_PREFIX = 'test_runner_'
RUN_DIR_RE = re.compile(r'^test_runner_(\d+)_(\d+)$')
LAST_LINK_NAME = 'test_runner_last'
HISTORY_FILENAME = 'test_runner_history.txt'
# How many past generations a successful publish keeps (D2). Covers any
# reader that resolved the PREVIOUS `test_runner_last` a moment before this
# run's flip (design 220 D2's "in-flight reader" case) and gives unit 2's
# hardlink carry-forward a previous generation to carry unchanged files
# forward from. Not the retention knob for `.ll` disk pressure — that is K
# itself, per D5's fallback ("if disk is obnoxious, retention can drop to
# K=1"), changed here if it is ever needed.
KEEP_GENERATIONS = 3


def make_run_stamp() -> str:
    """A directory name unique to this invocation: `test_runner_<epoch>_<pid>`.

    Timestamp alone is not enough (two runs started in the same second on a
    fast machine collide); pid alone is not enough (pids recycle). Together
    they are unique in practice, and the embedded epoch gives prune a
    recency ordering without having to stat anything.
    """
    return f"{RUN_DIR_PREFIX}{int(time.time())}_{os.getpid()}"


def publish_run(build_root: Path, run_name: str) -> List[str]:
    """Atomically flip `test_runner_last` to `run_name`, record it in the
    history ledger, and prune every run directory the ledger does not name.

    Returns the names pruned. A directory that was never recorded here —
    because its run crashed before reaching this call — is pruned exactly
    like a superseded old generation: it is simply absent from the ledger
    `publish_run` is about to write, so the sweep below removes it the same
    way it removes anything else outside the kept window. That is D2's
    "pruned as an unflipped orphan by the next run", with no separate
    orphan-detection path to keep in sync with this one.
    """
    last = build_root / LAST_LINK_NAME
    tmp = build_root / f"{LAST_LINK_NAME}.tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(run_name, tmp)   # relative target: just the run dir's name
    os.replace(tmp, last)       # atomic rename over the previous symlink

    history_path = build_root / HISTORY_FILENAME
    entries = []
    if history_path.exists():
        entries = [ln.strip() for ln in
                  history_path.read_text(encoding='utf-8').splitlines()
                  if ln.strip()]
    entries.append(run_name)
    entries = entries[-KEEP_GENERATIONS:]
    history_path.write_text('\n'.join(entries) + '\n', encoding='utf-8')

    keep = set(entries)
    pruned = []
    for entry in build_root.iterdir():
        if (entry.is_dir() and not entry.is_symlink()
                and RUN_DIR_RE.match(entry.name) and entry.name not in keep):
            shutil.rmtree(entry, ignore_errors=True)
            pruned.append(entry.name)
    return pruned


def resolve_last(build_root: Path) -> Optional[Path]:
    """The run directory `test_runner_last` currently names, or `None` if the
    symlink is absent (no completed run yet — a clean checkout, or every past
    run was killed before publishing). Resolved ONCE per invocation and held,
    per design 220 D2: a reader that re-resolved the symlink partway through
    would see a NEWER run flip underneath it if one happened to land
    mid-read, mixing two generations' artifacts in one decision.
    """
    link = build_root / LAST_LINK_NAME
    if not link.is_symlink():
        return None
    target = os.readlink(link)
    resolved = build_root / target
    return resolved if resolved.is_dir() else None


# ---------------------------------------------------------------------------
# The reuse manifest + staleness (design 220 D1/D3).
#
# Per compiled SUCCESS/PANIC test: which worker seed produced its optimized
# `.ll`, the artifact's filename (relative to the run directory — carried
# forward or not, it always ends up at `<run_dir>/<stem>.ll`), and the
# artifact's own mtime, recorded for a human reading the manifest rather than
# consumed by any freshness DECISION here (a decision always re-stats the
# real file; see `try_carry_forward`). A plain tab-separated text file, not
# JSON: this is a private contract between test_runner.py and irdet, and Saw
# has no JSON parser to keep in sync with a format nothing else needs.
# ---------------------------------------------------------------------------

MANIFEST_FILENAME = 'manifest.tsv'


@dataclass
class ManifestEntry:
    seed: int
    ll_name: str     # filename only; always directly under the run dir
    mtime: float      # the artifact's own mtime — informational (see above)


def read_manifest(run_dir: Optional[Path]) -> dict:
    """`{repo-relative path: ManifestEntry}`, or `{}` if `run_dir` is `None`
    or carries no manifest (a pre-design-220-unit-2 generation, or a run that
    produced no in-process compiles at all — `--sequential`/`--subprocess`).
    A malformed line is skipped rather than failing the read: the worst a bad
    line costs is one fewer carry-forward hit, never a wrong one, since
    `try_carry_forward` re-verifies everything it uses this dict for.
    """
    if run_dir is None:
        return {}
    entries = {}
    try:
        with open(run_dir / MANIFEST_FILENAME, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) != 4:
                    continue
                rel_path, seed_s, ll_name, mtime_s = parts
                try:
                    entries[rel_path] = ManifestEntry(int(seed_s), ll_name, float(mtime_s))
                except ValueError:
                    continue
    except OSError:
        return {}
    return entries


def write_manifest(run_dir: Path, entries: dict, global_max_mtime: float) -> None:
    lines = [
        "# design 220 suite manifest v1: path\\tseed\\tll_name\\tmtime",
        f"# global_max_input_mtime\t{global_max_mtime!r}",
    ]
    for rel_path in sorted(entries):
        e = entries[rel_path]
        lines.append(f"{rel_path}\t{e.seed}\t{e.ll_name}\t{e.mtime!r}")
    (run_dir / MANIFEST_FILENAME).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _llvmlite_dist_info_mtime() -> Optional[float]:
    """The installed llvmlite's own staleness input (design 220 D3(b)): IR
    depends on the llvmlite version, and a venv upgrade touches no repo file.
    Best-effort — an unusual venv layout just loses this one input, and only
    in the SAFE direction (more files look stale than strictly need to; never
    the reverse, since it can only ever RAISE the global bound)."""
    try:
        import llvmlite
        pkg_dir = Path(llvmlite.__file__).resolve().parent
        candidates = sorted(pkg_dir.parent.glob('llvmlite-*.dist-info'))
        target = candidates[-1] if candidates else pkg_dir
        return target.stat().st_mtime
    except Exception:
        return None


def compute_global_max_input_mtime() -> float:
    """Design 220 D3: the part of "every input" that is the SAME for every
    file in the run — every file and directory under `sawc/` (a deletion
    bumps no surviving file's mtime but does bump its parent directory's),
    the llvmlite install, and `test_runner.py` itself. Computed once per run,
    never per file: `try_carry_forward` compares this ONE number against each
    candidate's own artifact and source mtimes.
    """
    latest = 0.0
    for root, _dirs, files in os.walk(REPO_ROOT / 'sawc'):
        try:
            latest = max(latest, os.stat(root).st_mtime)
        except OSError:
            pass
        for name in files:
            try:
                latest = max(latest, os.stat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
    try:
        latest = max(latest, (REPO_ROOT / 'test_runner.py').stat().st_mtime)
    except OSError:
        pass
    dist_info_mtime = _llvmlite_dist_info_mtime()
    if dist_info_mtime is not None:
        latest = max(latest, dist_info_mtime)
    return latest


def manifest_eligible(test: TestCase) -> bool:
    """Whether this test's build products may enter the reuse manifest at all —
    design 220 D4's "no fresh artifact" carve-out, written as the rule instead
    of guessed at through a proxy.

    THE one place the rule lives. Two entry points, and they MUST agree, because
    an entry either side admits is an entry the other trusts: `compile_test`'s
    `_manifest_fields`, which stamps an entry onto a fresh compile, and
    `try_carry_forward`, which reuses one.

    Both conditions were learned from the design-220 re-gate, where `irdet --all`
    reported four VIOLATED INVARIANTs against an otherwise clean corpus.

    **No `// COMPILE-FLAGS:`.** The manifest promises irdet the OPTIMIZED IR of
    a plain default-flag compile, and a flagged test breaks that promise in one
    of two ways depending on the flag. An UNMODELED flag (`--no-hidden-alloc`,
    `-W`) falls back to a subprocess compile — which still writes a `.ll`,
    because `_emit_object` writes the always-on UNOPTIMIZED debug sidecar for
    every caller. The old gate asked "was a `.ll` placed?", saw one, and stamped
    an entry pointing at unoptimized IR; irdet compared its own optimized
    compile against it and correctly refused to call the difference
    nondeterminism. A MODELED flag (`--module-path`) does produce the optimized
    sidecar, but of a DIFFERENT compile than the one irdet reproduces — inert
    today only because irdet's flag-less compile of those files happens to fail
    and skip them, which is luck rather than a guarantee, and the same rule
    retires both.

    **Nothing asserted at COMPILE time.** `_check_warnings` judges the compile's
    OUTPUT, and a carry-forward hit performs no compile and has no output, so
    the assertion would silently not run — a test quietly checking less than it
    says it does. (`directive_shape_error` needs no clause here: a shape error
    settles the verdict before `_to_run` is ever reached, so such a test never
    acquires an entry to carry forward, and editing a directive bumps the
    source mtime, which fails the freshness test anyway.)

    Runtime assertions — EXPECT-OUTPUT, EXPECT-OUTPUT-CONTAINS, EXPECT-EXIT, the
    panic verdict — need no clause either: the execution stage re-checks them
    every run whatever the binary's origin, which is the same reason reuse is
    scoped to SUCCESS/PANIC in the first place.

    Cost, measured on this corpus: 15 of 1190 eligible tests (1.3%).
    """
    if test.compile_flags:
        return False
    if test.expected_warning_contains or test.expect_no_warnings:
        return False
    return True


def try_carry_forward(test: TestCase, run_dir: Path, prev_run_dir: Optional[Path],
                      prev_manifest: dict, global_max_mtime: float
                      ) -> Optional[CompileOutcome]:
    """Hardlink a still-fresh artifact forward instead of recompiling (design
    220 D3), or `None` if this test must compile for real.

    Deliberately scoped to SUCCESS/PANIC only. Both are re-validated for real
    by the execution stage EVERY run, however their binary arrived — which is
    what makes trusting a carried-forward BINARY safe without also trusting a
    cached VERDICT. A COMPILES/OBJECT/ERROR/DOCS test settles at compile time
    with no such net (nothing re-runs it to catch a wrong reuse), so those
    always compile fresh, same as before design 220. Fewer files get to skip
    compiling than "every file with an artifact" would allow, in exchange for
    never caching a verdict this run did not itself just prove.
    """
    if test.expect_type not in (ExpectType.SUCCESS, ExpectType.PANIC):
        return None
    if not manifest_eligible(test):
        # Asked here as well as at the stamping site, not only there: a manifest
        # written by an OLDER generation (or a future rule change) can name a
        # test this rule now refuses, and reuse must follow today's rule.
        return None
    if prev_run_dir is None:
        return None
    entry = prev_manifest.get(repo_path(test))
    if entry is None:
        return None

    prev_exe = prev_run_dir / test.binary_stem
    prev_ll = Path(str(prev_exe) + '.ll')
    try:
        artifact_mtime = prev_ll.stat().st_mtime
        source_mtime = test.path.stat().st_mtime
    except OSError:
        return None
    if not (artifact_mtime > global_max_mtime and artifact_mtime > source_mtime):
        return None

    exe_path = run_dir / test.binary_stem
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    placed = set()
    placed_paths = []
    for suffix in _PRODUCT_SUFFIXES:
        src = Path(str(prev_exe) + suffix)
        if not src.exists():
            continue
        dst = Path(str(exe_path) + suffix)
        try:
            os.link(src, dst)
        except OSError:
            # Cross-device, permission, whatever — fall back to a real
            # compile rather than leave a half-carried-forward stem behind.
            for p in placed_paths:
                try:
                    p.unlink()
                except OSError:
                    pass
            return None
        placed.add(suffix)
        placed_paths.append(dst)

    outcome = _to_run(exe_path, placed,
                      manifest=(entry.seed, f"{test.binary_stem}.ll", artifact_mtime))
    if outcome.settled:
        # No executable among what the previous generation had for this
        # stem — should not happen for a manifest entry that recorded a
        # SUCCESS/PANIC compile, but `_to_run` already knows how to say so;
        # no reason to duplicate that judgment here. Compile for real.
        return None
    outcome.reused = True
    return outcome


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
                   ) -> tuple[bool, Optional[int], str, str, Optional[str]]:
    """Run a compiled executable, retrying once if it dies silently by signal.

    Returns `(success, rc, stdout, stderr, note)`. `rc` is the raw status the
    child left (None when it never ran to completion), which `EXPECT-EXIT`
    reads — `success` alone collapses every nonzero status into one verdict.
    `note` is None unless the run was retried — DF-149b backstop (b). A silent
    retry could hide a real crash behind a lucky second run, so the note is not
    optional decoration: callers must print it, on a pass as well as a failure.
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

    return rc == 0, rc, stdout, stderr, note


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

    The `manifest_*` fields (design 220 D1/D3) are populated only for a
    SUCCESS/PANIC outcome that carries a fresh optimized-IR artifact —
    either a real in-process compile under a known worker seed, or a
    carry-forward hit that copied a previous entry forward unchanged
    (`reused=True` marks that case, purely for progress-line/reuse-rate
    reporting; it changes no behavior). `None` means "no manifest entry for
    this test": the sequential/`--subprocess` paths, anything that fell back
    to a subprocess compile, and every non-SUCCESS/PANIC expect type all
    leave these unset.
    """
    settled: bool
    passed: bool = False
    msg: str = ""
    exe_path: Optional[str] = None
    manifest_seed: Optional[int] = None
    manifest_ll_name: Optional[str] = None
    manifest_mtime: Optional[float] = None
    reused: bool = False


def directive_shape_error(test: TestCase) -> Optional[str]:
    """Why this test's EXPECT directives cannot be judged, or None if they can.

    A test with nothing to assert is a test that passes forever without
    checking anything, so a missing directive is a failure and not a skip.
    """
    if test.expect_type is None:
        return "Missing '// EXPECT: success', '// EXPECT: error', or '// EXPECT: panic' directive"
    if (test.expect_type == ExpectType.SUCCESS and not test.expected_output
            and not test.expected_output_contains
            and test.expected_exit is None):
        return ("Success test must have '// EXPECT-OUTPUT:' with expected "
                "output, at least one '// EXPECT-OUTPUT-CONTAINS:', or an "
                "'// EXPECT-EXIT:' status")
    if (test.expected_exit is not None
            and test.expect_type != ExpectType.SUCCESS):
        # The status is only read on the success path. On any other verdict the
        # directive would be silently ignored — the failure mode every other
        # shape rule here exists to prevent.
        return ("'// EXPECT-EXIT:' asserts the status of a RUN, so it belongs "
                "with '// EXPECT: success'. A run that aborts is "
                "'// EXPECT: panic'.")
    if test.expect_type == ExpectType.ERROR and not test.expected_error_contains:
        return "Error test must have at least one '// EXPECT-ERROR-CONTAINS:' directive"
    if test.expect_type == ExpectType.COMPILES and (
            test.expected_output or test.expected_output_contains
            or test.expected_panic_contains or test.expected_error_contains):
        # A `compiles` test never runs, so an output/panic assertion on one
        # would be quietly ignored — which is how a behavior test stops
        # checking behavior without anyone noticing. Say so instead.
        return ("'// EXPECT: compiles' asserts only that the compiler accepts "
                "the file, so it takes no output, panic or error assertion. "
                "Use '// EXPECT: success' if the run is part of the claim.")
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
    if ((test.expected_ir_contains or test.expected_ir_absent)
            and test.expect_type not in (ExpectType.SUCCESS,
                                         ExpectType.COMPILES,
                                         ExpectType.PANIC)):
        # The sidecar only exists for a compile that produced code, and on any
        # other verdict the directive would be silently ignored — the same
        # failure mode every shape rule above exists to prevent.
        return ("'// EXPECT-IR-CONTAINS:' / '// EXPECT-IR-ABSENT:' read the "
                "compile's `.ll` sidecar, so they belong with "
                "'// EXPECT: success', '// EXPECT: compiles' or "
                "'// EXPECT: panic'.")
    return None


def compile_test(test: TestCase, compile_fn=None,
                 run_dir: Optional[Path] = None,
                 seed: Optional[int] = None) -> CompileOutcome:
    """COMPILE STAGE: compile one test, and judge everything that needs no
    execution.

    `compile_fn(path, output_path, compile_flags) -> (success, stdout, stderr)`
    performs the compilation; it defaults to the spawn-a-subprocess compiler
    (`compile_saw_file`). The persistent-worker path passes the in-process
    compiler (`compile_saw_in_process`) instead. Everything else — `nm`
    inspection, docs comparison — is identical either way.

    `run_dir` is this invocation's own `.build/test_runner_<stamp>/` (design
    220 D2); build products land there instead of a flat `.build/`, so two
    invocations never race over the same path. Defaults to `.build/` itself
    for any caller that has not been updated to pass one (there are none
    left in this file, but `compile_test` is small and public enough that a
    silent `None` should still do something sane rather than crash).

    `seed` is the calling worker's own PYTHONHASHSEED (design 220 D1), known
    only on the persistent-worker path. When set, a SUCCESS/PANIC compile
    that placed the optimized `.ll` sidecar (`compile_saw_in_process` always
    requests one) stamps it onto the returned `CompileOutcome` as a manifest
    entry; every other path leaves the manifest fields unset, which is what
    keeps them out of the reuse manifest (design 220 D4's "no fresh artifact"
    carve-out already covers exactly this set).
    """
    if compile_fn is None:
        compile_fn = compile_saw_file
    if run_dir is None:
        run_dir = Path('.build')

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

    exe_path = run_dir / test.binary_stem
    exe_path.parent.mkdir(parents=True, exist_ok=True)

    # Compile
    compile_success, compile_stdout, compile_stderr, placed = compile_into_place(
        compile_fn, test, exe_path)

    def _manifest_fields():
        # design 220 D1/D3. Three conditions, and each rules out a different
        # way of having no fresh artifact (D4's carve-out): no worker seed means
        # this was not a persistent-worker in-process compile at all (the
        # sequential and `--subprocess` paths); `manifest_eligible` is the rule
        # about what the artifact WOULD be (see its docstring — it is what the
        # re-gate's four VIOLATED INVARIANTs turned out to be); and `.ll` in
        # `placed` is the fact that this particular compile did emit one.
        if seed is None or not manifest_eligible(test) or '.ll' not in placed:
            return None
        ll_path = Path(str(exe_path) + '.ll')
        try:
            mtime = ll_path.stat().st_mtime
        except OSError:
            return None
        return (seed, ll_path.name, mtime)

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
        # DF-232o: and what it must NOT say. A diagnostic fix is often about a
        # line that is gone.
        for absent_text in (test.expected_error_absent or ()):
            if absent_text in combined_output:
                return CompileOutcome(True, False,
                                      f"Error message should NOT contain '{absent_text}'\nGot: {combined_output[:300]}")

        return CompileOutcome(True, True, "Failed as expected")

    elif test.expect_type == ExpectType.COMPILES:
        # The accept side of a rule: acceptance IS the assertion, so the
        # verdict settles here and no binary is queued.
        if not compile_success:
            return CompileOutcome(True, False, (
                f"Expected the file to compile, but it did not:\n"
                f"{compile_stderr[:500]}"))
        warn_outcome = _check_warnings(test, compile_stdout + compile_stderr)
        if warn_outcome is not None:
            return warn_outcome
        ir_outcome = _check_ir(test, exe_path, placed)
        if ir_outcome is not None:
            return ir_outcome
        return CompileOutcome(True, True, "Compiled as expected")

    elif test.expect_type == ExpectType.PANIC:
        # Should compile successfully but panic at runtime: the execution
        # stage judges it.
        if not compile_success:
            msg = f"Compilation failed (expected to compile):\n{compile_stderr[:500]}"
            return CompileOutcome(True, False, msg)

        ir_outcome = _check_ir(test, exe_path, placed)
        if ir_outcome is not None:
            return ir_outcome

        return _to_run(exe_path, placed, _manifest_fields())

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

        ir_outcome = _check_ir(test, exe_path, placed)
        if ir_outcome is not None:
            return ir_outcome

        return _to_run(exe_path, placed, _manifest_fields())


def _check_ir(test: TestCase, exe_path: Path,
              placed: set) -> Optional[CompileOutcome]:
    """Judge a test's `// EXPECT-IR-CONTAINS:` directives, or None if they hold.

    design 223. The sidecar `sawc` leaves beside the binary is the OPTIMIZED
    module IR, so a symbol found here is one the emitted program really
    carries. Which suffix it wears follows the output shape (`<out>.ll` for a
    linked binary, `<out>.o.ll` for `-c` / `--freestanding`), and `placed` is
    the authority on which this compile wrote — a stale sidecar from an earlier
    run would answer the question just as readily.
    """
    if not test.expected_ir_contains and not test.expected_ir_absent:
        return None
    suffix = '.ll' if '.ll' in placed else ('.o.ll' if '.o.ll' in placed else None)
    if suffix is None:
        return CompileOutcome(True, False, (
            "'// EXPECT-IR-CONTAINS:' needs the compile's `.ll` sidecar, and "
            "this compile placed none."))
    ll_path = Path(str(exe_path) + suffix)
    try:
        ir = ll_path.read_text()
    except OSError as e:
        return CompileOutcome(True, False, f"Could not read {ll_path.name}: {e}")
    for expected in (test.expected_ir_contains or []):
        if expected not in ir:
            return CompileOutcome(True, False, (
                f"Emitted IR should contain '{expected}' — it does not. "
                f"({ll_path.name}, {len(ir)} bytes)"))
    for absent in (test.expected_ir_absent or []):
        if absent in ir:
            return CompileOutcome(True, False, (
                f"Emitted IR should NOT contain '{absent}' — it does. "
                f"({ll_path.name}, {len(ir)} bytes)"))
    return None


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


def _to_run(exe_path: Path, placed: set,
           manifest: Optional[tuple] = None) -> CompileOutcome:
    """Queue a compiled test for execution, first proving there is something
    to run.

    A compile that reports success but writes no executable — a runnable test
    carrying `-c`, say — would otherwise leave the execution stage running
    whatever stale binary the LAST run left at that path, and quietly passing
    on it. Separating the stages is what makes that reachable. The test is on what
    THIS compile placed, not on whether a file exists, because a stale binary
    satisfies `exists()` perfectly well.

    `manifest`, when given, is `(seed, ll_name, mtime)` (design 220 D1/D3) —
    attached onto the returned outcome so `_on_compiled` can fold it into the
    run's manifest without every caller of `_to_run` re-deriving the same
    three fields.
    """
    if '' not in placed:
        return CompileOutcome(True, False, (
            f"The compiler reported success but wrote no executable to "
            f"{exe_path}. A test that runs must produce a binary; check its "
            f"'// COMPILE-FLAGS:' for a flag (-c, --freestanding) that emits "
            f"an object instead, and mark it '// EXPECT: object' if so."))
    outcome = CompileOutcome(settled=False, exe_path=str(exe_path))
    if manifest is not None:
        outcome.manifest_seed, outcome.manifest_ll_name, outcome.manifest_mtime = manifest
    return outcome


def execute_test(test: TestCase, exe_path: str) -> tuple[bool, str, Optional[str]]:
    """EXECUTION STAGE: run one compiled binary and judge how it behaved.

    Only SUCCESS and PANIC tests get here; every other verdict was settled at
    compile time. Returns `(passed, message, note)`, where `note` is anything the
    runner did that the reader must be told about even when the test passed.
    """
    run_success, run_rc, run_stdout, run_stderr, note = run_executable(Path(exe_path))

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
    if test.expected_exit is not None:
        # design 221: the status IS the assertion, so it is judged before the
        # generic "did it exit 0" verdict — a test asserting exit 7 must not be
        # reported as an execution failure for having done exactly that.
        if run_rc != test.expected_exit:
            got = ("no status (the run never completed)" if run_rc is None
                   else f"status {run_rc}"
                   + (f" (killed by signal {-run_rc})" if run_rc < 0 else ""))
            return False, (f"Expected exit status {test.expected_exit}, got "
                           f"{got}\n{run_stderr[:500]}"), note
    elif not run_success:
        return False, f"Execution failed:\n{run_stderr[:500]}", note

    # design 158: substring assertions on a successful run's stdout, checked IN
    # ORDER — each match starts where the previous one ended. Order is half of
    # what a structured output (a backtrace, a tree) is asserting, and a set of
    # independent substrings would pass on a shuffled dump.
    cursor = 0
    for want in (test.expected_output_contains or []):
        found = run_stdout.find(want, cursor)
        if found < 0:
            where = ("out of order (it appears earlier)"
                     if want in run_stdout else "missing")
            return False, (f"Output should contain {want!r} — {where}\n"
                           f"Got:\n{run_stdout[:2000]}"), note
        cursor = found + len(want)

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


def _worker_loop(conn, verbose: bool, run_dir: Path, seed: int):
    """Persistent worker body: import sawc + build the builtin namespace once,
    then COMPILE tasks in-process until the sentinel arrives. A worker never
    executes a test binary — that happens back in the main process, on the
    execution threads, once the binary has settled.

    Each task is `(index, TestCase)`; each reply is `(index, CompileOutcome)`.
    The index lets the main process match a reply to its test without shipping
    the (already-known) TestCase back. `run_dir` is this invocation's
    `.build/test_runner_<stamp>/` (design 220 D2) — a `Path` crosses the
    spawn boundary fine (it is picklable), and stays constant for the
    worker's whole lifetime, so it is passed once here rather than per task.

    `seed` is the PYTHONHASHSEED this worker's OWN interpreter was spawned
    under (design 220 D1) — set in the parent's environment right before
    `Process.start()`, so it is already in effect by the time this function
    runs; passed explicitly too, both so `compile_test` can stamp it onto a
    manifest entry without this process re-reading its own environment, and
    so the recorded value can never drift from what the spawn actually used.
    """
    _init_in_process(verbose)
    try:
        while True:
            task = conn.recv()
            if task is _WORKER_DONE:
                break
            index, test = task
            outcome = compile_test(test, compile_saw_in_process, run_dir, seed)
            conn.send((index, outcome))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        conn.close()


def _compile_parallel_in_process(tasks, num_workers, verbose, on_result, run_dir: Path):
    """COMPILE-STAGE driver: compile `tasks` (a list of `(index, TestCase)`
    pairs — the caller has already carved out any carry-forward hits, see
    `run_tests_locally`) across `num_workers` persistent workers.

    `on_result(index, outcome)` is called on the main process as each compile
    finishes, for live progress. A worker that dies mid-task (e.g. an
    LLVM-level abort on a compiler bug) leaves its task's slot filled with a
    synthesized settled failure, so the run never hangs and never silently
    drops a test.

    Design 220 D1: each worker is spawned under its OWN randomly drawn
    PYTHONHASHSEED. `multiprocessing`'s spawn start method has no per-Process
    `env=` override, so the only way to hand a child a distinct environment is
    to mutate the PARENT's `os.environ` right before that child's `.start()`
    — safe here because every `.start()` in this loop runs sequentially, on
    the main thread, before any compiling begins. The parent's own
    environment is restored once every worker is up, so nothing after this
    loop (a subprocess-fallback compile, a linker invocation) inherits a
    leftover worker seed.
    """
    ctx = multiprocessing.get_context('spawn')
    task_iter = iter(tasks)

    saved_hashseed = os.environ.get('PYTHONHASHSEED')
    conns, procs = [], []
    for _ in range(min(num_workers, len(tasks))):
        # 0 would DISABLE hash randomization, masking exactly the class of
        # emission-order bug this whole scheme exists to keep reproducible
        # (irdet's seed_a()/seed_b() carry the identical comment).
        seed = random.randint(1, 2**31 - 1)
        os.environ['PYTHONHASHSEED'] = str(seed)
        parent, child = ctx.Pipe()
        p = ctx.Process(target=_worker_loop, args=(child, verbose, run_dir, seed),
                        daemon=True)
        p.start()
        child.close()  # only the worker holds the child end
        conns.append(parent)
        procs.append(p)
    if saved_hashseed is None:
        os.environ.pop('PYTHONHASHSEED', None)
    else:
        os.environ['PYTHONHASHSEED'] = saved_hashseed

    # `index` in every task/reply pair is the GLOBAL index into the caller's
    # original `tests` list (not a position within THIS call's `tasks`, which
    # may be a strict subset once carry-forward has carved entries out) — so
    # tracked as a set of outstanding global indices, not a `len(tasks)`-sized
    # array a worker's reply could fall outside of.
    pending = {index for index, _ in tasks}

    def feed(conn) -> bool:
        """Send the next task to `conn`; return False (and send the sentinel) if
        the work is exhausted."""
        nxt = next(task_iter, None)
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

    while active:
        for conn in multiprocessing.connection.wait(list(active)):
            try:
                index, outcome = conn.recv()
            except EOFError:
                # Worker exited unexpectedly with a task outstanding.
                active.discard(conn)
                continue
            pending.discard(index)
            on_result(index, outcome)
            if not feed(conn):
                active.discard(conn)
                conn.close()

    for p in procs:
        p.join()

    # Anything still pending belongs to a worker that died mid-task (e.g. an
    # LLVM-level abort) without ever replying — a definite, build-breaking
    # result for it, rather than a test that silently vanishes from the run.
    for index in pending:
        on_result(index, CompileOutcome(
            settled=True, passed=False,
            msg="worker process died during compilation (no result returned)"))


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


def run_tests_locally(tests, args, in_process, compile_fn, jsonl=None,
                      run_dir: Optional[Path] = None,
                      prev_run_dir: Optional[Path] = None,
                      prev_manifest: Optional[dict] = None,
                      global_max_mtime: float = 0.0,
                      manifest_out: Optional[dict] = None):
    """Compile and run `tests` on THIS machine, returning one
    `(test, status, msg, note)` per test.

    This is the whole pre-design-160 runner, unchanged in what it does and now
    callable more than once: a `--remote` run calls it for the local shard, and
    again for whatever the worker did not answer for. `run_dir` is this
    invocation's `.build/test_runner_<stamp>/` (design 220 D2); every compile
    path below writes there instead of a flat `.build/`.

    `prev_run_dir` / `prev_manifest` / `global_max_mtime` are design 220
    D1/D3's carry-forward inputs (the previous generation's directory and
    manifest, and this run's once-computed staleness bound); `manifest_out`
    is the CALLER's dict, mutated in place with an entry for every test this
    call resolves via carry-forward or a fresh in-process compile — a
    `--remote` run's local share and its recovered-share call both write into
    the same dict so `main()` gets one complete manifest either way.
    """
    if run_dir is None:
        run_dir = Path('.build')
    if prev_manifest is None:
        prev_manifest = {}
    if manifest_out is None:
        manifest_out = {}
    num_workers = args.jobs if args.jobs else os.cpu_count()
    if args.sequential:
        num_workers = 1

    # design 220 D3: resolve carry-forward hits FIRST, in the main thread —
    # a stat plus a couple of hardlinks per hit, fast enough to do serially
    # before any worker spawns. Everything else below operates on `remaining`
    # (the tests that still need a real compile); carry-forward hits are fed
    # through `_on_compiled` directly, further down, so they share every
    # printing/queueing/manifest-collection path a real compile uses.
    carry_forward_hits = []   # (index, CompileOutcome)
    remaining = []            # (index, TestCase)
    for i, test in enumerate(tests):
        outcome = try_carry_forward(test, run_dir, prev_run_dir, prev_manifest,
                                    global_max_mtime)
        if outcome is not None:
            carry_forward_hits.append((i, outcome))
        else:
            remaining.append((i, test))

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

    reused = [0]   # carry-forward hits, out of compiled[0] (design 220 D3)

    def _on_compiled(index, outcome):
        """Called on the main thread as each compile finishes — including a
        carry-forward "compile", which is just a hardlink and reaches here
        the same way, so manifest collection and progress printing need only
        one path each rather than a copy for each origin.
        """
        if outcome.manifest_seed is not None:
            manifest_out[repo_path(tests[index])] = ManifestEntry(
                seed=outcome.manifest_seed, ll_name=outcome.manifest_ll_name,
                mtime=outcome.manifest_mtime)
        with print_lock:
            compiled[0] += 1
            if outcome.reused:
                reused[0] += 1
            if outcome.settled:
                verdicts[0] += 1
                _settle(index, outcome.passed, outcome.msg,
                        f"[{verdicts[0]}/{len(tests)}] ")
                return
            queued[0] += 1
            symbol = REUSED_SYMBOL if outcome.reused else COMPILED_SYMBOL
            print(f"{Colors.DIM}({compiled[0]}/{len(tests)}){Colors.RESET} "
                  f"{symbol} {tests[index].name}")
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
    reuse_note = (f"; {len(carry_forward_hits)} reused from the previous run"
                 if carry_forward_hits else "")
    print(f"{Colors.BOLD}Compiling{Colors.RESET} {len(tests)} test(s) ({how}); "
          f"each binary runs {lag:g}s after it lands "
          f"({'sequentially' if args.sequential else f'{run_workers} execution workers'})"
          f"{reuse_note}.")
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
        # Carry-forward hits first — each is already a finished CompileOutcome
        # (a hardlink, not a compile), so they go straight through the same
        # funnel a real compile's result does.
        for index, outcome in carry_forward_hits:
            _on_compiled(index, outcome)

        if args.sequential:
            # Sequential. In-process still amortizes bootstrap: sawc is imported
            # and the builtin namespace built once in THIS process. No per-worker
            # seed here (there is only the one process, already running under
            # whatever seed it started with) — design 220 D1 is scoped to the
            # persistent-worker pool below, so a sequential run's compiles carry
            # no manifest entry.
            if in_process:
                _init_in_process(args.verbose)
            for index, test in remaining:
                _on_compiled(index, compile_test(test, compile_fn, run_dir))
        elif in_process:
            # PERSISTENT worker processes, each importing sawc + building the
            # builtin namespace once and then compiling many tests in-process.
            _compile_parallel_in_process(remaining, num_workers, args.verbose,
                                         _on_compiled, run_dir)
        else:
            # --subprocess: the pre-design-115 path. Each compile spawns a sawc.py
            # subprocess, so threads (not processes) suffice to overlap them. No
            # manifest entries here either — the CLI subprocess never requests
            # the optimized-IR sidecar.
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(compile_test, test, compile_fn, run_dir): i
                           for i, test in remaining}
                for future in as_completed(futures):
                    _on_compiled(futures[future], future.result())
    finally:
        # However the compile side ended, the execution side must be told, or
        # its workers park on an empty queue forever.
        settle_queue.close()

    t1 = time.monotonic()
    with print_lock:
        run_done = verdicts[0] - (len(tests) - queued[0])
        reused_count = reused[0]
    reuse_summary = (f" ({reused_count}/{compiled[0]} reused, "
                     f"{100.0 * reused_count / compiled[0]:.0f}%)"
                     if compiled[0] else "")
    print(f"\n{Colors.BOLD}Compiles complete{Colors.RESET} in {t1 - t0:.1f}s{reuse_summary} — "
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


def run_split(tests, args, in_process, compile_fn, jsonl, notes, origins,
             run_dir: Optional[Path] = None,
             prev_run_dir: Optional[Path] = None,
             prev_manifest: Optional[dict] = None,
             global_max_mtime: float = 0.0,
             manifest_out: Optional[dict] = None):
    """Run `tests` across this machine and a worker, and return every verdict.

    The shape of this function is the design's hard requirement: nothing about
    the worker may cost the run a verdict. Each step that can fail — resolving
    the token, reaching the worker, packing the tree, streaming results —
    appends a note and falls back to running the work here. Remote-compiled
    tests never populate `run_dir`: design 220 D3 excludes remote-sharded
    files from the manifest rather than trusting artifacts that never
    touched the local tree.
    """
    sys.path.insert(0, str(REPO_ROOT / 'tools'))
    import worker_client
    import worker_proto

    def all_local(why):
        notes.append(why)
        results = run_tests_locally(tests, args, in_process, compile_fn, jsonl,
                                    run_dir, prev_run_dir, prev_manifest,
                                    global_max_mtime, manifest_out)
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
                                in_process, compile_fn, jsonl, run_dir,
                                prev_run_dir, prev_manifest, global_max_mtime,
                                manifest_out)
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
                                      in_process, compile_fn, jsonl, run_dir,
                                      prev_run_dir, prev_manifest,
                                      global_max_mtime, manifest_out)
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

    print(f"{Colors.BLUE}{Colors.BOLD}Discovering tests...{Colors.RESET}")
    tests = select_tests(args, examples_dir)
    if tests is None:
        return 1

    print(f"Found {len(tests)} test(s)\n")

    if not tests:
        print("No tests found!")
        return 1

    # design 220 D2: every invocation gets its own build directory, published
    # by an atomic symlink flip once it completes — never a flat `.build/`
    # that two overlapping invocations, or a killed run, could leave torn.
    build_root = Path('.build')
    build_root.mkdir(exist_ok=True)
    run_name = make_run_stamp()
    run_dir = build_root / run_name
    run_dir.mkdir(parents=True)

    # design 220 D1/D3: resolved ONCE, before this run's own flip can move
    # `test_runner_last` — carry-forward reads a fixed prior generation for
    # this whole invocation, never one that changes mid-run. Absent on a
    # clean checkout or if every past run died before publishing, which is
    # the "no manifest present" case D4 requires irdet to degrade cleanly on.
    prev_run_dir = resolve_last(build_root)
    prev_manifest = read_manifest(prev_run_dir)
    global_max_mtime = compute_global_max_input_mtime()
    manifest_out = {}

    jsonl = JsonlSink(args.jsonl)
    notes, origins = [], {}
    try:
        if args.remote:
            results = run_split(tests, args, in_process, compile_fn, jsonl,
                                notes, origins, run_dir, prev_run_dir,
                                prev_manifest, global_max_mtime, manifest_out)
        else:
            results = run_tests_locally(tests, args, in_process, compile_fn,
                                        jsonl, run_dir, prev_run_dir,
                                        prev_manifest, global_max_mtime,
                                        manifest_out)
    finally:
        jsonl.close()

    results.sort(key=lambda r: r[0].name)

    # Print summary
    all_passed = print_summary(results, args.verbose, origins=origins,
                               notes=notes)

    # The manifest is written into the run directory BEFORE publish, so the
    # generation `publish_run` flips onto `test_runner_last` already carries
    # a complete, consistent manifest — never a window where the symlink
    # points at a run whose manifest is still being written.
    write_manifest(run_dir, manifest_out, global_max_mtime)

    # Publish LAST, after every verdict is in: reaching here means the run
    # completed (didn't crash, wasn't killed), which is the only thing that
    # makes this generation fit to publish — a red suite is still a completed
    # one and still publishes, so `test_runner_last` always reflects the most
    # recent COMPLETED run rather than only the most recent green one.
    pruned = publish_run(build_root, run_name)
    pruned_note = f", pruned {len(pruned)} old generation(s)" if pruned else ""
    print(f"Published {run_name} as {LAST_LINK_NAME}{pruned_note} "
          f"({len(manifest_out)} manifest entr{'y' if len(manifest_out) == 1 else 'ies'}).")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

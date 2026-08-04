# Design 115 — test runner: persistent compile workers (queued Aug 4)

User direction (Aug 4): suite wall-clock (~1 min, 964 tests, growing
with SOS work) needs attention. Measured breakdown (lead, Aug 4,
trivial test): 0.65 s per compile, of which ~250 ms is FIXED overhead
repeated per test — Python interpreter start, llvmlite import (24 ms),
sawc import (26 ms), builtin/std namespace rebuild (114 ms) — plus a
~200 ms clang link; RUNNING a test binary is ~0. The runner already
parallelizes, but each test spawns a fresh `sawc.py` subprocess.

DECISION (user, Aug 4): attack the fixed overhead with persistent
compile workers — do NOT merge test programs into combined binaries.
Merging is held in reserve (it breaks per-test semantics: 163
compile-error tests, abort-expecting tests, per-test EXPECT stdout,
COMPILE-FLAGS variants, hang isolation, failure attribution — the
agent-workflow exit criterion) and is revisited only if per-test BODY
compile time ever dominates.

## Scope

1. Rework test_runner.py: N persistent worker PROCESSES
   (multiprocessing), each importing llvmlite/sawc ONCE and building
   the builtin namespace ONCE, then compiling its share of tests
   in-process via the existing compile_saw() API. Binaries are still
   produced per test and still RUN as separate subprocesses (same
   timeouts, same process-group kill) — isolation of test EXECUTION
   is unchanged; only compiler bootstrapping is amortized.
2. Re-entrancy audit: fresh TypeChecker/CodeGenerator per compile in
   one long-lived process. The compiler already instantiates multiple
   passes per process for module deps, so this is likely near-true;
   audit module-level mutable state (codegen counters, lexer/parser
   globals, llvmlite init) and fix or isolate what leaks between
   compiles. Any non-obvious global found is a tracker-worthy
   discovery (it would bite the future compile-server/LSP too).
3. Builtin namespace reuse: build once per worker, then reuse
   per test — deep-copy per compile OR rebuild if copying is unsafe/
   slower (typecheck mutates namespaces; MEASURE both, pick the
   fastest that keeps tests bit-identical).
4. Error tests in-process: examples/errors/ asserts on compiler
   diagnostics; the in-process path must produce diagnostic text
   IDENTICAL to CLI output (capture the reporter, not stderr). If
   fidelity is at risk, error tests may stay on the subprocess path —
   163 tests' overhead is acceptable; correctness of assertion is not
   negotiable.
5. Preserve the full runner surface: -f multi-pattern filter,
   --sequential, verbose, per-test COMPILE-FLAGS incl. {TESTDIR} and
   --module-path (the in-process API must accept the same flags),
   xfail resolution, summary format. Keep the old spawn-per-test path
   behind a flag (--subprocess) for debugging runner-vs-compiler
   discrepancies.
6. Acceptance: BOTH modes produce the identical pass/fail/xfail set
   over the full suite (diff them in CI once); report before/after
   wall-clock in the final commit message. Bootstrap loop untouched.

## Non-goals

Merging test programs (reserve, above); sawc CLI changes; link
caching; blade test harness changes; a daemon/compile-server (this
brief's worker pool is the stepping stone, not the product).

Bars: full suite zero xfails + bootstrap green per commit; per-unit
commits; linear history; no attribution trailers; foreground suites;
interruption-safe; new discoveries tracker-flagged, not scope-crept.
SEQUENCING: dispatch AFTER design 113 lands (113 rewrites the codegen
internals whose re-entrancy this depends on — auditing them mid-flight
would be wasted work). May run concurrent with 114 (disjoint files:
test_runner.py vs std/typechecker/examples).

# Design 156 — two-stage test runner (compile all, then execute all)

**Status: APPROVED (user, Aug 6: "can we refactor the test runner to
compile everything and then execute everything? 2 stages should let
the binary settle"). Harness-only — dispatches immediately, concurrent
with the DF-146d agent (disjoint surfaces). Closes DF-149b.**

## Decision [user]

`test_runner.py` becomes two phases: PHASE 1 compiles every test
(in-process path unchanged — that speed matters), collecting binaries
and compile verdicts; PHASE 2 executes every binary and judges output.
Error/skip-directive tests are compile-only and settle in phase 1.

This is the structural DF-149b fix: the SIGTRAP was the kernel
validating a just-written Mach-O's code signature at exec — the
in-process path wrote and exec'd within microseconds. Two phases put
the rest of the compile sweep between any write and its exec.

## Pins

1. **DF-149b backstops still land** (both cheap, and a filtered
   `-f two_tests` run has no settle window): (a) the binary is
   written to a unique temp name and RENAMED into place — a fresh
   vnode, killing the stale-signature-cache case; (b) a
   retry-once-on-signal-death in `run_executable` that REPORTS the
   retry in the test's output line (a silent retry could mask a real
   crash — never). With (a)+(b) in, DF-149b closes.
2. **Phase-1 parallelism unchanged** (persistent workers, in-process
   compile); phase 2 runs binaries with the same worker count.
   Failure reporting may batch per phase, but every failure still
   names its test, and the summary format keeps its shape (agents and
   the Makefile parse the tail).
3. **No behavior change to verdicts**: same tests pass/fail/skip for
   the same reasons; `-f` filtering, `// COMPILE-FLAGS:`,
   `// EXPECT:` directives, and `--subprocess` all keep working.
   `--subprocess` also goes two-phase (uniformity — the phases are
   about ORDER, not the compile transport).
4. Suite wall-clock should not regress meaningfully; report the
   before/after timing in the summary.

## Tests / gates

The suite is its own test. Prove DF-149b's fix by the 156 battery
running beside a saturating load (e.g. `irdet --all`) without a
spurious signal death — the exact condition that reproduced it ~1/12.
Full battery: suite (zero xfails), lexdiff, astdiff, irdet --all
(venv), bootstrap, sos_runner. Tracker: close DF-149b with the fix
shape that landed.

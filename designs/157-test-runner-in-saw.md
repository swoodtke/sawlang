# Design 157 — the test runner in Saw (devtools stage 2)

**Status: APPROVED (user, Aug 6: "also, saw'ify the test runner?").
Devtools track, AFTER 155 (irdet port) — the runner is the bigger,
higher-traffic tool; irdet proves the pattern first. Builds on 156's
two-stage shape.**

## Decision [user] + the honest cost pin

Port `test_runner.py` to a Saw package (`devtools/sawtest/`),
reproducing 156's two-phase runner: discovery, directive parsing
(`// EXPECT:`, `// COMPILE-FLAGS:` with `{TESTDIR}`), phase-1 compile
fan-out, phase-2 execution + output judgment, `-f` multi-pattern
filter, summary format, exit codes.

**The cost pin (flagged to the user at approval):** the Python
runner's speed is its IN-PROCESS compile path — workers import the
compiler once. A Saw runner must SPAWN `sawc.py` per test (~1400
interpreter startups), likely ~1 min → ~3 min for the full suite.
That cost disappears when the compiler itself is a Saw binary (the
rewrite track's endpoint), at which point the port is strictly
better. Therefore:

1. **Parity is the gate, defaulting is a measurement**: the Saw
   runner must produce verdict-for-verdict parity with the Python
   runner over the whole corpus (same passes, fails, skips, exit
   code). It becomes the DEFAULT runner only when its full-suite
   wall-clock is within ~1.5x of the Python runner's — otherwise the
   Python runner stays default and the Saw one runs in CI-style
   parity mode until the self-hosted compiler closes the gap. Record
   the measured numbers in the tracker either way.
2. **No compile-server in v1.** A persistent Python compile daemon
   bridged over pipes would recover the speed but adds a protocol and
   a failure mode to the most-trusted tool in the repo; defer unless
   the measurement demands it. If bidirectional child-process
   streaming turns out to be needed (or merely missed), file it as a
   G-finding against std.process — that gap is a product of this
   port, same as Command.env is of 155.
3. DF/G findings are an explicit product (rewrite-decision
   instrument, same as 116/155). Expected stressors: directive
   parsing over file heads, process orchestration at scale,
   worker-pool patterns over TaskGroup, output capture volume.

## Tests / gates

The parity sweep IS the test (both runners over the corpus, verdicts
diffed). Full battery on the final tree: suite (zero xfails) — run
via BOTH runners at the parity gate — lexdiff, astdiff, irdet --all
(venv), bootstrap, sos_runner.

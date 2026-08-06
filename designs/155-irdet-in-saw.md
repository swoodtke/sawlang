# Design 155 — irdet in Saw (first devtools port)

**Status: PROPOSED by the user (Aug 6: "this seems like a good
candidate for saw-ification, no?"), briefed with my scheduling pin —
post-M1, the WARM-UP for the rewrite track (a small, complete tool
port before the parser port commits to a compiler stage). Veto or
reorder freely.**

## Why irdet

`tools/irdet.py` (just parallelized, `b71c36d`) is small, has a crisp
spec (compile each example twice under differing `PYTHONHASHSEED`,
byte-compare the IR, zero mismatches), and exercises exactly the std
surfaces a compiler-in-Saw will need: process spawning, env control,
file IO, byte comparison, thread-parallel fan-out, CLI args, timing.
Its parity gate is mechanical: run both tools over the corpus, demand
identical verdicts and exit codes.

## Units

1. **`Command.env(key, value)`** — the load-bearing std gap found by
   this port: `std.process` has `arg`/`run`/`output` and NO
   environment control, and per-child `PYTHONHASHSEED` IS the tool.
   Same discipline as `arg` (one call = one variable, nothing parsed
   or expanded); child inherits the parent env plus overrides.
   Runtime-seam impact (spawn ABI) is the agent's to assess — if the
   seam must grow, that is a finding for rt/ABI.md, not a workaround.
   Lands as its own unit with tests, independent of the port.
2. **The port**: a Saw package (suggest `devtools/irdet/`, blade
   package — the selfhost/lexer precedent) reproducing the tool:
   `git ls-files` + sawc invocations via `Command`, negative-test
   filtering via `std.file` head reads, byte comparison via `Data`,
   parallelism via `TaskGroup(threads: N)` mirroring the Python
   thread pool (per-task unique `-o` under `.build/irdet/`),
   deterministic output order, `-n/--all/-v/-j` CLI. It still invokes
   the PYTHON sawc (the oracle) — the tool is Saw, the compiler under
   test is not; that stays true through the whole rewrite track.
3. **Parity + replacement**: both tools over the corpus → identical
   verdicts, skip counts, exit codes. On parity, the Saw binary
   BECOMES the gate tool (Makefile + CLAUDE.md testing section +
   brief boilerplate updated) and the Python irdet is deleted — one
   tool, no drift. DF/G findings from writing it are an explicit
   product (the rewrite-decision instrument, same as 116).

## Tests / gates

Unit 1: env round-trip test (child echoes the var), inheritance +
override, `blade test` coverage if Command has app-level tests. Unit
2/3: the parity sweep is the test. Full battery: suite (zero xfails),
lexdiff, astdiff, irdet --all (run with BOTH tools at the parity
gate), bootstrap, sos_runner.

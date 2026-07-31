# Design 69 — Developer experience: debug info (T1f) + CI (queued Jul 31)

## Part 1 — debug info (T1f)
- Emit DWARF line tables via llvmlite's debug-info metadata (DIFile/
  DICompileUnit/DISubprogram/DILocation): every emitted instruction
  carries the source line of the Saw statement/expression it lowers.
  Scope v1: LINE TABLES ONLY (no variable info) — the goal is
  backtraces and debugger stepping, not watch windows.
- On by default (line tables are cheap); no flag needed unless it
  perturbs the O1 pipeline — report if a flag was required.
- Panics gain source location: `panic at foo.saw:42` — thread the
  line through the existing saw_panic seam (message prefix is fine).
  assert already prints its line; unify the format.
- Coroutine-transformed functions map to the ORIGINAL source lines
  (the transform preserves line info on rewritten nodes — verify,
  fix where synthesized nodes carry line 0).
- Acceptance: `lldb ./prog` breakpoint on a .saw line hits; `bt`
  shows saw function names + file:line for a panic under lldb; a
  scratch probe documents both (harness can't run lldb — probe
  evidence in the report + an --emit-ir test asserting !DILocation
  presence).

## Part 2 — CI (GitHub Actions)
- `.github/workflows/ci.yml`: ubuntu-latest + macos-latest; setup
  Python 3.12+ (3.14 if available), pip install llvmlite, run
  `test_runner.py`, blade tests, libs tests, and
  `tools/blade_bootstrap.py`. Linux is the NEW target here — fix
  small portability breaks it surfaces (report them); if a Linux fix
  is large, mark the job allow-failure and ledger it precisely.
- Badge in README. Keep the workflow minimal (no caching games v1).

Bars: full suite (baseline = post-68 count) + blade/libs + bootstrap
green per commit; zero xfails. Standing policy: fix user-facing bugs
on discovery unless ambiguous. Tracker: T1f + CI items closed,
design 69 landed. Docs: spec note (debug info status), README badge,
saw-lang skill unchanged (not a language feature).

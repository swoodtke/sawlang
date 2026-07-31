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

## Tracker

- **Part 1 (debug info / T1f) — LANDED.** DWARF line tables on by
  default via llvmlite debug metadata: module flags (Debug Info
  Version 3 / Dwarf Version 4) + one DICompileUnit (in !llvm.dbg.cu),
  a DIFile per source (multi-module correct), a DISubprogram per user
  function/method (readable Saw name + linkageName), and a DILocation
  per statement/tail-expr attached through `builder.debug_metadata`.
  New `sawc/codegen/debuginfo.py` (DebugInfoMixin); the active
  subprogram is looked up by the current builder's llvm function name,
  so nested closure/mono generation can't bleed scope (re-entrancy
  safe). Line 0 is inherited (no gaps) — coroutine-transformed
  `resume` maps to ORIGINAL source lines (verified: `__Frame_main_resume`
  → lines 13/14/16). Panic/assert unified: "panic at FILE:LINE: {msg}"
  through the saw_panic seam (`_panic_location_prefix`). NO flag needed
  — DILocations survive the O1 pipeline (the optimizer's own artificial
  `line: 0` records at O1 are normal DWARF). lldb evidence: breakpoint
  on `dbg_panic.saw:3` resolves (2 locations); `image lookup -n boom`
  → `boom at dbg_panic.saw:2:5`, panic → `dbg_panic.saw:3:9`, inlined
  frame reconstructed (`main + 4 [inlined] boom at dbg_panic.saw:3:9`).
  Tests: `examples/panic_source_location.saw` (runtime format) +
  `tools/test_debug_info.py` (--emit-ir !DILocation/DISubprogram at
  O0+O1). macOS caveat: source-level `run`/backtrace needs the .o kept
  (debug map) or a .dSYM; Linux embeds DWARF in the executable directly.

- **Part 2 (CI) — LANDED.** `.github/workflows/ci.yml`: ubuntu-latest +
  macos-latest matrix (fail-fast off), Python 3.12 (llvmlite 0.48 wheels
  on both; 3.14 has no manylinux wheel yet), `pip install -r
  sawc/requirements.txt`, clang installed on Linux. Steps: test_runner.py,
  tools/test_debug_info.py, tools/blade_bootstrap.py (blade build + blade
  tests), then semver/toml lib `blade test`. README CI badge added. Linux
  portability fixes surfaced by analysis (Linux is a new target; can't run
  it from the macOS dev box): (1) **PIC reloc** — hosted `_make_target_machine`
  now requests `reloc='pic'` so `clang obj.o -o exe` links as PIE on modern
  Linux (LLVM's x86_64-linux default reloc is non-PIC → PIE link error);
  macOS is always PIC so this is a no-op, freestanding keeps the default.
  (2) **blade_bootstrap** used a hardcoded `.venv/bin/python`; now
  `sys.executable` so it runs in CI (no virtualenv). Both jobs are required
  (no allow-failure); the workflow is unverified from macOS locally, so a
  first CI run may surface small follow-ups. Codegen was already
  Linux-aware (`_is_apple_triple` gates stdout symbol + CLOCK_MONOTONIC id;
  pthread wrappers resolve on glibc). design 69 landed.

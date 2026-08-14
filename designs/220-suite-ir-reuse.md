# Design 220 — recorded-seed suite compiles, per-run artifacts, irdet reuse

**Status: RULED (user, Aug 14), queued behind 218 stages 1-2 integration.**
Tooling-track brief (test_runner + irdet + battery contract; borders designs
115, 155, 156, 160). Every decision below was made in conversation with the
user on Aug 14; the units execute, they do not re-decide.

## What it buys

1. **Reproducible hash-order flakes, standalone value.** Today a suite
   failure caused by hash-order-dependent emission is unreproducible: the
   worker's `PYTHONHASHSEED` dies with the process. Recording seeds makes
   any such failure a `PYTHONHASHSEED=<recorded>` replay.
2. **irdet --all at roughly half cost in the steady state.** The gate's cost
   is compiling the corpus twice (measured: 728 examples/1128.6s tool time at
   design 146; ~1150 examples/755s at the Aug-14 stage-1 gate). The suite
   already compiled those files; reusing its IR leaves irdet one compile +
   a byte-compare per file. After a compiler change the scheme degrades
   gracefully to today's cost (everything stale, compile both sides).
3. **No torn artifact state.** Publish-then-flip means a killed run (the
   Aug-13 529 drops killed three) leaves the last published run intact, and
   a reader never sees run N's manifest pointing at run N+1's half-written
   files.
4. **Seed-pair diversity.** irdet's fixed 1-vs-424242 pair becomes a fresh
   random pair per gate run — strictly better coverage of the class.

## Decided points (the rulings)

**D1 — seeds are per WORKER, recorded.** Design 115 makes suite compiles
in-process in persistent worker processes (the ~250 ms bootstrap
amortization); the hash seed is fixed at interpreter start, so a per-compile
seed is impossible without forfeiting 115. Each worker process is spawned
under its own randomly drawn `PYTHONHASHSEED`; the manifest records, per
compiled file, the seed of the worker that compiled it. (~10 distinct seeds
per run, fresh every run — the fuzz axis survives, and becomes replayable.)

**D2 — per-run output directory, atomic flip.** The runner writes all build
products (binaries, `.ll`, manifest) under `.build/test_runner_<stamp>/`
(timestamp+pid; pid alone recycles). On successful completion it publishes
by symlink flip: create `test_runner_last.tmp` → rename over
`test_runner_last`. `ln -sfn` is unlink-then-create and is NOT the
mechanism; the flip is `os.symlink` + `os.replace`. Readers (irdet, humans)
resolve the symlink to a real path ONCE at start and hold it. Pruning: after
a successful flip, delete all per-run dirs beyond the newest K=3 (covers any
in-flight reader of the previous run; suite runs themselves are serialized
by the suite lock). A run that dies before the flip publishes nothing and is
pruned as an unflipped orphan by the next run.

**D3 — staleness is mtime-based, with the three known holes closed.** A
file's artifact is fresh iff its output is newer than every input. The input
set is: the example file itself, every file under `sawc/` (py + std .saw +
builtin.saw + rt/), AND (a) the DIRECTORIES' mtimes under `sawc/` — a
deletion bumps no surviving file's mtime but does bump its parent dir;
(b) the venv's llvmlite `dist-info` mtime (or version string) — IR depends
on the llvmlite version and a venv upgrade touches no repo file;
(c) `test_runner.py` itself. Compute max-input-mtime once per run, not per
file. A fresh artifact is carried into the new run dir by HARDLINK from the
previous run (content-identical, so shared inodes are correct; K retained
runs cost disk only for what actually recompiled). Remote-sharded compiles
(design 160) either ship their IR + seed back into the run dir or their
files are excluded from the manifest — irdet must only trust artifacts whose
stamp it can check against the LOCAL tree.

**D4 — irdet consumes the manifest; the verify step never silently heals.**
For each corpus file: if `test_runner_last`'s manifest carries a fresh
artifact, irdet compiles ONCE under a seed drawn to differ from the recorded
one and byte-compares. On any mismatch it recompiles BOTH sides fresh in
subprocesses — at the recorded seed A and its own seed B — and distinguishes
three outcomes:
  - fresh-A == artifact, fresh-A != fresh-B → **true nondeterminism**,
    reported exactly as today;
  - fresh-A != artifact → **violated invariant** (stale stamp, or
    in-process-vs-subprocess divergence — design 115's audited bit-identity
    broken), reported as its OWN failure category, never absorbed;
  - fresh-A == fresh-B == artifact → transient (e.g. the artifact raced a
    prune); count and report as reuse-fallback, verdict from the fresh pair.
A cache bug can therefore only cost time or produce a red that names
itself — never a false green. Files with no fresh artifact (COMPILE-FLAGS,
module paths, skips, remote-shard exclusions) take today's compile-both
path; the reusable set is the standalone-default-flag intersection, which is
exactly the set irdet checks anyway.

**D5 — the suite emits IR.** Reused artifacts require `--emit-ir` on suite
compiles. Unit 0 measures both deltas (compile time, disk for the `.ll`
corpus) before the layout lands; if disk is obnoxious, `.ll` retention can
drop to K=1 (hardlinks make K>1 nearly free only for unchanged files).

## Units

**Unit 0 — measure + consumer sweep (obligation 2).** The layout change is a
behavioral contract flip: build products move from flat `.build/<stem>` to
`.build/test_runner_<stamp>/`. Sweep who reads the old paths — the
stem-dedup scheme (test_runner.py:137), `sweep_stale_temp_products`,
battery lanes, Makefile targets, tools/ scripts, TESTING.md prose — one
paragraph of findings before any code. Measure `--emit-ir` deltas (D5).
Gate: the sweep paragraph + numbers recorded in this brief.

**Unit 1 — per-run dirs + atomic flip + prune (D2).** No manifest yet; the
suite's own behavior is the test. Gate: full suite green twice in a row
(second run exercises carry-forward-less rebuild), kill-mid-run leaves
`test_runner_last` valid, prune keeps K=3.

**Unit 2 — per-worker seeds + manifest (D1) + staleness stamp + hardlink
carry-forward (D3).** Gate: full suite green; a no-change second run reuses
(measured reuse rate reported); touching one example invalidates exactly
that file; touching a sawc file invalidates everything; a replay under a
recorded seed reproduces its artifact byte-identically (spot-check N=20).

**Unit 2 finding (STOP-DON'T-WORKAROUND, pre-existing compiler bug, not a
regression from this brief's own code): the byte-identical-replay leg of the
gate is BLOCKED.** `compile_saw()` is not self-reproducible across repeated
calls in one process, independent of `PYTHONHASHSEED` and independent of the
program compiled. Minimal repro: a 6-line one-struct program (`struct Point
{ x: Int, y: Int } / func main() { ... }`), compiled twice via
`compile_saw(..., emit_optimized_ir=True)` in the SAME process under a FIXED
seed, emits two `.ll` files that differ — `%"Vector$2$$Opt$Box$1$$Any$Resumable$GlobalAllocator.4152"`
in the first becomes `...GlobalAllocator.8430"` in the second (every
reference to the type follows). That type is the always-linked
backtrace/task-frame `Vector<Opt<Box<Any Resumable>>, GlobalAllocator>`
(design 158), present in every program regardless of what it imports, so
this is not corpus-dependent. The suffix numbers are identical across
DIFFERENT programs and DIFFERENT seeds at the same "compile number in this
process" (both a `printable_struct.saw` run and the 6-line repro produced
`.4152` on their first in-process compile and `.8430` on their second) —
confirming the driver is a per-process compile COUNT, not the seed and not
the source. `sawc/ast_nodes.py`'s `_NEXT_NODE_ID` is a module-global counter
that never resets within a process (by design, per its own docstring: it
exists so a generated name never derives from Python's `id()`, "neither
stable across runs... nor expressible in the eventual Saw port") — SOME
identity computation reachable from that backtrace-table monomorphization
still embeds a raw `node_id` in a mangled name, the same mechanism design
168 unit 3 already fixed once for collection-literal temp names
(`__collit_NNNNN` → positional naming, DF-164a) after finding it moved
`%"__collit_14189"` to `%"__collit_29638"` between two same-process
compiles. This is very likely a SIBLING of that fix at a different site,
not a one-off (brief obligation 4) — a real fix should sweep for every
remaining `node_id`-derived name, not patch this one call site. Confirmed
NOT present in fresh single-process compiles (two independent `sawc.py`
CLI invocations under the identical seed produce byte-identical output);
the class is specific to design 115's persistent workers compiling more
than one file per process, invisible to irdet's own methodology (always a
fresh subprocess per compile) until design 220's replay/reuse needed
cross-process byte identity for the first time. D4's three-way verify
(unit 3) is explicitly designed for exactly this — a mismatch here lands as
`fresh-A != artifact`, the "violated invariant" category, never a false
pass — so it does not block unit 3's own correctness gate, only depresses
the MEASURED reuse rate unit 3 reports until the underlying compiler bug is
fixed separately. Not worked around here per policy; needs a DF number and
its own fix dispatched outside this tooling-track brief.

**Unit 3 — irdet consumes the manifest (D4).** The Saw-side change
(devtools/irdet — it stays the Saw devtool; it reads the manifest, draws a
differing seed, and gains the three-way verify). Gate: `irdet --all` green
against a fresh suite run with measured reuse; a deliberately corrupted
artifact produces the invariant-violation category, not a nondeterminism
report and not a pass; `irdet --all` with NO manifest present behaves
exactly as today.

**Unit 3 finding (STOP-DON'T-WORKAROUND, pre-existing compiler bug, more
severe than unit 2's and PREDATES design 220 entirely): `irdet`'s process
exit code is not functional and never has been — the `irdet`/`irdet-all`
battery gate has been VACUOUSLY GREEN since design 155 ported the harness to
Saw.** Minimal repro (12 lines, no design-220 code involved):
```saw
import std.process.{Command}
func main() -> Int {
    var c = Command(program: "echo")
    c.arg("hi")
    guard let done = c.output() else { return 9 }
    print("ran")
    if done.success() { return 1 }
    0
}
```
Compiled and run: prints `ran`, exits **0** — not 1. `Command.output()`
suspends (TESTING.md / the saw-lang skill: "run() and output() ARE BOTH
COOPERATIVE"), which makes `main()` a coroutine transitively; a coroutine
`main() -> Int`'s returned value does not reach the process exit status,
for any value, anywhere in the function — confirmed with the CHECKED OUT,
UNMODIFIED, pre-220 `devtools/irdet/src/main.saw` (`git show HEAD~4:...`):
compiled as-is and run with a bad flag (`return EXIT_USAGE` = 2, from
`parse_options`, itself reached only because `main()` already suspends via
`tracked_examples()`'s own `Command.output()` for `git ls-files`), it exits
**0**, not 2. A SYNC `main() -> Int` (no suspending call anywhere in it)
works correctly — confirmed separately — so the break is specific to the
suspending-main + `Int` return combination; `codegen/core.py`'s special
case for `main` (`_declare_function`, ~line 2399) only hardcodes a `ret 0`
for a `-> Void` main, so a `-> Int` main's LLVM-level return type is
whatever `func.return_type` says, and something in the coroutine-lowered
path for `main` specifically loses that value between the state machine's
final `Poll::Ready` and the process's actual `exit()`. Blast radius,
swept (brief obligation 4): every `func main() -> Int` in the tree —
`selfhost/lexer/src/main.saw` (no suspending call visible in it — likely
unaffected, not independently confirmed) and four `examples/*.saw` tests
(their return value is not what test_runner checks, so the bug is inert for
them) — `devtools/bench/src/main.saw` uses a VOID main + `panic()` for its
checksum gate, unaffected by construction. `devtools/irdet` is the ONE
existing program combining a suspending `main()` with a data-driven `Int`
return depended on for pass/fail, which is exactly `battery.sh`'s
`run_irdet()` and `make irdet`/`irdet-all`'s gating mechanism. Consequence:
design 141's own mismatches were most likely caught by a human reading a
printed `MISMATCH:` line (or by the pre-155 Python `tools/irdet.py`, whose
`sys.exit` is unaffected) rather than by automated CI, and any REGRESSION
since the design-155 port would not have failed a build. Not worked around
here (there is no in-language alternative — Saw's stdlib has no explicit
`process.exit(code)` to sidestep `main`'s return value with); unit 3's own
Saw logic below is verified by READING STDOUT (the printed `MISMATCH:` /
`VIOLATED INVARIANT:` lines and summary counts), never by trusting
`irdet`'s exit code, and this brief's own gate runs report the real
mismatch/invariant counts alongside the (currently meaningless) exit
status. Needs its own DF and fix outside this tooling-track brief — likely
the highest-priority of the two findings this brief surfaced, since it
means a WHOLE BATTERY STAGE provides no automated protection today.
`tools/irdet_remote.py` is UNAFFECTED (both its local and remote checking
already read structured `--jsonl` records rather than trusting `$?` —
confirmed by re-reading `check_here`, which never even examines its
`subprocess.run(...)`'s return code), so the two-machine driver's own
pass/fail judgment stays sound; only the bare `./.build/irdetbin --all`
invocation (`battery.sh`'s `run_irdet`, `make irdet`/`irdet-all`) is
affected.

**Unit 3 gate, run at full scale (`irdet --all` against a fresh 1152-entry
suite manifest, one seed differing per file — design 220's own
`differing_seed`, deterministic since Saw has no RNG):** 1147 examples
checked, 67 skipped, **0 true-nondeterminism mismatches**, **174/1147
(15.2%) reused cleanly** (a fresh compile matched the suite's own artifact
on the first try), **968/1147 (84.4%) landed in `VIOLATED INVARIANT`** —
every one of them correctly categorized, none silently passed, none
misreported as nondeterminism, exactly as D4 specifies; this is the unit-2
finding's node_id-leak bug manifesting at corpus scale, not a defect in
unit 3's own logic (confirmed: the mandatory deliberate-corruption test
below produces the identical category through the identical code path).
Wall time: **1041.0s**, i.e. SLOWER than the 755s Aug-14 baseline
(+38%) — because 84.4% of the corpus pays the three-way verify's full
THREE compiles (reuse attempt + fresh-A + fresh-B) instead of the
baseline's two, and only 15.2% gets the intended one-compile saving. D5's
"roughly half cost in the steady state" motivation is REAL but not
currently realized: it is gated on DF-pending's node_id-leak fix landing
first, at which point the reuse rate should jump from 15% toward the
near-100% this run's clean 15.2% slice already demonstrates is achievable
(nothing about those files is special — they are almost certainly
whichever file happened to be the first each irdet worker/task compiled
in its process, matching unit 2's finding precisely). Deliberate-corruption
test (mandatory): `examples/hello.saw`'s recorded artifact was appended
with a garbage comment line and irdet re-run on it alone —
`VIOLATED INVARIANT: examples/hello.saw (recorded artifact is 25093
byte(s); a fresh recompile at its own seed (1432464053) is 25031
byte(s))` — the invariant-violation category, never a nondeterminism
report, never a pass. No-manifest test (mandatory): run against
`--only-files` with `.build/test_runner_last` absent prints "no suite
manifest -- every file compiles fresh both sides, as before design 220"
and every file takes `check_one_compile_both`, unchanged from the
pre-220 binary bit for bit (verified by running the CHECKED-OUT pre-220
binary and this one side by side on the same two files with `--only-files`
and comparing output shape).

**Unit 4 — battery + docs.** battery.sh ordering note (irdet after suite
maximizes reuse but must not REQUIRE it — D4's fallback), TESTING.md,
CLAUDE.md testing digest. Gate: full tracked battery.

**Unit 4 gate: the full tracked battery, `SAW_PYTHON=.venv/bin/python
tools/battery.sh`, no `--quick`.** 18/18 stages GREEN, 1933s total.
`suite`: 1817 passed, 27 xfailed (unchanged from every earlier run this
brief measured). `gmgate`: 51 programs across 2 lanes, 0 failing.
`bootstrap`: both library suites + the two-target layout check, ok.
`sos`: 32/32 across riscv32 + arm64. `irdet` itself printed `---> irdet ok
(1130s)` — the battery TRUSTS THIS, and it is wrong: the same run's own
stdout, three lines above the verdict, reads `969 file(s) VIOLATED THE
REUSE INVARIANT`. This is the unit-3 exit-code finding caught in the act,
inside this brief's own final gate, not a hypothetical — direct
confirmation that `battery.sh`'s `irdet` stage provides no real signal
today, independent of anything design 220 changed. Every OTHER stage's
`ok` is a genuine exit-code-backed pass. Whether to make `run_irdet` in
`battery.sh` parse its own stdout for a true verdict (mirroring
`tools/irdet_remote.py`'s `check_here`, which already does exactly this
and is unaffected) is a call left to the user: it is straightforward, but
it would flip the `irdet` stage from always-green to red-until-the-
node_id-leak-DF-is-fixed for every brief's battery run from here on, not
only this one's — a wider-blast-radius decision than "ordering note"
covers, so it is surfaced here rather than made unilaterally.

## Unit 0 findings (consumer sweep + measurements)

**Consumer sweep.** Grepped every reader of `.build/` across the tree
(`test_runner.py`, `Makefile`, `tools/battery.sh`, all of `tools/*.py`,
`TESTING.md`) for a dependency on the flat `.build/<stem>` naming the layout
flip changes. Findings:

- The stem-dedup scheme lives entirely in `test_runner.py` itself —
  `TestCase.binary_stem` (line 135), `compile_into_place`'s temp-write-then-
  `os.replace` (line 525), and `sweep_stale_temp_products` (line 575, called
  once at `main()` start). All three operate on whatever `Path` they are
  handed and carry no flat-layout assumption baked in; moving the base from
  `Path('.build')` to `Path('.build/test_runner_<stamp>')` is a one-line
  change at the `exe_path = Path('.build') / test.binary_stem` call site
  (line 898) plus wiring the run-dir through.
- `Makefile`'s `clean` target is `rm -rf .build/*` — layout-agnostic, still
  removes everything including run dirs and the `test_runner_last` symlink.
  No other Makefile target names a test_runner output path.
- `tools/battery.sh`'s `suite` stage is a bare `test_runner.py` invocation;
  every other stage (`irdet`, `bench`, `selfhostlex`) uses its own
  independent `.build/<subdir>` namespace (`.build/irdetbin`,
  `.build/benchbin_warehouse`, `.build/selfhostlex/`) and does not read
  `test_runner`'s outputs.
- Every `tools/*.py` script that touches `.build/` (`gmgate.py`,
  `test_ir_contract.py`, `test_bt_table.py`, `lexdiff.py`,
  `test_ice_breadcrumb.py`, `blade_bootstrap.py`, `sos_runner.py`,
  `sawfuzz.py`, `corodiff.py`, `test_lldb_saw.py`,
  `remote_worker_selftest.py`, `irdet_remote.py`, `test_worker.py`) owns a
  private subdirectory under `.build/` for its own compiles and never reads
  a path `test_runner.py` produced. `worker_proto.py`'s snapshot builder
  already excludes `.build` wholesale (`SNAPSHOT_EXCLUDE_SUFFIXES` /
  directory exclude list) when shipping the tree to a remote worker, so the
  layout change is invisible to design 160's remote-shard path either way —
  confirms D3's remote-shard carve-out matches what already happens today.
- `tools/test_runner_selftest.py` (not wired into any battery stage or
  Makefile target — a design-156 unit test, run by hand) imports
  `test_runner` as a module but only exercises `run_executable` and
  `SettleQueue`, neither of which touches `.build/` paths. Unaffected.
- `TESTING.md` prose (the "Test Runner Implementation" section) describes
  the flat layout by name (`examples/ffi/int_types.saw` becomes
  `.build/ffi_int_types`) — a genuine doc consumer, scheduled for the Unit 4
  docs pass.

No other consumer found. The flip is contained: `test_runner.py` changes,
`TESTING.md` prose updates in Unit 4, nothing else moves.

**A second finding, load-bearing for D5.** `_emit_object` in `sawc/sawc.py`
(shared by every `compile_saw()` caller — CLI, test_runner's in-process
path, blade, bootstrap, sos) already writes an IR sidecar to
`<output_path>.ll` on **every** compile, unconditionally, at
`optimize=False` (hardcoded, "for debugging"). `test_runner.py` already
treats `.ll` as one of the products `compile_into_place` renames into place
(`_PRODUCT_SUFFIXES`), so a `.build/<stem>.ll` file already exists after
every suite run today — 1165 of them, 358,579,913 bytes total on this
corpus. Nothing reads that path back (checked `reemitdiff.py`,
`test_debug_info.py`, `test_stable_type_id.py`, `test_ir_contract.py`: each
compiles its own target with its own `-o`, none touch a `test_runner.py`
output). It is unoptimized, pre-O1 IR — **not** what D4's byte-compare
needs, since irdet's own `--emit-ir` compiles at the default `optimize=True`
to match the O1-style default pipeline the corpus actually ships under.
D5's "the suite emits IR" therefore does not mean adding a sidecar from
nothing; it means the suite's sidecar has to become the *optimized* one.
Chosen shape for units 1-2: add `emit_optimized_ir: bool = False` to
`compile_saw()` / `_emit_object()` (default off, so every existing caller —
CLI, blade, bootstrap, sos — is untouched byte-for-byte); test_runner's
in-process compile path (`compile_saw_in_process`, a direct Python call into
the `sawc` module, not the CLI) passes `emit_optimized_ir=True`
unconditionally. No new CLI flag: the parameter is an internal API surface
`sawc.py`'s own `argparse` entry point never exposes, so CLAUDE.md's "complete
flag set" listing stays accurate unchanged. Tests that fall back to the
subprocess compile path (unmodeled `// COMPILE-FLAGS:`) simply get no
optimized sidecar and thus no manifest entry — which is exactly D4's
existing carve-out ("Files with no fresh artifact (COMPILE-FLAGS, module
paths, skips, remote-shard exclusions) take today's compile-both path").

**Measurements** (this machine, full corpus, 1817-test suite, `rm -rf
.build` between runs, suite lock held):

| | compile stage | total (+ draining) | `.build` size |
|---|---|---|---|
| baseline (today, unoptimized `.ll` sidecar as now) | 235.5s | 240.4s | 518M |
| probe: **also** emits an optimized `.ll` alongside the existing one | 243.1s | 248.0s | 834M |

Probe delta: **+7.6s compile time (+3.2%)**; the added optimized-IR corpus
alone is 328,215,005 bytes (~313 MiB) across the same 1165 files (slightly
smaller than the unoptimized corpus, as expected — O1 removes dead allocas
and unreachable code). The probe measured the *additive* cost (both
sidecars written) to isolate the marginal price of the extra
`codegen.emit_ir(optimize=True)` pass; the real Unit 1/2 implementation
*replaces* the existing unoptimized sidecar rather than adding a second
file (previous finding), so the actual per-run disk footprint stays close
to today's 518M (optimized IR is a few percent smaller than unoptimized),
not +316M. The real disk growth design 220 introduces is retaining K
generations of run directories instead of one flat `.build/` — hardlink
carry-forward (D3) makes an unchanged file free across generations, so the
K multiplier only bites the files that actually changed since the last
run. A full-corpus invalidation (any `sawc/` change) is the worst case:
up to K x ~500M until pruning catches up, which is what D5's fallback ("if
disk is obnoxious, `.ll` retention can drop to K=1") exists for. Compile
time cost (+3.2%) is small enough that K does not multiply it — IR is
emitted once at compile time regardless of how many prior generations are
kept.

## Non-goals

The 40-file `make irdet` sample keeps compiling both sides itself (it is the
cheap standalone check; coupling it to suite state buys seconds). No content
hashing — D3's mtime holes are closed structurally, and D4 makes residual
staleness self-reporting. No change to what irdet checks or to the corpus.

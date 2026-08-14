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

**Unit 3 — irdet consumes the manifest (D4).** The Saw-side change
(devtools/irdet — it stays the Saw devtool; it reads the manifest, draws a
differing seed, and gains the three-way verify). Gate: `irdet --all` green
against a fresh suite run with measured reuse; a deliberately corrupted
artifact produces the invariant-violation category, not a nondeterminism
report and not a pass; `irdet --all` with NO manifest present behaves
exactly as today.

**Unit 4 — battery + docs.** battery.sh ordering note (irdet after suite
maximizes reuse but must not REQUIRE it — D4's fallback), TESTING.md,
CLAUDE.md testing digest. Gate: full tracked battery.

## Non-goals

The 40-file `make irdet` sample keeps compiling both sides itself (it is the
cheap standalone check; coupling it to suite state buys seconds). No content
hashing — D3's mtime holes are closed structurally, and D4 makes residual
staleness self-reporting. No change to what irdet checks or to the corpus.

# Design 143 — Blade build-output directories + lockfile policy

STATUS: APPROVED (user, Aug 5). Blade-only (no sawc/ changes), so it may
run CONCURRENTLY with any compiler brief; dispatch when a slot frees.
Written in Saw — load the saw-lang skill; validate with the bootstrap
loop.

## Problem

Blade builds IN-PLACE: `builder.saw` emits `output_name` into the package
directory (its up-to-date check is literally `File.exists(output_name)`).
Consequences: artifacts sit beside source (`sos/root/sos-root.sosimg`
next to `Saw.toml` — caught in the M1 review `[user]`), every package
grows artifact gitignore patterns, stale artifacts shadow rebuild state,
and — load-bearing with M1b/arm64 on the roadmap — two TARGETS of one
package fight over a single filename in one directory.

## Decision 1 — the output directory [user]

Artifacts go under `<package>/.build/<target>/` — matching the repo's
existing `.build/` convention (sawc's cache/scratch, `-o` default),
gitignored ONCE at the repo root (`.build/` is already there). `<target>`
is the triple/profile name (pin: the sawc `--target` string, with `host`
for the default hosted build — veto-able). Everything moves onto it:
- the compile output + the up-to-date/hash check (per-target, so a
  riscv32 build never satisfies an arm64 check);
- `blade test` binaries;
- the `emit = "sosimg"` target's image;
- the bootstrap loop's stage artifacts (stage0/1/2 currently land
  wherever the loop runs them — unify under the same scheme);
- package roots lose their per-artifact gitignore lines (`*.sosimg`
  etc. — delete them; the root `.build/` rule covers all of it).
`blade clean` (if absent, add it) is `rm -rf .build/` per package.
Update tools/sos_runner.py + Makefile paths that reference emitted
artifacts; TESTING.md and the Blade section of README.

## Decision 2 — lockfile policy [user]

Applications COMMIT `Saw.lock`; libraries do NOT (the Cargo convention,
adopted): a lockfile in an app pins the reproducible build; in a library
it would fight the consumer's resolution. Blade already distinguishes
app/lib shapes via the manifest (probe: whatever field/layout marks a
binary target — record it). Sweep the tree to conformance: blade itself
and sos/root are apps (lock COMMITTED — sos/root/Saw.lock is currently
untracked on the M1 branch; flag it for that branch's revision);
libs/semver, libs/toml are libraries (no lock; add to their gitignore if
Blade writes one). Document in TESTING.md/README's Blade section.

## Tests
Bootstrap loop green with the new paths (that IS the main proof —
stage0→stage2 all reading/writing `.build/<target>/`); `blade test` on
libs finds its binaries; an up-to-date second build says so (per-target);
building the same package for two targets yields two artifacts, no
collision (can be simulated hosted with an explicit --target if cross
isn't linkable — the DIRECTORY behavior is what's under test); a stale
in-place artifact from the old convention is ignored, not trusted. Full
gate battery (suite, lexdiff, irdet, astdiff, bootstrap, sos — sos_runner
exercises the moved sosimg path).

## Exit criteria
No artifact in any package root; one root gitignore rule; per-target
subdirs; lockfile policy applied + documented; tracker line closed
(file this brief's origin as the M1-review finding).

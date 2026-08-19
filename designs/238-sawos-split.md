# Design 238 — The sawos Split: SOS Leaves the Language Repo

**Status: AUTHORED Aug 19 2026** from the coupling sweep recorded below (user:
"i want to move the sawos/sos code from this directory (sawlang) into ../sawos
— i want to retain the sawos tests and build system (blade?)"). **Queue slot:
BEFORE the M3 unit ladder** (user: "schedule it before more M3 sos work"), and
AFTER the sos riders batch — see "Scheduling" below.

**FOUR RULINGS, Aug 19 (same session):**
- **D-a RULED — imgformat moves to `libs/`.** "moving imgformat into libs is
  fine for now (make a note of the blade plugin idea since that is probably the
  way forward in the future)." The plugin is [BACKLOG], recorded as the
  probable future direction, not a dependency of this brief.
- **The downstream-CI gate is REPLACED by a standalone freestanding suite in
  sawlang** — "instead of running sawos from inside sawlang, we should create a
  stand-alone test suite which exercises the set of sawlang features needed for
  software like sawos." sawlang never checks out sawos. See "The gate,
  re-founded".
- **No shared suite lock across repos** — "they can run independently."
- **Toolchain discovery is `$PATH` first, pinned fetch second** — "the sawos
  repo should get for 'sawc' and 'blade' in the $PATH and if they don't exist,
  it should pull down swoodtke/sawlang from github and use that instead (at a
  fixed version/sha ideally so churn in sawlang doesn't break sawos)." Adopted;
  three sub-decisions it opens are D-b1..D-b3 below.

`../sawos` already exists as an empty directory. The repo this brief splits
FROM is `sawlang` (renamed from `claudes-lang`; stale absolute paths in older
briefs and tooling still say the old name).

## Why now, and not after M3

M3 is the largest planned expansion of `sos/` — six units from interruptibility
through Memory/IoMemory to quotas and death notifications [232]. Every M3 commit
written in-tree is a commit that has to be re-homed later, and the extraction
below is a `filter-repo` whose cost scales with the history it rewrites. The
split is cheapest at a quiet point in the tree, and the tree is quiet now: the
Aug-18 riders are the only sos work in flight.

The counter-argument — "split after M3, when the OS is real" — buys nothing.
Nothing in the units below gets easier with more sos code; two of them get
harder in proportion to it.

## The consumer sweep (obligation 2)

The boundary change here is a repo-level one, so the sweep asks: what, outside
`sos/`, depends on `sos/` being at that path — and what inside `sos/` depends on
anything outside it. Grep evidence, Aug 19:

- **Every package dependency under `sos/` resolves inside `sos/`.** The full
  set is `sosabi = ../abi`, `sos = ../kernel/sysapi` (seven packages),
  `sos = ../../kernel/sysapi`, `sosrt = ../../rt/common`. Nothing under `sos/`
  names `libs/`, `blade/`, or `sawc/` as a dependency. The tree is
  self-contained on the package axis.
- **Blade's SOS fixtures are self-contained.** `blade/tests/fixtures/sosapp`
  and `sosdefaults` declare their own `[sos]` manifests and reach into no part
  of `sos/`. Blade keeps exercising its sosimg emitter, its `[sos]` manifest
  parsing, and `sosimg_wire`/`sosimg_config` after the split, with no sawos
  checkout present.
- **Exactly two crossings exist.** `blade/Saw.toml:10`
  (`imgformat = { path = "../sos/imgformat" }`) and `tools/sos_runner.py`,
  whose module constants name `sawc/sawc.py`, `blade/`, `libs/toml/src`,
  `libs/semver/src`, and `sos/imgformat/src` off a computed `REPO_ROOT`.
- **sawc has no dependency on sos.** Its nine hits are comments plus one
  runtime-VARIANT name (`sos-hosted` in `runtime_abi.py`, `rt/ABI.md`) — a
  string in a link-time table, not a path. `--freestanding`,
  `--no-hidden-alloc`, `--runtime-provider` and the `sos-hosted` variant stay
  in sawc and are consumed from sawos as compiler flags, which is what they
  already are.
- **The history does NOT separate cleanly.** 97 commits touch `sos/`; the
  non-`sos/` paths they also touch include `blade/src/sosimg.saw`,
  `blade/Saw.toml`, `blade/tests/*`, eight `designs/*sos*.md`, `designs/todo.md`,
  `CLAUDE.md`, `.claude/skills/saw-lang/SKILL.md`, and a long tail of
  `examples/`. `filter-repo --path sos/` preserves the sos side of those
  commits and drops the rest — partial fidelity, not none. See D-d.

Conclusion the sweep supports: the split is a file move plus a path resolver,
with one genuine dependency decision (D-a) and one gate that must be rebuilt
(below). It is not a refactor of either tree.

## D-a — the imgformat cycle (RULED Aug 19: `libs/imgformat`)

`sos/imgformat` exists so the sosimg layout is written once: Blade WRITES the
images, the kernel core READS them, and the package is the shared authority that
stops the two from drifting (`sos/imgformat/src/lib.saw:1-5`, `sos/spec.md` §6).
Blade takes it as a path dependency and compiles it in; the kernel reaches the
same sources through `--module-path imgformat=…` (`sos_runner.py:74`).

If `imgformat` goes to sawos, **sawlang cannot build Blade without a sawos
checkout** — a repo-level cycle on the wrong axis. sawlang is the more
fundamental repo; its CI would need sawos cloned to build its own package
manager, and a sawos-side change could redden sawlang.

**RULED: `sos/imgformat` → `sawlang/libs/imgformat`.** `libs/` today
holds exactly Blade's dependency set (toml, semver); imgformat joins it
coherently, sawlang stays self-contained, and sawos depends downward only,
reaching the sources the same way it reaches sawc — through the D-b resolver.

The honest objection: an OS image format then lives in the language repo. That
is already true of the thing that is harder to move — `blade/src/sosimg.saw` is
the whole `[sos] emit = "sosimg"` target, ELF32→sosimg conversion included, and
it is Blade's code. The format package sitting beside its producer is the
consistent position, not a new compromise.

Alternatives considered and not recommended:

- **imgformat stays in sawos, Blade takes a git dependency on it.** Blade
  resolves git deps already (`src/git.saw`), so this builds — but it makes
  every sawlang Blade build network- and sawos-dependent, and pins a bootstrap
  cycle into the lockfile. Rejected on the same axis argument.
- **Blade grows an out-of-tree target plugin**, so `sosimg.saw` AND `imgformat`
  both live in sawos and Blade knows nothing about SOS. **This is the probable
  future direction** (user, Aug 19) and is filed to [BACKLOG] — but it is real
  design work on Blade's target model, and gating the split on it trades a
  two-day move for a two-week one. When it lands it SUPERSEDES this ruling:
  `libs/imgformat` goes back to sawos and `blade/src/sosimg.saw` follows it.
  Keeping imgformat a self-contained package with no sawlang-ward dependencies
  is what keeps that reversal cheap, and unit 2 must not add any.
- **Duplicate the layout with a drift test.** Refused: the duplication is
  precisely what the package was created to remove.

## The gate, re-founded (RULED Aug 19)

`CLAUDE.md` makes sos a COMPILER gate: a sawc change owes both the full suite
and `tools/sos_runner.py` on both arches, "the suite alone does not cover sos/",
and `battery.sh` carries `sos` as a stage. That is not ceremony — sos is the
only freestanding, no-hidden-alloc, cross-architecture, user-mode-crossing
exercise the codegen has.

The brief's first draft kept it by having sawlang CI check out sawos. **RULED
OUT.** sawlang never references sawos. Instead the coverage is re-founded as a
FIRST-CLASS sawlang suite that names the features directly.

**The diagnosis this ruling rests on:** sos is a SYSTEM test doing a UNIT
gate's job. When it goes red it says "the OS did not boot" — not "the
`--no-hidden-alloc` check regressed on enum init". Every feature below is
currently covered only incidentally, by a test that traverses it on the way to
something else. Naming them directly is more diagnostic AND cheaper to run.

**The feature inventory the new suite owns** — what `sos_runner` is really the
gate for:

- `--freestanding` codegen: no host runtime, no libc, no hidden dependencies.
- `--no-hidden-alloc`: the refusal surface, per construct.
- `--runtime-provider`: a package supplying the four frozen `__saw_rt_*` seams,
  with the signature check against `sawc/rt/ABI.md`.
- **Cross-target codegen for riscv32 AND aarch64** — a 32-bit target from a
  64-bit host is the live hazard here (platform-width `Int`, pointer size,
  struct layout, calling convention).
- Linking at a fixed load address with a custom linker script.
- `--module-path` module composition (the kcore/imgformat/sosrt shape).
- Blade's non-host target path: `blade build --target <triple>`.

**It must RUN, not just compile.** A suite that compiles and links freestanding
riscv32 proves the compiler emitted something, not that the something is
correct — calling convention, struct layout and trap-frame bugs are exactly
what sos catches today, and all three survive a clean link. So the cases stay
QEMU-executed; they are just tiny programs that print and exit rather than an
operating system.

**This is mostly kept code, not new code.** `sos_runner.py` splits at a seam
that already exists:

- GENERIC, stays in sawlang as the new suite's engine: `_run`, `_find_clang`,
  `_probe_tools`, `_run_qemu` (already arch-table-driven —
  `[qemu, *arch["qemu_args"], "-nographic", "-kernel", elf]`), `_check` and the
  transcript matcher (`_is_english_embedding`), and the `ARCHES` table.
- SOS-SPECIFIC, goes to sawos: `_build_blade`, `_build_root_image`,
  `_stitch_root_image`, `_root_image_path`, `_check_arch_free`, `_build_shared`,
  `expectations`, `arch_dirs`, and the CASES table.

The boot stubs are the one duplication: sawlang's suite needs a minimal
`_start` (stack, call, exit device) per arch, derived from `sos/hal/<arch>/
kernel/boot.S` (231 and 270 lines today, nearly all of it kernel setup the
suite does not need). The two copies then diverge deliberately — a test stub is
not a kernel — so this is a fork, not a shared file, and the brief says so
rather than pretending a common ancestor should be maintained.

Spelling: `tools/freestanding_runner.py`, `make freestanding-test`, and
`battery.sh`'s `sos` stage becomes `freestanding`. It is a sawlang suite and
takes sawlang's suite lock like any other.

**Ordering consequence, load-bearing:** this suite lands BEFORE the extraction.
Once sawos pins a sawlang SHA, compiler churn cannot break sawos — but nobody
LEARNS that churn broke sawos until someone bumps the pin. The pin is only safe
because sawlang has its own coverage; if the suite slips, the pin becomes a
silent-rot machine. It is unit 1 for that reason.

## The suite lock (RULED Aug 19: not shared)

sawos and sawlang run independently — no cross-repo serialization. This costs
nothing to implement: the lock is not in any harness, it is an agent protocol in
`CLAUDE.md` (grep for `saw-suite-lock` in `tools/`, `test_runner.py` and the
Makefile returns nothing). Unit 7 narrows that paragraph to sawlang's own
suites and sawos's CLAUDE.md gets its own, with its own lock path.

The residual risk is CPU, not correctness — two heavy suites on one laptop is
slow, and the DF-182f history (loadavg >700) is what the protocol was written
against. Accepted: the repos are usually worked one at a time, and a wedged
laptop is visible in a way a silent state collision would not be.

## D-b — the toolchain resolver (RULED Aug 19: `$PATH`, then a pinned fetch)

"Every place sawos names a sawlang artifact" is a position-quantified rule, so
it gets one chokepoint rather than a hand-kept list of constants (obligation 1):
a single `sawos/tools/toolchain.py` whose docstring NAMES its entry points
(`sos_runner.py`, the Makefile, CI). It owns sawc, blade, imgformat, and
Blade's toml/semver — nothing else in sawos may compute a sawlang path.

Resolution order:

1. **`SAWC` / `BLADE` env vars** — an explicit override, and how CI pins a
   prebuilt Blade. Precedent: `sos_runner` already sets `env["SAWC"]` for Blade
   to read (`sos_runner.py:1322`).
2. **`sawc` and `blade` on `$PATH`** — the developer fast path.
3. **`SAWLANG_ROOT`** — a local sawlang checkout, for working both repos at
   once against uncommitted compiler changes. (Kept from the first draft: this
   is the ONLY way to test a sawc change against sawos before it is pushed, and
   the split must not make that impossible.)
4. **Fetch `swoodtke/sawlang` at the pinned SHA** and bootstrap it, cached.
5. Otherwise a refusal naming all four.

Three sub-decisions this opens — each a real gap, none blocking:

- **D-b1 — there is no `sawc` binary to find (OPEN).** sawc is
  `python sawc/sawc.py` plus llvmlite: no `pyproject.toml`, no `setup.py`, no
  `bin/`, no console script. And `blade` is BUILT FROM SAW SOURCE BY sawc, so
  neither name exists on any `$PATH` today. Step 2 presupposes an install story
  sawlang does not have. It is small — a console-script entry point, or `bin/`
  shims plus `make install` — but it is a sawlang deliverable that must land
  before step 2 can ever hit, and it belongs to this brief (unit 3) or to a
  filed successor. Until then the resolver's step 2 is dead code.
- **D-b2 — a `$PATH`-found sawc is UNPINNED, which inverts the goal (OPEN).**
  The pin protects the FALLBACK path while the FAST path is whatever the
  developer happens to have installed — so the common case is the unpinned one,
  and a stale or bleeding-edge sawc silently produces a build sawos never
  tested. `sawc` has no `--version` today (grep: no version flag, no
  `__version__`). Proposal: sawc gains `--version`, `sawlang.pin` records what
  sawos requires, and the resolver VERIFIES what step 2 found — a mismatch is a
  loud refusal naming both versions, never a silent build. That makes `$PATH` a
  fast path rather than a hole. Doctrine: never hide errors.
- **D-b3 — the fetch is a clone-and-bootstrap, not a download (OPEN).**
  Fetching at a SHA yields Python source; the resolver then needs llvmlite
  installed and a `blade` built by sawc — minutes, not seconds. So it caches by
  SHA (`~/.cache/sawos/toolchain/<sha>/`) and builds once, and a cache hit is
  the steady state. What remains open is the bootstrap's shape (does the
  resolver create a venv for llvmlite, or require one?), not its reachability:
  **`swoodtke/sawlang` is PUBLIC** (user, Aug 19), so unit 4 fetches over
  HTTPS with no credentials and the fresh-machine promise holds as stated.
  This repo's own `origin` is SSH (`git@github.com:swoodtke/sawlang.git`) —
  a developer-remote preference, not a constraint on the resolver.

CI note: locally, auto-fetch is the point. In CI prefer an explicit checkout
step so the SHA is visible in the log and cacheable — same resolver, cache
pre-warmed, no behavioral fork.

## Units

0. **The oracle.** BEFORE anything moves, capture the acceptance oracle:
   `make sos-test` on main, both arches, full console transcript saved beside
   this brief. Every later unit is diffed against that transcript rather than
   judged "green" — a split that quietly loses a test case would otherwise
   still pass.
1. **The freestanding suite** (`tools/freestanding_runner.py`,
   `make freestanding-test`). Split `sos_runner.py` at the seam named in the
   gate section: the generic engine stays and gains a case table of tiny
   QEMU-executed programs, one or more per feature in the inventory, both
   arches. Minimal boot stubs derived from `sos/hal/<arch>/kernel/boot.S`.
   `battery.sh`'s `sos` stage becomes `freestanding`. **Lands FIRST and lands
   WHOLE** — every later unit removes sos coverage from this repo, and this is
   what replaces it. Gate: the new suite green, plus `sos-test` still green
   (sos has not moved yet, so both run).
2. **imgformat relocates INSIDE sawlang** (`sos/imgformat` → `libs/imgformat`,
   D-a). One repo, one commit: `blade/Saw.toml`, `blade/Saw.lock`,
   `sos_runner.py:74`, and the doc references in `sosimg.saw`,
   `imgformat/src/lib.saw`, `blade/Saw.toml`'s comment. Adds NO sawlang-ward
   dependency to the package (D-a's reversal clause). Gate: suite + sos green,
   everything still in one place. **The de-risking unit** — after it no
   dependency surgery remains and the split is a move plus a resolver.
3. **The install story** (D-b1). sawlang gains a way to put `sawc` and `blade`
   on a `$PATH` — console-script entry point or `bin/` shims plus
   `make install` — and `sawc --version` (D-b2), whose string is what the pin
   is checked against. Without this unit the resolver's `$PATH` step can never
   hit. If it grows past a day's work it EXITS to its own brief rather than
   stretching this one; the resolver then ships with step 2 documented as
   pending.
4. **The resolver, still in-repo.** `tools/toolchain.py` lands with
   `SAWLANG_ROOT` defaulting to the repo itself; `sos_runner.py`'s five path
   constants become resolver calls. All five resolution steps implemented and
   unit-tested, including the version check and the refusal. Suite green proves
   the funnel before the move exercises it.
5. **The extraction.** `filter-repo --path sos/` into `../sawos` (D-d), minus
   imgformat. sawos gains `Makefile` (`sos-test`), `CLAUDE.md`, `.gitignore`,
   `.github/workflows/ci.yml`, `sawlang.pin`, and `tools/` (sos_runner +
   resolver). sawlang deletes `sos/`, its `sos-test` target and its `sos` CI
   job — it now references sawos nowhere. Acceptance: the unit-0 transcript
   reproduced from sawos, both arches, once per resolution path that a dev
   machine can exercise (env override, `$PATH`, `SAWLANG_ROOT`, cold fetch).
6. **sawos CI and the negative tests.** sawos's own workflow, pinned. Two
   deliberate negatives: no sawlang reachable at all fails with the D-b
   refusal naming all four steps, not a confusing toolchain error; and a
   `$PATH` sawc whose version disagrees with the pin fails loudly (D-b2).
7. **Docs and tracker.** `CLAUDE.md`'s sos digest, its gate paragraph (sos is
   no longer the compiler's freestanding gate — `freestanding` is), and its
   suite-lock paragraph narrowed to sawlang. `TESTING.md`, `README.md` per
   design 125, `designs/INDEX.md`. D-c decided. sawos gets its own CLAUDE.md
   carrying the sos half, with its own lock path.

## Gates

Units 0-4 gate on `battery.sh suite sos` in sawlang — ordinary in-repo work,
with sos still present and still green. Unit 5's gate is the unit-0 transcript,
diffed, both arches, from sawos. Unit 6 gates on sawos CI plus its two
negatives. **No compiler change lands in this brief**: if the split surfaces a
sawc defect, the unit STOPS and files a DF (agent conduct — no coding around a
compiler defect), and this brief does not absorb the fix.

The suite lock stays sawlang's own (see the ruling above); sawos gets a
separate path. Nothing in either harness implements it, so this is a docs
change in both repos, not code.

## Explicitly OUT of scope

- **Blade's target-plugin mechanism** (the eventual home for `sosimg.saw`).
  Filed to [BACKLOG]; not a dependency of this split.
- **Any change to the sosimg format, the boot protocol, or the syscall
  surface.** The bytes are identical across this brief; the unit-0 transcript
  is the proof.
- **Any M3 work.** The ladder resumes in sawos after unit 6.
- **Broadening the freestanding suite past the inventory.** Unit 1 covers what
  `sos_runner` gates today, not every freestanding feature imaginable. New rows
  are welcome later, as their own filings.
- **`blade/src/sosimg.saw`, `blade/tests/sosimg_*`, and the sos fixtures.**
  They stay in sawlang. Blade keeps testing its own emitter.
- **`sawc/rt/ABI.md`'s `sos-hosted` runtime variant** and the freestanding
  flags. Compiler surface, compiler repo.

## Decisions agenda

- **D-a — imgformat placement.** RULED Aug 19: `libs/imgformat`, superseded
  later by the Blade plugin ([BACKLOG]).
- **D-b — resolver order.** RULED Aug 19: `$PATH` first, pinned fetch as
  fallback. Three sub-decisions OPEN, all detailed above — **D-b1** the missing
  install story (no `sawc`/`blade` binary exists to find), **D-b2** the
  unpinned-`$PATH` inversion (needs `sawc --version` + a pin check), **D-b3**
  fetch mechanics (SHA-keyed cache + bootstrap shape; reachability settled —
  the repo is public, so HTTPS, no credentials).
- **D-c — the sos design briefs.** `designs/78, 79, 112, 140, 162, 172, 178,
  232` and the sos DF entries. Move to sawos / copy / stay archival in sawlang?
  Design numbering is repo-global and heavily cross-cited, so moving fragments
  the sequence; copying duplicates a record the tracker flow says must never be
  duplicated. Lead's suggestion: they STAY (archival, cited by number), sawos
  opens its own numbering at 1 and cites sawlang briefs as `sawlang#NNN`.
- **D-d — history.** `filter-repo --path sos/` (partial fidelity, per the
  sweep) versus a squashed import with a pointer to the sawlang SHA. filter-repo
  recommended: partial history beats none, and the dropped context is
  reconstructible from sawlang, which is not going away.
- **D-e — sawos layout.** Keep the `sos/` prefix inside sawos, or flatten
  (`sawos/kernel/`, `sawos/hal/`, …). Flattening rewrites every internal
  `../..` path dep and every doc cross-reference; keeping the prefix costs one
  redundant directory level. Recommendation: keep `sos/` for the split, flatten
  later if ever, as its own commit.
- **D-f — the saw-lang skill.** sawos writes Saw and needs the idiom skill.
  Copy into sawos's `.claude/skills/` (drifts) or leave the sawos worktree
  pointing at sawlang's (requires the checkout). Open.

## Scheduling

AFTER queue item 7 (the sos riders batch — `clock_get` `type:`, abi enum
shifts, kcore re-narrowing), which are small in-tree edits already queued behind
DF-232f. Landing them first means the split moves a settled tree rather than
one with known-pending edits, and it keeps those riders on the simple in-repo
flow. BEFORE the M3 ladder, per the user.

Note the standing rule that SOS-side branches PARK for user review before
merging. This brief is SOS-side in blast radius but most of it is sawlang work:
units 1-4 and 7 follow the normal compiler-brief flow; units 5-6's sawos side
parks.

Units 1 and 2 are independent of each other and of 3-4, so they may run in
parallel worktrees. Everything from unit 5 on is strictly serial.

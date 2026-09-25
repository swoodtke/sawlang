# Saw Language Project — Development Guide

Saw: a systems language (Rust safety + Swift ergonomics, no lifetimes,
deterministic destruction). This file covers HOW TO DEVELOP the
compiler/tooling. For HOW TO WRITE Saw code, load the **saw-lang
skill** (`.claude/skills/saw-lang/`); the authoritative language
reference is **LANGUAGE_SPEC.md**. Open work: **designs/todo.md**
(tracker); decided designs: `designs/NN-*.md`.

## Repo map
```
sawc/              # Compiler: Python + llvmlite
  sawc.py          # CLI; lexer.py; parser/; ast_nodes.py
  typechecker/     # Type checking passes (mixin classes)
  codegen/         # LLVM IR generation (mixin classes)
  coro_transform.py# Source-level coroutine transform
  builtin.saw      # Built-in traits; std/ = stdlib (.saw)
  rt/              # Runtime ABI (design 113/113b, v2 by 117): rt/ABI.md freezes
                   # the __saw_rt_* seam contract; the seam bodies are AUTHORED
                   # IN SAW here — common/ (os_ops.saw = status-carrying tcp/fs/
                   # env ops) + host_macos/ + host_linux/ (reactor.saw kqueue/
                   # epoll, net_os.saw errno->SysError) (.saw, --runtime-build)
                   # + shim.c (FFI-blocked bodies, grown past the original
                   # three — DF-113a/b/c: write/panic, open_flags, getaddrinfo
                   # helpers, environ get/set, thread_spawn+offload thunk,
                   # set_nonblocking — plus DF-186c's Linux-only futex lock).
                   # Built + cached under .build/rt/, auto-linked for hosted
                   # builds. Design 117: the reactor is now Saw too
                   # (instance-based); the compiler only synthesizes the
                   # process-global __saw_reactor getter.
compiler/          # The self-hosted compiler, in Saw (epic SL-398; README.md):
                   # one dir per stage — lex/ (package sawlex) — plus driver/
                   # (the sawc2 binary), tools/ (build.py builds it with sawc/,
                   # subset_check.py enforces the subset its source is written
                   # in) and tests/ (run.py: unit programs, golden fixtures,
                   # the checker's fixtures). prototypes/ holds the paused
                   # minivm and the parser prototype that seeds its parser.
examples/          # Compiler test suite programs (test_runner.py)
blade/             # Blade package manager (written in Saw)
libs/              # Real Saw library packages (semver, toml)
tools/blade_bootstrap.py  # Self-hosting bootstrap loop
designs/           # Design briefs + todo.md tracker
libs/imgformat/    # the sosimg layout (design 238 unit 2, moved from sos/):
                   # Blade consumes it via a path dependency, the sawos
                   # kernel via --module-path. Its tests run in LIB_DIRS.
bin/, tools/toolchain.py  # `make install` shims + the toolchain resolver
                   # (design 238 units 3-4): SAWLANG_ROOT / $PATH+pin /
                   # cached fetch, one funnel, `toolchain` battery lane
```
SawOS left this repository (design 238 unit 5, Aug 28 2026): the kernel,
HALs, runtime, root server and their tests live in the sawos repo
(`../sawos` locally), flattened to its root, building against a sawlang
checkout through the resolver (`SAWLANG_ROOT` is the everyday spelling).
sawlang references sawos nowhere; the freestanding suite is the compiler's
cross-target gate.

## Python environment
Dependencies live in `.venv/` (Python 3.14, llvmlite). ALWAYS use it:
```bash
./.venv/bin/python test_runner.py
./.venv/bin/python sawc/sawc.py examples/hello.saw -o hello
```
The Makefile calls bare `python3`, so `make test` needs the venv
activated first.

## Compiler usage (dev)
```bash
./.venv/bin/python sawc/sawc.py <src.saw> [-o out] [-v] [-c]
    [--emit-ir] [--emit-ast] [--ids] [--emit-docs] [--emit-docs-all]
    [-O0 | -O2 | -Os | -Oz]
    [--emit-frame-layout] [--emit-bt-table] [--emit-frame-ledger]
    [--target TRIPLE] [--target-features FEATURES]
    [--module-path NAME=DIR]
    [--freestanding] [--runtime-build] [--runtime-provider]
    [--no-hidden-alloc] [-W NAME | -W all]
```
That is the complete flag set (`sawc.py:2081-2190`); `-o` defaults to
`.build/<source>`. `--emit-frame-ledger` (design 275 U1) dumps the
coroutine transform's DISCOVERY LEDGER instead of code — one FRAME row
per frame key it reached (kind, suspension causes, the decision — `framed` /
`no-frame-owed` / `template` / `refused` — its reason, home module, where the
body came from) and one SITE row per suspension position (its context and
outcome: embed / inline / refuse). Deterministically ordered and path-free, so
two compilers' dumps diff: it is the instrument behaviour preservation is proven
with. U1's fourth outcome, `declined`, is GONE from both tables — design 275 U2
spent that worklist. `--no-hidden-alloc` (design 135) rejects the
allocations the compiler inserts that no source construct names.
`-W` (design 150) enables a warning category (repeatable, `-W all` for
every one; warnings are off by default and never affect the exit code).
Default pipeline is O1-style; design 265 added `-O2`/`-Os`/`-Oz`
through the one `speed_level` funnel (`-Oz` enables the machine
outliner via `minsize`; the sos image took -24% from it — sos opts in
explicitly, freestanding does NOT imply a size level). `--module-path` maps a package name to a
module dir (Blade uses this per dependency). `--runtime-build` (design
113b) compiles a Saw runtime that `@export`s the frozen `__saw_rt_*` ABI
(sync-only, object output) — used to build `sawc/rt/`; the hosted runtime
objects are built + cached under `.build/rt/` and auto-linked (delete
`.build/rt/` to force a rebuild; `-v` lists the linked objects).

## Testing
- `make test` (venv active) or `./.venv/bin/python test_runner.py` —
  full compiler suite, ~1 min uncontended. Multi-pattern filter:
  `./.venv/bin/python test_runner.py -f test_a,test_b`.
- `./build.sh test` — the sawtracker patch gate's entry point
  (`.sawtracker/tests.json` runs `./build.sh test --changed-since HEAD^`
  on every submitted patch): bootstraps `.venv` if absent (or uses
  `$SAW_PYTHON`), then runs `tools/patch_gate.py` under the machine-wide
  suite lock, so a server-side patch test and a local suite run never
  overlap. **THE PER-PATCH GATE IS PATH-AWARE (user, Sep 25):**
  `compiler/tests/run.py` always runs; the full suite and freestanding
  (both arches) run only when a changed path is one of their runner's
  inputs (`SUITE_INPUTS` in `tools/patch_gate.py`: `sawc/`, `examples/`,
  `tests/{cbor,float}_vectors/`, `tests/freestanding/`, `blade/`, `libs/`,
  the runners — a new input a runner reads is added there), when the gate itself
  changes (`build.sh`, `tools/patch_gate.py`, `.sawtracker/`), or when
  the changed paths are unknown. It prints each decision and why;
  `./build.sh test --dry-run --diff FILE` shows a patch's decision
  without running anything.
- **PER-COMMIT GATE POLICY (user, Sep 24): run only the tests a change
  affects, and never duplicate what the server runs.** The per-patch gate
  above runs the full suite and freestanding (both arches) on every patch
  that reaches their inputs, so NOBODY, implementer or lead, runs a
  per-commit or pre-submit full suite or freestanding. Before a commit or
  a submission, run the change's pins, targeted `test_runner.py -f`
  subsets, and the battery lanes that touch the change's subject and that
  the server does not run: `astgraft` and `transferdecisions` for the
  typechecker or codegen, `bootstrap` for the blade/libs corpus,
  `docverify` for spec prose, `compiler` and `citations` for `compiler/`,
  `astdiff` for the parser; `irdet` and `reemit` only when the change can
  reach them. No branch owes the full battery; it will run on main
  periodically, never per merge, once sawtracker schedules it (ST-45, open).
  SawOS work happens in the sawos repo under
  its own gate (`make sos-test` there) and its own CLAUDE.md. XFAIL policy (user, Aug 7): a
  `// XFAIL: reason` test is legal ONLY as a pin of a filed finding —
  the reason MUST cite the DF number, the body is the minimal repro
  with EXPECT directives stating the intended behavior (so the XPASS
  flip validates the fix). The bar: zero UNCITED xfails, and a brief
  never xfails breakage IT introduced. Stale markers (XPASS) break
  the build — remove the marker in the landing that fixes the bug.
  Name a pin file for the BEHAVIOR it pins, never with an `_xfail`
  suffix (user, Aug 9) — the marker is the transient part, and the file
  outlives it as the regression test.
- `examples/conformance/` (design 191) is the standing safety-guarantee
  suite: one row per guarantee the language claims, with
  `examples/conformance/INDEX.md` naming the covering test for every
  row — including the rows an existing `examples/` test already covers,
  which is what makes the ledger auditable. It runs inside the ordinary
  battery; `-f conformance/` is the subset switch (~9s), and a brief
  touching a safety guarantee updates its rows FIRST (obligation 3).
- Never run two suite invocations at once.
- Tests support a `// COMPILE-FLAGS:` directive (`{TESTDIR}`
  placeholder), and — for warnings, which are reported on the SUCCESS
  path and never affect the exit code — `// EXPECT-WARNING-CONTAINS:`
  and `// EXPECT-NO-WARNINGS` (design 150).
- App-level: `blade test` (tests/*.saw exit 0 = pass; see TESTING.md);
  `./.venv/bin/python tools/blade_bootstrap.py` or
  `make blade-bootstrap` runs the self-hosting loop (stage0→stage2).
- IR determinism: the harness is **written in Saw** (`devtools/irdet/`,
  design 155 — the first devtool port; it still drives the PYTHON
  sawc). `make irdet` builds `.build/irdetbin` and samples 40 examples
  — cheap enough per commit. **A change that can reach IR emission runs
  `irdet --all`** (the whole corpus; design 146 unit D):
  ```bash
  ./.venv/bin/python sawc/sawc.py devtools/irdet/src/main.saw -o .build/irdetbin
  ./.build/irdetbin --all
  ```
  (`make irdet-all` does both, but the Makefile's bare `python3` cannot
  build it — activate the venv first.) A random sample cannot police a
  whole-corpus property: design 141 found two nondeterministic emission
  orders that had sat in the tree unnoticed until two unrelated new
  examples reshuffled the sample onto one of them. Two machines:
  `./.venv/bin/python tools/irdet_remote.py --all --remote HOST:PORT`.
  Design 220: `test_runner.py` gives every invocation its own
  `.build/test_runner_<stamp>/`, atomically published to
  `test_runner_last` (never `ln -sfn`'s unlink-then-create), with a
  `manifest.tsv` recording each SUCCESS/PANIC compile's worker
  `PYTHONHASHSEED` and its optimized-IR artifact — a hash-order failure
  replays via `PYTHONHASHSEED=<recorded>`, an unchanged file's artifact
  hardlinks forward instead of recompiling (freshness = newer than every
  `sawc/` file+directory, the llvmlite install, and `test_runner.py`
  itself), and `irdet` reuses one side of its byte-compare from that
  manifest when `test_runner_last` is fresh — a mismatch there is never
  trusted on its own; a three-way verify (fresh recompiles at both
  seeds) sorts it into true nondeterminism, a violated invariant (never
  absorbed into a nondeterminism report), or a transient race. Running
  `suite` right before `irdet` maximizes reuse but is never required
  (TESTING.md's "reuse manifest" section has the rest). A violated
  invariant is a FOURTH `--jsonl` record status, `invariant`, which
  `tools/irdet_verdict.py` fails on exactly as it fails on `mismatch` —
  the battery's irdet lane reads records, never `$?` (design 221 D).
- **THE GATE BATTERY is `tools/battery.sh`** (design 192 unit 5) — tracked,
  so a lane cannot quietly go missing the way it did while the battery was
  an untracked scratch file each session rewrote from this prose:
  ```bash
  SAW_PYTHON=/path/to/main/.venv/bin/python tools/battery.sh   # from a worktree
  tools/battery.sh --quick        # skips the slow five (reemit/irdet/gmgate/
                                  # bootstrap/freestanding)
  tools/battery.sh suite fuzz     # named stages
  tools/battery.sh --list
  ```
  Stages: `suite`, `icebreadcrumb`, `compiler` (`compiler/tests/run.py`:
  the self-hosted compiler's unit programs, its golden token fixtures with
  their kind coverage, and the subset checker over its source and its own
  fixtures), `astdiff`, `astgraft`,
  `corodiscovery` (design 275 U1: ONE ledger answers every coroutine frame
  decision — `tools/test_coro_discovery.py` parses `coro_transform.py` and
  fails on any site outside the ledger's builder that reads a raw discovery
  input, on a frame table looked up by a written `.name`, on a named consumer
  that stopped reading the ledger, on a new caller of either key composer, and
  on a missing freeze or miss invariant. Two of its nine checks RUN the
  compiler rather than reading it: one DROPS a recorded decision — injected
  into `FrameLedger.record_frame`, restored in a `finally`, the
  `icebreadcrumb` pattern — and requires the internal-compiler-error line to
  NAME the dropped key, because a structural check that `frame()` contains a
  raise is not a check that a consumer's miss reaches it; the other asserts the
  dump carries a `context=driven root` site for each of the three driven-root
  families, which is what caught a FRAME row sitting beside `# sites: 0`),
  `corototality` (design 275 U2: there is NO fourth outcome —
  `sawc/coro_shapes.py` says, per shape a suspension can sit in, SPLIT / HOIST /
  INLINE / EMBED / REFUSE, and `tools/test_coro_shapes.py` compares that table
  against `ast_walk.CONTAINER_KINDS` and `CONTAINER_HEADS` — the other two
  enumerations of the same fact — checks each row is well formed and each named
  consumer still reads it, then INJECTS the failure three times: a dropped
  container row must ICE naming the AST class, a dropped site decision must ICE,
  and a plain call to a `frame_boundary` callee grafted into a generated resume
  body must ICE naming the frame and the callee. Each injection runs beside an
  uninjected control, because a structural claim that a function contains a
  raise is not a claim that anything reaches it — and the three injections are
  six, because the plain-call one runs once per family a call comes in: a free
  call plus an INSTANCE, a STATIC and a GENERIC-struct method, each grafted from
  a node the compiler really produced),
  `windowseam` (design 275 U3: the statement-scoped borrow window is a STRUCTURE,
  not a `for`-loop feature — `tools/test_window_seam.py` fails if `sawc/windows.py`
  names an AST class or any iteration vocabulary in its code, if the record's
  resource slot stops being generic, if the chokepoint's docstring lists a client
  that no longer resolves, or if either the typechecker or codegen half reaches
  past its ONE adapter, so the generic window statement a follow-up specifies adds
  syntax and a binding rather than a second implementation of root accounting),
  `stdseed` (SL-327: the design-206 std seed table is keyed by `Method.node_id`,
  and a wrong key costs a DIAGNOSTIC rather than a failure, so nothing in the
  corpus can see it — `tools/test_std_seed_keying.py` checks the rule directly:
  a key must name the METHOD ITS ENTRY IS ABOUT, membership of the integer is
  not the question; a wrong-method key and a missing key are both refused at
  publication and re-keyed by identity, an unresolvable identity is an invariant
  failure naming the entry, and an unsound blob already on disk is discarded AND
  deleted so it costs one cold std build rather than a silence forever),
  `citations` (DF-248c, Aug 24: stale XFAIL/ledger citations against the
  tracker's closed set + committed conflict markers over tracked files —
  the gate for the files nothing compiles),
  `forgetgate`, `ircontract`, `preludegate`, `stdtypes`, `toolchain` (design
  238 unit 4: the sawlang-artifact resolver — four steps, the pin's version
  check, the refusal), `abidoc`, `bttable`,
  `fuzz` (`sawfuzz --quick`), `corodiff` (`--quick`), `bench` (the warehouse
  benchmark — checksums GATE, timing report-only; devtools/bench/ +
  TESTING.md), `minivm` (the paused prototype builds against compiler/lex
  and its differential harness passes), `floatvectors` (design
  253: the committed Float↔text vectors, bit-exact, plus the Ryū table
  re-derivation), then the slow five
  `reemit` (design 221 A2: TWO compiles in ONE process, byte-comparing the
  unopt IR, the OPTIMIZED IR and the object — the optimized IR is the
  artifact DF-220a moved and the only one nothing checked),
  `irdet` (`--all`, whole corpus), `gmgate` (both lanes), `bootstrap`,
  `freestanding` (the design-238-unit-1 feature suite under QEMU,
  both arches; the `sos` stage left with the kernel at 238 unit 5).
  Every stage RUNS even after one fails; the exit code is the
  number of failing stages. Adding a lane means editing `STAGES`.
  Coverage map (Aug-10 sweep): blade/tests + libs/*/tests are
  typechecked+run by `bootstrap` ONLY (so `--quick` skips them);
  compiler/*/tests by `compiler` only; astdiff parses EVERY tracked .saw
  but checks no semantics. RETIRED (SL-399): the `lexdiff` and
  `selfhostlex` lanes, with `tools/lexdiff.py` and `tools/dump_tokens.py`
  — the golden token fixtures in compiler/tests/lex, snapshotted once
  against the Python lexer, are the lexer's oracle now.
- The AST contract (design 126, gated by design 194): every attribute a pass
  stamps on an AST node is a DECLARED `annotation(...)` field on the node
  class, never a runtime graft — `tools/test_ast_graft.py` (the `astgraft`
  lane) fails on any attribute assignment in `sawc/` that no class declares.
  A graft is invisible to `dataclasses.fields()`, which is what
  `substitute_ast_types` walks, so a grafted `SawType` survives
  monomorphization un-substituted.
- Fuzzing (design 192): `tools/sawfuzz.py` mutates the examples/ corpus and
  asserts ONE oracle — the compiler succeeds or exits with a clean
  diagnostic; a traceback, an `internal compiler error`, a signal or a hang
  is a finding, minimized into `.build/fuzz-findings/` with its seed.
  Deterministic per `(seed, index)`, wave-bounded fan-out. A finding becomes
  a DF + a cited XFAIL pin + a `tools/sawfuzz_known.txt` entry, all three
  removed together by the fix. `--soak` runs it unbounded. See TESTING.md.
- Pyright diagnostics on sawc/ are NOISE (mixin `self.X` false
  positives) — ignore unless a real behavior test fails.

## Scratch compilations
For throwaway experiments do NOT write .saw files to /tmp or via
heredocs/echo (not auto-approved). Instead:
1. Write the file (Write tool) under `.build/scratch/` (gitignored)
2. `./.venv/bin/python sawc/sawc.py .build/scratch/foo.saw -o .build/scratch/foo`
3. `./.build/scratch/foo`

## Command hygiene (avoids permission prompts)
- Read files with the Read tool (batch multiple Reads); never `cat`
  via Bash loops.
- Navigate sawc/ Python with the LSP tool (workspaceSymbol,
  goToDefinition, findReferences); Grep/Glob for text search. Plain
  read-only `grep`/`ls` are allowlisted fallbacks; `find`/pipelines
  are not.
- NEVER prefix commands with `cd <path>;` — the working directory is
  already the repo root, and compound wrappers break allowlisting.
- NEVER run inline Python (`python -c`, `python - <<EOF`). Write
  probes to `.build/scratch/probe_*.py` and run with
  `./.venv/bin/python .build/scratch/probe_foo.py`.
- No shell heredocs; no `sed`/`awk` edits (use Edit).
- Commit messages containing backticks: write to a file, use
  `git commit -F <file>`. Never pipe via stdin/heredoc.
- `git add` explicit paths only — never `-A`/`.`.

## Code comments (user, Sep 23 2026; SL-357)
Comments are for the reader of the code as it is now, not a log of how it
got here. They apply to sawc/ Python, C and every `.saw` file.
1. Explain WHY: invariants, hazards, and non-obvious constraints a careful
   reader would get wrong. Never narrate WHAT the next lines do.
2. Present tense only. No "used to", "previously", "retired", "no longer",
   dates, "before DF-x", or "RULED by the user". History lives in git log,
   `designs/`, and the tracker.
3. At most one design/DF/SL reference per comment, as a trailing pointer:
   `(design 261)`. The comment must make sense without opening it; never
   paraphrase the brief.
4. Docstrings: a one-line summary, then at most ~8 lines. Longer reasoning
   belongs in the design brief; point to it. An entry-point list (rule 5)
   does not count toward the limit.
5. Funnel docstrings (brief obligation 1) keep their ENTRY POINTS lists:
   names only, one line each. Some gate lanes search source text (each
   lane has its own method; none derives every list), so a list is kept
   correct by hand and edited with care.
6. No line numbers, site counts, timings, or corpus statistics — they are
   stale the day after they are written.
7. Emphasis: at most one ALLCAPS word per comment, and only for a real
   hazard. Identifiers (EAGAIN, O_NONBLOCK) and named-invariant labels
   (RULE 1) are not emphasis.
8. A regression guard states the invariant and names the pinning test; it
   does not retell the bug.
9. `///` and `//!` doc comments are published API (`--emit-docs`) and
   follow the saw-docs skill; plain comments follow rules 1-8.
10. Changing code next to a comment means checking that comment still holds.

## Sawtracker (issues + the merge gate)
All issue tracking AND merge gating live in sawtracker, a webserver at
`Mac-Studio.local:8787` (CLI: `~/bin/sawtracker`; env `SAWTRACKER_HOST`/
`PORT`/`ACTOR`; agents identify as `--actor agent:<name>`). Projects:
SL (sawlang), SO (sawos). `.sawtracker/` in this repo is the SERVER'S
state (`issues/`, `events/`, `project.md`) — read freely, NEVER edit —
with TWO exceptions that are ours: `.sawtracker/tests.json`, which tells
the server how to test a submitted patch
(`./build.sh test --changed-since HEAD^`), and
`.sawtracker/version`, the release tag name (ST-46): a patch that changes it
(next to a `SAWC_VERSION` bump in `sawc/version.py`) makes the server create
that annotated tag at its merge commit. Never reuse a name.

**THE MERGE PATH (user, Sep 8 2026): GitHub is DOWNSTREAM of
sawtracker.** This checkout's deploy key (`.claude/sawlang_deploy_key`,
wired via repo-local `core.sshCommand` with `.claude/known_hosts`) is
PULL-ONLY, and GitHub CI runs on manual dispatch only — so nothing can
land by local commit + push. Every change to main, docs and briefs
included, travels as a PATCH:

1. File or claim an SL issue (`sawtracker create/list/show`).
2. Build + validate in an isolated worktree (gates unchanged, below).
3. The LEAD squashes the finished branch to ONE diff
   (`git diff main...<branch>`) and submits it:
   `sawtracker patch add SL-N --title "..." --file <diff>`.
4. The server applies it to its own branch, runs `./build.sh test`,
   and holds it at `proposed`. Review, approval
   (`patch review SL-N.p1 --approve`) and the merge are the USER'S.
5. After the merge: `git fetch origin && git merge --ff-only
   origin/main`, close the issue with a landing note, remove the
   worktree, delete the branch.

Direct commits on local main are RETIRED — they diverge from a remote
we cannot push, and the old "lead may commit docs directly" carve-out
is gone with them. Tracker commits (`sawtracker: ...`) arrive from the
server on every fetch; a fast-forward is the only merge local main ever
does. Revise a patch with `patch revise SL-N.p1 --file <diff>`; inspect
with `patch show`/`patch list`. The server's `./build.sh test` runs the
path-aware per-patch gate (Testing, above) on the applied patch; the lead
validates in the worktree first by review and spot checks, running only
the targeted tests the per-commit gate policy names.

## Design-brief workflow
Design decisions are made WITH the user, recorded as `designs/NN-*.md`
briefs, implemented by dispatched agents (one at a time; concurrent
only in isolated worktrees). Each finished brief unit reaches main as a
squashed sawtracker patch (section above), its server gate green.

**DIVISION OF LABOR + MODELS (user rulings, Aug 13-18):** the user
designs and RULES; the LEAD (session model) writes briefs, dispatches,
and VALIDATES every work product before it reaches main. Subagents are
ALWAYS `model: opus`, explicitly set — never inherited. Two exceptions:
a lead-model subagent may be dispatched (a) for the narrow aspect an
Opus agent demonstrably failed on (per-aspect, earned by the failure),
or (b) proactively to SPEC a tricky rewrite (emission census, exact
APIs, worked examples) that Opus then implements. A SONNET agent may
build oracle-dense MECHANICAL corpus work when the brief pins the grids,
the per-cell rule authorities, and a no-guessing rule (undetermined
cells flagged OPEN, never invented expectations) — per-task,
user-approved.

**WORKTREES + INTEGRATION (patch flow, Sep 8 2026):** ALL work happens
in isolated worktrees — NOTHING is committed directly on main any more
(the deploy key cannot push; see the sawtracker section). Agents keep
their own branches linear (rebase on main if behind). When a branch
passes the lead's validation and its gates, the LEAD squashes it to one
diff and submits it as a sawtracker patch; the user reviews and merges;
the lead fast-forwards main from origin, closes the issue, and removes
the worktree + branch. Resolve rebase conflicts HUNK BY HUNK with the
editor — NEVER `checkout --theirs/--ours` on a shared accumulator file
(todo.md, INDEX.md, SKILL.md): it replaces the whole file and silently
discards the other side's non-conflicted entries (this happened Aug 17;
recovered from history). After any accumulator-file resolution,
sanity-grep a couple of entries that exist only on the other side. Two
concurrent agents WILL collide on DF numbers — assign ranges at
dispatch or renumber at submission. SOS-side branches PARK for USER
review before submission; compiler briefs follow the normal flow.

**AGENT CONDUCT:** no workarounds — an agent that hits a language bug or
blocked dependency STOPS that unit, files a DF (mechanism named, per
obligation 4), and reports; it never codes around a compiler defect.
Never add attribution trailers (Co-Authored-By etc.) to commit messages.
HANDOFF.md is session state — never commit it. A fix that closes a
finding filed by a differential/fuzz harness removes the harness's
known-ledger entry (corodiff_known.txt, sawfuzz_known.txt) in the SAME
commit, and its gate includes that harness's lane.

**THE SUITE LOCK (machine-wide, sawlang's):** all suite-shaped invocations
in THIS repo (test_runner, battery.sh, freestanding_runner) serialize
through a mkdir lock at `/private/tmp/claude-<uid>/saw-suite-lock`
(uid = `id -u`; create the parent once per machine; the sawos repo has
its OWN lock path so the two never queue on each other). Acquire + gate +
release in ONE chained FOREGROUND command: `until mkdir <lock>
2>/dev/null; do sleep 15; done; <gate>; rc=$?; rmdir <lock>; echo
GATE=$rc` — in SANDBOXED agent worktrees, where the chained form is
refused, SPLIT it: the bare mkdir-wait as its own call, each gate as its
own call, the bare rmdir immediately after; the never-background and
never-stop-while-waiting-or-holding rules apply unchanged. Never
background the wait or the gate (a stopped agent's background waiters die
silently); never hold the lock while editing; if the command times out,
rerun the same command. Clear a stale lock only VERIFIED-DEAD: no suite
process exists (pgrep) AND the holder is identified dead.

**DESIGN DOCTRINE (user rulings, standing):**
- **Never hide errors** — failures surface as Result/Optional; no
  Void-swallowing, no sentinel collisions, no silent degradation.
- **Infer when accurate** — infer what is DETERMINED; be explicit where
  inference would guess; READER-VISIBILITY TRUMPS both (the call-site
  `&var` precedent — and Aug 18's `static` keyword ruling).
- **APIs do the expected thing, not the easy-to-implement thing** —
  hide complexity behind the surface a caller would predict.
- **No abbreviations in API names** (`SystemError` not `SysError`);
  terms of art (`Op`, `Right`) are words, not abbreviations.
- **Perf via measurement** — correctness first; optimize only from
  profiling data; no speculative perf work.
- **Kernels + embedded are first-class targets** — freestanding
  concerns shape runtime/stdlib design, never bolt on.

**POST-LANDING IDIOM REVIEW:** after integrating agent-written .saw
code, the lead skims it for idiom (against the saw-lang skill); catches
grow the skill so the next agent writes it right.

**LEAD SESSION OPS (macOS host):** start `caffeinate -ims &` before
long agent runs (never `-d` — the display must sleep), `pkill
caffeinate` at session end. Resume stalled agents via a message with
explicit recovery steps — a stopped agent's monitors and waiters are
dead, and its final "I'll wait for X" can never fire; verify claimed
state (lock dir, pgrep, branch commits) before acting on it.

**TRACKER FLOW (user, Aug 18):** `designs/todo.md` holds OPEN work only,
plus two standing pointer sections near the top — `[QUEUE]` (scheduled,
in order) and `[BACKLOG]` (filed, unscheduled) — one line per item
pointing at a DF entry below or a brief, never restating either. An
IMPLEMENTING AGENT closes its entry IN PLACE in todo.md (status +
landing note) and NEVER touches the done files; the LEAD moves closed
entries VERBATIM (never rewritten — old entries are often the sole
record of a mechanism) to the current week's `designs/done_<range>.md`
at INTEGRATION, after review/approval. A new done file starts each week
(aug18-aug25, then aug26-sep1, ...) and gets its `designs/INDEX.md`
line on creation. A tracker entry SUMMARIZES and points at its brief —
status, path, a few lines, bare one-line DF findings; evidence, repros
and staging live in the brief, never restated (two copies drift). Docs convention (design 125): LANGUAGE_SPEC.md
(authoritative), the saw-lang skill, AND README.md get feature updates
— NOT this file, whose digest below is only an orientation summary.
README carries the user-facing subset: anything a reader would pick Saw
for, plus the CLI / stdlib surfaces it already lists. User-facing prose
follows the saw-docs skill. Standing policy: fix user-facing bugs
on discovery unless genuinely ambiguous (then tracker + flag). Record
language pain hit while writing Saw as DF-findings in the tracker.

Four BRIEF OBLIGATIONS (1-3 from design 190's Aug-9 quality analysis;
4 added Aug 13 — each earned by a family of found bugs):
1. **A position-quantified rule is a funnel or a matrix.** A brief that
   introduces or touches a rule quantifying over "every position where X
   appears" either routes it through ONE chokepoint whose docstring NAMES
   its entry points, or carries an explicit position matrix its tests
   cover row by row. (Scattered rules grew 2-3 duplicate copies and every
   position gap of the week hid at a bypassed entry; funnels with named
   entries did not.)
2. **A behavioral-contract flip owes a consumer sweep.** A brief changing
   a behavioral contract — blocking→cooperative, by-value→by-pointer,
   eager→lazy, flag semantics — surveys "who relies on the old behavior"
   (grep + one paragraph) before dispatch. (The DF-182f irdet fork-bomb:
   cooperative `run()` deleted a throttle irdet relied on; loadavg >700.)
3. **A safety-surface brief writes its conformance rows first.** Since
   design 191 landed, a brief touching a safety guarantee adds/updates its
   `examples/conformance/` rows as its FIRST unit.
4. **A DF finding is presumed to be a CLASS until a sweep says otherwise.**
   Before a DF's fix is dispatched, name the MECHANISM that produced it (a
   bypassed funnel, an incompletely built scope, a missing check on one of
   several synthesized paths), enumerate the other positions that mechanism
   reaches, and probe them with compile/run evidence — the fix brief then
   targets the mechanism, with the sweep's matrix as its test plan, not the
   found symptom. A finding that really is one-off records WHY the
   mechanism admits no siblings instead. (Earned by DF-216a/b, Aug 13:
   both presented as isolated instances of general mechanisms — the
   comparison operators are one of several compiler-synthesized call
   constructions that skip `_check_value_transfer`, and `self` is one of
   several enclosing bindings a closure body's scope must carry.)

## Language state (orientation digest — details in spec/skill)
Landed through design 161 (Aug 6; 152, 154 and 157 are briefs, not yet
built — 155 and 158 landed Aug 7-8): full trait system (default bodies,
`any Trait` existentials, Equatable/Comparable/Hashable/Printable/
Error), overloading + labeled arguments (lenient model), generics with
default type params + default VALUES that drive inference (108) +
type-argument INFERENCE at call sites — args, closure returns,
overload sets (unique solver wins, ties error), later-arg fixpoint,
labeled mapping (93, 105) — with bounds checked for EVERY type arg
incl. primitives (109), Copy trait family + move checkpoint + Law of
Exclusivity, Result/Optional with auto-wrap + erased
`Result<T, Box<any Error>>`, full Swift-style optional chaining (111:
`a?.b?.c()` arbitrary length incl. call heads + method hops, one short-circuit
skips the rest of the postfix chain incl. args, flattening never `U??`, final
field must be copyable; chained assignment `x?.y = v` writes the payload in place,
types `Void?`, consumed via the `_`-blessed `if let`/`guard let`; a suspending
hop and a suspending chain both work since 120),
patterns (literals/ranges/guards/tuple
destructuring) + named tuples, collection literals (Map/Set/Vector),
platform-width Int, bounds/overflow/shift checks always on,
`#file`/`#line`/`#function` definition-site literals (98), shadowing
= error unless derived from the shadowed binding — incl. same-scope
redefinition and for-loop vars via the mentions-rule (100, 107).
Colorless concurrency: coroutine transform + one ambient cooperative
scheduler (89-b/c: live accept-loop servers work; op-budget fairness
backstop) + TaskGroup (MT via `threads: N`, Send-checked, fallible
constructor since 234) + channels +
precise reactor wakeup (91) + cancel wakes even an io-parked task
(102) + `extern blocking` calls RUN via thread offload (103). The
Thread/Task SPLIT (242, Aug 22-25): the namespace is the engine —
`Thread.spawn { }` is OS threads and blocking (`Thread<T>`/`VoidThread`,
body is `sync`, may call blocking externs), `Task.spawn(call())` is the
cooperative engine without a group (`Task<T>`/`VoidTask`, background
singleton, exit cancel-then-join); every non-group handle's FATE is
written (`join`/`detach`/`cancel` — discard is a compile error, backed
by a provenance-keyed drop panic), `detach()` exists on both engines,
a spawned brace captures NOTHING implicitly (the capture list IS the
parameter list), and the bare `spawn { }` is GONE;
suspending calls embed at any nesting depth / control-flow position
or error cleanly — never silently block (96, 101, 104) — and, since 120,
in any EXPRESSION position too (chains, args, receivers, operands,
literals, interpolation, return, `try!`, `?.` hops, value if/match,
`??`/`&&`/`||` RHS) via an ANF hoist in coro_transform that preserves
evaluation order and short-circuits; references
span suspends (88) and forward onward as re-borrows (106) + whole-referent
replacement `x = v` / `self = v` through `&var` (110: uniform with closures,
erased `&var any Trait` excluded, Box payload-swap works); std.net
owning TcpListener/TcpStream (failable ops return Result, EOF distinct
from error — 84-92). Freestanding toolkit: allocator type params +
Box/slab + statics/Atomic + UnsafeMemory + `@export`/`@section`.
Member visibility (design 80): struct fields + extension methods are
private-by-default outside the defining module (std under the gate
too — design 82 makes each std FILE its own module). Prelude
discipline (design 82): only a curated core is auto-visible
(primitives, Vector/Map/Set, Optional/Result/Box/Arc/Allocator, the
trait vocabulary incl. serde's Serialize/Deserialize/Encoder/Decoder,
the builtins + concurrency primitives — TaskGroup/`Task<T>`/VoidTask/
sleep/cancelled/Atomic, with `Thread.spawn`/`Task.spawn` as FORMS, not
importable names — StringBuilder, Duration); File/Data/Channel/Mutex/
SpinLock (std.spinlock)/Once (std.once)/slab (std.slab)/net (IoError/
IoErrorKind)/Utf8Error/path (Path)/directory (Directory)/process/env/
time (Instant)/fixedbuf (FixedBuf/
FixedStringBuilder)/cbor (CborEncoder/CborDecoder)/json (JsonValue)/
std.compiler.frame
(Slot/UnsafeRef/Poll/Resumable) — and `yield_now` + `dump_tasks`
(std.task, designs 114/158; the cooperative-yield
wrapper over the now stdlib-internal intrinsic) — need an import — so a
user type named `IoError`/`File` no longer collides. Imports are
RUST-STYLE and uniform across std and user modules (design 150, which
deleted design 82 Part B's std bare-exposure special case): `import
std.file` binds the last segment as a QUALIFIER and exposes nothing bare
(`file.File`, `time.Instant.now()`, `let t: time.Instant`, `&any
mod.Trait`, `<T: mod.Trait>` — every position a name appears);
`import std.file.*` is the bare opt-in; `import std.file.{A, B as C}`
selects exactly those names bare and binds NO qualifier (DF-247b, Aug 24:
each form binds exactly what it names — write the whole-module line too
when you want both; the pair is complementary, not a collision). `as`
renames the qualifier.
Qualifier bindings are WEAK — locals -> module decls -> imported bare
names -> qualifiers last — so a local `data`/`path`/`time` shadows one
lexically with no error, and the member-lookup failure names the
shadowing decl + three outs. Two imports on one qualifier error at the
import. Every form is a design-142 direct import. sawc gained `-W <name>`
/ `-W all` (design 150 4b): warnings OFF by default, never affect exit
code, no -Werror; first category `shadowed-qualifier`, emitted at the
declaration. Unsafe surface (design 130 + 136, superseding 81's marking rules):
unsafety is type-carried and DECLARED per declaration — `unsafe struct` marks a
type (compiler-enforced `Unsafe*` name; a plain `struct UnsafeDefaults` gets no
semantics); a function whose body or signature NAMES, BINDS, RECEIVES or
RETURNS an unsafe-typed value (a `&UnsafePointer<T>` counts) is declared with
`unsafe` in the POST-PARAMETER effect slot beside `sync` —
`func f(...) unsafe -> T`, matching the type grammar `(T) unsafe sync -> R`
(prefix spelling is an error with a fixit; 136). A function TYPE may carry
`unsafe` iff its signature names an unsafe type (a safe-signature `unsafe`
type is the rule-7 teaching error); closures INHERIT the enclosing function's
unsafe domain (no closure-level marker — confinement is a signature, i.e. a
small named `unsafe` helper). NOT transitive
(`Vector` holds a raw pointer and stays a safe type — only the methods reaching
through it are marked); calling an unsafe
function from safe code needs no ceremony, made sound by the rule that a
function with all-safe parameters must be sound for every input (a precondition
is spelled as an unsafe-typed parameter). The line-level `unsafe` expression
marker is GONE (writing one is a parse error). Accessor rule: on a safe type
every indexed accessor is checked — direct accessors panic out of range
(`Vector.set`/`swap`/`swap_out`/`with_ref`/`with_var_ref`, `Data.set`,
`FixedBuf.set`, `String.byte_at`/`substring`), `get`-shaped ones return
`None`/`Err` (`Vector.get`, `Data.get`, `Data.slice`, `FixedBuf.get` — the
last since DF-294a, which was the enumeration's one divergence); no silent
no-ops, no clamps, no ignorable status flags.
`Vector.with_ref`/`with_var_ref` (scoped, invalidation-proof element borrow)
replaced `ref_at`. The Aug-5 batch (122-131): every runtime-check panic
carries `panic at FILE:LINE:` (122); ONE allocator-failure policy —
every allocating std op returns `Result<_, AllocError>` all-or-nothing,
design 123's panic tier and its `try_` twins RETIRED by design 234
(Aug 25: constructors fallible via `Result<Self, E>` inits, `try_` now
means NON-BLOCKING only, the `try_copy` family — Vector's, Map's,
Set's — the surviving alloc twins pending
DF-257b's naming ruling; the five documented panic boundaries are
compiler-inserted allocations, collection literals, `copy()`, `Data`'s
CoW subscript, and the String layer); TaskGroup teardown is EAGER —
a group is a scope, task-owned values deinit at task completion via a
synthesized frame `__release` (124); the op budget charges LOOP BACKEDGES in
task bodies so pure-compute spinners cannot starve siblings (sync callees
exempt — the speed escape hatch; 127); structural Deinit is IMPLICIT and
every DECLARED empty-conformance derivation (Equatable/Comparable/Hashable/
Copy/ExplicitCopy) is gated on `@synthesize`; `var self` receivers
rejected (128); newlines are insignificant inside `()`/`[]`/committed
generic `<>` with trailing commas in the first two, unclosed brackets error
at the OPENER (129); payload reads are policy-driven PLACES — `o!`/`??`/
`if let` follow the payload's copy policy (the Copy tier retains;
ExplicitCopy/NoCopy demand `move o!` on a local, `o!.copy()`, or
`Optional.take(&var self)` — the field-safe move-out `Task.join` now
uses); `Deinit` is NON-declarable — a copy-policy conformance carries any
hand-written deinit body, which PREFIXES the synthesized field drops (131).
Doc comments (121):
`///` (following decl) + `//!` (module) lexed as trivia in BOTH lexers
(`sawc2 lex --docs` dump), parser-attached with unattached-doc
errors, `--emit-docs` JSON of the typechecked surface (design-80 gate on
members); std.task + std.time docstringed; the saw-docs skill is the
style guide for all user-facing doc text.
The Aug-6 batch (135-161): `--no-hidden-alloc` rejects the THREE allocations
the compiler inserts that no source construct names — interpolation anywhere
(no panic/assert carve-out), an escaping closure's captured env, and
single-arg `print` of a user Printable (135); `{}` FORMAT ARGUMENTS on
`print`/`panic`/`assert` (`print("x = {}", x)`) render through stack scratch
and allocate nothing, slot-vs-arg count is a compile error, and
`StringBuilder(bytes:capacity:)` fixed mode cuts on a UTF-8 boundary with `…`
+ `is_truncated()` (137). PLACES (141 + 146): a `borrows` method LENDS storage
(`lend` is a suspension of the accessor, not a return — prologue, window,
epilogue), the USE SITE picks shared vs exclusive out of ONE `&self`
declaration, windows nest LIFO, `borrows -> T?` is the conditional lend whose
absent path opens no window, a borrowing `match` arm may lend its PAYLOAD
binding (DF-146d), and a place borrow charges its ROOT so `v.push` inside a
window is a clean exclusivity error; `v[i]`/`d[i]`/`Vector.get`/`Map.[]` are
all places, value reads follow the copy tier, and a place read in a generic
body needs a `Copy` bound. Extensions are IMPORT-SCOPED (own module + direct
imports + the receiver's defining module; a transitive dep contributes
nothing) while CONFORMANCES follow the ORPHAN RULE (142); TYPE IDENTITY is
(defining module, name), so a dep's private `Header` reserves nothing (144).
ENUMS gained extensions — methods, statics, hand-written trait bodies,
`@synthesize`, no `init` — plus RAW BACKINGS (`enum E: UInt8` with every case
stating its value; `e as UInt8` total, `E.from(raw:) -> E?` partial), which is
the wire idiom (145). CONST GENERICS `<const N: Int>` + the repeat literal
`[v; N]`, folded before mangling, `[T; N]` params inferring N (148). Runtime
authoring (149): `unsafe static var` for compound global state (prefix
position, exempt from Sync, triggers 130's rule at every touching function),
`SpinLock<T>` const-initializable in a static with a `sync`-ENFORCED body, an
all-zero static costs no image bytes, and `[package] runtime = true` lets a
package BE the runtime with each seam checked against rt/ABI.md. Discarding a
`Result` is a COMPILE ERROR in every implicit-discard position — `let _ =` is
the explicit out, Result only (151). The automatic Copy TIER (named
ImplicitCopy before design 219 unified the silently-copyable tier): a
struct/enum whose owning members are all trivial/Copy IS Copy
with no declaration owed, copies retaining each member (139 wrappers carry the
tier they wrap; 159 fixed the missing retain). A tuple index never eats a
following `.`, so `t.0.name` and `t.0.1` work and a float literal needs a
digit on each side (161). Tooling: the test runner is two-stage and pipelined
behind a settle lag (156) and can shard onto a sandboxed remote worker (160) —
see TESTING.md. Blade (package manager
in Saw) is self-hosting. License: Apache-2.0 WITH LLVM-exception.

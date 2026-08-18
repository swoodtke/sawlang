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
examples/          # Compiler test suite programs (test_runner.py)
blade/             # Blade package manager (written in Saw)
libs/              # Real Saw library packages (semver, toml)
tools/blade_bootstrap.py  # Self-hosting bootstrap loop
designs/           # Design briefs + todo.md tracker
sos/               # SOS microkernel (design 140). spec.md is authoritative.
  kernel/          #   main.saw + core/lib.saw — the module EVERY kernel
                   #   image shares (drivers, trap frame, ktrap, the
                   #   object-op dispatch, the sosimg loader)
  kernel/abi/      #   KERNEL-INTERNAL: every op number/right/status, in one
                   #   place, shared by the dispatch and the wrappers below
  kernel/sysapi/   #   the PUBLIC `sos` module the kernel EXPORTS to userspace
                   #   (vDSO discipline: numbers are not ABI). Typed Saw +
                   #   @export'd C surface; a process depends on this only
  hal/riscv32/     #   the arch-aware code, one dir per arch (riscv32 +
  hal/arm64/       #   arm64, landed by design 162/M1b): kernel/ (boot.S trap
                   #   entry, board sinks, PMP, virt.ld) + user/ (the ecall
                   #   stub — design 172 part 2 left nothing else in
                   #   syscall.c — plus root.ld), each with an ABI.md.
                   #   virt.ld/root.ld live per-arch here, not under kernel/
                   #   or root/
  rt/common/       #   `sosrt`: THE SOS RUNTIME, arch-free + role-free Saw —
                   #   the four `__saw_rt_*` seams + the bump arena, over two
                   #   per-side hooks, plus hex/ascii helpers. Kernel + every
                   #   process. Its exports need `--runtime-provider` (design
                   #   149): sos_runner passes it, a process image says
                   #   `[package] runtime = true`
  rt/common_c/     #   support.c — the C that must stay C: mem* + the atomic
                   #   libcalls, ONE copy, see DF-140g
  imgformat/       #   the sosimg layout, shared by BOTH consumers: Blade via a
                   #   path dependency, the kernel via --module-path
  root/            #   the root server: a real Blade package, `[sos] emit =
                   #   "sosimg"`, banners via a System op and shuts down
  tests/           #   kernel entries + hand-assembled payloads/images
                   # `make sos-test` (tools/sos_runner.py) builds kernel AND
                   # root, stitches them, boots them under QEMU. Kernel builds
                   # need --module-path kcore=/imgformat=/sosrt=
```

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
    [--emit-ir] [--emit-ast] [--ids] [--emit-docs] [--emit-docs-all] [-O0]
    [--emit-frame-layout] [--emit-bt-table]
    [--target TRIPLE] [--target-features FEATURES]
    [--module-path NAME=DIR]
    [--freestanding] [--runtime-build] [--runtime-provider]
    [--no-hidden-alloc] [-W NAME | -W all]
```
That is the complete flag set (`sawc.py:1774-1876`); `-o` defaults to
`.build/<source>`. `--no-hidden-alloc` (design 135) rejects the
allocations the compiler inserts that no source construct names.
`-W` (design 150) enables a warning category (repeatable, `-W all` for
every one; warnings are off by default and never affect the exit code).
Default pipeline is O1-style. `--module-path` maps a package name to a
module dir (Blade uses this per dependency). `--runtime-build` (design
113b) compiles a Saw runtime that `@export`s the frozen `__saw_rt_*` ABI
(sync-only, object output) — used to build `sawc/rt/`; the hosted runtime
objects are built + cached under `.build/rt/` and auto-linked (delete
`.build/rt/` to force a rebuild; `-v` lists the linked objects).

## Testing
- `make test` (venv active) or `./.venv/bin/python test_runner.py` —
  full compiler suite, ~1 min uncontended. Multi-pattern filter:
  `./.venv/bin/python test_runner.py -f test_a,test_b`.
- **PER-COMMIT GATE POLICY (user, Aug 17):** a COMPILER change gates on
  BOTH the full compiler suite AND `tools/sos_runner.py` (both arches)
  before every commit — compiler changes can break kernel codegen and
  the suite alone does not cover sos/. An SOS-ONLY change (everything
  under sos/) gates on sos_runner ONLY — the compiler suite does not
  exercise it. A change touching both gates on both. TERMINAL gates
  scope the same way (user, Aug 17): a compiler branch owes the FULL
  battery; an SOS-only branch owes `battery.sh suite sos` — the five
  slow lanes are compiler oracles and test nothing such a branch
  changed; the suite runs once because new .saw files (tests, pins)
  join the corpus and must prove they behave. Harness edits
  (tools/sos_runner.py) and examples/ pin files do not make a branch
  a compiler branch. XFAIL policy (user, Aug 7): a
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
  — cheap enough per commit. **A brief's FINAL gate battery runs
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
  tools/battery.sh --quick        # skips reemit/irdet/gmgate/bootstrap/sos
  tools/battery.sh suite fuzz     # named stages
  tools/battery.sh --list
  ```
  Stages: `suite`, `icebreadcrumb`, `lexdiff`, `astdiff`, `astgraft`,
  `forgetgate`, `ircontract`, `preludegate`, `stdtypes`, `abidoc`, `bttable`,
  `fuzz` (`sawfuzz --quick`), `corodiff` (`--quick`), `bench` (the warehouse
  benchmark — checksums GATE, timing report-only; devtools/bench/ +
  TESTING.md), `selfhostlex` (the selfhost lexer's own tests — the one tree
  the Aug-10 coverage sweep found NO stage ran), then the slow five
  `reemit` (design 221 A2: TWO compiles in ONE process, byte-comparing the
  unopt IR, the OPTIMIZED IR and the object — the optimized IR is the
  artifact DF-220a moved and the only one nothing checked),
  `irdet` (`--all`, whole corpus), `gmgate` (both lanes), `bootstrap`,
  `sos`. Every stage RUNS even after one fails; the exit code is the
  number of failing stages. Adding a lane means editing `STAGES`.
  Coverage map (Aug-10 sweep): blade/tests + libs/*/tests are
  typechecked+run by `bootstrap` ONLY (so `--quick` skips them);
  sos/tests by `sos` only; lexdiff/astdiff lex/parse EVERY tracked .saw
  but check no semantics.
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

## Design-brief workflow
Design decisions are made WITH the user, recorded as `designs/NN-*.md`
briefs, implemented by dispatched agents (one at a time on `main`;
concurrent only in isolated worktrees, cherry-picked back — linear
history, no merge commits). Each brief lands in small per-unit commits,
full suite green each.

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

**WORKTREES + INTEGRATION:** ALL implementation work happens in
isolated worktrees — never commit implementation directly on main (the
lead may commit docs/briefs/tracker rulings directly). Integrate by
cherry-pick/rebase only, never merge commits; agents keep their own
branches linear (rebase on main if behind). Resolve conflicts HUNK BY
HUNK with the editor — NEVER `checkout --theirs/--ours` on a shared
accumulator file (todo.md, INDEX.md, SKILL.md): it replaces the whole
file and silently discards the other side's non-conflicted entries
(this happened Aug 17; recovered from history). After any
accumulator-file resolution, sanity-grep a couple of entries that exist
only on the other side. After integrating: remove the worktree, delete
the branch, run the integration gate on main. Two concurrent agents WILL
collide on DF numbers — assign ranges at dispatch or renumber at
integration. SOS-side branches PARK for USER review before merging;
compiler briefs follow the normal flow.

**AGENT CONDUCT:** no workarounds — an agent that hits a language bug or
blocked dependency STOPS that unit, files a DF (mechanism named, per
obligation 4), and reports; it never codes around a compiler defect.
Never add attribution trailers (Co-Authored-By etc.) to commit messages.
HANDOFF.md is session state — never commit it. A fix that closes a
finding filed by a differential/fuzz harness removes the harness's
known-ledger entry (corodiff_known.txt, sawfuzz_known.txt) in the SAME
commit, and its gate includes that harness's lane.

**THE SUITE LOCK (machine-wide):** all suite-shaped invocations
(test_runner, battery.sh, sos_runner) serialize through a mkdir lock at
`/private/tmp/claude-<uid>/saw-suite-lock` (uid = `id -u`; create the
parent once per machine). Acquire + gate + release in ONE chained
FOREGROUND command: `until mkdir <lock> 2>/dev/null; do sleep 15; done;
<gate>; rc=$?; rmdir <lock>; echo GATE=$rc`. Never background the wait
or the gate (a stopped agent's background waiters die silently); never
hold the lock while editing; if the command times out, rerun the same
command. Clear a stale lock only VERIFIED-DEAD: no suite process exists
(pgrep) AND the holder is identified dead.

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
backstop) + TaskGroup (MT via `threads: N`, Send-checked) + channels +
precise reactor wakeup (91) + cancel wakes even an io-parked task
(102) + `extern blocking` calls RUN via thread offload (103);
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
trait vocabulary, the builtins + concurrency primitives,
StringBuilder); File/Data/Channel/Mutex/SpinLock/net/IoError/Utf8Error/
process/env/time/fixedbuf (FixedBuf/FixedStringBuilder) — and `yield_now`
(std.task, design 114; the cooperative-yield
wrapper over the now stdlib-internal intrinsic) — need an import — so a
user type named `IoError`/`File` no longer collides. Imports are
RUST-STYLE and uniform across std and user modules (design 150, which
deleted design 82 Part B's std bare-exposure special case): `import
std.file` binds the last segment as a QUALIFIER and exposes nothing bare
(`file.File`, `time.Instant.now()`, `let d: time.Duration`, `&any
mod.Trait`, `<T: mod.Trait>` — every position a name appears);
`import std.file.*` is the bare opt-in; `import std.file.{A, B as C}`
selects bare AND binds the qualifier. `as` renames the qualifier.
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
`String.byte_at`/`substring`), `get`-shaped ones return `None`/`Err`
(`Vector.get`, `Data.get`, `Data.slice`); no silent
no-ops, no clamps, no ignorable status flags.
`Vector.with_ref`/`with_var_ref` (scoped, invalidation-proof element borrow)
replaced `ref_at`. The Aug-5 batch (122-131): every runtime-check panic
carries `panic at FILE:LINE:` (122); ONE allocator-failure policy —
infallible ops panic naming their method, `try_` twins return
`Result<_, AllocError>` all-or-nothing (123); TaskGroup teardown is EAGER —
a group is a scope, task-owned values deinit at task completion via a
synthesized frame `__release` (124); the op budget charges LOOP BACKEDGES in
task bodies so pure-compute spinners cannot starve siblings (sync callees
exempt — the speed escape hatch; 127); structural Deinit is IMPLICIT and
every DECLARED empty-conformance derivation (Equatable/Comparable/Hashable/
ExplicitCopy/ImplicitCopy) is gated on `@synthesize`; `var self` receivers
rejected (128); newlines are insignificant inside `()`/`[]`/committed
generic `<>` with trailing commas in the first two, unclosed brackets error
at the OPENER (129); payload reads are policy-driven PLACES — `o!`/`??`/
`if let` follow the payload's copy policy (ImplicitCopy retains;
ExplicitCopy/NoCopy demand `move o!` on a local, `o!.copy()`, or
`Optional.take(&var self)` — the field-safe move-out `TaskHandle.join` now
uses); `Deinit` is NON-declarable — a copy-policy conformance carries any
hand-written deinit body, which PREFIXES the synthesized field drops (131).
Doc comments (121):
`///` (following decl) + `//!` (module) lexed as trivia in BOTH lexers
(lexdiff parity, `--docs` dump), parser-attached with unattached-doc
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
the explicit out, Result only (151). The automatic ImplicitCopy TIER: a
struct/enum whose owning members are all trivial/ImplicitCopy IS ImplicitCopy
with no declaration owed, copies retaining each member (139 wrappers carry the
tier they wrap; 159 fixed the missing retain). A tuple index never eats a
following `.`, so `t.0.name` and `t.0.1` work and a float literal needs a
digit on each side (161). Tooling: the test runner is two-stage and pipelined
behind a settle lag (156) and can shard onto a sandboxed remote worker (160) —
see TESTING.md. Blade (package manager
in Saw) is self-hosting. License: Apache-2.0 WITH LLVM-exception.

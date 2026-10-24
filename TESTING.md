# Testing Guide for Saw Language

## Overview

Saw's tests come in three kinds:

- **Corpus programs** under `tests/corpus/`: ordinary Saw programs whose
  comment directives state what the compiler and the program must do. The
  corpus differential (`compiler/tests/corpusdiff/`) builds and runs each with
  `sawc` and judges it by its directives and by the run v0.18.0's compiler
  recorded for its frozen `examples/` twin.
- **The compiler's own tests** under `compiler/tests/`, run by
  `compiler/tests/run.py`: unit programs, golden dumps and refusal fixtures for
  every compiler stage, and the checks over the compiler's source.
- **The battery** (`tools/battery.sh`): the lanes above plus the checks of the
  files nothing compiles, the toolchain resolver, the gate itself and the
  ownership oracles under Guard Malloc.

## Running Tests

### Quick Start

```bash
# The per-patch gate, every part (what the merge server runs, unnarrowed)
./build.sh test

# What one change needs: the gate's decision for the paths since REV
./build.sh test --changed-since main
./build.sh test --changed-since main --dry-run      # the decision alone

# Named steps of the compiler's tests, building sawc first when they need it
./.venv/bin/python compiler/tests/run.py --only units,parser

# Some corpus programs through sawc, judged as the gate judges them; a PATH
# is relative to tests/corpus/
./.venv/bin/python compiler/tests/corpusdiff/corpusdiff.py run hello.saw errors/align_on_function.saw
```

The tools use the standard library alone, so `.venv/` only pins the
interpreter; `./build.sh test` makes it when it is absent.

### Test Results

The corpus differential puts each program in one bucket under one key:
`pass`, `refused` (sawc refuses it, keyed by the rule), `crash`, `wrong`,
`link`, `stage0-wrong` (the recorded run is itself wrong, annotated with the
finding), `nondeterministic` and `slow`. The baseline,
`compiler/tests/corpusdiff/corpus_diff.tsv`, records every program's verdict,
and the gate fails a patch that moves any of them, an improvement included. A
patch that moves one on purpose records it with `corpusdiff.py run --baseline`
in the same patch. `compiler/tests/corpusdiff/README.md` is the specification.

## Writing Tests

### Test Directives

Add test metadata using special comments at the top of `.saw` files:

#### Success Tests

For programs that should compile and run successfully:

```saw
// EXPECT: success
// EXPECT-OUTPUT:
// Hello, World!
// 42

func main() {
    print("Hello, World!")
    print(42)
}
```

#### Error Tests

For programs that should fail to compile:

```saw
// EXPECT: error
// EXPECT-ERROR-CONTAINS: undefined variable

func main() {
    print(x)  // x is not defined
}
```

### Directive Reference

One `EXPECT:` mode picks what a verdict means:

| Directive | Description |
|-----------|-------------|
| `// EXPECT: success` | Test should compile and run successfully |
| `// EXPECT: error` | Test should fail during compilation |
| `// EXPECT: compiles` | Test should compile, and that is the whole assertion; it is never run. For the accept side of a rule, where the program has nothing to say at runtime — it takes no output/panic/error assertion and rejects one, so a behavior test cannot silently stop checking behavior. Prefer `success` whenever the run asserts something real |
| `// EXPECT: panic` | Test should compile but panic at runtime |
| `// EXPECT: object` | Compile to an object file; no run (freestanding, `-c`; `sawc` has no object output yet, SL-865) |
| `// EXPECT: docs` | Compile with `--emit-docs`; the JSON is the output checked (`sawc` has no `--emit-docs` yet, SL-880) |
| `// EXPECT: skip` | Skip the file entirely (library modules, not tests) |

The rest constrain what the run must show:

| Directive | Description |
|-----------|-------------|
| `// EXPECT-OUTPUT:` | Lines following are expected stdout (one line per `//`) |
| `// EXPECT-OUTPUT-CONTAINS: text` | Stdout must contain "text". Repeatable, and matched IN ORDER — each match starts where the previous one ended. One space after the colon is the separator and everything after it counts, LEADING WHITESPACE INCLUDED, which is what `EXPECT-OUTPUT:` cannot express (it strips every line, so indented output is unmatchable there) |
| `// EXPECT-ERROR-CONTAINS: text` | Error message must contain "text" |
| `// EXPECT-ERROR-ABSENT: text` | …and must NOT contain "text". A diagnostic fix is often about the lines that are GONE — DF-232o's refusal used to bury itself under a cascade of its own consequences, and nothing else can pin the cascade away |
| `// EXPECT-PANIC-CONTAINS: text` | Panic message must contain "text" |
| `// EXPECT-WARNING-CONTAINS: text` | A warning must contain "text" (warnings ride the SUCCESS path and never change the exit code, so they need their own directive; `sawc` has no warnings yet, SL-879) |
| `// EXPECT-NO-WARNINGS` | The compile must emit no warning at all |
| `// EXPECT-SYMBOL-UNDEFINED: sym` | `nm` must report `sym` as undefined in the object |
| `// EXPECT-OBJECT-MAX-BYTES: n` | The emitted object must be at most `n` bytes |
| `// COMPILE-FLAGS: ...` | Extra compiler flags for this test; `{TESTDIR}` expands to the file's directory |
| `// XFAIL: reason` | Known-broken test: failure is expected, does not break the build |

### Known Failures (XFAIL)

When a test captures a real bug you are not fixing yet, mark it `// XFAIL:` with
a reason rather than deleting it or using `// EXPECT: skip`. The reason cites
the filed finding (an `SL-` issue, or an older `DF-` number):

```saw
// EXPECT: success
// EXPECT-OUTPUT: stdout: hello
// XFAIL: SL-123 Command.output() returns empty stdout; capture is lost in std/process.saw

func main() { ... }
```

Keep the `EXPECT` directives describing the **correct** behavior, so the fix
is what flips the verdict. The point of this over `skip` is that reverse
signal: `skip` silently drops the file from discovery, so a fix would go
unnoticed and the coverage would stay lost.

A marker goes stale in a second way the directives cannot see. When a finding
is closed by a ruling that SUPERSEDES the behaviour its pin asserts, the pin
keeps failing — a well-behaved known failure forever, citing a finding that is
done. The `citations` battery lane reads the marker's CITATION against the
tracker's closed set and catches that direction; see "The citations stage".

### Required Directives

All tests **must** have explicit directives:

1. **`// EXPECT: success`** or **`// EXPECT: error`** - Required for all tests
2. **`// EXPECT-OUTPUT:`** or **`// EXPECT-OUTPUT-CONTAINS:`** - Required for
   success tests (at least one output line, or one substring)
3. **`// EXPECT-ERROR-CONTAINS:`** - Required for error tests (at least one)

### Waiting in a multi-threaded test

A test over a `threads: N` group has to wait for something another thread did,
and the tempting way to write that wait is a sleep wide enough to *obviously*
cover it. That is what `task_backtrace_mt.saw` did — a 150ms margin its own
header called "wide on purpose" — and it cost an agent a whole battery re-run
when a second agent's load pushed the pool's startup past it (DF-246a). Wide is
not the same as synchronized.

Three rules, ruled Aug 24. They bind every test that waits on another thread.

**1. A fixed sleep is never a synchronizer.** It may PACE a poll loop; it may
never establish state. A `sleep(Duration.ms(50))` followed by code that assumes
the peer has drained a channel is a race the sleep hides rather than a wait: the
assumption is written nowhere, so nothing checks it, and the failure arrives
weeks later as a mysterious red cell on somebody else's branch.

**2. The awaited state must be STABLE once reached.** Wait for something that,
once true, STAYS true until the test itself changes it. In practice that means
the peer parks on a gate THE TEST OWNS — a channel nothing sends on until after
the observation, an `Atomic` the observer flips — never on a timer, whose window
closes on its own schedule. A stable state makes the observation impossible to
be LATE for, which is half the race gone.

**3. Observe by POLLING the observation itself, under a generous deadline.**
Poll the thing the test is about to assert on — the peer's own progress report,
the total it publishes, the value it sends back — until the stable state
appears. The deadline is there to bound genuine breakage, not to time the wait:
make it seconds where the real wait is microseconds, and fail loudly (a `panic`
naming what never arrived) rather than hanging into the runner's 30s kill.

**There is no synchronized `dump_tasks` twin, and there will not be one.** The
MT walk being unsynchronized is a recorded feature of design 158 — a worker may
be resuming a frame while the walk reads it, and the dump's own header says so.
What a test owes is the other half: looking at a moment IT chose.

#### The idiom: park on a gate the test controls

```saw
import std.channel.{Channel}

// The tick paces the poll and decides nothing; the deadline is ~10s, well
// inside the runner's 30s runtime limit, so only real breakage reaches it.
static POLL_TICK_MS: UInt64 = 1
static POLL_DEADLINE_TICKS: Int = 10000

// The worker announces its arrival, then parks on a gate nothing sends on until
// the observation is over — so once it is parked it STAYS parked (rule 2).
func worker(gate: Channel<Int>, ready: Channel<Int>) -> Int {
    try! ready.send(1)
    let _ = gate.receive()
    7
}

// The observer waits for the ARRIVAL, not for the clock (rules 1 and 3).
func observer(gate: Channel<Int>, ready: Channel<Int>) -> Int {
    var arrived = false
    var ticks = 0
    while not arrived {
        sleep(Duration.ms(POLL_TICK_MS))
        match ready.try_receive() {
            case Ok(report) -> { arrived = report.is_some() },
            case Err(e) -> { panic("the ready channel failed: {}", e.describe()) }
        }
        ticks = ticks + 1
        if ticks > POLL_DEADLINE_TICKS {
            panic("the worker never reached the gate")
        }
    }
    observe()
    let _ = gate.close()      // only NOW may the worker move again
    0
}
```

`Channel.try_receive` is the poll primitive: `Ok(Some(v))` a report,
`Ok(None)` nothing yet, `Err(Closed)` a peer that will never report. An
`Atomic<Int>` in a `static` reads the same way when the report carries no value.

What the idiom does NOT give you is a proof that the peer has finished parking:
no userland test can observe a peer's park, and between the arrival report and
the park sit a handful of instructions. What it changes is the SHAPE of the
remaining window. The old margin raced against pool startup — hundreds of
milliseconds under load, which is what it lost to; this races a few instructions
of user code against a whole poll period, and the state on the other side is
permanent rather than a four-second window that also expires. Both rewritten
tests (`tests/corpus/task_backtrace_mt.saw`,
`tests/corpus/channel_receive_cancel_mt.saw`) ran byte-identically 10/10 in
isolation and 10/10 at loadavg 34, and the backtrace one went from 3.9s per run
to 0.01s along the way: waiting on state is faster than waiting on a margin.

One wrinkle particular to backtrace tests: a RUNNING task's dump row names its
last suspension point, and a poll loop that may turn once or a thousand times
does not have one to name — it reports line 0. A `yield_now()` immediately ahead
of the observation gives the observer's own row a line the test can pin.

And the standing rule this sits on top of: assert MT behaviour on counts, sums
and final states, never on interleaving.

## Examples

### Example 1: Simple Success Test

```saw
// EXPECT: success
// EXPECT-OUTPUT:
// 7

struct Point {
    x: Int
    y: Int
}

extension Point {
    func distance(&self) -> Int {
        self.x + self.y
    }
}

func main() {
    let p = Point(x: 3, y: 4)
    print(p.distance())
}
```

### Example 2: Multi-Line Output Test

```saw
// EXPECT: success
// EXPECT-OUTPUT:
// Basic math:
// 30
// 200

func main() {
    print("Basic math:")
    print(10 + 20)
    print(10 * 20)
}
```

### Example 3: Error Test with Message Validation

```saw
// EXPECT: error
// EXPECT-ERROR-CONTAINS: cannot assign to immutable variable

func main() {
    let x = 10
    x = 20  // Error: x is immutable
}
```

### Example 4: Multiple Error Validations

```saw
// EXPECT: error
// EXPECT-ERROR-CONTAINS: undefined variable
// EXPECT-ERROR-CONTAINS: type mismatch

func main() {
    let x = unknownVar + 5
    let y: String = 42
}
```

## Test Organization

```
tests/corpus/
├── hello.saw              # Basic success tests
├── ...
├── errors/                # Error test cases
│   └── ...
└── conformance/           # One row per claimed safety guarantee (design 191)
    ├── INDEX.md           # The ledger — see below
    ├── M22_place_write_let_root.saw
    ├── ...
    └── modules/           # Helper modules, excluded from discovery
```

`examples/` is the same tree as it stood at v0.18.0, frozen: it is the key of
the recorded Stage 0 snapshots and is never edited. A corpus program edited
since is judged by its own directives alone (detached), and a new program with
no `examples/` twin is judged the same way (native); either one's verdict move
is recorded with `corpusdiff.py run --baseline` in the same patch.

### The conformance suite and its INDEX

`tests/corpus/conformance/` holds the standing check that every safety
guarantee the language CLAIMS is a guarantee something actually asserts. It
came out of the Aug-8 audit, which probed 247 claimed guarantees in one pass and
found nine holes; the suite is that pass, measured on every patch that reaches
the corpus differential.

```bash
# One row's program; a PATH is relative to tests/corpus/
./.venv/bin/python compiler/tests/corpusdiff/corpusdiff.py run conformance/M22_place_write_let_root.saw
```

**`tests/corpus/conformance/INDEX.md` is the convention that makes it a ledger
rather than a pile of tests.** Every row of the audit is listed there with the
file that covers it — a file in `conformance/` when the row needed one, an
existing `tests/corpus/` test when one already asserts the same rule at the same
position. A reader auditing coverage reads the INDEX, not the directory: the
directory shows what was written, the INDEX shows what is CLAIMED and where
each claim is checked, which is the only view in which a missing row is
visible.

Three rules follow from that, and they bind anything touching this directory:

1. **A row's file names its row in its first comment line** (`// Conformance
   row M22 — …`), so a failure report leads back to the INDEX.
2. **Adding, moving or deduping a row updates the INDEX in the same commit.**
   A row whose pointer goes stale is worse than a missing row, because the
   table then reads as covered.
3. **A regressing row is a red FAIL**, and the XFAIL policy applies unchanged:
   a marker is legal only as the pin of a filed finding, cited in its reason.
   The commit that fixes a conformance regression UPDATES the row — it never
   deletes it.

Per design 190's third process rule, a brief that touches a safety guarantee
adds or updates its conformance rows as its FIRST unit.

## The Self-Hosted Compiler's Tests

```bash
./.venv/bin/python compiler/tests/run.py
./.venv/bin/python compiler/tests/run.py --only mir,programs   # those steps, building sawc first if they need it
```

The compiler written in Saw (`compiler/`, epic SL-398) has its own tests until
it can run its own `@test` sidecars. `compiler/README.md` describes them in
full; in short, the runner:

- builds `sawc` (the seed builds Stage 1, Stage 1 builds Stage 2) and every
  unit program (`compiler/<stage>/tests/*.saw`) with sawc, and runs each unit
  program: exit 0 is a pass;
- compares `sawc lex` with each golden fixture in `compiler/tests/lex/`
  (`NAME.saw` beside its expected `NAME.tokens`, and `NAME.docs` for doc
  trivia), byte for byte;
- requires one release number everywhere it is written (the `version` step):
  the driver's `driver_version`, what `sawc --version` prints and the release
  tag in `.sawtracker/version`, so a release bump edits both files;
- holds each frozen directory (`blade/`, `libs/`, `tests/freestanding/`,
  `examples/`, `prototypes/`, `devtools/bench/`, `devtools/dogfood/`) to the
  git tree `tools/frozen_trees.tsv` records, with nothing in it uncommitted
  (the `frozen` step). Nothing builds those sources, so this is what keeps
  their v0.18.0 recipes true;
- refuses a fixture line that ends in whitespace, or a fixture that ends in a
  blank line, naming the file and line: the patch server applies patches with
  `git apply --whitespace=fix`, which strips both;
- fails if a token kind the lexer declares, or a kind of lex error it reports,
  appears in no fixture;
- runs the subset checker (`compiler/tools/subset_check.py`), whose hygiene
  rules read each file with sawc, over the compiler's own source, and over its
  fixtures in `compiler/tests/subset/`, whose `// refuses: RULE` markers name
  exactly what each must report;
- runs the grammar lint (`compiler/tests/grammar/lint.py`) over `GRAMMAR.md`,
  and each lint check's fixture, which injects one defect into a small grammar
  and names the line the check must report;
- runs the reference recognizer's own tests: the trees and coverage records
  pinned in `compiler/tests/grammar/fixtures/trees/`, the refusals pinned in
  `compiler/tests/grammar/fixtures/refusals/`, and for every rule the recognizer
  applies, a fixture it is seen deciding: switched off, the fixture's tree
  count changes or its refused text parses.

The full-corpus recognizer run is the battery's `grammarcorpus` lane:

```bash
./.venv/bin/python compiler/tests/grammar/corpus.py            # the lane
./.venv/bin/python compiler/tests/grammar/corpus.py FILE...    # these files only
./.venv/bin/python compiler/tests/grammar/corpus.py --write    # record the corpus
```

It recognizes every tracked `.saw` file with the grammar and compares each
verdict with `compiler/tests/grammar/corpus_expected.tsv`. The record is a
statement about `GRAMMAR.md`, so the recognizer refuses what the grammar's
productions and its section-13 rules refuse, naming the rule. The record lists
each refused file with its verdict and a classified reason: `a-removed` names
the removed form the file uses, `a-error` is a file sawc's parser refuses too,
and `c-conflict` one it accepts, which a ruling or a filed finding must explain.
A file that a rule the recognizer does not model yet refuses is listed by hand, as
`UNMODELLED` with the reason `unmodelled: RULE`, never left unlisted. A file the
record does not list must be accepted with exactly one tree. When a change
moves a verdict on purpose, run `--write`, which keeps the `UNMODELLED` rows,
and review the record's diff.

It prints one line per failure, then one summary line, and exits 1 on any
failure. The golden fixtures are the lexer's oracle.

### The per-patch gate

`./build.sh test` is what sawtracker runs on every submitted patch, as
`./build.sh test --changed-since HEAD^` (`.sawtracker/tests.json`). The
decision is `tools/patch_gate.py`'s. Every part builds and runs sawc:

- the compiler tests above always run;
- the fixpoint lane (`compiler/tests/fixpoint/fixpoint_lane.py`) runs when
  `compiler/` (the lane itself, `compiler/tools/build.py` and the seed's
  manifest and pin in `compiler/seed/` included), `std/`,
  `runtime/` (the runtime Stage 1 builds, which every later link takes) or
  `tests/corpus/` (the programs the replayed lanes run sawc over) changes,
  so a local gate never runs it. The gate runs its default mode, which compares
  every call but the candidate texts the grammar generator and mutator lex as
  they go (`generate.py`, `negative.py`), which lex with Stage 2 alone; full
  mode, `SAW_FIXPOINT_FULL=1`, compares those too, and is what the battery's
  `fixpoint` stage runs, so the periodic full battery on main (ST-45) covers
  them. The lane's summary line names the mode;
- the full grammar corpus runs when `GRAMMAR.md`, `LANGUAGE_SPEC.md` (whose
  headings `spec=` names), `compiler/tests/grammar/`, or what sawc's token
  dump and parser come from (`compiler/lex/`, `compiler/parse/`,
  `compiler/driver/`, `compiler/tools/build.py`, `compiler/seed/`) changes;
  otherwise each changed `.saw` file is checked against `corpus_expected.tsv`
  on its own, except the parser corpus's case files under
  `compiler/tests/parse/`, which the compiler tests' parse lane checks case by
  case;
- the corpus differential's regression gate (`corpusdiff.py gate`, see
  `compiler/tests/corpusdiff/README.md`) runs when what sawc is built from
  changes (each stage's `src/`, `compiler/driver/`, `compiler/seed/`,
  `compiler/tools/build.py`, `std/`, `runtime/`), or what it measures or judges
  by (`tests/corpus/`, the vector files under `tests/` the programs read,
  `examples/`, whose files the snapshot must be current with,
  `compiler/tests/corpusdiff/`, `compiler/tests/oracle.py` and the modules it
  imports). It measures the whole corpus and fails when any program's verdict
  moved from `corpus_diff.tsv`, an improvement included, so a patch that moves
  one records the move with `corpusdiff.py run --baseline` in the same patch;
- a change to the gate itself (`build.sh`, `tools/patch_gate.py`,
  `tools/suite_lock.sh`, `.sawtracker/`) runs everything, and so does a run
  whose changed paths are unknown.

It prints each part's decision with its reason. `--dry-run` prints the decision
and runs nothing, for a revision (`--changed-since REV`) or a patch file
(`--diff FILE`), which is how to see what a squashed patch will cost before
submitting it:

```bash
./build.sh test --dry-run --diff /tmp/patch.diff
```

`build.sh` holds the suite lock around everything the gate runs, through
`tools/suite_lock.sh`. When another run holds the lock, the gate prints who
holds it and since when, a heartbeat every five minutes while it waits, and the
total wait once it starts; its last line reports that wait apart from the test
time. From a worktree, point `SAW_PYTHON` at the main checkout's venv rather
than letting it bootstrap one.

A local run that wants the lock should let the server's gate go first, since a
patch waiting on a local run holds up its merge:

```bash
tools/suite_lock.sh acquire --yield-to-gate 'run.py --only units'
```

With `--yield-to-gate`, the acquire also waits while `sawtracker gate --project
SL --json` reports an SL gate run in progress or queued, and says which runs it
is waiting for. A queued entry held for changes requested, or superseded, does
not count, since it won't run as it stands. It asks again just after taking the
lock and gives the lock back if a gate run appeared in between. If the tracker
can't be reached or its report can't be read, the acquire says so and carries
on as a plain acquire.
The gate's own acquire in `build.sh` never yields.

A TERM, INT or HUP to the gate's process group ends `build.sh` with 128 plus
the signal's number, and it gives the lock back on the way out; the runners
end the programs they started in sessions of their own first
(`tools/child_groups.py`, which the `childgroups` battery stage holds them to).
A KILL can't be caught, so a gate killed that way leaves the lock held. Release
it with `tools/suite_lock.sh release` once `status` names a holder that is
gone.

### How many workers the gate uses

One setting sizes every pool the gate runs: `SAW_GATE_JOBS`, read through
`tools/gate_jobs.py`. By default it is three quarters of the machine's cores,
rounded down and never less than one (12 on a 16-core machine), and a larger
value is clamped to that ceiling, so the gate never keeps more than 75% of the
cores busy. `SAW_GATE_JOBS=1` runs everything serially. The ceiling counts
everything running at once, in every process: the outermost runner makes the
budget as tokens (lock files in a temporary directory), every process it
starts draws on the same tokens, and a pool takes a token for each worker
beyond its first, so parts running side by side share one budget instead of
each having its own.

```bash
SAW_GATE_JOBS=1 ./.venv/bin/python compiler/tests/run.py   # serially
SAW_GATE_JOBS=4 ./build.sh test --changed-since HEAD^      # at most four at once
```

`compiler/tests/run.py` runs each of its parts (`STEPS`) in a process of its
own, as many at once as the budget allows, starting those that need no `sawc`
while Stage 1 and Stage 2 build. The fixpoint lane replays the same parts
through its twin the same way, the twin running Stage 1 and Stage 2 at once
for a command that writes no files, and judges the twin's records in a fixed
order: by part, then by arguments. Both merge their output in a fixed order, so it is the same at every
worker count; `compiler/tests/parallel_order.py`, one of run.py's parts, checks
that a serial and a parallel run print the same, with an injected failure
reported in the same place. While the parts run, `run.py` writes
`run.py: started PART` and `run.py: finished PART (N s)` (or `failed`) to
standard error as each part starts and ends, in the order that happens, and the
fixpoint lane writes the same lines prefixed with `fixpoint: `; standard
output is unchanged.

## The Gate Battery

```bash
tools/battery.sh                     # everything
tools/battery.sh --quick             # skip the slow lanes (gmgate, linux)
tools/battery.sh compiler corpusdiff # named stages only
tools/battery.sh --list              # what the stages are
```

Everything a design brief runs before it is called landed, in one tracked
script. Every stage runs even after one fails — "the compiler tests are red"
and "they are red and so is the fixpoint" are different situations — and the
exit code is the number of failing stages.

`docverify` (`tools/docverify.py`) checks every fenced Saw block in README.md,
CLAUDE.md, LANGUAGE_SPEC.md and the saw-lang skill with `sawc coro --check`,
against what its fence claims:

- `saw` and `saw-body` must compile (`saw-body` is wrapped in a `main`).
- `saw-error` must be refused with the rule its first line pins
  (`// error-rule: RULE`, plus an optional `// error-contains: TEXT`), and with
  no missing-name or missing-import error beside it.
- `saw-pending SL-NNN` documents something sawc does not build yet. It must
  still fail, or not yet report its pinned diagnostic, and SL-NNN must be an
  open issue. Like an XFAIL, it breaks the lane once it passes.
- `saw-fragment` is exempt but counted: every run prints each source's exempt
  fraction.

The battery runs it as `tools/docverify.py --self-test`, which first runs
`tools/test_docverify.py`, the checks of those rules.

The interpreter comes from `$SAW_PYTHON`, else `./.venv/bin/python`, else
`python3`. A worktree has no venv of its own, so point it at the main
checkout's:

```bash
SAW_PYTHON=/path/to/main/.venv/bin/python tools/battery.sh
```

Adding a lane means editing `STAGES` in the script. That is the point of it
being tracked: it used to be an untracked scratch file each session rewrote
from prose, and a gate list nobody can diff is a gate list that quietly loses
an entry.

### The citations stage — the files nothing compiles

```bash
./.venv/bin/python tools/check_citations.py          # the lane
./.venv/bin/python tools/check_citations.py --list   # every citation, with its verdict
```

Every other lane in this battery compiles something. A file nothing compiles — a
tracker entry, an INDEX row, an XFAIL citation — can say anything at all and no
gate notices. This lane reads those files. Two checks, one blind spot (DF-248c).

#### Committed conflict markers

A line beginning `<<<<<<<` PAIRED with a later line beginning `>>>>>>>` in the
same file is a git conflict block somebody committed. Three of them were found
on `main` on Aug 24, one of which had been sitting in `designs/todo.md` since
Aug 22 — through every gate the tree has, because none of them read it.

The PAIR is the test. `=======` on its own is ordinary content (a markdown rule,
a banner) and the opener alone could be ASCII art, but the two together are the
exact shape git writes and nothing else. Every TRACKED text file is checked
(`git ls-files`, binaries skipped the way `git grep -I` skips them), with NO
exclusions — verified by grep when the lane landed. If a file ever legitimately
carries the shape, add its path to `CONFLICT_ALLOWED` in the tool with a comment
saying why; never widen it to a directory.

The fix is the tracker's own rule: resolve hunk by hunk in the editor, keeping
BOTH sides of an accumulator file (`todo.md`, `INDEX.md`, `SKILL.md`) unless
they are genuine duplicates, and never by taking one whole side.

#### Stale citations

The other direction of the XFAIL policy. An XFAIL marker PROMISES that a
finding is still open, and every gate reads that promise one way only: a pin
that starts passing is an XPASS and breaks the build. A pin whose finding was
CLOSED by a ruling that superseded the behaviour the pin asserts keeps FAILING,
so it stays a well-behaved known failure forever, while the ledger it belongs
to reports a red cell that is green.
`visibility_package_relative_import_fails_open.saw` sat that way for two days
after DF-232n closed.

The lane collects the first finding id of every `// XFAIL:` reason in the
tracked `.saw` corpus — a second id later in the same reason is prose, and
holding prose to the citation's standard is how a lint starts crying wolf — and
checks each against the tracker. An `SL-` id asks `.sawtracker/issues/`, the
server's own record. A `DF-` id asks the markdown tracker:

| Evidence | Reading |
|----------|---------|
| An entry in a `designs/done_*.md` file | CLOSED, full stop — the lead moves an entry there only once it is closed |
| A `designs/todo.md` entry struck through (`~~DF-xxx~~`) or opening `— CLOSED`/`FIXED`/`LANDED`/`RETIRED` | closed |
| ANY other `designs/todo.md` entry anchored on that DF | OPEN, and open WINS over every closure |
| No entry anchored on it anywhere | undecided — reported as info, not a failure |

That third row is the one that keeps the lane honest. A finding is often closed
in PART — DF-218w narrowed to one shape, DF-248b's window half landed and its
closure half did not — and the tracker spells the remainder as a RESIDUE entry.
Both keep a pinned XFAIL that is exactly right, so a citation is stale only when
nothing anchored on that DF is still open. A lint that cries wolf gets deleted.

An entry is a heading or a list item whose SUBJECT is the DF number; a wrapped
paragraph line that merely begins with a bolded cross-reference is not one.

Every recogniser in this lane — the entry anchors, the closure words, and the
conflict markers — is checked on EVERY invocation against real lines copied into
the tool, because a lint whose recognisers have quietly stopped recognising
anything reports a clean tree exactly the way a clean tree does, which is the
shape of gap this lane exists to close. The self-test earned its keep the day it
was written, catching `~~DF-218s remainder + DF-218w~~`: the strikethrough spans
two DFs there, so there is no `~~DF-218s~~` to match.

Fixing a stale row is the ledger's own rule, in whichever direction is true:
either the pin asserts a behaviour the closing ruling SUPERSEDED, in which case
it becomes the accept row under the behaviour's own name and the marker goes; or
the finding is not closed after all and the tracker entry is what needs
correcting.

### The toolchain stage

```bash
./.venv/bin/python tools/test_toolchain.py    # the lane
make toolchain
./.venv/bin/python tools/toolchain.py         # report what WOULD be resolved
./.venv/bin/python tools/toolchain.py v0-root # the v0 compiler's checkout
```

`tools/toolchain.py` is the one place anything locates a sawlang artifact — the
compiler, Blade, and the `imgformat`/`toml`/`semver` packages a consumer
compiles against. `sos_runner.py` computed none of those paths by the time it
left, which is what let it move to the sawos repository (238 unit 5) — where
the language is somewhere else — unchanged.

Resolution is four steps: what the operator named (`SAWC`, `BLADE`,
`SAWLANG_ROOT` — with this checkout as the default root, since it is one),
then `sawc` and `blade` on `$PATH`, then a fetch of the commit named in a
`sawlang.pin`, then a refusal naming all three. In this repository step 1
always answers (the checkout is its own root); the point of the lane is
that the other three still work when it does not — sawos is the consumer
that exercises them for real. A `SAWLANG_ROOT` at an older release resolves to
that tree's own `bin/sawc`, Stage 0 included (the v0.13.0 case).

`v0_root` is the second funnel: the checkout of v0.18.0, the last release that
holds Stage 0, which `bin/sawc0` forwards to and a snapshot's regeneration
runs. It is `SAWLANG_V0_ROOT` when that is set (refused unless its compiler
says 0.18.0), else the tag fetched and cached like a pin's commit.

Two things it checks that nothing else could. A `$PATH` compiler is verified
against the pin's version and a disagreement is a refusal NAMING BOTH — never a
silent build with the wrong compiler. And the step-4 refusal's text is asserted
word by word, because it is what an operator with no toolchain reads.

The lane fabricates its environment — a stand-in checkout, a stand-in `sawc` on
a stand-in `$PATH`, a pre-populated fetch cache — so no step depends on what
happens to be installed on the machine, and the fetch step is exercised without
touching the network.

### The compiler stage

Runs `compiler/tests/run.py`, the self-hosted compiler's tests (above). It is
where the compiler's unit programs are compiled and run; no other stage opens
them. `blade/tests`, `libs/*/tests` and `tests/freestanding` are frozen
sources that no stage runs (their READMEs give the v0.18.0 recipe).

The self-hosted compiler's code generation has its own timing report:
`compiler/tests/run/run_lane.py --bench` times the kernels in
`compiler/tests/run/bench/` under `sawc build -O2` against Stage 0, best of
five each. It gates nothing and no lane runs it; the run lane's README
describes the kernels.

## Ownership and Concurrency Gates Under Guard Malloc

```bash
make gmgate                          # or: ./.venv/bin/python tools/gmgate.py
./.venv/bin/python tools/gmgate.py --lane concurrency -v
./.venv/bin/python tools/gmgate.py -n 30 -v   # more runs, per-program detail
./.venv/bin/python tools/gmgate.py --list     # the lists and their coverage; builds nothing
```

A missing retain does not fail an ordinary test run. The surplus release lands
in a block libmalloc has freed but not unmapped, so the program prints the right
answers and exits 0; the damage surfaces later, at whatever unrelated allocation
trips over it. A deinit fires on the 1 -> 0 refcount edge and never again, so
neither a refcount assertion nor a deinit-print count can see a second release.

Guard Malloc (`/usr/lib/libgmalloc.dylib`) puts every allocation on its own page
and unmaps it on free, which turns a latent over-release into a fault at the
instruction that made it, on every run.

`tools/gmgate.py` builds its programs with sawc against the new std, through
the one build path the run lane, the census and corpusdiff share
(`compiler/tests/oracle.py`), and runs each under Guard Malloc. Two lanes, each
kept short because Guard Malloc costs a page per allocation:

- **`ownership`** (10 runs each) is about values: copies, retains, drops,
  refcounts, containers, `Data`'s copy-on-write.
- **`concurrency`** (5 runs each) is the same failure where the value lives in
  a heap-resident coroutine frame or crosses a task boundary: a frame hand-off,
  a capture, a task's teardown, a value moved into a task. Fewer repeats
  because these have a scheduler under them, so a repeat buys interleaving
  variety rather than the same trace.

Each lane is a list of categories, and each category names three kinds of
program: **twins** (the `tests/corpus/` twins of the programs the lane ran on
Stage 0), **stand-ins** (other programs sawc builds that police the same
shape, held while a twin is blocked) and **blocked** twins, which sawc refuses
today, each listed with its first refusal's rule and the unit that clears it.
A blocked twin is still built on every run, and fails the lane once sawc
builds it or refuses it by another rule, so the list never goes stale
silently. The tool's docstring states each lane's coverage, and the tool
checks that statement against the lists. A `tests/corpus/` program is judged by
its own directives, a `compiler/tests/run/` program by Stage 0's recorded run
of it; a fault, a signal or wrong output fails.

Before the lanes count, a self-test proves the harness sees what it exists to
see: `tools/gmgate_surplus_release.saw` is a refcount whose copy skips its
retain, so it releases one block twice. It must print `7` and exit 0 natively
and fault under Guard Malloc; if it stops faulting, the lane is blind and
fails.

**Add a program to a category in `tools/gmgate.py` whenever you write an
ownership oracle, and move a blocked twin into the category's twins once
sawc builds it.**

macOS only — Guard Malloc is a macOS facility, so on other platforms the tool
reports `SKIPPED` and exits 0 rather than failing.

## Best Practices

### 1. Always Add Expected Output

For success tests, add `EXPECT-OUTPUT:` to catch regressions:

```saw
// EXPECT: success
// EXPECT-OUTPUT:
// 42

func main() {
    print(42)
}
```

### 2. Be Specific with Error Messages

Use `EXPECT-ERROR-CONTAINS:` to validate the right error is reported:

```saw
// EXPECT: error
// EXPECT-ERROR-CONTAINS: undefined variable `x`
```

### 3. One Concept Per Test

Keep tests focused on a single feature:

```saw
// ✓ Good: tests one thing
// Test: optional chaining

// ✗ Bad: tests too many things
// Test: optionals, structs, enums, and error handling
```

### 4. Use Descriptive File Names

- `enums_simple.saw` - Basic enum declaration
- `enums_match.saw` - Pattern matching on enums
- `extension_mutable.saw` - Mutable methods

## Continuous Integration

The merge gate is sawtracker's per-patch run of `./build.sh test` (above). The
GitHub workflow (`.github/workflows/ci.yml`) runs the same entry point with
every part, on manual dispatch only. `./build.sh test` exits 0 when every part
passes and 1 when any fails.

## Debugging Failed Tests

When a corpus program's verdict moves, the gate names the program, its old
and new bucket and key, and the detail. To look closer:

1. Build it: `bin/sawc tests/corpus/extension_simple.saw -o .build/scratch/t`
2. Run it: `./.build/scratch/t`
3. Compare its output with its directives, and its verdict with
   `corpusdiff.py run extension_simple.saw`
4. Fix the code, or, for a move the patch makes on purpose, record the baseline

## Adding New Tests

1. Create a new `.saw` file in `tests/corpus/` (never in `examples/`, which is
   frozen)
2. Add test directives at the top
3. Run `corpusdiff.py run PATH` (relative to `tests/corpus/`) to see its
   verdict; a new program is native,
   judged by its directives alone
4. Record it with `corpusdiff.py run --baseline --jobs N`, and commit both

## Current Test Coverage

The baseline, `corpus_diff.tsv`, holds one row per program, and
`corpusdiff.py run --report FILE` writes the measurement's report
(`compiler/tests/corpusdiff/README.md`, "The report and the baseline"). The
corpus mixes:

- **Success tests**: programs that compile and run
- **Error tests**: programs that should fail compilation
- **Panic tests**: programs that compile but abort at runtime
- All tests validate output or error messages

The `XFAIL:` mechanism stays for the case it was built for (see
`designs/12-tech-debt-xfail-suite.md`): a brief that parks a known, reproducible
correctness gap marks it rather than deleting the test, and the ledger is
expected to be emptied again before the brief closes.

## Application-Level Testing with `blade test`

The corpus and the compiler's tests above test the **compiler itself**. A Saw
*application* (or library) tests its own logic a different way, using the Blade
package manager — no new language surface, just ordinary Saw programs (design
49). Blade is frozen in v0.18.0's language (blade/README.md), so `blade test`
drives v0.18.0's compiler, `sawc0`.

A test is a `.saw` file under the project's `tests/` directory with its own
`main()`. It **passes by exiting 0** and **fails by any nonzero exit** — most
naturally a failed `assert(...)` or a `panic(...)`, both of which abort the
process. `blade test`:

1. discovers every `tests/*.saw`,
2. compiles each with the project's sources (the same compiler invocation
   `blade build` uses),
3. runs the resulting binary,
4. reports per-test `ok` / `FAILED`, a summary line, and exits nonzero if any
   test failed (so CI fails the build).

```saw
// libs/toml/tests/toml_parsing.saw (abridged)
import toml.*

func main() {
    match TomlDoc.parse("[package]\nname = \"demo\"\n") {
        case Ok(doc) -> {
            guard let pkg = doc.index_of("package") else {
                panic("expected a [package] section")
            }
            assert((doc.section_at(pkg).get("name") ?? "").equals("demo"),
                   "name should be demo")

            // The named place reads the same section without the index.
            assert((doc.section("package")!.get("name") ?? "").equals("demo"),
                   "named place should read the same value")
            print("toml_parsing: ok")
        },
        case Err(e) -> panic("parse failed: {e.message}")
    }
}
```

`TomlSection` is `NoCopy`, so `section`/`section_at` are `borrows` accessors
that lend the section where it sits rather than handing one back. An index plus
`section_at` is what survives when several reads share one lookup, since a place
window is a single expression.

```bash
blade test
#    Testing myproject v0.1.0
# test toml_parsing ... ok
#
# test result: ok. 1 passed; 0 failed (1 total)
```

The compiler command defaults to `sawc` on `PATH`, and the `blade` shim sets it
to the `sawc0` beside it, since Blade drives Stage 0's command line; set the
`SAWC` environment variable to point `blade test` at another compiler. The
compiler's tests and an app's `blade test` suite do not share machinery or
semantics.

`blade test` never hides why a test could not compile or run (design 97). If no
compiler is available — `SAWC` unset **and** no `sawc` on `PATH` — it prints one
clear error telling you to set `SAWC`, and stops (rather than reporting every
test as a mysterious `FAILED`). When a test does not compile, the compiler's
error is shown; when a test aborts (a `panic` or failed `assert`), its stderr is
shown — a passing run stays quiet, a failing one explains itself.

`blade test` compiles each test with the same `--module-path` flags `blade
build` uses: the package's own, which maps its name to its `src/`, and one per
resolved dependency. So a test imports the package it tests by name, as
`import toml.*` above or `import blade.manifest`, and can `import` a dependency
too. It also reports per-test timing (`test NAME ... ok (Nms)`).

The compiled test binaries go in `.build/host/tests/`, under the same per-target
build directory as everything else Blade produces (see the README's Blade
section for the layout). Tests are compiled and then run, so they are always
built for the host. A test that writes scratch files of its own should create
its directory first, the way `blade/tests/dep_build.saw` does:

```saw
assert(Path(s: ".build/scratch").ensure_dir(), "scratch directory available")
```

`sawc0` does not create its output directory, so a test that skips this depends
on some earlier test having made the directory, and the suite starts failing
in whatever order the filesystem hands the files back.

### Library packages and the self-hosting bootstrap (design 64 B8)

The dependency machinery is extracted into real library packages, each with its
own `Saw.toml` and `blade test` suite, frozen with Blade (libs/README.md):

- `libs/toml` — the TOML reader (Blade depends on it by path).
- `libs/semver` — semantic versions / requirements (a `Comparable`/`Printable`
  dogfood).
- `libs/imgformat` — the sosimg image layout, written once and read by both
  sides: Blade's `emit = "sosimg"` target writes images and an SOS kernel loads
  them. Design 238 D-a moved it here from `sos/` so the language repo builds
  Blade with no OS tree present; its suite pins the wire constants and the
  header/segment rules a loader judges by.

Run a package's own tests by pointing Blade at its directory (`blade test`
from inside `libs/toml`, `libs/semver` or `libs/imgformat`), with
`SAWLANG_V0_ROOT` naming a v0.18.0 checkout so the `sawc0` that Blade drives
does not fetch one.

Blade is an application, so its `Saw.lock` is committed. The library packages'
are not: `blade build` writes no lock in a library, and each ships a one-line
`.gitignore` covering the `blade update` case.

Because Blade's own `Saw.toml` depends on `libs/toml`, every Blade build runs
the resolver, writes/uses `Saw.lock`, and passes `--module-path`. The bootstrap
loop that proves it end to end — Stage 0 builds Blade, that Blade builds Blade
through its own pipeline and runs Blade's suite, a second build reports "up to
date", `--force` rebuilds — is v0.18.0's `tools/blade_bootstrap.py`, run in a
v0.18.0 checkout.

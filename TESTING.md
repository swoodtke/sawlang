# Testing Guide for Saw Language

## Overview

The Saw language compiler includes an automated test runner that validates both successful compilation and error handling. Tests are defined directly in `.saw` example files using special comment directives.

## Running Tests

### Quick Start

The compiler needs `llvmlite`, which lives in the project virtualenv. The
Makefile calls bare `python3`, so `make test` needs that venv activated first;
invoking the runner through `./.venv/bin/python` never does.

```bash
# Run all tests (venv activated)
make test

# Or directly, with no activation needed:
./.venv/bin/python test_runner.py

# Verbose output (shows all passed tests)
make test-verbose
./.venv/bin/python test_runner.py -v

# Run only tests matching a pattern
make test-filter FILTER=enum
./.venv/bin/python test_runner.py -f enum

# Multiple patterns: repeat -f or comma-separate (a test runs if ANY matches)
./.venv/bin/python test_runner.py -f enum,arrays -f closures

# -v also shows the underlying failure detail for xfail tests
./.venv/bin/python test_runner.py -v -f some_xfail_test
```

### Test Results

- ✓ **Green checkmark**: Test passed
- ✗ **Red X**: Test failed
- x **Yellow x**: Known failure, marked `// XFAIL:` (does not break the build)
- ! **Red bang**: Marked `// XFAIL:` but passed — stale marker, breaks the build
- Summary shows the tally, e.g. `1341 passed`

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
| `// EXPECT: object` | Compile to an object file; no run (freestanding, `-c`) |
| `// EXPECT: docs` | Compile with `--emit-docs`; the JSON is the output checked |
| `// EXPECT: skip` | Skip the file entirely (library modules, not tests) |

The rest constrain what the run must show:

| Directive | Description |
|-----------|-------------|
| `// EXPECT-OUTPUT:` | Lines following are expected stdout (one line per `//`) |
| `// EXPECT-OUTPUT-CONTAINS: text` | Stdout must contain "text". Repeatable, and matched IN ORDER — each match starts where the previous one ended. One space after the colon is the separator and everything after it counts, LEADING WHITESPACE INCLUDED, which is what `EXPECT-OUTPUT:` cannot express (it strips every line, so indented output is unmatchable there) |
| `// EXPECT-ERROR-CONTAINS: text` | Error message must contain "text" |
| `// EXPECT-PANIC-CONTAINS: text` | Panic message must contain "text" |
| `// EXPECT-WARNING-CONTAINS: text` | A warning must contain "text" (warnings ride the SUCCESS path and never change the exit code, so they need their own directive) |
| `// EXPECT-NO-WARNINGS` | The compile must emit no warning at all |
| `// EXPECT-SYMBOL-UNDEFINED: sym` | `nm` must report `sym` as undefined in the object |
| `// EXPECT-OBJECT-MAX-BYTES: n` | The emitted object must be at most `n` bytes |
| `// COMPILE-FLAGS: ...` | Extra `sawc` flags for this test; `{TESTDIR}` expands to the file's directory |
| `// XFAIL: reason` | Known-broken test: failure is expected, does not break the build |

### Known Failures (XFAIL)

When a test captures a real bug you are not fixing yet, mark it `// XFAIL:` with
a reason rather than deleting it or using `// EXPECT: skip`:

```saw
// EXPECT: success
// EXPECT-OUTPUT: stdout: hello
// XFAIL: Command.output() returns empty stdout; capture is lost in std/process.saw

func main() { ... }
```

Keep the `EXPECT` directives describing the **correct** behavior. The test still
compiles and runs on every `make test`; it just reports as `xfail` (yellow `x`)
instead of failing the run.

The point of this over `skip` is the reverse signal: if the test starts passing,
it is reported as **XPASS** and *fails* the run, telling you the bug is fixed and
the marker should be removed. `skip` silently drops the file from discovery, so
a fix would go unnoticed and the coverage would stay lost.

| Outcome | Symbol | Breaks build? |
|---------|--------|---------------|
| Passed | green `✓` | no |
| Failed | red `✗` | yes |
| Expected failure (`xfail`) | yellow `x` | no |
| Unexpectedly passed (`xpass`) | red `!` | **yes** — remove the stale marker |

### Required Directives

All tests **must** have explicit directives:

1. **`// EXPECT: success`** or **`// EXPECT: error`** - Required for all tests
2. **`// EXPECT-OUTPUT:`** or **`// EXPECT-OUTPUT-CONTAINS:`** - Required for
   success tests (at least one output line, or one substring)
3. **`// EXPECT-ERROR-CONTAINS:`** - Required for error tests (at least one)

Tests without these directives will fail with a clear error message.

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
examples/
├── hello.saw              # Basic success tests
├── math.saw
├── structs.saw
├── ...
├── errors/                # Error test cases
│   ├── immutable.saw      # Assignment to let
│   ├── undefined_var.saw  # Undefined variable
│   ├── type_mismatch.saw  # Type errors
│   └── ...
└── conformance/           # One row per claimed safety guarantee (design 191)
    ├── INDEX.md           # The ledger — see below
    ├── M22_place_write_let_root.saw
    ├── ...
    └── modules/           # Helper modules, excluded from discovery
```

### The conformance suite and its INDEX

`examples/conformance/` holds the standing check that every safety guarantee
the language CLAIMS is a guarantee something actually asserts. It came out of
the Aug-8 audit, which probed 247 claimed guarantees in one pass and found nine
holes; the suite is that pass, run on every build.

```bash
./.venv/bin/python test_runner.py -f conformance/    # the subset alone (~9s)
```

**`examples/conformance/INDEX.md` is the convention that makes it a ledger
rather than a pile of tests.** Every row of the audit is listed there with the
file that covers it — a file in `conformance/` when the row needed one, an
existing `examples/` test when one already asserts the same rule at the same
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
   a marker is legal only as the pin of a filed DF, cited in its reason. The
   commit that fixes a conformance regression UPDATES the row — it never
   deletes it.

Per design 190's third process rule, a brief that touches a safety guarantee
adds or updates its conformance rows as its FIRST unit.

## The Gate Battery

```bash
tools/battery.sh                     # everything
tools/battery.sh --quick             # skip the slow lanes (irdet, gmgate, bootstrap, sos)
tools/battery.sh suite fuzz          # named stages only
tools/battery.sh --list              # what the stages are
```

Everything a design brief runs before it is called landed, in one tracked
script. Every stage runs even after one fails — "the suite is red" and "the
suite is red and so is irdet" are different situations — and the exit code is
the number of failing stages.

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

### The selfhostlex stage

The Aug-10 coverage sweep mapped which battery stage semantically checks
each test tree: `blade/tests` and `libs/*/tests` run inside `bootstrap`
(and ONLY there — `--quick` skips them), `sos/tests` inside `sos`, and
`selfhost/lexer/tests` ran NOWHERE — nine passing tests no stage
compiled. `selfhostlex` closes that: each `selfhost/lexer/tests/*.saw`
is compiled and run, exit 0 = pass, same contract as `blade test`.

### The forgetgate stage

Design 218 stage 4's exit criterion, mechanized. `__saw_forget(<place>)` clears
an optional field's drop flag without reading the payload, so it is correct only
when it is paired with exactly one prior consuming read — a two-statement
obligation DF-206f, DF-210f and DF-217h each got wrong. The Slot migration
replaced that pair with `take()` on every field it moved, and the fields it did
NOT move are the six deferred census families plus the two scrutinee-temp rows.

So the criterion is not "zero emissions" (that would mean zero deferrals) but
zero UNCITED ones, and `tools/test_forget_purge.py` checks three things: the
transform spells `__saw_forget` in exactly one place, `_forget_call`; every call
to it passes a family from `DEFERRED_FAMILIES`; and the funnel provably REFUSES
an unknown family, which the gate asserts by calling it with one. A new deferral
is a design decision and needs the gate file in the diff.

The same rule covers the M1/M3 ownership MARKS — `frame_place_read`, which tells
the transfer checkpoint ownership is already settled here, and
`frame_owning_read`, which asks codegen for a retain the checker never saw. Both
are the transform asserting an answer instead of letting the language give one,
both delete when the last emitter goes (218a section 6), and until then each
stamp site carries a `DEFERRED:` comment naming the families that keep it alive.
The consumer side cites nothing: it is the other half of the same mechanism.

This is what a gate buys over a comment sweep. Extending it turned up a ninth
stamp on the MIGRATED path — a `move o!` whose `!` sat above `self.o.take()`,
asserting past a rule (design 131: a payload read out of a call result is
already yours) that answers correctly on its own. It is deleted.

### The bench stage

`bench` compiles and runs `devtools/bench/warehouse/` (driver:
`devtools/bench/src/main.saw`, the third Saw-authored devtool). Two rules,
deliberately split: the benchmark's **checksums gate** — it is a
deterministic simulation and a changed checksum is a behavioral regression,
whatever the clock says — while its **timing only reports** (a min-of-5
line in the battery output, for trend-watching across runs; a slow machine
is not a failure). Battery numbers are contended by whatever else the run
does; quote headline numbers only from a quiet machine, per the bench
README. The Swift and Rust files beside the benchmark are manual reference
baselines and are never built by the battery.

## Ownership and Concurrency Gates Under Guard Malloc

```bash
make gmgate                          # or: ./.venv/bin/python tools/gmgate.py
./.venv/bin/python tools/gmgate.py --lane concurrency -v
./.venv/bin/python tools/gmgate.py -n 30 -v   # more runs, per-program detail
```

A missing retain does not fail an ordinary test run. The surplus release lands
in a block libmalloc has freed but not unmapped, so the program prints the right
answers and exits 0; the damage surfaces later, at whatever unrelated allocation
trips over it. That is how DF-151b stayed in a green tree from design 73
onward — and two of the tests that should have caught it were passing for the
wrong reason, because a deinit fires on the 1 -> 0 refcount edge and never
again, so neither a `strong_count` assertion nor a deinit-print count can see a
double release.

Guard Malloc (`/usr/lib/libgmalloc.dylib`) puts every allocation on its own page
and unmaps it on free, which turns a latent over-release into a fault at the
instruction that made it — 100% reproducible instead of 15-35% per run.

`tools/gmgate.py` runs two small curated lanes under it. Both are deliberately
short: Guard Malloc costs a page per allocation and is far too slow for the
whole suite, so each covers only the tests that are ownership ORACLES.

- **`ownership`** (10 runs each) is about VALUES — copies, retains, drops,
  refcounts, containers, `Data`'s copy-on-write.
- **`concurrency`** (5 runs each) is the same failure where the value lives in
  a heap-resident coroutine FRAME or crosses a task boundary: a frame handoff,
  a capture a task holds while its spawner runs on, a group teardown, a channel
  send. Design 190's audit found two confirmed silent use-after-frees in that
  surface and the suite saw neither. Fewer repeats because these have a
  scheduler under them — a repeat buys interleaving variety, not the same trace
  again.

The lane faults on what it is for, measured rather than assumed: a probe that
returns a pointer into heap storage a suspending frame released prints a
plausible byte and exits 0 natively, and takes SIGSEGV under this harness.

**Add a program to `OWNERSHIP_GATE` or `CONCURRENCY_GATE` in
`tools/gmgate.py` whenever you write such a test.**

macOS only — Guard Malloc is a macOS facility, so on other platforms the tool
reports `SKIPPED` and exits 0 rather than failing.

## The Corpus-Mutation Fuzzer

```bash
./.venv/bin/python tools/sawfuzz.py --quick        # ~1 minute, the battery mode
./.venv/bin/python tools/sawfuzz.py --quick 500    # explicit mutant count
./.venv/bin/python tools/sawfuzz.py --soak         # until you stop it
./.venv/bin/python tools/sawfuzz.py --seed 12345 --quick 200
./.venv/bin/python tools/sawfuzz.py --seed 1 --replay-index 91   # ONE mutant
./.venv/bin/python tools/sawfuzz.py --corpus-filter enum_raw     # narrow it
```

`tools/sawfuzz.py` takes a program out of `examples/`, applies one cheap
syntactic mutation, and compiles it. **One oracle: the compiler either succeeds
or exits with a clean diagnostic.** A Python traceback, an
`internal compiler error`, a crash by signal or a hang is a finding — whatever
the mutant looked like. Nonsense a user can type still deserves an error
message with a location, and design 190's census counted nine of one week's
findings wearing exactly that face.

Six mutations, each aimed at a class of path: token substitution out of the
language's own vocabulary (a keyword where a name belongs), literal rewrites
between the notations design 50 says are interchangeable, operator swaps inside
a family, delete-a-token (which is how parser RECOVERY gets exercised),
duplicate-a-line, swap-two-statements.

Mutation is the right shape here because the corpus is 1200+ programs that
already reach deep into the compiler. A one-token edit of a program that
reaches the coroutine transform still reaches the coroutine transform; a
generated program mostly does not get past the parser.

Every choice comes from `(seed, index)` and nothing else — no wall-clock, no
PID, no `os.urandom`, no set or dict iteration order, corpus order sorted — so
a finding replays. Subprocesses run in waves of `--jobs`, every wave reaped
before the next starts (DF-182f was a fork bomb; there is no path here that
spawns without counting).

### When it finds something

A finding is written to `.build/fuzz-findings/` as three files: the mutant
`.saw`, a delta-minimized `.min.saw`, and a `.txt` with the seed, the index,
the parent program, the mutation, the exact command and the compiler's output.
Findings are deduplicated by failure signature, so one bug hit thirty times
reports once. A mutant that fails is re-checked against its unmutated parent
first — if the parent fails the same way, the mutation found nothing.

Then it is an ordinary finding:

1. File it as a DF in `designs/todo.md`.
2. Pin the `.min.saw` in `examples/` under a name that says what BEHAVIOR it
   pins — never an `_xfail` suffix, since the marker is the transient part.
3. Mark it `// XFAIL:` citing the DF, with EXPECT directives stating the
   INTENDED behavior, so the XPASS flip validates the fix.
4. Add its signature to `tools/sawfuzz_known.txt` — the fuzzer's own XFAIL
   ledger. A listed signature is still reported, with its DF number, but does
   not fail the run. Without that, one filed-and-unfixed bug paints the battery
   red on every future commit, and a gate everyone has learned to ignore is
   worse than no gate.
5. In the landing that FIXES it: delete the XFAIL marker and the ledger entry
   together. A ledger entry that no longer fires is stale exactly as an XPASS
   marker is; `--ignore-known` re-reports everything, which is how you check.

## The Coroutine Differential Harness

```bash
./.venv/bin/python tools/corodiff.py --quick        # ~60 pairs, the battery mode
./.venv/bin/python tools/corodiff.py --all          # the whole cross (~40 min)
./.venv/bin/python tools/corodiff.py --list-axes    # the axis grammar
./.venv/bin/python tools/corodiff.py --filter place_write_set
./.venv/bin/python tools/corodiff.py --replay let_shadow_rebind__nocopy__before__susp_main
```

`tools/corodiff.py` (design 218 unit 0) generates a program twice with the SAME
value flow: the DRIVEN version suspends, the CONTROL version does not. **Adding
a suspension to a program is not supposed to change what it prints, what it
returns, or how many times anything is destroyed** — so a difference between
the twins is a coroutine-transform bug, and no model of what the program
*should* do is needed to see it.

That is the point of the lane. The DF-217 family are ownership bugs in
GENERATED code, which is exactly the code no reader reviews: the transform
lowers ownership-tracked locals into `UnsafePointer`-typed frame fields, where
ownership tracking stops by design, and exactly-once release is then a matter
of hand bookkeeping that the post-transform re-check structurally cannot
police. This harness is the net under that, and design 218 does not start
migrating the transform until it is a battery lane.

Four axes cross into the combo space:

- **20 BINDING constructs** — `let`, same-name shadow rebind, `if let`/`guard
  let`, both consuming match flavours and the BORROWING one (an arm binding its
  payload in place), tuple and nested-tuple destructuring, `_` discard, `??`
  RHS, three closure captures including one naming `self`, both place writes,
  `swap_out`, `Optional.take`.
- **5 copy-behavior AXIS VALUES** (`tools/corodiff.py` spells them `Tier(...)`),
  of which two WITNESS their own destruction: `nocopy`
  (`Res`, a hand-written deinit) and `tag` (a declared Copy struct over
  an `Arc<Res>` — a copy RETAINS, so the payload still dies exactly once, which
  is what makes a Copy over-release visible at all). `trivial`,
  `implicit` and `explicit` carry the parity checks only. The axis names
  predate design 219's rename: `implicit` is the `Copy` tier, and `explicit` a
  declared `ExplicitCopy` type.
- **4 SUSPEND PLACEMENTS** — before the binding, after it, between bind and
  use, and inside the initializer itself.
- **13 CONTEXTS** — a suspending `main`, a spawned task, a loop body, a closure,
  a nested block, a suspending METHOD, three cancellation shapes, a panicking
  task, an unjoined handle, a two-task group teardown, and `TaskGroup(threads:
  2)`.

### What the oracle checks, and where it stops

1. A traceback, an `internal compiler error`, a compile hang or a run hang is a
   finding on either twin, parity or no parity.
2. **COMPILE PARITY** — one twin refused where the other compiles. The driven
   twin being the refuser is a BOGUS-REFUSAL; both refusing identically is a
   deliberate rule and not a finding.
3. **RUN PARITY** — exit code, then stdout including the `NEW <id>` /
   `DEINIT <id>` witness lines. Same lines in a different ORDER is reported
   separately (`DEINIT-ORDER`): nothing was lost or duplicated and what moved
   is a destruction POINT, which is a resource-lifetime bug rather than a
   memory-safety one.
4. **WITNESS EXACTLY-ONCE**, per twin, independent of parity: for every witness
   id, `count(DEINIT id) == count(NEW id)`. More is a DOUBLE-FREE, fewer is a
   LEAK.

Check 4 is what carries the axes where parity CANNOT apply. A cancelled task
legitimately prints different lines from an uncancelled one, so the
cancellation contexts run the witness oracle and turn stdout parity off. A
panicking task ABORTS without unwinding, so nothing is released and a leak
means nothing there — that context keeps only the double-release half. An MT
group has no deterministic interleaving, so its stdout is compared as a
multiset. Each context declares which checks it can carry, in one place, which
is how a new axis gets added without either weakening the strong checks or
drowning the run in false reports.

Everything comes from the axes and `--seed`, and nothing reads a clock, a PID
or `os.urandom`. `--quick` takes a stratified sample — every value of every
axis covered at least once, then filled to size — so the battery runs the same
pairs on every machine. Compiles and runs go out in waves of `--jobs`, every
wave reaped before the next (DF-182f's rule).

### When it finds something

A finding is written to `.build/corodiff-findings/` as three files: both twins
and a `.txt` report with the combo, the oracle profile that judged it, what
differs, and the replay command. Findings are deduplicated by signature, so one
bug reached from thirty combos writes one report. A compiler complaint keys
itself (normalized, so the same refusal from another tier matches); a runtime
finding is keyed by construct, placement and the context's oracle class.

Then it is an ordinary finding — file the DF, pin the repro in `examples/`
under a behavior name, XFAIL it citing the DF, and add the signature to
`tools/corodiff_known.txt`. That file is this tool's XFAIL ledger and reads as
a matrix of known-broken cells: a listed signature is still reported, with its
DF number, but does not fail the run. Delete the entry in the landing that
fixes the bug; `--ignore-known` re-reports everything, which is how you check.

## The IR Contract Gate

```bash
make ircontract                      # or: ./.venv/bin/python tools/test_ir_contract.py
```

What the examples suite structurally cannot see, in miscompiles rather than
diagnostics.

The suite RUNS programs, so it never looks at one compiled with `-c` — nothing
spawns an object file. That blind spot hid DF-158e for as long as it existed: a
`-c` or `--freestanding` compile skipped the whole-program effect fixpoint, so
the coroutine transform never embedded a spawn root's nested suspending callees
and the call lowered as a direct blocking one. In a kernel the nested park then
ran inline, on the only stack there is. The harness compiles four coroutine
shapes both ways at `-O0` and requires the frame sets to be identical. `-O0`
because at the default pipeline the whole-program build inlines a frame's resume
method into its one caller and the symbol disappears, which says nothing about
whether the frame was built.

The suite does not CROSS-COMPILE either, and `word` (pointer-width) and `Int64`
are the same machine type on every host it runs on. That hid DF-158c: a family
of `__saw_rt_*` seams was declared at a hardcoded i64 where rt/ABI.md says
`word`, and the two clock seams at the platform word where the document says
`Int64` — the two wrong in opposite directions. An `@export`ed definition
unifies with the compiler's declaration of the same symbol and inherits its
type, so a runtime's correct `-> Int64` body emitted `define i32` on riscv32.
The harness reads the declared and defined seam types out of the IR at 64 and 32
bits and checks each against the signature parsed from rt/ABI.md — the same
parse `--runtime-provider` checks Saw signatures against, so the compiler's
declarations and a runtime's definitions are held to one document.

**Add a program to `EMBED_CORPUS` whenever a new coroutine embedding shape
lands.**

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

To integrate with CI/CD:

```bash
# In your CI script
make test || exit 1
```

The test runner exits with:
- **0** if all tests pass
- **1** if any test fails

## Debugging Failed Tests

When a test fails, the runner shows:

```
✗ extension_simple
  Output mismatch:
  Expected:
    7
  Got:
    8
```

To debug:

1. Compile manually:
   `./.venv/bin/python sawc/sawc.py examples/extension_simple.saw -o test_binary`
2. Run: `./test_binary`
3. Compare output with expected
4. Fix code or update test expectations

## Adding New Tests

1. Create a new `.saw` file in `examples/`
2. Add test directives at the top
3. Run `make test` to verify
4. Commit both the test and its metadata

## Current Test Coverage

Run `./.venv/bin/python test_runner.py` to see the current test count (it grows
as features land). The suite mixes:

- **Success tests**: Examples that compile and run
- **Error tests**: Examples that should fail compilation
- **Panic tests**: Examples that compile but abort at runtime
- All tests validate output or error messages

**Zero xfails is the bar**, and `examples/` currently holds none: the suite runs
fully green on every commit, with no red failures, no XPASS, and nothing yellow.

The `XFAIL:` mechanism stays for the case it was built for (see
`designs/12-tech-debt-xfail-suite.md`): a brief that parks a known, reproducible
correctness gap marks it rather than deleting the test, and the ledger is
expected to be emptied again before the brief closes. Fixing one flips it to
XPASS and breaks the build until its marker is removed, so a marker cannot
silently outlive the bug.

## Application-Level Testing with `blade test`

The `test_runner.py` harness above tests the **compiler itself**. A Saw
*application* (or library) tests its own logic a different way, using the Blade
package manager — no new language surface, just ordinary Saw programs (design
49).

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
import src.lib.*

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

The compiler command defaults to `sawc`; set the `SAWC` environment variable to
point `blade test` at a not-yet-installed compiler (e.g. an in-tree build). This
is entirely separate from `test_runner.py` — the compiler suite and an app's
`blade test` suite do not share machinery or semantics.

`blade test` never hides why a test could not compile or run (design 97). If no
compiler is available — `SAWC` unset **and** no `sawc` on `PATH` — it prints one
clear error telling you to set `SAWC`, and stops (rather than reporting every
test as a mysterious `FAILED`). When a test does not compile, the compiler's
error is shown; when a test aborts (a `panic` or failed `assert`), its stderr is
shown — a passing run stays quiet, a failing one explains itself.

`blade test` compiles each test with the project's resolved dependency
module-paths (the same flags `blade build` uses), so a test can `import` a
dependency. It also reports per-test timing (`test NAME ... ok (Nms)`).

The compiled test binaries go in `.build/host/tests/`, under the same per-target
build directory as everything else Blade produces (see the README's Blade
section for the layout). Tests are compiled and then run, so they are always
built for the host. A test that writes scratch files of its own should create
its directory first, the way `blade/tests/dep_build.saw` does:

```saw
assert(Path(s: ".build/scratch").ensure_dir(), "scratch directory available")
```

`sawc` does not create its output directory, so a test that skips this depends
on some earlier test having made the directory, and the suite starts failing
in whatever order the filesystem hands the files back.

### Library packages and the self-hosting bootstrap (design 64 B8)

The dependency machinery is extracted into real library packages, each with its
own `Saw.toml` and `blade test` suite:

- `libs/toml` — the TOML reader (Blade depends on it by path).
- `libs/semver` — semantic versions / requirements (a `Comparable`/`Printable`
  dogfood).

Run a package's own tests by pointing Blade at its directory
(`blade test` from inside `libs/toml` or `libs/semver`) — nothing but
`blade test` is needed once `sawc` is installed or `SAWC` is set. On a clean
in-tree checkout (no installed `sawc`) the bootstrap sets `SAWC` for you: the
loop runs both lib suites as a standard bar (design 97), so they are actually
validated on every `make blade-bootstrap` and cannot silently rot.

Blade is an application, so its `Saw.lock` is committed. The two library
packages are libraries, so theirs are not: `blade build` writes no lock in a
library, and each ships a one-line `.gitignore` covering the `blade update`
case. The bootstrap checks it, and a library that grows a `Saw.lock` fails the
loop.

Because Blade's own `Saw.toml` depends on `libs/toml`, **every Blade build runs
the resolver, writes/uses `Saw.lock`, and passes `--module-path`** — the dep
features cannot rot without breaking Blade's own build. The bootstrap loop
(`make blade-bootstrap`, or `python tools/blade_bootstrap.py`) proves it end to
end: the in-tree `sawc` builds Blade (stage0); that Blade builds Blade through
its own resolve/lock/module-path/incremental pipeline (stage1); the self-built
binary runs Blade's full suite; a second build reports "up to date"; `--force`
rebuilds (stage2); and the stage2 binary re-runs the suite.

Three of its stages are about where the output goes:

- the artifact is at `blade/.build/host/blade` with its build-hash beside it,
  and the package root holds no binary and no `.ll` file.
- a stale artifact left at the old in-place path is ignored rather than
  trusted. The stage removes the real artifact, drops a junk file where builds
  used to land, and requires a recompile that leaves the junk alone. Without
  the per-target artifact check, a matching build hash alone would report the
  stale file as up to date.
- one throwaway package is built for two target names (`host` and the explicit
  host triple) and must produce two artifacts, two build hashes, and an
  up-to-date second build for each. `blade clean --target` then removes one and
  leaves the other. Only the directory behavior is under test, so the machine
  does not need a second architecture it can link for.

## Test Runner Implementation

The test runner (`test_runner.py`) discovers every `.saw` file recursively,
reads each file's directives, and then works in two stages that overlap.

**The compile stage builds every test.** Build products land under this
invocation's own `.build/test_runner_<timestamp>_<pid>/` (design 220 D2),
named after the test's path relative to `examples/`, so
`examples/ffi/int_types.saw` becomes `<run dir>/ffi_int_types`. Each compile
writes to a unique temporary name and renames its products into place. Every
verdict that needs no running program settles here: `EXPECT: error`,
`EXPECT: object`, `EXPECT: docs`, and any test that failed to compile when it
should have succeeded.

On completion — pass or fail, since a red run still finished and is still fit
to publish — the run directory is flipped onto `.build/test_runner_last` by
an atomic symlink replace (never `ln -sfn`'s unlink-then-create, which has a
window with no symlink at all): a reader resolves the symlink once and holds
that path, so a run that republishes mid-read can never hand it a mix of two
generations' files. The newest three generations are kept (an in-flight
reader of the previous run, plus one more) and older ones pruned after each
successful publish — which is also how a run killed mid-compile gets cleaned
up: its directory was never added to the kept set, so the next successful run
sweeps it like any other superseded generation. `make clean` still removes
everything under `.build/`.

**The execution stage runs the binaries the compile stage produced** and checks
what they wrote, which covers `EXPECT: success` and `EXPECT: panic`. Each
binary runs as its own subprocess in its own process group under a 30-second
cap. On expiry the whole group is killed and the test is recorded as a failure,
so a test that hangs at runtime cannot wedge the run.

A binary does not pass from one stage to the other immediately. It waits five
seconds. On macOS/arm64 a binary exec'd microseconds after it was written can
die of SIGTRAP before `main` runs, while the kernel is still assessing the new
file, so the runner holds each binary back and lets the compiles that follow it
fill the wait. `--settle-lag SECS` changes that wait and `--settle-lag 0`
removes it.

Two further guards sit under the wait. The rename means the exec'd path always
holds a file the kernel has not judged before, and a child that dies by signal
having written nothing on either stream is re-run once. That retry is always
reported, both in the test's own line and in a `RE-RAN:` section of the
summary, because a retry nobody sees is a retry that can hide a real crash.

The stages overlap rather than running one after the other. Compiling
everything first and only then executing cost about a third of the suite's wall
clock: the first exec of a freshly written binary costs about 0.4s of kernel
assessment against 0.007s to run the same file again, and that assessment
barely parallelises. Underneath a compile stream that cost is hidden, because a
process parked in the kernel is not competing for a core. On its own it becomes
a second serial stretch. The same measurement is why the execution side runs
four times wider than the compile side.

Progress is two counters. `(n/N)` counts compiles and `[n/N]` counts verdicts;
they advance independently, since a binary's verdict lands a settle lag after
its compile while later compiles are still running.

See the `test_runner.py` source for the rest.

### The reuse manifest and hardlink carry-forward (design 220)

Every worker process in the persistent-worker pool (design 115) is spawned
under its own randomly drawn `PYTHONHASHSEED` (never `0`, which would disable
the randomization the whole scheme exists to keep observable), and a
SUCCESS/PANIC compile that reaches the execution stage also emits its
optimized LLVM IR (the same rendering `--emit-ir` alone would produce, not
the always-on unoptimized debug sidecar `_emit_object` writes for every other
caller of `compile_saw()`). Both are recorded, per file, in a plain
tab-separated `manifest.tsv` at the root of the published run directory: the
compiling worker's seed and the artifact's filename. A hash-order-dependent
suite failure is then a `PYTHONHASHSEED=<recorded seed>` replay of that one
worker.

On the NEXT run, a file's artifact is reused (hardlinked into the new run
directory, no recompile) instead of rebuilt when it is still FRESH: newer
than every file and directory under `sawc/` (a deletion bumps no surviving
file's mtime but does bump its parent directory's — that closes the hole a
plain "newest changed file" scan would miss), newer than the installed
llvmlite's own dist-info, newer than `test_runner.py` itself, and newer than
the example file's own mtime. That bound is computed ONCE per run, not once
per file. Touching one example invalidates exactly that file; touching
anything under `sawc/` invalidates the whole corpus in one step. Reuse is
scoped to SUCCESS/PANIC tests only — both are re-validated for real by the
execution stage every run regardless of how the binary arrived, which is
what makes trusting a carried-forward BINARY safe without also trusting a
cached VERDICT. A COMPILES/OBJECT/ERROR/DOCS test settles at compile time
with no such net, so those always compile fresh.

Two more kinds of test stay out of the manifest, both for the same underlying
reason — the manifest promises the optimized IR of a plain default-flag
compile, and only a test that IS one can keep that promise. A test carrying
`// COMPILE-FLAGS:` compiles a different configuration than the one `irdet`
reproduces (and an unmodeled flag falls back to a subprocess compile, whose
`.ll` is the always-on unoptimized debug sidecar, not the optimized artifact).
A test asserting something at COMPILE time — `// EXPECT-WARNING-CONTAINS:`,
`// EXPECT-NO-WARNINGS` — is judged on the compile's output, which a reused
binary does not have, so reusing it would silently skip the assertion. Together
they are 15 of 1190 eligible tests.

`devtools/irdet` (the IR-determinism harness — see the IR determinism
section in `CLAUDE.md`) reads this manifest through `test_runner_last`, so
running the suite right before `irdet --all` lets most of the corpus skip
one of its two compiles. Nothing about the manifest is trusted blindly: a
byte mismatch against the manifest's artifact triggers a three-way verify
(fresh recompiles at both seeds) that can only ever produce a red that names
itself — true nondeterminism, a violated invariant (a stale stamp, or an
in-process-vs-subprocess divergence), or a transient race — never a silent
pass. A missing or absent manifest (a clean checkout, a generation from
before this scheme, or `irdet` run with no prior suite run at all) makes
every file take the pre-220 compile-both path — reuse is an optimization
layered on top of the original check, never a precondition for it.

## Running Tests on a Second Machine

A spare machine can take a share of the suite. The share runs concurrently with
the local one, and the run prints one merged summary.

There is no SSH in this. The second machine runs one daemon, started by hand
under a sandbox profile, and the only thing that crosses the network is a job:
a snapshot of the tree plus a list of which tests to run. The daemon takes no
command from the client, and never executes the submitted tree in its own
process — each job runs in a child process tree, in a fresh directory that is
deleted when the job ends.

### Setting up the worker machine

The worker needs the same OS and architecture as the client (both arm64 macOS),
the Xcode command line tools, and a Python virtualenv with `llvmlite`. Its
checkout supplies only the daemon, the sandbox profile and that virtualenv;
every job runs the *client's* tree, which arrives with the job.

```bash
# 1. Get the repo onto the worker machine.
git clone <this repo> ~/saw-worker
cd ~/saw-worker

# 2. Build its virtualenv (the same one the compiler needs).
python3 -m venv .venv
./.venv/bin/pip install llvmlite

# 3. Create the shared secret. Copy the printed value to the CLIENT machine
#    at the same path, or export it there as SAW_WORKER_TOKEN.
./.venv/bin/python tools/test_worker.py --init-token

# 4. Start the daemon under the sandbox profile. Use the LAN address you want
#    it reachable on; 8710 is the default port.
sandbox-exec -D WORKER_ROOT="$PWD" -f tools/test_worker.sb \
    ./.venv/bin/python tools/test_worker.py --bind 0.0.0.0:8710
```

Step 4 prints what it bound and, on the next line, whether the sandbox took
effect:

```
saw test worker on 0.0.0.0:8710 (24 cores, protocol 1)
  jobs run under ./.venv/bin/python, in ./.worker-jobs (purged per job)
  sandbox: ACTIVE — this process and its job children are confined
```

`sandbox: NOT ACTIVE` means the `sandbox-exec` wrapper was left off and jobs
would run with the account's full privileges. The daemon prints the correct
launch line and keeps running; stop it and start it again properly. A dedicated
low-privilege account composes with the profile and is worth the ten minutes if
the machine has anything else on it.

The daemon runs in the foreground and logs to stdout. To keep a log file, write
it into the job root, which is the one directory the profile allows writes to:
`... --bind 0.0.0.0:8710 >> .worker-jobs/worker.log 2>&1`.

### What the sandbox allows

`tools/test_worker.sb` is short enough to read, and each allowance says which
part of the suite needs it. The three limits that carry the weight:

- **Writes** go to `<WORKER_ROOT>/.worker-jobs` and the per-user temporary
  area, and nowhere else in the account. The checkout the daemon runs from is
  read-only to the jobs it runs, so a job cannot modify the daemon, the profile
  or the virtualenv that is about to run it.
- **Outbound network** is pinned to this machine. The suite's `std.net` tests
  connect to listeners they opened themselves a moment earlier, which is
  loopback by construction; nothing else can reach the internet.
- **Reads** cover the system prefixes a toolchain lives in, the worker's own
  checkout, and `~/.config/saw-worker/` for the token the daemon reads at
  startup. The rest of the account's home directory is not readable. (Step 3
  above runs outside the sandbox, because creating the token means writing
  there and only reading it is allowed from inside.)

Subprocess execution is allowed, because that is how the suite works: the
runner spawns a compiler process per core, each compile spawns `clang` to link,
and every test is then executed as its own child.

After any edit to the profile, check that the OS still accepts it. This
resolves every operation and filter name against the running kernel:

```bash
./.venv/bin/python tools/test_worker.py --check-profile tools/test_worker.sb
```

### Using it from the client

Put the token where the client can find it (`~/.config/saw-worker/token`, or
`SAW_WORKER_TOKEN`), then:

```bash
# The suite, split between here and the worker
./.venv/bin/python test_runner.py --remote studio.local:8710

# IR determinism, the second-longest gate, split the same way. The harness
# itself is Saw (devtools/irdet/); this driver builds it and splits the corpus.
./.venv/bin/python tools/irdet_remote.py --all --remote studio.local:8710

# The whole battery on the worker: suite, lexdiff, astdiff, irdet --all
./.venv/bin/python tools/remote_battery.py --remote studio.local:8710
```

Which tests go where is decided by a hash of each test's path, weighted by the
two machines' core counts: a 10-core laptop paired with a 24-core Studio sends
the Studio about 70% of them. Assignment does not depend on discovery order or
on how the run is filtered, so a failing test lands on the same machine every
time and reproduces where it failed. Balance is what that trades away, and
across a suite this size the split lands within a few percent of the weights
anyway.

Compilation and execution both stay on the worker. Binaries never cross the
network in either direction.

The summary marks each failure with the machine that judged it:

```
FAILED TESTS:

  ✗ optional_chain_suspend [remote]
    Output mismatch:
    ...
```

### When the worker is not there

A gate that goes red because a machine on the other side of the house was
rebooting is worse than useless. So nothing about the worker can cost the run a
verdict: an unreachable host, a refused token, a worker already busy with
someone else's job, a connection that dies mid-shard, or a worker that stops
answering are all the same outcome. The tests it did not answer for run here,
and the summary says what happened:

```
REMOTE:
  worker studio.local:8710 is unreachable ([Errno 61] Connection refused) — every test ran here
```

The run's exit status is a verdict about the tree and nothing else.
`remote_battery.py` makes the same distinction in its exit status: `0` every
gate passed, `1` a gate failed, `2` the battery did not run at all — the last
of which is not a verdict about anything, and prints the local commands to run
instead.

Two waits bound a remote shard. The worker sends a heartbeat every 15 seconds
while a job runs, so silence for four of them means the worker is gone rather
than slow; and once the local share is finished, the worker gets a grace period
of five minutes (or twice the local share's wall clock, whichever is longer)
before this machine stops waiting and runs the rest itself.

### Limits

- One job at a time. A second client is refused rather than queued, and
  degrades to running its own tests.
- `tools/sos_runner.py` stays local: it boots a kernel under QEMU, which the
  worker is not required to have. `tools/blade_bootstrap.py` stays local too.
- The worker keeps the compiled Saw runtime (`.build/rt`) between jobs, keyed
  by a digest of `sawc/`, so a job only rebuilds it when the compiler changed.
  Nothing else survives a job.

### Self-test

```bash
./.venv/bin/python tools/remote_worker_selftest.py
```

Starts a real worker on loopback and exercises the whole path: the shipped
profile compiles against the running OS, sharding is deterministic and
core-weighted, a snapshot carries sources but no build products and refuses a
tar that tries to escape the job directory, `/health` accepts the right token
and refuses a wrong one, a shard round-trips and matches a local run verdict for
verdict, a worker killed mid-job leaves notes and a list of unanswered tests,
a second job is refused, and a battery submission starts its first gate.

One thing it cannot do is apply the sandbox profile: a process already inside a
seatbelt sandbox cannot apply a second one, so a run from inside a sandboxed
agent or CI job compiles the profile but does not run under it. On the worker
machine, the `sandbox: ACTIVE` line at startup is that check.

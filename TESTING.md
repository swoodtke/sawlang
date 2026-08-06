# Testing Guide for Saw Language

## Overview

The Saw language compiler includes an automated test runner that validates both successful compilation and error handling. Tests are defined directly in `.saw` example files using special comment directives.

## Running Tests

### Quick Start

```bash
# Run all tests
make test

# Or directly:
python3 test_runner.py

# Verbose output (shows all passed tests)
make test-verbose
python3 test_runner.py -v

# Run only tests matching a pattern
make test-filter FILTER=enum
python3 test_runner.py -f enum

# Multiple patterns: repeat -f or comma-separate (a test runs if ANY matches)
python3 test_runner.py -f enum,arrays -f closures

# -v also shows the underlying failure detail for xfail tests
python3 test_runner.py -v -f some_xfail_test
```

### Test Results

- ✓ **Green checkmark**: Test passed
- ✗ **Red X**: Test failed
- x **Yellow x**: Known failure, marked `// XFAIL:` (does not break the build)
- ! **Red bang**: Marked `// XFAIL:` but passed — stale marker, breaks the build
- Summary shows the tally, e.g. `196 passed, 1 xfailed`

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

| Directive | Description |
|-----------|-------------|
| `// EXPECT: success` | Test should compile and run successfully |
| `// EXPECT: error` | Test should fail during compilation |
| `// EXPECT: panic` | Test should compile but panic at runtime |
| `// EXPECT: skip` | Skip the file entirely (library modules, not tests) |
| `// EXPECT-OUTPUT:` | Lines following are expected stdout (one line per `//`) |
| `// EXPECT-ERROR-CONTAINS: text` | Error message must contain "text" |
| `// EXPECT-PANIC-CONTAINS: text` | Panic message must contain "text" |
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
2. **`// EXPECT-OUTPUT:`** - Required for success tests (at least one output line)
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
    func distance(self) -> Int {
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
└── errors/                # Error test cases
    ├── immutable.saw      # Assignment to let
    ├── undefined_var.saw  # Undefined variable
    ├── type_mismatch.saw  # Type errors
    └── ...
```

## Ownership Gate Under Guard Malloc

```bash
make gmgate                          # or: ./.venv/bin/python tools/gmgate.py
./.venv/bin/python tools/gmgate.py -n 30 -v   # more runs, per-program detail
```

A missing retain does not fail an ordinary test run. The surplus release lands
in a block libmalloc has freed but not unmapped, so the program prints the right
answers and exits 0; the damage surfaces later, at whatever unrelated allocation
trips over it. That is how DF-151b stayed in a green tree from design 73
onward — and two of the tests that should have caught it were passing for the
wrong reason, because a destructor fires on the 1 -> 0 refcount edge and never
again, so neither a `strong_count` assertion nor a deinit-print count can see a
double release.

Guard Malloc (`/usr/lib/libgmalloc.dylib`) puts every allocation on its own page
and unmaps it on free, which turns a latent over-release into a fault at the
instruction that made it — 100% reproducible instead of 15-35% per run.

`tools/gmgate.py` runs a small curated set of ownership oracles under it. The
lane is deliberately short: Guard Malloc costs a page per allocation and is far
too slow for the whole suite, and what it needs to cover is the tests that
assert something about copies, retains, drops or refcounts. **Add a program to
`GATE` in `tools/gmgate.py` whenever you write such a test.**

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

1. Compile manually: `./sawc/sawc.py examples/extension_simple.saw -o test_binary`
2. Run: `./test_binary`
3. Compare output with expected
4. Fix code or update test expectations

## Adding New Tests

1. Create a new `.saw` file in `examples/`
2. Add test directives at the top
3. Run `make test` to verify
4. Commit both the test and its metadata

## Current Test Coverage

Run `python3 test_runner.py` to see the current test count (it grows as
features land). The suite mixes:

- **Success tests**: Examples that compile and run
- **Error tests**: Examples that should fail compilation
- **Panic tests**: Examples that compile but abort at runtime
- All tests validate output or error messages

The suite is expected to run fully green (zero red failures, zero XPASS) on
every commit. Yellow `xfail` tests are expected and deliberate: they are the
project's **tech-debt ledger** (see `designs/12-tech-debt-xfail-suite.md`) —
each one encodes a known, reproducible correctness gap. Fixing one flips it
to XPASS and breaks the build until its marker is removed, so the ledger
can't silently rot.

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
// tests/toml_parsing.saw
import src.toml

func main() {
    match toml.TomlDoc.parse("[package]\nname = \"demo\"\n") {
        case Ok(doc) -> {
            guard let pkg = doc.get_section("package") else {
                panic("expected a [package] section")
            }
            assert((pkg.get("name") ?? "").equals("demo"), "name should be demo")
            print("toml_parsing: ok")
        },
        case Err(e) -> panic("parse failed: {e.message}")
    }
}
```

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

**The compile stage builds every test.** Build products land in `.build/`,
named after the test's path relative to `examples/`, so
`examples/ffi/int_types.saw` becomes `.build/ffi_int_types`. Each compile
writes to a unique temporary name and renames its products into place. Every
verdict that needs no running program settles here: `EXPECT: error`,
`EXPECT: object`, `EXPECT: docs`, and any test that failed to compile when it
should have succeeded.

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

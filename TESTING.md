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

## Test Runner Implementation

The test runner (`test_runner.py`):
- Discovers all `.saw` files recursively
- Parses test metadata from comments
- Compiles in isolated temporary directories
- Captures stdout/stderr
- Validates output or error messages
- Reports results with color formatting

See `test_runner.py` source code for implementation details.

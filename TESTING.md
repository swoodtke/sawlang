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
```

### Test Results

- ✓ **Green checkmark**: Test passed
- ✗ **Red X**: Test failed
- Summary shows total passed/failed count

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
| `// EXPECT-OUTPUT:` | Lines following are expected stdout (one line per `//`) |
| `// EXPECT-ERROR-CONTAINS: text` | Error message must contain "text" |

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

Run `python3 test_runner.py` to see current test count. As of the latest run:

- **36 total tests**
- **Success tests**: Examples that compile and run
- **Error tests**: Examples that should fail compilation
- All tests validate output or error messages

## Test Runner Implementation

The test runner (`test_runner.py`):
- Discovers all `.saw` files recursively
- Parses test metadata from comments
- Compiles in isolated temporary directories
- Captures stdout/stderr
- Validates output or error messages
- Reports results with color formatting

See `test_runner.py` source code for implementation details.

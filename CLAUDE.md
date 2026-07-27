# Saw Language Project

A modern systems programming language combining Rust's safety with Swift's elegance.

## Project Status

Currently in design phase. See `LANGUAGE_SPEC.md` for the full specification.

## Key Design Decisions

### Memory Management
- Copy by default (unlike Rust's move-by-default)
- Explicit `move` keyword for ownership transfer
- `@move` attribute for types that cannot be copied (unique resources)
- No garbage collector
- Deterministic destruction
- No reference types or lifetimes in type system
- Shared ownership via `Rc<T>`/`Arc<T>` wrapper types
- Synchronized access via `Mutex<T>`/`RwLock<T>`

### Mutability
- Immutable by default (`let`)
- Explicit `var` for mutable bindings
- `var` parameters allow mutation of caller's value
- `&` at call site indicates variable may be mutated: `foo(&x)`

### Type System
- Algebraic data types (enums with data)
- Traits for polymorphism
- Generics with trait bounds
- No null - `T?` optionals (postfix syntax like Swift)
- `Result<T, E>` for error handling
- Type extensions for adding methods to existing types
- `type` creates distinct types (can flow to underlying, but not vice versa)

### Syntax Philosophy
- Expression-oriented (everything returns a value)
- `guard let` for early exits (from Swift)
- String interpolation: `"Hello, {name}!"`
- Trailing closure syntax
- Pattern matching as core feature
- Dictionaries use `{ }` syntax: `{"key": value}`
- Swift-style `init` for struct initialization: `Point(x, y)`
- Named parameters in enums: `Move(x: Int, y: Int)`

### Key Differences from Rust
1. `var` instead of `let mut` (consistent use of `var` for mutability)
2. No reference types or lifetimes - use `var` params with `&` at call site
3. Copy by default, explicit `move` (inverse of Rust)
4. `T?` for optionals (postfix, Swift-style)
5. `guard let` for early unwrapping
6. Simpler closure syntax: `{ x in x * 2 }` or `{ $0 * 2 }`
7. Named tuple fields
8. `Type(...)` initialization instead of `Type::new(...)`
9. Type extensions like Swift
10. `type` definitions are distinct (alias→underlying allowed, underlying→alias requires initialization)
11. Python-style imports with full keywords (`import`, `module`, `public`)

### Module System
- Python-style imports (no namespace pollution)
- `import std.io` adds only `io` to namespace
- `import std.io.{Read, Write}` adds specific symbols
- Full keywords: `module`, `public`, `import` (not `mod`, `pub`, `use`)
- `package` and `parent` for relative imports (not `crate`, `super`)

### Concurrency
- Async/await
- Channels for message passing
- `Send`/`Sync` traits for thread safety

## Open Questions

- Final language name (Saw is placeholder)
- Semicolons: required, optional, or forbidden?
- Compilation target: LLVM, VM, or transpilation?

## File Structure

```
LANGUAGE_SPEC.md   # Full language specification
CLAUDE.md          # This file - project context
sawc/              # Saw compiler (Python + LLVM)
  sawc.py          # CLI entry point
  lexer.py         # Tokenizer
  parser.py        # Recursive descent parser
  ast_nodes.py     # AST node definitions
  codegen.py       # LLVM IR code generator
examples/          # Example Saw programs
  hello.saw        # Hello world
  math.saw         # Math operations and recursion
  variables.saw    # Variables and control flow
```

## Python Environment

Dependencies live in a virtualenv at `.venv/` (Python 3.14, llvmlite installed).
Always use it instead of system Python:

```bash
# Either activate it...
source .venv/bin/activate

# ...or invoke it directly
.venv/bin/python test_runner.py
.venv/bin/python sawc/sawc.py examples/hello.saw -o hello
```

Note: the Makefile calls bare `python3`, so `make test` requires the venv to be
activated first.

## Scratch Compilations

For throwaway experiments (probing a bug, checking codegen output), do NOT
write `.saw` files to `/tmp` or create them via shell heredocs/echo — those
commands can't be auto-approved. Instead:

1. Create the file with the Write tool under `.build/scratch/` (gitignored)
2. Compile: `./.venv/bin/python sawc/sawc.py .build/scratch/foo.saw -o .build/scratch/foo`
3. Run: `./.build/scratch/foo`

All three steps are covered by the project permissions allowlist in
`.claude/settings.json`, so they run without prompts.

## Command Hygiene (avoids permission prompts)

- Read files with the Read tool — to read several files, batch multiple Read
  calls in one message. Do not `cat` files via Bash loops.
- Never prefix commands with `cd <absolute path>; ...`. Your working directory
  is already the repo/worktree root and relative paths resolve there. Allowlist
  rules match from the start of the command string, so a `cd` prefix (or any
  compound wrapper) turns an auto-approved command into one that prompts.
- Run commands in the exact allowlisted forms shown in this file
  (`./.venv/bin/python ...`, `./.build/...`).

## Compiler Usage

```bash
# Install dependencies (into .venv)
.venv/bin/pip install llvmlite

# Compile a Saw program
./sawc/sawc.py examples/hello.saw -o hello

# Run the compiled executable
./hello

# Verbose output
./sawc/sawc.py examples/hello.saw -v

# Emit LLVM IR only
./sawc/sawc.py examples/hello.saw --emit-ir
```

## Testing

The compiler includes a comprehensive test runner:

```bash
# Run all tests
make test

# Run with verbose output
make test-verbose

# Run specific tests by pattern
make test-filter FILTER=enum
make test-filter FILTER=while_expr_conditional_found

# See TESTING.md for detailed documentation
```

**Test Coverage:** 181 tests including success cases and error validation

## Current Features

The compiler currently supports:

### Core Language
- Functions with parameters and return types
- Generic functions: `func identity<T>(x: T) -> T`
- Generic structs: `struct Box<T> { value: T }`
- Generic enums: `enum Maybe<T> { case Just(value: T), case Nothing }`
- Basic types: Int, Float, Bool, String
- Variables: `let` (immutable) and `var` (mutable)
- Arithmetic: `+`, `-`, `*`, `/`, `%` (modulo)
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `&&`, `||`, `not`
- Arrays: literals `[1, 2, 3]`, indexing `arr[i]`, type `[Int; 5]`
- Control flow: `if`/`else` expressions, `while` loops, `for` loops
- Loop control: `break`, `continue`
- Recursion
- `print(...)` built-in for debugging

### Type System
- Tuples: literals, indexing, multiple return values
- Structs: declarations, field access, initialization
- Field assignment: `obj.field = value`
- Optionals (`T?`): `None`, `!`, `??`, `?.`
- Optional binding: `if let`/`if var`, `guard let`/`guard var`
- Enums with associated values and `match` expressions
- Match exhaustiveness checking (must cover all variants or use `_` wildcard)
- Result<T, E> with auto-wrap returns
- `try`/`try?`/`try!` operators for error handling
- `try { } catch { }` blocks with implicit `error` variable
- Multiple error types with match in catch block

### Extensions & Methods
- `extension` blocks for adding methods to structs
- Generic extensions: `extension Box<T> { ... }`
- Immutable methods: `func method(self) -> Type`
- Mutable methods: `func method(var self)` (receives pointer)
- Custom `init` methods with overloading
- Method calls: `obj.method(args)`
- `self` keyword in method bodies

### Type System
- Type aliases: `type MyInt = Int` (creates distinct type)
  - Alias can flow to underlying: `func double(x: Int)` accepts `MyInt`
  - Underlying cannot flow to alias: `func process(x: MyInt)` rejects `Int`
  - Chained aliases work: `type A = Int`, `type B = A` → B flows to A flows to Int
- Associated types in traits: `type Item`
- Type assignments in extensions: `type Item = Int`

### Traits
- Trait definitions: `trait Name { func method(self) -> Type }`
- Trait conformance: `extension Type: Trait { ... }`
- Conformance checking (missing methods, signature mismatches)
- Multiple trait conformance: `extension Type: A, B { ... }`
- Trait bounds on generics: `func foo<T: Trait>(x: T)`
- Associated types with resolution: `type Item` → `type Item = Int`

## Example Code

### Basic Extension with Methods
```saw
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
    print(p.distance())  // 7
}
```

### Custom Init Methods
```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    init(magnitude: Int) -> Point {
        Point(x: magnitude, y: magnitude)
    }
}

func main() {
    let p1 = Point(x: 3, y: 4)     // Field init
    let p2 = Point(magnitude: 5)    // Custom init
    print(p2.x)  // 5
}
```

### Mutable Methods
```saw
struct Counter {
    value: Int
}

extension Counter {
    func increment(var self) {
        self.value = self.value + 1
    }

    func getValue(self) -> Int {
        self.value
    }
}

func main() {
    var counter = Counter(value: 0)
    counter.increment()
    print(counter.getValue())  // 1
}
```

### While Loops
```saw
func main() {
    // Conditional while loop
    var count = 0
    while count < 5 {
        print(count)
        count = count + 1
    }

    // Infinite loop with break
    var n = 0
    while {
        n = n + 1
        if n > 3 {
            break
        }
    }

    // Skip iterations with continue
    var i = 0
    while i < 10 {
        i = i + 1
        if i == 5 {
            continue  // Skip printing 5
        }
        print(i)
    }
}
```

### For Loops
```saw
func main() {
    // Iterate over a range
    for i in 0..5 {
        print(i)  // 0, 1, 2, 3, 4
    }

    // Break out of loop
    for i in 0..10 {
        if i == 3 {
            break
        }
        print(i)  // 0, 1, 2
    }

    // For loop as expression with break value
    let found = for i in 0..10 {
        if i > 5 {
            break i  // Returns Some(6)
        }
    }  // Returns None if loop completes normally

    if let value = found {
        print(value)  // 6
    }
}
```

### Generic Functions
```saw
// Generic identity function
func identity<T>(x: T) -> T {
    x
}

// Generic function with multiple type parameters
func first<A, B>(a: A, b: B) -> A {
    a
}

func main() {
    let x = identity<Int>(42)     // Returns 42
    let y = identity<Bool>(true)  // Returns true
    let z = first<Int, Bool>(10, false)  // Returns 10
    print(x)
}
```

### Traits
```saw
trait Describable {
    func describe(self) -> Int
}

struct Point {
    x: Int
    y: Int
}

extension Point: Describable {
    func describe(self) -> Int {
        self.x + self.y
    }
}

func main() {
    let p = Point(x: 3, y: 4)
    print(p.describe())  // 7
}
```

### Generic Enums
```saw
// Generic enum - similar to Option<T> in Rust
// Note: 'None' is a keyword in Saw, so we use Maybe instead of Option
enum Maybe<T> {
    case Just(value: T),
    case Nothing
}

func main() {
    // Create Maybe<Int> values
    let some_int = Maybe<Int>.Just(value: 42)
    let none_int = Maybe<Int>.Nothing

    // Match on Just variant
    match some_int {
        case Just(n) -> print(n),      // 42
        case Nothing -> print(0)
    }

    // Match on Nothing variant
    match none_int {
        case Just(n) -> print(n),
        case Nothing -> print(999)     // 999
    }

    // Works with any type
    let some_bool = Maybe<Bool>.Just(value: true)
    match some_bool {
        case Just(b) -> {
            if b {
                print(1)               // 1
            } else {
                print(0)
            }
        },
        case Nothing -> print(-1)
    }
}
```

### Logical Operators and Modulo
```saw
func main() {
    // Logical operators (short-circuit evaluation)
    let a = true && false   // false
    let b = true || false   // true
    let c = not true        // false

    // Combining with comparisons
    let x = 10
    let y = 20
    if x < y && y > 15 {
        print("both conditions true")
    }

    // Modulo operator
    print(10 % 3)           // 1
    print(17 % 5)           // 2

    // Even/odd check
    if x % 2 == 0 {
        print("x is even")
    }
}
```

### Arrays
```saw
func main() {
    // Array literal
    let arr = [1, 2, 3, 4, 5]

    // Array indexing
    print(arr[0])       // 1
    print(arr[2])       // 3

    // Dynamic indexing
    let i = 3
    print(arr[i])       // 4

    // Tuples also support [index] syntax
    let tuple = (10, 20, 30)
    print(tuple[0])     // 10 (same as tuple.0)
    print(tuple[1])     // 20

    // Array in loop
    var sum = 0
    for j in 0..5 {
        sum = sum + arr[j]
    }
    print(sum)          // 15
}
```

### While as Expression
```saw
func main() {
    // Infinite loop as expression - returns Int
    var counter = 0
    let result = while {
        counter = counter + 1
        if counter == 5 {
            break counter  // Exit and return value
        }
    }
    print(result)  // 5

    // Conditional loop as expression - returns Int?
    var i = 0
    let found = while i < 10 {
        if i == 3 {
            break i  // Return Some(3)
        }
        i = i + 1
    }  // Returns None if loop exits naturally

    // Unwrap with if let
    if let value = found {
        print(value)  // 3
    }

    // Or use nil coalescing
    let result = found ?? 0
    print(result)
}
```

### Result and Error Handling
```saw
struct ParseError {
    code: Int
}

// Functions returning Result get auto-wrap
func parseNumber(valid: Bool) -> Result<Int, ParseError> {
    if valid {
        return 42                    // Auto-wrapped to Ok
    }
    return ParseError(code: 1)       // Auto-wrapped to Err
}

func main() {
    // try! - force unwrap (panics on Err)
    let n = try! parseNumber(true)
    print(n)  // 42

    // try? - convert to Optional
    let maybe = try? parseNumber(false)
    if let value = maybe {
        print(value)
    } else {
        print(0)  // Prints 0 since parseNumber failed
    }

    // Inline catch with fallback
    let value = try parseNumber(false) catch { 99 }
    print(value)  // 99

    // Block try-catch
    try {
        let x = try parseNumber(false)
        print(x)
    } catch {
        print(error.code)  // 1
    }

    // Match on Result directly
    match parseNumber(true) {
        case Ok(n) -> print(n),
        case Err(e) -> print(e.code)
    }
}
```

### Multiple Error Types in Catch
```saw
struct ParseError { code: Int }
struct IoError { status: Int }

func parse(valid: Bool) -> Result<Int, ParseError> {
    if valid { return 42 }
    return ParseError(code: 1)
}

func read(exists: Bool) -> Result<Int, IoError> {
    if exists { return 100 }
    return IoError(status: 404)
}

func main() {
    // Multiple error types auto-wrapped in union
    try {
        let a = try parse(false)
        let b = try read(true)
        print(a + b)
    } catch {
        match error {
            case ParseError(e) -> print(e.code),
            case IoError(e) -> print(e.status)
        }
    }
}
```

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
- Interfaces for polymorphism
- Generics with interface bounds
- No null - `T?` optionals (postfix syntax like Swift)
- `Result<T, E>` for error handling
- Type extensions for adding methods to existing types
- `type` creates distinct types (not interchangeable aliases)

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
10. `type` definitions are distinct (not type aliases)
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
- `Send`/`Sync` interfaces for thread safety

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

## Compiler Usage

```bash
# Install dependencies
pip install llvmlite

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

**Test Coverage:** 47 tests including success cases and error validation

## Current Features

The compiler currently supports:

### Core Language
- Functions with parameters and return types
- Basic types: Int, Float, Bool, String
- Variables: `let` (immutable) and `var` (mutable)
- Arithmetic: `+`, `-`, `*`, `/`
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Control flow: `if`/`else` expressions, `while` loops
- Loop control: `break`, `continue`
- Recursion
- `print(...)` built-in for debugging

### Type System
- Tuples: literals, indexing, multiple return values
- Structs: declarations, field access, initialization
- Field assignment: `obj.field = value`
- Optionals (`T?`): `None`, `!`, `??`, `?.`
- Optional binding: `if let`/`if var`, `guard let`/`guard var`

### Extensions & Methods
- `extension` blocks for adding methods to structs
- Immutable methods: `func method(self) -> Type`
- Mutable methods: `func method(var self)` (receives pointer)
- Custom `init` methods with overloading
- Method calls: `obj.method(args)`
- `self` keyword in method bodies

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

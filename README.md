# Saw

A modern systems programming language combining the safety of Rust with the elegance of Swift.

## Why Saw?

Saw takes the best ideas from modern languages and combines them into a cohesive whole:

- **Safety by default** - No null pointers, memory safety without garbage collection
- **Elegant syntax** - Clean, readable code inspired by Swift
- **Zero-cost abstractions** - High-level constructs compile to efficient machine code
- **Predictable performance** - No hidden allocations, deterministic destruction

## Quick Example

```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    func magnitude(self) -> Int {
        self.x * self.x + self.y * self.y
    }

    func translate(var self, dx: Int, dy: Int) {
        self.x = self.x + dx
        self.y = self.y + dy
    }
}

func main() {
    var p = Point(x: 3, y: 4)
    print(p.magnitude())  // 25

    p.translate(1, 1)
    print(p.x)  // 4
}
```

## Key Features

### Immutable by Default

```saw
let x = 42          // Immutable
var count = 0       // Mutable
count = count + 1   // OK
x = 10              // Error!
```

### No Null - Optionals Instead

```saw
let maybe: Int? = None

// Safe unwrapping
if let value = maybe {
    print(value)
}

// Guard for early exit
guard let value = maybe else {
    return
}

// Default values
let result = maybe ?? 0

// Optional chaining
let len = user?.profile?.name?.len()
```

### Error Handling with Result

```saw
struct ParseError {
    message: String
}

func parse(input: String) -> Result<Int, ParseError> {
    if input.is_empty() {
        return ParseError(message: "empty input")  // Auto-wrapped to Err
    }
    return 42  // Auto-wrapped to Ok
}

func main() {
    // Force unwrap (panics on error)
    let n = try! parse("hello")

    // Convert to optional
    let maybe = try? parse("hello")

    // Inline catch with fallback
    let value = try parse("") catch { 0 }

    // Try-catch block
    try {
        let x = try parse("")
        print(x)
    } catch {
        print(error.message)
    }

    // Pattern match on Result
    match parse("hello") {
        case Ok(n) -> print(n),
        case Err(e) -> print(e.message)
    }
}
```

### Pattern Matching

```saw
enum Message {
    case Quit,
    case Move(x: Int, y: Int),
    case Write(text: String)
}

func handle(msg: Message) {
    match msg {
        case Quit -> exit(),
        case Move(x, y) -> move_to(x, y),
        case Write(text) -> print(text)
    }
}
```

### Traits for Polymorphism

```saw
trait Describable {
    func describe(self) -> String
}

extension Point: Describable {
    func describe(self) -> String {
        "Point at ({self.x}, {self.y})"
    }
}

func show<T: Describable>(item: T) {
    print(item.describe())
}
```

### Generics

```saw
struct Box<T> {
    value: T
}

func identity<T>(x: T) -> T {
    x
}

enum Maybe<T> {
    case Just(value: T),
    case Nothing
}
```

### Copy by Default, Explicit Move

Unlike Rust's move-by-default, Saw copies values by default:

```saw
let a = Point(x: 1, y: 2)
let b = a              // Copy - both valid
let c = move a         // Move - a is now invalid
```

### Type Extensions

Add methods to any type without modifying its definition:

```saw
extension Int {
    func is_even(self) -> Bool {
        self % 2 == 0
    }
}

print(42.is_even())  // true
```

### Module System

```saw
// mymodule.saw
public struct Config {
    name: String
}

public func load() -> Config {
    Config(name: "default")
}

// main.saw
import mymodule

func main() {
    let cfg = mymodule.load()
    print(cfg.name)
}
```

## Memory Management

Saw provides deterministic memory management without garbage collection:

- **Copy by default** for simple types
- **Explicit `move`** for ownership transfer
- **`Deinit` trait** for cleanup when values go out of scope
- **`NoCopy` trait** for move-only types (file handles, connections)
- **`CustomCopy` trait** for reference counting (`Rc<T>`, `Arc<T>`)
- **Reference types** (`&T`, `&var T`) for borrowing

```saw
// Mutable reference parameter
func increment(x: &var Int) {
    x = x + 1
}

var n = 5
increment(&n)  // n is now 6

// Immutable reference
func print_value(x: &Int) {
    print(x)
}
```

## Standard Library

Saw includes a growing standard library:

- **Vector<T>** - Dynamic arrays with `push`, `pop`, `get`, `len`
- **Map<K, V>** - Hash maps with `insert`, `get`, `contains`, `remove`
- **String** - String manipulation with `len`, `equals`, `contains`, `split`, `join`
- **StringBuilder** - Efficient string building
- **File** - File I/O with `open`, `create`, `read`, `write`
- **Directory** - Directory operations
- **Path** - Path manipulation
- **Data** - Raw byte arrays
- **Env** - Environment variables and command-line args
- **Process** - Process execution

## Getting Started

### Requirements

- Python 3.8+
- LLVM 14+ with `llvmlite` package
- Clang (for linking)

### Installation

```bash
# Clone the repository
git clone https://github.com/anthropics/sawlang.git
cd sawlang

# Install dependencies
pip install llvmlite

# Compile a program
./sawc/sawc.py examples/hello.saw

# Run it (output goes to .build/)
./.build/hello
```

### Compiler Options

```bash
./sawc/sawc.py <source.saw> [options]

Options:
  -o <file>    Output file name (default: .build/<source>)
  -c           Compile to object file only (no linking, no main required)
  -v           Verbose output
  --emit-ir    Output LLVM IR only
  --emit-ast   Dump typed AST for debugging
```

## Running Tests

```bash
# Run all tests (178 tests)
make test

# Verbose output
make test-verbose

# Filter by pattern
make test-filter FILTER=enum
```

## Current Status

Saw is in active development. The compiler currently supports:

### Core Language
- Functions with parameters and return types
- Generic functions and structs: `func identity<T>(x: T) -> T`
- Generic enums: `enum Maybe<T> { case Just(value: T), case Nothing }`
- All integer types: `Int`, `UInt`, `Int8`-`Int64`, `UInt8`-`UInt64`
- `Float`, `Bool`, `String` types
- Variables: `let` (immutable) and `var` (mutable)
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `&&`, `||`, `not`
- Compound assignment: `+=`, `-=`, `*=`, `/=`
- Recursion

### Type System
- Structs with field access and assignment
- Enums with associated values
- Pattern matching with exhaustiveness checking
- Optionals (`T?`): `None`, `!`, `??`, `?.`
- Optional binding: `if let`/`if var`, `guard let`/`guard var`
- Result<T, E> with auto-wrap returns
- `try`/`try?`/`try!` operators
- `try { } catch { }` blocks
- Tuples with indexing
- Arrays with literals and indexing
- Reference types: `&T`, `&var T`
- Type aliases: `type MyInt = Int`
- Type casting: `x as Int`

### Extensions & Methods
- `extension` blocks for adding methods
- Generic extensions: `extension Box<T> { ... }`
- Specialized extensions: `extension Vector<String> { ... }`
- Immutable methods: `func method(self)`
- Mutable methods: `func method(var self)`
- Static methods (no self parameter)
- Custom `init` methods with overloading

### Traits
- Trait definitions with methods and associated types
- Trait conformance: `extension Type: Trait { ... }`
- Multiple trait conformance
- Trait bounds on generics: `func foo<T: Trait>(x: T)`
- Built-in traits: `Deinit`, `NoCopy`, `CustomCopy`, `Iterator`

### Control Flow
- `if`/`else` expressions
- `while` loops (conditional and infinite)
- `for` loops with ranges and iterators
- `break` and `continue` with values
- Loops as expressions

### Modules
- `import` statements
- `module` declarations (inline and external)
- `public` visibility modifier
- Qualified access: `module.Type`

### FFI
- `extern "C"` blocks for C interop
- Pointer types: `UnsafePointer<T>`, `UnsafeConstPointer<T>`
- `sizeof<T>()` built-in

### Closures
- Closure expressions: `{ x in x * 2 }`
- Shorthand syntax: `{ $0 * 2 }`
- Trailing closure syntax
- Capturing variables from enclosing scope

See [LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) for the complete language specification.

## Blade Package Manager

Saw includes Blade, a package manager written in Saw itself:

```bash
# Build the package manager
./sawc/sawc.py blade/src/main.saw -o .build/blade

# Use it
./.build/blade help
./.build/blade new myproject
./.build/blade build
./.build/blade run
```

## Design Philosophy

### Key Differences from Rust

| Aspect | Rust | Saw |
|--------|------|-----|
| Default behavior | Move | Copy |
| Mutability | `let mut` | `var` |
| Optionals | `Option<T>` | `T?` (postfix) |
| References | `&T`, `&mut T` | `&T`, `&var T` |
| Initialization | `Type::new()` | `Type()` |
| Type extensions | Traits (impl blocks) | `extension` blocks |
| Modules | `mod`, `pub`, `use` | `module`, `public`, `import` |
| Error handling | `?` operator | `try`/`try?`/`try!` |

### Key Similarities to Swift

- `let`/`var` for immutability
- `guard let` for early exit
- `T?` optional syntax
- `extension` for adding methods
- `init` for custom initializers
- Trailing closure syntax
- String interpolation with `{}`

## Project Structure

```
sawc/                  # Compiler implementation
  sawc.py              # CLI entry point
  lexer.py             # Tokenizer
  parser/              # Recursive descent parser
  ast_nodes.py         # AST node definitions
  typechecker/         # Type checking passes
  codegen/             # LLVM IR code generator
  namespace.py         # Module/symbol resolution
  builtin.saw          # Built-in traits
  std/                 # Standard library (.saw files)
examples/              # Example programs
blade/                 # Blade package manager (written in Saw)
LANGUAGE_SPEC.md       # Full language specification
TESTING.md             # Test suite documentation
```

## Contributing

Saw is an experimental language. Contributions, feedback, and ideas are welcome!

## License

[MIT License](LICENSE)

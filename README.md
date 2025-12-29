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

## Memory Management

Saw provides deterministic memory management without garbage collection:

- **Copy by default** for simple types
- **Explicit `move`** for ownership transfer
- **`Deinit` trait** for cleanup when values go out of scope
- **`NoCopy` trait** for move-only types (file handles, connections)
- **`CustomCopy` trait** for reference counting (`Rc<T>`, `Arc<T>`)
- **`var` parameters** for mutable references with `&` at call site

```saw
// Mutable parameter - caller uses &
func increment(x: var Int) {
    x = x + 1
}

var n = 5
increment(&n)  // n is now 6
```

## Getting Started

### Requirements

- Python 3.8+
- LLVM 14+ with `llvmlite` package

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/saw.git
cd saw

# Install dependencies
pip install llvmlite

# Compile a program
./sawc/sawc.py examples/hello.saw -o hello

# Run it
./hello
```

### Compiler Options

```bash
./sawc/sawc.py <source.saw> [options]

Options:
  -o <file>    Output executable name
  -v           Verbose output
  --emit-ir    Output LLVM IR only
```

## Running Tests

```bash
# Run all tests
make test

# Verbose output
make test-verbose

# Filter by pattern
make test-filter FILTER=enum
```

## Current Status

Saw is in active development. The compiler currently supports:

- Functions and recursion
- Generics (functions, structs, enums)
- Structs with field access and assignment
- Enums with associated values and pattern matching
- Optionals (`T?`, `None`, `!`, `??`, `?.`)
- Optional binding (`if let`, `guard let`)
- Type extensions with methods
- Traits and conformance
- Control flow (`if`/`else`, `while`, `for`, `break`, `continue`)
- Arrays with indexing
- Tuples with named fields
- Logical operators (`&&`, `||`, `not`)
- Modulo operator (`%`)

See [LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) for the complete language specification.

## Design Philosophy

### Key Differences from Rust

| Aspect | Rust | Saw |
|--------|------|-----|
| Default behavior | Move | Copy |
| Mutability | `let mut` | `var` |
| Optionals | `Option<T>` | `T?` (postfix) |
| References | `&T`, `&mut T` | `var` params with `&` |
| Initialization | `Type::new()` | `Type()` |
| Type extensions | Traits (impl blocks) | `extension` blocks |
| Modules | `mod`, `pub`, `use` | `module`, `public`, `import` |

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
sawc/              # Compiler implementation
  sawc.py          # CLI entry point
  lexer.py         # Tokenizer
  parser.py        # Recursive descent parser
  ast_nodes.py     # AST node definitions
  codegen.py       # LLVM IR code generator
examples/          # Example programs
tests/             # Test suite
std/               # Standard library
LANGUAGE_SPEC.md   # Full language specification
```

## Contributing

Saw is an experimental language. Contributions, feedback, and ideas are welcome!

## License

[MIT License](LICENSE)

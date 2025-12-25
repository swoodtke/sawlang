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

## Compiler Usage

```bash
# Install dependencies
pip install llvmlite

# Compile a Saw program
python3 sawc/sawc.py examples/hello.saw -o hello

# Run the compiled executable
./hello

# Verbose output
python3 sawc/sawc.py examples/hello.saw -v

# Emit LLVM IR only
python3 sawc/sawc.py examples/hello.saw --emit-ir
```

## MVP Features

The current compiler supports:
- Functions with parameters and return types
- Basic types: Int, Float, Bool, String
- Variables: `let` (immutable) and `var` (mutable)
- Arithmetic: `+`, `-`, `*`, `/`
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Control flow: `if`/`else` expressions
- Recursion
- `print(...)` built-in for debugging

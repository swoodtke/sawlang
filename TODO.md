# Saw Language - Implementation Roadmap

## Current Status (MVP Complete + Core Types)
- [x] Basic functions with parameters and return types
- [x] Primitive types: Int, Float, Bool, String
- [x] Variables: `let` (immutable) and `var` (mutable)
- [x] Arithmetic operators: `+`, `-`, `*`, `/`
- [x] Comparison operators: `==`, `!=`, `<`, `>`, `<=`, `>=`
- [x] `if`/`else` expressions
- [x] Recursion
- [x] `print(...)` built-in
- [x] Tuples with literals, indexing, and multiple return values
- [x] Structs with field access and initialization

---

## Priority 1: Type Checking & Compiler Errors

### Type Checker
- [x] Build type inference engine
- [x] Check binary operator type compatibility
- [x] Check function argument types match parameters
- [x] Check return type matches declared type
- [x] Infer types for `let` without annotation
- [x] Track variable types in scope

### Semantic Analysis
- [x] Undefined variable errors
- [x] Undefined function errors
- [x] Duplicate variable declaration errors
- [x] Duplicate function declaration errors
- [x] Arity checking (wrong number of arguments)
- [x] Mutability checking (assigning to `let` variables)
- [ ] Use-before-initialization detection

### Error Reporting
- [x] Source location in all error messages (line:column)
- [x] Show the offending source line
- [x] Caret pointing to error location
- [x] Suggestion hints ("did you mean X?")
- [x] Multiple errors per compilation (don't stop at first)
- [x] Warning vs error distinction

### Error Recovery
- [ ] Parser recovery after syntax errors
- [x] Continue type checking after type errors
- [x] Collect all errors before reporting

---

## Priority 2: Core Type System

### Optionals (T?)
- [ ] Optional type syntax: `Int?`, `String?`
- [ ] `some(value)` and `none` literals
- [ ] Optional chaining: `user?.profile?.name`
- [ ] Nil coalescing: `value ?? default`
- [ ] Force unwrap: `value!`
- [ ] `if let` binding
- [ ] `guard let` early exit

### Structs
- [x] Struct declarations
- [x] Field access
- [ ] `extension` blocks for methods
- [x] Struct initialization: `Point(x: 10, y: 20)`
- [ ] `self` in methods
- [ ] `var self` for mutating methods

### Enums (Algebraic Data Types)
- [ ] Simple enums (no data)
- [ ] Enums with associated data: `Some(T)`, `None`
- [ ] Named parameters: `Move(x: Int, y: Int)`
- [ ] Pattern matching on enums

### Tuples
- [x] Tuple literals: `(1, 2, 3)`
- [ ] Named tuples: `(x: 10, y: 20)`
- [x] Tuple indexing: `point.0`, `point.1`
- [ ] Named field access: `point.x`
- [x] Multiple return values

### Type Definitions
- [ ] `type` keyword for distinct types
- [ ] Type wrapping: `type UserId = Int64`
- [ ] `.value` access to underlying value

### Generics (Basic)
- [ ] Generic functions: `fn identity<T>(x: T) -> T`
- [ ] Generic structs: `struct Box<T> { value: T }`
- [ ] Generic enums: `enum Option<T> { Some(T), None }`

---

## Priority 3: Core Control Flow

### Loops
- [ ] `while` loops
- [ ] `for item in collection` loops
- [ ] `for (index, item) in collection.enumerate()`
- [ ] `loop` with `break value`
- [ ] `continue` statement
- [ ] `break` statement

### Pattern Matching
- [ ] `match` expression
- [ ] Literal patterns: `0 => ...`
- [ ] Range patterns: `1..=9 => ...`
- [ ] Variable binding: `n => ...`
- [ ] Wildcard: `_ => ...`
- [ ] Guards: `n if n < 0 => ...`
- [ ] Exhaustiveness checking

### Additional Operators
- [ ] Logical: `&&`, `||`, `!`
- [ ] Modulo: `%`
- [ ] Compound assignment: `+=`, `-=`, `*=`, `/=`
- [ ] Bitwise: `&`, `|`, `^`, `~`, `<<`, `>>`
- [ ] Range: `..`, `..=`

---

## Priority 4: Data Structures & Collections

### Arrays
- [ ] Fixed-size arrays: `[Int; 5]`
- [ ] Array literals: `[1, 2, 3, 4, 5]`
- [ ] Indexing: `arr[0]`
- [ ] Length: `arr.len()`
- [ ] Bounds checking

### Vectors
- [ ] `Vec<T>` dynamic arrays
- [ ] `push`, `pop`, `len`
- [ ] Indexing and iteration
- [ ] Capacity management

### Dictionaries
- [ ] `Map<K, V>` type
- [ ] Literal syntax: `{"key": value}`
- [ ] `get`, `insert`, `remove`
- [ ] Iteration over keys/values

### Sets
- [ ] `Set<T>` type
- [ ] Literal syntax: `{1, 2, 3}`
- [ ] `insert`, `remove`, `contains`

---

## Priority 5: Functions & Closures

### Function Features
- [ ] Default parameter values
- [ ] `var` parameters with `&` at call site
- [x] Multiple return via tuples

### Closures
- [ ] Closure syntax: `{ x in x * 2 }`
- [ ] Shorthand: `{ $0 * 2 }`
- [ ] Capturing variables
- [ ] Trailing closure syntax
- [ ] `fn` types: `fn(Int) -> Int`

---

## Priority 6: Traits & Polymorphism

### Traits
- [ ] Trait declarations
- [ ] Default method implementations
- [ ] `impl Trait for Type`
- [ ] Trait bounds: `<T: Display>`
- [ ] Multiple bounds: `<T: Display + Debug>`
- [ ] Associated types

### Built-in Traits
- [ ] `Copy` - implicit copy
- [ ] `Clone` - explicit clone
- [ ] `Display` - string representation
- [ ] `Debug` - debug output
- [ ] `Eq`, `PartialEq` - equality
- [ ] `Ord`, `PartialOrd` - ordering
- [ ] `Iterator` - iteration protocol

### Type Extensions
- [ ] `extension Type { }` syntax
- [ ] Adding methods to existing types
- [ ] Computed properties
- [ ] Conditional extensions with `where`

---

## Priority 7: Memory Management

### Move Semantics
- [ ] `move` keyword for explicit ownership transfer
- [ ] `@move` attribute for move-only types

### Shared Ownership
- [ ] `Box<T>` - heap allocation
- [ ] `Rc<T>` - reference counting
- [ ] `Arc<T>` - atomic reference counting

### Synchronization
- [ ] `Mutex<T>`
- [ ] `RwLock<T>`
- [ ] Lock guards

---

## Priority 8: Error Handling

### Result Type
- [ ] `Result<T, E>` enum
- [ ] `Ok(value)` and `Err(error)`
- [ ] `?` propagation operator
- [ ] `.map()`, `.and_then()` combinators

### Panics
- [ ] `panic(message)` function
- [ ] `assert(condition, message)`
- [ ] `debug_assert` (debug builds only)

---

## Priority 9: Module System

### Modules
- [ ] `module` declarations
- [ ] `public` visibility
- [ ] `public(package)`, `public(parent)`

### Imports
- [ ] `import std.io` - module import
- [ ] `import std.io.{Read, Write}` - selective
- [ ] `import std.io as fileio` - aliasing
- [ ] `import package.module` - relative imports

### Package Structure
- [ ] `Saw.toml` manifest
- [ ] `src/lib.saw`, `src/main.saw`
- [ ] Submodule directories

---

## Deferred: Concurrency

- [ ] `async fn` declarations
- [ ] `.await` syntax
- [ ] `spawn` for threads
- [ ] Channels: `channel.create<T>()`
- [ ] `Send` and `Sync` traits
- [ ] `select` for async racing

---

## Deferred: Metaprogramming

- [ ] Const generics: `Array<T, const N: Int>`
- [ ] `const fn` compile-time functions
- [ ] Declarative macros
- [ ] Derive macros: `#[derive(Debug, Clone)]`
- [ ] Compile-time reflection

---

## Deferred: FFI & Unsafe

- [ ] `extern "C"` function declarations
- [ ] `#[no_mangle]` attribute
- [ ] `unsafe` blocks
- [ ] Raw pointers: `*T`, `*var T`
- [ ] `#[repr(C)]` for C-compatible layout

---

## Compiler Improvements

### Error Handling
- [x] Better error messages with source locations
- [ ] Error recovery in parser
- [x] Type error messages

### Optimizations
- [ ] Basic optimizations via LLVM
- [ ] Dead code elimination
- [ ] Inlining hints

### Tooling
- [ ] REPL for interactive testing
- [ ] Language server (LSP)
- [ ] Formatter
- [ ] Package manager

---

## Notes

- **Type checking is Priority 1** because a compiler without proper errors is frustrating to use
- Features are ordered by dependency (later features often depend on earlier ones)
- Type system comes before collections because structs/enums are needed to build them
- Control flow is essential for writing practical programs
- Traits enable the standard library design (`Copy`, `Clone`, `Iterator`, etc.)
- Concurrency and metaprogramming can wait until the core language is solid

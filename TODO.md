# Saw Language - Implementation Roadmap

## Current Status

**Compiler Stats:** ~17,000 lines of Python across modular packages
**Test Coverage:** 171 tests

---

**Completed Features:**
- [x] Basic functions with parameters and return types
- [x] Primitive types: Int, Float, Bool, String
- [x] Integer types: Int8, Int16, Int32, Int64, UInt, UInt8, UInt16, UInt32, UInt64
- [x] Type casting with `as` keyword
- [x] Variables: `let` (immutable) and `var` (mutable)
- [x] Arithmetic operators: `+`, `-`, `*`, `/`, `%`
- [x] Comparison operators: `==`, `!=`, `<`, `>`, `<=`, `>=`
- [x] Logical operators: `&&`, `||`, `not`
- [x] Compound assignment: `+=`, `-=`, `*=`, `/=`, `%=`
- [x] `if`/`else` expressions, `else if` chains
- [x] Recursion
- [x] `print(...)` built-in
- [x] String interpolation: `"Hello, {name}!"`
- [x] Tuples with literals, indexing, and multiple return values
- [x] Arrays with literals `[1, 2, 3]` and indexing `arr[i]`
- [x] Structs with field access and initialization
- [x] Optionals with `None`, `!`, `??`, `?.`
- [x] Optional binding: `if let`/`if var`, `guard let`/`guard var`
- [x] Panic on force-unwrap (`!`) of `None` value
- [x] Enums with associated data and pattern matching
- [x] Generic enums: `enum Maybe<T> { case Just(value: T), case Nothing }`
- [x] Match exhaustiveness checking and wildcard `case _ ->`
- [x] Struct extensions with methods and custom init
- [x] Mutable methods (`var self`)
- [x] Static methods (no self parameter)
- [x] Reference types: `&T` (immutable), `&var T` (mutable)
- [x] `&` at call site for reference parameters
- [x] While loops with `break` and `continue`
- [x] For loops with ranges (`for i in 0..10`) and custom iterators
- [x] Generic functions and structs with monomorphization
- [x] Traits with conformance checking
- [x] Trait bounds on generics (`<T: Iterator>`)
- [x] Associated types in traits
- [x] Distinct type definitions (`type UserId = Int`)
- [x] Closures: `{ x in x * 2 }` and `{ $0 * 2 }`
- [x] Function types: `(Int) -> Int`
- [x] Trailing closure syntax: `arr.map { $0 * 2 }`
- [x] Closure variable capture (copy semantics)
- [x] Resource management: `Deinit`, `CustomCopy`, `NoCopy` traits
- [x] Move semantics: `move` keyword for ownership transfer
- [x] Automatic scope-based cleanup with containment rules
- [x] Result<T, E> with auto-wrap returns
- [x] `try`/`try?`/`try!` operators for error handling
- [x] `try { } catch { }` blocks with implicit `error` variable
- [x] Multiple error types with match in catch block
- [x] Module system: `import`, `module`, `public`, `export`
- [x] Visibility: `public`, `public(package)`, `public(parent)`
- [x] Generic extension specialization

**Standard Library:**
- [x] Vector<T> - dynamic arrays with push, pop, len, get
- [x] Map<K, V> - hash map with get, insert, remove
- [x] StringBuilder - efficient string building
- [x] String methods - split, join, and more
- [x] Data - byte buffer type
- [x] File - file operations (create, open, read, write, exists, remove)
- [x] Directory - directory operations
- [x] Path - type-safe file path handling
- [x] Env - environment variable access
- [x] Process - process-related operations

---

## Priority 0: Code Quality & Technical Debt

### Known Issues in Code (TODOs)
- [ ] `typechecker/statements.py` - Validate guard else branch contains early exit (return/break/continue)

### Runtime Safety
- [x] Panic on force-unwrap (`!`) of `None` value
- [ ] Panic on out-of-bounds array/tuple access
- [ ] Better runtime error messages with source locations

### Code Refactoring
- [x] Refactored typechecker into modular package with mixin architecture
- [x] Refactored parser into modular package with mixin architecture
- [x] Refactored codegen into modular package with mixin architecture
- [ ] Add docstrings to complex type checking methods

### String Handling
- [ ] Support additional escape sequences: `\r`, `\0`, `\xNN`
- [ ] Unicode escapes: `\u{NNNN}`

---

## Priority 0.5: Testing Infrastructure

### Automated Testing ✅ COMPLETE
- [x] Create test runner script for all examples
- [x] Add expected output assertions for each example
- [x] Verify error test cases produce correct error messages
- [x] Parallelized test runner for ~6x speedup

### Unit Tests (deferred - integration tests sufficient)
- [ ] Add unit tests for lexer
- [ ] Add unit tests for parser
- [ ] Add unit tests for type checker

### CI/CD
- [ ] GitHub Actions workflow for automated testing
- [ ] Test on multiple Python versions (3.9+)
- [ ] Test LLVM IR generation without full compilation

---

## Priority 1: Type Checking & Compiler Errors

### Type Checker ✅ COMPLETE
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

### Error Reporting ✅ MOSTLY COMPLETE
- [x] Source location in all error messages (line:column)
- [x] Show the offending source line
- [x] Caret pointing to error location
- [x] Suggestion hints ("did you mean X?")
- [x] Multiple errors per compilation (don't stop at first)
- [x] Warning vs error distinction

### Error Recovery
- [ ] Parser recovery after syntax errors (currently stops on first error)
- [x] Continue type checking after type errors
- [x] Collect all errors before reporting

---

## Priority 2: Core Type System

### Optionals (T?) ✅ COMPLETE
- [x] Optional type syntax: `Int?`, `String?`
- [x] `None` literal (Swift-style with implicit wrapping)
- [x] Optional chaining: `user?.profile?.name`
- [x] Nil coalescing: `value ?? default`
- [x] Force unwrap: `value!`
- [x] `if let`/`if var` binding (var creates mutable reference)
- [x] `guard let`/`guard var` early exit

### Structs ✅ COMPLETE
- [x] Struct declarations
- [x] Field access
- [x] Struct initialization: `Point(x: 10, y: 20)`
- [x] Field assignment: `obj.field = value`
- [x] `extension` blocks for methods
- [x] `self` in methods
- [x] `var self` for mutating methods
- [x] Custom `init` methods with overloading
- [x] Static methods (no self parameter)
- [ ] Built-in type extensions (Int, String, Bool, etc.)
- [ ] Method overloading (beyond init)

### Enums (Algebraic Data Types) ✅ COMPLETE
- [x] Simple enums (no data)
- [x] Enums with associated data: `Some(T)`, `None`
- [x] Named parameters: `Move(x: Int, y: Int)`
- [x] Pattern matching on enums with `match` expressions
- [x] Match bindings to extract associated values
- [x] Enum equality operators (`==` and `!=`)
- [x] Exhaustiveness checking for match expressions
- [x] Wildcard pattern `case _ ->` for default cases
- [ ] Deep equality comparison (compare payloads, not just variant tags)

### Tuples
- [x] Tuple literals: `(1, 2, 3)`
- [ ] Named tuples: `(x: 10, y: 20)`
- [x] Tuple indexing: `point.0`, `point.1`
- [ ] Named field access: `point.x`
- [x] Multiple return values

### Type Definitions
- [x] `type` keyword for distinct types
- [x] Type wrapping: `type UserId = Int`
- [ ] `.value` access to underlying value

### Generics ✅ COMPLETE
- [x] Generic functions: `func identity<T>(x: T) -> T`
- [x] Generic structs: `struct Box<T> { value: T }`
- [x] Trait bounds: `<T: Iterator>`
- [x] Multiple bounds: `<T: A + B>`
- [x] Associated types in traits
- [x] Generic enums: `enum Maybe<T> { case Just(value: T), case Nothing }`
- [x] Generic extension specialization

---

## Priority 3: Core Control Flow ✅ COMPLETE

### Loops
- [x] `while` loops (with optional condition for infinite loops)
- [x] `break` statement (with optional value)
- [x] `continue` statement
- [x] While loops as expressions (conditional → `T?`, infinite → `T`)
- [x] `for i in start..end` range loops
- [x] `for item in iterator` custom iterator loops
- [x] For loops as expressions with `break value` returning `T?`
- [ ] `for (index, item) in collection.enumerate()`
- [ ] `..=` inclusive range syntax

### Pattern Matching
- [x] `match` expression on enums
- [x] Variable binding in enum patterns: `case Success(n) -> ...`
- [x] Wildcard pattern: `case _ -> ...` (default case)
- [x] Exhaustiveness checking (error on missing enum variants)
- [ ] Literal patterns: `case 0 -> ...`
- [ ] Range patterns: `case 1..=9 -> ...`
- [ ] Guards: `case n if n < 0 -> ...`
- [ ] Match on primitive types (Int, Bool, String)
- [ ] Match on tuples with destructuring

### Additional Operators ✅ MOSTLY COMPLETE
- [x] Logical AND/OR: `&&`, `||`
- [x] Logical NOT: `not` keyword (note: `!` is force-unwrap)
- [x] Modulo: `%`
- [x] Compound assignment: `+=`, `-=`, `*=`, `/=`, `%=`
- [ ] Bitwise: `&`, `|`, `^`, `~`, `<<`, `>>`
- [x] Range: `..` (exclusive end)
- [ ] Inclusive range: `..=`

---

## Priority 4: Data Structures & Collections ✅ MOSTLY COMPLETE

### Arrays
- [x] Fixed-size arrays: `[Int; 5]`
- [x] Array literals: `[1, 2, 3, 4, 5]`
- [x] Indexing: `arr[0]` (works for both arrays and tuples)
- [ ] Length: `arr.len()`
- [ ] Bounds checking

### Vectors ✅ COMPLETE
- [x] `Vector<T>` dynamic arrays
- [x] `push`, `pop`, `len`, `get`
- [x] Indexing and iteration

### Dictionaries ✅ COMPLETE
- [x] `Map<K, V>` type
- [x] `get`, `insert`, `remove`, `len`
- [ ] Literal syntax: `{"key": value}`
- [ ] Iteration over keys/values

### Sets
- [ ] `Set<T>` type
- [ ] Literal syntax: `{1, 2, 3}`
- [ ] `insert`, `remove`, `contains`

---

## Priority 5: Functions & Closures ✅ MOSTLY COMPLETE

### Function Features
- [ ] Default parameter values
- [x] Reference parameters with `&` at call site
- [x] Multiple return via tuples

### Closures ✅ COMPLETE
- [x] Closure syntax: `{ x in x * 2 }`
- [x] Shorthand: `{ $0 * 2 }`
- [x] Capturing variables (copy semantics)
- [x] Trailing closure syntax: `obj.method { ... }`
- [x] Function types: `(Int) -> Int`

---

## Priority 6: Traits & Polymorphism ✅ MOSTLY COMPLETE

### Traits
- [x] Trait declarations: `trait Name { func method(self) -> Type }`
- [ ] Default method implementations
- [x] `extension Type: Trait` for conformance
- [x] Trait bounds: `<T: Display>`
- [x] Multiple bounds: `<T: Display + Debug>`
- [x] Associated types: `type Item` in traits
- [x] Conformance checking (missing methods, signature mismatches)

### Built-in Traits
- [ ] `Copy` - implicit copy
- [ ] `Clone` - explicit clone
- [ ] `Display` - string representation
- [ ] `Debug` - debug output
- [ ] `Eq`, `PartialEq` - equality
- [ ] `Ord`, `PartialOrd` - ordering
- [x] `Iterator` - iteration protocol (builtin for ranges and custom types)

### Type Extensions ✅ COMPLETE
- [x] `extension Type { }` syntax
- [x] Adding methods to structs
- [x] `self` in immutable methods
- [x] `var self` for mutating methods
- [x] Custom `init` methods with overloading
- [x] Generic extension specialization
- [ ] Computed properties
- [ ] Conditional extensions with `where`
- [ ] Extensions for built-in types (Int, String, Bool)

---

## Priority 7: Memory Management ✅ COMPLETE

### Resource Management Traits
- [x] `Deinit` trait - automatic cleanup at scope exit
- [x] `CustomCopy` trait - custom copy logic (e.g., reference counting)
- [x] `NoCopy` trait - move-only types (cannot be copied)
- [x] `move` keyword for explicit ownership transfer
- [x] Containment rules - structs containing Deinit/CustomCopy/NoCopy fields must implement the trait
- [x] Automatic field deinit - compiler calls deinit on fields after user's deinit code
- [x] Automatic field copy - compiler calls copy() on CustomCopy fields during struct init
- [x] Manual deinit disallowed - calling obj.deinit() is a compile error

### Shared Ownership (deferred - needs heap allocation)
- [ ] `Box<T>` - heap allocation
- [ ] `Rc<T>` - reference counting
- [ ] `Arc<T>` - atomic reference counting

### Synchronization (deferred)
- [ ] `Mutex<T>`
- [ ] `RwLock<T>`
- [ ] Lock guards

---

## Priority 8: Error Handling ✅ MOSTLY COMPLETE

### Result Type
- [x] `Result<T, E>` enum with `Ok(value)` and `Err(error)`
- [x] Auto-wrap returns in functions returning `Result<T, E>`
- [x] `try!` - force unwrap (panics on Err)
- [x] `try?` - convert to Optional
- [x] `try expr catch { fallback }` - inline catch
- [x] `try { } catch { }` blocks for local error handling
- [x] Implicit `error` variable in catch blocks
- [x] Multiple error types with match in catch block

### Error Trait
- [ ] Built-in `Error` trait with `message(self) -> String`
- [ ] Pattern matching on `Error` trait with RTTI
- [ ] Catch-all required when matching on `Error` (can't know all implementors)

### Panics
- [x] Panic on force-unwrap of None
- [x] Panic on force-unwrap of Result Err (try!)
- [ ] `panic(message)` function
- [ ] `assert(condition, message)`
- [ ] `debug_assert` (debug builds only)

---

## Priority 9: Module System ✅ COMPLETE

### Modules
- [x] `module` declarations (inline and external)
- [x] `public` visibility
- [x] `public(package)`, `public(parent)` fine-grained visibility
- [x] Per-module type checking

### Imports
- [x] `import modules.utils` - module import with qualified access
- [x] `import modules.utils.{Point, double}` - selective imports
- [x] Glob imports: `import modules.utils.*`
- [x] Module re-exports with `export`

### Package Structure
- [x] `Saw.toml` manifest parsing
- [x] `init.saw` module facades
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
- [ ] String constant deduplication

### Tooling
- [ ] REPL for interactive testing
- [ ] Language server (LSP)
- [ ] Formatter
- [ ] Package manager
- [ ] Debug info generation (DWARF)

### Build System
- [x] Makefile for test running
- [ ] Incremental compilation
- [ ] Parallel compilation of independent modules

---

## Architecture Notes

### Current Compiler Pipeline
```
Source (.saw) → Lexer → Tokens → Parser → AST → Type Checker → Typed AST → Codegen → LLVM IR → clang → Binary
```

### Module Structure
The compiler is organized into modular packages with mixin architecture:

| Package | Description |
|---------|-------------|
| sawc/parser/ | Recursive descent parsing with mixins |
| sawc/typechecker/ | Type checking with expression/statement mixins |
| sawc/codegen/ | LLVM IR generation with specialized mixins |
| sawc/namespace.py | Unified symbol management |
| sawc/module_resolver.py | Module resolution and imports |

### Strengths
- Clean separation of compiler phases
- Modular architecture with focused mixins
- All AST nodes track line/column for diagnostics
- Multi-pass type checking handles forward references
- 171 integration tests with parallelized test runner

---

## Notes

- **Code quality (Priority 0)** added because technical debt slows feature development
- **Testing infrastructure (Priority 0.5)** critical for catching regressions
- Features are ordered by dependency (later features often depend on earlier ones)
- Type system comes before collections because structs/enums are needed to build them
- Traits enable the standard library design (`Copy`, `Clone`, `Iterator`, etc.)
- Concurrency and metaprogramming can wait until the core language is solid

## Quick Wins (Low effort, high value)
- [x] Add `while` loop (simple extension of existing control flow)
- [x] Add logical operators `&&`, `||`, `not` (straightforward binary/unary ops)
- [x] Add `%` modulo operator
- [x] Match exhaustiveness checking
- [x] Compound assignment operators
- [x] String interpolation

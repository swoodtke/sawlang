# Saw Language - Implementation Roadmap

## Current Status (MVP Complete + Core Types)

**Compiler Stats:** ~5,100 lines of Python across 7 modules
- Lexer: 316 LOC | Parser: 993 LOC | Type Checker: 1,556 LOC | Codegen: 1,454 LOC

**Completed Features:**
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
- [x] Optionals with `None`, `!`, `??`, `?.`
- [x] Optional binding: `if let`/`if var`, `guard let`/`guard var`
- [x] Enums with associated data and pattern matching
- [x] Struct extensions with methods and custom init
- [x] Mutable methods (`var self`)
- [x] While loops with `break` and `continue`

---

## Priority 0: Code Quality & Technical Debt

### Known Issues in Code (TODOs)
- [ ] `typechecker.py:499` - Validate guard else branch contains early exit (return/break/continue)
- [ ] `codegen.py:1033` - Add runtime panic check for force-unwrap of None

### Runtime Safety
- [ ] Panic on force-unwrap (`!`) of `None` value
- [ ] Panic on out-of-bounds tuple access
- [ ] Better runtime error messages with source locations

### Code Refactoring
- [ ] Extract `_check_expression` into visitor pattern (currently ~150 lines)
- [ ] Extract `_generate_expression` into visitor pattern (currently ~160 lines)
- [ ] Extract `parse_postfix` into smaller methods (currently ~120 lines)
- [ ] Reduce code duplication in optional wrapping/unwrapping logic
- [ ] Add docstrings to complex type checking methods

### String Handling
- [ ] Support additional escape sequences: `\r`, `\0`, `\xNN`
- [ ] Unicode escapes: `\u{NNNN}`

---

## Priority 0.5: Testing Infrastructure

### Automated Testing
- [x] Create test runner script for all examples
- [x] Add expected output assertions for each example
- [x] Verify error test cases produce correct error messages
- [ ] Add unit tests for lexer
- [ ] Add unit tests for parser
- [ ] Add unit tests for type checker

### CI/CD
- [ ] GitHub Actions workflow for automated testing
- [ ] Test on multiple Python versions (3.9+)
- [ ] Test LLVM IR generation without full compilation

### Test Coverage Gaps
- [ ] Edge cases for optional chaining chains
- [ ] Nested struct field assignment
- [ ] Complex enum pattern matching
- [ ] Method overloading resolution

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
- [ ] Better error messages for extensions:
  - [ ] Extension of undefined struct
  - [ ] Duplicate method names
  - [ ] Missing self parameter
  - [ ] Self type mismatch
  - [ ] Method call on non-struct type
  - [ ] Accessing method as field

### Error Recovery
- [ ] Parser recovery after syntax errors (currently stops on first error)
- [x] Continue type checking after type errors
- [x] Collect all errors before reporting

---

## Priority 2: Core Type System

### Optionals (T?)
- [x] Optional type syntax: `Int?`, `String?`
- [x] `None` literal (Swift-style with implicit wrapping)
- [x] Optional chaining: `user?.profile?.name`
- [x] Nil coalescing: `value ?? default`
- [x] Force unwrap: `value!`
- [x] `if let`/`if var` binding (var creates mutable reference)
- [x] `guard let`/`guard var` early exit

### Structs
- [x] Struct declarations
- [x] Field access
- [x] Struct initialization: `Point(x: 10, y: 20)`
- [x] Field assignment: `obj.field = value`
- [x] `extension` blocks for methods
- [x] `self` in methods
- [x] `var self` for mutating methods
- [x] Custom `init` methods with overloading
- [ ] Built-in type extensions (Int, String, Bool, etc.)
- [ ] Static methods (no self parameter)
- [ ] Method overloading (beyond init)

### Enums (Algebraic Data Types)
- [x] Simple enums (no data)
- [x] Enums with associated data: `Some(T)`, `None`
- [x] Named parameters: `Move(x: Int, y: Int)`
- [x] Pattern matching on enums with `match` expressions
- [x] Match bindings to extract associated values
- [x] Enum equality operators (`==` and `!=`)
- [ ] Exhaustiveness checking for match expressions (warn on missing cases)
- [ ] Deep equality comparison (compare payloads, not just variant tags)

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
- [x] `while` loops (with optional condition for infinite loops)
- [x] `break` statement (with optional value)
- [x] `continue` statement
- [ ] While loops as expressions (see details below)
- [ ] `for item in collection` loops
- [ ] `for (index, item) in collection.enumerate()`

#### While Loops as Expressions (Future Enhancement)

**Goal**: Allow while loops to return values via `break value`

**Syntax**:
```saw
// Conditional loop → Optional type
let found = while i < arr.len() {
    if arr[i] == target {
        break i  // Return Some(i)
    }
    i = i + 1
}  // found: Int? (Some if found, None if loop exits naturally)

// Infinite loop → Non-optional type
let result = while {
    if ready() {
        break 42
    }
}  // result: Int (must break to exit)
```

**Type Rules**:
- **Conditional while**: Returns `T?` where T is the break value type
  - `break value` → `Some(value)`
  - Natural exit (condition false) → `None`
- **Infinite while**: Returns `T` (non-optional)
  - Must have at least one `break value` to exit
  - Compile error if no breaks or if any break has no value

**Implementation Complexity**: Medium (3-4 hours)
1. AST: Convert `WhileStatement` to `WhileExpr` (can be used as statement or expression)
2. Type Checking (1-1.5 hours):
   - Track expected break type in current loop
   - Validate all breaks have compatible types
   - For conditional loops: wrap result in Optional
   - For infinite loops: ensure at least one break exists
3. Code Generation (1.5-2 hours):
   - Allocate storage for result value
   - Store break values before jumping to end
   - Load result after loop
   - For conditional loops: wrap in Optional struct
4. Testing (30 min): Add tests for both cases

**Challenges**:
- Type inference: Need to know result type before generating loop storage
- Multiple break points: All must have compatible types
- Error handling: Infinite loops without breaks should error

### Pattern Matching
- [x] `match` expression on enums
- [x] Variable binding in enum patterns: `case Success(n) -> ...`
- [x] Wildcard pattern: `case _ -> ...` (default case)
- [ ] Literal patterns: `case 0 -> ...`
- [ ] Range patterns: `case 1..=9 -> ...`
- [ ] Guards: `case n if n < 0 -> ...`
- [ ] Exhaustiveness checking (warn on missing enum variants)
- [ ] Match on primitive types (Int, Bool, String)
- [ ] Match on tuples with destructuring

### Additional Operators
- [ ] Logical AND/OR: `&&`, `||`
- [ ] Logical NOT: `not` keyword (note: `!` is force-unwrap)
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
- [x] `extension Type { }` syntax
- [x] Adding methods to structs
- [x] `self` in immutable methods
- [x] `var self` for mutating methods
- [x] Custom `init` methods with overloading
- [ ] Computed properties
- [ ] Conditional extensions with `where`
- [ ] Extensions for built-in types (Int, String, Bool)

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
- [ ] String constant deduplication

### Tooling
- [ ] REPL for interactive testing
- [ ] Language server (LSP)
- [ ] Formatter
- [ ] Package manager
- [ ] Debug info generation (DWARF)

### Build System
- [ ] Makefile or build script
- [ ] Incremental compilation
- [ ] Parallel compilation of independent modules

---

## Architecture Notes

### Current Compiler Pipeline
```
Source (.saw) → Lexer → Tokens → Parser → AST → Type Checker → Typed AST → Codegen → LLVM IR → clang → Binary
```

### Module Sizes (as of last analysis)
| Module | Lines | Responsibility |
|--------|-------|----------------|
| typechecker.py | 1,510 | Type checking, semantic analysis |
| codegen.py | 1,391 | LLVM IR generation |
| parser.py | 951 | Recursive descent parsing |
| ast_nodes.py | 389 | 38 AST node dataclasses |
| lexer.py | 312 | Tokenization |
| sawc.py | 191 | CLI entry point |
| errors.py | 132 | Error formatting |

### Strengths
- Clean separation of compiler phases
- All AST nodes track line/column for diagnostics
- Multi-pass type checking handles forward references
- 36 example programs as integration tests

### Areas Needing Attention
- Large switch statements in typechecker and codegen
- No automated test runner
- Guard statement validation incomplete
- Force-unwrap lacks runtime safety check

---

## Notes

- **Code quality (Priority 0)** added because technical debt slows feature development
- **Testing infrastructure (Priority 0.5)** critical for catching regressions
- **Type checking is Priority 1** because a compiler without proper errors is frustrating to use
- Features are ordered by dependency (later features often depend on earlier ones)
- Type system comes before collections because structs/enums are needed to build them
- Control flow (loops) is essential for writing practical programs
- Traits enable the standard library design (`Copy`, `Clone`, `Iterator`, etc.)
- Concurrency and metaprogramming can wait until the core language is solid

## Quick Wins (Low effort, high value)
- [x] Add `while` loop (simple extension of existing control flow)
- [ ] Add logical operators `&&`, `||` (straightforward binary ops)
- [ ] Add `%` modulo operator
- [ ] Exhaustiveness warning for match expressions

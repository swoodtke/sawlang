# Saw

A modern systems programming language combining the safety of Rust with the elegance of Swift.

## Why Saw?

Saw takes the best ideas from modern languages and combines them into a cohesive whole:

- **Safety enforced, not just promised** - No null pointers; memory safety is
  checked at a single value-transfer checkpoint, and mutable aliasing is caught
  statically by the Law of Exclusivity (many readers XOR one writer) — no
  garbage collector, no lifetimes
- **Elegant syntax** - Clean, readable code inspired by Swift
- **Zero-cost abstractions** - High-level constructs compile to efficient machine code
- **Predictable performance** - No hidden allocations (the only implicit copies
  are cheap by contract), deterministic LIFO destruction
- **Kernel- and embedded-ready** - freestanding by design: pluggable allocators,
  memory-mapped registers, compile-time layout checks, and C-ABI exports

## Quick Example

```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    func magnitude(&self) -> Int {
        self.x * self.x + self.y * self.y
    }

    func translate(&var self, dx: Int, dy: Int) {
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

// Optional chaining (illustrative)
let len = user?.profile?.name?.len()
```

### Error Handling with Result

```saw
struct ParseError {
    message: String
}

func parse(empty: Bool) -> Result<Int, ParseError> {
    if empty {
        return ParseError(message: "empty input")  // Auto-wrapped to Err
    }
    return 42  // Auto-wrapped to Ok
}

func main() {
    // Force unwrap (panics on error)
    let n = try! parse(false)
    print(n)  // 42

    // Inline catch with fallback
    let value = try parse(true) catch { 0 }
    print(value)  // 0

    // Pattern match on Result
    match parse(false) {
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
        case Quit -> print("quit"),
        case Move(x, y) -> print(x + y),
        case Write(text) -> print(text)
    }
}
```

### Traits, Default Methods, and Dynamic Dispatch

Conform via `extension Type: Trait`. Trait methods may carry a **default body**,
and any object-safe trait can be used as an `any Trait` existential for runtime
dynamic dispatch behind explicit ownership (`&any Trait` or `Box<any Trait>`):

```saw
trait Greeter {
    func name(&self) -> String
    func greet(&self) -> String {       // default body — calls a required method
        "Hello, {self.name()}!"
    }
}

extension Robot: Greeter {
    func name(&self) -> String { "R2" }
    // greet() inherited from the default; prints "Hello, R2!"
}

trait Shape {
    func area(&self) -> Int
}

func print_area(s: &any Shape) {   // dynamic dispatch through a fat pointer
    print(s.area())
}
```

### Overloading

A function, method, or `init` name carries an overload set resolved by exact
argument types:

```saw
func area(side: Int) -> Int { side * side }
func area(width: Int, height: Int) -> Int { width * height }

print(area(5))      // 25
print(area(3, 4))   // 12
```

### Printable and String Interpolation

Conform to `Printable` and your type interpolates like a builtin:

```saw
extension Point: Printable {
    func format(&self, into: &var StringBuilder) {
        into.append("(")
        into.append(self.x)
        into.append(", ")
        into.append(self.y)
        into.append(")")
    }
}

let p = Point(x: 3, y: 4)
print("point = {p}")   // point = (3, 4)
print(p.to_string())   // (3, 4)  — default method from Printable
```

### Errors as Values, Optionally Erased

`Error: Printable`, and `Result<T, Box<any Error>>` lets a function return any
error type without a hand-written union — the concrete error is auto-wrapped and
auto-erased at the return boundary (hosted convenience; kernel code keeps
concrete or closed-union errors to avoid hidden allocation):

```saw
func parse(ok: Bool) -> Result<Int, Box<any Error>> {
    if ok { return 42 }
    return ParseError(line: 7)   // auto-wrapped Err, erased into Box<any Error>
}

match parse(false) {
    case Ok(n) -> print(n),
    case Err(e) -> print("{e}")  // renders via the vtable
}
```

### Colorless Concurrency

No `async`/`await` keyword — **any call may suspend**, and the rare marked side
is the checked negative effect `sync`. A `TaskGroup` is a structured-concurrency
nursery: children are joined (or cancelled) when the group is torn down.

```saw
func work(n: Int) -> Int {
    yield_now()          // cooperative suspension point
    n * n
}

func main() {
    var group = TaskGroup()
    let a = group.spawn(work(3))
    let b = group.spawn(work(4))
    print(a.join() + b.join())   // 25 — structured join
}
```

### The Copy Trait Family

Transfer cost is readable at the use site. Trivial types (integers, POD structs)
copy implicitly and cheaply. Owning types are move-by-default: duplication is a
visible `.copy()`, and the compiler demands `move` to transfer ownership.
Refcounted types (like `String` and `Arc`) are `ImplicitCopy` — copies are cheap
refcount bumps, no `move` needed.

```saw
let a = Point(x: 1, y: 2)
let b = a              // trivial type: implicit copy, both valid

var v: Vector<Int> = [1, 2, 3]
var w = move v         // owning type: ownership transferred, v invalid
var u = w.copy()       // explicit, independent deep copy

let s1 = "hi"
let s2 = s1            // String: cheap implicit refcount bump, both valid
```

### Collection Literals and Sets

Bracket literals build a `Vector` in a `Vector`-typed position; braces build
`Map` (colon) or `Set` (comma):

```saw
let squares: Vector<Int> = [1, 4, 9, 16]
let ages: Map<String, Int> = {"ada": 36, "alan": 41}
let primes: Set<Int> = {2, 3, 5, 7}
```

### Ergonomic Details

```saw
func scale(x: Int, by: Int = 2) -> Int { x * by }  // default parameter value

scale(10)          // 20 — default used
scale(10, 3)       // 30

for i in 1..=5 { }  // inclusive range (..= )
let byte = 255u8    // fixed-width literal suffix
let _ = scale(99)   // discard binding (evaluates, drops, binds nothing)
assert(byte == 255, "sanity")   // panics with a message when false
```

### Type Extensions

Add methods and trait conformances to a type — including built-in primitives —
without modifying its definition:

```saw
extension Int {
    func doubled(&self) -> Int { self * 2 }
}

print(7.doubled())  // 14
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

Imports are Python-style (only the named symbol enters scope), with module and
per-symbol aliasing (`import std.io as sio`, `import m.{A as B}`), scoped
visibility (`public(package)`, `public(parent)`), and glob imports
(`import m.*`).

## Memory Management

Saw provides deterministic memory management without garbage collection:

- **The Copy trait family** — trivial types auto-copy bitwise; `ImplicitCopy`
  types copy cheaply on every transfer (refcount bumps, e.g. `String`, `Arc`);
  `ExplicitCopy` types (e.g. `Vector`, `Map`) never copy implicitly — you `move`
  to transfer or `.copy()` to duplicate; `NoCopy` types are move-only.
- **Explicit `move`** for ownership transfer, enforced at one value-transfer checkpoint
- **`Deinit` trait** for cleanup when values go out of scope (LIFO)
- **Reference types** (`&T`, `&var T`) for borrowing, with static exclusivity checking
- **Law of Exclusivity** — a `&var` path must be disjoint from every other
  by-reference path in the same call; fully static, no lifetimes
- **Shared ownership** via `Arc<T>` (atomic refcount — Saw is Arc-only) and owned
  heap allocation via `Box<T, A>`

```saw
// Mutable reference parameter (mutate via compound assignment; direct `x = ...`
// through a reference is rejected)
func increment(x: &var Int) {
    x += 1
}

var n = 5
increment(&n)  // n is now 6
```

## Kernels and Embedded

Saw is freestanding by design — the same language targets bare metal:

- **Pluggable allocation** — the allocator is a default type parameter on
  alloc-layer containers (`Vector<T, A = Global>`, `Map<K, V, A = Global>`,
  `Box<T, A = Global>`); a custom zero-sized allocator gives a distinct type that
  routes through its own `A` as a direct call. Per-type slab allocators over a
  `static` region make the `type JobBox = Box<Job, JobSlab>` kernel idiom work.
- **Memory-mapped I/O** — `UnsafeMemory<T, Use>` is a compiler-known view of
  memory at a fixed address, with volatile scalar `read()`/`write()` for device
  registers and field-offset projection.
- **Compile-time layout checks** — `static_assert(sizeof<UartRegs>() == 0x1C,
  "...")` fails the build on register-block drift at zero runtime cost.
- **C-ABI exports** — `@export("kernel_add")` gives a function an exact,
  unmangled symbol with the C calling convention; `@section("...")` places it in
  a named linker section. `Never`-returning exports lower to the `_start` shape.
- **Platform-width `Int`** — `Int`/`UInt` follow the target word (i64 on
  x86-64/aarch64, i32 on riscv32); fixed-width `Int8`…`Int64` have stable layouts
  for wire formats.

```saw
struct UartRegs {
    data: UInt32
    status: UInt32
}

static_assert(sizeof<UartRegs>() == 8, "UartRegs layout drift")

@export("kernel_add")
func add(a: Int, b: Int) -> Int {
    a + b
}
```

## Standard Library

Saw includes a growing standard library. Highlights:

- **String** - Immutable, reference-counted byte string (atomic refcount, O(1)
  `len()`), always valid UTF-8. `bytes()`/`chars()` iterator views, `split`,
  concatenation with `+`, `to_int`/`to_float` parsing, `fromBytes` (validating).
- **StringBuilder** - Efficient, geometrically-growing builder: `append`
  (overloaded for `String`/`Int`), `build`.
- **Vector<T, A>** - Dynamic array: `push`, `pop`, `get`, `len`, `map`/`fold`,
  `sort`/`sort_by`, `swap`; context-driven `[...]` literals.
- **Map<K, V, A>** - Hash map (open addressing): `insert`, `get`, `remove`,
  `contains_key`, `len`; `each` visitors and `keys()`/`values()` snapshots;
  `{k: v}` literals. Keys are any `Hashable + Equatable` type.
- **Set<T, A>** - Hash set: `insert`, `remove`, `contains`, `len`, plus
  `union`/`intersection`/`difference`/`is_subset`; `{a, b}` literals.
- **Arc<T>** / **Box<T, A>** - Atomic reference counting / owned heap allocation.
- **Mutex<T>**, **Channel<T>**, **Task<T>**, **TaskGroup** - Concurrency.
- **File**, **Directory**, **Path**, **Data**, **Env**, **Process** - System I/O.
- **std.time** - `Duration`, `Instant` (hosted).
- **Numeric extensions** - `Int`/`Float` methods: `abs`, `pow`, `min`/`max`/
  `clamp`, `sqrt`, `floor`/`ceil`/`round`, `is_even`/`is_odd`, `signum`.
- **Traits** - `Equatable`, `Comparable`, `Hashable`, `Printable`, `Error`.

## Getting Started

### Requirements

- Python 3.14 (a virtualenv is used — see below)
- `llvmlite` (LLVM bindings)
- Clang (for linking)

### Setup

The compiler runs from a project-local virtualenv at `.venv/`:

```bash
python3 -m venv .venv
./.venv/bin/pip install llvmlite
```

### Compile and Run

```bash
# Compile a program (-o names the output; default is .build/<source>)
./.venv/bin/python sawc/sawc.py examples/hello.saw -o hello

# Run it
./hello
```

### Compiler Options

```bash
./.venv/bin/python sawc/sawc.py <source.saw> [options]

Options:
  -o <file>    Output file name
  -c           Compile to object file only (no linking, no main required)
  -v           Verbose output
  --emit-ir    Output LLVM IR only
  --emit-ast   Dump typed AST for debugging
  -O0          Disable optimization (default is an O1-style pass pipeline)
```

## Running Tests

The compiler ships a comprehensive test runner. `make test` calls bare
`python3`, so activate the virtualenv first (or invoke the runner directly):

```bash
# Activate the venv, then run the full suite
source .venv/bin/activate
make test

# ...or invoke the runner directly without activating
./.venv/bin/python test_runner.py

# Filter by pattern
make test-filter FILTER=enum
```

Run `make test` to see the current test count. See
[TESTING.md](TESTING.md) for details, including application-level testing with
`blade test`.

## Current Status

Saw is in active development, with a large and growing feature set: generics with
trait bounds and monomorphization, ADTs with exhaustive `match`, the Copy trait
family, traits with default bodies and `any Trait` existentials, overloading,
`Printable`/`Error`/`Equatable`/`Comparable`/`Hashable`, colorless concurrency
(cooperative tasks + a thread-per-task engine), pluggable allocators, and the
freestanding toolkit (memory-mapped I/O, `static_assert`, C-ABI exports).

The authoritative, always-current feature list lives in
[CLAUDE.md](CLAUDE.md); the full language reference is in
[LANGUAGE_SPEC.md](LANGUAGE_SPEC.md).

## Blade Package Manager

Saw includes Blade, a package manager written in Saw itself — with a real TOML
parser, manifest model, builder, and test runner:

```bash
# Build the package manager
./.venv/bin/python sawc/sawc.py blade/src/main.saw -o .build/blade

# Use it
./.build/blade new myproject   # scaffold a new project
./.build/blade build           # compile the current project
./.build/blade run             # build and run
./.build/blade test            # compile and run the project's tests/
```

`blade test` discovers `tests/*.saw` files, compiles and runs each, and reports
failures (a test fails via `assert`/`panic`; a nonzero exit fails the build).

## Design Philosophy

### Key Differences from Rust

| Aspect | Rust | Saw |
|--------|------|-----|
| Transfer default | Move everything | Trivial types copy; owning types move (Copy trait family) |
| Mutability | `let mut` | `var` |
| Optionals | `Option<T>` | `T?` (postfix) |
| References | `&T`, `&mut T` | `&T`, `&var T` |
| Initialization | `Type::new()` | `Type()` |
| Type extensions | Traits (impl blocks) | `extension` blocks |
| Modules | `mod`, `pub`, `use` | `module`, `public`, `import` |
| Error handling | `?` operator | `try`/`try?`/`try!` |
| Concurrency | `async`/`await` (colored) | colorless tasks (no keyword) |

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
examples/              # Example programs (also the compiler test suite)
blade/                 # Blade package manager (written in Saw)
designs/               # Design briefs and the project tracker
LANGUAGE_SPEC.md       # Full language specification
TESTING.md             # Test suite documentation
```

## Contributing

Saw is an experimental language. Contributions, feedback, and ideas are welcome!

## License

Saw is licensed under the [Apache License 2.0 with LLVM
Exceptions](LICENSE) (SPDX: `Apache-2.0 WITH LLVM-exception`).

In plain terms: use, modify, and redistribute freely — with an explicit
patent grant from contributors. The LLVM exception means programs you
compile with `sawc` are entirely yours: the standard-library code
embedded in your binaries carries no attribution requirements.

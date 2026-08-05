# Saw

[![CI](https://github.com/swoodtke/claudes-lang/actions/workflows/ci.yml/badge.svg)](https://github.com/swoodtke/claudes-lang/actions/workflows/ci.yml)

A systems programming language with Rust-style memory safety and Swift-style
syntax. It has no garbage collector and no lifetimes.

## What Saw gives you

- **Memory safety without a garbage collector or lifetimes** - There are no null
  pointers. Memory safety is checked when a value is transferred, and mutable
  aliasing is caught at compile time by the Law of Exclusivity: a value can have
  many readers or one writer, never both at once.
- **Swift-style syntax** - `let`/`var` bindings, `extension` blocks, `T?`
  optionals, and trailing closures.
- **Zero-cost abstractions** - Generics and traits compile down to specialized
  machine code, with no runtime overhead for the abstraction.
- **Predictable performance** - Allocation is visible in the type: the
  allocating containers carry their allocator as a type parameter, and no
  assignment is secretly O(n). Two constructs allocate without a signature
  saying so, and they are the only two — an escaping closure heap-allocates its
  captured environment, and string interpolation allocates its result buffer.
  The only implicit copies are cheap ones, and values are destroyed in a defined
  order (last in, first out) as they go out of scope.
- **Runs on bare metal** - Saw is freestanding. Pluggable allocators,
  memory-mapped registers, compile-time layout checks, and C-ABI exports let it
  target kernels and embedded systems.

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

// Optional chaining — multi-hop fields + methods; result is `U?` (flattened)
let len = user?.profile?.name?.len()
user?.profile?.name = "Ada"   // chained assignment writes in place (`Void?`)
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

Conform via `extension Type: Trait`. Trait methods may carry a **default body**.
Any object-safe trait can also be used as a trait object (`any Trait`, called
an existential in the language spec) for runtime dynamic dispatch, held behind
explicit ownership (`&any Trait` or `Box<any Trait>`):

```saw
trait Greeter {
    func name(&self) -> String
    func greet(&self) -> String {       // default body: calls a required method
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

func print_area(s: &any Shape) {   // dynamic dispatch
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

### Generic Type Inference

Type arguments are inferred at call sites, from argument types, closure return
types, and even default values. Inference also works across overload sets: the
compiler picks a unique match, and a genuine tie is a compile error that lists
the candidates rather than guessing. You can always write `<...>` explicitly, and
an explicit type argument always wins:

```saw
func first<T>(v: &Vector<T>) -> T? { v.get(0) }

let names: Vector<String> = ["ada", "alan"]
let n = first(&names)              // T = String, inferred
let squares = names.map({ $0.len() })   // map<Int> solved from the closure
```

### Debug-Friendly Source Locations

`#file`, `#line`, and `#function` are compile-time literals filled in at the
definition site, with no runtime cost. Panics and asserts already include a
`panic at FILE:LINE:` prefix.

```saw
print("{#file}:{#line} in {#function} - checkpoint")
```

### Documentation Comments

`///` documents the declaration that follows it — a function, type, trait,
`static`, struct field, enum case, or extension method. `//!` documents the file
it appears in and belongs at the top, ahead of every declaration. A doc comment
that documents nothing is a compile error rather than a silent drop.

```saw
//! Monotonic and wall-clock time.

/// A span of time, held as whole nanoseconds.
struct Duration {
    /// Nanoseconds in the span.
    public nanos: Int64
}
```

`sawc <entry.saw> --emit-docs` type-checks the program and writes a JSON
description of it instead of generating code, covering the entry file's module
and every module it imports. Each item carries its rendered signature,
visibility, generic parameters and bounds, trait conformances, doc text, and
source line. Ordering is fixed, so the output diffs cleanly. Private fields,
methods, and inits are left out; `--emit-docs-all` keeps them.

### Shadowing Must Be Earned

Accidentally reusing a name from an enclosing scope is a compile error. The
exception is when the new binding is visibly derived from the one it shadows,
meaning the initializer mentions it. Deliberate refinement compiles; accidental
reuse does not:

```saw
if let x = x { }                  // OK: unwrap refinement
let data = parse(move data)       // OK: derived, old binding retired
for item in items.iter() { }      // fine: no shadow at all
for x in x.iter() { }             // OK: sequence mentions the shadowed name
let x = compute()                 // ERROR under an outer `x`; rename it
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
print(p.to_string())   // (3, 4), from Printable's default method
```

### Errors as Values

Every `Error` is `Printable`. Returning `Result<T, Box<any Error>>` lets a
function return any error type without writing a union by hand: the concrete
error is boxed and its exact type hidden behind `any Error` at the return
boundary. That is a convenience for hosted code. Kernel code sticks to concrete
or closed-union error types to avoid the hidden allocation.

```saw
func parse(ok: Bool) -> Result<Int, Box<any Error>> {
    if ok { return 42 }
    return ParseError(line: 7)   // auto-wrapped Err, boxed as Box<any Error>
}

match parse(false) {
    case Ok(n) -> print(n),
    case Err(e) -> print("{e}")  // prints via Printable
}
```

### Colorless Concurrency

There is no `async`/`await` keyword. **Any call may suspend**, and the rare call
that must not is marked `sync`, which the compiler checks. A `TaskGroup` owns its
child tasks and joins them when it goes out of scope; cancellation is explicit
and cooperative (`handle.cancel()`). A group is a scope, not a lifetime extender:
a task's values deinit when the task finishes, so a long-lived group does not
accumulate the resources of tasks that have already completed. The one value that
outlives a task is its result, which `join()` hands to the caller.
`TaskGroup(threads: N)` opts into running on multiple threads, with `Send` checked
at every spawn; the default stays single-threaded and deterministic.

```saw
import std.task          // `yield_now` lives in std.task

func work(n: Int) -> Int {
    yield_now()          // cooperative suspension point
    n * n
}

func main() {
    var group = TaskGroup()
    let a = group.spawn(work(3))
    let b = group.spawn(work(4))
    print(a.join() + b.join())   // 25, structured join
}
```

A suspending call needs no special position. It can sit in an operand, an
argument, a receiver, a chain hop, a collection literal, a string interpolation,
or a `return` value. The compiler rewrites the statement into evaluation-ordered
steps, so left-to-right order and short-circuiting hold as written:

```saw
func report() -> Int {
    let total = work(3) + work(4)      // both operands suspend
    print("squared: {work(5)}")        // suspends inside an interpolation
    let cached: Int? = None
    let extra = cached ?? work(7)      // the `??` RHS suspends only if it runs
    return total + extra
}
// spawned into a TaskGroup: prints "squared: 25", joins 74
```

A suspension the transform cannot place is a compile error naming the site, not
a silent blocking call.

A single cooperative scheduler runs spawned tasks eagerly, backed by an I/O
reactor (kqueue or epoll). A task parked on a socket wakes exactly when its file
descriptor is ready, cancellation wakes even an already-parked task, and an
operation-count budget stops a spinning task from starving the others: the
compiler charges every loop iteration of a task body against that budget, so a
pure-compute loop cedes without an explicit `yield_now`. So an
endless `accept`-loop server keeps serving live connections. Blocking FFI calls
(`extern "C" { blocking func ... }`) run on a separate thread and park the task
like any other I/O, so the remaining tasks stay responsive.

### Cooperative Networking

`std.net` exposes owning, safe types with no raw file descriptors or callbacks.
Suspension happens inside the methods, failures come back as `Result`, and
end-of-stream is represented as a distinct value from an error:

```saw
import std.net.{TcpListener, TcpStream}

let listener = try! TcpListener.listen(0)
while {
    let conn = try! listener.accept()        // parks; siblings keep running
    let _ = group.spawn(handle(move conn))
}

func handle(stream: TcpStream) {
    let chunk = try! stream.read()           // Result<Data, IoError>; empty Ok = EOF
    try! stream.write("hello")               // writes everything or errors honestly
}                                            // stream deinits here: the fd closes
                                             // when the handler returns

```

### The Copy Trait Family

You can see the cost of a transfer at the point where it happens. Trivial types
(integers, simple structs) copy implicitly and cheaply. Owning types move by
default: duplicating one is a visible `.copy()`, and transferring ownership
requires the `move` keyword. Reference-counted types like `String` and `Arc` are
`ImplicitCopy`, so a copy is a cheap refcount bump and needs no `move`.

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

scale(10)          // 20, default used
scale(10, 3)       // 30

for i in 1..=5 { }  // inclusive range (..= )
let byte = 255u8    // fixed-width literal suffix
let _ = scale(99)   // discard binding (evaluates, drops, binds nothing)
assert(byte == 255, "sanity")   // panics with a message when false
```

A statement ends at the end of its line, and there are no semicolons. Inside
brackets a line break carries no meaning, so anything that does not fit wraps —
argument lists, parameter lists, collection literals, generic lists — with an
optional trailing comma in the `(...)` and `[...]` forms:

```saw
func visit(
    dep_name: String,
    constraint: String,
    seen: &var Vector<String>,
) -> Bool {
    seen.push(dep_name)
    constraint.len() > 0
}

let grid: Vector<Int> = [
    1, 2,
    3, 4,
]
```

`{` and `}` are the exception: a block or closure is a statement container, so
line breaks inside one still end statements, even when the braces sit inside a
wrapped argument list. A bracket that is never closed is reported at the opener.

### Type Extensions

Add methods and trait conformances to a type, including built-in primitives,
without modifying its definition:

```saw
extension Int {
    func doubled(&self) -> Int { self * 2 }
}

let n = 7
print(n.doubled())  // 14
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
per-symbol aliasing (`import mypkg.io as fileio`, `import m.{A as B}`), scoped
visibility (`public(package)`, `public(parent)`), and glob imports
(`import m.*`).

**Member visibility**: struct fields and extension methods (including `init`)
are private by default outside their defining module, and `public` marks the API
surface. The standard library lives under the same gate: you reach its public
API, never its internals.

**Prelude discipline**: a curated core is available bare (primitives,
`Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/`Arc`, the trait vocabulary,
`print`/`panic`/`assert`, the concurrency primitives, `StringBuilder`).
Everything else
(`File`, `Data`, `Channel`, `Mutex`, `TcpStream`, `Command`, and so on) needs
`import std.<module>`, which also means your own type named `File` or
`IoError` never collides with the standard library's.

## Memory Management

Saw provides deterministic memory management without garbage collection:

- **The Copy trait family**: trivial types copy bitwise. `ImplicitCopy` types
  (like `String` and `Arc`) copy cheaply on every transfer as a refcount bump.
  `ExplicitCopy` types (like `Vector`) never copy implicitly: you `move` to
  transfer them or `.copy()` to duplicate. `NoCopy` types (like `File`, `Mutex`,
  and for now `Map`/`Set`) can only be moved.
- **Explicit `move`** for ownership transfer, checked at the point of transfer.
- **The `Deinit` trait** runs cleanup when a value goes out of scope, in reverse
  order of creation.
- **Reference types** (`&T`, `&var T`) for borrowing, checked for exclusivity at
  compile time.
- **The Law of Exclusivity**: a `&var` (mutable) reference must not overlap any
  other reference reaching the same value in the same call. It is fully static,
  with no lifetimes to write.
- **References compose**: a `&T` or `&var T` you receive can be passed on to
  another function as a re-borrow. A reference is never made more permissive than
  the one it came from, and references stay valid across suspension points.
- **Shared ownership** through `Arc<T>` (Saw uses atomic reference counts only)
  and owned heap allocation through `Box<T, A>`.
- **Allocation failure is loud**: an infallible operation (`push`, `append`,
  `insert`, `send`, `Box.make`, any constructor) panics with the name of the
  method that ran out of memory. It never truncates the container, never returns
  a plausible substitute value, and never hands back an object that has quietly
  stopped working. The `try_`-prefixed twins (`try_push`, `try_reserve`,
  `try_make`, `try_insert`, `try_send`) return `Result<_, AllocError>` for code
  that handles exhaustion rather than dying of it.
- **Unsafety is carried in the type**: raw pointers live in `Unsafe*` types.
  Where a pointer would flow through a function whose signature does not advertise
  it, you have to mark the spot with an `unsafe` expression. There are no
  `unsafe` blocks, and unsafety never spreads implicitly.

```saw
// Mutable reference parameter (the call site mirrors the parameter's sigil;
// mutate via compound assignment, mutating methods, or whole-referent
// replacement `x = v` — the same rule holds for `self = v` in a `&var self`
// method and for a closure's `&var` parameter)
func increment(x: &var Int) {
    x += 1
}

func reset(x: &var Int) {
    x = 0      // replaces the referent in place; caller still owns a valid Int
}

var n = 5
increment(&var n)  // n is now 6
reset(&var n)      // n is now 0
```

## Kernels and Embedded

Saw is freestanding: the same language targets bare metal.

- **Pluggable allocation**: the allocator is a default type parameter on the
  allocating containers (`Vector<T, A = GlobalAllocator>`,
  `Map<K, V, A = GlobalAllocator>`, `Box<T, A = GlobalAllocator>`). A custom zero-sized allocator produces a distinct type
  that routes through its own `A` as a direct call. Per-type slab allocators over
  a `static` region make the `type JobBox = Box<Job, JobSlab>` kernel idiom work.
- **One answer when allocation fails**: an infallible signature panics through
  the `__saw_rt_panic` seam, naming the method that ran out (`Vector.push:
  allocation failed`), so a kernel picks the policy. Every such operation has a
  `try_`-prefixed twin returning `Result<_, AllocError>` — `try_push`,
  `try_reserve`, `try_make`, `try_insert`, `try_send` — which is all-or-nothing:
  on `Err` the container is exactly as it was. Nothing truncates, and no type
  constructs an object that quietly stopped working.
- **Memory-mapped I/O**: `UnsafeMemory<T, Use>` is a compiler-known view of memory
  at a fixed address, with volatile `read()`/`write()` for device registers and
  field-offset projection.
- **Compile-time layout checks**: `static_assert(sizeof<UartRegs>() == 0x1C,
  "...")` fails the build when a register block's layout drifts, at no runtime
  cost.
- **C-ABI exports**: `@export("kernel_add")` gives a function an exact, unmangled
  symbol with the C calling convention, and `@section("...")` places it in a
  named linker section. A `Never`-returning export lowers to the `_start` shape.
- **Platform-width `Int`**: `Int` and `UInt` follow the target word (i64 on
  x86-64 and aarch64, i32 on riscv32), while fixed-width `Int8` through `Int64`
  have stable layouts for wire formats.

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

The standard library includes:

- **String** - Immutable, reference-counted byte string (atomic refcount, O(1)
  `len()`), always valid UTF-8. `bytes()`/`chars()` iterator views, `split`,
  `fromBytes` (validating), and parsing that returns an Optional rather than
  panicking: `to_int`, `to_float`, and `to_uint` — the unsigned companion that
  reaches the whole `0..UInt.max` range, with a `radix:` overload. Concatenation
  goes through interpolation or `StringBuilder`.
- **StringBuilder** - Geometrically-growing builder: `append` (overloaded for
  `String`/`Int`), `append_char`, `append_scalar` (UTF-8-encodes one Unicode
  scalar, returning the byte count, or `None` for a surrogate or out-of-range
  value), `len`, `is_empty`, `clear`, `as_str`, `build`.
- **Vector<T, A>** - Dynamic array: `push`, `pop`, `get`, `len`, `map`/`fold`,
  `sort`/`sort_by`, `swap`; context-driven `[...]` literals.
  `with_ref`/`with_var_ref` borrow one element in place for the duration of a
  closure, holding the whole vector borrowed so a reallocation cannot invalidate
  it. That is the only way to read or mutate a `NoCopy` element in place.
- **Map<K, V, A>** - Hash map (open addressing): `insert`, `get`, `remove`,
  `contains_key`, `len`; `each` visitors and `keys()`/`values()` snapshots;
  `{k: v}` literals. Keys are any copyable `Hashable + Equatable` type
  (move-only keys are rejected).
- **Set<T, A>** - Hash set: `insert`, `remove`, `contains`, `len`, plus
  `union`/`intersection`/`difference`/`is_subset`; `{a, b}` literals.
- **Arc<T>** / **Box<T, A>** - Atomic reference counting / owned heap allocation.
- **Mutex<T>**, **Channel<T>**, **Task<T>**, **TaskGroup** - Concurrency.
- **std.net** - `TcpListener`/`TcpStream`: owning, cooperative, `Result`-honest
  (accept/connect/read/`read_into`/overloaded write).
- **File**, **Directory**, **Path**, **Data**, **Env** - System I/O. Lookups and
  opens return Optionals; failable mutating operations (`remove`, `rename`,
  `create`, env `set`/`unset`) return `Result<Void, IoError>`. Nothing in std
  silently swallows an error.
- **std.process** - `Command.run() -> Result<Int32, ProcessError>`, `.output()`.
- **std.time** - `Duration`, `Instant` (hosted).
- **Numeric extensions** - The two sets are disjoint. `Int`: `abs`, `min`/`max`/
  `clamp`, `pow`, `is_even`/`is_odd`, `signum`. `Float`: `abs`,
  `floor`/`ceil`/`round`, `sqrt`, `min`/`max`.
- **Traits** - `Equatable`, `Comparable`, `Hashable`, `Printable`, `Error`.

## Getting Started

### Requirements

- Python 3.14 (a virtualenv is used; see below)
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
  -o <file>          Output file name (default: .build/<source>)
  -c                 Compile to an object file only (no linking, no main required)
  -v                 Verbose output
  --emit-ir          Output LLVM IR only
  --emit-ast         Dump the typed AST for debugging
  --emit-docs        Emit documentation JSON instead of code
  --emit-docs-all    Same, keeping private fields, methods, and inits
  -O0                Disable optimization (default is an O1-style pass pipeline)
  --target <triple>  Cross-compile for a target triple (default: the host)
  --freestanding     Freestanding profile: no hosted std, unlinked object output
  --runtime-build    Build a Saw runtime exporting the __saw_rt_* ABI
  --module-path NAME=DIR
                     Map a package name to a source directory (repeatable)
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

Saw is in active development. Implemented so far: generics with trait bounds and
call-site type inference (generics compile to specialized code); algebraic data
types with exhaustive `match`; the Copy trait family; traits with default bodies
and trait objects (`any Trait`); overloading; the `Printable`, `Error`,
`Equatable`, `Comparable`, and `Hashable` traits; multi-hop optional chaining
including chained assignment; whole-referent replacement through a `&var`
reference; colorless concurrency (a cooperative scheduler with a precise I/O
reactor, multi-threaded task groups, blocking-FFI offload, and suspending calls
in expression positions); member visibility with a curated prelude;
earned shadowing; source-location literals; doc comments with `--emit-docs`
extraction; pluggable allocators; and the freestanding toolkit (memory-mapped
I/O, `static_assert`, and C-ABI exports).

[LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) is the authoritative language reference —
when it and the compiler disagree, the compiler wins and the spec is the bug.
[CLAUDE.md](CLAUDE.md) is the compiler development guide; the language-state
paragraph at its end is an orientation summary, not a feature list of record.

## Blade Package Manager

Saw includes Blade, a package manager written in Saw itself. It has a TOML
parser, a manifest model, a dependency resolver, a deterministic lockfile, git
fetching, and incremental builds:

```bash
# Build the package manager (it depends on the libs/toml and libs/semver
# packages, so map both)
./.venv/bin/python sawc/sawc.py blade/src/main.saw -o .build/blade \
    --module-path toml=libs/toml/src \
    --module-path semver=libs/semver/src

# Use it
./.build/blade new myproject   # scaffold a new project
./.build/blade build           # resolve deps + compile (incremental; --force to rebuild)
./.build/blade update          # re-resolve dependencies and rewrite Saw.lock
./.build/blade run             # build and run
./.build/blade test            # compile and run the project's tests/
./.build/blade tree            # print the resolved dependency graph
./.build/blade add foo --path ../foo         # add a path dependency
./.build/blade add bar --git <url> --version ^1.0.0   # add a git dependency
```

### Dependencies (design 64)

A project declares dependencies in its `Saw.toml`:

```toml
[dependencies]
mathx = { path = "../mathx" }
jsonx = { git = "https://github.com/u/jsonx", version = "^1.2.0" }
tiny  = "0.3.1"          # bare = EXACT pin (ranges need ^, ~, or >=)
```

- **Resolver**: max-satisfying, one version per package. A path dep's version
  comes from its own manifest; a git dep's candidate versions are its `vX.Y.Z`
  tags (`git ls-remote`). Conflicts name every requirer; two different sources
  for one name, dependency cycles, and self-deps are errors.
- **`Saw.lock`**: deterministic (packages sorted, no timestamps), records
  version + source + git rev, plus a manifest-deps hash for drift detection.
- **Git**: tagged versions are cloned into `.blade/deps/<name>-<version>/`
  (`.blade/` is self-gitignoring). No global cache yet.
- **Incremental**: a content hash of every reachable source (`.blade/build-hash`)
  skips an up-to-date build; `--force` bypasses it.
- **Self-hosting**: Blade's own build depends on the `libs/toml` and
  `libs/semver` packages by path, so every Blade build exercises the resolver /
  lock / module-path pipeline. `make blade-bootstrap` runs the loop that builds and tests Blade
  through Blade itself.

`blade test` discovers `tests/*.saw` files, compiles and runs each (with the
project's dependency module-paths), and reports per-test timing; a test fails
via `assert`/`panic` or a nonzero exit.

The version-requirement logic also lives as a standalone library package,
`libs/semver` (a `Comparable`/`Printable` dogfood), with its own `blade test`
suite.

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

In plain terms: use, modify, and redistribute freely, with an explicit
patent grant from contributors. The LLVM exception means programs you
compile with `sawc` are entirely yours: the standard-library code
embedded in your binaries carries no attribution requirements.

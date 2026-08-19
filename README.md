# Saw

[![CI](https://github.com/swoodtke/sawlang/actions/workflows/ci.yml/badge.svg)](https://github.com/swoodtke/sawlang/actions/workflows/ci.yml)

A systems programming language with Rust-style memory safety and Swift-style
syntax. It has no garbage collector and no lifetimes, and it compiles for bare
metal as readily as for a hosted target.

This README is the starting point. For the full language rules, see
[LANGUAGE_SPEC.md](LANGUAGE_SPEC.md). For testing and contribution workflows,
see [TESTING.md](TESTING.md).

## What Saw gives you

- **Bare metal is a first-class target.** The freestanding profile links no
  libc and uses a small, fixed set of functions the host environment provides.
  Allocators are a type parameter, memory-mapped registers get a typed view,
  and `@export` gives a function an exact C symbol. The SOS kernel in this repo
  is built this way and boots under QEMU (`make sos-test`).
- **Memory safety without a garbage collector or lifetimes.** There are no null
  pointers. Ownership is checked where a value is transferred, and mutable
  aliasing is caught at compile time: many readers or one writer, never both at
  once (Saw calls this the Law of Exclusivity). There is nothing to annotate.
  Saw has no lifetime parameters.
- **Allocation is visible in the type.** The allocating containers carry their
  allocator as a type parameter, and the only implicit copies are cheap ones: a
  bitwise copy or a refcount bump. No assignment is secretly O(n). Duplicating
  a `Vector` is a visible `.copy()`. `sawc --no-hidden-alloc` turns this into a
  check: every allocation must be named by code you wrote, and the compiler
  allocating on its own authority is a compile error.
- **Destruction is deterministic.** Values are destroyed last-in-first-out as
  they leave scope, and the `deinit` is written for you from the type's fields.
- **A binary carries the program, not the standard library.** An import makes a
  module available to type-check against. It does not put the module in your
  output. Code generation walks out from `main` and the `@export`s and emits
  only what it reaches, and the link then strips whatever is left over. A
  four-line program links at about 63 KB.
- **Swift-style syntax, specialized generics.** `let`/`var` bindings,
  `extension` blocks, `T?` optionals, trailing closures, over generics and
  traits that compile to specialized machine code.

## Quick example

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

## A tour of the language

The sections below show how each feature reads at the keyboard. Each one links
to the spec for the full rules and the edge cases.

### Optionals instead of null

There are no null pointers. An absent value is `T?`, and `None` is the way to
spell one.

```saw
let maybe: Int? = None

if let value = maybe {       // bind if present
    print(value)
}

guard let value = maybe else {  // bind or return
    return
}

while let job = queue.pop() {  // one iteration per value, stops at None
    run(job)
}

let result = maybe ?? 0       // default value

// Optional chaining: multi-hop fields and methods; result is U?
let len = user?.profile?.name?.len()
user?.profile?.name = "Ada"   // chained assignment writes in place
```

See [Optionals](LANGUAGE_SPEC.md#optionals) in the spec.

### Error handling with Result

Failures are values, not exceptions. A function that can fail returns
`Result<T, E>`, and you handle it with `try`, `try!`, `try?`, a `match`, or an
inline `catch`.

```saw
struct ParseError { message: String }

func parse(empty: Bool) -> Result<Int, ParseError> {
    if empty { return ParseError(message: "empty input") }  // auto-wrapped Err
    return 42                                              // auto-wrapped Ok
}

func load_data() -> Result<Int, ParseError> {
    let value = try parse(false)   // an Err here returns from load_data immediately
    return value
}

func main() {
    let n = try! parse(false)        // panic on error
    print(n)                         // 42

    let value = try parse(true) catch { 0 }   // fallback on error
    print(value)                              // 0

    match parse(false) {
        case Ok(parsed) -> print(parsed),
        case Err(e) -> print(e.message)
    }
}
```

A bare `try` propagates the error to the caller. The enclosing function must
return a `Result`, and an `Err` becomes an early return, so `load_data` above
hands `ParseError` back to whoever called it. `try!` panics instead, and
`try?` turns the `Result` into an `Optional` (`None` on error). You can also
`match` on a `Result` directly, or handle it inline with `catch`.

A `Result` cannot be dropped by accident. Writing a fallible call as a bare
statement is a compile error, because the failure it reports would go nowhere:

```saw
stream.write(body)
// error: result of `write` is `Result<Void, IoError>` and is silently
//        discarded
// hint: handle it — `match` it, `try`/`try!`/`try?` it, or return it — or
//       write `let _ = ...` to discard it explicitly
```

Handle it, or say you meant to drop it with `let _ = stream.write(body)`.
Optionals and every other type stay freely discardable. The rule is about
failures, and a `Result` a caller may always ignore should not have been a
`Result`.

See [Error Handling](LANGUAGE_SPEC.md#5-error-handling) in the spec.

### main returns the exit status

`main` may return `Void`, `Int`, `Result<Void, E>` or `Result<Int, E>`, and
nothing else. `Void` exits 0, an `Int` is the status, an `Ok` payload is the
status (0 for `Ok(())`), and an `Err` prints the error and exits 1:

```saw
import std.file
import std.path.{Path}
import std.net.{IoError}

func main() -> Result<Void, IoError> {
    var config = try file.File.open(Path(s: "saw.toml"))
    let text = try config.read()
    print("read {text.len()} bytes")
    return
}
// With no saw.toml: prints `error: io error: open failed (not found)`, exits 1.
```

A command-line program reports failure by returning it, with no `exit()` call
and no status constant to keep in sync. The eight-bit narrowing a shell sees is
POSIX's: 300 arrives as 44. `main` may suspend whatever it returns.

See [The entry point](LANGUAGE_SPEC.md#the-entry-point) in the spec.

### Pattern matching

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

`match` is exhaustive: every case must be covered. To handle the rest at
once, use `case _`:

```saw
match msg {
    case Quit -> print("quit"),
    case _ -> print("got a message")   // any other case
}
```

An enum can also carry a raw integer backing (see the spec), which pins its
representation to one byte and lets it cross an ABI boundary.

See [Enums](LANGUAGE_SPEC.md#enums-algebraic-data-types) in the spec.

### Traits, generics, and dynamic dispatch

Conform a type to a trait with `extension Type: Trait`. Trait methods may carry
a default body, so a conforming type only implements what is unique to it.

```saw
trait Greeter {
    func name(&self) -> String
    func greet(&self) -> String { "Hello, {self.name()}!" }  // default body
}

extension Robot: Greeter {
    func name(&self) -> String { "R2" }
    // greet() inherited from the default; prints "Hello, R2!"
}
```

A trait can also be used as a boxed, dynamically-dispatched value with `any
Trait`:

```saw
trait Shape { func area(&self) -> Int }

func print_area(s: &any Shape) { print(s.area()) }  // dynamic dispatch
```

Generics are inferred at call sites from argument types, closure returns, and
default values, and they compile to specialized code:

```saw
func first<T: Copy>(v: &Vector<T>) -> T? { v.get(0) }

let names: Vector<String> = ["ada", "alan"]
let n = first(&names)                  // T = String, inferred
let lengths = names.map({ $0.len() })  // map<Int> solved from the closure
```

`Equatable`, `Comparable`, `Hashable`, and the copy policies can have their
bodies derived from the type's fields. Ask for it with `@synthesize`:

```saw
@synthesize
extension Version: Comparable {}   // lexicographic over the fields
```

See [Traits](LANGUAGE_SPEC.md#traits) and
[Generics](LANGUAGE_SPEC.md#7-metaprogramming) in the spec.

### Concurrency without async/await

There is no `async`/`await` keyword. Any function may suspend, and the rare
function that must not is marked `sync`, which the compiler checks. A
`TaskGroup` owns its child tasks and joins them when it goes out of scope.

```saw
import std.task.*        // yield_now lives in std.task

func work(n: Int) -> Int {
    yield_now()          // cooperative suspension point
    n * n
}

func main() {
    var group = TaskGroup()
    let a = group.spawn(work(3))
    let b = group.spawn(work(4))
    print(a.join() + b.join())   // 25
}
```

A suspending call works in any position: an operand, an argument, a receiver,
an interpolation, a `return` value. The compiler rewrites the statement into
evaluation-ordered steps, so left-to-right order and short-circuiting hold as
written. A single cooperative scheduler runs spawned tasks eagerly, backed by
an I/O reactor (kqueue or epoll). `TaskGroup(threads: N)` opts into multiple
threads, with `Send` checked at every spawn; the default stays single-threaded.

```saw
func report() -> Int {
    let total = work(3) + work(4)        // both operands suspend
    print("squared: {work(5)}")         // suspends inside an interpolation
    return total
}
```

See [Concurrency](LANGUAGE_SPEC.md#6-concurrency) in the spec.

### Memory and ownership

Saw has three words for what happens when a value is transferred:

- **Copy** — the compiler may duplicate it with nothing written at the site.
  Trivial types (copied bitwise) and the refcounted ones (`String`, `Arc`,
  `Data`) are both `Copy`.
- **NoCopy** — can only be moved (`File`, `Mutex`, `Map`, `Set`).
- **ExplicitCopy** — can be duplicated, but only with a spelled `.copy()`
  (`Vector`).

```saw
let a = Point(x: 1, y: 2)
let b = a              // trivial type: implicit copy, both valid

var v: Vector<Int> = [1, 2, 3]
var w = move v         // owning type: ownership transferred, v invalid
var u = w.copy()       // explicit, independent duplicate

let s1 = "hi"
let s2 = s1            // String: cheap refcount bump, both valid
```

A struct whose owning members are all `Copy` is `Copy` itself, with no
declaration needed. Values are destroyed last-in-first-out as they leave scope,
and a `deinit` is synthesized from the fields. You write one by hand only for a
raw resource such as a file descriptor.

References (`&T` for shared, `&var T` for exclusive) are parameters only, and
the compiler checks that an exclusive reference does not overlap any other
reference reaching the same value. References stay valid across suspension
points, and a reference you receive can be passed on to another function.

See [Memory Management](LANGUAGE_SPEC.md#4-memory-management) in the spec.

### Modules and imports

There are three import forms, and the standard library takes the same three as
any other module:

```saw
import std.time                    // binds the qualifier: time.Instant.now()
import std.time.*                  // every public name, bare: Instant.now()
import std.time.{Instant}          // Instant bare, plus the time qualifier
```

Imports are private: what an import binds is the file's, not its callers'. A
module's surface is what it declares `public`. Struct fields and extension
methods are private by default outside their defining module, and `public`
marks the API surface.

A curated core is available without an import (primitives, `Vector`/`Map`/`Set`,
`Optional`/`Result`/`Box`/`Arc`, the trait vocabulary, `print`/`panic`/`assert`,
the concurrency primitives, `StringBuilder`). Everything else (`File`, `Data`,
`Channel`, `Mutex`, `TcpStream`, and so on) needs an import, which also means
your own type named `File` or `IoError` never collides with the standard
library's.

See [Module System](LANGUAGE_SPEC.md#8-module-system) in the spec.

## Standard library

The standard library lives in `sawc/std/` and includes:

- **String** — immutable, reference-counted, always valid UTF-8.
- **StringBuilder** — growable builder; a fixed-capacity mode allocates
  nothing.
- **Vector / Map / Set** — the collection types, with `[...]`, `{k: v}`, and
  `{a, b}` literals.
- **Arc / Box** — atomic reference counting and owned heap allocation.
- **TaskGroup** — cooperative task groups (in the prelude). The rest of the
  concurrency surface — `Channel`, `Mutex`, `Once` — needs an import:
  `std.channel`, `std.mutex`, `std.once`.
- **std.data** — `Data`, copy-on-write byte buffer.
- **std.net** — `TcpListener` / `TcpStream`, owning and cooperative.
- **std.file** — `File` / `Directory` / `Path` / `Env`; every fallible
  operation returns a `Result`.
- **std.process** — run child processes cooperatively.
- **std.time** — `Instant` and `unix_timestamp` (hosted). `Duration` is in
  the prelude because `sleep` takes one.
- **std.cbor** — CBOR (RFC 8949) in its deterministic encoding profile.
- **Serialize / Deserialize** — over an `Encoder` / `Decoder` seam, with
  `@synthesize` derivation.

See [Standard Library Overview](LANGUAGE_SPEC.md#9-standard-library-overview)
in the spec for the full surface.

## Kernels and embedded

Saw is freestanding: the same language targets bare metal.

- **Pluggable allocation**: the allocator is a default type parameter on the
  allocating containers (`Vector<T, A = GlobalAllocator>`). A custom zero-sized
  allocator produces a distinct type that routes through its own allocator.
- **Memory-mapped I/O**: `UnsafeMemory<T>` is a typed view of memory at a fixed
  address, with volatile `read()`/`write()` for device registers.
- **No hidden allocations, enforced**: `--no-hidden-alloc` rejects the
  allocations the compiler would insert on its own authority, and names the
  spelling that does not allocate.
- **Global state**: `Atomic<Int>`, `SpinLock<T>`, `Mutex<T>`, and `Once<T>`
  cover the common shapes, all declarable as a bare `static`. Compound state
  whose consistency comes from a serialization argument uses
  `unsafe static var`, which makes every function that touches it declare
  `unsafe` too.
- **Compile-time layout checks**: `static_assert(sizeof<UartRegs>() == 8, "...")`
  fails the build when a register block's layout drifts.
- **C-ABI exports**: `@export("name")` gives a function an exact, unmangled
  symbol with the C calling convention.

```saw
import std.spinlock.*

static UART_BASE: Int = 0x1000_0000

struct UartRegs {
    data: UInt32
    status: UInt32
}

static_assert(sizeof<UartRegs>() == 8, "UartRegs layout drift")

static PENDING: SpinLock<Int>

@export("kernel_add")
func add(a: Int, b: Int) -> Int { a + b }

func boot() {
    print("uart at {} regs {}", UART_BASE, sizeof<UartRegs>())
}
```

Cross-compiling to a bare-metal target takes a triple and, where the part has
optional extensions, a feature list:

```bash
sawc kernel.saw -o kernel.o --freestanding --no-hidden-alloc \
    --target riscv32-unknown-none-elf --target-features +m,+a,+c
```

See [Interoperability](LANGUAGE_SPEC.md#10-interoperability) and
[Profiles](LANGUAGE_SPEC.md#profiles-hosted-and-freestanding) in the spec.

## Getting started

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

### Compile and run

```bash
# Compile a program (-o names the output; default is .build/<source>)
./.venv/bin/python sawc/sawc.py examples/hello.saw -o hello

# Run it
./hello
```

### Compiler options

```bash
./.venv/bin/python sawc/sawc.py <source.saw> [options]

Options:
  -o <file>          Output file name (default: .build/<source>)
  -c                 Compile to an object file only (no linking, no main required)
  -v                 Verbose output
  --emit-ir          Output LLVM IR only
  --emit-ast         Dump the typed AST for debugging
  --ids              With --emit-ast, include each node's stable node_id
  --emit-docs        Emit documentation JSON instead of code
  --emit-docs-all    Same, keeping private fields, methods, and inits
  --emit-frame-layout
                     Emit the coroutine frame layout report as JSON
  --emit-bt-table    Decode the linked task-backtrace table as JSON
  -O0                Disable optimization (default is an O1-style pass pipeline)
  --target <triple>  Cross-compile for a target triple (default: the host)
  --target-features <list>
                     LLVM subtarget features for --target (e.g. +m,+a,+c)
  --freestanding     Freestanding profile: no hosted std, unlinked object output
  --no-hidden-alloc  Reject allocations the compiler inserts that your source
                     does not name
  --runtime-build    Build a Saw runtime exporting the __saw_rt_* ABI
  --runtime-provider This package IS a runtime: it may export the __saw_rt_*
                     seams, each checked against sawc/rt/ABI.md
  --module-path NAME=DIR
                     Map a package name to a source directory (repeatable)
  -W <name>          Enable a warning category (repeatable; `-W all` for every
                     one). Warnings are off by default and never affect the
                     exit code. Categories: shadowed-qualifier
```

## Running tests

The compiler ships a test runner covering every example. `make test` calls bare
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

The suite can also be split across two machines over the network. See
[TESTING.md](TESTING.md) for the remote worker setup, the sandbox profile, and
application-level testing with `blade test`.

## Blade package manager

Saw includes Blade, a package manager written in Saw itself. It has a TOML
parser, a manifest model, a dependency resolver, a deterministic lockfile, git
fetching, and incremental builds.

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
./.build/blade clean           # remove build output
./.build/blade tree            # print the resolved dependency graph
./.build/blade add foo --path ../foo         # add a path dependency
./.build/blade add bar --git <url> --version ^1.0.0   # add a git dependency
```

### Dependencies

A project declares dependencies in its `Saw.toml`:

```toml
[dependencies]
mathx = { path = "../mathx" }
jsonx = { git = "https://github.com/u/jsonx", version = "^1.2.0" }
tiny  = "0.3.1"          # bare = EXACT pin (ranges need ^, ~, or >=)
```

`Saw.lock` is deterministic (packages sorted, no timestamps) and records
version, source, and git rev. An application commits it; a library does not,
because a library's resolution belongs to whoever depends on it. The source
layout decides which a package is: `src/main.saw` (or a root `main.saw`) builds
a program, `src/lib.saw` alone is a library.

`blade test` discovers `tests/*.saw` files, compiles and runs each, and reports
per-test timing. A test fails via `assert`/`panic` or a nonzero exit.

The version-requirement logic also lives as a standalone library package,
`libs/semver`, with its own `blade test` suite.

## Design philosophy

### Key differences from Rust

| Aspect | Rust | Saw |
|--------|------|-----|
| Transfer default | Move everything | `Copy` types duplicate silently (POD, `String`, `Arc`, `Data`, and any struct whose members are all `Copy`); everything else moves |
| Mutability | `let mut` | `var` |
| Optionals | `Option<T>` | `T?` (postfix) |
| References | `&T`, `&mut T` | `&T`, `&var T` |
| Initialization | `Type::new()` | `Type()` |
| Type extensions | Traits (impl blocks) | `extension` blocks |
| Modules | `mod`, `pub`, `use` | `module`, `public`, `import` |
| Error handling | `?` operator | `try`/`try?`/`try!` |
| Concurrency | `async`/`await` (colored) | colorless tasks (no keyword) |

### Key similarities to Swift

`let`/`var`, `guard let`, postfix `T?`, `extension` blocks, custom `init`s,
trailing closures, and `{}` string interpolation all mean what a Swift reader
expects. The divergences are ownership and effects, not surface syntax.

## Project structure

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
libs/                  # Real Saw library packages (semver, toml)
designs/               # Design briefs and the project tracker
LANGUAGE_SPEC.md       # Full language specification
TESTING.md             # Test suite documentation
```

## Current status

Saw is in active development. Implemented so far:

- **Types and generics** — algebraic data types with exhaustive `match`, enums
  that carry methods and an integer wire backing, generics with trait bounds
  and call-site type inference, const generic parameters, traits with default
  bodies and `any Trait` objects, overloading, and the `Printable` / `Error` /
  `Equatable` / `Comparable` / `Hashable` traits with `@synthesize` derivation.
- **Ownership** — the Copy trait family, synthesized destruction, places
  (`borrows` accessors that lend storage), whole-referent replacement through
  `&var`, and a `Result` that cannot be dropped by accident.
- **Concurrency** — colorless, with a cooperative scheduler over a precise I/O
  reactor, multi-threaded task groups, blocking-FFI offload, suspending calls
  in any expression position, and the whole error surface inside a task body.
- **Modules** — three import forms, member visibility over a curated prelude,
  import-scoped extensions, per-module type identity, and earned shadowing.
- **Systems work** — pluggable allocators, memory-mapped I/O, `static_assert`,
  C-ABI exports, `SpinLock<T>` and `unsafe static var` for global state,
  allocation-free formatting, and `--no-hidden-alloc`.
- **Tooling** — source-location literals, doc comments with `--emit-docs`
  extraction, opt-in compiler warnings, reachability-scoped code generation with
  a dead-stripped link, and the Blade package manager, which is self-hosting.

[LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) is the authoritative language reference.
When it and the compiler disagree, the compiler wins and the spec is the bug.

## Contributing

Saw is an experimental language. Issues and pull requests are welcome; start
from [LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) and the design briefs in `designs/`.

## License

Saw is licensed under the [Apache License 2.0 with LLVM
Exceptions](LICENSE) (SPDX: `Apache-2.0 WITH LLVM-exception`).

In plain terms: use, modify, and redistribute freely, with an explicit
patent grant from contributors. The LLVM exception means programs you
compile with `sawc` are entirely yours: the standard-library code
embedded in your binaries carries no attribution requirements.

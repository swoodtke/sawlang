# Saw

A systems programming language with Rust-style memory safety and Swift-style
syntax. It has no garbage collector and no lifetimes, and it compiles for bare
metal as well as for a hosted target.

[LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) is the language reference. For testing and
contribution workflows, see [TESTING.md](TESTING.md).

## Design

- **Memory safety without a garbage collector or lifetimes.** There are no
  null pointers. Ownership is checked where a value is transferred, and the Law
  of Exclusivity allows many readers or one writer, never both.
- **Deterministic destruction.** Values are destroyed last-in-first-out as they
  leave scope, and the `deinit` is written for you from the type's fields. A
  local that lives across a suspension still dies at the end of its own scope.
- **Checked integers.** Overflow, a bounds violation and a shift out of range
  panic rather than wrap. A conversion between integer types is written
  wherever the value lands.
- **Visible allocation.** Containers carry their allocator as a type parameter,
  and an allocation that fails returns `Result<_, AllocError>`.
  `--no-hidden-alloc` rejects every allocation the source does not name.
- **Errors are values.** A function that can fail returns `Result<T, E>`, and a
  `Result` cannot be dropped by accident. There are no exceptions.
- **Colorless concurrency.** There is no `async`/`await`. Any function may
  suspend, and the one that must not is marked `sync`. Cooperative tasks share
  one scheduler, and `Thread.spawn` starts an OS thread.
- **A declared unsafe surface.** A raw pointer or a typed view of a fixed
  address is an `Unsafe*` type, and a function that names one is declared
  `unsafe`. There are no `unsafe` blocks.
- **Bare metal is a first-class target.** The freestanding profile links no
  libc. SawOS, a capability-based microkernel written in Saw, is built this way
  and lives in its own repository. It builds with `sawc` v0.21.0 and boots
  under QEMU on riscv32 and arm64.
- **A binary carries the program, not the standard library.** An import makes a
  module available to type-check against. Code generation emits only what
  `main` and the `@export`s reach, and the link strips the rest.
- **Swift-style syntax, specialized generics.** `let`/`var`, `extension`
  blocks, `T?` optionals, `guard let`, trailing closures and `{}` interpolation.
  Generics and traits compile to specialized machine code.

## Quick example

```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    static func origin() -> Point {
        Point(x: 0, y: 0)
    }

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
    print(p.magnitude())  // prints: 25

    p.translate(1, 1)
    print(p.x)  // prints: 4

    print(Point.origin().magnitude())  // prints: 0
}
```

## A tour of the language

Each section links to the spec for the rules and the edge cases.

### Optionals instead of null

An absent value is `T?`, and `None` spells one.

```saw-fragment
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

A function that can fail returns `Result<T, E>`. You handle it with `try`,
`try!`, `try?`, a `match`, or an inline `catch`.

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
    print(n)                         // prints: 42

    let value = try parse(true) catch { 0 }   // fallback on error
    print(value)                              // prints: 0

    match parse(false) {
        case Ok(parsed) -> print(parsed),     // prints: 42
        case Err(e) -> print(e.message)
    }
}
```

A bare `try` propagates the error. `try!` panics with it, and `try?` gives an
`Optional`. When the callee fails with a different type than your signature
names, a routing clause (not built in `sawc` yet, SL-884) says where the error
goes:

```saw-fragment
enum ConfigError {
    case Alloc(e: AllocError),
    case Parse(e: ParseError)
}

func build() -> Result<Config, ConfigError> {
    let buf = try(as ConfigError.Alloc) alloc_buffer(4096)
    let cfg = try(as ConfigError.Parse) parse(buf)
    return cfg
}
```

Writing a fallible call as a bare statement is a compile error. Handle the
`Result`, or write `let _ =` to discard it explicitly.

```saw-error
// error-rule: result.discarded
// error-contains: silently discarded
func write(body: String) -> Result<Void, String> { return }

func main() {
    write("body")
    // error: the result of `write` is `Result<Void, String>` and is silently
    //        discarded: handle it (`match` it, `try` or `try!` it, or return
    //        it), or write `let _ = ...` to discard it explicitly
}
```

A constructor fails the same way. An `init` declares either the type it builds
or `Result<Type, E>`:

```saw-fragment
extension Config {
    init(budget: Int, ceiling: Int) -> Result<Config, ConfigError> {
        if budget > ceiling { return ConfigError.TooLarge(bytes: budget) }
        return Config(budget: budget)
    }
}

let cfg = try Config(budget: n, ceiling: 4096)
```

An operation whose failures have mixed sources returns an enum with a case per
source:

```saw-fragment
public enum ChannelError {
    case Closed,
    case Cancelled,
    case Alloc(e: AllocError),
    case System(e: SystemError)
}
```

See [Error Handling](LANGUAGE_SPEC.md#5-error-handling) in the spec.

### main returns the exit status

`main` may return `Void`, `Int`, `Result<Void, E>` or `Result<Int, E>`. An
`Err` writes the error on standard error and exits 1.

```saw
import std.file
import std.path.{Path}
import std.systemerror.{SystemError}

func main() -> Result<Void, SystemError> {
    var config = try file.File.open(Path(s: "saw.toml"))
    let text = try config.read()
    print("read {text.len()} bytes")
    return
}
// With no saw.toml: writes `error: open "saw.toml" failed (not found)` on
// standard error, exits 1.
```

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

`match` is exhaustive. To handle the rest at once, use `case _`:

```saw-fragment
match msg {
    case Quit -> print("quit"),
    case _ -> print("got a message")   // any other case
}
```

A type may name itself when the cycle passes through a heap indirection
(`Vector`, `Box`, `Map`), so a tree is written directly:

```saw
enum Json {
    case Number(n: Int),
    case Text(s: String),
    case Items(items: Vector<Json>)
}
extension Json: NoCopy {}
```

See [Enums](LANGUAGE_SPEC.md#enums-algebraic-data-types) and
[Recursive types](LANGUAGE_SPEC.md#recursive-types) in the spec.

### Traits, generics, and dynamic dispatch

Conform a type to a trait with `extension Type: Trait`. A trait method may
carry a default body.

```saw
trait Greeter {
    func name(&self) -> String
    func greet(&self) -> String { "Hello, {self.name()}!" }  // default body
}

struct Robot { id: Int }

extension Robot: Greeter {
    func name(&self) -> String { "R2" }
    // greet() inherited from the default
}

func main() { print(Robot(id: 1).greet()) }  // prints: Hello, R2!
```

`any Trait` is a dynamically dispatched value:

```saw
trait Shape { func area(&self) -> Int }

func print_area(s: &any Shape) { print(s.area()) }  // dynamic dispatch
```

Generics are inferred at call sites from argument types, closure returns, and
default values, and they compile to specialized code:

```saw-body
func first<T: Copy>(v: &Vector<T>) -> T? { v.get(0) }

let names: Vector<String> = ["ada", "alan"]
let n = first(&names)                       // T = String, inferred
let lengths = try! names.map({ s in s.len() })  // map<Int> solved from the closure
```

Constructors infer the same way, and a type annotation is one of the things
they infer from:

```saw-body
struct Pair<A, B> { a: A, b: B }

let p = Pair(a: 1, b: "port")     // Pair<Int, String>
let v: Vector<Int> = Vector()     // the element type, written once
```

A trait can require a constructor, and a generic builds `T(...)` through it:

```saw
trait Make { init(seed: Int) -> Self }

struct Tally { seed: Int }        // its memberwise Tally(seed:) satisfies Make
extension Tally: Make {}

func build<T: Make>(n: Int) -> T { T(seed: n) }

func main() { print(build<Tally>(3).seed) }   // prints: 3
```

`@synthesize` derives `Equatable`, `Comparable`, `Hashable` and the copy
policies from the type's fields:

```saw
struct Version { major: Int, minor: Int }

@synthesize
extension Version: Equatable {}

@synthesize
extension Version: Comparable {}   // lexicographic over the fields

func main() {
    print(Version(major: 1, minor: 2) < Version(major: 1, minor: 3))
    // prints: true
}
```

See [Traits](LANGUAGE_SPEC.md#traits),
[Generics](LANGUAGE_SPEC.md#7-metaprogramming), and
[Functions](LANGUAGE_SPEC.md#functions) (overloading) in the spec.

### Concurrency without async/await

Any function may suspend, and the rare function that must not is marked
`sync`. A `TaskGroup` owns its child tasks and joins them when it goes out of
scope.

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
    print(a.join() + b.join())   // prints: 25
}
```

`group.spawn` hands back a `Task<T>`, and `join()` takes the result once. A
suspending call works in any expression position, with evaluation order and
short-circuiting kept:

```saw-fragment
func report() -> Int {
    let total = work(3) + work(4)        // both operands suspend
    print("squared: {work(5)}")         // suspends inside an interpolation
    return total
}
```

`TaskGroup(threads: N)` opts into multiple threads. When every live task is
parked and nothing can send, the scheduler aborts with a task dump instead of
hanging. For a dedicated OS thread, such as a long blocking C call,
`Thread.spawn` returns a `Result<Thread<T>, SystemError>`, and `join()` blocks:

```saw
extern "C" {
    blocking func compress(level: Int32) -> Int
}

func main() {
    var worker = try! Thread.spawn { compress(9) }   // blocks its own thread
    print("compressed {worker.join()} bytes")
}
```

A thread's body is a `sync` context, and a spawned brace captures nothing
implicitly. One operation can have a default body for tasks and a `blocking`
twin for threads:

```saw-fragment
extension Mailbox {
    /// Takes the next letter: a task parks until one arrives, a thread blocks.
    public func take(&self) -> Letter { ... }
    public func take(&self) blocking -> Letter { ... }
}
```

Every handle has a written fate: a `Thread.spawn` handle must reach `join()` or
`detach()` on every path, and a `Task.spawn` handle `join()`, `detach()` or
`cancel()`. A task spawned without a group can outlive its spawner:

```saw-fragment
func reindex(catalog: Catalog) -> Int { ... }

func main() {
    let indexing = Task.spawn(reindex(catalog))
    serve_requests()
    print("indexed {indexing.join()} entries")
}
```

At `main`'s return, every task still live is cancelled and joined.

See [Concurrency](LANGUAGE_SPEC.md#6-concurrency),
[Tasks and Channels](LANGUAGE_SPEC.md#tasks-and-channels), and
[Task backtraces](LANGUAGE_SPEC.md#task-backtraces-design-158) in the spec.

### Memory and ownership

A transfer is one of three things:

- **Copy**: the compiler duplicates it with nothing written at the site
  (trivial types, and refcounted ones such as `String`).
- **NoCopy**: it can only be moved (`File`, `Mutex`).
- **ExplicitCopy**: it can be duplicated, but only with a spelled `.copy()`
  (`Vector`).

```saw-body
struct Point { x: Int, y: Int }

let a = Point(x: 1, y: 2)
let b = a              // trivial type: implicit copy, both valid
print(b.x + a.y)       // prints: 3

var v: Vector<Int> = [1, 2, 3]
var w = move v         // owning type: ownership transferred, v invalid
var u = w.copy()       // explicit, independent duplicate
print(u.len())         // prints: 3

let s1 = "hi"
let s2 = s1            // String: cheap refcount bump, both valid
print("{s1}{s2}")      // prints: hihi
```

References (`&T` for shared, `&var T` for exclusive) are parameters only, and
the compiler checks that an exclusive reference does not overlap any other
reference to the same value. A `borrows` method lends storage instead of a
value, which is how `v[i] += 1` writes a `Vector` element where it sits. An
unnamed lend lasts for its statement, and a named one
(`if var e = m.find(&k) { e.count += 1 }`) for the block its binding opens.

```saw-fragment
extension Document {
    // A read-only lend: callers reach the section where it sits, and nothing
    // they write reaches this storage.
    public func section(&self, name: String) borrows -> &Section? {
        if let i = self._section_index(name) {
            lend self.sections[i]
        } else {
            return None
        }
    }
}
```

`sawc` still accepts the `borrow` prefix v0.18.0 wrote on every unnamed lend.
`-W borrow-prefix` warns where it is redundant, and `sawc fix FILE...` drops
it. A `borrows struct` holds a lent place for exactly one `for` statement, so
the loop borrows the collection for its whole run:

```saw-error
// error-rule: loan.window-root
// error-contains: holds `v` shared until the window closes
func main() {
    var v: Vector<Int> = [1, 2, 3]
    var seen = 0
    for x in v.iter() {
        seen = seen + x
        let _ = v.push(9)
    }
    print(seen)
}
// error: `v` is borrowed exclusively here while the window of `iter` opened at
//        6:14 holds `v` shared until the window closes; a window charges its
//        whole root until it closes, so the root is reached only through the
//        window's binding
```

A method can also end its receiver. `consumes` says so at the declaration, and
`move` says so at the call:

```saw
struct Builder { items: Vector<Int> }
extension Builder: NoCopy {}

extension Builder {
    func finish(&var self) consumes -> Vector<Int> {
        move self.items
    }
}

func main() {
    var b = Builder(items: [1, 2, 3])
    let items = (move b).finish()   // `b` is moved-from past this expression
    print(items.len())              // prints: 3
}
```

See [Memory Management](LANGUAGE_SPEC.md#4-memory-management),
[Consuming method receivers](LANGUAGE_SPEC.md#consuming-method-receivers-consumes)
and [Places](LANGUAGE_SPEC.md#places-borrows-and-lend) in the spec.

### Modules and imports

There are three import forms, and the standard library takes the same three as
any other module. Each binds exactly what it names, so write both the first
and the second or third line when you want the qualifier and the bare name.

```saw
import std.time                    // binds the qualifier: time.Instant.now()
import std.time.*                  // every public name, bare: Instant.now()
import std.time.{Instant}          // Instant bare, and only Instant
```

Imports are private, and a module's surface is what it declares `public`.
`public import` re-exports a name on every form. A declaration can also be
`public(package)` or `public(parent)`. A struct's fields take the struct's
visibility, and `private` narrows one field back down:

```saw
public struct Account {
    name: String            // public, like the struct
    private balance: Int    // this module only
}
```

A curated core (primitives, `Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/
`Arc`, `print`/`panic`/`assert`, the concurrency primitives and
`StringBuilder`) needs no import. Everything else, such as `File` and
`Channel`, does.

See [Module System](LANGUAGE_SPEC.md#8-module-system) in the spec.

### Five smaller rules

- **A newline separates statements, and so does `;`.** A `;` that separates
  nothing is an error ([spec](LANGUAGE_SPEC.md#statement-boundaries)).
- **A method's kind is declared.** A method with no receiver is `static func`,
  called on its type, `Point.origin()`
  ([spec](LANGUAGE_SPEC.md#static-methods)).
- **Shadowing must be earned.** Reusing an enclosing name is an error unless
  the initializer mentions it: `if let x = x` compiles
  ([spec](LANGUAGE_SPEC.md#variables-and-mutability)).
- **Source locations are literals.** `#file`, `#line` and `#function` are
  filled in at compile time, and panics carry a `panic at FILE:LINE:` prefix
  ([spec](LANGUAGE_SPEC.md#source-location-literals)).
- **Doc comments are checked.** `///` documents the declaration that follows,
  `//!` the file. `--emit-docs` writes them as JSON (not yet in `sawc`,
  SL-880) ([spec](LANGUAGE_SPEC.md#doc-comments)).

## Standard library

The standard library lives in `std/`. The prelude needs no import; the other
modules do.

- **String**, **StringBuilder**: immutable, reference-counted UTF-8 text, and a
  growable builder whose fixed-capacity mode allocates nothing.
- **Byte**: `type Byte = UInt8`, the type of every byte a std API hands back.
  It reads as its `UInt8`, and a plain integer never becomes one implicitly
  (not enforced by `sawc` yet, SL-1012).
- **Scalar**: a Unicode scalar value, checked at construction:

  ```saw-body
  for ch in "héllo".scalars() {
      print("{} {}", ch, ch.value())
  }
  // One line per scalar.
  // prints: h 104
  // prints: é 233
  // prints: l 108
  // prints: l 108
  // prints: o 111
  ```

- **Float and text**: `f.to_string()` gives the shortest decimal that reads
  back as `f`, and `s.to_float()` the nearest `Float` to the string. Both are
  pure Saw, so they work freestanding.
- **Vector / Map / Set**, **Arc / Box**: the collections, with `[...]`,
  `{k: v}` and `{a, b}` literals, and atomic reference counting.
- **TaskGroup** (prelude), **std.channel**, **std.mutex**, **std.once**:
  cooperative task groups, channels, and the synchronization primitives.
- **std.data**: `Data`, a copy-on-write byte buffer.
- **std.net**: `TcpListener` and `TcpStream`. `accept`, `read`, `read_into` and
  `connect` take an optional `timeout: Duration` and answer `Timed<T>`.
  `listen` takes a labelled `reuse_address` (on by default), and `no_delay` is
  on by default with `set_no_delay(on:)` to change it.
- **std.file**, **std.directory**, **std.path**, **std.env**: the filesystem
  and environment; every fallible operation returns a `Result`.
- **std.signal**: OS signals as suspending events. `SignalWatch.watch(which:)`
  takes a `Signal` case such as `.Terminate` and returns a `Result` holding a
  watch whose `next()` suspends until the signal arrives.
- **std.process**, **std.time**: child processes, and `Instant` and
  `unix_timestamp`.
- **std.json**, **std.cbor**, **std.serialize**: `JsonValue` with `parse` and
  `to_json_string`, deterministic CBOR (RFC 8949), and the `Serialize` /
  `Deserialize` seam with `@synthesize` derivation.

See [Standard Library Overview](LANGUAGE_SPEC.md#9-standard-library-overview)
in the spec for the full surface.

## Kernels and embedded

The same language targets bare metal under the freestanding profile. The
allocator is a default type parameter on the allocating containers
(`Vector<T, A = GlobalAllocator>`), `UnsafeMemory<T, Use>` is a typed view of
memory at a fixed address (a `Device` view's reads and writes are volatile),
and `Atomic<Int>`, `SpinLock<T>`, `Mutex<T>` and `Once<T>` declare as a bare
`static`. `static_assert` fails the build when a register block's layout
drifts, and `@export("name")` gives a function an unmangled C symbol.
`@section("name")` places a definition in a named section, and `@align(N)`
sets the alignment of a local or a `static`. A generic parameter can carry a
value (`FixedBuf<const N: Int>`), and `[0; N]`
spells a zeroed buffer.

The `{}` form of `print`, `panic` and `assert` allocates nothing, so a panic
can still say what happened when the allocator is what failed.
`--no-hidden-alloc` rejects the allocations the compiler would insert on its
own authority and names the spelling that does not allocate.

```saw
import std.spinlock.*

static UART_BASE: Int = 0x1000_0000

struct UartRegs {
    data: UInt32
    status: UInt32
}

static_assert(sizeof<UartRegs>() == 8, "UartRegs layout drift")

static PENDING: SpinLock<Int>

@align(64)
static DMA_WINDOW: [UInt8; 256] = [0; 256]

@export("kernel_add")
func add(a: Int, b: Int) -> Int { a + b }

func boot() {
    print("uart at {} regs {}", UART_BASE, sizeof<UartRegs>())
}
```

`sawc build --freestanding` writes a freestanding object for
`aarch64-unknown-none-elf`, `riscv32-unknown-none-elf` and
`xtensa-esp-unknown-elf` (the ESP32-S3). A riscv32 build reads:

```bash
sawc kernel.saw -o kernel.o --freestanding --no-hidden-alloc \
    --target riscv32-unknown-none-elf --target-features +m,+a,+c
```

Without `+m`, integer formatting would call a library routine; without `+a`,
atomics call `__atomic_*` routines your kernel supplies, and `SpinLock` is
refused. On aarch64 the profile defaults to `-neon,-fp-armv8`; pass
`+neon,+fp-armv8` once your boot code enables `CPACR_EL1.FPEN`.

See [Interoperability](LANGUAGE_SPEC.md#10-interoperability),
[Module-level statics](LANGUAGE_SPEC.md#module-level-statics) and
[Profiles](LANGUAGE_SPEC.md#profiles-hosted-and-freestanding) in the spec.

## Getting started

### Requirements

- Python 3.14, standard library only (the build and test tools are Python)
- Clang 15 or later (LLVM opaque pointers), which compiles and links `sawc`'s
  output
- HTTPS to `blobs.sawlang.com` on the first build, which fetches the bootstrap
  seed

### Compile and run

```bash
# Compile a program (-o names the output; default is .build/<source>).
# The first run builds sawc itself.
bin/sawc tests/corpus/hello.saw -o hello

# Run it
./hello
```

### Putting `sawc` and `blade` on your PATH

`make install` builds Blade (with `sawc`) and symlinks three shims, `sawc`,
`sawc0` and `blade`, onto a prefix (`~/.local/bin` by default):

```bash
make install                        # -> ~/.local/bin
make install PREFIX=/usr/local/bin  # -> somewhere else
```

The shims exec this checkout. Before each run `sawc` has
`compiler/tools/build.py` bring its build up to date, so an edit or a `git pull`
changes what the name means with no reinstall. `sawc0` is v0.18.0's compiler,
the Python Stage 0 this tree no longer holds: the shim forwards to a v0.18.0
checkout, the one `SAWLANG_V0_ROOT` names or else one fetched and cached.
`blade` runs the `sawc` beside it unless `SAWC` names another compiler. To
install nothing, put `<checkout>/bin` on your `PATH`.

`sawc --version` prints the release.

### Linux

`sawc` builds and runs on Linux aarch64, and it cross-builds for Linux x86_64.
On a Mac the Linux builds run in a Debian 12 Lima VM that
`tools/lima/sawlang-linux.yaml` pins and `tools/linux.py` drives:

```bash
limactl start --name=sawlang-linux tools/lima/sawlang-linux.yaml   # once
./.venv/bin/python tools/linux.py status
./.venv/bin/python tools/linux.py run-lane --arch aarch64   # or x86_64, under Rosetta
```

`SAWC_CLANG` names the clang to use; otherwise `compiler/tools/build.py` tries
each `clang-NN` on `PATH` (newest first), then `clang`, then Homebrew's LLVM.
Apple's clang has no RISC-V backend, so a Mac needs `brew install llvm` for
riscv32.

### Compiler options

`sawc FILE.saw -o OUT` is `sawc build`. `sawc --help` lists every subcommand
and flag, including one subcommand per compiler stage (`lex`, `parse`,
`resolve`, `typecheck`, `mir`, `eval`, `borrowck`, `drops`, `mono`, `coro`).

```bash
sawc build [-O0 | -O1 | -O2 | -Os | -Oz] [-g | -g0] [-c] [--target TRIPLE]
           [--target-features FEATURES] [--freestanding] [--runtime]
           [--module-path NAME=DIR]... (FILE [-o OUT] | --emit-ll FILE)
sawc fix [--check] FILE...
sawc runtime (--out DIR | --emit-ll FILE)
sawc tools [--target TRIPLE]
sawc --version
```

The `-O` level goes to clang and is `-O0` when none is given. `-c` writes an
object and links nothing. `--freestanding` writes an ELF object under the
freestanding profile, rooted at its `@export`s. `--runtime` builds a program
that is its own runtime, defining every `__saw_rt_*` seam it reaches (checked
against `runtime/ABI.md`). `sawc runtime` builds the hosted runtime from
`runtime/`. `sawc tools` prints the `clang`, `ld.lld` and `objcopy` recorded for
a target, one `NAME PATH` line each. The spec documents some flags `sawc` does not take yet: the `-W`
categories other than `borrow-prefix` (SL-879) and `--emit-docs` (SL-880).

## Running tests

`./build.sh test` runs the per-patch gate, the entry point the merge server
runs. [TESTING.md](TESTING.md) describes the gate's parts and the test
directives.

```bash
./build.sh test                                  # every part
./build.sh test --changed-since main             # what a branch's change needs
./.venv/bin/python compiler/tests/run.py --only units,parser   # named steps
```

## Blade package manager

Blade is the Saw package manager, written in Saw. It has a TOML parser, a
manifest model, a dependency resolver, a deterministic lockfile, git fetching,
and incremental builds. Blade and its `libs/` packages build with `sawc`
(blade/README.md).

```bash
make blade                     # builds with bin/sawc -> .build/blade

./.build/blade new myproject   # scaffold a new project
./.build/blade build           # resolve deps + compile (incremental; --force to rebuild)
./.build/blade build --out-dir out --module-path extra=../extra
                               # build into out/ and pass a module root to sawc
./.build/blade build --target riscv32-unknown-none-elf --linker-script app.ld
                               # an [sos] image, linked with app.ld
./.build/blade update          # re-resolve dependencies and rewrite Saw.lock
./.build/blade run             # build and run
./.build/blade test            # compile and run the project's tests/
./.build/blade clean           # remove build output
./.build/blade tree            # print the resolved dependency graph
./.build/blade add foo --path ../foo         # add a path dependency
./.build/blade add bar --git <url> --version ^1.0.0   # add a git dependency
```

Blade refuses a flag it does not know, a flag with no value and a stray word
on every command (`blade build --targt x` is an error, not a host build), and
`blade <command> --help` and `blade help <command>` print the help.

A project declares dependencies in its `Saw.toml`:

```toml
[dependencies]
mathx = { path = "../mathx" }
jsonx = { git = "https://github.com/u/jsonx", version = "^1.2.0" }
tiny  = "0.3.1"          # bare = EXACT pin (ranges need ^, ~, or >=)
```

`Saw.lock` is deterministic and records version, source, and git rev. An
application commits it; a library does not. `libs/semver` and `libs/imgformat`
are standalone library packages with their own `blade test` suites.

## Project structure

```
compiler/              # sawc, the compiler, written in Saw: one package per stage
                       # (lex, parse, resolve, typecheck, mir, ..., llvm), the
                       # driver, the bootstrap seed's manifest, tools/ and tests/
std/                   # Standard library (.saw files)
runtime/               # The runtime, authored in Saw (ABI.md is its contract)
bin/                   # `sawc`, `sawc0` and `blade` shims (see `make install`)
tests/corpus/          # The corpus programs, measured on every patch
blade/                 # Blade package manager (written in Saw)
libs/                  # Real Saw library packages (semver, toml, imgformat)
designs/               # Design briefs and the project tracker
LANGUAGE_SPEC.md       # Full language specification
GRAMMAR.md             # The formal grammar
TESTING.md             # Test suite documentation
```

## Current status

Saw is in active development. Implemented so far:

- **Types and generics**: algebraic data types, enums with an integer wire
  backing, generics with trait bounds and inference, const generics, traits with
  default bodies and `any Trait`, overloading, `@synthesize`.
- **Ownership**: the Copy trait family, synthesized destruction, places, and a
  `Result` that cannot be dropped by accident.
- **Concurrency**: a cooperative scheduler over an I/O reactor, multi-threaded
  task groups, `Thread.spawn`, blocking-FFI offload.
- **Modules**: three import forms, member visibility, import-scoped extensions.
- **Systems work**: pluggable allocators, memory-mapped I/O, `static_assert`,
  C-ABI exports, `--no-hidden-alloc`.
- **Tooling**: checked doc comments, a dead-stripped link, and the self-hosting
  Blade package manager. `--emit-docs` and the `-W` warning categories other
  than `borrow-prefix` are not yet in `sawc` (SL-880, SL-879).

LANGUAGE_SPEC.md is the authoritative language reference. Where `sawc` doesn't
yet do what it says, the spec marks the gap with its tracker issue.

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

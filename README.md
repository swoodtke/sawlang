# Saw

[![CI](https://github.com/swoodtke/claudes-lang/actions/workflows/ci.yml/badge.svg)](https://github.com/swoodtke/claudes-lang/actions/workflows/ci.yml)

A systems programming language with Rust-style memory safety and Swift-style
syntax. It has no garbage collector and no lifetimes, and it compiles for bare
metal as readily as for a hosted target.

## What Saw gives you

- **Bare metal is a target, not a port.** The freestanding profile links no
  libc and rests on a frozen set of runtime seams the environment supplies.
  Allocators are a type parameter, `UnsafeMemory<T, Device>` gives a register
  block a typed view, `static_assert` fails the build when a layout drifts, and
  `@export` gives a function an exact C symbol. The SOS kernel in this repo is
  built that way and boots under QEMU on every `make sos-test`.
- **Memory safety without a garbage collector or lifetimes.** There are no null
  pointers. Ownership is checked where a value is transferred, and mutable
  aliasing is caught at compile time by the Law of Exclusivity: many readers or
  one writer, never both at once. There is nothing to annotate — Saw has no
  lifetime parameters.
- **Allocation is visible in the type.** The allocating containers carry their
  allocator as a type parameter, and the only implicit copies are cheap ones —
  a bitwise copy or a refcount bump — so no assignment is secretly O(n).
  Duplicating a `Vector` is a visible `.copy()`. `sawc --no-hidden-alloc` turns the
  guarantee into a check: every allocation must be named by the expression or
  by a type you wrote, and the compiler allocating on its own authority is a
  compile error.
- **Destruction is deterministic.** Values are destroyed last-in-first-out as
  they leave scope, and the `deinit` is written for you from the type's fields.
- **A binary carries the program, not the standard library.** An import makes a
  module available to type-check against; it does not put the module in your
  output. Code generation walks out from `main` and the `@export`s and emits
  only what it reaches, and the link then strips whatever is left over. A
  four-line program links at about 63 KB, where it used to link at 218 KB.
  `examples/link_dead_strip.saw` opens its own binary and fails if it grows past
  a fixed bound.
- **Swift-style syntax, monomorphized generics.** `let`/`var` bindings,
  `extension` blocks, `T?` optionals, trailing closures — over generics and
  traits that compile to specialized machine code rather than dispatching at
  runtime.

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
        case Ok(parsed) -> print(parsed),
        case Err(e) -> print(e.message)
    }
}
```

A `Result` cannot be dropped by accident. Writing a failable call as a bare
statement is a compile error, because the failure it reports would go nowhere:

```saw
stream.write(body)
// error: result of `write` is `Result<Void, IoError>` and is silently
//        discarded
// hint: handle it — `match` it, `try`/`try!`/`try?` it, or return it — or
//       write `let _ = ...` to discard it explicitly
```

Consume it, or say you meant to drop it with `let _ = stream.write(body)`.
Optionals and every other type stay freely discardable; the rule is about
failures, and a `Result` a caller may always ignore should not have been a
`Result`.

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

### Enums Carry Methods and Wire Values

An enum takes extensions on the same terms as a struct: methods, static methods,
and hand-written trait conformances. An error type is normally an enum.

```saw
enum SysError: UInt8 {
    case Ok = 0,
    case BadHandle = 3,
    case NoMemory = 12
}

extension SysError {
    func describe(&self) -> String {
        match self {
            case Ok -> "ok",
            case BadHandle -> "bad handle",
            case NoMemory -> "out of memory"
        }
    }
}

extension SysError: Printable {
    func format(&self, into: &var StringBuilder) { into.append(self.describe()) }
}
extension SysError: Error {}
```

The `: UInt8` is a raw backing. It pins the representation, so the enum is one
byte with exactly the values written above, and it can cross an ABI boundary:

```saw
let raw = SysError.NoMemory as UInt8      // 12; total, the enum is its tag
if let e = SysError.from(raw: byte) {     // partial; None on an unknown value
    print("decoded {e}")
}
```

Every case states its own value — nothing auto-increments, so reordering the
cases cannot renumber them. A backed enum is a legal field type in a struct read
through `UnsafeMemory`, which lets a wire-format view name a flags byte by its
type instead of carrying a bare integer and a comment.

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

`Equatable`, `Comparable`, `Hashable` and the copy policies can have their body
derived from the type's fields. Ask for it with `@synthesize`:

```saw
struct Version {
    major: Int,
    minor: Int,
    patch: Int
}

@synthesize
extension Version: Comparable {}   // lexicographic over the three fields
```

A conformance you write derives nothing without the marker, so adding a field
never changes `==` or `compare` behind your back. Trivial (POD) structs and
payload-free enums are the exception: they are already `Equatable` and
`Hashable` with no declaration at all, and nothing to mark.

The marker also decides whether a move-only type keeps its comparison
operators. `equals` and `compare` receive the second operand by value, so a
hand-written body may consume it, while `==` and `<` pass a reference — on an
`ExplicitCopy` or `NoCopy` type the compiler refuses the operator and points at
`a.equals(move b)` or the `@synthesize`d conformance. A derived body never
consumes its operand, so a `@synthesize`d move-only type compares normally.

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
func first<T: Copy>(v: &Vector<T>) -> T? { v.get(0) }

let names: Vector<String> = ["ada", "alan"]
let n = first(&names)              // T = String, inferred
let squares = names.map({ $0.len() })   // map<Int> solved from the closure
```

The `Copy` bound is not about inference. `v.get(0)` hands back a place rather
than a value, so reading one out inside a generic body is legal only where the
bounds prove every instantiation can be copied — the compiler asks once, in the
body, instead of at one unlucky call site.

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
//! Spans of time.

/// A span of time, held as whole nanoseconds.
struct Duration {
    /// Nanoseconds in the span.
    public nanos: UInt64
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

There is a second spelling that takes the values as arguments:

```saw
print("point = {}", p)
print("{} of {} frames used", used, total)
```

The two produce the same bytes. They differ in what happens underneath, which
is the next section.

### Formatting Without Allocating

`"{p}"` produces a `String`, and a `String` lives on the heap. That is fine
until the code doing the formatting is the code reporting that the heap is
gone — a panic from a refused allocation, or a kernel that has no allocator to
begin with.

The `{}` form allocates nothing. Literal pieces of the format string are
constants, integers are rendered into stack scratch, and a `Printable` value
streams through its own `format` into a fixed-capacity builder over stack
scratch:

```saw
print("addr {} size {}", base, size)   // no heap, anywhere
```

Placeholders and arguments are matched at compile time:

```saw
print("{} and {}", 1)
// error: `print` format string has 2 placeholders but 1 argument was given
```

`panic` and `assert` take the same arguments and assemble their message the same
way, so a panic still says what happened with the allocator refusing everything:

```saw
panic("out of {}: wanted {}, had {}", "frames", 64, 3)
// panic at slab.saw:41: out of frames: wanted 64, had 3
```

Whether your own type formats without allocating depends on how you write
`format`: `into.append(...)` calls do not allocate, and neither does forwarding
to a field's own `format`; `into.append("{self.x}")` does.

Compiling with `--no-hidden-alloc` turns the difference between the two
spellings into a compile error rather than a habit to keep.

For formatting you drive yourself, `std.fixedbuf` gives you a builder over
inline storage, sized by the type:

```saw
import std.fixedbuf.*

var out = FixedStringBuilder<64>()
out.append("n = ")
out.append(42)
print(out.as_string())      // prints: n = 42
```

`FixedStringBuilder<64>` holds its 64 bytes inline — on the stack, in a field,
wherever the value lives. Content that does not fit is cut on a UTF-8 boundary
and marked with `…`, and `is_truncated()` says so; a shortened message never
reads as a complete one.

### Sizes in the Type

A generic parameter can carry a value instead of a type:

```saw
struct FixedBuf<const N: Int> {
    data: [UInt8; N]
}

extension FixedBuf<N> {
    init() -> FixedBuf<N> { FixedBuf<N>(data: [0; N]) }
    func capacity(&self) -> Int { N }
}

var small = FixedBuf<16>()
var big   = FixedBuf<256>()
```

`FixedBuf<16>` and `FixedBuf<256>` are different types with different layouts,
and neither is assignable to the other. `N` reads inside the body as an ordinary
`Int` that costs nothing at runtime, and it can be an array length, a
`static_assert` operand, or a repeat count.

`[v; N]` is that repeat literal — `N` copies of one value, and the way to spell
a zeroed buffer:

```saw
var scratch: [Int8; 256] = [0; 256]
static POOL: [Int8; 4096] = [0; 4096]     // zeroinitializer, in .bss
```

A module `static` is a constant in all of those positions too, which is how a
size gets written once and derived everywhere else:

```saw
static REGION_SIZE: Int = 65536

static_assert(REGION_SIZE % 4096 == 0, "the region must be page-aligned")

struct Region { bytes: [UInt8; REGION_SIZE] }
static ARENA: [UInt8; REGION_SIZE] = [0; REGION_SIZE]
```

The static has to be an `Int`/`UInt` whose own initializer folds. Statics fold
in declaration order, so one may derive from the ones above it —
`static PAGE_MASK: Int = PAGE_SIZE - 1` — and a forward reference is a compile
error naming the order. A mutable `unsafe static var` or a static of another
type is a compile error that names which static and why.

The bit operators fold too, which is what register and wire arithmetic is
written in. `<<` wraps at the target's integer width, exactly as the emitted
shift does, and a shift count outside `0..<width` is a compile error rather
than a folded surprise:

```saw
static PAGE_SHIFT: Int = 12

static_assert((1 << PAGE_SHIFT) == 4096, "4K pages")
static_assert(((0x1234 + 0xFFF) & ~0xFFF) == 0x2000, "align up")

struct PageTable { entries: [UInt64; 1 << 9] }
```

A case of a raw-backed enum is a constant, so flag combinations fold:

```saw
enum Perm: UInt8 {
    case Read = 0x01,
    case Write = 0x02,
    case Exec = 0x04
}

static_assert((Perm.Read | Perm.Write) == 3, "read+write")
```

The result is the backing integer, `UInt8`, not `Perm` — 3 is not a declared
case, and calling it one would break `Perm.from(raw:)` and exhaustive `match`.
An enum is a closed set of tags; a bit set over those tags is the integer they
are tags for. Outside a constant, where the operands are enum-typed values
rather than case names, the operator is refused and the projection is written
out: `(held as UInt8) | (Perm.Exec as UInt8)`.

### Errors as Values

Every `Error` is `Printable`. Returning `Result<T, Box<any Error>>` lets a
function return any error type without writing a union by hand: the concrete
error is boxed and its exact type hidden behind `any Error` at the return
boundary. That is a convenience for hosted code: the box is named in the
signature, so `--no-hidden-alloc` allows it, but a kernel wants a concrete or
closed-union error type (`Result<T, ConcreteE>`), which allocates nothing at
all.

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
at every spawn; the default stays single-threaded and deterministic. A container
is `Send` when its contents are, so a task may carry a `Vector<Int>`, a `Map`, a
`Set`, a `Data` or a `StringBuilder` across a suspension on a worker thread.

The task's frame goes at completion too, along with the run-queue slot it
occupied, so a group costs what is running rather than what has ever run. A
server that spawns 200,000 short handlers into one group holds four slots if four
are in flight. `group.count()` reports the slots held: live tasks, plus tasks
whose result nobody has joined yet.

A task may borrow from the frame that spawned it, in either of the two spellings
that reach it: a capture, `group.spawn(work({ [&var n] in ... }))`, or a
reference argument, `group.spawn(fill(&var buf, 3))`. Both are one borrow, and
the Law of Exclusivity covers it for as long as the task can reach the root: the
task's handle carries the borrow, `join()` releases it, and a handle nobody joins
holds it until the group is destroyed. So spawn, join, then use the value reads
exactly as it looks, while writing, reading or moving the root between the spawn
and the join is a compile error naming the task and the join that would end its
borrow. A worker filling a caller's `Vector` writes through to it, and the
elements it pushed are destroyed once, by the caller, at the caller's scope end.

Into a `threads: N` group neither spelling compiles: a reference is not `Send`.
Sharing a value with a task that is still running — or with one on another
thread — is what `Arc<Mutex<T>>` and `Channel` are for.

```saw
import std.task.*        // `yield_now` lives in std.task

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
    let total = work(3) + work(4)         // both operands suspend
    print("squared: {work(5)}")           // suspends inside an interpolation
    let cached: Int? = None
    return total + (cached ?? work(7))    // the `??` RHS suspends only if it runs
}
// spawned into a TaskGroup: prints "squared: 25", joins 74
```

The short-circuit keeps its guard wherever it sits. In the `return` above the
`??` is nested inside a `+`, and `work(7)` still runs only on the `None` path.

A suspension the transform cannot place is a compile error naming the site, not
a silent blocking call.

Nor does the position depend on which module the code lives in. A suspending
function or method from a dependency, or from the standard library, is drawn
into the calling task's frame like a local one, and it keeps its own module's
meaning while it is there: the private helpers and constants its body names go
on resolving where they were written. Generic functions cross module boundaries
the same way, with one frame per instantiation.

A single cooperative scheduler runs spawned tasks eagerly, backed by an I/O
reactor (kqueue or epoll). A task parked on a socket wakes exactly when its file
descriptor is ready, cancellation wakes even an already-parked task, and an
operation-count budget stops a spinning task from starving the others: the
compiler charges every loop iteration of a task body against that budget, so a
pure-compute loop cedes without an explicit `yield_now`. So an
endless `accept`-loop server keeps serving live connections. Blocking FFI calls
(`extern "C" { blocking func ... }`) run on a separate thread and park the task
like any other I/O, so the remaining tasks stay responsive. The signature can be
any the C ABI carries, `read(fd, buf, n)` included; a pointer argument has to
address the suspended frame or the heap, since the worker is still reading
through it while the task is parked.

### Task Backtraces

A suspended task is not on any thread's stack, so a native backtrace of a parked
program shows the executor's poll loop and none of the program. `dump_tasks()`
prints what is missing: every live task, and the `file:line` of every suspending
call between its entry point and the place it is parked.

```
saw tasks: 2 live (unsynchronized snapshot)
  task group 1 slot 0 gen 1 io-parked
    at net.saw:412 in TcpStream.read
    at server.saw:18 in read_header
    at server.saw:24 in handle
  task group 1 slot 1 gen 1 running
    at server.saw:41 in accept_loop
```

A program that dies with tasks in flight prints this after its panic line, with
no flag to remember to turn on. Reconstruction is a walk of static tables the
compiler links into every binary, not an unwind, so it allocates nothing and
works under an exhausted allocator, in a kernel, and inside a panic handler.
`tools/lldb_saw.py` adds `saw tasks` and `saw bt` for a process stopped under
lldb.

### Cooperative Networking

`std.net` exposes owning, safe types with no raw file descriptors or callbacks.
Suspension happens inside the methods, failures come back as `Result`, and
end-of-stream is represented as a distinct value from an error:

```saw
import std.net.{TcpListener, TcpStream}

func handle(stream: TcpStream) {
    try {
        let chunk = try stream.read()   // Result<Data, IoError>; an empty Ok is EOF
        print(chunk.len())
        try stream.write("hello")       // writes every byte, or surfaces the error
    } catch {
        print("connection failed: {error}")
    }
}                                       // `stream` deinits here: the fd closes when
                                        // the handler returns

func serve(port: Int) {
    var group = TaskGroup()
    let listener = try! TcpListener.listen(port)
    while {
        let conn = try! listener.accept()    // parks; siblings keep running
        let _ = group.spawn(handle(move conn))
    }
}
```

The error handling in `handle` is ordinary Saw: a `try { } catch { }` block whose
try body suspends twice, inside a spawned task. A propagating `try` returns the
error from a suspending function the same way it does from a sync one, and an
erased `Result<T, Box<any Error>>` crosses a suspension too — the task body is
not a reduced dialect.

`TcpStream.connect` takes a dotted-quad IPv4 address or a hostname. An address
is parsed in Saw and dialled directly. A name goes through `getaddrinfo`, which
can take anything from a `/etc/hosts` read to a DNS timeout, so the lookup runs
on a worker thread and the task parks: sibling tasks keep running while it is in
flight. A name that does not resolve is an `Err(IoError)` naming it. IPv6 is not
resolved yet. See the [std.net section of the spec](LANGUAGE_SPEC.md).

### The Copy Trait Family

The cost of a transfer is readable at the point where it happens. The tiers and
the one decision they leave you are under
[Memory Management](#memory-management); this is what they look like.

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
wrapped argument list. An import's symbol list is the one brace pair that wraps,
being a delimited list rather than a statement container:

```saw
import std.net.{
    TcpListener,
    TcpStream,
}
```

A bracket that is never closed is reported at the opener.

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

Extension methods are **import-scoped**. A file sees extensions from its own
module, from the modules it imports directly, and from the receiver type's own
module — never from a transitive dependency it did not import. `public` on an
extension therefore means what it means everywhere else: importers of my module
get this. Nothing can add methods to your types program-wide behind your back,
and adding a dependency cannot change which method an existing call resolves to.

Trait conformances follow a stricter rule, because they are program-wide by
nature: `extension T: Trait` may be declared only in the module that defines `T`
or the module that defines `Trait`. Two modules minting different conformances
for one (type, trait) pair would let a `Map` built in one and probed in the
other disagree about hashing. To conform a foreign type to a foreign trait, wrap
it in a type you own.

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

There are three import forms, and the standard library takes the same three as
any other module:

```saw
import std.time                    // binds the qualifier: time.Instant.now()
import std.time.*                  // every public name, bare: Instant.now()
import std.time.{Instant}          // Instant bare, plus the time qualifier
```

A qualifier works wherever a name does — annotations, generic arguments,
call heads, static-method chains, `any` existentials, generic bounds. It is
also the lowest-priority name in scope, so a local called `data` or `time`
shadows one with no error and no ceremony, lexically. `sawc -W
shadowed-qualifier` flags the declaration if you want to hear about it.
`as` renames a qualifier (`import mypkg.io as fileio`) and braces rename a
symbol (`import m.{A as B}`). Visibility is scoped (`public(package)`,
`public(parent)`).

**Member visibility**: struct fields and extension methods (including `init`)
are private by default outside their defining module, and `public` marks the API
surface. The standard library lives under the same gate: you reach its public
API, never its internals.

**Type identity** is the defining module plus the name, so a dependency's
private `struct Header` reserves nothing in your program — you get your own
`Header`, with its own layout and its own methods. Two packages' *public*
`Header`s coexist as well; import at least one under an alias
(`import wire.{Header as WireHeader}`), since one file cannot refer to both by
the bare name. Using the bare name when two are in scope is a compile error
naming both modules. The standard library is under the rule too: each std file
is its own module, so the types a std file keeps to itself (`State`, `MapSlot`,
`OpenMode`, and the rest of its internals) reserve nothing, and your own type
may carry the name. What std publishes is unchanged.

**Prelude discipline**: a curated core is available bare (primitives,
`Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/`Arc`, the trait vocabulary,
`print`/`panic`/`assert`, the concurrency primitives, `StringBuilder`).
Everything else
(`File`, `Data`, `Channel`, `Mutex`, `TcpStream`, `Command`, and so on) needs an
import of its module, which also means your own type named `File` or
`IoError` never collides with the standard library's.

The rule covers every position a type is written, not only the ones that build
a value of it — a parameter, a return type, a field, a `let` annotation, a
generic argument:

```saw
func take(d: &Data) -> Int { d.len() }
// error: `Data` is not in the prelude and must be imported
// hint: `import std.data.{Data}` selects it, `import std.data.*` takes the
//       module's whole vocabulary bare, and `import std.data` lets you write
//       `data.Data`
```

What is checked is the name as you wrote it, so the qualified spelling passes
wherever an import bound the qualifier.

## Memory Management

Saw provides deterministic memory management without garbage collection:

- **The Copy trait family**: trivial types copy bitwise. `ImplicitCopy` types
  (like `String`, `Arc` and `Data`) copy cheaply on every transfer as a refcount
  bump.
  `ExplicitCopy` types (like `Vector`) never copy implicitly: you `move` to
  transfer them or `.copy()` to duplicate. `NoCopy` types (like `File`, `Mutex`,
  and for now `Map`/`Set`) can only be moved. A struct that owns such a field
  picks its own policy — `extension Holder: NoCopy {}` for move-only, or
  `@synthesize extension Holder: ExplicitCopy {}` for a memberwise deep copy.
  That is the one thing the compiler will not guess for you. An enum carrying
  such a payload picks a policy the same way, and its derived `copy()` is
  payload-deep over the active variant.
- **A type whose owning members are all trivial or `ImplicitCopy` is
  `ImplicitCopy` itself**, with no declaration written and none required. So
  `struct Ticket { code: String }` compiles bare, and `let b = a` is a refcount
  bump that leaves both bindings live. Declaring the stricter `NoCopy` on such a
  type is legal, and is how you make something move-only that could have been
  copied for free.
- **`NoMove` is a separate axis: relocation, not duplication.** A `NoMove` type
  moves exactly once, from its constructor into its binding, and never again —
  `move x` is a compile error, and so is `Optional.take` of one. Replacing a
  referent whole through a `&var` stays legal, because that destroys and
  constructs at one address. `NoMove` does not imply `NoCopy`; it requires it,
  so a type states both (`extension TaskGroup: NoCopy {}` beside
  `extension TaskGroup: NoMove {}`). A struct holding a `NoMove` member declares
  the same pair itself, or holds the value behind a `Box` for a movable handle
  over pinned storage. `TaskGroup` is the conformer that motivated it: a group's
  `Deinit` joins its children where the group was born, so a group that moved
  would join in one place and be driven from another.
- **Wrappers carry the tier of what they wrap.** Every type has exactly one
  transfer class, and a type built out of others is never weaker than its parts:
  an `Optional<T>`, a tuple, a fixed array, an enum payload and a `Result<T, E>`
  each take the strongest tier they hold. `Vector<Int>?` needs `move` or
  `.copy()`, `File?` is move-only, `Int?` stays trivial, and a struct with a
  `File?` field owes a policy exactly as if the field were a bare `File`.
  `.copy()` on an optional exists when the payload's tier provides one, copying
  `None` to `None` and `Some` to `Some` of the payload's own copy. A tuple's
  `.copy()` follows the same rule: it exists unless some element is move-only,
  and each element copies at its own tier, so a `(Vector<Int>, Int)` hands back
  an independent buffer beside a bitwise `Int`.
- **Explicit `move`** for ownership transfer, checked at the point of transfer.
- **Cleanup is written for you.** Any struct or enum that owns something gets a
  `deinit` synthesized from its fields, dropped in reverse declaration order at
  scope exit. You write a `deinit` by hand only for a raw resource such as a
  file descriptor; it runs before the field drops, and it goes inside the copy
  policy's conformance (`extension Res: NoCopy { func deinit(&var self) {...} }`)
  — every policy already requires `Deinit`, and a type with a destructor but no
  policy has no transfer rule.
- **Reading a payload out of an optional obeys the same table.** `o!`, the left
  operand of `??`, and an `if let` binding all name storage the optional still
  owns, so the payload's tier decides what the read costs. Borrowing in place
  (`o!.len()`) is free; a value read retains an `ImplicitCopy` payload and is
  refused for `ExplicitCopy`/`NoCopy`. The consuming reads are `move o!`, which
  retires the whole binding, and `o.take()`, which writes `None` back into the
  place and hands you the payload — including out of a struct field.
- **A method can hand out storage, not just a value.** A `borrows` method lends a
  **place** — an element or field that stays where it is — for the duration of
  one expression. `lend` is where the accessor pauses: it stops with its frame
  alive, the caller's code runs on the place, and anything after the `lend` runs
  when that window closes. The use site picks the flavor, so one declaration
  serves both a read and a write:

  ```saw
  extension Grid {
      public func [](&self, i: Int) borrows -> Cell {
          if i < 0 || i >= 9 { panic("Grid.[]: index out of range") }
          lend self.cells[i]
      }
  }

  print(g[4].weight)     // shared window: reads the element in place
  g[4].weight += 1       // exclusive window: writes it in place
  ```

  While a window is open its root is borrowed, so `v.push(x)` inside one is a
  compile error — iterator invalidation is caught by the Law of Exclusivity
  rather than by a callback's scope. Two windows onto one root in one call, or a
  window beside a `&var` of it, are the same violation: `swap2(&var d[0], &var
  d[1])` is refused rather than silently swapping copies. The lent place must be
  storage the receiver already owns, so an accessor cannot lend its own local or
  parameter — a write through such a window had nowhere to land. `Vector` and
  `Data` publish `v[i]` this
  way, which is what lets a move-only element be reached without copying it out.
  Reading a place *out* as a value follows the copy-tier table above. One
  consequence to know: on a `borrows` method the receiver is borrowed with the
  window's flavor, so `&self` there does not mean shared-only (see
  [Places](LANGUAGE_SPEC.md#places-borrows-and-lend)).

  A body can ask which flavor it is being compiled for. `#lend_var` is a
  compile-time constant, legal only inside a `borrows` body, that is `false` in
  the shared specialization and `true` in the exclusive one — so a copy-on-write
  type puts its separate-if-shared gate where only writes reach it:

  ```saw
  public func [](&self, index: Int) unsafe borrows -> UInt8 {
      if index < 0 || index >= self.length { panic("Data.[]: index out of range") }
      if #lend_var {
          if not self._make_ready(self.length) { panic("Data.[]: allocation failed") }
      }
      let bytes = self.byte_ptr() as UnsafePointer<UInt8>
      lend bytes[index]
  }
  ```

  The accessor compiles twice, and the gated branch is *removed* from the shared
  copy rather than skipped in it. That is what lets `Data` keep value semantics
  and still be read through a `let` binding: `print(d[0])` separates nothing,
  while `d[0] = 90` separates first and needs a `var`.

  `Map` publishes one too. Its values sit inside a slot enum's payload, and an
  arm of a borrowing `match` can lend that payload, so the subscript reaches the
  value in the table:

  ```saw
  var counts = Map<String, Vector<Int>>()
  var first: Vector<Int> = [1]
  let _ = counts.insert("a", move first)

  counts["a"]!.push(2)              // grows the stored vector where it sits
  print(counts["a"]!.len())         // prints: 2
  if let _ = counts["b"] {
      print("present")
  } else {
      print("absent")               // an absent key opens no window at all
  }
  ```
- **A closure's captured environment is immutable**, which is what makes copying
  a closure a plain refcount bump. Captures are read-only from inside the body:
  writing to one is a compile error, because the write would land on a per-call
  copy and vanish when the closure returned. The error names the two spellings
  that reach real storage — `[&var x]` to capture by borrow (a closure passed
  directly to a non-escaping parameter), or `Arc<Mutex<T>>` to share state a
  closure outlives the frame with.
- **Reference types** (`&T`, `&var T`) for borrowing, checked for exclusivity at
  compile time.
- **The Law of Exclusivity**: a `&var` (mutable) reference must not overlap any
  other reference reaching the same value for as long as it is live. It is fully
  static, with no lifetimes to write. A call argument's reference is live for the
  whole call expression, nested calls included, so `sink(&var p.x, reset(&var
  p))` is refused where `add(&var x, bump(&var y))` compiles; a `borrows`
  accessor's window lasts the enclosing expression; a `&var` capture or argument
  into a spawned task lasts until the task's handle is joined.
- **References compose**: a `&T` or `&var T` you receive can be passed on to
  another function as a re-borrow. A reference is never made more permissive than
  the one it came from, and references stay valid across suspension points.
- **References are parameters only**, and the compiler holds the line where a
  reference is written: a return type that names one is an error, in every
  position a return type is written, and so are a struct field (`struct Holder
  { r: &Int }`), a generic argument (`Vector<&Int>`, `idn<&Int>(x)`) and a
  closure whose inferred return is a reference (`{ &x }`). Refusing the field
  closes the construction with it, and refusing the generic argument leaves
  `v.push(&x)` alone, which is a call argument and means what it says. Each
  diagnostic names the two ways to write what was meant — pass or return the
  value, or lend the storage with a `borrows` accessor, which hands out the
  place itself for a window. A reference in parameter position is untouched.
  One expression crosses the line on purpose: `(&x) as UnsafePointer<T>` is the
  language's address-of, legal in any position, and it hands the lifetime
  question to the unsafe tier — a pointer leaves, not a reference, and the
  `unsafe` effect on every signature naming it is the fence.
- **Shared ownership** through `Arc<T>` (Saw uses atomic reference counts only)
  and owned heap allocation through `Box<T, A>`.
- **Allocation failure is loud**: an infallible operation (`push`, `append`,
  `insert`, `send`, `Box.make`, any constructor) panics through the
  `__saw_rt_panic` seam naming the method that ran out (`Vector.push: allocation
  failed`), so a kernel picks the policy. It never truncates the container, never
  returns a plausible substitute value, and never hands back an object that has
  quietly stopped working. The `try_`-prefixed twins (`try_push`, `try_reserve`,
  `try_make`, `try_insert`, `try_send`) return `Result<_, AllocError>` and are
  all-or-nothing: on `Err` the container is exactly as it was.
- **Unsafety is carried in the type, and declared by the function**: raw
  pointers live in `Unsafe*` types, and so does anything you declare with
  `unsafe struct` (the compiler enforces the name). A function that names, binds,
  receives or returns one of those values declares the effect after its parameter
  list — `func push(&var self, value: T) unsafe`, the slot `sync` already used —
  or the compiler rejects it and names the type. There are no `unsafe` blocks and no unsafe
  regions. Unsafety is not transitive: `Vector` holds a raw pointer and is still
  a safe type, so only the methods that reach through to it are marked. Calling
  an unsafe function from safe code needs no ceremony — a function whose
  parameters are all safe types has to be sound for every input, and a
  precondition is stated by taking an unsafe-typed parameter instead.
- **Every indexed accessor is checked**: on a safe type, an out-of-range index
  panics (`Vector.set`, `String.substring`) or returns `None` (`Vector.get`).
  Never a silent no-op, never a clamp to a plausible answer. Unchecked access
  exists only through `UnsafePointer`.
- **Integer conversion is checked too**, with three spellings for the three
  things it can mean. `x as UInt8` panics when the value has no `UInt8` —
  by range or by sign — instead of quietly producing a different number;
  `UInt8.from(x)` returns `UInt8?` for input the program does not control; and
  `UInt8.from(truncating: x)` keeps the low bits when that is the intent, the
  cast-shaped sibling of `&+`/`&-`/`&*`. Widening still emits one instruction
  and no check, and a constant that cannot fit its target is a compile error
  rather than a first-run abort.
- **Integer operands agree, and only bare literals promote**: `n * 2` is legal
  at every integer type because a bare literal has no width of its own and
  adopts the other operand's, while `n * 2i16` on an `Int` and `i + u` on an
  `Int`/`UInt` pair are compile errors naming both types. There is no promotion
  ladder — an operation has two peers, and picking a winner would decide in
  silence which operand's reading the program runs under. A shift COUNT is
  exempt; it is not a peer. The arms of a value `if`/`match` and the two sides
  of `??` are transfers, so an arm that widens losslessly is free
  (`if a > 0 { 11 } else { 7i16 }` in an `-> Int` function answers 7 on the
  else path) and one that would narrow or flip sign is refused.

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
- **One answer when allocation fails**: the panicking and `try_` tiers described
  under [Memory Management](#memory-management) are what a kernel gets too, and
  the panic routes through a seam the environment supplies.
- **Memory-mapped I/O**: `UnsafeMemory<T, Use>` is a compiler-known view of memory
  at a fixed address, with volatile `read()`/`write()` for device registers and
  field-offset projection. It is an unsafe type, so a driver method that touches
  a register block carries `unsafe` in its signature and reads as one at every
  call site.
- **Logging with no allocator**: `print("stage {} ok", i)` writes through the
  `__saw_rt_write` seam without touching a heap, so a kernel gets the same
  logging a hosted program has. Panic messages are assembled in stack scratch
  for the same reason — the failure you most need reported is the one where
  memory ran out. The SOS kernel in this repo logs this way; `make sos-test`
  boots it under QEMU and checks the lines on the UART.
- **No hidden allocations, enforced**: `--no-hidden-alloc` rejects the allocations the
  compiler would insert on its own authority — a string interpolation's buffer,
  an escaping closure's captured environment, `print` of one of your own
  `Printable` types — and names the spelling that does not allocate. Everything
  your source names still works: `Vector.push`, a collection literal, `spawn`, a
  `Box<any Error>` you wrote into a signature. The flag is orthogonal to
  `--freestanding` (a kernel with a slab allocator may want real `String`s) and
  the two combine; the SOS kernel builds under both, which is what keeps its log
  lines off the heap.
- **Global state, five ways, none of them silent**: `Atomic<Int>` for a word
  several tasks update independently — move-only, because a copied atomic is a
  second counter and the fork would be silent, so you share one through a
  `static` or a `&` parameter; `SpinLock<T>` for state threads or cores
  genuinely share where there is no OS — one word plus the payload, no
  allocator, so `static TABLE: SpinLock<HandleTable>` is a declaration a kernel
  can write; `Mutex<T>` for the same shape hosted, where a waiter should sleep
  rather than spin (also one inline word, also declarable as a bare `static`);
  `Once<T>` for state computed once at a moment the program picks and read as a
  plain value after; and `unsafe static var` for compound state whose
  consistency spans words and comes from a serialization argument only the
  author knows (interrupts off, one core, boot only). The last one is `unsafe`
  for a reason: naming it makes every function that touches it declare `unsafe`
  too, so the argument is in front of whoever reviews the code.
- **Interior mutability is a type you can write**: a `&self` method that writes
  needs an `UnsafeMutableInterior<T>` field, and carrying one is what makes a
  receiver arrive as the caller's storage rather than as a copy. The compiler
  does not know your type's name — it asks whether the type carries a cell —
  and the same answer decides that a `static` of it is writable and that it
  derives no `Sync` until you say `extension Counter: UnsafeSync {}` beside it.
  `Atomic`, `SpinLock`, `Mutex` and `Once` are written that way, with no
  privileges a program cannot claim.
- **Statics are image bytes, and say so**: an initializer is a constant
  expression (`static PAGE_SIZE: Int = 1 << PAGE_SHIFT`, folding in declaration
  order) plus memberwise aggregation. Nothing computed runs before `main`,
  because nothing runs before `main` — a hand-written `init` body is refused,
  and the error names the two spellings that do work.
- **A critical section cannot suspend**: `SpinLock`'s body is a `sync` function
  type, so suspending while holding the lock is a compile error rather than a
  livelock. And the lock needs real atomics — on rv32i, where a
  compare-and-swap would become a libcall into a C runtime the target does not
  have, naming a `SpinLock` is an error naming the flag that fixes it.
- **Zero regions cost nothing**: `unsafe static var ARENA: [UInt8; 65536] = [0;
  65536]` is 64 KiB of address space and zero bytes of image, in both profiles.
- **A package can be the runtime**: `[package] runtime = true` in `Saw.toml` lets
  a package implement the `__saw_rt_*` seams itself. The compiler links no
  runtime of its own beside it and checks every exported seam against the
  signatures in `sawc/rt/ABI.md`, so a seam with the wrong arity or width fails
  the build instead of linking cleanly and misbehaving.
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
import std.spinlock.*

static UART_BASE: Int = 0x1000_0000

struct UartRegs {
    data: UInt32
    status: UInt32
}

static_assert(sizeof<UartRegs>() == 8, "UartRegs layout drift")

struct Slot { owner: Int, used: Bool }

// Compound state, serialized by the caller's argument: every function that
// names it says `unsafe`, and the compiler will not let one forget.
unsafe static var HANDLES: [Slot; 64] = [Slot(owner: 0, used: false); 64]

// Genuinely shared state, serialized by the lock. No allocator involved, and
// no bytes in the image until something writes it.
static PENDING: SpinLock<Int>

func claim(owner: Int) unsafe -> Int {
    var i = 0
    while i < 64 {
        if not HANDLES[i].used {
            HANDLES[i] = Slot(owner: owner, used: true)
            PENDING.lock({ n in n = n + 1 })
            return i
        }
        i = i + 1
    }
    -1
}

@export("kernel_add")
func add(a: Int, b: Int) -> Int {
    a + b
}

func boot() {
    // Reaches the console through the runtime seam; allocates nothing.
    print("uart at {} regs {}", UART_BASE, sizeof<UartRegs>())
}
```

Cross-compiling to a bare-metal target takes a triple and, where the part has
optional extensions, a feature list:

```bash
sawc kernel.saw -o kernel.o --freestanding --no-hidden-alloc \
    --target riscv32-unknown-none-elf --target-features +m,+a,+c
```

Base rv32i has no divide instruction, so `--target-features +m` is what keeps
integer formatting from emitting a libcall the freestanding profile has no
library to satisfy.

On aarch64 the profile supplies one default of its own: `-neon,-fp-armv8`. An
AArch64 core traps Advanced SIMD at EL1 out of reset, and LLVM reaches for `q`
registers to move a struct, so a kernel used to fault on its first block copy —
before the exception vectors that would have reported it were installed. Pass
`--target-features +neon,+fp-armv8` to get SIMD back if your boot code enables
`CPACR_EL1.FPEN` first; you then own saving those registers across a context
switch.

## Standard Library

The standard library includes:

- **String** - Immutable, reference-counted byte string (atomic refcount, O(1)
  `len()`), always valid UTF-8. `bytes()`/`chars()` iterator views, `split`,
  `fromBytes` (validating), and parsing that returns an Optional rather than
  panicking: `to_int`, `to_float`, and `to_uint` — the unsigned companion that
  reaches the whole `0..UInt.max` range, with a `radix:` overload. Concatenation
  goes through interpolation or `StringBuilder`.
- **StringBuilder** - Geometrically-growing builder: `append` (overloaded for
  `String`/`Int`/`UInt`, rendering digits with no intermediate `String`),
  `append_char`, `append_scalar` (UTF-8-encodes one Unicode
  scalar, returning the byte count, or `None` for a surrogate or out-of-range
  value), `len`, `is_empty`, `clear`, `as_str`, `build`. A second constructor,
  `StringBuilder(bytes:capacity:)`, builds over caller-provided storage and
  never allocates: content that does not fit is cut on a UTF-8 boundary and
  marked with `…`, which `is_truncated()` reports. That is the builder
  `print`/`panic` hand to a `Printable` value's `format`.
- **FixedBuf&lt;N&gt; / FixedStringBuilder&lt;N&gt;** (`import std.fixedbuf.*`) - `N`
  bytes of storage held inline, sized by a const generic parameter, and a
  `StringBuilder` over one. Same `append` surface and same cut-and-mark
  truncation as the fixed-mode builder above, with the storage question
  answered by the type. Allocates nothing, so it works in both profiles.
- **Vector<T, A>** - Dynamic array: `push`, `pop`, `get`, `len`, `map`/`fold`,
  `sort`/`sort_by`, `swap`; context-driven `[...]` literals.
  `with_ref`/`with_var_ref` borrow one element in place for the duration of a
  closure, holding the whole vector borrowed so a reallocation cannot invalidate
  it. That is the only way to read or mutate a `NoCopy` element in place.
- **Map<K, V, A>** - Hash map (open addressing): `insert`, `remove`,
  `contains_key`, `len`; `each` visitors and `keys()`/`values()` snapshots;
  `{k: v}` literals. Keys are any copyable `Hashable + Equatable` type
  (move-only keys are rejected). `m[k]` and `m.get(k)` are one accessor under
  two names: each lends the stored value where it sits, so `m[k]!.count += 1`
  writes it in place and an absent key takes the absent path without touching
  anything.
- **Set<T, A>** - Hash set: `insert`, `remove`, `contains`, `len`, plus
  `union`/`intersection`/`difference`/`is_subset`; `{a, b}` literals.
- **Data** - Copy-on-write byte buffer: a window onto `Arc`-owned storage.
  Copying or slicing one is a refcount bump (`slice` is O(1) at any size), and
  the bytes separate at the first write that finds them shared, so no mutation
  is ever visible through another `Data`. `detached()` materializes the bytes
  eagerly, sized to `len()`, when a small slice would otherwise keep a large
  buffer alive.
- **Arc<T>** / **Box<T, A>** - Atomic reference counting / owned heap allocation.
  `Arc.with_unique(body:)` runs `body` on a `&var` borrow of the payload when
  the handle is the only strong owner and answers `None` when it is shared —
  the copy-on-write gate `Data` is built on.
- **Mutex<T>**, **Channel<T>**, **Task<T>**, **TaskGroup** - Concurrency. A
  channel has two receives, one per engine: `receive()` suspends the task and is
  what cooperative code wants; `recv()` blocks the calling thread and belongs to
  the `spawn`/`Task` engine. Calling `recv` from a task stops the executor
  thread, and with it the task that would have sent the value. `Mutex<T>` is one
  inline word beside its payload — no allocation, no `deinit`, and zero means
  unlocked, so `static REGISTRY: Mutex<Int>` needs no initializer.
- **Once<T>** - A value written once and read many times. `static LIMITS:
  Once<Limits>` is unset at zero; `set` publishes with the release/acquire
  pairing inside the type, `get` returns the value, and both a second `set` and
  a `get` before any `set` panic rather than returning a status the caller could
  ignore. `try_get() -> T?` is the twin for code that does not know yet.
- **std.net** - `TcpListener`/`TcpStream`: owning, cooperative, `Result`-honest
  (accept/connect/read/`read_into`/overloaded write).
- **File**, **Directory**, **Path**, **Data**, **Env** - System I/O. Every
  operation that can fail returns its cause: `File.open`/`create`/`open_append`,
  `read`, `write`, `seek_*` and `Directory.list` return `Result<_, IoError>`, as
  do the mutating operations (`remove`, `rename`, `create`, env `set`/`unset`).
  An Optional is reserved for a genuine absence — `Directory.current` answers
  `None` only when getcwd(2) itself fails. Nothing in std silently swallows an
  error. These operations are synchronous: prompt on a local disk, and that is
  the deliberate trade, but a network mount that has stopped answering (or a
  FUSE mount, or a FIFO with no writer) holds the calling thread — and a
  cooperative task that issues such a read holds its executor thread, with every
  sibling behind it. Work that cannot afford the stall belongs in a `spawn`-ed
  `Task`.
- **std.process** - `Command.run() -> Result<Int32, ProcessError>`, `.output()`,
  `.env(name:value:)` (one environment variable for the child, on top of the one
  it inherits), `.merge_stderr()`. Both `run` and `output` are cooperative: the
  wait parks on the child's exit and the stdout drain runs on a worker thread, so
  sibling tasks keep running for as long as the child does and no thread is spent
  waiting. Cancelling the task ends the wait, not the child.
- **Duration** - A span of time, UInt64 whole nanoseconds, in the prelude
  because `sleep` takes one. `Duration.ns` / `us` / `ms` / `secs` build one and
  `as_nanos` / `as_micros` / `as_millis` / `as_secs` read it back; it compares
  and prints (`200ms`, `1.42s`). Both profiles.
- **std.time** - `Instant`, `unix_timestamp` (hosted).
- **Numeric extensions** - The two sets are disjoint. `Int`: `abs`, `min`/`max`/
  `clamp`, `pow`, `is_even`/`is_odd`, `signum`. `Float`: `abs`,
  `floor`/`ceil`/`round`, `sqrt`, `min`/`max`.
- **Serialization** - `Serialize`/`Deserialize` over an `Encoder`/`Decoder`
  seam, prelude-visible and present in both profiles. A value writes itself into
  an `any Encoder` and reads itself back with a static
  `Type.deserialize(from:)`. `@synthesize` derives both directions structurally
  — every stored field in declaration order, covering the integer types, `Bool`,
  `String`, `Optional`, `Vector`, raw-backed enums and nested conforming types;
  anything else is a clean error naming the field. Every signature is `sync`, so
  a value serializes inside a lock or a kernel. Failures are `Result`:
  `DecodeError` carries the byte offset it stopped at, so malformed input is
  reported rather than panicked on.
- **std.cbor** (`import std.cbor.{CborEncoder, CborDecoder}`) - CBOR (RFC 8949)
  in its deterministic encoding profile: shortest-form arguments, definite
  lengths, sorted map keys, no floats, no tags, one top-level item. Anything
  outside the profile is rejected on decode, so the bytes are the value.
  `CborDecoder.open` validates the whole input against `max_depth`/`max_size`/
  `max_items` before any typed read runs, walking an explicit work stack rather
  than the call stack - a deeply nested blob is refused at a byte offset instead
  of exhausting the stack, and no input panics. Floats are a decode error in v1.
- **Traits** - `Equatable`, `Comparable`, `Hashable`, `Printable`, `Error`,
  `Serialize`, `Deserialize`.

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
  --emit-bt-table    Decode the linked task-backtrace table as JSON: per
                     coroutine frame, the source line each resume state parks
                     on or the embedded callee it is inside
  -O0                Disable optimization (default is an O1-style pass pipeline)
  --target <triple>  Cross-compile for a target triple (default: the host)
  --target-features <list>
                     LLVM subtarget features for --target (e.g. +m,+a,+c);
                     overrides the freestanding profile's aarch64 default
  --freestanding     Freestanding profile: no hosted std, unlinked object
                     output; on aarch64 implies -neon,-fp-armv8
  --no-hidden-alloc  Reject allocations the compiler inserts that your source
                     does not name (see Kernels and Embedded)
  --runtime-build    Build a Saw runtime exporting the __saw_rt_* ABI
  --runtime-provider This package IS a runtime: it may export the __saw_rt_*
                     seams, each checked against sawc/rt/ABI.md
  --module-path NAME=DIR
                     Map a package name to a source directory (repeatable)
  -W <name>          Enable a warning category (repeatable; `-W all` for every
                     one). Warnings are off by default and never affect the
                     exit code. Categories: shadowed-qualifier
```

## Running Tests

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

Run `make test` to see the current test count. See
[TESTING.md](TESTING.md) for details, including application-level testing with
`blade test`.

### Splitting the suite across two machines

A spare machine can take a share of the suite. There is no SSH in this: the
machine runs one daemon under a sandbox profile, and the only thing that
crosses the network is a job, meaning a snapshot of the tree plus a list of
which tests to run. The daemon takes no command from the client and never
executes the submitted tree in its own process.

On the worker machine — a checkout, a virtualenv, a shared token, and the
launch line:

```bash
./.venv/bin/python tools/test_worker.py --init-token
sandbox-exec -D WORKER_ROOT="$PWD" -f tools/test_worker.sb \
    ./.venv/bin/python tools/test_worker.py --bind 0.0.0.0:8710
```

On this machine:

```bash
./.venv/bin/python test_runner.py --remote studio.local:8710
./.venv/bin/python tools/irdet_remote.py --all --remote studio.local:8710
```

Tests are assigned by a hash of each test's path, weighted by the two machines'
core counts, so a failing test lands on the same machine every run. The two
shares run concurrently and produce one merged summary, with each failure
marked by the machine that judged it.

A worker that is unreachable, refuses the token, is busy, or dies mid-run costs
a note, never a verdict: the tests it did not answer for run here, and the exit
status stays a statement about the tree. `tools/remote_battery.py` runs the
whole gate battery on the worker the same way. Deployment, the sandbox
profile's allowances, and the self-test are in [TESTING.md](TESTING.md).

## Current Status

Saw is in active development. Implemented so far:

- **Types and generics** — algebraic data types with exhaustive `match`, enums
  that carry methods and an integer wire backing, generics with trait bounds
  and call-site type inference, const generic parameters, traits with default
  bodies and `any Trait` objects, overloading, and the `Printable` / `Error` /
  `Equatable` / `Comparable` / `Hashable` traits with `@synthesize` derivation.
- **Ownership** — the Copy trait family, synthesized destruction, places
  (`borrows` accessors that lend storage rather than a value), whole-referent
  replacement through `&var`, and a `Result` that cannot be dropped by accident.
- **Concurrency** — colorless, with a cooperative scheduler over a precise I/O
  reactor, multi-threaded task groups, blocking-FFI offload, suspending calls in
  any expression position, and the whole error surface (`try`, `try { } catch
  { }`, erased errors) inside a task body.
- **Modules** — three import forms, member visibility over a curated prelude,
  import-scoped extensions under an orphan rule for conformances, per-module
  type identity, and earned shadowing.
- **Systems work** — pluggable allocators, memory-mapped I/O, `static_assert`,
  C-ABI exports, `SpinLock<T>` and `unsafe static var` for global state,
  allocation-free formatting, and `--no-hidden-alloc`.
- **Tooling** — source-location literals, doc comments with `--emit-docs`
  extraction, opt-in compiler warnings, reachability-scoped code generation with
  a dead-stripped link, and the Blade package manager, which is self-hosting.

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
./.build/blade clean           # remove build output
./.build/blade tree            # print the resolved dependency graph
./.build/blade add foo --path ../foo         # add a path dependency
./.build/blade add bar --git <url> --version ^1.0.0   # add a git dependency
```

### Build output

Everything a build produces goes under `<package>/.build/<target>/`:

```
myproject/
  Saw.toml
  Saw.lock
  src/main.saw
  .build/
    host/                      # the default hosted build
      myproject                # the binary
      build-hash               # what the next build compares against
      tests/                   # `blade test` binaries
    riscv32-unknown-none-elf/  # `blade build --target riscv32-unknown-none-elf`
      myproject
      build-hash
```

`<target>` is the `sawc --target` triple, or `host` for a build that names no
target. Two targets of one package therefore have two directories rather than
two builds overwriting one filename, and the up-to-date check is per-target: a
riscv32 build cannot satisfy an arm64 check, and an arm64 binary cannot answer
for a riscv32 one.

Nothing generated sits beside a source file, so a package needs one ignore rule
(`.build/`) and `blade new` writes it. `blade clean` removes the whole tree;
`blade clean --target <triple>` removes one target and leaves the rest. Neither
touches `.blade/deps/`, which holds dependency source rather than output.

### Dependencies

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
  An **application commits it**; a **library does not**, because a library's
  resolution belongs to whoever depends on it. The source layout decides which
  a package is: `src/main.saw` (or a root `main.saw`) builds a program,
  `src/lib.saw` alone is a library. `blade build` writes the lock for an
  application only. `blade update` writes it either way, so a library that
  wants one for its own CI can have it and ignore the file.
- **Git**: tagged versions are cloned into `.blade/deps/<name>-<version>/`
  (`.blade/` is self-gitignoring). No global cache yet.
- **Incremental**: a content hash of every reachable source
  (`.build/<target>/build-hash`) skips an up-to-date build; `--force` bypasses
  it. Both the hash and the artifact must be present for a build to be skipped,
  so a missing binary always rebuilds.
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

`let`/`var`, `guard let`, postfix `T?`, `extension` blocks, custom `init`s,
trailing closures, and `{}` string interpolation all mean what a Swift reader
expects. The divergences are ownership and effects, not surface syntax.

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

Saw is an experimental language. Issues and pull requests are welcome; start
from [LANGUAGE_SPEC.md](LANGUAGE_SPEC.md) and the design briefs in `designs/`.

## License

Saw is licensed under the [Apache License 2.0 with LLVM
Exceptions](LICENSE) (SPDX: `Apache-2.0 WITH LLVM-exception`).

In plain terms: use, modify, and redistribute freely, with an explicit
patent grant from contributors. The LLVM exception means programs you
compile with `sawc` are entirely yours: the standard-library code
embedded in your binaries carries no attribution requirements.

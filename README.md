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
  assignment is secretly O(n). No hidden allocations, enforced by
  `sawc --no-hidden-alloc` — every allocation is named by the expression or by a
  type you wrote, and the compiler allocating on its own authority is a compile
  error. The only implicit copies are cheap ones, and values are destroyed in a
  defined order (last in, first out) as they go out of scope.
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
import std.fixedbuf

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
at every spawn; the default stays single-threaded and deterministic.

The task's frame goes at completion too, along with the run-queue slot it
occupied, so a group costs what is running rather than what has ever run. A
server that spawns 200,000 short handlers into one group holds four slots if four
are in flight. `group.count()` reports the slots held: live tasks, plus tasks
whose result nobody has joined yet.

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

Imports are Python-style (only the named symbol enters scope), with module and
per-symbol aliasing (`import mypkg.io as fileio`, `import m.{A as B}`), scoped
visibility (`public(package)`, `public(parent)`), and glob imports
(`import m.*`).

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
naming both modules.

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
  and for now `Map`/`Set`) can only be moved. A struct that owns such a field
  picks its own policy — `extension Holder: NoCopy {}` for move-only, or
  `@synthesize extension Holder: ExplicitCopy {}` for a memberwise deep copy.
  That is the one thing the compiler will not guess for you. An enum carrying
  such a payload picks a policy the same way, and its derived `copy()` is
  payload-deep over the active variant.
- **Wrappers carry the tier of what they wrap.** Every type has exactly one
  transfer class, and a type built out of others is never weaker than its parts:
  an `Optional<T>`, a tuple, a fixed array, an enum payload and a `Result<T, E>`
  each take the strongest tier they hold. `Vector<Int>?` needs `move` or
  `.copy()`, `File?` is move-only, `Int?` stays trivial, and a struct with a
  `File?` field owes a policy exactly as if the field were a bare `File`.
  `.copy()` on an optional exists when the payload's tier provides one, copying
  `None` to `None` and `Some` to `Some` of the payload's own copy.
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
  rather than by a callback's scope. `Vector` and `Data` publish `v[i]` this
  way, which is what lets a move-only element be reached without copying it out.
  Reading a place *out* as a value follows the copy-tier table above. One
  consequence to know: on a `borrows` method the receiver is borrowed with the
  window's flavor, so `&self` there does not mean shared-only (see
  [Places](LANGUAGE_SPEC.md#places-borrows-and-lend)).

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
- **Global state, three ways, none of them silent**: `Atomic<Int>` for a word
  several tasks update independently; `SpinLock<T>` for state threads or cores
  genuinely share — one word plus the payload, no allocator and no OS, so
  `static TABLE: SpinLock<HandleTable>` is a declaration a kernel can write; and
  `unsafe static var` for compound state whose consistency spans words and comes
  from a serialization argument only the author knows (interrupts off, one core,
  boot only). The last one is `unsafe` for a reason: naming it makes every
  function that touches it declare `unsafe` too, so the argument is in front of
  whoever reviews the code.
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
import std.spinlock

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

// Reaches the console through the runtime seam; allocates nothing.
print("uart at {} regs {}", UART_BASE, sizeof<UartRegs>())
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
- **FixedBuf&lt;N&gt; / FixedStringBuilder&lt;N&gt;** (`import std.fixedbuf`) - `N`
  bytes of storage held inline, sized by a const generic parameter, and a
  `StringBuilder` over one. Same `append` surface and same cut-and-mark
  truncation as the fixed-mode builder above, with the storage question
  answered by the type. Allocates nothing, so it works in both profiles.
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
- **File**, **Directory**, **Path**, **Data**, **Env** - System I/O. Every
  operation that can fail returns its cause: `File.open`/`create`/`open_append`,
  `read`, `write`, `seek_*` and `Directory.list` return `Result<_, IoError>`, as
  do the mutating operations (`remove`, `rename`, `create`, env `set`/`unset`).
  An Optional is reserved for a genuine absence — `Directory.current` answers
  `None` only when getcwd(2) itself fails. Nothing in std silently swallows an
  error.
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
  --target-features <list>
                     LLVM subtarget features for --target (e.g. +m,+a,+c)
  --freestanding     Freestanding profile: no hosted std, unlinked object output
  --no-hidden-alloc  Reject allocations the compiler inserts that your source
                     does not name (see Kernels and Embedded)
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
types with exhaustive `match`; the Copy trait family; synthesized destruction
and `@synthesize`d conformances; traits with default bodies
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

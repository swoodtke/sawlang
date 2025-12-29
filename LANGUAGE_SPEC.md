# Saw Language Specification

> A modern systems programming language combining the safety of Rust with the elegance of Swift

## 1. Design Philosophy

### Core Principles

1. **Safety without sacrifice** - Memory safety and thread safety by default, with explicit opt-out for low-level control
2. **Zero-cost abstractions** - High-level constructs compile to efficient machine code
3. **Expressiveness** - Clean, readable syntax that reduces boilerplate
4. **Predictability** - No hidden allocations, no garbage collection pauses, deterministic destruction
5. **Progressive disclosure** - Simple things are simple, complex things are possible

### Non-Goals

- Backward compatibility with C/C++ syntax
- Runtime reflection (compile-time reflection only)
- Implicit conversions between types
- Null pointers

---

## 2. Basic Syntax

### Variables and Mutability

```saw
// Immutable by default (like Rust)
let x = 42
let name = "Saw"

// Explicit mutability
var count = 0
count += 1

// Type annotations (optional with inference)
let pi: Float64 = 3.14159
var items: [Int] = []
```

### Functions

```saw
// Basic function
func add(a: Int, b: Int) -> Int {
    a + b  // implicit return for last expression
}

// Multiple return values via tuples
func divide(a: Int, b: Int) -> (quotient: Int, remainder: Int) {
    (a / b, a % b)
}

// Generic functions
func swap<T>(a: var T, b: var T) {
    let temp = a
    a = b
    b = temp
}

// Functions with default parameters
func greet(name: String, greeting: String = "Hello") -> String {
    "{greeting}, {name}!"
}

// Trailing closure syntax
func map<T, U>(list: [T], transform: (T) -> U) -> [U]

let doubled = numbers.map { x in x * 2 }
let doubled = numbers.map { $0 * 2 }  // shorthand
```

### Control Flow

```saw
// If expressions (not statements)
let max = if a > b { a } else { b }

// Pattern matching (core feature)
match value {
    0 => "zero",
    1..=9 => "single digit",
    n if n < 0 => "negative",
    _ => "other"
}

// For loops with iterators
for item in collection {
    print(item)
}

for (index, item) in collection.enumerate() {
    print("{index}: {item}")
}

// While loops
while condition {
    // ...
}

// Loop with break value
let result = loop {
    if found {
        break value
    }
}

// Guard for early exit (from Swift)
func process(input: String?) {
    guard let value = input else {
        return
    }
    // value is now unwrapped and available
}
```

---

## 3. Type System

### Primitive Types

```saw
// Integers
Int8, Int16, Int32, Int64, Int128
UInt8, UInt16, UInt32, UInt64, UInt128
Int    // Platform-native signed (i64 on 64-bit)
UInt   // Platform-native unsigned

// Floating point
Float32, Float64
Float  // Alias for Float64

// Other primitives
Bool        // true, false
Char        // Unicode scalar value
String      // UTF-8 string
Never       // Bottom type (function never returns)
```

### Composite Types

```saw
// Tuples
let point: (Int, Int) = (10, 20)
let named: (x: Int, y: Int) = (x: 10, y: 20)
let x = point.0
let y = named.y

// Arrays (fixed size, stack allocated)
let fixed: [Int; 5] = [1, 2, 3, 4, 5]

// Slices (view into contiguous memory)
let slice: [Int] = &fixed[1..4]

// Vectors (dynamic, heap allocated)
let dynamic: Vec<Int> = [1, 2, 3]

// Dictionaries (use { } with key: value pairs)
let ages: Map<String, Int> = {"alice": 30, "bob": 25}

// Sets (use { } without colons)
let uniques: Set<Int> = {1, 2, 3}

// Empty collections require type annotation
let empty_map: Map<String, Int> = {:}
let empty_set: Set<Int> = {}
```

### Structs

```saw
// Value type (copied by default)
struct Point {
    x: Float64,
    y: Float64,
}

// Methods via extensions
extension Point {
    // Custom initializer (beyond default field init)
    init(magnitude: Float64) -> Point {
        Point(x: magnitude, y: magnitude)
    }

    // Instance method (immutable self)
    func magnitude(self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method (var self receives pointer)
    func translate(var self, dx: Float64, dy: Float64) {
        self.x += dx
        self.y += dy
    }
}

// Usage - default field init
var p = Point(x: 3.0, y: 4.0)
p.translate(1.0, 1.0)

// Custom init
let p2 = Point(magnitude: 5.0)  // Creates Point(x: 5.0, y: 5.0)
```

### Enums (Algebraic Data Types)

```saw
// Simple enum
enum Direction {
    North,
    South,
    East,
    West,
}

// Enum with associated data
enum Result<T, E> {
    Ok(T),
    Err(E),
}

enum Message {
    Quit,
    Move(x: Int, y: Int),      // Named parameters
    Write(String),              // Positional parameter
    Color(Int, Int, Int),       // Multiple positional
}

// Creating enum values
let msg1 = Message.Move(x: 10, y: 20)
let msg2 = Message.Color(255, 128, 0)

// Pattern matching on enums
match message {
    Message.Quit => quit(),
    Message.Move(x, y) => move_to(x, y),
    Message.Write(text) => print(text),
    Message.Color(r, g, b) => set_color(r, g, b),
}
```

### Optionals

```saw
// Optional type (no null!) - T? syntax like Swift
let maybe: Int? = some(42)
let nothing: Int? = none

// Optional chaining
let len = user?.profile?.bio?.len()

// Unwrap with default
let value = maybe ?? 0

// Force unwrap (panics if none)
let value = maybe!

// If-let binding
if let value = maybe {
    print("Got {value}")
}

// Guard-let for early exit
guard let value = maybe else {
    return
}
```

### Traits

```saw
trait Display {
    func display(self) -> String
}

trait Debug {
    func debug(self) -> String {
        // Default implementation
        "<opaque>"
    }
}

// Interface implementation via extension
extension Point: Display {
    func display(self) -> String {
        "({self.x}, {self.y})"
    }
}

// Interface bounds
func print_all<T: Display>(items: [T]) {
    for item in items {
        print(item.display())
    }
}

// Multiple bounds
func process<T: Display + Debug + Clone>(item: T)

// Associated types
trait Iterator {
    type Item
    func next(var self) -> Self.Item?
}

// Interface inheritance (supertraits)
trait CustomCopy: Deinit {
    func copy(self) -> Self
    // Implementing CustomCopy requires also implementing Deinit
}

// Interface objects (dynamic dispatch)
func render(shapes: [dyn Shape]) {
    for shape in shapes {
        shape.draw()
    }
}
```

### Type Definitions

```saw
// Type definitions create distinct types (not interchangeable aliases)
type UserId = Int64
type OrderId = Int64

// Even with same underlying type, they are distinct
let user: UserId = UserId(42)
let order: OrderId = user  // Error! Types are not compatible

// Useful for units and domain types
type Miles = Float64
type Kilometers = Float64

let m: Miles = Miles(100.0)
let k: Kilometers = m  // Error! Can't mix miles and kilometers

// Access underlying value with .value
let raw: Float64 = m.value

// Type definitions for function signatures
type Callback = (Int) -> Bool
type Handler<T> = (T) -> Result<(), Error>
```

### Type Extensions

Extensions allow adding methods and custom initializers to types. Currently implemented for user-defined structs.

```saw
// Add methods to struct types
extension Point {
    // Immutable method (self passed by value)
    func distance_from_origin(self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutable method (var self passed by pointer)
    func scale(var self, factor: Float64) {
        self.x *= factor
        self.y *= factor
    }

    // Custom initializer (overloaded by parameter names)
    init(magnitude: Float64) -> Point {
        Point(x: magnitude, y: magnitude)
    }

    // Another custom initializer
    init(polar: Float64, angle: Float64) -> Point {
        Point(
            x: polar * angle.cos(),
            y: polar * angle.sin()
        )
    }
}

// Usage
var p = Point(x: 3.0, y: 4.0)     // Default field init
p.scale(2.0)                       // Mutates p
let d = p.distance_from_origin()  // Read-only

let p2 = Point(magnitude: 5.0)    // Custom init
let p3 = Point(polar: 10.0, angle: 1.57)  // Another custom init

// Future: Built-in type extensions (not yet implemented)
// extension Int {
//     func is_even(self) -> Bool { self % 2 == 0 }
// }

// Future: Computed properties (not yet implemented)
// extension String {
//     var is_empty: Bool { self.len() == 0 }
// }

// Future: Interface conformance via extension (not yet implemented)
// extension Point: Display {
//     func display(self) -> String { "({self.x}, {self.y})" }
// }
```

**Key Features:**
- Methods can be immutable (`self`) or mutable (`var self`)
- Custom `init` methods return the struct type
- Multiple `init` methods distinguished by parameter names
- Mutable methods receive `self` as a pointer for efficient mutation
- Field assignment supported: `self.field = value`

---

## 4. Memory Management

### Ownership Model

Saw uses copy-by-default semantics with explicit move for transferring ownership:

```saw
// All types are copied by default
let s1 = String.from("hello")
let s2 = s1  // s1 is copied, both valid

// Explicit move transfers ownership
let s3 = move s1  // s1 is moved, no longer valid
use_string(move s3)  // Transfer ownership to function

// Move is useful for:
// - Large types where copy is expensive
// - Types representing unique resources (file handles, connections)
// - Ensuring single ownership semantics

// Copy happens automatically for all assignments
let a = 42
let b = a  // Copy
let list = [1, 2, 3]
let list2 = list  // Copy (deep copy for collections)
```

### Move-Only Types

Some types represent unique resources that should not be copied. Use the `NoCopy` trait:

```saw
// Implement NoCopy trait for move-only semantics
struct FileHandle: NoCopy {
    fd: Int,
}

extension FileHandle {
    func open(path: String) -> Result<FileHandle, IoError> { ... }

    func deinit(var self) {
        close(self.fd)  // Automatic cleanup
    }
}

// NoCopy types must be explicitly moved
let file = FileHandle.open("data.txt")?
let file2 = file       // Error! Cannot copy NoCopy type
let file2 = move file  // Ok, ownership transferred

// Useful for resources that need cleanup
struct Connection: NoCopy { ... }
struct MutexGuard<T>: NoCopy { ... }
```

See [Resource Management Interfaces](#resource-management-traits) for the full `Deinit`/`CustomCopy`/`NoCopy` hierarchy.

### Passing by Reference

Use `var` parameters to allow a function to mutate the caller's value. At the call site, use `&` to indicate the variable may be modified:

```saw
// var parameter: function can mutate caller's value
func append_greeting(s: var String) {
    s.push_str(", world!")
}

var msg = String.from("Hello")
append_greeting(&msg)  // & indicates msg may be mutated
print(msg)  // "Hello, world!"

// Multiple var parameters
func swap<T>(a: var T, b: var T) {
    let temp = a
    a = b
    b = temp
}

var x = 1
var y = 2
swap(&x, &y)  // x is now 2, y is now 1

// Regular parameters are copied (caller's value unchanged)
func process(s: String) {
    // s is a copy, modifications don't affect caller
}

let original = "hello"
process(original)  // original is copied, unchanged
```

### Shared Ownership

For data that needs multiple owners, use reference-counted wrappers. These implement `CustomCopy` to increment the reference count on copy and `deinit` to decrement it:

```saw
// Reference counting (single-threaded shared ownership)
let shared: Rc<Data> = Rc(Data { ... })
let shared2 = shared  // copy() called, ref count increases

// Atomic reference counting (thread-safe shared ownership)
let atomic: Arc<Data> = Arc(Data { ... })

// Send Arc across threads
thread.spawn {
    let local = atomic  // Safe to share across threads
    process(local)
}

// Box for heap allocation without sharing
let boxed: Box<LargeStruct> = Box(LargeStruct { ... })
```

### Synchronized Access

For mutable shared state, wrap in synchronization primitives. Lock guards implement `NoCopy` so they can't be shared, and `deinit` to automatically release the lock:

```saw
// Mutex for exclusive mutable access
let counter: Arc<Mutex<Int>> = Arc(Mutex(0))

thread.spawn {
    var guard = counter.lock()  // Returns MutexGuard: NoCopy
    *guard += 1
}  // guard.deinit() called, lock released automatically

// RwLock for multiple readers or single writer
let data: Arc<RwLock<Map<String, Int>>> = Arc(RwLock(Map()))

// Read lock (shared)
let guard = data.read()
let value = guard.get("key")

// Write lock (exclusive)
var guard = data.write()
guard.insert("key", 42)
```

### Resource Management Interfaces

Saw provides a hierarchy of traits for types that need custom copy behavior or cleanup when going out of scope. This enables reference counting (like `Arc<T>`), RAII patterns (like file handles), and move-only types.

#### The Deinit Interface

```saw
// Called automatically when a value goes out of scope
trait Deinit {
    func deinit(var self)
}
```

The compiler inserts `deinit()` calls at all scope exit points—including normal exits, early returns, breaks, and error propagation.

**Important:** Manual `deinit()` calls are not allowed. Calling `obj.deinit()` is a compile-time error to prevent double-free and use-after-free bugs. For early cleanup, use a nested scope or `move` the value to a consuming function.

#### The CustomCopy Interface

```saw
// Interface inheritance: CustomCopy requires Deinit
trait CustomCopy: Deinit {
    func copy(self) -> Self
}
```

Types implementing `CustomCopy` use the `copy()` method instead of memcpy when assigned. This enables reference counting:

```saw
struct Arc<T>: CustomCopy {
    ptr: *ArcInner<T>  // Points to { refcount: Int, value: T }
}

extension Arc<T> {
    func copy(self) -> Arc<T> {
        self.ptr.refcount = self.ptr.refcount + 1
        Arc(ptr: self.ptr)
    }

    func deinit(var self) {
        self.ptr.refcount = self.ptr.refcount - 1
        if self.ptr.refcount == 0 {
            self.ptr.value.deinit()
            free(self.ptr)
        }
    }
}

// Usage
let a = Arc.new(42)  // refcount = 1
let b = a            // copy() called, refcount = 2
// end of scope: b.deinit() → refcount = 1
// end of scope: a.deinit() → refcount = 0, freed
```

#### The NoCopy Interface (Move-Only Types)

```saw
// Interface inheritance: NoCopy requires Deinit
trait NoCopy: Deinit {
    // Marker trait - no methods
}
```

Types implementing `NoCopy` cannot be copied—only moved. The compiler errors on assignment; use `move` to transfer ownership:

```saw
struct File: NoCopy {
    handle: Int
}

extension File {
    func open(path: String) -> Result<File, IoError> { ... }

    func deinit(var self) {
        close(self.handle)
    }
}

let f = File.open("data.txt")?
let g = f        // Error: Cannot copy NoCopy type 'File'
let g = move f   // Ok: f is now invalid
use(f)           // Error: f was moved
// g.deinit() called at scope exit, file closed
```

#### Summary of Type Behaviors

| Interface | Copy Behavior | Cleanup |
|-----------|---------------|---------|
| (none) | memcpy | none |
| `CustomCopy` | calls `copy()` | calls `deinit()` |
| `NoCopy` | compile error | calls `deinit()` |

#### Containment Rules

If a struct contains fields that implement `Deinit`, `CustomCopy`, or `NoCopy`, the struct must also implement that trait. This ensures resource management is never silently skipped:

```saw
struct Connection {
    socket: File       // File implements NoCopy
    config: Config     // plain type
}
// Error: Connection contains NoCopy field but doesn't implement NoCopy

// Fix: explicitly implement NoCopy
extension Connection: NoCopy {
    func deinit(var self) {
        // Your cleanup code here
        // Compiler auto-calls socket.deinit() after your code
    }
}
```

The containment rules are:
- **NoCopy containment**: If any field is `NoCopy`, the struct must be `NoCopy`
- **CustomCopy containment**: If any field is `CustomCopy` (and none are `NoCopy`), the struct must be `CustomCopy`
- **Deinit containment**: If any field is `Deinit`, the struct must implement `Deinit`

#### Automatic Field Operations

When you implement these traits, the compiler automatically handles fields:

**In `deinit`**: After your cleanup code runs, the compiler calls `deinit()` on all fields that implement `Deinit`, in reverse declaration order:

```saw
extension Connection: NoCopy {
    func deinit(var self) {
        print("closing connection")
        // Compiler inserts: self.socket.deinit()
    }
}
```

**In struct initialization**: When initializing a struct, `copy()` is automatically called on any `CustomCopy` fields that come from existing variables:

```saw
extension Container: CustomCopy {
    func copy(self) -> Container {
        Container(data: self.data)  // Compiler calls self.data.copy()
    }
    func deinit(var self) { }
}
```

---

## 5. Error Handling

Saw uses `Result<T, E>` for recoverable errors with `try` expressions for ergonomic handling. Errors are explicit in function signatures—no hidden control flow.

### Result Type

```saw
// Built-in generic enum
enum Result<T, E> {
    case Ok(value: T),
    case Err(error: E)
}

// Custom error types are just structs
struct IoError {
    code: Int
}

struct ParseError {
    line: Int
    message: String
}

// Functions declare error types explicitly in return type
func read_file(path: String) -> Result<String, IoError> {
    // ...
}
```

### Auto-Wrap Returns

In functions returning `Result<T, E>`, values are automatically wrapped:

```saw
func parse_number(valid: Bool) -> Result<Int, ParseError> {
    if valid {
        return 42  // Auto-wrapped to Ok(value: 42)
    }
    return ParseError(line: 1, message: "invalid")  // Auto-wrapped to Err(error: ...)
}

// Rules:
// - Return T → wraps in Ok(value: T)
// - Return E → wraps in Err(error: E)
// - Return Result<T, E> → no wrapping
```

### Try Variants

The `try` keyword has three forms:

```saw
// try - propagate error to caller (function must return Result)
func load_data() -> Result<Data, IoError> {
    let content = try read_file("data.txt")  // Propagates IoError if Err
    return parse(content)
}

// try? - convert Result to Optional (None on Err)
let maybe_content: String? = try? read_file("data.txt")

// try! - force unwrap (panics on Err)
let content = try! read_file("data.txt")  // Panics if Err
```

### Inline Catch

Handle errors locally with inline `catch`:

```saw
// Provide fallback value on error
let content = try read_file("config.txt") catch { "default config" }

// Access error in catch block
let content = try read_file("config.txt") catch {
    print("Error code: {error.code}")
    "default config"
}
```

### Block Try-Catch

For multiple operations that may fail:

```saw
try {
    let config = try read_config()
    let data = try load_data(config)
    process(data)
} catch {
    print("Error: {error.code}")
}
```

The implicit `error` variable is available in the catch block.

### Multiple Error Types

When a try block contains operations with different error types, use `match` to handle them:

```saw
struct IoError { code: Int }
struct ParseError { line: Int }

func read_file(path: String) -> Result<String, IoError> { ... }
func parse_config(content: String) -> Result<Config, ParseError> { ... }

func load_config() {
    try {
        let content = try read_file("config.txt")
        let config = try parse_config(content)
        use(config)
    } catch {
        // error is auto-wrapped in a union enum
        match error {
            case IoError(e) -> print("IO error: {e.code}"),
            case ParseError(e) -> print("Parse error at line: {e.line}")
        }
    }
}
```

The compiler automatically creates a union type for multiple error types, allowing pattern matching in the catch block.

### Explicit Result Handling

You can always handle `Result` explicitly with `match`:

```saw
match read_file("data.txt") {
    case Ok(content) -> process(content),
    case Err(e) -> print("Error: {e.code}")
}
```

### Panic for Unrecoverable Errors

```saw
// Panic halts execution (unrecoverable)
func get_index(arr: [Int], i: Int) -> Int {
    if i >= arr.len() {
        panic("Index {i} out of bounds")
    }
    arr[i]
}
```

### Summary

| Syntax | Behavior | Return Type |
|--------|----------|-------------|
| `try expr` | Unwrap Ok, propagate Err to caller | `T` |
| `try? expr` | Unwrap Ok, return None on Err | `T?` |
| `try! expr` | Unwrap Ok, panic on Err | `T` |
| `try expr catch { }` | Unwrap Ok, run catch block on Err | `T` |
| `try { } catch { }` | Catch errors from try block | block type |

---

## 6. Concurrency

### Async/Await

```saw
// Async functions return futures
async func fetch_url(url: String) -> Result<Response, HttpError> {
    let connection = connect(url).await?
    connection.get("/").await
}

// Concurrent execution
async func fetch_all(urls: [String]) -> [Result<Response, HttpError>] {
    // Spawn concurrent tasks
    let tasks = urls.map { url in spawn { fetch_url(url).await } }

    // Wait for all
    join_all(tasks).await
}

// Select first completed
async func race_fetch(primary: String, backup: String) -> Response {
    select {
        result = fetch_url(primary).await => result,
        result = fetch_url(backup).await => result,
    }
}
```

### Threads and Channels

```saw
// Spawn OS thread
let handle = thread.spawn {
    heavy_computation()
}
let result = handle.join()

// Channels for message passing
let (tx, rx) = channel.create<Message>()

thread.spawn {
    tx.send(Message.Data(42))
}

match rx.receive() {
    Message.Data(n) => print("Got {n}"),
    Message.Done => break,
}

// Buffered channels
let (tx, rx) = channel.buffered<Int>(100)
```

### Shared State

See [Synchronized Access](#synchronized-access) in Memory Management for `Mutex` and `RwLock` usage with `Arc` for thread-safe shared state.

### Send and Sync Interfaces

```saw
// Types that can be sent between threads
trait Send {}

// Types that can be safely shared between threads
trait Sync {}

// Compiler enforces thread safety
func spawn<F: FnOnce() + Send>(f: F) -> JoinHandle
```

---

## 7. Metaprogramming

### Generics

```saw
// Generic struct
struct Container<T> {
    value: T,
}

// Const generics
struct Array<T, const N: Int> {
    data: [T; N],
}

let arr: Array<Int, 5> = Array()

// Where clauses for complex bounds
func merge<T, U, V>(a: T, b: U) -> V
where
    T: Into<V>,
    U: Into<V>,
    V: Merge,
{
    V.merge(a.into(), b.into())
}
```

### Compile-Time Evaluation

```saw
// Const functions evaluated at compile time
const func factorial(n: Int) -> Int {
    if n <= 1 { 1 } else { n * factorial(n - 1) }
}

const FACT_10: Int = factorial(10)

// Compile-time assertions
static_assert(size_of<MyStruct>() <= 64, "Struct too large")
```

### Macros

```saw
// Declarative macros (pattern-based)
macro vec[$($elem:expr),*] {
    {
        var v = Vec()
        $(v.push($elem);)*
        v
    }
}

let nums = vec![1, 2, 3, 4]

// Derive macros (code generation)
#[derive(Debug, Clone, PartialEq)]
struct User {
    name: String,
    age: Int,
}

// Attribute macros
#[test]
func test_addition() {
    assert_eq(2 + 2, 4)
}

#[inline(always)]
func hot_path() { ... }
```

### Compile-Time Reflection

```saw
// Type introspection at compile time
const func field_names<T>() -> [String] {
    T.fields().map { f in f.name }
}

// Generate serialization automatically
#[derive(Serialize)]
struct Config {
    host: String,
    port: Int,
}
```

---

## 8. Module System

### Module Declaration

```saw
// In lib.saw (package root)
module parser      // Loads parser.saw or parser/module.saw
module compiler
public module runtime  // Public module

// Inline module
module helpers {
    public func utility() { ... }
}
```

### Visibility

```saw
// Private by default
struct Internal { ... }

// Public
public struct Public { ... }

// Public within package only
public(package) func internal_api() { ... }

// Public to parent module
public(parent) func parent_visible() { ... }
```

### Imports

Imports follow Python-style semantics - only the explicitly named symbol is added to the namespace:

```saw
// Import a module - adds 'io' to namespace
import std.io
io.open("file.txt")     // Access via module name

// Import specific symbols - adds only those names
import std.collections.{Map, Set}
let m = Map()           // Map is directly available
let s = Set()           // Set is directly available

// Import a single symbol
import std.io.File
let f = File.open("data.txt")

// Aliasing
import std.collections.HashMap as Map
import std.io as fileio
fileio.open("file.txt")

// Import from current package
import package.parser.Parser
import parent.helpers.utility

// Glob import (discouraged, makes dependencies unclear)
import std.prelude.*
```

### Package Structure

```
my_project/
├── Saw.toml          # Package manifest
├── src/
│   ├── lib.saw       # Library root
│   ├── main.saw      # Binary root
│   ├── parser.saw
│   └── compiler/
│       ├── module.saw
│       ├── lexer.saw
│       └── codegen.saw
├── tests/
│   └── integration.saw
└── examples/
    └── demo.saw
```

---

## 9. Standard Library Overview

### Core Types

```saw
std.option.{Option, Some, None}
std.result.{Result, Ok, Err}
std.string.String
std.vec.Vec
std.collections.{Map, Set, Deque}
```

### I/O

```saw
std.io.{Read, Write, Seek}
std.fs.{File, Path, read_to_string, write}
std.net.{TcpStream, TcpListener, UdpSocket}
```

### Concurrency

```saw
std.thread.{spawn, sleep, current}
std.sync.{Mutex, RwLock, Arc, Barrier}
std.channel.{channel, Sender, Receiver}
std.future.{Future, async, await}
```

### Utilities

```saw
std.fmt.{format, Display, Debug}
std.iter.{Iterator, IntoIterator}
std.cmp.{Ord, PartialOrd, Eq, PartialEq}
std.hash.{Hash, Hasher}
std.time.{Instant, Duration}
```

---

## 10. Interoperability

### C FFI

```saw
// Declare external C functions
extern "C" {
    func printf(format: *Char, ...) -> Int
    func malloc(size: UInt) -> *var Void
    func free(ptr: *var Void)
}

// Export for C
#[no_mangle]
public extern "C" func my_function(x: Int32) -> Int32 {
    x * 2
}

// C-compatible types
#[repr(C)]
struct CStruct {
    x: Int32,
    y: Int32,
}
```

### Unsafe Code

```saw
// Opt-out of safety guarantees
unsafe {
    let ptr = malloc(100)
    *ptr = 42
    free(ptr)
}

// Unsafe functions must be called in unsafe blocks
unsafe func dangerous() {
    // Raw pointer operations
    // Calling external functions
    // Accessing mutable statics
}

// Unsafe traits
unsafe trait GlobalAlloc {
    unsafe func alloc(layout: Layout) -> *var Void
    unsafe func dealloc(ptr: *var Void, layout: Layout)
}
```

---

## 11. Future Considerations

### Potential Features for Later Versions

1. **Effect system** - Track side effects in types
2. **Dependent types** - Types that depend on values
3. **Linear types** - Ensure resources are used exactly once
4. **First-class modules** - Modules as values
5. **Algebraic effects** - Structured control flow effects
6. **Refinement types** - Types with predicates (`Int where self > 0`)

---

## Appendix A: Keywords

```
and         as          async       await       break
catch       const       continue    deinit      defer
do          dyn         else        enum        extension
extern      false       func        for         guard
if          import      in          init        trait
let         loop        macro       match       module
move        none        not         or          package
parent      public      ref         return      self
Self        some        static      struct      true
try         type        unsafe      var         where
while
```

## Appendix B: Operators

```
Arithmetic:     +  -  *  /  %  **
Comparison:     == != <  >  <= >=
Logical:        && || !
Bitwise:        &  |  ^  ~  << >>
Assignment:     =  += -= *= /= %= &= |= ^= <<= >>=
Range:          ..  ..=
Optional:       ?  ??  ?.  !
Reference:      &  *
Type:           ->  =>  ::  .
```

---

*This specification is a living document. Details will be refined through iteration and implementation experience.*

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
fn add(a: Int, b: Int) -> Int {
    a + b  // implicit return for last expression
}

// Multiple return values via tuples
fn divide(a: Int, b: Int) -> (quotient: Int, remainder: Int) {
    (a / b, a % b)
}

// Generic functions
fn swap<T>(a: var T, b: var T) {
    let temp = a
    a = b
    b = temp
}

// Functions with default parameters
fn greet(name: String, greeting: String = "Hello") -> String {
    "{greeting}, {name}!"
}

// Trailing closure syntax
fn map<T, U>(list: [T], transform: fn(T) -> U) -> [U]

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
fn process(input: String?) {
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

// Methods
extension Point {
    // Initializer (called via Type(...) syntax)
    init(x: Float64, y: Float64) {
        self.x = x
        self.y = y
    }

    // Instance method (immutable self)
    fn magnitude(self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method
    fn translate(var self, dx: Float64, dy: Float64) {
        self.x += dx
        self.y += dy
    }
}

// Usage - objects created with Type(...) syntax
var p = Point(3.0, 4.0)
p.translate(1.0, 1.0)
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

### Traits (Interfaces)

```saw
trait Display {
    fn display(self) -> String
}

trait Debug {
    fn debug(self) -> String {
        // Default implementation
        "<opaque>"
    }
}

// Trait implementation
extension Display for Point {
    fn display(self) -> String {
        "({self.x}, {self.y})"
    }
}

// Trait bounds
fn print_all<T: Display>(items: [T]) {
    for item in items {
        print(item.display())
    }
}

// Multiple bounds
fn process<T: Display + Debug + Clone>(item: T)

// Associated types
trait Iterator {
    type Item
    fn next(var self) -> Self.Item?
}

// Trait objects (dynamic dispatch)
fn render(shapes: [dyn Shape]) {
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
type Callback = fn(Int) -> Bool
type Handler<T> = fn(T) -> Result<(), Error>
```

### Type Extensions

Extensions allow adding new functionality to existing types, including types from external libraries.

```saw
// Add methods to existing types
extension Int {
    fn is_even(self) -> Bool {
        self % 2 == 0
    }

    fn squared(self) -> Int {
        self * self
    }
}

let x = 42
x.is_even()    // true
x.squared()    // 1764

// Add computed properties
extension String {
    var is_empty: Bool {
        self.len() == 0
    }

    var reversed: String {
        self.chars().reverse().collect()
    }
}

// Add trait conformance via extension
extension Point: Display {
    fn display(self) -> String {
        "({self.x}, {self.y})"
    }
}

// Conditional extensions (only when constraints are met)
extension Vec<T> where T: Numeric {
    fn sum(self) -> T {
        self.fold(T.zero, { acc, x in acc + x })
    }
}

// Extensions can add initializers
extension String {
    init(repeating: Char, count: Int) {
        self = ""
        for _ in 0..count {
            self.push(repeating)
        }
    }
}

let stars = String(repeating: '*', count: 5)  // "*****"
```

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

Some types represent unique resources that should not be copied:

```saw
// Mark a type as move-only with @move attribute
@move
struct FileHandle {
    fd: Int,
}

extension FileHandle {
    fn open(path: String) -> Result<FileHandle, IoError> { ... }
    fn close(self) { ... }  // Takes ownership, closes file
}

// Move-only types must be explicitly moved
let file = FileHandle.open("data.txt")?
let file2 = file       // Error! FileHandle is move-only
let file2 = move file  // Ok, ownership transferred

// Useful for resources that need cleanup
@move
struct Connection { ... }

@move
struct MutexGuard<T> { ... }
```

### Passing by Reference

Use `var` parameters to allow a function to mutate the caller's value. At the call site, use `&` to indicate the variable may be modified:

```saw
// var parameter: function can mutate caller's value
fn append_greeting(s: var String) {
    s.push_str(", world!")
}

var msg = String.from("Hello")
append_greeting(&msg)  // & indicates msg may be mutated
print(msg)  // "Hello, world!"

// Multiple var parameters
fn swap<T>(a: var T, b: var T) {
    let temp = a
    a = b
    b = temp
}

var x = 1
var y = 2
swap(&x, &y)  // x is now 2, y is now 1

// Regular parameters are copied (caller's value unchanged)
fn process(s: String) {
    // s is a copy, modifications don't affect caller
}

let original = "hello"
process(original)  // original is copied, unchanged
```

### Shared Ownership

For data that needs multiple owners, use reference-counted wrappers:

```saw
// Reference counting (single-threaded shared ownership)
let shared: Rc<Data> = Rc(Data { ... })
let shared2 = shared  // Both point to same data, ref count increases

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

For mutable shared state, wrap in synchronization primitives:

```saw
// Mutex for exclusive mutable access
let counter: Arc<Mutex<Int>> = Arc(Mutex(0))

thread.spawn {
    var guard = counter.lock()
    *guard += 1
}  // Lock released when guard goes out of scope

// RwLock for multiple readers or single writer
let data: Arc<RwLock<Map<String, Int>>> = Arc(RwLock(Map()))

// Read lock (shared)
let guard = data.read()
let value = guard.get("key")

// Write lock (exclusive)
var guard = data.write()
guard.insert("key", 42)
```

---

## 5. Error Handling

### Result Type

```saw
enum Result<T, E> {
    Ok(T),
    Err(E),
}

fn read_file(path: String) -> Result<String, IoError> {
    // ...
}

// Explicit handling
match read_file("data.txt") {
    Ok(content) => process(content),
    Err(e) => print("Error: {e}"),
}

// Propagation operator
fn load_config() -> Result<Config, Error> {
    let content = read_file("config.json")?  // Returns early on error
    parse_json(content)?
}

// Map and combinators
let result = read_file("data.txt")
    .map(|s| s.to_uppercase())
    .unwrap_or("default")
```

### Panic for Unrecoverable Errors

```saw
// Panic halts execution (unrecoverable)
fn get_index(arr: [Int], i: Int) -> Int {
    if i >= arr.len() {
        panic("Index {i} out of bounds for length {arr.len()}")
    }
    arr[i]
}

// Assert for invariants
assert(x > 0, "x must be positive")
debug_assert(expensive_check())  // Only in debug builds
```

### Custom Error Types

```saw
enum ParseError {
    InvalidSyntax(line: Int, column: Int),
    UnexpectedToken(String),
    EndOfInput,
}

extension Error for ParseError {
    fn message(self) -> String {
        match self {
            InvalidSyntax(line, col) => "Syntax error at {line}:{col}",
            UnexpectedToken(tok) => "Unexpected token: {tok}",
            EndOfInput => "Unexpected end of input",
        }
    }
}
```

---

## 6. Concurrency

### Async/Await

```saw
// Async functions return futures
async fn fetch_url(url: String) -> Result<Response, HttpError> {
    let connection = connect(url).await?
    connection.get("/").await
}

// Concurrent execution
async fn fetch_all(urls: [String]) -> [Result<Response, HttpError>] {
    // Spawn concurrent tasks
    let tasks = urls.map { url in spawn { fetch_url(url).await } }

    // Wait for all
    join_all(tasks).await
}

// Select first completed
async fn race_fetch(primary: String, backup: String) -> Response {
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

### Send and Sync Traits

```saw
// Types that can be sent between threads
trait Send {}

// Types that can be safely shared between threads
trait Sync {}

// Compiler enforces thread safety
fn spawn<F: FnOnce() + Send>(f: F) -> JoinHandle
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
fn merge<T, U, V>(a: T, b: U) -> V
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
const fn factorial(n: Int) -> Int {
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
fn test_addition() {
    assert_eq(2 + 2, 4)
}

#[inline(always)]
fn hot_path() { ... }
```

### Compile-Time Reflection

```saw
// Type introspection at compile time
const fn field_names<T>() -> [String] {
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
    public fn utility() { ... }
}
```

### Visibility

```saw
// Private by default
struct Internal { ... }

// Public
public struct Public { ... }

// Public within package only
public(package) fn internal_api() { ... }

// Public to parent module
public(parent) fn parent_visible() { ... }
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
    fn printf(format: *Char, ...) -> Int
    fn malloc(size: UInt) -> *var Void
    fn free(ptr: *var Void)
}

// Export for C
#[no_mangle]
public extern "C" fn my_function(x: Int32) -> Int32 {
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
unsafe fn dangerous() {
    // Raw pointer operations
    // Calling external functions
    // Accessing mutable statics
}

// Unsafe traits
unsafe trait GlobalAlloc {
    unsafe fn alloc(layout: Layout) -> *var Void
    unsafe fn dealloc(ptr: *var Void, layout: Layout)
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
const       continue    defer       do          dyn
else        enum        extension   extern      false
fn          for         guard       if          impl
import      in          init        let         loop
macro       match       module      move        none
not         or          package     parent      public
ref         return      self        Self        some
static      struct      trait       true        type
unsafe      var         where       while
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

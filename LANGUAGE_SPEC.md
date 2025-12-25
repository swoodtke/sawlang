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
fn swap<T>(a: mut T, b: mut T) {
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
fn process(input: ?String) {
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

// Dictionaries
let ages: Map<String, Int> = ["alice": 30, "bob": 25]

// Sets
let uniques: Set<Int> = {1, 2, 3}
```

### Structs

```saw
// Value type (copied by default)
struct Point {
    x: Float64,
    y: Float64,
}

// Methods
impl Point {
    // Associated function (constructor)
    fn new(x: Float64, y: Float64) -> Self {
        Point { x, y }
    }

    // Instance method (immutable self)
    fn magnitude(self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method
    fn translate(mut self, dx: Float64, dy: Float64) {
        self.x += dx
        self.y += dy
    }
}

// Usage
var p = Point.new(3.0, 4.0)
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
    Move { x: Int, y: Int },
    Write(String),
    Color(Int, Int, Int),
}

// Pattern matching on enums
match message {
    Message.Quit => quit(),
    Message.Move { x, y } => move_to(x, y),
    Message.Write(text) => print(text),
    Message.Color(r, g, b) => set_color(r, g, b),
}
```

### Optionals

```saw
// Optional type (no null!)
let maybe: ?Int = some(42)
let nothing: ?Int = none

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
impl Display for Point {
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
    fn next(mut self) -> ?Self.Item
}

// Trait objects (dynamic dispatch)
fn render(shapes: [dyn Shape]) {
    for shape in shapes {
        shape.draw()
    }
}
```

### Type Aliases and Newtypes

```saw
// Type alias
type UserId = Int64
type Callback = fn(Int) -> Bool

// Newtype (distinct type, not just alias)
newtype Miles(Float64)
newtype Kilometers(Float64)

// Can't accidentally mix them
let m: Miles = Miles(100.0)
let k: Kilometers = m  // Error!
```

---

## 4. Memory Management

### Ownership Model

Saw uses Rust-style ownership with some ergonomic improvements:

```saw
// Each value has exactly one owner
let s1 = String.from("hello")
let s2 = s1  // s1 is moved, no longer valid

// Clone for explicit copy
let s3 = s2.clone()

// Small types are Copy by default (Int, Float, Bool, etc.)
let a = 42
let b = a  // Copy, both valid
```

### References and Borrowing

```saw
// Immutable reference (can have many)
fn len(s: &String) -> Int {
    s.bytes().count()
}

// Mutable reference (exclusive access)
fn push(s: &mut String, c: Char) {
    s.append(c)
}

// Borrowing rules:
// 1. Any number of immutable references, OR
// 2. Exactly one mutable reference
// Never both at the same time

let mut s = String.from("hello")
let r1 = &s      // ok
let r2 = &s      // ok
let r3 = &mut s  // Error! Can't borrow mutably while immutable refs exist
```

### Lifetimes

```saw
// Explicit lifetimes when needed (often inferred)
fn longest<'a>(a: &'a String, b: &'a String) -> &'a String {
    if a.len() > b.len() { a } else { b }
}

// Lifetime in structs
struct Parser<'src> {
    source: &'src String,
    position: Int,
}

// Simplified syntax for common patterns
fn first_word(s: &String) -> &String  // Lifetime elided
```

### Smart Pointers

```saw
// Unique ownership (heap allocation)
let boxed: Box<LargeStruct> = Box.new(LargeStruct { ... })

// Reference counting (shared ownership)
let shared: Rc<Data> = Rc.new(data)
let clone = shared.clone()  // Increases ref count

// Atomic reference counting (thread-safe)
let atomic: Arc<Data> = Arc.new(data)

// Interior mutability
let cell: Cell<Int> = Cell.new(0)
cell.set(42)

let ref_cell: RefCell<Vec<Int>> = RefCell.new([])
ref_cell.borrow_mut().push(1)
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
    InvalidSyntax { line: Int, column: Int },
    UnexpectedToken(String),
    EndOfInput,
}

impl Error for ParseError {
    fn message(self) -> String {
        match self {
            InvalidSyntax { line, col } => "Syntax error at {line}:{col}",
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

```saw
// Mutex for exclusive access
let counter: Mutex<Int> = Mutex.new(0)

thread.spawn {
    let mut guard = counter.lock()
    *guard += 1
}  // Lock released when guard goes out of scope

// RwLock for multiple readers
let data: RwLock<Map<String, Int>> = RwLock.new(Map.new())

// Read lock (shared)
let guard = data.read()
let value = guard.get("key")

// Write lock (exclusive)
let mut guard = data.write()
guard.insert("key", 42)
```

### Send and Sync Traits

```saw
// Types that can be sent between threads
trait Send {}

// Types that can be shared between threads via references
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

let arr: Array<Int, 5> = Array.new()

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
        let mut v = Vec.new()
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
// In lib.saw (crate root)
mod parser;      // Loads parser.saw or parser/mod.saw
mod compiler;
pub mod runtime; // Public module

// Inline module
mod helpers {
    pub fn utility() { ... }
}
```

### Visibility

```saw
// Private by default
struct Internal { ... }

// Public
pub struct Public { ... }

// Public within crate only
pub(crate) fn internal_api() { ... }

// Public to parent module
pub(super) fn parent_visible() { ... }
```

### Imports

```saw
// Use declarations
use std.collections.{Map, Set}
use std.io.{Read, Write}
use crate.parser.Parser
use super.helpers.utility

// Aliasing
use std.collections.HashMap as Map

// Glob import (discouraged except for preludes)
use std.prelude.*
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
│       ├── mod.saw
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
    fn malloc(size: UInt) -> *mut Void
    fn free(ptr: *mut Void)
}

// Export for C
#[no_mangle]
pub extern "C" fn my_function(x: Int32) -> Int32 {
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
    unsafe fn alloc(layout: Layout) -> *mut Void
    unsafe fn dealloc(ptr: *mut Void, layout: Layout)
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
const       continue    crate       defer       do
dyn         else        enum        extern      false
fn          for         guard       if          impl
in          let         loop        macro       match
mod         move        mut         newtype     none
not         or          pub         ref         return
self        Self        some        static      struct
super       trait       true        type        unsafe
use         var         where       while
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
Reference:      &  &mut  *
Type:           ->  =>  ::  .
```

---

*This specification is a living document. Details will be refined through iteration and implementation experience.*

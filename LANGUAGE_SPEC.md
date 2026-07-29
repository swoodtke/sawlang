# Saw Language Specification

> A modern systems programming language combining the safety of Rust with the elegance of Swift

## Status markers

This specification mixes shipped behavior with designed-but-unbuilt features.
Each major section is tagged so it can be read as an oracle for the current
compiler:

- **Status: implemented** — built and covered by the test suite (`make test`).
  Code examples use real, currently-compiling syntax.
- **Status: partially implemented** — the core is built; specific sub-features
  called out inline are not yet. Examples that reach into unbuilt stdlib or
  syntax are marked *(illustrative)*.
- **Status: planned** — designed, not yet built. Examples are *illustrative* of
  intended syntax and may not compile today.
- **Status: superseded** — an earlier design that has been replaced; the
  replacement is named.

Where an example is *illustrative*, it shows intended shape, not guaranteed
current behavior. When the implementation and this document disagree, the
implementation wins and this document is the bug.

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

**Status: implemented**, except where a construct is marked *(illustrative)*
below (default parameter values, the array-literal `.map` shorthand shown below,
and the `loop { }` keyword are planned; use `while { }` for infinite loops
today). Note the stdlib `Vector` does provide real `map<U>`/`fold<A>` methods
(see [Generics](#generics)); the illustrative example below is about method
chaining directly on array literals, which is separate and still planned.

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

// Generic functions with mutable-reference parameters
func swap<T>(a: &var T, b: &var T) {
    // (illustrative) — mutation through a &var reference uses compound
    // assignment or mutating methods; direct `a = b` is rejected. A real
    // swap goes through a by-value temporary or a stdlib `swapAt` helper.
}

// Functions with default parameters  (illustrative — default values planned)
func greet(name: String, greeting: String = "Hello") -> String {
    "{greeting}, {name}!"
}

// Trailing closure syntax  (illustrative — method-chained `.map` is planned)
func map<T, U>(list: [T], transform: (T) -> U) -> [U]

let doubled = numbers.map { x in x * 2 }
let doubled = numbers.map { $0 * 2 }  // shorthand
```

**Argument Evaluation Order:**
In a call, arguments are evaluated left to right; for a method call the
receiver is evaluated before the arguments. A by-value argument is
copied (or moved) at evaluation time — a *snapshot* taken at call setup,
before the callee runs. This is what makes a by-value argument that overlaps a
`&var` argument well-defined: the copy captures the pre-call value regardless
of any mutation the callee performs through the reference.

```saw
func f(snapshot: Int, r: &var Int) {
    r += 100
    print(snapshot)   // prints the value of the second arg's target BEFORE the call
}

var b = 1
f(b, &var b)          // snapshot copies b (== 1) at call setup; then b becomes 101
```

### Control Flow

```saw
// If expressions (not statements)
let max = if a > b { a } else { b }

// Pattern matching (core feature). Arms are `case <pattern> -> <expr>`,
// comma-separated. Matches must be exhaustive (cover every enum variant, or
// use `_`).
match direction {
    case North -> "up",
    case South -> "down",
    case _ -> "sideways"
}

// (illustrative — planned) Literal, range, and guard patterns are NOT yet
// implemented. Today you match on enum variants (with binding), Result/Option
// variants, and `_`:
//   match value {
//       case 0 -> "zero",              // literal patterns: planned
//       case 1..=9 -> "single digit",  // range patterns: planned
//       case n if n < 0 -> "negative", // guard patterns: planned
//   }

// For loops over ranges
for i in 0..5 {
    print(i)
}

// While loops (conditional and infinite `while { }`)
while condition {
    // ...
}

// Infinite loop as an expression with a break value.
// (The `loop { }` keyword is planned; use `while { }` today.)
let result = while {
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

**Status: partially implemented.** Structs, enums (ADTs) with exhaustive
`match`, tuples, fixed arrays, optionals, `Result`, distinct `type` aliases,
traits, and generic types/functions with monomorphization are all built (see
the subsection notes). Planned pieces called out below: slices (`&a[1..4]`),
`Set`/dictionary literals, `dyn` trait objects, trait default methods,
supertrait *enforcement*, and some primitive widths. Stdlib methods used only
to illustrate (e.g. `.sqrt()`) are marked *(illustrative)*.

### Primitive Types

Common types — `Int`, `UInt`, the sized `Int8`…`Int64`/`UInt8`…`UInt64`,
`Float`/`Float64`, `Bool`, and `String` — are implemented. `Int128`/`UInt128`,
`Float32`, `Char`, and `Never` are *planned*.

```saw
// Integers
Int8, Int16, Int32, Int64, Int128
UInt8, UInt16, UInt32, UInt64, UInt128
Int    // Platform-native signed — pointer width (i64 on 64-bit, i32 on riscv32)
UInt   // Platform-native unsigned — pointer width

// Floating point
Float32, Float64
Float  // Alias for Float64

// Other primitives
Bool        // true, false
Char        // Unicode scalar value
String      // Immutable, refcounted byte string (see "String" below)
Never       // Bottom type (function never returns)
```

**`Int`/`UInt` are pointer-width** (Swift's model, design 47): 64-bit on
x86-64/aarch64, **32-bit on riscv32** (e.g. ESP32-P4). `Int` is the type of an
index, a length, a size (`sizeof`/`alignof`), and an address, so it matches the
machine word on every target — no forced 64-bit instruction pairs or 64-bit
division libcalls (`__divdi3`) on a 32-bit chip. Consequently:

- The representable **range of `Int` (its max/min) is target-dependent**:
  `-2^63 … 2^63 - 1` on a 64-bit target, `-2^31 … 2^31 - 1` on riscv32 (and
  likewise `UInt`'s max). Code that must reason about a specific range should use
  a fixed-width type. (`Int.max`/`Int.min` named constants are not yet provided.)
- An **integer literal is a platform `Int`**; a literal that does not fit the
  target word is a compile error *at the literal* (so `9_999_999_999` compiles on
  a 64-bit host but is rejected under a 32-bit target).
- **Use the fixed-width types (`Int8`…`Int64`, `UInt8`…`UInt64`) for anything
  whose layout must be stable across targets** — wire formats, on-disk
  structures, and device/MMIO register maps. Their widths never change, and D1's
  checked arithmetic makes any narrow-width overflow a loud panic rather than a
  silent wrap. `Int64` is the escape hatch for a value wider than a 32-bit word.

### String

`String` is an **immutable, reference-counted byte string**. A `String` value is
a single pointer; copying one (binding it, passing it, storing it) is a cheap
refcount bump, and the buffer is freed deterministically when the last owner
goes away. Because it is `ImplicitCopy + Deinit`, strings flow through the
language with no `move` discipline — `greet(s)` does not consume `s`.

- **Representation.** One heap block `{ refcount, len, bytes…, NUL }`; the value
  points at `bytes`, with the header at negative offsets. The buffer stays
  NUL-terminated for zero-copy C FFI, and `len` is authoritative (O(1),
  interior NUL bytes are representable). The buffer is immutable after
  construction: concatenation and interpolation build fresh buffers (an
  `s + t` loop is O(n²); a mutable `StringBuilder` is future stdlib work).
- **UTF-8 guarantee.** A `String` always holds valid UTF-8. Two doors admit
  bytes and both enforce it: **string literals** are validated for free — source
  files are decoded as UTF-8 before lexing and there are no byte/`\x`/`\u`
  escape sequences, so an invalid-UTF-8 literal cannot be written (should byte
  escapes ever be added, they must validate at lex time — TODO); and
  **`String.fromBytes(data: &Data) -> Result<String, Utf8Error>`** copies raw
  bytes into a fresh string after a full runtime UTF-8 scan (rejecting invalid
  lead/continuation bytes, overlong encodings, UTF-16 surrogates, scalars beyond
  U+10FFFF, and truncated sequences). `Utf8Error.offset` is the byte index where
  the first malformed sequence begins (bytes before it decode cleanly —
  `valid_up_to()` semantics). Validation is written in Saw, not the compiler.
- **Access views, never `s[i]`.** There is deliberately no integer indexing (it
  conflates bytes with scalars). Two iterator views are provided instead:
  `bytes()` yields the raw bytes (`Int8`, matching `byte_at`) and `chars()`
  yields Unicode scalar values decoded from UTF-8. Scalars are yielded as `Int` —
  there is no `Char` primitive type yet, and ordering comparisons / a
  `Comparable` trait are a separate future decision (not built). Each iterator
  holds its OWN retain on the source string, so iterating a temporary
  (`for c in makeString().chars()`) is safe.
- **FFI: `withCString`.** `s.withCString { ptr in ... }` hands a closure an
  `UnsafePointer<Int8>` to the string's NUL-terminated bytes, valid for the
  duration of the call. The payload is already NUL-terminated, so the pointer is
  passed directly with no copy. The closure is a **non-escaping** parameter (the
  default, per the closures design): the compiler forbids it from being stored or
  outliving the call, which is the whole safety story — the borrowed pointer
  cannot leak. The closure returns `Void`; a result is produced by
  borrow-capturing an enclosing variable
  (`s.withCString { [&var n] ptr in n = strlen(ptr) }`).
- **The refcount is atomic** (`i64`), from day one. This is a deliberate cost
  paid up front so `String` is `Send`-ready before multithreading lands, so the
  concurrency milestone does not have to relitigate the memory model. The
  ordering protocol is the standard `Arc` discipline — immutability does *not*
  exempt the decrement:
  - **retain** (a copy): `atomicrmw add` **relaxed/monotonic** — a live
    reference already keeps the object alive, so no ordering is needed;
  - **release** (a drop): `atomicrmw sub` **release**; the thread that observes
    the count reach zero issues an **acquire fence**, then runs deinit / frees
    (ordering every other thread's final reads before the free);
  - **immortal literals**: string literals are static blocks with a sentinel
    refcount of `-1`, checked with a plain (non-atomic) load *before* any atomic
    op. Literals are never retained or released, so the common case pays zero
    atomic traffic.

### Composite Types

```saw
// Tuples
let point: (Int, Int) = (10, 20)
let named: (x: Int, y: Int) = (x: 10, y: 20)
let x = point.0
let y = named.y

// Arrays (fixed size, stack allocated)
let fixed: [Int; 5] = [1, 2, 3, 4, 5]

// A fixed array `[T; N]` inherits T's copy class (see The Copy Trait Family):
// `[Int; 5]` is trivially copyable, so `let b = fixed` bitwise-copies it. An
// array of `ExplicitCopy` elements is itself `ExplicitCopy` (move to transfer,
// `.copy()` to duplicate per element); an array of `NoCopy` elements is
// move-only. Owned elements are destroyed in reverse index order at scope death.

// Slices (view into contiguous memory)  (illustrative — slices are planned)
let slice: [Int] = &fixed[1..4]

// Vectors (dynamic, heap allocated) — stdlib `Vector<T>`, constructed via its
// initializers (`Vector<Int>(capacity: n)`) rather than a literal today.

// Dictionaries / Sets with `{ }` literals are planned:
//   let ages: Map<String, Int> = {"alice": 30, "bob": 25}   (illustrative)
//   let uniques: Set<Int> = {1, 2, 3}                        (illustrative)
//   let empty_map: Map<String, Int> = {:}                    (illustrative)
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

    // Instance method (immutable reference to self)
    func magnitude(&self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method (mutable reference to self)
    func translate(&var self, dx: Float64, dy: Float64) {
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
// Variants are introduced with the `case` keyword.

// Simple enum
enum Direction {
    case North,
    case South,
    case East,
    case West
}

// Enum with associated data
enum Message {
    case Quit,
    case Move(x: Int, y: Int),   // Named parameters
    case Write(text: String),    // Single associated value
    case Color(r: Int, g: Int, b: Int)
}

// Creating enum values
let msg1 = Message.Move(x: 10, y: 20)
let msg2 = Message.Color(r: 255, g: 128, b: 0)

// Pattern matching on enums: `case <Variant>(bindings) -> <expr>`, bare variant
// name (not `Message.Quit`), comma-separated, exhaustive.
match msg1 {
    case Quit -> quit(),
    case Move(x, y) -> move_to(x, y),
    case Write(text) -> print(text),
    case Color(r, g, b) -> set_color(r, g, b)
}
```

### Optionals

```saw
// Optional type (no null!) - T? syntax like Swift. A plain value of type T is
// implicitly wrapped into T?; the empty case is the keyword `None` (there is no
// `some(...)`/`none` constructor).
let maybe: Int? = 42
let nothing: Int? = None

// Optional chaining
let len = user?.profile?.bio?.len()

// Unwrap with default
let value = maybe ?? 0

// Force unwrap (panics with "force unwrap of None" if the value is None)
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

Trait definitions, conformance via `extension Type: Trait`, conformance
checking, single and multiple conformance, associated types (with resolution),
and `T: Trait` generic bounds are **implemented**. Trait *default method
bodies*, `dyn Trait` dynamic-dispatch objects, and multi-bound `+` syntax
(`T: A + B`) are *planned* — the examples below that use them are illustrative.

```saw
trait Display {
    func display(&self) -> String
}

trait Debug {
    func debug(&self) -> String {
        // Default implementation  (illustrative — default bodies are planned)
        "<opaque>"
    }
}

// Interface implementation via extension
extension Point: Display {
    func display(&self) -> String {
        "({self.x}, {self.y})"
    }
}

// Interface bounds
func print_all<T: Display>(items: [T]) {
    for item in items {
        print(item.display())
    }
}

// Multiple bounds  (illustrative — `+` multi-bound syntax is planned)
func process<T: Display + Debug + Clone>(item: T)

// Associated types
trait Iterator {
    type Item
    func next(&var self) -> Self.Item?
}

// Interface inheritance (supertraits)
trait ImplicitCopy: Deinit {
    func copy(&self) -> Self
    // Implementing ImplicitCopy requires also implementing Deinit
}

// Interface objects (dynamic dispatch)  (illustrative — `dyn` objects planned)
func render(shapes: [dyn Shape]) {
    for shape in shapes {
        shape.draw()
    }
}
```

### Type Definitions

**Status: implemented** for distinct `type` aliases with one-way flow (alias →
underlying allowed, the reverse requires explicit construction) and function-type
aliases. Generic type aliases (`type Handler<T> = ...`) are *planned*.

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

**Status: implemented** for user-defined structs (methods, overloaded custom
`init`, and — see Traits — conformance via `extension Type: Trait`).
Extending built-in types (`extension Int`), computed properties, and generic
specialized extensions beyond what monomorphization already supports remain
*planned*. Some method bodies below use stdlib methods (`.sqrt()`, `.cos()`)
that are *(illustrative)*.

```saw
// Add methods to struct types
extension Point {
    // Immutable method (reference to self)
    func distance_from_origin(&self) -> Float64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutable method (mutable reference to self)
    func scale(&var self, factor: Float64) {
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
//     func is_even(&self) -> Bool { self % 2 == 0 }
// }

// Future: Computed properties (not yet implemented)
// extension String {
//     var is_empty: Bool { self.len() == 0 }
// }

// Interface conformance via extension IS implemented:
extension Point: Display {
    func display(&self) -> String { "({self.x}, {self.y})" }
}
```

**Key Features:**
- Methods use `&self` (immutable reference) or `&var self` (mutable reference)
- Custom `init` methods return the struct type
- Multiple `init` methods distinguished by parameter names
- Mutable methods receive a reference for efficient mutation
- Field assignment supported: `self.field = value`

---

## 4. Memory Management

**Status: implemented** (the Copy trait family, `Deinit`, exclusivity, and
reference parameters are all built and enforced). No garbage collector;
destruction is deterministic and LIFO at scope exit.

### The Copy Trait Family

**Status: implemented.** Saw's transfer semantics are governed by one umbrella
trait, `Copy`, with two mutually-exclusive policy subtraits deciding *when* the
compiler may duplicate a value. This replaces the earlier "copy by default,
explicit move" framing and the never-implemented "deep copy for collections"
claim: the cost of every transfer is now readable at the use site.

```
                Copy                 "this type can be duplicated" (func copy(&self) -> Self)
               /    \
     ImplicitCopy    ExplicitCopy    policy: WHEN the compiler may call copy()
```

- **Trivial types auto-conform to `Copy`.** A type all of whose fields are
  trivially copyable, with no `Deinit` and no declared copy policy, is copied
  bitwise. `Int`, `Bool`, `Float`, POD structs/tuples, and fixed arrays of such
  are in this class. `x.copy()` on them compiles to a bitwise copy.
- **`ImplicitCopy`** — the compiler invokes `copy()` automatically at every
  transfer site (binding, assignment, argument, return, aggregate element).
  **Contract: cheap, O(1)-ish** — e.g. a refcount bump. `String` and `Rc`/`Arc`
  are `ImplicitCopy`.
- **`ExplicitCopy`** — the compiler *never* copies implicitly; a transfer out of
  an existing binding requires `move`, and duplication is always a visible
  `v.copy()`. **Contract: may be expensive/deep** — e.g. `Vector`, `Map`.
  Enforcement is the value-transfer checkpoint (the same machinery that backs
  `NoCopy`).
- **`NoCopy`** — never duplicable, on purpose (`File`, `Mutex`). Move-only.
- **Every declared policy trait extends `Deinit`**: `ImplicitCopy`,
  `ExplicitCopy`, and `NoCopy` all require a `deinit(&var self)` (declared as
  `trait ImplicitCopy: Deinit` etc. in the builtin prelude). A type opts into
  a policy because it manages a resource, and managing a resource means having
  a destructor — so the trivially-copyable tier is exactly the destructor-free
  tier. A policy type with genuinely nothing to clean up writes an empty
  `deinit`.
- **`ImplicitCopy` and `ExplicitCopy` are mutually exclusive** on one type.

```saw
// Trivial: implicit bitwise copy, both valid
let a = 42
let b = a

// ExplicitCopy (e.g. Vector): transfer needs `move`, duplication needs .copy()
var v = Vector<Int>(capacity: 4)
var w = move v            // ownership transferred; v no longer valid
var u = w.copy()          // explicit, independent deep copy

// ImplicitCopy (String): copies are implicit refcount bumps, no `move` needed
let s1 = "hello"
let s2 = s1               // both valid; cheap retain
```

**The `T: Copy` generic bound** grants `.copy()` in a generic body and is
satisfied by trivial | `ImplicitCopy` | `ExplicitCopy` types; monomorphization
synthesizes the right tier per instantiation. Narrower `T: ImplicitCopy` /
`T: ExplicitCopy` bounds also work. An unbounded `T` does **not** get `.copy()`.

```saw
func dup<T: Copy>(x: T) -> T {
    x.copy()
}
```

**Derivation & containment.** A struct declaring `ExplicitCopy`/`ImplicitCopy`
without a hand-written `copy()` gets a memberwise one synthesized (POD fields
bitwise, copy-policy fields via their `copy()`; a `NoCopy` field makes
derivation impossible). Containment is explicit, never inferred: a struct with
an `ExplicitCopy` (or `NoCopy`) field must itself declare that policy — the
compiler errors with a hint otherwise. Containment looks *through* array-typed
fields: a struct holding a `[NoCopy; N]` field is move-only and must declare
`NoCopy`, exactly as for a scalar `NoCopy` field.

**Fixed arrays.** A fixed array `[T; N]` is treated as an anonymous struct with
`N` uniform fields: it inherits T's copy class. `[trivial; N]` copies bitwise;
`[ImplicitCopy; N]` copies implicitly per element (each element's `copy()`);
`[ExplicitCopy; N]` is move-by-default and `arr.copy()` duplicates element-by-
element in index order; `[NoCopy; N]` is move-only. Owned elements are released
in **reverse index order** at scope death, composing with the enclosing struct/
enum drop glue. (A `[String; N]` field, like a scalar `String` field, does not
force the container to declare a policy — String's per-element retain/release is
compiler-handled.)

The only implicit copies are cheap by contract, so design principle #4 ("no
hidden allocations") holds: an innocent `=` is never secretly O(n).

### Move-Only Types

Some types represent unique resources that should not be copied. Trait
conformance is declared through an `extension` (there is no struct-header
`struct X: Trait` syntax):

```saw
struct FileHandle {
    fd: Int
}

// Declare NoCopy (and its cleanup) via an extension
extension FileHandle: NoCopy {
    func deinit(&var self) {
        close(self.fd)  // Automatic cleanup at scope exit
    }
}

// NoCopy types must be explicitly moved
var file = openHandle("data.txt")
let borrowed = file    // Error! Cannot copy NoCopy type 'FileHandle'
let owned = move file  // Ok, ownership transferred
```

See [Resource Management Interfaces](#resource-management-traits) for the full `Deinit`/`ImplicitCopy`/`ExplicitCopy`/`NoCopy` hierarchy.

### Reference Types

**Status: implemented.** Reference types (`&T` and `&var T`) allow passing values by reference without copying. References are only valid as function/method parameters and cannot escape. Mutation through a `&var` reference is done with compound assignment (`x += 1`) or mutating methods — direct assignment `x = ...` through a reference is rejected. Some example bodies below use planned stdlib methods (`push_str`, `String.from`) and are *(illustrative)*.

```saw
// &T - immutable reference (read-only access)
func print_length(s: &String) {
    print(s.len())  // Can read through reference
}

let msg = "Hello"
print_length(&msg)  // Pass reference with &

// &var T - mutable reference (allows modification)
func append_greeting(s: &var String) {
    s.push_str(", world!")  // Can mutate through reference
}

var msg = String.from("Hello")
append_greeting(&var msg)  // &var mirrors the &var parameter
print(msg)  // "Hello, world!"

// Multiple reference parameters. (The body is illustrative: because direct
// assignment through a reference is rejected, a real swap uses a by-value
// temporary or a stdlib helper.)
func swap<T>(a: &var T, b: &var T) { /* ... */ }

var x = 1
var y = 2
swap(&var x, &var y)  // x is now 2, y is now 1

// Regular parameters are copied (caller's value unchanged)
func process(s: String) {
    // s is a copy, modifications don't affect caller
}

let original = "hello"
process(original)  // original is copied, unchanged
```

**Reference Semantics:**
- References auto-dereference on read: `x` where `x: &Int` gives the `Int` value
- Mutable references allow compound assignment: `x += 1` where `x: &var Int`
- Direct assignment through references is not allowed: `x = 5` is an error
- Moving out of references is not allowed: `move x` where `x: &var T` is an error
- References cannot escape: cannot return, store in structs, or capture in closures

**Call-site reference sigils:** the call site mirrors the parameter's reference
spelling. `&x` lends immutably to a `&T` parameter; `&var x` lends mutably to a
`&var T` parameter. A mismatch in **either** direction is a compile error
(`&x` to a `&var T` parameter, or `&var x` to a `&T` parameter), and `&var x`
additionally requires `x` to be a `var` binding. A `&var` reference is only
valid as a call/method/init argument — it cannot be stored, returned, or bound
to a variable. This completes the sigil symmetry across types (`&T`/`&var T`),
receivers (`&self`/`&var self`), closure capture (`&v`/`&var v`), and call
sites.

```saw
func readIt(x: &Int) -> Int { x }
func bump(y: &var Int) { y += 1 }

var b = 5
bump(&var b)        // OK — &var mirrors the &var parameter
// bump(&b)         // error: parameter `y` is `&var Int`; write `&var b`
// readIt(&var b)   // error: parameter `x` is `&Int`; write `&b`
```

**Method Self:**
Methods use reference syntax for self:
```saw
extension Point {
    func magnitude(&self) -> Float64 { ... }      // Immutable reference
    func translate(&var self, dx: Float64) { ... } // Mutable reference
}
```

**The Law of Exclusivity (many readers XOR one writer):**
In a single call, an access path passed *mutably* — a `&var` argument, or the
receiver of a `&var self` method — must be **disjoint** from every other
by-reference path in that call. Immutable `&` paths may overlap each other
freely: with no writer in the call, the shared storage is immutable for the
callee's duration, so the aliasing is unobservable. A `move` argument may not
alias any reference argument in the same call.

```saw
func swap(a: &var Int, b: &var Int) { ... }

var x = 0
swap(&x, &x)          // error: `x` is passed as `&var` while also aliased
swap(&x, &y)          // ok: distinct roots

var p = Point(x: 1, y: 2)
f(&var p, &p.x)       // error: `p` overlaps its field `p.x`
f(&var p.x, &p.y)     // ok: disjoint fields (the rule is path-disjointness,
                      //     not one reference per variable)
g(&x, &x)             // ok when both parameters are immutable `&` (shared reads)
```

This check is **fully static** and needs no lifetimes or runtime flags.
Because references cannot escape in Saw (they are only parameters — never
returned, stored in fields, or captured by reference; closures capture by
value), every live reference was created at some call expression on the stack.
Two references can therefore only alias if they were passed in the same call
chain, and forwarding is covered by applying the same rule at *every* call
site: inside a callee its `var` parameters are distinct storage, and the only
way they could alias is if the caller aliased them — which the caller's own
call-site check rejects.

Access paths compared for disjointness are `x`, `x.f`, `x.0`, and `x[i]`:
same root with differing fields, tuple indices, or differing *constant* array
indices are disjoint; different roots are always disjoint. A non-constant
(dynamic) array index is treated conservatively — `swap(&var a[i], &a[j])` is
rejected even when `i != j` at runtime (a checked `a.swapAt(i, j)` stdlib
method is the intended escape hatch).

> **Invariant (for future features):** the fully-static guarantee rests on the
> no-escape property. If closures capturing by reference, returned/stored
> references, or globally-reachable mutable variables are ever added, they must
> either preserve no-escape or be folded into the call-site disjointness check;
> otherwise this law weakens from *sound* to *advisory*.

### Shared Ownership

**Status: planned** (the examples below are illustrative; `Rc`/`Arc`/`Box`
wrapper types and `thread.spawn` are not yet in the stdlib). The `ImplicitCopy`
+ `Deinit` machinery they rely on *is* implemented and is exactly how `String`
works today.

For data that needs multiple owners, use reference-counted wrappers. These implement `ImplicitCopy` to increment the reference count on copy and `deinit` to decrement it:

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

**Status: planned** (illustrative — `Mutex`/`RwLock`, lock guards, and threads
are not yet implemented).

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

**Status: implemented.** Saw provides a hierarchy of traits for types that need
custom copy behavior or cleanup when going out of scope. This enables reference
counting (like `String` and the planned `Arc<T>`), deep-copy owning types (like
`Vector`), RAII patterns (like file handles), and move-only types. Conformance
is always declared through an `extension` (`extension T: Trait`); there is no
struct-header conformance syntax. The full family is `Copy`
(umbrella) → `ImplicitCopy` / `ExplicitCopy` policies, plus `Deinit` and
`NoCopy`; see [The Copy Trait Family](#the-copy-trait-family) above for the
transfer-site rules.

#### The Deinit Interface

```saw
// Called automatically when a value goes out of scope
trait Deinit {
    func deinit(&var self)
}
```

The compiler inserts `deinit()` calls at all scope exit points—including normal exits, early returns, breaks, and error propagation.

**Important:** Manual `deinit()` calls are not allowed. Calling `obj.deinit()` is a compile-time error to prevent double-free and use-after-free bugs. For early cleanup, use a nested scope or `move` the value to a consuming function.

#### The ImplicitCopy Interface

```saw
// Interface inheritance: ImplicitCopy requires Deinit
trait ImplicitCopy: Deinit {
    func copy(&self) -> Self
}
```

Types implementing `ImplicitCopy` use the `copy()` method instead of memcpy at
every transfer site (the copy is implicit and must be cheap by contract). This
enables reference counting; the conformance is declared in the extension:

```saw
struct Arc<T> {
    ptr: *ArcInner<T>  // Points to { refcount: Int, value: T }
}

extension Arc<T>: ImplicitCopy {
    func copy(&self) -> Arc<T> {
        self.ptr.refcount += 1
        Arc(ptr: self.ptr)
    }

    func deinit(&var self) {
        self.ptr.refcount -= 1
        if self.ptr.refcount == 0 {
            self.ptr.value.deinit()
            free(self.ptr)
        }
    }
}

// Usage
let a = makeArc(42)  // refcount = 1
let b = a            // copy() called, refcount = 2
// end of scope: b.deinit() → refcount = 1
// end of scope: a.deinit() → refcount = 0, freed
```

#### The ExplicitCopy Interface (Deep-Copy Owning Types)

```saw
// ExplicitCopy also requires Deinit; mutually exclusive with ImplicitCopy
trait ExplicitCopy: Deinit {
    func copy(&self) -> Self
}
```

Types implementing `ExplicitCopy` are **never** copied implicitly — the
compiler demands `move` at a transfer out of an existing binding, and any
duplication is a visible `v.copy()`. This is the policy for expensive,
resource-owning types such as `Vector` and `Map`. Enforcement reuses the
`NoCopy` value-transfer checkpoint, with its own diagnostic:

```saw
extension Buf: ExplicitCopy {
    func copy(&self) -> Buf { /* deep copy */ }
    func deinit(&var self) { /* free buffer */ }
}

var a = makeBuf()
var b = a          // Error: cannot copy value of type `Buf` which implements
                   //        ExplicitCopy — use .copy() or `move`
var c = a.copy()   // Ok: explicit, independent deep copy
var d = move a     // Ok: ownership transferred, a no longer valid
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
struct File {
    handle: Int
}

extension File: NoCopy {
    func deinit(&var self) {
        close(self.handle)
    }
}

var f = openFile("data.txt")
let g = f        // Error: Cannot copy NoCopy type 'File'
let h = move f   // Ok: f is now invalid
use(f)           // Error: f was moved
// h.deinit() called at scope exit, file closed
```

#### Summary of Type Behaviors

| Kind | Transfer (`let b = a`) | `.copy()` | Cleanup |
|------|------------------------|-----------|---------|
| trivial / POD (auto-`Copy`) | implicit bitwise copy | bitwise | none |
| `ImplicitCopy` | implicit `copy()` (cheap) | yes | `deinit()` |
| `ExplicitCopy` | **error** — needs `move` | yes (visible) | `deinit()` |
| `NoCopy` | **error** — needs `move` | no | `deinit()` |

#### Containment Rules

If a struct contains fields that implement `Deinit`, `ImplicitCopy`, or `NoCopy`, the struct must also implement that trait. This ensures resource management is never silently skipped:

```saw
struct Connection {
    socket: File       // File implements NoCopy
    config: Config     // plain type
}
// Error: Connection contains NoCopy field but doesn't implement NoCopy

// Fix: explicitly implement NoCopy
extension Connection: NoCopy {
    func deinit(&var self) {
        // Your cleanup code here
        // Compiler auto-calls socket.deinit() after your code
    }
}
```

The containment rules are:
- **NoCopy containment**: If any field is `NoCopy`, the struct must be `NoCopy`
- **ExplicitCopy containment**: If any field is `ExplicitCopy`, the struct must declare `ExplicitCopy` (or `NoCopy`)
- **ImplicitCopy containment**: If any field is `ImplicitCopy` (and none are `NoCopy`/`ExplicitCopy`), the struct must be `ImplicitCopy`
- **Deinit containment**: If any field is `Deinit`, the struct must implement `Deinit`

#### Automatic Field Operations

When you implement these traits, the compiler automatically handles fields:

**In `deinit`**: After your cleanup code runs, the compiler calls `deinit()` on all fields that implement `Deinit`, in reverse declaration order:

```saw
extension Connection: NoCopy {
    func deinit(&var self) {
        print("closing connection")
        // Compiler inserts: self.socket.deinit()
    }
}
```

**In struct initialization**: When initializing a struct, `copy()` is automatically called on any `ImplicitCopy` fields that come from existing variables:

```saw
extension Container: ImplicitCopy {
    func copy(&self) -> Container {
        Container(data: self.data)  // Compiler calls self.data.copy()
    }
    func deinit(&var self) { }
}
```

---

## 5. Error Handling

**Status: implemented** — `Result<T, E>`, auto-wrap returns (with the `T == E`
ambiguity rejected, design 30), `try`/`try?`/`try!`, inline `catch`, block
`try { } catch { }` with the implicit `error` variable, the closed unnameable
multiple-error-type union with `match` (design 30), and explicit `match` on
`Result`.

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

| Returned value | Declared return | Result |
|----------------|-----------------|--------|
| value of type `T` | `Result<T, E>`, `T != E` | wraps in `Ok(value:)` |
| value of type `E` | `Result<T, E>`, `T != E` | wraps in `Err(error:)` |
| a `Result<T, E>` value | `Result<T, E>` | returned unchanged |
| value of type `T` (== `E`) | `Result<T, E>`, `T == E` | **compile error** (ambiguous) |

When the Ok and Err types are the *same concrete type*, a bare `return expr`
of that type is ambiguous — auto-wrap cannot tell which variant is meant — and
is rejected. Write the explicit variant instead:

```saw
func divide(a: Int, b: Int) -> Result<Int, Int> {
    if b == 0 {
        return Result<Int, Int>.Err(error: -1)
    }
    return Result<Int, Int>.Ok(value: a / b)   // bare `return a / b` is an error
}
```

Generic bodies are unaffected: a generic `Result<T, E>` function decides the
wrap abstractly against its declared parameters (a `T`-typed value → `Ok`, an
`E`-typed value → `Err`) and monomorphizes that choice consistently, even when
an instantiation makes `T == E`.

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

### The error union

When a `try { } catch { }` block propagates **more than one** error type, the
implicit `error` variable has a compiler-synthesized **closed enum** over
exactly the error types propagated in that block. Its observable semantics:

- **Closed and exact.** `match error` must be exhaustive over exactly the
  propagated (deduplicated) set of error types — no catch-all is required. A
  `case _ ->` may be added but is not needed, and omitting a propagated type is
  a compile error.
- **Deduplicated.** If the block propagates the *same* error type more than
  once, that is a single-error-type block: `error` keeps that one concrete,
  nameable type (see below), not a union.
- **Unnameable.** The union type cannot be written in surface syntax. It
  therefore cannot appear in any signature, field, return type, or annotation —
  escape is prevented structurally rather than by a special rule. Attempting to
  return `error` from a function, for example, fails to type-check because no
  written return type is compatible with the union. Local inferred bindings
  (`let e = error`) are permitted and harmless.

```saw
try {
    let a = try read_file("config.txt")     // IoError
    let b = try parse_config(a)              // ParseError
    use(b)
} catch {
    // `error` : closed union over { IoError, ParseError }
    let e = error                            // ok: local inferred binding
    match e {                                // must cover both; no catch-all needed
        case IoError(io) -> print("io: {io.code}"),
        case ParseError(p) -> print("parse: {p.line}")
    }
}
```

**Single error type.** When a try block propagates only one error type (after
deduplication), `error` is that concrete, nameable type — no union is formed —
so its fields are accessible directly (e.g. `error.code`).

### Explicit Result Handling

You can always handle `Result` explicitly with `match`:

```saw
match read_file("data.txt") {
    case Ok(content) -> process(content),
    case Err(e) -> print("Error: {e.code}")
}
```

### Panic for Unrecoverable Errors

Panics halt execution (unrecoverable). The compiler emits them for `try!`/
force-unwrap failures and division by zero (see Runtime Semantics). The example
below is *(illustrative)* — an explicit `panic(...)` builtin and `.len()` on a
fixed array are illustrative of intent.

```saw
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

### Integer Arithmetic Semantics

**Status: implemented (design 31).**

- **Overflow panics — always, in every build profile.** `+`, `-`, and `*` on
  any integer type (signed or unsigned), unary negation of a signed minimum
  (`-Int.min`), and the `INT_MIN / -1` division case all **panic** at runtime
  with an "integer overflow" message. The behavior is identical at `-O0` and the
  default `O1` pipeline — the optimizer never elides a check. Overflow joins the
  existing panic family (division by zero, force-unwrap, `try!`) and routes
  through the same `saw_panic` seam, so it works freestanding.
- **Division and modulo**: `a / 0` and `a % 0` **panic** with a "division by
  zero" message rather than raising a hardware fault. `INT_MIN / -1` and
  `INT_MIN % -1` **panic** with "integer overflow" — the modulo result is
  mathematically zero but is defined to panic for consistency with division.
- **Intentional wraparound** is spelled with the **wrapping operators
  `&+`, `&-`, `&*`** (Swift-style): defined two's-complement wrap, no check,
  **integer operands only** (a `Float` operand is a type error). Each is a
  single token (no interior whitespace), sharing the precedence of its checked
  counterpart (`&+`/`&-` add-tier, `&*` multiply-tier). They are unambiguous
  against a call-site reference `&x` (a prefix position) and a bare binary `&`.
- **Float arithmetic** is untouched: IEEE semantics (inf/nan), no overflow trap.

### Bitwise and Shift Operators

**Status: implemented (design 50).**

- **Operators.** Binary `&` (AND), `|` (OR), `^` (XOR), the shifts `<<` / `>>`,
  and the unary complement `~`, plus the compound forms `&= |= ^= <<= >>=`.
  **Integer operands only** — a `Float` or `Bool` operand is a type error (`Bool`
  uses the logical `&&`/`||`/`not`). The result takes the left operand's type.
- **Precedence** is C-family (see Appendix B): shifts bind tighter than
  comparison but looser than `+ -`; among the bitwise operators `&` binds tighter
  than `^`, which binds tighter than `|`. So `a | b & c` == `a | (b & c)` and
  `x << 2 + 1` == `x << (2 + 1)`.
- **Shift range is checked.** A shift amount that is **negative or `>=` the left
  operand's bit width panics** with "shift out of range" — the same
  checked-by-default house rule as arithmetic overflow (Rust-debug precedent).
  Wrapping-shift variants are not shipped.
- **`>>` is arithmetic on signed, logical on unsigned.** A signed left operand
  sign-extends (`ashr`); an unsigned left operand zero-fills (`lshr`). `<<` is a
  plain logical shift for both.
- **Integer literals** may be written in hex (`0xFF`), binary (`0b1010`), or
  octal (`0o755`), and any integer literal may use `_` digit separators
  (`0xDEAD_BEEF`, `1_000_000`). A literal is a **platform `Int`** (pointer-width,
  design 47): one that does not fit the target word is a compile error at the
  literal — so a value beyond `2^32` compiles on a 64-bit host but is rejected
  under a 32-bit target. Use a wider fixed-width field type for such constants.

### Runtime Semantics and Traps

**Status: implemented.**

- **Force-unwrap of `None`** (`opt!`) panics with "force unwrap of None".
  **`try!` on an `Err`** panics, reporting the source line.
- **Fixed-array indexing with an out-of-bounds compile-time constant** is a
  **compile error** ("index out of range"), mirroring the tuple-index check.
  Bounds checking for *dynamic* array indices is not yet implemented.
- **Tuple indexing** past the tuple's arity is a compile error.

### Equality (`Equatable`)

**Status: implemented** (`designs/32-equality.md`). The `Equatable` trait gates
`==` / `!=`; conformance mirrors the Copy family's house rule:

- **Auto-conform:** trivial (POD) structs — the exact set that auto-conforms to
  `Copy` — and payload-free enums. Integers, `Bool`, `Float`, and `String`
  conform builtin.
- **Opt-in with synthesis:** every other struct/enum declares
  `extension T: Equatable {}`. An empty body **synthesizes** the comparison:
  memberwise `&&` for structs, payload-deep for enums (equal tag, then the
  active variant's payload fields, recursively). A hand-written
  `func equals(&self, other: Self) -> Bool` **overrides** the synthesis.
- **Resource types never conform** (`File`, `Mutex`, ...): they are neither
  trivially copyable nor accepted as Equatable conformers.
- Tuples are Equatable iff every element is. A `T: Equatable` generic bound
  grants `==`/`.equals` in a generic body.
- `a == b` on a conforming user type lowers to its `equals`; primitives keep
  direct `icmp`/`fcmp`. `!=` is always the negation of `==`. `String ==` is
  content equality. **Float keeps IEEE semantics** — `NaN != NaN`.
- **Migration note:** payload-carrying enums previously had a tag-only `==`
  (so `Msg.Write("a") == Msg.Write("b")` was wrongly `true`). They now have no
  `==` until they declare `Equatable`, and it is payload-deep.

---

## 6. Concurrency

**Status: partially implemented (stage 1, in progress).** The concurrency model
is defined in `designs/18-async-await.md`; it lands in stages behind a
task-only API (no user-facing thread API — the engine is a swappable
implementation detail and never leaks thread identity). Stage 1
(`designs/21-concurrency-stage1.md`) builds the sharing primitives on a
thread-per-task engine with **no new syntax**. Async/await (stages 2-3) remain
illustrative below.

**Landed in stage 1:**

- **`Send`/`Sync` marker traits**, compiler-known and auto-derived
  *structurally* (the auto-`Copy` pattern), usable as generic bounds
  (`T: Send`). Primitives/`Bool`/`Float`/`String` are `Send + Sync` (`String`'s
  day-one atomic refcount is the designed payoff); a struct/enum is `Send`/`Sync`
  iff all its fields/payloads are; `UnsafePointer<T>` is neither and poisons its
  containers structurally. The wrappers override the structural rule so their raw
  pointers do not poison them: `Arc<T>` is `Send + Sync` iff `T: Send + Sync`;
  `Mutex<T>`/`Channel<T>`/`Task<T>` are `Send`/`Sync` iff `T: Send`. Explicit
  conformance (`extension X: Send`) is rejected — derivation only, no
  unsafe-impl story in v1.
- **`Arc<T>`** — atomic reference-counted shared ownership (`ImplicitCopy +
  Deinit`). One `saw_alloc`'d control block `{ i64 strong, i64 weak, T payload }`;
  the weak count is reserved now as ABI (init 1) even though `Weak` does not ship
  yet. `copy()` retains (atomic add, monotonic); `deinit()` releases (atomic sub,
  release), and the thread that takes strong to 0 issues an acquire fence, runs
  the payload drop glue in place, then releases the collective weak count (at 0:
  acquire fence + free). This is the two-phase protocol of the String section.
- **Reference-typed closure parameters** — `{ &var data in ... }` receives a
  pointer and mutates the referent in place. A closure whose signature has
  reference parameters is **non-storable** (legal only as a direct call
  argument) — the conservative gate ahead of full non-escaping closures.
- **`Mutex<T>`** — `NoCopy + Deinit`, backed by a `pthread_mutex_t` in a
  `saw_alloc`'d block. `lock(body)` runs the closure once, synchronously, with
  `&var` access to the payload under the lock, and is **non-reentrant**
  (self-deadlock on re-lock). The pthread opaque buffer is a conservative
  64-byte slot (real sizes: macOS 64, glibc/x86_64 40, glibc/aarch64 48),
  initialized via `pthread_mutex_init` — never a hardcoded platform struct.
- **Escaping-closure heap environments** — a closure used in value position
  (bound, returned, stored, or passed to `spawn`) outlives its creating frame,
  so its captured environment is `saw_alloc`'d instead of stack-allocated.
  Captures transfer in per the value-transfer rules (ImplicitCopy retained,
  trivial copied bitwise; a move-only capture is rejected), and a generated
  env-destructor runs the captures' drop glue exactly once and frees the block.
  For `spawn` that destructor runs on the task thread after the body returns, so
  a captured `Arc` is retained at capture and released once on the task thread.
  Non-escaping closures (a direct call argument, e.g. `Mutex.lock`'s body) keep
  a stack env. General stored/returned escaping closures currently leak their
  env (documented); full closure `Deinit` is deferred.
- **`Arc<T>` payload method forwarding** — an immutable `&self` method on the
  payload `T` is callable through the `Arc` (`arc.method(...)`): the call borrows
  the control block's payload slot. Sound because a live strong reference pins
  the payload. A `&var self` payload method is rejected (aliased mutation — use
  `Arc<Mutex<T>>`). This gives the `Arc<Mutex<T>>` idiom its access path:
  `arc.lock { ... }` forwards to `Mutex.lock`.
- **`spawn` / `Task<T>`** — `spawn { ... } -> Task<T>` launches the closure on a
  fresh task (hosted pthread-per-task engine; thread identity is never exposed).
  The Send capture-audit walks the closure's captures and rejects the first
  whose type is not `Send`, naming the capture. `Task<T>` is `NoCopy + Deinit`:
  `join` blocks for the result; dropping an unjoined `Task` **joins** it
  (structured concurrency — a task's lifetime is a value's lifetime).
- **`Channel<T: Send>`** — an `ImplicitCopy` handle onto a shared, internally
  refcounted unbounded MPMC queue (cloning the handle shares the queue; the last
  handle drains and frees it). Guarded by an internal pthread mutex + condvar
  (conservative 64-byte condvar slot; real `pthread_cond_t` is ≤48 bytes),
  initialized via `pthread_cond_init` — never a hardcoded struct. `send(v)`
  enqueues under the lock and signals a waiter; `recv() -> T` blocks while empty.
  `T: Send` is enforced on the type at construction.

The atomic-ordering runtime (`__saw_atomic_*`, per the String protocol) is
shared by `Arc` and `Channel`; the `pthread_create`/`join` and condvar wrappers
back `spawn`/`Task` and `Channel`. Under the future cooperative engine, `recv()`
and channel waits become suspension points but keep their shapes; `lock`'s
critical section stays synchronous (a `sync` closure cannot `await`), which is
how the never-block invariant makes holding a lock across `await` a compile
error. Task bodies may suspend under that engine, so a `spawn` closure is not a
`sync` context.

**Status: tasks, channels, Mutex, Send/Sync — implemented (stage 1,
thread-per-task engine). Suspension/cooperative engine — planned.**
There is NO `async`/`await` keyword and there never will be: Saw is
COLORLESS (designs/18 Axis B′). Any call may suspend (once the
cooperative engine lands); the marked side is the rare one — `sync`
contexts are checked suspension-free. Tasks are the ONLY concurrency
primitive: no user-facing threads, no thread identity, ever. The stage-1
engine happens to run one OS thread per task; that is invisible and will
change.

### Suspension and the coroutine transform

**Status: in progress (design 44).** How a suspending function is turned
into a resumable state machine is decided and partly built. The mechanism
is a **source-level transform**: a suspending function becomes an ordinary
synthesized struct — its *frame* — plus a `resume` method that dispatches on
a state field. The frame holds the function's parameters, every local whose
scope spans a suspension point, the state index, and a result slot; its size
is an ordinary compile-time struct size (the enabler for statically-allocated
`.bss` task frames on freestanding targets — the Embassy model). Because the
frame is a normal Saw struct, it is compiled by the same code generator and
the same deterministic-destruction (`Deinit`) machinery as everything else.

Observable rules:

- **What suspends is inferred, not annotated.** A function suspends iff it
  transitively reaches a suspension point; the `sync` effect check
  (design 22) already identifies every such point. No keyword marks it.
- **Frame lifetime / no forced destroy.** A frame dies only by its own code
  reaching an exit — normal completion or a cooperative early `return`. There
  are NO per-suspension-point destroy paths and no way to drop a suspended
  frame from outside (design 18's no-forced-destroy ruling). Locals live at an
  exit are destroyed in LIFO order through ordinary control flow; the one
  special case is a completed frame whose result was never consumed — that
  result is dropped exactly once when the frame dies.
- **Conditional move across a suspension** (design 45 Part 0a). A cleanup-needing
  local moved on some paths but not others is dropped exactly once: its frame
  field carries a drop flag (the optional's `is_some` discriminant) that the move
  clears *without* dropping, so the frame's own `Deinit` skips the moved-out value
  on exactly the paths that moved it.
- **Nested suspending calls embed the callee's frame *by value*** (design 45 Part
  0b): `let x = g(args)` where `g` suspends places `g`'s frame as a field of the
  caller's frame; the caller's state machine drives that sub-frame to `Done`
  across its own suspensions, then captures `g`'s result. Flat frames → whole-task
  size is a compile-time constant.
- **Suspending recursion is a compile error.** A cycle in the suspending-call
  graph would have no finite frame size (frames embed by value), so it is rejected
  with a diagnostic that names the cycle (e.g. `ping -> pong -> ping`). Ordinary
  non-suspending recursion is unaffected.
- **References may span suspensions** (design 18 D6, task confinement): a
  `&`/`&var` parameter — including `&var self` — remains valid and exclusive
  across a suspension, because the whole task suspends and resumes as a unit and
  references cannot escape it. A driven suspending method (design 45 Part 0c)
  holds its receiver as a pointer into the caller's storage and mutates it across
  suspensions; the caller observes the mutation.
- **`deinit` may not suspend** — a destructor is always a `sync` context, so a
  suspension inside one is a compile error (deterministic destruction).
- **Not yet supported** (rejected with a diagnostic, not miscompiled): a
  suspension inside a loop/`if`/`match` body that spans the suspension (needs a
  CFG-based split), and transforming a *generic* suspending function/method
  (blocked on effect-polymorphism re-inference, design 18 A5).

**Suspending `main` and the cooperative executor (design 45 items 1 & 4).** The
real cooperative primitives are `yield_now()` (suspend and become immediately
re-ready) and `sleep(ms)` (suspend with a timed wake). Both are inferred
suspension points. When `main` transitively reaches one, the compiler infers
`main` suspending and auto-wraps it in an **entry executor** with no user-visible
plumbing: `main` becomes a frame + `resume`, and the generated entry drives it to
completion on a single cooperative run, parking the thread for each `sleep` wake
and resuming at once for each `yield_now`. A single task interleaves nothing, so
this is the single-task slice of the executor; multi-task `spawn` with a
heterogeneous run queue, structured join, cancellation, and a suspending
`Channel.receive` are a later stage (they need type-erased task handles, which
the language does not yet provide).

The transform is also still exercisable through a test-only entry: `__suspend()`
marks a synthetic suspension point and `__drive(f(args))` / `__drive_steps(f(args))`
/ `__drive(recv.m(args))` create a frame and step it to completion. A function or
method is transformed only when it is driven (or is a suspending `main`); code
that drives nothing is compiled exactly as before.

### Tasks and Channels

```saw
// Spawn a task (escaping closure; every capture must be Send)
let task = spawn {
    heavy_computation()          // returns Int
}
let result = task.join()         // Task<Int>: NoCopy; deinit joins if unjoined

// Channels: ImplicitCopy handles onto a shared queue
let ch = Channel<Int>()          // Channel<T: Send>
let producer = spawn {
    ch.send(move 42)
    true
}
let got = ch.recv()              // blocks the calling thread (thread-per-task
                                 // engine); a cooperative suspending receive
                                 // is a later stage
producer.join()
```

**Two engines coexist today, deliberately not unified.** `spawn`/`Task`/`Channel`
(design 21b) run on a **thread-per-task** engine: `spawn` starts an OS thread,
`Task.join()`/`Channel.recv()` block that thread, and `Deinit` joins an unjoined
task at scope exit (structured concurrency). Separately, a suspending `main`
runs on the **single-threaded cooperative executor** (above) with `yield_now`/
`sleep`. These are distinct runtimes for now — a cooperative task cannot yet be
`spawn`ed onto the executor (that needs type-erased task handles), and the two do
not share a scheduler. Unifying them (cooperative `spawn`, structured join, and
cancellation on the executor) is a later stage.

### Shared State

`Arc<Mutex<T>>` — see [Synchronized Access](#synchronized-access).
`Mutex.lock`'s closure parameter is a `sync (…)` context: suspending while
holding a lock is a compile error.

### Send and Sync

`Send` ("may move to another task") and `Sync` ("may be shared by
reference across tasks") are compiler-derived STRUCTURALLY — explicit
conformance is rejected. `spawn` audits every capture for Send;
`Channel<T>` requires `T: Send`. `String` is Send+Sync (immutable,
atomic refcount); `UnsafePointer` is neither and poisons containing
types.

### Module-level statics

**Status: implemented (design 41).** A `static` is a module-level
constant-initialized global:

```saw
static MAX_TASKS: Int = 256           // POD scalar → rodata
static PRIMES: [Int; 3] = [2, 3, 5]   // constant fixed-array literal
static ORIGIN: Point = Point(x: 0, y: 0)  // POD struct literal
static SLAB: [Int8; 4096]             // bare declaration → zero-init (BSS)
public static VERSION: Int = 7        // exported; read as `mod.VERSION`
```

Statics obey four rules, ratified in design 19 (Rust's model):

- **Const-initialized only.** The initializer must be a compile-time
  constant: literals, a negated numeric literal, POD struct literals with
  constant fields, constant fixed-array literals, or `Atomic(<int>)`.
  Function calls, `String`, and heap types are rejected. A POD or
  fixed-array static may be declared with NO initializer — it is
  zero-initialized (there is no `[0; N]` repeat literal; bare declaration
  is the mechanism for large zero regions such as slab buffers).
- **Sync-only.** The static's type must be `Sync` (a static is reachable
  from every task). A non-Sync type is a compile error naming the type.
- **Immutable — there is NO `static mut`, ever.** Assigning to a static
  (whole, field, or element) or taking `&var STATIC` is a compile error;
  an `&STATIC` immutable lend is fine. Mutation of global state flows ONLY
  through interior-synchronized types. This makes "all shared mutable
  state is mediated" a language-level theorem.
- **Immortal.** Statics never run `deinit` (const-init keeps `Deinit`
  types out in practice); the OS / reset reclaims them.

Reads elsewhere in the module (or `mod.NAME` from an importer of a
`public` static) behave like an immutable binding.

### `Atomic<Int>`

**Status: implemented (design 41).** `Atomic<Int>` is the minimal
interior-synchronized primitive — the sanctioned way to mutate global
state. It is const-initializable (`Atomic(0)`), usable as a `static` and
as a struct field, and `Sync` by the ordinary structural derivation (a
struct of a `Sync` field). Its methods take an immutable `&self` — the
mutation is interior, which is exactly what lets an immutable static be
updated; the no-`static mut` rule keys on assignment, not on these
method calls.

```saw
static COUNTER: Atomic<Int> = Atomic(0)

func main() {
    let old = COUNTER.fetch_add(1)   // seq_cst RMW; returns the PREVIOUS value
    let now = COUNTER.load()         // seq_cst load
    COUNTER.store(0)                 // seq_cst store
    let swapped = COUNTER.compare_exchange(0, 42)  // -> Bool (success)
}
```

All four operations lower to sequentially-consistent LLVM atomics.

---

## 7. Metaprogramming

**Status: partially implemented** — generics are built (see below); const
evaluation, macros, and compile-time reflection are planned.

### Generics

**Status: implemented.** Generic functions, structs, and enums; `T: Trait`
bounds (including the built-in `T: Copy` / `ImplicitCopy` / `ExplicitCopy`
bounds); generic extensions, including **bounded** extensions
(`extension Vector<T: Copy>: ExplicitCopy { ... }`, used in the stdlib).

Implementation notes:
- **Monomorphization**: each instantiation is a distinct specialized function/
  type; all specialized signatures are declared before any body is generated.
  Names go through one canonical, type-signature-based mangler (nested type
  arguments included).
- **Abstract checking of generic bodies**: a generic body is type-checked once,
  abstractly, against its bounds — so an unused generic with a type error is
  still caught. Two reconciliations are currently *deferred* and only fully
  resolved at instantiation: return-type reconciliation, and bound-aware method
  resolution (a method available only under a specific bound). This is
  documented honestly as a known limitation, not a guarantee.
- Inside a `T: Copy` body, `x.copy()` type-checks (abstractly returns `T`);
  an unbounded `T` does not get `.copy()`.

```saw
// Generic struct
struct Container<T> {
    value: T
}

func identity<T>(x: T) -> T {
    x
}

// A Copy bound grants .copy() in the body; monomorphization emits the right
// tier per instantiation.
func dup<T: Copy>(x: T) -> T {
    x.copy()
}
```

**Method-level generic type parameters.** An extension method may introduce its
own generic type parameters, *in addition to* the type's own — the canonical
case being a transform whose output type is independent of the element type:

```saw
extension Vector<T: Copy, A: Allocator = Global> {
    // `U` is a METHOD-level type parameter, distinct from the element type `T`
    // and the allocator `A` (which the result vector inherits).
    func map<U>(&self, transform: (T) -> U) -> Vector<U, A> { /* ... */ }

    // `Acc` is the accumulator type (named `Acc`, not `A`, since `A` is now
    // the extension's allocator type parameter).
    func fold<Acc>(&self, initial: Acc, combine: (Acc, T) -> Acc) -> Acc { /* ... */ }
}

var v = Vector<Int>()
// ...
let labels = v.map<String> { "n={$0}" }   // Vector<Int> -> Vector<String>
let sum    = v.fold<Int>(0) { $0 + $1 }    // -> Int
```

The method's type arguments are supplied **explicitly** at the call site
(`v.map<String>(...)`) — type-argument **inference is not yet implemented**, so a
generic method requires its `<...>`, exactly like a generic free function, and a
non-generic method rejects type arguments. The method body is checked abstractly
with its own type parameters in scope (the same abstract-body checking as any
generic). Each instantiation monomorphizes per `(receiver type arguments, method
type arguments)` pair; the mangled symbol composes the two
(`Vector<Int>.map<String>` → `Vector$2$Int$Global_map$1$String`). `init` methods
take no type parameters of their own — they construct the extension's type.

**Default type parameters.** A trailing type parameter may declare a **default
type** with `= Type` in the parameter list (types only — there are no value
defaults). A reference site may then omit that (and every following) argument,
and it is filled from the default:

```saw
struct Vector<T, A: Allocator = Global> { /* ... */ }

var xs = Vector<Int>()           // A defaults to Global
var ys = Vector<Int, Global>()   // identical type to `xs`
var zs = Vector<Int, MySlab>()   // a distinct type over a custom allocator
```

The **identity rule** is the load-bearing guarantee: defaults are applied
**before name mangling**, so `Vector<Int>` and `Vector<Int, Global>` produce the
*same* mangled name and the *same* monomorphized struct — they are one type, not
two that happen to coincide. Consequences:
- A function declared over `Vector<Int>` accepts a `Vector<Int, Global>` value,
  and vice-versa — they are interchangeable everywhere.
- A `Vector<Int, MySlab>` is a **distinct type**: passing it where `Vector<Int>`
  is expected is a compile error. Allocator identity is part of the type (this is
  what makes cross-allocator mixing unrepresentable rather than a runtime bug).
- Omitting an argument for a parameter that has **no default** is an arity error,
  and a default that fails its parameter's bound (`A: Allocator = SomeNonAllocator`)
  is rejected. Defaults referencing an earlier parameter are not supported (every
  stdlib default is a ground type such as `Global`).

**Status: planned** — const generics (`struct Array<T, const N: Int>`) and
`where` clauses are *illustrative* below and not yet implemented:

```saw
// (illustrative — planned) Const generics
struct Array<T, const N: Int> {
    data: [T; N]
}

// (illustrative — planned) Where clauses for complex bounds
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

**Status: planned** (illustrative — `const func`, `static_assert`, macros, and
compile-time reflection below are all designed but not implemented).

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

**Status: partially implemented.** `import` (module, specific-symbol, and
qualified forms), inline and external `module` declarations, `public`
visibility, and qualified access (`module.Type`) are built. Scoped visibility
(`public(package)`, `public(parent)`), import aliasing (`as`), and glob imports
(`import x.*`) are *planned* and marked *(illustrative)* below. The `Saw.toml`
package layout is handled by the Blade package manager.

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

// (illustrative — planned) Scoped visibility
public(package) func internal_api() { ... }
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

// (illustrative — planned) Aliasing
import std.collections.HashMap as Map
import std.io as fileio

// Import from current package
import package.parser.Parser
import parent.helpers.utility

// (illustrative — planned) Glob import (discouraged)
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

**Status: partially implemented.** The module *paths* below sketch the intended
namespace layout and are largely *illustrative*. Actually shipped today:
`String`, `Vector<T>`, `Map<K,V>`, `File`, `Directory`, `Path`, `Data`, `Env`,
`Process` (and `Result`/optionals as language features). I/O beyond files, `net`,
`thread`, `sync`, `channel`, `future`, and the `fmt`/`iter`/`cmp`/`hash`/`time`
utility modules are planned.

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

### Profiles (hosted and freestanding)

**Status: freestanding stage 1 implemented.** Saw compiles under two profiles.
The default **hosted** profile links libc and provides everything above. The
**freestanding** profile (`sawc --freestanding`, optionally with `--target
<triple>`) targets kernels and bare-metal: it links no libc and emits an
unlinked object file. In this profile the runtime rests on exactly four seam
symbols the environment must supply at link time — `saw_alloc(size, align)`,
`saw_dealloc(ptr, size, align)`, `saw_write(ptr, len)`, and the noreturn
`saw_panic(msg, len)` — which the hosted profile instead satisfies with weak
libc-backed defaults (overridable at link time without a flag). Freestanding
programs may use `core` and the `alloc`-layer types (`String`, `Vector`, `Map`,
`Data`, `StringBuilder`, `Path`), which allocate only through the seams; the
hosted-only modules (`File`, `Process`, `Env`, `Directory`) and `Float` printing
are unavailable. See `designs/19-freestanding-profile.md` for the full design.

---

## 10. Interoperability

**Status: partially implemented.** `extern "C"` function declarations and the
pointer types `UnsafePointer<T>` / `UnsafeConstPointer<T>` (plus `sizeof<T>()`
and `alignof<T>()` builtins, which fold to the target's ABI size and alignment
of `T` in bytes at monomorphization time) are used by the stdlib today. The
`#[repr(C)]` / `#[no_mangle]`
attributes, C-varargs, `extern "C"` *exports*, and `unsafe` blocks/functions/
traits are *planned* — the examples below using them are illustrative. (The
spec's `*Char`/`*var Void` shorthand is illustrative; the implemented spelling is
`UnsafePointer<T>` / `UnsafeConstPointer<T>`.)

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

### Placement writes (the placement-move primitive)

**Status: implemented (stdlib-internal).** A store through a typed raw pointer —
`ptr[i] = value`, where `ptr: UnsafePointer<T>` — is Saw's **placement-move**
primitive, and it is deliberately *not* the same operation as ordinary
assignment to a live binding. Its exact contract:

- **Bitwise move into the target slot.** The `T` value is moved into the memory
  at `ptr + i` by a raw store. `value` is *consumed* — the same value-transfer
  checkpoint that governs `move`/`.copy()` applies at the store, so the source
  is not usable afterward (a non-`Copy` source must be `move`d in; an
  `ImplicitCopy` source is retained by the checkpoint as usual).
- **No destination release.** Unlike `x = value` on a live binding — which first
  runs the old value's `deinit` — a placement write does **not** deinit whatever
  bytes currently occupy the slot. It assumes the slot is **uninitialized**.
- **Author's obligation.** Because there is no destination release, writing
  through a pointer into a slot that already holds a *live* value **leaks** that
  value (its `deinit` never runs). Placement writes are therefore only sound on
  raw, uninitialized memory (a freshly allocated buffer, or a slot past a
  container's live length). Conversely, using *ordinary* assignment semantics on
  uninitialized memory would be a bug — it would run `deinit` on garbage bytes.
  This primitive exists precisely to avoid that.

The canonical user is **`Vector.push`**: after `grow()` guarantees spare
capacity, `buf[self.length] = value` places the incoming element into the fresh,
never-written tail slot and then bumps `length`. The loop invariant — only ever
writing the slot at the current `length` — is what keeps every placement write
landing on uninitialized memory, so no live element is ever silently leaked.
`Box.make` is the single-slot user: `ptr[0] = move value` into the freshly
allocated chunk.

### Address casts (`&T` → pointer, pointer ↔ `Int`)

**Status: implemented (design 42, stdlib-internal).** Two explicit unsafe casts
bridge references, raw pointers, and integer addresses — the plumbing a slab
allocator needs over a `static` region:

- `(&expr) as UnsafePointer<T>` reinterprets a reference (notably `&STATIC_ARRAY`)
  as a raw pointer to the referent's storage. Both are addresses; the cast is the
  visible unsafe bridge that lets a static region back an allocator.
- `ptr as Int` / `addr as UnsafePointer<T>` round-trip a pointer through its
  integer address (`ptrtoint` / `inttoptr`) — how a slab threads freed-chunk
  addresses through an `Atomic<Int>` free-list.

### `UnsafeMemory<T, Use>` — typed memory at a fixed address

**Status: implemented (design 46).** `UnsafeMemory<T, Use>` is a compiler-known
one-word wrapper over a fixed machine address: a typed view onto memory the
program does not own, for register blocks and board bootstrap regions. It is
const-initialized from an integer literal, `static`-able, and `Sync` by fiat
(the `Atomic` precedent — sharing across tasks is sound; synchronizing the
memory it names is the programmer's responsibility). The `Unsafe` prefix is the
house rule for any type whose ordinary use can violate memory safety.

The second parameter, `Use`, is an **intent marker** and is **explicit always —
there is no default**. The compiler derives the access discipline from it; the
platform derives its configuration obligations from it (cache attributes,
PMP/page tables — the declaration is the coordination point, not a type-level
promise). Two markers exist today:

- **`Device`** — a memory-mapped register block. Accesses lower to **volatile**
  loads/stores, so they are never reordered, merged, or elided. Only scalar
  views may be accessed, through **`read()`** / **`write(v)`**; there is **no
  whole-struct access** (multi-register access is never atomic, and reads can
  have side effects). Within the viewed struct, the layout-transparent field
  markers **`ReadOnly<T>`** and **`WriteOnly<T>`** gate the accessor projection
  exposes — a `ReadOnly` field offers only `read()`, a `WriteOnly` field only
  `write()`, a plain field both. **Volatile is not atomic** — it constrains the
  compiler, not the memory system; ordering across accesses still needs fences.
- **`Normal`** — bootstrap or DMA-visible RAM (the initial stack, an early
  heap). Plain (non-volatile) loads/stores; whole-struct and element access are
  allowed; and it carries the region accessors **`ptr() -> UnsafePointer<Int8>`**,
  **`len() -> Int`** (region byte length), and **`end() -> UnsafePointer<Int8>`**
  (one-past-the-end — a stack top or slab handoff).

**Projection (both intents, one engine).** Member access on
`UnsafeMemory<Struct, Use>` yields `UnsafeMemory<Field, Use>` at *base +
compile-time offset*; it chains through nested structs and indexes through
fixed-array fields. No memory is ever loaded to project — it is pure address
arithmetic (an inbounds GEP through the natural-ABI layout, folded to a constant
offset).

**Layout guarantee.** The viewed struct uses **declaration-order, natural-ABI
layout**. Reserved `_pad` fields are the interim idiom for holes; explicit
`repr`/offset attributes are deferred until a device demands them.

```saw
struct UartRegs {
    data:   UInt32,
    status: ReadOnly<UInt32>,
    ctrl:   UInt32,
    intclr: WriteOnly<UInt32>,
}

static UART1:      UnsafeMemory<UartRegs, Device>       = UnsafeMemory(0x18003000)
static BOOT_STACK: UnsafeMemory<[UInt8; 16384], Normal> = UnsafeMemory(0x3FC7C000)
static EARLY_HEAP: UnsafeMemory<[UInt8; 65536], Normal> = UnsafeMemory(0x3FC80000)

let tx_full: UInt32 = 32
while (UART1.status.read() & tx_full) != 0 { }  // volatile poll of a RO register
UART1.data.write(byte)                          // volatile write to a RW register
let sp = BOOT_STACK.end()                        // stack top for early boot
slab_init(EARLY_HEAP.ptr(), EARLY_HEAP.len())    // hand the region to a slab
```

Fabricating an address is in the same trust bucket as the `UnsafePointer` family
(unsafe blocks remain deferred; the naming convention is the marker).

### Allocators (`Allocator` trait, `Global`, public `A` parameter)

**Status: implemented — public type parameter, `Global` default.** Alloc-layer
stdlib types (`Vector`, `Map`, `Data`, `StringBuilder`, `Arc`, ...) obtain memory
through the `Allocator` trait — `alloc(&self, size: Int, align: Int) ->
UnsafePointer<Int8>?` and `dealloc(&self, ptr, size, align)` — rather than
calling the `saw_alloc` / `saw_dealloc` seams directly. `Global` is a zero-field
unit struct that wraps the seams; because it is zero-sized, `Global().alloc(...)`
monomorphizes to a direct seam call with no allocator value materialized at
runtime.

The allocator is a **public type parameter with a default**:
`Vector<T, A: Allocator = Global>` and `Map<K, V, A = Global>`. Hosted code
writes `Vector<T>` unchanged — the default fills `A = Global` before mangling, so
`Vector<T>` and `Vector<T, Global>` are one type (see
[Default type parameters](#generics)). A custom allocator is written as a
zero-field unit struct conforming to `Allocator`:

```saw
struct MySlab {}
extension MySlab: Allocator {
    func alloc(&self, size: Int, align: Int) -> UnsafePointer<Int8>? { /* ... */ }
    func dealloc(&self, ptr: UnsafePointer<Int8>, size: Int, align: Int) { /* ... */ }
}

var v = Vector<Int, MySlab>()   // grow/deinit route through MySlab; A().alloc is
                                // a direct, statically-dispatched call — no stored
                                // allocator, no vtable
```

`Vector<Int, MySlab>` is a **distinct type** from `Vector<Int>`; a value of one
cannot be passed where the other is expected. Deinit frees through the vector's
own `A`, so allocations never cross heaps. A fallible factory such as
`Vector.try_with_capacity(n) -> Result<Vector<T, A>, AllocError>` surfaces
allocation failure to the caller (tier 2 of the three-tier failure model) with
`size`/`align` context, instead of the default infallible APIs' panic.

Paper 19 §4's allocator model is now landed end to end: module-level `static`
declarations (design 41) and **per-type slab allocators** (design 42) both ship.
The only piece still deferred is the optional `AllocatedBy<Slab>` sugar (per-type
default allocator), which paper 19 keeps for when kernel code justifies it.

### `Box<T, A>` — a single owned heap allocation

**Status: implemented (design 42).** `Box<T, A: Allocator = Global>` owns one
`T` allocated through allocator `A`. Hosted code writes `Box<T>` (the default
fills `A = Global`); a kernel writes `Box<Job, JobSlab>` to place the value in a
per-type slab (the design-19 §4 "kernel idiom"). `Box` is **NoCopy** — it is
`move`d, never silently duplicated — and its single heap `T` is released exactly
once on deinit.

The two constructors are **static factory methods** (allocation is fallible, so
it is not hidden behind `init`):

```saw
let a = Box<Int>.make(42)          // MakeBox — infallible; PANICS on OOM
                                   //   (three-tier model, infallible tier)
match Box<Int>.make_or(42) {       // MakeBoxOr — fallible tier
    case Ok(b)  -> print(b.value())
    case Err(e) -> print(e.size)   // AllocError with size/align context
}
```

On the `make_or` failure path the value is cleanly `deinit`'d at scope exit
(never leaked). `make` places the value with the placement-move primitive
(`ptr[0] = move value`) and, on allocator failure, panics. Payload access:

- `value()` returns a copy of the payload (bounded `T: Copy`).
- **Method forwarding** (like `Arc`): an immutable `&self` method on the payload
  struct is callable through the Box — `b.peek()` forwards to the payload's
  `peek`. A `&var self` payload method is rejected (aliased mutation of
  owned-through-a-handle state is what a `Mutex` payload exists to make safe).

### Slab allocators (the kernel idiom)

**Status: implemented (design 42).** A slab is a per-type fixed-chunk allocator
over a caller-owned `static` region — freestanding-compatible (no libc, just
`Atomic<Int>` CAS). `std/slab.saw` provides `SlabHead` (a slab's mutable
bookkeeping: a bump counter + a LIFO free-list head, both `Atomic<Int>`) and the
`slab_alloc` / `slab_dealloc` free functions. A user allocator is a zero-field
unit struct wiring its own statics in ~10 lines:

```saw
static JOB_REGION: [Int8; 64]                                  // 4 chunks × 16B, .bss
static JOB_HEAD: SlabHead = SlabHead(bump: Atomic(0), free: Atomic(0))

struct JobSlab {}
extension JobSlab: Allocator {
    func alloc(&self, size: Int, align: Int) -> UnsafePointer<Int8>? {
        slab_alloc((&JOB_REGION) as UnsafePointer<Int8>, 4, 16, &JOB_HEAD)
    }
    func dealloc(&self, ptr: UnsafePointer<Int8>, size: Int, align: Int) {
        slab_dealloc(ptr, &JOB_HEAD)
    }
}
type JobBox = Box<Job, JobSlab>          // the kernel idiom
```

The region reaches the slab as `(&STATIC) as UnsafePointer<Int8>` — a reference,
cast to a raw pointer, over a bare-declared (writable `.bss`) static. `alloc`
returns `None` on exhaustion (feeding the three-tier model: `make` panics on it,
`make_or` returns `Err`); `dealloc` pushes the chunk back onto the free-list.
The chunk size must be ≥ 8 bytes (a freed chunk stores the free-list link in its
own first word) and ≥ the payload. The CAS loops are lock-free; classic ABA is
possible and accepted at this stage (documented in `std/slab.saw`).

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

## Appendix 0: The Compiler (`sawc`)

**Status: implemented.** The reference compiler is `sawc` (Python + llvmlite),
lowering Saw to LLVM IR and then to a native object/executable.

```
sawc <source.saw> [options]

  -o <file>    Output executable name (default: ./<source>)
  -c           Compile to an object file (.o) only — no linking, no main() required
  -v           Verbose output (pipeline stages)
  --emit-ir    Emit LLVM IR only, don't compile
  --emit-ast   Dump the typed AST (debugging)
  -O0          Disable optimization passes (raw codegen; default is an O1-style
               pipeline: entry-block allocas + mem2reg and friends)
```

Optimization: by default `sawc` runs an O1-style pass pipeline (allocas hoisted
to the entry block, mem2reg, etc.); `-O0` turns it off for debugging raw output.

Known limitation: `--emit-ir` does **not** load the stdlib builtins, so it fails
on programs that use `String`/`Vector`/`Result` and similar. Use a full compile
(or `-c`) for those.

## Appendix A: Keywords

Reserved words. Some name planned features (marked); logical negation is the
word `not` (there is no `and`/`or` — use `&&`/`||`), and the empty optional is
`None`. `case` introduces enum variants and match arms.

```
Implemented:
as       break    case     catch    continue deinit   dyn      else
enum     extension extern  false    for      func     guard    if
import   in       init     let      match    module   move     None
not      package  parent   public   return   self     Self     static
struct   trait    true     try      type     var      while

Planned / reserved:
and  async  await  const  defer  do  loop  macro  none  or  ref
some  unsafe  where
```

## Appendix B: Operators

```
Implemented
  Arithmetic:     +  -  *  /  %        (overflow panics — see Integer Arithmetic)
  Wrapping:       &+ &- &*             (two's-complement wrap; integer-only)
  Bitwise:        &  |  ^  ~  << >>    (integer-only — see Bitwise & Shift)
  Comparison:     == != <  >  <= >=
  Logical:        &&  ||  not        (`not` is logical NOT — not `!`)
  Assignment:     =  += -= *= /= %=  &= |= ^= <<= >>=
  Range:          ..                 (half-open, e.g. `for i in 0..5`)
  Optional:       ?  ??  ?.  !        (`!` is force-unwrap; `?.` optional chain)
  Reference:      &  &var             (`&x` at a call site; `&var` params)
  Cast:           as                 (`x as Int`)
  Member/return:  .  ->

Planned (parsed shape may differ or be rejected today)
  Arithmetic:     **                 (power)
  Range:          ..=                (inclusive)
  Match arrow:    =>                 (superseded — Saw match arms use `->`)
  Path:           ::
```

**Precedence** (tightest binding at the top; each row binds tighter than the
rows below it). C-family: shifts sit above comparison, and `&` above `^` above
`|`. So `a | b & c` parses as `a | (b & c)`, and `x << 2 + 1` as `x << (2 + 1)`.

```
  unary            - x    not x    ~ x    &x  &var x   (prefix)
  cast             as
  multiplicative   *  /  %  &*
  additive         +  -  &+  &-
  shift            <<  >>
  range            ..
  comparison       == != <  >  <= >=
  bitwise AND      &
  bitwise XOR      ^
  bitwise OR       |
  logical AND      &&
  logical OR       ||
  nil-coalesce     ??
```

The four meanings of `&` are disambiguated purely by position: a *prefix* `&x` /
`&var x` is a call-site reference; the *single tokens* `&+ &- &*` are the
wrapping operators; an *infix* `&` between two full operands is bitwise AND. `~`
is bitwise complement (integer); `not` is Boolean negation. `!` is
**force-unwrap only**, never logical NOT.

---

*This specification is a living document. Details will be refined through iteration and implementation experience.*

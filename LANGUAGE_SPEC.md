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
below (the array-literal `.map` shorthand shown below is planned; default
parameter values ARE implemented, design 53). Infinite loops are written
`while { }` — there is no `loop` keyword (it was dropped as redundant). Note the
stdlib `Vector` does provide real `map<U>`/`fold<A>` methods
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

**Bindings always initialize.** Every `let`/`var` requires an initializer at the
declaration (`var x: Int` with no `= ...` is a parse error). There is no
uninitialized local, so use-before-initialization is structurally impossible —
no definite-initialization analysis is needed.

**Discard binding `let _`.** (design 53) `_` in `let` position is a true
discard: it evaluates the right-hand side (running its side effects), consumes
the value as the final owner (through the value-transfer checkpoint — a NoCopy
source needs `move`), drops it immediately at the end of the statement like an
unused temporary, and creates **no** binding. `_` is unreadable, and two
`let _` in one scope never collide. `var _` is rejected (a discard has nothing
to mutate). Per-position `_` in a tuple destructuring (`let (a, _) = pair`,
design 63) discards that component the same way. Parameter discards are out of
scope for now.

```saw
let _ = compute()      // run compute() for its effect; drop the result now
let _ = openFile()     // a NoCopy result is deinit'd at end of this statement
```

**Shadowing must be a visible refinement.** (design 100) A binding *shadows* when
its name would also resolve to an enclosing binding — a local/param/capture in a
lexically-enclosing scope, or a module-level `static`. Shadowing is a **compile
error UNLESS the new binding derives from the one it shadows**, so an accidental
shadow (a slip that silently hides the outer value) is caught while a deliberate
refinement stays ergonomic:

```saw
let data = read()
if refine {
    let data = parse(move data)   // OK: initializer mentions `data` (derived)
    let data2 = parse(data)       // (in one scope) — mentioning `data` also derives
}
let x: Int? = get()
if let x = x { use(x) }           // OK: the scrutinee references the shadowed `x`
let n = 5
if branch {
    let n = compute()             // ERROR: initializer never mentions `n`
}
```

- The reference may be **any** use of the shadowed name in the initializer —
  bare (`x`), `move x`, `x.copy()`, `f(x)`, or nested. The mention *is* the
  declaration of intent.
- Sites with **no initializer** to prove intent are flat errors when they shadow:
  a `match` / `if let` / `guard let` **pattern** binding (`case Move(x, y)` under
  an outer `x` — patterns *bind*, they do not compare, the classic footgun), a
  function parameter shadowing a module `static`, and a closure parameter
  shadowing an enclosing local. The single-name `if let x = x` / `guard let x = x`
  stay legal by the main rule (the scrutinee references the shadowed binding).
- Same-scope redefinition (`let x = 1; let x = 2` in one scope) is unchanged — it
  remains the pre-existing "already defined in this scope" error.
- Prelude/std names (`print`, `Vector`, …) are not bindings for this rule; a
  local named after one is governed by the existing rules, not design 100.
- The diagnostic names the shadowed binding's exact declaration site
  (`'data' shadows the binding declared at FILE:L:C`) and hints to rename or
  derive it.

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
    // in-place swap of two Vector slots uses the `Vector.swap(i, j)` method.
}

// Functions with default parameter values (implemented, design 53)
func greet(name: String, greeting: String = "Hello") -> String {
    "{greeting}, {name}!"
}
greet("Sam")             // greeting defaults to "Hello"
greet("Sam", "Hi")       // explicit

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

**Overloading (exact-match model).**
**Status: implemented (design 55).** A name may carry several
functions/methods (beyond `init`, which was always overloadable). This is
viable precisely because Saw has **no implicit numeric conversions** — an
argument matches a parameter only if it is *exactly* type-compatible (aliases
flow to their underlying type, defaults are filled; nothing else). Resolution
runs at every call form (free, method, static, module-qualified).

```saw
func describe(x: Int) -> Int { x + 1 }
func describe(x: String) -> Int { x.len() }     // same arity, different type — OK
func describe(x: Int, y: Int) -> Int { x + y }  // different arity — OK

describe(10)        // -> Int overload
describe("hello")   // -> String overload
describe(3, 4)      // -> 2-arg overload
```

Tie-breaks apply in order, then the result must be unique:
1. **Exact beats optional-wrap** — an `Int` argument prefers `f(Int)` over
   `f(Int?)`; both may coexist.
2. **Resolution precedes `Result`/optional auto-wrap** — the callee is chosen
   from the raw argument types, before any return-position wrap machinery.
3. **Concrete beats generic** — `f(Int)` beats `f<T>(T)`; when a name is
   OVERLOADED, a generic candidate competes only when the call supplies explicit
   type arguments (argument-type inference, design 93, applies to a *singleton*
   generic function/method — it is not run across an overload set, where it could
   manufacture new ambiguity). Two matching generics are a call-site ambiguity.

After the rules there must be exactly one survivor, else a call-site ambiguity
error listing the candidates; a no-match lists them too. **Closure arguments**
are resolved using the *non-closure* arguments first; if candidates still tie
and differ only in closure-parameter types, the call is ambiguous (this keeps
a closure's expected-type inference single-target).

Two declarations that no rule could separate — an identical normalized
signature (post-alias, with bare type parameters folded to one placeholder, so
`f<T>(T)`/`f<U>(U)` collide) **and the same parameter labels** — are a
**declaration-site** error. Same-arity different-types and different-arity are
always legal; so is **same types with different labels** (see labeled
arguments below — `f(a:b:)` and `f(kind:value:)` coexist).

**Default parameter values.**
**Status: implemented (design 53).** A parameter may carry a default value on
free functions, methods, and inits. Rules:

- **Trailing only.** A parameter without a default may not follow one that has
  a default (a declaration error).
- **Per-call, at the call site.** An omitted trailing argument is filled by
  evaluating the default expression *at the call site, once per call* — a fresh
  value each time (a default that calls a counter observes a new value on every
  call that omits the argument). The fill flows through the value-transfer
  checkpoint exactly like an explicit argument, so a NoCopy default construction
  moves in cleanly.
- **Arbitrary expressions, no self/other-param refs.** A default may be any
  expression (including calls) but may reference only module-level items — never
  another parameter or `self`.
- **Effects flow through.** A suspending default makes the callee suspending, so
  a `sync` context that fills it is diagnosed.
- **Overload interaction.** A defaulted declaration expands into its reachable
  call *shapes* (full arity down to the first defaulted arity). Any shape
  colliding with another overload's shape is a declaration-site ambiguity error
  (the same bucket as an identical normalized signature above). Mangling is
  unchanged — defaults are filled caller-side.

```saw
func connect(host: String, port: Int = 8080, tls: Bool = false) -> Int { port }
connect("a")                 // port 8080, tls false
connect("a", 443)            // port 443, tls false
connect("a", 443, true)      // all explicit
```

**Labeled arguments (lenient model).**
**Status: implemented (design 66).** Call arguments may be written with their
parameter's label. **Labels are required only where a call is otherwise
ambiguous; they are available everywhere for clarity.** A positional call is
always legal wherever it is unambiguous, and behaves identically to the same
call without labels.

*The binding rule.* Arguments bind **left to right**:

- a **positional** argument binds the next unbound parameter;
- a **labeled** argument binds the parameter with that name, provided that
  parameter sits **at or after** the next unbound position — a label may skip
  **forward** only over parameters that have defaults, **never backward**, and
  arguments are **never reordered**. A forward skip over a non-defaulted
  parameter is a `missing argument` error; a label that would bind behind the
  cursor is a backward-binding error.
- a label that names **no** parameter of the callee eliminates that candidate
  (a call-site error naming the label if none survives).

This subsumes pure positional calls (byte-identical), fully-labeled calls in
declaration order, partial labels as constraints, and **mid-default skipping**
(a labeled argument may skip a defaulted parameter that a positional call could
not).

```saw
func connect(host: Int, port: Int = 8080, retries: Int = 3) -> Int { … }
connect(1)                    // both defaults
connect(1, retries: 5)        // skip the defaulted `port` (mid-default skip)
connect(host: 2, port: 80)    // fully / partly labeled — same call
```

*Overloading.* Labels are part of a function's identity. The **label filter**
runs first (candidates whose parameter names cannot bind the call's labels are
eliminated), then the exact-type matching + tie-breaks above run on the
survivors. Two overloads may share parameter types but differ in labels; a
single disambiguating label resolves the call, while a bare positional call
over such a pair is an ambiguity error that lists the labeled forms.

```saw
func f(a: Int, b: Int) -> Int { … }
func f(kind: Int, value: Int) -> Int { … }   // same types, different labels — OK
f(a: 1, b: 2)        // f(a:b:)
f(0, value: 4)       // one label suffices — resolves to f(kind:value:)
f(1, 2)              // error: ambiguous — write the labels
```

*Scope.* Labeled calling covers free functions, instance/static methods, and
module-qualified calls. **Closures take no labels** — closure/function-value
types are structural and carry no parameter names. Struct/`init` and enum
payload construction keep their own **order-independent** name matching
(`Point(y: 4, x: 3)` is valid); they are a separate resolution scheme from the
ordered call binding rule, by design (design 66).

### Built-in Functions

A handful of functions are compiler-known (no import needed):

- `print(value?)` — write a value (Int family, `Bool`, `String`, `Float`, or a
  string interpolation) plus a newline; no argument prints a bare newline.
- `panic(message: String) -> Never` — abort with `message` (design 49). It
  routes through the freestanding-safe `saw_panic` runtime seam and **diverges**:
  its type is `Never`, so a function ending in `panic(...)` needs no return
  value, and `guard let x = … else { panic(…) }` is a valid diverging exit. The
  abort message carries the source location — `panic at FILE:LINE: {message}`
  (design 69).
- `assert(cond: Bool, message: String)` — a no-op when `cond` is true; when
  false it panics with the same unified location format,
  `panic at FILE:LINE: assertion failed: {message}` (design 69). `debug_assert`
  is deferred until a build-profile split exists.

**Debug info (design 69):** the compiler emits DWARF line tables by default (on
every build, no flag) via llvmlite debug metadata — a DICompileUnit, a
DISubprogram per function (with its Saw name), and a DILocation per statement.
A debugger (lldb/gdb) can therefore set line breakpoints and show `file:line`
backtraces, including for panics. Scope is line tables only in v1 (no
variable/type info yet). On macOS, source-level stepping needs the intermediate
`.o` kept (compile with `-c`, then link) or a generated `.dSYM`, because the
linker leaves DWARF in the object and references it through a debug map; Linux
embeds DWARF in the executable directly.
- `sizeof<T>()` / `alignof<T>()` — the size / alignment of `T` in bytes.

```saw
func checked(x: Int) -> Int {
    if x < 0 {
        panic("negative input")   // diverges; no `else`/return needed after
    }
    x * 2
}

func main() {
    assert(1 + 1 == 2, "arithmetic is broken")   // no-op
    print(checked(21))                            // 42
}
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

// Literal, range, guard, and tuple patterns (design 63 — implemented). A match
// on a value/tuple scrutinee tests arms in order:
match value {
    case 0 -> "zero",              // integer / Bool / String literal patterns
    case 1..=9 -> "single digit",  // range patterns (`1..9` and `1..=9`)
    case n if n < 0 -> "negative", // guard: runs after binding, falls through
    case _ -> "big",               // fallback (see exhaustiveness below)
}
// Tuple patterns destructure and nest with the other forms:
match pair {
    case (0, 0) -> "origin",
    case (x, 0) -> "on x axis",
    case (Some(v), n) if v == n -> "match",   // nested payload / Optional pattern
    case (x, y) -> "general",                 // irrefutable arm = fallback
}
// Exhaustiveness: literal / range / guarded arms never prove it on an open type
// — a wildcard or bare-binding (or irrefutable tuple) arm is required. EXCEPTION:
// `true` + `false` arms exhaust Bool. A closed integer range-cover is not
// computed (v1 — always add a fallback).

// For loops over ranges
for i in 0..5 {
    print(i)        // 0 1 2 3 4 (exclusive)
}

// Inclusive range `..=` (design 53): a dedicated Int.max-safe iterator, NOT a
// `0..(5+1)` desugar — `0..=Int.max` yields Int.max and stops without phantom
// overflow. Empty when start > end.
for i in 0..=5 {
    print(i)        // 0 1 2 3 4 5 (inclusive)
}

// enumerated() yields (index, element) pairs; each_indexed is its closure twin.
for pair in vec.enumerated() {
    print(pair.0)   // index
    print(pair.1)   // element
}
vec.each_indexed { i, x in print(i) }

// While loops (conditional and infinite `while { }`)
while condition {
    // ...
}

// Infinite loop as an expression with a break value (`while { }` is the idiom;
// there is no `loop` keyword).
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
the subsection notes). `Map`/`Set` and their `{ }` literals, context-driven
Vector literals, and trait default methods are **implemented**. Planned pieces
called out below: slices (`&a[1..4]`), supertrait *enforcement*, and some
primitive widths. `any Trait` existentials (type-erased dynamic dispatch)
are **implemented** (see Traits). Stdlib methods used only to illustrate (e.g.
`.sqrt()`) are marked *(illustrative)*.

### Primitive Types

Common types — `Int`, `UInt`, the sized `Int8`…`Int64`/`UInt8`…`UInt64`,
`Float`/`Float64`, `Bool`, and `String` — are implemented. `Int128`/`UInt128`,
`Float32`, and `Char` are *planned*. `Never` (the bottom type) is the type of a
diverging `panic(...)` (design 49) and is spellable as a return type
(`func boom() -> Never`; `@export`'s `_start` shape lowers it to `void` +
noreturn, design 58). An expression of type `Never` is assignable to any
expected type, so a function body that ends in `panic(...)` needs no return
value, and a `panic` arm/branch contributes no type to a `match`/`if`.

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
Never       // Bottom type (a diverging `panic`; usable as a return type)
```

**`Int`/`UInt` are pointer-width** (Swift's model, design 47): 64-bit on
x86-64/aarch64, **32-bit on riscv32** (e.g. ESP32-P4). `Int` is the type of an
index, a length, a size (`sizeof`/`alignof`), and an address, so it matches the
machine word on every target — no forced 64-bit instruction pairs or 64-bit
division libcalls (`__divdi3`) on a 32-bit chip. Consequently:

- The representable **range of `Int` (its max/min) is target-dependent**:
  `-2^63 … 2^63 - 1` on a 64-bit target, `-2^31 … 2^31 - 1` on riscv32 (and
  likewise `UInt`'s max). Code that must reason about a specific range should use
  a fixed-width type.
- **`Int.max`/`Int.min` named constants** (design 53) give those bounds from a
  single source of truth (the target word width), and **`.max`/`.min` are
  available on every fixed-width type and `UInt`** (`Int8.max == 127`,
  `UInt8.max == 255`, `Int32.min == -2147483648`, …). Use them instead of
  hand-writing a bound (and to spell `Int8.min`, which a `-128i8` literal cannot).
- An **integer literal is a platform `Int`** by default; a literal that does not
  fit the target word is a compile error *at the literal* (so `9_999_999_999`
  compiles on a 64-bit host but is rejected under a 32-bit target).
- **Literal suffixes** (design 53) type a literal as an exact fixed-width type:
  `255u8`, `1_000i32`, `0xFFFF_FFFFu32`, `0b1010u8`, `0o17u16` — suffix set
  `i8/i16/i32/i64/u8/u16/u32/u64`, with an optional single `_` before the suffix.
  A suffixed literal IS that type (no platform-`Int` involvement — this is how a
  64-bit constant is written on riscv32), range-checked at the literal (`256u8`
  is a compile error). A suffixed literal does not implicitly convert to a
  different fixed-width type (`let x: Int8 = 5u16` is an error); a plain
  (unsuffixed) literal still coerces to any integer type. Float literals take no
  suffix.
- **A bare (unsuffixed) integer literal adopts a fixed-width EXPECTED type
  wherever one is in force, and is range-checked *at the literal*** (design 87).
  This is uniform across every position a value flows into — `let`/`var` with a
  fixed-width annotation, a function/method parameter, a struct field or `init`
  argument, a default parameter value, a `return` (and if/match arm results that
  merge to a fixed-width type), an enum payload, a compound-assign RHS
  (`x += 1` for `x: Int8`), and the element/key/value positions of array, tuple,
  `Vector`, `Map`, and `Set` literals. In each the literal takes the slot's exact
  width, so it stores and overflow-checks at that width, and an out-of-range
  literal (`let b: UInt8 = 256`) is a clean compile error, never a silent wrap or
  an ICE. With NO fixed-width expected type a literal stays platform `Int`
  (`let x = 5`), and `Int`/`Int` arithmetic is unaffected. The one place a
  literal is typed by a sibling rather than a declared slot is a mixed binop
  (`b + 0`, `fd < 200`): the literal adopts the other operand's fixed-width type.
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
  `s + t` loop is O(n²); the mutable, geometrically-growing `StringBuilder`
  (design 38) is the efficient builder — `append`/`build`).
- **Escape sequences.** The supported escapes in a string literal are exactly
  `\\`, `\"`, `\n` (LF, 10), `\t` (tab, 9), `\r` (CR, 13), `\0` (NUL, 0),
  `\u{...}`, plus the `\{` / `\}` brace forms (a literal brace, distinct from
  interpolation). `\0` produces an interior NUL that `len()` counts (a `String`
  is length-prefixed, not NUL-terminated). Any OTHER backslash sequence is a
  clean **lex error** naming it (``unknown escape `\d` ``) — the backslash is
  never silently dropped.
- **`\u{...}` escapes** (design 53). A string literal may contain a Unicode
  scalar escape `\u{1F600}` — 1–6 hex digits — encoded to its UTF-8 bytes in the
  literal. Surrogates (`D800`–`DFFF`) and code points above `0x10FFFF` are
  rejected *at lex time*, so a literal can never hold an invalid scalar. It
  composes with interpolation: `"{x} \u{2713}"`. Source files with CRLF
  (`\r\n`) line endings lex cleanly — a `\r` between tokens is line whitespace.
- **UTF-8 guarantee.** A `String` always holds valid UTF-8. Two doors admit
  bytes and both enforce it: **string literals** are validated for free — source
  files are decoded as UTF-8 before lexing, and the only escape that introduces
  a code point (`\u{...}`) is scalar-validated at lex time (there are no
  byte/`\x` escapes), so an invalid-UTF-8 literal cannot be written; and
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
  there is no `Char` primitive type yet (a scalar is just an `Int`). `String`
  itself *is* `Comparable` (byte-lexicographic ordering, design 48). Each iterator
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
- **Number parsing** (`designs/57`). Three optional-returning methods parse the
  **whole** string (no trimming — the caller trims with `trim`; empty → `None`;
  any trailing/leading junk → `None`). Parse failure is *data*, so these never
  panic: `to_int() -> Int?` (base 10), `to_int(radix: Int) -> Int?`
  (a design-55 overload, radix 2..=36, digits `0-9a-zA-Z`, no `0x` prefix — the
  caller strips it), and `to_float() -> Float?`
  (`[+-]?digits[.digits][e[+-]digits]`). Overflow returns `None`: the integer
  parser accumulates a **non-positive magnitude** with wrapping arithmetic and
  divide-back checks (portable across Int widths, no `Int.max` constant needed;
  `Int.min` round-trips). `to_float` is naive accumulation — fine for typical
  input, but **not** a correctly-rounded `strtod` (the last ULP may differ).
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

### Source-location literals

Three magic literals expand at compile time to their **definition site** — the
place the token literally appears in source (design 98). They are ordinary
compile-time constants of the type below, so they have **zero runtime cost**,
are freestanding-safe, and are valid anywhere a literal of that type is (an
expression, an interpolation, a default parameter value, a `static` initializer
for `#line`):

- **`#file` → `String`** — the source file's **basename** (not a full path, so no
  build-machine paths leak into a binary). It matches the design-69 panic prefix
  (`panic at FILE:LINE:`), the same file spelled the same way.
- **`#line` → `Int`** — the 1-based line of the token.
- **`#function` → `String`** — the enclosing function/method's **bare name** with
  no struct qualifier (`main`, `here`, `init`); at module scope, `<module>`.

```saw
func log(msg: String) { print("{#file}:{#line} - {msg}") }  // debug-print idiom
```

Expansion is at the definition site, never the caller. In a **generic** the value
is the generic's own file/line, identical across every instantiation. In a
**default argument** it is the default's own definition site (there is no
caller-site `#file`-as-default-argument capture — Swift's other mode — in v1).
Inside a **suspending function** body `#line`/`#function` report the ORIGINAL
source line and the user function's name, not the transformed coroutine frame's.
`#` introduces one of these three directives *only*; any other `#name` is a clean
"unknown directive" lex error.

### Composite Types

```saw
// Tuples (positional — implemented). Access fields by index with `.N`.
let point: (Int, Int) = (10, 20)
let x = point.0

// Tuple destructuring (design 63 — implemented). Irrefutable only: bindings,
// per-position `_` discard, and nested tuples. The whole source is consumed
// (owning components move out; a bare ImplicitCopy/POD source is copied).
let (a, b) = point            // a = 10, b = 20
var (mx, my) = (1, 2)         // mutable bindings
let (first, _) = point        // discard the second component
let (p, (q, r)) = (1, (2, 3)) // nested

// Named tuple fields (design 63 — implemented, Swift-compatible). Field names +
// order + types are part of the type. A named tuple and a POSITIONAL tuple of
// the same shape are mutually compatible (labels are a view over the positional
// layout); two named tuples with different names or a different order are NOT.
// Literals are all-or-nothing labeled and may not reorder against a known
// target. Access by `.name` OR positionally (`.0`/`[i]`).
let named: (x: Int, y: Int) = (x: 10, y: 20)
let y = named.y                     // by name
let y2 = named.1                    // positionally (same field)
let flowed: (Int, Int) = named      // named -> positional (compatible)
// The NAMED pattern form `let (x: a, y: b) = named` is deferred — use the
// positional form `let (a2, b2) = named` (labels are ignored in patterns).

// Arrays (fixed size, stack allocated)
let fixed: [Int; 5] = [1, 2, 3, 4, 5]

// A fixed array `[T; N]` inherits T's copy class (see The Copy Trait Family):
// `[Int; 5]` is trivially copyable, so `let b = fixed` bitwise-copies it. An
// array of `ExplicitCopy` elements is itself `ExplicitCopy` (move to transfer,
// `.copy()` to duplicate per element); an array of `NoCopy` elements is
// move-only. Owned elements are destroyed in reverse index order at scope death.

// Fixed arrays carry two builtin members (design 72) — and only these two;
// user extensions on array types are not supported:
//   `.len()`        -> the compile-time constant length N (an `Int`)
//   `.swap(i, j)`   -> swap two elements in place (bounds-checked; the receiver
//                      must be a `var`). The dynamic-index escape hatch, mirroring
//                      `Vector.swap`: it lets a dynamic-index exclusivity conflict
//                      be sidestepped without copying elements.
print(fixed.len())            // 5
var reversible = [10, 20, 30]
reversible.swap(0, 2)         // -> [30, 20, 10]

// Slices (view into contiguous memory)  (illustrative — slices are planned)
let slice: [Int] = &fixed[1..4]

// Vectors (dynamic, heap allocated) — stdlib `Vector<T>`. A bracket literal
// builds a Vector when the EXPECTED type is `Vector<T, A>` (design 54); with no
// expected type it is a fixed-size array (above).
let squares: Vector<Int> = [1, 4, 9, 16]     // context-driven Vector literal
let empty_vec: Vector<Int> = []              // empty Vector via context

// Dictionaries and Sets use `{ }` literals (design 54):
let ages: Map<String, Int> = {"alice": 30, "bob": 25}
let uniques: Set<Int> = {1, 2, 3}
let empty_map: Map<String, Int> = {:}        // empty map (needs an annotation)
let inferred = {1: 10, 2: 20}                // Map<Int, Int>, K/V inferred
```

**The `{ }` closure rule** (design 54): a brace is a **map literal** when its
first delimiter is `:` (`{k: v, ...}`, and `{:}` is the empty map), a **set
literal** when it is `,` (`{a, b, ...}`), and a **closure/block** otherwise —
`{}`, `{expr}`, `{ x in ... }`, and `{ $0 ... }` are ALWAYS closures (spell
empty/singleton collections `Map<K, V>()`, `Set<T>()`, `Set.of(x)`). The choice
is made by bounded parser lookahead with no type feedback. Duplicate map keys:
last wins. Each element is consumed exactly as an `insert`/`push` argument
(moves for owning types).

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

**Layout rule (language-level).** Every struct uses **declaration-order,
natural-ABI layout**: fields are laid out in source order at their target's
natural alignment, with padding inserted only to satisfy alignment. This is a
guarantee, not an optimization — there is no field reordering and there is no
`repr` attribute to request one layout over another (the rule *is* the C-
compatible layout, which is why an aggregate can be shared with C through
`UnsafePointer<Struct>` and why `UnsafeMemory<Struct, Device>` can project to a
register at a fixed offset). Reserved `_pad` fields are the interim idiom for
deliberate holes. It generalizes the design-46 register-block layout guarantee
to all structs.

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

**Call-site optional auto-wrap** (`designs/57`, DF3). The implicit `T → T?` wrap
also applies at **call boundaries**: a bare `T` argument auto-wraps into a `T?`
parameter at every call form (free function, method, static method,
module-qualified, struct `init`, and enum-payload construction). It is **one
level only** (`T → T?`, never `T → T??` — and an already-optional argument is
passed through, never re-wrapped). It runs **after overload resolution**, so an
exact match still beats the wrap (design 55 rule 1: `f(5)` picks `f(Int)` over a
coexisting `f(Int?)`). It does **not** fire through a generic-instantiation
boundary — passing a bare `Int` where a generic parameter `U` was instantiated to
`Int?` is an error; the optional must be explicit there. Move/copy semantics are
unchanged (the wrap consumes the argument exactly as an explicit `Some(x)` would).

### Traits

Trait definitions, conformance via `extension Type: Trait`, conformance
checking, single and multiple conformance, associated types (with resolution),
`T: Trait` generic bounds, multi-bound `+` syntax (`T: A + B`), **trait default
method bodies** (below), and `any Trait` existentials (type-erased dynamic
dispatch, below) are **implemented**.

**Trait default method bodies** are implemented: a trait method declared *with*
a `{ ... }` body is a default. A conformer may omit it (it inherits a
per-conformer copy of the default, compiled with `Self` bound to the concrete
type) or override it with its own method. A default body may call the trait's
other methods (including required ones) — those calls dispatch to the
conformer's implementation. Defaults flow through trait inheritance (a single
`extension T: Child` inherits the defaults of `Child` *and* its supertraits),
get an `any Trait` vtable slot (pointing at the override if present, else the
monomorphized default), and have their effects inferred per conformer (a `sync`
default body is a checked suspension-free context). A method with *no* default
is still a required method: omitting it fails conformance.

```saw
trait Greeter {
    func name(&self) -> String
    func greet(&self) -> String {   // default body — calls a required method
        "Hello, {self.name()}!"
    }
}

extension Robot: Greeter {
    func name(&self) -> String { "R2" }
    // greet() inherited from the default; prints "Hello, R2!"
}

trait Display {
    func display(&self) -> String
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

// Multiple bounds (implemented) — require several traits with `+`
func process<T: Display + Equatable>(item: T)

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
```

#### `any Trait` existentials (dynamic dispatch)

**Status: implemented.** `any Trait` is a *type-erased* value: it forgets its
concrete type and dispatches through a vtable at runtime. It is the keyword
`any` (Swift's modern spelling — it names the intent), a **contextual** keyword
in type position, so `any` stays a valid identifier everywhere else. The
opaque/static-dispatch counterpart (a later addition) will use the keyword
`generic`.

Erased values live only behind **explicit ownership** — there is no hidden
existential container (a divergence from Swift, where `any P` silently boxes).
Costs are visible in the type:

- `&any Trait` — a borrowed erased value (a non-escaping reference).
- `Box<any Trait, A = GlobalAllocator>` — an owned erased value (NoCopy; the payload is
  heap-allocated through `A`).

Anywhere else — a by-value binding, field, parameter, or return, or any other
generic slot such as `Vector<any Trait>` or `Arc<any Trait>` — is a compile
error naming the rule. `Vector<Box<any Trait>>` is the idiom for a heterogeneous
collection.

```saw
trait Shape { func area(&self) -> Int }

struct Circle { r: Int }
extension Circle: Shape { func area(&self) -> Int { self.r * self.r * 3 } }
struct Square { s: Int }
extension Square: Shape { func area(&self) -> Int { self.s * self.s } }

// Borrowed dispatch: `&circle` is erased to `&any Shape` at the call boundary
// (the vtable is attached there — no retroactive coercion elsewhere).
func describe(shape: &any Shape) -> Int {
    shape.area()            // vtable dispatch through the fat pointer
}

// Owned, heterogeneous collection. Each box is built erased-directly and torn
// down (payload deinit + dealloc, driven by the vtable) exactly once.
func total_area() -> Int {
    var shapes = Vector<Box<any Shape>>()
    shapes.push(Box<any Shape>.make(Circle(r: 2)))
    shapes.push(Box<any Shape>.make(Square(s: 3)))
    var total = 0
    var n = shapes.len()
    while n > 0 {
        if let b = shapes.pop() { total = total + b.area() }
        n = n - 1
    }
    total                   // 12 + 9 = 21
}
```

**Representation.** An erased value is a two-word *fat pointer* `(data, vtable)`.
The vtable is a per-`(concrete type, trait)` constant (rodata; freestanding-fine)
laid out `[destructor, size, align, type_id, methods…]` with the methods in trait
declaration order. `Box<any Trait, A>` teardown takes the destructor, size, and
align from the vtable (never a static `sizeof<T>`, since the payload is erased)
and routes the dealloc to `A`. The `type_id` header slot is a stable
per-concrete-type constant that backs downcasting (below).

**Effects** follow the *trait* signature: a `sync` trait method stays
sync-callable through `any`; an unmarked one conservatively suspends, like any
call through a function value.

**Downcasting (v1).** An owned `Box<any Trait>` can be narrowed back to a
concrete conforming type through two builtins with an **explicit** type argument
(no inference):

- `b.is<T>() -> Bool` — compares the box's vtable `type_id` to `T`'s. A borrow:
  the box stays live, so a caller can branch before deciding to consume.
- `b.take<T>() -> T?` — **consumes** the box. On a match it moves the payload out
  (freeing the shell *without* running the destructor, since ownership transfers)
  and yields `Some(T)`; on a mismatch it drops the box (destructor + dealloc) and
  yields `None`. It consumes the box **either way** (a mismatch is not left
  intact — `is<T>()` first is how you branch without consuming), so a use after
  `take` is a use-after-move error.

`T` must be a concrete type conforming to the trait. This is what lets an erased
`Box<any Error>` be recovered to its concrete error for retry logic. Catch-side
`match`-on-concrete sugar over an erased box is not yet provided.

```saw
match step() {
    case Ok(v)  -> use(v),
    case Err(e) -> {                 // e: Box<any Error>
        if e.is<IoErr>() {
            if let io = e.take<IoErr>() { retry(io) }
        } else {
            report(e)                // still an erased Box<any Error>
        }
    }
}
```

**Object safety (v1).** A trait is erasable only if every method is
dispatchable. These are rejected with a diagnostic naming the reason:
- a method that takes or returns `Self` **by value** (the whole Copy family) —
  the `&self` / `&var self` *receiver* is fine, so a mutating method IS erasable;
- a method with its own generic type parameters;
- a trait with associated types (pinning `any Iterator<Item = Int>` is a later
  addition);
- a marker trait (`Send`/`Sync`/`NoCopy`, or any trait with no methods) — there
  is nothing to dispatch.

#### `Printable` — formatting

**Status: implemented.** `Printable` is the prelude-visible formatting trait
(like `Equatable`/`Comparable`). Its core method is a **streaming formatter**;
`to_string` rides on it as a default method body:

```saw
trait Printable {
    func format(&self, into: &var StringBuilder)

    func to_string(&self) -> String {   // default body (see default methods)
        var b = StringBuilder()
        self.format(into: &var b)
        b.build()
    }
}
```

- `Int`/`UInt` and the fixed-width integers, `Float`, `Bool`, and `String`
  conform **builtin** — the compiler renders them inline.
- User types conform **by hand** — there is *no* auto-conformance or synthesis
  (that is the deferred `Debug` design's territory).
- **String interpolation** `"{expr}"` and **`print(expr)`** accept any Printable
  value, streaming it through `format`; builtin pieces keep their existing
  byte-identical fast path. A **non-Printable** type used in interpolation is a
  clean compile error naming the type and the trait.
- A `T: Printable` generic bound grants `format`/`to_string` and interpolation of
  `T` values in generic bodies.

```saw
struct Point { x: Int, y: Int }
extension Point: Printable {
    func format(&self, into: &var StringBuilder) {
        into.append("(")
        into.append(self.x)     // append(Int) overload
        into.append(", ")
        into.append(self.y)
        into.append(")")
    }
}
// A Printable field is streamed into the SAME builder (no intermediate Strings):
struct Line { a: Point, b: Point }
extension Line: Printable {
    func format(&self, into: &var StringBuilder) {
        into.append("Line[")
        self.a.format(into: &var into)   // forward the shared builder
        into.append(" -> ")
        self.b.format(into: &var into)
        into.append("]")
    }
}

let p = Point(x: 3, y: 4)
print("point = {p}")   // point = (3, 4)
```

#### `Error` and erased Results

**Status: implemented.** An error type is a Printable value:

```saw
trait Error: Printable {}
```

Both conformance spellings are legal: a one-shot `extension E: Error { func
format(...) {...} }` (format is inherited from `Printable`), or a split
`extension E: Printable {...}` + an empty `extension E: Error {}`.

`Result<T, Box<any Error>>` is a supported return type — an **erased Result**:

- Returning a concrete `E: Error` from such a function auto-wraps it to `Err`
  **and** auto-erases it into a `Box<any Error>` at the return boundary. The
  return checkpoint runs one well-ordered sequence: overload resolution →
  `Result`/`Optional` auto-wrap → erase.
- `try callee()` where the callee returns `Result<U, Box<any Error>>` propagates
  the box as-is (a move, no re-box); where the callee returns a concrete
  `Result<U, E>`, the `E` is erased into a fresh box at the propagation edge.
- Matching `Err(e)` (or a `catch` whose tried calls include an erased box) binds
  `e` as `Box<any Error>`; `"{e}"` / `e.to_string()` render it through the
  vtable. To recover a concrete error (e.g. retry only on `IoErr`), narrow the
  box with `e.is<IoErr>()` / `e.take<IoErr>()` (see Downcasting above). Catch-side
  `match`-on-concrete sugar over the erased box is still deferred.

```saw
struct ParseErr { code: Int }
extension ParseErr: Error {
    func format(&self, into: &var StringBuilder) {
        into.append("parse error ")
        into.append(self.code)
    }
}

func parse(ok: Bool) -> Result<Int, Box<any Error>> {
    if ok { return 42 }        // Ok
    return ParseErr(code: 7)   // auto-wrap Err + auto-erase to Box<any Error>
}
```

> **Freestanding note.** Erasing an error boxes it through `GlobalAllocator`, so
> `Result<T, Box<any Error>>` is a *hosted convenience*. Kernel / freestanding
> code that must avoid hidden allocation keeps concrete or closed-union error
> types (`Result<T, ConcreteE>`), which allocate nothing.

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

// Project a distinct type TO its underlying with an explicit cast (design 63).
// This is the sanctioned form — there is no `.value` accessor. The cast is
// ONE-DIRECTIONAL (toward the underlying): `raw as Miles` stays an error, and a
// sibling-alias cast (`user as OrderId`) is rejected too. A partial projection
// to an intermediate alias on the chain is allowed.
let raw: Float64 = m as Float64
let uid: Int64 = user as Int64

// Type definitions for function signatures
type Callback = (Int) -> Bool
type Handler<T> = (T) -> Result<(), Error>
```

### Type Extensions

**Status: implemented** for user-defined structs (methods — including
overloaded methods and static methods, see [Functions](#functions) — overloaded
custom `init`, and — see Traits — conformance via `extension Type: Trait`).
Extending built-in primitive types (`extension Int`, `extension Float`) is also
implemented (design 57 registers them as extendable — the stdlib numeric methods
are built this way). Computed properties and generic specialized extensions
beyond what monomorphization already supports remain *planned*. Some method
bodies below use stdlib methods (`.sqrt()`, `.cos()`) that are *(illustrative)*.

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

// Built-in type extensions (implemented, design 57). The stdlib's own
// numeric methods (abs, pow, is_even, clamp, ...) are written exactly this way.
extension Int {
    func doubled(&self) -> Int { self * 2 }
}

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
  **Contract: cheap, O(1)-ish** — e.g. a refcount bump. `String` and `Arc`
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
rejected even when `i != j` at runtime (the checked `Vector.swap(i, j)` method
is the intended escape hatch; landed in design 40).

> **Invariant (for future features):** the fully-static guarantee rests on the
> no-escape property. If closures capturing by reference, returned/stored
> references, or globally-reachable mutable variables are ever added, they must
> either preserve no-escape or be folded into the call-site disjointness check;
> otherwise this law weakens from *sound* to *advisory*.

### Shared Ownership

**Status: implemented.** `Arc<T>` (atomic reference counting) and
`Box<T, A>` (owned heap allocation) are in the stdlib. Saw is **Arc-only** —
there is no single-threaded `Rc<T>` (decided in design 16): the atomic refcount
is the one shared-ownership primitive. `Arc` is `ImplicitCopy + Deinit`
(retain on copy, release on drop; the last owner runs the payload's `deinit`
exactly once), built on the same machinery as `String`.

```saw
// Atomic reference counting (thread-safe shared ownership)
let shared = Arc<Payload>(value: Payload(id: 7))
let shared2 = shared          // copy() called, strong count increases
print(shared2.strong_count()) // 2

// Box<T, A>: owned heap allocation without sharing (NoCopy — move to transfer).
// Static factories: `.make` (panics on OOM) and `.make_or` (fallible).
let boxed = Box<Int>.make(42)
print(boxed.value())          // 42
```

### Synchronized Access

**Status: `Mutex<T>` implemented (hosted); `RwLock` planned.** `Mutex<T>` is
`NoCopy + Deinit`, backed by a `pthread_mutex_t` on the hosted engine. Rather
than a returned lock guard, `lock` takes a non-escaping closure and runs it with
`&var` access to the guarded payload under the lock — the lock is always
released on the way out. `get()` snapshots the payload (`T: Copy`).

```saw
// Mutex for exclusive mutable access
let m = Mutex<Int>(value: 0)

m.lock { &var c in
    c = c + 1
    true            // the closure returns a Bool result
}                   // lock released automatically

if let v = m.get() {
    print(v)        // 1
}
```

`RwLock` (multiple readers XOR single writer) is planned; it is not yet in the
stdlib.

### Resource Management Interfaces

**Status: implemented.** Saw provides a hierarchy of traits for types that need
custom copy behavior or cleanup when going out of scope. This enables reference
counting (like `String` and `Arc<T>`), deep-copy owning types (like
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
force-unwrap failures and division by zero (see Runtime Semantics). The
`panic(...)` builtin (design 49) and `.len()` on a fixed array (design 72) are
implemented; the `[Int]` slice parameter below is still *(illustrative)* — on a
fixed array `[Int; N]` the same code type-checks and runs today.

```saw
func get_index(arr: [Int], i: Int) -> Int {   // [Int] slice: illustrative
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
- **Fixed-array indexing with a *dynamic* index** is **bounds-checked at
  runtime** (design 63): `0 <= i < N` (folded to one unsigned compare, so a
  negative index is caught too); an out-of-range index panics "index out of
  range". ALWAYS ON, every profile, no disable flag (the same posture as integer
  overflow). An in-range constant index is folded away; raw-pointer /
  `UnsafeMemory` indexing is the explicit unchecked escape. Read and write paths
  are both checked.
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
- **Optional and fixed-array members** (design 72 L9): a synthesized `==` lowers
  an `Optional` member (`None == None`, `Some vs None` unequal, payload compared
  deep only when both sides are `Some` — a `None` slot's payload is never
  touched) and a fixed-array member `[T; N]` (element-wise conjunction). So a
  struct/enum whose fields/payloads are `T?` or `[T; N]` (with `T: Equatable`)
  conforms; auto-conformance is still trivial-only. A genuinely non-Equatable
  member remains a clean error at the comparison site.
- `a == b` on a conforming user type lowers to its `equals`; primitives keep
  direct `icmp`/`fcmp`. `!=` is always the negation of `==`. `String ==` is
  content equality. **Float keeps IEEE semantics** — `NaN != NaN`.
- **Migration note:** payload-carrying enums previously had a tag-only `==`
  (so `Msg.Write("a") == Msg.Write("b")` was wrongly `true`). They now have no
  `==` until they declare `Equatable`, and it is payload-deep.

### Ordering (`Comparable`)

**Status: implemented** (`designs/48-ord-hash.md`). The `Comparable` trait gates
the ordering operators `< <= > >=`, which **desugar to `compare`**:

```
enum Ordering { case Less, case Equal, case Greater }

trait Comparable {          // requires Equatable
    func compare(&self, other: Self) -> Ordering
}
```

- **Builtin:** integer types, `Float`, and `String` conform builtin. Integers
  and `Float` lower directly to `icmp`/`fcmp`; `String` compares
  **byte-lexicographically** (= code-point order for ASCII / UTF-8; a shorter
  string that is a prefix of a longer one is `Less`).
- **No auto-conformance.** Unlike `Equatable`, a struct/enum is *never*
  automatically `Comparable` — field order is a semantic choice. Opt in with an
  empty `extension T: Comparable {}`, which **synthesizes** a lexicographic
  compare (struct: field-declaration order; enum: variant-declaration order,
  then the active payload). A hand-written `compare` **overrides** the synthesis.
- **Requires Equatable.** A `Comparable` type must also be `Equatable` (so `==`
  and `compare(...) == .Equal` agree); a trivial struct satisfies this by
  auto-`Equatable`, otherwise declare `extension T: Equatable {}` too.
- `a < b` is `a.compare(b) == .Less`, `a <= b` is `!= .Greater`, etc. A
  `T: Comparable` generic bound grants the operators in a generic body.
- **Float NaN:** a `NaN` is unordered, so every ordering operator involving it
  is `false` (matching the primitive `fcmp`); in a three-way `compare`, an
  unordered pair yields `Equal` (there is no total order over NaN — documented).

### Hashing (`Hashable`) and `Hasher`

**Status: implemented** (`designs/48-ord-hash.md`). The `Hashable` trait gates
use as a hash-map key. It streams a value into a **streaming `Hasher`** (FNV-1a):

```
struct Hasher { /* opaque FNV-1a state */ }
extension Hasher {
    init() -> Hasher
    func write_int(&var self, n: Int)   // FNV-1a step
    func finish(&self) -> Int           // the digest (with a final avalanche)
}

trait Hashable {            // requires Equatable
    func hash(&self, h: &var Hasher)
}
```

- Conformance **mirrors `Equatable`'s gating exactly:** trivial (POD) structs
  and payload-free enums auto-conform; everything else opts in with an empty
  `extension T: Hashable {}` (which streams each field / active payload);
  primitives and `String` conform builtin. `Hashable` **requires Equatable**.
- **hash/== contract:** `a == b` implies `a` and `b` hash identically. Synthesis
  upholds it by streaming exactly the fields `==` compares; a hand-written
  `hash` must uphold it. (Unequal values *may* collide — that is a hash map's
  job to resolve.) `Float` normalizes `-0.0`/`+0.0` so they hash alike; NaN bit
  patterns are not normalized (`NaN != NaN`, so nothing is required).
- `x.hash(&var h)` streams `x`; primitives mix directly, `String` streams its
  bytes, structs/enums stream their fields/payloads.

### `Vector.sort` / `sort_by`

**Status: implemented** (`designs/48-ord-hash.md`). In-place **insertion sort**
(simple and correct first; **stable** — equal elements keep input order):

- `sort(&var self)` on `Vector<T: Comparable + Copy>` — ascending by `T`'s order.
- `sort_by(&var self, compare: (T, T) -> Ordering)` on `Vector<T: Copy>` — the
  comparator is a **non-escaping** closure parameter.
- Element *movement* uses byte-level `swap` (refcount-neutral, never a copy);
  *comparison* reads elements by value through `get`, so both are bound to
  `T: Copy` (the `Vector.each` precedent). No ExplicitCopy element is ever
  silently duplicated.

### `Map<K: Hashable + Equatable, V, A: Allocator = GlobalAllocator>`

**Status: implemented** (`designs/48-ord-hash.md`, unified by `designs/54`).
`Map` is **THE dictionary type** — an **open-addressing** hash table (linear
probing, tombstone deletion) over a `Vector` of slot enums. (The old
Vector-backed linear-scan `Map` was **retired** in design 54; there is now one
`Map`, and the name `HashMap` no longer exists.)

- Power-of-two capacity (bucket = `hash & (cap-1)`); grows (doubling + rehash)
  once the live-load factor would exceed 3/4.
- `init()`, `len`, `is_empty`, `insert(key, value) -> V?` (returns the old value
  on update), `get(key) -> V?`, `contains_key(key) -> Bool`,
  `remove(key) -> V?`. Works with `Int` and `String` keys (and any
  `Hashable + Equatable` key).
- **Keys must be copyable-with-retain** (design 65): the container probes keys BY
  COPY (hash / compare / slot inspection), so a KEY must be trivial/POD,
  `ImplicitCopy` (String, `Arc<T>`), or `ExplicitCopy` — a **NoCopy** key, or a
  `Deinit`-only move-only key, is a clean compile error. VALUES have no such
  restriction (a NoCopy value is fine — it is moved, never probe-copied).
- Slots are an enum `{ Empty, Tombstone, Occupied(key, value) }`, so a fresh
  table is deinit-safe even for owning key/value types; slot updates/removals
  move the old slot out (`Vector.swap_out`, a refcount-neutral move), so nothing
  leaks or double-frees. `Map` is **NoCopy** (move-only): transfer with `move`;
  there is no implicit `.copy()` (an `ExplicitCopy` conformance is future work).
- **Iteration order is UNSPECIFIED** (table/bucket order). For deterministic
  output, sort a `keys()` snapshot (`String`/`Int` are `Comparable`).

### `Set<T: Hashable + Equatable, A: Allocator = GlobalAllocator>`

**Status: implemented** (`designs/54`). An unordered hash set, implemented as a
thin wrapper over `Map<T, SetMark>` (a zero-field unit value), so there is one
hash implementation to trust. `Set` is **NoCopy**; order is **UNSPECIFIED**
(sort a `to_vector()` snapshot for deterministic output). Elements inherit the
Map **key** rule: they must be copyable-with-retain (trivial/POD, `ImplicitCopy`,
or `ExplicitCopy`) — a NoCopy / move-only-Deinit element is a compile error.

- Core: `insert(v) -> Bool` (true iff newly inserted), `remove(v) -> Bool`,
  `contains(v) -> Bool`, `len()`, `is_empty()`, `each(body: (T) -> Void)`
  (non-escaping visitor; mutating the set inside its own `each` is a static
  Law-of-Exclusivity error), `to_vector() -> Vector<T, A>` (`T: Copy`),
  `Set(from: Vector<T, A>)` (consumes/drains the vector; NoCopy-safe),
  `Set.of(v)` (single-element factory).
- Algebra (all borrow `&other`, return a NEW set / `Bool`; bounded
  `T: Copy` — even membership-only ops read each element by value):
  `union`, `intersection`, `difference`, `is_subset`, `is_superset`.

**Iteration** (`designs/57`). Saw's no-escape references mean an iterator object
cannot borrow the map, so iteration is not an Iterator-over-a-borrow. Two forms:

- **Visitors** (the zero-allocation primitive) — non-escaping closures, same
  borrow discipline as `Vector.sort_by`/`withCString`:
  `each(body: (K, V) -> Void)`, `each_key((K) -> Void)`, `each_value((V) -> Void)`.
  Keys/values are handed to the closure **by value** (through the same whole-slot
  copy path `get` uses), so a visitor works for any key/value type `get` already
  supports (trivial + ImplicitCopy). Empty/Tombstone slots are skipped. **Order is
  UNSPECIFIED** (table/bucket order, not insertion order) — sort a `keys()`
  snapshot for deterministic output. Mutating the map inside its own visitor is a
  static Law-of-Exclusivity error (iterator invalidation caught at compile time).
- **Snapshots** (the convenience, built on the visitors): `keys() -> Vector<K, A>`
  (bounded `K: Copy`) and `values() -> Vector<V, A>` (bounded `V: Copy`). There is
  no `entries()` in v1 (a tuple-of-copies has containment wrinkles the visitors
  already cover).

### Numeric methods (`Int` / `Float`)

**Status: implemented** (`designs/57`, `std/numeric.saw`). `Int` and `Float` are
extendable primitive pseudo-structs (the same mechanism `String` uses), so
methods are called with ordinary `value.method(...)` syntax.

- `extension Int`: `abs()` (**panics on `Int.min`** — its positive magnitude is
  unrepresentable, so the negation overflows, per the house overflow rule),
  `min(other:)` / `max(other:)` / `clamp(low:, high:)`, `pow(exp:)` (repeated
  **checked** multiply; a negative exponent **panics** — no integer result),
  `is_even()` / `is_odd()`, `signum()` (−1 / 0 / 1).
- `extension Float`: `abs()`, `floor()`, `ceil()`, `round()` (half away from
  zero), `sqrt()`, `min(other:)` / `max(other:)`. These lower to the libm math
  functions and follow **IEEE** semantics — a `NaN` propagates, and `min`/`max`
  with one `NaN` operand return the non-`NaN` one.

---

## 6. Concurrency

**Status: implemented.** Saw's concurrency is **colorless** (designs/18 Axis
B′): there is NO `async`/`await` keyword and there never will be — any call may
suspend, and the marked side is the rare negative effect `sync` (a checked
suspension-free context). The model is task-only: no user-facing thread API, no
thread identity ever exposed — the engine is a swappable implementation detail.
Two engines ship and coexist (they are not unified): the design-21b
thread-per-task engine (`spawn`/`Task`/`Channel`, below) and the cooperative
single-threaded executor (the coroutine transform, suspending `main`, and the
multi-task `TaskGroup` — designs 44/45/52/52b, below).

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
- **Escaping-closure heap environments — `ImplicitCopy`, refcounted env**
  (design 71 + 73) — a closure used in value position (bound, returned, stored,
  or passed to `spawn`) outlives its creating frame, so its captured environment
  is `saw_alloc`'d instead of stack-allocated. Captures are **moved in at
  creation** (ImplicitCopy retained, trivial copied bitwise; a `move` capture
  takes ownership); the creating frame does not release a moved-in capture early.
  **An escaping closure is an `ImplicitCopy` value** (the family of `String` and
  `Arc`): its heap env leads with an **atomic refcount word**, the closure
  representation is `{ fn_ptr, env_ptr, dtor_ptr }`, and the env is immutable and
  shared. Copying a closure — `let g = f`, a struct/`Vector`/field copy, passing
  or returning by value — is a **refcount bump**; there is no observable mutation
  through a shared env, so the sharing is semantically invisible. Dropping a
  closure **releases** one reference: it decrements the refcount and, only at the
  last owner, runs the env destructor (releasing owned captures exactly once and
  freeing the block) under the normal LIFO + drop-flag rules, wherever the value
  lives (a `let`/`var`, a struct field, a `Vector` element, a returned result).
  A **capture-less** closure has a null env (no refcount word) and is trivially
  copyable. Forwarding a closure into a *non-escaping* (borrowing) parameter is a
  **lend** — no retain, and the caller keeps ownership (drops once). For `spawn`
  the task frame owns the closure's reference and the trampoline release is THE
  release — the env is torn down on the task thread exactly once. Non-escaping
  closures (a direct call argument, e.g. `Mutex.lock`'s body) keep a stack env and
  own nothing. `[&var x]` reference-captures remain non-escaping-only. *(This
  closed design 71's residual gap: an owning closure in a copyable struct that is
  then copied now retains the shared env and tears it down once at the last
  owner.)*
- **A closure satisfies the generic `Copy` bound** (design 77 DF-C2). Because an
  escaping closure is `ImplicitCopy`, a container element type of closures is
  copyable: `Vector<() -> Int>` is `ExplicitCopy`, and `.copy()`/`.get()` each
  retain the element env exactly once (balanced deinit through copy-and-read).
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
critical section stays synchronous (a `sync` closure cannot suspend), which is
how the never-block invariant makes holding a lock across a suspension point a
compile error. Task bodies may suspend under that engine, so a `spawn` closure is not a
`sync` context.

**Status: tasks, channels, Mutex, Send/Sync — implemented (stage 1,
thread-per-task engine). Cooperative engine — implemented: the coroutine
transform, suspending `main`, and multi-task `TaskGroup` (spawn / join / cancel /
suspending channel) all ship (designs 44/45/52/52b), including OPT-IN
multi-threaded execution `TaskGroup(threads: N)` with a Send-on-frames gate
(design 75).**
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
- **Suspension inside control flow** (design 52 Part 0): a suspension that spans a
  `while`/`for`/`if`/`match` body is supported by a **CFG-based state split**. The
  `resume` state machine is a dispatch loop over basic blocks; a loop back-edge or
  branch merge is a state transition, a suspension inside a construct just
  terminates its block, and the counter/binding it carries is frame-resident so
  counted iterations survive across resumes. `break`/`continue` in a
  suspension-spanning loop are supported; a `for` is over a range (a non-range
  iterable inside a suspending loop is a diagnostic, not a miscompile). A nested
  suspending call — free function OR method (design 84) — embeds as a driven
  sub-frame in **every** control-flow position: a plain statement, an `if`/`else`
  branch, a `match` arm (literal/range patterns included), a nested `if`/loop, and a
  **trailing** (block-final) `if`/`match` where the parser parks the block's last
  bare expression (design 101). There is no silent third outcome — a suspending
  call the state split cannot express is a diagnostic, never a plain blocking call.
- **Suspending recursion is a compile error.** A cycle in the suspending-call
  graph would have no finite frame size (frames embed by value), so it is rejected
  with a diagnostic that names the cycle (e.g. `ping -> pong -> ping`). Ordinary
  non-suspending recursion is unaffected.
- **References may span suspensions** (design 18 D6, task confinement;
  implemented design 88): a `&`/`&var` parameter or reference local — including
  `&var self` — remains valid and exclusive across a suspension, because the whole
  task suspends and resumes as a unit and references cannot escape it. In the
  implementation, such a reference becomes a frame-resident raw pointer into the
  referent's storage; reads/writes after resume address the same referent, and a
  `&var` mutation is visible to the caller (a driven suspending method, design 45
  Part 0c, is the same mechanism for its receiver). The reference does not own the
  referent, so it is never dropped by the frame — destruction stays exactly-once
  through the referent's real owner.
  - **Driven-in-place vs spawned (the confinement boundary).** A held reference is
    sound only when its referent outlives the frame. A function DRIVEN in place may
    freely hold a reference param into the driver's live storage. A SPAWNED task,
    whose frame is boxed onto the run queue and resumed later (possibly on another
    thread), may NOT take a reference PARAMETER — that would point into the
    spawner's stack, which can die before the task runs; it is a compile error
    (both single- and multi-threaded groups, a confinement rule deeper than the
    design-75 `Send` gate). A reference to a task-CONFINED local INSIDE the spawned
    body is fine — it points into the task's own frame, which the box keeps alive.
  - Container-internal borrows (`Vector.with_ref`/`with_var_ref`) keep their
    `sync`-body restriction: unlike a confined stack/frame referent, a container
    borrow projects into shared, reachable storage that a concurrent task could
    reallocate across a suspension, so it may not span one.
- **`deinit` may not suspend** — a destructor is always a `sync` context, so a
  suspension inside one is a compile error (deterministic destruction).
- **Effect polymorphism — generic suspending functions/methods** (design 70,
  A5). A generic function's suspend-bit is not fixed at its declaration: effect
  inference runs **per instantiation**, keyed by the mangled symbol. Each
  monomorphized instantiation re-runs the suspend fixpoint with its concrete
  type arguments bound, so `func run<T: Worker>(w: &var T)` suspends iff the
  instantiated `T`'s methods do — `run<Slow>` may suspend while `run<Fast>` is
  suspension-free, and the two coexist, each inferred independently. The
  coroutine transform accepts a suspending instantiation by monomorphizing it to
  a concrete function/method (name = mangled symbol) *before* frame synthesis, so
  a generic instantiation can be `__drive`n, `TaskGroup.spawn`ed, or driven as a
  `&var self` method through the ordinary (non-generic) machinery. A `sync`
  context that calls an instantiation which suspends is the normal sync
  violation, reported **at the call site**, naming the instantiation and the full
  suspension path (e.g. `run$1$Slow → Slow.step → __suspend`). Trait-object
  (`any Trait`) dispatch is unaffected: its effect follows the **declared** trait
  method signature (a `sync` trait method stays sync-callable through `any`), not
  a per-instantiation re-inference — erasure has no concrete `T` to re-infer.
  Driven methods on *generic structs* (`__drive(b.run())` for `b: Holder<Int>`,
  design 74 shape 2) and *nested suspending generic calls* from a driven body
  (design 74 shape 3) are also supported: a generic-struct method is monomorphized
  over the struct's type params so the frame's receiver pointer gets a concrete
  layout, and a nested suspending generic call is promoted to a concrete spliced
  callee embedded as a sub-frame by value (keyed by its mangled instantiation).
  A **closure** created in a driven body is supported (design 77 DF-C1): it is a
  frame field, an indirect call `f(args)` is rewritten to a call through that
  field, and captured frame locals are moved into the closure by value so its
  refcounted env deinits exactly once at frame death. A **tuple** local and a
  `let (a, b) = f()` **destructuring** also survive a suspension — their bindings
  are frame-resident (design 77). A suspending call in an **`if let` / `guard let`
  body** also embeds (design 104 item 1): the optional-binding branch is CFG-split
  like an `if`/`match`, the bound name becomes a frame field, `guard let`'s
  else-exit path splits with it, and the design-100 same-name unwrap `if let x = x`
  keeps the inner `x: T` and the outer `x: T?` in distinct fields. A method that is
  **both struct-generic and method-generic** (`Dual<T>.mix<U>`) drives too (design
  104 item 3): the frame is keyed by both instantiations (`Dual_mix$2$T$U` — design
  95's resolved-signature keying extended with the method's own type args), so
  2 struct × 2 method instantiations are 4 distinct frames.
- **Not yet supported** (rejected with a diagnostic anchored at the user's source
  line, not miscompiled): a suspending call buried in a *larger expression* (an
  argument, a receiver, a `let x = if … { s.read() }` value position); a
  suspension-spanning `if let`/`guard let` with a *tuple pattern*, or one whose body
  *re-binds* the bound name (rename the inner binding); a nested suspending *generic*
  call to a template in *another module*; a suspension inside a `for` over a
  non-range iterable; and a value-producing `break` out of a suspension-spanning
  loop.

**Suspending `main` and the cooperative executor (design 45 items 1 & 4).** The
real cooperative primitives are `yield_now()` (suspend and become immediately
re-ready) and `sleep(ms)` (suspend with a timed wake). Both are inferred
suspension points. When `main` transitively reaches one, the compiler infers
`main` suspending and auto-wraps it in an **entry executor** with no user-visible
plumbing: `main` becomes a frame + `resume`, and the generated entry drives it to
completion on a single cooperative run, parking the thread for each `sleep` wake
and resuming at once for each `yield_now`.

**Multi-task cooperative concurrency — `TaskGroup` (design 52b).** The
heterogeneous run queue is now built on `any Trait` erasure (design 51): every
coroutine frame is compiler-synthesized to conform to a builtin `Resumable`
trait — `resume(&var self) sync -> __Poll` (advance one step; `resume` is the
anti-suspension boundary, so it is `sync`) plus `__wake_reason(&self) sync -> Int`
(the wake surface: `0` = ready/yield, `>0` = sleep that many ms). A frame boxed as
`Box<any Resumable>` lets distinct frame types share one queue,
`Vector<Box<any Resumable>>`.

- **`TaskGroup`** is a local nursery. `group.spawn(f(args)) -> TaskHandle<T>`
  lowers like `__drive`: `f` becomes a spawnable root (frame + `Resumable`
  conformance), and a synthesized `__spawn_f` helper builds the frame, erases it
  into a `Box<any Resumable>`, enqueues it, and returns a typed handle. `T` must
  be non-`Void` (the handle needs a result slot; return a value such as a count).
- **The executor** lives in the group: round-robin drive to completion of all
  children, honoring wake reasons — `yield_now` requeues immediately, `sleep(ms)`
  is scheduled earliest-deadline over relative sleeps, and a channel wait is a
  yield-requeue retry (wake-on-send folded into yield). It is `sync` (built from
  `resume`), which is what lets the group's `Deinit` run it.
- **`TaskHandle<T>`** owns nothing — raw pointers into the group-owned heap frame.
  `join()` drives the group then TAKES the frame's `__result` exactly once
  (force-unwrap read + a slot clear, so teardown drops nothing). Dropping an
  unjoined handle is fine: the result stays in the frame and is dropped once at
  group teardown — exactly-once either way.
- **Structured join = LIFO destruction (design 18 C1).** The group's `Deinit`
  runs the executor to completion of every child, then tears each frame down.
  Because the group is declared before the resources its tasks use and before its
  own handles, LIFO destroys it *first* — draining children while those resources
  are still alive — and handles die before the frames they point into. Task
  frames are self-contained (spawn strips references, paper 18), so no scope
  ordering hazard arises. NO forced destroy anywhere.
- **Cancellation** is cooperative (design 18 C1). `handle.cancel()` sets a
  frame-resident `__cancel` word through the handle's raw pointer; task code reads
  it with `cancelled()` (rewritten to the frame's word) and returns through normal
  control flow — frame locals drop exactly once. There is no forced destroy and no
  implicit cancellation at suspension points.
- **Implicit yield + the cooperative fairness budget (designs 89-b/89-c).** A
  suspending call IS a yield point: when a read / accept / sleep / channel-receive
  PARKS (would-block / empty / deadline-not-reached) it cedes to the scheduler
  automatically, so a task doing real I/O never needs an explicit `yield_now`
  (and a call that has data ready returns WITHOUT parking — no spurious yield).
  The residual starvation risk — a task that keeps completing suspending io ops
  WITHOUT ever parking (an always-ready socket) — is bounded by a cooperative
  **op-count budget** (default 128): each io primitive that completes without
  parking charges a per-running-task budget, and when it is exhausted the primitive
  forces one `yield_now` (park-and-immediately-reschedule) so siblings run, then
  the budget resets; a genuine park resets it too. It is an OP-COUNT, never a
  wall-clock read — kernel-friendly and DETERMINISTIC (tests may assert exact
  interleavings). No new yield points, signals, or language surface — purely at
  existing suspension points. Honest limit: this only helps tasks that make SOME
  suspending calls; a pure-compute loop with no suspending call at all still needs
  an explicit `yield_now` (or an MT thread) — the same as every cooperative runtime.
- **Suspending channel receive (design 62 G3).** `Channel.receive() -> T` is the
  first-class cooperative suspending receive: it dequeues a value if ready, else
  suspends the *task* (not the thread) and is rescheduled when a value arrives
  (channel-yield wake). The coro transform lowers each `let v = ch.receive()` /
  `ch.receive()` call site INLINE into the `try_receive()` + `yield_now()` loop
  against the caller's own frame (no callee frame — so no generic-method-frame
  gap); `try_receive() -> T?` remains available for a hand-rolled cancellation-aware
  loop (`if cancelled() { ... }`). NAMING: the cooperative method is `receive`;
  the 21b thread engine's blocking `recv` keeps its name and is untouched (same
  signature `(&self) -> T`, so overloading — which cannot differ by effect —
  cannot distinguish the two). A `receive()` buried in an expression position (not
  a top-level `let v = ...` / bare statement) is rejected cleanly.

**Multi-threaded execution — `TaskGroup(threads: N)` (design 75 A2).** By default a
`TaskGroup()` runs its children on ONE thread (deterministic interleaving, above).
`TaskGroup(threads: N)` (`N >= 2`) opts a group into a MULTI-THREADED executor: N OS
worker threads drain a single mutex-protected SHARED run queue (the sanctioned
"one injector + N workers" — simplicity over per-worker lock-free deques, v1).
`TaskGroup()` and `TaskGroup(threads: 1)` stay byte-identical to the single-threaded
engine (no threads, no lock).
- **The drain is fork-join.** A drain is triggered lazily by `join()` / `Deinit`; it
  spawns N workers, each of which repeatedly LOCKS the queue, claims the first
  runnable frame (marking it active so no two workers touch one frame), UNLOCKS,
  `resume()`s it OUTSIDE the lock, then re-locks to record the outcome. The drain
  then joins all workers — an OS-level barrier that makes every frame's `__result`
  visible before `join()` reads it. `join()` and `Deinit` remain exactly-once and
  idempotent (a fully-drained group spawns nothing).
- **Send-on-frames gate.** A frame spawned into a multi-threaded group is handed
  between workers, so every value it carries across a suspension — the spawned
  function's parameters, its across-suspension locals (and those of embedded callee
  sub-frames), and its RESULT type (it travels worker→`join()`) — must be `Send`.
  The compiler rejects the first non-`Send` value at the spawned function, naming
  it and its type. Single-threaded groups skip the gate entirely. (A multi-threaded
  group must be spawned into *directly* for the gate to key on it — `threads:` is
  tracked on the group's binding, not yet through an opaque helper it is passed to.)
- **D6 task confinement (paper 18).** A frame runs on ONE thread at a time; stealing
  moves frames between workers only BETWEEN suspensions. There are no migration
  guarantees beyond Send-correctness; `&var self` driven methods stay task-confined.
- **Shared timer / cancellation.** Sleeps advance by the earliest deadline under the
  queue lock (a shared timer, no per-worker wheel). Cross-task cancellation:
  `TaskHandle.cancel_addr() -> Int` yields the `__cancel` word's address (a `Send`
  `Int`) so a canceller task can set it from a worker thread; the target observes it
  via `cancelled()` (the `__cancel` byte is set-once monotonic — race-free,
  eventually consistent, cooperative). The 21b thread-per-task `spawn`/`Task`/`Channel`
  engine is separate and untouched — the two engines coexist.

Now-closed gaps (design 62), each landed with tests:
- **`if let` / `guard let` over a suspending call (G2).** `if let x = f() { ... }`
  / `guard let x = f() else { ... }` whose condition is a plain suspending call is
  supported: the transform hoists the condition into a preceding driven temp
  (`let __t = f()`) and binds over it. The hoisted `T?` temp uses the `self_opt`
  frame encoding (an already-optional field is stored as-is, not double-wrapped).
  Only the plain-call form is hoisted — a move-in-condition remains a clean error.
  `while let` does not exist in the grammar.
- **`TaskGroup` inside a suspending function (G1).** A `TaskGroup` may be a direct
  frame-resident local of a suspending function: the group + its erased run queue
  are frame state, and `group.spawn(...)`'s `&group` resolves to an addressable
  frame field (plain-encoded, real empty-`TaskGroup()` placeholder). The group's
  `Deinit` still runs its executor to completion during normal frame cleanup
  (including across a parent suspension between spawn and drop); each group's
  executor drives only its own queue (nested groups compose without re-entrancy);
  cancellation words are frame-resident and reachable.

Remaining limits (rejected cleanly / documented, not miscompiled): a spawned
function must be non-`Void`; a suspending call as a nested *method* other than the
`receive()` inline lowering is not embeddable (use a free function or the loop
idiom); a suspension INSIDE an `if let`/`guard let` BRANCH (as opposed to its
condition) is not split.

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
                                 // engine); the cooperative engine uses the
                                 // suspending try_receive idiom (below)
producer.join()
```

### Cooperative tasks: TaskGroup

```saw
// The cooperative multi-task engine (design 52b). Tasks are stackless coroutine
// frames driven on the current thread — no OS threads, no thread identity.

func worker(base: Int) -> Int {
    print(base)
    yield_now()                  // cooperatively hand control back to the group
    return base + 1
}

func main() {
    var group = TaskGroup()
    let a = group.spawn(worker(10))   // -> TaskHandle<Int>; T must be non-Void
    let b = group.spawn(worker(20))
    print(a.join())                   // drive the group; take a's result: 11
    print(b.join())                   // 21
}                                     // group Deinit drains any unjoined child

// Cooperative suspending receive over a Channel (design 62 G3):
func consumer(ch: Channel<Int>) -> Int {
    var sum = 0
    var got = 0
    while got < 3 {
        let v = ch.receive()              // first-class cooperative receive:
        sum = sum + v                     // suspends the task while the channel is
        got = got + 1                     // empty, resumes when a value arrives
    }
    return sum
}
// (`try_receive() -> T?` is still available for a hand-rolled loop, e.g. a
//  cancellation-aware `if cancelled() { ... }` on the empty branch.)

// A TaskGroup may live in a SUSPENDING function's own frame (design 62 G1):
func orchestrate(base: Int) -> Int {
    var group = TaskGroup()
    let h1 = group.spawn(worker(base))
    let h2 = group.spawn(worker(base + 1))
    sleep(1)                              // the parent may suspend between spawn
    return h1.join() + h2.join()          // and join; the group drains at teardown
}

// OPT-IN multi-threaded execution (design 75 A2): N OS worker threads drain a
// shared queue. Every value a spawned frame carries across a suspension must be
// Send (params, across-suspend locals, and the result). Assert on counts/sums,
// never on the (nondeterministic) interleaving.
func square(n: Int) -> Int { yield_now(); n * n }
func parallel() -> Int {
    var group = TaskGroup(threads: 4)     // 4 workers; `TaskGroup(threads: 1)` and
    let a = group.spawn(square(3))        //   `TaskGroup()` stay single-threaded
    let b = group.spawn(square(5))
    return a.join() + b.join()            // 9 + 25 = 34 (order not observable)
}
//   group.spawn(needsVector(move v))    // COMPILE ERROR: `Vector<Int>` is not Send
//                                        // (share via Arc/Mutex/Channel instead)

// if-let / guard-let over a suspending call (design 62 G2):
func maybe_step(n: Int) -> Int? {
    yield_now()
    if n > 0 { return n * 10 }
    return None
}
func using_iflet(n: Int) -> Int {
    if let v = maybe_step(n) { return v } // condition hoisted to a driven temp
    return -1
}

// Cooperative cancellation (NO forced destroy):
func job() -> Int {
    var i = 0
    while i < 1000000 {
        if cancelled() { return i }       // observed where the task checks
        yield_now()
        i = i + 1
    }
    return i
}
// let h = group.spawn(job());  h.cancel();  print(h.join())
```

### Cooperative IO: the reactor (design 76)

Unbounded external waits (sockets) never block the cooperative executor. A
process-global **poller** — kqueue on macOS, epoll on Linux — is the reactor: when
no task is runnable the executor blocks in the poller with a timeout equal to the
earliest sleep deadline (never busy-waiting, never blocking while a task is
runnable), and wakes tasks whose fds are ready.

**Precise wakeup (design 91).** A readiness event wakes EXACTLY the frame(s)
registered for that `(fd, direction)` — not every io-parked frame. Each park
registers its fd carrying the parked frame's wake-word ADDRESS as the event's
user-data (`kevent.udata` / `epoll_event.data`); on a ready event the poller
latches that word, and the scheduler resumes only the frame whose word changed. The
latch is a persistent word (not an edge), so a readiness that races the park is
never lost. The token is per-PARK (the frame's own word), not per-fd-number, and
one-shot interest plus close both drop a registration — so a reused fd number can
never route a wake to a stale frame. Level-vs-edge posture: interest is one-shot
per park (`EV_ONESHOT` / `EPOLLONESHOT`), and each re-park re-registers. Two frames
waiting DIFFERENT directions on one fd are independent registrations (both woken
precisely); concurrent SAME-direction waiters on one fd collapse to one kernel
registration (last-registrant-wins) and are not a supported pattern.

**std.net — the safe owning API (design 84).** Application code uses owning socket
TYPES, never a raw fd or pointer. `TcpListener` and `TcpStream` are `NoCopy`; each
one's `Deinit` closes its fd exactly once (the move checkpoint prevents
use-after-close, `NoCopy` prevents double-close). Suspension is hidden INSIDE the
methods — `accept` / `read` / `connect` register the fd with the reactor and park
the task internally, so the caller writes an ordinary method call with no `io_wait`
in sight. Errors are `IoError` (conforms to `Error`, errno-shaped).

```saw
// A cooperative echo, entirely over the safe owning API.
func serve(stream: TcpStream) -> Int {
    let chunk = stream.read()             // suspends until bytes arrive; empty = EOF
    let n = chunk.len()
    stream.write_all(move chunk)          // suspends until every byte is sent
    return n                              // stream.Deinit closes the fd here
}

func main() {
    let listener = TcpListener.listen(0)!             // Result<TcpListener, IoError>
    let stream = TcpStream.connect("127.0.0.1", listener.local_port())!
    // ... spawn workers over accept()/read()/write_all_str() in a TaskGroup ...
}
// TcpStream.pair() gives a connected pair for tests/IPC with no bound port.
```

The design-76 raw layer (`tcp_*` / `net_*` free functions + `io_wait(fd, dir)`, a
`yield_now`-like suspension point that registers+parks on the reactor) still exists
as the PRIVATE implementation std.net's methods drive — it is not part of the public
surface.

Bounded local IO stays synchronous (regular-file read/write) — the never-block
invariant is about latency-UNBOUNDED waits, not IO in general.

**`extern blocking func`.** An FFI call that may block for an unbounded time is
annotated `blocking` inside an `extern` block; the call is a suspension point (it
offloads to a worker thread and suspends the task, rather than blocking the
executor):

```saw
extern "C" {
    blocking func db_query(id: Int) -> Int   // unbounded FFI -> suspends
}
```

An unannotated extern promises promptness and is `sync`-callable. A `blocking`
extern call is illegal in a `sync` context (a compile error, like any other
suspension), and `blocking` externs are rejected in the freestanding profile
(no thread pool).

Design 103 (A6) — the offload actually RUNS. Inside a suspending body (a driven /
spawned task, or a suspending `main`), a blocking-extern call bound to its own
statement (`let r = db_query(id)`, a bare call, or a tail `return db_query(id)`)
is lowered to: start a worker thread that runs the extern, PARK the task on the
worker's self-pipe (registered with the reactor exactly like a socket read), then
take the result when the pipe signals completion. So the task suspends
cooperatively — siblings keep running while it blocks, and the single reactor
thread is never wedged. The worker thread touches only its own job + pipe; all
wake routing stays in the reactor; the pipe byte and the join of the worker form
the release/acquire boundary, so the result transfers with no data race. v1 is
thread-per-call and restricts the extern to the C-ABI `(Int) -> Int` whitelist (a
pool + wider signatures are future work); a wider signature, or a blocking-extern
call buried in a larger expression (an argument, a `try!`), is a clean compile
error anchored at the call site. A blocking-extern call at statement position inside
a suspension-spanning `if let`/`guard let` body offloads like any other (design 104
item 1 CFG-splits the branch). Cancelling a task parked on an
offload job wakes it (via the design-102 reactor self-pipe), but the in-flight
blocking call cannot be aborted — the task joins the worker before taking its
cancel path.

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
extension Vector<T: Copy, A: Allocator = GlobalAllocator> {
    // `U` is a METHOD-level type parameter, distinct from the element type `T`
    // and the allocator `A` (which the result vector inherits).
    func map<U>(&self, transform: (T) -> U) -> Vector<U, A> { /* ... */ }

    // `Acc` is the accumulator type (named `Acc`, not `A`, since `A` is now
    // the extension's allocator type parameter).
    func fold<Acc>(&self, initial: Acc, combine: (Acc, T) -> Acc) -> Acc { /* ... */ }
}

var v = Vector<Int>()
// ...
let labels = v.map { "n={$0}" }           // Vector<Int> -> Vector<String>, U inferred
let sum    = v.fold(0) { $0 + $1 }         // -> Int, Acc inferred from `0`
let typed  = v.map<String> { "n={$0}" }    // explicit is always allowed and wins
```

The method's type arguments may be supplied **explicitly** at the call site
(`v.map<String>(...)`) or **inferred** from the argument types (design 93):
`v.map({ $0.to_string() })` solves `U` from the closure's inferred RETURN type,
`v.fold(0) { ... }` solves the accumulator from the initial argument. Inference
applies to generic free functions and methods alike; a non-generic call still
rejects type arguments. Explicit `<...>` always wins; a partial explicit prefix
pins its leading parameters and the rest are inferred; an unconstrained trailing
parameter with a default type fills from the default. Inference never guesses — a
parameter no argument constrains (**underdetermined**) or one an argument forces
to two different types (**conflict**) is a clean error naming the parameter and
suggesting explicit arguments, and an inferred argument is bound-checked naming
the inferred type. Inference is a single left-to-right pass (non-closure
arguments, then closures), so a parameter determinable only by a *later*
argument than one it gates must be given explicitly; likewise, generic
OVERLOAD resolution (two candidates of one name) still requires explicit `<...>`
on the generic candidate. The method body is checked abstractly
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
struct Vector<T, A: Allocator = GlobalAllocator> { /* ... */ }

var xs = Vector<Int>()           // A defaults to GlobalAllocator
var ys = Vector<Int, GlobalAllocator>()   // identical type to `xs`
var zs = Vector<Int, MySlab>()   // a distinct type over a custom allocator
```

The **identity rule** is the load-bearing guarantee: defaults are applied
**before name mangling**, so `Vector<Int>` and `Vector<Int, GlobalAllocator>` produce the
*same* mangled name and the *same* monomorphized struct — they are one type, not
two that happen to coincide. Consequences:
- A function declared over `Vector<Int>` accepts a `Vector<Int, GlobalAllocator>` value,
  and vice-versa — they are interchangeable everywhere.
- A `Vector<Int, MySlab>` is a **distinct type**: passing it where `Vector<Int>`
  is expected is a compile error. Allocator identity is part of the type (this is
  what makes cross-allocator mixing unrepresentable rather than a runtime bug).
- Omitting an argument for a parameter that has **no default** is an arity error,
  and a default that fails its parameter's bound (`A: Allocator = SomeNonAllocator`)
  is rejected. Defaults referencing an earlier parameter are not supported (every
  stdlib default is a ground type such as `GlobalAllocator`).

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

**`static_assert` — implemented (design 53).** `const func`, macros, and
compile-time reflection below are still *planned*.

`static_assert(<const-expr>, "message")` is legal at top level and in statement
position. The condition is evaluated at compile time (with authoritative target
layout, so `sizeof`/`alignof` are exact): a false result is a **compile error
carrying the message**, a true result emits **zero code**. The evaluator accepts
integer/`Bool` literals, unary `-`/`not`, arithmetic/comparison/logical
operators, `sizeof<T>()`/`alignof<T>()`, and the `Int.max`/`.min` limits;
anything else (e.g. a runtime function call) is rejected as non-constant.

```saw
// Kernel register-block drift check
static_assert(sizeof<UartRegs>() == 0x1C, "UartRegs layout drift")
static_assert(alignof<UInt32>() == 4, "unexpected alignment")

func f() {
    static_assert(Int.max > 0, "sanity")   // also valid in statement position
}
```

```saw
// Const functions evaluated at compile time (planned)
const func factorial(n: Int) -> Int {
    if n <= 1 { 1 } else { n * factorial(n - 1) }
}

const FACT_10: Int = factorial(10)
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

**Status: implemented.** `import` (module, specific-symbol, and qualified
forms), inline and external `module` declarations, `public` visibility, scoped
visibility (`public(package)`, `public(parent)`), import aliasing (`as`, design
53), glob imports (`import x.*`), and qualified access (`module.Type`) are all
built. The `Saw.toml` package layout is handled by the Blade package manager.

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

// Scoped visibility (implemented)
public(package) func internal_api() { ... }
public(parent) func parent_visible() { ... }
```

#### Member visibility (design 80)

Struct FIELDS and extension METHODS (including `init` and static methods) are
**private-by-default OUTSIDE the defining module** — the same rule and the same
modifier family (`public` / `public(package)` / `public(parent)`) as top-level
declarations. Inside the defining module, member access is unrestricted.

```saw
public struct Account {
    public name: String    // readable/writable cross-module
    balance: Int           // private: only this module can touch it
}

public extension Account {
    public init(name: String) -> Account { Account(name: name, balance: 0) }
    public func balance_of(&self) -> Int { self.balance }  // public accessor
    func settle(&var self) { ... }                          // private helper
}
```

Consequences:
- A member marked `public` on a member of a non-public struct is legal but
  inert (like Rust) — the struct itself gates reachability.
- **Cross-module memberwise construction** (`Account(name:, balance:)`) requires
  ALL fields visible; if any field is private, use a visible `init` instead. The
  same rule governs any field access — reads AND writes go through one gate, so a
  private field cannot be corrupted from another module (this is what closes the
  `Vector.length`/`capacity` memory-safety hole: those invariants are private,
  and a bounds-checked `get()` can no longer be tricked into an OOB read).
- **Trait-conformance methods follow the trait**: a method satisfying a visible
  trait's requirement is callable wherever the conformance is visible (a
  `public` marker on it is allowed and redundant); dispatch through `any Trait`
  and generic bounds is unaffected.
- Enum variants follow the enum's visibility (per-variant visibility is not in
  scope). Saw has no struct-destructuring patterns, so pattern matching reaches
  only enum-variant payloads, gated by the enum.
- **The standard library is under the gate too**: std types expose their real
  API `public` and keep their internals private (the `_`-prefix convention is
  now backed by real privacy). std has **no special visibility status** (design
  82): each std file is its OWN module for the member gate — a private field or
  method of one std file is invisible to another, exactly like user modules;
  genuinely-shared std internals are marked `public(package)` (std is the
  package). User code is always a separate module from std.

### The prelude (design 82)

Not all of std is auto-visible. The **prelude** — the names usable without an
`import` — is a curated core:

- primitives (`Int`, `UInt`, the fixed-width ints, `Float`, `Bool`, `String`,
  `Void`, `Never`), core containers (`Vector`, `Map`, `Set`), core wrappers
  (`Optional`, `Result`, `Box`, `Arc`, `Allocator`, `GlobalAllocator`);
- core traits (the Copy family, `Deinit`, `Iterator`, `Equatable`, `Comparable`,
  `Hashable`, `Printable`, `Error`, `Send`, `Sync`);
- the builtins (`print`/`panic`/`assert`/`sizeof`/`alignof`/`static_assert`) and
  the concurrency primitives (`TaskGroup`, `yield_now`, `sleep`, `spawn`,
  `cancelled`); `StringBuilder` (common enough to stay bare).

Everything else in std is **import-required**: `File`, `Directory`, `Path`,
`Data`, `Channel`, `Mutex`, `Duration`, `Instant`, `IoError`, `Utf8Error`, the
whole `net` surface (`TcpListener`/`TcpStream`), and the `process`/`env`/`time`
contents. These stay compiler-known for codegen but are not injected into a
user namespace without `import std.<module>`. A bare reference to one is a clean
error ("`TcpStream` is not in the prelude and must be imported") naming the
import that supplies it. Because a non-imported std module is not even compiled
into the program, a user is free to define its OWN `IoError`/`File`/etc. with no
clash.

### Imports

Imports follow Python-style semantics - only the explicitly named symbol is added to the namespace:

```saw
// Import specific std symbols - adds only those names, usable bare (design 82).
// A std import re-exposes names already compiled into the builtins; it does NOT
// create a `mod.Name` alias (the leaf, e.g. `data`/`net`, is a common local).
import std.net.{TcpListener, TcpStream}
let l = TcpListener.listen(0)!

// Whole std module - exposes every symbol the module defines, bare.
import std.file
let f = File.create("data.txt")

// User-module imports still support qualified access + aliasing (design 53).
import mypkg.parser.{Parser}
import mypkg.collections.{Map as Dict}           // per-symbol alias
import mypkg.io as fileio                          // module alias

// Import from current package
import package.parser.Parser
import parent.helpers.utility

// Glob import (implemented, discouraged) — all public symbols enter scope
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
namespace layout and are largely *illustrative* (the concrete names may differ).
Actually shipped today: `String`, `StringBuilder`, `Vector<T, A>`,
`Map<K, V, A>`, `Set<T, A>`, `Arc<T>`, `Box<T, A>`, `Mutex<T>`, `Channel<T>`,
`Task<T>`, `TaskGroup`, `File`, `Directory`, `Path`, `Data`, `Env`, `Process`,
`std.time` (`Duration`/`Instant`), plus `Int`/`Float` numeric extensions and the
`Equatable`/`Comparable`/`Hashable`/`Printable`/`Error` traits (and
`Result`/optionals as language features). I/O beyond files, `net`, `RwLock`, and
a formalized module namespacing are still planned. There is no `async`/`future`
module: concurrency is colorless (no `async`/`await`).

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
// Colorless tasks — no thread API, no async/await. Cooperative primitives
// (yield_now/sleep), TaskGroup (spawn/join/cancel), and the thread-per-task
// spawn/Task/Channel engine. See §6 Concurrency for the real API.
spawn { ... } -> Task<T>          // thread-per-task engine
group.spawn(f(args)) -> TaskHandle<T>   // cooperative TaskGroup
Mutex<T>, Arc<T>, Channel<T>      // sharing + synchronization primitives
```

### Utilities

```saw
std.fmt.{format, Display, Debug}
std.iter.{Iterator, IntoIterator}
std.cmp.{Ord, PartialOrd, Eq, PartialEq}
std.hash.{Hash, Hasher}
std.time.{Instant, Duration}
```

**`std.time`** is **implemented** (`designs/57`, `std/time.saw`) and
**hosted-only** (it links libc for the clock; freestanding kernels provide their
own timer): `Duration { nanos: Int64 }` with `secs`/`millis`/`micros`/`nanos`
accessors and `from_millis`/`from_secs` constructors (Equatable + Comparable +
Printable, rendering a human form like `1.42s` / `230ms`); `Instant.now()` (a
monotonic clock), `elapsed()`, and `duration_since(earlier:)`; and a free
`unix_timestamp() -> Int64` (wall-clock seconds since the Unix epoch). `Int64`
nanoseconds keep the layout stable across platform Int widths.

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
hosted-only modules (`File`, `Process`, `Env`, `Directory`, `time`) and `Float`
printing are unavailable. See `designs/19-freestanding-profile.md` for the full design.

---

## 10. Interoperability

**Status: implemented.** `extern "C"` function declarations, the pointer types
`UnsafePointer<T>` / `UnsafeConstPointer<T>` (plus `sizeof<T>()` and
`alignof<T>()` builtins, which fold to the target's ABI size and alignment of
`T` in bytes at monomorphization time), and **C-callable exports via `@export`**
(design 58) are all shipped. There is **no** `#[repr(C)]` attribute: every Saw
struct already has a stable **declaration-order, natural-ABI layout** (see
[Structs](#structs)), so C-compatibility is the language rule rather than an
opt-in — export signatures are gated by a C-safe type whitelist instead. There
are **no** `unsafe` blocks/functions/traits — unsafety is type-carried (see
[Unsafe Code](#unsafe-code) below). Still *planned*: C-varargs on the export
side. (The spec's `*Char`/`*var Void` shorthand is illustrative; the implemented
spelling is `UnsafePointer<T>` / `UnsafeConstPointer<T>`.)

### C FFI

```saw
// Declare external C functions
extern "C" {
    func printf(format: UnsafeConstPointer<Int8>, ...) -> Int
    func malloc(size: UInt) -> UnsafePointer<Int8>?
    func free(ptr: UnsafePointer<Int8>)
}

// Export a Saw function under the exact C symbol `my_function` (design 58):
// C calling convention, unmangled symbol, external linkage, kept alive
// through DCE. See the Attributes section for the signature whitelist.
@export
func my_function(x: Int32) -> Int32 {
    x * 2
}

// Rename the emitted symbol, and place it in an object-file section:
@export("_start")
@section(".text.boot")
func kernel_entry() -> Never {
    // ... never returns; lowered to a `void` + `noreturn` C symbol ...
    panic("unreachable")
}

// Aggregates cross the boundary by pointer (the layout guarantee makes this
// correct); pass `UnsafePointer<CStruct>`, never a by-value struct.
struct CStruct {
    x: Int32,
    y: Int32,
}
```

### Attributes (design 58)

**Status: implemented.** Attributes are Swift-style `@name` / `@name("string")`
lines placed immediately before a declaration. In v1 they are legal **only on
top-level `func` and `static` declarations** — an attribute on a struct, enum,
trait, extension, type alias, extern block, method, or local is a clean
"attributes are not supported on X" error (the grammar leaves room for
`#[test]`/derive-style growth without opening it yet). An unknown attribute name,
a repeated attribute, or the wrong argument shape is a compile error. The v1 set
is `@export` and `@section`; `@inline` is reserved for a later design.

**`@export` / `@export("sym")`** makes a function or static callable from C. It
is one unified attribute whose meaning is inseparable: **C calling convention +
exact unmangled symbol** (or the explicit `"sym"`) **+ external linkage + kept
alive through DCE** (via `@llvm.used`, so it survives the default -O1 pipeline
even when nothing in the program references it — the `_start` / vector-table
shape). There is deliberately no separate `no_mangle`/`c_abi` split.

Restrictions on an exported **function** (each a clean error):

- top-level free functions only (grammar already excludes methods/closures);
- **not** generic (a C symbol has no type parameters);
- effect-`sync`: an export is an effect **root** like `main` and must be
  transitively suspension-free — a coroutine frame cannot cross a C boundary;
- **signature whitelist** (params and return): the fixed-width integers
  `Int8`…`Int64` / `UInt8`…`UInt64`, the platform words `Int` / `UInt` (the C
  `intptr_t`/`uintptr_t` shape), `Float`, and `UnsafePointer<T>`; the return may
  additionally be `Void` or `Never` (lowered to a `void` + `noreturn` symbol).
  **Rejected in v1:** `Bool` (the extern-import path lowers it as a bare `i1`,
  which does not match the platform C `_Bool` ABI), `String`, optionals,
  `Result`, tuples, closures, and **all by-value structs/enums** — pass an
  aggregate as `UnsafePointer<S>` (the layout guarantee makes that correct).

An exported **static** relaxes the whitelist (data has no calling convention):
fixed-width integers, `Int`/`UInt`, `Float`, **arrays** thereof, and **structs**
whose fields are all whitelisted. Statics are already immortal and `Sync`-only
(see [Statics](#module-level-statics)); `@export` only names the symbol and keeps
it alive.

**Symbol hygiene.** Two exports resolving to the same symbol are an error (an
unmangled C symbol must be unique); colliding with a reserved runtime symbol
(`main`, `saw_*`, `__saw_*`) is an error. `@export` composes with overloading
(the exact-match model): an exported function's *name* may be overloaded
Saw-side, but only **one** overload may carry `@export` without an explicit
symbol name — otherwise both would claim the same unmangled symbol. `public` is
not required (export is its own visibility to the linker), but module visibility
still governs Saw-side callers.

**`@section("name")`** places a top-level function or static in the named
object-file section (the LLVM section attribute). It composes with `@export` and
does not require it; the name is passed through verbatim (the linker's problem)
beyond a non-empty check. Section-name *syntax* is target-specific — ELF accepts
`.vector_table`, mach-o requires the `SEG,sect` form.

```saw
// The freestanding vector-table idiom (design 58 Part 3):
@export("_vectors")
@section(".vector_table")
static VECTORS: [UInt32; 64]        // externally-visible, kept alive, in-section
```

### Unsafe Code — unsafety is type-carried, not region-carried

**Principle (design 55): unsafety is type-carried, not region-carried.** Saw has
**no** `unsafe { }` blocks, `unsafe func`, or `unsafe trait`. Where a construct
carries a proof obligation the compiler cannot discharge, the *type* names it —
the `Unsafe` prefix is the marker. `UnsafePointer<T>` / `UnsafeConstPointer<T>`
(raw pointers), `UnsafeMemory<T, Use>` (typed memory at a fixed address), and the
explicit `as`-casts that mint them are the entire surface: touching one of these
types *is* the opt-out, so the obligation travels with the value that carries it
rather than being fenced off in a lexical region.

**The visibility rule (design 81).** The type-carried principle gains one
refinement: *where a raw pointer would flow **invisibly** — with no `Unsafe*`
type spelled at that exact site — the `unsafe` expression marker is required
there.* `unsafe` is a contextual keyword that prefixes an expression; it sits
just below assignment and looser than every operator (`unsafe base + n` marks
the whole arithmetic; `unsafe p[0] = 5` marks the whole store — the marker
lifts off the lvalue onto the assignment). This keeps every entry to the raw
domain greppable — by a signature, a field type, a pointer-naming cast, or the
`unsafe` keyword — without a region block that would say nothing.

Where the marker is **required** (in a function whose own signature carries no
`Unsafe*` type):

- **Deref / index — read or write:** `unsafe ptr[i]`, `unsafe ptr[i] = v`.
- **Raw pointer arithmetic:** `unsafe base + n`.
- **Binding a pointer produced by a call:** `let p = unsafe A().alloc(s, a)` —
  a pointer-returning call shows no pointer type at the call syntax (this
  includes a discarded pointer-returning call, e.g. `unsafe memcpy(...)`).

Where it is **not** required — the pointer is already visible or is pass-through:

- A **cast that names a pointer type** and any pointer op transitively inside it:
  `(base + n) as UnsafePointer<T>` needs no marker (the cast is the marker).
- A **parameter / return / field** of pointer type (the signature or field decl
  is the visible marker), and **passing** a pointer value through a call.
- Inside the **marked domain**: a function whose own signature carries a raw
  pointer (parameter or return), OR a `self`-receiver method of a struct that
  declares a raw-pointer field — there the field decl is the marker, which is
  what keeps container *access* methods (`Vector.get`/`push`, `Arc.copy`) marker-
  free while a no-`self` **factory** (`Box.make`, which mints a fresh pointer via
  `alloc`) still shows the marker.

`unsafe` on an expression that performs **no** unsafe operation is a clean
error ("`unsafe` marks an expression with no unsafe operation") — markers stay
honest. Compiler-synthesized code (coroutine frames) is exempt by provenance.

```saw
// The obligation rides the type. Constructing a raw view IS the opt-out —
// no block, no `unsafe func`.
static UART0: UnsafeMemory<UartRegs, Device> = UnsafeMemory(0x1800_0000)

// `addr: Int` carries no Unsafe* type, so the raw-pointer flow is marked.
func poke(addr: Int) {
    let p = addr as UnsafePointer<Int32>   // cast NAMES the type: visible, no marker
    unsafe p[0] = 42                       // placement-move through a raw pointer
}

// Signature carries `UnsafePointer` -> the MARKED DOMAIN: ops here are free.
func poke_domain(p: UnsafePointer<Int32>) {
    p[0] = 42
}
```

For scoped, no-copy access to a container element (including a `NoCopy` one)
without minting a raw pointer at all, use `Vector.with_ref`/`with_var_ref`
(design 81): a non-escaping `&T`/`&var T` borrow of the element in place, with
the whole vector held borrowed for the body (reallocation- and
invalidation-proof). This replaced the removed `ref_at`.

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
layout** — the same language-level rule that governs [all structs](#structs), so
a register block's field offsets are exactly what the hardware manual lists.
Reserved `_pad` fields are the interim idiom for holes; there is no `repr`
attribute (design 58 — the layout rule replaces one).

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

### Allocators (`Allocator` trait, `GlobalAllocator`, public `A` parameter)

**Status: implemented — public type parameter, `GlobalAllocator` default.** Alloc-layer
stdlib types (`Vector`, `Map`, `Data`, `StringBuilder`, `Arc`, ...) obtain memory
through the `Allocator` trait — `alloc(&self, size: Int, align: Int) ->
UnsafePointer<Int8>?` and `dealloc(&self, ptr, size, align)` — rather than
calling the `saw_alloc` / `saw_dealloc` seams directly. `GlobalAllocator` is a zero-field
unit struct that wraps the seams; because it is zero-sized, `GlobalAllocator().alloc(...)`
monomorphizes to a direct seam call with no allocator value materialized at
runtime.

The allocator is a **public type parameter with a default**:
`Vector<T, A: Allocator = GlobalAllocator>` and `Map<K, V, A = GlobalAllocator>`. Hosted code
writes `Vector<T>` unchanged — the default fills `A = GlobalAllocator` before mangling, so
`Vector<T>` and `Vector<T, GlobalAllocator>` are one type (see
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

**Status: implemented (design 42).** `Box<T, A: Allocator = GlobalAllocator>` owns one
`T` allocated through allocator `A`. Hosted code writes `Box<T>` (the default
fills `A = GlobalAllocator`); a kernel writes `Box<Job, JobSlab>` to place the value in a
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

The `dyn` reservation is RETIRED — type-erased dynamic dispatch is spelled
`any Trait` (a contextual keyword in type position, so `any` is still a valid
identifier). The opaque/static-dispatch counterpart, when it lands, will use the
provisional keyword `generic`. `sync`, `escaping`, and `any` are all contextual
(recognized only in specific positions), so they are not reserved words.

The `loop` and `ref` reservations are RETIRED (design 55): `loop` was redundant
with `while { }` (the infinite-loop idiom), and `ref` never had a design — a
future by-reference match binding would reuse the `&` sigil vocabulary — so both
are freed as ordinary identifiers. `do` and `defer` stay reserved (cheap
insurance for plausible futures).

```
Implemented:
as       break    case     catch    continue deinit   else     enum
extension extern  false    for      func     guard    if       import
in       init     let      match    module   move     None     not
package  parent   public   return   self     Self     static   struct
trait    true     try      type     var      while

Contextual (recognized only in type/effect positions; still valid identifiers):
any      escaping sync

Planned / reserved:
and  const  defer  do  generic  macro  none  or
some  unsafe  where
```

`async` and `await` are deliberately **absent** — Saw is colorless and will
never have them (see §6 Concurrency).

## Appendix B: Operators

```
Implemented
  Arithmetic:     +  -  *  /  %        (overflow panics — see Integer Arithmetic)
  Wrapping:       &+ &- &*             (two's-complement wrap; integer-only)
  Bitwise:        &  |  ^  ~  << >>    (integer-only — see Bitwise & Shift)
  Comparison:     == != <  >  <= >=
  Logical:        &&  ||  not        (`not` is logical NOT — not `!`)
  Assignment:     =  += -= *= /= %=  &= |= ^= <<= >>=
  Range:          ..  ..=            (`..` half-open, `..=` inclusive — design 53)
  Optional:       ?  ??  ?.  !        (`!` is force-unwrap; `?.` optional chain)
  Reference:      &  &var             (`&x` at a call site; `&var` params)
  Cast:           as                 (`x as Int`)
  Member/return:  .  ->
  Attribute:      @                  (`@export`, `@section("...")` — design 58;
                                      declaration position only)

Planned (parsed shape may differ or be rejected today)
  Arithmetic:     **                 (power — use `Int.pow(...)` today)
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
  range            ..  ..=
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

---
name: saw-lang
description: Writing Saw code — syntax cheat sheet, ownership/move rules, collections, errors, concurrency, and gotchas. Load BEFORE writing or reviewing any .saw file. Authoritative reference is LANGUAGE_SPEC.md; this is the working digest.
---

# Writing Saw — working digest

Saw = Rust-grade safety + Swift ergonomics. No lifetimes, no GC, no
null, no async/await coloring. When this digest is not enough, grep
LANGUAGE_SPEC.md (authoritative) — section names match the headers
below.

## Core syntax
```saw
let x = 42                 // immutable binding (must initialize)
var n = 0; n += 1          // mutable
func f(a: Int, b: Int = 2) -> Int { a * b }   // default param (trailing)
f(5)  f(5, 3)  f(5, b: 3)  // labels optional; required only on ambiguity
struct Point { x: Int, y: Int }
extension Point { func mag(&self) -> Int { self.x * self.x } }
extension Point { init(m: Int) -> Point { Point(x: m, y: m) } }
enum Msg { case Quit, case Move(x: Int, y: Int) }
type UserId = Int          // DISTINCT type; flows TO Int; back via UserId(i)
let raw = id as Int        // explicit projection toward underlying
print("hi {name}: {p}")    // interpolation; user types need Printable
```
- Everything is an expression (if/match/while/blocks yield values;
  `break v` from loops → Optional).
- `for i in 0..5` / `0..=5`; `while cond {}` / infinite `while {}`.
- Integer literals: `0xFF`, `0b1010`, `1_000_000`, fixed-width
  suffixes `255u8`/`1_000i32` (exact-typed, range-checked).
- `\u{1F600}` escapes; strings are immutable UTF-8, refcounted.
- Comments `//`. No semicolons. `not` for logical negation.

## Ownership (the part that bites)
Copy tiers: trivial/POD = implicit bitwise copy; `ImplicitCopy`
(String, Arc) = free refcount bump; `ExplicitCopy` (Vector, Map, Set)
= must `move v` or `v.copy()` at every transfer; `NoCopy` (File,
Mutex, Box) = `move` only.
```saw
var w = move v         // v now invalid (use-after-move = compile error)
var u = w.copy()       // explicit duplicate
```
- `move` works on ANY type and retires the binding; a moved `var`
  revives on reassignment.
- NO partial moves (`move p.x` is an error) — move whole bindings.
- References `&T`/`&var T` are PARAMETER-ONLY, cannot escape/be
  stored. Call sites mirror the sigil: `f(&x)` / `f(&var x)` (and `x`
  must be `var`). Mutate through `&var` via compound assignment or
  methods — plain `x = ...` through a ref is rejected.
- Law of Exclusivity: one `&var` XOR many `&` to overlapping paths,
  statically checked.
- Deterministic LIFO destruction (`Deinit` trait); never call
  `deinit()` manually.
- `let _ = expr` = true discard (consumes + drops immediately).

## Collections & literals
```saw
let v: Vector<Int> = [1, 2, 3]      // [..] is a fixed array unless
                                    // the expected type is Vector
let m = {"a": 1, "b": 2}            // Map<String,Int> (hash; unordered)
let s = {1, 2, 3}                   // Set<Int>
let e: Map<String,Int> = {:}        // empty map needs annotation
// {} and {expr} are ALWAYS closures — use Set<T>() / Set.of(x)
```
- Map/Set keys: `Hashable + Equatable` and copyable-with-retain
  (NoCopy keys rejected). Values unrestricted. Iteration order
  unspecified — sort `keys()` for determinism.
- Iterate: `m.each { k, v in ... }`, `each_key`, `keys()/values()`
  snapshots (Copy elements); `v.iter()`, `v.enumerated()` (for-in),
  `each`/`map<U>`/`fold<A>` closures; Set algebra:
  union/intersection/difference/is_subset (elements `T: Copy`).
- Duplicate literal keys: last wins. Tuples: `(1, "a")`, `.0`/`[0]`;
  named tuples `(x: 3, y: 4)` with `.x`; destructuring
  `let (a, _) = pair` (irrefutable only in let).

## Patterns
```saw
match x {
    case 0 -> "zero",
    case 1..=9 -> "digit",           // both 1..9 and 1..=9
    case n if n < 0 -> "neg",        // guards never prove exhaustiveness
    case (0, y) -> "axis {y}",       // tuple patterns nest
    case _ -> "other"                // fallback required with literal arms
}
match msg { case Move(x, y) -> ..., case Quit -> ... }  // enums exhaustive
if let v = maybe { } / guard let v = maybe else { return }
if let (a, b) = optPair { }          // tuple over Optional tuple
```
- String literal patterns compare by content. `true`+`false` exhausts
  Bool. Match on an OWNED enum consumes it (bindings own payloads).

## Errors
```saw
func parse(s: String) -> Result<Int, ParseError> {
    if bad { return ParseError(...) }   // auto-wrapped Err
    return 42                            // auto-wrapped Ok
}
try! f()   try? f()   try f() catch { fallback }
try { let a = try f(); let b = try g() } catch {
    match error { case ParseError(e) -> ..., case IoError(e) -> ... }
}   // multi-type: error is an ephemeral union (can't escape the catch)
func load() -> Result<Cfg, Box<any Error>> {   // erased: any error type
    let t = try read()      // concrete errors auto-box at the boundary
    ...
}   // catch binds the box; "{error}" prints via vtable; NO downcasting yet
```
- `trait Error: Printable {}` — conform via `extension E: Error {
  func format(&self, into: &var StringBuilder) {...} }`.
- Optionals: `T?`, `None`, force `!` (panics), `??`, `?.`, and
  call-site auto-wrap (`f(5)` matches `f(x: Int?)`).
- `panic(msg) -> Never`; `assert(cond, msg)`. Overflow/bounds/shift
  violations panic ALWAYS (wrap intentionally with `&+ &- &*`).

## Traits & generics
```saw
trait Shape { func area(&self) -> Int
              func describe(&self) -> String { "area {self.area()}" } }
extension Circle: Shape { func area(&self) -> Int { ... } }  // default inherited
func show(s: &any Shape) { print(s.area()) }   // dynamic dispatch
var boxed: Box<any Shape> = Box<any Shape>.make(c)  // owned existential
func biggest<T: Shape + Comparable>(v: &Vector<T>) -> ...
v.map<String>({ $0.to_string() })   // method type args are EXPLICIT
```
- `any` only behind `&`, `&var`, or `Box` (unsized otherwise).
- Equatable: auto for trivial structs/payload-free enums; opt in with
  empty `extension T: Equatable {}` (synthesized) elsewhere.
  Comparable requires Equatable (no auto). Hashable mirrors Equatable.
  Printable: hand-written `format` (no synthesis).
- Overloads resolve by EXACT types (no conversions), labels
  disambiguate same-type sets (`f(0, value: 4)`).

## Concurrency (colorless)
```saw
func work(n: Int) -> Int { yield_now(); n * n }  // any call may suspend
func main() {
    var group = TaskGroup()
    let a = group.spawn(work(3))
    print(a.join())        // structured join; group Deinit drains children
}
sleep(200)                  // cooperative; sync is the CHECKED negative effect
ch.receive()                // cooperative channel receive (blocking twin: recv)
handle.cancel(); if cancelled() { ... }   // cooperative cancellation
```
- `func f(...) sync -> T` promises no suspension (checked).
- Thread engine (`spawn`/`Task`/`Channel.recv`) is separate from the
  cooperative TaskGroup engine — don't mix per task.
- Generic suspending functions/methods work (design 70): effect is
  re-inferred PER instantiation, so `f<A>` may suspend while `f<B>` is
  sync. You can `__drive` / `group.spawn` a generic instantiation and drive
  a generic `&var self` method. Still unsupported (clean compile error): a
  buried suspending method call on a `T`-typed value inside a driven body
  (drive the method directly, or make the call a nested free function),
  and driven methods on generic STRUCTS.

## Modules & packages
```saw
import std.io               // adds `io`; import std.io.{Read as R}
import mymodule as mm       // aliasing; `module`/`public`/`package`/`parent`
```
- Visibility: `public`, `public(package)`, `public(parent)`, private
  default. Package layout: `src/lib.saw` ← `import <pkgname>` (Blade
  `--module-path`); `src/main.saw` for binaries.

## Systems/embedded corner
`static NAME: T = const_init` (Sync-only, immortal); `Atomic<Int>`;
allocator type params `Vector<T, A: Allocator = Global>`, `Box<T, A>`,
slab in std/slab.saw; `UnsafeMemory<T, Device|Normal>` for MMIO
(volatile, RO/WO markers); `@export("sym")`/`@section(".s")` on
top-level func/static (C ABI, whitelist: fixed-width ints, Int/UInt,
Float, UnsafePointer, Void/Never — no Bool/String/aggregates by
value); `static_assert(sizeof<T> == N, "msg")`; struct layout =
declaration-order natural ABI (documented rule). Unsafety is
TYPE-carried (Unsafe* prefix), not region-carried — no unsafe blocks.

## Gotchas
- An escaping closure (bound/returned/stored/`spawn`) that captures owned
  values is an OWNING value: it drops its captures when the closure
  drops, and is **NoCopy** — `let g = f` on a closure binding is an
  error, use `move f`. Forwarding a closure into a non-escaping
  (borrowing) param needs no move. Storing an owning closure in a
  COPYABLE struct and then copying that struct still double-frees
  (known gap) — put it behind a NoCopy owner if you must copy.
- `guard` must exit (return/break/continue/panic).
- A dependency name mapped via `--module-path` shadowing a local
  module file is an error.
- `Vector.get(i)` returns a COPY (needs copyable element); use
  `swap_out(i, v)` to move a slot out; `ref_at` for NoCopy access.
- String `chars()` yields Int scalars (no Char type).
- `to_int()`/`to_float()` are whole-string, no trimming → Optional.
- std.time/std.process/std.file are HOSTED-only (link libc).
- Blade: `blade build/run/test/new/add/tree/update`; Saw.toml
  `[dependencies] name = { path = "..." }` or `{ git = "...",
  version = "1.2.3" }` (bare version = exact pin; no registry yet).

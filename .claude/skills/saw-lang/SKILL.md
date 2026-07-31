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
(String, Arc, escaping closures) = free refcount bump; `ExplicitCopy`
(Vector, Map, Set) = must `move v` or `v.copy()` at every transfer;
`NoCopy` (File, Mutex, Box) = `move` only.
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
}   // catch binds the box; "{error}" prints via vtable
if err.is<IoErr>() { if let io = err.take<IoErr>() { retry(io) } }  // downcast
```
- `trait Error: Printable {}` — conform via `extension E: Error {
  func format(&self, into: &var StringBuilder) {...} }`.
- Downcast an owned `Box<any Trait>` with `b.is<T>() -> Bool` (borrow) and
  `b.take<T>() -> T?` (CONSUMES the box — moves the payload out on a hit, drops
  it on a miss; use `is<T>()` first to branch). Explicit `T`, must conform.
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
- `TaskGroup(threads: N)` (design 75) opts into MULTI-THREADED execution (N OS
  workers drain a shared queue). `TaskGroup()` / `threads: 1` stay single-threaded
  (byte-identical, deterministic interleaving). Into a multi-threaded group,
  every value a spawned frame carries across a suspension — params, across-suspend
  locals, AND the result type — must be `Send` (else a clean compile error naming
  it; share via `Arc`/`Mutex`/`Channel`, not by moving a `Vector` etc. in). Test MT
  code on counts/sums, NEVER on interleaving. Cross-task cancel:
  `handle.cancel_addr() -> Int` (a Send address a canceller task sets).
- Thread engine (`spawn`/`Task`/`Channel.recv`) is separate from the
  cooperative TaskGroup engine — don't mix per task.
- Cooperative IO (design 76, std.net, hosted-only): a global kqueue/epoll reactor;
  the executor polls it when nothing runs (timeout = earliest sleep deadline,
  never busy-waits). Idiom = non-blocking `try_*` + `io_wait(fd, dir)` in the TASK
  body (`dir` 0=read, 1=write), a suspension point that registers+parks until the
  fd is ready: `while going { let r = tcp_try_read(fd,buf,n); if net_would_block(r)
  { io_wait(fd,0) } else { ...; going=false } }`. Setup: `tcp_listen`/
  `tcp_local_port`/`tcp_connect_start`+`tcp_connect_check`/`tcp_socketpair`/
  `tcp_close`/`net_buffer`. Cancellation-aware: check `cancelled()` BEFORE
  `io_wait`. MT groups: a frame can't hold a non-Send read buffer across a
  suspend, so MT io parks on write-readiness only. First-class suspending
  `tcp_read`/`accept`/`write` (no hand-written loop) is a future lift.
- `extern "C" { blocking func f(...) -> T }` marks an unbounded FFI call: it
  SUSPENDS (offloads to a hosted pool), is illegal in a `sync` context, and is
  rejected in the freestanding profile. An unannotated extern promises promptness.
  (Runtime offload pool is still pending — a blocking call inside a task body is
  currently rejected, not yet run.)
- Generic suspending functions/methods work (design 70 + 74): effect is
  re-inferred PER instantiation, so `f<A>` may suspend while `f<B>` is
  sync. You can `__drive` / `group.spawn` a generic instantiation, drive a
  generic `&var self` method, drive a suspending method on a generic STRUCT
  (`Holder<Int>`, design 74 shape 2), and make NESTED suspending generic
  calls from a driven body (design 74 shape 3). Still unsupported (clean,
  user-anchored compile error): a buried suspending METHOD call on a value
  inside a driven body — drive the method directly, or wrap it in a nested
  free function (shape 1); a nested suspending generic call to a template in
  ANOTHER module (shape 4); and a method that is BOTH struct-generic and
  method-generic.

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
- An escaping closure (bound/returned/stored/`spawn`) is **ImplicitCopy**
  over a refcounted heap env (like String/Arc): `let g = f` is a free
  refcount bump (both valid), and the captures are torn down exactly once
  when the last owner drops. Copying a struct/`Vector` that holds a
  closure retains the env; capture-less closures are trivially copyable.
  `move f` still transfers ownership. A closure also satisfies the generic
  `Copy` bound, so `Vector<() -> Int>` is copyable — `.copy()`/`.get()` each
  retain the element env exactly once (deinit-once through copy).
- `guard` must exit (return/break/continue/panic).
- A dependency name mapped via `--module-path` shadowing a local
  module file is an error.
- `Vector.get(i)` returns a COPY (needs copyable element); use
  `swap_out(i, v)` to move a slot out; `ref_at` for NoCopy access.
- String `chars()` yields Int scalars (no Char type).
- `to_int()`/`to_float()` are whole-string, no trimming → Optional.
- std.time/std.process/std.file/std.net are HOSTED-only (link libc).
- `UnsafePointer<T> + n` / `- n` / `[i]` are ELEMENT-STRIDE GEPs (the C
  convention: `UnsafePointer<Int32> + 1` advances 4 bytes). Use them for typed
  pointer math. `ptr as Int` (+ int math + `as UnsafePointer<T>`) DESTROYS
  provenance (blocks alias analysis) — reserve it for genuine address-as-number
  cases (slab free-list). For byte-granular offsets, cast to `UnsafePointer<Int8>`
  FIRST, then add.
- STYLE: no commented magic numbers — name them. Use a module-level `static`
  (`static AF_INET: Int32 = 2`, then `socket(AF_INET, ...)`) or a payload-free
  enum for a closed set. Static inits accept only plain literals (no casts/
  arithmetic); std-module statics are NOT visible cross-module yet.
- For a KNOWN C struct, declare a typed Saw struct (declaration-order natural ABI,
  design 58) as a stack local + `(&sa) as UnsafePointer<...>` for the syscall —
  never a raw byte blob; alignment comes free from the widest field. Only
  genuinely OS-divergent bytes need a compiler shim.
- Blade: `blade build/run/test/new/add/tree/update`; Saw.toml
  `[dependencies] name = { path = "..." }` or `{ git = "...",
  version = "1.2.3" }` (bare version = exact pin; no registry yet).

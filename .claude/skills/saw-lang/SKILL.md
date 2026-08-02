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
  suffixes `255u8`/`1_000i32` (exact-typed, range-checked). A bare
  (unsuffixed) literal adopts a fixed-width EXPECTED type wherever one
  is in force — annotation, param, field, return, default value,
  if/match arm, compound-assign RHS, array/tuple/Map/Set element — and
  is range-checked at the literal (`let b: UInt8 = 256` is a clean
  error). With no fixed-width expectation it stays platform `Int`
  (`let x = 5`); in a mixed binop it takes the other operand's width.
- Escapes: exactly `\\ \" \n \t \r \0 \u{1F600}` + `\{ \}` (brace forms);
  `\0` is an interior NUL that `len()` counts. Any other escape is a lex
  error (no silent drop). Strings are immutable UTF-8, refcounted.
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
- FAILABLE-RETURNS-RESULT (design 92, non-negotiable): a fallible op SURFACES
  its failure — `Result<T, IoError/…>` (caller must handle/`try`), or `T?` for an
  uninteresting/expected absence. NEVER a `Void` return that drops the error, and
  NEVER a sentinel that collides with a valid value (an empty `Data` must not mean
  BOTH EOF and error). A genuine boolean QUESTION (`exists`, `contains`) stays
  `Bool`. std follows this: `file.remove/rename`, `directory.create/remove/
  set_current`, `env.set/unset/set_cwd` → `Result<Void, IoError>`; net read/write/
  accept → Result (see the net section). `Result<Void, E>`: a bare `return` in
  such a function is `Ok(())`; `match r { case Ok(_) -> …, case Err(e) -> … }`.

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
- Cooperative net (design 84, std.net, hosted-only): use the SAFE OWNING TYPES —
  `TcpListener` and `TcpStream` (both NoCopy, `Deinit` closes the fd exactly once).
  NO raw fds, NO pointers, NO `io_wait` in your code — suspension is hidden INSIDE
  the methods (each parks on the global kqueue/epoll reactor internally):
  ```saw
  let listener = TcpListener.listen(0)!        // Result<TcpListener, IoError>
  let port = listener.local_port()
  let stream = try! listener.accept()          // Result<TcpStream, IoError>; suspends
  let chunk = try! stream.read()               // Result<Data, IoError>; Ok(EMPTY) = EOF
  try! stream.write("hi")                      // write(s: String) -> Result<Void, IoError>
  try! stream.write(move data)                 // write(bytes: Data); whole buffer, suspends
  let (a, b) = TcpStream.pair()                // connected pair, tests/IPC (no port)
  let s = try! TcpStream.connect("127.0.0.1", port)  // Result; suspends until connected
  ```
  DESIGN 92 — failable net calls RETURN the failure, never swallow it: `read`
  gives `Result<Data, IoError>` where an EMPTY Ok is EOF and an `Err` is a genuine
  error (DISTINCT — an empty Data no longer means both); `write(bytes: Data)`
  writes the WHOLE buffer and returns `Result<Void, IoError>` (it REPLACED the old
  Void `write_all`/`write_all_str` that hid a hard write error); `accept` returns
  `Result<TcpStream, IoError>`. Handle with `try`/`try!`/`match`. `write` is
  OVERLOADED — `write(s: String)` for text and `write(bytes: Data)` for binary;
  both suspend and both are drivable from a spawned worker (design 95 keys the two
  overloads' driven frames by resolved signature, so a worker may call BOTH back
  to back). `IoError: Error` (errno- shaped) — interpolate it (`"{e}"`).
  accept/read/connect are cancellation-
  observing at their internal park. The design-76 raw `tcp_*`/`net_*`/`io_wait`
  free functions are PRIVATE std internals — do not use them.
- A spawned worker that makes MULTIPLE parking net calls works — `read()`
  then `write()`, a read/write loop, or accumulating chunks across reads
  (`req.append(move chunk)`). Fixed by design 85 (fcntl variadic ABI) + design 86
  (`&var self` mutation on an opt-encoded frame-local across a suspend writes back
  to the real frame slot).
- **ONE ambient cooperative scheduler (design 89-b):** `spawn` enqueues a task
  into the current thread's shared run queue and it runs EAGERLY — whenever the
  executor runs, not only at `join`. So an infinite `accept`-loop server
  (`while true { let c = accept(); group.spawn(handle(c)) }`) serves its handlers
  while main is parked on accept — a live server WORKS. A TaskGroup is a
  lifetime/join SCOPE (its `Deinit` structured-joins its members at scope exit),
  not a separate executor; nested groups compose by construction; a task joining
  another yields to the one scheduler (no nested loop). Suspending calls yield
  IMPLICITLY when they park (a task doing I/O never needs `yield_now`); `yield_now`
  is only for a CPU loop that makes no parking calls. (⚠ Fairness: a task that
  never parks and never yields monopolizes the single-threaded scheduler — the
  op-count cooperative budget that bounds this is deferred, design 89-c.)
- A spawned task may CALL `TcpListener.accept()`, and a **multi-connection
  accept-LOOP** (one server task `accept`-looping to serve N connections
  sequentially, with N client tasks in the same joined group) now round-trips —
  design 90 fixed the reactor lost-wakeup. Each connection's read+write, fd-number
  reuse across connection turnover, and two readers parked on different fds all
  wake (`net_serve_two_connections`, `net_serve_three_connections`,
  `net_fd_reuse_across_connections`, `net_two_concurrent_parked_reads`). The
  reactor wakes PRECISELY the frame(s) registered for the `(fd, direction)` that
  became ready (design 91 — a readiness event carries the parked frame's wake-word
  as user-data), not the herd; a reader parked on one fd is never roused by
  another's event (`net_precise_wakeup`, `net_precise_n_readers`). Every parking op
  still re-checks its own fd and re-parks on a spurious wake, now purely
  belt-and-suspenders — you never see any of this, it is internal.
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
- A CLOSURE created in a driven body works (design 77 DF-C1): call it after a
  suspend, hold it across one (its env deinits exactly once at frame death), or
  own it in a spawned TaskGroup frame — captured frame locals are moved into the
  closure by value. A tuple local and `let (a, b) = f()` destructuring also
  survive a suspension (design 77): their bindings are frame-resident.
- **References may span a suspension (design 88, D6).** A `&T`/`&var T` param or
  a `&var self` receiver of a suspending function stays valid across a suspend —
  it becomes a frame-resident pointer into the referent, so a read after resume
  and a `&var` mutation both address the SAME caller value (mutation is
  caller-visible). The reference doesn't own → never dropped by the frame (deinit
  stays exactly-once). Held refs are for DRIVEN-in-place frames: a SPAWNED task
  may NOT take a reference PARAM (it would point into the dead spawner stack — a
  clean compile error, both group kinds; pass an owned value / `Arc` / `Channel`
  instead), but a reference to a task-LOCAL inside the spawned body is fine. Net
  (design 84) stays value-based: `read() -> Data`, `write_all(move data)` — a
  `&var Data` net read is not offered (an orthogonal nested-method-read depth
  limit blocks it, not the reference mechanism).

## Modules & packages
```saw
import std.net.{TcpListener, TcpStream}   // non-prelude std: import to use bare
import std.file                            // whole module (exposes File, ...)
import mymodule as mm       // aliasing; `module`/`public`/`package`/`parent`
```
- **Prelude (design 82) — what's bare vs what needs `import std.X`.** Bare
  (prelude): primitives, `Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/`Arc`/
  `Allocator`/`GlobalAllocator`, the Copy family + `Deinit`/`Iterator`/
  `Equatable`/`Comparable`/`Hashable`/`Printable`/`Error`/`Send`/`Sync`,
  `print`/`panic`/`assert`/`sizeof`/`alignof`/`static_assert`, `TaskGroup`/
  `yield_now`/`sleep`/`spawn`/`cancelled`, `StringBuilder`. IMPORT-REQUIRED:
  `File`/`Directory`/`Path` (std.file/directory/path), `Data` (std.data),
  `Channel` (std.channel), `Mutex` (std.mutex), `Duration`/`Instant` (std.time),
  `IoError`/`TcpListener`/`TcpStream` (std.net), `Utf8Error` (std.string),
  `Command` (std.process), `Env` (std.env). A bare non-prelude name is a clean
  error ("`X` is not in the prelude and must be imported") — add the import.
  A std import exposes names BARE (no `mod.Name` qualifier). Because a
  non-imported std module isn't compiled in, you may define your OWN `IoError`/
  `File`/etc. with no clash.
- Visibility: `public`, `public(package)`, `public(parent)`, private
  default. Package layout: `src/lib.saw` ← `import <pkgname>` (Blade
  `--module-path`); `src/main.saw` for binaries.
- MEMBER visibility (design 80): struct FIELDS and extension METHODS
  (incl. `init`/static) are **also private-by-default outside the defining
  module** — mark your API surface `public` (`public name: String`,
  `public func get(...)`, `public init(...)`). Same-module access is
  unrestricted. Gotchas: (1) a cross-module memberwise literal
  `T(a:, b:)` needs ALL fields visible — expose a `public init` when a
  field is private; reads AND writes are gated, so another module cannot
  corrupt a private field. (2) A method satisfying a visible trait's
  requirement is callable through the conformance with no `public` needed.
  (3) `public` on a member of a private struct is legal but inert. std is
  under the gate too — you reach its public API, never its internals; each std
  FILE is its own module (design 82), so std internals are private per-file.

## Systems/embedded corner
`static NAME: T = const_init` (Sync-only, immortal); `Atomic<Int>`;
allocator type params `Vector<T, A: Allocator = GlobalAllocator>`, `Box<T, A>`,
slab in std/slab.saw; `UnsafeMemory<T, Device|Normal>` for MMIO
(volatile, RO/WO markers); `@export("sym")`/`@section(".s")` on
top-level func/static (C ABI, whitelist: fixed-width ints, Int/UInt,
Float, UnsafePointer, Void/Never — no Bool/String/aggregates by
value); `static_assert(sizeof<T> == N, "msg")`; struct layout =
declaration-order natural ABI (documented rule). Unsafety is
TYPE-carried (Unsafe* prefix), not region-carried — no unsafe blocks.
**`unsafe` marker (design 81):** an expression prefix, required where a raw
pointer flows INVISIBLY in a function whose signature carries no `Unsafe*`
type — a deref/index read or write (`unsafe ptr[i]`, `unsafe ptr[i] = v`),
pointer arithmetic (`unsafe base + n`), or binding a pointer produced by a
call (`let p = unsafe A().alloc(s, a)`). NOT needed where visible: a cast that
names `UnsafePointer<T>` (and any op inside it), a pointer param/return/field,
a passed-through pointer. Free inside the MARKED DOMAIN: a fn whose signature
carries a raw pointer, OR a `self`-method of a struct with a pointer field
(so container access methods need no marker; a no-`self` factory like
`Box.make` does). `unsafe` on nothing-unsafe = error. Precedence: below
assignment, looser than every operator (`unsafe p[0] = 5` marks the store).
For scoped no-copy element access use `Vector.with_ref`/`with_var_ref` (a
non-escaping `&T`/`&var T` borrow, invalidation-proof) — this REPLACED `ref_at`.

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
  `swap_out(i, v)` to move a slot out; `with_ref`/`with_var_ref(i, body)`
  for scoped in-place (NoCopy) access (design 81; `ref_at` was removed).
- String `chars()` yields Int scalars (no Char type).
- `to_int()`/`to_float()` are whole-string, no trimming → Optional.
- std.time/std.process/std.file/std.net are HOSTED-only (link libc).
  `Command(program:).arg(..).run() -> Result<Int32, ProcessError>`: Ok(code) =
  launched + exited (signal death = 128+signum, never a bogus 0); Err = could not
  launch (executable not found / shell exit 127). `ProcessError: Error` names the
  program. `.output() -> CommandOutput?` still captures stdout.
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

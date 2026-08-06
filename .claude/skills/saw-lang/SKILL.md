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
extension Msg { func is_quit(&self) -> Bool { match self { case Quit -> true,
                                                           case _ -> false } } }
type UserId = Int          // DISTINCT type; flows TO Int; back via UserId(i)
let raw = id as Int        // explicit projection toward underlying
print("hi {name}: {p}")    // interpolation; user types need Printable
print("{#file}:{#line} - msg")  // #file/#line/#function: definition-site consts
```
- `#file`/`#line`/`#function` (design 98) are compile-time magic literals
  expanding at their DEFINITION site (zero runtime cost): `#file` → source
  basename (`String`, matches the panic prefix), `#line` → 1-based token line
  (`Int`), `#function` → enclosing function/method BARE name (`String`; no
  struct qualifier; module scope → `<module>`). The debug-print idiom is
  `print("{#file}:{#line} - msg")`. Usable in any expression/interpolation,
  a default value, or a `static` init (`#line`). In a generic they report the
  generic's own file/line identically across instantiations; inside a suspending
  body they report the ORIGINAL source line/name (not the coroutine frame's).
  `#` takes only these three — any other `#name` is a lex error.
- Everything is an expression (if/match/while/blocks yield values;
  `break v` from an infinite `while {}` yields `T` directly — must break;
  from a conditional while/for it yields `T?`).
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
- Line breaks (design 129): a statement ends at end-of-line, but a newline
  between `(`/`)`, `[`/`]`, or inside a COMMITTED generic `<...>` is
  insignificant — so argument lists, parameter lists, tuples, collection
  literals, index expressions and generic lists all WRAP. A trailing comma is
  allowed in the `(...)`/`[...]` forms (`f(\n a,\n b,\n)`) and rejected in
  `<...>` ("a trailing comma is not allowed in a generic argument list"). `{}`
  stays newline-SIGNIFICANT (a block/closure is a statement container), which
  holds even for a closure argument inside a wrapped call — so a multi-statement
  closure body still works there. The ONE brace pair that DOES wrap is an
  import's symbol list (`import kcore.{\n  a, b,\n}` — design 147): it is a
  delimited list, not a statement container, and takes a trailing comma too.
  A newline AFTER the closing bracket still ends
  the statement. `a < b` stays a comparison whether or not it straddles lines;
  suppression needs the parser to have committed to the generic reading. An
  unclosed `(`/`[` is reported AT THE OPENER, not at EOF. Wrap a long signature
  or call rather than hoisting extra bindings just to fit a line.
- Doc comments (design 121): `///` documents the declaration that FOLLOWS it
  (top-level func/struct/enum/trait/extension/type/static, struct fields, enum
  cases, extension methods + inits, trait methods); a run of `///` lines is one
  block, and a `public` modifier or `@attribute` line in between is fine. `//!`
  documents the FILE and is legal only ahead of every declaration. Only a
  line-leading comment counts — `////` (4+) and a `///` trailing code stay
  ordinary. One space after the marker is stripped; body text is opaque
  (Markdown by convention). A block that documents nothing is a clean error
  ("doc comment is not followed by a documentable declaration"), never a silent
  drop. `sawc <entry> --emit-docs` emits the whole surface as JSON (signatures,
  suspending-vs-sync effect, self borrows/consumes, conformances) for the entry
  module plus every module it imports; write user-facing doc text per the
  saw-docs skill.
- Shadowing (design 100/107): a `let`/`var`/`for`-var that shadows an ENCLOSING
  binding (an outer local/param/capture/loop-var or a module `static`) is a
  compile ERROR unless its initializer MENTIONS the shadowed name —
  `let data = parse(move data)`, `let n = n + 1`, `if let x = x`,
  `for x in x.lines()` are OK (derived / scrutinee / sequence references it); a
  non-deriving `let x = compute()` / `for x in ys` under an outer `x` is rejected.
  The SAME rule now covers same-scope redefinition (design 107):
  `var data = read(); let data = parse(move data)` in ONE scope is legal (the new
  binding REPLACES the old, its own mutability; a `.copy()`-derived old value
  drops AT the redefinition point); a non-deriving same-scope `let data = fresh()`
  stays the "already defined" error. No-initializer shadows are flat errors: a
  `match`/`if let`/`guard let` PATTERN binding (`case Move(x, y)` under outer `x`
  — patterns BIND, not compare), a fn param vs a module `static`, a closure param
  vs an enclosing local. (A `for` loop binds a single name — no tuple pattern in
  the header.) Prelude/std names are not bindings for this rule.

## Ownership (the part that bites)
Copy tiers: trivial/POD = implicit bitwise copy; `ImplicitCopy`
(String, Arc, escaping closures) = free refcount bump; `ExplicitCopy`
(Vector, conformance bounded `T: Copy`) = must `move v` or `v.copy()` at every
transfer; `NoCopy` (File, Mutex, Box — and currently Map/Set: their
`ExplicitCopy` is future work, `.copy()` on them is a compile error) = `move` only.
**A struct that OWNS one of those must pick its own copy policy** — the #1 thing
you hit writing Saw. `struct Holder { v: Vector<Int> }` does not compile bare;
the compiler knows how to DESTROY it but not whether you want it duplicated:
```saw
extension Holder: NoCopy {}                     // move-only (usually what you want)
@synthesize
extension Holder: ExplicitCopy {}               // memberwise deep .copy()
```
Both bodies are EMPTY — the `deinit` is synthesized either way. Only the copy
policy is your call. (A `String`/closure field is compiler-handled and forces
nothing, and so is an enum whose payloads are only trivial/ImplicitCopy.)
**ENUMS PICK A POLICY TOO** (design 139) — an enum carrying an ExplicitCopy or
NoCopy payload declares one exactly as a struct with such a field does; a bare
one is the same error. Same two spellings, same empty bodies:
```saw
enum Reel { case Loaded(t: Tape), case Empty }   // Tape is NoCopy
extension Reel: NoCopy {}
@synthesize
extension Bag: ExplicitCopy {}   // payload-deep copy() over the ACTIVE variant
```
**WRAPPERS CARRY THE TIER OF WHAT THEY WRAP** (design 139). Every type has
exactly one transfer class, and a composite is never weaker than its parts: an
`Optional<T>`, a tuple, a `[T; N]`, an enum payload and a `Result<T, E>` all take
the strongest tier they hold. So `Vector<Int>?` needs `move`/`.copy()`, `File?`
is move-only, `Int?` stays trivial — and a struct with a `File?` FIELD must
declare `NoCopy` (the containment cascade). `.copy()` on an optional exists
exactly when the payload's tier provides one (`None`→`None`, `Some`→`Some` of the
payload's copy): a `String?` retains, a `Vector<Int>?` duplicates the buffer, a
`File?` has none. A refused optional transfer names THREE ways out —
`o.copy()`, `move o`, `o.take()`; `take()` is the one that works on a FIELD,
where `move` would be the no-partial-moves error.
**`Deinit` is NOT declarable** (design 131): `extension T: Deinit {...}` is a
compile error naming the three policies. A hand-written `deinit` body goes
INSIDE the policy conformance (`extension Res: NoCopy { func deinit(&var self)
{...} }`) — the requirement is inherited, so that is the only spelling. A type
declaring just `Deinit` had a destructor and no transfer rule, so `let s = r`
silently aliased it and both halves ran deinit. `T: Deinit` as a generic BOUND
is still fine.
```saw
var w = move v         // v now invalid (use-after-move = compile error)
var u = w.copy()       // explicit duplicate
```
- `move` works on ANY type and retires the binding; a moved `var`
  revives on reassignment.
- NO partial moves (`move p.x` is an error) — move whole bindings.
- References `&T`/`&var T` are PARAMETER-ONLY, cannot escape/be
  stored. Call sites mirror the sigil: `f(&x)` / `f(&var x)` (and `x`
  must be `var`). Mutate through `&var` via compound assignment, methods, or
  whole-referent REPLACEMENT `x = v` (design 110 — uniform across functions,
  `&var self` methods via `self = v`, and closures; matches Swift `inout`).
  `x = v` is legal exactly when `v` type-checks as `var x: T = v`: the RHS takes
  the ordinary transfer checkpoint (fresh temp needs nothing, ImplicitCopy copies,
  ExplicitCopy/NoCopy need `move v`/`.copy()` — the `move` consumes the CALLEE's
  local); the old referent deinits once and the new value installs, caller's
  binding stays valid. STILL banned: `x = v` through an immutable `&T`
  (read-only); `move` OUT of a ref. EXCLUDED: a `&var any Trait` ERASED referent
  (the slot's concrete type is unknown — specific error points at Box) — but a
  `&var Box<any Shape>` referent IS sized, so `b = Box<any Shape>.make(Square(..))`
  swaps the payload. Generic `&var T` works per instantiation (the RHS must BE a
  `T`). A bare trait name behind a ref (`&Shape`/`&var Shape`) is unsized — write
  `&any Shape`/`&var any Shape`.
- Law of Exclusivity: one `&var` XOR many `&` to overlapping paths,
  statically checked.
- Forwarding (design 106): a received reference param (or `&var self`) may
  itself be the operand of `&`/`&var` — pass it onward as a re-borrow:
  `func relay(r: &var T) { g(&var r) }`, `g(&var self.field)`, `g(&var self)`.
  Sigils still mirror; `&var` forwarding needs an INCOMING `&var` (a `&` can't
  upgrade to `&var` — clean error), a `&var` may forward as `&` (downgrade OK).
  Composes to any depth and across a suspend (the frame-resident pointer is
  forwarded — a twice-forwarded `&var` mutation is visible at the root);
  exclusivity is by root path (`g(&var r, &r)` in one call is rejected). This
  is what lets `net.read_into` forward its `&var Data` to a helper.
- **PLACES: `borrows` / `lend` (design 141/146).** A `borrows` method hands out
  STORAGE instead of a value — the element/field stays where it is and the
  caller reads or writes it there. `borrows` rides the effect slot
  (`unsafe sync borrows`); `[]` is a declarable method name, so a `borrows []`
  is the subscript; any named method may be `borrows` too.
  ```saw
  extension Grid {
      public func [](&self, i: Int) borrows -> Cell {
          if i < 0 || i >= 9 { panic("Grid.[]: index out of range") }
          lend self.cells[i]              // window opens here
          self.reads = self.reads + 1     // EPILOGUE (needs `&var self`)
      }
  }
  g[4].weight += 1                        // writes the element in place
  ```
  **`lend` is a SUSPENSION, not a return.** The accessor runs to its `lend`,
  PAUSES with its frame alive, the caller's window code runs inside that pause,
  and the epilogue runs on resume. `-> T` names the type of the PLACE, so
  `return <value>` in a borrows body is a clean error. Every path lends EXACTLY
  once or diverges first (`panic` before the lend is the bounds-check shape);
  `lend` inside a loop is rejected (lend once, after the loop picks the place).
  **The USE SITE picks the flavor**: a read opens a shared window, a write or a
  `&var` argument opens an exclusive one, out of ONE declaration. Window extent
  = the smallest expression that turns the place back into a value; windows
  NEST (`b[0][1].n += 1` is two, epilogues LIFO). A place borrow charges its
  ROOT, so `v.push(x)` inside a window is a compile error (invalidation-proof
  by the Law of Exclusivity, not by a closure scope) and so is swapping two
  elements through two windows (`v.swap(i, j)` is the method for that).
  **`borrows -> T?` is the CONDITIONAL lend**: each path either `lend`s or
  plainly `return None`. The absent path opens NO window and runs NO epilogue —
  `if let x = d.at(i)` sees `None`, and `d.at(i)!.m()` panics (the `!` is the
  promise the window keeps). `lend` may not be in a LOOP, so a body that has to
  SEARCH splits in two: a plain function finds the index, the accessor lends it
  (`libs/toml`'s `_section_index` beside `section`). VALUE READS out of a place
  follow design 131's table: retain for ImplicitCopy, clean error for
  ExplicitCopy/NoCopy naming `with_ref` / `swap_out`. v1 fences: a borrows body
  is `sync` (a window never spans a suspend — `with_ref`/`with_var_ref` stay the
  long-window spelling), no borrows function VALUES or existentials, no trait
  requirements, and no place projection into an ENUM PAYLOAD (which is why `Map`
  has no subscript).
- Deterministic LIFO destruction (`Deinit` trait); never call
  `deinit()` manually. You almost never WRITE one either (design 128): any
  struct/enum owning something gets a memberwise `deinit` synthesized — fields
  dropped in reverse declaration order, enums dropping the active variant's
  payload — with no declaration needed. Hand-write `deinit(&var self)` only for
  a raw resource (an fd, a mapping); your body runs FIRST and the field drops
  are appended, and there is only ever one deinit per type. Corollary: an empty
  `func deinit(&var self) {}` is dead code — delete it.
- `let _ = expr` = true discard (consumes + drops immediately).

## Collections & literals
```saw
let v: Vector<Int> = [1, 2, 3]      // [..] is a fixed array unless
                                    // the expected type is Vector
let m = {"a": 1, "b": 2}            // Map<String,Int> (hash; unordered)
let s = {1, 2, 3}                   // Set<Int>
let e: Map<String,Int> = {:}        // empty map needs annotation
// {} and {expr} are ALWAYS closures — use Set<T>() / Set.of(x)
var scratch: [Int8; 256] = [0; 256] // REPEAT literal: N copies of one value
```
- **`[v; N]` is the repeat literal (design 148)** — the way to spell a zero
  stack buffer. `N` is a compile-time constant (literal, const arithmetic, or a
  const generic param); the value expression runs EXACTLY ONCE and is copied
  into every slot. `[0; 4096]` lowers to one zeroinitializer store (a memset);
  anything else splat-loops. Elements must copy for FREE — trivial or
  ImplicitCopy — since there is nowhere to write the `.copy()` an ExplicitCopy
  value needs (`[v; 3]` on a `Vector<Int>` is a clean error naming the policy),
  and a generic `[t; N]` is refused for the same reason (no bound yet says
  "copies for free"). Statics take one: `static BUF: [Int8; 4096] = [0; 4096]`
  lands in .bss. LENGTH IS PART OF THE TYPE — `[Int; 3]` is not a `[Int; 5]`.
- No bare block statement (design 122): a closure literal alone in statement
  position is a compile error ("never called") — call it `{ ... }()` or bind it.
  Narrow a lifetime by extracting a function.
- `let n = <Void expr>` is a type error (bind nothing, or `let _ = ...`), and a
  top-level `func`/`extern` named after a built-in (`print`/`assert`/`sleep`/
  `spawn`/`sizeof`/…) is a duplicate-definition error — the call site always
  resolves to the built-in, so the declaration could never run.
  The Void rule is SYNTACTIC (design 132): a Void you can SEE errors, a Void
  that arrives by INSTANTIATION does not. `let r = body(x)` inside a
  `func f<R>(...) -> R` compiles at every `R`, `Void` included — it becomes a
  zero-sized binding (no storage; reading the name yields no value), so a
  generic body that type-checks compiles for every instantiation and you never
  get an error at a distance. Same as a unit type in Rust/Swift.
- Map/Set keys: `Hashable + Equatable` and copyable-with-retain
  (NoCopy keys rejected). A payload-free enum qualifies — it is a bare
  tag, so `Set<Color>` and `Map<Color, Int>` both work (design 132).
  Values unrestricted. Iteration order
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
- **An error type may be an ENUM, and usually should be** (design 145). A closed
  set of failures is what an enum is for, and enums carry methods and
  hand-written trait bodies now — so the old workaround of making every error a
  struct is retired:
  ```saw
  enum SysError { case Ok, case BadHandle, case Other }
  extension SysError {
      func describe(&self) -> String {
          match self { case Ok -> "ok", case BadHandle -> "bad handle",
                       case Other -> "other" }
      }
  }
  extension SysError: Printable {
      func format(&self, into: &var StringBuilder) { into.append(self.describe()) }
  }
  extension SysError: Error {}
  ```
  Reach for a struct when a failure carries per-case DATA that does not fit a
  payload, or when you want field-by-field construction.
- Downcast an owned `Box<any Trait>` with `b.is<T>() -> Bool` (borrow) and
  `b.take<T>() -> T?` (CONSUMES the box — moves the payload out on a hit, drops
  it on a miss; use `is<T>()` first to branch). Explicit `T`, must conform.
- Optionals: `T?`, `None`, force `!` (panics), `??`, call-site auto-wrap
  (`f(5)` matches `f(x: Int?)`), and full **optional chaining** `?.` (design 111):
  `a?.b?.c()` any length, `?.field`/`?.method()`, call-result heads
  (`x.a()?.b`); each optional hop needs its own `?`, a plain intermediate uses
  `.`; the first None short-circuits the WHOLE tail INCLUDING skipped-call args
  (side effects don't run); result is `U?`, flattened (never `U??`). A final FIELD
  projection copies → must be copyable (move-only field rejected — end in a method
  instead); a final method result is unrestricted. Composes with `??`/`if let`/
  `guard let`/`!`. Chained ASSIGNMENT `x?.y = v` writes the payload field in place
  iff every hop is non-None (RHS skipped on short-circuit, ordinary transfer rules
  — `move`/`.copy()` for ExplicitCopy/NoCopy); it types `Void?` (discard in
  statement position; consume "did it write" via `guard let _ = x?.y = v else {}`
  — `_` is blessed as an `if let`/`guard let` pattern that binds nothing + drops
  the payload). A SUSPENDING hop works (design 120): `o?.read()` runs the hop only
  when every earlier hop is non-None, a multi-hop chain peels one hop at a time,
  and a chained assignment with a suspending RHS writes only on the non-None path.
  Still rejected: a chained assignment through MORE THAN ONE hop whose RHS suspends
  (`a?.b?.c = s.read()` — `if let` the inner optional first). `?.` indexing is
  unsupported.
- **PAYLOAD READS ARE PLACES (design 131).** `o!`, the `??` left operand, and an
  `if let`/`guard let` binding all name storage the optional still owns, so the
  payload's copy tier decides the read — same table as everywhere else. BORROW
  (`o!.m()`, `&o!`, `o!.field`, a `?.` hop) is always free. A VALUE READ
  (`let a = o!`, a by-value arg, a return, an operand) is bitwise for trivial,
  a RETAIN for ImplicitCopy (the optional keeps its own reference — so
  `var o: String? = "v"; let a = o!; o = None; print(a)` prints `v`), and a
  clean ERROR for ExplicitCopy/NoCopy naming the consuming spellings. `a ?? b`
  yields an owned value, so both arms follow the value-read row. Two consuming
  forms:
  - **`move o!`** — compile-time, zero cost, retires the WHOLE binding (no husk,
    no partial move); still panics if dynamically None. LOCALS ONLY —
    `move h.field!` is the no-partial-moves error.
  - **`o.take()`** — `Optional.take(&var self) -> T?`. Writes `None` into the
    place and returns the payload owned, so it works on a FIELD (the move-out
    `move` can't do). Needs a mutable place, exclusivity-checked like any
    `&var self` method. Checked spelling `o.take()!`.
  `if let a = move o` is the consuming binding. A WHOLE-optional read follows the
  same table since design 139 — the optional's tier IS its payload's, so
  `let y = x` retains a `String?` and is REFUSED on a `Vector<Int>?`/`File?`
  (`x.copy()` / `move x` / `x.take()`). A payload read out of a CALL RESULT
  (`v.get(0)!`, `if let x = f()`) is unaffected — that value is already yours.
- `panic(msg) -> Never`; `assert(cond, msg)`. Overflow/bounds/shift/div-zero
  violations panic ALWAYS (wrap intentionally with `&+ &- &*`). EVERY panic —
  the compiler-raised traps included — prints `panic at FILE:LINE: {reason}`,
  where LINE is the trapping expression's own line (a closure body reports its
  own line, not the enclosing function's), in both profiles. The message is
  assembled in STACK scratch (design 137), so it survives an exhausted allocator
  — which is the point, since a refused `Vector.push` panics. 508 bytes of
  message; a longer one is cut and marked `…`.
- **FORMAT ARGUMENTS (design 137) — `{}` placeholders, the alloc-free spelling.**
  `print`/`panic`/`assert` take a LITERAL format string with `{}` slots plus one
  value each: `print("x = {}", x)`, `panic("out of {}: wanted {}", "frames", 64)`,
  `assert(a == b, "want {} got {}", a, b)`. Monomorphized generics, not varargs —
  slot count vs argument count is a COMPILE error (`print("{} and {}", 1)` →
  "format string has 2 placeholders but 1 argument was given"), the format string
  must be a literal, and mixing `{name}` interpolation with `{}` in one format
  string is rejected. `\{`/`\}` stay literal braces.
  ```saw
  print("x = {x}")     // builds a heap String, then writes it
  print("x = {}", x)   // writes the pieces; allocates NOTHING
  ```
  Same bytes; the second works freestanding and under total allocator denial.
  Reach for it in a kernel, a panic path, or anywhere `--no-hidden-alloc` is in
  force (below). `print`
  has no line-length limit (each piece goes to the seam at its own length); only
  a single user-`Printable` rendering is bounded (512 bytes, marked).
- **`--no-hidden-alloc` (design 135) — the guarantee, as a flag.** Per
  invocation; rejects allocations the COMPILER inserts that no source construct
  names. THREE sites error: (1) string interpolation `"{x}"` ANYWHERE, with NO
  carve-out for a `panic`/`assert` message argument (the allocator being out is
  exactly when a panic has to work — write `panic("out of {}", what)`);
  (2) an ESCAPING closure that CAPTURES something (bound to a `let`/`var`,
  returned, stored — its env is a refcounted heap block; a closure passed
  straight to the call that runs it keeps a STACK env and is fine, and so is an
  escaping closure with no captures); (3) single-argument `print(user_printable)`,
  which renders through a synthesized `to_string()` — `print("{}", p)` streams
  the same bytes into stack scratch. Everything the SOURCE names is untouched:
  `Vector.push`, a collection literal, `Box.make`, `spawn` (env included), a
  written `Box<any Error>` and its erased-error auto-wrap, an ImplicitCopy
  transfer. Orthogonal to `--freestanding` (a slab-backed kernel may want real
  `String`s) and combines with it — the SOS kernel gate builds under both. Full
  site-by-site table: LANGUAGE_SPEC "No hidden allocations".
- **`StringBuilder` FIXED mode (design 137)** — `StringBuilder(bytes:capacity:)`
  over caller storage. Never grows, never frees; overflow cuts on a UTF-8
  boundary and stamps `…`, and `is_truncated()` reports it (until `clear()`).
  Holds `capacity - 4` bytes of text (marker + NUL); capacity < 5 panics. This is
  what `print`/`panic` hand to your `format`, so **write `format` out of `append`
  calls, not `"{...}"` interpolation** — the latter builds a heap String and is
  what makes a type un-printable on the alloc-free path. `append(value: Int)` and
  `append(value: UInt)` render digits directly (no intermediate String), and
  forwarding to a field's own `format` (`self.n.format(into: &var into)`) is
  alloc-free too since design 135 — either spelling is safe in a body. In fixed
  mode `try_append`/`try_append_char` never return `Err`: nothing refused them,
  and truncation is reported by the marker, not by a fake `AllocError`.
- FAILABLE-RETURNS-RESULT (design 92, non-negotiable): a fallible op SURFACES
  its failure — `Result<T, IoError/…>` (caller must handle/`try`), or `T?` for an
  uninteresting/expected absence. NEVER a `Void` return that drops the error, and
  NEVER a sentinel that collides with a valid value (an empty `Data` must not mean
  BOTH EOF and error). A genuine boolean QUESTION (`exists`, `contains`) stays
  `Bool`. std follows this: `file.remove/rename`, `directory.create/remove/
  set_current`, `env.set/unset/set_cwd` → `Result<Void, IoError>`; net read/write/
  accept → Result (see the net section). `Result<Void, E>`: a bare `return` in
  such a function is `Ok(())`; `match r { case Ok(_) -> …, case Err(e) -> … }`.
  Design 132 finished the sweep in std.file/std.directory — the whole opening
  and reading surface carries its cause now: `File.open`/`create`/`open_append`
  → `Result<File, IoError>`, `File.read` → `Result<Data, IoError>` (an empty Ok
  means the file had nothing left, distinct from a failure), `File.write` →
  `Result<Int, IoError>` (bytes written), `File.seek_*`/`position` →
  `Result<Int, IoError>`, `Directory.list` → `Result<Vector<Path>, IoError>`.
  There is no `if let` over a Result, so bind them with `match`/`try`:
  ```saw
  var f = try File.open(p)            // in a Result-returning function
  let text = match f.read() {
      case Ok(bytes) -> move bytes,
      case Err(e) -> { return "" }    // a `return` arm needs its own block
  }
  ```
  `Directory.current` stays `Path?` — `None` means getcwd(2) failed, and since
  design 132 a long path is returned whole rather than becoming that `None`.

## Traits & generics
```saw
trait Shape { func area(&self) -> Int
              func describe(&self) -> String { "area {self.area()}" } }
extension Circle: Shape { func area(&self) -> Int { ... } }  // default inherited
func show(s: &any Shape) { print(s.area()) }   // dynamic dispatch
var boxed: Box<any Shape> = Box<any Shape>.make(c)  // owned existential
func biggest<T: Shape + Comparable>(v: &Vector<T>) -> ...
v.map({ $0.to_string() })           // type args INFERRED (design 93): U from
v.map<String>({ $0.to_string() })   // the closure's return; explicit still wins
```
- `any` only behind `&`, `&var`, or `Box` (unsized otherwise).
- **Generic type-arg inference (design 93 + 105):** a generic free function or
  method may omit its `<...>` — argument types (and a closure's inferred RETURN
  type) solve them (`wrap(5)`, `first(7,"hi")`, `v.map({...})`, `v.fold(0){...}`).
  Explicit `<...>` always allowed + wins; a partial explicit prefix pins the
  leading params, the rest infer; a defaulted trailing param fills unconstrained.
  Failures are clean errors (underdetermined / conflicting), and an inferred arg
  is bound-checked. A default VALUE typed by a type param (`func f<T>(a: Int,
  b: T = 0)`, design 108) is checked against the INSTANTIATED `T` per call, and
  when `T` is otherwise undetermined the default DRIVES inference — `f(1)` infers
  `T = Int` from `b: T = 0` (a supplied arg wins). A default that can't fit the
  instantiation (`f<Float>(1)` — a bare `0` doesn't adopt `Float`) or that infers
  a bound-violating type is a clean call-anchored error (never an ICE). Design 105
  extended the boundary:
  - **Overload sets** now infer: inference runs PER CANDIDATE, and if EXACTLY ONE
    generic overload both solves and type-matches it is picked. Concrete overloads
    still win (design 55 exact-match). Two+ that solve is a clean AMBIGUITY error
    listing the candidates + their solved type args (`give explicit type arguments
    or labels`) — never a silent pick. So a generic fallback alongside concrete
    specializations, or two generic overloads distinguished by container shape
    (`f(Wrap<T>)` vs `f(Vector<T>)`) or by LABEL, all infer.
  - **Later-arg solve**: a parameter determined by an argument to its RIGHT is now
    solved (fixpoint over the arg list), including a closure that appears BEFORE
    the value that fixes its `T` (`run({ $0*2 }, 10)`).
  - **Labeled calls** map arguments to parameters by LABEL before unifying.
  - Driven/spawned inferred generics (incl. a suspending generic OVERLOAD)
    monomorphize per resolved candidate, just like explicit ones.
  Still explicit: two generic overloads of one name that BOTH solve at a call
  (ambiguous — give `<...>`); a driven/spawned generic METHOD overload (only free
  functions carry the per-overload codegen symbol) — drive it directly at an
  explicit instantiation if needed.
- **`@synthesize` (design 128) — a WRITTEN empty conformance derives its body
  only under the marker**; a bare one is a compile error. Applies to
  ImplicitCopy/ExplicitCopy (`copy`), Equatable (`equals`), Comparable
  (`compare`), Hashable (`hash`), structs and enums alike:
  ```saw
  @synthesize
  extension Point: Equatable {}     // memberwise; payload-deep for an enum
  @synthesize
  extension Point: Comparable {}    // lexicographic, declaration order
  ```
  AUTO-conformance is UNTOUCHED and needs neither marker nor declaration:
  trivial (POD) structs + payload-free enums are already Equatable/Hashable, and
  primitives/String conform builtin. So the marker appears only where you wrote
  `extension T: Trait` yourself. A marker that derives nothing (a hand-written
  body already there, or a trait with no derivation like Printable) is an error,
  as is a derivation blocked by a member — it names the field.
  Comparable requires Equatable (no auto, so EVERY Comparable conformance is
  written and every derived one is marked). Hashable mirrors Equatable.
  Printable: hand-written `format` (no synthesis).
- Overloads resolve by EXACT types (no conversions), labels
  disambiguate same-type sets (`f(0, value: 4)`). Between platform `Int` and
  `UInt` the EXACT one wins (design 137), so `f(Int)`/`f(UInt)` twins are
  writable — `StringBuilder.append` needs both. A bare literal's WIDTH stays
  flexible, so `h(Int)` vs `h(Int8)` called `h(5)` is still ambiguous (write
  `h(5i8)`).
- **CONST GENERICS: a parameter that carries a VALUE (design 148).** `const` in
  the parameter position is what keeps it visually distinct from a bounded type
  param — and `<N: Int>`, the natural guess, is now a clean error pointing at
  the real spelling:
  ```saw
  struct FixedBuf<const N: Int> { data: [UInt8; N] }
  extension FixedBuf<N> {                    // constness comes from the
      init() -> FixedBuf<N> {                // declaration; don't repeat it
          FixedBuf<N>(data: [0; N])
      }
      func capacity(&self) -> Int { N }      // N is an Int here, free at runtime
  }
  var small = FixedBuf<16>()                 // different TYPE from FixedBuf<256>
  ```
  The value is part of the type identity and the monomorphization key, so
  `FixedBuf<16>` and `FixedBuf<256>` are two types with two layouts and neither
  flows into the other. v1 scope: `Int`/`UInt` values only; usable as a `[T; N]`
  length, a `static_assert` operand, a `sizeof` operand, a repeat count, or a
  plain Int; const ARITHMETIC in instantiation position (`FixedBuf<2 * 128>` IS
  `FixedBuf<256>` — folded before mangling); defaults compose with design 37
  (`<const N: Int = 4>`, so `Ring()` means `Ring<4>`); structs, enums and free
  functions all take them. Explicit at the use site except for ONE inference
  case — a `[T; N]` PARAMETER binds N from the argument's length:
  ```saw
  func width<const N: Int>(xs: [Int; N]) -> Int { N }
  print(width([1, 2, 3, 4]))    // 4
  ```
  Wrong-kind arguments are clean errors naming the parameter (`FixedBuf<Int>` →
  "takes a VALUE"; `Pair<4>` → "takes a TYPE"). NOT in v1: const params of user
  types, `where N > 0` (use `static_assert(N > 0, ...)` in the body), variadics.
- **The fixed-buffer idiom (std.fixedbuf).** For formatting or scratch bytes
  with no allocator, reach for the std types rather than rolling a buffer:
  ```saw
  import std.fixedbuf
  var out = FixedStringBuilder<64>()   // 64 bytes inline; holds 60 of text
  out.append("n = ")
  out.append(42)
  print(out.as_string())               // prints: n = 42
  ```
  `FixedStringBuilder<N>` is `StringBuilder`'s fixed mode with the storage
  question answered — same `append` surface, same cut-and-mark-with-`…`
  truncation (`is_truncated()` reports it), nothing allocated. `FixedBuf<N>` is
  the raw buffer under it (`capacity()`, bounds-checked `get`/`set`, and `ptr()`
  for unsafe paths). Taking an address needs `&var self`: a `&self` receiver
  arrives BY VALUE, so a pointer built inside such a method addresses the
  callee's copy.

## Concurrency (colorless)
```saw
import std.task                                   // design 114: `yield_now` lives here
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
  let listener = try! TcpListener.listen(0)    // Result<TcpListener, IoError>
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
  accept/read/read_into/write/connect all OBSERVE cooperative cancellation at their
  internal park — including a task ALREADY parked on a permanently-idle fd (design
  102 item 2): a peer's `handle.cancel()` or a `cancel_addr` write rouses the parked
  task (the reactor has a self-wake pipe, and the scheduler wakes a parked frame it
  finds cancelled), it re-checks `cancelled()` at its loop top and returns
  `Err(IoError)` — so a cancelled idle-fd wait no longer hangs. A NON-cancelled
  sibling parked on another idle fd stays parked (precise, no herd wake). The
  design-76 raw `tcp_*`/`net_*`/`io_wait` free functions are PRIVATE std internals —
  do not use them.
- A spawned worker that makes MULTIPLE parking net calls works — `read()`
  then `write()`, a read/write loop, or accumulating chunks across reads
  (`req.append(move chunk)`). Fixed by design 85 (fcntl variadic ABI) + design 86
  (`&var self` mutation on an opt-encoded frame-local across a suspend writes back
  to the real frame slot).
- A suspending reactor method (`stream.read()`, etc.) drives correctly at ANY
  NESTING DEPTH below a spawned/driven root — a worker may call a free fn that
  calls a free fn that calls `stream.read()` (2, 3, … frames deep), including a
  `match stream.read() { … }` where the call is the scrutinee (design 96 closed
  the depth-2+ hang: a callee whose only suspension source was a nested std method
  was miscompiled as a blocking call that wedged the thread).
- **ONE ambient cooperative scheduler (design 89-b):** `spawn` enqueues a task
  into the current thread's shared run queue and it runs EAGERLY — whenever the
  executor runs, not only at `join`. So an infinite `accept`-loop server
  (`while true { let c = accept(); group.spawn(handle(c)) }`) serves its handlers
  while main is parked on accept — a live server WORKS. A TaskGroup is a
  lifetime/join SCOPE (its `Deinit` structured-joins its members at scope exit),
  not a separate executor; nested groups compose by construction; a task joining
  another yields to the one scheduler (no nested loop). **Scope, not extender
  (design 124):** a task's owned values deinit when THE TASK completes, not at
  group teardown — a handler's `TcpStream` closes its fd on return, so the
  accept-loop above reclaims each connection as it finishes and a reader sees EOF
  as soon as its sibling writer completes. Only the RESULT outlives the task:
  `join()` moves it out (the caller owns it for real, valid after the task is
  gone) and an unjoined result drops once at group teardown. Cancelled-then-
  completed follows the same path. So a long-lived group accumulates nothing, and
  a task-local resource is NOT a way to extend a lifetime — hold it in the
  spawner if you need it to outlast the task. **The SLOT goes too (design 134):**
  the frame allocation is released at completion and its run-queue slot returns to
  a free list, so a group costs O(live + unjoined-result tasks) rather than
  O(tasks ever spawned) — an accept loop that serves 200k connections holds as
  many slots as it has connections IN FLIGHT (`group.count()` reports them). The
  result and the cancel word live in a group-owned cell that outlives the frame,
  which is what lets the frame go; a `Void` task's slot is reclaimed at
  completion, a task with a result keeps its slot until `join` takes the value.
  Handles are `(slot, generation)` pairs, so a handle to a task that has come and
  gone can never reach whatever occupies its slot next: joining an already-joined
  `TaskHandle` panics, joining a finished `VoidTaskHandle` returns, and `cancel`
  is a no-op on both. `cancel_addr()` pins its slot (a raw address must stay
  valid), giving up reuse for that one slot. Suspending calls yield
  IMPLICITLY when they park (a task doing I/O never needs `yield_now`); `yield_now`
  (design 114: `import std.task` — no longer prelude) is now needed only where the
  compute budget does not reach (the bounds below). Fairness backstop — ONE op-count
  budget (default 128, never wall-clock, so interleavings stay deterministic)
  covers both ways a task can fail to cede. (a) An always-ready socket (design
  89-c): every 128 non-parking io ops the primitive force-yields once, so a busy
  reader cedes automatically. (b) A PURE-COMPUTE loop (design 127): the compiler
  charges every LOOP ITERATION of a task body against a frame-resident counter and
  force-yields when it runs out, so `while true { n = n + 1 }` in a spawned task no
  longer starves its siblings and needs no `yield_now`. The compute check is
  inserted at the TOP of each loop body (a `continue` hits it too) in the task's own
  body, in the suspending callees the compiler embeds, and in a suspending `main` —
  which means the body becomes SUSPENDING even if you wrote nothing that suspends.
  Four bounds worth knowing: a SYNC callee is NOT instrumented (a compute loop
  inside a never-suspending helper called from a task still starves — move the loop
  into the task or put a `yield_now` in the helper); a `for` over a COLLECTION
  (`for x in v.iter()`) is not instrumented, nor is any loop nested inside one
  (only a range `for` can be state-split — use a `while` over an index); a CLOSURE
  body is not instrumented; std's io loops use the 89-c charge instead. Cost on a
  maximally tight arithmetic loop in a spawned task: 1.53x (the loop joins the
  frame's state machine). Loops outside task bodies are untouched.
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
  SUSPENDS, is illegal in a `sync` context, and is rejected in the freestanding
  profile. An unannotated extern promises promptness. Design 103 (A6): a blocking
  call inside a suspending body (driven / spawned / a suspending `main`) now RUNS —
  it is OFFLOADED to a worker thread (thread-per-call v1) and the task PARKS on the
  job's pipe like any socket read, so siblings keep running while it blocks and the
  cooperative thread is never wedged. v1 restricts the extern to the C-ABI
  `(Int) -> Int` whitelist (a single Int arg, Int result); a wider signature is a
  clean anchored error (multi-arg + a real pool are future work). Since design 120
  a blocking-extern call BURIED in a larger expression offloads like any other
  suspension — `identity(slow(x))`, `return 1 + slow(x)`, `"slept {slow(x)}"` and
  `let r = 1 + slow(x)` all RUN (re-probed Aug 4); the pre-120 rule that you had to
  bind it to its own `let` first is RETIRED, and so is the error it named. Design
  133 extended that to a NESTED short-circuit: `1 + (cached ?? slow(x))` and
  `identity(cached ?? slow(x))` offload on the None path and skip the offload
  entirely when the LHS decides. (At statement position inside an `if let`/`guard let` body it
  offloads fine — design 104 CFG-splits that branch.) Cancelling a task parked on an offload job wakes
  it (design 102), but the in-flight blocking call cannot be aborted: take() joins
  the worker before the task takes its cancel path.
- Generic suspending functions/methods work (design 70 + 74): effect is
  re-inferred PER instantiation, so `f<A>` may suspend while `f<B>` is
  sync. You can `__saw_drive` / `group.spawn` a generic instantiation, drive a
  generic `&var self` method, drive a suspending method on a generic STRUCT
  (`Holder<Int>`, design 74 shape 2), make NESTED suspending generic
  calls from a driven body (design 74 shape 3), and drive/nest generic templates
  defined in ANOTHER module (design 104 item 2, shape 4 — the pristine-template
  capture is shared across every module in the compilation unit). A suspending
  METHOD call in a
  driven/spawned body embeds as a driven sub-frame in EVERY control-flow
  position — a plain statement, an `if`/`else` branch, a `match` arm
  (including literal/range-pattern arms), a nested `if`, a nested `while`/`for`,
  a TRAILING (block-final) `if`/`match` (design 84 + 101), AND an `if let` /
  `guard let` BODY (design 104 item 1: the optional-binding branch is CFG-split
  like `if`/`match`; the bound name becomes a frame field, and the design-100
  same-name unwrap `if let x = x` keeps the inner `x: T` and outer `x: T?` in
  distinct fields) — so
  `while going { …; if let ok = maybe(k) { let x = try! s.read(); s.write(move x) } }`
  just works. It also embeds in any EXPRESSION position (design 120): a chain head
  or later hop, an argument, a receiver, an operand, a literal element, a string
  interpolation, a `return` value, a `try!` subject, a `?.` hop, a
  `Channel.receive()`. The compiler unchains the statement into evaluation-ordered
  temporaries for you, so left-to-right order and intermediate deinit timing match
  the hand-written `let`-per-step spelling — a side-effecting sibling written
  BEFORE the suspension is lifted with it, so `add(noisy(1), slow(3))` prints
  `noisy` first and `add(v.pop()!, slow(v.len()))` reads the post-pop length
  (design 147; literals, plain name/field/element reads, a `move` operand and a
  closure literal are left in place, anything with a call or `&var` in it is
  lifted); a CONDITIONAL position (a value
  `if`/`match` arm, a `??` / `&&` / `||` RHS, a `?.` hop) keeps its short-circuit,
  so a skipped suspension and its side effects never run — at ANY nesting depth
  since design 133. The operator no longer has to be the outermost expression of
  its statement: `f(a ?? slow())`, `return 1 + (a ?? slow())`,
  `not (a && slow())`, `g(f(a ?? slow()))` and the blocking-extern versions of
  each all transform now (the whole short-circuit is lifted to its own statement
  first), and the RHS still runs only when the LHS does not decide. Still a clean,
  user-anchored compile error (NOT a silent block): a suspension-spanning `if let`/
  `guard let` with a TUPLE pattern, or one whose body RE-BINDS the bound name
  (rename the inner binding); and a NESTED generic call whose template suspends
  UNCONDITIONALLY without calling a type-param method (`func g<T>(x: T) -> T {
  yield_now(); x }` called nested) — its instantiation's effect node is not built,
  so drive it directly with `__saw_drive`/`spawn` instead (this is a same-module limit,
  not a cross-module one). A method that is BOTH struct-generic AND method-generic
  (`Dual<T>.mix<U>`) now drives (design 104 item 3): the frame is keyed by both
  instantiations (`Dual_mix$2$T$U`), so 2 struct × 2 method insts are 4 distinct
  frames.
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
  offers BOTH: value `read() -> Result<Data, IoError>` (fresh Data per call, the
  ergonomic default) AND reference `read_into(&var Data) -> Result<Int, IoError>`
  (design 96 — appends the chunk into a caller buffer through a `&var` held across
  the internal park, so a reader ACCUMULATES successive chunks into ONE growing
  buffer with no per-chunk allocation; returns the byte count, 0 = EOF).

## Modules & packages
```saw
import std.net.{TcpListener, TcpStream}   // non-prelude std: import to use bare
import std.file                            // whole module (exposes File, ...)
import mymodule as mm       // aliasing; `module`/`public`/`package`/`parent`
```
- **Utility methods belong on the receiver as extensions — including on
  types you don't own** (user idiom ruling, Aug 5). A helper that is
  *about* one value reads as a method: write `extension Data {
  func u16_at(&self, off: Int) -> UInt? }` and call `d.u16_at(0)`, NOT
  `func u16_at(d: &Data, off: Int)`. This is safe on foreign/std types
  because design-80/82 visibility makes the extension MODULE-PRIVATE by
  default — invisible to other packages, absent from the type's public
  docs, no collision risk. Free functions are for operations no single
  argument owns (conversion pipelines, multi-receiver algorithms). If a
  private extension turns out generally useful, promote it to std rather
  than making it `public` on a std type from a package.
- **Extension methods are IMPORT-SCOPED (design 142).** Lookup consults
  exactly three places: your own module, the modules your FILE imports
  DIRECTLY, and the receiver type's own defining module (its inherent API —
  a `Data` you were handed keeps every `std.data` method whether or not you
  wrote `import std.data`, which you may not even be able to write). A
  TRANSITIVE dependency contributes NOTHING: if you import `net` and `net`
  imports `codec`, `codec`'s `public extension Data` is invisible to you
  until you import `codec` yourself. So `public` on an extension means what
  it means everywhere else — importers of my module get this — and the
  calling-it-without-the-import error names the module to add
  (``type `Data` has no method `u16_at` in scope here`` / ``add `import
  bmod```). std is ONE scoping domain (its files extend each other's types
  on purpose), so nothing about std method calls changes. Two imported
  modules may extend one type with the same method name: different
  signatures overload normally, identical ones are an ambiguity error AT THE
  CALL naming both modules.
- **CONFORMANCES follow the ORPHAN RULE (design 142)**, not import scoping:
  `extension T: Trait` is declarable ONLY in the module defining `T` or the
  module defining `Trait`. A conformance mints one vtable per (type, trait)
  pair and backs a contract (Hashable feeds Map, Equatable feeds `==`), so
  two of them for one pair would let a Map built in one module and probed in
  another disagree about hashing — an incoherence no use-site error can
  catch. To conform a foreign type to a foreign trait, WRAP it in a type you
  own. A conformance declared under the rule is coherent program-wide, so it
  needs no import: it is visible wherever the type and the trait both are.
  In practice you almost never notice this rule — you conform your own
  types, and the in-tree migration when it landed was zero.
- **TYPE IDENTITY is (defining module, name) — design 144.** A dependency's
  PRIVATE `struct Header` reserves nothing in your program: you declare your
  own `Header`, with its own layout, methods and `Vector<Header>`. Same for
  private enums, traits and type aliases. Two packages' PUBLIC same-name types
  coexist too, but one file cannot spell both bare — import at least one under
  an alias (`import wire.{Header as WireHeader}`, or `import wire` and write
  `wire.Header`). A bare use with two in scope is an ambiguity error naming
  both modules, at the USE site. Nothing about how you WRITE a type changed;
  names print short everywhere (`--emit-docs` adds a `module` field where two
  would read alike).
- **Prelude (design 82) — what's bare vs what needs `import std.X`.** Bare
  (prelude): primitives, `Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/`Arc`/
  `Allocator`/`GlobalAllocator`, the Copy family + `Deinit`/`Iterator`/
  `Equatable`/`Comparable`/`Hashable`/`Printable`/`Error`/`Send`/`Sync`,
  `print`/`panic`/`assert`/`sizeof`/`alignof`/`static_assert`, `TaskGroup`/
  `sleep`/`spawn`/`cancelled`, `StringBuilder`. IMPORT-REQUIRED:
  `File`/`Directory`/`Path` (std.file/directory/path), `Data` (std.data),
  `Channel` (std.channel), `Mutex` (std.mutex), `Duration`/`Instant` (std.time),
  `IoError`/`TcpListener`/`TcpStream` (std.net), `Utf8Error` (std.string),
  `yield_now` (std.task — design 114; the wrapper over the stdlib-internal
  cooperative-yield intrinsic), `Command` (std.process), `Env` (std.env),
  `FixedBuf`/`FixedStringBuilder` (std.fixedbuf — design 148). A bare non-prelude name is a clean
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
  corrupt a private field. Do NOT cargo-cult `public` onto fields/methods in a
  SINGLE-module program or test — same-module access is ungated, so it is inert
  noise there. (2) A method satisfying a visible trait's
  requirement is callable through the conformance with no `public` needed.
  (3) `public` on a member of a private struct is legal but inert. std is
  under the gate too — you reach its public API, never its internals; each std
  FILE is its own module (design 82), so std internals are private per-file.

## Allocation failure (design 123 — one policy, two tiers)
An **infallible signature PANICS** on allocator exhaustion, naming its method
(`panic at vector.saw:180: Vector.push: allocation failed`) and routing through
`__saw_rt_panic` so a kernel picks the policy. That is `push`/`append`/`insert`/
`send`/`Box.make`/`String.to_uppercase`/`Path.join` and EVERY constructor
(`Vector(capacity:)`, `Data(capacity:)`, `Arc(value:)`, `Mutex(value:)`,
`Channel()`, `TaskGroup(threads:)`), plus the compiler's own two sites (a
spawned task's control block, an escaping closure's env).

Each has a **`try_` twin returning `Result<_, AllocError>`** — the fallible tier,
and the PRIMARY surface for allocator-parameterized types (`Vector<T, A>`,
`Box<T, A>`, `Map<K, V, A>`, `Set<T, A>`): `try_with_capacity`, `try_push`,
`try_reserve`, `try_copy`, `try_make`, `try_append`, `try_append_char`,
`try_append_bytes`, `try_insert`, `try_send`. `try_` is the ONE spelling (design
123 renamed `Box.make_or` -> `try_make`; `Channel.try_receive` is unrelated — a
non-blocking poll, Rust's `try_recv`). A `try_` op is ALL-OR-NOTHING: on `Err`
the container is untouched, every element still in it. Its argument is consumed
either way — `try_reserve` FIRST when the value must survive a refusal.
`AllocError` carries the refused `size`/`align` and is `Error + Printable`
(`"{e}"` -> `allocation of 64 bytes (align 8) failed`).
```saw
match frames.try_push(Frame(id: 1)) {
    case Ok(_) -> print("queued"),
    case Err(e) -> print("out of frame memory: {e}")
}
```
`String` has NO fallible tier — every producer returns a plain `String`, so the
one allocator behind them panics (covers `to_uppercase`/`replace`/`trim`/
`substring`/`join`/`StringBuilder.build`/`Path.join`/`String.fromBytes`).
Nothing degrades: no truncated container, no `Ok("")` from a validating
constructor, no un-joined path, no dropped message, and no inert object
(`Arc`/`Mutex`/`Channel` used to construct one and no longer can). `Mutex.get()`
is `T`, not `T?`, for the same reason. Still open: `Mutex.lock`'s result is
`Bool` rather than the closure's own type (M1, blocked on DF-123c — Arc payload
forwarding cannot reach a method-generic method).

## Systems/embedded corner
`static NAME: T = const_init` (Sync-only, immortal); `Atomic<Int>`;
allocator type params `Vector<T, A: Allocator = GlobalAllocator>`, `Box<T, A>`,
slab in std/slab.saw; `UnsafeMemory<T, Device|Normal>` for MMIO
(volatile, RO/WO markers);
- **Wire/register structures are TYPED VIEWS, never offset arithmetic**
  (user idiom ruling, Aug 5). Declare the layout ONCE as a struct of
  fixed-width fields (+ explicit reserved bytes), pin the ABI with
  `static_assert(sizeof<T>() == N)`, and read through
  `UnsafeMemory<T, Normal>` (RAM) / `<T, Device>` (MMIO) by FIELD NAME —
  `seg.mem_len`, not `read_u32(rec + SEG_MEM_LEN)`. One unsafe view
  construction replaces N raw reads; a layout edit that skews offsets
  becomes a compile error instead of a silent corruption. Design the
  format alignment-friendly (each u32 4-aligned) so the overlay is exact;
  note LE assumptions in a comment. Share the struct module between
  writer and reader when they are separate packages. `@export("sym")`/`@section(".s")` on
top-level func/static ONLY (`@synthesize` is the extension-only one — see
traits; each is a clean error in the other's position)
(C ABI, whitelist: fixed-width ints, Int/UInt,
Float, UnsafePointer, Void/Never — no Bool/String/aggregates by
value; an exported return may not be optional — a seam returns a raw
`UnsafePointer<T>`, the `?`-wrapping is the caller's `extern` decl).
`@export` of a reserved runtime symbol (`main`, `saw_*`, `__saw_*`) is an
error — EXCEPT under `sawc --runtime-build` (design 113b), which lets the
per-host runtime under `sawc/rt/` export exactly the frozen `__saw_rt_*`
ABI (sync-only; a non-ABI `__saw_rt_*` name / a suspending body is a clean
error). You only touch this when authoring `sawc/rt/`. `static_assert(
sizeof<T>() == N, "msg")`; struct layout = declaration-order natural ABI
(documented rule) — a Saw struct can mirror a C struct for FFI.
**Unsafe surface (design 130 + 136 — supersedes design 81's marking rules).**
Unsafety is TYPE-carried, not region-carried: no `unsafe` blocks, no unsafe
regions, and NO line-level `unsafe` expression marker (writing one is now a
parse error telling you to mark the declaration). The unsafe types are
`UnsafePointer<T>`/`UnsafeConstPointer<T>`, `UnsafeMemory<T, Use>`, and anything
you declare `unsafe struct` — the keyword confers the semantics and the compiler
then REQUIRES the name to start with `Unsafe` (`unsafe struct MmioReg` errors,
"rename it to `UnsafeMmioReg`"). The converse does not hold: a plain
`struct UnsafeDefaults` is an ordinary safe type.
**Trigger rule:** a function is `unsafe` iff its body or signature NAMES, BINDS,
RECEIVES or RETURNS a value of an unsafe type — a reference to one
(`&UnsafePointer<T>`) counts, and so does merely reading a pointer field to test
it (`self.buffer != None`). Not declaring it is a clean error naming the type.
Spelling (design 136): `unsafe` is an EFFECT and rides the post-parameter slot
beside `sync`, canonical order `unsafe sync` — `public func push(&var self, ...)
unsafe`, `init(at: Int) unsafe -> UnsafeMmioReg`, `func read(&self) unsafe sync
-> Int`. A prefix `unsafe func`/`unsafe init` is a clean error naming the slot,
and so is the reversed `sync unsafe`. `unsafe struct` KEEPS the prefix (a struct
has no parameter list, so no slot; the enforced `Unsafe*` name carries it). A
function TYPE uses the same slot with `escaping` completing the order:
`(UnsafePointer<T>) unsafe sync -> R` — so a declaration and its type read
identically.
**NOT transitive:** `Vector` holds an `UnsafePointer` field and IS a safe type —
safe to name, hold, pass, store. Only the methods reaching through to the field
are unsafe, and `self` is never counted as contact. Derivation doesn't propagate
either: a `&T` obtained from `buf[i]` inside an unsafe function is safe onward.
**Function TYPES: the effect is the SIGNATURE (design 136).** `unsafe` on a
function type is well-formed iff a parameter or the return names an unsafe type —
BOTH halves error: `(UnsafeMmioReg) sync -> Int` ("does not say `unsafe`") and
`(Int) unsafe sync -> Int` (rule 7: "a function taking only safe types must be
sound for every input"). One contract, one spelling, so there is no variance
question. Checked on the type AS WRITTEN, so a generic `(&T) sync -> R` slot is
judged against `T` and never re-judged for a `T = UnsafePointer<Int8>`
instantiation. A DECLARATION may still carry a redundant `unsafe` (it promises
something about its BODY); taking it as a value yields the plain type.
**Closures: judged on their SIGNATURE, and they INHERIT the enclosing domain.**
`v.with_ref(0) { e in e + 1 }` sees only `&T` and stays safe even though
`with_ref` is unsafe. A closure whose signature names an unsafe type carries
`unsafe` in its type and fits the `unsafe` slot that handed it the value
(`String.withCString`'s callback is the std case) — that contact stays local.
Contact BEYOND the signature (a captured pointer, an unsafe binding written in
the closure body) belongs to the ENCLOSING function: there is NO closure-level
marker, so a safe-signature closure with an unsafe body needs the enclosing
`func f(...) unsafe` (the allowed redundant form) or a hoisted named `unsafe`
helper — inside a safe function it is the ordinary "not declared `unsafe`" error
naming that function. A closure-scoped unsafe region was considered and rejected:
captures give a closure the whole enclosing frame, so its braces confine the text
but not the blast radius; the enforceable boundary is a SIGNATURE. An
unsafe-built, safe-signatured closure escaping behind a plain function type is
the author's rule-7 wrapper (the ad-hoc `Vector`-over-`UnsafePointer`).
**Calling an unsafe function from safe code needs no ceremony.** What makes that
sound: a function whose parameters are all safe types must be sound for EVERY
input, and a precondition is expressed by taking an unsafe-typed parameter —
which drags the obligation into the caller through the trigger rule itself.
Std policy: an `unsafe` function is short enough to review as a unit.
**Accessor rule:** on a safe type every indexed accessor is checked. A direct
accessor PANICS out of range (`Vector.set`/`swap`/`swap_out`/`with_ref`/
`with_var_ref`, `Data.set`, `String.byte_at`/`substring`); a `get`-shaped one
returns `None`/`Err` (`Vector.get`, `Data.get`, `Data.slice`). Never a silent
no-op, never a clamp, never an ignorable status flag (`Data.set` returned one).
For scoped no-copy element access use `Vector.with_ref`/`with_var_ref` (a
non-escaping `&T`/`&var T` borrow, invalidation-proof) — this REPLACED `ref_at`.
**MMIO driver idiom (blessed, design 112 — use for EVERY memory-mapped
device):** two structs per device — a register-block struct that IS the
hardware layout (declaration-order ABI; `ReadOnly<T>` for read-only registers)
and a driver struct owning the mapped block, with extension methods as the
device API:
```saw
struct UartRegs { thr: UInt8, ..., lsr: ReadOnly<UInt8>, ... }
struct Uart16550 { regs: UnsafeMemory<UartRegs, Device> }
extension Uart16550 {
    init(at: Int) unsafe -> Uart16550 { Uart16550(regs: UnsafeMemory<UartRegs, Device>(at)) }
    func write_byte(&self, b: UInt8) unsafe { /* poll lsr, write thr */ }
}
```
Don't drive registers through free functions constructing `UnsafeMemory` per
call, and don't extend the raw block type. The driver struct keeps `regs`
private (design 80); `Uart16550` itself is a SAFE type (unsafety is not
transitive), so it passes through safe code freely and only the methods touching
`regs` carry the `unsafe` effect. It has room for device state. No singleton
`static` drivers yet (statics need const inits — Once/Lazy is tracker F5):
construct in the owner and lend `&driver` down.

## Gotchas
- Receivers are `&self` and `&var self`, always with the sigil. A bare
  `var self` (an old spelling some code still shows) is a compile error
  pointing at `&var self`; a bare `self` is likewise rejected.
- **`borrows` CHANGES WHAT `&self` MEANS** (design 146) — read this before
  writing an accessor. On a `borrows` method the receiver is borrowed with the
  WINDOW's flavor, decided at each USE SITE: `print(g[4].n)` borrows `g` shared,
  `g[4].n += 1` borrows it exclusively, out of the same `&self` declaration.
  This is the ONE place in Saw where a `&self` spelling does not mean
  shared-only, and it is deliberate (design 141 decision 3: one body serves both
  flavors). The polymorphism reaches the `lend` and NOTHING else — the rest of
  the body is ordinary `&self` code, so a field write or a `&var self.<field>`
  in the prologue/epilogue is the same hard error it is in any other `&self`
  method. Write the accessor `&var self` when the body genuinely mutates the
  receiver (an epilogue that bumps a counter); that is legal and STRICTER —
  every use site then borrows the receiver exclusively, reads included, so a
  `let` root stops working. `--emit-docs` reports a `&self` borrows receiver as
  `"self": "window"`, not `"borrows"`.
- **`&var self.<field>` inside a plain `&self` method is a compile error**
  (design 146). A `&self` receiver arrives by VALUE, so that projection used to
  hand out a mutable reference into the callee's copy and the write vanished —
  silently, for years. Same rule design 106 already applied to a `&` parameter.
  Fix: declare `&var self`, or `borrows -> T` if you meant to lend the place.
- **RAW-BACKED ENUMS are the wire idiom** (design 145 B2). A payload-free enum
  may declare an integer backing in the colon position; that PINS the width and
  the tag values, so it may be a field of an `UnsafeMemory`-viewed wire struct
  (`flags: SegFlags` instead of a bare `UInt8` and a comment):
  ```saw
  enum SysError: UInt8 { case Ok = 0, case BadHandle = 3, case NoMemory = 12 }
  let raw = err as UInt8                       // TOTAL — the enum IS its tag
  if let e = SysError.from(raw: b) { ... }     // PARTIAL — None on unknown
  ```
  Every case states its own value (no auto-increment: declaring a backing says
  the numbers are ABI, so a reorder must never renumber them), duplicates and
  omissions are clean errors, and payload cases are rejected. An enum WITHOUT a
  backing keeps compiler-assigned ordinals and is not castable at all. The
  inverse is `from(raw:)` — a synthesized static returning `E?`, NOT an init: an
  unrecognized wire byte is data, never a trap. Fixed-width backings are the
  wire-safe choice; a raw-ordered Comparable derivation does not exist.
- **ENUMS TAKE EXTENSIONS, same as structs** (design 145): instance methods with
  `&self`/`&var self` (`match self` is the idiomatic body, `self = Other` the
  whole-value replacement), static methods (no `self` param), hand-written trait
  bodies (Printable/Error/your own), `@synthesize` derivations, a hand-written
  `deinit` inside the copy policy, and per-instantiation methods on a generic
  enum. Import-scoped lookup and the orphan rule apply unchanged. The ONE
  difference: no `init` — the cases are the constructors, and writing one is a
  clean error naming a static method as the way to compute which case to build.
- An escaping closure (bound/returned/stored/`spawn`) is **ImplicitCopy**
  over a refcounted heap env (like String/Arc): `let g = f` is a free
  refcount bump (both valid), and the captures are torn down exactly once
  when the last owner drops. Copying a struct/`Vector` that holds a
  closure retains the env; capture-less closures are trivially copyable.
  `move f` still transfers ownership. A closure also satisfies the generic
  `Copy` bound, so `Vector<() -> Int>` is copyable — `.copy()`/`.get()` each
  retain the element env exactly once (deinit-once through copy).
- **Writing to a by-value capture is a compile error** (design 132). The env is
  immutable and each plain/`move`/`copy` capture is loaded into a per-call
  local, so `{ n = n + 1  n }` would count in a copy that dies with the call.
  The error names the two working spellings: `[&var n]` (borrow capture — only
  in a closure passed directly to a non-escaping parameter) and `Arc<Mutex<T>>`
  (escaping, shared instead of captured). READS are untouched, and so are the
  closure's own locals/params, a `&var` closure parameter, and a capture that
  is already a reference. Covers the whole path in — `n = v`, `n += v`,
  `s.f = v`, `t.0 = v`, a fixed-array element — but NOT `v[i] = x` on a
  `Vector`, whose heap buffer the copy shares (that write does persist). The
  counter-closure idiom is unwritable without an `Arc<Mutex<Int>>`.
- `guard` must exit (return/break/continue/panic).
- Shadowing footgun (design 100/107): naming an inner binding after an outer one
  is an ERROR unless the inner DERIVES from the outer (its initializer mentions the
  name). Reach for it deliberately (`let data = parse(move data)`, `if let x = x`);
  to just reuse a name for an unrelated value, pick a different name. A
  `case Move(x, y)` under an outer `x` is rejected — it binds fresh `x`/`y`, it
  does not compare against the outer `x`. The rule is uniform across SITES: the
  same-scope redefinition `var data = read(); let data = parse(move data)` is legal
  in ONE scope (the new binding replaces the old; a `.copy()`-derived old value
  drops right at the redefinition), and a `for`-loop var derives from the SEQUENCE
  (`for x in x.iter()` OK, `for x in ys` under an outer `x` errors — including an
  inner loop var vs an enclosing loop var).
- A dependency name mapped via `--module-path` shadowing a local
  module file is an error.
- **`v[i]` is a PLACE, not a copy** (design 146) — `Data` has the same `d[i]`.
  Reach the element THROUGH it: `v[i].count += 1`, `v[i] = fresh`
  (whole-element write, old element deinits once), `v[i].method()`,
  `f(&var v[i])`. Taking it OUT as a value (`let e = v[i]`) follows the copy
  tier: bitwise for trivial, RETAIN for ImplicitCopy, clean ERROR for
  ExplicitCopy/NoCopy. Both `v[i]` and `d[i]` PANIC out of range.
  **`Vector.get(i)` is the `None`-returning twin** — a conditional lend, the
  same lowering: `if let e = v.get(i)` is a value read (so the copy tier
  applies), `v.get(i)!.count += 1` opens an exclusive window, and the absent
  path opens no window at all. A move-only element is REFUSED at a value read
  now; it used to come out as a non-retained alias two lookups double-freed.
  `swap_out(i, v)` moves a slot out; `with_ref`/`with_var_ref(i, body)` are
  still the multi-statement / long-window spellings (a place window is ONE
  expression) and the only way to hold a borrow across several statements.
  `iter()`/`enumerated()` carry a `T: Copy` bound (design 122): `next()` yields
  an element the consumer OWNS, so a NoCopy element is reached through a place
  or `with_ref`, never a `for` loop. Since design 130's accessor rule,
  `set`/`swap`/`swap_out`/`with_ref`/`with_var_ref`, `String.byte_at(i)` and
  `String.substring(s, e)` ALL PANIC out of range — no silent no-op
  (`set`/`swap` used to be) and no clamp (`substring` used to be). An empty
  `substring(i, i)` is still legal; a REVERSED range panics.
- **A pattern that BINDS NOTHING is a presence test, not a read** (design 146).
  `if let _ = doc.section(name)`, `guard let _ = ...`, and a `match` arm like
  `case Empty` or `case Occupied(_)` look at the discriminant through the
  borrow — no copy, no drop — so they work on a move-only place, where a value
  read is refused. A `match` on a place matches it WHERE IT SITS, and an arm
  that does bind binds the payload in place, so the copy tier is consulted for
  that one binding rather than the whole element. Two shapes stay on the
  value-read path because a window is a closure: an arm that `return`s/`break`s
  out of the function, and an arm that `move`s its own binding out.
  Holding one index and reading several values (`doc.section_at(i).get("a")`,
  `...get("b")`) is still the idiom when reads must span STATEMENTS — a place
  window is one expression, so an INDEX is what survives.
- **A place value read inside a generic body needs a bound** (design 146). An
  element type that mentions a type parameter (`Slot<K>`, or a bare `K`) has no
  copy tier of its own — the instantiation decides — so the read is legal only
  when the bounds prove every instantiation copies (`K: Copy`). The error names
  the parameter and arrives in the generic body, never at one caller. Reach the
  place through a borrow if you cannot bound it.
- String `chars()` yields Int scalars (no Char type); the inverse is
  `StringBuilder.append_scalar(scalar: Int) -> Int?` (design 119) — UTF-8
  encodes + appends a scalar, returns the byte count (1..4), `None` (appends
  nothing) for an invalid scalar (negative / surrogate / > 0x10FFFF).
- `to_int()`/`to_int(radix:)`/`to_float()` are whole-string, no trimming →
  Optional; `to_uint()`/`to_uint(radix:)` (design 119) are the unsigned
  companions (→ `UInt?`), reaching the `2^63..2^64-1` range signed parsing
  can't (overflow past `UInt.max` → `None`). Integer bounds are the builtins
  `Int.max`/`Int.min`, `UInt.max`/`UInt.min`, `Int8.max`…`UInt64.max`. An
  unsigned value prints unsigned everywhere — `print`, `"{x}"` and `to_string()`
  agree across the whole `0..2^64-1` range (design 122).
- std.time/std.process/std.file/std.net are HOSTED-only (link libc).
  `Command` spawns a real ARGV — no shell, ever (design 122): one `arg(..)` call
  is exactly one argv element, so spaces, quotes, `;`, `*` and `$VAR` inside an
  argument are literal bytes the child receives verbatim (nothing is split,
  expanded or executed). Want a shell? Spawn one explicitly:
  `Command(program: "/bin/sh")`, `arg("-c")`, `arg("cmd | cmd2")`. `arg` returns
  Void, so build it in statements, not a chain:
  ```saw
  var c = Command(program: "git")
  c.arg("clone"); c.arg(url)
  let code = try! c.run()
  ```
  `run() -> Result<Int32, ProcessError>`: Ok(code) = launched + exited (signal
  death = 128+signum, never a bogus 0); Err = could not launch (spawn failed, or
  the child could not exec -> 127). `ProcessError: Error` names the program.
  `.output() -> CommandOutput?` captures stdout (stderr is inherited).
- `UnsafePointer<T> + n` / `- n` / `[i]` are ELEMENT-STRIDE GEPs (the C
  convention: `UnsafePointer<Int32> + 1` advances 4 bytes). Use them for typed
  pointer math. `ptr as Int` (+ int math + `as UnsafePointer<T>`) DESTROYS
  provenance (blocks alias analysis) — reserve it for genuine address-as-number
  cases (slab free-list). For byte-granular offsets, cast to `UnsafePointer<Int8>`
  FIRST, then add.
- STYLE (user idiom ruling, Aug 6): no magic numbers — name them — and a
  CLOSED NAMED SET of values (states, tags, modes, op ids, rights bits) is an
  **Int-inheriting backed enum**, not a family of statics: `enum LockState:
  UInt8 { case Unlocked = 0, case Held = 1 }` names the set, PINS the values,
  gives exhaustive `match` over the states, `E.from(raw:) -> E?` at the read
  boundary, and `as` where the raw number is needed (fixed-width backing when
  the values cross a wire/ABI, design 47). A module-level `static` is for a
  genuine standalone QUANTITY — a size, an alignment, a budget, a lone
  constant like `static AF_INET: Int32 = 2`. A parallel family of Int statics
  (`UNLOCKED`/`HELD`, `TAG_A`/`TAG_B`) is the smell this ruling exists to
  catch (design 153 sweeps the existing ones). Static inits accept only plain
  literals (no casts/arithmetic) plus array literals — including a REPEAT
  literal, so `static BUF: [Int8; 4096] = [0; 4096]` is the spelling for a large
  zeroed region (design 148); std-module statics are NOT visible cross-module
  yet.
- For a KNOWN C struct, declare a typed Saw struct (declaration-order natural ABI,
  design 58) as a stack local + `(&sa) as UnsafePointer<...>` for the syscall —
  never a raw byte blob; alignment comes free from the widest field. Only
  genuinely OS-divergent bytes need a compiler shim.
- Blade: `blade build/run/test/new/add/tree/update`; Saw.toml
  `[dependencies] name = { path = "..." }` or `{ git = "...",
  version = "1.2.3" }` (bare version = exact pin; no registry yet).

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
                           // an `init` declares the RECEIVER (`Self`, the
                           // receiver written out, or NO clause) or
                           // `Result<Receiver, E>` — nothing else, and never
                           // an optional. See "A FALLIBLE `init`" in Errors
extension Point { static func origin() -> Point { Point(x: 0, y: 0) } }
                           // `static` is REQUIRED on a receiver-less method
                           // (design 236) and the call is on the TYPE. A
                           // self-less `func` is a DECLARATION error with a
                           // two-way fixit; `static func f(&self)` is the
                           // mirror; `static init` is an error (init is exempt)
enum Msg { case Quit, case Move(x: Int, y: Int) }
extension Msg { func is_quit(&self) -> Bool { match self { case Quit -> true,
                                                           case _ -> false } } }
type UserId = Int          // DISTINCT type; flows TO Int; back via UserId(i)
                           // `type` is CONTEXTUAL (DF-232b, Aug 17): a keyword
                           // only where an alias begins (module level, or a
                           // trait/extension member). Elsewhere it is an
                           // ordinary name — `f(type: 1)`, `struct E { type: Int }`,
                           // `e.type`, `let type = 7` all compile. An alias
                           // inside a function body is still refused.
                           // underlying may NOT be an enum (DF-194b) — no `as`
                           // reading exists for one, so the alias is refused
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
  `#` takes only these three plus `#lend_var` (the `borrows`-body
  specialization constant, design 179 — see Places) — any other `#name` is a
  lex error.
- Everything is an expression (if/match/while/blocks yield values;
  `break v` from an infinite `while {}` yields `T` directly;
  from a conditional while/for it yields `T?`).
- `for i in 0..5` / `0..=5`; `while cond {}` / infinite `while {}`;
  `while let x = src.next() {}` (the drain — see Patterns).
- **A conditionless `while {}` with NO `break` types `Never`** (design 177) —
  it diverges exactly like `panic(...)`, so `func halt() -> Never { while { } }`
  is the halt spelling, a diverging tail satisfies any `-> T`, the code after it
  is unreachable, and it is a valid `guard ... else` exit. Judged per loop: a
  `break` in a NESTED loop leaves the outer one diverging, and a `return` is not
  a break. **`while true {}` is EXCLUDED** and keeps its old typing — write the
  conditionless form when you mean "this never returns".
- **A `-> Never` CALL diverges wherever `panic(...)` does (design 228).** One
  rule: an expression of type `Never` satisfies any expected type, because there
  is no value to reconcile. The positions, all of them:
  ```saw
  guard let e = find(id) else { fault(1) }        // a guard exit
  if e.stale { fault(2) }                         // a statement
  match k { case Missing -> { fault(3) },         // an arm — the match takes
            case Ready -> { Reply(code: 0) } }    //   the other arm's type
  cfg.port ?? fault(4)                            // a `??` default
  return fault(5)                                 // a `return` operand
  store(fault(6))                                 // an argument (`store` is
                                                  //   never called)
  func handle() -> Reply { fault(7) }             // a tail, at ANY return type
  func onward() -> Never { fault(8) }             // …including `-> Never`
  ```
  The callee's shape is not a factor: plain, overloaded, module-private,
  imported, `extern "C"`, extension method, static method, generic function or
  method, closure, and `any Trait` requirement all behave alike, hosted and
  freestanding. Treat all of it as working now and SUSPECT in older builds —
  the guard exit was a clean refusal, `return <diverging>` and a diverging
  ARGUMENT were compiler crashes (the latter for `panic` too), `o ?? panic(..)`
  was refused, and a diverging arm or tail emitted invalid IR whenever the
  callee was overloaded or module-private.
  **A task body may not be `Never`**: `group.spawn(halt())`, `Thread.spawn { while {} }`
  and `__saw_drive(halt())` are refused, since `join` on such a handle could
  never return. Write a forever-task as `-> Void` with a loop and end it by
  cancelling the task or breaking the loop. Calling a suspending `-> Never`
  function directly is untouched.
- Integer literals: `0xFF`, `0b1010`, `1_000_000`, fixed-width
  suffixes `255u8`/`1_000i32` (exact-typed, range-checked). A bare
  (unsuffixed) literal adopts a fixed-width EXPECTED type wherever one
  is in force — annotation, param, field, return, default value,
  if/match arm, compound-assign RHS, array/tuple/Map/Set element — and
  is range-checked at the literal (`let b: UInt8 = 256` is a clean
  error). An ASSIGNMENT TARGET is on that list at every target kind
  (DF-232a, fixed Aug 17): `v = 4`, `w.b = 2`, `t.0 = 5`, `arr[0] = 5`,
  `m[k]! = 5`, an `unsafe static var`, and a `&var`/`self` referent. Six
  of those were internal compiler errors before that date
  (`cannot store i64 to i32*`), so treat them as working now and SUSPECT
  in older builds; `0u32` was the workaround.
  With no fixed-width expectation it stays platform `Int`
  (`let x = 5`); in a mixed binop it takes the other operand's TYPE.
  A CLOSURE BODY's return positions are on that list too (DF-226a, fixed
  Aug 17: the tail, the arm results inside it, a `return`), and so is an
  OPTIONAL slot's PAYLOAD (DF-226d, same day): `let x: Int32? = 1` is an
  `Int32`, at every position above and to any depth (`Int32??` lands at
  `Int32`), while a branching value keeps the optional so an arm may still
  be a bare `None`. Both were internal compiler errors before those dates
  (`ret i64` from an `i32` function), so treat them as working now and
  SUSPECT in older builds. A `RESULT` slot adopts too (DF-226e, fixed
  Aug 17): it peels to the UNIQUE payload that could take the literal,
  which also picks the variant — `return 4` at `-> Result<Int32, Bad>`
  is `Ok(4)` at `Int32`, `return 7` at `-> Result<String, Int32>` is
  `Err(7)`. Where BOTH payloads could take it (`Result<Int32, Int8>`)
  it is refused by name; write `Result<Int32, Int8>.Ok(value: 4)`.
  A closure's `return` behaves as a named body's, and so does a closure's
  TAIL since DF-232h (fixed Aug 22): `{ x in 12 }` at a
  `-> Result<Int32, E>` slot is `Ok(12)`, and the ambiguity refusal, the
  erased `Box<any Error>` target and an optional Ok payload all reach it
  too. It was refused outright before that date (``argument `f` expects
  `(Int) sync -> Result<Int32, Bad>` but got `(Int) -> Int32` ``), with
  `return 12` as the workaround, so distrust a bare Result tail in an
  older build. A bare `None` TAIL at a `Result<T?, E>` is `Ok(None)` on
  the same terms since DF-244b (fixed Aug 22) — a named body, a method, a
  closure, a generic body and an erased `Box<any Error>` target alike —
  where it used to die with ``cannot tell what this `None` is a `None`
  OF`` and `return None` was the one-keyword workaround. A `None` at a
  Result whose Ok type is NOT an optional stays the clean refusal it
  always was for `return`, now at the tail too.
  **A CONSTANT EXPRESSION IS ON THAT LIST TOO (DF-235a/b, fixed Aug 21):**
  anything the const evaluator folds — `2 + 3`, a shift, a mask, `~m`, a
  negated constant — adopts the slot's width and is range-checked on the
  FOLDED value, so `let e: UInt16 = 1 << 20` is the same clean "does not
  fit" error the bare `1048576` is, and `let a: Int8 = -(1 << 7)` is
  `Int8.min` and compiles. GOTCHA: the fold is in design 185's SIGNED
  platform-`Int` domain, so `1 << 63` is `Int.min` and does NOT fit a
  `UInt64` — mask it (`~0 & 0xFFFF_FFFF`) or write the literal, exactly as
  `(1 << 63) as UInt64` has always demanded. A runtime operand is not a
  constant, so `n * 2` is untouched. Treat all of it as working now and
  SUSPECT in older builds: most positions SILENTLY TRUNCATED (`1 << 20` at
  `UInt16` printed 0), the repeat literal and the `??` operand carried the
  value at platform width past the declared one, `acc += (1 << 2) + 4` was
  refused outright, and a mixed array literal or a Result payload was a
  codegen ICE.
  **AND THE NAMES A CONSTANT MAY READ COME WITH IT (DF-240a, ruled + fixed
  Aug 21):** a fixed-width slot is a FULL const position, so the expression's
  leaves may be a module `static` or a raw-backed enum CASE, exactly as in a
  `static_assert` or an array length. `let e: UInt16 = 1 << PAGE_SHIFT` is the
  clean "does not fit" error (the size-in-one-place idiom stops losing the
  check), and `let mask: UInt8 = Perm.Read | Perm.Write` is legal with the
  value 3 — see FLAG ENUMS below for what that amends. Both were wrong before
  Aug 21: the first compiled and printed `0`, the second was refused.
  **AND SO DOES A MIXED-BINOP OPERAND (DF-243a, fixed Aug 22)** — the one
  position on the bare literal's list that ladder had not reached. A const
  expression beside a typed operand adopts that operand's width in a
  comparison, in arithmetic and in the bitwise operators, in a const position
  and out of one: `(right as UInt32) >= (1 << 8)` and `flag + (1 << PAGE_SHIFT)`
  need no suffix, and one that does not fit is the same "does not fit" error a
  bare literal gives. It was refused outright before that date (``operator `>=`
  requires both operands to have the same type, but the left is `UInt32` and
  the right is `Int` ``) with `1u32 << 8` as the workaround, which is what made
  the Aug-17 bit-flag ruling cost a suffix in an assert and none in the case
  value it checks. A RUNTIME operand is still not a constant, so
  `word.read() | (1u32 << n)` keeps its suffix for the reason the idiom below
  states.
  **IDIOM (user ruling, Aug 16): no suffix where an expected type is in
  force.** `static CR: UInt32 = 0x301u32` says the width twice — write
  `0x301`; same in a param (`reg.write(0)`), a comparison against a typed
  operand (`(fr & FLAG) == 0`), and a repeat literal (`[0; N]` under
  `[UInt64; N]`). A suffix earns its keep only where the literal would
  otherwise stay platform `Int`: a SUBEXPRESSION no expected type reaches —
  `word.read() | (1u32 << n)` needs it (the `|` sees `Int` otherwise; a
  shift passed DIRECTLY as the argument adopts and does not) — and a
  64-bit constant on a 32-bit target with no annotation beside it.
  **STYLE (user ruling, Aug 17): large numeric literals take `_` group
  separators.** Write `1_000_000_000`, `0xFFFF_FFFF`, `0x2000_0000` —
  never a bare `1000000000` or `0x2000000`: the digits are for the
  machine, the grouping is for the human reading them. Group decimal
  by thousands and hex by fours (nibble-quads); a literal short enough
  to read at a glance (`4096`, `0x301`) needs none.
  **STYLE (user ruling, Aug 17): a BIT-FLAG value is spelled as a
  shift, never an absolute decimal.** In a rights/flags enum:
  `case ThreadCreate = 1 << 8`, not `= 256` — including the low bits
  (`Transfer = 1 << 0`) for uniformity. WRITABLE since DF-232c (Aug 17):
  a case value is a const EXPRESSION, so literals plus arithmetic,
  bitwise and shift operators over them all fold, range-checked against
  the backing afterwards. It may NOT name a `static` or another enum's
  case (an enum's cases are fixed before either is known) — that is a
  clean error. Before Aug 17 the whole shape was a PARSE error, so this
  is SUSPECT in older builds; decimals were the workaround.
  HEX device-register masks (`0x20`, `0x301`) stay hex —
  they mirror datasheet fields and carry a bit comment instead.
- **INTEGER OPERANDS MUST AGREE, and only bare literals promote (design
  195).** All typed operands of an operation have the SAME type: a binary
  operator, a comparison, a compound assignment or a range over two
  integers of different WIDTH — or the same width and different
  SIGNEDNESS — is a clean error naming both types and the ways out.
  ```saw
  n * 2      // fine at every integer type: a bare literal adopts
  n * -2     // also a bare literal — the `-` is not a suffix
  n * 2i16   // error on an `Int n`: a suffixed literal is exact-typed
  i + u      // error: `Int` and `UInt` are two types
  i < u      // same — and this is the one that silently answered wrong
  ```
  No promotion ladder: an operation has two peers, and picking a winner
  between them would silently decide whose reading the program runs
  under. The SHIFT COUNT is exempt (`flags << shift` at any two types) —
  a count is not a peer, and `<<=`/`>>=` follow. `Float` beside an
  integer is refused too; write the float literal.
- **VALUE-BRANCH ARMS ARE TRANSFERS (design 195).** Each arm of a value
  `if`/`match`, and each operand of `??`, takes the rule a `return`
  takes: a lossless widening is free (same-sign up, unsigned into
  strictly wider signed), anything else is refused.
  ```saw
  func f(a: Int) -> Int { if a > 0 { 11 } else { 7i16 } }  // f(-3) is 7
  func g(a: Int) -> Int { if a > 0 { 11 } else { 7u64 } }  // error: no
                          // common type — neither widens into the other
  ```
  The merged type is the arm every other arm widens into, and each arm
  extends by its OWN signedness. Two distinct FIXED widths still do not
  merge (they convert nowhere implicitly), and bare literals adopt in
  arm position, so the same arms at `-> Int16` need nothing written.
  Treat a mismatched-width value `if` as correct now and SUSPECT in
  older builds: it used to hand back the then-arm's value on both paths.
- **A CONVERSION IS WRITTEN EVERYWHERE — there is no position exemption
  (design 205).** A PLAIN transfer takes the same rule the arm takes: a
  lossless widening is free, a narrowing or a same-width sign change is
  one of design 170's three spellings, written where the value lands.
  ```saw
  let n: Int = 300
  let b: Int8 = n          // error: cannot assign `Int` to `Int8`
                           // hint: `as Int8` / `Int8.from(...)` /
                           //       `Int8.from(truncating: ...)`
  let u: UInt = 7
  let i: Int = u           // error: same rule, the sign-flip axis
  let wide: Int = u32val   // fine: a lossless widening decides nothing
  ```
  The positions, all of them: a `let`/`var` initializer, an assignment
  RHS, a call argument, a `return` and a body's TAIL, a struct field, an
  enum payload, an array / tuple / `Vector` / `Map` / `Set` element, an
  optional slot, a default parameter value, a `static` initializer.
  BARE-LITERAL ADOPTION IS UNTOUCHED (`let a: Int8 = 42` needs no suffix
  and no conversion, at every position on that list) — that is what the
  closed permission existed for. Treat all of it as caught now and
  SUSPECT in older builds: `let b: Int8 = n` on an `Int` holding 300
  printed 44 and `let i: Int = u` on `UInt.max` printed -1, silently, at
  every one of those positions. The migration is mechanical — say which
  you meant: `as` when an out-of-range value would be a BUG,
  `from(truncating:)` when the wrap was the point, `from` + handling when
  the input is untrusted.
- A FLOAT literal needs a digit on each side of the point (design 161):
  `1.5` yes, `7.` no (a parse error naming `7.0`). A `.` that no digit
  follows ends the number, so `7.to_string()` is a method call on the
  literal `7` and `1..=9` is a range. No exponent form exists — `7e5` is
  `7` followed by the identifier `e5`.
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
  **A BINARY EXPRESSION DOES NOT WRAP unless brackets already enclose it**
  (DF-172d) — neither spelling works, so reach for parentheses:
  ```saw
  let d = base | VALID | PAGE
        | AF | UXN            // error: Unexpected token: PIPE
  let d = base | VALID | PAGE |
          AF | UXN            // error: Unexpected token: NEWLINE
  let d = (base | VALID | PAGE
           | AF | UXN)        // OK — the newline is inside `(`
  ```
  Hits hardest when OR-ing named bits into a hardware descriptor, which is the
  most common long line in a driver.
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
THREE WORDS, one job each (design 219). **`Copy`** is THE silently-copyable
tier: trivial/POD (bitwise) and the refcounted family (String, Arc, Data,
escaping closures — a free bump) are one tier, and which of the two a type uses
is a codegen detail no rule above it sees. It is DERIVED, not declared — see the
automatic tier below. **`NoCopy`** (File, Mutex, Box, StringBuilder,
TcpListener/TcpStream, Command, TaskGroup, SpinLock, Once, Atomic — and
currently Map/Set: their `ExplicitCopy` is future work, `.copy()` on them is a
compile error) is the declared opt-OUT: `move` only. **`ExplicitCopy`** is an
ordinary synthesizable trait naming the DUPLICABLE family — every `Copy` type
satisfies it, plus the declared conformers (Vector, whose conformance is
bounded `T: ExplicitCopy`). A type declaring `ExplicitCopy` and nothing else is
move-only: `move v` or `v.copy()` at every transfer.
The two bounds differ: `<T: Copy>` admits only what duplicates silently,
`<T: ExplicitCopy>` reads "duplicable, possibly with ceremony" and is what
licenses a spelled `.copy()` on an abstract `T`. An `ExplicitCopy` argument
does NOT satisfy `T: Copy`. Declaring BOTH on one type is a COMPILE ERROR —
they require the same `copy(&self) -> Self`, so the second conformance
redefines it (``method `copy` is already defined for struct `T` with an
indistinguishable signature``). Declare `Copy`; it already satisfies
`T: ExplicitCopy`.
**`NoMove` is a SEPARATE AXIS (design 188)** — relocation, not duplication. A
`NoMove` value moves exactly once (constructor into binding): `move x` and
`Optional.take` of one are compile errors, whole-referent replacement through
`&var` stays legal, and it REQUIRES a declared `NoCopy` beside it (`extension
TaskGroup: NoCopy {}` + `extension TaskGroup: NoMove {}`; declaring it on a
Copy-tier type is an error). Containment is a DECLARED cascade — a struct
holding one says both words itself, or holds it behind a `Box` for a movable
handle over pinned storage. Not a generic bound. `TaskGroup` conforms: a group
is a SCOPE (design 124) whose Deinit joins where it was born, so `move group`
used to compile and abort in the runtime.
**`Data` MOVED OFF the NoCopy list (design 165)** and is now the COPY-ON-WRITE
member of the Copy tier: a `Data` is a window (offset + length) onto
`Arc`-owned storage, `let b = a` and `a.copy()` are retains, and the bytes
separate at the first write that finds them shared. Value semantics hold — no
mutation is ever visible through another `Data` — so `move` on a `Data` still
works but is no longer required anywhere. Three things to know:
- **Every mutation takes one uniqueness gate.** `set` used to write THROUGH
  shared storage while `push`/`append` copied first; it no longer does. A byte
  set through a slice-sharing `Data` is invisible to the slice.
- **`slice()` is O(1)** (a retain, narrower window) and `copy()` is lazy;
  `detached()`/`try_detached()` are the EAGER spelling, sized to `len()`, for
  when a small slice would otherwise pin a large buffer. (`try_copy` is gone —
  `try_detached` is it, under a name that says which one can run out of memory.)
- **`d[i]` READS free and WRITES with a gate** (design 179). The accessor is
  `&self`, so a read works on a `let`, a `&Data` param, or a slice several
  `Data`s share, and separates nothing; a write opens an exclusive window, so it
  needs a `var` root and the first one on shared bytes copies. One declaration
  does both because the uniqueness gate sits under `#lend_var` (see Places), so
  it is IN the exclusive specialization and simply absent from the shared one.
  `d.get(i)` is the `None`-returning twin of a panicking `[]`, nothing more.
The gate itself is `Arc.with_unique(body:) -> R?` — runs `body` on a `&var`
borrow of the payload when the handle is the only strong owner, `None` when
shared (Arc's `&self` payload forwarding still refuses `&var self` methods).
**A struct that OWNS one of those must pick its own copy policy** — the #1 thing
you hit writing Saw. `struct Holder { v: Vector<Int> }` does not compile bare;
the compiler knows how to DESTROY it but not whether you want it duplicated:
```saw
extension Holder: NoCopy {}                     // move-only (usually what you want)
@synthesize
extension Holder: ExplicitCopy {}               // memberwise deep .copy()
```
Both bodies are EMPTY — the `deinit` is synthesized either way. Only the copy
policy is your call.
**THE AUTOMATIC Copy TIER (design 159) — the other half of that rule.**
A struct or enum whose owning members are all trivial/Copy IS
Copy, with no declaration written and none owed. Its copy RETAINS each
refcounted member; the last owner's drop releases each exactly once. So
`struct P { name: String }` compiles bare and `let b = a` is a free retain that
leaves both live — this is deliberate and stays implicit.
```saw
struct Ticket { code: String }   // no policy declared, and none is owed
let b = a                        // free retain; `a` and `b` are both live
```
What puts a type on this tier WITHOUT owing a declaration is the member set the
compiler retains for you: a `String` field, an escaping-closure field, a `[T; N]`
of either, and another struct/enum already on this tier. A field of a DECLARED
Copy type is NOT one of them — an `Arc<T>` field triggers the ordinary
containment error (``contains Copy field `tag` of type `Arc<Res>` but
does not implement Copy``), so `Arc` in the tier list above means Arc
ITSELF, not a struct holding one.
Declaring the STRICTER `NoCopy` on such a type is legal and is the
API-discipline escape hatch — `extension Ticket: NoCopy {}` makes a type that
could copy for free move-only instead. Ceremony stays where a real choice
exists (ExplicitCopy vs NoCopy for a `Vector`/`File`/`Box` member); between
"bump a refcount" and "don't copy at all" there is none, so you are not asked.
**ENUMS PICK A POLICY TOO** (design 139) — an enum carrying an ExplicitCopy or
NoCopy payload declares one exactly as a struct with such a field does; a bare
one is the same error. Same two spellings, same empty bodies:
```saw
enum Reel { case Loaded(t: Tape), case Empty }   // Tape is NoCopy
extension Reel: NoCopy {}
enum Bag { case Full(t: Vector<Int>), case Empty }   // Vector<Int> is ExplicitCopy
@synthesize
extension Bag: ExplicitCopy {}   // copy() over the ACTIVE variant's payload
```
**A HAND-WRITTEN `copy()` IS THE RETAIN HOOK, AND MUST BE `sync`** (design 219).
A `copy()` body inside a Copy/ExplicitCopy conformance is called at
transfer sites no source construct names, so a suspending one is refused AT the
conformance ("a copy-policy `copy()` runs at compiler-inserted call sites and
must be `sync`"). You need not write `sync` — a body that never suspends
already passes, which is how std's own hooks (`Arc`, `Channel`) do. What the
compiler does not check is the rest of the contract: a hook it inserts
everywhere should be cheap and infallible, and a heavy one costs on every
silent transfer.
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
A TUPLE has `.copy()` on the same terms: it exists unless some element is
move-only, and each element copies at ITS OWN tier (`String`/`Arc` retains,
`Vector<Int>` gets its own buffer, trivial is bitwise, a nested tuple recurses).
`var (a, n) = t.copy()` destructures the copy; `u.0.push(x)` on the copy works
too (a tuple element is a place — see Collections).
A `(File, Int)` is refused naming the element: ``element 0 of type `File` is
NoCopy``.
**`Deinit` is NOT declarable** (design 131): `extension T: Deinit {...}` is a
compile error naming the three policies. A hand-written `deinit` body goes
INSIDE the policy conformance (`extension Res: NoCopy { func deinit(&var self)
{...} }`) — the requirement is inherited, so that is the only spelling. A type
declaring just `Deinit` had a `deinit` and no transfer rule, so `let s = r`
silently aliased it and both halves ran deinit. `T: Deinit` as a generic BOUND
is still fine.
```saw
var w = move v         // v now invalid (use-after-move = compile error)
var u = w.copy()       // explicit duplicate
```
- `move` works on ANY type and retires the binding; a moved `var`
  revives on reassignment.
- **Returning an owned container is `move v` — in `return` position AND
  as a bare tail expression.** The single most common function shape:
  ```saw
  func collect() -> Vector<Int> {
      var v = Vector<Int>()
      v.push(1)
      return move v      // or `move v` as the tail — same rule
  }
  ```
  A bare `v` there is the ExplicitCopy/NoCopy read error ("use .copy()
  ... or `move`") — and note the error anchors at the function
  declaration line today, not the tail expression (a known diagnostic
  wart, dogfood wave 1).
- NO partial moves (`move p.x` is an error) — move whole bindings.
- References `&T`/`&var T` are PARAMETER-ONLY, cannot escape/be
  stored. **A RETURN TYPE MAY NOT NAME ONE** — `-> &T` is a compile error at the
  declaration, in every position a return type is written (`func`, extension
  method/`init`, trait requirement, `extern func`, and the function TYPE
  `(Int) sync -> &Int`), reading what the type NAMES rather than its outer
  spelling (`(Int, &Int)`, `&Int?`, `Vector<&Int>` are refused too; the walk
  stops at a nested function type, whose PARAMETERS take references
  legitimately). It used to compile:
  `func dangle() -> &Int { let local = 99  return &local }` ran and printed out
  of a dead frame. Two ways to write what you meant — return the VALUE, or lend
  the STORAGE with a `borrows` accessor (Places, below), the sanctioned way to
  hand out a place. Reference PARAMETERS are untouched.
  **FOUR MORE POSITIONS REFUSE ONE (DF-163d + design 188)**, each where it is
  written, all on the same NAMES walk and with the same two outs: a struct FIELD
  (`struct Holder { r: &Int }` — refused at the field, which closes
  `Holder(r: &x)` with it, since a struct literal is not a call argument); an
  ENUM CASE PAYLOAD (`case Held(r: &Int)` — storage on a field's terms, and the
  hole a one-case enum used to route the whole rule around, straight into
  `Vector` storage); a
  GENERIC ARGUMENT in either spelling (`let v: Vector<&Int>`, `idn<&Int>(&x)` —
  refused at the argument, because `v.push(&x)` into it IS a genuine call
  argument); and a closure's INFERRED return (`{ &x }` typed `() -> &Int` — a
  closure literal writes no return type, so the check runs at inference and
  anchors on the tail expression). The `with_ref` identity closure `{ e in e }`
  is fine: reading a reference binding yields the VALUE, so it returns `T`.
  A bare `&` anywhere else that is not a call argument — bound to a `let`/`var`,
  an operand, a literal element — is refused too.
  **THREE MORE, from the position matrix (design 193)**: a `static`
  (`static SLOT: &Int` — the longest-lived storage there is), an
  ASSOCIATED-TYPE assignment (`type Item = &Int`, which is what every use of
  `Item` resolves to), and a generic parameter's DEFAULT
  (`struct Holder<T = &Int>` — substituted before mangling, so it fills every
  `T`-typed field with no argument position ever written).
  **A `type` ALIAS IS NOT A WAY PAST ANY OF IT (design 188)** — the walk resolves
  aliases first, so `type R = &Int` is refused in a field, a payload, a generic
  argument (`Vector<R>`) and a return, and so is the back-conversion `R(&x)` that
  would have inhabited them. A PARAMETER stays legal: the walk never ran there.
  **ONE CROSSING (DF-163f): `(&x) as UnsafePointer<T>`** (and the const twin) is
  legal in ANY expression position — argument, local binding, return expression,
  and the chained `(&self) as UnsafePointer<TaskGroup> as Int` token idiom. It is
  the only address-of the language has, and it crosses into the UNSAFE TIER
  rather than escaping: a pointer survives the expression, not a reference, and
  the `unsafe` effect it forces onto every signature naming it is the fence. The
  target must BE a pointer type — `(&x) as Int` is refused like any other bare
  `&`.
  Call sites mirror the sigil: `f(&x)` / `f(&var x)` (and `x`
  must be `var`). Mutate through `&var` via compound assignment, methods, or
  whole-referent REPLACEMENT `x = v` (design 110 — uniform across functions,
  `&var self` methods via `self = v`, and closures; the caller's binding
  stays valid).
  `x = v` is legal exactly when `v` type-checks as `var x: T = v`: the RHS takes
  the ordinary transfer checkpoint (fresh temp needs nothing, Copy copies,
  ExplicitCopy/NoCopy need `move v`/`.copy()` — the `move` consumes the CALLEE's
  local); the old referent deinits once and the new value installs, caller's
  binding stays valid. STILL banned: `x = v` through an immutable `&T`
  (read-only); `move` OUT of a ref. EXCLUDED: a `&var any Trait` ERASED referent
  (the slot's concrete type is unknown — specific error points at Box) — but a
  `&var Box<any Shape>` referent IS sized, so `b = Box<any Shape>.make(Square(..))`
  swaps the payload. Generic `&var T` works per instantiation (the RHS must BE a
  `T`). A bare trait name behind a ref (`&Shape`/`&var Shape`) is unsized — write
  `&any Shape`/`&var any Shape`.
- **NO LOCAL REFERENCES → EXTRACT A FUNCTION (the idiom).** Because a
  reference cannot be bound (`let r = &foo.bar.baz.arr` is not a form), a long
  body working on a deep place re-spells the whole chain at every use —
  `foo.bar.baz.arr[0]`, `foo.bar.baz.arr.len()`, again and again. The intended
  shape, not a workaround: extract a helper that takes the place by reference,
  so the chain is spelled ONCE at the call site and the helper works through
  the parameter:
  ```saw
  func drain(arr: &var Vector<Job>) { ... arr.len() ... arr[0] ... }
  drain(&var foo.bar.baz.arr)
  ```
  The same move serves a NoCopy place you cannot bind (a `TomlSection` off
  `doc.section_at(i)` re-opened at every read): pass the OWNER by reference
  plus the index and do the lookup once inside the helper. Signals to split: a
  function past ~60 lines, or the same 2+-hop chain spelled 3+ times. The
  borrow lasts exactly the call, so exclusivity stays easy to see — and the
  helper gets a name, which is what the chain never had. (Design 212 swept
  std + blade for exactly this; the taskgroup executor's repeated
  `g[0].<field>` fetches and blade's `section_at` re-opens were the found
  cases.)
- Law of Exclusivity: one `&var` XOR many `&` to overlapping paths,
  statically checked. The receiver's SPELLING does not matter — a call through
  an `&any Trait` existential or an opaque `&T` under a bound is checked exactly
  as a concrete one is, in the generic body, before any instantiation.
  **AN ASSIGNMENT IS A WRITE OF ITS TARGET (design 193)**, and its RHS runs
  first, so the RHS may not borrow an overlapping path: `p.x = bump(&var p)` is
  refused (whatever `bump` wrote through the borrow would be overwritten),
  while `p.x = shift(&var p.y)` (disjoint) and the accumulator idiom
  `acc = combine(move acc, e)` (a `move`, not a borrow — the assignment revives
  the binding) both compile. The `p?.x = ...` chain spelling has always been
  refused; the plain one now agrees.
  **A NESTED CALL'S REFERENCES JOIN THE OUTER CALL'S ACCESS SET (design 199)** —
  an argument's borrow extends over the whole call EXPRESSION, so a `&`/`&var`
  written inside a call in an argument list meets the same disjointness test as
  the arguments beside it:
  ```saw
  sink(&var p.a, reset(&var p))          // error: both reach `p`
  p.total(reset(&var p))                 // error: the receiver is in the set
  combine(bump(&var n), scale(&var n))   // error: neither ref is at the top level
  add(&var x, bump(&var y))              // ok: distinct roots
  scale(&var p.b, bump(&var p.a))        // ok: disjoint PATHS, as ever
  ```
  The receiver one is the sharpest: a `&self` receiver arrives BY VALUE, so
  whether its copy is taken before or after `reset` writes was argument
  evaluation order (it printed the pre-reset total). Hoist the nested call into
  its own `let` and the two borrows are in separate statements. Only the access
  SET widened — the path test is untouched, so nothing disjoint changed. This
  compiled on every tier unless a place window happened to be open (188 covered
  that half), so treat the shape as caught now and SUSPECT in older builds.
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
  `&var` argument opens an exclusive one, out of ONE declaration. A SHARED
  window lends the element READ-ONLY (`&T`), so a write inside one is a compile
  error (design 176 — before that the window was `&var` whichever flavor was
  picked, and a misclassified use site wrote through it silently). Window extent
  = the smallest expression that turns the place back into a value; windows
  NEST (`b[0][1].n += 1` is two, epilogues LIFO) and a nested WRITE makes every
  containing window exclusive too, so an immutable root is refused by NAME. A place borrow charges its
  ROOT, so `v.push(x)` inside a window is a compile error (invalidation-proof
  by the Law of Exclusivity, not by a closure scope) and so is swapping two
  elements through two windows (`v.swap(i, j)` is the method for that).
  **THE ONE POSITION THAT MAY NAME THE ROOT IS AN ASSIGNMENT'S RHS** — `v[0].n =
  v.len()`, `h.at().n = h.count()`, and even `v[0].n = v.pop()!.n`, because a
  right-hand side is defined to run BEFORE its target, so the compiler lifts it
  out of the window and the two accesses become two statements (DF-218j, widened
  to plain reads by DF-248a). Everywhere else the root stays refused —
  `v[0].bump(by: v.len())`, `print("{v.len()} {v[0]}")`, `v[0] == v[1]` — because
  an argument and a body read run AFTER the accessor's prologue and lifting one
  would reorder the program; write the `let` yourself there. The diagnostic
  (``cannot read `v` from inside a place window opened on it``) spells the
  asymmetry out, since nothing on the page distinguishes the two.
  **TWO BY-REFERENCE ACCESSES TO ONE ROOT IN ONE CALL, at least one a place,
  are an EXCLUSIVITY ERROR on every copy tier (design 188)** — two windows
  (`setboth(&var p.at(0), &var p.at(1))`) or a window beside a `&var` of its
  root, including one created by a NESTED call in the same argument list
  (`sink(&var p.at(0), reset(&var p))`), because a window's extent is the whole
  call. (Design 199 dropped the place precondition from that last clause — a
  nested call's references join the access set with or without a window; see the
  Law of Exclusivity entry.) Until 188 this compiled on a free-copy receiver
  and BOTH WRITES WERE
  LOST (std `Data` corrupted); what refused it on Vector was the copy policy,
  not the Law. Separate statements are the fix. Untouched: one window, windows
  in separate statements, a window beside a shared read of a DISJOINT path,
  nested windows, and plain fixed-array `a[0]`/`a[1]` (not an accessor).
  **THE LENT PLACE IS ROOTED IN THE RECEIVER (design 188)** — `lend <local>` /
  `lend <param>` is a compile error (reads were sound, writes vanished:
  `c.slot() = 99` was a silent no-op), `&var` params included. A match-arm
  payload of a receiver-rooted scrutinee counts, and so does an INDIRECTION out
  of the receiver (`if let buf = self.buffer { lend buf[i] }` — the receiver's
  own heap, which is how std Vector/Data are written); `lend buf` whole does not.
  **FOUR SPELLINGS WRITE THROUGH A PLACE** (design 176), all meaning "replace or
  mutate the storage the container already holds, where it sits": `v[i] = fresh`
  (unconditional lend), `m[k]! = fresh` (forced conditional lend — panics on
  absent, the `!` being the panic spelling of `?` exactly as for a read),
  `c.slot(i) = fresh` (NAMED accessor), and `m[k]?.field = v` /
  `v.get(i)?.field = v` (chain assignment — the head lends, an absent head
  writes nothing and evaluates no RHS, types `Void?`). Each opens an EXCLUSIVE
  window, so each needs a `var` root. A method call is an assignment target only
  when it lends a place; anything else is refused naming the method. Fence: a
  second `?` hop past the lend (`m[k]?.a?.b = v`) is not supported — bind first.
  **`borrows -> T?` is the CONDITIONAL lend**: each path either `lend`s or
  plainly `return None`. The absent path opens NO window and runs NO epilogue —
  `if let x = d.at(i)` sees `None`, and `d.at(i)!.m()` panics (the `!` is the
  promise the window keeps). `lend` may not be in a LOOP, so a body that has to
  SEARCH splits in two: a plain function finds the index, the accessor lends it
  (`libs/toml`'s `_section_index` beside `section`). VALUE READS out of a place
  follow design 131's table: retain for Copy, clean error for
  ExplicitCopy/NoCopy naming `with_ref` / `swap_out`.
  **MOVING A LOCAL INTO A WINDOW WORKS** — `slots[0].push(move h)`,
  `bag.at().take(r: move h)`, and the same shape through
  `with_ref`/`with_var_ref` all consume `h` once. The window is a closure, and a
  `move` capture into a NON-ESCAPING closure transfers WHEN THE BODY RUNS: the
  environment holds a pointer to the local, and the body takes the value as it
  starts. So a conditional lend whose absent path skips the body leaves `h`
  alone and it deinits at the end of its own scope, and a body that took it and
  did not move it on deinits it at the body's end. Refused until Aug 24
  (DF-218h — ``cannot copy value of type `Res` which implements NoCopy``,
  anchored at a receiver that copies nothing), so distrust the shape in an older
  build, where the workaround was to move into a plain local first. An ESCAPING
  closure keeps the creation-time transfer, and a body that moves ITS capture
  out still double-frees there (DF-255a) — pass the value as a parameter
  instead.
  **An arm of a borrowing `match` may LEND ITS PAYLOAD BINDING** (design 146,
  DF-146d) — how a slot-enum container gets an accessor at all:
  ```saw
  match self.slots[i] {
      case Filled(_, r) -> { lend r },      // the payload, where it sits
      case Empty -> { return None }         // the conditional lend's absent path
  }
  ```
  Tag stability is free: the window borrows the scrutinee's ROOT, so the Law of
  Exclusivity freezes the enum (discriminant included) for the window's whole
  extent. The scrutinee must be storage reached through the receiver
  (`self.slot`, `self.slots[i]`, another place off `self`); matching a value the
  body just BUILT is a clean error, since that payload dies with the accessor.
  **`#lend_var` (design 179) lets the BODY see the flavor** — a compile-time
  constant, legal only in a `borrows` body, `false` in the shared
  specialization and `true` in the exclusive one. It exists for copy-on-write,
  which must separate shared storage before lending a writable place and must
  not separate for a read:
  ```saw
  public func [](&self, index: Int) unsafe borrows -> UInt8 {
      if index < 0 || index >= self.length {
          panic("Data.[]: index out of range: {} (len {})", index, self.length)
      }
      if #lend_var {                      // the exclusive copy only
          if not self._make_ready(self.length) { panic("Data.[]: allocation failed") }
      }
      let bytes = self.byte_ptr() as UnsafePointer<UInt8>
      lend bytes[index]
  }
  ```
  The accessor compiles TWICE and the gated branch is REMOVED from the shared
  copy, not skipped in it — which is why that copy is honest `&self` code a
  `let` root may call. It PRUNES as the condition of an `if` STATEMENT (`not`,
  `&&`, `||` fold with it); anywhere else it is a plain compile-time `Bool`.
  Clean errors outside a `borrows` body and in a `&var self`-DECLARED accessor
  (always true there — declare `&self` to get both). An accessor that never
  names it compiles once, exactly as before. Gate placement is yours: in a
  `borrows -> T?` the prologue runs on the ABSENT path too, so a gate above the
  presence test separates on a MISS — put it below.
  v1 fences: a borrows body is `sync` (a window never spans a suspend —
  `with_ref`/`with_var_ref` stay the long-window spelling), no borrows function
  VALUES or existentials, no trait requirements, no way to declare an accessor
  SHARED-ONLY (the flavor is always the use site's — which is why `Set` gets no
  element accessor: a write would change an element's hash), and a borrows body
  cannot FORWARD another conditional place (`lend other.get(k)!` is not
  expressible — split the search out and lend your own storage instead). A body
  that DOES forward an unconditional one (`lend other[i]`) reaches the inner
  accessor EXCLUSIVELY whichever specialization is running, so a shared read of
  a nested CoW buffer copies — sound, but worth knowing.
- Deterministic LIFO destruction (`Deinit` trait); never call
  `deinit()` manually. You almost never WRITE one either (design 128): any
  struct/enum owning something gets a memberwise `deinit` synthesized — fields
  dropped in reverse declaration order, enums dropping the active variant's
  payload — with no declaration needed. Hand-write `deinit(&var self)` only for
  a raw resource (an fd, a mapping); your body runs FIRST and the field drops
  are appended, and there is only ever one deinit per type. Corollary: an empty
  `func deinit(&var self) {}` is dead code — delete it.
  **REVERSE-DECLARATION IS THE RULE FOR EVERY TEARDOWN, DISCARDS INCLUDED**
  (DF-218y, ruled Aug 22). The fields a pattern throws away with `_` come apart
  in the same order the ones it names do: `case Trip(v, _, _)` releases `c` then
  `b`, and so do `let (_, _, _) = triple` and its `if let` / `guard let` twins.
  So which fields a pattern happens to NAME never changes the order the rest
  come apart in. Two inline discard loops walked FORWARD until the ruling — the
  match lowering's (sync only, which is what made it disagree with its own
  driven twin, whose whole-value release goes through the synthesized deinit)
  and the destructuring `let`'s (both twins) — so distrust a multi-field discard's
  order in an older build. Only the ORDER moved; nothing leaked either way.
- `let _ = expr` = true discard (consumes + drops immediately). It is also the
  REQUIRED spelling for dropping a `Result` (design 151, Errors below).

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
  stack buffer. `N` is a compile-time constant (literal, const arithmetic, a
  const generic param, or a module `static` — see the SIZE-IN-ONE-PLACE idiom
  below); the value expression runs EXACTLY ONCE and is copied
  into every slot. `[0; 4096]` lowers to one zeroinitializer store (a memset);
  anything else splat-loops. Elements must copy for FREE — trivial or
  Copy — since there is nowhere to write the `.copy()` an ExplicitCopy
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
  get an error at a distance.
- Map/Set keys: `Hashable + Equatable` and copyable-with-retain
  (NoCopy keys rejected). A payload-free enum qualifies — it is a bare
  tag, so `Set<Color>` and `Map<Color, Int>` both work (design 132).
  Values unrestricted. Iteration order
  unspecified — sort `keys()` for determinism.
- Iterate: `m.each { k, v in ... }`, `each_key`, `keys()/values()`
  snapshots (Copy elements); `v.iter()`, `v.enumerated()` (for-in),
  `each`/`map<U>`/`fold<A>`/`each_indexed` closures; Set algebra:
  union/intersection/difference/is_subset (elements `T: Copy`).
- **Vector's four CLOSURE methods carry NO copy bound (design 216)** —
  `each`, `map<U>`, `fold<Acc>` and `each_indexed` lend the element as a
  `&T`, so a `Vector<File>`/`Vector<Job>` traverses, maps and folds like
  any other. Reading the binding yields the value, so `{ $0 * 2 }` and
  `{ $0.to_string() }` are unchanged; what needs the sigil is FORWARDING —
  a closure passing its element to another `&T` parameter writes `&n`.
  The closure is not `sync`, so a suspending transform works (the borrow
  spans the suspend; `&self` is held for the whole call, so exclusivity
  forbids the `push` that would reallocate under it). `iter`/`enumerated`
  KEEP `T: Copy` — `next()` hands out an element the consumer owns, which
  is a real copy at the source (design 122). `sort`/`sort_by` keep theirs
  too: the blocker was `Comparable` taking `other: &Self`, which design 239
  landed, so lifting the bound is design 216's remaining half rather than a
  dependency.
- A tuple index is a bare integer that never eats a following `.`, so a
  projection continues past it (design 161): `t.0.name`, `t.0.name.len()`,
  `pair.0.x`, and `t.0.1` as two index hops (not the float `0.1`). Works
  inside interpolation too (`"{t.0.name}"`). The old `(t.0).name`
  workaround is unnecessary now.
- **A tuple index is a PLACE, not a copy** (DF-151j) — the same storage a
  struct field names, and the write side works like one: `t.0.push(x)`,
  `t.1 += 1`, `t.0 = fresh` (whole-element write, old element deinits once),
  `t.0.field = v`, `f(&var t.0)`, nested `t.0.1.push(x)`, and the named
  spelling `pair.x.push(v)`. Mutability is the ROOT's, so `let t = (v, 7)`
  rejects all of them exactly as `let h` rejects `h.v.push(x)`. Exclusivity
  is by PATH like a field's: `f(&var t.0, &t.1)` is two disjoint elements and
  compiles, `f(&var t.0, &t.0)` is the violation. A value READ follows the
  copy tier (`let e = t.0` retains a Copy element, errors on an
  ExplicitCopy/NoCopy one). Until this landed every write through a tuple
  element was a SILENT NO-OP, so treat one as fine now and suspect in older
  builds.
- An ANNOTATED tuple literal is checked against its declared element types
  (DF-151l), so `let t: (Int?, Int) = (1, 0)` wraps element 0, `(None, 0)`
  types the `None`, and `let n: (Int8, Int) = (5, 1)` adopts `Int8` at the
  literal. Unannotated literals still infer element-wise.
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
while let job = queue.pop() { }      // DRAIN: one iteration per Some
```
- **`while let` IS THE DRAIN LOOP (design 233)** — `while let x = src.next() { … }`
  runs the body once per `Some` and falls out on the first `None`. The scrutinee
  RE-EVALUATES every iteration (that is what drains it) and `continue` is a jump
  to the head, so it re-evaluates too; a scrutinee reading a variable the body
  never changes loops forever, uncaught. Binding rules are `if let`'s, looped:
  the derived-shadow rule (`while let c = c.next()` is legal), the tuple pattern
  (`while let (k, v) = pairs.pop()`), the payload-read tier, and `while var` for
  a mutable binding. NO `else` clause exists (a parse error names
  `if let ... else`), and the loop produces NO VALUE — value position is a clean
  error. A `Result` source composes through `try?`
  (`while let m = try? f()`), which absorbs `Err` into termination — reach for it
  when "no more input" and "the read broke" want the same handling, and `match`
  the Result inside a plain loop when they do not. **THIS REPLACES the interim
  `while { guard let r = src.next() else { break } … }` spelling**, which buries
  termination in the body and, when a refactor loses the `break`, fails as a HANG
  rather than an error. (That spelling also MISCOMPILED over a suspension until
  DF-233a, so treat a pre-Aug-16 one as suspect.) The scrutinee may suspend, in
  a driven or spawned body; a TUPLE pattern over a suspending scrutinee is the
  same clean error `if let` gives.
- **An EXACT duplicate arm is a compile error**, reported at the second and
  naming the first's line — no input reaches it. Equality is textual after
  literal normalization (`case 10` and `case 0x0A` are one pattern), and an
  irrefutable hole is one pattern however it is spelled, so two `case _` arms
  and `case Move(x, y)` beside `case Move(a, b)` are both refused. RANGES and
  GUARDS are exempt and stay first-match-wins: `case 1..=9` ahead of `case 5`,
  or `case n if n < 0` ahead of `case n`, is the normal way to write overlap.
  Refinement is not duplication — `case Filled(0)` before `case Filled(n)` is
  two patterns. The enum spelling used to be an internal compiler error and
  the literal spelling used to compile and silently take the first, so treat
  a duplicate arm as caught now and suspect in older builds.
- String literal patterns compare by content. `true`+`false` exhausts
  Bool. Match on an OWNED enum consumes it (bindings own payloads):
  for a NoCopy/ExplicitCopy enum with owning payload, the scrutinee is
  moved-from afterwards — a second `match s` (or any later use) is a
  use-after-move error, exactly like a second `move s`. Matching
  through a `&`/`&var` binding or a place stays a borrow (no consume);
  keep an ExplicitCopy value with `match s.copy()`.
  A **Copy-tier enum is a BORROW instead**: each binding takes a retain
  of the payload and releases it at the arm's end, the scrutinee keeps its own
  reference and drops at ITS scope end, and matching one twice is fine. So an
  `Arc` payload's `strong_count()` reads one HIGHER inside the arm than outside
  it, and a value the arm hands out (`case Full(a) -> a`) is retained again on
  the way out, as every value read out of storage somebody else owns is.

## Errors
```saw
func parse(s: String) -> Result<Int, ParseError> {
    if bad { return ParseError(...) }   // auto-wrapped Err
    return 42                            // auto-wrapped Ok
}
record(42)                               // and in ARGUMENT position, same rule
let rows: Vector<Result<Int, String>> = [1, 2]   // …and every declared slot
// There is no `Ok(x)`/`Err(e)` to write: the wrap IS the construction. `T == E`
// is the one ambiguity, and it is a compile error — spell the variant then.
try! f()   try? f()   try f() catch { fallback }
try(as LocalError.Alloc) alloc(4096)     // ROUTE the error channel (design 234)
try { let a = try f(); let b = try g() } catch {
    match error { case ParseError(e) -> ..., case IoError(e) -> ... }
}   // multi-type: error is an ephemeral union (can't escape the catch)
func load() -> Result<Cfg, Box<any Error>> {   // erased: any error type
    let t = try read()      // concrete errors auto-box at the boundary
    ...
}   // catch binds the box; "{error}" prints via vtable
if err.is<IoErr>() { if let io = err.take<IoErr>() { retry(io) } }  // downcast
```
- **`try(as ErrorType.Case) f()` ROUTES the error channel (design 234 §3).**
  A `try` whose callee fails with a type your signature does not name spells
  the conversion, in a PREFIX clause:
  ```saw
  enum ConfigError { case Alloc(e: AllocError), case Parse(e: ParseError) }

  func build() -> Result<Config, ConfigError> {
      let buf = try(as ConfigError.Alloc) alloc_buffer(4096)
      let cfg = try(as ConfigError.Parse) parse(buf)
      let extra = try read_defaults()          // already ConfigError: bare try
      return assemble(cfg, extra)
  }
  ```
  The named case must carry EXACTLY ONE payload the callee's error fits —
  checked, done. No lifting trait, no candidate search, so editing an enum
  never changes what a distant `try` does. Rust's `.map_err(E::C)?` without
  the closure. The Ok value is untouched.
  PREFIX is load-bearing: `ConfigError.Alloc` and `time.Duration` are the same
  dotted shape, so a trailing clause would collide with design 63's projection
  of the unwrapped result — every trailing `as` stays an ordinary cast, and
  `try (f())` (a `(` no `as` follows) stays a parenthesized expression.
  `try!`/`try?` take NO clause (neither propagates), and a clause plus a
  `catch` on one `try` is refused — route or handle, not both. Inside a
  `try { } catch { }` block nothing is owed: the union absorbs the ROUTED
  type. Routing happens BEFORE propagation, so the routed type is what the
  suspending one-error-type fence counts — two callees routed into one domain
  enum are ONE type there, which is a new tool, not a new restriction.
- **DISCARDING A `Result` IS A COMPILE ERROR** (design 151) — the last silent
  drop in the language is closed. A failable call written as a bare statement
  throws away the failure it reports, so `stream.write(body)` alone is now
  ``result of `write` is `Result<Void, IoError>` and is silently discarded``.
  Consume it (`match`, `try`/`try!`/`try?`, or return it), or write the
  explicit discard:
  ```saw
  let _ = stream.write(body)   // best effort: the peer is already closing
  ```
  Covers EVERY implicit-discard position, not just bare statements: a `Void`
  body's TAIL expression (the parser makes a block's last expression statement
  the tail, so `func f() { g() }` is this case, not the statement case), a loop
  body's tail, and a statement-position `if`/`match` forwarding a branch value.
  The diagnostic anchors on the CALL, not the forwarding construct, so a
  statement-position `match` reports each arm at its own line. Keyed on the
  CHECKED TYPE, so an erased `Result<T, Box<any Error>>` and a suspending call
  need no special case; `try!`/`try` CONSUME, so the `T` they yield is free to
  drop unless `T` is itself a Result. **Result ONLY** — Optionals and
  everything else stay freely discardable (`m.insert(k, v)`'s old-value `V?`,
  a `Void?` `?.` chain statement). There is no must-use attribute: a Result you
  may always ignore should not have been a Result.
- **`main` RETURNS THE EXIT STATUS, and may return exactly four things**
  (design 221): `Void` (0), `Int` (the value), `Result<Void, E>` and
  `Result<Int, E>` (the `Ok` payload, 0 for `Ok(())`; an `Err` PRINTS the error
  and exits 1). Anything else is refused at the declaration — ``error: `main`
  must return `Void`, `Int`, `Result<Void, E>` or `Result<Int, E>`, but returns
  `String` ``. So a failing command-line program `return`s its failure instead
  of calling libc `exit()`:
  ```saw
  func main() -> Result<Void, IoError> {
      var config = try file.File.open(Path(s: "saw.toml"))
      let text = try config.read()
      print("read {text.len()} bytes")
      return
  }
  ```
  `E` must be renderable (`Printable`; `Error` refines it, and an erased
  `Box<any Error>` works through its vtable) — the Err path prints it the way
  `"{e}"` does. The status is POSIX-narrowed to a byte by the platform, so 300
  is observed as 44. `main` may SUSPEND at any of the four. Treat all of this as
  working now and SUSPECT in older builds: a suspending `main` used to drop its
  value and exit 0 whatever it returned, `-> Result` emitted a struct-returning
  `@main` against a C ABI expecting `int` (a stable, meaningless 138), and
  `-> String` exited with the low byte of a heap POINTER.
- **THREE TIERS, and your signature picks one (design 234 §1).** (1) A LEAF op
  returns the NARROWEST concrete type it can fail with — one failure mode, no
  compound (`push -> Result<Void, AllocError>`, and `AllocError` keeps the
  `size`/`align` so the site stays loggable). (2) A COMPOUND domain enum, with
  PAYLOAD-CARRYING cases, only where the sources genuinely mix — and it CARRIES
  the leaf rather than restating it (`case Alloc(e: AllocError)`, never a
  re-enumeration of its fields). A domain that cannot time out has no `TimedOut`
  case. Share case NAMES and payload TYPES across domains; never share a WRAPPER
  enum (a `ChannelError.Sys` would claim an in-process channel can fail because
  the OS said no, and every match would go two levels deep). (3) `Box<any
  Error>` is the APPLICATION aggregation tier and std never produces one — it is
  for a caller that does not care which error arrived. There is NO stdlib-wide
  errno-style enum, ever: its defining property is that every signature lies.
  Crossing between tiers is WRITTEN — `try(as LocalError.Alloc) f()`.
- **A FALLIBLE `init` IS `-> Result<Self, E>`, and that is the ONLY fallible
  form** (DF-245a, ruled + landed Aug 24). An `init` declares the RECEIVER —
  `Self`, the receiver written out (`Wrap<T>` inside `extension Wrap<T>`), or no
  return clause at all — or `Result<Receiver, E>`. The construction then carries
  the Result, so nothing at the call site is special:
  ```saw
  extension Config {
      init(budget: Int, ceiling: Int) -> Result<Config, ConfigError> {
          if budget == 0 { return ConfigError.Missing }
          if budget > ceiling { return ConfigError.TooLarge(bytes: budget) }
          return Config(budget: budget)      // Ok, by the ordinary auto-wrap
      }
  }
  let cfg = try Config(budget: n, ceiling: 4096)     // …or try! / try? / match
  let _ = Config(budget: n, ceiling: 4096)           // design 151 applies too
  ```
  The BODY is an ordinary Result body: a receiver value is `Ok`, an error value
  is `Err`, tail and `return` alike. Works on a generic receiver, a
  const-generic one, with default parameters, and across label-distinguished
  overloads. **NOT `-> Self?`** — refused at the declaration, because a `None`
  names no cause; the fixit points at the Result. Any other return type
  (`-> Int`, another struct, a `Result` whose Ok is not the receiver) is refused
  there too. Before Aug 24 every one of those was ACCEPTED and then miscompiled:
  the call site typed the construction as the receiver whatever was written, so
  a wrong return type was two types and the program died with an internal
  compiler error about LLVM IR. Two limits: an `init` body may not suspend (an
  ICE today, DF-251d), and a RENAMED generic extension's init parameters do not
  substitute at the call site (DF-251c).
- **`try!` PANICS WITH THE ERROR IT WAS HANDED** (DF-245b, Aug 22):
  `panic at FILE:LINE: try! failed: allocation of 64 bytes (align 8) failed`.
  The rendering is the alloc-free format path, so it survives an exhausted
  allocator and works freestanding, and an erased `Box<any Error>` renders
  through its vtable. `E` is not bounded `Printable` at a `try!`, so an error
  type with no conformance keeps the bare `try! failed` — which is the whole
  message every `try!` used to give, so a build that prints only that on a
  `Printable` error predates Aug 22. This is what makes `try!` a usable
  migration for a call site that does not want to handle a failure.
- **TWO PANICS ARE DOCUMENTED BOUNDARIES, not tiers to migrate** (user ruling,
  Aug 22). The ERASED-ERROR box: returning a concrete error at
  `-> Result<T, Box<any Error>>` allocates, and an error path cannot report an
  allocation failure without allocating, so the erasure panics — name your error
  type if you must not meet it. And `Data.[]`'s copy-on-write SEPARATION: the
  accessor rule governs a direct indexed accessor, so `d[i]` panics; the
  Result-returning preflight is `try_detached()`, which separates the buffer
  where a failure has somewhere to go.
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
- Optionals: `T?` — or `Optional<T>`, the same type under a written name
  (design 176). **`?` NESTS**: `Int??` / `String???` in every type position
  (annotation, param, return, generic arg, field, behind a `&`), and
  `Optional<Int?>` names that same type — this is what `Vector<Int?>.get(i)`
  yields, one layer for "no such element" and one for "the element is absent".
  `??` is also the coalescing OPERATOR and one token serves both: type position
  counts two layers, expression position stays the operator. They never collide
  — a type is otherwise followed by `=`, `,`, `)`, `>`, `{` or a newline —
  EXCEPT in an `as` cast target, where the operator wins (`x as Int? ?? y` is a
  cast then a coalesce). A bare value written into a two-layer slot
  (`let a: Int?? = 5`) lands intact at whatever depth the slot names, so naming
  the type and reaching one through a container (`let got: Int?? = v.get(0)`)
  are the same thing now. **`??` PEELS ONE LAYER, so its default owes the PEELED
  type**: on a `Vector<Int?>`, `v.get(9) ?? v.get(0)` is a clean error naming
  both types (the default is `Int??` where an `Int?` is owed). Write
  `v.get(9) ?? None` — a bare `None` adopts the payload type — or peel the
  default yourself. `None`, force `!` (panics), `??`, call-site auto-wrap
  (`f(5)` matches `f(x: Int?)` — and, since design 176, a generic parameter
  INSTANTIATED to an optional too, so `m.insert("y", 7)` on a
  `Map<String, Int?>` and `v.push(3)` on a `Vector<Int?>` both wrap),
  and full **optional chaining** `?.` (design 111):
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
  the payload). The COMPOUND spelling `x?.y += v` writes the same storage
  (design 227): the field is read, the operator applied and the result written
  back on the non-None path, and a None head runs neither the write nor the RHS.
  Every compound operator works, a place head does (`m[k]?.n += 1` writes inside
  the window), and the operand rules are the compound statement's — both integer
  operands agree, a bare literal adopts the field's width. It was a parse error
  until Aug 15, so treat it as working now and SUSPECT in older builds.
  A SUSPENDING hop works (design 120): `o?.read()` runs the hop only
  when every earlier hop is non-None, a multi-hop chain peels one hop at a time,
  and a chained assignment with a suspending RHS writes only on the non-None path.
  The COMPOUND spelling takes a suspending RHS too since design 224
  (`x?.n += s.read()` runs the read only on the non-None path, exactly as
  `x?.n = s.read()` does); it was refused until Aug 15, along with the plain
  `n += s.read()` it lowers through. Still rejected: a chained assignment
  through MORE THAN ONE hop whose RHS suspends (`a?.b?.c = s.read()` — `if let`
  the inner optional first). `?.` indexing is unsupported.
- **PAYLOAD READS ARE PLACES (design 131).** `o!`, the `??` left operand, and an
  `if let`/`guard let` binding all name storage the optional still owns, so the
  payload's copy tier decides the read — same table as everywhere else. BORROW
  (`o!.m()`, `&o!`, `o!.field`, a `?.` hop) is always free. A VALUE READ
  (`let a = o!`, a by-value arg, a return, an operand) is bitwise for trivial,
  a RETAIN for Copy (the optional keeps its own reference — so
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
  **`o.is_some()` / `o.is_none()` (DF-218a) read the TAG and nothing else** —
  no reference made, none taken, so the copy tier never enters into it and they
  work on a `File?` exactly as on an `Int?`. `&self`-shaped: no arguments, no
  mutable place, and a call result is as good a receiver as a local (its payload
  drops at the end of the statement, once). This is the core form the `_`-blessed
  presence test desugars to, so reach for it directly when the answer is a value
  you want rather than a branch you take.
  `if let a = move o` is the consuming binding. A WHOLE-optional read follows the
  same table since design 139 — the optional's tier IS its payload's, so
  `let y = x` retains a `String?` and is REFUSED on a `Vector<Int>?`/`File?`
  (`x.copy()` / `move x` / `x.take()`). A payload read out of a CALL RESULT
  (`v.get(0)!`, `if let x = f()`) is unaffected — that value is already yours.
- **INTEGER CONVERSION IS CHECKED (design 170) — three spellings, pick by
  meaning.** `x as UInt8` PANICS when the value has no representation in the
  target, by range OR by sign (`panic at FILE:LINE: cast to UInt8 out of range:
  1000`). `UInt8.from(x) -> UInt8?` is the partial twin — `None` when it does
  not fit, for input you do not control. `UInt8.from(truncating: x) -> UInt8`
  is the deliberate wrap: total, keeps the low bits (value mod 2^n), the
  cast-shaped sibling of `&+ &- &*`. The LABEL is the operation, so there is no
  boolean parameter.
  ```saw
  let n = read_len()
  let a = n as UInt8                    // panics if n > 255 or n < 0
  let b = UInt8.from(n)                 // UInt8? — None if it does not fit
  let c = UInt8.from(truncating: n)     // low 8 bits, on purpose
  ```
  Both `from` forms exist for EVERY source/target pair, total ones included
  (`Int.from(x: Int8)` is always `Some`), so a generic body can rely on the
  shape. WIDENING is untouched — same-sign widening, the identity, and unsigned
  to strictly-wider signed emit exactly one sext/zext and no check. A checked
  pair costs one compare and a branch. A CONSTANT operand is answered at
  compile time: `0xFF as UInt8` is free, `1000 as UInt8` is a COMPILE ERROR
  (const arithmetic and a raw-backed enum's case value fold too; a `let` local
  does NOT fold and takes the runtime check). GOTCHA: same-width sign flips are
  checked, so `-1 as UInt8` (255) and `255u8 as Int8` (-1) are no longer how you
  reinterpret a byte — write `UInt8.from(truncating:)` / `Int8.from(truncating:)`.
  That is the `Int8`↔`UInt8` idiom whenever C `char` bytes meet `Data`.
  A raw-backed enum's `e as Backing` stays TOTAL; narrowing BELOW the backing
  takes the ordinary rule. An alias projects to its underlying first, then these
  rules apply. Saturating is deliberately not offered.
  **AND THE RULE HAS NO POSITION EXEMPTION (design 205)**: the same conversion
  is written at every place a value lands in a new home, not only at a cast —
  `let b: Int8 = n` on an `Int` is the refusal above, and so is the same
  transfer at an argument, a return, a field, an element or a `static`. See the
  ownership section's transfer bullet; the platform `Int`/`UInt` pair was the
  last position that converted silently.
- `panic(msg) -> Never`; `assert(cond, msg)`. Overflow/bounds/shift/div-zero
  violations panic ALWAYS (wrap intentionally with `&+ &- &*`; an out-of-range
  integer CAST panics too — see above). EVERY panic —
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
  **AN INTEGER RENDERS AT ITS OWN WIDTH** (DF-238b, fixed Aug 22): an `Int64` /
  `UInt64` prints all 64 bits on a 32-bit target, and `print(v)`, `print("{}", v)`
  and a panic message naming `v` agree byte for byte at every width. Before that
  date the value was TRUNCATED to the platform word on its way into the renderer
  — `print("{}", 0x1234_0000_5678)` on riscv32 wrote 22136, its low word, with
  nothing said — so distrust a wide value printed by an older freestanding build.
  Invisible on a 64-bit host, where the two widths coincide.
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
  written `Box<any Error>` and its erased-error auto-wrap, a Copy
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
- **WHAT A GENERIC BODY REQUIRES IS INFERRED, and refused at the CALL (design
  219 wave C).** One question per type parameter: does the body ever duplicate a
  `T` with nothing written? If not — every use is a move — the body works at
  every type including move-only ones, which is the common case because the
  ordinary generic shape is forwarding. If it does, `T` must be on the `Copy`
  tier and each call site is checked against the argument you passed:
  ``error: `twice` requires `T` to be `Copy` — it binds `x` twice, at lines 2
  and 3; `Res` is move-only``. The requirement PROPAGATES through forwarding
  hops, and it covers generic methods (discharged against the RECEIVER's type
  args) and generic coroutines.
  - **Per PATH, not per mention.** `if a < b { b } else { a }` names each
    parameter twice and duplicates neither. But a read out of storage the body
    does not own — a field, a tuple element, an indexed place — is a duplicate
    however few times the name appears (no partial move exists).
  - **To duplicate on purpose: `<T: ExplicitCopy>` + a spelled `.copy()`.** The
    bound is required for wrapper receivers too — `(T, Int)`, `T?`, `[T; N]`
    and nestings all reach the same rule.
  - **A `public` generic must DECLARE it** (write `<T: Copy>`): an inferred
    requirement can tighten when the body is edited, which would break callers
    with no signature change. Private/internal generics ride inference.
    Declaring a bound the body EXCEEDS is also an error.
  - **Two declaration rules derive PER INSTANCE**: a container at a `NoMove`
    payload is `NoMove` (`Wrap<TaskGroup>` cannot move, `Wrap<Int>` can), and a
    generic whose instantiated signature names an unsafe type must be declared
    `unsafe`.
- **EVERY primitive takes a user conformance** (design 176): `Int`, `UInt`, all
  eight fixed-width integers, `Bool`, `Float`, `String`. `extension UInt8:
  MyProto { ... }` declares, dispatches directly (`b.encoded()`), and satisfies
  a generic BOUND (`<T: MyProto>` at `T = UInt8` — monomorphized, no vtable).
  That set used to be Int/Float/String only, with no rule behind the split.
  A primitive still cannot be ERASED to `&any Trait`/`Box<any Trait>` — an
  existential carries a vtable beside the value and a primitive has no boxed
  form — and that is one clean error naming the two outs: the generic bound, or
  a wrapper struct you own.
  **INSIDE THE BODY, `self` IS THE PRIMITIVE** (DF-225d, fixed Aug 22) — return
  it bare, do arithmetic on it, compare it, satisfy a bound with it. On the ten
  primitives design 176 added it was none of those until that date: the
  typechecker kept its own {Int, Float, String} copy of "which names are
  primitives" and 176 widened only the other two, so `self` was a STRUCT of the
  same name and every failure printed the two types identically — ``method
  `encoded` should return `UInt8` but returns `UInt8` ``, ``operator `*` cannot
  be applied to `UInt8` and `Int` ``, ``cannot compare `UInt8` with `UInt8` ``.
  Int, Float and String worked throughout, which is what made it look like a
  `UInt8` problem.
- **Generic type-arg inference (design 93 + 105) covers FUNCTIONS and METHODS
  only — CONSTRUCTORS do not infer yet.** `Arc(value: r)` / `Mutex(value: 0)`
  are errors demanding `Arc<Res>(value: r)` / `Mutex<Int>(value: 0)`; spell
  every layer in nested construction. (Ruled to change Aug 10 — design 207
  routes constructors through the same solver; until it lands, write the
  arguments.) For functions and methods: a generic free function or
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
  Copy/ExplicitCopy (`copy`), Equatable (`equals`), Comparable
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
- **`Self` works in an extension signature, at every position and on a GENERIC
  extension too** (DF-216f, DF-216r): a parameter, a return, and nested in
  either (`&Self`, `Self?`, `Vector<Self>`, `(Self, Int)`). Inside
  `extension Wrap<T>` it means `Wrap<T>` — the spelling you would write by
  hand.
- **AN EXTENSION MAY RENAME THE PARAMETER IT RE-DECLARES** (DF-216h, fixed
  Aug 21): `struct Pair<A>` extended as `extension Pair<U>` binds `U` to the
  receiver's argument at every position — a hand-written `&Pair<U>`, `Self` in
  any of its spellings, a field read typed by it, a static's parameters, a
  method-level generic beside it, a partial rename over two parameters, a
  bounded rename, and a generic enum's extension. Positional, as the
  re-declaration always was. Treat it as working now and SUSPECT in older
  builds, where NOTHING substituted: the call site refused with ``argument
  `other` expects `&Pair<U>` but got `&Pair<String>` `` and the body itself did
  not type-check against its own declaration (``method `firstval` should return
  `U` but returns `A` ``). Repeating the struct's own parameter names was the
  workaround, and is still the clearer spelling.
- **`equals`/`compare` TAKE `other: &Self` (design 239).** The right operand is
  a shared reference at every tier, which is what `==` `!=` `<` `>` `<=` `>=`
  have always passed. A comparison destroys neither operand, and a move-only
  type with a HAND-WRITTEN comparison is comparable:
  ```saw
  extension Tag: Equatable {                  // Tag is NoCopy
      func equals(&self, other: &Self) -> Bool { self.id == other.id }
  }
  a == b                     // fine, at every tier
  if not a.equals(&b) { }    // the direct call spells the borrow
  ```
  Two refusals fall out of the signature, both clean. A by-value `other` is a
  DECLARATION error (``parameter `other` of `equals` must be a reference``,
  with the fixit), and `move other` inside the body is the ordinary "cannot
  move out of reference". There is no tier condition, no transitive query and
  no `@synthesize` escape hatch to reach for — a synthesized body was only ever
  the way out because it could not consume, and now nothing can. The
  conformance rule is general: a conformance's parameters mirror the
  requirement's borrows, both directions, `&` against `&var` included.
  Calls spell the `&` at a concrete receiver and through a generic bound alike
  (`func differ<T: Equatable>(a: &T, b: &T) -> Bool { a.equals(&b) }`, which
  works at every conforming type including the primitives and `String`).
  ONE ASYMMETRY worth knowing: `String.equals`/`String.compare` keep a by-value
  `other`, because `String` conforms builtin rather than through a written
  conformance and those are its own API — so `s.equals("literal")` still works,
  where `&"literal"` could not (a literal has no address).
  Treat all of this as working now and SUSPECT in older builds, where the
  operand was by value: a hand-written body could `move` it and free a value
  the caller still owned, which the compiler answered by REFUSING the operator
  on ExplicitCopy/NoCopy operands (transitively, through fields, payloads and
  tuple elements) and did not catch at all on the Copy tier.
- **SERIALIZATION (design 169): `Serialize` / `Deserialize` over `Encoder` /
  `Decoder`.** Prelude-visible, both profiles. A value writes itself into a
  format-agnostic sink and reads itself back out of one. `@synthesize` DERIVES
  both directions — every stored field, declaration order, as one array:
  ```saw
  @synthesize
  extension Endpoint: Serialize {}
  @synthesize
  extension Endpoint: Deserialize {}

  try ep.serialize(to: &var enc)
  let back = try Endpoint.deserialize(from: &var dec)   // STATIC — on the TYPE
  ```
  The walk covers the integer types, Bool, String, Optional (absent -> null),
  Vector, RAW-BACKED enums (out via the raw value, back via the partial
  `from(raw:)`; an unknown value is `UnknownCase`, never a trap) and any member
  that itself conforms. Anything else is a clean error NAMING THE FIELD — write
  the body by hand. An enum with no raw backing is refused (its cases have no
  wire values). Hand-written bodies are the escape hatch for invariant-carrying
  types, exactly as with the rest of the family.
  EVERY serde signature is `sync` — serialization writes into a buffer, so it
  works inside a place window, under a SpinLock, and in a kernel. Do I/O on the
  buffer afterwards, not inside `serialize`.
  `deserialize` is a `static func` requirement returning `Self` (design 236
  put the keyword in the trait, where it was prose before), so `Deserialize`
  is a generic BOUND and never an `any Deserialize` (a static requirement has
  no receiver to dispatch on — clean error where you write the existential),
  and a hand-written conformance writes `static func deserialize(...)` too:
  the kinds must agree.
  `Serialize`/`Encoder`/`Decoder` ARE object-safe and travel behind `&var any`.
  Errors are Result: `DecodeError` carries the BYTE OFFSET it stopped at, and
  malformed input is never a panic. Counts are declared —
  `begin_array(count:)` is followed by exactly that many items, else
  `CountMismatch`. Narrow ints read back through `read_int_range`/`read_uint_max`
  (a narrowing cast would panic; the range is checked first).
- **THE FORMAT IS `std.cbor` (design 169 units 3+4)** — CBOR RFC 8949 in its
  DETERMINISTIC profile, import-required (`import std.cbor.{CborEncoder,
  CborDecoder}`), both profiles. Frozen contract: `sawc/std/CBOR.md`; golden
  blobs: `tests/cbor_vectors/` (32 accept + 20 reject, gating the Saw codec AND
  `tools/sawcbor.py` over `cbor2`).
  ```saw
  var enc = CborEncoder()
  try entry.serialize(to: &var enc)
  let blob = try enc.finish()          // CountMismatch if an item is still open

  var dec = try CborDecoder.open(bytes: move blob)
  let back = try LockEntry.deserialize(from: &var dec)
  ```
  Shortest-form arguments, definite lengths, map keys sorted by ENCODED BYTES,
  no floats, no tags, one top-level item — anything else is a DECODE ERROR, not
  a tolerated alias, so the bytes ARE the value. A struct is an ARRAY of its
  fields, never a map of names. `open` validates the WHOLE input first (limits
  `max_depth`/`max_size`/`max_items` are constructor params, hosted defaults
  64 / 16 MiB / 100000), walking an EXPLICIT work stack — depth is the stack's
  height, so a hostile blob never reaches the call stack and never panics.
  FLOATS ARE A DECODE ERROR in v1 (`Float` has no settled serialization).
  `encode<T: Serialize>(value:)` is the one-call write; there is NO `decode<T>`
  twin — name the type (`LockEntry.deserialize(from:)`), because a static
  requirement is not callable on a type parameter yet (DF-169e).
  `v[i].serialize(to: &var enc)` over a LOCAL encoder works — the element is
  reached through a place window and the encoder is borrowed where it stands.
  It was refused until Aug 22 (DF-169h: the window's body captured the local by
  VALUE, so a NoCopy encoder was ``cannot copy value of type `CborEncoder` ``
  anchored at the subscript), with "read the element out first" as the
  workaround, so distrust the shape in an older build.
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
  `FixedBuf<256>` — folded before mangling), and a module `static` counts as a
  constant there too (DF-172j: `FixedBuf<CAP>` IS `FixedBuf<16>` for a
  `static CAP: Int = 16`); defaults compose with design 37
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
  import std.fixedbuf.*
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
import std.task.*                                 // design 114: `yield_now` lives here
                                                  // (`import std.task` -> task.yield_now())
func work(n: Int) -> Int { yield_now(); n * n }  // any call may suspend
func main() {
    var group = TaskGroup()
    let a = group.spawn(work(3))
    print(a.join())        // structured join; group Deinit drains children
}
sleep(Duration.ms(200))     // cooperative; sync is the CHECKED negative effect
try! ch.receive()           // cooperative receive -> Result<T, ChannelError>
try! ch.send(1)             // ...and so do send/close (blocking twin: recv)
let _ = ch.close()          // the producer says it is finished; idempotent
handle.cancel(); if cancelled() { ... }   // cooperative cancellation
dump_tasks()                // every live task's logical backtrace (std.task)
```
- **`dump_tasks()` prints where every live task is PARKED (design 158)** —
  `import std.task.{dump_tasks}`. A suspended task is not on any thread's stack,
  so a native backtrace of a parked program shows the executor's poll loop and
  nothing else; this shows the frames, innermost first, with the real
  `file:line` of every suspending call between the task's entry point and its
  park:
  ```
  saw tasks: 2 live (unsynchronized snapshot)
    task group 1 slot 0 gen 1 io-parked
      at net.saw:412 in TcpStream.read
      at server.saw:18 in read_header
    task group 1 slot 1 gen 1 running
      at server.saw:41 in accept_loop
  ```
  `slot`/`gen` are the task's identity in its group's run queue (a generation
  advancing across dumps is a REUSED slot, design 134); the last word is why it
  is not running (`ready` / `sleeping` / `io-parked` / `running`). **THE PANIC
  PATH PRINTS ONE FOR YOU** — a program that dies with tasks in flight writes the
  dump after its panic line, and a panic with no live task prints exactly what it
  always did. Allocates NOTHING (a static table walk over a read-only table the
  compiler links into every binary, not an unwind), so it works under a denied
  allocator, freestanding, and inside a panic handler; under a debugger,
  `command script import tools/lldb_saw.py` adds `saw tasks` / `saw bt` /
  `saw table`. The MT walk is unsynchronized and says so in its header; an ST
  group is exact. GOTCHA: a RUNNING task's line is its last park point, not where
  it is executing — the `running` marker is the tell.
- **`sleep` takes a `Duration` and nothing else** (design 180). The bare-Int form
  is GONE — `sleep(200)` is now a clean error naming `Duration.ms`. `Duration` is
  PRELUDE (no import; `Instant` still needs `import std.time`), holds UInt64 whole
  nanoseconds, and is built by `Duration.ns` / `us` / `ms` / `secs` and read by
  `as_nanos` / `as_micros` / `as_millis` / `as_secs`. GOTCHA: the constructors take
  `UInt64`, so a literal is fine (`Duration.ms(200)`) but an `Int` variable needs
  the conversion stated (`Duration.ms(n as UInt64)`), which panics on a negative.
  A constructor whose argument would scale past the u64 nanosecond range (about
  584 years) panics naming itself. A cancel arriving while a task is ASLEEP is
  observed promptly now, not at the end of the nap (the executor idles in the
  reactor poll in every case, so the cross-thread wake reaches a pure-timer park).
- `func f(...) sync -> T` promises no suspension (checked).
- **`TaskGroup(threads: N)` IS A LIVE POOL (design 75 + 225).** N OS workers over
  a shared queue, started at the group's FIRST spawn and running until its
  `Deinit` — so a task spawned into a multi-threaded group starts at once and
  runs alongside the thread that owns the group, exactly as `Thread.spawn {}` and a
  cooperative group's tasks already did. `handle.join()` WAITS for its one task
  and leaves the pool running (three spawn-join rounds cost N threads, not 3N);
  `Deinit` lets the workers finish every live task and joins them. Until Aug 16
  it was FORK-JOIN — the workers existed only inside a `join()`/`Deinit`, so
  reading a value a worker was supposed to send, before joining it, hung at 100%
  CPU forever. Treat the live behavior as working now and SUSPECT in older
  builds. The delta to hold onto: MT order was never deterministic, and what
  widened is WHEN — a task's effects land at an unspecified point between the
  spawn and the join. `join()` is still a barrier for its task, `Deinit` for the
  group, and `TaskGroup()` / `threads: 1` stay single-threaded
  (byte-identical, deterministic interleaving). Into a multi-threaded group,
  every value a spawned frame carries across a suspension — params, across-suspend
  locals, AND the result type — must be `Send` (else a clean compile error naming
  it). An OWNING CONTAINER is Send iff its CONTENTS are, so moving a
  `Vector<Int>`, a `Map`, a `Set`, a `Data` or a `StringBuilder` in is fine and a
  `Vector` of closures is refused, naming the element. Share genuinely shared
  state via `Arc`/`Mutex`/`Channel`. Test MT
  code on counts/sums, NEVER on interleaving. Cross-task cancel:
  `handle.cancel_addr() -> Int` (a Send address a canceller task sets).
- **SHARING A TYPE THAT OWNS RAW MEMORY: two levels, one assertion each**
  (LANGUAGE_SPEC "A raw buffer shared across threads"). The pointer field does
  NOT poison the type — `Vector` is the precedent — so write the struct plain
  and mark only the methods that reach THROUGH it `unsafe`. LEVEL 1 (behind a
  lock): one `extension Buf: UnsafeSend {}`, owing four things (the memory is
  heap-only, nothing in the type is thread-affine, `deinit` is sound from any
  thread, no unsynchronized sibling reaches the same region) — and
  `Arc<Mutex<Buf>>` then composes mechanically, because `extension Mutex<T:
  Send>: UnsafeSync {}` ignites and `Arc<T: Send + Sync>` follows. LEVEL 2
  (atomics or a `SpinLock` INSIDE the type + `extension Buf: UnsafeSync {}`):
  for lock-free sharing and for the `static` position, since a static must be
  Sync and an interior cell is what blocks the derivation; the obligation is the
  WHOLE `&self` surface being race-free under true parallelism, jointly. Two
  rules pick the level: a lock converts Send INTO Sync and does nothing else (it
  serializes simultaneity, it cannot un-migrate — which is why its conformance
  is BOUNDED on `T: Send`, so a `Mutex<Box<TaskGroup>>` is not Sync), and
  NOTHING upgrades a non-Send type to Send except the type's own declaration —
  no wrapper multiplies, `Arc`/`Mutex`/`Box` are each Send/Sync exactly when
  their contents are. When neither assertion is honest, send the OPERATION
  instead: the value stays with one task and peers name operations on it over a
  `Channel` (remote operation, not shared access), which works for every type
  because the message is what has to be Send.
- `Thread.spawn { … } -> Thread<T>` checks BOTH directions of the thread crossing
  (design 193): every capture must be `Send` on the way in, and `T` must be
  `Send` on the way back, since the body computes the result on its own thread
  and `join()` hands it over. A `Void` body's handle is the distinct `VoidThread`
  (`Thread<Void>` is unwritable, by the visible-`Void` rule), exactly as
  `group.spawn` of a `Void` body gives a `VoidTask`.
  A borrow capture (`[&var n]`) is refused before
  either question — an escaping closure cannot hold a pointer into the frame
  that spawned it.
  **INSIDE A GENERIC BODY, THE DECLARED BOUND IS THE ANSWER** (DF-219c, fixed
  Aug 21): a `<T: Send>` bound licenses capturing a `T`, and `<T: Send + Sync>`
  licenses an `Arc<T>` (an Arc shares its payload by construction, so it needs
  both). An UNBOUNDED `T` is still refused — nothing was promised — and the
  bound is checked at the CALL, against the concrete type argument, so the
  trust is never misplaced. Treat this as working now and SUSPECT in older
  builds, where the audit answered False for every abstract `T` and
  `Send`-bounded fan-out was simply unwritable, bound or no bound. GOTCHA when
  you get it wrong: a non-Sync payload makes the WHOLE `Arc` non-Send, so the
  message says "not `Send`" — read past it to the sentence naming the unmet
  bound (`` `Arc` is `Send` only when its payload is `Sync` ``).
- **THE NAMESPACE IS THE ENGINE (design 242).** `Thread.*` is OS threads and
  blocking; `TaskGroup` and `Task<T>` are cooperative and suspending. The two are
  different machines — one blocks, one suspends; `Channel.recv` blocks and
  `receive` parks — so the call site's namespace is what says which one you are
  on:
  ```saw
  var t = Thread.spawn { crunch(n) }   // Thread<Int>; join() BLOCKS this thread
  let h = group.spawn(crunch(n))       // Task<Int>;   join() drives the group
  ```
  A `Void` body gives `VoidThread` / `VoidTask` respectively.
  **REACH FOR THEM IN THIS ORDER**: `TaskGroup` by default (structured, one
  thread, deterministic interleaving); `TaskGroup(threads: N)` when the work is
  CPU-parallel and every frame is `Send`; `Thread.spawn` only when one thread
  must BLOCK — a long or thread-phobic C call — which is the one thing the
  cooperative engine has no answer for.
  Don't mix engines per task. `Channel.recv` from a task is the worst version
  of mixing them: the block is unbounded and the thread it stops
  is the EXECUTOR's, so every sibling stops too — including the task that would
  have sent the value, which turns the wait into a group deadlock. Use `receive`.
  Nothing rejects the call today (DF-181c).
  The bare `spawn { … }` is GONE: it named neither engine, read like the
  cooperative one and started an OS thread. Writing one is a clean error naming
  both spellings, so code that still has it predates Aug 22.
- **A THREAD'S FATE IS WRITTEN, NEVER DROPPED (design 242 rulings 5/9a/9b).**
  A `Thread.spawn` handle must reach `join()` on EVERY path out of its scope.
  Both discard spellings are compile errors — the bare statement AND the
  `let _ =` that design 151 blesses for a `Result` — and so is a `return` that
  leaves the handle unconsumed:
  ```saw
  Thread.spawn { crunch(n) }              // error: ... must be consumed
  var t = Thread.spawn { crunch(n) }
  if urgent { let _ = t.join() }          // error: not consumed on this path
  Thread.spawn { crunch(n) }.join()       // the wait-here spelling: fine
  ```
  Two things discharge it besides a written `join()`. A move into STORAGE whose
  owner declares a hand-written `deinit` (`self.workers.push(move t)` inside a
  `Pool` that joins them in its own deinit) — which is how a pool outlives the
  function that starts it. And `group.spawn`, whose handles carry NO obligation
  at all: a group is a declared consumer, so the accept-loop idiom
  (`while true { group.spawn(handle(accept())) }`) is untouched, and a bound
  group handle may simply be dropped.
  The storage rule asks only that the owner DECLARE a deinit, not that it
  actually join — an owner that forgets meets the runtime backstop:
  `panic at task.saw:150: Thread was dropped without being joined or detached`.
  GOTCHA for older code: the handle used to JOIN on drop, so
  `let _ = spawn { … }` was a sequential call plus thread overhead and every
  exit edge of a function holding one was a blocking edge. A build that accepts
  an unjoined handle predates Aug 24.
- **A `Thread.spawn` BODY IS `sync`, AND MAY BLOCK ON FFI (design 242 rulings
  8/9).** A spawned thread runs no executor, so a suspension there has nothing
  to resume it: `Thread.spawn { yield_now()  7 }` is a clean error naming
  `TaskGroup(threads: 1)`, which is suspending work on a dedicated thread WITH
  an executor. The one permitted source is a `blocking` extern, directly or
  through a helper — it runs as a plain call and blocks that thread, which is
  the reason to spawn one; design 103's offload is for a body with a task to
  park, and there is none here. An ordinary `sync` body still refuses the same
  call. Treat both as working now and SUSPECT in older builds: the body used to
  compile as ORDINARY SYNC CODE with no frame at all, so a `yield_now()` inside
  one was a silent no-op and a corpus test claiming to check frame residency
  across a suspension was passing while checking nothing.
- **A CHANNEL WAIT IS A PARK, AND CHANNELS CLOSE EXPLICITLY (design 230).**
  `receive() -> Result<T, ChannelError>`, `send`/`close ->
  Result<Void, ChannelError>`, `enum ChannelError { case Closed, case Cancelled,
  case Alloc(e: AllocError) }` (a receive TIMEOUT is the reserved next case).
  `Alloc` arrived with design 234 §1 and CARRIES the leaf error rather than
  restating its vocabulary — it renders through it (`the channel could not
  allocate a queue node: allocation of 64 bytes (align 8) failed`), and adding a
  case makes an exhaustive `match` on a `ChannelError` a compile error until you
  handle it. The park is the mechanical half:
  a waiting receiver costs 0% CPU and is woken by a send or a close ON ITS OWN
  CHANNEL — before 230 it suspended READY and a sole waiter burned 100% of a core,
  so treat a quiet channel wait as working now and SUSPECT in older builds.
  `Cancelled` is the answer a parked receive gives when its task is cancelled: the
  check is at the loop top, ahead of the queue read, so a cancelled consumer stops
  instead of taking one more message. Hand-rolling the loop with `try_receive` +
  `cancelled()` still works and is no longer the only way to be cancellable.
  **`try_receive` is `-> Result<T?, ChannelError>` since design 234 §4**, not the
  bare `T?` it used to be: `Ok(Some(v))` a message, `Ok(None)` nothing yet,
  `Err(Closed)` closed AND drained. Would-block is not an error; a closed channel
  is, because a poll loop that cannot tell the two apart waits forever. The
  drain idiom composes a `try` with a `while let` — the `try` peels the error
  channel, the `while let` peels the optional:
  ```saw
  func drain(ch: Channel<Job>) -> Result<Int, ChannelError> {
      var n = 0
      while let job = try ch.try_receive() { run(job)  n = n + 1 }
      return n
  }
  ```
  That works in a SUSPENDING body too since DF-245d (fixed Aug 22) — see the
  container-HEAD rule in the concurrency section: a propagating `try` in a
  head used to be refused there, and `try! ch.try_receive()` was the
  workaround, so distrust the plain `try` spelling in an older build. A pre-234
  build has the bare `T?`, so `if let v = ch.try_receive()` without a `try!`
  means the code predates Aug 22.
  `close()` is the part you have to WRITE. A handle carries no sender/receiver
  role — every handle is the same handle, and a waiting receiver holds one too —
  so nothing can work out that the producers are gone. Say so:
  ```saw
  func produce(orders: Channel<Order>, batch: Vector<Order>) {
      for order in batch.iter() { try! orders.send(order) }
      try! orders.close()              // ANY holder may; by convention the producer
  }
  func consume(orders: Channel<Order>) -> Int {
      var handled = 0
      var going = true
      while going {
          match orders.receive() {
              case Ok(order) -> { fulfil(order)  handled = handled + 1 },
              case Err(_) -> { going = false }   // closed AND drained
          }
      }
      return handled
  }
  ```
  Rules worth holding: close DRAINS first (a receive hands out everything already
  queued before it reports `Closed`, so closing mid-flight loses nothing); a send
  after close is `Err(Closed)` and does not enqueue; a SECOND close is
  `Err(Closed)`, not a panic, so a lost race is `let _ =`-able without being
  silent; there is NO automatic close at last-handle drop (that is the same
  uncountability restated). And the allocator: a `send` whose queue node is
  refused is `Err(Alloc(e))`, in the same error type, so nothing about a send
  panics any more. (Both of those were different before design 234 landed on
  Aug 22: the refused node PANICKED, `try_send` was the twin that reported it
  and panicked on a CLOSED channel instead, and neither could carry the other's
  failure — DQ-230b. The two stale sentences that used to sit here said `send`
  panicked on the allocator and that `receive` does not observe cancellation;
  the second was DF-230a, fixed with the `Cancelled` case above.)
  FORGETTING `close()` IS A DEADLOCK, and the executor reports it instead of
  hanging: every live task parked on a channel, nothing runnable, no io, no timer
  and no unjoined `Thread.spawn {}` task means nothing can ever run, so the program
  panics with `dump_tasks()` attached and each waiter marked `channel-parked`.
  It is decided by elimination, never by watching a task fail to progress —
  design 127's op budget makes a long computation present exactly like a
  permanent wait.
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
  **`connect` TAKES AN IPv4 ADDRESS OR A NAME, and RESOLUTION IS OFFLOADED
  (design 184).** A dotted quad — strictly four octets, 1-3 digits each, no
  leading zero, nothing else in the string — is an address already, so it is
  parsed in Saw and dialled directly: a literal caller never touches the
  resolver or leaves the executor thread. Anything else is resolved through
  `__saw_rt_resolve_ipv4` (std's only `blocking` extern, over `getaddrinfo`),
  which runs on a WORKER THREAD while the task parks, so siblings keep running
  through a DNS timeout; the first IPv4 answer is dialled. A name that does not
  resolve, and one whose answers hold no IPv4 address, are both
  `Err(IoError)` naming the host: `io error: resolve "db.internal" failed (not
  found)`. IPv6 is not resolved and there is no resolver cache. Until design 184
  the host argument was IGNORED OUTRIGHT and every `connect` dialled 127.0.0.1
  and reported success (DF-181d), so a pre-184 build is the one where
  `connect("example.com", 80)` appears to work.
  DESIGN 92 — failable net calls RETURN the failure, never swallow it: `read`
  gives `Result<Data, IoError>` where an EMPTY Ok is EOF and an `Err` is a genuine
  error (DISTINCT — an empty Data no longer means both); `write(bytes: Data)`
  writes the WHOLE buffer and returns `Result<Void, IoError>` (it REPLACED the old
  Void `write_all`/`write_all_str` that hid a hard write error); `accept` returns
  `Result<TcpStream, IoError>`. Handle with `try`/`try!`/`match`. `write` is
  OVERLOADED — `write(s: String)` for text and `write(bytes: Data)` for binary;
  both suspend and both are drivable from a spawned worker (design 95 keys the two
  overloads' driven frames by resolved signature, so a worker may call BOTH back
  to back). `IoError: Error` — interpolate it (`"{e}"`) for the whole story:
  `io error: connect failed (host unreachable)`. **It carries the failing op's
  name, a PORTABLE KIND and the platform's RAW CODE (design 234 §2), and the two
  halves answer different questions.** `e.kind()` is an `IoErrorKind` (`import
  std.net.{IoErrorKind}`) — a curated portable set (`NotFound`,
  `PermissionDenied`, `ConnectionRefused`, `TimedOut`, `Interrupted`, …) ending
  in `Unknown` — and it is the branchable half:
  ```saw
  match e.kind() {
      case NotFound -> create_it(),
      case PermissionDenied -> give_up(),
      case _ -> retry_later(e.code())        // log the number, don't branch on it
  }
  ```
  Classification is DIAGNOSTIC, not contractual: it is lossy on purpose (EACCES
  and EPERM both land on `PermissionDenied`), so treat `Unknown` as an opaque
  failure rather than an errno to be worked out. `e.code()` is that number — an
  `Int32`, the platform's OWN (`ECONNREFUSED` is 61 on macOS and 111 on Linux),
  `0` where the platform has none, which includes a failure std raised itself
  (a park cut short by cancellation). Only `kind()` reaches the rendered text,
  which is what makes `"{e}"` read the same on every host. Growth is loud:
  promoting a code out of `Unknown` into a new kind breaks an exhaustive match
  at compile time rather than silently rerouting it. Treat all of this as
  working now and SUSPECT in older builds: `e.code()` returned the portable TAG
  under a name that read like an errno (tag 16 was the catch-all `Other`, errno
  16 is `EBUSY`), there was no `kind()`, and the raw platform number was
  discarded inside the runtime with nothing able to recover it. The five
  off-loopback causes — host/network unreachable, timed out, host/network down —
  were unmapped until Aug 15, so a pre-fix build says `(other error)` for EVERY
  remote dial failure.
  accept/read/read_into/write/connect all OBSERVE cooperative cancellation at their
  internal park — including a task ALREADY parked on a permanently-idle fd (design
  102 item 2): a peer's `handle.cancel()` or a `cancel_addr` write rouses the parked
  task (the reactor has a cross-thread wake, and the scheduler wakes a parked frame it
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
- **ANY DEPTH MEANS ANY MODULE TOO (design 210).** The frames between a root and
  its park may live in your package, a dependency, or std, in any mix — the three
  are one rule. A suspending method of an imported module embeds into the
  caller's frame with its own module's meaning intact: the module-private helpers
  and `static`s its body names keep resolving after the embed, inside a module
  that cannot see them and does not need to. Generic templates cross module lines
  the same way, one frame per instantiation.
  ```saw
  // pkg/lib.saw — `resolve_slot` and `SLOTS` are private to this module
  static SLOTS: Int = 16
  func resolve_slot(key: String) -> Int { key.len() % SLOTS }
  extension Store {
      public func fetch(&self, key: String) -> Result<Data, IoError> {
          let slot = resolve_slot(key)
          self.conn(slot).read()             // suspends, in a DEPENDENCY's method
      }
  }
  // main.saw — drives it without seeing either private name
  func main() { print(try! store.fetch("k").len()) }
  ```
  Before design 210 this compiled only when the callee was std; a user module's
  method failed with ``function `resolve_slot` is not directly accessible``
  pointing INTO the dependency's own file, a diagnostic about code the caller
  neither wrote nor could fix. That shape means the compiler predates 210.
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
  spawner if you need it to outlast the task.
  **AND A SCOPE INSIDE A SUSPENDING BODY IS A SCOPE TOO (design 218 unit 2).**
  A local that lives across a suspension is held in a frame field, and its
  lifetime is still its scope's: it deinits at the end of the block that owns
  it, in reverse declaration order, on every edge out of that scope —
  fallthrough, `break`, `continue`, `return` — and at the redefinition point of
  a design-107 same-scope rebind. So a driven loop body releases per ITERATION:
  ```saw
  while going {
      var conn = try! listener.accept()   // suspends
      serve(&var conn)
  }                                       // conn's fd closes HERE, each pass
  ```
  Treat that as working now and SUSPECT in older builds, where a frame field
  lived until the frame died: the loop above held every connection open until
  the task completed, and a shadow rebind released the OLD value after the new
  one was already in use. The counts always balanced, so nothing leaked — what
  was wrong was WHEN. The sync half of the same rule had THREE broken edges of
  its own until Aug 21 — `break`, `continue`, and the ERROR EDGE of a
  `try { } catch { }` block, none of which ran any scope cleanup at all, all of
  which DID leak — so distrust a pre-Aug-21 build on both sides. The try one is
  the easiest to hit and the least visible:
  ```saw
  try {
      var f = try file.File.open(path)   // an fd
      let text = try f.read()            // if THIS fails …
      handle(text)
  } catch {
      report(error)                      // … `f` used to leak, silently
  }
  ```
  A catch block is a SIBLING scope, so everything the try body opened dies on
  the branch into it, innermost-first — the same rule the fall-through edge out
  of that block has always followed. In a DRIVEN body the same release still
  happens at frame teardown rather than at the edge: once, never a leak, but
  later than the sync twin (DF-242a).
  **AN OPTIONAL-BINDING BRANCH IS A SCOPE TOO, and on the sync side it was not
  one until Aug 22** (DF-218x) — the fourth sync leak, and the last. The three
  above were broken EDGES; this one was a broken BINDING, held in no scope at
  all, so widening the walk could never have reached it:
  ```saw
  if let conn = pending.take() {
      serve(&var conn)
      return                  // `conn`'s fd used to leak, silently
  }
  ```
  A binding lives for the branch that introduced it and dies on whichever edge
  the branch leaves through — fall-through, `return`, `break`, `continue` —
  which is the rule every other binding already followed. It covers all five
  spellings of the one lowering (`if let`, `if var`, and design 233's
  `while let` / `while var`), and it moves the design-63 TUPLE pattern's leaves
  in with them: those were released, but at the end of the ENCLOSING block, so
  two successive `if let (a, b) = …` branches held both pairs at once. `guard
  let` is untouched and always was right — its binding belongs to the enclosing
  scope on purpose, which is the whole difference between the two forms. The
  DRIVEN twin was right too, so this is the sync half catching up.
  **The SLOT goes too (design 134):**
  the frame allocation is released at completion and its run-queue slot returns to
  a free list, so a group costs O(live + unjoined-result tasks) rather than
  O(tasks ever spawned) — an accept loop that serves 200k connections holds as
  many slots as it has connections IN FLIGHT (`group.count()` reports them). The
  result and the cancel word live in a group-owned cell that outlives the frame,
  which is what lets the frame go; a `Void` task's slot is reclaimed at
  completion, a task with a result keeps its slot until `join` takes the value.
  Handles are `(slot, generation)` pairs, so a handle to a task that has come and
  gone can never reach whatever occupies its slot next: joining an already-joined
  `Task` panics, joining a finished `VoidTask` returns, and `cancel`
  is a no-op on both. **A DYNAMIC number of tasks works through a
  `Vector<Task<T>>`** (probe-verified Aug 10 — a dogfood reader
  feared the NoCopy handle wouldn't compose with the vector; it does):
  ```saw
  var handles = Vector<Task<Int>>()
  for i in 0..5 {
      handles.push(group.spawn(work(i)))
  }
  var total = 0
  while handles.len() > 0 {
      let h = handles.pop()!     // pop moves the handle out — yours to join
      total += h.join()
  }
  ```
  `cancel_addr()` pins its slot (a raw address must stay
  valid), giving up reuse for that one slot. Suspending calls yield
  IMPLICITLY when they park (a task doing I/O never needs `yield_now`); `yield_now`
  (design 114: `import std.task.*` — no longer prelude) is now needed only where the
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
  cooperative thread is never wedged. **THE OFFLOAD IDIOM (design 183): annotate
  the real C signature and pass a buffer you own.**
  ```saw
  extern "C" {
      blocking func read(fd: Int32, buf: UnsafePointer<Int8>, n: Int) -> Int
  }
  func drain(fd: Int32) unsafe -> Int {
      var chunk: [Int8; 4096] = [0; 4096]        // frame-owned: survives the park
      read(fd, (&chunk) as UnsafePointer<Int8>, 4096)
  }
  ```
  Any signature the C-ABI whitelist admits offloads — fixed-width integers,
  Int/UInt, Float, `UnsafePointer<T>`, `Void`/`Never` returns, ANY arity (the old
  `(Int) -> Int` rule is RETIRED, and a thread per call still is the model).
  Anything outside it is a clean error at the DECLARATION, in @export's words
  (``parameter `s` has type `String`, which is not C-ABI-safe``) — pass an
  aggregate as `UnsafePointer<S>`.
  **THE POINTER RULE: a pointer argument must point into the suspended FRAME or
  the HEAP.** The worker reads through it while the task is parked, and may still
  be reading after a cancel; both of those storage classes outlive the park (a
  suspending function's locals live in a heap-resident frame). A stack temporary
  cannot reach an offload, since the function owning one would have to be `sync`
  and a `sync` body may not suspend. If you `malloc` the buffer yourself, free it
  after the call returns, never on a cancel path racing it.
  `blocking` is part of an extern's CONTRACT: two declarations of one symbol that
  disagree about it are an error, so you cannot annotate a seam std also declares
  (`__saw_rt_fs_read`) — offload your own distinctly-named wrapper instead.
  Since design 120
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
  capture is shared across every module in the compilation unit).
- **A SUSPENDING METHOD WORKS ON EVERY RECEIVER SHAPE, at the embedded position
  as well as the drive root (design 223).** A plain struct, an ENUM extension, a
  GENERIC struct (`Box2<String>`), a method-level generic (`h.wrap<String>(v)`),
  and a method that SATISFIES A TRAIT REQUIREMENT — entry-module and
  cross-module alike:
  ```saw
  extension Color { func label(&self) -> String { yield_now()  "red" } }
  extension Box2<T> { func describe(&self) -> String { yield_now()  "boxed" } }
  extension Person: Greeter { func greet(&self) -> String { yield_now()  self.n } }
  ```
  Treat all five as working now and SUSPECT in older builds, where the failures
  were not alike: the enum receiver was a codegen ICE, the generic-struct
  receiver in an embedded body compiled as an ORDINARY FUNCTION that printed the
  right answer and never suspended, the method-level generic was a raw
  `KeyError`, and the conformance method was reported as not implementing the
  requirement it plainly implements.
  **The one refusal: `any Trait` DISPATCH to a suspending body.** A suspending
  call embeds the callee's frame by value, so it needs the frame at compile
  time, and an erased receiver carries a vtable word instead — so
  `func shout(g: &any Greeter) -> String { g.greet() }` against a suspending
  `Person.greet` is a clean error at the dispatch. Call the method on the
  concrete type, or take the receiver as a generic `<T: Greeter>`. (In older
  builds this compiled and the `yield_now()` ran outside any frame, where it is
  a no-op.) A `&any Trait` PARAMETER of a suspending function is refused for the
  neighbouring reason: a reference that spans a suspension is held in the frame
  as a handle to its referent, and an erased referent has no size — take a
  `Box<any Trait>` or a generic bound.
- A suspending
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
  just works. The optional binding's SCRUTINEE takes one too (DF-182a), so
  `guard let d = source.next()` drives the method and parks inside it; the
  condition is unconditional, so it is lifted to a temp ahead of the binding. A
  trailing `if let … { v } else { w }` in VALUE position takes one in either
  branch (DF-182b), and a body that suspends may hand a local out through a tail
  `move r` rather than a `return` (DF-182d). A `move` SCRUTINEE works too
  (DF-182c): `if let x = move opt` / `guard let x = move opt` whose continuation
  spans a suspension consumes the optional, carries the payload in the frame and
  drops it exactly once — the ordinary shape for reading an owning value out of
  an Optional, at every copy tier. A `move` scrutinee of a suspension-spanning
  `match` is still refused. It also embeds in any EXPRESSION position (design 120): a chain head
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
  first), and the RHS still runs only when the LHS does not decide.
  **A CONTAINER'S HEAD IS A POSITION TOO (design 224)** — the expression a
  construct evaluates outside all of its blocks: an `if`/`while` CONDITION, a
  `for` RANGE (either endpoint), a `match` SCRUTINEE, an `if let`/`guard let`
  SUBJECT, and an `&&`/`||` RHS inside any of them. A `while` condition suspends
  once per ITERATION, where it is written, so `while try! ch.receive() > 0 { … }`
  drains a channel and a `continue` re-evaluates it. A compound assignment's RHS
  (`n += slow()`, and its chained spelling `x?.n += slow()`) and a
  `return try! ch.receive()` take the same rewrite. (The `try!` is design 230's:
  a receive answers `Result<T, ChannelError>`, and a `try!` subject is itself one
  of these positions, so the two hoists compose.) Every one of these was neither
  embedded nor refused until Aug 15 — a channel receive SPUN at 100% CPU and
  never returned, a free function or method was a codegen ICE — so treat them as
  working now and SUSPECT in older builds. One boundary: a VALUE-position
  `while` whose condition suspends is a clean error (its result comes out of a
  `break <value>`, which a suspension-spanning loop does not support).
  **A PROPAGATING `try` IN A HEAD WORKS TOO (DF-245d, fixed Aug 22)** — the same
  five head slots, and the drain loop design 234 §4 asks for is the one that
  wanted it:
  ```saw
  while let job = try ch.try_receive() { run(job) }   // in a spawned task
  guard let cfg = try load(path) else { return 0 }
  if (try grab(n)) > 0 { … }        for i in 0..(try count()) { … }
  ```
  Until then a `try` written in a head was refused with ``cannot propagate
  errors from a function returning `Poll` `` — a type the author never wrote —
  or died as ``Cannot create Result.Err outside Result-returning function``, so
  treat all five as working now and SUSPECT in older builds, where `try!` was
  the workaround. This is DF-244a's rule at the other position: the lowering
  keys on STATEMENTS, and a head is the one place an expression sits outside
  every block its construct owns.
  **THREE MORE POSITIONS, fixed Aug 21 (design 237)** — treat each as working
  now and SUSPECT in older builds. A DESTRUCTURING `let`'s RHS, in both
  spellings (`let (a, b) = (s(1), s(2))` and `let (a, b) = pair()` where `pair`
  suspends), which used to be the nested/expression-position refusal. A
  `Result`-returning function's RETURNED value, at the Ok side, the Err side and
  the erased `Box<any Error>` side (`return read_len()` at
  `-> Result<Int, IoError>`) — the auto-wrap is a real node and the hoist did
  not know it, so the same refusal fired. And an ARGUMENT that auto-wraps into a
  `T?` or `Result<T, E>` parameter, which was not refused but MISCOMPILED inside
  a driven body: `ch.send(count)` on a `Channel<Int?>` died with an
  internal-compiler-error type mismatch at the author's line, and so did any
  argument naming a frame-resident local at a wrapping parameter.
  ONE thing became a REFUSAL: `__saw_drive` may not appear in a body that itself
  suspends. It is design 44's test-only entry and it used to crash the compiler
  there; a suspending body already runs inside an executor, so the diagnostic
  names the direct call — which is what embeds.
  Still a clean,
  user-anchored compile error (NOT a silent block): a suspension-spanning `if let`/
  `guard let`/`while let` with a TUPLE pattern; a suspending `try { } catch { }` block whose try
  body raises TWO OR MORE distinct error types (below); and a NESTED generic call
  whose template suspends
  UNCONDITIONALLY without calling a type-param method (`func g<T>(x: T) -> T {
  yield_now(); x }` called nested) — its instantiation's effect node is not built,
  so drive it directly with `__saw_drive`/`spawn` instead (this is a same-module limit,
  not a cross-module one). A method that is BOTH struct-generic AND method-generic
  (`Dual<T>.mix<U>`) now drives (design 104 item 3): the frame is keyed by both
  instantiations (`Dual_mix$2$T$U`), so 2 struct × 2 method insts are 4 distinct
  frames. TWO BINDINGS IN ONE SUSPENDING BODY MAY SHARE A NAME and each keeps its
  own value across a suspension — a derived shadow (`if let x = x`,
  `let n = n + 10`, `for n in n..n + 2`), disjoint scopes (a `match` arm binding
  and a later local of the same name), two arms of one `match`, or a local derived
  from a param. The frame carries one field per BINDING, not per name. This was
  keyed by name until Aug 6 and read the wrong slot silently, so treat a
  same-named pair across a suspension as fine now but suspect in older builds.
- **THE ERROR SURFACE WORKS IN A TASK BODY (design 196).** All of it, at the same
  tiers sync code gets. A propagating `try` returns the error from the function
  (`let chunk = try stream.read()` in a task reports the failure instead of
  panicking with `try!` or losing the cause with `try?`); a `try { } catch { }`
  BLOCK may suspend anywhere inside it, in statement or value position, driven or
  spawned, nested, and inside a loop whose `break`/`continue` still reach the
  enclosing loop; an erased `Result<T, Box<any Error>>` returns and propagates
  across a suspension and its function is spawnable. Each of these was a compile
  error or a compiler crash until Aug 10, so treat them as working now and
  SUSPECT in older builds — a pre-196 task body had to use `try!`.
  ```saw
  func serve(stream: &var TcpStream) -> Int {
      var served = 0
      try {
          let body = try fetch(&var stream)   // the catch is a resume target
          served = body.len()
      } catch {
          print("dropping connection: {error}")
      }
      served
  }
  ```
  ONE FENCE: a suspending try/catch BLOCK may raise only ONE error type. Two
  callees with different error types in one try body is a clean error naming both
  — write one block per error type, or handle each call with an inline
  `try <call> catch { … }`. An inline catch has no such limit.
- A CLOSURE created in a driven body works (design 77 DF-C1): call it after a
  suspend, hold it across one (its env deinits exactly once at frame death), or
  own it in a spawned TaskGroup frame — captured frame locals are moved into the
  closure by value. A tuple local and `let (a, b) = f()` destructuring also
  survive a suspension (design 77): their bindings are frame-resident. A closure
  literal passed STRAIGHT to a call in a task body captures frame locals in every
  position the call can sit in — the body's tail, a `return`, a `let`, an
  assignment, a condition, a scrutinee, a nested call's argument — which is what
  makes the shared-counter idiom writable:
  ```saw
  func add(shared: Arc<Mutex<Int>>, n: Int) -> Int {
      shared.lock({ &var c in c = c + n  c })   // captures `n`, the parameter
  }
  // group.spawn(add(shared.copy(), 1))
  ```
  Two positions still refuse a capture, cleanly: a bare (non-block) `match` arm
  expression, which cannot host the materialization at all, and a `while`
  CONDITION, where it would run once ahead of a condition that runs every
  iteration. Bind the closure to a `let` first where the parameter is not `sync`.
- **References may span a suspension (design 88, D6).** A `&T`/`&var T` param or
  a `&var self` receiver of a suspending function stays valid across a suspend —
  it becomes a frame-resident pointer into the referent, so a read after resume
  and a `&var` mutation both address the SAME caller value (mutation is
  caller-visible). The reference doesn't own → never dropped by the frame (deinit
  stays exactly-once). A SPAWNED task may take one too (design 201) — the
  argument borrows its ROOT for the task's life on the extent rule below, so
  `group.spawn(fill(&var buf, 3))` compiles and the task's writes are at `buf`
  after the join. EXCEPT into a `threads: N` group, where a reference is not
  `Send` and the frame cannot cross to a worker thread (pass an owned value /
  `Arc` / `Channel` there). A reference to a task-LOCAL inside the spawned body
  needs none of this. Net
  offers BOTH: value `read() -> Result<Data, IoError>` (fresh Data per call, the
  ergonomic default) AND reference `read_into(&var Data) -> Result<Int, IoError>`
  (design 96 — appends the chunk into a caller buffer through a `&var` held across
  the internal park, so a reader ACCUMULATES successive chunks into ONE growing
  buffer with no per-chunk allocation; returns the byte count, 0 = EOF).
- **TWO SPELLINGS REACH THE SPAWNER, ONE RULE COVERS BOTH (designs 188/189/201).**
  A borrow CAPTURE (`group.spawn(run({ [&var n] in n = n + 1  n }))`) and a
  `&`/`&var` ARGUMENT of the spawned call (`group.spawn(bump(&var n))`) are the
  same borrow, and everything below applies to each. The argument spelling is
  what a worker filling a caller's buffer wants:
  ```saw
  func fill(v: &var Vector<Int>, n: Int) -> Int { … v.push(i) … v.len() }
  var buf: Vector<Int> = []
  var group = TaskGroup()
  let h = group.spawn(fill(&var buf, 3))
  print(h.join())          // 3
  print(buf.len())         // 3 — the task wrote through to the root
  ```
  The frame holds a pointer into the caller's storage and owns nothing through
  it, so the pushed elements die once, with `buf`, at `buf`'s scope end — a
  task's OWN values deinit eagerly at completion, a borrowed referent is not
  one of them.
- **DECLARE THE ROOT BEFORE ITS GROUP (design 188).** Sound because destruction
  is LIFO: the group's Deinit joins before anything declared AHEAD of it dies.
  Declared AFTER the group, that inverts — the binding is torn down while the
  tasks are still live — so it is a compile error naming both declaration lines
  and the fix. Declare the group at the TOP of the scope it governs.
- **AN MT GROUP TAKES NEITHER SPELLING.** A reference is not `Send`
  (``parameter `n` of type `&var Int` is not `Send` ``), and a closure is not
  either, so the capture is refused one indirection out. Share cross-thread
  state through `Arc`/`Mutex`/`Channel`.
- **THE BORROW'S EXTENT IS THE TASK'S LIFE, AND THE HANDLE CARRIES IT
  (design 189).** `&var x` borrows `x`'s root EXCLUSIVELY and `&x` shares it,
  for as long as the task can reach it — so the Law of Exclusivity sees a spawn
  borrow over a window as long as the task rather than as long as the spawning
  call. **`join()` releases** (it consumes the result exactly once, so the point
  is statically known), which is what keeps SPAWN-JOIN-USE legal with nothing
  extra written:
  ```saw
  var n = 0
  var group = TaskGroup()
  let h = group.spawn(run({ [&var n] in n = n + 100  n }))
  n = 5                    // error: `n` cannot be written here — the task
                           //   spawned at line 3 holds `&var n` until
                           //   `h.join()` releases it
  print(h.join())
  print(n)                 // fine: the borrow ended at the join
  ```
  **An exclusive borrow excludes READS too** (one writer XOR many readers, over
  a task-length window), so `let seen = n` between the spawn and the join is the
  same error. To watch a value while the task runs, share it through an
  `Arc<Mutex<T>>` or a `Channel` — where the synchronization is in the types.
  Shared `&x` borrows COMPOSE: two of them live at once, with caller reads
  beside them, are fine. A `move` of a borrowed root is the same violation under
  the move vocabulary, and it is the one that made this a SOUNDNESS rule:
  `consume(move buf)` between a spawn and its join used to drop the buffer and
  hand the task freed memory, silently, exit 0.
  RELEASES LATER THAN THE JOIN, all conservative: a DISCARDED or never-joined
  handle holds its borrow to the GROUP's death (a `Task`'s Deinit owns
  nothing and does not join), and so does one stored in a field or an element; a
  join inside an `if` releases on that path only, so the borrow is live again
  below the branch (hoist the join out); a borrow still live when a LOOP BODY
  ends is refused outright, since the next iteration would open a second
  exclusive borrow of one root (join inside the body — that shape is fine).
  `cancel()` does NOT release: the cancelled task still runs its cancel path,
  and it reaches the referent through the same pointer.
  **IDIOM**: declare the group first, spawn, join, then touch the root. If the
  caller genuinely needs the value mid-task, that is an `Arc<Mutex<T>>` or a
  `Channel`, not a borrow.
- **`std.compiler.frame` is the FRAME vocabulary, and you almost never want it**
  (design 218 unit 1). A suspending function becomes a state machine over a heap
  frame, and this module is the types that machine is written in: `Slot<T>`
  (storage that either holds a `T` or is empty — `empty`/`of`/`put`/`take`/
  `clear`/`is_occupied` plus a `borrows` `value()`), `UnsafeRef<T>` (an
  `unsafe struct` holding a pointer to something else's storage, with a
  `deref() unsafe borrows` and a `copy()`), and the `Resumable` trait every
  generated frame conforms to (`resume`/`wake_reason`/`is_cancelled`/`bt_desc`/
  `release`) with its `Poll` signal enum. Import-gated and NOT in the prelude; in ordinary
  Saw a plain `let` is the answer and reaching for a `Slot` is a smell. It is
  PUBLIC on purpose: transform output is held to the ordinary ownership rules,
  so the compiler may only emit code you could have written, and a vocabulary
  it could reach and you could not would be a second rule set. What it is worth
  knowing for: `Slot`'s payload is released exactly once BY CONSTRUCTION (the
  tag and the payload move in one operation, and the field is private), and
  `UnsafeRef`'s validity — the referent outlives every `deref` — is carried by
  design 130's marking rule rather than by a check, so a function touching one
  is `unsafe`-declared and is reviewed. Conforming to `Resumable` by hand
  grants nothing: spawn and enqueue are compiler-lowered.

## Modules & packages
```saw
import std.net.{TcpListener, TcpStream}   // selective: EXACTLY those names, bare
import std.file.*                          // glob: every public name of the module, BARE
import std.file                            // whole module: QUALIFIED ONLY — `file.File`
import mymodule as mm       // aliasing; `module`/`public`/`package`/`parent`
public import wire.{Header}  // RE-EXPORT: `Header` joins THIS module's surface
```
- **THREE IMPORT FORMS, and std takes the same three as any package
  (design 150).** `import std.time` binds the last segment as a QUALIFIER
  and exposes nothing bare (`time.Instant.now()`, `let t: time.Instant`);
  `import std.time.*` puts every public name in scope bare;
  `import std.time.{Instant}` binds `Instant` and only `Instant`. `as`
  renames the qualifier (`import std.time as clock`), braces rename a
  symbol (`{Map as Dict}`).
  A qualifier works in EVERY position a name appears: annotations (incl.
  behind `&`/`&var` and inside `Optional`), return types, generic arguments,
  call heads, constructors, static-method chains (`time.Instant.now()`),
  enum construction, `any` existentials (`&any shapes.Named`) and generic
  bounds (`<T: shapes.Named>`). A bare name that only a qualifier is in
  scope for is a clean error naming all three forms.
  **EACH FORM BINDS EXACTLY WHAT IT NAMES (DF-247b, Aug 24).** Only the
  whole-module form binds a qualifier. A selective import used to bind one
  too, for reaching what it did not list — an undocumented reach into the
  rest of the module, which is the very thing the braces exist to prevent.
  Want both? Write both, on two lines naming one module — they are
  COMPLEMENTARY, not a duplicate-qualifier collision (that error is about
  two DIFFERENT modules), and the bare and qualified spellings are then ONE
  TYPE in every position:
  ```saw
  import std.file
  import std.file.{File}
  func open_it(p: Path) -> Result<File, IoError> { File.open(p) }
  func exists(p: Path) -> Bool { file.File.exists(p) }
  ```
  A qualifier no whole-module import bound is a clean error naming the line
  that would bind it (``error: `net` is not a module qualifier here``), in a
  type position and an expression position alike. Treat all of this as
  current and SUSPECT in older builds, where `import std.net.{TcpStream}` also
  gave you `net.IoError` — and where the same spelling under a GLOB resolved
  to a name-only type that compared unequal to the bare one, with nothing said.
  **IDIOM**: braces in library code (the import list documents the
  dependency and survives a rename); glob for a vocabulary module a file
  leans on (`std.path.*` in a file that is all paths); qualified for
  occasional use or where the bare name would collide — `import std.time`
  costs one word per use and never fights your own `Instant`.
- **A QUALIFIER IS THE WEAKEST NAME IN SCOPE (design 150 pin 4).**
  Resolution runs local scopes -> module-level declarations -> imported bare
  names -> qualifiers LAST, so a local, param or loop var named `data`,
  `path`, `time` or `net` shadows one with NO shadowing error. The shadow is
  lexical — the next function's `data.` reaches the module again. So writing
  `import std.data` never costs you the word `data`:
  ```saw
  import std.data
  func fresh() -> data.Data { data.Data() }   // the module
  func main() {
      var data = fresh()                       // local wins from here, no error
      data.push(65)                            // a method call, not module access
  }
  ```
  If member lookup then fails on the shadowing value, the error names the
  declaration that took the name and the three ways out. `sawc -W
  shadowed-qualifier` flags the DECLARATION instead of waiting for the use
  (warnings are off by default and never affect the exit code).
- Two imports binding ONE qualifier is an error AT THE IMPORT naming both
  paths; `as` fixes it. Any import form makes the module a DIRECT import, so
  choosing qualified access never loses its design-142 extensions.
  `sawc/std/` is reachable ONLY through a `std.`-prefixed path (DF-225e,
  Aug 21), so a bare `import data` names YOUR module — the collision above
  is a collision of qualifiers, never a second compilation of a std file.
- **AN IMPORT CYCLE IS A COMPILE ERROR NAMING THE LOOP** (DF-232e, Aug 21):
  `import cycle: a -> b -> a`, anchored on the first participating import
  with every edge's line in the hint. Break it by moving what both sides
  need into a module they both import. A module importing ITSELF is not a
  cycle and compiles. Treat this as working now and SUSPECT in older
  builds, where the modules were checked in an ARBITRARY order and the
  failure surfaced as an ordinary `undefined function` — inside an INNOCENT
  third module that merely imported a participant.
- **AN IMPORT IS PRIVATE (design 229).** What you import is YOURS, not your
  callers'. An importer of your module reaches what you declare `public` and
  what you `public import`, and NOTHING you merely imported — the bare name
  under a glob, the `{X}` selection, the qualified `m.X` and the chain
  `m.dep.X` are all refused, with a hint naming both fixes and the dependency
  the name really lives in. std is under the same rule: your `import
  std.data` is not on your surface. `public import` opts in, on every form —
  `public import wire` re-exports the QUALIFIER (`m.wire.Header`), `public
  import wire.{Header}` re-exports that NAME and only it (it binds no
  qualifier of its own to hand on, which is what makes a curated facade
  possible), `public import wire.*` re-exports the whole vocabulary. Your own view of
  your imports is unchanged either way, and a re-export widens no extension
  scope (a re-exported type keeps its own module's inherent API and brings
  nothing else).
  **IDIOM**: prefer the CONSUMER importing the dependency directly — it
  states intent and survives your refactor. Reach for `public import` only
  when your module genuinely IS the facade for that dependency (a system-call
  module publishing the encodings its callers must write).
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
  imports `codec`, a `public` method on `codec`'s `extension Data` is
  invisible to you until you import `codec` yourself. So `public` on an
  extension METHOD means what it means everywhere else — importers of my
  module get this — and the
  calling-it-without-the-import error names the module to add
  (```type `Data` has no method `u16_at` in scope here``` / ```add `import
  bmod` ```). std is ONE scoping domain (its files extend each other's types
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
  **PROGRAM-WIDE MEANS EVERY IMPORT FORM** (DF-238c, fixed Aug 22). The half a
  GLOB used to lose is the rule's SECOND one — the conformance declared in the
  TRAIT's module for a foreign type, whose declaration site a glob of the
  TYPE's module cannot reach either. `import m.*` reported ``type `Rec` does
  not implement trait `Summary` `` and hinted at adding the extension that was
  already there, while `import m.{Summary}` compiled the same file. A DECLARED
  `UnsafeSend`/`UnsafeSync` went the same way, so a `static` of a globbed
  cell-carrying type was refused as non-Sync. Both work now — treat them as
  working and SUSPECT in older builds, where switching the import to the
  selective form was the workaround.
- **TYPE IDENTITY is (defining module, name) — design 144.** A dependency's
  PRIVATE `struct Header` reserves nothing in your program: you declare your
  own `Header`, with its own layout, methods and `Vector<Header>`. Same for
  private enums, traits and type aliases. Two packages' PUBLIC same-name types
  coexist too, but one file cannot spell both bare — import at least one under
  an alias (`import wire.{Header as WireHeader}`, or `import wire` and write
  `wire.Header`). A bare use with two in scope is an ambiguity error naming
  both modules, at the USE site. Nothing about how you WRITE a type changed;
  names print short everywhere (`--emit-docs` adds a `module` field where two
  would read alike). **std is under the rule too (design 204):** each std FILE
  is its own module, so the types a std file keeps to itself — `State`,
  `MapSlot`, `LockState`, `OpenMode`, `SeekWhence`, `DataBuf`, `SetMark`,
  `FdPair`, `LockRelease`, the `Cbor*` internals, the iterators — reserve
  NOTHING, and your own type may carry the name. A std module's surface is what
  it declares `public`, and nothing else is reachable through any import form
  (``error: `OpenMode` is not defined in `std.file` `` + ``hint: available:
  File``). std's PUBLIC types are untouched: `Vector`/`File`/`Data` are still
  one declaration each, and redeclaring one is still ``struct `Vector` is
  defined multiple times``.
- **Prelude (design 82) — what's bare vs what needs `import std.X`.** Bare
  (prelude): primitives, `Vector`/`Map`/`Set`, `Optional`/`Result`/`Box`/`Arc`/
  `Allocator`/`GlobalAllocator`, the Copy family + `Deinit`/`Iterator`/
  `Equatable`/`Comparable`/`Hashable`/`Printable`/`Error`/`Send`/`Sync`,
  `Serialize`/`Deserialize` + `Encoder`/`Decoder`/`EncodeError`/`DecodeError`
  (std.serde — design 169),
  `print`/`panic`/`assert`/`sizeof`/`alignof`/`static_assert`, `TaskGroup`/
  `sleep`/`spawn`/`cancelled`, `StringBuilder`, `Duration` (std.duration —
  design 180; `sleep` takes one, so gating it would gate `sleep`).
  `Atomic<Int>` is prelude-bare too — a `builtin.saw` primitive, not a
  module, so there is nothing to import (it sat in NEITHER list until a
  design-203 dogfood reader had to guess; it belongs here).
  IMPORT-REQUIRED:
  `File`/`Directory`/`Path` (std.file/directory/path), `Data` (std.data),
  `Channel` (std.channel), `Mutex` (std.mutex), `Once` (std.once — design 186),
  `Instant` (std.time),
  `IoError`/`IoErrorKind`/`TcpListener`/`TcpStream` (std.net), `Utf8Error`
  (std.string),
  `yield_now` (std.task — design 114; the wrapper over the stdlib-internal
  cooperative-yield intrinsic) and `dump_tasks` (std.task — design 158),
  `Command` (std.process), `Env` (std.env),
  `FixedBuf`/`FixedStringBuilder` (std.fixedbuf — design 148),
  `CborEncoder`/`CborDecoder` (std.cbor — design 169; `std.serde`'s
  `Serialize`/`Deserialize`/`Encoder`/`Decoder` stay PRELUDE, only the format is
  gated), and — since design 188 closed the two the gate list had missed —
  `SpinLock` (std.spinlock) and `SlabHead`/`slab_alloc`/`slab_dealloc`
  (std.slab), both of which used to resolve bare against a spec that said
  otherwise, and `Slot`/`UnsafeRef`/`Poll`/`Resumable`
  (std.compiler.frame — design 218 unit 1; the first std module in a
  SUBDIRECTORY, so the import path has three segments and the qualifier is the
  last one: `import std.compiler.frame` gives you `frame.Slot`). A bare
  non-prelude name is a clean
  error ("`X` is not in the prelude and must be imported") whose hint names all
  three forms — so reach it BARE with `import std.X.*` or `import std.X.{Name}`,
  and `import std.X` alone gives you `X.Name` instead (design 150; the module
  paths above are the leaf, not the spelling to copy). Because a
  non-imported std module isn't compiled in, you may define your OWN `IoError`/
  `File`/etc. with no clash. The prelude itself is untouched by all of this:
  `import std.vector` just binds a harmless `vector` qualifier.
  **THE GATE RUNS ON ANNOTATIONS, not only where a VALUE is built (design 194).**
  A signature that merely RECEIVES a gated type needs the import too —
  `func take(d: &Data) -> Int` with no `import std.data` is now the ordinary
  "not in the prelude" error, where it used to compile. Every written position
  is covered: parameter, return, `let x: T`, struct field, enum case payload,
  `type` alias RHS, `static`, generic argument, tuple element, array element, a
  function type's parts, and `any Trait`. What is checked is the name AS
  WRITTEN, so the qualified spelling passes everywhere an import bound the
  qualifier (`func take(d: &data.Data)` under `import std.data`). Pre-194 code
  that named a gated type only in a signature now needs the import it always
  should have had; the usual face is `Result<T, IoError>` in a return type.
  The qualified spelling works in the three DECLARATION slots too — a struct
  FIELD, an enum case PAYLOAD, a `type` alias RHS — and in a CONSTRUCTOR's
  generic argument (`Vector<data.Data>()`). Treat all four as working now and
  SUSPECT in older builds (DF-194a): those annotations used to keep the dot into
  type comparison (```field `p` expects type `data.Data` but got `Data` ```), and
  `import std.data.{Data}` was the workaround.
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
- **AN EXTENSION HEAD CARRIES NO VISIBILITY** (ruled Aug 20): `public extension
  Point { … }` is a declaration-site ERROR ("an extension cannot carry a
  visibility modifier … visibility belongs on members"), and so are
  `public(package)`/`public(parent)` and the `@synthesize`-attributed spellings.
  An extension is not a nameable entity — nothing imports it, nothing calls it —
  so write `extension Point` and mark each MEMBER. It used to parse and be
  stored with one consumer (the docs emitter's signature string): not a member
  default, not a clamp, not a scoping input, so a `public extension` whose
  members were unmarked exported NOTHING. ~105 corpus heads carried the
  decoration; treat any code that still does as pre-Aug-21.
- **A PUBLIC API NEEDS PUBLIC TYPES** (user ruling, Aug 21). A declaration may
  not name a type LESS VISIBLE than its own reach: a `public func`'s parameters
  and return are `public`, a `public(package)` declaration's signature types are
  at least `public(package)`, a `public` field's type is at least as visible as
  the field. Refused AT THE DECLARATION, naming the type, both tiers and the two
  fixes:
  ```saw
  struct Hidden { n: Int }
  public func give() -> Hidden { Hidden(n: 2) }
  // error: function `give` is public, but the return type names `Hidden`,
  //        which is private — a public API needs public types
  // hint: either widen the type — mark the struct `Hidden` `public` — or
  //       narrow the declaration ...
  ```
  A PRIVATE declaration names anything, and a `public` member of a non-public
  type is capped at that type (gotcha 3 above), so the rule asks nothing extra
  there. Covers every position a declaration NAMES a type — parameter, return,
  the type a `borrows` accessor LENDS, struct field, enum case payload,
  `static`, `type` alias target, trait REQUIREMENT (the trait's tier is the
  bar), a generic parameter's BOUND and DEFAULT, a trait's parent, an
  extension's associated type — and a type ARGUMENT counts, so `Vector<Hidden>`
  exposes `Hidden` like a bare one. Function BODIES are untouched. Judged on the
  modifier AS WRITTEN, so it fires in a single-file program too: one more reason
  not to cargo-cult `public` there (gotcha 1). The shape it retires is a value a
  caller can hold and cannot NAME — which used to compile on the value path and
  fail on the PLACE path with an unrelated `__window` type mismatch.

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
`try_append_bytes`, `try_insert`. `try_` is the ONE spelling (design
123 renamed `Box.make_or` -> `try_make`; `Channel.try_receive` is unrelated — a
non-blocking poll, and since design 234 §4 the prefix means THAT and nothing
else: the non-blocking variant of an operation that could otherwise block,
shaped `Result<T?, E>` where `Ok(None)` is "nothing yet", or a plain `T?` where
there is no error path at all (`SpinLock.try_lock`, `Once.try_get`)). **`Channel.send` LEFT this policy with design 234** and is
where the whole tier is going: it reports BOTH failures as values in one error
type — `Err(Closed)` and `Err(Alloc(e))`, the second carrying the `AllocError`
— and `try_send` RETIRED with the split (it existed because `send`'s one error
slot was already spent on `Closed`, so the allocator had nowhere to go but a
panic, and `try_send` was the mirror image; neither could carry the other's
failure, which is what DQ-230b asked). `try! ch.send(v)` is a
pre-234 `send` and `ch.send(v)` handled is the new shape; a call to `try_send`
means the code predates Aug 22. A `try_` op is ALL-OR-NOTHING: on `Err`
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
is `T`, not `T?`, for the same reason. **`Mutex.lock` hands back the closure's
OWN result** — `lock<R>(body: (&var T) sync -> R) -> R`, the same shape
`SpinLock.lock` has (M1 landed; DF-123c is closed, and `Arc<Mutex<T>>`
forwarding reaches the method-generic `lock` too):
```saw
let n = shared.lock({ c in c = c + 5  c })   // shared: Arc<Mutex<Int>> -> n == 5
```

## Systems/embedded corner
`static NAME: T = const_init` (Sync-only, immortal, and NEVER OPTIONAL —
DF-226f, Aug 17: `static SLOT: Int? = 7` is refused by the rule, since a
static is fixed at compile time and so always present; only the static's
OWN type, an optional FIELD is fine, and no auto-wrap was added); `Atomic<Int>`;
allocator type params `Vector<T, A: Allocator = GlobalAllocator>`, `Box<T, A>`,
slab in std/slab.saw; `UnsafeMemory<T, Device|Normal>` for MMIO
(volatile, RO/WO markers);
- **GLOBAL STATE: five tools, not interchangeable (designs 149 + 186).**
  Pick by the SHAPE of the state, not by convenience:
  - **`Atomic<Int>`** — single-word state several tasks update
    independently. Still the recommendation everywhere it fits.
    **NoCopy** (design 202), on `SpinLock`'s terms and for the same
    reason: a copied atomic is a SECOND counter with its own word, so a
    `fetch_add` through one is invisible through the other. SHARE one —
    a `static`, or a `&Atomic<Int>` param — never `let b = a`. A struct
    with an `Atomic` field declares its own policy
    (`extension Stats: NoCopy {}`), the error naming the field.
    Statics are unaffected and `move` still works: `NoCopy`, not
    `NoMove`, since nothing pins an atomic's address.
  - **`SpinLock<T>`** (`import std.spinlock.*`) — state several THREADS or
    cores genuinely share where there is no OS: one word + the payload, no
    allocation, so it works FREESTANDING. `static LOCK: SpinLock<Counters>`
    (NO initializer — zero IS unlocked + zeroed payload). `lock({ c in
    ... })` / `try_lock` hand out `&var T` and return the body's own
    result; the body is `sync` ENFORCED (suspending under a lock is a
    compile error, not a livelock). NoCopy, so it cannot be captured into
    a closure — reach one through a static or a `&` param. Needs real
    target atomics: on rv32i, naming one is a compile error pointing at
    `--target-features +a`. Short critical sections; a waiter burns its
    core.
  - **`Mutex<T>`** (`import std.mutex.{Mutex}`, HOSTED) — the same shape
    where a waiter should SLEEP rather than spin. Since design 186 it is
    one inline word (`os_unfair_lock` / futex), allocates nothing, has no
    `deinit` and no `try_make`, and zero is unlocked — so `static
    REGISTRY: Mutex<Int>` works with no initializer exactly as `SpinLock`
    does. Blocks the calling THREAD; not reentrant.
  - **`Once<T>`** (`import std.once.*`) — state COMPUTED once at a moment
    the program picks, then read as a plain value. `static LIMITS:
    Once<Limits>` (zero is UNSET), `LIMITS.set(...)` once, `LIMITS.get()`
    after. A second `set` PANICS, and so does a `get` before any `set`
    (`try_get() -> T?` is the inspectable twin) — a caller-checkable bug
    is a fault, not a status. Readers are SAFE functions.
  - **`unsafe static var NAME: T = init`** — COMPOUND state genuinely
    MUTATED throughout, whose consistency spans words (a `[Slot; 64]`
    handle table, a bitmap+queue pair, an arena region) and rests on a
    serialization argument the compiler cannot see (interrupts off, single
    core, boot only). Assignable by name, `&var`-lendable, exempt from
    Sync. NAMING one triggers design 130's rule, so every touching
    function is declared `unsafe` and reviewed. `var` and `unsafe` come as
    a pair — each half alone is a clean error. Prefix position, like
    `unsafe struct`. Trivially-destructible types only (v1). **Reach for
    `Once` first**: `var` should mean what it says.
- **A ZERO static costs no image bytes** (design 149): a bare declaration
  or an all-zero initializer (`static ARENA: [UInt8; 65536] = [0; 65536]`)
  is zerofill in BOTH profiles. Declare the region at its real size.
- **A STATIC INITIALIZER IS A CONSTANT EXPRESSION (design 186).** Three
  tiers and no others: (1) zero-init, the bare declaration; (2) whatever
  the const evaluator folds — arithmetic, the bitwise operators,
  `sizeof`/`alignof`, `Int.max`, a raw-backed enum case, an EARLIER module
  static — plus memberwise aggregation over those; (3) anything COMPUTED
  is refused, and the error names the two spellings that work (`Once<T>`
  for set-once, `unsafe static var` for mutated-throughout). So
  `static PAGE_MASK: Int = (1 << 12) - 1` compiles now — that was
  DF-185b's refusal. Initializers fold in DECLARATION ORDER, so one may
  name the statics above it and a forward reference is a clean error
  naming the order. Write the size once and derive the rest:
  ```saw
  static PAGE_SHIFT: Int = 12
  static PAGE_SIZE: Int = 1 << PAGE_SHIFT
  static PAGE_MASK: Int = PAGE_SIZE - 1
  ```
  FIELD AGGREGATION FOLDS, USER `init` BODIES DO NOT: `Region(bytes:
  PAGE_SIZE, pages: 1)` is a constant and `Region(pages: 1)` through a
  hand-written `init` is not, even where the body visibly would fold.
- **INTERIOR MUTABILITY: the wrapper idiom (design 186).** A `&self`
  method that WRITES needs an `UnsafeMutableInterior<T>` field. That is
  the one primitive; it holds an inline `T` (no wrapper cost, and
  `sizeof<Counter>() == sizeof<Int>()` below), and its one accessor is
  `ptr(&self) unsafe -> UnsafePointer<T>`. Carrying one makes a type
  CELL-CARRYING, which is what buys the guarantee: **a cell-carrying
  receiver arrives BY POINTER even at `&self`**, so the write reaches the
  caller's storage instead of a copy. Every other `&self` still arrives BY
  VALUE (the `FixedBuf.ptr()` gotcha). Four parts, and the third and
  fourth are not optional:
  ```saw
  struct Counter { cell: UnsafeMutableInterior<Int> }

  extension Counter: UnsafeSync {}          // cell-carrying derives no Sync

  extension Counter {
      public init(start: Int) unsafe -> Counter {
          Counter(cell: UnsafeMutableInterior(start))
      }
      func _at(&self) unsafe -> UnsafePointer<Int> { self.cell.ptr() }  // ONE helper
      public func value(&self) unsafe -> Int { self._at()[0] }
      public func bump(&self, by: Int) unsafe { self._at()[0] = self._at()[0] + by }
  }

  static HITS: Counter
  ```
  Callers need no ceremony — an `unsafe` function is callable from safe
  code — so `HITS.bump(by: 1)` sits in a safe body, which is the whole
  payoff. `Atomic`, `SpinLock`, `Mutex` and `Once` are all written this
  way. A cell-carrying `static` is never rodata, and it derives no `Sync`:
  the refusal names the missing declaration AND the blocking field. `Send`
  still derives (a cell moves fine). A cell is NoCopy as a VALUE, but a
  cell FIELD contributes its `T`'s copy tier — say `extension Counter:
  NoCopy {}` yourself if a copy would be a bug, which is exactly what
  `Atomic` says (design 202). A DECLARED policy on the field's own type
  wins over the clause, so an `Atomic` field cascades `NoCopy` upward
  while an `UnsafeMutableInterior<Int>` field does not.
- **`UnsafeSync` / `UnsafeSend` are the DECLARED thread-safety assertion**
  (design 186). `Send`/`Sync` stay derivation-only (`extension X: Sync` is
  still rejected); these two REFINE them, so a declared conformance
  satisfies a `T: Sync` bound through the parent and generic code never
  names the assertion. Legal only where the derivation FAILED and every
  blocking field is unsafe-typed (a cell, an `UnsafePointer`, an
  `UnsafeMemory`) — asserting past a SAFE non-Sync field is refused naming
  the field, and asserting where the derivation already succeeds is
  refused too. Conditional headers work and their bounds are re-checked
  per instantiation (`extension Mutex<T: Send>: UnsafeSync {}` promises
  nothing about `Mutex<File>`). They appear in EXACTLY ONE position, the
  conformance header: `T: UnsafeSync` as a bound and `any UnsafeSync` are
  both clean errors pointing back at the property.
- **`--freestanding` on aarch64 implies `--target-features -neon,-fp-armv8`**
  (design 172). An AArch64 core traps Advanced SIMD at EL1 out of reset
  (`CPACR_EL1.FPEN` = 0) and LLVM uses `q` registers to move a struct, so a
  kernel faulted on its first block copy — before the vectors that would
  have reported it were installed. `--target-features` OVERRIDES completely,
  so a kernel whose boot code enables FPEN asks for `+neon,+fp-armv8` by
  name (and then owns saving those registers across a context switch). No
  other target gets a profile default: riscv32's `+m,+a,+c` is a fact about
  the PART, not about the profile.
- **A package can BE the runtime** (design 149): `[package] runtime = true`
  in Saw.toml lets it `@export` the frozen `__saw_rt_*` seams, links no
  runtime beside it, and CHECKS each seam's signature against
  `sawc/rt/ABI.md` — a wrong arity or width is a compile error naming the
  document rather than a clean link and a wrong answer at run time.
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
- **`FuncPointer<F>` IS the callback/entry-point type (design 226)** — one word,
  the address of code whose signature is `F`, and exactly a C function pointer
  at the ABI. Functions are still NOT first-class values (DF-172a is open);
  this is the typed hole. `F` must be a function type and must be **`sync`** (a
  suspending body needs a frame a bare address cannot carry), refused AT the
  type wherever one is written. A **SAFE** type — construction is closed, so an
  API receiving one owes no `unsafe`, it copies bitwise and `Send`/`Sync`
  derive. TWO construction forms:
  ```saw
  let f: FuncPointer<(Int) sync -> Int> = { n in n * 2 }   // zero-capture literal
  let g: FuncPointer<(Int) sync -> Int> = doubled          // named `sync` function
  f(21)                                                     // an ordinary call
  ```
  The literal may capture NOTHING — no environment travels with a code address —
  and what counts is what the body NAMES: an enclosing local, or a method's
  `self`, with or without a `[x]` list. The refusal says so ("pass the state
  through the argument parameter"). Form 2 wants a **declared `sync`**,
  non-generic function; the `FuncPointer` type selects among overloads, and a
  generic name is refused (one pointer, one compiled body). Both forms work in
  every expected-type position: argument, annotated `let`, struct field init,
  `return`, and a **`static`** — the address is a link-time constant, which is
  what lets a dispatch table be a static and be read as `TABLE.run(x)`.
  Zero-alloc by construction (passes `--no-hidden-alloc`). `FuncPointer<F>.from_raw(addr:
  UnsafePointer<UInt8>)` is the ONE forging member, `unsafe` by the ordinary
  trigger, for a callback arriving from C and a loader reading an entry PC.
  A C callback's `F` names raw pointers, so it carries `unsafe` by design 136's
  rule while the `FuncPointer` stays safe:
  ```saw
  extern "C" {
      func qsort(base: UnsafePointer<Int32>, nmemb: UInt, size: UInt,
                 compar: FuncPointer<(UnsafeConstPointer<Int32>,
                                      UnsafeConstPointer<Int32>) unsafe sync -> Int32>)
  }
  ```
  ONE GOTCHA LEFT. **DF-226c**: form 2 takes a BARE name, not `mod.f`, so a
  cross-module source needs the selective import (`import mod.{handler}`)
  rather than the whole-module one.
  **A CLOSURE BODY'S RETURN POSITIONS TAKE THE EXPECTED TYPE (DF-226a, fixed
  Aug 17)** — so an `Int32`-returning comparator writes `-1`, not `-1i32`, and
  the no-suffix-where-an-expected-type-is-in-force idiom holds inside a closure
  exactly as it does everywhere else. The tail expression, the `if`/`match` arm
  results inside it, and a `return` in the body all adopt it, and an array
  literal tail shapes into a `Vector` return. Treat it as working now and
  SUSPECT in older builds, where the tail adopted NOTHING: a bare literal at a
  fixed-width return stayed platform `Int` and died in codegen (`ret i64` from
  an `i32` function), and `{ x in [1, 2, 3] }` against a `Vector<Int>` return
  was refused as a `[Int; 3]`.
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
BINDS includes a binding nothing reads — a `match` arm naming an unsafe payload
(`case Filled(t) -> 1`) has the value in scope either way — and a DEFAULT
parameter value counts as signature contact even when the parameter's own type
is safe (`func f(a: Int = raw.value())`, design 193).
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
**A CONFORMER OF AN `unsafe` REQUIREMENT MUST DECLARE IT (design 188)** — a
safe-declared body satisfying `func peek(&self) unsafe -> Int` is a clean error
at the conformance, since a caller reaching it through the requirement is
promised the unsafe contract. The reverse stays legal: an `unsafe`-declared body
satisfying a SAFE requirement is the redundant form above.
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
**A POINTER PLACE TRANSFERS BOTH WAYS, AND BOTH SPELL `move` (design 219).**
`ptr[i] = move value` was always the placement write; `let x = move ptr[i]` is
now the read, legal (a scoped carve-out from the no-partial-moves rule — a
pointer place tracks no occupancy for a move-out to corrupt) and REQUIRED for an
ExplicitCopy/NoCopy element, whose unspelled read is refused with ``this read
transfers ownership — spell it `move buf[index]` `` (an ExplicitCopy element may
also `ptr[i].copy()`, which leaves the slot occupied). The pointer binding is
untouched; keeping track of which slots are still live is yours, exactly as for
the write side. `move v[0]` on a Vector/field/tuple element stays the design-35
error — those places ARE tracked, and `swap_out`/`take()` are their move-outs.
**PREFIX `*` IS THE SAME PLACE, SPELLED (design 219).** `*p` and `p[0]` are ONE
production — parser sugar, so the read, the store, `(*pt).x`, `&var *p` and
`move *p` all work exactly as the index form does. Reach for it on a
SINGLE-OBJECT pointer, where `p[0]` reads like an array index and `*p` says what
is meant. Disambiguated by position like unary `-` (`a * *p` is both), and it is
NOT a user-definable prefix operator — that surface stays closed.
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
**Write your own accessor's panic in the house wording** (DF-249a):
`panic("Bag.[]: index out of range: {} (len {})", i, self.len())` — the family is
`<what>: index out of range: <i> (len <n>)`, with a range accessor spelling both
bounds (`range out of range: {}..{} (len {})`). Design 137's `{}` arguments, not
interpolation, so the message costs no allocation and works freestanding.
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
- **A `&self` METHOD MAY NOT WRITE ITS RECEIVER** (design 146 + 176). A `&self`
  receiver arrives by VALUE, so the write lands in the callee's copy and
  vanishes. Both spellings are compile errors: the DIRECT write
  (`self.hits = self.hits + 1`, `self.hits += 1` — unchecked until design 176,
  a silent no-op for years) and the `&var self.<field>` PROJECTION that hands
  the write to someone else. Fix: declare `&var self`, or `borrows -> T` if you
  meant to lend the place. The rule covers storage INSIDE the receiver — a
  field, a nested field, a tuple element, an optional payload, an inline
  `[T; N]` element. Storage the receiver only POINTS AT is not covered, since
  the copy shares it: `self.cells[i] = v` on a `Vector` field writes the
  caller's element and is fine, and so is a write through an `UnsafePointer`
  field (std's `Task.cancel`).
  **A PLACE WINDOW is the fourth spelling** (design 200, DF-176c): where the
  field's type publishes a `borrows` accessor, `self.grid[0] += 100` opens an
  EXCLUSIVE window on the copy and is the same error — a silent no-op until
  Aug 10. Reads are untouched (a shared window lends read-only), and what
  decides the rest is where the accessor lends FROM, so the carve-out holds
  through a window too: `Vector.[]` lends out of the heap buffer, so
  `self.rows[0][0] += 100` reaches the caller's element and compiles.
  **It holds in a `borrows` body, prologue and epilogue included — and that is
  where it bites hardest**: an accessor's receiver travels by POINTER, so a
  field write there does not vanish, it LANDS, and a read through a shared
  window mutated a `let` root (DF-175a). An epilogue that genuinely counts
  reads declares the accessor `&var self`, which is STRICTER — every use site
  then borrows the receiver exclusively, reads included. In a FLAVORED accessor
  the third out is `#lend_var`: gate the mutation and only the exclusive
  specialization runs it. The place-window spelling is the ONE exception there
  and is intended (design 200 ratified it): a window write in a prologue or
  epilogue lands for the same by-pointer reason, and `#lend_var` is how you
  keep it out of the shared specialization.
  **A `&var self` METHOD CALL is the same error, on `self` OR on a FIELD of it**
  (DF-179b, DF-176b). `self.reset()` takes the whole receiver exclusively, which
  is the one thing `&self` promises not to do; `self.cells.push(9)` runs against
  the copy's `Vector` header, so the caller sees no new element — and since the
  copy and the original share a buffer, a push that does not reallocate writes
  into storage the caller owns while the caller's `length` stays behind. Both
  were unchecked until Aug 7-8, and the borrows-body forms really did mutate a
  `let` root.
  **THERE IS NO INTERIOR-MUTABILITY EXEMPTION** — design 186 dissolved the
  `{Atomic, SpinLock, UnsafeMemory}` list it used to be, and found it protected
  nothing. `self.n.fetch_add(1)`, `self.cell.lock({ ... })` and a user cell
  wrapper's `self.hits.bump()` are all `&self` METHODS, which this rule never
  refused; what makes them reach the caller's storage is the CELL-CARRYING
  by-pointer receiver, not an exemption. A `&var self` method on a field stays
  refused whatever the field holds — including a wrapper around a cell — since
  it takes the whole wrapper, sibling fields included. The indirection
  carve-out is unchanged and independent: `self.rows[0].push(9)` reaches a heap
  element the copy shares and is fine.
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
  wire-safe choice; a raw-ordered Comparable derivation does not exist. A
  backing survives GENERICS (DF-232i): `enum Code<T>: UInt8` carries its
  declared values into every instantiation, so two instantiations cast to the
  same byte — until Aug 17 a generic one silently emitted ORDINALS instead, so
  distrust `as` on a generic backed enum in an older build.
- **WIRE MATH IS CONST MATH (design 185).** `& | ^ << >> ~` fold in a constant,
  so a bit position, a mask or a page size is written as the arithmetic that
  produces it in EVERY const position — a `static_assert`, an array length, a
  repeat count:
  ```saw
  static PAGE_SHIFT: Int = 12
  static_assert((1 << PAGE_SHIFT) == 4096, "4K pages")
  static_assert(((addr + 0xFFF) & ~0xFFF) == 0x2000, "align up")
  struct PageTable { entries: [UInt64; 1 << 9] }
  var page: [UInt8; 1 << PAGE_SHIFT] = [0; 1 << PAGE_SHIFT]
  ```
  Folded at the TARGET's integer width in the signed platform-`Int` domain:
  `1 << 63` is `Int.min` on a 64-bit target and `1 << 31` is `Int.min` on
  riscv32, `~0` is `-1` (mask it back — `0xFF & ~0` is 255), and a shift count
  outside `0..<width` is a compile error rather than a folded surprise.
  Precedence is Saw's, NOT C's: the bitwise tier sits BELOW comparison, so a
  compared mask needs its parentheses (`(a | b) == 3`, never `a | b == 3`).
  **FLAG ENUMS**: a raw-backed case is a constant, so `Perm.Read | Perm.Write`
  folds — and its type is the BACKING INTEGER, never the enum, because 3 need
  not be a declared case (typing it `Perm` would break `from(raw:)` and
  exhaustiveness). An enum is a set of tags; a bit set over them is the integer
  they are tags for, and Saw ships no OptionSet type. A FIXED-WIDTH SLOT IS A
  CONST POSITION (DF-240a, ruled Aug 21 — an amendment to 185 unit 4, which
  widens WHICH positions are const, not what a constant means), so an annotated
  `let`, a field, an argument, a `return` and an arm all fold a combination and
  range-check it against the declared type. Outside a const or adoption
  position the operands are enum-typed VALUES carrying no number and the
  operator is REFUSED — write `(a as UInt8) | (b as UInt8)`, the same total
  projection design 145 gives.
  ```saw
  enum Perm: UInt8 { case Read = 0x01, case Write = 0x02, case Exec = 0x04 }
  static_assert((Perm.Read | Perm.Write) == 3, "rw")   // UInt8, folds
  let mask: UInt8 = Perm.Read | Perm.Write             // 3 — the slot is const
  let flags = (held as UInt8) | (Perm.Exec as UInt8)   // runtime: say `as`
  ```
  The `let mask` line was refused before Aug 21, so a build that rejects it
  predates the amendment.
  The generic-ARGUMENT position keeps the smaller design-148 grammar (`>` is the
  shift token, so `FixedBuf<1 << 8>` cannot parse) — write `FixedBuf<2 * 128>`
  or a `static`.
- **`static` IS REQUIRED ON A STATIC METHOD, and there is no inference**
  (design 236). Write the keyword at the declaration and call it on the TYPE:
  ```saw
  extension Bag {
      static func make(seed: Int) -> Bag { Bag(n: seed) }
      func count(&self) -> Int { self.n }

      func dup(x: Int) -> Int { x * 2 }
      // error: method `dup` has no receiver — add `&self`/`&var self`, or
      //        declare it `static func` if a static was intended
  }
  ```
  Three refusals, all at the DECLARATION: a self-less non-`init` `func`
  (the fixit names both readings, because a forgotten `&self` and an intended
  static are indistinguishable to the compiler); a `static` method that takes
  `&self`/`&var self` (the mirror); and `static init` (an `init` is exempt by
  construction and already called as `Bag(...)`). Order is `public static
  func`. Struct and ENUM extensions, generic extensions and TRAIT requirements
  are all covered, and a conformance must MATCH kinds — a static requirement
  takes a static, an instance requirement an instance method, each direction
  its own error. Module-level `func`s are not methods and are untouched,
  `@export`ed C-ABI seams included; `static` at module scope keeps its
  design-149 meaning (a VARIABLE — the declaration head continues into a name
  and a colon, the member head into `func`). Staticness WAS inferred from the
  missing receiver until Aug 20, so a pre-236 corpus writes the bare form.
- **A STATIC method is called on the TYPE, never on a value** (DF-217q):
  `Bag.make(seed: 5)`, not `b.make(seed: 5)`. A static has no receiver for a
  value to become, so the instance spelling is a clean error naming the type
  spelling — it used to mis-bind the labels instead
  (``no parameter named `seed```) or reach codegen and fail the verifier. Same
  for an enum's statics. A static and an instance method MAY share a name; each
  call shape picks the one it can mean. EVERY receiver spelling is refused,
  a FIELD ACCESS (`self.layout.clean_all()`, `h.inner.solo(3)`) included —
  that one used to take the module-qualified `mod.Type.method()` route, where a
  nullary static silently dropped the receiver and an arity-1 one was a codegen
  ICE, so treat it as caught now and SUSPECT in older builds (DF-236a).
- **AN ENUM VARIANT IS NAMED ON THE TYPE TOO** (DF-236a's sweep) — `Color.Red`
  and `Color.Custom(r: 3)`, never `value.Red` / `value.Custom(r: 3)`. A variant
  BUILDS a value, so a receiver has nothing to become, and the error says so
  with the type spelling. Through a field at enum type (`h.c.Red`) both
  spellings used to construct a fresh value and discard the receiver, silently;
  same vintage, same suspicion in older builds. To ask which variant a value
  holds, `match` it.
- **ENUMS TAKE EXTENSIONS, same as structs** (design 145): instance methods with
  `&self`/`&var self` (`match self` is the idiomatic body, `self = Other` the
  whole-value replacement), `static func` methods, hand-written trait
  bodies (Printable/Error/your own), `@synthesize` derivations, a hand-written
  `deinit` inside the copy policy, and per-instantiation methods on a generic
  enum. Import-scoped lookup and the orphan rule apply unchanged. The ONE
  difference: no `init` — the cases are the constructors, and writing one is a
  clean error naming a static method as the way to compute which case to build.
- An escaping closure (bound/returned/stored/`spawn`) is **Copy**
  over a refcounted heap env (like String/Arc): `let g = f` is a free
  refcount bump (both valid), and the captures are torn down exactly once
  when the last owner drops. Copying a struct/`Vector` that holds a
  closure retains the env; capture-less closures are trivially copyable.
  `move f` still transfers ownership. A closure also satisfies the generic
  `Copy` bound, so `Vector<() -> Int>` is copyable — `.copy()`/`.get()` each
  retain the element env exactly once (deinit-once through copy).
- **A `return` in a closure returns FROM THE CLOSURE** (design 213), checked
  against the closure's own return type — the enclosing function's signature has
  no say. So a `(Int) sync -> Void` closure can `return` early to skip an
  element, and a `(Int) -> Int` one can `return 99` while the function around it
  returns a `String`. Errors follow the same boundary: `try` inside a closure
  propagates out of the CLOSURE (so the closure's return type must be the
  `Result`), and an enclosing `try {} catch {}` does NOT extend into a closure
  body — give the closure its own. The return type comes from the slot the
  closure is passed to; with no expected type the `return`s are checked against
  each other, and a body whose every path returns types as what it returns
  rather than `Void`. Until this landed all of it was read off whichever
  function lexically contained the closure (and, in a suspending body, off the
  coroutine frame's `Poll`), so treat closure `return` as working now and
  SUSPECT in older builds. Corpus note: the codebase's own idiom is still the
  value-expression tail (`if`/`match` as the closure's last expression) — a
  census of all 2003 tracked `.saw` files found zero closure `return`s — so
  reach for `return` when it reads better, not by default.
  That gap is CLOSED (DF-213b/DF-232h, Aug 22): a closure declared
  `-> Result<T, E>` auto-wraps its TAIL value exactly as a named function does,
  so `{ x in 12 }` and `{ x in return 12 }` mean the same thing. `return v`
  was the workaround. Its last corner closed with DF-244b (Aug 22): a bare
  `None` tail at a `Result<T?, E>` types itself now, in a closure and in a named
  body alike.
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
- **A closure body MAY NAME `self`** (design 216) — and a `&T`/`&var T` PARAMETER
  of the enclosing function. Both are captured BY BORROW: the body reads the live
  value, and through `&var self` / a `&var T` param it WRITES the caller's
  storage. This used to be an ICE (`'self' not found in current scope`) for every
  closure naming `self` in any method, which is why no std code does it.
  ```saw
  extension Counter {
      func viaFree(&self) -> Int { run_int({ self.n + 1 }) }
      func bump(&var self) -> Int { run_int({ self.n = self.n + 10  self.n }) }
  }
  ```
  ONE rule over three spellings, because a receiver IS a reference: **a capture
  that lowers to a pointer into the enclosing frame is legal only in a closure
  passed directly to a non-escaping parameter** — `[&x]`/`[&var x]`, a reference
  parameter, and `self` alike. Escaping is refused:
  ```saw
  func handOut(&self) -> () -> Int { return { self.n + 3 } }
  // error: an escaping closure cannot capture `self`: a method's receiver is a
  // borrow of storage the CALLER owns ...
  func make(r: &Thing) -> () -> Int { return { r.x + 1 } }
  // error: an escaping closure cannot capture `r`, a reference (`&Thing`) ...
  ```
  GOTCHA: `let f = { self.n }` counts as ESCAPING even when you call `f()` two
  lines later — the env is on the heap either way and the check reads the
  position, not the eventual use. Pass the closure straight to the call that runs
  it. The two outs the diagnostic names: hoist what the body needs into locals
  ahead of the closure, or take the receiver as an explicit closure parameter
  (`body: (&Counter, Int) sync -> R`, called `self.run({ c, v in c.n + v })`) —
  the second is what a std-side by-borrow callback wants. A CONSUMING `self`
  receiver (no `&`) is an owned binding and captures by value as usual.
  Treat the ref-param half as caught now and SUSPECT in older builds: an escaping
  closure capturing a `&T` param used to compile to a raw pointer into a dead
  frame with no diagnostic.
  The capture can also be WRITTEN, behind a borrow sigil: `[&self]` and
  `[&var self]` mean what the implicit one means and meet the same rule.
  `[&var self]` needs a `&var self` receiver (a shared receiver has no exclusive
  borrow to give); `[&self]` in a `&var self` method NARROWS to shared, and a
  write through it is then refused as it would be in a `&self` method. Only the
  `&` forms exist — `[self]` and `[move self]` are parse errors, because the
  receiver's own mode decides the capture's.
  The enclosing method may be sync OR SUSPENDING (design 218 stage 3 closed
  DF-216g); both read the live receiver. Treat the suspending half as working
  now and SUSPECT in older builds, where it was an ICE. In a suspending body the
  receiver is reached through a place window, so `self.n = self.n + 10` inside
  such a closure is two windows on one root — which is fine since Aug 22
  (DF-218j: the right-hand side's window closes before the target's opens, which
  is the order an assignment already had). Before that it was refused with a
  copy error and `self.n += 10` was the workaround, so distrust the long form in
  an older build.
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
  tier: bitwise for trivial, RETAIN for Copy, clean ERROR for
  ExplicitCopy/NoCopy. Both `v[i]` and `d[i]` PANIC out of range.
  **`Vector.get(i)` is the `None`-returning twin** — a conditional lend, the
  same lowering: `if let e = v.get(i)` is a value read (so the copy tier
  applies), `v.get(i)!.count += 1` opens an exclusive window, and the absent
  path opens no window at all. A move-only element is REFUSED at a value read
  now; it used to come out as a non-retained alias two lookups double-freed.
  `swap_out(i, v)` moves a slot out; `with_ref`/`with_var_ref(i, body)` are
  still the multi-statement / long-window spellings (a place window is ONE
  expression) and the only way to hold a borrow across several statements.
  **`Map` has the subscript too** (DF-146d): `m["k"] borrows -> V?`, a
  conditional lend over the slot's enum payload. `m["k"]!.n += 1` writes the
  stored value, `m["k"]!.push(x)` grows a `Vector` value where it sits (no
  read-modify-write of the whole entry), `m["k"] ?? d` and `if let _ = m["k"]`
  take the absent path with no window at all. **`m.get(k)` IS that same
  accessor** under a named spelling (design 176): one conditional lend, two
  names, same copy-tier rule on a value read. It used to hand back an owned
  `V?`, which for a NoCopy value was a non-retained alias two lookups double-freed
  (DF-146j) — reach one through the window (`m.get(k)!.method()`) or take it out
  with `remove`. `Set` has no
  element accessor on purpose: its elements are the table's keys, and a write
  through one would change an element's hash.
  `iter()`/`enumerated()` carry a `T: Copy` bound (design 122): `next()` yields
  an element the consumer OWNS, so a NoCopy element is reached through a place
  or `with_ref`, never a `for` loop. Since design 130's accessor rule,
  `set`/`swap`/`swap_out`/`with_ref`/`with_var_ref`, `String.byte_at(i)` and
  `String.substring(s, e)` ALL PANIC out of range — no silent no-op
  (`set`/`swap` used to be) and no clamp (`substring` used to be). An empty
  `substring(i, i)` is still legal; a REVERSED range panics.
- **RENDERING or COMPARING a place is a BORROW, not a read** (DF-218i,
  DF-248d). Both positions hand the element to a `&self` callee and keep
  nothing — `format(&self, into:)` for one, `equals`/`compare`'s `other: &Self`
  for the other — so the copy tier never comes into it and a move-only element
  prints and compares like an `Int` one:
  ```saw
  print("{v[0]}")   print(v[0])   print("{}", v[0])    // every rendering slot
  v[0] == w[0]      v[0] < w[0]                        // all six operators
  ```
  Rendering covers an interpolation operand anywhere, a single-argument `print`
  of a `Printable`, and the format arguments of `print`/`panic`/`assert`. Treat
  both as working now and SUSPECT in older builds, where each was ``lends a
  place of type `Res`, which is move-only`` — printing or comparing a
  `Vector<Res>` element was simply unwritable, while the same operation over two
  move-only LOCALS compiled.
  GOTCHA: the window spans the whole expression that asks for the borrow, so
  anything else in it is inside the window — an `assert` condition naming the
  place's own root (`assert(v[0].n == 1, "{}", v[0])`) wants a `let` of its own
  first, and so does the two-places-ONE-container comparison `v[0] == v[1]`
  (DF-248a). The error there TEACHES the split, because the assignment shape one
  line up compiles.
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
  PRESENCE IS TIER-INDEPENDENT AT EVERY SPELLING (design 218, DF-218a) — a plain
  optional, a conditional lend (`v.get(i)`), and an UNCONDITIONAL lend whose
  element is itself optional (`Slot<T>.value()` at `T = Res?`) all answer the
  same way at every tier. That third one reads like a value read and is not: the
  lend is unconditional, so the optional is the ELEMENT rather than the lend's
  own presence. It used to fall through to the value path — a NoCopy payload
  could not be presence-tested AT ALL there, and a Copy tier paid a retain — so
  treat it as working now and SUSPECT in older builds. It desugars to
  `is_some()`, which is the same question spelled out.
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
  `run()` AND `output()` ARE BOTH COOPERATIVE (designs 182 + 187) — `run` parks
  on the child's exit, and `output` additionally drains the stdout pipe on a
  worker thread (the seam is `blocking`, so design 183 offloads it), so a task
  running or capturing a child no longer starves its siblings and no thread is
  spent waiting. Consequence for callers: BOTH SUSPEND, so a `sync` function can
  call neither. `output()` is spawnable into a `threads: N` group. Cancelling
  the task ends the WAIT, not the child (which keeps running, unreaped);
  `ProcessError.cancelled()` distinguishes that Err from a launch failure, and a
  cancelled `output()` answers `None`.
  `env(name:value:)` (design 155) sets ONE environment variable for the child,
  under `arg`'s discipline — the name and the value are bytes the child receives
  verbatim, nothing parsed or expanded. The child INHERITS this process's
  environment and the overrides win; a second `env` for one name replaces the
  value, so the child never sees a variable twice. `env_count()` reports how
  many. A name that is empty or contains `=` panics (it could never be a
  variable). `merge_stderr()` sends the child's stderr wherever its stdout goes
  — into the capture under `output()`, plain `2>&1` under `run()` — which is how
  a tool that runs children it EXPECTS to fail keeps its own output readable.
  Capturing stderr on its own is not expressible yet.
  ```saw
  var c = Command(program: python)
  c.arg("build.py")
  c.env("PYTHONHASHSEED", "1")   // this child only; everything else inherited
  c.merge_stderr()               // its diagnostics are not ours to print
  ```
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
  catch (design 153 sweeps the existing ones). The rule holds even when the
  numbers feed an API that takes raw integers: an `Atomic<Int>` comparing
  against a closed state set uses `State.Ready as Int` projections at the
  call sites, never a static family mirroring the enum — the enum stays the
  single source of the values, and no "the words agree" assert is owed
  (std/once.saw is the worked example). A module-level `static` is for a
  genuine standalone QUANTITY; std-module statics are NOT visible cross-module
  yet.
- **A SIZE GOES IN ONE PLACE, and that place is a `static` (DF-172j).** An
  `Int`/`UInt` static whose initializer FOLDS is a compile-time constant, so it
  may be an array length, a repeat count, a const generic argument and a
  `static_assert` operand — with const arithmetic composing over it. Write the
  size once and derive the rest; the named-array-type-plus-`sizeof` workaround
  is retired.
  ```saw
  static PAGE_SHIFT: Int = 12
  static REGION_SIZE: Int = 1 << (PAGE_SHIFT + 4)      // derives, design 186
  static_assert(REGION_SIZE % 4096 == 0, "the region must be page-aligned")
  struct Region { bytes: [UInt8; REGION_SIZE] }
  static ARENA: [UInt8; REGION_SIZE] = [0; REGION_SIZE]
  var half: [UInt8; REGION_SIZE / 2] = [0; REGION_SIZE / 2]   // in a body
  ```
  What does NOT fold: an `unsafe static var` (mutable), a static of a
  non-integer type, and one with no initializer — each a clean error NAMING
  which static and why (``the mutable static `ARENA_BYTES` is not allowed
  here``). A local shadows a static here as anywhere else, so a derived shadow
  is the runtime value it looks like. Cross-module follows visibility: a
  `public` static reached by `import dep.{REGION_SIZE}` folds, and so does the
  QUALIFIER spelling (`[UInt8; dep.REGION_SIZE]`, design 185 — it was a parse
  error until then, which is what DF-172l filed). A length that folds NEGATIVE
  is a clean error too (it used to reach LLVM as `[-1 x i8]`).
  **A LOCAL STATIC MAY DERIVE FROM AN IMPORTED ONE (DF-232g, fixed Aug 21):**
  `static SLOTS: Int = dep.EVENTS + dep.TIMERS` folds, in both the bare and
  the qualified spelling and mixed with local statics — which is what lets a
  derived size be declared APART from the numbers it derives from. Until then
  the same arithmetic was constant INLINE at the use site and not constant
  once given a NAME, and the refusal called a pure alias ``the computed
  static `S` ``, so a pre-Aug-21 kernel keeps every derived size in one file
  with its operands.
  **DF-185b IS CLOSED (design 186)**: `static MASK: Int = (1 << 12) - 1` and
  `static RW: UInt8 = Perm.Read | Perm.Write` both compile — a static
  initializer is a constant EXPRESSION now, and a const position, so the
  old advice to "write the number in the static and the arithmetic where it is
  used" is retired. See the statics tiers above for the one thing that still
  does not fold: a user `init` body.
- For a KNOWN C struct, declare a typed Saw struct (declaration-order natural ABI,
  design 58) as a stack local + `(&sa) as UnsafePointer<...>` for the syscall —
  never a raw byte blob; alignment comes free from the widest field. Only
  genuinely OS-divergent bytes need a compiler shim.
- Blade: `blade build/run/test/new/add/tree/update`; Saw.toml
  `[dependencies] name = { path = "..." }` or `{ git = "...",
  version = "1.2.3" }` (bare version = exact pin; no registry yet).

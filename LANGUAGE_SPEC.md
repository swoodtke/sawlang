# Saw Language Specification

> A systems programming language with Rust-style memory safety and Swift-style syntax

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
4. **Predictability** - Allocation is visible in the type, no garbage collection pauses, deterministic destruction. **No hidden allocations**, enforced by `sawc --no-hidden-alloc`: every allocation is named by the expression or by a type the author wrote, and the compiler allocating on its own authority is a compile error. Without the flag, three constructs allocate without saying so — an escaping closure's captured environment, a string interpolation's result buffer, and single-argument `print` of a user `Printable`. See [No hidden allocations](#no-hidden-allocations---no-hidden-alloc) for the site-by-site classification.
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

### Statement Boundaries

A statement ends at the end of its line. There are no semicolons.

Inside brackets a line break carries no meaning, so a list that does not fit on
one line wraps. This holds between `(` and its matching `)`, between `[` and
`]`, and inside a generic `<...>` list:

```saw
func total(
    first: Int,
    second: Int,
    third: Int,
) -> Int {
    first + second + third
}

func main() {
    let grid: Vector<Int> = [
        1, 2,
        3, 4,
    ]
    print(total(
        grid.get(0)!,
        grid.get(1)!,
        grid.get(2)!,
    ))                          // prints: 6
}
```

A trailing comma is allowed in the `(...)` and `[...]` forms — argument lists,
parameter lists, tuples, collection literals, and memberwise struct literals.
It is rejected in a generic list, which has no wrapping idiom to serve:

```saw
let bad: Vector<Int,> = [1]
// error: Parse error at 1:20: a trailing comma is not allowed in a generic
// argument list (it is allowed in `(...)` and `[...]` lists)
```

`{` and `}` are the exception. A block or closure is a statement container, so
line breaks inside one keep ending statements, including when the braces sit
inside a wrapped argument list:

```saw
let doubled = apply(
    values: v.copy(),
    f: { n in
        let scaled = n * 2      // two statements, two lines
        scaled
    },
)
```

An import's symbol list is the one brace pair that does wrap. It is a delimited
list rather than a statement container, so line breaks inside it are
insignificant and a trailing comma is allowed, exactly as in `(...)`:

```saw
import kcore.{
    console, pmp_reset,
    pmp_region,
}
```

The line break AFTER a closing bracket still ends the statement, so a wrapped
call never runs on into the line below it. A bracket that is never closed is
reported at the opener rather than wherever the parse finally gave up:

```
error: Parse error at 14:18: unclosed `(` — no matching `)` before the end of
the file (a line break inside brackets does not close them)
```

Suppression inside `<...>` applies only where the parser has committed to the
generic reading — a type annotation, a generic parameter list on a declaration,
or a call that supplies its type arguments explicitly (`first_of<Int, String>(…)`).
A `<` that turns out to be a comparison is never treated as a bracket, so
`show(a < b, a > b)` compares whether or not its arguments straddle lines.

### Variables and Mutability

```saw
// Immutable by default
let x = 42
let name = "Saw"

// Explicit mutability
var count = 0
count += 1

// Type annotations (optional with inference)
let pi: Float = 3.14159
var items: Vector<Int> = []
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
- **Same-scope redefinition** obeys the same mentions-rule (design 107):
  `var data = read(); let data = parse(move data)` in *one* scope is legal because
  the initializer mentions `data`; a non-deriving `let data = fresh()` after a
  `let data = …` stays the "already defined in this scope" error. The new binding
  **replaces** the old (with its own mutability — `let`↔`var` freely); if the old
  still owns a value at the point of replacement (a `.copy()` derivation), that
  value drops **at the redefinition point**, deterministically.
- A **`for`-loop variable** joins the rule too (design 107), with the **sequence**
  (the iterable) as the initializer analog: `for x in x.lines()` / `for i in 0..i`
  is a legal refinement, `for x in ys` under an outer `x` is a rename error. An
  enclosing loop variable is itself an enclosing binding, so a nested inner loop
  reusing the name non-derived is an error. (A `for` loop binds a single name;
  tuple destructuring in the header is not a supported form.)
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

// Generic functions with mutable-reference parameters. Mutation through a
// &var reference uses compound assignment, a mutating method, or whole-referent
// replacement (design 110): `a = b` overwrites what `a` refers to, in place.
func replace<T>(a: &var T, b: &var T) {
    a = b
}
// A true in-place swap is not writable this way — moving out of a reference is
// rejected, so there is no way to park the old value. Use `Vector.swap(i, j)`.

// Functions with default parameter values (implemented, design 53)
func greet(name: String, greeting: String = "Hello") -> String {
    "{greeting}, {name}!"
}
greet("Sam")             // greeting defaults to "Hello"
greet("Sam", "Hi")       // explicit

// Trailing closure syntax (implemented — `numbers` is a Vector<Int>;
// Vector.map infers U from the closure's return type, design 93)
let doubled = numbers.map { x in x * 2 }
let tripled = numbers.map { $0 * 3 }  // shorthand parameter form
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

The one deliberate exception is **optional chaining** (`designs/111`, see
[Optionals](#optionals)): when a `?` hop short-circuits, the REST of the postfix
chain is skipped — including the argument expressions of a skipped method call, so
those arguments (and their side effects) do not run. This is observable and
intentional.

A **suspending** argument, receiver, or operand does not change this order
(`designs/120`). The compiler rewrites such a call into evaluation-ordered
temporaries before embedding the suspension, so `f(a(), b())` with either call
suspending still evaluates `a()` fully, then `b()`, then calls `f`.

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
3. **Concrete beats generic** — `f(Int)` beats `f<T>(T)`. When a name is
   OVERLOADED and no concrete candidate matches, argument-type inference
   (design 93 + 105) is run PER generic candidate: if EXACTLY ONE generic
   overload both solves its type arguments and type-matches, it is picked; two or
   more that solve are a clean ambiguity error listing the candidates and their
   solved type args (`give explicit type arguments or labels`). A concrete
   candidate that matches always wins over any generic one, so an inferred
   overload never changes the meaning of a call that already resolved.

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

### The entry point

**Status: implemented.** A program starts at `main`, a top-level function
taking no parameters. Its return type is the program's **exit status**, and it
may be exactly one of four:

| Written | Exit status |
|---|---|
| `func main()` | 0 |
| `func main() -> Int` | the value |
| `func main() -> Result<Void, E>` | 0 on `Ok`; on `Err`, the error is printed and the status is 1 |
| `func main() -> Result<Int, E>` | the `Ok` payload; on `Err`, the error is printed and the status is 1 |

Any other return type is a compile error at the declaration:

```saw
func main() -> String { "done" }
// error: `main` must return `Void`, `Int`, `Result<Void, E>` or
//   `Result<Int, E>`, but returns `String`
```

`E` is renderable — `Printable`, which `Error` refines — and the `Err` path
prints it the way `"{e}"` does, so an erased `Result<T, Box<any Error>>` works
through its vtable like anything else. An error type that conforms to neither is
the ordinary not-`Printable` diagnostic, reported at `main`.

```saw
import std.file
import std.path.{Path}
import std.net.{IoError}

func main() -> Result<Void, IoError> {
    var config = try file.File.open(Path(s: "saw.toml"))
    let text = try config.read()
    print("read {text.len()} bytes")
    return
}
// With no saw.toml: prints `error: io error: open failed (not found)`, exits 1.
```

The status is one byte wide by the time a shell sees it: POSIX `wait(2)` carries
eight bits, so a `main` returning 300 is observed as 44. Saw passes the value to
the C entry unchanged and the platform does the narrowing.

`main` may suspend (see [Concurrency](#6-concurrency)) whatever it returns. The
compiler replaces a suspending `main` with an entry executor that drives its
frame — and, if the program also spawns, drives every task alongside it — and
the value comes back out of that executor unchanged.

### Built-in Functions

A handful of functions are compiler-known (no import needed):

- `print(value?)` — write a value plus a newline; no argument prints a bare
  newline. The value may be any `Printable`: the Int family, `Bool`, `String`,
  `Float` and the user types that conform, or a string interpolation.
- `panic(message) -> Never` — abort with `message` (design 49). It
  routes through the freestanding-safe `__saw_rt_panic` runtime seam and **diverges**:
  its type is `Never`, so a function ending in `panic(...)` needs no return
  value, and `guard let x = … else { panic(…) }` is a valid diverging exit. The
  abort message carries the source location — `panic at FILE:LINE: {message}`
  (design 69). A conditionless `while { }` with no `break` diverges on the same
  terms and needs no abort ([Diverging loops](#diverging-loops)).
- `assert(cond: Bool, message)` — a no-op when `cond` is true; when
  false it panics with the same unified location format,
  `panic at FILE:LINE: assertion failed: {message}` (design 69). `debug_assert`
  is deferred until a build-profile split exists.

All three also take a **literal format string with `{}` placeholders** followed
by one value per placeholder — `print("x = {}", x)`,
`panic("out of {}: wanted {}", "frames", 64)`,
`assert(a == b, "want {} got {}", a, b)`. That spelling allocates nothing, and
the placeholder count is checked against the argument count at compile time. See
[Format arguments and the allocation-free path](#format-arguments-and-the-allocation-free-path).

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

// Duplicate arms: an arm that EXACTLY duplicates an earlier one is a compile
// error, reported at the second and naming the first's line, because no input
// can ever reach it. Equality is textual after literal normalization, so
// `case 10` and `case 0x0A` are one pattern, and an irrefutable hole is one
// pattern whether it is written `_` or given a name (`case Move(x, y)` and
// `case Move(a, b)` are the same arm twice). Ranges and guards are exempt:
// overlapping ranges and same-pattern guarded arms are how first-match-wins is
// written, and both stay legal.
match code {
    case 1 -> "one",         // <- line 2 of this snippet
    case 1 -> "one again",   // error: duplicate match arm: `1` is already
    case _ -> "other"        //   matched by the arm at line 2
}

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

// Guard binds for the rest of the scope; the `else` must exit
func process(input: String?) {
    guard let value = input else {
        return
    }
    // value is now unwrapped and available
}
```

#### Diverging loops

A conditionless `while { ... }` whose body contains no `break` **diverges**: no
path leaves it through its exit edge, so control never continues past the loop.
Its type is `Never`, the same bottom type `panic(...)` has (design 177). A
function whose body ends in one therefore satisfies `-> Never`, and satisfies
any other declared return type as well, since `Never` is assignable to
everything.

```saw
// A halt: no `break`, no `return`, no value owed.
func halt() -> Never {
    while { }
}

// Never flows to everything, so this satisfies `-> Int` with no value in sight.
func pick(n: Int) -> Int {
    if n > 0 {
        return n
    }
    while { }
}
```

Everything that follows from divergence follows the way it does for
`panic(...)`. Code written after the loop is unreachable, and is still checked
where it stands. A diverging loop is a valid `guard` exit
(`guard let v = o else { while { } }`). A `match`/`if` branch that is one
contributes no type to the branch join.

Two boundaries decide whether a loop diverges.

**A `break` anywhere in the loop's own body cancels it**, valued or not, and
every break form keeps the typing it already had: `break v` out of an infinite
loop yields `T`, out of a conditional loop `T?`. The break belongs to the
innermost loop enclosing it, so one inside a NESTED loop leaves the outer
conditionless loop diverging. A `return` is not a break — a loop whose only
exits are returns still diverges, because nothing continues past the loop
itself.

**`while true { ... }` is excluded** and keeps today's typing. The conditionless
form is the deliberate "this diverges" spelling; a literal `true` condition
stays an ordinary loop that a later edit may falsify, and the compiler does not
read the condition to decide a type.

```saw
func spin() -> Never {
    while true { }
    // error: function `spin` should return `Never` but body has no value
}
```

#### Optional binding in a loop header (`while let`)

`while let x = <scrutinee> { ... }` runs the body once per `Some` and leaves the
loop on the first `None`. It completes the `if let` / `guard let` family, and
its subject is the drain: a source that yields `T?` until it is empty.

```saw
var pending: Vector<Job> = load_queue()
while let job = pending.pop() {
    run(job)
}
// pending is empty here
```

The scrutinee is re-evaluated **every iteration** — that is what makes this a
drain rather than a test. `continue` is a jump to the loop head, so it
re-evaluates too. A scrutinee that reads a variable nothing in the body changes
therefore loops forever; the compiler does not check for that.

Binding rules are `if let`'s, applied once per iteration:

- The same shadowing rule (see Shadowing). A scrutinee that mentions the
  shadowed name is a derived shadow and is allowed: `while let c = c.next()`.
- The same pattern surface. A tuple pattern over an optional tuple works
  (`while let (key, value) = pairs.pop()`), and over a *suspending* scrutinee it
  is rejected with the same diagnostic `if let` gives, naming the way out.
- The same payload-read tier. A `Copy` payload retains; an `ExplicitCopy` or
  `NoCopy` one needs `move`, `.copy()` or `take()` exactly where `if let` needs
  it.
- `while var x = ...` binds mutably, as `if var` does.

There is no `else` clause. The absent case is the loop exit, so writing one is a
parse error naming `if let ... else` as the one-shot form.

A `while let` produces no value and cannot be used as an expression:

```saw
let r = while let x = src.next() { }
// error: a `while let` loop produces no value and cannot be used as an
// expression
```

A `Result`-yielding source composes through `try?`, which turns `Err` into
termination:

```saw
while let record = try? reader.next_record() {
    try! index.insert(record)
}
```

That absorbs the failure. Use it where "no more input" and "the read broke" want
the same handling; where they do not, `match` the `Result` inside a plain loop
and act on the error.

The scrutinee may suspend, in a driven or a spawned body alike; it is hoisted
per iteration exactly as an `if let` scrutinee is (see the Concurrency section's
G2 note).

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
`Float`, `Bool`, and `String` — are implemented. `Int128`/`UInt128`,
`Float32`, and `Char` are *planned*. `Never` (the bottom type) is the type of a
diverging expression and is spellable as a return type (`func boom() -> Never`;
`@export`'s `_start` shape lowers it to `void` + noreturn, design 58). Two
expressions have it: `panic(...)` (design 49) and a conditionless
`while { ... }` with no `break` (design 177, see
[Diverging loops](#diverging-loops)). An expression of type
`Never` is assignable to any expected type, so a function body that ends in one
needs no return value, and such an arm/branch contributes no type to a
`match`/`if`.

```saw
// Integers
Int8, Int16, Int32, Int64
UInt8, UInt16, UInt32, UInt64
Int128, UInt128    // (planned)
Int    // Platform-native signed — pointer width (i64 on 64-bit, i32 on riscv32)
UInt   // Platform-native unsigned — pointer width

// Floating point
Float       // 64-bit IEEE 754 — the one float type (ruled Aug 20: no
            // `Float64` alias; a width-named family may return if a
            // narrower float ever lands)
Float32     // (planned)

// Other primitives
Bool        // true, false
Char        // (planned) Unicode scalar value — today a scalar is just an Int
String      // Immutable, refcounted byte string (see "String" below)
Never       // Bottom type (a diverging `panic` or `while { }` with no `break`;
            // usable as a return type)
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
- **A float literal needs a digit on each side of the point** (design 161).
  `1.5` and `0.5` are floats; `7.` is not one. A `.` that no digit follows ends
  the number, which is what makes `7.to_string()` a method call on `7` and
  `1..=9` a range. A trailing-dot `7.` is a parse error naming the spelling
  `7.0`. The grammar has no exponent form, so `7e5` is the integer `7` followed
  by the identifier `e5`. Digits immediately after a member-access `.` are a
  tuple index rather than the start of a number, so they take neither a decimal
  point nor a suffix (see Composite Types).
- **A bare (unsuffixed) integer literal adopts a fixed-width EXPECTED type
  wherever one is in force, and is range-checked *at the literal*** (design 87).
  This is uniform across every position a value flows into — `let`/`var` with a
  fixed-width annotation, a function/method parameter, a struct field or `init`
  argument, a default parameter value, a `return` (and if/match arm results that
  merge to a fixed-width type), an enum payload, a compound-assign RHS
  (`x += 1` for `x: Int8`), and the element/key/value positions of array, tuple,
  `Vector`, `Map`, and `Set` literals. An ASSIGNMENT TARGET names an expected
  type the same way an annotation does, at every target kind: a local (`v = 4`),
  a struct field (`w.b = 2`), a tuple element under either spelling (`t.0 = 5`,
  `pair.x = 5`), an array or `Vector` element (`arr[0] = 5`), a `borrows` place
  (`m[k]! = 5`), an `unsafe static var`, and the referent of a `&var` reference
  or of `self`. In each the literal takes the slot's exact
  width, so it stores and overflow-checks at that width, and an out-of-range
  literal (`let b: UInt8 = 256`) is a clean compile error, never a silent wrap or
  an ICE. With NO fixed-width expected type a literal stays platform `Int`
  (`let x = 5`), and `Int`/`Int` arithmetic is unaffected. The one place a
  literal is typed by a sibling rather than a declared slot is a mixed binop
  (`b + 0`, `fd < 200`): the literal adopts the other operand's fixed-width type.
- **A CONSTANT EXPRESSION adopts and is range-checked exactly as a literal is.**
  Anything the constant evaluator folds — `2 + 3`, a shift, a mask, `~m`, a
  negated constant — takes the slot's fixed width at every position above, and
  the check runs on the FOLDED value: `let e: UInt16 = 1 << 20` is the same
  clean "does not fit" error `let e: UInt16 = 1048576` is, and `let a: Int8 =
  -(1 << 7)` is `Int8.min` and compiles. The fold happens in the signed platform
  `Int` domain (see *Constant expressions*), so `1 << 63` is `Int.min` and does
  not fit an unsigned slot — mask it (`~0 & 0xFFFF_FFFF`) or write the literal.
  An expression with a runtime operand in it is not a constant and is unaffected:
  `n * 2` and `word | (1u32 << n)` type as they always did.
- **A CLOSURE body's return positions are those positions too.** The tail
  expression, the if/match arm results inside it, and a `return` in the body all
  take the closure's declared return type, so a `(Int32) sync -> Int32` slot
  takes `{ x in 1 }` and needs no suffix. An array literal in the same position
  shapes to a `Vector` return, exactly as it does in a named body.
- **An OPTIONAL slot's payload counts as the expected type**, since the slot
  wraps the value for you: `let x: Int32? = 1` types the literal `Int32` and
  range-checks it there, at every position above (`f(2)` for a `f(o: Int32?)`,
  a field, a return, an array or `Vector` element, a closure tail). A slot
  naming more than one layer takes the innermost payload, so `let d: Int32?? = 11`
  is an `Int32` too. A branching value keeps the optional, which is what lets an
  arm be a bare `None`: in `if c { 1 } else { None }` at `-> Int32?` the `1`
  adopts `Int32` and the `None` learns what it is a `None` of.
- **A `Result` slot peels to the payload that can take the literal.** A Result
  has two payloads, so the rule names which: the literal adopts the UNIQUE
  payload that could adopt it, and that also picks the variant, since the
  auto-wrap chooses `Ok`/`Err` by the value's type. `return 4` at
  `-> Result<Int32, Bad>` is `Ok(4)` typed `Int32`; `return 7` at
  `-> Result<String, Int32>` is `Err(7)`. Where BOTH payloads could adopt it —
  `Result<Int32, Int8>`, since a bare literal fits either width — the compiler
  refuses and names both, and the explicit `Result<Int32, Int8>.Ok(value: 4)`
  or `.Err(error: 4)` says which; inside the constructor the literal has one
  slot and adopts there. An optional payload composes (`Result<Int32?, Bad>`
  lands at `Int32`), and an abstract generic `Result<T, E>` peels nothing.
- **Use the fixed-width types (`Int8`…`Int64`, `UInt8`…`UInt64`) for anything
  whose layout must be stable across targets** — wire formats, on-disk
  structures, and device/MMIO register maps. Their widths never change, and D1's
  checked arithmetic makes any narrow-width overflow a loud panic rather than a
  silent wrap. `Int64` is the escape hatch for a value wider than a 32-bit word.

### Never

`Never` is the bottom type: the type of an expression that does not produce a
value because control never continues past it. Three expressions have it, and a
call to a function declared `-> Never` is one of them:

```saw
func fault(code: Int) -> Never {          // declared: this call does not return
    print("fault {code}")
    while { }
}

panic("out of range")                     // the builtin
while { }                                 // a break-less loop (Diverging loops)
fault(7)                                  // a call to any `-> Never` function
```

**An expression of type `Never` satisfies any expected type.** There is no value
to convert, so there is nothing to reconcile: the expression leaves, and
whatever the surrounding code expected is never asked for. That one rule covers
every position an expression can appear in.

```saw
func lookup(table: &Registry, id: Int) -> Entry {
    guard let e = table.find(id) else { fault(1) }   // a `guard` exit
    if e.stale { fault(2) }                          // a statement
    return e
}

func status(e: &Entry) -> Reply {
    match e.kind {
        case Missing -> { fault(3) },                // an arm: the `match` takes
        case Ready -> { Reply(code: 0) }             // the other arm's type
    }
}

func port(cfg: &Config) -> Int {
    cfg.port ?? fault(4)                             // a `??` default
}

func finish(e: &Entry) -> Int {
    if e.ready { return e.code }
    return fault(5)                                  // a `return` operand
}

func record(e: &Entry) -> Int {
    if e.ready { return 0 }
    store(fault(6))                                  // an argument: `store` is
}                                                    // never called
```

The positions are: a `guard ... else` exit, a bare statement, an arm of a value
`if` or `match` (in any arm position, at any result type), the tail expression
of a function (whatever its declared return type), the operand of `return`, the
default operand of `??`, and an argument of another call. A diverging tail also
satisfies `-> Never` itself, so a `Never` function may end in a call to another
one with nothing written after it.

The rule does not depend on how the callee is written or reached. A plain
function, one of an overload set, a module-private function called inside its
own module, an imported public one, an `extern "C"` declaration, an extension
method, a static method, a generic function or method, a closure, and a trait
requirement reached through an `any Trait` existential all diverge on the same
terms, in the hosted and freestanding profiles alike.

**A task body may not be `Never`.** A task is a computation something later
waits for, so `group.spawn(halt())`, `Thread.spawn { while { } }` and
`__saw_drive(halt())` are refused at the call:

```
error: a task body may not be `Never`: `halt` never returns, so the task never
completes and `join` on its handle could never return
hint: a task is something to wait for, and a `Never` body gives it a result
that cannot exist. Write a forever-task as `-> Void` with a loop —
`func serve() { while { ... } }` — and end it by cancelling the task or
breaking the loop
```

A `-> Never` function is otherwise unrestricted, including a suspending one
called directly.

`Never` is spellable wherever a return type is written, and only there: it is
not a type values are stored at. A `-> Never` declaration lowers to a `void`
symbol carrying LLVM's `noreturn`, which is the C `_start`/`abort` shape and
what makes `@export`ing one usable as a bare-metal entry point (see
[Interoperability](#10-interoperability)).

### String

`String` is an **immutable, reference-counted byte string**. A `String` value is
a single pointer; copying one (binding it, passing it, storing it) is a cheap
refcount bump, and the buffer is freed deterministically when the last owner
goes away. Because it is `Copy + Deinit`, strings flow through the
language with no `move` discipline — `greet(s)` does not consume `s`.

- **Representation.** One heap block `{ refcount, len, bytes…, NUL }`; the value
  points at `bytes`, with the header at negative offsets. The buffer stays
  NUL-terminated for zero-copy C FFI, and `len` is authoritative (O(1),
  interior NUL bytes are representable). The buffer is immutable after
  construction: interpolation builds a fresh buffer each time (a `"{s}{t}"`
  accumulation loop is O(n²); the mutable, geometrically-growing `StringBuilder`
  (design 38) is the efficient builder — `append`/`build`). There is no `+`
  operator on `String` — concatenate via interpolation or `StringBuilder`.
- **Escape sequences.** The supported escapes in a string literal are exactly
  `\\`, `\"`, `\n` (LF, 10), `\t` (tab, 9), `\r` (CR, 13), `\0` (NUL, 0),
  `\u{...}`, plus the `\{` / `\}` brace forms (a literal brace, distinct from
  interpolation). `\0` produces an interior NUL that `len()` counts (`len` is
  authoritative — the trailing NUL never defines the length). Any OTHER backslash sequence is a
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
  `Data.to_string() -> Result<String, Utf8Error>` is the same door under a
  different name — it delegates to `fromBytes` (design 122), so decoding a byte
  buffer read off a socket or a file surfaces the failure instead of minting a
  String that breaks the invariant. `Utf8Error` conforms to `Error`, so it
  interpolates and boxes at an erased `Result<T, Box<any Error>>` boundary.
- **Access views, never `s[i]`.** There is deliberately no integer indexing (it
  conflates bytes with scalars). Two iterator views are provided instead:
  `bytes()` yields the raw bytes and `chars()`
  yields Unicode scalar values decoded from UTF-8. Bytes are `Int8` — from
  `byte_at(i)` and from `bytes()` alike — so a byte at or above 0x80 reads
  NEGATIVE, and a comparison against a `u8`-suffixed literal is a type error
  (`Data`'s bytes are `UInt8`; `String`'s are not). Scalars are yielded as `Int` —
  there is no `Char` primitive type yet (a scalar is just an `Int`). `String`
  itself *is* `Comparable` (byte-lexicographic ordering, design 48). Each iterator
  holds its OWN retain on the source string, so iterating a temporary
  (`for c in makeString().chars()`) is safe.
- **Encoding a scalar** (`designs/119`). `StringBuilder.append_scalar(scalar:
  Int) -> Result<Int?, AllocError>` is the inverse of `chars()`: it UTF-8-encodes
  one Unicode scalar and appends it, answering the byte count (1..4). An invalid
  scalar — negative, a UTF-16 surrogate (`0xD800..0xDFFF`), or greater than
  `0x10FFFF` — is `Ok(None)` and appends nothing (never a silent drop). The two
  answers ride separate channels on purpose: `Ok(None)` says "not a scalar
  value" and `Err(AllocError)` says the builder could not grow, so neither can be
  mistaken for the other. Because `chars()` yields only valid scalars, an
  encode/decode round-trip is the identity on that domain.
- **FFI: `withCString`.** `s.withCString { ptr in ... }` hands a closure an
  `UnsafePointer<Int8>` to the string's NUL-terminated bytes, valid for the
  duration of the call. The payload is already NUL-terminated, so the pointer is
  passed directly with no copy. The closure is a **non-escaping** parameter (the
  default, per the closures design): the compiler forbids it from being stored or
  outliving the call, which is the whole safety story — the borrowed pointer
  cannot leak. The closure returns `Void`; a result is produced by
  borrow-capturing an enclosing variable
  (`s.withCString { [&var n] ptr in n = strlen(ptr) }`).
- **Splitting**: `split(separator: String) -> Result<Vector<String>, AllocError>`
  divides on every occurrence of `separator` (content comparison, same as literal
  patterns); adjacent separators yield empty pieces, and a string with no
  separator is a one-element vector. It builds that vector, so it reports a
  refusal like every other allocating operation ([Allocation
  failure](#allocation-failure)).
- **Number parsing** (`designs/57`, `designs/119`). Optional-returning methods
  parse the **whole** string (no trimming — the caller trims with `trim`;
  empty → `None`; any trailing/leading junk → `None`). Parse failure is *data*,
  so these never panic: `to_int() -> Int?` (base 10),
  `to_int(radix: Int) -> Int?` (a design-55 overload, radix 2..=36, digits
  `0-9a-zA-Z`, no `0x` prefix — the caller strips it), and `to_float() -> Float?`
  (`[+-]?digits[.digits][e[+-]digits]`). Overflow returns `None`: the integer
  parser accumulates a **non-positive magnitude** with wrapping arithmetic and
  divide-back checks (portable across Int widths, no `Int.max` constant needed;
  `Int.min` round-trips). `to_float` is naive accumulation — fine for typical
  input, but **not** a correctly-rounded `strtod` (the last ULP may differ).
  `to_uint() -> UInt?` and `to_uint(radix: Int) -> UInt?` are the unsigned
  companions (design 119). They accept an optional leading `+`, reject a leading
  `-`, and reach the full `0..UInt.max` range — the `2^63..2^64-1` magnitudes
  a signed `to_int` returns `None` for. Overflow past `UInt.max` is `None`,
  detected with the same wrapping-arithmetic carry and divide-back checks. The
  fixed-width and platform integer bounds used to range-check a parsed value are
  the built-in `Int.max`/`Int.min`, `UInt.max`/`UInt.min`, and the per-type
  `Int8.max` … `UInt64.max` constants (design 53).
- **The refcount is atomic** (platform-word `isize`), from day one. This is a deliberate cost
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

### Data

`Data` is a **copy-on-write byte buffer**: a window (an offset and a length)
onto storage an `Arc` owns. Copying a `Data` retains that storage rather than
duplicating it, and the bytes separate at the first write that finds them
shared. It is `Copy`, so byte buffers flow through the language with no
`move` discipline, and a copy costs a refcount bump. It lives in `std.data` and
needs an import.

```saw
import std.data.*

var a = try! Data(capacity: 4)
try! a.push(1)
var b = a              // a retain: no bytes copied
try! b.push(2)         // b is shared here, so it separates first
print("{a.len()} {b.len()}")     // prints: 1 2
```

This completes the standard library's three byte-container positions: `String`
is shared and immutable, `Vector` is uniquely owned and mutable, `Data` is
shared until written.

- **The uniqueness gate.** Every mutation — `push`, `append`, `append_bytes`,
  `set`, a write through `d[i]`, and the reservations behind them —
  takes the same test: sole owner, write in place; shared, copy the live bytes
  into a fresh buffer and write there. The mechanism is
  `Arc.with_unique(body:)`, which runs its body on a `&var` borrow of the
  payload when the handle is the only strong owner and answers `None` when it
  is not. Because there is no second path, no operation on a `Data` can be
  observed by another `Data`.
- **Slicing is O(1) at any size.** `slice(start, end) -> Data?` retains the same
  storage and narrows the window; `None` means the bounds were invalid. The
  slice is an independent value, so writing either it or its source separates
  the bytes first.
- **`copy()` is lazy; `detached()` is eager.** `copy()` is the `Copy`
  retain and cannot fail. `detached()` materializes the bytes into a buffer
  sized to `len()`, which is what to reach for when a small slice would
  otherwise keep a large buffer alive; it reports a refused allocation as
  `Err(AllocError)`.
- **`capacity()` reports what fits before the next allocation.** For a sole
  owner of a whole buffer that is the buffer's capacity. For shared storage, or
  a slice that starts partway in, the next write separates the bytes, so the
  answer is `len()`.
- **Reads never separate.** `d[i]`, `get(i) -> UInt8?`, `len()`, `is_empty()`,
  `pop()`, `clear()` and `byte_ptr()` leave the storage shared. `pop` and
  `clear` only narrow this window, so a sibling keeps every byte it could see.
- **`d[i]` is a place, and reading one costs nothing.** The accessor is `&self`,
  so a read works on a `let` binding, a `&Data` parameter, or a slice several
  `Data`s share. A write opens an exclusive window, so it needs a `var` root and
  the first one on shared bytes copies them. Both come out of one declaration:
  the uniqueness gate is written under `#lend_var` (see
  [Places](#places-borrows-and-lend)), which puts it in the exclusive
  specialization only. `get(i)` is the `None`-returning twin of a panicking
  `[]`, not a different kind of read.
- **Iterating holds a retain.** `iter()` returns a `DataIterator` that owns a
  `Data`, so an iterator outliving the binding it came from still reads live
  bytes.

Out of range, `set`/`d[i]` panic and `get`/`slice` answer
`None` — design 130's accessor rule, the same split `Vector` uses. A refused
ALLOCATION is a different question and rides a different channel: `set` reports
it, `d[i]` panics (see [Allocation failure](#allocation-failure)).

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
`#` introduces these three and `#lend_var` (see
[Places](#places-borrows-and-lend)) and nothing else; any other `#name` is a
clean "unknown directive" lex error.

### Doc comments

**Status: implemented** (design 121). Two comment forms carry documentation.
Everything else about comments is unchanged: `//` runs to end of line and means
nothing to the compiler.

- **`///` documents the declaration that follows it.** A run of `///` lines with
  nothing between them is one doc comment; it attaches to the next
  `func`/`struct`/`enum`/`trait`/`extension`/`type`/`static`, to a struct field,
  an enum case, an extension method or `init`, or a trait method. A `public`
  modifier or an attribute line between the comment and the declaration makes no
  difference.
- **`//!` documents the file it appears in.** It is legal only ahead of every
  declaration, so it belongs at the top.
- A doc comment must start its line. `//// four slashes` is an ordinary comment
  (banner lines keep working), and so is a `///` written after code on the same
  line.

One space after the marker is dropped; the rest of the line is kept verbatim.
The compiler treats the text as opaque — Markdown is the convention, not a rule.

```saw
//! Spans of time.

/// A span of time, held as whole nanoseconds.
struct Span {
    /// Nanoseconds in the span.
    public nanos: UInt64
}
```

A doc comment that documents nothing is an error rather than a silent drop:

```saw
/// Displaced from `main` by the block below.

/// Prints zero.
func main() { print(0) }
// error: Parse error at 1:1: doc comment is not followed by a documentable
// declaration
```

`sawc <entry.saw> --emit-docs` type-checks the program and writes a JSON
description of it instead of code (to `-o`, else stdout). It covers the entry
file's module and every module the program imports, `std` included, so a file
that imports what you want documented is the whole driver. Each item carries its
rendered signature, visibility, generic parameters and bounds, parameters and
return type, trait conformances, doc text, and source line — plus the two things
a signature does not show: whether the function **suspends**, and whether a
method **borrows, mutably borrows, or consumes** `self`. A callable also carries
a `static` flag, read off the declared keyword. Private fields,
methods, and inits are left out; `--emit-docs-all` keeps them. Ordering is
fixed, so the output is diffable.

### Composite Types

```saw
// Tuples (positional — implemented). Access fields by index with `.N`.
let point: (Int, Int) = (10, 20)
let x = point.0

// A tuple index is a bare integer and never consumes a following `.` (design
// 161), so a projection continues past one.
let pairs: ((x: Int, y: Int), Int) = ((x: 1, y: 2), 3)
let px = pairs.0.x                  // 1 — a named field of element 0
let nested = ((1, 2), 3)
let second = nested.0.1             // 2 — two index hops, not the float 0.1

// A tuple index is a PLACE, not a copy — the same storage a struct field names
// (DF-151j). Reach the element through it:
func grow(v: &var Vector<Int>) { try! v.push(7) }

var t = (Vector<Int>(), 0)
try! t.0.push(1)                    // grows the tuple's own vector
t.1 += 1                            // compound assignment on the element
t.0 = Vector<Int>()                 // whole-element write; the old element
                                    // deinits exactly once
grow(&var t.0)                      // lends the element slot
var pair = (x: Vector<Int>(), y: 0)
try! pair.x.push(2)                 // the named spelling reaches the same slot

// Mutability is the root's: `let t = (v, 7)` rejects every line above, the way
// `let h` rejects `h.v.push(x)`.
//
//   error: cannot call `&var self` method `push` on immutable variable `t`
//   error: cannot assign to element of immutable variable `t`
//
// The Law of Exclusivity judges elements by PATH, as it judges struct fields:
// `f(&var t.0, &t.1)` names two disjoint elements and compiles, while
// `f(&var t.0, &t.0)` is an exclusive access violation. (Root-charging applies
// to accessor-mediated places like `v[i]`, where a dynamic index cannot be told
// apart; a tuple index is static.)
//
// A value READ out of an element follows the copy tier, like any other place:
// `let e = t.0` is bitwise for a trivial element, a retain for Copy, and
// a clean error for ExplicitCopy/NoCopy naming `move`/`.copy()`.

// An ANNOTATED tuple literal is checked against the declared element types, so
// an optional element takes the ordinary one-level auto-wrap and a fixed-width
// element adopts its width (DF-151l):
let opt: (Int?, Int) = (1, 0)       // element 0 wraps to `Some(1)`
let cleared: (Int?, Int) = (None, 0)
let narrow: (Int8, Int) = (5, 1)    // `5` adopts Int8, range-checked here
// With no annotation each element still contributes its own type.

// Tuple destructuring (design 63 — implemented). Irrefutable only: bindings,
// per-position `_` discard, and nested tuples. The whole source is consumed
// (owning components move out; a bare Copy/POD source is copied).
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

// The REPEAT literal `[v; N]` is N copies of one value. `N` is a compile-time
// constant: a literal, constant arithmetic, a const generic parameter (see
// Generics), or a module `static` that is one (see Module-level statics). The
// value expression is evaluated exactly once.
var scratch: [Int8; 256] = [0; 256]      // a zeroed stack buffer
let flags = [true; 4]                    // type `[Bool; 4]`
let sized = [0; 2 * 128]                 // type `[Int; 256]`

// The same constants size the TYPE, so one `static` can be the only place a
// region's size is written:
static REGION_SIZE: Int = 65536
var region: [UInt8; REGION_SIZE] = [0; REGION_SIZE]
var half: [UInt8; REGION_SIZE / 2] = [0; REGION_SIZE / 2]

// A length that folds to a negative number is a compile error:
//
//   struct Bad { bytes: [UInt8; 2 - 3] }
//   // error: array length is negative (`-1`)

// An all-zero repeat lowers to a single zeroinitializer store; other values
// lower to a splat loop. Elements must copy for free — trivially copyable or
// Copy — because a repeat makes N copies and there is nowhere to write
// the `.copy()` an ExplicitCopy value needs:
//
//   let rows = [v; 3]   // v: Vector<Int>
//   // error: a repeat literal needs a freely copyable element, and
//   //        `Vector<Int, GlobalAllocator>` is ExplicitCopy
//
// A repeat literal is a const initializer, so a static holds one:
static SCRATCH: [Int8; 4096] = [0; 4096]     // zeroinitializer, in .bss

// The length is part of the type. `[Int; 3]` is not a `[Int; 5]`, and passing
// one where the other is expected is a compile error naming both.

// A fixed array `[T; N]` inherits T's copy tier (see The Copy Trait Family):
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
(moves for owning types). A consequence, made explicit by design 122: **there is
no bare block statement.** A closure literal alone in statement position would
build a closure and discard it, so none of its body would run — that is a
compile error naming the two real spellings (call it, `{ ... }()`, or bind it).
To narrow a value's lifetime, extract a function.

**Binding a `Void` expression** (design 122, refined by design 132). Writing
`let n = nothing()` names a value that does not exist, and it is a compile error
at the binding: call it as a statement, or write `let _ = ...` if the point is
to evaluate and discard. The line is **syntactic**. A `Void` you can see in the
source is a visible mistake and is rejected; a `Void` that arrives by
INSTANTIATION is not. A local typed by a function's own type parameter compiles
at every instantiation, `Void` included, where it becomes a zero-sized binding —
no storage, and reading the name yields no value:

```saw
func around<R>(&self, body: (Int) sync -> R) -> R {
    let result = body(self.n)   // fine at every R, `Void` among them
    self.release()
    result
}
```

Generic code stays instantiation-uniform: a body that type-checks generically
compiles for every instantiation, `Void` included, so no call site can produce
an error the definition did not.

### Structs

```saw
// Value type (copied by default)
struct Point {
    x: Float,
    y: Float,
}

// Methods via extensions
extension Point {
    // Custom initializer (beyond default field init)
    init(magnitude: Float) -> Point {
        Point(x: magnitude, y: magnitude)
    }

    // Instance method (shared reference to self)
    func magnitude(&self) -> Float {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method (exclusive reference to self)
    func translate(&var self, dx: Float, dy: Float) {
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
// name (not `Message.Quit`), comma-separated, exhaustive. Two arms for one
// variant are a duplicate-arm error (see Control Flow), including when they
// name their payload bindings differently.
match msg1 {
    case Quit -> quit(),
    case Move(x, y) -> move_to(x, y),
    case Write(text) -> print(text),
    case Color(r, g, b) -> set_color(r, g, b)
}
```

#### Match consumes an owned enum

A `match` on an owned NoCopy or ExplicitCopy enum with owning payload
consumes the scrutinee: each arm binding owns its payload field, and the
binding that held the enum is moved-from afterward. A later use, including a
second `match`, is a use-after-move error, the same error a second `move s`
gives. Matching through a `&`/`&var` parameter or a place borrows instead and
consumes nothing; to keep an ExplicitCopy value past the match, write
`match s.copy()`. Enums whose payloads are trivial or Copy are not
consumed.

```saw
enum Slot {
    case Filled(r: Res),    // Res is NoCopy
    case Empty
}
extension Slot: NoCopy {}

let s = Slot.Filled(r: Res(id: 7))
match s {
    case Filled(r) -> use(move r),  // `r` owns the payload
    case Empty -> {}
}
match s { ... }   // error: use of moved variable `s`
```

A Copy-tier enum is matched as a borrow instead. Each binding takes a
retain of the payload and releases it when the arm ends; the scrutinee keeps
its own reference and drops at the end of its own scope. Matching one twice is
allowed, and reading `strong_count()` inside an arm shows both owners.

```saw
enum Holder {
    case Full(a: Arc<Res>),
    case Nothing
}
@synthesize extension Holder: Copy {}

let h = Holder.Full(a: try! Arc<Res>(value: Res(id: 9)))
match h { case Full(a) -> first(a), case Nothing -> {} }
match h { case Full(a) -> second(a), case Nothing -> {} }
// the payload is released once, when `h`'s scope ends
```

#### Methods on enums

An enum carries methods on the same terms as a struct: write an `extension`.
`match self` is the idiomatic body, and `&var self` replaces the whole value.

```saw
enum SysError {
    case Ok,
    case BadHandle,
    case Other
}

extension SysError {
    func describe(&self) -> String {
        match self {
            case Ok -> "ok",
            case BadHandle -> "bad handle",
            case Other -> "other"
        }
    }

    func degrade(&var self) {
        self = SysError.Other      // whole-value replacement
    }

    static func best() -> SysError {   // static: declared, and no receiver
        SysError.Ok
    }
}
```

Trait conformances take hand-written bodies, so an enum is a normal choice for
an error type:

```saw
extension SysError: Printable {
    func format(&self, into: &var StringBuilder) {
        try! into.append("SysError(")
        try! into.append(self.describe())
        try! into.append(")")
    }
}

extension SysError: Error {}

func might_fail(bad: Bool) -> Result<Int, SysError> {
    if bad {
        return SysError.BadHandle
    }
    return 5
}
```

The rules that govern struct extensions govern these unchanged: import-scoped
method lookup, the orphan rule for conformances, `@synthesize` for a derived
`equals`/`compare`/`hash`/`copy`, a hand-written `deinit` inside the copy
policy, and the required `static` keyword on a method with no receiver.
Methods on a generic enum monomorphize per instantiation.

One difference: an enum extension may not declare an `init`. The cases are the
constructors.

```saw
extension Color {
    init(bright: Bool) -> Color { Color.Red }
}
// error: enum `Color` cannot declare an `init`: an enum's cases are its
//        constructors
```

Compute which case to build in a static method returning the enum.

#### Raw-backed enums

A payload-free enum may declare an integer backing type in the declaration's
colon position. The backing pins the representation — width and tag values — so
the enum can cross an ABI boundary.

```saw
enum SysError: UInt8 {
    case Ok = 0,
    case BadHandle = 3,
    case NoMemory = 12
}

let e = SysError.NoMemory
print(e as UInt8)             // prints: 12
print(sizeof<SysError>())     // prints: 1
```

Any fixed-width integer (`Int8`..`UInt64`) or platform `Int`/`UInt` works.
Fixed-width is the wire-safe choice.

Three rules:

1. **Payload-free only.** A case carrying a payload has no integer identity, and
   declaring a backing on such an enum is an error.
2. **Every case states its value, and no two share one.** Nothing
   auto-increments. Declaring a backing says the numbers are ABI, so reordering
   the cases cannot silently renumber them. An enum without a backing keeps
   compiler-assigned ordinals and is not castable.

   The value is a **constant expression**, not only a literal, so a flag says
   which bit it means. Literals (`0x100`, `0b1010`), and arithmetic, bitwise
   and shift operators over them, all fold; the result is range-checked against
   the backing exactly as a literal is. A folded `1 << 8` states its value as
   exactly as `256` does, so rule 2 is unaffected. The expression may not name
   a `static` or another enum's case — an enum's cases are fixed by its own
   declaration, before either is known — and that is a clean error.

```saw
enum Right: UInt32 {
    case Transfer = 1 << 0,
    case Debug    = 1 << 8,
}
```
3. **`as` goes one way.** The enum is its tag, so `e as UInt8` is total. The
   inverse is partial and is spelled `from(raw:)`:

```saw
if let e = SysError.from(raw: byte) {
    print("decoded {e}")
} else {
    print("unrecognized status byte")
}
```

`from(raw:)` is synthesized, returns `E?`, and yields `None` for a value no case
declares. It is a lookup, not an `init` — an unrecognized byte off a wire is
data the caller decides about, not a trap.

A backing survives GENERICS. `enum Code<T>: UInt8` carries its declared values
into every instantiation, so `Code<Int>.Warn as UInt8` and
`Code<String>.Warn as UInt8` are the same declared byte — the tags belong to the
enum, not to the instantiation, and only a payload type could differ between
them.

A case of a backed enum is a compile-time constant, so it may be a
`static_assert` operand, an array length, or an operand of the bit operators in
a constant. A combination of cases is the **backing integer**, not the enum; see
"Flag enums".

Because the representation is pinned, a backed enum is a legal field type in a
struct read through `UnsafeMemory`, so a typed wire view can name a flags byte
by its type:

```saw
enum SegFlags: UInt8 {
    case Empty = 0,
    case Exec = 1,
    case Write = 2
}

struct SegHeader {
    kind: UInt32,
    flags: SegFlags,
    pad0: UInt8,
    pad1: UInt16,
    mem_len: UInt32
}

static_assert(sizeof<SegHeader>() == 12, "SegHeader must stay 12 bytes")
```

`Equatable`/`Hashable` auto-conformance is unchanged, and so is match
exhaustiveness. A raw-ordered `Comparable` derivation is not available.

### Optionals

```saw
// Optional type (no null!) - T? syntax like Swift. A plain value of type T is
// implicitly wrapped into T?; the empty case is the keyword `None` (there is no
// `some(...)`/`none` constructor).
let maybe: Int? = 42
let nothing: Int? = None

// `Optional<T>` is the same type under a written name (the spelling `Result`
// always had).
let same: Optional<Int> = maybe

// `?` NESTS. The containers genuinely produce two-layer values —
// `Vector<Int?>.get(i)` is one — and both spellings name that type.
let two: Int?? = v.get(0)
let also: Optional<Int?> = two          // the same type, written the other way
func describe(o: Int??) -> String { ... }
let three: String??? = None             // by induction

// Optional chaining — `?.field` / `?.method()` on ANY Optional-typed expression,
// arbitrary length. Each optional hop carries its own `?`; the first None
// short-circuits the WHOLE tail. The result is `U?`, flattened (never `U??`).
let len: Int? = user?.profile?.bio?.len()   // multi-hop, method final
let id: Int? = makeUser()?.id               // call-result head
user?.name = "Ada"                          // chained assignment (writes in place)
user?.visits += 1                           // and its compound spelling

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

**Nested optionals have two spellings, and they are one type.** The postfix `?`
nests (`Int??`, `String???`) in every position a type is written — annotations,
parameters, returns, generic arguments, struct fields, behind a `&` — and
`Optional<Int?>` names the same type. Neither is privileged; the containers are
what produce two-layer values in the first place, since `Vector<Int?>.get(i)`
answers "no such element" and "the element, which is itself absent" on separate
layers.

`??` is also the nil-coalescing *operator*, and one token serves both readings:
the type grammar counts a `??` as two optional layers, and expression position
keeps it as the operator. The two never collide, because a type is otherwise
followed by `=`, `,`, `)`, `>`, `{` or a newline — with one exception. The
target of an `as` cast *is* followed by an expression continuation, so there the
operator wins and `x as Int? ?? y` is a cast to `Int?` and then a coalesce.
Types nested inside a cast target (`x as Vector<Int??>`) are unaffected.

**`??` peels exactly one layer, and its default owes what is left.** On a
`Vector<Int?>`, `v.get(9)` is an `Int??` and `v.get(9) ?? v.get(0)` is a type
error: the default is another `Int??` where an `Int?` is owed. The error names
both types. A bare `None` on the right adopts the payload type, so
`v.get(9) ?? None` is the usual spelling; otherwise peel the default yourself.
The rule refuses only a default DEEPER than the payload — everything the
ordinary one-layer coalesce does is untouched.

**Optional chaining** (`designs/111`) is **implemented** in full (Swift-style).
`e?.field` and `e?.method(args)` are legal where `e: T?`: `None` short-circuits,
`Some(v)` projects the field / calls the method on the payload. Chains are
arbitrary postfix sequences — each OPTIONAL hop carries its own `?`, a
non-optional intermediate uses plain `.`, and the head may be any Optional-typed
expression including a **call result** (`x.a()?.b?.c()`). The chain's type is
`U?` where `U` is the final segment's non-optional type; an already-optional final
segment stays `U?` (**never `U??`** — flattening). Intermediate payloads are
borrowed IN PLACE (no copy, no consume — chaining an owned Optional does not
consume it); a final FIELD projection copies its value (so the field must be
copyable — a move-only NoCopy/ExplicitCopy field is rejected; end the chain in a
method instead), while a final METHOD result is a fresh value, unrestricted. The
result composes as an ordinary Optional (`??`, `if let`, `guard let`, `!`, match
all apply). `?.` on a non-Optional expression is a clean error.

Once a `?` short-circuits, **ALL later evaluation is skipped, including the
argument expressions of a skipped method call** — a deliberate, observable
carve-out of the left-to-right rule under "Argument Evaluation Order" below.

**Chained assignment** `x?.y = v` (and longer chains, `x?.a.b?.c = v`) writes the
RHS through the chain into the payload FIELD **in place** iff every optional hop
is non-None; the RHS is skipped entirely on short-circuit (same eval-order
carve-out). The head must be a mutable place (a `var` or a `&var`-reachable path),
and exclusivity applies to the written root. The RHS follows ordinary assignment
transfer rules against the field type (implicit copy where the tier allows,
`move`/`.copy()` for ExplicitCopy/NoCopy); the old field value deinits exactly
once on the written path, and nothing drops on the skipped path. The assignment
EXPRESSION has type **`Void?`** (`None` = skipped, wrapped unit = written): in
statement position it is discarded silently (the common case); "did it happen" is
consumed via optional binding, **not** a `!= nil` comparison —
`guard let _ = x?.y = v else { … }` (design 111 blesses `_` as the `if let` /
`guard let` bound pattern: evaluate and test the Optional, bind nothing, drop the
payload immediately).

The **compound spelling** `x?.y += v` writes the same storage: on the non-None
path the field is read, the operator applied and the result written back, and on
a None head neither the write nor the RHS runs. Every compound operator is
available (`+= -= *= /= %= &= |= ^= <<= >>=`), the operand rules are the compound
statement's (both integer operands agree in width and signedness; a bare literal
adopts the field's type), and the result is the same `Void?`. A SUSPENDING RHS
works in either spelling (design 224): `x?.y += stream.read()` runs the read only
on the non-None path, exactly as `x?.y = stream.read()` does. Builds before
design 224 refused both the chained compound form and the plain `n += slow()`
it lowers through.

The head may be a **place** — a conditional lend, in either spelling:

```saw
m["x"]?.value = 42        // subscript head
v.get(0)?.value = 8       // named-accessor head
```

The head lends, and an absent head opens no window, writes nothing and evaluates
no RHS — the ordinary `?.` short-circuit. The `?` is the LEND's optionality, so
inside the window the payload is simply there; the head is never read out as a
value first, which is what would make the write land in a copy. One fence: a
second `?` hop past the lend (`m[k]?.a?.b = v`) is not supported — bind the lend
first.

A **suspending hop** is supported (`designs/120`), on the read and the write
side. The chain lowers to its branch shape before the suspension is embedded, so
`o?.read()` runs the hop only when every earlier hop is non-None, and a
short-circuit still skips it (and its side effects) entirely. A multi-hop chain
peels one hop at a time; `o?.a?.read()` evaluates `o?.a` into a temporary and
then takes the last hop over it. A chained assignment whose RHS suspends
(`x?.y = stream.read()`) lowers to a None-guarded read-modify-writeback, so the
RHS runs only on the written path. `?.` indexing (`a?[i]`) is still out of scope.

#### Payload reads: the place rule

Every payload-extraction form — `o!`, the left operand of `??`, and an
`if let` / `guard let` / match payload binding — denotes a **place**, the same
way `s.field` does (see [Places](#places-borrows-and-lend) for the general rule
and for the `borrows` methods that hand one out). It names storage the optional
still owns, so the read is governed by the payload's entry in
[the Copy trait family](#the-copy-trait-family) table, with no exemption for any
extraction form:

| Use of the place | trivial | Copy | ExplicitCopy | NoCopy |
|---|---|---|---|---|
| Borrow in place (`o!.m()`, `&o!`, `o!.field`, a `?.` hop) | ok | ok | ok | ok |
| Value read (`let a = o!`, by-value argument, return, operand) | bitwise | retain | error | error |
| `o!.copy()` | — | ok | ok (deep) | rejected |
| `move o!` | ok | ok | ok | ok |
| `o.take()` | ok | ok | ok | ok |

A borrow reads the payload where it sits and costs nothing. A value read makes a
second owner, so a `Copy` payload is retained at the extraction and the
optional keeps its own reference:

```saw
var name: String? = "Ada"
let owned = name!        // retains; `name` still owns its payload
name = None              // releases the optional's reference
print(owned)             // prints: Ada
```

An `ExplicitCopy` or `NoCopy` payload is never duplicated implicitly, so a value
read is refused and the error names the three consuming spellings:

```saw
// `File.open` returns `Result<File, IoError>`; `try?` discards the cause to
// give the `File?` this example is about.
var file: File? = try? File.open(Path(s: "/var/log/app.log"))
let f = file!
// error: cannot read the payload out of `file` in let binding:
//        `File` implements NoCopy
// hint: use `move file!` to transfer the whole binding, or `file.take()`
//       to move the payload out in place
```

**`move o!`** is the compile-time transfer. It retires the whole binding — there
is no husk state, no partial move, and no runtime writeback, so it means exactly
what `move o` means, spelled at the projection. It still unwraps, so it panics if
the optional is dynamically `None`, and it costs nothing at run time. Because it
retires a *binding*, it is legal only on a local; `move h.field!` is the ordinary
no-partial-moves error.

**`Optional.take(&var self) -> T?`** is the runtime transfer. It writes `None`
into the place and returns what was there, owned. That reaches places `move`
cannot — above all a struct field, which is the move-out that no-partial-moves
otherwise forbids. It needs a mutable place and is exclusivity-checked like any
other `&var self` method. The checked spelling is `o.take()!`:

```saw
struct Logger { sink: File? }
extension Logger: NoCopy {}

func close_sink(l: &var Logger) {
    if let f = l.sink.take() {   // `l.sink` is None afterwards
        drop_file(move f)
    }
}
```

An `if let` binding follows the value-read row; `if let a = move o` is its
consuming form and retires `o`. `a ?? b` yields an owned value, so both arms hand
over their own reference. Whole-optional operations are unaffected: `let y = x`
on a `T?` already retained through the owning-enum rule, and `move x` already
retired the binding.

**`Optional.is_some(&self) -> Bool`** and **`Optional.is_none(&self) -> Bool`**
read the occupancy tag and nothing else. No reference is created and none is
taken, so the copy tier never enters into it: the two work on a move-only
payload exactly as they work on an `Int`, and neither a `.copy()` nor a `move`
is owed anywhere. They take no arguments and need no mutable place, so a call
result is as good a receiver as a local.

```saw
struct Logger { sink: File? }
extension Logger: NoCopy {}

func is_open(l: &Logger) -> Bool {
    l.sink.is_some()          // `File` is NoCopy; the tag is not the payload
}
```

A receiver that is a freshly produced value still owns its payload after the
tag is read, and deinits at the end of the statement.

**Call-site optional auto-wrap** (`designs/57`, DF3). The implicit `T → T?` wrap
also applies at **call boundaries**: a bare `T` argument auto-wraps into a `T?`
parameter at every call form (free function, method, static method,
module-qualified, struct `init`, and enum-payload construction). It is **one
level only** (`T → T?`, never `T → T??` — and an already-optional argument is
passed through, never re-wrapped). It runs **after overload resolution**, so an
exact match still beats the wrap (design 55 rule 1: `f(5)` picks `f(Int)` over a
coexisting `f(Int?)`). It fires at a generic parameter INSTANTIATED to an
optional too, so `m.insert("y", 7)` on a `Map<String, Int?>` wraps exactly as a
written `Int?` parameter does. Move/copy semantics are unchanged (the wrap
consumes the argument exactly as an explicit `Some(x)` would).

**Call-site `Result` auto-wrap.** The same rule at the other payload kind, in
the same positions: a bare `T` becomes `Ok`, a bare `E` becomes `Err`, and a
`T` that is also the `E` is the ambiguity error described under *Auto-Wrap
Returns*.

```saw
func record(entry: Result<Int, String>) { … }

record(42)        // Ok(value: 42)
record("bad row") // Err(error: "bad row")

let rows: Vector<Result<Int, String>> = [1, 2]   // two Ok elements
```

A `Result<T?, E>` fed a bare `T` takes both wraps, innermost first:
`record_opt(4)` against `Result<Int?, String>` is `Ok(Some(4))`. Argument
position does not erase: a concrete error passed where
`Result<T, Box<any Error>>` is declared must be written as an explicit `Err`
value, since the erasure needs the allocator the return position supplies.

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

// Conformance via extension
extension Point: Display {
    func display(&self) -> String {
        "({self.x}, {self.y})"
    }
}

// Trait bounds (a place read inside a generic body needs a Copy bound)
func print_all<T: Display + Copy>(items: &Vector<T>) {
    for item in items.iter() {
        print(item.display())
    }
}

// Multiple bounds (implemented) — require several traits with `+`
func process<T: Display + Equatable>(item: T) { ... }

// Associated types
trait Iterator {
    type Item
    func next(&var self) -> Item?
}

// Trait refinement (supertraits)
trait ExplicitCopy: Deinit {
    func copy(&self) -> Self
    // ExplicitCopy implies Deinit; the deinit itself is synthesized
}
```

**A static requirement spells `static`**, on the same terms as a
[static method](#static-methods): a requirement with no receiver is declared
`static func`, and one that omits the keyword is a clean error at the
declaration. Conformance matching requires the kinds to AGREE — a static
requirement is satisfied only by a static, an instance requirement only by an
instance method:

```saw
trait Maker {
    static func make(seed: Int) -> Self
    func label(&self) -> String
}

extension Point: Maker {
    static func make(seed: Int) -> Point { Point(x: seed, y: 0) }
    func label(&self) -> String { "point" }
}
```

Writing `func make(&self, seed: Int)` in that conformance is an error naming
the missing keyword, and declaring `label` `static` is the error in the other
direction. Neither substitution can be called through: a static has no
receiver for a caller to supply, and an instance method's vtable slot has no
parameter without one.

A trait carrying a static requirement is a generic **bound**, never an
`any Trait` existential — dispatch needs a receiver, and a static has none.
`Deserialize` is the standard-library case; see
[Serialization](#serialization-serialize-deserialize-encoder-decoder).

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
    try! shapes.push(Box<any Shape>.make(Circle(r: 2)))
    try! shapes.push(Box<any Shape>.make(Square(s: 3)))
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
laid out `[deinit, size, align, type_id, methods…]` with the methods in trait
declaration order. `Box<any Trait, A>` teardown takes the deinit, size, and
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
  (freeing the shell *without* running the deinit, since ownership transfers)
  and yields `Some(T)`; on a mismatch it drops the box (deinit + dealloc) and
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
- a method that names `Self` in a **parameter** or in its **return type** — two
  `any Trait` values need not share a concrete type, so no vtable thunk can
  accept the operand or size the result. This covers the Copy family
  (`-> Self`), `Equatable`/`Comparable` (`other: &Self`), and any nesting
  (`-> Result<Self, E>`). By reference or by value makes no difference; the
  `&self` / `&var self` *receiver* is fine, so a mutating method IS erasable;
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
  conform **builtin** — the compiler renders them inline. An UNSIGNED value
  renders unsigned through every path — `print`, interpolation and `to_string()`
  agree on the full `0..2^64-1` range (design 122 closed DF-119b, where
  `print(UInt.max)` alone emitted `-1`).
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
        try! into.append("(")
        try! into.append(self.x)     // append(Int) overload
        try! into.append(", ")
        try! into.append(self.y)
        try! into.append(")")
    }
}
// A Printable field is streamed into the SAME builder (no intermediate Strings):
struct Line { a: Point, b: Point }
extension Line: Printable {
    func format(&self, into: &var StringBuilder) {
        try! into.append("Line[")
        self.a.format(into: &var into)   // forward the shared builder
        try! into.append(" -> ")
        self.b.format(into: &var into)
        try! into.append("]")
    }
}

let p = Point(x: 3, y: 4)
print("point = {p}")   // point = (3, 4)
```

#### Format arguments and the allocation-free path

**Status: implemented.** `print`, `panic` and `assert` take a literal format
string with `{}` placeholders followed by one value per placeholder:

```saw
print("x = {}", x)
print("{} of {} frames used", used, total)
panic("out of {}: wanted {}", "frames", 64)
assert(a == b, "want {} got {}", a, b)
```

Each argument keeps its own type and renders through its own `format`. These are
monomorphized generics, not varargs, so the placeholder count and the argument
count are compared at compile time:

```saw
print("{} and {}", 1)
// error: `print` format string has 2 placeholders but 1 argument was given
```

The format string has to be a literal, since that is what the count is read
from. Mixing `{name}` interpolation into a format string that also carries
arguments is rejected; use `{}` for every slot. Write `\{` and `\}` for literal
braces, which stay literal beside a real placeholder.

**Nothing on this path allocates.** Literal parts of the format string are
interned constants, integers are rendered into stack scratch, a `String` is
already its own bytes, and a user `Printable` streams through `format` into a
fixed-capacity builder over stack scratch. The interpolation spelling `"{x}"`
cannot do this: it produces a `String`, which is a heap value by definition.
That is the difference between the two spellings, and the reason the fixed one
exists:

```saw
print("x = {x}")     // builds a String, then writes it
print("x = {}", x)   // writes the pieces; no allocation anywhere
```

Both produce the same bytes. The second works in the freestanding profile with
no allocator at all, and with a hosted allocator refusing every request. It is
also the only one of the two that compiles under
[`--no-hidden-alloc`](#no-hidden-allocations---no-hidden-alloc).

A `print` line has no length limit — each piece goes to the output seam at its
own length, so a long `String` argument is written whole. The one bounded piece
is a single user `Printable` rendering (512 bytes), which truncates with the
marker below. `panic` and `assert` assemble one message and are bounded as a
whole (508 bytes of message); see [Panic](#panic-for-unrecoverable-errors).

An integer argument renders at its own width, not the platform's. `Int64` and
`UInt64` print all 64 bits on a 32-bit target, where the digit loop lowers to
the 64-bit division libcalls; every narrower type extends to the platform word
as before. `print(v)`, `print("{}", v)` and a panic message that names `v`
produce the same bytes at every width.

#### `StringBuilder` fixed mode

**Status: implemented.** `StringBuilder(bytes:capacity:)` builds over
caller-provided storage instead of the heap. It never grows and never frees:
content that does not fit is cut on a UTF-8 boundary and the marker `…` is
stamped in its place, so a shortened result says it was shortened.
`is_truncated()` reports it, and stays true until `clear()`.

```saw
var store: [Int8; 32] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
var b = StringBuilder(bytes: (&store) as UnsafePointer<Int8>, capacity: 32)
try! b.append("n = ")
try! b.append(42)
print(b.build())          // n = 42
print(b.is_truncated())   // false
```

The last four bytes of `capacity` are reserved for the marker and the NUL
terminator, so a builder holds `capacity - 4` bytes of text. A capacity below
five panics: there is no room to say anything.

Fixed mode is what `print`/`panic`/`assert` hand to a user type's `format`, so
whether a type is printable without allocating depends on how its `format` is
written. `append` calls are allocation-free; `"{...}"` interpolation inside a
`format` body is not.

```saw
extension Point: Printable {
    func format(&self, into: &var StringBuilder) {
        try! into.append("(")        // allocation-free
        try! into.append(self.x)
        try! into.append(")")
    }
}
extension Other: Printable {
    func format(&self, into: &var StringBuilder) {
        try! into.append("({self.x})")   // builds a String first
    }
}
```

`append(value: Int)` and `append(value: UInt)` render digits directly, with no
intermediate `String`. Forwarding to a builtin's own `format` —
`self.n.format(into: &var into)` — is allocation-free too, so either spelling of
a field is safe inside a `format` body. In fixed mode `append` and
`append_char` never
report `Err`: there is no allocator to refuse them, and truncation is reported
by the marker and `is_truncated()` rather than by an `AllocError` naming a
failure that did not happen. That is why a `format` body may spell `try!` — the
storage it writes into cannot refuse.

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
        try! into.append("parse error ")
        try! into.append(self.code)
    }
}

func parse(ok: Bool) -> Result<Int, Box<any Error>> {
    if ok { return 42 }        // Ok
    return ParseErr(code: 7)   // auto-wrap Err + auto-erase to Box<any Error>
}
```

> **Freestanding note.** Erasing an error boxes it through `GlobalAllocator`, so
> `Result<T, Box<any Error>>` is a *hosted convenience*. That box is named — it
> is written in the signature — so `--no-hidden-alloc` allows it. What a kernel
> wants is a concrete or closed-union error type (`Result<T, ConcreteE>`), which
> allocates nothing at all.

### Type Definitions

**Status: implemented** for distinct `type` aliases with one-way flow (alias →
underlying allowed, the reverse requires explicit construction) and function-type
aliases. Generic type aliases (`type Handler<T> = ...`) are *planned*.

The underlying type may not be an **enum**. An alias exists to be read back to
what it names, and `as` has no enum reading — so an enum alias would be a name
with no way out. It is refused at the alias declaration, whether the enum is
named directly, reached through a chain of aliases, raw-backed, or written with
a module qualifier:

```saw
enum Level { case High, case Low }

type Rank = Level      // Error! an alias of an enum is not allowed
type Step = Rank       // Error! the same, through the chain
```

Structs and primitives are unaffected. This includes the built-in enums, so
`type Outcome = Result<Int, ParseErr>` is refused today as well; a use case is
what would reopen the question.

```saw
// Type definitions create distinct types (not interchangeable aliases)
type UserId = Int
type OrderId = Int

// Even with the same underlying type, they are distinct
let user = UserId(42)
let order: OrderId = user  // Error! Types are not compatible

// Useful for units and domain types
type Miles = Float
type Kilometers = Float

let m = Miles(100.0)
let k: Kilometers = m  // Error! Can't mix miles and kilometers
```

`Alias(value)` is the way INTO a distinct type. It takes exactly one unlabeled
argument, which is checked against the underlying type — so a bare literal
adopts that type and is range-checked there, and a value of an unrelated type is
a clean error. The construction is representationally free: an alias is its
underlying at runtime, and the distinction is the typechecker's alone.

An alias over an unsigned or fixed-width underlying has no other spelling. An
annotated `let` accepts an underlying-typed initializer only for the four
primitive kinds (`Int`, `Float`, `Bool`, `String`), so `type Handle = UInt` is
constructible through `Handle(...)` and nothing else.

```saw
type Handle = UInt
type Small = Int64

let h = Handle(7)        // the only spelling for an unsigned underlying
let s = Small(99)        // the literal adopts Int64 and is checked there
```

Going the other way needs no ceremony. A distinct type flows to its underlying
implicitly at a call site or an annotation, and `as` projects it explicitly:

```saw
// Project a distinct type TO its underlying with an explicit cast. There is no
// `.value` accessor. The cast is ONE-DIRECTIONAL (toward the underlying):
// `42 as UserId` stays an error — that is what `UserId(42)` is for — and a
// sibling-alias cast (`user as OrderId`) is rejected too. A partial projection
// to an intermediate alias on the chain is allowed.
let raw: Float = m as Float
let uid: Int = user as Int

// Type definitions for function signatures
type Callback = (Int) -> Bool
type Handler<T> = (T) -> Result<(), Error>
```

### Type Extensions

**Status: implemented** for user-defined structs and enums (methods — including
overloaded methods and static methods, see [Functions](#functions) — overloaded
custom `init`, and — see Traits — conformance via `extension Type: Trait`).
An extension on an enum is an extension on a struct, with one exception: no
`init`, because the cases are the constructors. See
[Methods on enums](#methods-on-enums).
Extending built-in primitive types (`extension Int`, `extension Float`) is also
implemented (design 57 registers them as extendable — the stdlib numeric methods
are built this way). Computed properties and generic specialized extensions
beyond what monomorphization already supports remain *planned*. Some method
bodies below use stdlib methods (`.sqrt()`, `.cos()`) that are *(illustrative)*.

```saw
// Add methods to struct types
extension Point {
    // Read-only method (shared reference to self)
    func distance_from_origin(&self) -> Float {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    // Mutating method (exclusive reference to self)
    func scale(&var self, factor: Float) {
        self.x *= factor
        self.y *= factor
    }

    // Custom initializer (overloaded by parameter names)
    init(magnitude: Float) -> Point {
        Point(x: magnitude, y: magnitude)
    }

    // Another custom initializer
    init(polar: Float, angle: Float) -> Point {
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

// Trait conformance via extension IS implemented:
extension Point: Display {
    func display(&self) -> String { "({self.x}, {self.y})" }
}
```

`Self` names the type being extended, in any signature position — a parameter,
a return, and nested inside either (`&Self`, `Self?`, `Vector<Self>`,
`(Self, Int)`, `[Self; 2]`). It works the same on a GENERIC extension, where it
means that extension applied to its own parameters:

```saw
struct Wrap<T> { v: T }

extension Wrap<T> {
    func same(&self, other: &Self) -> Int { 9 }   // &Self is &Wrap<T>
    func bumped(&self) -> Self { Wrap<T>(v: self.v) }
}
```

An extension re-declares the type's parameters POSITIONALLY, so it may RENAME
them. The extension's names are what its signatures and bodies are written in,
and they bind to the receiver's arguments exactly as the type's own names do:

```saw
struct Pair<A> { first: A, second: A }

extension Pair<U> {                                  // U is Pair's A
    func agree(&self, other: &Pair<U>) -> Bool { ... }
    func firstval(&self) -> U { self.first }
}
```

Repeating the type's own names is the clearer spelling and the usual one.

#### What an `init` may return

An `init` declares one of exactly two return types, and the compiler checks
which:

- **the receiver** — `Self`, the receiver written out (`Wrap<T>` inside
  `extension Wrap<T>`), or no return clause at all. `Point(magnitude: 5.0)`
  then has type `Point`.
- **`Result<Receiver, E>`** — the fallible constructor. `Config(path: p)` then
  has type `Result<Config, ConfigError>`, and composes with `try`, `try!`,
  `try?`, `match`, the `try(as ...)` routing clause and
  [Discarding a Result](#discarding-a-result) with nothing extra written.

```saw
enum ConfigError { case Missing, case TooLarge(bytes: Int) }
// ... Printable + Error conformances ...

struct Config { budget: Int }

extension Config {
    init(budget: Int, ceiling: Int) -> Result<Config, ConfigError> {
        if budget == 0 { return ConfigError.Missing }
        if budget > ceiling { return ConfigError.TooLarge(bytes: budget) }
        return Config(budget: budget)
    }
}

func load(budget: Int) -> Result<Int, ConfigError> {
    let cfg = try Config(budget: budget, ceiling: 4096)
    return cfg.budget
}
```

The body is checked the way any `Result`-returning body is: a receiver value
becomes `Ok`, an error value becomes `Err`, and the tail expression follows the
same rule a `return` does, so neither variant is written by hand.

Anything else is a compile error at the declaration, naming both legal forms.
An OPTIONAL return is refused on its own terms:

```saw
extension Config {
    init(budget: Int) -> Config? { ... }
}
// error: `init` may not return an optional — an optional creation encodes as
//        `Result<Config, E>`, because a `None` names no cause
// hint: write `-> Result<Config, E>` naming the error the absence meant, and
//       return that error where the `None` was
```

A constructor that fails has a reason, and `None` discards it. That is the same
never-hide-errors rule [Error Handling](#5-error-handling) states for every
other operation.

Limit: an `init` body may not suspend. A suspending call inside one is an
internal compiler error today rather than a diagnostic; compute the value in a
suspending function and hand it to an ordinary `init`.

**Key Features:**
- Methods use `&self` (shared reference) or `&var self` (exclusive reference).
  Both receivers are borrows and the sigil says so; a bare `var self` is a
  compile error pointing at `&var self`
- A method with no receiver is declared `static` (below)
- A custom `init` returns the receiver, or `Result<Receiver, E>` when it can
  fail
- Multiple `init` methods distinguished by parameter names
- Mutable methods receive a reference for efficient mutation
- Field assignment needs `&var self`: `self.field = value` in a `&self` method
  is a compile error (below)

#### Static methods

**Status: implemented.** A static method is declared `static` and takes no
receiver. The keyword is required, and the parameter list may not disagree
with it:

```saw
struct Bag { n: Int }

extension Bag {
    static func make(seed: Int) -> Bag { Bag(n: seed) }   // static
    func count(&self) -> Int { self.n }                   // instance

    func dup(x: Int) -> Int { x * 2 }
    // error: method `dup` has no receiver — add `&self`/`&var self`, or
    //        declare it `static func` if a static was intended
}
```

Staticness is fully determined by the missing receiver, so it could be
inferred, and until this rule it was. What the keyword buys is the other
direction: a method that forgets its `&self` used to become a static silently,
which is a different kind of method than the author wrote. The declaration now
says which one it is, and the fixit names both readings because the compiler
cannot tell them apart.

The mirror holds. A `static` method that takes `&self` or `&var self` is a
clean error at the declaration, and so is `static init`: an `init` takes no
receiver by construction and is already called on the type, as `Bag(...)`.

The type is the only way to call a static, `Bag.make(seed: 5)` and never
`b.make(seed: 5)`. A static has no receiver for a value to become, so the
instance spelling is a clean error naming the type spelling, at every way of
spelling a receiver — a local, `self`, a call result, an element, and a FIELD
ACCESS (`outer.inner.make(seed: 5)`), which reads like the qualified
`module.Type.method()` form and is not one. The two kinds may share a name:
each call shape picks the one it can mean.

The same rule covers an enum's VARIANTS, which are constructors rather than
methods: `Color.Red` and `Color.Custom(r: 3)` name a variant on the type, and
naming one through a value (`c.Red`, `h.color.Custom(r: 3)`) is the same clean
error. To ask which variant a value holds, `match` it.

`static` here is the same keyword a
[module-level static](#module-level-statics) uses, in a different position. A
declaration head continues into a name and a colon (`static PAGE_SIZE: Int =
4096`); a member head continues into `func`. Module-level functions are not
methods, so the rule never reaches them, `@export`ed C-ABI seams included.

Enums take statics on these terms unchanged (see
[Methods on enums](#methods-on-enums)), and so do generic extensions. Visibility
comes first: `public static func make(...)`.

#### A `&self` method may not write its receiver

A `&self` receiver is a shared borrow, and it arrives **by value**. A write into
it would land in the copy the method discards:

```saw
extension Counter {
    func peek(&self) -> Int {
        self.hits = self.hits + 1   // error: cannot assign to storage reached
        self.hits                   //        through a `&self` receiver
    }
}
```

The rule covers every write whose target is storage inside the receiver — a
field, a nested field, a tuple element, an optional payload, an element of an
inline `[T; N]` — in both the plain and the compound spelling, and it covers the
`&var self.field` projection that would hand such a write to someone else. Two
ways to say what you meant: declare the method `&var self`, or lend the storage
with a `borrows` accessor and let each use site pick the window's flavor.

It also covers the mutation spelled as a **call**, in both receiver forms.
`self.reset()` inside a `&self` body, where `reset` takes `&var self`, is the
same error: a `&var self` method takes the entire receiver exclusively, which is
the one thing `&self` says it will not do. So is the same call on a **field** —
`self.cells.push(9)` runs against the copy's `Vector` header, so the caller sees
no new element:

```saw
extension Bag {
    func peek(&self) -> Int {
        self.cells.push(9)      // error: cannot call `&var self` method `push`
        self.cells.len()        //        on storage reached through a `&self`
    }                           //        receiver
}
```

The field form is worse than a vanishing field write, because the copy and the
original share a buffer: a push that does not reallocate writes into storage the
caller owns while the caller's `length` stays behind.

The fourth spelling is a **place window**. Where a field's type publishes a
`borrows` accessor, a write through it opens an exclusive window on the copy:

```saw
struct Board {
    grid: Grid          // Grid holds an INLINE [Cell; 9] — the refusal below
}                       // is about inline storage; a Vector field is the
                        // heap-buffer case the next paragraph ALLOWS

extension Board {
    func bump(&self) {
        self.grid[0] += 100     // error: cannot write through a place window on
    }                           //        storage reached through a `&self` receiver
}
```

Only an *exclusive* window is refused. A read (`self.grid[0]`) opens a shared
one, which lends the element read-only, so nothing is written and nothing is
lost. What decides the rest is where the accessor lends from: `Grid` above lends
an element of its own inline `[Cell; 9]`, while `Vector.[]` lends out of the
heap buffer `self.buffer` points at — so `self.rows[0][0] += 100` reaches the
caller's element and is allowed, on the same terms as the direct write below.

Storage the receiver only *points at* is not covered, because a copy of the
receiver shares it rather than duplicating it. A `Vector` field's elements live
in its heap buffer, so `self.cells[i] = v` writes the caller's element and is
allowed; the same goes for a write through an `UnsafePointer` field, and for a
`&var self` method reached through either.

**Interior mutability writes through `&self`, and that is the point.**
`self.n.fetch_add(1)` on an `Atomic` field, `self.lock.lock({ ... })` on a
`SpinLock` one, and `self.cell.set(v)` on a wrapper you wrote yourself are all
idioms rather than mistakes. None of them is an exception to the rule above:
each is a `&self` METHOD, which this rule never refused, and what makes the
write reach the caller's storage is that a
[cell-carrying](#interior-mutability) receiver arrives by POINTER even at
`&self`.

A `&var self` method is a different claim and stays refused whatever the field
holds. It takes the entire receiver exclusively — sibling fields included — and
that is the one thing `&self` promises not to do; that a cell-carrying receiver
arrives by pointer means the write would *land*, not that the exclusivity claim
is honest. So a wrapper around a cell gets no exemption, and its author's
recourse is the same as anyone's: `&self` methods, which the cell is what makes
writable.

The rule holds inside a `borrows` body too, prologue and epilogue included. That
is where it matters most: an accessor's receiver travels by pointer, so a field
write there does not vanish, it *lands* — a read through a shared window would
mutate a `let` root.

The place-window spelling is the one exception, and it is intended. A window
write in an accessor's prologue or epilogue reaches the caller's storage for the
same by-pointer reason, which is what an accessor that must touch its receiver
before lending needs. It runs for a shared window as well as an exclusive one,
so an accessor that means to count only writes gates the mutation on
`#lend_var` (see [Places](#places-borrows-and-lend)).

---

## 4. Memory Management

**Status: implemented** (the Copy trait family, `Deinit`, exclusivity, and
reference parameters are all built and enforced). No garbage collector;
destruction is deterministic and LIFO at scope exit.

### The Copy Trait Family

**Status: implemented.** Three words carry Saw's transfer semantics, one job
each. `Copy` is the tier of values the compiler may duplicate silently.
`NoCopy` is the opt-out that makes a type move-only. `ExplicitCopy` is an
ordinary trait naming the wider family of values that can be duplicated at all,
possibly at the cost of a spelled `.copy()`. This replaces the earlier "copy by
default, explicit move" framing and the never-implemented "deep copy for
collections" claim: the cost of every transfer is readable at the use site.

- **`Copy` is DERIVED, not declared.** A type whose owning members are all
  `Copy` is `Copy`, with no declaration written and none asked for. That covers
  the trivially-copyable (POD) types — `Int`, `Bool`, `Float`, POD
  structs/tuples, fixed arrays of such — and the refcounted ones: `String`,
  `Arc` and `Data` are `Copy`, and so is `struct Ticket { code: String }`.
  Whether a given type duplicates bitwise or by retaining a refcount is an
  emission detail, and no rule above code generation distinguishes the two.
  `Data`'s copy is a retain of shared storage; the bytes separate at the first
  write that finds them shared, so the copy stays O(1) without giving up value
  semantics (see [Data](#data)).
- **A DECLARED `Copy` conformance has two forms.** The empty one is an
  assertion — `@synthesize extension Point: Copy {}` compiles only while the
  members qualify, which makes it a type-level API contract. The one with a
  `copy()` body is the retain hook: the compiler calls that body at every silent
  transfer. `Arc` and `Channel` are built on it, in ordinary Saw rather than
  compiler magic, which is what lets you write your own `Arc`-alike.
- **The retain hook is a performance footgun, and stating that is the whole
  contract.** The body runs at transfer sites no source construct names, so a
  heavy one costs on every silent copy. Cheap and infallible is the expected
  shape. The compiler enforces one part of it, `sync` (below); the rest is the
  author's documented choice.
- **`NoCopy`** — never duplicable, on purpose (`File`, `Mutex`, `Box`,
  `SpinLock`, `Once`, [`Atomic`](#atomicint) — a copy of any of those is a
  second, independent piece of state; currently also `Map`/`Set`, whose
  `ExplicitCopy` conformance is future work). Move-only, and it is the
  declaration that overrides what the members would have derived.
- **`ExplicitCopy`** — the trait that says a duplicate exists and is spelled.
  Every `Copy` type satisfies it, since duplicating one for free is a valid way
  to answer `copy()`, so `<T: ExplicitCopy>` reads as "duplicable, possibly with
  ceremony" and is the bound that licenses a spelled `.copy()` on an abstract
  `T`. A type declaring it and nothing else is move-only: every transfer needs
  `move`, every duplicate a visible `.copy()`. **Contract: the duplicate may be
  expensive, and reaches every owned member** — e.g. `Vector` (whose conformance
  is bounded `T: ExplicitCopy`).
  `@synthesize extension T: ExplicitCopy {}` derives the memberwise body.
- **`NoCopy` and `ExplicitCopy` extend `Deinit`**: they are declared as
  `trait NoCopy: Deinit` and `trait ExplicitCopy: Deinit` in the builtin
  prelude. A type opts into one because it manages a resource, and managing a
  resource means having a `deinit`. The `deinit` itself is synthesized (see
  [Synthesized destruction](#synthesized-destruction)); declaring the policy is
  all you write.
- **`Deinit` is not declarable on its own.** `extension T: Deinit {...}` is a
  compile error naming the copy policies. A type that declared only `Deinit`
  had a `deinit` and no transfer rule, so `let s = r` fell through every arm
  of the checkpoint and both halves ran `deinit`. A hand-written `deinit` body
  goes inside the policy conformance, where the requirement is inherited:

  ```saw
  extension Res: NoCopy {
      func deinit(&var self) { close(self.fd) }
  }
  ```

  `T: Deinit` remains legal as a generic bound; only the conformance form is
  gone.
- **A type declares one of them, not both.** Both traits require the same
  method, `copy(&self) -> Self`, so a second conformance redeclares a method
  the type already has:

  ```saw
  @synthesize
  extension Ticket: Copy {}

  @synthesize
  extension Ticket: ExplicitCopy {}
  // error: method `copy` is already defined for struct `Ticket` with an
  //        indistinguishable signature
  //   hint: overloads must differ in arity or parameter types
  ```

  Declare `Copy` when transfers are silent. Every `Copy` type already
  satisfies an `ExplicitCopy` bound, so the second declaration would add
  nothing even if it compiled.
- **A hand-written `copy()` must be `sync`.** The `copy()` body
  inside a copy-policy conformance is the retain hook: the compiler calls it at
  transfer sites the source never spells, so a suspension inside it would
  suspend a function that declared itself `sync` with nothing on the page to
  show for it. A suspending body is refused at the conformance, where the
  author can act on it:

  ```
  error: cannot suspend in the `Copy` `copy()` of `Heavy`: method
         `Heavy.copy` calls yield_now (`Heavy.copy` suspends at line 8)
  hint: a copy-policy `copy()` runs at compiler-inserted call sites and must be
        `sync` ...
  ```

  Writing `sync` is optional: a body the effect analysis finds suspension-free
  already satisfies the rule, which is how every std hook (`Arc`, `Channel`,
  `Vector`) passes with nothing written. The rule is mechanical; the rest of
  the hook's contract is not. A `copy()` the compiler inserts everywhere should
  be cheap and infallible, and a heavy one is legal at the author's cost.

```saw
// Trivial: implicit bitwise copy, both valid
let a = 42
let b = a

// ExplicitCopy (e.g. Vector): transfer needs `move`, duplication needs .copy()
var v = try! Vector<Int>(capacity: 4)
var w = move v            // ownership transferred; v no longer valid
var u = w.copy()          // explicit, independent duplicate (its own buffer)

// Copy (String): copies are implicit refcount bumps, no `move` needed
let s1 = "hello"
let s2 = s1               // both valid; cheap retain
```

**The two bounds ask different questions.** `T: Copy` admits exactly the
silently-copyable tier: a body under it may duplicate the value with nothing
written at the site. `T: ExplicitCopy` admits the whole duplicable family, so
it grants `.copy()` and nothing more — an `ExplicitCopy` argument does not
satisfy `T: Copy`, because a body that copies it silently would be spending a
duplication the caller cannot see. Monomorphization emits the right operation per
instantiation. An unbounded `T` gets neither.

```saw
func dup<T: ExplicitCopy>(x: &T) -> T {
    x.copy()
}
```

**A type that mentions a type parameter has no tier of its own — it demands a
bound.** `Slot<K>`'s transfer class is whatever the instantiation's `K` turns
out to be, so it cannot be read off the declaration, and a site that must decide
before monomorphization asks the parameter's BOUNDS instead. A place value read
is such a site ([Value reads](#value-reads)): it is legal exactly when every
parameter the element type mentions carries a `Copy`-family bound, and the
refusal is reported in the generic body rather than at one caller's
instantiation. Where the read is legal, the copy is emitted at the
instantiation, alongside the matching drop, so the concrete tier decides which
copy it is.

**Derivation & containment.** A struct declaring `ExplicitCopy`/`Copy`
can have its `copy()` derived memberwise (POD fields bitwise, copy-policy fields
via their own `copy()`), but the derivation is opt-in: mark the extension
`@synthesize`, or write `copy()` by hand. See
[Synthesized conformances](#synthesized-conformances). A `NoCopy` field makes
derivation impossible and is reported by name.

```saw
struct Snapshot {
    rows: Vector<Int>,
    label: String
}

@synthesize
extension Snapshot: ExplicitCopy {}   // memberwise copy() + synthesized deinit
```

Containment is explicit, never inferred: a struct with
an `ExplicitCopy` (or `NoCopy`) field must itself declare that policy — the
compiler errors with a hint otherwise. Containment looks *through* array- and
optional-typed fields: a struct holding a `[NoCopy; N]` or a `File?` field is
move-only and must declare `NoCopy`, exactly as for a scalar `NoCopy` field.

**The automatic `Copy` tier.** A struct or enum whose owning members are
all trivial or `Copy` *is* `Copy`, with no declaration written
and none required. Copying such a value retains each refcounted member, and the
last owner's drop releases each one exactly once.

```saw
struct Ticket { code: String }     // no policy declared, and none is owed

func main() {
    let n = 3
    let a = Ticket(code: "ticket-{n}")
    let b = a                      // a free retain: `a` and `b` are both live
    print("{a.code} {b.code}")     // prints: ticket-3 ticket-3
}
```

The members that put a type on this tier without owing a declaration are the
ones whose retain and release the compiler handles itself: a `String` field, an
escaping closure field, a fixed array of either, and another struct or enum
already on this tier. A field of a *declared* `Copy` type is not one of
them — an `Arc<T>` field makes the containment rule apply as usual:

```
struct `Carrier` contains Copy field `tag` of type `Arc<Res>` but does
not implement Copy
```

Declaring the stricter `NoCopy` on a type that would be on this tier is legal,
and is how a type that could be copied for free is made move-only anyway:

```saw
struct Ticket { code: String }
extension Ticket: NoCopy {}        // stricter than the automatic tier

func main() {
    let n = 3
    let a = Ticket(code: "ticket-{n}")
    let b = a                      // error: cannot copy value of type `Ticket`
                                   //        which implements NoCopy
    print(b.code)                  // hint: use `move` to transfer ownership instead
}
```

Declared-policy ceremony stays where a genuine choice exists: `ExplicitCopy`
versus `NoCopy` for a type owning a `Vector`, a `File`, a `Box`. Between
retaining a refcount and not copying at all there is no such choice to make, so
the compiler does not ask for one.

**Fixed arrays.** A fixed array `[T; N]` is treated as an anonymous struct with
`N` uniform fields: it inherits T's copy tier. `[trivial; N]` copies bitwise;
`[Copy; N]` copies implicitly per element (each element's `copy()`);
`[ExplicitCopy; N]` is move-by-default and `arr.copy()` duplicates element-by-
element in index order; `[NoCopy; N]` is move-only. Owned elements are released
in **reverse index order** at scope death, composing with the enclosing struct/
enum drop glue. (A `[String; N]` field, like a scalar `String` field, does not
force the container to declare a policy — String's per-element retain/release is
compiler-handled.)

**Wrappers carry the tier of what they wrap.** Every type has exactly one
transfer class, and a type built out of other types is never weaker than its
parts. An `Optional<T>`, a tuple, a fixed array, an enum's payloads and a
`Result<T, E>` each take the strongest tier among the values they hold. So
`Vector<Int>?` is `ExplicitCopy` because `Vector<Int>` is, `File?` is move-only
because `File` is, and `Int?` stays trivial.

```saw
let v: Vector<Int> = [1, 2, 3]
let o: Vector<Int>? = move v

let p = o           // error: cannot copy value of type
                    //        `Vector<Int, GlobalAllocator>?` which implements ExplicitCopy
let q = o.copy()    // ok: an independent buffer
```

`.copy()` on an optional exists exactly when the payload's tier provides one,
and duplicates the payload the way that tier duplicates: `None` copies to
`None`, `Some` to `Some` of the payload's own copy. A `String?` retains, a
`Vector<Int>?` copies the buffer, a `File?` has no `.copy()` at all.

A refused optional transfer names three ways out: `.copy()`, `move`, and
`.take()`. The last writes `None` back into the place and hands the payload
over, which is what makes it the spelling that works on a *field* — `move` there
would be a partial move.

A tuple works the same way. `t.copy()` exists when no element is move-only, and
copies each element at that element's own tier: a `String` or `Arc` element
retains, a `Vector<Int>` element gets its own buffer, a trivial one is copied
bitwise. A tuple holding a `NoCopy` element has no `.copy()`, and the refusal
names the offending element by position and type.

```saw
var v: Vector<Int> = [1, 2]
let t = (move v, 7)

var (a, n) = t.copy()   // ok: `a` is an independent buffer
try! a.push(3)          // t.0 still holds 2 elements
```

**Enums declare a policy too.** An enum carrying an `ExplicitCopy` or `NoCopy`
payload names its transfer class the way a struct with such a field does, and a
bare one is the same error with the same hints. An enum whose payloads are only
trivial or `Copy` needs no declaration, exactly as a `String`-field
struct needs none.

```saw
enum Reel {
    case Loaded(t: Tape),      // Tape is NoCopy
    case Empty
}

extension Reel: NoCopy {}      // move-only

enum Bag {
    case Nums(v: Vector<Int>),
    case Empty
}

@synthesize
extension Bag: ExplicitCopy {}  // copy() over the active variant's payload
```

The derived enum `copy()` switches on the active variant and duplicates only
that variant's payload, each field at its own tier. A payload-free variant is a
bare tag and copies as itself.

**Optional payloads follow the same table.** Reading the payload out of an
optional that someone else still owns is a read out of storage, so it is
governed by the payload's own policy — see
[Payload reads](#payload-reads-the-place-rule).

The only implicit copies are cheap by contract, which is the part of design
principle #4 this section carries: an innocent `=` is never secretly O(n). The
allocations no signature announces are listed, and rejected under a flag, in
[No hidden allocations](#no-hidden-allocations---no-hidden-alloc).

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

See [Resource Management Traits](#resource-management-traits) for the full `Deinit`/`Copy`/`ExplicitCopy`/`NoCopy` hierarchy.

### Reference Types

**Status: implemented.** Reference types (`&T` and `&var T`) allow passing values by reference without copying. References are only valid as function/method parameters and cannot escape. Mutation through a `&var` reference is done with compound assignment (`x += 1`), mutating methods, or — as of design 110 — whole-referent *replacement* assignment `x = v` (the same rule closures already followed; see below). Some example bodies below use planned stdlib methods (`push_str`, `String.from`) and are *(illustrative)*.

```saw
// &T - shared reference (read-only access)
func print_length(s: &String) {
    print(s.len())  // Can read through reference
}

let msg = "Hello"
print_length(&msg)  // Pass reference with &

// &var T - exclusive reference (allows modification)
func append_greeting(s: &var String) {
    s.push_str(", world!")  // Can mutate through reference
}

var msg = String.from("Hello")
append_greeting(&var msg)  // &var mirrors the &var parameter
print(msg)  // "Hello, world!"

// Multiple reference parameters.
func swap<T>(a: &var T, b: &var T) { ... }

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
- An exclusive reference allows compound assignment: `x += 1` where `x: &var Int`
- **Whole-referent replacement (design 110):** `x = v` through a `&var T`
  function/method reference parameter — and `self = v` in a `&var self` method —
  *replaces* the referent in place. It is legal exactly when `v` would type-check
  against `var x: T = v`: the RHS goes through the ordinary value-transfer
  checkpoint (a fresh temporary needs nothing; a `Copy` binding copies
  implicitly; an `ExplicitCopy`/`NoCopy` binding needs `move v` / `.copy()`, and
  the `move` consumes the *callee's* local). The old referent value deinits
  exactly once, then the new value installs; the caller's binding is never
  invalidated and still owns a valid `T`. This unifies functions/methods with
  closures, which already permitted `n = v` through a `&var`/`[&var]` parameter.
  Two exclusions keep their own diagnostics: (1)
  assignment through a shared `&T` is rejected (read-only); (2) the referent
  must be a **statically-known** type — a `&var any Trait` **erased** referent is
  rejected (behind the erasure the caller's slot is a concrete type, so a
  differently-typed store would corrupt it), with a specific error pointing at
  the `Box<any Trait>` level. The payload-swap idiom that *does* work: a
  `&var Box<any Shape>` referent is a sized concrete type, so
  `b = Box<any Shape>.make(Square(...))` replaces the payload and the caller's
  binding stays a valid `Box<any Shape>`. A generic `&var T` referent works per
  instantiation — inside the abstract body the RHS must itself be a `T`.
- Moving out of references is not allowed: `move x` where `x: &var T` is an error
  (it would invisibly invalidate the caller's object)
- A bare trait name behind a reference (`&Shape` / `&var Shape`) is unsized and
  rejected — write the existential (`&any Shape` / `&var any Shape`)
- References cannot escape: cannot return, store in structs, or be captured by
  an escaping closure. A capture that lowers to a pointer into the enclosing
  frame is legal only in a closure passed directly to a non-escaping parameter,
  and three spellings reach that rule: the explicit `[&x]`/`[&var x]`
  borrow-capture, a plain capture of a `&T`/`&var T` **parameter**, and a
  closure body naming `self` (a receiver is a borrow). See
  [Capturing `self` and reference parameters](#capturing-self-and-reference-parameters)

**A return type may not name a reference.** The no-escape property above is
enforced at the declaration, in every position a return type is written: a
`func`, an extension method or `init`, a trait requirement, an `extern func`,
and the function-**TYPE** grammar (`(Int) sync -> &Int`). The rule reads what
the return type *names*, not its outermost spelling, so `(Int, &Int)`, `&Int?`
and `Vector<&Int>` are refused on the same terms. It stops at a nested function
type: that type's parameter list takes references legitimately — `(&T) sync -> R`
is `Vector.with_ref`'s callback — and its own return was checked at its own
arrow. A reference in *parameter* position is untouched anywhere.

```saw
extension Counter {
    func peek(&self) -> &Int { &self.n }
    // error: method `peek` may not return a reference: the return type `&Int`
    // is a reference, and references in Saw are PARAMETERS ONLY — a reference
    // borrows storage for the duration of one call and may not escape it ...

    func slot(&self) borrows -> Int { lend self.n }   // the accessor that works
}
```

The diagnostic anchors on the return-type token and names the two ways to write
what was meant: return the **value**, or — to hand out storage the receiver
already owns — declare a `borrows` accessor, which lends the place for a window
instead of letting a pointer out (see *Places* below). Until this was enforced,
`func dangle() -> &Int { let local = 99  return &local }` compiled and ran,
printing out of a frame that had already died.

**A field, an enum payload, a generic argument and a closure's return may not
name one either.** These positions carry a reference past the call that created
it without ever writing a `&` in a signature, and each is refused where it is
written:

- **A struct field.** `struct Holder { r: &Int }` is rejected at the field
  declaration. That closes the construction with it: no field has a reference
  type, so `Holder(r: &x)` has nothing to fill. A struct literal is not a call
  argument, which is why the field is the position that has to say no.
- **An enum case payload.** `enum Slot { case Held(r: &Int) }` is storage on
  exactly a field's terms, and it was the position that made the whole rule
  routable around: wrap the reference in a one-case enum and it went into
  `Vector` storage that outlived the call.
- **A generic argument**, in a type position (`let v: Vector<&Int>`) and at an
  explicit instantiation (`idn<&Int>(&x)`) alike. A generic holds its argument
  as storage, and `v.push(&x)` into a `Vector<&Int>` is a genuine call argument
  — so the refusal is at the argument rather than at the call, where a
  reference argument is exactly what is meant.
- **A closure's inferred return.** A closure literal writes no return type, so
  the declaration-side rule above has nothing to read: `{ &x }` typed
  `() -> &Int`. The check runs at inference instead and anchors on the body's
  tail expression. Reading a reference *binding* yields the value, so the
  `with_ref` identity closure `{ e in e }` returns a `T` and is untouched.

Three further declarations name a type without writing a `&` in any signature,
and each is refused too:

- **A `static`.** `static SLOT: &Int` declares the longest-lived storage in the
  language: it outlives every call in the program.
- **An associated-type assignment.** `type Item = &Int` in an extension names
  the type every use of `Item` resolves to — a field's type, a return type, a
  generic argument — so one reference there reaches all of them.
- **A generic parameter's default.** `struct Holder<T = &Int>` substitutes
  `&Int` for an omitted argument before mangling, which fills every field typed
  `T` without the argument position ever being written.

All of them read what the type *names*, on one walk, and each diagnostic states
the rule and the same two ways out. A reference written anywhere else that is
not a call argument — bound to a `let`/`var`, used as an operand, placed in a
literal — is refused on the same terms.

**A `type` alias is not a way past any of it.** The walk resolves aliases before
it reads a type, so `type R = &Int` is refused in every position above — a
field, a payload, a generic argument (`let v: Vector<R>`), a return type — and
so is the alias's own back-conversion, `R(&x)`, which is what would have
inhabited them. The alias used to hide a reference from all four checks, because
each reads the type as WRITTEN. A PARAMETER is untouched: the walk has never run
there, and a parameter is where a reference belongs.

**The one crossing: a cast to a pointer.** `(&x) as UnsafePointer<T>` and its
const twin are legal in **any** expression position — a call argument, a local
binding, a function's return expression, and the chained
`(&self) as UnsafePointer<TaskGroup> as Int` that turns an address into a
token. This is the only address-of Saw has, and it is a crossing into the
unsafe tier rather than an escape. What survives the expression is a pointer
rather than a reference, so keeping the referent alive and unmoved for every
dereference becomes the unsafe tier's obligation; the unsafe effect the pointer
forces onto every signature that names it is the fence from there on. The cast
must name a pointer type to qualify —
`(&x) as Int` is an ordinary expression and the reference in it is refused.

```saw
extension Counter {
    func cell(&var self) unsafe -> UnsafePointer<Int> {
        (&var self.n) as UnsafePointer<Int>   // the address, into the unsafe tier
    }
}

let r = &x        // error: `&` here is not a call argument, and references in
                  // Saw are PARAMETERS ONLY ...
```

```saw
struct Holder { r: &Int }
// error: field `r` of `Holder` may not be a reference: its type `&Int` is a
// reference, and references in Saw are PARAMETERS ONLY — a reference borrows
// storage for the duration of one call and may not escape it ...

let f = { &x }
// error: a closure may not return a reference: this body's value has type
// `&Int`, which is a reference ...
```

#### Capturing `self` and reference parameters

A closure body may name `self`, and may name a `&T`/`&var T` parameter of the
enclosing function. Both are captured **by borrow**: the environment holds a
pointer to the storage, so the body reads the live value, and through a
`&var self` receiver or a `&var T` parameter it writes the caller's storage.

```saw
extension Counter {
    func viaFree(&self) -> Int { run_int({ self.n + 1 }) }

    func bump(&var self) -> Int {
        run_int({ self.n = self.n + 10  self.n })   // the write lands on the caller's value
    }
}
```

A receiver is a reference, so this is the same rule as everywhere else in this
section: **a capture that lowers to a pointer into the enclosing frame is legal
only in a closure passed directly to a non-escaping parameter.** One predicate,
three spellings — the explicit `[&x]`/`[&var x]` borrow-capture, a reference
parameter, and `self`. Outside that position the environment is heap-allocated
and outlives the frame it points into, so the capture is refused:

```saw
extension Counter {
    func handOut(&self) -> () -> Int { return { self.n + 3 } }
    // error: an escaping closure cannot capture `self`: a method's receiver is
    // a borrow of storage the CALLER owns — a reference borrows storage for the
    // duration of one call and may not outlive the frame it points into
}

func make(r: &Thing) -> () -> Int { return { r.x + 1 } }
// error: an escaping closure cannot capture `r`, a reference (`&Thing`) ...
```

Binding the closure to a `let` counts as escaping even when it is called in the
same frame: the environment is on the heap either way, and the checker judges
the position rather than the eventual use. The diagnostic names the ways out —
copy the values the body needs into locals ahead of the closure and capture
those, or take the receiver as an explicit closure parameter
(`body: (&Counter, Int) sync -> R`, called as `self.run({ c, v in c.n + v })`).

A **consuming** `self` receiver (declared without `&`) is an owned binding, not
a borrow, so it is captured by value under the ordinary transfer rules.

The capture may also be written out loud, behind a borrow sigil:

```saw
extension Counter {
    func viaFree(&self) -> Int { run_int({ [&self] in self.n + 1 }) }
    func bump(&var self) -> Int { run_int({ [&var self] in self.n += 10  self.n }) }
}
```

`[&self]` and `[&var self]` mean exactly what the implicit capture means, and
they meet the same non-escaping rule. `[&var self]` requires a `&var self`
receiver: a shared receiver has no exclusive borrow to hand out, and asking for
one names the working spelling.

```saw
extension Counter {
    func read(&self) -> Int { run_int({ [&var self] in self.n + 1 }) }
    // error: `[&var self]` needs a `&var self` receiver, and `read` takes
    // `&self`: a shared borrow has no exclusive borrow to hand out
}
```

The reverse narrows, and the narrowing has teeth: `[&self]` inside a
`&var self` method captures the receiver **shared**, so a write through it is
refused exactly as it would be in a `&self` method. `self` appears in a capture
list only behind `&` or `&var` — `[self]` and `[move self]` are parse errors,
since the receiver's own mode decides the capture's.

The enclosing method may be `sync` or **suspending**; both compile and both read
the live receiver. A driven method's receiver lives behind the task frame, and
the frame lends it to the closure as a handle it duplicates for the purpose.

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

**Reference forwarding (re-borrowing a received reference):** a reference
parameter (or a `&var self` receiver) may itself be the operand of `&`/`&var` at
a call site — passing a received reference *onward* to another reference
parameter. This is a **re-borrow**: the callee gets a reference to the same
referent, and codegen forwards the already-held pointer (no re-take of a local
address). The call-site sigils still mirror the parameter, and the mutability
rules hold: **a `&var` forward requires an incoming `&var`** (a shared `&`
reference cannot be upgraded to `&var` — rejected cleanly), while a `&var` may be
forwarded as `&` (a downgrade to a shared read is fine).

```saw
func bump(x: &var Int) { x += 1 }
func read_it(x: &Int) -> Int { x }

func relay(r: &var Int) {
    bump(&var r)        // forward the `&var` onward (mutation reaches the root)
    let _ = read_it(&r) // downgrade the same `&var` to a shared `&` — OK
}
// func relay2(r: &Int) { bump(&var r) }   // error: cannot forward `&` as `&var`

extension Counter {
    func step(&var self) {
        bump(&var self.n)   // `&var self.field` projection forwarding
        // and `bump2(&var self)` forwards the WHOLE `&var self` receiver onward
    }
}
```

Forwarding composes to any depth (`f` → `g` → `h`) and works across a suspension:
a reference held in a driven coroutine frame (a frame-resident pointer, see
*References across suspensions* under Concurrency) forwards that pointer onward, so
a mutation through a twice-forwarded `&var` after a resume is visible at the root
caller. Exclusivity is enforced by **root path**: forwarding `&var r` while also
forwarding `&r` (the same referent) in one call is an exclusive-access violation,
caught statically — the forwarded borrow is rooted at the parameter's referent
path exactly like a directly-taken reference. A spawned frame may take a
reference parameter at its root, on the terms *A task may borrow from the frame
that spawned it* sets out under Concurrency: the argument borrows its root for
the task's life, so a forwarded reference never outlives the storage it names.

**Method Self:**
Methods use reference syntax for self:
```saw
extension Point {
    func magnitude(&self) -> Float { ... }      // Shared reference
    func translate(&var self, dx: Float) { ... } // Exclusive reference
}
```

**The Law of Exclusivity (many readers XOR one writer):**
In a single call, an access path passed *exclusively* — a `&var` argument, or
the receiver of a `&var self` method — must be **disjoint** from every other
by-reference path in that call. Shared `&` paths may overlap each other
freely: with no writer in the call, the shared storage does not change for the
callee's duration, so the overlap is unobservable. A `move` argument may not
alias any reference argument in the same call.

```saw
func swap(a: &var Int, b: &var Int) { ... }

var x = 0
var y = 0
swap(&var x, &var x)  // error: `x` is passed as `&var` while also aliased
swap(&var x, &var y)  // ok: distinct roots

var p = Point(x: 1, y: 2)
f(&var p, &p.x)       // error: `p` overlaps its field `p.x`
f(&var p.x, &p.y)     // ok: disjoint fields (the rule is path-disjointness,
                      //     not one reference per variable)
g(&x, &x)             // ok when both parameters are shared `&` (two readers)
```

This check is **fully static** and needs no lifetimes or runtime flags.
References cannot escape in Saw: they are only parameters, never returned or
stored in fields, and a closure captures by value except where the capture is
itself a borrow of the enclosing frame — an explicit `[&x]`/`[&var x]`, a
reference parameter, or `self` — all three of which are confined to non-escaping
closures. Every live
reference therefore has a statically known extent, and two of them can alias
only within it. Forwarding is covered by applying the same rule at *every* call
site: inside a callee its `var` parameters are distinct storage, and the only
way they could alias is if the caller aliased them — which the caller's own
call-site check rejects.

Access paths compared for disjointness are `x`, `x.f`, `x.0`, and `x[i]`:
same root with differing fields, tuple indices, or differing *constant* array
indices are disjoint; different roots are always disjoint. A non-constant
(dynamic) array index is treated conservatively — `swap(&var a[i], &a[j])` is
rejected even when `i != j` at runtime (the checked `Vector.swap(i, j)` method
is the intended escape hatch; landed in design 40).

The rule holds however the callee is reached. A method call through an `&any
Trait` existential or through an opaque `&T` under a trait bound is checked at
the call site exactly as a call on the concrete type is: erasure and genericity
change the dispatch, not the aliasing. A generic body is checked once, before
any instantiation, so `s.pair(&var p, &var p)` under `<T: Pairer>` is refused
where it is written rather than at some later instantiation.

**Nested calls.** An argument's borrow extends over the whole call *expression*,
nested calls included. A `&` or `&var` written inside a call that sits in an
argument list joins the outer call's access set and meets the same
path-disjointness test as the arguments written beside it.

```saw
var p = Point(x: 1, y: 2)
sink(&var p.x, reset(&var p))
// error: exclusive access violation: `p` is borrowed by a nested call in this
//        argument list while `p.x` is also accessed by reference in the same
//        call — both reach `p`

add(&var x, bump(&var y))         // ok: distinct roots
scale(&var p.y, bump(&var p.x))   // ok: disjoint fields, as everywhere else
```

The receiver is an ordinary member of that set, so `p.total(reset(&var p))` is
refused as well. A `&self` receiver arrives by value, and whether its copy is
taken before or after `reset` writes is argument evaluation order. Two nested
calls reaching one root are refused on the same terms, with neither reference
written at the outer level:

```saw
combine(bump(&var n), scale(&var n))   // error: both reach `n`
```

The fix is a hoisted binding, which puts the two borrows in separate statements:

```saw
let extra = reset(&var p)
sink(&var p.x, extra)
```

**Assignment.** An assignment writes its target, and its right-hand side is
evaluated first, so the RHS may not borrow a path overlapping the written root:
everything the callee wrote through that borrow would be overwritten by the
assignment that follows.

```saw
var p = Point(x: 1, y: 2)
p.x = bump(&var p)      // error: `p` is written by this assignment while also
                        //        being accessed in the right-hand side
p.x = shift(&var p.y)   // ok: disjoint paths
acc = combine(move acc, e)   // ok: `move` hands ownership over and the
                             //     assignment revives the binding
```

**Extents longer than one call.** Two constructs hold a reference past the call
that created it, and each is folded into the same disjointness check rather than
getting a checker of its own — only the *window* over which paths are compared
changes.

- A **place window** (`borrows` / `lend`, below) borrows its root for the extent
  of the expression that opened it, which is the whole enclosing call.
- A **task capture** borrows its root for the life of the spawned task: `[&var
  x]` exclusively, `[&x]` shared, released at the task handle's `join()` or at
  the group's death. The concurrency chapter states the release rules; the point
  here is that a spawn does not create a reference the law cannot see.

```saw
let h = group.spawn(run({ [&var n] in n = n + 1  n }))
let seen = n
// error: exclusive access violation: `n` cannot be read here — the task spawned
//        at line 1 holds `&var n` until `h.join()` releases it
```

> **Invariant (for future features):** the fully-static guarantee rests on every
> live reference having a statically known extent. A call argument's extent is
> the call expression, a place window's is the enclosing expression, a task capture's is the
> handle's join or its group's death. Returned/stored references or
> globally-reachable mutable variables would have none, so they must either be
> given one or be kept out; otherwise this law weakens from *sound* to
> *advisory*.

### Places (`borrows` and `lend`)

**Status: implemented.** A **place** is storage that already exists: a local, a
field, a tuple component, an array element, an optional's payload. Places are
not new — `v.x`, `t.0` and `o!` have always been places. What is new is that a
*method* can hand one out.

A `borrows` method yields a place of `T` rather than a value of `T`:

```saw
struct Grid { cells: [Cell; 9] }

extension Grid {
    public func [](&self, i: Int) borrows -> Cell {
        if i < 0 || i >= 9 {
            panic("Grid.[]: index out of range")
        }
        lend self.cells[i]
    }
}

var g = Grid(cells: [...])
print(g[4].weight)     // reads the element where it sits
g[4].weight += 1       // writes it where it sits
```

`borrows` rides the post-parameter effect slot beside `unsafe` and `sync`, in
the order `unsafe sync borrows`, and the same slot exists on function types
(`(Int) borrows -> Cell`). `[]` is a declarable method name, so a `borrows`
method named `[]` is the subscript. Any named method may be `borrows` too
(`func first() borrows -> T`).

#### `lend` suspends the accessor; it does not return

`lend <place>` marks the borrow window. It is the one construct in Saw whose
control flow is easiest to read as a pause rather than a return. The accessor
runs to its `lend` and **stops there with its frame alive**. The caller's window
code — whatever the use site does with the place — runs *inside* that pause. When
the window closes the accessor **resumes** and runs whatever follows the `lend`,
then finishes.

So a `borrows` body has three parts and no `return` of a value anywhere:

```saw
extension Ledger {
    public func entry(&var self, i: Int) borrows -> Entry {
        if i < 0 || i >= self.entries.len() {     // prologue: runs at entry
            panic("Ledger.entry: index out of range")
        }
        lend self.entries[i]                      // the window opens here
        self.touched = self.touched + 1           // epilogue: runs at window close
    }
}
```

`-> T` names the type of the **place** the method lends, never the type of a
returned value. Writing `return <value>` in a `borrows` body is a compile error
saying so. Every path must `lend` exactly once, or diverge (a `panic` before the
`lend` is the bounds-check shape) — the coverage rule, checked the way return
coverage is. A `lend` inside a loop is rejected: two windows would need their
prologues and epilogues interleaved. Lend once, after the loop has chosen the
place.

The lowering is a scoped-borrow callback, which is what a place window already
was before it had syntax: the accessor becomes an ordinary method taking a
window closure, the use site becomes a call passing one. No coroutine machinery,
no allocation, one direct call for the common case.

#### The lent place is rooted in the receiver

An accessor lends storage its **receiver** already owns. `lend` on the
accessor's own local or parameter is a compile error:

```saw
extension Counter {
    func slot(&self) borrows -> Int {
        var tmp = self.n + 1
        lend tmp          // error: `lend tmp` is not rooted in the receiver
    }
}
```

Reads through such a window were sound — the frame is alive for the window's
whole extent — which is why the hole was quiet. Writes had nowhere to land:
`c.slot() = 99` compiled, wrote into `tmp`, and the value died when the accessor
resumed. The rule is the one the spec already applied to a `match` arm (an arm
may not lend the payload of a value the body just built), stated for a plain
`lend`.

A parameter is refused on the same terms, `&var` included, even though its
referent outlives the window: lending what a caller handed you is a larger
promise than lending your own storage, and there is no shape yet that needs it.
Widening the rule later stays compatible.

Two things count as the receiver's own storage without being written `self.…`. A
`match` arm's payload binding is one, when the scrutinee is receiver-rooted (see
[Conditional lends](#conditional-lends-borrows--t)). An INDIRECTION out of the
receiver is the other: `Vector.[]` lends `buf[index]` for a `buf` read out of
`self.buffer`, and `Data.[]` lends through a pointer cast from
`self.byte_ptr()`. That storage is the receiver's own heap and no more dies with
the accessor than a field does. Lending such a binding whole (`lend buf`) is
still refused — that would hand out the frame's copy of the pointer.

#### The window's flavor comes from the use site

One `borrows` declaration serves reads and writes. The **use site** decides:
reading through the place opens a shared window, writing through it (or handing
it over as `&var`) opens an exclusive one. The declaration never says which.

```saw
print(g[4].weight)      // shared window on `g`
g[4].weight += 1        // exclusive window on `g`
bump(&var g[4])         // exclusive window, spanning the call
```

#### Writing through a place

Four spellings reach the write side, and they all mean the same thing — replace
or mutate storage the container already holds, where it sits:

```saw
v[i] = fresh              // subscript, unconditional lend
m[k]! = fresh             // forced conditional lend; panics if `k` is absent
c.slot(i) = fresh         // named accessor
m[k]?.field = v           // chain assignment; an absent key writes nothing
```

The `!` form is the panic spelling of the `?` form, exactly as it is for a read.
Each opens an **exclusive** window, so each needs a mutable root and reports an
immutable one by name. A method call is an assignment target only when it lends
a place; anything else is refused naming the method.

A shared window lends the element **read-only**: inside it the place is a `&T`,
so a write is a compile error there and not merely a use site the classifier was
supposed to have called exclusive. Nested windows take the inner one's flavor —
`b[0][1].count += 1` opens two exclusive windows, since the write reaches the
outer place's storage — and an immutable root is refused for either of them,
named as the root rather than as the window.

> **`borrows` changes what `&self` means.** A `borrows` accessor's receiver is
> borrowed with the **window's** flavor, decided at each use site — this is the
> one place in Saw where a `&self` spelling does not mean shared-only. A read
> through `g[4]` borrows `g` shared; a write through `g[4]` borrows `g`
> exclusively, out of that same `&self` declaration. The polymorphism reaches
> the `lend` and nothing else: the rest of the body is ordinary `&self` code, so
> a field write or a `&var self.<field>` written in the prologue or epilogue is
> the same error it is in any other `&self` method. Declaring the accessor
> `&var self` instead is legal and *more* restrictive: every use site then
> borrows the receiver exclusively, including a read.
>
> `--emit-docs` reports such a receiver as `"self": "window"` rather than
> `"borrows"`, for the same reason.

#### `#lend_var`: a body that knows its flavor

One body serving both flavors is the right default. Copy-on-write is where it
runs out. A CoW container has to separate shared storage *before* lending a
place that might be written, and must not separate for one that will only be
read — so with no way to tell those apart, `Data.[]` once declared `&var self`
and gated on every use, which made a pure read demand exclusivity and a `let`
binding unusable.

`#lend_var` is a compile-time constant, legal only inside a `borrows` body, that
names the specialization being compiled: `false` for the shared window, `true`
for the exclusive one.

```saw
extension Data {
    public func [](&self, index: Int) unsafe borrows -> UInt8 {
        if index < 0 || index >= self.length {
            panic("Data.[]: index out of range: {} (len {})", index, self.length)
        }
        if #lend_var {
            if not self._make_ready(self.length) {   // the copy-on-write gate
                panic("Data.[]: allocation failed")
            }
        }
        let bytes = self.byte_ptr() as UnsafePointer<UInt8>
        lend bytes[index]
    }
}
```

**That `Data.[]: allocation failed` is a documented boundary, and it stays a
panic.** A subscript is an expression a `try` could in principle attach to, but
the accessor rule governs here: a direct indexed accessor on a safe type
signals out-of-range by panicking, and the copy-on-write separation is part of
the same unconditional lend. Splitting one of its two failures out as a value
and leaving the other a panic would make `d[i]` mean two different things by
which failure it met. A caller that must not meet it preflights instead:
`detached()` performs the separation and returns `Result<Data, AllocError>`,
so the allocation is attempted where a failure has somewhere to go, and the
writes that follow find the buffer already unique.

An accessor that names the constant compiles as **two specializations**. The
authored declaration keeps its `&self` receiver and folds the constant false;
what the constant gated is *removed from the body*, not skipped, so that copy is
ordinary non-mutating `&self` code and an immutable root may call it. The
compiler emits a `&var self` sibling that folds the constant true and keeps the
gate, and sends every exclusive use site there. Nothing changes at the call —
the use site already carries the flavor:

```saw
let frozen = load()
print(frozen[0])       // shared: no gate, no separation, no `var` required
var buf = frozen
buf[0] = 90            // exclusive: separates first, so `frozen` keeps its bytes
```

The constant **prunes** where it is the condition of an `if` statement, which is
the shape a gate takes; the branch not taken leaves no trace in the tree, so it
is never checked. `not`, `&&` and `||` fold with it, so `if #lend_var &&
self.shared` keeps a runtime condition in the specialization that has one.
Anywhere else `#lend_var` is an ordinary compile-time `Bool`.

Three rules bound it:

- Outside a `borrows` body it is a compile error. Every legal occurrence is
  folded away before type checking, so anything the checker sees is misplaced.
- In a `&var self`-declared accessor it is a compile error naming the receiver
  as the fix. That declaration is already the stricter one — every use site of
  it is exclusive — so the constant would always be true while reading like a
  decision.
- An accessor that never names it compiles once, exactly as before. The
  accessors that do not need this pay nothing for it.

Two consequences worth knowing. The gate reads the true refcount: a `borrows`
receiver travels by pointer, so the accessor sees the same `Arc` the caller
holds rather than a retained copy, and `strong_count()` answers about the
caller's sharing. And an accessor that *forwards* another accessor's place
(`lend other[i]`) reaches the inner accessor exclusively whichever
specialization is running, because `lend X` hands `X` over as `&var X`. That is
sound — separating storage is never wrong — but a shared read of a nested
copy-on-write buffer will copy.

#### Window extent and nesting

The **window's extent** is the smallest expression that turns the place back
into a value: the chain suffix that follows it, the whole call when the place is
a reference argument, the whole statement when it is being written to. Nothing
outside that extent runs with the window open.

Windows **nest**, which is what orders them. `b[0][1].count += 1` is two
windows, the outer opening first and closing last. Two place arguments in one
call run their prologues in argument order and their epilogues LIFO, because
that is what nesting means.

**Everything inside the extent runs against the enclosing scope's own
bindings.** The code in a window is code you wrote where you wrote it, so a
local it names is *borrowed*, never copied — which is what lets a move-only
value be handed to something reached through a place:

```saw
var enc = CborEncoder()             // NoCopy, built right here
var i = 0
while i < entries.len() {
    try entries[i].serialize(to: &var enc)     // borrowed, not copied
    i = i + 1
}
```

The one name that is not borrowed is the **root of the place itself**. A window
already holds that root — exclusively, if the use site writes — so reaching it a
second time from inside the extent is the aliasing the Law of Exclusivity
refuses. Bind what you need from the root before the window opens:

```saw
let n = v.len()
v[0].bump(by: n)        // `v[0].bump(by: v.len())` is refused
```

An **assignment** is the one position that needs no such line. Its right-hand
side is defined to run before its target, so a right-hand side that names the
target's own root is lifted out of the window and the two accesses become two
statements:

```saw
v[0].n = v.len()        // compiles: the read finishes, then the window opens
v[0].n = v.pop()!.n     // and so does this, for the same reason
```

That order is not available anywhere else. An argument and a body read both run
after the accessor's prologue, so lifting one would change the order the program
runs in; the diagnostic there names the asymmetry and gives the `let`.

#### Conditional lends (`borrows -> T?`)

`borrows -> T?` is the optional place. Each path through the body either `lend`s
real storage (the present path) or plainly returns `None` (the absent path — no
storage, an immediate value) or diverges:

```saw
extension Grid {
    public func at(&self, i: Int) borrows -> Cell? {
        if i < 0 || i >= 9 {
            return None
        }
        lend self.cells[i]
    }
}
```

`lend` may not appear in a loop, so a body that has to *search* for the place
splits in two: an ordinary function finds the index, and the accessor lends it.
`libs/toml` is the worked example (`_section_index` beside `section`).

**The absent path opens no window and runs no epilogue.** There is nothing to
lend, so there is nothing to close; the caller decides what absence means. A
value read means `None`; a chain that reached *through* the place with `!` has
already promised the place is there, so absence is that force-unwrap's panic.

```saw
print(g.at(4)!.weight)              // panics if absent
g.at(4)!.weight += 1                // exclusive window on the present path
if let c = g.at(99) { ... } else { ... }   // absent: no window, no epilogue
```

#### Value reads

A place stops being storage at a **value read** — binding it, passing it by
value, returning it, using it as an operand. That is governed by the element's
entry in [the Copy trait family](#the-copy-trait-family) table, exactly as an
optional payload is ([Payload reads](#payload-reads-the-place-rule)):

| Use of the place | trivial | Copy | ExplicitCopy | NoCopy |
|---|---|---|---|---|
| Borrow (`v[i].m()`, `&v[i]`, `v[i].field`) | ok | ok | ok | ok |
| Value read (`let e = v[i]`, by-value argument, return) | bitwise | retain | error | error |

A `Copy` element is retained at the read, so the container keeps its own
reference and both are destroyed once. An `ExplicitCopy` or `NoCopy` element is
never duplicated implicitly, and the error names the ways out — `with_ref` to
borrow it in place, `swap_out` to move it out.

**A position that keeps nothing is a borrow, not a read.** Some expressions hand
a value to a `&self` callee and are done with it, and a place in one of those is
borrowed where it sits — the table above never comes into it, so a move-only
element behaves exactly as an `Int` one does. Two such positions:

*Rendering.* `print("{v[0]}")`, `print(v[0])` and `print("{}", v[0])` hand the
element to `format(&self, into:)`. That covers an interpolation operand wherever
an interpolation is written, a single-argument `print` of a `Printable`, and the
format arguments of `print`, `panic` and `assert`.

*Comparison.* `v[0] == w[0]` and the ordering operators lower to
`equals`/`compare`, whose `other` is a `&Self`, so neither side is read out.

The window spans the whole expression that asks for the borrow, so an operand
beside the place is inside that window too — which is why an `assert` condition
that names the place's own root wants a binding of its own ahead of the call.

**A pattern that binds nothing is a presence test, not a read.** `if let _ =
g.at(i)`, `guard let _ = g.at(i)`, and a `match` arm like `case Empty` or
`case Occupied(_)` take no payload out: they look at the discriminant through
the borrow. So they are legal for every tier, move-only elements included, and
they emit no copy and no drop. A `match` on a place matches it where it sits,
and an arm that DOES bind binds the payload in place, so the table above is
consulted for that one binding rather than for the whole element.

```saw
if let _ = doc.section("package") { ... }     // presence: no read at all
match slots[i] {                              // discriminant through the borrow
    case Empty -> 0,
    case Occupied(_, _) -> 1
}
```

Presence is tier-independent wherever it is asked, and the scrutinee's shape
does not change that. A plain optional, a conditional lend (`v.get(i)`), and an
unconditional lend whose element is ITSELF optional (`Slot<T>.value()` at
`T = Res?`) all answer the same question the same way, at every tier. The third
of those is the one worth naming, because it reads like a value read and is not:
the lend is unconditional, so the optional the use site sees is the element
rather than the lend's own presence, and asking whether it holds anything is
still a look at the tag. It desugars to `is_some()`, which is the same question
written out.

```saw
struct Session { id: Int }
extension Session: NoCopy {}

var slot = Slot<Session?>.of(value: Session(id: 1))
if let _ = slot.value() { ... }        // same question as slot.value().is_some()
```

Two shapes keep the ordinary value-read path, because a window is a closure: an
arm body that leaves the enclosing function (`return`, `break`, `continue`), and
an arm that `move`s one of its own bindings out, which is destructuring rather
than reading.

**An element type that mentions a type parameter demands a bound.** `Slot<K>`
has no copy tier of its own: whether it duplicates is a property of the
instantiation, so a value read of one inside a generic body is legal exactly
when the bounds prove every instantiation can be copied — a `Copy`-family bound
on each parameter it mentions. The question is asked once, in the generic body,
never at an instantiation, so a body that compiles compiles for every caller.
The refusal names both ways forward:

```saw
struct Holder<K> { slots: Vector<Slot<K>> }

extension Holder<K> {
    func tag_at(&self, i: Int) -> Int {
        let s = self.slots[i]      // error: `self.slots[…]` lends a place of
        ...                        // type `Slot<K>`, whose copy policy depends
    }                              // on the type parameter `K`
}
```

Bound `K: Copy` and the read is legal; leave it unbounded and reach the place
through a borrow instead. Where the read IS legal, the copy is emitted at the
instantiation — the same phase that emits the matching drop — so the concrete
tier decides whether it is a bitwise copy, a retain, or the type's own
`copy()`.

#### Lending an enum payload

A `match` on a place matches it where it sits, so an arm that binds binds the
payload in place (above). That binding can also be **lent**, which is how a
container whose storage is a slot enum publishes an accessor at all:

```saw
enum Slot { case Empty, case Filled(key: Int, res: Res) }

extension Table {
    public func at(&self, i: Int) borrows -> Res? {
        if i < 0 || i >= self.slots.len() {
            return None
        }
        match self.slots[i] {
            case Filled(_, r) -> { lend r },
            case Empty -> { return None }
        }
    }
}
```

Tag stability comes free. The window borrows the scrutinee's root for its whole
extent, so the Law of Exclusivity freezes the enum, discriminant included: no
code inside the window can overwrite the slot with a different variant while the
payload is out.

The scrutinee must be storage reached through the receiver — a field, an
element, or another place hanging off `self`. Matching a value the body just
built would lend a temporary that dies with the accessor, so it is a clean error
rather than a write that goes nowhere:

```saw
let built = self.fresh()
match built {
    case Filled(_, r) -> { lend r },  // error: `lend r` names the payload of a
    case Empty -> { return None }     // `match` on something other than the
}                                     // receiver's own storage
```

#### Exclusivity, invalidation, and the fences

A place borrow charges its **root**: `&v[i]` borrows all of `v`, shared for `&`
and exclusive for `&var`. Index values are ignored, so any `v[i]` borrows the
whole of `v` — swapping two elements through two windows is an exclusivity
error, and `Vector.swap(i, j)` stays the method for that. No new rules are
involved: a place use is an access path like any other, so passing `&var v`
beside `&v[i]` in one call, or capturing `[&var v]` alongside, are the existing
Law of Exclusivity shapes.

That is also what makes a window invalidation-proof. While a window is open its
root is borrowed, so `v.push(x)` inside the window is a compile error — the same
guarantee `with_ref` gets from its closure scope, obtained here from the law.

**Two by-reference accesses to one root in one call, at least one of them a
place, are an exclusivity error on every copy tier.** Two windows
(`setboth(&var p.at(0), &var p.at(1))`), or a window beside a `&var` of its own
root, name overlapping storage, and the diagnostic says so:

```saw
setboth(&var p.at(0), &var p.at(1))
// error: exclusive access violation: the place `p.at(…)` borrows `p` for the
//        whole window, and `p` is accessed by reference a second time in the
//        same call
```

The window's extent is the whole call, so a reference created by a NESTED call
in the same argument list is inside it too — `sink(&var p.at(0), reset(&var p))`
is the same violation. Until design 188 none of this was checked: what refused
the shape on an `ExplicitCopy` or `NoCopy` receiver was the COPY POLICY, because
the compiler copied the receiver to open the second access and reported that
copy. A receiver that copies for free had nothing to trip on, so the program
compiled and both writes went into copies. Reading a `Data` back after a
two-window swap gave `d0=1 d1=1` for a buffer holding `1, 2`.

Everything outside that trigger is unaffected: a single window, two windows in
separate statements, a window beside a shared read of a disjoint path, nested
windows (`b[0][1].n += 1` — two windows on two roots), and plain fixed-array
indexing (`a[0]` is not an accessor, so constant distinct indices stay disjoint).

Three fences hold in this version:

- A `borrows` body is `sync`. A place window may not span a suspension: the root
  stays borrowed for the whole window, so yielding with one open would let
  another task invalidate it. `with_ref` / `with_var_ref` remain the explicit
  long-window and multi-statement spellings.
- There are no `borrows` function *values* or existentials. A `borrows` method
  cannot be bound to a name or erased behind `any Trait`.
- Traits cannot require a `borrows` method. A generic `T: IndexPlace` bound is
  not part of this version.

#### Standard library accessors

`Vector` and `Data` publish their element access as places:

```saw
var v: Vector<Entry> = [...]
print(v[0].count)                // shared window
v[0].count += 1                  // exclusive window
v[0] = Entry(count: 0)           // whole-element write; the old one deinits once
f(&var v[0])                     // the window spans the call

var d = try! Data(capacity: 1)
try! d.push(9u8)
d[0] = 0u8                       // panicking place, same rules
```

`Data.[]` differs from `Vector.[]` in one way, and it is inside the body rather
than in the declaration. Copy-on-write has to separate shared storage before
lending a place a caller might write to, and must not separate for a read, so
the accessor is declared `&self` and puts the separation behind
[`#lend_var`](#lend_var-a-body-that-knows-its-flavor): the gate sits in the
exclusive specialization and is absent from the shared one. A read therefore
works on a `let` root, a `&Data` parameter, or a slice several `Data`s share; a
write opens an exclusive window, so it needs a `var` root, and the first write
on shared bytes copies (see [Data](#data)). `d.get(i)` is the `None`-returning
twin, nothing more.

Both panic out of range, on design 130's accessor-rule terms. `Vector.get(i)` is
the `None`-returning twin of `v[i]` and the same lowering — a conditional lend:

```saw
if let e = v.get(i) { ... }      // value read, so the copy tier decides
if let _ = v.get(i) { ... }      // presence test: legal for every tier
v.get(i)!.count += 1             // exclusive window; the `!` panics if absent
```

`Map` publishes its values as a subscript, `func [](key: K) borrows -> V?` — a
conditional lend, since a key may not be there:

```saw
var counts = Map<String, Entry>()
let _ = counts.insert("a", Entry(n: 0))

counts["a"]!.n += 1                       // exclusive window; writes the stored value
print(counts["a"]!.n)                     // shared window
print((counts["b"] ?? Entry(n: 0)).n)     // absent: no window opens
if let _ = counts["b"] { ... }            // presence test: no copy, any tier
```

A map's value lives inside an enum payload (`MapSlot.Occupied(key:value:)`), and
the accessor reaches it by matching the slot where it sits and lending the arm's
binding. So the window addresses the value in the table: a `Vector` value grows
through `m["k"]!.push(x)` rather than being read out, appended to, and written
back.

`Set` has no equivalent. A set's elements are the underlying map's keys, and the
table's own correctness depends on them — a window's flavor comes from the use
site, so any element accessor would also permit a write that changes an
element's hash and loses it in its own table.

A place is one expression, so a caller that reads several values out of one
move-only element holds an INDEX rather than a binding. `libs/toml` is the
worked example: `TomlDoc.section(name) borrows -> TomlSection?` is the named
place, and `index_of(name)` plus `section_at(i)` is the same borrow when several
reads share one lookup.

`Map` and `Set` probe through their slots the same way. `K` is `Hashable +
Equatable`, never `Copy`, so reading a whole slot out is not something the table
is entitled to do; every probe matches the slot where it sits, which also means
walking past a live entry touches no refcount.

### Shared Ownership

**Status: implemented.** `Arc<T>` (atomic reference counting) and
`Box<T, A>` (owned heap allocation) are in the stdlib. Saw is **Arc-only** —
there is no single-threaded `Rc<T>` (decided in design 16): the atomic refcount
is the one shared-ownership primitive. `Arc` is `Copy + Deinit`
(retain on copy, release on drop; the last owner runs the payload's `deinit`
exactly once), built on the same machinery as `String`.

```saw
// Atomic reference counting (thread-safe shared ownership). The control block
// is an allocation, so the constructor reports; `try!` says this caller would
// rather die than handle a refusal.
let shared = try! Arc<Payload>(value: Payload(id: 7))
let shared2 = shared          // copy() called, strong count increases
print(shared2.strong_count()) // 2

// Box<T, A>: owned heap allocation without sharing (NoCopy — move to transfer).
// `make` is a static because the allocator type argument is named at the call
// site, not because construction is special.
let boxed = try! Box<Int>.make(42)
print(boxed.value())          // 42
```

### Synchronized Access

**Status: `Mutex<T>` implemented (hosted); `RwLock` planned.** `Mutex<T>` is
ONE INLINE WORD beside its payload: `os_unfair_lock` on macOS, a futex on Linux,
and zero means unlocked on both. It is `NoCopy`, allocates nothing and frees
nothing. Rather than a returned lock guard, `lock` takes a non-escaping closure
and runs it with `&var` access to the guarded payload under the lock — the lock
is always released on the way out. `get()` snapshots the payload
(`T: ExplicitCopy`).

```saw
// lock<R>(body: (&var T) sync -> R) -> R — the body's own result comes back out
let m = Mutex<Int>(value: 0)

let doubled = m.lock({ c in
    c = c + 1
    c * 2
})                  // lock released automatically

print(doubled)      // 2
print(m.get())      // 1
```

The result type is the closure's, not a fixed `Bool`: `lock` is generic in `R`,
the same shape [`SpinLock.lock`](#spinlockt) has. A body that computes nothing
gives a `Void` result. Naming the parameter `&var c` instead of `c` is also
accepted, and means the same thing — the parameter type says `&var T` either
way.

**A `static` holds one with no initializer.** Zero is unlocked, so the whole
value is zerofill and an idle mutex costs no image bytes:

```saw
import std.mutex.{Mutex}

static REGISTRY: Mutex<Int>

func record(n: Int) {
    REGISTRY.lock({ &var total in total = total + n })
}
```

`Mutex(value:)` allocates nothing and cannot fail, so it has no `try_` twin —
the fallible tier exists exactly where an allocation does
(see [Allocation failure](#allocation-failure)), and `get` is not optional.

**Movability** comes from the Law of Exclusivity rather than from an
address-stability contract: a thread inside `lock()` holds a live `&self`
borrow for the whole critical section, and a move needs exclusive access, so a
move cannot be spelled while any thread is inside the lock. Moving an IDLE
mutex relocates one word and a payload, and nothing was pointing at either —
which is why `Mutex` is ordinary `NoCopy` and deliberately not
[`NoMove`](#nomove).

`lock` blocks the calling THREAD on a contended lock, and is not reentrant:
taking a mutex this thread already holds is a program bug (macOS traps, Linux
deadlocks). Prefer a `Channel` where a task would otherwise wait.

`RwLock` (multiple readers XOR single writer) is planned; it is not yet in the
stdlib.

### Resource Management Traits

**Status: implemented.** Saw provides a hierarchy of traits for types that need
custom copy behavior or cleanup when going out of scope. This enables reference
counting (like `String` and `Arc<T>`), owning types that duplicate their storage
(like `Vector`), scope-bound cleanup of a raw resource (like file handles), and
move-only types. `NoCopy`, `ExplicitCopy` and a DECLARED `Copy` are written as
an `extension` (`extension T: Trait`); there is no struct-header conformance
syntax, and a derived `Copy` is written nowhere. The family is `Copy` (the
silent tier),
`NoCopy` (the move-only opt-out) and `ExplicitCopy` (the duplicable family),
over `Deinit`; see [The Copy Trait Family](#the-copy-trait-family) above for
the transfer-site rules.

#### The Deinit trait

```saw
// Called automatically when a value goes out of scope
trait Deinit {
    func deinit(&var self)
}
```

The compiler inserts `deinit()` calls at every scope exit: falling off the end
of a block, `return`, `break`, `continue`, and error propagation. Each scope
releases its own bindings in reverse declaration order, and a jump out of
several scopes releases them innermost first.

An optional binding is scoped to the branch that introduced it. An `if let`,
`if var`, `while let` or `while var` binding — a tuple pattern's leaves
included — is released at the end of the then-branch, on that same list of
edges, so a `return` out of the branch releases it exactly as falling off the
end of the branch does. A `guard let` binding is the deliberate exception: it
outlives the guard by design, so it belongs to the enclosing scope and is
released with it.

You rarely write the body. Any struct or enum that owns something gets a
memberwise `deinit` synthesized from its fields, so a hand-written one is for
raw resources only; see [Synthesized destruction](#synthesized-destruction).

`Deinit` is never conformed to directly. A hand-written body goes inside the
type's copy policy — `NoCopy`, `ExplicitCopy`, or `Copy` — see
[The Copy trait family](#the-copy-trait-family). As a generic bound
(`T: Deinit`) it works like any other trait.

**Important:** Manual `deinit()` calls are not allowed. Calling `obj.deinit()` is a compile-time error to prevent double-free and use-after-free bugs. For early cleanup, use a nested scope or `move` the value to a consuming function.

#### The Copy trait

```saw
trait Copy {
    func copy(&self) -> Self
}
```

Most `Copy` types never write this conformance: the tier is derived from the
members. Declaring it with a `copy()` body installs the retain hook, and the
compiler calls that body instead of a memcpy at every transfer site. The hook
is how reference counting is written in ordinary Saw, and its cost lands at
sites the source does not name, so it must be cheap:

```saw
unsafe static var STRONG: Int = 0

struct Ticket { id: Int }

extension Ticket {
    static func issue(id: Int) unsafe -> Ticket {
        STRONG = STRONG + 1
        Ticket(id: id)
    }
}

extension Ticket: Copy {
    func copy(&self) unsafe -> Ticket {     // retain: the hook
        STRONG = STRONG + 1
        Ticket(id: self.id)
    }
    func deinit(&var self) unsafe {         // release: its pair
        STRONG = STRONG - 1
    }
}

func hold(t: &Ticket) unsafe {
    let b = t              // the compiler calls copy(): a retain
    print(STRONG)          // 2
}                          // b's deinit runs here: the release

func main() unsafe {
    let a = Ticket.issue(id: 42)
    print(STRONG)          // 1
    hold(&a)
    print(STRONG)          // 1 again
}
```

The `deinit` sits inside the `Copy` conformance rather than beside it, because
`Deinit` is the policy hierarchy's base and is never declared on its own (see
[The Deinit trait](#the-deinit-trait)). `std.arc` is this shape with the count
in the heap block and the increments atomic; `String`, `Data` and an escaping
closure's environment are the same hook again.

#### The ExplicitCopy trait (owning types that duplicate)

```saw
// ExplicitCopy also requires Deinit
trait ExplicitCopy: Deinit {
    func copy(&self) -> Self
}
```

A type declaring `ExplicitCopy` and nothing else is **never** copied
implicitly — the compiler demands `move` at a transfer out of an existing
binding, and any duplication is a visible `v.copy()`. This is the policy for expensive,
resource-owning types such as `Vector` — today the only conforming std type
(`Map`/`Set` remain `NoCopy` pending their `copy()`). Enforcement reuses the
`NoCopy` value-transfer checkpoint, with its own diagnostic:

```saw
extension Buf: ExplicitCopy {
    func copy(&self) -> Buf { ... }    // duplicate the buffer
    func deinit(&var self) { ... }     // free buffer
}

var a = makeBuf()
var b = a          // Error: cannot copy value of type `Buf` which implements
                   //        ExplicitCopy — use .copy() or `move`
var c = a.copy()   // Ok: explicit, independent duplicate
var d = move a     // Ok: ownership transferred, a no longer valid
```

#### The NoCopy trait (move-only types)

```saw
// Trait refinement: NoCopy requires Deinit
trait NoCopy: Deinit {
    // Marker trait - no methods
}
```

A type conforming to `NoCopy` cannot be copied—only moved. The compiler errors on assignment; use `move` to transfer ownership:

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

#### The `NoMove` trait (pinned types)

**Status: implemented (design 188).** Duplication and relocation are separate
axes. The four tiers above answer "may this value be duplicated, and at what
cost"; `NoMove` answers a different question — "may this value live anywhere
other than where it was built" — and a type states both:

```saw
extension TaskGroup: NoCopy {}
extension TaskGroup: NoMove {}
```

`NoMove` does not imply `NoCopy`; it **requires** it. Declaring `NoMove` on a
type whose copy tier is anything but a declared `NoCopy` is an error, so neither
property is ever inferred from the other. That strictness is also where the
model grows: `NoMove` beside `ExplicitCopy` (a pinned type with a hand-written
`copy()` that re-registers the duplicate) opens by relaxing exactly that check.

A `NoMove` value moves **once**, from its constructor into its binding, and
never again:

```saw
func make() -> TaskGroup {
    var group = TaskGroup()
    let _ = group.spawn(work(21))
    move group
    // error: cannot `move` `group`: `TaskGroup` is `NoMove`, so it lives where
    //        its constructor built it and may not be relocated.
}
```

`move x` is refused, and with it every other transfer position — the `NoCopy`
rules funnel each one through `move`. So is `Optional.take` of a `NoMove`
payload, which relocates the payload out of the optional. What stays legal is
whole-referent replacement through a `&var`:

```saw
func reset(g: &var TaskGroup) {
    g = TaskGroup()        // legal: destroy, then construct, at one address
}
```

That is not a relocation. The old value's `deinit` runs first — for a group,
that is the structured join — and the new value is built where the old one was.

Containment is a **declared cascade**, in the style of the copy tiers: a struct
or enum with a `NoMove` member does not compile until it declares `NoMove` (and
`NoCopy`) itself.

```saw
struct Server { group: TaskGroup, port: Int }
extension Server: NoCopy {}
// error: `Server` contains NoMove member `group` of type `TaskGroup` but does
//        not declare `NoMove`
```

Nothing is inherited silently, which means a field's movability can never change
a type's behind the author's back. For a type that wants a movable HANDLE over
pinned state, the answer is composition rather than a language mechanism: a
`Box` moves freely and what it points at stays put.

`NoMove` is not a generic bound. A bound licenses a generic body to do
something with every instantiation, and this one licenses nothing — `T: NoMove`
is a clean error pointing at the conformance position. There is no `Pin` type,
no projection machinery, and no blessing for self-referential values.

#### Summary of Type Behaviors

| Kind | Transfer (`let b = a`) | `.copy()` | Cleanup |
|------|------------------------|-----------|---------|
| trivial / POD (auto-`Copy`) | implicit bitwise copy | bitwise | none |
| `Copy` | implicit `copy()` (cheap) | yes | `deinit()` |
| `ExplicitCopy` | **error** — needs `move` | yes (visible) | `deinit()` |
| `NoCopy` | **error** — needs `move` | no | `deinit()` |

The `deinit()` in the Cleanup column is synthesized from the type's fields
unless you write one. `NoMove` is orthogonal to every row: it does not change
how a value transfers, it removes the one transfer `NoCopy` still allows.

#### Containment Rules

A struct that contains a field with a copy policy must declare a copy policy of
its own. The compiler knows how to destroy such a struct — see *Synthesized
destruction* below — but it cannot know whether you want the value duplicated,
so that one decision stays with you:

```saw
struct Connection {
    socket: File       // File is NoCopy
    config: Config     // plain type
}
// error: struct `Connection` contains NoCopy field `socket` of type `File`
//        but does not implement NoCopy

// Fix: declare the policy. The body is empty; `deinit` is synthesized and
// closes `socket` at scope exit.
extension Connection: NoCopy {}
```

The containment rules are:
- **NoCopy containment**: If any field is `NoCopy`, the struct must be `NoCopy`
- **ExplicitCopy containment**: If any field is `ExplicitCopy`, the struct must declare `ExplicitCopy` (or `NoCopy`)
- **Copy containment**: If any field's type *declares* `Copy` — an `Arc<T>`, a
  user retain-hook type — and none is `NoCopy`/`ExplicitCopy`, the struct must
  declare `Copy` too. Fields the compiler retains on its own (a `String`, a
  closure, a fixed array of either) are exempt: they put the struct on the
  automatic tier, which owes no declaration
- **NoMove containment**: If any field is `NoMove`, the struct must declare
  `NoMove` (and therefore `NoCopy`)

There is no Deinit containment rule. Destruction is never something a type opts
into.

#### Synthesized destruction

Every struct and enum that owns something gets a `deinit`, written by the
compiler. Fields are dropped in reverse declaration order, matching the order
locals drop in; an enum switches on its tag and drops the active variant's
owning payload. A field that owns nothing costs nothing.

Reverse declaration order is the rule for *every* structural teardown, and a
DISCARD is one. The fields a `match` arm throws away with `_`
(`case Trip(v, _, _)`) and the components a destructuring `let` throws away
(`let (_, _) = pair`, and the same pattern under `if let` / `guard let`) are
released in reverse declaration order too, exactly as the named bindings beside
them are — so which fields a pattern happens to name never changes the order the
rest come apart in.

```saw
struct Session {
    log: Vector<String>,
    buffer: Vector<Int>
}

extension Session: NoCopy {}
// deinit drops `buffer`, then `log`. Nothing to write.
```

Write a `deinit` yourself when a raw resource needs releasing — a file
descriptor, a mapped page, an allocation the compiler does not track. Your body
runs first, then the field drops are appended:

```saw
extension Connection: NoCopy {
    func deinit(&var self) {
        log_close(self.id)
        // then: self.socket drops
    }
}
```

There is only ever one `deinit` per type. Writing one replaces the synthesized
body; it does not add a second pass.

**In struct initialization**: When initializing a struct, `copy()` is automatically called on any `Copy` fields that come from existing variables:

```saw
extension Container: Copy {
    func copy(&self) -> Container {
        Container(data: self.data)  // Compiler calls self.data.copy()
    }
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

### Auto-Wrap

Saw has no `Ok(x)` or `Err(e)` constructor to write: the wrap IS the
construction, and it fires wherever a value lands in a declared `Result` slot.
Returns are shown here; the argument positions (call arguments at every form,
struct-literal fields, enum payloads, collection-literal elements, defaulted
parameters) follow the same table and are described under *Call-site `Result`
auto-wrap*.

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

Four return targets take this wrap, and they take the identical one: a
function body's tail, a method body's tail, an explicit `return`, and a
CLOSURE body's tail.

```saw
func run(f: (Int) sync -> Result<Int32, ParseError>) -> Int32 { ... }

run({ x in 12 })                       // Ok(12), same as `{ x in return 12 }`
run({ x in ParseError(line: x) })      // Err
```

The ambiguity rejection, the erased `Box<any Error>` target and the
optional-Ok-payload wrap all reach a closure tail exactly as they reach a named
one.

A bare `None` is on that list too. At a declared `Result<T?, E>` it is
`Ok(None)`, at all four targets and in a generic body:

```saw
func poll(n: Int) -> Result<Int?, Stop> {
    if n == 0 { return None }        // an explicit return
    None                             // …and the tail that means the same thing
}
```

It can only mean the Ok side, so it is decided ahead of the ambiguity rule
rather than by it — the none-literal fits every type, and asking that question
of a `None` would reject an unambiguous program. A `None` at a `Result` whose Ok
type is NOT an optional is a compile error naming the declared Ok type, at every
one of the four targets.

### Error-type doctrine

Three tiers, and a signature says which one it is on.

**A leaf operation returns the narrowest concrete type it can fail with.** Most
std operations have exactly one failure mode and need no compound: a refused
allocation is `Result<Void, AllocError>`, and `AllocError` carries the `size` and
`align` of the request, so an out-of-memory site stays loggable with context.

**A compound domain enum carries payloads, and exists only where the sources
genuinely mix.** `ChannelError` is the worked example. A channel operation can
fail because the channel is closed, because the waiting task was cancelled, or
because the allocator refused a queue node, and those are three unrelated
sources. The generic one CARRIES the leaf rather than restating its vocabulary:

```saw
public enum ChannelError {
    case Closed,
    case Cancelled,
    case Alloc(e: AllocError)      // the leaf itself, not a copy of its fields
}
```

A domain that cannot time out has no `TimedOut` case; a domain that allocates
nothing has no `Alloc` case. Signatures stay exact. Case NAMES and payload TYPES
are shared across domains — every `Alloc` case carries an `AllocError` and is
spelled `Alloc` — but the wrapper enums are not. A `ChannelError.Sys` carrying
an OS refusal would claim that a purely in-process channel can fail because the
operating system said no, and every match on it would go two levels deep.

**`Box<any Error>` is the application aggregation tier, and std never produces
one.** The erased `Result<T, Box<any Error>>` is for a caller that does not care
which error arrived. std always names its error type, so a program that does
care can match on it, and one that does not can let the boxing happen at its own
boundary.

**There is no stdlib-wide error enum.** Its defining property is that every
signature lies: a `push -> Result<_, StdError>` claims failure modes `push`
cannot produce, and every exhaustive match over it grows arms no input can ever
reach. errno's flatness was C's lack of sum types, not a design to copy.

Crossing between tiers is written, never inferred — see
[Error routing at `try`](#error-routing-at-try).

### `try_` means non-blocking

The prefix is reserved for the non-blocking variant of an operation that could
otherwise block, and it means nothing else. The standard shape is the blocking
operation's error type with the payload optionalized:

```saw
func receive(&self) -> Result<T, ChannelError>       // parks until a message arrives
func try_receive(&self) -> Result<T?, ChannelError>  // answers at once
```

`Ok(None)` is "nothing yet". Would-block is not an error — it is the normal
answer to a poll — while `Err(Closed)` still surfaces, because a closed channel
must not look like an empty one. Where the non-blocking variant has no error
path at all, a plain `T?` says everything: `SpinLock.try_lock` answers `None`
when another thread holds the lock, and `Once.try_get` answers `None` before the
value has been set.

The two peel apart cleanly at a call site, the `try` taking the error channel
and the `while let` taking the optional:

```saw
func drain(ch: Channel<Job>) -> Result<Int, ChannelError> {
    var n = 0
    while let job = try ch.try_receive() {   // ends on empty, propagates on closed
        run(job)
        n = n + 1
    }
    return n
}
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

### Error routing at `try`

A `try` whose callee fails with a different error type than the enclosing
function declares spells the conversion, as a prefix clause:

```saw
struct AllocError { size: Int, align: Int }
struct ParseError { line: Int }

enum ConfigError {
    case Alloc(e: AllocError),
    case Parse(e: ParseError)
}

func alloc_buffer(bytes: Int) -> Result<Data, AllocError> { ... }
func parse(buf: Data) -> Result<Config, ParseError> { ... }
func read_defaults() -> Result<Defaults, ConfigError> { ... }

func build() -> Result<Config, ConfigError> {
    let buf = try(as ConfigError.Alloc) alloc_buffer(4096)
    let cfg = try(as ConfigError.Parse) parse(buf)
    let extra = try read_defaults()          // already ConfigError: bare try
    return assemble(cfg, extra)
}
```

The clause converts the error channel only; the Ok value is untouched. The
named case must carry exactly one payload, and the callee's error type must fit
it. There is no candidate search and no lifting trait — editing an enum never
changes what a distant `try` does, and every construction site is greppable.

The clause is written in PREFIX position because a trailing one could not be
told apart from a cast. `ConfigError.Alloc` and `time.Instant` are the same
dotted-path shape, so `try parse_id() as UserId` — a projection of the
unwrapped result — would be ambiguous with routing. The slot after `try` is
owned by `try`; every trailing `as` remains an ordinary cast.

`try!` and `try?` take no clause: neither propagates, so there is no error
channel to convert. A clause and a `catch` on one `try` are refused together —
route the error onward, or handle it here.

```saw
let n = try!(as ConfigError.Alloc) alloc_buffer(64)
// error: `try!` cannot take a routing clause — `try!` does not propagate the
//        error, so there is no error channel to convert
```

Inside a `try { } catch { }` block nothing is owed: the catch's error union
absorbs whatever propagates, routed or not. The routing happens before
propagation, so a routed `try` counts as its TARGET type everywhere downstream
— including the one-error-type rule a suspending `try { } catch { }` follows,
where routing two callees into one domain enum makes them one type at the
fence.

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

**In a suspending body the union is the one fence.** A `try { } catch { }` block
that spans a suspension becomes states of its own (see *Coroutines*), and the
caught error travels between them in a frame field of one declared type, so such
a block may propagate only ONE error type. Two is a clean error naming both,
with the two spellings that work: one block per error type, or an inline
`try <call> catch { … }` per call. A block in a sync body keeps the union
unchanged.

### Explicit Result Handling

You can always handle `Result` explicitly with `match`:

```saw
match read_file("data.txt") {
    case Ok(content) -> process(content),
    case Err(e) -> print("Error: {e.code}")
}
```

### Discarding a Result

A `Result` whose value no construct consumes is a compile error. A failable
call written as a bare statement throws away the failure it reports, so the
compiler rejects it:

```saw
import std.net.*

func send(stream: &var TcpStream, body: String) {
    stream.write(body)
    // error: result of `write` is `Result<Void, IoError>` and is silently
    //        discarded
    // hint: handle it — `match` it, `try`/`try!`/`try?` it, or return it — or
    //       write `let _ = ...` to discard it explicitly
}
```

Handling it means consuming the `Result`: `match` on it, apply `try`, `try!`
or `try?`, or return it to the caller.

```saw
func send(stream: &var TcpStream, body: String) -> Result<Void, IoError> {
    return stream.write(body)
}
```

When the failure genuinely does not matter, `let _ =` says so in the source and
the reader can see that the author decided:

```saw
func send(stream: &var TcpStream, body: String) {
    let _ = stream.write(body)   // best effort: the peer is already closing
}
```

The rule covers every position where a value is computed and nothing reads it,
not only bare statements. A `Void` function or method body's tail expression
counts, so does a loop body's tail, and so does a statement-position `if` or
`match` that forwards its branch's value. The diagnostic anchors on the call
that produced the `Result` rather than on the construct that forwarded it, so a
statement-position `match` reports each arm at its own line.

The check reads the type in hand, never the syntax that produced it. An erased
`Result<T, Box<any Error>>` is a `Result`, and a suspending call needs no
special case. `try!` and `try` consume the `Result` they apply to, so the `T`
they yield is an ordinary value; the one exception is a `T` that is itself a
`Result`, which the rule then covers on its own terms.

**`Result` only.** Optionals and every other type stay freely discardable.
Dropping the old value a map insert hands back is normal, and a `?.` chain
typed `Void?` is a statement by design. There is no must-use attribute in Saw:
a `Result` a caller may always ignore should not have been a `Result`.

### Panic for Unrecoverable Errors

Panics halt execution (unrecoverable). The compiler emits them for `try!`/
force-unwrap failures and division by zero (see Runtime Semantics). The
`panic(...)` builtin (design 49) and `.len()` on a fixed array (design 72) are
implemented; the `[Int]` slice parameter below is still *(illustrative)* — on a
fixed array `[Int; N]` the same code type-checks and runs today.

```saw
func get_index(arr: [Int], i: Int) -> Int {   // [Int] slice: illustrative
    if i >= arr.len() {
        panic("Index {} out of bounds", i)
    }
    arr[i]
}
```

#### Panic messages allocate nothing

A panic message is assembled in stack scratch, never on the heap. This matters
because the allocator is one of the things that panics: `Vector.push` panics
when a growth is refused (see [Allocation failure](#allocation-failure)), and a
message assembled through the allocator could not report that failure. The
message survives an exhausted allocator, the freestanding profile, and a kernel
with no heap.

Both spellings work, and the format-argument form is the one that holds under
allocator exhaustion:

```saw
panic("out of {}: wanted {}, had {}", "frames", 64, 3)
// panic at slab.saw:41: out of frames: wanted 64, had 3
```

The scratch holds 508 bytes of message. A longer one is cut and marked with a
trailing `…`, the same marker fixed-mode `StringBuilder` uses, so a shortened
abort message says it was shortened. The `panic at FILE:LINE:` prefix is an
interned constant and is never cut.

`assert(cond, "want {} got {}", a, b)` renders its arguments on the failing
branch only. A passing assert costs the condition test.

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
  through the same `__saw_rt_panic` seam, so it works freestanding.
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
  Their cast-shaped sibling is `T.from(truncating:)`, below: the same intent
  (defined two's-complement wrap, stated rather than implied) applied to a
  conversion rather than to an operator.
- **Float arithmetic** is untouched: IEEE semantics (inf/nan), no overflow trap.

### Integer Conversions

**Status: implemented (design 170).**

Three spellings, one for each thing a conversion between integer types can
mean. Choosing among them states what an unrepresentable value would mean at
that site.

```saw
let big = 1000

let a = big as UInt8                    // panics: 1000 has no UInt8 value
let b = UInt8.from(big)                 // None
let c = UInt8.from(truncating: big)     // 232 — the low 8 bits, on purpose
```

- **`x as UInt8` is CHECKED.** A value the target cannot represent, by range
  or by sign, panics: `panic at FILE:LINE: cast to UInt8 out of range: 1000`.
  The message renders the offending value through the allocation-free format
  path, so it works under an exhausted allocator and in the freestanding
  profile. A conversion that quietly yields a different number is the defect
  class arithmetic overflow already panics for, so `as` behaves the same way.
- **`UInt8.from(x)` returns `UInt8?`.** `None` when the value does not fit.
  This is the spelling for input the program does not control, where out of
  range is a fact about the input rather than a bug in the program.
- **`UInt8.from(truncating: x)` returns `UInt8`.** Total, and keeps the low
  bits — the value mod 2^n. The label *is* the operation: labels are overload
  identity, so there is no boolean parameter and no `truncate: false` corner.

Both `from` forms are defined for **every** source/target pair, total ones
included, so `Int.from(x: Int8)` type-checks and is always `Some`. A generic
body can rely on the shape existing at whatever type it is instantiated at.

Saturating conversion is not offered. Clamping is a value-domain policy, not a
bit operation, and offering it as an escape from the checked cast would
readmit plausible-looking corruption at sites that meant to convert.

#### What each pair costs

| Pair | Checked | Emitted |
|---|---|---|
| Same-sign widening (`Int8` → `Int`, `UInt8` → `UInt`) | no | one `sext`/`zext` |
| Unsigned → strictly wider signed (`UInt8` → `Int16`) | no | one `zext` |
| Identity (`Int` → `Int`) | no | nothing |
| Narrowing (`Int` → `UInt8`, `Int64` → `Int32`) | yes | one compare + branch |
| Sign change at or above the source width (`Int` → `UInt`) | yes | one compare + branch |

Total pairs emit exactly what they emitted before the rule existed: a check
there could only ever be true. A checked pair costs one compare and a branch —
the same class as the overflow check — and the optimizer removes it wherever
it can prove the range on its own.

#### Constants

An operand that folds to a compile-time value is answered at compile time. In
range, the check is elided and the cast is free. Out of range, it is a
**compile error**, not a program that builds and aborts on its first run:

```saw
let ok = 0xFF as UInt8      // fine, and free
let bad = 1000 as UInt8
// error: `1000` is not representable as `UInt8`, so this cast would always panic
// hint: `UInt8` holds 0 through 255; write `UInt8.from(truncating: ...)` to keep
//       the low bits, or `UInt8.from(...)` to get `None` instead
```

The folding evaluator is the one behind `static_assert` and `[T; N]` lengths,
so a folded cast and its runtime twin cannot disagree. It sees through const
arithmetic and a raw-backed enum's case value. It does **not** see through a
`let`: a local is a runtime value whatever it was initialized with, so
`let big = 1000` followed by `big as UInt8` takes the runtime check and
panics. The compile error is for a cast whose operand is written as a
constant, which is where a wrong constant is a typo the compiler can catch.

#### Interactions

- **Raw-backed enums.** `e as Backing` stays total — the enum *is* its tag.
  Casting **below** the backing (`enum E: UInt16` value `as UInt8`) is an
  ordinary narrowing and takes the ordinary rule. The partial inverse is still
  `E.from(raw:)`.
- **Distinct type aliases.** Projection resolves to the underlying first, then
  these rules apply, so an alias narrows exactly as its underlying does.
- **Pointer and address casts** are unaffected; see "Address casts".
- **Float** conversions are unchanged.

### Integer Width Agreement

**Status: implemented (designs 195, 205).**

Three rules cover every position where integers of different types meet.

#### Operands agree; only literals promote

All typed operands of an operation have the **same type**. A binary operator, a
comparison, a compound assignment or a range whose two operands are integers of
different width — or of the same width and different signedness — is a compile
error naming both:

```saw
func doubling(n: Int) -> Int {
    n * 2i16
}
// error: operator `*` requires both operands to have the same type, but the
//        left is `Int` and the right is `Int16`
// hint: drop the `i16` suffix so the literal adopts `Int`, or convert one
//       operand — `x as Int` panics out of range, `Int.from(x)` answers
//       `None`, `Int.from(truncating: x)` keeps the low bits
```

Implicit promotion happens from **operands whose width is still undecided** and
nowhere else. A bare literal has no width of its own and adopts the other
operand's type, so `n * 2` is legal at every integer type; the negated form
`n * -2` is a bare literal too, and `big / 3` on a `UInt big` is an unsigned
division, because the literal is a `UInt` there. A suffixed literal is
exact-typed, and a named value carries the type it was declared with.

A **constant expression** is in the same state and adopts on the same terms —
this is the mixed-binop position of the rule in "Integer literals adopt their
slot's width", so one bit is spelled one way wherever it appears:

```saw
enum SystemRight: UInt32 {
    case Transfer = 1 << 0,
    case Debug = 1 << 8,
}
static_assert((SystemRight.Debug as UInt32) >= (1 << 8),
              "kind-specific rights start at bit 8")
```

The fold supplies the names a constant may read, so a module `static` or a
raw-backed enum case may be a leaf; a value that does not fit the peer's width
is the same "does not fit" error a bare literal gives. A **runtime** operand is
not a constant, so `word.read() | (1u32 << n)` for a runtime `n` still needs its
suffix.

There is no promotion ladder. An operation has two peers, and a rule picking a
winner between them would decide, silently, which operand's reading the program
runs under. `Int` beside `UInt` is the case that shows why: read as signed, a
large `UInt` is negative; read as unsigned, a negative `Int` is enormous.

The **shift count is exempt**. `<<` and `>>` do not take two peers — the right
operand is a count, range-checked against the left operand's width at runtime
and contributing nothing to the result's type — so `flags << shift` stays legal
whatever the two types are. The compound forms `<<=` and `>>=` follow.

`Float` and an integer are two types, so they do not mix either. There is no
implicit conversion between them in any direction; write the float literal.

#### Value-branch arms are transfers

Each arm of a value `if` or `match`, and each operand of `??`, hands its value
to one merged home. Each is a transfer, so each takes the rule a `return` takes:
a lossless widening is free, and anything else is refused.

```saw
func f(a: Int) -> Int {
    if a > 0 { 11 } else { 7i16 }
}
// f(3) is 11; f(-3) is 7 — the Int16 arm widens into the merged Int
```

The merged type is the arm type every other arm widens into losslessly: the
identity, same-sign widening, and unsigned into strictly wider signed, which is
the total half of the conversion table above. Each arm extends into it by its
own signedness, so an unsigned arm zero-extends and keeps its value. Arms with
no such common type are refused where they are written:

```saw
func g(a: Int) -> Int {
    if a > 0 { 11 } else { 7u64 }
}
// error: the `if` and `else` branches have no common type: `Int` and `UInt64`
//        — neither widens into the other without losing a value
```

Two distinct fixed widths still do not merge, because they do not convert
implicitly anywhere (see "Integer Conversions"): an `Int16` arm beside an
`Int64` one is the same type error it is at a `let`. Bare literals adopt in arm
position exactly as they do in operand position, so the arms above in an
`-> Int16` function are legal with nothing written.

#### Plain transfers take the same rule

**Status: implemented (design 205).**

The two rules above are the operator's and the arm's. A plain transfer takes the
same one. A lossless widening is free; a narrowing or a same-width sign change is
one of the three spellings from "Integer Conversions", written where the value
lands.

```saw
let n: Int = 300
let b: Int8 = n
// error: cannot assign `Int` to variable of type `Int8`
// hint: write the conversion: `as Int8` panics out of range, `Int8.from(...)`
//       answers `None`, `Int8.from(truncating: ...)` keeps the low bits
```

There is no position exemption. The rule holds wherever a value lands in a new
home: a `let` or `var` initializer, an assignment right-hand side, a call
argument, a `return` and a body's tail expression, a struct-field initializer, an
enum payload, an array, tuple, `Vector`, `Map` or `Set` element, an optional
slot, a default parameter value, and a `static` initializer.

Only the platform pair changed, because it was the exception. Two fixed widths
have never been convertible: an `Int16` in an `Int8` slot is an error and always
was. `Int` and `UInt` were admitted into and out of every integer type, so
`let b: Int8 = n` on an `Int` holding 300 printed 44, and `let i: Int = u` on
`UInt.max` printed -1. That permission existed so a bare literal could reach a
fixed-width slot, a job expected-type propagation does on its own; what it
covered in practice was a value losing its high bits or its reading.

Two things are untouched. A bare literal still adopts the slot it is written in,
at every position on that list: `let a: Int8 = 42` needs no suffix and no
conversion, and is range-checked at the literal. And a lossless widening is still
implicit, because it decides nothing. `let wide: Int = u32val` extends by the
source's signedness and keeps the value. That admission is positional: a transfer
knows which side is the source, and general assignability does not.

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
  checked-by-default house rule as arithmetic overflow: a check the release
  build keeps.
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
- **All six fold in a constant.** `1 << BIT`, `MASK & ~ALIGN`, `A | B` are
  compile-time constants wherever their operands are, so a bit position or a
  mask is an array length, a repeat count, a const generic argument or a
  `static_assert` operand. See "Compile-Time Evaluation" for the grammar and for
  the width the folding uses.

#### Flag enums

A raw-backed enum's case is a compile-time constant (see "Raw backings"), so a
combination of cases folds in any constant position:

```saw
enum Perm: UInt8 {
    case Read = 0x01,
    case Write = 0x02,
    case Exec = 0x04
}

static_assert((Perm.Read | Perm.Write) == 3, "read+write")

struct Table { rows: [UInt8; Perm.Read | Perm.Write | Perm.Exec] }
```

**The result is the backing integer, never the enum.** `Perm.Read | Perm.Write`
is a `UInt8` holding 3, and 3 is not a declared case: typing it as `Perm` would
hand `Perm.from(raw:)` and an exhaustive `match` a value outside the closed set
the enum is. An enum is a set of tags; a bit set over those tags is the integer
they are tags for. Swift draws this line with `OptionSet` and Rust with
`bitflags`; Saw states it and does not ship a bit-set type.

**A fixed-width slot is a constant position too** (amended Aug 21 2026). Where a
declared narrower type is in force — an annotated `let`, a field, an argument, a
`return`, a `static`, an arm — the combination folds and is range-checked
against that type, so `let mask: UInt8 = Perm.Read | Perm.Write` is a `UInt8`
holding 3, and a combination too wide for the slot is a compile error rather
than a truncation:

```saw
let mask: UInt8 = Perm.Read | Perm.Write     // 3

enum Cfg: UInt16 { case Mask = 0x000F, case Wide = 0x1000 }
let narrow: UInt8 = Cfg.Wide | Cfg.Mask
// error: constant expression 4111 does not fit in `UInt8` (range 0..=255)
```

The same rule covers a module `static` named in such a slot
(`let e: UInt16 = 1 << PAGE_SHIFT`), which is what the size-in-one-place idiom
writes. See "Compile-Time Evaluation".

Outside a constant, a bit operator applied to an enum-typed **value** is a
compile error. The projection is explicit:

```saw
let held = Perm.Write
let flags = (held as UInt8) | (Perm.Exec as UInt8)   // UInt8, 6

let bad = held | Perm.Exec
// error: operator `|` requires integer operands, got `Perm` and `Perm`
//   hint: an enum is a closed set of tags, not a bit set: write
//         `(a as UInt8) | (b as UInt8)`. The result is the backing integer,
//         because a combined value need not be a declared case
```

`e as Backing` is the same total projection design 145 defines, and requiring it
is what keeps "a raw-backed enum value is always a declared case" true.

### Runtime Semantics and Traps

**Status: implemented.**

- **Every compiler-raised panic names its source location.** Integer overflow,
  division by zero, shift range, array bounds, force-unwrap of `None` and `try!`
  on an `Err` all abort through the same prefix `panic()` and `assert()` use:
  `panic at FILE:LINE: {reason}`. FILE is the source basename (the spelling
  `#file` produces); LINE is the line of the expression that trapped, not the
  top of the enclosing function. Both are compile-time constants folded into the
  message text, so a check still lowers to one constant and one
  `__saw_rt_panic` call, and the format is the same in the hosted and
  freestanding profiles.
- **Force-unwrap of `None`** (`opt!`) panics with "force unwrap of None".
- **`try!` on an `Err`** panics with "try! failed: `error`", rendering the error
  it was handed:

  ```saw
  func reserve() -> Result<Void, AllocError> {
      return AllocError(size: 64, align: 8)
  }

  func main() {
      try! reserve()
      // panic at reserve.saw:6: try! failed: allocation of 64 bytes (align 8) failed
  }
  ```

  The error goes through the allocation-free format path, so the message
  survives an exhausted allocator and works freestanding; an erased
  `Box<any Error>` renders through its vtable, as `"{e}"` does. `E` is not
  bounded `Printable` at a `try!`, so an error type with no conformance keeps
  the bare "try! failed".
- **An integer `as` whose value the target cannot represent** panics with
  "cast to `T` out of range: `value`" (design 170). The value is rendered on
  the failing branch only, through the allocation-free format path. An operand
  that folds out of range is a compile error instead, and a total pair is never
  checked. See "Integer Conversions".
- **Fixed-array indexing with an out-of-bounds compile-time constant** is a
  **compile error** ("index out of range"), mirroring the tuple-index check.
- **Fixed-array indexing with a *dynamic* index** is **bounds-checked at
  runtime** (design 63): `0 <= i < N` (folded to one unsigned compare, so a
  negative index is caught too); an out-of-range index panics
  "array: index out of range: `i` (len `N`)" — the bounds-panic wording family,
  see "The accessor rule". ALWAYS ON, every profile, no disable flag (the same
  posture as integer overflow). An in-range constant index is folded away;
  raw-pointer / `UnsafeMemory` indexing is the explicit unchecked escape. Read
  and write paths are both checked.
- **Tuple indexing** past the tuple's arity is a compile error.

### Equality (`Equatable`)

**Status: implemented** (`designs/32-equality.md`). The `Equatable` trait gates
`==` / `!=`; conformance mirrors the Copy family's house rule:

- **Auto-conform:** trivial (POD) structs — the exact set that auto-conforms to
  `Copy` — and payload-free enums. Integers, `Bool`, `Float`, and `String`
  conform builtin.
- **Opt-in with synthesis:** every other struct/enum declares the conformance and
  marks it `@synthesize` to have the comparison derived: memberwise `&&` for
  structs, payload-deep for enums (equal tag, then the active variant's payload
  fields, recursively). A hand-written
  `func equals(&self, other: &Self) -> Bool` is used instead of the derivation.
  A declared conformance that neither carries `@synthesize` nor writes `equals`
  is a compile error; see [Synthesized conformances](#synthesized-conformances).

  ```saw
  @synthesize
  extension Named: Equatable {}
  ```
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
- **The right operand is a shared reference**, at every tier: see
  [The comparison operand is a
  reference](#the-comparison-operand-is-a-reference).
- **Migration note:** payload-carrying enums previously had a tag-only `==`
  (so `Msg.Write("a") == Msg.Write("b")` was wrongly `true`). They now have no
  `==` until they declare `Equatable`, and it is payload-deep.

### Ordering (`Comparable`)

**Status: implemented** (`designs/48-ord-hash.md`). The `Comparable` trait gates
the ordering operators `< <= > >=`, which **desugar to `compare`**:

```
enum Ordering { case Less, case Equal, case Greater }

trait Comparable {          // requires Equatable
    func compare(&self, other: &Self) -> Ordering
}
```

- **Builtin:** integer types, `Float`, and `String` conform builtin. Integers
  and `Float` lower directly to `icmp`/`fcmp`; `String` compares
  **byte-lexicographically** (= code-point order for ASCII / UTF-8; a shorter
  string that is a prefix of a longer one is `Less`).
- **No auto-conformance.** Unlike `Equatable`, a struct/enum is *never*
  automatically `Comparable` — field order is a semantic choice. Opt in with
  `@synthesize extension T: Comparable {}`, which derives a lexicographic
  compare (struct: field-declaration order; enum: variant-declaration order,
  then the active payload). A hand-written `compare` is used instead. Since
  Comparable has no auto-conformance, every Comparable conformance is written,
  and every derived one carries the marker.
- **Requires Equatable.** A `Comparable` type must also be `Equatable` (so `==`
  and `compare(...) == .Equal` agree); a trivial struct satisfies this by
  auto-`Equatable`, otherwise declare `@synthesize extension T: Equatable {}` too.
- `a < b` is `a.compare(&b) == .Less`, `a <= b` is `!= .Greater`, etc. A
  `T: Comparable` generic bound grants the operators in a generic body.
- **Float NaN:** a `NaN` is unordered, so every ordering operator involving it
  is `false` (matching the primitive `fcmp`); in a three-way `compare`, an
  unordered pair yields `Equal` (there is no total order over NaN — documented).

### The comparison operand is a reference

**Status: implemented.** `Equatable.equals(&self, other: &Self)` and
`Comparable.compare(&self, other: &Self)` take the right operand as a shared
reference, at every copy tier. A comparison therefore destroys neither operand,
and there is no rule to remember: nothing is transferred, so no conformance can
consume what it was handed.

A move-only type with a hand-written comparison is comparable:

```saw
struct Tag { id: Int }
extension Tag: NoCopy {
    func deinit(&var self) { print("drop {self.id}") }
}
extension Tag: Equatable {
    func equals(&self, other: &Self) -> Bool { self.id == other.id }
}
extension Tag: Comparable {
    func compare(&self, other: &Self) -> Ordering {
        if self.id < other.id { Ordering.Less }
        else if self.id > other.id { Ordering.Greater }
        else { Ordering.Equal }
    }
}

let a = Tag(id: 9)
let b = Tag(id: 3)
if a > b { print("gt") }
// prints: gt
// prints: drop 3
// prints: drop 9      — two drops for two values, however many comparisons ran
```

Two rules follow from the signature.

**A conformance must declare the reference.** A by-value `other` says the body
may take ownership of an operand every caller only lends, so it is refused at
the declaration:

```saw
extension Tag: Equatable {
    func equals(&self, other: Tag) -> Bool { self.id == other.id }
}
// error: parameter `other` of `equals` must be a reference: trait `Equatable`
//   declares it `&Self`, and this implementation takes it by value (`Tag`)
// hint: write `func equals(&self, other: &Self)` — on `Tag` that is `&Tag`. A
//   by-value parameter says the body may consume what it is given, and every
//   caller of the requirement hands it a borrow
```

The rule is general — a conformance's parameters mirror the requirement's
borrows, in both directions and including `&` against `&var`.

**A body cannot consume its operand.** `move other` is the ordinary "cannot
move out of reference", reported in the body at the line that wrote it. That is
what closes the hole by construction rather than by a check: there is no
position from which a conformance could release a value the caller still owns.

**Calls spell the borrow.** The operators are compiler-lowered and unchanged
(`a == b`, `a < b`); the direct call writes the `&` every reference argument in
Saw writes, at a concrete receiver and through a generic bound alike:

```saw
if not a.equals(&b) { print("tags differ") }

func differ<T: Equatable>(a: &T, b: &T) -> Bool { a.equals(&b) }
```

`differ` works at every conforming type — the integers, `Float`, `String`, and
your own structs and enums, derived or hand-written — because a call through
the bound uses the same lowering the operator does.

**Migration.** A pre-existing conformance written `other: Self` gets the error
above; change the parameter to `&Self` and delete any `move` of it. The tiers
that used to be refused outright (an ExplicitCopy or NoCopy operand reaching a
hand-written body, directly or through a member, enum payload, tuple element,
optional payload or array element) all compare now, and so does a generic body
under a `T: Equatable`/`T: Comparable` bound instantiated at one. `String`'s own
`equals`/`compare` keep a by-value `other`: `String` conforms builtin rather
than through a written conformance, and those methods are its own API.

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
  and payload-free enums auto-conform; everything else opts in with
  `@synthesize extension T: Hashable {}` (which streams each field / active
  payload); primitives and `String` conform builtin. `Hashable` **requires
  Equatable**.
- **hash/== contract:** `a == b` implies `a` and `b` hash identically. Synthesis
  upholds it by streaming exactly the fields `==` compares; a hand-written
  `hash` must uphold it. (Unequal values *may* collide — that is a hash map's
  job to resolve.) `Float` normalizes `-0.0`/`+0.0` so they hash alike; NaN bit
  patterns are not normalized (`NaN != NaN`, so nothing is required).
- `x.hash(&var h)` streams `x`; primitives mix directly, `String` streams its
  bytes, structs/enums stream their fields/payloads.

### Serialization (`Serialize`, `Deserialize`, `Encoder`, `Decoder`)

**Status: implemented** (`designs/169-serialize-cbor.md`). A value writes itself
into an `any Encoder` and reads itself back out of an `any Decoder`. The traits
name a data model; the concrete format decides the bytes (`std.cbor` is the
format in the tree). All four names are prelude-visible and present in the
freestanding profile.

```
trait Serialize {
    func serialize(&self, to: &var any Encoder) -> Result<Void, EncodeError>
}

trait Deserialize {
    static func deserialize(from: &var any Decoder) -> Result<Self, DecodeError>
}
```

- **`deserialize` is STATIC** — it is called on the type
  (`Point.deserialize(from: &var d)`), because there is no value yet to call it
  on. That makes `Deserialize` a generic **bound**, never an `any Deserialize`
  existential: a static requirement has no receiver to dispatch on, and
  `Result<Self, DecodeError>` names `Self` by value. Both are rejected at the
  point the existential is written. `Serialize`, `Encoder` and `Decoder` are
  object-safe on purpose — they are the traits that travel behind `any`.
- **Failures are `Result`, never a sentinel or a half-built value.**
  `EncodeError` carries an `EncodeFault`; `DecodeError` carries a
  `DecodeFault` *and the byte offset it stopped at*, so a rejected blob can be
  examined at the position that stopped it. Malformed input always arrives as an
  error — a decoder never panics on it.
- **Counts are declared, not implied.** `begin_array(count:)` /
  `begin_map(count:)` open an item of exactly that length and are followed by
  exactly that many items; `begin_bytes(count:)` opens a byte string filled by
  that many `write_byte` calls. Miscounting is `CountMismatch`, not a silently
  short item.
- **Every serde signature is `sync`.** Serialization writes into a buffer, so it
  is suspension-free by contract, and the effect is what lets a value serialize
  inside a place window, under a `SpinLock`, or in a kernel. A conformer that
  wants to do I/O writes into a buffer first and sends the buffer afterwards.
- **`@synthesize` derives both directions structurally.** The walk emits every
  stored field in declaration order as one array; it covers the integer types,
  `Bool`, `String`, `Optional` (absent becomes null), `Vector`, raw-backed enums,
  and any member that itself conforms. A member outside that set is a clean
  error naming the field and its type, with the hand-written body as the way
  out — never a silently skipped field.
  ```
  @synthesize
  extension Endpoint: Serialize {}
  @synthesize
  extension Endpoint: Deserialize {}
  ```
  A **raw-backed enum** derives from the design-145 idiom: out through the
  case's raw value, back through the partial `E.from(raw:)`. A raw value no case
  carries is data, not a trap — it becomes `UnknownCase` at the byte it was read
  at. An enum with **no** raw backing is refused, naming the backing to declare:
  its cases have no on-the-wire values.
  Unlike the Equatable/Comparable/Hashable derivations, which codegen emits from
  the field layout, these two synthesize a real source body and hand it to the
  ordinary front end — a derived body is made of `try`, method calls and a `for`
  loop, and `Result` propagation is not worth re-implementing in IR.
- `Decoder` carries three requirements with **default bodies**:
  `expect_array(count:)` (open an array and check its length),
  `read_int_range(min:max:)` and `read_uint_max(max:)`. The last two are how a
  value narrower than `Int` is read back: a narrowing cast would panic on an
  out-of-range value, and malformed input must never panic, so the range is
  checked first and the cast that follows cannot trap.

### `std.cbor` — the concrete format

**Status: implemented** (`designs/169-serialize-cbor.md`, `std/cbor.saw`).
CBOR (RFC 8949) restricted to its **deterministic encoding** profile. The wire
contract is frozen in `sawc/std/CBOR.md`, and `tools/sawcbor.py` is a second
implementation of that same document over the `cbor2` library; the blobs under
`tests/cbor_vectors/` are what the two are held to. Import-required, and present
in both profiles.

```saw
import std.cbor.{CborEncoder, CborDecoder}

var enc = CborEncoder()
try entry.serialize(to: &var enc)
let blob = try enc.finish()

var dec = try CborDecoder.open(bytes: move blob)
let back = try LockEntry.deserialize(from: &var dec)
```

The profile in one list: shortest-form arguments, definite lengths only, map
keys sorted by their encoded bytes, no floats, no tags, one top-level item. A
blob outside it is **rejected on decode** rather than tolerated, because
accepting two spellings of one value would make "the bytes are the value" false.
A struct is an array of its stored fields in declaration order, not a map of
names, so nothing is spent encoding names and schema evolution is a v1 non-goal.

- **`CborEncoder`** writes into a growable buffer it owns. `finish()` hands the
  bytes over and reports `CountMismatch` if an array, map or byte string is
  still open. An allocation the buffer cannot serve is `EncodeFault.BufferFull`,
  not a panic, so a value can be encoded under a constrained allocator. Writing
  a map whose keys are out of order or repeated is `Unsupported`: the profile
  has no representation for a non-canonical map, so the encoder cannot emit one.
- **`CborDecoder.open(bytes:max_depth:max_size:max_items:)` validates the whole
  input before it returns.** Typed reads then run over bytes already known to be
  well formed. The scan walks an **explicit work stack**, so nesting depth is
  the stack's height, checked before each descent: the decoder never recurses on
  input, and a blob nested a hundred thousand deep is refused at the byte where
  it passed the limit rather than exhausting the call stack. Limits are
  constructor parameters with hosted defaults (64 levels, 16 MiB, 100000 items);
  a kernel caller states its own. A container declaring more items than
  `max_items` is refused at its head, before anything is reserved for it.
- **No input panics.** The decoder's one allocation is that work stack, sized
  once at open from `max_depth`. Text is validated as UTF-8 by decoding the
  bytes in place rather than by building a `String`, so a text item cannot put
  the scan at the allocator's mercy.
- **`transcode(to:)`** writes the whole input into any `Encoder`, item by item,
  re-encoding each from its parsed value rather than copying bytes. Against a
  `CborEncoder` that yields the canonical spelling of the input, which is what
  the vector suite checks.
- **Floats are a decode error in v1.** No Float16, Float32 or Float64 is written
  and every one is rejected on read. `Float` has no settled serialization, and
  choosing one here would freeze it into stored blobs. Half- and
  single-precision stay out permanently under the shortest-form rule, which
  admits one spelling per value.
- `encode<T: Serialize>(value:)` is the one-call write. There is **no**
  `decode<T>` twin: a static trait requirement is not callable on a type
  parameter yet (DF-169e), so a value is read back through its own type,
  `LockEntry.deserialize(from: &var dec)`.

### `Vector.each` / `map` / `fold` / `each_indexed`

**Status: implemented** (`designs/216-vector-copy-bounds.md`). The four closure
methods carry **no copy bound**. Each lends the element to the closure as a
`&T`, so the vector still owns it afterwards and a move-only element type
traverses like any other:

```saw
var jobs = Vector<Job>()        // Job is NoCopy
try! jobs.push(Job(name: "alpha"))

jobs.each { j in print(j.name) }            // borrows the element
let labels = try! jobs.map<String>({ j in j.label() })  // map allocates, so it reports
let total  = jobs.fold<Int>(0) { acc, j in acc + j.name.len() }
```

`map`'s closure is written inside the parentheses rather than trailing it,
because a trailing closure is not recognized inside a `try` operand today —
`try! jobs.map { … }` reads the `{` as a separate closure and the call as a
field access (DF-259c). `each` and `fold` are unaffected: neither allocates,
so neither needs the `try!`.

Reading a `&T` binding yields the value, so `{ $0 * 2 }` and `{ $0.to_string() }`
are written exactly as before. What the reference spelling changes is
**forwarding**: a closure handing its element to another `&T` parameter writes
`&n`, not `n`.

The closure parameter is not `sync`, so a **suspending** transform works. The
element borrow may then span a suspension: the method holds `&self` for its
whole run, so the Law of Exclusivity forbids any `&var self`, and therefore any
`push` and its reallocation, from reaching the buffer under a live borrow.

`iter` and `enumerated` keep `T: Copy`; `VectorIterator` and
`EnumeratedIterator` conform to `Iterator` under `T: ExplicitCopy`. Theirs is a
real constraint rather than an inherited one: `next()` hands the consumer an
element it owns, which is a copy at the source.

### `Vector.sort` / `sort_by`

**Status: implemented** (`designs/48-ord-hash.md`). In-place **insertion sort**
(simple and correct first; **stable** — equal elements keep input order):

- `sort(&var self)` on `Vector<T: Comparable + Copy>` — ascending by `T`'s order.
- `sort_by(&var self, compare: (T, T) -> Ordering)` on `Vector<T: Copy>` — the
  comparator is a **non-escaping** closure parameter.
- Element *movement* uses byte-level `swap` (refcount-neutral, never a copy);
  *comparison* reads both elements by value through `get`, which is what binds
  them to `T: Copy`. No ExplicitCopy element is ever silently duplicated. The
  bound was blocked on `Comparable`/`Equatable` taking `other: &Self`, which
  they now do ([The comparison operand is a
  reference](#the-comparison-operand-is-a-reference)); lifting it is the
  remaining half of `designs/216-vector-copy-bounds.md`, which the closure
  methods already had.

### `Map<K: Hashable + Equatable, V, A: Allocator = GlobalAllocator>`

**Status: implemented** (`designs/48-ord-hash.md`, unified by `designs/54`).
`Map` is **THE dictionary type** — an **open-addressing** hash table (linear
probing, tombstone deletion) over a `Vector` of slot enums. (The old
Vector-backed linear-scan `Map` was **retired** in design 54; there is now one
`Map`, and the name `HashMap` no longer exists.)

- Power-of-two capacity (bucket = `hash & (cap-1)`); grows (doubling + rehash)
  once the live-load factor would exceed 3/4.
- `init()`, `len`, `is_empty`,
  `insert(key, value) -> Result<V?, AllocError>` (the `Ok` payload is the old
  value on update), `contains_key(key) -> Bool`, `remove(key) -> V?`. Works with
  `Int` and `String` keys (and any `Hashable + Equatable` key).
- **`m[k]` and `m.get(k)` are ONE accessor under two names** — a conditional lend
  of the stored value (`borrows -> V?`; see [Places](#places-borrows-and-lend)).
  Both name the value where it sits, both open no window at all for an absent
  key, and both follow the copy tier when the place is read out as a value.
  `get` used to return an owned `V?` built by copying the slot, which for a
  move-only value was a non-retained alias two lookups double-freed; reach such
  a value through the window (`m.get(k)!.method()`) or take it out with `remove`.
- **Keys must be copyable-with-retain** (design 65): the container probes keys BY
  COPY (hash / compare / slot inspection), so a KEY must be trivial/POD,
  `Copy` (String, `Arc<T>`), or `ExplicitCopy` — a **NoCopy** key, or a
  `Deinit`-only move-only key, is a clean compile error. VALUES have no such
  restriction (a NoCopy value is fine — it is moved, never probe-copied). A
  **payload-free enum is trivial/POD** and so is a legal key: it is a bare tag,
  owning nothing, which is the same reason it auto-conforms to `Equatable` and
  `Hashable` in the first place.
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
Map **key** rule: they must be copyable-with-retain (trivial/POD, `Copy`,
or `ExplicitCopy`) — a NoCopy / move-only-Deinit element is a compile error.

- Core: `insert(v) -> Result<Bool, AllocError>` (the `Ok` payload is true iff
  newly inserted), `remove(v) -> Bool`, `contains(v) -> Bool`, `len()`,
  `is_empty()`, `each(body: (T) -> Void)` (non-escaping visitor; mutating the set
  inside its own `each` is a static Law-of-Exclusivity error),
  `to_vector() -> Result<Vector<T, A>, AllocError>` (`T: Copy`),
  `Set(from: Vector<T, A>) -> Result<Set<T, A>, AllocError>` (consumes/drains the
  vector; NoCopy-safe), `Set.of(v)` (single-element factory, same shape).
- Algebra (all borrow `&other`, all bounded `T: Copy` — even membership-only ops
  read each element by value): `union`, `intersection` and `difference` build a
  NEW set, `is_subset` and `is_superset` answer a `Bool`, and every one of the
  five reports through `Result<_, AllocError>` because each builds a table to
  work in.

**Iteration** (`designs/57`). Saw's no-escape references mean an iterator object
cannot borrow the map, so iteration is not an Iterator-over-a-borrow. Two forms:

- **Visitors** (the zero-allocation primitive) — non-escaping closures, same
  borrow discipline as `Vector.sort_by`/`withCString`:
  `each(body: (K, V) -> Void)`, `each_key((K) -> Void)`, `each_value((V) -> Void)`.
  Keys/values are handed to the closure **by value**, so a visitor works for a
  trivial or `Copy` key/value type. Empty/Tombstone slots are skipped. **Order is
  UNSPECIFIED** (table/bucket order, not insertion order) — sort a `keys()`
  snapshot for deterministic output. Mutating the map inside its own visitor is a
  static Law-of-Exclusivity error (iterator invalidation caught at compile time).
- **Snapshots** (the convenience, built on the visitors):
  `keys() -> Result<Vector<K, A>, AllocError>` (bounded `K: Copy`) and
  `values() -> Result<Vector<V, A>, AllocError>` (bounded `V: Copy`) — each
  allocates the snapshot, so each reports. There is no `entries()` in v1 (a
  tuple-of-copies has containment wrinkles the visitors already cover).

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

#### Conformances on primitives

**Every** primitive is an extendable pseudo-struct — `Int`, `UInt`, the eight
fixed-width integers, `Bool`, `Float`, `String` — so a user trait may be
conformed to any of them and the conformance participates in generic bounds:

```saw
trait Wire { func encoded(&self) -> UInt8 }
extension UInt8: Wire { func encoded(&self) -> UInt8 { self } }

func put<T: Wire>(v: T) -> UInt8 { v.encoded() }   // monomorphized, no vtable
```

A primitive cannot be **erased** to `&any Trait` or `Box<any Trait>`: an
existential carries a vtable beside the value and a primitive has no boxed form
to carry one. That is a clean error naming the two ways out — a generic bound
(above), or a wrapper struct you own and conform. Neither costs anything at
runtime.

---

## 6. Concurrency

**Status: implemented.** Saw's concurrency is **colorless** (designs/18 Axis
B′): there is NO `async`/`await` keyword and there never will be — any call may
suspend, and the marked side is the rare negative effect `sync` (a checked
suspension-free context). The model is task-only: no user-facing thread API, no
thread identity ever exposed — the engine is a swappable implementation detail.
Two engines ship and coexist (they are not unified): the design-21b
OS-thread engine (`Thread.spawn`/`Thread<T>`/`Channel.recv`, below) and the cooperative
executor — single-threaded by default, with `TaskGroup(threads: N)` opting into
multiple threads (design 75) — carrying the coroutine transform, suspending
`main`, and the multi-task `TaskGroup` (designs 44/45/52/52b, below).

**Landed in stage 1:**

- **`Send`/`Sync` marker traits**, compiler-known and auto-derived
  *structurally* (the auto-`Copy` pattern), usable as generic bounds
  (`T: Send`). Primitives/`Bool`/`Float`/`String` are `Send + Sync` (`String`'s
  day-one atomic refcount is the designed payoff); a struct/enum is `Send`/`Sync`
  iff all its fields/payloads are; `UnsafePointer<T>` is neither and poisons its
  containers structurally. The wrappers override the structural rule so their raw
  pointers do not poison them: `Arc<T>` is `Send + Sync` iff `T: Send + Sync`;
  `Mutex<T>`/`Channel<T>`/`Thread<T>` are `Send`/`Sync` iff `T: Send`; and an
  OWNING CONTAINER inherits its contents' answer — `Vector<T>`, `Map<K, V>` and
  `Set<T>` are `Send`/`Sync` iff their elements are, with `Data` and
  `StringBuilder` unconditional on `String`'s argument (design 187, closing
  DF-182e). A container's buffer pointer is its own bookkeeping, and `&var`
  access to it goes through the Law of Exclusivity, so moving one across a
  thread boundary is safe exactly when moving its contents is. Explicit
  conformance to the bare traits (`extension X: Send`) is rejected —
  derivation is structural; a type asserting what the compiler cannot
  see declares `UnsafeSend`/`UnsafeSync` instead (design 186; see the
  `UnsafeSync / UnsafeSend` section), the same declared-unsafety
  mechanism as everywhere else.
- **`Arc<T>`** — atomic reference-counted shared ownership (`Copy +
  Deinit`). One control block `{ i64 strong, i64 weak, T payload }` taken from
  the `__saw_rt_alloc` seam;
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
  seam-allocated block. `lock(body)` runs the closure once, synchronously, with
  `&var` access to the payload under the lock, and is **non-reentrant**
  (self-deadlock on re-lock). The pthread opaque buffer is a conservative
  64-byte slot (real sizes: macOS 64, glibc/x86_64 40, glibc/aarch64 48),
  initialized via `pthread_mutex_init` — never a hardcoded platform struct.
- **Escaping-closure heap environments — `Copy`, refcounted env**
  (design 71 + 73) — a closure used in value position (bound, returned, stored,
  or passed to `spawn`) outlives its creating frame, so its captured environment
  comes from the allocator instead of the stack. Captures are **moved in at
  creation** (Copy retained, trivial copied bitwise; a `move` capture
  takes ownership); the creating frame does not release a moved-in capture early.
  **An escaping closure is a `Copy` value** (the family of `String` and
  `Arc`): its heap env leads with an **atomic refcount word**, the closure
  representation is `{ fn_ptr, env_ptr, dtor_ptr }`, and the env is immutable and
  shared. Copying a closure — `let g = f`, a struct/`Vector`/field copy, passing
  or returning by value — is a **refcount bump**; there is no observable mutation
  through a shared env, so the sharing is semantically invisible. Dropping a
  closure **releases** one reference: it decrements the refcount and, only at the
  last owner, runs the env deinit (releasing owned captures exactly once and
  freeing the block) under the normal LIFO + drop-flag rules, wherever the value
  lives (a `let`/`var`, a struct field, a `Vector` element, a returned result).
  A **capture-less** closure has a null env (no refcount word) and is trivially
  copyable. Forwarding a closure into a *non-escaping* (borrowing) parameter is a
  **lend** — no retain, and the caller keeps ownership (drops once). For `spawn`
  the task frame owns the closure's reference and the trampoline release is THE
  release — the env is torn down on the task thread exactly once. Non-escaping
  closures (a direct call argument, e.g. `Mutex.lock`'s body) keep a stack env and
  own nothing. Borrow captures remain non-escaping-only, in all three of their
  spellings: `[&x]`/`[&var x]`, a reference parameter, and `self` (see
  [Capturing `self` and reference parameters](#capturing-self-and-reference-parameters)). *(This
  closed design 71's residual gap: an owning closure in a copyable struct that is
  then copied now retains the shared env and tears it down once at the last
  owner.)*
- **A `move` capture into a non-escaping closure transfers when the body runs.**
  A non-escaping closure keeps its environment on the stack and has no teardown
  of its own, so it cannot own a value from creation the way an escaping
  environment does. Its environment holds a pointer to the local, and the body
  takes the value as it starts. The source therefore stops owning it on exactly
  the paths that run the body. A body that never runs (a conditional lend's
  absent path, a closure the callee did not call) leaves the local alone, and it
  deinits at the end of its own scope. What the body took belongs to the body: a
  body that moves it on only some paths deinits it on the others, at the body's
  end. This is one rule for every non-escaping shape, the closure a place window
  is lowered into included, which is what makes `v[i].push(move h)` through a
  place consume `h` once:

  ```saw
  let h = Res(id: 1)
  try! slots[0].push(move h)     // `h` is the container's now
  ```

  Running one such body twice panics rather than taking a value that has already
  left. An **escaping** closure keeps the creation-time transfer described above.
- **Assigning to a by-value capture is a compile error** (design 132). The env
  above is immutable, and at body entry every plain / `move` / `copy` capture is
  loaded out of it into a per-call local. A write to one therefore lands on that
  local and is gone when the call returns, so the checker rejects it instead:

  ```saw
  func make_counter() -> () -> Int {
      var n = 0
      { n = n + 1        // error: cannot assign to `n`: it is captured by
        n }              //        value, so the write would be discarded
  }                      //        when the closure returns
  ```

  The diagnostic names the two spellings that do reach real storage. `[&var n]`
  captures by borrow, legal in a closure passed directly to a non-escaping
  parameter, where the env holds a pointer into the live frame. `Arc<Mutex<T>>`
  is the answer for a closure that outlives the frame, since the state is then
  shared rather than captured. Reading a by-value capture is untouched, as are
  a closure's own locals and params, a `&var` closure parameter, and a write
  through a capture whose type is already a reference. The rule covers the
  whole path into the captured value — `x = v`, `x += v`, `x.f = v`, `x.0 = v`,
  a fixed-array element — but not an index into a heap-backed container such as
  `Vector`, whose buffer the copy shares with the original.
- **A closure satisfies the generic `Copy` bound** (design 77 DF-C2). Because an
  escaping closure is `Copy`, a container element type of closures is
  copyable: `Vector<() -> Int>` is `ExplicitCopy`, and `.copy()`/`.get()` each
  retain the element env exactly once (balanced deinit through copy-and-read).
- **A `return` inside a closure returns from the CLOSURE**, and is checked
  against the closure's own return type. A closure is a callable, so control
  leaving its body leaves that body; the enclosing function's signature has no
  say. This is what lets a closure take an early exit:

  ```saw
  func each_sync(body: (Int) sync -> Void) { body(1)  body(-2)  body(3) }

  func report(v: &Vector<Int>) -> String {
      each_sync({ e in
          if e < 0 { return }      // skip this element; `report` keeps going
          print("saw {e}")
      })
      "done"
  }
  ```

  The closure's return type comes from the slot it is passed to when there is
  one, and from the body when there is not — with no expected type, the
  `return`s are checked against each other and against the tail expression, so
  a body whose every path returns still types as what it returns rather than
  `Void`. An error raised inside a closure follows the same boundary: `try`
  propagates out of the CLOSURE, so it needs the closure's return type to be a
  `Result`, and a `try {} catch {}` written in the enclosing function does not
  extend into a closure body (that catch belongs to a frame the closure's error
  path never reaches — write the closure its own).
- **`Arc<T>` payload method forwarding** — a `&self` method on the
  payload `T` is callable through the `Arc` (`arc.method(...)`): the call borrows
  the control block's payload slot. Sound because a live strong reference pins
  the payload. A `&var self` payload method is rejected (aliased mutation — use
  `Arc<Mutex<T>>`). This gives the `Arc<Mutex<T>>` idiom its access path:
  `arc.lock { ... }` forwards to `Mutex.lock`.
- **`Thread.spawn` / `Thread<T>`** — `Thread.spawn { ... } -> Thread<T>`
  launches the closure on a fresh OS thread (hosted pthread-per-thread engine;
  the thread identity is never exposed). A body whose value is `Void` yields a
  `VoidThread` instead, for the same reason `group.spawn` yields a `VoidTask`:
  `Thread<Void>` cannot be written as an annotation, and joining one has no
  value to hand back.
  The Send capture-audit walks the closure's captures and rejects the first
  whose type is not `Send`, naming the capture. The RESULT type is checked the
  same way: it is computed on the spawned thread and handed back by `join()`, so
  a non-`Send` result is refused at the spawn. Inside a GENERIC body the audit
  reads the enclosing signature's DECLARED bounds — a `<T: Send>` bound licenses
  capturing a `T`, `<T: Send + Sync>` licenses an `Arc<T>` — because a generic
  body is checked once, abstractly, and a declared bound is a promise the caller
  is separately made to keep (it is checked at the call, against the concrete
  type argument). An unbounded `T` is refused, as it always was.
  `Thread<T>` and `VoidThread` are `NoCopy + Deinit`. `join` blocks for the
  result; the handle must reach one of the fates below on every path, and
  dropping it is not one of them (see [No implicit
  fates](#no-implicit-fates)).
  The body is a `sync` context that permits a `blocking` extern (see
  [The thread body](#the-thread-body)).
- **`Channel<T: Send>`** — a `Copy` handle onto a shared, internally
  refcounted unbounded MPMC queue (cloning the handle shares the queue; the last
  handle drains and frees it). Guarded by an internal pthread mutex + condvar
  (conservative 64-byte condvar slot; real `pthread_cond_t` is ≤48 bytes),
  initialized via `pthread_cond_init` — never a hardcoded struct.
  `send(v) -> Result<Void, ChannelError>` enqueues under the lock and wakes the
  receivers parked on that channel; `recv() -> T` blocks the calling thread while
  empty. `close() -> Result<Void, ChannelError>` is how a producer says it is
  finished (design 230, below): there is no sender count to derive it from.
  `T: Send` is enforced on the type at construction.

The atomic-ordering runtime (`__saw_atomic_*`, per the String protocol) is
shared by `Arc` and `Channel`; the thread-spawn/join (`__saw_rt_thread_spawn`/
`_join`, design 117) and condvar wrappers back `Thread.spawn`/`Thread<T>` and
`Channel`. Under the cooperative engine the channel wait
is the suspending `receive()` twin — `recv()` remains the blocking
thread-engine call; `lock`'s
critical section stays synchronous (a `sync` closure cannot suspend), which is
how the never-block invariant makes holding a lock across a suspension point a
compile error.

**Status: tasks, channels, Mutex, Send/Sync — implemented (stage 1,
thread-per-task engine). Cooperative engine — implemented: the coroutine
transform, suspending `main`, and multi-task `TaskGroup` (spawn / join / cancel /
suspending channel) all ship (designs 44/45/52/52b), including OPT-IN
multi-threaded execution `TaskGroup(threads: N)` with a Send-on-frames gate
(design 75).**
There is NO `async`/`await` keyword and there never will be: Saw is
COLORLESS (designs/18 Axis B′). Any call may suspend; the marked side is
the rare one — `sync` contexts are checked suspension-free. Tasks are the
ONLY concurrency
primitive: no user-facing threads, no thread identity, ever. The stage-1
engine happens to run one OS thread per task; that is invisible and will
change.

### Suspension and the coroutine transform

**Status: implemented (designs 44/45/52/52b, extended through 104).** How a
suspending function is turned into a resumable state machine: the mechanism
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
- **Scope-end release: a driven body destroys where its sync twin destroys.**
  A local that lives across a suspension is held in a frame field, but its
  lifetime is still its SCOPE's. It is released at the end of the scope that
  owns it, in reverse declaration order, on every edge by which control leaves
  that scope — falling off the end of the block, `break`, `continue`, and
  `return`, plus the redefinition point of a same-scope redefinition. A loop
  body releases per iteration, before the backedge, so a `File` or a
  `TcpStream` bound inside a driven loop closes at the end of the iteration
  that opened it rather than when the task completes. The frame's own release
  at completion stays, covering the parameters and anything still live at the
  exit.
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
- **The defining module does not restrict embedding.** A suspending function or
  method embeds into a caller's frame whether it was declared in the caller's
  module, in another package, or in std. The three are one rule, and the callee's
  body keeps its own module's meaning across the embed: the names it resolved at
  its declaration — a module-private helper, a private `static`, an overload, a
  trait conformance — resolve to the same things after it has been embedded,
  where the calling module cannot see them and has no need to.

  Two mechanisms carry that, and which one applies is decided by whether the
  callee is generic. A **non-generic** callee is embedded from the annotations
  its own declaration check produced: the resolved types, callee symbols,
  suspension points and copy judgments travel with the body, and nothing about
  it is resolved a second time. A **generic** callee is re-checked once per
  instantiation, because its types and its effects both depend on the type
  arguments; that re-check runs in the module where the template was written,
  with the instantiation's concrete type arguments in scope, so a template can
  name its own module's helpers and the caller's types in the same expression.

  A generic template defined in one module and instantiated in another is
  therefore driven, embedded and monomorphized like any other; per-instantiation
  frames are keyed by the mangled instantiation, so two instantiations of one
  template are two frames.
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
  - **Driven-in-place vs spawned.** A held reference is sound only when its
    referent outlives the frame. A function DRIVEN in place may freely hold a
    reference param into the driver's live storage: the driver's caller is parked
    on the drive, so the referent cannot go anywhere. A SPAWNED task's frame is
    boxed onto the run queue and resumed later, so the answer there is the
    EXTENT, not the position: a `&`/`&var` argument at a spawn borrows its root
    for the task's life and the handle carries that borrow, which is what keeps
    the spawner's storage alive underneath it. See *A task may borrow from the
    frame that spawned it* below. A reference to a task-CONFINED local INSIDE the
    spawned body needs none of that — it points into the task's own frame, which
    the box keeps alive. A `threads: N` group refuses a reference parameter
    outright, on `Send`.
  - Container-internal borrows (`Vector.with_ref`/`with_var_ref`) keep their
    `sync`-body restriction: unlike a confined stack/frame referent, a container
    borrow projects into shared, reachable storage that a concurrent task could
    reallocate across a suspension, so it may not span one.
- **`deinit` may not suspend** — a `deinit` is always a `sync` context, so a
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
  a generic instantiation can be `__saw_drive`n, `TaskGroup.spawn`ed, or driven as a
  `&var self` method through the ordinary (non-generic) machinery. A `sync`
  context that calls an instantiation which suspends is the normal sync
  violation, reported **at the call site**, naming the instantiation and the full
  suspension path (e.g. `run$1$Slow → Slow.step → __saw_suspend`). Trait-object
  (`any Trait`) dispatch takes its effect from the **declared** trait method
  signature (a `sync` trait method stays sync-callable through `any`), not from
  a per-instantiation re-inference — erasure has no concrete `T` to re-infer.
  **A suspending conformance body may not be reached through `any Trait`.** A
  suspending call embeds the callee's frame by value, so the caller must know at
  compile time which body it is embedding, and an erased receiver carries a
  vtable word instead. Dispatching through `any Trait` to a trait method that
  some type implements with a suspending body is a compile error at the
  dispatch:

  ```saw
  trait Greeter { func greet(&self) -> String }

  extension Person: Greeter {
      func greet(&self) -> String { yield_now()  self.n }
  }

  func shout(g: &any Greeter) -> String {
      g.greet()
      // error: cannot dispatch through `any Greeter` to `greet`: `Person`
      //   implements it with a SUSPENDING body, and a suspending call needs
      //   the callee's frame at compile time — dynamic dispatch has only a
      //   vtable word, so there is no frame to embed and nothing to drive
  }
  ```

  The two ways to write it: call the method on the concrete type, or take the
  receiver as a generic `<T: Greeter>`, which monomorphizes and keeps the frame
  identity. Treat this as refused now and SUSPECT in older builds, where it
  compiled, ran, printed the right answer and never suspended — no frame was
  built anywhere in the program, so the `yield_now()` inside the conformance
  body ran outside a frame, where it is a no-op.
  Driven methods on *generic structs* (`__saw_drive(b.run())` for `b: Holder<Int>`,
  design 74 shape 2) and *nested suspending generic calls* from a driven body
  (design 74 shape 3) are also supported: a generic-struct method is monomorphized
  over the struct's type params so the frame's receiver pointer gets a concrete
  layout, and a nested suspending generic call is promoted to a concrete spliced
  callee embedded as a sub-frame by value (keyed by its mangled instantiation).
  The generic-struct method embeds from an ordinary driven body as well as from
  a `__saw_drive` root — the instantiation is built at either position — and so
  do the other two receiver shapes a method can have: a method on an **enum**
  extension, and a method that **satisfies a trait requirement**. All three work
  in the entry module and across a module boundary. In builds before design 223
  the enum receiver was a codegen failure, the generic-struct receiver in the
  embedded position compiled as an ordinary function that never suspended, and a
  suspending conformance method was reported as not implementing the requirement
  it plainly implements.
  The defining module does not matter (design 104 item 2, shape 4): the
  pristine-template capture spans every module checked in the compilation unit, so a
  generic suspending free function or generic-struct method defined in module A is
  driven / nested-driven from module B at any instantiation.
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
- **Expression position (design 120).** A suspending call may appear anywhere an
  expression may: a chain head or a later hop (`a().b().c()`), a call argument or
  receiver, an operator operand, a collection/tuple/struct-literal element, a
  string interpolation, a `return` value, a `try!`/`try?`/`try … catch` subject, a
  `?.` hop, and a cooperative `Channel.receive()`. The transform rewrites the
  statement into evaluation-ordered temporaries (`let __t1 = a()`,
  `let __t2 = __t1.b()`, …) and embeds each step with the statement-level
  machinery above, so evaluation order, the deinit timing of the intermediates,
  and the ownership rules are the ones the hand-unchained spelling gets. A
  side-effecting sibling written BEFORE the suspension is lifted along with it,
  in source order, so it still runs first: `add(noisy(1), slow(3))` prints
  `noisy` then `slow`, and `add(v.pop()!, slow(v.len()))` reads the length the
  pop left behind. The filter is conservative. A literal, and a plain read of a
  name, field, tuple element or index, stay where they are written; anything
  containing a call or a `&var` borrow is lifted. A `move` operand and a closure
  literal stay put as well, the first because retiring a binding has nothing to
  order and the second because binding a closure to a temp would make it
  escaping. Each temp keeps its subexpression's own line and column, so a
  transfer checkpoint or diagnostic still reports where the argument was
  written. A
  position that is evaluated CONDITIONALLY keeps its guard: a value-position
  `if`/`match` arm, a `??` RHS, an `&&`/`||` RHS, a `?.` hop, and a
  chained-assignment RHS lower to the branch shape first, so an arm that is not
  taken never runs its suspension or its side effects. The guard holds at any
  nesting depth (design 133): a short-circuit buried in a larger expression —
  `f(a ?? slow())`, `return 1 + (a ?? slow())`, `not (a && slow())` — is lifted
  to its own statement, which is that same branch shape, so the operand the LHS
  decides against still never runs. A blocking `extern` call (below) rides the
  same rewrite, including when it is buried in a larger expression.
  Two more positions belong to that list and were refused until Aug 21. A
  destructuring `let`'s right-hand side takes the rewrite in both spellings, a
  tuple literal of suspending calls and a suspending call returning a tuple:
  ```saw
  let (head, rest) = (try! ch.receive(), try! tally.receive())
  let (width, height) = measure()          // `measure` suspends
  ```
  And so does the returned value of a `Result`-returning function, which the
  auto-wrap turns into a wrapped value before the transform sees it:
  `return read_len()` at `-> Result<Int, IoError>` works, at the Ok side, the
  Err side, and the erased `Box<any Error>` side alike.
  One more thing was wrong in a driven body rather than refused: an argument
  that auto-wraps into a `T?` or a `Result<T, E>` parameter lost its wrapper
  when the transform moved it, so `ch.send(count)` on a `Channel<Int?>` inside a
  driven body was a compiler crash reporting a type mismatch at the author's
  line. Treat all three as working now and SUSPECT in older builds.
- **Container head position (design 224).** A control-flow construct also
  evaluates one expression OUTSIDE all of its blocks, and a suspending call may
  sit there too: an `if` or `while` condition, a `for` range (either endpoint),
  a `match` scrutinee, an `if let`/`guard let` subject, and an `&&`/`||` RHS
  inside any of them. Five of the six heads are evaluated once, before the
  construct branches, so each is lifted to a binding ahead of it. A `while`
  condition is evaluated before EVERY iteration, so it is lifted to the top of
  the loop body instead: the loop runs as many times as the condition's
  successive answers say, a `continue` re-evaluates it, and a `break` in the
  body still leaves the loop.
  ```saw
  func drain(ch: Channel<Int>, tally: Channel<Int>) -> Int {
      var served = 0
      while (try! ch.receive()) > 0 {     // the condition suspends, once per iteration
          served += try! tally.receive()  // a compound assignment's RHS suspends
      }
      return try! ch.receive()            // and so does a `return` of a receive
  }
  ```
  A compound assignment's RHS and a `return` of a cooperative
  `Channel.receive()` take the same rewrite. Before design 224 none
  of these positions was embedded OR refused, which is the one outcome the
  cooperative contract does not allow: a channel receive there spun at 100% CPU
  and never completed, and a suspending free function or method reached codegen
  as a call to a body the transform had already split into resume bodies. Treat
  all of it as working now and SUSPECT in older builds.
  One boundary stays: a `while` in VALUE position whose condition suspends is
  refused with a clean error at the call, because a value `while` produces its
  result through a `break <value>` and a value-producing `break` out of a
  suspension-spanning loop is itself unsupported (below).
- **Error handling across a suspension (design 196).** Every spelling of the
  error surface works in a body that suspends, at the same tiers it works in a
  sync one.
  - A propagating **`try`** returns the error from the function. In a state
    machine that means storing the `Result` into the frame's slot and finishing,
    so `let chunk = try stream.read()` in a task body reports the failure to the
    caller instead of panicking (`try!`) or losing the cause (`try?`). It may
    sit in a `return` or a block tail, and in a CONTAINER HEAD — an `if let` /
    `guard let` / `while let` subject, an `if` or `while` condition, a `for`
    range endpoint, a `match` scrutinee — which is what makes the non-blocking
    drain loop `while let job = try ch.try_receive() { … }` write the same way
    in a task as in sync code. Both were refused before Aug 22 (a `return` until
    DF-244a, a head until DF-245d), naming `Poll` — a type the source never
    mentions — or failing as an internal error, so `try!` was the workaround and
    an older build still needs it.
  - A **`try { … } catch { … }` block** may suspend anywhere inside it. The catch
    arm becomes a resume target of its own, reachable from every state the try
    body lowers into, so a statement after a `try` runs only if the earlier one
    succeeded and the caught error survives the transition in a frame field. The
    block works in statement position and in value position (`let r = try { … }
    catch { … }`, or as the body's tail expression), in a driven and a spawned
    body alike, nested in another block, and inside a loop whose `break` and
    `continue` still reach the enclosing loop.
  - An **erased `Result<T, Box<any Error>>`** returns and propagates across a
    suspension, boxing a concrete error at the return edge or re-boxing one at
    the propagation edge, and a function returning one is spawnable.
  ```saw
  func fetch(stream: &var TcpStream) -> Result<Data, IoError> {
      let head = try stream.read()      // suspends; a failure returns Err here
      try stream.write("ok")
      return move head
  }

  func serve(stream: &var TcpStream) -> Int {
      var served = 0
      try {
          let body = try fetch(&var stream)   // the catch arm is a resume target
          served = body.len()
      } catch {
          print("dropping connection: {error}")
      }
      served
  }
  ```
- **Not yet supported** (rejected with a diagnostic anchored at the user's source
  line, not miscompiled): a
  suspension-spanning `if let`/`guard let` with a *tuple pattern*; a **nested** generic call
  whose template suspends *unconditionally* without calling a type-param method
  (`func g<T>(x: T) -> T { yield_now(); x }` called nested — its instantiation's
  effect node is not built; drive it directly with `__saw_drive`/`spawn` instead — a
  same-module limit, orthogonal to the module boundary); a suspension inside a `for`
  over a non-range iterable; a value-producing `break` out of a suspension-spanning
  loop; a chained assignment through MORE THAN ONE optional hop whose RHS
  suspends (`a?.b?.c = stream.read()` — the single-hop form works; bind the inner
  optional with `if let` first); and a suspending `try { … } catch { … }` block
  whose try body raises TWO OR MORE distinct error types, where the catch would
  bind a union the split lowering cannot build (write one block per error type,
  or handle each call with an inline `try <call> catch { … }`).

**Suspending `main` and the cooperative executor (design 45 items 1 & 4).** The
real cooperative primitives are `yield_now()` (suspend and become immediately
re-ready) and `sleep(d)` (suspend with a timed wake). Both are inferred
suspension points. **`yield_now` requires importing std.task** (design 114): it
is std.task's public `func yield_now()`, the one explicit cede a pure-compute
task loop needs; a task doing I/O yields implicitly when it parks, so most code
never names it. Write `import std.task.*` (or `import std.task.{yield_now}`) to
call it bare, or `import std.task` and write `task.yield_now()`. The bare name
is otherwise a stdlib-internal intrinsic, and calling it without the import is a
clean error naming the three forms.
(`sleep` stays in the prelude, and so does the `Duration` it takes.) When `main`
transitively reaches one, the compiler infers
`main` suspending and auto-wraps it in an **entry executor** with no user-visible
plumbing: `main` becomes a frame + `resume`, and the generated entry drives it to
completion on a single cooperative run, parking the thread for each `sleep` wake
and resuming at once for each `yield_now`.

**Multi-task cooperative concurrency — `TaskGroup` (design 52b).** The
heterogeneous run queue is now built on `any Trait` erasure (design 51): every
coroutine frame is compiler-synthesized to conform to the `Resumable`
trait (`std.compiler.frame`, below) — `resume(&var self) sync -> Poll`
(advance one step; `resume` is the
anti-suspension boundary, so it is `sync`) plus `wake_reason(&self) sync -> Int`
(the wake surface: `0` = ready/yield, `>0` = sleep that many nanoseconds) and
`release(&var self) sync` (drop what the frame still owns). A frame boxed as
`Box<any Resumable>` lets distinct frame types share one queue,
`Vector<Box<any Resumable>>`.

- **`TaskGroup`** is a local nursery. `group.spawn(f(args)) -> Task<T>`
  lowers like `__saw_drive`: `f` becomes a spawnable root (frame + `Resumable`
  conformance), and a synthesized `__spawn_f` helper builds the frame, erases it
  into a `Box<any Resumable>`, enqueues it, and returns a typed handle. A `Void`
  task is fine too: it returns a result-less `VoidTask` (design 102 item 1).
  `spawn` works through a shared reference to the group, and enqueueing mutates
  the queue through it. That is safe for a different reason than `Channel.send`'s
  (which is `Sync`, lock-backed for true parallelism): a `TaskGroup` is `NoMove`
  and not `Send`, so it is pinned to its owning thread — every `spawn` and
  `wait` runs on one thread, interleaved cooperatively, and mutation through
  `&` cannot race. Under `threads: N` the worker handoff rides the group's
  internal run-queue mutex; the user surface stays single-threaded. A task may
  spawn siblings onto its own group while the group is being driven, and no
  `var` binding is required.
  A group joins its children where its OWNER drops, and the owner may live on
  the heap: `NoMove` forbids relocating an established group, not constructing
  one directly into a `Box` (`Box<TaskGroup>.make(TaskGroup())`), and a
  `Box`- or `Arc`-owned group is intended — the scope a group defines for its
  tasks is its ownership extent, not a lexical block. The join point is
  deterministic in every case (deinit at the final owner's release, on the
  owning thread), but for a heap-owned group it is dataflow-determined: the
  function releasing the last handle drives the group's remaining tasks to
  completion there, whether or not its text mentions the group. A task that
  never completes blocks that join wherever it is — the same property a
  stack-local group's scope-end join already has; `Task.cancel()` is the
  tool for ending one early.
- **One function, several roles.** A function may be spawned, `__saw_drive`n and
  embedded as another frame's sub-frame in the same program. The spawn role
  reaches its result and cancel word through the group-owned cell (`__cellp`)
  while the other two keep both in the frame, so a function carrying a spawn role
  and any other one gets a second frame: the transform synthesizes
  `f$spawnroot(<params>) -> T { return f(<params>) }` and spawns that, leaving `f`
  a single driven-flavour frame that every other role shares. The cancel word
  propagates down the trampoline and the result threads back up through the
  ordinary sub-frame machinery. A spawn-only root is its own spawn frame and
  gains neither a field nor a hop.
- **The scheduler** is ambient and per-thread (design 89-b): spawned frames enter
  the thread's shared run queue and run EAGERLY — whenever the scheduler runs, not
  only at `join`. A group is a membership/lifetime scope, not a private executor:
  its `join`/`Deinit` drive the shared queue until the group's own members
  finish, honoring wake reasons — `yield_now` requeues immediately, `sleep(d)`
  is scheduled earliest-deadline over relative sleeps, and a channel wait parks
  until a send. When nothing is runnable the scheduler parks in the reactor with
  the earliest deadline as its timeout, whether anything is waiting on an fd or
  not, so a cancel arriving mid-nap is observed then rather than at the deadline;
  a cancelled sleeper is made runnable and takes its cancel path on resume. The drive loop is `sync` (built from `resume`), which is what
  lets the group's `Deinit` run it. A multi-threaded `TaskGroup(threads: N)`
  keeps its own queue and its own live worker pool instead (design 75/225).
- **`Task<T>`** owns nothing. It records the task's `(slot, generation)` in
  its group plus raw pointers into that task's group-owned CELL, which holds the
  result and the cancel word (design 134). The cell is not part of the frame and
  outlives it. `join()` drives the group (a multi-threaded group's pool is
  already running it, so there it WAITS instead) then TAKES the result exactly once,
  leaving `None` behind, and the caller owns that value outright: it stays valid
  after the task is gone. Dropping an unjoined handle is fine — the result stays
  in the cell and is dropped once at group teardown, exactly-once either way.
- **Eager per-task destruction (design 124).** A task's owned values are released
  when THE TASK completes, not when its group is torn down — and an owned value
  whose SCOPE ends earlier is released there, exactly as in a sync body (see
  "Scope-end release" above). Params and the locals still live at the exit are
  frame fields, so the transform emits a `release` at
  every `return Done` site: it drops them in the same LIFO order an ordinary
  function's scope exit uses, including a frame-resident nested `TaskGroup` (whose
  own children are structured-joined first). The single exception is the result
  slot, which is what `join()` moves out — or, unjoined, what the frame drops once
  at group teardown. So a group is a lifetime SCOPE, not a lifetime extender: a
  handler task's `TcpStream` closes its fd when the handler returns, an
  `accept`-loop server reclaims each connection as it finishes rather than
  accumulating them, and a task that reads to EOF sees it as soon as its sibling
  writer completes. A cancelled-then-completed task takes the same path.
- **Task slot lifecycle (design 134).** The frame ALLOCATION is reclaimed on the
  same schedule as the values inside it. When a task reports Done the scheduler
  releases its frame box outright, and the slot it occupied — the run-queue entry
  and its scheduler bookkeeping — goes on the group's free list for the next
  `spawn` to claim. A group therefore costs O(live tasks + tasks whose result
  nobody has joined) rather than O(tasks ever spawned), so a long-running server
  no longer grows in task count. `group.count()` reports the slots held.

  What made this possible is that nothing points into a frame any more. The
  result and the cancel word live in a per-task CELL the group owns, allocated at
  spawn beside the slot; the cell is typed (it holds a `T?`) but the group holds
  it erased, so the group never names `T` and the box teardown still runs the
  right deinit. A `Void` task's cell holds only the cancel word, so its slot
  is reclaimed at completion; a task with a result keeps its slot until `join`
  takes the value.

  Reuse is safe because a handle is an `(index, generation)` pair. Each slot
  carries a counter that advances when the slot retires, so a handle to a task
  that has come and gone is recognisably STALE and every handle operation checks
  before it acts. The outcomes are defined, never a read of whatever occupies the
  slot next: `Task.join` panics ("this task's result was already joined")
  because it cannot invent a second result, `VoidTask.join` returns (the
  task is finished, which is what the call was asking), and `cancel` is a no-op
  on both. `cancel_addr()` is the one exception to reuse: the raw address it
  hands a peer must outlive the task and carries no generation for the peer to
  check, so taking it PINS the slot — that slot keeps its cell and is never
  handed out again, while its generation still retires normally.
- **Structured join = LIFO destruction (design 18 C1).** The group's `Deinit`
  runs the executor to completion of every child, then tears each frame down.
  Because the group is declared before the resources its tasks use and before its
  own handles, LIFO destroys it *first* — draining children while those resources
  are still alive — and handles die before the frames they point into. Task
  frames are self-contained (spawn strips references, paper 18), so no scope
  ordering hazard arises. NO forced destroy anywhere.
- **Cancellation** is cooperative (design 18 C1). `handle.cancel()` sets the
  `__cancel` word in the task's cell through the handle's raw pointer; task code
  reads it with `cancelled()` (rewritten to the same word) and returns through
  normal control flow — frame locals drop exactly once. There is no forced
  destroy and no implicit cancellation at suspension points. Cancelling a task
  that already finished and was reclaimed is a defined no-op.
- **Implicit yield + the cooperative fairness budget (designs 89-b/89-c/127).** A
  suspending call IS a yield point: when a read / accept / sleep / channel-receive
  PARKS (would-block / empty / deadline-not-reached) it cedes to the scheduler
  automatically, so a task doing real I/O never needs an explicit `yield_now`
  (and a call that has data ready returns WITHOUT parking — no spurious yield).
  Two ways a task can still fail to cede are bounded by the same cooperative
  **op-count budget** (default 128). It is an OP-COUNT, never a wall-clock read:
  kernel-friendly, and DETERMINISTIC, so tests may assert exact interleavings.
  Both forms force the same `yield_now` (park-and-immediately-reschedule, wake
  reason 0) and then reset the budget; there are no signals and no new language
  surface.
  - **Always-ready I/O (design 89-c).** A task that keeps completing suspending
    io ops without ever PARKING — a socket that always has bytes — charges each
    non-parking op against a process-global budget. The io primitive itself
    force-yields when the budget runs out. A genuine park resets it too.
  - **Pure compute (design 127).** A task that makes no suspending call at all
    charges every LOOP ITERATION against a frame-resident counter, and the loop
    force-yields when that runs out. `while true { n = n + 1 }` in a spawned task
    cedes on its own; no `yield_now` is needed. A body that would otherwise have
    compiled as a straight sync run-to-completion frame becomes suspending as a
    result, which is how it gains a place to yield.

  The compute check goes at the TOP of each loop body (so a `continue` reaches it
  too) in the task's own body, in the suspending callees the compiler embeds into
  it, and in a suspending `main`. Four bounds, each deliberate:
  - a SYNC callee is not instrumented, so a compute loop inside a never-suspending
    helper called from a task stays unpreempted. Put the loop in the task, or give
    the helper a `yield_now` (which makes it suspending);
  - a `for` over a COLLECTION (`for x in v.iter()`) is not instrumented, and
    neither is any loop nested inside one — only a range `for` can be state-split.
    Write it as a `while` over an index if the loop is long enough to matter;
  - a CLOSURE body is not instrumented (a closure is not driven, so a yield there
    would do nothing);
  - std's own io loops keep the 89-c charge rather than carrying both.

  Cost: a wrapping decrement and a branch per iteration, plus the larger effect
  that the loop it guards joins the frame's state machine (its variables become
  frame fields). Measured at 1.53x on a maximally tight arithmetic loop (200M
  iterations of an LCG step, arm64). Loops outside task bodies are untouched.
- **Suspending channel receive (design 62 G3, design 230).**
  `Channel.receive() -> Result<T, ChannelError>` is the first-class cooperative
  suspending receive: it dequeues a value if ready, else PARKS the *task* (not
  the thread) until a send or a `close()` on that channel wakes it. The coro
  transform lowers each `let v = ch.receive()` / `ch.receive()` call site INLINE
  into a non-blocking-attempt + park loop against the caller's own frame (no
  callee frame — so no generic-method-frame gap); `try_receive()` remains
  available for a hand-rolled loop.
  **A parked receive observes cancellation.** `receive` checks at its loop top,
  ahead of the queue read, and answers `Err(Cancelled)` — so `h.cancel()` on a
  consumer waiting for a message ends it, exactly as it ends one waiting on a
  socket. A cancelled receive dequeues nothing.
  **The park carries the channel's identity.** The wake reason a parked frame
  records is the negated address of a readiness word the channel maintains, so
  the executor's rule is "resume the frame once the word it named is nonzero"
  and a send wakes exactly the receivers of that channel. Until design 230 the
  wait suspended READY and the scheduler re-queued it as fast as it could spin:
  a sole waiter cost 100% of a core, two multi-threaded workers 143%. Treat a
  0%-CPU channel wait as working now and SUSPECT in older builds.
  NAMING: the cooperative method is `receive`;
  the 21b thread engine's blocking `recv` keeps its name and is untouched (same
  signature `(&self) -> T`, so overloading — which cannot differ by effect —
  cannot distinguish the two). A `receive()` buried in an expression position is
  hoisted to its own statement first (design 120), so `inc(ch.receive()) +
  ch.receive()` takes the two values left to right. **Never call `recv` from a
  cooperative task.** Its block is unbounded, and the thread it stops is the
  executor's — so every sibling task stops with it, including the one that would
  have sent the value. `receive` is the replacement. Nothing rejects the
  call today.
- **Disconnection is EXPLICIT: `close()` (design 230).** A channel handle is a
  unified `Copy` handle with no sender/receiver role split, so "the last sender
  went away" is not something the type can count — a waiting receiver's own
  handle keeps any refcount nonzero forever. Saying so is the mechanism:

  ```saw
  public func close(&self) -> Result<Void, ChannelError>
  public func send(&self, v: T) -> Result<Void, ChannelError>
  public func receive(&self) -> Result<T, ChannelError>

  public enum ChannelError {
      case Closed,
      case Cancelled,
      case Alloc(e: AllocError)      // design 234 §1: carry the leaf
  }
  ```

  Any holder may call `close()`; by convention the producer does, after its last
  message. Every parked receiver is woken. A receive DRAINS what is already
  queued and only then reports `Err(Closed)`, so closing a channel with messages
  in it loses none of them. A send after a close is `Err(Closed)` and does not
  enqueue. A second close is `Err(Closed)` rather than a panic, so a close that
  races another one is idempotent to ignore with `let _ =` without being silent.
  `Err(Cancelled)` is the other answer a `receive` can give: the waiting task was
  cancelled, nothing was dequeued, and the consumer loop ends the way a cancelled
  socket read ends. `send` and `close` never report it — neither waits.
  `Err(Alloc(e))` is the third: the allocator refused the queue node a `send`
  needed, and the case CARRIES the `AllocError` rather than restating its
  vocabulary, which is design 234 §1's rule for a compound domain enum. It
  renders through the leaf — `the channel could not allocate a queue node:
  allocation of 64 bytes (align 8) failed`.
  `ChannelError` is an enum because a receive TIMEOUT is the other legitimate way
  one of these calls can fail to deliver; that case is reserved, not yet built.

  ```saw
  func consume(orders: Channel<Order>) -> Int {
      var handled = 0
      var going = true
      while going {
          match orders.receive() {
              case Ok(order) -> {
                  fulfil(order)
                  handled = handled + 1
              },
              case Err(_) -> { going = false }   // the producer closed the channel
          }
      }
      return handled
  }
  ```

  There is NO automatic close when the last handle drops, which is the same
  point restated: roles are uncountable, so there is no last handle to key on.
  A channel nobody closes and nobody sends to is a deadlock, and the executor
  reports it (below) rather than waiting forever. A split
  `Sender<T>`/`Receiver<T>` surface, which would make disconnection automatic
  again, is recorded as future work.
- **The quiescent deadlock report (design 230).** When every live task is parked
  on a channel, no io is registered, no timer is pending, nothing is runnable and
  no unjoined `Thread.spawn {}` body exists, nothing in the process can ever
  run again.
  The executor reports that state and aborts, printing the task dump after the
  panic line so the parked-on-what is visible:

  ```
  panic at taskgroup.saw:1977: deadlock: every task is waiting to receive from a
  channel, and nothing in this program can send. ...
  saw tasks: 1 live (as-of panic, unsynchronized)
    task group 1 slot 0 gen 1 channel-parked
      at worker.saw:5 in consume
  ```

  The report is decided by elimination, never by counting resumes: design 127's
  op budget force-yields a long computation exactly the way a permanent wait
  presents, so a "resumed N times with no progress" heuristic would abort correct
  programs. The state is read twice with a nap between, because the walk is
  unsynchronized and an abort is not a diagnostic. `close()` is the cooperative
  path and this is the backstop; a program that closes its channels never reaches
  it.

**Multi-threaded execution — `TaskGroup(threads: N)` (design 75 A2, rebuilt as a
live pool by design 225).** By default a `TaskGroup()` runs its children on ONE
thread (deterministic interleaving, above). `TaskGroup(threads: N)` (`N >= 2`)
opts a group into a MULTI-THREADED executor: N OS worker threads serve a single
mutex-protected SHARED run queue (the sanctioned "one injector + N workers" —
simplicity over per-worker lock-free deques, v1). `TaskGroup()` and
`TaskGroup(threads: 1)` stay byte-identical to the single-threaded engine (no
threads, no lock).
- **The pool is live.** The N workers start at the group's FIRST spawn and run
  until its `Deinit`, so a task spawned into a multi-threaded group begins
  immediately and runs alongside the thread that owns the group. A worker LOCKS
  the queue, claims the first runnable frame by moving its box out of the slot,
  UNLOCKS, `resume()`s it, then re-locks to put it back and record the outcome;
  an idle worker parks on a condition variable beside the queue lock at no CPU
  cost, and a group that never spawns starts no thread.
- **`join()` waits; `Deinit` retires the pool.** `handle.join()` waits for that
  one task and returns its result, leaving the workers running — so repeated
  spawn-and-join into one group costs N threads in total, not N per join. A
  group's `Deinit` signals that no more work is coming, lets the workers finish
  every live task, and joins them; that is the structured join, and it is still
  exactly-once and idempotent.
- **What is observable, and what changed.** Multi-threaded execution order was
  never deterministic. What a live pool widens is WHEN that is visible: a task's
  effects — a channel send, an `Arc<Mutex<T>>` update — now become visible to the
  owning thread at an unspecified point between the spawn and the join, where
  before nothing of a multi-threaded group had happened until a `join()` or
  `Deinit` and all of it had happened after. Three things did not change:
  `join()` is a barrier for the task it names, `Deinit` is a barrier for the
  whole group, and `TaskGroup()` / `threads: 1` remain the deterministic
  single-threaded engine. So a program may still rely on results through handles
  and on shared state through `Arc`/`Mutex`/`Channel`; what it may not rely on is
  a `threads: N` group not having started yet.
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
- **Fairness across threads.** The op-count backstop is PER-THREAD: each worker,
  and the thread running the ambient scheduler, gets its own count of
  non-parking io ops before it is made to cede. The loop-backedge budget that
  covers pure-compute tasks is frame-resident, so it is per-task already.
- **Shared timer / cancellation.** Sleeps advance by the earliest deadline under the
  queue lock (a shared timer, no per-worker wheel). Cross-task cancellation:
  `Task.cancel_addr() -> Int` yields the `__cancel` word's address (a `Send`
  `Int`) so a canceller task can set it from a worker thread; the target observes it
  via `cancelled()` (the `__cancel` byte is set-once monotonic — race-free,
  eventually consistent, cooperative). The word is in the task's cell, which the
  group keeps alive, so a write that lands after the task finished is inert rather
  than undefined; taking the address pins the slot (design 134, above). The 21b
  OS-thread `Thread.spawn`/`Thread<T>`/`Channel.recv` engine is separate and
  untouched — the two engines coexist.

Now-closed gaps (design 62), each landed with tests:
- **`if let` / `guard let` over a suspending call (G2).** `if let x = f() { ... }`
  / `guard let x = f() else { ... }` whose condition is a plain suspending call is
  supported: the transform hoists the condition into a preceding driven temp
  (`let __t = f()`) and binds over it. The hoisted `T?` temp uses the `self_opt`
  frame encoding (an already-optional field is stored as-is, not double-wrapped).
  Only the plain-call form is hoisted — a move-in-condition remains a clean error.
  `while let` (Control Flow) takes the same hoist once per iteration, since its
  scrutinee sits inside the loop body.
- **`TaskGroup` inside a suspending function (G1).** A `TaskGroup` may be a direct
  frame-resident local of a suspending function: the group + its erased run queue
  are frame state, and `group.spawn(...)`'s `&group` resolves to an addressable
  frame field (plain-encoded, real empty-`TaskGroup()` placeholder). The group's
  `Deinit` still drives its members to completion during normal frame cleanup
  (including across a parent suspension between spawn and drop); nested groups
  compose on the one ambient scheduler (design 89-b — a joining task yields to
  it, no re-entrant drive loop); cancellation words are frame-resident and
  reachable.

Remaining limits (rejected cleanly / documented, not miscompiled): the
design-104-era list in the Suspension section above — a suspension-spanning
`if let`/`guard let`/`while let` with a tuple pattern, and a nested generic call whose template
suspends unconditionally without calling a type-param method. Earlier restrictions
— a spawned function had to be non-`Void`, a nested suspending *method* was not
embeddable, an `if let`/`guard let` body could not span a suspension, a suspending
call could not sit in a larger expression, and such a body could not re-bind the
bound name — were lifted (designs 102 item 1, 84/101, 104 item 1, 120, and the
per-binding frame fields described below).

Two bindings in one suspending body may share a name. Each keeps its own storage
across a suspension, whether they nest (a design-100 derived shadow such as
`if let x = x`), sit in disjoint scopes (a `match` arm binding and a later local),
or belong to different arms of one `match`. The frame carries one field per
binding, not per name; the compiler renames the colliding ones internally, so
nothing about this is visible except that the values are right.

The transform is also still exercisable through a test-only entry: `__saw_suspend()`
marks a synthetic suspension point and `__saw_drive(f(args))` / `__saw_drive_steps(f(args))`
/ `__saw_drive(recv.m(args))` create a frame and step it to completion. A function or
method is transformed only when it is driven (or is a suspending `main`); code
that drives nothing is compiled exactly as before.

A drive site may not appear in a body that itself suspends, and writing one is a
clean compile error naming the direct call instead. A suspending body already
runs inside an executor, so a suspending call there simply embeds — there is
nothing for a second root to buy, and running one would need nested-executor
semantics (fairness, the op budget) designed for a spelling only tests write.

### Tasks and Channels

```saw
// Spawn an OS thread (escaping closure; every capture must be Send)
var worker = Thread.spawn {
    heavy_computation()          // returns Int
}
let result = worker.join()       // Thread<Int>: NoCopy. The join is required —
                                 // dropping the handle is a compile error

// Channels: Copy handles onto a shared queue
let ch = try! Channel<Int>()     // Channel<T: Send>; the queue allocates
var producer = Thread.spawn { [ch] in
    try! ch.send(42)             // send/receive/close report through Result
    true
}
let got = ch.recv()              // blocks the calling thread (the thread
                                 // engine's receive); the cooperative twin is
                                 // the suspending receive() (below)
let _ = producer.join()
```

#### No implicit fates

The result of `Thread.spawn { ... }` must reach `join()` or `detach()` on every
path out of the scope that binds it, and the result of `Task.spawn(...)` must
reach `join()`, `detach()` or `cancel()`. Both discard spellings are compile
errors, including the `let _ =` that discards a `Result`:

```saw
Thread.spawn { crunch(n) }
// error: `Thread.spawn` hands back a `Thread<Int>` that must be consumed,
//        and this one is discarded

var t = Thread.spawn { crunch(n) }
if urgent { let _ = t.join() }
// error: `t` holds a `Thread<Int>` that is never consumed: it was spawned at
//        line 1 and reaches the end of its scope with no `join()` or `detach()`
//        on this path
```

The check is per-path: a `join()` inside a branch settles that branch and no
other, and a `return` is an exit like any other. `Thread.spawn { ... }.join()`
consumes the handle where it is made, which is the wait-here spelling.

Two things discharge the obligation besides a written `join()`. One is a move
into storage whose owner consumes the handle in its own `deinit`; the compiler
asks only that the owning type DECLARE a hand-written `deinit`, which is how a
worker pool outlives the function that starts it:

```saw
import std.task.{VoidThread}

struct Pool { workers: Vector<VoidThread> }

extension Pool: NoCopy {
    func deinit(&var self) {
        while self.workers.len() > 0 {
            if let held = self.workers.pop() { var h = move held  h.join() }
        }
    }
}

extension Pool {
    func start(&var self, count: Int) {
        var i = 0
        while i < count {
            var t = Thread.spawn { serve() }
            try! self.workers.push(move t)   // discharged: `Pool` declares a deinit
            i = i + 1
        }
    }
}
```

The other is `group.spawn`, whose handles carry no obligation at all — a group
is a declared consumer and its `Deinit` is the join barrier, so the accept-loop
idiom (`while true { group.spawn(handle(accept())) }`) needs nothing written.

Because a declared `deinit` is necessary and not sufficient, an owner that
forgets can still reach a thread handle's destructor unconsumed. That path
panics, naming the type and the fates:

```
panic at task.saw:181: Thread was dropped without being joined or detached —
`join()` waits for it and takes its result, `detach()` gives the thread to the
process
```

The handle used to JOIN on drop instead. That made `let _ = Thread.spawn { ... }`
— the natural way to guess at fire-and-forget — a sequential call plus the cost
of a thread, and it made every exit edge of a function holding a handle a
blocking edge, error paths included.

#### `detach()`: the fate that does not wait

`detach()` is the second fate, on both engines. It consumes the handle and
gives the work to the process. Nothing will join it, so its result is given up:

```saw
var worker = Thread.spawn { [job] in compress(job) }
worker.detach()                  // the handle is consumed here

let background = Task.spawn(reindex(catalog))
background.detach()
```

Saying so is the point. Discarding a `Result` takes `let _ =` because throwing
a failure away should be visible where it happens, and `detach()` is the same
statement about a whole unit of work: the value is dropped at one named place
rather than outliving the program in a slot nobody reads.

What each engine promises differs, and the difference is the engines'.

A DETACHED THREAD keeps running. Values it owns deinit when it completes, on
its own thread. If it is still running at process exit the operating system
terminates it wherever it has got to, and nothing it holds is released — the
same boundary a never-completed coroutine frame has, where process death drops
nothing. A thread you need to have finished is a thread you join.

A DETACHED TASK keeps running on the cooperative scheduler, and its result is
dropped when it completes rather than kept for a join that will never come:

```saw
func measure(id: Int) -> Report { ... }

let handle = Task.spawn(measure(7))
handle.detach()
// the Report is built, and dropped, when the task finishes
```

At `main`'s return the background group cancels every member still live and
joins them (below), so a detached task ends there if it has not ended sooner.

`group.spawn` handles take no `detach()`. A group task may borrow from the
frame that spawned it, and the group's scope is what releases that borrow, so
"give it to the process" has no meaning for one — drop the handle instead, or
spawn with `Task.spawn` when the task genuinely outlives its spawner. Calling
`detach()` on a group handle panics.

#### The spawn brace's capture list

A spawn brace captures nothing implicitly. The capture list is the body's
parameter list: each entry transfers at the spawn, by value, at its own copy
tier, and `[move x]` is how a move-only value goes.

```saw
let count = 3
var t = Thread.spawn { crunch(count) }
// error: a spawned brace captures nothing implicitly, and this body names
//        `count`
// hint: name what crosses in the capture list —
//       `Thread.spawn { [count] in ... }`. The list IS the body's parameter
//       list ...

var t = Thread.spawn { [count] in crunch(count) }   // fine
```

Ordinary closures are unaffected: their captures are read at the same frame by
the same thread, and there is no boundary to spell. What the rule buys is that
everything crossing a concurrency boundary is written at the crossing, where
the reader of a spawn site is looking.

#### The thread body

A `Thread.spawn { ... }` body is a `sync` context: a spawned thread runs no
executor, so there is nothing on it to resume a suspension.

```saw
var t = Thread.spawn { yield_now()  7 }
// error: cannot suspend in a `Thread.spawn { ... }` body: closure calls
//        yield_now
```

Suspending work on a dedicated thread is `TaskGroup(threads: 1)`, which brings
an executor with it. Before this rule the body compiled as ordinary sync code —
no coroutine frame was built at all — so a `yield_now()` inside one was a silent
no-op.

One suspension source is permitted, and it is the reason to reach for a thread
in the first place: a `blocking` extern runs DIRECTLY there, blocking the
spawned thread. Design 103's offload — which moves such a call to a worker
thread and parks the task — applies to a suspending body, and there is no task
here to park. An ordinary `sync` body still refuses the same call.

```saw
extern "C" {
    blocking func compress(src: UnsafePointer<Int8>, n: Int) -> Int
}
var t = Thread.spawn { [buf, len] in compress(buf, len) }   // blocks on purpose
let bytes = t.join()
```

### Cooperative tasks: TaskGroup

```saw
// The cooperative multi-task engine (design 52b). Tasks are stackless coroutine
// frames driven on the current thread — no OS threads, no thread identity.
import std.task.*                // design 114: `yield_now` lives in std.task

func worker(base: Int) -> Int {
    print(base)
    yield_now()                  // cooperatively hand control back to the group
    return base + 1
}

func main() {
    var group = TaskGroup()
    let a = group.spawn(worker(10))   // -> Task<Int> (a Void spawn gives
                                      //    a VoidTask, design 102)
    let b = group.spawn(worker(20))
    print(a.join())                   // drive the group; take a's result: 11
    print(b.join())                   // 21
}                                     // group Deinit drains any unjoined child

// A task's owned values die WITH THE TASK (design 124), not with the group, so a
// long-lived group does not accumulate finished tasks' resources:
func handle(conn: TcpStream) -> Int {
    let req = try! conn.read()
    try! conn.write("ok")
    req.len()
}                                     // `conn` deinits HERE: the fd closes when
                                      // the handler returns, not at group teardown
// The result is the one value that outlives the task: `join()` moves it out and
// the caller owns it; an unjoined result drops once at group teardown.

// Cooperative suspending receive over a Channel (design 62 G3, design 230). The
// consumer runs until the producer closes the channel, which is what ends the
// loop: a receive on a closed, drained channel is Err(Closed).
func consumer(ch: Channel<Int>) -> Int {
    var sum = 0
    var going = true
    while going {
        match ch.receive() {
            case Ok(v) -> { sum = sum + v },   // parked while the channel is
            case Err(_) -> { going = false }   // empty, woken by a send or a close
        }
    }
    return sum
}

func producer(ch: Channel<Int>) {
    var i = 1
    while i <= 3 {
        try! ch.send(i)
        i = i + 1
    }
    try! ch.close()                           // without this the consumer would
}                                             // wait forever — see close(), above
// (`try_receive() -> Result<T?, ChannelError>` is still available for a
//  hand-rolled loop, e.g. one with its own `if cancelled() { ... }` on the empty
//  branch. `receive` observes cancellation itself and answers `Err(Cancelled)`,
//  so a hand-rolled loop is a choice now rather than the only way.)

// A TaskGroup may live in a SUSPENDING function's own frame (design 62 G1):
func orchestrate(base: Int) -> Int {
    var group = TaskGroup()
    let h1 = group.spawn(worker(base))
    let h2 = group.spawn(worker(base + 1))
    sleep(Duration.ms(1))                 // the parent may suspend between spawn
    return h1.join() + h2.join()          // and join; the group drains at teardown
}

// OPT-IN multi-threaded execution (design 75 A2): N OS worker threads drain a
// shared queue. Every value a spawned frame carries across a suspension must be
// Send (params, across-suspend locals, and the result). Assert on counts/sums,
// never on the (nondeterministic) interleaving.
func square(n: Int) -> Int {
    yield_now()
    n * n
}
func parallel() -> Int {
    var group = try! TaskGroup(threads: 4)  // 4 workers; `TaskGroup(threads: 1)` and
    let a = group.spawn(square(3))         //   `TaskGroup()` stay single-threaded
    let b = group.spawn(square(5))
    return a.join() + b.join()            // 9 + 25 = 34 (order not observable)
}
//   group.spawn(needsVector(move v))    // fine: `Vector<Int>` is Send, because
//                                        // `Int` is. A `Vector` of closures is
//                                        // not — the ELEMENT decides.

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

#### Background tasks: `Task.spawn`

`Task.spawn(work(n))` starts a cooperative task without a group. It hands back
the same `Task<T>` / `VoidTask` that `group.spawn` does, and the task rides the
same ambient scheduler:

```saw
import std.task.*

func square(n: Int) -> Int {
    yield_now()
    n * n
}

func main() {
    let squared = Task.spawn(square(6))
    print(squared.join())        // 36
}
```

It takes a CALL to a named function, not a brace, and for the reason the
cooperative engine exists: a coroutine frame is built for a named function, and
a background task's whole point is that it can suspend.

THE GROUP IT SPAWNS INTO is one the program never declares. It is built on the
first `Task.spawn` in the process and never before, so a program that spawns no
background task pays one zero word for it. There is no multi-threaded flavour:
`TaskGroup(threads: N)` is how parallelism is asked for.

AT `main`'s RETURN that group cancels every member still live, joins them, and
exits. Cancel first, because a background task is exactly the kind that loops
forever and there is nobody left to ask it to stop; join after, because a
cancelled task reaches its own completion through ordinary control flow, and
that is where the values it owns are released:

```saw
func serve(id: Int) {
    let conn = open(id)
    while true {
        if cancelled() { return }    // `conn` deinits here, on the way out
        yield_now()
    }
}

func main() {
    let worker = Task.spawn(serve(1))
    worker.detach()
    print("main is finished")
}
// main is finished
// (then: the task is cancelled, runs its cancel path, and `conn` closes)
```

A SYNC `main` never yields, so its background tasks first run at that exit join
— by which time they are already cancelled. That is the cooperative model being
itself rather than a special case: a task runs when something cedes to it, and a
`main` that never suspends never does. Give the tasks a `yield_now()`, or join
them, or spawn them from a suspending `main`.

BORROWS ARE REFUSED AT THE FORM. A `&`/`&var` argument of the spawned call, and
a borrow capture in a closure inside it, are both clean errors:

```saw
var buffer: Vector<Int> = []
let filler = Task.spawn(fill(&var buffer, 3))
// error: `Task.spawn` accepts no borrows: `&var buffer` is an argument of the
//        spawned call
```

A group's scope is what ends such a borrow (see *The borrow's extent is the
task's life*), and a background task has no scope: it may be detached, and it
ends at `main`'s return rather than at a scope its root outlives. Spawn into a
`TaskGroup`, or hand the task an owned value, an `Arc` or a `Channel`.

THE HANDLE IS MUST-CONSUME, on the same terms `Thread.spawn`'s is (*No implicit
fates*, above): `join()`, `detach()` or `cancel()` on every path, both discard
spellings refused. `group.spawn` handles are exempt — the group is a declared
consumer — and that exemption is what makes the accept-loop idiom work. One
that escapes the check and reaches its destructor unconsumed panics:

```
panic at taskgroup.saw:1827: Task was dropped without being joined, detached or
cancelled — `join()` waits for it and takes its result, `detach()` hands it to
the process, `cancel()` asks it to stop
```

`Task.spawn` needs a `main` to close its group at, so the freestanding profile
refuses it and names the spelling that works there: a `TaskGroup` the author
declares, whose scope says where the tasks end.

#### A group is a scope, and cannot be moved

`TaskGroup` is `NoCopy` and, since design 188, `NoMove` (see
[The `NoMove` trait](#the-nomove-trait-pinned-types)). A group's
`Deinit` structured-joins its children where the group was born, and every
spawned frame reaches its group through that address, so a group that moved
would join in one place and be driven from another:

```saw
func make() -> TaskGroup {
    var group = TaskGroup()
    let _ = group.spawn(work(21))
    move group
    // error: cannot `move` `group`: `TaskGroup` is `NoMove` … A `TaskGroup` is
    //        a SCOPE (design 124): its `Deinit` structured-joins its children
    //        where the group was born …
}
```

The move used to be accepted and the runtime then aborted (`Vector.get: no place
to lend`). Keep the group in the frame that opened it and pass `&var group` down,
or spawn into a group the caller owns. A struct holding a group must declare
`NoCopy` and `NoMove` itself; to hand out a movable handle over one, put it
behind a `Box`.

#### A task may borrow from the frame that spawned it

There are two spellings and one rule. A borrow **capture** reaches the spawner
through a closure the task runs; a `&`/`&var` **argument** of the spawned call
reaches it directly:

```saw
let h = group.spawn(run({ [&var n] in n = n + 1  n }))   // capture
let g = group.spawn(bump(&var n))                        // argument
```

Both are sound when the borrowed binding is declared **before** its group.
Destruction is LIFO and the group's `Deinit` joins at scope exit, so everything
declared ahead of the group is still alive when the join runs:

```saw
var n = 7
var group = TaskGroup()
let h = group.spawn(run({ [&var n] in n = n + 1  n }))
print(h.join())        // 8
print(n)               // 8 — the task's write is visible at the root
```

Declared **after** the group, that argument inverts: LIFO tears the binding down
first, while the group has not joined, and the task reaches freed storage. It is
a compile error naming the order, in either spelling:

```saw
var group = TaskGroup()
var n = 7
let h = group.spawn(run({ [&var n] in n = n + 1  n }))
// error: cannot capture `&var n` into a task: `n` is declared AFTER the group
//        `group` it is spawned into …, and destruction is LIFO

let g = group.spawn(bump(&var n))
// error: cannot pass `&var n` into a task: `n` is declared AFTER the group
//        `group` it is spawned into …, and destruction is LIFO
```

The group opens the scope it governs, so it is declared at the top of it.

A **`threads: N` group takes neither spelling.** A reference is not `Send`, so
the frame cannot cross to a worker thread; the capture is refused for the same
reason one indirection out (a closure is not `Send` either):

```saw
var group = try! TaskGroup(threads: 2)
let h = group.spawn(bump(&var n))
// error: cannot spawn `bump` into a multi-threaded `TaskGroup(threads: ...)`:
//        parameter `n` of type `&var Int` is not `Send` …
```

Share genuinely cross-thread state through an `Arc`, a `Mutex` or a `Channel`.

#### The borrow's extent is the task's life

A spawn borrow — capture or argument, the same record either way — holds its
root for as long as the task can reach it, and the task's **handle carries that
borrow**. `&var` opens an exclusive borrow of the root and `&` a shared one,
judged by the Law of Exclusivity over that whole window rather than over the
spawning call.

Joining releases. `join()` takes the task's result out of its cell exactly once,
so the release point is statically known and the spawn-join-use order above
stays legal with nothing written to say so. Between the spawn and the join the
root belongs to the task:

```saw
var n = 0
var group = TaskGroup()
let h = group.spawn(run({ [&var n] in n = n + 100  n }))
n = 5
// error: exclusive access violation: `n` cannot be written here — the task
//        spawned at line 3 holds `&var n` until `h.join()` releases it
print(h.join())
print(n)               // fine: the borrow ended at the join
```

An exclusive borrow excludes reads too, not only writes. That is the ordinary
one-writer-XOR-many-readers table applied over a window as long as the task, and
it is what makes the write the task performs unobservable in progress. To watch
a value while a task is still running, share it through an `Arc<Mutex<T>>` or a
`Channel`, where the synchronization is in the types. Shared borrows compose:
two `&x` borrows may be live at once, and the caller may read `x` beside them.

The argument spelling reads the same, and the spawn-join-use order is what a
worker filling a caller's buffer looks like:

```saw
func fill(v: &var Vector<Int>, n: Int) -> Int {
    var i = 0
    while i < n {
        try! v.push(i)
        yield_now()
        i = i + 1
    }
    v.len()
}

var buf: Vector<Int> = []
var group = TaskGroup()
let h = group.spawn(fill(&var buf, 3))
print(h.join())        // 3
print(buf.len())       // 3 — the task wrote through to the root
```

The frame holds a pointer into the caller's storage and owns nothing through it,
so the elements the task pushed are destroyed once, by `buf`, at `buf`'s scope
end. A task's own values deinit eagerly at task completion; a borrowed referent
is not one of them.

A `move` of a borrowed root is the same violation under the move vocabulary,
and it is the case that made this a soundness rule rather than a consistency
one. Before the extent existed, `consume(move buf)` between a spawn and its
join dropped the buffer and the join then drove a task that read the freed
slot — silently, exit 0.

```saw
var buf: Vector<Int> = [1, 2, 3]
var group = TaskGroup()
let h = group.spawn(run({ [&var buf] in try! buf.push(9)  buf.len() }))
let taken = consume(move buf)
// error: cannot `move` `buf` while a spawned task borrows it: the task spawned
//        at line 3 holds `&var buf` until `h.join()` releases it
```

Three cases release later than the join, each conservatively:

- A handle that is **discarded or never joined** holds its borrow until the
  group's death. Nothing joins it earlier: `Task`'s `Deinit` owns nothing
  and leaves the result in the group's cell, so it is the group's `Deinit` that
  drains the task. A handle stored in a field or an element is the same case,
  since there is no binding to recognize a join on.
- A **join inside a branch** releases only on that path, so the borrow is live
  again below the branch. Hoist the join out of the branch to get the root back.
- A borrow still live when a **loop body** ends is refused outright: one textual
  spawn would open a second exclusive borrow of the same root on the next
  iteration. Join inside the body and each iteration's borrow is released before
  the next opens.

`cancel()` does not release. A cancelled task still runs its cancel path, and
the reference is live until it finishes.

### Task backtraces (design 158)

A suspended task is not on any thread's stack, so a native backtrace of a parked
program shows the executor's poll loop and nothing about what the program is
waiting for. `dump_tasks()` prints the missing half: one entry per live task,
with the `file:line` of every suspending call between the task's entry point and
the place it is parked, innermost frame first.

```saw
import std.task.{dump_tasks}

func read_header(s: TcpStream) -> Data { try! s.read() }
func handle(s: TcpStream) -> Int { read_header(move s).len() }
```

```
saw tasks: 2 live (unsynchronized snapshot)
  task group 1 slot 0 gen 1 io-parked
    at net.saw:412 in TcpStream.read
    at server.saw:18 in read_header
    at server.saw:24 in handle
  task group 1 slot 1 gen 1 running
    at server.saw:41 in accept_loop
```

`group` numbers the live `TaskGroup`s in the order they first spawned; `slot` and
`gen` are the task's identity in that group's run queue, and a generation
advancing across dumps is a slot that has been reused. The last word says why the
task is not running: `ready`, `sleeping`, `io-parked`, or `running`.

**The panic path prints one for you.** A program that dies with tasks in flight
writes its dump after the panic line. Nothing is appended when no task is live,
so a panic in a program that is not running tasks reads exactly as it did
before.

Reconstruction is a walk of static tables, not an unwind. A task's frames are
embedded by value inside one allocation at compile-time-known offsets, each
carrying a state word naming its resume point, and the compiler records what
those states mean in a read-only table linked into every binary
(`__saw_bt_table`). So the dump allocates nothing and needs no runtime support:
it works under an exhausted allocator, in the freestanding profile, and inside a
panic handler. `sawc --emit-bt-table` decodes the table as JSON, and
`tools/test_bt_table.py --sizes` reports what it costs.

The walk reads task slots without cross-thread synchronization. In a
multi-threaded group that is a best-effort snapshot and the header says so; a
single-threaded group is exact, since nothing else is running.

**Under a debugger.** `tools/lldb_saw.py` reads the same table out of a stopped
process:

```
(lldb) command script import tools/lldb_saw.py
(lldb) saw tasks     # one line per live task
(lldb) saw bt        # every live task's logical backtrace
(lldb) saw table     # the binary's frame table, decoded (no process needed)
```

It is read-only: it reconstructs where each task is parked, and never steps,
resumes, or decodes a variable inside a frame.

### Cooperative IO: the reactor (design 76)

Unbounded external waits (sockets) never block the cooperative executor. A
process-global **poller** — kqueue on macOS, epoll on Linux — is the reactor: when
no task is runnable the executor blocks in the poller with a timeout equal to the
earliest sleep deadline (never busy-waiting, never blocking while a task is
runnable), and wakes tasks whose fds are ready. That holds even when nothing is
waiting on an fd and the only thing pending is a timer: the poller is where the
executor idles either way, so a cancel arriving mid-nap is observed at the wake
rather than at the deadline.

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
in sight. Errors are `IoError`: the failing operation's name, a portable
`IoErrorKind`, and the platform's own code for the refusal. It conforms to
`Error`, so `"{e}"` renders it as
`io error: connect failed (host unreachable)` — the KIND only, which is what
makes the text read the same on every host.

The two halves answer different questions and design 234 §2 keeps them apart.
`e.kind()` is the branchable half: a curated portable set (`NotFound`,
`PermissionDenied`, `ConnectionRefused`, `TimedOut`, …) ending in `Unknown` for
a failure the vocabulary has no word for. Classification is DIAGNOSTIC, not
contractual — several platform codes fold into one kind, `EACCES` and `EPERM`
both landing on `PermissionDenied` — so correct handling of `Unknown` treats it
as an opaque failure rather than an errno to be worked out. `e.code()` is the
loggable half: the platform's raw number (`ECONNREFUSED` is 61 on macOS and 111
on Linux), `0` where the platform has none, which includes a failure std raised
on its own behalf such as a park cut short by cancellation. Log the code, branch
on the kind. Growth is loud: promoting a code out of `Unknown` into a new kind
breaks an exhaustive match at compile time instead of silently rerouting it.

```saw
// A cooperative echo, entirely over the safe owning API. Failable ops return
// Result (design 92): read gives Result<Data, IoError> — an EMPTY Ok is EOF,
// DISTINCT from Err — and write sends the whole buffer or surfaces the error.
func serve(stream: TcpStream) -> Int {
    let chunk = try! stream.read()        // suspends until bytes arrive; empty Ok = EOF
    let n = chunk.len()
    try! stream.write(move chunk)         // suspends until every byte is sent
    return n                              // stream.Deinit closes the fd here
}

func main() {
    let listener = try! TcpListener.listen(0)         // Result<TcpListener, IoError>
    let stream = try! TcpStream.connect("127.0.0.1", listener.local_port())
    // ... spawn workers over accept()/read()/write() in a TaskGroup ...
}
// TcpStream.pair() gives a connected pair for tests/IPC with no bound port.
```

The design-76 raw layer (`tcp_*` / `net_*` free functions + `io_wait(fd, dir)`, a
`yield_now`-like suspension point that registers+parks on the reactor) still exists
as the PRIVATE implementation std.net's methods drive — it is not part of the public
surface.

**The host argument of `connect` is an IPv4 address or a name.** A dotted quad
(four octets, one to three digits each, no leading zero, nothing else in the
string) is an address already, so it is parsed in Saw and dialled directly:
nothing about a literal caller touches the resolver. Anything else is a name,
and `connect` resolves it before dialling the first IPv4 answer.

Resolution never stops the executor. The runtime seam is `__saw_rt_resolve_ipv4`
over `getaddrinfo`, and it is the only seam in std declared `blocking`: a lookup
can take anything from an `/etc/hosts` read to a DNS timeout, so the call is
offloaded to a worker thread and the calling task parks, the same way a socket
read does. Sibling tasks run while a resolution is in flight. That contract is
enforced rather than documented — `blocking` is part of an extern's contract, so
a second declaration of the symbol without it is a compile error and the
resolver cannot be reached by a call that would hold the executor thread.

A name that does not resolve, and a name whose answers contain no IPv4 address,
are both an `Err(IoError)` naming the host:

```saw
match TcpStream.connect("db.internal", 5432) {
    case Ok(stream) -> serve(move stream),
    // prints: io error: resolve "db.internal" failed (not found)
    case Err(e) -> print("{e}")
}
```

IPv6 is not resolved. The seam is named `_ipv4` and answers a `u32` array so
that a v6 seam is an addition rather than a reinterpretation; happy-eyeballs
needs the dual-stack design first. There is no resolver cache, and no connect
timeout beyond the operating system resolver's own.

Bounded local IO stays synchronous (regular-file read/write) — the never-block
invariant is about latency-UNBOUNDED waits, not IO in general.

**File and directory IO is prompt by policy, and the policy has a cost worth
stating.** Nothing in `std.file` or `std.directory` suspends, so the calling
thread stays inside the system call until it returns. That is deliberate: a
page-cache read costs less than the thread hop an offload would add, and the
freestanding profile has no thread to hop to, so a file API whose correctness
depended on one could not exist there. The cost is that the promise is a property
of the FILESYSTEM, not of the call. On a network filesystem that has stopped
answering, on a FUSE mount, on a device node, or on a FIFO (`File.open` on one
waits for a writer even locally), a read is unbounded — and a cooperative task
that issues one holds its executor thread for the duration, with every sibling
task on that thread waiting behind it. There is no per-call opt-out; code that
knows it is on such a mount should do that work in a `Thread.spawn` body, whose
own thread is then the one that waits.

#### Blocking externs and the offload

An FFI call that may block for an unbounded time is annotated `blocking` inside
an `extern` block. The call is a suspension point: it runs on a worker thread
and the task parks, instead of the call holding the executor thread.

```saw
extern "C" {
    // `read(2)` on a pipe or a slow device is unbounded.
    blocking func read(fd: Int32, buf: UnsafePointer<Int8>, n: Int) -> Int
}

func drain(fd: Int32) unsafe -> Int {
    var chunk: [Int8; 4096] = [0; 4096]
    read(fd, (&chunk) as UnsafePointer<Int8>, 4096)   // siblings keep running
}
```

An unannotated extern promises promptness and is `sync`-callable. A `blocking`
extern call is illegal in a `sync` context, like any other suspension, and
`blocking` externs are rejected in the freestanding profile, which has no
threads to offload onto.

`blocking` is part of an extern's contract, not a spelling of it. Two
declarations of one symbol that disagree about it are a clean error, so a
declaration cannot be silently dropped along with its annotation, and no
downstream declaration can make a function another module calls a suspension
source.

**What the offload does.** Inside a suspending body (a driven or spawned task,
or a suspending `main`), the call lowers to three steps: start a worker thread
that runs the extern, park the task on that worker's self-pipe (registered with
the reactor exactly like a socket read), and take the result when the pipe
signals completion. The task suspends cooperatively, so siblings keep running
while it blocks and the reactor thread is never wedged. The worker touches only
its own job and pipe; wake routing stays in the reactor. The pipe byte and the
join of the worker are the release/acquire boundary, so the result transfers
with no data race. It is a thread per call; there is no pool yet.

**Signatures.** Any signature the C-ABI whitelist admits can be offloaded —
fixed-width integers, `Int`/`UInt`, `Float`, `UnsafePointer<T>`, and `Void` or
`Never` as the return. That is the same set `@export` admits, and the
diagnostic for a type outside it is the same, anchored at the declaration:

```saw
extern "C" {
    blocking func slow_named(s: String) -> Int
}
// error: `extern blocking func slow_named`: parameter `s` has type `String`,
//        which is not C-ABI-safe
```

Arity is unrestricted. Pass an aggregate as `UnsafePointer<S>`.

**Pointer arguments must outlive the call.** The worker reads through a pointer
argument while the task is parked, and it may still be reading after a cancel.
So a pointer argument must address storage in one of two places: the suspended
frame, or the heap. Both survive the park by construction — a suspending
function's locals live in its frame, which is heap-resident across every
suspension, and heap storage lives until it is freed.

```saw
func reader(fd: Int32) unsafe -> Int {
    var buf: [Int8; 64] = [0; 64]          // frame-owned: survives the park
    read(fd, (&buf) as UnsafePointer<Int8>, 64)
}
```

The third possibility, a stack temporary, cannot arise: stack storage that dies
before the worker is done belongs to a function that returned, and a function
that can return while an offload is in flight is a `sync` one, which cannot
reach an offload at all. That is the same fence as any other suspension, and it
is what makes the rule keepable rather than a convention.

Storage the frame owns must also stay put until the join. The compiler arranges
this for the frame's own locals; if you free heap storage yourself, free it
after the call returns, not on a cancel path that races it.

**Position.** A blocking-extern call bound to its own statement (`let r =
db_query(id)`, a bare call, a tail `return db_query(id)`) offloads directly. One
buried in a larger expression — an argument, an operand, a `try!` subject — is
hoisted to its own statement first and offloads from there, and one at statement
position inside a suspension-spanning `if let`/`guard let` body offloads like any
other, since that branch is split like an `if`.

**Cancellation.** Cancelling a task parked on an offload job wakes it: the
reactor's self-pipe rouses the poll, and the park loop re-checks the cancel word
at its top and leaves. The in-flight C call is not aborted, and cannot be — a
thread sitting in `read(2)` has no cooperative point to observe anything at.
Taking the result therefore joins the worker first, on the cancel path as much as
the completion path. Two consequences worth stating: a cancelled task still waits
for its C call to finish before it can return, and nothing the call points at may
be released until that join, which is why the frame keeps its storage until then.

**Two engines coexist today, deliberately not unified, and the NAMESPACE is
which one you are on.** `Thread.spawn`/`Thread<T>`/`Channel.recv` run on the
**OS-thread** engine: `Thread.spawn` starts an OS thread, its body is a `sync`
context that may block on FFI, and `Thread.join()`/`Channel.recv()` block the
calling thread. `Task.spawn`/`TaskGroup`/`Task<T>`/`Channel.receive` run on the
**single-threaded cooperative executor** (above), where a body suspends and a
join drives the group; a suspending `main` runs there too. The call site's
namespace says which machine it is on, and the two behave differently enough
that reading it matters: one blocks and one suspends, and a handle's obligations
differ (a `Thread<T>` and a `Task.spawn` `Task<T>` must be consumed; a group's
`Task<T>` may be dropped).

Reach for them in this order. `TaskGroup` by default: structured, one thread,
deterministic interleaving, and the scope says where the tasks end.
`Task.spawn` when a task genuinely outlives the frame that started it and no
scope fits. `TaskGroup(threads: N)` when the work is CPU-parallel and every
frame is `Send`. `Thread.spawn` when one thread must BLOCK — a long or
thread-phobic C call — which is the one thing the cooperative engine has no
answer for.

Do not mix the two engines for one task. `Channel.recv` from a cooperative task
is the worst version of it: the block is unbounded and the thread it stops is
the executor's, so every sibling stops with it — including the task that would
have sent the value. Use `receive`. Nothing rejects that call today (DF-181c).

### Shared State

`Arc<Mutex<T>>` — see [Synchronized Access](#synchronized-access).
`Mutex.lock`'s closure parameter is a `sync (…)` context: suspending while
holding a lock is a compile error.

### Send and Sync

`Send` ("may move to another task or thread") and `Sync` ("this type's `&self`
surface is safe under true parallelism: more than one thread may hold shared
access at once") are compiler-derived STRUCTURALLY — a struct or
enum is `Send`/`Sync` iff every field or payload is, and **explicit
`extension X: Send` is rejected**. `Thread.spawn` audits every capture for `Send`;
`Channel<T>` requires `T: Send`. `String` is `Send`+`Sync` (immutable buffer,
atomic refcount); `UnsafePointer` is neither and poisons anything holding one;
an interior cell blocks `Sync` ([Interior mutability](#interior-mutability)).

Saw has no shared references in flight, so `Sync` is not about `&` travelling.
A plain `&` never crosses a spawn, and a single-threaded group never consults
`Sync` at all. It is consulted where handles and statics CREATE parallel shared
access: an `Arc` sent across a spawn in a `threads: N` group (which is why
`Arc<T: Send + Sync>` demands it), a lock (`Mutex` and `SpinLock` are `Sync`
BECAUSE they serialize), and a `static`, which every thread can reach.

Interior mutability is what makes the two separate axes. A struct with an
`Atomic` field mutates safely through `&self`, so it is `Send` AND `Sync`. A
struct wrapping a non-atomic interior cell moves harmlessly to another thread
(`Send`) but would race under two threads' shared access (not `Sync`). `Send`
cannot tell those apart; `Sync` is the record of exactly that difference.

#### `UnsafeSync` / `UnsafeSend`

**Status: implemented (design 186).** Some types are thread-safe for a reason
the derivation cannot see — a `Vector`'s buffer pointer is bookkeeping the Law
of Exclusivity already governs, an `Arc`'s refcount is updated with atomic
read-modify-writes, a `Mutex` serializes every access to its payload. The
assertion has its own two names:

```saw
trait UnsafeSync: Sync {}
trait UnsafeSend: Send {}
```

They REFINE the marker traits, so a declared conformance satisfies every
`T: Sync` / `T: Send` bound through the parent and generic code keeps its
vocabulary. The `Unsafe` prefix carries the claim: the conformance header IS
the audited, greppable assertion.

```saw
extension Mutex<T: Send>: UnsafeSync {}
extension Vector<T: Send, A: Send>: UnsafeSend {}
```

Conditional headers are half the point, and their bounds are re-checked at
every instantiation — the first line above promises nothing about a
`Mutex<File>`.

**Legality, checked at the header.** One is declarable only where the
structural derivation FAILED, and only when every field that blocked it is
UNSAFE-TYPED: an interior cell, an `UnsafePointer`, an `UnsafeMemory`. You may
hand-assert exactly what the unsafe domain already owns. Asserting past a SAFE
non-`Sync` field is refused naming the field, because it would be a claim about
someone else's invariants; asserting where the derivation already succeeds is
refused too, since it teaches the next reader that something was needed.

**Three fences.** The assertion appears in exactly one position, the
conformance header: `T: UnsafeSync` as a generic bound and `any UnsafeSync` as
an existential are both clean errors pointing at the property. These are two
builtin traits, not a user-definable unsafe-trait feature. The
[orphan rule](#conformance-coherence-the-orphan-rule) applies unchanged.

### A raw buffer shared across threads

**Status: implemented.** A type that owns raw memory — a pointer into the heap,
a mapped region, an inline byte array it hands addresses out of — becomes
shareable in one of two ways, and which one you want depends on where the
synchronization lives. Both start from the same fact: the raw pointer does not
poison the type.

#### Level 1: the buffer behind a lock

**Write the type as an ordinary safe struct.** A field of unsafe type does not
make the struct unsafe. Unsafety is not transitive
([Unsafe Code](#unsafe-code--unsafe-types-and-the-functions-that-touch-them)),
and `Vector` is the precedent: it holds an `UnsafePointer` and is a safe type
you pass, store and return with no ceremony. Only the methods that reach
*through* the pointer carry the `unsafe` effect, and each one owes total
soundness — a function whose parameters are all safe types must be sound for
every input it can be handed, so `push` below bounds-checks and panics rather
than trusting its caller.

```saw
import std.mutex.{Mutex}

static SAMPLE_CAPACITY: Int = 64

struct SampleBuffer {
    bytes: UnsafePointer<UInt8>,
    filled: Int
}

extension SampleBuffer: NoCopy {
    func deinit(&var self) unsafe {
        GlobalAllocator().dealloc(self.bytes as UnsafePointer<Int8>, SAMPLE_CAPACITY, 1)
    }
}

extension SampleBuffer {
    init() unsafe -> SampleBuffer {
        guard let block = GlobalAllocator().alloc(SAMPLE_CAPACITY, 1) else {
            panic("SampleBuffer: allocation failed")
        }
        SampleBuffer(bytes: block as UnsafePointer<UInt8>, filled: 0)
    }

    func len(&self) -> Int { self.filled }            // safe: never names the pointer

    func push(&var self, sample: UInt8) unsafe {
        if self.filled >= SAMPLE_CAPACITY { panic("SampleBuffer.push: buffer is full") }
        self.bytes[self.filled] = sample
        self.filled = self.filled + 1
    }

    func sum(&self) unsafe -> Int {
        var total = 0
        for i in 0..self.filled {
            total += self.bytes[i] as Int
        }
        total
    }
}
```

`len` is not `unsafe`. It reads an `Int` field and never names the pointer, so
the trigger rule never fires — non-transitivity seen from inside the type.

**Assert `UnsafeSend` once.** `UnsafePointer` is neither `Send` nor `Sync`, so
structural derivation stops at the `bytes` field and `SampleBuffer` derives
neither. Moving one to another thread is safe anyway, for reasons the
derivation cannot read off the fields, so the type says so:

```saw
extension SampleBuffer: UnsafeSend {}
```

That one line carries four obligations, and they are the review checklist:

1. **The memory is heap-only.** What the pointer addresses outlives the thread
   that allocated it. A pointer into a stack frame or into thread-local storage
   fails here, and no lock repairs it.
2. **Nothing in the type is thread-affine.** No cached thread id, no handle
   valid on one thread only, no state whose meaning depends on which thread
   reads it.
3. **`deinit` is sound from any thread.** The last owner frees the region, and
   which thread that turns out to be is not knowable at the declaration.
4. **No unsynchronized sibling reaches the same region.** The assertion is
   about *this* value's exclusive claim on its bytes; a second pointer to the
   same allocation, held somewhere else and written without coordination,
   voids it.

**`Arc<Mutex<T>>` composes from there.** The standard library's conformances are
conditional, so the one assertion propagates: `extension Mutex<T: Send>:
UnsafeSync {}` now holds, `Mutex<SampleBuffer>` derives `Send` from its cells,
and `extension Arc<T: Send + Sync>: UnsafeSend {}` and its `UnsafeSync` twin
then make the handle safe to copy into a worker.

```saw
func record(shared: Arc<Mutex<SampleBuffer>>, sample: UInt8) {
    shared.lock({ &var buf in buf.push(sample) })
}

func main() {
    let shared = try! Arc<Mutex<SampleBuffer>>(value: Mutex<SampleBuffer>(value: SampleBuffer()))
    var workers = try! TaskGroup(threads: 2)
    let left = workers.spawn(record(shared.copy(), 3))
    let right = workers.spawn(record(shared.copy(), 4))
    left.join()
    right.join()
    print("{} samples, sum {}", shared.lock({ &var buf in buf.len() }),
                                shared.lock({ &var buf in buf.sum() }))
    // prints: 2 samples, sum 7
}
```

Delete the `UnsafeSend` line and the spawn is refused at the function that would
have crossed:

```
error: cannot spawn `record` into a multi-threaded `TaskGroup(threads: ...)`:
       parameter `shared` of type `Arc<Mutex<SampleBuffer>>` is not `Send`, so
       the task frame cannot cross to a worker thread. Share thread-safe state
       via `Arc` (and `Mutex` for mutation) or a `Channel` instead of moving it
       in.
```

#### Level 2: synchronization inside the type

Level 1 buys thread safety with an outer lock: every access serializes, and the
value is `Sync` only for as long as it sits inside the `Mutex`. Put the
synchronization inside the type instead when you want lock-free sharing, or when
the type itself has to be `Sync` — which is what the `static` position requires
([Module-level statics](#module-level-statics)), and what an interior cell
blocks.

The obligation is bigger than Level 1's and is worth stating before the code:
**every `&self` method must be race-free under true parallelism**, jointly —
any two of them may run at the same instant on the same value. Level 1 gets
that from the lock. Here you owe it method by method.

```saw
static REGION_BYTES: Int = 4096
static CHUNK_BYTES: Int = 16

struct BumpArena {
    region: UnsafeMutableInterior<[UInt8; REGION_BYTES]>,
    next: Atomic<Int>
}

extension BumpArena: NoCopy {}
extension BumpArena: UnsafeSync {}

extension BumpArena {
    func _base(&self) unsafe -> UnsafePointer<UInt8> {
        self.region.ptr() as UnsafePointer<UInt8>
    }

    /// Claims `count` bytes and returns their offset, or `None` when the region
    /// is spent. Never hands out a reference into the region.
    func take(&self, count: Int) unsafe -> Int? {
        let start = self.next.fetch_add(count)
        if start + count > REGION_BYTES { return None }
        for i in 0..count {
            self._base()[start + i] = 0
        }
        start
    }
}

static SCRATCH: BumpArena          // zero is an empty arena; no initializer owed

func claim(rounds: Int) -> Int {
    var taken = 0
    for _ in 0..rounds {
        if let _ = SCRATCH.take(CHUNK_BYTES) { taken += 1 }
    }
    taken
}

func main() {
    var workers = try! TaskGroup(threads: 2)
    let left = workers.spawn(claim(100))
    let right = workers.spawn(claim(100))
    print("claimed {} chunks", left.join() + right.join())
    // prints: claimed 200 chunks
}
```

`take` is the whole argument: one `fetch_add` decides an offset, no two callers
can be handed the same one, and the region is written only inside the range that
call just won. The cell is what makes the mutation reach the caller's storage
through a `&self` receiver ([Interior mutability](#interior-mutability)), and it
is also what blocks `Sync`, which is why the assertion is legal here at all.
Without it the `static` is refused, and the diagnostic names the field that
blocked the derivation and the line to add:

```
error: static `SCRATCH` has non-Sync type `BumpArena`; statics must be Sync
       (shared across all tasks)
  hint: ... `BumpArena` carries an interior cell (design 186), so it derives no
        `Sync`: field `region` of type `UnsafeMutableInterior<[UInt8; 4096]>` is
        mutable through a shared borrow, which the derivation cannot reason
        about. If the synchronization is real but invisible to the compiler, say
        so — `extension BumpArena: UnsafeSync {}`, beside the type, where it can
        be audited.
```

#### The two rules, and the fallback

**A lock converts `Send` into `Sync`, and nothing more.** A mutex serializes
simultaneity: two threads may hold the handle, never the payload at once. It
does not un-migrate anything, so the payload must still be safe to *move*
between threads on its own. That is why the standard library's conformance is
bounded rather than unconditional:

```saw
extension Mutex<T: Send>: UnsafeSync {}
```

The bound is re-checked at every instantiation, so a `Mutex` over a payload that
is not `Send` is not `Sync`, and the `Arc` around it is not `Send` either:

```saw
// `Box<TaskGroup>` is not `Send`
func poke(shared: Arc<Mutex<Box<TaskGroup>>>) -> Int { shared.strong_count() }
// error: cannot spawn `poke` into a multi-threaded `TaskGroup(threads: ...)`:
//        parameter `shared` of type `Arc<Mutex<Box<TaskGroup, GlobalAllocator>>>`
//        is not `Send`, ...
```

**Nothing upgrades a non-`Send` type to `Send` except the type's own design.**
No wrapper does it. `Arc`, `Mutex`, `Box` and a struct field are each
`Send`/`Sync` exactly when their contents are, and stacking them multiplies
nothing — which is what the refusal above is showing. The only thing that
changes the answer is a declared `UnsafeSend`/`UnsafeSync` on the type itself,
written beside the type under the orphan rule, where a reviewer will find it.

**When neither assertion is honest, send the operation instead of the value.**
This works for every type, including ones that could never be `Send`: the value
stays with one task, and everybody else names an operation on it. The request
crosses, the buffer does not, and no assertion is owed by anybody. (Continuing
the `SampleBuffer` above, with no `UnsafeSend` on it — the `import` line joins
the ones at the top of the file.)

```saw
import std.channel.{Channel}

enum Request {
    case Record(sample: UInt8)
}

func feed(inbox: Channel<Request>, sample: UInt8) {
    try! inbox.send(Request.Record(sample: sample))
}

func main() {
    var buf = SampleBuffer()           // owned here, shared with nobody
    let inbox = try! Channel<Request>()
    var senders = TaskGroup()
    let left = senders.spawn(feed(inbox.copy(), 3))
    let right = senders.spawn(feed(inbox.copy(), 4))
    for _ in 0..2 {
        let request = try! inbox.receive()
        match request {
            case Record(sample) -> buf.push(sample)
        }
    }
    left.join()
    right.join()
    print("sum {}", buf.sum())
    // prints: sum 7
}
```

`Request` is `Send` because a `UInt8` is. That is the whole cost of the pattern,
and it is why it always works: remote operation is not shared access, so the
thread-safety question moves off the buffer and onto the messages, where it is
usually trivial.

The senders can be on other threads. Change the one word and the program is a
`threads: 2` group whose workers run while `main` is reading:

```saw
func main() {
    var buf = SampleBuffer()           // still owned here, still shared with nobody
    let inbox = try! Channel<Request>()
    var senders = try! TaskGroup(threads: 2)
    let left = senders.spawn(feed(inbox.copy(), 3))
    let right = senders.spawn(feed(inbox.copy(), 4))
    for _ in 0..2 {
        let request = try! inbox.receive()   // arrives from a worker thread
        match request {
            case Record(sample) -> buf.push(sample)
        }
    }
    left.join()
    right.join()
    print("sum {}", buf.sum())
    // prints: sum 7
}
```

`SampleBuffer` never becomes `Send` and never needs to: it stays on `main`'s
thread and only `Request` crosses. Which sample arrives first is unspecified,
which is why the program adds them.

### Module-level statics

**Status: implemented (design 41).** A `static` is a module-level
constant-initialized global:

```saw
static MAX_TASKS: Int = 256           // POD scalar → rodata
static PRIMES: [Int; 3] = [2, 3, 5]   // constant fixed-array literal
static ORIGIN: Point = Point(x: 0, y: 0)  // POD struct literal
static SLAB: [Int8; 4096]             // bare declaration → zero-init (.bss)
static ARENA: [UInt8; 65536] = [0; 65536]  // all-zero initializer → .bss too
public static VERSION: Int = 7        // exported; read as `mod.VERSION`
```

Statics obey four rules, ratified in design 19:

- **Const-initialized only.** A static is image bytes, so its initial value
  is fixed at compile time. There are exactly THREE tiers, and the third one
  is a refusal:

  1. **Zero-init.** A bare declaration with no initializer, legal when
     all-zero is a valid value of the type — every scalar, a struct of them,
     a fixed array of them, an `Atomic<Int>`, a `SpinLock<T>`, a `Mutex<T>`,
     a `Once<T>`. Copyability is irrelevant here: a static is never copied,
     so a `NoCopy` type whose storage is scalar throughout still qualifies,
     which is what makes `static LOCK: SpinLock<T>` a legal declaration.
  2. **A constant expression, plus memberwise aggregation.** Whatever the
     const evaluator folds — literals, arithmetic and the bitwise operators
     over them, `sizeof`/`alignof`, the integer limits, a raw-backed enum
     case, an earlier module `static`, and an IMPORTED one in either
     spelling (`A` under `import dep.{A}`, `dep.A` under `import dep`) — and
     struct literals, fixed-array literals (including a `[v; N]` repeat),
     `Atomic(<int>)` and `UnsafeMemory(<int>)` built out of those. The
     initializer and every other const position share ONE evaluator, so an
     expression that folds in an array length folds here too — which is what
     lets a derived size be declared APART from the numbers it derives from:
     `static SLOTS: Int = dep.EVENTS + dep.TIMERS`.
  3. **Runtime-computed state is never a static initializer, in any form.**
     A user `init` BODY does not run at compile time — even one that visibly
     would fold, because folding bodies is const-fn and Saw does not have it
     — and neither does a function call, a `String`, or any heap type. State
     that has to be computed has two spellings, and they are not
     interchangeable: **set once** wants `static X: Once<T>`
     ([`std.once`](#stdonce)), and **mutated throughout** wants
     `unsafe static var` plus the author's own ordering argument. There is no
     life-before-main and no static constructor.

  Field aggregation folds; bodies do not. That is the whole line between (2)
  and (3), and it is why `Region(bytes: PAGE_SIZE, pages: 1)` is a constant
  and `Region(pages: 1)` — the same struct, reached through a hand-written
  `init` — is not.

- **Sync-only.** The static's type must be `Sync` (a static is reachable
  from every task). A non-Sync type is a compile error naming the type.
  An `unsafe static var` is exempt — see below. A CELL-CARRYING type derives
  no `Sync`, so a static of one needs its type's `UnsafeSync` declaration
  ([Interior mutability](#interior-mutability)); the refusal names both the
  declaration to write and the field that blocked the derivation.
- **Immutable, unless declared `unsafe static var`.** Assigning to a
  static (whole, field, or element) or taking `&var STATIC` is a compile
  error; an `&STATIC` shared lend is fine. Mutation of global state flows
  through interior-synchronized types (`Atomic<Int>`, `SpinLock<T>`), or
  through the `unsafe` declaration below — never silently.
- **Immortal.** Statics never run `deinit`, so a static's type must be
  trivially destructible: no hand-written `deinit` anywhere in its type
  tree, and no field that owns a resource. A declared copy POLICY is not
  the test — `NoCopy` says "do not duplicate me", which has nothing to say
  about a value that is never duplicated.
- **Never optional.** A static's own type may not be an optional
  (`static SLOT: Int? = 7` is a compile error naming the rule). A static is
  initialized once at compile time and never changes, so it is always
  present, and an optional would make every read unwrap for an answer fixed
  at compile time. The refusal covers the bare, wrapped and `None`
  initializers and the no-initializer form alike, since it is asked on the
  type. Only the static's OWN type is the target — an optional FIELD or
  element is ordinary storage (`static H: Holder` where `Holder.slot` is an
  `Int?` is fine). State whose absence is real has to be computed: use
  `static X: Once<T>` or `unsafe static var`.

Reads elsewhere in the module (or `mod.NAME` from an importer of a
`public` static) behave like an immutable binding.

**A static is a constant where a constant is required.** An `Int` or
`UInt` static whose initializer folds to a number folds into every position
the language fixes at compile time: an array length `[T; N]`, a
repeat-literal count `[v; N]`, a const generic argument, and a
`static_assert` condition. Constant arithmetic composes over it, so one
declaration can size a region and everything derived from it:

```saw
static PAGE_SHIFT: Int = 12
static PAGE_SIZE: Int = 1 << PAGE_SHIFT      // derived from the one above
static PAGE_MASK: Int = PAGE_SIZE - 1

static_assert(PAGE_SIZE % 4096 == 0, "the region must be page-aligned")

struct Region { bytes: [UInt8; PAGE_SIZE] }
static ARENA: [UInt8; PAGE_SIZE] = [0; PAGE_SIZE]

func main() {
    var half: [UInt8; PAGE_SIZE / 2] = [0; PAGE_SIZE / 2]
    print(half.len())                  // prints: 2048
}
```

Initializers fold in **declaration order**, so one may name the statics
above it and no others. That is also the cycle rule: a forward reference has
nothing to fold against, and a self reference is the degenerate forward one.
Both are refused where the name is written.

```saw
static EARLY: Int = LATER * 2
static LATER: Int = 64
// error: static `LATER` is declared after this point
//   hint: static initializers fold in DECLARATION ORDER, so one may name
//         only the statics above it — which is also what makes a cycle
//         impossible. Move the declaration up
```

What still does not fold is a value that is not a fact about the source. A
mutable `unsafe static var`, a static of a non-integer type, and one
declared without an initializer are each refused, and the message names
which static and why rather than reading as "a static may not be named
here":

```saw
unsafe static var ARENA_BYTES: Int = 1024
static ARENA: [UInt8; ARENA_BYTES] = [0; 1024]
// error: array length is not a compile-time constant: the mutable static
//        `ARENA_BYTES` is not allowed here
```

The name resolves as it would in any other read. A local wins over a
static, so a derived shadow (`let REGION_SIZE = REGION_SIZE + 1`) is the
runtime value it looks like and is refused in a length; a const generic
parameter wins over both. Across modules the ordinary visibility gate
applies: a `public` static reached through an import folds, a
module-private one is not nameable at all. Both spellings work, the bare
import and the qualifier, and they fold to the same number:

```saw
import dep
import dep.{REGION_SIZE}

struct Frame { bytes: [UInt8; dep.REGION_SIZE] }   // qualified
static ARENA: [UInt8; REGION_SIZE] = [0; REGION_SIZE]   // imported bare
```

**Zero statics cost no image bytes.** A static whose initializer is
all-zero — a bare declaration, or an explicit `[0; N]` — is emitted as
zerofill storage, in both the hosted and the freestanding profile. The 64
KiB arena above adds 64 KiB to the program's address space and nothing to
its file. A non-zero initializer has bytes to carry and carries them.

#### `unsafe static var` — mutable statics for compound state

**Status: implemented (design 149).** Some global state is wider than one
word and has invariants that span it: a handle table of multi-word slots,
a bitmap paired with the queues it indexes, an arena's backing storage. No
atomic expresses that, because atomicity is per-word and the invariant is
not.

```saw
struct Slot { owner: Int, used: Bool }

unsafe static var TABLE: [Slot; 64] = [Slot(owner: 0, used: false); 64]
unsafe static var LIVE: Int = 0

func claim(owner: Int) unsafe -> Int {       // `unsafe`: it names TABLE
    var i = 0
    while i < 64 {
        if not TABLE[i].used {
            TABLE[i] = Slot(owner: owner, used: true)
            LIVE = LIVE + 1
            return i
        }
        i = i + 1
    }
    -1
}
```

This is not an `Atomic` replacement, and reaching for it where an
`Atomic` fits is a mistake the diagnostics point out. Single-word state
that several tasks update independently wants `Atomic`; state several
threads genuinely share wants `SpinLock` or `Mutex`. `unsafe static var` is
for state whose consistency comes from a serialization argument the compiler
cannot see — interrupts off, a single core, boot-time only — and the
`unsafe` declaration is what makes that argument somebody's job to state.

**It is also not a `Once`.** State that is computed once at a moment the
program picks, and read as a plain value from then on, is `static X: Once<T>`
([`std.once`](#stdonce)): the publish ordering is inside the type, the
readers are safe functions, and a second `set` is a panic rather than a
silent overwrite. `unsafe static var` is for state genuinely MUTATED
throughout the program's life, which is what `var` says.

Four rules:

- **`var` and `unsafe` come as a pair.** A `static var` without `unsafe`,
  and an `unsafe static` without `var`, are each a clean error naming the
  spelling. There is one way to declare global mutable state.
- **Naming one is unsafe contact.** Design 130's trigger rule extends to
  it: a function whose body names an unsafe static is declared `unsafe`
  or is a compile error. The type is usually an ordinary safe one, so the
  unsafety is the DECLARATION's, and the rule is what puts every touching
  function in front of a reviewer.
- **Exempt from Sync.** Sync is the claim the declaration is already
  making by hand, and the compound state this exists for (slots holding
  raw pointers, shadow register state) is structurally non-Sync exactly
  where it is most wanted.
- **Trivially destructible only** (v1), like every static.

`unsafe` takes the PREFIX position here, as it does on `unsafe struct`
and for the same reason: a static has no parameter list, so there is no
effect slot for it to ride.

### Interior mutability

**Status: implemented (design 186).** Interior mutability is mutation through
a SHARED borrow. One primitive expresses it, and everything the compiler does
about it follows from a structural property rather than from a list of type
names it knows.

```saw
unsafe struct UnsafeMutableInterior<T>       // holds a T, inline
func ptr(&self) unsafe -> UnsafePointer<T>   // the only accessor
```

The signature is the whole safety story. Every function touching a cell is
dragged into the declared-`unsafe` domain by the ordinary
[trigger rule](#the-unsafe-surface), with no new effect rules; a safe public
wrapper method takes on the all-safe-parameters obligation exactly where
`SpinLock.lock` already does. The cell is layout-transparent — it occupies
exactly its `T` — so a cell field costs no wrapper, and construction is
positional (`UnsafeMutableInterior(v)`).

A type that transitively contains a cell is **cell-carrying**, and that answers
four questions at once:

- **Receivers travel by pointer.** A `&self` method on a cell-carrying type
  reaches the CALLER's storage rather than a copy of it. That is what lets
  `ptr()` be worth anything: without it the address would be the callee copy's,
  and every write through it would be dropped at the return. Every other
  `&self` receiver is still passed by value.
- **A `static` of one is never read-only.** It is written in place, so a
  read-only segment would fault on the first write. An all-zero one still costs
  no image bytes.
- **Codegen assumes nothing.** No shared borrow of cell-carrying storage
  carries `readonly`, `noalias` or an invariant-load marker.
- **`Sync` derivation is blocked**, at the cell. Sharing a value that can be
  mutated through a shared borrow is exactly the claim a structural derivation
  cannot make — the fields all look immutable and are not. `Send` is untouched:
  a cell MOVES fine, and it is sharing that needs an argument.

The block sits at the cell, not at everything holding one. A type holding a
cell DIRECTLY says [`UnsafeSync`](#unsafesync--unsafesend); a type holding one
of THOSE derives normally, because the declaration it passes through is the
argument. So `struct Stats { hits: Atomic<Int> }` gets its `Sync` derived, with
no thread-safety assertion of its own to write. (It does owe a COPY policy —
`Atomic` is `NoCopy`, and that cascade is a separate question from this one.)

**The wrapper idiom** is a cell field, `&self` methods, one small `unsafe`
helper, and a declared `UnsafeSync`:

```saw
struct Counter {
    cell: UnsafeMutableInterior<Int>
}

extension Counter: UnsafeSync {}

extension Counter {
    public init(start: Int) unsafe -> Counter {
        Counter(cell: UnsafeMutableInterior(start))
    }

    // The one unsafe helper: confinement is a signature.
    func _at(&self) unsafe -> UnsafePointer<Int> { self.cell.ptr() }

    public func value(&self) unsafe -> Int { self._at()[0] }
    public func bump(&self, by: Int) unsafe { self._at()[0] = self._at()[0] + by }
}

static HITS: Counter
```

`Atomic`, `SpinLock`, `Mutex` and `Once` are all written this way. What stays
compiler-known about `Atomic` is its ATOMICITY, which no library can express.

A cell is `NoCopy` as a value — copying one makes a second, independent cell —
but a cell FIELD contributes its `T`'s copy tier to whatever holds it, rather
than cascading `NoCopy` onto it. The container states its own policy, so a
wrapper that wants to be move-only says `extension Counter: NoCopy {}` in a line
the reader can see. `Atomic<Int>` is one such wrapper and does say it (below);
a `Counter` over a cell of a plain word does not have to.

### `Atomic<Int>`

**Status: implemented (design 41).** `Atomic<Int>` is the minimal
interior-synchronized primitive — the sanctioned way to mutate global
state. It is const-initializable (`Atomic(0)`), usable as a `static` and
as a struct field, and holds an interior cell, so it declares `UnsafeSync`
rather than deriving `Sync`. Its methods take a shared `&self` — the
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

A receiver carrying an `Atomic` cell — `Atomic<Int>` itself, or any
struct holding one — arrives at a `&self` method as the caller's STORAGE
rather than as a copy, which is what makes interior mutation through a
shared borrow reach the real cell. That is the cell-carrying property
above, and it is not special to `Atomic`.

`Atomic` is **move-only**: it declares `NoCopy`, so `let b = a` on one is a
compile error and `move a` is how it travels.

```saw
let local = Atomic(0)
let alias = local
// error: cannot copy value of type `Atomic<Int>` which implements NoCopy
```

A copied atomic would be a second counter with its own word, and a `fetch_add`
through one would be invisible through the other, so the program that meant to
count once counts twice and has nothing to show for it. Share an atomic instead
of duplicating it: reach one through a `static`, or lend it as a
`&Atomic<Int>` parameter.

```saw
static COUNTER: Atomic<Int> = Atomic(0)

func observed(a: &Atomic<Int>) -> Int { a.load() }

func main() {
    let _prev = COUNTER.fetch_add(1)
    print(observed(&COUNTER))        // prints: 1
}
```

A struct with an `Atomic` field declares its own copy policy, on the terms any
NoCopy member gets ([The Copy trait family](#the-copy-trait-family)):

```saw
struct Stats { hits: Atomic<Int> }
// error: struct `Stats` contains NoCopy field `hits` of type `Atomic<Int>`
//        but does not implement NoCopy

extension Stats: NoCopy {}       // the fix the diagnostic names
```

`NoCopy` and not `NoMove`: nothing pins an atomic's address, so one moves
freely into another binding, a call, or a struct. Statics are unaffected — a
NoCopy static is legal, and every atomic operation takes `&self`.

### `SpinLock<T>`

**Status: implemented (design 149).** `import std.spinlock`. A value
guarded by an atomic word: one word plus the payload, no allocation, and no
operating system, so it works in the freestanding profile where
[`Mutex<T>`](#synchronized-access) — which needs a host lock — does not.

```saw
import std.spinlock.*

struct Counters { hits: Int, misses: Int }

static STATS: SpinLock<Counters>         // zero = unlocked, payload zeroed

func record(hit: Bool) {
    STATS.lock({ c in
        if hit { c.hits = c.hits + 1 } else { c.misses = c.misses + 1 }
    })
}

let seen = STATS.lock({ c in c.hits })   // the body's result comes back out
if let n = STATS.try_lock({ c in c.hits }) { }  // None if held; never spins
```

- `lock<R>(body: (&var T) sync -> R) -> R` spins until free, runs `body`
  once with `&var` access, releases, and returns what `body` returned.
- `try_lock<R>(body: (&var T) sync -> R) -> R?` decides with one
  compare-and-swap. `None` means the lock was held at that instant.
- `is_locked() -> Bool` is a debugging aid; the answer can be stale
  before it is read, so branch with `try_lock`, not with this.

`NoCopy` (a copied lock is two locks guarding two payloads). It carries an
interior cell, so its `Sync` is DECLARED — `extension SpinLock<T: Send>:
UnsafeSync {}` — on the same terms as `Mutex`: handing out a `&var T` under
mutual exclusion is safe to share exactly when moving a `T` between threads is.
Locking is not reentrant: taking the lock while holding it spins forever.

Two constraints are enforced, not documented:

- **The body is `sync`.** Suspending inside a critical section is a
  compile error. A suspended task keeps the lock while the executor runs
  somebody else, and that somebody may be the task waiting for it.
  A consequence: since `lock` and its body are both `sync`, a task cannot
  be interrupted while holding the lock, so two tasks on one thread never
  contend and contention always means another thread or another core.
- **The target must have atomics.** Where a compare-and-swap lowers to
  `__atomic_*` libcalls (rv32i), naming a `SpinLock` is a compile error
  pointing at `--target-features +a`, never a silent fallback into a C
  runtime a freestanding target does not have.

Hold it briefly. A waiter burns its core until the lock is free.

### `std.once`

**Status: implemented (design 186).** `import std.once`. `Once<T>` holds a value
written once and read many times. A `static` is image bytes and there is no
life-before-main, so a global whose initial value must be COMPUTED cannot be a
static initializer in any form; this is the answer for the half of that which is
set once.

```saw
import std.once.*

struct Limits { workers: Int, queue: Int }

static LIMITS: Once<Limits>          // zero is UNSET; .bss, no image bytes

func boot(cpus: Int) {
    LIMITS.set(Limits(workers: cpus, queue: cpus * 64))
}

func workers() -> Int {              // a safe function: no `unsafe` anywhere
    LIMITS.get().workers
}
```

- `set(value: T)` publishes, once. **Panics** if a value is already present, or
  if another thread is publishing at that instant. Racing setters resolve
  through a compare-exchange: the first wins, every loser panics.
- `get() -> T` returns the published value (`T: ExplicitCopy`). **Panics** if nothing
  has been published yet.
- `try_get() -> T?` is the inspectable twin — `None` while unset.
- `is_set() -> Bool` is a debugging aid; the answer can be stale before it is
  read.

Both panics are the fault-not-status rule. Two boot paths initializing one
`Once` is a bug in the boot order, and reading a value that has not been
computed is a bug in the call order; a status either could ignore would let the
program run on the wrong configuration instead.

`Once` is `NoCopy` (a copy is a second, independent slot) and declares
`UnsafeSync` at `T: Send + Sync` — `get` hands a COPY to whichever thread asked,
and two readers copy the stored value concurrently. It is DECLARED rather than
constructed: the unset state is the zero pattern, so a bare `static` is the only
spelling it needs. Design 149's immortality rule applies as it does to every
static, so `T` must be trivially destructible.

It does not block. A `get` racing the `set` that would satisfy it takes the
not-yet-initialized panic; spin on `try_get` if a wait is what you want.

---

## 7. Metaprogramming

**Status: partially implemented** — generics are built (see below); const
evaluation, macros, and compile-time reflection are planned.

### Generics

**Status: implemented.** Generic functions, structs, and enums; `T: Trait`
bounds (including the built-in `T: Copy` and `T: ExplicitCopy`
bounds); generic extensions, including **bounded** extensions
(`extension Vector<T: ExplicitCopy, A: Allocator = GlobalAllocator>:
ExplicitCopy { ... }`, used in the stdlib).

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
extension Vector<T, A: Allocator = GlobalAllocator> {
    // `U` is a METHOD-level type parameter, distinct from the element type `T`
    // and the allocator `A` (which the result vector inherits). The element is
    // lent as a `&T`, so the extension carries no copy bound.
    func map<U>(&self, transform: (&T) -> U) unsafe -> Vector<U, A> { ... }

    // `Acc` is the accumulator type (named `Acc`, not `A`, since `A` is now
    // the extension's allocator type parameter).
    func fold<Acc>(&self, initial: Acc, combine: (Acc, &T) -> Acc) unsafe -> Acc { ... }
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
parameter with a default type fills from the default. A parameter whose *value*
default is typed by a type parameter (`func f<T>(a: Int, b: T = 0)`) has that
default type-checked against the **instantiated** `T` at each call, and when `T`
is otherwise undetermined the **default drives inference** (design 108) — `f(1)`
infers `T = Int` from `b: T = 0` (a supplied argument always wins, so `f(1, 2.0)`
infers `Float`); a default that cannot fit the instantiated type (`f<Float>(1)` —
a bare integer literal does not adopt `Float`) or that drives inference to a
bound-violating type is a clean call-anchored error, never an ICE. Inference
never guesses — a
parameter no argument constrains (**underdetermined**) or one an argument forces
to two different types (**conflict**) is a clean error naming the parameter and
suggesting explicit arguments, and an inferred argument is bound-checked naming
the inferred type. Inference runs non-closure arguments first, then closures,
**fixpointing** over the argument list (design 105) so a parameter determined by
an argument to its *right* — including a closure that precedes the value that
fixes its `T` (`run({ $0 * 2 }, 10)`) — is solved on a later pass. Labeled
arguments are paired with parameters by LABEL before unifying. Inference also
runs across an **overload set** (design 105): with no concrete match, each
generic candidate is solved independently and the unique solving-and-type-matching
one is picked, two or more being the ambiguity error above (see *Overloading*).
The method body is checked abstractly
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
struct Vector<T, A: Allocator = GlobalAllocator> { ... }

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

**Const generics — implemented.** A type parameter may carry a VALUE instead of
a type. The `const` keyword in the parameter position is what keeps the two
kinds apart at a glance:

```saw
struct FixedBuf<const N: Int> {
    data: [UInt8; N]
}

extension FixedBuf<N> {
    init() -> FixedBuf<N> {
        FixedBuf<N>(data: [0; N])
    }

    // `N` reads as an ordinary Int here — one value per instantiation, folded
    // to a constant at compile time.
    func capacity(&self) -> Int { N }
}

var small = FixedBuf<16>()
var big   = FixedBuf<256>()
print(sizeof<FixedBuf<16>>())      // 16
print(sizeof<FixedBuf<256>>())     // 256
```

`FixedBuf<16>` and `FixedBuf<256>` are different types with different layouts.
The value is part of the type identity and part of the monomorphization key, so
neither is assignable to the other and each gets its own specialized code.

Scope, deliberately narrow in this version:

- **Value type**: `Int` or `UInt`. A parameter of any other type is rejected at
  the declaration (`a const parameter is `Int` or `UInt``).
- **Where a parameter may be used**: an array length (`[T; N]`), a
  `static_assert` operand, `sizeof` arithmetic, a repeat-literal count, and any
  expression position wanting an `Int`.
- **Const arithmetic** in instantiation position: literals, const parameters,
  and `+ - * / %` over them. `FixedBuf<2 * 128>` and `FixedBuf<256>` are the
  same instantiation — the value is folded before anything mangles it, the same
  identity rule default type arguments follow. The bit operators are not part
  of the grammar in this position: an argument list is closed by `>`, which is
  also the shift token. Write the multiplicative form (`FixedBuf<2 * 128>`) or
  a `static`. An array length is closed by `]` and takes the full grammar.
- **A module `static`** may be the argument on the same terms, so
  `FixedBuf<REGION_SIZE>` and `FixedBuf<65536>` are one instantiation with one
  layout and one symbol. See Module-level statics for which statics fold.
- **Declarations**: structs, enums, and free functions all take const
  parameters, and an extension on a const-generic type is written like any
  generic extension (`extension FixedBuf<N>` — the constness comes from the
  declaration, so it is not repeated).
- **Defaults** compose with default type arguments: `struct Ring<const N: Int =
  4>` lets `Ring()` mean `Ring<4>`.
- **Inference**: explicit in this version, with one exception. A `[T; N]`
  parameter binds `N` from the argument's length:

  ```saw
  func width<const N: Int>(xs: [Int; N]) -> Int { N }
  print(width([1, 2, 3, 4]))     // 4 — N solved from the argument
  ```

Passing the wrong kind of argument is a clean error naming the parameter:
`FixedBuf<Int>` reports that `N` takes a value, and `Pair<4>` that `T` takes a
type.

Not supported: const parameters of user types, comparisons over a parameter in
the declaration (`where N > 0` — write `static_assert(N > 0, ...)` in the body),
and variadic shapes.

**Status: planned** — `where` clauses are *illustrative* below and not yet
implemented:

```saw
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

**Type-parameter bounds name traits.** A bound is checked at the declaration, so
a non-trait in that position is reported where it is written rather than at every
use site. `<N: Int>` — the natural guess at a value parameter — says so and
points at the const spelling:

```saw
struct FixedBuf<N: Int> { len: Int }
// error: `Int` is a type, not a trait, so it cannot bound the type parameter `N`
//   hint: to take a compile-time VALUE, write `const N: Int`
```

#### What a generic body requires of its type parameters (design 219)

A generic body is written once and runs at every type it is instantiated at, so
the compiler asks one question about each type parameter while checking the
body: **does this body ever duplicate a value of `T` with nothing written at the
site?** There are two answers, and they are inferred, not declared.

- **It does not** — every use is a move. The body works at every type,
  move-only ones included. This is the common case, because the ordinary
  generic shape is forwarding, and forwarding moves.
- **It does** — the body needs `T` on the `Copy` tier, and each call site is
  checked against the type argument you actually passed.

The refusal lands at the CALL, names the requirement, and quotes the line in the
body that caused it:

```saw
func twice<T>(x: T) -> Int {
    let a = sink(x)
    let b = sink(x)   // `x` is bound a second time here
    a + b
}

twice(move r)
// error: `twice` requires `T` to be `Copy` — it binds `x` twice, at lines 2
//        and 3; `Res` is move-only
```

The rule is per PATH, not per mention. `if a < b { b } else { a }` names each
parameter twice and duplicates neither, because no single path uses either one
twice, so it stays available at every tier. A read out of storage the body does
not own — a field, a tuple element, an indexed place — is always a duplicate,
however few times the name appears: there is no partial move, so the source
keeps its copy.

The requirement travels. A generic that forwards its `T` to a callee needing
`Copy` needs it too, and the refusal appears at ITS call site with the concrete
type named.

**Duplicating on purpose: declare `<T: ExplicitCopy>` and spell `.copy()`.**
`.copy()` on a value whose type mentions an unbounded type parameter is refused
at the definition, and that covers wrappers as well as a bare `T` — `(T, Int)`,
`T?`, `[T; N]`, and nestings of them all reach the same rule:

```saw
func dup<T: ExplicitCopy>(p: (T, Int)) -> (T, Int) { p.copy() }
```

**A `public` generic must DECLARE what it requires.** Where the requirement is
inferred, editing the body can tighten it — add a second bind and callers at
move-only types break with no signature change. Inside a module that is a local
matter; across a published API it is not, so a `public` generic whose body needs
the `Copy` tier says so in its signature, and the compiler asks for it at the
declaration. Declaring a bound the body then EXCEEDS is also an error:
`<T: ExplicitCopy>` licenses a spelled `.copy()` and nothing more, so a body
reading the value out unwritten would be a copy for some instantiations and an
alias for others.

**Two declaration rules are derived per instance**, since a generic has no
declaration site that could state them for every argument at once:

- a container instantiated at a `NoMove` payload is itself `NoMove`
  (`Wrap<TaskGroup>` may not be relocated; `Wrap<Int>` may);
- a generic whose instantiated signature names an unsafe type must be declared
  `unsafe` (a monomorphized signature is a signature — see *Unsafe Code*).

### Compile-Time Evaluation

**`static_assert` — implemented (design 53).** `const func`, macros, and
compile-time reflection below are still *planned*.

`static_assert(<const-expr>, "message")` is legal at top level and in statement
position. The condition is evaluated at compile time (with authoritative target
layout, so `sizeof`/`alignof` are exact): a false result is a **compile error
carrying the message**, a true result emits **zero code**.

#### The constant grammar

One evaluator answers everywhere a constant is required — a `static_assert`
condition, an array length `[T; N]`, a repeat-literal count `[v; N]`, a const
generic argument, a `static` initializer — so the same expression cannot mean
different things in two positions. A **fixed-width slot** is on that list too
(amended Aug 21 2026): where a declared `Int8`…`UInt64` type is in force, an
operator expression over constants folds and is range-checked against the
declared type, with the same names in scope every other constant position has.
It accepts:

- integer and `Bool` literals, in every notation (`0xFF`, `0b1010`, `0o755`,
  `1_000_000`);
- unary `-`, `not`, and `~`;
- `+ - * / %`, the comparisons, `&&` / `||`;
- the bitwise `&`, `|`, `^` and the shifts `<<`, `>>`;
- `sizeof<T>()` / `alignof<T>()`;
- the `Int.max` / `Int.min` limits, on every integer type;
- a const generic parameter in scope;
- a module `static` of type `Int`/`UInt` whose own initializer folds, bare or
  module-qualified;
- a case of a raw-backed enum, and an `as` between integer types.

Anything else — a runtime function call, a `let` local, a case of an enum with
no backing — is rejected as non-constant, and the diagnostic names the
sub-expression that failed rather than the whole condition.

**A constant is evaluated at the target's integer width.** The domain is the
platform `Int`: signed, pointer-wide, the type a bare integer literal already
has. `<<` wraps at that width exactly as the emitted `shl` does, so `1 << 63` is
`Int.min` on a 64-bit target and `1 << 31` is `Int.min` on a 32-bit one. A shift
count that is negative or `>=` the width is a compile error, which is the
compile-time form of the "shift out of range" panic. A narrower destination is
range-checked where the constant lands (an `as`, a fixed-width slot, an array
length), not inside the arithmetic — so `~0` is `-1`, and `0xFF & ~0` is the way
to say 255. Division and modulo truncate toward zero, matching the runtime
semantics above.

Array lengths and const arguments are resolved during type checking, which is
earlier than struct layout is known, so `sizeof<T>()` is rejected in those
positions while remaining available in a `static_assert`.

```saw
// Kernel register-block drift check
static_assert(sizeof<UartRegs>() == 0x1C, "UartRegs layout drift")
static_assert(alignof<UInt32>() == 4, "unexpected alignment")

static PAGE_SHIFT: Int = 12

static_assert((1 << PAGE_SHIFT) == 4096, "4K pages")
static_assert(((0x1234 + 0xFFF) & ~0xFFF) == 0x2000, "align up")

struct PageTable { entries: [UInt64; 1 << 9] }

func f() {
    static_assert(Int.max > 0, "sanity")   // also valid in statement position
    var page: [UInt8; 1 << PAGE_SHIFT] = [0; 1 << PAGE_SHIFT]
    print(page.len())                      // prints: 4096
}
```

The two length positions take the same expression grammar. `[T; N]` used to
parse a smaller one and fail at the parser on anything outside it, while the
repeat count beside it gave a semantic answer; both now parse everything and the
evaluator gives the one answer.

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
macro vector[$($elem:expr),*] {
    {
        var v = Vector()
        $(v.push($elem);)*
        v
    }
}

let nums = vector![1, 2, 3, 4]

// Derive macros (code generation) — Saw's trait names, and the `@name`
// attribute grammar the language already uses
@derive(Printable, Copy, Equatable)
struct User {
    name: String
    age: Int
}

// Attribute macros
@test
func test_addition() {
    assert(2 + 2 == 4)
}

@inline(always)
func hot_path() { ... }
```

### Compile-Time Reflection

```saw
// Type introspection at compile time
const func field_names<T>() -> [String] {
    T.fields().map { f in f.name }
}

// Generate serialization automatically
@derive(Serialize)
struct Config {
    host: String
    port: Int
}
```

---

## 8. Module System

**Status: implemented.** `import` (module, specific-symbol, and qualified
forms), `public import` re-export, inline and external `module` declarations,
`public` visibility, scoped visibility (`public(package)`, `public(parent)`),
import aliasing (`as`, design 53), glob imports (`import x.*`), and qualified
access (`module.Type`) are all built. The `Saw.toml` package layout is handled
by the Blade package manager.

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

A scoped name is reachable by every spelling its scope allows, not just the
qualified one. From inside the package, `public(package) func internal_api`
answers to `m.internal_api()`, to `import m.{internal_api}` and to the glob
`import m.*` alike; from outside, all three are refused, through a facade's
`public import` re-export as much as directly — a re-export hands on the NAME,
never a wider tier. The import forms are sugar for the qualified reach and are
never the stricter of the set. A refusal names the tier and the DEFINING
module, so the reader learns which modifier to change and where:

```
error: `internal_api` is public(package) in `pkg.secret`
hint: mark it `public` in `pkg.secret` to expose it — a `public import`
      re-export hands on the NAME, never a wider tier
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

extension Account {
    public init(name: String) -> Account { Account(name: name, balance: 0) }
    public func balance_of(&self) -> Int { self.balance }  // public accessor
    func settle(&var self) { ... }                          // private helper
}
```

**An extension HEAD carries no visibility, and writing one is an error.** An
extension is not a nameable entity: nothing imports it, nothing calls it, and
there is no name for a modifier to govern. Its members are what an importer
reaches, and each of them says its own tier — so `public extension Account` is
refused at the modifier, with the fixit "mark each member instead":

```
error: an extension cannot carry a visibility modifier — an extension is not a
       nameable entity, so it has nothing to be visible. Visibility belongs on
       members: mark each one instead (`public func`, `public static func`,
       `public init`), and delete the modifier here
```

Consequences:
- A member marked `public` on a member of a non-public struct is legal but
  inert — the struct itself gates reachability.
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

#### Signature visibility: a public API needs public types

A declaration may not name a type less visible than the declaration's own
reach. A `public` function's parameters and return type are `public`; a
`public(package)` declaration's signature names types that are at least
`public(package)`; a `public` field's type is at least as visible as the field.
A private declaration may name anything, because nothing it names can leave the
module.

```saw
struct Hidden {
    n: Int
}

public func give() -> Hidden {
    Hidden(n: 2)
}
```

```
error: function `give` is public, but the return type names `Hidden`, which is
       private — a public API needs public types
hint: either widen the type — mark the struct `Hidden` `public` — or narrow the
      declaration, so its signature stays where `Hidden` can be named. A caller
      that can reach a declaration must be able to name every type in its
      signature
```

The refusal is at the declaration, which is where both fixes live. Without it a
caller holds a value it cannot name: the type is not in scope, so there is no
annotation to write, no way to declare a field of it, and no way to pass it on.
The rule reads the modifier as written, so it applies inside a single-module
program as much as across a package boundary — the same discipline a `public`
generic follows when it has to declare the tier it requires.

Every position where a declaration names a type is covered: a parameter, a
return type, the type a `borrows` accessor lends, a struct field, an enum case
payload, a `static`'s type, a `type` alias's target, a trait requirement's
signature, a generic parameter's bound and its default, a trait's parent, and
an extension's associated-type assignment. A type ARGUMENT is a named type like
any other, so `Vector<Hidden>` exposes `Hidden` exactly as a bare `Hidden`
does.

A member's reach is capped by the type it belongs to. A `public` member of a
non-public struct is already inert (above), so its effective reach is the
struct's, and the rule asks no more of it than that:

```saw
struct Inner {
    n: Int
}

extension Inner {
    public func widen(&self) -> Hidden {   // fine: `Inner` is private, so this
        Hidden(n: self.n * 3)              // method is unreachable from outside
    }
}
```

Enum case payloads follow their enum's tier, and a trait requirement follows
its trait's, since neither carries a modifier of its own. An extension's own
generics and its associated-type assignments are judged at the widest reach
among its members, which is what a caller meets.

Function BODIES are outside the rule. A local, a `let` annotation, a temporary
and a closure's inferred type are not on the declaration's surface, and every
use of a member is already gated where it happens.

#### Extension scoping (design 142)

Visibility says whether a member MAY be reached. Scoping says whether it is
visible at all. Method lookup on a receiver consults extensions from exactly
three places:

1. the current module;
2. the modules the current file imports DIRECTLY;
3. the receiver type's own defining module — its inherent API, which travels
   with the value.

A transitive dependency contributes nothing. If your package depends on `net`
and `net` depends on `codec`, a `public` method on `codec`'s `extension Data` is
invisible to you until you import `codec` yourself. So `public` on an extension
METHOD means what it means on every other declaration: importers of my module
get this. (The extension's HEAD carries no modifier — see Member visibility.)
Without
the rule, any module anywhere in the link could add methods to any type for the
whole program, and adding an unrelated dependency could change which method a
call resolved to.

Rule 3 is what keeps this workable. A `Data` handed to you by some library is
still a `Data`, with every method `std.data` gave it, whether or not you wrote
`import std.data` — and you may not even be able to write it, since the prelude
rules gate the NAME `Data` separately from the value.

The standard library is one scoping domain. Its files are separate modules for
privacy, but they extend each other's types deliberately (`std.string` defines
`join` on `Vector<String>`), so std's public surface is in scope wherever its
types are.

Two modules may extend one type with the same method name. Where both are
visible they form an ordinary overload set and resolve by signature. Where their
signatures are indistinguishable, the error is at the CALL — each declaration is
fine on its own, and neither module knows the other exists:

```
error: ambiguous method `kind` on `Reading`: `modules.ext142_dup_a` and
       `modules.ext142_dup_b` both extend it with an indistinguishable signature
```

Calling an out-of-scope method names the module that defines it:

```
error: type `Data` has no method `u16_at` in scope here
  hint: `bmod` extends `Data` with `u16_at`, but this file does not import it
        — add `import bmod`
```

#### Conformance coherence: the orphan rule (design 142)

`extension T: Trait` is declarable only in the module that defines `T` or the
module that defines `Trait`. Anywhere else is a compile error naming both
owners.

Methods can be import-scoped because a method is chosen at a call site, where
"which ones can I see" is a fair question with a per-file answer. A conformance
cannot. It mints one vtable per (type, trait) pair and backs a semantic
contract — `Hashable` feeds `Map`, `Equatable` feeds `==` — so two modules
minting different conformances for one pair would let a `Map` built in one
module and probed in another disagree about hashing. No use-site diagnostic can
catch that, because neither site is wrong.

Pinning a conformance to an owner makes it global, which is why conformances
need no import scoping of their own: one declared under this rule is visible
wherever the type and the trait both are.

```saw
// In the module that defines Reading — the type's owner.
extension Reading: Printable {
    public func format(&self, into: &var StringBuilder) {
        try! into.append("Reading(")
        try! into.append(self.raw)
        try! into.append(")")
    }
}

// In the module that defines Describable — the trait's owner, conforming a
// foreign type. Also allowed.
extension Reading: Describable {
    public func describe(&self) -> String { "reading {self.raw}" }
}
```

To conform a foreign type to a foreign trait, wrap it in a type you own.

#### Type identity (design 144)

A type is identified by the module that defines it together with its name. Two
modules that each declare a private `struct Header` declare two different
types, with two layouts, two `Vector<Header>` instantiations and two sets of
methods. The same holds for enums, traits and type aliases.

```saw
// wire.saw
struct Header {
    kind: Int
    length: Int
}

// main.saw — a different `Header`, and not a conflict.
struct Header {
    kind: Int
}
```

A private type therefore reserves nothing outside its own module. Before this,
a dependency's private `Header` made `Header` unusable in every program that
imported the dependency, for a type the program could not name, construct or
see.

Public types of the same name coexist too, since they are also two types. What
one file cannot do is refer to both by the bare name, so import at least one
under an alias:

```saw
import parser.{Header as ParserHeader}
import wire.{Header as WireHeader}

let request = ParserHeader(kind: 1)
let frame = WireHeader(kind: 2, length: 8)
```

Importing both under the bare name is legal; using it is not. The error names
both modules at the use site:

```saw
import parser.{Header}
import wire.{Header}

let h = Header(kind: 1)
// error: ambiguous struct `Header`: defined in both `parser` and `wire`
// hint: qualify the use (e.g. `parser.Header`), or import `Header` from a
//       single module
```

Names are unchanged by any of this. A diagnostic, a `--emit-docs` page and an
AST dump all show the name as written; where two types would print alike,
`--emit-docs` carries the defining module in a `module` field beside the name.

The standard library is under the same rule. Each std file is its own module
(see *The prelude* below), so a type a std file keeps to itself belongs to that
file. `std/once.saw` declares a private `State` and `std/map.saw` a private
`MapSlot`; a program may declare either name, and its own declaration is what
every use resolves to:

```saw
enum State: Int {
    case Idle = 0,
    case Busy = 1
}

func main() {
    print("{State.Busy as Int}")   // prints: 1
}
```

Two std files may each own one name for the same reason two packages may. What
std PUBLISHES is unaffected: `Vector`, `File`, `Data` and the rest of the API
keep the exposure the prelude and the import forms give them, and a second
declaration of one of those names is the redefinition error it has always been.

### The prelude (design 82)

Not all of std is auto-visible. The **prelude** — the names usable without an
`import` — is a curated core:

- primitives (`Int`, `UInt`, the fixed-width ints, `Float`, `Bool`, `String`,
  `Void`, `Never`), core containers (`Vector`, `Map`, `Set`), core wrappers
  (`Optional`, `Result`, `Box`, `Arc`, `Allocator`, `GlobalAllocator`);
- core traits (the Copy family, `Deinit`, `Iterator`, `Equatable`, `Comparable`,
  `Hashable`, `Printable`, `Error`, `Send`, `Sync`);
- the builtins (`print`/`panic`/`assert`/`sizeof`/`alignof`/`static_assert`) and
  the concurrency primitives (`TaskGroup`, `sleep`, `spawn`, `cancelled`);
  `StringBuilder` (common enough to stay bare); `Duration`, because `sleep` is
  a prelude builtin and a `Duration` is the only thing it takes.

Everything else in std is **import-required**: `File`, `Directory`, `Path`,
`Data`, `Channel`, `Mutex`, `SpinLock`, `Once`, `Instant`, `IoError`, `Utf8Error`, the
whole `net` surface (`TcpListener`/`TcpStream`), `yield_now` (std.task —
design 114), `FixedBuf`/`FixedStringBuilder` (std.fixedbuf),
`CborEncoder`/`CborDecoder` (std.cbor), `SlabHead` and the slab free
functions (std.slab), and the
`process`/`env`/`time` contents. These stay compiler-known for codegen but are not injected into a
user namespace without an import of its module. A bare reference to one is a
clean error ("`TcpStream` is not in the prelude and must be imported") naming
the three import forms that supply it. Because a non-imported std module is not
even compiled into the program, a user is free to define its OWN
`IoError`/`File`/etc. with no clash.

The gate covers **every position a type is written**, not only the positions
that build a value of it. A signature that merely receives a gated type needs
the import as much as one that constructs it:

```saw
func take(d: &Data) -> Int { d.len() }
// error: `Data` is not in the prelude and must be imported
```

The full set: a parameter, a return type, a `let`/`var` annotation, a struct
field, an enum case payload, a `type` alias right-hand side, a `static`'s type,
a generic argument, a tuple element, an array element, a function type's
parameter or return, and the trait of an `any Trait` existential. What is
checked is the name **as written**, so the qualified spelling is accepted
wherever an import bound the qualifier — `func take(d: &data.Data)` under
`import std.data` is fine.

The prelude is independent of the import forms below: it needs no import, and
`import std.vector` binds a `vector` qualifier over a module whose names were
already bare.

A std module's surface is the types it declares `public`. Everything else it
declares is internal to its own file: not in the prelude, not reachable through
any import form, and not a name a program has to avoid. Asking for one is a
clean error naming what the module does have.

```saw
import std.file.{OpenMode}
// error: `OpenMode` is not defined in `std.file`
// hint: available: File
```

### Imports

There are three import forms, and they mean the same thing for std as for any
other module.

| Form | What enters scope |
|---|---|
| `import std.file` | the qualifier `file`; nothing bare |
| `import std.file.*` | every public name of the module, bare; no qualifier |
| `import std.file.{File, Path as P}` | `File` and `P` bare; no qualifier |

**Each form binds exactly what it names.** Only the whole-module form binds a
qualifier — a selective or glob import gives you the names it lists or takes and
nothing else. That is the point of the braces: the import list is what documents
the dependency, and a free reach into everything the list did not name is the
undocumented dependency the form exists to prevent.

A file that wants both writes both, on two lines that name one module:

```saw
import std.file
import std.file.{File}

func open_it(p: Path) -> Result<File, IoError> { File.open(p) }
func exists(p: Path) -> Bool { file.File.exists(p) }
```

They are **complementary, not conflicting** — the duplicate-qualifier error
below is about two imports of two DIFFERENT modules — and the bare and qualified
spellings are then **one type** everywhere: an annotation, a construction, a
generic argument, an `any` existential, a generic bound, a struct field, an enum
payload, a `type` alias, and extension and conformance lookup all see the same
type with the same identity.

What an import binds is private to the file that writes it. Each form takes an
optional `public` prefix to hand it on; see [Re-export](#re-export).

**Whole module** binds the last path segment as a qualifier and exposes no bare
names. Reach the module's contents through it:

```saw
import std.time
import std.data

func since(t: time.Instant) -> Duration { t.elapsed() }  // annotation

func main() {
    let started = time.Instant.now()                     // static method
    var buffer: Vector<data.Data> = []                   // generic argument
    try! buffer.push(data.Data())                        // constructor
    print("{since(started).as_micros()}")
}
```

A qualifier works in every position a type or function name appears: type
annotations (including behind `&`/`&var` and inside `Optional`), return types,
generic arguments, call heads, constructors, static-method chains, enum
construction, `any` existentials, and generic bounds. Declaration slots take it
too: a struct field's type, an enum case payload's type, and a `type` alias
right-hand side.

```saw
import shapes

func describe(s: &any shapes.Named) -> String { s.label() }
func widest<T: shapes.Named>(t: &T) -> String { t.label() }

struct Scene { backdrop: shapes.Circle }
enum Chosen { case Picked(s: shapes.Circle), case Nothing }
type Outline = shapes.Circle
```

**Glob** is the explicit opt-in for bare names — the "give me this module's
vocabulary" form:

```saw
import std.path.*
let p = Path(s: "/etc/hosts")
```

**Selective** names what it takes, and takes exactly that:

```saw
import std.net.{TcpListener, TcpStream}
let listener = try! TcpListener.listen(0)      // selected, bare
let err: net.IoError = ...                     // error: `net` is not a
                                               // module qualifier here
```

Add `import std.net` beside it to write the qualified form, or select
`IoError` too.

`as` renames the qualifier a whole-module import binds; inside braces it renames
one symbol:

```saw
import std.time as clock                       // clock.Instant.now()
import mypkg.collections.{Map as Dict}         // Dict, not Map
```

`package` and `parent` prefixes resolve a path relative to the current package
or the parent module:

```saw
import package.parser.{Parser}
import parent.helpers.{utility}
```

A bare reference to a name that only a qualifier is in scope for is a clean
error naming all three forms:

```
error: `Data` is not in the prelude and must be imported
hint: `import std.data.{Data}` selects it, `import std.data.*` takes the
      module's whole vocabulary bare, and `import std.data` lets you write
      `data.Data`
```

And the mirror — a qualified reference whose qualifier no whole-module import
bound — names the line that would bind it, in a type position and an expression
position alike:

```
error: `data` is not a module qualifier here
hint: `import std.data.{...}` binds the names it takes and no qualifier —
      add `import std.data` to write `data.<name>`
```

#### Re-export

An import binds names for the file that writes it. It does not put them on that
module's surface. A module's surface is what it declares `public`, so an
importer of `parser` reaches `parser`'s own public declarations and nothing
`parser` merely imported:

```saw
// parser.saw
import wire.{Header}

public func parse(bytes: &Data) -> Header { ... }
```

```saw
// app.saw
import parser

func first(h: &parser.Header) -> Int { h.tag }
```

```
error: `Header` is not part of `parser`'s surface
  --> app.saw:3:13
hint: `Header` is imported by `parser` but not re-exported — add `public
      import` in `parser`, or import `wire` directly
```

Reachability is the visibility chain, so every spelling gets the same answer:
the bare name under `import parser.*`, the selection `import parser.{Header}`,
the qualified `parser.Header`, and the chain `parser.wire.Header` are all
refused. std is imported on the same terms — a module's `import std.data` is
that module's, and `parser.data.Data` from outside is the same refusal.

`public import` is the opt-in, and no form is refused it. Each hands on what
its own shape binds:

| Form | What an importer of this module reaches through it |
|---|---|
| `public import wire` | the qualifier: `parser.wire.Header` |
| `public import wire.{Header}` | `Header`, bare and as `parser.Header` |
| `public import wire.*` | every public name of `wire`, bare and qualified |

A selective re-export hands on the names it lists, and nothing else — it binds
no qualifier of its own to hand on — so `public import wire.{Header}` publishes
`Header` without publishing the rest of `wire`. That is what a curated facade is
made of: a module can publish the handful of types its callers need and keep the
internals they sit beside unreachable.

Two things a re-export does not change. The module's own view of its imports is
the same either way: `public` on an import controls what flows through the
module, not what the module sees. And it does not widen extension scope — a
re-exported type keeps its own module's extensions, which travel with the type
(see [Extension scoping](#extension-scoping-design-142)), and no other module's
extensions come with it.

`public(package) import` and the other scoped visibilities are not accepted;
re-export is all or nothing.

#### Qualifier bindings are weak

A qualifier is the lowest-priority name in scope. Resolution runs local scopes,
then module-level declarations, then imported bare names, and consults
qualifiers last. So a local, parameter, or loop variable may take a qualifier's
name, with no shadowing error:

```saw
import std.data

func fresh() -> data.Data { data.Data() }      // `data` is the module here

func main() {
    var data = fresh()                          // the local wins from here
    try! data.push(65)
    print("{data.len()}")                       // a method call, not a module access
    print("{fresh().len()}")                    // the module again, inside `fresh`
}
```

The shadow is lexical: outside the declaring scope the qualifier reaches the
module. This matters because std leaf names — `data`, `path`, `time`, `net` —
are among the most natural local names in the language, and importing a module
may not cost the author the word.

When member lookup then fails on a shadowing value, the error says why:

```
error: type `Int` has no method `Data`
hint: `data` here is the binding declared on line 4, which shadows the module
      qualifier bound by `import std.data` — rename the binding, import the
      module as another name (`import std.data as <name>`), or select `Data`
      directly (`import std.data.{Data}`)
```

`sawc -W shadowed-qualifier` flags the declaration instead of waiting for the
use. See [Compiler warnings](#compiler-warnings).

#### Qualifier collisions

Two imports binding one qualifier is an error at the import, naming both paths.
`as` resolves it:

```saw
import std.data
import data              // error: two imports bind the qualifier `data`:
                         //        `std.data` and `data`
                         // hint: rename one with `as`, e.g. `import data as <name>`
```

The second import there names YOUR module, not std's. `sawc/std/` is reachable
only through a `std.`-prefixed path: a bare `import data` searches the importing
file's own directory, its package root and the configured search paths, and
stops. So a user module named after a std leaf is an ordinary module — the
collision above is a collision of QUALIFIERS, which `as` fixes, and never a
second compilation of a std file.

#### Import cycles

Two modules that import each other, directly or around a longer loop, are a
compile error naming the loop. There is no order in which to check them — each
needs the other's names first — so the compiler says which modules are in the
cycle and where each edge is written, rather than picking an order and letting
the failure land on whichever module lost:

```
error: import cycle: pkg.a -> pkg.b -> pkg.a
  --> pkg/a.saw:5:1
hint: `pkg.a` imports `pkg.b` (line 5); `pkg.b` imports `pkg.a` (line 4)
      — break the loop by moving the shared declarations into a module both
      sides import
```

A module importing ITSELF is not a cycle: it asks for names it already has, and
it compiles.

#### Import form and extension visibility

Extension methods and conformances are import-scoped (see
[Extension scoping](#extension-scoping-design-142)). Every import form makes the module a
direct import, so choosing qualified access never silently loses a module's
extensions.

### Compiler warnings

`sawc -W <name>` enables a warning category; `-W all` enables every one.
Warnings are off by default and never affect the exit code — there is no
`-Werror`. An unrecognized category is an error, so a misspelled flag cannot
quietly disable itself and read as a clean build.

| Category | Reports |
|---|---|
| `shadowed-qualifier` | a declaration takes the name of a module qualifier bound by an import, so qualified access is unavailable in its scope |

```
$ sawc app.saw -W shadowed-qualifier
warning [-W shadowed-qualifier]: `data` shadows the module qualifier bound by `import std.data`
  --> app.saw:5:5
   |
 5 |     var data = fresh()
   |     ^
   hint: qualified access is unavailable while this binding is in scope —
         rename it, or write `import std.data as <name>`
```

The warning fires at the declaration. The use-site error it anticipates is
unconditional.

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

**Status: partially implemented.** Each std file is its own module (design 82),
so the module list below is also the import list: a leaf name is what
`import std.<leaf>` binds as a qualifier.
Actually shipped today: `String`, `StringBuilder`, `Vector<T, A>`,
`Map<K, V, A>`, `Set<T, A>`, `Arc<T>`, `Box<T, A>`, `Mutex<T>`, `Channel<T>`,
`Thread<T>`, `TaskGroup`, `File`, `Directory`, `Path`, `Data`, `Env`,
`Command`/`ProcessError` (std.process — a real argv spawn, never a shell: one
`arg()` is one argv element and nothing in it is split, expanded or executed;
run `/bin/sh -c` explicitly if a shell is what you want, design 122. `env(name:
value:)` sets one environment variable for the child under the same rule, on top
of the environment it inherits; `merge_stderr()` sends its standard error
wherever its standard output goes. `run()` and `output()` are both COOPERATIVE:
the wait parks on the child's exit through the reactor and the stdout drain runs
on a worker thread, so siblings run for the child's whole lifetime and no thread
waits. Cancelling the task ends the WAIT — the child keeps running, and
`ProcessError.cancelled()` tells that apart from a launch failure),
`std.net` (`TcpListener`/`TcpStream`),
`std.duration` (`Duration`) and `std.time` (`Instant`), plus `Int`/`Float`
numeric extensions and the
`Equatable`/`Comparable`/`Hashable`/`Printable`/`Error` traits (and
`Result`/optionals as language features). `RwLock` and I/O beyond files and
sockets are still planned. There is no `async`/`future`
module: concurrency is colorless (no `async`/`await`).

### The modules

`Optional` and `Result` are language features rather than modules — the empty
case is the keyword `None`, and there is no `Some(...)` constructor. Everything
else lives in one of these files. The prelude column says whether the module's
names are bare already (see [The prelude](#the-prelude-design-82)); the rest
need one of the three [import forms](#imports).

| Module | Principal names | Prelude |
|---|---|---|
| `std.vector` | `Vector<T, A>` | yes |
| `std.map` / `std.set` | `Map<K, V, A>`, `Set<T, A>` | yes |
| `std.string` | `String` methods, `Utf8Error` | `String` only |
| `std.stringbuilder` | `StringBuilder` | yes |
| `std.arc` / `std.box` | `Arc<T>`, `Box<T, A>` | yes |
| `std.alloc` | `Allocator`, `GlobalAllocator`, `AllocError` | `Allocator`, `GlobalAllocator` |
| `std.slab` | `SlabHead`, `slab_alloc`, `slab_dealloc` | no |
| `std.numeric` | the `Int` / `Float` extensions | yes (methods on primitives) |
| `std.taskgroup` | `TaskGroup`, `Task<T>`, `VoidTask` | yes |
| `std.task` | `yield_now`, `Thread<T>`, `VoidThread` (the `Thread.spawn` handles) | no |
| `std.channel` | `Channel<T>`, `ChannelError` | no |
| `std.mutex` / `std.spinlock` | `Mutex<T>`, `SpinLock<T>` | no |
| `std.once` | `Once<T>` | no |
| `std.data` | `Data` | no |
| `std.file` / `std.directory` / `std.path` | `File`, `Directory`, `Path` | no |
| `std.net` | `TcpListener`, `TcpStream`, `IoError` | no |
| `std.process` / `std.env` | `Command`, `ProcessError`, `Env` | no |
| `std.duration` | `Duration` | yes |
| `std.time` | `Instant`, `unix_timestamp` | no |
| `std.fixedbuf` | `FixedBuf<N>`, `FixedStringBuilder<N>` | no |
| `std.serde` | `Serialize`, `Deserialize`, `Encoder`, `Decoder`, the error types | yes |
| `std.cbor` | `CborEncoder`, `CborDecoder`, `encode` | no |
| `std.compiler.frame` | `Slot<T>`, `UnsafeRef<T>`, `Poll`, `Resumable` | no |

Concurrency has no module of its own beyond those: it is colorless, with no
`async`/`await`. The NAMESPACE is the engine.
`Thread.spawn { ... } -> Thread<T>` is the OS-thread engine;
`group.spawn(f(args))` and `Task.spawn(f(args))`, both `-> Task<T>`, are the
cooperative one. See [§6 Concurrency](#6-concurrency) for the real API.

`Iterator`, `Equatable`, `Comparable`, `Hashable`, `Printable`, `Error`, `Send`
and `Sync` are prelude traits declared in `builtin.saw`, not module contents.
`Atomic<Int>` is likewise a builtin, not a module: prelude-bare, nothing to
import. There is no `Deque`, no `RwLock`, and no `UdpSocket` yet.

`std.slab` and `std.spinlock` were the two rows this table got wrong: both
documented as gated, and neither listed in the compiler's set, so `SlabHead` and
`SpinLock` resolved with no import at all. Both are gated now. The table above is
checked against the compiler's list on every run of `make preludegate`, so a
future row and the behaviour behind it cannot drift apart in silence.

**`std.fixedbuf`** is **implemented** (`std/fixedbuf.saw`) and works in both
profiles: it allocates nothing. `FixedBuf<N>` is `N` bytes of zeroed storage held
inline, sized by a const generic parameter, with `capacity()`, `get`/`set`
(bounds-checked, panicking out of range), and `ptr()` for the unsafe paths that
need an address. `FixedStringBuilder<N>` is a `StringBuilder` over one of those
buffers: the same `append` surface, the same truncation behaviour (content that
does not fit is cut on a UTF-8 boundary and marked `…`, reported by
`is_truncated()`), and no allocator anywhere. `N` counts the whole buffer, of
which four bytes are held back for the marker and terminator, so
`FixedStringBuilder<64>` holds 60 bytes of text; an `N` below 5 is a compile
error.

```saw
import std.fixedbuf.*

var out = FixedStringBuilder<64>()
out.append("n = ")
out.append(42)
print(out.as_string())      // prints: n = 42
```

**`Duration`** is a span of time, `UInt64` whole nanoseconds, and is in the
prelude. Build one with `Duration.ns`, `us`, `ms` or `secs`; read one back with
`as_nanos`, `as_micros`, `as_millis`, `as_secs`. It is Equatable, Comparable and
Printable, rendering a human form like `1.42s` or `230ms`.

```saw
let nap = Duration.ms(200)
print("{nap}")              // prints: 200ms
sleep(nap)
```

The backing is unsigned because a span is a magnitude, and the whole u64
nanosecond range — about 584 years — is reachable from every constructor, so no
span a caller can spell wraps into a shorter one. A constructor whose argument
would scale past that range panics naming itself:

```saw
let d = Duration.secs(18446744074)
// panic at duration.saw:79: Duration.secs: 18446744074 seconds is past the
// representable span
```

**`std.time`** is **implemented** (`designs/57`, `std/time.saw`) and
**hosted-only** (it links libc for the clock; freestanding kernels provide their
own timer): `Instant.now()` (a monotonic clock), `elapsed()`, and
`duration_since(earlier:)`, all three handing back a `Duration`; and a free
`unix_timestamp() -> Int64` (wall-clock seconds since the Unix epoch). `Int64`
nanoseconds keep the `Instant` layout stable across platform Int widths. The two
span methods panic rather than report a negative one: `elapsed` if the monotonic
clock stepped backward, `duration_since` if `earlier` is in fact the later of
the two.

**`std.compiler.frame`** is the frame vocabulary the coroutine transform
compiles against: `Slot<T>`, `UnsafeRef<T>`, and the `Resumable` trait every
generated frame conforms to with its `Poll` signal enum. It is import-gated and it is not written for
everyday code — reach for a plain `let` in ordinary Saw — but it is PUBLIC, and
that is a decision rather than an accident. Generated code is held to the
ordinary ownership rules, so the transform may emit only code a programmer
could have written; a vocabulary the compiler could reach and you could not
would be a second set of rules with nothing checking it.

`Slot<T>` is storage that either holds a `T` or is empty. It is where a frame
keeps a local across a suspension, and its occupancy is part of the type:

```saw
import std.compiler.frame.{Slot}

var s = Slot<String>.empty()
s.put("payload")
print(s.value().len())      // prints: 7
let owned = s.take()        // the slot is empty again
```

`put` installs a value and drops the previous occupant if there was one.
`take` moves the occupant out and panics on an empty slot — the caller's state
machine is the proof that it is not empty, and a wrong proof reports itself
rather than handing back a husk. `clear` drops the occupant if there is one and
is idempotent, which is what a frame's teardown runs per field. `value()` is a
`borrows` accessor, so reads, writes and method calls reach the payload where
it sits. `is_occupied` answers the tag.

The field is private, which is the whole guarantee: a payload leaves a slot by
exactly four operations — `take`, `clear`, a `put` onto an occupied slot, and
the synthesized deinit — and each of them updates the tag in the same body that
moves or drops the payload. Released exactly once is therefore a property of
the type. A slot is `NoCopy`, and a `NoMove` `T` does not belong in one: `put`
and `take` are moves, and a pinned value's storage is a plain field.

`UnsafeRef<T>` is a pointer to a `T` that something else owns — a frame's
method receiver, and the reference parameters it carries across a suspension.
It owns nothing and is never dropped. `deref()` lends the referent as a place,
and the WINDOW MODE comes from the binding: a `var`-bound handle can open an
exclusive window and a `let`-bound one cannot, so a `&self` receiver and a
`&var self` receiver get the right window out of one declaration. `copy()`
returns a second handle to the same referent; the type is `NoCopy` so that
duplication is written where it happens.

The validity contract is the part the compiler does not check: every `deref`
must happen while the referent is alive, and the referent must not have moved.
A handle over storage that outlives it by construction satisfies that; a handle
over anything else does not, and nothing will say so. The obligation has a
carrier rather than a proof — `UnsafeRef` is an `unsafe struct`, so every
function that mints, holds or dereferences one is `unsafe`-declared and is
reviewed as the unit that owns the argument.

`Resumable` is the protocol a frame answers to: `resume` (advance one step,
returning `Poll.Pending` or `Poll.Done`), `wake_reason`, `is_cancelled`,
`bt_desc`, and `release` (drop what the
frame still owns). `Poll` is the signal enum, published in the same module so
that the trait's whole signature — types and names both — is one a reader can
write down. Conforming by hand grants nothing — spawning and enqueuing
are lowered by the compiler against frames it built itself, and THAT gate is
what keeps a user conformance inert, not any unspellability in the signature.
`release` carries the contract eager teardown needs: it may run before
the frame's deinit, and the deinit is a no-op afterwards.

### Profiles (hosted and freestanding)

**Status: freestanding stage 1 implemented.** Saw compiles under two profiles.
The default **hosted** profile links libc and provides everything above. The
**freestanding** profile (`sawc --freestanding`, optionally with `--target
<triple>`) targets kernels and bare-metal: it links no libc and emits an
unlinked object file. In this profile the runtime rests on the `__saw_rt_*` seam
symbols the environment must supply at link time — `__saw_rt_alloc(size, align)`,
`__saw_rt_dealloc(ptr, size, align)`, `__saw_rt_write(ptr, len)`, the noreturn
`__saw_rt_panic(msg, len)` and the rest of the frozen set — which the hosted
profile satisfies by linking a runtime built from `sawc/rt/`. Freestanding
programs may use `core` and the `alloc`-layer types (`String`, `Vector`, `Map`,
`Data`, `StringBuilder`, `Path`), which allocate only through the seams; the
hosted-only modules (`File`, `process` (`Command`), `Env`, `Directory`, `time`,
`net`) and `Float`
printing are unavailable. See `designs/19-freestanding-profile.md` for the full design.

**A package may BE the runtime.** `[package] runtime = true` in `Saw.toml`
declares a package a runtime provider (blade passes `sawc
--runtime-provider`). It may then `@export` the frozen `__saw_rt_*` names, no
runtime of the compiler's is linked beside it, and every exported seam's
signature is checked against the contract in `sawc/rt/ABI.md` at compile time. A
mismatch — the wrong arity, or a `word` return where the ABI says `Int64` — is a
compile error naming the document, rather than a clean link and a wrong answer at
run time. `sawc --runtime-build`, which is how `sawc/rt/` itself is compiled, is
the same permission plus a std-free unlinked build; a kernel wants the package
form.

**On aarch64 the freestanding profile turns Advanced SIMD OFF**
(`-neon,-fp-armv8`, design 172). An AArch64 core traps every SIMD instruction at
EL1 out of reset — `CPACR_EL1.FPEN` is 0 — and LLVM reaches for `q` registers to
move a struct, so a kernel that had not yet enabled FP faulted on its first block
copy. Nothing reported it, because the fault arrived before the exception vectors
were installed. A freestanding target is by definition one where no OS has
enabled FP, so the profile says so instead of each kernel author rediscovering
it. The general-registers-only lowering is complete: the backend has an
instruction for everything, and the cost is a few extra `ldp`/`stp` pairs on a
large struct move.

`--target-features` OVERRIDES it completely. A kernel whose boot code *does*
enable `CPACR_EL1.FPEN` before any compiled code runs, and that wants the
vectorized block moves back, asks for them by name:

```bash
sawc kernel.saw -o kernel.o --freestanding --target aarch64-unknown-none-elf \
    --target-features +neon,+fp-armv8
```

Note what such a kernel takes on with them: SIMD registers are live state, so
every context switch has to save and restore them.

Other targets get no default of their own — riscv32 still needs an explicit
`--target-features +m,+a,+c`, because *which* extensions a RISC-V part has is a
fact about the part, not about the profile.

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
are **no** `unsafe` blocks and no unsafe regions: unsafety is type-carried, and a
declaration that touches an unsafe type declares the effect in its signature (see
[Unsafe Code](#unsafe-code) below). Still *planned*: C-varargs on the export
side. (The spec's `*Char`/`*var Void` shorthand is illustrative; the implemented
spelling is `UnsafePointer<T>` / `UnsafeConstPointer<T>`.)

### C FFI

```saw
// Declare external C functions
extern "C" {
    func puts(s: UnsafeConstPointer<Int8>) -> Int
    func malloc(size: Int) -> UnsafePointer<Int8>?
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

A handful of C symbols the compiler declares for its own lowering — `printf`,
`snprintf`, `strcpy`, `strcat`, `abort` — may be declared here too, and the two
declarations share one symbol when they agree:

```saw
extern "C" {
    func printf(format: UnsafeConstPointer<Int8>, ...) -> Int32
}
```

A declaration that disagrees is refused at the declaration, naming the signature
the compiler used:

```saw
extern "C" {
    func printf(format: UnsafeConstPointer<Int8>, ...) -> Int
}
// error: `printf` is declared `extern "C"` here with a signature the compiler's
//        own declaration of that symbol does not have
// hint: the compiler declares `printf` for its own string, format and panic
//       lowering, as `i32 (i8*, ...)` — declare it the same way to share the
//       symbol, or give your declaration a different name
```

### Function pointers (`FuncPointer<F>`)

**Status: implemented.** `FuncPointer<F>` is the address of compiled code whose
signature is `F`. It is one machine word with no environment beside it, so it
is exactly a C function pointer at the ABI: a callback C can call, and an entry
point a loader can jump to. Functions are not first-class values in Saw. This
type covers the two cases that need one anyway, and nothing more.

`F` is a function type and it must be `sync`. A suspending body runs out of a
frame, and a bare address has nowhere to keep one, so a suspending `F` is a
clean error at the type:

```saw
FuncPointer<(Int) sync -> Int>          // ok

FuncPointer<(Int) -> Int>
// error: `FuncPointer`'s type argument must be `sync`, but `(Int) -> Int` may
// suspend

FuncPointer<Int>
// error: `FuncPointer`'s type argument must be a function type, but `Int` is not
```

`FuncPointer<F>` is a safe type. Construction is closed — the two forms below
are the only ways to build one, and both hand over code the compiler has
checked against `F` — so possession and the call are sound for every input, and
an API receiving one needs no `unsafe`. Code is immortal, so a function pointer
cannot dangle. It copies bitwise, and `Send`/`Sync` derive.

**Form 1: a zero-capture closure literal**, coerced wherever a `FuncPointer` is
expected. The literal is emitted under `F`'s own ABI, with no environment
parameter, so it allocates nothing:

```saw
let doubler: FuncPointer<(Int) sync -> Int> = { n in n * 2 }
print("{doubler(21)}")                  // prints: 42
```

The literal may capture nothing, and what counts as a capture is what the body
names — an enclosing local, or a method's `self`, whether or not a capture list
mentions it:

```saw
func make(bias: Int) -> FuncPointer<(Int) sync -> Int> {
    { n in n + bias }
    // error: a closure coerced to `FuncPointer` may capture nothing, but this
    // one captures `bias`
}
```

There is no environment for the captured value to travel in. Pass the state
through the argument parameter instead, or read it from a `static`.

**Form 2: a named function**, non-generic and declared `sync`:

```saw
func doubled(n: Int) sync -> Int { n * 2 }

let f: FuncPointer<(Int) sync -> Int> = doubled
```

The signature must match `F` exactly — parameter types and return type, with no
conversions. When the name carries several overloads, the `FuncPointer` type
selects among them. A generic function is refused: a `FuncPointer` names one
compiled body, and a generic names a family.

Both forms work in every position that supplies an expected type: a call
argument, an annotated `let`, a struct field initializer, a `return`, and a
`static` initializer. The last is what lets a dispatch table be a `static` —
the address is a link-time constant, so the table costs no startup code.

```saw
struct Handler {
    code: Int32,
    run: FuncPointer<(Int) sync -> Int>,
}

static TABLE: Handler = Handler(code: 7, run: { n in n + 1 })
```

Calling one is an ordinary call expression. Arguments are positional (a
function type carries no parameter names), and the call needs no ceremony. A
pointer held in a field is called in place:

```saw
func apply(p: FuncPointer<(Int) sync -> Int>, n: Int) -> Int { p(n) }

let t = TABLE
print("{t.run(41)}")                    // prints: 42
```

**`from_raw` is the one member that forges a pointer** out of an address
nothing verified, for a C callback arriving through FFI and for a loader
reading an entry PC. It takes a raw pointer, so it is `unsafe` by the ordinary
rule, and the caller owes the promise that the address is a function of
signature `F`:

```saw
func entry_at(pc: Int) unsafe -> FuncPointer<(UInt) sync -> Never> {
    FuncPointer<(UInt) sync -> Never>.from_raw(pc as UnsafePointer<UInt8>)
}
```

A C function taking a callback declares it with the `FuncPointer` type, and
either construction form crosses:

```saw
extern "C" {
    func qsort(base: UnsafePointer<Int32>, nmemb: UInt, size: UInt,
               compar: FuncPointer<(UnsafeConstPointer<Int32>,
                                    UnsafeConstPointer<Int32>) unsafe sync -> Int32>)
}
```

`F` carries `unsafe` here because its signature names raw pointers, which is
the same rule every function type follows. The `FuncPointer` itself stays safe.

### Attributes (design 58)

**Status: implemented.** Attributes are Swift-style `@name` / `@name("string")`
lines placed immediately before a declaration. They are legal on top-level
`func` and `static` declarations (`@export`, `@section`) and on `extension`
declarations (`@synthesize`). An attribute on a struct, enum, trait, type alias,
extern block, method, or local is a clean "attributes are not supported on X"
error; an attribute on the wrong one of the two accepting positions names what
is legal there instead. An unknown attribute name, a repeated attribute, or the
wrong argument shape is a compile error. The set is `@export`, `@section` and
`@synthesize`; `@inline` is reserved for a later design.

**`@export` / `@export("sym")`** makes a function or static callable from C. It
is one unified attribute whose meaning is inseparable: **C calling convention +
exact unmangled symbol** (or the explicit `"sym"`) **+ external linkage + kept
alive through DCE** (via `@llvm.used`, so it survives the default -O1 pipeline
even when nothing in the program references it — the `_start` / vector-table
shape). There is deliberately no separate `no_mangle`/`c_abi` split.

An export is a keep-root at all three points where unreached code is discarded:
the `-O1` pipeline above, code generation (which emits only the functions
reachable from `main`, the exports, and an `@section` placement), and the link
(`-dead_strip` on mach-O, `--gc-sections` on ELF). So an exported function that
nothing in the program calls is still in the object and still in the executable.

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
(`main`, `saw_*`, `__saw_*`) is an error. **Exception — the runtime-build mode
(design 113b):** the per-host Saw runtime under `sawc/rt/` implements the
`__saw_rt_*` ABI (`sawc/rt/ABI.md`). Compiling it with `sawc --runtime-build`
loosens the reservation for EXACTLY the frozen `__saw_rt_*` ABI names (a
misspelled/non-ABI `__saw_rt_*` export is a clean error naming the valid set; a
suspending seam body is rejected — the runtime is sync-only); every other
reserved name stays rejected, and an ordinary compile keeps the full reservation.
`@export` composes with overloading
(the exact-match model): an exported function's *name* may be overloaded
Saw-side, but only **one** overload may carry `@export` without an explicit
symbol name — otherwise both would claim the same unmangled symbol. `public` is
not required (export is its own visibility to the linker), but module visibility
still governs Saw-side callers.

**`@section("name")`** places a top-level function or static in the named
object-file section (the LLVM section attribute). It composes with `@export` and
does not require it; the name is passed through verbatim (the linker's problem)
beyond a non-empty check. Section-name *syntax* is target-specific — ELF accepts
`.vector_table`, mach-o requires the `SEG,sect` form. Getting it wrong on a
mach-O target is a compile error naming the declaration and the two-part form:

```saw
@section(".vector_table")
func kernel_entry() -> Int32 { 0 }
// error: `@section(".vector_table")` is not a valid section on this target:
//        mach-O names a section by SEGMENT and section, separated by a comma
// hint: write the two-part form — `@section("__TEXT,vector_table")` for code,
//       `@section("__DATA,vector_table")` for data. ...
```

```saw
// The freestanding vector-table idiom (design 58 Part 3):
@export("_vectors")
@section(".vector_table")
static VECTORS: [UInt32; 64]        // externally-visible, kept alive, in-section
```

#### Synthesized conformances

**`@synthesize`** goes on an `extension` and asks the compiler to derive the
conformance's method from the type's fields. It takes no argument.

```saw
struct Version {
    major: Int,
    minor: Int,
    patch: Int
}

@synthesize
extension Version: Comparable {}     // lexicographic over the three fields
```

Five traits derive a body, each from the declaration order of the type's fields
(or, for an enum, its variants and their payloads):

| Trait | Derived method | Body |
|---|---|---|
| `Copy` / `ExplicitCopy` | `copy` | memberwise; POD fields bitwise, policy fields via their own `copy`. For an enum, over the active variant's payload |
| `Equatable` | `equals` | memberwise `&&`; payload-deep for enums |
| `Comparable` | `compare` | lexicographic in declaration order |
| `Hashable` | `hash` | streams exactly the fields `==` compares |

The rule is the same for all five: a **declared** conformance derives its body
only under `@synthesize`. Writing the conformance means the body is yours unless
you ask for the compiler's, so a conformance that is neither marked nor
hand-written is a compile error naming the type, the trait and the missing
method. What the marker acknowledges is that the derived body ranges over
whatever fields the type happens to have — add a field later and `==`,
`compare`, `hash` or `copy` changes with it.

Two things the marker does **not** reach:

- **Auto-conformance.** A trivial (POD) struct and a payload-free enum conform to
  `Equatable` and `Hashable` with no declaration at all, so there is nothing to
  mark. `@synthesize` applies only where a conformance is written.
- **Traits with no derivation**, such as `Printable`. A marker that derives
  nothing is an error rather than silently inert — which also catches marking a
  conformance that already has a hand-written body.

A derivation that cannot be written is reported against the member that blocks
it: `@synthesize` on a copy policy for a struct with a `NoCopy` field names that
field, as do `Equatable`/`Comparable`/`Hashable` over a member that does not
itself conform.

Destruction is not on this list. A `deinit` is synthesized for every type that
owns something, with no marker and no declaration; see
[Synthesized destruction](#synthesized-destruction).

### Unsafe Code — unsafe types, and the functions that touch them

**Status: implemented (design 130, superseding design 81's marking rules).**

**Principle: unsafety is carried by TYPES, and a function that touches one
declares it.** Saw has no `unsafe { }` blocks and no unsafe regions. Where a
construct carries a proof obligation the compiler cannot discharge, a *type*
names it, and the obligation then travels with every value of that type and
every signature that mentions one.

#### Unsafe types

The built-in unsafe types are `UnsafePointer<T>` / `UnsafeConstPointer<T>` (raw
pointers) and `UnsafeMemory<T, Use>` (typed memory at a fixed address). A
program declares its own with `unsafe struct`:

```saw
unsafe struct UnsafeMmioReg { addr: Int }     // ok
unsafe struct MmioReg { addr: Int }
// error: an unsafe type must be named `Unsafe*`, but this one is named `MmioReg`
//   hint: rename it to `UnsafeMmioReg`, or drop the `unsafe` keyword if the
//         type is safe to name, hold and pass
```

The `unsafe` keyword confers the semantics; the compiler then enforces the
`Unsafe` name prefix, so the unsafety is legible at every use site without
opening the declaration. The rule runs one way only: a plain
`struct UnsafeDefaults` is an ordinary safe type, because the keyword is the
only thing that marks one.

**Unsafety is not transitive.** A `Vector<T>` holds an `UnsafePointer<T>` field
and is itself a safe type: safe to name, hold, pass and store. Only the
*functions* that reach through to the pointer are unsafe. That is what lets
`Vector.pop` and `Vector.push` differ, and it is the whole point of putting the
marker on functions rather than on the types that contain them.

#### The trigger rule

A function is `unsafe` when its body or signature **names, binds, receives or
returns** a value of an unsafe type — including a reference to one
(`&UnsafePointer<T>` counts). Reading `self.buffer` to test it against `None` is
contact, and the marker is simply true there. The rule is deliberately broader
than "performs a deref": `Vector.iter()` only reads `self.buffer` and hands it to
an iterator struct, and that narrow reading is what hid two use-after-free bugs
under the previous model.

**Binds** covers a binding that is never read: a `match` arm that names an
unsafe payload (`case Filled(t) -> 1`) has the value in scope whether or not it
touches it. A **default parameter value** is part of the signature and counts
the same way, so `func f(a: Int = raw.value())` is contact even though the
parameter's own type is safe.

It fires on one thing that is not a type: **naming an `unsafe static var`**
(design 149). A mutable static's type is usually an ordinary safe one —
`[HandleSlot; 64]` says nothing about who may write it — so there the unsafety
belongs to the declaration rather than to the type, and the same rule carries it
to every function that touches the state.

Failing to declare it is a clean error naming the type and the fix:

```
error: method `Vector.push` is not declared `unsafe`, but its body names a value
       of unsafe type (`UnsafePointer<T>`)
  hint: write `func push(...) unsafe` — the unsafety belongs in the signature
        where every caller can see it

error: function `peek_owner` is not declared `unsafe`, but its body names an
       unsafe static (`TABLE`)
```

**Derivation does not propagate.** A value or reference of a *safe* type produced
inside an unsafe function is safe onward — the `&T` that `with_ref` hands its
closure is an ordinary reference. Performing that derivation soundly is exactly
what the reviewed wrapper exists for.

Declaring `unsafe` where the rule would not require it is allowed. The marker is
a promise about the contract, and a conformer of an `unsafe` trait requirement
must make it — checked since design 188:

```saw
trait Raw { func peek(&self) unsafe -> Int }

extension Plain: Raw {
    func peek(&self) -> Int { self.n }
    // error: method `peek` must declare `unsafe` to conform to trait `Raw`,
    //        whose requirement declares it
}
```

A caller reaching the method through the requirement is promised an unsafe
contract, so the implementation says so too. The other direction stays open: an
`unsafe`-declared implementation of a SAFE requirement is the redundant
declaration above, allowed and meaningful only about the body.

#### Spelling

`unsafe` is an effect, and a declaration spells its effects in the
post-parameter slot beside `sync`, in the canonical order `unsafe sync`:

```saw
public func push(&var self, value: T) unsafe { ... }
func with_var_ref<R>(&var self, i: Int, body: (&var T) sync -> R) unsafe -> R
init(at: Int) unsafe -> UnsafeMmioReg { ... }
```

A function **type** uses the same slot, with `escaping` completing the order
`unsafe sync escaping`:

```saw
func with_raw<R>(&self, body: (UnsafePointer<T>) unsafe sync -> R) unsafe -> R
```

A signature therefore reads identically whether it is declared or written as a
type. Two declarations keep the PREFIX, both because they have no parameter list
to put a slot after: `unsafe struct`, whose enforced `Unsafe*` name carries the
unsafety to every use site, and `unsafe static var` (design 149), which the
trigger rule carries to every function that names it.

Writing `unsafe` in front of a `func` or an `init` names the slot instead:

```
error: `unsafe` goes after the parameter list, not before `func` — write
       `func name(...) unsafe -> T` (the effect slot, before `sync`)
```

Reversing the order (`sync unsafe`) is rejected the same way. `--emit-docs`
renders the slot in the `signature` field and prefixes the `effect` field with
`unsafe`.

#### The effect on a function type

On a function type the effect is a property of the **signature**: it is present
exactly when a parameter or the return names an unsafe type. Both halves are
compile errors.

```saw
func with_raw<R>(&self, body: (UnsafePointer<T>) unsafe sync -> R) unsafe -> R   // ok
func run(body: (UnsafeMmioReg) sync -> Int) unsafe -> Int
// error: the function type `(UnsafeMmioReg) sync -> Int` names an unsafe type
//        (`UnsafeMmioReg`) but its effect slot does not say `unsafe`
func apply(body: (Int) unsafe sync -> Int) -> Int
// error: the function type `(Int) unsafe sync -> Int` declares `unsafe` but its
//        signature names no unsafe type
//   hint: a function taking only safe types must be sound for every input;
//         unsafety enters a signature only through its types
```

The type-position effect has one job: handing an unsafe value into a function
nobody named, which is the `with_raw` shape. Tying it to the signature means one
contract has one spelling, so there is no marked-versus-unmarked pair to define
variance between. The rule is checked on the type **as written**, which is what
keeps generics out of it: `Vector.with_ref`'s `(&T) sync -> R` is judged once
against `T`, not again for an instantiation that substitutes a pointer.

A declaration is judged the other way round, and a redundant `unsafe` on one
stays legal (above): a declaration's marker is a promise about its **body**.
Taking such a function as a value yields the plain type, because the value's
type is read off the signature like any other.

#### Closures

A closure inherits its enclosing function's unsafe domain. There is no
closure-level marker, and a closure's own type says `unsafe` under the same
signature rule as any function type.

```saw
func read_first() unsafe -> Int {
    if let block = GlobalAllocator().alloc(BLOCK_BYTES, BLOCK_ALIGN) {
        block[0] = 7 as Int8
        let read: () -> Int = { block[0] as Int }   // safe signature, unsafe body
        ...
    }
}
```

The closure above captures a raw pointer, so its body is unsafe while its
signature is not — and `read_first`, which declares the effect, is where a
reviewer reads that. A safe-signature closure with an unsafe body can only occur
there: the value it touches either came from a capture (so the enclosing body
bound it, and was already unsafe by the trigger rule) or from a binding written
inside the enclosing body. So the compiler charges that contact to the enclosing
declaration, and the same "not declared `unsafe`" error names it:

```
error: function `read_byte` is not declared `unsafe`, but its body names a value
       of unsafe type (`UnsafePointer<Int8>`)
  hint: write `func read_byte(...) unsafe`
```

The two honest spellings for an unsafe closure in a safe function are declaring
the enclosing function `unsafe`, or hoisting the body into a small named
`unsafe` helper. A closure-scoped unsafe region was considered and rejected:
captures give a closure the whole enclosing frame, so its braces confine the text
without confining what the text can reach. The enforceable boundary is a
signature.

A closure whose signature *does* name an unsafe type is the `with_raw` case
instead. Its contact stays local, because the slot it was passed to already
declares the effect at the call site:

```saw
with_register(16) { r in r.read() }    // `r: UnsafeMmioReg`: the slot said so
```

An unsafe-built, safe-signatured closure that escapes behind a plain function
type is the author's rule-7 responsibility — the ad-hoc analogue of `Vector`
wrapping an `UnsafePointer`.

A closure that never names an unsafe type is safe even when passed into an unsafe
function, which is what keeps the reviewed wrappers usable from safe code:

```saw
func with_ref<R>(&self, i: Int, body: (&T) sync -> R) unsafe -> R
v.with_ref(0) { e in e + 1 }        // the closure sees only `&T`: safe
```

#### Calling an unsafe function

Calling an unsafe function from a safe one needs no ceremony — no marker, no
block, no re-declaration. The unsafe function is the reviewed wrapper and its
callers are safe.

What makes that sound is the **soundness rule**: a function whose parameters are
all safe types must be sound for **every** input. A precondition is expressed by
taking an unsafe-typed parameter, which drags the obligation into the caller
through the trigger rule itself.

- `with_ref(index: Int)` takes only safe types, so it must be sound for every
  index — it bounds-checks and panics on a miss.
- `dealloc(ptr: UnsafePointer<Int8>, size: Int, align: Int)` names an unsafe
  type, so any caller must name one too, and every caller is therefore unsafe.

One marker therefore covers both categories: a function that requires an
unsafe-typed argument, and a safe function that reaches through one internally.
There is no `unsafe(caller)` spelling.

Standing policy for std, and the assumption the model rests on: an `unsafe`
function is short enough to review as a unit.

#### The accessor rule

On a safe type, every indexed accessor is checked. Unchecked access exists only
through `UnsafePointer`. An out-of-range index **panics** for a direct accessor
(`Vector.set`, `Vector.swap`, `Vector.swap_out`, `Vector.with_ref`,
`with_var_ref`, `Data.set`, `String.byte_at`, `String.substring`) or yields
`None`/`Err` for a `get`-shaped one (`Vector.get`, `Data.get`, `Data.slice`). Never a silent
no-op, never a clamp to a plausible-looking result, and never a status flag a
caller can ignore.

**The wording family.** Every bounds panic in the language spells the same
sentence — the compiler's own fixed-array trap and every hand-written accessor
prologue in the standard library alike:

```
<what>: index out of range: <i> (len <n>)
```

so `v[5]` on a three-element vector is
`panic at v.saw:9: Vector.[]: index out of range: 5 (len 3)`, and `a[i]` on a
`[Int; 3]` is `array: index out of range: 5 (len 3)`. A range or slice accessor
spells both bounds: `String.substring: range out of range: 5..2 (len 5)`. The
index is reported at its own signedness, so a negative one reads `-1` rather
than the huge unsigned value the check folds it to.

Both numbers are already in hand where the check fails, and the message is
assembled through the allocation-free format path (the `{}` arguments of
"Format arguments", not interpolation) — so a bounds panic reports itself under
an exhausted allocator, in the freestanding profile, and in a kernel. Write your
own accessor's panic the same way:
`panic("Bag.[]: index out of range: {} (len {})", i, self.len())`.

Arithmetic traps — integer overflow, a shift count out of range, division by
zero — are deliberately *not* in this family: they report a condition rather
than an index into something with a length, and they keep their fixed text.

For scoped, no-copy access to a container element (including a `NoCopy` one)
without minting a raw pointer at all, use `Vector.with_ref`/`with_var_ref`: a
non-escaping `&T`/`&var T` borrow of the element in place, with the whole vector
held borrowed for the body (reallocation- and invalidation-proof). This replaced
the removed `ref_at`.

```saw
// The obligation rides the type; the function that touches it says so.
static UART0: UnsafeMemory<UartRegs, Device> = UnsafeMemory(0x1800_0000)

func poke(addr: Int) unsafe {
    let p = addr as UnsafePointer<Int32>
    p[0] = 42                              // placement-move through a raw pointer
}

// A safe wrapper: safe parameters, so it must be sound for every input.
func poke_register(index: Int) {
    if index < 0 || index >= REGISTER_COUNT {
        panic("poke_register: index out of range")
    }
    poke(UART_BASE + index * 4)            // calling unsafe code needs no ceremony
}
```

There is no line-level `unsafe` expression marker. Design 81 had one, prefixing
any expression where a raw pointer flowed with no `Unsafe*` type spelled at that
site; design 130 removed it along with the "marked domain" rules that decided
where it was required.

### Placement writes (the placement-move primitive)

**Status: implemented (stdlib-internal).** A store through a typed raw pointer —
`ptr[i] = value`, where `ptr: UnsafePointer<T>` — is Saw's **placement-move**
primitive, and it is deliberately *not* the same operation as ordinary
assignment to a live binding. Its exact contract:

- **Bitwise move into the target slot.** The `T` value is moved into the memory
  at `ptr + i` by a raw store. `value` is *consumed* — the same value-transfer
  checkpoint that governs `move`/`.copy()` applies at the store, so the source
  is not usable afterward (a non-`Copy` source must be `move`d in; an
  `Copy` source is retained by the checkpoint as usual).
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

### Pointer-place reads (`move ptr[i]`)

**Status: implemented (design 219).** A read through a typed raw pointer —
`ptr[i]`, where `ptr: UnsafePointer<T>` — is the mirror image of the placement
write above. The load hands the value to the reader and nothing releases the
slot afterward, so the read *transfers* the element rather than duplicating it.
An owning element says so:

```saw
public func pop(&var self) unsafe -> T? {
    if self.length == 0 {
        None
    } else {
        self.length = self.length - 1
        if let buf = self.buffer {
            move buf[self.length]     // the slot is past the new length
        } else {
            None
        }
    }
}
```

- **`move` is required for an `ExplicitCopy` or `NoCopy` element.** An unspelled
  read is refused, and the diagnostic names the spelling:
  ``this read transfers ownership — spell it `move buf[index]` ``. An
  `ExplicitCopy` element has a second answer, `ptr[i].copy()`, which duplicates
  the element and leaves the slot occupied. A trivial or `Copy` element
  reads as a copy with no spelling, exactly as it does elsewhere.
- **The pointer binding is untouched.** `move ptr[i]` retires no binding: the
  pointer is the place's base, not the value transferred, and it stays usable
  on the next line.
- **Author's obligation.** After the move, the slot holds bytes no `deinit` will
  ever run on. Reading the same slot again hands out a second owner of one
  value, which is a double free at the second drop. Keeping track of which slots
  are live is the author's job here, in the same way it is for a placement
  write — the pointer is what put this code in the manual domain, and the
  enclosing `unsafe` declaration is what marks it.
- **Safe places are unaffected.** `move` out of a `Vector` element, a struct
  field or a tuple element stays a compile error (``cannot move out of element
  `[0]` of `v` ``). The language tracks occupancy for those places, so a
  move-out would leave a hole their `deinit` drops a second time.

The move-out family, and what keeps each one's occupancy true:

| Spelling | What refills the place |
|---|---|
| `o.take()` | writes `None` back, so the tag says empty |
| `v.swap_out(i, value)` | the replacement element |
| `move ptr[i]` | the author, inside `unsafe`-declared code |

**Every move out of a place either maintains the place's occupancy or happens
where no occupancy is tracked, and the second kind is spelled `move` inside
`unsafe` code.** The spelling is a declaration of intent rather than a proof of
liveness, which is the same contract depth `unsafe` itself carries. It also
makes `move <pointer place>` the greppable census of a program's manual
transfer points.

### Prefix `*` — the pointer place, spelled

**Status: implemented (design 219).** `*p` names the same place as `p[0]`. It is
parser sugar: the two spellings produce one production, so everything the index
form supports the prefix form supports, and neither the typechecker nor codegen
knows there are two.

```saw
let v = *p                  // value read
*p = fresh                  // store
(*pt).x = 3                 // field projection through the pointee
bump(&var *p)               // the place, by reference
let taken = move *p         // the transfer, on an owning pointee
```

`p[0]` conflates array indexing with single-pointee dereference, and std's
pointer sites are mostly single-object; `*slot` says which is meant. Precedence
and disambiguation follow unary `-`: a `*` in prefix position is a dereference,
one between two operands is multiplication, and `a * *p` is both. **`*` is not a
user-definable prefix operator** — this is one grammar production for the
pointer place, not an operator surface.

Every use sits inside `unsafe`-declared code, since naming an `UnsafePointer`
is what forces that declaration.

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

Fabricating an address is in the same trust bucket as the `UnsafePointer` family:
`UnsafeMemory` is an unsafe type, so every function that reaches through one
declares `unsafe` in its effect slot.

### Allocators (`Allocator` trait, `GlobalAllocator`, public `A` parameter)

**Status: implemented — public type parameter, `GlobalAllocator` default.** Alloc-layer
stdlib types (`Vector`, `Map`, `Data`, `StringBuilder`, `Arc`, ...) obtain memory
through the `Allocator` trait — `alloc(&self, size: Int, align: Int) unsafe ->
UnsafePointer<Int8>?` and `dealloc(&self, ptr, size, align) unsafe` — rather than
calling the `__saw_rt_alloc` / `__saw_rt_dealloc` seams directly. `GlobalAllocator` is a zero-field
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
    func alloc(&self, size: Int, align: Int) unsafe -> UnsafePointer<Int8>? { ... }
    func dealloc(&self, ptr: UnsafePointer<Int8>, size: Int, align: Int) unsafe { ... }
}

var v = Vector<Int, MySlab>()   // grow/deinit route through MySlab; A().alloc is
                                // a direct, statically-dispatched call — no stored
                                // allocator, no vtable
```

`Vector<Int, MySlab>` is a **distinct type** from `Vector<Int>`; a value of one
cannot be passed where the other is expected. Deinit frees through the vector's
own `A`, so allocations never cross heaps. `Vector(capacity:)` and every other
allocating operation surface a refusal to the caller as
`Err(AllocError)` with `size`/`align` context — see
[Allocation failure](#allocation-failure).

Paper 19 §4's allocator model is now landed end to end: module-level `static`
declarations (design 41) and **per-type slab allocators** (design 42) both ship.
The only piece still deferred is the optional `AllocatedBy<Slab>` sugar (per-type
default allocator), which paper 19 keeps for when kernel code justifies it.

### Allocation failure

**Status: implemented (design 234, superseding design 123's two-tier policy).**
Every allocating operation in the standard library returns
`Result<_, AllocError>`. There is one spelling per operation, and the signature
says whether it can fail.

```saw
var frames = Vector<Frame, FrameSlab>()
match frames.push(Frame(id: 1)) {
    case Ok(_) -> print("queued"),
    case Err(e) -> print("out of frame memory: {e}")
}
// prints e.g. out of frame memory: allocation of 64 bytes (align 8) failed
```

The operations are `Vector.push`/`reserve`/`map`, `Map.insert`/`keys`/`values`,
`Set.insert` and its algebra, `Data.push`/`set`/`append`/`append_bytes`/
`reserve`/`detached`, `StringBuilder.append`/`append_char`/`append_scalar`,
`Box.make`, `String.split`/`to_data`, `Env.args`, `Command.arg`/`env`/`output`,
and the constructors `Vector(capacity:)`, `Data(capacity:)`,
`StringBuilder(capacity:)`, `Arc(value:)`, `Channel()` and
`TaskGroup(threads:)`. A constructor reports through the `Result<Self, E>` init
form, so the call keeps its spelling and the caller gains one word.
`Mutex(value:)` is not in the list: it allocates nothing.

Each is **all-or-nothing**: on `Err` the container is exactly as it was, with
every element still in it. The `AllocError` carries the byte `size` and `align`
of the request that was refused and conforms to `Error` and `Printable`, so it
interpolates into a log line and boxes at a `Result<T, Box<any Error>>` boundary
like any other error.

`try!` is the spelling for code that would rather die than handle the refusal.
It panics naming the error, which is more than the tier it replaced could say:

```saw
var v = Vector<Int>()
try! v.push(1)   // on refusal: try! failed: allocation of 32 bytes (align 8) failed
```

Panic messages are assembled in stack scratch (see [Panic messages allocate
nothing](#panic-messages-allocate-nothing)), so an allocator that has refused
everything still reports what it refused. The panic routes through the
`__saw_rt_panic` seam, so a kernel picks the policy: oops, kill the task,
reboot.

The `try_` prefix now means one thing, **non-blocking**: `Channel.try_receive`,
`SpinLock.try_lock`, `Once.try_get`. The allocation twins it also used to mean
(`try_push`, `try_insert`, `try_append`, `try_make`, `try_with_capacity` and the
rest) are gone; the operation each one doubled reports.

**`Channel.send` shows the compound shape.** It reports BOTH of its
failures as values in one error type — `Err(Closed)` for a closed channel and
`Err(Alloc(e))` for a refused queue node, the second carrying the `AllocError`
itself. `try_send` retired with the split: it existed because `send` had one
error slot already spent on `Closed`, so the allocator's refusal had nowhere to
go but a panic, and `try_send` was the mirror image (allocator as a value, a
closed channel as a panic). Neither could carry the other's failure, which is
what DQ-230b asked about. One send, one error type, both sources in it. That is
the general rule for a domain error: the compound carries the leaf rather than
re-enumerating its vocabulary.

#### Where a refusal still panics

Five places, each because the report has nowhere to go.

**The allocations the compiler inserts that no source construct names** — string
interpolation, an escaping closure's captured environment, a coroutine frame, a
spawned task's control block. There is no expression to hang a `try` on.
`--no-hidden-alloc` rejects them at compile time for code that cannot accept a
panic there.

**A collection literal.** `[a, b, c]` lowers to a container plus one synthesized
`push` per element, and a synthesized call is the same case one level down. The
literal forces the `Result` and panics naming the error:
`collection literal: allocation of 64 bytes (align 8) failed`.

**`copy()`.** Its signature belongs to `ExplicitCopy` and the compiler emits
calls to it, so it cannot return a `Result`. `Vector.copy()` panics naming the
method; `Vector.try_copy()` is the reporting spelling for a duplicate, and the
one place the retired prefix survives.

**`Data`'s subscript.** Writing through `d[i]` on shared storage separates the
bytes first, and that allocation shares a body with the bounds check. Splitting
one of the two failures out as a value would make `d[i]` mean two different
things by which failure it met. `detached()` attempts the same allocation where
a refusal has somewhere to go, so it is the preflight.

**`String`.** Every producer returns a plain `String`, so there is nowhere to
put a failure: `to_uppercase`, `to_lowercase`, `replace`, `trim`, `substring`,
`Vector<String>.join`, `StringBuilder.build`, `Path.join` and `String.fromBytes`
all panic through the one allocator behind them. `Printable.format` is on the
same footing — its signature is the trait's, and the path it serves (panic and
assert assembly, `print("{}", x)`) is the one that has to work with the
allocator refusing everything, which is why it writes into fixed storage where
an overrun truncates and no `AllocError` exists at all.

A type parameterized by its allocator (`Vector<T, A>`, `Box<T, A>`,
`Map<K, V, A>`, `Set<T, A>`) is the freestanding toolkit. Types with no
allocator parameter — `String`, `StringBuilder`, `Data`, `Arc`, `Mutex`,
`Channel` — allocate through `GlobalAllocator`.

What none of these do is degrade. There is no truncated `Vector`, no
`Ok("")` from a validating constructor, no un-joined path returned from `join`,
no message dropped by `send`, and no object that constructs "successfully" and
then does nothing — `Arc`, `Mutex` and `Channel` used to have exactly that inert
state, and it no longer exists.

### No hidden allocations (`--no-hidden-alloc`)

**Status: implemented (design 135).** `Vector.push` allocates, and it says so:
a method with a contract, an allocator in the type. The guarantee is about the
other case — the compiler allocating on its own authority, where nothing in the
source says a heap block is involved. `sawc --no-hidden-alloc` rejects every
such site at compile time.

"Named" means named by the **expression** or by a **type the author wrote**.
The classification below covers every allocation `sawc` emits.

| Site | What triggers it | Named | Under the flag |
|---|---|---|---|
| Escaping closure environment | a closure that outlives its frame and captures something | no | rejected |
| String interpolation buffer | `"...{x}..."`, anywhere, including a `panic`/`assert` message | no | rejected |
| `to_string()` for an interpolated `Printable` piece | `"{point}"` | no | rejected, as part of the interpolation |
| `to_string()` for one-argument `print` of a `Printable` | `print(point)` | no | rejected |
| Task control block and coroutine frame | `spawn`, `TaskGroup.spawn` | yes: the call starts a task | allowed |
| A spawned closure's environment | `Thread.spawn { ... }` | yes: part of starting the task | allowed |
| Erased-error box | returning a concrete error from `-> Result<T, Box<any Error>>`, and each `try` that propagates one | yes: the `Box` is in the written signature | allowed |
| Existential box | `Box<any Shape>.make(v)` | yes | allowed |
| Collection literal | `[a, b]`, `{k: v}`, `{a, b}` | yes: the literal names the collection | allowed |
| `TaskGroup(threads: N)` control block | the call | yes | allowed |
| Implicit `copy()` at a transfer | passing a `Copy` value | yes: the type declares that policy (a refcount bump for `String`, `Arc`, a closure environment) | allowed |
| `x.to_string()` | the call | yes: it returns a `String` | allowed |
| `&concrete` to `&any Trait` | passing to an existential reference | — | never allocates: a static vtable is attached |
| Optional and `Result` auto-wrap | `return 42` from a `Result`-returning function | — | never allocates: an inline tagged value |
| Place windows | `v[i]`, a `borrows` accessor's lend | — | never allocates |
| Loop desugaring | `for i in 0..n`, `v.iter()` | — | never allocates |
| String literals, statics, `#file`/`#line` | — | — | never allocates: immortal blocks with refcount `-1` |
| Format arguments | `print("{}", x)`, `panic`, `assert` | — | never allocates |
| Runtime-check panic messages | a bounds, overflow, shift or divide trap | — | never allocates: interned constants |
| A builtin's `format(into:)` | `self.n.format(into: &var b)` | — | never allocates |

The three rejected sites each name the spelling that works:

```saw
let label = "count: {n}"
// error: string interpolation allocates a String — `--no-hidden-alloc`
//        forbids allocations the source does not name
//   hint: pass the values as format arguments instead — `print("x = {}", x)`,
//         `panic("out of {}", what)` — or assemble the text in a
//         fixed-capacity `StringBuilder`; a message with nothing interpolated
//         into it is an interned literal and costs nothing
```

Interpolation is rejected **everywhere**, with no exception for `panic` and
`assert` message arguments. The moment a panic matters most is when the
allocator has nothing left to give, so a message routed through the allocator is
a message that does not arrive. `panic("out of {}: wanted {}", "frames", 64)`
says the same thing out of stack scratch. Runtime-check panics were never
affected: they lower to interned constants.

An escaping closure is one bound to a `let`/`var`, returned, or stored in a
field; its captures move to a refcounted heap block. A closure passed straight
to the call that runs it keeps its environment on the stack and stays legal, and
so does an escaping closure with nothing captured — that one is a bare code
pointer.

`print(point)` has no rendering to reach for except the `to_string()` the
compiler synthesizes at the call site. `print("{}", point)` streams the same
bytes through the value's own `format` into stack scratch; see [Format arguments
and the allocation-free path](#format-arguments-and-the-allocation-free-path).
Inside a generic, `print(v)` on a `T: Printable` is judged at the template,
where `T` could be anything, so it is rejected there too. The
format-argument spelling covers every instantiation, which is why the check does
not wait for one.

**The erased-error box is the one allocation on an error path, and its own
failure is a documented boundary: it panics.** Returning a concrete error from a
`-> Result<T, Box<any Error>>` function boxes it, and if the allocator refuses
that box there is nowhere to put the news — reporting an allocation failure
would take an allocation, which is the failure being reported. So the erasure
panics rather than inventing a second, un-erasable error channel. This is the
same rule the hidden-allocation sites above follow, arrived at from the other
direction: those cannot report because no expression can carry the report, and
this one cannot report because the report is what ran out. A program that must
not meet it does not erase — it names its error type, which is the tier the
standard library stays on ([Error-type doctrine](#error-type-doctrine)).

The flag is **orthogonal to `--freestanding`**. A kernel with a slab allocator
may want allocator-backed `String`s, so the freestanding profile does not imply
the flag. The two combine, and pairing them is the recommendation; the SOS
kernel builds under both.

The flag judges the program's own source. The standard library is written on the
allocation-free path already — no interpolation appears anywhere in it — and the
coroutine transform's output is compiler-authored, so a spawned frame's box is
counted once at the `spawn` that asked for it rather than again at every
rewritten hop.

### `Box<T, A>` — a single owned heap allocation

**Status: implemented (design 42).** `Box<T, A: Allocator = GlobalAllocator>` owns one
`T` allocated through allocator `A`. Hosted code writes `Box<T>` (the default
fills `A = GlobalAllocator`); a kernel writes `Box<Job, JobSlab>` to place the value in a
per-type slab (the design-19 §4 "kernel idiom"). `Box` is **NoCopy** — it is
`move`d, never silently duplicated — and its single heap `T` is released exactly
once on deinit.

The constructor is a **static factory method**, because the allocator type
argument is named at the call site (`Box<Job, JobSlab>.make(...)`):

```saw
match Box<Int>.make(42) {
    case Ok(b)  -> print(b.value())
    case Err(e) -> print(e.size)   // AllocError with size/align context
}
```

On the failure path the value is cleanly `deinit`'d at scope exit (never
leaked): `make` places it with the placement-move primitive
(`ptr[0] = move value`) only once the allocation succeeded, so a refusal leaves
it unmoved. Payload access:

- `value()` returns a copy of the payload (bounded `T: ExplicitCopy`).
- **Method forwarding** (like `Arc`): a `&self` method on the payload
  struct is callable through the Box — `b.peek()` forwards to the payload's
  `peek`. A `&var self` payload method is rejected (aliased mutation of
  owned-through-a-handle state is what a `Mutex` payload exists to make safe).

### Slab allocators (the kernel idiom)

**Status: implemented (design 42).** A slab is a per-type fixed-chunk allocator
over a caller-owned `static` region — freestanding-compatible (no libc, just
`Atomic<Int>` CAS). `std/slab.saw` provides `SlabHead` (a slab's mutable
bookkeeping: a bump counter + a LIFO free-list head, both `Atomic<Int>`, so the
head is `NoCopy` — a copy would be a second set of bookkeeping over the same
region) and the `slab_alloc` / `slab_dealloc` free functions. A user allocator
is a zero-field unit struct wiring its own statics in ~10 lines:

```saw
static JOB_REGION: [Int8; 64]                                  // 4 chunks × 16B, .bss
static JOB_HEAD: SlabHead = SlabHead(bump: Atomic(0), free: Atomic(0))

struct JobSlab {}
extension JobSlab: Allocator {
    func alloc(&self, size: Int, align: Int) unsafe -> UnsafePointer<Int8>? {
        slab_alloc((&JOB_REGION) as UnsafePointer<Int8>, 4, 16, &JOB_HEAD)
    }
    func dealloc(&self, ptr: UnsafePointer<Int8>, size: Int, align: Int) unsafe {
        slab_dealloc(ptr, &JOB_HEAD)
    }
}
type JobBox = Box<Job, JobSlab>          // the kernel idiom
```

The region reaches the slab as `(&STATIC) as UnsafePointer<Int8>` — a reference,
cast to a raw pointer, over a bare-declared (writable `.bss`) static. `alloc`
returns `None` on exhaustion, which is what `Box.make` turns into
`Err(AllocError)`; `dealloc` pushes the chunk back onto the free-list.
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

  -o <file>    Output executable name (default: .build/<source>)
  -c           Compile to an object file (.o) only — no linking, no main() required
  -v           Verbose output (pipeline stages)
  --emit-ir    Emit LLVM IR only, don't compile
  --emit-ast   Dump the typed AST (debugging)
  --emit-docs  Type-check and emit documentation JSON instead of code, for the
               entry module and every module it imports (see Doc comments).
               Writes to -o, else stdout.
  --emit-docs-all
               Same, keeping private fields, methods and inits.
  -O0          Disable optimization passes (raw codegen; default is an O1-style
               pipeline: entry-block allocas + mem2reg and friends)
  --target TRIPLE
               Cross-compile for a target triple (default: the host)
  --target-features FEATURES
               LLVM subtarget features for --target, comma separated (e.g.
               `+m,+a,+c` for rv32imac). A triple names an architecture but not
               its optional extensions; base rv32i has no divide instruction,
               so an integer `/` becomes a libcall freestanding cannot link.
               Overrides the freestanding profile's own default (below).
  --freestanding
               Freestanding profile: runtime seams as declarations only, no
               hosted std modules, no Float printing, unlinked object output.
               On aarch64 it also implies `--target-features -neon,-fp-armv8`
               (below).
  --no-hidden-alloc
               Reject allocations the compiler inserts that no source construct
               names: string interpolation, an escaping closure's captured
               environment, and `print` of a user Printable. Allocations the
               source names are unaffected. Orthogonal to --freestanding; see
               No hidden allocations.
  --runtime-build
               Compile a Saw runtime that `@export`s the frozen `__saw_rt_*`
               ABI. Sync-only, unlinked object output; builds `sawc/rt/`.
  --runtime-provider
               This package IS a runtime (design 149; blade passes it for
               `[package] runtime = true`). Permits `@export`ing the frozen
               seams, checks each against sawc/rt/ABI.md, and links no runtime
               of ours beside it. Unlike --runtime-build this is an ordinary
               package build: std is available and the output links.
  --module-path NAME=DIR
               Map package NAME to source directory DIR (`import NAME` ->
               DIR/lib.saw, `import NAME.sub` -> DIR/sub.saw). Repeatable;
               this is how the package manager wires dependencies.
  -W NAME      Enable a warning category (repeatable; `-W all` for every one).
               Warnings are off by default and never affect the exit status.
               See Compiler warnings.
  --ids        With --emit-ast, include each node's stable node_id. Off by
               default: ids are stable within a run but carry no
               cross-implementation meaning, so the canonical dump omits them.
  --emit-frame-layout
               Emit the coroutine frame layout report as JSON instead of code:
               per monomorphized frame, its size, alignment, and every field's
               offset. Writes to -o, else stdout. Analysis only.
  --emit-bt-table
               Emit the logical task-backtrace table as JSON instead of code:
               per monomorphized frame, the name/file it prints and the source
               line or embedded child for each resume state. Writes to -o,
               else stdout. Analysis only; the table itself is always linked.
```

Optimization: by default `sawc` runs an O1-style pass pipeline (allocas hoisted
to the entry block, mem2reg, etc.); `-O0` turns it off for debugging raw output.

## Appendix A: Keywords

Reserved words. Some name planned features (marked); logical negation is the
word `not` (there is no `and`/`or` — use `&&`/`||`), and the empty optional is
`None`. `case` introduces enum variants and match arms.

The `dyn` reservation is RETIRED — type-erased dynamic dispatch is spelled
`any Trait` (a contextual keyword in type position, so `any` is still a valid
identifier). The opaque/static-dispatch counterpart, when it lands, will use the
provisional keyword `generic`.

**Reserved means lexed as a keyword.** The first list below is exactly the
lexer's keyword table (`sawc/lexer.py`); those words cannot be used as
identifiers anywhere. Everything in the second list is recognized by the parser
or the typechecker in one specific position and is an ordinary identifier
everywhere else, so `let module = 3` and a method named `parent` both compile.
The module-system words are deliberately in that second group — reserving them
would collide with user code for no gain.

The `loop` and `ref` reservations are RETIRED (design 55): `loop` was redundant
with `while { }` (the infinite-loop idiom), and `ref` never had a design — a
future by-reference match binding would reuse the `&` sigil vocabulary — so both
are freed as ordinary identifiers. `do` and `defer` were never lexer
keywords to begin with; they stay PLANNED reservations (cheap insurance for
plausible futures) — not yet enforced, so `let do = 5` compiles today, but
earmarked so a future design does not have to fight existing code for the
name.

```
Reserved (lexer keywords — never usable as identifiers):
as       borrows  break    case     catch    continue else     enum
extension         extern   false    for      func     guard    if
in       init     lend     let      match    move     None     not
public   return   self     static   struct   trait    true     try
unsafe   var      while

Contextual (parser- or typechecker-recognized in one position; still valid
identifiers):
any      const    deinit   escaping export   import   module   package
parent   Self     sync     type

Planned / reserved:
and  defer  do  generic  macro  none  or  some  where
```

`const` joined the contextual list with const generics (design 148). It is
recognized only in a generic parameter position, so `let const = 3` still
compiles.

`type` joined it too. It declares an alias only where one can begin — the
word followed by a NAME, at module level or as a trait/extension member —
and is an ordinary identifier everywhere else, so `clock_get(type: .Monotonic)`,
`struct Event { type: Int }`, `e.type` and `let type = 7` all compile. A type
alias inside a function body is still refused, by a message naming the three
places an alias is allowed.

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
  Attribute:      @                  (`@export`, `@section("...")`,
                                      `@synthesize`; declaration position only)

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

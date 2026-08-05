# Saw language design review — a claims audit against README.md

**Date:** 2026-08-04 · **Tree:** `main` @ `f764b75` · **Reviewer:** independent
language-design review (no access to `designs/`, deliberately blind to the
project's own rationale).

**Method.** Every substantive claim in `README.md` was extracted, cross-read
against `LANGUAGE_SPEC.md` for the promised semantics, and then tested
empirically with probe programs under `.build/scratch/lrev_*.saw`, compiled and
run with `./.venv/bin/python sawc/sawc.py <file> -o .build/scratch/<out>`.
Error-case claims were tested by writing the program the claim says must be
rejected and checking both *that* it is rejected and *how well*. `examples/`
(846 files) was used as the corpus of what the language looks like in practice.
The full test suite was not run; all evidence below is from individual probes.

**Headline.** The safety core is real and survived adversarial probing — this is
not a language that merely *says* it is safe. The gaps are almost all on the
**resource-lifetime** and **surface-syntax** axes, not the memory-safety axis,
plus four README sentences that overclaim relative to what the compiler does.

---

## 1. Verdict summary

| # | Claim (README) | Verdict |
|---|---|---|
| 1 | No null pointers | HOLDS |
| 2 | Memory safety checked at transfer (move checking) | HOLDS |
| 3 | Law of Exclusivity: many readers XOR one writer, fully static, no lifetimes | HOLDS |
| 4 | References cannot escape | HOLDS |
| 5 | Unsafety is carried in the type; no `unsafe` blocks | HOLDS |
| 6 | Deterministic LIFO destruction of scope locals | HOLDS |
| 7 | `Deinit` composes through aggregates | HOLDS-WITH-CAVEATS |
| 8 | "values are destroyed … as they go out of scope" — for **task frames** | **DOES-NOT-HOLD** |
| 9 | Zero-cost abstractions: generics/traits → specialized machine code | HOLDS |
| 10 | `any Trait` dynamic dispatch is opt-in and explicitly owned | HOLDS |
| 11 | "No hidden allocations" | **DOES-NOT-HOLD** |
| 12 | "The only implicit copies are cheap ones" | HOLDS |
| 13 | Colorless concurrency: no `async`/`await`, any call may suspend | HOLDS |
| 14 | `sync` is a compiler-checked negative effect | HOLDS |
| 15 | Suspending calls embed anywhere or error cleanly — never silently block | HOLDS |
| 16 | Blocking FFI runs on a separate thread and parks the task | HOLDS |
| 17 | `TaskGroup` owns its children and joins them at scope exit | HOLDS |
| 18 | Cancellation is explicit and cooperative | HOLDS |
| 19 | `TaskGroup(threads: N)` with `Send` checked at every spawn | HOLDS |
| 20 | "an operation-count budget stops a spinning task from starving the others" | **DOES-NOT-HOLD** |
| 21 | References stay valid across suspension points | HOLDS |
| 22 | `std.net`: owning, `Result`-honest, EOF distinct from error | HOLDS-WITH-CAVEATS |
| 23 | Swift-style syntax | HOLDS-WITH-CAVEATS |
| 24 | Immutable by default | HOLDS |
| 25 | Optionals: `if let`/`guard let`/`??`/full optional chaining + chained assignment | HOLDS |
| 26 | `Result` + auto-wrap + `try`/`try?`/`try!`/`catch` | HOLDS |
| 27 | Pattern matching over ADTs | HOLDS |
| 28 | Traits with default bodies | HOLDS |
| 29 | Overloading by **exact** argument types; no implicit conversions | HOLDS |
| 30 | Generic inference incl. across overload sets; ties error and list candidates | HOLDS |
| 31 | Shadowing must be earned | HOLDS |
| 32 | `Printable` + interpolation + `to_string()` default | HOLDS |
| 33 | Errors as values: `Result<T, Box<any Error>>` erasure + downcast | HOLDS |
| 34 | The Copy trait family | HOLDS |
| 35 | Collection literals (`[]` / `{k:v}` / `{a,b}`) | HOLDS |
| 36 | Type extensions, including on primitives | HOLDS |
| 37 | Module system + member visibility + prelude discipline | HOLDS |
| 38 | `#file` / `#line` / `#function` definition-site literals | HOLDS |
| 39 | "Panics and asserts already include a `panic at FILE:LINE:` prefix" | **DOES-NOT-HOLD** |
| 40 | Whole-referent replacement `x = v` through `&var` | HOLDS |
| 41 | Freestanding / bare metal | HOLDS-WITH-CAVEATS |
| 42 | `static_assert` compile-time layout checks | HOLDS |
| 43 | `@export` C-ABI symbols | HOLDS |
| 44 | `UnsafeMemory<T, Use>` MMIO | HOLDS |
| 45 | Pluggable allocators as default type parameters | HOLDS |
| 46 | "Nothing in std silently swallows an error" | HOLDS (spot-checked) |

**Counts:** 38 HOLDS · 4 HOLDS-WITH-CAVEATS · 4 DOES-NOT-HOLD.

---

## 2. Claim-by-claim evidence

### 2.1 The safety core (claims 1–6) — HOLDS, and it is the best part of the language

Every adversarial probe I could construct was caught, with diagnostics that are
better than Rust's on the same shapes.

**Use-after-move (claim 2).**

```saw
var v: Vector<Int> = [1, 2, 3]
var w = move v
print(v.len())
```
```
error: use of moved variable `v`
 5 |     print(v.len())
   |           ^
   hint: value was moved at line 4 and can no longer be used
```

**Iterator invalidation via the element-borrow API (claim 3).** `Vector` sells
`with_var_ref` as "invalidation-proof". I attacked it directly:

```saw
var v: Vector<Int> = [1, 2, 3]
let r = v.with_var_ref(0, { [&var v] &var e in
    v.push(99)     // would realloc the buffer under the live `e` borrow
    e = 7
    0
})
```
```
error: exclusive access violation: `v` is passed as `&var` while also being accessed in the same call
```

Then via the **parent path**, to see whether the disjointness check is really
path-based rather than name-based:

```saw
var h = Holder(v: [1, 2, 3])
let r = h.v.with_var_ref(0, { [&var h] &var e in
    h.v.push(9)
    e
})
```
```
error: exclusive access violation: `h.v` is passed as `&var` while also being accessed in the same call
```

Same for mutating a `Map` from inside its own `each` visitor. This is the
classic C++/Go/Java footgun, statically eliminated with no lifetime syntax.

**Shared-ownership aliasing (claim 3).** `Arc<T>` is `ImplicitCopy`, so two
handles alias one payload. The compiler blocks the obvious escalation:

```saw
let a = Arc<Counter>(value: Counter(n: 0))
let b = a
a.bump()             // `func bump(&var self)`
```
```
error: cannot call `&var self` method `bump` through `Arc` — aliased mutation of a shared value is not allowed
   hint: wrap the payload in a `Mutex` and mutate it inside `lock`
```

That, plus the "no `static mut`, ever" rule in the spec, means *all shared
mutable state is mediated* is a real theorem here, not an aspiration. It is the
single strongest design decision in the language.

**Traps, not UB (claim 1).** Out-of-range index returns `Optional`; force-unwrap
of `None` and integer overflow both abort:

```
1 / 2 / 3 / -1 / -1        (v.get(i) ?? -1 for i in 0..5)
panic: force unwrap of None at line 10       (exit 134)
panic: integer overflow                      (exit 134)
```

**Unsafety is type-carried (claim 5).**

```saw
let p = (&b) as UnsafePointer<Int>
print(p[0])
```
```
error: dereferencing a raw pointer requires the `unsafe` marker
   hint: prefix the expression with `unsafe` … the raw pointer flows with no `UnsafePointer` type
         visible at this site; or put an `Unsafe*` type in this function's signature to enter
         the marked domain
```

This is a genuinely novel and, I think, *better* factoring than Rust's `unsafe`
blocks: the obligation attaches to the type-invisibility of the pointer, not to
a lexical region, so it cannot be silenced by wrapping a larger area.

**LIFO destruction (claim 6).** Verified for locals, nested calls, and early
return. The one caveat is claim 7, below.

**Only defect found in this block:** the "references cannot escape" rule is
enforced, but the diagnostic is a red herring. `func leak(x: &Int) -> &Int { x }`
gives

```
error: function `leak` should return `&Int` but returns `Int`
```

which reads as a type mismatch, not as "reference return types do not exist".

### 2.2 Claim 7 — `Deinit` through aggregates: HOLDS-WITH-CAVEATS

Drop glue does not compose automatically. A struct holding a `Deinit` field must
declare its own conformance:

```saw
struct R { id: Int }
extension R: Deinit { func deinit(&var self) { print(self.id) } }
struct Pair { a: R, b: R }
```
```
error: struct `Pair` contains Deinit field `a` of type `R` but does not implement Deinit
   hint: add `extension Pair: Deinit { func deinit(var self) { ... } }`
```

And the far more common shape — a struct with a `Vector` field — needs **two**
hand-written conformances:

```saw
struct Holder { v: Vector<Int> }
```
```
error: struct `Holder` contains ExplicitCopy field `v` of type `Vector<Int>` but does not implement ExplicitCopy
error: struct `Holder` contains Deinit field `v` of type `Vector<Int>` but does not implement Deinit
```

Forcing the author to *notice* is defensible design. Forcing them to *write*
`extension Holder: Deinit { func deinit(&var self) { } }` and a field-by-field
`copy` is not — the compiler already knows the structural answer, and an
`extension T: Deinit {}` synthesis (the way `Equatable` already works) would
give the same "you must opt in" signal with none of the boilerplate. This is the
single biggest ergonomic tax in the language: it hits every struct that owns a
collection, i.e. most structs.

Two diagnostic bugs ride along: both hints suggest `func deinit(var self)` and
`func copy(self)`, receiver spellings that appear nowhere in `LANGUAGE_SPEC.md`
(the spec is uniformly `&var self` / `&self`). `var self` *does* compile and
behaves identically to `&var self`, which means the language accepts an
undocumented duplicate receiver spelling — and the compiler's own hints teach it.

### 2.3 Claim 8 — task-frame destruction: DOES-NOT-HOLD

> "values are destroyed in a defined order (last in, first out) as they go out of
> scope"

For stack locals this holds. For **spawned task frames it does not**: a task's
owned values are not released when the task completes, only when the whole
`TaskGroup` is torn down.

```saw
struct R { id: Int }
extension R: Deinit { func deinit(&var self) { print(self.id) } }
func worker(r: R) -> Int { yield_now(); 7 }

func main() {
    var group = TaskGroup()
    let h = group.spawn(worker(R(id: 42)))
    print(h.join())          // task has completed
    print(100)               // marker
}
```
```
7
100
42        <- R's deinit runs only at group teardown
```

Worse, the group never reaps: five tasks spawned and joined one at a time all
hold their resources until the end.

```saw
var i = 1
while i <= 5 {
    let h = group.spawn(worker(R(id: i)))
    let _ = h.join()
    i = i + 1
}
print(999)
```
```
999
5
4
3
2
1
```

**Consequence.** The README's flagship concurrency example is an endless
`accept`-loop server that spawns a handler per connection into one long-lived
group. On this implementation that group accumulates every completed handler's
frame — including its `TcpStream`, i.e. its **file descriptor** — for the life of
the server. It is an unbounded fd and memory leak in exactly the program the
language is advertised with, and it is invisible in the tests because every test
group is short-lived.

### 2.4 Claim 22 — `std.net` EOF: HOLDS-WITH-CAVEATS

EOF-as-empty-`Ok` is genuinely distinct from `Err`, and works when the writer is
dropped by an ordinary function return:

```saw
func send_and_close(w: TcpStream) { try! w.write("hello") }   // fd closed on return
func receiver(stream: TcpStream) -> Int {
    print((try! stream.read()).len())   // 5
    print((try! stream.read()).len())   // 0 = EOF
    0
}
```
```
5
0
0
```

But the natural spelling — the writer is a **sibling task** — deadlocks, because
of claim 8:

```saw
let hs = group.spawn(sender(move a))     // sender writes "hello", returns
let hr = group.spawn(receiver(move b))   // reads 5, then reads again for EOF
print(hs.join())                          // prints 5 — sender COMPLETED
print(hr.join())                          // hangs forever
```
```
5
5
<hangs; killed after 25s>
```

The sender finished; its `TcpStream` is still open inside the retained frame; the
receiver parks forever waiting for an EOF that cannot arrive until the group is
destroyed, which cannot happen until the receiver finishes. A three-way lifetime
deadlock, silent, with no diagnostic. Fixing claim 8 fixes this.

### 2.5 Claim 20 — starvation budget: DOES-NOT-HOLD

> "an operation-count budget stops a spinning task from starving the others"

The budget only applies to tasks that make suspending I/O ops that complete
without parking. A task that spins on pure computation starves its siblings
completely:

```saw
func spinner() -> Int {
    print("spin start")
    var i = 0
    var acc = 0
    while i < 40000000 { acc = acc &+ i; i = i + 1 }
    print("spin end")
    acc
}
func chatty() -> Int { print("sibling ran"); 1 }
// main spawns spinner then chatty into one TaskGroup
```
```
spin start
spin end
sibling ran
```

Nothing in the implementation is wrong here — this is the honest, documented
limit of a cooperative scheduler. The README sentence is what is wrong: "a
spinning task" reads naturally as "a task that spins", which is precisely the
case the budget does *not* cover. One clause ("a task that keeps completing
ready I/O without ever parking") makes it true.

### 2.6 Claim 11 — "No hidden allocations": DOES-NOT-HOLD

Three constructs that read as plain value bindings allocate on the heap.
`--emit-ir` on this program:

```saw
func adder(n: Int) -> (Int) -> Int { { x: Int in x + n } }
func main() {
    let f = adder(3)
    print(f(4))
    let n = 42
    let s = "n = {n}"
    print(s)
}
```

`main`'s IR:

```llvm
%env_raw.i = tail call ptr @__saw_rt_alloc(i64 16, i64 16)     ; closure env
...
%.12 = call i32 (ptr, i64, ptr, ...) @snprintf(ptr ... %fmt_buf, i64 64, ptr @.str.49, i64 42)
%piece_len = call i64 @strlen(...)
%block.i = call ptr @__saw_rt_alloc(i64 %total.i, i64 16)       ; interpolated String
```

So: (a) creating an escaping closure heap-allocates a refcounted environment;
(b) string interpolation heap-allocates *and* routes an `Int` through libc
`snprintf` + `strlen`; (c) `Result<T, Box<any Error>>` boxes at the return
boundary (the README does acknowledge this one). The README already has the
right framing elsewhere — "Kernel code sticks to concrete error types to avoid
the hidden allocation" — it just needs the bullet to say "allocation is always
visible in the type" rather than "no hidden allocations".

The `snprintf` dependency is separately notable for the bare-metal story:
interpolating an integer pulls libc into a program that otherwise would not need
it.

### 2.7 Claim 39 — panic locations: DOES-NOT-HOLD

> "Panics and asserts already include a `panic at FILE:LINE:` prefix."

There are three different panic formats in the compiler
(`grep` over `sawc/codegen/`):

| Source | Observed message |
|---|---|
| `assert` / `panic()` | `panic at lrev_panic_prefix.saw:4: assertion failed: sanity check failed` |
| force-unwrap / `try!` | `panic: force unwrap of None at line 10` — line, **no file** |
| overflow / bounds / div-by-zero / shift | `panic: integer overflow` — **no location at all** |

The claim is true for the third of panics a programmer writes by hand and false
for the two-thirds the *language* raises. For a systems language whose entire
safety story is "we trap instead of corrupting memory", a bounds-check abort that
cannot tell you which line trapped is the weakest link in the story. Everything
needed (`#file`/`#line` machinery, the `panic at FILE:LINE:` formatter) already
exists.

### 2.8 Claim 9 — zero-cost abstractions: HOLDS, convincingly

```saw
trait Shape { func area(&self) -> Int
              func describe(&self) -> Int { self.area() + 1 } }
func total<S: Shape>(a: &S, b: &S) -> Int { a.area() + b.describe() }
func dyn_total(a: &any Shape, b: &any Shape) -> Int { a.area() + b.describe() }
func id<T>(x: T) -> T { x }
```

IR symbols: `total$1$Sq`, `id$1$Int`, `id$1$String` — real monomorphization, one
symbol per instantiation, no witness tables. `main` constant-folded the entire
generic + trait-default call graph down to three literal `__saw_rt_write` calls.
`dyn_total` takes `{ ptr, ptr }` (data + vtable) and does exactly two indirect
calls — the dynamic cost is present only where `any` was written. This is the
Rust/C++ cost model, delivered.

### 2.9 Claims 13–19, 21, 40 — concurrency: HOLDS

- README's `TaskGroup` snippet compiles and prints `25` verbatim.
- `sync` violation, with a *transitive* explanation and the exact suspension site:
  `cannot suspend in 'sync func' declaration: 'sync func must_not' calls
  'may_suspend' → yield_now ('may_suspend' suspends at line 6)`.
- `Deinit` bodies are `sync`-checked too, with a dedicated message.
- MT `Send`: `cannot spawn 'consume' into a multi-threaded TaskGroup(threads: ...):
  parameter 'v' of type 'Vector<Int, GlobalAllocator>' is not Send … Share
  thread-safe state via Arc (and Mutex for mutation) or a Channel`. Best error
  message in the compiler.
- Blocking FFI offload works, including **buried in an expression**:
  `let r = 1 + usleep(600000)` inside a spawned task prints
  `slow: start / fast: ran / slow: done` — the sibling runs during the block.
  (The saw-lang skill still documents buried blocking calls as a compile error;
  that note is stale.)
- Unjoined children complete at group scope exit (`0 / 1 / 2 / 100`).
- `&var` across a suspension mutates the caller's value: `bump_twice(&var n)` →
  `7 / 7`.
- Whole-referent replacement works for scalars and for a `move`d `ExplicitCopy`
  struct through `&var`.
- Cancellation of a `yield_now` loop returns cleanly.

The colorless model is the second-strongest thing in the language after the
exclusivity law. Being able to write `stream.read()` at arbitrary nesting depth
inside a `match` scrutinee, with the compiler either transforming it or refusing
with an anchored error, is a materially better developer experience than Rust's
`async fn` coloring, and it is *implemented*, not sketched.

### 2.10 Claims 23–38, 41–46 — surface, modules, freestanding

All the README snippets compile and produce the documented output, verbatim,
including the Quick Example, optionals, `Result`, pattern matching, traits,
overloading, generic inference, `#file`/`#line`/`#function`, shadowing, the Copy
family, collection literals, default parameters, ranges, literal suffixes, `_`
discard, `assert`, and primitive extensions. Selected sharper results:

- **No implicit conversions** (claim 29) is enforced even for widening:
  `argument 'x' expects 'Int64' but got 'Int32'`. Zig-grade explicitness.
- **Inference ties** (claim 30) produce exactly what the README promises:
  `ambiguous call to 'take': type-argument inference matches multiple generic
  overloads (Wrap<Int>) … matching: <T> take(w: Wrap<T>) with <T=Int>;
  <T> take(w: T) with <T=Wrap<Int>>`.
- **Member visibility** (claim 37) works cross-module with precise messages
  (`field 'name' of struct 'Config' is private and not accessible from this
  module`).
- **`static_assert`** (claim 42) fails the build: `static assertion failed:
  UartRegs layout drift`.
- **Freestanding** (claim 41) cross-compiles cleanly to `riscv32-unknown-none-elf`
  (3096-byte object) and `aarch64-unknown-linux-gnu`. But `--freestanding`
  targeting the **host on macOS** is a hard LLVM abort, not a diagnostic:

  ```
  LLVM ERROR: Global variable 'kernel_add' has an invalid section specifier
  '.text.kernel_add': mach-o section specifier requires a segment and section
  separated by a comma.
  ```

  and it leaves a 0-byte `.o` behind. `sawc/codegen/core.py:1450-1452` already
  knows Mach-O rejects that spelling and guards the `runtime_build` path; the
  `freestanding` path was not given the same guard.

---

## 3. Design assessment

### 3.1 Where the design is strong

**The exclusivity law is the right bet.** Saw's central wager is that dropping
escaping references buys you Rust's aliasing guarantee without Rust's lifetime
system. Having tried to break it, I believe the wager pays. The argument in
`LANGUAGE_SPEC.md:1620-1642` is sound and, more importantly, the *invariant it
rests on is stated in the spec as a standing constraint on future features* —
that is unusually disciplined language design. The result is that the two hardest
things about Rust for newcomers (lifetime annotations, and the borrow checker
rejecting programs you cannot reformulate) simply do not exist, while the
guarantee that matters is retained.

**All shared mutable state is mediated.** No `static mut`; `Arc` refuses
`&var self` forwarding; statics must be `Sync`; `Atomic` is the sanctioned
interior-mutability primitive; multi-threaded spawn is `Send`-checked. That is a
short, closed list of doors, all of them locked, all with good error messages.
Very few languages can say this.

**Type-carried unsafety.** Replacing `unsafe { }` regions with "the obligation
follows the pointer's *visibility in the signature*" is the most original idea in
the language and I think it is better than the thing it replaces. It cannot be
laundered by enlarging a block, and the "marked domain" concept (a struct with a
pointer field has already advertised itself, so its `self`-methods are clean) is
exactly the right escape valve for container implementations.

**Colorless concurrency that actually compiles.** Effect inference plus a
source-level coroutine transform, with `sync` as the *checked negative*, is the
right polarity: the common case is unannotated and the rare constraint is
declared. And the compiler's honesty here is exemplary — every place the
transform cannot handle produces an anchored user-facing error rather than a
silent blocking call.

**Diagnostics.** Across ~40 error probes, the quality is consistently better than
mainstream compilers: hints propose the fix, the exclusivity errors name the
overlapping path, the `sync` error prints the transitive call chain to the
offending suspension, the Send error names the type *and* the remedy. This is a
real asset and it should be treated as a shipped feature.

### 3.2 Where the design has gaps and internal tensions

**(a) Ownership vs. structured concurrency — the unresolved seam.** The language
promises deterministic destruction; the scheduler retains completed task frames
until group teardown (§2.3). These are the same claim pointing in two directions,
and the collision is not theoretical: it produces a silent deadlock in the EOF
pattern (§2.4) and an unbounded fd leak in the accept-loop server the README
advertises. A `TaskGroup` is documented as a *lifetime scope*; right now it is a
lifetime *extender*. This is the most important defect in the review.

**(b) Explicitness has no synthesis escape hatch for the structural cases.**
Saw's principle — every cost visible at the point it happens — is right, and
`move`/`.copy()` at transfer sites is a good trade. But the principle has been
applied where the compiler already knows the whole answer: composing `Deinit` and
`ExplicitCopy` through a struct's fields is 100% mechanical, and requiring the
body to be typed out buys zero information. Compare `Equatable`, which got this
right: `extension T: Equatable {}` opts in and synthesizes. The tension is not
"explicit vs. easy", it is "explicit *declaration*" (good) vs. "explicit
*transcription*" (pure tax).

**(c) The surface syntax has a hard, undocumented one-line rule.** No
parenthesized list — call arguments, function parameters, struct literals — may
span lines (§3.3). The consequence is visible in the project's own flagship Saw
program: `blade/src/resolver.saw:271` is a **210-character** single-line function
signature. This is the largest gap between "Swift-style syntax" as a claim and
what writing Saw feels like. It also cannot be worked around, only endured.

**(d) `{ }` in statement position is a silently-uncalled closure.** The
collection-literal design ("`{}` and `{expr}` are ALWAYS closures") makes a bare
block a value expression, and an unused value expression is silently discarded
(§3.3). This is the only place I found where Saw *silently does nothing* — every
other sharp edge in the language produces a diagnostic. It is directly against
the project's stated "never hide errors" principle.

**(e) Mutable captured state in an escaping closure is silently wrong.**
`make_counter()` returns 1, 1, 1 (§3.3). This is a correctness bug, not an
ergonomic one: a well-known idiom compiles, runs, and produces the wrong answer
with no diagnostic.

**(f) Builtins are not in the namespace.** A user-defined `func print(x: Int, y: Int)`
or `func assert(a: Int)` is silently ignored rather than rejected as a
redefinition, and the resulting arity error blames the user's call site (§3.3).
The "shadowing must be earned" rule is carefully worked out for locals and
explicitly exempts prelude names — which leaves the top-level collision case with
no rule at all.

**(g) `Arc<T>` is a shared-ownership type with no read path.** `Arc` exposes
`init`, `copy`, `deinit`, `strong_count` and forwards `&self` methods. There is
no `.value()`, and field access fails with `struct 'Arc' has no field 'n'` — a
message that additionally leaks Arc's private internal (`hint: available fields:
ptr`). So `Arc<SomeStruct>` requires the payload type to have been written with
accessor methods; `Arc<Vector<Int>>` is effectively opaque. For the type the
compiler *recommends* whenever you hit a sharing problem, that is a thin API.

**(h) Distinct `type` aliases are inconsistent and, over fixed-width types,
unconstructible.** See §3.3 — the spec's documented construction form
(`UserId(42)`) does not exist, and whether a value can enter the alias at all
depends on whether the underlying type is `Int` or `Int64`.

**(i) Code size.** `examples/hello.saw` (8 lines) links to a **143 KB** binary;
a 30-line program emits 19,022 lines of IR before optimization, because the
prelude instantiates the scheduler's `Vector<Box<any Resumable>>`, `Atomic`,
`Channel`, `Mutex`, etc. regardless of use. The freestanding profile has an
internalize+`--gc-sections` answer for this; the hosted profile does not. For a
language courting embedded and kernel work, hosted code size is a proxy the
audience will check.

### 3.3 Sharp edges hit while probing (exact repros)

**1. Multi-line parenthesized lists do not parse.**

```saw
func three(a: Int, b: Int, c: Int) -> Int { a + b + c }
let x = three(1,
              2,
              3)
```
```
error: Parse error at 5:21: Unexpected token: NEWLINE
```
Same for a wrapped signature (`Parse error at 7:14: Expected parameter name`) and
a wrapped struct literal (`Parse error at 13:20: Expected field name`). Zero of
the 846 files in `examples/` wraps a call — because none can.

**2. A bare block silently evaluates to an uncalled closure.**

```saw
func main() {
    let a = R(id: 1)
    {
        let b = R(id: 2)
        print(100)
    }
    print(200)
}
```
```
200
1
```
`100` never printed; `R(id: 2)` was never constructed. Compiles clean, no
warning. There is consequently **no anonymous scope** in the language: narrowing
a resource's lifetime requires extracting a function.

**3. Mutable state captured by an escaping closure resets on every call.**

```saw
func make_counter() -> () -> Int {
    var n = 0
    { n = n + 1
      n = n + 10
      n }
}
// print(c()) three times
```
```
11
11
11
```
Mutation is visible *within* one invocation (0+1+10 = 11) and discarded between
them. Either it should persist, or the mutation of a by-value capture should be
a compile error. Silently returning 11,11,11 is the worst of the three options —
especially next to `[&var n]` borrow-captures, which *do* mutate the real
variable (`examples/closures_borrow_capture.saw`).

**4. Binding a `Void` expression is an ICE with an empty message.**

```saw
func nothing() { }
func main() { let n = nothing() }
```
```
error: internal compiler error:
```
Type-checking *passes* (`Type check passed` under `-v`); codegen crashes on
`AssertionError` in `llvmlite`'s `alloca(void)` (`sawc/codegen/statements.py:272`
→ `core.py:427`). The generic ICE wrapper then prints an empty reason.

**5. Redefining a builtin is silently ignored.**

```saw
func assert(a: Int) -> Int { a * 2 }
func main() { print(assert(21)) }
```
```
error: `assert` takes exactly two positional arguments (a Bool condition and a String message)
```
Same for `print`. The user's declaration is never in the overload set and never
reported. This also bit me writing an `extern "C" { blocking func sleep(...) }`
probe, where the builtin `sleep` won and produced a `Void` type error two lines
away from the actual cause.

**6. Returning an owned parameter requires `move`, with a "cannot copy" message.**

```saw
func ident(v: Vector<Int>) -> Vector<Int> { v }
```
```
error: cannot copy value of type `Vector<Int, GlobalAllocator>` which implements ExplicitCopy
   hint: use .copy() for an explicit deep copy, or `move` to transfer ownership
```
No copy was requested; the callee already owns `v` and is returning it at end of
scope. Both the requirement and the wording ("cannot copy") are wrong-footed.

**7. Distinct `type` aliases: the spec's construction form does not exist, and
constructibility depends on the underlying type.**

```saw
type UserId = Int64
let user: UserId = UserId(42)      // spec LANGUAGE_SPEC.md:1245, verbatim
```
```
error: undefined function `UserId`
```
```saw
type AliasI   = Int
type AliasI64 = Int64
let a: AliasI   = 42     // OK
let b: AliasI64 = 42     // error: cannot assign `Int` to variable of type `AliasI64`
let c: AliasI   = mk()   // OK — a runtime Int flows implicitly INTO the alias
func take(u: AliasI) -> Int { u as Int }
take(mk())               // error: argument `u` expects `AliasI` but got `Int`
```
So: an alias over `Int` accepts an implicit underlying value in an *annotated
let* but not in a *parameter*; an alias over `Int64` accepts nothing at all and
has no constructor. The "units and domain types" use case the spec advertises is
not reachable over fixed-width types.

**8. Closure parameter types are not inferred from a declared function-type
return.**

```saw
func adder(n: Int) -> (Int) -> Int { { x in x + n } }
```
```
error: Cannot infer type for closure parameter `x`. Add type annotation: `x: Type`
```
The return type `(Int) -> Int` fully determines `x`. Inference reaches into
closure *return* types (README's `map` example) but not into closure *parameter*
types from an expected function type.

**9. `--freestanding` on a Mach-O host is an uncaught LLVM abort.** See §2.10.

**10. Diagnostic hints teach undocumented syntax.** The missing-`Deinit` hint
suggests `func deinit(var self)`; the missing-`ExplicitCopy` hint suggests
`func copy(self)`. Neither spelling appears in the spec. `var self` compiles and
behaves as `&var self`.

---

## 4. The five changes I would argue for hardest

**1. Release a task's frame when the task completes, not when its group dies.**
(§2.3, §2.4.) This is a correctness and resource-safety defect, not a
performance nit: it silently deadlocks the standard reader/writer EOF pattern and
leaks a file descriptor per connection in the README's own server example.
Everything else on this list is a papercut by comparison. If frames must be
retained to keep `join()` results alive, retire the frame's *owned values* at
completion and keep only the result slot; or have `join()` consume the handle and
release the frame.

**2. Give every language-raised panic a `FILE:LINE`.** (§2.7.) Bounds, overflow,
division by zero, shift range, force-unwrap, `try!`. The machinery exists and is
already used for `assert`. A trap you cannot locate undercuts the central safety
pitch, and it is the cheapest high-value fix on this list. Unify all three
formats on `panic at FILE:LINE: <reason>` while you are in there.

**3. Synthesize structural `Deinit` / `ExplicitCopy` from an empty conformance.**
(§2.2, §3.2b.) Keep the opt-in — `extension Holder: Deinit {}` — and derive the
field-by-field body, exactly as `Equatable` already works. This removes the
single largest boilerplate tax in the language without giving up the "you must
declare it" property. Fix the two hints' receiver spellings at the same time.

**4. Allow parenthesized lists to span lines, and stop treating a bare `{ }`
statement as a discarded closure.** (§3.3 items 1 and 2.) The first is a lexer
change (suppress NEWLINE inside an open bracket depth) and it is the difference
between "Swift-style syntax" being a claim and being true — the evidence is a
210-character signature in Blade's own resolver. The second should either become
a real scope block or a hard error; silently skipping user statements is the one
place the language violates its own "never hide errors" rule.

**5. Close the two silent-wrong-answer holes: mutable closure captures, and
builtin redefinition.** (§3.3 items 3 and 5.) `make_counter()` returning 1,1,1
and a user's `func print(...)` vanishing are both cases where the compiler
chooses a semantics the programmer did not ask for and says nothing. Pick a
rule for each (persist-or-reject; shadow-or-reject) and enforce it loudly. While
there, make `let n = <Void>` a type error instead of an ICE (§3.3 item 4).

Runner-up, not in the five because it is scope rather than defect: give `Arc<T>`
a payload read path (`&self` projection or a `with_ref`-style scoped borrow).
It is the type the compiler recommends every time sharing comes up, and today it
can only be read through methods the payload's author happened to write.

---

## 5. Bottom line

Judged as a serious systems language pitching itself against Rust, Swift and Zig:
the **semantic core is competitive today**. The exclusivity law without lifetimes
is a real contribution; type-carried unsafety is a genuine improvement on
`unsafe` blocks; colorless concurrency with a checked `sync` negative is better
than `async`/`await` coloring and it is built, not designed; monomorphization and
the diagnostics are at or above the standard of the languages it names.

What is not yet competitive is the **resource-lifetime story at the concurrency
boundary** (change 1) and the **surface ergonomics** (changes 3 and 4) — and
those two, not the type system, are what a prospective user will hit in their
first afternoon. Four README sentences currently promise slightly more than the
compiler delivers (§2.3, §2.5, §2.6, §2.7); three of them are one clause away
from being true, and one of them (task-frame destruction) is a bug to fix rather
than prose to soften.

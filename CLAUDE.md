# Saw Language Project

A modern systems programming language combining Rust's safety with Swift's elegance.

## Project Status

Active implementation. A working compiler (Python + LLVM via llvmlite) lowers a
large language subset — see the "Current Features" section below for the landed
feature list and `LANGUAGE_SPEC.md` for the full specification. Design work
continues per-brief in `designs/`.

## Key Design Decisions

### Memory Management
- The Copy trait family governs transfers (decided in `designs/06`, landed):
  - Trivial types (POD, recursively) auto-conform to `Copy` and copy bitwise
  - `ImplicitCopy` types copy implicitly and cheaply at every transfer
    (refcount bump) — e.g. `String`, `Arc`
  - `ExplicitCopy` types (e.g. `Vector`, `Map`) never copy implicitly: `move`
    to transfer, or a visible `.copy()` to duplicate
  - `NoCopy` types (e.g. `File`, `Mutex`) are move-only
  - `T: Copy` generic bound grants `.copy()`; containment rules are explicit
- Explicit `move` keyword for ownership transfer, enforced at one value-transfer
  checkpoint in the typechecker
- No garbage collector; deterministic LIFO destruction via `Deinit`
- References (`&T`, `&var T`) are parameters only, cannot escape; no lifetimes.
  Mutable aliasing is caught statically by the Law of Exclusivity
- Shared ownership via `Arc<T>` (atomic refcount — Arc-only, no `Rc`, decided
  design 16; landed) and owned heap allocation via `Box<T, A>` (landed)
- Synchronized access via `Mutex<T>` (landed, hosted); `RwLock<T>` planned
- Pluggable allocation: the allocator is a public **default type parameter**
  on alloc-layer containers — `Vector<T, A: Allocator = Global>`,
  `Map<K, V, A = Global>` (landed in `designs/37`). Hosted code writes
  `Vector<T>` (fills `A = Global`, one identity with `Vector<T, Global>`); a
  custom zero-sized allocator gives a *distinct* type that routes
  alloc/grow/deinit through its own `A` as a direct call. Module-level
  `static` declarations (`designs/41`) and **per-type slab allocators**
  (`designs/42`) have landed: `Box<T, A: Allocator = Global>` (NoCopy owned
  heap allocation; `Box<T>.make`/`.make_or` factories) plus `std/slab.saw`'s
  fixed-chunk slab over a `static` region make the `type JobBox = Box<Job,
  JobSlab>` kernel idiom work end to end (`designs/19` §4).

### Mutability
- Immutable by default (`let`)
- Explicit `var` for mutable bindings
- `var` parameters allow mutation of caller's value
- Call sites mirror the parameter's reference spelling: `&x` lends immutably to
  a `&T` param, `&var x` lends mutably to a `&var T` param. A mismatch either way
  is a compile error, and `&var x` requires `x` to be a `var` binding. A `&var`
  reference is only valid as a call argument.

### Type System
- Algebraic data types (enums with data)
- Traits for polymorphism
- Generics with trait bounds
- No null - `T?` optionals (postfix syntax like Swift)
- `Result<T, E>` for error handling
- Type extensions for adding methods to existing types
- `type` creates distinct types (can flow to underlying, but not vice versa)

### Syntax Philosophy
- Expression-oriented (everything returns a value)
- `guard let` for early exits (from Swift)
- String interpolation: `"Hello, {name}!"`
- Trailing closure syntax
- Pattern matching as core feature
- Collection literals with the `{ }` closure rule (design 54): `{k: v, ...}` is
  a `Map` literal (colon), `{a, b, ...}` a `Set` literal (comma), `{:}` the empty
  map (needs an annotation); `{}`, `{expr}`, `{ x in ... }`, `{ $0 ... }` are
  ALWAYS closures/blocks (spell empty/singleton collections `Map<K,V>()`,
  `Set<T>()`, `Set.of(x)`). Bounded parser lookahead, no type feedback; duplicate
  keys last-wins. A bracket literal `[a, b]`/`[]` builds a `Vector` when the
  expected type is `Vector<T, A>` (annotation/param/return/field), else a
  fixed-size array.
- Swift-style `init` for struct initialization: `Point(x, y)`
- Named parameters in enums: `Move(x: Int, y: Int)`

### Key Differences from Rust
1. `var` instead of `let mut` (consistent use of `var` for mutability)
2. No lifetimes - reference params `&T`/`&var T`, and the call site mirrors the
   sigil (`&x` / `&var x`)
3. Copy trait family: trivial types copy, owning types move with explicit `.copy()`
4. `T?` for optionals (postfix, Swift-style)
5. `guard let` for early unwrapping
6. Simpler closure syntax: `{ x in x * 2 }` or `{ $0 * 2 }`
7. Named tuple fields
8. `Type(...)` initialization instead of `Type::new(...)`
9. Type extensions like Swift
10. `type` definitions are distinct (alias→underlying allowed, underlying→alias requires initialization)
11. Python-style imports with full keywords (`import`, `module`, `public`)

### Module System
- Python-style imports (no namespace pollution)
- `import std.io` adds only `io` to namespace
- `import std.io.{Read, Write}` adds specific symbols
- Aliasing (design 53): `import std.io as sio` (module alias) and
  `import std.io.{Read as R, Write}` (per-symbol alias) — purely local renames
  (mangling/module graph unchanged); duplicate local name in one selective import
  is an error
- Full keywords: `module`, `public`, `import` (not `mod`, `pub`, `use`)
- `package` and `parent` for relative imports (not `crate`, `super`)

### Concurrency
- Colorless cooperative tasks (NO `async`/`await` keyword; suspendability is
  effect-inferred, `sync` is the checked negative effect) — see `TaskGroup` below
- Channels for message passing
- `Send`/`Sync` traits for thread safety
- Coroutine transform (design 44 + design 45 Part 0): a suspending function or
  method driven by `__drive(f())`/`__drive_steps(f())`/`__drive(recv.m())`
  (test-only entry) is rewritten source-level into a frame struct (params +
  across-suspend locals + embedded callee sub-frames + `__state`/`__wake` +
  result slot) plus a `resume(&var self) -> __Poll` method, compiled by the
  existing codegen/deinit machinery. Cleanup is normal-control-flow only (no
  forced destroy). Landed: conditional move across a suspend (frame drop flag +
  `__forget` clear-without-drop, 0a); nested suspending calls embedded by value
  and driven (0b); driving a suspending method with `&var self` across a suspend
  (receiver held as a frame pointer, 0c). Suspending recursion, a suspension in
  nested control flow (loop/if/match), and generic driven functions/methods are
  compile errors. OFF by construction for code that drives nothing.
- Cooperative executor (design 45, single-task slice): `yield_now()` and
  `sleep(ms)` are the real cooperative suspension primitives (`__suspend()` stays
  test-only). A suspending `main` (one that reaches `yield_now`/`sleep`) is
  auto-wrapped in a single-threaded entry executor that drives its frame,
  parking the thread per `sleep` wake (via the `saw_sleep_ms` seam).
- Multi-task `TaskGroup` (design 52b): the C1 nursery on the erased run queue.
  Every frame gets compiler-synthesized conformance to a builtin `Resumable`
  trait (`resume(&var self) sync -> __Poll` + `__wake_reason(&self) sync -> Int`);
  frames are boxed as `Box<any Resumable>` (design 51) into a
  `Vector<Box<any Resumable>>`. `group.spawn(f(args)) -> TaskHandle<T>` lowers
  like `__drive` (a synthesized `__spawn_f` boxes/enqueues the frame; T non-Void).
  The executor (round-robin, honoring yield/sleep-earliest-deadline/channel-yield)
  lives in the group and is `sync`, so the group's `Deinit` runs it to completion
  of every child — structured join falls out of LIFO destruction (the group,
  declared before its handles/resources, is torn down first; frames are
  self-contained since spawn strips references). `TaskHandle.join()` drives then
  takes the frame's `__result` exactly-once (force-unwrap + `__forget`); an
  unjoined result drops once at teardown. Cancellation is cooperative: a
  frame-resident `__cancel` word set by `handle.cancel()`, read by `cancelled()`
  (rewritten to the frame word), observed through normal control flow — NO forced
  destroy. Suspending channel receive = `Channel.try_receive() -> T?` + the Part-0
  `yield_now`-on-empty loop idiom. The design-21b `spawn`/`Task`/`Channel`
  thread-per-task engine is separate and untouched — the two engines coexist,
  not unified.

## Open Questions

- Final language name (Saw is placeholder)
- Semicolons: required, optional, or forbidden?
- Compilation target: LLVM, VM, or transpilation?

## File Structure

```
LANGUAGE_SPEC.md   # Full language specification
CLAUDE.md          # This file - project context
sawc/              # Saw compiler (Python + LLVM)
  sawc.py          # CLI entry point
  lexer.py         # Tokenizer
  parser.py        # Recursive descent parser
  ast_nodes.py     # AST node definitions
  codegen.py       # LLVM IR code generator
examples/          # Example Saw programs
  hello.saw        # Hello world
  math.saw         # Math operations and recursion
  variables.saw    # Variables and control flow
```

## Python Environment

Dependencies live in a virtualenv at `.venv/` (Python 3.14, llvmlite installed).
Always use it instead of system Python:

```bash
# Either activate it...
source .venv/bin/activate

# ...or invoke it directly
.venv/bin/python test_runner.py
.venv/bin/python sawc/sawc.py examples/hello.saw -o hello
```

Note: the Makefile calls bare `python3`, so `make test` requires the venv to be
activated first.

## Scratch Compilations

For throwaway experiments (probing a bug, checking codegen output), do NOT
write `.saw` files to `/tmp` or create them via shell heredocs/echo — those
commands can't be auto-approved. Instead:

1. Create the file with the Write tool under `.build/scratch/` (gitignored)
2. Compile: `./.venv/bin/python sawc/sawc.py .build/scratch/foo.saw -o .build/scratch/foo`
3. Run: `./.build/scratch/foo`

All three steps are covered by the project permissions allowlist in
`.claude/settings.json`, so they run without prompts.

## Command Hygiene (avoids permission prompts)

- Read files with the Read tool — to read several files, batch multiple Read
  calls in one message. Do not `cat` files via Bash loops.
- For code navigation in the Python compiler (sawc/), prefer the LSP tool
  (pyright is configured project-wide): `workspaceSymbol` to locate a
  symbol, `goToDefinition`/`findReferences`/`incomingCalls` to trace usage.
  It is faster and more precise than `grep`. For text/pattern searches, use
  the Grep and Glob tools — if they are not in your tool list, load them
  first with `ToolSearch: select:Grep,Glob`. Plain read-only Bash `grep`/`ls`
  are allowlisted as a fallback; `find` and pipelines are not.
- Never prefix commands with `cd <absolute path>; ...`. Your working directory
  is already the repo/worktree root and relative paths resolve there. Allowlist
  rules match from the start of the command string, so a `cd` prefix (or any
  compound wrapper) turns an auto-approved command into one that prompts.
- Run commands in the exact allowlisted forms shown in this file
  (`./.venv/bin/python ...`, `./.build/...`).
- To check several tests, use the runner's multi-pattern filter instead of a
  shell loop: `./.venv/bin/python test_runner.py -f test_a,test_b,test_c`.
  Don't pipe runner output through grep/head — failure detail is already
  printed in the summary, and `-v` adds it for xfail tests too.
- NEVER run inline Python (`python -c "..."`, `python - <<EOF`). For any
  Python probe — importing compiler modules, checking llvmlite APIs,
  inspecting a parse tree — Write a script to `.build/scratch/probe_*.py`
  and run it with `./.venv/bin/python .build/scratch/probe_foo.py`. That
  command form is allowlisted; every unique `python -c` string prompts the
  user and cannot be allowlisted.

## Compiler Usage

```bash
# Install dependencies (into .venv)
.venv/bin/pip install llvmlite

# Compile a Saw program
./sawc/sawc.py examples/hello.saw -o hello

# Run the compiled executable
./hello

# Verbose output
./sawc/sawc.py examples/hello.saw -v

# Emit LLVM IR only
./sawc/sawc.py examples/hello.saw --emit-ir
```

## Testing

The compiler includes a comprehensive test runner:

```bash
# Run all tests
make test

# Run with verbose output
make test-verbose

# Run specific tests by pattern
make test-filter FILTER=enum
make test-filter FILTER=while_expr_conditional_found

# See TESTING.md for detailed documentation
```

**Test Coverage:** a growing suite of success, error, and panic cases — run
`make test` to see the current count.

**App-level testing (`blade test`):** `test_runner.py` tests the *compiler*.
A Saw application tests itself with Blade: `tests/*.saw` files that pass by
exiting 0 (fail via `assert`/`panic`), discovered/compiled/run by the
`blade test` subcommand (design 49). Separate machinery from the compiler
suite — see the "Application-Level Testing" section of TESTING.md. Blade's own
tests live in `blade/tests/`.

## Current Features

The compiler currently supports:

### Core Language
- Functions with parameters and return types
- Generic functions: `func identity<T>(x: T) -> T`
- Generic structs: `struct Box<T> { value: T }`
- Generic enums: `enum Maybe<T> { case Just(value: T), case Nothing }`
- Generic methods (method-level type params): `func map<U>(&self, f: (T) -> U) -> Vector<U, A>`
  in an extension. Type args are explicit at the call site (`v.map<Int>(...)`);
  inference is future work. Monomorphized per (receiver args, method args) pair.
- Default type parameters: `struct Vector<T, A: Allocator = Global>` — an omitted
  trailing arg is filled from its default BEFORE mangling, so `Vector<Int>` and
  `Vector<Int, Global>` are one type / one monomorphization. Too-few-with-no-default
  and a default that fails its bound are errors.
- Default parameter VALUES (design 53): `func f(x: Int, y: Int = <expr>)` on free
  funcs, methods, inits. Trailing-only; the default is evaluated PER CALL at the
  call site (fresh value each time) through the value-transfer checkpoint (NoCopy
  moves in cleanly); effects flow through (a suspending default taints the callee,
  so a `sync` caller filling it is diagnosed); decl-site shape expansion extends
  design 55's `_overload_sig_key` (a defaulted decl's reachable arities must not
  collide with another overload's shape). Mangling unchanged (filled caller-side).
- Basic types: Int, Float, Bool, String
- `Int`/`UInt` are **pointer-width** (design 47): i64 on x86-64/aarch64, i32 on
  riscv32. The `Int` range (max/min) is target-dependent; an integer literal is a platform
  `Int` and one exceeding the target word errors at the literal. Fixed-width
  `Int8`…`Int64`/`UInt8`…`UInt64` have stable layouts — use them for wire
  formats. One `self.int_type` (from the target datalayout pointer size) drives
  every platform-`Int` lowering. Genuinely-64 sites are only the fixed-width
  `Int64`/`UInt64` types; the runtime seams (`saw_alloc`/`write`/`panic` sizes),
  the String header (`{ isize refcount, isize len, bytes }`), and the Arc/Channel
  atomic refcount all follow the platform word too — the stdlib already types
  them `Int`, so hosted (64-bit) codegen is byte-for-byte unchanged.
- `Int.max`/`Int.min` (design 53): platform-width bounds from one source of truth
  (the target word); `.max`/`.min` on every fixed-width type + `UInt`.
- Variables: `let` (immutable) and `var` (mutable). Every binding MUST initialize
  (uninitialized `var x: Int` is a parse error) — use-before-init is structurally
  impossible (design 53 Part 7 verdict, no definite-init analysis needed).
- Discard binding `let _ = expr` (design 53 / DF1): evaluates the RHS, consumes
  it as final owner (move for NoCopy), drops it immediately at statement end,
  binds nothing. `_` unreadable; two `let _` never collide; `var _` is an error.
- Arithmetic: `+`, `-`, `*`, `/`, `%` (modulo); wrapping `&+ &- &*`
- Comparisons: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `&&`, `||`, `not`
- Bitwise: `&`, `|`, `^`, `~`, `<<`, `>>` (integer-only) + compound `&= |= ^= <<= >>=`;
  C-family precedence; `>>` arithmetic on signed / logical on unsigned; a shift
  amount that is negative or `>=` the width panics ("shift out of range")
- Integer literals: decimal, hex `0xFF`, binary `0b1010`, octal `0o755`, with
  `_` digit separators (`0xDEAD_BEEF`, `1_000_000`). Rust-style fixed-width
  suffixes (design 53): `255u8`, `1_000i32`, `0xFF_u8` (set i8/i16/i32/i64/
  u8/u16/u32/u64, optional single `_` before the suffix) — the literal IS that
  fixed-width type, range-checked at the literal (`256u8` errors), and does not
  implicitly convert to another fixed-width type.
- String escapes include `\u{1F600}` (design 53): 1-6 hex digits, valid Unicode
  scalar only (surrogates + >0x10FFFF rejected at lex time), encoded to UTF-8.
- Ranges: `a..b` (exclusive) and `a..=b` (inclusive, design 53 — a dedicated
  Int.max-safe `RangeInclusive`, no `a..(b+1)` desugar). `vec.enumerated()`
  ((Int, T) iterator) + `vec.each_indexed((Int, T) -> Void)`.
- Arrays: literals `[1, 2, 3]`, indexing `arr[i]`, type `[Int; 5]`
- Control flow: `if`/`else` expressions, `while` loops, `for` loops
- Loop control: `break`, `continue`
- Recursion
- `print(...)` built-in for debugging

### Type System
- Tuples: literals, indexing, multiple return values
- Structs: declarations, field access, initialization
- Field assignment: `obj.field = value`
- Optionals (`T?`): `None`, `!`, `??`, `?.`
- Call-site optional auto-wrap (design 57, DF3): a bare `T` argument auto-wraps
  into a `T?` parameter at all call forms (free/method/static/module/init/enum
  payload). One level only; ordered AFTER overload resolution (exact beats
  optional-wrap, design 55 rule 1); NOT through a generic-instantiation boundary
  (`id<Int?>(5)` is an error — explicit optional required). Move/copy unchanged.
- Optional binding: `if let`/`if var`, `guard let`/`guard var`
- Enums with associated values and `match` expressions
- Match exhaustiveness checking (must cover all variants or use `_` wildcard)
- Result<T, E> with auto-wrap returns
- `try`/`try?`/`try!` operators for error handling
- `try { } catch { }` blocks with implicit `error` variable
- Multiple error types with match in catch block

### Extensions & Methods
- `extension` blocks for adding methods to structs
- Generic extensions: `extension Box<T> { ... }`
- Immutable methods: `func method(&self) -> Type`
- Mutable methods: `func method(&var self)` (receives a mutable reference)
- Custom `init` methods with overloading
- Method calls: `obj.method(args)`
- `self` keyword in method bodies
- Function/method/static overloading (design 55, exact-match model): a name
  carries an overload set; a candidate matches iff every argument is exactly
  type-compatible (no implicit conversions). Pinned tie-breaks: exact beats
  optional-wrap; resolution precedes Result/optional auto-wrap; concrete beats
  generic (a generic overload competes only with explicit call-site type args).
  Closures resolve on the non-closure args (closure-only tie = ambiguity).
  Declaration-site rejection of indistinguishable signatures (post-alias, bare
  type params folded). Resolution is one chokepoint feeding the value-transfer
  checkpoint, per-overload effect edges, and exclusivity. `StringBuilder.append`
  absorbs the old `append_int` as an `append(Int)` overload.

### Type System
- Type aliases: `type MyInt = Int` (creates distinct type)
  - Alias can flow to underlying: `func double(x: Int)` accepts `MyInt`
  - Underlying cannot flow to alias: `func process(x: MyInt)` rejects `Int`
  - Chained aliases work: `type A = Int`, `type B = A` → B flows to A flows to Int
- Associated types in traits: `type Item`
- Type assignments in extensions: `type Item = Int`

### Traits
- Trait definitions: `trait Name { func method(&self) -> Type }`
- Trait conformance: `extension Type: Trait { ... }`
- Conformance checking (missing methods, signature mismatches)
- Multiple trait conformance: `extension Type: A, B { ... }`
- Trait bounds on generics: `func foo<T: Trait>(x: T)`
- Bounded generic extensions: `extension Vector<T: Copy>: ExplicitCopy { ... }`
- Method-level generic type params: `func map<U>(&self, ...) -> Vector<U>` — a
  method introduces type params beyond the extension's; explicit call-site args
  (`v.map<Int>(...)`), inference not yet implemented. `Vector.map`/`fold` use them.
- Associated types with resolution: `type Item` → `type Item = Int`
- `any Trait` existentials (design 51): type-erased dynamic dispatch via a fat
  pointer `(data, vtable)`. `any` is a contextual keyword in type position.
  Legal only behind explicit ownership — `&any Trait` (borrowed) and
  `Box<any Trait, A>` (owned, NoCopy); anything else is a clean unsized error.
  Erasure happens at construction/call boundaries: `&concrete` → `&any Trait`
  (vtable attached), and erased-direct `Box<any Trait>.make(v)`. Dispatch loads
  a method thunk from the vtable slot; effects follow the trait signature (a
  `sync` trait method stays sync-callable through `any`). Box teardown pulls
  destructor/size/align from the vtable and routes dealloc to `A` (exactly-once).
  Object safety (v1) rejects Self-by-value methods (the Copy family), generic
  methods, associated types, and marker traits (`&var self` receivers ARE
  any-able). `make_or` on an erased Box and `Arc<any Trait>` are deferred.
- `Equatable` trait gates `==`/`!=` (design 32): trivial (POD) structs and
  payload-free enums auto-conform (the auto-Copy set); primitives + `String`
  builtin. Others opt in via `extension T: Equatable {}` — an empty body
  synthesizes memberwise `==` (structs) / payload-deep `==` (enums); a
  hand-written `equals` overrides. `!=` is the negation; Float keeps IEEE
  semantics (`NaN != NaN`); `T: Equatable` bound grants `==` in generics.
- `Comparable` trait gates `< <= > >=` (design 48), which desugar to
  `compare(&self, other: Self) -> Ordering` (`enum Ordering { Less, Equal,
  Greater }`). Integer types, `Float` (IEEE; NaN unordered → all ops false),
  and `String` (byte-lexicographic) are builtin. **No auto-conformance** —
  opt in via `extension T: Comparable {}` (synthesizes lexicographic
  field/payload-order compare; hand-written `compare` overrides). Requires
  `Equatable`. `T: Comparable` bound grants the operators in generics.
- `Hashable` trait gates hash-map keys (design 48): `hash(&self, h: &var Hasher)`
  streams into a FNV-1a `Hasher` (`write_int`/`finish`). Conformance mirrors
  `Equatable`'s gating (auto for trivial structs + payload-free enums; opt-in
  synthesis otherwise; primitives + `String` builtin). Requires `Equatable`;
  hash/== contract holds (synthesis streams exactly the fields `==` compares).
- **Trait default method bodies** (design 56): a trait method declared with a
  `{ ... }` body is a default. A conformer omits it (inherits a per-conformer
  synthesized copy, typechecked with `Self` = the concrete type) or overrides it;
  a default may call required methods (dispatching to the conformer). Defaults
  flow through trait inheritance, get an `any Trait` vtable slot
  (override-or-default), and infer effects per instantiation (a `sync` default is
  a checked suspension-free context). A method with no default stays required.
- `Printable` trait (design 56, prelude-visible): `format(&self, into: &var
  StringBuilder)` + a default-body `to_string(&self) -> String`. Integer types,
  `Float`, `Bool`, `String` conform builtin (rendered inline; **no
  auto-conformance/synthesis** for user types). String interpolation `"{expr}"`
  and `print(expr)` accept any Printable (builtins keep byte-identical fast
  paths; a non-Printable in interpolation is a clean error); `T: Printable` bound
  grants it in generics. `&var` re-borrow of a mutable-reference parameter is
  allowed (forwarding the shared builder to a nested `format`).
- `Error` trait (design 56): `trait Error: Printable {}` (both spellings: one-shot
  `extension E: Error { format }` or split `: Printable` + empty `: Error {}`).
  `Result<T, Box<any Error>>` is a supported **erased Result** return type:
  returning a concrete `E: Error` auto-wraps Err AND auto-erases into a
  `Box<any Error>` at the return boundary (sequence: overload resolution 55 →
  auto-wrap 30 → erase 56); `try` re-boxes a concrete-error callee at the
  propagation edge and passes an already-erased callee straight through; matching
  `Err(e)`/`catch` binds the box and `"{e}"` renders via the vtable. Boxing uses
  `Global` (hosted convenience; kernel code keeps concrete/union errors — no
  hidden allocation). Erased-error downcasting is deferred (needs a type-id
  design). `type_conforms_to` looks through imported modules (cross-module erase).

### Memory & Safety
- Copy trait family: auto-`Copy` trivial types, `ImplicitCopy`, `ExplicitCopy`,
  `NoCopy`, `T: Copy` bound, memberwise `.copy()` derivation, containment checks
- Value-transfer checkpoint enforces `move`/`.copy()` at every transfer site
- Law of Exclusivity: static "many readers XOR one writer" check on `&var` paths
- `Deinit` with automatic LIFO cleanup (manual `deinit()` calls are rejected).
  A binding `move`d on only some paths carries a runtime **drop flag** so it is
  dropped exactly where it was not moved (conditional-move correctness)
- `Box<T, A: Allocator = Global>`: NoCopy owned heap allocation; static factories
  `Box<T>.make` (infallible, panics on OOM) and `.make_or` (fallible, value
  cleanly deinit'd on failure); payload method forwarding (like Arc) + `value()`
- Slabs (`std/slab.saw`): fixed-chunk allocator over a `static` region via
  `Atomic<Int>` CAS; a user unit-struct allocator + `Box<T, Slab>` is the kernel
  idiom (`designs/42`). Address casts `(&STATIC) as UnsafePointer<T>` / `ptr as Int`
- `UnsafeMemory<T, Use>` (`designs/46`): compiler-known one-word view of memory at
  a fixed address; const-init from an integer literal, static-able, Sync by fiat.
  `Use` is an EXPLICIT intent marker (no default): `Device` emits volatile,
  scalar-only `read()`/`write(v)` with `ReadOnly<T>`/`WriteOnly<T>` field markers
  gating projection (no whole-struct access; volatile ≠ atomic); `Normal` gets
  plain whole-struct/element access plus region accessors `ptr()`/`len()`/`end()`.
  Member/index access PROJECTS to `UnsafeMemory<Field, Use>` at base + compile-time
  offset (never loads the aggregate); declaration-order natural-ABI layout, `_pad`
  idiom for holes
- Reference parameters `&T` / `&var T` (mutate via compound assignment; no escape)
- String: immutable, reference-counted (atomic refcount), O(1) `len()`
- Module-level `static NAME: T = init` (+ `public`): const-initialized,
  Sync-only, immutable (no `static mut`), immortal (never deinit). POD/array
  statics may be bare-declared (zero-init). `Atomic<Int>` is the sanctioned
  interior-mutable primitive (`load`/`store`/`fetch_add`/`compare_exchange`,
  seq_cst) — usable as a static and a struct field; mutating METHODS through an
  immutable static are the one allowed mutation path (design 41), always
  valid UTF-8 (literals validated at lex time; `String.fromBytes(&Data) ->
  Result<String, Utf8Error>` validates at runtime). `bytes()`/`chars()` iterator
  views (chars yields Int scalars — no `Char` type yet); `withCString { ptr in
  ... }` non-escaping C-string borrow. `StringBuilder`: Global-backed, geometric
  growth, `append`/`append_int`, refcount-correct `build()`. Number parsing
  (design 57): `to_int() -> Int?`, `to_int(radix: Int) -> Int?` (design-55
  overload, 2..=36), `to_float() -> Float?` — whole-string match, no trimming,
  empty/junk/overflow → None (panic-free; to_int uses wrapping ops + divide-back
  overflow detection, to_float is naive accumulation, not correctly-rounded)
- Pluggable allocation: `Allocator` trait + `Global`; alloc-layer containers
  carry the allocator as a public default type parameter
  (`Vector<T, A: Allocator = Global>`, `Map<K, V, A = Global>`). `A().alloc(...)`
  is a zero-cost direct call; a custom allocator yields a distinct type and
  deinit frees through the value's own `A`
- `Vector.sort()` (`T: Comparable + Copy`) / `sort_by(compare)` (`T: Copy`,
  non-escaping comparator returning `Ordering`) — design 48: in-place, stable
  insertion sort; byte-level `swap` movement (no element copy), `T: Copy` only
  for by-value comparison reads. `Vector.swap_out(i, v) -> T` moves a slot out.
- `Map<K: Hashable + Equatable, V, A: Allocator = Global>` (`std/map.saw`,
  designs 48 + 54): THE dictionary type — open addressing (linear probing,
  tombstones), power-of-two cap, grow at 3/4 load. `insert`/`get`/`remove`/
  `contains_key`/`len`; Int and String keys. Slots are an enum
  `{ Empty, Tombstone, Occupied(k, v) }` (owning-key-safe); NoCopy (no `.copy()`).
  The old Vector-backed linear-scan `Map` was RETIRED (design 54) — one `Map`,
  and the name `HashMap` no longer exists. Iteration (design 57): non-escaping
  closure VISITORS `each(K,V)`/`each_key(K)`/`each_value(V)` (K/V passed by value;
  skip Empty/Tombstone; order UNSPECIFIED — table order) + SNAPSHOTS
  `keys() -> Vector<K,A>` (K: Copy) / `values()` (V: Copy), built via the
  visitors. Mutating the map inside its own visitor is a static exclusivity
  error. No `entries()` in v1.
- `Set<T: Hashable + Equatable, A: Allocator = Global>` (`std/set.saw`, design
  54): a NoCopy hash set wrapping `Map<T, SetMark>` (zero-field unit value — one
  hash impl). Core `insert(v)->Bool`/`remove(v)->Bool`/`contains`/`len`/
  `is_empty`/`each` (non-escaping visitor)/`to_vector()` (T: Copy)/`Set(from:
  Vector)` (consumes)/`Set.of(v)`. Algebra (borrow `&other`, new set/Bool, bound
  `T: Copy`): `union`/`intersection`/`difference`/`is_subset`/`is_superset`.
  Order UNSPECIFIED.
- Numeric extensions (design 57, `std/numeric.saw`): `extension Int` — `abs()`
  (panics on Int.min per overflow rule), `min`/`max`/`clamp`, `pow` (checked;
  negative exp panics), `is_even`/`is_odd`/`signum`; `extension Float` — `abs`/
  `floor`/`ceil`/`round`/`sqrt`/`min`/`max` (via libm, IEEE NaN). Enabled by
  registering Int/Float as extendable primitive pseudo-structs (the String
  mechanism, generalized).

### Runtime & Tooling
- `static_assert(<const-expr>, "message")` (design 53): legal at top level and in
  statement position. Const-evaluated at codegen (authoritative target layout →
  exact `sizeof`/`alignof`); a false result is a clean compile error carrying the
  message, a true result emits zero code. Evaluator handles int/bool literals,
  unary `-`/`not`, arithmetic/comparison/logical ops, `sizeof<T>`/`alignof<T>`,
  and Int limits; anything else is rejected as non-constant.
- `panic(message: String) -> Never` and `assert(cond: Bool, message: String)`
  builtins (design 49): both route through the freestanding-safe `saw_panic`
  seam. `panic` has the bottom type `Never` (diverges — a function ending in it
  needs no return value; valid in `guard`/`if`/`match` diverging positions);
  `assert` is a no-op on true, else panics `assertion failed: {msg} (line N)`.
- Division / modulo by zero panics ("division by zero")
- Out-of-bounds constant array index is a compile error; tuple index bounds checked
- Force-unwrap of `None` and `try!` on `Err` panic with a message
- Integer overflow panics ("integer overflow") — always, every profile — for
  `+`/`-`/`*` on any integer type, `-Int.min`, and `INT_MIN / -1` (and `% -1`),
  via `llvm.{s,u}{add,sub,mul}.with.overflow` (decided in `designs/31`, landed).
  Intentional two's-complement wraparound uses the `&+`/`&-`/`&*` operators
  (integer-only, same precedence as `+`/`-`/`*`)
- Shift by a negative amount or `>=` the operand width panics ("shift out of
  range") — same house rule as overflow (decided in `designs/50`, landed)
- `std.time` (design 57, `std/time.saw`, HOSTED-ONLY — excluded from
  freestanding): `Duration { nanos: Int64 }` (secs/millis/micros/nanos +
  from_millis/from_secs; Equatable + Comparable + Printable human form
  "1.42s"/"230ms"), `Instant.now()` (monotonic), `elapsed()`/`duration_since()`,
  free `unix_timestamp() -> Int64` (wall clock). Backed by two compiler clock
  shims that hide the timespec layout + macOS/Linux CLOCK_MONOTONIC variance.
- Compiler flags: `-o`, `-v`, `-c`, `--emit-ir`, `--emit-ast`, `-O0`
  (default is an O1-style pass pipeline)
- Attributes + C exports (design 58): Swift-style `@name` / `@name("string")`
  lines before a declaration, v1 legal ONLY on top-level `func`/`static`
  (anything else = clean "attributes are not supported on X"; unknown/duplicate/
  bad-arity errors list the known set `@export`, `@section`). `@export` /
  `@export("sym")` = C calling convention + exact unmangled-or-given symbol +
  external linkage + DCE-survival (`@llvm.used`, holds at default -O1). Exported
  functions must be non-generic, effect-`sync` (an effect ROOT like `main`), and
  match a C-safe signature whitelist (fixed-width ints, `Int`/`UInt`, `Float`,
  `UnsafePointer<T>`, `Void`/`Never` return — `Never` lowers to `void`+noreturn,
  the `_start` shape). REJECTED: `Bool` (bare-`i1` vs C `_Bool` ABI — verdict:
  reject in v1), `String`, optionals, `Result`, tuples, closures, by-value
  structs (pass `UnsafePointer<S>`). Exported statics relax to arrays/structs of
  whitelisted fields (vector-table idiom). Symbol hygiene: duplicate export
  symbol / `main`/`saw_*`/`__saw_*` collision = error; an overloaded name carries
  `@export` on only ONE overload unless explicit distinct symbols. `@section(
  "name")` on funcs/statics = LLVM section (composes with `@export`, verbatim
  name; ELF `.foo` vs mach-o `SEG,sect`). NO `repr(C)` — the declaration-order
  natural-ABI layout is THE documented struct layout rule. `@inline` deferred.

## Example Code

### Basic Extension with Methods
```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    func distance(&self) -> Int {
        self.x + self.y
    }
}

func main() {
    let p = Point(x: 3, y: 4)
    print(p.distance())  // 7
}
```

### Custom Init Methods
```saw
struct Point {
    x: Int
    y: Int
}

extension Point {
    init(magnitude: Int) -> Point {
        Point(x: magnitude, y: magnitude)
    }
}

func main() {
    let p1 = Point(x: 3, y: 4)     // Field init
    let p2 = Point(magnitude: 5)    // Custom init
    print(p2.x)  // 5
}
```

### Mutable Methods
```saw
struct Counter {
    value: Int
}

extension Counter {
    func increment(&var self) {
        self.value = self.value + 1
    }

    func getValue(&self) -> Int {
        self.value
    }
}

func main() {
    var counter = Counter(value: 0)
    counter.increment()
    print(counter.getValue())  // 1
}
```

### While Loops
```saw
func main() {
    // Conditional while loop
    var count = 0
    while count < 5 {
        print(count)
        count = count + 1
    }

    // Infinite loop with break
    var n = 0
    while {
        n = n + 1
        if n > 3 {
            break
        }
    }

    // Skip iterations with continue
    var i = 0
    while i < 10 {
        i = i + 1
        if i == 5 {
            continue  // Skip printing 5
        }
        print(i)
    }
}
```

### For Loops
```saw
func main() {
    // Iterate over a range
    for i in 0..5 {
        print(i)  // 0, 1, 2, 3, 4
    }

    // Break out of loop
    for i in 0..10 {
        if i == 3 {
            break
        }
        print(i)  // 0, 1, 2
    }

    // For loop as expression with break value
    let found = for i in 0..10 {
        if i > 5 {
            break i  // Returns Some(6)
        }
    }  // Returns None if loop completes normally

    if let value = found {
        print(value)  // 6
    }
}
```

### Generic Functions
```saw
// Generic identity function
func identity<T>(x: T) -> T {
    x
}

// Generic function with multiple type parameters
func first<A, B>(a: A, b: B) -> A {
    a
}

func main() {
    let x = identity<Int>(42)     // Returns 42
    let y = identity<Bool>(true)  // Returns true
    let z = first<Int, Bool>(10, false)  // Returns 10
    print(x)
}
```

### Traits
```saw
trait Describable {
    func describe(&self) -> Int
}

struct Point {
    x: Int
    y: Int
}

extension Point: Describable {
    func describe(&self) -> Int {
        self.x + self.y
    }
}

func main() {
    let p = Point(x: 3, y: 4)
    print(p.describe())  // 7
}
```

### Generic Enums
```saw
// Generic enum - similar to Option<T> in Rust
// Note: 'None' is a keyword in Saw, so we use Maybe instead of Option
enum Maybe<T> {
    case Just(value: T),
    case Nothing
}

func main() {
    // Create Maybe<Int> values
    let some_int = Maybe<Int>.Just(value: 42)
    let none_int = Maybe<Int>.Nothing

    // Match on Just variant
    match some_int {
        case Just(n) -> print(n),      // 42
        case Nothing -> print(0)
    }

    // Match on Nothing variant
    match none_int {
        case Just(n) -> print(n),
        case Nothing -> print(999)     // 999
    }

    // Works with any type
    let some_bool = Maybe<Bool>.Just(value: true)
    match some_bool {
        case Just(b) -> {
            if b {
                print(1)               // 1
            } else {
                print(0)
            }
        },
        case Nothing -> print(-1)
    }
}
```

### Logical Operators and Modulo
```saw
func main() {
    // Logical operators (short-circuit evaluation)
    let a = true && false   // false
    let b = true || false   // true
    let c = not true        // false

    // Combining with comparisons
    let x = 10
    let y = 20
    if x < y && y > 15 {
        print("both conditions true")
    }

    // Modulo operator
    print(10 % 3)           // 1
    print(17 % 5)           // 2

    // Even/odd check
    if x % 2 == 0 {
        print("x is even")
    }
}
```

### Arrays
```saw
func main() {
    // Array literal
    let arr = [1, 2, 3, 4, 5]

    // Array indexing
    print(arr[0])       // 1
    print(arr[2])       // 3

    // Dynamic indexing
    let i = 3
    print(arr[i])       // 4

    // Tuples also support [index] syntax
    let tuple = (10, 20, 30)
    print(tuple[0])     // 10 (same as tuple.0)
    print(tuple[1])     // 20

    // Array in loop
    var sum = 0
    for j in 0..5 {
        sum = sum + arr[j]
    }
    print(sum)          // 15
}
```

### While as Expression
```saw
func main() {
    // Infinite loop as expression - returns Int
    var counter = 0
    let result = while {
        counter = counter + 1
        if counter == 5 {
            break counter  // Exit and return value
        }
    }
    print(result)  // 5

    // Conditional loop as expression - returns Int?
    var i = 0
    let found = while i < 10 {
        if i == 3 {
            break i  // Return Some(3)
        }
        i = i + 1
    }  // Returns None if loop exits naturally

    // Unwrap with if let
    if let value = found {
        print(value)  // 3
    }

    // Or use nil coalescing
    let result = found ?? 0
    print(result)
}
```

### Result and Error Handling
```saw
struct ParseError {
    code: Int
}

// Functions returning Result get auto-wrap
func parseNumber(valid: Bool) -> Result<Int, ParseError> {
    if valid {
        return 42                    // Auto-wrapped to Ok
    }
    return ParseError(code: 1)       // Auto-wrapped to Err
}

func main() {
    // try! - force unwrap (panics on Err)
    let n = try! parseNumber(true)
    print(n)  // 42

    // try? - convert to Optional
    let maybe = try? parseNumber(false)
    if let value = maybe {
        print(value)
    } else {
        print(0)  // Prints 0 since parseNumber failed
    }

    // Inline catch with fallback
    let value = try parseNumber(false) catch { 99 }
    print(value)  // 99

    // Block try-catch
    try {
        let x = try parseNumber(false)
        print(x)
    } catch {
        print(error.code)  // 1
    }

    // Match on Result directly
    match parseNumber(true) {
        case Ok(n) -> print(n),
        case Err(e) -> print(e.code)
    }
}
```

### Multiple Error Types in Catch
```saw
struct ParseError { code: Int }
struct IoError { status: Int }

func parse(valid: Bool) -> Result<Int, ParseError> {
    if valid { return 42 }
    return ParseError(code: 1)
}

func read(exists: Bool) -> Result<Int, IoError> {
    if exists { return 100 }
    return IoError(status: 404)
}

func main() {
    // Multiple error types auto-wrapped in union
    try {
        let a = try parse(false)
        let b = try read(true)
        print(a + b)
    } catch {
        match error {
            case ParseError(e) -> print(e.code),
            case IoError(e) -> print(e.status)
        }
    }
}
```

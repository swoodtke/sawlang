# Hazards: what the frozen compiler gets wrong

The Python compiler (`sawc/*.py`) is frozen, and its bugs stay. Bootstrap
Stage 0 is that compiler building the new compiler's source, which is written
in the conservative subset of architecture §4: sync code only, no closure
captures, arena indices instead of references, plain structs, enums, generics,
`Vector`, `Map`, `String`, `Optional`, `Result`, `match` and `try`, explicit
methods instead of inline place writes, no `borrow` and no `@test`. This ledger
lists every shape the frozen compiler mishandles that such source could hit.

How the ledger is used:

- **Authors** of the compiler source avoid every shape here and write the
  entry's **Instead** spelling.
- **The subset checker**, a battery lane over the compiler source, refuses each
  shape whose **Checker** line says `yes`.
- **What remains is a trust obligation, not a guarantee** (codex t1). Entries
  whose Checker line says `no`, or covers the shape only in part, are the
  obligations authors and reviewers carry by hand. Stage 1 recompiling the
  source, the tests and the bootstrap fixpoint are evidence, not proof. The
  Stage 1 executable is itself built by Stage 0, so a silent miscompile can
  corrupt the very compiler that would catch it. A shape that cannot be checked
  and is easy to avoid is excluded from the subset outright (SL:architecture
  §4's blanket rules).
- **Differential testing** uses it as the index of places the frozen compiler
  is a known-wrong oracle, but a hazard shape in a case is not an exemption
  (codex t2). When the new compiler disagrees with the frozen one, adjudicate
  that specific mismatch: check the EXPECT directives and the spec, and
  establish that the mismatch is the cited issue's failure. Only then annotate
  it `oracle known wrong: SL-N`. The annotation records why the frozen result
  is not authoritative for that mismatch. The new compiler is still checked
  against the intended result, and any other mismatch in the same case is
  judged on its own.

**Silent** means Stage 0 accepts the code and does the wrong thing: a
miscompile, a leak, a double free, a wrong type, a truncation, or a missing
check (code Stage 0 accepts and Stage 1 refuses). **Loud** means Stage 0
refuses valid code or crashes, so the build fails visibly and the entry mainly
gives the spelling that works.

Issues that share one mechanism, or one rule that avoids them, form one entry.
A family with any silent member is listed under silent hazards, and each issue
in it is tagged. Entry codes (S1, L1, C1) are what the inventory maps to.

Sources: the Sep 25 tracker sweep (SL:tracker-cleanup, which closed most of
these issues as `frozen`), the issue text, and the Sep 1 parser census
(`designs/reviews/parser-census-sep1.md`). Nothing was compiled for this
ledger; the issues' repros are the evidence. Main is at 2fa71814.

## Silent hazards

### S1. `init` in a generic extension (SL-80, SL-31, SL-32)

**Shape:**
- **SL-80** (silent, double free): an `init` declared in a generic extension
  that moves an owning parameter into the value it builds also releases that
  parameter when the `init` returns. The caller reads freed storage and
  releases it again. Pinned by
  `examples/generic_init_moved_parameter_is_released_once.saw` (XFAIL).
- **SL-31** (fixed on main): the leak of an un-moved owning parameter in the
  same generator was fixed on Sep 2 by 218c stage 3 (178e6522), and its XFAIL
  flipped. The tracker issue is stale.
- **SL-32** (loud): an extension that renames the struct's type parameters
  (`extension Pair<U>` over `struct Pair<A>`) and declares an `init` is
  refused at the construction site: ``parameter `three` expects type `U` but
  got `Int` ``.

**Example (SL-80):**
```saw
struct Wrap<T> { value: T }
extension Wrap<T> { init(from: T) -> Wrap<T> { Wrap<T>(value: from) } }
// Wrap<Res>(from: move r): `Res`'s deinit runs inside init, then again at scope end
```

**Instead:** declare no `init` inside a generic extension. Build generic
structs memberwise at the call site with inferred type arguments,
`Wrap(value: move r)`, which drops once (see S13 for why the arguments should
be inferred).

**Checker:** yes: refuse an `init` inside any `extension` whose header has type
parameters.

### S2. Moving or re-matching a payload of a borrowed match (SL-192)

**Shape:** a `match` whose scrutinee is reached through a reference (a
`&`/`&var` parameter, `self`, or a field of either) binds a move-only payload.
Two spellings then drop that payload twice: `move` of the arm binding, and a
nested `match` on the arm binding, even with no `move` written. The second is
the common one: `match r.what { case Reply(outcome) -> match outcome { … } }`.
The ruled behavior is a refusal.

**Example:**
```saw
func take_it(s: &var Slot) -> Owned {
    match s {
        case Empty -> { Owned(w: 0) },
        case Full(o) -> { move o },   // `s` still owns `o`: dropped again later
    }
}
```

**Instead:** when the scrutinee is borrowed, pass an arm binding onward by `&`,
or call a `&self` method on it. Never `move` it and never make it the scrutinee
of another `match`. Where a nested read is needed, give the inner type a `&self`
accessor. To move a payload out, match an owned value: a local, or a by-value
parameter.

**Checker:** yes. The borrowed-versus-owned distinction is visible in the
syntax, so the rule and the recipe above agree (codex t5):
- **An owned scrutinee** is a plain name bound in the function by `let` or
  `var`, a by-value parameter (its declared type is not `&T` or `&var T`), or
  `move` of either. `self` is never one, not even in a `consumes` method: the
  spec keeps a consuming receiver borrowed for `match`, and its one exception
  is `move self.<field>` (codex t5). Saw has no
  reference-typed locals outside `borrow` bindings, which the subset excludes.
  `move` of an arm binding is allowed here.
- **Anything else is treated as borrowed:** a reference parameter, `self` in
  any method, a field path, an index, or a call. `move` of
  an arm binding is refused there, as is a `match` whose scrutinee is an
  enclosing arm's binding.

### S3. Owned values around `try` and `catch` (SL-240, SL-348, SL-74)

**Shape:**
- **SL-240** (silent, leak): a statement-position `try f() catch { fallback }`
  whose value has an owning type is never dropped. The bound form,
  `let kept = try f() catch { … }`, drops correctly, and so does the block form
  `try { … } catch { … }` on both paths (Air, SL-399 r3 review, probes q2 and
  q2b).
- **SL-348** (silent, leak): a by-value `move` operand evaluated before a
  propagating `try` that fails in the same expression is released by nothing.
  The same leak happens in every position where a moved value precedes the
  `try`:
  - an earlier argument or a consumed receiver;
  - an earlier tuple, array or struct-literal element;
  - an earlier Map-literal key or value;
  - an earlier interpolation segment;
  - a `move` between two `try`s;
  - the condition of a `while` as well as the heads of `if`, `match` and `for`.

  An owned temporary with no `move` written leaks the same way. That covers a
  call's result, a struct literal, and an interpolated string passed as an
  argument (SL-399 r3 review, probes b04b, b04c, b04d and q1).
- **SL-74** (loud): a `move` inside a `catch` block that diverges (`return`,
  `panic`) still retires the binding on the fall-through path, so the next use
  is refused. All three `catch` forms do this.

**Example (SL-348):**
```saw
var r = Res(name: "kept")
let n = sink_rev(move r, try fail())   // fail() errors: `r` is never dropped
```

**Instead:** bind every `try … catch` value to a named local. Hoist each `try`
into its own `let` before any expression that moves a value *or builds an owned
temporary*, such as a call's result passed as an argument:
`let k = try fail()`, then `sink_rev(move r, k)`; and
`let k = try fail_it()`, then `sink2(make_res("fresh"), k)` (Air t10). When an error path must
consume a local, `match` on the `Result` instead of writing `move` in a
`catch`.

**Checker:** yes: refuse an expression statement that is a `try … catch`, an
expression that contains both `move` and `try`, and `move` inside a `catch`
block. Also refuse an owned temporary evaluated before a `try` in the same
expression, in every position the Shape lists. A temporary is a call's
result, a struct literal or an interpolated string. It leaks the same way with
no `move` written: `sink2(make_res("fresh"), try fail_it())` never drops the
fresh value (Air, SL-399 review, probe p24). An operand that owns nothing,
such as a Copy struct literal or an `Int` result, is not a temporary here.

### S4. Whole-call exclusivity (SL-284, SL-294, SL-111)

**Shape:**
- **SL-284** (silent, missing check): a nested call that implicitly borrows
  the outer call's receiver is accepted, as in `c.write(c.read())` and
  `b.append(b.build())`. Stage 1 refuses it.
- **SL-294** (silent, missing check): a later value argument that reads or
  writes a root that an earlier `&`/`&var` argument borrows is accepted, as in
  `consume(&var value, value)`. Stage 1 refuses it.
- **SL-111** (loud): an index write whose right side reads the same root,
  `v[i] = v[i] * k` or `self.cells[i] = self.cells[i] * by`, gets a wrong
  error or an ICE.

**Example (SL-284):**
```saw
var c = Counter(n: 7)
c.write(c.read())   // accepted; the new compiler refuses it
```

**Instead:** evaluate any operand that touches a root the call or the write
already borrows into a `let` first: `let r = c.read()`, then `c.write(r)`. For
read-modify-write of one element, use `v[i] *= k`, or compute into a local and
write it back.

**Checker:** yes, by root name: refuse a call whose receiver root or
`&`/`&var` argument root appears in another argument, and a plain assignment
whose target root appears on its right side. This also refuses disjoint
fields, which costs little.

### S5. `&var` into a `let` binding (SL-130)

**Shape:**
- **The `let` face:** `&var` into a field, tuple element or fixed-array element
  whose root is a `let` binding compiles, and writes through the `let`. The
  direct write `p.a = 2` is refused, so only the reference form slips through.
  Stage 1 refuses it.
- **The qualified-static face:** `&var` into an immutable `static` reached
  through a module qualifier compiles, and the write is silently lost:
  `bump_int(&var limits_mod.LIMIT_VALUE)` leaves the value at 3 (SL-399 r3
  review, probe b14; reproduced on main 2fa71814). The unqualified form is
  refused.

**Example:**
```saw
func bump(x: &var Int) { x = x + 1 }
let p = Pair(a: 1, b: 2)
bump(&var p.a)   // accepted; p.a is now 2
```

**Instead:** declare the root `var` whenever any `&var` reaches into it. Never
take `&var` into a `static`; copy it into a local `var`.

**Checker:** yes: resolve the root name to its declaration, through any module
qualifier, and refuse `&var` into a `let` or an immutable `static`.

### S6. Function exits (SL-298, SL-295)

**Shape:**
- **SL-298** (silent): a value-returning function with a reachable path that
  falls off the end compiles, and that path returns a fabricated zero. One
  `return` anywhere suppresses the missing-return check. Stage 1 refuses it.
- **SL-295** (loud): statements after an unconditional `return` make the
  function's result `Void`, so a valid function is refused.

**Example (SL-298):**
```saw
func f(x: Int32) -> Int32 { if x > 0 { return x } }   // f(0) returns 0
```

**Instead:** end every value-returning function with a tail expression, or
with an `if`/`match` whose every branch returns. Put nothing after an
unconditional `return`, `break` or `continue`.

**Checker:** yes, structurally: a non-`Void` function body ends in an
expression, a `return` or `panic`, or a branch construct whose every arm does;
no statement follows an unconditional `return`/`break`/`continue` in its block.

### S7. Integer literal above `Int.max` (SL-299)

**Shape:** an integer literal with no type context whose value is outside
platform `Int`'s range compiles and wraps instead of being refused.

**Example:**
```saw
func main() { print(18446744073709551615) }   // prints -1
```

**Instead:** write large constants with a suffix, `14695981039346656037u64`,
or bind them to a `UInt64`-typed `let` or `static`.

**Checker:** yes: refuse an unsuffixed integer literal whose magnitude exceeds
`Int.max`.

### S8. Enum `==` with a hand-written `equals` (SL-61)

**Shape:** `==` on an enum ignores a hand-written `Equatable.equals` and
compares payloads structurally, so `a == b` and `a.equals(&b)` can disagree.
The struct arm calls `equals` correctly.

**Example:**
```saw
enum Bag { case Empty, case Full(k: Vector<Int>) }
extension Bag: Equatable { func equals(&self, other: &Self) -> Bool { self.size() == other.size() } }
// a = Full([1, 2]); b = a.copy(); a == b is false, a.equals(&b) is true
```

**Instead:** don't hand-write `Equatable` on an enum. Use
`@synthesize extension E: Equatable {}` for structural equality, and write any
other comparison as an ordinary method with its own name (`same_kind(&other)`).

**Checker:** yes: refuse an `extension X: Equatable` with a body when `X` is
declared as an `enum` in the source.

### S9. Type aliases (SL-49, SL-50, SL-52, SL-77, SL-383, SL-384)

**Shape:** several mechanisms, one avoidance rule.
- **SL-49** (silent at a `let`, ICE elsewhere): `G<Alias>` where
  `G<Underlying>` is expected. With `type TokenKind = UInt8`, a
  `Vector<TokenKind>` at a `Vector<UInt8>` parameter, return or field is an
  ICE, and the `let` form is accepted where the intended rule refuses it. This
  holds for every generic, not just `Vector`.
- **SL-50** (silent; ICE through `any Trait`): a conformance method whose
  signature spells the underlying type where the trait requirement names the
  alias is accepted.
- **SL-52** (loud): an alias over a primitive fails a trait bound at a free
  generic call, `rank<T: Comparable>(Handle(1), Handle(2))`, though it passes
  through a receiver's type argument (`Vector<Handle>.sort()`). The suggested
  `extension Handle: Comparable` is then refused by the orphan rule.
- **SL-77** (loud): a `type` alias is unbound through `import m.*`, and
  `m.Alias` resolves to a name-only type unequal to the alias. Only
  `import m.{Alias}` binds it.
- **SL-383** and **SL-384** (loud in every probed cell): for a distinct alias
  over a struct, member access and enum-payload bindings are typed `Void`, so
  the program is refused with a misleading error (`undefined variable n`,
  "body has no value"). A discarded statement-position call through such an
  alias is unprobed and could be silent.

**Example (SL-384):**
```saw
struct Noisy { name: String }
type Tag = Noisy
let t = Tag(Noisy(name: "four"))
let n = t.name.len()   // typed Void, so `n` is then undefined
```

**Instead:** declare no `type` aliases in the compiler source. Use plain `Int`
arena indices, or a one-field struct (`struct ExprId { index: Int }`) when a
distinct id type is wanted. SL-340's alias face is in S11.

**Checker:** yes: refuse every `type` alias declaration.

### S10. Nested optionals (SL-264, SL-290)

**Shape:**
- **SL-264** (silent): a bare `None` arm of a value `if`/`match` at an
  annotated, non-tail `T??` destination produces `Some(None)`, not `None`.
  Tails distribute the wrap correctly; `let`, assignment, argument and field
  positions do not.
- **SL-290** (loud, ICE): a `T?` argument to a `T??` parameter, or
  `let x: T?? = inner`, reaches codegen with mismatched layouts.

**Example (SL-264):**
```saw
let inner: Int? = None
let x: Int?? = if false { inner } else { None }   // x is Some(None)
```

**Instead:** use no nested optionals: no `T??` or `Optional<T?>`, and no
optional element or value types in collections whose accessors return an
optional (`Vector<T?>`, `Map<K, V?>`). Use an enum with named cases for a
three-state value.

**Checker:** yes for written types: refuse `?` applied to an optional type and
an optional type argument to `Vector`, `Map` or `Set`. A nested optional that
arises only inside a generic instantiation needs types.

### S11. Owning payloads in cells (SL-340)

**Shape:**
- `Mutex(value:)` and `SpinLock(value:)` over a heap-owning payload free it at
  construction, a use-after-free. The `UnsafeMutableInterior(value)` inside
  the `init` does not retire the parameter, so the parameter's cleanup runs.
- A cell or distinct-alias value over an owning type never drops its payload,
  a leak.
- `UnsafeMutableInterior(x)` or `Alias(x)` of a NoCopy or ExplicitCopy value is
  accepted without `move`.

The two halves hide each other today. Pinned by
`examples/conformance/K141_mutex_guarded_for_is_sync.saw` (XFAIL).

**Example:**
```saw
var v: Vector<Int> = [1, 2, 3]
let guarded = Mutex(value: move v)   // v's buffer is freed here
```

**Instead:** the sync compiler needs no cells. Use no `Mutex`, `SpinLock`,
`Once` or `UnsafeMutableInterior`, and no `type` aliases (S9).

**Checker:** yes: refuse those type names.

### S12. Consuming an erased box through a projection (SL-288)

**Shape:** `take<T>()` on a `Box<any Trait>` reached through a field, tuple
element or array element frees the box shell inside the call, and the
container frees it again at scope exit. `move w.b` is refused, but
`w.b.take<Res>()`, which consumes the same field, is accepted.

**Example:**
```saw
struct W { b: Box<any Shape> }
w.b.take<Res>()   // "gone 42", then a second deinit reads freed memory
```

**Instead:** keep `any Trait` out of the compiler source and dispatch over an
enum. If an erased box is ever needed, bind it to a local and call `take` on
the local.

**Checker:** yes: refuse `any` in type position.

### S13. Nested generics with defaulted parameters (SL-382)

**Shape:** a type that nests a generic with a defaulted parameter is mangled
without the default (`Vector`'s allocator), so the deinit lookup misses and the
contents never drop. The same mangling feeds retain, copy and static lookups.
It has two faces:
- **Construction:** `Plain<Vector<Noisy>>(v: move v)`, with the nested type
  argument written explicitly. The inferred `Plain(v: move v)` drops correctly.
- **Fields, the likelier face** (Air t6, probed against the frozen compiler).
  A *field* whose type nests such a generic never drops its contents, however
  the value was built: `struct Outer { p: Plain<Vector<Noisy>> }`,
  `vv: Vector<Vector<Rec>>`, `m: Map<String, Vector<Rec>>`. These are the
  ordinary shapes of symbol tables and per-scope lists. The controls drop
  exactly once:
  - a field one generic deep (`v: Vector<Noisy>`);
  - a nested generic with nothing defaulted (`p: Plain<Noisy>`);
  - the default written out (`Plain<Vector<Noisy, GlobalAllocator>>`);
  - the same nested types as locals, parameters or return types.

  Deriving copy over such a field is loud:
  ``internal compiler error: no `copy` symbol for field `vv` of type `Vector<Vector<Rec>>` ``.
  With the default written out, the derived copy is deep and both copies drop.

**Example:**
```saw
struct Scopes { names: Vector<Vector<Name>> }   // the inner vectors never drop: a leak
struct Scopes { names: Vector<Vector<Name, GlobalAllocator>> }   // drops once
```

**Instead:**
- Let construction type arguments be inferred.
- In a field type that nests a generic, write every defaulted type argument
  (`Vector<Vector<Rec, GlobalAllocator>>`). Better still, keep fields one
  generic deep, with arena indices into a flat `Vector`, which is the subset's
  layout anyway.

**Checker:** yes, syntactically:
- refuse an explicit type-argument list on a construction expression when one
  of the arguments is itself generic;
- refuse a field type in which a generic with defaulted parameters (`Vector`,
  `Map`, `Set`, `Box`) appears as a type argument without those arguments
  written.

L15's ICE text matches the copy face here, so L15 (SL-389) may be a second
trigger of the same missing-symbol path. Check that once before trusting L15's
candidate shape.

### S14. Argument labels the frozen compiler does not check (SL-285, SL-297)

**Shape:**
- **SL-285** (silent, missing check): a named `borrows` accessor drops
  argument labels before checking them, so `v.get(value: 0)` compiles though
  the parameter is `index:`. This affects every such accessor. Stage 1 refuses
  it.
- **SL-297** (silent): a repeated named constructor argument,
  `Pair(first: 1, second: 2, first: 3)`, is accepted and one value is dropped.

**Instead:** call `get` and the other std accessors positionally (`v.get(i)`)
or with the declared label. Never repeat a label in one argument list.

**Checker:** yes: refuse a repeated label in one argument list, and labeled
arguments to the std `borrows` accessors (a list read from `sawc/std/`).

### S15. Methods called on an indexed element (SL-368)

**Shape:** a method called directly on a pointer-index receiver,
`p[0].store(5)`, runs on a spilled copy, so a write through an `Atomic` or any
cell is lost. These receivers are unswept: `&var self` methods on `p[i]`, and
both receiver kinds on `v[i]`, `Data` places, tuple indexes and `borrows`
places. Architecture §4 names this as a checker shape. Stage 0 evidence for the
optional-chain receivers (Air, SL-399 review): `v.get(0)?.bump()` and
`m["a"]?.bump()` silently lose the write (probes p05b and p08), while the
refused `!` form works.

**Example:**
```saw
p[0].store(5)
print(p[0].load())   // prints 0, not 5
```

**Instead:** use no `UnsafePointer`, `Atomic` or cells in the compiler source.
Call mutating methods only on a named local or a field path, never directly on
`x[i]`. The recipe for changing an element depends on its copy tier (codex t4):
- **A Copy element:** read it into a local, change the local, and write it back
  with `v[i] = e`.
- **A move-only element** (ExplicitCopy or NoCopy, such as a nested `Vector`)
  cannot be read out that way, and moving out of `v[i]` is refused (spec:
  moving out of a place). Prefer the subset's arena layout, where mutated
  elements are Copy-tier records addressed by index. Where a nested owner is
  unavoidable, exchange it out with `v.swap_out(i, move placeholder)` (or a
  fresh construction in place of the named placeholder), change it, and put it
  back with `v.swap_out(i, move changed)`, discarding the placeholder that comes
  back. Every transfer of an owned move-only value is a spelled `move`.

**Checker:** yes: refuse a method call whose receiver is an index expression,
with an allowlist of known read-only methods.

### S16. Generic bodies returning a type parameter (SL-156)

**Shape:** in a generic body whose return type is a type parameter or an
associated type, the returned value is not checked against that type. A
mistyped return compiles at Stage 0.

**Instead:** no different spelling. Don't count a clean Stage 0 build as type
checking for these bodies; Stage 1 checks generic bodies fully and reports the
mismatch.

**Checker:** no: needs types.

### S17. `?` or `??` after a cast target (SL-309)

**Shape:** after `as T`, a following `?` or `??` is read according to
whitespace, because `??` lexes as one token. `n as Int? ?? 9` targets `Int?`,
`n as Int?? 9` targets `Int` and then coalesces, and `n as Int? ?` targets
`Int??`. The ruled grammar refuses all of them. The parse is silent; every
probed cell then fails type checking, because a cast never produces an
optional.

**Instead:** coalesce first, then convert: `(n ?? 9) as Int`. Never write `?`
or `??` directly after a cast target.

**Checker:** yes: refuse a `?` or `??` token directly after the type of an
`as` cast.

### S18. Names the frozen compiler shares program-wide (SL-319, SL-132, SL-195)

**Shape:** the language gives each declaration its module's identity; the
frozen compiler keeps some names in one program-wide table.
- **SL-319** (silent or loud): a qualified call `mine.encode(1)` into a user
  module can resolve to a std free function of the same name when that std
  module is compiled in. In the repro it is refused with an error about the
  std function. When the std signature fits, the wrong function would run.
- **SL-132** (loud): a free function named like a private std free function
  (`tcp_socketpair`, `unix_timestamp`) is refused as a duplicate, and
  redefining one of `__saw_exec_*` is an ICE.
- **SL-195** (loud): two modules that each declare a `static` of the same name
  collide even if neither is used, with the error anchored at line 1 of the
  entry file.

**Example (SL-319):**
```saw
import std.json.{JsonEncoder}
module mine { public func encode(n: Int) -> Int { n + 100 } }
func main() { print(mine.encode(1)) }   // resolves to std.json's encode<T>
```

**Instead:** give every free function and every `static` in the compiler
source a name that is unique across the whole build, std included. Prefix
module-local helpers with the module's name (`lex_`, `parse_`).

**Checker:** yes: collect free-function and `static` names across the
compiler source and `sawc/std/`, and refuse duplicates.

### S19. Type walks bounded by a depth count (SL-390)

**Shape:** several of the frozen compiler's type walks stop at a fixed depth
instead of detecting cycles, so a written type nested past the bound skips the
rule the walk enforces (SL-390 c1, Air t7). The members the subset can reach:
- **Silent:** a reference nested 13 or more levels deep in a field's type
  escapes the no-reference-field refusal (SL-390 itself).
- **Silent:** a private type nested 9 deep in a public signature compiles, so
  the visibility rule is skipped (`sigvis._check_signature_type`, bound 8).
- **Silent:** a `Result` discarded through 33 forwarding `match`/`if` levels
  compiles, so design 151 is skipped (`statements._result_discard_culprits`,
  bound 32).
- **Silent:** the no-move-type test gives up past 13 wraps
  (`types._is_no_move_type`, bound 12).
- **Loud:** `struct R { x: Optional<Int> }` is an ICE ("Unknown generic struct:
  Optional").
- **Loud:** `(Self, Int)` in a trait signature is an ICE, because
  `_names_self` skips tuple elements.
- **Loud:** 63 nested `as` casts are a RecursionError (see L14).

**Instead:** keep every written type under 8 levels of nesting, the lowest
silent bound. Use no alias chains (S9 bans aliases outright). Write `T?`, never
`Optional<T>`, in type position. Put no `Self` inside a tuple type.

**Checker:** yes: the syntactic nesting depth of every written type (as L14
measures blocks), `Optional<` in a type, and `Self` inside a tuple type.

### S20. Float literals out of range (SL-68)

**Shape:** an unrepresentable float literal silently becomes `inf` or `0.0`.
It is S7's float twin (Air t8).

**Instead:** the compiler source needs no float literals, so the subset has
none. If one is ever needed, keep it well inside `Float`'s range.

**Checker:** yes: refuse a float literal token in the compiler source.

### S21. A line break inside an interpolation (SL-401)

**Shape:** when a line break falls inside an interpolation's braces, outside
any brackets, Stage 0 evaluates only the segment's first line and drops the
rest. Nothing is reported. This is the "keeps the first token and drops the
rest" defect of SL:grammar §16, reached through a line break. With `x = 7`:
- `"plus {x⏎ + 3}"` prints `plus 7`;
- `"and {x > 0⏎ && x > 9}"` prints `and true`;
- `"eq {x⏎ == 8}"` prints `eq 7`;
- `"len {s⏎ .len()}"` prints `len abc`.

A `-` or `*` on the next line is refused in some positions. Parenthesizing
the segment gives the right answer (Air, SL-399 r3 review, probes b10, b10c and
q3; reproduced on main 2fa71814).

**Example:**
```saw
let x = 7
print("and {x > 0
    && x > 9}")   // prints `and true`
```

**Instead:** keep each interpolation on one line: a name, a field or a simple
call, as C3 advises. Compute anything longer into a `let` first.

**Checker:** yes: refuse any line break inside an interpolation's braces.

## Loud hazards

### L1. Integer literal adoption (SL-13, SL-53, SL-56, SL-70, SL-75, SL-84, SL-194)

**Shape:** a bare integer literal is meant to adopt a non-`Int` integer type
wherever one is expected. The frozen compiler misses these positions, and
refuses the code in each:
- **SL-75**: at a call with two or more overloads, the matcher types a bare
  literal as `Int` before adoption runs, so `b.put(len: 1)` is refused at a
  `UInt` parameter even when every candidate agrees on the type.
- **SL-56**: a label-selected overload, `report(byte: 65)` against
  `report(value: Int)` and `report(byte: UInt8)`.
- **SL-13**: even a suffixed literal ties an overload set that differs only in
  `Int` versus a narrow type: `pick(200u8)` against `pick(n: Int)` and
  `pick(b: UInt8)` is ambiguous.
- **SL-53**: the synthesized `E.from(raw:)`: `Tag.from(raw: 9)` is refused
  against a `UInt8` backing.
- **SL-194**: a platform `UInt` parameter (`arg: 0`) and a `UInt`-backed
  `from(raw: 0)`. Every fixed width adopts.
- **SL-70**: a value `if`/`match` of bare literals beside a typed operand:
  `wide + (if up { 1 } else { 0 })` with `wide: UInt64`.
- **SL-84**: an annotation on the binding does not reach value-`match` arms:
  `let ra: UInt = match r { case Ok(v) -> v, case Err(_) -> 0 }`.

**Instead:** don't overload a name on integer width, and don't overload at all
where an overload takes a non-`Int` integer parameter. Where a non-`Int`
integer is expected at a call, `from(raw:)` or a branch arm, write a typed
value: a suffixed literal (`9u8`, `0u64`), `0 as UInt` (there is no platform
`UInt` suffix), or a named `static`.

**Checker:** yes for overload sets and for `from(raw:)` with a bare literal,
both syntactic; a bare literal at a single `UInt` parameter or in a branch arm
needs the expected type.

### L2. Closure literals and call syntax (SL-7, SL-38, SL-41, SL-65, SL-73, SL-293, SL-310, SL-352)

**Shape:** closures without captures are in the subset. The frozen compiler
refuses these spellings:
- **SL-7**: a closure literal bound to a `let` annotated with a function type
  does not infer its parameter types, then reports a mismatch against an `Int`
  fallback.
- **SL-65**: a closure literal as an enum-variant payload does not infer its
  parameter types; the struct-field twin does.
- **SL-293**: a closure literal at an optional function-typed slot is refused,
  and a closure read out of an optional cannot be called.
- **SL-38**: `$0` inside a `try`/`try!`/`try?` operand is not counted, so the
  closure gets no parameters. Pinned by
  `examples/closure_shorthand_parameter_inside_a_try.saw` (XFAIL).
- **SL-41**: a trailing closure inside a `try` operand, `try! v.map { … }`,
  parses as a field access. Pinned by
  `examples/trailing_closure_inside_a_try_operand.saw` (XFAIL).
- **SL-310**: a bare trailing closure on a free function, `run { 10 }`, reports
  `undefined variable run`.
- **SL-352** and **SL-73**: a call whose callee is not a name or a member, as
  in `{ n in n + 1 }(2) + 1`, `foo()(1)`, `(f)(1)` or `v[i](x)`, is refused
  because the parser has no call node for such a callee. The general postfix
  call is ruled into the language (SL-73).

**Example (SL-7):**
```saw
let sink: (Owned) sync -> Void = { o in print("{}", o.w) }
// error: Cannot infer type for closure parameter 'o'
```

**Instead:** give every closure literal named, annotated parameters
(`{ o: Owned in … }`) and never use `$0`. Pass closures inside the argument
parentheses, never as trailing closures. Keep function values out of optional
and enum-payload slots. Bind a function value to a local and call it by name.

**Checker:** yes: refuse unannotated closure parameters, `$0`, trailing-closure
syntax, a function type under `?`, and a call whose callee is not a name or a
member.

### L3. Module-qualified spellings and cross-module defaults (SL-14, SL-36, SL-78, SL-115, SL-125, SL-199, SL-358)

**Shape:** design 150 says a qualifier works wherever a name appears. The
frozen compiler misses several positions:
- **SL-36**: `lib.Plain()` ignores defaulted `init` parameters, while the bare
  `Plain()` honors them.
- **SL-78**: `mutex.Mutex<Int>(value: 5)` drops its explicit type argument.
- **SL-358** (ICE): a qualified const-generic construction with no expected
  type, `var fb = fixedbuf.FixedStringBuilder<32>()`.
- **SL-14**: a `FuncPointer` built from a qualified name, `fpmod.tripled`, is
  refused (DF-226c).
- **SL-199**: a qualified name in a trait-conformance header or a
  receiver-type position gets a wrong error. Six positions parse qualified
  names outside `parse_type`.
- **SL-125**: under a whole-module `import m`, a bare `Point` half-resolves,
  giving ``cannot assign `Point` to variable of type `Point` `` where the
  program should get a clean out-of-scope error.
- **SL-115**: a default parameter value that names a module-level `static`
  fails when called from another module, and the error points at an unrelated
  line of the caller.

**Example (SL-78):**
```saw
import std.mutex.{Mutex}
import std.mutex
let sel  = Mutex<Int>(value: 5)         // compiles
let qual = mutex.Mutex<Int>(value: 5)   // argument `value` expects `T` but got `Int`
```

**Instead:** use only selective imports, `import m.{A, B}` (with `as` to
rename), and write imported names bare. Write default parameter values as
literals.

**Checker:** yes: refuse the `import m` and `import m.*` forms, and a default
parameter value that is not a literal.

### L4. Optional and Result shaping at typed destinations (SL-28, SL-42, SL-46, SL-291, SL-292)

**Shape:**
- **SL-28**: a collection literal returned, or used as a tail, where
  `Result<Vector<…>, E>` (or `Map`, `Set`) is expected is refused. The bare
  `-> Vector<Int>` twin compiles.
- **SL-291**: assigning a bare payload or error to a `Result`-typed local or
  `&var Result` is refused, as in `source = "changed"`.
- **SL-292**: an annotated `Result`-typed value `if`/`match` whose arms are a
  bare payload and a bare error is refused.
- **SL-42**: `f(x) == None` cannot infer what the `None` is against the call's
  optional; the annotated-local twin compiles.
- **SL-46**: an `Optional` method called directly on a `get` result,
  `v.get(0).is_some()`, resolves against the payload type. `Map.get` does the
  same.

**Example (SL-292):**
```saw
let chosen: Result<Int, String> = if ok { 9 } else { "no" }   // refused
```

**Instead:** bind a collection literal to an annotated local before returning
it. Construct Results explicitly in assignments and branch arms:
`Result<Int, String>.Ok(value: 9)`, `Result<Int, String>.Err(error: "no")`.
Test presence with `.is_none()`/`.is_some()` on a call result, except a `get`
result, since a method chained directly on `.get(…)` is SL-46's broken shape
(Air t9). Use `i >= 0 && i < v.len()` for a vector index (both bounds: `Vector.get` returns
`None` for a negative index, and `i < v.len()` alone is true for -1; codex t3),
and `m.contains_key(k)` for a map.

**Checker:** yes for SL-42 (`== None`), SL-46 (a method chained directly on
`.get(…)`) and SL-28 (a collection literal returned from a function declared
`-> Result<…>`). SL-291 and SL-292 need the destination type.

### L5. Zero-sized `Result` payloads (SL-85)

**Shape:** a `Result` whose Ok and Err payloads are both zero-sized is an ICE
at the Err wrap. The enum lowers to its tag alone, and the Err path indexes a
payload that does not exist.

**Example:**
```saw
struct Unreadable {}
func attempt() -> Result<Void, Unreadable> { return Unreadable() }   // ICE
```

**Instead:** give every error type at least one field.

**Checker:** yes: refuse a struct declared with no fields.

### L6. Copy tier and conditional conformance (SL-114, SL-270, SL-381)

**Shape:**
- **SL-270**: an automatically Copy-tier struct (one that owns a `String` and
  declares nothing) is refused as a `Set` element or `Map` key, though
  accepted as a `Map` value.
- **SL-381**: a bounded extension, `extension Box1<T: ExplicitCopy>`, is
  instantiated for a type argument that fails the bound (`Vector<NoCopyT>`),
  and the compile fails inside it. The likeliest face for compiler source is
  `Vector<Vector<T>>` with a move-only `T`: `Vector<Vector<T>>.copy` is
  instantiated although `T` fails `ExplicitCopy`, so it does not compile at
  all (Air t9, found by the S13 probe). `Mutex<Vector<Noisy>>` hits the same
  path through std.
- **SL-114** (fixed on main): an automatically Copy-tier struct failing a
  `T: Copy` bound was fixed by design 219 B2. Conformance row V32 pins it. The
  tracker issue is stale.

**Example (SL-270):**
```saw
struct Rec { text: String }
var s = Set<Rec>()         // refused: "it is move-only, not retainable"
var m = Map<Rec, Int>()    // refused
```

**Instead:** key `Map`s and `Set`s by `Int` or `String`. Declare no bounded
extensions on the compiler's own generic types, and don't instantiate a
generic that has one at a type argument that fails the bound.

**Checker:** yes for declarations (a bound on a type parameter in an
`extension` header); key types need types.

### L7. Fixed-size arrays (SL-131, SL-133, SL-191, SL-363)

**Shape:**
- **SL-191**: an indexed write through a `&var [T; N]` parameter, `a[0] = 9`,
  is refused, and the hint mentions a `let` that does not exist. The same
  write through a `&var` struct's array field works.
- **SL-133**: a repeat literal `[t; N]` whose element has a generic type is
  refused.
- **SL-363** (LLVM assertion): a constant repeat or fixed-array literal with
  more than 65535 leaves, such as `[0; 70_000]`.
- **SL-131** (likely fixed on main): `.copy()` of a fixed array, or a
  `T: Copy` bound, over an Optional or tuple with a refcounted payload is
  refused. `type_satisfies_copy_bound` in `sawc/namespace.py` now answers from
  the copy tier, which covers both; unprobed.

**Example (SL-191):**
```saw
func bump(a: &var [UInt8; 4]) {
    a[0] = 9   // error: cannot assign to element of immutable array `a`
}
```

**Instead:** prefer `Vector` to fixed-size arrays in the compiler source. If a
fixed array is used, keep it small and its element type concrete, and put it
inside a struct when a callee must write it.

**Checker:** yes: refuse `[T; N]` types and repeat literals, or at least the
four shapes above.

### L8. `Box`-linked types (SL-62, SL-63)

**Shape:**
- **SL-62**: `Box` method forwarding reaches a struct payload's methods but not
  an enum payload's, so a box-linked recursive enum cannot be traversed with
  methods: ``type `Box` has no method `rank` ``.
- **SL-63** (ICE): an optional chain through a `Box<T>?` field,
  `self.slot?.twice() ?? 0`, is ``BindOptional lowered outside an optional
  chain``.

**Instead:** link trees by arena index, as the subset already requires, and
declare no `Box` fields.

**Checker:** yes: refuse `Box<` in type position.

### L9. Name collisions within a program (SL-5, SL-96, SL-107)

**Shape:**
- **SL-5** (ICE): a generic method, instance or static, with the same name as
  a generic free function is never monomorphized: "monomorphization did not
  discover the instance".
- **SL-96**: a generic extension whose type parameter is spelled like an
  existing type (`extension Holder<Cmd>` beside `enum Cmd`) loses every
  method.
- **SL-107** (possibly fixed): a static and an instance method with one name on
  one type are refused as indistinguishable. The spec now allows the pair, and
  `examples/static_and_instance_method_share_a_name.saw` pins one, but its two
  methods also differ by label. The same-label shape (`Duration.secs(2)`
  beside `d.secs()`) is unprobed.

**Example (SL-5):**
```saw
func carry<T>(v: T) -> T { v }
extension Holder { func carry<T>(&self, v: T) -> T { v } }   // ICE at the method call
```

**Instead:** give generic methods names that no free function uses. Name type
parameters so they match no declared type. Give static and instance methods
different names.

**Checker:** yes: compare the declared names across the compiler source *and*
`sawc/std/`, as S18 does (Air t9). SL-5's collision is with any generic free
function in the program, std's included: `std.cbor` and `std.json` each declare
`encode<T>`, so a generic method named `encode` in the compiler source would
hit it whenever either module is compiled in.

### L10. Static trait requirement through a type parameter (SL-113)

**Shape:** inside `func decode<T: Deserialize>(…)`, the call
`T.deserialize(from: &var dec)` is ``undefined variable `T` ``. Instance
requirements dispatch through a bound correctly.

**Instead:** call static requirements on the concrete type, or declare the
requirement as an instance method.

**Checker:** yes: refuse a call whose receiver is a type parameter of the
enclosing declaration.

### L11. Value-position loops (SL-22)

**Shape:** a `while` or `for` used as a value (`let x = while … { break v }`)
whose result type is not an integer is an ICE. The `None` sentinel for the
loop's result is built as an integer constant.

**Instead:** declare a `var` before a statement loop and assign it before
`break`.

**Checker:** yes: refuse `break` with an operand.

### L12. Leading minus after a block (SL-45, SL-88)

**Shape:**
- **SL-45**: a tail beginning with `-` after a block statement such as
  `if … { return … }` is parsed as a subtraction whose left side is the block,
  and ICEs at the `BinaryOp`.
- **SL-88**: a line beginning with `-` after a value-`if` statement does the
  same.

**Example (SL-45):**
```saw
func h(b: Int) -> Int {
    if b >= 48 { return b - 48 }
    -1   // ICE: 'NoneType' object has no attribute 'type'
}
```

**Instead:** never begin a statement or a tail with unary `-`. Write
`return -1`, or bind the value first.

**Checker:** yes: refuse a line whose first token is `-`.

### L13. Statement match arms (SL-59)

**Shape:** a bare statement (`return`, `break`, `continue`, `let`) as a
match-arm body is a parse error, "Unexpected token: RETURN". Design 259 R7′
makes it legal in the new grammar.

**Instead:** brace statement arms and end every arm with a comma:
`case 0 -> { return 7 },`.

**Checker:** yes: refuse an arm body that begins with a statement keyword.

### L14. Nesting depth and chain length (SL-308, SL-380)

**Shape:**
- **SL-308**: the parser has no depth guard. Nested parentheses fail at about
  61 levels, nested `if` blocks at about 48, and nested closures at about 50,
  with a raw `RecursionError` traceback.
- **SL-380**: a long left-deep chain ICEs on recursion depth in later passes.
  `+` and `&&` chains fail between 300 and 400 terms, `else if` chains around
  300, and builder method and `as` chains by 1000.

**Instead:** keep block nesting under about 30 levels and operator or
`else if` chains under about 100 terms. Use `match` for long dispatch; a
1000-arm `match` compiles.

**Checker:** yes: measure nesting depth and chain length syntactically.

### L15. Unreduced ICE: "no copy symbol for field" (SL-389)

**Shape:** not yet reduced. `prototypes/minivm/tests/numeric_contract.saw`
ICEs with `no copy symbol for field code`. From reading
`sawc/codegen/methods.py`, the message comes from a derived `copy()` whose
field type has no emitted `copy` function. In minivm the field is
`FuncIR.code: Vector<Instruction>`, and both `FuncIR` and `Instruction` take
`@synthesize … ExplicitCopy`. The likely trigger is a derived `copy()` emitted
in a program that never demands `Vector<Instruction>.copy()`. This is
unconfirmed; nothing was compiled.

**Instead:** until it is reduced, don't `@synthesize` `ExplicitCopy` on a struct
that holds a `Vector` of another user struct. The compiler's arena tables need
no copy.

**Checker:** no, not until the shape is confirmed. A lint could flag the
candidate shape meanwhile.

### L16. A long expression cannot wrap outside brackets (SL-83)

**Shape:** a binary expression cannot continue on the next line unless brackets
already enclose it. Design 259 R3 rules trailing-operator continuation legal,
and the frozen parser refuses it. Every long `&&`/`||` condition or arithmetic
expression meets this (Air t8).

**Example:**
```saw
if kind == TokenKind.Ident &&     // refused at Stage 0
   next.is_open_paren() { … }
```

**Instead:** wrap a multi-line expression in parentheses:
`if (kind == TokenKind.Ident &&` on one line, then `next.is_open_paren()) { … }`.

**Checker:** not needed. The frozen parser refuses it loudly, and the entry
exists so authors don't each rediscover the spelling.

### L17. A type named like a prelude type (SL-71)

**Shape:** a type in a dependency module named like a prelude type (`Token`
is fine; `Result`, `Vector`, `Duration`, `Path` are not) silently resolves to the
builtin at a use site, and draws a nonsense refusal.

**Instead:** no compiler type reuses a prelude type name (SL:architecture §4's
blanket rules).

**Checker:** yes: compare each declared type name against the prelude list.

## Cases with no issue

These four come from codex's review of the parked SL-2.p2 r3 (SL-2 c29, with
the lead's c30). Two of them are defects of that parked patch rather than of
main, so each entry says how main behaves.

### C1. Uncharged `move *p`

**Shape:** in the parked depth funnel, `move *p` consumes the `*` without
charging a nesting level. With 255 parenthesis groups around `move *p`, 257
constructs are accepted where the limit should refuse at the star. On main
there is no depth guard at all (L14), and `*p` is raw-pointer code outside the
subset. Loud on main, through L14.

**Instead:** use no pointer dereference in the compiler source. The new parser
adopts the sl2u0 funnel (architecture §3.2) and must charge the `*` in
`move *p`.

**Checker:** yes: refuse `move *`.

### C2. Trailing backslash at end of file

**Shape:** present on main. In `sawc/lexer.py`, `read_string` calls
`advance()` after an escape backslash unconditionally, and `advance()` indexes
the source directly. A file that ends in `"abc\` raises `IndexError: string
index out of range` instead of a located diagnostic. Loud.

**Instead:** end every source file with a newline, outside any string literal.

**Checker:** yes: refuse a file that ends inside a string literal or does not
end in a newline.

### C3. Quote inside a `//` comment inside an interpolation

**Shape:** the c29 finding is that the parked N7 rule counts quotes inside an
interpolation's `//` comment. On main the lexer scans an interpolation's
`{…}` by counting braces alone, ignoring quotes and comments. Any string left
open after an interpolation is reported as an unterminated interpolation at
the first `{`, not at the opening quote. So on main this is a misplaced
diagnostic on code that is already invalid. Loud. From reading the lexer, and
not probed: a `{` or `}` inside a comment or a nested string within an
interpolation moves the point where main ends the interpolation.

**Example:**
```saw
func main() { let s = "a {1 // comment: "
}
// reported at the `{` (1:26), not at the opening quote (1:23)
```

**Instead:** keep interpolations to a name, a field or a simple call. Put no
comments, braces or nested string literals inside `{…}`.

**Checker:** yes: lexically, refuse `//`, `{`, `}` and `"` inside an
interpolation's braces.

### C4. Comma-free next case after an operand-less `return` or `break`

**Shape:** in the parked statement-arm grammar (R7′),
`match n { case 0 -> return case _ -> return }` fails with "Unexpected token:
CASE", and `break` fails the same way. Adding the arm comma fixes it. Main
refuses every bare statement arm (L13), so this spelling is refused on main as
well. Loud.

**Instead:** brace statement arms and end every arm with a comma (L13).

**Checker:** yes: the L13 rule covers it.

## Inventory

Each of the 82 issues the sweep flagged, plus the four promoted after the Air's review and one found since, mapped to its entry. "Call" is this
ledger's reading. Where it differs from the sweep, Notes for the lead says why.

| Issue | Entry | Call |
|---|---|---|
| SL-5 | L9 Name collisions within a program | loud |
| SL-7 | L2 Closure literals and call syntax | loud |
| SL-13 | L1 Integer literal adoption | loud |
| SL-14 | L3 Module-qualified spellings | loud |
| SL-22 | L11 Value-position loops | loud |
| SL-28 | L4 Optional and Result shaping | loud |
| SL-31 | S1 `init` in a generic extension | fixed on main |
| SL-32 | S1 `init` in a generic extension | loud |
| SL-36 | L3 Module-qualified spellings | loud |
| SL-38 | L2 Closure literals and call syntax | loud |
| SL-41 | L2 Closure literals and call syntax | loud |
| SL-42 | L4 Optional and Result shaping | loud |
| SL-45 | L12 Leading minus after a block | loud |
| SL-46 | L4 Optional and Result shaping | loud |
| SL-49 | S9 Type aliases | silent |
| SL-50 | S9 Type aliases | silent |
| SL-52 | S9 Type aliases | loud |
| SL-53 | L1 Integer literal adoption | loud |
| SL-56 | L1 Integer literal adoption | loud |
| SL-59 | L13 Statement match arms | loud |
| SL-61 | S8 Enum `==` with a hand-written `equals` | silent |
| SL-62 | L8 `Box`-linked types | loud |
| SL-63 | L8 `Box`-linked types | loud |
| SL-65 | L2 Closure literals and call syntax | loud |
| SL-68 | S20 Float literals out of range | silent (promoted after review) |
| SL-70 | L1 Integer literal adoption | loud |
| SL-71 | L17 A type named like a prelude type | loud (promoted after review) |
| SL-73 | L2 Closure literals and call syntax | loud |
| SL-74 | S3 Owned values around `try` and `catch` | loud |
| SL-75 | L1 Integer literal adoption | loud |
| SL-77 | S9 Type aliases | loud |
| SL-78 | L3 Module-qualified spellings | loud |
| SL-80 | S1 `init` in a generic extension | silent |
| SL-83 | L16 A long expression cannot wrap outside brackets | loud (promoted after review) |
| SL-84 | L1 Integer literal adoption | loud |
| SL-85 | L5 Zero-sized `Result` payloads | loud |
| SL-88 | L12 Leading minus after a block | loud |
| SL-96 | L9 Name collisions within a program | loud |
| SL-107 | L9 Name collisions within a program | loud (possibly fixed) |
| SL-111 | S4 Whole-call exclusivity | loud |
| SL-113 | L10 Static trait requirement through a type parameter | loud |
| SL-114 | L6 Copy tier and conditional conformance | fixed on main |
| SL-115 | L3 Module-qualified spellings | loud |
| SL-125 | L3 Module-qualified spellings | loud |
| SL-130 | S5 `&var` into a `let` binding | silent |
| SL-131 | L7 Fixed-size arrays | loud (likely fixed) |
| SL-132 | S18 Names shared program-wide | loud |
| SL-133 | L7 Fixed-size arrays | loud |
| SL-156 | S16 Generic bodies returning a type parameter | silent |
| SL-191 | L7 Fixed-size arrays | loud |
| SL-192 | S2 Moving or re-matching a payload of a borrowed match | silent |
| SL-194 | L1 Integer literal adoption | loud |
| SL-195 | S18 Names shared program-wide | loud |
| SL-199 | L3 Module-qualified spellings | loud |
| SL-240 | S3 Owned values around `try` and `catch` | silent |
| SL-264 | S10 Nested optionals | silent |
| SL-270 | L6 Copy tier and conditional conformance | loud |
| SL-284 | S4 Whole-call exclusivity | silent |
| SL-285 | S14 Argument labels | silent |
| SL-288 | S12 Consuming an erased box through a projection | silent |
| SL-290 | S10 Nested optionals | loud |
| SL-291 | L4 Optional and Result shaping | loud |
| SL-292 | L4 Optional and Result shaping | loud |
| SL-293 | L2 Closure literals and call syntax | loud |
| SL-294 | S4 Whole-call exclusivity | silent |
| SL-295 | S6 Function exits | loud |
| SL-297 | S14 Argument labels | silent |
| SL-298 | S6 Function exits | silent |
| SL-299 | S7 Integer literal above `Int.max` | silent |
| SL-308 | L14 Nesting depth and chain length | loud |
| SL-309 | S17 `?` or `??` after a cast target | silent |
| SL-310 | L2 Closure literals and call syntax | loud |
| SL-319 | S18 Names shared program-wide | silent or loud |
| SL-340 | S11 Owning payloads in cells | silent |
| SL-348 | S3 Owned values around `try` and `catch` | silent |
| SL-352 | L2 Closure literals and call syntax | loud |
| SL-358 | L3 Module-qualified spellings | loud |
| SL-363 | L7 Fixed-size arrays | loud |
| SL-368 | S15 Methods called on an indexed element | silent |
| SL-380 | L14 Nesting depth and chain length | loud |
| SL-381 | L6 Copy tier and conditional conformance | loud |
| SL-382 | S13 Explicit nested type arguments | silent |
| SL-383 | S9 Type aliases | loud |
| SL-384 | S9 Type aliases | loud |
| SL-389 | L15 Unreduced ICE | loud (shape unconfirmed) |
| SL-390 | S19 Type walks bounded by a depth count | silent (promoted after review) |
| SL-401 | S21 A line break inside an interpolation | silent (found in the compiler-skeleton review) |

No issue is marked "not reachable from the subset". Several entries depend on
features the subset does not list (`any`, `Box`, cells, pointers, fixed arrays,
`FuncPointer`). Architecture §4's feature list says what the subset uses, not
what it excludes, so those entries stay live, and their checker rules make the
exclusion mechanical.

## Notes for the lead

**Calls that differ from the sweep:**
- **SL-31**: the sweep said silent (leak). The leak was fixed on Sep 2 by 218c
  stage 3 (178e6522, "DF-251b's XFAIL flipped"), so the issue is stale. The
  live hazard in the same generator is SL-80.
- **SL-114**: the sweep said loud "if still live". It was fixed by design 219
  B2, and conformance row V32 (`V32_copy_bound_is_tier_derived.saw`) pins an
  automatically Copy-tier struct meeting `T: Copy`. The issue is stale.
- **SL-131**: kept loud, but likely fixed. The predicate it names now answers
  from the copy tier. Probe it before closing.
- **SL-107**: kept loud, but possibly fixed by design 236. Only the same-label
  shape is unprobed.
- **SL-383 and SL-384**: the sweep said silent ("typed Void"). Every probed
  cell fails to compile with a misleading error, so I list them as loud. A
  discarded statement-position call through such an alias is unprobed.
- **SL-352**: loud. SL-347's juxtaposition refusal (0839ed7d) is on main, so
  the census's silent `let x = { 1 }()` face (dropping the `()`) is now a
  refusal.
- **SL-309**: kept silent as the sweep had it. The whitespace-dependent parse
  is silent, but every probed cell then fails type checking.
- **SL-14**: only its DF-226c half, a qualified `FuncPointer`, is a hazard.
  DF-226b concerns a `borrows` function type, which is invalid code anyway.

**Hazard candidates outside the 82.** SL-68, SL-83, SL-71 and SL-390 are
promoted to entries S20, L16, L17 and S19 (Air t7, t8), and added to the
inventory. The rest stay out, each for the reason given:
- **SL-68** (DF-276a): promoted to S20.
- **SL-83** (design 259 R3): promoted to L16.
- **SL-66**, frozen half: a bare reference to an all-defaulted generic may lose
  its defaults. The census could not reproduce it at a parameter, and SL-382
  is the confirmed neighbor.
- **SL-71** (census N9): promoted to L17.
- **SL-390:** promoted to S19, with the members of its c1 sweep that the subset
  can reach.
- **Closure-capture bugs** (SL-26, SL-30, SL-345, SL-387) are excluded by "no
  captures". Architecture §4 names SL-345 as a checker example; the
  refuse-every-capture rule covers it.
- **SL-313** (N11/N12): a Stage-0-built binary dies with a bare SIGSEGV at
  about 1M recursion frames or on a deep `Box`-chain drop. That is not a
  Stage 0 build hazard. It matters for the new compiler's own walks.
- **SL-378** (unsafe placement write) is outside the subset.
- **Census N10** (the `as`-cast copy bypass) was fixed by fd0cbeb8 (DF-299a).
  It is not a hazard.

**Decisions for the lead,** each followed by the lead's resolution (Sep 25):
1. **Blanket checker rules.** Resolved: adopted as the subset's definition, and
   written into SL:architecture §4. Many entries reduce to a few blanket rules
   that are cheap to check:
   - no `type` aliases;
   - selective imports only;
   - no `init` in a generic extension;
   - no overloads with a non-`Int` integer parameter;
   - no `any`, `Box`, cells, pointers or fixed arrays. The cells are named once,
     here (Air t9): `Mutex`, `SpinLock`, `Once`, `UnsafeMutableInterior`,
     `Atomic` and `Arc`. `Arc` is not in the subset's feature list, since the
     compiler needs no shared ownership;
   - closures with annotated parameters, passed in parentheses;
   - no value-position loops;
   - no statement arms without braces;
   - added after the Air's review (t6–t8): in a field type that nests a generic,
     every defaulted type argument written, or fields one generic deep (S13);
     written types under 8 levels of nesting, `T?` rather than `Optional<T>`,
     and no `Self` inside a tuple type (S19); no float literals (S20); no type
     named like a prelude type (L17).

   Adopting them as the subset's definition makes most `yes` checker lines one
   rule each.
2. **Stale issues.** Close SL-31 and SL-114 as fixed, and probe SL-107 and
   SL-131 first? Resolved: no action. The tracker cleanup already closed all
   four (SL-107 as done, the others as `frozen`), and their entries here
   record the status.
3. **C1 and C4** are defects of the parked SL-2.p2, not of main. On main they
   reduce to L14 and L13. Resolved: they stay here as a record. The new
   parser's rules (SL-393) cover the behaviour.
4. **SL-389** needs a minimal repro before the ledger can name its shape.
   Resolved: L15 keeps its candidate shape from reading the code. The issue is
   closed as `frozen`, and a Stage 0 build that hits the ICE reopens the
   question.
5. **S11, S12, S15 and L8** matter only if the compiler source uses `any`,
   `Box`, cells or pointers. Resolved: SL:architecture §4 excludes them
   explicitly (decision 1).

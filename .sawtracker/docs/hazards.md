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
  entry's **Instead** spelling. An **Instead** spelling is a Stage 0
  workaround, not a Saw idiom (the user, Sep 29), so every site that uses one
  is marked `// Stage 0 workaround (SL:hazards <id>): canonical: <original>`,
  where the original is the canonical spelling the workaround replaced (a
  ` — <why>` may follow). The same marker serves sawlang and sawtracker. A check
  validates each marker's id and prints the inventory with the canonical text,
  so restoring the canonical spelling is mechanical. After self-hosting, every marked
  site returns to its natural spelling and the marker check turns into a
  refusal (SL-425). Do not copy an **Instead** spelling into code that Stage 0
  does not build.
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

**Leaks are tolerated in Stage 1** (the user's ruling on SL-399). Stage 1 runs
to compile the compiler source and is then replaced: Stage 2 is built by the
new compiler, and the fixpoint compares Stage 2 with Stage 3. So a leak costs
Stage 1 memory, never output, and running out of memory is loud. One condition
makes this true: no skipped drop may have an observable effect. The compiler
source declares no `deinit` (checker rule `deinit-body`), and the std `deinit`s
it reaches only free memory or close a file descriptor. The compiler source may
use std's `env`, `file` and `path` modules, whose API holds no write. Adding a
std module or API to the checker's allowlist re-checks that condition, and a
test pins the module list so that no change to it slips by (Air t14). A leak-only entry is marked **leak only**. It keeps its Shape and
Instead, since each shape becomes a test the new compiler must pass, but it has
no checker rule.

Issues that share one mechanism, or one rule that avoids them, form one entry.
A family with any silent member is listed under silent hazards, and each issue
in it is tagged. Entry codes (S1, L1, C1) are what the inventory maps to.

An entry stays while something cites it: a checker rule, a workaround marker,
an oracle annotation, or an open defect it pins. The rest are retired: the
SL-425 sweep compiled and ran every entry's repro with sawc2 and the seed, and
an entry handled correctly by both and cited by nothing is deleted. A mention
of an id with no section here (S7, L14, C1, ...) names a retired entry; its
verdict is in SL-425 c7.

**The checker today (SL-839, Oct 23).** The intersection rule is lifted:
nothing runs Stage 0 over the compiler's source, and `subset_check.py` keeps
only `grammar`, `import-allowlist` (its hygiene part), `workaround-marker` and `redundant-visibility`. An entry's
**Checker** line naming any other rule records a retired rule. The entry stays
while a marker, an oracle annotation or an open defect still cites it.

Sources: the Sep 25 tracker sweep (SL:tracker-cleanup, which closed most of
these issues as `frozen`), the issue text, and the Sep 1 parser census
(`designs/reviews/parser-census-sep1.md`). Nothing was compiled for this
ledger; the issues' repros are the evidence. Main is at 2fa71814.

## Silent hazards

### S3. Owned values around `try` and `catch` (SL-240, SL-348, SL-74, SL-427, SL-429, SL-430)

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
  - an earlier argument or a consumed receiver, including the arguments of a
    custom `init` and of a labelled function call;
  - an earlier tuple or array element;
  - an earlier enum-payload value, as in `Msg.Move(r: make_res("p"), n: try
    fail_it())` (Air, probe q5);
  - an earlier Map-literal key or value;
  - an earlier interpolation segment;
  - a `move` between two `try`s;
  - the heads of `if`, `match` and `for`.

  An owned temporary with no `move` written leaks the same way. That covers a
  call's result, a struct literal, and an interpolated string passed as an
  argument. It also leaks in a `while` condition, where a moved value is
  already refused because the condition runs again (SL-399 r3 review, probes
  b04b, b04c, b04d and q1).

  A memberwise *struct* construction drops its earlier fields only where the
  construction is bound: as a `let` or `var` initializer, an assignment's right
  side, a tuple element, or a field of another bound memberwise construction.
  Passed as an argument, returned, used as a receiver or a payload,
  interpolated, or used as an `if` arm's value, it leaks like any other
  temporary (SL-399 r4 review, probes m6, n3, n4, n6, n8 and n12). An enum
  payload construction always leaks.

  Two more faces leak the same way:
  - **A named value passed by value.** A Copy-tier owning value, such as a
    local `String` or a struct holding one, that is passed by value before a
    failing `try` leaks its retain. That holds when the value is read again
    afterwards, and when it is a by-value parameter passed on. In
    `sink_s(s, try fail_it())`, 1000 failures leak 1001 allocations, against 1
    for the hoisted control (probes o2, o5, o8 and o9; reproduced on main
    2fa71814).
  - **A temporary receiver under a failing `try`.** In
    `let n = try make_res("x").fail()`, the receiver is never dropped when
    `fail()` errs. It is dropped with no `try`, when the `try` succeeds, and
    when the receiver is bound first. A temporary *argument* is dropped by the
    callee (probes q8 and q8b; reproduced).

  A checker that traces which operands own something has missed a face in each
  review round, so the subset enforces the Instead structurally (Checker).
- **SL-427** (silent, leak): the *error* itself is never released on two
  paths, found by sawtracker's ST-66.
  - A `try … catch` whose catch diverges, as in
    `let v = try fail(n) catch { return -1 }`, leaks the caught error once per
    failure, in sync code and in a coroutine alike. The lead measured 1,000
    leaks at N=1,000 and 2,000 at N=2,000.
  - In a coroutine, `return try f()` leaks the error it propagates; sync code
    does not.

  - **The catch need not diverge** (sawtracker's ST-71, measured with `leaks
    --atExit` at N=1,000 and 2,000, -O2): a catch that FALLS THROUGH,
    `let v = try f() catch { -1 }`, leaks the error too, in sync code as well.
    So does a `try` inside a block `try { … } catch { … }`.

  A `match` on the `Result` releases the error in every one of these cases (0 leaks).
- **SL-429** (silent, leak): `try?` never releases the error it discards, in
  sync code too. `let _ = try? fail(i)` and `let o = try? fail(i)` each leak
  one block per failure. The lead reproduced 1,000 leaks at N=1,000 and 2,000
  at N=2,000, in sync code at -O2, and a `match` on the same `Result` leaks 0.
  This reaches Stage 1, because the compiler is sync code (the Air's
  probe_leak18).
- **SL-430** (silent, leak): in a coroutine, a propagating `try` leaks the
  error in every position but one, and SL-427's `return try` is one case of
  it.
  - **Leaks:**
    - a `try g()` statement;
    - `let v = try f()`;
    - `v = try f()`;
    - `total += try f()`;
    - `return try f()`;
    - any of those inside an `if`;
    - `try … catch { return 0 }`.
  - **Clean:** a `try` nested in a call argument (`add1(try f(i))`),
    `return f(i)`, and a `match`. The call-argument exception is about where
    the `try` sits after the coroutine transform, not in the source: the
    transform rewrites some `let x = try f()` into call arguments, and those
    still leak (ST-71). So a census cannot trust the AST position, and counts
    every coroutine `try`.
  - Where the `try` sits relative to the suspension makes no difference.
  - **The loud twin:** an ExplicitCopy error type is refused in the same
    position ("cannot copy value of type `Solo` which implements
    ExplicitCopy"), while the sync form compiles and leaks 0. So the coroutine
    path copies the error instead of moving it, and for a Copy-tier error that
    copy is the unbalanced retain (the Air's probe_leak15, probe_leak16 and
    probe_leak17).
  - The self-hosted compiler is sync-only, so this face does not reach Stage 1.
- **SL-74** (loud): a `move` inside a `catch` block that diverges (`return`,
  `panic`) still retires the binding on the fall-through path, so the next use
  is refused. All three `catch` forms do this.

**Example (SL-348):**
```saw
var r = Res(name: "kept")
let n = sink_rev(move r, try fail())   // fail() errors: `r` is never dropped
```

**Instead:** bind every `try … catch` value to a named local. Hoist every
propagating `try` into its own `let`, over a call on a name or a field path,
before the expression that uses its value. In particular, hoist it before any
expression that moves a value, builds an owned temporary, or passes an owning
value by value:
`let k = try fail()`, then `sink_rev(move r, k)`; and
`let k = try fail_it()`, then `sink2(make_res("fresh"), k)` (Air t10). When an error path must
consume a local, `match` on the `Result` instead of writing `move` in a
`catch`. Where a caught error is discarded at all (`catch { return … }`, and
also a fall-through `catch { -1 }`), where the code would write `try?`, or where a coroutine would propagate with `try`,
`match` on the `Result` too, so the error is released.

**Checker:** leak only, except `try?`. The rule `optional-try` refuses a `try?`
expression in `compiler/` (SL-432; SL:open-questions D3), because a parser's
speculative fallbacks would leak per attempt. SL-240 and SL-348 leak, SL-74 is
loud, and SL-430 leaks only in a coroutine. Hoisting each `try` into its own
`let` remains good style, but nothing enforces it.

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

### S23. An owned value consumed without a binding: comparison operands, interpolation segments, format arguments, or a head's receiver (SL-404)

**Mechanism.** The frozen compiler's owned-temporary check (`_is_owned_temporary`) lists the positions that consume a value without binding it:
- a member-access object;
- a method-call receiver;
- an `is_some`/`is_none` receiver;
- an expression statement;
- an `if let`/`guard let` scrutinee;
- a `match` scrutinee.

Four more positions consume without binding and are missing from that list: a comparison operand, an interpolation segment, a format argument of `print`, `panic` or `assert`, and a cast operand (`as`). There, an owned value (a `String`, a struct holding one, a `String?`) is never released. The cast leaks in std itself: `std/file.saw` and `std/directory.saw` write `path.as_str() as UnsafePointer<Int8>`, so every `File` or `Directory` call made with a freshly built path leaks one block (SL-427). The lead measured `make(n) as UnsafePointer<Int8>` at 1 leak per call, and 0 with the value bound first. A fresh value on either side of `??` measured clean. On a comparison, the right operand is also retained even when nothing owns it.

**Shape (leak only):**
- **What leaks, at those four positions:** an operand that is not a named place or a literal.
  - a call result: `f() == x`, `"{pad2(m)}"`, `print("{}", make(n: i))`;
  - a subscript read, including a field reached through one: `v[i] == "x"`, `m["k"]! == "x"`, `v.get(i)! == "x"`, `"{v[0]}"`, and a parser's `self.toks[self.pos].text == word`;
  - an interpolation used as a comparison operand: `req.token != "Bearer {token}"`.

  A call result leaks once per evaluation. A subscript read of a container that outlives its uses leaks once per distinct element, because the element's buffer is over-retained.
- **What does not leak, in a sync function:**
  - a named place: a local, a parameter, a field path (`t.text`), a tuple field, `o!` on a bound optional;
  - a literal;
  - a call or subscript that is only a receiver inside a trivial operand: `v[i].len() == 99`.
- **In a coroutine** a named place is read out of a frame slot as a fresh value, so it leaks at these positions too, and binding to a `let` does not help (chat m249). The self-hosted compiler is sync-only, so this does not reach Stage 1.
- **A `Printable` segment, whatever it is.** An interpolation segment of a user `Printable` type is rendered through a `to_string()` the compiler synthesizes, and that string is never released, even when the segment is a named local: `let t = Tok(…)` and then `"{t}!"` leaks once per evaluation (1,000 at N=1,000, 2,000 at N=2,000). Primitive segments (`Int`, `Float`, `Bool`) leak nothing, and neither does a `Printable` format argument, `print("{}", t)`, which renders through `format(into:)`. This reaches Stage 1, because a dump or diagnostic that interpolates a token or node is the natural spelling.
- **A receiver in a control-flow head.** A temporary receiver the head does not bind is dropped late, and an early `return` skips the drop, with or without a `try`: `if make_res("x").size() > 0 { return 1 }` in the head of an `if`, `while`, `match` or `for`. Over 1000 calls, `leaks --atExit` counts 1001 leaks, against a by-value argument's baseline of 1.

A temporary passed by value as an argument is dropped by its callee. An owned `match` or `if let` scrutinee that the pattern binds drops correctly. `StringBuilder.append` transfers its argument and does not leak.

**Evidence.**
- **Comparisons.** `for _ in 0..1000000 { let _ = s.substring(1, 6) == "zzzzz" }` leaks 32 bytes per iteration at -O2 and -O0, and nothing when the substring is bound first (SL-404 c2). In sawtracker this cost 3.5 GB at startup: a byte-at-a-time `find` compared a fresh substring at every position of 114 MB of journal.
- **Segments.** `"{pad2(m)}-{pad2(m + 1)}"` and `"{v[0]}-{v[1]}"` each leak 2 per evaluation in sync code, and 0 with the segments bound first.
- **Format arguments,** measured by the lead over 2,000 iterations:
  - `print("{}", make(n: i))` leaks 1,999;
  - `print("{}", v[i % 2])` leaks 2, once per distinct element;
  - `let s = make(n: i)` then `print("{}", s)` leaks 0.
- The census tool asks `_is_owned_temporary` at every comparison operand whose type needs cleanup. Excluding string literals, its answer matches every probe, leaking and not. Measurements and the tool are in chat f13 and f14.

**Instead:**
- **In sync code, and so in all of Stage 1:** at a comparison, an interpolation segment, a format argument or a cast, an operand that is not a named place or a literal is bound to a `let` first, always. For example, `let text = self.toks[self.pos].text`, then `text == word`. A user `Printable` value is never interpolated directly: bind its rendered text first, `let text = t.to_string()`, then `"[{text}]"`, which leaks nothing (the Air's probe_leak12, at -O2), or pass it as a format argument. It is the same bind-it-first rule, applied to the rendered text rather than the value.
- **In a coroutine,** where binding does not help: use the receiver form `a.equals(b)` or `not a.equals(b)`, a `match` on the value, or a synchronous helper that does the check or builds the string.
- **In a control-flow head:** bind a temporary receiver to a `let` before the head.

**Checker:** yes, an exception to the Stage 1 leak ruling (the user, Sep 29). The checker refuses an owned operand that `_is_owned_temporary` accepts, at a comparison, an interpolation segment, a format argument or a cast in `compiler/`. The rule is built under SL-422, and SL-405 adds the cast.
- **The case for an exception.** A parser comparing token text through a subscript, or a dump or diagnostic interpolating `"{kind_name(t.kind)} {t.text}"`, leaks per token over every file Stage 1 compiles.
- **An exact rule:** refuse an owned operand that `_is_owned_temporary` accepts, at a comparison, an interpolation segment, a format argument or a cast in `compiler/`. String literals are exempt, since they are static.
- **Today:** that predicate finds 0 leaking comparison operands in sawc2 (the driver, the lexer and the std they use). `compiler/lex` compares bytes as `Int` and builds records with `StringBuilder.append`.

### S26. A static or an operator from a bounded extension, on an argument that misses the bound (SL-463)

**Shape (missing check):** a member declared in `extension Cell<T: Equatable> { ... }`, or brought by a bounded conformance `extension Cell<T: Equatable>: Equatable`, exists only where `T` meets the bound. Stage 0 enforces that for an instance method (`a.same(&b)` on a `Cell<Token>` is refused: "has no method `same`: requires `T: Equatable`"), but not for a static, `Cell<Token>.twin(&a, &b)`, nor for an operator that resolves to such a member, `a == b` through the bounded conformance's `equals`. It accepts both, and instantiates the member's body at a type that body was never checked for. sawc2's typecheck refuses both, as `type.bound`, through the one member lookup that methods, statics, subscripts, `for` loops and `init`s share.

**Instead:** call such a member only on an argument that meets the bound.

**Checker:** yes: `bounded-extension` refuses every bound on an extension in compiler source, so the shape cannot arise there, and the new std is compiled by sawc2 alone.

### S28. A `deinit` with an observable effect in the compiler's cone (SL-522)

**Shape (silent: lost output):** Stage 1 is built by Stage 0, and its leaks are tolerated, provided that no skipped drop has an observable effect (see "Leaks are tolerated in Stage 1" above). A `deinit` that does more than free memory or close a read descriptor (a buffered writer that flushes, a process handle that waits or kills, a file that is renamed into place on drop) would turn a Stage 0 leak into lost or wrong output, silently. That is the natural design for an output file, so writing the compiler's own output (SL-522: the `.ll`, objects, and the spawned clang) is where this hazard arises.

**Instead:** effects are explicit calls that return a `Result`, never `deinit` work. Write unbuffered (`write(&Data) -> Result<_, SystemError>`) and finish with an explicit `close() -> Result`; wait for a spawned process explicitly (`run()` blocks and returns the exit status); a `deinit` only releases the descriptor. Every site marks the canonical design it replaces: `// Stage 0 workaround (SL:hazards S28): canonical: <the buffered writer / deinit-flushing form>`. They return to it under SL-425, once Stage 0 is retired by the pinned seed binary (SL:open-questions, "Bootstrap seed").

**Checker:** the existing `deinit-body` rule refuses a `deinit` in compiler source. The std modules in the cone are reviewed against this entry in `compiler/tools/std_cone_review.md`, and adding a std write or process API re-checks it (the allowlist pin).

### S36. A spawn borrow released by joining a rebound handle variable (SL-565)

**Shape (silent: a use-after-free):** a `&var` (or `&`) argument or capture at a `group.spawn` borrows its root until that task's handle is joined, or until the group is torn down (spec: the borrow's extent is the task's life). Stage 0 releases the borrow at a `join` of any variable that ever held the handle, not only one that holds it at the join. So rebinding the handle variable, then joining it, ends a borrow whose task is still running:

```saw
var h = group.spawn(fill(&var buf, 200))
h = group.spawn(quick())       // the first handle is discarded; its borrow lasts to the group's teardown
h.join()
consume(move buf)              // accepted: the teardown then drives `fill` into the freed buffer
```

The same hole is reached through `let g = move h; h = group.spawn(…); h.join()`, and through a spawn site inside a loop: a `let h = group.spawn(look(&buf))` in the body leaves an earlier iteration's task unjoined, and a later iteration's `h.join()` releases the one loan both tasks share (shared borrows only: Stage 0 applies the loop-body rule to exclusive borrows alone, where the spec refuses every spawn borrow still live when a loop body ends). Stage 0 compiles all of these, and the program faults at the group's teardown. sawc2 refuses them once SL-565 releases a borrow only where the joined value is the borrowing task's handle on every path. The pins are its borrowck refusal fixtures.

**Instead:** give each spawn that borrows its own `let` binding and join that binding. Never rebind or move out of a handle variable while its task still borrows.

**Checker:** not needed: the compiler's source spawns no task.

### S37. A detached thread that finishes after the detach drops no result (SL-765)

**Shape (silent: a lost deinit, and a leak):** `Thread.spawn { … }` then `detach()`. When the detach runs first and the thread finishes after it, Stage 0's thread exit (`_generate_spawn_trampoline`, `sawc/codegen/calls.py`) frees the control block without destroying the result. A result that owns something (a `String`, a value with a printing `deinit`) is never dropped. `leaks --atExit` shows the result's storage as a root leak. The other order (exit, then detach) and a join both drop it. sawc2 drops it once in both orders (SL-765 T2's `__saw_exit` and T3a's detach report).

**Instead:** join the thread when its result owns anything, or return a value with no drop from a thread you detach.

**Checker:** not needed: the compiler's source spawns no thread.

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

### L29. A suspending default value: sawc2 charges the caller that leaves it out, and Stage 0 refuses both forms (SL-656)

**Shape:** the user's ruling (b) on SL-656 says a default is evaluated in the caller, so its effect belongs to the call that leaves the argument out, never to the function. For `func f(n: Int = slow())`:
- **sawc2:** `f` is an ordinary function whose summary is its body's alone. `f()` suspends in the caller, and is refused only in a `sync` context (`effect.sync`, naming the default). `f(n: 2)` is accepted anywhere, `sync` included.
- **Stage 0:** refuses every call that leaves out a suspending default, and also refuses a `sync` caller that passes the argument explicitly.

So code using a suspending default builds under sawc2 and fails under Stage 0. It is loud: Stage 0 refuses at the call.

**Instead:** in code Stage 0 builds (`compiler/`, `blade/`, `libs/`, `examples/`), give no parameter a default value that suspends; make the suspending value an argument the caller passes.

**Checker:** not needed: Stage 0 refuses loudly.

### L33. A field read two struct hops away, bound by a `let`: Stage 0 loses the binding when neither struct type is named in the module (SL-649)

**Shape (loud):** a field read that stands alone as a statement's value, with its receiver two struct hops from a parameter or `self`, and neither struct type named in the using module, yields no value in Stage 0:
- `let s = o.res.node.start` reports "undefined variable `s`" at the next use;
- a tail `o.res.node.start` reports "body has no value".

The binding's name is irrelevant. It works when the field is read as a call argument (`show(o.res.node.start)`), when a `let` holds the intermediate struct (`let n = o.res.node`, then `n.start` in an argument), when either struct name is imported, and with a single hop. The compiler's instance was `let start = self.res.nodes[prior.node].start` in typecheck's `refuse_second_policy`: `self.res` is a `ResProgram`, `nodes` holds `AstNode`, and `conform.saw` imports neither. The minimal repro is three files (the trigger needs a module boundary); it is on SL-649.

**Instead:** bind the intermediate struct and read the field where it's used: `let node = self.res.nodes[prior.node]`, then `node.start` as the argument. Don't bind a field read of such a chain to a local. Importing the type's name only to cure it adds an unused import.

**Checker:** not needed: the failure is loud, and the shape needs type resolution and import scope, which the subset checker doesn't have.

## Cases with no issue



These four come from codex's review of the parked SL-2.p2 r3 (SL-2 c29, with
the lead's c30). Two of them are defects of that parked patch rather than of
main, so each entry says how main behaves.

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

### C10. A consumed `match` on an owned `Optional` keeps its payload to scope end

**Shape (silent: wrong drop timing):** on an owned `Noisy?`, `match o { case Some(n) -> … }` destroys `n` at the end of the enclosing scope under Stage 0, not at the arm's end. The arm binding owns the payload ("Match consumes an owned enum"), so its `deinit` belongs at the arm's end, where sawc2 runs it. A user enum with the same shape drops at the arm's end in both compilers. The repro is the Air's `e9_matchconsume.saw` (chat file f22), and the SL-513 ruling (B) puts the destruction of parts no arm binding takes at the match's completion (C11).

**Instead:** none needed in compiler source, which declares no `deinit` (checker rule `deinit-body`), so the timing is unobservable in Stage 1.

**Checker:** covered by `deinit-body`.

### C11. A part discarded by a consumed `match`, `if let` or `while let` dies at arm entry

**Shape (silent: wrong drop timing):** the SL-513 ruling (B, SL:open-questions) says a part no binding takes dies when the construct that took it completes: after the body for `match`, `if let` and `while let`. Stage 0 behaves differently:
- it destroys such a part at arm entry, before the body runs: `case Full(_) -> print("arm")` prints `drop 3`, then `arm`;
- the same goes for a `_` in `if let (x, _) = o { … }`;
- where a guard fails and falls through (`case Both(x, _) if …` and then `case Both(_, y)`), it destroys both parts at the enclosing scope's end, which is neither rule.

Stage 0's own suite pins arm entry deliberately, in `examples/coro_discarded_match_payload_field_drop_order.saw`, `coro_discarded_match_payload_released_at_extraction.saw`, `coro_mixed_match_payload_released_at_extraction.saw` and `discard_forms_release_matrix.saw`. Those test the frozen compiler; they are not the contract. The repros are the Air's `f2_min`, `d8_matchtime` (chat file f22) and `b_guard`, `b_iflet` (f23).

**Instead:** none needed in compiler source, which declares no `deinit` (checker rule `deinit-body`), so the timing is unobservable in Stage 1. A differential mismatch on these shapes is adjudicated against the ruling and annotated with this entry.

**Checker:** covered by `deinit-body`.

## Inventory

Each of the 82 issues the sweep flagged, plus the four promoted after the Air's review and eight found since, mapped to its entry. "Call" is this
ledger's reading. Where it differs from the sweep, Notes for the lead says why.

| Issue | Entry | Call |
|---|---|---|
| SL-5 | L9 Name collisions within a program | loud |
| SL-7 | L2 Closure literals and call syntax | loud |
| SL-13 | L1 Integer literal adoption | loud |
| SL-14 | L3 Module-qualified spellings | loud |
| SL-28 | L4 Optional and Result shaping | loud |
| SL-36 | L3 Module-qualified spellings | loud |
| SL-38 | L2 Closure literals and call syntax | loud |
| SL-41 | L2 Closure literals and call syntax | loud |
| SL-42 | L4 Optional and Result shaping | loud |
| SL-46 | L4 Optional and Result shaping | loud |
| SL-49 | S9 Type aliases | silent |
| SL-50 | S9 Type aliases | silent |
| SL-52 | S9 Type aliases | loud |
| SL-53 | L1 Integer literal adoption | loud |
| SL-56 | L1 Integer literal adoption | loud |
| SL-65 | L2 Closure literals and call syntax | loud |
| SL-70 | L1 Integer literal adoption | loud |
| SL-73 | L2 Closure literals and call syntax | loud |
| SL-74 | S3 Owned values around `try` and `catch` | loud |
| SL-75 | L1 Integer literal adoption | loud |
| SL-77 | S9 Type aliases | loud |
| SL-78 | L3 Module-qualified spellings | loud |
| SL-84 | L1 Integer literal adoption | loud |
| SL-96 | L9 Name collisions within a program | loud |
| SL-107 | L9 Name collisions within a program | loud (possibly fixed) |
| SL-111 | S4 Whole-call exclusivity | loud |
| SL-115 | L3 Module-qualified spellings | loud |
| SL-125 | L3 Module-qualified spellings | loud |
| SL-194 | L1 Integer literal adoption | loud |
| SL-199 | L3 Module-qualified spellings | loud |
| SL-240 | S3 Owned values around `try` and `catch` | silent, leak only |
| SL-284 | S4 Whole-call exclusivity | silent |
| SL-291 | L4 Optional and Result shaping | loud |
| SL-292 | L4 Optional and Result shaping | loud |
| SL-293 | L2 Closure literals and call syntax | loud |
| SL-294 | S4 Whole-call exclusivity | silent |
| SL-295 | S6 Function exits | loud |
| SL-298 | S6 Function exits | silent |
| SL-310 | L2 Closure literals and call syntax | loud |
| SL-348 | S3 Owned values around `try` and `catch` | silent, leak only |
| SL-352 | L2 Closure literals and call syntax | loud |
| SL-358 | L3 Module-qualified spellings | loud |
| SL-368 | S15 Methods called on an indexed element | silent |
| SL-383 | S9 Type aliases | loud |
| SL-384 | S9 Type aliases | loud |
| SL-390 | S19 Type walks bounded by a depth count | silent (promoted after review) |
| SL-404 | S23 An owned value consumed without a binding: comparison operands, interpolation segments, format arguments, or a head's receiver | silent, leak only (found in the compiler-skeleton review; widened by sawtracker's ST-64) |
| SL-427 | S3 and S23 The error around `try`/`catch`, and a cast operand in std | silent, leak only (found by sawtracker's ST-66; the std half fixed under a freeze exception) |
| SL-429 | S3 `try?` never releases the error it discards | silent, leak only (found in ST-69's review) |
| SL-430 | S3 A coroutine's propagating `try` leaks the error | silent, leak only (found in ST-69's review) |
| SL-656 | L29 A suspending default value: sawc2 charges the caller that leaves it out, and Stage 0 refuses both forms | loud (Stage 0 refuses at the call; no live instance) |
| SL-565 | S36 A spawn borrow released by joining a rebound handle variable | silent, a use-after-free (found by the Air reviewing SL-565.p1; no live instance: the compiler spawns no task) |
| SL-765 | S37 A detached thread that finishes after the detach drops no result | silent, a lost deinit and a leak (found by the Air reviewing SL-765.p3; no live instance: the compiler spawns no thread) |
| SL-649 | L33 A field read two struct hops away, bound by a `let`, with neither struct type named in the module | loud (Stage 0 reports an undefined variable; one marked instance in `compiler/typecheck/src/conform.saw`) |

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

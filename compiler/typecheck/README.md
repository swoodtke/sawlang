# compiler/typecheck: type checking

The typecheck stage of the self-hosted compiler, package `sawtypecheck` (epic
SL-398, unit 6b, SL-447). It reads resolve's program unchanged, arenas and
side tables, and produces side tables keyed by resolve's ids (SL:architecture
§3.0, §3.4). U6b1 built the signature half: every declaration's signature
program-wide, trait requirements, the conformance table, the member tables and
the Copy tiers, and the checks that need only those. U6b2 builds the body half:
every body typed against those signatures alone, with its conversions, calls,
places and transfers recorded. U6b3 builds the summaries bodies derive, solved
to a fixpoint over the call graph, and the checks that read them and the types.
`compiler/tests/typecheck/README.md` specifies the dump, the interner's key and
the position matrices.

```
typecheck/
  src/
    api.saw           typecheck_program and the record `sawc2 typecheck` prints
    program.saw       TcProgram: resolve's program and every table the phases fill
    model.saw         the records: signatures, generics, conformances, members,
                      tiers; a body's uses, adjustments and calls
    types.saw         the type interner
    spell.saw         a type's canonical spelling
    signatures.saw    generic parameter lists and the type funnel, `build_type`
    declarations.saw  one signature builder per declaration kind; the
                      accessor-signature reader; extension heads
    conform.saw       the conformance table: requirements, defaults, `@synthesize`,
                      agreement; substitution
    tier.saw          the Copy-tier classifier, containment, bound satisfaction
    members.saw       the member tables and a module's view of them
    overloads.saw     the declaration-site overload rule: a redeclaration no
                      call could tell apart, refused where it is written
    checks.saw        finite size, the signature half of `unsafe`, what an
                      `init` returns, `Deinit`'s conformances, where a
                      `deinit` is written, and a test-only conformance or
                      member overlapping what production code meets
    typeops.saw       the type questions a body asks: numbers, Optionals, Results
    adjust.saw        adjustment chains, conversions, and peeling
    candidates.saw    what a name or selector can mean: overload sets, members,
                      a bound's requirements
    infer.saw         call-site unification over one declaration's parameters
    bodies.saw        the body walk: statements, expressions, calls, patterns,
                      the expected-type funnel and the overload filter
    bodydump.saw      the dump's `bodies` section
    bodyverify.saw    the body verifier
    paths.saw         the per-path use count: whether a by-value read of a
                      generic body's local moves it or duplicates it
    summaries.saw     phase 2: bodies' units and items, the summaries, their
                      fixpoint, their dump text and their verifier
    stdsuspension.saw the std suspension table, written by
                      compiler/tools/std_suspension.py
    exports.saw       `@export`: each export's C symbol, and the export rules
    runtimeabi.saw    the runtime ABI table, written by
                      compiler/tools/runtime_table.py
    erasure.saw       object safety: the funnel every written `any Trait` reaches
    effects.saw       phase 3: the checks that read the summaries
    exhaust.saw       match exhaustiveness and duplicate arms
    arith.saw         typed integer arithmetic, the one rule every constant follows
    fold.saw          constant folding by typed arithmetic, for literal ranges, which
                      the MIR evaluator (compiler/eval) agrees with; the value a
                      literal or range pattern tests
    lang.saw          the lang items' shapes
    strings.saw       the String positions and their funnel
    bodychecks.saw    borrowing-struct containment, a static's type, the body
                      half of `unsafe`, the `borrows(sync)` window
    mutability.saw    the writability funnel: whether each place a body writes
                      or borrows exclusively may be written
    binders.saw       what each binding construct makes of its names, which the
                      funnel and the hints that propose a write both read
    refpositions.saw  references are parameters only: the funnel over written
                      type positions, and the inferred ones
    dump.saw          the dump
    verify.saw        the verifier
    walks.saw         the memo table the semantic walks key by TypeId or
                      declaration, and their question tags
```

## The semantic walks

A question about a type or a declaration is answered by a walk keyed by
identity, never by a count of how deep it went (SL:architecture principle 6):
a type is interned before every type that holds it, so a walk over a type's
parts ends, and one over declarations ends by an in-progress mark. Each walk
memoizes by TypeId, program-wide in `TcProgram.walks` where the answer is
final, or for the one call where it is not:

- **The inline walks** (`tier.saw`): `is_no_move`, `is_cell_carrying` and
  `is_trivial` share one summary per type, a declaration's rule over its own
  parameters joined with its arguments', so no walk substitutes into a member.
  A declaration met while its own rule is built holds itself inline, which the
  finite-size check refuses.
- **Bound satisfaction** (`satisfies`): one run per question, each (type,
  trait) pair once. A derivation that reaches back to a pair it is still
  deciding holds there, as a recursive type's `Send` does through its
  `Vector`. A false answer is final. A true one that leaned on an open frame
  below its own is reused while that frame is open, and every pair decided
  inside a frame settles when it does: final once the cycle's root holds,
  forgotten when a frame they may have leaned on fails, else leaning on the
  lowest frame reached. Deriving `Send` or `Sync` from the members of a type
  nested past the instantiation depth, which only a type that holds itself at
  ever larger arguments reaches, is refused as `type.instantiation-depth`.
  A run is asked by some code, its module and whether it is test code, and
  reads only the conformances that code may use (`conformance_visible`): a
  test-only one exists for its own module's test code alone (SL:testing).
- **Finite size** (`checks.saw`): each struct and enum's inline mask, the
  parameters it holds inline, solved to a fixpoint; an edge to each
  declaration it holds inline; and the strongly connected components of those
  edges. A declaration on a cycle is refused, with the shortest path from its
  storage to an instance of itself.
- **Structural questions**: `names_self_type`, `type_holds`, `nesting_depth`,
  `unsafe_named`, `type_tier`, `decl_owns`, `export_data_ok`, what a type's
  parts name for the reference-position funnel (`reference_part`),
  `copies_silently`, and a condition's evaluation (`eval_condition`), which
  follows each (receiver, requirement) pair once.
- **What a type holds** (`types.saw`): the interner records, per type, whether
  an error type or a type parameter or `Self` stands anywhere in it, joined
  from its parts once. `has_error` and `mentions_param` read it, `subst`
  returns a type holding no parameter unchanged, and the walks below skip
  such a type.
- **One call's walks**: `mentions_owner`, `mentions_unsolved`, `open_tier`,
  `mentions_unseen_param`, `borrowing_named`, `copy_needs`, `unify` and
  `peel` depend on more than the type, so each keeps, for its one call, the
  answer for each branching part it has finished (`TcTypes.branches`): only a
  type with two parts or more multiplies the paths to its parts.

## Phases

`typecheck_program` resolves the entry's program, then:

1. **Generic parameters** (`signatures.saw`). Each generic parameter is keyed
   by the leaf it is declared at, to its declaration and index. An
   extension's parameters rename those of the type it extends, so they are
   keyed as the type's. Each type's extensions are indexed.
2. **Signatures** (`declarations.saw`), modules in load order and
   declarations in source order, std and builtin modules as interfaces. A
   declaration's generic parameters are built lazily, since a signature may
   name a type declared later. Every type position goes through
   `build_type`, which reads resolve's binding on a path's last segment and
   never a spelling. A bound on a written type argument is recorded as an
   obligation, checked once the conformance table exists.
3. **The conformance table** (`conform.saw`): each conformance resolve
   recorded, then how each requirement of its trait and the traits it refines
   is met, against the members written in the extensions the conformance's
   module sees. A production conformance is met as if no test-only
   declaration existed; the test-only ones are settled after, and take a
   production conformance's answer for each requirement it also reaches. A
   test-only conformance's associated type agrees with a production
   conformance's that reaches the same trait, and `project` reads a
   production conformance's first.
   A type declares one copy policy, so a conformance to a
   second of `Copy`, `ExplicitCopy` and `NoCopy` is refused
   (`check_copy_policies`), and so is a `copy()` a type that is not
   `NoCopy` writes outside its policy (`check_copy_placement`). Then every
   overload set, a module's free functions of one name, the methods of one
   name and the `init`s a module's extensions give a type, and a trait's
   requirements of one name, goes through one funnel,
   `refuse_indistinguishable` (`overloads.saw`), which refuses a declaration
   sharing a call shape with an earlier one: the same labels and types,
   aliases read as their targets and every type parameter as one
   placeholder, a defaulted parameter's shorter calls counted, an `init`'s
   labels in any order. Beside it, `check_construction_inits` judges each
   `init` against its struct's memberwise construction: one matching the
   fields exactly overrides it, where only the struct's module, in
   production code and an unbounded extension, may write one, and any other
   sharing its call shape is refused (SL-648). The body half's construction
   funnel, `construction_route`, reads the same predicates for a call's
   candidates and for a zero-initialized static's value.
4. **Member tables** (`members.saw`), one per struct, enum and builtin type.
   What production conformances bring joins a table before what test-only
   ones do, so ordinary code sees it whatever the declaration order.
5. **Copy tiers** (`tier.saw`), one per nominal type.
6. **The checks** that need the tables: a test-only conformance overlapping
   a production one, a test-only member meeting a requirement a production
   conformance meets, bounds, Copy-policy containment,
   `NoMove`'s declared containment and the `NoCopy` it requires, finite size, the signature half of `unsafe`, what an `init` returns, the
   conformances `Deinit` refuses, and a `deinit` written outside the copy
   policy.
7. **Bodies** (`bodies.saw`), each module checked in full, declarations in
   source order: a function's parameter defaults and block, a static's
   initializer, a raw case's value, an `@align` argument, then the file's
   `static_assert`s and test cases. Each body is checked against signatures
   only, so no body reads another. Then **object safety** (`erasure.saw`):
   every written `any Trait`, a signature's or a body's, is judged by one
   funnel, `check_object_safety`, and refused where it is written when its
   trait is not object-safe (spec, "Object safety (v1)").
8. **Places** (`settle_places`): once every body is checked, each subscript's
   role and each `borrows` accessor's receiver borrow is read off the use its
   position recorded (SL:borrowing §5, design 141), and a plain subscript
   read where its position keeps nothing is held to the getitem it is, so its
   element copies (D29). Then each closure's
   captures (`settle_captures`): the bindings its capture list writes and its
   body names from outside it, each with its transfer, and the refusals of a
   capture that does not copy silently and of a borrow of the enclosing frame
   in a closure that escapes.
9. **Mutability** (`mutability.saw`): every place a use writes (an
   assignment, a compound assignment) or borrows exclusively (`&var`, a
   `&var self` receiver, `borrow var` in each form, an exclusive lend,
   `[&var x]`) is walked to its root by one funnel, `place_verdict`, whose
   docstring names its entry points. Bindings always initialize, so the root decides: a `var`
   is written, a `let`, a pattern's, a `for` loop's or a closure parameter's
   binding, a parameter taken by value and a plain `static` are not; a
   reference along the path decides by its own `&` or `&var`; `self` by its
   receiver; a binding a closure captured, by the capture: a by-value,
   `move` or `copy` capture is judged exactly as a `let` of its type, in
   every closure (SL-472). A raw pointer's pointee is always written. A
   bare `borrow` statement lends its place shared, so a write through it is
   refused whatever the root (SL-487). Then **escaping consumes**
   (`captures.saw`): a consuming use of a by-value capture inside a closure
   that escapes is refused (SL-469). A `move` that takes a part of a binding is
   refused as the body is walked (`transfer.partial-move`), and so is one of
   a binding that owns nothing, a reference or a pattern's binding aliasing a
   borrowed scrutinee (`transfer.move-from-borrow`). Then **reference
   positions** (`refpositions.saw`): each outermost type a module checked in
   full writes is judged by the position its parent gives it, through one
   funnel, `reference_position_of`, whose docstring names the positions; a
   parameter may be a reference, a `borrows` lend may lend one, a borrowing
   struct's field may hold a shared one, and no other position may name one
   at any depth. Then a bare `&` outside a call argument or a pointer cast, a
   binding whose inferred type names a reference, and a call instantiated at
   one. A closure's inferred result is judged as the closure is walked.
10. **Exhaustiveness** (`exhaust.saw`): every `match`'s unguarded arms
   against its scrutinee's type, as the usefulness of a wildcard row over the
   pattern matrix, which names each missing value; and an unguarded arm that
   repeats an earlier one, its literals compared by the value they test
   (`pattern_value`), never by their spelling. A discarded `Result` is
   refused as the body is walked (design 151).
11. **Path uses** (`paths.saw`, design 219): each by-value read of a local
    whose type names one of the function's own type parameters, which the
    walk recorded as a copy, is settled over the body's paths (below): a move
    when no path uses the local again, a copy otherwise.
12. **Summaries** (`summaries.saw`, SL:architecture §3.4 "Order" phase 2):
   every function's may-suspend, sync-callable and inferred Copy requirement,
   one worklist over the call graph to the least fixpoint (below).
13. **Effect checks** (`effects.saw`, phase 3): a `sync` body calls only
    sync-callable targets, each call site meets its callee's Copy requirement,
    no closure body suspends, and no coercion to `any Trait` dispatches to a
    suspending implementation.
14. **Body rules** (`bodychecks.saw`): borrowing-struct containment, a
    static's type (never optional, and `Sync` unless it is an `unsafe static
    var`), a raw-backed enum's backing and its cases' values, stated and
    distinct by their folded values, the body half of `unsafe`, and the
    `borrows(sync)` window, which
    reads the summaries. A `consumes` call's `move` and `move self`'s `consumes` body
    are checked as the body is walked.
15. **Exports** (`exports.saw`, the export funnel `tc_check_exports`): each
    `@export`ed function and static of a module checked in full has its C
    symbol recorded by declaration (`export_symbols`), which mono roots and
    the backend defines. Its signature takes and returns only what C passes,
    no generic is exported, no symbol twice, and none may suspend, by its
    summary. `main`, `saw_*` and `__saw_*` are reserved, except that a
    runtime (`runtime_build`, set by `sawc2 runtime` and `typecheck
    --runtime`) defines the frozen seams it owns, each against the ABI table
    `runtimeabi.saw`: its arity and every width class.

## Constants

Typecheck needs a constant's value before any MIR exists, to range-check a
literal or a constant expression where it adopts an integer slot
(SL:architecture §3.10, "the one exception to the staged order"), so
`fold.saw` folds over the tree. It follows the evaluator's rule, typed
arithmetic (`arith.saw`, ruled Sep 25): each literal is written at the type
it adopts, each operation runs at its operands' type at the target's width,
and an overflow, an out-of-range shift or a division by zero is a refusal,
where design 185 folded in the signed `Int` domain. So `1 << 63` at `UInt64`
is 2^63, `~(0 as UInt)` is `UInt.max`, and `256 - 1` at `UInt8` is refused,
since `256` does not fit there. The MIR evaluator (`compiler/eval`) computes
every constant position's value from MIR through the same arithmetic, and the
eval lane holds the two to agreement. Retiring this fold in favour of lowering
a constant expression to MIR on demand is a later unit's.

## The summaries

A body is split into units, the function's own and one per closure in it,
and each unit's items are its calls, its copies of a place and its coercions
to an existential. A function's summary (the dump's `(summary ...)`) is:

- **may-suspend**: `yes`, `no`, or a condition, the requirements called
  through its own type parameters (or, in a trait's default body, `Self`)
  that are not declared `sync`: `run<T: Worker>` may suspend when `T`'s
  `Worker.step` does. A call site substitutes its type arguments and
  evaluates it: a concrete type's implementation answers, a caller's own
  parameter composes into the caller's condition.
- **sync-callable**, carried apart: a call through a function value, or to a
  requirement through `any`, never suspends and is sync-callable only when its
  type or requirement says `sync`.
- **the Copy requirement** (design 219): the type parameters the body copies
  with nothing written, directly or through a callee that requires it. A copy
  is a read out of storage the body does not own (a field, an element, a
  payload), or a read of a local some path uses again (below).
- **refuses-when**: the conditions under which an instantiation would put a
  suspending call in a closure body, dispatch through `any` to a suspending
  implementation, or call what is not sync-callable in a `sync` body; the
  call site that makes one true is refused.

A closure's calls are not its function's: they add nothing to its suspension,
and what would make one suspend becomes a `refuses-when` condition. Nor are a
parameter's default's: the caller evaluates a default (LANGUAGE_SPEC,
"Default parameter values"), so each default value has a summary of its own,
solved beside its function's, which a call that leaves the argument out adds
to the body it is in (`eval_call`), and the function's summary leaves it out.
A bodyless requirement's unit holds only its defaults. Every
summary starts at the bottom and only grows, so the worklist, in declaration
order, reaches the least fixpoint however recursion cycles.

**Std's summaries come from a table.** Std is read as interfaces and no std
body is checked, so an interface function's summary is its row of
`compiler/tools/std_suspension.txt`: the frozen compiler's own std check,
observed once by `compiler/tools/std_suspension.py`, and the one suspension
analysis it runs over std's effect graph. A function declared `sync`, and an
extern (by its `blocking`), are summarized by their declaration. A std function
with no row is taken as suspending, with a `summary.untabled` NOTE naming it.
The table is replaced by real inference when the new std's bodies are
checked; `run.py` fails when it no longer matches a fresh observation, and
the verifier when a row names no std function.

## The body half

Every result is a side table keyed by node id; the tree is never written
(SL:architecture §3.0). Per expression: its own type, its adjustment chain
(each step a conversion with the type it produces), whether it is a place,
and how its position uses it: a transfer (`move`, `copy`, `temp`) for a value
use, a borrow, a projection, a write or a test otherwise. Per call, operator,
subscript, `for` and pattern case: its target declaration, the type a member
is instantiated at, and its own type arguments.

- **The expected-type funnel** is `expect`, and its docstring lists its entry
  points, one per literal-adoption position of SL:architecture §3.4. A
  literal, a constant expression, an implicit member and a construction take
  the slot as `peel` finds it; any other expression is typed with the slot as
  a hint and converted by `coerce`, within what the position allows: its
  optional wrap depth, its Result wrap, whether it builds the error box and
  whether it widens an integer (`allowance`, the wrap and erasure matrix of
  the corpus README). Conditions,
  whose literal would be an error anyway, are checked apart.
- **The overload filter** is `filter_candidates`: labels and arity first
  (`bind_args`, design 66's ordered binding, or name matching for a
  construction), then types, where an argument that takes its type from its
  position fits by its shape. A concrete candidate beats a generic one, a
  unique best wins by per-argument dominance (exact over adoption over
  conversion), and anything else is refused naming every candidate.
- **Inference** (`check_candidate`) unifies each argument that types itself
  against its parameter, pass by pass until nothing more is solved (design
  105's later-argument fixpoint); a literal or closure left over types itself
  after that, and `None` or an implicit member last. An unsolved parameter
  takes its default or is refused; each solution meets its bounds.
- **Places and transfers.** A local, `self`, a field or element of a place, a
  payload `o!` of a place, a subscript and a `borrows` accessor's lend are
  places. A position that takes a value copies a place, which only a type of
  the Copy tier does silently (design 131), or hands off a temporary. A
  generic body's read of a local of its own type parameter's type is settled
  per path by phase 11, and recorded as `move` when no path uses the local
  after it.

## The per-path use count

The rule is per path, not per mention (spec, design 219): a local read by
value at most once on every path is moved by that read, and so owes no Copy
requirement. `settle_path_uses` is the one place that decides it. It tracks
each local, a parameter, a `let` or `var`, a pattern's binding, whose type
names a type parameter of the function not bounded by Copy, and walks the
body's control structure with one state per path:

- a branch takes the most any one alternative uses: the arms of an `if` and
  a `match`, and the right side of `&&`, `||` and `??`, which a path may
  skip; a `match` guard that fails passes its path on to the later arms;
- a loop's body and a closure's body are walked twice, since each may run
  again, so a by-value read of an outer local there is a duplicate;
- a `return` ends its path, a `break` carries its path past the loop and a
  `continue` to its head, and a closure's `return` or `?` carries its path
  out of the closure; an expression of type `Never` ends its path;
- a propagating `try` in a `try` block's body carries its path to the catch
  block, which runs on every such path, and past the block the body's end
  and the catch block's join; an inline catch's catch block is a branch
  after its operand;
- a spelled `move x` ends `x` on its path, and an assignment `x = v` gives it
  a new value;
- a borrow (`&x`, a receiver, a format argument, a comparison operand) is no
  by-value use, but any use after a by-value read duplicates the value, since
  the read had to leave it in place.

A local no path uses again has each by-value read recorded as `move`. One
that some path does keeps its reads as `copy`, one of which carries the
requirement, and the refusal at a call quotes both uses (`copy_partner`); a
loop's or a closure's single read is quoted alone. A binding that aliases a
borrowed place, and a read through a reference, copy out of storage the body
does not own and are not tracked.

## Body readings

These are the reversible readings U6b2 made; SL-447's report lists them.

- A std module's extensions of a type the synthetic builtin module holds
  (`String`, `Int`) count as the type's defining module's, so they are seen
  with no import, as std is where those types' methods are written.
- A `match` on an owned local whose type is not Copy consumes it, and each
  binding takes its part (spec, "Match consumes an owned enum"); a match on
  any other place borrows, and its bindings alias their parts; `if let` on a
  place copies the payload out (design 131). The consumed scrutinee's use is
  recorded as `move`.
- Today's std declares only a place accessor for `Vector.[]`, with a `&var
  self` receiver. A value read of `v[i]` is a getitem derived from it, and a
  write a derived setitem, though SL:borrowing §5.2 derives getitem only from
  a `&self` accessor, which the new std will add.
- A `borrows` accessor's receiver is borrowed exclusively when the use its
  place's projection ends in writes (an assignment, a compound assignment, an
  exclusive borrow), or when the accessor takes `&var self` and declares no
  shared twin ("Safety readings"), and shared otherwise.
- `T.from(x)`, `T.from(truncating: x)` on an integer and `A(x)` for a
  distinct alias of a builtin type are conversions no declaration writes
  (designs 170 and 250); `E.from(raw:)` is a member-table row of every
  raw-backed enum. An Optional's `take`, `is_some` and `is_none` (design
  131), `copy()` on a type of the Copy or ExplicitCopy tier that declares
  none, and an array's `len` and `swap` are builtin methods, found only when
  the type's members have no method of that name.
- A `borrows` body lends rather than returns, so it is checked as statements;
  a `return` in it expects the lent place's type, `None` for a conditional
  lend's absent path.
- A `Result<Void, E>` body that ends in a statement, and a bare `return` in
  one, give its `Ok`.
- The new std's atomic intrinsics (SL:open-questions D23) are typed as Stage
  0's synthesized helpers of their names: `__saw_atomic_add_i64` and
  `__saw_atomic_sub_i64_release` take an `UnsafePointer<Int>` and an `Int`
  delta and return the old value, `__saw_atomic_load_i64_relaxed` takes an
  `UnsafePointer<Int>` and returns the word (D24), and
  `__saw_atomic_fence_acquire` takes nothing. A plain load is an ordinary
  read through a pointer.
- A documented enum case's doc comment is a child of its node, and no raw
  value.
- sawc2 takes no target yet, so the platform pair, `Int` and `UInt`, is read
  as 64 bits wide when a widening's losslessness is judged: `Int64` into `Int`
  widens, as on the hosted targets.
- A bare module static keeps its declared type in a slot, as the frozen
  compiler has it, and adopts only as a mixed operator's peer or inside a
  constant expression.
- A call whose signature names a type the program could not form, because
  the std module that declares it does not parse, is refused as
  `slice.not-yet` at the call, so the gap is named where it is met. Every std
  module parses today, so nothing reaches it.
- A call whose target's signature carries a type another module's refusal
  left unformed poisons the body (SL:architecture §3.0): its error types are
  that refusal's, and the verifier asks nothing of them.
- A closure escapes unless it is written straight as a call's argument whose
  parameter is a function type that does not say `escaping`; a function
  value's parameter counts too. Binding it to a `let` escapes (spec,
  Capturing `self` and reference parameters).
- An implicit capture of `self` borrows as the enclosing method's receiver
  declares, shared or exclusive, as `[&self]` and `[&var self]` would; a
  consuming method's `self` is owned, and captured by value. A reference
  parameter's capture copies its reference, which borrows the frame.
- A closure's captures are its capture list's entries, in order, then the
  enclosing bindings its body names, in the order it first names them; a
  nested closure's names count for every closure around it that they lie
  outside of.

## Summary readings

These are the reversible readings U6b3 made; SL-447's report lists them.

- The inferred Copy requirement is counted per path ("The per-path use
  count"): a by-value read of a local whose type names one of the function's
  type parameters is a move when no path uses the local after it, and a copy
  otherwise; a read out of a field, an element or a payload is always a copy
  (SL:borrowing, "if it looks like a copy, then just copy"). A parameter whose
  bounds declare `Copy` owes nothing further.
- A use of any kind after a by-value read on one path, a borrow included,
  makes the read a copy, as the spec's second bind does: the read left the
  value in place for it.
- A loop's body counts twice whatever `break` it holds, and a closure's body
  twice, since nothing says a closure runs once.
- An `if let` or `match` binding taken out of a place is a payload read, and
  so a copy; a `match` on a local of a type parameter's type binds by copy,
  as a type that copies silently does.
- An assignment `x = v` gives a `var` a new value, so a read before it and one
  after it are each the only read of their value.
- A `sync` body inside a generic function (a `sync` function, a `deinit`, a
  closure of a `sync` type) that calls a requirement through a bound not
  declared `sync` is judged per instantiation, as a closure that would suspend
  through a bound is: the condition joins the function's `refuses-when`, and
  the call whose type arguments make it false is refused, naming the
  instantiation. A call that is not sync-callable for every type argument is
  refused at the definition.
- A `deinit` body is a `sync` context (spec: suspension, "`deinit` may not
  suspend").
- A `borrows(sync)` window, the block of a `borrow` or a `for` whose head calls
  such an accessor, refuses a call that may suspend for some type argument at
  its definition, as a `sync` body does; the statement form of `borrow` is not
  checked yet.
- Borrowing-struct containment follows SL:borrowing's lifted refusals: a
  `borrow` head may bind one, a reference parameter (`&It`, `&var It`) passes
  a bound one onward, and `&var` fields are allowed. The signature positions
  are checked in modules checked in full; std declares its iterators and
  their `borrows` accessors.
- A member written to meet a requirement is visible wherever its trait's
  visibility reaches, beside its own visibility, which it only widens.
- A struct or enum owns something when a field or payload holds a `String`, a
  type parameter, a function value, an existential, or an owning struct or
  enum, a raw pointer owning nothing; one that owns something and writes no
  `deinit` gets a synthesized one in its member table, the requirement of
  `Deinit` as its declaration.
- A construction's partial prefix of type arguments is completed by inference
  only when no `init` the module sees has type parameters of its own, which
  the prefix could be mistaken for; with one, a short prefix stays
  `type.arity`.
- The body half of `unsafe` looks at every typed node of a function's bodies,
  its parameter defaults and closures included, each node's type and every
  step of its adjustment chain, and names the first.
- An interface generic function gets no condition over its type parameters,
  since its body is not read: its table row holds for every instantiation.
  That is weaker than a bound call's condition, and it retires with the table.
- The std table's rows come from the frozen compiler's std check, keyed as
  sawc2 names each declaration the source writes; the methods that check
  synthesizes (a policy's `deinit`, a default copied into a conformer, a place
  accessor's twin) have no row, and a place accessor's lowered window
  parameters are left out of its key.
- The table's module cross-check derives the parking modules from the
  cooperative intrinsics a body spells, not from the executor's own
  `__saw_exec_*` helpers: those serve the `sync` drive loop, and
  `std.taskgroup`, which declares them, holds no suspending function.
- `effect.any-suspends` refuses a suspending implementation where it is
  coerced to `any Trait`, not where it is dispatched: the coercion is the site
  a modular checker sees, since the dispatch may sit in another module
  (SL:open-questions D21). Stage 0 refuses at the dispatch, so a coercion
  never dispatched is accepted there and refused here.
- Exhaustiveness reasons over closed types at any depth: `Bool` and enum
  constructors split inside tuples and payloads, so `(true, true)`,
  `(true, false)` and `(false, _)` cover `(Bool, Bool)` (D21). Only an open
  type, an integer or a `String`, needs a wildcard or a binding.

The declarations typecheck knows by identity are found once (`find_known`):
`Optional` (for `T?`, which no name occurrence spells), `Result`, `String`,
the Copy family, the derivable traits, the panic sink, the interior cell and
`Atomic` from resolve's lang-item table (resolve/README.md), and the
primitives and the unsafe pointers from the builtin module. That is a table of the stage's
own vocabulary, not a lookup of a name the program wrote. `lang.saw` holds
each lang item a source declares to its role's shape, its cases and payload
labels, its requirements and their signatures, its fields, conformances and
the methods its module writes, and refuses a difference as `lang.shape`,
naming the first part that differs. The expected shapes are Stage 0's
`builtin.saw`, so every lane over `sawc/` checks the table against it. The
String layer's two types, `String` and `StringBuilder`, carry an API beyond
what the compiler calls, so their shapes are sets of parts each must hold:
String's single field, its Copy conformance with the retain and release
hooks, and its other conformances; the builder's fixed-mode `init`,
`append(s:)`, `append(value:)`, `build` and its policy. So are the cell's and
`Atomic`'s: the type parameter, the one field `value`, and the policies, the
cell's `NoCopy` and `Atomic`'s `UnsafeSync` and `NoCopy`, whose operations the
new std writes over the `Int` word where Stage 0's types them over `T`. A `lang.shape` refusal
is listed before the refusals the checks ahead of it made, since a slip in a
lang item explains them. An Optional the new std declares writes its own
`take`, `is_some` and `is_none`, so typecheck answers those names builtin only
for Stage 0's synthesized one, and a lang item prints by its bare name, as a
builtin does, under either std; so does `String`, from `std.string`.

## The String positions

The compiler makes or reads a String itself, with no call written, at a fixed
set of positions, and each lowers through a lang item (SL-456). The body walk
records each through one funnel, `string_position` in `strings.saw`, whose
docstring lists its entry points; the body verifier requires a position for
every literal, interpolation, source location, string-literal pattern,
builtin comparison of Strings, and `panic` and `assert` call, so a position
that bypassed the funnel is an invariant rather than a silent fallback to a
builtin. Under the new std the module dump ends with `(string-positions (L:C
POSITION DECLARATION) ...)`, the declaration each lowers through; under Stage
0's std, whose compiler synthesizes those, nothing is printed.

| position | where | lowers through | pinned by |
|---|---|---|---|
| `literal` | a string literal | `std.string.string_literal`, over its immortal static block | std lang `string_positions` |
| `source-location` | `#file`, `#function` | `std.string.string_literal` | std lang `string_positions` |
| `interpolation` | `"{x}"`, a message or not | `std.stringbuilder.StringBuilder`: `init`, `append`, `build` | std lang `string_positions`, cone `interpolation` |
| `message` | a literal message of `print`, `panic`, `assert` with no format arguments | `std.string.string_literal`: its bytes go out as they are | std lang `string_positions`, cone `literal_only` |
| `format` | a format string with `{}` slots (design 137) | `std.stringbuilder.StringBuilder`'s fixed mode, in stack scratch | std lang `string_positions` |
| `argument` | a String format argument, or a String message | `std.string.string_bytes` and `std.string.string_length`, its bytes and their count | std lang `string_positions` |
| `rendered` | a message that is a Printable value off the builtin fast path | `std.prelude.Printable`'s `to_string` default | std lang `string_positions` |
| `pattern` | `case "zero" ->` | `std.string.string_equals` | std lang `string_positions` |
| `equality` | `==`, `!=` on Strings | `std.string.string_equals` | std lang `string_positions` |
| `ordering` | `<`, `<=`, `>`, `>=` on Strings | `std.string.string_compare` | std lang `string_positions` |
| `panic` | `panic`, `assert` | `std.panic.panic_sink`, the message's bytes and length | std lang `string_positions` |

Copying a String and dropping one are not positions: the new std's String
writes its retain and release hooks in its Copy conformance, so MIR calls
`String.copy()` where a transfer copies, as for any type with a written hook,
and its `deinit` where one drops (the std lane's `mir/string_refcount.mir`).

## Readings

These are the reversible readings this unit made; SL-447's report lists them.

- A declared copy policy is uniform over the arguments, as the frozen
  compiler has it: `Vector<T, A>` is ExplicitCopy for every `T`, though its
  conformance holds only where `T: ExplicitCopy`. An undeclared generic
  type's tier is a rule over its arguments.
- A shared or exclusive reference, a slice, a function value and a raw
  pointer are Copy; `any Trait` on its own is NoCopy. An interior cell field
  contributes its payload's tier, and an undeclared type's member reaching
  back to a type being classified adds nothing.
- The Copy-containment rule for a field of a declared Copy type, a retain
  hook, applies to a struct's field of that type or an array of it, as the
  frozen compiler applies it, not to a tuple, an optional or an enum's
  payload.
- A bound is satisfied through a conformance to the trait or to one refining
  it, with the conformance's conditions checked against the arguments. Copy
  and ExplicitCopy are answered by the tier; Equatable and Hashable also by
  the automatic conformance of a trivially copyable type; Send and Sync from
  the members, except that the interior cell itself derives no Sync, so a type
  holding one directly is Sync only by a declared `UnsafeSync` (spec,
  Interior mutability); the numbers, `Bool` and `String` meet the value traits
  builtin, and the raw pointers only ExplicitCopy and Equatable.
- A requirement's parents count: a conformance to `Error` is met by a
  `format` written for `Printable`, and a conformance to `NoCopy` or
  `ExplicitCopy` owes `Deinit`'s `deinit`, which is implicit. A requirement
  is met by a member of the type written in an extension the conformance's
  module sees, not only in the conformance's own extension.
- Signature agreement compares receiver, staticness, the number of type
  parameters, parameter names and types, and the result, after `Self` and
  the associated types become the conformance's; an `unsafe` requirement
  needs an `unsafe` member (design 188), and `borrows` follows SL:borrowing
  §2.5. A `sync` requirement met by a member not declared `sync` holds when
  the member's summary makes it sync-callable, which phase 3 checks.
- A trait requirement with generic parameters of its own is refused once, at
  the requirement, as `trait.generic-requirement`: the grammar parses the form
  and type checking refuses it for now (GRAMMAR §3.4). Its signature is still
  built whole, so a generic member meeting it, its default body and a call
  through a bound add no refusal, and a dispatch through `any` leaves it out
  of the requirements it judges.
- An extern has no effect slot, so the signature half of `unsafe` asks
  nothing of it. A default parameter value is an expression, which U6b3's
  body half checks.
- `()` is the empty tuple, a type of its own beside `Void`.
- A projection, `T.Item`, is keyed by its associated type, its trait and its
  base (tests/typecheck/README.md, the interner's key). No bound can say a
  projection copies or meets a trait, so it is NoCopy, satisfies no bound,
  and a generic body moves it with `move`, as it would a NoCopy value; a
  struct holding one declares its policy. A trait's own associated type is
  the projection on its `Self`, with the same reading, so a default body
  moves or borrows it too (SL-458).
- A hand-written `deinit` is refused outside an extension declaring the
  type's copy policy (`Copy`, or a trait refining `Deinit`), since none
  would call it at a scope's end (spec, The Deinit trait).
- A slot holding a type already refused is poisoned: what is checked against
  it, a `None`, an implicit member, an empty literal, adopts the error type
  rather than refusing again (SL:architecture §3.0).
- A constant argument folds when it is a literal, a const parameter, or `+`,
  `-` and `*` over literals; a static, and arithmetic over a const parameter,
  are outside the slice.
- `T??` is two nested optional nodes in the tree, each one layer.
- An extension's parameters restate the type's defaults; a restated default
  is typed but not compared with the type's.
- An extension head's parameter that names a type where the head is written
  (the module's, a selective import's, the prelude's) makes the head a
  specialized extension, `slice.not-yet`, whatever else it omits; a pure
  rename that leaves out a defaulted parameter is refused with the head
  written out (SL:open-questions D14); a rename missing an undefaulted one is
  `type.arity`.
- A literal or range pattern's integer adopts the matched type whole, as a
  bare literal adopts its slot, so `case 300` on a `UInt8` and `case -1` on
  an unsigned type are refused as not fitting it, the spec's rule for every
  literal. Stage 0 accepts both and truncates at run time, so `case 300`
  matches 44 there (SL-609).
- A bare integer literal at an overloaded call prefers a parameter of type
  `Int`, and is otherwise ambiguous among the integer overloads it fits
  (spec, Overloading, tie-break 4; SL-615): `h(5)` over `h(Int)`/`h(Int8)`
  and `report(65)` over `report(value: Int)`/`report(byte: UInt8)` pick
  `Int`, and `h(5)` over `h(Int8)`/`h(UInt8)` is `call.ambiguous`. Stage 0
  refuses the first two as ambiguous. The preference is judged per argument,
  so `h(1, 2)` over `h(Int, Int8)`/`h(Int8, Int)` is ambiguous too. An
  optional parameter is a wrap, not an `Int` overload: `h(5)` over
  `h(Int?)`/`h(Int8)` picks `Int8` by tie-break 1, and over
  `h(Int?)`/`h(Int8?)` is ambiguous, where Stage 0 types the literal `Int`
  before choosing and picks `Int?`. A literal fits an integer type by type,
  its value checked once the overload is chosen, as for a `Result`'s two
  payloads, so `h(300)` over `h(Int8)`/`h(Int16)` is ambiguous rather than
  `Int16`, as in Stage 0.
- A redeclaration is judged per overload set and per module (SL-641). A
  static and an instance method of one name share a set, as in Stage 0, so
  `total(&self)` beside `static total()` is refused though their call forms
  differ; a test-only declaration shares its production twin's set; a
  trait's requirements are a set, where Stage 0 accepts two equal ones. Every
  type parameter folds to one placeholder at any depth, so `h<T>(v: T?)`
  beside `h<U>(v: U?)` and two extensions renaming the type's parameter
  collide, which Stage 0 accepts, since it folds only a bare parameter of the
  function's own. A function's shapes are the spec's prefixes, so a labeled
  call skipping a middle defaulted parameter (`f(x:z:)` over `f(x:y:z:)` with
  defaults beside `f(x:z:)`) stays a call-site ambiguity in both compilers.
  An `init`'s shapes compare as label sets, since its arguments bind by name;
  Stage 0 keys an `init` by its labels in order and ignores their types. A
  `borrows` member never shares a set with a plain one, and two whose
  receivers differ are the shared and exclusive twins (SL:borrowing §4). The
  memberwise construction is outside the sets (SL-648).
- A member named `copy` is a Copy or ExplicitCopy type's stray `copy()`
  (`copy.outside-policy`) when a call with no arguments reaches it: a static
  one and one whose parameters all have defaults count, one that takes an
  argument no default fills does not. A generic type that declares no policy
  counts as Copy by its members, since some instantiation is.

## Safety readings

These are the reversible readings SL-462 made; its report lists them.

- `&self` is read-only all the way down (SL:borrowing §9, SL-483): a write
  through a `Vector` field's buffer is refused from `self` under `&self` and
  from a `[&self]` capture, as from any other root that does not write. A
  raw pointer's pointee is written whatever holds the pointer (SL:open-questions
  D28), and so is a place a `&self` accessor lends, since its receiver is only
  read and its own `lend` was judged in its body (SL:borrowing §3); Stage 0
  accepts the heap writes design 200 allowed.
- A `&self` `borrows` body is a `&self` method: it writes no window it opens
  on `self`'s own storage (conformance row M33), since its callers borrow the
  root shared. An accessor that takes `&var self` and declares no shared twin
  (`@synthesize(shared)` or a `&self` overload) borrows its receiver
  exclusively at every use, a read included, so its root must be writable:
  a read through it on a `let` root is refused (SL:borrowing §3). The
  receiver decides this, not the lend, so a cell-carrying `(&self) borrows
  -> &var T` serves a `let` root, though the borrow check charges its root
  exclusively for overlap; the two are separate facts, and agree on every
  other declaration. Stage 0's std predates declared modes, so its accessors
  serve both, as the borrow check also reads them.
- A write through a subscript whose accessor lends read-only stays
  `subscript.role`'s refusal; through a named accessor it is
  `mutability.immutable`. `&var r` through a shared reference is
  `mutability.immutable`, not `type.not-a-place`.
- A reference read through a binding gives the referent's value at every
  position that builds or passes a value, copied out as any place read is
  (spec, Reference Semantics; `read_value`, whose docstring names the
  positions): `let a = p` over `p: &Int` is an `Int`, `(p, 1)` an `(Int,
  Int)`, `{ e in e }` over a `&T` returns a `T`, and `id(p)` infers `T =
  Int`, as Stage 0 has them. A reference parameter takes the reference
  forwarded with its sigil, `takes_ref(&p)` or `bump(&var q)`, so a bare
  `takes_ref(p)` is refused with the sigil written out, as Stage 0 refuses
  it; a receiver's sigil is implicit. A reference slot outside a call, a
  return's or an annotation's, keeps the reference, which the
  reference-position check refuses where the slot is declared.
- A reference in a tuple element, an optional's payload, an array element or
  a type argument is refused in a parameter's type as well as in a stored
  one: `func f(t: (Int, &Int))` is refused, where Stage 0 walks a parameter
  only for its type arguments. A `let` annotation naming a reference is
  refused too, where Stage 0 has no annotation rule.
- A type alias may stand for a reference, as a parameter's type may be one;
  each use is judged where it stands, with the alias resolved.
- A generic instantiated by inference at a reference, `idn(&x)` for `idn<T>(x:
  T)`, is refused at the call; a parameter `x: &T` solves `T` to the
  referent.
- A pattern's binding aliases its part when the walk took the scrutinee as
  borrowed (`TcOrigin.Borrowed`: a reference, a receiver, a field, or a name
  reading through a borrow: a `borrow` binding, a payload binding aliasing a
  borrowed scrutinee, a `[&x]` or `[&var x]` capture), so a `move` of it is
  refused; a match on an owned local consumes it, and its bindings own their
  parts.

## Capture readings

These are the reversible readings typecheck batch A made (SL-472, SL-469).

- A by-value capture is judged exactly as a `let` of its type would be,
  whatever binding it was taken from: the one unsafe allowance is a `let`'s,
  a write to a raw pointer's pointee. So `h.deref().bump()` on a `[move h]`
  capture of an `UnsafeRef` is refused as it is on a `let h`, which design
  218's generated receiver capture rests on.
- A consuming use of any by-value capture, plain, `move` or `copy`, is
  refused in an escaping body, and at every copy tier: a `move` of a Copy-tier
  capture is refused too, with the hint to drop the `move`. A `match` on an
  owned capture whose type does not copy silently consumes it, and so does an
  inner closure's `[move x]` of it.
- Each consuming use is judged against the innermost closure that captured
  the binding. A by-value capture of an inner closure is a value of its own,
  and the inner closure's `[move x]` entry is the use the outer closure
  answers for.
- A spelled `[copy x]` of a value whose type names a type parameter needs a
  bound that grants the copy, `Copy` for every parameter it names or
  `ExplicitCopy` on a bare one, or is refused at the definition; a silent
  by-value capture, `[x]` or implicit, is the inferred Copy requirement,
  checked at each call, as a getitem's copy is (SL:open-questions D30).
- The brace written as a `Thread.spawn` or `Task.spawn` form's argument is
  exempt from the consume rule, keyed on the form: its capture list is its
  parameter list and its body runs once (design 242). Its captures are still
  `let`s. The form takes only a brace, never a closure value.
- An implicit capture that does not copy silently is
  `transfer.implicit-copy`'s refusal alone; the consume rule does not refuse
  it again.

## Bound readings

These are the reversible readings typecheck batch B1 made (SL-463, SL-467,
SL-470, SL-474).

- A member a bounded extension or conformance withholds from its receiver is
  refused as `type.bound`, naming the bound; Stage 0 words it as a missing
  method. The builtin `copy()` on a NoCopy value stays `member.unknown`, and
  on a type whose copy reaches an unbounded type parameter it is `type.bound`.
- A requirement two conformances bring reaches the member table once, from
  the first, so that conformance's conditions are the ones its member is held
  to.
- A `[]=` that `settle_places` chooses for a subscript's write is not held to
  its own extension's bounds; the subscript's `[]` already was.
- A public generic's undeclared Copy requirement, and a declared
  `ExplicitCopy` its body exceeds, are judged for the function's own type
  parameters; a requirement on the parameters of a method's type is held at
  each call site. Public means `public`; `package` does not publish.
- A `NoMove` by-value parameter's journey home ends at the first `&`, `&var`
  or `borrow` argument naming it, in source order; a method call's receiver
  borrow does not end it, as in Stage 0. A wrapper of a `NoMove` value is
  `NoMove` when it holds it inline: an Optional, a tuple, an array, a generic
  instance's substituted field or payload; a pointer or a `Box` holds it
  behind an indirection.
- An indexed place read by value in a generic body is design 219's inferred
  requirement, checked at the call (SL:open-questions D27), where Stage 0
  refuses it at the definition.
- The overload filter scores a bare reference binding by its referent's
  value, as the funnel reads it, so among overloads taking `Int` and `&Int`
  `p` picks the `Int` one, as Stage 0 does (SL-484); a reference parameter it
  fits only by its sigil, so with no by-value overload that fits it picks the
  reference one, which asks for the sigil.
- Call-site sigils mirror the parameter both ways (SL-484): `&x` or `&var x`
  written for a parameter taken by value is refused with the sigil dropped,
  and `&var x` or `borrow var p` for a shared reference with `&x` or
  `borrow p`. `borrow p` for a by-value parameter is the statement form's
  copy, not a sigil, and stays.
- Under Stage 0's std a builtin type's own method and its builtin
  conformance's requirement of one name overload by their parameters, so
  `s.compare(&t)` is `Comparable.compare(other: &Self)` and `s.compare(t)` is
  `String.compare(other: String)`, as Stage 0 resolves them; where the two
  take the same parameters, the type's own method answers.

## Getitem readings

These are the reversible readings typecheck batch B2 made for SL-486.

- A plain subscript is a getitem only where an accessor serves it: a fixed
  array's `a[i]` and a raw pointer's `p[i]` are places of their own, read in
  place as a field is.
- `.copy()` written straight on a plain subscript spells the copy its getitem
  makes, so an ExplicitCopy element takes it; the lowering keeps the in-place
  read, which is the same value.
- A Copy-tier element keeps its role and lowering where its position keeps
  nothing: only the refusal is new, never a second copy.
- A `match` on a plain subscript reads it by value only when an arm binds a
  name; arms binding nothing test the tag, at every tier.
- A sigiled `&v[0]` or `&var v[0]` is a lent place here; SL:borrowing §9
  retires the spelling, and refusing it is not this rule's.
- A write through a plain subscript (`v[0].n = 1`) is not judged here; it is
  the retired inline place use.

## NoMove readings

These are the reversible readings typecheck batch B2 made for SL-485.

- A `NoMove` bound is refused where it is written and dropped, so the
  parameter is checked as if unbounded after it (SL-485).
- `NoMove` containment reads a member the way relocation does: inline in a
  field or payload, through an optional, a tuple, an array or a generic
  instance's substituted members; a pointer holds its value behind an
  indirection and owes nothing. A generic declaration holding a type
  parameter derives `NoMove` per instance and owes no declaration.

## Object-safety readings

These are the reversible readings SL-510 made.

- A trait whose only requirement, its parents' included, is `Deinit`'s
  `deinit` is a marker trait, as `NoCopy` is: a `deinit` is never called by
  hand (`deinit.manual-call`), so no dispatch reaches it. `any Deinit` is
  refused the same way.
- A static requirement makes its trait non-erasable, as the spec's
  Serialization section says of `Deserialize`, though "Object safety (v1)"
  does not list it; Stage 0 refuses it too.
- Each written `any Trait` is refused once, where it is written, and a
  coercion to it adds no refusal: the spec's "rejected at the point the
  existential is written". Stage 0 reports once per trait.

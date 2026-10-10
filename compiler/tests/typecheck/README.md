# compiler/tests/typecheck: the type checker's corpus

The corpus the typecheck stage (`compiler/typecheck`, SL-447) is held to. This
file specifies `sawc2 typecheck`'s records and dump, the type interner's key,
the position matrices the corpus covers, and the rules typecheck refuses by.
The stage checks signatures (U6b1), bodies (U6b2), and the summaries and the
checks that read them (U6b3).

```
typecheck/
  README.md          this specification
  typecheck_lane.py  the lane compiler/tests/run.py runs
  golden/            NAME.saw, a program, and NAME.typecheck, its expected record
  multi/             NAME/main.saw and its modules, and NAME.typecheck
  refuse/            RULE[.VARIANT].saw
  frozen_check.py    signatures, Copy tiers, call targets and binding types against
                     the frozen compiler's
  frozen_effects.py  exhaustiveness, discarded-Result and suspension verdicts
                     against the frozen compiler's
  FROZEN_CHECK.md    the record of those checks
  cone_coverage.py   how much of the std cone gets a fully bound signature
  corpus_info.py     how much of tests/corpus/ checks, for information
```

## `sawc2 typecheck`

```sh
.build/sawc2 typecheck (--dump | --check) [--notes] [--interfaces] [--summaries]
                       [--std-root DIR] [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved, then checked,
with every module it imports. The flags are resolve's (see
`compiler/tests/resolve/README.md`); `--interfaces` also dumps the std and
builtin modules, whose signatures are checked as interfaces. Each entry gets one record, starting
with the line `FILE<TAB>path`, holding in order:

- one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal:
  resolve's first, then typecheck's, each in the order they were made;
- with `--notes`, one `NOTE` line, in the same shape, per note: a refusal in
  an interface module, std or builtin, which refuses nothing;
- one `INVARIANT<TAB>module<TAB>message` line per problem any verifier
  finds, resolve's then typecheck's, for every module, interfaces included;
- with `--summaries`, one `SUMMARY<TAB>identity<TAB>SUSPENDS<TAB>SYNC` line per
  function of the modules checked in full, SUSPENDS `suspends`,
  `suspends-when` or `never-suspends`, SYNC `nonsync`,
  `sync-callable-unless` or `sync-callable`;
- with `--dump`, the dump of each module checked in full, in load order.

The exit code is 1 when any program has a refusal, 2 on a usage failure, and 0
otherwise.

## The dump

A module's dump is one S-expression, one entry per line, in this layout:

```
(Module IDENTITY
  (declarations
    (KIND PATH L:C [VISIBILITY] [DETAIL]...)...)
  (members
    (TYPE
      (MEMBER-KIND NAME [FIELD-TYPE] VISIBILITY SOURCE)...)...)
  (views
    (TYPE NAME...)...)
  (conformances
    (TYPE TRAIT L:C (REQUIREMENT STATUS)...)...)
  (copy-tier
    (TYPE TIER [declared])...)
  (bodies
    (DECLARATION L:C
      (L:C-L:C KIND TYPE [ADJUSTMENT]... place|value USE [CALL])...)...))
```

- **declarations** lists the module's declarations in source order, as
  resolve's dump does: PATH is the name, after its parent's for a member, and
  L:C where its name is written. VISIBILITY is `private`, `public`, `package`
  or `parent`. The detail depends on the kind:
  - `struct`: its generic parameters, and `unsafe` or `borrows` for a
    modifier; `enum`: its generic parameters and `(raw TYPE)`; `case`:
    `(payload (NAME TYPE)...)`; `field`, `static`, `alias` and
    `type-assign`: the type, and `unsafe-var` for an `unsafe static var`;
  - `trait`: `(parents TRAIT...)`; `assoc-type`: nothing more;
  - `extension`: `(target TYPE)`, its conditions `(where (PARAM TRAIT...)...)`,
    `(conforms TRAIT...)` and `synthesize` for `@synthesize`;
  - `func`, `method`, `init`, `requirement`, `extern`: a signature, below.
- A **signature** is `(signature [GENERICS] [(receiver shared|exclusive)]
  (params (NAME TYPE PASSING [default])...) [(effects WORD...)] [(lend
  CLASS shared|exclusive)] -> RESULT [static] [default-body] [variadic]
  [blocking] [synthesize-shared])`. PASSING is `owned`, `shared` for a `&T`
  or `&[T]` parameter, or `exclusive` for a `&var` one. The effects are the
  slot's words in its order (`consumes unsafe constexpr sync escaping borrows`,
  `borrows(sync)` for the lend that may not span a suspension). An `init`
  with no written result produces `Self`; any other function with none
  produces `Void`.
- **GENERICS** is `(generics (NAME [(bounds TRAIT...)] [(default TYPE)])...)`,
  a const parameter written `(const NAME TYPE [(default VALUE)])`.
- A function's declaration (`func`, `method`, `init`, `extern`, and a
  `requirement` with a default body) ends with its **summary** (phase 2,
  `compiler/typecheck/README.md`, "The summaries"): `(summary SOURCE
  (suspends WHEN) (sync-callable UNLESS) [(copy PARAM...)] [(refuses-when
  CONDITION...)])`. SOURCE is `body`, `declared` (an extern, or a `sync`
  function whose body is not checked), `table` (a std function's row) or
  `untabled`. WHEN is `yes`, `no` or `when CONDITION...`; UNLESS is `yes`,
  `no` or `unless CONDITION...`. A CONDITION is `PARAM.Trait.requirement`, a
  requirement called through one of the function's own type parameters, or
  `Self` in a trait's default body; a PARAM of `copy` is a type parameter the
  body copies; a `refuses-when` entry is `(KIND CONDITION)`, KIND `closure` (a
  closure's call would suspend), `any` (a coercion would dispatch to a
  suspending implementation) or `sync` (a `sync` body's call would not be
  sync-callable). Each list is sorted.
- **lend** is the accessor-signature reader's classification of a `borrows`
  result (SL:architecture §3.4): `place` (`&T`, `&var T`),
  `conditional-place` (`&T?`), `slice` (`&[T]`), `conditional-slice`
  (`&[T]?`), `borrowing-struct` (a `borrows struct` lent by value), or `other`,
  which the checks on `borrows` bodies refuse.
- **members** lists each struct and enum the module declares, with its member
  table: its fields or cases, the methods, statics, inits and type
  assignments of every extension of it in the program, and what its
  conformances bring. SOURCE is `declared`, `(extension MODULE)`, `(default
  TRAIT)` for a trait's default body, or `(synthesized TRAIT)` for what
  `@synthesize` derives and for the `deinit` the compiler writes for a type
  that owns something and writes none (`(synthesized Deinit)`, spec,
  Synthesized destruction). A member kind is `field`, `case`, `method`,
  `static`, `init` or `type-assign`.
- **views** lists, for every struct and enum an entry or package module of the
  program declares, the names of the members this module sees: the table
  through the two filters of "Member tables and views", below.
- **conformances** lists each conformance the module's extensions declare,
  where the trait is named, and how each requirement of the trait and of the
  traits it refines is met: `written` (a member of the type the conformance's
  module sees, or a type assignment: the conformance's own, or for a parent
  trait's associated type the one the type's conformance to that trait
  writes), `default`, `synthesized` (under
  `@synthesize`), `implicit` (a `deinit`, synthesized for every type), or
  `missing`, which a refusal names.
- **copy-tier** gives each struct and enum the module declares its tier:
  `Copy`, `ExplicitCopy` or `NoCopy`, with `declared` when a conformance
  declares it. An undeclared generic type's tier is a rule over its
  arguments, `(join BASE PARAM...)`: the strongest of BASE and the tiers of
  the arguments for those parameters.
- **bodies** lists each body the module holds, grouped under its declaration
  (`item` and a position for a `static_assert` or a test case): a function's
  parameter defaults and block, a static's initializer, a raw case's value,
  an `@align` argument. Each line is one typed node, expressions and patterns,
  in source order (a node before the nodes inside it):
  - its span, `L:C-L:C`, and its KIND, the parser dump's name for its
    alternative;
  - TYPE, the node's own type before any conversion;
  - each ADJUSTMENT in order, `(KIND TYPE)` with the type the step produces:
    `adopt` (a literal or constant taking its slot's type), `never`, `some`,
    `ok`, `err` (auto-wrap), `slice` (`&v` to `&[T]`), `shared` (an exclusive
    reference passed as a shared one), `deref` (a reference read through),
    `borrow` and `borrow-var` (a receiver's implicit borrow, design 141),
    `erase` (a concrete value becoming `any Trait` or `Box<any Error>`), and
    `widen` (an integer extended losslessly into a wider one, "The wrap and
    erasure matrix");
  - `place` or `value`, then USE: a value use's transfer, `move` (a spelled
    `move`, the place it moves, the owned local a `match` consumes and the
    parts its bindings take, or a generic body's by-value read of a local
    that no path uses after it, design 219), `copy` (an implicit copy of a
    place) or `temp`
    (the hand-off of an owned temporary); or `borrow`, `borrow-var`,
    `project` (the base of a member, index or `!`), `write`, `update` (a
    compound assignment's target) or `test` (a scrutinee, a pattern that binds
    nothing);
  - for a closure that captures something, `(captures (NAME USE)...)`: each
    capture in order, the capture list's entries then the bindings its body
    names, with its transfer: `copy` or `move` by value, `borrow` or
    `borrow-var` for a borrow of the enclosing frame;
  - CALL, for a call, operator, subscript, `for` or pattern case: `(ROLE
    [TARGET] [SPELLING] [derived] [(owner TYPE)] [(inst TYPE...)]
    [(bind PARAM=ARG...)] [(variadic K)])`. ROLE is
    `call`, `memberwise`, `case`, `builtin`, `conversion`, `op` (a builtin
    operator, by its spelling), `operator` (a declared `equals` or `compare`),
    `getitem`, `setitem`, `place` (SL:borrowing §5's roles, `derived` when the
    type declares only the place accessor), `iterator` (a `for` loop's `next`)
    or `value` (a function value). TARGET is the declaration's identity and,
    for a function, its parameters, which tell an overload apart; `owner` is
    the type a member is instantiated at, and `inst` the target's own type
    arguments. `bind` is how the overload filter bound the written arguments
    (design 66): each parameter in order, with the position among the written
    arguments of the one that binds it, or `default` when its default fills
    it. It is printed only when the binding is not one to one in order, and
    `variadic` names the first argument a C variadic tail takes.

### Type spellings

Every type is written in its canonical spelling, so no dump depends on the
order types were interned in, and two spellings of one type print the same.

| type | spelling |
|---|---|
| a builtin type | its name: `Int`, `String`, `Void`, `UnsafePointer<T>`, `Result<T, E>` |
| any other nominal type | its module's identity and its path, then its arguments, every default filled: `std.vector.Vector<Int, std.alloc.GlobalAllocator>` |
| `Optional<T>` | `T?`, with a reference or function type in parentheses: `(&T)?` |
| a type or const parameter | its name |
| `Self` in a trait, a trait's associated type | `Self`, `Self.Item` |
| a type parameter's associated type, a projection | its base, then the associated type's name: `T.Item` |
| tuples | `()`, `(A,)`, `(A, B)`, `(x: A, y: B)` |
| a function type | `(A, B) EFFECTS -> R` |
| references, slices, arrays | `&T`, `&var T`, `&[T]`, `&var [T]`, `[T; N]` |
| an existential | `any TRAIT` |
| a constant argument | its folded value |
| a type that could not be formed | `(error)`, beside a refusal |

An alias and a type assignment are transparent: the type they stand for is
written.

## The interner's key

One interner per compilation holds every type, and identity is key equality:

- a nominal type is its declaration (so its defining module and path, design
  144) and its canonical arguments, each defaulted parameter filled at every
  depth, so `Vector<Int>` and `Vector<Int, GlobalAllocator>` are one key;
  `T?` is the builtin `Optional` applied to `T`, one key with `Optional<T>`;
- a type or const parameter is its declaring declaration and its index, so
  the `T` of `Vector<T>.push` and the `T` of `Map<K, T>` never meet. An
  extension's parameters rename the parameters of the type it extends, and
  are keyed as the type's;
- `Self` in a trait requirement is a placeholder keyed by the trait; a
  conformance substitutes it when a requirement is matched;
- a projection, `T.Item` (SL:open-questions W4), is the associated type's
  declaration, its trait, and the type it is projected from, `T`'s parameter
  key. A trait's own associated type, `Item` or `Self.Item` in the trait, is
  the projection on the `Self` it is written under, so a refining trait's
  `Self.Item` is projected from its own `Self` (SL-458). Two projections are
  one type only when their keys are equal, so the `T.Item` and `U.Item` of
  one trait never meet; no bound can pin a projection to a concrete type, so
  none equals one. Substitution replaces the base, and a base that becomes a
  nominal type replaces the projection by the type its conformance assigns.
  A requirement called through a type parameter `T` has the trait's
  associated types substituted by `T`'s projections, so `s.take(v)` with
  `take(v: Self.Item)` takes an `S.Item`;
- every other form is its kind and its parts: a tuple's elements and labels,
  a function type's parameters, result and effects, a reference's or slice's
  referent and exclusivity, an array's element and length, an existential's
  trait, a constant's value.

Ids are handed out in the order signatures are built, modules in load order
and declarations in source order. Keys are symbolic, so a serialized module
boundary can re-intern by key.

## Member tables and views

A nominal type's member table is built once. A module sees a member through
two filters: a member of an extension needs the extension's module in the
module's extension set (its own, its direct imports' and what they re-export,
design 142) or the type's own module; and every member needs its visibility
to reach the module (design 80: a member of another module is seen when it is
`public`, when it is `package` and the modules share a package, or when it is
`parent` and the module lies under its parent). What a conformance brings is
as visible as the conformance, which the orphan rule makes global, and so is
a member written to meet a requirement, whatever its own visibility, when the
trait's visibility reaches the module (spec, Member visibility:
"Trait-conformance methods follow the trait"; multi/conformance_views). A
requirement's default or derivation reaches the table once, however many of
the type's conformances reach its trait: `E: Printable` and `E: Error`, which
refines it, bring one `to_string`.

A third filter belongs to the receiver, not the module: a member declared in
a bounded extension, `extension Cell<T: Equatable> { ... }`, or brought by a
bounded conformance, exists only on an instantiation whose arguments meet
those bounds (SL-463). One funnel, `members_for`
(`compiler/typecheck/src/candidates.saw`), drops the rest and keeps the first
it dropped, so the refusal names the bound rather than a missing member; in a
generic body a type parameter's argument is answered by the bounds in scope,
as `type.bound` answers them. The builtin `copy()` follows the same question:
it exists where the receiver meets `ExplicitCopy`, through its tier or a
conformance whose conditions hold, at any depth of a tuple, an array or an
Optional. Under `type.bound` unless a cell says otherwise:

| row | verdict | covered by |
|---|---|---|
| a method of a bounded extension | refused | type.bound.extension-method |
| a static of one, which Stage 0 accepts (SL:hazards S26) | refused | type.bound.extension-static |
| a member of a bounded conformance | refused | type.bound.conformance-member |
| `==` through a bounded conformance's `equals`, which Stage 0 accepts | refused | type.bound.operator |
| a subscript, a `for` loop's `next`, an `init` whose type inference solves | refused | type.bound.subscript, type.bound.iterator, type.bound.init |
| std's `copy()` on `Vector<T>` where `T` is not ExplicitCopy | refused | type.bound.vector-copy |
| the builtin `copy()` reaching an unbounded type parameter, through a tuple, an Optional or an array (row V43) | refused | type.bound.copy-wrapper |
| the builtin `copy()` on a NoCopy value, a tuple holding one included (rows V11, V22) | refused, `member.unknown` | member.unknown.copy-nocopy |
| each where the bound holds: a concrete argument, a generic body's own bound, `copy()` under `T: ExplicitCopy` | allowed | extension_bounds |

## The position matrix

Every type position the subset and the std cone write, and the golden case
that covers it.

| position | typed as | covered by |
|---|---|---|
| named type, no arguments: a builtin, struct or enum | a nominal type | types |
| named type with arguments, defaults filled at every depth | a nominal type with canonical arguments | generics |
| qualified named type `m.T` | the module's declaration | multi/views |
| `T?`, `T??` | `Optional` applied to the payload | types |
| `&T`, `&var T` | a reference | types, declarations |
| `&[T]`, `&var [T]` | a slice | types |
| `[T; N]`, with a literal or a const parameter | an array | generics |
| `()`, `(T,)`, `(A, B)`, `(x: A, y: B)` | a tuple | types |
| function type with effects | a function type | types |
| `any Trait` | an existential | types |
| an alias, a type assignment | the type it stands for | types, traits |
| `Self` in a struct, enum or extension | the type applied to its own parameters | traits, declarations |
| `Self` in a trait, a trait's associated type | a placeholder | traits |
| `T.Item`, a type parameter's associated type, inherited from a parent trait or reached through two bounds | a projection | associated_types |
| bare `Item` in a refining trait's members, an associated type it inherits, and one conformance assigning it for both traits | the parent's associated type | inherited_associated_types |
| type parameter, const parameter | a parameter keyed by its declaration | generics |
| generic parameter's bounds, default and const type | traits, a type, a constant | generics |
| constant argument: a literal, `+`, `-`, `*`, a const parameter | its folded value, or the parameter | generics |
| field, payload, raw backing, static types | the declaration's types | declarations, tiers |
| parameter and result types, a receiver | the signature | declarations |
| extension head, its parameters' bounds, its conformances | the target, conditions, traits | traits |
| trait parents, requirements, default bodies | the trait's signatures | traits |
| extern parameters, variadic, `blocking` | the signature | declarations |
| a `borrows` result | the accessor-signature reader's classification | declarations |

| outside the slice | refused as |
|---|---|
| a constant argument named by a static | `slice.not-yet` |
| arithmetic over a const parameter, which folds only per instantiation | `slice.not-yet` |
| a constant argument written with `/`, `%`, a shift, a bit operator, a call or a member | `slice.not-yet` (the alternative) |
| a generic type alias | `slice.not-yet` (`syntax.decl.type-alias`) |
| an extension of a declaration that is not a struct, an enum or a builtin type | `slice.not-yet` (`syntax.decl.extension`) |
| a member named through an associated type, `T.Item.Key` | resolve's `slice.not-yet` |

The slice is what `compiler/` and the std cone use; a construct outside it is
refused by name, never mis-typed, and the verifier asks nothing of what lies
under one.

## The body position matrices

The expected-type funnel's entry points, the literal-adoption positions of
SL:architecture §3.4, each a function `expect`'s docstring names:

| position | entry point | covered by |
|---|---|---|
| an annotated `let` or `var` | `check_let_value` | funnel |
| a static's initializer, a raw case's value, an `@align` argument | `check_static_value` | funnel, declarations |
| every assignment-target kind: a local, a field, a tuple element, an array or `Vector` element, a reference's referent | `check_assigned` | funnel, places |
| a parameter, an init argument | `check_argument` | funnel, calls |
| a field of a memberwise construction | `check_field_argument` | funnel, calls |
| a default value | `check_default_value` | funnel |
| `return` | `check_returned` | funnel, peeling |
| a body's tail | `check_body_tail` | funnel, peeling |
| the `if`, `else` and `match` results that merge | `check_branch` | funnel, control |
| an enum payload | `check_payload` | funnel, calls |
| a compound assignment's right side | `check_compound_value` | funnel, places |
| a collection literal's element, key and value, a tuple's element | `check_element` | funnel |
| a closure's tail and branch results | `check_closure_tail` | funnel, control |
| a mixed operator's other operand; a comparison's, borrowed | `check_operand`, `check_compared` | funnel, operators, peeling |
| `??`'s fallback | `check_coalesce_right` | funnel, peeling |

### The wrap and erasure matrix

What each funnel position lets the conversion build, which `expect` hands to
`coerce` as a `TcAllowance`: how many optional wraps (`any` for the slot's
depth), whether a Result wrap, and whether a concrete error erases into
`Box<any Error>` under the `Err` wrap. At every position a Result wrap goes
outside an optional wrap, never inside one ("A `Result<T?, E>` fed a bare `T`
takes both wraps, innermost first"), and there is one Result wrap at most ("a
bare `T` becomes `Ok`, a bare `E` becomes `Err`"). A value branch's arms take
what the position the branch stands in allows ("A tail that is itself a value
`if` or `match` is judged per arm"). The spec lines, from LANGUAGE_SPEC.md:

- **D1**, Primitive Types: "A slot naming more than one layer takes the
  innermost payload, so `let d: Int32?? = 11` is an `Int32` too", after "at
  every position above (`f(2)` for a `f(o: Int32?)`, a field, a return, an
  array or `Vector` element, a closure tail)";
- **Target**, Primitive Types: "An ASSIGNMENT TARGET names an expected type
  the same way an annotation does";
- **Call**, "Call-site optional auto-wrap": "a bare `T` argument auto-wraps
  into a `T?` parameter at every call form (free function, method, static
  method, module-qualified, struct `init`, and enum-payload construction). It
  is one level only (`T → T?`, never `T → T??` — and an already-optional
  argument is passed through, never re-wrapped)";
- **CallResult**, "Call-site `Result` auto-wrap": "The same rule at the other
  payload kind, in the same positions";
- **NoErase**, the same section: "Argument position does not erase: a
  concrete error passed where `Result<T, Box<any Error>>` is declared must be
  written as an explicit `Err` value, since the erasure needs the allocator
  the return position supplies";
- **Slot**, Auto-Wrap: "it fires wherever a value lands in a declared
  `Result` slot", and "the argument positions (call arguments at every form,
  struct-literal fields, enum payloads, collection-literal elements, defaulted
  parameters) follow the same table";
- **Return**, "`Error` and erased Results": "Returning a concrete `E: Error`
  from such a function auto-wraps it to `Err` and auto-erases it into a
  `Box<any Error>` at the return boundary";
- **Four**, Auto-Wrap: "Four return targets take this wrap, and they take the
  identical one: a function body's tail, a method body's tail, an explicit
  `return`, and a CLOSURE body's tail", and "the erased `Box<any Error>`
  target and the optional-Ok-payload wrap all reach a closure tail exactly as
  they reach a named one";
- **Tuple**, Composite Types: "an optional element takes the ordinary
  one-level auto-wrap";
- **Rows**, "Call-site `Result` auto-wrap": "`let rows: Vector<Result<Int,
  String>> = [1, 2]   // two Ok elements`".
- **Widen**, Integer Width Agreement, "Plain transfers take the same rule": "A
  lossless widening is free… There is no position exemption. The rule holds
  wherever a value lands in a new home: a `let` or `var` initializer, an
  assignment right-hand side, a call argument, a `return` and a body's tail
  expression, a struct-field initializer, an enum payload, an array, tuple,
  `Vector`, `Map` or `Set` element, an optional slot, a default parameter
  value, and a `static` initializer";
- **Arms**, "Value-branch arms are transfers": "Each arm of a value `if` or
  `match`, and each operand of `??`, hands its value to one merged home. Each
  is a transfer, so each takes the rule a `return` takes: a lossless widening
  is free", and "Bare literals adopt in arm position exactly as they do in
  operand position";
- **Peers**, "Operands agree; only literals promote": "A binary operator, a
  comparison, a compound assignment or a range whose two operands are
  integers of different width… is a compile error naming both", and "A
  suffixed literal is exact-typed, and a named value carries the type it was
  declared with".

A widening is lossless when it is the identity, a same-sign widening, or an
unsigned type into a strictly wider signed one, and the platform pair, `Int`
or `UInt`, stands on at least one side ("Two distinct fixed widths still do
not merge, because they do not convert implicitly anywhere"). It is recorded
as a `widen` adjustment, inside any wrap the position builds (`let o: Int? =
u` on a `UInt8 u` is `(widen Int) (some Int?)`).

| position | optionals | Result | erases | widens | spec | covered by |
|---|---|---|---|---|---|---|
| `let`, `var` | any | yes | no (OPEN) | yes | D1, Slot, Widen | wraps, widening; erase-let, narrowing, fixed-widths |
| static | 1 (OPEN) | yes | no (OPEN) | yes | Slot, Widen; "Never optional" makes the wrap unreachable | wraps |
| assignment | any | yes | no (OPEN) | yes | Target, D1, Slot, Widen | wraps, widening; erase-assign |
| argument | 1 | yes | no | yes | Call, CallResult, NoErase, Widen | wraps, widening; wrap-argument, erase-argument |
| memberwise field | 1 | yes | no | yes | Call (struct `init`), Slot, NoErase, Widen | wraps, widening; wrap-field, erase-field |
| default | 1 (OPEN) | yes | no | yes | Slot (an argument position), NoErase, Widen | wraps, widening; wrap-default, erase-default |
| `return` | any | yes | yes | yes | D1, Four, Return, Widen | wraps, widening |
| body tail | any | yes | yes | yes | D1, Four, Return, Widen | wraps, peeling, widening; fixed-widths |
| branch | inherited | inherited | inherited | yes | D1 ("if/match arm results that merge"), Four, Arms | wraps, widening; wrap-branch, erase-branch, branch-merge, literal-range |
| payload | 1 | yes | no | yes | Call (enum-payload construction), Slot, NoErase, Widen | wraps, widening; wrap-payload, erase-payload |
| compound | 1 (OPEN) | yes | no (OPEN) | no | its slot is a number or `Bool`, so no wrap is reachable; Peers | widen-compound, static-compound |
| element | 1 | yes | no | yes | Tuple, Slot, Rows, NoErase, Widen | wraps, widening; wrap-element, erase-element |
| closure tail | any | yes | yes | yes | D1, Four, Widen | wraps |
| operand, compared | 1 (OPEN) | no (OPEN) | no (OPEN) | no | "The one place a literal is typed by a sibling rather than a declared slot is a mixed binop"; Peers | wraps, widening; wrap-compared, result-compared, widen-operand, static-peer |
| `??`'s fallback | 1 (OPEN) | no (OPEN) | no (OPEN) | yes | "`??` peels exactly one layer, and its default owes what is left"; Arms | wraps, widening; wrap-coalesce, result-coalesce |

An OPEN cell is one the spec does not state; it takes the most restrictive
reading its nearest stated rule supports. The Result wrap inside an optional
and a second Result wrap are OPEN too (result-in-optional, result-nested).

A value branch with no expected type merges its arms: an arm that types
itself is typed on its own, the merged type is the arm type every other arm
widens into, and each narrower arm records its `widen` (Arms); arms with no
such type are refused (branch-merge). An arm whose tail is a bare literal, or
a constant expression over literals, is a peer whose width is undecided, as an
operand's is: it is checked after the other arms, adopts their merged type
with an `adopt`, never a `widen`, and must fit it (literal-range), so `if c {
1 } else { x16 }` is `Int16` whichever arm comes first. When every arm is a
literal the first is typed on its own, and the branch is `Int`. A branch with
an expected type is unchanged: each arm takes the slot. A bare module static
in an arm is a named value, not a literal, and keeps its declared type
(Peers).

A bare integer literal, or its negation, that stands at a funnel position is
range-checked against the integer type it adopts, its own `Int` when it adopts
none (spec, Primitive Types: "range-checked *at the literal*"). A larger
constant expression is folded (`fold.saw`) by typed arithmetic
(SL:architecture §3.10), with a module static of an integer type and a
raw-backed enum's case as leaves: each literal is written at the type the
expression adopts, each leaf converted to it, and each operation runs at its
operands' type. A value that does not fit where it adopts is refused as "does
not fit", so `b >= (BIG + 0)` with `BIG = 1000` and a `UInt8` peer is refused
as "constant expression 1000 does not fit in `UInt8`" (static-leaf); an
operation that leaves its type's range is refused as overflowing it, so `255 +
1` at `UInt8` is (constant-range), and so is `256 - 1`, whose `256` does not
fit; a shift count outside the shifted type's width and a division by zero
are refused too. `1 << 63` at `UInt64` is 2^63. A 64-bit magnitude past
`Int.max` is refused only where it certainly does not fit: a non-negated one
at a signed type. A literal with a signed width suffix is held to the width's
signed range wherever it stands, with the minimum's magnitude allowed only
under a unary minus, `-128_i8` (SL:open-questions D6; signed-suffix).

A combination of a raw-backed enum's cases is its backing integer, never the
enum (spec, Flag enums): it adopts an integer slot and is range-checked there
(flag-combination), and with no integer slot it is the backing type. A lone
case adopts an integer slot the same way, at every funnel position but an
operator's peer, a compound assignment's right side and `??`'s fallback,
where it keeps the enum's type as a named value does (D17).

An operator's peer adopts only when it is a literal or a constant expression.
A bare module static is a named value and keeps its declared type there, so
`flag >= SHIFT` for a `UInt32 flag` and an `Int SHIFT` is refused, with the
hint `SHIFT as UInt32` (static-peer, static-compound); a static adopts only as
a leaf inside a constant expression, so `flag >= (1 << SHIFT)` checks (Peers).

A `??` whose fallback is wider than the
optional's payload would merge into the fallback's type, widening the payload
inside its Optional, which no adjustment records: it is `slice.not-yet`
(coalesce-wider).

Every body construct in the slice, and how it is typed:

| construct | typed as | covered by |
|---|---|---|
| integer, float, string, `Bool` and `None` literals, `#file`, `#line`, `#function` | `Int` adopting its slot, range-checked, or a suffixed literal's exact type; `Float`, `String`, `Bool`; the slot's Optional, or the Ok payload's `None` at a `Result<T?, E>` slot (spec, Auto-Wrap: "At a declared `Result<T?, E>` it is `Ok(None)`") | funnel, peeling, widening, none_ok |
| a constant expression: literals, module statics of an integer type and raw-backed cases, under `-`, `~`, arithmetic, shift and bit operators; `fold.saw` also folds a type alias's construction over one, `Byte(65)`, as the identity, for the evaluator's agreement | adopts its slot, or its mixed operator's peer, and folds there by typed arithmetic, every literal and leaf fitting and no operation overflowing; a bare static adopts only as a leaf inside one, and keeps its declared type anywhere else, an operator's peer included (spec, Integer Width Agreement: "a module `static`… may be a leaf"); a combination of cases with no integer slot is the backing integer (spec, Flag enums) | funnel, widening, folding |
| a shift, `a << n` | the left operand's type; each count an integer of any width, no peer ("The shift count is exempt") | widening |
| an interpolation, its segments | `String`; each segment Printable or a primitive, or an erased box `Box<any Trait>` whose trait refines Printable, rendered through the existential; borrowed | format, split_conformance |
| a local, a parameter, a static, `self` | its type, a place | places |
| a const parameter, `N` | a value of its declared type, not a place (design 148) | builtin_values |
| a function named as a value | its one function's type | calls |
| a field, a named tuple's element, a tuple index | the member's type through any reference, a place when the base is | places, funnel |
| `E.Case`, `.Case`, `E.Case(...)`, `.Case(...)` | the enum, its arguments from its head (`Maybe<Int>.Nothing`), the slot or the payload | peeling, calls, builtin_values |
| `Int.max`, `T.from(x)`, `T.from(truncating: x)`, `E.from(raw: x)`, `A(x)` | the conversions no declaration writes | carried |
| a free function, method, static method, `init` or memberwise call | the overload filter's choice, instantiated | calls, inference |
| a requirement called through a type parameter whose signature names an associated type, `s.take(v)` with `take(v: Self.Item)`; a call instantiating a signature that names `T.Item` | the receiver's projection, `S.Item`, which takes no concrete type and copies silently under no bound; at the call, the conformance's assignment | associated_types; type.mismatch.projection, type.mismatch.projection-concrete, transfer.implicit-copy.projection |
| a call's arguments: positional, a label skipping a default, a default left out, a construction's or payload's labels out of order, a C variadic tail | the binding of each parameter to its argument or its default | arguments, lowlevel |
| a construction whose head writes a prefix of its type's arguments, `Two<Int>(a: 1, b: true)` | the prefix pins the leading parameters, inference solves the rest (spec, Generics) | partial_arguments |
| a function value's call | its function type | calls, control |
| `h.f(x)` where `f` is a field holding a function and the type has no method `f` this module sees | the field's function value, called (`value`); with such a method seen too, refused as `call.field-method-ambiguous` (SL:open-questions D16) | field_calls, multi/field_views |
| `o.take()`, `o.is_some()`, `o.is_none()`, `x.copy()`, an array's or slice's `len()` and `swap(i, j)` | the methods no declaration writes | places, conversions |
| a builtin type's method of a trait it conforms to builtin: `n.to_string()`, `7.to_string()`, `equals`, `compare`, `hash` (design 109) | the trait's requirement or default, `Self` the builtin type | builtin_values |
| a raw pointer's `*p` and `p[i]`, `(&x) as UnsafePointer<T>`, an extern call, a C variadic one, an `unsafe static var`, an allocator parameter's `A()` | the pointee, a pointer, the extern's result, a value of the parameter | lowlevel |
| `print`, `panic`, `assert` with a message or format arguments; `sizeof`, `alignof` | `Void`, `Never`, `Int` | format, inference |
| a subscript | a getitem, setitem or place accessor call, or an array's builtin | places, funnel |
| `o!`, `-x`, `not b`, `~x`, `&x`, `&var x`, `move x`, `move o!`, `*p` | the payload place, the operand's type, a reference, the moved value, the payload moved out of the optional place (design 131), the pointee | places, operators, conversions, builtin_values |
| arithmetic, bit, shift, comparison, logic, `??`, `as`, `a..b` | agreeing operands; builtin or a declared `equals`/`compare` | operators |
| `==` on an undeclared generic POD struct, `Pair<Int> == Pair<Int>` | the automatic `Equatable`, judged per instantiation (SL:open-questions D18) | partial_arguments |
| `==`, `<` on a type parameter, a trivially copyable struct, a tuple | a bound's `equals` or `compare` ("A `T: Equatable` generic bound grants `==`"); the structural comparison of the automatic `Equatable` ("trivial (POD) structs"), and of a tuple whose elements all are ("Tuples are Equatable iff every element is") | comparisons |
| `try`, `try!`, `try?` | the `Ok` type, its error propagating into the body's Result | carried |
| tuples, repeat, `Map` and `Set` literals | from the slot, or the first element | funnel |
| a bracket literal | a `Vector` where the slot is one; otherwise a fixed array `[T; N]`, `T` from the slot or the first element and `N` its element count (spec, Composite Types: "with no expected type it is a fixed-size array") | arrays, funnel |
| a closure | parameters written or from the slot's function type, or, as a generic call's argument, from the parameter type once inference has solved its parameters; result from the slot or its tail; with no slot, from its first `return`, which the later `return`s and the tail must agree with, so a body whose every path returns has what it returns (design 213, SL-476): all-`return`, a `return` beside a tail, `return`s in `if`/`match` arms and a loop, a generic parameter's slot, a bare `return`, a nested closure's `return` kept to it | control, closure_inference, closure_returns; type.mismatch.closure-returns, .closure-returns-fall-off, .closure-returns-tail |
| a closure's captures: a Copy local named with nothing written, `[move x]`, `[copy x]`, `[&x]`, `[&var x]`, a reference parameter, `self`, `[&self]`, `[&var self]` | copied, moved, or borrowed as the word or the receiver says; a borrow of the frame only in a closure passed straight to a parameter whose function type does not say `escaping` | captures; transfer.implicit-copy.capture, capture.copy, capture.escaping-borrow, capture.exclusive-self |
| `if`, `match` | the merged branch type, or `Void` as a statement | control, patterns |
| `while`, `while { }`, `while let`, `for`, `break`, `continue`, `return` | `Void`, or `Never` with no `break` | control, places |
| `let`, `var`, destructuring, assignment, compound assignment, `guard`, `lend` | statements | funnel, patterns, declarations |
| a `borrow` block, `borrow` place, `if borrow let` | the place's type, borrowed | borrows |
| `borrow var PLACE`, `borrow PLACE` where a `&var T` or `&T` parameter expects it | the place passed by reference, `&var T` or `&T` (SL:borrowing §2.2) | borrow_arguments |
| a default value whose parameter's type is a type parameter, `b: T = 0` | a literal typed as written, whose type drives each call's inference, or `None`, which needs each call's `T` optional; checked against each call's `T` (design 108) | generic_defaults; generic-default |
| patterns: wildcard, literal, range, tuple, variant, name, `None`, borrow binding | the matched type; bindings copy, take, move or alias | patterns, places |
| a lone name pattern resolve took for a case | that case of the matched enum, else refused (D13) | patterns, multi/cases |

| outside the slice (bodies) | refused as |
|---|---|
| an optional chain, `a?.b` | `slice.not-yet` (`syntax.expr.optional-member`) |
| a `try` block, an inline `catch`, a `try(as ...)` route | `slice.not-yet` (the alternative) |
| an open range, `a..` or `..b` | `slice.not-yet` (the alternative) |
| `for borrow`, `while borrow`, `lends`, `move *p` | `slice.not-yet` (the alternative) |
| `break` with a value | `slice.not-yet` (`syntax.stmt.break`) |
| a method or static method named without its call | `slice.not-yet` (`syntax.expr.member`) |
| a call of a type parameter with arguments, `T(x)` | `slice.not-yet` (`syntax.expr.call`) |
| `sleep`, `cancelled` | `slice.not-yet` (sync-only) |
| a call whose signature names a type from a std module the parser refuses | `slice.not-yet` |
| a specialized extension, and every body in it | `slice.not-yet` |
| a default of a type parameter's type that is no literal and no `None` | `slice.not-yet` (generic-default) |
| a `??` whose fallback is wider than the optional's payload | `slice.not-yet` (coalesce-wider) |
| constructing a builtin type no declaration writes an `init` for: `Atomic(v)`, `UnsafeMutableInterior(v)`, `UnsafeMemory<T, U>(a)` | `slice.not-yet` (builtin-construction) |
| a method call on `any Trait` | `slice.not-yet` (existential-call) |
| a method `Box` or `Arc` forwards to its payload | `slice.not-yet` (forwarding) |
| `TaskGroup.spawn` | `slice.not-yet` (task-group-spawn) |
| a `borrow` block over a method that lends through a closure parameter, as `borrow var c = m.lock() { ... }` | `slice.not-yet` (lock-borrow) |
| calling a `FuncPointer`, a function or closure where one is expected | `slice.not-yet` (func-pointer) |
| pointer arithmetic, `p + i` | `slice.not-yet` (pointer-arithmetic) |
| the erasing `Box<any Trait>.make` | `slice.not-yet` (box-make-any) |
| a method of the interior cell, `c.ptr()` | `slice.not-yet` (cell-method) |

## The summary and check position matrices

Each position a U6b3 rule quantifies over, and the golden case or refusal
fixture (`refuse/RULE.VARIANT`) that covers it.

**Suspension and sync-callability** (SL:architecture §3.4, "Effects"):

| position | answered by | covered by |
|---|---|---|
| a call of a function with a checked body | its summary, at the call's type arguments | summaries |
| a call of a std function | its row of the std suspension table | summaries (`Vector.map`, `yield_now`) |
| a call of an extern | its `blocking` | declarations |
| a call through a bound | a condition over the caller's parameter | summaries; effect.sync.bound |
| a call through a function value | never suspends; sync-callable when its type says `sync` | summaries; effect.sync.value |
| a call in a `sync` function, a `deinit`, a closure of a `sync` type | refused when not sync-callable | effect.sync, effect.sync.deinit, effect.sync.closure |
| a `sync` requirement met by a member not declared `sync` | the member's summary | effect.sync.requirement |
| a call in a closure body | refused when it may suspend, at once or at the instantiation | effect.closure-suspends, effect.closure-suspends.instantiation |
| a coercion to `any Trait` | refused when an implementation it dispatches to may suspend | effect.any-suspends, effect.any-suspends.instantiation |
| a call in a `borrows(sync)` window, `borrow` block or `for` | refused when it may suspend | borrows.sync-window; body_rules |
| a call site of a body that copies its `T` | the Copy tier of the site's argument | summaries; copy.requirement; path_uses |

**The per-path use count** (design 219, `compiler/typecheck/README.md`, "The
per-path use count"): where a by-value read of a generic body's local stands,
and whether it duplicates the local. A function named is one of
`golden/path_uses.saw`'s; a program named is a golden program or a fixture.

| position | answer | covered by |
|---|---|---|
| one read on the path, the parameter forwarded into a construction | `move`, no requirement | `Wrap.init`, body_types, inference |
| one read in each arm of an `if` | `move` | `larger` |
| one read in each arm of a `match` | `move` | `arms` |
| the right side of `??`, which a path may skip | `move` | `either` |
| two reads on one path | `copy`, the requirement, both quoted | `twice`; copy.requirement |
| a read in a loop's body | `copy`, the requirement, quoted alone | `repeated` |
| a read in a closure's body | `copy`, the requirement, quoted alone | `captured` |
| a read, then a borrow on the same path | `copy`, the requirement, both quoted | `peeked` |
| a read on a path a `return` ends, and one after it | `move` | `early`, `guarded` |
| a read on a path a `break` carries past the loop, and one after the loop | `copy`, both quoted | `broken` |
| a spelled `move`, and nothing after it | `move`, no requirement | `moved` |
| a read, an assignment, a read | `move` each | `refilled` |
| a read of a field of a type parameter's type | `copy`, the requirement at one read | `field` |

**A discarded `Result`** (design 151):

| position | covered by |
|---|---|
| a bare statement | result.discarded |
| a `Void` body's tail | result.discarded (its last statement) |
| a loop body's tail | result.discarded.loop |
| an arm of a statement-position `match` | result.discarded.arm |
| an arm of a statement-position `if` | result.discarded.if |
| a `Void` closure's tail | result.discarded.closure |
| `let _ =`, the out | exhaustive |

**Exhaustiveness**:

| scrutinee | covered by |
|---|---|
| an enum, a case missing | match.non-exhaustive; exhaustive |
| a case covered only by a guarded arm | match.non-exhaustive.guard; exhaustive |
| `Bool` | match.non-exhaustive.bool |
| an optional, nested | match.non-exhaustive.optional; exhaustive |
| a tuple of constructor types | match.non-exhaustive.tuple; exhaustive |
| an integer or `String` by literals and ranges | match.non-exhaustive.literal; exhaustive |
| `Result` | exhaustive |
| an inline-recursive enum with wildcards | type.infinite-size.matched |

**Borrowing-struct containment** (spec, Borrowing structs; SL:borrowing §2.6):

| position | verdict | covered by |
|---|---|---|
| a `let` or `var` binding, a pattern binding | refused | borrowing.containment |
| a parameter taken by value | refused | borrowing.containment.parameter |
| a field | refused | borrowing.containment.field |
| a payload | refused | borrowing.containment.payload |
| an erasure to an existential | refused | borrowing.containment.erase |
| a result not lent with `borrows` | refused | borrowing.containment.return |
| a function type's parameter or result | refused | borrowing.containment.function-type |
| a `for` head, a `borrow` head, a reference parameter | allowed | body_rules |

## The safety matrices

The rows of the three safety families (SL-462): each row a refusal fixture
(`refuse/RULE.VARIANT`) or the golden program that allows it.

**Mutability** (spec, Variables and Mutability: "Bindings always initialize";
Reference Types). Every position that writes a place or borrows it
exclusively reaches `place_verdict` (`compiler/typecheck/src/mutability.saw`),
whose docstring names them: an assignment, a compound assignment, `&var`, a
`&var self` receiver (the builtin `take()` and an array's `swap` too), `borrow
var` (argument, block head, unwrap, and the statement form's place, written
whole or through a projection), a write through a bare `borrow` statement,
which lends its place shared (SL-487), an exclusive `lend`, the window of a
`borrows` accessor opened exclusive, a window read through an accessor that
borrows its receiver exclusively at every use (a `&var self` one with no
shared twin, SL-470), and a `[&var x]` capture. Under
`mutability.immutable`:

| row | verdict | covered by |
|---|---|---|
| assigning a `let` local | refused | mutability.immutable |
| compound-assigning a `let` local | refused | mutability.immutable.compound |
| `&var x` of a `let` | refused | mutability.immutable.exclusive-ref |
| a field of a `let` struct | refused | mutability.immutable.field |
| a tuple element of a `let` | refused | mutability.immutable.tuple-element |
| a fixed-array element of a `let`, plain and compound, through a field | refused | mutability.immutable.array-element, mutability.immutable.array-element-compound |
| a `Vector` element of a `let` root (an exclusive window) | refused | mutability.immutable.vector-element |
| `m[k]! = v` on a `let` `Map` root | refused | mutability.immutable.map-force |
| the payload of a `let` optional, `o!.n = v` | refused | mutability.immutable.optional-payload |
| a hand-written accessor's window on a `let` root | refused | mutability.immutable.accessor-root |
| a `&var self` method on a `let`, NoCopy and automatic Copy | refused | mutability.immutable.exclusive-receiver, mutability.immutable.copy-receiver |
| `v.push` on a `let` Vector | refused | mutability.immutable.vector-push |
| a `&var self` method through an inline array element of a `let` | refused | mutability.immutable.array-element-receiver |
| the builtin `take()` on a `let` optional | refused | mutability.immutable.take |
| a write through `&T`: compound, replacement, a `&var self` method | refused | mutability.immutable.shared-reference, mutability.immutable.shared-reference-replace, mutability.immutable.shared-reference-receiver |
| a write through a closure's `&T` parameter | refused | mutability.immutable.shared-closure-parameter |
| a write through a named accessor lending read-only, `-> &T` | refused | mutability.immutable.read-only-lend |
| a `borrow var` statement writing through a read-only lend: a field, compound, the whole place, on a `let` root (SL-487) | refused | mutability.immutable.read-only-lend-statement, -compound, -whole, -let |
| a bare `borrow` statement written through: a field, compound, a `&var self` method, the whole place, on a `let` root, through a `&T` parameter (SL:borrowing §2.2, SL-487) | refused | mutability.immutable.shared-borrow, -compound, -method, -whole, -let, -parameter |
| a `borrow var` statement on a `let` root, through one exclusive window and through two nested ones (SL-487) | refused | mutability.immutable.borrow-statement, mutability.immutable.borrow-statement-chain |
| a write through a subscript lending read-only | refused | subscript.role.setitem |
| `&self` writing a field, `self = v`, an inline array element | refused | mutability.immutable.shared-receiver, mutability.immutable.shared-self-replace, mutability.immutable.shared-receiver-array |
| `&self` calling a `&var self` method on `self` or a field, projecting `&var self.f` | refused | mutability.immutable.shared-receiver-call, mutability.immutable.shared-receiver-field-call, mutability.immutable.shared-receiver-projection |
| `&self` writing through a window on inline storage | refused | mutability.immutable.shared-receiver-window |
| a `&self` `borrows` body writing a field in its epilogue | refused | mutability.immutable.shared-receiver-epilogue |
| a `[&self]` capture's write in a `&var self` method | refused | mutability.immutable.shared-capture-self |
| a `for` loop's, an `if let`'s, a `guard let`'s, a `match` arm's binding | refused | mutability.immutable.for-binding, mutability.immutable.if-let, mutability.immutable.guard-let, mutability.immutable.match-binding |
| a `let` destructuring's binding, a closure's parameter | refused | mutability.immutable.destructure, mutability.immutable.closure-parameter |
| a `borrow let` binding | refused | mutability.immutable.borrow-let |
| a `let` declared in a loop body, assigned in the loop | refused | mutability.immutable.loop-let |
| a parameter taken by value | refused | mutability.immutable.parameter |
| a by-value capture, and a field of one | refused | mutability.immutable.value-capture, mutability.immutable.value-capture-field |
| a plain, `move` or `copy` capture, in an escaping or a non-escaping closure (SL-472: a `let` in the body), written by `x = v`, `x += v`, `x.f = v`, `x[i] = y` (a `Vector`'s heap element included), a `&var self` method, `&var x`, `take()`: one fixture per cell, `capture-KIND-WRITE-CLOSURE` | refused | mutability.immutable.capture-* (the plain non-escaping assignment and field cells are value-capture and value-capture-field) |
| an array's `swap` on a `move` capture | refused | mutability.immutable.capture-move-swap-nonescaping |
| copies of one escaping closure sharing a counter in a `[move v]` capture's heap buffer | refused | mutability.immutable.capture-shared-environment |
| a nested `[&var n]` of an outer by-value capture | refused | mutability.immutable.capture-reborrow-of-value |
| a `[&x]` capture's write | refused | mutability.immutable.shared-capture |
| `[&var x]` of a `let` | refused | mutability.immutable.exclusive-capture |
| a plain `static` | refused | mutability.immutable.static |
| a `var`, its fields and elements; `&var` of one; a `&var self` method on one | allowed | mutability |
| `r = v` and `r += v` through a `&var` parameter (design 110), and its reborrow `&var r` | allowed | mutability |
| `self = v` and field writes under `&var self` | allowed | mutability |
| writes to `self.f` in a `consumes` body | allowed | mutability |
| a `let` declared in a loop body, taking a fresh value each iteration | allowed | mutability |
| `var` destructuring, `if var`, `guard var`, `borrow var` | allowed | mutability |
| the `borrow var` statement on a `var` root: assigned, compound-assigned, a `&var self` method through it; a bare `borrow` read | allowed | mutability |
| a `[&var x]` capture's write | allowed | mutability |
| a nested `[&var n]` of an outer `[&var n]`; the counter through a non-escaping `[&var v]` | allowed | capture_rules |
| an implicit `self` capture's write under `&var self`; a write through a plain capture of a `&var` parameter; a closure's own `&var` parameter written | allowed | capture_rules |
| a `&self` cell method (`Mutex.lock`) on a `move` capture; a captured raw pointer's pointee, escaping too | allowed | capture_rules |
| a `&var self` method through a `[move h]` capture of an `UnsafeRef`, as through a `let h` | refused | mutability.immutable.capture-unsafe-handle |
| a move into a place window, `slots[0].push(move h)`; the non-escaping `[move v]` idiom `var w = move v` | allowed | capture_rules |
| an `unsafe static var` | allowed | mutability |
| a raw pointer's pointee, through a `let` pointer or a `&self` receiver | allowed | mutability |
| `&self` writing storage the receiver points at (SL:borrowing §9, SL-483): a `Vector` field's element assigned, compound-assigned, passed `borrow var`, opened in a `borrow var` block; a `&var self` method of one; a hand-written accessor lending out of a `Vector`; a nested chain; a `[&self]` capture's write; a prologue write in a `&self` `borrows` body; a read through a `&var self` accessor with no shared twin | refused | mutability.immutable.shared-receiver-heap, -heap-compound, -heap-argument, -heap-block, -heap-method, -heap-accessor, -heap-chain, mutability.immutable.shared-capture-heap, mutability.immutable.shared-accessor-heap, mutability.immutable.exclusive-only-heap |
| a raw pointer's pointee from `&self`: `p[0] = v`, `*p = v`, a pointer read out of a `Vector` field (SL:open-questions D28); a `&self` accessor's lend, whose receiver is only read (SL:borrowing §3); storage the receiver points at under `&var self` | allowed | mutability |
| a `&self` `borrows` body writing through a window on `self`'s inline storage (row M33) | refused | mutability.immutable.shared-accessor-window |
| a read through a `&var self` accessor with no shared twin, on a `let` root, at each window opener: a subscript, a named accessor, a conditional lend through `!`, a `borrow let` head, a `for` head, a nested window, a method call's receiver; a `&self` accessor forwarding its lend through one (rows K123, K125, K129) | refused | mutability.immutable.exclusive-only-subscript, -accessor, -conditional, -borrow-let, -for-head, -nested, -receiver, -forwarded-lend |
| reads through a `&var self` accessor on a `var` and through a `&var` parameter; on a `let` root, through a `@synthesize(shared)` twin or a hand-written `&self` overload (rows K123, K127, K128) | allowed | exclusive_only |
| a chain of hops settles from its use outward: a write through the last hop borrows every earlier hop's receiver exclusively and picks the exclusive accessor over its twin, at a subscript and a named accessor; a read leaves each hop shared (SL-490) | allowed | chain_settle |
| a `var` parameter | none: the grammar has no `var` parameter | |
| an interior cell's `&self` method on a `let` (`Atomic`, `Mutex`, `SpinLock`) | allowed: a `&self` method borrows shared, so no row reaches the funnel; the cells' constructions are `slice.not-yet` | |

**Reference positions** (spec, Reference Types: "References cannot escape").
Every outermost written type passes `reference_position_of`
(`compiler/typecheck/src/refpositions.saw`), whose docstring names the
written positions; the walk reads the type an alias stands for and stops at a
function type, whose own nodes answer. Under `type.reference-position`:

| row | verdict | covered by |
|---|---|---|
| a free function's, a method's, a requirement's, an extern's return | refused | type.reference-position.return, type.reference-position.method-return, type.reference-position.requirement-return, type.reference-position.extern-return |
| a function type's return, written as a parameter's or a field's type | refused | type.reference-position.function-type-return, type.reference-position.field-function-type |
| a return naming one in a tuple, an optional (`&Int?`), a type argument | refused | type.reference-position.return-tuple, type.reference-position.return-optional, type.reference-position.return-vector |
| a struct field, an enum payload, a static | refused | type.reference-position.field, type.reference-position.payload, type.reference-position.static |
| an exclusive field of a borrowing struct | refused | type.reference-position.borrowing-field |
| a type argument, in a parameter's type too: `Vector`, `Map`'s value, `Optional<&T>` written, `Box`, nested | refused | type.reference-position.type-argument, type.reference-position.map-value, type.reference-position.optional-written, type.reference-position.box, type.reference-position.nested-generic |
| a type argument written at a call, `idn<&Int>(&x)` | refused | type.reference-position.explicit-instantiation |
| an alias used as a field's or a return's type | refused | type.reference-position.alias-field, type.reference-position.alias-return |
| an associated-type assignment, a generic parameter's default | refused | type.reference-position.associated-type, type.reference-position.generic-default |
| a `let` annotation | refused | type.reference-position.local-annotation |
| a reference inside a `borrows` lend, `&(Int, &Int)` | refused | type.reference-position.lend-nested |
| `let r = &x`, `var r = &var x`: a bare `&` bound | refused | type.reference-position, type.reference-position.exclusive-binding |
| a bare `&` in an array literal, a tuple literal, an operator's operand, a closure's tail, a cast to an integer | refused | type.reference-position.array-literal, type.reference-position.tuple-literal, type.reference-position.operand, type.reference-position.closure-return, type.reference-position.cast-to-integer |
| a binding whose inferred type names a reference: only a bare `&` builds one, as an argument instantiating a generic | refused | type.reference-position.inferred-binding |
| a reference binding passed with no sigil to a reference parameter, a function's, a `&var` one's, a method's; and to the reference overload when no by-value one fits | refused, `type.mismatch` with the sigil written out | type.mismatch.unsigiled-reference, type.mismatch.unsigiled-exclusive, type.mismatch.unsigiled-method-argument, type.mismatch.unsigiled-overload |
| `&var x` for a `&T` parameter: a free function's, a method's, a static method's, an initializer's, by label, a function value's; `borrow var p` for one (SL-484) | refused, `type.mismatch` naming `&x` or `borrow p` | type.mismatch.sigil-exclusive, -exclusive-method, -exclusive-static, -exclusive-init, -exclusive-labeled, -exclusive-closure, -exclusive-borrow |
| `&x` or `&var x` for a parameter taken by value: Copy, NoCopy through a reference, ExplicitCopy, a generic method's `T` (SL-484) | refused, `type.mismatch` dropping the sigil | type.mismatch.sigil-to-value, -to-value-exclusive, -to-value-nocopy, -to-value-explicit, -to-value-generic |
| an operator's reference operand, `a + &b` | refused as a bare `&` operand before any sigil question | type.reference-position.operand |
| each call shape with its parameter's own sigil; a `&var` reference forwarded as `&`; `f(p)` picking `f(Int)` over `f(&Int)`; Stage 0's `s.compare(&t)` reaching the requirement | allowed | call_sigils |
| a reference to a NoCopy value read by value into an aggregate | refused, `transfer.implicit-copy` | transfer.implicit-copy.reference-read |
| a generic instantiated at a reference by inference | refused | type.reference-position.instantiation |
| a bare trait behind a reference, `&Shape` | refused | type.not-a-type.trait |
| a parameter: `&T`, `&var T`, `&[T]`, `&any Trait`, an alias of a reference, an extern's | allowed | reference_positions |
| a function type's parameter, `(&Int) sync -> R` | allowed | reference_positions |
| a `borrows` lend: `-> &T`, `-> &var T`, `-> &var T?` (SL:borrowing §2) | allowed | reference_positions |
| a borrowing struct's shared field (spec, Borrowing structs; `borrowing.containment` keeps its values in their window) | allowed | reference_positions |
| a type alias standing for a reference | allowed | reference_positions |
| a bare `&` as a call argument, and as the operand of a cast to a raw pointer (DF-163f) | allowed | reference_positions |
| a reference read through a binding into an unannotated `let` or a closure's inferred result, which gives the value | allowed | reference_positions |
| the same read at every value-building position: a tuple, array, collection or map element, a construction's field, a payload, an auto-wrap, a segment or format argument, a value branch's arm, a tail, a `return`, a by-value argument, a generic argument inferring the referent; the sigiled forwards `&p`, `&var q`, and a receiver (SL-474) | allowed | reference_reads |
| a generic whose parameter is `&T`, called with `&x`, which solves `T` to the referent | allowed | reference_positions |

**Field move-out** (spec, "NO partial moves"; Moving a field out). Checked as
the walk meets a `move` (`check_whole_move`):

| row | verdict | covered by |
|---|---|---|
| `move h.v`, a struct field | refused | transfer.partial-move |
| `move t.0`, a tuple element | refused | transfer.partial-move.tuple-element |
| `move h.s!`, an optional field's payload | refused | transfer.partial-move.payload |
| `move v[i]` on a `Vector`, on a fixed array | refused | transfer.partial-move.vector-element, transfer.partial-move.array-element |
| `move p.a.b`, a nested path | refused | transfer.partial-move.nested |
| `move r.f` through `r: &var S`, in a `consumes` body | refused | transfer.partial-move.through-reference |
| `move self.a.b` in a `consumes` body | refused | transfer.partial-move.consumes-nested |
| `move self.f` outside a `consumes` body | refused | consumes.move-self |
| `move r` of a reference binding, `&var` and `&` | refused | transfer.move-from-borrow, transfer.move-from-borrow.shared |
| `move` of a pattern binding that aliases a borrowed scrutinee's part, through a reference or `self` | refused | transfer.move-from-borrow.match-payload, transfer.move-from-borrow.match-self |
| `move` of a closure's reference parameter | refused | transfer.move-from-borrow.closure-parameter |
| `move` of a payload binding where the scrutinee is a name reading through a borrow: a `borrow let`, a `borrow var`, an `if borrow let` unwrap binding, a payload binding matched again, a `[&s]` capture (SL-478) | refused | transfer.move-from-borrow.borrow-let, .borrow-var, .borrow-unwrap, .borrow-payload, .borrow-capture |
| `move` of a `borrow let` binding itself, and of a `[&s]` capture (row V69) | refused | transfer.move-from-borrow.borrow-binding |
| a `match` on such a name reading its payloads in place, a Copy payload copied out | allowed | borrowed_scrutinees |
| a plain binding of a lent optional place's payload, the place a `borrow` binding or a field of one: `if let`, `guard let`, `while let`, `case Some(x)`, over a `&self`, a `&var self` and a cell-carrying conditional lend, a NoCopy payload (SL:borrowing §2.4, SL-492) | refused, the hint naming `borrow let` | transfer.implicit-copy.lent-if, .lent-guard, .lent-while, .lent-match |
| a `var` binding of a lent optional place's payload: `if var` over each of the three lends, `guard var`, `while var`, a lent place's optional field (SL-492) | refused | borrowing.var-unwrap, .shared, .cell, .guard, .while, .field |
| the same heads copying a Copy payload; `borrow let|var` binding it in place; `_` testing presence; a conditional lend called without `borrow`, whose payload is copied out, so `if var` writes the copy (SL-492) | allowed | lent_unwrap |
| a whole binding, `move o!`, `move self.f` in a `consumes` body, `move buf[i]` through a raw pointer | allowed | field_moves |

**Relocation** (design 188: a `NoMove` value moves once, into its home).
Checked as the walk meets a `move` (`check_no_move`), a `[move x]` capture and
`take()`, under `transfer.no-move`; `n.` abbreviates
`refuse/transfer.no-move.`:

| row | verdict | covered by |
|---|---|---|
| a consuming call's receiver, `(move p).finish()` (row V53) | refused | `transfer.no-move` (bare) |
| a bound value moved into an argument (row V59) | refused | n.argument |
| a by-value parameter placed after a `&` named it (row V58) | refused | n.placement-after-borrow |
| a move into a binding, of a generic instance holding one | refused | n.binding |
| a `[move a]` capture; `take()` out of an optional; a tuple holding one | refused | n.capture, n.take |
| a fresh by-value parameter placed by `ptr[0] = move value`; lending by `&var`; replacing a referent whole | allowed | no_move |

The declaration side (SL-485; rows V121-V123), checked with the
containment rules (`check_no_move_declarations`):

| row | verdict | covered by |
|---|---|---|
| a struct's `NoMove` field, an enum's payload, one in an optional, a generic instance at a `NoMove` argument, undeclared | refused | nomove.undeclared, .payload, .wrapped, .instance |
| `T: NoMove` on a function's and on an extension's parameter | refused | nomove.bound, nomove.bound.extension |
| `NoMove` with no declared `NoCopy`, beside `ExplicitCopy` | refused | nomove.requires-nocopy, nomove.requires-nocopy.explicit |
| a container declaring `NoCopy` and `NoMove`; a pointer holder; a generic holding `T` | allowed | no_move |

**Generic captures** (SL-481, D30). A spelled `[copy x]` of a value whose
type names a type parameter is refused at the definition unless a bound
grants the copy (`add_capture`); a silent by-value capture, `[x]` or
implicit, is design 219's inferred requirement, recorded through the same
copy items a getitem's copy reaches (`implied_copies`, then the summaries'
`copy_needs`) and checked at each call:

| capture | verdict | covered by |
|---|---|---|
| `[copy x]` of an unbounded `T`, of `(T, Int)`, of a `T?` with `T: ExplicitCopy` | refused at the definition, `capture.copy` | capture.copy.generic, -generic-tuple, -generic-optional |
| `[x]`, an implicit capture of an unbounded `T`, called at a NoCopy type | refused at the call, `copy.requirement` | copy.requirement.capture-value, copy.requirement.capture-implicit |
| `[copy x]` at `T: ExplicitCopy` and `T: Copy`; `[move x]` unbounded; `[x]` and an implicit capture called at `Int` | allowed | generic_captures; MIR golden `closures` |

**Plain subscript reads** (SL:open-questions D29; SL:borrowing §1, §5.2: a plain
subscript is a getitem wherever it is read). Settled once places are
(`check_plain_subscript_reads`), over every accessor subscript whose use
borrows or projects without writing and whose projection does not end in a
position that lends (`lends_in_place`: the `borrow` forms, `lend`, a `for`
head). A sigil on an accessor's place lends nothing: it is refused itself, by
`borrowing.sigil-place` (below). Under `transfer.implicit-copy`, `g.`
abbreviating `refuse/transfer.implicit-copy.getitem-`:

| position | verdict | covered by |
|---|---|---|
| an interpolation hole; `print`'s message; a `{}` format argument of `print`, `assert`, `panic` | refused, NoCopy element | g.interpolation, g.message, g.format, g.assert, g.panic |
| a comparison operand | refused | g.comparison |
| a field read, a `&self` method, a chained hop off the subscript | refused | g.field, g.method, g.chain |
| a member hop or a subscript off an ExplicitCopy element, with no `.copy()` | refused | g.explicit, g.subscript |
| a `match` whose arm binds a payload | refused | g.scrutinee |
| an element of a type parameter's type, hopped off in a generic body | design 219's inferred requirement, refused at a NoCopy call | copy.requirement.getitem-hop |
| each position spelled `borrow`; `.copy()` on an ExplicitCopy element; Copy-tier elements plain; a `match` binding nothing; a generic at a Copy type | allowed | plain_subscript_reads |

**Sigils on an accessor's place** (SL:borrowing §2.2, §9: `bump(&var g[4])`
becomes `bump(borrow var g[4])`). `ref_expr` follows the operand's fields,
tuple elements, payloads and builtin elements down (`sigil_accessor`), and a
`borrows` call there is `borrowing.sigil-place`, `s.` abbreviating
`refuse/borrowing.sigil-place`:

| position | verdict | covered by |
|---|---|---|
| `&var v[0]`, `&v[0]` as a function's argument | refused, the fix-it `borrow var` / `borrow` | s, s.shared |
| a field of the place, `&var v[0].n`; a chained subscript, `&var g[0][1]`; a named accessor, `&var bag.at(0)` | refused | s.field, s.chain, s.named |
| a method call's argument, `t.absorb(&var v[0])` | refused | s.method-argument |
| a local, a field path, a fixed array's element, a raw pointer's element (`(&buf[i]) as UnsafePointer<T>`) | allowed | sigil_places |

**Escaping function values** (SL:open-questions D35). A function type in a
storage position is escaping whatever it spells: only a parameter's keeps the
word, recorded on the parameter (`TcParam.escaping`) while its type takes the
storage form (`build_param_type`, `strip_escaping`), so one type serves every
storage position. A non-escaping value, a parameter whose function type does
not say `escaping` or a local bound to one (`nonescaping_bindings`), is judged
where it lands (`check_escape`, `check_escaping_argument`, `check_assign`,
`add_capture`), under `escaping.stored`, `e.` abbreviating
`refuse/escaping.stored`:

| position | non-escaping value | escaping value |
|---|---|---|
| a struct field, in a construction and in an assignment | refused: e, e.assign | allowed: escaping_values (written plain and spelled `escaping`) |
| an enum payload | refused: e.payload | allowed: escaping_values |
| a `Vector` element, through `push`'s type parameter | refused: e.element | allowed: escaping_values |
| an Optional | refused: e.optional | allowed: escaping_values |
| a static | none reaches it: a static's initializer is a constant, and an `unsafe static var` holds only trivially destructible values | |
| a capture into an escaping closure | refused: e.capture | allowed: escaping_values |
| a return | refused: e.return | allowed: escaping_values |
| a type argument, inferred or written, `id(f)`, `id<() -> Int>(f)` | refused: e.generic-inferred, e.generic-written | allowed |
| an `escaping` parameter | refused: e.escaping-parameter | allowed |
| a call; a parameter that does not escape; a local `let g = f`, which keeps the kind (e.bound refuses storing `g`); a capture into a closure that does not escape, where the kind holds (e.inner refuses storing it there) | allowed: escaping_values | allowed: escaping_values (a lend) |

**Declared bounds** (design 219: a generic's signature covers its body's
inferred Copy requirement where it publishes or declares one), under
`copy.declared-bound`: a public generic function (row V45) and a public
generic method whose requirement a callee brings refuse, `copy.declared-bound`
and `.method`; a declared `ExplicitCopy` the body exceeds (row V46),
`.explicit`. A private generic rides inference, its call sites checked by
`copy.requirement` (`summaries`), an indexed place read included (row P12,
`copy.requirement.indexed-place`, and golden `indexed_place_requirement`).

**Escaping consumes** (SL-469: an escaping closure's environment is shared by
every copy and outlives each call). Checked once captures are settled
(`check_escaping_consumes`, `compiler/typecheck/src/captures.saw`), under
`capture.escaping-consume`; `c.` abbreviates `refuse/capture.escaping-consume.`:

| row | verdict | covered by |
|---|---|---|
| a returned closure, one stored in a field, one bound to a `let`, one passed to an `escaping` parameter, each consuming its `move` capture by a `move` argument, a tail, a `return`, a `consumes` call, a destructuring, a move into a constructed value's field | refused | `c.ESCAPE-USE`, ESCAPE in returned, stored, bound, parameter; USE in argument, tail, return, consumes, destructure, field |
| a `match` consuming an owned capture | refused | c.match |
| an inner closure's `[move r]` of the outer escaping closure's capture | refused | c.inner-capture |
| a `[copy s]` capture of a `String`, a `[copy v]` of a `Vector`, an implicit `String` capture, moved | refused | c.copy-string, c.copy-vector, c.implicit |
| conformance row V49's shape | refused | `capture.escaping-consume` (bare) |
| a non-escaping closure consuming its `move` capture | allowed | capture_rules |
| a `Thread.spawn` brace consuming its capture | allowed: the brace is exempt; the form is `slice.not-yet` | |

## The conformance rows

The rows of `examples/conformance/INDEX.md`'s Mutability and References
sections, and V03–V05, V31, V49, V60–V62, V68 and V70 of its Moves section, each
with what covers it here; `compiler/tests/borrowck/CONFORMANCE.md` names the
same fixtures. `m.` abbreviates `refuse/mutability.immutable.`, `r.`
`refuse/type.reference-position.`, `p.` `refuse/transfer.partial-move.` and
`b.` `refuse/transfer.move-from-borrow.`; a bare name is the rule's own
fixture.

| rows | covered by |
|---|---|
| M01, M02, M03, M04, M05 | `m` (bare), `m.compound`, `m.exclusive-ref`, `m.field`, `m.exclusive-receiver` |
| M06, M07, M08, M09 | `m.vector-push`, `m.array-element`, `m.vector-element`, `m.tuple-element` |
| M10, M11, M12 | `m.shared-reference`, `m.shared-reference-replace`, `m.shared-reference-receiver` |
| M13, M14, M15, M16 | `m.shared-receiver`, `m.shared-receiver-call`, `m.shared-receiver-field-call`, `m.shared-receiver-projection` |
| M17, M18, M19, M20, M21 | `m.for-binding`, `m.if-let`, `m.parameter`, `m.value-capture`, `m.value-capture-field` |
| M22, M23, M24, M25, M26 | `m.accessor-root`, `m.shared-closure-parameter`, `m.shared-receiver-epilogue`, `m.map-force`, `m.copy-receiver` |
| M27 | `slice.not-yet` (a method call on `any Trait`); an interior cell's `&self` method borrows shared, which no row of the funnel asks about |
| M28, M32, M41 | language changed (SL:borrowing §9, SL-483): `m.shared-receiver-heap-method` (M28), `m.shared-receiver-heap-chain` (M32), `m.shared-receiver-heap`, `-heap-compound`, `-heap-accessor` and `-heap-chain` (M41) |
| M34, M35 | accepted: golden `mutability` (writes under `&var self`) |
| M33 | `m.shared-accessor-window`: a `&self` accessor's prologue writing a window on inline storage; its heap form, `m.shared-accessor-heap` (SL-483) |
| M29 | accepted: golden `mutability`, `borrow_arguments` |
| M30, M31, M36, M37 | `m.static`, `m.shared-receiver-window`, `m.shared-capture-self`, `m.array-element` and `m.array-element-compound` |
| M38 | the borrow check (U6d2) |
| M39, M40 | `slice.not-yet` (`syntax.stmt.optional-assign`) |
| M42, M43, M44 | `m.shared-receiver-array`, `m.optional-payload`, `m.array-element-receiver` |
| R01, R02, R03, R04, R05 | `r.return`, `r.method-return`, `r.requirement-return`, `r.extern-return`, `r.function-type-return` |
| R06, R07, R08, R09, R10 | `r.return-tuple`, `r.return-optional`, `r.return-vector`, `r.field`, `r.payload` |
| R11, R12, R13, R14, R15 | `r` (bare), `r.exclusive-binding`, `r.type-argument` and `r.local-annotation`, `r.explicit-instantiation`, `r.closure-return` |
| R16, R17, R18, R19, R20, R21 | `r.array-literal`, `r.tuple-literal`, `r.map-value`, `r.static`, `r.alias-field`, `r.alias-return` |
| R22, R23 | `capture.escaping-borrow` and `capture.escaping-borrow.explicit`: a closure bound to a `let` or passed to an escaping parameter, the `[&x]` spelling |
| R24, R25 | `slice.not-yet` (`TaskGroup.spawn`, task-group-spawn): due when spawn enters the slice |
| R26, R27, R29, R31, R32, R34 | `r.optional-written`, `r.nested-generic`, `r.cast-to-integer`, `r.operand`, `r.box`, `r.field-function-type` |
| R28, R30, R33 | accepted: golden `reference_positions` (the pointer cast, the `borrows` lends), `captures` (a non-escaping borrow capture) |
| V03, V04 | `b` (bare), `b.shared` |
| V05, V31 | `p` (bare), `p.vector-element` |
| V60, V61, V62 | `b.match-payload`, `b.match-self`, `b.match-payload` (a Copy-tier payload) |
| V68, V70 | `b.closure-parameter` |
| V49 | `capture.escaping-consume` (bare): an escaping closure's consume of its `move` capture is refused (SL-469) |
| R43, R44 | `capture.escaping-borrow.reference-container`, `capture.escaping-borrow.local-container` (SL-467) |

That is 44 M rows, 36 R rows and 10 V rows: 78 refused here, 6 accepted
here, 5 answered by `slice.not-yet` and 1 by the borrow check.

## Refusals

Each rule's fixture is `refuse/RULE.saw`, or `refuse/RULE.VARIANT.saw` for one
of several positions. A fixture's first line is

```
// refuses: RULE at L:C
```

and its first `ERROR` must carry that rule at that position. The second line
says what the fixture shows.

| rule | refuses |
|---|---|
| `type.not-a-type` | a type position that names something not a type: a case, a module, a function; a trait, with the hint `any Trait` |
| `type.not-a-trait` | a bound, a trait's parent or a conformance that names something not a trait |
| `type.arity` | more type arguments than parameters, fewer than those with no default, arguments on a type parameter or `Self`, an extension renaming a different number of parameters than its type has |
| `type.argument-kind` | a type for a const parameter, a value for a type parameter |
| `type.bound` | a type argument, or a default, that does not satisfy its parameter's bound, for every kind of type, primitives included (design 109); a member of a bounded extension or conformance on a receiver whose arguments do not meet its bounds, and the builtin `copy()` reaching a type parameter no bound makes `ExplicitCopy` (SL-463) |
| `type.default` | a parameter with no default after one with a default; a default that names a type parameter |
| `type.alias-cycle` | type aliases that stand for each other |
| `type.infinite-size` | a struct or enum whose storage contains its own inline, through fields, payloads, tuples, optionals, arrays and the generic declarations they instantiate, or through ever larger instantiations |
| `conformance.incomplete` | a requirement of a trait, or of a trait it refines, that nothing meets: no member written, no default, no derivation; an associated type no type assignment gives, the conformance's own or, for a parent trait's, the type's conformance to that trait (refined_assignments) |
| `conformance.associated-conflict` | a refining trait's conformance restating a parent trait's associated type as another type than the type's conformance to the parent assigns |
| `conformance.signature` | a written member that disagrees with its requirement: receiver, staticness, type parameters, parameters, result, an `unsafe` the requirement declares, `consumes`, or `borrows` (a `borrows(sync)` member never meets a plain `borrows` requirement, SL:borrowing §2.5) |
| `synthesize.required` | a declared conformance to a derivable trait whose method is neither written nor asked for with `@synthesize` (design 128) |
| `synthesize.inert` | `@synthesize` on a conformance that derives nothing |
| `nomove.undeclared` | a struct or enum holding a `NoMove` value inline, a field, a payload, through an optional, a tuple, an array or a generic instance, that does not declare `NoMove` itself (design 188) |
| `nomove.bound` | `NoMove` written as a generic parameter's bound |
| `nomove.requires-nocopy` | a `NoMove` conformance on a type whose policy is not a declared `NoCopy` |
| `copy.undeclared-policy` | a struct or enum with no policy holding an ExplicitCopy or NoCopy member, or a struct with a field of a declared Copy type |
| `unsafe.undeclared` | a function whose parameters, result or receiver name an unsafe type, or whose body (its closures included) names, binds, receives or returns a value of one or names an `unsafe static var`, and which is not declared `unsafe` (designs 130, 136 and 149) |
| `unsafe.function-type` | a function type that names an unsafe type without saying `unsafe`, or says it without naming one |
| `unsafe.type-name` | an `unsafe struct` not named `Unsafe*` |
| `init.result` | an `init` returning neither its receiver nor `Result<Receiver, E>`; an optional on its own terms |
| `conformance.deinit` | a conformance to `Deinit` itself, which a copy policy carries instead (design 131) |
| `deinit.outside-policy` | a `deinit` written in an extension that declares no copy policy, beside the type's policy or on a type with none, where no scope exit would call it (spec, The Deinit trait) |
| `extension.default-omitted` | an extension head renaming its type's parameters that leaves out a defaulted one, with the head written out (D14) |
| `type.mismatch` | a value that does not convert to what its position expects, one fixture per funnel position and one per cell of the wrap and erasure matrix a position refuses; a condition that is not a `Bool`; a pattern that does not fit its value; operands that disagree; a bare integer literal, or a constant expression's literal or leaf, that does not fit the type it adopts; a constant expression whose typed arithmetic overflows, shifts past its width or divides by zero; a literal past its signed suffix's range (D6) |
| `type.ambiguous-result` | a value both of a Result slot's payloads could take |
| `type.not-a-value` | a type, module or trait named where a value is read |
| `type.not-a-place` | a value where a place is needed: an assignment's target, `move`, `&var` |
| `type.cast` | an `as` between types it does not convert |
| `type.try` | a `try` propagating out of a body that returns no Result, or into one whose error type does not take its error |
| `member.unknown` | a field or method the type does not have, or this module does not see; the builtin `copy()` on a NoCopy value |
| `call.arity` | too many arguments, a missing one, a case built without its payload |
| `call.label` | a label no parameter has, one naming a parameter behind the last bound, a repeated label |
| `call.ambiguous` | overloads the arguments fit equally, named |
| `call.no-match` | no overload the arguments fit, each named |
| `call.not-callable` | a call of a value that is no function |
| `call.field-method-ambiguous` | `h.f(x)` where `f` names both a field holding a function and a method this module sees, with the fix-it `let g = h.f; g(x)` (D16) |
| `infer.failed` | a type argument nothing determines or two arguments disagree on; `None` or an empty literal with nothing expected, though not one whose slot holds a type already refused, which adopts the error type |
| `implicit-member.no-type` | an implicit member where nothing expects a type, with the `Enum.Case` fix-it |
| `mutability.immutable` | a write or an exclusive borrow of a place nothing makes writable: rooted in a `let`, a pattern's, a `for` loop's or a closure parameter's binding, a parameter taken by value, a plain `static`, `self` under `&self`, a binding a closure captured by value (in every closure, SL-472) or by shared borrow, or reached through a shared reference or a read-only lend (the mutability matrix) |
| `type.reference-position` | a reference where a type is stored, returned or bound: every written position but a parameter, a function type's parameter, a `borrows` lend and a borrowing struct's shared field, at any depth; a bare `&` outside a call argument or a pointer cast; a binding inferred to name one; a call instantiated at one (the reference-position matrix) |
| `transfer.partial-move` | a spelled `move` of a part of a binding: a field, a tuple element, an element, an optional field's payload, at any depth (the field move-out matrix) |
| `transfer.move-from-borrow` | a spelled `move` of a binding that owns nothing: a reference, a closure's reference parameter, a `borrow` binding, a `[&x]` or `[&var x]` capture, a pattern's binding aliasing a part of a borrowed scrutinee, which a name reading through a borrow is as a scrutinee (spec, Reference Semantics; DF-288a) |
| `transfer.implicit-copy` | an ExplicitCopy or NoCopy place read by value with no `move`, payload reads included (design 131), and a projection's (`T.Item` in a generic body, a trait's own `Item` in its default bodies); a closure's capture of one by value with nothing written, with the fix-it `[move x]`; a plain subscript of such an element read where its position keeps nothing, a getitem all the same, with the fix-it `borrow` (D29) |
| `transfer.no-move` | a `move` of a `NoMove` value, or of one holding it inline (an Optional, a tuple, an array, a generic instance), at every position: a binding, an argument, a consuming receiver, a `[move x]` capture, `take()` out of an optional; a by-value parameter placed by `ptr[i] = move p` before any `&`, `&var` or `borrow` named it is the value reaching its home, and allowed (design 188) |
| `deinit.manual-call` | a `deinit` called by hand, written or synthesized, through a bound or named as a static (spec, The Deinit trait) |
| `copy.declared-bound` | a body's inferred Copy requirement on one of its own type parameters that its signature does not cover: a public generic that does not declare it, or a declared `ExplicitCopy` the body exceeds (design 219) |
| `capture.copy` | `[copy x]` of a NoCopy binding, which has no copy; `[copy x]` of a value whose type names a type parameter no bound lets the body copy: `Copy` for every one, or `ExplicitCopy` on a bare parameter (D30) |
| `capture.escaping-consume` | a consuming use of a by-value capture in a closure that escapes, at every copy tier: a `move` of it, a `match` consuming it, an inner closure's `[move x]` of it; a spawn form's brace is exempt (SL-469; the escaping-consume matrix) |
| `capture.escaping-borrow` | a borrow of the enclosing frame, `[&x]`, `[&var x]`, a reference parameter or `self`, captured by a closure that escapes: anything but one passed straight to a parameter whose function type does not say `escaping` (spec, Capturing `self` and reference parameters) |
| `capture.exclusive-self` | `[&var self]` in a method whose receiver is `&self` |
| `subscript.role` | a subscript of a type that declares no `[]`, or a role it declares and derives no accessor for (SL:borrowing §5.2) |
| `pattern.case-mismatch` | a lone name resolve took for a case none of whose candidates is a case of the matched type, naming the case and suggesting the rename (D13) |
| `format.slot-count` | a format string whose `{}` slots and arguments differ in number, or a formatted message that is no literal |
| `format.argument` | a format argument or interpolated segment that is neither Printable nor a primitive |
| `format.mixed` | a format string that interpolates a value beside its `{}` slots or arguments (spec, "Format arguments and the allocation-free path"), judged where the string-position funnel records it as `format` |
| `operator.undefined` | an operator over a type it is not defined for |
| `static.optional` | a static whose own type is an optional; an `unsafe static var` is exempt (spec, Module-level statics: "Never optional") |
| `borrowing.containment` | a borrowing struct (spec, Borrowing structs) bound outside the head of a `borrow` or a `for`, taken as a parameter by value, stored in a field or a payload, erased to an existential, returned by a function that does not lend it with `borrows`, or carried by a function type |
| `escaping.stored` | a non-escaping function value (a parameter whose function type does not say `escaping`, or a local bound to one) in a position that holds it past the call: a field, a payload, an element, an Optional, a return, an assignment's target, an escaping closure's capture, a type argument, an `escaping` parameter (D35) |
| `borrowing.sigil-place` | `&` or `&var` on a place reached through a `borrows` call, a subscript accessor or a named one, at any depth of fields, tuple elements and payloads: the place is passed with `borrow` (SL:borrowing §9) |
| `borrowing.var-unwrap` | an `if var`, `guard var` or `while var` binding of the payload of an optional place a `borrow` binding names, or of an optional field of one: it would write a copy, never the place (SL:borrowing §2.4) |
| `borrows.result` | a `borrows` function whose result is no place, slice, optional of either or borrowing struct (the accessor-signature reader's `other`) |
| `borrows.sync-window` | a call that may suspend, for some type argument, in the block of a `borrow` or a `for` whose head calls a `borrows(sync)` accessor (SL:borrowing §2.5) |
| `consumes.move` | a bare call of a `consumes` method on a place, at every Copy tier: the call spells `(move x).m()`, and a temporary receiver needs no `move` (spec, `consumes`) |
| `consumes.move-self` | `move self` or `move` of a part of `self` outside a `consumes` method (SL-414) |
| `match.non-exhaustive` | a `match` some value of its scrutinee's type reaches no unguarded arm of, each missing value named as a pattern: enums (`Optional` and `Result` included), `Bool`, tuples, split by their constructors at any depth; any other type, matched by literals and ranges, covered only by a wildcard or a binding |
| `result.discarded` | a `Result` computed where nothing reads it (design 151): a statement, a `Void` body's or a loop body's tail, an arm of a statement-position `if` or `match`, refused at the expression that produced it; `let _ =` is the out |
| `effect.sync` | a call in a `sync` body (a function declared `sync`, a `deinit`, a closure of a `sync` type) of a target that is not sync-callable: one that may suspend, a function value whose type is not `sync`; a call whose type arguments make a requirement a generic `sync` body calls through a bound not sync-callable; a `sync` requirement met by a member that is not sync-callable |
| `copy.requirement` | a call whose type argument is not on the Copy tier where its callee's body copies that parameter with nothing written (design 219), named with the copy's position, or, for a local one path uses twice, both uses |
| `effect.closure-suspends` | a call in a closure body that may suspend, or a call whose type arguments make a closure in its callee call a suspending implementation (spec: suspension, "a closure body cannot suspend") |
| `effect.any-suspends` | a coercion to `any Trait`, or a call whose type arguments make one in its callee, where the implementation of a requirement not declared `sync` may suspend, naming both (spec: suspension) |
| `slice.not-yet` | a signature or body construct outside the bootstrap slice |

The traits that derive under `@synthesize` are `Copy`, `ExplicitCopy`,
`Equatable`, `Comparable`, `Hashable`, `Serialize` and `Deserialize`. An
extern has no effect slot, so the unsafe rule asks nothing of it.

## The lane

`typecheck_lane.py` runs one `sawc2 typecheck` process per group and checks:

- each golden program's record equals its `.typecheck` file byte for byte;
  `--write` rewrites them after a deliberate change, for review;
- each refusal fixture is refused first by its rule, at its position;
  `--fill` writes the header of a new fixture whose first line is
  `// refuses: TODO`, for review;
- every rule typecheck's source refuses by has a fixture, and every fixture
  names such a rule;
- the compiler's own source checks with no refusal: the sawc2 build, with the
  stage packages mapped, and each unit program; a unit program the parser
  refuses is counted apart;
- no function of the compiler's own source may suspend, since the subset is
  sync-only; how many are sync-callable is printed for information, with any
  that are not listed;
- no std function the compiler's source calls lacks a row of the std
  suspension table (a `summary.untabled` NOTE);
- no record carries an `INVARIANT` line.

## The verifier

`verify.saw` runs on every module, std and builtin included, and finds the
type positions from the tree by its own rule: every type node of a signature,
which is everything outside a body, a parameter's default, a static's
initializer, a case's raw value, an attribute's argument, a `static_assert`,
a test case and a construct refused as outside the slice. It checks that each
has a type, that a named type's last segment carries resolve's record, and
that an error type stands only in a module with a refusal; that every
nominal type has a member table and a Copy tier; and that every conformance
accounts for each requirement and leaves none missing without a refusal.

`bodyverify.saw` runs on every module checked in full and finds a body's
expressions, patterns and calls from the tree by its own rule, its own list of
alternatives and resolve's call classes, apart from the walk's dispatch: a
call's head that names a function, type or case is no expression, and a
method's selector is none but its receiver is. A type written in a body (a
`let` annotation, a cast's target, a closure parameter's type, a call head's
type arguments, however the call is resolved or refused) is a body's too: it
checks that each such type position was built exactly once, to an interned
type that is an error only in a module with a refusal, with a named type's
last segment read through resolve's record (body_types). It checks that each
expression and pattern was typed exactly once, that no type is left unresolved in a module with no refusal and a body
no other module's refusal poisoned (SL:architecture §3.0), that each
has a use and a value use a transfer that fits its category, that each call has
a target and as many type arguments as its target has parameters, none of them
its target's own, that each call the overload filter resolved records a total
argument binding (every written argument binds exactly one parameter or falls
in the variadic tail, and every parameter no argument binds has a default),
that each closure records a capture, with a capture's transfer, of every
enclosing binding its body names, and that each adjustment chain composes,
every step's source the step before's result.

The summary verifier (`summaries.saw`) checks that every function has its
three summaries, that each checked body's summary is a fixpoint (one more step
over its items changes nothing), that every condition is over the function's
own type parameters, and, in a module with no refusal, that no call in a
closure body and no coercion to `any` may suspend: `compiler/` is sync-only,
so only the refusal fixtures and this invariant show those two checks exist.
In the builtin module it also checks that every row of the std suspension
table names a std function.

## The one-time checks

- `frozen_check.py` observes the frozen typechecker in-process, as
  `compiler/tests/resolve/frozen_check.py` does, and compares each struct's
  field types, each function's and method's parameter and result types, and
  each struct's and enum's Copy tier over the sawc2 build; and, for the body
  half, each call's chosen target and instantiation and each `let` and `var`
  binding's type. `FROZEN_CHECK.md` records what it found.
- `frozen_effects.py` compares the exhaustiveness and discarded-`Result`
  verdicts over the sawc2 build and the corpus's refusal programs for those
  rules, and, over the corpus programs that park through `yield_now` alone,
  the functions the frozen coroutine transform frames with those sawc2 finds
  may suspend. `FROZEN_CHECK.md` records what it found.
- `cone_coverage.py` counts the std cone declarations that get a fully bound
  signature, and lists the rest with the reason.
- `corpus_info.py` checks every file of `tests/corpus/` and prints how many
  check with no refusal, and the rules the rest are refused by; a program
  whose check crashes the process is counted as such, and the rest are
  checked in a fresh process.

None of them gates; each is kept runnable.

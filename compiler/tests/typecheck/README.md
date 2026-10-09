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
  module sees, or a type assignment), `default`, `synthesized` (under
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
| a constant expression: literals, module statics of an integer type and raw-backed cases, under `-`, `~`, arithmetic, shift and bit operators | adopts its slot, or its mixed operator's peer, and folds there by typed arithmetic, every literal and leaf fitting and no operation overflowing; a bare static adopts only as a leaf inside one, and keeps its declared type anywhere else, an operator's peer included (spec, Integer Width Agreement: "a module `static`… may be a leaf"); a combination of cases with no integer slot is the backing integer (spec, Flag enums) | funnel, widening, folding |
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
| a closure | parameters written or from the slot's function type, or, as a generic call's argument, from the parameter type once inference has solved its parameters; result from the slot or its tail | control, closure_inference |
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
| `type.bound` | a type argument, or a default, that does not satisfy its parameter's bound, for every kind of type, primitives included (design 109) |
| `type.default` | a parameter with no default after one with a default; a default that names a type parameter |
| `type.alias-cycle` | type aliases that stand for each other |
| `type.infinite-size` | a struct or enum whose storage contains its own inline, through fields, payloads, tuples, optionals, arrays and the generic declarations they instantiate, or through ever larger instantiations |
| `conformance.incomplete` | a requirement of a trait, or of a trait it refines, that nothing meets: no member written, no default, no derivation; an associated type no type assignment gives |
| `conformance.signature` | a written member that disagrees with its requirement: receiver, staticness, type parameters, parameters, result, an `unsafe` the requirement declares, `consumes`, or `borrows` (a `borrows(sync)` member never meets a plain `borrows` requirement, SL:borrowing §2.5) |
| `synthesize.required` | a declared conformance to a derivable trait whose method is neither written nor asked for with `@synthesize` (design 128) |
| `synthesize.inert` | `@synthesize` on a conformance that derives nothing |
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
| `member.unknown` | a field or method the type does not have, or this module does not see |
| `call.arity` | too many arguments, a missing one, a case built without its payload |
| `call.label` | a label no parameter has, one naming a parameter behind the last bound, a repeated label |
| `call.ambiguous` | overloads the arguments fit equally, named |
| `call.no-match` | no overload the arguments fit, each named |
| `call.not-callable` | a call of a value that is no function |
| `call.field-method-ambiguous` | `h.f(x)` where `f` names both a field holding a function and a method this module sees, with the fix-it `let g = h.f; g(x)` (D16) |
| `infer.failed` | a type argument nothing determines or two arguments disagree on; `None` or an empty literal with nothing expected, though not one whose slot holds a type already refused, which adopts the error type |
| `implicit-member.no-type` | an implicit member where nothing expects a type, with the `Enum.Case` fix-it |
| `transfer.implicit-copy` | an ExplicitCopy or NoCopy place read by value with no `move`, payload reads included (design 131), and a projection's (`T.Item` in a generic body, a trait's own `Item` in its default bodies); a closure's capture of one by value with nothing written, with the fix-it `[move x]` |
| `capture.copy` | `[copy x]` of a NoCopy binding, which has no copy |
| `capture.escaping-borrow` | a borrow of the enclosing frame, `[&x]`, `[&var x]`, a reference parameter or `self`, captured by a closure that escapes: anything but one passed straight to a parameter whose function type does not say `escaping` (spec, Capturing `self` and reference parameters) |
| `capture.exclusive-self` | `[&var self]` in a method whose receiver is `&self` |
| `subscript.role` | a subscript of a type that declares no `[]`, or a role it declares and derives no accessor for (SL:borrowing §5.2) |
| `pattern.case-mismatch` | a lone name resolve took for a case none of whose candidates is a case of the matched type, naming the case and suggesting the rename (D13) |
| `format.slot-count` | a format string whose `{}` slots and arguments differ in number, or a formatted message that is no literal |
| `format.argument` | a format argument or interpolated segment that is neither Printable nor a primitive |
| `operator.undefined` | an operator over a type it is not defined for |
| `static.optional` | a static whose own type is an optional; an `unsafe static var` is exempt (spec, Module-level statics: "Never optional") |
| `borrowing.containment` | a borrowing struct (spec, Borrowing structs) bound outside the head of a `borrow` or a `for`, taken as a parameter by value, stored in a field or a payload, erased to an existential, returned by a function that does not lend it with `borrows`, or carried by a function type |
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

# compiler/typecheck: type checking

The typecheck stage of the self-hosted compiler, package `sawtypecheck` (epic
SL-398, unit 6b, SL-447). It reads resolve's program unchanged, arenas and
side tables, and produces side tables keyed by resolve's ids (SL:architecture
§3.0, §3.4). U6b1 built the signature half: every declaration's signature
program-wide, trait requirements, the conformance table, the member tables and
the Copy tiers, and the checks that need only those. U6b2 builds the body half:
every body typed against those signatures alone, with its conversions, calls,
places and transfers recorded. The effect fixpoints come in U6b3.
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
    checks.saw        finite size, the signature half of `unsafe`, what an
                      `init` returns, `Deinit`'s conformances
    typeops.saw       the type questions a body asks: numbers, Optionals, Results
    adjust.saw        adjustment chains, conversions, and peeling
    candidates.saw    what a name or selector can mean: overload sets, members,
                      a bound's requirements
    infer.saw         call-site unification over one declaration's parameters
    bodies.saw        the body walk: statements, expressions, calls, patterns,
                      the expected-type funnel and the overload filter
    bodydump.saw      the dump's `bodies` section
    bodyverify.saw    the body verifier
    dump.saw          the dump
    verify.saw        the verifier
```

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
   module sees.
4. **Member tables** (`members.saw`), one per struct, enum and builtin type.
5. **Copy tiers** (`tier.saw`), one per nominal type.
6. **The checks** that need the tables: bounds, Copy-policy containment,
   finite size, the signature half of `unsafe`, what an `init` returns, and
   the conformances `Deinit` refuses.
7. **Bodies** (`bodies.saw`), each module checked in full, declarations in
   source order: a function's parameter defaults and block, a static's
   initializer, a raw case's value, an `@align` argument, then the file's
   `static_assert`s and test cases. Each body is checked against signatures
   only, so no body reads another.
8. **Places** (`settle_places`): once every body is checked, each subscript's
   role and each `borrows` accessor's receiver borrow is read off the use its
   position recorded (SL:borrowing §5, design 141).

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
  the Copy tier does silently (design 131), or hands off a temporary.

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
  exclusive borrow), and shared otherwise, whatever the accessor declares.
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

The builtin declarations typecheck knows by identity, (builtin, name), are
found once: `Optional` (for `T?`, which no name occurrence spells), `Result`,
the Copy family, the derivable traits, the unsafe pointers and the interior
cell. That is a table of the stage's own vocabulary, not a lookup of a name
the program wrote.

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
  the members; the numbers, `Bool` and `String` meet the value traits
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
  §2.5. A `sync` requirement met by a member not declared `sync` is left to
  the effect checks of U6b3, where inference answers it.
- An extern has no effect slot, so the signature half of `unsafe` asks
  nothing of it. A default parameter value is an expression, which U6b3's
  body half checks.
- `()` is the empty tuple, a type of its own beside `Void`.
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

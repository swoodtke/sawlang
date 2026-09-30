# compiler/tests/typecheck: the type checker's corpus

The corpus the typecheck stage (`compiler/typecheck`, SL-447) is held to. This
file specifies `sawc2 typecheck`'s records and dump, the type interner's key,
the position matrix the corpus covers, and the rules typecheck refuses by. So
far the stage checks signatures only (U6b1); bodies come next.

```
typecheck/
  README.md          this specification
  typecheck_lane.py  the lane compiler/tests/run.py runs
  golden/            NAME.saw, a program, and NAME.typecheck, its expected record
  multi/             NAME/main.saw and its modules, and NAME.typecheck
  refuse/            RULE[.VARIANT].saw
  frozen_check.py    signatures and Copy tiers against the frozen compiler's
  FROZEN_CHECK.md    the record of that check
  cone_coverage.py   how much of the std cone gets a fully bound signature
  corpus_info.py     how much of tests/corpus/ checks, for information
```

## `sawc2 typecheck`

```sh
.build/sawc2 typecheck (--dump | --check) [--notes] [--interfaces] [--std-root DIR]
                       [--module-path NAME=DIR]... [FILE | @LIST]...
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
- one `INVARIANT<TAB>module<TAB>message` line per problem either verifier
  finds, resolve's then typecheck's, for every module, interfaces included;
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
    (TYPE TIER [declared])...))
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
  `@synthesize` derives. A member kind is `field`, `case`, `method`,
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
- `Self` in a trait requirement is a placeholder keyed by the trait, and a
  trait's own associated type a placeholder keyed by its declaration; a
  conformance substitutes both when a requirement is matched;
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
as visible as the conformance, which the orphan rule makes global.

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
| an associated type named through a type parameter, bare or as `T.Item` | resolve's `slice.not-yet` |

The slice is what `compiler/` and the std cone use; a construct outside it is
refused by name, never mis-typed, and the verifier asks nothing of what lies
under one.

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
| `unsafe.undeclared` | a function whose parameters, result or receiver name an unsafe type and which is not declared `unsafe` (designs 130 and 136) |
| `unsafe.function-type` | a function type that names an unsafe type without saying `unsafe`, or says it without naming one |
| `unsafe.type-name` | an `unsafe struct` not named `Unsafe*` |
| `slice.not-yet` | a signature construct outside the bootstrap slice |

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

## The one-time checks

- `frozen_check.py` observes the frozen typechecker in-process, as
  `compiler/tests/resolve/frozen_check.py` does, and compares each struct's
  field types, each function's and method's parameter and result types, and
  each struct's and enum's Copy tier over the sawc2 build. `FROZEN_CHECK.md`
  records what it found.
- `cone_coverage.py` counts the std cone declarations that get a fully bound
  signature, and lists the rest with the reason.
- `corpus_info.py` checks every file of `tests/corpus/` and prints how many
  check with no refusal, and the rules the rest are refused by.

None of them gates; each is kept runnable.

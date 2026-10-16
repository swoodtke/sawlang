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
  inject/            NAME.saw, a program a unit program checks, then edits, to
                     prove the body verifier reports a record no check makes,
                     or asks a predicate no refusal shows of each row
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
.build/sawc2 typecheck (--dump | --check) [--notes] [--interfaces] [--summaries] [--runtime]
                       [--std-root DIR] [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved, then checked,
with every module it imports. The flags are resolve's (see
`compiler/tests/resolve/README.md`); `--interfaces` also dumps the std and
builtin modules, whose signatures are checked as interfaces; `--runtime` checks
each program as a runtime source, whose exports may be the frozen seams, as
`sawc2 runtime` does (the `export.*` rules). Each entry gets one record, starting
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
  - for an inline catch or a `try` block, `(error TYPE)`: the type of its
    catch block's `error` binding, `Never` for a `try` block no `try`
    propagates out of;
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
"Trait-conformance methods follow the trait"; multi/conformance_views). What
a test-only extension declares or brings is seen by its own module's test code
alone (SL:testing, "Test-only means test-only"), through resolve's declaration
filter `may_use`; a free function's overload set is expanded by resolve's
`overload_decls` under the same filter, so ordinary code sees an overload set
or a type's members as if no test-only declaration existed, and an importer
never sees a private overload. A
requirement's default or derivation reaches the table once, however many of
the type's conformances reach its trait: `E: Printable` and `E: Error`, which
refines it, bring one `to_string`.

The per-declaration filter, by position (SL-626):

| row | verdict | covered by |
|---|---|---|
| an importer calling a private overload, bare, qualified (which Stage 0 accepts) or through a merged set | refused | type.mismatch.private-overload, type.mismatch.private-overload-qualified, call.no-match.private-overload-merged |
| ordinary code calling a test-only overload, of its own module or another's; test code calling another module's | refused | call.arity.test-only-overload, type.mismatch.test-only-overload-imported, type.mismatch.test-only-overload-imported-test |
| ordinary code calling a test-only extension's method, static, `init` or method overload | refused | member.unknown.test-only-method, member.unknown.test-only-static, call.label.test-only-init, call.label.test-only-method-overload |
| ordinary code calling, or naming as a value, the ordinary overload of a set with a test-only one; test code using every overload and member | allowed | test_only_overloads |
| a test-only twin of a production function, `main` included, with `@test` or in a group: a test build holds both, though a normal build emits neither test-only one | refused, `overload.indistinguishable` | overload.indistinguishable.test-only, .test-only-main, .test-only-main-group |
| an importer naming as a value the one overload it sees; a set whose first declaration is narrower than a later public one, imported; the module calling its own private overloads | allowed | multi/overload_visibility |

A type's policies, `Copy`, `ExplicitCopy`, `NoCopy`, `NoMove`, `ZeroInit`,
`UnsafeSend` and `UnsafeSync`, are declared only in the file that defines
the type, and test code is a file of its own (SL-659, the user's ruling (a)):
an `@test` declaration, an `@test { }` group and a sidecar each count as one,
and every `@test` declaration and group of a module counts as the same test
file. One funnel, `in_defining_file` (`compiler/typecheck/src/conform.saw`),
answers where a declaration sits; `policy_in_place` asks it of a policy
conformance, and `check_policy_placement` (`checks.saw`) refuses one that is
not, under `conformance.policy-placement`. A misplaced policy counts for
nothing: the tier, movability, zero-value and visibility readers each ask
`policy_in_place`, so nothing else is refused or decided because of it, and
a type has one tier, one movability, one zero value and one thread behaviour
in a binary. Another module's policy for a type is the orphan rule's first
(resolve's `conformance.orphan`); only the trait's own module, the prelude,
gets past it, and the std lane holds the prelude clean. sawc2 reads no
sidecar yet, and a sidecar's declarations are test-only declarations of its
module, so the test-only rows cover it:

| row | verdict | covered by |
|---|---|---|
| a test-only `NoCopy` (with its `deinit`), `Copy` (with its hook), `ExplicitCopy`, `NoMove`, `UnsafeSend` or `UnsafeSync` conformance on a production type, in an `@test` declaration | refused | conformance.policy-placement, .copy, .explicit-copy, .no-move, .unsafe-send, .unsafe-sync |
| the same in an `@test { }` group, `ZeroInit` and a group's static of the type included | refused | conformance.policy-placement.group, .copy-group, .explicit-copy-group, .no-move-group, .unsafe-send-group, .unsafe-sync-group, .zero-init-group |
| a test-only `ZeroInit` in the production struct's own module, which another module's static would read | refused | conformance.policy-placement.zero-init |
| a conditional head on a generic type, `@synthesize`, an enum, a policy named after a non-policy trait in one head | refused, at the policy | conformance.policy-placement.conditional, .synthesize, .enum, .one-extension |
| a test-only `NoMove` on a production type, beside production code that moves the value or holds it in a `NoCopy` struct | refused at the conformance alone: no `transfer.no-move`, no `nomove.undeclared` | conformance.policy-placement.no-move, .no-move-holder |
| another module's policy conformance for a type | refused, resolve's `conformance.orphan` | resolve conformance.orphan.policy |
| a production type's policies declared beside it, used by test code; a test-only conformance to a trait that is no policy on it; a test-only type's policies, in a separate `@test` declaration or a group, each policy trait | allowed | policy_placement, test_only_copy_policy, test_only_conformances |
| a test-only struct holding a test-only `NoMove` type inline without declaring `NoMove` | refused, `nomove.undeclared` | nomove.undeclared.test-only |

Test code cannot change how a production type copies (SL:testing, Air t15):
a type has one tier in a binary. A test-only copy policy on a production type
is `conformance.policy-placement`'s, above, and `check_test_only_copies`
(`compiler/typecheck/src/conform.saw`) refuses a test-only `copy()` on one,
under `copy.test-only-policy`, the funnel's named special case for a member
(SL-630); which `copy()` a copy runs is read from the policy conformance
alone (`policy_copy`). A Copy or ExplicitCopy type's `copy()` is
written only there, and `check_copy_placement` refuses one written anywhere
else under `copy.outside-policy`, a type that is Copy by its members
included; a NoCopy type's `copy()` is an ordinary method (SL-641). A member
named `copy` counts when a call with no arguments reaches it:

| row | verdict | covered by |
|---|---|---|
| a test-only `copy()` on a production type, in a plain test-only extension, alone or beside a production `Copy` conformance that derives its own | refused, and not also `copy.outside-policy` | copy.test-only-policy.copy-method, copy.test-only-policy.beside-synthesized |
| a policy's `copy()` written by another extension than the conformance, so the conformance writes none | refused, `synthesize.required`, then `copy.outside-policy` | synthesize.required.copy-outside-policy |
| a `copy()` outside the policy of a type Copy by its members, a struct (bare), an enum or a generic type; beside a derived `Copy` or `ExplicitCopy`; in another conformance's extension; a static one; one whose parameters all have defaults | refused, `copy.outside-policy` | copy.outside-policy, .enum, .generic, .declared, .explicit, .other-conformance, .static, .defaulted |
| a NoCopy type's `copy()`, in a plain extension or in its `NoCopy` conformance, called by name; a Copy type's `copy` with a parameter no default fills; a `Copy` conformance's hook | allowed | copy_method_shapes |
| a NoCopy type's `copy()`, copied silently or passed to an `ExplicitCopy` bound | refused, `transfer.implicit-copy`, `type.bound` | transfer.implicit-copy.nocopy-copy-method, type.bound.nocopy-copy-method |
| a `deinit` in a plain test-only extension | refused, `deinit.outside-policy` | deinit.outside-policy.test-only |
| a test-only type's policy, `copy()` and `deinit`, with `@test` or in a test group, used by test code; a production NoCopy type's `copy()`, called by name | allowed | test_only_copy_policy |

A declaration's attributes are read through one funnel, resolve's
`decl_attribute`, from the node the declaration records as holding them: its
Declaration or ExtensionMember node. Under `@test` that is still the
Declaration, never the TestOnly item around it, so a declaration written after
`@test` keeps its attributes as one inside an `@test { }` group does (SL-631).
Each fixture holds the group form beside it as its control:

| row | verdict | covered by |
|---|---|---|
| `@synthesize`, `@export` and `@align` after `@test`, and inside a group | allowed | test_only_attributes; MIR golden `test_only_attributes` |
| `@synthesize` after `@test` on a conformance that derives nothing | refused | synthesize.inert.test-only |
| `@export` after `@test` on a generic function | refused | export.generic.test-only |
| a test-only `@export` of a production export's symbol, though a normal build emits no test-only export | refused | export.duplicate.test-only |
| `@align` after `@test` with a `Bool` argument | refused | type.mismatch.test-only-align |

Nor can test code change which conformances production code sees (SL-629)
or what meets a production conformance's requirements (SL-640). One funnel,
`conformance_visible` (`compiler/typecheck/src/conform.saw`), answers whether
a conformance exists for the code asking: one a test-only extension declares
exists for its own module's test code alone, by resolve's `may_use`.
`satisfies` takes the code asking as its viewer and answers every pair of its
run with it, so a bound, a conditional conformance's condition, an operator
through `Equatable` or `Comparable`, a format argument, an erasure and `Send`
and `Sync` all read the one answer. A production conformance is settled with
the members a production conformance may use (`meets_from`) and a parent
conformance it may see (`assignment_for`), so a test-only member never meets
it. A test-only conformance that reaches a trait a production conformance
covers takes that one's answer for each of its requirements
(`production_status`), so a production generic's one instance at the type
runs one body whichever conformance monomorphization reads; the members a
production conformance brings, a default or a derivation, join the member
table before a test-only one's, and an associated type ordinary code projects
is a production conformance's, so neither depends on declaration order. A
test-only member that meets a requirement a production conformance already
meets, with a written member, the trait's default or a derivation, is refused
where it is declared (`check_test_only_shadows`), since nothing through the
trait would run it; a fake is a test-only type passed to the production
generic. A member written to meet a requirement follows its trait's
visibility only for a production conformance. A policy test code declares
for a production type never reaches the funnel's question:
`conformance.policy-placement` refuses it, and `conformance_visible` hides it
from every viewer, so a type has one tier and one thread behaviour for every
viewer.

| row | verdict | covered by |
|---|---|---|
| a production conformance whose requirement only a test-only member meets: a plain test-only extension's, a test group's, a static, or a parent's requirement or associated type only a test-only conformance to the parent writes | refused, as missing | conformance.incomplete.test-only-member, -group, -static, -parent-member, -parent-assignment, synthesize.required.test-only-member |
| a production refinement assigning a parent's associated type as another type than a test-only conformance to the parent does, or a test-only refinement assigning it as another type than a production sibling refinement does, in either declaration order | refused | conformance.associated-conflict.test-only-parent, -test-only-sibling |
| a test-only member whose signature meets a requirement a production conformance meets: with the trait's default, through a refinement, a static, a member written in a test-only refinement's own extension, with `@synthesize` | refused, `conformance.test-only-shadow` | conformance.test-only-shadow, .refinement, .static, .test-only-conformance, .synthesize |
| the same, met in production by a written member | refused, `overload.indistinguishable` | overload.indistinguishable.test-only-requirement |
| a test-only member of a requirement's name with another signature, or of another name | allowed | test_only_conformances |
| ordinary code's direct call of what a production conformance brings, a default or a derivation, beside a test-only refinement declared before it or after it | allowed | test_only_conformances (`Early`, `Late`, `EarlyKey`, `LateKey`, `EarlyFault`, `LateFault`), run probes/test_only_members |
| ordinary code in another module calling a private method that meets a public trait's requirement only for a test-only conformance | refused, `member.unknown` | member.unknown.test-only-conformance-visibility |
| ordinary code's bound met only by a test-only conformance: inferred, explicit, a generic struct's argument in a signature, a field or an inferred construction, a conditional conformance's condition, `Comparable`, `Iterator`, a refining trait's, `Hashable` | refused, `type.bound` | type.bound.test-only-conformance, -explicit, -struct, -field, -struct-inferred, type.bound.test-only-conditional, -comparable, -iterator, -refinement, -hashable |
| ordinary code's `==`, `!=` and `<` through a test-only `Equatable` or `Comparable` | refused, `operator.undefined` | operator.undefined.test-only-equatable, -equatable-ne, -comparable |
| ordinary code formatting or interpolating a type only a test-only `Printable` covers | refused, `format.argument` | format.argument.test-only-printable, -printable-interpolation |
| ordinary code erasing a type to `any Trait` that only a test-only conformance meets | refused, `type.mismatch` | type.mismatch.test-only-erasure |
| another module's test code using a module's test-only conformance | refused, `type.bound` | type.bound.test-only-conformance-imported-test |
| a test-only conformance to a trait a production type meets through a production refinement, or automatically: `Equatable` or `Hashable` of a trivially copyable struct, a generic one or a payload-free enum | refused, `conformance.test-only-overlap` | conformance.test-only-overlap, .hashable, .enum, .generic, .refinement |
| a `for` over a production `next` beside a test-only `Iterator` conformance | allowed: the loop reads the member, not the conformance | test_only_conformances |
| the module's test code at every position above, a test-only conformance met by a test-only member, and a test-only refinement of a production conformance, which takes its statuses | allowed | test_only_conformances |

A type argument written inside a body is not bound-checked at all yet
(SL-654), so that position has no row of its own here.

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
| a static on its type written without its type arguments, whose inferred argument misses the bound (SL-657) | refused | type.bound.static |
| std's `copy()` on `Vector<T>` where `T` is not ExplicitCopy | refused | type.bound.vector-copy |
| the builtin `copy()` reaching an unbounded type parameter, through a tuple, an Optional or an array (row V43) | refused | type.bound.copy-wrapper |
| the same parameter 18 tuples deep (SL-627) | refused | type.bound.copy-deep-parameter |
| a bound over a tuple 66 deep of a NoCopy struct, answered by identity at any depth (SL-627) | refused | type.bound.deep-tuple |
| the builtin `copy()` on a NoCopy value, a tuple holding one included (rows V11, V22) | refused, `member.unknown` | member.unknown.copy-nocopy |
| each where the bound holds: a concrete argument, a generic body's own bound, `copy()` under `T: ExplicitCopy` | allowed | extension_bounds |
| a bounded extension written before the type it extends, whose bounds are its own head's (SL-740) | refused | type.bound.extension-before-type |

A tuple, an Optional and a fixed array meet a trait through their parts only
where the spec says so: the copy tiers, `Send`, `Sync`, `Equatable` and
`Hashable`. `Comparable` is not one of them (spec, Ordering: integers, `Float`
and `String` builtin, a struct or enum through a written conformance). One
funnel, `structural_trait` (`compiler/typecheck/src/tier.saw`), names the
list for each kind (SL-754):

| row | verdict | covered by |
|---|---|---|
| `<` on a tuple, an Optional, a fixed array of `Int` | refused, `operator.undefined` | operator.undefined.ordered-tuple, -optional, -array |
| a `T: Comparable` bound at each | refused | type.bound.comparable-tuple, -optional, -array |
| `Vector.sort` over tuples, its extension's `T: Comparable` | refused | type.bound.sort-tuple |
| `Equatable` and `Hashable` through a tuple's and an Optional's parts, at a bound, `==` and a `Map` key, and through a fixed array's as a struct's field | allowed | run programs aggregate_equals, aggregate_hash, aggregate_map_keys |

A fourth filter is the specialized extension's (spec, Type Extensions; SL-740):
a head that names a type for every parameter it writes, `extension
Vector<String>`, declares members for that instantiation alone, its omitted
defaulted parameters filled (SL:open-questions D14), and its body sees the
head's types where it names them and `Self` as the instantiation. Two funnels
in `compiler/typecheck/src/signatures.saw` answer it: `ext_self_type`, what
`Self` is in an extension, and `extension_applies`, whether its members belong
to a receiver, which `members_for` and mono's role lookups ask; a member found
by its type alone is called at the head's instantiation (`found_owner`). The
run program `specialized_extensions` and the probe
`specialized_extension_statics` (`compiler/tests/run/`) hold the accepted rows.

| row | verdict | covered by |
|---|---|---|
| a method, a `&var self` method and a generic method, on a std type and a user type specialized at a primitive, a struct or an enum; a receiver reached through a nested generic argument; a generic extension's member beside them | allowed | run specialized_extensions, probe specialized_extension_statics |
| a static, on the instantiation written and on the type written bare; an `init`, explicit and inferred; `Self`; the head's type built by its name in the body | allowed | probe specialized_extension_statics |
| two specializations at different arguments declaring one name | allowed | run specialized_extensions |
| a method, a `&var self` method or a static called on another instantiation | refused, `member.unknown` | member.unknown.specialized-instantiation, .specialized-mutating, .specialized-static |
| a call inside a generic body bound only by `T`, whatever `T` is instantiated to | refused, `member.unknown` | member.unknown.specialized-generic-body |
| a member of the shape a generic extension's member has, on the same type | refused, `overload.indistinguishable` | overload.indistinguishable.specialized-beside-generic |
| an `init` taking the head's instantiation's fields exactly | refused, `init.override-specialized` | init.override-specialized |
| a conformance in a specialized extension, an assertion included | refused, `extension.specialized-conformance` | extension.specialized-conformance, .assertion |
| a head naming a type for some parameters and renaming others | refused, `extension.partial-specialization` | extension.partial-specialization |
| a head writing a generic argument, `extension Map<String, Vector<Int>>` | refused by the parser: a head's parameter is a name (GRAMMAR, syntax.generic.param) | |

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
| a compound assignment's right side, but a shift's count, which is no peer | `check_compound_value` | funnel, places |
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
operation that leaves its type's range is refused as overflowing it,
`constant.overflow`, so `255 + 1` at `UInt8` is (constant.overflow), and so
is `256 - 1`, as `type.mismatch`, whose `256` does not fit; a shift count
outside the shifted type's width and a division by zero are refused too, as
`constant.shift-range` and `constant.divide-by-zero`. `1 << 63` at `UInt64` is 2^63. A 64-bit magnitude past
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

### The constant-position funnel

Every position the constant grammar governs reaches one funnel,
`check_constant_position`, after its expression is typed (spec, Compile-Time
Evaluation, "The constant grammar"; SL-493, SL-494). Its docstring names the
entry points. It refuses, in order, the first sub-expression outside the
position's grammar (`static.not-constant`, naming it), a static whose value
depends on itself (`static.cycle`, once per cycle, at the earliest-declared
static on it, naming the statics in order), a fault the fold meets in the
expression itself (`constant.overflow`, `constant.shift-range`,
`constant.divide-by-zero`, and `type.mismatch` for a value that does not
fit, but `constant.cast-range` for a cast that does not, which it hands to the
constant-cast funnel), and a `static_assert` whose condition folds to `false`
(`static_assert.failed`, carrying its message). A fault met inside a static
the expression names is that static's refusal. An expression with a refusal
inside it already is not judged again, and neither is an optional static's,
which `static.optional` refuses. What the grammar admits and the fold does not
compute (an aggregate, a float, `sizeof`, a const parameter) is constant and
unfolded: no fault and no verdict. The evaluator computes the same answers from
MIR and is held to the fold by its agreement check, so its own refusals are
defence in depth (`compiler/tests/eval/README.md`).

| position | entry point | grammar beyond the shared one | covered by |
|---|---|---|---|
| a static's initializer | `check_static_body` | a struct's memberwise construction, an array and a repeat literal, a float, an earlier static of any type; no `init` body, call, tuple, `String`, or case of an enum with no backing | constant_positions, constant_refusals; static.not-constant, .conversion, .init, .interpolation, .tuple, .unbacked-case, .mutable; static.cycle; constant.divide-by-zero; constant.cast-range.static-initializer |
| a raw case's value | `check_raw_value` | names no static and no other enum's case (spec, Raw backings) | constant_positions; static.not-constant.raw-static, .raw-case |
| an `@align` argument on a static | `check_align_attribute` | none | constant_positions |
| an `@align` argument on a local | `check_align_local` | none | constant_positions; static.not-constant.align |
| a `static_assert` condition, at the top and in every body kind | `check_static_assert` | a const parameter in scope | constant_positions, constant_faults; static_assert.failed, .function, .method, .init, .closure, .default-body, .test-case, .declared-later, .declared-later-module; static.not-constant.assert-local; constant.overflow.assert, constant.shift-range |

The shared grammar is the fold's: integer and `Bool` literals, `#line`, module
statics that are not an `unsafe static var`, raw-backed cases, an integer
type's `max` and `min`, under the unary, arithmetic, shift, bit, comparison
and logical operators and `as`; a type alias's construction over a constant
(the user's ruling, SL:open-questions "Resolved"); and `sizeof` and `alignof`,
of any type in a `static_assert` and elsewhere only of a type the target alone
lays out, an integer, `Bool`, `Float`, `String` or a raw pointer, an alias
measuring as the type it stands for (spec, "Layout in a constant"; a struct,
an enum, a tuple, an array or an optional is `static.not-constant`, naming the
type: `.layout-static`, `.layout-align`, `.layout-align-local`,
`.layout-raw`; golden `layout_constants` holds the accepted rows). The
array-length, repeat-count and const-argument positions are folded by
`build_const` (SL-457) and do not reach the funnel; it refuses every `sizeof`
there, of any type, as `slice.not-yet`.

### The certain-fault funnel

A shift whose count, or a division or remainder whose divisor, is constant
before generic instantiation faults wherever it runs, whatever the other
operand is, so it is a compile error even where no constant position folds it
(spec, Compile-Time Evaluation; SL:open-questions Q-shiftcount). One funnel,
`check_certain_fault`, judges both rules for `<<`, `>>`, `<<=`, `>>=`, `/`,
`%`, `/=` and `%=`; its docstring names its entry points. "Constant before
instantiation" is decided once, by `fold_before_instantiation`: the operand
folds by the fold's grammar and mentions no type or const parameter. A count
outside the shifted type's width is `constant.shift-range`, and a divisor that
folds to zero `constant.divide-by-zero`, each at the operand; an operand whose
own fold faults is refused at that fault, and so is an operation that is
constant as a whole, as the constant-position funnel refuses it. Reachability
is not asked: `if false { x << 64 } else { x }` is refused. A count or divisor
that names a const parameter is constant only per instantiation, and may sit
behind a guard that keeps it from running (`if N > 0 { x << (N - 1) }`), so
it stays a run-time check.

| operand | refused | covered by |
|---|---|---|
| a literal count beside a run-time value, binary and compound | `constant.shift-range` | .binary, .compound |
| a count naming a static, a constant expression over one | `constant.shift-range` | .static-count, .expression-count |
| a count whose own fold faults | `constant.shift-range` | .count-fault |
| a count in code that never runs | `constant.shift-range` | .unreachable |
| a zero divisor of `/`, `%`, `/=`, and `%=` over a static | `constant.divide-by-zero` | .division, .remainder, .compound, .compound-remainder |
| a count or a divisor naming a static declared after it (the pending-constant funnel) | `constant.shift-range`, `constant.divide-by-zero` | .declared-later |
| a run-time count or divisor; a constant one that cannot fault; one that names a const parameter | nothing | certain_fault_controls; run programs runtime_count_divisor, const_generic_shift_guard |

### The constant-cast funnel

A cast whose operand is constant before generic instantiation and whose value
its integer target cannot hold panics wherever it runs, so it is a compile
error at its `as` (spec, Integer Conversions, "Constants"; SL-757). One
funnel, `refuse_constant_cast`, refuses it as `constant.cast-range`, in Stage
0's words, naming the value, the target and the target's range; its docstring
names its entry points. "Constant before instantiation" is the certain-fault
funnel's `fold_before_instantiation`: a literal, const arithmetic, a module
static, a raw-backed case, an integer type's limit, and a cast of one of them.
Every cast to an integer type is judged once every body is typed, through the
pending-constant funnel, so a static or a case declared after the cast folds
too. At a constant position the constant-position funnel meets the same fault
first and hands it to this funnel, so a cast that does not fit is refused by
one rule, at its `as`, wherever it is written. A slot a lone case adopts holds
no cast: `let x: UInt8 = Wide.Big` stays `type.mismatch`'s "does not fit".
Reachability is not asked. A `let` local, a value computed at run time and a
const parameter keep the run-time check, `cast to T out of range`.

| operand | refused | covered by |
|---|---|---|
| a literal, in a `let`, an argument, and code that never runs | `constant.cast-range` | (bare), .argument, .unreachable |
| const arithmetic, a negative constant to an unsigned type, an integer limit | `constant.cast-range` | .arithmetic, .sign, .limit |
| a raw-backed case below its backing, and a negative one to an unsigned type | `constant.cast-range` | .case, .case-sign |
| a case declared after the cast; a module static | `constant.cast-range` | .declared-later, .static |
| a cast of a cast | `constant.cast-range` | .nested |
| a static's initializer, a `static_assert` condition | `constant.cast-range` | .static-initializer, .assert; goldens constant_refusals, constant_faults |
| a case to its own backing, to a wider type, below its backing where it fits; a literal, a sum and a limit that fit; a static that fits; a `let` local, a computed enum value, a const parameter | nothing | constant_cast_controls; run programs constant_cast_accepted, constant_cast_runtime |

### The pending-constant funnel

Bodies are typed in declaration order, module by module, and a static's or a
raw-backed case's value has no type until its own body is checked. A constant
judgment that folds through one declared after the expression, or in a module
checked later, would stop short where it is met and let a certain fault
through (SL-760). One funnel, `defer_constant`, holds such a judgment, and
`judge_pending_constants` makes each held one, in the order it was met, once
every body is typed; its docstring names its entry points. A cast is always
held (the constant-cast funnel). Every other check folds where it is met and
holds its judgment only when the fold stops at a node no body has typed yet
(`awaits_typing`), so a judgment that can be made at once is made there and
the order of refusals is unchanged. A held judgment whose expression holds a
refusal already is not made again. A static's initializer holds nothing: it
may name only the statics above it (spec, Compile-Time Evaluation), which is
the declaration-order rule's to refuse. The array-length, repeat-count and
const-argument positions fold in `build_const`, which takes no static at all
(`slice.not-yet`), so nothing there waits on a body.

| judgment | entry point | refused, through a later static or case | covered by |
|---|---|---|---|
| a cast to an integer type | `cast_expr` | `constant.cast-range` | constant.cast-range.declared-later |
| a shift count or a divisor, binary and compound | `check_certain_fault` | `constant.shift-range`, `constant.divide-by-zero` | constant.shift-range.declared-later, constant.divide-by-zero.declared-later |
| a constant expression or a lone case adopting an integer slot | `check_constant_range` | `constant.overflow`, `constant.shift-range`, `type.mismatch` | constant.overflow.declared-later, type.mismatch.constant-declared-later |
| a `static_assert` condition, an `@align` argument | `check_constant_position` | `static_assert.failed`, a fault the fold meets | static_assert.failed.declared-later, .declared-later-module |
| each of the above, through a later static or case, where it folds and cannot fault | each of the above | nothing | golden constant_declared_later_controls |

### Layout asserts

A `static_assert` whose condition measures a type with `sizeof` or `alignof`
waits for the type's layout, which only `compiler/target` computes
(SL:open-questions D40). The funnel defers it (`defer_layout_assert`) with its
message and the function whose body holds it. One over concrete types is
checked by the layout-assert funnel, `asserts_typecheck_program` in
`compiler/asserts`, which every mode's typecheck goes through, so it is refused
as `static_assert.failed` at its condition whether its body is reachable or
not, under `--check` too (`static_assert.failed.layout`,
`.layout-body`). One that measures a type parameter is checked by mono at each
instantiation of its function (`compiler/tests/mono/refuse/static_assert.failed`),
and one in a body never instantiated is never checked. The evaluator leaves
every deferred one alone (`compiler/tests/eval/golden/layout_asserts`).

Every body construct in the slice, and how it is typed:

| construct | typed as | covered by |
|---|---|---|
| integer, float, string, `Bool` and `None` literals, `#file`, `#line`, `#function` | `Int` adopting its slot, range-checked, or a suffixed literal's exact type; `Float`, `String`, `Bool`; the slot's Optional, or the Ok payload's `None` at a `Result<T?, E>` slot (spec, Auto-Wrap: "At a declared `Result<T?, E>` it is `Ok(None)`") | funnel, peeling, widening, none_ok |
| a constant expression: literals, module statics of an integer type and raw-backed cases, under `-`, `~`, arithmetic, shift and bit operators; `fold.saw` also folds a type alias's construction over one, `Byte(65)`, as the identity, for the evaluator's agreement | adopts its slot, or its mixed operator's peer, and folds there by typed arithmetic, every literal and leaf fitting and no operation overflowing; a bare static adopts only as a leaf inside one, and keeps its declared type anywhere else, an operator's peer included (spec, Integer Width Agreement: "a module `static`… may be a leaf"); a combination of cases with no integer slot is the backing integer (spec, Flag enums) | funnel, widening, folding |
| a shift, `a << n`, and a compound one, `a <<= n` | the left operand's type; each count an integer of any width, no peer ("The shift count is exempt", "The compound forms `<<=` and `>>=` follow"), a constant one an `Int`; a count constant before instantiation is range-checked against the shifted type's width beside a run-time value too (the certain-fault funnel), and any other count at run time (spec, Bitwise and Shift Operators) | widening, compound_shifts, certain_fault_controls; operator.undefined.compound-shift-count; constant.shift-range.binary, .compound |
| an interpolation, its segments | `String`; each segment Printable or a primitive, or an erased box `Box<any Trait>` whose trait refines Printable, rendered through the existential; borrowed | format, split_conformance |
| a local, a parameter, a static, `self` | its type, a place | places |
| a const parameter, `N` | a value of its declared type, not a place (design 148) | builtin_values |
| a function named as a value | its one function's type | calls |
| a field, a named tuple's element, a tuple index | the member's type through any reference, a place when the base is | places, funnel |
| `E.Case`, `.Case`, `E.Case(...)`, `.Case(...)` | the enum, its arguments from its head (`Maybe<Int>.Nothing`), the slot or the payload | peeling, calls, builtin_values |
| `Int.max`, `T.from(x)`, `T.from(truncating: x)`, `E.from(raw: x)`, `A(x)` | the conversions no declaration writes | carried |
| a free function, method, static method, `init` or memberwise call | the overload filter's choice, instantiated; a bare integer literal prefers an `Int` parameter | calls, inference, literal_overloads |
| a requirement called through a type parameter whose signature names an associated type, `s.take(v)` with `take(v: Self.Item)`; a call instantiating a signature that names `T.Item` | the receiver's projection, `S.Item`, which takes no concrete type and copies silently under no bound; at the call, the conformance's assignment | associated_types; type.mismatch.projection, type.mismatch.projection-concrete, transfer.implicit-copy.projection |
| a call's arguments: positional, a label skipping a default, a default left out, a construction's or payload's labels out of order, a C variadic tail | the binding of each parameter to its argument or its default | arguments, lowlevel |
| a construction whose head writes a prefix of its type's arguments, `Two<Int>(a: 1, b: true)` | the prefix pins the leading parameters, inference solves the rest (spec, Generics) | partial_arguments |
| a static call on a generic type written without its type arguments, `Wrap.of(t: 5)`, `Set.of(7)`, `Tag.empty()` at a declared `Tag<Int>` or `Tag<String>?` | inference solves the type's parameters from the arguments and, through the result, from the expected type, peeled through the Optional or `Ok` it auto-wraps; nothing determining one is `infer.failed`, and a name the type has no static of is `member.unknown`; a written head, `Tag<Int>.count()`, is untouched (SL-657) | static_inference; infer.failed.static-bare-extension, infer.failed.static-generic-extension, member.unknown.static-bare-head, member.unknown.static-bare-std-head |
| a function value's call | its function type | calls, control |
| `h.f(x)` where `f` is a field holding a function and the type has no method `f` this module sees | the field's function value, called (`value`); with such a method seen too, refused as `call.field-method-ambiguous` (SL:open-questions D16) | field_calls, multi/field_views |
| `o.take()`, `o.is_some()`, `o.is_none()`, `x.copy()`, an array's or slice's `len()` and `swap(i, j)` | the methods no declaration writes | places, conversions |
| a builtin type's method of a trait it conforms to builtin: `n.to_string()`, `7.to_string()`, `equals`, `compare`, `hash` (design 109) | the trait's requirement or default, `Self` the builtin type | builtin_values |
| a raw pointer's `*p` and `p[i]`, `(&x) as UnsafePointer<T>`, an extern call, a C variadic one, an `unsafe static var`, an allocator parameter's `A()` | the pointee, a pointer, the extern's result, a value of the parameter | lowlevel |
| `print`, `panic`, `assert` with a message or format arguments; `sizeof`, `alignof` | `Void`, `Never`, `Int` | format, inference |
| `Task.spawn(f(x))`, under a std root declaring `Task` beside `TaskGroup` | `Task<T>` for a root of type `T`, `VoidTask` for a `Void` one; the root's call is the task's, so its suspension is not the spawner's | task_spawn |
| `group.spawn(f(x))` on a `TaskGroup`, a local, a field or through a `&TaskGroup` | the group borrowed shared for the spawn; the handle and the root as `Task.spawn`'s | group_spawn |
| `Thread.spawn { ... }`, under a std root declaring `std.task.Thread` and `std.systemerror.SystemError` | `Result<Thread<T>, SystemError>` for a body of type `T`, `Void` included; a builtin call whose brace is its operand (`Thread.spawn` under Stage 0's std, which has no `SystemError`, is `slice.not-yet`, its brace still checked) | thread_spawn; thread_body_std_table |
| a subscript | a getitem, setitem or place accessor call, or an array's builtin | places, funnel |
| `o!`, `-x`, `not b`, `~x`, `&x`, `&var x`, `move x`, `move o!`, `*p` | the payload place, the operand's type, a reference, the moved value, the payload moved out of the optional place (design 131), the pointee | places, operators, conversions, builtin_values |
| arithmetic, bit, shift, comparison, logic, `??`, `as`, `a..b` | agreeing operands; builtin or a declared `equals`/`compare` | operators |
| a raw-backed enum's `as` to an integer | a borrow of a place, through a reference too, at every copy tier, since the enum is its tag (spec, Raw-backed enums); a temporary or a `move` handed off; the same-type cast a by-value read (SL-623); a `borrow PLACE` or a part of one read in place, as every `borrow` subscript is (SL-642) | raw_enum_cast; transfer.implicit-copy.raw-enum-forwarding; run probe borrow_place_reads |
| `==` on an undeclared generic POD struct, `Pair<Int> == Pair<Int>` | the automatic `Equatable`, judged per instantiation (SL:open-questions D18) | partial_arguments |
| `==`, `<` on a type parameter, a trivially copyable struct, a tuple | a bound's `equals` or `compare` ("A `T: Equatable` generic bound grants `==`"); the structural comparison of the automatic `Equatable` ("trivial (POD) structs"), and of a tuple whose elements all are ("Tuples are Equatable iff every element is") | comparisons |
| `==`, `!=` on whatever `satisfies` grants `Equatable` through its parts with no `equals` of its own: a tuple, an Optional, a fixed array, nested in each other, holding a `String`, or a trivial struct holding an array (SL-759) | the bound's answer, asked of the same funnel; compared in place where `compares_in_place` (`typeops.saw`) holds, as before, and otherwise a call to the `Equatable.equals` requirement at the type, `!=` its negation, which mono's member glue answers as it answers the bound | comparisons; run program structural_equality_operator |
| `try`, `try!`, `try?` | the `Ok` type, its error propagating into the innermost `try` block around it, else into the body's Result; a `try` in a closure leaves the closure | carried, catches |
| an inline catch, `try e catch { … }` | the `Ok` type, the catch block a branch of that type in a statement too (spec, Inline Catch: "either produces the fallback value or diverges"), its `error` the operand's error type, an erased `Box<any Error>` as written | catches; type.mismatch.try-catch, operator.undefined.try-catch |
| a `try` block, `try { … } catch { … }` | the type its body and catch block merge into, as an `if`'s branches do, in a statement too, as Stage 0 has it; its `error` the one error type its `try`s propagate, however many do, or `Never` where none does | catches; type.mismatch.try-block |
| an optional assignment, `a?.b = v`, `a?.b op= v` and their `borrow var` forms | `Void?`, which a statement discards and an optional binding's subject, `if let _ = a?.b = v`, tests, its binding a `Void`: each `?.` hop a place of its base's payload's field (`project`), the top hop `write` or `update`, the value checked against the field as an assignment's or a compound assignment's is; a conditional lend's head takes no second `?` | catches; borrowing.lend-chain, operator.undefined.optional-assign, type.not-a-place.optional-assign, mutability.immutable.optional-assign |
| tuples, repeat, `Map` and `Set` literals | from the slot, or the first element | funnel |
| a repeat literal's element | refused unless it copies silently, a temporary's too (spec, Composite Types); a type parameter's an implied copy at the literal (SL-612) | copy_free_reads; transfer.implicit-copy.repeat-temporary, copy.requirement.repeat |
| a bracket literal | a `Vector` where the slot is one; otherwise a fixed array `[T; N]`, `T` from the slot or the first element and `N` its element count (spec, Composite Types: "with no expected type it is a fixed-size array") | arrays, funnel |
| a closure | parameters written or from the slot's function type, or, as a generic call's argument, from the parameter type once inference has solved its parameters; result from the slot or its tail; with no slot, from its first `return`, which the later `return`s and the tail must agree with, so a body whose every path returns has what it returns (design 213, SL-476): all-`return`, a `return` beside a tail, `return`s in `if`/`match` arms and a loop, a generic parameter's slot, a bare `return`, a nested closure's `return` kept to it | control, closure_inference, closure_returns; type.mismatch.closure-returns, .closure-returns-fall-off, .closure-returns-tail |
| a closure's captures: a Copy local named with nothing written, `[move x]`, `[copy x]`, `[&x]`, `[&var x]`, a reference parameter, `self`, `[&self]`, `[&var self]` | copied, moved, or borrowed as the word or the receiver says; a borrow of the frame only in a closure passed straight to a parameter whose function type does not say `escaping`. A reference, a slice's included (`is_reference`), is a borrow of the frame under every word, each a reborrow of its referent: `[r]`, `[copy r]` and the implicit capture in the reference's own mode, `[&r]` and `[&var r]` in theirs; `[copy r]` of a `&var` reference is refused, a second writer (`capture.copy.exclusive-reference`), and `[move r]` moves out of a borrow, as `move r` does, and so does `[move x]` of a borrowed match payload or of an enclosing closure's borrow capture (SL-607) | captures; transfer.implicit-copy.capture, capture.copy, capture.escaping-borrow, capture.escaping-borrow.copy-reference, capture.escaping-borrow.slice, capture.exclusive-self, transfer.move-from-borrow.capture-reference, -capture-payload, -capture-inner |
| `if`, `match` | the merged branch type, or `Void` as a statement | control, patterns |
| `while`, `while { }`, `while let`, `for`, `break`, `continue`, `return` | `Void`, or `Never` with no `break` | control, places |
| `let`, `var`, destructuring, assignment, compound assignment, `guard`, `lend` | statements | funnel, patterns, declarations |
| a `borrow` block, `borrow` place, `if borrow let` | the place's type, borrowed | borrows |
| `lends self`, a reference field's value in the construction a `borrows -> S` function returns | `&Self`, shared, typed as `&self` is; any other operand, a `&var self` receiver, and every other position refused (the origin funnel, below) | declarations; lends.origin, lends.position, slice.not-yet.lends-exclusive |
| `borrow var PLACE`, `borrow PLACE` where a `&var T` or `&T` parameter expects it | the place passed by reference, `&var T` or `&T` (SL:borrowing §2.2) | borrow_arguments |
| a default value whose parameter's type is a type parameter, `b: T = 0` | a literal typed as written, whose type drives each call's inference, or `None`, which needs each call's `T` optional; checked against each call's `T` (design 108) | generic_defaults; generic-default |
| patterns: wildcard, literal, range, tuple, variant, name, `None`, borrow binding | the matched type; bindings copy, take, move or alias | patterns, places |
| a lone name pattern resolve took for a case | that case of the matched enum, else refused (D13) | patterns, multi/cases |

| outside the slice (bodies) | refused as |
|---|---|
| an optional chain read, `a?.b`, and a call through `?.` in an optional assignment's target | `slice.not-yet` (`syntax.expr.optional-member`) |
| a `try` block whose `try`s propagate more than one error type, which its `error` holds as their union | `slice.not-yet` (error-union) |
| a `try(as ...)` route | `slice.not-yet` (the alternative) |
| an open range, `a..` or `..b` | `slice.not-yet` (the alternative) |
| `for borrow`, `while borrow`, `move *p` | `slice.not-yet` (the alternative) |
| `lends self` from a `&var self` receiver | `slice.not-yet` |
| `break` with a value | `slice.not-yet` (`syntax.stmt.break`) |
| a method or static method named without its call | `slice.not-yet` (`syntax.expr.member`) |
| a call of a type parameter with arguments, `T(x)` | `slice.not-yet` (`syntax.expr.call`) |
| a generic static method called on a generic type written without its type arguments, whose call would solve the type's parameters and the method's at once (SL-657) | `slice.not-yet` (generic-static-bare-head) |
| `sleep`, `cancelled` | `slice.not-yet` (sync-only) |
| a call whose signature names a type from a std module the parser refuses | `slice.not-yet` |
| a default of a type parameter's type that is no literal and no `None` | `slice.not-yet` (generic-default) |
| a `??` whose fallback is wider than the optional's payload | `slice.not-yet` (coalesce-wider) |
| constructing a builtin type no declaration writes an `init` for, `UnsafeMemory<T, U>(a)`; `Atomic(v)` and `UnsafeMutableInterior(v)` are their lang roles' positional constructions | `slice.not-yet` (builtin-construction) |
| a `borrow` block over a method that lends through a closure parameter, as `borrow var c = m.lock() { ... }` | `slice.not-yet` (lock-borrow) |
| calling a `FuncPointer`, a function or closure where one is expected | `slice.not-yet` (func-pointer) |
| downcasting an erased box, `b.is<T>()` and `b.take<T>()` | `slice.not-yet` (erased-box-downcast) |
| a method of the interior cell, `c.ptr()` | `slice.not-yet` (cell-method) |

## The summary and check position matrices

Each position a U6b3 rule quantifies over, and the golden case or refusal
fixture (`refuse/RULE.VARIANT`) that covers it.

**Suspension and sync-callability** (SL:architecture §3.4, "Effects"):

| position | answered by | covered by |
|---|---|---|
| a call of a function with a checked body | its summary, at the call's type arguments | summaries |
| a call of a std function | its row of the std suspension table | summaries (`Vector.map`, `yield_now`) |
| a call of a new-std function | its summary, its body checked; a park point of `std.task` suspends by its lang role | task_vocabulary |
| a call of a test intrinsic, `__saw_test_suspend` or `__saw_suspend` | suspends, under either std | task_vocabulary; effect.sync.test-intrinsic |
| a call of an extern | its `blocking` | declarations |
| a call through a bound | a condition over the caller's parameter | summaries; effect.sync.bound |
| a call through a function value | never suspends; sync-callable when its type says `sync` | summaries; effect.sync.value |
| a call of a function with a default value | its summary, which leaves its defaults out: the caller evaluates a default, so the function's body alone decides, whichever argument the call passes (LANGUAGE_SPEC, "Default parameter values") | coro golden default_caller; probe default_caller_suspends (`f(n: 2)` in a `sync` body) |
| the call of a default a call leaves out, `f.n` in `f()` | the default's own summary, at the call's type arguments (`eval_default`), owed by the body the call is in (`eval_call`): a `sync` body or a closure body that leaves a suspending default out is refused | mir golden default_suspension; effect.sync.default-filled, effect.sync.default-condition, effect.closure-suspends.default, effect.sync.requirement-default-bound |
| the call of a bodyless requirement's default a call through a bound leaves out, `P.m.n` in `t.m()` | the requirement's default's own summary, solved in the worklist with the requirement's unit, which holds only its defaults | mir golden default_requirement; run requirement_default, probe requirement_default_bound |
| the call of an interface-only std function's default | the function's summary, since no default of an interface is checked | mir golden default_requirement |
| a spawn form's root call, `f(x)` in `Task.spawn(f(x))` | the task's call: its suspension and its sync-callability stay in the task, while its instantiation's Copy and refusal conditions bind the spawner (`eval_call`); each default it leaves out is the spawner's, whole | task_spawn (the `sync` spawner `start`); effect.sync.spawn-default |
| a drive site's root call, `f(x)` in `__saw_drive(f(x))` | the driver's call, as a spawn root is the task's (`eval_call`): a body whose only suspending call is a drive root does not suspend; each default it leaves out is the driver's, whole | drive_site (the `sync` driver `start`); effect.sync.drive-default |
| a call in a `sync` function, a `deinit`, a closure of a `sync` type, a `sync` bodyless requirement's default | refused when not sync-callable | effect.sync, effect.sync.deinit, effect.sync.closure, effect.sync.requirement-default |
| a `sync` requirement met by a member not declared `sync` | the member's summary | effect.sync.requirement |
| a hand-written `copy()` of a `Copy` or `ExplicitCopy` conformance | refused at the conformance when it suspends | effect.sync.copy-hook |
| a call in a closure body | refused when it may suspend, at once or at the instantiation | effect.closure-suspends, effect.closure-suspends.instantiation |
| a call in a `Thread.spawn` body | refused when it may suspend by any cause but `blocking`: each summary carries its causes (park point, `blocking` extern, test intrinsic, `any` dispatch, function value, unclassified), a std row's from the table | effect.thread-body, effect.thread-body.test-suspend, effect.thread-body.closure-call; thread_spawn (`nap`, a direct `blocking` call); thread_body_std_table |
| a coercion to `any Trait` | refused when an implementation it dispatches to may suspend | effect.any-suspends, effect.any-suspends.instantiation |
| a call in a `borrows(sync)` window, `borrow` block or `for` | refused when it may suspend | borrows.sync-window; body_rules |
| a call site of a body that copies its `T` | the Copy tier of the site's argument | summaries; copy.requirement; path_uses |
| a call site of a body whose repeat literal's element is its `T`, a temporary's or a place's | the Copy tier of the site's argument, the copy quoted at the literal | copy.requirement.repeat; copy_free_reads |

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
| a read before a propagating `try` in a `try` block's body, and one in its catch block | `copy`, both quoted | catch_paths `caught` |
| a read after a `try` block's last `try`, and one in its catch block | `move` each | catch_paths `untried` |
| a read in an inline catch's operand, and one in its catch block | `copy`, both quoted | catch_paths `inline` |

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

**Duplicate arms** (spec, Control Flow). Patterns compare by the values
they test, read by `pattern_value` (`fold.saw`), which MIR's decision tree
reads too (SL-609); a hole is one pattern whether it is `_` or a name. `d.`
abbreviates `refuse/match.duplicate.`, and run program
`compiler/tests/run/match_literal_values.saw` holds the accepted controls
against Stage 0:

| position | verdict | covered by |
|---|---|---|
| `case 1` twice | refused | match.duplicate |
| `Move(a, b)` after `Move(x, y)` | refused | d.variant |
| `0x10` and `16` | refused | d.hex |
| `-1` and `- 1` | refused | d.negative |
| `1_000` and `1000_u16` | refused | d.separator |
| `"a"` and `"\u{61}"` | refused | d.string |
| a repeat inside a tuple and a payload | refused | d.nested |
| a binding, then `_` | refused | d.catch-all |
| a repeat whose first arm is guarded | allowed | match_literal_values |
| two equal ranges, a literal inside a range | allowed | match_literal_values |
| `-1` beside `1` | allowed | match_literal_values |

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
| a `borrows` call lending one as an argument, a receiver, or any other value position but a head | refused | borrowing.containment.argument, .receiver |
| a construction outside a returning path of the `borrows` function that lends it | refused | borrowing.containment.construction |
| a `for` head, a `borrow` head, a reference parameter | allowed | body_rules |

**The origin funnel** (`check_lend_origins`, `compiler/typecheck/src/bodychecks.saw`;
spec, Borrowing structs, "The origin is the receiver"). A borrowing struct
points into the one root the call site's window charges: every returning path
of a `borrows -> S` function, the tail and each `return` through the arms of a
value `if`, `match`, `try` block and `catch`, ends in a construction of `S`
whose every reference field is `lends self`, and nothing else constructs one.

| cell | verdict | covered by |
|---|---|---|
| `lends self` from a `&self` receiver, on every path | allowed | declarations; run `lends_for`, `lends_for_suspends` |
| `lends self.items`, a projection | refused | lends.origin |
| `lends other`, a reference parameter | refused | lends.origin.parameter |
| `lends spare`, a local | refused | lends.origin.local |
| `lends self` from a `&var self` receiver | refused | slice.not-yet.lends-exclusive |
| `lends self` outside such a construction | refused | lends.position |
| a path yielding another producer's result | refused | lends.path |
| a path whose construction fills a reference field with something else | refused | lends.path.construction |

**Object safety** (spec, "Object safety (v1)"; SL-510). Every existential
type is interned by `mk_any`, whose one caller is the type funnel's `any
Trait` arm, so each erasure starts at a written `any Trait` node, and the
funnel (`check_object_safety`, `compiler/typecheck/src/erasure.saw`) judges
each one once the requirements are known, refusing it where it is written, as
the spec's "rejected at the point the existential is written" says. A
coercion to `&any T`, `&var any T` or `Box<any T>` is refused through the
written type it converts to, and adds no refusal of its own. The reasons, in
the order they are asked, over the trait's own requirements and then its
parents': a marker trait, which has no requirement once `Deinit`'s `deinit`
is set aside (no dispatch reaches it); an associated type; a static
requirement, which has no receiver to dispatch on (spec, Serialization:
"a static requirement has no receiver to dispatch on … rejected at the point
the existential is written"); and a requirement naming `Self` at any depth of
its result or a parameter, a default body's signature included. A generic
requirement is not a reason while SL:open-questions Q23 holds:
`trait.generic-requirement` refuses it at the requirement, and its erasure
adds nothing. Under `erasure.not-object-safe`, `o.` abbreviating
`refuse/erasure.not-object-safe.`:

| reason | coercion | field `Box` | parameter `Box` |
|---|---|---|---|
| `Self` in a parameter (`other: &Self`) | `erasure.not-object-safe` (bare), o.exclusive | o.self-param-field | o.self-param-box |
| `Self` in the result (`-> Self`) | o.self-result | o.self-result-field | o.self-result-box |
| an associated type | o.associated | o.associated-field | o.associated-box |
| a marker trait | o.marker | o.marker-field | o.marker-box |
| a static requirement | o.static | o.static-field | o.static-box |

| row | verdict | covered by |
|---|---|---|
| `Self` nested in the result, `-> Result<Self, Int>` | refused | o.self-result-nested |
| `Self` 34 tuples deep in a parameter (SL-627) | refused | o.self-param-deep |
| an inherited requirement naming `Self`, `trait Shape: Equatable` | refused, naming `Equatable.equals` | o.inherited |
| an inherited associated type, `trait Sized: Iterator` | refused, naming `Iterator.Item` | o.associated-inherited |
| a `Self`-naming requirement with a default body (the spec exempts none) | refused | o.default-body |
| the Copy family, `any Copy` | refused | o.copy |
| `Send`, `NoCopy` (whose one inherited requirement is `Deinit`'s), a trait refining only `Sync` | refused | o.marker-send, o.marker-no-copy, o.marker-refining |
| `any UnsafeSync`, pointing at the conformance header (spec, `UnsafeSync`, "Three fences") | refused | o.unsafe-sync |
| an enum payload, a function's result, a Result's error box, a `Vector` element, a type alias, a function type's parameter, another trait's requirement, a `let` annotation | refused | o.payload, o.result, o.error-result, o.generic-argument, o.alias, o.function-type, o.requirement, o.let-annotation |
| a trait with a generic requirement, erased | `trait.generic-requirement` alone | trait.generic-requirement |
| `&self` and `&var self` requirements, a default body naming no `Self` in its signature, an object-safe parent; `Printable`, `Error`, `Hashable`; at `&any`, `&var any`, a field's and a parameter's `Box`, a `Vector` element, `Result<Int, Box<any Error>>` | allowed | object_safety |

**Dispatch** (spec, `any Trait` existentials; SL-721). A method call whose
receiver, read through its references, is an `any Trait` or an erased
`Box<any Trait>` is resolved by one funnel (`dispatch_call`,
`compiler/typecheck/src/bodies.saw`) against the requirements the trait's
vtable carries (`dispatch_requirements`, `compiler/typecheck/src/erasure.saw`:
the trait's own, then each parent's, instance requirements only, `Deinit`'s
left out). The candidates' owner is the existential, so `Self` is it and the
call records the requirement at that owner, which mono lowers to a vtable
slot. The receiver is dereferenced to the existential, through a reference
or through the box, then borrowed as the requirement declares, so every
dispatch's receiver is `&any Trait` or `&var any Trait` and the writability
funnel judges an exclusive one at the place it was reached through. The
erasing `Box<any Trait>.make(v)` records the erasure on its argument, as a
return into an erased `Result` does, and an erasure of a primitive is
refused wherever one is recorded. Under `refuse/`:

| row | verdict | covered by |
|---|---|---|
| a `&self` and a `&var self` requirement, a default body, a parent's requirement, a requirement with arguments and a result, at `&any`, `&var any` and a `var` box | allowed | dispatch |
| a `&var self` requirement through `&any` or through a box a `let` holds | refused | mutability.immutable.existential-receiver, mutability.immutable.erased-box-receiver |
| a method the trait does not declare | refused | member.unknown.existential |
| a consuming requirement | refused by the parser at the requirement | parse's `syntax.rule.requirement-borrows` |
| a generic requirement | `trait.generic-requirement` at the requirement | trait.generic-requirement |
| a requirement of a trait that is not object-safe | `erasure.not-object-safe` where the existential is written, the call adding nothing | erasure.not-object-safe |
| `Box<any Trait>.make` of a value that does not conform, of a primitive | refused | type.mismatch.erase-box-make, erasure.primitive.box-string |
| a value assigned into a `&var any Trait`'s referent, which would erase into a bare `any Trait` | refused | type.mismatch.erase-bare |
| `b.is<T>()`, `b.take<T>()` on an erased box | `slice.not-yet` | slice.not-yet.erased-box-downcast |
| a `&any Trait` parameter of a suspending function, dispatched on both sides of a suspension | allowed (SL-721's ruling): the frame holds the reference's two words | run probe erased_reference_across_suspension |
| a write to that parameter's referent while the suspended frame holds it | driven: unreachable, since a drive parks its caller; spawned: refused by the borrow check, since the task's handle holds the referent until its join (SL:coroutines A8c); in one argument list beside the suspending call: refused as for a plain reference | borrowck's loan.write-while-shared.spawn-erased, loan.nested-call.erased-suspending |

**Statics are `Sync`** (spec, Module-level statics: "Sync-only"; Interior
mutability; SL-537). Checked with a static's other signature rules
(`check_static_type`, `compiler/typecheck/src/bodychecks.saw`) by the bound
check every `Sync` question goes through (`satisfies`), so a declared
`UnsafeSync` answers first, its conditions held to the static's arguments,
and the derivation is blocked at the interior cell itself, so only a type
holding a cell directly owes the declaration. Under `static.not-sync`, `s.`
abbreviating `refuse/static.not-sync.`; the `calls/` programs of the std lane
hold the same rows under the new std:

| row | verdict | covered by |
|---|---|---|
| a struct holding a cell with no `UnsafeSync` | refused, naming the field and `extension Counter: UnsafeSync {}` | `static.not-sync` (bare); std call `static_not_sync` |
| a struct holding such a struct, named down to the cell's holder | refused | s.nested |
| an array of one; an enum whose payload is a cell, held in an Optional so the static's zero is valid | refused | s.array, s.payload |
| a struct holding a raw pointer | refused, naming the field | s.pointer |
| a conditional `UnsafeSync` at an argument that fails its bound | refused, naming the bound and the argument | s.conditional |
| `Atomic<Int>`, which declares `UnsafeSync`; a cell holder declaring it; a struct holding those, which derives `Sync`; a conditional `UnsafeSync` met; a scalar; an `unsafe static var` of a type that is not `Sync` | allowed | static_sync; std call `static_sync` |

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
| a `borrow var` statement writing through std's `Arc.value`, whose hint names `Arc<Mutex<T>>` and `unique()` rather than a writable accessor (SL-712) | refused | mutability.immutable.arc-value |
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
| a `[&v]` capture's write through a `&var` reference parameter, and through a `&var` slice: the capture narrows it, as `[&self]` narrows `&var self` (SL-607) | refused | mutability.immutable.shared-capture-reference, mutability.immutable.shared-capture-slice |
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
| a lend's `&[Int]?` allowed, and the same type held as a vector's element, which its parts' answer, kept by the type, does not excuse (SL-639) | refused | type.reference-position.lent-then-held |
| `let r = &x`, `var r = &var x`: a bare `&` bound | refused | type.reference-position, type.reference-position.exclusive-binding |
| a bare `&` in an array literal, a tuple literal, an operator's operand, a closure's tail, a cast to an integer | refused | type.reference-position.array-literal, type.reference-position.tuple-literal, type.reference-position.operand, type.reference-position.closure-return, type.reference-position.cast-to-integer |
| a binding whose inferred type names a reference: only a bare `&` builds one, as an argument instantiating a generic | refused | type.reference-position.inferred-binding |
| a reference binding passed with no sigil to a reference parameter, a function's, a `&var` one's, a method's; and to the reference overload when no by-value one fits | refused, `type.mismatch` with the sigil written out | type.mismatch.unsigiled-reference, type.mismatch.unsigiled-exclusive, type.mismatch.unsigiled-method-argument, type.mismatch.unsigiled-overload |
| a slice binding passed with no sigil to a slice parameter: a slice is forwarded as a reference is, and `&s`, `&var s` reborrow it in the sigil's mode (SL-607) | refused, `type.mismatch` with the sigil written out | type.mismatch.slice-unsigiled |
| a closure whose inferred result is a slice binding's value: a slice's elements are no one value to read through to (SL-607) | refused | type.reference-position.closure-slice-result |
| `&var x` for a `&T` parameter: a free function's, a method's, a static method's, an initializer's, by label, a function value's; `borrow var p` for one (SL-484) | refused, `type.mismatch` naming `&x` or `borrow p` | type.mismatch.sigil-exclusive, -exclusive-method, -exclusive-static, -exclusive-init, -exclusive-labeled, -exclusive-closure, -exclusive-borrow |
| `&x` or `&var x` for a parameter taken by value: Copy, NoCopy through a reference, ExplicitCopy, a generic method's `T` (SL-484) | refused, `type.mismatch` dropping the sigil | type.mismatch.sigil-to-value, -to-value-exclusive, -to-value-nocopy, -to-value-explicit, -to-value-generic |
| an operator's reference operand, `a + &b` | refused as a bare `&` operand before any sigil question | type.reference-position.operand |
| each call shape with its parameter's own sigil; a `&var` reference forwarded as `&`; `f(p)` picking `f(Int)` over `f(&Int)`; Stage 0's `s.compare(&t)` reaching the requirement | allowed | call_sigils |
| a reference to a NoCopy value read by value into an aggregate | refused, `transfer.implicit-copy` | transfer.implicit-copy.reference-read |
| a reference to an optional of a NoCopy or ExplicitCopy payload, `&` or `&var`, as `??`'s left operand; a reference to a NoCopy value as a cell's value: each read through the reference before the copy check (`read_value`, SL-612) | refused, `transfer.implicit-copy` | transfer.implicit-copy.coalesce-reference, -coalesce-exclusive-reference, -coalesce-explicit-reference, -cell-reference |
| the same with a Copy payload or referent, a cell and an `Atomic` over `&Int` | allowed | copy_free_reads |
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
| a `[move x]` capture of a reference parameter, of a payload binding over a borrowed scrutinee, of an enclosing closure's `[&x]` capture: one rule with `move x` (SL-607) | refused | transfer.move-from-borrow.capture-reference, .capture-payload, .capture-inner |
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
| a value holding one 18 tuples deep (SL-627) | refused | n.deep |
| a fresh by-value parameter placed by `ptr[0] = move value`; lending by `&var`; replacing a referent whole | allowed | no_move |

The declaration side (SL-485; rows V121-V123), checked with the
containment rules (`check_no_move_declarations`):

| row | verdict | covered by |
|---|---|---|
| a struct's `NoMove` field, an enum's payload, one in an optional, a generic instance at a `NoMove` argument, undeclared | refused | nomove.undeclared, .payload, .wrapped, .instance |
| one 18 tuples deep, undeclared (SL-627) | refused | nomove.undeclared.deep |
| `T: NoMove` on a function's and on an extension's parameter | refused | nomove.bound, nomove.bound.extension |
| `NoMove` with no declared `NoCopy`, beside `ExplicitCopy` | refused | nomove.requires-nocopy, nomove.requires-nocopy.explicit |
| a container declaring `NoCopy` and `NoMove`; a pointer holder; a generic holding `T` | allowed | no_move |

**Cell-carrying** (spec, Interior mutability). `is_cell_carrying` answers
whether a type holds an `UnsafeMutableInterior` in its own storage; the
backend withholds `noalias` from a shared reference to one (SL-592). It
refuses nothing, so its rows are a unit program's:
`compiler/typecheck/tests/cell_carrying.saw` asks it of every parameter type
in `inject/cell_carrying.saw`, which names each row by its function.

| row | answer |
|---|---|
| the cell; `Atomic<Int>`; a struct holding an `Atomic`, which derives `Sync`; `Wrap<T>` at a cell, and nested; an Optional, a tuple and an array of one; an enum case's payload, `Result`'s `Ok` and its `Err` | carrying |
| `Int`; a plain struct; `Wrap<Int>`; an Optional of a plain struct; an enum of plain payloads; `Result` of plain types; `String` | free |
| a struct holding an `UnsafePointer` to a cell; `Box`, `Vector` of a cell; a reference to one | free: the cell is behind a pointer |
| `Wrap` 66 deep at a cell, and at `Int` (SL-627) | carrying, free |

**Shared parts** (SL-639). A type's parts are a DAG: `D{k} = (D{k-1},
D{k-1})` has 2^k paths over k+1 types, so each walk over parts answers once
per part. `compiler/typecheck/tests/shared_parts.saw` checks
`inject/shared_parts.saw`, 40 deep, clean, verifies its bodies, and asks each
question of a `yes_` row's parameter and of the `no_` row beside it, whose
paths end at a different part.

| row | question | answer |
|---|---|---|
| a written parameter, an `Equatable` bound on it, a written parameter unified with its argument, and a generic body whose inferred types share their parts | checked clean | |
| a shared tuple of `Int`s, and of a NoCopy struct | `Equatable`, `copies_silently` | holds, fails |
| a struct reaching itself through 40 nested pairs, and the same reaching a non-`Send` part too | `Send` | holds, fails |
| a generic struct's shared field, at `Int`, and the same of a non-`Send` part | `Send` | holds, fails |

**Copy-policy containment** (spec, The Copy Trait Family, "Containment" and
"The automatic `Copy` tier"; `check_containment`). The members whose retain
the compiler handles itself put a struct on the automatic tier with no
policy owed; a field of a declared Copy type does not. The two golden
programs run under `--std-root std`, where `String`'s Copy is a written
conformance and still owes nothing (SL-515); the fixtures run under Stage 0's
std, the only one with an `Arc`; `c.` abbreviates
`refuse/copy.undeclared-policy.`:

| member | verdict | covered by |
|---|---|---|
| a `String` field, a `[String; 3]`, a `String?`, a struct on the tier through one, an enum's `String` payload | allowed | string_fields |
| a NoCopy field beside a `String` field | refused, naming the NoCopy field | string_field_refusals |
| a field of std's `Data`, of a user type declaring `Copy` | refused | string_field_refusals; c.data, c.retain-hook |
| an `Arc<T>` field | refused | c.arc |
| an ExplicitCopy field; an enum's NoCopy payload | refused | `copy.undeclared-policy` (bare), c.enum |

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
`.explicit`. A requirement on a parameter of a method's type is declared by
the method's extension (SL-501): a public method in an extension that does not
grant the parameter `Copy` refuses, `.extension`, through a callee too,
`.extension-callee`, and so does a method in an extension declaring `T:
ExplicitCopy` that its body exceeds, `.extension-explicit`; a trait default
body publishes as its trait does (golden `declared_bounds` holds the accepted
rows). A private generic rides inference, its call sites checked by
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
| a `Thread.spawn` brace consuming its capture | allowed: the brace is exempt | golden `thread_spawn` (`fan`'s `[move v]`) |

## The conformance rows

The rows of `examples/conformance/INDEX.md`'s Mutability and References
sections, and V03–V05, V31, V49, V60–V62, V68, V70 and V124, V126–V128, V131 and V150–V153 of its Moves section, each
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
| M27 | accepted: an interior cell's `&self` method borrows shared, which no row of the funnel asks about; a `&var self` requirement through `&any` or a `let` box is `m.existential-receiver`, `m.erased-box-receiver` |
| M28, M32, M41 | language changed (SL:borrowing §9, SL-483): `m.shared-receiver-heap-method` (M28), `m.shared-receiver-heap-chain` (M32), `m.shared-receiver-heap`, `-heap-compound`, `-heap-accessor` and `-heap-chain` (M41) |
| M34, M35 | accepted: golden `mutability` (writes under `&var self`) |
| M33 | `m.shared-accessor-window`: a `&self` accessor's prologue writing a window on inline storage; its heap form, `m.shared-accessor-heap` (SL-483) |
| M29 | accepted: golden `mutability`, `borrow_arguments` |
| M30, M31, M36, M37 | `m.static`, `m.shared-receiver-window`, `m.shared-capture-self`, `m.array-element` and `m.array-element-compound` |
| M38 | the borrow check (U6d2) |
| M39, M40 | `slice.not-yet` (`syntax.stmt.optional-assign`) |
| M42, M43, M44 | `m.shared-receiver-array`, `m.optional-payload`, `m.array-element-receiver` |
| M45 | `m.shared-capture-reference`, `m.shared-capture-slice` (SL-607) |
| R01, R02, R03, R04, R05 | `r.return`, `r.method-return`, `r.requirement-return`, `r.extern-return`, `r.function-type-return` |
| R06, R07, R08, R09, R10 | `r.return-tuple`, `r.return-optional`, `r.return-vector`, `r.field`, `r.payload` |
| R11, R12, R13, R14, R15 | `r` (bare), `r.exclusive-binding`, `r.type-argument` and `r.local-annotation`, `r.explicit-instantiation`, `r.closure-return` |
| R16, R17, R18, R19, R20, R21 | `r.array-literal`, `r.tuple-literal`, `r.map-value`, `r.static`, `r.alias-field`, `r.alias-return` |
| R22, R23 | `capture.escaping-borrow` and `capture.escaping-borrow.explicit`: a closure bound to a `let` or passed to an escaping parameter, the `[&x]` spelling |
| R24, R25 | the borrow check (U6d2): a `group.spawn` root's borrow is a loan its handle holds (SL:coroutines A8c) |
| R26, R27, R29, R31, R32, R34 | `r.optional-written`, `r.nested-generic`, `r.cast-to-integer`, `r.operand`, `r.box`, `r.field-function-type` |
| R28, R30, R33 | accepted: golden `reference_positions` (the pointer cast, the `borrows` lends), `captures` (a non-escaping borrow capture) |
| V03, V04 | `b` (bare), `b.shared` |
| V05, V31 | `p` (bare), `p.vector-element` |
| V60, V61, V62 | `b.match-payload`, `b.match-self`, `b.match-payload` (a Copy-tier payload) |
| V68, V70 | `b.closure-parameter` |
| V49 | `capture.escaping-consume` (bare): an escaping closure's consume of its `move` capture is refused (SL-469) |
| R43, R44 | `capture.escaping-borrow.reference-container`, `capture.escaping-borrow.local-container` (SL-467) |
| R45, R46, R47 | `capture.escaping-borrow.slice`, `capture.escaping-borrow.copy-reference`, `r.closure-slice-result` (SL-607) |
| V124 | `b.capture-reference`, `b.capture-payload`, `b.capture-inner` (SL-607) |
| V126 | `transfer.implicit-copy.repeat-temporary`, `-repeat-explicit`, `-repeat-slot`, `-repeat-place`, `-repeat-move`, `copy.requirement.repeat`; the Copy controls, golden `copy_free_reads` (SL-612) |
| V127, V128 | `transfer.implicit-copy.coalesce-reference`, `-coalesce-exclusive-reference`, `-coalesce-explicit-reference` (V127), `-cell-reference` (V128); the Copy controls, golden `copy_free_reads` (SL-612) |
| V131 | accepted: golden `raw_enum_cast`, a raw-backed enum's cast borrowing its place; the same-type cast's refusal beside it, `transfer.implicit-copy.raw-enum-forwarding` (SL-623); a `borrow PLACE` operand, whole or a field of one, run probe `borrow_place_reads` (SL-642) |
| V150 | `copy.second-policy` (bare), `.no-copy`, `.explicit-no-copy`, `.one-extension`, `.bounded`, `.bounded-both` (SL-641) |
| V151 | `copy.outside-policy` (bare), `.declared`, `.explicit`, `.enum`, `.generic`, `.other-conformance`, `.static`, `.defaulted`; the other shapes accepted, golden `copy_method_shapes` (SL-641) |
| V152 | accepted: golden `copy_method_shapes`, a NoCopy type's `copy()` called by name; `transfer.implicit-copy.nocopy-copy-method`, `type.bound.nocopy-copy-method` (SL-641) |
| V153 | `overload.indistinguishable.deinit`, `.copy`, and the redeclaration matrix under Refusals (SL-641) |

That is 45 M rows, 39 R rows and 19 V rows: 89 refused here, 8 accepted
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
| `type.raw-backing` | an enum's raw backing written as a type alias, `Byte`, an alias of it and a user alias alike, since an alias is a distinct type and the backing is a fixed-width or platform integer written as itself; a backing that is not an integer type; a backing on an enum whose case carries a payload (spec, Raw-backed enums; SL-498: `type.raw-backing`, `.user-alias`, `.alias-of-byte`, `.not-integer`, `.payload`; golden `constant_positions` holds the `UInt8` control) |
| `type.raw-value` | a case of a raw-backed enum that states no value (`.missing`), and two cases sharing one, compared by their folded values, so `0x01` is `1` and `1 << 0` is too (`.folded`) (spec, Raw-backed enums, rule 2; SL-609) |
| `type.infinite-size` | a struct or enum on a cycle of the by-value containment graph: its storage contains an instance of itself inline, through fields, payloads, tuples, optionals, arrays and the generic declarations they instantiate, the same instance, a fixed other one (`.fixed-argument`) or an ever larger one (`.growing`); golden `containment_cycles` holds every declaration of a component and the finite controls (SL-627) |
| `type.instantiation-depth` | deriving `Send` or `Sync` from the members of a type nested past the instantiation depth limit (64), which a type holding itself at ever larger arguments behind a pointer reaches (spec, "Instantiation depth is bounded"; SL-627) |
| `conformance.incomplete` | a requirement of a trait, or of a trait it refines, that nothing meets: no member written, no default, no derivation; an associated type no type assignment gives, the conformance's own or, for a parent trait's, the type's conformance to that trait (refined_assignments); for a production conformance, what a test-only extension writes or a test-only parent conformance assigns meets nothing (SL-640: `-test-only-member`, `-test-only-group`, `-test-only-static`, `-test-only-parent-member`, `-test-only-parent-assignment`) |
| `conformance.test-only-overlap` | a test-only conformance to a trait a production type already meets in production code, through a production conformance to a trait refining it, or automatically as a trivially copyable type (`Equatable`, `Hashable`); the same pair twice is resolve's `conformance.duplicate` (SL:testing; SL-629) |
| `conformance.test-only-shadow` | a test-only method, static or `init` of a production type whose signature meets a requirement a production conformance of the type meets with the trait's default or with `@synthesize`, directly or through a refinement (`.refinement`, `.static`, `.test-only-conformance`, `.synthesize`); one met by a written member is `overload.indistinguishable`'s (`.test-only-requirement`), a copy policy's `copy()` `copy.test-only-policy`'s and a `deinit` `deinit.outside-policy`'s (SL:testing; SL-640) |
| `conformance.associated-conflict` | a refining trait's conformance restating a parent trait's associated type as another type than the type's conformance to the parent assigns; a test-only conformance assigning it as another type than a production conformance reaching the parent through a sibling refinement does (`.test-only-sibling`, SL-640) |
| `conformance.signature` | a written member that disagrees with its requirement: receiver, staticness, type parameters, parameters, result, an `unsafe` the requirement declares, `consumes`, or `borrows` (a `borrows(sync)` member never meets a plain `borrows` requirement, SL:borrowing §2.5); a parameter that says `escaping` where the requirement's does not, though the narrowing is met (SL-504: `conformance.signature.escaping`, `-escaping-default`; a function-typed parameter's own parameters are compared exactly, `-escaping-nested`; golden `escaping_values`) |
| `trait.generic-requirement` | a trait requirement declaring generic parameters of its own, which the grammar parses and type checking refuses for now (GRAMMAR §3.4), once, at the requirement: with a default body (`.default-body`), met by a generic method in a conformance (`.conformance`), called through a bound (`.bound`), and its trait erased (bare), none adds a second refusal; golden `generic_methods` holds the accepted control, a generic method in an ordinary extension |
| `synthesize.required` | a declared conformance to a derivable trait whose method is neither written nor asked for with `@synthesize` (design 128); a copy policy's `copy()` counts as written only inside the conformance (`-copy-outside-policy`) |
| `synthesize.inert` | `@synthesize` on a conformance that derives nothing |
| `nomove.undeclared` | a struct or enum holding a `NoMove` value inline, a field, a payload, through an optional, a tuple, an array or a generic instance, that does not declare `NoMove` itself (design 188) |
| `nomove.bound` | `NoMove` written as a generic parameter's bound |
| `nomove.requires-nocopy` | a `NoMove` conformance on a type whose policy is not a declared `NoCopy` |
| `zeroinit.override` | a `ZeroInit` conformance on a struct whose construction an `init` overrides, naming the override (SL-660) |
| `zeroinit.invalid` | a `ZeroInit` conformance on a struct with a field whose zero is not valid, at any depth: a part with no valid zero, a type parameter the conformance does not bound by `ZeroInit`, a field of another module's type it cannot see, or an override; or on an enum whose zero is no case (SL-660) |
| `copy.undeclared-policy` | a struct or enum with no policy holding an ExplicitCopy or NoCopy member, or a struct with a field of a declared Copy type, which `String` is not even where std declares its Copy (spec, "The automatic `Copy` tier") |
| `unsafe.undeclared` | a function whose parameters, result or receiver name an unsafe type, or whose body (its closures included) names, binds, receives or returns a value of one or names an `unsafe static var`, and which is not declared `unsafe` (designs 130, 136 and 149) |
| `unsafe.function-type` | a function type that names an unsafe type without saying `unsafe`, or says it without naming one |
| `unsafe.type-name` | an `unsafe struct` not named `Unsafe*` |
| `init.result` | an `init` returning neither its receiver nor `Result<Receiver, E>`; an optional on its own terms |
| `init.override-outside-module` | an `init` matching a struct's fields exactly, the shape that overrides its memberwise construction, declared outside the struct's module (SL-648; the override matrix below) |
| `init.override-test-only` | an override that is test-only on a production struct, with `conformance.policy-placement`'s reasoning (SL:testing; SL-648) |
| `init.override-bounded` | an override in an extension whose type parameters carry bounds, naming the bound and the unbounded head (SL-648) |
| `init.override-specialized` | an override in a specialized extension, an `init` taking the fields of the instantiation its head names exactly, naming that instantiation and the generic head (SL-648, SL-740) |
| `conformance.deinit` | a conformance to `Deinit` itself, which a copy policy carries instead (design 131); a test-only one included (`.test-only`) |
| `conformance.policy-placement` | a policy conformance, `Copy`, `ExplicitCopy`, `NoCopy`, `NoMove`, `ZeroInit`, `UnsafeSend` or `UnsafeSync`, declared outside the file that defines its type, test code being a file of its own: each policy in an `@test` declaration and in a group, a conditional head, `@synthesize`, an enum, beside a non-policy trait in one head (bare, `.copy`, `.explicit-copy`, `.no-move`, `.unsafe-send`, `.unsafe-sync`, `.zero-init`, `.group`, `.copy-group`, `.explicit-copy-group`, `.no-move-group`, `.unsafe-send-group`, `.unsafe-sync-group`, `.zero-init-group`, `.conditional`, `.synthesize`, `.enum`, `.one-extension`, `.no-move-holder`); the policy matrix above (SL-659) |
| `conformance.derived-only` | a written conformance to `Send` or `Sync`, which the compiler derives from the members and never takes as written (spec, Send and Sync; SL-673): on a raw-pointer holder that a `T: Send` bound would then accept (bare), `Sync` (`.sync`), a type whose members derive it anyway (`.derivable`), a conditional head (`.generic`), an enum (`.enum`), both in one head (`.one-extension`), beside `@synthesize` (`.synthesize`), a test-only extension (`.test-only`) and a test group (`.test-group`); one funnel, `check_derived_conformances`, refuses these, `conformance.deinit`'s, `conformance.derived-parent`'s and `trait.deinit-parent`'s. Golden `thread_assertions` holds the control: `UnsafeSend`/`UnsafeSync` past an unsafe-typed field meet the bounds |
| `conformance.derived-parent` | a conformance to a user trait refining `Send` or `Sync` on a type that does not derive it under the extension's conditions, naming the parent and the blocking field or payload: a raw-pointer holder (bare), `Sync` past an interior cell (`.sync`), an unconditioned generic head (`.generic`), an enum (`.enum`), a refinement chain (`.chain`), a test-only extension (`.test-only`). The parent is required, never granted (SL-673): golden `derived_parent_grants_nothing` keeps the refused type short of a `T: Send` bound, and golden `derived_parents` holds the accepted rows and `T: Shippable` meeting `T: Send` in a generic body |
| `conformance.requires` | a conformance to `Comparable` or `Hashable`, or to a trait refining one, on a type that does not meet `Equatable` under the extension's conditions, as code that may use the conformance sees it (spec, Ordering and Hashing: "requires Equatable"); the requires matrix below (SL-755) |
| `trait.deinit-parent` | a user trait listing `Deinit` as a parent, which only the copy policies `NoCopy` and `ExplicitCopy` do (SL-673) |
| `conformance.assertion-derives` | an `UnsafeSend` or `UnsafeSync` on a type that derives the property from its members under the extension's conditions, its own assertions of it deleted (spec, `UnsafeSync` / `UnsafeSend`, "Legality, checked at the header"; SL-675): a struct of `Send` fields (bare), `Sync` through a member that asserts it (`.sync`), a conditional head whose bound makes the field derive (`.conditional`), an enum (`.enum`). One funnel, `check_thread_assertion`, makes the header checks |
| `conformance.assertion-safe-member` | an `UnsafeSend` or `UnsafeSync` past a field or case payload that blocks the derivation and whose type names no unsafe type, naming it (SL-675): a safe non-`Send` struct, which a `T: Send` bound would otherwise accept (bare), an unconditioned type parameter (`.generic`), a safe non-`Sync` struct (`.sync`), a closure (`.closure`), an enum payload (`.enum`), a member reaching the asserted type again, judged without the assertion as Stage 0 judges it (`.recursive`), a test-only extension (`.test-only`). Golden `thread_assertion_legality` holds the accepted rows: a raw pointer, an interior cell, a type argument naming an unsafe type, an enum payload, and conditional heads |
| `trait.assertion-position` | `UnsafeSend` or `UnsafeSync` written anywhere but a conformance header (spec, `UnsafeSync` / `UnsafeSend`, "Three fences"; SL-675): a function's bound (bare), `UnsafeSync` (`.sync`), a struct's (`.struct`), a method's (`.method`), an extension's condition (`.extension`), a trait's parent (`.parent`). The existential is `erasure.not-object-safe.unsafe-sync`'s, and a header on one instantiation is `extension.specialized-conformance.assertion`'s |
| `deinit.outside-policy` | a `deinit` written in an extension that declares no copy policy, beside the type's policy or on a type with none, where no scope exit would call it (spec, The Deinit trait); a plain test-only extension's included (`-test-only`) |
| `copy.test-only-policy` | a test-only `copy()` on a production type, in a plain test-only extension (`.copy-method`) or beside a production `Copy` that derives its own (`.beside-synthesized`); the policy conformance itself is `conformance.policy-placement`'s (SL:testing, Air t15; SL-630) |
| `copy.outside-policy` | a member named `copy` that a call with no arguments reaches, written outside the `Copy` or `ExplicitCopy` conformance of a type that does not declare `NoCopy`: in a plain extension, another conformance's, beside a derived policy, on a type Copy by its members, static or with every parameter defaulted (spec, The Copy Trait Family; SL-641) |
| `overload.indistinguishable` | a declaration that shares a call shape with an earlier one of its overload set, at the later one; the matrix below the table lists each position (spec, Overloading; SL-641) |
| `copy.second-policy` | a second copy policy on one type, at its conformance: `Copy` then `ExplicitCopy` (bare), `Copy` then `NoCopy` (`.no-copy`), `NoCopy` then `ExplicitCopy` (`.explicit-no-copy`), two in one extension's head (`.one-extension`), and bounded extensions, `Copy` beside `NoCopy` (`.bounded`) and `Copy` beside `ExplicitCopy` (`.bounded-both`); a test-only policy on a production type is `conformance.policy-placement`'s and counts for neither (spec, The Copy Trait Family; SL-641) |
| `extension.default-omitted` | an extension head renaming its type's parameters that leaves out a defaulted one, with the head written out (D14) |
| `extension.partial-specialization` | an extension head naming a type for some of its parameters and renaming others, a generic specialized extension, which the spec leaves planned (SL-740) |
| `extension.specialized-conformance` | a conformance declared in a specialized extension, for one instantiation, which the spec leaves planned; it counts for nothing (bare), an `UnsafeSend` assertion included (`.assertion`) (SL-740) |
| `type.mismatch` | a value that does not convert to what its position expects, one fixture per funnel position and one per cell of the wrap and erasure matrix a position refuses; a condition that is not a `Bool`; a pattern that does not fit its value; operands that disagree; a bare integer literal, or a constant expression's literal or leaf, that does not fit the type it adopts, a case of an enum declared later included (`.constant-declared-later`); a literal or range pattern's integer that does not fit the matched type (`.pattern-literal-range`, `.pattern-negative-unsigned`, `.pattern-range-end`); a literal past its signed suffix's range (D6) |
| `constant.overflow`, `constant.shift-range`, `constant.divide-by-zero` | a constant expression whose typed arithmetic overflows, shifts by a count outside its width, or divides by zero, where it adopts an integer slot and at every constant position (the constant-position funnel); a shift count or divisor constant before instantiation that faults whatever the other operand is, reachable or not (the certain-fault funnel); either one folding through a static or a case declared after it (`.declared-later`, the pending-constant funnel) |
| `constant.cast-range` | a cast whose operand is constant before instantiation and whose value its integer target cannot hold, at its `as`, in any position and at every constant position, reachable or not (the constant-cast funnel) |
| `type.ambiguous-result` | a value both of a Result slot's payloads could take |
| `type.not-a-value` | a type, module or trait named where a value is read |
| `type.not-a-place` | a value where a place is needed: an assignment's target, `move`, `&var` |
| `type.cast` | an `as` between types it does not convert |
| `type.try` | a `try` propagating out of a body that returns no Result, or into one whose error type does not take its error |
| `member.unknown` | a field or method the type does not have, or this module does not see; a specialized extension's member on another instantiation or in a generic body (SL-740); the builtin `copy()` on a NoCopy value |
| `member.through-pointer` | a method a `Box`'s or an `Arc`'s payload declares and the pointer does not, called on the pointer: a pointer forwards nothing, so the message names `borrow b.value().m(…)`, and for a `&var self` one `borrow var` on a box, or a lock or `unique()` on an `Arc`; every receiver mode, through a box (`&self` bare, `.var-self`, `.consumes`, a `borrows` accessor `.borrows`, a `&Box` parameter `.reference`, a `String` payload `.string`) and an `Arc` (`.arc`, `.arc-var-self`, `.arc-consumes`, `Mutex.lock` `.arc-borrows`) (SL-712) |
| `call.arity` | too many arguments, a missing one, a case built without its payload |
| `call.label` | a label no parameter has, one naming a parameter behind the last bound, a repeated label |
| `call.ambiguous` | overloads the arguments fit equally, named; a bare integer literal over integer overloads with no `Int` one, or preferring `Int` in a different overload at each argument (spec, Overloading, tie-break 4: `.literal-no-int`, `.literal-crossed`) |
| `call.no-match` | no overload the arguments fit, each named; a struct's construction that an override this module does not see takes (`.hidden-override`, SL-648) |
| `call.not-callable` | a call of a value that is no function |
| `call.field-method-ambiguous` | `h.f(x)` where `f` names both a field holding a function and a method this module sees, with the fix-it `let g = h.f; g(x)` (D16) |
| `infer.failed` | a type argument nothing determines or two arguments disagree on; `None` or an empty literal with nothing expected, though not one whose slot holds a type already refused, which adopts the error type |
| `implicit-member.no-type` | an implicit member where nothing expects a type, with the `Enum.Case` fix-it |
| `mutability.immutable` | a write or an exclusive borrow of a place nothing makes writable: rooted in a `let`, a pattern's, a `for` loop's or a closure parameter's binding, a parameter taken by value, a plain `static`, `self` under `&self`, a binding a closure captured by value (in every closure, SL-472) or by shared borrow, or reached through a shared reference or a read-only lend (the mutability matrix) |
| `type.reference-position` | a reference where a type is stored, returned or bound: every written position but a parameter, a function type's parameter, a `borrows` lend and a borrowing struct's shared field, at any depth; a bare `&` outside a call argument or a pointer cast; a binding inferred to name one; a call instantiated at one (the reference-position matrix) |
| `transfer.partial-move` | a spelled `move` of a part of a binding: a field, a tuple element, an element, an optional field's payload, at any depth (the field move-out matrix) |
| `transfer.move-from-borrow` | a spelled `move` of a binding that owns nothing: a reference, a closure's reference parameter, a `borrow` binding, a `[&x]` or `[&var x]` capture, a pattern's binding aliasing a part of a borrowed scrutinee, which a name reading through a borrow is as a scrutinee (spec, Reference Semantics; DF-288a) |
| `transfer.implicit-copy` | an ExplicitCopy or NoCopy place read by value with no `move`, payload reads included (design 131), and a projection's (`T.Item` in a generic body, a trait's own `Item` in its default bodies); a closure's capture of one by value with nothing written, with the fix-it `[move x]`; a repeat literal's element, whatever the value is, a temporary or a `move` included, refused once, as the repeat (SL-612); a plain subscript of such an element read where its position keeps nothing, a getitem all the same, with the fix-it `borrow` (D29). A place read's hint offers only what compiles for its shape, `move` on a binding that owns its value or on its optional's payload, `take()` on an optional place a write through lands in (a `var`, a `&var` parameter, `&var self`), and through an owned root that is never written a move of the root into a `var` first, `.copy()` where the type meets `ExplicitCopy`, and names the tier only where the type establishes one (SL-500; golden `implicit_copy_hints`, and golden `implicit_copy_fixes` with each fix applied) |
| `transfer.no-move` | a `move` of a `NoMove` value, or of one holding it inline (an Optional, a tuple, an array, a generic instance), at every position: a binding, an argument, a consuming receiver, a `[move x]` capture, `take()` out of an optional; a by-value parameter placed by `ptr[i] = move p` before any `&`, `&var` or `borrow` named it is the value reaching its home, and allowed (design 188) |
| `deinit.manual-call` | a `deinit` called by hand, written or synthesized, through a bound or named as a static (spec, The Deinit trait) |
| `copy.declared-bound` | a body's inferred Copy requirement on one of its own type parameters that its signature does not cover, or on its type's that its extension does not: a public generic that does not declare it, or a declared `ExplicitCopy` the body exceeds (design 219, SL-501) |
| `capture.copy` | `[copy x]` of a NoCopy binding, which has no copy; `[copy x]` of a value whose type names a type parameter no bound lets the body copy: `Copy` for every one, or `ExplicitCopy` on a bare parameter (D30); `[copy r]` of a `&var` reference, a second writer of its referent (SL-607) |
| `capture.escaping-consume` | a consuming use of a by-value capture in a closure that escapes, at every copy tier: a `move` of it, a `match` consuming it, an inner closure's `[move x]` of it; a spawn form's brace is exempt (SL-469; the escaping-consume matrix) |
| `capture.escaping-borrow` | a borrow of the enclosing frame, `[&x]`, `[&var x]`, a reference parameter or `self`, captured by a closure that escapes: anything but one passed straight to a parameter whose function type does not say `escaping` (spec, Capturing `self` and reference parameters) |
| `capture.exclusive-self` | `[&var self]` in a method whose receiver is `&self` |
| `subscript.role` | a subscript of a type that declares no `[]`, or a role it declares and derives no accessor for (SL:borrowing §5.2) |
| `pattern.case-mismatch` | a lone name resolve took for a case none of whose candidates is a case of the matched type, naming the case and suggesting the rename (D13) |
| `format.slot-count` | a format string whose `{}` slots and arguments differ in number, or a formatted message that is no literal |
| `format.argument` | a format argument or interpolated segment that is neither Printable nor a primitive |
| `format.mixed` | a format string that interpolates a value beside its `{}` slots or arguments (spec, "Format arguments and the allocation-free path"), judged where the string-position funnel records it as `format` |
| `atomic.width` | an `Atomic<X>` at an `X` other than `Int`, written or inferred, once per type, where a position first carries it: v1 atomics are `Atomic<Int>` only (SL:open-questions D38); one only an instantiation forms is mono's |
| `export.c-abi` | an `@export`ed function whose parameter or result C cannot pass: anything but a fixed-width integer, `Int`/`UInt`, `Float`, a pointer or a `FuncPointer`, and `Void` or `Never` as a result, so never an optional; an exported static whose type has no fixed C data layout (designs 58 and 113b) |
| `export.generic` | an `@export`ed generic function, whose one C symbol cannot name a body per instantiation |
| `export.duplicate` | a second declaration exported under a C symbol the program already exports, at the second |
| `export.reserved` | an export named `main`, `saw_*` or `__saw_*`; in a runtime (`--runtime`, `sawc2 runtime`) the frozen seams the runtime owns are the exception, and a seam the program owns, an argument accessor, is still refused (runtime/ABI.md, "Program arguments") |
| `export.unknown-seam` | in a runtime, a `__saw_rt_*` export the ABI table (`typecheck/src/runtimeabi.saw`, from runtime/ABI.md) does not list |
| `export.seam-signature` | in a runtime, a seam whose arity or a parameter's or the result's width class differs from the ABI table's, pointers and words sharing the class `word` (design 149) |
| `export.suspends` | an `@export`ed function that may suspend, read from its summary: C calls it with no executor to resume it |
| `operator.undefined` | an operator over a type it is not defined for, the integer-only ones over a `Float` or a `Bool` among them (the integer-only operator matrix below); a raw pointer takes only `p + n` and `p - n`, an integer offset after it, which steps `n` elements; a `try`, an inline catch's included, over a value that is no Result, and an optional assignment's `?.` hop over one that is no Optional |
| `static.immortal` | a static or `unsafe static var` whose type owns something a drop would release, at any depth: a `String`, a closure, or a type writing its own `deinit` (`Vector`, `Box` and `Arc` among them), naming it (spec, Module-level statics: "Immortal"; the immortal matrix below) |
| `static.optional` | a static whose own type is an optional; an `unsafe static var` is exempt (spec, Module-level statics: "Never optional") |
| `static.not-sync` | a static whose type is not `Sync`, naming the member that blocks the derivation, down to a cell-carrying type and the `UnsafeSync` declaration it owes, or a conditional `UnsafeSync` and the bound its argument fails; an `unsafe static var` is exempt (spec, Module-level statics: "Sync-only"; the static Sync matrix) |
| `static.not-constant` | a sub-expression outside the constant grammar of a static's initializer, a raw case's value, an `@align` argument or a `static_assert` condition, named (the constant-position funnel) |
| `static.zero-init` | a static or `unsafe static var` with no initializer whose all-zero value holds, at any depth, a struct whose construction an `init` overrides, naming the override (SL-648; the override matrix and the zero-init matrix below) |
| `static.zero-hidden` | a static or `unsafe static var` with no initializer whose all-zero value holds, at any depth, a struct with a field the declaring module does not see and no `ZeroInit` conformance vouching for it, naming the field (SL-660; the zero-init matrix below) |
| `static.zero-invalid` | a static or `unsafe static var` with no initializer whose all-zero value holds, at any depth, a part with no valid zero: a `String`, an enum with a payload, a raw-backed enum with no case of value 0, a function, a `FuncPointer`, `Never`, naming it (SL-660; the zero-init matrix below) |
| `static.cycle` | a static whose value depends on itself, through any number of statics, named in order |
| `static_assert.failed` | a `static_assert` whose condition folds to `false`, at the top of a file or in a body, a static it names declared later or in a module checked later included (`.declared-later`, `.declared-later-module`); one over a layout once the layout-assert funnel measures it (Layout asserts) |
| `borrowing.containment` | a borrowing struct (spec, Borrowing structs) bound outside the head of a `borrow` or a `for`, taken as a parameter by value, stored in a field or a payload, erased to an existential, returned by a function that does not lend it with `borrows`, or carried by a function type; a `borrows` call lending one anywhere but such a head; a construction of one outside a returning path of the `borrows` function that lends it |
| `lends.origin` | a `lends` whose operand is not `self`: a projection of the receiver, a parameter, a local, named in the message (spec, Borrowing structs, "The origin is the receiver") |
| `lends.position` | a `lends` anywhere but a reference field's value in a construction a `borrows` function returns |
| `lends.path` | a returning path of a `borrows -> S` function that ends in anything but a construction of `S` with `lends self` in every reference field, at the path's value |
| `escaping.stored` | a non-escaping function value (a parameter whose function type does not say `escaping`, or a local bound to one) in a position that holds it past the call: a field, a payload, an element, an Optional, a return, an assignment's target, an escaping closure's capture, a type argument, an `escaping` parameter (D35) |
| `borrowing.sigil-place` | `&` or `&var` on a place reached through a `borrows` call, a subscript accessor or a named one, at any depth of fields, tuple elements and payloads: the place is passed with `borrow` (SL:borrowing §9) |
| `borrowing.var-unwrap` | an `if var`, `guard var` or `while var` binding of the payload of an optional place a `borrow` binding names, or of an optional field of one: it would write a copy, never the place (SL:borrowing §2.4) |
| `borrowing.lend-chain` | an optional assignment whose head is a conditional lend, with a `?.` hop past the lend's own `?`, at that hop (spec, Optionals: "One fence") |
| `borrows.result` | a `borrows` function whose result is no place, slice, optional of either or borrowing struct (the accessor-signature reader's `other`) |
| `borrows.sync-window` | a call that may suspend, for some type argument, in the block of a `borrow` or a `for` whose head calls a `borrows(sync)` accessor (SL:borrowing §2.5) |
| `consumes.move` | a bare call of a `consumes` method on a place, at every Copy tier: the call spells `(move x).m()`, and a temporary receiver needs no `move` (spec, `consumes`) |
| `consumes.move-self` | `move self` or `move` of a part of `self` outside a `consumes` method (SL-414) |
| `match.non-exhaustive` | a `match` some value of its scrutinee's type reaches no unguarded arm of, each missing value named as a pattern: enums (`Optional` and `Result` included), `Bool`, tuples, split by their constructors at any depth; any other type, matched by literals and ranges, covered only by a wildcard or a binding |
| `match.duplicate` | an unguarded arm whose pattern repeats an earlier unguarded arm's exactly, holes alike whatever they are named and literals compared by value, at the second arm, naming the first's line; a guarded arm and a pattern holding a range are never duplicates (spec, Control Flow; the duplicate-arm matrix) |
| `result.discarded` | a `Result` computed where nothing reads it (design 151): a statement, a `Void` body's or a loop body's tail, an arm of a statement-position `if` or `match`, refused at the expression that produced it; `let _ =` is the out |
| `effect.sync` | a call in a `sync` body (a function declared `sync`, a `deinit`, a closure of a `sync` type) of a target that is not sync-callable: one that may suspend, a function value whose type is not `sync`; a call whose type arguments make a requirement a generic `sync` body calls through a bound not sync-callable; a `sync` requirement met by a member that is not sync-callable; a hand-written `copy()` of a copy-policy conformance that may suspend, refused at the conformance |
| `copy.requirement` | a call whose type argument is not on the Copy tier where its callee's body copies that parameter with nothing written (design 219), named with the copy's position, or, for a local one path uses twice, both uses; a repeat literal of the parameter's value is such a copy, however often the value is read (SL-612) |
| `effect.closure-suspends` | a call in a closure body that may suspend, or a call whose type arguments make a closure in its callee call a suspending implementation (spec: suspension, "a closure body cannot suspend") |
| `erasure.primitive` | a primitive, `String` among them, erased to `&any Trait`, `&var any Trait` or a box, at every erasure (`refuse_primitive_erasure`): an existential carries a vtable beside the value, and a primitive has no boxed form to carry one, naming the bound and the wrapper struct as the outs (bare; `.box-string`, `Box<any Trait>.make`) |
| `erasure.not-object-safe` | a written `any Trait` whose trait is not object-safe: a marker trait, one with an associated type, a static requirement, or a requirement naming `Self` in its result or a parameter, its parents' included, naming the trait, the reason and the member (spec, "Object safety (v1)"; the object-safety matrix) |
| `effect.any-suspends` | a coercion to `any Trait`, or a call whose type arguments make one in its callee, where the implementation of a requirement not declared `sync` may suspend, naming both (spec: suspension) |
| `drive.argument` | a test driver (`__saw_drive`, `__saw_drive_steps`) given anything but one positional argument (bare), or a root that is no call of a function or a method: a function value, a closure (`.value-root`) |
| `spawn.argument` | a `Task.spawn` or `group.spawn` (`.group`) given anything but one positional argument, or a root that is no call of a free function: a method, a closure, a value (`.method-root`); a `Thread.spawn` given anything but one brace (`.thread`), or a brace that declares parameters (`.thread-parameter`) |
| `spawn.implicit-capture` | a `Thread.spawn` brace naming an enclosing binding its capture list does not: the list is the body's parameter list (design 242; conformance row K91) |
| `spawn.send` | a `Thread.spawn` capture whose type is not `Send`, a generic body's declared bounds answering for its parameters (`.generic`, conformance row K74); a body whose value is not `Send`, which `join()` hands back across the threads (`.result`) |
| `effect.thread-body` | a call in a `Thread.spawn` body that may suspend by any cause but a `blocking` extern, named by its path to the first source it strikes on: a park point (conformance row K83), the test intrinsic (`.test-suspend`, K114), a call through a function value not declared `sync` (`.closure-call`, K114), a std function's table row (golden `thread_body_std_table`, K112) |
| `spawn.borrow` | a borrow a `Task.spawn` root takes of its spawner, at both spellings: a `&` or `&var` argument of the root call, and a borrow capture written in a closure anywhere inside it (`.capture`); a reference a call nested in the arguments makes ends at the spawn and is none (golden `task_spawn`; spec, "BORROWS ARE REFUSED AT THE FORM") |
| `spawn.never-body` | a task root of type `Never`, whose handle's `join` could never return, or which a test driver would drive for ever (design 228; conformance row D12); the funnel `refuse_never_task_body` names its entry points, the `Task.spawn` form, `group.spawn` (`.group`), the two test drivers (`.drive`, `.drive-steps`) and the `Thread.spawn` brace (`.thread`, conformance row D11) |
| `slice.not-yet` | a signature or body construct outside the bootstrap slice |

The traits that derive under `@synthesize` are `Copy`, `ExplicitCopy`,
`Equatable`, `Comparable`, `Hashable`, `Serialize` and `Deserialize`. An
extern has no effect slot, so the unsafe rule asks nothing of it.

The redeclaration matrix (SL-641). Every overload set reaches one funnel,
`refuse_indistinguishable` (`compiler/typecheck/src/overloads.saw`), whose
docstring names its entry points; `o.` abbreviates
`refuse/overload.indistinguishable.`:

| row | verdict | covered by |
|---|---|---|
| a free function declared twice, the same after an alias, or sharing a shape through a defaulted parameter, one or both | refused | `o` (bare), `o.alias`, `o.default-shape`, `o.default-shapes` |
| generic functions differing in a type parameter's name, bare or inside another type, and two type parameters against one | refused | `o.generic`, `o.generic-nested`, `o.generic-folded` |
| functions differing only in result or in `unsafe` | refused | `o.result`, `o.effects` |
| a test-only twin of a production function, and two test-only functions | refused | `o.test-only`, `o.test-only-twins` |
| a method in two extensions or twice in one; through a defaulted parameter; by receiver alone; a static twice; a static beside an instance method | refused | `o.method`, `o.method-one-extension`, `o.method-default-shape`, `o.receiver`, `o.static`, `o.static-instance` |
| an `init` in two extensions, through a defaulted parameter, and with its labels reordered, since an `init` binds by name | refused | `o.init`, `o.init-default-shape`, `o.init-reordered` |
| a generic method, a bounded extension's method beside an unbounded one's, and two extensions naming the type's parameter differently | refused | `o.generic-method`, `o.bounded-extension`, `o.extension-parameter` |
| a test-only twin of a production method; an enum's method in two extensions | refused | `o.test-only-method`, `o.enum` |
| a trait's requirement twice, and a requirement beside a default body | refused | `o.requirement`, `o.requirement-default` |
| two `deinit`s, two hooks in one copy policy | refused | `o.deinit`, `o.copy` |
| two `borrows` accessors of one receiver | refused | `o.borrows` |
| a `borrows` accessor's shared and exclusive twins, which `borrow let` and `borrow var` choose between (SL:borrowing §4) | allowed | `overload_shapes` |
| a `deinit` or a `copy()` written outside the policy, beside the policy's own | refused by the placement rule alone | `deinit.outside-policy.beside-policy-deinit`, `copy.outside-policy.declared` |
| other labels, another arity, a concrete function beside a generic one, a method's other labels across extensions, a generic method beside a concrete one, `init`s of other labels or types, an `init` beside a static | allowed | `overload_shapes` |
| two modules' functions of one shape | allowed: a set is one module's, and a call that sees both refuses the ambiguity | multi/overload_modules; std's `json.encode` and `cbor.encode` |
| an `init` sharing a call shape with a struct's memberwise construction without matching its fields exactly: through a defaulted parameter, or with type parameters swapped; and two overrides of one construction | refused, in a module that sees every field | `o.memberwise-default-shape`, `o.memberwise-generic`, `o.override-twice` |

The override matrix (SL-648). An `init` whose labels, in any order, and types
are a struct's fields exactly overrides its memberwise construction. Which
construction a call reaches is decided by one funnel,
`construction_route` (`compiler/typecheck/src/bodies.saw`), whose
docstring names its entry points, a call's candidates and a zero-initialized
static's value; whether an `init` overrides at all, by
`matches_fields` and `override_fault` (`candidates.saw`), which the
declaration-site check (`check_construction_inits`, `overloads.saw`) and the
funnel share. `golden/construction_override` is abbreviated `g.`:

| row | verdict | covered by |
|---|---|---|
| a plain call, a labeled call in another order, a positional call, `Self(...)` in a method, a static's body | the override | `g.` |
| another `init` of the type, so a fallible override's `Result` reaches it | the override | `g.`; run `probes/construction_override.saw` |
| a parameter's default value, an alias of the struct, a test case | the override | `g.` |
| a generic construction, inferred, with written arguments, and in a generic body | the override | `g.`; run `probes/construction_override.saw` |
| the override's own block, a closure in it and `Self(...)` included | the raw construction | `g.`; run `probes/construction_override.saw` |
| another module, the override `public` | the override | multi/construction_override_modules; run `probes/construction_override.saw` |
| another module, the override module-private, the fields public | refused at the call; a field read and write there accepted | `call.no-match.hidden-override`; multi/construction_override_modules |
| a static's initializer | refused: the override is a call | `static.not-constant.override` |
| an `init` of a subset of the fields, or of other types | an ordinary overload; the construction is unchanged | `g.` |
| an override declared outside the struct's module | refused at the declaration | `init.override-outside-module` |
| a test-only override of a production struct; a test-only struct's own | refused; the control accepted | `init.override-test-only`; `g.` |
| an override in a bounded extension; in an unbounded generic one | refused; the control accepted | `init.override-bounded`; `g.` |
| an override in a specialized extension, the head's instantiation's fields read as its body sees them (SL-740) | refused | `init.override-specialized` |
| a derived `copy()` | unchanged: it copies field by field and calls no constructor | mono's glue |
| a synthesized `Deserialize` | lands with the serde port, which sawc2's std does not have yet | none |
| a zero-initialized `static` or `unsafe static var` of a struct with an override, in its module or another, or holding one at any depth (a field, an array element) | refused: zero is a construction the override never checks | `static.zero-init`, `static.zero-init.override-module`, `static.zero-init.nested` |
| a zero-initialized `static` of a struct without one, and of one whose overridden part is an Optional, zero being `None` | accepted | `g.` |
| a zero-initialized `static` of a struct with a field the declaring module does not see, at any depth | refused unless a `ZeroInit` conformance vouches for it (SL-660) | the zero-init matrix below |

The zero-init matrix (SL-660). A static or `unsafe static var` with no
initializer is zero-initialized, and that value is a construction. It is
legal when every part of it is valid at zero: a part the declaring module
could build field by field (every field visible, no override, every field
valid), or a type declaring `ZeroInit`. One funnel answers it, `zero_fault`
(`compiler/typecheck/src/bodies.saw`), whose docstring names its two entry
points, a bare static and a `ZeroInit` declaration; both run in
`check_zero_inits`, once every body is typed, so a raw-backed case's value is
folded wherever its enum sits. `ZeroInit` is a lang item of the new std's
prelude and unbound under Stage 0's, so a row that declares it runs with
`--std-root std`. `golden/zero_init` is abbreviated `z.` and
`multi/zero_init_modules` `zm.`:

| row | verdict | covered by |
|---|---|---|
| a scalar, `Bool`, `Float`, a raw pointer, a tuple, an array, `Atomic<Int>` | accepted | `z.` |
| a payload-free enum, zero being its first case; a raw-backed enum with a case of value 0, written in any position | accepted | `z.` |
| an Optional, of a type with no valid zero or with hidden fields: zero is `None` (one owning a resource is the immortal rule's, below) | accepted | `z.`, `zm.` |
| a struct of this module with private fields, at the top, in a field, behind a generic argument | accepted: the module sees them | `z.` |
| a struct declaring `ZeroInit` in its own module, its fields private, from another module | accepted | `zm.` |
| a `ZeroInit` struct holding another struct of its module whose fields are private | accepted: the declaring module sees them | `zm.` |
| a conditional `ZeroInit` (`Lock<T: ZeroInit>`) at a scalar, at a `ZeroInit` type, and at a struct of the static's module with no declaration | accepted: the condition's argument is walked by the same rule, at the static's module | `zm.` |
| another module's struct with a private field: at the top, in a field, in an array, behind a generic argument | refused, naming the field | `static.zero-hidden`, `.nested`, `.array`, `.generic` |
| a conditional `ZeroInit` at an argument with a hidden field | refused, naming the argument's field | `static.zero-hidden.conditional` |
| Stage 0's `SpinLock`, `Mutex` or `Once` under Stage 0's root, whose std cannot declare `ZeroInit` | refused, naming the private field | `static.zero-hidden.frozen-std` |
| a `String`, directly or as a conditional `ZeroInit`'s argument | refused: a `String` owns its bytes | `static.zero-invalid`, `static.zero-invalid.conditional` |
| an enum with a payload case | refused | `static.zero-invalid.payload-enum` |
| a raw-backed enum with no case of value 0 | refused: zero is a value no case names | `static.zero-invalid.raw-enum` |
| a function value; a `FuncPointer` (Stage 0's root, the std that declares it) | refused: a zero one names no function | `static.zero-invalid.function`, `static.zero-invalid.func-pointer` |
| a struct with an override, at any depth | refused, naming the override | the override matrix above |
| a reference | refused where it is written, never a second time | `type.reference-position.static` |
| `ZeroInit` on a struct with an override | refused at the declaration | `zeroinit.override` |
| `ZeroInit` on a struct with a field of no valid zero; with a field of its unbounded type parameter; with a field of another module's type it cannot see; on a raw-backed enum with no case of value 0 | refused at the declaration, naming the field | `zeroinit.invalid`, `.param`, `.hidden`, `.enum` |
| `ZeroInit` on another module's type | refused by resolve's orphan rule: only the type's module, or the prelude, may declare it | `conformance.orphan` (resolve) |

The requires matrix (SL-755). `Comparable` and `Hashable` each require
`Equatable` of their type, and a conformance never grants it: the prelude
lists no parent for either, since a parent would give the type `Equatable`
through the conformance. One funnel, `check_required_conformances`
(`compiler/typecheck/src/checks.saw`), reads the conformance table, and
`required_trait` (`conform.saw`) holds the pairs. Since every conformance
meets what its trait requires, a bound carries it, as a bound carries a
`Send` parent: `carried_traits` (`conform.saw`) answers what a bound or a
trait's `Self` gives, for `satisfies` and for the requirements a call
through the bound finds. No other trait in the vocabulary requires a
trait it does not refine but `Send` and `Sync`, which `conformance.derived-parent`
covers. `golden/required_conformances` is abbreviated `rc.`:

| row | verdict | covered by |
|---|---|---|
| `@synthesize`d `Comparable`, `Hashable`, on a type that is not `Equatable` | refused | `conformance.requires` (bare), `.hashable` |
| a written `compare`, a written `hash`, on such a type | refused | `.written`, `.hashable-written` |
| an enum with payloads, which is not automatically `Equatable` | refused | `.enum` |
| a conformance to a user trait refining `Comparable` | refused, naming the refinement | `.refinement` |
| an unconditioned generic `Comparable` beside an `Equatable` that holds only where `T: Equatable` | refused | `.generic` |
| a production `Comparable` whose `Equatable` is test-only | refused, as production code sees it | `.test-only` |
| beside a declared `Equatable`, `@synthesize`d or written | accepted | `rc.` |
| a trivial struct or a payload-free enum, automatically `Equatable` | accepted | `rc.` |
| an automatic `Hashable` | met by construction: the trivial types it reaches are automatically `Equatable`, and no conformance is written to check | none |
| a conditional head whose bounds meet the condition, `T: Comparable + Equatable`, or `T: Comparable` alone, which carries `Equatable` | accepted | `rc.` |
| `==`, `!=` and `.equals` in a generic body under `T: Comparable` or `T: Hashable`; a `T: Comparable` forwarded to a `T: Equatable` bound; `==` on `Self` in the default body of a trait refining `Comparable` | accepted: the bound carries `Equatable` (`carried_traits`, `conform.saw`) | `rc.` |
| a refining trait's conformance beside `Equatable`; a test-only `Comparable` beside a test-only `Equatable` | accepted | `rc.` |
| a primitive or `String` | builtin: each is `Equatable` | none |

The integer-only operator matrix (SL-756). The wrapping operators `&+ &- &*`
take integer operands only (spec, Integer Arithmetic), as the shifts, the
bit operators and `~` do (spec, Bitwise and Shift Operators), and `%` with
them; a `Bool` takes the logical `&&`, `||` and `not`, never a bit operator.
A binary chain is classified by `operator_kinds`, which `arithmetic_expr`
reads, and a compound one by `check_compound_operands`; each refuses at the
operator, under `operator.undefined`. Over `Float`, and over `Bool` where the
row says:

| operator | verdict | covered by |
|---|---|---|
| `&+`, `&-`, `&*`, over values, over literals, beside `+` in one chain | refused, as a wrapping operator | `operator.undefined.wrapping-add`, `-subtract`, `-multiply`, `-literal`, `-chain` |
| `&+` over `Bool` | refused, as a wrapping operator | `operator.undefined.wrapping-bool` |
| `%`, `<<`, `>>` | refused, as a shift or remainder operator | no fixture of its own |
| `&`, `\|`, `^`, `~` | refused | the corpus's `bitwise_requires_integers` holds `&`; no fixture of its own |
| `&`, `\|`, `^` over `Bool`, over values and over literals | refused | `operator.undefined.bit-bool`, `-bool-or`, `-bool-xor`, `-bool-literal` |
| `\|=`, `&=`, `^=` over `Bool` | refused | `operator.undefined.compound-bit-bool` |
| `%=` | refused, as `%` is | `operator.undefined.compound-remainder` |
| `&=`, `\|=`, `^=`, `<<=`, `>>=` | refused | no fixture of its own |
| `+`, `-`, `*`, `/`, unary `-`, and `+=`, `-=`, `*=`, `/=` | accepted: IEEE arithmetic | no fixture of its own |

The immortal matrix (spec, Module-level statics: "Immortal"; SL-722). A
static is never destroyed, so its type owns nothing a drop would release.
`check_static_type` (`compiler/typecheck/src/bodychecks.saw`) is the funnel
for every rule on a static's declared type, and its docstring names its entry
point; `static_owner` walks the type, substituting a generic instance's
arguments into its fields and payloads, and holding a builtin type's
arguments inline. Unlike `static.not-sync` and `static.optional`, the rule
covers an `unsafe static var` too. `golden/static_immortal` is abbreviated
`i.`:

| row | verdict | covered by |
|---|---|---|
| a type writing its own `deinit`: the static's type, a field's, an array element's, a generic instance's argument | refused, naming the type | `static.immortal`, `.nested`, `.array`, `.generic` |
| the same, as an `unsafe static var` | refused | `static.immortal.var` |
| a member owning a resource: a `String`, a `Vector`, a `Box`, an `Arc`, each in an optional field so that its zero is valid | refused, naming it | `static.immortal.string`, `.vector`, `.box`, `.arc` |
| a group handle, `Task<Int>?` (its type writes its own `deinit`), which closes K164's static cell before borrowck's `loan.handle-escape` | refused, naming `Task<Int>` | `static.immortal.task-handle` |
| `Once<String>`, and `Once<Cfg>` with a `String` field | refused, after `static.zero-invalid` | `i.` |
| `Once<Int>`, `SpinLock<Int>`, `Mutex<Int>`, a struct of scalars declaring `NoCopy`, a struct holding an `Atomic` | accepted | `i.` |
| a static whose own type is an optional | `static.optional`, which already refused it | `static.optional` |

## The lane

`typecheck_lane.py` runs one `sawc2 typecheck` process per group and checks:

- each golden program's record equals its `.typecheck` file byte for byte;
  `--write` rewrites them after a deliberate change, for review. A first line
  `// flags: ...` passes those flags, and the programs sharing a line run as
  one group; under `--std-root` the expectation leaves out each `std.`
  module's dump, keeping the program's modules and every line outside a
  module, so a refusal in std still shows;
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
naming a type parameter its body does not see (its declaration's own, or the
type its extension extends): a recursive call names its own parameters, and a
parameter of the callee's signature in its caller's call can only have leaked
there (golden `generic_recursion`; the unit program
`compiler/typecheck/tests/verify_instantiations.saw` edits
`inject/instantiations.saw`'s calls to name an unseen parameter and requires
the report), that each call the overload filter resolved records a total
argument binding (every written argument binds exactly one parameter or falls
in the variadic tail, and every parameter no argument binds has a default),
that each closure records a capture, with a capture's transfer, of every
enclosing binding its body names, and that each adjustment chain composes,
every step's source the step before's result.

The summary verifier (`summaries.saw`) checks that every function has its
three summaries, that each checked body's summary is a fixpoint (one more step
over its items changes nothing), and so is each checked default value's,
a bodyless requirement's included, that every condition is over the function's
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

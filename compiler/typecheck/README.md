# compiler/typecheck: type checking

The typecheck stage of the self-hosted compiler, package `sawtypecheck` (epic
SL-398, unit 6b, SL-447). It reads resolve's program unchanged, arenas and
side tables, and produces side tables keyed by resolve's ids (SL:architecture
§3.0, §3.4). This unit, U6b1, builds the signature half: every declaration's
signature program-wide, trait requirements, the conformance table, the member
tables and the Copy tiers, and the checks that need only those. Bodies come
in U6b2, and the effect fixpoints in U6b3. `compiler/tests/typecheck/README.md`
specifies the dump, the interner's key and the position matrix.

```
typecheck/
  src/
    api.saw           typecheck_program and the record `sawc2 typecheck` prints
    program.saw       TcProgram: resolve's program and every table the phases fill
    model.saw         the records: signatures, generics, conformances, members, tiers
    types.saw         the type interner
    spell.saw         a type's canonical spelling
    signatures.saw    generic parameter lists and the type funnel, `build_type`
    declarations.saw  one signature builder per declaration kind; the
                      accessor-signature reader
    conform.saw       the conformance table: requirements, defaults, `@synthesize`,
                      agreement; substitution
    tier.saw          the Copy-tier classifier, containment, bound satisfaction
    members.saw       the member tables and a module's view of them
    checks.saw        finite size, and the signature half of `unsafe`
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
   finite size and the signature half of `unsafe`.

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

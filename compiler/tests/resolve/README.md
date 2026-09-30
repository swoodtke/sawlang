# compiler/tests/resolve: the resolver's corpus

The corpus the resolve stage (`compiler/resolve`, SL-445) is held to. This file
specifies `sawc2 resolve`'s records and dump, the position matrix the corpus
covers, and the rules resolve refuses by.

```
resolve/
  README.md          this specification
  resolve_lane.py    the lane compiler/tests/run.py runs
  golden/            NAME.saw, a program, and NAME.resolve, its expected record
  multi/             NAME/main.saw and its modules, and NAME.resolve
  refuse/            RULE[.VARIANT].saw, or RULE[.VARIANT]/main.saw and its modules
  prelude_check.py   the prelude and std tables against the frozen compiler's
  frozen_check.py    call heads and import bindings against the frozen compiler's
  FROZEN_CHECK.md    the record of the two checks above
  corpus_info.py     how much of tests/corpus/ resolves, for information
```

## `sawc2 resolve`

```sh
.build/sawc2 resolve (--dump | --check) [--notes] [--std-root DIR] [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved with every module
it imports. `--std-root` names the directory that holds `std/` and
`builtin.saw` (default `sawc`); `--module-path` maps a package to its
directory, as the frozen compiler's flag does. `@LIST` names a file of entry
paths, one per line. Each entry gets one record, starting with the line
`FILE<TAB>path`, holding in order:

- one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal, in the
  order resolution made them, in any module of the program;
- with `--notes`, one `NOTE` line, in the same shape, per note: what an
  interface module, std or builtin, could not provide, which refuses nothing;
- one `INVARIANT<TAB>module<TAB>message` line per problem the verifier finds;
- with `--dump`, the dump of each module resolved in full, in load order: the
  entry first, then the modules it imports that are not std's.

The exit code is 1 when any program has a refusal, 2 on a usage failure, and 0
otherwise.

## The dump

A module's dump is one S-expression, one entry per line, in this layout:

```
(Module IDENTITY
  (names
    (L:C SPELLING BINDING)...)
  (calls
    (L:C CLASS [BINDING])...)
  (declarations
    (KIND PATH L:C [VISIBILITY] [test-only] [static] [payload] [DETAIL])...)
  (surface
    (NAME BINDING)...)
  (imports
    (L:C MODULE [public] [test-only] FORM)...)
  (extensions MODULE...))
```

- **names** lists every name occurrence of the module (Name occurrences,
  below), by position, with the spelling written there and its binding.
- **calls** lists every call, by the position of its callee, with its class
  and, when resolve decides the callee, its binding (Call heads, below).
- **declarations** lists the module's declarations in source order: each
  top-level declaration, each enum case, field, trait member and extension
  member after its parent. PATH is the name, after its parent's for a member
  (`Point.x`, `Color.Red`, `Pair.swap`, the extended type's name for an
  extension member). A function, extern, method and init carry
  `(signature (PARAMS) -> RETURN)` with each type written by the identities its
  names resolved to: that is the stable path of one overload. An extension
  carries its type's binding and `(conforms TRAIT...)`.
- **surface** is what the module hands on to its importers (design 229): its
  own non-private declarations and what its `public import`s re-export, by name.
- **imports** lists each import: its module, and its form, `(qualifier NAME)`,
  `(glob)`, or `(select (NAME BINDING)...)` with each selected name as bound.
- **extensions** is the set of modules whose extension methods the module sees
  (designs 142 and 254): its own, its direct imports', and those their
  `public import`s reach, transitively. The receiver's defining module is
  typecheck's to add, per receiver.

L:C is a 1-based line and a column counting Unicode scalars, as the parser's
positions do.

### Bindings

| binding | what the name denotes |
|---|---|
| `(local NAME L:C)` | a local, a parameter, a pattern, loop or optional binding, a capture, a receiver (`self`), or a catch block's `error`, by where it is declared |
| `(type-param NAME L:C)` | a type or const generic parameter, by where it is declared |
| `(KIND MODULE PATH)` | a declaration: KIND is `struct`, `enum`, `trait`, `alias`, `static`, `type` (a builtin type), `assoc-type` or `type-assign` |
| `(overload MODULE NAME)` | a function name: the module's whole overload set of that name, externs and builtin functions included |
| `(overloads NAME MODULE...)` | a bare function name several modules supply: the module's own functions of that name and those its imports bind bare, merged into one overload set (design 249) |
| `(case MODULE ENUM.CASE)` | one enum case |
| `(cases NAME CANDIDATE...)` | a case selector: a variant pattern's head, a lone name pattern that names a case, or an implicit member; each candidate is a `MODULE.ENUM.CASE` identity of an enum in the module's import closure (its own module, `builtin`, the prelude's modules, and every module those import, transitively), and typecheck chooses one by the scrutinee's or the expected type. A lone name pattern names a case only when the closure declares a payload-free case of that name. A variant pattern's head no enum in the closure declares as a case is looked up as a type instead: an arm of a `try` block's error union names an error type |
| `(module MODULE)` | a module, through a qualifier or an import's path |
| `(self-type [IDENTITY])` | `Self`: the enclosing type, or a trait's own |
| `(error)` | refused; an `ERROR` line says why |

A call's binding may also be `(member [IDENTITY])`: a static method of a named
type, which typecheck finds among that type's members.

### Name occurrences

A name occurrence is what the verifier finds from the tree, by its own rule:

- the identifier of a Name expression;
- every segment of a path, in a type, a bound, a conformance, a trait's
  parents, an extension's head, an `any` type, a `try(as ...)` route and a
  constant; an import's path is one occurrence, at its last segment;
- `self`, whose SelfExpr node is the occurrence, since the tree keeps no leaf
  for the keyword, and a `[&self]` capture;
- a variant pattern's head, an implicit member, a capture's name, and the name
  a selective import asks for;
- a member's name when resolve decides it: a module's member, or an enum's case
  reached through the enum;
- a lone name pattern when it names a case rather than binding.

A declaration's own name, a binding's, a field or argument label, and a member
selected on a value are not occurrences.

### Call heads

| class | the callee |
|---|---|
| `init` | a type: `Foo(...)` builds through its `init` set |
| `overload` | a function name: an overload set |
| `local` | a local holding a function value |
| `type-param` | a type parameter |
| `case` | an enum case, `E.Case(...)` |
| `implicit-case` | an implicit member, `.Case(...)` |
| `method` | a member selected on a value, found from the receiver's type |
| `static-method` | a member of a named type that is not one of its cases |
| `value` | any other expression: a function value, decided from its type (SL-73) |

## The position matrix

Every position a name is resolved in, and the golden case that covers it. A
position outside the bootstrap slice is refused as `slice.not-yet`, naming its
GRAMMAR.md alternative; the last table lists them.

| position | resolved as | covered by |
|---|---|---|
| top-level function, struct, enum, trait, alias, static, extern | a declaration of the module | declarations |
| enum case, struct field, trait and extension member | a member of its parent | declarations |
| parameter and return types | a type | declarations, types |
| parameter default | an expression, before the parameters are bound | expressions |
| field, payload, static and alias types | a type | declarations, types |
| raw value, static initializer, array length, `@align` argument | an expression | declarations, types, expressions |
| generic parameter, its bounds and its default | a type parameter; traits; a type | types, declarations |
| const generic parameter, its type and default | a type parameter; a type; a constant | types |
| extension head, extension generics | the extended type, `Self` in its members; type parameters | declarations, lockdown |
| conformances, trait parents | traits | declarations, types |
| trait requirement, default body | a function, `Self` the trait | declarations, types |
| associated type, type assignment | a type-level binding in the trait or extension | declarations, expressions |
| named type with generic arguments | a type, each argument a type or a constant | types, lockdown |
| qualified type `m.T` | a module, then its member | multi/imports |
| reference, optional, tuple, array, slice, function and `any` types | their parts | types |
| `Self` | the enclosing type or trait | types |
| constant: literal, static, arithmetic, `sizeof`, `alignof` | its parts | types |
| name expression, with generic arguments | the lookup funnel | all |
| `self` | the enclosing method's receiver | declarations, calls |
| member of a module | its surface | multi/imports |
| member of an enum through its type | the case | calls, patterns, prelude |
| member of any other type, member or optional member of a value | a selector for typecheck | calls |
| implicit member | a case selector | calls |
| call head, its arguments | classified once | calls |
| operators, literals, interpolation, collection literals, casts, `move`, `*`, `&`, `try`, `!`, subscripts | their parts | expressions, lockdown |
| `try(as E.Case)` | the case, through its path | expressions |
| closure: captures, parameters, statements | the enclosing binding; locals of the closure | scopes |
| `let`, `var`, destructuring `let` | the initializer, then the binding, which may derive from one it shadows | scopes, expressions |
| assignment, compound and optional assignment | their parts | expressions, lockdown |
| `return`, `break`, `continue`, `lend`, `static_assert` | their parts | lockdown, expressions |
| `guard let`, `guard` condition | the subject, the else block, then the binding in the enclosing scope | scopes, expressions |
| `if`, `else if`, `if let`, `if borrow let` | each arm's head, its bindings in its block only | scopes, lockdown |
| `match`: pattern, guard, body | one scope per arm | scopes, patterns |
| `while`, `while let`, `while borrow`, `for`, `for borrow` | the head, the binding in the body only | scopes, lockdown |
| `borrow` block, place, unwrap | the place, then the bindings in the block | lockdown |
| `try` block, inline `catch` | `error` bound in the catch block | scopes |
| pattern: wildcard, literal, range, tuple, variant, name, `None`, borrow binding | bindings and case selectors | patterns, optionals, lockdown |
| a lone name pattern, by the enums of the module's import closure | a case when the closure declares one of that name, else a binding | multi/closure |
| test-only declaration, test group, test case | collected test-only; named from test code only | tests |
| prelude names | the prelude table | prelude |
| every import form, re-exports through a facade | Imports, below | multi/imports |

| outside the slice | refused as |
|---|---|
| a `$0` parameter | `slice.not-yet` (`syntax.expr.shorthand-param`) |
| a `module` declaration, in a file or inline | `slice.not-yet` |
| a `package` or `parent` import path | `slice.not-yet` |
| the `Thread.spawn` and `Task.spawn` forms | `slice.not-yet` |
| a frozen-compiler test intrinsic, a name that starts `__saw_` and nothing declares | `slice.not-yet` |
| an associated type named bare through a type parameter's bound, `-> Item` under `<T: Container>`, when nothing else binds the name | `slice.not-yet` |

The slice is sync-only (SL:architecture §4), so the concurrency forms and the
intrinsics that drive coroutines are outside it; nothing under a refused
construct is resolved, and the verifier asks nothing of it. How a bound's
associated type is spelled is an open language question, so that name is
refused as unbuilt rather than as undefined.

A refusal case's body is never resolved: a normal build matches only its
braces (SL:testing §5).

### Imports

A qualifier binds its module, `.*` every name on its surface the importer can
see, `.{A, B as C}` exactly those names; each form makes the module a direct
import. `public import` puts what it binds on the importer's surface: the
qualifier, the selected names, or the whole vocabulary.

## Refusals

Each rule's fixture is `refuse/RULE.saw`, or `refuse/RULE.VARIANT.saw` for one
of several positions; a refusal that needs more than one module is a directory
whose `main.saw` is the entry (SL:testing §5). A fixture's first line is

```
// refuses: RULE at L:C
```

and its first `ERROR` must carry that rule at that position; a position in
another module of the fixture is written `FILE.saw:L:C`. The second line says
what the fixture shows.

| rule | refuses |
|---|---|
| `name.undefined` | a name nothing binds, or a path segment its module does not have as a type |
| `name.duplicate-declaration` | two top-level declarations of one name that are not both functions, a function beside a type of its name included (a reading: types and values share one namespace, which the spec does not state); a case or field declared twice |
| `name.reserved` | a declaration named like a prelude name (design 255) |
| `name.shadowing` | a binding that shadows a local or a module static and does not derive from it: a `let`, `var`, loop or optional binding whose initializer does not mention it, a same-scope redefinition, and always a pattern binding, a parameter and a closure parameter (designs 100 and 107) |
| `name.duplicate-binding` | two parameters, or two generic parameters, of one name |
| `name.ambiguous` | a bare name two explicit imports bind to two declarations that are not both functions, refused at the use |
| `name.not-in-prelude` | a std name the prelude leaves out, with the import that supplies it (design 255) |
| `name.self-outside-method` | `self` with no receiver |
| `name.self-outside-type` | `Self` with no enclosing type |
| `name.unknown-case` | an implicit member no enum in the module's import closure declares as a case |
| `import.unknown-module` | an import of a module that does not exist |
| `import.unknown-symbol` | a name a module's surface does not have, asked for by a selective import or a qualified path |
| `import.not-reexported` | a name a module imports but does not hand on (design 229) |
| `visibility.private` | a name private, or of another package or parent, in its module (design 80), asked for by an import or a qualified path, or a bare name a glob import misses only for that reason |
| `import.duplicate-qualifier` | two whole-module imports binding one qualifier to two modules |
| `import.cycle` | modules that import each other, at the first participant's import |
| `import.prelude-name` | a selective import binding a prelude name to another declaration |
| `import.unavailable` | an import of a module that could not be read or parsed |
| `import.unreadable` | an entry file or std module that cannot be read |
| `resolve.parse-refused` | an imported module the parser refuses |
| `test.only-reference` | ordinary code naming a test-only declaration or a test-only import's name |
| `conformance.orphan` | a conformance in neither its type's module nor its trait's (design 142) |
| `conformance.duplicate` | a second conformance of one type to one trait (design 142) |
| `slice.not-yet` | a construct outside the bootstrap slice |

`resolve.prelude-table` is a note, never a refusal: the prelude table names a
declaration its module does not have. `prelude_check.py` covers the tables.

## The lane

`resolve_lane.py` runs one `sawc2 resolve` process per group and checks:

- each golden program's record equals its `.resolve` file byte for byte;
  `--write` rewrites them after a deliberate change, for review;
- each refusal fixture is refused first by its rule, at its position;
  `--fill` writes the header of a new fixture whose first line is
  `// refuses: TODO`, for review;
- every rule the resolver's source refuses by has a fixture, but the two its
  `WAIVED` table names, and a missing entry file is refused as
  `import.unreadable`;
- the compiler's own source resolves with no refusal: the sawc2 build, with
  the stage packages mapped, and each unit program; a unit program the parser
  refuses is counted apart;
- no record carries an `INVARIANT` line.

## The one-time checks

- `prelude_check.py` compares resolve's three tables, the synthetic builtin
  declarations, the std modules and the prelude, with the frozen compiler's
  view of today's std, and prints every difference.
- `frozen_check.py` hooks the frozen typechecker in-process, as
  `compiler/tools/std_cone.py` hooks its code generator, and compares what each
  call head and import binding resolved to over a program the two compilers
  both accept.
- `corpus_info.py` resolves every file of `tests/corpus/` and prints how many
  resolve with no refusal, and the rules the rest are refused by.

None of them gates; each is kept runnable. `FROZEN_CHECK.md` records what the
first two found.

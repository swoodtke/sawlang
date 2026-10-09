# compiler/resolve: name resolution

The resolve stage of the self-hosted compiler, package `sawresolve` (epic
SL-398, unit 6a, SL-445). It reads the parser's arena unchanged and produces
side tables keyed by the arena's node ids: what every name occurrence denotes,
how every call's head is classified, and each module's symbol, surface and
import tables (SL:architecture §3.3). `compiler/tests/resolve/README.md`
specifies its dump and holds its position matrix.

```
resolve/
  src/
    api.saw         resolve_program and the record `sawc2 resolve` prints
    program.saw     ResProgram: the modules, their arenas and every table
    model.saw       the records: modules, declarations, bindings, calls
    names.saw       the interner and the pair index, over flat vectors
    loader.saw      module identity to file to arena; the std module table
    prelude.saw     the builtin module's synthetic declarations; the prelude
    lang.saw        the lang-item table and its funnel
    collect.saw     phase 1
    imports.saw     phase 2
    lookup.saw      the lookup funnel and the scopes it reads
    kinds.saw       which alternatives build which kinds of position
    walk.saw        phase 3: declarations, bodies, types, patterns
    rules.saw       the conformance rules, which need every module
    dump.saw        the dump
    verify.saw      the verifier
```

## Modules

`sawc2 resolve` takes each file it is given as the entry of its own program.
A module's identity is its import path: `std.vector`, `sawparse.src.api`, or,
beside the entry file, the path as written (`shapes`, `util.io`); the entry
file's is its name without `.saw`. The synthetic `builtin` module holds what
nothing declares and `builtin.saw`'s declarations (SL:open-questions D12).

- The std root holds one of two stds. The new std (`--std-root std`) is told
  by its `prelude.saw`: `std.X` is `<std root>/X.saw`, every module in
  `load_new_std_modules`' table is loaded and compiled whole, writes its
  imports as any module does, and its prelude module declares the vocabulary
  the builtin module keeps under Stage 0's std; `std.string` declares
  `String`, which the prelude enters from there. That builtin module then
  holds only what no source can declare: the numbers, `Bool`, `Void`, `Never`,
  the two pointers, `print`, `panic`, `assert`, `sizeof` and `alignof`, and
  the atomic intrinsics the new std's refcounts are written over
  (`__saw_atomic_add_i64`, `__saw_atomic_sub_i64_release`,
  `__saw_atomic_fence_acquire`, spelled as Stage 0's synthesized helpers;
  SL:open-questions D23; and `__saw_atomic_load_i64_relaxed`, D24). No prelude entry names an intrinsic: only a module
  of the new std sees one, when `lookup` finds the name nowhere else. A
  prelude name the new std does not declare yet is left out.
- Under Stage 0's std (`sawc`, the default), `std.X` is
  `<std root>/std/X.saw`. Every std module in `load_frozen_std_modules`'
  table is loaded, as an interface only: its declarations, imports and
  signatures (generics with their bounds and defaults, field, payload, static
  and alias types, parameter and return types, extension heads, conformances
  and member signatures), never a body, a static initializer, a parameter
  default or an attribute's argument. The parser reads it so too
  (`parse_interface`): each body, static initializer and parameter default is
  a skipped node, so a refusal inside one costs nothing, and a declaration
  whose own text the parser refuses is dropped, with a note naming it, while
  the rest of the module loads. A refusal in an interface is a note, and the
  verifier checks the signatures it walks, and that no other module holds a
  skipped node. A std file the parser refuses as a whole, over a lex error or
  an unclosed bracket, is unavailable; a note says so, and an import of it is
  refused as `import.unavailable`.
- For a package mapped with `--module-path NAME=DIR`, `NAME` is `DIR/lib.saw`
  and `NAME.rest` is `DIR/rest.saw`, as the frozen compiler maps them.
- Any other path is looked for beside the importing file, then beside the
  entry file, then under the importing file's package root, the nearest
  directory at or above it that holds a `Saw.toml`.
- A `package` or `parent` path is not in the bootstrap slice yet.

Each module is collected as it loads. Ids are the program's: nodes index one
arena that holds every module's tree, declarations one table. A binding into
another module prints as that module's identity and the declaration's path.

## Phases

1. **Collect** (`collect.saw`). Each module's top-level declarations go into
   `top`, keyed by (module, name): types, functions as overload sets, statics,
   externs, traits, aliases. Enum cases, fields and trait and extension members
   go into `members`, keyed by (parent, name), and every case into `cases`,
   keyed by name. Two top-level declarations of one name that are not both
   functions are refused, and so is a case or field declared twice, and, in a
   module of the program, a declaration named like a prelude name.
2. **Imports** (`imports.saw`). Every import finds its module, loading new
   ones; the list of imports grows as they load, so one pass reaches the whole
   program. Qualifiers are bound, a second qualifier for another module
   refused. Import cycles among the program's modules are found by a
   depth-first walk with an explicit stack. Each module's import closure is
   computed once: the module, `builtin` and the modules the prelude draws
   from, and every module any of them imports, in any form, transitively. A
   module is marked as it is reached, so the walk ends over a refused cycle
   too. Each module's surface (its visible declarations and what its `public
   import`s hand on) grows by a worklist to a fixpoint. Then each selective
   import's names are resolved against the surface.
3. **Signatures and bodies** (`walk.saw`). Every name is looked up in its
   lexical scope through `lookup` (below), every binding made through
   `bind_local`, and every call's head classified once.

After the three phases, `rules.saw` checks the conformances: each lives in its
type's module or its trait's, and each (type, trait) pair is declared once.

## The lang-item table

The compiler knows some std declarations by role (SL-456): `Optional`,
`Result`, `Ordering`, the trait vocabulary it reasons about (the Copy family,
`Deinit`, `Equatable`, `Comparable`, `Hashable`, `Printable`, `Error`, `Send`,
`Sync` and their unsafe assertions, `Iterator`), the structs `Hasher`, `Range`
and `RangeInclusive`, the panic sink every panic calls once its message is
formatted, and the String layer: `String`, the functions the compiler lowers
its String positions through (`string_literal`, which wraps a literal's
immortal static block; `string_bytes`; `string_equals` and `string_compare`,
which `==`, the ordering operators and string-literal patterns compare with),
and `StringBuilder`, which interpolation builds through and a format string's
arguments render into (typecheck/README.md, "The String positions").
`lang.saw` holds the table, one declaration per role, bound once the builtin
and std modules are collected:

- under the new std, to the declaration its home module declares: the prelude
  module for a type or trait, `std.panic` for the sink, `std.string` for
  `String` and its functions, `std.stringbuilder` for the builder; a role it
  does not declare is refused as `lang.missing`;
- under Stage 0's std, to the builtin module's declaration of the role's name,
  the builtin `panic` for the sink and the builtin `String`, and to Stage 0's
  `std.stringbuilder` for the builder. The String functions are unbound
  there: Stage 0's code generator synthesizes them.

Only the std root's modules are consulted, so a program's own `enum Optional`
binds no role (it is refused as a prelude name). `lang_item` is the one query
of the table; its docstring names its entry points, and typecheck's known
declarations take each lang item from it. A role for allocation joins it with
the collections. Typecheck holds each bound declaration to its role's shape
(`lang.shape`, typecheck/README.md). A case named `None` is refused as
`name.none-case` in any enum but the Optional role's (SL:open-questions D22),
so the keyword keeps one meaning. Under the new std the resolve dump of
`std.prelude` ends with the table, `(lang-items ...)`.

## The lookup funnel

`lookup` in `lookup.saw` is the one lookup of a bare name, in design 150's
order: locals and type parameters, then the module's declarations, then
imported bare names, then the prelude, then the gated std tier, which refuses
with the import that supplies the name (a std module sees it bare, below),
then qualifiers. Functions of one name
merge across the module and its bare imports into one overload set (design
249); any other two imports of one name that bind two declarations are refused
at the use (design 255).
A type position sees type-level locals only. `bind_local` applies the
shadowing rule of designs 100 and 107. Their docstrings name their entry
points.

## Readings

These are the reversible readings the unit made; SL-445's report lists them.

- A lone name pattern is a payload-free case when some enum in the module's
  import closure declares a case of that name without a payload, and a binding
  otherwise (SL:open-questions D13). A variant pattern's head and an implicit
  member are case selectors: resolve records the cases of that name in the
  closure, and typecheck chooses one by the scrutinee's or the expected type.
  A scrutinee's type is reachable only through the closure, so no case it could
  name is left out, and an enum in a module the closure does not reach changes
  nothing. A variant pattern's head no enum in the closure declares as a case
  is looked up as a type, for a `try` block's error union.
- `Optional` is an enum with the cases `Some`, with a payload, and `None`, so
  `case Some(v)` is a case selector as `case Ok(v)` is: the builtin module's
  under Stage 0's std, the prelude's under the new std. `None` is a keyword, so
  only the declaration names its case, and no expression constructs a `Some`.
- A generic body names its type parameter's associated type as `T.Item`
  (SL:open-questions W4): a path headed by a type parameter is bound, as a
  projection, to the one associated type of that name its bounds declare or
  inherit through refinement. Two bounds reaching one declaration name it
  once; two declarations are refused as `name.ambiguous`, none as
  `name.undefined` naming the bounds searched. `Self.Item` in a trait names
  its own or an inherited associated type the same way. A trait's parents may
  sit in a module walked later, so these are decided once every module is
  walked (`settle_pending`), and their refusals follow the others.
- Bare `Item` in a generic body stays refused, as `name.undefined` with the
  fix-it `T.Item`, every in-scope parameter whose bounds reach one listed. A
  trait's body and its conformances name their own `Item` bare. `T.Item.Key`
  is `slice.not-yet`: an associated type declares no bound, so it names
  nothing yet. A bare name a glob import misses only because the
  declaration is private in its module is refused as `visibility.private`.
- A module of Stage 0's std sees the gated std tier bare, where any other
  module is refused with the import that supplies the name: `sawc/std` is
  written for the frozen compiler's one std namespace, in which
  `std/file.saw` names `Path` and `IoError` with no import. The new std's
  modules write their imports.
- A function beside a type of its name is a duplicate declaration, since
  types and values share one namespace.
- The concurrency forms `Thread.spawn` and `Task.spawn`, and the frozen
  compiler's `__saw_` test intrinsics, are outside the sync-only slice.
- A member of a module, and a case of an enum reached through its type, are
  resolved here. A member of any other type, a static method included, and a
  member of a value, are typecheck's: they need the type's members, which
  extensions add.
- Types and values share one namespace, but a type position skips value
  locals.
- `self` is the receiver of the enclosing method, the SelfExpr node its
  occurrence. `Self` is its own binding kind, the enclosing type or trait.
- A catch block binds `error`, recorded against the block.
- Test-only declarations are collected with a flag; a refusal case's body is
  never resolved, since a normal build only matches its braces.

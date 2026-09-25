# compiler/: the self-hosted Saw compiler

The Saw compiler written in Saw (epic SL-398). Until it builds itself, the
frozen Python compiler in `sawc/` builds it: that is bootstrap Stage 0. The
design lives in the tracker's docs, which `~/bin/sawtracker doc show NAME`
prints:

- **SL:architecture**: the stages and their contracts (§3), the shared
  representation (§3.0), and the bootstrap and the subset (§4).
- **SL:hazards**: the shapes Stage 0 mishandles, and which of them the subset
  checker refuses.
- **SL:testing** and **SL:borrowing**: the locked-down language the compiler
  implements.

## Layout

```
compiler/
  lex/                the lexer, package `sawlex` (lex/README.md has its dump format)
    src/lib.saw
    tests/*.saw       unit programs
  driver/             the `sawc2` binary, package `sawc2`
    src/main.saw
  tools/
    build.py          builds sawc2, or any program over the stage packages
    subset_check.py   the subset checker
  tests/
    run.py            the test runner
    lex/              golden token fixtures
    subset/           the subset checker's own fixtures
    grammar/          the tools over GRAMMAR.md: extract.py, lint.py, the
                      reference recognizer (recognize.py, contexts.py) and the
                      corpus lane (corpus.py, corpus_expected.tsv)
```

The parser corpus derived from the grammar, `tests/parse/`, arrives in phase 2
of SL-406.

Each stage has its own directory and is a package, with its source under
`src/`. The others import it as `<package>.src.<module>`, through
`--module-path`. `STAGE_PACKAGES` in `tools/build.py` is the one table of those
packages, and every build goes through `build_program` there. The driver is
named `sawc2` for now.

## Building

Use the venv's Python, since it runs the frozen compiler:

```sh
./.venv/bin/python compiler/tools/build.py            # builds .build/sawc2
.build/sawc2 lex [--docs] <file.saw>                   # the token dump, or the doc trivia
.build/sawc2 lex --kinds                               # every token kind's dump name
./.venv/bin/python compiler/tools/build.py ENTRY.saw -o OUT   # another program
```

A lex error prints one `ERROR` record and exits 1. A usage or I/O failure exits 2.

## Testing

```sh
./.venv/bin/python compiler/tests/run.py
```

The runner prints each failure on its own line, then one summary line, and exits
1 if anything failed. Its output is deterministic. The battery's `compiler` lane
runs it, and so does every per-patch gate run (`./build.sh test`). It checks five
things.

- **Unit programs**: `compiler/<stage>/tests/*.saw`. These are small programs in
  the subset, built by the frozen compiler against the stage packages. Each
  passes by exiting 0. Until the compiler builds itself, these and the golden
  dumps are its only tests. At self-hosting, `*.test.saw` sidecars take over
  (SL:testing §4).
- **Golden token fixtures**: `tests/lex/NAME.saw`, with the expected
  `sawc2 lex` output in `NAME.tokens`. Where doc trivia matter, `NAME.docs` holds
  the expected `sawc2 lex --docs` output. Each fixture's first line names its
  source, which is a tracked `.saw` file or the inputs of a lexer unit program.
  The fixtures are the lexer's oracle. When the lexer changes on purpose,
  regenerate the affected expectations with `sawc2 lex` and review the diff.
  No fixture line may end in whitespace, and no fixture may end in a blank line:
  the patch server's `git apply --whitespace=fix` and most editors strip both,
  so the runner refuses them by file and line.
- **Coverage**: every token kind appears in some `.tokens` file. The kinds come
  from the lexer itself: `sawc2 lex --kinds` prints `token_kinds()`, and the
  runner checks its length against the `TokenKind` cases as declared. Every kind
  of lex error appears too, taken from the messages of the lexer's own
  `err`/`err_at` calls.
- **The subset checker**, over the compiler's source and over its own fixtures
  (below).
- **The grammar tools** in `tests/grammar/`: the lint over `GRAMMAR.md`, with a
  fixture per check that injects one defect and names the line the check must
  report, and the reference recognizer's pinned trees, coverage records and
  refusals, with a fixture each rule it applies is seen deciding. Its
  full-corpus run, `tests/grammar/corpus.py`, is the battery's `grammarcorpus`
  lane: every tracked `.saw` file's verdict against
  `tests/grammar/corpus_expected.tsv`.

## The subset

The compiler's own source is written in the subset of SL:architecture §4. It is
the intersection of today's Saw and the locked-down language, with the shapes
Stage 0 mishandles taken out. `tools/subset_check.py` enforces it over every
`compiler/**/*.saw` except `compiler/tests/**` (fixtures hold arbitrary Saw) and
`*.test.saw` (sidecars, which only Stage 1 builds). It reads the source through
the frozen compiler's own lexer and parser, so it checks exactly what Stage 0
reads.

```sh
./.venv/bin/python compiler/tools/subset_check.py              # the tree
./.venv/bin/python compiler/tools/subset_check.py FILE...      # these files
```

A diagnostic reads `file:line: rule: message (source)`. The driver and the stage
packages form one build, and each unit program is a build of its own over the
stage packages. That matters for the rules that compare declarations across a
build. The rules read every region of a file: inline `module m { ... }` bodies
(`inline-module` refuses the module itself), trait default bodies, `init`
bodies, `static` initializers, `static_assert` conditions, and the text of each
interpolation.

Each rule has at least one fixture, `tests/subset/RULE.saw` or
`tests/subset/RULE.VARIANT.saw`, whose `// refuses: RULE...` markers name
exactly the lines and rules the checker must report; a rule named twice on a line
expects two findings of it there, each with its own message. The `clean`
fixtures, which hold the spellings SL:hazards recommends and ordinary subset
code, must report nothing. The runner fails for a rule with no fixture.

| Rule | Refuses | Source |
|---|---|---|
| `lex`, `parse` | a file the frozen lexer or parser rejects | §4 |
| `file-end` | a file that does not end in a newline | C2 |
| `sync-only` | tasks, threads, channels, `sleep`, a `blocking` extern | §4 |
| `closure-capture` | a closure naming an enclosing binding or `self`, a capture list | §4 |
| `type-alias` | any `type` alias | §4, S9 |
| `prelude-type-name` | a declared type named like a public std type, import-gated ones included | §4, L17 |
| `selective-imports` | `import m` and `import m.*` | §4, L3 |
| `import-allowlist` | a std module off `ALLOWED_STD_MODULES`, or a package that is not a compiler stage | §4 |
| `std-api` | a std call off `STD_API`; `m[k]` on a Map; a write, a mutating method or a presence test through `get`; `m[k]! = v`; `with_ref`, `with_var_ref`, `with_unique`, a closure-taking `lock` | §4 |
| `borrows-accessor` | `borrows`, `lend`, `lends`, and a `borrows struct` | §4 |
| `generic-extension-init` | an `init` in an extension with type parameters | §4, S1 |
| `integer-overload` | an overload set where a member takes a non-`Int` integer | §4, L1 |
| `any-type` | `any` in a type | §4, S12 |
| `box-type` | `Box` | §4, L8 |
| `cell-type` | `Mutex`, `SpinLock`, `Once`, `UnsafeMutableInterior`, `Atomic`, `Arc` | §4, S11, S15 |
| `raw-pointer` | pointer types, std's `unsafe struct`s, `unsafe`, `*p`, `move *p` | §4, C1 |
| `fixed-array` | `[T; N]` types, repeat literals, and an array literal with no written type to adopt | §4, L7 |
| `value-loop` | `break` with an operand | §4, L11 |
| `statement-arm` | a match arm whose body is a bare statement | §4, L13, C4 |
| `borrow-syntax` | `borrow` as a name | §4 |
| `test-directive` | `@test` | §4 |
| `deinit-body` | a `deinit` in an extension, a conformance or a trait body | leak tolerance |
| `borrowed-match-payload` | `move` of an arm binding, or a `match` on one, when the scrutinee is borrowed | S2 |
| `root-reuse` | an argument reading the receiver's or a `&` argument's root; an index write whose right side reads its root | S4 |
| `var-ref-into-let` | `&var`, or a call of a `&var self` method, reaching into a binding that is not a `var`, or into any `static` | S5 |
| `function-exit` | a value-returning body, `init` or closure that can fall off its end or end in a `Void` call; code after `return`, `break` or `continue` | S6 |
| `int-literal-range` | an unsuffixed integer literal above `Int.max`, except as a `UInt64` binding's value or as `-9223372036854775808` | S7 |
| `enum-equatable-body` | a hand-written `equals` on an enum, in its `Equatable` conformance or apart from it | S8 |
| `nested-optional` | `T??`, and an optional element or value type in `Vector`, `Map` or `Set` | S10 |
| `argument-labels` | a repeated label; a labeled call to a `borrows` accessor, std's or the build's, judged by the receiver's type | S14 |
| `index-receiver-call` | a method not known to only read, on storage reached through `x[i]`, `m[k]?.` or a tuple element | S15 |
| `cast-then-optional` | `?` or `??` after an `as` cast's type, on its line or the next | S17 |
| `program-unique-names` | a free function or `static` named like another in the build or in std; a type named like another in the build, since the checker keys its facts about types by name | S18 |
| `written-type-shape` | a written type nested 8 levels, `Optional<T>`, `Self` inside a tuple type | §4, S19 |
| `float-literal` | any float literal | §4, S20 |
| `interpolation-line-break` | a line break inside an interpolation's braces | S21 |
| `inline-module` | every inline `module name { }` | S22 |
| `from-raw-literal` | `from(raw:)` with a bare literal | L1 |
| `closure-syntax` | an unannotated closure parameter, `$0`, a trailing closure, a function type under `?` | L2 |
| `default-value-literal` | a default parameter value that is not a literal | L3 |
| `optional-shaping` | `== None`, a method directly on a `get` result, a collection literal returned as a `Result` | L4 |
| `empty-struct` | a struct with no fields | L5 |
| `bounded-extension` | a bound on an extension's type parameter | L6 |
| `name-collision` | a generic method and generic function sharing a name (std included), a static and an instance method sharing one, a type parameter spelled like a type | L9 |
| `type-param-receiver` | a call whose receiver is a type parameter | L10 |
| `leading-minus` | a line that begins with `-` after a token that can end an operand | L12 |
| `nesting-depth`, `chain-length` | brackets nested past 30; an operator, `??`, postfix, `else if` or `else if let` chain past 100 | L14 |
| `generic-extension-params` | an extension head naming a generic type, the build's or std's, without its type parameters, as `extension Gen { }`, `extension Gen: NoCopy {}` or `extension Vector { }` | L18 |
| `interpolation-content` | `//`, a brace or a quote inside an interpolation | C3 |

§4 is SL:architecture §4; the other codes are SL:hazards entries, and "leak
tolerance" is its introduction's "Leaks are tolerated in Stage 1". A hazard that
only leaks has no rule: Stage 1 is replaced after it compiles the source, so a
leak costs it memory, never output. That holds while no skipped drop has an
effect, which is why the source declares no `deinit` and why
`ALLOWED_STD_MODULES` is pinned in `tests/run.py`: adding a std module means
checking that every `deinit` it reaches only frees memory or closes a
descriptor. S13, a nested generic with defaulted parameters, only leaks, so it
has no rule.

Several checks are syntactic, so they are partial. What they cannot see stays a
trust obligation, as SL:hazards describes:

- `std-api` traces a receiver's type through written types: bindings, fields,
  the build's function and method returns (untraced when overloads return
  different types, since which overload a call picks is not traced), `get` and
  subscripts, `self` in an extension or a trait default body, a match-arm
  binding (from the scrutinee's enum, `Optional` or `Result` payload), and a
  destructured tuple's elements. A
  method on a traced receiver is the owning type's. A type parameter's methods
  are its bounds': one a build trait declares is the build's. On an untraced
  receiver, a name std declares counts as std's, even when a compiler type
  declares it too, so an instance method on the allowlist is allowed on every
  untraced receiver. `m[k]` is caught when the receiver traces to `Map`, or when
  the subscript is used as an optional.
- `closure-capture`, `root-reuse` and `var-ref-into-let` resolve names through
  lexical scopes. They do not follow values. A path headed by an inline module's
  name, such as `m.inner.NAME`, is followed through the module bodies it names:
  `var-ref-into-let` finds the `static` behind `&var m.NAME`, and `std-api`
  knows a call through `m.inner.f(...)` is the build's own.
- `nested-optional` sees written types only, not the types a generic
  instantiation produces.
- SL:hazards S16 and L15 have no check.

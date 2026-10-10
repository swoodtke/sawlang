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

LANGUAGE_SPEC.md is authoritative for meaning, with one exception. Where it
and one of these docs disagree, a **Ruled** section of the doc, or a retirement
it records (SL:borrowing §9), supersedes the spec text it names. Otherwise the
spec holds, and a doc that restates a rule the spec has since replaced is the
stale one. The spec is then rewritten to the ruling, so a conflict is temporary.
SL:open-questions logs how each one was settled.

## Layout

```
compiler/
  lex/                the lexer, package `sawlex` (lex/README.md has its dump format)
    src/lib.saw
    tests/*.saw       unit programs
  parse/              the parser, package `sawparse` (parse/README.md has its
                      records, its claims and its depth funnel)
    CLAIMS.tsv        the alternatives and rules the parser implements so far
    src/*.saw
    tests/*.saw       unit programs
  resolve/            name resolution, package `sawresolve` (resolve/README.md has
                      its phases and side tables)
    src/*.saw
  typecheck/          type checking, package `sawtypecheck` (typecheck/README.md
                      has its phases and readings)
    src/*.saw
    tests/*.saw       unit programs
  mir/                lowering to MIR, package `sawmir` (tests/mir/README.md has
                      the dump, the position matrices and the verifier's checks)
    src/*.saw
  eval/               the constant evaluator over MIR, package `saweval`
                      (tests/eval/README.md has its positions, record and rules)
    src/*.saw
  borrowck/           the borrow check over MIR, package `sawborrowck`
                      (tests/borrowck/README.md has its analysis, rules, labels
                      and dump)
    src/*.saw
  drops/              drop elaboration over borrow-checked MIR, package `sawdrops`
                      (tests/drops/README.md has its flags, glue resolution, rule,
                      dump and verifier)
    src/*.saw
  driver/             the `sawc2` binary, package `sawc2`
    src/main.saw
  tools/
    build.py          builds sawc2, or any program over the stage packages
    subset_check.py   the subset checker
    grammar_tables.py writes parse/src/grammar.saw from GRAMMAR.md
    depth_funnel.py   the parser's depth-funnel lane
    comma_funnel.py   the parser's comma-list-funnel lane
    frozen_compare.py the one-time comparison with the frozen parser, not a lane
    std_cone.py       the std cone of sawc2's Stage 0 build, recorded in std_cone.txt
                      and reviewed against SL:hazards in std_cone_review.md; with
                      --std-root, a program's cone against the new std
    std_suspension.py each std function's suspension verdict from Stage 0's std
                      check, recorded in std_suspension.txt and compiled into
                      typecheck/src/stdsuspension.saw
  tests/
    run.py            the test runner
    parse_lane.py     the parse lane: sawc2 parse against the parser corpus
    lex/              golden token fixtures
    subset/           the subset checker's own fixtures
    funnel/           the depth-funnel lane's own fixtures
    grammar/          the tools over GRAMMAR.md: extract.py, lint.py, the
                      reference recognizer (recognize.py, contexts.py, and
                      lexdump.py, which reads sawc2's token dump), the corpus
                      lane (corpus.py, corpus_expected.tsv), the canonical AST
                      dump (dump.py) and the corpus generator (generate.py)
    parse/            the parser corpus: the dump's specification (README.md),
                      hand-checked dumps, the generated cases, their waivers
    resolve/          the resolve lane (resolve_lane.py): the dump's specification
                      (README.md), golden dumps, refusal fixtures, the interface
                      parse's equivalence pin over std (interface_pin.py), and the
                      one-time frozen-compiler check (frozen_check.py, FROZEN_CHECK.md)
    typecheck/        the typecheck lane (typecheck_lane.py): the dump's
                      specification (README.md), golden dumps, refusal fixtures,
                      the one-time frozen-compiler check (frozen_check.py,
                      FROZEN_CHECK.md) and the std cone's coverage
                      (cone_coverage.py)
    mir/              the MIR lane (mir_lane.py): the dump's specification
                      (README.md), golden dumps, refusal fixtures, and how much
                      of tests/corpus/ lowers (corpus_info.py, for information)
    eval/             the evaluator lane (eval_lane.py): the record's specification
                      (README.md), golden records, refusal fixtures, and the
                      evaluator's agreement with typecheck's fold over tests/corpus/
    std/              the std lane (std_lane.py) over the new std in `std/`: the
                      subset profile's fixtures, the lang items' paired dumps
                      and shape fixtures, the API-equivalence members and
                      exceptions, the behaviour pairs, the call programs, the MIR
                      pins and the cones
    borrowck/         the borrowck lane (borrowck_lane.py): the dump's
                      specification (README.md), golden records, refusal and
                      due fixtures, the soundness premise's pins (premise/),
                      the conformance matrix of the borrow-check rows
                      (CONFORMANCE.md), and the move-error and loan
                      differentials over tests/corpus/ (differential.tsv,
                      loan_differential.tsv)
    drops/            the drops lane (drops_lane.py): the dump's specification
                      (README.md), golden records, refusal and due fixtures, and
                      the conformance rows drop elaboration owns (conformance.tsv)
```

The new std, the std sawc2 compiles from Stage 1 on, is the top-level `std/`
(SL-456): `sawc2 resolve`, `typecheck` and `mir` take it with `--std-root std`,
and compile each of its modules whole. Its prelude module declares what Stage
0's builtin module synthesizes, and resolve's lang-item table (resolve/README.md)
binds the compiler's vocabulary to it.

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
.build/sawc2 parse --dump FILE...                      # each file's canonical AST dump
.build/sawc2 parse --check FILE...                     # each file's diagnostics
./.venv/bin/python compiler/tools/build.py ENTRY.saw -o OUT   # another program
```

A lex error prints one `ERROR` record and exits 1, and so does a file the parser
refuses. A usage or I/O failure exits 2.

## Testing

```sh
./.venv/bin/python compiler/tests/run.py
```

The runner prints each failure on its own line, then one summary line, and exits
1 if anything failed. Its output is deterministic. The battery's `compiler` lane
runs it, and so does every per-patch gate run (`./build.sh test`). It checks
these things.

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
- **The std cone**: `tools/std_cone.py` recomputes, from a real Stage 0 build,
  every std and runtime declaration sawc2 reaches, and fails when that differs
  from `tools/std_cone.txt` in either direction. After a change that moves the
  cone, review the difference (`--why TEXT` shows how the build reaches a
  declaration), rerun it with `--write`, and commit the file. A declaration new
  to the cone is also reviewed against SL:hazards, as `tools/std_cone_review.md`
  records for the rest.
- **The std suspension table**: `tools/std_suspension.py` observes the frozen
  compiler's std check and fails when `tools/std_suspension.txt`, or its
  compiled form `typecheck/src/stdsuspension.saw`, differs from what it
  observes, or when the std modules holding a suspending function differ from
  those whose bodies spell a cooperative primitive. Rerun it with `--write`
  after std changes, and review the difference.
- **The grammar tools** in `tests/grammar/`: the lint over `GRAMMAR.md`, with a
  fixture per check that injects one defect and names the line the check must
  report, and the reference recognizer's pinned trees, coverage records and
  refusals, with a fixture each rule it applies is seen deciding. The
  recognizer reads its tokens from `sawc2 lex`. Its full-corpus run,
  `tests/grammar/corpus.py`, is the battery's `grammarcorpus` lane: every
  tracked `.saw` file's verdict against `tests/grammar/corpus_expected.tsv`.
- **The parser corpus** in `tests/parse/`: the hand-checked dumps, and the
  generated cases, which regenerating must reproduce byte for byte, with the
  `parsecoverage` check over them (`tests/parse/README.md`).
- **The parser** (`parse/README.md`): its grammar tables are current, its depth
  funnel holds (`tools/depth_funnel.py`, with fixtures in `tests/funnel/`), its
  comma lists all pass through one funnel (`tools/comma_funnel.py`), and
  the parse lane (`tests/parse_lane.py`) runs one `sawc2 parse` process over
  the parser corpus and `tests/corpus/`, requiring what `parse/CLAIMS.tsv`
  claims, and re-renders every expected dump through `sawc2 parse --redump`.
  The lane caches the recognizer's records under `.build/parse-lane/`.
- **Name resolution** (`resolve/README.md`): the resolve lane
  (`tests/resolve/resolve_lane.py`) holds `sawc2 resolve` to its golden dumps
  and refusal fixtures, requires a fixture for every rule it refuses by, and
  resolves the compiler's own source whole: the sawc2 build and each unit
  program.
- **Type checking** (`typecheck/README.md`): the typecheck lane
  (`tests/typecheck/typecheck_lane.py`) holds `sawc2 typecheck` to its golden
  dumps and refusal fixtures, requires a fixture for every rule it refuses by,
  and checks the compiler's own source whole, signatures, bodies and effects,
  the sawc2 build and each unit program, with no refusal, no verifier problem
  and no function that may suspend.
- **MIR** (`tests/mir/README.md`): the MIR lane (`tests/mir/mir_lane.py`) holds
  `sawc2 mir` to its golden dumps and refusal fixtures, and lowers the
  compiler's own source whole, the sawc2 build and each unit program, with no
  refusal and no problem from the MIR verifier.
- **Constants** (`tests/eval/README.md`): the evaluator lane
  (`tests/eval/eval_lane.py`) holds `sawc2 eval` to its golden records and
  refusal fixtures, requires a fixture for every rule it refuses by, evaluates
  the compiler's own source whole, and fails on any constant of tests/corpus/
  where the evaluator and typecheck's fold disagree.
- **The new std** (`tests/std/std_lane.py`): every module of `std/` resolves,
  typechecks, lowers and has its constants evaluated with no refusal and no
  invariant; the subset checker's std profile accepts it; each lang-item
  program types the same against `std/` and `sawc/`; each lang item keeps its
  shape; the std API allowlist's members match in the two stds (below); each
  behaviour pair runs under Stage 0 (exiting 0, or panicking as its
  `// expect-panic:` line says) and checks, lowers and evaluates against
  `std/`; each call program (`tests/std/calls/`), which only the new std can
  type, checks clean through drop elaboration, or is refused first where its
  `// refuses:` header says; each MIR pin (`tests/std/mir/`) holds, String's
  retain and release reading the count with a relaxed atomic load and comparing
  it with the immortal sentinel before any atomic read-modify-write; and each
  recorded cone holds, the ones of a program using only Optional and Result
  and of one whose only Strings are literals reaching no runtime module and
  no allocator, and the one of a program that interpolates reaching the
  builder and the allocator.
- **The borrow check** (`tests/borrowck/README.md`): the borrowck lane
  (`tests/borrowck/borrowck_lane.py`) holds `sawc2 borrowck` to its golden
  records, refusal and due fixtures, requires a fixture for every rule it
  refuses by, checks the compiler's own source whole and the new std with no
  refusal and no invariant, requires `tests/borrowck/CONFORMANCE.md` to
  account for every row of the five borrow-check sections of
  `examples/conformance/INDEX.md`, holds every tests/corpus/ program that
  expects a move error to a borrow-check refusal or a stated reason, and
  every program that expects a loan error, or that a loan rule refuses
  though it expects to succeed, to a loan refusal or a stated mechanism. The
  check is sound without lifetimes only because typecheck keeps every
  reference inside its function (SL-462), which `tests/borrowck/premise/`
  pins.
- **Drop elaboration** (`tests/drops/README.md`): the drops lane
  (`tests/drops/drops_lane.py`) holds `sawc2 drops` to its golden records,
  refusal and due fixtures, elaborates the compiler's own source whole and
  the new std with no refusal and no invariant, requires the verifier after
  elaboration to be clean over every tests/corpus/ program that elaborates,
  and holds each conformance row drop elaboration owns to its summary.

## The std profile

`tools/subset_check.py --std` holds `std/` to the subset with exactly the
low-level features SL:architecture §4 names: `raw-pointer` (raw memory and
pointers), `borrows-accessor` (`borrows` and `lend`), `deinit-body` (a type
owning a buffer frees it), and `box-type` and `generic-extension-init`
(allocator parameters: `Box<T, A>`, and `Vector<T, A>` built by its `init`)
are dropped. A bound may be `Allocator`, or a policy trait a container's
conditional conformance needs (`Copy`, `ExplicitCopy`, `Send`, `Sync`), and
nothing else (`bounded-extension`); a fieldless struct may be an allocator
(`empty-struct`); the prelude may declare the vocabulary's alias `Byte` and
no other (`type-alias`); and a std module imports only std modules
(`import-allowlist`). `prelude-type-name` and `std-api` hold the compiler to
std, so the profile drops them too, and `compile` and `owned-operand`, which
ask Stage 0's code generator, never run: sawc2's check of `std/` stands in.
The frozen parser predates a case named `None` and takes no attribute on a
method, so the profile reads such a case as an identifier and a method
without its `@synthesize(shared)`, and `move buf[i]` through a binding is the
raw-memory feature's move out of a pointer place, not `borrowed-match-payload`.
Its fixtures are `tests/std/subset/`.

## API equivalence

`STD_API` in `tools/subset_check.py` carries each allowlisted member's
contract, and `tests/std/equivalence.tsv` maps each to the declarations that
answer it, with the unit of SL-456 that writes them. Once a unit has landed,
the lane compares each of its declarations' signature record, from sawc2's
dump of `sawc/std` and of `std/`, effects, receiver, lend, parameters and
result. A lang item's members are held by the shape check instead. A
difference fails unless `tests/std/equivalence_exceptions.tsv` lists it with a
reason and the unit it is due by; an exception whose unit has landed fails.
Three rows compare more than a record: `layout String` holds the new std's
String to one `UnsafePointer<Int8>` field, which the `string_layout` pair holds
to Stage 0's size and alignment; `conformances TYPE` compares the traits whose
bounds a value of the type meets under each root, one probe program per
trait; and `paired NAME` names a conversion no declaration writes, held by the
paired program `lang/NAME.saw`.

## The subset

The compiler's own source is written in the subset of SL:architecture §4. It is
the intersection of today's Saw and the locked-down language, with the shapes
Stage 0 mishandles taken out. `tools/subset_check.py` enforces it over every
`compiler/**/*.saw` except `compiler/tests/**` (fixtures hold arbitrary Saw) and
`*.test.saw` (sidecars, which only Stage 1 builds). It reads the source through
the frozen compiler's own lexer and parser, so it checks exactly what Stage 0
reads. A build those rules accept is then compiled by the frozen compiler itself,
in a child process and without emitting code, for the rules only its code
generator can answer.

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
code, must report nothing. The runner fails for a rule with no fixture. A
fixture in `tests/subset/generated/` holds an `owned-operand` position that
only code another rule refuses can reach, such as a `String` cast to a pointer,
so it is compiled by itself, without the source rules.

| Rule | Refuses | Source |
|---|---|---|
| `lex`, `parse` | a file the frozen lexer or parser rejects | §4 |
| `compile` | a build the frozen compiler rejects, when every other rule accepts it | §4 |
| `file-end` | a file that does not end in a newline | C2 |
| `sync-only` | tasks, threads, channels, `sleep`, a `blocking` extern | §4 |
| `closure-capture` | a closure naming an enclosing binding or `self`, a capture list | §4 |
| `type-alias` | any `type` alias | §4, S9 |
| `prelude-type-name` | a declared type named like a public std type, import-gated ones included, or like `Optional` or `Result` | §4, L17 |
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
| `optional-try` | every `try?` | S3 |
| `root-reuse` | an argument reading the receiver's or a `&` argument's root; an index write whose right side reads its root | S4 |
| `var-ref-into-let` | `&var`, or a call of a `&var self` method, reaching into a binding that is not a `var`, or into any `static` | S5 |
| `function-exit` | a value-returning body, `init` or closure that can fall off its end or end in a `Void` call; code after `return`, `break` or `continue` | S6 |
| `int-literal-range` | an unsuffixed integer literal above `Int.max`, except as a `UInt64` binding's value or as `-9223372036854775808`; a literal with a signed suffix above its width's signed maximum, in any context, except the magnitude of the width's minimum under a unary minus (`-128_i8`) | S7 |
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
| `owned-operand` | an operand Stage 0's `_is_owned_temporary` calls an owned temporary, as a comparison operand, an interpolation segment, a format argument of `print`, `panic` or `assert`, or the operand of an `as` cast that builds a new value rather than forwarding it, a string literal exempt; any interpolation segment codegen renders through a synthesized `to_string()` (a type off its builtin fast path, such as a user `Printable`), a named place included | S23 |
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
| `generic-extension-params` | an extension head naming a generic type, the build's or std's (`Optional` and `Result` included), without its type parameters, as `extension Gen { }`, `extension Gen: NoCopy {}`, `extension Vector { }` or `extension Result { }`; its message for `extension Optional { }` says Stage 0 cannot extend `Optional` at all | L18 |
| `interpolation-content` | `//`, a brace or a quote inside an interpolation | C3 |
| `workaround-marker` | a comment that reads as a Stage 0 workaround marker but is not in its one form, or names an S or L entry SL:hazards does not declare | SL:hazards |

§4 is SL:architecture §4; the other codes are SL:hazards entries, and "leak
tolerance" is its introduction's "Leaks are tolerated in Stage 1". A hazard that
only leaks has no rule: Stage 1 is replaced after it compiles the source, so a
leak costs it memory, never output. That holds while no skipped drop has an
effect, which is why the source declares no `deinit` and why
`ALLOWED_STD_MODULES` is pinned in `tests/run.py`: adding a std module means
checking that every `deinit` it reaches only frees memory or closes a
descriptor. S13, a nested generic with defaulted parameters, only leaks, so it
has no rule. S23 only leaks too, and has one anyway: a parser comparing token
text, or a diagnostic interpolating it, would leak once per token of every file
Stage 1 compiles. S3's `try?`, which never releases the error it discards, has
one for the same reason: a parser's "try this, else fall back" paths would leak
once per attempt.

`owned-operand` asks the compiler, not the source: its code generator's
predicate judges each operand of the build Stage 0 is given, generic bodies at
each instantiation, and every body is generated, reached or not. A build that
another rule refuses is not compiled, so its `owned-operand` findings wait until
the others are fixed.

Several checks are syntactic, so they are partial. What they cannot see stays a
trust obligation, as SL:hazards describes:

- `std-api` traces a receiver's type through written types: bindings, fields,
  the build's function and method returns (of the overloads a call's argument
  count and labels can bind to, untraced when those return different types,
  since argument types are not traced), `get` and
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

## Stage 0 workarounds

Some code in `compiler/` is shaped around a frozen-compiler bug rather than
written the natural way: a value bound to a `let` only so Stage 0 releases it, or
an index computed apart from a call that borrows its root. Each such site carries
a marker, on its line or directly above it:

```saw
// Stage 0 workaround (SL:hazards S23): canonical: print("sawc2: cannot open {path}: {e}")
print("sawc2: cannot open {}: {}", path, e)
```

The id names the SL:hazards entry the code works around. `canonical:` gives the
spelling the workaround replaced, so undoing it after self-hosting is mechanical.
A short reason may follow after ` — `. A marked site is not an idiom to copy: it
exists for Stage 0 only, and is reverted to its canonical spelling once the
compiler builds itself.

The `workaround-marker` rule refuses a marker in any other spelling, one with no
`canonical:` part, and one whose id is not an S or L entry of the tracked copy of
SL:hazards, `.sawtracker/docs/hazards.md`. `tools/subset_check.py` over the tree,
and `tests/run.py`, print the inventory: the count per entry, then each marker's
entry, `file:line` and canonical spelling. A rule whose fix is a workaround asks
for the marker in its message.

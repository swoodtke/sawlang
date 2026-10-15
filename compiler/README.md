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
  target/             the target description, package `sawtarget`: every concrete
                      type's layout and the C convention (tests/mono/README.md,
                      "Layouts")
    src/layout.saw
  asserts/            the layout-assert funnel, package `sawasserts`: every
    src/layout.saw    mode's typecheck, then each `static_assert` over a
                      layout checked against the target's (tests/typecheck/
                      README.md, "Layout asserts")
  mono/               monomorphization over elaborated MIR, package `sawmono`
                      (tests/mono/README.md has its items, glue, dump and rules)
    src/*.saw
  coro/               coroutine lowering over mono's items, package `sawcoro`
                      (tests/coro/README.md has its decision, rules and dump)
    src/*.saw
  llvm/               the textual LLVM IR backend, package `sawllvm`
                      (tests/run/README.md has its translation and `sawc2 build`)
    src/*.saw
  driver/             the `sawc2` binary, package `sawc2`
    src/main.saw
  seed/               the bootstrap seed: sawc2's own IR per host target, and the
                      commit it was emitted from (pin); see "The seed"
  tools/
    build.py          builds the seed binary, Stage 1 and Stage 2, or any program
                      over the stage packages (by Stage 0)
    seed.py           writes the seed (a bump) and checks it
    subset_check.py   the subset checker
    sawc2_reading.py  sawc2's reading of a file in the frozen parser's tree, which
                      the subset checker's std profile reads std/ through
    grammar_tables.py writes parse/src/grammar.saw from GRAMMAR.md
    depth_funnel.py   the parser's depth-funnel lane
    comma_funnel.py   the parser's comma-list-funnel lane
    frozen_compare.py the one-time comparison with the frozen parser, not a lane;
                      sawc2_reading.py reads sawc2's dumps with its reader
    std_cone.py       the std cone of sawc2's Stage 0 build, recorded in std_cone.txt
                      and reviewed against SL:hazards in std_cone_review.md; with
                      --std-root, a program's cone against the new std
    std_suspension.py each std function's suspension verdict from Stage 0's std
                      check, recorded in std_suspension.txt and compiled into
                      typecheck/src/stdsuspension.saw
    runtime_table.py  the runtime ABI table, from runtime/ABI.md and the runtime's
                      sources, compiled into typecheck/src/runtimeabi.saw; and
                      Stage 0's copy of the runtime held to runtime/
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
    mono/             the mono lane (mono_lane.py): the dump's and the layout
                      table's specification (README.md), golden item dumps and
                      layout tables, refusal fixtures, and the layouts against
                      Stage 0's (layout_exceptions.tsv)
    coro/             the coro lane (coro_lane.py): the dump's specification
                      (README.md), golden frame decisions, refusal fixtures and
                      the packages they import (modules/)
    run/              the run lane (run_lane.py): the backend's, `sawc2 build`'s
                      and `sawc2 runtime`'s specification (README.md), and
                      programs built by sawc2 and by Stage 0 whose binaries'
                      output must agree
    fixpoint/         the fixpoint lane (fixpoint_lane.py): Stage 2, sawc2
                      built by sawc2, against Stage 1 over every lane's
                      invocations (twin.py runs both), Stage 3 against Stage 2,
                      and the adjudicated mismatches (mismatches.tsv)
```

The new std, the std sawc2 compiles from Stage 1 on, is the top-level `std/`
(SL-456): `sawc2 resolve`, `typecheck` and `mir` take it with `--std-root std`,
and compile each of its modules whole. Its prelude module declares what Stage
0's builtin module synthesizes, and resolve's lang-item table (resolve/README.md)
binds the compiler's vocabulary to it.

Each stage has its own directory and is a package, with its source under
`src/`, which is the package's module root: `--module-path` maps the package
to that directory, so the others import a module of it as `<package>.<module>`,
and the lexer, whose one file is `lib.saw`, as `sawlex`.
`STAGE_PACKAGES` in `tools/build.py` is the one table of those
packages, and every build goes through `build_program` there. The driver is
named `sawc2` for now.

## Building

The seed is sawc2 compiled by clang from its own LLVM IR, which is committed
under `seed/` (below). Stage 1 is the sawc2 the seed builds at -O2,
`.build/sawc2`. Stage 2 is sawc2 built by Stage 1 at -O2,
`.build/sawc2-stage2`, and Stage 3 is Stage 2 building itself. The fixpoint is
Stage 3 equal to Stage 2, byte for byte. Stage 0, the frozen Python compiler
in `sawc/`, builds none of them; it still builds the unit programs and the
oracles' programs (`build.py ENTRY -o OUT`), so the venv's Python is what runs
`build.py`:

```sh
./.venv/bin/python compiler/tools/build.py            # builds the seed, Stage 1, then Stage 2
.build/sawc2 lex [--docs] <file.saw>                   # the token dump, or the doc trivia
.build/sawc2 lex --kinds                               # every token kind's dump name
.build/sawc2 lex @LIST                                 # both dumps of each listed file, framed
.build/sawc2 parse --dump FILE...                      # each file's canonical AST dump
.build/sawc2 parse --check FILE...                     # each file's diagnostics
.build/sawc2 build --std-root std FILE -o OUT          # FILE compiled and linked by clang
.build/sawc2 build --std-root std --emit-ll FILE       # FILE's `.ll` on standard output
.build/sawc2 runtime --out DIR                         # the host's runtime objects, into DIR
./.venv/bin/python compiler/tools/build.py ENTRY.saw -o OUT   # another program
```

`sawc2 build` writes the program's `.ll` beside its output and runs clang on
it with the runtime objects the manifest beside the executable names
(tests/run/README.md). `sawc2 runtime` builds those objects: each runtime
source of `runtime/` and its C shim, at the module's own target, each export
checked against the runtime ABI table. The file and process API they use is
the ruled Stage 0 workaround of SL:open-questions, "SL-522": an unbuffered
write with an explicit `close`, and a blocking `Command.wait`, each site
marked for SL:hazards S28.

Every step of `build.py` is cached by key, so an unchanged tree compiles and
links nothing. The seed binary is built under `.build/seed/<key>/`, its key
covering the committed IR, `runtime/shim.c` and clang. Stage 1 is linked
against the seed's own runtime, and cached under a key covering the seed, the
trees it compiles and `build.py` itself, which holds the link's arguments
(`.build/sawc2.key`). Every link after it takes the runtime Stage 1 builds
from `runtime/` at the repository root, cached under `.build/rt2/<key>/` by a
key covering Stage 1, `runtime/`, std and clang, and named by
`.build/sawc2-runtime.txt`. Stage 2 is cached under a key covering Stage 1, the
trees it compiles, `build.py`, the runtime manifest and its objects, and clang
(`.build/sawc2-stage2.key`). The lanes run Stage 2; `SAWC2_STAGE=1` (or
`run.py --stage 1`) runs them on Stage 1 instead, for bisecting, and Stage 2
is then not built.

### The seed

`seed/` holds, for each host target (`arm64-apple-darwin`,
`aarch64-unknown-linux-gnu`, `x86_64-unknown-linux-gnu`), xz-compressed:

- `sawc2.ll.xz`, the driver's IR as `sawc2 build -O2 --emit-ll` writes it;
- `runtime/DIR/NAME.ll.xz`, each runtime source's IR as `sawc2 runtime
  --emit-ll` writes it.

`seed/pin` names the commit that IR was emitted from. `build.py`'s
`build_seed` decompresses the host's IR, compiles each runtime module and
`runtime/shim.c` from the tree as `sawc2 runtime` does, and links the driver
against them as `sawc2 build` does, all with the clang `choose_clang` picks.
The shim is the tree's, not the pin's, so a change to a shim seam the pinned
runtime IR calls owes a bump.

`tools/seed.py check` requires every target's IR to hold no absolute path,
so the IR depends only on the source and the target, and the seed to
reproduce itself: built from the committed IR, it emits, for the pinned
commit's tree, every target's committed IR byte for byte. The fixpoint lane
runs it with the host's seed; `--seed TRIPLE` runs it with another target's,
which in the Linux VM includes x86_64 under Rosetta.

**Bumping the seed** is needed only when `compiler/` starts using something
the seed does not compile; it is a patch of its own:

1. On a clean checkout of a commit of main, build the stages (`build.py`,
   with the current seed). The check reads the pinned commit's tree from git,
   so the pin has to name a commit that main holds.
2. `./.venv/bin/python compiler/tools/seed.py write --target arm64-apple-darwin`
   writes the host's seed from Stage 1 and pins HEAD; it refuses a tree whose
   `compiler/`, `std/` or `runtime/` differs from HEAD.
3. `tools/linux.py seed` writes the two Linux seeds the same way in the
   `sawlang-linux` VM, from the same commit, and copies them back.
4. `./.venv/bin/python compiler/tools/seed.py check`, then commit `seed/` on
   top of that commit. The IR is binary, so the patch is made with
   `git diff --binary`.

Stage 1 is the seed compiling the tree's `std/` as well as `compiler/`, so a
std change that needs a compiler feature the seed lacks, a new intrinsic say,
lands in two patches. The first is the compiler half: the feature, with its
pins, and std unchanged. The second, once the first is on main, bumps the
seed to its merge commit and makes the std change, with the pins that need
it (SL-662).

A lex error prints one `ERROR` record and exits 1, and so does a file the parser
refuses. A usage or I/O failure exits 2.

## Testing

```sh
./.venv/bin/python compiler/tests/run.py
```

The runner prints each failure on its own line, then one summary line, and exits
1 if anything failed. Its output is deterministic. The battery's `compiler` lane
runs it, and so does every per-patch gate run (`./build.sh test`). Every lane
below that runs sawc2 runs Stage 2. It checks these things.

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
- **The std cone**: `tools/std_cone.py` recomputes, from a real Stage 0 build
  of the driver, every std and runtime declaration that build reaches, and
  fails when that differs from `tools/std_cone.txt` in either direction. No
  stage is that build since the seed, but it is the one build of the whole
  driver by Stage 0, whose language `compiler/` stays in until `sawc/` is
  deleted. After a change that moves the
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
- **The runtime ABI table**: `tools/runtime_table.py` reads every
  `__saw_rt_*` seam's signature out of `runtime/ABI.md` (the seam set is
  Stage 0's, `sawc/runtime_abi.py`), with its owner, each host's runtime
  sources and the seams its C shim defines, and fails when
  `typecheck/src/runtimeabi.saw` differs from that reading, or when a host's
  sources and shim do not export the runtime's seams exactly once each. It
  also fails when Stage 0's copy of the runtime, `sawc/rt/`, differs from
  `runtime/` in any file, or when Stage 0 reads the ABI differently: the
  oracles compare programs Stage 0 links against its copy with programs sawc2
  links against `runtime/`, so the two trees are one runtime, and a runtime
  change is made in both until `sawc/` is deleted. Rerun it with `--write` after an ABI or
  runtime-source change, and review the difference. The table is checked in
  so that it outlives Stage 0 (SL:open-questions D41).
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
  builder and the allocator; and sawc2's own build, the driver with every stage
  package, typechecks, lowers, borrow-checks and drop-elaborates against `std/`
  with no refusal, its cone (`tests/std/cone/sawc2.cone`) reaching no runtime,
  task or network module.
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
- **Monomorphization and layout** (`tests/mono/README.md`): the mono lane
  (`tests/mono/mono_lane.py`) holds `sawc2 mono` to its golden item dumps and
  layout tables and its refusal fixtures, requires a fixture for every rule it
  refuses by, and compares each layout Stage 0 can name with Stage 0's.
- **Coroutine lowering** (`tests/coro/README.md`): the coro lane
  (`tests/coro/coro_lane.py`) holds `sawc2 coro` to its golden frame
  decisions and its refusal fixtures, requires a fixture for every rule it
  refuses by, and requires its decisions to agree with typecheck's summaries
  over the mono lane's and the run lane's programs.
- **The backend and `sawc2 build`** (`tests/run/README.md`): the run lane
  (`tests/run/run_lane.py`) builds each program of `tests/run/` with
  `sawc2 build` against the new std and with Stage 0, runs both, and requires
  the same output and exit status, a link printing nothing; a due program
  must be refused where it says; hello's `.ll` and one runtime source's are
  pinned; and `sawc2 runtime` writes the same bytes twice and refuses a
  runtime that leaves a seam undefined or defines one twice.

One lane runs apart from the runner: the per-patch gate runs it when
`compiler/` (the seed included), `std/`, `runtime/` or `sawc/` (Stage 0)
changes, and the battery's `fixpoint` stage runs it by hand:

- **The fixpoint** (`tests/fixpoint/fixpoint_lane.py`): the seed check
  (`tools/seed.py check`, "The seed" above), then Stage 1's `.ll` of
  its own driver is the same bytes over two builds and from another
  directory, Stage 2 writes that same `.ll`, Stage 3 (Stage 2 building
  itself) links into Stage 2's bytes, and every `sawc2` invocation the
  runner's sawc2-driven lanes make gives the same output and exit status
  under Stage 2 as under Stage 1, but for the mismatches
  `tests/fixpoint/mismatches.tsv` adjudicates.

## The std profile

`tools/subset_check.py --std` holds `std/` to the subset with exactly the
low-level features SL:architecture §4 names: `raw-pointer` (raw memory and
pointers), `borrows-accessor` and `borrow-syntax` (`borrows`, `lend`, and the
`borrow` that takes a lent place), `deinit-body` (a type owning a buffer frees
it), `box-type` and `generic-extension-init` (allocator parameters:
`Box<T, A>`, and `Vector<T, A>` built by its `init`), `cell-type` (the
prelude's `UnsafeMutableInterior` and the `Atomic` over it, SL:open-questions
D38) and `sync-only` (`std.task`'s park points and the modules that call them)
are dropped. A bound may be `Allocator`, or a policy trait a container's
conditional conformance needs (`Copy`, `ExplicitCopy`, `Send`, `Sync`), and
nothing else (`bounded-extension`); a fieldless struct may be an allocator
(`empty-struct`); the prelude may declare the vocabulary's alias `Byte` and
no other (`type-alias`); and a std module imports only std modules
(`import-allowlist`). `prelude-type-name` and `std-api` hold the compiler to
std, so the profile drops them too, and `compile` and `owned-operand`, which
ask Stage 0's code generator, never run: sawc2's check of `std/` stands in.
`prefix-cast` guards how the frozen parser reads a prefix over `as`, which
sawc2's reading makes moot, so it never runs either.
`move buf[i]` through a binding is the raw-memory feature's move out of a
pointer place, not `borrowed-match-payload`.

No stage compiles `std/` with Stage 0, so the profile reads it with sawc2
(`tools/sawc2_reading.py`), not the frozen parser: `sawc2 lex` gives the tokens
and `sawc2 parse --dump` the tree, rebuilt in the frozen parser's shapes so
that every rule reads `std/` as it reads the compiler's source. GRAMMAR.md
therefore decides what parses, and a file sawc2 refuses is refused as
`grammar` with sawc2's diagnostic, where the compiler's source gets `lex` and
`parse`. A form of the new language that the profile names no feature for is
refused as `new-feature`: a slice type, or a `constexpr` function. The reading
refuses to guess: a dump whose leaves do not line up with the tokens, or a node
it has no reading for, stops the check (`ReadingError`). Its fixtures are
`tests/std/subset/`, and the profile needs a built sawc2.

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
| `import-allowlist` | a std module off `ALLOWED_STD_MODULES`, a package that is not a compiler stage, or a path headed by `src` | §4 |
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
| `conditional-temporary` | a call's result read through a method, a field, an index or a tuple element in a bare value-`match` arm, a `match` guard or the right side of `??`, an operand only some paths evaluate | S29 |
| `prefix-cast` | a `-` or `~` whose operand is an `as` cast, unless the cast sits inside a parenthesis directly after the operator, as `-(x as T)`: `-x as T`, `-(x) as T` and `~(x as A) as B` are refused, and `(-x) as T` is the spelling for GRAMMAR.md's meaning; interpolations included | S30 |
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
| `redundant-visibility` | a field marked with its struct's own tier, `public` in a `public struct` or `public(package)` in a `public(package) struct`; a field inherits that tier, so only a narrowing `private` is written | the spec |

§4 is SL:architecture §4; "the spec" is LANGUAGE_SPEC.md's member visibility,
which states a field's tier once, on its type; the other codes are SL:hazards
entries, and "leak tolerance" is its introduction's "Leaks are tolerated in
Stage 1". A hazard that
only leaks has no rule: Stage 1 is replaced after it compiles the source, so a
leak costs it memory, never output. That holds while no skipped drop has an
effect, which is why the source declares no `deinit` and why
`ALLOWED_STD_MODULES` is pinned in `tests/run.py`: adding a std module means
checking that every `deinit` it reaches only frees memory or closes a
descriptor (SL:hazards S28: a write is unbuffered and a child is waited for
explicitly, so no `deinit` flushes or waits). S13, a nested generic with defaulted parameters, only leaks, so it
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

## Constructors

A function whose body only builds a value of a type is that type's `init`, called
as `Type(label: …)`: `TcValue(fault: f)`, not a free `tc_fault(f)`. A named
alternative with no argument to label is a `static func` on the type,
`ResBinding.unbound()`. A constructor whose parameters are exactly the struct's
fields is the memberwise construction itself, so it is not written. A function
that computes something and returns it as a struct stays a function named for
what it computes, `coro_edges(coro)` or `parse_source(path, text, unit)`, and so
do the stage entry points such as `mir_program(tc)`.

Two limits apply in this source:
- no `init` in an extension with type parameters (`generic-extension-init`,
  SL:hazards S1);
- no `init` whose labels and types are exactly the fields'. Under SL-648 that
  is an override of the memberwise construction, which Stage 0 refuses, so it
  waits until the compiler builds itself.

Some older factory functions predate this rule. SL-652 converts them, and new
code doesn't copy them.

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

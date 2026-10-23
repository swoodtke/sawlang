# compiler/: the self-hosted Saw compiler

The Saw compiler written in Saw (epic SL-398). The seed, its own IR, builds
Stage 1, so the compiler and its std may use the whole language; the
constraint is what the pinned seed compiles, which the bootstrap build
enforces. The frozen Python compiler in `sawc/`, Stage 0, stays only as the
oracle whose recorded runs the lanes compare with. The design lives in the
tracker's docs, which `~/bin/sawtracker doc show NAME` prints:

- **SL:architecture**: the stages and their contracts (§3), the shared
  representation (§3.0), and the bootstrap (§4).
- **SL:hazards**: the shapes Stage 0 mishandles, which the remaining workaround
  markers cite.
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
  seed/               the bootstrap seed's manifest (sawc2's own IR per host target,
                      by SHA-256, on the blob host) and the commit it was emitted
                      from (pin); see "The seed"
  tools/
    build.py          builds the seed binary, Stage 1 and Stage 2, and then any
                      program over the stage packages (by sawc2); fetches the seed
    seed.py           writes the seed (a bump), publishes it, and checks it
    subset_check.py   the subset checker: the source rules over compiler/ and std/
    sawc2_reading.py  sawc2's reading of a file in the frozen parser's tree, which
                      the subset checker and the parser's lanes read source through
    grammar_tables.py writes parse/src/grammar.saw from GRAMMAR.md
    depth_funnel.py   the parser's depth-funnel lane
    comma_funnel.py   the parser's comma-list-funnel lane
    frozen_compare.py the one-time comparison with the frozen parser, not a lane;
                      sawc2_reading.py reads sawc2's dumps with its reader
    std_cone.py       a program's cone against the new std, which the std lane's
                      recorded cones hold (tests/std/cone/)
    std_suspension.py each std function's suspension verdict from Stage 0's std
                      check, recorded in std_suspension.txt by --write (the v0
                      compiler) and compiled into typecheck/src/stdsuspension.saw
    runtime_table.py  the runtime ABI table, from runtime/ABI.md and the runtime's
                      sources, compiled into typecheck/src/runtimeabi.saw; and
                      Stage 0's copy of the runtime held to runtime/
  tests/
    run.py            the test runner
    oracle.py         Stage 0's recorded snapshots: the record format every lane
                      reads, the comparison, and the one way to the v0 compiler
                      that regenerates them (v0_root)
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
                      one-time frozen-compiler check (prelude_check.py, FROZEN_CHECK.md)
    typecheck/        the typecheck lane (typecheck_lane.py): the dump's
                      specification (README.md), golden dumps and refusal fixtures
    mir/              the MIR lane (mir_lane.py): the dump's specification
                      (README.md), golden dumps, refusal fixtures, and how much
                      of tests/corpus/ lowers (corpus_info.py, for information)
    eval/             the evaluator lane (eval_lane.py): the record's specification
                      (README.md), golden records, refusal fixtures, and the
                      evaluator's agreement with typecheck's fold over tests/corpus/
    std/              the std lane (std_lane.py) over the new std in `std/`: the
                      std profile's fixtures, the lang items' dumps and shape
                      fixtures, the behaviour pairs and Stage 0's recorded runs
                      of them (stage0/), the call programs, the MIR pins and the
                      cones
    borrowck/         the borrowck lane (borrowck_lane.py): the dump's
                      specification (README.md), golden records, refusal and
                      due fixtures, the soundness premise's pins (premise/),
                      the conformance matrix of the borrow-check rows
                      (CONFORMANCE.md), and the move-error and loan
                      differentials over tests/corpus/ (differential.tsv,
                      loan_differential.tsv, with Stage 0's recorded builds of
                      the fixtures it lists in stage0/)
    drops/            the drops lane (drops_lane.py): the dump's specification
                      (README.md), golden records, refusal and due fixtures, and
                      the conformance rows drop elaboration owns (conformance.tsv)
    mono/             the mono lane (mono_lane.py): the dump's and the layout
                      table's specification (README.md), golden item dumps and
                      layout tables, refusal fixtures, and the layouts against
                      Stage 0's recorded ones (stage0/, layout_exceptions.tsv)
    coro/             the coro lane (coro_lane.py): the dump's specification
                      (README.md), golden frame decisions, refusal fixtures and
                      the packages they import (modules/); Stage 0's snapshot
                      of the coroutine programs (stage0/) and the census
    run/              the run lane (run_lane.py): the backend's, `sawc2 build`'s
                      and `sawc2 runtime`'s specification (README.md), and
                      programs whose sawc2-built binaries' output must agree
                      with Stage 0's recorded runs (stage0/)
    migrate/          the corpus rewriter's golden fixtures, over the
                      instrument's recorded records (stage0/)
    corpusdiff/       the whole-corpus differential against Stage 0's snapshot
                      (stage0/), for information
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

The seed is sawc2 compiled by clang from its own LLVM IR, which `seed/`
names by SHA-256 and the blob host serves (below). Stage 1 is the sawc2 the seed builds at -O2,
`.build/sawc2`. Stage 2 is sawc2 built by Stage 1 at -O2,
`.build/sawc2-stage2`, and Stage 3 is Stage 2 building itself. The fixpoint is
Stage 3 equal to Stage 2, byte for byte. Stage 0, the frozen Python compiler
in `sawc/`, builds none of them, nor the unit programs (`build.py ENTRY -o
OUT`, by sawc2); the lanes read its recorded snapshots (`tests/oracle.py`),
and only a snapshot's regeneration runs it. A record does not name the Stage
0 that made it, so a change under `sawc/` rerecords every snapshot
(`tests/run/README.md`, "The oracle"):

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
links nothing. The seed's files are cached under `.build/blobs/` by SHA-256,
and the seed binary is built under `.build/seed/<key>/`, its key covering the
manifest's SHA-256s, `runtime/shim.c` and clang, so a cached seed builds with
no network. Stage 1 is linked
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

The seed of each host target (`arm64-apple-darwin`,
`aarch64-unknown-linux-gnu`, `x86_64-unknown-linux-gnu`) is these files,
xz-compressed:

- `sawc2.ll.xz`, the driver's IR as `sawc2 build -O2 --emit-ll` writes it;
- `runtime/DIR/NAME.ll.xz`, each runtime source's IR as `sawc2 runtime
  --emit-ll` writes it.

They are not in the tree. `seed/manifest.tsv` lists each one as its target,
name, SHA-256 and size, and the blob host serves it at
`https://blobs.sawlang.com/<SHA-256>`, publicly and unchanging; a blob is
never deleted, so every commit's seed stays buildable. `seed/pin` names the
commit the IR was emitted from. `build.py`'s `seed_blob` is the one way a seed
file is had: from the cache, `.build/blobs/<SHA-256>`, when its size and hash
are the manifest's, else fetched over HTTPS, checked, and cached. A file the
host lacks, a fetch that fails, or bytes that are not the manifest's are an
error naming the file, the URL and the expected hash. `SAWLANG_BLOB_URL` names
a mirror instead of the host.

`build_seed` decompresses the host's IR, compiles each runtime module and
`runtime/shim.c` from the tree as `sawc2 runtime` does, and links the driver
against them as `sawc2 build` does, all with the clang `choose_clang` picks.
The shim is the tree's, not the pin's, so a change to a shim seam the pinned
runtime IR calls owes a bump.

`tools/seed.py check` requires every target's IR to hold no absolute path,
so the IR depends only on the source and the target, and the seed to
reproduce itself: built from the manifest's IR, it emits, for the pinned
commit's tree, every target's IR byte for byte. It reads the IR through
`seed_blob`, so it judges the bytes the manifest names, never a file a bump
left in `.build/`. The fixpoint lane runs it with the host's seed; `--seed
TRIPLE` runs it with another target's, which in the Linux VM includes x86_64
under Rosetta.

**Bumping the seed** is needed only when `compiler/` starts using something
the seed does not compile; it is a patch of its own, and its diff is the
manifest and the pin:

1. On a clean checkout of a commit of main, build the stages (`build.py`,
   with the current seed). The check reads the pinned commit's tree from git,
   so the pin has to name a commit that main holds.
2. `./.venv/bin/python compiler/tools/seed.py write --target arm64-apple-darwin`
   emits the host's seed from Stage 1 into `.build/seed-write/`, then
   publishes it: uploads each new file, fetches it back to check the host
   serves those bytes, and rewrites the target's manifest lines and the pin,
   which names HEAD. It refuses a tree whose `compiler/`, `std/` or
   `runtime/` differs from HEAD. A file whose IR is unchanged keeps its
   manifest line, whatever xz now makes of it. The upload needs the blob
   host's upload key, which only the lead's machine holds:
   `SAWLANG_BLOB_KEY` and `SAWLANG_BLOB_KNOWN_HOSTS` name it and the host's
   pinned key, by default `.claude/blobs_upload_key` and
   `.claude/linode_known_hosts` in the checkout; without them `publish`
   refuses, naming them.
3. `tools/linux.py seed` emits the two Linux seeds the same way in the
   `sawlang-linux` VM, from the same commit, copies them back into
   `.build/seed-write/`, and publishes them from this machine
   (`seed.py publish`), since the VM has no key.
4. `./.venv/bin/python compiler/tools/seed.py check`, then commit
   `seed/manifest.tsv` and `seed/pin` on top of that commit.

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

- **Unit programs**: `compiler/<stage>/tests/*.saw`. These are small programs
  built by sawc2 against the new std and the stage packages (`build.py`'s
  `build_program`). Each passes by exiting 0. Until `*.test.saw` sidecars take
  over (SL:testing §4), these and the golden dumps are the compiler's own
  tests.
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
  `err`/`err_at` calls, as sawc2 reads the lexer's source (`tools/sawc2_reading.py`).
- **The subset checker**, over the compiler's source and over its own fixtures
  (below).
- **The std suspension table**: `tools/std_suspension.txt` is the frozen
  compiler's std check, recorded with the triple it was observed on, and
  `tools/std_suspension.py` fails when its compiled form
  `typecheck/src/stdsuspension.saw` differs from it, or when the new std's
  modules holding a suspending function differ from those calling a park
  point. `--write` observes the v0 compiler's std check again
  (`tests/oracle.py`'s `v0_root`), refuses unless the std modules holding a
  suspending row are those whose bodies spell a cooperative primitive, and
  rewrites both; review the difference.
- **The runtime ABI table**: `tools/runtime_table.py` reads every
  `__saw_rt_*` seam's signature out of `runtime/ABI.md` (the seam set is
  Stage 0's, `sawc/runtime_abi.py`), with its owner, each host's runtime
  sources and the seams its C shim defines, and fails when
  `typecheck/src/runtimeabi.saw` differs from that reading, or when a host's
  sources and shim do not export the runtime's seams exactly once each. It
  also fails when Stage 0's copy of the runtime, `sawc/rt/`, differs from
  `runtime/` in any file, or when Stage 0 reads the ABI differently: the
  recorded oracles hold programs Stage 0 linked against its copy beside
  programs sawc2 links against `runtime/`, so the two trees are one runtime, and a runtime
  change is made in both until `sawc/` is deleted. Rerun it with `--write` after an ABI or
  runtime-source change, and review the difference. The table is checked in
  so that it outlives Stage 0 (SL:open-questions D41).
- **The seed's fetch** (`tests/seed/test_seed_store.py`): `seed_blob` and
  `build_seed` against a blob host on 127.0.0.1, with a small seed of the
  host's target and caches of their own. A cold cache builds from fetched
  blobs; a warm one builds with the fetch URL unroutable; a corrupted cache
  entry is fetched again; a hash that matches no blob, bytes of the wrong
  size or hash, and a refused connection fail naming the file, the URL and the
  expected hash; and `seed.py publish` uploads only a changed file and fetches
  it back.
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
  program checks against `std/` with its recorded typecheck dump; each lang
  item keeps its shape; each behaviour pair's recorded run under Stage 0
  (`tests/std/stage0/`) exits 0, or panics as its `// expect-panic:` line says,
  and the pair checks, lowers and evaluates against `std/`; each call program (`tests/std/calls/`), which only the new std can
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
  refuses by, and compares each layout Stage 0 can name with Stage 0's
  recorded one.
- **Coroutine lowering** (`tests/coro/README.md`): the coro lane
  (`tests/coro/coro_lane.py`) holds `sawc2 coro` to its golden frame
  decisions and its refusal fixtures, requires a fixture for every rule it
  refuses by, and requires its decisions to agree with typecheck's summaries
  over the mono lane's and the run lane's programs.
- **The backend and `sawc2 build`** (`tests/run/README.md`): the run lane
  (`tests/run/run_lane.py`) builds each program of `tests/run/` with
  `sawc2 build` against the new std, runs it, and requires the output and
  exit status of Stage 0's recorded run (`tests/run/stage0/`), a link printing
  nothing; a due program
  must be refused where it says; hello's `.ll` and one runtime source's are
  pinned; and `sawc2 runtime` writes the same bytes twice and refuses a
  runtime that leaves a seam undefined or defines one twice.

Two lanes run apart from the runner. The corpus differential's regression
gate (`tests/corpusdiff/README.md`) runs every corpus program through sawc2
and fails on any verdict that moved from its baseline. The per-patch gate runs
the fixpoint lane when `compiler/` (the seed included), `std/`, `runtime/` or
`sawc/` (Stage 0) changes, and the battery's `fixpoint` stage runs it by hand:

- **The fixpoint** (`tests/fixpoint/fixpoint_lane.py`): the seed check
  (`tools/seed.py check`, "The seed" above), then Stage 1's `.ll` of
  its own driver is the same bytes over two builds and from another
  directory, Stage 2 writes that same `.ll`, Stage 3 (Stage 2 building
  itself) links into Stage 2's bytes, and every `sawc2` invocation the
  runner's sawc2-driven lanes make gives the same output and exit status
  under Stage 2 as under Stage 1, but for the mismatches
  `tests/fixpoint/mismatches.tsv` adjudicates.

## The subset checker

The compiler and its std may use the whole language: the seed builds Stage 1,
so nothing compiles the compiler's source with Stage 0, and the constraint is
what the pinned seed compiles, which the bootstrap build enforces
(SL:architecture §4). `tools/subset_check.py` keeps the source rules that hold
for reasons of their own, over every `compiler/**/*.saw` except
`compiler/tests/**` (fixtures hold arbitrary Saw), and with `--std`, over
`std/`.

```sh
./.venv/bin/python compiler/tools/subset_check.py              # the tree
./.venv/bin/python compiler/tools/subset_check.py FILE...      # these files
./.venv/bin/python compiler/tools/subset_check.py --std        # std/
```

It reads each file with sawc2 (`tools/sawc2_reading.py`): `sawc2 lex` gives the
tokens and `sawc2 parse --dump` the tree, rebuilt in the frozen parser's shapes
the rules are written over. GRAMMAR.md therefore decides what parses, and a file
sawc2 refuses is refused as `grammar` with sawc2's diagnostic. The reading
refuses to guess: a dump whose leaves do not line up with the tokens, or a node
it has no reading for, stops the check (`ReadingError`). The checker needs a
built sawc2. A diagnostic reads `file:line: rule: message (source)`, and the
rules read every region of a file, inline `module m { ... }` bodies included.

| Rule | Refuses | Source |
|---|---|---|
| `grammar` | a file sawc2's lexer or parser refuses | GRAMMAR.md |
| `import-allowlist` | in the compiler, a path headed by `src`; in std, an import of anything but a std module | the spec |
| `workaround-marker` | a comment that reads as a Stage 0 workaround marker but is not in its one form, or names an S or L entry SL:hazards does not declare | SL:hazards |
| `redundant-visibility` | a field marked with its struct's own tier, `public` in a `public struct` or `public(package)` in a `public(package) struct`; a field inherits that tier, so only a narrowing `private` is written | the spec |

"The spec" is LANGUAGE_SPEC.md: its Package Structure, where a package's module
root is its `src/`, and its member visibility, which states a field's tier once,
on its type.

Each rule has at least one fixture, `tests/subset/RULE.saw` or
`tests/subset/RULE.VARIANT.saw`, whose `// refuses: RULE...` markers name
exactly the lines and rules the checker must report; a rule named twice on a line
expects two findings of it there. The `clean` fixtures must report nothing. The
runner fails for a rule with no fixture. The std profile's fixtures are
`tests/std/subset/`, which the std lane checks the same way; its `clean`
fixtures hold the low-level forms std writes, which the reading must take.

## Constructors

A function whose body only builds a value of a type is that type's `init`, called
as `Type(label: …)`: `TcValue(fault: f)`, not a free `tc_fault(f)`. A named
alternative with no argument to label is a `static func` on the type,
`ResBinding.unbound()`. A constructor whose parameters are exactly the struct's
fields is the memberwise construction itself, so it is not written. A function
that computes something and returns it as a struct stays a function named for
what it computes, `coro_edges(coro)` or `parse_source(path, text, unit)`, and so
do the stage entry points such as `mir_program(tc)`.

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
spelling the workaround replaced, so undoing it is mechanical. A short reason
may follow after ` — `. A marked site is not an idiom to copy: Stage 0 no longer
builds the compiler, and each site is reverted to its canonical spelling once
sawc2 and the seed handle what its canonical form needs (SL-425).

The `workaround-marker` rule refuses a marker in any other spelling, one with no
`canonical:` part, and one whose id is not an S or L entry of the tracked copy of
SL:hazards, `.sawtracker/docs/hazards.md`. `tools/subset_check.py` over the tree,
and `tests/run.py`, print the inventory: the count per entry, then each marker's
entry, `file:line` and canonical spelling.

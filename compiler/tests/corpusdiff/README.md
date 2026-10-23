# compiler/tests/corpusdiff: every corpus program, sawc against Stage 0

The whole-corpus behavioural differential (SL-655, SL-398's acceptance item
4): each `tests/corpus/` program built and run by sawc, compared with what
Stage 0 did with its `examples/` twin, and put in one bucket under one key.
Its report is the list of what sawc cannot do yet, and its baseline is a
regression gate: the per-patch gate fails a patch that moves any program's
verdict (SL-666, "The gate" below).

```
corpusdiff/
  README.md         this specification
  corpusdiff.py     the tool
  stage0/           Stage 0's snapshot: index.tsv, and TRIPLE/PATH.stage0 per program
  corpus_diff.tsv   the baseline: one row per program (path, bucket, key, detail)
  annotations.tsv   the lane's own annotations (path, kind, reason)
```

```sh
python compiler/tests/corpusdiff/corpusdiff.py check
python compiler/tests/corpusdiff/corpusdiff.py snapshot [--reuse] [--jobs N] [PATH...]
python compiler/tests/corpusdiff/corpusdiff.py run [--jobs N] [--no-build] [--baseline | --quick] [--report FILE] [PATH...]
python compiler/tests/corpusdiff/corpusdiff.py gate [--no-build]
tools/battery.sh corpusdiff
```

## The programs

The corpus programs are found as `test_runner.py` finds the suite's under
`examples/`: every `.saw` below `tests/corpus/` outside a `modules`
directory, but those marked `EXPECT: skip`. Each is paired with the file of
the same path below `examples/` (SL:architecture §5), which every program has.

## The Stage 0 snapshot

`snapshot` compiles each twin with Stage 0, the v0 compiler that
`oracle.v0_compiler` finds (its `COMPILE-FLAGS` included), on the host triple
and writes one record per
program to `stage0/TRIPLE/PATH.stage0`, in the format
`compiler/tests/oracle.py` reads and writes, which the coroutine snapshot
(`compiler/tests/coro/stage0/`) shares:

- a program whose twin is `EXPECT: success` or `EXPECT: panic` is run twice
  from the repository root, as `test_runner.py` runs it, and the record holds
  its exit status, standard output and standard error, a stream that differs
  between the runs recorded as `varies`;
- a refusal test, and any build Stage 0 refuses, holds Stage 0's whole
  diagnostic output as `log` lines, and its `build` line holds the error
  that holds the first `EXPECT-ERROR-CONTAINS` text, the one a refusal is
  judged by (SL:coroutines §3.3);
- an `EXPECT: docs` test holds the documentation Stage 0 wrote; `compiles`
  and `object` tests hold the build alone;
- every record says whether Stage 0 met the twin's own directives
  (`meets_expect`).

`stage0/index.tsv` has one row per program, with the twin's SHA-256 prefix
and the sizes and hashes of what its record holds. `check` holds the snapshot
whole: a row and a record for every corpus program and none for anything
else, each row the summary of its record, and each twin unchanged since its
record was written. A corpus program added or a twin edited is caught there,
and `snapshot --reuse PATH...` writes just that record: `--reuse` keeps each
raw result saved under `.build/corpusdiff/stage0-raw/` whose twin has not
changed, so an interrupted write resumes where it stopped. The snapshot is
the oracle that outlives `sawc/`: `check` and `run` only read it, and only
`snapshot` runs Stage 0, through `oracle.v0_root`, the one place the v0
compiler's checkout is named.

## The measurement

`run` holds the snapshot whole first and stops if it is not; then it builds
sawc through `compiler/tools/build.py` (unless `--no-build`) and, for each
program, runs `sawc build --std-root std` on the corpus file with its
`COMPILE-FLAGS`, and runs what it builds the way the snapshot ran Stage 0's.
Both `snapshot` and `run` take one program at a time unless `--jobs` says
otherwise, and neither takes the suite lock, so either shares the machine
with the patch server's gate. `run`'s `--jobs` is held to the gate's worker
ceiling (`tools/gate_jobs.py`), and `gate` takes that whole budget.

The buckets:

| bucket | means | keys |
|---|---|---|
| `pass` | sawc does what Stage 0 did | `-` |
| `refused` | sawc refuses a program Stage 0 builds, or a refusal test by a gap rule | the stage and the rule: `resolve name.undefined`, `driver driver.usage` |
| `crash` | an `INVARIANT` line, sawc's own panic or signal, a signal in its binary, or a hang | `INVARIANT`, `sawc panic`, `sawc SIGNAL`, `sawc exit N`, `run SIGNAL`, `hang in build`, `hang in run` |
| `link` | clang or the link fails on sawc's `.ll` | `clang or the link` |
| `wrong` | it builds and runs, but the exit status or the output differs; or a refusal test is built, or refused by another rule than the plan's | `exit differs`, `stdout differs`, `stderr differs`, `sawc's binary panics`, `accepts a refusal test`, `refused by another rule` |
| `stage0-wrong` | Stage 0's answer is known wrong, or Stage 0 fails the twin's own directives | the annotation's citation, `Stage 0 fails its directives (unannotated)` |
| `nondeterministic` | the program's output varies, and no annotation says how to judge it | `Stage 0's stdout varies`, `sawc's two runs differ` |
| `slow` | a build or a run timed out, then finished at twice the timeout | `slow build`, `slow run` |

Each key's detail is the first refusal's message, the first line that
differs, or what sawc printed. The first of these that applies decides a
program's bucket:

1. sawc's build printed an `INVARIANT` line: `crash`.
2. A refusal test (`EXPECT: error`) is judged as the coroutine census judges
   one (`oracle.judge_refusal`): `pass` when sawc refuses it by the rule the
   plan names for its Stage 0 error, or by any rule that is no gap when the
   plan names none; `refused` when a gap rule (`oracle.GAP_RULES`) refuses
   it; `wrong` when sawc builds it or refuses it by another rule. A refusal
   test whose refusal `annotations.tsv` marks `stage0-wrong` is not: it goes
   on through the rules below like any program, and one sawc builds is run.
3. Any other refusal: `refused`, keyed by its stage and rule. A flag `sawc
   build` does not take is the driver's refusal, `driver driver.usage`
   (Stage 0's `--runtime-build` is passed as `--runtime`,
   `oracle.SAWC_SPELLINGS`), and a `--target` sawc has no layout for is
   `driver driver.unknown-target`.
4. A `compiles`, `object` or `docs` test that builds: `pass`.
5. A build that fails otherwise: `crash` when sawc panicked, died by a
   signal or printed no error; `link` when clang or the linker printed one.
6. The binary died by a signal, a panic's abort aside, that Stage 0's did not
   die by: `crash`.
7. Stage 0's answer is known wrong (see Annotations): `stage0-wrong`, keyed
   by the citation, its detail saying whether sawc meets the program's own
   directives, the oracle there; for a refusal test, whose directives state
   no run, the detail is what the run did: `sawc builds it, and its run
   exits N` or `panics: …`.
8. The corpus file's `EXPECT` is not its twin's, since the language changed
   on purpose (SL:architecture §5), or `annotations.tsv` marks the program
   `nondeterministic`: it is judged by its own directives, `pass` or `wrong`.
9. Stage 0's two runs differed: `nondeterministic`.
10. Stage 0 did not build the twin or did not meet its directives, and
    nothing says why: `stage0-wrong`.
11. The run is compared with Stage 0's (below): `pass` when they agree,
    else `wrong`, after one more run: a binary whose two runs differ from
    each other is `nondeterministic` instead.

**Comparing a run.** Both sides' streams are compared after removing what
neither compiler's program decides: the checkout's root; the corpus root
(Stage 0 compiled `examples/PATH`, sawc `tests/corpus/PATH`); and the
location of a `panic at FILE:LINE:` outside the program's own file, since each
compiler's std is its own file. The program's own panic lines are compared
only when its twin is the same file, since a migration may move them. A stream
Stage 0 recorded as `varies` is not compared. A link error's text has clang's
temporary object names made equal by the fixpoint twin's rule
(`compiler/tests/fixpoint/twin.py`) before it becomes a detail.

**Timeouts.** A build and a run each have a timeout. Since the lane shares
the machine with the patch server's gate, a timeout is not yet a hang: every
program that timed out is tried once more at the end of the sweep, at twice
the timeout, and is a `crash` (`hang in …`) only if it times out again, else
`slow`, with both times in its detail.

**The stage of a refusal** is the compiler stage whose source spells the
rule; for a rule several stages spell (`slice.not-yet`), it is the first of
sawc's stage commands (`parse`, `resolve`, … `coro`) whose `--check` makes
the same refusal at the same position, and `llvm` when none before the
backend does.

## Annotations

The lane reads the corpus file's own annotations, as the other lanes do:
an `XFAIL:` pin of a filed finding, the run lane's `// differs:` line citing
SL:hazards with its `// prints:` lines, and SL:architecture §5's `oracle
known wrong: SL-nnn`. `annotations.tsv` adds the lane's own, one row per
program, for what a corpus file does not say:

- `stage0-wrong`: Stage 0's answer is known wrong; the reason cites the DF,
  SL issue or SL:hazards entry. On a refusal test it says the refusal is a
  Stage 0 limit, not the language's;
- `nondeterministic`: the program's output depends on scheduling, time or
  hash order, so it is judged by its own directives.

## The report and the baseline

`run` writes `.build/corpusdiff/results.tsv`, one row per program, and
`report.md`, and prints the report: the commit it measured (HEAD, and the
newest main commit in its history), the counts per bucket, then each bucket's
keys ranked by program count with three example paths each and the most
common details under each key, then the counts by the twin's `EXPECT`. A
gap rule's details group as written, since the missing name is the point;
every other key's group by their shape, each name and number made alike.

`corpus_diff.tsv` is the checked-in baseline: `run --baseline` rewrites it
from a run over the whole corpus, and every other run ends with the programs
that moved since it, from which bucket and key to which. A `slow` program is
written as the verdict its second try reached, since whether a run times out
says more about the machine's load than about sawc.

A run over named PATHs, or the quick form, is partial: it writes
`results-partial.tsv` and `report-partial.md` beside the whole run's files
and leaves those alone. `run --quick` checks the whole snapshot, then measures
the first program under each bucket and key of the baseline, so every verdict
the baseline holds is reached once.

## The gate

`gate` is a whole run on the gate's worker budget, compared with the
baseline. It fails when the snapshot is not whole, when sawc does not build,
and when any program moved: a new bucket or key, an improvement as much as a
regression; a new detail inside `stage0-wrong`, where the detail is the
oracle's answer (the run against the program's own directives); a program the
baseline lacks; or a baseline row for a program that is gone. A `slow`
program is compared by the verdict its second try reached. Each move is
printed with its old and new verdict, and the whole report is written to
`.build/corpusdiff/report.md`.

So the baseline always says what main does. A patch that moves a verdict on
purpose, a sawc fix or a new corpus program, runs `run --baseline` and
carries the rewritten rows, which review reads as the patch's effect on the
corpus; the gate then finds nothing moved. Details outside `stage0-wrong`, a
refusal's message or the first line that differs, may change freely.

The baseline is a measurement, so its rows are never merged by hand. On a
rebase, take main's `corpus_diff.tsv` whole and re-run `run --baseline` on the
rebased tree: rows the branch never claimed can move under it, and only a full
run sees them. Run `tools/git_setup.sh` once per clone, and git keeps main's
file on a rebase by itself (`.gitattributes` names its merge driver; a clone
without the setup gets an ordinary text merge). Under `git merge main` the
driver keeps the branch's file instead, so rebase rather than merge main.
Whichever side the driver keeps, the re-measure is still owed before
submitting. A forgotten one is never silent: the gate compares every measured
verdict with the file and fails with the moved programs named.

The per-patch gate (`tools/patch_gate.py`) runs it when what sawc is built
from changes, or what the measurement reads: `tests/corpus/`, the vector
files the programs read, `examples/` (the twins the snapshot must be current
with), this directory, and `compiler/tests/oracle.py` with the modules it
imports. It runs in full there, never in the quick form: one program per
bucket and key cannot see a passing program regress, and the whole run's
builds spread over the gate's workers. The battery's `corpusdiff`
stage runs it too. `run --quick` stays for a quick look by hand.

## The coroutine census

`compiler/tests/coro/census.py` measures the same thing over the coroutine
programs, judging each by its own directives rather than by Stage 0's
snapshot, and adds the plan's gating; it reads the shared module for the
build, the run and the refusal judgement, and its snapshot is the same record
format with frame layouts added.

The two overlap: the census's programs and refusal tests are corpus programs,
and its snapshot's run and refusal records say what this snapshot's records
for them say. They merge in three moves. The coroutine snapshot keeps only
its frame layouts and tables, and reads each program's run from `stage0/`
here. The census becomes this tool's run over its program list, so a
coroutine program is judged by Stage 0's output as well as by its own
directives, which moves the census's counts once. The plan's gating becomes a
report over that run's refusals, which needs every refusal of a program kept,
where `corpus_diff.tsv` keeps the first.

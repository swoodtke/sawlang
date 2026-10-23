#!/usr/bin/env python3
"""The per-patch gate decides by changed path, runs no Python compiler, and
fails a patch on any corpus program whose verdict moved (SL-666).

    python tools/test_patch_gate.py

Checks, with nothing built or run:

- `patch_gate.plan` over representative changed-path sets: which parts run,
  and why;
- no part's command names the frozen Python compiler or a runner of it, and
  every directory sawc is built from is an input of the corpus differential;
- `corpusdiff.regressions`, the baseline's rule, over synthetic rows: a new
  bucket or key fails, an improvement included, as does a new detail inside
  `stage0-wrong`, a program the baseline lacks and a baseline row nothing
  measured; a detail outside `stage0-wrong` does not, and a `slow` program is
  compared by the verdict its second try reached;
- a refusal test that annotations.tsv marks `stage0-wrong` is built and run
  rather than judged as a refusal, and its detail says what the run did;
- an unknown target is a driver refusal, and a usage refusal names a flag by
  the spelling `sawc build` is given;
- measuring threads that key refusals at once agree on the stage, since a
  gate that flips a key by thread timing fails patches for nothing.
"""
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "corpusdiff"))

import patch_gate  # noqa: E402
import corpusdiff  # noqa: E402

failures = []


def check(cond, what):
    if not cond:
        failures.append(what)


def decisions(paths):
    """{part name: run?} for `paths` (None = unknown)."""
    return {name: run for name, run, _, _ in patch_gate.plan(paths, "test")}


ALL = ("compiler tests", "fixpoint", "grammar corpus", "corpusdiff")
GRAMMAR_FILES = "grammar: changed .saw files"

# (changed paths, the parts that run). The per-file grammar check is listed
# when it runs.
CASES = (
    (None, ALL),
    ({"tools/patch_gate.py"}, ALL),
    ({".sawtracker/tests.json"}, ALL),
    ({"designs/todo.md"}, ("compiler tests",)),
    ({"sawc/codegen/calls.py"}, ("compiler tests", "fixpoint")),
    ({"test_runner.py"}, ("compiler tests",)),
    ({"tests/freestanding/cases/hello.saw"}, ("compiler tests", GRAMMAR_FILES)),
    ({"blade/src/main.saw", "libs/toml/src/lib.saw"}, ("compiler tests", GRAMMAR_FILES)),
    ({"compiler/typecheck/src/check.saw"}, ("compiler tests", "fixpoint", "corpusdiff", GRAMMAR_FILES)),
    ({"compiler/typecheck/tests/golden.saw"}, ("compiler tests", "fixpoint", GRAMMAR_FILES)),
    ({"compiler/parse/src/grammar.saw"}, ALL),
    ({"compiler/driver/src/main.saw"}, ALL),
    ({"std/vector.saw"}, ("compiler tests", "fixpoint", "corpusdiff", GRAMMAR_FILES)),
    ({"runtime/common/os_ops.saw"}, ("compiler tests", "fixpoint", "corpusdiff", GRAMMAR_FILES)),
    ({"tests/corpus/hello.saw"}, ("compiler tests", "fixpoint", "corpusdiff", GRAMMAR_FILES)),
    ({"examples/hello.saw"}, ("compiler tests", "corpusdiff", GRAMMAR_FILES)),
    ({"tests/float_vectors/shortest.tsv"}, ("compiler tests", "corpusdiff")),
    ({"compiler/tests/corpusdiff/corpus_diff.tsv"}, ("compiler tests", "fixpoint", "corpusdiff")),
    ({"compiler/tests/oracle.py"}, ("compiler tests", "fixpoint", "corpusdiff")),
    ({"GRAMMAR.md"}, ("compiler tests", "grammar corpus")),
    ({"compiler/tests/parse/cases/expr.saw"}, ("compiler tests", "fixpoint")),
)


def check_plans():
    for paths, want in CASES:
        got = decisions(paths)
        ran = tuple(name for name in got if got[name])
        check(sorted(ran) == sorted(want), "plan(%s) runs %s, want %s" % (sorted(paths or ["<unknown>"]),
                                                                           ", ".join(ran), ", ".join(want)))


def check_no_python_compiler():
    names = [name for name, _ in patch_gate.PARTS]
    check(names == list(ALL), "the gate's parts are %s, want %s" % (names, list(ALL)))
    retired = ("sawc/", "test_runner.py", "freestanding_runner.py", "astdiff.py")
    for name, command in patch_gate.PARTS:
        for word in command:
            check(not any(r in word for r in retired), "part %s runs %s, which is retired" % (name, word))
    for part, inputs in patch_gate.SUITE_INPUTS.items():
        check(part in names, "SUITE_INPUTS names %s, which is no part" % part)
    for _, directory in patch_gate.build.STAGE_PACKAGES:
        check(directory + "/" in patch_gate.SUITE_INPUTS["corpusdiff"],
              "%s builds sawc but is no corpusdiff input" % directory)


def row(path, bucket, key="-", detail="-", **extra):
    return dict(path=path, bucket=bucket, key=key, detail=detail, **extra)


def check_regressions():
    base = [row("a.saw", "pass"), row("b.saw", "refused", "resolve name.undefined", "`x` is not defined"),
            row("c.saw", "stage0-wrong", "annotated SL-283", "sawc meets its directives"),
            row("d.saw", "wrong", "stdout differs", "line 3")]
    same = [dict(r) for r in base]
    check(corpusdiff.regressions(same, base) == [], "an unmoved run reports moves")

    def moved(changes, want):
        rows = [dict(r) for r in base]
        for k, fields in changes.items():
            rows[k].update(fields)
        got = corpusdiff.regressions(rows, base)
        check(len(got) == want, "%s: %d move(s) reported, want %d: %s" % (changes, len(got), want, got))
        return got

    got = moved({0: dict(bucket="wrong", key="stdout differs")}, 1)
    check(got and "a.saw" in got[0] and "`pass -`" in got[0], "a program leaving pass is not named: %s" % got)
    moved({1: dict(key="typecheck call.no-match")}, 1)
    moved({1: dict(bucket="pass", key="-")}, 1)
    moved({1: dict(detail="`y` is not defined")}, 0)
    moved({3: dict(detail="line 4")}, 0)
    got = moved({2: dict(detail="sawc: exit 1")}, 1)
    check(got and "inside `stage0-wrong" in got[0], "a stage0-wrong detail move is not named as one: %s" % got)
    got = corpusdiff.regressions(same + [row("e.saw", "pass")], base)
    check(len(got) == 1 and "e.saw is not in the baseline" in got[0], "a new program is not reported: %s" % got)
    got = corpusdiff.regressions(same[1:], base)
    check(len(got) == 1 and "a.saw is in the baseline but was not measured" in got[0],
          "a lost program is not reported: %s" % got)
    slow = row("a.saw", "slow", "slow run", "timed out after 60s, finished in 70s on a second try: pass -",
               settled=("pass", "-", "-"))
    rows = [corpusdiff.settled(slow)] + same[1:]
    check(corpusdiff.regressions(rows, base) == [], "a slow program is compared by its first try's bucket")
    check(corpusdiff.settled(base[1]) == base[1], "settled() changes a row that did not time out")


def check_wrong_refusal():
    path = "while_let_tuple_over_suspension_refused.saw"
    d = corpusdiff.expect.read(os.path.join(corpusdiff.CORPUS, path))
    rec = corpusdiff.load()[path]
    annotations = corpusdiff.read_annotations()
    check(annotations.get(path, (None,))[0] == "stage0-wrong", "%s is not annotated stage0-wrong" % path)
    src = os.path.join(corpusdiff.CORPUS, path)
    check(corpusdiff.build_verdict(src, d, rec, 0, [], "", wrong_refusal=False)[:2] == ("wrong", "accepts a refusal test"),
          "an unannotated refusal test that builds is not `wrong`")
    check(corpusdiff.build_verdict(src, d, rec, 0, [], "", wrong_refusal=True) is None,
          "an annotated refusal test that builds is not run")
    got = corpusdiff.run_verdict(path, d, rec, 0, "66\n", "", annotations)
    check(got == ("stage0-wrong", "annotated SL-566", "sawc builds it, and its run exits 0"),
          "an annotated refusal test's run: %s" % (got,))


def check_driver_refusals():
    """A target sawc has no layout for is a driver refusal, not a crash; a
    usage refusal names only the flags sawc does not take, as `sawc build`
    spells them."""
    path = "static_zero_bss.saw"
    d = corpusdiff.expect.read(os.path.join(corpusdiff.CORPUS, path))
    rec = corpusdiff.load()[path]
    src = os.path.join(corpusdiff.CORPUS, path)
    got = corpusdiff.build_verdict(src, d, rec, 2, [], "sawc: unknown target riscv32-unknown-none-elf\n")
    check(got == ("refused", "driver driver.unknown-target", "sawc: unknown target riscv32-unknown-none-elf"),
          "an unknown target's exit: %s" % (got,))
    check("driver.unknown-target" in corpusdiff._NAMED_DETAILS, "an unknown target's details are grouped by shape")
    path = "runtime_build_suspending_body_error.saw"
    d = corpusdiff.expect.read(os.path.join(corpusdiff.CORPUS, path))
    rec = corpusdiff.load()[path]
    src = os.path.join(corpusdiff.CORPUS, path)
    usage = "usage: sawc lex [--docs] <file.saw>\n       sawc build [--runtime] (FILE [-o OUT])\n"
    got = corpusdiff.build_verdict(src, d, rec, 2, [], usage)
    check(got == ("refused", "driver driver.usage", "sawc build takes no such arguments"),
          "a usage refusal names a Stage 0 spelling sawc maps: %s" % (got,))


def check_stage_table_threads():
    """Threads that key refusals at once, as a parallel run does, each see the
    whole table of which stage spells a rule, never a half-filled one."""
    rule = "slice.not-yet"
    corpusdiff._STAGES.clear()
    want = corpusdiff.stage_of(rule)
    check("+" in want, "%s is spelled by one stage only (%s), so this check sees no race" % (rule, want))
    for _ in range(3):
        corpusdiff._STAGES.clear()
        got = []
        threads = [threading.Thread(target=lambda: got.append(corpusdiff.stage_of(rule))) for _ in range(12)]
        # Staggered, so later threads arrive while the first is filling the table.
        for t in threads:
            t.start()
            time.sleep(0.002)
        for t in threads:
            t.join()
        check(set(got) == {want}, "threads keyed %s by %s, want %s" % (rule, sorted(set(got)), want))


def main():
    check_plans()
    check_no_python_compiler()
    check_regressions()
    check_wrong_refusal()
    check_driver_refusals()
    check_stage_table_threads()
    for f in failures:
        print("FAIL: " + f)
    print("patch gate: %s" % ("FAIL (%d)" % len(failures) if failures else "ok"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

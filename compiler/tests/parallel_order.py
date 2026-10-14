#!/usr/bin/env python3
"""A serial and a parallel run print the same, an injected failure included.

    python compiler/tests/parallel_order.py

`compiler/tests/run.py` runs `run()`. It checks:

- the worker-count knob, `tools/gate_jobs.py`: three quarters of the cores,
  rounded down and at least one, with SAW_GATE_JOBS clamped to it, and a
  budget of N tokens never running more than N at once;
- a few of run.py's steps, run serially (one worker) and in parallel (this
  step's budget), print the same bytes, with a failure injected into one case
  of the coro lane appearing in both at the same place, and each writes one
  progress line as it starts and one as it ends, outside those bytes;
- a small fixpoint replay, serial and parallel, judges the same, with a
  difference injected into one Stage 2 invocation reported in both;
- the recognizer's worker processes run the sawc2 their parent chose (a
  logging wrapper here, the twin under the fixpoint lane), and never rebuild
  one handed down to them, however stale it looks;
- `sawc2 lex @LIST` frames each listed file exactly as the single-file
  commands print it, and under the twin a difference in one listed file is
  reported naming it;
- in the fixpoint lane's default mode the generator's and mutator's
  candidate texts lex with Stage 2 alone and every other text through the
  twin, which still catches a difference on a case text; in full mode the
  candidates go through the twin too.

Each injection goes through a wrapper written under `.build/`, put where the
lanes expect sawc2 or where the twin expects Stage 2; nothing tracked changes.
"""
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixpoint"))
sys.path.append(os.path.join(REPO, "tools"))

import gate_jobs  # noqa: E402

OUT = os.path.join(REPO, ".build", "parallel-order")
MARK = "INJECTED\tparallel-order"
# The stage-lane steps compared, and the call whose output the wrapper alters.
STAGE_STEPS = ("golden", "grammar_lint", "coro")
STAGE_INJECTED = ("coro", "--dump")
# The fixpoint replay's lanes, and the Stage 2 call the wrapper alters.
FIXPOINT_LANES = ("golden", "coro")
FIXPOINT_INJECTED = ("lex", "--kinds")

# The wrapper: runs the binary PARALLEL_ORDER_REAL names and passes its answer
# on, except that a call beginning with PARALLEL_ORDER_MATCH gets MARK as a line
# of its standard output, after the first FILE line, or at the end.
WRAPPER = r'''import os, subprocess, sys
args = sys.argv[1:]
r = subprocess.run([os.environ["PARALLEL_ORDER_REAL"]] + args, capture_output=True)
out = r.stdout
if args[:len(os.environ["PARALLEL_ORDER_MATCH"].split())] == os.environ["PARALLEL_ORDER_MATCH"].split():
    lines = out.split(b"\n")
    at = next((k + 1 for k, line in enumerate(lines) if line.startswith(b"FILE\t")), len(lines))
    out = b"\n".join(lines[:at] + [%r.encode()] + lines[at:])
sys.stdout.buffer.write(out)
sys.stderr.buffer.write(r.stderr)
sys.exit(r.returncode)
''' % MARK


# (cpus, SAW_GATE_JOBS or None, the expected worker count, or None for an error).
KNOB_CASES = (
    (16, None, 12),
    (16, "1", 1),
    (16, "5", 5),
    (16, "12", 12),
    (16, "64", 12),
    (1, None, 1),
    (2, None, 1),
    (3, None, 2),
    (4, "4", 3),
    (16, "0", None),
    (16, "many", None),
)


def check_knob(failures):
    for cpus, value, want in KNOB_CASES:
        environ = {} if value is None else {gate_jobs.VARIABLE: value}
        try:
            got = gate_jobs.jobs(environ, cpus)
        except SystemExit:
            got = None
        if got != want:
            failures.append("parallel order: SAW_GATE_JOBS=%s on %d cores gives %s, expected %s"
                            % (value, cpus, got, want if want is not None else "an error"))
    if gate_jobs.child_env(3, {})[gate_jobs.VARIABLE] != "3":
        failures.append("parallel order: child_env does not hand the child its count")
    check_tokens(failures)
    return len(KNOB_CASES)


def check_tokens(failures):
    """A new budget of four is this process's own token and three more, and a
    pool on it never runs more than four at once."""
    saved = {k: os.environ.get(k) for k in (gate_jobs.TOKENS, gate_jobs.VARIABLE)}
    os.environ.pop(gate_jobs.TOKENS, None)
    os.environ[gate_jobs.VARIABLE] = "4"
    try:
        with gate_jobs.budget():
            held = []
            while len(held) < 8:
                token = gate_jobs.try_acquire()
                if token is None:
                    break
                held.append(token)
            for token in held:
                gate_jobs.release(token)
            if len(held) != 3:
                failures.append("parallel order: a budget of 4 lends %d tokens beside its own, expected 3"
                                % len(held))
            peak = pool_peak()
            if not 2 <= peak <= 4:
                failures.append("parallel order: a pool on a budget of 4 ran %d at once, expected 2 to 4" % peak)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def pool_peak():
    lock = threading.Lock()
    busy = [0, 0]

    def work(_):
        with lock:
            busy[0] += 1
            busy[1] = max(busy[1], busy[0])
        time.sleep(0.02)
        with lock:
            busy[0] -= 1

    gate_jobs.map_ordered(work, range(40))
    return busy[1]


def write_wrapper():
    os.makedirs(OUT, exist_ok=True)
    script = os.path.join(OUT, "inject.py")
    with open(script, "w") as fh:
        fh.write(WRAPPER)
    wrapper = os.path.join(OUT, "sawc2-inject")
    with open(wrapper, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script))
    os.chmod(wrapper, 0o755)
    return wrapper


class Injecting:
    """PARALLEL_ORDER_REAL and PARALLEL_ORDER_MATCH set for the block, which
    the wrapper reads in every process the block starts, and restored after."""

    def __init__(self, real, match):
        self.values = {"PARALLEL_ORDER_REAL": real, "PARALLEL_ORDER_MATCH": " ".join(match)}

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.values}
        os.environ.update(self.values)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def stage_output(failures, R, wrapper, budget):
    """Everything run.py would print for STAGE_STEPS at `budget` workers, its
    progress lines apart: those are checked, never compared."""
    steps = [R.STEP_BY_NAME[name] for name in STAGE_STEPS]
    progress = io.StringIO()
    _, results = R.run_steps(steps, sawc2=wrapper, budget=budget, progress=progress, label="pin")
    check_progress(failures, budget, progress.getvalue(),
                   {step.name: bool(r["failures"]) for step, r in results})
    streams = b"".join(r["stdout"] + r["stderr"] for _, r in results)
    return streams.decode("utf-8", "replace") + R.render(R.merge(None, results))


def check_progress(failures, budget, text, fails):
    """Each step in `fails` writes one started line and then one line ending
    it, `failed` when `fails` says it fails and `finished` otherwise."""
    lines = text.split("\n")[:-1]
    for name, failing in sorted(fails.items()):
        start = [k for k, line in enumerate(lines) if line == "pin: started %s" % name]
        end_verb = "failed" if failing else "finished"
        ends = [k for k, line in enumerate(lines) if line.startswith("pin: %s %s (" % (end_verb, name))
                and line.endswith(" s)")]
        others = [line for line in lines if line.split(" ")[2:3] == [name]
                  and not line.startswith(("pin: started ", "pin: %s " % end_verb))]
        if len(start) != 1 or len(ends) != 1 or start[0] > ends[0] or others:
            failures.append("parallel order: at %d workers the step %s wrote %d started and %d %s progress lines"
                            "%s, expected one of each in that order"
                            % (budget, name, len(start), len(ends), end_verb,
                               " and %r" % others[0] if others else ""))
    if len(lines) != 2 * len(fails):
        failures.append("parallel order: at %d workers the steps wrote %d progress lines, expected %d"
                        % (budget, len(lines), 2 * len(fails)))


def check_stage_steps(failures, R, wrapper, budget):
    with Injecting(R.build.SAWC2, STAGE_INJECTED):
        serial = stage_output(failures, R, wrapper, 1)
        parallel = stage_output(failures, R, wrapper, budget)
    compare(failures, "the steps %s" % ", ".join(STAGE_STEPS), serial, parallel)
    if not any(MARK.split("\t")[0] in line and line.startswith("coro golden ") for line in serial.split("\n")):
        failures.append("parallel order: the failure injected into `sawc2 %s` is not reported"
                        % " ".join(STAGE_INJECTED))


def fixpoint_output(F, wrapper, budget):
    """The fixpoint judgment of FIXPOINT_LANES at `budget` workers, without
    the timings."""
    failures, counts = [], {}
    out = os.path.join(OUT, "fixpoint-%d" % budget)
    os.makedirs(out, exist_ok=True)
    records = F.replay_lanes(failures, counts, lanes=FIXPOINT_LANES, new=wrapper, out=out, budget=budget)
    F.judge(failures, counts, records)
    lines = failures + ["%s %s" % (n, key) for key, n in sorted(counts.items()) if not key.startswith("seconds")]
    return "".join(line + "\n" for line in lines)


def check_fixpoint(failures, F, wrapper, budget):
    with Injecting(F.build.STAGE2, FIXPOINT_INJECTED):
        serial = fixpoint_output(F, wrapper, 1)
        parallel = fixpoint_output(F, wrapper, budget)
    compare(failures, "the fixpoint replay of %s" % ", ".join(FIXPOINT_LANES), serial, parallel)
    want = "fixpoint mismatch: sawc2 %s: " % " ".join(FIXPOINT_INJECTED)
    if not any(line.startswith(want) for line in serial.split("\n")):
        failures.append("parallel order: the difference injected into Stage 2's `sawc2 %s` is not reported"
                        % " ".join(FIXPOINT_INJECTED))


def compare(failures, what, serial, parallel):
    if serial == parallel:
        return
    a, b = serial.split("\n"), parallel.split("\n")
    for k in range(max(len(a), len(b))):
        x = a[k] if k < len(a) else "<end>"
        y = b[k] if k < len(b) else "<end>"
        if x != y:
            failures.append("parallel order: %s print differently, serial and parallel, at line %d: %r, then %r"
                            % (what, k + 1, x[:120], y[:120]))
            return


def run():
    import fixpoint_lane as F
    import run as R
    failures = []
    counts = {"parallel order knob cases": check_knob(failures)}
    budget = gate_jobs.jobs()
    wrapper = write_wrapper()
    check_stage_steps(failures, R, wrapper, budget)
    check_fixpoint(failures, F, wrapper, budget)
    counts["parallel order comparisons"] = 2
    counts["handed-down binary checks"] = check_handed_down(failures, R)
    counts["lex list checks"] = check_lex_list(failures, F, R.build, wrapper)
    counts["candidate text checks"] = check_candidates(failures, F, R.build, wrapper)
    return failures, counts


def check_candidates(failures, F, build, wrapper):
    """Candidate-text workers lex with SAWC2_CANDIDATE_BINARY when a runner
    sets it (the fixpoint lane's default mode) and with the chosen sawc2
    otherwise (full mode); the generator and the mutator are such workers;
    and in default mode a Stage 2 difference on a case text is still caught."""
    import cases
    import lexdump
    import recognize
    work = os.path.join(OUT, "candidates")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    logs = {}
    wrappers = {}
    for name in ("chosen", "candidate"):
        logs[name] = os.path.join(work, name + ".log")
        wrappers[name] = os.path.join(work, "sawc2-" + name)
        with open(wrappers[name], "w") as fh:
            fh.write('#!/bin/sh\necho "$*" >> "%s"\nexec "%s" "$@"\n' % (logs[name], build.STAGE2))
        os.chmod(wrappers[name], 0o755)
    paths = [os.path.join(COMPILER, "tests", "lex", name) for name in WORKER_FILES[:2]]
    saved = (build.SAWC2, list(lexdump._built), os.environ.get("SAWC2_CANDIDATE_BINARY"))

    def calls(name):
        if not os.path.exists(logs[name]):
            return 0
        with open(logs[name]) as fh:
            return sum(1 for _ in fh)

    try:
        build.SAWC2 = wrappers["chosen"]
        lexdump._built[:] = []
        for candidates, default_mode, want in ((True, True, "candidate"), (False, True, "chosen"),
                                               (True, False, "chosen")):
            for log in logs.values():
                if os.path.exists(log):
                    os.remove(log)
            if default_mode:
                os.environ["SAWC2_CANDIDATE_BINARY"] = wrappers["candidate"]
            else:
                os.environ.pop("SAWC2_CANDIDATE_BINARY", None)
            recognize.check_paths(paths, jobs=2) if not candidates else recognize.run_workers(
                [recognize.__file__, "--worker", "--grammar", recognize.extract.GRAMMAR], paths, 2, candidates=True)
            other = "chosen" if want == "candidate" else "candidate"
            if calls(want) == 0 or calls(other) != 0:
                failures.append("parallel order: %s workers in %s mode lexed %d times with the %s sawc2 and %d "
                                "with the %s one, expected only the %s one"
                                % ("candidate-text" if candidates else "other", "default" if default_mode else "full",
                                   calls(want), want, calls(other), other, want))
        # A difference on a case text, in default mode, through the twin.
        log = os.path.join(work, "twin-log")
        os.makedirs(log)
        twin = os.path.join(work, "sawc2-twin")
        with open(twin, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, F.TWIN))
        os.chmod(twin, 0o755)
        build.SAWC2 = twin
        lexdump._built[:] = []
        os.environ["SAWC2_CANDIDATE_BINARY"] = build.STAGE2
        injected = {"FIXPOINT_REF": build.STAGE1, "FIXPOINT_NEW": wrapper, "FIXPOINT_LOG": log,
                    "PARALLEL_ORDER_REAL": build.STAGE2, "PARALLEL_ORDER_MATCH": "lex"}
        before = {k: os.environ.get(k) for k in injected}
        os.environ.update(injected)
        try:
            cases.evaluate_files([os.path.join(cases.GOLDEN, "strings.saw")], jobs=2)
        finally:
            for k, v in before.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        records = []
        for path in glob.glob(os.path.join(log, "*.json")):
            with open(path, encoding="utf-8") as fh:
                records.append(json.load(fh))
        judged = []
        F.judge(judged, {}, records)
        if not any(line.startswith("fixpoint mismatch: sawc2 lex ") for line in judged):
            failures.append("parallel order: in default mode a Stage 2 difference on a case text is not caught "
                            "(%d twin records)" % len(records))
    finally:
        build.SAWC2, lexdump._built[:] = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("SAWC2_CANDIDATE_BINARY", None)
        else:
            os.environ["SAWC2_CANDIDATE_BINARY"] = saved[2]
    for module in ("generate.py", "negative.py"):
        with open(os.path.join(COMPILER, "tests", "grammar", module), encoding="utf-8") as fh:
            text = fh.read()
        if text.count("recognize.run_workers(") != text.count("candidates=True)"):
            failures.append("parallel order: %s starts recognizer workers that are not marked as lexing "
                            "candidate texts" % module)
    return 5


# Files whose dumps the list check compares: plain tokens, doc trivia, lex
# errors, and a path that does not exist.
LIST_FILES = ("comments.saw", "doc_comments.saw", "error_binary_digit.saw", "no_such_file.saw")


def check_lex_list(failures, F, build, wrapper):
    """`sawc2 lex @LIST` prints, per listed file, exactly what `sawc2 lex FILE`
    and `sawc2 lex --docs FILE` print, with their statuses; lexdump reads it
    back as it reads those; and under the twin a Stage 2 difference in one
    listed file is reported naming that file."""
    import lexdump
    work = os.path.join(OUT, "lex-list")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    paths = [os.path.join(COMPILER, "tests", "lex", name) for name in LIST_FILES]
    listing = os.path.join(work, "list.txt")
    with open(listing, "w") as fh:
        fh.write("".join(p + "\n" for p in paths))
    kinds = subprocess.run([build.SAWC2, "lex", "--kinds"], capture_output=True, text=True).stdout.split()
    framing = [k for k in kinds if k in ("FILE", "DOCS", "END")]
    if framing:
        failures.append("parallel order: token kinds %s collide with `sawc2 lex @LIST`'s frame lines" % framing)
    batched = lexdump.frames(subprocess.run([build.SAWC2, "lex", "@" + listing], capture_output=True)
                             .stdout.decode("utf-8"))
    for path in paths:
        single = []
        for flags in ((), ("--docs",)):
            r = subprocess.run([build.SAWC2, "lex"] + list(flags) + [path], capture_output=True)
            single += [r.returncode, r.stdout.decode("utf-8")]
        if batched.get(path) != tuple(single):
            failures.append("parallel order: `sawc2 lex @LIST` frames %s as %r, the single-file commands print %r"
                            % (os.path.basename(path), batched.get(path), tuple(single)))
    # The twin, with Stage 2 altered in the first listed file's frame, over
    # the files that exist: Stage 0's std and the new one word a failed open
    # differently, which is not this check's concern.
    paths = paths[:-1]
    with open(listing, "w") as fh:
        fh.write("".join(p + "\n" for p in paths))
    log = os.path.join(work, "log")
    os.makedirs(log)
    twin = os.path.join(work, "sawc2-twin")
    with open(twin, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, F.TWIN))
    os.chmod(twin, 0o755)
    env = dict(os.environ, FIXPOINT_REF=build.STAGE1, FIXPOINT_NEW=wrapper, FIXPOINT_LOG=log,
               PARALLEL_ORDER_REAL=build.STAGE2, PARALLEL_ORDER_MATCH="lex @" + listing, SAW_GATE_JOBS="1")
    subprocess.run([twin, "lex", "@" + listing], capture_output=True, env=env)
    records = []
    for path in glob.glob(os.path.join(log, "*.json")):
        with open(path, encoding="utf-8") as fh:
            records.append(json.load(fh))
    judged, counts = [], {}
    F.judge(judged, counts, records)
    want = "fixpoint mismatch: sawc2 lex %s (listed in sawc2 lex @%s): " % (paths[0], listing)
    if len(judged) != 1 or not judged[0].startswith(want) or counts.get("fixpoint listed files compared") != len(paths):
        failures.append("parallel order: a Stage 2 difference in one listed file is reported as %r with %r, "
                        "expected one mismatch naming %s" % (judged, counts, os.path.basename(paths[0])))
    return len(LIST_FILES) + 2


# The files the worker check lexes; each is lexed twice, for tokens and docs.
WORKER_FILES = ("comments.saw", "directives.saw", "compound_locals.saw", "borrow_keyword.saw")


def check_handed_down(failures, R):
    """Under a logging wrapper as the chosen sawc2, the recognizer's workers'
    calls are logged; and with the wrapper looking older than its sources and
    handed down, they are logged again and nothing rebuilds Stage 1 or 2."""
    import lexdump
    import recognize
    build = R.build
    paths = [os.path.join(COMPILER, "tests", "lex", name) for name in WORKER_FILES]
    log = os.path.join(OUT, "worker-calls.log")
    logging = os.path.join(OUT, "sawc2-logging")
    with open(logging, "w") as fh:
        fh.write('#!/bin/sh\necho "$*" >> "%s"\nexec "%s" "$@"\n' % (log, build.SAWC2))
    os.chmod(logging, 0o755)
    saved = (build.SAWC2, list(lexdump._built), os.environ.get("SAWC2_BINARY"))
    stamps = [os.path.getmtime(p) for p in (build.STAGE1, build.STAGE2) if os.path.exists(p)]
    try:
        for stale in (False, True):
            if os.path.exists(log):
                os.remove(log)
            build.SAWC2 = logging
            lexdump._built[:] = []
            if stale:
                os.utime(logging, (0, 0))
                os.environ["SAWC2_BINARY"] = logging
            recognize.check_paths(paths, jobs=2)
            calls = 0
            if os.path.exists(log):
                with open(log) as fh:
                    calls = sum(1 for _ in fh)
            if calls < 2 * len(paths):
                failures.append("parallel order: the recognizer's workers made %d calls through the %s sawc2 "
                                "their parent chose, expected at least %d"
                                % (calls, "stale" if stale else "fresh", 2 * len(paths)))
    finally:
        build.SAWC2, lexdump._built[:] = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("SAWC2_BINARY", None)
        else:
            os.environ["SAWC2_BINARY"] = saved[2]
    if [os.path.getmtime(p) for p in (build.STAGE1, build.STAGE2) if os.path.exists(p)] != stamps:
        failures.append("parallel order: a stale sawc2 handed down to the recognizer's workers was rebuilt")
    return 2


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("parallel order: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

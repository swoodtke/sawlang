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
  difference injected into one Stage 2 invocation reported in both.

Each injection goes through a wrapper written under `.build/`, put where the
lanes expect sawc2 or where the twin expects Stage 2; nothing tracked changes.
"""
import io
import os
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
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("parallel order: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

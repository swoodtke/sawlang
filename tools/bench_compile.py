#!/usr/bin/env python3
"""The compile-time benchmark (SL-955): five fixed builds, timed by
`sawc build --time-stages`, as a Markdown table for a tracker comment.

    tools/bench_compile.py [--runs N] [--sawc PATH] [--json FILE] [--no-lock]

The builds: sawc's own build at -O2 and at -O0 (the argument list of
compiler/tools/build.py's `driver_arguments`), Blade at -O2 (tools/blade_lane.py's
`blade_build_arguments`), hello at -O0 and the largest corpus program at -O0.
Each runs N times; a cell is the median over the runs, and `total` also gets
its min and max. Outputs go under `.build/bench/`. The run holds the suite lock
(`--no-lock` skips it and the header says so), since the numbers mean nothing
while something else compiles. Run by hand, and post the table to SL-955.
"""
import argparse
import datetime
import json
import os
import platform
import re
import statistics
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import blade_lane  # noqa: E402
import build  # noqa: E402
import child_groups  # noqa: E402

BENCH_DIR = os.path.join(build.BUILD_DIR, "bench")
HELLO = os.path.join(REPO, "compiler", "tests", "run", "hello.saw")
LARGEST = os.path.join(REPO, "tests", "corpus", "coro_inline_catch_loop_exit_in_child_positions.saw")
BUILD_TIMEOUT_S = 1800
SUITE_LOCK = os.path.join(REPO, "tools", "suite_lock.sh")
TIME_LINE = re.compile(r"^time: (.+) ([0-9]+(?:\.[0-9]+)?) ms$")
TIME_STAGES = "--time-stages"


def program_arguments(sawc, entry, opt, out):
    """The argv for a plain program at `opt`, timed."""
    return [sawc, "build", TIME_STAGES, opt, entry, "-o", out]


def builds(sawc):
    """(column name, argv) for each benchmark build, in table order."""
    def out(name):
        return os.path.join(BENCH_DIR, name)
    return [
        ("sawc -O2", build.driver_arguments(sawc, out("sawc_o2"), "-O2", [TIME_STAGES])),
        ("sawc -O0", build.driver_arguments(sawc, out("sawc_o0"), "-O0", [TIME_STAGES])),
        ("blade -O2", blade_lane.blade_build_arguments(out("blade"), sawc, [TIME_STAGES, "-O2"])),
        ("hello -O0", program_arguments(sawc, HELLO, "-O0", out("hello"))),
        ("largest corpus -O0", program_arguments(sawc, LARGEST, "-O0", out("largest"))),
    ]


def parse_times(text):
    """[(step, ms)] in the order `--time-stages` printed them."""
    rows = []
    for line in text.splitlines():
        m = TIME_LINE.match(line.strip())
        if m:
            rows.append((m.group(1), float(m.group(2))))
    return rows


def run_once(argv):
    """The parsed times of one build; raises RuntimeError when it fails or prints none."""
    proc = child_groups.start(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors="replace")
    try:
        out, _ = proc.communicate(timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        proc.communicate()
        raise RuntimeError("timed out: %s" % " ".join(argv))
    finally:
        child_groups.forget(proc)
    if proc.returncode != 0:
        raise RuntimeError("exit %d: %s\n%s" % (proc.returncode, " ".join(argv), out[-1500:]))
    rows = parse_times(out)
    if not any(step == "total" for step, _ in rows):
        raise RuntimeError("no `time: total` line from %s" % " ".join(argv))
    return rows


def summarize(runs):
    """{"steps": {step: median}, "order": [step...], "total": {median, min, max}}
    for one build's list of runs (each a [(step, ms)])."""
    order = []
    values = {}
    for rows in runs:
        for step, ms in rows:
            if step == "total":
                continue
            if step not in values:
                order.append(step)
                values[step] = []
            values[step].append(ms)
    totals = [dict(rows)["total"] for rows in runs]
    return {"order": order,
            "steps": {step: statistics.median(v) for step, v in values.items()},
            "total": {"median": statistics.median(totals), "min": min(totals), "max": max(totals)}}


def merged_order(summaries):
    """Every step of any build, in pipeline order: each build's own order,
    merged so a step keeps its place relative to the steps it shares."""
    order = []
    for summary in summaries:
        previous = None
        for step in summary["order"]:
            if step not in order:
                at = order.index(previous) + 1 if previous in order else len(order)
                order.insert(at, step)
            previous = step
    return order


def format_table(names, summaries):
    """The Markdown table: a column per build, a row per step (blank where a
    build lacks it), then `total` (median) and `total min-max`."""
    def cell(value):
        return "" if value is None else "%.1f" % value
    lines = ["| step (ms) | " + " | ".join(names) + " |",
             "|---|" + "---:|" * len(names)]
    for step in merged_order(summaries):
        lines.append("| %s | " % step + " | ".join(cell(s["steps"].get(step)) for s in summaries) + " |")
    lines.append("| **total** | " + " | ".join("**%.1f**" % s["total"]["median"] for s in summaries) + " |")
    lines.append("| total min-max | " + " | ".join("%.1f-%.1f" % (s["total"]["min"], s["total"]["max"])
                                                   for s in summaries) + " |")
    return "\n".join(lines)


def load_average():
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def header(commit, date, machine, load_before, load_after, runs, locked, sawc):
    def show(load):
        return "n/a" if load is None else "%.2f" % load
    lines = ["Commit %s, %s, %s, load (1 min) %s before / %s after, %d run%s each (median), sawc `%s`%s"
             % (commit, date, machine, show(load_before), show(load_after), runs, "" if runs == 1 else "s",
                os.path.relpath(sawc, REPO) if sawc.startswith(REPO) else sawc,
                "" if locked else ", suite lock NOT held (--no-lock)")]
    return "\n".join(lines)


def git_commit():
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def lock(action, *what):
    # The lock's chatter goes to stderr so stdout is only the table.
    r = subprocess.run(["sh", SUITE_LOCK, action] + list(what), cwd=REPO, stdout=sys.stderr)
    if r.returncode != 0:
        raise RuntimeError("suite lock %s failed (exit %d)" % (action, r.returncode))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--sawc", default=build.SAWC)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--no-lock", action="store_true", help="skip the suite lock")
    args = ap.parse_args()
    if args.runs < 1:
        ap.error("--runs takes at least 1")
    sawc = os.path.abspath(args.sawc)
    os.makedirs(BENCH_DIR, exist_ok=True)
    child_groups.install()
    if not args.no_lock:
        lock("acquire", "--yield-to-gate", "bench_compile")
    try:
        cores = os.cpu_count() or 1
        load_before = load_average()
        if load_before is not None and load_before > cores / 2:
            print("warning: 1-minute load %.2f is above half the %d cores; the numbers are noisy"
                  % (load_before, cores), file=sys.stderr)
        names, summaries, raw = [], [], {}
        for name, argv in builds(sawc):
            print("bench: %s" % name, file=sys.stderr, flush=True)
            runs = [run_once(argv) for _ in range(args.runs)]
            names.append(name)
            summaries.append(summarize(runs))
            raw[name] = {"argv": argv, "runs": [[list(r) for r in rows] for rows in runs]}
        load_after = load_average()
        if load_after is not None and load_after > cores / 2:
            print("warning: 1-minute load %.2f after the runs is above half the %d cores"
                  % (load_after, cores), file=sys.stderr)
    finally:
        if not args.no_lock:
            lock("release")
    machine = "%s %s, %d cores" % (platform.system(), platform.machine(), cores)
    date = datetime.date.today().isoformat()
    commit = git_commit()
    print(header(commit, date, machine, load_before, load_after, args.runs, not args.no_lock, sawc))
    print()
    print(format_table(names, summaries))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"commit": commit, "date": date, "machine": machine, "cores": cores,
                       "load_before": load_before, "load_after": load_after, "runs": args.runs,
                       "locked": not args.no_lock, "builds": raw}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The compile-time benchmark (SL-955): five fixed builds, timed by
`sawc build --time-stages`, as a Markdown table for a tracker comment.

    tools/bench_compile.py [--runs N] [--sawc PATH] [--json FILE] [--no-lock] [--cache | --front-cache]

The builds: sawc's own build at -O2 and at -O0 (the argument list of
compiler/tools/build.py's `driver_arguments`), Blade at -O2 (tools/blade_lane.py's
`blade_build_arguments`), hello at -O0 and the largest corpus program at -O0.
Each runs N times; a cell is the median over the runs, and `total` also gets
its min and max. Outputs go under `.build/bench/`, and no build takes an
object from the object cache or std's front end from the std front cache, so
a split build under `SAWC_CODEGEN_UNITS` measures its compile. The run holds the suite lock
(`--no-lock` skips it and the header says so), since the numbers mean nothing
while something else compiles. Run by hand, and post the table to SL-955.

`--cache` measures the object cache instead (`cache_builds`): each split build
of a copy of its sources with a fresh cache under `.build/bench/`, then again
with nothing changed, then after each of tools/unit_stability.py's edits to
one module, with the whole-module build for reference, the std front cache
off.

`--front-cache` measures the std front cache (`front_runs`): hello, Blade
whole and split, sawc split with its objects cached, and the largest corpus
program, each with the cache off, cold and warm, on a cache under
`.build/bench/`.
"""
import argparse
import collections
import datetime
import json
import os
import platform
import re
import shutil
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


def run_once(argv, cwd=REPO, env=None):
    """The parsed times of one build, with the object cache and the std front
    cache off unless `env` says otherwise; raises RuntimeError when it fails
    or prints none."""
    proc = child_groups.start(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors="replace",
                              env=env or dict(os.environ, SAWC_OBJECT_CACHE="off", SAWC_FRONT_CACHE="off"))
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


# The object cache's builds (`--cache`): a name, tools/unit_stability.py's
# program, the speed, the codegen units, and the unit_stability cases whose
# edits are measured after the warm build.
CacheBuild = collections.namedtuple("CacheBuild", "name program speed units edits")
CACHE_BUILDS = (
    CacheBuild("sawc -O2 split thin", "sawc", "-O2", "module", ("sawc-body", "sawc-string", "sawc-new-call")),
    CacheBuild("sawc -O0 split", "sawc", "-O0", "module", ("sawc-body", "sawc-string", "sawc-new-call")),
    CacheBuild("blade -O2 split thin", "blade", "-O2", "module", ("blade-body", "blade-string")),
    CacheBuild("sawc -O2 whole", "sawc", "-O2", "1", ()),
    CacheBuild("blade -O2 whole", "blade", "-O2", "1", ()),
)
CACHED_UNIT = re.compile(r"^clang unit \S+ cached$")


def cache_arguments(sawc, program, speed, units, out):
    """The argv of a timed build of `program`'s copy, run from the copy."""
    argv = [sawc, "build", TIME_STAGES, speed, "--codegen-units=" + units, "--std-root", "std"]
    for name, rel in program.packages:
        argv += ["--module-path", "%s=%s" % (name, rel)]
    return argv + [program.entry, "-o", out]


def units_compiled(rows):
    """(units compiled, units) of a split build's parsed times."""
    units = [step for step, _ in rows if step.startswith("clang unit ")]
    return len([u for u in units if not CACHED_UNIT.match(u)]), len(units)


def cache_runs(sawc, spec, runs):
    """{case: [rows]} of `runs` passes over one CACHE_BUILDS entry: a cold
    build into a fresh cache, a warm one with nothing changed, and one after
    each edit, applied in the copy and undone after; a whole-module build is
    its cold build alone."""
    import unit_stability
    program = unit_stability.PROGRAMS[spec.program]
    root = os.path.join(BENCH_DIR, "cache-" + re.sub(r"[^a-z0-9]+", "-", spec.name))
    unit_stability.copy_program(program, root)
    out = os.path.join(root, "out", "program")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    argv = cache_arguments(sawc, program, spec.speed, spec.units, out)
    cache = os.path.join(root, "object-cache")
    # The std front cache stays off, so these rows measure the object cache
    # alone, as they always have; `--front-cache` measures the other.
    env = dict(os.environ, SAWC_CACHE_DIR=cache, SAWC_FRONT_CACHE="off")
    for name in ("SAWC_OBJECT_CACHE", "SAWC_CACHE_ENTRIES", "SAWC_CODEGEN_UNITS", "SAWC_LTO"):
        env.pop(name, None)
    cases = collections.OrderedDict()
    for _ in range(runs):
        shutil.rmtree(cache, ignore_errors=True)
        cases.setdefault("cold", []).append(run_once(argv, root, env))
        if spec.units == "1":
            continue
        cases.setdefault("warm, no edit", []).append(run_once(argv, root, env))
        for edit in spec.edits:
            case = unit_stability.CASES[edit]
            path = os.path.join(root, case.path)
            with open(path) as fh:
                original = fh.read()
            unit_stability.apply_edit(case, root)
            try:
                cases.setdefault("warm, " + case.about, []).append(run_once(argv, root, env))
            finally:
                with open(path, "w") as fh:
                    fh.write(original)
    return cases


def cache_row(name, case, runs):
    """One row of the cache table: the median total and the medians of
    clang, the link (with dsymutil) and the cache's own work, and the units
    compiled, for one case's runs."""
    summary = summarize(runs)
    steps = summary["steps"]
    link = (steps.get("link", 0.0) + steps.get("clang link", 0.0) + steps.get("dsymutil", 0.0))
    compiled, units = units_compiled(runs[-1])
    return ("| %s | %s | **%.0f** (%.0f-%.0f) | %.0f | %.0f | %s | %s |"
            % (name, case, summary["total"]["median"], summary["total"]["min"], summary["total"]["max"],
               steps.get("clang", 0.0), link,
               "%.0f" % steps["object cache"] if "object cache" in steps else "-",
               "%d of %d" % (compiled, units) if units else "1 of 1"))


def format_cache_table(results):
    """The Markdown table of `--cache`: a row per build and case."""
    lines = ["| build | case | total ms (min-max) | clang | link | object cache | units compiled |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for name, cases in results:
        for case, runs in cases.items():
            lines.append(cache_row(name, case, runs))
    return "\n".join(lines)


# The std front cache's builds (`--front-cache`): a name and the argv maker
# for an output path, and whether the build is split, whose object cache is
# filled first so the rows measure the front cache alone.
FrontBuild = collections.namedtuple("FrontBuild", "name arguments split")


def front_builds(sawc):
    """The `--front-cache` builds, in table order."""
    split = ["--codegen-units=module"]
    return (
        FrontBuild("hello -O0", lambda out: program_arguments(sawc, HELLO, "-O0", out), False),
        FrontBuild("blade -O2 whole",
                   lambda out: blade_lane.blade_build_arguments(out, sawc, [TIME_STAGES, "-O2"]), False),
        FrontBuild("blade -O2 split thin",
                   lambda out: blade_lane.blade_build_arguments(out, sawc, [TIME_STAGES, "-O2"] + split), True),
        FrontBuild("sawc -O2 split thin, objects warm",
                   lambda out: build.driver_arguments(sawc, out, "-O2", [TIME_STAGES] + split), True),
        FrontBuild("largest corpus -O0", lambda out: program_arguments(sawc, LARGEST, "-O0", out), False),
    )


# A `--front-cache` row's cases, in order: the cache off, a cold cache that
# computes std's front end and stores it, and a warm one that loads it.
FRONT_CASES = ("off", "cold", "warm")


def front_runs(spec, runs):
    """{case: [rows]} of `runs` passes over one `front_builds` entry, each on
    a cache of its own under `.build/bench/`: a split build's object cache is
    filled by an untimed build first, then the build runs with the front
    cache off, cold (its images removed) and warm."""
    root = os.path.join(BENCH_DIR, "front-" + re.sub(r"[^a-z0-9]+", "-", spec.name))
    out = os.path.join(root, "program")
    argv = spec.arguments(out)
    cache = os.path.join(root, "cache")
    env = dict(os.environ, SAWC_CACHE_DIR=cache)
    for name in ("SAWC_FRONT_CACHE", "SAWC_OBJECT_CACHE", "SAWC_CACHE_ENTRIES", "SAWC_CODEGEN_UNITS", "SAWC_LTO"):
        env.pop(name, None)
    cases = collections.OrderedDict((case, []) for case in FRONT_CASES)
    for _ in range(runs):
        shutil.rmtree(cache, ignore_errors=True)
        os.makedirs(root, exist_ok=True)
        if spec.split:
            run_once(argv, REPO, env)
        cases["off"].append(run_once(argv, REPO, dict(env, SAWC_FRONT_CACHE="off")))
        shutil.rmtree(os.path.join(cache, "front"), ignore_errors=True)
        cases["cold"].append(run_once(argv, REPO, env))
        cases["warm"].append(run_once(argv, REPO, env))
    return cases


# The steps std's front end and the program's run in, which a row sums.
FRONT_END_STEPS = ("resolve", "typecheck", "asserts", "mir", "verify resolve", "verify typecheck", "verify mir",
                   "eval", "verify eval", "borrowck", "verify borrowck", "drops", "verify drops")


def front_row(name, case, runs):
    """One row of the front cache table: the median total, the front end's
    steps summed, std's front end computed, the cache's load or store, and
    clang with the link."""
    summary = summarize(runs)
    steps = summary["steps"]
    front = sum(steps.get(s, 0.0) for s in FRONT_END_STEPS)
    cache = steps.get("front cache load", steps.get("front cache store"))
    link = sum(steps.get(s, 0.0) for s in ("clang", "link", "clang link", "dsymutil"))
    return ("| %s | %s | **%.0f** (%.0f-%.0f) | %.0f | %s | %s | %.0f |"
            % (name, case, summary["total"]["median"], summary["total"]["min"], summary["total"]["max"], front,
               "%.0f" % steps["std front end"] if "std front end" in steps else "-",
               "-" if cache is None else "%s %.0f" % ("load" if "front cache load" in steps else "store", cache),
               link))


def format_front_table(results):
    """The Markdown table of `--front-cache`: a row per build and case."""
    lines = ["| build | case | total ms (min-max) | front-end steps | std front end | front cache | clang + link |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for name, cases in results:
        for case, runs in cases.items():
            lines.append(front_row(name, case, runs))
    return "\n".join(lines)


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
    ap.add_argument("--cache", action="store_true", help="measure the object cache: cold, warm and after an edit")
    ap.add_argument("--front-cache", action="store_true",
                    help="measure the std front cache: off, cold and warm")
    args = ap.parse_args()
    if args.cache and args.front_cache:
        ap.error("--cache and --front-cache measure one cache each")
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
        names, summaries, raw, cached = [], [], {}, []
        if args.cache:
            for spec in CACHE_BUILDS:
                print("bench: %s" % spec.name, file=sys.stderr, flush=True)
                cases = cache_runs(sawc, spec, args.runs)
                cached.append((spec.name, cases))
                raw[spec.name] = {case: [[list(r) for r in rows] for rows in runs] for case, runs in cases.items()}
        if args.front_cache:
            for spec in front_builds(sawc):
                print("bench: %s" % spec.name, file=sys.stderr, flush=True)
                cases = front_runs(spec, args.runs)
                cached.append((spec.name, cases))
                raw[spec.name] = {case: [[list(r) for r in rows] for rows in runs] for case, runs in cases.items()}
        for name, argv in ([] if args.cache or args.front_cache else builds(sawc)):
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
    if args.cache:
        print(format_cache_table(cached))
    elif args.front_cache:
        print(format_front_table(cached))
    else:
        print(format_table(names, summaries))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"commit": commit, "date": date, "machine": machine, "cores": cores,
                       "load_before": load_before, "load_after": load_after, "runs": args.runs,
                       "locked": not args.no_lock, "builds": raw}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

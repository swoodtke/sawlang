#!/usr/bin/env python3
"""The compiler's cost grows near-linearly in one long construct (SL-970).

    python compiler/tests/complexity/complexity_lane.py [--write [--raise SHAPE=N]... [--add SHAPE=N]...]

Each row of `ceilings.tsv` builds its shape (`shapes.py`) at 2, N and 2N and
takes r = (I(2N) - I(2)) / (I(N) - I(2)), I the instructions a whole `sawc
build --emit-ll` retires, so std's share cancels: linear gives r near 2,
quadratic near 4. A row fails when the median r of CHECK_RUNS passes its
ceiling plus its slack, both measured by `write` over WRITE_RUNS. A row is
added by the unit that makes its shape near-linear, at N = 1,600: ctor returns
with typecheck's argument binding (T1), yields with the coroutine passes (C1-C3).
`check_history` holds the file to its rules against HEAD and HEAD^.
"""
import argparse
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import build  # noqa: E402
import gate_jobs  # noqa: E402
import shapes  # noqa: E402

CEILINGS = os.path.join(HERE, "ceilings.tsv")
WORK = os.path.join(REPO, ".build", "complexity")
CHECK_RUNS = 3
WRITE_RUNS = 7
# A row's slack is twice the spread its WRITE_RUNS measured, and never less.
LEAST_SLACK = 0.1
# `write` lowers a ceiling only by more than this, so rewriting the file with
# nothing changed moves nothing.
HYSTERESIS = 0.03
WALL_RUNS = 5
WALL_ONLY_BELOW = 2.5
WALL_CEILING = 3.0
BUILD_TIMEOUT = 600
# The caches would make one size's build cheaper than another's for reasons
# that have nothing to do with its size.
ENV = dict(os.environ, SAWC_FRONT_CACHE="off", SAWC_OBJECT_CACHE="off")
HEADER = "shape\tN\tceiling\tslack"


class CannotTell(Exception):
    """The counter is there and said nothing readable."""


def read_ceilings(text, where):
    """([(shape, n, ceiling, slack)], [problem]) from the text of a ceilings
    file."""
    rows = []
    problems = []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#") or line == HEADER:
            continue
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] not in shapes.SHAPES or not fields[1].isdigit():
            problems.append("%s:%d is not `SHAPE<TAB>N<TAB>CEILING<TAB>SLACK` over a shape of shapes.py"
                            % (where, number))
            continue
        try:
            ceiling, slack = float(fields[2]), float(fields[3])
        except ValueError:
            problems.append("%s:%d: the ceiling or slack is not a number" % (where, number))
            continue
        if int(fields[1]) <= 2:
            problems.append("%s:%d: N must be above 2, the size the lane subtracts" % (where, number))
            continue
        if slack < LEAST_SLACK:
            problems.append("%s:%d: the slack %.2f is under the least, %.2f" % (where, number, slack, LEAST_SLACK))
            continue
        if fields[0] in seen:
            problems.append("%s:%d: a second row for %s" % (where, number, fields[0]))
            continue
        seen.add(fields[0])
        rows.append((fields[0], int(fields[1]), ceiling, slack))
    return rows, problems


def render(rows):
    """The text of a ceilings file holding `rows`, under this file's comment."""
    with open(CEILINGS, encoding="utf-8") as fh:
        comment = [line for line in fh.read().splitlines() if line.startswith("#")]
    body = ["%s\t%d\t%.2f\t%.2f" % row for row in rows]
    return "\n".join(comment + [HEADER] + body) + "\n"


def _git(*args):
    return subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True, text=True)


def check_history(rows):
    """Problems with `rows` against the ceilings file at HEAD and at HEAD^: a
    row dropped, its N lowered, or, at the same N, its ceiling or its ceiling
    plus slack raised."""
    problems = []
    path = os.path.relpath(CEILINGS, REPO)
    now = {row[0]: row[1:] for row in rows}
    for rev in ("HEAD", "HEAD^"):
        if _git("rev-parse", "--verify", "-q", rev + "^{commit}").returncode != 0:
            continue
        listed = _git("ls-tree", rev, "--", path)
        if listed.returncode != 0:
            problems.append("complexity: git cannot read %s at %s: %s" % (path, rev, listed.stderr.strip()))
            continue
        if not listed.stdout.strip():
            continue
        shown = _git("show", "%s:%s" % (rev, path))
        if shown.returncode != 0:
            problems.append("complexity: git cannot read %s at %s: %s" % (path, rev, shown.stderr.strip()))
            continue
        before, _ = read_ceilings(shown.stdout, "%s:%s" % (rev, path))
        for shape, n, ceiling, slack in before:
            if shape not in now:
                problems.append("complexity: %s drops the row for %s, which %s holds" % (path, shape, rev))
                continue
            n_now, ceiling_now, slack_now = now[shape]
            if n_now < n:
                problems.append("complexity: %s lowers %s's N from %d at %s to %d; a row's N only goes up"
                                % (path, shape, n, rev, n_now))
            elif n_now == n and ceiling_now > ceiling:
                problems.append("complexity: %s raises %s's ceiling from %.2f at %s to %.2f; ceilings only go down"
                                % (path, shape, ceiling, rev, ceiling_now))
            elif n_now == n and ceiling_now + slack_now > ceiling + slack + 1e-9:
                problems.append("complexity: %s raises %s's bound, ceiling plus slack, from %.2f at %s to %.2f"
                                % (path, shape, ceiling + slack, rev, ceiling_now + slack_now))
    return problems


def counter():
    """"instructions" or "wall", the measure this system offers, or None when
    it offers neither; raises CannotTell for a counter that is there and broken.
    macOS counts with `/usr/bin/time -l`, Linux with `perf stat`. Under "wall",
    only a row whose ceiling is under WALL_ONLY_BELOW is checked, by the fastest
    of WALL_RUNS, against WALL_CEILING: time is too noisy for a tighter bound."""
    system = platform.system()
    if system == "Darwin":
        if not os.access("/usr/bin/time", os.X_OK):
            raise CannotTell("/usr/bin/time is missing, so no instruction count can be read")
        return "instructions"
    if system == "Linux":
        if shutil.which("perf") is None:
            return "wall"
        r = subprocess.run(["perf", "stat", "-x,", "-e", "instructions", "--", "true"], capture_output=True, text=True)
        value = _perf_value(r.stderr)
        if value == "absent":
            return "wall"
        if r.returncode != 0 or value is None:
            raise CannotTell("`perf stat -e instructions` exits %d and reports %r" % (r.returncode, r.stderr.strip()))
        return "instructions"
    return None


def _perf_value(stderr):
    """The instruction count of `perf stat -x,` output, "absent" when the
    kernel exposes no counter, or None."""
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) >= 3 and fields[2].startswith("instructions"):
            if fields[0] in ("<not supported>", "<not counted>"):
                return "absent"
            if fields[0].isdigit():
                return int(fields[0])
    return None


def _program(shape, n):
    path = os.path.join(WORK, "%s_%d.saw" % (shape, n))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(shapes.program(shape, n))
    return path


def measure(method, path):
    """The instructions, or the fastest wall time, of building `path`."""
    argv = [build.SAWC, "build", "--emit-ll", path]
    name = os.path.basename(path)
    if method == "wall":
        best = None
        for _ in range(WALL_RUNS):
            began = time.monotonic()
            r = subprocess.run(argv, capture_output=True, env=ENV, timeout=BUILD_TIMEOUT)
            took = time.monotonic() - began
            if r.returncode != 0:
                raise CannotTell("%s: `sawc build --emit-ll` exits %d" % (name, r.returncode))
            best = took if best is None else min(best, took)
        return best
    if platform.system() == "Darwin":
        r = subprocess.run(["/usr/bin/time", "-l"] + argv, capture_output=True, text=True, env=ENV,
                           timeout=BUILD_TIMEOUT)
        m = re.search(r"^\s*(\d+)\s+instructions retired", r.stderr, re.M)
        count = int(m.group(1)) if m else None
    else:
        r = subprocess.run(["perf", "stat", "-x,", "-e", "instructions", "--"] + argv, capture_output=True,
                           text=True, env=ENV, timeout=BUILD_TIMEOUT)
        value = _perf_value(r.stderr)
        count = value if isinstance(value, int) else None
    if r.returncode != 0:
        raise CannotTell("%s: `sawc build --emit-ll` exits %d" % (name, r.returncode))
    if count is None:
        raise CannotTell("%s: the build's instruction count cannot be read" % name)
    return count


def ratios(method, sizes, runs):
    """{shape: [r, one per run]} for each (shape, N) of `sizes`, each run
    building the shape at 2, N and 2N."""
    os.makedirs(WORK, exist_ok=True)
    paths = {}
    for shape, n in sizes:
        for size in (2, n, 2 * n):
            paths[(shape, size)] = _program(shape, size)
    cells = [(shape, size, k) for shape, n in sizes for k in range(runs) for size in (2, n, 2 * n)]
    # Wall times are measured one at a time, so that the builds do not share
    # the machine with each other.
    values = gate_jobs.map_ordered(lambda cell: measure(method, paths[cell[:2]]), cells,
                                   most=1 if method == "wall" else None)
    got = dict(zip(cells, values))
    out = {}
    for shape, n in sizes:
        out[shape] = []
        for k in range(runs):
            small, at_n, at_2n = got[(shape, 2, k)], got[(shape, n, k)], got[(shape, 2 * n, k)]
            if at_n <= small:
                raise CannotTell("%s: the build at N=%d measures no more than at 2" % (shape, n))
            out[shape].append((at_2n - small) / (at_n - small))
    return out


def run(verbose=False):
    """(failure lines, counts) for run.py."""
    with open(CEILINGS, encoding="utf-8") as fh:
        rows, failures = read_ceilings(fh.read(), os.path.relpath(CEILINGS, REPO))
    failures = ["complexity: " + p for p in failures] + check_history(rows)
    try:
        method = counter()
        if method is None:
            return failures, {"complexity shapes skipped": len(rows)}
        checked = rows
        if method == "wall":
            checked = [row for row in rows if row[2] < WALL_ONLY_BELOW]
        measured = ratios(method, [(shape, n) for shape, n, _, _ in checked], CHECK_RUNS)
    except (CannotTell, subprocess.TimeoutExpired) as why:
        return failures + ["complexity: cannot tell: %s" % why], {"complexity shapes": 0}
    for shape, n, ceiling, slack in checked:
        r = statistics.median(measured[shape])
        bound = WALL_CEILING if method == "wall" else ceiling
        if verbose:
            print("complexity %s at N=%d: median r=%.3f of %s, ceiling %.2f + slack %.2f (%s)" % (
                shape, n, r, " ".join("%.3f" % x for x in measured[shape]), bound, slack, method))
        if r > bound + slack:
            failures.append("complexity %s at N=%d: median r=%.2f passes its ceiling %.2f plus its slack %.2f: a "
                            "stage grew superlinear in one %s construct (compiler/tests/complexity/shapes.py)"
                            % (shape, n, r, bound, slack, shape))
    counts = {"complexity shapes": len(checked)}
    if len(checked) < len(rows):
        counts["complexity shapes skipped"] = len(rows) - len(checked)
    return failures, counts


def write(raises, adds):
    """Measures every row WRITE_RUNS times and rewrites `ceilings.tsv`: a row
    raised or added takes the worst r as its ceiling and twice the spread as
    its slack; any other row is lowered to them only when its ceiling drops by
    more than HYSTERESIS and its ceiling plus slack does not rise, and a row
    whose median passes its bound is refused."""
    with open(CEILINGS, encoding="utf-8") as fh:
        rows, problems = read_ceilings(fh.read(), os.path.relpath(CEILINGS, REPO))
    if problems:
        for p in problems:
            print("complexity: " + p)
        return 1
    if counter() != "instructions":
        print("complexity: --write needs an instruction counter, and this system has none")
        return 1
    sizes = {row[0]: row[1] for row in rows}
    for shape, n in raises.items():
        if shape not in sizes:
            print("complexity: --raise names %s, which has no row; --add one" % shape)
            return 1
        if n <= sizes[shape]:
            print("complexity: --raise %s=%d does not raise its N=%d" % (shape, n, sizes[shape]))
            return 1
        sizes[shape] = n
    for shape, n in adds.items():
        if shape not in shapes.SHAPES or shape in sizes or n <= 2:
            print("complexity: --add %s=%d names no shape of shapes.py without a row, or N is not above 2"
                  % (shape, n))
            return 1
        sizes[shape] = n
    order = [row[0] for row in rows] + [shape for shape in shapes.SHAPES if shape in adds]
    measured = ratios("instructions", [(shape, sizes[shape]) for shape in order], WRITE_RUNS)
    old = {row[0]: row for row in rows}
    refused = 0
    new = []
    for shape in order:
        rs = measured[shape]
        worst = _up(max(rs))
        slack = _up(max(LEAST_SLACK, 2 * (max(rs) - min(rs))))
        spread = "r %.3f-%.3f over %d runs" % (min(rs), max(rs), len(rs))
        if shape not in old or shape in raises:
            new.append((shape, sizes[shape], worst, slack))
            print("complexity %s: N=%d, ceiling %.2f, slack %.2f (%s)" % (shape, sizes[shape], worst, slack, spread))
            continue
        _, n, ceiling, kept = old[shape]
        if statistics.median(rs) > ceiling + kept:
            refused += 1
            new.append(old[shape])
            print("complexity %s at N=%d: median r=%.2f passes its ceiling %.2f plus slack %.2f (%s); a ceiling "
                  "is never raised" % (shape, n, statistics.median(rs), ceiling, kept, spread))
        elif worst < ceiling - HYSTERESIS and worst + slack <= ceiling + kept:
            new.append((shape, n, worst, slack))
            print("complexity %s at N=%d: ceiling %.2f -> %.2f, slack %.2f -> %.2f (%s)"
                  % (shape, n, ceiling, worst, kept, slack, spread))
        else:
            new.append(old[shape])
            print("complexity %s at N=%d: ceiling %.2f and slack %.2f kept (%s)" % (shape, n, ceiling, kept, spread))
    text = render(new)
    with open(CEILINGS, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 1 if refused else 0


def _up(x):
    """`x` rounded up to the hundredths the file records, so a recorded bound
    is never under what was measured."""
    return math.ceil(round(x * 100, 6)) / 100


def _pairs(ap, items, flag):
    out = {}
    for item in items:
        shape, _, n = item.partition("=")
        if not n.isdigit():
            ap.error("%s takes SHAPE=N, not %r" % (flag, item))
        out[shape] = int(n)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="measure every row and record what it earned")
    ap.add_argument("--raise", dest="raises", action="append", default=[], metavar="SHAPE=N",
                    help="with --write, move SHAPE's row to the larger N")
    ap.add_argument("--add", dest="adds", action="append", default=[], metavar="SHAPE=N",
                    help="with --write, add a row for SHAPE at N")
    args = ap.parse_args()
    raises = _pairs(ap, args.raises, "--raise")
    adds = _pairs(ap, args.adds, "--add")
    if (raises or adds) and not args.write:
        ap.error("--raise and --add need --write")
    ok, output = build.build_sawc()
    if not ok:
        print("complexity: sawc does not build: %s" % output.strip().split("\n")[-1])
        return 1
    if args.write:
        try:
            return write(raises, adds)
        except (CannotTell, subprocess.TimeoutExpired) as why:
            print("complexity: cannot tell: %s" % why)
            return 1
    failures, counts = run(verbose=True)
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("complexity: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

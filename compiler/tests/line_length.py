#!/usr/bin/env python3
"""A parse costs time linear in its input, however long its lines are.

    python compiler/tests/line_length.py            run the cells and print the timings

Each cell writes 20,000 items on one line, as call arguments, as a set literal
and as a tuple pattern, and times `sawc2 parse --check` on it against the same
call written one argument per line. The two hold the same tokens, so a parse
linear in its input takes about as long on each, and a cost that grows with a
token's column, such as converting a column back into a byte offset by walking
the line, makes the one-line text hundreds of times slower at this size.

A timing is the fastest of up to ATTEMPTS runs, each parsing the text COPIES
times in one process so that the parse, not the process start, dominates it. A
cell passes when its fastest run is within RATIO of the baseline's.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

WORK = os.path.join(REPO, ".build", "line-length")
ITEMS = 20000
COPIES = 10
ATTEMPTS = 3
# Linear parsing puts a cell near 1x its baseline, a quadratic one at hundreds.
RATIO = 5.0


def items():
    return ["a%d" % i for i in range(ITEMS)]


def in_function(line):
    return "func f() {\n    " + line + "\n}\n"


def baseline():
    """The call, one argument per line: every line is short."""
    return in_function("let x = g(\n        " + ",\n        ".join(items()) + "\n    )")


def cells():
    one_line = ", ".join(items())
    return [
        ("%d call arguments on one line" % ITEMS, in_function("let x = g(" + one_line + ")")),
        ("a set literal of %d elements on one line" % ITEMS,
         in_function("let x = {" + one_line + "}")),
        ("a tuple pattern of %d names on one line" % ITEMS,
         in_function("let (" + one_line + ") = w")),
    ]


def write(name, text):
    path = os.path.join(WORK, name + ".saw")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def timed(path):
    """(seconds, refusal or None) of one process parsing `path` COPIES times."""
    began = time.monotonic()
    r = subprocess.run([build.SAWC2, "parse", "--check"] + [path] * COPIES, capture_output=True)
    took = time.monotonic() - began
    out = r.stdout.decode("utf-8", "replace")
    refused = [line for line in out.split("\n") if line.startswith("ERROR\t")]
    if r.returncode != 0 or refused or out.count("FILE\t") != COPIES:
        return took, refused[0] if refused else "exit %d" % r.returncode
    return took, None


def run(verbose=False):
    """(failure lines, counts) for run.py."""
    os.makedirs(WORK, exist_ok=True)
    failures = []
    base_path = write("baseline", baseline())
    base = None
    for _ in range(ATTEMPTS):
        took, refused = timed(base_path)
        if refused:
            return ["line-length baseline: refused: %s" % refused], {"line-length cells": 0}
        base = took if base is None else min(base, took)
    rows = cells()
    for k, (name, text) in enumerate(rows):
        path = write("cell%d" % k, text)
        best = None
        for _ in range(ATTEMPTS):
            took, refused = timed(path)
            if refused:
                failures.append("line-length cell %s: refused: %s" % (name, refused))
                break
            best = took if best is None else min(best, took)
            # One run within the bound settles it, and one far past it
            # settles the opposite without paying for more.
            if best <= RATIO * base or best > 10 * RATIO * base:
                break
        if best is None:
            continue
        if verbose:
            print("line-length cell %s: %.3fs against %.3fs (%.1fx)"
                  % (name, best, base, best / base))
        if best > RATIO * base:
            failures.append("line-length cell %s: %.3fs, %.0f times the %.3fs of the same "
                            "call one argument per line; a parse must be linear in its "
                            "input, not in its line lengths" % (name, best, best / base, base))
    return failures, {"line-length cells": len(rows)}


def main():
    ok, output = build.build_sawc2()
    if not ok:
        print("line-length: sawc2 does not build: %s" % output.strip().split("\n")[-1])
        return 1
    failures, counts = run(verbose=True)
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("line-length: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

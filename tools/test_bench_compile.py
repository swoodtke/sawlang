#!/usr/bin/env python3
"""tools/bench_compile.py's table and argument lists, with no build run.

    python tools/test_bench_compile.py

Checks the parser and the median on a recorded `--time-stages` sample, the
table's shape and blank cells, and that the benchmark's argument lists for
sawc and Blade are the ones compiler/tools/build.py and tools/blade_lane.py
build.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import bench_compile as bench  # noqa: E402
import blade_lane  # noqa: E402
import build  # noqa: E402

SAMPLE = """hello, world
time: asserts 0.0 ms
time: mir 10.7 ms
time: verify mir 20.4 ms
time: llvm 3.0 ms
time: clang 40.1 ms
time: total 100.0 ms
"""

failures = []


def check(what, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (what, got, want))


def sample_run(scale, with_clang=True):
    rows = bench.parse_times(SAMPLE)
    rows = [(s, ms * scale) for s, ms in rows if with_clang or s != "clang"]
    return rows


rows = bench.parse_times(SAMPLE)
check("parse order", [s for s, _ in rows], ["asserts", "mir", "verify mir", "llvm", "clang", "total"])
check("parse multiword step", dict(rows)["verify mir"], 20.4)

summary = bench.summarize([sample_run(1), sample_run(3), sample_run(2)])
check("median step", summary["steps"]["mir"], 10.7 * 2)
check("total median/min/max", (summary["total"]["median"], summary["total"]["min"], summary["total"]["max"]),
      (200.0, 100.0, 300.0))
check("total is not a step", "total" in summary["steps"], False)

other = bench.summarize([[("mir", 5.0), ("write ll", 1.0), ("total", 9.0)]])
check("merged order", bench.merged_order([summary, other]),
      ["asserts", "mir", "write ll", "verify mir", "llvm", "clang"])

table = bench.format_table(["a", "b"], [summary, other]).splitlines()
check("header", table[0], "| step (ms) | a | b |")
check("separator", table[1], "|---|---:|---:|")
check("row count", len(table), 2 + 6 + 2)
check("blank cell", table[2 + 2], "| write ll |  | 1.0 |")
check("shared cell", table[3], "| mir | 21.4 | 5.0 |")
check("total row", table[-2], "| **total** | **200.0** | **9.0** |")
check("min-max row", table[-1], "| total min-max | 100.0-300.0 | 9.0-9.0 |")

compiler = "/x/sawc"
check("sawc -O2 argv", dict(bench.builds(compiler))["sawc -O2"],
      build.driver_arguments(compiler, os.path.join(bench.BENCH_DIR, "sawc_o2"), "-O2", ["--time-stages"]))
check("sawc argv is link_driver's but timed",
      [a for a in build.driver_arguments(compiler, "o")] ,
      [compiler, "build", "-O2", "--std-root", "std"] + build.package_arguments(build.REPO)
      + [os.path.relpath(build.DRIVER_ENTRY, build.REPO), "-o", "o"])
check("sawc -O0 flag", dict(bench.builds(compiler))["sawc -O0"][3], "-O0")
check("blade argv", dict(bench.builds(compiler))["blade -O2"],
      blade_lane.blade_build_arguments(os.path.join(bench.BENCH_DIR, "blade"), compiler,
                                       ["--time-stages", "-O2"]))
check("blade default argv", blade_lane.blade_build_arguments("o")[:2], [build.SAWC, "build"])
check("five builds", [n for n, _ in bench.builds(compiler)],
      ["sawc -O2", "sawc -O0", "blade -O2", "hello -O0", "largest corpus -O0"])
check("fixed inputs exist", [os.path.exists(bench.HELLO), os.path.exists(bench.LARGEST)], [True, True])

header = bench.header("abc1234", "2026-11-02", "m", 1.0, 2.0, 3, False, "/x/sawc")
check("header names no-lock", "NOT held" in header, True)

for f in failures:
    print("FAIL: " + f)
print("bench_compile: %s" % ("FAIL" if failures else "ok"))
sys.exit(1 if failures else 0)

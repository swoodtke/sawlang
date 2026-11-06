#!/usr/bin/env python3
"""tools/bench_compile.py's table and argument lists, with no build run.

    python tools/test_bench_compile.py

Checks the parser and the median on a recorded `--time-stages` sample, the
table's shape and blank cells, `--cache`'s rows and unit counts,
`--front-cache`'s and `--layers`' rows and builds, and that the benchmark's argument lists
for sawc and Blade are the ones
compiler/tools/build.py and tools/blade_lane.py build.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import bench_compile as bench  # noqa: E402
import blade_lane  # noqa: E402
import build  # noqa: E402
import unit_stability  # noqa: E402

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

CACHE_SAMPLE = """time: split 3.0 ms
time: clang unit -program cached 0.2 ms
time: clang unit std.string 40.0 ms
time: clang unit main cached 0.4 ms
time: object cache 5.0 ms
time: clang 41.0 ms
time: link 20.0 ms
time: dsymutil 4.0 ms
time: total 90.0 ms
"""
cache_rows = bench.parse_times(CACHE_SAMPLE)
check("units compiled", bench.units_compiled(cache_rows), (1, 3))
check("cache row", bench.cache_row("b", "warm", [cache_rows]),
      "| b | warm | **90** (90-90) | 41 | 24 | 5 | 1 of 3 |")
whole_rows = bench.parse_times(SAMPLE)
check("whole-module cache row", bench.cache_row("w", "cold", [whole_rows]),
      "| w | cold | **100** (100-100) | 40 | 0 | - | 1 of 1 |")
check("cache table shape", len(bench.format_cache_table([("b", {"cold": [cache_rows], "warm": [cache_rows]})])
                               .splitlines()), 4)
check("cache argv", bench.cache_arguments("/x/sawc", unit_stability.PROGRAMS["blade"], "-O2", "module", "o")[:7],
      ["/x/sawc", "build", "--time-stages", "-O2", "--codegen-units=module", "--std-root", "std"])
check("cache builds' edits exist", [e for s in bench.CACHE_BUILDS for e in s.edits if e not in unit_stability.CASES],
      [])
check("cache builds' programs match their edits",
      [e for s in bench.CACHE_BUILDS for e in s.edits if unit_stability.CASES[e].program != s.program], [])

FRONT_COLD = """time: std front end 150.0 ms
time: front cache store 60.0 ms
time: resolve 20.0 ms
time: typecheck 30.0 ms
time: clang link 80.0 ms
time: total 340.0 ms
"""
FRONT_WARM = """time: front cache load 45.0 ms
time: resolve 1.0 ms
time: typecheck 2.0 ms
time: clang link 80.0 ms
time: total 150.0 ms
"""
check("front cold row", bench.front_row("h", "cold", [bench.parse_times(FRONT_COLD)]),
      "| h | cold | **340** (340-340) | 50 | 150 | store 60 | 80 |")
check("front warm row", bench.front_row("h", "warm", [bench.parse_times(FRONT_WARM)]),
      "| h | warm | **150** (150-150) | 3 | - | load 45 | 80 |")
check("front off row", bench.front_row("h", "off", [bench.parse_times(SAMPLE)]),
      "| h | off | **100** (100-100) | 31 | - | - | 40 |")
check("front table shape", len(bench.format_front_table(
    [("h", {c: [bench.parse_times(FRONT_WARM)] for c in bench.FRONT_CASES})]).splitlines()), 5)
fronts = bench.front_builds(compiler)
check("front builds", [s.name for s in fronts],
      ["hello -O0", "blade -O2 whole", "blade -O2 split thin", "sawc -O2 split thin, objects warm",
       "largest corpus -O0"])
check("front sawc argv is the driver's, split and timed", fronts[3].arguments("o"),
      build.driver_arguments(compiler, "o", "-O2", ["--time-stages", "--codegen-units=module"]))
check("front blade split argv", fronts[2].arguments("o"),
      blade_lane.blade_build_arguments("o", compiler, ["--time-stages", "-O2", "--codegen-units=module"]))
check("front splits", [s.split for s in fronts], [False, False, True, True, False])

LAYERS_WARM = """time: front cache load 45.0 ms
time: front layer sawlex loaded 5.0 ms
time: front layer program computed 30.0 ms
time: front layers store 2.0 ms
time: front layers join 0.0 ms
time: resolve 10.0 ms
time: clang link 80.0 ms
time: total 190.0 ms
"""
check("layers row", bench.layer_row("s", "warm", [bench.parse_times(LAYERS_WARM)]),
      "| s | warm | **190** (190-190) | 10 | 1 / 1 | load 45 | 2 | 0 | 80 | 1 of 1 |")
check("layers cold row", bench.layer_row("h", "cold", [bench.parse_times(FRONT_COLD)]),
      "| h | cold | **340** (340-340) | 50 | 0 / 0 | computed 150 | - | 0 | 80 | 1 of 1 |")
check("layers split row", bench.layer_row("b", "warm", [cache_rows]),
      "| b | warm | **90** (90-90) | 0 | 0 / 0 | - | - | 41 | 24 | 1 of 3 |")
check("layers argv spells mappings absolute",
      bench.layer_arguments("/x/sawc", unit_stability.PROGRAMS["blade"], "-O2", "module", "o", "/r")[7:9],
      ["--module-path", "blade=/r/blade/src"])
check("layers table shape", len(bench.format_layers_table(
    [("s", {c: [bench.parse_times(LAYERS_WARM)] for c in bench.LAYER_CASES})]).splitlines()), 5)
check("layers builds", [s.name for s in bench.LAYER_BUILDS],
      ["sawc -O2 split thin", "sawc -O0 split", "blade -O2 split thin", "hello -O0", "sawtracker -O2 split thin"])
check("layers builds' edits exist",
      [e for s in bench.LAYER_BUILDS for e in s.edits
       if not e.startswith("append:") and (e not in unit_stability.CASES
                                           or unit_stability.CASES[e].program != s.program)], [])
check("layers appended files exist",
      [e for s in bench.LAYER_BUILDS for e in s.edits if e.startswith("append:") and s.program != "sawtracker"
       and not os.path.exists(os.path.join(REPO, e[len("append:"):]))], [])

header = bench.header("abc1234", "2026-11-02", "m", 1.0, 2.0, 3, False, "/x/sawc")
check("header names no-lock", "NOT held" in header, True)

for f in failures:
    print("FAIL: " + f)
print("bench_compile: %s" % ("FAIL" if failures else "ok"))
sys.exit(1 if failures else 0)

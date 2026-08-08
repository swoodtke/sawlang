#!/usr/bin/env python3
"""Acceptance harness for the in-binary backtrace table (design 158 unit 1).

Two things are checked, and one is measured.

CHECKED — structure, over a coroutine-heavy slice of `examples/`. The table is
what both the panic-time dump and `tools/lldb_saw.py` decode, and a wrong
offset there reads a live frame at the wrong place and prints a confident lie.
So every frame record is validated against the layout report the same compile
produced: the `__state` offset must be a real field of that frame, every child
index must name a frame that exists, every child offset must be the offset of
the `__subN` the transform said is live in that state, and every state with a
child must also carry the call's line.

CHECKED — exact lines, on one fixture. `examples/task_backtrace_nest.saw` is a
known three-frame nest; the walk has to report the three lines a reader would
point at, so they are pinned here by number. (The fixture says so at its top —
editing it means editing this list.)

MEASURED — size. The table is ALWAYS ON, which is a size cost the user
explicitly reserved a veto on, so `--sizes` reports the blob's bytes per
program next to the binary it rides in.

    python tools/test_bt_table.py            # the gates
    python tools/test_bt_table.py --sizes    # the size report
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(ROOT, "sawc", "sawc.py")
EXAMPLES = os.path.join(ROOT, "examples")
sys.path.insert(0, os.path.join(ROOT, "sawc"))

# Coroutine-shaped programs covering every frame shape the encoder has to get
# right: a suspending main, embedded free-function and method sub-frames, a
# spawn root, a generic instantiation, an MT group, and a `borrows`-heavy body.
STRUCTURE_CORPUS = [
    "task_backtrace_nest.saw",
    "task_backtrace_mt.saw",
    "task_backtrace_churn.saw",
    "async_main_nested_sleep.saw",
    "coro_nested_suspend_method.saw",
    "coro_generic_struct_and_method.saw",
    "taskgroup_slot_reuse_o_live.saw",
    "taskgroup_nested_groups.saw",
    "taskgroup_spawn_generic.saw",
]

# The fixture's parked three-frame nest, outermost first: (frame, line).
FIXTURE = "task_backtrace_nest.saw"
FIXTURE_FRAMES = [
    ("worker", 34),      # let n = middle(seed)
    ("middle", 29),      # let r = leaf(n)
    ("leaf", 24),        # sleep(Duration.secs(2))
]


def _sawc(args):
    proc = subprocess.run([sys.executable, SAWC] + args,
                          capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"sawc {' '.join(args)} failed:\n"
                           f"{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def bt_table(path):
    return json.loads(_sawc([path, "--emit-bt-table"]))


def frame_layout(path):
    return json.loads(_sawc([path, "--emit-frame-layout"]))["frames"]


def check_structure(path, verbose):
    """Cross-check one program's table against its own frame-layout report."""
    table = bt_table(path)
    layout = frame_layout(path)
    problems = []
    by_symbol = {f["symbol"]: (i, f) for i, f in enumerate(table["frames"])}

    if len(table["frames"]) != len(layout):
        problems.append(f"table has {len(table['frames'])} frames, the layout "
                        f"report has {len(layout)}")

    for symbol, info in sorted(layout.items()):
        hit = by_symbol.get(symbol)
        if hit is None:
            problems.append(f"{symbol}: in the layout report, absent from the table")
            continue
        index, frame = hit
        if index != info["bt_index"]:
            problems.append(f"{symbol}: table index {index} != bt_index "
                            f"{info['bt_index']} — `__bt_desc` would lie")
        fields = {f["name"]: f for f in info["fields"]}
        if frame["state_field"] != fields["__state"]["offset"]:
            problems.append(f"{symbol}: __state at {frame['state_field']} in "
                            f"the table, {fields['__state']['offset']} in LLVM")
        if len(frame["states"]) != info["states"]:
            problems.append(f"{symbol}: {len(frame['states'])} state entries "
                            f"for {info['states']} states")
        live = {f["live_state"]: f for f in info["fields"]
                if f["kind"] == "sub"}
        for state, entry in enumerate(frame["states"]):
            if entry["child"] < 0:
                if state in live:
                    problems.append(f"{symbol}: state {state} holds "
                                    f"{live[state]['name']} but the table calls "
                                    f"it a leaf")
                continue
            if entry["child"] >= len(table["frames"]):
                problems.append(f"{symbol}: state {state} names frame "
                                f"{entry['child']}, out of range")
                continue
            sub = live.get(state)
            if sub is None:
                problems.append(f"{symbol}: state {state} names a child the "
                                f"layout report says is not live there")
                continue
            if entry["child_offset"] != sub["offset"]:
                problems.append(f"{symbol}: {sub['name']} at "
                                f"{entry['child_offset']}, LLVM says "
                                f"{sub['offset']}")
            if table["frames"][entry["child"]]["symbol"] != sub["callee"]:
                problems.append(
                    f"{symbol}: state {state} points at "
                    f"{table['frames'][entry['child']]['symbol']}, the layout "
                    f"report says {sub['callee']}")
            if not entry["line"]:
                problems.append(f"{symbol}: state {state} is inside a call "
                                f"with no line to print")
    if verbose and not problems:
        print(f"  ok  {os.path.basename(path)} "
              f"({len(table['frames'])} frames, {table['bytes']} bytes)")
    return problems


def check_fixture(verbose):
    """The exact three-frame nest, by line number."""
    table = bt_table(os.path.join(EXAMPLES, FIXTURE))
    by_name = {f["name"]: f for f in table["frames"]}
    problems = []
    for name, line in FIXTURE_FRAMES:
        frame = by_name.get(name)
        if frame is None:
            problems.append(f"fixture: no frame named `{name}`")
            continue
        lines = sorted({s["line"] for s in frame["states"] if s["line"]})
        if line not in lines:
            problems.append(f"fixture: `{name}` has no state on line {line} "
                            f"(has {lines})")
    if table["exec"] is None:
        problems.append("fixture: no runtime descriptor — a debugger could not "
                        "find the task list")
    if verbose and not problems:
        print(f"  ok  {FIXTURE} pins {len(FIXTURE_FRAMES)} frames by line")
    return problems


def sizes(paths):
    print(f"{'program':<44} {'frames':>7} {'table':>8} {'binary':>10} {'%':>6}")
    total_table = 0
    for path in paths:
        name = os.path.relpath(path, ROOT)
        try:
            table = bt_table(path)
        except RuntimeError:
            continue
        out = os.path.join(ROOT, ".build", "scratch", "btsize.bin")
        binary = 0
        try:
            _sawc([path, "-o", out])
            binary = os.path.getsize(out)
        except (RuntimeError, OSError):
            pass
        total_table += table["bytes"]
        share = (100.0 * table["bytes"] / binary) if binary else 0.0
        print(f"{name:<44} {len(table['frames']):>7} {table['bytes']:>8} "
              f"{binary:>10} {share:>5.2f}%")
    print(f"\ntotal table bytes across {len(paths)} programs: {total_table}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", action="store_true",
                    help="report the table's byte cost instead of gating")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    paths = [os.path.join(EXAMPLES, n) for n in STRUCTURE_CORPUS]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("test_bt_table: missing corpus files: "
              + ", ".join(os.path.basename(p) for p in missing),
              file=sys.stderr)
        return 1

    if args.sizes:
        sizes(paths)
        return 0

    problems = []
    for path in paths:
        problems += check_structure(path, args.verbose)
    problems += check_fixture(args.verbose)

    if problems:
        print("test_bt_table: FAILED", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"test_bt_table: ok — {len(paths)} programs cross-checked against "
          f"their frame layouts, {len(FIXTURE_FRAMES)} fixture lines pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main())

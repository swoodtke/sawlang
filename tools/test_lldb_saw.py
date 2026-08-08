#!/usr/bin/env python3
"""Acceptance harness for `tools/lldb_saw.py` (design 158 unit 2).

Drives a real lldb, in batch mode, over a real Saw binary. Two tiers, because
the two need different things from the machine:

STATIC — always run where lldb exists. `saw table` decodes the in-binary
backtrace table out of the FILE and prints every frame, its `__state` offset,
and per state the line it parks on or the child it is inside. This is the whole
format contract plus the two symbol lookups the live walk depends on
(`__saw_bt_vtables` and the task-list head), checked with no process at all.

LIVE — run where the machine will let a debugger launch a process. The program
is `examples/task_backtrace_panic.saw`, which aborts with one task parked three
frames down, so the stop needs no breakpoint and lands at a moment the example
already pins on the in-process side. Same binary, same table, two independent
readers: if they disagree, one of them is wrong about the format.

SKIPS CLEANLY, exit 0, when lldb is absent (it is a platform tool, not a
dependency of this project) — and downgrades to the static tier when lldb is
present but cannot attach, which is the ordinary state of a sandboxed or
un-entitled shell. `tools/gmgate.py` uses the same contract for Guard Malloc.

    python tools/test_lldb_saw.py [-v]
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(ROOT, "sawc", "sawc.py")
SCRIPT = os.path.join(ROOT, "tools", "lldb_saw.py")
FIXTURE = os.path.join(ROOT, "examples", "task_backtrace_panic.saw")
BUILD = os.path.join(ROOT, ".build", "lldb_saw")

# `saw table`, from the file. The lines are the fixture's own — the same ones
# the in-process dump prints there, which is the point of checking both.
WANT_TABLE = [
    "backtrace table v1: 3 frame(s)",
    "panicking_leaf  (task_backtrace_panic.saw",
    "state 1: parked at line 21",
    "panicking_worker  (task_backtrace_panic.saw",
    "state 1: line 26, inside panicking_leaf at +",
    "frame vtable map: __saw_bt_vtables",
    "task list head: saw.static.__saw_bt_head",
]

# `saw tasks` names both live tasks; `saw bt` adds the parked one's frames, in
# innermost-first order.
WANT_TASKS = [
    "2 live task(s)",
    "task group 1 slot 0 gen 1 [st] sleeping",
    "task group 1 slot 1 gen 1",
]
WANT_BT = [
    "task group 1 slot 0 gen 1 [st] sleeping",
    "at task_backtrace_panic.saw:21 in panicking_leaf",
    "at task_backtrace_panic.saw:26 in panicking_worker",
]

LLDB_TIMEOUT_S = 120
LOADED = "saw: `saw tasks`, `saw bt` and `saw table` are available"


def build_fixture(verbose):
    os.makedirs(os.path.dirname(BUILD), exist_ok=True)
    cmd = [sys.executable, SAWC, FIXTURE, "-o", BUILD]
    if verbose:
        print("  " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"building the fixture failed:\n{proc.stdout}\n{proc.stderr}")
    return BUILD


def run_lldb(lldb, binary, commands, verbose):
    cmd = [lldb, "--batch", "--no-lldbinit"]
    for c in commands:
        cmd += ["-o", c]
    cmd += ["--", binary]
    if verbose:
        print("  " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                          timeout=LLDB_TIMEOUT_S)
    return proc.stdout + proc.stderr


def check(out, wants, label):
    """Each expectation in order, so a shuffled backtrace does not pass."""
    problems = []
    cursor = 0
    for want in wants:
        at = out.find(want, cursor)
        if at < 0:
            where = "out of order" if want in out else "missing"
            problems.append(f"{label}: {where} {want!r}")
            continue
        cursor = at + len(want)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    lldb = shutil.which("lldb")
    if lldb is None:
        print("test_lldb_saw: SKIPPED — lldb is not on PATH")
        return 0

    try:
        binary = build_fixture(args.verbose)
    except RuntimeError as e:
        print(f"test_lldb_saw: {e}", file=sys.stderr)
        return 1

    def drive(commands):
        try:
            return run_lldb(lldb, binary, commands, args.verbose)
        except subprocess.TimeoutExpired:
            return None

    # --- static tier -------------------------------------------------------
    out = drive([f"command script import {SCRIPT}", "saw table", "quit"])
    if out is None:
        print(f"test_lldb_saw: lldb did not finish in {LLDB_TIMEOUT_S}s",
              file=sys.stderr)
        return 1
    if args.verbose:
        print(out)
    if LOADED not in out:
        print("test_lldb_saw: the script did not load\n" + out, file=sys.stderr)
        return 1
    problems = check(out, WANT_TABLE, "saw table")

    # --- live tier ---------------------------------------------------------
    live = drive([f"command script import {SCRIPT}", "run",
                  "saw tasks", "saw bt", "quit"])
    if live is None:
        print(f"test_lldb_saw: lldb did not finish in {LLDB_TIMEOUT_S}s",
              file=sys.stderr)
        return 1
    if args.verbose:
        print(live)
    can_attach = "attach failed" not in live and "Not allowed to attach" not in live
    if can_attach:
        problems += check(live, WANT_TASKS, "saw tasks")
        problems += check(live, WANT_BT, "saw bt")

    if problems:
        print("test_lldb_saw: FAILED", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("--- lldb output ---\n" + out + "\n" + live, file=sys.stderr)
        return 1

    if can_attach:
        print("test_lldb_saw: ok — `saw table`, `saw tasks` and `saw bt` all "
              "agree with the fixture")
    else:
        print("test_lldb_saw: ok — `saw table` checked; the live tier was "
              "SKIPPED (this machine will not let lldb attach)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

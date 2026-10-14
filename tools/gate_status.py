#!/usr/bin/env python3
"""Whether the server's patch gate for a project is running or has a runnable
run queued.

    python tools/gate_status.py PROJECT

Exit 0: idle. Exit 1: busy, with one line naming the running and queued runs.
Exit 2: unknown, with one line saying why. `suite_lock.sh acquire
--yield-to-gate` waits on 1 and falls back to the plain acquire on 2, so a
tracker it cannot read never costs a local run more than the plain lock would.

SAW_GATE_STATUS_CMD replaces `sawtracker gate --project PROJECT --json`, which
is how tools/test_suite_lock.py stands a fixture in for the tracker.
"""
import json
import os
import shlex
import subprocess
import sys

# A tracker that accepts the connection and never answers would otherwise
# stall the waiter, which polls this, for good.
TIMEOUT = 30


def query(project):
    cmd = os.environ.get("SAW_GATE_STATUS_CMD")
    argv = shlex.split(cmd) if cmd else ["sawtracker", "gate", "--project", project, "--json"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        return None, "%s: not found" % argv[0]
    except subprocess.TimeoutExpired:
        return None, "%s: no answer in %ds" % (argv[0], TIMEOUT)
    if r.returncode != 0:
        lines = (r.stderr.strip() or r.stdout.strip()).splitlines()
        return None, lines[0] if lines else "%s: exit %d" % (argv[0], r.returncode)
    return r.stdout, None


def busy_runs(text, project):
    """(running, queued) patch names for `project`; ValueError when the
    report cannot answer the question."""
    report = json.loads(text)
    runners = report.get("runners") if isinstance(report, dict) else None
    if not isinstance(runners, list):
        raise ValueError("the gate report has no runners list")
    running, queued = [], []
    for runner in runners:
        if not isinstance(runner, dict):
            raise ValueError("a gate runner is not an object")
        run = runner.get("running")
        if isinstance(run, dict) and run.get("project") == project:
            running.append(str(run.get("patch", "?")))
        waiting = runner.get("queued") or []
        if not isinstance(waiting, list):
            raise ValueError("a gate runner's queue is not a list")
        for entry in waiting:
            # A held (changes requested) or superseded entry shares the queue
            # but never runs as it stands, so yielding to it would wait on
            # nothing.
            if (isinstance(entry, dict) and entry.get("project") == project
                    and not entry.get("held") and not entry.get("superseded")):
                queued.append(str(entry.get("patch", "?")))
    return running, queued


def main(argv):
    if len(argv) != 2:
        print("usage: tools/gate_status.py PROJECT", file=sys.stderr)
        return 2
    project = argv[1]
    text, err = query(project)
    if err is not None:
        print(err)
        return 2
    try:
        running, queued = busy_runs(text, project)
    except ValueError as e:
        print("unreadable gate report: %s" % e)
        return 2
    if not running and not queued:
        return 0
    parts = []
    if running:
        parts.append("%s running" % ", ".join(running))
    if queued:
        parts.append("%d queued: %s" % (len(queued), ", ".join(queued)))
    print("; ".join(parts))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

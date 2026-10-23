#!/usr/bin/env python3
"""A TERM to a runner's process group leaves none of the processes the runner
started behind (SL-603).

    python tools/test_child_groups.py [RUNNER...]

A launch either stays in the runner's process group, which the TERM reaches
directly, or starts a group of its own through `tools/child_groups.py`, whose
handler ends it; `bypasses` fails on any tracked source that makes a group
some other way. One case per runner: a driver runs the runner's own launch
code on a hanging child, the case TERMs the driver's group, and every process
of the case must be gone within the grace. A child in a group of its own
ignores TERM, so the KILL after the grace is on trial too, and each hanging
child has a grandchild, so the reach to the whole group is.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import child_groups  # noqa: E402
import gate_jobs  # noqa: E402

# Slack on top of a grace, for polling and process teardown.
SLACK_SECONDS = 3.0
# How long a driver may take to have its hanging child running; test_runner
# compiles its child first.
READY_SECONDS = 180.0

HANG = """#!/bin/sh
trap '' TERM
sleep 600 &
echo ready > "$0.$$.ready"
wait
"""

# A child that stays in its runner's group dies of the TERM that group gets.
HANG_IN_GROUP = """#!/bin/sh
sleep 600 &
echo ready > "$0.$$.ready"
wait
"""

HANG_PY = """import os, subprocess, sys, time
subprocess.Popen(["sleep", "600"])
open("%s.%d.ready" % (sys.argv[0], os.getpid()), "w").close()
time.sleep(600)
"""

HANG_SAW = """// EXPECT: success
// EXPECT-EXIT: 0
func main() {
    while true {
        sleep(Duration.ms(100))
    }
}
"""

STEP_OUT = os.path.join(REPO, ".build", "compiler-tests-steps")

# runner -> (the grace it gives its children; how the case knows they run:
# "script" by the hanging script's marker, "saw" by the program's pid staying
# alive, "line" by the driver writing `ready`, "group" by two markers of
# children in the driver's own group, "steps" by a run.py step's result file
# appearing; the log, under the case's directory, in which a real `main`'s
# handler must report, or None)
RUNNERS = {
    "test_runner": (child_groups.GRACE_SECONDS, "saw", "driver.log"),
    # compiler/tests/oracle.py: the run and the sawc build the coroutine
    # census, its Stage 0 snapshot and the corpus differential all launch.
    "oracle_run": (child_groups.GRACE_SECONDS, "script", None),
    "oracle_build": (child_groups.GRACE_SECONDS, "script", None),
    "test_worker": (child_groups.RUNNER_GRACE_SECONDS, "script", None),
    # The daemon's own main installs the handler that ends its job groups.
    "remote_worker_selftest": (2 * child_groups.RUNNER_GRACE_SECONDS, "line", "worker/worker.log"),
    # compiler/tests/run.py itself, its steps each in a process of its own.
    "run_steps": (child_groups.RUNNER_GRACE_SECONDS, "steps", "driver.log"),
    "recognizer_workers": (0.0, "group", None),
    "fixpoint_twin": (0.0, "group", None),
}
HANDLER_LINE = "SIGTERM: ended its child process groups"


# --- the driver: one runner's launch code, in a process of its own ---------

class _Sink:
    broken = False

    def emit(self, **_event):
        pass


def _observe_starts(pidfile):
    """Append each pid `child_groups.start` returns to `pidfile`."""
    real = child_groups.start

    def start(argv, *args, **kw):
        proc = real(argv, *args, **kw)
        with open(pidfile, "a") as fh:
            fh.write("%d\n" % proc.pid)
        return proc
    child_groups.start = start


def drive(runner, work, pidfile):
    _observe_starts(pidfile)
    hang = os.path.join(work, "hang")
    if runner == "test_runner":
        sys.path.insert(0, REPO)
        import test_runner
        discover = test_runner.discover_tests
        test_runner.discover_tests = lambda _examples: discover(Path(work) / "examples")
        sys.argv = ["test_runner.py", "-j", "1", "--settle-lag", "1"]
        test_runner.main()
        return
    # Children in the driver's own group need no handler: the TERM reaches them.
    if runner == "recognizer_workers":
        sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "grammar"))
        import recognize
        # The hanging workers lex nothing, but the binary is handed down to them
        # through the environment, so it must be a path.
        recognize.lexdump.ensure_sawc = lambda: "/usr/bin/false"
        recognize.run_workers([os.path.join(work, "hang.py")], ["a", "b"], 2)
        return
    if runner == "fixpoint_twin":
        sys.path.insert(0, os.path.join(REPO, "compiler", "tests", "fixpoint"))
        os.environ.update(FIXPOINT_REF=os.path.join(work, "hang_in_group"),
                          FIXPOINT_NEW=os.path.join(work, "hang_in_group"), SAW_GATE_CALL_TOKENS="2")
        import twin
        twin.run_both(["lex"])
        return
    child_groups.install()
    if runner in ("oracle_run", "oracle_build"):
        sys.path.insert(0, os.path.join(REPO, "compiler", "tests"))
        import oracle
        if runner == "oracle_run":
            oracle.run_binary(hang)
        else:
            oracle.build.SAWC = hang
            oracle.sawc_build(os.path.join(REPO, "examples", "hello.saw"), os.path.join(work, "hello"), [])
    elif runner == "test_worker":
        import test_worker
        config = argparse.Namespace(job_root=os.path.join(work, "jobs"), job_timeout=600.0,
                                    venv=sys.executable)
        job = test_worker.JobRunner(config, {}, None, _Sink())
        job.tree.mkdir(parents=True)
        job._await(job._spawn([hang], job.dir / "job.log"))
    elif runner == "remote_worker_selftest":
        import remote_worker_selftest
        root = Path(work) / "worker"
        root.mkdir()
        remote_worker_selftest.Worker(root, seed_runtime=False)
        with open(pidfile, "a") as fh:
            fh.write("ready\n")
        time.sleep(600)


# --- the cases -------------------------------------------------------------

def _recorded(pidfile):
    try:
        with open(pidfile) as fh:
            words = fh.read().split()
    except FileNotFoundError:
        return [], False
    return [int(w) for w in words if w.isdigit()], "ready" in words


def _alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


def _step_results():
    try:
        return set(os.listdir(STEP_OUT))
    except FileNotFoundError:
        return set()


def _ready(kind, work, pidfile, steps_before):
    if kind == "group":
        return len([n for n in os.listdir(work) if n.endswith(".ready")]) >= 2
    if kind == "steps":
        return bool(_step_results() - steps_before)
    pids, line = _recorded(pidfile)
    if not pids:
        return False
    if kind == "line":
        return line
    if kind == "script":
        return any(os.path.exists(os.path.join(work, "hang.%d.ready" % p)) for p in pids)
    return _alive(pids[-1])


def _setup(work):
    for name, text in (("hang", HANG), ("hang_in_group", HANG_IN_GROUP), ("hang.py", HANG_PY)):
        path = os.path.join(work, name)
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, 0o755)
    os.makedirs(os.path.join(work, "examples"))
    with open(os.path.join(work, "examples", "hang.saw"), "w") as fh:
        fh.write(HANG_SAW)


def _marked(work):
    """The pids of the hanging children that wrote a marker."""
    return [int(n.split(".")[-2]) for n in os.listdir(work) if n.endswith(".ready")]


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _group_verdict(driver, kind, grace, work):
    """The TERM must end the runner and, within the slack after it, every
    process left in its group, and every marked child, wherever its group."""
    child_groups.kill(driver, signal.SIGTERM)
    limit = grace + SLACK_SECONDS
    try:
        rc = driver.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        return "the runner was still running %.0fs after a TERM" % limit, []
    marked = _marked(work)
    deadline = time.monotonic() + SLACK_SECONDS
    while (_alive(driver.pid) or any(_pid_alive(p) for p in marked)) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _alive(driver.pid):
        return "processes of the runner's own group outlived it by %.0fs" % SLACK_SECONDS, [driver.pid]
    # A marked child still alive left the runner's group, so leads its own.
    escaped = [p for p in marked if _pid_alive(p)]
    if escaped:
        return "child(ren) %s left the runner's group and outlived the TERM" % escaped, escaped
    if kind == "steps" and rc != 143:
        return "run.py exited %s, not 143" % rc, []
    return None, []


def _verdict(driver, kind, grace, work, pidfile, steps_before):
    """(None or what went wrong, the child groups still alive at the end)."""
    deadline = time.monotonic() + READY_SECONDS
    while not _ready(kind, work, pidfile, steps_before):
        if driver.poll() is not None or time.monotonic() > deadline:
            return "the driver never had its child running (status %s)" % driver.poll(), []
        time.sleep(0.1)
    if kind in ("saw", "steps"):
        # Past test_runner's retry of a program that dies as it is exec'd, or
        # into a run.py step's own launches.
        time.sleep(1.0)
    if kind in ("group", "steps"):
        return _group_verdict(driver, kind, grace, work)
    pids = [p for p in _recorded(pidfile)[0] if _alive(p)]
    child_groups.kill(driver, signal.SIGTERM)
    started = time.monotonic()
    limit = grace + SLACK_SECONDS
    while any(_alive(p) for p in pids) and time.monotonic() - started < limit:
        time.sleep(0.05)
    left = [p for p in pids if _alive(p)]
    if left:
        return "child group(s) %s outlived a TERM to the runner by %.0fs" % (left, limit), left
    try:
        rc = driver.wait(timeout=SLACK_SECONDS)
    except subprocess.TimeoutExpired:
        return "the driver did not exit once its children were gone", []
    if rc != 143:
        return "the driver exited %s, not 143" % rc, []
    return None, []


def run_case(runner):
    """(None if `runner` passed, else what went wrong; the driver's output)."""
    grace, kind, handler_log = RUNNERS[runner]
    work = tempfile.mkdtemp(prefix="child-groups-", dir=os.path.join(REPO, ".build"))
    pidfile = os.path.join(work, "pids")
    log_path = os.path.join(work, "driver.log")
    _setup(work)
    if kind == "steps":
        cmd = [sys.executable, os.path.join(REPO, "compiler", "tests", "run.py")]
    else:
        cmd = [sys.executable, os.path.abspath(__file__), "--drive", runner, work, pidfile]
    # A budget of its own, two wide, so the case's pools run side by side.
    env = gate_jobs.child_env(2)
    env.pop(gate_jobs.TOKENS, None)
    steps_before = _step_results()
    with open(log_path, "w") as log:
        driver = child_groups.start(cmd, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT)
    left = []
    try:
        problem, left = _verdict(driver, kind, grace, work, pidfile, steps_before)
    finally:
        # Exact groups only: the driver's while it is unreaped, so its id
        # cannot have been reused, and those just seen outliving the TERM.
        if driver.returncode is None:
            child_groups.kill(driver)
        for pgid in left:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
        try:
            driver.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        child_groups.forget(driver)
        with open(log_path) as fh:
            output = fh.read()
        if problem is None and handler_log:
            with open(os.path.join(work, handler_log)) as fh:
                if HANDLER_LINE not in fh.read():
                    problem = "%s does not show the runner's own handler ending its groups" % handler_log
        shutil.rmtree(work, ignore_errors=True)
    return problem, output


# Each way a tracked source can put a child in a session or group of its own:
# Python's, the C and Saw seams under them, and a shell's job control.
NEW_GROUP = re.compile(r"start_new_session|setsid|preexec_fn|setpgid|setpgrp|process_group\s*="
                       r"|POSIX_SPAWN_SET(PGROUP|SID)|\bset -[a-zA-Z]*m")
# Prose describes these mechanisms without using them.
PROSE = (".md", ".txt", ".tsv", ".json")


def bypasses():
    """Tracked source that starts a child in a group of its own without
    `child_groups.start`, which a TERM to its runner would leave behind."""
    names = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split("\0")
    exempt = {"tools/child_groups.py", "tools/test_child_groups.py"}
    found = []
    for name in names:
        if not name or name in exempt or name.endswith(PROSE) or name.startswith(".sawtracker/"):
            continue
        path = os.path.join(REPO, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for number, line in enumerate(fh, 1):
                if NEW_GROUP.search(line):
                    found.append("%s:%d: %s" % (name, number, line.strip()))
    return found


def main():
    if sys.argv[1:2] == ["--drive"]:
        drive(*sys.argv[2:5])
        return 0
    child_groups.install()
    wanted = sys.argv[1:] or list(RUNNERS)
    unknown = [r for r in wanted if r not in RUNNERS]
    if unknown:
        print("child groups: unknown runner(s) %s; known: %s" % (", ".join(unknown), ", ".join(RUNNERS)))
        return 2
    failed = 0
    for site in bypasses():
        failed += 1
        print("child groups: FAIL: a new process group outside child_groups.start: %s" % site)
    for runner in wanted:
        started = time.monotonic()
        problem, output = run_case(runner)
        took = time.monotonic() - started
        if problem:
            failed += 1
            print("child groups: FAIL: %s: %s (%.0fs)" % (runner, problem, took))
            print("    " + output.strip().replace("\n", "\n    "))
        else:
            print("child groups: ok: %s (%.0fs)" % (runner, took))
    if failed:
        return 1
    print("child groups: OK: %s" % ", ".join(wanted))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The suite lock reports its holder, a heartbeat and the wait, and build.sh
hands the wait to the gate.

    python tools/test_suite_lock.py

Every case runs against a lock directory of its own (SAW_SUITE_LOCK), so this
never touches, or waits on, the machine-wide lock. The build.sh case points
SAW_PYTHON at a stub that stands in for patch_gate.py and reports what it saw.
The --yield-to-gate cases point SAW_GATE_STATUS_CMD at a scripted tracker, so
no case ever asks the real one.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import child_groups  # noqa: E402

LOCK_TOOL = os.path.join(REPO, "tools", "suite_lock.sh")
# The holder every case scripts acts for this process, which outlives it.
ME = str(os.getpid())

failures = []


def check(cond, what, output=""):
    if not cond:
        failures.append("%s%s" % (what, ("\n    " + output.replace("\n", "\n    ")) if output else ""))


def env_for(lock):
    return dict(os.environ, SAW_SUITE_LOCK=lock, SAW_SUITE_LOCK_HEARTBEAT="1",
                SAW_SUITE_LOCK_POLL="1")


def lock_tool(lock, *args):
    return subprocess.run(["sh", LOCK_TOOL] + list(args), cwd=REPO, env=env_for(lock),
                          capture_output=True, text=True)


def waiter(lock, command):
    """Start `command` against `lock` in the background, so the test can hold
    the lock for a few heartbeats and then release it."""
    return subprocess.Popen(command, cwd=REPO, env=env_for(lock), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def finish(proc):
    out, _ = proc.communicate(timeout=60)
    return proc.returncode, out


def free_lock(root):
    lock = os.path.join(root, "free")
    r = lock_tool(lock, "acquire", "--pid", ME, "free case")
    check(r.returncode == 0 and "suite lock: acquired; it was free" in r.stdout,
          "a free lock is acquired at once and says so", r.stdout + r.stderr)
    holder = open(os.path.join(lock, "holder")).read() if os.path.exists(lock) else ""
    for line in ("pid: " + ME, "command: free case", "cwd: %s" % REPO):
        check(line in holder.splitlines(), "the holder file records %r" % line, holder)
    check(re.search(r"^started: \d+ \(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC\)$", holder, re.M),
          "the holder file records when it was taken", holder)
    r = lock_tool(lock, "status")
    check("held by pid %s (free case, in %s) since " % (ME, REPO) in r.stdout,
          "status names the holder", r.stdout)
    r = lock_tool(lock, "release")
    check(r.returncode == 0 and not os.path.exists(lock) and "released after holding it" in r.stdout,
          "release removes the holder file and the directory", r.stdout + r.stderr)
    r = lock_tool(lock, "release")
    check(r.returncode != 0, "releasing a lock nobody holds fails", r.stdout + r.stderr)


def held_lock(root):
    lock = os.path.join(root, "held")
    lock_tool(lock, "acquire", "--pid", ME, "scripted holder")
    proc = waiter(lock, ["sh", LOCK_TOOL, "acquire", "waiting case"])
    time.sleep(3.5)
    lock_tool(lock, "release")
    rc, out = finish(proc)
    check("suite lock: held by pid %s (scripted holder, in %s) since " % (ME, REPO) in out
          and out.splitlines()[0].endswith("; waiting"),
          "a busy lock names its holder at entry", out)
    check("suite lock: still waiting after " in out and "; held by pid " + ME in out,
          "the wait prints a heartbeat naming the holder", out)
    check(rc == 0 and re.search(r"suite lock: acquired after waiting \d+s", out),
          "the acquisition prints the total wait", out)
    lock_tool(lock, "release")


def unknown_holder(root):
    lock = os.path.join(root, "unknown")
    os.mkdir(lock)
    proc = waiter(lock, ["sh", LOCK_TOOL, "acquire", "after an old-style taker"])
    time.sleep(1.5)
    os.rmdir(lock)
    rc, out = finish(proc)
    check(re.search(r"held by an unknown holder \(no holder file\) since .* ago; waiting", out),
          "a lock directory without a holder file reads as an unknown holder", out)
    check(rc == 0 and "acquired after waiting" in out, "it is still acquired once free", out)
    lock_tool(lock, "release")


def build_sh(root):
    lock = os.path.join(root, "build")
    lock_tool(lock, "acquire", "--pid", ME, "scripted holder")
    # The gate is what local runs yield to, so a busy gate report must not
    # hold build.sh back.
    tracker = Tracker(root, "build")
    tracker.answer(gate_report(running="SL-1.p1", queued=["SL-2.p1"]))
    env = tracker.env(lock)
    env["SAW_PYTHON"] = gate_stub(root)
    proc = subprocess.Popen(["./build.sh", "test", "--diff", "some.diff"], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2.5)
    lock_tool(lock, "release")
    rc, out = finish(proc)
    check("suite lock: held by pid %s (scripted holder" % ME in out and "still waiting after" in out
          and "acquired after waiting" in out, "build.sh reports the wait", out)
    check("stub: tools/patch_gate.py --diff some.diff" in out, "build.sh runs the gate", out)
    m = re.search(r"stub: wait=(\d+)", out)
    check(m and int(m.group(1)) >= 1, "build.sh passes the measured wait to the gate", out)
    check("command: ./build.sh test --diff some.diff" in out and "pid: " + ME not in out.split("stub:")[-1],
          "the lock is held in build.sh's name while the gate runs", out)
    check(rc == 3, "build.sh exits with the gate's status, %d here" % rc, out)
    check(not os.path.exists(lock) and "suite lock: released" in out,
          "build.sh releases the lock when the gate ends", out)
    check("yielding" not in out and not os.path.exists(os.path.join(tracker.dir, "count")),
          "build.sh never yields, or asks the tracker", out)


def gate_report(running=None, queued=(), held=(), superseded=()):
    """A `sawtracker gate --json` report with one SL runner, plus another
    project's busy runner that a yielding acquire must ignore. Held and
    superseded entries follow the runnable ones in the same queue, with no
    position, as the tracker lists them."""
    sl = {"runner": 0, "projects": ["SL"], "queued": [
        {"patch": p, "project": "SL", "position": i + 1} for i, p in enumerate(queued)]}
    sl["queued"] += [{"patch": p, "project": "SL", "held": "changes requested", "position": None,
                      "eta": None} for p in held]
    sl["queued"] += [{"patch": p, "project": "SL", "superseded": "revised", "position": None,
                      "eta": None} for p in superseded]
    if running:
        sl["running"] = {"patch": running, "project": "SL", "elapsed": 30}
    other = {"runner": 1, "projects": ["SO"], "running": {"patch": "SO-9.p1", "project": "SO"},
             "queued": [{"patch": "SO-10.p1", "project": "SO", "position": 1}]}
    return json.dumps({"runners": [sl, other], "totals": {}})


class Tracker:
    """A stand-in for `sawtracker gate`, through SAW_GATE_STATUS_CMD: call N
    answers with the file N in its directory, or `default`, and a `fail` file
    makes every call fail the way an unreachable server does."""

    def __init__(self, root, name):
        self.dir = os.path.join(root, "tracker-" + name)
        os.mkdir(self.dir)
        self.script = os.path.join(self.dir, "sawtracker")
        with open(self.script, "w") as fh:
            fh.write('#!/bin/sh\nd=$(dirname "$0")\n'
                     'n=$(($(cat "$d/count" 2>/dev/null || echo 0) + 1))\necho "$n" > "$d/count"\n'
                     'if [ -f "$d/fail" ]; then\n'
                     '    echo "sawtracker: Connect: io error: connect failed (connection refused)" >&2\n'
                     '    exit 1\nfi\n'
                     'if [ -f "$d/$n" ]; then cat "$d/$n"; else cat "$d/default"; fi\n')
        os.chmod(self.script, 0o755)

    def answer(self, text, call="default"):
        # Renamed into place, so a call never reads half an answer.
        path = os.path.join(self.dir, str(call))
        with open(path + ".new", "w") as fh:
            fh.write(text)
        os.replace(path + ".new", path)

    def fail(self):
        open(os.path.join(self.dir, "fail"), "w").close()

    def calls(self):
        with open(os.path.join(self.dir, "count")) as fh:
            return int(fh.read())

    def env(self, lock):
        return dict(env_for(lock), SAW_GATE_STATUS_CMD=self.script)


def yielder(lock, tracker, command):
    return subprocess.Popen(["sh", LOCK_TOOL, "acquire", "--yield-to-gate", "--pid", ME, command],
                            cwd=REPO, env=tracker.env(lock), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def yield_idle(root):
    """An idle SL gate lets a yielding acquire take a free lock at once; another
    project's runs are not its business."""
    lock = os.path.join(root, "yield-idle")
    tracker = Tracker(root, "idle")
    tracker.answer(gate_report())
    rc, out = finish(yielder(lock, tracker, "idle gate"))
    check(rc == 0 and out == "suite lock: acquired; it was free\n",
          "an idle gate lets a yielding acquire take a free lock", out)
    check(tracker.calls() == 2, "it asks the gate before and just after taking the lock", out)
    lock_tool(lock, "release")


def yield_queued(root):
    """A queued gate run keeps a yielding acquire off a free lock until the
    gate is idle."""
    lock = os.path.join(root, "yield-queued")
    tracker = Tracker(root, "queued")
    tracker.answer(gate_report(queued=["SL-612.p1", "SL-626.p1"]))
    proc = yielder(lock, tracker, "queued gate")
    time.sleep(2.5)
    taken_while_queued = os.path.exists(lock)
    tracker.answer(gate_report())
    rc, out = finish(proc)
    check(not taken_while_queued, "a yielding acquire leaves a free lock alone while a gate run is queued", out)
    check(out.startswith("suite lock: yielding to the server's SL gate "
                         "(2 queued: SL-612.p1, SL-626.p1); waiting\n"),
          "a yielding acquire names the gate runs it waits for", out)
    check("suite lock: still waiting after " in out and "; yielding to the server's SL gate (" in out,
          "the yielding wait prints a heartbeat naming the gate", out)
    check(rc == 0 and re.search(r"suite lock: acquired after waiting [1-9]\d*s", out),
          "once the gate is idle it takes the lock and prints the total wait", out)
    holder = open(os.path.join(lock, "holder")).read() if os.path.exists(lock) else ""
    check("command: queued gate" in holder, "the lock is then held in the caller's name", holder)
    lock_tool(lock, "release")


def yield_held(root):
    """Held and superseded entries will not run as they stand, so they alone
    leave the gate idle; a runnable entry beside a held one still makes it busy."""
    lock = os.path.join(root, "yield-held-only")
    tracker = Tracker(root, "held-only")
    tracker.answer(gate_report(held=["SL-660.p1"], superseded=["SL-661.p1"]))
    rc, out = finish(yielder(lock, tracker, "held entries"))
    check(rc == 0 and out == "suite lock: acquired; it was free\n",
          "held and superseded entries with nothing running let a yielding acquire take the lock",
          out)
    lock_tool(lock, "release")
    lock = os.path.join(root, "yield-held-beside")
    tracker = Tracker(root, "held-beside")
    tracker.answer(gate_report(queued=["SL-662.p1"], held=["SL-660.p1"]))
    proc = yielder(lock, tracker, "held beside runnable")
    time.sleep(1.5)
    taken = os.path.exists(lock)
    tracker.answer(gate_report())
    rc, out = finish(proc)
    check(not taken and out.startswith("suite lock: yielding to the server's SL gate "
                                       "(1 queued: SL-662.p1); waiting\n")
          and rc == 0 and "acquired after waiting" in out,
          "a runnable entry beside a held one is waited for, and only it is named", out)
    lock_tool(lock, "release")


def yield_running(root):
    """A running gate run is waited for too, even while the lock is free."""
    lock = os.path.join(root, "yield-running")
    tracker = Tracker(root, "running")
    tracker.answer(gate_report(running="SL-611.p1"))
    proc = yielder(lock, tracker, "running gate")
    time.sleep(1.5)
    taken = os.path.exists(lock)
    tracker.answer(gate_report())
    rc, out = finish(proc)
    check(not taken and "yielding to the server's SL gate (SL-611.p1 running); waiting" in out
          and rc == 0 and "acquired after waiting" in out,
          "a running gate run makes a yielding acquire wait", out)
    lock_tool(lock, "release")


def yield_gives_back(root):
    """A gate run that appears between the check and the take gets the lock
    handed back before any holder file is written."""
    lock = os.path.join(root, "yield-back")
    tracker = Tracker(root, "back")
    tracker.answer(gate_report(), call=1)
    tracker.answer(gate_report(queued=["SL-640.p1"]), call=2)
    tracker.answer(gate_report(running="SL-640.p1"), call=3)
    tracker.answer(gate_report())
    rc, out = finish(yielder(lock, tracker, "raced gate"))
    check(out.startswith("suite lock: a gate run appeared as it took the lock "
                         "(1 queued: SL-640.p1); gave it back\n"
                         "suite lock: yielding to the server's SL gate (1 queued: SL-640.p1); waiting\n"),
          "a gate run that appears as it takes the lock makes it give the lock back", out)
    check(rc == 0 and "acquired after waiting" in out and tracker.calls() >= 5,
          "it takes the lock once the gate is idle on both checks", out)
    lock_tool(lock, "release")


def yield_behind_holder(root):
    """While the lock is held a yielding acquire waits on the holder, asks the
    gate only once the lock could be taken, and says when it turns to waiting
    on the gate instead."""
    lock = os.path.join(root, "yield-held")
    lock_tool(lock, "acquire", "--pid", ME, "scripted holder")
    tracker = Tracker(root, "held")
    tracker.answer(gate_report(queued=["SL-650.p1"]))
    proc = yielder(lock, tracker, "behind a holder")
    time.sleep(2.5)
    asked = os.path.exists(os.path.join(tracker.dir, "count"))
    lock_tool(lock, "release")
    time.sleep(1.5)
    tracker.answer(gate_report())
    rc, out = finish(proc)
    check(out.startswith("suite lock: held by pid %s (scripted holder" % ME)
          and "still waiting after" in out and "; held by pid " + ME in out,
          "a yielding acquire behind a holder names the holder", out)
    check(not asked, "the gate is not asked while the lock is held", out)
    check("suite lock: now yielding to the server's SL gate (1 queued: SL-650.p1); waiting" in out,
          "a turn from the holder to the gate is reported", out)
    check(rc == 0 and "acquired after waiting" in out, "it takes the lock once released", out)
    lock_tool(lock, "release")


def yield_fallback(root):
    """An unreachable tracker, or a report that cannot say, falls back to the
    plain acquire and says so."""
    lock = os.path.join(root, "yield-unreachable")
    tracker = Tracker(root, "unreachable")
    tracker.fail()
    rc, out = finish(yielder(lock, tracker, "no tracker"))
    check(out == "suite lock: cannot read the server's SL gate (sawtracker: Connect: io error: "
                 "connect failed (connection refused)); falling back to the plain acquire\n"
                 "suite lock: acquired; it was free\n" and rc == 0,
          "an unreachable tracker falls back to the plain acquire, with the message", out)
    check(tracker.calls() == 1, "a fallen-back acquire stops asking the tracker", out)
    lock_tool(lock, "release")
    lock = os.path.join(root, "yield-unreadable")
    tracker = Tracker(root, "unreadable")
    tracker.answer('{"merge_queue": {}}')
    rc, out = finish(yielder(lock, tracker, "odd report"))
    check(rc == 0 and "cannot read the server's SL gate (unreadable gate report: the gate "
                      "report has no runners list); falling back" in out
          and "acquired; it was free" in out,
          "a report without the runners falls back too", out)
    lock_tool(lock, "release")


def gate_stub(root):
    """An interpreter for build.sh that records that the gate ran, then fails."""
    stub = os.path.join(root, "stub_python")
    with open(stub, "w") as fh:
        fh.write('#!/bin/sh\necho "stub: $*"\necho "stub: wait=$SAW_GATE_LOCK_WAIT"\n'
                 'cat "$SAW_SUITE_LOCK/holder"\nexit 3\n')
    os.chmod(stub, 0o755)
    return stub


def orphaned_waiter(root):
    """A signal that reaches build.sh alone leaves its acquire child running;
    the child must stop waiting rather than take the lock for a dead owner."""
    lock = os.path.join(root, "orphan")
    lock_tool(lock, "acquire", "--pid", ME, "scripted holder")
    env = env_for(lock)
    env["SAW_PYTHON"] = gate_stub(root)
    proc = subprocess.Popen(["./build.sh", "test", "--diff", "some.diff"], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    time.sleep(2.5)
    lock_tool(lock, "release")
    out, _ = proc.communicate(timeout=60)
    time.sleep(2)
    check("stopped waiting: pid %d, which it waited for, is gone; the lock was not taken"
          % proc.pid in out, "a waiter whose owner is killed stops waiting", out)
    check("stub:" not in out, "the gate never runs for the killed build.sh", out)
    r = lock_tool(lock, "status")
    check(not os.path.exists(lock) and "suite lock: free" in r.stdout,
          "the lock is free once its holder releases, never held for the dead waiter",
          out + r.stdout)
    if os.path.exists(lock):
        lock_tool(lock, "release")


def shells():
    """build.sh's `#!/bin/sh` is bash on macOS and dash on Debian; both run it."""
    return ["sh"] + [s for s in ("/bin/dash",) if os.path.exists(s)]


def start_gate(lock, root, shell, gate):
    """build.sh under `shell`, in a session of its own as sawtracker starts a gate,
    with `gate` standing in for patch_gate.py."""
    stub = os.path.join(root, "slow_gate")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\n" + gate)
    os.chmod(stub, 0o755)
    env = env_for(lock)
    env["SAW_PYTHON"] = stub
    return child_groups.start([shell, "./build.sh", "test", "--diff", "some.diff"], cwd=REPO,
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def await_path(path, proc, seconds=20):
    deadline = time.time() + seconds
    while not os.path.exists(path) and proc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    return os.path.exists(path)


def end_group(proc):
    """KILL whatever of a case's build.sh group outlived it."""
    child_groups.kill(proc)
    child_groups.forget(proc)


def term_releases(root):
    """A TERM to a gate's process group ends build.sh with 143 and gives the
    lock back, which a cancelled server run relies on (SL-603)."""
    for shell in shells():
        lock = os.path.join(root, "term-" + os.path.basename(shell))
        started = lock + ".gate"
        proc = start_gate(lock, root, shell, 'touch "$SAW_SUITE_LOCK.gate"\nsleep 60\n')
        try:
            ran = await_path(started, proc)
            child_groups.kill(proc, signal.SIGTERM)
            rc, out = finish(proc)
        finally:
            end_group(proc)
        check(ran, "%s: the gate stub ran" % shell, out)
        check(rc == 143, "%s: a TERMed build.sh exits 143, not %s" % (shell, rc), out)
        check(not os.path.exists(lock) and "suite lock: released" in out,
              "%s: a TERMed build.sh releases the lock" % shell, out)
        if os.path.exists(lock):
            lock_tool(lock, "release")


def term_while_waiting(root):
    """A TERM to a gate still waiting for the lock leaves the holder's lock alone."""
    for shell in shells():
        lock = os.path.join(root, "term-wait-" + os.path.basename(shell))
        lock_tool(lock, "acquire", "--pid", ME, "scripted holder")
        proc = start_gate(lock, root, shell, "exit 0\n")
        try:
            time.sleep(1.5)
            child_groups.kill(proc, signal.SIGTERM)
            rc, out = finish(proc)
        finally:
            end_group(proc)
        holder = open(os.path.join(lock, "holder")).read() if os.path.exists(lock) else ""
        check(rc != 0 and "suite lock: held by pid %s" % ME in out,
              "%s: the TERMed build.sh was waiting, and stopped" % shell, out)
        check("pid: " + ME in holder and "released" not in out,
              "%s: a TERMed waiter neither takes nor releases the holder's lock" % shell, out + holder)
        lock_tool(lock, "release")


def dead_owner_at_acquire(root):
    """An owner that dies as the mkdir succeeds gets the lock released at once."""
    lock = os.path.join(root, "dead-owner")
    gone = subprocess.Popen(["true"])
    gone.wait()
    r = lock_tool(lock, "acquire", "--pid", str(gone.pid), "for a dead owner")
    check(r.returncode != 0 and "released at once: pid %d" % gone.pid in r.stdout
          and not os.path.exists(lock),
          "a lock taken for a dead owner is released at once", r.stdout + r.stderr)
    if os.path.exists(lock):
        lock_tool(lock, "release")


def main():
    child_groups.install()
    root = tempfile.mkdtemp(prefix="suite-lock-test-")
    try:
        for case in (free_lock, held_lock, unknown_holder, build_sh, orphaned_waiter,
                     term_releases, term_while_waiting, dead_owner_at_acquire, yield_idle,
                     yield_queued, yield_held, yield_running, yield_gives_back, yield_behind_holder,
                     yield_fallback):
            case(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for f in failures:
        print("suite lock: FAIL: %s" % f)
    if failures:
        return 1
    print("suite lock: OK: holder, heartbeat, wait, unknown holder, build.sh, orphaned waiter, "
          "TERMed gate, TERMed waiter, dead owner, yield to an idle/queued/held/running gate, "
          "give back on a race, yield behind a holder, fallback")
    return 0


if __name__ == "__main__":
    sys.exit(main())

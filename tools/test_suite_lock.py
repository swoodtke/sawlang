#!/usr/bin/env python3
"""The suite lock reports its holder, a heartbeat and the wait, and build.sh
hands the wait to the gate.

    python tools/test_suite_lock.py

Every case runs against a lock directory of its own (SAW_SUITE_LOCK), so this
never touches, or waits on, the machine-wide lock. The build.sh case points
SAW_PYTHON at a stub that stands in for patch_gate.py and reports what it saw.
"""
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
    env = env_for(lock)
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
                     term_releases, term_while_waiting, dead_owner_at_acquire):
            case(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for f in failures:
        print("suite lock: FAIL: %s" % f)
    if failures:
        return 1
    print("suite lock: OK: holder, heartbeat, wait, unknown holder, build.sh, orphaned waiter, "
          "TERMed gate, TERMed waiter, dead owner")
    return 0


if __name__ == "__main__":
    sys.exit(main())

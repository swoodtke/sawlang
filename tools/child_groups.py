"""Child process groups that end with the runner that started them (SL-603).

A runner starts a child in a new session so a timeout can kill the child's
whole tree, but a signal sent to the runner's own process group never reaches
that session. `start` records each such group. On SIGTERM, SIGINT or SIGHUP
the handler `install` sets up sends every live one TERM, waits the group's
grace, KILLs what is left, and exits with 128 plus the signal's number.

ENTRY POINTS:
  start
  forget
  kill
  install
"""
import os
import signal
import subprocess
import sys
import time

# A test program gets this long between TERM and KILL.
GRACE_SECONDS = 2.0
# A child that is itself a runner forwarding to groups of its own needs longer
# than the grace it gives them, or its KILL lands before theirs does.
RUNNER_GRACE_SECONDS = 10.0
POLL_SECONDS = 0.05

# Leader pid (which is the group id) -> its grace. Mutated from worker threads
# and read by the handler on the main thread; each dict operation is atomic
# under the GIL, so neither side takes a lock the other could be holding.
_groups = {}
_stopping = False


def start(argv, grace=GRACE_SECONDS, **popen_kw):
    """`subprocess.Popen(argv, **popen_kw)` in a new session, recorded until
    `forget`. A child started after the handler has begun is TERMed at once,
    and the handler's next poll picks it up."""
    proc = subprocess.Popen(argv, start_new_session=True, **popen_kw)
    _groups[proc.pid] = grace
    if _stopping:
        _signal_group(proc.pid, signal.SIGTERM)
    return proc


def forget(proc):
    """Drop `proc`'s record once it has been reaped. A leader's pid can be
    reused only after its reaping, so the record must not outlive that."""
    _groups.pop(proc.pid, None)


def kill(proc, sig=signal.SIGKILL):
    """Send `sig` to the whole group `start` began for `proc`."""
    if not _signal_group(proc.pid, sig):
        try:
            proc.send_signal(sig)
        except OSError:
            pass


def install():
    """Route SIGTERM, SIGINT and SIGHUP through the handler. Call it from the
    main thread, before the first `start`."""
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _on_signal)


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except OSError:
        return False


def _group_alive(pgid):
    # The handler may hold the main thread that would reap a leader, and a
    # zombie leader keeps its group answering signals, so reap it here.
    try:
        os.waitpid(pgid, os.WNOHANG)
    except ChildProcessError:
        pass
    return _signal_group(pgid, 0)


def _on_signal(signum, _frame):
    global _stopping
    if _stopping:
        return
    _stopping = True
    deadlines = {}
    killed = 0
    while True:
        now = time.monotonic()
        for pgid, grace in list(_groups.items()):
            if pgid not in deadlines:
                deadlines[pgid] = now + grace
                _signal_group(pgid, signal.SIGTERM)
        for pgid in [g for g in deadlines if not _group_alive(g)]:
            # Gone is final: the id may be reused from here on, so it is
            # never signalled again.
            del deadlines[pgid]
            _groups.pop(pgid, None)
        for pgid, deadline in list(deadlines.items()):
            if now >= deadline:
                _signal_group(pgid, signal.SIGKILL)
                killed += 1
                del deadlines[pgid]
                _groups.pop(pgid, None)
        if not deadlines:
            break
        time.sleep(POLL_SECONDS)
    name = signal.Signals(signum).name
    note = f", {killed} by KILL" if killed else ""
    print(f"{os.path.basename(sys.argv[0])}: {name}: ended its child process "
          f"groups{note}", file=sys.stderr)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    # Not sys.exit: worker threads would go on starting children while the
    # interpreter waited for them.
    os._exit(128 + signum)

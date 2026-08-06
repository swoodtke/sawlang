#!/usr/bin/env python3
"""
Self-test for test_runner.run_executable's hard run-phase timeout.

This is NOT discovered by the .saw suite (that only globs examples/*.saw).
It proves the design-86 item-1 guarantee: a test that HANGS AT RUNTIME is
killed and recorded FAILED (timeout) within the wall-clock cap, and the
runner never wedges — even when the hung process spawned a grandchild that
inherited the stdout pipe (the classic subprocess-timeout wedge).

Run:  ./.venv/bin/python tools/test_runner_selftest.py
"""

import os
import stat
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_runner  # noqa: E402


def _write_exe(dirpath: Path, name: str, body: str) -> Path:
    p = dirpath / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  FAIL: {msg}")
        raise SystemExit(1)


def test_plain_hang_times_out():
    """A process that never exits is killed and reported within the cap."""
    with tempfile.TemporaryDirectory() as d:
        exe = _write_exe(Path(d), "hang.sh", "sleep 3600\n")
        t0 = time.monotonic()
        ok, out, err, note = test_runner.run_executable(exe, timeout=2)
        elapsed = time.monotonic() - t0
        _check(not ok, "hanging test should report failure")
        _check("timed out" in err, f"stderr should mention timeout, got: {err!r}")
        _check(elapsed < 10, f"runner should return promptly, took {elapsed:.1f}s")
    print("  ok: plain hang times out and reports FAILED (timeout)")


def test_grandchild_wedge_does_not_hang_runner():
    """
    The wedge case: the child spawns a grandchild that outlives it and
    inherits the stdout pipe, then the child itself exits. With a naive
    subprocess.run(timeout=...) this hangs the reaper forever. With the
    process-group kill it returns promptly.
    """
    with tempfile.TemporaryDirectory() as d:
        # Background a long sleep (grandchild keeps the inherited pipe open),
        # then the script's foreground work also hangs so the timeout must fire.
        exe = _write_exe(Path(d), "wedge.sh", "sleep 3600 &\nsleep 3600\n")
        t0 = time.monotonic()
        ok, out, err, note = test_runner.run_executable(exe, timeout=2)
        elapsed = time.monotonic() - t0
        _check(not ok, "wedge test should report failure")
        _check(elapsed < 10, f"runner must not wedge, took {elapsed:.1f}s")
    print("  ok: grandchild-with-inherited-pipe does not wedge the runner")


def test_normal_exit_still_works():
    """A fast, successful executable is unaffected by the timeout machinery."""
    with tempfile.TemporaryDirectory() as d:
        exe = _write_exe(Path(d), "ok.sh", "echo hello\nexit 0\n")
        ok, out, err, note = test_runner.run_executable(exe, timeout=5)
        _check(ok, f"normal exit should succeed, err={err!r}")
        _check(out.strip() == "hello", f"stdout should pass through, got {out!r}")
    print("  ok: normal fast exit passes through unchanged")


def test_nonzero_exit_reported():
    """A crashing/failing executable is reported as a failure (not a timeout)."""
    with tempfile.TemporaryDirectory() as d:
        exe = _write_exe(Path(d), "fail.sh", "echo boom\nexit 3\n")
        ok, out, err, note = test_runner.run_executable(exe, timeout=5)
        _check(not ok, "nonzero exit should report failure")
        _check("timed out" not in err, "a fast failure is not a timeout")
    print("  ok: nonzero exit reported as failure, not timeout")


def test_silent_signal_death_is_retried_and_reported():
    """DF-149b backstop (b): a child killed by a signal having written NOTHING
    is re-run once, and the retry is REPORTED whether or not it then passes.

    The script dies of SIGTRAP on its first run (writing nothing, exactly like
    a binary the kernel has not finished validating) and succeeds on its
    second, so this covers both halves: the retry recovers the run AND the
    note still comes back, because a silent retry could hide a real crash.
    """
    with tempfile.TemporaryDirectory() as d:
        marker = Path(d) / "ran-once"
        exe = _write_exe(Path(d), "flaky.sh",
                         f'if [ -e "{marker}" ]; then echo hello; exit 0; fi\n'
                         f'touch "{marker}"\n'
                         f'kill -TRAP $$\n')
        ok, out, err, note = test_runner.run_executable(exe, timeout=5)
        _check(ok, f"the retry should have succeeded, err={err!r}")
        _check(out.strip() == "hello", f"retry stdout should pass through, got {out!r}")
        _check(note is not None, "a retry must be reported, never silent")
        _check("signal 5" in note, f"the note should name the signal, got {note!r}")
        _check("succeeded" in note, f"the note should say how it ended, got {note!r}")
    print("  ok: silent signal death is retried once and the retry is reported")


def test_repeated_silent_death_still_fails():
    """A binary that dies silently EVERY time is still a failure — the retry
    buys one more chance, not a pass."""
    with tempfile.TemporaryDirectory() as d:
        exe = _write_exe(Path(d), "always.sh", "kill -TRAP $$\n")
        ok, out, err, note = test_runner.run_executable(exe, timeout=5)
        _check(not ok, "a consistently crashing binary must still fail")
        _check(note is not None, "the retry must be reported")
        _check("failed too" in note, f"the note should say the retry failed, got {note!r}")
        _check("signal" in err, f"stderr should name the signal death, got {err!r}")
    print("  ok: a binary that always dies silently still fails, with the retry noted")


def test_talkative_failure_is_not_retried():
    """A failure that SPOKE is a real failure — no retry, no note. This is what
    keeps every panic test (which prints before aborting) at one run."""
    with tempfile.TemporaryDirectory() as d:
        exe = _write_exe(Path(d), "loud.sh", "echo 'panic at x.saw:1: boom' >&2\nkill -ABRT $$\n")
        ok, out, err, note = test_runner.run_executable(exe, timeout=5)
        _check(not ok, "a signal death should still fail")
        _check(note is None, f"a failure that wrote output must not be retried, got {note!r}")
        _check("boom" in err, f"the child's own stderr must survive, got {err!r}")
    print("  ok: a signal death that wrote output is not retried")


def main() -> int:
    print("test_runner run-phase timeout self-test")
    test_normal_exit_still_works()
    test_nonzero_exit_reported()
    test_plain_hang_times_out()
    test_grandchild_wedge_does_not_hang_runner()
    test_silent_signal_death_is_retried_and_reported()
    test_repeated_silent_death_still_fails()
    test_talkative_failure_is_not_retried()
    print("ALL SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

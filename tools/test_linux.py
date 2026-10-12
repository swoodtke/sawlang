#!/usr/bin/env python3
"""tools/linux.py's verdicts on Lima's state, against stub `limactl`s.

    python tools/test_linux.py

The `linux` battery lane skips, and passes, only when the VM is known not to
run: limactl absent, no `sawlang-linux` instance, or one that is stopped. A
limactl that cannot report Lima's state (a sandbox that cannot read ~/.lima)
leaves the VM's state unknown, so `status` exits 4 with limactl's own message
and the lane fails on it. Each case runs `status` and `lane` with a stub
limactl first on a PATH that holds no real one; no VM is touched.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LINUX = os.path.join(HERE, "linux.py")
OUT = os.path.join(REPO, ".build", "test-linux")
STUB_MESSAGE = "level=fatal msg=\"cannot evaluate symlinks in ~/.lima: operation not permitted\""

# (case, the stub's shell body or None for no limactl at all, the status
# `status` exits with, text its output holds, the status `lane` exits with).
CASES = (
    ("no limactl", None, 3, "limactl is not installed", 0),
    ("limactl fails", "echo '%s' >&2; exit 1" % STUB_MESSAGE, 4, STUB_MESSAGE, 4),
    ("limactl prints no JSON", "echo 'not json'; exit 0", 4, "not JSON", 4),
    ("no such VM", "exit 0", 3, "there is no `sawlang-linux` VM", 0),
    ("VM stopped", "echo '{\"name\":\"sawlang-linux\",\"status\":\"Stopped\"}'; exit 0", 3,
     "start it with `limactl start sawlang-linux`", 0),
)


def run_case(name, body):
    """(status exit, status output, lane exit, lane output) for one stub."""
    bin_dir = os.path.join(OUT, name.replace(" ", "-"))
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    if body is not None:
        stub = os.path.join(bin_dir, "limactl")
        with open(stub, "w") as fh:
            fh.write("#!/bin/sh\n%s\n" % body)
        os.chmod(stub, 0o755)
    env = dict(os.environ, PATH=bin_dir + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    out = []
    for command in ("status", "lane"):
        r = subprocess.run([sys.executable, LINUX, command], cwd=REPO, env=env, capture_output=True, text=True,
                           timeout=60)
        out += [r.returncode, r.stdout + r.stderr]
    return out


def main():
    failures = []
    for name, body, want_status, text, want_lane in CASES:
        status, said, lane, lane_said = run_case(name, body)
        if status != want_status or text not in said:
            failures.append("%s: `status` exits %d, not %d, or does not say %r: %s"
                            % (name, status, want_status, text, said.strip()[:300]))
        if lane != want_lane or text not in lane_said:
            failures.append("%s: `lane` exits %d, not %d, or does not say %r: %s"
                            % (name, lane, want_lane, text, lane_said.strip()[:300]))
        if want_lane == 0 and "SKIPPED" not in lane_said:
            failures.append("%s: `lane` passes without saying it SKIPPED: %s" % (name, lane_said.strip()[:300]))
        if want_lane != 0 and "SKIPPED" in lane_said:
            failures.append("%s: `lane` fails but says it SKIPPED: %s" % (name, lane_said.strip()[:300]))
    for failure in failures:
        print(failure)
    print("linux tool: %s: %d stub cases" % ("FAIL (%d)" % len(failures) if failures else "ok", len(CASES)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

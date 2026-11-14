#!/usr/bin/env python3
"""tools/linux.py's verdicts on Lima's state, against stub `limactl`s.

    python tools/test_linux.py

`shell CMD < FILE` carries FILE to CMD: a stub limactl logs the bytes of
standard input each invocation found, and only the user's command's holds any.
The `linux` battery lane skips, and passes, only when the VM is known not to
run: limactl absent, no `sawlang-linux` instance, or one that is stopped. A
limactl that cannot report Lima's state (a sandbox that cannot read ~/.lima)
leaves the VM's state unknown, so `status` exits 4 with limactl's own message
and the lane fails on it. Each case runs `status` and `lane` with a stub
limactl first on a PATH that holds no real one; no VM is touched. The retired
`stage0` command is refused with the usage.
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


# A limactl that lists a running VM and, for `shell`, drains its standard
# input and logs the command it was given with the bytes it found.
SHELL_STUB = """#!/bin/sh
if [ "$1" = list ]; then
    echo '{"name":"sawlang-linux","status":"Running"}'
    exit 0
fi
while [ "$1" != "--" ]; do shift; done
shift
bytes=$(cat | wc -c | tr -d ' ')
echo "$1 $bytes" >> "$STUB_LOG"
case "$1" in printenv) echo /home/stub ;; esac
exit 0
"""
SHELL_INPUT_BYTES = 500


def check_shell_input(failures):
    """`shell CMD < FILE` hands FILE to CMD: the calls the tool makes first
    (the VM's home, the clone's directory) find their standard input empty, so
    none of them consumes it."""
    bin_dir = os.path.join(OUT, "shell-input")
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    stub = os.path.join(bin_dir, "limactl")
    with open(stub, "w") as fh:
        fh.write(SHELL_STUB)
    os.chmod(stub, 0o755)
    log = os.path.join(bin_dir, "calls.log")
    data = os.path.join(bin_dir, "input.bin")
    with open(data, "wb") as fh:
        fh.write(bytes(k % 251 for k in range(SHELL_INPUT_BYTES)))
    env = dict(os.environ, PATH=bin_dir + os.pathsep + "/usr/bin" + os.pathsep + "/bin", STUB_LOG=log)
    with open(data, "rb") as fh:
        r = subprocess.run([sys.executable, LINUX, "shell", "wc", "-c"], cwd=REPO, env=env, stdin=fh,
                           capture_output=True, text=True, timeout=60)
    calls = open(log).read().split("\n") if os.path.exists(log) else []
    want = ["printenv 0", "test 0", "wc %d" % SHELL_INPUT_BYTES, ""]
    if r.returncode != 0 or calls != want:
        failures.append("`shell wc -c < FILE` exits %d, and the stub's calls (command, standard input bytes) are %r, "
                        "not %r: %s" % (r.returncode, calls, want, (r.stdout + r.stderr).strip()[:300]))


# A limactl that lists a running VM and answers the calls the disk commands
# make: `df` prints STUB_AVAIL bytes, `du` lists two clones, `test` succeeds
# unless STUB_NO_GIT is set, and every call's arguments are logged, each in
# brackets.
DISK_STUB = """#!/bin/sh
if [ "$1" = list ]; then
    echo '{"name":"sawlang-linux","status":"Running"}'
    exit 0
fi
while [ "$1" != "--" ]; do shift; done
shift
for a in "$@"; do printf '[%s]' "$a" >> "$STUB_LOG"; done
echo >> "$STUB_LOG"
case "$1" in
    printenv) echo /home/stub ;;
    df) printf 'Avail\\n%s\\n' "$STUB_AVAIL" ;;
    du) printf '3000\\t/home/stub/sawlang/old\\n1000\\t/home/stub/sawlang/new\\n4000\\t/home/stub/sawlang\\n' ;;
    test) [ -z "$STUB_NO_GIT" ] || exit 1 ;;
esac
exit 0
"""
GIB = 2 ** 30


def run_disk(args, avail, tag, no_git=False):
    """(exit, output, the stub's logged calls) of `linux.py ARGS` against
    DISK_STUB with `avail` bytes free."""
    bin_dir = os.path.join(OUT, "disk-" + tag)
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    stub = os.path.join(bin_dir, "limactl")
    with open(stub, "w") as fh:
        fh.write(DISK_STUB)
    os.chmod(stub, 0o755)
    log = os.path.join(bin_dir, "calls.log")
    env = dict(os.environ, PATH=bin_dir + os.pathsep + "/usr/bin" + os.pathsep + "/bin", STUB_LOG=log,
               STUB_AVAIL=str(avail))
    if no_git:
        env["STUB_NO_GIT"] = "1"
    r = subprocess.run([sys.executable, LINUX] + args, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    calls = open(log).read().splitlines() if os.path.exists(log) else []
    return r.returncode, r.stdout + r.stderr, calls


def check_disk(failures):
    """`status` prints the free space and each clone's size; `sync`,
    `run-lane` and `seed` refuse under the threshold before any sync call,
    naming the clones; `remove-clone` refuses each bad name, this checkout's
    own clone, and a directory with no `.git` without removing anything, and
    sends `rm -rf -- DIR` as one argument for a good one."""
    code, said, calls = run_disk(["status"], 5 * GIB, "status")
    for text in ("the VM has 5.0 GiB free on /", "clone old, 2.9 GiB", "clone new, 1.0 GiB"):
        if text not in said:
            failures.append("`status` does not print %r: %s" % (text, said.strip()[:300]))
    for command in (["sync"], ["run-lane"], ["seed"], ["lane"]):
        code, said, calls = run_disk(command, GIB, "low-" + command[0])
        if code == 0 or "under the 2.0 GiB" not in said or "old (2.9 GiB), new (1.0 GiB)" not in said \
                or "remove-clone NAME" not in said:
            failures.append("`%s` with 1 GiB free exits %d, and does not refuse naming the clones: %s"
                            % (command[0], code, said.strip()[:300]))
        if any(call.startswith("[bash]") or call.startswith("[git]") for call in calls):
            failures.append("`%s` with 1 GiB free still syncs: %r" % (command[0], calls))
    code, said, calls = run_disk(["sync"], 5 * GIB, "enough")
    # The stub has no mounts, so a sync that gets past the check stops at
    # its mount lookup.
    if "under the" in said or "no mount of the" not in said:
        failures.append("`sync` with 5 GiB free is refused for its disk or never goes on: %r %s"
                        % (calls, said.strip()[:300]))
    own = os.path.basename(REPO)
    for bad in ("", ".", "..", "a/b", "../x", "a b", "a;b", "$HOME", "/abs", "a\\nb", own):
        code, said, calls = run_disk(["remove-clone", bad], 5 * GIB, "bad")
        if code != 2 or calls:
            failures.append("`remove-clone %r` exits %d with the VM calls %r, not 2 and none: %s"
                            % (bad, code, calls, said.strip()[:300]))
    for args in ([], ["a", "b"], ["--self"]):
        code, said, calls = run_disk(["remove-clone"] + args, 5 * GIB, "usage")
        if code != 2 or calls:
            failures.append("`remove-clone %s` exits %d with the VM calls %r, not 2 and none"
                            % (" ".join(args), code, calls))
    code, said, calls = run_disk(["remove-clone", "gone"], 5 * GIB, "nogit", no_git=True)
    if code == 0 or any(call.startswith("[rm]") for call in calls):
        failures.append("`remove-clone` of a directory with no .git exits %d and calls %r" % (code, calls))
    want = ["[printenv][HOME]", "[test][-d][/home/stub/sawlang/p1113.x_y-1/.git]",
            "[rm][-rf][--][/home/stub/sawlang/p1113.x_y-1]", "[df][-B1][--output=avail][/]"]
    code, said, calls = run_disk(["remove-clone", "p1113.x_y-1"], 5 * GIB, "good")
    if code != 0 or calls != ["[printenv][HOME]"] + want[1:] or "removed /home/stub/sawlang/p1113.x_y-1" not in said \
            or "5.0 GiB free" not in said:
        failures.append("`remove-clone p1113.x_y-1` exits %d, sends %r, not %r: %s"
                        % (code, calls, want, said.strip()[:300]))
    code, said, calls = run_disk(["remove-clone", own, "--self"], 5 * GIB, "self")
    if code != 0 or "[rm][-rf][--][/home/stub/sawlang/%s]" % own not in calls:
        failures.append("`remove-clone %s --self` exits %d, sends %r" % (own, code, calls))


def main():
    failures = []
    check_shell_input(failures)
    check_disk(failures)
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
    # The VM has no v0 compiler, so its clone cannot record the run lane's
    # oracle: `stage0` is no command, refused with the usage before any VM call.
    r = subprocess.run([sys.executable, LINUX, "stage0"], cwd=REPO, capture_output=True, text=True, timeout=60)
    if r.returncode != 2 or "stage0" in r.stdout + r.stderr:
        failures.append("`stage0` exits %d, not 2 with a usage that never names it: %s"
                        % (r.returncode, (r.stdout + r.stderr).strip()[:300]))
    for failure in failures:
        print(failure)
    print("linux tool: %s: %d stub cases, `stage0` refused, `shell` carries its standard input, the disk checks"
          % ("FAIL (%d)" % len(failures) if failures else "ok", len(CASES)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

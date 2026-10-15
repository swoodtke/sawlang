#!/usr/bin/env python3
"""Linux builds through the `sawlang-linux` Lima VM (SL-536).

    tools/linux.py status            # the VM, its toolchain, and this checkout's clone in it
    tools/linux.py sync              # clone or fetch this checkout's HEAD into the VM
    tools/linux.py shell [CMD...]    # CMD (or a login shell) in the VM's clone
    tools/linux.py run-lane [--arch aarch64|x86_64] [NAME...]
                                     # sync, build the stages in the VM, run the run lane
                                     # (x86_64: cross-built, run under Rosetta)
    tools/linux.py lane              # the battery's `linux` lane: run-lane on both arches,
                                     # or a passing SKIP when the VM is not running
    tools/linux.py seed              # a seed bump's Linux half: sync, write the Linux targets'
                                     # seed in the VM, copy it into this checkout
    tools/linux.py stage0 [NAME...]  # sync, record Stage 0's run-lane runs in the VM, copy
                                     # them into compiler/tests/run/stage0/

The VM is `tools/lima/sawlang-linux.yaml`. This tool never starts, stops or
creates it: starting it from inside a sandboxed session fails at the
Virtualization framework, so the user starts it. When it is not running, or
limactl is not installed, every command exits 3 after saying how to start it,
which is what lets the `linux` battery lane skip rather than fail. When
limactl is installed but cannot report Lima's state, every command exits 4
with limactl's message: the VM's state is unknown, and the lane fails on it
(tools/test_linux.py pins both).

The host checkout is mounted read-only, so the VM builds in a clone on its own
disk, `~/sawlang/<checkout name>`. `sync` carries COMMITS: the clone is checked
out at this checkout's HEAD, and uncommitted changes stay behind (it warns).
The clone gets its own `.venv`, Python 3.14 from uv with sawc's requirements
and llvmlite pinned as on the Mac, so Stage 0 can record the run lane's
Linux oracle inside the VM (`stage0`), and every stage is built natively
there from the Linux seed.
`seed` writes that seed (compiler/README.md, "The seed"): Stage 1 built in the
VM emits it, and it is copied back over this checkout's `compiler/seed/`.
"""
import json
import os
import shutil
import subprocess
import sys

VM = "sawlang-linux"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "tools", "lima", "sawlang-linux.yaml")
EXIT_NOT_RUNNING = 3
# limactl is installed but cannot report Lima's state (a sandbox that cannot
# read ~/.lima, say): the VM's state is unknown, which is no reason to skip.
EXIT_LIMA_FAILED = 4
# The Stage 0 environment the clone's venv gets: the Mac's Python minor and
# its llvmlite, exactly.
PYTHON = "3.14"
LLVMLITE = "llvmlite==0.48.0"
UV = "$HOME/.local/bin/uv"
# Each arch the run lane runs on, and the target sawc2 cross-builds for it:
# None is the VM's own (native aarch64); x86_64 binaries run under Rosetta.
ARCHES = {"aarch64": None, "x86_64": "x86_64-unknown-linux-gnu"}
# The seeds a bump writes in the VM, each a directory of compiler/seed/.
LINUX_SEEDS = ("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu")


class VmError(Exception):
    """What stops a command, with the exit status it ends with."""

    def __init__(self, message, status=1):
        super().__init__(message)
        self.status = status


def limactl(args, **kwargs):
    try:
        return subprocess.run(["limactl"] + args, **kwargs)
    except FileNotFoundError:
        raise VmError("linux: limactl is not installed; Lima runs the `%s` VM (%s)" % (VM, rel(CONFIG)),
                      EXIT_NOT_RUNNING)


def rel(path):
    return os.path.relpath(path, REPO)


def instance():
    """The VM's `limactl list --json` record, once it is known to be running.

    Every instance is listed rather than the VM by name, because limactl
    exits 1 both for a name it has no instance of and for a Lima state it
    cannot read; listing them all fails only for the second, which is
    `EXIT_LIMA_FAILED` with limactl's own words, never "no VM"."""
    r = limactl(["list", "--json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise VmError("linux: limactl cannot list Lima's instances, so whether the `%s` VM runs is unknown "
                      "(limactl exited %d): %s" % (VM, r.returncode, (r.stderr or r.stdout).strip() or "no output"),
                      EXIT_LIMA_FAILED)
    record = None
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        try:
            one = json.loads(line)
        except ValueError:
            raise VmError("linux: `limactl list --json` printed a line that is not JSON, so whether the `%s` VM "
                          "runs is unknown: %s" % (VM, line.strip()[:300]), EXIT_LIMA_FAILED)
        if isinstance(one, dict) and one.get("name") == VM:
            record = one
    if record is None:
        raise VmError("linux: there is no `%s` VM; create it once with `limactl start --name=%s %s`, "
                      "then run this again (this tool never creates or starts it)" % (VM, VM, rel(CONFIG)),
                      EXIT_NOT_RUNNING)
    if record.get("status") != "Running":
        raise VmError("linux: the `%s` VM is %s; start it with `limactl start %s`, then run this again "
                      "(this tool never starts it)" % (VM, record.get("status", "not running").lower(), VM),
                      EXIT_NOT_RUNNING)
    return record


def vm_path(record, host_path):
    """Where the VM sees `host_path`, through the mounts its config names."""
    for mount in record.get("config", {}).get("mounts", []):
        location = os.path.expanduser(mount.get("location", ""))
        point = mount.get("mountPoint") or location
        if host_path == location or host_path.startswith(location.rstrip("/") + "/"):
            return point.rstrip("/") + host_path[len(location.rstrip("/")):]
    raise VmError("linux: no mount of the `%s` VM covers %s (the mounts are in %s)" % (VM, host_path, rel(CONFIG)))


def run_in_vm(argv, workdir="/tmp", capture=False):
    """`argv` run in the VM from `workdir`; limactl quotes each argument."""
    return limactl(["shell", "--workdir", workdir, VM, "--"] + argv, capture_output=capture, text=True)


def vm_home():
    r = run_in_vm(["printenv", "HOME"], capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise VmError("linux: cannot read the VM's home directory: %s" % r.stderr.strip())
    return r.stdout.strip()


def clone_dir():
    return "%s/sawlang/%s" % (vm_home(), os.path.basename(REPO))


def host_git(args):
    r = subprocess.run(["git"] + args, cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise VmError("linux: git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


# Run in the VM as `bash -c SCRIPT sync SOURCE SHA DEST`: the clone is made
# once, then fetched and checked out at the host's HEAD; ignored files (the
# venv, `.build/`'s caches) survive, anything else untracked does not.
SYNC_SCRIPT = r"""
set -eu
source="$1"; sha="$2"; dest="$3"
git_() { git -c safe.directory='*' "$@"; }
if [ ! -d "$dest/.git" ]; then
    mkdir -p "$(dirname "$dest")"
    git_ clone -q --no-checkout "$source" "$dest"
fi
cd "$dest"
git_ fetch -q "$source" "$sha"
git_ checkout -q --force --detach "$sha"
git_ clean -fdq
if [ ! -x .venv/bin/python ]; then
    __UV__ venv -q --python __PYTHON__ .venv
fi
__UV__ pip install -q --python .venv/bin/python -r sawc/requirements.txt "__LLVMLITE__"
echo "linux: $dest at $(git_ rev-parse --short HEAD), $(.venv/bin/python --version), \
llvmlite $(.venv/bin/python -c 'import llvmlite; print(llvmlite.__version__)')"
""".replace("__UV__", UV).replace("__PYTHON__", PYTHON).replace("__LLVMLITE__", LLVMLITE)


def sync(record):
    """The VM's clone of this checkout, brought to its HEAD; its path."""
    common = host_git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    sha = host_git(["rev-parse", "HEAD"])
    if host_git(["status", "--porcelain", "--untracked-files=no"]):
        print("linux: warning: this checkout has uncommitted changes, which sync does not carry")
    dest = clone_dir()
    r = run_in_vm(["bash", "-c", SYNC_SCRIPT, "sync", vm_path(record, common), sha, dest])
    if r.returncode != 0:
        raise VmError("linux: sync failed (exit %d)" % r.returncode)
    return dest


def command_status(record, _args):
    print("linux: the `%s` VM is running (%s, %s CPUs, %s)" % (VM, record.get("arch"), record.get("cpus"),
                                                              record.get("vmType")))
    probe = ("for c in clang-19 clang; do command -v $c >/dev/null && echo \"$c: $($c --version | head -1)\"; "
             "done; echo \"uv: $(%s --version 2>/dev/null || echo missing)\"; "
             "dest=\"$1\"; if [ -d \"$dest/.git\" ]; then echo \"clone: $dest at "
             "$(git -c safe.directory='*' -C \"$dest\" rev-parse --short HEAD)\"; "
             "else echo \"clone: none yet (tools/linux.py sync)\"; fi" % UV)
    r = run_in_vm(["bash", "-c", probe, "status", clone_dir()])
    print("host: %s at %s" % (REPO, host_git(["rev-parse", "--short", "HEAD"])))
    return r.returncode


def command_sync(record, _args):
    sync(record)
    return 0


def command_shell(record, args):
    if args[:1] == ["--"]:
        args = args[1:]
    dest = clone_dir()
    exists = run_in_vm(["test", "-d", dest], capture=True).returncode == 0
    if not exists:
        raise VmError("linux: the VM has no clone of this checkout yet; run `tools/linux.py sync`")
    if not args:
        return limactl(["shell", "--workdir", dest, VM]).returncode
    return run_in_vm(args, workdir=dest).returncode


def command_run_lane(record, args):
    arch = "aarch64"
    names = []
    i = 0
    while i < len(args):
        if args[i] == "--arch" and i + 1 < len(args):
            arch = args[i + 1]
            i += 2
            continue
        if args[i].startswith("-"):
            return usage()
        names.append(args[i])
        i += 1
    if arch not in ARCHES:
        print("linux: --arch is one of %s" % ", ".join(ARCHES))
        return 2
    target = ARCHES[arch]
    dest = sync(record)
    stages = [".venv/bin/python", "compiler/tools/build.py"] + (["--runtime", target] if target else [])
    build = run_in_vm(stages, workdir=dest)
    if build.returncode != 0:
        print("linux: the stages do not build in the VM (exit %d)" % build.returncode)
        return build.returncode
    lane = [".venv/bin/python", "compiler/tests/run/run_lane.py"] + (["--target", target] if target else [])
    return run_in_vm(lane + names, workdir=dest).returncode


def command_seed(record, args):
    """The VM's Stage 1, built from the current seed, writes the Linux
    targets' seed of HEAD in the clone, which replaces this checkout's."""
    if args:
        return usage()
    dest = sync(record)
    write = [".venv/bin/python", "compiler/tools/seed.py", "write"]
    for target in LINUX_SEEDS:
        write += ["--target", target]
    r = run_in_vm(write, workdir=dest)
    if r.returncode != 0:
        print("linux: the VM does not write the seed (exit %d)" % r.returncode)
        return r.returncode
    seeds = os.path.join(REPO, "compiler", "seed")
    for target in LINUX_SEEDS:
        shutil.rmtree(os.path.join(seeds, target), ignore_errors=True)
        r = limactl(["copy", "-r", "%s:%s/compiler/seed/%s" % (VM, dest, target), seeds])
        if r.returncode != 0:
            raise VmError("linux: cannot copy compiler/seed/%s out of the VM (exit %d)" % (target, r.returncode))
        print("linux: compiler/seed/%s" % target)
    print("linux: written from %s; `compiler/tools/seed.py check` checks them against the pin"
          % host_git(["rev-parse", "--short", "HEAD"]))
    return 0


def command_stage0(record, args):
    """The VM's Stage 0 records the run lane's runs of HEAD's programs (or
    the NAMEs) for its host, and that host's records replace this
    checkout's (compiler/tests/run/README.md, "The oracle")."""
    if any(a.startswith("-") for a in args):
        return usage()
    dest = sync(record)
    r = run_in_vm([".venv/bin/python", "compiler/tests/run/run_lane.py", "--stage0"] + args, workdir=dest)
    if r.returncode != 0:
        print("linux: the VM does not record Stage 0's runs (exit %d)" % r.returncode)
        return r.returncode
    records = os.path.join(REPO, "compiler", "tests", "run", "stage0")
    host = "aarch64-unknown-linux-gnu"
    if not args:
        shutil.rmtree(os.path.join(records, host), ignore_errors=True)
    os.makedirs(records, exist_ok=True)
    r = limactl(["copy", "-r", "%s:%s/compiler/tests/run/stage0/%s" % (VM, dest, host), records])
    if r.returncode != 0:
        raise VmError("linux: cannot copy compiler/tests/run/stage0/%s out of the VM (exit %d)"
                      % (host, r.returncode))
    print("linux: compiler/tests/run/stage0/%s, recorded at %s" % (host, host_git(["rev-parse", "--short",
                                                                                     "HEAD"])))
    return 0


COMMANDS = {
    "status": command_status,
    "sync": command_sync,
    "shell": command_shell,
    "run-lane": command_run_lane,
    "seed": command_seed,
    "stage0": command_stage0,
}


def usage():
    print(__doc__.split("\n\n")[1])
    return 2


def lane(argv):
    """The battery's `linux` lane: the run lane on every arch, or a SKIP that
    passes when the VM is known not to run (exit 3). Any other refusal,
    limactl failing to report Lima's state among them, fails with its reason.
    Returns the number of failing arches, or the refusal's status."""
    if argv:
        return usage()
    try:
        record = instance()
    except VmError as e:
        if e.status == EXIT_NOT_RUNNING:
            print("linux: SKIPPED, not failed: %s" % e)
            return 0
        print(e)
        return e.status
    failed = 0
    for arch in ARCHES:
        print("--- linux run lane, %s" % arch)
        try:
            status = command_run_lane(record, ["--arch", arch])
        except VmError as e:
            print(e)
            status = e.status
        if status != 0:
            failed += 1
    return failed


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)
    if argv[:1] == ["lane"]:
        return lane(argv[1:])
    if not argv or argv[0] not in COMMANDS:
        return usage()
    try:
        record = instance()
        return COMMANDS[argv[0]](record, argv[1:])
    except VmError as e:
        print(e)
        return e.status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

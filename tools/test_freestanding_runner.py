#!/usr/bin/env python3
"""tools/freestanding_runner.py's verdicts on its prerequisites, against stub tools.

    python tools/test_freestanding_runner.py

The freestanding suite skips, and passes, only when QEMU, ld.lld or a clang for
the target is known absent: not on PATH, or no clang `build.pick_clang` would
choose. When their presence cannot be determined it fails (exit 4): no PATH at
all, a tool on PATH that does not answer `--version`, or a `SAWC_CLANG` naming
no usable clang. Each case runs the runner's `--tools` decision with stub tools
first on a PATH that holds no real ones, with `HOMEBREW_PREFIX` naming no
Homebrew, so nothing is built or booted.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, HERE)

import build  # noqa: E402
import freestanding_runner  # noqa: E402

RUNNER = os.path.join(HERE, "freestanding_runner.py")
OUT = os.path.join(build.BUILD_DIR, "test-freestanding-runner")
ARCHES = [a for a in freestanding_runner.ARCHES if not a["off"]]
# The runner probes the arches in order, so the first one's QEMU is the one an
# absence or a refusal is reported for.
QEMU = ARCHES[0]["qemu"]
# Where `build.homebrew_clang()` looks, pointed at nothing: a clang outside
# PATH would otherwise answer every case that has the stubs alone.
NO_HOMEBREW = os.path.join(OUT, "no-homebrew")

ANSWERS = "#!/bin/sh\necho '%s 0.0 (stub)'\nexit 0\n"
REFUSES = "#!/bin/sh\necho '%s: cannot run here' >&2\nexit 1\n"
EVERY_QEMU = dict((a["qemu"], ANSWERS) for a in ARCHES)


def present(over=None):
    """ld.lld and every arch's QEMU answering, then the stubs of `over` in
    their place or beside them."""
    found = {"ld.lld": ANSWERS}
    found.update(EVERY_QEMU)
    found.update(over or {})
    return found


# (case, {stub name: body}, PATH entries after the stubs or None for no PATH,
# SAWC_CLANG, the exit status, text the output holds, whether it says SKIPPED).
# `{real}` in SAWC_CLANG is a clang on this machine that compiles for every
# arch; a case naming it is passed over where there is none.
CASES = (
    ("no ld.lld", {}, [], None, 0, "ld.lld is not on PATH", True),
    ("no QEMU", {"ld.lld": ANSWERS}, [], None, 0, "%s is not on PATH" % QEMU, True),
    ("no clang", present(), [], None, 0, "no clang compiles for", True),
    ("a clang without the target", present({"clang": REFUSES}), [], None, 0, "does not compile opaque-pointer IR",
     True),
    ("ld.lld does not answer", {"ld.lld": REFUSES}, [], None, 4, "so whether it runs is unknown", False),
    ("QEMU does not answer", present({QEMU: REFUSES}), [], None, 4, "so whether it runs is unknown", False),
    ("no PATH", {}, None, None, 4, "PATH is not set", False),
    ("SAWC_CLANG names nothing", present(), [], "/nonexistent/clang", 4, "SAWC_CLANG names no clang", False),
    ("all present", present(), [], "{real}", 0, "every prerequisite is present", False),
)


def run_case(name, stubs, after, sawc_clang):
    """(exit status, output) of `--tools` under one set of stubs."""
    bin_dir = os.path.join(OUT, name.replace(" ", "-"))
    shutil.rmtree(bin_dir, ignore_errors=True)
    os.makedirs(bin_dir)
    for tool, body in stubs.items():
        path = os.path.join(bin_dir, tool)
        with open(path, "w") as fh:
            fh.write(body % tool)
        os.chmod(path, 0o755)
    env = dict(os.environ)
    env.pop("PATH", None)
    env.pop("SAWC_CLANG", None)
    env["HOMEBREW_PREFIX"] = NO_HOMEBREW
    if after is not None:
        env["PATH"] = os.pathsep.join([bin_dir] + after)
    if sawc_clang is not None:
        env["SAWC_CLANG"] = sawc_clang
    r = subprocess.run([sys.executable, RUNNER, "--tools"], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=180)
    return r.returncode, r.stdout + r.stderr


def main():
    real, _ = build.pick_clang(ARCHES[0]["triple"], None)
    if real is not None and not all(build.clang_capable(real, a["triple"]) for a in ARCHES):
        real = None
    failures = []
    ran = 0
    for name, stubs, after, sawc_clang, want_status, text, skipped in CASES:
        if sawc_clang == "{real}":
            if real is None:
                print("freestanding runner: passed over %r: no clang here compiles for every one of %s"
                      % (name, ", ".join(a["triple"] for a in ARCHES)))
                continue
            sawc_clang = real
        ran += 1
        status, said = run_case(name, stubs, after, sawc_clang)
        if status != want_status or text not in said:
            failures.append("%s: `--tools` exits %d, not %d, or does not say %r: %s"
                            % (name, status, want_status, text, said.strip()[:400]))
        if skipped and "SKIPPED" not in said:
            failures.append("%s: passes without saying it SKIPPED: %s" % (name, said.strip()[:400]))
        if not skipped and "SKIPPED" in said:
            failures.append("%s: says it SKIPPED: %s" % (name, said.strip()[:400]))
    for failure in failures:
        print(failure)
    print("freestanding runner: %s: %d stub cases" % ("FAIL (%d)" % len(failures) if failures else "ok", ran))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

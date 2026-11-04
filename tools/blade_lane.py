#!/usr/bin/env python3
"""The Blade lane: Blade built by sawc, self-built, and run over its packages.

    tools/blade_lane.py

Steps, each printed, the first failure ending the run:
  1. sawc builds Blade from blade/ (`build_blade`).
  2. That Blade builds blade/ itself.
  3. The self-built Blade runs `blade test` in blade/ and in each package
     under libs/.
  4. `blade new` and `blade run` make and run a package in a directory under
     `.build/`.

Every compile goes through `build.SAWC`, handed to Blade as `SAWC`. The suite
lock is not taken here: the battery and the patch gate run this inside the lock
their caller already holds. Child processes start through tools/child_groups.py.

ENTRY POINTS:
  build_blade
  ensure_blade
  blade_environment
"""
import os
import shutil
import sys
import subprocess
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build  # noqa: E402
import child_groups  # noqa: E402
import patch_gate  # noqa: E402

BLADE_DIR = os.path.join(REPO, "blade")
LIBS_DIR = os.path.join(REPO, "libs")
LIBRARIES = ("semver", "toml", "imgformat")
WORK_DIR = os.path.join(build.BUILD_DIR, "blade_lane")
BLADE_BINARY = os.path.join(WORK_DIR, "blade")
SMOKE_DIR = os.path.join(WORK_DIR, "smoke")
SELF_BUILT = os.path.join(BLADE_DIR, ".build", "host", "blade")
SMOKE_PACKAGE = "smoke_app"
BUILD_TIMEOUT_S = 900
TEST_TIMEOUT_S = 900
SMOKE_TIMEOUT_S = 300

# Blade's own module path: its package and the three libraries it imports.
MODULE_PATHS = (
    ("blade", os.path.join(BLADE_DIR, "src")),
    ("toml", os.path.join(LIBS_DIR, "toml", "src")),
    ("semver", os.path.join(LIBS_DIR, "semver", "src")),
    ("imgformat", os.path.join(LIBS_DIR, "imgformat", "src")),
)

_build_lock = threading.Lock()
_built = []


def blade_environment(extra=None):
    """The environment a Blade child runs in: this checkout's sawc as `SAWC`."""
    env = dict(os.environ)
    env["SAWC"] = build.SAWC
    if extra:
        env.update(extra)
    return env


def run(argv, timeout, cwd=REPO, env=None):
    """(exit status or None on a timeout, combined output) of `argv`."""
    try:
        proc = child_groups.start(argv, cwd=cwd, env=env if env is not None else blade_environment(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as e:
        return 127, "%s: %s" % (argv[0], e)
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        out, _ = proc.communicate()
        code = None
    finally:
        child_groups.forget(proc)
    return code, out or ""


def blade_build_arguments(out, compiler=None, flags=()):
    """The argv that has `compiler` (default `build.SAWC`) build Blade into
    `out`; `flags` follow `build`. The compile benchmark shares it."""
    argv = [compiler or build.SAWC, "build"] + list(flags) + [os.path.join(BLADE_DIR, "src", "main.saw"), "-o", out]
    for name, directory in MODULE_PATHS:
        argv += ["--module-path", "%s=%s" % (name, directory)]
    return argv


def build_blade():
    """Compile Blade with sawc into `BLADE_BINARY`: (ok, output)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    code, out = run(blade_build_arguments(BLADE_BINARY), BUILD_TIMEOUT_S)
    return code == 0, out


def ensure_blade():
    """`BLADE_BINARY`, built once per process; raises RuntimeError when sawc cannot build it."""
    with _build_lock:
        if not _built:
            ok, out = build_blade()
            if not ok:
                raise RuntimeError("sawc does not build Blade\n%s" % out)
            _built.append(BLADE_BINARY)
    return BLADE_BINARY


class Failure(Exception):
    pass


def step(title, argv, timeout, cwd=REPO, expect=None):
    """Run one step, print its title, and raise Failure unless it exits 0 and
    (when given) its output holds `expect`."""
    print("blade: %s" % title, flush=True)
    code, out = run(argv, timeout, cwd=cwd)
    if code is None:
        raise Failure("%s timed out after %ds\n%s" % (title, timeout, out))
    if code != 0:
        raise Failure("%s exited %d\n%s" % (title, code, out))
    if expect is not None and expect not in out:
        raise Failure("%s did not print %r\n%s" % (title, expect, out))
    return out


def tests_passed(title, binary, cwd):
    out = step(title, [binary, "test"], TEST_TIMEOUT_S, cwd=cwd)
    summary = [line for line in out.splitlines() if line.startswith("test result:")]
    print("      " + (summary[-1] if summary else "(no summary line)"), flush=True)
    if not summary or " 0 failed" not in summary[-1]:
        raise Failure("%s: no passing summary\n%s" % (title, out))


def lane():
    ok, out = (True, "") if build.handed_down() else build.build_sawc()
    if not ok:
        print("%s\nblade: FAIL: sawc does not build" % out)
        return 1
    try:
        print("blade: sawc builds Blade", flush=True)
        ok, out = build_blade()
        if not ok:
            raise Failure("sawc does not build Blade\n%s" % out)
        if os.path.exists(SELF_BUILT):
            os.remove(SELF_BUILT)
        step("Blade builds itself", [BLADE_BINARY, "build"], BUILD_TIMEOUT_S, cwd=BLADE_DIR)
        if not os.path.exists(SELF_BUILT):
            raise Failure("the self-build left no %s" % SELF_BUILT)
        tests_passed("blade test in blade/", SELF_BUILT, BLADE_DIR)
        for lib in LIBRARIES:
            tests_passed("blade test in libs/%s" % lib, SELF_BUILT, os.path.join(LIBS_DIR, lib))
        shutil.rmtree(SMOKE_DIR, ignore_errors=True)
        os.makedirs(SMOKE_DIR)
        step("blade new", [SELF_BUILT, "new", SMOKE_PACKAGE], SMOKE_TIMEOUT_S, cwd=SMOKE_DIR,
             expect="Created")
        step("blade run", [SELF_BUILT, "run"], SMOKE_TIMEOUT_S, cwd=os.path.join(SMOKE_DIR, SMOKE_PACKAGE),
             expect="Hello, %s!" % SMOKE_PACKAGE)
    except Failure as e:
        print("blade: FAIL: %s" % e)
        return 1
    print("blade: ok")
    return 0


if __name__ == "__main__":
    child_groups.install()
    # sawc's builds of Blade, and Blade's own, share the run's sawc cache.
    patch_gate.gate_cache()
    sys.exit(lane())

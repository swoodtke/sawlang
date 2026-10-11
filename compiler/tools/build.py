#!/usr/bin/env python3
"""Build the self-hosted compiler: Stage 1 with the frozen compiler, Stage 2
with Stage 1.

    python compiler/tools/build.py                   # .build/sawc2, then .build/sawc2-stage2
    python compiler/tools/build.py ENTRY.saw -o OUT  # any program over the stages, by Stage 0

The numbering is the conventional one: Stage 0 is the frozen Python compiler
in `sawc/`, Stage 1 is the sawc2 it builds (`.build/sawc2`), and Stage 2 is
sawc2 built by Stage 1 at -O2 (`.build/sawc2-stage2`). The lanes run Stage 2;
`SAWC2_STAGE=1` selects Stage 1 instead, for bisecting a difference between
the two, and then Stage 2 is not built. `SAWC2` is the binary selected.

Stage 2 is cached: its key covers Stage 1's object, the sources Stage 1
compiles, the link script, the runtime objects and clang, so an unchanged
tree links nothing. Stage 1 is rebuilt on every call, as Stage 0 has no cache
of its own.

The interpreter running this script runs `sawc/sawc.py`, so invoke it with the
venv's Python. `STAGE_PACKAGES` is the one place that maps a stage package to
its directory: the driver, the unit programs and the runner all build through
`build_program`, so a new stage is registered here once.
"""
import argparse
import hashlib
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FROZEN_SAWC = os.path.join(REPO, "sawc", "sawc.py")
BUILD_DIR = os.path.join(REPO, ".build")
STAGE1 = os.path.join(BUILD_DIR, "sawc2")
# The object Stage 0 writes beside Stage 1 and links it from.
STAGE1_OBJECT = STAGE1 + ".o"
STAGE2 = os.path.join(BUILD_DIR, "sawc2-stage2")
STAGE2_KEY = STAGE2 + ".key"
DRIVER_ENTRY = os.path.join(REPO, "compiler", "driver", "src", "main.saw")
LINK_SCRIPT = os.path.join(REPO, "compiler", "driver", "sawc2")
RUNTIME_OBJECTS = os.path.join(REPO, "compiler", "tools", "runtime_objects.py")
STD_ROOT = os.path.join(REPO, "std")
LINK_TIMEOUT = 1800

# (package name, source directory relative to the repo root). The directory is
# the package's module root, as `--module-path NAME=DIR` defines it: the others
# import a stage as `<name>.<module>`, and `<name>` alone is its `lib.saw`.
STAGE_PACKAGES = (
    ("sawlex", "compiler/lex/src"),
    ("sawparse", "compiler/parse/src"),
    ("sawresolve", "compiler/resolve/src"),
    ("sawtypecheck", "compiler/typecheck/src"),
    ("sawmir", "compiler/mir/src"),
    ("saweval", "compiler/eval/src"),
    ("sawborrowck", "compiler/borrowck/src"),
    ("sawdrops", "compiler/drops/src"),
    ("sawtarget", "compiler/target/src"),
    ("sawmono", "compiler/mono/src"),
    ("sawllvm", "compiler/llvm/src"),
)


def selected_stage():
    """The stage `SAWC2_STAGE` names, 2 when it is unset."""
    stage = os.environ.get("SAWC2_STAGE", "2")
    if stage not in ("1", "2"):
        sys.exit("build: SAWC2_STAGE is %r; it names Stage 1 or Stage 2" % stage)
    return int(stage)


SAWC2 = STAGE2 if selected_stage() == 2 else STAGE1


def sawc_arguments(entry, out):
    """The frozen compiler's command-line arguments for building `entry` to
    `out`: what `build_program` runs, and what `std_cone.py` runs in-process."""
    args = [entry, "-o", out]
    for name, rel in STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, os.path.join(REPO, rel))]
    return args


def package_arguments(root):
    """`--module-path` for every stage package, under the tree at `root`."""
    args = []
    for name, rel in STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, os.path.join(root, rel))]
    return args


def build_program(entry, out):
    """Compile `entry` to the executable `out` with Stage 0. Returns (ok,
    compiler output)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    argv = [sys.executable, FROZEN_SAWC] + sawc_arguments(entry, out)
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def link_driver(compiler, out):
    """The driver built by the sawc2 binary `compiler` at -O2 and linked into
    `out`; the error text, or "" when it linked. Stage 2 and Stage 3 are both
    linked here, so the fixpoint compares two links made the same way."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    env = dict(os.environ)
    env["SAWC2_BIN"] = compiler
    env["SAW_PYTHON"] = sys.executable
    r = subprocess.run([LINK_SCRIPT, "build", "-O2", "--std-root", "std"] + package_arguments(REPO)
                       + [os.path.relpath(DRIVER_ENTRY, REPO), "-o", out], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=LINK_TIMEOUT)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip()[:600] or "it exited %d" % r.returncode
    return ""


def build_stage1():
    """Stage 0 builds the driver into `.build/sawc2`. Returns (ok, output)."""
    return build_program(DRIVER_ENTRY, STAGE1)


def _hash_tree(digest, root):
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(directory, name)
            digest.update(os.path.relpath(path, REPO).encode("utf-8") + b"\0")
            with open(path, "rb") as fh:
                digest.update(hashlib.sha256(fh.read()).digest())


def stage2_key():
    """What Stage 2 is a function of: Stage 1's code, the trees it compiles,
    the link script, the runtime objects both links take and the clang that
    links them. Stage 1's code is the object Stage 0 links it from, since the
    linker stamps each Stage 1 binary with a fresh UUID. None when Stage 1's
    object is missing or the runtime objects cannot be named."""
    if not os.path.exists(STAGE1_OBJECT):
        return None
    digest = hashlib.sha256()
    with open(STAGE1_OBJECT, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    for root in [os.path.join(REPO, rel) for _, rel in STAGE_PACKAGES] + [os.path.dirname(DRIVER_ENTRY),
                                                                          STD_ROOT]:
        _hash_tree(digest, root)
    with open(LINK_SCRIPT, "rb") as fh:
        digest.update(fh.read())
    r = subprocess.run([sys.executable, RUNTIME_OBJECTS], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    for path in r.stdout.split():
        digest.update(path.encode("utf-8") + b"\0")
        with open(path, "rb") as fh:
            digest.update(hashlib.sha256(fh.read()).digest())
    clang = subprocess.run([os.environ.get("CLANG", "clang"), "--version"], capture_output=True, text=True)
    digest.update(clang.stdout.encode("utf-8"))
    return digest.hexdigest()


def build_stage2():
    """Stage 1 builds the driver into `.build/sawc2-stage2`, unless the cached
    link has the same key. Returns (ok, output)."""
    key = stage2_key()
    if key is None:
        return False, ("build: Stage 2's cache key needs %s and the runtime objects, and one is missing"
                       % os.path.relpath(STAGE1_OBJECT, REPO))
    if os.path.exists(STAGE2) and os.path.exists(STAGE2_KEY):
        with open(STAGE2_KEY) as fh:
            if fh.read().strip() == key:
                os.utime(STAGE2)
                return True, ""
    if os.path.exists(STAGE2_KEY):
        os.remove(STAGE2_KEY)
    why = link_driver(STAGE1, STAGE2)
    if why:
        return False, "Stage 1 does not build Stage 2: " + why
    with open(STAGE2_KEY + ".tmp", "w") as fh:
        fh.write(key + "\n")
    os.replace(STAGE2_KEY + ".tmp", STAGE2_KEY)
    return True, ""


def build_sawc2():
    """Build Stage 1, then Stage 2 unless Stage 1 is selected. Returns (ok,
    output)."""
    ok, output = build_stage1()
    if not ok or SAWC2 == STAGE1:
        return ok, output
    ok2, output2 = build_stage2()
    return ok2, "\n".join(part for part in (output, output2) if part)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entry", nargs="?", help="a program to build instead of sawc2")
    ap.add_argument("-o", dest="out", help="the output path (required with ENTRY)")
    args = ap.parse_args()
    if args.entry is None:
        ok, output = build_sawc2()
        target = SAWC2
    else:
        if args.out is None:
            ap.error("-o is required when an ENTRY is given")
        ok, output = build_program(os.path.abspath(args.entry), os.path.abspath(args.out))
        target = args.out
    if output:
        print(output)
    if not ok:
        print("build: FAILED: %s" % target)
        return 1
    print("build: %s" % os.path.relpath(target, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())

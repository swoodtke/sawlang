#!/usr/bin/env python3
"""Build the self-hosted compiler's programs with the frozen compiler (Stage 0).

    python compiler/tools/build.py                   # .build/sawc2
    python compiler/tools/build.py ENTRY.saw -o OUT  # any program over the stages

The interpreter running this script runs `sawc/sawc.py`, so invoke it with the
venv's Python. `STAGE_PACKAGES` is the one place that maps a stage package to
its directory: the driver, the unit programs and the runner all build through
`build_program`, so a new stage is registered here once.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FROZEN_SAWC = os.path.join(REPO, "sawc", "sawc.py")
BUILD_DIR = os.path.join(REPO, ".build")
SAWC2 = os.path.join(BUILD_DIR, "sawc2")
DRIVER_ENTRY = os.path.join(REPO, "compiler", "driver", "src", "main.saw")

# (package name, directory relative to the repo root). Each stage is a package
# the others import as `<name>.src.<module>`.
STAGE_PACKAGES = (
    ("sawlex", "compiler/lex"),
)


def build_program(entry, out):
    """Compile `entry` to the executable `out`. Returns (ok, compiler output)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    argv = [sys.executable, FROZEN_SAWC, entry, "-o", out]
    for name, rel in STAGE_PACKAGES:
        argv += ["--module-path", "%s=%s" % (name, os.path.join(REPO, rel))]
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def build_sawc2():
    """Build the driver to `.build/sawc2`. Returns (ok, compiler output)."""
    return build_program(DRIVER_ENTRY, SAWC2)


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

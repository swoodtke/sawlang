#!/usr/bin/env python3
"""Blade self-hosting bootstrap loop (design 64 B8).

Demonstrates that Blade builds and tests Blade through its own dependency
pipeline (resolve -> Saw.lock -> per-dep --module-path -> incremental), using
Blade's real path dependency `libs/toml`.

  stage0 : the in-tree sawc builds Blade directly (the kept bootstrap entry).
  stage1 : stage0 `blade build` compiles Blade through its own resolve / lock /
           module-path / incremental pipeline.
  test   : the stage1 binary runs Blade's full test suite (green).
  cache  : a second `blade build` reports "up to date" (incremental dogfood);
           `blade build --force` rebuilds -> stage2.
  stage2 : the stage2 binary runs the test suite again (closes the loop).

Run from the repo root:  ./.venv/bin/python tools/blade_bootstrap.py
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "bin", "python")
SAWC = os.path.join(REPO, "sawc", "sawc.py")
BLADE_DIR = os.path.join(REPO, "blade")
TOML_SRC = os.path.join(REPO, "libs", "toml", "src")
STAGE0 = os.path.join(REPO, ".build", "blade0")
STAGE_BIN = os.path.join(BLADE_DIR, "blade")   # blade's self-built binary

ENV = dict(os.environ)
ENV["SAWC"] = f"{PY} {SAWC}"   # blade build/test drive the in-tree compiler


def fail(msg, out=""):
    print(f"BOOTSTRAP FAILED: {msg}")
    if out:
        print(out)
    sys.exit(1)


def run(argv, **kw):
    # Plain pipe capture. The DF12 workaround (redirect-to-file + bounded retry
    # on a signal-killed build) is gone: design 67 root-caused and fixed the
    # memory corruption (an owning-payload enum / a struct-with-String field read
    # out of a container was bitwise-copied without a retain yet released at drop
    # -> double free), so blade's self-build is now deterministically clean,
    # including with a pipe as stdout.
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def main():
    # Clean prior stage artifacts so incremental state is fresh.
    for p in [os.path.join(BLADE_DIR, ".blade"), STAGE_BIN,
              os.path.join(BLADE_DIR, "blade.ll")]:
        subprocess.run(["rm", "-rf", p])

    # stage0: sawc builds blade directly (with the toml dependency mapped).
    print("== stage0: sawc builds blade ==")
    r = run([PY, SAWC, os.path.join(BLADE_DIR, "src", "main.saw"),
             "-o", STAGE0, "--module-path", f"toml={TOML_SRC}"])
    if r.returncode != 0:
        fail("stage0 build", r.stdout + r.stderr)

    # stage1: stage0 builds blade through its own pipeline.
    print("== stage1: blade build (own pipeline) ==")
    r = run([STAGE0, "build"], cwd=BLADE_DIR, env=ENV)
    if r.returncode != 0 or "Compiling" not in r.stdout:
        fail("stage1 build", r.stdout + r.stderr)
    print(r.stdout.strip())
    if not os.path.exists(STAGE_BIN):
        fail("stage1 binary missing")
    if not os.path.exists(os.path.join(BLADE_DIR, "Saw.lock")):
        fail("Saw.lock not written")

    # stage1 test: the self-built binary runs blade's suite.
    print("== stage1 test ==")
    r = run([STAGE_BIN, "test"], cwd=BLADE_DIR, env=ENV)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    if r.returncode != 0:
        fail("stage1 test", r.stdout + r.stderr)

    # incremental: a second build is up-to-date.
    print("== second build (expect up-to-date) ==")
    r = run([STAGE0, "build"], cwd=BLADE_DIR, env=ENV)
    if "up to date" not in r.stdout:
        fail("second build was not up-to-date", r.stdout + r.stderr)
    print(r.stdout.strip())

    # --force rebuilds -> stage2.
    print("== blade build --force (expect rebuild) ==")
    r = run([STAGE0, "build", "--force"], cwd=BLADE_DIR, env=ENV)
    if "Compiling" not in r.stdout:
        fail("--force did not rebuild", r.stdout + r.stderr)
    print(r.stdout.strip())

    # stage2 test closes the loop.
    print("== stage2 test ==")
    r = run([STAGE_BIN, "test"], cwd=BLADE_DIR, env=ENV)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    if r.returncode != 0:
        fail("stage2 test", r.stdout + r.stderr)

    # Clean the self-built binary (keep Saw.lock committed).
    subprocess.run(["rm", "-rf", STAGE_BIN, os.path.join(BLADE_DIR, "blade.ll")])

    print("BOOTSTRAP: ok")


if __name__ == "__main__":
    main()

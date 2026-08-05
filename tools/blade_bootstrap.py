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
  layout : design 143 — the artifact is in `.build/host/` and the package root
           is clean, a stale artifact from the old in-place layout is ignored
           rather than trusted, and two targets of one package build side by
           side without collision.

Run from the repo root:  ./.venv/bin/python tools/blade_bootstrap.py
"""
import os
import subprocess
import sys

from llvmlite import binding

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The interpreter running this script — locally that IS `.venv/bin/python`
# (llvmlite installed), and on CI it is the setup-python interpreter with
# llvmlite pip-installed. Using sys.executable instead of a hardcoded `.venv`
# path is what lets the bootstrap run in CI, which has no virtualenv.
PY = sys.executable
SAWC = os.path.join(REPO, "sawc", "sawc.py")
BLADE_DIR = os.path.join(REPO, "blade")
TOML_DIR = os.path.join(REPO, "libs", "toml")
SEMVER_DIR = os.path.join(REPO, "libs", "semver")
TOML_SRC = os.path.join(TOML_DIR, "src")
SEMVER_SRC = os.path.join(SEMVER_DIR, "src")
# The sosimg layout package (design 140): Blade's `emit = "sosimg"` target
# shares it with the SOS kernel, so stage0 needs it mapped like any other dep.
IMGFORMAT_DIR = os.path.join(REPO, "sos", "imgformat")
IMGFORMAT_SRC = os.path.join(IMGFORMAT_DIR, "src")
LIB_DIRS = [("toml", TOML_DIR), ("semver", SEMVER_DIR)]
STAGE0 = os.path.join(REPO, ".build", "blade0")

# Design 143: a package's build output lives in `<package>/.build/<target>/`,
# and `host` is the target name for a build that names no triple.
BLADE_BUILD = os.path.join(BLADE_DIR, ".build")
STAGE_BIN = os.path.join(BLADE_BUILD, "host", "blade")   # blade's self-built binary
# Where the old in-place layout put it. Nothing should write here again, and a
# file that appears here must never be mistaken for a build.
LEGACY_BIN = os.path.join(BLADE_DIR, "blade")
# The host triple, named explicitly, so one package can be built for two target
# NAMES on a machine that can only link for one of them. What is under test is
# the directory behavior, not cross-compilation.
HOST_TRIPLE = binding.get_default_triple()

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


def lib_tests(blade_bin):
    # Design 97: the `libs/toml` + `libs/semver` packages ship their own
    # `blade test` suites. Run them here — with SAWC set (via ENV) so blade drives
    # the in-tree compiler, exactly as the main build does — so the suites are
    # ACTUALLY validated as part of the standard bars instead of being a coverage
    # gap that "fails on a clean tree, pre-existing". A `blade test` in a package
    # dir writes only under its gitignored `.build/`.
    for name, d in LIB_DIRS:
        print(f"== libs/{name}: blade test ==")
        r = run([blade_bin, "test"], cwd=d, env=ENV)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        if r.returncode != 0 or "0 failed" not in r.stdout:
            fail(f"libs/{name} blade test", r.stdout + r.stderr)
        # The test binaries went under the per-target build directory, and
        # nothing landed in the package root.
        if not os.path.isdir(os.path.join(d, ".build", "host", "tests")):
            fail(f"libs/{name}: test binaries are not in .build/host/tests")
        # Design 143 lockfile policy: these are LIBRARIES, so Blade must not
        # leave a Saw.lock behind for the author to wonder about committing.
        if os.path.exists(os.path.join(d, "Saw.lock")):
            fail(f"libs/{name}: a library grew a Saw.lock")


def layout_checks():
    """Design 143: artifacts are per-target and never beside the source."""
    print("== layout: artifact placement ==")
    if not os.path.exists(STAGE_BIN):
        fail(f"artifact is not at {os.path.relpath(STAGE_BIN, REPO)}")
    for stray in ["blade", "blade.ll"]:
        if os.path.exists(os.path.join(BLADE_DIR, stray)):
            fail(f"a build left `{stray}` in the package root")
    if not os.path.exists(os.path.join(BLADE_BUILD, "host", "build-hash")):
        fail("the build stamp is not beside the artifact")
    print(f"  {os.path.relpath(STAGE_BIN, REPO)}; package root clean")


def stale_artifact_guard(blade0):
    """An artifact from the old in-place layout is IGNORED, never trusted.

    The incident this guards against: a build reports success (or "up to
    date") on the strength of a file that is not the thing it just built. Here
    the stamp still matches, so only the per-target artifact check stands
    between a stale binary and a build that never runs.
    """
    print("== layout: a stale in-place artifact is ignored ==")
    junk = b"this is not a binary\n"
    with open(LEGACY_BIN, "wb") as f:
        f.write(junk)
    os.remove(STAGE_BIN)
    try:
        r = run([blade0, "build"], cwd=BLADE_DIR, env=ENV)
        if r.returncode != 0:
            fail("build after removing the artifact", r.stdout + r.stderr)
        if "Compiling" not in r.stdout:
            fail("a stale in-place artifact was trusted as up to date",
                 r.stdout + r.stderr)
        if not os.path.exists(STAGE_BIN):
            fail("the rebuild did not produce the artifact")
        with open(LEGACY_BIN, "rb") as f:
            if f.read() != junk:
                fail("the build wrote to the old in-place path")
    finally:
        os.remove(LEGACY_BIN)
    print(f"  rebuilt; {os.path.relpath(LEGACY_BIN, REPO)} untouched")


def two_target_build(blade_bin):
    """One package, two target names, two artifacts, no collision."""
    print("== layout: two targets of one package ==")
    parent = os.path.join(REPO, ".build")
    pkg = os.path.join(parent, "twotarget")
    subprocess.run(["rm", "-rf", pkg])
    os.makedirs(parent, exist_ok=True)

    r = run([blade_bin, "new", "twotarget"], cwd=parent, env=ENV)
    if r.returncode != 0 or not os.path.isdir(pkg):
        fail("blade new", r.stdout + r.stderr)
    if not os.path.exists(os.path.join(pkg, ".gitignore")):
        fail("blade new did not scaffold a .gitignore")

    for args, target in [([], "host"), (["--target", HOST_TRIPLE], HOST_TRIPLE)]:
        r = run([blade_bin, "build"] + args, cwd=pkg, env=ENV)
        if r.returncode != 0 or "Compiling" not in r.stdout:
            fail(f"build for {target}", r.stdout + r.stderr)
        # A second build of the SAME target is up to date, and building the
        # other target in between did not disturb that.
        r = run([blade_bin, "build"] + args, cwd=pkg, env=ENV)
        if "up to date" not in r.stdout:
            fail(f"second build for {target} was not up to date",
                 r.stdout + r.stderr)

    for target in ["host", HOST_TRIPLE]:
        art = os.path.join(pkg, ".build", target, "twotarget")
        if not os.path.exists(art):
            fail(f"no artifact for target {target}")
        if not os.path.exists(os.path.join(pkg, ".build", target, "build-hash")):
            fail(f"no stamp for target {target}")
    if os.path.exists(os.path.join(pkg, "twotarget")):
        fail("an artifact landed in the package root")
    print(f"  host + {HOST_TRIPLE}, side by side")

    # `blade clean --target` takes one target and leaves the other; a bare
    # `blade clean` takes the whole tree.
    r = run([blade_bin, "clean", "--target", HOST_TRIPLE], cwd=pkg, env=ENV)
    if r.returncode != 0:
        fail("blade clean --target", r.stdout + r.stderr)
    if os.path.isdir(os.path.join(pkg, ".build", HOST_TRIPLE)):
        fail("clean --target left its target behind")
    if not os.path.isdir(os.path.join(pkg, ".build", "host")):
        fail("clean --target removed another target")
    r = run([blade_bin, "clean"], cwd=pkg, env=ENV)
    if r.returncode != 0:
        fail("blade clean", r.stdout + r.stderr)
    if os.path.isdir(os.path.join(pkg, ".build")):
        fail("blade clean left the build directory behind")
    print("  clean --target takes one; clean takes all")

    subprocess.run(["rm", "-rf", pkg])


def main():
    # Clean prior stage artifacts so incremental state is fresh. The last two
    # are where the pre-143 layout put them; removing them keeps a tree built by
    # an older Blade from confusing this run.
    for p in [BLADE_BUILD, os.path.join(BLADE_DIR, ".blade"), LEGACY_BIN,
              os.path.join(BLADE_DIR, "blade.ll")]:
        subprocess.run(["rm", "-rf", p])

    # stage0: sawc builds blade directly (with the toml + semver deps mapped).
    print("== stage0: sawc builds blade ==")
    r = run([PY, SAWC, os.path.join(BLADE_DIR, "src", "main.saw"),
             "-o", STAGE0, "--module-path", f"toml={TOML_SRC}",
             "--module-path", f"semver={SEMVER_SRC}",
             "--module-path", f"imgformat={IMGFORMAT_SRC}"])
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
    # Blade is an APPLICATION, so its lock is written and committed.
    if not os.path.exists(os.path.join(BLADE_DIR, "Saw.lock")):
        fail("Saw.lock not written")
    layout_checks()

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

    # A stale artifact from the old in-place layout must not be trusted.
    stale_artifact_guard(STAGE0)

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

    # The library packages' own `blade test` suites, run through the self-built
    # blade with the in-tree compiler (design 97). Green here closes the coverage
    # gap: the lib suites are now a standard bar, not a "pre-existing" caveat.
    lib_tests(STAGE_BIN)

    # One package, two target names, two artifacts (design 143). Run through
    # the self-built blade, on a throwaway package, so it also exercises
    # `blade new` and `blade clean`.
    two_target_build(STAGE_BIN)

    # Clean every package's build output (keep Saw.lock committed).
    subprocess.run(["rm", "-rf", BLADE_BUILD])
    for _name, d in LIB_DIRS:
        subprocess.run(["rm", "-rf", os.path.join(d, ".build")])

    print("BOOTSTRAP: ok")


if __name__ == "__main__":
    main()

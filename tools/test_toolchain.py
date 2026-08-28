#!/usr/bin/env python3
"""Unit tests for the toolchain resolver (design 238 unit 4).

All four resolution steps, the version check and the refusal. `resolve()` takes
its environment and its consumer root as PARAMETERS precisely so this file can
drive every step without mutating the process — and without a network: step 3
is exercised through a pre-populated cache (the steady state) and through its
missing-prerequisite refusal, never by cloning.

The refusal texts are asserted on rather than merely "an error was raised",
because design 238 unit 6's negative tests read exactly those words: a
consumer with no toolchain has to be told what to do about it, and one whose
compiler disagrees with its pin has to be told which two versions disagreed.

    ./.venv/bin/python tools/test_toolchain.py
"""

import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toolchain import (MODULE_DIRS, PIN_FILE,  # noqa: E402
                       ToolchainError, resolve)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}{(': ' + detail) if detail else ''}")
        FAILURES.append(name)


def expect_error(name, fn, *needles):
    """Run `fn`, require a ToolchainError, require every needle in its text."""
    try:
        fn()
    except ToolchainError as e:
        text = str(e)
        missing = [n for n in needles if n not in text]
        check(name, not missing,
              f"message missing {missing!r} — said:\n{text}")
        return text
    except Exception as e:  # noqa: BLE001 - any other exception is the failure
        check(name, False, f"raised {type(e).__name__}: {e}")
        return ""
    check(name, False, "no ToolchainError was raised")
    return ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_checkout(base, name="sawlang"):
    """A directory that passes `_looks_like_sawlang` and holds the packages."""
    root = os.path.join(base, name)
    os.makedirs(os.path.join(root, "sawc"))
    with open(os.path.join(root, "sawc", "sawc.py"), "w") as f:
        f.write("# a stand-in compiler\n")
    for parts in MODULE_DIRS.values():
        os.makedirs(os.path.join(root, *parts))
    os.makedirs(os.path.join(root, "blade", "src"))
    return root


def make_bin(base, name, script):
    """An executable on a fake PATH directory. Returns the directory."""
    bindir = os.path.join(base, "bin")
    os.makedirs(bindir, exist_ok=True)
    path = os.path.join(bindir, name)
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return bindir


def fake_sawc(version):
    return (f"#!/bin/sh\n"
            f"if [ \"$1\" = \"--version\" ]; then echo 'sawc {version}'; "
            f"exit 0; fi\nexit 1\n")


def write_pin(consumer_root, text):
    with open(os.path.join(consumer_root, PIN_FILE), "w") as f:
        f.write(text)


def consumer(base):
    """A consumer root — a directory that is NOT a sawlang checkout, so the
    in-repo default never fires and the steps below are the ones under test."""
    root = os.path.join(base, "consumer")
    os.makedirs(root, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Step 1 — what the operator named
# ---------------------------------------------------------------------------

def test_step1_in_repo_default(tmp):
    print("step 1: the in-repo default")
    # No consumer_root given: the resolver takes the repository this file lives
    # in, which IS a sawlang checkout, so sawlang resolves to itself.
    tc = resolve(env={"PATH": ""})
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    check("this checkout is the default root", tc.root == here, tc.root)
    check("source names the checkout", tc.source == "this checkout", tc.source)
    check("sawc argv ends at sawc/sawc.py",
          tc.sawc()[-1] == os.path.join(here, "sawc", "sawc.py"), tc.sawc())
    check("imgformat resolves under libs/",
          tc.module_source("imgformat") ==
          os.path.join(here, "libs", "imgformat", "src"))
    check("module_path_arg is NAME=DIR",
          tc.module_path_arg("toml") ==
          f"toml={os.path.join(here, 'libs', 'toml', 'src')}")
    check("blade is built from source by default",
          tc.blade_binary() is None)
    check("blade's package dir is under the root",
          tc.blade_package_dir() == os.path.join(here, "blade"))


def test_step1_named_root(tmp):
    print("step 1: SAWLANG_ROOT")
    root = make_checkout(tmp, "named")
    c = consumer(tmp)
    tc = resolve(env={"SAWLANG_ROOT": root, "PATH": ""}, consumer_root=c)
    check("the named root wins", tc.root == root, tc.root)
    check("source names SAWLANG_ROOT", tc.source == "SAWLANG_ROOT", tc.source)
    check("semver resolves under it",
          tc.module_source("semver") ==
          os.path.join(root, "libs", "semver", "src"))

    # A root that is not a checkout is refused where it is NAMED, not later.
    expect_error(
        "a SAWLANG_ROOT that is not a checkout is refused by name",
        lambda: resolve(env={"SAWLANG_ROOT": tmp, "PATH": ""},
                        consumer_root=c),
        "is not a sawlang checkout", "sawc/sawc.py")


def test_step1_beats_path(tmp):
    print("step 1: a named root beats an installed compiler")
    root = make_checkout(tmp, "editing")
    bindir = make_bin(tmp, "sawc", fake_sawc("9.9.9"))
    c = consumer(tmp)
    tc = resolve(env={"SAWLANG_ROOT": root, "PATH": bindir}, consumer_root=c)
    check("the checkout being edited wins over $PATH",
          tc.root == root and tc.sawc()[-1].startswith(root), tc.sawc())


def test_step1_named_artifacts(tmp):
    print("step 1: SAWC and BLADE")
    c = consumer(tmp)
    tc = resolve(env={"SAWC": "/usr/bin/python3 /opt/sawc/sawc.py", "PATH": ""},
                 consumer_root=c)
    check("SAWC is split into an argv",
          tc.sawc() == ["/usr/bin/python3", "/opt/sawc/sawc.py"], tc.sawc())
    check("SAWC round-trips as one string for Blade",
          tc.sawc_env_value() == "/usr/bin/python3 /opt/sawc/sawc.py")
    check("source names SAWC", tc.source == "SAWC", tc.source)
    check("no root came with it", tc.root is None)

    root = make_checkout(tmp, "withblade")
    tc = resolve(env={"SAWLANG_ROOT": root, "BLADE": "/opt/bin/blade",
                      "PATH": ""}, consumer_root=c)
    check("BLADE is taken as the binary",
          tc.blade_binary() == "/opt/bin/blade", tc.blade_binary())
    check("source names both", "BLADE" in tc.source and
          "SAWLANG_ROOT" in tc.source, tc.source)


# ---------------------------------------------------------------------------
# Step 2 — $PATH, and the version check
# ---------------------------------------------------------------------------

def test_step2_path(tmp):
    print("step 2: $PATH")
    bindir = make_bin(tmp, "sawc", fake_sawc("0.1.0"))
    make_bin(tmp, "blade", "#!/bin/sh\nexit 0\n")
    c = consumer(tmp)

    tc = resolve(env={"PATH": bindir}, consumer_root=c)
    check("sawc comes off PATH",
          tc.sawc() == [os.path.join(bindir, "sawc")], tc.sawc())
    check("blade comes off PATH too",
          tc.blade_binary() == os.path.join(bindir, "blade"))
    check("source names PATH", tc.source == "PATH", tc.source)
    check("no root came with it", tc.root is None)
    check("an unpinned PATH compiler is noted, not refused",
          any("unpinned" in n for n in tc.notes), tc.notes)


def test_step2_version_check(tmp):
    print("step 2: the version check")
    bindir = make_bin(tmp, "sawc", fake_sawc("0.1.0"))
    c = consumer(tmp)

    write_pin(c, "# the toolchain this repo builds against\n"
                 "version = 0.1.0\nsha = abc123\n")
    tc = resolve(env={"PATH": bindir}, consumer_root=c)
    check("a matching version resolves", tc.source == "PATH", tc.source)
    check("a matching version is not noted", tc.notes == [], tc.notes)

    # The refusal names BOTH versions — which is the whole point of D-b2.
    write_pin(c, "version = 0.2.0\nsha = abc123\n")
    expect_error("a mismatched version refuses, naming both",
                 lambda: resolve(env={"PATH": bindir}, consumer_root=c),
                 "0.1.0", "0.2.0", "SAWLANG_ROOT")

    # A `sawc` that will not name itself is not one to trust with a build.
    quiet = make_bin(os.path.join(tmp, "quiet"), "sawc", "#!/bin/sh\nexit 0\n")
    write_pin(c, "version = 0.1.0\n")
    expect_error("a compiler that will not say its version refuses",
                 lambda: resolve(env={"PATH": quiet}, consumer_root=c),
                 "would not say what version", "0.1.0")
    os.remove(os.path.join(c, PIN_FILE))


def test_step2_has_no_sources(tmp):
    print("step 2: executables only")
    bindir = make_bin(tmp, "sawc", fake_sawc("0.1.0"))
    c = consumer(tmp)
    tc = resolve(env={"PATH": bindir}, consumer_root=c)
    expect_error("a package's sources need a checkout",
                 lambda: tc.module_source("imgformat"),
                 "no sawlang checkout is available", "imgformat",
                 "SAWLANG_ROOT", PIN_FILE)
    expect_error("so does Blade's own package",
                 tc.blade_package_dir,
                 "no sawlang checkout is available", "Blade's own sources")


# ---------------------------------------------------------------------------
# Step 3 — the pinned fetch
# ---------------------------------------------------------------------------

def test_step3_cache_hit(tmp):
    print("step 3: the cached fetch")
    cache = os.path.join(tmp, "cache")
    sha = "0123456789abcdef0123456789abcdef01234567"
    os.makedirs(cache)
    # A cache entry that already holds a checkout: the steady state, and the
    # path that must touch no network.
    make_checkout(cache, sha)
    c = consumer(tmp)
    write_pin(c, f"version = 0.1.0\nsha = {sha}\n")

    # PATH is empty, so `git` is not even findable — if this reached the clone
    # it would refuse, which is what makes the assertion meaningful.
    tc = resolve(env={"PATH": "", "SAW_TOOLCHAIN_CACHE": cache},
                 consumer_root=c)
    check("a cache hit is used", tc.root == os.path.join(cache, sha), tc.root)
    check("source names the fetch", tc.source == "fetch", tc.source)
    check("the fetched checkout supplies the packages",
          tc.module_source("imgformat") ==
          os.path.join(cache, sha, "libs", "imgformat", "src"))


def test_step3_missing_prereq(tmp):
    print("step 3: the fetch's prerequisites")
    c = consumer(tmp)
    write_pin(c, "version = 0.1.0\nsha = deadbeef\n")
    expect_error("a fetch with no git refuses, naming it",
                 lambda: resolve(env={"PATH": "",
                                      "SAW_TOOLCHAIN_CACHE":
                                          os.path.join(tmp, "empty")},
                                 consumer_root=c),
                 "needs `git`", "SAWLANG_ROOT")


# ---------------------------------------------------------------------------
# Step 4 — the refusal
# ---------------------------------------------------------------------------

def test_step4_refusal(tmp):
    print("step 4: the refusal")
    c = consumer(tmp)
    text = expect_error(
        "no toolchain anywhere refuses, naming all three steps",
        lambda: resolve(env={"PATH": ""}, consumer_root=c),
        # step 1
        "SAWLANG_ROOT", "SAWC", "BLADE",
        # step 2
        "PATH", "make install",
        # step 3
        PIN_FILE, "cached by SHA",
        # and why each did not fire
        "are all unset", "no `sawc` on your PATH", f"no {PIN_FILE} here")
    check("the refusal says where it looked for the pin",
          c in text, text)

    # A pin with a version but no sha cannot drive step 3, and says so.
    write_pin(c, "version = 0.1.0\n")
    expect_error("a pin with no sha says so",
                 lambda: resolve(env={"PATH": ""}, consumer_root=c),
                 f"{PIN_FILE} names no `sha`")


# ---------------------------------------------------------------------------
# The pin file, and the package table
# ---------------------------------------------------------------------------

def test_pin_parsing(tmp):
    print("the pin file")
    c = consumer(tmp)
    write_pin(c, "not a key-value line\n")
    expect_error("a malformed pin line refuses, located",
                 lambda: resolve(env={"PATH": ""}, consumer_root=c),
                 f"{PIN_FILE}:1", "expected `key = value`")

    # Comments, blank lines, quotes and unknown keys are all fine.
    bindir = make_bin(tmp, "sawc", fake_sawc("0.1.0"))
    write_pin(c, "\n# a comment\nversion = \"0.1.0\"   # trailing\n"
                 "sha = abc\nfuture_key = whatever\n")
    tc = resolve(env={"PATH": bindir}, consumer_root=c)
    check("a quoted, commented pin parses", tc.source == "PATH", tc.source)
    os.remove(os.path.join(c, PIN_FILE))


def test_unknown_package(tmp):
    print("the package table")
    tc = resolve(env={"PATH": ""})
    expect_error("a package the resolver does not own is named as such",
                 lambda: tc.module_source("nosuch"),
                 "is not a sawlang package this resolver owns",
                 "imgformat", "semver", "toml")


TESTS = [
    test_step1_in_repo_default,
    test_step1_named_root,
    test_step1_beats_path,
    test_step1_named_artifacts,
    test_step2_path,
    test_step2_version_check,
    test_step2_has_no_sources,
    test_step3_cache_hit,
    test_step3_missing_prereq,
    test_step4_refusal,
    test_pin_parsing,
    test_unknown_package,
]


def main():
    print("toolchain resolver (design 238 unit 4)")
    for test in TESTS:
        tmp = tempfile.mkdtemp(prefix="sawtoolchain-")
        try:
            test(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("toolchain: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

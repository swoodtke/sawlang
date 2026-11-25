#!/usr/bin/env python3
"""The tool records `build.py` writes, against a fake Homebrew prefix.

    python compiler/tests/seed/test_tool_records.py

`compiler/tests/run.py` runs `run()`. The cases:

- a tool inside `PREFIX/Cellar/FORMULA/VERSION/` is recorded as
  `PREFIX/opt/FORMULA/...`, by `recorded_tool_path` and through the
  llvm-objcopy a clang names (`choose_objcopy`);
- a path outside a keg, or in a keg with no `opt` link, is kept;
- a record naming a tool that has since gone is written again, with a line on
  standard error (`configure_bare_metal_targets`).
"""
import contextlib
import io
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

WORK = os.path.join(REPO, ".build", "tool-records-test")
# A clang that compiles anything and names `$FAKE_OBJCOPY` as its llvm-objcopy.
FAKE_CLANG = """#!/bin/sh
case "$1" in
  -print-prog-name=*) echo "$FAKE_OBJCOPY" ;;
esac
exit 0
"""


def executable(path, text="#!/bin/sh\nexit 0\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o755)


def cases(failures, counts):
    def check(name, ok, detail=""):
        counts["tool record cases"] = counts.get("tool record cases", 0) + 1
        if not ok:
            failures.append("tool records: %s%s" % (name, ": " + detail if detail else ""))

    prefix = os.path.realpath(os.path.join(WORK, "brew"))
    keg = os.path.join(prefix, "Cellar", "llvm", "1.0")
    for tool in ("clang", "llvm-objcopy"):
        executable(os.path.join(keg, "bin", tool))
    os.makedirs(os.path.join(prefix, "opt"))
    os.symlink(os.path.join("..", "Cellar", "llvm", "1.0"), os.path.join(prefix, "opt", "llvm"))
    inside = os.path.join(keg, "bin", "clang")
    stable = os.path.join(prefix, "opt", "llvm", "bin", "clang")
    got = build.recorded_tool_path(inside)
    check("a keg path is recorded as its opt path", got == stable, got)
    plain = os.path.join(WORK, "plain", "bin", "clang")
    executable(plain)
    check("a path outside Homebrew is kept", build.recorded_tool_path(plain) == plain)
    other = os.path.join(prefix, "Cellar", "other", "2.0", "bin", "tool")
    executable(other)
    check("a keg with no opt link is kept", build.recorded_tool_path(other) == other)
    # Homebrew keeps an older keg until `brew cleanup`: a tool probed there is
    # not the file `opt` names, so its own path stays recorded.
    old = os.path.join(prefix, "Cellar", "llvm-two", "1.0", "bin", "clang")
    executable(old)
    executable(os.path.join(prefix, "Cellar", "llvm-two", "2.0", "bin", "clang"))
    os.symlink(os.path.join("..", "Cellar", "llvm-two", "2.0"), os.path.join(prefix, "opt", "llvm-two"))
    got = build.recorded_tool_path(old)
    check("a tool in an older keg than opt names is kept", got == old, got)

    fake = os.path.join(WORK, "bin", "clang")
    executable(fake, FAKE_CLANG)
    saved_env = {name: os.environ.get(name) for name in ("FAKE_OBJCOPY", "SAWC_CLANG")}
    os.environ["FAKE_OBJCOPY"] = os.path.join(keg, "bin", "llvm-objcopy")
    got = build.choose_objcopy(fake)
    check("the objcopy a clang names is recorded as its opt path",
          got == os.path.join(prefix, "opt", "llvm", "bin", "llvm-objcopy"), str(got))

    saved = {name: getattr(build, name) for name in ("BUILD_DIR", "RUNTIME_MANIFEST")}
    saved_chosen = dict(build._CHOSEN_CLANGS)
    try:
        build.BUILD_DIR = os.path.join(WORK, "build")
        build.RUNTIME_MANIFEST = os.path.join(build.BUILD_DIR, "sawc-runtime.txt")
        build._CHOSEN_CLANGS.clear()
        os.environ["SAWC_CLANG"] = fake
        gone = os.path.join(WORK, "gone", "llvm-objcopy")
        executable(gone)
        os.environ["FAKE_OBJCOPY"] = gone
        build.configure_bare_metal_targets()
        record = build.runtime_manifest("riscv32-unknown-none-elf")
        with open(record) as fh:
            first = fh.read()
        check("the record names the objcopy", "objcopy " + gone in first, first)
        os.remove(gone)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            build.configure_bare_metal_targets()
        with open(record) as fh:
            second = fh.read()
        check("a record naming a missing tool is written again", gone not in second, second)
        check("it says so on standard error", "no longer exists" in err.getvalue() and gone in err.getvalue(),
              err.getvalue())
    finally:
        for name, value in saved.items():
            setattr(build, name, value)
        build._CHOSEN_CLANGS.clear()
        build._CHOSEN_CLANGS.update(saved_chosen)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run():
    """([failure], {count: n})."""
    failures, counts = [], {}
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    try:
        cases(failures, counts)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    print("tool records: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                    ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The resolve lane's checks on a modified std, which no tracked std can hold.

    python compiler/tests/resolve/interface_pin.py

Each case runs on a copy of `std/`, one file of it extended, with the entry
beside the copy:

- A std module the parser refuses as a whole: an import of it is refused as
  `import.unavailable` at the import.
- A std trait whose requirement has a default body: a user conformance that
  leaves the method out typechecks, and one that leaves out a requirement with
  no default is refused.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

WORK = os.path.join(REPO, ".build", "interface-pin")
TIMEOUT = 300

# Appended to a copy of `std/data.saw`: an unclosed brace, which the parser
# refuses for the whole file.
UNAVAILABLE_TAIL = "\nstruct Unclosed {\n"
UNAVAILABLE_ENTRY = "import std.data.{Data}\n\nfunc f() -> Int {\n    0\n}\n"
UNAVAILABLE_AT = "1:8"
# Appended to a copy of `std/path.saw`: a trait with a default body.
DEFAULT_TRAIT = ("\npublic trait Greets {\n    func name(&self) -> Int\n\n"
                 "    func greet(&self) -> Int {\n        self.name() + 1\n    }\n}\n")
DEFAULT_FILLED = ("import std.path.{Greets}\n\nstruct Person {\n    id: Int\n}\n\n"
                  "extension Person: Greets {\n    func name(&self) -> Int {\n        self.id\n    }\n}\n")
DEFAULT_MISSING = ("import std.path.{Greets}\n\nstruct Person {\n    id: Int\n}\n\n"
                   "extension Person: Greets {\n    func greet(&self) -> Int {\n        self.id\n    }\n}\n")


def rel(path):
    return os.path.relpath(path, REPO)


def std_copy(name, file, tail):
    """A copy of `std/` under WORK/NAME/std whose FILE ends in `tail`; returns
    the case's directory and the copy, the std root."""
    case = os.path.join(WORK, name)
    shutil.rmtree(case, ignore_errors=True)
    root = os.path.join(case, "std")
    shutil.copytree(os.path.join(REPO, "std"), root)
    path = os.path.join(root, file)
    with open(path) as fh:
        text = fh.read()
    with open(path, "w") as fh:
        fh.write(text + tail)
    return case, root


def write_entry(case, name, text):
    """An entry program beside the std copy, never inside it, where it would
    be a std module."""
    path = os.path.join(case, name)
    with open(path, "w") as fh:
        fh.write(text)
    return rel(path)


def sawc(command, root, entry):
    r = subprocess.run([build.SAWC, command, "--check", "--notes", "--std-root", rel(root), entry],
                       cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.stdout.split("\n")


def refusals(lines):
    return [l for l in lines if l.startswith(("ERROR\t", "INVARIANT\t"))]


def check_unavailable(failures):
    case, root = std_copy("unavailable", "data.saw", UNAVAILABLE_TAIL)
    entry = write_entry(case, "main.saw", UNAVAILABLE_ENTRY)
    lines = sawc("resolve", root, entry)
    errors = [l for l in lines if l.startswith("ERROR\t")]
    want = "ERROR\timport.unavailable\t%s:%s\t" % (entry, UNAVAILABLE_AT)
    if not any(l.startswith(want) for l in errors):
        failures.append("interface pin: an import of a std module the parser refuses gives %r, "
                        "expected import.unavailable at %s:%s" % (errors[:2], entry, UNAVAILABLE_AT))


def check_default_body(failures):
    case, root = std_copy("default-body", "path.saw", DEFAULT_TRAIT)
    filled = write_entry(case, "filled.saw", DEFAULT_FILLED)
    for l in refusals(sawc("typecheck", root, filled)):
        failures.append("interface pin: a conformance a std default body completes: %s" % l)
    missing = write_entry(case, "missing.saw", DEFAULT_MISSING)
    if not refusals(sawc("typecheck", root, missing)):
        failures.append("interface pin: a conformance missing a requirement with no default "
                        "body typechecks")


def run():
    failures = []
    counts = {}
    check_unavailable(failures)
    check_default_body(failures)
    counts["interface pin built cases"] = 2
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("interface pin: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The interface parse's checks, which the resolve lane runs.

    python compiler/tests/resolve/interface_pin.py

Only Stage 0's std root is read by the interface parse (the new std's
modules are parsed in full), so each case runs on a copy of that root:

- A std root with one bad signature: that declaration is dropped with a note,
  and the rest of the module resolves.
- A std root whose module the parser refuses as a whole: an import of it is
  refused as `import.unavailable`.
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

# Appended to a copy of `std/path.saw`: one declaration whose signature the
# parser refuses, between two it takes.
DROPPED_DECLARATIONS = ("\npublic func before_bad() -> Int {\n    1\n}\n"
                        "\npublic func bad(x: ) -> Int {\n    1\n}\n"
                        "\npublic func after_bad() -> Int {\n    2\n}\n")
DROPPED_ENTRY = ("import std.path.{Path, after_bad, before_bad}\n\n"
                 "func f(p: Path) -> Int {\n    before_bad() + after_bad()\n}\n")
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
    """A copy of the std root under WORK/NAME whose `std/FILE` ends in `tail`;
    returns the root and the line `tail` starts on."""
    root = os.path.join(WORK, name)
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "sawc", "std"), os.path.join(root, "std"))
    shutil.copy(os.path.join(REPO, "sawc", "builtin.saw"), root)
    path = os.path.join(root, "std", file)
    with open(path) as fh:
        text = fh.read()
    with open(path, "w") as fh:
        fh.write(text + tail)
    return root, text.count("\n") + 1


def write_entry(root, name, text):
    path = os.path.join(root, name)
    with open(path, "w") as fh:
        fh.write(text)
    return rel(path)


def sawc(command, root, entry):
    r = subprocess.run([build.SAWC, command, "--check", "--notes", "--std-root", rel(root), entry],
                       cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.stdout.split("\n")


def refusals(lines):
    return [l for l in lines if l.startswith(("ERROR\t", "INVARIANT\t"))]


def check_dropped_declaration(failures):
    root, line = std_copy("dropped", "path.saw", DROPPED_DECLARATIONS)
    entry = write_entry(root, "main.saw", DROPPED_ENTRY)
    lines = sawc("resolve", root, entry)
    bad_line = line + 5
    want = "NOTE\tresolve.parse-refused\t%s:%d:1\t" % (rel(os.path.join(root, "std", "path.saw")),
                                                        bad_line)
    notes = [l for l in lines if l.startswith(want)]
    if len(notes) != 1 or "`public func bad(x: ) -> Int {`" not in notes[0]:
        failures.append("interface pin: a std declaration the parser refuses gives no note "
                        "naming it at line %d" % bad_line)
    for l in refusals(lines):
        failures.append("interface pin: the declarations around a dropped one: %s" % l)


def check_unavailable(failures):
    root, _ = std_copy("unavailable", "data.saw", UNAVAILABLE_TAIL)
    entry = write_entry(root, "main.saw", UNAVAILABLE_ENTRY)
    lines = sawc("resolve", root, entry)
    errors = [l for l in lines if l.startswith("ERROR\t")]
    want = "ERROR\timport.unavailable\t%s:%s\t" % (entry, UNAVAILABLE_AT)
    if not errors or not errors[0].startswith(want):
        failures.append("interface pin: an import of a std module the parser refuses gives %r, "
                        "expected import.unavailable at %s" % (errors[:1], UNAVAILABLE_AT))


def check_default_body(failures):
    root, _ = std_copy("default-body", "path.saw", DEFAULT_TRAIT)
    filled = write_entry(root, "filled.saw", DEFAULT_FILLED)
    for l in refusals(sawc("typecheck", root, filled)):
        failures.append("interface pin: a conformance a std default body completes: %s" % l)
    missing = write_entry(root, "missing.saw", DEFAULT_MISSING)
    if not refusals(sawc("typecheck", root, missing)):
        failures.append("interface pin: a conformance missing a requirement with no default "
                        "body typechecks")


def run():
    failures = []
    counts = {}
    check_dropped_declaration(failures)
    check_unavailable(failures)
    check_default_body(failures)
    counts["interface pin built cases"] = 3
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

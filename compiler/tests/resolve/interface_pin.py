#!/usr/bin/env python3
"""The interface parse's checks, which the resolve lane runs.

    python compiler/tests/resolve/interface_pin.py

- The equivalence pin: every `sawc/std` file and `sawc/builtin.saw`, parsed
  both ways by `interface_pin.saw`. Where the full parse accepts a file, the
  interface parse must take it with no diagnostic and agree with it but for
  the skipped nodes; where the full parse refuses one, the interface parse
  must still take it whole. `FULL_REFUSED` names the files of that second
  kind, so a file moving between the two is seen.
- A std root with one bad signature: that declaration is dropped with a note,
  and the rest of the module resolves.
- A std root whose module the parser refuses as a whole: an import of it is
  refused as `import.unavailable`.
- A std trait whose requirement has a default body: a user conformance that
  leaves the method out typechecks, and one that leaves out a requirement with
  no default is refused.
"""
import glob
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

PIN_SOURCE = os.path.join(HERE, "interface_pin.saw")
WORK = os.path.join(REPO, ".build", "interface-pin")
PIN_EXE = os.path.join(WORK, "interface_pin")
TIMEOUT = 300

# The std files the full parse refuses, which only the interface parse takes.
FULL_REFUSED = {"sawc/std/data.saw"}

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


def std_files():
    files = sorted(glob.glob(os.path.join(REPO, "sawc", "std", "**", "*.saw"), recursive=True))
    return [os.path.join(REPO, "sawc", "builtin.saw")] + files


def check_equivalence(failures, counts):
    os.makedirs(WORK, exist_ok=True)
    ok, output = build.build_program(PIN_SOURCE, PIN_EXE)
    if not ok:
        failures.append("interface pin: %s does not compile: %s"
                        % (rel(PIN_SOURCE), output.strip().splitlines()[-1:]))
        return
    paths = [rel(p) for p in std_files()]
    r = subprocess.run([PIN_EXE] + paths, cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
    seen = set()
    whole = set()
    for line in r.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        seen.add(fields[1])
        if fields[0] == "FAIL":
            failures.append("interface pin %s: %s" % (fields[1], "\t".join(fields[2:])))
        elif fields[0] == "WHOLE":
            whole.add(fields[1])
        elif fields[0] == "SAME":
            counts["interface pin files"] = counts.get("interface pin files", 0) + 1
    for path in paths:
        if path not in seen:
            failures.append("interface pin %s: no line" % path)
    for path in sorted(whole - FULL_REFUSED):
        failures.append("interface pin %s: the full parse refuses it; add it to FULL_REFUSED "
                        "if that is meant" % path)
    for path in sorted(FULL_REFUSED - whole):
        failures.append("interface pin %s: FULL_REFUSED names it, but the full parse does not "
                        "refuse it" % path)
    if r.returncode != 0 and not any(f.startswith("interface pin") for f in failures):
        failures.append("interface pin: exit %d: %s" % (r.returncode, r.stderr.strip()[:200]))


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


def sawc2(command, root, entry):
    r = subprocess.run([build.SAWC2, command, "--check", "--notes", "--std-root", rel(root), entry],
                       cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.stdout.split("\n")


def refusals(lines):
    return [l for l in lines if l.startswith(("ERROR\t", "INVARIANT\t"))]


def check_dropped_declaration(failures):
    root, line = std_copy("dropped", "path.saw", DROPPED_DECLARATIONS)
    entry = write_entry(root, "main.saw", DROPPED_ENTRY)
    lines = sawc2("resolve", root, entry)
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
    lines = sawc2("resolve", root, entry)
    errors = [l for l in lines if l.startswith("ERROR\t")]
    want = "ERROR\timport.unavailable\t%s:%s\t" % (entry, UNAVAILABLE_AT)
    if not errors or not errors[0].startswith(want):
        failures.append("interface pin: an import of a std module the parser refuses gives %r, "
                        "expected import.unavailable at %s" % (errors[:1], UNAVAILABLE_AT))


def check_default_body(failures):
    root, _ = std_copy("default-body", "path.saw", DEFAULT_TRAIT)
    filled = write_entry(root, "filled.saw", DEFAULT_FILLED)
    for l in refusals(sawc2("typecheck", root, filled)):
        failures.append("interface pin: a conformance a std default body completes: %s" % l)
    missing = write_entry(root, "missing.saw", DEFAULT_MISSING)
    if not refusals(sawc2("typecheck", root, missing)):
        failures.append("interface pin: a conformance missing a requirement with no default "
                        "body typechecks")


def run():
    failures = []
    counts = {}
    check_equivalence(failures, counts)
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

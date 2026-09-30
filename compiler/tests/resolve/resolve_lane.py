#!/usr/bin/env python3
"""The resolve lane: `sawc2 resolve` against its golden dumps and refusal fixtures.

    python compiler/tests/resolve/resolve_lane.py            # check
    python compiler/tests/resolve/resolve_lane.py --write    # rewrite the golden dumps
    python compiler/tests/resolve/resolve_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw` or `multi/NAME/main.saw`, resolves to
  exactly the record in `golden/NAME.resolve` or `multi/NAME.resolve`;
- each refusal fixture, `refuse/RULE[.VARIANT].saw` or
  `refuse/RULE[.VARIANT]/main.saw`, is refused first by the rule and at the
  position its `// refuses:` header names;
- every rule resolve refuses by has a fixture, unless `WAIVED` says why not;
- the compiler's own source, the sawc2 build and each unit program, resolves
  with no refusal;
- no record anywhere carries an `INVARIANT` line from the verifier.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
MULTI = os.path.join(HERE, "multi")
REFUSE = os.path.join(HERE, "refuse")
RESOLVE_SOURCE = os.path.join(COMPILER, "resolve", "src")
TIMEOUT = 300

_HEADER = re.compile(r"^// refuses: (\S+)(?: at ((?:[\w.-]+\.saw:)?\d+:\d+))?$")
_RULE_ID = re.compile(r'"((?:name|import|visibility|conformance|test|slice|resolve)\.[a-z-]+)"')

# Rules no tracked fixture can reach, each with the reason. A rule the lane
# checks with a case it builds itself (`check_built_cases`) is named here too.
WAIVED = {
    "resolve.prelude-table": "a note on the builtin module when the prelude table names a "
                             "declaration its module lacks; prelude_check.py covers the tables",
    "import.unreadable": "an entry file or std module that cannot be read; the lane checks it "
                         "by naming a file that does not exist",
    "resolve.parse-refused": "an imported module the parser refuses; a tracked .saw file the "
                             "grammar refuses would need a grammar-corpus row, so the lane "
                             "writes the case under .build and checks it there",
}
BUILT_DIR = os.path.join(REPO, ".build", "resolve-lane")
# The case check_built_cases writes: an entry importing a module that does not
# parse, and where the refusal is reported.
PARSE_REFUSED_ENTRY = "import broken.{thing}\n\nfunc f() -> Int {\n    thing()\n}\n"
PARSE_REFUSED_MODULE = "public func thing() -> Int {\n    let = 1\n}\n"
PARSE_REFUSED_AT = "broken.saw:2:9"
# The interface case: a copy of the std root whose `std/path.saw` gains a
# signature spelling resolve does not build yet. An interface module's
# refusal is a note, and the verifier checks the signatures it walked.
INTERFACE_ROOT = os.path.join(BUILT_DIR, "interface-root")
INTERFACE_DECLARATION = ("\npublic func first_item<T: Iterator>(items: &var T) -> T.Item? {\n"
                         "    items.next()\n}\n")
INTERFACE_RULE = "slice.not-yet"


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "resolve"] + args, cwd=REPO, capture_output=True,
                       text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def package_args():
    args = []
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    return args


def records(output):
    """{path: record text after its FILE line}, in order."""
    out = {}
    current = None
    lines = []
    for line in output.split("\n"):
        if line.startswith("FILE\t"):
            if current is not None:
                out[current] = "\n".join(lines).rstrip("\n") + "\n"
            current = line[len("FILE\t"):]
            lines = []
        else:
            lines.append(line)
    if current is not None:
        out[current] = "\n".join(lines).rstrip("\n") + "\n"
    return out


def golden_cases():
    """(entry path, expectation path), sorted."""
    cases = []
    for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw"))):
        cases.append((src, os.path.splitext(src)[0] + ".resolve"))
    for entry in sorted(glob.glob(os.path.join(MULTI, "*", "main.saw"))):
        name = os.path.basename(os.path.dirname(entry))
        cases.append((entry, os.path.join(MULTI, name + ".resolve")))
    return cases


def refusal_cases():
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    cases += sorted(glob.glob(os.path.join(REFUSE, "*", "main.saw")))
    return cases


def check_golden(failures, counts, write):
    cases = golden_cases()
    code, out = sawc2(["--dump"] + [rel(src) for src, _ in cases])
    got = records(out)
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("resolve golden %s: no record" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("resolve golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("resolve golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        counts["resolve golden cases"] = counts.get("resolve golden cases", 0) + 1


def first_difference(expected, got):
    a = expected.split("\n")
    b = got.split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<end>"
        y = b[i] if i < len(b) else "<end>"
        if x != y:
            return "line %d: expected %r, got %r" % (i + 1, x[:90], y[:90])
    return "a trailing byte"


def header_of(path):
    with open(path) as fh:
        first = fh.readline().rstrip("\n")
    return _HEADER.match(first)


def first_error(record, entry=None):
    """(rule, position) of a record's first refusal, or None. The position is
    `L:C`, after the file's name when that is not the entry's own file."""
    for line in record.split("\n"):
        if line.startswith("ERROR\t"):
            fields = line.split("\t")
            path, row, col = fields[2].rsplit(":", 2)
            if entry is not None and path != entry:
                return fields[1], "%s:%s:%s" % (os.path.basename(path), row, col)
            return fields[1], "%s:%s" % (row, col)
    return None


def check_refusals(failures, counts, fill):
    cases = refusal_cases()
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = records(out)
    named = set()
    for path in cases:
        record = got.get(rel(path), "")
        found = first_error(record, rel(path))
        m = header_of(path)
        if fill and (m is None or m.group(1) == "TODO"):
            write_header(path, found)
            continue
        if m is None:
            failures.append("resolve refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named.add(rule)
        if found is None:
            failures.append("resolve refusal %s: expected %s, nothing refused" % (rel(path), rule))
        elif found[0] != rule:
            failures.append("resolve refusal %s: expected %s first, refused as %s at %s"
                            % (rel(path), rule, found[0], found[1]))
        elif at and found[1] != at:
            failures.append("resolve refusal %s: %s at %s, expected at %s"
                            % (rel(path), rule, found[1], at))
        counts["resolve refusal fixtures"] = counts.get("resolve refusal fixtures", 0) + 1
    return named


def write_header(path, found):
    with open(path) as fh:
        lines = fh.read().split("\n")
    header = "// refuses: NOTHING" if found is None else "// refuses: %s at %s" % found
    if lines and lines[0].startswith("// refuses:"):
        lines[0] = header
    else:
        lines.insert(0, header)
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def rule_catalog():
    """Every rule id resolve's source refuses by."""
    ids = set()
    for path in glob.glob(os.path.join(RESOLVE_SOURCE, "*.saw")):
        with open(path) as fh:
            ids.update(_RULE_ID.findall(fh.read()))
    return ids


def check_catalog(failures, counts, named):
    catalog = rule_catalog()
    for rule in sorted(catalog):
        if rule not in named and rule not in WAIVED:
            failures.append("resolve rule %s has no refusal fixture" % rule)
    for rule in sorted(WAIVED):
        if rule not in catalog:
            failures.append("resolve waiver %s names no rule resolve refuses by" % rule)
        elif rule in named:
            failures.append("resolve waiver %s: the rule has a fixture now" % rule)
    counts["resolve rules"] = len(catalog)


def check_built_cases(failures, counts):
    """The refusals no tracked fixture holds, written under .build: a missing
    entry file, an imported module the parser refuses, and a std signature
    outside the slice."""
    missing = rel(os.path.join(HERE, "no-such-entry.saw"))
    code, out = sawc2(["--check", missing])
    found = first_error(records(out).get(missing, ""))
    if found is None or found[0] != "import.unreadable":
        failures.append("resolve: a missing entry file is not refused as import.unreadable")
    case = os.path.join(BUILT_DIR, "parse-refused")
    os.makedirs(case, exist_ok=True)
    entry = os.path.join(case, "main.saw")
    with open(entry, "w") as fh:
        fh.write(PARSE_REFUSED_ENTRY)
    with open(os.path.join(case, "broken.saw"), "w") as fh:
        fh.write(PARSE_REFUSED_MODULE)
    code, out = sawc2(["--check", rel(entry)])
    found = first_error(records(out).get(rel(entry), ""), rel(entry))
    if found != ("resolve.parse-refused", PARSE_REFUSED_AT):
        failures.append("resolve: an imported module the parser refuses gives %r, expected "
                        "resolve.parse-refused at %s" % (found, PARSE_REFUSED_AT))
    check_interface_note(failures)
    counts["resolve built cases"] = 3


def check_interface_note(failures):
    """A std signature outside the slice is a NOTE with its rule, never an
    ERROR or an INVARIANT."""
    std_dir = os.path.join(INTERFACE_ROOT, "std")
    shutil.rmtree(INTERFACE_ROOT, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "sawc", "std"), std_dir)
    shutil.copy(os.path.join(REPO, "sawc", "builtin.saw"), INTERFACE_ROOT)
    path = os.path.join(std_dir, "path.saw")
    with open(path) as fh:
        text = fh.read()
    line = text.count("\n") + 2
    with open(path, "w") as fh:
        fh.write(text + INTERFACE_DECLARATION)
    code, out = sawc2(["--check", "--notes", "--std-root", rel(INTERFACE_ROOT),
                       rel(os.path.join(HERE, "golden", "types.saw"))])
    lines = out.split("\n")
    want = "NOTE\t%s\t%s:%d:" % (INTERFACE_RULE, rel(path), line)
    if not any(l.startswith(want) for l in lines):
        failures.append("resolve: a std signature outside the slice gives no %s note at %s:%d"
                        % (INTERFACE_RULE, rel(path), line))
    for l in lines:
        if l.startswith(("ERROR\t", "INVARIANT\t")):
            failures.append("resolve interface case: %s" % l)


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def check_acceptance(failures, counts):
    """The compiler's own source resolves whole: the sawc2 build, then each unit
    program, each the entry of its own program. A unit program the parser
    refuses has no tree to resolve and is counted apart."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc2(["--check"] + package_args() + entries)
    got = records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("resolve acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            counts["unit programs the parser refuses"] = (
                counts.get("unit programs the parser refuses", 0) + 1)
            continue
        for line in lines:
            failures.append("resolve acceptance %s: %s" % (entry, line))
        counts["resolved compiler programs"] = counts.get("resolved compiler programs", 0) + 1


def check_invariants(failures, output_records):
    for path, record in output_records.items():
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("resolve %s: %s" % (path, line))


def run(write=False, fill=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    named = check_refusals(failures, counts, fill)
    code, out = sawc2(["--check"] + [rel(p) for p in refusal_cases()]
                      + [rel(src) for src, _ in golden_cases()])
    check_invariants(failures, records(out))
    check_catalog(failures, counts, named)
    check_built_cases(failures, counts)
    check_acceptance(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    fill = "--fill" in sys.argv[1:]
    failures, counts = run(write, fill)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("resolve lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

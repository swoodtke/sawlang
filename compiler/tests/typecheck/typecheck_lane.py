#!/usr/bin/env python3
"""The typecheck lane: `sawc2 typecheck` against its golden dumps and refusal fixtures.

    python compiler/tests/typecheck/typecheck_lane.py            # check
    python compiler/tests/typecheck/typecheck_lane.py --write    # rewrite the golden dumps
    python compiler/tests/typecheck/typecheck_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw` or `multi/NAME/main.saw`, checks to
  exactly the record in `golden/NAME.typecheck` or `multi/NAME.typecheck`;
- each refusal fixture, `refuse/RULE[.VARIANT].saw` or
  `refuse/RULE[.VARIANT]/main.saw`, is refused first by the rule and at the
  position its `// refuses:` header names;
- every rule typecheck refuses by has a fixture;
- the compiler's own source, the sawc2 build and each unit program, checks
  with no refusal;
- no record anywhere carries an `INVARIANT` line from either verifier.
"""
import glob
import os
import re
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
TYPECHECK_SOURCE = os.path.join(COMPILER, "typecheck", "src")
TIMEOUT = 300

_HEADER = re.compile(r"^// refuses: (\S+)(?: at ((?:[\w.-]+\.saw:)?\d+:\d+))?$")
_RULE_ID = re.compile(r'"((?:type|conformance|synthesize|copy|unsafe|slice)\.[a-z-]+)"')


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "typecheck"] + args, cwd=REPO, capture_output=True,
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
        cases.append((src, os.path.splitext(src)[0] + ".typecheck"))
    for entry in sorted(glob.glob(os.path.join(MULTI, "*", "main.saw"))):
        name = os.path.basename(os.path.dirname(entry))
        cases.append((entry, os.path.join(MULTI, name + ".typecheck")))
    return cases


def refusal_cases():
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    cases += sorted(glob.glob(os.path.join(REFUSE, "*", "main.saw")))
    return cases


def first_difference(expected, got):
    a = expected.split("\n")
    b = got.split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<end>"
        y = b[i] if i < len(b) else "<end>"
        if x != y:
            return "line %d: expected %r, got %r" % (i + 1, x[:90], y[:90])
    return "a trailing byte"


def check_golden(failures, counts, write):
    cases = golden_cases()
    code, out = sawc2(["--dump"] + [rel(src) for src, _ in cases])
    got = records(out)
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("typecheck golden %s: no record" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("typecheck golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("typecheck golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        counts["typecheck golden cases"] = counts.get("typecheck golden cases", 0) + 1


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
            failures.append("typecheck refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named.add(rule)
        if found is None:
            failures.append("typecheck refusal %s: expected %s, nothing refused"
                            % (rel(path), rule))
        elif found[0] != rule:
            failures.append("typecheck refusal %s: expected %s first, refused as %s at %s"
                            % (rel(path), rule, found[0], found[1]))
        elif at and found[1] != at:
            failures.append("typecheck refusal %s: %s at %s, expected at %s"
                            % (rel(path), rule, found[1], at))
        counts["typecheck refusal fixtures"] = counts.get("typecheck refusal fixtures", 0) + 1
    return named


def rule_catalog():
    """Every rule id typecheck's source refuses by."""
    ids = set()
    for path in glob.glob(os.path.join(TYPECHECK_SOURCE, "*.saw")):
        with open(path) as fh:
            ids.update(_RULE_ID.findall(fh.read()))
    return ids


def check_catalog(failures, counts, named):
    catalog = rule_catalog()
    for rule in sorted(catalog):
        if rule not in named:
            failures.append("typecheck rule %s has no refusal fixture" % rule)
    for rule in sorted(named):
        if rule not in catalog:
            failures.append("typecheck fixtures name %s, which typecheck does not refuse by"
                            % rule)
    counts["typecheck rules"] = len(catalog)


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def check_acceptance(failures, counts):
    """The compiler's own source checks whole: the sawc2 build, then each unit
    program, each the entry of its own program. A unit program the parser
    refuses has no tree to check and is counted apart."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc2(["--check"] + package_args() + entries)
    got = records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("typecheck acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            counts["unit programs the parser refuses"] = (
                counts.get("unit programs the parser refuses", 0) + 1)
            continue
        for line in lines:
            failures.append("typecheck acceptance %s: %s" % (entry, line))
        counts["checked compiler programs"] = counts.get("checked compiler programs", 0) + 1


def check_invariants(failures, output_records):
    for path, record in output_records.items():
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("typecheck %s: %s" % (path, line))


def run(write=False, fill=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    named = check_refusals(failures, counts, fill)
    code, out = sawc2(["--check"] + [rel(p) for p in refusal_cases()]
                      + [rel(src) for src, _ in golden_cases()])
    check_invariants(failures, records(out))
    check_catalog(failures, counts, named)
    check_acceptance(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    fill = "--fill" in sys.argv[1:]
    failures, counts = run(write, fill)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("typecheck lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

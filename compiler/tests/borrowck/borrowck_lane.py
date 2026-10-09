#!/usr/bin/env python3
"""The borrowck lane: `sawc2 borrowck` against its golden records, refusal
fixtures, conformance matrix and the move-error differential.

    python compiler/tests/borrowck/borrowck_lane.py            # check
    python compiler/tests/borrowck/borrowck_lane.py --write    # rewrite the golden records
    python compiler/tests/borrowck/borrowck_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- CONFORMANCE.md accounts for every row of `examples/conformance/INDEX.md`'s
  five borrow-check sections, each with an owner from the matrix's own
  table, every `compiler/tests/` path it names exists, and every row the
  borrow check owns names a fixture or golden of this directory;
- each golden program, `golden/NAME.saw`, checks to exactly the record in
  `golden/NAME.borrowck`, which carries no `ERROR` or `INVARIANT` line;
- each refusal fixture, `refuse/RULE.saw` or `refuse/RULE.VARIANT.saw`, is
  refused first by RULE at the position its `// refuses:` header names, with
  no `INVARIANT` line under `sawc2 borrowck` nor under `sawc2 mir`, and every
  rule the borrow check refuses by (`borrowck_rules` in
  `compiler/borrowck/src/check.saw`) has a fixture;
- the compiler's own source, the sawc2 build and each unit program, and the
  new std under `--std-root std`, check with no refusal and no `INVARIANT`;
- every tests/corpus program that expects a move error is refused by a
  borrow-check rule, or `differential.tsv` says why not, and no line there
  names a program the borrow check does refuse. The drop labels over the
  compiler and over tests/corpus are counted for information.
"""
import collections
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

INDEX = os.path.join(REPO, "examples", "conformance", "INDEX.md")
MATRIX = os.path.join(HERE, "CONFORMANCE.md")
GOLDEN = os.path.join(HERE, "golden")
REFUSE = os.path.join(HERE, "refuse")
DIFFERENTIAL = os.path.join(HERE, "differential.tsv")
CORPUS = os.path.join(REPO, "tests", "corpus")
STD_ENTRY = os.path.join(TESTS, "std", "entry.saw")
RULES_SOURCE = os.path.join(COMPILER, "borrowck", "src", "check.saw")
TIMEOUT = 3600

# INDEX.md's five borrow-check sections, by the start of their headings, and
# the heading each has in the matrix.
SECTIONS = (
    ("## Mutability", "## Mutability"),
    ("## References are parameters only", "## References are parameters only"),
    ("## The Law of Exclusivity", "## The Law of Exclusivity"),
    ("## Moves and use-after-move", "## Moves and use-after-move"),
    ("## Places (`borrows` / `lend`)", "## Places (`borrows` / `lend`)"),
)
OWNERS = ("U6d1", "U6d2", "typecheck", "SL-462", "typecheck-gap", "parse", "mir", "§3.7", "§3.8", "§3.9",
          "slice.not-yet")
LABELS = ("static", "elided", "flagged")
BORROWCK_RULES = ("move.use-after", "consumes.some-paths")

_ROW = re.compile(r"^\| ([A-Z]\d+) \|")
_PATH = re.compile(r"`(compiler/tests/[^`]+)`")
_HEADER = re.compile(r"^// refuses: (\S+)(?: at (\d+:\d+))?$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
_EXPECT = re.compile(r"//\s*EXPECT-ERROR-CONTAINS:\s*(.*)")
# An expected diagnostic that names a move: the programs the differential
# holds the borrow check to.
_MOVE_ERROR = re.compile(r"moved|move out|partial move|cannot move|consumed", re.I)


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args, stage="borrowck"):
    r = subprocess.run([build.SAWC2, stage] + args, cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
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


def first_difference(expected, got):
    a = expected.split("\n")
    b = got.split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<end>"
        y = b[i] if i < len(b) else "<end>"
        if x != y:
            return "line %d: expected %r, got %r" % (i + 1, x[:90], y[:90])
    return "a trailing byte"


def section_rows(path, headings):
    """{heading: [row cells]} for the sections whose headings start with one
    of `headings`, in file order."""
    out = collections.OrderedDict((h, []) for h in headings)
    current = None
    with open(path) as fh:
        for line in fh:
            if line.startswith("## "):
                current = next((h for h in headings if line.startswith(h)), None)
                continue
            if current is not None and _ROW.match(line):
                out[current].append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def check_conformance(failures, counts):
    index = section_rows(INDEX, [s for s, _ in SECTIONS])
    matrix = section_rows(MATRIX, [m for _, m in SECTIONS])
    for source, heading in SECTIONS:
        want = collections.Counter(cells[0] for cells in index[source])
        have = collections.Counter(cells[0] for cells in matrix[heading])
        for row in sorted(want - have):
            failures.append("borrowck conformance %s: row %s of INDEX.md's %r is not in the matrix"
                            % (rel(MATRIX), row, source[3:]))
        for row in sorted(have - want):
            failures.append("borrowck conformance %s: row %s is in the matrix but not in INDEX.md's %r"
                            % (rel(MATRIX), row, source[3:]))
        for cells in matrix[heading]:
            if len(cells) < 3 or cells[1] not in OWNERS:
                failures.append("borrowck conformance %s: row %s names no owner of the matrix's table"
                                % (rel(MATRIX), cells[0]))
                continue
            named = _PATH.findall(cells[2])
            for path in named:
                if not os.path.exists(os.path.join(REPO, path)):
                    failures.append("borrowck conformance %s: row %s names %s, which does not exist"
                                    % (rel(MATRIX), cells[0], path))
            if cells[1] == "U6d1" and not any(p.startswith("compiler/tests/borrowck/") for p in named):
                failures.append("borrowck conformance %s: row %s is the borrow check's and names no fixture "
                                "or golden of compiler/tests/borrowck/" % (rel(MATRIX), cells[0]))
            key = "conformance rows: %s" % cells[1]
            counts[key] = counts.get(key, 0) + 1


def check_golden(failures, counts, write):
    cases = [(src, os.path.splitext(src)[0] + ".borrowck")
             for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))]
    code, out = sawc2(["--dump"] + [rel(src) for src, _ in cases])
    got = records(out)
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("borrowck golden %s: no record" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("borrowck golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("borrowck golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        for line in record.split("\n"):
            if line.startswith(("ERROR\t", "INVARIANT\t")):
                failures.append("borrowck golden %s: %s" % (rel(src), line))
        counts["borrowck golden cases"] = counts.get("borrowck golden cases", 0) + 1


def first_error(record):
    for line in record.split("\n"):
        if line.startswith("ERROR\t"):
            fields = line.split("\t")
            _, row, col = fields[2].rsplit(":", 2)
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


def borrowck_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func borrowck_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def check_refusals(failures, counts, fill):
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = records(out)
    code, lowered_out = sawc2(["--check"] + [rel(p) for p in cases], stage="mir")
    lowered = records(lowered_out)
    covered = set()
    for path in cases:
        record = got.get(rel(path), "")
        found = first_error(record)
        with open(path) as fh:
            m = _HEADER.match(fh.readline().rstrip("\n"))
        if fill and (m is None or m.group(1) == "TODO"):
            write_header(path, found)
            continue
        if m is None:
            failures.append("borrowck refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named = os.path.basename(path).split(".saw")[0]
        if not (named == rule or named.startswith(rule + ".")):
            failures.append("borrowck refusal %s: the file is not named for its rule %s" % (rel(path), rule))
        if found is None:
            failures.append("borrowck refusal %s: expected %s, nothing refused" % (rel(path), rule))
        elif found[0] != rule or (at and found[1] != at):
            failures.append("borrowck refusal %s: expected %s at %s first, refused as %s at %s"
                            % (rel(path), rule, at, found[0], found[1]))
        else:
            covered.add(rule)
        # The borrow check is the one that refuses: the stages before it
        # accept the fixture, and no verifier finds a problem in it.
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("borrowck refusal %s: under sawc2 borrowck: %s" % (rel(path), line))
        for line in lowered.get(rel(path), "").split("\n"):
            if line.startswith(("INVARIANT\t", "ERROR\t")):
                failures.append("borrowck refusal %s: under sawc2 mir: %s" % (rel(path), line))
        counts["borrowck refusal fixtures"] = counts.get("borrowck refusal fixtures", 0) + 1
    rules = borrowck_rules()
    for rule in rules:
        if rule not in covered:
            failures.append("borrowck rule %s: no refusal fixture refuses by it" % rule)
    counts["borrowck rules"] = len(rules)


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def count_labels(record, counts, prefix):
    for line in record.split("\n"):
        for label in LABELS:
            if line.endswith("  // " + label):
                key = "%s %s drops" % (prefix, label)
                counts[key] = counts.get(key, 0) + 1


def check_acceptance(failures, counts):
    """The compiler's own source checks whole: the sawc2 build, then each unit
    program, with no refusal and no invariant, and so does the new std. A
    unit program the parser refuses has nothing to check and is counted
    apart."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc2(["--check"] + package_args() + entries)
    got = records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("borrowck acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            continue
        for line in lines:
            failures.append("borrowck acceptance %s: %s" % (entry, line))
        counts["borrow-checked compiler programs"] = counts.get("borrow-checked compiler programs", 0) + 1
    code, out = sawc2(["--dump"] + package_args() + [entries[0]])
    count_labels(out, counts, "compiler")
    code, out = sawc2(["--check", "--std-root", "std", rel(STD_ENTRY)])
    for line in out.split("\n"):
        if line.startswith(("ERROR\t", "INVARIANT\t")):
            failures.append("borrowck acceptance std: %s" % line)


def corpus_programs():
    skip = ("/modules/", "/module_tests/", "/module_matrix/")
    return sorted(rel(p) for p in glob.glob(os.path.join(CORPUS, "**", "*.saw"), recursive=True)
                  if not any(s in p for s in skip))


def read_differential():
    """{path: reason} from differential.tsv."""
    out = {}
    with open(DIFFERENTIAL) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("path\t"):
                continue
            path, _, reason = line.partition("\t")
            out[path] = reason
    return out


def check_corpus(failures, counts):
    rels = corpus_programs()
    listing = os.path.join(REPO, ".build", "borrowck_corpus_list.txt")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    with open(listing, "w") as fh:
        fh.write("".join(p + "\n" for p in rels))
    r = subprocess.run([build.SAWC2, "borrowck", "--dump", "@" + rel(listing)], cwd=REPO,
                       capture_output=True, text=True, timeout=TIMEOUT)
    got = records(r.stdout)
    if r.returncode not in (0, 1):
        failures.append("borrowck corpus: sawc2 exited %d" % r.returncode)
    reasons = read_differential()
    expected = set()
    for path in rels:
        record = got.get(path, "")
        count_labels(record, counts, "corpus")
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t") and ("the statement at" in line or "initialisation state" in line):
                failures.append("borrowck corpus %s: %s" % (path, line))
        with open(os.path.join(REPO, path)) as fh:
            wanted = _EXPECT.findall(fh.read())
        if not any(_MOVE_ERROR.search(w) for w in wanted):
            continue
        expected.add(path)
        refused = any(l.startswith("ERROR\t") and l.split("\t")[1] in BORROWCK_RULES
                      for l in record.split("\n"))
        if refused:
            counts["corpus move errors refused"] = counts.get("corpus move errors refused", 0) + 1
            if path in reasons:
                failures.append("borrowck differential %s: refused by the borrow check, yet %s says why not"
                                % (path, rel(DIFFERENTIAL)))
        elif path not in reasons:
            failures.append("borrowck differential %s: expects a move error the borrow check does not refuse, "
                            "and %s gives no reason" % (path, rel(DIFFERENTIAL)))
        else:
            counts["corpus move errors owned elsewhere"] = counts.get("corpus move errors owned elsewhere", 0) + 1
    for path in sorted(reasons):
        if path not in expected:
            failures.append("borrowck differential %s: listed in %s but expects no move error"
                            % (path, rel(DIFFERENTIAL)))


def run(write=False, fill=False):
    failures = []
    counts = {}
    check_conformance(failures, counts)
    check_golden(failures, counts, write)
    check_refusals(failures, counts, fill)
    check_acceptance(failures, counts)
    check_corpus(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    fill = "--fill" in sys.argv[1:]
    failures, counts = run(write, fill)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("borrowck lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

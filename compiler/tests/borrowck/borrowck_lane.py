#!/usr/bin/env python3
"""The borrowck lane: `sawc2 borrowck` against its golden records, refusal
fixtures, conformance matrix and the move-error differential.

    python compiler/tests/borrowck/borrowck_lane.py            # check
    python compiler/tests/borrowck/borrowck_lane.py --write    # rewrite the golden records
    python compiler/tests/borrowck/borrowck_lane.py --fill     # fill `// refuses: TODO` headers
    python compiler/tests/borrowck/borrowck_lane.py --stage0   # record Stage 0's builds of the divergent fixtures

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each ledger `.gitattributes` merges by union (`LEDGERS`) gives every row
  an id of its own, and each fixture in `ledger/` fails that check;
- CONFORMANCE.md accounts for every row of `examples/conformance/INDEX.md`'s
  five borrow-check sections, each with an owner from the matrix's own
  table, every `compiler/tests/` path it names exists, and every row the
  borrow check owns (U6d1 or U6d2) names a fixture or golden of this
  directory;
- each golden program, `golden/NAME.saw`, checks to exactly the record in
  `golden/NAME.borrowck`, which carries no `ERROR` or `INVARIANT` line;
- each refusal fixture, `refuse/RULE.saw` or `refuse/RULE.VARIANT.saw`, is
  refused first by RULE at the position its `// refuses:` header names, with
  no `INVARIANT` line under `sawc2 borrowck` nor under `sawc2 mir`, and every
  rule the borrow check refuses by (`borrowck_rules` in
  `compiler/borrowck/src/check.saw`) has a fixture; a due fixture, headed
  `// due: RULE when ...`, is held to the refusal standing in its way;
- each premise program, `premise/NAME.saw`, is refused first by the earlier
  stage's rule its header names;
- the compiler's own source, the sawc2 build and each unit program, and the
  new std under `--std-root std`, check with no refusal and no `INVARIANT`;
- each generated program of `LONG_PROGRAMS`, deeper than any fixed budget of
  the loan analysis would reach, is refused first by its rule, or by none;
- every tests/corpus program that expects a move error is refused by a
  borrow-check rule, or `differential.tsv` says why not, and no line there
  names a program the borrow check does refuse;
- the loan differential, both ways: every tests/corpus program that expects
  an exclusivity or loan error is refused by a rule of the loan half, and
  every program expected to succeed is refused by none, or
  `loan_differential.tsv` names the program with its direction and the
  mechanism of the divergence; a fixture of this directory listed there is
  one Stage 0 compiles, by its recorded build (`stage0/HOST/NAME.stage0`,
  which `--stage0` writes through the v0 compiler). The drop labels over the
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
sys.path.insert(0, TESTS)

import build  # noqa: E402
import oracle  # noqa: E402

# Stage 0's recorded builds of the fixtures the loan differential says it
# compiles, one directory per host triple.
STAGE0 = os.path.join(HERE, "stage0")
INDEX = os.path.join(REPO, "examples", "conformance", "INDEX.md")
MATRIX = os.path.join(HERE, "CONFORMANCE.md")
GOLDEN = os.path.join(HERE, "golden")
REFUSE = os.path.join(HERE, "refuse")
PREMISE = os.path.join(HERE, "premise")
DIFFERENTIAL = os.path.join(HERE, "differential.tsv")
CORPUS = os.path.join(REPO, "tests", "corpus")
STD_ENTRY = os.path.join(TESTS, "std", "entry.saw")
RULES_SOURCE = os.path.join(COMPILER, "borrowck", "src", "check.saw")
TIMEOUT = 3600
GITATTRIBUTES = os.path.join(REPO, ".gitattributes")
LEDGER_FIXTURES = os.path.join(HERE, "ledger")

# The ledgers `.gitattributes` merges by union, each with the shape of its
# rows: a markdown table row's first cell, or a tsv line's first field after
# the header. A union merge keeps both sides' rows, so two patches that chose
# one id both land, and `check_ledgers` is what refuses that.
LEDGERS = (
    ("examples/conformance/INDEX.md", "table"),
    ("compiler/tests/borrowck/CONFORMANCE.md", "table"),
    ("compiler/tests/drops/conformance.tsv", "tsv"),
)
# Ids already carried by more than one row, each admitted on exactly that many
# rows: one more row, or one fewer, fails.
ADMITTED_DUPLICATES = {
    "examples/conformance/INDEX.md": {"X41": 2, "K53": 2},
    "compiler/tests/borrowck/CONFORMANCE.md": {"X41": 2},
}
# Each fixture of `ledger/`, its shape, and the one id it carries twice.
LEDGER_FIXTURE_CASES = (
    ("duplicate_row.md", "table", "V02"),
    ("duplicate_row.tsv", "tsv", "V02"),
)

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
# The owners whose rows must name a fixture or golden of this directory.
BORROWCK_OWNERS = ("U6d1", "U6d2")
# The rule prefixes of the loan half (U6d2), which the loan differential
# holds tests/corpus/ to.
LOAN_RULE_PREFIXES = ("loan.", "lend.", "assign.")
LOAN_DIFFERENTIAL = os.path.join(HERE, "loan_differential.tsv")
LOAN_DIRECTIONS = ("accepts", "refuses")
LOAN_CLASSES = ("owned", "order", "stage0-over-refusal", "stricter", "gap", "mir-bug")

_ROW = re.compile(r"^\| ([A-Z]\d+) \|")
_PATH = re.compile(r"`(compiler/tests/[^`]+)`")
_HEADER = re.compile(r"^// refuses: (\S+)(?: at (\d+:\d+))?$")
_DUE = re.compile(r"^// due: (\S+) when (.+)$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
_EXPECT = re.compile(r"//\s*EXPECT-ERROR-CONTAINS:\s*(.*)")
# An expected diagnostic that names a move: the programs the differential
# holds the borrow check to.
_MOVE_ERROR = re.compile(r"moved|move out|partial move|cannot move|consumed", re.I)
# An expected diagnostic that names an exclusivity or loan error: the programs
# the loan differential holds the loan half to. A window on an immutable root
# is a mutability error, typecheck's.
_LOAN_ERROR = re.compile(r"exclusiv|while also being accessed|window opened on it|for the whole window|"
                         r"cannot be held across a suspension|not rooted in the receiver|lends twice|"
                         r"returns no value|while a spawned task borrows|cannot be accessed by reference", re.I)
_NOT_LOAN_ERROR = re.compile(r"immutable", re.I)


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


def ledger_rows(path, shape):
    """[(line number, id, line)] for each row of a ledger of `shape`."""
    out = []
    header = shape == "tsv"
    with open(path) as fh:
        for number, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if shape == "table":
                m = _ROW.match(line)
                if m:
                    out.append((number, m.group(1), line))
            elif line and not line.startswith("#"):
                if header:
                    header = False
                    continue
                out.append((number, line.split("\t")[0], line))
    return out


def duplicate_rows(path, shape, admitted=None):
    """One failure per id carried by more rows than `admitted` allows (one by
    default), quoting each of those rows in full, and one per admitted id
    carried by fewer rows than it admits."""
    admitted = admitted or {}
    by_id = collections.OrderedDict()
    for number, ident, line in ledger_rows(path, shape):
        by_id.setdefault(ident, []).append((number, line))
    failures = []
    for ident, rows in by_id.items():
        if len(rows) > admitted.get(ident, 1):
            failures.append("borrowck ledger %s: row id %s is carried by %d rows: %s"
                            % (rel(path), ident, len(rows),
                               " / ".join("line %d: %s" % row for row in rows)))
    for ident, n in sorted(admitted.items()):
        if len(by_id.get(ident, ())) < n:
            failures.append("borrowck ledger %s: row id %s is admitted on %d rows but is carried by %d; "
                            "update ADMITTED_DUPLICATES" % (rel(path), ident, n, len(by_id.get(ident, ()))))
    return failures


def union_paths():
    """The paths `.gitattributes` marks `merge=union`, in order."""
    out = []
    with open(GITATTRIBUTES) as fh:
        for line in fh:
            fields = line.split()
            if fields and not fields[0].startswith("#") and "merge=union" in fields[1:]:
                out.append(fields[0])
    return out


def check_ledgers(failures, counts):
    """Every union-merged ledger's row ids are unique, the union-merged paths
    are exactly `LEDGERS`, and each fixture's duplicate is refused with both
    of its rows quoted."""
    marked = union_paths()
    listed = [path for path, _ in LEDGERS]
    for path in marked:
        if path not in listed:
            failures.append("borrowck ledger %s: %s merges by union, and LEDGERS does not check its row ids"
                            % (rel(GITATTRIBUTES), path))
    for path, shape in LEDGERS:
        if path not in marked:
            failures.append("borrowck ledger %s: %s is in LEDGERS but is not marked merge=union"
                            % (rel(GITATTRIBUTES), path))
        failures += duplicate_rows(os.path.join(REPO, path), shape, ADMITTED_DUPLICATES.get(path))
        counts["union-merged ledgers"] = counts.get("union-merged ledgers", 0) + 1
    for name, shape, ident in LEDGER_FIXTURE_CASES:
        path = os.path.join(LEDGER_FIXTURES, name)
        got = duplicate_rows(path, shape)
        rows = [line for _, row, line in ledger_rows(path, shape) if row == ident]
        expected = "borrowck ledger %s: row id %s is carried by %d rows: " % (rel(path), ident, len(rows))
        if len(rows) < 2 or len(got) != 1 or not got[0].startswith(expected) \
                or not all(line in got[0] for line in rows):
            failures.append("borrowck ledger %s: expected only row id %s refused, with each of its rows "
                            "quoted; got %r" % (rel(path), ident, got))
        counts["ledger fixtures"] = counts.get("ledger fixtures", 0) + 1


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
            if cells[1] in BORROWCK_OWNERS and not any(p.startswith("compiler/tests/borrowck/") for p in named):
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
            first = fh.readline().rstrip("\n")
            second = fh.readline().rstrip("\n")
        # A due fixture names the rule it is due for, then the refusal that
        # stands in its way until that rule's construct enters the slice.
        due = _DUE.match(first)
        m = _HEADER.match(second if due else first)
        if fill and not due and (m is None or m.group(1) == "TODO"):
            write_header(path, found)
            continue
        if m is None:
            failures.append("borrowck refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named_rule = due.group(1) if due else rule
        named = os.path.basename(path).split(".saw")[0]
        if not (named == named_rule or named.startswith(named_rule + ".")):
            failures.append("borrowck refusal %s: the file is not named for its rule %s" % (rel(path), named_rule))
        if found is None:
            failures.append("borrowck refusal %s: expected %s, nothing refused" % (rel(path), rule))
        elif found[0] != rule or (at and found[1] != at):
            if due:
                failures.append("borrowck refusal %s: the due row %s is due (%s): it is no longer refused as %s"
                                % (rel(path), named_rule, due.group(2), rule))
            else:
                failures.append("borrowck refusal %s: expected %s at %s first, refused as %s at %s"
                                % (rel(path), rule, at, found[0], found[1]))
        elif not due:
            covered.add(rule)
        # The borrow check is the one that refuses: the stages before it
        # accept the fixture, and no verifier finds a problem in it.
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("borrowck refusal %s: under sawc2 borrowck: %s" % (rel(path), line))
        for line in lowered.get(rel(path), "").split("\n"):
            if line.startswith("INVARIANT\t") or (line.startswith("ERROR\t") and not due):
                failures.append("borrowck refusal %s: under sawc2 mir: %s" % (rel(path), line))
        key = "borrowck due fixtures" if due else "borrowck refusal fixtures"
        counts[key] = counts.get(key, 0) + 1
    rules = borrowck_rules()
    for rule in rules:
        if rule not in covered:
            failures.append("borrowck rule %s: no refusal fixture refuses by it" % rule)
    counts["borrowck rules"] = len(rules)


def check_premise(failures, counts):
    """The soundness premise: each program in premise/ is refused first by
    the typecheck rule its header names, so no reference reaches the borrow
    check able to outlive its function."""
    cases = sorted(glob.glob(os.path.join(PREMISE, "*.saw")))
    if not cases:
        failures.append("borrowck premise %s: no premise program" % rel(PREMISE))
        return
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = records(out)
    rules = borrowck_rules()
    for path in cases:
        with open(path) as fh:
            m = _HEADER.match(fh.readline().rstrip("\n"))
        found = first_error(got.get(rel(path), ""))
        if m is None or m.group(1) in rules:
            failures.append("borrowck premise %s: no `// refuses: RULE at L:C` header naming a rule of an "
                            "earlier stage" % rel(path))
        elif found != (m.group(1), m.group(2)):
            failures.append("borrowck premise %s: expected %s at %s first, got %s"
                            % (rel(path), m.group(1), m.group(2), "nothing" if found is None else
                               "%s at %s" % found))
        counts["borrowck premise programs"] = counts.get("borrowck premise programs", 0) + 1


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


def window_chain_source(n):
    """An accessor lending through `n` nested windows, each opened on the
    lent reference before it; legal, since every hop traces to `self`, two
    trace steps per window."""
    pad = "        "
    lines = ["struct Cell {", "    value: Int", "}", "", "extension Cell {",
             "    func me(&var self) borrows -> &var Cell {", "        lend self", "    }", "}", "",
             "struct Grid {", "    cell: Cell", "}", "", "extension Grid {",
             "    func deep(&var self) borrows -> &var Int {", pad + "borrow var c1 = self.cell.me() {"]
    for k in range(2, n + 1):
        lines.append(pad + "    " * (k - 1) + "borrow var c%d = c%d.me() {" % (k, k - 1))
    lines.append(pad + "    " * n + "lend c%d.value" % n)
    lines += [pad + "    " * (k - 1) + "}" for k in range(n, 0, -1)]
    lines += ["    }", "}", "", "func main() {", "    var g = Grid(cell: Cell(value: 0))",
              "    borrow var v = g.deep() {", "        v = 5", "    }", '    print("{}", g.cell.value)', "}"]
    return "\n".join(lines) + "\n"


def pointer_chain_source(n, from_receiver):
    """An accessor lending through a pointer copied through `n` locals: read
    out of the receiver it is legal, and taken from a parameter it is
    `lend.root`."""
    params = "" if from_receiver else ", q: UnsafePointer<Int>"
    lines = ["struct Holder {", "    ptr: UnsafePointer<Int>", "}", "", "extension Holder {",
             "    func at(&var self%s) unsafe borrows -> &var Int {" % params,
             "        let p0 = %s" % ("self.ptr" if from_receiver else "q")]
    lines += ["        let p%d = p%d" % (k, k - 1) for k in range(1, n + 1)]
    lines += ["        lend p%d[0]" % n, "    }", "}", "", "func main() {", "}"]
    return "\n".join(lines) + "\n"


def cell_chain_source(n, cell):
    """`n` shared hops under a second shared window on the root: ending in a
    cell accessor, every hop charges the root exclusively and the second
    window is `loan.window-root`; ending in a shared hop, it is legal."""
    last = ".lock()" if cell else ".me()"
    use = "a + 1" if cell else "a.at[0] + 1"
    lines = ["struct Node {", "    at: UnsafePointer<Int>", "}", "", "extension Node {",
             "    func me(&self) borrows -> &Node {", "        lend self", "    }", "",
             "    func lock(&self) unsafe borrows -> &var Int {", "        lend self.at[0]", "    }", "}", "",
             "func twice(n: &Node) unsafe -> Int {", "    borrow let a = n%s%s {" % (".me()" * n, last),
             "        borrow let b = n.me() {", "            %s" % use, "        }", "    }", "}", "",
             "func main() {", "}"]
    return "\n".join(lines) + "\n"


def long_ifs_source(n):
    """A window open across `n` sequential `if`s: each `if`'s join is
    numbered below its arms, which a dataflow swept in index order pays a
    round for."""
    lines = ["func main() {", "    var v = [1, 2, 3]", "    var t = 0", "    borrow var c = v[1] {"]
    for k in range(n):
        lines += ["        if t > %d {" % k, "            t = 1", "        }"]
    lines += ["        c = 7", "    }", '    print("{} {}", t, v[1])', "}"]
    return "\n".join(lines) + "\n"


# Generated programs deeper than any fixed budget of the loan analysis would
# reach, each with the rule it is refused by first, or None (SL-619):
# `borrowck_trace` and `from_receiver` walk definitions to the end, and the
# block dataflows and the window-exclusivity propagation run to their
# fixpoints.
LONG_PROGRAMS = (
    ("window_chain_33", window_chain_source(33), None),
    ("pointer_chain_32", pointer_chain_source(32, True), None),
    ("pointer_parameter_chain_32", pointer_chain_source(32, False), "lend.root"),
    ("cell_chain_40", cell_chain_source(40, True), "loan.window-root"),
    ("shared_chain_40", cell_chain_source(40, False), None),
    ("long_ifs_1100", long_ifs_source(1100), None),
)


def check_long_programs(failures, counts):
    """Each of `LONG_PROGRAMS` is refused first by its rule, or by none, with
    no `INVARIANT`."""
    directory = os.path.join(REPO, ".build", "borrowck_long")
    os.makedirs(directory, exist_ok=True)
    paths = []
    for name, source, _ in LONG_PROGRAMS:
        path = os.path.join(directory, name + ".saw")
        with open(path, "w") as fh:
            fh.write(source)
        paths.append(rel(path))
    code, out = sawc2(["--check", "--std-root", "std"] + paths)
    got = records(out)
    for path, (name, _, rule) in zip(paths, LONG_PROGRAMS):
        record = got.get(path)
        if record is None:
            failures.append("borrowck long program %s: no record" % name)
            continue
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("borrowck long program %s: %s" % (name, line))
        found = first_error(record)
        found_rule = found[0] if found else None
        if found_rule != rule:
            failures.append("borrowck long program %s: expected %s, refused as %s"
                            % (name, rule or "no refusal", found_rule or "nothing"))
        counts["long programs"] = counts.get("long programs", 0) + 1


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
    rules = borrowck_rules()
    loan_reasons = read_loan_differential(failures)
    loan_seen = set()
    expected = set()
    for path in rels:
        record = got.get(path, "")
        count_labels(record, counts, "corpus")
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t") and ("the statement at" in line or "initialisation state" in line):
                failures.append("borrowck corpus %s: %s" % (path, line))
        with open(os.path.join(REPO, path)) as fh:
            text = fh.read()
        wanted = _EXPECT.findall(text)
        check_loan_row(path, text, wanted, record, loan_reasons, loan_seen, failures, counts)
        if not any(_MOVE_ERROR.search(w) for w in wanted):
            continue
        expected.add(path)
        refused = any(l.startswith("ERROR\t") and l.split("\t")[1] in rules
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
    for path in sorted(loan_reasons):
        if path.startswith("compiler/tests/borrowck/"):
            check_fixture_divergence(path, loan_reasons[path], failures, counts)
        elif path not in loan_seen:
            failures.append("borrowck loan differential %s: listed in %s, but neither expects a loan error nor "
                            "is refused by a loan rule while expecting success" % (path, rel(LOAN_DIFFERENTIAL)))


def check_fixture_divergence(path, row, failures, counts):
    """A refusal fixture of this directory that Stage 0 runs: the loan half
    refuses it by a loan rule, and Stage 0 compiles it, as its `refuses`
    line says."""
    if row[0] != "refuses":
        failures.append("borrowck loan differential %s: a fixture's line must be `refuses`" % path)
        return
    code, out = sawc2(["--check", path])
    record = records(out).get(path, "")
    found = first_error(record)
    if found is None or not found[0].startswith(LOAN_RULE_PREFIXES):
        failures.append("borrowck loan differential %s: listed as refused by a loan rule, refused as %s"
                        % (path, "nothing" if found is None else found[0]))
    with open(os.path.join(REPO, path), "rb") as fh:
        data = fh.read()
    name = stage0_name(path)
    rec, why = oracle.load_run(STAGE0, name, data, stage0_command())
    if rec is None:
        failures.append("borrowck loan differential %s: %s" % (path, why))
    elif rec.build != "ok":
        failures.append("borrowck loan differential %s: listed as one Stage 0 compiles, and Stage 0 refuses it"
                        % path)
    key = "fixture divergences from Stage 0: %s" % row[1]
    counts[key] = counts.get(key, 0) + 1


def stage0_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def stage0_command():
    return "python compiler/tests/borrowck/borrowck_lane.py --stage0"


def divergent_fixtures():
    """The fixtures of this directory the loan differential lists, which
    Stage 0 is to compile."""
    return sorted(p for p in read_loan_differential([]) if p.startswith("compiler/tests/borrowck/"))


def record_stage0():
    """Stage 0 compiles each fixture the loan differential lists (`-c`, no
    link), and its record replaces the one in `STAGE0`; a record naming none
    is removed. The lane's only run of Stage 0, through the v0 compiler
    (`oracle.v0_compiler`)."""
    triple = build.host_triple()
    paths = divergent_fixtures()
    for path in paths:
        rec = oracle.record_run(os.path.join(REPO, path), oracle.record_file(STAGE0, triple, stage0_name(path)),
                                path, flags=["-c"], runs=0)
        print("borrowck lane stage0 %s %s: build %s" % (triple, stage0_name(path), rec.build))
    for stale in oracle.stale_records(os.path.join(STAGE0, triple), {stage0_name(p) for p in paths}):
        os.remove(stale)
        print("borrowck lane stage0: removed %s" % rel(stale))
    return 0


def read_loan_differential(failures):
    """{path: (direction, class, reason)} from loan_differential.tsv."""
    out = {}
    with open(LOAN_DIFFERENTIAL) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("path\t"):
                continue
            fields = line.split("\t")
            if len(fields) != 4 or fields[1] not in LOAN_DIRECTIONS or fields[2] not in LOAN_CLASSES:
                failures.append("borrowck loan differential %s: a line is not PATH, DIRECTION, CLASS, WHY with a "
                                "direction of %s and a class of %s: %r"
                                % (rel(LOAN_DIFFERENTIAL), "/".join(LOAN_DIRECTIONS), "/".join(LOAN_CLASSES),
                                   line[:80]))
                continue
            out[fields[0]] = (fields[1], fields[2], fields[3])
    return out


def check_loan_row(path, text, wanted, record, loan_reasons, loan_seen, failures, counts):
    """The loan differential, both ways: a program whose expected diagnostic
    names an exclusivity or loan error is refused by a rule of the loan half,
    or loan_differential.tsv says why not (`accepts`); a program expected to
    succeed that a rule of the loan half refuses is listed too (`refuses`),
    each with the mechanism of the divergence."""
    loan_rules = [l.split("\t")[1] for l in record.split("\n")
                  if l.startswith("ERROR\t") and l.split("\t")[1].startswith(LOAN_RULE_PREFIXES)]
    expects_loan = any(_LOAN_ERROR.search(w) and not _NOT_LOAN_ERROR.search(w) for w in wanted)
    expects_success = "// EXPECT: error" not in text
    listed = loan_reasons.get(path)
    if expects_loan:
        loan_seen.add(path)
        if loan_rules:
            counts["corpus loan errors refused"] = counts.get("corpus loan errors refused", 0) + 1
            if listed is not None:
                failures.append("borrowck loan differential %s: refused by %s, yet %s says why not"
                                % (path, loan_rules[0], rel(LOAN_DIFFERENTIAL)))
        elif listed is None or listed[0] != "accepts":
            failures.append("borrowck loan differential %s: expects a loan error no loan rule refuses, and %s "
                            "gives no `accepts` line" % (path, rel(LOAN_DIFFERENTIAL)))
        else:
            key = "corpus loan errors accepted: %s" % listed[1]
            counts[key] = counts.get(key, 0) + 1
    elif expects_success and loan_rules:
        loan_seen.add(path)
        if listed is None or listed[0] != "refuses":
            failures.append("borrowck loan differential %s: expected to succeed, refused by %s, and %s gives no "
                            "`refuses` line" % (path, loan_rules[0], rel(LOAN_DIFFERENTIAL)))
        else:
            key = "corpus successes refused: %s" % listed[1]
            counts[key] = counts.get(key, 0) + 1


def run(write=False, fill=False):
    failures = []
    counts = {}
    check_ledgers(failures, counts)
    check_conformance(failures, counts)
    check_golden(failures, counts, write)
    check_refusals(failures, counts, fill)
    check_premise(failures, counts)
    check_acceptance(failures, counts)
    check_long_programs(failures, counts)
    check_corpus(failures, counts)
    for stale in oracle.stale_records(STAGE0, {stage0_name(p) for p in divergent_fixtures()}):
        failures.append("borrowck loan differential %s: a Stage 0 record of no listed fixture; `%s` removes it"
                        % (rel(stale), stage0_command()))
    return failures, counts


def main():
    if "--stage0" in sys.argv[1:]:
        return record_stage0()
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

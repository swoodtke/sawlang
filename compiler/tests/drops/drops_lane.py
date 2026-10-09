#!/usr/bin/env python3
"""The drops lane: `sawc2 drops` against its golden records, refusal and due
fixtures, the compiler's own source, the new std, tests/corpus and the
conformance rows drop elaboration owns.

    python compiler/tests/drops/drops_lane.py            # check
    python compiler/tests/drops/drops_lane.py --write    # rewrite the golden records

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw`, elaborates to exactly the record in
  `golden/NAME.drops`, which carries no `ERROR` or `INVARIANT` line; a first
  line `// flags: ...` passes those flags, and under `--std-root` the record
  keeps the entry module's dump alone;
- each fixture in `refuse/` is refused first at its header's position: by its
  rule, or, for a due row, by the refusal standing in its way, until that one
  is lifted; every rule drop elaboration refuses by (`drops_rules` in
  `compiler/drops/src/elaborate.saw`) has a fixture;
- the compiler's own source, the sawc2 build and each unit program, and the
  new std's entry under `--std-root std`, elaborate with no refusal and no
  `INVARIANT`;
- every tests/corpus program that elaborates does so with no `INVARIANT`, so
  the verifier after elaboration is clean over it; the flags over the sawc2
  build and over the corpus are counted;
- each conformance row CONFORMANCE.md gives drop elaboration (owner `§3.7`)
  names a fixture of this directory, and `conformance.tsv` holds each row's
  program to its summary.
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
sys.path.insert(0, os.path.join(TESTS, "borrowck"))

import build  # noqa: E402
import borrowck_lane  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
REFUSE = os.path.join(HERE, "refuse")
CONFORMANCE_TSV = os.path.join(HERE, "conformance.tsv")
MATRIX = os.path.join(TESTS, "borrowck", "CONFORMANCE.md")
STD_ENTRY = os.path.join(TESTS, "std", "entry.saw")
RULES_SOURCE = os.path.join(COMPILER, "drops", "src", "elaborate.saw")
TIMEOUT = 3600

_FLAGS = re.compile(r"^// flags: (.*)$")
_DUE = re.compile(r"^// due: (\S+) when (.+)$")
_HEADER = re.compile(r"^// refuses: (\S+) at (\d+:\d+)$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
_FLAG_LOCAL = re.compile(r"^    let _\d+: Bool;  // flag ")
_DROP = re.compile(r"^        drop\(")
_ROW = re.compile(r"^\| ([A-Z]\d+) \| ([^|]+) \|(.*)\|$")
# Due rows that pin an order rather than a refusal: the dump they will check.
PINS = ("order.borrowing-struct",)


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "drops"] + args, cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def entry_module_only(record, name):
    """The record's lines before its first dump, then module `name`'s dump."""
    out = []
    keep = True
    for line in record.split("\n"):
        if line.startswith("module "):
            keep = line == "module " + name
        if keep:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def check_golden(failures, counts, write):
    cases = sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))
    groups = {}
    for src in cases:
        with open(src) as fh:
            m = _FLAGS.match(fh.readline().rstrip("\n"))
        flags = tuple(m.group(1).split()) if m else ()
        groups.setdefault(flags, []).append(src)
    for flags, srcs in sorted(groups.items()):
        code, out = sawc2(["--dump"] + list(flags) + [rel(s) for s in srcs])
        got = borrowck_lane.records(out)
        for src in srcs:
            exp = os.path.splitext(src)[0] + ".drops"
            record = got.get(rel(src))
            if record is None:
                failures.append("drops golden %s: no record" % rel(src))
                continue
            if "--std-root" in flags:
                record = entry_module_only(record, os.path.splitext(os.path.basename(src))[0])
            if write:
                with open(exp, "w") as fh:
                    fh.write(record)
                continue
            if not os.path.exists(exp):
                failures.append("drops golden %s: no expectation %s" % (rel(src), rel(exp)))
                continue
            with open(exp) as fh:
                expected = fh.read()
            if expected != record:
                failures.append("drops golden %s: the record differs at %s"
                                % (rel(src), borrowck_lane.first_difference(expected, record)))
            for line in record.split("\n"):
                if line.startswith(("ERROR\t", "INVARIANT\t")):
                    failures.append("drops golden %s: %s" % (rel(src), line))
            counts["drops golden cases"] = counts.get("drops golden cases", 0) + 1


def drops_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func drops_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def check_refusals(failures, counts):
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = borrowck_lane.records(out)
    rules = drops_rules()
    covered = set()
    for path in cases:
        with open(path) as fh:
            first = fh.readline().rstrip("\n")
            second = fh.readline().rstrip("\n")
        due = _DUE.match(first)
        header = _HEADER.match(second if due else first)
        if header is None:
            failures.append("drops refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        named = due.group(1) if due else header.group(1)
        if not os.path.basename(path).startswith(named + "."):
            failures.append("drops refusal %s: the file is not named for %s" % (rel(path), named))
        if named not in rules and named not in PINS:
            failures.append("drops refusal %s: %s is no rule of drops_rules() and no pin" % (rel(path), named))
        found = borrowck_lane.first_error(got.get(rel(path), ""))
        want = (header.group(1), header.group(2))
        if found != want:
            if due and (found is None or found[0] != header.group(1)):
                failures.append("drops refusal %s: the due row %s is due (%s): it is no longer refused as %s"
                                % (rel(path), named, due.group(2), header.group(1)))
            else:
                failures.append("drops refusal %s: expected %s at %s first, got %s"
                                % (rel(path), want[0], want[1], "nothing" if found is None else
                                   "%s at %s" % found))
        else:
            covered.add(named)
        for line in got.get(rel(path), "").split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("drops refusal %s: %s" % (rel(path), line))
        counts["drops refusal fixtures"] = counts.get("drops refusal fixtures", 0) + 1
    for rule in rules:
        if rule not in covered:
            failures.append("drops rule %s: no refusal or due fixture names it" % rule)
    counts["drops rules"] = len(rules)


def count_flags(record, counts, prefix):
    for line in record.split("\n"):
        if _FLAG_LOCAL.match(line):
            key = "%s drop flags" % prefix
            counts[key] = counts.get(key, 0) + 1


def check_acceptance(failures, counts):
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in borrowck_lane.unit_programs()]
    code, out = sawc2(["--check"] + borrowck_lane.package_args() + entries)
    got = borrowck_lane.records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("drops acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            continue
        for line in lines:
            failures.append("drops acceptance %s: %s" % (entry, line))
        counts["elaborated compiler programs"] = counts.get("elaborated compiler programs", 0) + 1
    code, out = sawc2(["--dump"] + borrowck_lane.package_args() + [entries[0]])
    count_flags(out, counts, "compiler")
    code, out = sawc2(["--check", "--std-root", "std", rel(STD_ENTRY)])
    for line in out.split("\n"):
        if line.startswith(("ERROR\t", "INVARIANT\t")):
            failures.append("drops acceptance std: %s" % line)


def corpus_records():
    rels = borrowck_lane.corpus_programs()
    listing = os.path.join(REPO, ".build", "drops_corpus_list.txt")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    with open(listing, "w") as fh:
        fh.write("".join(p + "\n" for p in rels))
    code, out = sawc2(["--dump", "@" + rel(listing)])
    return code, rels, borrowck_lane.records(out)


def elaborated(record):
    return any(line.startswith("module ") for line in record.split("\n"))


def summary(record):
    """`drops N, flags M` over a record's dump, or `refused RULE`."""
    found = borrowck_lane.first_error(record)
    if found is not None:
        return "refused %s" % found[0]
    if not elaborated(record):
        return "not elaborated"
    drops = sum(1 for l in record.split("\n") if _DROP.match(l))
    flags = sum(1 for l in record.split("\n") if _FLAG_LOCAL.match(l))
    return "drops %d, flags %d" % (drops, flags)


def check_corpus(failures, counts, got, rels):
    for path in rels:
        record = got.get(path, "")
        if not elaborated(record):
            continue
        counts["elaborated corpus programs"] = counts.get("elaborated corpus programs", 0) + 1
        count_flags(record, counts, "corpus")
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("drops corpus %s: %s" % (path, line))


def read_conformance():
    """[(row, path, summary)] from conformance.tsv."""
    out = []
    with open(CONFORMANCE_TSV) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("row\t"):
                continue
            row, path, want = line.split("\t")[:3]
            out.append((row, path, want))
    return out


def check_conformance(failures, counts, got):
    rows = read_conformance()
    listed = {row for row, _, _ in rows}
    with open(MATRIX) as fh:
        for line in fh:
            m = _ROW.match(line.rstrip("\n"))
            if not m or m.group(2).strip() != "§3.7":
                continue
            row = m.group(1)
            if "compiler/tests/drops/" not in m.group(3):
                failures.append("drops conformance %s: row %s is drop elaboration's and names no fixture of "
                                "compiler/tests/drops/" % (rel(MATRIX), row))
            if row not in listed:
                failures.append("drops conformance %s: row %s has no line in %s"
                                % (rel(MATRIX), row, rel(CONFORMANCE_TSV)))
    for row, path, want in rows:
        record = got.get(path)
        if record is None:
            failures.append("drops conformance %s: row %s's program %s has no record" % (rel(CONFORMANCE_TSV), row, path))
            continue
        have = summary(record)
        if have != want:
            failures.append("drops conformance %s: row %s's program %s gives `%s`, not `%s`"
                            % (rel(CONFORMANCE_TSV), row, path, have, want))
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t") and elaborated(record):
                failures.append("drops conformance %s: row %s: %s" % (rel(CONFORMANCE_TSV), row, line))
        counts["drops conformance rows"] = counts.get("drops conformance rows", 0) + 1


def run(write=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    check_refusals(failures, counts)
    check_acceptance(failures, counts)
    code, rels, got = corpus_records()
    if code not in (0, 1):
        failures.append("drops corpus: sawc2 exited %d" % code)
    check_corpus(failures, counts, got, rels)
    check_conformance(failures, counts, got)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    failures, counts = run(write)
    for failure in failures:
        print(failure)
    summary_line = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("drops lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary_line))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

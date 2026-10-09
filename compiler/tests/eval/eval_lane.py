#!/usr/bin/env python3
"""The evaluator lane: `sawc2 eval` against its golden records and refusal fixtures.

    python compiler/tests/eval/eval_lane.py            # check
    python compiler/tests/eval/eval_lane.py --write    # rewrite the golden records
    python compiler/tests/eval/eval_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw`, evaluates to exactly the record in
  `golden/NAME.eval`, which carries no `INVARIANT` line;
- each refusal fixture, `refuse/RULE.saw` or `refuse/RULE.VARIANT.saw`, is
  refused first by RULE at the position its `// refuses:` header names, and
  every rule the evaluator refuses by (`eval_rules` in
  `compiler/eval/src/report.saw`) has a fixture;
- the compiler's own source, the sawc2 build and each unit program,
  evaluates with no refusal and no `INVARIANT` line;
- over tests/corpus/, the evaluator and typecheck's fold agree on every
  constant: a disagreement, or any other problem the evaluator's verifier
  finds, fails the lane. How many constants the corpus has, and how many the
  evaluator values, is reported for information.
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
REFUSE = os.path.join(HERE, "refuse")
CORPUS = os.path.join(REPO, "tests", "corpus")
RULES_SOURCE = os.path.join(COMPILER, "eval", "src", "report.saw")
TIMEOUT = 3600

_HEADER = re.compile(r"^// refuses: (\S+)(?: at (\d+:\d+))?$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
# The problems the evaluator's verifier reports, told apart from the earlier
# stages' by their wording.
_EVAL_PROBLEMS = ("the evaluator and typecheck's fold disagree", "a constant position was never evaluated",
                  "a constant's value is not of its position's type")


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "eval"] + args, cwd=REPO, capture_output=True, text=True,
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


def check_golden(failures, counts, write):
    cases = [(src, os.path.splitext(src)[0] + ".eval")
             for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))]
    code, out = sawc2(["--dump"] + [rel(src) for src, _ in cases])
    got = records(out)
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("eval golden %s: no record" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("eval golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("eval golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("eval golden %s: %s" % (rel(src), line))
        counts["eval golden cases"] = counts.get("eval golden cases", 0) + 1


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


def evaluator_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func eval_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def check_refusals(failures, counts, fill):
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = records(out)
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
            failures.append("eval refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        named = os.path.basename(path).split(".saw")[0]
        if not (named == rule or named.startswith(rule + ".")):
            failures.append("eval refusal %s: the file is not named for its rule %s" % (rel(path), rule))
        if found is None:
            failures.append("eval refusal %s: expected %s, nothing refused" % (rel(path), rule))
        elif found[0] != rule or (at and found[1] != at):
            failures.append("eval refusal %s: expected %s at %s first, refused as %s at %s"
                            % (rel(path), rule, at, found[0], found[1]))
        else:
            covered.add(rule)
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("eval refusal %s: %s" % (rel(path), line))
        counts["eval refusal fixtures"] = counts.get("eval refusal fixtures", 0) + 1
    rules = evaluator_rules()
    for rule in rules:
        if rule not in covered:
            failures.append("eval rule %s: no refusal fixture refuses by it" % rule)
    counts["eval rules"] = len(rules)


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def check_acceptance(failures, counts):
    """The compiler's own source evaluates whole: the sawc2 build, then each
    unit program, with no refusal and no invariant. A unit program the parser
    refuses has nothing to evaluate and is counted apart."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc2(["--check"] + package_args() + entries)
    got = records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("eval acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            continue
        for line in lines:
            failures.append("eval acceptance %s: %s" % (entry, line))
        counts["evaluated compiler programs"] = counts.get("evaluated compiler programs", 0) + 1
    code, out = sawc2(["--dump"] + package_args() + [entries[0]])
    counts["compiler constants evaluated"] = sum(
        1 for l in out.split("\n") if " = " in l and not l.startswith(("ERROR", "INVARIANT")))


def evaluate_all(rels, listing):
    """{path: record} for the programs `rels`; a program its process died in
    has no record, and the programs after it are evaluated afresh."""
    got = {}
    crashed = []
    pending = list(rels)
    while pending:
        with open(listing, "w") as fh:
            fh.write("".join(p + "\n" for p in pending))
        r = subprocess.run([build.SAWC2, "eval", "--dump", "@" + rel(listing)], cwd=REPO,
                           capture_output=True, text=True, timeout=TIMEOUT)
        found = records(r.stdout)
        if r.returncode in (0, 1):
            got.update(found)
            break
        dead = next(p for p in pending if p not in found)
        for path in pending[:pending.index(dead)]:
            got[path] = found[path]
        crashed.append(dead)
        pending = pending[pending.index(dead) + 1:]
    return got, crashed


def check_corpus(failures, counts):
    files = sorted(glob.glob(os.path.join(CORPUS, "*.saw")))
    rels = [rel(p) for p in files]
    listing = os.path.join(REPO, ".build", "eval_corpus_list.txt")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    got, crashed = evaluate_all(rels, listing)
    for path in crashed:
        failures.append("eval corpus %s: the evaluator crashed" % path)
    valued = without = 0
    for path in rels:
        record = got.get(path, "")
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t") and any(p in line for p in _EVAL_PROBLEMS):
                failures.append("eval corpus %s: %s" % (path, line))
            elif line.startswith(("static ", "raw ", "align ", "static_assert ")):
                if line.endswith("(no value)"):
                    without += 1
                elif " = " in line:
                    valued += 1
    counts["corpus constants valued"] = valued
    counts["corpus constants with no value"] = without


def run(write=False, fill=False):
    failures = []
    counts = {}
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
    print("eval lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

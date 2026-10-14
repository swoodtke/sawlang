#!/usr/bin/env python3
"""The coro lane: `sawc2 coro` against its golden frame decisions, frame
layouts and refusal fixtures, and its decisions against typecheck's
summaries.

    python compiler/tests/coro/coro_lane.py            # check
    python compiler/tests/coro/coro_lane.py --write    # rewrite the golden records

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw`, gives exactly the record in
  `golden/NAME.coro` (`--dump`), the one in `golden/NAME.layouts`
  (`--layouts`) and the one in `golden/NAME.lowered` (`--lowered`), with no
  `INVARIANT` line and no refusal but coroutine lowering's own;
- each fixture in `refuse/` is refused first at its header's position by the
  rule its name starts with, that refusal's message holds each of its
  `// message:` lines, and every rule coroutine lowering refuses by
  (`coro_rules` in `compiler/coro/src/suspends.saw`) has a fixture;
- over every program of this lane, of the mono lane's goldens and of the run
  lane, coroutine lowering's frame decisions agree with typecheck's
  summaries wherever a summary is unconditional, and every frame is laid
  out: `sawc2 coro --layouts` gives each a record with no `INVARIANT` line.
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
MODULES = os.path.join(HERE, "modules")
RULES_SOURCE = os.path.join(COMPILER, "coro", "src", "suspends.saw")
AGREEMENT = (os.path.join(TESTS, "mono", "golden"), os.path.join(TESTS, "run"))
TIMEOUT = 600

_HEADER = re.compile(r"^// refuses: (\S+) at (\d+:\d+)$")
_MESSAGE = re.compile(r"^// message: (.+)$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')


def rel(path):
    return os.path.relpath(path, REPO)


def module_args():
    """`--module-path` for each package under `modules/`, which a fixture
    imports by its directory's name."""
    args = []
    for directory in sorted(glob.glob(os.path.join(MODULES, "*"))):
        if os.path.isdir(directory):
            args += ["--module-path", "%s=%s" % (os.path.basename(directory), rel(directory))]
    return args


def sawc2(args):
    r = subprocess.run([build.SAWC2, "coro"] + args, cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def coro_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func coro_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def errors(record):
    """Each `ERROR` line of a record as (rule, L:C, message)."""
    out = []
    for line in record.split("\n"):
        if line.startswith("ERROR\t"):
            fields = line.split("\t", 3)
            _, row, col = fields[2].rsplit(":", 2)
            out.append((fields[1], "%s:%s" % (row, col), fields[3] if len(fields) > 3 else ""))
    return out


def check_invariants(failures, kind, path, record):
    for line in record.split("\n"):
        if line.startswith("INVARIANT\t"):
            failures.append("coro %s %s: %s" % (kind, rel(path), line))


def check_golden(failures, counts, write, rules, mode, suffix):
    """Each golden program's `mode` record against its `suffix` file."""
    cases = sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))
    code, out = sawc2([mode, "--std-root", "std"] + module_args() + [rel(s) for s in cases])
    got = borrowck_lane.records(out)
    for src in cases:
        exp = os.path.splitext(src)[0] + suffix
        record = got.get(rel(src))
        if record is None:
            failures.append("coro golden %s: no %s record" % (rel(src), mode))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("coro golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("coro golden %s: the %s record differs at %s"
                            % (rel(src), mode, borrowck_lane.first_difference(expected, record)))
        for rule, where, _ in errors(record):
            if rule not in rules:
                failures.append("coro golden %s: refused by %s at %s, before coroutine lowering"
                                % (rel(src), rule, where))
        check_invariants(failures, "golden", src, record)
        key = {"--dump": "coro golden records", "--layouts": "coro layout records"}.get(mode, "coro lowered records")
        counts[key] = counts.get(key, 0) + 1


def check_refusals(failures, counts, rules):
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    code, out = sawc2(["--check", "--std-root", "std"] + module_args() + [rel(p) for p in cases])
    got = borrowck_lane.records(out)
    covered = set()
    for path in cases:
        with open(path) as fh:
            lines = fh.read().split("\n")
        header = _HEADER.match(lines[0])
        if header is None:
            failures.append("coro refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        messages = []
        for line in lines[1:]:
            m = _MESSAGE.match(line)
            if not line.startswith("//"):
                break
            if m:
                messages.append(m.group(1))
        rule = header.group(1)
        base = os.path.basename(path)
        if not (base == rule + ".saw" or base.startswith(rule + ".")):
            failures.append("coro refusal %s: the file is not named for %s" % (rel(path), rule))
        if rule not in rules:
            failures.append("coro refusal %s: %s is no rule of coro_rules()" % (rel(path), rule))
        record = got.get(rel(path), "")
        found = errors(record)
        want = (rule, header.group(2))
        if not found or found[0][:2] != want:
            failures.append("coro refusal %s: expected %s at %s first, got %s"
                            % (rel(path), want[0], want[1],
                               "nothing" if not found else "%s at %s" % found[0][:2]))
        else:
            covered.add(rule)
            for text in messages:
                if text not in found[0][2]:
                    failures.append("coro refusal %s: the message does not hold %r: %s"
                                    % (rel(path), text, found[0][2]))
        check_invariants(failures, "refusal", path, record)
        counts["coro refusal fixtures"] = counts.get("coro refusal fixtures", 0) + 1
    for rule in rules:
        if rule not in covered:
            failures.append("coro rule %s: no refusal fixture names it" % rule)
    counts["coro rules"] = len(rules)


def check_agreement(failures, counts):
    """Typecheck's summaries and the frame decisions, over programs other
    lanes hold: a disagreement is an `INVARIANT` line of `sawc2 coro`."""
    cases = []
    for directory in AGREEMENT:
        cases += sorted(glob.glob(os.path.join(directory, "*.saw")))
    code, out = sawc2(["--layouts", "--std-root", "std"] + [rel(p) for p in cases])
    got = borrowck_lane.records(out)
    for path in cases:
        record = got.get(rel(path))
        if record is None:
            failures.append("coro agreement %s: no --layouts record" % rel(path))
            continue
        check_invariants(failures, "agreement", path, record)
    counts["coro agreement programs"] = len(cases)


def run(write=False):
    failures = []
    counts = {}
    rules = coro_rules()
    check_golden(failures, counts, write, rules, "--dump", ".coro")
    check_golden(failures, counts, write, rules, "--layouts", ".layouts")
    check_golden(failures, counts, write, rules, "--lowered", ".lowered")
    check_refusals(failures, counts, rules)
    check_agreement(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    failures, counts = run(write)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("coro lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

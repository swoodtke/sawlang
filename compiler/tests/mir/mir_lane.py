#!/usr/bin/env python3
"""The MIR lane: `sawc2 mir` against its golden dumps and refusal fixtures.

    python compiler/tests/mir/mir_lane.py            # check
    python compiler/tests/mir/mir_lane.py --write    # rewrite the golden dumps
    python compiler/tests/mir/mir_lane.py --fill     # fill `// refuses: TODO` headers

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw`, lowers to exactly the record in
  `golden/NAME.mir`, and each span program, `spans/NAME.saw`, to exactly the
  `--spans` record in `spans/NAME.mir`;
- each refusal fixture, `refuse/NAME.saw`, is refused first by
  `slice.not-yet` at the position its `// refuses:` header names;
- no record of a golden program or a fixture carries an `INVARIANT` line;
- the compiler's own source, the sawc2 build and each unit program, lowers
  with no refusal and no `INVARIANT` line from any verifier.
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
SPANS = os.path.join(HERE, "spans")
REFUSE = os.path.join(HERE, "refuse")
TIMEOUT = 300

_HEADER = re.compile(r"^// refuses: (\S+)(?: at (\d+:\d+))?$")


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "mir"] + args, cwd=REPO, capture_output=True, text=True,
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


def golden_cases():
    return [(src, os.path.splitext(src)[0] + ".mir")
            for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))]


def refusal_cases():
    return sorted(glob.glob(os.path.join(REFUSE, "*.saw")))


def check_golden(failures, counts, write, spans=False):
    if spans:
        cases = [(src, os.path.splitext(src)[0] + ".mir")
                 for src in sorted(glob.glob(os.path.join(SPANS, "*.saw")))]
        code, out = sawc2(["--dump", "--spans"] + [rel(src) for src, _ in cases])
        key = "mir span golden cases"
    else:
        cases = golden_cases()
        code, out = sawc2(["--dump"] + [rel(src) for src, _ in cases])
        key = "mir golden cases"
    got = records(out)
    for src, exp in cases:
        record = got.get(rel(src))
        if record is None:
            failures.append("mir golden %s: no record" % rel(src))
            continue
        if write:
            with open(exp, "w") as fh:
                fh.write(record)
            continue
        if not os.path.exists(exp):
            failures.append("mir golden %s: no expectation %s" % (rel(src), rel(exp)))
            continue
        with open(exp) as fh:
            expected = fh.read()
        if expected != record:
            failures.append("mir golden %s: the record differs at %s"
                            % (rel(src), first_difference(expected, record)))
        for line in record.split("\n"):
            if line.startswith(("ERROR\t", "INVARIANT\t")):
                failures.append("mir golden %s: %s" % (rel(src), line))
        counts[key] = counts.get(key, 0) + 1


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


def check_refusals(failures, counts, fill):
    cases = refusal_cases()
    if not cases:
        return
    code, out = sawc2(["--check"] + [rel(p) for p in cases])
    got = records(out)
    for path in cases:
        record = got.get(rel(path), "")
        found = first_error(record)
        with open(path) as fh:
            m = _HEADER.match(fh.readline().rstrip("\n"))
        if fill and (m is None or m.group(1) == "TODO"):
            write_header(path, found)
            continue
        if m is None:
            failures.append("mir refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule, at = m.group(1), m.group(2)
        if found is None:
            failures.append("mir refusal %s: expected %s, nothing refused" % (rel(path), rule))
        elif found[0] != rule or (at and found[1] != at):
            failures.append("mir refusal %s: expected %s at %s first, refused as %s at %s"
                            % (rel(path), rule, at, found[0], found[1]))
        for line in record.split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("mir refusal %s: %s" % (rel(path), line))
        counts["mir refusal fixtures"] = counts.get("mir refusal fixtures", 0) + 1


def unit_programs():
    return sorted(glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")))


def check_acceptance(failures, counts):
    """The compiler's own source lowers whole: the sawc2 build, then each unit
    program, each the entry of its own program, with no refusal and no
    invariant. A unit program the parser refuses has no tree to lower and is
    counted apart."""
    entries = [rel(build.DRIVER_ENTRY)] + [rel(p) for p in unit_programs()]
    code, out = sawc2(["--check"] + package_args() + entries)
    got = records(out)
    for entry in entries:
        record = got.get(entry)
        if record is None:
            failures.append("mir acceptance %s: no record" % entry)
            continue
        lines = [l for l in record.split("\n") if l.startswith(("ERROR\t", "INVARIANT\t"))]
        if lines and all("\tresolve.parse-refused\t" in l for l in lines) and entry != entries[0]:
            counts["unit programs the parser refuses"] = (
                counts.get("unit programs the parser refuses", 0) + 1)
            continue
        for line in lines:
            failures.append("mir acceptance %s: %s" % (entry, line))
        counts["lowered compiler programs"] = counts.get("lowered compiler programs", 0) + 1
    code, out = sawc2(["--dump"] + package_args() + [entries[0]])
    counts["lowered compiler functions"] = sum(1 for l in out.split("\n") if l.startswith("fn "))


def run(write=False, fill=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    check_golden(failures, counts, write, spans=True)
    check_refusals(failures, counts, fill)
    check_acceptance(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    fill = "--fill" in sys.argv[1:]
    failures, counts = run(write, fill)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("mir lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

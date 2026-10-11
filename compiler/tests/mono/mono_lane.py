#!/usr/bin/env python3
"""The mono lane: `sawc2 mono` against its golden item dumps and layout
tables, its refusal fixtures, and Stage 0's layouts.

    python compiler/tests/mono/mono_lane.py            # check
    python compiler/tests/mono/mono_lane.py --write    # rewrite the golden records

`compiler/tests/run.py` runs `run()`. It checks, as README.md in this
directory specifies:

- each golden program, `golden/NAME.saw`, monomorphized against the new std,
  gives exactly the record in `golden/NAME.mono` (`--dump`) and the layout
  table in `golden/NAME.layouts` (`--layouts`), neither carrying an `ERROR` or
  `INVARIANT` line;
- each fixture in `refuse/` is refused first at its header's position by the
  rule its name starts with, and every rule mono refuses by (`mono_rules` in
  `compiler/mono/src/worklist.saw`) has a fixture;
- each type of a layout table that Stage 0 can spell has Stage 0's size and
  alignment there, read off a probe program Stage 0 builds and runs, unless
  `layout_exceptions.tsv` gives the reason the two differ.
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
EXCEPTIONS = os.path.join(HERE, "layout_exceptions.tsv")
RULES_SOURCE = os.path.join(COMPILER, "mono", "src", "worklist.saw")
PROBES = os.path.join(REPO, ".build", "mono-lane")
TIMEOUT = 600

_HEADER = re.compile(r"^// refuses: (\S+) at (\d+:\d+)$")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
_LAYOUT = re.compile(r"^(.*): size (\d+) align (\d+) ")
_MODULE_PATH = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+(?=[A-Z])")
_MAIN = re.compile(r"^func main\(\)", re.M)


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "mono"] + args, cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout


def check_golden(failures, counts, write):
    cases = sorted(glob.glob(os.path.join(GOLDEN, "*.saw")))
    for mode, suffix in (("--dump", ".mono"), ("--layouts", ".layouts")):
        code, out = sawc2([mode, "--std-root", "std"] + [rel(s) for s in cases])
        got = borrowck_lane.records(out)
        for src in cases:
            exp = os.path.splitext(src)[0] + suffix
            record = got.get(rel(src))
            if record is None:
                failures.append("mono golden %s: no %s record" % (rel(src), mode))
                continue
            if write:
                with open(exp, "w") as fh:
                    fh.write(record)
                continue
            if not os.path.exists(exp):
                failures.append("mono golden %s: no expectation %s" % (rel(src), rel(exp)))
                continue
            with open(exp) as fh:
                expected = fh.read()
            if expected != record:
                failures.append("mono golden %s: the %s record differs at %s"
                                % (rel(src), mode, borrowck_lane.first_difference(expected, record)))
            for line in record.split("\n"):
                if line.startswith(("ERROR\t", "INVARIANT\t")):
                    failures.append("mono golden %s: %s" % (rel(src), line))
            counts["mono golden records"] = counts.get("mono golden records", 0) + 1


def mono_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func mono_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def check_refusals(failures, counts):
    cases = sorted(glob.glob(os.path.join(REFUSE, "*.saw")))
    code, out = sawc2(["--check", "--std-root", "std"] + [rel(p) for p in cases])
    got = borrowck_lane.records(out)
    rules = mono_rules()
    covered = set()
    for path in cases:
        with open(path) as fh:
            header = _HEADER.match(fh.readline().rstrip("\n"))
        if header is None:
            failures.append("mono refusal %s: no `// refuses: RULE at L:C` header" % rel(path))
            continue
        rule = header.group(1)
        base = os.path.basename(path)
        if not (base == rule + ".saw" or base.startswith(rule + ".")):
            failures.append("mono refusal %s: the file is not named for %s" % (rel(path), rule))
        if rule not in rules:
            failures.append("mono refusal %s: %s is no rule of mono_rules()" % (rel(path), rule))
        found = borrowck_lane.first_error(got.get(rel(path), ""))
        want = (rule, header.group(2))
        if found != want:
            failures.append("mono refusal %s: expected %s at %s first, got %s"
                            % (rel(path), want[0], want[1], "nothing" if found is None else "%s at %s" % found))
        else:
            covered.add(rule)
        for line in got.get(rel(path), "").split("\n"):
            if line.startswith("INVARIANT\t"):
                failures.append("mono refusal %s: %s" % (rel(path), line))
        counts["mono refusal fixtures"] = counts.get("mono refusal fixtures", 0) + 1
    for rule in rules:
        if rule not in covered:
            failures.append("mono rule %s: no refusal fixture names it" % rule)
    counts["mono rules"] = len(rules)


def read_exceptions():
    out = {}
    if not os.path.exists(EXCEPTIONS):
        return out
    with open(EXCEPTIONS) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            spelled, reason = line.split("\t", 1)
            out[spelled] = reason
    return out


def stage0_spelling(text):
    """The source spelling Stage 0 reads `text` (a sawc2 type) as, or None
    for a type no probe can name: a reference, a function type, and the two
    zero-sized ones (Stage 0's `alignof<Void>()` is an internal error)."""
    if "&" in text or "->" in text or text in ("Never", "Void"):
        return None
    return _MODULE_PATH.sub("", text)


def check_layouts(failures, counts):
    """Each golden program's layout table against Stage 0's `sizeof` and
    `alignof` of the same types, built into the program itself."""
    os.makedirs(PROBES, exist_ok=True)
    exceptions = read_exceptions()
    used = set()
    for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw"))):
        table = os.path.splitext(src)[0] + ".layouts"
        if not os.path.exists(table):
            continue
        rows = []
        with open(table) as fh:
            for line in fh:
                m = _LAYOUT.match(line.rstrip("\n"))
                if m:
                    spelled = stage0_spelling(m.group(1))
                    if spelled is not None:
                        rows.append((spelled, int(m.group(2)), int(m.group(3))))
        if not rows:
            continue
        with open(src) as fh:
            program = fh.read()
        probe = _MAIN.sub("func mono_probe_original()", program, count=1)
        probe += "\nfunc main() {\n"
        for spelled, _, _ in rows:
            probe += '    print("%s\\t{}\\t{}", sizeof<%s>(), alignof<%s>())\n' % (spelled, spelled, spelled)
        probe += "}\n"
        name = os.path.splitext(os.path.basename(src))[0]
        probe_src = os.path.join(PROBES, name + ".saw")
        probe_bin = os.path.join(PROBES, name)
        with open(probe_src, "w") as fh:
            fh.write(probe)
        r = subprocess.run([sys.executable, build.FROZEN_SAWC, probe_src, "-o", probe_bin], cwd=REPO,
                           capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            failures.append("mono layout %s: Stage 0 does not build the probe: %s"
                            % (rel(src), (r.stdout + r.stderr).strip()[-300:]))
            continue
        run = subprocess.run([probe_bin], capture_output=True, text=True, timeout=60)
        stage0 = {}
        for line in run.stdout.split("\n"):
            parts = line.split("\t")
            if len(parts) == 3:
                stage0[parts[0]] = (int(parts[1]), int(parts[2]))
        for spelled, size, align in rows:
            theirs = stage0.get(spelled)
            if theirs is None:
                failures.append("mono layout %s: Stage 0 printed no layout for %s" % (rel(src), spelled))
                continue
            if theirs != (size, align):
                if spelled in exceptions:
                    used.add(spelled)
                    continue
                failures.append("mono layout %s: %s is size %d align %d here, size %d align %d under Stage 0"
                                % (rel(src), spelled, size, align, theirs[0], theirs[1]))
            counts["layouts matching Stage 0"] = counts.get("layouts matching Stage 0", 0) + 1
    for spelled in sorted(exceptions):
        if spelled not in used:
            failures.append("mono layout %s: the exception for %s is stale" % (rel(EXCEPTIONS), spelled))


def run(write=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    check_refusals(failures, counts)
    check_layouts(failures, counts)
    return failures, counts


def main():
    write = "--write" in sys.argv[1:]
    failures, counts = run(write)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("mono lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

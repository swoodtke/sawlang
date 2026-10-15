#!/usr/bin/env python3
"""The mono lane: `sawc2 mono` against its golden item dumps and layout
tables, its refusal fixtures, and Stage 0's layouts.

    python compiler/tests/mono/mono_lane.py            # check
    python compiler/tests/mono/mono_lane.py --write    # rewrite the golden records
    python compiler/tests/mono/mono_lane.py --stage0   # record Stage 0's layout probes

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
  alignment there, read off Stage 0's recorded run of a probe program
  (`stage0/HOST/NAME.stage0`, which `--stage0` writes through the v0
  compiler and which is stale once the probe changes), unless
  `layout_exceptions.tsv` gives the reason the two differ;
- each subcommand `--lowerings` counts for lowers each program's source to
  MIR as often as it owes: once from `mir` on, never before.
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
sys.path.insert(0, TESTS)

import build  # noqa: E402
import borrowck_lane  # noqa: E402
import oracle  # noqa: E402

# Stage 0's recorded runs of the layout probes, one directory per host
# triple (README.md, "The lane").
STAGE0 = os.path.join(HERE, "stage0")
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
# The subcommands `--lowerings` counts for, each with the count it owes.
LOWERING_COMMANDS = (("resolve", 0), ("typecheck", 0), ("mir", 1), ("eval", 1), ("borrowck", 1),
                     ("drops", 1), ("mono", 1))
# Besides the golden programs: statics whose evaluated values mono reads, a
# layout assertion the evaluator defers, a program mono refuses, and one
# refused before mono, whose constants are never evaluated there.
LOWERING_PROGRAMS = [os.path.join(TESTS, "run", "statics.saw"), os.path.join(TESTS, "run", "layout_asserts.saw"),
                     os.path.join(REFUSE, "mono.depth.saw"),
                     os.path.join(TESTS, "eval", "refuse", "eval.overflow.saw")]


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


def layout_probe(src):
    """(the rows of `src`'s layout table Stage 0 can spell, as (spelling,
    size, align); the probe program printing Stage 0's `sizeof` and `alignof`
    of each, built into the program itself), or None when no row is
    spelled."""
    table = os.path.splitext(src)[0] + ".layouts"
    if not os.path.exists(table):
        return None
    rows = []
    with open(table) as fh:
        for line in fh:
            m = _LAYOUT.match(line.rstrip("\n"))
            if m:
                spelled = stage0_spelling(m.group(1))
                if spelled is not None:
                    rows.append((spelled, int(m.group(2)), int(m.group(3))))
    if not rows:
        return None
    with open(src) as fh:
        program = fh.read()
    probe = _MAIN.sub("func mono_probe_original()", program, count=1)
    probe += "\nfunc main() {\n"
    for spelled, _, _ in rows:
        probe += '    print("%s\\t{}\\t{}", sizeof<%s>(), alignof<%s>())\n' % (spelled, spelled, spelled)
    probe += "}\n"
    return rows, probe


def probes():
    """{golden program name: (its source, rows, probe text)} for every golden
    program with a layout probe."""
    out = {}
    for src in sorted(glob.glob(os.path.join(GOLDEN, "*.saw"))):
        found = layout_probe(src)
        if found is not None:
            out[os.path.splitext(os.path.basename(src))[0]] = (src, found[0], found[1])
    return out


def stage0_command(names=()):
    return "python compiler/tests/mono/mono_lane.py --stage0" + "".join(" " + n for n in names)


def record_stage0():
    """Stage 0 builds and runs each layout probe, and its record replaces the
    one in `STAGE0`; a record naming no probe is removed. The lane's only run
    of Stage 0, through the v0 compiler (`oracle.v0_compiler`)."""
    os.makedirs(PROBES, exist_ok=True)
    triple = build.host_triple()
    found = probes()
    for name, (src, _, probe) in sorted(found.items()):
        probe_src = os.path.join(PROBES, name + ".saw")
        with open(probe_src, "w") as fh:
            fh.write(probe)
        rec = oracle.record_run(probe_src, oracle.record_file(STAGE0, triple, name), rel(src),
                                data=probe.encode("utf-8"))
        print("mono lane stage0 %s %s: build %s" % (triple, name, rec.build))
    for path in oracle.stale_records(os.path.join(STAGE0, triple), set(found)):
        os.remove(path)
        print("mono lane stage0: removed %s" % rel(path))
    return 0


def check_layouts(failures, counts):
    """Each golden program's layout table against Stage 0's `sizeof` and
    `alignof` of the same types, built into the program itself, as Stage 0's
    recorded run of that probe printed them."""
    exceptions = read_exceptions()
    used = set()
    found = probes()
    for path in oracle.stale_records(STAGE0, set(found)):
        failures.append("mono layout %s: a Stage 0 record of no probe; `%s` removes it"
                        % (rel(path), stage0_command()))
    for name, (src, rows, probe) in sorted(found.items()):
        rec, why = oracle.load_run(STAGE0, name, probe.encode("utf-8"), stage0_command())
        if rec is None:
            failures.append("mono layout %s: %s" % (rel(src), why))
            continue
        if rec.build != "ok":
            failures.append("mono layout %s: Stage 0 does not build the probe: %s"
                            % (rel(src), rec.build_error or rec.build))
            continue
        if rec.stdout == "varies":
            failures.append("mono layout %s: Stage 0's probe printed differently on two runs" % rel(src))
            continue
        stage0 = {}
        for line in rec.stdout.split("\n"):
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


def check_lowerings(failures, counts):
    """Each driver subcommand that reads a program lowers its source to MIR
    the number of times `LOWERINGS` says: once from `mir` on, so the
    evaluator and the stages after it read one lowering, and never before."""
    cases = sorted(glob.glob(os.path.join(GOLDEN, "*.saw"))) + LOWERING_PROGRAMS
    for command, want in LOWERING_COMMANDS:
        r = subprocess.run([build.SAWC2, command, "--check", "--lowerings", "--std-root", "std"]
                           + [rel(p) for p in cases], cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
        got = borrowck_lane.records(r.stdout)
        for path in cases:
            record = got.get(rel(path))
            if record is None:
                failures.append("mono lowerings %s %s: no record" % (command, rel(path)))
                continue
            seen = [line for line in record.split("\n") if line.startswith("LOWERINGS\t")]
            if seen != ["LOWERINGS\t%d" % want]:
                failures.append("mono lowerings %s %s: expected one `LOWERINGS\t%d` line, got %s"
                                % (command, rel(path), want, seen or "none"))
            counts["lowering counts"] = counts.get("lowering counts", 0) + 1


def run(write=False):
    failures = []
    counts = {}
    check_golden(failures, counts, write)
    check_refusals(failures, counts)
    check_layouts(failures, counts)
    check_lowerings(failures, counts)
    return failures, counts


def main():
    if "--stage0" in sys.argv[1:]:
        return record_stage0()
    write = "--write" in sys.argv[1:]
    failures, counts = run(write)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("mono lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

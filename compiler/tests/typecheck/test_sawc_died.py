#!/usr/bin/env python3
"""The lanes' report of a `sawc` that died, against a stand-in compiler.

    python compiler/tests/typecheck/test_sawc_died.py

`compiler/tests/run.py` runs `run()` with the typecheck lane. The stand-in
prints two `FILE` records, writes two lines to standard error and exits with
the status its first argument after the subcommand names; `build.run_sawc`
and the typecheck lane's phases are held to:

- exit 0 and exit 1 are normal: the records come back, nothing is raised;
- any other status is one `SawcDied`, naming the status, the last record
  printed and the last line of standard error;
- a lane phase whose compiler dies is one failure line, however many fixtures
  the call held, and the fixtures with no record are not reported one by one;
- the mono lane's lowerings check is one line per subcommand, and
  `sawc_reading.parse_files` raises the same `SawcDied`.

It also holds the typecheck lane's header rule: a leading comment line that
begins like a header and does not parse as one is a failure, a misplaced or
repeated `// errors:` is a failure, and the right forms draw none.
"""
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mono"))

import build  # noqa: E402
import mono_lane  # noqa: E402
import sawc_reading  # noqa: E402
import typecheck_lane  # noqa: E402

STUB = """#!%s
import sys

status = int(__import__("os").environ["STUB_STATUS"])
files = [a for a in sys.argv[2:] if a.endswith(".saw")]
for path in files[:2]:
    print("FILE\\t" + path)
    print("ERROR\\tstub.rule\\t%%s:1:1\\tmessage" %% path)
sys.stderr.write("first line of standard error\\n")
sys.stderr.write("panic: the stand-in died\\n")
sys.exit(status)
"""


def with_stub(status, check):
    """`check()` with `build.SAWC` the stand-in that exits `status`."""
    with tempfile.TemporaryDirectory() as scratch:
        path = os.path.join(scratch, "sawc-stub")
        with open(path, "w") as fh:
            fh.write(STUB % sys.executable)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        saved = build.SAWC
        saved_status = os.environ.get("STUB_STATUS")
        build.SAWC = path
        os.environ["STUB_STATUS"] = str(status)
        try:
            return check()
        finally:
            build.SAWC = saved
            if saved_status is None:
                os.environ.pop("STUB_STATUS", None)
            else:
                os.environ["STUB_STATUS"] = saved_status


def run():
    failures = []
    counts = {}
    names = ["a.saw", "b.saw", "c.saw"]

    for status in (0, 1):
        try:
            r = with_stub(status, lambda: build.run_sawc([build.SAWC, "typecheck"] + names))
            if r.returncode != status or r.stdout.count("FILE\t") != 2:
                failures.append("sawc died: exit %d came back as %r" % (status, r.returncode))
        except build.SawcDied as died:
            failures.append("sawc died: exit %d is a normal status, raised %s" % (status, died))
    for status in (134, 2, 250):
        want = ("`sawc typecheck` died (exit %d) after b.saw: panic: the stand-in died" % status)
        try:
            with_stub(status, lambda: build.run_sawc([build.SAWC, "typecheck"] + names))
            failures.append("sawc died: exit %d raised nothing" % status)
        except build.SawcDied as died:
            if str(died) != want:
                failures.append("sawc died: exit %d said %r, expected %r" % (status, str(died), want))

    # The lane's phases: one failure per died call.
    cases = [os.path.join(typecheck_lane.REFUSE, name) for name in
             sorted(n for n in os.listdir(typecheck_lane.REFUSE) if n.endswith(".saw"))
             if typecheck_lane.refusal_flags(os.path.join(typecheck_lane.REFUSE, name)) == ()][:5]
    saved_cases = typecheck_lane.refusal_cases
    typecheck_lane.refusal_cases = lambda: cases
    try:
        found = []
        with_stub(134, lambda: typecheck_lane.check_refusals(found, {}, False))
    finally:
        typecheck_lane.refusal_cases = saved_cases
    expected = "typecheck refusal: `sawc typecheck` died (exit 134) after %s: panic: the stand-in died" % (
        typecheck_lane.rel(cases[1]))
    if found != [expected]:
        failures.append("typecheck refusals over a dead compiler: %r, expected exactly %r" % (found, [expected]))

    golden = []
    with_stub(134, lambda: typecheck_lane.check_golden(golden, {}, False))
    if not golden or any("died (exit 134)" not in f for f in golden) or any("no record" in f for f in golden):
        failures.append("typecheck golden over a dead compiler: %r" % golden[:2])

    # The mono lane's lowerings check: one line per subcommand.
    lowerings = []
    with_stub(134, lambda: mono_lane.check_lowerings(lowerings, {}))
    wanted = ["mono lowerings %s: `sawc %s` died (exit 134) after " % (c, c) for c, _ in mono_lane.LOWERING_COMMANDS]
    if len(lowerings) != len(wanted) or not all(f.startswith(w) and f.endswith("panic: the stand-in died")
                                               for f, w in zip(lowerings, wanted)):
        failures.append("mono lowerings over a dead compiler: %r" % lowerings[:2])
    # The shared batch reader: the same sentence, raised for the caller.
    reading = [os.path.join(typecheck_lane.REPO, name) for name in names]
    want = "`sawc parse` died (exit 134) after b.saw: panic: the stand-in died"
    try:
        with_stub(134, lambda: sawc_reading.parse_files(reading))
        failures.append("sawc_reading.parse_files over a dead compiler raised nothing")
    except build.SawcDied as died:
        if str(died) != want:
            failures.append("sawc_reading.parse_files said %r, expected %r" % (str(died), want))

    counts["dead-compiler cases"] = 9
    failures.extend(header_cases(counts))
    return failures, counts


MESSAGE = "the raw value of `Code.C` depends on itself"
# (label, header lines, the sentence each failure must hold or None for no failure)
HEADER_CASES = [
    ("message without its space", ["// message:" + MESSAGE], "cannot read"),
    ("message with its space", ["// message: " + MESSAGE], None),
    ("a wrong message without its space", ["// message:no such text"], "cannot read"),
    ("a wrong message with its space", ["// message: no such text"], None),
    ("errors: 2", ["// errors: 2"], None),
    ("errors: 4", ["// errors: 4"], None),
    ("errors after the message", ["// message: " + MESSAGE, "// errors: 2"], "goes before the first `// message:`"),
    ("errors misspelt", ["// errors:2"], "cannot read"),
    ("error, singular", ["// error: 2"], "cannot read"),
    ("errors stated twice", ["// errors: 2", "// errors: 3"], "stated twice"),
    ("messages, plural", ["// messages: " + MESSAGE], "cannot read"),
    ("spacing after the slashes", ["//message: " + MESSAGE], "cannot read"),
    ("a flags line without its space", ["// flags:--runtime"], "cannot read"),
    ("a warns line without a count", ["// warns: many"], "cannot read"),
    ("prose that starts like a header", ["// error type, so the refusal"], "cannot read"),
    ("a word that only starts the same", ["// messaging layer", "// errorless"], None),
    ("a header after the leading comment", ["", "// message:late"], None),
]


def header_cases(counts):
    """Each leading-comment line the lane cannot read draws its failure, and
    the right forms draw none."""
    failures = []
    with tempfile.TemporaryDirectory() as scratch:
        for k, (label, lines, want) in enumerate(HEADER_CASES):
            path = os.path.join(scratch, "case%d.saw" % k)
            with open(path, "w") as fh:
                fh.write("// refuses: static.cycle at 9:14\n" + "\n".join(lines) + "\nenum Code: UInt8 {}\n")
            said = [s for _, _, s in typecheck_lane.header_problems(path)]
            if want is None and said:
                failures.append("header case %r: expected no failure, got %r" % (label, said))
            elif want is not None and not any(want in s for s in said):
                failures.append("header case %r: expected a failure holding %r, got %r" % (label, want, said))
    counts["header cases"] = len(HEADER_CASES)
    return failures


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    print("sawc died: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                 ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

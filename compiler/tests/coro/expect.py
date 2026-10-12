#!/usr/bin/env python3
"""A corpus program's run directives, read and judged as `test_runner.py`
reads and judges them, so a lane over tests/corpus/ needs neither it nor
Stage 0.

Only the directives a run is judged by are read: `EXPECT:`, `EXPECT-OUTPUT:`
with its continuation lines, `EXPECT-OUTPUT-CONTAINS:`, `EXPECT-PANIC-CONTAINS:`,
`EXPECT-EXIT:`, `EXPECT-ERROR-CONTAINS:` and `COMPILE-FLAGS:`. The header ends
at the first line that is neither blank nor a comment.
"""
import os


class Directives:
    def __init__(self):
        self.expect = None
        self.output = []
        self.output_contains = []
        self.panic_contains = []
        self.error_contains = []
        self.exit = None
        self.flags = []


def read(path):
    """The directives of the program at `path`; `{TESTDIR}` in its flags
    expands to the directory holding it."""
    d = Directives()
    in_output = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line and not line.strip().startswith("//"):
                break
            # The order matters: each directive's spelling is tested before
            # any spelling it is a prefix of, and `EXPECT-OUTPUT:` before the
            # continuation rule that would take it as output.
            if "// EXPECT:" in line:
                d.expect = line.split("// EXPECT:")[1].strip()
                in_output = False
            elif "// EXPECT-EXIT:" in line:
                d.exit = int(line.split("// EXPECT-EXIT:")[1].strip())
                in_output = False
            elif "// EXPECT-OUTPUT-CONTAINS:" in line:
                text = line.split("// EXPECT-OUTPUT-CONTAINS:")[1].rstrip()
                if text.startswith(" "):
                    text = text[1:]
                if text:
                    d.output_contains.append(text)
                in_output = False
            elif "// EXPECT-OUTPUT:" in line:
                in_output = True
                rest = line.split("// EXPECT-OUTPUT:")[1].strip()
                if rest:
                    d.output.append(rest)
            elif "// EXPECT-PANIC-CONTAINS:" in line:
                d.panic_contains.append(line.split("// EXPECT-PANIC-CONTAINS:")[1].strip())
                in_output = False
            elif "// EXPECT-ERROR-CONTAINS:" in line:
                d.error_contains.append(line.split("// EXPECT-ERROR-CONTAINS:")[1].strip())
                in_output = False
            elif "// COMPILE-FLAGS:" in line:
                raw = line.split("// COMPILE-FLAGS:")[1].strip()
                d.flags = raw.replace("{TESTDIR}", os.path.dirname(path)).split()
                in_output = False
            elif _ends_output(line):
                in_output = False
            elif in_output:
                if line.strip().startswith("//"):
                    text = line.strip()[2:].strip()
                    if text or d.output:
                        d.output.append(text)
                elif line.strip() == "":
                    in_output = False
    return d


# Every other directive test_runner.py reads closes an `EXPECT-OUTPUT:` block
# without being taken as output.
_OTHER = ("// EXPECT-SYMBOL-UNDEFINED:", "// EXPECT-OBJECT-MAX-BYTES:", "// EXPECT-IR-CONTAINS:",
          "// EXPECT-IR-ABSENT:", "// EXPECT-ERROR-ABSENT:", "// EXPECT-WARNING-CONTAINS:",
          "// EXPECT-NO-WARNINGS", "// XFAIL-IF:", "// XFAIL:")


def _ends_output(line):
    return any(marker in line for marker in _OTHER)


def judge(d, code, stdout, stderr):
    """None when a run that exited with `code` (negative for a signal, None
    for a timeout) and printed `stdout` and `stderr` is what `d` expects,
    else the first way it is not."""
    if code is None:
        return "timed out"
    if d.expect == "panic":
        if code == 0:
            return "expected a panic, exited 0"
        for want in d.panic_contains:
            if want not in stdout + stderr:
                return "the panic does not contain %r" % want
        return None
    if d.exit is not None:
        if code != d.exit:
            return "exit %d, expected %d" % (code, d.exit)
    elif code != 0:
        return "exit %d" % code
    cursor = 0
    for want in d.output_contains:
        found = stdout.find(want, cursor)
        if found < 0:
            return "the output does not contain %r%s" % (want, " in order" if want in stdout else "")
        cursor = found + len(want)
    if d.output and stdout.strip().split("\n") != d.output:
        got = stdout.strip().split("\n")
        k = next(i for i in range(max(len(got), len(d.output)))
                 if (got[i] if i < len(got) else None) != (d.output[i] if i < len(d.output) else None))
        return "output line %d is %r, expected %r" % (k + 1, got[k] if k < len(got) else "<end>",
                                                      d.output[k] if k < len(d.output) else "<end>")
    return None

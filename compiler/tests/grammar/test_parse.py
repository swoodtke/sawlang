#!/usr/bin/env python3
"""The parser corpus's own checks: the dumps, the generated cases, coverage.

    python compiler/tests/grammar/test_parse.py

Each `compiler/tests/parse/dump/NAME.saw` must dump, by dump.py, to exactly its
NAME.dump, and each text in REFUSED must have no dump, for the reason given. A
leaf must escape every character str.splitlines ends a line at. The productions whose punctuation is a leaf (`Grammar.flagged`) must
be the ones compiler/tests/parse/README.md lists, so a grammar change that adds
one updates the specification too. Regenerating the corpus must reproduce
`generated/`, and the `parsecoverage` check must hold (generate.check).
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dump  # noqa: E402
import extract  # noqa: E402
import generate  # noqa: E402
import recognize  # noqa: E402

PARSE_DIR = os.path.join(extract.REPO, "compiler", "tests", "parse")
DUMP_PINS = os.path.join(PARSE_DIR, "dump")
README = os.path.join(PARSE_DIR, "README.md")
# The README's table of productions whose punctuation is a leaf: its header, and
# a row.
FLAGGED_HEADER = "| production | what it shows |"
FLAGGED_ROW = re.compile(r"^\| (`[a-z-]+`(?:, `[a-z-]+`)*) \|")
# Texts that have no dump, and the failure source_dump gives: the recognizer's
# lexical refusals, decided outside the chart, refuse a dump as they refuse the
# text.
REFUSED = [
    ("func f() {\n    /// d\n    let b = 1\n}\n",
     "FAIL: 2:5 refused by syntax.lex.doc-attach"),
    ('extern "C" {\n    /// d\n    func g()\n}\n',
     "FAIL: 2:5 refused by syntax.lex.doc-attach"),
    ("trait T {\n    /// d\n    type A\n}\n",
     "FAIL: 2:5 refused by syntax.lex.doc-attach"),
    ("extension S: T {\n    /// d\n    type A = Int\n}\n",
     "FAIL: 2:5 refused by syntax.lex.doc-attach"),
    ("@export\n/// d\npublic func f() {\n}\n",
     "FAIL: 2:1 refused by syntax.lex.doc-attach"),
    ("func f() {\n}\n//! late\n",
     "LEXERR: 3:1 refused by syntax.lex.module-doc"),
    ('func f() {\n    let s = "{é}"\n}\n',
     "SEGLEX: 2:14 Lexer error at 1:1: Unexpected character"),
]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _first_difference(want, got):
    for n in range(max(len(want), len(got))):
        a = want[n] if n < len(want) else "<end>"
        b = got[n] if n < len(got) else "<end>"
        if a != b:
            return "line %d: expected %r, got %r" % (n + 1, a[:100], b[:100])
    return "a trailing newline"


def check_dump_pins(failures, g):
    sources = sorted(glob.glob(os.path.join(DUMP_PINS, "*.saw")))
    for path in sources:
        rel = os.path.relpath(path, extract.REPO)
        stem = os.path.splitext(path)[0]
        if not os.path.exists(stem + ".dump"):
            failures.append("dump pin %s: no .dump expectation" % rel)
            continue
        try:
            got = dump.source_dump(g, path=path)
        except dump.Failure as e:
            failures.append("dump pin %s: no dump: %s" % (rel, e))
            continue
        want = _read(stem + ".dump").split("\n")[:-1]
        if got != want:
            failures.append("dump pin %s: %s" % (rel, _first_difference(want, got)))
    for path in sorted(glob.glob(os.path.join(DUMP_PINS, "*.dump"))):
        if not os.path.exists(os.path.splitext(path)[0] + ".saw"):
            failures.append("dump pin %s: no input beside it"
                            % os.path.relpath(path, extract.REPO))
    return len(sources)


def check_refusals(failures, g):
    for text, want in REFUSED:
        try:
            dump.source_dump(g, text)
        except dump.Failure as e:
            if str(e) != want:
                failures.append("dump refusal %r: expected %r, got %r" % (text, want, str(e)))
            continue
        failures.append("dump refusal %r: dumped, but expected %r" % (text, want))
    return len(REFUSED)


def check_escapes(failures):
    """Every character str.splitlines ends a line at is one a leaf escapes, so
    a dump line is one line of the dump."""
    breaking = [chr(c) for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF
                and len(("a" + chr(c) + "b").splitlines()) != 1]
    for ch in breaking:
        if ch not in dump.LINE_BREAKING or len(dump.escape_leaf("a" + ch + "b").splitlines()) != 1:
            failures.append("dump: a leaf holding U+%04X breaks its line" % ord(ch))
    return len(breaking)


def check_flagged(failures, g):
    listed = set()
    lines = [line.strip() for line in _read(README).split("\n")]
    start = lines.index(FLAGGED_HEADER) if FLAGGED_HEADER in lines else len(lines)
    for line in lines[start + 2:]:
        m = FLAGGED_ROW.match(line)
        if not m:
            break
        listed.update(name.strip("` ") for name in m.group(1).split(","))
    if listed != g.flagged:
        failures.append("parse README: the productions whose punctuation is a leaf are %s, "
                        "but the README lists %s"
                        % (", ".join(sorted(g.flagged)), ", ".join(sorted(listed))))
    return len(g.flagged)


def run():
    """(failure lines, counts) for run.py."""
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    failures = []
    g = recognize.Grammar(extract.extract())
    counts = {"dump pins": check_dump_pins(failures, g),
              "dump refusals": check_refusals(failures, g),
              "line-breaking characters": check_escapes(failures),
              "punctuation-leaf productions": check_flagged(failures, g)}
    generated, covered = generate.check()
    failures += generated
    counts.update(covered)
    return failures, counts


def main():
    failures, counts = run()
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("parse corpus tests: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                          summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

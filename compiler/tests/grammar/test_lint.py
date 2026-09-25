#!/usr/bin/env python3
"""The lint's own tests: GRAMMAR.md lints clean, and every check is seen failing.

    python compiler/tests/grammar/test_lint.py

Each `fixtures/lint/CHECK[.VARIANT].fix` injects one defect into a copy of
`fixtures/mini_grammar.md` and names the (line, check) findings the lint must
report: exactly those, no more. The mini grammar itself is the uninjected
control and must lint clean. Every check needs a fixture, and on GRAMMAR.md
every check must examine something (lint.idle_checks).

A fixture holds `Why:` and `Expect: LINE CHECK` lines, then edits, each a
`--- replace` block, a `--- with` block and `--- end`; the replaced text must
occur exactly once. `␠` in a `with` block stands for a space, since the patch
server strips trailing whitespace from committed files.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import extract  # noqa: E402
import lint  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
MINI = os.path.join(FIXTURES, "mini_grammar.md")
MINI_SPEC = os.path.join(FIXTURES, "mini_spec.md")
LINT_FIXTURES = os.path.join(FIXTURES, "lint")


class Fixture:
    def __init__(self, path):
        self.path = path
        self.rel = os.path.relpath(path, extract.REPO)
        self.check = os.path.basename(path).split(".")[0]
        self.why = ""
        self.expect = set()
        self.edits = []
        self.errors = []
        self._read()

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        mode = None
        old, new = [], []
        for n, line in enumerate(lines, 1):
            if mode is None:
                if line.startswith("Why: "):
                    self.why = line[5:]
                elif line.startswith("Expect: "):
                    parts = line[8:].split()
                    if len(parts) != 2 or not parts[0].isdigit():
                        self.errors.append("line %d: want `Expect: LINE CHECK`" % n)
                    else:
                        self.expect.add((int(parts[0]), parts[1]))
                elif line == "--- replace":
                    mode, old, new = "old", [], []
                elif line.strip():
                    self.errors.append("line %d: unexpected %r" % (n, line))
            elif line == "--- with" and mode == "old":
                mode = "new"
            elif line == "--- end" and mode == "new":
                self.edits.append(("\n".join(old), "\n".join(new).replace("␠", " ")))
                mode = None
            elif mode == "old":
                old.append(line)
            else:
                new.append(line)
        if mode is not None:
            self.errors.append("an edit is not closed with `--- end`")
        if not self.why or not self.expect or not self.edits:
            self.errors.append("a fixture needs a Why:, an Expect: and an edit")

    def apply(self, text):
        for old, new in self.edits:
            count = text.count(old)
            if count != 1:
                raise ValueError("the replaced text occurs %d times in the mini grammar: %r"
                                 % (count, old[:60]))
            text = text.replace(old, new)
        return text


def findings(text, headings):
    problems, examined = lint.lint(extract.extract_text(text, MINI), headings)
    return {(p.line, p.check) for p in problems}, problems


def run():
    """(failure lines, counts) for run.py."""
    failures = []
    counts = {}
    headings = extract.spec_headings(MINI_SPEC)
    with open(MINI, encoding="utf-8") as fh:
        mini = fh.read()
    got, problems = findings(mini, headings)
    for p in problems:
        failures.append("grammar lint control: the mini grammar is not clean: %s"
                        % p.render(os.path.relpath(MINI, extract.REPO)))

    fixtures = [Fixture(p) for p in sorted(glob.glob(os.path.join(LINT_FIXTURES, "*.fix")))]
    covered = set()
    for fx in fixtures:
        if fx.check not in lint.CHECKS:
            failures.append("grammar lint fixture %s: no check is named %s" % (fx.rel, fx.check))
            continue
        covered.add(fx.check)
        if fx.errors:
            failures.extend("grammar lint fixture %s: %s" % (fx.rel, e) for e in fx.errors)
            continue
        if not any(check == fx.check for _, check in fx.expect):
            failures.append("grammar lint fixture %s: expects no %s finding" % (fx.rel, fx.check))
        try:
            text = fx.apply(mini)
        except ValueError as exc:
            failures.append("grammar lint fixture %s: %s" % (fx.rel, exc))
            continue
        got, _ = findings(text, headings)
        for line, check in sorted(fx.expect - got):
            failures.append("grammar lint fixture %s: expected %s at line %d, not reported"
                            % (fx.rel, check, line))
        for line, check in sorted(got - fx.expect):
            failures.append("grammar lint fixture %s: unexpected %s at line %d"
                            % (fx.rel, check, line))
    for check in lint.CHECKS:
        if check not in covered:
            failures.append("grammar lint: check %s has no fixture" % check)
    counts["grammar lint fixtures"] = len(fixtures)

    model = extract.extract()
    problems, examined = lint.lint(model, extract.spec_headings(lint.SPEC))
    for p in problems:
        failures.append("grammar lint: " + p.render("GRAMMAR.md"))
    for check in lint.idle_checks(examined):
        failures.append("grammar lint: check %s examined nothing in GRAMMAR.md" % check)
    counts["grammar lint checks"] = len(lint.CHECKS)
    return failures, counts


def main():
    failures, counts = run()
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("grammar lint tests: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                          summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The self-hosted compiler's tests, until it can run its own `@test` sidecars.

    python compiler/tests/run.py

Builds `sawc2` and the unit programs with the frozen compiler and runs the unit
programs; compares `sawc2 lex` with the golden fixtures in `lex/`, whose token
kinds and lex errors must cover the lexer's; runs the subset checker over the
compiler source and its own fixtures in `subset/`; and runs the grammar lint and
the reference recognizer's own tests in `grammar/`. Each failure prints one line
in a fixed order, the summary comes last, and any failure exits 1.
"""
import collections
import concurrent.futures
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, os.path.join(HERE, "grammar"))

import build  # noqa: E402
import subset_check  # noqa: E402
import ast_nodes as A  # noqa: E402  (on sys.path through subset_check)
import test_lint  # noqa: E402
import test_recognize  # noqa: E402

UNIT_OUT = os.path.join(REPO, ".build", "compiler-tests")
LEX_FIXTURES = os.path.join(HERE, "lex")
SUBSET_FIXTURES = os.path.join(HERE, "subset")
GRAMMAR_FIXTURES = os.path.join(HERE, "grammar", "fixtures")
LEXER_SOURCE = os.path.join(COMPILER, "lex", "src", "lib.saw")
RUN_TIMEOUT = 60

_MARKER = re.compile(r"//\s*refuses:\s*(.+)$")

# Stage 1 tolerates leaks only while every std `deinit` the compiler reaches
# frees memory or closes a descriptor, so widening the std cone fails here until
# that is re-checked and the pin updated (SL:hazards, leak tolerance).
PINNED_STD_MODULES = ("env", "file", "path")


class Run:
    def __init__(self):
        self.failures = []
        self.counts = {}

    def fail(self, text):
        self.failures.append(text)

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n


def unit_programs():
    """`compiler/<stage>/tests/*.saw`, as (name, path), sorted."""
    out = []
    for path in glob.glob(os.path.join(COMPILER, "*", "tests", "*.saw")):
        stage = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if stage == "tests":
            continue
        name = "%s/%s" % (stage, os.path.splitext(os.path.basename(path))[0])
        out.append((name, path))
    return sorted(out)


def build_and_run_unit(name, path):
    """(name, failure text or None)."""
    exe = os.path.join(UNIT_OUT, name.replace("/", "_"))
    ok, output = build.build_program(path, exe)
    if not ok:
        return name, "unit %s: does not compile: %s" % (name, _first_line(output))
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return name, "unit %s: timed out" % name
    if r.returncode != 0:
        detail = _first_line(r.stderr) or _first_line(r.stdout)
        return name, "unit %s: exit %d: %s" % (name, r.returncode, detail)
    return name, None


def _first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def run_units(run):
    programs = unit_programs()
    workers = min(8, os.cpu_count() or 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda np: build_and_run_unit(*np), programs))
    for _, failure in sorted(results):
        if failure:
            run.fail(failure)
    run.count("unit programs", len(programs))


def sawc2(*args):
    r = subprocess.run([build.SAWC2] + list(args), capture_output=True, timeout=RUN_TIMEOUT)
    return r.returncode, r.stdout


def check_fixture_whitespace(run):
    """No fixture line ends in whitespace, and no fixture ends in a blank line.
    `git apply --whitespace=fix` (the patch server's setting) and editors strip
    both, which would change a fixture on its way into the tree."""
    paths = [p for d in (LEX_FIXTURES, SUBSET_FIXTURES) for p in glob.glob(os.path.join(d, "*"))]
    paths += glob.glob(os.path.join(GRAMMAR_FIXTURES, "**", "*.*"), recursive=True)
    for path in sorted(paths):
        rel = os.path.relpath(path, REPO)
        with open(path, "rb") as fh:
            data = fh.read()
        for lineno, line in enumerate(data.split(b"\n"), 1):
            if line.endswith((b" ", b"\t", b"\r")):
                run.fail("fixture %s:%d: the line ends in whitespace, which "
                         "`git apply --whitespace=fix` and editors strip" % (rel, lineno))
        if data.endswith(b"\n\n"):
            run.fail("fixture %s: ends in a blank line, which `git apply "
                     "--whitespace=fix` strips" % rel)


def run_golden(run):
    """Every fixture's expectations, then which kinds they cover."""
    sources = sorted(glob.glob(os.path.join(LEX_FIXTURES, "*.saw")))
    expectations = sorted(glob.glob(os.path.join(LEX_FIXTURES, "*.tokens"))
                          + glob.glob(os.path.join(LEX_FIXTURES, "*.docs")))
    stems = {os.path.splitext(p)[0] for p in sources}
    for exp in expectations:
        if os.path.splitext(exp)[0] not in stems:
            run.fail("golden %s: no input beside it" % os.path.relpath(exp, REPO))
    if not sources:
        run.fail("golden: no fixtures in %s" % os.path.relpath(LEX_FIXTURES, REPO))
    kinds_seen = set()
    errors_seen = set()
    for src in sources:
        stem = os.path.splitext(src)[0]
        rel = os.path.relpath(src, REPO)
        if not os.path.exists(stem + ".tokens"):
            run.fail("golden %s: no .tokens expectation" % rel)
            continue
        for suffix, flags in ((".tokens", ()), (".docs", ("--docs",))):
            exp_path = stem + suffix
            if not os.path.exists(exp_path):
                continue
            with open(exp_path, "rb") as fh:
                expected = fh.read()
            code, got = sawc2("lex", *flags, src)
            want_code = 1 if expected.startswith(b"ERROR\t") else 0
            if got != expected:
                run.fail("golden %s%s: output differs at %s"
                         % (rel, " --docs" if flags else "", _first_difference(expected, got)))
            elif code != want_code:
                run.fail("golden %s%s: exit %d, expected %d"
                         % (rel, " --docs" if flags else "", code, want_code))
            run.count("golden expectations")
            if suffix == ".tokens":
                for record in expected.split(b"\n"):
                    fields = record.split(b"\t")
                    if fields[0] == b"ERROR" and len(fields) >= 3:
                        errors_seen.add(fields[2].decode("utf-8"))
                    elif fields[0]:
                        kinds_seen.add(fields[0].decode("ascii"))
        run.count("golden fixtures")
    check_kind_coverage(run, kinds_seen)
    check_error_coverage(run, errors_seen)


def _first_difference(expected, got):
    exp_lines = expected.split(b"\n")
    got_lines = got.split(b"\n")
    for i in range(max(len(exp_lines), len(got_lines))):
        a = exp_lines[i] if i < len(exp_lines) else b"<end>"
        b = got_lines[i] if i < len(got_lines) else b"<end>"
        if a != b:
            return "record %d: expected %r, got %r" % (i + 1, a[:80], b[:80])
    return "a trailing byte"


def lexer_program():
    src = subset_check.SourceFile(LEXER_SOURCE)
    if src.program is None:
        raise RuntimeError("cannot parse %s" % os.path.relpath(LEXER_SOURCE, REPO))
    return src.program


def check_kind_coverage(run, kinds_seen):
    """The kinds come from the lexer: `sawc2 lex --kinds`, whose length must
    match the case count of `TokenKind` as declared."""
    code, out = sawc2("lex", "--kinds")
    kinds = out.decode("ascii").split()
    if code != 0 or not kinds:
        run.fail("coverage: `sawc2 lex --kinds` failed (exit %d)" % code)
        return
    declared = [e for e in lexer_program().enums if e.name == "TokenKind"]
    cases = len(declared[0].variants) if declared else 0
    if len(kinds) != cases or len(set(kinds)) != len(kinds):
        run.fail("coverage: token_kinds() lists %d distinct of %d kinds, but TokenKind "
                 "declares %d cases" % (len(set(kinds)), len(kinds), cases))
    for kind in kinds:
        if kind not in kinds_seen:
            run.fail("coverage: token kind %s appears in no golden fixture" % kind)
    run.count("token kinds", len(kinds))


def check_error_coverage(run, errors_seen):
    """The error kinds come from the lexer's source: the message of every
    `err`/`err_at` it calls."""
    messages = set()
    for n in subset_check.walk(lexer_program()):
        if isinstance(n, A.MethodCall) and n.method_name in ("err", "err_at"):
            first = n.arguments[0].value if n.arguments else None
            if not isinstance(first, A.StringLiteral):
                run.fail("coverage: a lex error at %s:%d has no literal message"
                         % (os.path.relpath(LEXER_SOURCE, REPO), n.line))
                continue
            messages.add(first.value)
    for message in sorted(messages):
        if message not in errors_seen:
            run.fail("coverage: lex error %r appears in no golden fixture" % message)
    run.count("lex error kinds", len(messages))


def run_subset(run):
    files, diags = subset_check.check_tree()
    for d in diags:
        run.fail("subset: " + d.render())
    run.count("checked source files", len(files))
    allowed, pinned = sorted(subset_check.ALLOWED_STD_MODULES), sorted(PINNED_STD_MODULES)
    if allowed != pinned:
        run.fail("subset: ALLOWED_STD_MODULES is %s, pinned as %s; check that every std "
                 "`deinit` it reaches only frees memory or closes a descriptor, then update "
                 "PINNED_STD_MODULES" % (", ".join(allowed), ", ".join(pinned)))
    fixtures = sorted(glob.glob(os.path.join(SUBSET_FIXTURES, "*.saw")))
    names = {_fixture_rule(p) for p in fixtures}
    for rule in sorted(subset_check.RULES):
        if rule not in names:
            run.fail("subset: rule %s has no fixture" % rule)
    for path in fixtures:
        check_subset_fixture(run, path)
        run.count("checker fixtures")


def _fixture_rule(path):
    """`RULE.saw` and `RULE.VARIANT.saw` are fixtures of RULE."""
    return os.path.basename(path).split(".")[0]


def check_subset_fixture(run, path):
    """A fixture's `// refuses: RULE...` markers name exactly the (line, rule)
    pairs the checker must report, a rule named twice on a line meaning two
    findings of it there; a `clean` fixture has none."""
    rel = os.path.relpath(path, REPO)
    rule = _fixture_rule(path)
    if rule != "clean" and rule not in subset_check.RULES:
        run.fail("subset fixture %s: no rule is named %s" % (rel, rule))
        return
    expected = collections.Counter()
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            m = _MARKER.search(line)
            if m:
                for name in m.group(1).replace(",", " ").split():
                    expected[(lineno, name)] += 1
    if rule != "clean" and not any(name == rule for _, name in expected):
        run.fail("subset fixture %s: marks no line with its own rule" % rel)
    got = collections.Counter((d.line, d.rule) for d in subset_check.check_files([path]))
    for line, name in sorted(set(expected) | set(got)):
        want, have = expected[(line, name)], got[(line, name)]
        if not have:
            run.fail("subset fixture %s:%d: expected %s, not reported" % (rel, line, name))
        elif not want:
            run.fail("subset fixture %s:%d: unexpected %s" % (rel, line, name))
        elif want != have:
            run.fail("subset fixture %s:%d: expected %s %d times, reported %d"
                     % (rel, line, name, want, have))


def run_grammar(run):
    """The grammar lint with its fixtures, and the recognizer's unit tests; the
    full-corpus recognizer run is the battery's `grammarcorpus` lane."""
    for module in (test_lint, test_recognize):
        failures, counts = module.run()
        for failure in failures:
            run.fail(failure)
        for key, n in counts.items():
            run.count(key, n)


def main():
    run = Run()
    ok, output = build.build_sawc2()
    if not ok:
        run.fail("build: sawc2 does not compile: %s" % _first_line(output))
    run_units(run)
    check_fixture_whitespace(run)
    if ok:
        run_golden(run)
    run_subset(run)
    run_grammar(run)
    for failure in run.failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(run.counts.items()))
    verdict = "FAIL (%d)" % len(run.failures) if run.failures else "ok"
    print("compiler tests: %s: %s" % (verdict, summary))
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())

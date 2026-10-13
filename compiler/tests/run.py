#!/usr/bin/env python3
"""The self-hosted compiler's tests, until it can run its own `@test` sidecars.

    python compiler/tests/run.py [--stage 1|2]

Builds Stage 1 (`sawc2`, by the frozen compiler) and Stage 2 (sawc2 built by
Stage 1, `compiler/tools/build.py`), and every sawc2-driven lane below runs
Stage 2; `--stage 1`, or `SAWC2_STAGE=1`, runs them on Stage 1 instead, for
bisecting. Builds the unit programs with the frozen compiler and runs them;
compares `sawc2 lex` with the golden fixtures in `lex/`, whose token
kinds and lex errors must cover the lexer's; runs the subset checker over the
compiler source and its own fixtures in `subset/`; recomputes the std cone of
sawc2's build and compares it with `tools/std_cone.txt`, and the std suspension
table with `tools/std_suspension.txt`; compares the runtime ABI table compiled
into sawc2 with `sawc/rt/ABI.md` and the runtime's sources; and runs the grammar lint,
the reference recognizer's own tests in `grammar/`, and the parser corpus's
checks over `parse/`; runs the corpus rewriter's golden fixtures in
`migrate/`; checks that the parser's grammar tables are current and that its
speculation ledgers, the parser's and the tree builder's, name every field, runs the
depth-funnel lane with its fixtures in `funnel/`, runs the parse lane, which
holds `sawc2 parse` to the parser corpus as far as `compiler/parse/CLAIMS.tsv`
claims, and times the line-length cells, which hold a parse to linear time on
one very long line; and runs the resolve lane over `resolve/`, the typecheck
lane over `typecheck/`, the MIR lane over `mir/` and the evaluator lane over
`eval/`, whose golden dumps, refusal fixtures and the compiler's own source
hold `sawc2 resolve`, `sawc2 typecheck`, `sawc2 mir` and `sawc2 eval` to their
specifications, the evaluator lane also holding the evaluator and typecheck's
fold to agreement over tests/corpus/; runs the std lane over `std/`, the
new std; runs the borrowck lane over `borrowck/`; runs the drops lane over
`drops/`; runs the mono lane over `mono/`, whose golden item dumps, layout
tables and refusal fixtures hold `sawc2 mono` and the target description, and
whose layouts are compared with Stage 0's; runs the coro lane over `coro/`,
whose golden frame decisions and refusal fixtures hold `sawc2 coro`, and whose
decisions must agree with typecheck's summaries; runs the run lane over `run/`,
which builds each program with `sawc2 build` and with Stage 0 and compares
the two binaries' output; and checks that the Stage 0 snapshot in
`coro/stage0/` is whole and prints the coroutine census, which gates nothing;
and checks that a serial and a parallel run print the same (`parallel_order.py`).
The inventory of Stage 0 workaround markers prints first, then each failure as
one line in a fixed order; the summary comes last, and any failure exits 1.

Each of those parts is a step (`STEPS`) run in a process of its own, as many
at once as `SAW_GATE_JOBS` allows (`tools/gate_jobs.py`, `run_steps`); the
output is merged in `STEPS` order, so it is the same at every worker count.
"""
import collections
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, os.path.join(HERE, "grammar"))
sys.path.append(os.path.join(REPO, "tools"))

import gate_jobs  # noqa: E402
import build  # noqa: E402
import comma_funnel  # noqa: E402
import depth_funnel  # noqa: E402
import grammar_tables  # noqa: E402
import speculation_ledger  # noqa: E402
import std_cone  # noqa: E402
import runtime_table  # noqa: E402
import std_suspension  # noqa: E402
import subset_check  # noqa: E402
import ast_nodes as A  # noqa: E402  (on sys.path through subset_check)
import line_length  # noqa: E402
import parse_lane  # noqa: E402
import test_lint  # noqa: E402
import test_parse  # noqa: E402
import test_recognize  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "migrate"))
import test_migrate  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "resolve"))
import resolve_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "typecheck"))
import typecheck_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "mir"))
import mir_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "eval"))
import eval_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "std"))
import std_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "borrowck"))
import borrowck_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "drops"))
import drops_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "mono"))
import mono_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "coro"))
import census  # noqa: E402
import coro_lane  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "run"))
import run_lane  # noqa: E402

UNIT_OUT = os.path.join(REPO, ".build", "compiler-tests")
LEX_FIXTURES = os.path.join(HERE, "lex")
SUBSET_FIXTURES = os.path.join(HERE, "subset")
SUBSET_GENERATED = os.path.join(SUBSET_FIXTURES, "generated")
GRAMMAR_FIXTURES = os.path.join(HERE, "grammar", "fixtures")
PARSE_CORPUS = os.path.join(HERE, "parse")
RESOLVE_CORPUS = os.path.join(HERE, "resolve")
TYPECHECK_CORPUS = os.path.join(HERE, "typecheck")
MIR_CORPUS = os.path.join(HERE, "mir")
EVAL_CORPUS = os.path.join(HERE, "eval")
BORROWCK_CORPUS = os.path.join(HERE, "borrowck")
DROPS_CORPUS = os.path.join(HERE, "drops")
MONO_CORPUS = os.path.join(HERE, "mono")
CORO_CORPUS = os.path.join(HERE, "coro")
RUN_CORPUS = os.path.join(HERE, "run")
FUNNEL_FIXTURES = os.path.join(HERE, "funnel")
LEXER_SOURCE = os.path.join(COMPILER, "lex", "src", "lib.saw")
RUN_TIMEOUT = 60

_MARKER = re.compile(r"//\s*refuses:\s*(.+)$")

# Stage 1 tolerates leaks only while every std `deinit` the compiler reaches
# frees memory or closes a descriptor, so widening the std cone fails here until
# that is re-checked and the pin updated (SL:hazards, leak tolerance).
PINNED_STD_MODULES = ("data", "env", "file", "path", "process")


class Run:
    def __init__(self):
        self.failures = []
        self.counts = {}
        self.inventory = []

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
    # From this checkout's root, so a unit program that reads a fixture by its
    # repository path reads this tree's, whatever the caller's directory.
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, cwd=REPO)
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
    results = gate_jobs.map_ordered(lambda np: build_and_run_unit(*np), programs)
    for _, failure in sorted(results):
        if failure:
            run.fail(failure)
    run.count("unit programs", len(programs))


def sawc2(*args):
    r = subprocess.run([build.SAWC2] + list(args), capture_output=True, timeout=RUN_TIMEOUT)
    return r.returncode, r.stdout


def run_fixture_whitespace(run):
    """No fixture line ends in whitespace, and no fixture ends in a blank line.
    `git apply --whitespace=fix` (the patch server's setting) and editors strip
    both, which would change a fixture on its way into the tree."""
    paths = [p for d in (LEX_FIXTURES, SUBSET_FIXTURES, SUBSET_GENERATED, FUNNEL_FIXTURES)
             for p in glob.glob(os.path.join(d, "*")) if os.path.isfile(p)]
    paths.append(parse_lane.CLAIMS)
    paths.append(std_cone.CONE_FILE)
    paths.append(std_suspension.TABLE_FILE)
    paths += glob.glob(os.path.join(GRAMMAR_FIXTURES, "**", "*.*"), recursive=True)
    paths += glob.glob(os.path.join(PARSE_CORPUS, "**", "*.*"), recursive=True)
    paths += glob.glob(os.path.join(test_migrate.FIXTURES, "*"))
    for suffix in ("*.saw", "*.resolve"):
        paths += glob.glob(os.path.join(RESOLVE_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.typecheck"):
        paths += glob.glob(os.path.join(TYPECHECK_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.mir"):
        paths += glob.glob(os.path.join(MIR_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.eval"):
        paths += glob.glob(os.path.join(EVAL_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.borrowck", "*.md"):
        paths += glob.glob(os.path.join(BORROWCK_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.drops", "*.md", "*.tsv"):
        paths += glob.glob(os.path.join(DROPS_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.mono", "*.layouts", "*.md", "*.tsv"):
        paths += glob.glob(os.path.join(MONO_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.ll", "*.md"):
        paths += glob.glob(os.path.join(RUN_CORPUS, "**", suffix), recursive=True)
    for suffix in ("*.saw", "*.coro", "*.layouts", "*.md", "*.tsv", "*.stage0"):
        paths += glob.glob(os.path.join(CORO_CORPUS, "**", suffix), recursive=True)
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
    run.inventory = subset_check.workaround_inventory(files)
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
    # One call checks each fixture as its own build and compiles them together.
    reported = collections.defaultdict(list)
    for d in subset_check.check_files(fixtures):
        reported[d.path].append(d)
    for path in fixtures:
        check_subset_fixture(run, path, reported[os.path.relpath(path, REPO)])
        run.count("checker fixtures")
    # An `owned-operand` position that only refused source can reach is asked of
    # Stage 0 directly: the checker never compiles a build another rule refuses.
    for path in sorted(glob.glob(os.path.join(SUBSET_GENERATED, "*.saw"))):
        rel = os.path.relpath(path, REPO)
        diags = subset_check.check_generated([(path, [subset_check.SourceFile(path)])],
                                             {path: rel})
        check_subset_fixture(run, path, diags)
        run.count("checker fixtures")


def _fixture_rule(path):
    """`RULE.saw` and `RULE.VARIANT.saw` are fixtures of RULE."""
    return os.path.basename(path).split(".")[0]


def check_subset_fixture(run, path, diags):
    """A fixture's `// refuses: RULE...` markers name exactly the (line, rule)
    pairs the checker reports in `diags`, a rule named twice on a line meaning
    two findings of it there; a `clean` fixture has none."""
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
    got = collections.Counter((d.line, d.rule) for d in diags)
    for line, name in sorted(set(expected) | set(got)):
        want, have = expected[(line, name)], got[(line, name)]
        if not have:
            run.fail("subset fixture %s:%d: expected %s, not reported" % (rel, line, name))
        elif not want:
            run.fail("subset fixture %s:%d: unexpected %s" % (rel, line, name))
        elif want != have:
            run.fail("subset fixture %s:%d: expected %s %d times, reported %d"
                     % (rel, line, name, want, have))


def run_std_cone(run):
    """The std cone of Stage 0's build of sawc2 against `tools/std_cone.txt`,
    failing in either direction (SL:architecture §4, the bootstrap std)."""
    failures, counts = std_cone.check()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_std_suspension(run):
    """The std suspension table against the frozen compiler's std check, and
    the modules its `suspends` rows fall in against the parking spellings."""
    failures, counts = std_suspension.check()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_runtime_table(run):
    """The runtime ABI table compiled into sawc2 against a fresh reading of
    rt/ABI.md through `sawc/runtime_abi.py`, and each host's runtime sources
    and shim against it."""
    failures, counts = runtime_table.check()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def _run_module(run, module):
    failures, counts = module.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


# The grammar's three checks are three steps, since each is long enough alone;
# the full-corpus recognizer run is the battery's `grammarcorpus` lane.
def run_grammar_lint(run):
    """The grammar lint with its fixtures."""
    _run_module(run, test_lint)


def run_recognizer(run):
    """The recognizer's unit tests."""
    _run_module(run, test_recognize)


def run_grammar_parse(run):
    """The parser corpus's checks."""
    _run_module(run, test_parse)


def run_migrate(run):
    """The corpus rewriter's golden fixtures (compiler/tools/migrate)."""
    failures, counts = test_migrate.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_parser(run):
    """The parser's grammar tables, its speculation ledger, its comma-list and
    depth funnels, its parse lane and its line-length cells; the last three run
    sawc2, so they wait for it to build."""
    stale = grammar_tables.check()
    if stale:
        run.fail("grammar tables: " + stale)
    for module in (speculation_ledger, comma_funnel, depth_funnel, parse_lane, line_length):
        failures, counts = module.run()
        for failure in failures:
            run.fail(failure)
        for key, n in counts.items():
            run.count(key, n)


def run_resolver(run):
    """The resolve lane (compiler/tests/resolve/resolve_lane.py): the golden dumps, the
    refusal fixtures and their rule coverage, and the compiler's own source
    resolving with no refusal."""
    failures, counts = resolve_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_typechecker(run):
    """The typecheck lane (compiler/tests/typecheck/typecheck_lane.py): the golden
    dumps, the refusal fixtures and their rule coverage, and the compiler's own
    source checking with no refusal."""
    failures, counts = typecheck_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_mir(run):
    """The MIR lane (compiler/tests/mir/mir_lane.py): the golden dumps, the
    refusal fixtures, and the compiler's own source lowering with no refusal
    and no invariant."""
    failures, counts = mir_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_eval(run):
    """The evaluator lane (compiler/tests/eval/eval_lane.py): the golden
    records, the refusal fixtures and their rule coverage, the compiler's own
    source evaluating with no refusal, and the evaluator's agreement with
    typecheck's fold over tests/corpus/."""
    failures, counts = eval_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_std(run):
    """The std lane (compiler/tests/std/std_lane.py): the new std under sawc2,
    its subset profile, its lang items, its cone and its API equivalence."""
    failures, counts = std_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_borrowck(run):
    """The borrowck lane (compiler/tests/borrowck/borrowck_lane.py): the
    conformance matrix, the golden records, the refusal fixtures and their
    rule coverage, the compiler's own source and the new std checking with no
    refusal, and the move-error differential over tests/corpus/."""
    failures, counts = borrowck_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_drops(run):
    """The drops lane (compiler/tests/drops/drops_lane.py): the golden
    records, the refusal and due fixtures, the compiler's own source and the
    new std elaborating with no refusal, the verifier clean over tests/corpus/,
    and the conformance rows drop elaboration owns."""
    failures, counts = drops_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_mono(run):
    """The mono lane (compiler/tests/mono/mono_lane.py): the golden item dumps
    and layout tables, the refusal fixtures and their rule coverage, and the
    layouts against Stage 0's."""
    failures, counts = mono_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_coro(run):
    """The coro lane (compiler/tests/coro/coro_lane.py): the golden frame
    decisions, the refusal fixtures and their rule coverage, and the
    decisions' agreement with typecheck's summaries."""
    failures, counts = coro_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_programs(run):
    """The run lane (compiler/tests/run/run_lane.py): each program built by
    sawc2 and by Stage 0, the two binaries' output and exit status compared,
    the due programs refused where they say, and hello's `.ll` pinned."""
    failures, counts, _ = run_lane.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)


def run_census(run):
    """The coroutine census (compiler/tests/coro/census.py), as information:
    only a Stage 0 snapshot that is not whole fails, and the census's lines
    print beside the inventory."""
    failures, counts, lines = census.run()
    for failure in failures:
        run.fail(failure)
    for key, n in counts.items():
        run.count(key, n)
    run.inventory += lines


def run_parallel_order(run):
    """The runners print the same at every worker count, an injected failure
    included (compiler/tests/parallel_order.py)."""
    import parallel_order
    _run_module(run, parallel_order)


class Step:
    """One part of the run, `run_<name>(run)`. `when` is "always" (it needs
    nothing built), "after build" (it waits for the build, whatever the build
    says) or "built" (it runs only when sawc2 builds). A step holds one token
    while it runs, and its pools take more as they go
    (`gate_jobs.map_ordered`), which makes its sawc2 calls overlap
    (`calls_overlap`); a step with a `width` runs a pool that takes none, so it
    holds `width` tokens and gets that as its SAW_GATE_JOBS."""

    def __init__(self, name, when, calls_overlap=False, width=None):
        self.name = name
        self.when = when
        self.calls_overlap = calls_overlap
        self.width = width

    def function(self):
        return globals()["run_" + self.name]


# In output order, which is the order the parts ran in when they ran serially.
STEPS = (
    Step("units", "always", calls_overlap=True),
    Step("fixture_whitespace", "always"),
    Step("golden", "built"),
    Step("subset", "always", calls_overlap=True),
    Step("std_cone", "built", calls_overlap=True),
    Step("std_suspension", "after build"),
    Step("runtime_table", "after build"),
    Step("grammar_lint", "after build"),
    Step("recognizer", "after build"),
    Step("grammar_parse", "after build", calls_overlap=True),
    Step("migrate", "after build", calls_overlap=True),
    Step("parser", "built", calls_overlap=True),
    Step("resolver", "built"),
    Step("typechecker", "built"),
    Step("mir", "built"),
    Step("eval", "built"),
    Step("std", "built", calls_overlap=True),
    Step("borrowck", "built"),
    Step("drops", "built"),
    Step("mono", "built"),
    Step("coro", "built"),
    Step("programs", "built", calls_overlap=True),
    Step("census", "built", calls_overlap=True, width=2),
    Step("parallel_order", "built", calls_overlap=True),
)
STEP_BY_NAME = {step.name: step for step in STEPS}

# The longest steps start first, so that the short ones fill in around them;
# the rest start in `STEPS` order. Only the wall time depends on this.
LONG_STEPS = ("units", "subset", "drops", "borrowck", "grammar_parse", "eval", "std_cone", "programs",
              "std", "typechecker", "parser", "migrate", "parallel_order")

STEP_OUT = os.path.join(REPO, ".build", "compiler-tests-steps")

# What a step's sawc2 call may use, from its environment: the tokens its step
# holds for each call (`run_steps`).
CALL_TOKENS = "SAW_GATE_CALL_TOKENS"


def run_steps(steps, build_sawc2=None, sawc2=None, env=None, budget=None, call_tokens=1):
    """Runs each of `steps` in a process of its own and returns (the build's
    (ok, output), or None without one; [(step, result)] in the order of
    `steps`). A result is a dict: failures, counts, inventory, stdout, stderr,
    skipped, true of a "built" step after a failed build, and crashed, true of
    a step whose process ended without its result.

    `build_sawc2` runs here first, every step but an "always" one waiting for
    it, and `sawc2` replaces `build.SAWC2` in each step. The build and each
    step hold their tokens of the gate's budget while they run, the first of
    them this process's own (`gate_jobs.budget`); a step whose calls do not
    overlap holds `call_tokens` (two under the fixpoint lane's twin), which
    SAW_GATE_CALL_TOKENS tells each call it may use. Each step gets `budget`,
    or `gate_jobs.jobs()` when that is smaller, as its SAW_GATE_JOBS, and
    SAW_GATE_STEP, its name.
    """
    limit = min(budget or gate_jobs.jobs(), gate_jobs.jobs())
    call_tokens = max(1, min(call_tokens, limit))
    os.makedirs(STEP_OUT, exist_ok=True)
    cond = threading.Condition()
    state = {"own": True, "running": 0, "built": build_sawc2 is None, "ok": build_sawc2 is None,
             "build": None}
    results = {}

    def cost(step):
        if step.width:
            return min(step.width, limit)
        return 1 if step.calls_overlap else call_tokens

    def take(count):
        """`count` tokens, the own one first, or None when they are not free."""
        held = []
        if state["own"]:
            state["own"] = False
            held.append("own")
        while len(held) < count:
            token = gate_jobs.try_acquire()
            if token is None:
                give_back(held)
                return None
            held.append(token)
        return held

    def give_back(held):
        for token in held:
            if token == "own":
                state["own"] = True
            else:
                gate_jobs.release(token)

    def finish(name, result, held):
        with cond:
            if name is not None:
                results[name] = result
            give_back(held)
            state["running"] -= 1
            cond.notify_all()

    def do_build(held):
        try:
            outcome = build_sawc2()
        except BaseException as e:  # a crash is a failed build, reported as one
            outcome = (False, "%s: %s" % (type(e).__name__, e))
        with cond:
            state["build"] = outcome
            state["built"] = True
            state["ok"] = outcome[0]
        finish(None, None, held)

    def launch(step, held):
        step_env = dict(env or {})
        step_env[CALL_TOKENS] = str(1 if step.calls_overlap or step.width else call_tokens)

        def go():
            try:
                result = _run_step_process(step, step.width or limit, sawc2, step_env)
            except BaseException as e:
                result = _crashed(step, "%s: %s" % (type(e).__name__, e), b"", b"")
            finish(step.name, result, held)
        threading.Thread(target=go, daemon=True).start()

    order = [s for name in LONG_STEPS for s in steps if s.name == name]
    order += [s for s in steps if s not in order]
    with gate_jobs.budget(), cond:
        if build_sawc2 is not None:
            state["running"] += 1
            threading.Thread(target=do_build, args=(take(1),), daemon=True).start()
        pending = order
        while pending:
            if state["built"] and not state["ok"]:
                for step in [s for s in pending if s.when == "built"]:
                    results[step.name] = _result(skipped=True)
                    pending.remove(step)
            ready = [s for s in pending if s.when == "always" or state["built"]]
            held = None
            if ready and state["running"] < limit:
                held = take(cost(ready[0]))
            if held is None:
                # Tokens free up in other processes too, which notify nobody.
                cond.wait(timeout=0.05)
                continue
            pending.remove(ready[0])
            state["running"] += 1
            launch(ready[0], held)
        while state["running"]:
            cond.wait()
    return state["build"], [(step, results[step.name]) for step in steps]


def _run_step_process(step, workers, sawc2, env):
    """`run.py --step NAME` in a child process with `workers` as its budget."""
    fd, result_path = tempfile.mkstemp(prefix="%s-" % step.name, suffix=".json", dir=STEP_OUT)
    os.close(fd)
    try:
        cmd = [sys.executable, os.path.abspath(__file__), "--step", step.name, "--result", result_path]
        if sawc2:
            cmd += ["--sawc2", sawc2]
        child_env = gate_jobs.child_env(workers)
        child_env.update(env or {})
        child_env["SAW_GATE_STEP"] = step.name
        r = subprocess.run(cmd, capture_output=True, env=child_env)
        try:
            with open(result_path, encoding="utf-8") as fh:
                result = json.load(fh)
        except (OSError, ValueError):
            result = None
        if r.returncode != 0 or result is None:
            why = _first_line("\n".join(reversed((r.stderr or b"").decode("utf-8", "replace").splitlines())))
            return _crashed(step, "exit %d: %s" % (r.returncode, why), r.stdout, r.stderr)
        return _result(result["failures"], result["counts"], result["inventory"], r.stdout, r.stderr)
    finally:
        os.remove(result_path)


def _result(failures=(), counts=None, inventory=(), stdout=b"", stderr=b"", skipped=False, crashed=False):
    return {"failures": list(failures), "counts": dict(counts or {}), "inventory": list(inventory),
            "stdout": stdout, "stderr": stderr, "skipped": skipped, "crashed": crashed}


def _crashed(step, why, stdout, stderr):
    """A step whose process ended without its result: one failure naming it."""
    return _result(["step %s: did not finish: %s" % (step.name, why)], stdout=stdout, stderr=stderr,
                   crashed=True)


def step_main(name, result_path, sawc2):
    """One step, in the child process `run_steps` starts: its Run as JSON."""
    if sawc2:
        build.SAWC2 = sawc2
    run = Run()
    STEP_BY_NAME[name].function()(run)
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump({"failures": run.failures, "counts": run.counts, "inventory": run.inventory}, fh)
    return 0


def merge(build_outcome, results):
    """One Run of the build's failure, then each step's, in order."""
    run = Run()
    if build_outcome is not None and not build_outcome[0]:
        run.fail("build: sawc2 does not compile: %s" % _first_line(build_outcome[1]))
    for _, result in results:
        run.failures += result["failures"]
        for key, n in result["counts"].items():
            run.count(key, n)
        run.inventory += result["inventory"]
    return run


def render(run):
    """The lines run.py prints after the steps' own output."""
    lines = list(run.inventory) + list(run.failures)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(run.counts.items()))
    verdict = "FAIL (%d)" % len(run.failures) if run.failures else "ok"
    lines.append("compiler tests: %s: %s" % (verdict, summary))
    return "".join(line + "\n" for line in lines)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--step"] and len(args) in (4, 6) and args[1] in STEP_BY_NAME and args[2] == "--result" \
            and (len(args) == 4 or args[4] == "--sawc2"):
        return step_main(args[1], args[3], args[5] if len(args) == 6 else None)
    if args[:1] == ["--stage"] and len(args) == 2 and args[1] in ("1", "2"):
        # The environment carries the choice to the steps and their own child processes.
        os.environ["SAWC2_STAGE"] = args[1]
        build.SAWC2 = build.STAGE1 if args[1] == "1" else build.STAGE2
    elif args:
        print("usage: run.py [--stage 1|2]")
        return 2
    build_outcome, results = run_steps(STEPS, build_sawc2=build.build_sawc2)
    for _, result in results:
        sys.stdout.buffer.write(result["stdout"])
        sys.stderr.buffer.write(result["stderr"])
    sys.stdout.flush()
    sys.stderr.flush()
    run = merge(build_outcome, results)
    sys.stdout.write(render(run))
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())

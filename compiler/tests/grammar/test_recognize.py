#!/usr/bin/env python3
"""The recognizer's own tests: pinned trees, pinned records, and the rules.

    python compiler/tests/grammar/test_recognize.py

`fixtures/trees/NAME.saw` pins its `tree_report` in NAME.trees, with every
removed production enabled in NAME.removed.trees, and its coverage records in
NAME.record. A tree fixture whose first line is `// rule: RULE` must parse to
one tree, and to a different tree count with RULE switched off. A
`fixtures/refusals/NAME.saw` fixture starts `// refuses: RULE` and
`// verdict: VERDICT DETAIL`: `check_source` must give that verdict, and must
accept the text with RULE switched off. Every rule the recognizer applies needs
a fixture of one kind or the other, so each is seen deciding something.
VERDICTS pins more verdicts, REMOVED_FORMS the removed form a refusal is
classified as, CORPUS_CASES the corpus lane's comparison; each token of
OPEN_END_FOLLOW must decide a tree of OPEN_END_FIXTURE, and
`contexts.problems` must be empty.
"""
import glob
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import contexts  # noqa: E402
import extract  # noqa: E402
import recognize  # noqa: E402

TREES = os.path.join(HERE, "fixtures", "trees")
REFUSALS = os.path.join(HERE, "fixtures", "refusals")
RULE_RE = re.compile(r"^// rule: (syntax\.(?:rule|lex)\.\S+)$")
REFUSES_RE = re.compile(r"^// refuses: (syntax\.(?:rule|lex)\.\S+)\n// verdict: (\S+) (.*)\n")

# (source, verdict): the token-level rules the recognizer applies before parsing.
VERDICTS = [
    ("func f() {\n    let v: Vector<Int>= w\n}\n", "OK"),        # generic-close-split
    ("func f() {\n    let m: Map<K, Vector<V>>= w\n}\n", "OK"),  # both lists close
    ("func f() {\n    let s = a << 2 >> b\n}\n", "OK"),          # SHL and SHR
    ("func f() {\n    g(a,\n      b)\n}\n", "OK"),                # a line break in ( )
    ("func f() {\n    let v = Vector<\n        Int>()\n}\n", "OK"),  # in a generic list
    ("func f() {\n    let x = 1 +\n        2\n}\n", "OK"),        # operator-continuation
    ("func f() {\n    let x = 1\n        - 2\n}\n", "OK"),        # a new statement: - 2
    ("func f() {\n    let x = 1\n        + 2\n}\n", "FAIL"),      # no unary plus
    ("func f() {\n    x = 1 y\n}\n", "FAIL"),                     # juxtaposition
    ("func f() {\n    let café = 1\n}\n", "LEXERR"),         # ascii-identifier
    ("func f() {\n    print(\"{a b}\")\n}\n", "SEGFAIL"),         # interpolation-whole
    ("func f() {\n    print(\"{\\q}\")\n}\n", "SEGLEX"),          # a segment that fails to lex
    ("func f() {\n    print(\"{g(\"{a}\")}\")\n}\n", "OK"),       # a nested segment
    ("func f() {\n    print(\"{g(\"{a b}\")}\")\n}\n", "SEGFAIL"),  # checked on its own too
    ("const X: Int = 1\n", "FAIL"),                               # removed: refused-const
    # A comparison's `<` and a later line's `>` hold no generic list between them.
    ("func f() {\n    ok = n < max\n    big = m > 0\n}\n", "OK"),
    ("func f() {\n    f(a < b)\n    g(c > d)\n}\n", "OK"),
    ("func f() {\n    let v: Vector<\n        Int\n    > = w\n}\n", "OK"),  # a type's list
    # generic-close-split after `&`, a qualified path and `->`
    ("func f() {\n    let g: &Vector<Int>= w\n}\n", "OK"),
    ("func f() {\n    let g: std.Vector<Int>= w\n}\n", "OK"),
    ("func f() {\n    let g: () -> Vector<Int>= w\n}\n", "OK"),
    ("func f() {\n    x = a<b>>= 1\n}\n", "FAIL"),                # no split in an expression
    # A label's `:` leads an expression, not a type, so no list is committed to
    # and a later `>=` compares: an argument, a field initializer, a payload, a
    # map entry, a named tuple, a call across lines, a nested call.
    ("func f() {\n    let r = pick(a: a < b, b: b >= a)\n}\n", "OK"),
    ("func f() {\n    let r = pick(a: a < b, b >= a)\n}\n", "OK"),
    ("func f() {\n    let p = P(lo: a < b, hi: a >= b)\n}\n", "OK"),
    ("func f() {\n    let m = Msg.Move(x: a < b, y: a >= b)\n}\n", "OK"),
    ("func f() {\n    let m = .Move(x: a < b, y: a >= b)\n}\n", "OK"),
    ("func f() {\n    let m = {1: a < b, 2: b >= a}\n}\n", "OK"),
    ("func f() {\n    let t = (lo: a < b, hi: b >= a)\n}\n", "OK"),
    ("func f() {\n    let r = pick(\n        a: a < b,\n        b: b >= a\n    )\n}\n", "OK"),
    ("func f() {\n    let r = pick(a: a < ident(x: b), b: b >= a)\n}\n", "OK"),
    # An arm's `->` leads an expression too, so this is a chain, which
    # REMOVED_FORMS names.
    ("func f() {\n    let r = match n {\n        case 0 -> a < b + 1 >= 0\n"
     "        case _ -> false\n    }\n}\n", "FAIL"),
    ("func f() {\n    if a { b } { c }\n}\n", "FAIL"),            # head-restriction
    # statement-separator and declaration-separator
    ("func f() {\n    x = 1;\n}\n", "FAIL"),
    ("func f() {\n    x = 1;; y = 2\n}\n", "FAIL"),
    ("func f() {\n    x = 1\n    ; y = 2\n}\n", "FAIL"),
    ("func f() {\n    x = 1; y = 2\n}\n", "OK"),
    ("func a() {\n} func b() {\n}\n", "FAIL"),
    ("struct P { x: Int }; struct Q { y: Int }\n", "FAIL"),
    # doc-attach: what a `///` run may document
    ("enum E {\n    /// A case.\n    case A\n}\n/// An alias.\ntype T = Int\n", "OK"),
    ("/// A test-only helper.\n@test\nfunc helper() {\n}\n", "OK"),
    ("/// A test case.\n@test \"adds\" {\n}\n", "FAIL"),
    ("/// Documents nothing.\n", "FAIL"),
]


# (source, the removed form the classifier names): refusals a removed production
# explains, so the report names its rule rather than a token.
REMOVED_FORMS = [
    ("func f() {\n    let r = match n {\n        case 0 -> a < b + 1 >= 0\n"
     "        case _ -> false\n    }\n}\n", "syntax.expr.refused-compare-chain"),
    ("func f() {\n    let r = pick(a: a < b + 1 >= 0)\n}\n",
     "syntax.expr.refused-compare-chain"),
]
# The fixture whose trees need each token of OPEN_END_FOLLOW.
OPEN_END_FIXTURE = "range_open_end.saw"


def _first_difference(want, got):
    for n in range(max(len(want), len(got))):
        a = want[n] if n < len(want) else "<end>"
        b = got[n] if n < len(got) else "<end>"
        if a != b:
            return "line %d: expected %r, got %r" % (n + 1, a[:100], b[:100])
    return "a trailing newline"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def record_lines(g, text):
    out = []
    for origin, parse in recognize.source_parses(g, text):
        for d in parse.derivations():
            out.append("parse %s" % (origin or "file"))
            out += parse.record(d).lines()
    return out


def check_pins(failures, g, g_removed):
    count = 0
    for saw in sorted(glob.glob(os.path.join(TREES, "*.saw"))):
        stem = os.path.splitext(saw)[0]
        name = os.path.basename(saw)
        rel = os.path.relpath(saw, extract.REPO)
        text = _read(saw)
        if not os.path.exists(stem + ".trees"):
            failures.append("recognizer fixture %s: no .trees expectation" % rel)
        for suffix, grammar in ((".trees", g), (".removed.trees", g_removed)):
            if os.path.exists(stem + suffix):
                got = recognize.tree_report(grammar, name, text)[0]
                want = _read(stem + suffix).split("\n")[:-1]
                if got != want:
                    failures.append("recognizer fixture %s%s: %s"
                                    % (rel, suffix, _first_difference(want, got)))
                count += 1
        if os.path.exists(stem + ".record"):
            got = record_lines(g, text)
            want = _read(stem + ".record").split("\n")[:-1]
            if got != want:
                failures.append("recognizer fixture %s.record: %s"
                                % (rel, _first_difference(want, got)))
            count += 1
    return count


def applied_rules(failures, model, g):
    """Every rule the recognizer applies, each checked against the grammar: the
    tables' nonterminals, alternatives and methods must exist too."""
    rules = set(model.rule_ids()) | set(model.lexical_rule_ids())
    alts = {a.effective_name for a in model.alternatives()}
    nts = set(g.info)
    applied = set()
    for nt, (what, cited) in recognize.PREFERENCES.items():
        if nt not in nts:
            failures.append("recognizer: %s is not a nonterminal" % nt)
        if what not in alts:
            failures.append("recognizer: %s is not an alternative" % what)
        applied.update(cited)
    for nt, method, rule in recognize.FILTERS:
        if nt not in nts:
            failures.append("recognizer: %s is not a nonterminal" % nt)
        if not hasattr(recognize.Forest, method):
            failures.append("recognizer: Forest has no filter %s" % method)
        applied.add(rule)
    applied.update(recognize.OTHER_RULES)
    for rule in sorted(applied - rules):
        failures.append("recognizer: %s is not a section-13 or lexical rule" % rule)
    named = (set(recognize.TRAILING_CALLEES) | set(recognize.RECEIVERS)
             | set(recognize.ATTRIBUTE_NAMES) | set(recognize.ATTRIBUTE_HOSTS)
             | recognize.DOCUMENTED | {"syntax.expr.call.paren-trailing",
                                       "syntax.decl.receiver.exclusive",
                                       recognize.TEST_ONLY_DECLARATION})
    for name in sorted(named - alts):
        failures.append("recognizer: %s is not an alternative" % name)
    for nt in (set(recognize.LEAF_HOPS) | set(recognize.HEAD_RESETS)
               | set(recognize.GENERIC_HOSTS)) - nts:
        failures.append("recognizer: %s is not a nonterminal" % nt)
    return applied


def check_rules(failures, model, g):
    """Each applied rule decides a tree fixture or a refusal fixture."""
    applied = applied_rules(failures, model, g)
    decided = set()
    for saw in sorted(glob.glob(os.path.join(TREES, "*.saw"))):
        text = _read(saw)
        m = RULE_RE.match(text.split("\n", 1)[0])
        if not m:
            continue
        rel = os.path.relpath(saw, extract.REPO)
        rule = m.group(1)
        if rule not in applied:
            failures.append("recognizer fixture %s: the recognizer does not apply %s"
                            % (rel, rule))
            continue
        decided.add(rule)
        with_rule = _tree_counts(g, text)
        without = _without(rule, lambda: _tree_counts(g, text))
        if with_rule != [1] * len(with_rule):
            failures.append("recognizer fixture %s: tree counts %s, want one tree per parse"
                            % (rel, with_rule))
        if without == with_rule:
            failures.append("recognizer fixture %s: %s decides nothing here; without it the "
                            "tree counts are still %s" % (rel, rule, without))
    count = len(decided)
    for saw in sorted(glob.glob(os.path.join(REFUSALS, "*.saw"))):
        text = _read(saw)
        rel = os.path.relpath(saw, extract.REPO)
        m = REFUSES_RE.match(text)
        if not m:
            failures.append("recognizer fixture %s: want `// refuses: RULE` and "
                            "`// verdict: VERDICT DETAIL` lines first" % rel)
            continue
        rule, want = m.group(1), (m.group(2), m.group(3))
        if rule not in applied:
            failures.append("recognizer fixture %s: the recognizer does not apply %s"
                            % (rel, rule))
            continue
        decided.add(rule)
        count += 1
        got = recognize.check_source(g, text, trees=True)
        if got != want:
            failures.append("recognizer fixture %s: %s %s, expected %s %s"
                            % ((rel,) + got + want))
        # Without the rule the text parses, with one tree or with the several
        # the rule was choosing between.
        without = _without(rule, lambda: recognize.check_source(g, text, trees=True))
        if without[0] not in ("OK", "AMBIGUOUS"):
            failures.append("recognizer fixture %s: %s decides nothing here; without it the "
                            "verdict is still %s %s" % ((rel, rule) + without))
    for rule in sorted(applied - decided):
        failures.append("recognizer: no fixture cites %s, so nothing shows it deciding" % rule)
    return count


def check_removed_forms(failures, model, g):
    """Each of REMOVED_FORMS is refused, and the classifier names its form."""
    import corpus
    classifier = corpus.Classifier(model)
    with tempfile.TemporaryDirectory() as tmp:
        for n, (source, form) in enumerate(REMOVED_FORMS):
            path = os.path.join(tmp, "form%d.saw" % n)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(source)
            verdict, detail = recognize.check_source(g, source)
            reason = classifier.classify(path, verdict, detail)
            if verdict == "OK" or reason != "a-removed: " + form:
                failures.append("removed form %r: %s, classified %r, expected a-removed: %s"
                                % (source, verdict, reason, form))
    return len(REMOVED_FORMS)


def check_open_end(failures, g):
    """Each token of OPEN_END_FOLLOW decides a tree of the open-end fixture: with
    it gone from the set, the fixture's report changes."""
    path = os.path.join(TREES, OPEN_END_FIXTURE)
    text = _read(path)
    full = recognize.OPEN_END_FOLLOW
    want = recognize.tree_report(g, OPEN_END_FIXTURE, text)[0]
    for tok in full:
        recognize.OPEN_END_FOLLOW = tuple(t for t in full if t != tok)
        try:
            got = recognize.tree_report(g, OPEN_END_FIXTURE, text)[0]
        finally:
            recognize.OPEN_END_FOLLOW = full
        if got == want:
            failures.append("recognizer fixture %s: without %r in OPEN_END_FOLLOW its trees "
                            "are unchanged" % (os.path.relpath(path, extract.REPO), tok))
    return len(full)


def _without(rule, run):
    """run() with one rule switched off, restored however run() ends."""
    recognize.DISABLED.add(rule)
    try:
        return run()
    finally:
        recognize.DISABLED.discard(rule)


def _tree_counts(g, text):
    return [len(p.derivations()) for _, p in recognize.source_parses(g, text)]


# (path, its verdict and reason, its record row or None, whether the lane fails)
CORPUS_CASES = [
    ("accepted.saw", ("OK", ""), None, False),
    ("refused.saw", ("FAIL", "a-error: 1:1 near X"), None, True),
    ("listed_accepted.saw", ("OK", ""), ("FAIL", "a-error: 1:1 near X"), True),
    ("moved.saw", ("FAIL", "a-error: 2:1 near X"), ("FAIL", "a-error: 1:1 near X"), True),
    ("recorded.saw", ("FAIL", "a-error: 1:1 near X"), ("FAIL", "a-error: 1:1 near X"), False),
    ("ambiguous.saw", ("AMBIGUOUS", "finding: 1:1 x"), ("AMBIGUOUS", "finding: 1:1 x"), True),
    ("unmodelled.saw", ("OK", ""), ("UNMODELLED", "unmodelled: syntax.rule.x"), False),
    ("now_modelled.saw", ("FAIL", "a-error: 1:1 refused by syntax.rule.x"),
     ("UNMODELLED", "unmodelled: syntax.rule.x"), True),
]


def check_corpus(failures, model):
    """The corpus lane fails each way it can, and the classifier names a removed form."""
    import corpus
    got = {p: v for p, v, _, _ in CORPUS_CASES}
    expected = {p: row for p, _, row, _ in CORPUS_CASES if row is not None}
    expected["gone.saw"] = ("FAIL", "a-error: 1:1 near X")
    lines = corpus.compare(list(got), got, expected, gone=["gone.saw", "never_listed.saw"])
    failing = {line.split(":")[0] for line in lines}
    want = {p for p, _, _, fails in CORPUS_CASES if fails} | {"gone.saw"}
    if failing != want:
        failures.append("corpus lane: fails %s, expected %s" % (sorted(failing), sorted(want)))
    # Recording keeps an UNMODELLED row only while the recognizer accepts its file.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "expected.tsv")
        corpus.write_expected(got, expected, path)
        rows, problems = corpus.load_expected(path)
    kinds = {p: row[0] for p, row in rows.items()}
    want_kinds = {p: v[0] for p, v in got.items() if v[0] != "OK"}
    want_kinds["unmodelled.saw"] = "UNMODELLED"
    if problems or kinds != want_kinds:
        failures.append("corpus record: wrote %s%s, expected %s"
                        % (sorted(kinds.items()), problems, sorted(want_kinds.items())))
    t6 = os.path.join(TREES, "t6_const.saw")
    reason = corpus.Classifier(model).classify(t6, "FAIL", "")
    if reason != "a-removed: syntax.decl.refused-const":
        failures.append("corpus classifier: %s is %r" % (os.path.relpath(t6, extract.REPO), reason))
    return len(CORPUS_CASES) + 2


def run():
    """(failure lines, counts) for run.py."""
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    failures = []
    model = extract.extract()
    g = recognize.Grammar(model)
    g_removed = recognize.Grammar(model, "all")
    counts = {"recognizer pins": check_pins(failures, g, g_removed)}
    counts["recognizer rule fixtures"] = check_rules(failures, model, g)
    for source, want in VERDICTS:
        got = recognize.check_source(g, source)[0]
        if got != want:
            failures.append("recognizer verdict: %r is %s, expected %s" % (source, got, want))
    counts["recognizer verdicts"] = len(VERDICTS)
    counts["removed forms"] = check_removed_forms(failures, model, g)
    counts["open-end follow tokens"] = check_open_end(failures, g)
    counts["corpus lane cases"] = check_corpus(failures, model)
    failures.extend(contexts.problems(model))
    return failures, counts


def main():
    failures, counts = run()
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("recognizer tests: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                        summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

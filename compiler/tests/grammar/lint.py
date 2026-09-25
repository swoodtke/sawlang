#!/usr/bin/env python3
"""The grammar lint: every structural rule GRAMMAR.md states about itself.

    python compiler/tests/grammar/lint.py [GRAMMAR.md] [--spec LANGUAGE_SPEC.md]

Each finding prints as `FILE:LINE: CHECK: message`, sorted by line, and any
finding exits 1. `CHECKS` names every check; each has a fixture under
`fixtures/` that proves it fires at the right line (test_lint.py), and each
must examine at least one item of the real grammar, so no check is vacuous.
"""
import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import extract  # noqa: E402

SPEC = os.path.join(extract.REPO, "LANGUAGE_SPEC.md")
NAME_RE = re.compile(r"^syntax\.[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+$")
NODE_RE = re.compile(r"^(?:[A-Z][A-Za-z0-9]*|-)$")
REF_RE = re.compile(r"^(?:SL:[a-z]+ §\d+(?:\.\d+)*|SL-\d+(?: c\d+)?|design \d+[a-z]?(?: [A-Z]\d+′?)?)$")
PRODUCTION_LINE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)* ::= ")
OPERATORS = ("(", ")", "|", "?", "*", "+", "ε")

# check id -> what it enforces. Order is the order findings are reported in at
# one line.
CHECKS = collections.OrderedDict([
    ("fence", "every fence is closed, and one ebnf-notation fence defines the notation"),
    ("structure", "an ebnf block holds header, rule and continuation lines in that order"),
    ("header", "a header line has the notation's fields, in order, two spaces apart"),
    ("outside-fence", "no production is written outside an ebnf fence"),
    ("name-format", "production and alternative names are syntax.AREA.CONSTRUCT(.PART)*"),
    ("alternative-prefix", "an alternative's name extends its production's name"),
    ("unnamed-alternative", "every alternative of a multi-alternative production is named"),
    ("alternative-text", "an alternative is a sequence of notation items, with no stray @"),
    ("parentheses", "an alternative's parentheses balance"),
    ("status", "status= is one of the notation's statuses"),
    ("spec", "spec= names a heading of LANGUAGE_SPEC.md"),
    ("ref-format", "ref= names a document section, a tracker issue or a design"),
    ("lockdown-ref", "a lockdown production names its source in ref="),
    ("node-kind", "node= is an UpperCamelName or -"),
    ("duplicate-name", "every syntax.* name is defined once"),
    ("duplicate-nonterminal", "every nonterminal is defined once"),
    ("undefined-nonterminal", "every nonterminal an alternative uses is defined"),
    ("unused-nonterminal", "every nonterminal is reachable from a start symbol"),
    ("start-symbol", "the start symbols of section 1 are defined"),
    ("head-expr", "head-expr derives exactly what expr derives"),
    ("token-kind", "every token kind an alternative uses is in the token-kind table"),
    ("spelling", "every quoted terminal is a keyword or a listed spelling"),
    ("contextual-word", "every contextual terminal is a listed contextual word, not a keyword"),
    ("unknown-name", "every syntax.* name cited in prose, rules or tables is defined"),
    ("trailing-whitespace", "no line ends in whitespace"),
    ("unknown-table", "every table has one of the known schemas"),
    ("table-count", "each table schema appears exactly once"),
    ("table-width", "every table row has as many cells as its header"),
    ("context-columns", "the context matrix's columns are the defined contexts, in order"),
    ("context-code", "every context cell is a defined code"),
    ("context-construct", "every context row names a production, once"),
    ("lexical-rule-id", "a lexical rule's id is syntax.lex.NAME"),
    ("rule-id", "a disambiguation rule's id is syntax.rule.NAME"),
    ("rule-construct", "a disambiguation rule's constructs are productions"),
    ("rule-status", "a disambiguation rule's status is one of the notation's statuses"),
    ("refusal-row", "a refusal row names a removed production"),
    ("refusal-missing", "every removed production has exactly one refusal row"),
    ("retired-construct", "a retired shape parses as a named production"),
    ("depth-construct", "a nesting-depth row names a production"),
    ("word-production", "a contextual word's productions are productions"),
    ("precedence-construct", "a precedence tier names a production"),
    ("difference-construct", "a difference row names defined constructs or rules"),
    ("difference-kind", "a difference row's kind is one section 16 defines"),
])


class Problem:
    def __init__(self, line, check, message):
        self.line = line
        self.check = check
        self.message = message

    def key(self):
        return (self.line, list(CHECKS).index(self.check), self.message)

    def render(self, path):
        return "%s:%d: %s: %s" % (path, self.line, self.check, self.message)


class Lint:
    def __init__(self, model, headings):
        self.model = model
        self.headings = headings
        self.problems = []
        self.examined = collections.Counter()

    def fail(self, line, check, message):
        assert check in CHECKS, check
        self.problems.append(Problem(line, check, message))

    def saw(self, check, n=1):
        self.examined[check] += n


def lint(model, headings):
    """(sorted problems, Counter of items each check examined)."""
    run = Lint(model, headings)
    for fn in (_check_anomalies, _check_outside_fence, _check_headers, _check_alternatives,
               _check_names, _check_nonterminals, _check_terminals, _check_mentions,
               _check_whitespace, _check_tables, _check_contexts, _check_rules,
               _check_refusals, _check_reference_tables, _check_differences):
        fn(run)
    return sorted(run.problems, key=Problem.key), run.examined


def _check_anomalies(run):
    m = run.model
    for line, kind, message in m.anomalies:
        check = {"fence": "fence", "header": "header", "structure": "structure",
                 "untokenizable": "alternative-text"}[kind]
        run.fail(line, check, message)
    run.saw("fence", len(m.fences))
    run.saw("structure", len(m.productions))
    run.saw("header", len(m.productions))
    notation = [f for f in m.fences if f[0] == "ebnf-notation"]
    if len(notation) != 1:
        run.fail(notation[1][1] if len(notation) > 1 else 1, "fence",
                 "want one ebnf-notation fence, found %d" % len(notation))
    elif not m.statuses:
        run.fail(notation[0][1], "fence", "the ebnf-notation fence defines no `status ::=` set")


def _check_outside_fence(run):
    inside = set()
    for _, start, end in run.model.fences:
        inside.update(range(start, (end or len(run.model.lines)) + 1))
    for i, line in enumerate(run.model.lines, 1):
        if i in inside:
            continue
        run.saw("outside-fence")
        if PRODUCTION_LINE_RE.match(line):
            run.fail(i, "outside-fence", "a production outside an ebnf fence: %r" % line)


def _check_headers(run):
    statuses = set(run.model.statuses)
    for p in run.model.productions:
        run.saw("status")
        if p.status not in statuses:
            run.fail(p.line, "status", "status %r is not one of %s"
                     % (p.status, ", ".join(run.model.statuses)))
        run.saw("spec")
        if p.spec not in run.headings:
            run.fail(p.line, "spec", "no LANGUAGE_SPEC.md heading is %r" % p.spec)
        if p.ref is not None:
            run.saw("ref-format")
            if not REF_RE.match(p.ref):
                run.fail(p.line, "ref-format", "ref %r names no document section, "
                         "tracker issue or design" % p.ref)
        if p.status == "lockdown":
            run.saw("lockdown-ref")
            if p.ref is None:
                run.fail(p.line, "lockdown-ref", "%s is lockdown but has no ref=" % p.name)
        run.saw("node-kind")
        if not NODE_RE.match(p.node):
            run.fail(p.line, "node-kind", "node %r is not an UpperCamelName or -" % p.node)


def _check_alternatives(run):
    for p in run.model.productions:
        multi = len(p.alternatives) > 1
        for a in p.alternatives:
            run.saw("unnamed-alternative")
            if a.name is None and multi:
                run.fail(a.line, "unnamed-alternative",
                         "an alternative of %s has no @name" % p.name)
            if a.name is not None:
                run.saw("alternative-prefix")
                if not a.name.startswith(p.name + "."):
                    run.fail(a.line, "alternative-prefix",
                             "alternative %s is not under %s" % (a.name, p.name))
            run.saw("alternative-text")
            if "@" in re.sub(r'"[^"]*"', "", a.text):
                run.fail(a.line, "alternative-text", "a stray @ in %r" % a.text)
            for item in a.items:
                if not (item in OPERATORS or item[0] in "\"'"
                        or extract.NONTERMINAL_RE.match(item)
                        or extract.TOKEN_KIND_RE.match(item)):
                    run.fail(a.line, "alternative-text", "item %r is not a nonterminal, "
                             "a token kind or a terminal" % item)
            run.saw("parentheses")
            depth = 0
            for item in a.items:
                depth += {"(": 1, ")": -1}.get(item, 0)
                if depth < 0:
                    break
            if depth != 0:
                run.fail(a.line, "parentheses", "unbalanced parentheses in %r" % a.text)


def _check_names(run):
    m = run.model
    for p in m.productions:
        for name, line in [(p.name, p.line)] + [(a.name, a.line) for a in p.alternatives if a.name]:
            run.saw("name-format")
            if not NAME_RE.match(name):
                run.fail(line, "name-format", "%s is not syntax.AREA.CONSTRUCT(.PART)*" % name)
    first = {}
    for name, what, line in m.definitions():
        run.saw("duplicate-name")
        if name in first:
            run.fail(line, "duplicate-name", "%s is also defined as a %s at line %d"
                     % (name, first[name][0], first[name][1]))
        else:
            first[name] = (what, line)


def _check_nonterminals(run):
    m = run.model
    defined = {}
    for p in m.productions:
        if p.nonterminal is None:
            continue
        run.saw("duplicate-nonterminal")
        if p.nonterminal in defined:
            run.fail(p.rule_line, "duplicate-nonterminal", "%s is also defined at line %d"
                     % (p.nonterminal, defined[p.nonterminal]))
        else:
            defined[p.nonterminal] = p.rule_line
    uses = collections.defaultdict(set)
    for p in m.productions:
        for a in p.alternatives:
            for nt in a.nonterminals():
                run.saw("undefined-nonterminal")
                uses[p.nonterminal].add(nt)
                if nt not in defined:
                    run.fail(a.line, "undefined-nonterminal", "%s is not defined" % nt)
    # Reachability, not mere use: a production only an orphan uses, itself
    # included, is as dead as one nothing uses.
    reached = set()
    pending = [nt for _, nt in m.start_symbols]
    while pending:
        nt = pending.pop()
        if nt not in reached:
            reached.add(nt)
            pending.extend(uses[nt])
    for nt, line in sorted(defined.items(), key=lambda kv: kv[1]):
        run.saw("unused-nonterminal")
        if nt not in reached:
            run.fail(line, "unused-nonterminal", "%s is not reachable from a start symbol" % nt)
    if not m.start_symbols:
        run.fail(1, "start-symbol", "section 1 names no start symbols")
    for line, nt in m.start_symbols:
        run.saw("start-symbol")
        if nt not in defined:
            run.fail(line, "start-symbol", "start symbol %s is not defined" % nt)
    head = [p for p in m.productions if p.nonterminal == "head-expr"]
    run.saw("head-expr")
    if not head:
        run.fail(1, "head-expr", "head-expr is not defined")
    elif [a.items for a in head[0].alternatives] != [["expr"]]:
        run.fail(head[0].rule_line, "head-expr", "head-expr must be exactly `expr`")


def _check_terminals(run):
    m = run.model
    kinds = {cells[0] for _, cells in m.rows_of("token-kinds") if cells}
    spellings = {word for _, word in m.keywords}
    for _, cells in m.rows_of("spellings"):
        if len(cells) > 1:
            spellings.update(re.findall(r"`([^`]+)`", cells[1]))
    keywords = {word for _, word in m.keywords}
    words = set()
    for _, cells in m.rows_of("contextual-words"):
        if cells:
            words.update(re.findall(r"`([^`]+)`", cells[0]))
    for a in m.alternatives():
        for item in a.items:
            if extract.TOKEN_KIND_RE.match(item):
                run.saw("token-kind")
                if item not in kinds:
                    run.fail(a.line, "token-kind", "token kind %s is not in the token-kind table"
                             % item)
            elif item.startswith('"'):
                run.saw("spelling")
                if item[1:-1] not in spellings:
                    run.fail(a.line, "spelling", "%s is neither a keyword nor a listed spelling"
                             % item)
            elif item.startswith("'"):
                run.saw("contextual-word")
                word = item[1:-1]
                if word in keywords:
                    run.fail(a.line, "contextual-word", "%s is a keyword, so it is quoted "
                             "with double quotes" % item)
                elif word not in words:
                    run.fail(a.line, "contextual-word", "%s is not in the contextual-word table"
                             % item)


def _check_mentions(run):
    known = {name for name, _, _ in run.model.definitions()}
    for line, name in run.model.mentions:
        run.saw("unknown-name")
        if name not in known:
            run.fail(line, "unknown-name", "%s names nothing this grammar defines" % name)


def _check_whitespace(run):
    for i, line in enumerate(run.model.lines, 1):
        run.saw("trailing-whitespace")
        if line != line.rstrip():
            run.fail(i, "trailing-whitespace", "the line ends in whitespace")


def _check_tables(run):
    m = run.model
    seen = collections.defaultdict(list)
    for t in m.tables:
        run.saw("unknown-table")
        if t.kind == "unknown":
            run.fail(t.line, "unknown-table", "a table with header %s has no known schema"
                     % " | ".join(t.header))
            continue
        seen[t.kind].append(t)
        for line, cells in t.rows:
            run.saw("table-width")
            if len(cells) != len(t.header):
                run.fail(line, "table-width", "the row has %d cells, its header %d"
                         % (len(cells), len(t.header)))
    for kind in extract.TABLE_KINDS:
        run.saw("table-count")
        if len(seen[kind]) == 0:
            run.fail(1, "table-count", "there is no %s table" % kind)
        for t in seen[kind][1:]:
            run.fail(t.line, "table-count", "a second %s table (the first is at line %d)"
                     % (kind, seen[kind][0].line))


def _productions(run):
    return {p.name for p in run.model.productions}


def _check_contexts(run):
    m = run.model
    contexts = m.context_names()
    codes = set(m.context_codes())
    productions = _productions(run)
    for t in m.tables_of(extract.MATRIX):
        run.saw("context-columns")
        if t.header[1:] != contexts:
            run.fail(t.line, "context-columns", "the columns are not the defined contexts: %s"
                     % _first_difference(t.header[1:], contexts))
        rows = {}
        for line, cells in t.rows:
            if not cells:
                continue
            run.saw("context-construct")
            if cells[0] not in productions:
                run.fail(line, "context-construct", "%s is not a production" % cells[0])
            elif cells[0] in rows:
                run.fail(line, "context-construct", "%s already has a row at line %d"
                         % (cells[0], rows[cells[0]]))
            else:
                rows[cells[0]] = line
            for column, cell in zip(t.header[1:], cells[1:]):
                run.saw("context-code")
                if cell not in codes:
                    run.fail(line, "context-code", "cell %r under %s is not a defined code"
                             % (cell, column))
    first = {}
    for line, cells in m.rows_of("contexts"):
        if cells and cells[0] in first:
            run.fail(line, "context-columns", "context %s is also defined at line %d"
                     % (cells[0], first[cells[0]]))
        elif cells:
            first[cells[0]] = line


def _first_difference(got, want):
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else "<none>"
        w = want[i] if i < len(want) else "<none>"
        if g != w:
            return "column %d is %s, the contexts table says %s" % (i + 2, g, w)
    return "same"


def _check_rules(run):
    m = run.model
    productions = _productions(run)
    statuses = set(m.statuses)
    for line, cells in m.rows_of("lexical-rules"):
        run.saw("lexical-rule-id")
        if not (NAME_RE.match(cells[0]) and cells[0].startswith("syntax.lex.")):
            run.fail(line, "lexical-rule-id", "%s is not syntax.lex.NAME" % cells[0])
    for line, cells in m.rows_of("rules"):
        run.saw("rule-id")
        if not (NAME_RE.match(cells[0]) and cells[0].startswith("syntax.rule.")):
            run.fail(line, "rule-id", "%s is not syntax.rule.NAME" % cells[0])
        if len(cells) < 5:
            continue
        for c in _names(cells[1]):
            run.saw("rule-construct")
            if c not in productions:
                run.fail(line, "rule-construct", "%s names no production" % c)
        run.saw("rule-status")
        if cells[4] not in statuses:
            run.fail(line, "rule-status", "status %r is not one of %s"
                     % (cells[4], ", ".join(m.statuses)))


def _names(cell):
    return [c.strip() for c in cell.split(",") if c.strip()]


def _check_refusals(run):
    m = run.model
    removed = [p for p in m.productions if p.status == "removed"]
    removed_names = {p.name for p in removed}
    rows = collections.defaultdict(list)
    for line, cells in m.rows_of("refusals"):
        run.saw("refusal-row")
        if cells[0] not in removed_names:
            run.fail(line, "refusal-row", "%s is not a removed production" % cells[0])
        rows[cells[0]].append(line)
    for p in removed:
        run.saw("refusal-missing")
        if len(rows[p.name]) != 1:
            run.fail(p.line, "refusal-missing", "removed production %s has %d refusal rows, "
                     "want 1" % (p.name, len(rows[p.name])))


def _check_reference_tables(run):
    productions = _productions(run)
    for kind, check, column in (("retired-shapes", "retired-construct", 1),
                                ("depth", "depth-construct", 0),
                                ("contextual-words", "word-production", 2),
                                ("precedence", "precedence-construct", 3)):
        for line, cells in run.model.rows_of(kind):
            if len(cells) <= column:
                continue
            for c in _names(cells[column]):
                run.saw(check)
                if c not in productions:
                    run.fail(line, check, "%s names no production" % c)


def _check_differences(run):
    m = run.model
    known = {name for name, _, _ in m.definitions()}
    kinds = {k for _, k in m.difference_kinds}
    for line, cells in m.rows_of("differences"):
        if len(cells) < 4:
            continue
        for c in _names(cells[0]):
            run.saw("difference-construct")
            if c not in known:
                run.fail(line, "difference-construct", "%s names no construct or rule" % c)
        run.saw("difference-kind")
        if cells[3] not in kinds:
            run.fail(line, "difference-kind", "kind %r is not one of %s"
                     % (cells[3], ", ".join(k for _, k in m.difference_kinds)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("grammar", nargs="?", default=extract.GRAMMAR)
    ap.add_argument("--spec", default=SPEC, help="the spec whose headings spec= names")
    args = ap.parse_args(argv)
    model = extract.extract(args.grammar)
    problems, examined = lint(model, extract.spec_headings(args.spec))
    shown = os.path.relpath(args.grammar)
    for p in problems:
        print(p.render(shown))
    idle = idle_checks(examined)
    for c in idle:
        print("%s: %s: the check examined nothing, so it proves nothing" % (shown, c))
    failures = len(problems) + len(idle)
    alts = model.alternatives()
    print("grammar lint: %s: %d productions, %d alternatives (%d named), %d checks"
          % ("FAIL (%d)" % failures if failures else "ok", len(model.productions),
             len(alts), sum(1 for a in alts if a.name), len(CHECKS)))
    return 1 if failures else 0


def idle_checks(examined):
    return [c for c in CHECKS if not examined[c]]


if __name__ == "__main__":
    sys.exit(main())

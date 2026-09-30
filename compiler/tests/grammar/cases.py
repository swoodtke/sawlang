#!/usr/bin/env python3
"""The parser corpus's hand-written cases and every case's expectation.

    python compiler/tests/grammar/cases.py FILE...          print each case's expectation
    python compiler/tests/grammar/cases.py --write FILE...  write each file's expectations
    python compiler/tests/grammar/cases.py --check          check golden/ and negative/

A case is headed `// case: NAME`, or `// case from refusal-unit: NAME` for a
refusal case's body, parsed from that start symbol. A golden case's
expectation is its dump; a negative case's is the name of the removed
production or rule that refuses it, `parse-error` when nothing named does, or,
for an N cell or a P cell's bare form whose tokens parse as another construct,
that reading's dump.
Every expectation comes from the reference recognizer;
compiler/tests/parse/README.md describes the files.

ENTRY POINTS
    read_cases
    Expectations.golden
    Expectations.negative
    check
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dump  # noqa: E402
import extract  # noqa: E402
import lexdump  # noqa: E402
import recognize  # noqa: E402

PARSE_DIR = os.path.join(extract.REPO, "compiler", "tests", "parse")
GOLDEN = os.path.join(PARSE_DIR, "golden")
NEGATIVE = os.path.join(PARSE_DIR, "negative")
HEADER = "// case: "
UNIT_HEADER = "// case from refusal-unit: "
# Each header's start symbol.
STARTS = {HEADER: "source-file", UNIT_HEADER: "refusal-unit"}
# The files of negative/ that negative.py writes; every other case file there
# is hand-written.
GENERATED_NEGATIVES = ("bare", "cells", "mutations", "removed")
# The expectation file beside a case file, by directory.
SUFFIXES = {GOLDEN: ".dump", NEGATIVE: ".expect"}
PARSE_ERROR = "parse-error"
PARSES_AS = "parses as another construct"
# The line a negative cell case writes when its tokens parse as another
# construct, so that the case says so.
PARSES_AS_NOTE = "// " + PARSES_AS
# The line a hand-written negative case writes when it leaves a bracket
# unclosed. Section 2.7 names that refusal and reports it at the opener, before
# any parse, where the recognizer, which balances no brackets, only fails
# later, so every case that leaves one records the lexical rule at the opener.
UNCLOSED_NOTE = "// an unclosed bracket, refused at its opener"
UNCLOSED_RULE = "syntax.lex.unclosed-bracket"
CELL = "/cell:"
# A P cell's construct written bare in its context, which the cell allows only
# parenthesized.
BARE = "/bare:"
# The brackets `continuation` balances when `Expectations.unsettled` drops the
# tokens after a refusal point, and the name that stands in for a dropped run.
OPENERS = ("LPAREN", "LBRACKET", "LBRACE")
CLOSERS = ("RPAREN", "RBRACKET", "RBRACE")
STAND_IN = "z"
REFUSED_BY = re.compile(r"(\d+:\d+) refused by (syntax\.[a-z-]+\.[a-z-]+)")
NEAR = re.compile(r"^(\d+:\d+) near ")
# A lex error no lexical rule names: the lexer's position (recognize.lex_error_detail).
LEXER_AT = re.compile(r"^Lexer error at (\d+:\d+): ")
# The statements and items a double refusal is looked for in, each parsed with
# what surrounds it in its file (Expectations.unit_trees).
UNITS = ("statement", "top-level-item", "trait-member", "extension-member", "extern-func",
         "field", "enum-case")


class Case:
    """One case: its name, the start symbol it is parsed from, its text, and
    the header line that names it."""
    __slots__ = ("name", "start", "text", "header")

    def __init__(self, name, start, text, header):
        self.name, self.start, self.text, self.header = name, start, text, header


def header_of(line):
    """(start symbol, name) of a header line, or None."""
    for prefix, start in STARTS.items():
        if line.startswith(prefix):
            return start, line[len(prefix):]
    return None


def read_cases(path):
    """[Case] of a case file: each case runs from its header to the line before
    the next header, less the blank line that separates two cases."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    cases = []
    for line in lines:
        head = header_of(line)
        if head is not None:
            cases.append((head, line, []))
        elif cases:
            cases[-1][2].append(line)
        elif line.strip():
            raise ValueError("%s: text before the first case header"
                             % os.path.relpath(path, extract.REPO))
    # A case's text ends in a line break, so its last line and the separating
    # blank line, or the file's end, join back into exactly that text.
    return [Case(name, start, "\n".join(body), line) for (start, name), line, body in cases]


def expectation_path(path):
    return os.path.splitext(path)[0] + SUFFIXES[os.path.dirname(path)]


def expectation_text(cases, results):
    """An expectation file: each case's header, its expectation lines, and a
    blank line between cases."""
    return "\n".join(case.header + "\n" + "\n".join(lines) + "\n"
                     for case, lines in zip(cases, results))


class Problem(Exception):
    """A case whose expectation the recognizer cannot give: a golden case it
    refuses, a negative case it accepts, or a tree that is not unique."""


class Expectations:
    """Every expectation of a case, from the recognizer. A refusal is named by
    a section-13 rule that decides at a token a removed production's reading
    takes (rule_at), else by the removed production whose enabling alone makes
    the text parse, else by the rule the recognizer refuses it with, else
    `parse-error` (compiler/tests/parse/README.md, Refusals)."""

    def __init__(self, model=None):
        self.model = model or extract.extract()
        self.g = recognize.Grammar(self.model)
        self.all_removed = recognize.Grammar(self.model, "all")
        self.removed = [p for p in self.model.productions
                        if p.status == "removed" and p.nonterminal]
        self._single = {}
        # section-13 rule -> the removed productions among its constructs.
        removed_names = {p.name for p in self.removed}
        self.removed_of = {}
        for _, cells in self.model.rows_of("rules"):
            named = [c.strip() for c in cells[1].split(",") if c.strip() in removed_names]
            if named:
                self.removed_of.setdefault(cells[0], []).extend(named)

    def single(self, nonterminal):
        if nonterminal not in self._single:
            self._single[nonterminal] = recognize.Grammar(self.model, {nonterminal})
        return self._single[nonterminal]

    def checked(self, g, text, start):
        return recognize.check(g, text, trees=True, start=start)

    def dump(self, g, text, start, checked):
        try:
            return dump.source_dump(g, text, checked=checked, start=start)
        except dump.Failure as e:
            raise Problem("no dump: %s" % e)

    def golden(self, case):
        """(dump lines, the record's alternatives) of a golden case."""
        checked = self.checked(self.g, case.text, case.start)
        if checked.verdict != "OK":
            raise Problem("refused: %s %s" % (checked.verdict, checked.detail))
        return self.dump(self.g, case.text, case.start, checked), alternatives(checked)

    def refusal(self, text, start, settle=True):
        """(name, "L:C" or None, the alternatives of the tree that enabling a
        removed production gives, or for a depth refusal the section-11 rows
        charged at its token) for a text the recognizer refuses, or None when
        it accepts the text; Problem when a refusal has more than one name."""
        checked = self.checked(self.g, text, start)
        if checked.verdict == "OK":
            return None
        if checked.verdict in ("AMBIGUOUS", "NOTREE"):
            raise Problem("%s %s" % (checked.verdict, checked.detail))
        decided = self.rule_at(text, start)
        if decided is not None:
            self.refused_once(text, start, decided[1])
            return decided[0], decided[1], []
        if self.checked(self.all_removed, text, start).verdict == "OK":
            hits = []
            for p in self.removed:
                enabled = self.checked(self.single(p.nonterminal), text, start)
                if enabled.verdict == "OK":
                    hits.append((p.name, enabled))
            if len(hits) != 1:
                raise Problem("refused, and explained by %s removed productions%s"
                              % (len(hits), "".join(" " + n for n, _ in hits)))
            self.refused_once(text, start, None)
            name, enabled = hits[0]
            return name, None, alternatives(enabled)
        m = REFUSED_BY.search(checked.detail)
        if m:
            others = sorted(set(checked.rules) - {m.group(2)})
            if others and m.group(2) not in recognize.PRECEDENCE:
                # Each rule refuses another reading, and the grammar does not
                # say which refusal a parser reports.
                raise Problem("refused by %s and by %s, each refusing another reading"
                              % (m.group(2), ", ".join(others)))
            # The depth limit, and a stop's rule, decide at their own token,
            # whatever follows it.
            if settle and not checked.decided and m.group(2) not in recognize.NAMED_RULES \
                    and self.unsettled(text, start, m.group(2)):
                return PARSE_ERROR, m.group(1), []
            return m.group(2), m.group(1), list(checked.charged)
        if checked.verdict == "FAIL":
            m = NEAR.match(checked.detail)
        elif checked.verdict == "LEXERR":
            m = LEXER_AT.match(checked.detail)
        else:
            m = None
        return PARSE_ERROR, m.group(1) if m else None, []

    def unsettled(self, text, start, rule):
        """Whether the recognizer's name `rule` for a refusal would change if
        the tokens after the refusal point were dropped or replaced. A rule
        that decides by the token after the construct it refuses has that
        token as its refusal point; the tokens after it are dropped, or each
        run of them replaced by one name, keeping line breaks and the
        brackets that balance the text (`continuation`).
        `let b = a.. == c` is refused by range-open-end only while an operand
        follows the `==`, so its refusal is a parse error. A rule that decides
        by the construct's own tokens decides at them, whatever follows."""
        toks, _, err = recognize.lex_with_docs(text)
        if err is not None:
            return False
        parse = recognize.Parse(self.g, start, recognize.prepare(self.g, toks, start))
        if not parse.accepted or parse.derivations() or parse._forest is None:
            return False
        first = parse.precedence()
        if first is not None:
            # A precedence rule's refusal lies in the head it refuses, and the
            # token after that head decides it only when it is the refused token.
            at, _, end = first
            ends = [end] if at == end else []
        else:
            refused = refused_spans(parse._forest, (start, 0, len(parse.tokens)))
            if not refused:
                return False
            reported = max(why for _, why in refused)
            ends = sorted({key[2] for key, why in refused if why == reported
                           and looks_ahead(key, why)})
        starts = lexdump.line_starts(text)
        for j in ends:
            if j >= len(parse.tokens):
                continue
            point = parse.tokens[j]
            k = max(n for n, t in enumerate(toks) if (t.line, t.column) <= (point.line, point.column))
            after = [t for t in toks[k + 1:] if t.kind != "EOF"]
            if not any(t.kind != "NEWLINE" for t in after):
                continue
            first = starts[after[0].line - 1] + after[0].column - 1
            kept, replaced = [], []
            for t, keep in continuation(after):
                if keep:
                    kept.append(t.value)
                    replaced.append(t.value)
                elif not replaced or replaced[-1] != STAND_IN:
                    replaced.append(STAND_IN)
            for rest in (kept, replaced):
                variant = text[:first] + " ".join(rest).replace(" \n ", "\n") + "\n"
                try:
                    got = self.refusal(variant, start, settle=False)
                except Problem:
                    return True
                if got is None or got[0] != rule:
                    return True
        return False

    def rule_at(self, text, start):
        """(rule, "L:C") when a section-13 rule on a removed production refuses
        a token that ends a construct before it, as cast-target-question
        refuses a `??` after a cast target, and that production's reading
        takes the token: the rule decides there, whatever follows, so it names
        the refusal. The earliest such token counts; None when there is none.
        A rule that chooses between two readings of the same tokens, as
        discard-binding reads `var _ = e` as the removed form, leaves the name
        to the production."""
        toks, _, err = recognize.lex_with_docs(text)
        if err is not None:
            return None
        parse = None
        found = []
        for nt, _, rule in recognize.FILTERS:
            for removed in self.removed_of.get(rule, ()):
                taken = self.taken(removed, toks, start)
                if not taken:
                    continue
                if parse is None:
                    parse = recognize.Parse(self.g, start, recognize.prepare(self.g, toks, start))
                    forest = recognize.Forest(parse.chart)
                for (done, i), ends in sorted(parse.chart.ends.items()):
                    if done != nt:
                        continue
                    for j in sorted(ends):
                        t = parse.tokens[j] if j < len(parse.tokens) else None
                        if t is None or (t.line, t.column) not in taken:
                            continue
                        forest.derivations(nt, i, j)
                        if (j, rule) in forest.refused.get((nt, i, j), ()):
                            found.append((t.line, t.column, rule))
        if not found:
            return None
        line, column, rule = min(found)
        return rule, "%d:%d" % (line, column)

    def refused_once(self, text, start, at):
        """Problem when, with every removed production enabled, a removed
        production's reading around the refusal at `at` ("L:C", or None for
        anywhere) holds a second removed reading: the text is refused twice,
        once inside the refused form, and a parser reading the refused form by
        the rules meets the inner refusal first.
        `while { a } + (x as Int??) { }` needs refused-cast-question inside
        refused-brace-condition's head. A refusal after the reading, as the
        juxtaposed `9` of `n as Int?? 9`, is not inside it. The readings are
        those of the whole text's trees, or for a step-1 name those of each
        statement or item holding `at` (`unit_trees`), so an error elsewhere in
        the file hides nothing."""
        toks, _, err = recognize.lex_with_docs(text)
        if err is not None:
            return
        g = self.all_removed
        parse = recognize.Parse(g, start, recognize.prepare(g, toks, start))
        if at is not None:
            trees = self.unit_trees(parse, at)
        elif parse.accepted:
            trees = parse.derivations()
        else:
            return
        removed = {p.nonterminal: p.name for p in self.removed}
        for tree in trees:
            for d in recognize.walk_real(g, tree):
                if d.nt not in removed or (at is not None and not any(
                        "%d:%d" % (t.line, t.column) == at for t in parse.tokens[d.i:d.j])):
                    continue
                inner = next((k for k in recognize.walk_real(g, d)
                              if k is not d and k.nt in removed), None)
                if inner is not None:
                    raise Problem("refused twice: the reading of %s holds a reading of %s"
                                  % (removed[d.nt], removed[inner.nt]))

    def unit_trees(self, parse, at):
        """The trees, from the whole text's chart, of each statement or item
        (UNITS) whose span holds the token at `at`, complete or not in the rest
        of the file. Taking them from the file's own chart keeps what surrounds
        the unit: the body it stands in, the head around it, and positions."""
        k = next((n for n, t in enumerate(parse.tokens) if "%d:%d" % (t.line, t.column) == at),
                 None)
        if k is None:
            return []
        forest = recognize.Forest(parse.chart)
        out = []
        for (nt, i), ends in sorted(parse.chart.ends.items()):
            if nt in UNITS and i <= k:
                for j in sorted(ends):
                    if j > k:
                        out.extend(forest.derivations(nt, i, j))
        return out

    def taken(self, removed, toks, start):
        """The (line, column) of each token some reading of the removed
        production takes, with that production enabled."""
        p = self.model.by_name()[removed]
        g = self.single(p.nonterminal)
        chart = recognize.Parse(g, start, recognize.prepare(g, toks, start)).chart
        out = set()
        for (done, i), ends in chart.ends.items():
            if done == p.nonterminal:
                for j in ends:
                    out.update((t.line, t.column) for t in chart.tokens[i:j])
        return out

    def negative(self, case):
        """(expectation lines, refusal name or None, alternatives) of a negative
        case: `refuses NAME`, with the recognizer's position when it gives one,
        or, for a cell or bare-form case that says it parses as another
        construct, that reading's dump."""
        opener = unclosed_opener(case.text)
        if UNCLOSED_NOTE in case.text.split("\n") and opener is None:
            raise Problem("says `%s`, but it leaves no bracket unclosed" % UNCLOSED_NOTE)
        if opener is not None:
            # The lexical rule applies before any parse, so it names the text
            # whatever else would refuse it.
            return ["refuses %s at %s" % (UNCLOSED_RULE, opener)], UNCLOSED_RULE, []
        got = self.refusal(case.text, case.start)
        if got is not None:
            name, at, alts = got
            return ["refuses %s%s" % (name, " at " + at if at else "")], name, alts
        construct, ctx = cell_of(case.name)
        if construct is None or PARSES_AS_NOTE not in case.text.split("\n"):
            raise Problem("accepted; a negative case must be refused, unless it is a cell "
                          "or bare-form case that says `%s`" % PARSES_AS_NOTE)
        checked = self.checked(self.g, case.text, case.start)
        if (construct, ctx) in cells(checked):
            raise Problem("accepted, and its tree places %s in %s, which section 12 says "
                          "it may not stand in%s" % (construct, ctx, " bare" if BARE in case.name
                                                     else ""))
        lines = self.dump(self.g, case.text, case.start, checked)
        return [PARSES_AS] + lines, None, alternatives(checked)


def continuation(after):
    """[(token, whether it stays)] for the tokens after a refusal point: a line
    break stays, and so does a bracket that closes one opened before the point
    or at it, so the text stays balanced; every other token goes, a bracket
    pair and what it holds included."""
    depth = 0
    marks = []
    for t in after:
        if t.kind == "NEWLINE" and depth == 0:
            marks.append([t, True, 0])
        elif t.kind in OPENERS:
            depth += 1
            marks.append([t, False, depth])
        elif t.kind in CLOSERS:
            if depth == 0:
                marks.append([t, True, 0])
                continue
            marks.append([t, False, depth])
            depth -= 1
        else:
            marks.append([t, False, depth])
    return [(t, keep) for t, keep, _ in marks]


def looks_ahead(key, why):
    """Whether the refusal `why` made in span `key` was decided by the token
    after the span: by a filter that reads it, or at that token."""
    at, rule = why
    methods = [m for nt, m, r in recognize.FILTERS if nt == key[0] and r == rule]
    return at == key[2] or any(m in recognize.LOOKAHEAD_FILTERS for m in methods)


def refused_spans(forest, key):
    """[(span, (token index, rule))] for each refusal under a span with no
    tree, the walk `Forest.refusals` makes, with the span each was made in."""
    out = []
    seen = {key}
    pending = [key]
    while pending:
        cur = pending.pop()
        if forest.memo.get(cur):
            continue
        out.extend((cur, why) for why in sorted(forest.refused.get(cur, ())))
        for child in sorted(forest.dead.get(cur, ())):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return out


def unclosed_opener(text):
    """"L:C" of a text's first unclosed bracket, where section 2.7 reports it,
    or None when it leaves none or does not lex. A closer that closes an
    opener deeper in the stack leaves the openers above it unclosed; one that
    closes nothing is stray and leaves the stack alone."""
    toks, _, err = recognize.lex_with_docs(text)
    if err is not None:
        return None
    stack = []
    first = None
    for t in toks:
        if t.kind in OPENERS:
            stack.append(t)
        elif t.kind in CLOSERS:
            want = OPENERS[CLOSERS.index(t.kind)]
            j = len(stack) - 1
            while j >= 0 and stack[j].kind != want:
                j -= 1
            if j >= 0:
                if j + 1 < len(stack):
                    first = min(first or stack[j + 1], stack[j + 1], key=_at)
                del stack[j:]
    if stack:
        first = min(first or stack[0], stack[0], key=_at)
    return None if first is None else "%d:%d" % _at(first)


def _at(t):
    return (t.line, t.column)


def cell_of(name):
    """(construct, context) of a cell or bare-form case's name, or (None, None)."""
    for marker in (CELL, BARE):
        base, sep, ctx = name.partition(marker)
        if sep:
            return base, ctx
    return None, None


def alternatives(checked):
    """The alternatives the trees of an accepted text use, its segments' included."""
    out = set()
    for _, parse in checked.parses:
        for d in parse.derivations()[:1]:
            out.update(parse.record(d).alternatives)
    return sorted(out)


def cells(checked):
    out = set()
    for _, parse in checked.parses:
        for d in parse.derivations()[:1]:
            out.update((c, ctx) for c, ctx, _, _ in parse.record(d).cells)
    return out


# Running over files --------------------------------------------------------------

def case_files(root):
    """The hand-written case files under golden/ or negative/, sorted."""
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        stem, ext = os.path.splitext(name)
        if ext == ".saw" and not (root == NEGATIVE and stem in GENERATED_NEGATIVES):
            out.append(os.path.join(root, name))
    return out


def evaluate(exp, path, case):
    """[kind, name, lines or None, problem or None, refusal, alternatives] for
    one case of a file under golden/ or negative/."""
    try:
        if os.path.dirname(path) == GOLDEN:
            lines, alts = exp.golden(case)
            return ["golden", case.name, lines, None, None, alts]
        lines, refusal, alts = exp.negative(case)
        return ["negative", case.name, lines, None, refusal, alts]
    except Problem as e:
        kind = "golden" if os.path.dirname(path) == GOLDEN else "negative"
        return [kind, case.name, None, str(e), None, []]


def run_worker():
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    exp = Expectations()
    files = {}
    for line in sys.stdin:
        path, index = line.rstrip("\n").split("\t")
        if path not in files:
            files[path] = read_cases(path)
        sys.stdout.write(json.dumps(evaluate(exp, path, files[path][int(index)])) + "\n")
    return 0


def evaluate_files(paths, jobs=None):
    """{path: [(Case, result)]} for the case files `paths`, over worker processes."""
    cases = {p: read_cases(p) for p in paths}
    todo = ["%s\t%d" % (p, k) for p in paths for k in range(len(cases[p]))]
    if not todo:
        return {p: [] for p in paths}
    results = recognize.run_workers([os.path.abspath(__file__), "--worker"], todo,
                                    jobs or recognize.default_jobs())
    out = {p: [] for p in paths}
    for job, result in zip(todo, results):
        path, index = job.split("\t")
        out[path].append((cases[path][int(index)], result))
    return out


def file_problems(path, evaluated):
    """Failure lines for a case file's cases: a problem, or a name used twice."""
    rel = os.path.relpath(path, extract.REPO)
    out = []
    seen = set()
    for case, (kind, name, lines, problem, _, _) in evaluated:
        if problem is not None:
            out.append("%s case %s (%s): %s" % (kind, name, rel, problem))
        if name in seen:
            out.append("%s case %s (%s): the name is used twice" % (kind, name, rel))
        seen.add(name)
    return out


def check(jobs=None):
    """(failure lines, counts, results): each hand-written case file's
    expectations equal what the recognizer gives, and each expectation file
    has its case file. `results` are evaluate's lists, for coverage."""
    paths = case_files(GOLDEN) + case_files(NEGATIVE)
    evaluated = evaluate_files(paths, jobs)
    failures = []
    for path in paths:
        failures += file_problems(path, evaluated[path])
        rel = os.path.relpath(expectation_path(path), extract.REPO)
        if not os.path.exists(expectation_path(path)):
            failures.append("%s: missing; run %s --write %s"
                            % (rel, REWRITE, os.path.relpath(path, extract.REPO)))
            continue
        pairs = evaluated[path]
        if any(r[2] is None for _, r in pairs):
            continue
        want = expectation_text([c for c, _ in pairs], [r[2] for _, r in pairs])
        with open(expectation_path(path), encoding="utf-8") as fh:
            have = fh.read()
        if have != want:
            failures.append("%s: the recognizer's expectations differ at %s; run %s --write %s "
                            "and review the diff" % (rel, first_difference(have, want), REWRITE,
                                                     os.path.relpath(path, extract.REPO)))
    failures += orphans(GOLDEN, (".saw", ".dump"))
    failures += orphans(NEGATIVE, (".saw", ".expect"))
    results = [r for p in paths for _, r in evaluated[p]]
    counts = {"golden cases": sum(1 for r in results if r[0] == "golden"),
              "hand-written negative cases": sum(1 for r in results if r[0] == "negative")}
    return failures, counts, results


REWRITE = "compiler/tests/grammar/cases.py"
# The sources a case may be named for besides a GRAMMAR.md name (a section-13
# or lexical rule, a production or an alternative), each owed a case: the
# parser census, design 259's rulings, and the tracker rulings GRAMMAR.md
# records, the table in compiler/tests/parse/README.md.
CENSUS = tuple("census-N%d" % n for n in range(1, 13))
DESIGN_259 = tuple("design259-R%d" % n for n in range(1, 9))
RULINGS = tuple("SL-400-c6-Q%d" % n for n in range(1, 24) if n not in (12, 15)) + (
    "SL-400-c6-U2a", "SL-400-c7", "SL-400-c9",
    "SL-406-c11-1", "SL-406-c11-2", "SL-406-c11-3",
    "SL-406-c17", "SL-406-c22", "SL-406-c23", "SL-406-c25", "SL-408-c1", "SL-409-c1", "SL-414-c1")
# The lexical rules recognize.check names when it refuses a text: the ones it
# applies itself, and the ones the lexer names in its lex error.
NAMED_LEXICAL = ("syntax.lex.ascii-identifier", "syntax.lex.doc-attach", "syntax.lex.module-doc",
                 "syntax.lex.directive", "syntax.lex.escape", "syntax.lex.float-point",
                 "syntax.lex.int-range", "syntax.lex.unterminated-string")


# The section-13 and lexical rules whose decisions refuse nothing: each chooses
# between readings, shapes the tree, or leaves its refusals to a later stage
# or to the productions, so no negative case can show a refusing side.
CHOOSING_RULES = (
    "syntax.lex.double-question", "syntax.lex.longest-match", "syntax.lex.tuple-index",
    "syntax.rule.arm-statement-end", "syntax.rule.borrow-extent",
    "syntax.rule.coalesce-grouping", "syntax.rule.continuation-keywords",
    "syntax.rule.deref-or-multiply", "syntax.rule.flat-chains", "syntax.rule.flat-else-if",
    "syntax.rule.generic-arg-value", "syntax.rule.generic-close-split", "syntax.rule.head-reset",
    "syntax.rule.interpolation-segment", "syntax.rule.leading-minus",
    "syntax.rule.module-inline", "syntax.rule.name-pattern", "syntax.rule.one-call-node",
    "syntax.rule.operator-continuation", "syntax.rule.optional-chain-run",
    "syntax.rule.paren-type", "syntax.rule.postfix-per-hop", "syntax.rule.prefix-or-cast",
    "syntax.rule.reference-position", "syntax.rule.refusal-body",
    "syntax.rule.subscript-arguments", "syntax.rule.subscript-declaration",
    "syntax.rule.tuple-index-dot",
)


def refusing_rules():
    """The rules the recognizer refuses a text by, naming them."""
    return sorted({rule for _, _, rule in recognize.FILTERS} | set(recognize.NAMED_RULES)
                  | set(recognize.STOP_RULES) | set(NAMED_LEXICAL) | {UNCLOSED_RULE})


def removed_of(model):
    """{section-13 rule: the removed productions its constructs column lists},
    which name the refusals of the rules that choose one reading of a text."""
    removed = {p.name for p in model.productions if p.status == "removed" and p.nonterminal}
    out = {}
    for _, cells in model.rows_of("rules"):
        named = [c.strip() for c in cells[1].split(",") if c.strip() in removed]
        if named:
            out.setdefault(cells[0], []).extend(named)
    return out


def coverage(g, results, removed, waivers):
    """(failure lines, counts) for the golden and negative corpus: each removed
    alternative (`removed`, their names and the production each is refused
    as) needs a negative case refused as that production whose tree, with the
    production enabled, uses it; each section-12 N cell a negative case of its
    own, and each P cell one of its bare form; each section-13 rule a golden case named for it; each
    section-13 and lexical rule but CHOOSING_RULES, its refusing side: a
    negative case named for it that records its name, or a removed
    production's; each rule the recognizer refuses by name a negative case
    refused by it; and each
    section-11 row a negative case whose depth refusal it is charged at, the
    opener of the 257th level being that row's construct. Each case's
    name must start with a source it may be named for, and each census item,
    design 259 ruling, listed tracker ruling and lexical rule needs a case of
    either kind. `results` are evaluate's lists, the generated negatives'
    included. A waiver for a covered item, or for one the check does not ask
    for, fails too."""
    table = g.model.tables_of(extract.MATRIX)[0]
    contexts = table.header[1:]
    items = {
        "removed": {name for name, _ in removed},
        "n-cell": {"%s %s" % (row[0], ctx) for _, row in table.rows
                   for ctx, code in zip(contexts, row[1:]) if code == "N"},
        "p-cell": {"%s %s" % (row[0], ctx) for _, row in table.rows
                   for ctx, code in zip(contexts, row[1:]) if code == "P"},
        "rule": set(g.model.rule_ids()),
        "refusal": set(refusing_rules()),
        "refusing-side": (set(g.model.rule_ids()) | set(g.model.lexical_rule_ids()))
                         - set(CHOOSING_RULES),
        "source": set(CENSUS + DESIGN_259 + RULINGS) | set(g.model.lexical_rule_ids()),
        "depth-row": {cells[0] for _, cells in g.model.rows_of("depth")},
    }
    known = {name for name, _, _ in g.model.definitions()} | items["source"]
    production_of = dict(removed)
    removed_names = {p.name for p in g.model.productions if p.status == "removed"}
    used = {kind: set() for kind in items}
    out = ["parsecoverage: %s is listed as choosing, but the recognizer refuses by it" % rule
           for rule in sorted(set(CHOOSING_RULES) & set(refusing_rules()))]
    out += ["parsecoverage: %s is listed as choosing, but is no section-13 or lexical rule" % rule
            for rule in sorted(set(CHOOSING_RULES) - set(g.model.rule_ids())
                               - set(g.model.lexical_rule_ids()))]
    for kind, name, lines, _, refusal, alts in results:
        source = name.split("/")[0]
        if source not in known:
            out.append("parsecoverage: the %s case %s is named for %s, which is no GRAMMAR.md "
                       "name, census item, design 259 ruling or listed tracker ruling"
                       % (kind, name, source))
        if lines is None:
            continue
        used["source"].add(source)
        if kind == "golden":
            used["rule"].add(source)
            continue
        construct, ctx = cell_of(name)
        if construct is not None:
            used["p-cell" if BARE in name else "n-cell"].add("%s %s" % (construct, ctx))
        if refusal is not None:
            used["refusal"].add(refusal)
            used["removed"].update(a for a in alts if production_of.get(a) == refusal)
            if refusal == source or refusal in removed_names:
                used["refusing-side"].add(source)
        if refusal == recognize.DEPTH_RULE:
            used["depth-row"].update(alts)
    counts = {}
    for kind in sorted(items):
        for item in sorted(items[kind]):
            if item not in used[kind] and (kind, item) not in waivers and kind == "refusing-side":
                out.append("parsecoverage: the rule %s shows no refusing side: no negative case "
                           "named for it records its name or a removed form's, and it has no "
                           "waiver and is not in CHOOSING_RULES" % item)
            elif item not in used[kind] and (kind, item) not in waivers:
                out.append("parsecoverage: the %s %s has no %s case and no waiver"
                           % (kind, item, WANTED[kind]))
            elif item in used[kind] and (kind, item) in waivers:
                out.append("parsecoverage: the %s %s is covered, so its waiver goes" % (kind, item))
        for k, item in sorted(waivers):
            if k == kind and item not in items[kind]:
                out.append("parsecoverage: the waived %s %s is not one the check asks for"
                           % (kind, item))
        counts[COUNT_NAMES[kind]] = len(items[kind] & used[kind])
    return out, counts


COUNT_NAMES = {"removed": "covered removed alternatives", "n-cell": "covered N cells",
               "p-cell": "covered P cells", "rule": "rules with a golden case",
               "refusal": "named refusals with a negative case", "source": "sources with a case",
               "depth-row": "section-11 rows with a limit+1 case",
               "refusing-side": "rules with a named refusing case"}
WANTED = {"removed": "negative", "n-cell": "negative", "p-cell": "bare-form negative",
          "rule": "golden", "refusal": "negative", "source": "golden or negative",
          "depth-row": "limit+1 negative", "refusing-side": "named refusing"}


def orphans(root, suffixes):
    """Failure lines for a file of `root` that is neither a case file nor the
    expectation file of one."""
    out = []
    names = sorted(os.listdir(root)) if os.path.isdir(root) else []
    stems = {os.path.splitext(n)[0] for n in names if n.endswith(".saw")}
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext not in suffixes or stem not in stems:
            out.append("%s: not a case file or the expectations of one"
                       % os.path.relpath(os.path.join(root, name), extract.REPO))
    return out


def first_difference(have, want):
    a, b = have.split("\n"), want.split("\n")
    for n in range(max(len(a), len(b))):
        x = a[n] if n < len(a) else "<end>"
        y = b[n] if n < len(b) else "<end>"
        if x != y:
            return "line %d: %r, now %r" % (n + 1, x[:80], y[:80])
    return "the end"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="case files under golden/ or negative/")
    ap.add_argument("--write", action="store_true", help="write each file's expectations")
    ap.add_argument("--check", action="store_true", help="check every hand-written case file")
    ap.add_argument("--jobs", type=int, default=recognize.default_jobs())
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    if args.worker:
        return run_worker()
    if args.check:
        failures, counts, _ = check(args.jobs)
        for f in failures:
            print(f)
        summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
        print("parse cases: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
        return 1 if failures else 0
    paths = [os.path.abspath(p) for p in args.files]
    for p in paths:
        if os.path.dirname(p) not in SUFFIXES:
            ap.error("%s is not a case file under golden/ or negative/" % p)
    evaluated = evaluate_files(paths, args.jobs)
    status = 0
    for path in paths:
        pairs = evaluated[path]
        problems = file_problems(path, pairs)
        for line in problems:
            print(line)
        if args.write:
            if problems:
                status = 1
                print("%s: nothing written" % os.path.relpath(path, extract.REPO))
                continue
            with open(expectation_path(path), "w", encoding="utf-8") as fh:
                fh.write(expectation_text([c for c, _ in pairs], [r[2] for _, r in pairs]))
        else:
            status = status or (1 if problems else 0)
            for case, result in pairs:
                print(case.header)
                print("\n".join(result[2] or ["<%s>" % result[3]]))
                print()
    return status


if __name__ == "__main__":
    sys.exit(main())

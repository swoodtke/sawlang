#!/usr/bin/env python3
"""One in-memory model of GRAMMAR.md, the input of every grammar tool.

    python compiler/tests/grammar/extract.py [GRAMMAR.md] [--json]

The model holds the productions with their alternatives, the notation's status
set, the start symbols, the token and keyword lists, every table the document
defines (sorted by schema), and each `syntax.*` mention. It records what it
could not read as anomalies instead of refusing, so the lint can report each one
at its line. Extraction is deterministic, and `--json` dumps the model for
inspection; nothing it produces is committed.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GRAMMAR = os.path.join(REPO, "GRAMMAR.md")

HEADER_RE = re.compile(
    r'^# (\S+)  status=(\S+)  spec="([^"]*)"  node=(\S+)(?:  ref="([^"]*)")?$')
RULE_RE = re.compile(r"^([a-z][a-z0-9]*(?:-[a-z0-9]+)*) ::= (.*)$")
CONT_RE = re.compile(r"^    \| (.*)$")
ANNOT_RE = re.compile(r"^(.*?)\s+@(\S+)$")
ITEM_RE = re.compile(r'"[^"]+"|\'[^\']+\'|[()|?*+]|ε|[A-Za-z_][A-Za-z0-9_-]*')
NONTERMINAL_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
TOKEN_KIND_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Wider than a well-formed name, so a mistyped one, `syntax.rule.Brace`, is still
# caught as a mention and reported as naming nothing.
MENTION_RE = re.compile(
    r"syntax\.[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?:\.[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)+")
FENCE_RE = re.compile(r"^```(\S*)\s*$")
SEPARATOR_RE = re.compile(r"^\|[-:| ]+\|$")
HEADING_RE = re.compile(r"^(#{1,6}) (.*)$")

# Table schemas, keyed by the header row. The context matrix is the one table
# whose header is `construct` followed by the context names.
SCHEMAS = {
    ("kind", "spelling", "notes"): "token-kinds",
    ("class", "spellings"): "spellings",
    ("word", "position", "production"): "contextual-words",
    ("rule", "statement", "source"): "lexical-rules",
    ("tier", "operators", "associativity", "production"): "precedence",
    ("construct", "why", "write instead"): "refusals",
    ("shape", "parses as", "replacement"): "retired-shapes",
    ("construct", "charge", "held until"): "depth",
    ("context", "position", "restriction"): "contexts",
    ("code", "meaning"): "context-codes",
    ("rule", "constructs", "resolution", "source", "status"): "rules",
    ("construct", "this grammar", "today's parser", "kind", "source"): "differences",
}
MATRIX = "context-matrix"
TABLE_KINDS = tuple(sorted(set(SCHEMAS.values()) | {MATRIX}))


class Alternative:
    """One alternative: its item tokens, its `@name` (None when omitted), line."""

    def __init__(self, production, index, line, text, name, items):
        self.production = production
        self.index = index
        self.line = line
        self.text = text
        self.name = name
        self.items = items
        self.carries = []

    @property
    def effective_name(self):
        """An unnamed single alternative carries its production's name."""
        return self.name or self.production.name

    def nonterminals(self):
        return [t for t in self.items if NONTERMINAL_RE.match(t)]

    def to_json(self):
        return {"line": self.line, "name": self.name, "effective_name": self.effective_name,
                "items": self.items, "carries": self.carries}


class Production:
    def __init__(self, line, name, status, spec, node, ref):
        self.line = line
        self.name = name
        self.status = status
        self.spec = spec
        self.node = node
        self.ref = ref
        self.nonterminal = None
        self.rule_line = None
        self.alternatives = []

    def to_json(self):
        return {"line": self.line, "name": self.name, "status": self.status,
                "spec": self.spec, "node": self.node, "ref": self.ref,
                "nonterminal": self.nonterminal, "rule_line": self.rule_line,
                "alternatives": [a.to_json() for a in self.alternatives]}


class Table:
    def __init__(self, kind, line, section, header, rows):
        self.kind = kind
        self.line = line
        self.section = section
        self.header = header
        self.rows = rows  # [(line, [cell, ...])]

    def to_json(self):
        return {"kind": self.kind, "line": self.line, "section": self.section,
                "header": self.header, "rows": [[ln, cells] for ln, cells in self.rows]}


class Model:
    """Everything the grammar tools read from GRAMMAR.md."""

    def __init__(self, path, text):
        self.path = path
        self.text = text
        self.lines = text.split("\n")
        self.anomalies = []      # [(line, kind, message)]
        self.fences = []         # [(tag, open line, close line or None)]
        self.productions = []
        self.statuses = []       # the notation's closed set, in its order
        self.start_symbols = []  # [(line, nonterminal)]
        self.keywords = []       # [(line, word)]
        self.tables = []
        self.mentions = []       # [(line, name)]
        self.headings = []       # [(line, level, text)]
        self.difference_kinds = []  # [(line, kind)]

    # Lookups ---------------------------------------------------------------

    def by_nonterminal(self):
        out = {}
        for p in self.productions:
            if p.nonterminal and p.nonterminal not in out:
                out[p.nonterminal] = p
        return out

    def by_name(self):
        out = {}
        for p in self.productions:
            out.setdefault(p.name, p)
        return out

    def alternatives(self):
        return [a for p in self.productions for a in p.alternatives]

    def tables_of(self, kind):
        return [t for t in self.tables if t.kind == kind]

    def rows_of(self, kind):
        return [row for t in self.tables_of(kind) for row in t.rows]

    def context_names(self):
        return [cells[0] for _, cells in self.rows_of("contexts") if cells]

    def context_codes(self):
        return [cells[0] for _, cells in self.rows_of("context-codes") if cells]

    def rule_ids(self):
        return [cells[0] for _, cells in self.rows_of("rules") if cells]

    def lexical_rule_ids(self):
        return [cells[0] for _, cells in self.rows_of("lexical-rules") if cells]

    def definitions(self):
        """Every defined `syntax.*` name, as (name, what, line), in document order."""
        out = []
        for p in self.productions:
            out.append((p.name, "production", p.line))
            for a in p.alternatives:
                if a.name is not None:
                    out.append((a.name, "alternative", a.line))
        for ln, cells in self.rows_of("lexical-rules"):
            out.append((cells[0], "lexical rule", ln))
        for ln, cells in self.rows_of("rules"):
            out.append((cells[0], "rule", ln))
        return out

    def to_json(self):
        return {
            "path": os.path.relpath(self.path, REPO) if self.path.startswith(REPO) else self.path,
            "anomalies": [list(a) for a in self.anomalies],
            "fences": [list(f) for f in self.fences],
            "statuses": self.statuses,
            "start_symbols": [list(s) for s in self.start_symbols],
            "keywords": [list(k) for k in self.keywords],
            "difference_kinds": [list(k) for k in self.difference_kinds],
            "productions": [p.to_json() for p in self.productions],
            "tables": [t.to_json() for t in self.tables],
            "mentions": [list(m) for m in self.mentions],
        }


def split_row(line):
    """The cells of a Markdown table row; `\\|` is a literal bar inside a cell."""
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip().replace("\\|", "|") for c in cells[1:-1]]


def tokenize_alternative(text):
    """The items of an alternative's sequence, or None if some text is not one."""
    items = ITEM_RE.findall(text)
    if "".join(items).replace(" ", "") != text.replace(" ", ""):
        return None
    return items


def _read_fences(model):
    """Fence spans, plus the set of line numbers that sit inside a fence."""
    inside = set()
    open_at = None
    tag = None
    for i, line in enumerate(model.lines, 1):
        m = FENCE_RE.match(line)
        if open_at is None:
            if m:
                open_at, tag = i, m.group(1)
        elif line.strip() == "```":
            model.fences.append((tag, open_at, i))
            inside.update(range(open_at, i + 1))
            open_at = None
        elif m and m.group(1):
            # A tagged opener inside an open fence means the earlier one never closed.
            model.fences.append((tag, open_at, None))
            model.anomalies.append((open_at, "fence", "the ```%s fence is not closed" % tag))
            inside.update(range(open_at, i))
            open_at, tag = i, m.group(1)
    if open_at is not None:
        model.fences.append((tag, open_at, None))
        model.anomalies.append((open_at, "fence", "the ```%s fence is not closed" % tag))
        inside.update(range(open_at, len(model.lines) + 1))
    return inside


def _read_productions(model):
    for tag, start, end in model.fences:
        if tag != "ebnf":
            continue
        stop = end if end is not None else len(model.lines) + 1
        cur = None
        for lineno in range(start + 1, stop):
            line = model.lines[lineno - 1]
            if not line.strip():
                _close(model, cur)
                cur = None
                continue
            hm = HEADER_RE.match(line)
            if hm:
                _close(model, cur)
                cur = Production(lineno, *hm.groups())
                model.productions.append(cur)
                continue
            if line.startswith("#"):
                model.anomalies.append((lineno, "header", "malformed header line: %r" % line))
                cur = None
                continue
            rm = RULE_RE.match(line)
            cm = CONT_RE.match(line)
            if rm:
                if cur is None or cur.nonterminal is not None:
                    model.anomalies.append((lineno, "structure", "rule line without a header"))
                    cur = None
                    continue
                cur.nonterminal = rm.group(1)
                cur.rule_line = lineno
                _add_alternative(model, cur, lineno, rm.group(2))
            elif cm:
                if cur is None or cur.nonterminal is None:
                    model.anomalies.append((lineno, "structure", "continuation line without a rule"))
                    continue
                _add_alternative(model, cur, lineno, cm.group(1))
            else:
                model.anomalies.append((lineno, "structure", "unrecognized line in an ebnf block: %r" % line))
        _close(model, cur)


def _close(model, production):
    if production is not None and production.nonterminal is None:
        model.anomalies.append((production.line, "structure", "header without a rule line"))


def _add_alternative(model, production, lineno, text):
    name = None
    seq = text
    am = ANNOT_RE.match(text)
    if am and am.group(2).startswith("syntax."):
        seq, name = am.group(1), am.group(2)
    items = tokenize_alternative(seq)
    if items is None:
        model.anomalies.append((lineno, "untokenizable", "untokenizable text in %r" % seq))
        items = []
    production.alternatives.append(
        Alternative(production, len(production.alternatives), lineno, seq, name, items))


def _read_notation(model):
    for tag, start, end in model.fences:
        if tag != "ebnf-notation" or end is None:
            continue
        for lineno in range(start + 1, end):
            m = re.match(r"^status\s+::= (.*)$", model.lines[lineno - 1])
            if m:
                model.statuses = re.findall(r'"([^"]+)"', m.group(1))


def _read_prose(model, inside):
    section = ""
    bullets = []
    i = 0
    n = len(model.lines)
    while i < n:
        lineno = i + 1
        line = model.lines[i]
        if lineno in inside:
            i += 1
            continue
        hm = HEADING_RE.match(line)
        if hm:
            section = hm.group(2)
            model.headings.append((lineno, len(hm.group(1)), section))
        if line.startswith("|") and i + 1 < n and SEPARATOR_RE.match(model.lines[i + 1]):
            header = split_row(line)
            rows = []
            j = i + 2
            while j < n and model.lines[j].startswith("|"):
                rows.append((j + 1, split_row(model.lines[j])))
                j += 1
            kind = SCHEMAS.get(tuple(header))
            if kind is None and header[:1] == ["construct"]:
                kind = MATRIX
            model.tables.append(Table(kind or "unknown", lineno, section, header, rows))
            i = j
            continue
        if line.startswith("**Start symbols.**"):
            for k, text in _paragraph(model, i):
                for word in re.findall(r"`([a-z][a-z0-9-]*)`", text):
                    model.start_symbols.append((k, word))
        if line.startswith("These words are keywords."):
            j = i
            while j < n and model.lines[j].strip():
                j += 1
            while j < n and not model.lines[j].strip():
                j += 1
            for k, text in _paragraph(model, j):
                for word in re.findall(r"`([^`]+)`", text):
                    model.keywords.append((k, word))
        m = re.match(r"^- `([a-z]+)`: ", line)
        if m:
            bullets.append((lineno, section, m.group(1)))
        i += 1
    # The kinds a differences row may name are the bullets its own section defines.
    sections = {t.section for t in model.tables if t.kind == "differences"}
    model.difference_kinds = [(ln, word) for ln, sec, word in bullets if sec in sections]


def _paragraph(model, i):
    """(line number, text) for each line of the paragraph starting at index i."""
    while i < len(model.lines) and model.lines[i].strip():
        yield i + 1, model.lines[i]
        i += 1


def _read_mentions(model):
    for i, line in enumerate(model.lines, 1):
        for m in MENTION_RE.finditer(line):
            model.mentions.append((i, m.group(0)))


def _derive_carried_statuses(model):
    status = {p.nonterminal: p.status for p in model.productions if p.nonterminal}
    for p in model.productions:
        for a in p.alternatives:
            carried = {status[nt] for nt in a.nonterminals()
                       if status.get(nt) not in (None, "current")}
            a.carries = sorted(carried - {p.status})


def extract_text(text, path="<text>"):
    model = Model(path, text)
    inside = _read_fences(model)
    _read_productions(model)
    _read_notation(model)
    _read_prose(model, inside)
    _read_mentions(model)
    _derive_carried_statuses(model)
    return model


def extract(path=GRAMMAR):
    with open(path, encoding="utf-8") as fh:
        return extract_text(fh.read(), path)


def spec_headings(path):
    """Every Markdown heading of the spec, outside fenced code, as text."""
    heads = set()
    in_fence = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = HEADING_RE.match(line)
            if m:
                heads.add(m.group(2).strip())
    return heads


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("grammar", nargs="?", default=GRAMMAR)
    ap.add_argument("--json", action="store_true", help="dump the whole model as JSON")
    args = ap.parse_args(argv)
    model = extract(args.grammar)
    if args.json:
        json.dump(model.to_json(), sys.stdout, indent=1, sort_keys=True, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    alts = model.alternatives()
    print("productions: %d, alternatives: %d, named: %d"
          % (len(model.productions), len(alts), sum(1 for a in alts if a.name)))
    print("fences: %d, tables: %d, mentions: %d, anomalies: %d"
          % (len(model.fences), len(model.tables), len(model.mentions), len(model.anomalies)))
    for kind in TABLE_KINDS:
        print("  %-17s %d row(s)" % (kind, len(model.rows_of(kind))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

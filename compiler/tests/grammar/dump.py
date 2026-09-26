#!/usr/bin/env python3
"""The canonical AST dump of compiler/tests/parse/README.md, from the recognizer.

    python compiler/tests/grammar/dump.py FILE...        each file's dump
    python compiler/tests/grammar/dump.py --text TEXT    a text's dump

A file the recognizer refuses, lexically or in its parse or an interpolation
segment's, or whose tree is not unique, prints why and exits 1. `render` lays
out one tree; `source_dump` dumps a whole text, its interpolation segments and
doc comments included, and is the entry point the generator and the tests use.

ENTRY POINTS
    source_dump
    render
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import extract  # noqa: E402
import lexdump  # noqa: E402
import recognize  # noqa: E402

# Token kinds whose leaf is the literal's source spelling.
LITERALS = ("INT", "FLOAT", "STRING")
# The leaf a blank interpolation segment, a format placeholder, prints as.
PLACEHOLDER = "{}"
DOC = "Doc"
INDENT = "  "


class Failure(Exception):
    """A text with no tree, or with more than one, which has no dump."""


class Unit:
    """One parse together with the text its tokens were lexed from."""

    def __init__(self, parse, source, origin):
        self.parse = parse
        self.source = source
        self.origin = origin
        self.starts = lexdump.line_starts(source)


# Characters escaped in a leaf, so that a dump line holds exactly one line of
# the dump: the C0 controls and DEL, and the other characters Python's
# str.splitlines ends a line at.
LINE_BREAKING = frozenset([chr(c) for c in range(0x20)] + ["\x7f", "\x85", " ", " "])


def _escape_char(ch):
    return "\\x%02x" % ord(ch) if ord(ch) <= 0xFF else "\\u%04x" % ord(ch)


def escape_leaf(text):
    """A leaf's text on one line: a LINE_BREAKING character as `\\xHH` or
    `\\uHHHH`, and a parenthesis, which would read as the S-expression's own, as
    `\\(` or `\\)`."""
    out = []
    for ch in text:
        if ch in LINE_BREAKING:
            out.append(_escape_char(ch))
        elif ch in "()":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def quote_doc(text):
    """A doc comment line as a quoted string: its text is not source spelling,
    so a quote and a backslash are escaped too."""
    body = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % "".join(_escape_char(c) if c in LINE_BREAKING else c for c in body)


class Builder:
    """Turns recognizer trees into S-expression lists: [label, child...] for a
    node and a str for a leaf."""

    def __init__(self, units, docs, strict=True):
        self.units = {u.origin: u for u in units}
        self.docs = docs
        self.strict = strict

    def tree(self, unit, derivation, file_docs=None):
        targets = doc_targets(unit.parse, derivation, self.docs) if file_docs is not None else {}
        items = self._items(unit, derivation.tree, targets)
        if file_docs:
            items[0][1:1] = [[DOC] + [quote_doc(d.text) for d in file_docs]]
        return items

    def _items(self, unit, t, targets):
        if t[0] == "tok":
            return self._leaf(unit, t) if t[3] else []
        if t[0] == "splice":
            return [x for c in t[1] for x in self._items(unit, c, targets)]
        _, kind, kids, suffix = t
        node = [kind + ("." + suffix if suffix else "")]
        if id(t) in targets:
            node.append([DOC] + [quote_doc(line) for line in targets[id(t)]])
        for c in kids:
            node.extend(self._items(unit, c, targets))
        return [node]

    def _leaf(self, unit, t):
        tokens = unit.parse.tokens
        tok = tokens[t[2]]
        if tok.kind == "INTERP_STRING":
            return self._interpolation(unit, tok)
        if tok.kind in LITERALS:
            after = tokens[t[2] + 1] if t[2] + 1 < len(tokens) else None
            return [escape_leaf(lexdump.raw_spelling(unit.source, unit.starts, tok, after))]
        return [escape_leaf(t[1])]

    def _interpolation(self, unit, tok):
        """An interpolated string's segments: each literal run as written, in
        quotes, and each expression segment's own tree."""
        at = unit.starts[tok.line - 1] + tok.column
        out = []
        pos = 0
        raw = tok.value
        for seg in tok.segments:
            if seg.kind != "expr":
                continue
            brace = unit.starts[seg.line - 1] + seg.column - 1 - at
            if brace > pos:
                out.append('"%s"' % escape_leaf(raw[pos:brace]))
            pos = brace + len(seg.text) + 2
            origin = "%s%d:%d" % (unit.origin + "/" if unit.origin else "", seg.line, seg.column)
            out.extend(self._segment(self.units[origin]))
        if pos < len(raw):
            out.append('"%s"' % escape_leaf(raw[pos:]))
        return out

    def _segment(self, unit):
        derivations = unit.parse.derivations()
        if len(derivations) != 1 and (self.strict or not derivations):
            raise Failure("segment %s: %d tree(s)" % (unit.origin, len(derivations)))
        items = self._items(unit, derivations[0].tree, {})
        return items or [PLACEHOLDER]


def doc_targets(parse, derivation, docs):
    """{id of a node tree: its `///` lines} for each documented declaration."""
    starts = {}
    for d in recognize.walk_real(parse.g, derivation):
        name = parse.g.alternative(d.nt, d.ai).effective_name
        if name == recognize.TEST_ONLY_DECLARATION:
            inner = [k for k in d.kids if isinstance(k, recognize.Derivation)
                     and k.nt == "declaration-item"]
            if inner and parse.g.alternative(inner[0].nt, inner[0].ai).effective_name \
                    in recognize.DOCUMENTED:
                starts.setdefault(d.i, _node_of(parse.g, inner[0]))
        elif name in recognize.DOCUMENTED:
            starts.setdefault(d.i, _node_of(parse.g, d))
    out = {}
    for first, last, lines in doc_runs(docs):
        after = next((k for k, t in enumerate(parse.tokens)
                      if t.line > last and t.kind != "NEWLINE"), None)
        if after in starts:
            out[id(starts[after].tree)] = lines
    return out


def _node_of(g, d):
    """The derivation that builds the node of a documented declaration: the
    declaration itself, or the last node its `node=-` alternative holds."""
    while g.info[d.nt].node == "-":
        d = [k for k in d.kids if isinstance(k, recognize.Derivation)
             and not k.nt.startswith("__")][-1]
    return d


def doc_runs(docs):
    """[(first line, last line, [text...])] for each run of `///` lines."""
    runs = []
    for dc in docs:
        if dc.kind != "doc":
            continue
        if runs and dc.line == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], dc.line, runs[-1][2] + [dc.text])
        else:
            runs.append((dc.line, dc.line, [dc.text]))
    return runs


def height(item):
    if isinstance(item, str):
        return 0
    return 1 + max([height(c) for c in item[1:]] or [0])


def render(item, depth=0):
    """The lines of one S-expression. A node whose children are leaves, or nodes
    of leaves, takes one line. Any other node opens a line with its Kind and the
    leaves before its first node child, and puts each later child on a line of
    its own, one indent deeper; its `)` ends its last line."""
    pad = INDENT * depth
    if isinstance(item, str):
        return [pad + item]
    if height(item) <= 2:
        return [pad + flat(item)]
    head = [item[0]]
    k = 1
    while k < len(item) and isinstance(item[k], str):
        head.append(item[k])
        k += 1
    lines = [pad + "(" + " ".join(head)]
    for c in item[k:]:
        lines.extend(render(c, depth + 1))
    lines[-1] += ")"
    return lines


def flat(item):
    if isinstance(item, str):
        return item
    return "(" + " ".join([item[0]] + [flat(c) for c in item[1:]]) + ")"


def source_dump(g, text=None, path=None, checked=None):
    """The dump of a whole source text as a list of lines. It raises Failure
    with check_source's detail, the refusing rule's id among it, for any text
    the recognizer does not accept with exactly one tree, a lexical refusal
    such as syntax.lex.doc-attach included. `checked` is the text's
    recognize.check result, for a caller that checked it already."""
    if text is None:
        # newline="" keeps a CRLF inside a string literal as written.
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    if checked is None:
        checked = recognize.check(g, None if path else text, trees=True, path=path)
    if checked.verdict != "OK":
        raise Failure("%s: %s" % (checked.verdict, checked.detail))
    units = []
    for origin, parse in checked.parses:
        units.append(Unit(parse, _segment_text(units, origin) if origin else text, origin))
    builder = Builder(units, checked.docs)
    tree = builder.tree(units[0], units[0].parse.derivations()[0],
                        [d for d in checked.docs if d.kind == "module"])
    lines = []
    for item in tree:
        lines.extend(render(item))
    return lines


def source_units(g, text):
    """([Unit] for the file and each interpolation segment, doc comments), for
    a text that lexes; a segment that does not lex raises lexdump.LexError."""
    toks, docs, err = recognize.lex_with_docs(text)
    if err is not None:
        raise Failure(recognize.lex_error_detail(err))
    parse = recognize.Parse(g, "source-file", recognize.prepare(g, toks))
    units = [Unit(parse, text, "")]
    for origin, p in recognize.segment_parses(g, parse)[1:]:
        units.append(Unit(p, _segment_text(units, origin), origin))
    return units, docs


def report(g, label, text, start="source-file", record=False):
    """(lines, whether every parse has exactly one tree): each parse's tree
    count and the dump of each of its trees, indented, then its coverage record
    when `record` is set. A source file's interpolation segments are parses of
    their own, and each file tree shows its segments' first trees in place."""
    import json
    try:
        if start == "source-file":
            units, docs = source_units(g, text)
        else:
            parse = recognize.Parse(g, start, recognize.text_tokens(g, text, start))
            units, docs = [Unit(parse, text, "")], []
    except Failure as e:
        return ["%s: LEX ERROR: %s" % (label, e)], False
    except lexdump.LexError as e:
        return ["%s: LEX ERROR: %s" % (label, recognize.lex_error_detail(e))], False
    builder = Builder(units, docs, strict=False)
    lines = []
    unique = True
    for unit in units:
        name = label if not unit.origin else "%s segment %s" % (label, unit.origin)
        derivations = unit.parse.derivations()
        if not unit.parse.accepted:
            lines.append("%s: NO PARSE" % name)
        elif not derivations:
            lines.append("%s: REFUSED: %s" % (name, unit.parse.refusal()
                                               or "no rule refused a tree"))
        else:
            lines.append("%s: %d tree(s)%s" % (name, len(derivations),
                                               "" if len(derivations) == 1 else " AMBIGUOUS"))
        for d in derivations:
            file_docs = [x for x in docs if x.kind == "module"] if not unit.origin else None
            try:
                items = builder.tree(unit, d, file_docs)
            except Failure as e:
                items = ["<%s>" % e]
            for item in items:
                lines.extend(render(item, 1))
            if record:
                lines.append(json.dumps(unit.parse.record(d).to_json(), sort_keys=True))
        unique = unique and len(derivations) == 1
    return lines, unique


def _segment_text(units, origin):
    """The text of the segment at `origin`, from the unit that holds it."""
    parent, _, own = origin.rpartition("/")
    line, column = (int(x) for x in own.split(":"))
    for u in units:
        if u.origin == parent:
            for tok in u.parse.tokens:
                for seg in tok.segments or ():
                    if seg.kind == "expr" and (seg.line, seg.column) == (line, column):
                        return seg.text
    raise KeyError(origin)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--text", help="dump this text instead of files")
    args = ap.parse_args(argv)
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    g = recognize.Grammar(extract.extract())
    jobs = [("<text>", args.text, None)] if args.text is not None else []
    jobs += [(p, None, p) for p in args.files]
    status = 0
    for label, text, path in jobs:
        try:
            print("\n".join(source_dump(g, text, path)))
        except Failure as e:
            print("%s: no dump: %s" % (label, e))
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())

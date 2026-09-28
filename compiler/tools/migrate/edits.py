"""Source text as tokens with offsets, and non-overlapping text edits over it.

Anchors come from the typed AST as (line, column) pairs; every edit is placed
by finding the token that starts there, so an edit never depends on reading
text around an anchor.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if os.path.join(REPO, "sawc") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "sawc"))

from lexer import Lexer, TokenType  # noqa: E402

SEGMENT_DELTA = 1
OPENERS = {TokenType.LPAREN: TokenType.RPAREN, TokenType.LBRACKET: TokenType.RBRACKET,
           TokenType.LBRACE: TokenType.RBRACE}


class Tok:
    __slots__ = ("off", "kind", "value", "line", "col", "end", "depth")

    def __init__(self, off, kind, value, line, col, end, depth):
        self.off, self.kind, self.value = off, kind, value
        self.line, self.col, self.end, self.depth = line, col, end, depth

    def __repr__(self):
        return "Tok(%s %r @%d:%d)" % (self.kind.name, self.value, self.line, self.col)


class Source:
    """One file's text, its line starts and its tokens, interpolation
    segments included (each with the depth of its string nesting)."""

    def __init__(self, text):
        self.text = text
        self.starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.starts.append(i + 1)
        self.tokens = []
        self._lex(text, 1, 1, 0)
        self.tokens.sort(key=lambda t: (t.off, t.depth))
        self.by_off = {}
        for i, t in enumerate(self.tokens):
            self.by_off.setdefault(t.off, i)

    def offset(self, line, col):
        return self.starts[line - 1] + col - 1

    def _lex(self, text, line0, col0, depth):
        """Lex `text`, whose first character sits at (line0, col0)."""
        def place(line, col):
            return line0 + line - 1, (col0 + col - 1) if line == 1 else col

        for t in Lexer(text).tokenize():
            if t.type == TokenType.EOF:
                continue
            line, col = place(t.line, t.column)
            self.tokens.append(Tok(self.offset(line, col), t.type, t.value, line, col, None, depth))
            if t.type == TokenType.INTERP_STRING:
                for seg in t.segments or []:
                    if seg.kind == "expr":
                        sline, scol = place(seg.line, seg.column)
                        self._lex(seg.text, sline, scol + SEGMENT_DELTA, depth + 1)

    def index_at(self, line, col):
        """The index of the token starting at (line, col), or None."""
        return self.by_off.get(self.offset(line, col))

    def match_close(self, i):
        """The index of the bracket closing the opener at `i`, or None."""
        opener = self.tokens[i]
        want = OPENERS.get(opener.kind)
        if want is None:
            return None
        depth, level = 0, opener.depth
        for j in range(i, len(self.tokens)):
            t = self.tokens[j]
            if t.depth != level:
                continue
            if t.kind == opener.kind:
                depth += 1
            elif t.kind == want:
                depth -= 1
                if depth == 0:
                    return j
        return None

    def prev(self, i):
        """The previous token at the same string depth, or None."""
        level = self.tokens[i].depth
        for j in range(i - 1, -1, -1):
            if self.tokens[j].depth == level:
                return j
            if self.tokens[j].depth < level:
                return None
        return None

    def next(self, i):
        level = self.tokens[i].depth
        for j in range(i + 1, len(self.tokens)):
            if self.tokens[j].depth == level:
                return j
            if self.tokens[j].depth < level:
                return None
        return None

    def end_of(self, i):
        """The offset just past token `i`, for the tokens whose source spelling
        is their value (names, keywords, punctuation, numbers)."""
        t = self.tokens[i]
        if t.kind in (TokenType.STRING, TokenType.INTERP_STRING):
            return self._string_end(t.off)
        nxt = self.next(i)
        text = self.text
        k = t.off + len(str(t.value)) if t.value is not None else t.off + 1
        if text[t.off:k] == str(t.value):
            return k
        # Numbers keep their spelling in the source; scan the word.
        k = t.off
        stop = self.tokens[nxt].off if nxt is not None else len(text)
        while k < stop and not text[k].isspace() and text[k] not in ")]},;":
            k += 1
        return k

    def _string_end(self, off):
        text = self.text
        assert text[off] == '"'
        k, depth = off + 1, 0
        while k < len(text):
            ch = text[k]
            if ch == "\\":
                k += 2
                continue
            if depth == 0 and ch == '"':
                return k + 1
            if ch == "{":
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
            elif ch == '"' and depth:
                k = self._string_end(k)
                continue
            k += 1
        return k

    def line_text(self, line):
        start = self.starts[line - 1]
        end = self.starts[line] - 1 if line < len(self.starts) else len(self.text)
        return self.text[start:end]


class Edit:
    __slots__ = ("start", "end", "text", "site")

    def __init__(self, start, end, text, site=None):
        self.start, self.end, self.text, self.site = start, end, text, site

    def __repr__(self):
        return "Edit(%d, %d, %r)" % (self.start, self.end, self.text)


class Overlap(Exception):
    pass


def apply(text, edits):
    """`text` with every edit applied; overlapping edits raise Overlap. Two
    insertions at one offset apply in the order given."""
    return apply_mapped(text, edits)[0]


def apply_mapped(text, edits):
    """(new text, spans): `apply`, plus the (start, end) offsets in the new
    text where each edit's text landed, in the order the edits were given."""
    ordered = sorted(enumerate(edits), key=lambda p: (p[1].start, p[1].end, p[0]))
    out, cursor, pos = [], 0, 0
    spans = [None] * len(edits)
    for i, e in ordered:
        if e.start < cursor:
            raise Overlap("%r overlaps an earlier edit" % (e,))
        out.append(text[cursor:e.start])
        pos += e.start - cursor
        spans[i] = (pos, pos + len(e.text))
        out.append(e.text)
        pos += len(e.text)
        cursor = e.end
    out.append(text[cursor:])
    return "".join(out), spans

"""Tokens and doc comments from the self-hosted lexer, read back from its dump.

`lex_file` and `lex_text` run `sawc2 lex` and `sawc2 lex --docs` and return the
records as objects: a `Token` has the dump's kind name, its text (unescaped),
its 1-based position, an integer's width suffix, and an interpolated string's
segments. The record format is compiler/lex/README.md's. A lex error raises
`LexError`. `raw_spelling` recovers a literal's source spelling, which the dump
normalizes. `ensure_sawc2` builds the driver when it is missing or older than
its sources or the frozen compiler that builds it.

ENTRY POINTS
    lex_file
    lex_text
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

# What a fresh sawc2 depends on: the stages it is built from, and the frozen
# compiler that builds it.
SAWC2_SOURCES = (os.path.join(COMPILER, "lex"), os.path.join(COMPILER, "driver"),
                 os.path.join(REPO, "sawc"))
LEX_TIMEOUT = 60


class Token:
    __slots__ = ("kind", "value", "line", "column", "suffix", "segments")

    def __init__(self, kind, value, line, column, suffix=None, segments=None):
        self.kind = kind
        self.value = value
        self.line = line
        self.column = column
        self.suffix = suffix
        self.segments = segments

    def __repr__(self):
        return "Token(%s %r %d:%d)" % (self.kind, self.value, self.line, self.column)


class Segment:
    """One segment of an interpolated string: `text` (decoded) or `expr` (raw)."""
    __slots__ = ("kind", "text", "line", "column")

    def __init__(self, kind, text, line=0, column=0):
        self.kind = kind
        self.text = text
        self.line = line
        self.column = column


class Doc:
    """One `///` (kind `doc`) or `//!` (kind `module`) line."""
    __slots__ = ("kind", "line", "column", "text")

    def __init__(self, kind, line, column, text):
        self.kind = kind
        self.line = line
        self.column = column
        self.text = text


class LexError(Exception):
    def __init__(self, line, column, message):
        Exception.__init__(self, "%d:%d %s" % (line, column, message))
        self.line = line
        self.column = column
        self.message = message


_ESCAPES = {"\\": 0x5C, "n": 0x0A, "t": 0x09, "r": 0x0D, "0": 0x00}


def unescape(field):
    """The text a dump field escapes at the byte level."""
    if "\\" not in field:
        return field
    raw = field.encode("utf-8")
    out = bytearray()
    k = 0
    while k < len(raw):
        b = raw[k]
        if b != 0x5C:
            out.append(b)
            k += 1
            continue
        c = chr(raw[k + 1])
        if c == "x":
            out.append(int(raw[k + 2:k + 4].decode("ascii"), 16))
            k += 4
        else:
            out.append(_ESCAPES[c])
            k += 2
    return out.decode("utf-8")


def _position(field):
    line, column = field.split(":")
    return int(line), int(column)


def parse_tokens(dump):
    """The tokens of a `sawc2 lex` dump; raises LexError for an ERROR record."""
    out = []
    for record in dump.split("\n"):
        if not record:
            continue
        fields = record.split("\t")
        kind = fields[0]
        line, column = _position(fields[1])
        if kind == "ERROR":
            # The message is prose, written as it is, not an escaped field.
            raise LexError(line, column, "\t".join(fields[2:]))
        value = unescape(fields[2]) if len(fields) > 2 else ""
        if kind == "INTERP_STRING":
            segments = []
            for f in fields[3:]:
                if f.startswith("T:"):
                    segments.append(Segment("text", unescape(f[2:])))
                else:
                    sline, scol, text = f[2:].split(":", 2)
                    segments.append(Segment("expr", unescape(text), int(sline), int(scol)))
            out.append(Token(kind, value, line, column, segments=segments))
        else:
            out.append(Token(kind, value, line, column,
                             suffix=fields[3] if len(fields) > 3 else None))
    return out


def parse_docs(dump):
    out = []
    for record in dump.split("\n"):
        if not record:
            continue
        fields = record.split("\t")
        line, column = _position(fields[1])
        out.append(Doc(fields[2], line, column, unescape(fields[3]) if len(fields) > 3 else ""))
    return out


_built = []


def ensure_sawc2():
    """The path of a sawc2 at least as new as everything it is built from."""
    if _built:
        return _built[0]
    if not os.path.exists(build.SAWC2) or _newest(SAWC2_SOURCES) > os.path.getmtime(build.SAWC2):
        ok, output = build.build_sawc2()
        if not ok:
            raise RuntimeError("sawc2 does not build: %s" % output.strip().split("\n")[0])
    _built.append(build.SAWC2)
    return build.SAWC2


def _newest(roots):
    newest = 0.0
    for root in roots:
        for d, _, files in os.walk(root):
            newest = max(newest, os.path.getmtime(d))
            for f in files:
                if not f.startswith("."):
                    newest = max(newest, os.path.getmtime(os.path.join(d, f)))
    return newest


def _run(*args):
    r = subprocess.run([ensure_sawc2(), "lex"] + list(args), capture_output=True,
                       timeout=LEX_TIMEOUT)
    if r.returncode not in (0, 1):
        raise RuntimeError("sawc2 lex %s: exit %d: %s"
                           % (" ".join(args), r.returncode, r.stdout.decode("utf-8", "replace")))
    return r.returncode, r.stdout.decode("utf-8")


def lex_file(path):
    """(tokens, doc comments) of the file; raises LexError."""
    code, dump = _run(path)
    tokens = parse_tokens(dump)
    if code != 0:
        raise RuntimeError("sawc2 lex %s: exit %d without an ERROR record" % (path, code))
    _, docs = _run("--docs", path)
    return tokens, parse_docs(docs)


_cache = {}


def lex_text(text):
    """(tokens, doc comments) of a text; raises LexError. Results are cached, since
    the same interpolation segment recurs. sawc2 reads only files, so the text
    goes through a directory that is removed however the lex ends."""
    if text in _cache:
        hit = _cache[text]
        if isinstance(hit, LexError):
            raise hit
        return hit
    with tempfile.TemporaryDirectory(prefix="sawgrammar-") as scratch:
        path = os.path.join(scratch, "text.saw")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            result = lex_file(path)
        except LexError as e:
            _cache[text] = e
            raise
    _cache[text] = result
    return result


def line_starts(source):
    """The offset of each line's first character, for 1-based lines."""
    starts = [0]
    for k, ch in enumerate(source):
        if ch == "\n":
            starts.append(k + 1)
    return starts


# The characters a number literal can be spelled with; `.` only between digits.
NUMBER_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_.")


def raw_spelling(source, starts, tok, after=None):
    """A literal token's spelling in `source`, whose `line_starts` are `starts`.
    The dump strips a number's underscores, lowercases its base prefix, and
    decodes a string, so the spelling comes from the text. `after` is the next
    token, which bounds a number: the lexer's own reading says where it ends,
    whatever underscores it took."""
    at = starts[tok.line - 1] + tok.column - 1
    if tok.kind == "STRING":
        k = at + 1
        while source[k] != '"':
            k += 2 if source[k] == "\\" else 1
        return source[at:k + 1]
    if tok.kind == "INTERP_STRING":
        return '"%s"' % tok.value
    if tok.kind in ("INT", "FLOAT"):
        end = len(source)
        if after is not None and after.line == tok.line:
            end = starts[after.line - 1] + after.column - 1
        k = at
        while k < end and source[k] in NUMBER_CHARS \
                and not (source[k] == "." and not source[k + 1:k + 2].isdigit()):
            k += 1
        spelled = source[at:k]
        if spelled.replace("_", "").lower() != (tok.value + (tok.suffix or "")).lower():
            raise RuntimeError("%d:%d: %r does not spell %r"
                               % (tok.line, tok.column, spelled, tok.value))
        return spelled
    return tok.value

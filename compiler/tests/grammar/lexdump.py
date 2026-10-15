"""Tokens and doc comments from the self-hosted lexer, read back from its dump.

`lex_file` and `lex_text` run `sawc2 lex` and `sawc2 lex --docs` and return the
records as objects: a `Token` has the dump's kind name, its text (unescaped),
its 1-based position, an integer's width suffix, and an interpolated string's
segments. The record format is compiler/lex/README.md's. A lex error raises
`LexError`. `raw_spelling` recovers a literal's source spelling, which the dump
normalizes. `ensure_sawc2` builds the driver when it is missing or older than
its sources or the frozen compiler that builds it.

`lex_files` and `lex_texts` lex many at once through `sawc2 lex @LIST`, so a
worker that knows its inputs runs one sawc2 process for all of them.

ENTRY POINTS
    lex_file
    lex_text
    lex_files
    lex_texts
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

# What a fresh sawc2 depends on: every stage it is built from, its driver, the
# seed that builds Stage 1, the std the stages compile and the runtime they
# link.
SAWC2_SOURCES = tuple(os.path.join(REPO, rel) for _, rel in build.STAGE_PACKAGES) + (
    os.path.join(COMPILER, "driver"), build.SEED_DIR, build.STD_ROOT, build.RT_ROOT)
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
    """A lex error: its position, message, the id of the rule that refuses
    (`parse-error` when none names it) and a hint, or ""."""

    def __init__(self, line, column, message, rule="parse-error", hint=""):
        Exception.__init__(self, "%d:%d %s" % (line, column, message))
        self.line = line
        self.column = column
        self.message = message
        self.rule = rule
        self.hint = hint


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
            # ERROR, the position, the message, the rule's id, then the hint
            # when there is one; the prose is written as it is, not escaped.
            raise LexError(line, column, fields[2] if len(fields) > 2 else "",
                           fields[3] if len(fields) > 3 else "parse-error",
                           fields[4] if len(fields) > 4 else "")
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
    """The path of a sawc2 at least as new as everything it is built from. A
    binary handed down from a runner above is used as it is: that runner
    keeps it fresh, and two processes building it at once would race."""
    if _built:
        return _built[0]
    if build.handed_down():
        if not os.path.exists(build.SAWC2):
            raise RuntimeError("SAWC2_BINARY names %s, which does not exist" % build.SAWC2)
    elif not os.path.exists(build.SAWC2) or _newest(SAWC2_SOURCES) > os.path.getmtime(build.SAWC2):
        ok, output = build.build_sawc2()
        if not ok:
            raise RuntimeError("sawc2 does not build: %s" % output.strip().split("\n")[0])
    _built.append(build.SAWC2)
    return build.SAWC2


def candidate_sawc2():
    """The sawc2 that candidate texts are lexed with, those the generator and
    the mutator make and lex as they go, when a runner above chose one apart
    (SAWC2_CANDIDATE_BINARY: the fixpoint lane's default mode hands Stage 2
    here and its twin to everything else); None to use `ensure_sawc2`'s."""
    return os.environ.get("SAWC2_CANDIDATE_BINARY") or None


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
    """(tokens, doc comments) of the file; raises LexError. A file `lex_files`
    has lexed is answered from that, once."""
    if path in _prefetched:
        return _answer(_prefetched.pop(path))
    code, dump = _run(path)
    tokens = parse_tokens(dump)
    if code != 0:
        raise RuntimeError("sawc2 lex %s: exit %d without an ERROR record" % (path, code))
    _, docs = _run("--docs", path)
    return tokens, parse_docs(docs)


def _lexed(path, code, dump, docs_code, docs):
    """What `lex_file` makes of the two dumps and their statuses: (tokens, doc
    comments), or the LexError or RuntimeError it would raise."""
    if code not in (0, 1):
        return RuntimeError("sawc2 lex %s: exit %d: %s" % (path, code, dump))
    try:
        tokens = parse_tokens(dump)
    except LexError as e:
        return e
    if code != 0:
        return RuntimeError("sawc2 lex %s: exit %d without an ERROR record" % (path, code))
    if docs_code not in (0, 1):
        return RuntimeError("sawc2 lex --docs %s: exit %d: %s" % (path, docs_code, docs))
    return tokens, parse_docs(docs)


def _answer(lexed):
    if isinstance(lexed, Exception):
        raise lexed
    return lexed


def lex_list(paths, scratch):
    """{path: what `_lexed` makes of it} for every path, from one `sawc2 lex
    @LIST` call over a listing written into the directory `scratch`."""
    listing = os.path.join(scratch, "list.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("".join(p + "\n" for p in paths))
    r = subprocess.run([ensure_sawc2(), "lex", "@" + listing], capture_output=True,
                       timeout=LEX_TIMEOUT * max(1, len(paths) // 100))
    if r.returncode not in (0, 1, 2):
        raise RuntimeError("sawc2 lex @%s: exit %d: %s" % (listing, r.returncode, r.stdout[-300:]))
    return {path: _lexed(path, *parts) for path, parts in frames(r.stdout.decode("utf-8")).items()}


def frames(dump):
    """{path: (status, token dump, docs status, doc dump)} of a `sawc2 lex
    @LIST` dump, each dump the text the single-file command prints."""
    lines = dump.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = {}
    k = 0
    while k < len(lines):
        if not lines[k].startswith("FILE\t"):
            raise RuntimeError("sawc2 lex @LIST: expected a FILE line, got %r" % lines[k][:120])
        path = lines[k][len("FILE\t"):]
        parts = []
        k += 1
        for closer in ("DOCS\t", "END\t"):
            body = []
            while k < len(lines) and not lines[k].startswith(closer):
                body.append(lines[k])
                k += 1
            if k == len(lines):
                raise RuntimeError("sawc2 lex @LIST: %s has no %s line" % (path, closer.strip()))
            parts += [int(lines[k][len(closer):]), "".join(line + "\n" for line in body)]
            k += 1
        out[path] = tuple(parts)
    return out


_prefetched = {}


def lex_files(paths):
    """Lex every file of `paths` with one sawc2 process, so that `lex_file`
    answers each from that; the answers are those it gives a file alone
    (pinned by compiler/tests/parallel_order.py)."""
    todo = [p for p in dict.fromkeys(paths) if p not in _prefetched]
    if len(todo) > 1:
        with tempfile.TemporaryDirectory(prefix="sawgrammar-") as scratch:
            _prefetched.update(lex_list(todo, scratch))


def lex_texts(texts):
    """Lex every text of `texts` not yet cached with one sawc2 process, so
    that `lex_text` answers each from the cache as it would alone."""
    todo = [t for t in dict.fromkeys(texts) if t not in _cache]
    if len(todo) <= 1:
        return
    with tempfile.TemporaryDirectory(prefix="sawgrammar-") as scratch:
        paths = []
        for k, text in enumerate(todo):
            paths.append(os.path.join(scratch, "text%d.saw" % k))
            with open(paths[-1], "w", encoding="utf-8") as fh:
                fh.write(text)
        lexed = lex_list(paths, scratch)
    for text, path in zip(todo, paths):
        # A RuntimeError is not an answer to keep: `lex_text` meets it again.
        if not isinstance(lexed[path], RuntimeError):
            _cache[text] = lexed[path]


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
    The dump strips a number's underscores and decodes a string, so the
    spelling comes from the text. `after` is the next
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


def spellings(text):
    """The spelling of each token of `text` but EOF, as written, a line break
    as "\\n", or None when the text does not lex."""
    try:
        toks, _ = lex_text(text)
    except LexError:
        return None
    starts = line_starts(text)
    out = []
    for n, t in enumerate(toks):
        if t.kind == "EOF":
            continue
        if t.kind in ("INT", "FLOAT", "STRING", "INTERP_STRING"):
            out.append(raw_spelling(text, starts, t, toks[n + 1] if n + 1 < len(toks) else None))
        elif t.kind == "HASH_DIRECTIVE":
            out.append("#" + t.value)
        elif t.kind == "NEWLINE":
            out.append("\n")
        else:
            out.append(t.value)
    return out

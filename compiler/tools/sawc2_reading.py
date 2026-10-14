#!/usr/bin/env python3
"""sawc2's reading of Saw source, as the frozen parser's tree and tokens.

The subset checker's rules are written over the frozen parser's tree, and the
std profile reads `std/` with sawc2: tokens from `sawc2 lex`, the tree from
`sawc2 parse --dump`, rebuilt as the frozen parser builds it. A form the frozen
tree lacks gets a node here, a subclass of the frozen kind it stands nearest.
The dump records no positions, so its leaves, each a token in source order, are
matched to the tokens, and a node's line is that of the token the frozen parser
takes it from. Leaves and tokens that disagree are a `ReadingError` (SL-600).

    python compiler/tools/sawc2_reading.py FILE...   # each file's tree, for inspection
"""
import dataclasses
import hashlib
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "sawc"))
sys.path.insert(0, HERE)

import ast_nodes as A  # noqa: E402
import build  # noqa: E402
from lexer import TokenType as T  # noqa: E402

WORK = os.path.join(REPO, ".build", "sawc2-reading")
TIMEOUT = 300


class ReadingError(Exception):
    """sawc2's dump and its tokens do not line up, or the dump holds a node
    this reading does not know: a defect of the reading, never of the source."""


# ---------------------------------------------------------------------------
# Nodes the frozen tree has none of. Each extends the frozen kind whose rules
# should see it, so a walk over structural fields reaches its children.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class TraitRequirement(A.TraitMethod):
    """A trait requirement, which may be `borrows` (SL:borrowing)."""
    is_borrows: bool = False


@dataclasses.dataclass
class BorrowBindingPattern(A.BindingPattern):
    """`borrow let x` or `borrow var x` in a variant's payload pattern."""
    mutable: bool = False


@dataclasses.dataclass
class BorrowBinding(A.ASTNode):
    """One `let x = place` or `var x = place` of a `borrow` block."""
    name: str = ""
    pattern: object = None
    value: object = None
    mutable: bool = False


@dataclasses.dataclass
class BorrowBlock(A.Expression):
    """`borrow let x = place { ... }`: the bindings lend their places to the block."""
    bindings: list = dataclasses.field(default_factory=list)
    body: object = None


@dataclasses.dataclass
class BorrowPlace(A.Expression):
    """`borrow place` or `borrow var place`, borrowing for one statement."""
    place: object = None
    mutable: bool = False


@dataclasses.dataclass
class BorrowUnwrap(A.Expression):
    """`if borrow var x = place { }` or a `while` head of that shape."""
    name: str = ""
    place: object = None
    mutable: bool = False
    then_branch: object = None
    else_branch: object = None
    is_loop: bool = False


@dataclasses.dataclass
class ForBorrow(A.Statement):
    """`for borrow var x in seq { }`."""
    variable: str = ""
    iterable: object = None
    body: object = None
    mutable: bool = False


@dataclasses.dataclass
class GuardCondition(A.Statement):
    """`guard condition else { ... }`."""
    condition: object = None
    else_branch: object = None


@dataclasses.dataclass
class ImplicitMember(A.Expression):
    """`.Case`, an enum case of the type its position expects."""
    member: str = ""


@dataclasses.dataclass
class MultiSubscript(A.Expression):
    """`x[a, b]` or `x[k: a]`, a subscript of more than one argument."""
    array_expr: object = None
    arguments: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CallExpr(A.Expression):
    """A call whose callee is neither a name nor a member: `f()(1)`."""
    callee: object = None
    arguments: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SliceType(A.SawType):
    """`&[T]` or `&var [T]`: a reference whose `inner_type` is the element type."""


# ---------------------------------------------------------------------------
# Tokens.
# ---------------------------------------------------------------------------

class Segment:
    """One segment of an interpolated string, as the frozen lexer's
    `StringSegment`: decoded `text` for a literal run, the raw text and the
    position of its `{` for an interpolation."""
    __slots__ = ("kind", "text", "line", "column")

    def __init__(self, kind, text, line=0, column=0):
        self.kind = kind
        self.text = text
        self.line = line
        self.column = column


class Token:
    """One `sawc2 lex` record, in the frozen lexer's `Token` shape."""
    __slots__ = ("type", "value", "line", "column", "suffix", "segments", "kind")

    def __init__(self, kind, value, line, column, suffix=None, segments=None):
        self.kind = kind
        self.type = _frozen_type(kind)
        self.value = value
        self.line = line
        self.column = column
        self.suffix = suffix
        self.segments = segments


def _frozen_type(kind):
    """The frozen lexer's kind for a sawc2 kind. `borrow` is a keyword only
    for sawc2; the frozen lexer reads it as the identifier it spells."""
    if kind == "BORROW":
        return T.IDENT
    return T[kind]


def _unescape_lex(text):
    """A `sawc2 lex` field's text: the dump escapes bytes (compiler/lex/README.md)."""
    out = bytearray()
    i = 0
    raw = text.encode("utf-8")
    simple = {ord("\\"): 0x5C, ord("n"): 0x0A, ord("t"): 0x09, ord("r"): 0x0D, ord("0"): 0x00}
    while i < len(raw):
        b = raw[i]
        if b == 0x5C and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == ord("x") and i + 3 < len(raw):
                out.append(int(raw[i + 2:i + 4].decode("ascii"), 16))
                i += 4
                continue
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
        out.append(b)
        i += 1
    return out.decode("utf-8")


_SEGMENT_RE = re.compile(r"E:(\d+):(\d+):(.*)\Z", re.S)


def parse_tokens(text):
    """`sawc2 lex` output as Tokens, or (None, (line, message)) on its ERROR record."""
    tokens = []
    for record in text.split("\n"):
        if not record:
            continue
        fields = record.split("\t")
        if fields[0] == "ERROR":
            line = int(fields[1].split(":")[0])
            return None, (line, "%s: %s" % (fields[3] if len(fields) > 3 else "lex", fields[2]))
        line, column = (int(x) for x in fields[1].split(":"))
        kind = fields[0]
        value = _unescape_lex(fields[2]) if len(fields) > 2 else ""
        suffix = None
        segments = None
        if kind == "INTERP_STRING":
            segments = []
            for field in fields[3:]:
                if field.startswith("T:"):
                    segments.append(Segment("text", _unescape_lex(field[2:])))
                else:
                    m = _SEGMENT_RE.match(field)
                    if m is None:
                        raise ReadingError("an INTERP_STRING segment reads %r" % field)
                    segments.append(Segment("expr", _unescape_lex(m.group(3)),
                                            int(m.group(1)), int(m.group(2))))
        elif len(fields) > 3:
            suffix = fields[3]
        tokens.append(Token(kind, value, line, column, suffix, segments))
    return tokens, None


def _sawc2(args, cwd=REPO):
    if not os.path.exists(build.SAWC2):
        raise ReadingError("the std profile reads std/ with sawc2, and %s is not built; build it "
                           "with compiler/tools/build.py" % os.path.relpath(build.SAWC2, REPO))
    r = subprocess.run([build.SAWC2] + list(args), cwd=cwd, capture_output=True, timeout=TIMEOUT)
    return r.returncode, r.stdout.decode("utf-8")


def _rel(path):
    """`path` as sawc2 is given it: from the repository root, so that the
    fixpoint lane's twin sees the same arguments in every checkout."""
    return os.path.relpath(os.path.abspath(path), REPO)


def lex_file(path):
    """(tokens, None) or (None, (line, message)) for one file."""
    code, out = _sawc2(["lex", _rel(path)])
    tokens, error = parse_tokens(out)
    if error is None and code != 0:
        raise ReadingError("`sawc2 lex %s` exited %d with no ERROR record" % (_rel(path), code))
    return tokens, error


_segment_cache = {}


def lex_text(text):
    """The tokens of a fragment, an interpolation's text, or None when sawc2
    refuses it. The fragment's file is named for its text, so two checks at
    once share it and a rerun asks sawc2 the same question."""
    if text not in _segment_cache:
        os.makedirs(WORK, exist_ok=True)
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        path = os.path.join(WORK, "segment-%s.saw" % digest)
        if not os.path.exists(path):
            fd, scratch = tempfile.mkstemp(dir=WORK, suffix=".saw")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(scratch, path)
        tokens, error = lex_file(path)
        _segment_cache[text] = None if error is not None else tokens
    return _segment_cache[text]


def parse_files(paths):
    """{path: ("ok", root Node) | ("error", line, message)} from one
    `sawc2 parse --dump` process."""
    _, out = _sawc2(["parse", "--dump"] + [_rel(p) for p in paths])
    records, current = {}, None
    for line in out.split("\n"):
        if line.startswith("FILE\t"):
            current = []
            records[line[5:]] = current
        elif current is not None:
            current.append(line)
    result = {}
    for path in paths:
        lines = records.get(_rel(path))
        if lines is None:
            raise ReadingError("`sawc2 parse --dump` printed no record for %s" % path)
        errors = [line.split("\t") for line in lines if line.startswith("ERROR\t")]
        if errors:
            rule, at, message = errors[0][1], errors[0][2], errors[0][3]
            result[path] = ("error", int(at.split(":")[0]), "%s: %s" % (rule, message))
        else:
            result[path] = ("ok", read_dump("\n".join(lines)))
    return result


def read_dump(text):
    """The canonical dump as `frozen_compare.Node`s, by that tool's reader.
    Imported here, not at the top, since importing it puts the grammar tools
    on `sys.path`, which a process that only imports the subset checker has
    no use for."""
    import frozen_compare
    return frozen_compare.read_dump(text)


# ---------------------------------------------------------------------------
# Leaves and literals.
# ---------------------------------------------------------------------------

def unescape_leaf(text):
    """A dump leaf as written: the dump's own escapes (`\\xHH`, `\\uHHHH`, `\\(`,
    `\\)`) undone, the literal's escapes kept (compiler/tests/parse/README.md)."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt in "()":
                out.append(nxt)
                i += 2
                continue
            if nxt == "x" and re.match(r"[0-9A-Fa-f]{2}", text[i + 2:i + 4]):
                out.append(chr(int(text[i + 2:i + 4], 16)))
                i += 4
                continue
            if nxt == "u" and re.match(r"[0-9A-Fa-f]{4}", text[i + 2:i + 6]):
                out.append(chr(int(text[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(text[i:i + 2])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


_STRING_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r", "0": "\0",
                   "{": "{", "}": "}"}


def decode_string(spelling):
    """A string literal's value from its source spelling, quotes included."""
    body = spelling[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "u" and body[i + 2:i + 3] == "{":
                end = body.index("}", i + 3)
                out.append(chr(int(body[i + 3:end], 16)))
                i = end + 1
                continue
            out.append(_STRING_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


_INT_SUFFIX_RE = re.compile(r"(?:_?)([iu](?:8|16|32|64))\Z")


def decode_int(spelling):
    """(value, suffix) of an integer literal as written. No digit of any base
    is an `i` or a `u`, so a trailing width suffix is never read as digits."""
    text = spelling
    suffix = None
    m = _INT_SUFFIX_RE.search(text)
    if m:
        suffix = m.group(1)
        text = text[:m.start()]
    text = text.replace("_", "")
    low = text[:2].lower()
    if low == "0x":
        return int(text, 16), suffix
    if low == "0b":
        return int(text, 2), suffix
    if low == "0o":
        return int(text, 8), suffix
    return int(text, 10), suffix


def _leaf_matches(leaf, tok):
    """Is `tok` the token the dump's `leaf` prints?"""
    if tok.kind == "STRING":
        return leaf.startswith('"') and decode_string(leaf) == tok.value
    if tok.kind == "INT":
        return leaf.replace("_", "") == tok.value + (tok.suffix or "")
    if tok.kind == "FLOAT":
        return leaf.replace("_", "") == tok.value
    return leaf == tok.value


# The token kinds a dump leaf always prints, so each must match one, but for
# the contextual words a node's kind implies, which the lexer reads as names.
LEAF_BEARING =("IDENT", "INT", "FLOAT", "STRING", "INTERP_STRING", "DOLLAR_PARAM")
IMPLIED_WORDS = ("import", "module", "type", "static_assert", "blocking", "lends", "copy",
                 "const", "_", "export", "section", "synthesize", "align", "test", "package",
                 "parent", "any", "constexpr", "private", "shared", "sizeof", "alignof")


# ---------------------------------------------------------------------------
# The reading: leaves matched to tokens, then nodes converted.
# ---------------------------------------------------------------------------

def _is_node(x):
    """A dump child is a node or a leaf, and every leaf is a string."""
    return not isinstance(x, str)


def nodes(n, base=None):
    """`n`'s child nodes, of `base` when given. A doc comment is never one:
    no rule reads docs."""
    return [c for c in n.children if _is_node(c) and c.base != "Doc"
            and (base is None or c.base == base)]


def leaves(n):
    return [c for c in n.children if not _is_node(c)]


TYPE_BASES = ("NamedType", "OptionalType", "RefType", "ArrayType", "TupleType", "FuncType",
              "AnyType", "SliceType")


class Reader:
    """One file: its tokens and dump, read as the frozen parser's Program."""

    def __init__(self, path, tokens, root):
        self.path = path
        self.tokens = tokens
        self.root = root
        self.leaf_token = {}       # (id(node), child index) -> token index
        self.first = {}            # id(node) -> first leaf token index, or None
        self.last = {}             # id(node) -> last leaf token index, or None
        self.gap = {}              # id(node) -> token index after the leaf before it
        self.cursor = 0            # where the next leading-keyword search starts
        self.interp = None         # the segment line while inside an interpolation
        # (line, what) for each form of the new language this reading met that
        # the frozen tree has no field for, which a profile may refuse.
        self.features = []
        self._align()

    # -- alignment ---------------------------------------------------------

    def _align(self):
        pos = [0]
        prev_end = [0]
        used = self.used = set()

        def visit(n):
            self.gap[id(n)] = prev_end[0]
            first = last = None
            if n.base == "Doc":
                self.first[id(n)] = self.last[id(n)] = None
                return
            if n.base == "Interp":
                i = self._seek(pos[0], lambda t: t.kind == "INTERP_STRING", n)
                pos[0] = i + 1
                prev_end[0] = i + 1
                used.add(i)
                self.first[id(n)] = self.last[id(n)] = i
                return
            for k, c in enumerate(n.children):
                if _is_node(c):
                    visit(c)
                    if self.first.get(id(c)) is not None:
                        first = self.first[id(c)] if first is None else first
                        last = self.last[id(c)]
                    continue
                leaf = unescape_leaf(c)
                if leaf in ("<<", ">>"):
                    want = "<" if leaf == "<<" else ">"
                    i = self._seek(pos[0], lambda t, w=want: t.value == w, n, leaf)
                    if self.tokens[i + 1].value != want:
                        raise ReadingError("%s: `%s` is not two adjacent tokens at %d:%d"
                                           % (self.path, leaf, self.tokens[i].line,
                                              self.tokens[i].column))
                    end = i + 1
                else:
                    i = self._seek(pos[0], lambda t, lf=leaf: _leaf_matches(lf, t), n, leaf)
                    end = i
                self.leaf_token[(id(n), k)] = i
                used.add(i)
                pos[0] = end + 1
                prev_end[0] = end + 1
                first = i if first is None else first
                last = end
            self.first[id(n)] = first
            self.last[id(n)] = last

        visit(self.root)
        for i, t in enumerate(self.tokens):
            if t.kind in LEAF_BEARING and i not in used and t.value not in IMPLIED_WORDS:
                raise ReadingError("%s:%d:%d: the token `%s` matches no leaf of the dump"
                                   % (self.path, t.line, t.column, t.value))

    def _seek(self, start, pred, node, leaf=None):
        """The first token from `start` that `pred` takes. Only tokens no leaf
        prints may lie before it."""
        what = leaf if leaf is not None else "INTERP_STRING"
        for i in range(start, len(self.tokens)):
            t = self.tokens[i]
            if pred(t):
                return i
            if t.kind in LEAF_BEARING and t.value not in IMPLIED_WORDS:
                raise ReadingError("%s:%d:%d: the dump's next leaf is %r of %s, but the token "
                                   "here is `%s`" % (self.path, t.line, t.column, what,
                                                     node.kind, t.value))
        raise ReadingError("%s: no token prints the leaf %r of %s" % (self.path, what, node.kind))

    # -- lines ---------------------------------------------------------------

    def range_of(self, n):
        """The token indices a node's own tokens can lie in: from just after the
        leaf before it to its last leaf, or to the next leaf when it has none."""
        start = self.gap[id(n)]
        end = self.last.get(id(n))
        if end is None:
            end = start
            while end < len(self.tokens) and end not in self.used:
                end += 1
        return start, end

    def anchor(self, n, *kinds, value=None):
        """The line of the first token of one of `kinds` that opens `n`. The
        search never goes back past one an enclosing node already took."""
        if self.interp is not None:
            return self.interp
        i = self.anchor_index(n, kinds, value)
        if i is None:
            return self.start_line(n)
        return self.tokens[i].line

    def anchor_index(self, n, kinds, value=None):
        start, end = self.range_of(n)
        start = max(start, self.cursor)
        for i in range(start, min(end + 1, len(self.tokens))):
            t = self.tokens[i]
            if t.kind in kinds and (value is None or t.value == value):
                self.cursor = i + 1
                return i
        return None

    # Tokens that end what came before and so never begin a node.
    NOT_A_START = ("NEWLINE", "RPAREN", "RBRACKET", "RBRACE", "COMMA", "SEMICOLON")

    def start_line(self, n):
        """The line of the first token at or after where `n` can begin."""
        if self.interp is not None:
            return self.interp
        start, _ = self.range_of(n)
        return self.line_from(max(start, self.cursor))

    def line_from(self, i):
        """The line of the first token from `i` that can begin a node."""
        while i < len(self.tokens) and self.tokens[i].kind in self.NOT_A_START:
            i += 1
        return self.tokens[min(i, len(self.tokens) - 1)].line

    def leaf_line(self, n, k):
        """The line of `n`'s child `k`, a leaf."""
        if self.interp is not None:
            return self.interp
        return self.tokens[self.leaf_token[(id(n), k)]].line

    def leaf_index(self, n, text):
        for k, c in enumerate(n.children):
            if not _is_node(c) and unescape_leaf(c) == text:
                return k
        return None

    def before_leaf_line(self, n, k):
        """The line of the token before `n`'s leaf `k`: a member's `.` or `?.`."""
        if self.interp is not None:
            return self.interp
        return self.tokens[self.leaf_token[(id(n), k)] - 1].line

    def after_line(self, inner, *kinds):
        """The line of the first token of `kinds` after `inner`'s last leaf: a
        `!` or a `[` that follows an operand."""
        if self.interp is not None:
            return self.interp
        last = self.last.get(id(inner))
        start = (last + 1) if last is not None else self.range_of(inner)[1]
        for i in range(start, len(self.tokens)):
            if self.tokens[i].kind in kinds:
                return self.tokens[i].line
        return self.start_line(inner)

    # -- the file ------------------------------------------------------------

    def program(self):
        prog = A.Program(structs=[], functions=[], source_path=self.path)
        self.items(self.root, prog)
        return prog

    def items(self, parent, prog):
        for item in nodes(parent):
            self.item(item, prog)

    def item(self, n, prog):
        b = n.base
        if b == "Import":
            prog.imports.append(self.import_decl(n))
        elif b == "ModuleDecl":
            prog.module_decls.append(self.module_decl(n))
        elif b == "StaticAssert":
            prog.static_asserts.append(self.static_assert(n))
        elif b == "Declaration":
            self.declaration(n, prog)
        elif b == "TestOnly":
            for inner in nodes(n):
                self.item(inner, prog)
        elif b == "TestGroup":
            self.items(n, prog)
        elif b == "TestCase":
            # A test case declares nothing the frozen tree has a place for, and
            # the `@test` token before it is refused on its own.
            return
        else:
            raise ReadingError("%s: no reading of the item %s" % (self.path, n.kind))

    def import_decl(self, n):
        line = self.anchor(n, "IDENT", value="import")
        path = self.path_names(nodes(n, "Path")[0])
        words = [unescape_leaf(x) for x in leaves(n)]
        symbols = nodes(n, "ImportSymbol")
        decl = A.ImportDecl(path=path, symbols=None, alias=None, line=line,
                            is_public=n.kind == "Import.reexport")
        if "*" in words:
            decl.is_glob = True
        elif "{" in words:
            decl.symbols = []
            aliases = {}
            for s in symbols:
                names = [unescape_leaf(x) for x in leaves(s)]
                decl.symbols.append(names[0])
                if s.kind == "ImportSymbol.alias":
                    aliases[names[0]] = names[-1]
            decl.symbol_aliases = aliases or None
        elif "as" in words:
            decl.alias = words[words.index("as") + 1]
        return decl

    def path_names(self, n):
        return [unescape_leaf(x) for x in leaves(n)]

    def dotted(self, n):
        return ".".join(self.path_names(n))

    def module_decl(self, n):
        words = [unescape_leaf(x) for x in leaves(n)]
        public = words[:1] == ["public"]
        line = self.anchor(n, "IDENT", value="module")
        if public:
            line = self.leaf_line(n, self.leaf_index(n, "public"))
        name = words[1] if public else words[0]
        md = A.ModuleDecl(name=name, is_public=public, line=line)
        if n.kind == "ModuleDecl.inline":
            md.is_inline = True
            md.body = A.Program(structs=[], functions=[])
            self.items(n, md.body)
        return md

    def static_assert(self, n):
        line = self.anchor(n, "IDENT", value="static_assert")
        cond = self.expr(nodes(n)[0])
        message = decode_string(unescape_leaf(leaves(n)[-1]))
        return A.StaticAssert(condition=cond, message=message, line=line, source_file=self.path)

    def visibility(self, n):
        for v in nodes(n, "Visibility"):
            return {"Visibility.public": A.Visibility.PUBLIC,
                    "Visibility.package": A.Visibility.PACKAGE,
                    "Visibility.parent": A.Visibility.PARENT}[v.kind]
        return A.Visibility.PRIVATE

    def attributes(self, n):
        out = []
        for a in nodes(n, "Attribute"):
            line = self.anchor(a, "AT")
            name = a.kind.split(".", 1)[1]
            arg = None
            expr_arg = None
            if name == "export-symbol":
                name = "export"
            if name == "synthesize-shared":
                name, arg = "synthesize", "shared"
            strings = [unescape_leaf(x) for x in leaves(a) if unescape_leaf(x).startswith('"')]
            if strings:
                arg = decode_string(strings[0])
            if name == "align":
                expr_arg = self.expr(nodes(a)[0])
            out.append(A.Attribute(name=name, arg=arg, expr_arg=expr_arg, line=line))
        return out

    def declaration(self, n, prog):
        vis = self.visibility(n)
        attrs = self.attributes(n)
        inner = [c for c in nodes(n) if c.base not in ("Doc", "Attribute", "Visibility")][0]
        b = inner.base
        if b == "Func":
            fn = self.function(inner, vis)
            fn.attributes = attrs
            prog.functions.append(fn)
        elif b == "Struct":
            prog.structs.append(self.struct(inner, vis))
        elif b == "Enum":
            prog.enums.append(self.enum(inner, vis))
        elif b == "Trait":
            prog.traits.append(self.trait(inner, vis))
        elif b == "Extension":
            ext = self.extension(inner)
            ext.attributes = attrs
            prog.extensions.append(ext)
        elif b == "TypeAlias":
            line = self.anchor(inner, "IDENT", value="type")
            prog.type_definitions.append(A.TypeDefinition(
                name=unescape_leaf(leaves(inner)[0]), defined_type=self.type(nodes(inner)[0]),
                visibility=vis, line=line, source_file=self.path))
        elif b == "Static":
            st = self.static(inner, vis)
            st.attributes = attrs
            prog.statics.append(st)
        elif b == "ExternBlock":
            prog.extern_blocks.append(self.extern_block(inner))
        else:
            raise ReadingError("%s: no reading of the declaration %s" % (self.path, inner.kind))

    # -- signatures ----------------------------------------------------------

    def type_params(self, n):
        out = []
        for g in nodes(n, "GenericParam"):
            words = [unescape_leaf(x) for x in leaves(g)]
            line = self.leaf_line(g, self.leaf_index(g, words[0]))
            kids = nodes(g)
            if g.kind == "GenericParam.const":
                const_default = self.expr(kids[1]) if len(kids) > 1 else None
                out.append(A.TypeParameter(name=words[0], bounds=[], is_const=True,
                                           const_type=self.type(kids[0]),
                                           const_default_expr=const_default, line=line))
                continue
            bounds = [self.dotted(p) for p in kids if p.base == "Path"]
            types = [k for k in kids if k.base != "Path"]
            out.append(A.TypeParameter(name=words[0], bounds=bounds,
                                       default=self.type(types[0]) if types else None,
                                       line=line))
        return out

    def parameters(self, n):
        """(parameters, self_mutable, self_is_reference), as `parse_parameters` returns."""
        params = []
        self_mutable = False
        self_is_reference = False
        for p in nodes(n, "Param"):
            if p.kind == "Param.receiver":
                exclusive = nodes(p)[0].kind == "Receiver.exclusive"
                self_mutable = exclusive
                self_is_reference = True
                params.append(A.Parameter(name="self", type=A.SawType(A.TypeKind.VOID),
                                          is_reference=True, reference_mutable=exclusive))
                continue
            name = unescape_leaf(leaves(p)[0])
            kids = nodes(p)
            t = self.type(kids[0])
            is_ref = t.kind == A.TypeKind.REFERENCE
            default = self.expr(kids[1]) if len(kids) > 1 else None
            params.append(A.Parameter(name=name, type=t, default_value=default,
                                      is_reference=is_ref,
                                      reference_mutable=is_ref and t.reference_mutable))
        return params, self_mutable, self_is_reference

    def return_type(self, n):
        for k in nodes(n):
            if k.base in TYPE_BASES:
                return self.type(k)
        return A.SawType(A.TypeKind.VOID)

    def head(self, n):
        """(name, the leaf words after it) of a `func`, method, `init` or
        requirement, and whether it is declared `static`. The name may itself
        be an effect word, `func sync()`, so the effects are only the words that
        follow it."""
        words = [unescape_leaf(x) for x in leaves(n)]
        static = words[:1] == ["static"]
        if static:
            words = words[1:]
        if n.base == "Init":
            return "init", words, static
        if words[:2] == ["[", "]"]:
            if words[2:3] == ["="]:
                return "[]=", words[3:], static
            return "[]", words[2:], static
        return words[0], words[1:], static

    def effects(self, n, line):
        """The effect words of a declaration on `line`. `constexpr` has no
        field on the frozen node, so it is recorded as a feature."""
        _, words, static = self.head(n)
        fx = {w: (w in words) for w in ("consumes", "unsafe", "sync", "borrows")}
        fx["static"] = static
        if "constexpr" in words:
            self.features.append((line, "a `constexpr` function"))
        return fx

    def body(self, n):
        blocks = nodes(n, "Block")
        return self.block(blocks[-1]) if blocks else None

    def function(self, n, vis):
        line = self.anchor(n, "FUNC")
        type_params = self.type_params(n)
        params, _, _ = self.parameters(n)
        fx = self.effects(n, line)
        return_type = self.return_type(n)
        return A.Function(name=unescape_leaf(leaves(n)[0]), parameters=params,
                          return_type=return_type, body=self.body(n), type_params=type_params,
                          visibility=vis, is_sync=fx["sync"], is_unsafe=fx["unsafe"],
                          is_borrows=fx["borrows"], line=line, source_file=self.path)

    def method_name(self, n):
        return self.head(n)[0]

    def method(self, n, vis):
        if n.base == "Init":
            line = self.anchor(n, "INIT")
            name = "init"
            type_params = []
        else:
            line = self.anchor(n, "FUNC")
            name = self.method_name(n)
            type_params = self.type_params(n)
        params, self_mutable, self_is_reference = self.parameters(n)
        fx = self.effects(n, line)
        is_static = not (params and params[0].name == "self")
        return_type = self.return_type(n)
        return A.Method(name=name, parameters=params, return_type=return_type,
                        body=self.body(n), is_init=n.base == "Init", self_mutable=self_mutable,
                        self_is_reference=self_is_reference, is_static=is_static,
                        declared_static=fx["static"], is_sync=fx["sync"], is_unsafe=fx["unsafe"],
                        is_borrows=fx["borrows"], is_consumes=fx["consumes"],
                        type_params=type_params, visibility=vis, line=line,
                        source_file=self.path)

    def struct(self, n, vis):
        line = self.anchor(n, "STRUCT")
        words = [unescape_leaf(x) for x in leaves(n)]
        name = [w for w in words if w not in ("unsafe", "borrows")][0]
        type_params = self.type_params(n)
        fields = []
        for f in nodes(n, "Field"):
            name_leaves = [k for k, c in enumerate(f.children) if not _is_node(c)]
            fvis, written = A.Visibility.PRIVATE, False
            if nodes(f, "Visibility"):
                fvis, written = self.visibility(f), True
            elif len(name_leaves) > 1:
                written = True
                name_leaves = name_leaves[1:]
            k = name_leaves[0]
            fields.append(A.StructField(name=unescape_leaf(f.children[k]),
                                        type=self.type(nodes(f)[-1]), visibility=fvis,
                                        visibility_written=written, line=self.leaf_line(f, k)))
        return A.Struct(name=name, fields=fields, type_params=type_params, visibility=vis, is_unsafe="unsafe" in words,
                        is_borrowing="borrows" in words, line=line, source_file=self.path)

    def enum(self, n, vis):
        line = self.anchor(n, "ENUM")
        type_params = self.type_params(n)
        raw = [self.type(k) for k in nodes(n) if k.base in TYPE_BASES]
        variants = []
        for c in nodes(n, "Case"):
            name = unescape_leaf(leaves(c)[0])
            payload = [(unescape_leaf(leaves(p)[0]), self.type(nodes(p)[0]))
                       for p in nodes(c, "PayloadField")]
            v = A.EnumVariant(name=name, associated_types=payload)
            k = self.leaf_index(c, "=")
            if k is not None:
                v.raw_line = self.leaf_line(c, k)
                value = [x for x in nodes(c) if x.base != "PayloadField"][0]
                expr = self.expr(value)
                if isinstance(expr, A.IntLiteral):
                    v.raw_value = expr.value
                elif (isinstance(expr, A.UnaryOp) and expr.op == "-"
                      and isinstance(expr.operand, A.IntLiteral)):
                    v.raw_value = -expr.operand.value
                else:
                    v.raw_value_expr = expr
            variants.append(v)
        return A.Enum(name=unescape_leaf(leaves(n)[0]), variants=variants,
                      type_params=type_params, visibility=vis, line=line,
                      source_file=self.path, raw_type=raw[0] if raw else None)

    def trait(self, n, vis):
        line = self.anchor(n, "TRAIT")
        type_params = self.type_params(n)
        methods = []
        assoc = []
        for k in nodes(n):
            if k.base == "AssocType":
                assoc.append(A.AssociatedType(name=unescape_leaf(leaves(k)[0]),
                                              line=self.anchor(k, "IDENT", value="type")))
            elif k.base == "Requirement":
                rline = self.anchor(k, "FUNC")
                self.type_params(k)
                params, self_mutable, self_is_reference = self.parameters(k)
                fx = self.effects(k, rline)
                return_type = self.return_type(k)
                methods.append(TraitRequirement(
                    name=self.method_name(k), parameters=params, return_type=return_type,
                    self_mutable=self_mutable, self_is_reference=self_is_reference,
                    is_sync=fx["sync"], is_unsafe=fx["unsafe"], is_static=fx["static"],
                    body=self.body(k), line=rline, is_borrows=fx["borrows"]))
        return A.Trait(name=unescape_leaf(leaves(n)[0]), methods=methods, associated_types=assoc,
                       type_params=type_params,
                       parent_traits=[self.dotted(p) for p in nodes(n, "Path")],
                       visibility=vis, line=line, source_file=self.path)

    def extension(self, n):
        line = self.anchor(n, "EXTENSION")
        paths = nodes(n, "Path")
        type_params = self.type_params(n)
        methods = []
        assigns = []
        for m in nodes(n, "ExtensionMember"):
            if m.kind == "ExtensionMember.type-assign":
                ta = nodes(m, "TypeAssign")[0]
                assigns.append(A.TypeAssignment(name=unescape_leaf(leaves(ta)[0]),
                                                assigned_type=self.type(nodes(ta)[0]),
                                                line=self.anchor(ta, "IDENT", value="type")))
                continue
            decl = [k for k in nodes(m) if k.base in ("Method", "Init")][0]
            methods.append(self.method(decl, self.visibility(m)))
        return A.Extension(struct_name=self.dotted(paths[0]), methods=methods,
                           type_params=type_params,
                           conformances=[self.dotted(p) for p in paths[1:]],
                           type_assignments=assigns, line=line, source_file=self.path)

    def static(self, n, vis):
        line = self.anchor(n, "STATIC")
        kids = nodes(n)
        return A.StaticDecl(name=[unescape_leaf(x) for x in leaves(n)
                                  if unescape_leaf(x) not in ("unsafe", "var")][0],
                            type=self.type(kids[0]),
                            initializer=self.expr(kids[1]) if len(kids) > 1 else None,
                            visibility=vis, is_var=n.kind == "Static.unsafe-var",
                            is_unsafe=n.kind == "Static.unsafe-var", line=line,
                            source_file=self.path)

    def extern_block(self, n):
        line = self.anchor(n, "EXTERN")
        functions = []
        for f in nodes(n, "ExternFunc"):
            fline = self.anchor(f, "IDENT", "FUNC") if f.kind == "ExternFunc.blocking" \
                else self.anchor(f, "FUNC")
            params, _, _ = self.parameters(f)
            functions.append(A.ExternFunction(
                name=unescape_leaf(leaves(f)[0]), parameters=params,
                return_type=self.return_type(f),
                is_variadic="..." in [unescape_leaf(x) for x in leaves(f)],
                is_blocking=f.kind == "ExternFunc.blocking", line=fline,
                source_file=self.path))
        return A.ExternBlock(abi=decode_string(unescape_leaf(leaves(n)[0])), functions=functions,
                             line=line)

    # -- types ---------------------------------------------------------------

    BUILTIN_TYPES = {"Int": A.TypeKind.INT, "Float": A.TypeKind.FLOAT, "Bool": A.TypeKind.BOOL,
                     "String": A.TypeKind.STRING, "Void": A.TypeKind.VOID,
                     "Never": A.TypeKind.NEVER, "UInt": A.TypeKind.UINT,
                     "Int8": A.TypeKind.INT8, "Int16": A.TypeKind.INT16,
                     "Int32": A.TypeKind.INT32, "Int64": A.TypeKind.INT64,
                     "UInt8": A.TypeKind.UINT8, "UInt16": A.TypeKind.UINT16,
                     "UInt32": A.TypeKind.UINT32, "UInt64": A.TypeKind.UINT64}

    def type(self, n):
        b = n.base
        if b == "NamedType":
            path = nodes(n)[0]
            names = self.path_names(path)
            name = ".".join(names)
            args = [self.type_arg(k) for k in nodes(n)[1:]]
            if len(names) == 1 and name in self.BUILTIN_TYPES:
                return A.SawType(self.BUILTIN_TYPES[name])
            if name == "Self":
                return A.SawType(A.TypeKind.SELF)
            if name in ("UnsafePointer", "UnsafeConstPointer"):
                return A.SawType(A.TypeKind.POINTER, inner_type=args[0] if args else None,
                                 pointer_mutable=name == "UnsafePointer")
            return A.SawType(A.TypeKind.STRUCT, struct_name=name, type_args=args or None,
                             written_name=name, written_file=self.path,
                             written_line=self.leaf_line(path, 0))
        if b == "OptionalType":
            return A.SawType(A.TypeKind.OPTIONAL, inner_type=self.type(nodes(n)[0]))
        if b == "RefType":
            return A.SawType(A.TypeKind.REFERENCE, inner_type=self.type(nodes(n)[0]),
                             reference_mutable=n.kind == "RefType.exclusive")
        if b == "ArrayType":
            elem, size = nodes(n)
            size_expr = self.expr(size)
            if isinstance(size_expr, A.IntLiteral):
                return A.SawType(A.TypeKind.ARRAY, array_element_type=self.type(elem),
                                 array_size=int(size_expr.value), array_size_expr=size_expr)
            return A.SawType(A.TypeKind.ARRAY, array_element_type=self.type(elem),
                             array_size_expr=size_expr)
        if b == "TupleType":
            fields = nodes(n, "TupleField")
            if fields:
                return A.SawType(A.TypeKind.TUPLE,
                                 element_types=[self.type(nodes(f)[0]) for f in fields],
                                 tuple_field_names=[unescape_leaf(leaves(f)[0]) for f in fields])
            return A.SawType(A.TypeKind.TUPLE, element_types=[self.type(k) for k in nodes(n)])
        if b == "FuncType":
            kids = nodes(n)
            words = {unescape_leaf(x) for x in leaves(n)}
            t = A.SawType(A.TypeKind.FUNCTION, param_types=[self.type(k) for k in kids[:-1]],
                          func_return_type=self.type(kids[-1]))
            t.func_is_sync = "sync" in words
            t.func_is_escaping = "escaping" in words
            t.func_is_unsafe = "unsafe" in words
            t.func_is_borrows = "borrows" in words
            return t
        if b == "AnyType":
            name = self.dotted(nodes(n)[0])
            return A.SawType(A.TypeKind.EXISTENTIAL, existential_trait=name, written_name=name,
                             written_file=self.path, written_line=self.leaf_line(nodes(n)[0], 0))
        if b == "SliceType":
            first = self.first.get(id(n))
            line = self.interp or (self.tokens[first].line if first is not None else 0)
            self.features.append((line, "a slice type `&[T]`"))
            return SliceType(A.TypeKind.REFERENCE, inner_type=self.type(nodes(n)[0]),
                             reference_mutable=n.kind == "SliceType.exclusive")
        raise ReadingError("%s: no reading of the type %s" % (self.path, n.kind))

    def type_arg(self, n):
        """A generic argument: a type, or a constant expression as frozen
        `_const_value_type` wraps it."""
        if n.base in TYPE_BASES:
            return self.type(n)
        expr = self.expr(n)
        if isinstance(expr, A.IntLiteral):
            return A.SawType(A.TypeKind.CONST_VALUE, const_value=int(expr.value),
                             array_size_expr=expr)
        return A.SawType(A.TypeKind.CONST_VALUE, array_size_expr=expr)

    # -- statements ------------------------------------------------------------

    def block(self, n, kids=None):
        line = self.anchor(n, "LBRACE") if kids is None else self.start_line(n)
        stmts = [self.statement(k) for k in (nodes(n) if kids is None else kids)]
        final = None
        if stmts and type(stmts[-1]) is A.ExpressionStatement:
            final = stmts.pop().expression
        return A.Block(statements=stmts, final_expr=final, line=line)

    LOOPS = ("While", "WhileLet", "For")

    def statement(self, n):
        b = n.base
        if b == "ExprStmt":
            inner = nodes(n)[0]
            expr = self.expr(inner)
            if inner.base in self.LOOPS:
                return expr
            return A.ExpressionStatement(expression=expr, line=expr.line)
        if b == "Let":
            line = self.anchor(n, "LET", "VAR")
            kids = nodes(n)
            name = unescape_leaf(leaves(kids[0])[0])
            annotation = self.type(kids[1]) if len(kids) > 2 else None
            return A.LetStatement(name=name, type_annotation=annotation,
                                  value=self.expr(kids[-1]), mutable=n.kind == "Let.mutable",
                                  line=line)
        if b == "AttributedLocal":
            attrs = self.attributes(n)
            let = self.statement(nodes(n, "Let")[0])
            let.attributes = attrs
            return let
        if b == "DestructureLet":
            line = self.anchor(n, "LET", "VAR")
            pat, value = nodes(n)
            return A.DestructuringLet(pattern=self.pattern(pat), value=self.expr(value),
                                      mutable=n.kind == "DestructureLet.mutable", line=line)
        if b == "Assign":
            target, value = nodes(n)
            t = self.expr(target)
            return A.AssignStatement(target=t, value=self.expr(value), line=t.line)
        if b == "CompoundAssign":
            target, value = nodes(n)
            t = self.expr(target)
            op = [unescape_leaf(x) for x in leaves(n)][0][:-1]
            return A.CompoundAssignStatement(target=t, op=op, value=self.expr(value), line=t.line)
        if b == "OptionalAssign":
            target, value = nodes(n)
            t = self.expr(target)
            op = None
            if n.kind.endswith("compound"):
                op = [unescape_leaf(x) for x in leaves(n)][0][:-1]
            assign = A.OptionalChainAssign(target=t, value=self.expr(value), op=op, line=t.line)
            return A.ExpressionStatement(expression=assign, line=t.line)
        if b == "Return":
            line = self.anchor(n, "RETURN")
            kids = nodes(n)
            return A.ReturnStatement(value=self.expr(kids[0]) if kids else None, line=line)
        if b == "Break":
            line = self.anchor(n, "BREAK")
            kids = nodes(n)
            return A.BreakStatement(value=self.expr(kids[0]) if kids else None, line=line)
        if b == "Continue":
            return A.ContinueStatement(line=self.anchor(n, "CONTINUE"))
        if b == "Lend":
            line = self.anchor(n, "LEND")
            return A.LendStatement(place=self.expr(nodes(n)[0]), line=line)
        if b == "Guard":
            return self.guard(n)
        if b == "StaticAssert":
            return self.static_assert(n)
        raise ReadingError("%s: no reading of the statement %s" % (self.path, n.kind))

    def guard(self, n):
        line = self.anchor(n, "GUARD")
        if n.kind == "Guard.condition":
            cond, body = nodes(n)
            return GuardCondition(condition=self.expr(cond), else_branch=self.block(body),
                                  line=line)
        kids = nodes(n)
        target, subject, body = kids[0], kids[1:-1], kids[-1]
        name, pattern = self.binding_target(target)
        optional = self.binding_subject(n, subject)
        return A.GuardLetStatement(name=name, optional_expr=optional,
                                   mutable=n.kind == "Guard.var", else_branch=self.block(body),
                                   line=line, pattern=pattern)

    def binding_target(self, n):
        if n.base == "BindingName":
            return unescape_leaf(leaves(n)[0]), None
        return "", self.pattern(n)

    def binding_subject(self, owner, subject):
        """A binding's subject: an expression, or an optional-chain assignment
        `x?.y = v`, which the binding consumes."""
        if len(subject) == 2:
            target = self.expr(subject[0])
            k = self.leaf_index(owner, "=")
            line = self.leaf_line(owner, k) if k is not None else target.line
            return A.OptionalChainAssign(target=target, value=self.expr(subject[1]), line=line)
        return self.expr(subject[0])

    # -- expressions -------------------------------------------------------------

    def expr(self, n):
        method = getattr(self, "x_" + n.base, None)
        if method is None:
            raise ReadingError("%s: no reading of the expression %s" % (self.path, n.kind))
        return method(n)

    def x_Name(self, n):
        k = 0
        targs = [self.type_arg(t) for t in nodes(n)]
        return A.Identifier(name=unescape_leaf(leaves(n)[0]), type_args=targs or None,
                            line=self.leaf_line(n, k))

    def x_Path(self, n):
        """A name in a constant expression, `N` or `m.N`."""
        names = self.path_names(n)
        expr = A.Identifier(name=names[0], line=self.leaf_line(n, 0))
        for k, name in enumerate(names[1:], 1):
            expr = A.MemberAccess(object=expr, member=name, line=self.before_leaf_line(n, k))
        return expr

    def x_SelfExpr(self, n):
        return A.SelfExpr(line=self.anchor(n, "SELF"))

    def x_IntLit(self, n):
        value, suffix = decode_int(unescape_leaf(leaves(n)[0]))
        return A.IntLiteral(value=value, suffix=suffix, line=self.leaf_line(n, 0))

    def x_FloatLit(self, n):
        return A.FloatLiteral(value=float(unescape_leaf(leaves(n)[0]).replace("_", "")),
                              line=self.leaf_line(n, 0))

    def x_StringLit(self, n):
        return A.StringLiteral(value=decode_string(unescape_leaf(leaves(n)[0])),
                               line=self.leaf_line(n, 0))

    def x_BoolLit(self, n):
        true = n.kind == "BoolLit.true"
        return A.BoolLiteral(value=true, line=self.anchor(n, "TRUE" if true else "FALSE"))

    def x_NoneLit(self, n):
        return A.NoneLiteral(line=self.anchor(n, "NONE"))

    def x_SourceLoc(self, n):
        return A.SourceLocationLiteral(kind=n.kind.split(".", 1)[1], source_file=self.path,
                                       line=self.anchor(n, "HASH_DIRECTIVE"))

    def x_ShorthandParam(self, n):
        return A.Identifier(name=unescape_leaf(leaves(n)[0]), line=self.leaf_line(n, 0))

    def x_ImplicitMember(self, n):
        return ImplicitMember(member=unescape_leaf(leaves(n)[0]),
                              line=self.before_leaf_line(n, 0))

    def x_Interp(self, n):
        children = [c for c in n.children if _is_node(c) or unescape_leaf(c) == "{}"]
        if self.interp is None:
            tok = self.tokens[self.first[id(n)]]
            line, segments = tok.line, tok.segments
        else:
            # An interpolation inside another's segment, which no token of the
            # file carries, so its segments are the dump's own.
            line = self.interp
            segments = [Segment("expr", "", line) if _is_node(c) or unescape_leaf(c) == "{}"
                        else Segment("text", decode_string(unescape_leaf(c)))
                        for c in n.children]
        exprs_seen = [s for s in segments if s.kind == "expr"]
        if len(exprs_seen) != len(children):
            raise ReadingError("%s:%d: an interpolation's segments and its dump disagree"
                               % (self.path, line))
        parts, expressions, pending = [], [], []
        index = 0
        saved = self.interp
        for seg in segments:
            if seg.kind == "text":
                pending.append(seg.text)
                continue
            parts.append("".join(pending))
            pending = []
            child = children[index]
            index += 1
            if not _is_node(child):
                expressions.append(A.FormatPlaceholder(line=seg.line or line))
                continue
            self.interp = seg.line or line
            try:
                expressions.append(self.expr(child))
            finally:
                self.interp = saved
        parts.append("".join(pending))
        return A.StringInterpolation(parts=parts, expressions=expressions, line=line)

    def x_Binary(self, n):
        items = n.children
        left = self.expr(items[0])
        k = 1
        while k < len(items):
            op = unescape_leaf(items[k])
            line = self.leaf_line(n, k)
            right = self.expr(items[k + 1])
            left = A.BinaryOp(op=op, left=left, right=right, line=line)
            k += 2
        return left

    def x_Coalesce(self, n):
        items = n.children
        left = self.expr(items[0])
        k = 1
        while k < len(items):
            line = self.leaf_line(n, k)
            left = A.NilCoalesce(expr=left, default=self.expr(items[k + 1]), line=line)
            k += 2
        return left

    def x_Range(self, n):
        k = next(i for i, c in enumerate(n.children) if not _is_node(c))
        op = unescape_leaf(n.children[k])
        before = [c for c in n.children[:k] if _is_node(c)]
        after = [c for c in n.children[k + 1:] if _is_node(c)]
        return A.RangeExpr(start=self.expr(before[0]) if before else None,
                           end=self.expr(after[0]) if after else None,
                           is_inclusive=op == "..=", line=self.leaf_line(n, k))

    def x_Unary(self, n):
        # A constant expression's negation is the bare `Unary`: its production
        # has one alternative.
        ops = {"Unary.negate": ("-", "MINUS"), "Unary.not": ("not", "NOT"),
               "Unary.complement": ("~", "TILDE"), "Unary": ("-", "MINUS")}
        op, kind = ops[n.kind]
        line = self.anchor(n, kind)
        return A.UnaryOp(op=op, operand=self.expr(nodes(n)[0]), line=line)

    def x_Deref(self, n):
        line = self.anchor(n, "STAR")
        return A.ArrayIndex(array_expr=self.expr(nodes(n)[0]),
                            index=A.IntLiteral(value=0, line=line), line=line)

    def x_Ref(self, n):
        line = self.anchor(n, "AMPERSAND")
        return A.ReferenceExpr(expr=self.expr(nodes(n)[0]), mutable=n.kind == "Ref.exclusive",
                               line=line)

    def x_Lends(self, n):
        line = self.anchor(n, "IDENT", value="lends")
        return A.LendsExpr(place=self.expr(nodes(n)[0]), line=line)

    def x_Cast(self, n):
        inner, target = nodes(n)
        expr = self.expr(inner)
        return A.CastExpr(expr=expr, target_type=self.type(target),
                          line=self.leaf_line(n, self.leaf_index(n, "as")))

    def x_Move(self, n):
        line = self.anchor(n, "MOVE")
        place = nodes(n)[0]
        unwrap = "!" in [unescape_leaf(x) for x in leaves(n)]
        base = place
        while base.base in ("Member", "TupleIndex", "Subscript"):
            base = nodes(base)[0]
        if base.base == "Deref":
            variable_node = nodes(base)[0]
        else:
            variable_node = base
        variable = "self" if variable_node.base == "SelfExpr" else \
            unescape_leaf(leaves(variable_node)[0])
        partial = place is not base or base.base == "Deref"
        path = self.expr(place) if partial else None
        return A.MoveExpr(variable=variable, path=path, unwrap=unwrap, line=line)

    def x_Try(self, n):
        line = self.anchor(n, "TRY")
        variant = {"Try.optional": "optional", "Try.force": "force"}.get(n.kind, "propagate")
        kids = nodes(n)
        route = None
        if n.kind == "Try.route":
            route = self.path_names(kids[0])
            kids = kids[1:]
        expr = self.expr(kids[0])
        catch = None
        if kids[-1].base == "Catch":
            catch = self.block(nodes(kids[-1], "Block")[0])
        return A.TryExpr(expr=expr, variant=variant, catch_block=catch, route_path=route,
                         line=line)

    def x_TryBlock(self, n):
        line = self.anchor(n, "TRY")
        tb, cb = nodes(n, "Block")
        return A.TryCatchExpr(try_block=self.block(tb), catch_block=self.block(cb), line=line)

    def x_Tuple(self, n):
        line = self.anchor(n, "LPAREN")
        fields = nodes(n, "TupleField")
        if fields:
            return A.TupleLiteral(elements=[self.expr(nodes(f)[0]) for f in fields],
                                  field_names=[unescape_leaf(leaves(f)[0]) for f in fields],
                                  line=line)
        return A.TupleLiteral(elements=[self.expr(k) for k in nodes(n)], line=line)

    def x_Array(self, n):
        line = self.anchor(n, "LBRACKET")
        return A.ArrayLiteral(elements=[self.expr(k) for k in nodes(n)], line=line)

    def x_Repeat(self, n):
        line = self.anchor(n, "LBRACKET")
        value, count = nodes(n)
        lit = A.ArrayLiteral(elements=[self.expr(value)], line=line)
        lit.repeat_count = self.expr(count)
        return lit

    def x_Map(self, n):
        line = self.anchor(n, "LBRACE")
        entries = [(self.expr(nodes(e)[0]), self.expr(nodes(e)[1])) for e in nodes(n, "MapEntry")]
        return A.MapLiteral(entries=entries, line=line)

    def x_Set(self, n):
        line = self.anchor(n, "LBRACE")
        return A.SetLiteral(elements=[self.expr(k) for k in nodes(n)], line=line)

    def x_Closure(self, n):
        if self.interp is not None:
            line = body_line = self.interp
            column = 0
        else:
            brace = self.anchor_index(n, ("LBRACE",))
            line = self.tokens[brace].line if brace is not None else self.start_line(n)
            # The trailing-closure rule finds the token before the closure by
            # its position, so the closure keeps its `{`'s column.
            column = self.tokens[brace].column if brace is not None else 0
            k = self.leaf_index(n, "in")
            body_start = self.leaf_token[(id(n), k)] + 1 if k is not None else \
                (brace + 1 if brace is not None else self.range_of(n)[0])
            while self.tokens[body_start].kind == "NEWLINE":
                body_start += 1
            body_line = self.tokens[body_start].line
        captures = []
        for c in nodes(n, "Capture"):
            mode = {"Capture.value": "plain", "Capture.move": "move", "Capture.copy": "copy",
                    "Capture.borrow": "ref", "Capture.borrow-exclusive": "ref_var",
                    "Capture.self": "ref", "Capture.self-exclusive": "ref_var"}[c.kind]
            names = [unescape_leaf(x) for x in leaves(c)]
            name = "self" if c.kind.startswith("Capture.self") else names[-1]
            captures.append(A.CaptureSpec(name=name, mode=mode, line=self.start_line(c)))
        params = []
        for p in nodes(n, "ClosureParam"):
            kids = nodes(p)
            params.append(A.ClosureParam(
                name=unescape_leaf(leaves(p)[0]),
                type_annotation=self.type(kids[0]) if kids else None,
                is_reference=p.kind != "ClosureParam.value",
                reference_mutable=p.kind == "ClosureParam.ref-exclusive",
                line=self.leaf_line(p, self.leaf_index(p, unescape_leaf(leaves(p)[0])))))
        stmts = [k for k in nodes(n) if k.base not in ("Capture", "ClosureParam")]
        body = self.block(n, stmts)
        body.line = body_line
        return A.ClosureExpr(parameters=params, body=body, capture_specs=captures, line=line,
                             column=column)

    def x_If(self, n):
        """One `if` and its arms, nested as the frozen parser nests them: each
        `else if` is the final expression of its predecessor's else block."""
        kids = nodes(n)
        arms = [(self.anchor(n, "IF"), self.if_head(kids[0]), self.block(kids[1]))]
        tail = None
        for k in kids[2:]:
            if k.base == "IfArm":
                head, body = nodes(k)
                line = self.anchor(k, "IF")
                arms.append((line, self.if_head(head), self.block(body)))
            else:
                tail = self.block(k)
        node = None
        for line, reading, then in reversed(arms):
            else_branch = tail
            if node is not None:
                else_branch = A.Block(statements=[], final_expr=node, line=node.line)
            node = self.make_if(line, reading, then, else_branch)
            tail = None
        return node

    def if_head(self, head):
        if head.base == "LetArm":
            kids = nodes(head)
            name, pattern = self.binding_target(kids[0])
            return ("let", name, pattern, self.binding_subject(head, kids[1:]),
                    head.kind == "LetArm.var")
        if head.base == "BorrowArm":
            kids = nodes(head)
            return ("borrow", unescape_leaf(leaves(kids[0])[0]), self.expr(kids[1]),
                    head.kind == "BorrowArm.var")
        return ("cond", self.expr(head))

    def make_if(self, line, reading, then, else_branch):
        if reading[0] == "let":
            _, name, pattern, subject, mutable = reading
            return A.IfLetExpr(name=name, optional_expr=subject, mutable=mutable,
                               then_branch=then, else_branch=else_branch, line=line,
                               pattern=pattern)
        if reading[0] == "borrow":
            _, name, place, mutable = reading
            return BorrowUnwrap(name=name, place=place, mutable=mutable, then_branch=then,
                                else_branch=else_branch, line=line)
        return A.IfExpr(condition=reading[1], then_branch=then, else_branch=else_branch,
                        line=line)

    def x_While(self, n):
        line = self.anchor(n, "WHILE")
        kids = nodes(n)
        if n.kind == "While.infinite":
            return A.WhileExpr(condition=None, body=self.block(kids[0]), line=line)
        if n.kind == "While.borrow":
            arm, body = kids
            ak = nodes(arm)
            return BorrowUnwrap(name=unescape_leaf(leaves(ak[0])[0]), place=self.expr(ak[1]),
                                mutable=arm.kind == "BorrowArm.var", then_branch=self.block(body),
                                is_loop=True, line=line)
        return A.WhileExpr(condition=self.expr(kids[0]), body=self.block(kids[1]), line=line)

    def x_WhileLet(self, n):
        line = self.anchor(n, "WHILE")
        kids = nodes(n)
        name, pattern = self.binding_target(kids[0])
        subject = self.expr(kids[1])
        body = self.block(kids[2])
        binding = A.IfLetExpr(
            name=name, optional_expr=subject, mutable=n.kind == "WhileLet.var",
            then_branch=body,
            else_branch=A.Block(statements=[A.BreakStatement(line=line)], final_expr=None,
                                line=line),
            line=line, pattern=pattern, while_let=True)
        return A.WhileExpr(condition=None,
                           body=A.Block(statements=[A.ExpressionStatement(expression=binding,
                                                                          line=line)],
                                        final_expr=None, line=line),
                           line=line, is_while_let=True)

    def x_For(self, n):
        line = self.anchor(n, "FOR")
        if n.kind == "For.borrow":
            fb = nodes(n, "ForBorrow")[0]
            name, seq, body = nodes(fb)
            return ForBorrow(variable=unescape_leaf(leaves(name)[0]), iterable=self.expr(seq),
                             body=self.block(body), mutable=fb.kind == "ForBorrow.var",
                             line=line)
        name, seq, body = nodes(n)
        return A.ForLoop(variable=unescape_leaf(leaves(name)[0]), iterable=self.expr(seq),
                         body=self.block(body), line=line)

    def x_Match(self, n):
        line = self.anchor(n, "MATCH")
        kids = nodes(n)
        subject = self.expr(kids[0])
        arms = []
        for arm in kids[1:]:
            aline = self.anchor(arm, "CASE")
            parts = nodes(arm)
            pattern = self.pattern(parts[0])
            guard = None
            if self.leaf_index(arm, "if") is not None:
                guard = self.expr(parts[1])
            body_node = parts[-1]
            if body_node.base == "Block":
                body = self.block(body_node)
            elif body_node.base in self.ARM_STATEMENTS:
                stmt = self.statement(body_node)
                body = A.Block(statements=[stmt], final_expr=None, line=stmt.line)
            else:
                body = self.expr(body_node)
            variant, bindings = _legacy_arm_shape(pattern)
            arms.append(A.MatchArm(variant_name=variant, bindings=bindings, body=body,
                                   line=aline, pattern=pattern, guard=guard))
        return A.MatchExpr(matched_expr=subject, arms=arms, line=line)

    ARM_STATEMENTS = ("Let", "DestructureLet", "Assign", "CompoundAssign", "OptionalAssign",
                      "Return", "Break", "Continue", "Lend", "Guard", "StaticAssert",
                      "AttributedLocal")

    def x_BorrowBlock(self, n):
        line = self.anchor(n, "BORROW")
        bindings = []
        for b in nodes(n, "BorrowBinding"):
            kids = nodes(b)
            name, pattern = self.binding_target(kids[0])
            bindings.append(BorrowBinding(name=name, pattern=pattern, value=self.expr(kids[1]),
                                          mutable=b.kind == "BorrowBinding.var",
                                          line=self.start_line(b)))
        return BorrowBlock(bindings=bindings, body=self.block(nodes(n, "Block")[0]), line=line)

    def x_BorrowPlace(self, n):
        line = self.anchor(n, "BORROW")
        return BorrowPlace(place=self.expr(nodes(n)[0]), mutable=n.kind == "BorrowPlace.var",
                           line=line)

    def x_OptionalChain(self, n):
        inner = self.expr(nodes(n)[0])
        return A.OptionalEvalExpr(expr=inner, line=inner.line)

    def x_OptionalMember(self, n):
        base = nodes(n)[0]
        k = self.leaf_index(n, unescape_leaf(leaves(n)[0]))
        line = self.before_leaf_line(n, k)
        return A.MemberAccess(object=A.BindOptional(expr=self.expr(base), line=line),
                              member=unescape_leaf(leaves(n)[0]), line=line)

    def x_Member(self, n):
        base = nodes(n)[0]
        k = [i for i, c in enumerate(n.children) if not _is_node(c)][0]
        line = self.before_leaf_line(n, k)
        return A.MemberAccess(object=self.expr(base), member=unescape_leaf(n.children[k]),
                              line=line)

    def x_TupleIndex(self, n):
        base = nodes(n)[0]
        k = [i for i, c in enumerate(n.children) if not _is_node(c)][0]
        line = self.before_leaf_line(n, k)
        return A.TupleIndex(tuple_expr=self.expr(base), index=int(unescape_leaf(n.children[k])),
                            line=line)

    def x_ForceUnwrap(self, n):
        inner = nodes(n)[0]
        expr = self.expr(inner)
        return A.ForceUnwrap(expr=expr, line=self.after_line(inner, "EXCLAIM"))

    def x_Subscript(self, n):
        kids = nodes(n)
        base = self.expr(kids[0])
        line = self.after_line(kids[0], "LBRACKET")
        if n.kind == "Subscript.multi":
            args = []
            for k in kids[1:]:
                if k.base == "Arg":
                    args.append(self.argument(k))
                else:
                    args.append(A.Argument(value=self.expr(k)))
            return MultiSubscript(array_expr=base, arguments=args, line=line)
        return A.ArrayIndex(array_expr=base, index=self.expr(kids[1]), line=line)

    def argument(self, a):
        value_node = nodes(a)[0]
        value = self.expr(value_node)
        if isinstance(value, A.ReferenceExpr):
            value.in_argument_position = True
        name = unescape_leaf(leaves(a)[0]) if a.kind == "Arg.labelled" else None
        return A.Argument(value=value, name=name)

    SPAWN_NAMESPACES = ("Thread", "Task")

    def x_Call(self, n):
        kids = nodes(n)
        if n.kind in ("Call.size", "Call.align"):
            name = "sizeof" if n.kind == "Call.size" else "alignof"
            line = self.anchor(n, "IDENT", value=name)
            return A.FunctionCall(name=name, arguments=[],
                                  type_args=[self.type_arg(k) for k in kids], line=line)
        callee, rest = kids[0], kids[1:]
        if callee.base == "Member":
            base = nodes(callee)[0]
            k = [i for i, c in enumerate(callee.children) if not _is_node(c)][0]
            name = unescape_leaf(callee.children[k])
            line = self.before_leaf_line(callee, k)
            obj = self.expr(base)
            targs = [self.type_arg(t) for t in nodes(callee)[1:]] or None
            args = self.call_arguments(callee, rest)
            if (name == "spawn" and isinstance(obj, A.Identifier)
                    and obj.name in self.SPAWN_NAMESPACES and not obj.type_args):
                return A.FunctionCall(name="%s.spawn" % obj.name, arguments=args, line=line)
            return A.MethodCall(object=obj, method_name=name, arguments=args, type_args=targs,
                                line=line)
        if callee.base == "OptionalMember":
            base = nodes(callee)[0]
            name = unescape_leaf(leaves(callee)[0])
            k = self.leaf_index(callee, name)
            line = self.before_leaf_line(callee, k)
            obj = A.BindOptional(expr=self.expr(base), line=line)
            targs = [self.type_arg(t) for t in nodes(callee)[1:]] or None
            return A.MethodCall(object=obj, method_name=name, arguments=self.call_arguments(callee, rest),
                                type_args=targs, line=line)
        if callee.base == "Name":
            name = unescape_leaf(leaves(callee)[0])
            line = self.leaf_line(callee, 0)
            targs = [self.type_arg(t) for t in nodes(callee)] or None
            args = self.call_arguments(callee, rest)
            labelled = [a for a in args if a.name is not None]
            # The frozen parser reads `name(label: ...)` as a construction,
            # unless a trailing closure makes it a call.
            if (n.kind == "Call.paren" and args and args[0].name is not None
                    and len(labelled) == len(args)):
                for a in args:
                    if isinstance(a.value, A.ReferenceExpr):
                        a.value.in_argument_position = False
                return A.StructInit(struct_name=name,
                                    field_inits=[(a.name, a.value) for a in args],
                                    type_args=targs, line=line)
            return A.FunctionCall(name=name, arguments=args, type_args=targs, line=line)
        callee_expr = self.expr(callee)
        return CallExpr(callee=callee_expr, arguments=self.call_arguments(callee, rest),
                        line=callee_expr.line)

    def call_arguments(self, callee, rest):
        """The arguments of a call. Its `(` is taken first, so that a `(`
        opening the next statement is never mistaken for an empty list's."""
        last = self.last.get(id(callee))
        if self.interp is None and last is not None:
            for i in range(last + 1, len(self.tokens)):
                kind = self.tokens[i].kind
                if kind == "LPAREN":
                    self.cursor = max(self.cursor, i + 1)
                if kind not in ("RPAREN", "RBRACKET", "GT", "NEWLINE"):
                    break
        args = []
        for k in rest:
            if k.base == "Arg":
                args.append(self.argument(k))
            else:
                args.append(A.Argument(value=self.expr(k), name=None))
        return args

    # -- patterns ----------------------------------------------------------------

    def pattern(self, n):
        b = n.base
        if b == "WildcardPat":
            return A.WildcardPattern(line=self.anchor(n, "IDENT", value="_"))
        if b == "NamePat":
            name = unescape_leaf(leaves(n)[0])
            line = self.leaf_line(n, 0)
            if name[:1].isupper():
                return A.EnumPattern(variant_name=name, subpatterns=[], line=line)
            return A.BindingPattern(name=name, line=line)
        if b == "NonePat":
            return A.EnumPattern(variant_name="None", subpatterns=[],
                                 line=self.anchor(n, "NONE"))
        if b == "VariantPat":
            name = unescape_leaf(leaves(n)[0])
            return A.EnumPattern(variant_name=name,
                                 subpatterns=[self.pattern(k) for k in nodes(n)],
                                 line=self.leaf_line(n, 0))
        if b == "BorrowBindPat":
            name = unescape_leaf(leaves(n)[0])
            return BorrowBindingPattern(name=name, mutable=n.kind == "BorrowBindPat.var",
                                        line=self.anchor(n, "BORROW"))
        if b == "TuplePat":
            line = self.anchor(n, "LPAREN")
            return A.TuplePattern(elements=[self.pattern(k) for k in nodes(n)], line=line)
        if b == "LiteralPat":
            return A.LiteralPattern(value=self.literal_pattern(n), line=self.start_line(n))
        if b == "RangePat":
            line = self.start_line(n)
            ints = self.pattern_ints(n)
            return A.RangePattern(start=ints[0], end=ints[1],
                                  is_inclusive=n.kind == "RangePat.inclusive", line=line)
        raise ReadingError("%s: no reading of the pattern %s" % (self.path, n.kind))

    def literal_pattern(self, n):
        line = self.start_line(n)
        if n.kind in ("LiteralPat.int", "LiteralPat.negative-int"):
            return self.pattern_ints(n)[0]
        if n.kind == "LiteralPat.string":
            return A.StringLiteral(value=decode_string(unescape_leaf(leaves(n)[0])), line=line)
        return A.BoolLiteral(value=n.kind == "LiteralPat.true", line=line)

    def pattern_ints(self, n):
        """The integer endpoints a literal or range pattern prints, each with
        its `-` when it is negative."""
        out = []
        negative = False
        for k, c in enumerate(n.children):
            text = unescape_leaf(c)
            if text == "-":
                negative = True
                continue
            if not re.match(r"[0-9]", text):
                continue
            value, suffix = decode_int(text)
            line = self.leaf_line(n, k)
            lit = A.IntLiteral(value=value, suffix=suffix, line=line)
            if negative or n.kind == "LiteralPat.negative-int":
                lit = A.UnaryOp(op="-", operand=lit, line=line)
            out.append(lit)
            negative = False
        if n.kind == "LiteralPat.negative-int" and out and not isinstance(out[0], A.UnaryOp):
            out[0] = A.UnaryOp(op="-", operand=out[0], line=out[0].line)
        return out


def _legacy_arm_shape(pattern):
    """(variant_name, bindings) of an arm, as the frozen parser's
    `_legacy_arm_shape` derives them."""
    if isinstance(pattern, A.WildcardPattern):
        return "_", []
    if isinstance(pattern, A.EnumPattern):
        names = []
        for sub in pattern.subpatterns:
            if isinstance(sub, A.WildcardPattern):
                names.append("_")
            elif isinstance(sub, A.BindingPattern):
                names.append(sub.name)
            else:
                return "", []
        return pattern.variant_name, names
    return "", []


class Reading:
    """One file as sawc2 reads it: its tokens, the frozen-shaped Program and
    the new-language forms it holds (`Reader.features`), or sawc2's first
    refusal, (line, message)."""

    def __init__(self, tokens=None, program=None, features=(), error=None):
        self.tokens = tokens
        self.program = program
        self.features = list(features)
        self.error = error


def read_files(paths):
    """{path: Reading} for `paths`, every file parsed by one sawc2 process."""
    parsed = parse_files(paths)
    out = {}
    for path in paths:
        verdict = parsed[path]
        if verdict[0] == "error":
            out[path] = Reading(error=(verdict[1], verdict[2]))
            continue
        tokens, error = lex_file(path)
        if error is not None:
            raise ReadingError("%s: sawc2 parses it but `sawc2 lex` refuses it: %s"
                               % (path, error[1]))
        reader = Reader(path, tokens, verdict[1])
        out[path] = Reading(tokens=tokens, program=reader.program(), features=reader.features)
    return out


def main(argv):
    for path, reading in read_files(argv).items():
        print(path)
        if reading.error is not None:
            print("  refused at line %d: %s" % reading.error)
        else:
            print(reading.program)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

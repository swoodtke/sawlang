"""The grammar pass: removed productions, the meaning-preservation check, and
grammar flips.

A ruling that changes how an accepted text parses would change a migrated
file's meaning silently. Each detector finds the sawc AST shapes a ruling
reads differently, and proposes the parentheses that spell sawc's reading.
A candidate becomes a site only when two checks agree: sawc's AST is the same
with the parentheses (they spell its reading), and the reference recognizer's
tree is not (the grammar read the original differently). Parentheses are
transparent in both trees, so the second check is exact.

ENTRY POINTS
    meaning_sites
    removed_form_edits
    parse_outcomes
"""
import dataclasses

import edits
import verify
from edits import Edit, TokenType

from ast_nodes import (  # noqa: E402
    ArrayIndex, BinaryOp, BindOptional, CastExpr, ForceUnwrap, IntLiteral, MemberAccess,
    MethodCall, NilCoalesce, OptionalEvalExpr, RangeExpr, ReferenceExpr, SawType, TryExpr,
    TupleIndex, TypeKind, UnaryOp,
)
from ast_walk import child_nodes, structural_fields  # noqa: E402
from lexer import Lexer  # noqa: E402
from parser import Parser  # noqa: E402

SKIP_FIELDS = {"line", "column", "node_id", "origin_node_id", "source_file", "source_path",
               "doc", "module_doc", "file_module_docs"}
# The operands the prefix tier covers alone (GRAMMAR.md, syntax.expr.prefix).
POSTFIX_OR_PRIMARY_NOT = (CastExpr, BinaryOp, NilCoalesce)

RULINGS = {
    "Q1": "SL-400.Q1-prefix-binds-tighter-than-as",
    "Q2": "SL-400.Q2-try-covers-its-operand",
    "Q3": "SL-400.Q3-coalesce-groups-right",
    "Q5": "SL-400.Q5-parenthesized-type-is-grouping",
    "cast": "SL-406.c24-cast-target-generic-is-local",
    "spaced": "SL-406.c11-spaced-call-is-a-call",
}


# ------------------------------------------------------------------ sawc trees
def sawc_parse(text, path="x.saw"):
    lexer = Lexer(text)
    return Parser(lexer.tokenize(), source_file=path, doc_comments=lexer.doc_comments).parse()


def shape(value, seen=None):
    """A position-free serialization of a sawc AST value."""
    if isinstance(value, SawType):
        return ("T", str(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__,) + tuple(
            (f.name, shape(getattr(value, f.name))) for f in structural_fields(value)
            if f.name not in SKIP_FIELDS)
    if isinstance(value, (list, tuple)):
        return tuple(shape(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, shape(v)) for k, v in value.items()))
    return value


def text_shape(text):
    try:
        return shape(sawc_parse(text))
    except Exception:  # noqa: BLE001 - a text sawc refuses has no shape
        return None


def expr_shape(snippet):
    wrapper = "func __migrate_probe() {\n    let __x = (%s\n)\n}\n" % snippet
    try:
        program = sawc_parse(wrapper)
    except Exception:  # noqa: BLE001 - a span that is no expression has no shape
        return None
    return shape(program.functions[0].body.statements[0].value)


def walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(child_nodes(n))


def leftmost(node):
    """The node a sawc expression's first token belongs to. A prefix
    operator's node is anchored at its own token, so the walk stops there."""
    while True:
        if isinstance(node, CastExpr):
            node = node.expr
        elif isinstance(node, BinaryOp):
            node = node.left
        elif isinstance(node, NilCoalesce):
            node = node.expr
        elif isinstance(node, RangeExpr) and node.start is not None:
            node = node.start
        elif isinstance(node, (MemberAccess, ArrayIndex, TupleIndex, ForceUnwrap,
                               BindOptional, OptionalEvalExpr)):
            node = step(node)
        elif isinstance(node, MethodCall) and not getattr(node, "is_static_method_call", False):
            node = node.object
        else:
            return node


def step(node):
    if isinstance(node, MemberAccess):
        return node.object
    if isinstance(node, ArrayIndex):
        return node.array_expr
    if isinstance(node, TupleIndex):
        return node.tuple_expr
    return node.expr


# ------------------------------------------------------------------ spans
def span_end(src, start_i, node):
    """The offset just past the tokens starting at `start_i` that spell
    `node` exactly, or None."""
    want = shape(node)
    j, n, balance = start_i, 0, 0
    while j is not None and n < 400:
        kind = src.tokens[j].kind
        if kind in edits.OPENERS:
            balance += 1
        elif kind in edits.OPENERS.values():
            balance -= 1
            if balance < 0:
                return None
        elif kind == TokenType.NEWLINE and balance == 0:
            return None
        end = src.end_of(j)
        if expr_shape(src.text[src.tokens[start_i].off:end]) == want:
            return end
        j = src.next(j)
        n += 1
    return None


def wrap(src, start_i, node):
    """Parentheses around the tokens that spell `node`. Its first sawc node may
    sit inside parentheses the node starts with, so each opener just before
    it is a candidate start too."""
    i = start_i
    while i is not None:
        end = span_end(src, i, node)
        if end is not None:
            off = src.tokens[i].off
            return [Edit(off, off, "("), Edit(end, end, ")")]
        i = src.prev(i)
        if i is None or src.tokens[i].kind != TokenType.LPAREN:
            return None
    return None


# ------------------------------------------------------------------ detectors
def candidates(program, src):
    """[(ruling, line, col, edits or None)] proposed from sawc's AST."""
    out = []
    for n in walk(program):
        if isinstance(n, (UnaryOp, ReferenceExpr)) and isinstance(
                getattr(n, "operand", None) or getattr(n, "expr", None), CastExpr):
            inner = getattr(n, "operand", None) or getattr(n, "expr", None)
            out.append(("Q1", n, inner))
        elif (isinstance(n, ArrayIndex) and isinstance(n.array_expr, CastExpr)
              and isinstance(n.index, IntLiteral)):
            out.append(("Q1", n, n.array_expr))
        elif isinstance(n, TryExpr) and isinstance(n.expr, POSTFIX_OR_PRIMARY_NOT):
            out.append(("Q2", n, n.expr))
        elif isinstance(n, NilCoalesce) and isinstance(n.expr, NilCoalesce):
            out.append(("Q3", n, n.expr))
        elif isinstance(n, BinaryOp) and n.op == "<" and isinstance(n.left, CastExpr):
            out.append(("cast", n, n.left))
        elif isinstance(n, CastExpr) and "<" in str(n.target_type):
            out.append(("cast", n, n))
    found = []
    for ruling, holder, inner in out:
        first = leftmost(inner)
        i = src.index_at(first.line, first.column) if getattr(first, "line", 0) else None
        found.append((ruling, holder.line, holder.column,
                      wrap(src, i, inner) if i is not None else None))
    return found


def one_tuple_types(src, program):
    """Q5: a `(T)` type sawc reads as a one-element tuple, as `(T,)` edits.
    The type has no position, so the parenthesized spans in type position
    are found by tokens and confirmed by the shape checks."""
    found = []
    has = any(isinstance(v, SawType) and v.kind == TypeKind.TUPLE and len(v.element_types or []) == 1
              for v in types_in(program))
    if not has:
        return found
    for i, t in enumerate(src.tokens):
        if t.kind != TokenType.LPAREN:
            continue
        close = src.match_close(i)
        if close is None:
            continue
        before = src.prev(i)
        after = src.next(close)
        if before is None or src.tokens[before].kind not in (
                TokenType.COLON, TokenType.ARROW, TokenType.LT, TokenType.COMMA, TokenType.AS):
            continue
        # A function type's parameter list is followed by its effects or `->`.
        if after is not None and (src.tokens[after].kind in (TokenType.ARROW, TokenType.UNSAFE,
                                                             TokenType.BORROWS)
                                  or src.tokens[after].value in ("sync", "escaping")):
            continue
        inner_last = src.prev(close)
        if inner_last is None or inner_last == i or src.tokens[inner_last].kind == TokenType.COMMA:
            continue
        # Only a single element: no comma at the parenthesis' own depth.
        j, depth, comma = src.next(i), 0, False
        while j is not None and j != close:
            k = src.tokens[j].kind
            if k in edits.OPENERS:
                j = src.match_close(j)
            elif k == TokenType.COMMA:
                comma = True
                break
            j = src.next(j)
        if comma:
            continue
        end = src.end_of(inner_last)
        found.append(("Q5", t.line, t.col, [Edit(end, end, ",")]))
    return found


def types_in(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, SawType):
        yield value
        for f in dataclasses.fields(value):
            yield from types_in(getattr(value, f.name), seen)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from types_in(getattr(value, f.name), seen)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from types_in(v, seen)


def spaced_calls(src):
    """A call written with a space before its `(`, as removals of the space."""
    found = []
    for i, t in enumerate(src.tokens):
        if t.kind != TokenType.LPAREN or t.depth:
            continue
        p = src.prev(i)
        if p is None or src.tokens[p].kind not in (TokenType.IDENT, TokenType.RPAREN,
                                                   TokenType.RBRACKET):
            continue
        end = src.end_of(p)
        gap = src.text[end:t.off]
        if gap and gap.strip() == "" and "\n" not in gap:
            found.append(("spaced", t.line, t.col, [Edit(end, t.off, "")]))
    return found


class MeaningSite:
    def __init__(self, ruling, line, col, status, edits_, reason=""):
        self.ruling, self.line, self.col, self.status = ruling, line, col, status
        self.edits, self.reason = edits_, reason


def meaning_sites(text):
    """([MeaningSite], note): the sites whose reading differs, with the
    parentheses that keep sawc's, plus flags where a check cannot decide."""
    try:
        program = sawc_parse(text)
    except Exception:  # noqa: BLE001 - a text sawc refuses has no reading to keep
        return [], "sawc refuses the text"
    if verify.verdict(text) != "OK":
        return [], "the grammar refuses the text"
    src = edits.Source(text)
    base_shape = shape(program)
    base_tree, _ = verify.tree(text)
    base_tree = [verify.erase(i) for i in base_tree]
    sites = []
    for ruling, line, col, eds in candidates(program, src) + one_tuple_types(src, program) + spaced_calls(src):
        name = RULINGS[ruling]
        if eds is None:
            sites.append(MeaningSite(name, line, col, "flagged", [], "the span of sawc's reading was not found"))
            continue
        new = edits.apply(text, eds)
        if text_shape(new) != base_shape:
            if ruling == "spaced":
                sites.append(MeaningSite(name, line, col, "flagged", [],
                                         "removing the space changes sawc's reading"))
            else:
                sites.append(MeaningSite(name, line, col, "flagged", [],
                                         "the explicit spelling changes sawc's reading"))
            continue
        tree, why = verify.tree(new)
        if tree is None:
            sites.append(MeaningSite(name, line, col, "flagged", [],
                                     "the explicit spelling is refused by the grammar (%s)" % why))
            continue
        if [verify.erase(i) for i in tree] == base_tree:
            continue
        if ruling == "spaced":
            sites.append(MeaningSite(name, line, col, "flagged", [],
                                     "the grammar reads the spaced call differently"))
        else:
            sites.append(MeaningSite(name, line, col, "rewritten", eds))
    return sites, None


# ------------------------------------------------------------------ removed forms
def export_edits(src):
    """`export m.f [as g]` / `export m.*` to the `public import` fixit
    (GRAMMAR.md, syntax.decl.refused-export)."""
    out = []
    for i, t in enumerate(src.tokens):
        # `export` is a contextual word at the head of a top-level item.
        if t.depth or not (t.kind == TokenType.EXPORT or (t.kind == TokenType.IDENT and t.value == "export")):
            continue
        p = src.prev(i)
        if p is not None and src.tokens[p].kind != TokenType.NEWLINE:
            continue
        j = src.next(i)
        path = []
        while j is not None and src.tokens[j].kind in (TokenType.IDENT, TokenType.DOT, TokenType.STAR):
            path.append(j)
            j = src.next(j)
        if not path:
            return None
        last, alias = path[-1], None
        if j is not None and src.tokens[j].kind == TokenType.AS:
            k = src.next(j)
            if k is None or src.tokens[k].kind != TokenType.IDENT:
                return None
            alias, last = src.tokens[k].value, k
            j = src.next(k)
        if j is not None and src.tokens[j].kind != TokenType.NEWLINE:
            return None
        text = "".join(str(src.tokens[p].value) for p in path)
        if text.endswith(".*"):
            new = "public import %s" % text
        else:
            module, _, name = text.rpartition(".")
            if not module or not name:
                return None
            new = "public import %s.{%s}" % (module, name if alias is None else "%s as %s" % (name, alias))
        out.append((t.line, t.col, Edit(t.off, src.end_of(last), new)))
    return out


def removed_form_edits(text, reason):
    """(edits, flag reason) for a non-error file the grammar refuses by a
    removed production, per corpus_expected.tsv's `a-removed:` reason."""
    forms = [f.strip() for f in reason.split(":", 1)[1].split(",")]
    if forms == ["syntax.decl.refused-export"]:
        found = export_edits(edits.Source(text))
        if not found:
            return None, "an `export` declaration the fixit does not cover"
        return found, None
    if "syntax.expr.refused-lend-var" in forms:
        return None, "`#lend_var` (K1): the two accessors are written by hand"
    return None, "removed production(s) %s with no replacement settled for U3" % ", ".join(forms)


# ------------------------------------------------------------------ flips
def frozen_error(text, path):
    """The frozen lexer's or parser's first complaint about `text`, or None."""
    try:
        sawc_parse(text, path)
    except Exception as e:  # noqa: BLE001 - any refusal, a crash included, is not acceptance
        return (str(e).strip().split("\n") or ["?"])[0][:160]
    return None


def parse_outcomes(original, migrated, path):
    """(the frozen parser's complaint about the original or None, whether the
    grammar accepts the migration)."""
    return frozen_error(original, path), verify.verdict(migrated) == "OK"

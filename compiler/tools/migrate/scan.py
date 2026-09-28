"""The parser-only scan: candidate retired shapes where the instrument is blind.

The place pass walks function and method bodies only, and only in a file an
entry lowered. Everywhere else -- trait default bodies, static initializers,
default parameter values, and whole files that fail before lowering -- a
subscript or a call to an accessor-named method may be a retired place use,
and nothing says which. Each such candidate is flagged; none is rewritten
(SL:borrow-survey, Limitations).
"""
import glob
import os

import layout
import edits  # noqa: F401  (puts sawc on sys.path)

from ast_nodes import ArrayIndex, MethodCall  # noqa: E402
from ast_walk import child_nodes  # noqa: E402
from lexer import Lexer  # noqa: E402
from parser import Parser  # noqa: E402

# The std closure-borrow APIs (SL:borrow-survey §E); their visitor siblings stay.
CLOSURE_BORROW_APIS = ("with_ref", "with_var_ref", "lock", "try_lock", "with_unique")


def parse(text, path):
    lexer = Lexer(text)
    tokens = lexer.tokenize()
    return Parser(tokens, source_file=path, doc_comments=lexer.doc_comments).parse()


def borrows_names(program, acc):
    for ext in getattr(program, "extensions", None) or []:
        for m in getattr(ext, "methods", None) or []:
            if getattr(m, "is_borrows", False):
                acc.add(m.name)
    for tr in getattr(program, "traits", None) or []:
        for m in getattr(tr, "methods", None) or []:
            if getattr(m, "is_borrows", False):
                acc.add(m.name)
    for fn in getattr(program, "functions", None) or []:
        if getattr(fn, "is_borrows", False):
            acc.add(fn.name)
    for md in getattr(program, "module_decls", None) or []:
        if getattr(md, "body", None) is not None:
            borrows_names(md.body, acc)
    return acc


def accessor_names(root=layout.REPO):
    """Every method name declared `borrows` in std or in the source corpus."""
    names = set()
    paths = sorted(glob.glob(os.path.join(root, "sawc", "std", "**", "*.saw"), recursive=True))
    paths.append(os.path.join(root, "sawc", "builtin.saw"))
    paths += [os.path.join(root, p) for p in layout.tracked(layout.SOURCE, root) if p.endswith(".saw")]
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                borrows_names(parse(fh.read(), p), names)
        except Exception:  # noqa: BLE001 - a file the parser refuses declares nothing it can read
            continue
    return names


def regions(program, walked):
    """(region, node) pairs the instrument did not see."""
    def decl_regions(decl, kind):
        for p in getattr(decl, "parameters", None) or []:
            if getattr(p, "default_value", None) is not None:
                yield "default parameter value", p.default_value
        if getattr(decl, "body", None) is not None and (decl.line, decl.column) not in walked:
            yield kind, decl.body

    for fn in getattr(program, "functions", None) or []:
        yield from decl_regions(fn, "unlowered function body")
    for ext in getattr(program, "extensions", None) or []:
        for m in getattr(ext, "methods", None) or []:
            yield from decl_regions(m, "unlowered method body")
    for tr in getattr(program, "traits", None) or []:
        for m in getattr(tr, "methods", None) or []:
            for p in getattr(m, "parameters", None) or []:
                if getattr(p, "default_value", None) is not None:
                    yield "default parameter value", p.default_value
            if getattr(m, "body", None) is not None:
                yield "trait default body", m.body
    for st in getattr(program, "statics", None) or []:
        if getattr(st, "initializer", None) is not None:
            yield "static initializer", st.initializer
    for sa in getattr(program, "static_asserts", None) or []:
        yield "static assertion", sa.condition
    for md in getattr(program, "module_decls", None) or []:
        if getattr(md, "body", None) is not None:
            yield from regions(md.body, walked)


def candidates(program, walked, accessors):
    """[(line, column, region, shape)] in source order."""
    out = []
    for region, node in regions(program, walked):
        stack = [node]
        while stack:
            n = stack.pop()
            if isinstance(n, ArrayIndex):
                out.append((n.line, n.column, region, "subscript"))
            elif isinstance(n, MethodCall):
                if n.method_name in CLOSURE_BORROW_APIS:
                    out.append((n.line, n.column, region, "closure-borrow call `%s`" % n.method_name))
                elif n.method_name in accessors:
                    out.append((n.line, n.column, region, "call to accessor-named `%s`" % n.method_name))
            stack.extend(child_nodes(n))
    return sorted(set(out))

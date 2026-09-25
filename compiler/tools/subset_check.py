#!/usr/bin/env python3
"""Refuse, in the self-hosted compiler's source, the shapes Stage 0 mishandles.

Each rule in `RULES` enforces one subset rule or one checkable hazard entry and
names that source in its diagnostic. The frozen compiler's own lexer and parser
read the source, so the checker sees exactly what Stage 0 reads.

    python compiler/tools/subset_check.py          # compiler/**/*.saw, no tests/ or sidecars
    python compiler/tools/subset_check.py FILE...  # each file as a unit program
"""
import dataclasses
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "sawc"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ast_nodes as A  # noqa: E402
from lexer import Lexer, TokenType as T  # noqa: E402
from parser import Parser  # noqa: E402
from build import STAGE_PACKAGES  # noqa: E402

ARCH = "SL:architecture §4"

RULES = {
    "lex": ARCH + ": the frozen lexer must accept the source",
    "parse": ARCH + ": the frozen parser must accept the source",
    "file-end": "SL:hazards C2",
    "sync-only": ARCH,
    "closure-capture": ARCH,
    "type-alias": ARCH + "; SL:hazards S9",
    "prelude-type-name": ARCH + "; SL:hazards L17",
    "selective-imports": ARCH + "; SL:hazards L3",
    "import-allowlist": ARCH + ": the compiler's std cone",
    "std-api": ARCH + ": the API allowlist",
    "borrows-accessor": ARCH + ": accessors belong to the new std",
    "generic-extension-init": ARCH + "; SL:hazards S1",
    "integer-overload": ARCH + "; SL:hazards L1",
    "any-type": ARCH + "; SL:hazards S12",
    "box-type": ARCH + "; SL:hazards L8",
    "cell-type": ARCH + "; SL:hazards S11, S15",
    "raw-pointer": ARCH + "; SL:hazards C1",
    "fixed-array": ARCH + "; SL:hazards L7",
    "value-loop": ARCH + "; SL:hazards L11",
    "statement-arm": ARCH + "; SL:hazards L13, C4",
    "borrow-syntax": ARCH,
    "test-directive": ARCH,
    "deinit-body": "SL:hazards: leaks are tolerated in Stage 1",
    "borrowed-match-payload": "SL:hazards S2",
    "root-reuse": "SL:hazards S4",
    "var-ref-into-let": "SL:hazards S5",
    "function-exit": "SL:hazards S6",
    "int-literal-range": "SL:hazards S7",
    "enum-equatable-body": "SL:hazards S8",
    "nested-optional": "SL:hazards S10",
    "argument-labels": "SL:hazards S14",
    "index-receiver-call": "SL:hazards S15",
    "cast-then-optional": "SL:hazards S17",
    "program-unique-names": "SL:hazards S18",
    "written-type-shape": ARCH + "; SL:hazards S19",
    "float-literal": ARCH + "; SL:hazards S20",
    "interpolation-line-break": "SL:hazards S21",
    "inline-module": "SL:hazards S22",
    "from-raw-literal": "SL:hazards L1",
    "closure-syntax": "SL:hazards L2",
    "default-value-literal": "SL:hazards L3",
    "optional-shaping": "SL:hazards L4",
    "empty-struct": "SL:hazards L5",
    "bounded-extension": "SL:hazards L6",
    "name-collision": "SL:hazards L9",
    "type-param-receiver": "SL:hazards L10",
    "leading-minus": "SL:hazards L12",
    "nesting-depth": "SL:hazards L14",
    "chain-length": "SL:hazards L14",
    "generic-extension-params": "SL:hazards L18",
    "interpolation-content": "SL:hazards C3",
}

# The std modules the compiler may import. The bootstrap std unit must build
# every module on this list, so each addition widens that unit's cone. Stage 1
# may skip drops, so an addition also re-checks that every std `deinit` it
# reaches only frees memory or closes a descriptor (SL:hazards, leak tolerance).
ALLOWED_STD_MODULES = ("env", "file", "path")

PACKAGE_RELATIVE_HEADS = ("src", "parent", "package")

# The std members the compiler may call, each meaning the same under `sawc/std`
# (Stage 0) and the new std (Stage 1): a free function or constructor by name, a
# static member as `Type.member`, an instance method as `.name`. An addition
# re-checks the `deinit` condition `ALLOWED_STD_MODULES` states.
STD_API = (
    "print", "panic", "assert",
    "Byte", "Path", "Scalar", "StringBuilder", "Vector",
    "Env.args", "File.open", "UInt8.from", "Result.Ok", "Result.Err",
    ".append", ".build", ".byte_at", ".clear", ".equals", ".get", ".is_empty", ".len",
    ".push", ".read", ".starts_with", ".substring", ".to_string", ".to_uint",
)

# Std calls the lockdown retires, refused by name whatever the allowlist says.
RETIRED_STD_METHODS = ("with_ref", "with_var_ref", "with_unique")

SYNC_ONLY_NAMES = ("TaskGroup", "Task", "VoidTask", "Thread", "VoidThread", "Channel",
                   "sleep", "cancelled", "yield_now", "dump_tasks", "spawn")
CELL_NAMES = ("Mutex", "SpinLock", "Once", "UnsafeMutableInterior", "Atomic", "Arc")
# The frozen parser's raw-pointer spellings. The other unsafe types are the
# `unsafe struct`s std declares, which `StdFacts` collects.
POINTER_TYPE_NAMES = ("UnsafePointer", "UnsafeConstPointer")
COLLECTIONS = ("Vector", "Map", "Set")
NON_INT_INTEGERS = (A.TypeKind.UINT, A.TypeKind.INT8, A.TypeKind.INT16, A.TypeKind.INT32,
                    A.TypeKind.INT64, A.TypeKind.UINT8, A.TypeKind.UINT16,
                    A.TypeKind.UINT32, A.TypeKind.UINT64)
UNSIGNED_64 = (A.TypeKind.UINT, A.TypeKind.UINT64)
INT_MAX = (1 << 63) - 1

# Methods a call may reach through an indexed receiver or a `get` result: each
# only reads it, so a copy of the element gives the same answer.
READ_ONLY_METHODS = ("byte_at", "compare", "contains", "contains_key", "copy", "ends_with",
                     "equals", "get", "hash", "index_of", "is_empty", "is_none", "is_some",
                     "len", "starts_with", "substring", "to_string")

MAX_NESTING = 30
MAX_CHAIN = 100
# A written type nests fewer levels than the lowest depth bound among the
# frozen compiler's type walks (SL:hazards S19).
MAX_TYPE_DEPTH = 7

STATEMENT_KEYWORDS = (T.RETURN, T.BREAK, T.CONTINUE, T.LET, T.VAR, T.GUARD, T.WHILE, T.FOR)
# The tokens that can end an operand. A `*` or `-` after one, across any newline
# the parser skips, is a binary operator; after anything else it is a prefix
# operator, except that `.*` is an import glob.
OPERAND_END = (T.IDENT, T.INT, T.FLOAT, T.STRING, T.INTERP_STRING, T.RPAREN, T.RBRACKET,
               T.RBRACE, T.SELF, T.TRUE, T.FALSE, T.NONE, T.EXCLAIM, T.QUESTION,
               T.HASH_DIRECTIVE, T.DOLLAR_PARAM)

_POS_RE = re.compile(r"at (\d+):(\d+)(: )?")


@dataclasses.dataclass(frozen=True, order=True)
class Diagnostic:
    path: str
    line: int
    rule: str
    message: str

    def render(self):
        return "%s:%d: %s: %s (%s)" % (self.path, self.line, self.rule, self.message,
                                       RULES[self.rule])


class SourceFile:
    """One file: its text, the frozen lexer's tokens and the frozen parser's tree."""

    def __init__(self, path):
        self.path = path
        self.rel = os.path.relpath(path, REPO)
        with open(path, encoding="utf-8") as fh:
            self.text = fh.read()
        self.tokens = None
        self.program = None
        self.lex_error = None
        self.parse_error = None
        lexer = Lexer(self.text)
        try:
            self.tokens = lexer.tokenize()
        except Exception as exc:  # the frozen lexer raises more than SyntaxError
            self.lex_error = _position(exc)
            return
        try:
            self.program = Parser(self.tokens, source_file=path,
                                  doc_comments=lexer.doc_comments).parse()
        except Exception as exc:
            self.parse_error = _position(exc)


def _position(exc):
    """The line and message of a frozen lexer or parser error. The first
    position is the file's: an error inside an interpolation nests the inner
    lexer's, whose line 1 is the interpolation's, after it."""
    text = str(exc) or type(exc).__name__
    found = list(_POS_RE.finditer(text))
    if not found:
        return 1, "%s: %s" % (type(exc).__name__, text.split("\n")[0])
    first = found[0]
    if first.group(3):
        return int(first.group(1)), text[first.end():].split("\n")[0]
    message = text[:first.start()].strip()
    for inner in found[1:]:
        if inner.group(3):
            message += ": " + text[inner.end():].split("\n")[0]
            break
    return int(first.group(1)), message


def programs(prog):
    """`prog` and every inline `module m { ... }` body inside it, outermost first."""
    stack = [prog]
    while stack:
        p = stack.pop()
        yield p
        for md in reversed(p.module_decls):
            if md.body is not None:
                stack.append(md.body)


# ---------------------------------------------------------------------------
# Facts about std and the builtins, which share the program with the compiler.
# ---------------------------------------------------------------------------

class StdFacts:
    def __init__(self):
        from mono_identity import PRIMITIVE_TYPE_NAMES
        self.names = {}
        self.generic_functions = set()
        self.generic_methods = set()
        self.types = set(PRIMITIVE_TYPE_NAMES) | {"Void", "Never"}
        # Names a compiler type may not take: every type the builtins or a std
        # module make public, gated or not (SL:hazards L17).
        self.reserved_types = set(self.types)
        self.methods = set()
        self.borrows_methods = set()
        self.unsafe_types = set(POINTER_TYPE_NAMES)
        self.generic_types = set()
        self.method_kinds = {}
        std_dir = os.path.join(REPO, "sawc", "std")
        paths = sorted(glob.glob(os.path.join(std_dir, "**", "*.saw"), recursive=True))
        paths.append(os.path.join(REPO, "sawc", "builtin.saw"))
        for path in paths:
            src = SourceFile(path)
            if src.program is None:
                raise RuntimeError("subset_check: cannot parse %s" % src.rel)
            builtin = path.endswith("builtin.saw")
            for prog in programs(src.program):
                self._collect(prog, src.rel, builtin)

    def _collect(self, prog, rel, builtin):
        for fn in prog.functions:
            self.names.setdefault(fn.name, rel)
            if fn.type_params:
                self.generic_functions.add(fn.name)
        for st in prog.statics:
            self.names.setdefault(st.name, rel)
        for decl in prog.structs + prog.enums + prog.traits + prog.type_definitions:
            self.types.add(decl.name)
            if builtin or decl.visibility != A.Visibility.PRIVATE:
                self.reserved_types.add(decl.name)
        for s in prog.structs:
            if s.is_unsafe:
                self.unsafe_types.add(s.name)
        for decl in prog.structs + prog.enums:
            if decl.type_params:
                self.generic_types.add(decl.name)
        for tr in prog.traits:
            self.methods.update(m.name for m in tr.methods)
        for ext in prog.extensions:
            for m in ext.methods:
                self.methods.add(m.name)
                if m.type_params or ext.type_params:
                    self.generic_methods.add(m.name)
                if m.is_borrows and m.name != "[]":
                    self.borrows_methods.add(m.name)
                if not m.is_init:
                    kind = "static" if m.is_static else "instance"
                    self.method_kinds.setdefault((ext.struct_name, m.name), set()).add(kind)


_STD = None


def std_facts():
    global _STD
    if _STD is None:
        _STD = StdFacts()
    return _STD


def _mutates_self(m):
    return bool(getattr(m, "self_mutable", False) or getattr(m, "is_consumes", False))


def _instance_method(m):
    return not getattr(m, "is_static", False) and not getattr(m, "is_init", False)


def _shared_type(types):
    if not types or any(t != types[0] for t in types[1:]):
        return None
    return types[0]


class BuildFacts:
    """What one build's own files declare, inline modules included: the names a
    call may resolve to without reaching std, and the written types an
    expression's type is traced through."""

    def __init__(self, files):
        self.functions = set()
        self.generic_functions = set()
        self.void_functions = set()
        self.statics = set()
        self.modules = set()
        self.module_bodies = {}
        self.types = set()
        self.generic_types = set()
        self.enums = set()
        self.methods = set()
        self.borrows_methods = set()
        self.borrows_owned = set()
        self.fields = {}
        self.variants = {}
        self.returns = {}
        self.method_returns = {}
        self.method_mutates = {}
        self.name_mutates = {}
        nonvoid = set()
        for f in files:
            if f.program is None:
                continue
            for prog in programs(f.program):
                self._collect(prog, nonvoid)
        self.void_functions -= nonvoid

    def _collect(self, prog, nonvoid):
        for md in prog.module_decls:
            self.modules.add(md.name)
            if md.body is not None:
                self.module_bodies.setdefault(md.name, []).append(md.body)
        for fn in prog.functions:
            self.functions.add(fn.name)
            if fn.type_params:
                self.generic_functions.add(fn.name)
            self.returns.setdefault(fn.name, []).append(fn.return_type)
            if fn.return_type is None or fn.return_type.kind == A.TypeKind.VOID:
                self.void_functions.add(fn.name)
            else:
                nonvoid.add(fn.name)
        for st in prog.statics:
            self.statics.add(st.name)
        for decl in prog.structs + prog.enums + prog.traits + prog.type_definitions:
            self.types.add(decl.name)
        for en in prog.enums:
            self.enums.add(en.name)
            # A generic enum's payload types name its own parameters, which mean
            # nothing at a match site.
            if not en.type_params:
                self.variants.setdefault(en.name, {
                    v.name: [t for _, t in v.associated_types] for v in en.variants})
        for decl in prog.structs + prog.enums:
            if decl.type_params:
                self.generic_types.add(decl.name)
        for s in prog.structs:
            self.fields[s.name] = {fd.name: fd.type for fd in s.fields}
        owners = [(ext.struct_name, ext.methods) for ext in prog.extensions]
        owners += [(tr.name, tr.methods) for tr in prog.traits]
        for owner, methods in owners:
            for m in methods:
                self.methods.add(m.name)
                if getattr(m, "is_borrows", False):
                    self.borrows_methods.add(m.name)
                    self.borrows_owned.add((owner, m.name))
                self.method_returns.setdefault((owner, m.name), []).append(m.return_type)
                if _instance_method(m):
                    self.method_mutates[(owner, m.name)] = _mutates_self(m)
                    self.name_mutates.setdefault(m.name, set()).add(_mutates_self(m))

    def read_only(self, name):
        """Is every instance method of this name a read-only `&self` method?"""
        kinds = self.name_mutates.get(name)
        return bool(kinds) and kinds == {False}

    def function_return(self, name):
        """The written return type every overload of the function shares, or None."""
        return _shared_type(self.returns.get(name))

    def method_return(self, owner, name):
        """The written return type every overload of the method shares, or None:
        a call's overload is not traced, so differing returns leave it unknown."""
        return _shared_type(self.method_returns.get((owner, name)))

    def module_member(self, path):
        """What a path headed by an inline module's name reaches, walked through
        the module bodies: ("module", n), ("static", n), ("function", n) or
        ("type", n), where the first n segments name it; None when the head is
        not a module. A module name may repeat across the build, so every body
        of that name is searched."""
        bodies = self.module_bodies.get(path[0])
        if not bodies:
            return None
        for i in range(1, len(path)):
            seg = path[i]
            nested = [md.body for b in bodies for md in b.module_decls
                      if md.name == seg and md.body is not None]
            if nested:
                bodies = nested
                continue
            for kind, decls in (("static", lambda b: b.statics),
                                ("function", lambda b: b.functions),
                                ("type", lambda b: b.structs + b.enums + b.traits)):
                if any(d.name == seg for b in bodies for d in decls(b)):
                    return kind, i + 1
            return None
        return "module", len(path)


# ---------------------------------------------------------------------------
# Small AST helpers.
# ---------------------------------------------------------------------------

def children(node):
    """The structural child nodes of `node`, in field order."""
    out = []
    for f in A.structural_fields(node):
        _collect(getattr(node, f.name), out)
    return out


def _collect(value, out):
    if isinstance(value, A.SawType) or value is None:
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _collect(v, out)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        out.append(value)


def walk(node):
    """`node` and every structural descendant, depth first."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(children(n)))


def type_parts(t):
    """`t` and every type written inside it."""
    stack = [t]
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        yield cur
        stack.extend(cur.type_args or ())
        stack.extend(cur.element_types or ())
        stack.extend(cur.param_types or ())
        stack.extend((cur.inner_type, cur.array_element_type, cur.func_return_type))


def is_optional(t):
    return t is not None and (t.kind == A.TypeKind.OPTIONAL or
                              (t.kind == A.TypeKind.STRUCT and t.struct_name == "Optional"))


def optional_payload(t):
    if t.kind == A.TypeKind.OPTIONAL:
        return t.inner_type
    return (t.type_args or [None])[0]


# A `?.` chain parses as an OptionalEvalExpr around its spine, with each `?.`
# hop's receiver wrapped in a BindOptional.
CHAIN_WRAPPERS = (A.BindOptional, A.OptionalEvalExpr)
HOPS = (A.MethodCall, A.MemberAccess, A.ArrayIndex, A.TupleIndex, A.ForceUnwrap, A.CastExpr)


def postfix_object(expr):
    if isinstance(expr, (A.MethodCall, A.MemberAccess)):
        return expr.object
    if isinstance(expr, A.ArrayIndex):
        return expr.array_expr
    if isinstance(expr, A.TupleIndex):
        return expr.tuple_expr
    if isinstance(expr, (A.ForceUnwrap, A.CastExpr) + CHAIN_WRAPPERS):
        return expr.expr
    return None


def root_name(expr):
    """The binding an expression's receiver chain starts from, or None."""
    while True:
        if isinstance(expr, A.Identifier):
            return expr.name
        if isinstance(expr, A.SelfExpr):
            return "self"
        if isinstance(expr, A.MoveExpr):
            return expr.variable
        if isinstance(expr, A.ReferenceExpr):
            expr = expr.expr
            continue
        nxt = postfix_object(expr)
        if nxt is None:
            return None
        expr = nxt


PLACE_STEPS = (A.MemberAccess, A.ArrayIndex, A.TupleIndex, A.ForceUnwrap) + CHAIN_WRAPPERS


def place_root(expr):
    """The binding a place is stored in, through field, element and unwrap steps
    only: a call's result is a new value, not a place."""
    while isinstance(expr, PLACE_STEPS):
        expr = postfix_object(expr)
    if isinstance(expr, A.Identifier):
        return expr.name
    if isinstance(expr, A.SelfExpr):
        return "self"
    return None


def member_path(expr):
    """The dotted names a place starts with, `a.b.c` from `a.b.c[i].d`, when its
    root is a bare name; otherwise None."""
    steps = []
    while isinstance(expr, PLACE_STEPS):
        steps.append(expr)
        expr = postfix_object(expr)
    if not isinstance(expr, A.Identifier):
        return None
    names = [expr.name]
    for step in reversed(steps):
        if not isinstance(step, A.MemberAccess):
            break
        names.append(step.member)
    return names


def reaches_get(expr):
    """Does an expression reach its value through a `.get(...)` call?"""
    while expr is not None:
        if _is_get_call(expr):
            return True
        expr = postfix_object(expr)
    return False


def through_index(expr):
    """Does a receiver reach its storage through `x[i]` or a tuple element?"""
    while isinstance(expr, PLACE_STEPS):
        if isinstance(expr, (A.ArrayIndex, A.TupleIndex)):
            return True
        expr = postfix_object(expr)
    return False


def _written_through_index(target):
    while isinstance(target, PLACE_STEPS):
        if isinstance(target, A.ArrayIndex):
            return True
        target = postfix_object(target)
    return False


def _is_get_call(expr):
    return isinstance(expr, A.MethodCall) and expr.method_name == "get"


def mentions(expr, name):
    for n in walk(expr):
        if isinstance(n, A.Identifier) and n.name == name:
            return True
        if isinstance(n, A.SelfExpr) and name == "self":
            return True
        if isinstance(n, A.MoveExpr) and n.variable == name:
            return True
        if isinstance(n, A.FunctionCall) and n.name == name:
            return True
    return False


def pattern_names(pattern, fallback=()):
    if pattern is None:
        return [name for name in fallback if name and name != "_"]
    names = []
    for n in walk(pattern):
        if isinstance(n, A.BindingPattern) and n.name and n.name != "_":
            names.append(n.name)
    return names


def is_literal(expr):
    if isinstance(expr, (A.IntLiteral, A.FloatLiteral, A.BoolLiteral, A.StringLiteral,
                         A.NoneLiteral)):
        return True
    return (isinstance(expr, A.UnaryOp) and expr.op == "-"
            and isinstance(expr.operand, (A.IntLiteral, A.FloatLiteral)))


def is_collection_literal(expr):
    return isinstance(expr, (A.ArrayLiteral, A.MapLiteral, A.SetLiteral))


def arguments_of(call):
    if isinstance(call, (A.FunctionCall, A.MethodCall, A.EnumInit)):
        return [(a.name, a.value) for a in call.arguments]
    if isinstance(call, A.StructInit):
        return list(call.field_inits)
    return []


CALLS = (A.FunctionCall, A.MethodCall, A.StructInit, A.EnumInit)


def _named(name):
    return A.SawType(A.TypeKind.STRUCT, struct_name=name)


def _peel(t):
    while t is not None and t.kind == A.TypeKind.REFERENCE:
        t = t.inner_type
    return t


def _type_name(t):
    t = _peel(t)
    if t is None:
        return None
    if t.kind == A.TypeKind.STRUCT:
        return t.struct_name
    if t.kind == A.TypeKind.ENUM:
        return t.enum_name
    return None


def _is_map(t):
    return _type_name(t) == "Map"


# ---------------------------------------------------------------------------
# The per-file checker.
# ---------------------------------------------------------------------------

class FileChecker:
    def __init__(self, src, std, facts):
        self.src = src
        self.std = std
        self.facts = facts
        self.diags = []
        self.seen = set()
        self._token_index = None

    def report(self, line, rule, message):
        key = (line, rule, message)
        if key in self.seen:
            return
        self.seen.add(key)
        self.diags.append(Diagnostic(self.src.rel, line, rule, message))

    def run(self):
        src = self.src
        if not src.text.endswith("\n"):
            self.report(src.text.count("\n") + 1, "file-end",
                        "the file must end with a newline")
        if src.lex_error:
            self.report(src.lex_error[0], "lex", src.lex_error[1])
            return self.diags
        self.check_tokens(src.tokens, 0)
        if src.parse_error:
            self.report(src.parse_error[0], "parse", src.parse_error[1])
            return self.diags
        for prog in programs(src.program):
            self.check_declarations(prog)
        self.check_types()
        self.check_literals()
        return self.diags

    # -- token rules -------------------------------------------------------

    def check_tokens(self, toks, line_base):
        """The token rules over `toks`, whose line 1 is the file's line
        `line_base + 1`: the file itself, or an interpolation's text."""
        def line_of(tok):
            return tok.line + line_base

        significant = _significant_newlines(toks)
        depth = 0
        over = False
        for i, tok in enumerate(toks):
            prev = toks[i - 1] if i > 0 else None
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if tok.type in (T.LPAREN, T.LBRACKET, T.LBRACE):
                depth += 1
                if depth > MAX_NESTING and not over:
                    over = True
                    self.report(line_of(tok), "nesting-depth",
                                "brackets nest deeper than %d levels" % MAX_NESTING)
            elif tok.type in (T.RPAREN, T.RBRACKET, T.RBRACE):
                depth -= 1
                if depth <= MAX_NESTING:
                    over = False
            elif tok.type == T.IDENT:
                self.check_name_token(tok, prev, nxt, line_of(tok))
            elif tok.type == T.MINUS:
                if prev is None or (prev.type == T.NEWLINE and significant[i - 1]):
                    before = _previous(toks, i, significant, skip_all_newlines=True)
                    if before is not None and before.type in OPERAND_END:
                        self.report(line_of(tok), "leading-minus",
                                    "a line after an operand may not begin with `-`; write "
                                    "`return -1` or bind the value first")
            elif tok.type == T.STAR:
                before = _previous(toks, i, significant)
                if before is None or before.type not in OPERAND_END + (T.DOT,):
                    self.report(line_of(tok), "raw-pointer", "a pointer dereference")
            elif tok.type == T.UNSAFE:
                self.report(line_of(tok), "raw-pointer", "`unsafe` has no place in the subset")
            elif tok.type in (T.BORROWS, T.LEND):
                self.report(line_of(tok), "borrows-accessor",
                            "`%s` belongs to the new std, not the subset" % tok.value)
            elif tok.type == T.DOLLAR_PARAM:
                self.report(line_of(tok), "closure-syntax",
                            "shorthand closure parameters; name and annotate each one")
            elif tok.type == T.CASE:
                self.check_arm(toks, i, line_base)
            elif tok.type == T.AS:
                self.check_cast(toks, i, line_base)
            elif tok.type == T.AT and nxt is not None and nxt.type == T.IDENT \
                    and nxt.value == "test":
                self.report(line_of(tok), "test-directive",
                            "`@test` belongs in a `*.test.saw` sidecar")
            elif tok.type == T.INTERP_STRING:
                self.check_interpolation(tok, line_base)

    def check_interpolation(self, tok, line_base):
        for seg in tok.segments or ():
            if seg.kind != "expr":
                continue
            line = seg.line + line_base
            if any(s in seg.text for s in ("//", "{", "}", '"')):
                self.report(line, "interpolation-content",
                            "keep an interpolation to a name, a field or a simple call: "
                            "no comment, brace or string inside it")
                continue
            if "\n" in seg.text:
                self.report(line + seg.text.count("\n"), "interpolation-line-break",
                            "keep an interpolation on one line; compute a longer "
                            "expression into a `let` first")
            try:
                inner = Lexer(seg.text).tokenize()
            except Exception:
                continue
            # A broken segment is refused above; the other token rules read it as
            # one line, so a `-` or `*` after the break is not taken for a prefix.
            self.check_tokens([t for t in inner if t.type != T.NEWLINE], line - 1)

    def check_name_token(self, tok, prev, nxt, line):
        # A member, an enum case or a label is not the std name it spells.
        if prev is not None and prev.type in (T.DOT, T.CASE):
            return
        if nxt is not None and nxt.type == T.COLON:
            return
        name = tok.value
        if name in SYNC_ONLY_NAMES:
            self.report(line, "sync-only", "`%s` belongs to concurrent code" % name)
        elif name in CELL_NAMES:
            self.report(line, "cell-type", "`%s` is a cell" % name)
        elif name == "Box":
            self.report(line, "box-type", "link by arena index, not `Box`")
        elif name in self.std.unsafe_types:
            self.report(line, "raw-pointer", "`%s` is an unsafe type" % name)
        elif name == "borrow":
            self.report(line, "borrow-syntax", "`borrow` is a keyword of the new language")
        elif name == "lends":
            self.report(line, "borrows-accessor",
                        "`lends` belongs to the new std, not the subset")

    def check_arm(self, toks, i, line_base):
        """A match arm whose body starts with a statement keyword."""
        depth = 0
        j = i + 1
        while j < len(toks):
            t = toks[j]
            if t.type in (T.LPAREN, T.LBRACKET, T.LBRACE):
                depth += 1
            elif t.type in (T.RPAREN, T.RBRACKET, T.RBRACE):
                if depth == 0:
                    return
                depth -= 1
            elif depth == 0 and t.type in (T.COMMA, T.NEWLINE, T.EOF):
                return
            elif depth == 0 and t.type == T.ARROW:
                break
            j += 1
        else:
            return
        j += 1
        while j < len(toks) and toks[j].type == T.NEWLINE:
            j += 1
        if j < len(toks) and toks[j].type in STATEMENT_KEYWORDS:
            self.report(toks[j].line + line_base, "statement-arm",
                        "brace a statement arm: `case X -> { return 7 },`")

    def check_cast(self, toks, i, line_base):
        """`?` or `??` after the type of an `as` cast, on its line or the next."""
        j = i + 1
        if j < len(toks) and toks[j].type in (T.LPAREN, T.LBRACKET):
            j = _skip_group(toks, j)
        else:
            while j < len(toks) and toks[j].type == T.IDENT:
                j += 1
                if j < len(toks) and toks[j].type == T.LT:
                    j = _skip_group(toks, j)
                if j < len(toks) and toks[j].type == T.DOT:
                    j += 1
                    continue
                break
        while j < len(toks) and toks[j].type == T.NEWLINE:
            j += 1
        if j < len(toks) and toks[j].type in (T.QUESTION, T.DOUBLE_QUESTION):
            self.report(toks[j].line + line_base, "cast-then-optional",
                        "coalesce first, then convert: `(n ?? 9) as Int`")

    def previous_token(self, line, column):
        """The token before the one at `line:column`, newlines skipped."""
        toks = self.src.tokens
        if self._token_index is None:
            self._token_index = {(t.line, t.column): i for i, t in enumerate(toks)}
        i = self._token_index.get((line, column))
        if i is None:
            return None
        i -= 1
        while i >= 0 and toks[i].type == T.NEWLINE:
            i -= 1
        return toks[i] if i >= 0 else None

    # -- literals ------------------------------------------------------------

    def check_literals(self):
        """Integer literals past `Int.max` and float literals, wherever an
        expression can sit, interpolations included."""
        allowed = set()
        for n in walk(self.src.program):
            if isinstance(n, A.LetStatement):
                _allow_typed(n.value, n.type_annotation, allowed)
            elif isinstance(n, A.StaticDecl):
                _allow_typed(n.initializer, n.type, allowed)
            elif isinstance(n, A.UnaryOp) and n.op == "-" \
                    and isinstance(n.operand, A.IntLiteral) and n.operand.value == INT_MAX + 1:
                allowed.add(id(n.operand))
        for n in walk(self.src.program):
            if isinstance(n, A.IntLiteral) and n.suffix is None \
                    and isinstance(n.value, int) and n.value > INT_MAX \
                    and id(n) not in allowed:
                self.report(n.line, "int-literal-range",
                            "an unsuffixed integer literal above Int.max wraps; give it a "
                            "suffix or a `UInt64` binding")
            elif isinstance(n, A.FloatLiteral):
                self.report(n.line, "float-literal", "the subset has no float literals")

    # -- declarations and bodies ---------------------------------------------

    def check_declarations(self, prog):
        for md in prog.module_decls:
            if md.is_inline or md.body is not None:
                self.report(md.line, "inline-module",
                            "no inline `module %s { }`; Stage 0 never drops a value of a "
                            "type declared in one, so use a file module" % md.name)
        for td in prog.type_definitions:
            self.report(td.line, "type-alias",
                        "no `type` aliases; use `Int` or a one-field struct")
        for imp in prog.imports:
            self.check_import(imp)
        for decl in prog.structs + prog.enums + prog.traits:
            if decl.name in self.std.reserved_types:
                self.report(decl.line, "prelude-type-name",
                            "`%s` is the name of a std type" % decl.name)
        for s in prog.structs:
            if not s.fields:
                self.report(s.line, "empty-struct", "give every struct at least one field")
        for blk in prog.extern_blocks:
            for fn in blk.functions:
                if fn.is_blocking:
                    self.report(fn.line or blk.line, "sync-only",
                                "a `blocking` extern suspends")
        for fn in prog.functions:
            BodyChecker(self, fn, None).run()
        for ext in prog.extensions:
            if not ext.type_params and self.is_generic_type(ext.struct_name):
                self.report(ext.line, "generic-extension-params",
                            "`%s` is generic; write its type parameters in the extension "
                            "head" % ext.struct_name)
            if ext.type_params:
                for m in ext.methods:
                    if m.is_init:
                        self.report(m.line, "generic-extension-init",
                                    "no `init` in a generic extension; build it memberwise")
                if any(tp.bounds for tp in ext.type_params):
                    self.report(ext.line, "bounded-extension",
                                "no bounds on an extension's type parameters")
            for m in ext.methods:
                self.check_deinit(m)
                BodyChecker(self, m, ext).run()
        for tr in prog.traits:
            for m in tr.methods:
                self.check_deinit(m)
                if m.body is not None:
                    BodyChecker(self, m, tr).run()
        for st in prog.statics:
            if st.initializer is not None:
                BodyChecker(self, None, None).run_expression(st.initializer)
        for sa in prog.static_asserts:
            BodyChecker(self, None, None).run_expression(sa.condition)

    def check_deinit(self, m):
        """A `deinit` in any extension or trait body. Stage 1 tolerates leaks
        only while no skipped drop has an effect, and a struct or enum body
        declares no methods, so these are the places one can be written."""
        if m.name == "deinit":
            self.report(m.line, "deinit-body",
                        "a skipped drop must have no effect in Stage 1, so the compiler "
                        "source declares no `deinit`")

    def is_generic_type(self, name):
        """Is `name` a generic type: the build's when the build declares it,
        std's otherwise?"""
        if name in self.facts.types:
            return name in self.facts.generic_types
        return name in self.std.generic_types

    def check_import(self, imp):
        path = imp.path
        if imp.symbols is None or imp.is_glob:
            self.report(imp.line, "selective-imports",
                        "import names selectively: `import %s.{...}`" % ".".join(path))
        head = path[0] if path else ""
        if head == "std":
            module = ".".join(path[1:])
            if module not in ALLOWED_STD_MODULES:
                self.report(imp.line, "import-allowlist",
                            "`std.%s` is not on the compiler's std allowlist" % module)
        elif head not in PACKAGE_RELATIVE_HEADS and \
                head not in [name for name, _ in STAGE_PACKAGES]:
            self.report(imp.line, "import-allowlist",
                        "`%s` is neither std, a compiler stage, nor package-relative" % head)

    # -- written types -------------------------------------------------------

    def check_types(self):
        stack = [(self.src.program, 1)]
        while stack:
            node, line = stack.pop()
            line = getattr(node, "line", 0) or line
            for f in A.structural_fields(node):
                self._types_in(getattr(node, f.name), line, stack)

    def _types_in(self, value, line, stack):
        if isinstance(value, A.SawType):
            self.check_type(value, line)
        elif isinstance(value, (list, tuple)):
            for v in value:
                self._types_in(v, line, stack)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            stack.append((value, line))

    def check_type(self, t, fallback):
        if _type_depth(t) > MAX_TYPE_DEPTH:
            self.report(t.written_line or fallback, "written-type-shape",
                        "a written type nests more than %d levels" % MAX_TYPE_DEPTH)
        for part in type_parts(t):
            line = part.written_line or fallback
            k = part.kind
            if k == A.TypeKind.STRUCT and part.struct_name == "Optional":
                self.report(line, "written-type-shape", "write `T?`, not `Optional<T>`")
            if k == A.TypeKind.TUPLE and any(p.kind == A.TypeKind.SELF
                                             for p in type_parts(part)):
                self.report(line, "written-type-shape", "no `Self` inside a tuple type")
            if k == A.TypeKind.EXISTENTIAL:
                self.report(line, "any-type", "no `any`; dispatch over an enum")
            elif k == A.TypeKind.ARRAY:
                self.report(line, "fixed-array", "no fixed-size arrays; use `Vector`")
            elif k == A.TypeKind.POINTER:
                self.report(line, "raw-pointer", "a raw pointer type")
            if is_optional(part):
                inner = optional_payload(part)
                if is_optional(inner):
                    self.report(line, "nested-optional",
                                "no nested optionals; use an enum with named cases")
                if inner is not None and (inner.kind == A.TypeKind.FUNCTION or (
                        inner.kind == A.TypeKind.TUPLE and len(inner.element_types or ()) == 1
                        and inner.element_types[0].kind == A.TypeKind.FUNCTION)):
                    self.report(line, "closure-syntax",
                                "keep function values out of optional slots")
            if k == A.TypeKind.STRUCT and part.struct_name in COLLECTIONS:
                if any(is_optional(a) for a in part.type_args or ()):
                    self.report(line, "nested-optional",
                                "no optional element or value type in a `%s`"
                                % part.struct_name)


def _allow_typed(value, annotation, allowed):
    """The typed binding SL:hazards S7 recommends for a constant past `Int.max`."""
    if isinstance(value, A.IntLiteral) and annotation is not None \
            and annotation.kind in UNSIGNED_64:
        allowed.add(id(value))


def _significant_newlines(toks):
    """For each token, whether it is a NEWLINE the parser reads: one directly
    inside `(` or `[` is skipped, as the frozen parser skips it."""
    out = [False] * len(toks)
    stack = []
    for i, t in enumerate(toks):
        if t.type in (T.LPAREN, T.LBRACKET, T.LBRACE):
            stack.append(t.type)
        elif t.type in (T.RPAREN, T.RBRACKET, T.RBRACE):
            if stack:
                stack.pop()
        elif t.type == T.NEWLINE:
            out[i] = not stack or stack[-1] == T.LBRACE
    return out


def _previous(toks, i, significant, skip_all_newlines=False):
    j = i - 1
    while j >= 0 and toks[j].type == T.NEWLINE and (skip_all_newlines or not significant[j]):
        j -= 1
    return toks[j] if j >= 0 else None


def _type_depth(t):
    kids = [k for k in (t.type_args or []) + (t.element_types or []) + (t.param_types or [])
            + [t.inner_type, t.array_element_type, t.func_return_type] if k is not None]
    return 1 + max((_type_depth(k) for k in kids), default=0)


def _skip_group(toks, j):
    """From an opener at `j`, the index just past its matching closer."""
    openers = (T.LPAREN, T.LBRACKET, T.LT)
    closers = (T.RPAREN, T.RBRACKET, T.GT)
    depth = 0
    while j < len(toks):
        if toks[j].type in openers:
            depth += 1
        elif toks[j].type in closers:
            depth -= 1
            if depth == 0:
                return j + 1
        elif toks[j].type in (T.NEWLINE, T.EOF, T.LBRACE):
            return j
        j += 1
    return j


class Binding:
    """A name in scope. `kind` is one of: let, var, param, param-ref,
    param-refvar, pattern, pattern-var, for, closure-param, catch. `depth` is
    the closure nesting it was bound at, so a use from deeper is a capture.
    `borrowed` marks a binding that aliases storage it does not own
    (SL:hazards S2)."""
    __slots__ = ("kind", "depth", "borrowed", "type")

    def __init__(self, kind, depth, borrowed=False, type_=None):
        self.kind = kind
        self.depth = depth
        self.borrowed = borrowed
        self.type = type_


# Stage 0 lets a `&var` write through any root; only these may be written
# (SL:hazards S5).
MUTABLE_ROOTS = ("var", "param-refvar", "pattern-var")


class BodyChecker:
    """One function, method, trait default body or static initializer, walked
    with its lexical scopes."""

    def __init__(self, fc, decl, owner):
        self.fc = fc
        self.facts = fc.facts
        self.decl = decl
        self.owner = owner
        self.scopes = [{}]
        self.closure_depth = 0
        self.self_kind = None
        self.chain_links = set()
        self.type_params = {}
        for tp in (getattr(owner, "type_params", ()) or []) + \
                (getattr(decl, "type_params", ()) or []):
            self.type_params[tp.name] = list(tp.bounds or ())
        rt = getattr(decl, "return_type", None)
        self.returns_result = _type_name(rt) == "Result"

    def report(self, line, rule, message):
        self.fc.report(line, rule, message)

    # -- scopes --------------------------------------------------------------

    def bind(self, name, kind, borrowed=False, type_=None):
        if name and name != "_":
            self.scopes[-1][name] = Binding(kind, self.closure_depth, borrowed, type_)

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def is_local(self, name):
        return name == "self" and self.self_kind is not None or self.lookup(name) is not None

    # -- entry ---------------------------------------------------------------

    def run(self):
        d = self.decl
        for p in d.parameters:
            if p.name == "self":
                continue
            kind = "param-refvar" if p.reference_mutable else (
                "param-ref" if p.is_reference else "param")
            self.bind(p.name, kind, type_=p.type)
            if p.default_value is not None and not is_literal(p.default_value):
                self.report(d.line, "default-value-literal",
                            "write a default parameter value as a literal")
        if isinstance(d, (A.Method, A.TraitMethod)) and _instance_method(d):
            if getattr(d, "is_consumes", False):
                self.self_kind = "consumes"
            elif d.self_mutable:
                self.self_kind = "refvar"
            else:
                self.self_kind = "ref"
        rt = d.return_type
        is_init = getattr(d, "is_init", False)
        value_returning = is_init or (rt is not None and rt.kind != A.TypeKind.VOID)
        if value_returning and not getattr(d, "is_borrows", False):
            if not self.block_ends(d.body):
                self.report(d.line, "function-exit",
                            "a value-returning body must end in a value, a `return`, or a "
                            "branch whose every arm does")
            if self.returns_result:
                self.check_result_tail(d.body)
        self.block(d.body)

    def run_expression(self, expr):
        """A `static` initializer or a `static_assert` condition, checked as a
        body of one expression."""
        self.expr(expr, None)

    # -- function exits --------------------------------------------------------

    def block_ends(self, block):
        if block is None:
            return False
        if block.final_expr is not None:
            return self.expr_ends(block.final_expr)
        if not block.statements:
            return False
        last = block.statements[-1]
        if isinstance(last, A.ReturnStatement):
            return True
        if isinstance(last, A.ExpressionStatement):
            return self.expr_ends(last.expression)
        return False

    def expr_ends(self, expr):
        if isinstance(expr, A.IfExpr):
            return (expr.else_branch is not None and self.block_ends(expr.then_branch)
                    and self.block_ends(expr.else_branch))
        if isinstance(expr, A.IfLetExpr):
            return (not expr.while_let and expr.else_branch is not None
                    and self.block_ends(expr.then_branch) and self.block_ends(expr.else_branch))
        if isinstance(expr, A.MatchExpr):
            return all(self.arm_ends(arm.body) for arm in expr.arms)
        if isinstance(expr, A.TryCatchExpr):
            return self.block_ends(expr.try_block) and self.block_ends(expr.catch_block)
        if isinstance(expr, A.ScopedBlock):
            return self.block_ends(expr.block)
        if isinstance(expr, A.WhileExpr):
            return False
        return not self.is_void_call(expr)

    def is_void_call(self, expr):
        """A call known to return nothing: its path produces no value."""
        if isinstance(expr, A.FunctionCall) and not self.is_local(expr.name):
            return expr.name in ("print", "assert") or expr.name in self.facts.void_functions
        if isinstance(expr, A.MethodCall):
            key = (_type_name(self.type_of(expr.object)), expr.method_name)
            if key not in self.facts.method_returns:
                return False
            return all(rt is None or rt.kind == A.TypeKind.VOID
                       for rt in self.facts.method_returns[key])
        return False

    def arm_ends(self, body):
        if isinstance(body, A.Block):
            return self.block_ends(body)
        return self.expr_ends(body)

    def check_result_tail(self, block):
        tails = []
        self._tails(block, tails)
        for expr in tails:
            if is_collection_literal(expr):
                self.report(expr.line, "optional-shaping",
                            "bind a collection literal to an annotated local before "
                            "returning it as a `Result`")

    def _tails(self, node, out):
        if isinstance(node, A.Block):
            if node.final_expr is not None:
                self._tails(node.final_expr, out)
            elif node.statements and isinstance(node.statements[-1], A.ExpressionStatement):
                self._tails(node.statements[-1].expression, out)
        elif isinstance(node, (A.IfExpr, A.IfLetExpr)):
            self._tails(node.then_branch, out)
            if node.else_branch is not None:
                self._tails(node.else_branch, out)
        elif isinstance(node, A.MatchExpr):
            for arm in node.arms:
                self._tails(arm.body, out)
        elif node is not None:
            out.append(node)

    # -- statements ------------------------------------------------------------

    def block(self, block):
        """Walk `block` in its own scope."""
        if block is None:
            return
        self.push()
        stmts = block.statements
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, (A.ReturnStatement, A.BreakStatement, A.ContinueStatement)):
                if i + 1 < len(stmts) or block.final_expr is not None:
                    self.report(stmt.line, "function-exit",
                                "nothing may follow an unconditional return, break or "
                                "continue")
            self.statement(stmt)
        if block.final_expr is not None:
            self.expr(block.final_expr, block)
        self.pop()

    def statement(self, s):
        if isinstance(s, A.LetStatement):
            if s.type_annotation is None:
                self.check_untyped_array(s.value, s.line)
            self.expr(s.value, s)
            self.bind(s.name, "var" if s.mutable else "let",
                      borrowed=self.aliases_borrowed(s.value),
                      type_=s.type_annotation or self.type_of(s.value))
        elif isinstance(s, A.DestructuringLet):
            self.check_untyped_array(s.value, s.line)
            self.expr(s.value, s)
            self.bind_destructured(s.pattern, self.type_of(s.value),
                                   "var" if s.mutable else "let")
        elif isinstance(s, A.AssignStatement):
            self.check_place_write(s.target, s.line)
            self.check_assignment_root(s)
            self.expr(s.target, s)
            self.expr(s.value, s)
        elif isinstance(s, A.CompoundAssignStatement):
            self.check_place_write(s.target, s.line)
            self.expr(s.target, s)
            self.expr(s.value, s)
        elif isinstance(s, A.ReturnStatement):
            if s.value is not None:
                if self.returns_result and is_collection_literal(s.value) \
                        and self.closure_depth == 0:
                    self.report(s.line, "optional-shaping",
                                "bind a collection literal to an annotated local before "
                                "returning it as a `Result`")
                self.expr(s.value, s)
        elif isinstance(s, A.ExpressionStatement):
            self.expr(s.expression, s)
        elif isinstance(s, A.BreakStatement):
            if s.value is not None:
                self.report(s.line, "value-loop",
                            "no value-position loops; assign a `var` before `break`")
                self.expr(s.value, s)
        elif isinstance(s, A.ForLoop):
            self.check_untyped_array(s.iterable, s.line)
            self.expr(s.iterable, s)
            self.push()
            self.bind(s.variable, "for")
            self.block(s.body)
            self.pop()
        elif isinstance(s, A.WhileExpr):
            self.expr(s, None)
        elif isinstance(s, A.GuardLetStatement):
            self.check_presence_test(s.name, s.pattern, s.optional_expr, s.line)
            self.expr(s.optional_expr, s)
            self.block(s.else_branch)
            self.bind_optional_pattern(s.name, s.pattern, s.mutable, s.optional_expr)
        else:
            for child in children(s):
                self.any(child, s)

    def bind_destructured(self, pattern, t, kind):
        """Bind a destructuring pattern's names, each with its element's written
        type when the value's tuple type is traced."""
        t = _peel(t)
        elements = t.element_types if t is not None and t.kind == A.TypeKind.TUPLE else None
        if not isinstance(pattern, A.TuplePattern):
            for name in pattern_names(pattern):
                self.bind(name, kind)
            return
        for i, sub in enumerate(pattern.elements):
            element = elements[i] if elements and i < len(elements) else None
            if isinstance(sub, A.BindingPattern):
                self.bind(sub.name, kind, type_=element)
            else:
                self.bind_destructured(sub, element, kind)

    def check_untyped_array(self, value, line):
        """An array literal with no written type to adopt, in an unannotated
        binding, a `for` sequence, a method receiver or a match scrutinee: the
        frozen compiler types it as a fixed array, through tuples, branches,
        closure values and generic calls alike. A parameter or field type is
        written, so a non-generic call's arguments adopt it."""
        stack = [value]
        while stack:
            n = stack.pop()
            if n is None or isinstance(n, (A.StructInit, A.EnumInit, A.MethodCall)):
                continue
            if isinstance(n, A.ArrayLiteral):
                self.report(line, "fixed-array",
                            "an array literal with no written type is a fixed-size array; "
                            "bind it to a `Vector<T>`-annotated local")
                return
            if isinstance(n, A.FunctionCall):
                if self.is_generic_function(n.name):
                    stack.extend(v for _, v in arguments_of(n))
            elif isinstance(n, A.ClosureExpr):
                stack.append(n.body)
            elif isinstance(n, A.Block):
                stack.append(n.final_expr)
            else:
                stack.extend(children(n))

    def is_generic_function(self, name):
        if self.is_local(name):
            return False
        return name in self.facts.generic_functions or (
            name not in self.facts.functions and name in self.fc.std.generic_functions)

    def check_assignment_root(self, s):
        """A plain index write whose right side reads the target's root. A field
        write such as `p.a = p.b + 1` is accepted: the hazard's shape is an
        index write, and Stage 0 compiles a field write correctly (SL:hazards S4)."""
        target = s.target
        if not _written_through_index(target):
            return
        root = place_root(target)
        if root is not None and self.is_local(root) and mentions(s.value, root):
            self.report(s.line, "root-reuse",
                        "an index write whose right side reads `%s`; compute into a local "
                        "first, or use a compound assignment" % root)

    # -- expressions -----------------------------------------------------------

    def any(self, node, parent):
        if isinstance(node, A.Block):
            self.block(node)
        elif isinstance(node, A.Statement):
            self.statement(node)
        elif isinstance(node, A.Expression):
            self.expr(node, parent)
        else:
            for child in children(node):
                self.any(child, node)

    def expr(self, e, parent):
        if e is None:
            return
        if isinstance(e, A.Identifier):
            self.use(e.name, e.line)
        elif isinstance(e, A.SelfExpr):
            if self.closure_depth > 0:
                self.report(e.line, "closure-capture", "a closure may not capture `self`")
        elif isinstance(e, A.MoveExpr):
            self.use(e.variable, e.line)
            b = self.lookup(e.variable)
            if b is not None and b.borrowed:
                self.report(e.line, "borrowed-match-payload",
                            "`%s` aliases storage it does not own; pass it on by `&` "
                            "instead of moving it" % e.variable)
            if e.path is not None:
                self.expr(e.path, e)
        elif isinstance(e, A.ClosureExpr):
            self.closure(e)
        elif isinstance(e, A.MatchExpr):
            self.match(e)
        elif isinstance(e, (A.IfExpr, A.IfLetExpr)):
            if id(e) not in self.chain_links:
                self.check_else_if_chain(e)
            if isinstance(e, A.IfExpr):
                self.expr(e.condition, e)
                self.block(e.then_branch)
            else:
                self.check_presence_test(e.name, e.pattern, e.optional_expr, e.line)
                self.expr(e.optional_expr, e)
                self.push()
                self.bind_optional_pattern(e.name, e.pattern, e.mutable, e.optional_expr)
                self.block(e.then_branch)
                self.pop()
            self.block(e.else_branch)
        elif isinstance(e, A.TryExpr):
            self.expr(e.expr, e)
            if e.catch_block is not None:
                self.catch_block(e.catch_block, "error")
        elif isinstance(e, A.TryCatchExpr):
            self.block(e.try_block)
            self.catch_block(e.catch_block, e.error_binding or "error")
        elif isinstance(e, A.WhileExpr):
            self.expr(e.condition, e)
            self.block(e.body)
        elif isinstance(e, CALLS):
            self.call(e, parent)
        elif isinstance(e, A.BinaryOp):
            if not isinstance(parent, A.BinaryOp):
                terms = _count_nested(e, A.BinaryOp, ("left", "right"))
                if terms > MAX_CHAIN:
                    self.report(e.line, "chain-length",
                                "an operator chain of %d terms; split it" % terms)
            if e.op in ("==", "!=") and (isinstance(e.left, A.NoneLiteral)
                                         or isinstance(e.right, A.NoneLiteral)):
                self.report(e.line, "optional-shaping",
                            "test presence with `.is_none()` or `.is_some()`, not `== None`")
            self.expr(e.left, e)
            self.expr(e.right, e)
        elif isinstance(e, A.NilCoalesce):
            if not isinstance(parent, A.NilCoalesce):
                terms = _count_nested(e, A.NilCoalesce, ("expr", "default"))
                if terms > MAX_CHAIN:
                    self.report(e.line, "chain-length",
                                "a `??` chain of %d terms; split it" % terms)
            self.expr(e.expr, e)
            self.expr(e.default, e)
        elif isinstance(e, A.ReferenceExpr):
            if e.mutable:
                self.check_var_ref(e)
                if reaches_get(e.expr):
                    self.report(e.line, "std-api",
                                "`&var` through `get` writes a place in sawc/std and a "
                                "copy in the new std")
            self.expr(e.expr, e)
        elif isinstance(e, A.ArrayLiteral):
            if e.repeat_count is not None:
                self.report(e.line, "fixed-array", "no repeat literals; use `Vector`")
            for el in e.elements:
                self.expr(el, e)
        elif isinstance(e, A.OptionalChainAssign):
            self.check_place_write(e.target, e.line)
            self.expr(e.target, e)
            self.expr(e.value, e)
        else:
            if isinstance(e, A.ArrayIndex):
                self.check_subscript(e, parent)
            if isinstance(e, HOPS + CHAIN_WRAPPERS):
                self.check_postfix_chain(e, parent)
            for child in children(e):
                self.any(child, e)

    def use(self, name, line):
        b = self.lookup(name)
        if b is not None and b.depth < self.closure_depth:
            self.report(line, "closure-capture",
                        "a closure may not capture `%s`; pass it as a parameter" % name)

    def catch_block(self, block, binding):
        self.push()
        self.bind(binding, "catch")
        self.block(block)
        self.pop()

    def closure(self, e):
        if e.capture_specs:
            self.report(e.line, "closure-capture", "no capture lists in the subset")
        for p in e.parameters:
            if p.type_annotation is None:
                self.report(e.line, "closure-syntax",
                            "annotate every closure parameter: `{ x: Int in ... }`")
        if _returns_value(e.body) and not self.block_ends(e.body):
            self.report(e.line, "function-exit",
                        "a closure that returns a value must end in one on every path")
        self.closure_depth += 1
        self.push()
        for p in e.parameters:
            t = p.type_annotation
            written_ref = t is not None and t.kind == A.TypeKind.REFERENCE
            if p.reference_mutable or (written_ref and t.reference_mutable):
                kind = "param-refvar"
            elif p.is_reference or written_ref:
                kind = "param-ref"
            else:
                kind = "closure-param"
            self.bind(p.name, kind, type_=t)
        self.block(e.body)
        self.pop()
        self.closure_depth -= 1

    def aliases_borrowed(self, expr):
        """Does `expr` name storage a borrowed binding aliases?"""
        root = place_root(expr) if not isinstance(expr, A.Identifier) else expr.name
        b = self.lookup(root) if root is not None else None
        return b is not None and b.borrowed

    def bind_optional_pattern(self, name, pattern, mutable, subject):
        borrowed = not self.owned_scrutinee(subject)
        payload = _peel(self.type_of(subject))
        payload = optional_payload(payload) if is_optional(payload) else None
        for n in pattern_names(pattern, [name]):
            self.bind(n, "pattern-var" if mutable else "pattern", borrowed=borrowed,
                      type_=payload)

    def match(self, e):
        self.check_untyped_array(e.matched_expr, e.line)
        self.expr(e.matched_expr, e)
        scrutinee = e.matched_expr
        root = place_root(scrutinee)
        b = self.lookup(root) if root is not None else None
        if b is not None and b.borrowed:
            self.report(e.line, "borrowed-match-payload",
                        "`%s` aliases storage it does not own; give its type a `&self` "
                        "accessor instead of matching it" % root)
        if _is_get_call(scrutinee) and not any(
                pattern_names(arm.pattern, arm.bindings) for arm in e.arms):
            self.report(e.line, "std-api",
                        "a presence test through `get`; compare the index with `len()`")
        borrowed = not self.owned_scrutinee(scrutinee)
        scrutinee_type = _peel(self.type_of(scrutinee))
        for arm in e.arms:
            self.push()
            types = self.arm_payload_types(scrutinee_type, arm)
            for name in pattern_names(arm.pattern, arm.bindings):
                self.bind(name, "pattern", borrowed=borrowed, type_=types.get(name))
            self.expr(arm.guard, arm)
            if isinstance(arm.body, A.Block):
                self.block(arm.body)
            else:
                self.expr(arm.body, arm)
            self.pop()

    def arm_payload_types(self, scrutinee, arm):
        """The written type of each name an enum-case arm binds, by position in
        the case's payload, when the scrutinee's type is traced."""
        if isinstance(arm.pattern, A.EnumPattern):
            subs = [p.name if isinstance(p, A.BindingPattern) else None
                    for p in arm.pattern.subpatterns]
        else:
            subs = list(arm.bindings or ())
        payload = None
        variant = arm.variant_name
        if is_optional(scrutinee):
            payload = [optional_payload(scrutinee)] if variant == "Some" else None
        elif _type_name(scrutinee) == "Result" and len(scrutinee.type_args or ()) == 2:
            payload = {"Ok": scrutinee.type_args[:1], "Err": scrutinee.type_args[1:]}.get(
                variant)
        elif _type_name(scrutinee) in self.facts.variants:
            payload = self.facts.variants[_type_name(scrutinee)].get(variant)
        if payload is None:
            return {}
        return {name: _peel(t) for name, t in zip(subs, payload) if name}

    def owned_scrutinee(self, s):
        """A local bound by `let`/`var`, a by-value parameter, or `move` of
        either. `self` never is, not even in a `consumes` method."""
        if isinstance(s, A.MoveExpr) and s.path is None:
            s = A.Identifier(name=s.variable)
        if isinstance(s, A.Identifier):
            b = self.lookup(s.name)
            return b is not None and b.kind in ("let", "var", "param") and not b.borrowed
        return False

    def check_var_ref(self, e):
        path = member_path(e.expr)
        if path is not None and not self.is_local(path[0]):
            member = self.facts.module_member(path)
            if member is not None and member[0] == "static":
                self.report(e.line, "var-ref-into-let",
                            _static_root_message("`&var` reaches into",
                                                 ".".join(path[:member[1]])))
                return
        self.check_mutable_root(place_root(e.expr), e.line, "`&var` reaches into")

    def check_mutable_root(self, root, line, reach):
        """`reach` says how the write reaches `root`, as "`&var` reaches into"."""
        if root is None:
            return
        message = "%s `%s`, which is not a `var`" % (reach, root)
        if root == "self":
            if self.self_kind == "ref":
                self.report(line, "var-ref-into-let", message)
            return
        b = self.lookup(root)
        if b is not None:
            if b.kind not in MUTABLE_ROOTS:
                self.report(line, "var-ref-into-let", message)
        elif root in self.facts.statics:
            self.report(line, "var-ref-into-let", _static_root_message(reach, root))

    def call(self, e, parent):
        args = arguments_of(e)
        labels = [name for name, _ in args if name]
        if len(labels) != len(set(labels)):
            self.report(e.line, "argument-labels", "a label repeats in one argument list")
        self.check_std_call(e)
        if isinstance(e, A.FunctionCall):
            self.use(e.name, e.line)
            if not e.name[:1].isupper() and self.is_generic_function(e.name):
                for _, value in args:
                    self.check_untyped_array(value, e.line)
        if isinstance(e, A.MethodCall):
            self.method_call(e, parent, labels)
        self.check_ref_args(e, args)
        self.check_trailing_closures(e, args)
        if isinstance(e, A.MethodCall):
            self.expr(e.object, e)
        for _, value in args:
            self.expr(value, e)

    def method_call(self, e, parent, labels):
        obj = e.object
        self.check_postfix_chain(e, parent)
        self.check_untyped_array(obj, e.line)
        mutating = self.may_mutate(e)
        if mutating and through_index(obj):
            self.report(e.line, "index-receiver-call",
                        "`.%s()` on storage reached through an index runs on a copy; call "
                        "it on a named local or a field path" % e.method_name)
        if self.known_mutating(e):
            self.check_mutable_root(place_root(obj), e.line,
                                    "`.%s()` takes `&var self` on" % e.method_name)
        if isinstance(obj, A.Identifier):
            if obj.name in self.type_params:
                self.report(e.line, "type-param-receiver",
                            "call a static requirement on the concrete type, not on `%s`"
                            % obj.name)
        if isinstance(obj, A.MethodCall) and obj.method_name == "get":
            self.report(e.line, "optional-shaping",
                        "a method called directly on a `get` result; bind the result or "
                        "test it with `if let`")
        if e.method_name == "from" and any(
                a.name == "raw" and isinstance(a.value, A.IntLiteral) and a.value.suffix is None
                for a in e.arguments):
            self.report(e.line, "from-raw-literal",
                        "`from(raw:)` with a bare literal; write a suffixed literal")
        if labels and self.calls_borrows_accessor(e):
            self.report(e.line, "argument-labels",
                        "call the accessor `%s` positionally" % e.method_name)
        root = root_name(obj)
        if root is not None and self.is_local(root):
            if any(mentions(a.value, root) for a in e.arguments):
                self.report(e.line, "root-reuse",
                            "an argument reads `%s`, the receiver's root; bind it to a "
                            "`let` first" % root)

    def calls_borrows_accessor(self, e):
        """Does `e` call a `borrows` accessor? A traced receiver decides whose
        method it is; on an untraced one, any accessor of that name counts."""
        owner = _type_name(self.type_of(e.object))
        std_accessor = e.method_name in self.fc.std.borrows_methods
        if owner is not None and owner not in self.type_params:
            if (owner, e.method_name) in self.facts.borrows_owned:
                return True
            return owner not in self.facts.types and std_accessor
        return std_accessor or e.method_name in self.facts.borrows_methods

    def receiver_owner(self, e):
        """The build type whose method `e` calls, when the receiver's type is known."""
        owner = _type_name(self.type_of(e.object))
        if owner in self.facts.types:
            return owner
        return None

    def known_mutating(self, e):
        """Does `e` call a build method known to take `&var self`?"""
        owner = self.receiver_owner(e)
        if owner is not None:
            return self.facts.method_mutates.get((owner, e.method_name), False)
        kinds = self.facts.name_mutates.get(e.method_name)
        return bool(kinds) and kinds == {True}

    def may_mutate(self, e):
        name = e.method_name
        if name in READ_ONLY_METHODS:
            return False
        owner = self.receiver_owner(e)
        if owner is not None:
            return self.facts.method_mutates.get((owner, name), True)
        return not self.facts.read_only(name)

    def check_ref_args(self, e, args):
        values = [v for _, v in args]
        for i, v in enumerate(values):
            if not isinstance(v, A.ReferenceExpr):
                continue
            root = root_name(v)
            if root is None or not self.is_local(root):
                continue
            if any(mentions(w, root) for j, w in enumerate(values) if j != i):
                self.report(e.line, "root-reuse",
                            "another argument reads `%s`, which a `&` argument borrows; "
                            "bind it to a `let` first" % root)
                return

    def check_trailing_closures(self, e, args):
        for _, value in args:
            if isinstance(value, A.ClosureExpr):
                prev = self.fc.previous_token(value.line, value.column)
                if prev is not None and prev.type in (T.RPAREN, T.IDENT, T.GT):
                    self.report(value.line, "closure-syntax",
                                "pass a closure inside the argument parentheses")

    def check_postfix_chain(self, e, parent):
        if isinstance(parent, HOPS + CHAIN_WRAPPERS) and postfix_object(parent) is e:
            return
        hops = 0
        cur = e
        while isinstance(cur, HOPS + CHAIN_WRAPPERS):
            if isinstance(cur, HOPS):
                hops += 1
            cur = postfix_object(cur)
        if hops > MAX_CHAIN:
            self.report(e.line, "chain-length", "a postfix chain of %d hops; split it" % hops)

    def check_else_if_chain(self, e):
        arms = 1
        cur = e
        while True:
            branch = cur.else_branch
            if branch is None or branch.statements or not isinstance(
                    branch.final_expr, (A.IfExpr, A.IfLetExpr)):
                break
            cur = branch.final_expr
            self.chain_links.add(id(cur))
            arms += 1
        if arms > MAX_CHAIN:
            self.report(e.line, "chain-length",
                        "an `else if` chain of %d arms; use `match`" % arms)

    # -- the std API -----------------------------------------------------------

    def type_of(self, expr):
        """The written type an expression is known to have, or None."""
        facts = self.facts
        if isinstance(expr, A.Identifier):
            b = self.lookup(expr.name)
            return _peel(b.type) if b is not None else None
        if isinstance(expr, A.SelfExpr):
            if isinstance(self.owner, A.Extension):
                return _named(self.owner.struct_name)
            if isinstance(self.owner, A.Trait):
                return _named(self.owner.name)
            return None
        if isinstance(expr, A.MemberAccess):
            owner = _type_name(self.type_of(expr.object))
            return _peel(facts.fields.get(owner, {}).get(expr.member))
        if isinstance(expr, A.MethodCall):
            receiver = _peel(self.type_of(expr.object))
            owner = _type_name(receiver)
            if owner in facts.types:
                return _peel(facts.method_return(owner, expr.method_name))
            if expr.method_name == "get" and owner in ("Vector", "Map") and receiver.type_args:
                return A.SawType(A.TypeKind.OPTIONAL, inner_type=receiver.type_args[-1])
            if isinstance(expr.object, A.Identifier) and expr.object.name in facts.types:
                variants = facts.variants.get(expr.object.name, {})
                if expr.method_name in variants:
                    return _named(expr.object.name)
                return _peel(facts.method_return(expr.object.name, expr.method_name))
            return None
        if isinstance(expr, A.ArrayIndex):
            container = _peel(self.type_of(expr.array_expr))
            if _type_name(container) in ("Vector", "Map") and container.type_args:
                return _peel(container.type_args[-1])
            return None
        if isinstance(expr, (A.ForceUnwrap, A.BindOptional)):
            inner = _peel(self.type_of(expr.expr))
            return optional_payload(inner) if is_optional(inner) else None
        if isinstance(expr, A.FunctionCall):
            if expr.name in facts.functions:
                return _peel(facts.function_return(expr.name))
            if expr.name[:1].isupper():
                return _named(expr.name)
            return None
        if isinstance(expr, A.StructInit):
            return _named(expr.struct_name)
        if isinstance(expr, A.EnumInit):
            return _named(expr.enum_name)
        if isinstance(expr, A.MapLiteral):
            return _named("Map")
        if isinstance(expr, A.ReferenceExpr):
            return self.type_of(expr.expr)
        if isinstance(expr, A.MoveExpr):
            return self.type_of(A.Identifier(name=expr.variable))
        return None

    def check_subscript(self, e, parent):
        """`m[k]` on a Map, or a subscript read as an optional, which only a Map's
        is: an optional place in sawc/std, a panicking getitem in the new std."""
        optional_use = (isinstance(parent, (A.ForceUnwrap, A.BindOptional, A.NilCoalesce))
                        and parent.expr is e) or (
                        isinstance(parent, (A.IfLetExpr, A.GuardLetStatement))
                        and parent.optional_expr is e)
        if optional_use or _is_map(self.type_of(e.array_expr)):
            self.report(e.line, "std-api",
                        "`m[k]` on a Map changes meaning in the new std; use `get`")

    def check_place_write(self, target, line):
        if isinstance(target, A.OptionalEvalExpr):
            target = target.expr
        if isinstance(target, A.ForceUnwrap) and isinstance(target.expr, A.ArrayIndex):
            self.report(line, "std-api",
                        "`m[k]! = v` panics in sawc/std and inserts in the new std")
        elif reaches_get(target):
            self.report(line, "std-api",
                        "a write through `get` writes a place in sawc/std and a copy in "
                        "the new std")

    def check_presence_test(self, name, pattern, subject, line):
        if not pattern_names(pattern, [name]) and _is_get_call(subject):
            self.report(line, "std-api",
                        "a presence test through `get`; compare the index with `len()`")

    def check_std_call(self, e):
        """A call that reaches std must be on `STD_API`. A method's receiver
        decides whose method it is when its type is traceable; otherwise a name
        std also declares is judged as std's."""
        facts = self.facts
        if isinstance(e, A.FunctionCall):
            if e.name in facts.functions or e.name in facts.types or self.is_local(e.name):
                return
            key = e.name
        elif isinstance(e, A.StructInit):
            # The frozen parser reads any `name(label: ...)` as a construction.
            if e.struct_name in facts.types or e.struct_name in facts.functions:
                return
            key = e.struct_name
        elif isinstance(e, A.EnumInit):
            if e.enum_name in facts.types:
                return
            key = "%s.%s" % (e.enum_name, e.variant_name)
        else:
            if e.method_name in RETIRED_STD_METHODS or (
                    e.method_name == "lock"
                    and any(isinstance(a.value, A.ClosureExpr) for a in e.arguments)):
                self.report(e.line, "std-api",
                            "`%s` is retired in the new std" % e.method_name)
                return
            self.check_through_get(e)
            key = self.method_key(e)
            if key is None:
                return
        if key not in STD_API:
            self.report(e.line, "std-api",
                        "`%s` is not on the compiler's std API allowlist" % key)

    def check_through_get(self, e):
        obj = e.object
        if _is_get_call(obj) or (isinstance(obj, (A.ForceUnwrap, A.BindOptional))
                                 and _is_get_call(obj.expr)):
            if e.method_name in ("is_some", "is_none"):
                self.report(e.line, "std-api",
                            "a presence test through `get`; compare the index with `len()`")
                return
        if reaches_get(obj) and not _is_get_call(obj) and self.may_mutate(e):
            self.report(e.line, "std-api",
                        "`.%s()` through `get` acts on a place in sawc/std and a copy in "
                        "the new std" % e.method_name)

    def method_key(self, e):
        """The allowlist key for a method call, or None for the build's own."""
        facts = self.facts
        obj = e.object
        if isinstance(obj, A.Identifier) and not self.is_local(obj.name):
            if obj.name in facts.modules or obj.name in facts.types \
                    or obj.name in self.type_params:
                return None
            if obj.name[:1].isupper():
                return "%s.%s" % (obj.name, e.method_name)
        path = member_path(obj)
        if path is not None and len(path) > 1 and not self.is_local(path[0]):
            member = facts.module_member(path)
            if member in (("module", len(path)), ("type", len(path))):
                return None
        receiver = _peel(self.type_of(obj))
        name = _type_name(receiver)
        if receiver is not None and receiver.kind == A.TypeKind.EXISTENTIAL:
            name = receiver.existential_trait
        if name in self.type_params:
            # A type parameter's methods are its bounds': a build trait's is the
            # build's; any other is judged as untraced.
            if any((bound, e.method_name) in facts.method_returns
                   for bound in self.type_params[name]):
                return None
        elif name is not None:
            if name in facts.types or (name, e.method_name) in facts.method_returns:
                return None
            return "." + e.method_name
        # An untraced receiver: a name std also declares is judged as std's, so
        # a compiler method of that name cannot switch the allowlist off.
        if e.method_name in facts.methods and e.method_name not in self.fc.std.methods:
            return None
        return "." + e.method_name


def _static_root_message(reach, name):
    # Every `static` is refused as a root, a mutable one included: its writes
    # belong in a local `var` (SL:hazards S5).
    return "%s the `static` `%s`; copy it into a local `var` first" % (reach, name)


def _count_nested(e, kind, fields):
    count = 0
    stack = [e]
    while stack:
        n = stack.pop()
        if isinstance(n, kind):
            stack.extend(getattr(n, f) for f in fields)
        else:
            count += 1
    return count


def _returns_value(block):
    """Does a body hold a `return` with a value, outside nested closures?"""
    stack = [block]
    while stack:
        n = stack.pop()
        if isinstance(n, A.ClosureExpr):
            continue
        if isinstance(n, A.ReturnStatement) and n.value is not None:
            return True
        stack.extend(children(n))
    return False


# ---------------------------------------------------------------------------
# Rules over a whole build: the names every file in it declares.
# ---------------------------------------------------------------------------

def _all_programs(files):
    for f in files:
        if f.program is not None:
            for prog in programs(f.program):
                yield f, prog


def check_build(reported, context, std):
    """Rules that compare declarations across one build, inline modules
    included. Only `reported` files get diagnostics; `context` files contribute
    their declarations."""
    diags = []
    declared = {}
    type_sites = {}
    generic_functions = set()
    generic_methods = set()
    types = set(std.types)
    enums = set()
    overloads = {}
    kinds_by_method = {key: set(kinds) for key, kinds in std.method_kinds.items()}
    for f, prog in _all_programs(reported + context):
        for fn in prog.functions:
            declared.setdefault(fn.name, set()).add(f.rel)
            overloads.setdefault(("func", fn.name), []).append((f, fn))
            if fn.type_params:
                generic_functions.add(fn.name)
        for st in prog.statics:
            declared.setdefault(st.name, set()).add(f.rel)
        for decl in _type_decls(prog):
            types.add(decl.name)
            type_sites.setdefault(decl.name, []).append("%s:%d" % (f.rel, decl.line))
        for en in prog.enums:
            enums.add(en.name)
        for ext in prog.extensions:
            for m in ext.methods:
                overloads.setdefault(("method", ext.struct_name, m.name), []).append((f, m))
                if m.type_params or ext.type_params:
                    generic_methods.add(m.name)
                if not m.is_init:
                    kind = "static" if m.is_static else "instance"
                    kinds_by_method.setdefault((ext.struct_name, m.name), set()).add(kind)

    def report(f, line, rule, message):
        diags.append(Diagnostic(f.rel, line, rule, message))

    for f, prog in _all_programs(reported):
        decls = [(fn.name, fn.line) for fn in prog.functions] + \
                [(st.name, st.line) for st in prog.statics]
        for name, line in decls:
            if name in std.names:
                report(f, line, "program-unique-names",
                       "`%s` is also declared in %s; prefix it with the module's name"
                       % (name, std.names[name]))
            elif len(declared.get(name, ())) > 1:
                others = sorted(declared[name] - {f.rel})
                report(f, line, "program-unique-names",
                       "`%s` is also declared in %s" % (name, ", ".join(others)))
        # The checker's facts about a type are keyed by its name, so a second
        # declaration would answer for the first.
        for decl in _type_decls(prog):
            here = "%s:%d" % (f.rel, decl.line)
            others = sorted(set(type_sites[decl.name]) - {here})
            if others:
                report(f, decl.line, "program-unique-names",
                       "the type `%s` is also declared at %s" % (decl.name, ", ".join(others)))
        for fn in prog.functions:
            if fn.type_params and fn.name in (generic_methods | std.generic_methods):
                report(f, fn.line, "name-collision",
                       "the generic function `%s` shares its name with a generic method"
                       % fn.name)
        for ext in prog.extensions:
            for m in ext.methods:
                if (m.type_params or ext.type_params) and \
                        m.name in (generic_functions | std.generic_functions):
                    report(f, m.line, "name-collision",
                           "the generic method `%s` shares its name with a generic function"
                           % m.name)
                if not m.is_init and \
                        len(kinds_by_method.get((ext.struct_name, m.name), ())) > 1:
                    report(f, m.line, "name-collision",
                           "`%s.%s` is both a static and an instance method"
                           % (ext.struct_name, m.name))
                if ext.struct_name in enums and m.name == "equals":
                    report(f, m.line, "enum-equatable-body",
                           "an enum's hand-written `equals` disagrees with `==`; write "
                           "`@synthesize extension %s: Equatable {}`, or give the "
                           "comparison its own method name" % ext.struct_name)
        for owner in _type_param_owners(prog):
            for tp in owner.type_params:
                if tp.name in types:
                    report(f, tp.line or owner.line, "name-collision",
                           "the type parameter `%s` is spelled like a declared type"
                           % tp.name)
    reported_files = set(id(f) for f in reported)
    for members in overloads.values():
        if len(members) < 2:
            continue
        if not any(_has_narrow_integer(decl) for _, decl in members):
            continue
        for f, decl in members:
            if id(f) in reported_files:
                report(f, decl.line, "integer-overload",
                       "no overloads where an overload takes a non-`Int` integer")
    return diags


def _type_decls(prog):
    return prog.structs + prog.enums + prog.traits + prog.type_definitions


def _type_param_owners(prog):
    for decl in prog.functions + prog.structs + prog.enums + prog.traits:
        yield decl
    for ext in prog.extensions:
        yield ext
        for m in ext.methods:
            yield m


def _has_narrow_integer(decl):
    for p in decl.parameters:
        t = _peel(p.type)
        if t is not None and t.kind in NON_INT_INTEGERS:
            return True
    return False


# ---------------------------------------------------------------------------
# Entry points.
# ---------------------------------------------------------------------------

def tree_files():
    """Every compiler source file in scope, sorted."""
    root = os.path.join(REPO, "compiler")
    out = []
    for path in glob.glob(os.path.join(root, "**", "*.saw"), recursive=True):
        rel = os.path.relpath(path, root)
        if rel.split(os.sep)[0] == "tests" or path.endswith(".test.saw"):
            continue
        out.append(path)
    return sorted(out)


def _under(path, rel_dir):
    return path.startswith(os.path.join(REPO, rel_dir) + os.sep)


def stage_files():
    """The source files of every stage package, which a unit program links."""
    dirs = [os.path.join(rel, "src") for _, rel in STAGE_PACKAGES]
    return [p for p in tree_files() if any(_under(p, d) for d in dirs)]


def check_files(paths, compiler=(), stages=None):
    """Check `paths`. The `compiler` files are one build (the driver and every
    stage package); each other file is a build of its own, linked against the
    stage packages, as a unit program is."""
    if stages is None:
        stages = stage_files()
    std = std_facts()
    diags = []
    loaded = {p: SourceFile(p) for p in sorted(set(paths) | set(compiler) | set(stages))}
    compiler_files = [loaded[p] for p in sorted(compiler)]
    stage_sources = [loaded[p] for p in sorted(stages) if p not in paths or p in compiler]
    compiler_facts = BuildFacts(compiler_files)
    for p in sorted(set(paths)):
        if p in compiler:
            facts = compiler_facts
        else:
            facts = BuildFacts([loaded[p]] + stage_sources)
        diags.extend(FileChecker(loaded[p], std, facts).run())
    if compiler:
        diags.extend(check_build(compiler_files, [], std))
    for p in sorted(set(paths) - set(compiler)):
        diags.extend(check_build([loaded[p]], stage_sources, std))
    return sorted(set(diags))


def check_tree():
    files = tree_files()
    stages = stage_files()
    compiler = stages + [p for p in files if _under(p, os.path.join("compiler", "driver", "src"))]
    return files, check_files(files, compiler, stages)


def main(argv):
    if argv:
        paths = [os.path.abspath(p) for p in argv]
        diags = check_files(paths)
        count = len(paths)
    else:
        files, diags = check_tree()
        count = len(files)
    for d in diags:
        print(d.render())
    print("subset: %d file(s), %d diagnostic(s)" % (count, len(diags)))
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

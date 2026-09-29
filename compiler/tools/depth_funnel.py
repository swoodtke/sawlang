#!/usr/bin/env python3
"""The parser's stack use is bounded by its depth budget, statically and at run time.

    python compiler/tools/depth_funnel.py            check compiler/parse/src
    python compiler/tools/depth_funnel.py FILE...    check these files as one package
    python compiler/tools/depth_funnel.py --cycles   also print each recursive component

`Parser.enter_level` is the one place the parser charges a level of its
256-deep budget (SL-424, contract item 5), and this lane holds the parser to it.

STATICALLY, every recursion in `compiler/parse/src` passes through a charge.
The call graph's nodes are the package's free functions and methods, read with
the frozen compiler's own parser. An edge is a call: a free function by name,
and a method through `self` or through a receiver whose type the lane follows
from written types (fields, parameters, annotated or initialized locals, a
return type), or, where it cannot, every package method of that name. A call is
CHARGED when it sits in a statement after one that calls `self.enter_level`,
and before one that calls `self.leave_level`, in the same block. The graph of
uncharged edges must be acyclic, self-edges included, and nothing is exempt,
so every walk over a finished tree is a loop. The funnel's ENTRY POINTS comment
must name exactly the methods that charge.

AT RUN TIME, through `sawc2 parse --check`: 256 levels of each claimed
nesting construct are accepted and the 257th is refused at its opener by
syntax.rule.depth-limit, a flat chain far deeper than any stack parses, and a
refused statement gives its depth back to the next one.

The lane proves itself on fixtures in `compiler/tests/funnel/`, each naming
the failures it must produce, and on the real parser with its funnel call cut
out of `parse_paren`, which must fail as a recursion that bypasses the funnel.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402
import subset_check  # noqa: E402
import ast_nodes as A  # noqa: E402  (on sys.path through subset_check)

PACKAGE = os.path.join(REPO, "compiler", "parse", "src")
FUNNEL_FILE = os.path.join(PACKAGE, "parser.saw")
FIXTURES = os.path.join(REPO, "compiler", "tests", "funnel")
WORK = os.path.join(REPO, ".build", "depth-funnel")
FUNNEL = "enter_level"
RELEASE = "leave_level"
ENTRY_POINTS = "ENTRY POINTS:"
LIMIT = 256
DEPTH_RULE = "syntax.rule.depth-limit"
# A flat chain this long overflows any stack a recursion per operand would use.
FLAT_TERMS = 20000
_EXPECT = re.compile(r"^// expect: (.+)$")


def type_name(t):
    """The name a written type names, looking through `&`: a declared type's
    own name, or the kind of a primitive, which no package declares."""
    while t is not None and t.kind == A.TypeKind.REFERENCE:
        t = t.inner_type
    if t is None:
        return None
    return t.struct_name or t.enum_name or "<%s>" % t.kind.name


class Package:
    """The declarations of the checked files: types' fields and methods, and
    free functions, each with the Saw declaration behind it."""

    def __init__(self, sources):
        self.fields = {}      # type -> {field: type name}
        self.methods = {}     # type -> {method: declaration}
        self.functions = {}   # name -> declaration
        self.scopes = []      # (key, owner type or None, declaration, path)
        for src in sources:
            if src.program is None:
                raise SystemExit("depth-funnel: %s does not parse" % src.rel)
            prog = src.program
            for s in prog.structs:
                self.fields[s.name] = {f.name: type_name(f.type) for f in s.fields}
            for f in prog.functions:
                self.functions[f.name] = f
                self.scopes.append((f.name, None, f, src.rel))
            for ext in prog.extensions:
                for m in ext.methods:
                    self.methods.setdefault(ext.struct_name, {})[m.name] = m
                    self.scopes.append(("%s.%s" % (ext.struct_name, m.name), ext.struct_name,
                                        m, src.rel))

    def by_name(self, method):
        return sorted("%s.%s" % (t, method) for t, ms in self.methods.items() if method in ms)


class Resolver:
    """Types of the expressions one declaration's calls are made on."""

    def __init__(self, package, owner, decl):
        self.p = package
        self.owner = owner
        self.locals = {prm.name: type_name(prm.type) for prm in decl.parameters}
        for n in subset_check.walk(decl.body):
            if isinstance(n, A.LetStatement):
                self.locals[n.name] = (type_name(n.type_annotation) if n.type_annotation
                                       else self.type_of(n.value))

    def type_of(self, e):
        if isinstance(e, A.SelfExpr):
            return self.owner
        if isinstance(e, A.Identifier):
            return self.locals.get(e.name)
        if isinstance(e, A.MemberAccess):
            base = self.type_of(e.object)
            return self.p.fields.get(base, {}).get(e.member) if base else None
        if isinstance(e, A.StructInit):
            return e.struct_name
        if isinstance(e, A.FunctionCall) and e.name in self.p.functions:
            return type_name(self.p.functions[e.name].return_type)
        if isinstance(e, A.MethodCall):
            base = self.type_of(e.object)
            m = self.p.methods.get(base, {}).get(e.method_name) if base else None
            return type_name(m.return_type) if m is not None else None
        return None

    def targets(self, call):
        """The graph nodes a call can reach."""
        if isinstance(call, A.FunctionCall):
            return [call.name] if call.name in self.p.functions else []
        base = self.type_of(call.object)
        if base is not None and base not in self.p.methods and base not in self.p.fields:
            return []
        if base is not None:
            ms = self.p.methods.get(base, {})
            return ["%s.%s" % (base, call.method_name)] if call.method_name in ms else []
        return self.p.by_name(call.method_name)


def calls_in(node):
    return [n for n in subset_check.walk(node) if isinstance(n, (A.FunctionCall, A.MethodCall))]


def is_self_call(call, name):
    return isinstance(call, A.MethodCall) and call.method_name == name \
        and isinstance(call.object, A.SelfExpr)


def edges_of(resolver, decl):
    """[(target, charged, line)] for one declaration: a call is charged when it
    sits in a statement after the one that calls the funnel and before the one
    that releases it, in the same block."""
    out = []
    pending = [(decl.body, False)]
    while pending:
        block, charged = pending.pop()
        items = list(block.statements) + ([block.final_expr] if block.final_expr else [])
        state = charged
        for stmt in items:
            calls = calls_in(stmt)
            opens = any(is_self_call(c, FUNNEL) for c in calls)
            closes = any(is_self_call(c, RELEASE) for c in calls)
            nested = [n for n in subset_check.walk(stmt) if isinstance(n, A.Block) and n is not stmt]
            inner = set()
            for b in nested:
                for c in calls_in(b):
                    inner.add(id(c))
            for c in calls:
                if id(c) in inner:
                    continue
                for t in resolver.targets(c):
                    out.append((t, state, getattr(c, "line", 0)))
            outermost = [b for b in nested
                         if not any(b is not o and any(x is b for x in subset_check.walk(o))
                                    for o in nested)]
            for b in outermost:
                pending.append((b, state))
            if opens:
                state = True
            if closes:
                state = charged
    return out


def strongly_connected(g):
    """Tarjan's algorithm, iterative; the components that hold a cycle."""
    index, low, on_stack, stack, out = {}, {}, set(), [], []
    counter = [0]
    for root in sorted(g):
        if root in index:
            continue
        work = [(root, iter(sorted(g[root])))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for succ in it:
                if succ not in index:
                    index[succ] = low[succ] = counter[0]
                    counter[0] += 1
                    stack.append(succ)
                    on_stack.add(succ)
                    work.append((succ, iter(sorted(g[succ]))))
                    advanced = True
                    break
                if succ in on_stack:
                    low[node] = min(low[node], index[succ])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in g[node]:
                    out.append(sorted(comp))
    return out


def find_cycle(g, comp):
    members = set(comp)
    path = [comp[0]]
    seen = {comp[0]: 0}
    node = comp[0]
    while True:
        succ = next(s for s in sorted(g[node]) if s in members)
        if succ in seen:
            return path[seen[succ]:] + [succ]
        seen[succ] = len(path)
        path.append(succ)
        node = succ


def entry_points(sources):
    """The names the comment above `func enter_level` lists, or None when no
    file holds the funnel."""
    for src in sources:
        lines = src.text.split("\n")
        for k, line in enumerate(lines):
            if line.strip().startswith("func %s(" % FUNNEL):
                j = k - 1
                block = []
                while j >= 0 and lines[j].strip().startswith("//"):
                    block.insert(0, lines[j].strip()[2:].strip())
                    j -= 1
                if ENTRY_POINTS not in block:
                    return set()
                return {name for name in block[block.index(ENTRY_POINTS) + 1:] if name}
    return None


def static_failures(sources, show_cycles=False):
    """(failure lines, scopes, charging methods) for one package's sources."""
    package = Package(sources)
    full = {key: set() for key, _, _, _ in package.scopes}
    uncharged = {key: set() for key in full}
    charging = set()
    where = {}
    for key, owner, decl, rel in package.scopes:
        where[key] = "%s:%d" % (rel, getattr(decl, "line", 0))
        resolver = Resolver(package, owner, decl)
        for target, charged, _ in edges_of(resolver, decl):
            full[key].add(target)
            if not charged:
                uncharged[key].add(target)
        if any(is_self_call(c, FUNNEL) for c in calls_in(decl.body)):
            charging.add(decl.name)
    failures = []
    for comp in strongly_connected(uncharged):
        cycle = find_cycle(uncharged, comp)
        failures.append("a recursion never enters `self.%s(...)`: %s (at %s)"
                        % (FUNNEL, " -> ".join(cycle), ", ".join(where[k] for k in cycle[:-1])))
    listed = entry_points(sources)
    if listed is not None:
        charging.discard(FUNNEL)
        for name in sorted(charging - listed):
            failures.append("`%s` charges the depth budget, but the funnel's %s list does "
                            "not name it" % (name, ENTRY_POINTS))
        for name in sorted(listed - charging):
            failures.append("the funnel's %s list names `%s`, which never calls `self.%s`"
                            % (ENTRY_POINTS, name, FUNNEL))
    if show_cycles:
        for comp in strongly_connected(full):
            print("recursive component: %s; charged by %s"
                  % (", ".join(comp), ", ".join(sorted(c for c in comp
                                                       if c.split(".")[-1] in charging))))
    return failures, len(package.scopes), len(charging)


def package_sources(paths=None):
    paths = paths or sorted(glob.glob(os.path.join(PACKAGE, "*.saw")))
    return [subset_check.SourceFile(p) for p in paths]


# ---- the lane's own evidence ------------------------------------------------------

def fixture_failures():
    """Each fixture reports exactly the failures its `// expect:` lines name,
    each a substring of one failure; a fixture with none must pass."""
    out = []
    paths = sorted(glob.glob(os.path.join(FIXTURES, "*.saw")))
    for path in paths:
        src = subset_check.SourceFile(path)
        expects = [m.group(1) for m in map(_EXPECT.match, src.text.split("\n")) if m]
        got, _, _ = static_failures([src])
        rel = os.path.relpath(path, REPO)
        for want in expects:
            if not any(want in g for g in got):
                out.append("depth-funnel fixture %s: expected a failure containing %r" % (rel, want))
        for g in got:
            if not any(want in g for want in expects):
                out.append("depth-funnel fixture %s: unexpected: %s" % (rel, g))
    return out, len(paths)


def injected_failures():
    """The real parser with the funnel call cut out of `parse_paren` must fail
    as a recursion that bypasses the funnel."""
    with open(FUNNEL_FILE, encoding="utf-8") as fh:
        text = fh.read()
    anchor = "self.%s(open)" % FUNNEL
    head = text.find("func parse_paren(")
    body_end = text.find("\n    func ", head + 1) if head >= 0 else -1
    cut = text.find(anchor, head, body_end if body_end >= 0 else len(text)) if head >= 0 else -1
    if cut < 0:
        return ["depth-funnel: the injection's anchor, `%s` in `parse_paren`, is gone from %s; "
                "move the anchor with the code" % (anchor, os.path.relpath(FUNNEL_FILE, REPO))]
    injected = text[:cut] + "true" + text[cut + len(anchor):]
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, "parser.saw")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(injected)
    others = [p for p in sorted(glob.glob(os.path.join(PACKAGE, "*.saw"))) if p != FUNNEL_FILE]
    got, _, _ = static_failures(package_sources(others + [path]))
    bypass = [g for g in got if g.startswith("a recursion never enters") and "parse_paren" in g]
    if not bypass:
        return ["depth-funnel: the parser with its funnel cut out of `parse_paren` passes; "
                "the lane cannot see a recursion that bypasses the funnel"]
    return []


# ---- the run-time cells ---------------------------------------------------------------

def in_function(expr):
    return "func f() {\n    let x = " + expr + "\n}\n"


def parens(k):
    return in_function("(" * k + "1" + ")" * k)


def modules(k):
    return "module m {\n" * k + "}\n" * k


def prefix_run(k):
    return in_function("- " * k + "1")


def cast_chain(k):
    return in_function("1" + " as Int" * k)


def brackets(k):
    return in_function("[" * k + "1" + "]" * k)


def postfix_chain(k):
    return in_function("a" + ".b" * k)


def try_run(k):
    return in_function("try " * k + "1")


def interpolations(k):
    return in_function('"{' * k + "1" + '}"' * k)


def in_type(ty):
    return "func f() {\n    let x: " + ty + " = w\n}\n"


def generic_args(k):
    return in_type("A<" * k + "B" + ">" * k)


def function_types(k):
    return in_type("() -> " * k + "Int")


def tuple_types(k):
    return in_type("(" * k + "Int" + ", Int)" * k)


def failed_speculation(k):
    """A generic list that fails and is re-read as comparisons, then k levels,
    which fit only if the failed speculation gave its level back."""
    return in_function("(a < b, c) + " + "(" * k + "1" + ")" * k)


def cut_speculation(k):
    """A generic list k levels deep. Cut short by the limit it is refused
    there, never re-read as the comparisons that would fit."""
    return in_function("f<" + "(" * (k - 1) + "Int" + ")" * (k - 1) + ">(x)")


def flat_comparisons(pairs):
    """An argument list of `pairs` comparisons. No `>` follows any `<`, so no
    generic list is speculated and the run charges nothing per pair."""
    args = ", ".join("x%d < x%d" % (2 * i, 2 * i + 1) for i in range(pairs))
    return in_function("g(" + args + ")")


def balanced_speculation(k):
    """A call hop and k - 1 generic lists, each nested in the one before, which
    the `>` run and `(d)` keep: k levels, so the limit refuses the list at the
    257th, never re-reading the lists as comparisons."""
    lists = ", ".join("a%d < a%d" % (2 * i, 2 * i + 1) for i in range(k - 1))
    return in_function("g(" + lists + " " + "> " * (k - 1) + "(d))")


def nested_ifs(k):
    return in_function("if a { " * k + "1" + " }" * k)


def ifs_in_else_if_arms(k):
    """An `if` nested in an `else if` arm's body charges a level of its own."""
    return in_function("if a { 1 } else if a { " * k + "1" + " }" * k)


def else_if_chain(arms):
    """One `if` chain: one level, whatever its number of arms."""
    return in_function("if a { 1 }" + " else if a { 1 }" * (arms - 1) + " else { 1 }")


def nested_matches(k):
    return in_function("match a { case _ -> " * k + "1" + " }" * k)


def nested_whiles(k):
    return in_function("while a { " * k + "1" + " }" * k)


def nested_while_lets(k):
    return in_function("while let x = a { " * k + "1" + " }" * k)


def nested_fors(k):
    return in_function("for i in a { " * k + "1" + " }" * k)


def nested_try_blocks(k):
    return in_function("try { " * k + "1" + " } catch { 1 }" * k)


def nested_guards(k):
    return "func f() {\n    " + "guard a else { " * k + "return" + " }" * k + "\n}\n"


def nested_tuple_patterns(k):
    return "func f() {\n    let " + "(" * k + "a" + ")" * k + " = w\n}\n"


def nested_variant_payloads(k):
    """The `match` takes one level, and each payload's `(` one more."""
    return ("func f() {\n    match w { case " + "A(" * (k - 1) + "b" + ")" * (k - 1)
            + " -> 1 }\n}\n")


def mixed_patterns(k):
    """Tuple and variant patterns alternating, from a destructuring `let`."""
    openers = "".join("(" if i % 2 == 0 else "A(" for i in range(k))
    return "func f() {\n    let " + openers + "a" + ")" * k + " = w\n}\n"


def nth(text, needle, n, shift=0):
    """The offset of the nth occurrence of `needle` in `text`, plus `shift`."""
    at = -1
    for _ in range(n):
        at = text.index(needle, at + 1)
    return at + shift


def cells():
    """(name, text, expected first refusal or None, its line:col or None)."""
    out = []
    for name, build_text, find in (
            ("nested parentheses", parens, lambda t: t.index("(" * 256) + 256),
            ("nested inline modules", modules, None),
            ("a prefix run", prefix_run, lambda t: nth(t, "- ", LIMIT + 1)),
            ("an `as` chain", cast_chain, lambda t: nth(t, " as ", LIMIT + 1, 1)),
            ("nested array literals", brackets, lambda t: nth(t, "[", LIMIT + 1)),
            ("a postfix chain", postfix_chain, lambda t: nth(t, ".b", LIMIT + 1)),
            ("a `try` run", try_run, lambda t: nth(t, "try ", LIMIT + 1)),
            ("nested interpolations", interpolations, lambda t: nth(t, '"{', LIMIT + 1)),
            ("nested generic arguments", generic_args, lambda t: nth(t, "<", LIMIT + 1)),
            ("nested function types", function_types, lambda t: nth(t, "() ->", LIMIT + 1)),
            ("nested tuple types", tuple_types, lambda t: t.index("(" * (LIMIT + 1)) + LIMIT),
            ("a failed speculation's levels", failed_speculation,
             lambda t: t.index("(" * (LIMIT + 1)) + LIMIT),
            ("a speculation the limit cuts short", cut_speculation,
             lambda t: t.index("(" * LIMIT) + LIMIT - 1),
            ("balanced speculated lists", balanced_speculation,
             lambda t: nth(t, " < ", LIMIT, 1)),
            ("nested `if` chains", nested_ifs, lambda t: nth(t, "if a", LIMIT + 1)),
            ("`if` chains in `else if` arms", ifs_in_else_if_arms,
             lambda t: nth(t, "if a { 1 }", LIMIT + 1)),
            ("nested `match` expressions", nested_matches, lambda t: nth(t, "match", LIMIT + 1)),
            ("nested `while` loops", nested_whiles, lambda t: nth(t, "while", LIMIT + 1)),
            ("nested `while let` loops", nested_while_lets, lambda t: nth(t, "while", LIMIT + 1)),
            ("nested `for` loops", nested_fors, lambda t: nth(t, "for", LIMIT + 1)),
            ("nested try blocks", nested_try_blocks, lambda t: nth(t, "try", LIMIT + 1)),
            ("nested `guard` statements", nested_guards, lambda t: nth(t, "guard", LIMIT + 1)),
            ("nested tuple patterns", nested_tuple_patterns, lambda t: nth(t, "(", LIMIT + 2)),
            ("nested variant payloads", nested_variant_payloads,
             lambda t: nth(t, "(", LIMIT + 1)),
            ("mixed tuple and variant patterns", mixed_patterns,
             lambda t: nth(t, "(", LIMIT + 2))):
        out.append(("%s at %d" % (name, LIMIT), build_text(LIMIT), None, None))
        text = build_text(LIMIT + 1)
        at = find(text) if find else None
        out.append(("%s at %d" % (name, LIMIT + 1), text, DEPTH_RULE, at))
    for op in ("??", "||", "&&", "|", "^", "&"):
        chain = (" %s " % op).join(["a"] * FLAT_TERMS)
        out.append(("a flat `%s` chain of %d operands" % (op, FLAT_TERMS),
                    "func f() {\n    let x = %s\n}\n" % chain, None, None))
    for pairs in (LIMIT + 1, FLAT_TERMS // 2):
        out.append(("a flat run of %d comparison arguments" % pairs, flat_comparisons(pairs),
                    None, None))
    for arms in (300, FLAT_TERMS // 4):
        out.append(("an `if` chain of %d arms" % arms, else_if_chain(arms), None, None))
    recovered = ("func f() {\n    let x = " + "(" * (LIMIT + 1) + "1" + ")" * (LIMIT + 1)
                 + "\n    let y = " + "(" * LIMIT + "1" + ")" * LIMIT + "\n}\n")
    out.append(("a refused statement gives its depth back", recovered, DEPTH_RULE, None))
    return out


def position(text, offset):
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return "%d:%d" % (line, col)


def runtime_failures():
    os.makedirs(WORK, exist_ok=True)
    rows = cells()
    paths = []
    for k, (_, text, _, _) in enumerate(rows):
        path = os.path.join(WORK, "cell%d.saw" % k)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        paths.append(path)
    r = subprocess.run([build.SAWC2, "parse", "--check"] + paths, capture_output=True)
    records = {}
    current = None
    for line in r.stdout.decode("utf-8", "replace").split("\n"):
        if line.startswith("FILE\t"):
            current = records.setdefault(line[5:], [])
        elif line.startswith("ERROR\t") and current is not None:
            current.append(line.split("\t"))
    out = []
    for (name, text, want, at), path in zip(rows, paths):
        errors = records.get(path)
        if errors is None:
            out.append("depth-funnel cell %s: sawc2 printed no record (exit %d)"
                       % (name, r.returncode))
        elif want is None and errors:
            out.append("depth-funnel cell %s: refused: %s" % (name, "\t".join(errors[0][1:])))
        elif want is not None and (not errors or errors[0][1] != want):
            out.append("depth-funnel cell %s: expected %s first, got %s"
                       % (name, want, errors[0][1] if errors else "an acceptance"))
        elif want is not None and len(errors) != 1:
            out.append("depth-funnel cell %s: expected one refusal, got %d" % (name, len(errors)))
        elif at is not None and errors[0][2] != position(text, at):
            out.append("depth-funnel cell %s: refused at %s, expected the opener at %s"
                       % (name, errors[0][2], position(text, at)))
    return out, len(rows)


def run(show_cycles=False):
    """(failure lines, counts) for run.py."""
    failures, scopes, charging = static_failures(package_sources(), show_cycles)
    fixture, fixtures = fixture_failures()
    failures += fixture + injected_failures()
    cell_failures, cell_count = runtime_failures()
    failures += cell_failures
    return failures, {"depth-funnel scopes": scopes, "depth-funnel entry points": charging,
                      "depth-funnel fixtures": fixtures, "depth-funnel cells": cell_count}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--cycles", action="store_true", help="print each recursive component")
    args = ap.parse_args(argv)
    if args.files:
        failures, _, _ = static_failures(package_sources([os.path.abspath(f) for f in args.files]),
                                         args.cycles)
        counts = {}
    else:
        ok, output = build.build_sawc2()
        if not ok:
            print("depth-funnel: sawc2 does not build: %s" % output.strip().split("\n")[-1])
            return 1
        failures, counts = run(args.cycles)
    for f in failures:
        print("FAIL: " + f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("depth-funnel: %s%s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                  ": " + summary if summary else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

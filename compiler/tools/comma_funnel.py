#!/usr/bin/env python3
"""Every comma-separated list in the parser goes through its one comma-list funnel.

    python compiler/tools/comma_funnel.py            check compiler/parse/src
    python compiler/tools/comma_funnel.py FILE...    check these files as one package

`Parser.parse_comma_list` parses every list whose elements a `,` separates
(SL-437): its element parser, closer, trailing-comma policy and line breaks come
from the position matrix `list_shape`. This lane holds the parser to that, over
the source as the frozen compiler's own parser reads it.

A COMMA TAKE is an `if` whose condition tests `kind == TokenKind.Comma` (or
`kind_at(n) == TokenKind.Comma`) and whose `then` block consumes a token
(`self.advance()` or `self.take_leaf()`), or a `while` whose condition tests
it and whose body consumes one. A declaration that holds a take TAKES commas.
A COMMA LOOP is a `while` or `for` whose body holds a take or calls a
declaration that takes commas, the funnel apart. The lane fails on:

- a comma loop outside the funnel that the funnel's COMMA LEDGER does not
  exempt, a ledger line naming a declaration with no comma loop, and a ledger
  line with no reason;
- a funnel whose ENTRY POINTS list is not exactly the declarations that call
  it.

It proves itself on a copy of the parser with an ad hoc comma loop added, which
must fail as unexempted, and with a stale ledger line and a missing entry point.
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import subset_check  # noqa: E402
import ast_nodes as A  # noqa: E402  (on sys.path through subset_check)

PACKAGE = os.path.join(REPO, "compiler", "parse", "src")
FUNNEL_FILE = os.path.join(PACKAGE, "parser.saw")
WORK = os.path.join(REPO, ".build", "comma-funnel")
FUNNEL = "parse_comma_list"
ENTRY_POINTS = "ENTRY POINTS:"
LEDGER = "COMMA LEDGER:"
CONSUMERS = ("advance", "take_leaf")
_LEDGER_LINE = re.compile(r"^(\w+): (\S.*)$")


def is_comma(e):
    return (isinstance(e, A.MemberAccess) and e.member == "Comma"
            and isinstance(e.object, A.Identifier) and e.object.name == "TokenKind")


def tests_comma(e):
    """Whether expression `e` holds an `==` test against `TokenKind.Comma`."""
    if e is None:
        return False
    for n in subset_check.walk(e):
        if isinstance(n, A.BinaryOp) and n.op == "==" and (is_comma(n.left)
                                                                 or is_comma(n.right)):
            return True
    return False


def consumes(node):
    """Whether `node` holds a call that consumes a token."""
    if node is None:
        return False
    for n in subset_check.walk(node):
        if (isinstance(n, A.MethodCall) and isinstance(n.object, A.SelfExpr)
                and n.method_name in CONSUMERS):
            return True
    return False


def takes(node):
    """Whether `node` holds a comma take."""
    for n in subset_check.walk(node):
        if isinstance(n, A.IfExpr) and tests_comma(n.condition) and consumes(n.then_branch):
            return True
        if isinstance(n, A.WhileExpr) and tests_comma(n.condition) and consumes(n.body):
            return True
    return False


def called(node):
    """The names `node` calls: methods through `self`, and free functions."""
    out = set()
    for n in subset_check.walk(node):
        if isinstance(n, A.MethodCall) and isinstance(n.object, A.SelfExpr):
            out.add(n.method_name)
        elif isinstance(n, A.FunctionCall):
            out.add(n.name)
    return out


def declarations(sources):
    """[(name, declaration, path)] of every free function and method."""
    out = []
    for src in sources:
        if src.program is None:
            raise SystemExit("comma-funnel: %s does not parse" % src.rel)
        for f in src.program.functions:
            out.append((f.name, f, src.rel))
        for ext in src.program.extensions:
            for m in ext.methods:
                out.append((m.name, m, src.rel))
    return out


def funnel_comment(sources):
    """(entry points, {exempted name: reason}, malformed ledger lines) from the
    comment above `func parse_comma_list`, or None when no file holds it."""
    for src in sources:
        lines = src.text.split("\n")
        for k, line in enumerate(lines):
            if not line.strip().startswith("func %s(" % FUNNEL):
                continue
            j = k - 1
            block = []
            while j >= 0 and lines[j].strip().startswith("//"):
                block.insert(0, lines[j].strip()[2:].strip())
                j -= 1
            entries, ledger, bad = set(), {}, []
            section = None
            for item in block:
                if item in (ENTRY_POINTS, LEDGER):
                    section = item
                elif section == ENTRY_POINTS and item:
                    entries.add(item)
                elif section == LEDGER and item:
                    m = _LEDGER_LINE.match(item)
                    if m:
                        ledger[m.group(1)] = m.group(2)
                    else:
                        bad.append(item)
            return entries, ledger, bad
    return None


def failures_of(sources):
    """(failure lines, comma loops found, callers of the funnel)."""
    decls = declarations(sources)
    comment = funnel_comment(sources)
    if comment is None:
        return ["comma-funnel: no `func %s` in the package" % FUNNEL], 0, 0
    entries, ledger, bad = comment
    out = ["comma-funnel: the %s line %r is not `name: reason`" % (LEDGER, b) for b in bad]
    taking = {name for name, d, _ in decls if name != FUNNEL and takes(d.body)}
    loops = {}
    callers = set()
    for name, d, rel in decls:
        if FUNNEL in called(d.body) and name != FUNNEL:
            callers.add(name)
        if name == FUNNEL:
            continue
        for n in subset_check.walk(d.body):
            if not isinstance(n, (A.WhileExpr, A.ForLoop)):
                continue
            direct = takes(n.body) or (isinstance(n, A.WhileExpr) and tests_comma(n.condition)
                                       and consumes(n.body))
            through = sorted(called(n.body) & taking)
            if direct or through:
                loops.setdefault(name, []).append((rel, getattr(n, "line", 0), through))
    for name in sorted(loops):
        if name in ledger:
            continue
        for rel, line, through in loops[name]:
            how = " through `%s`" % "`, `".join(through) if through else ""
            out.append("comma-funnel: %s:%d: `%s` takes a `,` in a loop%s outside `%s`; parse "
                       "the list through the funnel, or exempt it in the %s with its reason"
                       % (rel, line, name, how, FUNNEL, LEDGER))
    for name in sorted(set(ledger) - set(loops)):
        out.append("comma-funnel: the %s exempts `%s`, which holds no loop that takes a `,`"
                   % (LEDGER, name))
    for name in sorted(callers - entries):
        out.append("comma-funnel: `%s` calls `%s`, but the funnel's %s list does not name it"
                   % (name, FUNNEL, ENTRY_POINTS))
    for name in sorted(entries - callers):
        out.append("comma-funnel: the funnel's %s list names `%s`, which never calls `%s`"
                   % (ENTRY_POINTS, name, FUNNEL))
    return out, sum(len(v) for v in loops.values()), len(callers)


def load(paths):
    return [subset_check.SourceFile(p) for p in paths]


def package_paths():
    return sorted(glob.glob(os.path.join(PACKAGE, "*.saw")))


# Each injection: (label, anchor in parser.saw, replacement, a failure it must give).
INJECTIONS = [
    ("an ad hoc comma loop",
     "    // The parser of one element of `list`.\n",
     "    func probe_list(&var self) -> Bool {\n"
     "        while true {\n"
     "            if not self.parse_expr() {\n"
     "                return false\n"
     "            }\n"
     "            if self.kind() == TokenKind.Comma {\n"
     "                self.advance()\n"
     "            } else {\n"
     "                break\n"
     "            }\n"
     "        }\n"
     "        true\n"
     "    }\n\n"
     "    // The parser of one element of `list`.\n",
     "`probe_list` takes a `,` in a loop"),
    ("a stale ledger line",
     "    // COMMA LEDGER:\n",
     "    // COMMA LEDGER:\n    //     parse_if: an exemption with nothing to exempt\n",
     "exempts `parse_if`"),
    ("an entry point cut from the list",
     "    //     parse_capture_list\n",
     "",
     "`parse_capture_list` calls `parse_comma_list`"),
]


def injected_failures():
    """The lane fails on each injected copy of the parser."""
    out = []
    os.makedirs(WORK, exist_ok=True)
    with open(FUNNEL_FILE, encoding="utf-8") as fh:
        text = fh.read()
    others = [p for p in package_paths() if os.path.abspath(p) != os.path.abspath(FUNNEL_FILE)]
    for label, anchor, change, want in INJECTIONS:
        if anchor not in text:
            out.append("comma-funnel: the injection's anchor for %s is gone from parser.saw; "
                       "move it with the code" % label)
            continue
        path = os.path.join(WORK, "parser.saw")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(anchor, change, 1))
        got, _, _ = failures_of(load(others + [path]))
        if not any(want in g for g in got):
            out.append("comma-funnel: the parser with %s passes; the lane cannot see it" % label)
    return out


def run():
    """(failure lines, counts) for run.py."""
    failures, loops, callers = failures_of(load(package_paths()))
    failures += injected_failures()
    return failures, {"comma-funnel entry points": callers,
                      "comma-funnel exempt loops": loops,
                      "comma-funnel injections": len(INJECTIONS)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    if args.files:
        failures, loops, callers = failures_of(load([os.path.abspath(f) for f in args.files]))
        counts = {"comma-funnel entry points": callers, "comma-funnel exempt loops": loops}
    else:
        failures, counts = run()
    for f in failures:
        print("FAIL: " + f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("comma-funnel: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

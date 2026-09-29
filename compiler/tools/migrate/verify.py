"""Checks of a rewritten text against GRAMMAR.md's reference recognizer.

A rewritten file must parse with exactly one tree, and the `borrow` prefixes
alone must only wrap: with every `BorrowPlace` node erased, the text with just
its prefixes inserted has the original's tree (the prefix binds a postfix
expression, so an insertion at the wrong token regroups the tree around it).
"""
import os
import sys

import layout

GRAMMAR_TOOLS = os.path.join(layout.REPO, "compiler", "tests", "grammar")
if GRAMMAR_TOOLS not in sys.path:
    sys.path.insert(0, GRAMMAR_TOOLS)

import dump  # noqa: E402
import extract  # noqa: E402
import recognize  # noqa: E402

PREFIXES = ("borrow var ", "borrow ")
_GRAMMAR = []


def grammar():
    if not _GRAMMAR:
        sys.setrecursionlimit(max(sys.getrecursionlimit(), recognize.RECURSION_LIMIT))
        _GRAMMAR.append(recognize.Grammar(extract.extract()))
    return _GRAMMAR[0]


def tree(text):
    """(tree, None) for a text with exactly one tree, else (None, detail)."""
    g = grammar()
    checked = recognize.check(g, text, trees=True)
    if checked.verdict != "OK":
        return None, "%s: %s" % (checked.verdict, checked.detail)
    units = []
    for origin, parse in checked.parses:
        units.append(dump.Unit(parse, dump._segment_text(units, origin) if origin else text, origin))
    builder = dump.Builder(units, checked.docs)
    items = builder.tree(units[0], units[0].parse.derivations()[0],
                         [d for d in checked.docs if d.kind == "module"])
    return items, None


def verdict(text):
    return recognize.check(grammar(), text).verdict


def erase(item):
    """The tree with each `BorrowPlace` wrapper removed, and each statement
    kind a borrow target selects (`OptionalAssign.borrow-plain`) named as its
    plain twin."""
    if isinstance(item, str):
        return item
    if item[0].startswith("BorrowPlace") and len(item) == 2:
        return erase(item[1])
    return [item[0].replace(".borrow-", ".")] + [erase(c) for c in item[1:]]


def is_prefix(edit):
    return edit.start == edit.end and edit.text in PREFIXES


def check_prefixes(original, edits, apply):
    """None when the prefix insertions among `edits` only wrap, else why not."""
    prefixes = [e for e in edits if is_prefix(e)]
    if not prefixes:
        return None
    before, why = tree(original)
    if before is None:
        return "the original text has no single tree (%s)" % why
    after, why = tree(apply(original, prefixes))
    if after is None:
        return "the prefixed text has no single tree (%s)" % why
    if [erase(i) for i in after] != [erase(i) for i in before]:
        return "a `borrow` prefix regroups the tree around it"
    return None

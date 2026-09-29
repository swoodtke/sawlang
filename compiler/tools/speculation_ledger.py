#!/usr/bin/env python3
"""Every mutable field of the parser and its tree builder has a recorded rollback decision.

    python compiler/tools/speculation_ledger.py         check parser.saw and tree.saw
    python compiler/tools/speculation_ledger.py FILE    check another copy of one of them

A speculation (SL-424 U4c) parses ahead and may be undone by
`Parser.restore`, which undoes the tree built meanwhile through
`TreeBuilder.restore`. Each of the two structs keeps a SPECULATION LEDGER
comment above its `checkpoint`, listing each field with its decision, one per
line:

    field: restored
    field: restored by OTHER
    field: unchanged, because REASON
    field: kept, because REASON

`restored` means the struct's `restore` writes the field: its body names
`self.field`. `restored by OTHER` means the field is read only through OTHER,
itself a restored field. `unchanged, because` gives the reason no speculation
changes it, and `kept, because` the reason what a speculation writes there
stays true after it is undone, as a cache's entries do. A field whose type is a
struct of the same file may instead be decided field by field, as
`field.sub: DECISION` for every field `sub` of that struct, `restored` then
meaning that `restore` names `self.field.sub`. The lane fails on a field with
no line, a line naming no field, a restored field `restore` never names, and a
decision of any other shape; it proves itself on copies of each file with a
field added and with one field's restore cut out.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import subset_check  # noqa: E402

SRC = os.path.join(REPO, "compiler", "parse", "src")
PARSER = os.path.join(SRC, "parser.saw")
TREE = os.path.join(SRC, "tree.saw")
WORK = os.path.join(REPO, ".build", "speculation-ledger")
LEDGER = "SPECULATION LEDGER:"
RESTORE = "func restore("
_LINE = re.compile(r"^(\w+(?:\.\w+)?): (restored|restored by (\w+)|(?:unchanged|kept), "
                   r"because (.+))$")


class Target:
    """One struct whose fields a ledger decides, and the injections that prove
    the lane sees a gap in it: (label, anchor, replacement, wanted failure)."""

    def __init__(self, path, struct, injections):
        self.path = path
        self.struct = struct
        self.injections = injections


TARGETS = [
    Target(PARSER, "Parser", [
        ("a field added", "public struct Parser {\n",
         "public struct Parser {\n    private probe_field: Int\n", "field `probe_field`"),
        ("a restore cut out", "        self.lists = saved.lists\n", "",
         "`restore` never names `self.lists`"),
    ]),
    Target(TREE, "TreeBuilder", [
        ("a field added", "public struct TreeBuilder {\n",
         "public struct TreeBuilder {\n    private probe_field: Int\n", "field `probe_field`"),
        ("a field added to the tree it builds", "public struct AstTree {\n",
         "public struct AstTree {\n    public probe_field: Int\n", "field `tree.probe_field`"),
        ("a restore cut out", "        self.child_count = saved.children\n", "",
         "`restore` never names `self.child_count`"),
    ]),
]


def structs_of(src):
    """{struct name: [(field name, field type name)]} of a parsed file, or None."""
    if src.program is None:
        return None
    return {s.name: [(f.name, getattr(f.type, "struct_name", None)) for f in s.fields]
            for s in src.program.structs}


def ledger_of(text, struct):
    """[line text] of the ledger comment above `struct`'s `checkpoint`, or None.
    The ledger belongs to the first `checkpoint` after the struct's declaration."""
    lines = text.split("\n")
    head = None
    for k, line in enumerate(lines):
        if re.match(r"^(public )?struct %s\b" % re.escape(struct), line):
            head = k
            break
    if head is None:
        return None
    for k in range(head, len(lines)):
        if lines[k].strip() == "// " + LEDGER:
            out = []
            for entry in lines[k + 1:]:
                s = entry.strip()
                if not s.startswith("//") or not s[2:].strip():
                    break
                out.append(s[2:].strip())
            return out
    return None


def restore_body(text, struct):
    """The text of the first `restore` after `struct`'s declaration, from its
    head to the next method's."""
    m = re.search(r"^(public )?struct %s\b" % re.escape(struct), text, re.M)
    if m is None:
        return None
    at = text.find(RESTORE, m.end())
    if at < 0:
        return None
    end = re.search(r"\n    (public )?func ", text[at + len(RESTORE):])
    return text[at:at + len(RESTORE) + end.start()] if end else text[at:]


def failures_of(path, struct):
    src = subset_check.SourceFile(path)
    rel = os.path.relpath(path, REPO)
    structs = structs_of(src)
    if structs is None or struct not in structs:
        return ["speculation ledger %s: no `struct %s` parses there" % (rel, struct)]
    ledger = ledger_of(src.text, struct)
    if ledger is None:
        return ["speculation ledger %s: no `// %s` comment for `%s`" % (rel, LEDGER, struct)]
    body = restore_body(src.text, struct)
    if body is None:
        return ["speculation ledger %s: no `%s` method for `%s`" % (rel, RESTORE, struct)]
    out = []
    decisions = {}
    for entry in ledger:
        m = _LINE.match(entry)
        if not m:
            out.append("speculation ledger %s: %r is not `field: restored`, `field: restored "
                       "by OTHER`, `field: unchanged, because REASON` or `field: kept, because "
                       "REASON`" % (rel, entry))
            continue
        name = m.group(1)
        if name in decisions:
            out.append("speculation ledger %s: `%s` has two lines" % (rel, name))
        decisions[name] = m
    # The names a decision may carry: each field, or each field of a field
    # whose type is a struct of this file and which is decided field by field.
    wanted = []
    for name, type_name in structs[struct]:
        split = any(d.startswith(name + ".") for d in decisions)
        if split and type_name in structs:
            wanted += ["%s.%s" % (name, sub) for sub, _ in structs[type_name]]
            if name in decisions:
                out.append("speculation ledger %s: `%s` is decided both whole and field by "
                           "field" % (rel, name))
        else:
            wanted.append(name)
    for name in wanted:
        if name not in decisions:
            out.append("speculation ledger %s: field `%s` of `%s` has no decision; restore it "
                       "or say why no speculation changes it" % (rel, name, struct))
    for name, m in sorted(decisions.items()):
        if name not in wanted:
            out.append("speculation ledger %s: `%s` names no field of `%s`" % (rel, name, struct))
            continue
        restored = name if m.group(2) == "restored" else m.group(3)
        if restored is None:
            continue
        if restored != name and (restored not in decisions
                                 or decisions[restored].group(2) != "restored"):
            out.append("speculation ledger %s: `%s` is restored by `%s`, which is not itself "
                       "restored" % (rel, name, restored))
        elif not re.search(r"\bself\.%s\b" % re.escape(restored), body):
            out.append("speculation ledger %s: `%s` is restored, but `restore` never names "
                       "`self.%s`" % (rel, name, restored))
    return out


def injected_failures():
    """The lane fails on each file with a field added, and with one field's
    restore cut out."""
    out = []
    os.makedirs(WORK, exist_ok=True)
    for target in TARGETS:
        with open(target.path, encoding="utf-8") as fh:
            text = fh.read()
        for label, anchor, change, want in target.injections:
            if anchor not in text:
                out.append("speculation ledger: the injection's anchor for %s is gone from %s; "
                           "move it with the code"
                           % (label, os.path.relpath(target.path, REPO)))
                continue
            path = os.path.join(WORK, os.path.basename(target.path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace(anchor, change, 1))
            got = failures_of(path, target.struct)
            if not any(want in g for g in got):
                out.append("speculation ledger: `%s` with %s passes; the lane cannot see it"
                           % (target.struct, label))
    return out


def run():
    """(failure lines, counts) for run.py."""
    failures = []
    fields = 0
    for target in TARGETS:
        failures += failures_of(target.path, target.struct)
        structs = structs_of(subset_check.SourceFile(target.path)) or {}
        fields += len(structs.get(target.struct, []))
    failures += injected_failures()
    return failures, {"speculation ledger fields": fields,
                      "speculation ledger structs": len(TARGETS)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?")
    args = ap.parse_args(argv)
    if args.file:
        path = os.path.abspath(args.file)
        failures = []
        for target in TARGETS:
            if os.path.basename(target.path) == os.path.basename(path):
                failures += failures_of(path, target.struct)
        counts = {}
    else:
        failures, counts = run()
    for f in failures:
        print("FAIL: " + f)
    print("speculation ledger: %s" % ("FAIL (%d)" % len(failures) if failures else "ok"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

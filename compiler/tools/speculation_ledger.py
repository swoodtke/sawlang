#!/usr/bin/env python3
"""Every mutable field of the parser has a recorded rollback decision.

    python compiler/tools/speculation_ledger.py         check compiler/parse/src/parser.saw
    python compiler/tools/speculation_ledger.py FILE    check another copy of it

A speculation (SL-424 U4c) parses ahead and may be undone by
`Parser.restore`. The SPECULATION LEDGER comment above `Parser.checkpoint`
lists each field of `struct Parser` with its decision, one per line:

    field: restored
    field: restored by OTHER
    field: unchanged, because REASON
    field: kept, because REASON

`restored` means `restore` writes the field: its body names `self.field`.
`restored by OTHER` means the field is read only through OTHER, itself a
restored field. `unchanged, because` gives the reason no speculation changes
it, and `kept, because` the reason what a speculation writes there stays true
after it is undone, as a cache's entries do. The lane fails on a field with no
line, a line naming no field, a restored field `restore` never names, and a
decision of any other shape; it proves itself on copies of the parser with a
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

PARSER = os.path.join(REPO, "compiler", "parse", "src", "parser.saw")
WORK = os.path.join(REPO, ".build", "speculation-ledger")
STRUCT = "Parser"
LEDGER = "SPECULATION LEDGER:"
RESTORE = "func restore("
_LINE = re.compile(r"^(\w+): (restored|restored by (\w+)|(?:unchanged|kept), because (.+))$")


def fields_of(src):
    """The field names of `struct Parser`, in order, or None."""
    if src.program is None:
        return None
    for s in src.program.structs:
        if s.name == STRUCT:
            return [f.name for f in s.fields]
    return None


def ledger_of(text):
    """[(line text)] of the ledger comment, or None when there is none."""
    lines = text.split("\n")
    for k, line in enumerate(lines):
        if line.strip() == "// " + LEDGER:
            out = []
            for entry in lines[k + 1:]:
                s = entry.strip()
                if not s.startswith("//") or not s[2:].strip():
                    break
                out.append(s[2:].strip())
            return out
    return None


def restore_body(text):
    """The text of `restore`, from its head to the next method's."""
    at = text.find(RESTORE)
    if at < 0:
        return None
    end = re.search(r"\n    (public )?func ", text[at + len(RESTORE):])
    return text[at:at + len(RESTORE) + end.start()] if end else text[at:]


def failures_of(path):
    src = subset_check.SourceFile(path)
    rel = os.path.relpath(path, REPO)
    fields = fields_of(src)
    if fields is None:
        return ["speculation ledger %s: no `struct %s` parses there" % (rel, STRUCT)]
    ledger = ledger_of(src.text)
    if ledger is None:
        return ["speculation ledger %s: no `// %s` comment" % (rel, LEDGER)]
    body = restore_body(src.text)
    if body is None:
        return ["speculation ledger %s: no `%s` method" % (rel, RESTORE)]
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
    for name in fields:
        if name not in decisions:
            out.append("speculation ledger %s: field `%s` of `%s` has no decision; restore it "
                       "or say why no speculation changes it" % (rel, name, STRUCT))
    for name, m in sorted(decisions.items()):
        if name not in fields:
            out.append("speculation ledger %s: `%s` names no field of `%s`" % (rel, name, STRUCT))
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
    """The lane fails on the parser with a field added, and with one field's
    restore cut out."""
    with open(PARSER, encoding="utf-8") as fh:
        text = fh.read()
    out = []
    os.makedirs(WORK, exist_ok=True)
    head = "public struct %s {\n" % STRUCT
    cut = "        self.lists = saved.lists\n"
    for label, anchor, change, want in (
            ("a field added", head, head + "    private probe_field: Int\n",
             "field `probe_field`"),
            ("a restore cut out", cut, "", "`restore` never names `self.lists`")):
        if anchor not in text:
            out.append("speculation ledger: the injection's anchor for %s is gone from %s; move "
                       "it with the code" % (label, os.path.relpath(PARSER, REPO)))
            continue
        path = os.path.join(WORK, "parser.saw")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(anchor, change, 1))
        got = failures_of(path)
        if not any(want in g for g in got):
            out.append("speculation ledger: the parser with %s passes; the lane cannot see it"
                       % label)
    return out


def run():
    """(failure lines, counts) for run.py."""
    failures = failures_of(PARSER) + injected_failures()
    src = subset_check.SourceFile(PARSER)
    return failures, {"speculation ledger fields": len(fields_of(src) or [])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?")
    args = ap.parse_args(argv)
    if args.file:
        failures, counts = failures_of(os.path.abspath(args.file)), {}
    else:
        failures, counts = run()
    for f in failures:
        print("FAIL: " + f)
    print("speculation ledger: %s" % ("FAIL (%d)" % len(failures) if failures else "ok"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""LANGUAGE_SPEC's std module table, checked against resolve's prelude table.

    python compiler/tests/prelude_doc/check_prelude_doc.py

The spec's "The modules" table says, per std module, which principal names are
bare (the Prelude column) and which need `import std.X`. The compiler's own
answer is `res_declare_prelude` in compiler/resolve/src/prelude.saw: an
inclusion list of `p.prelude_name("Name", "module")`, so a name absent from it
is gated. Nothing else ties the two together, so a row can drift from the
behavior behind it without either side looking wrong.

The prelude is read straight from that source with a line parser, not from a
`sawc` dump: the table is a flat run of literal calls, no dump of it exists,
and the check then needs no built compiler. Calls under `if p.std_new` are
read and the `else` arm of one is skipped, since the new std is the one the
spec describes.

Disagreements it reports, each naming the name and the module:
  - a name a "yes" row lists that the prelude does not enter;
  - a name a gated row lists (or a prose cell does not name) that it enters;
  - a prelude name from a module a gated row describes, even when the row does
    not list that name;
  - a name entered from a module the row does not name.
A Prelude cell that is prose (`String` only, `Allocator`, `GlobalAllocator`)
names the bare names in backticks; every other principal name of the row is
read as gated.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPEC = os.path.join(REPO, "LANGUAGE_SPEC.md")
PRELUDE = os.path.join(REPO, "compiler", "resolve", "src", "prelude.saw")
FIXTURES = os.path.join(HERE, "fixtures")

_HEADER = re.compile(r"^\|\s*Module\s*\|\s*Principal names\s*\|\s*Prelude\s*\|")
_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
_MODULE = re.compile(r"`(std\.[a-z_]+(?:\.[a-z_]+)*)`")
_SPAN = re.compile(r"`([^`]+)`")
_HEAD = re.compile(r"^[A-Za-z_]\w*")
_CALL = re.compile(r'^\s*p\.prelude_name\("([^"]+)",\s*"([^"]+)"\)')
_IF_NEW = re.compile(r"^\s*if p\.std_new \{\s*$")
_IF_OLD = re.compile(r"^\s*if not p\.std_new \{\s*$")
_ELSE = re.compile(r"^\s*\} else \{\s*$")


def read_prelude(text):
    """{name: module} from the body of `res_declare_prelude`, under the new std."""
    entries = {}
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "func res_declare_prelude" in l), None)
    if start is None:
        return None
    # Each open `if p.std_new` block is (skip while true): [taken_in_this_arm].
    stack = []
    for line in lines[start + 1:]:
        if line.startswith("}"):
            break
        if _IF_NEW.match(line):
            stack.append(True)
        elif _IF_OLD.match(line):
            stack.append(False)
        elif _ELSE.match(line) and stack:
            stack[-1] = not stack[-1]
        elif line.strip() == "}" and stack:
            stack.pop()
        else:
            m = _CALL.match(line)
            if m and all(stack):
                entries[m.group(1)] = m.group(2)
    return entries


def read_table(text):
    """[(modules, names, cell)] from the spec's module table, or None."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if _HEADER.match(l)), None)
    if start is None:
        return None
    rows = []
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break
        if _SEPARATOR.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        modules = _MODULE.findall(cells[0])
        names = []
        for span in _SPAN.findall(cells[1]):
            m = _HEAD.match(span)
            if m:
                names.append(m.group(0))
        rows.append((modules, names, cells[2]))
    return rows


def check(spec_text, prelude_text):
    """(failure lines, counts)."""
    rows = read_table(spec_text)
    if not rows:
        return (["prelude_doc: no `| Module | Principal names | Prelude |` table "
                 "in the spec, so nothing can be checked"], {})
    prelude = read_prelude(prelude_text)
    if prelude is None:
        return (["prelude_doc: prelude.saw has no `res_declare_prelude`"], {})
    failures = []
    checked = 0
    for modules, names, cell in rows:
        label = " / ".join(modules)
        low = cell.lower()
        if low.startswith("yes"):
            bare, gated_row = set(names), False
        elif low.startswith("no"):
            bare, gated_row = set(), True
        else:
            bare = {_HEAD.match(s).group(0) for s in _SPAN.findall(cell)
                    if _HEAD.match(s)}
            gated_row = False
        for name in names:
            checked += 1
            home = prelude.get(name)
            if name in bare and home is None:
                failures.append("%s: the spec calls `%s` prelude, but resolve "
                                "gates it" % (label, name))
            elif name not in bare and home is not None:
                failures.append("%s: the spec gates `%s` (Prelude cell %r), but "
                                "resolve enters it from %s" % (label, name, cell, home))
            elif home is not None and home != "builtin" and home not in modules:
                failures.append("%s: resolve enters `%s` from %s, not a module "
                                "of the row" % (label, name, home))
        if not low.startswith("yes"):
            # A gated or partial row contributes exactly its bare names.
            for name in sorted(bare - set(names)):
                checked += 1
                home = prelude.get(name)
                if home is None:
                    failures.append("%s: the spec calls `%s` prelude, but resolve "
                                    "gates it" % (label, name))
                elif home not in modules:
                    failures.append("%s: resolve enters `%s` from %s, not a module "
                                    "of the row" % (label, name, home))
            for name, home in sorted(prelude.items()):
                if home in modules and name not in bare and name not in names:
                    failures.append("%s: the Prelude cell %r does not name `%s`, "
                                    "which resolve enters from %s"
                                    % (label, cell, name, home))
    return failures, {"prelude names checked": checked, "prelude entries": len(prelude)}


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run():
    """(failure lines, counts) for run.py: the spec against resolve, then each
    fixture directory, `agrees*` clean and `disagrees*` failing."""
    failures, counts = check(_read(SPEC), _read(PRELUDE))
    for case in sorted(glob.glob(os.path.join(FIXTURES, "*"))):
        name = os.path.basename(case)
        got, _ = check(_read(os.path.join(case, "spec.md")),
                       _read(os.path.join(case, "prelude.saw")))
        if name.startswith("agrees") and got:
            failures.append("prelude_doc fixture %s should agree, but: %s"
                            % (name, "; ".join(got)))
        elif name.startswith("disagrees"):
            want = _read(os.path.join(case, "expect.txt")).splitlines()
            for line in want:
                if line and not any(line in g for g in got):
                    failures.append("prelude_doc fixture %s: no disagreement "
                                    "contains %r" % (name, line))
            if len(got) != len([l for l in want if l]):
                failures.append("prelude_doc fixture %s: %d disagreement(s), "
                                "expected %d: %s" % (name, len(got),
                                len([l for l in want if l]), "; ".join(got)))
        elif not name.startswith(("agrees", "disagrees")):
            failures.append("prelude_doc fixture %s: name it agrees* or disagrees*" % name)
    counts["prelude_doc fixtures"] = len(glob.glob(os.path.join(FIXTURES, "*")))
    return failures, counts


if __name__ == "__main__":
    bad, stats = run()
    for line in bad:
        print("  - " + line)
    print(", ".join("%s %d" % kv for kv in stats.items()))
    sys.exit(1 if bad else 0)

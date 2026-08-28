#!/usr/bin/env python3
"""LANGUAGE_SPEC's module table is what the prelude gate promises, and this
checks that the compiler's list keeps the promise (design 188 unit 7).

The prelude is an ALLOWLIST: `IMPORT_REQUIRED_STD_MODULES` in `sawc.py` names
the std modules whose surface a program must import, and everything else is bare.
The spec documents the same partition, one row per module, in the "The modules"
table's Prelude column. Nothing tied the two together, so they drifted: the table
said `std.spinlock` was gated and the set did not list it, which made `SpinLock`
(and `SlabHead`, and the slab free functions) reachable with no import for as
long as anyone had been reading the spec to find out (DF-188i, audit row W01).

A drift like that is invisible from both ends. The compiler behaves consistently
— it is simply gating a different set than the one documented — and the document
is internally coherent. So this asserts the two agree:

  1. every module the table marks gated (`no` in the Prelude column) is in
     `IMPORT_REQUIRED_STD_MODULES`;
  2. every module in `IMPORT_REQUIRED_STD_MODULES` has a table row, and that row
     does not claim the module is bare.

The table is read as the source of truth for INTENT, and the set for behavior.
A row whose Prelude cell is neither a plain `yes`/`no` (`String only`,
`Allocator, GlobalAllocator` — the per-symbol carve-outs) is reported as
undecidable rather than guessed at, so a new carve-out has to be spelled out
here rather than silently skipped.

Run from the repo root:  ./.venv/bin/python tools/test_prelude_gate_doc.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

from sawc import IMPORT_REQUIRED_STD_MODULES  # noqa: E402

SPEC = os.path.join(REPO, "LANGUAGE_SPEC.md")

# The table's header, which is what locates it. Matched on the column names so a
# heading rename does not silently turn this test into a no-op.
_HEADER = re.compile(r"^\|\s*Module\s*\|\s*Principal names\s*\|\s*Prelude\s*\|")
_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
# A leaf may be DOTTED since design 218 unit 1 (`std.compiler.frame` is
# `sawc/std/compiler/frame.saw`), so the capture runs to the closing backtick.
_MODULE = re.compile(r"`std\.([a-z_]+(?:\.[a-z_]+)*)`")

# Prelude cells that are a plain answer for the WHOLE module. Anything else is a
# per-symbol carve-out and is listed below by hand, so adding one is a
# deliberate act.
_BARE = {"yes"}
_GATED = {"no"}
# Rows whose Prelude cell is prose because the module is split: the module is
# partly bare, so the whole-module gate must NOT list it.
_PARTIAL_ROWS = {
    "string",          # `String` only — `Utf8Error` is the carved-out symbol
    "alloc",           # `Allocator` / `GlobalAllocator` bare, `AllocError` not
    "numeric",         # methods on primitives; nothing to import
    "float",           # ditto, plus one `StringBuilder` overload: no top-level
                       # name to import, so the gate has nothing to hold
}


def read_table():
    """`{module leaf: prelude cell}` from the spec's module table."""
    rows = {}
    with open(SPEC, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if start is None:
        return None
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break
        if _SEPARATOR.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        leaves = _MODULE.findall(cells[0])
        for leaf in leaves:
            rows[leaf] = cells[-1]
    return rows


def main() -> int:
    rows = read_table()
    if not rows:
        print("LANGUAGE_SPEC.md: could not find the `| Module | Principal names "
              "| Prelude |` table — this test cannot check anything")
        return 1

    failures = []
    documented_gated = set()
    for leaf, cell in sorted(rows.items()):
        answer = cell.lower()
        if leaf in _PARTIAL_ROWS:
            continue
        if answer in _GATED:
            documented_gated.add(leaf)
        elif answer in _BARE:
            if leaf in IMPORT_REQUIRED_STD_MODULES:
                failures.append(
                    f"`std.{leaf}`: the spec's table says its names are in the "
                    f"prelude, but IMPORT_REQUIRED_STD_MODULES gates them")
        else:
            failures.append(
                f"`std.{leaf}`: Prelude cell is {cell!r}, which is neither "
                f"`yes` nor `no`. A per-symbol carve-out belongs in this test's "
                f"_PARTIAL_ROWS with a reason, so it is stated rather than "
                f"guessed")

    ungated = sorted(documented_gated - IMPORT_REQUIRED_STD_MODULES)
    if ungated:
        failures.append(
            "modules the spec documents as import-gated that "
            "IMPORT_REQUIRED_STD_MODULES does not list (their names resolve "
            "bare, and the spec says they do not):\n    "
            + "\n    ".join(f"std.{m}" for m in ungated))

    undocumented = sorted(
        m for m in IMPORT_REQUIRED_STD_MODULES if m not in rows)
    if undocumented:
        failures.append(
            "modules the compiler gates that the spec's table has no row for "
            "(a reader has no way to learn they need an import):\n    "
            + "\n    ".join(f"std.{m}" for m in undocumented))

    if failures:
        print("the prelude gate and LANGUAGE_SPEC's module table disagree:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1

    print(f"prelude gate: {len(documented_gated)} documented-gated module(s), "
          f"all present in IMPORT_REQUIRED_STD_MODULES "
          f"({len(IMPORT_REQUIRED_STD_MODULES)} entries, every one documented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

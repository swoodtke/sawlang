#!/usr/bin/env python3
"""runtime/ABI.md is the runtime ABI contract, and this checks that it says
so completely (design 149 unit c).

The compiler CHECKS an exported seam's signature against the document —
`runtime_table.abi_signatures()` parses the signatures straight out of ABI.md,
so the document is the contract rather than a description of one. That gives
the document a job it can fail at in two directions:

  1. a frozen symbol the document does not describe is a seam nobody can be
     checked against, so a wrong implementation of it links and misbehaves;
  2. a documented symbol outside the frozen set is a promise the compiler will
     not let anyone keep — `@export`ing it is refused as a reserved name.

Neither shows up in a build, so neither would be noticed. This asserts the two
sets are equal and that every parsed signature is well-formed. The frozen set
is `runtime_table.RUNTIME_SEAMS`, stated apart from the document so that this
check is not the document compared with itself.

Run from the repo root:  ./.venv/bin/python tools/test_runtime_abi_doc.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

from runtime_table import DEFAULTED_SEAMS  # noqa: E402
from runtime_table import RUNTIME_SEAMS  # noqa: E402
from runtime_table import abi_signatures  # noqa: E402

# The classes `abi_class` maps a documented type spelling onto. A spelling it
# does not recognize falls through as itself, which would silently never match a
# Saw signature — so an unrecognized one is a documentation bug, not a pass.
KNOWN_CLASSES = {"void", "noreturn", "word", "i64", "i32", "i16", "i8", "float"}


def defaulted_failures() -> list:
    """The "Weak defaults" section against the table's defaulted set, and
    that set against std's seams module: each defaulted seam has exactly one
    `@weak @export` there, and nothing else is exported from it."""
    failures = []
    with open(os.path.join(REPO, "runtime", "ABI.md")) as fh:
        text = fh.read()
    start = text.find("\n## Weak defaults")
    end = text.find("\n## ", start + 1)
    section = text[start:end] if start >= 0 else ""
    listed = set(re.findall(r"`(__saw_rt_[a-z0-9_]+)`", section))
    if start < 0:
        failures.append('runtime/ABI.md has no "Weak defaults" section')
    elif listed != set(DEFAULTED_SEAMS):
        failures.append("the \"Weak defaults\" section names %s where DEFAULTED_SEAMS holds %s"
                        % (sorted(listed), sorted(DEFAULTED_SEAMS)))
    for name in sorted(set(DEFAULTED_SEAMS) - set(RUNTIME_SEAMS)):
        failures.append("DEFAULTED_SEAMS names `%s`, which is not a runtime seam" % name)
    with open(os.path.join(REPO, "std", "builtins", "seams.saw")) as fh:
        lines = [line.strip() for line in fh]
    exported = []
    for k, line in enumerate(lines):
        m = re.match(r'@export\("([^"]+)"\)$', line)
        if m:
            exported.append((m.group(1), k > 0 and lines[k - 1] == "@weak"))
    for name in sorted(DEFAULTED_SEAMS):
        found = [weak for symbol, weak in exported if symbol == name]
        if len(found) != 1 or not found[0]:
            failures.append("std/builtins/seams.saw must hold exactly one `@weak @export(\"%s\")`" % name)
    for symbol, _ in exported:
        if symbol not in DEFAULTED_SEAMS:
            failures.append("std/builtins/seams.saw exports `%s`, which ABI.md does not mark defaulted" % symbol)
    return failures


def main() -> int:
    sigs = abi_signatures()
    failures = []

    undocumented = sorted(RUNTIME_SEAMS - set(sigs))
    if undocumented:
        failures.append(
            "frozen ABI symbols with no signature in runtime/ABI.md (nothing can be "
            "checked against them):\n  " + "\n  ".join(undocumented))

    unfrozen = sorted(set(sigs) - RUNTIME_SEAMS)
    if unfrozen:
        failures.append(
            "signatures in runtime/ABI.md for symbols outside RUNTIME_SEAMS "
            "(exporting one is refused as a reserved name):\n  "
            + "\n  ".join(unfrozen))

    for name in sorted(sigs):
        params, ret = sigs[name]
        bad = [c for c in (*params, ret) if c not in KNOWN_CLASSES]
        if bad:
            failures.append(
                f"{name}: unrecognized ABI type spelling(s) {bad} — "
                f"runtime_table.ABI_CLASSES does not map them, so no Saw "
                f"signature can ever match")
        if ret == "noreturn" and name != "__saw_rt_panic":
            failures.append(f"{name}: documented as noreturn; only panic is")

    failures += defaulted_failures()

    if failures:
        print("runtime/ABI.md is out of step with the frozen ABI set:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1

    print(f"runtime/ABI.md: {len(sigs)} seam signatures, matching the frozen set exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

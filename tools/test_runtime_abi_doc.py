#!/usr/bin/env python3
"""rt/ABI.md is the runtime ABI contract, and this checks that it says so
completely (design 149 unit c).

Since design 149 the compiler CHECKS an exported seam's signature against the
document — `runtime_abi.abi_signatures()` parses the signatures straight out of
ABI.md, so the document is the contract rather than a description of one. That
gives the document a job it can fail at in two directions:

  1. a frozen symbol the document does not describe is a seam nobody can be
     checked against, so a wrong implementation of it links and misbehaves;
  2. a documented symbol outside the frozen set is a promise the compiler will
     not let anyone keep — `@export`ing it is refused as a reserved name.

Neither shows up in a build, so neither would be noticed. This asserts the two
sets are equal and that every parsed signature is well-formed.

Run from the repo root:  ./.venv/bin/python tools/test_runtime_abi_doc.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))

from runtime_abi import RUNTIME_ABI_SYMBOLS, abi_signatures  # noqa: E402

# The classes `_abi_class` maps a documented type spelling onto. A spelling it
# does not recognize falls through as itself, which would silently never match a
# Saw signature — so an unrecognized one is a documentation bug, not a pass.
KNOWN_CLASSES = {"void", "noreturn", "word", "i64", "i32", "i16", "i8", "float"}


def main() -> int:
    sigs = abi_signatures()
    failures = []

    undocumented = sorted(RUNTIME_ABI_SYMBOLS - set(sigs))
    if undocumented:
        failures.append(
            "frozen ABI symbols with no signature in rt/ABI.md (nothing can be "
            "checked against them):\n  " + "\n  ".join(undocumented))

    unfrozen = sorted(set(sigs) - RUNTIME_ABI_SYMBOLS)
    if unfrozen:
        failures.append(
            "signatures in rt/ABI.md for symbols outside RUNTIME_ABI_SYMBOLS "
            "(exporting one is refused as a reserved name):\n  "
            + "\n  ".join(unfrozen))

    for name in sorted(sigs):
        params, ret = sigs[name]
        bad = [c for c in (*params, ret) if c not in KNOWN_CLASSES]
        if bad:
            failures.append(
                f"{name}: unrecognized ABI type spelling(s) {bad} — "
                f"runtime_abi._ABI_CLASSES does not map them, so no Saw "
                f"signature can ever match")
        if ret == "noreturn" and name != "__saw_rt_panic":
            failures.append(f"{name}: documented as noreturn; only panic is")

    if failures:
        print("rt/ABI.md is out of step with the frozen ABI set:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1

    print(f"rt/ABI.md: {len(sigs)} seam signatures, matching the frozen set exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

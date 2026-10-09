#!/usr/bin/env python3
"""How much of tests/corpus/ `sawc2 mir` lowers, for information; it gates
nothing.

    python compiler/tests/mir/corpus_info.py [-v]

Each corpus file is the entry of its own program. A record counts as lowered
when it has no ERROR and no INVARIANT line, as refused by the lowering when
it carries a lowering's `slice.not-yet`, and as refused earlier when only an
earlier stage refuses it (typecheck's own `slice.not-yet` included). INVARIANT lines are counted on their own; with `-v` each is
printed, with the lowering's refusals grouped by message.
"""
import glob
import os
import subprocess
import sys

import mir_lane

CORPUS = os.path.join(mir_lane.REPO, "tests", "corpus")
# The lowering's `slice.not-yet` messages, told apart from typecheck's.
LOWERING = "is not lowered to MIR"


def main():
    verbose = "-v" in sys.argv[1:]
    files = sorted(glob.glob(os.path.join(CORPUS, "*.saw")))
    listing = os.path.join(mir_lane.REPO, ".build", "mir_corpus_list.txt")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    with open(listing, "w") as fh:
        fh.write("".join(mir_lane.rel(p) + "\n" for p in files))
    r = subprocess.run([mir_lane.build.SAWC2, "mir", "--check", "@" + mir_lane.rel(listing)],
                       cwd=mir_lane.REPO, capture_output=True, text=True, timeout=3600)
    got = mir_lane.records(r.stdout)
    lowered = refused_here = refused_earlier = with_invariants = 0
    reasons = {}
    invariants = []
    for path in files:
        record = got.get(mir_lane.rel(path), "")
        errors = [l.split("\t") for l in record.split("\n") if l.startswith("ERROR\t")]
        found = [l for l in record.split("\n") if l.startswith("INVARIANT\t")]
        if found:
            with_invariants += 1
            invariants += [mir_lane.rel(path) + ": " + l for l in found]
        if not errors and not found:
            lowered += 1
        elif errors and any(e[1] == "slice.not-yet" and LOWERING in e[3] for e in errors):
            refused_here += 1
            message = [e[3] for e in errors if LOWERING in e[3]][0]
            reasons[message] = reasons.get(message, 0) + 1
        elif errors:
            refused_earlier += 1
    print("mir corpus: %d files: %d lowered, %d refused by the lowering, %d refused earlier, "
          "%d with an invariant" % (len(files), lowered, refused_here, refused_earlier,
                                    with_invariants))
    if verbose:
        for message, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print("  %4d  %s" % (n, message))
        for line in invariants:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

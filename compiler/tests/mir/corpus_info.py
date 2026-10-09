#!/usr/bin/env python3
"""How much of tests/corpus/ `sawc2 mir` lowers, for information; it gates
nothing.

    python compiler/tests/mir/corpus_info.py [-v]

Each corpus file is the entry of its own program. A record counts as lowered
when it has no ERROR and no INVARIANT line, as refused by the lowering when
it carries a lowering's `slice.not-yet`, and as refused earlier when only an
earlier stage refuses it (typecheck's own `slice.not-yet` included). The
driver prints a record once it is complete, so a process that dies leaves the
program it died in with no record: that one counts as a crash, and the
programs after it are lowered in a fresh process. A program
with no record at all is counted apart, never as lowered. INVARIANT lines are
counted on their own; with `-v` each is printed, with the lowering's refusals
grouped by message.
"""
import glob
import os
import subprocess
import sys

import mir_lane

CORPUS = os.path.join(mir_lane.REPO, "tests", "corpus")
# The lowering's `slice.not-yet` messages, told apart from typecheck's.
LOWERING = "is not lowered to MIR"


def lower_all(rels, listing):
    """({path: record}, [paths whose process crashed]) for the programs `rels`."""
    got = {}
    crashed = []
    pending = list(rels)
    while pending:
        with open(listing, "w") as fh:
            fh.write("".join(p + "\n" for p in pending))
        r = subprocess.run([mir_lane.build.SAWC2, "mir", "--check", "@" + mir_lane.rel(listing)],
                           cwd=mir_lane.REPO, capture_output=True, text=True, timeout=3600)
        records = mir_lane.records(r.stdout)
        if r.returncode in (0, 1):
            got.update(records)
            break
        # The driver prints a program's record only once it is complete, so
        # the one that crashed is the first with no record.
        dead = next(p for p in pending if p not in records)
        for path in pending[:pending.index(dead)]:
            got[path] = records[path]
        crashed.append(dead)
        pending = pending[pending.index(dead) + 1:]
    return got, crashed


def main():
    verbose = "-v" in sys.argv[1:]
    files = sorted(glob.glob(os.path.join(CORPUS, "*.saw")))
    rels = [mir_lane.rel(p) for p in files]
    listing = os.path.join(mir_lane.REPO, ".build", "mir_corpus_list.txt")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    got, crashed = lower_all(rels, listing)
    lowered = refused_here = refused_earlier = with_invariants = missing = 0
    reasons = {}
    invariants = []
    for rel in rels:
        if rel in crashed:
            continue
        if rel not in got:
            missing += 1
            continue
        record = got[rel]
        errors = [l.split("\t") for l in record.split("\n") if l.startswith("ERROR\t")]
        found = [l for l in record.split("\n") if l.startswith("INVARIANT\t")]
        if found:
            with_invariants += 1
            invariants += [rel + ": " + l for l in found]
        if not errors and not found:
            lowered += 1
        elif errors and any(e[1] == "slice.not-yet" and LOWERING in e[3] for e in errors):
            refused_here += 1
            message = [e[3] for e in errors if LOWERING in e[3]][0]
            reasons[message] = reasons.get(message, 0) + 1
        elif errors:
            refused_earlier += 1
    print("mir corpus: %d files: %d lowered, %d refused by the lowering, %d refused earlier, "
          "%d with an invariant, %d crashed, %d with no record"
          % (len(files), lowered, refused_here, refused_earlier, with_invariants, len(crashed),
             missing))
    for path in crashed:
        print("  crashed: " + path)
    if verbose:
        for message, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print("  %4d  %s" % (n, message))
        for line in invariants:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

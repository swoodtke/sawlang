#!/usr/bin/env python3
"""irdet_verdict — read irdet's `--jsonl` records and say whether the run passed.

Why a gate reads records instead of `$?` (design 221 Part D). Until DF-220b was
fixed, a suspending `main` never propagated its return value: irdet's own `main`
suspends on every path, so `./.build/irdetbin --all` ALWAYS exited 0, and the
battery's irdet lane — which trusted that status — had never been able to fail.
Design 220's terminal battery printed "969 file(s) VIOLATED THE REUSE INVARIANT"
three lines above `irdet: ok`.

The status works now. This still does not read it, and that is the point: a gate
should not depend on the bug it gates being fixed. `--jsonl` is the same
structured output `tools/irdet_remote.check_here` already trusts — one record per
file, `{"kind": "file", "path", "status", "detail"}`, `status` one of
`ok`/`skip`/`mismatch` (the three strings irdet's `Verdict.wire_name` documents
as ABI).

Three ways to fail, and the last two are what make this more than a rename:

  * any `mismatch` record — a real determinism finding;
  * NO `ok` record — every candidate skipped means nothing was verified, which
    is what an interpreter that cannot import llvmlite looks like;
  * fewer records than `--expect` — the run stopped early (a crash, a kill, a
    disk error mid-write), which no per-record read can see on its own.

Usage:
    tools/irdet_verdict.py <records.jsonl> [--expect N]
"""

import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--expect", type=int, default=None,
                    help="how many file records the run was planned to write")
    args = ap.parse_args()

    if not os.path.exists(args.records):
        print(f"irdet_verdict: {args.records} does not exist — the run wrote no "
              f"records at all, so nothing was checked")
        return 1

    counts = {"ok": 0, "skip": 0, "mismatch": 0}
    mismatched = []
    malformed = 0
    with open(args.records, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if record.get("kind") != "file":
                continue
            status = record.get("status", "")
            counts[status] = counts.get(status, 0) + 1
            if status == "mismatch":
                mismatched.append((record.get("path", "<no path>"),
                                   record.get("detail", "")))

    total = sum(counts.values())
    print(f"irdet_verdict: {total} record(s) — {counts['ok']} ok, "
          f"{counts['skip']} skipped, {counts['mismatch']} MISMATCH"
          + (f", {malformed} malformed" if malformed else ""))

    failed = False
    for path, detail in mismatched:
        print(f"  MISMATCH {path}  ({detail})")
        failed = True
    if counts["ok"] == 0:
        print("irdet_verdict: NOTHING WAS CHECKED — every candidate skipped, so "
              "this run verified nothing. Check that the interpreter running "
              "sawc can import llvmlite.")
        failed = True
    if args.expect is not None and total < args.expect:
        print(f"irdet_verdict: the run planned {args.expect} file(s) and wrote "
              f"{total} record(s) — it stopped early.")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

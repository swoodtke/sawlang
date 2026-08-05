#!/usr/bin/env python3
"""AST dump acceptance harness (design 126 R11).

The parser-stage twin of `tools/lexdiff.py`, and the acceptance oracle for the
coming Saw parser port. Until that port exists there is no second implementation
to diff against, so this harness pins the two properties the oracle itself must
have before it can judge anything:

  (a) COMPLETE -- every tracked `.saw` file dumps with no dispatcher fallback.
      A missing arm used to be invisible: the dump simply omitted the node (or
      printed `<unknown ...>` in the middle of a plausible-looking tree), so an
      incomplete oracle would have happily "matched" a port that dropped the
      same nodes. `sawc/ast_dump.py` records every miss; any `UNKNOWN` record
      here is a failure.

  (b) DETERMINISTIC -- dumping the same file twice, in fresh processes under
      differing PYTHONHASHSEED, is byte-identical. Python randomizes string
      hashing per process, so a single run cannot reveal a `set`-ordered dump.

When the Saw parser lands, this grows a third sweep -- run the port, diff its
dump against the Python one -- and the bar becomes zero mismatches over the
corpus, exactly as lexdiff has today.

Usage:
    python tools/astdiff.py [-v]
"""
import argparse
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMPER = os.path.join(REPO, "tools", "dump_ast.py")

# Not 0: that would DISABLE hash randomization and mask what (b) looks for.
SEEDS = ("1", "424242")


def tracked_saw_files() -> list:
    r = subprocess.run(["git", "ls-files", "*.saw"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("astdiff: `git ls-files` failed")
    files = [f for f in r.stdout.splitlines() if f.strip()]
    files.sort()
    return files


def dump_once(rel: str, seed: str):
    """(stdout_bytes, status, stderr_bytes) from a fresh dumper process.

    `status` is "ok", "parse-error" or "crash". Distinguishing the last two
    matters and is not free: an uncaught exception in the dumper also exits 1,
    so an exit code alone would silently report a CRASHED file as a deliberate
    parse-error file -- which is exactly how a dumper bug first hid here. A real
    error dump is a single ERROR record on stdout; a crash prints a traceback to
    stderr and produces no records.
    """
    env = dict(os.environ, PYTHONHASHSEED=seed)
    p = subprocess.run([sys.executable, DUMPER, rel], cwd=REPO, env=env,
                       capture_output=True)
    if p.returncode == 0:
        return p.stdout, "ok", p.stderr
    if p.returncode == 1 and p.stdout.startswith(b"ERROR\t"):
        return p.stdout, "parse-error", p.stderr
    return p.stdout, "crash", p.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    files = tracked_saw_files()
    t0 = time.time()
    incomplete, unstable, crashed = [], [], []
    n_error_files = 0

    for rel in files:
        first, status, err = dump_once(rel, SEEDS[0])
        if status == "crash":
            tail = err.decode("utf-8", "replace").strip().split("\n")[-1]
            crashed.append((rel, tail))
            continue
        if status == "parse-error":
            n_error_files += 1
        if b"\nUNKNOWN\t" in first or first.startswith(b"UNKNOWN\t"):
            misses = sorted({ln.split(b"\t", 1)[1].decode("utf-8", "replace")
                             for ln in first.split(b"\n")
                             if ln.startswith(b"UNKNOWN\t")})
            incomplete.append((rel, misses))
        second, _, _ = dump_once(rel, SEEDS[1])
        if first != second:
            unstable.append(rel)

    dt = time.time() - t0
    print("astdiff: swept %d tracked .saw files (%d rejected by the parser, "
          "%.1fs)" % (len(files), n_error_files, dt))

    if crashed:
        print("astdiff: %d file(s) CRASHED the dumper" % len(crashed))
        for rel, tail in crashed[:20]:
            print("  - %s\n      %s" % (rel, tail))
    if incomplete:
        allmisses = sorted({m for _, ms in incomplete for m in ms})
        print("astdiff: %d file(s) hit a dispatcher fallback; %d distinct node "
              "type(s) uncovered:" % (len(incomplete), len(allmisses)))
        for m in allmisses:
            print("  - %s" % m)
        if args.verbose:
            for rel, ms in incomplete[:20]:
                print("    %s  %s" % (rel, ", ".join(ms)))
    if unstable:
        print("astdiff: %d file(s) dumped differently across runs" % len(unstable))
        for rel in unstable[:20]:
            print("  - %s" % rel)

    if crashed or incomplete or unstable:
        return 1
    print("astdiff: OK -- every file dumps completely and identically twice")
    return 0


if __name__ == "__main__":
    sys.exit(main())

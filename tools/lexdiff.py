#!/usr/bin/env python3
"""Differential lexer harness (design 116).

Sweeps every tracked `.saw` file in the repo through BOTH lexers and diffs their
canonical token dumps:

  * the sawc Python lexer, via `tools/dump_tokens.py` (in-process, for speed);
  * the Saw port `selfhost/lexer` (`sawlex`), via the compiled binary.

Token records must match byte-for-byte. ERROR records (files the Python lexer
rejects) are compared on the tag + position only — message prose is not required
to match (design 116 bar). ZERO mismatches over the whole corpus is the
acceptance bar.

Usage:
    python tools/lexdiff.py [--saw-bin PATH] [--no-build] [-v]

By default the Saw lexer is compiled to `.build/sawlex` first (delete it or pass
a fresh --saw-bin to force a rebuild). `make lexdiff` wires this up.
"""
import argparse
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dump_tokens  # noqa: E402


def build_saw_lexer(out_path: str) -> None:
    sawc = os.path.join(REPO, "sawc", "sawc.py")
    main_saw = os.path.join(REPO, "selfhost", "lexer", "src", "main.saw")
    print("Building the Saw lexer -> %s" % out_path)
    r = subprocess.run([sys.executable, sawc, main_saw, "-o", out_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("lexdiff: failed to build the Saw lexer")


def tracked_saw_files() -> list:
    r = subprocess.run(["git", "ls-files", "*.saw"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("lexdiff: `git ls-files` failed")
    files = [f for f in r.stdout.splitlines() if f.strip()]
    files.sort()
    return files


def python_dump(path: str):
    """(records, is_error) from the Python lexer, in-process."""
    records, code = dump_tokens.dump(path)
    return records, code != 0


def saw_dump(saw_bin: str, path: str):
    r = subprocess.run([saw_bin, path], capture_output=True)
    out = r.stdout
    records = out.split(b"\n")
    if records and records[-1] == b"":
        records.pop()
    return records, r.returncode != 0


def records_match(py_recs, saw_recs) -> bool:
    """Token lines must be byte-identical; ERROR lines compare tag+position."""
    if len(py_recs) != len(saw_recs):
        return False
    for a, b in zip(py_recs, saw_recs):
        if a.startswith(b"ERROR\t") and b.startswith(b"ERROR\t"):
            # Compare "ERROR" + "line:col"; message prose is not required to match.
            if a.split(b"\t")[:2] != b.split(b"\t")[:2]:
                return False
        elif a != b:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saw-bin", default=os.path.join(REPO, ".build", "sawlex"))
    ap.add_argument("--no-build", action="store_true",
                    help="use an existing --saw-bin without rebuilding")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not args.no_build:
        os.makedirs(os.path.join(REPO, ".build"), exist_ok=True)
        build_saw_lexer(args.saw_bin)
    if not os.path.exists(args.saw_bin):
        sys.exit("lexdiff: Saw lexer binary not found: %s" % args.saw_bin)

    files = tracked_saw_files()
    mismatches = []
    n_error_files = 0
    t0 = time.time()
    for rel in files:
        path = os.path.join(REPO, rel)
        py_recs, py_err = python_dump(path)
        saw_recs, saw_err = saw_dump(args.saw_bin, path)
        if py_err:
            n_error_files += 1
        if not records_match(py_recs, saw_recs):
            mismatches.append((rel, py_recs, saw_recs, py_err, saw_err))
            if args.verbose:
                print("MISMATCH: %s" % rel)
                _show_first_diff(py_recs, saw_recs)
    dt = time.time() - t0

    print("lexdiff: swept %d tracked .saw files (%d rejected by the Python lexer)"
          % (len(files), n_error_files))
    print("lexdiff: %d mismatch(es), %.1fs" % (len(mismatches), dt))
    if mismatches:
        for rel, py_recs, saw_recs, py_err, saw_err in mismatches[:20]:
            print("  - %s  (py_err=%s saw_err=%s, %d vs %d records)"
                  % (rel, py_err, saw_err, len(py_recs), len(saw_recs)))
        sys.exit(1)
    print("lexdiff: OK — zero mismatches over the corpus")


def _show_first_diff(py_recs, saw_recs):
    for i in range(max(len(py_recs), len(saw_recs))):
        a = py_recs[i] if i < len(py_recs) else b"<none>"
        b = saw_recs[i] if i < len(saw_recs) else b"<none>"
        if a != b:
            print("    line %d:" % (i + 1))
            print("      py : %r" % a)
            print("      saw: %r" % b)
            return


if __name__ == "__main__":
    main()

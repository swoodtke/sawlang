#!/usr/bin/env python3
"""Compiler output determinism harness (design 126 R2).

Compiling one unchanged source twice must produce byte-identical LLVM IR. That
was NOT true before design 126: two `set`-of-`str` iterations reached emission
order (the codegen type topological sort, and closure-environment field order),
and two generated names were derived from `id()` -- a memory address. Since
Python randomizes string hashing per process, a single run always looked
self-consistent and the defect was invisible without a cross-run comparison.

Each sampled source is compiled twice, in fresh processes, under DIFFERENT
`PYTHONHASHSEED` values, and the emitted `.ll` files are compared as bytes.
Any difference is a determinism bug. Zero is the acceptance bar.

Usage:
    python tools/irdet.py [-n COUNT] [--all] [-v]

`make irdet` wires this up. Sampling is deterministic (fixed seed), so a failure
reproduces; `--all` sweeps every compilable tracked example.
"""
import argparse
import os
import random
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc", "sawc.py")

# Two seeds that produce different str hashing. 0 would DISABLE randomization,
# which would mask exactly the class of bug this harness exists to catch.
SEEDS = ("1", "424242")


def tracked_examples() -> list:
    r = subprocess.run(["git", "ls-files", "examples/*.saw"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("irdet: `git ls-files` failed")
    files = [f for f in r.stdout.splitlines() if f.strip()]
    files.sort()
    return files


def is_negative_test(rel: str) -> bool:
    """Error / skip examples never reach codegen, so they have no IR to compare.

    Same rule the suite uses (`test_runner.py` reads these directives), rather
    than a path or filename convention -- error tests live both in
    `examples/errors/` and scattered through `examples/`.
    """
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return True
    return "// EXPECT: error" in head or "// EXPECT: skip" in head


def emit_ir(rel: str, seed: str):
    """Compile `rel` to IR in a fresh process; return the bytes, or None if the
    file does not build standalone (module-path deps, host-only, ...)."""
    stem = os.path.splitext(os.path.basename(rel))[0]
    out_ll = os.path.join(REPO, ".build", stem + ".ll")
    if os.path.exists(out_ll):
        os.remove(out_ll)
    env = dict(os.environ, PYTHONHASHSEED=seed)
    p = subprocess.run([sys.executable, SAWC, rel, "--emit-ir"],
                       cwd=REPO, env=env, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(out_ll):
        return None
    with open(out_ll, "rb") as fh:
        blob = fh.read()
    os.remove(out_ll)
    return blob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=40,
                    help="how many examples to sample (default 40)")
    ap.add_argument("--all", action="store_true",
                    help="sweep every compilable example instead of sampling")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    files = [f for f in tracked_examples() if not is_negative_test(f)]
    if args.all:
        sample = files
    else:
        random.seed(20260804)          # fixed: a failure must reproduce
        sample = sorted(random.sample(files, min(args.count, len(files))))

    t0 = time.time()
    mismatches, skipped, checked = [], 0, 0
    for rel in sample:
        blobs = [emit_ir(rel, s) for s in SEEDS]
        if any(b is None for b in blobs):
            skipped += 1
            if args.verbose:
                print("  skip (does not build standalone): %s" % rel)
            continue
        checked += 1
        if blobs[0] != blobs[1]:
            mismatches.append(rel)
            print("  MISMATCH: %s (%d vs %d bytes)"
                  % (rel, len(blobs[0]), len(blobs[1])))

    dt = time.time() - t0
    print("irdet: compiled %d example(s) twice under differing PYTHONHASHSEED "
          "(%d skipped, %.1fs)" % (checked, skipped, dt))
    if mismatches:
        print("irdet: %d file(s) produced NON-REPRODUCIBLE IR" % len(mismatches))
        return 1
    if checked == 0:
        # A compile failure counts as a skip, so an interpreter without llvmlite
        # skips the entire corpus and this used to print OK — a final gate
        # reporting success having verified nothing. `make irdet` runs bare
        # `python3`; run `.venv/bin/python tools/irdet.py` instead.
        print("irdet: NOTHING WAS CHECKED -- every candidate failed to compile.")
        print("irdet: run it under the virtualenv interpreter "
              "(.venv/bin/python tools/irdet.py%s)"
              % (" --all" if args.all else ""))
        return 1
    print("irdet: OK -- every sampled example compiled to byte-identical IR")
    return 0


if __name__ == "__main__":
    sys.exit(main())

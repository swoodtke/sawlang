#!/usr/bin/env python3
"""Ownership gate under Guard Malloc (design 159 unit 4).

A missing retain is INVISIBLE to an ordinary run. The surplus release lands in
a block libmalloc has already freed but not unmapped, so the program reads
correct values and exits 0 — until some later, unrelated allocation trips over
the damage. That is why DF-151b sat in the tree from design 73 (a by-value
argument) and design 147 (a local copy) with a green suite the whole time: at a
~15-35% per-run crash rate a single suite pass clears easily, and the two tests
that should have caught it were passing for the wrong reason.

Guard Malloc (`/usr/lib/libgmalloc.dylib`) puts each allocation on its own page
and UNMAPS it on free, so a release of a freed block faults AT the offending
instruction instead of corrupting a neighbour. Every program below went from
100% crash to 100% clean across the design 159 fix.

This lane is deliberately SMALL. Guard Malloc costs a page per allocation and
runs the whole suite far too slowly to gate on; what it needs to cover is the
ownership oracles, where a latent over-release is the failure mode that no
other check can see. Add a program here when it exists to prove something about
copies, retains, drops or refcounts.

Usage:
    python tools/gmgate.py [-n RUNS] [-v]

`make gmgate` wires this up. macOS only — Guard Malloc is a macOS facility, so
elsewhere this reports SKIPPED rather than failing (see TESTING.md).
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc", "sawc.py")
GMALLOC = "/usr/lib/libgmalloc.dylib"
OUT_DIR = os.path.join(REPO, ".build", "gmgate")

# The curated lane. Each entry is an example that asserts something about
# ownership; the comment says which shape it pins.
GATE = [
    # The undeclared ImplicitCopy tier across every transfer class (design 159).
    "examples/df151b_implicit_tier_transfers.saw",
    # A closure env retained through struct copies (design 73). This one is the
    # reason the lane exists: its own `strong_count` assertions read correct
    # while the env was released three times, so Guard Malloc is the ONLY thing
    # that can police it.
    "examples/closure_copyable_struct_copied.saw",
    # An ImplicitCopy value copied out of a place, then the place overwritten
    # (design 147 unit B / DF-139a).
    "examples/df139a_copy_then_overwrite.saw",
    # A closure env's retains and releases counted against an Arc (design 73).
    "examples/closure_deinit_arc_balance.saw",
    "examples/closure_borrow_lend_balance.saw",
    # Container-slot read-out: an owning value copied OUT of a container the
    # container still owns — the `v[i]` / `m[k]` duplication rule.
    "examples/closure_vector_copy_get.saw",
    "examples/map_string_owning_value_balance.saw",
    "examples/set_algebra_owning_balance.saw",
    "examples/generic_for_loop_owning_balance.saw",
    # Implicit copies at a call argument, nested in a struct, and splatted into
    # a repeat literal.
    "examples/implicit_copy_call_arg.saw",
    "examples/implicit_copy_nested.saw",
    "examples/repeat_literal_implicit_copy.saw",
    # A refcounted value copied into an OPT-ENCODED destination, at all six
    # transfer sites (DF-151c). Its Arc counts prove the retains happen; only
    # Guard Malloc proves no surplus release does, since an over-release reads
    # correct until the freed block is reused.
    "examples/df151c_optional_dest_copy.saw",
    # A match scrutinee that no binding holds (DF-151d). A leak here inverts to
    # an over-release under a fix that drops one time too many — an escaping arm
    # binding is an alias into the very value being released — so the counts and
    # this lane police opposite failures of the same change.
    "examples/df151d_match_temporary_scrutinee.saw",
    # Optional ELEMENTS of a fixed array (DF-151e): the retain is driven by the
    # payload's type and the wrap follows it, at construction and at a write.
    "examples/df151e_optional_element_array.saw",
    # TUPLE drop glue (DF-151f). The leak and the over-release are one change:
    # elements now drop at scope exit AND a whole-tuple copy now retains them,
    # so getting either half wrong inverts this program's failure. The counts
    # catch a missing retain; only Guard Malloc catches a surplus release.
    "examples/df151f_tuple_drop_glue.saw",
    # An assignment RHS reading out of storage the source keeps (DF-151h). The
    # exact DF-151b shape one statement kind over: `a = h.r` read correct and
    # freed twice, so the surplus release is invisible without Guard Malloc.
    "examples/df151h_assign_rhs_retain.saw",
]


def build(rel: str, verbose: bool):
    """Compile one gate program. Returns its binary path, or None if absent."""
    src = os.path.join(REPO, rel)
    if not os.path.exists(src):
        return None
    stem = os.path.splitext(os.path.basename(rel))[0]
    out = os.path.join(OUT_DIR, stem)
    os.makedirs(OUT_DIR, exist_ok=True)
    r = subprocess.run([sys.executable, SAWC, src, "-o", out],
                       capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        if verbose:
            sys.stderr.write(r.stdout + r.stderr)
        return False
    return out


def run_under_gmalloc(binary: str, runs: int):
    """Run `binary` `runs` times under Guard Malloc; return the failure list."""
    env = dict(os.environ)
    env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    # Guard the page BEFORE the allocation too, so an underflowing write faults
    # as readily as an overflowing one.
    env["MALLOC_PROTECT_BEFORE"] = "1"
    failures = []
    for i in range(runs):
        r = subprocess.run([binary], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            failures.append((i, r.returncode))
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--runs", type=int, default=10,
                    help="runs per program under Guard Malloc (default 10)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if sys.platform != "darwin" or not os.path.exists(GMALLOC):
        print("gmgate: SKIPPED — Guard Malloc is a macOS facility "
              f"({GMALLOC} not present)")
        return 0

    failed, checked, missing = [], 0, []
    for rel in GATE:
        binary = build(rel, args.verbose)
        if binary is None:
            missing.append(rel)
            continue
        if binary is False:
            print(f"  [1;31mBUILD FAIL[0m {rel}")
            failed.append(rel)
            continue
        failures = run_under_gmalloc(binary, args.runs)
        checked += 1
        if failures:
            codes = ", ".join(f"run {i} rc={rc}" for i, rc in failures[:5])
            print(f"  FAIL {rel}: {len(failures)}/{args.runs} crashed ({codes})")
            failed.append(rel)
        elif args.verbose:
            print(f"  ok   {rel}: {args.runs}/{args.runs} clean")

    for rel in missing:
        print(f"  note: {rel} is not in the tree — gate entry skipped")

    print(f"gmgate: {checked} program(s) x {args.runs} runs under Guard Malloc, "
          f"{len(failed)} failing")
    if failed:
        print("\nA failure here is an OVER-RELEASE or a use-after-free, not a "
              "flake:\nGuard Malloc unmaps freed blocks, so the fault lands at "
              "the instruction\nthat touched one. Re-run the named program "
              "directly to see it:\n"
              f"  DYLD_INSERT_LIBRARIES={GMALLOC} .build/gmgate/<name>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

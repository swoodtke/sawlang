#!/usr/bin/env python3
"""Print the Saw runtime's object files that a hosted sawc2 build links.

    python compiler/tools/runtime_objects.py [--target TRIPLE] [--manifest]

sawc2 links Stage 0's prebuilt runtime (SL:architecture §3.11): the same
`.build/rt/<key>/` objects a Stage 0 build of a hosted program links, built
and cached by Stage 0's `sawc/rt_build.py`, under its lock, on first use.
With no `--target` the triple is the one Stage 0 builds for by default,
llvmlite's host triple, so the cache a Stage 0 build already filled is the one
returned. One path per line; exit 1 when the runtime fails to build.

With `--manifest` it prints the runtime manifest `sawc2 build` reads instead:
a `target TRIPLE` line naming the sawc2 target the objects are built for, then
an `object PATH` line for each (compiler/tests/run/README.md).
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "sawc"))

# Each sawc2 target, by the prefix and suffix of the LLVM triples it stands for.
SAWC2_TARGETS = (
    ("arm64-apple-", "", "arm64-apple-darwin"),
    ("aarch64-apple-", "", "arm64-apple-darwin"),
    ("x86_64-", "-linux-gnu", "x86_64-unknown-linux-gnu"),
)


def sawc2_target(triple):
    """The sawc2 target the LLVM `triple` is, or None."""
    for prefix, suffix, target in SAWC2_TARGETS:
        if triple.startswith(prefix) and triple.endswith(suffix):
            return target
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", help="the triple to build the runtime for")
    ap.add_argument("--manifest", action="store_true", help="print the runtime manifest sawc2 build reads")
    args = ap.parse_args()
    from rt_build import RuntimeBuildError, build_runtime  # noqa: E402
    triple = args.target
    if not triple:
        from llvmlite import binding  # noqa: E402
        triple = binding.get_default_triple()
    try:
        objects = build_runtime(triple)
    except RuntimeBuildError as e:
        print("runtime_objects: the Saw runtime failed to build:\n%s" % e, file=sys.stderr)
        return 1
    if args.manifest:
        target = sawc2_target(triple)
        if target is None:
            print("runtime_objects: %s is not a target sawc2 builds for" % triple, file=sys.stderr)
            return 1
        print("target %s" % target)
        for path in objects:
            print("object %s" % path)
        return 0
    for path in objects:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

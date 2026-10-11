#!/usr/bin/env python3
"""Print the Saw runtime's object files that a hosted sawc2 build links.

    python compiler/tools/runtime_objects.py [--target TRIPLE]

sawc2 links Stage 0's prebuilt runtime (SL:architecture §3.11): the same
`.build/rt/<key>/` objects a Stage 0 build of a hosted program links, built
and cached by Stage 0's `sawc/rt_build.py`, under its lock, on first use.
With no `--target` the triple is the one Stage 0 builds for by default,
llvmlite's host triple, so the cache a Stage 0 build already filled is the one
returned. One path per line; exit 1 when the runtime fails to build.
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "sawc"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", help="the triple to build the runtime for")
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
    for path in objects:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

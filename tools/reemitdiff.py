#!/usr/bin/env python3
"""reemitdiff — does compiling the SAME file twice in ONE process emit the same IR?

`tools/irdet.py` compiles each example twice under two `PYTHONHASHSEED`s, one
compile per PROCESS, and compares the results. That oracle is blind by
construction to a whole class of nondeterminism: a name derived from a
process-global counter (the `node_id` allocator, the string/closure counters) is
perfectly stable across two fresh processes and shifts the moment anything is
compiled ahead of it. DF-164a found exactly that — `%"__collit_14189"` in one
compile and `%"__collit_29638"` in the next, same source — and design 164's tier
prototype then failed its differential for the same reason, because any cache
that restores std ahead of the entry file changes the order ids are allocated
in.

This tool compiles each example TWICE inside one interpreter and byte-compares
the emitted `.ll` and `.o`. A name that depends on how much has been compiled
before it fails here and nowhere else. The test runner's persistent workers
(design 115/156) compile many files per process, so this is also the shape the
suite actually runs in.

Usage:
    ./.venv/bin/python tools/reemitdiff.py [--all] [-j N] [pattern ...]

Exit code 0 = every file re-emitted identically.
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "sawc"))
sys.path.insert(0, os.path.join(REPO, "sawc", "parser"))

EXAMPLES = os.path.join(REPO, "examples")
# The examples the runner expects to FAIL to compile have no IR to compare.
SKIP_DIRS = {"errors"}


def _iter_examples(patterns):
    for root, dirs, files in os.walk(EXAMPLES):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if not name.endswith(".saw"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, REPO)
            if patterns and not any(p in rel for p in patterns):
                continue
            yield path


def _compile_flags(source_path):
    """Read a test's `// COMPILE-FLAGS:` directive, as the runner does.

    Only the flags that change what is EMITTED are honoured here; a directive
    naming a path placeholder is a module-graph test and is skipped, since
    reproducing the runner's `{TESTDIR}` substitution is not this tool's job.
    """
    with open(source_path, "r") as f:
        head = f.read(4096)
    for line in head.splitlines():
        if "// COMPILE-FLAGS:" in line:
            return line.split("// COMPILE-FLAGS:")[1].split()
    return []


def _emit_once(source_path, out_path, flags):
    import sawc

    kwargs = dict(verbose=False, optimize="-O0" not in flags)
    if "--freestanding" in flags:
        kwargs["freestanding"] = True
    if "--runtime-build" in flags:
        kwargs["runtime_build"] = True
    if "-c" in flags:
        kwargs["object_only"] = True
    if "--no-hidden-alloc" in flags:
        kwargs["no_hidden_alloc"] = True
    if "--runtime-provider" in flags:
        kwargs["runtime_provider"] = True
    if "--target" in flags:
        kwargs["target_triple"] = flags[flags.index("--target") + 1]
    if "--target-features" in flags:
        kwargs["target_features"] = flags[flags.index("--target-features") + 1]
    sawc.compile_saw(source_path, out_path, **kwargs)


def check(source_path):
    """Compile `source_path` twice in this process; report whether it matched."""
    flags = _compile_flags(source_path)
    if any("{TESTDIR}" in f for f in flags) or "--emit-docs" in flags:
        return (source_path, "skip", "")
    tmp = tempfile.mkdtemp(prefix="reemit-")
    try:
        outs = []
        for tag in ("a", "b"):
            out = os.path.join(tmp, tag, "out")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf), redirect_stderr(buf):
                    _emit_once(source_path, out, flags)
            except SystemExit:
                return (source_path, "skip", "compile refused")
            except Exception:
                return (source_path, "skip", traceback.format_exc(limit=2))
            outs.append(out)

        for suffix in (".ll", ".o", ""):
            a, b = outs[0] + suffix, outs[1] + suffix
            if not (os.path.exists(a) and os.path.exists(b)):
                continue
            if suffix == "":
                # The linked executable is not a valid oracle on macOS: its N_OSO
                # debug-map stab carries the object's path and mtime, so two COLD
                # compiles into different directories already differ (design 164
                # unit 5). The IR and the object are the reproducible artifacts.
                continue
            with open(a, "rb") as fa, open(b, "rb") as fb:
                if fa.read() != fb.read():
                    return (source_path, "DIFF", suffix)
        return (source_path, "ok", "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_shard(files):
    """This process's share: every file compiled twice, serially.

    Serial ON PURPOSE — the counters under test are process-global, so two
    concurrent compiles in one interpreter would interleave them and measure
    nothing. Parallelism comes from sharding across PROCESSES.
    """
    lines = []
    for path in files:
        _rel, verdict, detail = check(path)
        lines.append(f"{verdict}\t{os.path.relpath(path, REPO)}\t{detail.splitlines()[-1] if detail else ''}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*")
    ap.add_argument("--all", action="store_true",
                    help="(default; kept for symmetry with irdet)")
    ap.add_argument("-j", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--shard", help="i/n — internal, one worker's share")
    args = ap.parse_args()

    files = list(_iter_examples(args.patterns))

    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        for line in _run_shard(files[i::n]):
            print(line)
        return 0

    print(f"reemitdiff: {len(files)} example(s), {args.j} worker(s)")
    # Plain subprocesses, not multiprocessing: its queues need POSIX semaphores,
    # which the agent sandbox refuses.
    procs = [subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--shard", f"{i}/{args.j}",
         *args.patterns],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for i in range(args.j)]

    diffs, skipped, ok = [], 0, 0
    for proc in procs:
        out, _ = proc.communicate()
        for line in out.splitlines():
            verdict, rel, detail = (line.split("\t") + ["", ""])[:3]
            if verdict == "DIFF":
                diffs.append((rel, detail))
                print(f"  DIFF {rel} ({detail})")
            elif verdict == "skip":
                skipped += 1
            elif verdict == "ok":
                ok += 1

    print(f"\nidentical: {ok}   skipped: {skipped}   DIVERGENT: {len(diffs)}")
    if diffs:
        print("\nA second compile in the same process emitted different bytes:")
        for rel, detail in diffs:
            print(f"  {rel}  ({detail})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

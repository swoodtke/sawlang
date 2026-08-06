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
    python tools/irdet.py [-n COUNT] [--all] [-v] [--remote URL]

`make irdet` wires this up. Sampling is deterministic (fixed seed), so a failure
reproduces; `--all` sweeps every compilable tracked example.

`--all` is the second-longest gate in the battery, and the files in it are
independent, so `--remote URL` hands a core-weighted share of them to a remote
test worker (design 160) and checks the rest here at the same time. A worker
that is unreachable, refuses the token, or dies mid-sweep costs a note: the
files it did not answer for are checked locally before the gate reports, so the
verdict is always about the compiler and never about the network.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def emit_ir(rel: str, seed: str, task_id: int):
    """Compile `rel` to IR in a fresh process; return the bytes, or None if the
    file does not build standalone (module-path deps, host-only, ...).

    Checks run in parallel, so each compile gets its own `-o` base under
    `.build/irdet/` — the default `.build/<stem>` would collide across
    concurrent tasks (and across same-stem files in different subdirs).
    """
    stem = os.path.splitext(os.path.basename(rel))[0]
    out_base = os.path.join(REPO, ".build", "irdet",
                            "%d_s%s_%s" % (task_id, seed, stem))
    out_ll = out_base + ".ll"
    if os.path.exists(out_ll):
        os.remove(out_ll)
    env = dict(os.environ, PYTHONHASHSEED=seed)
    p = subprocess.run([sys.executable, SAWC, rel, "--emit-ir", "-o", out_base],
                       cwd=REPO, env=env, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(out_ll):
        return None
    with open(out_ll, "rb") as fh:
        blob = fh.read()
    os.remove(out_ll)
    return blob


def check_one(task):
    """(index, rel) -> (rel, 'ok'|'skip'|'mismatch', detail). The two seed
    compiles of one file stay sequential inside the task; parallelism is
    across files, which are independent."""
    idx, rel = task
    first = emit_ir(rel, SEEDS[0], idx)
    second = emit_ir(rel, SEEDS[1], idx) if first is not None else None
    if first is None or second is None:
        return (rel, "skip", "")
    if first != second:
        return (rel, "mismatch",
                "%d vs %d bytes" % (len(first), len(second)))
    return (rel, "ok", "")


class JsonlSink:
    """Append one record per checked file, flushed as it lands.

    A remote worker tails this file while the check is still running, which is
    what makes a remote shard stream its verdicts back instead of arriving in
    one lump at the end. Flushing per line is the whole contract.
    """

    def __init__(self, path):
        self._fh = open(path, "a", encoding="utf-8") if path else None
        self._lock = threading.Lock()

    def write(self, **record):
        if self._fh is None:
            return
        with self._lock:
            self._fh.write(json.dumps(record, sort_keys=True) + "\n")
            self._fh.flush()

    def close(self):
        if self._fh is not None:
            self._fh.close()


def check_files(files, jobs, verbose, sink=None, first_index=0):
    """Check `files` here; return `{rel: (status, detail)}`.

    Files are independent, so checks run in a thread pool (the work is
    subprocess-bound). executor.map preserves input order, so output and exit
    status stay deterministic regardless of completion order. `first_index`
    offsets the per-task scratch names so a local shard and a fallback pass
    cannot collide on one.
    """
    out = {}
    if not files:
        return out
    tasks = [(first_index + i, rel) for i, rel in enumerate(files)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for rel, status, detail in pool.map(check_one, tasks):
            out[rel] = (status, detail)
            if sink:
                sink.write(kind="file", path=rel, status=status, detail=detail)
            if status == "skip" and verbose:
                print("  skip (does not build standalone): %s" % rel)
            if status == "mismatch":
                print("  MISMATCH: %s (%s)" % (rel, detail))
    return out


def plan_remote(url, token_file, connect_timeout, files):
    """Decide the split before any checking starts.

    Returns `(worker, snapshot, local_files, remote_files, notes)`, with
    `worker` None when the run should stay local. The worker's core count is
    only known after `/health`, and the split is weighted by it, so connecting
    has to come first — which is also why an unreachable worker costs nothing
    but a connect timeout: no snapshot has been built yet.
    """
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import worker_client                        # noqa: E402
    import worker_proto                         # noqa: E402

    worker, info, why = worker_client.connect(url, token_file, connect_timeout)
    if worker is None:
        return None, None, files, [], [f"{why}; checking every file here"]

    weights = [os.cpu_count() or 1, info.cores]
    local_files, remote_files = worker_proto.split_by_shard(files, weights)
    blob, why = worker_client.snapshot(REPO)
    if blob is None:
        return None, None, files, [], [f"{why}; checking every file here"]
    return worker, blob, local_files, remote_files, [
        f"remote: {info.describe()}; {len(local_files)} file(s) here, "
        f"{len(remote_files)} there"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=40,
                    help="how many examples to sample (default 40)")
    ap.add_argument("--all", action="store_true",
                    help="sweep every compilable example instead of sampling")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-j", "--jobs", type=int,
                    default=max(1, min(10, (os.cpu_count() or 2) - 2)),
                    help="concurrent checks (default: min(10, cores-2))")
    ap.add_argument("--only-files", metavar="FILE", default=None,
                    help="check exactly the repo-relative paths listed in FILE, "
                         "one per line (how a remote worker is given its shard)")
    ap.add_argument("--jsonl", metavar="FILE", default=None,
                    help="append one JSON record per checked file, flushed as "
                         "it lands")
    ap.add_argument("--remote", metavar="URL", default=None,
                    help="hand a core-weighted share of the files to a remote "
                         "test worker (design 160)")
    ap.add_argument("--remote-token-file", metavar="PATH", default=None)
    ap.add_argument("--remote-connect-timeout", type=float, default=10.0,
                    metavar="SECS")
    args = ap.parse_args()

    if args.only_files:
        with open(args.only_files, encoding="utf-8") as fh:
            sample = [ln.strip() for ln in fh if ln.strip()]
    else:
        files = [f for f in tracked_examples() if not is_negative_test(f)]
        if args.all:
            sample = files
        else:
            random.seed(20260804)      # fixed: a failure must reproduce
            sample = sorted(random.sample(files, min(args.count, len(files))))

    os.makedirs(os.path.join(REPO, ".build", "irdet"), exist_ok=True)
    sink = JsonlSink(args.jsonl)
    t0 = time.time()
    notes = []
    results = {}
    local_files, remote_files = sample, []
    worker = blob = None

    if args.remote:
        worker, blob, local_files, remote_files, notes = plan_remote(
            args.remote, args.remote_token_file, args.remote_connect_timeout,
            sample)

    remote_results = {}
    thread = None
    if worker is not None and remote_files:
        def collect():
            def on_file(event):
                rel = event.get("path")
                if not rel:
                    return
                remote_results[rel] = (event.get("status", "skip"),
                                       event.get("detail", ""))
                if event.get("status") == "mismatch":
                    print("  MISMATCH (remote): %s (%s)"
                          % (rel, event.get("detail", "")))
            run = worker.submit(
                {"kind": "irdet", "paths": remote_files, "jobs": args.jobs},
                blob, {"file": on_file})
            notes.extend(run.notes)

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()

    # The local share is checked while the worker chews on its own.
    results.update(check_files(local_files, args.jobs, args.verbose, sink))

    if thread is not None:
        thread.join()
        for rel, (status, detail) in remote_results.items():
            sink.write(kind="file", path=rel, status=status, detail=detail)
        results.update(remote_results)
        missing = [f for f in remote_files if f not in remote_results]
        if missing:
            notes.append(f"the worker answered for {len(remote_files) - len(missing)} "
                         f"of {len(remote_files)} file(s); checking the other "
                         f"{len(missing)} here")
            results.update(check_files(missing, args.jobs, args.verbose, sink,
                                       first_index=len(sample)))

    sink.close()
    mismatches = sorted(r for r, (s, _) in results.items() if s == "mismatch")
    skipped = sum(1 for s, _ in results.values() if s == "skip")
    checked = len(results) - skipped

    for note in notes:
        print("irdet: %s" % note)
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

#!/usr/bin/env python3
"""Run the IR-determinism sweep across TWO machines (design 160).

The harness itself is Saw now (`devtools/irdet/`, design 155) and knows nothing
about the network: it checks the files it is given and streams a verdict per
file into a `--jsonl` sink. This driver is the other half — it splits the corpus
by core count, hands one share to a remote test worker, runs the other share
here through the same binary, and merges the two answers into one verdict.

    python tools/irdet_remote.py --remote studio.local:8710 [--all] [-n N] [-j N]

A worker that is unreachable, refuses the token, or dies mid-sweep costs a note:
the files it did not answer for are checked here before the gate reports, so the
verdict is always about the compiler and never about the network.

Without `--remote` this is just the local binary, and you should run that
directly instead.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

IRDET_SOURCE = os.path.join("devtools", "irdet", "src", "main.saw")
IRDET_BIN = os.path.join(".build", "irdetbin")


def build_harness(python: str) -> str:
    """Compile the Saw harness and return its path. Exits on failure."""
    out = os.path.join(REPO, IRDET_BIN)
    r = subprocess.run([python, os.path.join("sawc", "sawc.py"),
                        IRDET_SOURCE, "-o", IRDET_BIN],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("irdet_remote: could not build the Saw harness")
    return out


def candidate_files(binary: str, args) -> list:
    """The file list this run covers.

    Asked of the harness itself rather than recomputed here: which examples are
    negative tests is the harness's rule, and two implementations of it would be
    two rules. `--plan` prints the list it WOULD check and exits.

    Judged on the OUTPUT, not the status (design 221 Part D). The status was
    vacuous for the whole of this tool's life — irdet's `main` suspends, and a
    suspending `main` never propagated its value (DF-220b), so `--plan` reported
    0 whatever happened. It propagates now; the check stays on the output
    because that is what this function actually needs to be true, and an empty
    plan is the failure it was reaching for. A harness that died writes nothing.
    """
    argv = [binary, "--plan"]
    if args.all:
        argv.append("--all")
    else:
        argv += ["-n", str(args.count)]
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    files = [ln.strip() for ln in r.stdout.splitlines()
             if ln.strip().endswith(".saw")]
    if not files:
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("irdet_remote: the harness listed no files to check")
    return files


def check_here(binary: str, files: list, jobs: int, verbose: bool) -> dict:
    """Check `files` on this machine; return `{rel: (status, detail)}`."""
    if not files:
        return {}
    listing = os.path.join(REPO, ".build", "irdet-local-files.txt")
    results = os.path.join(REPO, ".build", "irdet-local.jsonl")
    os.makedirs(os.path.dirname(listing), exist_ok=True)
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("\n".join(files) + "\n")
    if os.path.exists(results):
        os.remove(results)

    argv = [binary, "--only-files", listing, "--jsonl", results,
            "-j", str(jobs)]
    if verbose:
        argv.append("-v")
    subprocess.run(argv, cwd=REPO)

    out = {}
    if os.path.exists(results):
        with open(results, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("kind") == "file" and record.get("path"):
                    out[record["path"]] = (record.get("status", "skip"),
                                           record.get("detail", ""))
    return out


def plan_remote(url, token_file, connect_timeout, files):
    """Decide the split before any checking starts.

    Returns `(worker, snapshot, local_files, remote_files, notes)`, with
    `worker` None when the run should stay local. The worker's core count is
    only known after `/health`, and the split is weighted by it, so connecting
    has to come first — which is also why an unreachable worker costs nothing
    but a connect timeout: no snapshot has been built yet.
    """
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
    ap.add_argument("-n", "--count", type=int, default=40)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=8)
    ap.add_argument("--python", default=os.path.join(REPO, ".venv", "bin", "python"),
                    help="the interpreter that builds the harness")
    ap.add_argument("--remote", metavar="URL", required=True,
                    help="hand a core-weighted share of the files to a remote "
                         "test worker (design 160)")
    ap.add_argument("--remote-token-file", metavar="PATH", default=None)
    ap.add_argument("--remote-connect-timeout", type=float, default=10.0,
                    metavar="SECS")
    args = ap.parse_args()

    binary = build_harness(args.python)
    files = candidate_files(binary, args)
    t0 = time.time()

    worker, blob, local_files, remote_files, notes = plan_remote(
        args.remote, args.remote_token_file, args.remote_connect_timeout, files)

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
    results = check_here(binary, local_files, args.jobs, args.verbose)

    if thread is not None:
        thread.join()
        results.update(remote_results)
        missing = [f for f in remote_files if f not in remote_results]
        if missing:
            notes.append(f"the worker answered for "
                         f"{len(remote_files) - len(missing)} of "
                         f"{len(remote_files)} file(s); checking the other "
                         f"{len(missing)} here")
            results.update(check_here(binary, missing, args.jobs, args.verbose))

    mismatches = sorted(r for r, (s, _) in results.items() if s == "mismatch")
    skipped = sum(1 for s, _ in results.values() if s == "skip")
    checked = len(results) - skipped

    for note in notes:
        print("irdet: %s" % note)
    print("irdet: compiled %d example(s) twice under differing PYTHONHASHSEED "
          "(%d skipped, %.1fs)" % (checked, skipped, time.time() - t0))
    if mismatches:
        print("irdet: %d file(s) produced NON-REPRODUCIBLE IR" % len(mismatches))
        return 1
    if checked == 0:
        print("irdet: NOTHING WAS CHECKED -- every candidate failed to compile.")
        return 1
    print("irdet: OK -- every sampled example compiled to byte-identical IR")
    return 0


if __name__ == "__main__":
    sys.exit(main())

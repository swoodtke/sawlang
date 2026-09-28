"""Runs the instrument over every entry of the source corpus, one process per
entry, and caches each run's records by the entry's tag."""
import concurrent.futures
import json
import os
import subprocess
import sys

import layout

INSTRUMENT = os.path.join(layout.HERE, "instrument.py")
TIMEOUT = 600


def tag_of(path):
    return path.replace("/", "__")


def run_one(path, outdir, root=layout.REPO, python=sys.executable, fresh=False):
    tag = tag_of(path)
    out = os.path.join(outdir, tag + ".json")
    if os.path.exists(out) and not fresh:
        return path, out
    with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    binary = os.path.join(outdir, "bin", tag)
    cmd = [python, INSTRUMENT, out, "--", os.path.join(root, path),
           *layout.compile_flags(text, path, root), "-o", binary]
    env = dict(os.environ, PYTHONHASHSEED="0")
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=TIMEOUT, env=env)
        if not os.path.exists(out):
            with open(out, "w", encoding="utf-8") as fh:
                json.dump([{"kind": "status", "status": "no-output:%d" % r.returncode,
                            "stderr": r.stderr[-2000:]}], fh)
    except subprocess.TimeoutExpired:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump([{"kind": "status", "status": "timeout"}], fh)
    return path, out


def observe(entries, outdir, jobs, root=layout.REPO, fresh=False, progress=None):
    """{entry: records} for every entry, running the ones not cached."""
    os.makedirs(os.path.join(outdir, "bin"), exist_ok=True)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futures = [pool.submit(run_one, p, outdir, root, sys.executable, fresh) for p in entries]
        for n, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            path, out = fut.result()
            with open(out, encoding="utf-8") as fh:
                results[path] = json.load(fh)
            if progress and n % 100 == 0:
                progress("observed %d/%d" % (n, len(entries)))
    return results


def status_of(records):
    for r in records:
        if r.get("kind") == "status":
            return r.get("status")
    return "missing"

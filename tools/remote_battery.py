#!/usr/bin/env python3
"""Run a brief's gate battery on the remote test worker (design 160).

    ./.venv/bin/python tools/remote_battery.py --remote studio.local:8710

Submits the working tree as it stands and runs, on the worker, in order:

    test_runner.py          the full suite
    tools/lexdiff.py        the two lexers agree
    tools/astdiff.py        the two parsers agree
    tools/irdet.py --all    every example compiles to byte-identical IR

This is the agent-workflow half of design 160: the machine that just finished a
unit ships its tree to the worker and starts the next one while the battery
runs elsewhere. Nothing is shared but the snapshot — the worker unpacks into a
fresh directory, compiles everything itself, and purges when it is done.

`tools/sos_runner.py` is deliberately NOT in the battery. It boots a kernel
under QEMU, which the worker is not required to have installed; run it locally
alongside this. `tools/blade_bootstrap.py` is likewise left out: it is a
self-hosting loop whose failure modes are worth watching directly.

Exit status says which kind of answer you got, so a wrapper can tell a real
failure from a missing machine:

    0   every gate passed on the worker
    1   a gate FAILED — this is a verdict about the tree
    2   the battery did not run (unreachable, refused, or cut short) — this is
        not a verdict about anything; run the battery locally
"""

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import worker_client  # noqa: E402

LOCAL_BATTERY = (
    "./.venv/bin/python test_runner.py",
    "./.venv/bin/python tools/lexdiff.py",
    "./.venv/bin/python tools/astdiff.py",
    "./.venv/bin/python tools/irdet.py --all",
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--remote", required=True, metavar="URL",
                    help="worker address, e.g. studio.local:8710")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--connect-timeout", type=float, default=10.0,
                    metavar="SECS")
    ap.add_argument("--root", default=str(REPO), metavar="DIR",
                    help="the tree to submit (default: this checkout)")
    args = ap.parse_args()

    worker, info, why = worker_client.connect(args.remote, args.token_file,
                                              args.connect_timeout)
    if worker is None:
        return _no_run(why)
    print(f"battery on {info.describe()}")
    if not info.sandboxed:
        print("  warning: that worker is NOT running under a sandbox profile")

    blob, why = worker_client.snapshot(Path(args.root))
    if blob is None:
        return _no_run(why)
    print(f"  submitting {len(blob) / 1e6:.1f} MB from {args.root}")

    started = time.monotonic()
    failed = []

    def on_start(event):
        print(f"  {event['name']:<8} running...", flush=True)

    def on_gate(event):
        name, ok = event["name"], event["ok"]
        verdict = "ok" if ok else f"FAILED (status {event.get('status')})"
        print(f"  {name:<8} {verdict} in {event.get('seconds', 0):.1f}s",
              flush=True)
        if not ok:
            failed.append(name)
            for line in (event.get("tail") or "").splitlines():
                print(f"      {line}")

    def on_log(event):
        print(f"  worker: {event.get('text', '')}")

    run = worker.submit({"kind": "battery"}, blob,
                        {"gate-start": on_start, "gate": on_gate,
                         "log": on_log})

    for note in run.notes:
        print(f"  note: {note}")
    elapsed = time.monotonic() - started

    if not run.completed:
        return _no_run("the battery did not finish on the worker")
    if failed:
        print(f"\nBATTERY FAILED on the worker in {elapsed:.0f}s: "
              f"{', '.join(failed)}")
        print("Reproduce locally with:")
        for cmd in LOCAL_BATTERY:
            print(f"  {cmd}")
        return 1
    print(f"\nBATTERY GREEN on the worker in {elapsed:.0f}s "
          f"(suite, lexdiff, astdiff, irdet --all)")
    print("Still to run locally: ./.venv/bin/python tools/sos_runner.py")
    return 0


def _no_run(why: str) -> int:
    print(f"the battery did NOT run: {why}")
    print("This is not a verdict about the tree. Run it here instead:")
    for cmd in LOCAL_BATTERY:
        print(f"  {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

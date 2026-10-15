#!/usr/bin/env python3
"""Two park std builds that overlap both hand back a complete std.

    python compiler/tests/coro/test_park_std.py

`coro_lane.run()` runs `run()`. The copy is slowed (it pauses after the first
directory entry) so that a build in flight is observable by the other, the
overlap `parallel_order` produces by chance. Each build's result is checked
for every std file and the park tail on `task.saw`, after both finish. The
builds go to a scratch root, never the lane's own (SL-692).
"""
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import coro_lane  # noqa: E402


def _files(root):
    out = set()
    for base, _, names in os.walk(root):
        for name in names:
            out.add(os.path.relpath(os.path.join(base, name), root))
    return out


def run():
    failures = []
    scratch = tempfile.mkdtemp(prefix="park-std-test-")
    real_copytree = shutil.copytree
    saved = (coro_lane.PARK_ROOT, getattr(coro_lane, "PARK_STD", None))

    def slow_copytree(src, dst, *args, **kwargs):
        def slow_copy(a, b, **kw):
            time.sleep(0.02)
            return shutil.copy2(a, b, **kw)
        return real_copytree(src, dst, *args, copy_function=slow_copy, **kwargs)

    results = {}

    def build(name):
        try:
            results[name] = coro_lane.park_std()
        except Exception as e:  # noqa: BLE001
            results[name] = e

    try:
        coro_lane.PARK_ROOT = scratch
        coro_lane.PARK_STD = os.path.join(scratch, "std")
        shutil.copytree = slow_copytree
        threads = [threading.Thread(target=build, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
            time.sleep(0.2)
        for t in threads:
            t.join()
    finally:
        shutil.copytree = real_copytree
        coro_lane.PARK_ROOT, coro_lane.PARK_STD = saved
        want = _files(os.path.join(coro_lane.REPO, "std"))
        with open(coro_lane.PARKS_TAIL) as fh:
            tail = fh.read()
        for name in sorted(results):
            got = results[name]
            if isinstance(got, Exception):
                failures.append("park std build %s raised %r" % (name, got))
                continue
            root = os.path.join(coro_lane.REPO, got)
            if not os.path.isdir(root) or _files(root) != want:
                failures.append("park std build %s: %s is not a complete std" % (name, got))
                continue
            with open(os.path.join(root, "task.saw")) as fh:
                if not fh.read().endswith(tail):
                    failures.append("park std build %s: task.saw does not end in the park tail" % name)
        shutil.rmtree(scratch, ignore_errors=True)
    return failures, {"park std concurrent builds": len(results)}


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    print("park std: %s" % ("FAIL (%d)" % len(failures) if failures else "ok"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

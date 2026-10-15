#!/usr/bin/env python3
"""Pins for the seed blobs a worker snapshot carries (SL-696).

Run:  ./.venv/bin/python tools/test_worker_snapshot.py

Each case builds a small tree whose manifest names fake seed files, points the
funnel's cache at a scratch directory, and snapshots the tree.
"""

import hashlib
import io
import lzma
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import worker_client  # noqa: E402
import worker_proto as proto  # noqa: E402

build = proto._build_module()


def _check(ok, why):
    if not ok:
        raise AssertionError(why)


def _tree(base, payloads):
    """A tree whose manifest names `payloads` as the driver's IR plus runtime
    sources; returns (root, {sha256: bytes})."""
    root = base / "tree"
    (root / "compiler" / "seed").mkdir(parents=True)
    (root / "sawc").mkdir()
    (root / "sawc" / "sawc.py").write_text("pass\n")
    (root / ".build").mkdir()
    (root / ".build" / "other").write_text("product")
    blobs, lines = {}, []
    names = [build.SEED_DRIVER] + ["runtime/r%d.ll.xz" % i for i in range(len(payloads) - 1)]
    for name, text in zip(names, payloads):
        data = lzma.compress(text.encode())
        sha = hashlib.sha256(data).hexdigest()
        blobs[sha] = data
        lines.append("t-triple\t%s\t%s\t%d\n" % (name, sha, len(data)))
    (root / "compiler" / "seed" / "manifest.tsv").write_text("".join(lines))
    return root, blobs


def _members(blob):
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return {m.name: (tar.extractfile(m).read() if m.isfile() else None) for m in tar.getmembers()}


def _setup(d, payloads):
    base = Path(d)
    cache = base / "cache"
    cache.mkdir()
    build.BLOB_CACHE = str(cache)
    os.environ[build.BLOB_URL_VARIABLE] = "http://127.0.0.1:9/"
    return _tree(base, payloads), cache


def test_carries_exactly_the_manifest_blobs():
    with tempfile.TemporaryDirectory() as d:
        (root, blobs), cache = _setup(d, ["a", "b", "c"])
        (cache / "ffff").write_bytes(b"not in the manifest")
        for sha, data in blobs.items():
            (cache / sha).write_bytes(data)
        got = _members(proto.build_snapshot(root))
        under = {n: v for n, v in got.items() if n.startswith(".build/") and v is not None}
        _check(under == {".build/blobs/" + sha: data for sha, data in blobs.items()},
               "the snapshot's .build/ files are not exactly the manifest's blobs: %s" % sorted(under))
        _check("sawc/sawc.py" in got, "sources must still travel")


def test_missing_blob_without_network_names_the_file():
    with tempfile.TemporaryDirectory() as d:
        (root, blobs), cache = _setup(d, ["a", "b"])
        blob, why = worker_client.snapshot(root)
        _check(blob is None, "a snapshot without the seed must not be sent")
        _check(build.SEED_DRIVER in why or "runtime/r0.ll.xz" in why, "the reason names no file: %s" % why)


def test_corrupt_cached_blob_is_not_carried():
    with tempfile.TemporaryDirectory() as d:
        (root, blobs), cache = _setup(d, ["a", "b"])
        shas = sorted(blobs)
        for sha in shas:
            (cache / sha).write_bytes(blobs[sha])
        (cache / shas[0]).write_bytes(b"corrupt")
        blob, why = worker_client.snapshot(root)
        if blob is not None:
            _check(_members(blob)[".build/blobs/" + shas[0]] == blobs[shas[0]],
                   "a corrupted blob was carried as is")
        else:
            _check("SHA-256" in why or "bytes" in why, "unclear reason: %s" % why)


def test_two_snapshots_are_identical():
    with tempfile.TemporaryDirectory() as d:
        (root, blobs), cache = _setup(d, ["a", "b", "c"])
        for sha, data in blobs.items():
            (cache / sha).write_bytes(data)
        first = proto.build_snapshot(root)
        time.sleep(1.1)  # a gzip header stamped with the clock differs across a second
        _check(first == proto.build_snapshot(root),
               "the same tree and blobs gave two different snapshots")


def test_tree_without_manifest_carries_no_blobs():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "tree"
        root.mkdir()
        (root / "x.py").write_text("pass\n")
        _check(list(_members(proto.build_snapshot(root))) == ["x.py"], "unexpected members")


def main():
    saved = (build.BLOB_CACHE, os.environ.get(build.BLOB_URL_VARIABLE))
    failed = 0
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print("ok   " + name)
                except Exception as e:
                    failed += 1
                    print("FAIL %s: %s" % (name, e))
    finally:
        build.BLOB_CACHE = saved[0]
        if saved[1] is None:
            os.environ.pop(build.BLOB_URL_VARIABLE, None)
        else:
            os.environ[build.BLOB_URL_VARIABLE] = saved[1]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

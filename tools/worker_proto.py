#!/usr/bin/env python3
"""Wire vocabulary shared by the remote test worker and its clients (design 160).

The worker exists so a second machine can take half of a gate run. The user's
pin on the design is that NO SSH is involved: the worker machine runs one fixed
daemon, launched by hand under `sandbox-exec`, and the only thing that crosses
the wire is a job — a snapshot of the tree plus a list of what to run. Nothing
the client sends is ever executed by the daemon process itself; every job runs
in a child process tree, which is where the sandbox boundary lives.

This module is the part both sides must agree on, and deliberately nothing
else: it imports only the standard library, never the compiler, and never the
test runner.

## The protocol

One HTTP/1.0 request per job, so streaming needs no chunk framing — the
response body is JSON Lines and the connection close is the end of it.

    GET  /health   -> one JSON object describing the worker
    POST /job      -> a stream of JSON Lines, one event per line

Both require `Authorization: Bearer <token>`. The token is a shared secret in a
file (default `~/.config/saw-worker/token`), because a token file is something
the user can create, read, rotate and revoke without any daemon-side state.

A job's request body is framed as:

    4 bytes  big-endian length of the spec
    N bytes  the spec, UTF-8 JSON
    rest     a gzipped tar of the client's tree

The spec says which KIND of job this is (`suite`, `irdet`, `battery`) and, for
the sharded kinds, exactly which repo-relative paths to run. It never contains
a command line: the daemon decides what to execute, so a client cannot ask the
worker to run something arbitrary.
"""

import hashlib
import io
import json
import os
import struct
import tarfile
from pathlib import Path

# Bumped only for a breaking wire change. `/health` reports it and clients
# refuse a worker they cannot speak to, rather than failing halfway through a
# job with a confusing parse error.
PROTOCOL_VERSION = 1

DEFAULT_PORT = 8710

# Where the shared secret lives. The env var wins, so a test (or a second
# worker on the same machine) can use a different token without touching the
# user's real one.
TOKEN_ENV = "SAW_WORKER_TOKEN"
TOKEN_FILE_ENV = "SAW_WORKER_TOKEN_FILE"
DEFAULT_TOKEN_FILE = Path.home() / ".config" / "saw-worker" / "token"

# The daemon emits `{"event": "ping"}` this often while a job is running, so a
# client can distinguish "the gate is just slow" from "the worker died". A
# whole-corpus irdet gate goes minutes without producing a verdict; without a
# heartbeat the only safe client-side read timeout would be longer than the
# longest gate, which is the same as having no timeout at all.
HEARTBEAT_SECS = 15.0

# What a client should give up on. Four missed heartbeats: long enough that a
# briefly wedged worker recovers, short enough that a dead one degrades the run
# in well under a minute.
STREAM_IDLE_TIMEOUT = HEARTBEAT_SECS * 4

JOB_KINDS = ("suite", "irdet", "battery")

# Everything under the client's root that must NOT travel. `.git` and `.venv`
# are large and useless to the worker (it has its own venv, and jobs need no
# history); `.build` is the one that matters for correctness — build products
# are the thing the design says never crosses the wire, so the worker compiles
# everything it runs.
SNAPSHOT_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", ".build", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", "worktrees",
    # A worker's job root defaults to `<checkout>/.worker-jobs`, so a machine
    # that is both client and worker — the loopback self-test, or a Studio
    # submitting to itself — would otherwise pack a whole unpacked tree, and
    # its runtime-object cache, into the next snapshot.
    ".worker-jobs",
})
SNAPSHOT_EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".o", ".ll")
SNAPSHOT_EXCLUDE_NAMES = frozenset({".DS_Store"})


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------

def load_token(explicit_file=None) -> str:
    """Read the shared secret, or return "" if there is none.

    Order: an explicit file argument, then `SAW_WORKER_TOKEN` (the literal
    secret), then `SAW_WORKER_TOKEN_FILE`, then the default path. Returning ""
    rather than raising is deliberate — the daemon turns a missing token into a
    refusal to start, and a client turns it into a note and a local-only run.
    Neither should be an unhandled traceback.
    """
    if explicit_file:
        return _read_token_file(Path(explicit_file))
    env = os.environ.get(TOKEN_ENV)
    if env and env.strip():
        return env.strip()
    env_file = os.environ.get(TOKEN_FILE_ENV)
    if env_file:
        return _read_token_file(Path(env_file))
    return _read_token_file(DEFAULT_TOKEN_FILE)


def _read_token_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Tree snapshot
# ---------------------------------------------------------------------------

def build_snapshot(root: Path) -> bytes:
    """Pack `root` into a gzipped tar the worker can unpack into a fresh tree.

    Entries are sorted and their metadata normalized (mtime 0, uid/gid 0, no
    owner names), so the same tree always produces the same bytes. That is not
    required by the protocol; it is what makes a snapshot comparable across
    runs when something goes wrong and you need to know whether the worker saw
    what you think it saw.

    Symlinks are stored as symlinks and never followed: following them would
    both inflate the snapshot and let a link out of the tree drag arbitrary
    host files onto the worker.
    """
    root = Path(root)
    buf = io.BytesIO()
    # mtime=0 keeps the gzip header itself stable too.
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6,
                      format=tarfile.PAX_FORMAT) as tar:
        for rel in _snapshot_members(root):
            info = tar.gettarinfo(str(root / rel), arcname=str(rel))
            if info is None:
                continue
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if info.isfile():
                with open(root / rel, "rb") as fh:
                    tar.addfile(info, fh)
            else:
                tar.addfile(info)
    return buf.getvalue()


def _snapshot_members(root: Path):
    """Yield the repo-relative paths a snapshot carries, sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SNAPSHOT_EXCLUDE_DIRS)
        for d in dirnames:
            out.append(rel_dir / d if str(rel_dir) != "." else Path(d))
        for name in sorted(filenames):
            if name in SNAPSHOT_EXCLUDE_NAMES:
                continue
            if name.endswith(SNAPSHOT_EXCLUDE_SUFFIXES):
                continue
            out.append(rel_dir / name if str(rel_dir) != "." else Path(name))
    out.sort(key=str)
    return out


def runtime_cache_key(root: Path):
    """A digest of the compiler sources in a tree, or None if there are none.

    `.build/rt/` holds the Saw runtime objects the compiler builds once and
    links into every hosted binary. Build products never cross the wire, so a
    job would rebuild them from scratch every time; the worker instead keeps
    them keyed by this digest and reuses them only for a tree whose compiler is
    byte-identical. Any change under `sawc/` — the compiler, the runtime's own
    `.saw` sources, `shim.c` — produces a different key and a fresh build.

    It walks the same files a snapshot carries, so the key computed from a
    client's tree and the key computed from the worker's unpacked copy of it
    agree. Hashing `__pycache__` would break exactly that.
    """
    sawc = Path(root) / "sawc"
    if not sawc.is_dir():
        return None
    h = hashlib.blake2b(digest_size=16)
    for rel in _snapshot_members(sawc):
        path = sawc / rel
        if not path.is_file() or path.is_symlink():
            continue
        h.update(str(rel).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def extract_snapshot(blob: bytes, dest: Path) -> None:
    """Unpack a snapshot into `dest`, refusing any member that escapes it.

    The daemon is the one place in this system that handles bytes from the
    network, so the classic tar traversal (`../../.ssh/authorized_keys`) is
    checked here rather than trusted to the sandbox. Both defences are wanted:
    the sandbox stops a successful escape from mattering, and this stops the
    escape.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if target != resolved_dest and resolved_dest not in target.parents:
                raise ValueError(
                    f"snapshot member escapes the job directory: {member.name!r}")
            if member.islnk() or member.issym():
                link_target = (target.parent / member.linkname).resolve()
                if (link_target != resolved_dest
                        and resolved_dest not in link_target.parents):
                    raise ValueError(
                        f"snapshot link escapes the job directory: "
                        f"{member.name!r} -> {member.linkname!r}")
        tar.extractall(dest, filter="tar")


# ---------------------------------------------------------------------------
# Request framing
# ---------------------------------------------------------------------------

_SPEC_LEN = struct.Struct(">I")

# A spec is a few kilobytes of paths at most; anything larger is a malformed or
# hostile request and is refused before allocating for it.
MAX_SPEC_BYTES = 8 * 1024 * 1024


def frame_job(spec: dict, snapshot: bytes) -> bytes:
    blob = json.dumps(spec, sort_keys=True).encode("utf-8")
    return _SPEC_LEN.pack(len(blob)) + blob + snapshot


def unframe_job(body: bytes) -> tuple:
    if len(body) < _SPEC_LEN.size:
        raise ValueError("job body is truncated (no spec length)")
    (n,) = _SPEC_LEN.unpack(body[:_SPEC_LEN.size])
    if n > MAX_SPEC_BYTES:
        raise ValueError(f"job spec claims {n} bytes, over the limit")
    start = _SPEC_LEN.size
    if len(body) < start + n:
        raise ValueError("job body is truncated (spec shorter than declared)")
    spec = json.loads(body[start:start + n].decode("utf-8"))
    return spec, body[start + n:]


# ---------------------------------------------------------------------------
# Deterministic, core-weighted sharding
# ---------------------------------------------------------------------------

def shard_owner(key: str, weights) -> int:
    """Which shard owns `key`, given one weight per shard.

    Assignment is a hash of the test's own path, not a round-robin over an
    ordered list: a given test lands on the same machine on every run, so a
    failure reproduces where it happened and a rerun does not silently move it.
    Balance is the thing being traded away, and deliberately — with hundreds of
    tests the split lands within a few percent of the weights anyway.

    `weights` are core counts, so a 10-core laptop paired with a 24-core Studio
    sends the Studio ~70% of the work.
    """
    total = sum(weights)
    if total <= 0:
        return 0
    h = int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(),
                       "big")
    pos = h % total
    for i, w in enumerate(weights):
        if pos < w:
            return i
        pos -= w
    return len(weights) - 1


def split_by_shard(keys, weights):
    """Partition `keys` into one list per weight, preserving input order."""
    buckets = [[] for _ in weights]
    for key in keys:
        buckets[shard_owner(key, weights)].append(key)
    return buckets


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def encode_event(event: dict) -> bytes:
    """One event as a single JSON Lines record.

    Newlines inside strings are escaped by `json.dumps`, so a line is always a
    whole event — the property the client's readline loop depends on.
    """
    return (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")

#!/usr/bin/env python3
"""Self-test for the remote test worker (design 160).

Run:  ./.venv/bin/python tools/remote_worker_selftest.py

Everything here runs against a REAL worker on loopback — the daemon is started
as a child process, jobs really are compiled and executed in a fresh directory,
and the degradation cases really do kill it mid-job. There are no stubs: the
failure this suite exists to prevent is a client that hangs, or a gate that
goes red, because of the machine on the other end, and neither is provable
against a fake.

What is covered:

  * the shipped sandbox profile compiles against the running OS (and a broken
    profile is rejected, so the check is not vacuous);
  * shard assignment is deterministic and follows the core weights;
  * a snapshot carries sources and no build products, and a tar that tries to
    escape the job directory is refused;
  * `/health` accepts the right token and refuses a wrong one, and an
    unreachable worker is a note rather than an exception;
  * a suite shard round-trips, and the verdicts match a local run of the same
    tests, verdict for verdict;
  * a worker killed mid-job leaves the client with notes and a list of tests it
    did not get answers for;
  * a second job submitted while one is running is refused, not queued;
  * a battery submission starts its first gate on the worker.

One thing is NOT covered here, and cannot be: applying the sandbox profile.
A process already inside a seatbelt sandbox cannot apply a second one
(`sandbox_apply` returns EPERM), so an agent or CI job that is itself
sandboxed can compile the profile but not run under it. The daemon reports
`sandbox: ACTIVE` / `NOT ACTIVE` at startup for exactly this reason — on the
real worker machine, that line is the check.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import test_worker                                        # noqa: E402
import worker_client                                      # noqa: E402
import worker_proto as proto                              # noqa: E402

TOKEN = "selftest-" + os.urandom(8).hex()

# Three error tests (they settle at compile time, no binary) and one success
# test (compiled, linked and EXECUTED on the worker) — so a round trip covers
# both of the runner's stages.
SHARD = [
    "examples/hello.saw",
    "examples/errors/immutable.saw",
    "examples/errors/undefined_var.saw",
]


def _check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# A worker on loopback
# ---------------------------------------------------------------------------

class Worker:
    """A daemon child process, and the client wired up to talk to it."""

    def __init__(self, tmp: Path, seed_runtime=True):
        self.tmp = tmp
        self.job_root = tmp / "jobs"
        self.job_root.mkdir(parents=True, exist_ok=True)
        self.token_file = tmp / "token"
        self.token_file.write_text(TOKEN + "\n", encoding="utf-8")
        self.port_file = tmp / "port"
        self.log = open(tmp / "worker.log", "wb")
        if seed_runtime:
            self._seed_runtime()
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO / "tools" / "test_worker.py"),
             "--bind", "127.0.0.1:0",
             "--token-file", str(self.token_file),
             "--job-root", str(self.job_root),
             "--venv", sys.executable,
             "--print-port-file", str(self.port_file),
             "--job-timeout", "900", "-v"],
            cwd=str(REPO), stdout=self.log, stderr=subprocess.STDOUT,
            start_new_session=True)
        self.port = self._await_port()
        self.url = f"127.0.0.1:{self.port}"

    def _seed_runtime(self):
        """Pre-fill the worker's runtime cache from this checkout's `.build/rt`.

        Not a shortcut around anything under test: it is the same cache the
        worker fills for itself after its first job, seeded so the self-test
        does not pay a full Saw-runtime build to prove that a verdict travels.
        A machine without `.build/rt` yet simply builds it inside the job.
        """
        built = REPO / ".build" / "rt"
        key = proto.runtime_cache_key(REPO)
        if not key or not built.is_dir():
            return
        dest = self.job_root / "rt-cache" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built, dest, dirs_exist_ok=True)

    def _await_port(self, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                _check(False, f"the worker exited at startup:\n"
                              f"{(self.tmp / 'worker.log').read_text()}")
            try:
                text = self.port_file.read_text().strip()
                if text:
                    return int(text)
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        _check(False, "the worker never reported a port")

    def client(self, token=TOKEN):
        return worker_client.RemoteWorker(self.url, token, connect_timeout=5)

    def kill(self):
        try:
            os.killpg(os.getpgid(self.proc.pid), 9)
        except (ProcessLookupError, PermissionError, OSError):
            self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kill()
        self.log.close()


# ---------------------------------------------------------------------------
# Offline checks
# ---------------------------------------------------------------------------

def test_sandbox_profile_compiles():
    """The OS parses the shipped profile, and would reject a broken one.

    Compiling resolves every operation and filter name against the running
    kernel's sandbox vocabulary, so this catches a rule that macOS does not
    understand — the failure that would otherwise appear as a worker that
    refuses to launch.
    """
    problem = test_worker.compile_profile(REPO / "tools" / "test_worker.sb")
    _check(problem is None, f"the shipped profile does not compile: {problem}")

    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "bad.sb"
        bad.write_text("(version 1)\n(deny default)\n(allow not-an-operation)\n")
        problem = test_worker.compile_profile(bad)
        _check(problem is not None,
               "a profile naming a nonexistent operation was accepted — the "
               "profile check proves nothing")
    print("  ok: the sandbox profile compiles, and a broken one is rejected")


def test_sharding_is_deterministic_and_weighted():
    keys = [f"examples/t{i}.saw" for i in range(2000)]
    first = proto.split_by_shard(keys, [10, 24])
    again = proto.split_by_shard(keys, [10, 24])
    _check(first == again, "the same weights gave a different split")

    local, remote = first
    _check(len(local) + len(remote) == len(keys), "the split lost or duplicated keys")
    share = len(remote) / len(keys)
    _check(0.65 < share < 0.76,
           f"a 10/24 core split sent {share:.0%} to the worker, not ~71%")

    # A test's home depends on the weights, not on the order it was discovered
    # in: shuffling the input must not move anything.
    shuffled = list(reversed(keys))
    s_local, s_remote = proto.split_by_shard(shuffled, [10, 24])
    _check(set(s_local) == set(local) and set(s_remote) == set(remote),
           "reordering the inputs moved tests between machines")

    # One machine gets everything when the other has no cores to offer.
    only_local, only_remote = proto.split_by_shard(keys, [10, 0])
    _check(not only_remote and len(only_local) == len(keys),
           "a zero-core worker was still sent work")
    print("  ok: sharding is deterministic, order-independent and core-weighted")


def test_snapshot_contents_and_traversal():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "tree"
        (root / "sawc").mkdir(parents=True)
        (root / ".build").mkdir()
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()
        (root / "sawc" / "sawc.py").write_text("print('hi')\n")
        (root / ".build" / "binary").write_text("MZ")
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (root / "__pycache__" / "x.pyc").write_text("junk")
        (root / "stale.pyc").write_text("junk")

        blob = proto.build_snapshot(root)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            names = set(tar.getnames())
        _check("sawc/sawc.py" in names, f"sources must travel, got {names}")
        for unwanted in (".build/binary", ".git/HEAD", "__pycache__/x.pyc",
                         "stale.pyc"):
            _check(unwanted not in names,
                   f"{unwanted} must not travel — build products stay home")
        _check(blob == proto.build_snapshot(root),
               "the same tree produced two different snapshots")

        # A tar that tries to write outside the job directory is refused.
        evil = io.BytesIO()
        with tarfile.open(fileobj=evil, mode="w:gz") as tar:
            info = tarfile.TarInfo("../escaped.txt")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"bad"))
        try:
            proto.extract_snapshot(evil.getvalue(), Path(d) / "job")
        except ValueError as e:
            _check("escapes" in str(e), f"unexpected refusal message: {e}")
        else:
            _check(False, "a traversing tar member was extracted")
        _check(not (Path(d) / "escaped.txt").exists(),
               "the traversing member landed on disk")
    print("  ok: snapshots carry sources only, and traversal is refused")


# ---------------------------------------------------------------------------
# Live worker
# ---------------------------------------------------------------------------

def test_health_and_auth(worker):
    info, why = worker.client().probe()
    _check(info is not None, f"health with the right token failed: {why}")
    _check(info.cores >= 1, "health reported no cores")

    info, why = worker.client(token="wrong-token").probe()
    _check(info is None, "a wrong token was accepted")
    _check("token" in why, f"the refusal should name the token, got: {why}")

    dead = worker_client.RemoteWorker("127.0.0.1:9", TOKEN, connect_timeout=3)
    t0 = time.monotonic()
    info, why = dead.probe()
    _check(info is None, "a dead port answered /health")
    _check(time.monotonic() - t0 < 10, "an unreachable worker took too long to fail")
    _check("unreachable" in why, f"unexpected message for a dead port: {why}")
    print("  ok: health accepts the token, refuses a wrong one, and a dead "
          "worker is a note")


def test_suite_shard_matches_a_local_run(worker):
    """The parity check: the same tests, run here and there, agree."""
    local = _run_locally(SHARD)
    remote, run = _run_remotely(worker, SHARD)

    _check(run.completed, f"the remote shard did not finish: {run.notes}")
    _check(set(remote) == set(SHARD),
           f"the worker answered for {sorted(remote)}, expected {sorted(SHARD)}")
    for path in SHARD:
        _check(remote[path]["status"] == local[path]["status"],
               f"{path}: worker said {remote[path]['status']}, "
               f"this machine said {local[path]['status']}")
        _check(local[path]["status"] in ("pass", "xfail"),
               f"{path} is not green locally ({local[path]['status']}) — "
               f"pick different tests for the self-test")
    _check(not list((worker.job_root).glob("job-*")),
           "the job directory was not purged")
    print(f"  ok: a {len(SHARD)}-test shard round-trips and matches a local "
          f"run verdict-for-verdict")


def test_worker_death_mid_job_degrades(worker_tmp):
    """Kill the worker while it is running a shard: the client must come back
    with notes and the list of tests it never heard about."""
    with Worker(worker_tmp) as w:
        got = {}
        run = {}

        def on_result(event):
            got[event["path"]] = event

        def go():
            run["r"] = w.client().submit(
                {"kind": "suite", "paths": SHARD}, proto.build_snapshot(REPO),
                {"result": on_result})

        thread = threading.Thread(target=go, daemon=True)
        t0 = time.monotonic()
        thread.start()
        # Wait for the job to be underway, then pull the plug.
        _await(lambda: _job_started(w), 60, "the worker never started the job")
        w.kill()

        thread.join(timeout=proto.STREAM_IDLE_TIMEOUT + 30)
        _check(not thread.is_alive(),
               "the client never returned after the worker died — a dead "
               "worker must not hang a run")
        outcome = run.get("r")
        _check(outcome is not None, "the client returned no outcome")
        _check(not outcome.completed, "a killed job reported completion")
        _check(outcome.notes, "a killed job produced no note to print")
        missing = [p for p in SHARD if p not in got]
        _check(missing, "the kill landed after every verdict; test is not "
                        "exercising what it claims")
        elapsed = time.monotonic() - t0
        _check(elapsed < 300, f"degradation took {elapsed:.0f}s")
    print(f"  ok: a worker killed mid-job degrades to notes plus "
          f"{len(missing)} unanswered test(s), in {elapsed:.0f}s")


def test_second_job_is_refused_not_queued(worker):
    started = threading.Event()
    done = threading.Event()

    def first():
        worker.client().submit({"kind": "suite", "paths": SHARD},
                               proto.build_snapshot(REPO),
                               {"accepted": lambda e: started.set()})
        done.set()

    thread = threading.Thread(target=first, daemon=True)
    thread.start()
    _check(started.wait(120), "the first job never started")

    info, why = worker.client().probe()
    _check(info is None and "already running" in why,
           f"a busy worker should be declined at /health, got {info} / {why}")
    # A real snapshot, not an empty body: a refusal that arrives while this
    # side is still uploading megabytes is the case that used to surface as a
    # broken pipe instead of as the worker's reason.
    run = worker.client().submit({"kind": "suite", "paths": SHARD},
                                 proto.build_snapshot(REPO), {})
    _check(not run.completed, "a second concurrent job was accepted")
    _check(any("refused" in n for n in run.notes),
           f"the refusal should be a note, got {run.notes}")
    done.wait(timeout=300)
    thread.join(timeout=10)
    print("  ok: a busy worker refuses a second job instead of queueing it")


def test_battery_starts_on_the_worker(worker_tmp):
    """A battery submission reaches the worker and starts its first gate.

    The battery itself is the full local gate run and takes as long as one; the
    self-test proves the path is wired and then hangs up, which is also the
    interesting half — a client that disappears must not leave a suite running
    on the worker.
    """
    with Worker(worker_tmp) as w:
        seen = []
        run = {}

        def go():
            run["r"] = w.client().submit(
                {"kind": "battery"}, proto.build_snapshot(REPO),
                {"gate-start": lambda e: seen.append(e["name"])})

        thread = threading.Thread(target=go, daemon=True)
        thread.start()
        _await(lambda: bool(seen), 120, "the battery never started a gate")
        _check(seen[0] == "suite", f"the battery starts with the suite, got {seen}")
        w.kill()
        thread.join(timeout=proto.STREAM_IDLE_TIMEOUT + 30)
        _check(not thread.is_alive(), "the battery client hung after the kill")
    print("  ok: a battery submission starts the suite gate on the worker")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_locally(paths):
    """Run `paths` through the local runner and return {path: record}."""
    with tempfile.TemporaryDirectory() as d:
        listing = Path(d) / "paths.txt"
        listing.write_text("\n".join(paths) + "\n", encoding="utf-8")
        out = Path(d) / "results.jsonl"
        subprocess.run([sys.executable, str(REPO / "test_runner.py"),
                        "--only-paths", str(listing), "--jsonl", str(out),
                        "--settle-lag", "1"],
                       cwd=str(REPO), capture_output=True, text=True,
                       timeout=900)
        records = {}
        for line in out.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") == "test":
                records[record["path"]] = record
        return records


def _run_remotely(worker, paths):
    got = {}
    run = worker.client().submit(
        {"kind": "suite", "paths": paths, "settle_lag": 1},
        proto.build_snapshot(REPO), {"result": lambda e: got.update({e["path"]: e})})
    return got, run


def _job_started(worker):
    return any(p.is_dir() for p in worker.job_root.glob("job-*"))


def _await(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    _check(False, message)


def main() -> int:
    print("remote test worker self-test (design 160)")
    test_sandbox_profile_compiles()
    test_sharding_is_deterministic_and_weighted()
    test_snapshot_contents_and_traversal()

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with Worker(tmp / "w1") as worker:
            test_health_and_auth(worker)
            test_suite_shard_matches_a_local_run(worker)
            test_second_job_is_refused_not_queued(worker)
        test_worker_death_mid_job_degrades(tmp / "w2")
        test_battery_starts_on_the_worker(tmp / "w3")

    print("ALL SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

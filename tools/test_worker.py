#!/usr/bin/env python3
"""The Saw remote test worker: a fixed daemon that runs gate jobs for a client
machine (design 160).

Launch it, under the shipped sandbox profile, on the machine that has cores to
spare:

    sandbox-exec -D WORKER_ROOT="$PWD" -f tools/test_worker.sb \\
        ./.venv/bin/python tools/test_worker.py --bind 0.0.0.0:8710

There is no SSH anywhere in this system, by design. The worker machine exposes
exactly one port speaking exactly one protocol, and the daemon on the other end
of it is this file — small enough to read in a sitting, and fixed: a client
cannot ask it to run a command. A job says *which tests* to run, never *how*.

## What the daemon guarantees

* **It never executes the submitted tree in its own process.** Every job runs
  as a child process tree the daemon spawns with `start_new_session=True`, so
  the whole job can be killed as a group and, on the worker machine, that child
  tree is what the sandbox confines.
* **Every job gets a fresh directory, and it is purged when the job ends** —
  ends any way at all: success, failure, timeout, or the client hanging up.
* **The worker's own venv is what runs jobs.** The snapshot carries no build
  products and no interpreter; the worker compiles everything it runs.
* **One job at a time.** A second submission is refused with 409 rather than
  queued, because a client that waits behind an unknown queue cannot honour its
  own deadline — it degrades to running locally instead, which is always the
  right answer.

## Operational surface

    --bind HOST:PORT       where to listen (default 0.0.0.0:8710)
    --job-root DIR         where job directories live (default ./.worker-jobs)
    --venv PATH            interpreter jobs run under (default ./.venv/bin/python)
    --token-file PATH      the shared secret (default ~/.config/saw-worker/token)
    --job-timeout SECS     hard cap on one job (default 3600)
    --init-token           create a token file if there is none, print it, exit
    --check-profile PATH   compile a sandbox profile and report, exit
    --once                 serve a single job then exit (used by the self-test)
"""

import argparse
import hmac
import http.server
import json
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker_proto as proto  # noqa: E402

MAX_BODY_BYTES = 512 * 1024 * 1024

# How much of a gate's console output travels back with its verdict. Enough to
# see the failure, not so much that a broken job floods the client.
LOG_TAIL_LINES = 60


# ---------------------------------------------------------------------------
# Am I actually confined?
# ---------------------------------------------------------------------------

def sandbox_active() -> bool:
    """Whether this process is inside a seatbelt sandbox.

    The daemon reports this at startup and in `/health`. The sandbox is the
    entire security story of this design, and it is applied by a command-line
    wrapper the user types — which means the failure mode is forgetting it, and
    a forgotten sandbox looks exactly like a working one. So the daemon says
    which it is, every time it starts.
    """
    try:
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("System"))
        lib.sandbox_check.restype = ctypes.c_int
        lib.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                      ctypes.c_uint64]
        return lib.sandbox_check(os.getpid(), None, 0) == 1
    except Exception:
        return False


def compile_profile(path: Path):
    """Compile a seatbelt profile without applying it; return None on success
    or the compiler's message.

    This is how the shipped profile is checked on a machine that cannot apply a
    second sandbox (a nested `sandbox_apply` is refused). Compilation is not a
    no-op check: it resolves every operation and filter name against the
    running OS, so a profile naming an operation this macOS does not have is
    rejected here rather than at launch.
    """
    try:
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("sandbox")
                          or "libsandbox.1.dylib")
    except Exception as e:  # pragma: no cover - non-macOS
        return f"libsandbox is unavailable on this platform: {e}"

    lib.sandbox_create_params.restype = ctypes.c_void_p
    lib.sandbox_set_param.restype = ctypes.c_int
    lib.sandbox_set_param.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                      ctypes.c_char_p]
    lib.sandbox_compile_file.restype = ctypes.c_void_p
    lib.sandbox_compile_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_char_p)]

    params = lib.sandbox_create_params()
    # One parameter, with a placeholder value: compiling only needs it BOUND.
    # One is also all seatbelt takes here — a second `sandbox_set_param` call
    # corrupts the set and every `(param ...)` reference then fails to resolve,
    # which is why the profile spends its single parameter on WORKER_ROOT and
    # derives the job root from it with `string-append`.
    lib.sandbox_set_param(params, b"WORKER_ROOT", b"/tmp/saw-worker-root")
    err = ctypes.c_char_p()
    handle = lib.sandbox_compile_file(str(path).encode(), params,
                                      ctypes.byref(err))
    if handle:
        return None
    return (err.value or b"unknown error").decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# Event sink: the response body
# ---------------------------------------------------------------------------

class EventSink:
    """Serialised writer for the JSON Lines response.

    A job's own events and the heartbeat come from different threads, so writes
    take a lock. A client that hangs up mid-job turns a write into a broken
    pipe; that is recorded rather than raised, and the job runner polls
    `.broken` to kill the child — a disconnected client must not leave a suite
    running on the worker.
    """

    def __init__(self, wfile):
        self._wfile = wfile
        self._lock = threading.Lock()
        self.broken = False

    def emit(self, **event) -> None:
        with self._lock:
            if self.broken:
                return
            try:
                self._wfile.write(proto.encode_event(event))
                self._wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                self.broken = True


# ---------------------------------------------------------------------------
# Running one job
# ---------------------------------------------------------------------------

class JobRunner:
    """Executes one job in a fresh directory and streams its events."""

    def __init__(self, config, spec, snapshot, sink):
        self.config = config
        self.spec = spec
        self.snapshot = snapshot
        self.sink = sink
        self.job_id = f"job-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.dir = Path(config.job_root) / self.job_id
        self.tree = self.dir / "tree"
        self.deadline = time.monotonic() + config.job_timeout

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        heartbeat = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(heartbeat,),
                                daemon=True)
        try:
            proto.extract_snapshot(self.snapshot, self.tree)
        except Exception as e:
            self.sink.emit(event="error", message=f"could not unpack the snapshot: {e}")
            self._purge()
            return

        kind = self.spec.get("kind")
        self.sink.emit(event="accepted", job=self.job_id, kind=kind,
                       cores=os.cpu_count() or 1,
                       sandboxed=sandbox_active())
        beat.start()
        started = time.monotonic()
        try:
            self._seed_runtime_cache()
            if kind == "suite":
                ok, ran = self._run_suite()
            elif kind == "irdet":
                ok, ran = self._run_irdet()
            elif kind == "battery":
                ok, ran = self._run_battery()
            else:
                self.sink.emit(event="error",
                               message=f"unknown job kind {kind!r}")
                return
            self._save_runtime_cache()
            # Purge BEFORE saying done, so a client that has seen `done` knows
            # the worker is holding nothing of its tree. The `finally` below
            # purges again — rmtree is idempotent — for every other way out.
            self._purge()
            self.sink.emit(event="done", ok=ok, ran=ran,
                           seconds=round(time.monotonic() - started, 1))
        except Exception as e:  # a daemon bug must reach the client, not the void
            self.sink.emit(event="error", message=f"the worker failed this job: {e}")
        finally:
            heartbeat.set()
            self._purge()

    def _heartbeat(self, stop: threading.Event) -> None:
        while not stop.wait(proto.HEARTBEAT_SECS):
            if self.sink.broken:
                return
            self.sink.emit(event="ping", t=round(time.monotonic(), 1))

    def _purge(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # -- the compiled runtime cache ---------------------------------------

    def _cache_dir(self, key):
        return Path(self.config.job_root) / "rt-cache" / key

    def _seed_runtime_cache(self) -> None:
        key = proto.runtime_cache_key(self.tree)
        if not key:
            return
        self._rt_key = key
        src = self._cache_dir(key)
        if src.is_dir():
            dest = self.tree / ".build" / "rt"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=True)
            self.sink.emit(event="log", text=f"reused the cached Saw runtime ({key[:12]})")

    def _save_runtime_cache(self) -> None:
        key = getattr(self, "_rt_key", None)
        built = self.tree / ".build" / "rt"
        if not key or not built.is_dir():
            return
        dest = self._cache_dir(key)
        if dest.is_dir():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            shutil.copytree(built, tmp)
            os.replace(tmp, dest)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)

    # -- child processes ---------------------------------------------------

    def _child_env(self):
        """A deliberately small environment for jobs.

        Not the daemon's environment: a job should not inherit whatever the
        user's shell happened to export. `TMPDIR` points inside the job
        directory so scratch files are purged with everything else.
        """
        tmp = self.dir / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "HOME": os.environ.get("HOME", str(self.dir)),
            "TMPDIR": str(tmp),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "SAW_REMOTE_JOB": self.job_id,
        }

    def _spawn(self, argv, log_path: Path):
        log = open(log_path, "wb")
        proc = subprocess.Popen(
            argv, cwd=str(self.tree), env=self._child_env(),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        proc._saw_log = log  # closed by _await
        return proc

    def _await(self, proc, on_poll=None, poll_interval=0.15):
        """Wait for a child, honouring the job deadline and client hang-up.

        Returns the exit status, or None if the child was killed. `on_poll` is
        called between polls — that is where streamed verdicts are picked up,
        so results reach the client while the job is still running rather than
        in one lump at the end.
        """
        killed = None
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            if on_poll:
                on_poll()
            if self.sink.broken:
                killed = "the client disconnected"
                break
            if time.monotonic() > self.deadline:
                killed = f"the job exceeded its {self.config.job_timeout:g}s cap"
                break
            time.sleep(poll_interval)

        if killed:
            _kill_group(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            self.sink.emit(event="error", message=killed)
            rc = None
        if on_poll:
            on_poll()  # drain whatever landed between the last poll and exit
        try:
            proc._saw_log.close()
        except Exception:
            pass
        return rc

    # -- job kinds ---------------------------------------------------------

    def _run_suite(self):
        paths = [p for p in self.spec.get("paths", []) if p]
        if not paths:
            return True, 0
        shard_file = self.dir / "shard.txt"
        shard_file.write_text("\n".join(paths) + "\n", encoding="utf-8")
        results = self.dir / "results.jsonl"
        argv = [self.config.venv, "test_runner.py",
                "--only-paths", str(shard_file), "--jsonl", str(results)]
        if self.spec.get("jobs"):
            argv += ["-j", str(int(self.spec["jobs"]))]
        if self.spec.get("settle_lag") is not None:
            argv += ["--settle-lag", str(float(self.spec["settle_lag"]))]

        log = self.dir / "suite.log"
        seen = [0]
        ran = [0]

        def drain():
            for record in _read_new_lines(results, seen):
                if record.get("kind") == "test":
                    ran[0] += 1
                    self.sink.emit(event="result", **{
                        k: record.get(k) for k in
                        ("path", "name", "status", "msg", "note")})

        proc = self._spawn(argv, log)
        rc = self._await(proc, on_poll=drain)
        if rc is None or (rc != 0 and ran[0] == 0):
            self.sink.emit(event="log", text=_tail(log))
        return rc == 0, ran[0]

    def _run_irdet(self):
        paths = [p for p in self.spec.get("paths", []) if p]
        if not paths:
            return True, 0
        list_file = self.dir / "irdet-files.txt"
        list_file.write_text("\n".join(paths) + "\n", encoding="utf-8")
        results = self.dir / "irdet.jsonl"
        argv = [self.config.venv, "tools/irdet.py",
                "--only-files", str(list_file), "--jsonl", str(results)]
        if self.spec.get("jobs"):
            argv += ["-j", str(int(self.spec["jobs"]))]

        log = self.dir / "irdet.log"
        seen = [0]
        ran = [0]

        def drain():
            for record in _read_new_lines(results, seen):
                if record.get("kind") == "file":
                    ran[0] += 1
                    self.sink.emit(event="file", path=record.get("path"),
                                   status=record.get("status"),
                                   detail=record.get("detail", ""))

        proc = self._spawn(argv, log)
        rc = self._await(proc, on_poll=drain)
        if rc is None or (rc != 0 and ran[0] == 0):
            self.sink.emit(event="log", text=_tail(log))
        return rc == 0, ran[0]

    # The battery, in the order a finishing agent runs it. SOS stays on the
    # client in v1: it needs QEMU, which the worker is not required to have.
    BATTERY = (
        ("suite", ["test_runner.py"]),
        ("lexdiff", ["tools/lexdiff.py"]),
        ("astdiff", ["tools/astdiff.py"]),
        ("irdet", ["tools/irdet.py", "--all"]),
    )

    def _run_battery(self):
        all_ok = True
        ran = 0
        for name, argv in self.BATTERY:
            if self.sink.broken:
                break
            self.sink.emit(event="gate-start", name=name)
            log = self.dir / f"{name}.log"
            started = time.monotonic()
            proc = self._spawn([self.config.venv] + argv, log)
            rc = self._await(proc)
            ran += 1
            ok = rc == 0
            all_ok = all_ok and ok
            self.sink.emit(event="gate", name=name, ok=ok, status=rc,
                           seconds=round(time.monotonic() - started, 1),
                           tail=_tail(log))
            if rc is None:
                break  # killed: deadline or hang-up, nothing more will run
        return all_ok, ran


def _kill_group(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _read_new_lines(path: Path, seen):
    """Yield JSON records appended to `path` since the last call.

    `seen[0]` is a byte offset rather than a line count, so a partially written
    final line is simply not consumed yet: the offset only advances past
    complete lines.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(seen[0])
            data = fh.read()
    except FileNotFoundError:
        return
    if not data:
        return
    consumed = data.rfind(b"\n") + 1
    if consumed <= 0:
        return
    seen[0] += consumed
    for line in data[:consumed].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _tail(path: Path, lines: int = LOG_TAIL_LINES) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    kept = text.splitlines()[-lines:]
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

class WorkerHandler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.0 semantics: no keep-alive, no chunk framing. The response body IS
    # the event stream and the connection close is its terminator, which is the
    # simplest thing that streams correctly through the standard library on
    # both sides.
    protocol_version = "HTTP/1.0"
    server_version = "saw-test-worker/1"

    @property
    def config(self):
        return self.server.config

    def log_message(self, fmt, *args):  # quieter than the default
        if self.config.verbose:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # -- helpers -----------------------------------------------------------

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        offered = header[len(prefix):].strip() if header.startswith(prefix) else ""
        # compare_digest on both halves: a wrong token and a missing one must
        # cost the same, and neither may leak the real one by timing.
        return bool(offered) and hmac.compare_digest(offered, self.config.token)

    def _reply_json(self, code: int, payload: dict) -> None:
        body = (json.dumps(payload, sort_keys=True) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        if self.path.split("?")[0] != "/health":
            self._reply_json(404, {"error": "no such endpoint"})
            return
        if not self._authorized():
            self._reply_json(401, {"error": "bad or missing bearer token"})
            return
        self._reply_json(200, {
            "worker": "saw-test-worker",
            "protocol": proto.PROTOCOL_VERSION,
            "cores": os.cpu_count() or 1,
            "host": socket.gethostname(),
            "sandboxed": sandbox_active(),
            "busy": self.server.job_lock.locked(),
            "kinds": list(proto.JOB_KINDS),
        })

    def do_POST(self):
        if self.path.split("?")[0] != "/job":
            self._reply_json(404, {"error": "no such endpoint"})
            return
        if not self._authorized():
            self._reply_json(401, {"error": "bad or missing bearer token"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY_BYTES:
            self._reply_json(413, {"error": f"job body length {length} is not acceptable"})
            return

        # Refuse before reading the body: a busy worker should cost the client
        # a round trip, not an upload it will throw away.
        if not self.server.job_lock.acquire(blocking=False):
            self._reply_json(409, {"error": "the worker is already running a job"})
            return

        try:
            body = self.rfile.read(length)
            if len(body) != length:
                self._reply_json(400, {"error": "job body was truncated in transit"})
                return
            try:
                spec, snapshot = proto.unframe_job(body)
            except Exception as e:
                self._reply_json(400, {"error": f"malformed job: {e}"})
                return
            if spec.get("protocol") != proto.PROTOCOL_VERSION:
                self._reply_json(400, {
                    "error": f"client speaks protocol {spec.get('protocol')}, "
                             f"this worker speaks {proto.PROTOCOL_VERSION}"})
                return
            if spec.get("kind") not in proto.JOB_KINDS:
                self._reply_json(400, {"error": f"unknown job kind {spec.get('kind')!r}"})
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            sink = EventSink(self.wfile)
            if self.config.verbose:
                sys.stderr.write(f"job {spec.get('kind')} "
                                 f"({len(snapshot)} snapshot bytes) from "
                                 f"{self.address_string()}\n")
            JobRunner(self.config, spec, snapshot, sink).run()
        finally:
            self.server.job_lock.release()
            if self.config.once:
                threading.Thread(target=self.server.shutdown, daemon=True).start()


class WorkerServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, config):
        self.config = config
        self.job_lock = threading.Lock()
        super().__init__(addr, WorkerHandler)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _check_job_root(path: Path):
    """Prove the job root is writable NOW, or say why it is not.

    The shipped sandbox profile grants write to exactly one directory:
    `WORKER_ROOT/.worker-jobs`. A `--job-root` pointing anywhere else is
    perfectly legal unsandboxed and fails on the first job under the sandbox —
    which is the worst moment to discover it, since the client sees a job that
    accepted and then died. So the daemon finds out at startup instead.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return (f"the job root {path} is not writable ({e}).\n"
                f"  Under the shipped sandbox profile the only writable "
                f"directory is <WORKER_ROOT>/.worker-jobs; either drop "
                f"--job-root or edit tools/test_worker.sb to match.")
    return None


def _init_token(path: Path) -> int:
    if path.exists() and path.read_text(encoding="utf-8").strip():
        print(f"a token already exists at {path} — leaving it alone")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    token = os.urandom(32).hex()
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"wrote a new worker token to {path}")
    print("copy the same value to the CLIENT machine at that path "
          "(or export SAW_WORKER_TOKEN):")
    print(f"  {token}")
    return 0


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bind", default=f"0.0.0.0:{proto.DEFAULT_PORT}",
                    metavar="HOST:PORT")
    ap.add_argument("--job-root", default=str(here / ".worker-jobs"),
                    help="where per-job directories are created and purged")
    ap.add_argument("--venv", default=str(here / ".venv" / "bin" / "python"),
                    help="the interpreter jobs run under")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--job-timeout", type=float, default=3600.0, metavar="SECS")
    ap.add_argument("--once", action="store_true",
                    help="serve one job, then exit (the self-test uses this)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--init-token", action="store_true",
                    help="create the token file if absent, print it, and exit")
    ap.add_argument("--check-profile", metavar="PATH", default=None,
                    help="compile a sandbox profile, report, and exit")
    ap.add_argument("--print-port-file", metavar="PATH", default=None,
                    help="write the bound port to PATH once listening")
    args = ap.parse_args()

    if args.check_profile:
        problem = compile_profile(Path(args.check_profile))
        if problem:
            print(f"sandbox profile REJECTED by the OS:\n{problem}")
            return 1
        print(f"sandbox profile compiles: {args.check_profile}")
        return 0

    token_path = Path(args.token_file) if args.token_file else proto.DEFAULT_TOKEN_FILE
    if args.init_token:
        return _init_token(token_path)

    token = proto.load_token(args.token_file)
    if not token:
        print(f"refusing to start: no token. Create one with\n"
              f"  {sys.executable} {__file__} --init-token"
              + (f" --token-file {args.token_file}" if args.token_file else ""),
              file=sys.stderr)
        return 2

    host, _, port = args.bind.rpartition(":")
    config = argparse.Namespace(
        token=token, job_root=args.job_root, venv=args.venv,
        job_timeout=args.job_timeout, verbose=args.verbose, once=args.once)

    problem = _check_job_root(Path(args.job_root))
    if problem:
        print(f"refusing to start: {problem}", file=sys.stderr)
        return 2
    if not Path(args.venv).exists():
        print(f"warning: {args.venv} does not exist — jobs will fail. "
              f"Create the worker venv or pass --venv.", file=sys.stderr)

    server = WorkerServer((host or "0.0.0.0", int(port)), config)
    bound_port = server.socket.getsockname()[1]
    if args.print_port_file:
        Path(args.print_port_file).write_text(str(bound_port), encoding="utf-8")

    confined = sandbox_active()
    print(f"saw test worker on {host or '0.0.0.0'}:{bound_port} "
          f"({os.cpu_count()} cores, protocol {proto.PROTOCOL_VERSION})")
    print(f"  jobs run under {args.venv}, in {args.job_root} (purged per job)")
    if confined:
        print("  sandbox: ACTIVE — this process and its job children are confined")
    else:
        print("  sandbox: NOT ACTIVE — jobs will run with this account's full "
              "privileges.\n"
              "  Relaunch under the shipped profile:\n"
              "    sandbox-exec -D WORKER_ROOT=\"$PWD\" "
              "-f tools/test_worker.sb \\\n"
              f"      {args.venv} tools/test_worker.py --bind {args.bind}")
    sys.stdout.flush()

    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

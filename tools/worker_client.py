#!/usr/bin/env python3
"""Client side of the remote test worker (design 160).

Everything here is written to one rule: **a broken worker costs a note, never a
verdict.** A gate run that goes red because a machine on the other side of the
house was rebooting is worse than useless — it trains you to ignore red. So no
method on `RemoteWorker` raises for anything the network can do to it. They
return notes, and the caller runs the work locally instead.

The failures that must all degrade the same way:

* the host is down, or nothing is listening on the port;
* the token is wrong, or absent on either side;
* the worker is already running someone else's job;
* the connection dies halfway through a shard;
* the worker stops sending anything at all (it is wedged, or the network
  swallowed it) — caught by the heartbeat, not by a total-runtime cap, since
  a slow gate is not a dead one.

The caller learns which tests it did NOT get verdicts for and runs those
itself. That is the whole degradation story: no retries, no failover, no
waiting on a machine that has stopped answering.
"""

import http.client
import json
import socket
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker_proto as proto  # noqa: E402


@dataclass
class WorkerInfo:
    """What `/health` said about the worker."""
    cores: int
    host: str
    protocol: int
    sandboxed: bool
    busy: bool
    url: str

    def describe(self) -> str:
        confined = "sandboxed" if self.sandboxed else "NOT sandboxed"
        return f"{self.host} at {self.url} ({self.cores} cores, {confined})"


@dataclass
class RemoteRun:
    """The outcome of one submitted job."""
    completed: bool = False          # the worker said `done`
    ok: bool = True                  # ...and reported success
    events: int = 0
    notes: list = field(default_factory=list)
    seconds: float = 0.0

    def note(self, text: str) -> None:
        self.notes.append(text)


def parse_url(url: str) -> tuple:
    """`host:port`, `http://host:port`, or a bare host -> (host, port)."""
    text = url if "//" in url else "//" + url
    parts = urllib.parse.urlsplit(text, scheme="http")
    if not parts.hostname:
        raise ValueError(f"cannot parse worker address {url!r}")
    return parts.hostname, parts.port or proto.DEFAULT_PORT


class RemoteWorker:
    def __init__(self, url: str, token: str, connect_timeout: float = 10.0):
        self.url = url
        self.token = token
        self.connect_timeout = connect_timeout
        self.host, self.port = parse_url(url)

    # -- health ------------------------------------------------------------

    def probe(self):
        """`(WorkerInfo, None)` if the worker is usable, `(None, why)` if not.

        Called before any snapshot is built, so an unreachable worker costs a
        connect timeout rather than the seconds it takes to tar the tree.
        """
        try:
            conn = http.client.HTTPConnection(self.host, self.port,
                                              timeout=self.connect_timeout)
            conn.request("GET", "/health", headers=self._headers())
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
        except (OSError, socket.timeout, http.client.HTTPException) as e:
            return None, f"worker {self.url} is unreachable ({e})"

        if resp.status == 401:
            return None, (f"worker {self.url} refused the token — check "
                          f"{proto.DEFAULT_TOKEN_FILE} on both machines")
        if resp.status != 200:
            return None, f"worker {self.url} answered /health with {resp.status}"
        try:
            info = json.loads(body)
        except ValueError:
            return None, f"worker {self.url} sent an unreadable /health reply"
        if info.get("protocol") != proto.PROTOCOL_VERSION:
            return None, (f"worker {self.url} speaks protocol "
                          f"{info.get('protocol')}, this client speaks "
                          f"{proto.PROTOCOL_VERSION} — update one of them")
        if info.get("busy"):
            return None, f"worker {self.url} is already running a job"
        return WorkerInfo(cores=int(info.get("cores", 1)),
                          host=str(info.get("host", self.host)),
                          protocol=int(info.get("protocol", 0)),
                          sandboxed=bool(info.get("sandboxed")),
                          busy=False, url=self.url), None

    # -- jobs --------------------------------------------------------------

    def submit(self, spec: dict, snapshot: bytes, handlers: dict) -> RemoteRun:
        """Run one job, dispatching each streamed event to `handlers[name]`.

        `handlers` maps an event name to a callable taking the event dict.
        Events nobody handles are ignored, so a newer worker adding an event
        does not break an older client.
        """
        run = RemoteRun()
        started = time.monotonic()
        body = proto.frame_job(dict(spec, protocol=proto.PROTOCOL_VERSION),
                               snapshot)
        conn = resp = None
        try:
            conn = http.client.HTTPConnection(self.host, self.port,
                                              timeout=self.connect_timeout)
            headers = self._headers()
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Length"] = str(len(body))
            conn.request("POST", "/job", body=body, headers=headers)
            # Hold the socket now. The response says `Connection: close`, so
            # `getresponse` hands the socket to the response object and clears
            # `conn.sock` — leaving no way to reach it afterwards, and the
            # connect timeout still armed on every read of a stream that is
            # SUPPOSED to go quiet between verdicts.
            sock = conn.sock
            resp = conn.getresponse()
            if resp.status != 200:
                detail = _short(resp.read())
                run.note(f"worker {self.url} refused the job "
                         f"({resp.status}: {detail})")
                return run
            # From here on the worker sends a heartbeat every HEARTBEAT_SECS,
            # so silence for several of them means the worker is gone — not
            # that the gate is slow. This is the only timeout on a running job.
            if sock is not None:
                sock.settimeout(proto.STREAM_IDLE_TIMEOUT)
            self._consume(resp, handlers, run)
        except (OSError, socket.timeout, http.client.HTTPException) as e:
            run.note(f"the connection to {self.url} broke mid-job ({e})")
        finally:
            run.seconds = time.monotonic() - started
            for closeable in (resp, conn):
                try:
                    if closeable is not None:
                        closeable.close()
                except OSError:
                    pass
        if not run.completed and not run.notes:
            run.note(f"worker {self.url} closed the stream without finishing "
                     f"the job")
        return run

    def _consume(self, resp, handlers: dict, run: RemoteRun) -> None:
        while True:
            line = resp.readline()
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                run.note(f"worker {self.url} sent a line that is not an event: "
                         f"{_short(line)}")
                continue
            run.events += 1
            name = event.get("event")
            if name == "ping":
                continue
            if name == "error":
                run.note(f"worker {self.url}: {event.get('message')}")
                run.ok = False
                continue
            if name == "done":
                run.completed = True
                run.ok = run.ok and bool(event.get("ok"))
                handler = handlers.get("done")
                if handler:
                    handler(event)
                return
            handler = handlers.get(name)
            if handler:
                handler(event)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/x-ndjson"}


def _short(blob, limit: int = 200) -> str:
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8", "replace")
    blob = " ".join(blob.split())
    return blob[:limit]


# ---------------------------------------------------------------------------
# Connecting a worker, start to finish
# ---------------------------------------------------------------------------

def connect(url: str, token_file=None, connect_timeout: float = 10.0):
    """`(RemoteWorker, WorkerInfo, None)` or `(None, None, why)`.

    The one call a caller needs before deciding how to split its work: it
    resolves the token, reaches the worker, and checks the protocol. Every
    reason it can fail comes back as prose meant to be printed verbatim next to
    the run's summary.
    """
    token = proto.load_token(token_file)
    if not token:
        return None, None, (
            f"no worker token: put the shared secret in "
            f"{proto.DEFAULT_TOKEN_FILE} or set {proto.TOKEN_ENV}")
    try:
        worker = RemoteWorker(url, token, connect_timeout)
    except ValueError as e:
        return None, None, str(e)
    info, why = worker.probe()
    if info is None:
        return None, None, why
    return worker, info, None


def snapshot(root: Path):
    """`(bytes, None)` or `(None, why)` — packing the tree must not raise."""
    try:
        return proto.build_snapshot(Path(root)), None
    except Exception as e:
        return None, f"could not snapshot the tree for the worker ({e})"

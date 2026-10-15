#!/usr/bin/env python3
"""The seed's one funnel, `build.seed_blob`, against a blob host of its own.

    python compiler/tests/seed/test_seed_store.py

`compiler/tests/run.py` runs `run()`. Each case builds a small seed of the
host's target, a driver that exits with a value its one runtime module
returns, through `build.build_seed`, with the manifest, the blob cache and the
seed cache under `.build/` and the blob host a local HTTP server, so nothing
reaches the real host. The cases:

- a cold cache builds the seed from fetched blobs, and the binary runs;
- a warm cache builds with the fetch URL an unroutable address;
- a corrupted cache entry is detected and fetched again, or, with no host,
  fails naming the file;
- a manifest hash that matches no blob, a fetched file of the wrong size or
  hash, and a host that refuses the connection each fail naming the file,
  the URL and the expected SHA-256;
- a malformed or misordered manifest is refused, naming the manifest;
- `seed.check_path_free` reads the seed through the funnel;
- `seed.publish` uploads a new file and fetches it back, keeps the line of
  a file whose IR is unchanged in other xz bytes, and refuses without a key.
"""
import contextlib
import hashlib
import http.server
import io
import lzma
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402
import seed  # noqa: E402

WORK = os.path.join(REPO, ".build", "seed-store-test")
# TEST-NET-1 (RFC 5737): nothing answers there, so a fetch could only time out.
UNROUTABLE = "http://192.0.2.1/"
EXIT_VALUE = 42

DRIVER_IR = b"""declare i32 @seed_value()

define i32 @main() {
  %v = call i32 @seed_value()
  ret i32 %v
}
"""
# The one runtime symbol runtime/shim.c calls, beside the value.
RUNTIME_IR = b"""define i32 @seed_value() {
  ret i32 %d
}

define void @__saw_rt_dealloc(ptr %%p, i64 %%size, i64 %%align) {
  ret void
}
""" % EXIT_VALUE


class Host:
    """A blob host on 127.0.0.1: serves `blobs` ({name: bytes}), then the
    files of `directory`, and counts the requests for each name."""

    def __init__(self, directory):
        self.blobs = {}
        self.directory = directory
        self.requests = {}
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                name = self.path.lstrip("/")
                host.requests[name] = host.requests.get(name, 0) + 1
                data = host.blobs.get(name)
                path = os.path.join(host.directory, name)
                if data is None and "/" not in name and os.path.isfile(path):
                    with open(path, "rb") as fh:
                        data = fh.read()
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        class Server(http.server.ThreadingHTTPServer):
            def server_bind(self):
                # HTTPServer's own looks its name up in DNS, which a sandbox
                # can leave to time out.
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

        self.server = Server(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url():
    """A URL on 127.0.0.1 whose port nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return "http://127.0.0.1:%d/" % port


def xz(data, preset=6):
    return lzma.compress(data, format=lzma.FORMAT_XZ, preset=preset)


def entry_of(triple, name, data):
    return build.SeedFile(triple, name, hashlib.sha256(data).hexdigest(), len(data))


class Case:
    def __init__(self, failures, counts):
        self.failures = failures
        self.counts = counts

    def check(self, name, ok, detail=""):
        self.counts["seed store cases"] = self.counts.get("seed store cases", 0) + 1
        if not ok:
            self.failures.append("seed store: %s%s" % (name, ": " + detail if detail else ""))


def write_manifest(entries):
    with open(build.SEED_MANIFEST, "w", encoding="utf-8") as fh:
        fh.write(build.format_seed_manifest({entries[0].triple: entries}, [entries[0].triple]))


def fresh_seed_cache():
    shutil.rmtree(build.SEED_CACHE, ignore_errors=True)


def build_and_run(case, name):
    """build_seed's binary run, or None; a failure is recorded under `name`."""
    binary, why = build.build_seed()
    if binary is None:
        case.check(name, False, "build_seed refuses: %s" % why)
        return None
    r = subprocess.run([binary], capture_output=True, timeout=60)
    case.check(name, r.returncode == EXIT_VALUE, "the seed exits %d, not %d" % (r.returncode, EXIT_VALUE))
    return binary


def expect_refusal(case, name, entry, url, *needles):
    """build_seed refuses with a text naming `entry`'s file, `url` and its
    SHA-256, and each of `needles`."""
    fresh_seed_cache()
    binary, why = build.build_seed()
    wanted = ("%s/%s" % (entry.triple, entry.name), url.rstrip("/") + "/" + entry.sha256, entry.sha256) + needles
    missing = [n for n in wanted if n not in why]
    case.check(name, binary is None and not missing,
               "built %s" % binary if binary else "the refusal lacks %r: %s" % (missing, why))


def cases(case, host, triple):
    driver_xz, runtime_xz = xz(DRIVER_IR), xz(RUNTIME_IR)
    driver = entry_of(triple, build.SEED_DRIVER, driver_xz)
    runtime = entry_of(triple, "runtime/common/value.ll.xz", runtime_xz)
    host.blobs = {driver.sha256: driver_xz, runtime.sha256: runtime_xz}
    write_manifest([driver, runtime])
    os.environ[build.BLOB_URL_VARIABLE] = host.url

    binary = build_and_run(case, "a cold cache builds the seed from fetched blobs")
    case.check("a cold cache fetches each file once",
               host.requests == {driver.sha256: 1, runtime.sha256: 1}, repr(host.requests))
    case.check("a fetched file is cached under its SHA-256",
               all(os.path.isfile(os.path.join(build.BLOB_CACHE, e.sha256)) for e in (driver, runtime)))

    os.environ[build.BLOB_URL_VARIABLE] = UNROUTABLE
    again, why = build.build_seed()
    case.check("a warm seed cache needs no network", again == binary and binary is not None, why)
    fresh_seed_cache()
    build_and_run(case, "a warm blob cache builds the seed with no network")
    case.check("a warm blob cache fetches nothing", sum(host.requests.values()) == 2, repr(host.requests))

    cached = os.path.join(build.BLOB_CACHE, driver.sha256)
    with open(cached, "r+b") as fh:
        fh.seek(100)
        byte = fh.read(1)
        fh.seek(100)
        fh.write(bytes([byte[0] ^ 0xFF]))
    fresh_seed_cache()
    note = io.StringIO()
    with contextlib.redirect_stderr(note):
        expect_refusal(case, "a corrupted cache entry with no host fails naming the file", driver, UNROUTABLE,
                       "the fetch fails")
    case.check("a corrupted cache entry is reported", "has SHA-256" in note.getvalue(), note.getvalue())
    os.environ[build.BLOB_URL_VARIABLE] = host.url
    with contextlib.redirect_stderr(io.StringIO()):
        build_and_run(case, "a corrupted cache entry is fetched again")
    case.check("the refetch restores the cache entry", build._blob_problem(cached, driver) == "")
    case.check("the refetch is one request", host.requests.get(driver.sha256) == 2, repr(host.requests))

    missing = entry_of(triple, build.SEED_DRIVER, b"no blob has these bytes")
    write_manifest([missing, runtime])
    expect_refusal(case, "a manifest hash that matches no blob fails", missing, host.url, "404")

    short = driver._replace(size=driver.size + 1)
    write_manifest([short, runtime])
    shutil.rmtree(build.BLOB_CACHE)
    expect_refusal(case, "a fetched file of the wrong size fails", short, host.url,
                   "is %d bytes, not %d" % (driver.size, short.size))

    wrong = entry_of(triple, build.SEED_DRIVER, b"x" * driver.size)
    host.blobs[wrong.sha256] = driver_xz
    write_manifest([wrong, runtime])
    expect_refusal(case, "a fetched file of the wrong SHA-256 fails", wrong, host.url,
                   "has SHA-256 %s" % driver.sha256)
    case.check("a file that fails its check is not cached",
               not os.path.exists(os.path.join(build.BLOB_CACHE, wrong.sha256))
               and not [n for n in os.listdir(build.BLOB_CACHE) if n.endswith(".part")])

    write_manifest([driver, runtime])
    shutil.rmtree(build.BLOB_CACHE)
    refused = closed_port_url()
    os.environ[build.BLOB_URL_VARIABLE] = refused
    expect_refusal(case, "a host that refuses the connection fails", driver, refused, "the fetch fails")

    with open(build.SEED_MANIFEST, "a", encoding="utf-8") as fh:
        fh.write("%s\tsawc2.ll\t%s\t1\n" % (triple, driver.sha256))
    binary, why = build.build_seed()
    case.check("a malformed manifest line is refused",
               binary is None and "manifest.tsv:" in why and "is not" in why, why)
    write_manifest([runtime, driver])
    binary, why = build.build_seed()
    case.check("a misordered manifest is refused", binary is None and "the order is" in why, why)


def path_free_cases(case, host, triple):
    pathful = xz(RUNTIME_IR + b'@where = constant [9 x i8] c"/Users/a/b"\n')
    driver = entry_of(triple, build.SEED_DRIVER, xz(DRIVER_IR))
    runtime = entry_of(triple, "runtime/common/value.ll.xz", pathful)
    host.blobs = {driver.sha256: xz(DRIVER_IR), runtime.sha256: pathful}
    write_manifest([driver, runtime])
    os.environ[build.BLOB_URL_VARIABLE] = host.url
    failures, counts = [], {}
    seed.check_path_free(failures, counts)
    case.check("seed.check_path_free reads each file through the funnel",
               counts.get("seed files path-free") == 2 and len(failures) == 1
               and "%s/runtime/common/value.ll.xz holds an absolute path: /Users/a/b" % triple in failures[0],
               repr(failures))


def publish_cases(case, host, triple):
    driver_xz = xz(DRIVER_IR)
    driver = entry_of(triple, build.SEED_DRIVER, driver_xz)
    runtime = entry_of(triple, "runtime/common/value.ll.xz", xz(RUNTIME_IR))
    host.blobs = {driver.sha256: driver_xz, runtime.sha256: xz(RUNTIME_IR)}
    write_manifest([driver, runtime])
    os.environ[build.BLOB_URL_VARIABLE] = host.url

    staged = os.path.join(seed.STAGING, triple)
    os.makedirs(os.path.join(staged, "runtime", "common"))
    recompressed = xz(DRIVER_IR, preset=0)
    changed_ir = RUNTIME_IR.replace(b"ret i32 %d" % EXIT_VALUE, b"ret i32 7")
    for name, data in ((build.SEED_DRIVER, recompressed), ("runtime/common/value.ll.xz", xz(changed_ir))):
        with open(os.path.join(staged, name), "wb") as fh:
            fh.write(data)
    with open(os.path.join(staged, seed.STAGED_COMMIT), "w", encoding="utf-8") as fh:
        fh.write("0" * 40 + "\n")

    os.environ[seed.UPLOAD_KEY_VARIABLE] = os.path.join(WORK, "no-such-key")
    why = seed.publish([triple])
    case.check("publish without the upload key refuses, naming it",
               seed.UPLOAD_KEY_VARIABLE in why and "no-such-key" in why, why)

    for variable in (seed.UPLOAD_KEY_VARIABLE, seed.KNOWN_HOSTS_VARIABLE):
        path = os.path.join(WORK, variable.lower())
        with open(path, "w") as fh:
            fh.write("a stand-in: the upload goes to a local directory\n")
        os.environ[variable] = path
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        why = seed.publish([triple])
    case.check("publish uploads a new file and fetches it back", why == "", why)
    manifest = build.seed_manifest()[triple]
    new = entry_of(triple, "runtime/common/value.ll.xz", xz(changed_ir))
    case.check("an unchanged IR keeps its manifest line in other xz bytes", manifest[0] == driver, repr(manifest))
    case.check("a changed IR gets a new line", manifest[1:] == [new], repr(manifest))
    case.check("only the changed file is uploaded", sorted(os.listdir(host.directory)) == [new.sha256],
               repr(os.listdir(host.directory)))
    case.check("the upload is fetched back", host.requests.get(new.sha256) == 1, repr(host.requests))
    case.check("publish pins the emitted commit", seed.read_pin() == "0" * 40, repr(seed.read_pin()))


def run():
    """([failure], {count: n})."""
    failures, counts = [], {}
    case = Case(failures, counts)
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    hostdir = os.path.join(WORK, "host")
    os.makedirs(hostdir)
    saved = {name: getattr(build, name) for name in ("SEED_MANIFEST", "BLOB_CACHE", "SEED_CACHE", "FETCH_TIMEOUT")}
    saved_seed = {name: getattr(seed, name) for name in ("STAGING", "PIN", "UPLOAD_DESTINATION")}
    variables = (build.BLOB_URL_VARIABLE, seed.UPLOAD_KEY_VARIABLE, seed.KNOWN_HOSTS_VARIABLE)
    saved_env = {name: os.environ.get(name) for name in variables}
    host = Host(hostdir)
    try:
        build.SEED_MANIFEST = os.path.join(WORK, "manifest.tsv")
        build.BLOB_CACHE = os.path.join(WORK, "blobs")
        build.SEED_CACHE = os.path.join(WORK, "seed")
        build.FETCH_TIMEOUT = 2
        seed.STAGING = os.path.join(WORK, "seed-write")
        seed.PIN = os.path.join(WORK, "pin")
        seed.UPLOAD_DESTINATION = hostdir + "/"
        triple = build.host_triple()
        cases(case, host, triple)
        shutil.rmtree(build.BLOB_CACHE, ignore_errors=True)
        path_free_cases(case, host, triple)
        shutil.rmtree(build.BLOB_CACHE, ignore_errors=True)
        host.requests = {}
        publish_cases(case, host, triple)
    finally:
        host.close()
        for name, value in saved.items():
            setattr(build, name, value)
        for name, value in saved_seed.items():
            setattr(seed, name, value)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if not failures:
        shutil.rmtree(WORK, ignore_errors=True)
    return failures, counts


def main():
    failures, counts = run()
    for failure in failures:
        print(failure)
    print("seed store: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                  ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

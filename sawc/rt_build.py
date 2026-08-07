"""Build + cache the per-host Saw runtime (design 113b).

Hosted builds no longer get the `__saw_rt_*` seam bodies synthesized in LLVM IR
by codegen; the bodies live as Saw sources under `sawc/rt/` (common/ +
host_macos/ or host_linux/), compiled with `sawc --runtime-build`, plus one
small `shim.c` for the three FFI-blocked bodies (DF-113a/b/c). This module
compiles those sources into object files under `.build/rt/<key>/` and returns
them so the driver can add them to a hosted link line.

The cache key is a hash of every runtime source (the .saw files + shim.c) plus
the target triple and this file, so a stale runtime after an edit is impossible
— change any source and the key changes, forcing a rebuild into a fresh dir.
Concurrency-safe: the build runs under an exclusive `flock`, so parallel `sawc`
invocations (the test runner) never race — the first builds, the rest reuse.
A failure to build the runtime is a hard error naming the failing source.
"""

import hashlib
import os
import subprocess
import sys


class RuntimeBuildError(Exception):
    """The runtime itself failed to build — hosted linking cannot proceed."""


def _rt_root() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rt")


def _host_dir(triple: str) -> str:
    t = (triple or "").lower()
    apple = any(k in t for k in ("apple", "darwin", "macos", "ios"))
    return "host_macos" if apple else "host_linux"


def _runtime_sources(triple: str):
    """(saw_sources, shim_c) for `triple`: every .saw under rt/common and the
    selected rt/host_<os>, plus rt/shim.c."""
    root = _rt_root()
    saw = []
    for sub in ("common", _host_dir(triple)):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".saw"):
                    saw.append(os.path.join(d, fn))
    shim = os.path.join(root, "shim.c")
    return saw, shim


def _compiler_and_lang_inputs() -> list:
    """Every non-rt input whose change can alter the built runtime's ABI:
    the whole compiler tree (codegen decides layout), builtin.saw, and all of
    std (runtime sources compile against their declarations, and a program
    built with a NEW std layout linking rt objects built against an OLD one
    hangs with no compile error — DF-165a). A curated subset is the bug class
    this key exists to prevent; hashing the lot costs single-digit ms."""
    sawc_dir = os.path.dirname(os.path.abspath(__file__))
    inputs = []
    for dirpath, _dirnames, filenames in os.walk(sawc_dir):
        rel = os.path.relpath(dirpath, sawc_dir)
        if rel.split(os.sep)[0] in ("rt", "__pycache__"):
            continue
        for fn in filenames:
            if fn.endswith(".py") or fn.endswith(".saw"):
                inputs.append(os.path.join(dirpath, fn))
    return sorted(inputs)


def _cache_key(saw_sources, shim_c, triple: str) -> str:
    h = hashlib.sha256()
    h.update(b"saw-rt-v2\0")
    h.update((triple or "").encode() + b"\0")
    # The key covers every input that can change what the built runtime IS:
    # rt sources + shim, the compiler tree, builtin.saw and std (DF-165a).
    for path in _compiler_and_lang_inputs() + sorted(saw_sources) + [shim_c]:
        h.update(path.encode() + b"\0")
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()[:16]


def _build_dir_root() -> str:
    # `.build/rt/` under the COMPILER checkout (anchored via __file__, exactly
    # like the runtime sources above), NOT the caller's cwd: sawc is invoked
    # from arbitrary directories (blade package builds), where a cwd-relative
    # cache would rebuild per directory, need write access wherever the user
    # happens to stand, and collide with unrelated `.build/rt` entries (a stale
    # scratch binary named `rt` broke every repo-root compile during 113b
    # verification).
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, ".build", "rt")


def _do_build(build_dir: str, saw_sources, shim_c, triple: str, verbose: bool):
    """Compile every runtime source into `build_dir`. Raises RuntimeBuildError
    on any failure. Returns the list of produced object paths."""
    import fcntl  # POSIX; the hosted runtime is macOS/Linux only

    os.makedirs(build_dir, exist_ok=True)
    objects = []
    sawc_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sawc.py")

    # Compile each .saw with `sawc --runtime-build` (object output).
    for src in saw_sources:
        obj = os.path.join(build_dir, os.path.splitext(os.path.basename(src))[0] + ".o")
        cmd = [sys.executable, sawc_py, src, "-o", obj, "--runtime-build"]
        if triple:
            cmd += ["--target", triple]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(obj):
            raise RuntimeBuildError(
                f"runtime source `{src}` failed to compile:\n"
                f"{(res.stdout + res.stderr).strip()}")
        objects.append(obj)

    # Compile the C shim with clang.
    if os.path.exists(shim_c):
        shim_obj = os.path.join(build_dir, "shim.o")
        cmd = ["clang", "-c", shim_c, "-o", shim_obj, "-O2", "-fno-strict-aliasing"]
        if triple:
            cmd += ["-target", triple]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(shim_obj):
            raise RuntimeBuildError(
                f"runtime shim `{shim_c}` failed to compile:\n"
                f"{(res.stdout + res.stderr).strip()}")
        objects.append(shim_obj)

    return objects


def build_runtime(triple: str, verbose: bool = False):
    """Return the list of runtime object files for `triple`, building + caching
    them under `.build/rt/<key>/` if not already present. Raises
    RuntimeBuildError if the runtime fails to build."""
    import fcntl

    saw_sources, shim_c = _runtime_sources(triple)
    key = _cache_key(saw_sources, shim_c, triple)
    final_dir = os.path.join(_build_dir_root(), key)
    ok_marker = os.path.join(final_dir, ".ok")
    manifest = os.path.join(final_dir, "objects.txt")

    def _read_manifest():
        with open(manifest) as f:
            return [ln.strip() for ln in f if ln.strip()]

    if os.path.exists(ok_marker) and os.path.exists(manifest):
        return _read_manifest()

    os.makedirs(_build_dir_root(), exist_ok=True)
    lock_path = os.path.join(_build_dir_root(), key + ".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Re-check under the lock: another process may have built it while we waited.
        if os.path.exists(ok_marker) and os.path.exists(manifest):
            return _read_manifest()
        if verbose:
            print(f"  Building Saw runtime ({_host_dir(triple)}) -> {final_dir}")
        objects = _do_build(final_dir, saw_sources, shim_c, triple, verbose)
        with open(manifest, "w") as f:
            f.write("\n".join(os.path.abspath(o) for o in objects) + "\n")
        with open(ok_marker, "w") as f:
            f.write(key + "\n")
        return [os.path.abspath(o) for o in objects]

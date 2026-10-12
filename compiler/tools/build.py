#!/usr/bin/env python3
"""Build the self-hosted compiler: Stage 1 with the frozen compiler, Stage 2
with Stage 1.

    python compiler/tools/build.py                   # .build/sawc2, then .build/sawc2-stage2
    python compiler/tools/build.py ENTRY.saw -o OUT  # any program over the stages, by Stage 0
    python compiler/tools/build.py --runtime TRIPLE  # the stages, then another target's runtime

The numbering is the conventional one: Stage 0 is the frozen Python compiler
in `sawc/`, Stage 1 is the sawc2 it builds (`.build/sawc2`), and Stage 2 is
sawc2 built by Stage 1 at -O2 (`.build/sawc2-stage2`). The lanes run Stage 2;
`SAWC2_STAGE=1` selects Stage 1 instead, for bisecting a difference between
the two, and then Stage 2 is not built. `SAWC2` is the binary selected.

Stage 2 is cached: its key covers Stage 1's code, the sources Stage 1
compiles, this file, the runtime manifest and its objects and clang, so an
unchanged tree links nothing. Stage 1 is rebuilt on every call, as Stage 0
has no cache of its own. Stage 1 links against Stage 0's runtime, since Stage
0 links it; every link after that takes the runtime Stage 1 builds with
`sawc2 runtime`, cached under `.build/rt2/<key>/` by a key covering Stage 1's
code, `sawc/rt/`, std, the target and clang. Beside the stages goes
`.build/sawc2-runtime.txt`, the runtime manifest naming the host, the clang
`choose_clang` picked and those objects, which a hosted `sawc2 build` links
against.

The interpreter running this script runs `sawc/sawc.py`, so invoke it with the
venv's Python. `STAGE_PACKAGES` is the one place that maps a stage package to
its directory: the driver, the unit programs and the runner all build through
`build_program`, so a new stage is registered here once.
"""
import argparse
import fcntl
import hashlib
import os
import platform
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FROZEN_SAWC = os.path.join(REPO, "sawc", "sawc.py")
BUILD_DIR = os.path.join(REPO, ".build")
STAGE1 = os.path.join(BUILD_DIR, "sawc2")
# The file that stands for Stage 1's code in a cache key. On macOS it is the
# object Stage 0 links Stage 1 from and keeps beside it, since the linker
# stamps each Mach-O binary with a fresh UUID; on Linux Stage 0 removes the
# object, and the ELF binary, whose build ID is a hash of its contents, is as
# stable as the object.
STAGE1_CODE = STAGE1 + ".o" if sys.platform == "darwin" else STAGE1
STAGE2 = os.path.join(BUILD_DIR, "sawc2-stage2")
STAGE2_KEY = STAGE2 + ".key"
DRIVER_ENTRY = os.path.join(REPO, "compiler", "driver", "src", "main.saw")
# The runtime manifest a hosted `sawc2 build` reads beside its own binary: the
# host target and the runtime objects it links (compiler/tests/run/README.md).
RUNTIME_MANIFEST = os.path.join(BUILD_DIR, "sawc2-runtime.txt")
# The runtime's sources, and where the objects Stage 1 builds from them are
# cached by key.
RT_ROOT = os.path.join(REPO, "sawc", "rt")
RUNTIME_CACHE = os.path.join(BUILD_DIR, "rt2")
THIS_FILE = os.path.abspath(__file__)
STD_ROOT = os.path.join(REPO, "std")
LINK_TIMEOUT = 1800

# (package name, source directory relative to the repo root). The directory is
# the package's module root, as `--module-path NAME=DIR` defines it: the others
# import a stage as `<name>.<module>`, and `<name>` alone is its `lib.saw`.
STAGE_PACKAGES = (
    ("sawlex", "compiler/lex/src"),
    ("sawparse", "compiler/parse/src"),
    ("sawresolve", "compiler/resolve/src"),
    ("sawtypecheck", "compiler/typecheck/src"),
    ("sawtarget", "compiler/target/src"),
    ("sawasserts", "compiler/asserts/src"),
    ("sawmir", "compiler/mir/src"),
    ("saweval", "compiler/eval/src"),
    ("sawborrowck", "compiler/borrowck/src"),
    ("sawdrops", "compiler/drops/src"),
    ("sawmono", "compiler/mono/src"),
    ("sawcoro", "compiler/coro/src"),
    ("sawllvm", "compiler/llvm/src"),
)


def selected_stage():
    """The stage `SAWC2_STAGE` names, 2 when it is unset."""
    stage = os.environ.get("SAWC2_STAGE", "2")
    if stage not in ("1", "2"):
        sys.exit("build: SAWC2_STAGE is %r; it names Stage 1 or Stage 2" % stage)
    return int(stage)


SAWC2 = STAGE2 if selected_stage() == 2 else STAGE1


def sawc_arguments(entry, out):
    """The frozen compiler's command-line arguments for building `entry` to
    `out`: what `build_program` runs, and what `std_cone.py` runs in-process."""
    args = [entry, "-o", out]
    for name, rel in STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, os.path.join(REPO, rel))]
    return args


def package_arguments(root):
    """`--module-path` for every stage package, under the tree at `root`."""
    args = []
    for name, rel in STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, os.path.join(root, rel))]
    return args


def build_program(entry, out):
    """Compile `entry` to the executable `out` with Stage 0. Returns (ok,
    compiler output)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    argv = [sys.executable, FROZEN_SAWC] + sawc_arguments(entry, out)
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def link_driver(compiler, out):
    """The driver built and linked into `out` at -O2 by the sawc2 binary
    `compiler`, which reads the runtime manifest beside itself; the error
    text, or "" when it linked. Stage 2 and Stage 3 are both linked here, so
    the fixpoint compares two links made the same way."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run([compiler, "build", "-O2", "--std-root", "std"] + package_arguments(REPO)
                       + [os.path.relpath(DRIVER_ENTRY, REPO), "-o", out], cwd=REPO,
                       capture_output=True, text=True, timeout=LINK_TIMEOUT)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip()[-600:] or "it exited %d" % r.returncode
    return ""


def host_triple():
    """The sawc2 target of the machine this runs on, which the runtime
    manifest beside the stages names and a hosted `sawc2 build` links for."""
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine == "arm64":
        return "arm64-apple-darwin"
    if sys.platform.startswith("linux") and machine in ("aarch64", "arm64"):
        return "aarch64-unknown-linux-gnu"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "x86_64-unknown-linux-gnu"
    sys.exit("build: no sawc2 target describes this host (%s, %s)" % (sys.platform, machine))


def clang_triple(triple):
    """The triple clang is told for a sawc2 target: `target_clang_triple` in
    compiler/target/src/layout.saw, which the two must agree with."""
    return "arm64-apple-macosx11.0.0" if triple == "arm64-apple-darwin" else triple


# The clangs tried when `SAWC2_CLANG` names none, in order: the versioned
# names a Linux distribution installs beside an older default, then `clang`.
CLANG_CANDIDATES = ("clang-19", "clang-18", "clang-17", "clang-16", "clang-15", "clang")
# The capability every clang sawc2 hands its `.ll` to must have: opaque
# pointers (`ptr`), which sawc2 emits throughout and LLVM 15 made the default.
# The module is compiled rather than a version parsed, since Apple's clang
# numbers its versions apart from LLVM's.
OPAQUE_POINTER_MODULE = "define ptr @f(ptr %p) {\n  ret ptr %p\n}\n"
CLANG_REQUIREMENT = "sawc2's .ll needs a clang that compiles opaque-pointer IR (`ptr`): LLVM 15 or later"
_CHOSEN_CLANGS = {}


def choose_clang(triple):
    """The clang every sawc2 compile and link for `triple` uses: `SAWC2_CLANG`,
    else the first of `CLANG_CANDIDATES` on `PATH` that compiles
    `OPAQUE_POINTER_MODULE` for the target. Returns (absolute path, "") or
    (None, why none qualifies). The runtime manifest records the choice, and
    everything after reads it there: `sawc2 build`'s link, `sawc2 runtime`
    run without `--clang`, and `stage2_key`.

    ENTRY POINTS:
      build_runtime
    """
    if triple in _CHOSEN_CLANGS:
        return _CHOSEN_CLANGS[triple]
    named = os.environ.get("SAWC2_CLANG")
    candidates = [named] if named else list(CLANG_CANDIDATES)
    refused = []
    answer = None
    for candidate in candidates:
        path = shutil.which(candidate)
        if path is None:
            if named:
                refused.append("SAWC2_CLANG names %s, which is not an executable" % named)
            continue
        path = os.path.abspath(path)
        if clang_capable(path, triple):
            answer = (path, "")
            break
        refused.append("%s does not compile opaque-pointer IR (`ptr`) for %s" % (path, triple))
    if answer is None:
        tried = "SAWC2_CLANG" if named else "any of %s on PATH" % ", ".join(CLANG_CANDIDATES)
        answer = (None, "no clang qualifies (tried %s): %s. %s" % (tried, "; ".join(refused) or "none is installed",
                                                                    CLANG_REQUIREMENT))
    _CHOSEN_CLANGS[triple] = answer
    return answer


def clang_capable(clang, triple):
    """Whether `clang` compiles the opaque-pointer module for `triple`."""
    directory = os.path.join(BUILD_DIR, "clang-check")
    os.makedirs(directory, exist_ok=True)
    stem = os.path.join(directory, "%s-%d" % (triple, os.getpid()))
    with open(stem + ".ll", "w") as fh:
        fh.write(OPAQUE_POINTER_MODULE)
    try:
        r = subprocess.run([clang, "-c", "-target", clang_triple(triple), "-x", "ir", stem + ".ll", "-o", stem + ".o"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    finally:
        for path in (stem + ".ll", stem + ".o"):
            if os.path.exists(path):
                os.remove(path)


def clang_version(clang):
    return subprocess.run([clang, "--version"], capture_output=True, text=True).stdout


def runtime_key(triple, clang):
    """What the runtime Stage 1 builds for `triple` with `clang` is a function
    of: Stage 1's code (`STAGE1_CODE`, as for Stage 2's key), the runtime's
    sources and C shim, the std they compile against, the target and the
    clang. None when Stage 1's code is missing."""
    if not os.path.exists(STAGE1_CODE):
        return None
    digest = hashlib.sha256()
    digest.update(b"sawc2-runtime-v1\0")
    with open(STAGE1_CODE, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    for root in (RT_ROOT, STD_ROOT):
        _hash_tree(digest, root)
    digest.update(("%s\0%s\0" % (triple, clang)).encode("utf-8"))
    digest.update(clang_version(clang).encode("utf-8"))
    return digest.hexdigest()[:16]


def runtime_seam_problems(objects, triple):
    """Every way the external `__saw_rt_*` definitions of `objects`, as `nm`
    reads them, are not the ABI table's runtime seams each exactly once: the
    check `sawc2 runtime` makes from its own exports, made again on the bytes
    it wrote."""
    import runtime_table
    rows, _ = runtime_table.abi_rows()
    wanted = set(name for name, _, _, owner in rows if owner == "runtime")
    seen = {}
    # Mach-O prefixes a C symbol with an underscore, and ELF does not.
    mach_o = triple.endswith("-apple-darwin")
    for path in objects:
        r = subprocess.run(["nm", "-g", "--defined-only", path], capture_output=True, text=True)
        if r.returncode != 0:
            return ["nm cannot read %s: %s" % (path, r.stderr.strip())]
        for line in r.stdout.splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[1] in ("T", "D", "S", "B", "R"):
                name = fields[2][1:] if mach_o and fields[2].startswith("_") else fields[2]
                if name.startswith("__saw_rt_"):
                    seen.setdefault(name, []).append(os.path.basename(path))
    problems = []
    for name in sorted(wanted - set(seen)):
        problems.append("no runtime object defines `%s`" % name)
    for name in sorted(seen):
        if name not in wanted:
            problems.append("%s defines `%s`, which is not a runtime seam" % (", ".join(seen[name]), name))
        elif len(seen[name]) > 1:
            problems.append("`%s` is defined by %s" % (name, ", ".join(seen[name])))
    return problems


def runtime_manifest(triple):
    """The runtime manifest a `sawc2 build` for `triple` reads beside its
    binary: `sawc2-runtime.txt` for the host, `sawc2-runtime-TRIPLE.txt` for
    another target (compiler/tests/run/README.md)."""
    if triple == host_triple():
        return RUNTIME_MANIFEST
    return os.path.join(BUILD_DIR, "sawc2-runtime-%s.txt" % triple)


def build_runtime(triple=None):
    """Stage 1's `sawc2 runtime` builds the runtime objects for `triple`, the
    host when None, into `.build/rt2/<key>/` with the clang `choose_clang`
    picks, unless that directory already holds the build of the same key, and
    the runtime manifest naming them is written beside the stages. Returns the
    error text, or "" when the manifest is written."""
    triple = triple or host_triple()
    clang, why = choose_clang(triple)
    if clang is None:
        return why
    key = runtime_key(triple, clang)
    if key is None:
        return "the runtime's key needs %s" % os.path.relpath(STAGE1_CODE, REPO)
    directory = os.path.join(RUNTIME_CACHE, key)
    done = os.path.join(directory, "manifest.txt")
    os.makedirs(RUNTIME_CACHE, exist_ok=True)
    # Two builds of one key in one checkout would remove each other's
    # half-built directory, so the build of a key holds its lock, and the
    # check for a finished one is repeated under it.
    with open(os.path.join(RUNTIME_CACHE, key + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(done):
            shutil.rmtree(directory, ignore_errors=True)
            os.makedirs(directory)
            r = subprocess.run([STAGE1, "runtime", "--rt-root", "sawc/rt", "--target", triple, "--clang", clang,
                                "--out", directory], cwd=REPO, capture_output=True, text=True, timeout=LINK_TIMEOUT)
            if r.returncode != 0:
                return "Stage 1 does not build the runtime: " + ((r.stdout + r.stderr).strip()[-600:]
                                                                  or "it exited %d" % r.returncode)
            objects = [line[len("object "):] for line in r.stdout.splitlines() if line.startswith("object ")]
            problems = runtime_seam_problems(objects, triple)
            if problems:
                return "the runtime Stage 1 built does not define the ABI's seams: " + "; ".join(problems)
            with open(done + ".tmp", "w") as fh:
                fh.write(r.stdout)
            os.replace(done + ".tmp", done)
    with open(done) as fh:
        manifest = fh.read()
    written = runtime_manifest(triple)
    old = None
    if os.path.exists(written):
        with open(written) as fh:
            old = fh.read()
    if old != manifest:
        with open(written + ".tmp", "w") as fh:
            fh.write(manifest)
        os.replace(written + ".tmp", written)
    return ""


def build_stage1():
    """Stage 0 builds the driver into `.build/sawc2`, linking it against Stage
    0's own runtime as every Stage 0 build does; then Stage 1 builds the
    runtime every later link takes, and its manifest is written beside the
    stages. Returns (ok, output)."""
    ok, output = build_program(DRIVER_ENTRY, STAGE1)
    if not ok:
        return ok, output
    why = build_runtime()
    if why:
        return False, "build: " + why
    return True, output


def _hash_tree(digest, root):
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(directory, name)
            digest.update(os.path.relpath(path, REPO).encode("utf-8") + b"\0")
            with open(path, "rb") as fh:
                digest.update(hashlib.sha256(fh.read()).digest())


def stage2_key():
    """What Stage 2 is a function of: Stage 1's code, the trees it compiles,
    this file (which holds the link's arguments), the runtime manifest and the
    objects it names, and the clang that links them. Stage 1's code is
    `STAGE1_CODE`. None when Stage 1's code or the manifest is missing."""
    if not os.path.exists(STAGE1_CODE):
        return None
    digest = hashlib.sha256()
    with open(STAGE1_CODE, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    for root in [os.path.join(REPO, rel) for _, rel in STAGE_PACKAGES] + [os.path.dirname(DRIVER_ENTRY),
                                                                          STD_ROOT]:
        _hash_tree(digest, root)
    with open(THIS_FILE, "rb") as fh:
        digest.update(fh.read())
    if not os.path.exists(RUNTIME_MANIFEST):
        return None
    with open(RUNTIME_MANIFEST, "rb") as fh:
        manifest = fh.read()
    digest.update(manifest)
    clang = None
    for line in manifest.decode("utf-8").split("\n"):
        if line.startswith("object "):
            with open(line[len("object "):], "rb") as fh:
                digest.update(hashlib.sha256(fh.read()).digest())
        elif line.startswith("clang "):
            clang = line[len("clang "):]
    if clang is None:
        return None
    digest.update(clang_version(clang).encode("utf-8"))
    return digest.hexdigest()


def build_stage2():
    """Stage 1 builds the driver into `.build/sawc2-stage2`, unless the cached
    link has the same key. Returns (ok, output)."""
    key = stage2_key()
    if key is None:
        return False, ("build: Stage 2's cache key needs %s and %s, and one is missing"
                       % (os.path.relpath(STAGE1_CODE, REPO), os.path.relpath(RUNTIME_MANIFEST, REPO)))
    if os.path.exists(STAGE2) and os.path.exists(STAGE2_KEY):
        with open(STAGE2_KEY) as fh:
            if fh.read().strip() == key:
                os.utime(STAGE2)
                return True, ""
    if os.path.exists(STAGE2_KEY):
        os.remove(STAGE2_KEY)
    why = link_driver(STAGE1, STAGE2)
    if why:
        return False, "Stage 1 does not build Stage 2: " + why
    with open(STAGE2_KEY + ".tmp", "w") as fh:
        fh.write(key + "\n")
    os.replace(STAGE2_KEY + ".tmp", STAGE2_KEY)
    return True, ""


def build_sawc2():
    """Build Stage 1, then Stage 2 unless Stage 1 is selected. Returns (ok,
    output)."""
    ok, output = build_stage1()
    if not ok or SAWC2 == STAGE1:
        return ok, output
    ok2, output2 = build_stage2()
    return ok2, "\n".join(part for part in (output, output2) if part)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entry", nargs="?", help="a program to build instead of sawc2")
    ap.add_argument("-o", dest="out", help="the output path (required with ENTRY)")
    ap.add_argument("--runtime", metavar="TRIPLE", action="append", default=[],
                    help="also build the runtime of another target and write its manifest")
    args = ap.parse_args()
    if args.entry is None:
        ok, output = build_sawc2()
        target = SAWC2
        for triple in args.runtime if ok else []:
            why = build_runtime(triple)
            if why:
                ok, output, target = False, "build: " + why, runtime_manifest(triple)
                break
            output = "\n".join(part for part in (output, "build: %s" % os.path.relpath(runtime_manifest(triple),
                                                                                           REPO)) if part)
    elif args.runtime:
        ap.error("--runtime builds sawc2's runtimes, so it takes no ENTRY")
        return 2
    else:
        if args.out is None:
            ap.error("-o is required when an ENTRY is given")
        ok, output = build_program(os.path.abspath(args.entry), os.path.abspath(args.out))
        target = args.out
    if output:
        print(output)
    if not ok:
        print("build: FAILED: %s" % target)
        return 1
    print("build: %s" % os.path.relpath(target, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build the self-hosted compiler: Stage 1 with the seed, Stage 2 with Stage 1.

    python compiler/tools/build.py                   # .build/sawc-stage1, then .build/sawc-stage2
    python compiler/tools/build.py --quiet           # the same, printing only a failure
    python compiler/tools/build.py ENTRY.saw -o OUT  # the stages, then any program over them
    python compiler/tools/build.py --runtime TRIPLE  # the stages, then another target's runtime

The seed is sawc compiled by clang from its own `.ll`, one set of files per
host target, which `compiler/seed/manifest.tsv` names by SHA-256 and the blob
host serves (`seed_blob`, `seed.py`). Stage 1 is the sawc the seed
builds at -O2 (`.build/sawc-stage1`), and Stage 2 is sawc built by Stage 1 at -O2
(`.build/sawc-stage2`). The lanes run Stage 2; `SAWC_STAGE=1` selects Stage
1 instead, for bisecting a difference between the two, and then Stage 2 is
not built. `SAWC` is the binary selected, or the one `SAWC_BINARY` names: a
runner that has chosen the binary (the fixpoint lane's twin, say) hands it to
every process below it that way. `bin/sawc` runs `--quiet` before every
compile, so an installed `sawc` is always this tree's.

Every step is cached by key, so an unchanged tree compiles and links nothing:
the seed's files under `.build/blobs/` by SHA-256 (`seed_blob`), the seed under
`.build/seed/<key>/` (`build_seed`), Stage 1 and Stage 2 beside their
binaries. Stage 1 links against the seed's runtime; every link
after that takes the runtime Stage 1 builds from `runtime/` with `sawc
runtime`, cached under `.build/rt2/<key>/` by a key covering Stage 1, `runtime/`,
std, the target and clang. Beside the stages goes `.build/sawc-runtime.txt`,
the runtime manifest naming the host, the clang `choose_clang` picked and
those objects, which a hosted `sawc build` links against.

Nothing here runs Stage 0: the stages need only Python's standard library,
clang, and HTTPS to the blob host while the seed's files are not yet cached;
and `build_program` builds a program with `SAWC`, after the stages.
`STAGE_PACKAGES` is the one place that maps a stage package to its directory:
the stages, the unit programs and the runner all read it, so a new stage is
registered here once.
"""
import argparse
import fcntl
import hashlib
import http.client
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import namedtuple

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.join(REPO, ".build")
STAGE1 = os.path.join(BUILD_DIR, "sawc-stage1")
STAGE1_KEY = STAGE1 + ".key"
STAGE2 = os.path.join(BUILD_DIR, "sawc-stage2")
STAGE2_KEY = STAGE2 + ".key"
DRIVER_ENTRY = os.path.join(REPO, "compiler", "driver", "src", "main.saw")
# The runtime manifest a hosted `sawc build` reads beside its own binary: the
# host target and the runtime objects it links (compiler/tests/run/README.md).
RUNTIME_MANIFEST_NAME = "sawc-runtime.txt"
RUNTIME_MANIFEST = os.path.join(BUILD_DIR, RUNTIME_MANIFEST_NAME)
# Held while the stages are built, so two builds in one checkout never link
# the same stage at once.
BUILD_LOCK = os.path.join(BUILD_DIR, "sawc.lock")
# The runtime's sources, and where the objects Stage 1 builds from them are
# cached by key.
RT_ROOT = os.path.join(REPO, "runtime")
RUNTIME_CACHE = os.path.join(BUILD_DIR, "rt2")
THIS_FILE = os.path.abspath(__file__)
STD_ROOT = os.path.join(REPO, "std")
LINK_TIMEOUT = 1800
# The seed (seed.py describes it): its manifest, which names each file by
# SHA-256, and where the seed binaries built from it are cached by key.
SEED_DIR = os.path.join(REPO, "compiler", "seed")
SEED_MANIFEST = os.path.join(SEED_DIR, "manifest.tsv")
SEED_DRIVER = "sawc.ll.xz"
# The runtime manifest's name as the seed's own driver reads it beside its
# binary, which is the pinned commit's spelling, not this tree's: a seed bump
# that changes it changes this, and `seed.py check` fails until it does.
SEED_RUNTIME_MANIFEST = "sawc2-runtime.txt"
SEED_CACHE = os.path.join(BUILD_DIR, "seed")
# The blob host serves a file at its lowercase hex SHA-256, publicly, and never
# changes or deletes one; the variable names a mirror instead. The cache holds
# the fetched files under the same names.
BLOB_URL = "https://blobs.sawlang.com/"
BLOB_URL_VARIABLE = "SAWLANG_BLOB_URL"
BLOB_CACHE = os.path.join(BUILD_DIR, "blobs")
FETCH_TIMEOUT = 120
SHIM_C = os.path.join(RT_ROOT, "shim.c")
# Bumped when `build_seed` compiles or links the seed differently, which its
# key cannot otherwise see.
SEED_RECIPE = b"sawc2-seed-v2\0"

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


# Each variable the stages read, beside its `SAWC2_` spelling: one of those
# still set in an environment would be ignored without a word, so it is
# refused, naming the spelling the stages read.
RENAMED_VARIABLES = (("SAWC2_STAGE", "SAWC_STAGE"), ("SAWC2_BINARY", "SAWC_BINARY"),
                     ("SAWC2_CANDIDATE_BINARY", "SAWC_CANDIDATE_BINARY"), ("SAWC2_CLANG", "SAWC_CLANG"))


def refuse_renamed_variables():
    for old, new in RENAMED_VARIABLES:
        if old in os.environ:
            sys.exit("build: %s is set, and it is spelled %s now; set that instead" % (old, new))


def selected_stage():
    """The stage `SAWC_STAGE` names, 2 when it is unset."""
    stage = os.environ.get("SAWC_STAGE", "2")
    if stage not in ("1", "2"):
        sys.exit("build: SAWC_STAGE is %r; it names Stage 1 or Stage 2" % stage)
    return int(stage)


refuse_renamed_variables()
SAWC = os.environ.get("SAWC_BINARY") or (STAGE2 if selected_stage() == 2 else STAGE1)


def handed_down():
    """Whether a runner above this process chose `SAWC` (SAWC_BINARY), so
    keeping it fresh is that runner's job and never this process's."""
    return bool(os.environ.get("SAWC_BINARY"))


def package_arguments(root):
    """`--module-path` for every stage package, under the tree at `root`."""
    args = []
    for name, rel in STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, os.path.join(root, rel))]
    return args


def build_program(entry, out):
    """Compile `entry`, against the new std and every stage package, to the
    executable `out` with `SAWC`, the stage the lanes run. Returns (ok,
    compiler output)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run([SAWC, "build", "--std-root", "std"] + package_arguments(REPO)
                       + [os.path.relpath(entry, REPO), "-o", out], cwd=REPO, capture_output=True, text=True,
                       timeout=LINK_TIMEOUT)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def link_module(ll, out, sanitize=False):
    """Link the host `.ll` at `ll` into the executable `out` at -O0 as a
    hosted `sawc build` links it (`driver_link` in
    compiler/driver/src/main.saw, which the two must agree with): with the
    clang and the runtime objects the manifest beside `SAWC` names, and with
    `-fsanitize=address` when `sanitize`. For a module no `sawc build` can
    write, such as one a test hands the backend past a refusal. Returns (ok,
    clang's output)."""
    manifest = os.path.join(os.path.dirname(os.path.realpath(SAWC)), RUNTIME_MANIFEST_NAME)
    triple, clang, objects = None, None, []
    with open(manifest) as fh:
        for line in fh.read().splitlines():
            if line.startswith("target "):
                triple = line[len("target "):]
            elif line.startswith("clang "):
                clang = line[len("clang "):]
            elif line.startswith("object "):
                objects.append(line[len("object "):])
    if triple is None or clang is None:
        return False, "%s names no target or no clang" % manifest
    arguments = [clang, "-target", clang_triple(triple), "-O0"] + (["-fsanitize=address"] if sanitize else [])
    arguments += ["-x", "ir", ll, "-x", "none"] + objects + link_libraries(triple) + ["-o", out]
    r = subprocess.run(arguments, capture_output=True, text=True, timeout=LINK_TIMEOUT)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def link_driver(compiler, out):
    """The driver built and linked into `out` at -O2 by the sawc binary
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
    """The sawc target of the machine this runs on, which the runtime
    manifest beside the stages names and a hosted `sawc build` links for."""
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine == "arm64":
        return "arm64-apple-darwin"
    if sys.platform.startswith("linux") and machine in ("aarch64", "arm64"):
        return "aarch64-unknown-linux-gnu"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "x86_64-unknown-linux-gnu"
    sys.exit("build: no sawc target describes this host (%s, %s)" % (sys.platform, machine))


def clang_triple(triple):
    """The triple clang is told for a sawc target: `target_clang_triple` in
    compiler/target/src/layout.saw, which the two must agree with."""
    return "arm64-apple-macosx11.0.0" if triple == "arm64-apple-darwin" else triple


def link_libraries(triple):
    """The libraries a link for the sawc target `triple` names after its
    objects: `driver_link_libraries` in compiler/driver/src/main.saw, which
    the two must agree with, since the seed links as `sawc build` does.
    glibc keeps the math functions in libm, apart from libc; macOS carries
    them in libSystem. The Linux triples are named one by one, so a new Linux
    target must be added here and there.

    ENTRY POINTS:
      build_seed
      link_module
    """
    return ["-lm"] if triple in ("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu") else []


# The clangs tried when `SAWC_CLANG` names none, in order: the versioned
# names a Linux distribution installs beside an older default, then `clang`.
CLANG_CANDIDATES = ("clang-19", "clang-18", "clang-17", "clang-16", "clang-15", "clang")
# The capability every clang sawc hands its `.ll` to must have: opaque
# pointers (`ptr`), which sawc emits throughout and LLVM 15 made the default.
# The module is compiled rather than a version parsed, since Apple's clang
# numbers its versions apart from LLVM's.
OPAQUE_POINTER_MODULE = "define ptr @f(ptr %p) {\n  ret ptr %p\n}\n"
CLANG_REQUIREMENT = "sawc's .ll needs a clang that compiles opaque-pointer IR (`ptr`): LLVM 15 or later"
_CHOSEN_CLANGS = {}


def choose_clang(triple):
    """The clang every sawc compile and link for `triple` uses: `SAWC_CLANG`,
    else the first of `CLANG_CANDIDATES` on `PATH` that compiles
    `OPAQUE_POINTER_MODULE` for the target. Returns (absolute path, "") or
    (None, why none qualifies). The runtime manifest records the choice, and
    everything after reads it there: `sawc build`'s link, `sawc runtime`
    run without `--clang`, and `stage2_key`.

    ENTRY POINTS:
      build_runtime
    """
    if triple in _CHOSEN_CLANGS:
        return _CHOSEN_CLANGS[triple]
    named = os.environ.get("SAWC_CLANG")
    candidates = [named] if named else list(CLANG_CANDIDATES)
    refused = []
    answer = None
    for candidate in candidates:
        path = shutil.which(candidate)
        if path is None:
            if named:
                refused.append("SAWC_CLANG names %s, which is not an executable" % named)
            continue
        path = os.path.abspath(path)
        if clang_capable(path, triple):
            answer = (path, "")
            break
        refused.append("%s does not compile opaque-pointer IR (`ptr`) for %s" % (path, triple))
    if answer is None:
        tried = "SAWC_CLANG" if named else "any of %s on PATH" % ", ".join(CLANG_CANDIDATES)
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
    of: Stage 1's binary, the runtime's sources and C shim, the std they
    compile against, the target and the clang. None when Stage 1 is
    missing."""
    if not os.path.exists(STAGE1):
        return None
    digest = hashlib.sha256()
    digest.update(b"sawc2-runtime-v1\0")
    with open(STAGE1, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    for root in (RT_ROOT, STD_ROOT):
        _hash_tree(digest, root)
    digest.update(("%s\0%s\0" % (triple, clang)).encode("utf-8"))
    digest.update(clang_version(clang).encode("utf-8"))
    return digest.hexdigest()[:16]


def runtime_seam_problems(objects, triple):
    """Every way the external `__saw_rt_*` definitions of `objects`, as `nm`
    reads them, are not the ABI table's runtime seams each exactly once: the
    check `sawc runtime` makes from its own exports, made again on the bytes
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
    """The runtime manifest a `sawc build` for `triple` reads beside its
    binary: `sawc-runtime.txt` for the host, `sawc-runtime-TRIPLE.txt` for
    another target (compiler/tests/run/README.md)."""
    if triple == host_triple():
        return RUNTIME_MANIFEST
    return os.path.join(BUILD_DIR, "sawc-runtime-%s.txt" % triple)


def build_runtime(triple=None):
    """Stage 1's `sawc runtime` builds the runtime objects for `triple`, the
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
        return "the runtime's key needs %s" % os.path.relpath(STAGE1, REPO)
    directory = os.path.join(RUNTIME_CACHE, key)
    done = os.path.join(directory, "manifest.txt")
    os.makedirs(RUNTIME_CACHE, exist_ok=True)
    # Two builds of one key in one checkout would remove each other's
    # half-built directory, so the build of a key holds its lock, and the
    # check for a finished one is repeated under it.
    with open(os.path.join(RUNTIME_CACHE, key + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(done):
            announce()
            shutil.rmtree(directory, ignore_errors=True)
            os.makedirs(directory)
            r = subprocess.run([STAGE1, "runtime", "--rt-root", os.path.relpath(RT_ROOT, REPO), "--target", triple,
                                "--clang", clang, "--out", directory], cwd=REPO, capture_output=True, text=True,
                               timeout=LINK_TIMEOUT)
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


class SeedError(Exception):
    """The manifest is malformed, or a seed file it names cannot be had; the
    text names the file, and for a file, the URL and the expected SHA-256."""


# One manifest line: the file `name` of the seed of `triple`, whose xz bytes
# have the lowercase hex SHA-256 `sha256` and are `size` bytes long.
SeedFile = namedtuple("SeedFile", "triple name sha256 size")
SEED_MANIFEST_HEADER = (
    "# The seed: each file's target, name, SHA-256 and size in bytes, in build.py's\n"
    "# seed_files order; the blob host serves each at its SHA-256. compiler/tools/seed.py\n"
    "# writes this file, and compiler/README.md, \"The seed\", says when.\n")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def seed_manifest(path=None):
    """Every SeedFile the manifest at `path` (SEED_MANIFEST when None) names,
    as {triple: [SeedFile]}, each list in `seed_files` order. Raises SeedError
    on a line that is not one."""
    path = path or SEED_MANIFEST
    if not os.path.exists(path):
        return {}
    seeds = {}
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            where = "%s:%d" % (os.path.relpath(path, REPO), number)
            if (len(fields) != 4 or not fields[0] or not fields[1].endswith(".ll.xz")
                    or not SHA256_HEX.fullmatch(fields[2]) or not fields[3].isdigit()):
                raise SeedError("%s is not `TARGET<tab>NAME.ll.xz<tab>SHA-256<tab>BYTES`: %r" % (where, line))
            entry = SeedFile(fields[0], fields[1], fields[2], int(fields[3]))
            seeds.setdefault(entry.triple, []).append(entry)
    for triple, entries in seeds.items():
        names = [entry.name for entry in entries]
        runtime = [name for name in names[1:] if name.startswith("runtime/")]
        if names[:1] != [SEED_DRIVER] or runtime != sorted(set(names[1:])):
            raise SeedError("%s lists %s's files as %s; the order is %s, then runtime/ sorted, each once"
                            % (os.path.relpath(path, REPO), triple, ", ".join(names), SEED_DRIVER))
    return seeds


def format_seed_manifest(seeds, order):
    """The text of a manifest holding `seeds` ({triple: [SeedFile]}), the
    targets in `order`."""
    lines = [SEED_MANIFEST_HEADER]
    for triple in order:
        lines += ["%s\t%s\t%s\t%d\n" % entry for entry in seeds.get(triple, [])]
    return "".join(lines)


def seed_entries(triple):
    """The seed of `triple` as the manifest names it, a SeedFile per file:
    the driver's IR, then each runtime source's, in `host_sources` order
    (common first, sorted within a directory), which is the link's object
    order. Empty when the manifest names no file of `triple`."""
    return seed_manifest().get(triple, [])


def seed_files(triple):
    """The names of the seed files of `triple`, in `seed_entries` order."""
    return [entry.name for entry in seed_entries(triple)]


def blob_url(sha256):
    """Where the blob host, or the mirror BLOB_URL_VARIABLE names, serves
    the file with SHA-256 `sha256`."""
    return (os.environ.get(BLOB_URL_VARIABLE) or BLOB_URL).rstrip("/") + "/" + sha256


def _blob_problem(path, entry):
    """Why the file at `path` is not `entry`'s bytes, or ""."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) != entry.size:
        return "is %d bytes, not %d" % (len(data), entry.size)
    found = hashlib.sha256(data).hexdigest()
    if found != entry.sha256:
        return "has SHA-256 %s" % found
    return ""


def _seed_problem(entry, url, why):
    return "seed file %s/%s (SHA-256 %s) from %s: %s" % (entry.triple, entry.name, entry.sha256, url, why)


def _fetch_blob(entry, path):
    """Fetches `entry` from the blob host and publishes it at `path` by
    rename once its size and SHA-256 are the manifest's; raises SeedError."""
    url = blob_url(entry.sha256)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, partial = tempfile.mkstemp(dir=os.path.dirname(path), prefix=entry.sha256 + ".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
                    shutil.copyfileobj(response, out, 1 << 20)
            except urllib.error.HTTPError as e:
                raise SeedError(_seed_problem(entry, url, "the host answers %d %s" % (e.code, e.reason)))
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
                raise SeedError(_seed_problem(entry, url, "the fetch fails: %s" % getattr(e, "reason", e)))
        why = _blob_problem(partial, entry)
        if why:
            raise SeedError(_seed_problem(entry, url, "the fetched file " + why))
        os.replace(partial, path)
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def seed_blob(entry, fresh=False):
    """The path of the seed file `entry`'s xz bytes in BLOB_CACHE, the one
    way a seed file is had. The cached copy serves when its size and SHA-256
    are the manifest's, checked on every read; otherwise the file is fetched
    from the blob host, checked, and published by rename. `fresh` fetches
    even when the cache holds the file. Raises SeedError, naming the file,
    the URL and the expected SHA-256; nothing else is ever tried.

    The funnel is this and `seed_manifest`, the manifest's one reading;
    `seed_key` reads the manifest's digests alone, so a cached seed needs no
    network. Entry points:
      seed_entries
      seed_files
      seed_key
      build_seed
      seed.seed_ir
      seed.check
      seed.check_path_free
      seed.check_reproduces
      seed.publish
      seed.upload
    """
    path = os.path.join(BLOB_CACHE, entry.sha256)
    if not fresh and os.path.exists(path):
        why = _blob_problem(path, entry)
        if not why:
            return path
        print("seed: the cached %s %s, not the manifest's; fetching it again"
              % (os.path.relpath(path, REPO), why), file=sys.stderr)
    _fetch_blob(entry, path)
    return path


def seed_key(triple, clang):
    """What the seed of `triple` built with `clang` is a function of: the
    manifest's digests of its files, the C shim, the recipe, the target and
    the clang. It reads no seed file, so a cached seed needs no network."""
    digest = hashlib.sha256()
    digest.update(SEED_RECIPE)
    for entry in seed_entries(triple):
        digest.update(("%s/%s\0" % (entry.triple, entry.name)).encode("utf-8") + bytes.fromhex(entry.sha256))
    digest.update(os.path.relpath(SHIM_C, REPO).encode("utf-8") + b"\0")
    with open(SHIM_C, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    digest.update(("%s\0%s\0" % (triple, clang)).encode("utf-8"))
    digest.update(clang_version(clang).encode("utf-8"))
    return digest.hexdigest()[:16]


def _clang(clang, arguments):
    """Runs `clang` with `arguments`; the error text, or "" when it succeeded."""
    r = subprocess.run([clang] + arguments, cwd=REPO, capture_output=True, text=True, timeout=LINK_TIMEOUT)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip()[-600:] or "clang exited %d" % r.returncode
    return ""


def _decompress(source, destination):
    import lzma
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with lzma.open(source) as src, open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)


def build_seed(triple=None):
    """The seed binary of `triple`, the host when None, built from the IR its
    manifest lines name (`seed_blob`) into `.build/seed/<key>/` unless that
    directory already holds the build of the same key: each runtime IR
    compiled as `sawc runtime` compiles it, `runtime/shim.c` too, and the
    driver's IR linked against them as `sawc build` links, all by
    `choose_clang`'s clang. Beside the binary goes the runtime manifest naming
    those objects, which the seed links Stage 1 against. Returns (path, "")
    or (None, why)."""
    triple = triple or host_triple()
    try:
        entries = seed_entries(triple)
    except SeedError as e:
        return None, str(e)
    if not entries:
        return None, ("no seed for %s: %s names no file of it (compiler/README.md, \"The seed\")"
                      % (triple, os.path.relpath(SEED_MANIFEST, REPO)))
    clang, why = choose_clang(triple)
    if clang is None:
        return None, why
    key = seed_key(triple, clang)
    directory = os.path.join(SEED_CACHE, key)
    binary = os.path.join(directory, "sawc")
    done = os.path.join(directory, "done")
    target = clang_triple(triple)
    os.makedirs(SEED_CACHE, exist_ok=True)
    # As in `build_runtime`: the build of a key holds its lock, and the check
    # for a finished one is repeated under it.
    with open(os.path.join(SEED_CACHE, key + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.path.exists(done):
            announce()
            try:
                blobs = [seed_blob(entry) for entry in entries]
            except SeedError as e:
                return None, str(e)
            shutil.rmtree(directory, ignore_errors=True)
            os.makedirs(directory)
            objects = []
            for entry, blob in zip(entries[1:], blobs[1:]):
                name = entry.name
                stem = os.path.join(directory, name[:-len(".ll.xz")])
                _decompress(blob, stem + ".ll")
                why = _clang(clang, ["-c", "-target", target, "-O2", "-x", "ir", stem + ".ll", "-o", stem + ".o"])
                if why:
                    return None, "the seed's %s does not compile: %s" % (name, why)
                os.remove(stem + ".ll")
                objects.append(stem + ".o")
            shim = os.path.join(directory, "shim.o")
            why = _clang(clang, ["-c", SHIM_C, "-O2", "-fno-strict-aliasing", "-target", target, "-o", shim])
            if why:
                return None, "%s does not compile for the seed: %s" % (os.path.relpath(SHIM_C, REPO), why)
            objects.append(shim)
            ll = os.path.join(directory, "sawc.ll")
            _decompress(blobs[0], ll)
            why = _clang(clang, ["-target", target, "-O2", "-x", "ir", ll, "-x", "none"] + objects
                         + link_libraries(triple) + ["-o", binary])
            if why:
                return None, "the seed of %s does not link: %s" % (triple, why)
            os.remove(ll)
            with open(os.path.join(directory, SEED_RUNTIME_MANIFEST), "w") as fh:
                fh.write("target %s\nclang %s\n" % (triple, clang) + "".join("object %s\n" % o for o in objects))
            with open(done, "w") as fh:
                fh.write(key + "\n")
    return binary, ""


def stage1_key(seed):
    """What Stage 1 is a function of: the seed binary at `seed` (its cache
    key, the name of its directory), the trees it compiles, and this file,
    which holds the link's arguments."""
    digest = hashlib.sha256()
    digest.update(b"stage1\0" + os.path.basename(os.path.dirname(seed)).encode("utf-8") + b"\0")
    _hash_sources(digest)
    return digest.hexdigest()


def bootstrap_stage1():
    """The seed (`build_seed`) builds the driver into `.build/sawc-stage1` at -O2,
    linking it against the seed's own runtime, unless the cached link has the
    same key. The seed is the one compiler in the chain that the tree does not
    build. Returns (ok, output)."""
    seed, why = build_seed()
    if seed is None:
        return False, "build: " + why
    key = stage1_key(seed)
    if os.path.exists(STAGE1) and os.path.exists(STAGE1_KEY):
        with open(STAGE1_KEY) as fh:
            if fh.read().strip() == key:
                os.utime(STAGE1)
                return True, ""
    if os.path.exists(STAGE1_KEY):
        os.remove(STAGE1_KEY)
    announce()
    why = link_driver(seed, STAGE1)
    if why:
        return False, "the seed does not build Stage 1: " + why
    with open(STAGE1_KEY + ".tmp", "w") as fh:
        fh.write(key + "\n")
    os.replace(STAGE1_KEY + ".tmp", STAGE1_KEY)
    return True, ""


def build_stage1():
    """Stage 1 from the bootstrap (`bootstrap_stage1`); then Stage 1 builds
    the runtime every later link takes, and its manifest is written beside the
    stages. Returns (ok, output)."""
    ok, output = bootstrap_stage1()
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


def _hash_sources(digest):
    """The trees a stage compiles into the driver, and this file."""
    for root in [os.path.join(REPO, rel) for _, rel in STAGE_PACKAGES] + [os.path.dirname(DRIVER_ENTRY),
                                                                          STD_ROOT]:
        _hash_tree(digest, root)
    with open(THIS_FILE, "rb") as fh:
        digest.update(fh.read())


def stage2_key():
    """What Stage 2 is a function of: Stage 1's binary, the trees it
    compiles, this file (which holds the link's arguments), the runtime
    manifest and the objects it names, and the clang that links them. None
    when Stage 1 or the manifest is missing."""
    if not os.path.exists(STAGE1):
        return None
    digest = hashlib.sha256()
    with open(STAGE1, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    _hash_sources(digest)
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
    """Stage 1 builds the driver into `.build/sawc-stage2`, unless the cached
    link has the same key. Returns (ok, output)."""
    key = stage2_key()
    if key is None:
        return False, ("build: Stage 2's cache key needs %s and %s, and one is missing"
                       % (os.path.relpath(STAGE1, REPO), os.path.relpath(RUNTIME_MANIFEST, REPO)))
    if os.path.exists(STAGE2) and os.path.exists(STAGE2_KEY):
        with open(STAGE2_KEY) as fh:
            if fh.read().strip() == key:
                os.utime(STAGE2)
                return True, ""
    if os.path.exists(STAGE2_KEY):
        os.remove(STAGE2_KEY)
    announce()
    why = link_driver(STAGE1, STAGE2)
    if why:
        return False, "Stage 1 does not build Stage 2: " + why
    with open(STAGE2_KEY + ".tmp", "w") as fh:
        fh.write(key + "\n")
    os.replace(STAGE2_KEY + ".tmp", STAGE2_KEY)
    return True, ""


def build_sawc():
    """Build Stage 1, then Stage 2 unless Stage 1 is selected, holding
    BUILD_LOCK throughout. Returns (ok, output)."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(BUILD_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ok, output = build_stage1()
        if not ok or SAWC == STAGE1:
            return ok, output
        ok2, output2 = build_stage2()
        return ok2, "\n".join(part for part in (output, output2) if part)


# What `--quiet` prints on standard error once, the first time a step is about
# to build rather than find its cached result; None prints nothing.
ANNOUNCEMENT = None


def announce():
    global ANNOUNCEMENT
    if ANNOUNCEMENT:
        print(ANNOUNCEMENT, file=sys.stderr, flush=True)
        ANNOUNCEMENT = None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entry", nargs="?", help="a program to build instead of sawc")
    ap.add_argument("-o", dest="out", help="the output path (required with ENTRY)")
    ap.add_argument("--runtime", metavar="TRIPLE", action="append", default=[],
                    help="also build the runtime of another target and write its manifest")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing when the stages build, and a failure on standard error")
    args = ap.parse_args()
    if args.quiet:
        if args.entry is not None or args.runtime:
            ap.error("--quiet builds the stages alone, so it takes no ENTRY and no --runtime")
        global ANNOUNCEMENT
        ANNOUNCEMENT = ("sawc: building the compiler with compiler/tools/build.py; a first build "
                        "takes a minute or two")
        ok, output = build_sawc()
        if not ok:
            print("%s\nbuild: FAILED: %s" % (output, os.path.relpath(SAWC, REPO)), file=sys.stderr)
            return 1
        return 0
    if args.entry is None:
        ok, output = build_sawc()
        target = SAWC
        for triple in args.runtime if ok else []:
            why = build_runtime(triple)
            if why:
                ok, output, target = False, "build: " + why, runtime_manifest(triple)
                break
            output = "\n".join(part for part in (output, "build: %s" % os.path.relpath(runtime_manifest(triple),
                                                                                           REPO)) if part)
    elif args.runtime:
        ap.error("--runtime builds sawc's runtimes, so it takes no ENTRY")
        return 2
    else:
        if args.out is None:
            ap.error("-o is required when an ENTRY is given")
        target = SAWC
        ok, output = (True, "") if handed_down() else build_sawc()
        if ok:
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

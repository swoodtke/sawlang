#!/usr/bin/env python3
"""The bootstrap seed: sawc2's own `.ll`, committed per host target, which
`build.py` compiles into the compiler that builds Stage 1.

    python compiler/tools/seed.py check                       # path-free, and it reproduces itself
    python compiler/tools/seed.py check --seed TRIPLE         # the same, run by another target's seed
    python compiler/tools/seed.py write --target TRIPLE...    # a bump: Stage 1's IR of this commit

`compiler/seed/TRIPLE/` holds, compressed with xz, the driver's `.ll` as
`sawc2 build -O2 --emit-ll` writes it (`sawc2.ll.xz`), and each runtime
source's as `sawc2 runtime --emit-ll` writes it (`runtime/DIR/NAME.ll.xz` for
`runtime/DIR/NAME.saw`). `compiler/seed/pin` names the commit that IR was
emitted from. The C shim is not committed: `build.py` compiles
`runtime/shim.c` from the tree, so a shim change that alters a seam the pinned
runtime IR calls owes a bump.

`check`, which the fixpoint lane runs, requires:

- **every target**: each target of `runtime_table.HOSTS` has a seed, holding
  exactly the files its pinned tree's sources call for;
- **path-free**: no committed `.ll` holds an absolute path, so the IR is a
  function of the source and the target alone, whatever machine wrote it;
- **self-reproduction**: the seed `build.py` builds from the committed IR
  (the host's, or `--seed`'s) emits, for the pinned commit's tree, every
  target's committed IR byte for byte.

`write` refuses a tree whose compiler, std or runtime differs from HEAD, since
the pin names HEAD. compiler/README.md, "The seed", is the bump procedure.
"""
import argparse
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402
import runtime_table  # noqa: E402

PIN = os.path.join(build.SEED_DIR, "pin")
TARGETS = tuple(target for target, _, _, _ in runtime_table.HOSTS)
OUT = os.path.join(build.BUILD_DIR, "seed-check")
EMIT_TIMEOUT = 1800
# xz's strongest preset: the IR is written once per bump and read on every
# cold build, and decompression costs the same at any preset.
XZ_PRESET = 9 | lzma.PRESET_EXTREME
# An absolute path: a `/` that starts a path rather than continuing a word or
# a relative path, then at least two segments.
ABSOLUTE_PATH = re.compile(rb"(?<![A-Za-z0-9_.~/-])/[A-Za-z0-9_.+-]+/[A-Za-z0-9_.+/-]*")


def rel(path):
    return os.path.relpath(path, REPO)


def read_pin():
    """The pinned commit, or None when the pin file names none."""
    if not os.path.exists(PIN):
        return None
    with open(PIN, encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    return lines[0] if len(lines) == 1 and re.fullmatch(r"[0-9a-f]{40}", lines[0]) else None


def host_directory(triple):
    for target, directory, _, _ in runtime_table.HOSTS:
        if target == triple:
            return directory
    raise SystemExit("seed: %s is not a target of runtime_table.HOSTS" % triple)


def runtime_sources(root, triple):
    """The runtime sources `sawc2 runtime` compiles for `triple` in the tree
    at `root`, relative to its `runtime/`: `runtime_table.host_sources`'s
    reading, of another tree."""
    out = []
    for sub in ("common", host_directory(triple)):
        names = sorted(n for n in os.listdir(os.path.join(root, "runtime", sub)) if n.endswith(".saw"))
        out += ["%s/%s" % (sub, n) for n in names]
    return out


def expected_files(root, triple):
    """What the seed of `triple` holds for the tree at `root`, relative to its
    directory, in `build.seed_files`'s order."""
    return [build.SEED_DRIVER] + ["runtime/%s.ll.xz" % src[:-len(".saw")] for src in runtime_sources(root, triple)]


def emit(binary, root, triple, name):
    """The `.ll` `binary` emits for the seed file `name` of `triple` from the
    tree at `root`, as bytes; (None, why) when it refuses."""
    if name == build.SEED_DRIVER:
        # A stage package the pinned tree predates is left out; its driver
        # imports none.
        packages = []
        for package, directory in build.STAGE_PACKAGES:
            if os.path.isdir(os.path.join(root, directory)):
                packages += ["--module-path", "%s=%s" % (package, os.path.join(root, directory))]
        argv = ([binary, "build", "-O2", "--std-root", "std", "--target", triple] + packages
                + ["--emit-ll", os.path.relpath(build.DRIVER_ENTRY, REPO)])
    else:
        source = os.path.join("runtime", name[len("runtime/"):-len(".ll.xz")] + ".saw")
        argv = [binary, "runtime", "--std-root", "std", "--target", triple, "--emit-ll", source]
    r = subprocess.run(argv, cwd=root, capture_output=True, timeout=EMIT_TIMEOUT)
    if r.returncode != 0:
        return None, "`%s` exited %d: %s" % (" ".join(argv[1:3]), r.returncode,
                                             (r.stdout + r.stderr).decode("utf-8", "replace").strip()[-600:])
    return r.stdout, ""


def absolute_paths(text):
    """The absolute paths in the `.ll` `text`, at most five, each once."""
    found = []
    for m in ABSOLUTE_PATH.finditer(text):
        path = m.group(0).decode("utf-8", "replace")
        if path not in found:
            found.append(path)
        if len(found) == 5:
            break
    return found


# The detector's own cases, run before it judges the seed: (IR text, whether
# it holds an absolute path).
DETECTOR_CASES = (
    (b'@s = constant [9 x i8] c"/Users/a/b"', True),
    (b'c"/home/me/sawlang/std/vector.saw\\00"', True),
    (b'c"see /tmp/x\\00"', True),
    (b'c"compiler/tools/build.py writes it"', False),
    (b'c"/=\\00" c"/\\00" c"a // b"', False),
)


def check_path_free(failures, counts):
    for text, absolute in DETECTOR_CASES:
        if bool(absolute_paths(text)) != absolute:
            failures.append("seed: the absolute-path detector %s %r" % ("misses" if absolute else "flags", text))
        counts["seed detector cases"] = counts.get("seed detector cases", 0) + 1
    for triple in TARGETS:
        for name in build.seed_files(triple):
            with lzma.open(os.path.join(build.SEED_DIR, triple, name)) as fh:
                paths = absolute_paths(fh.read())
            if paths:
                failures.append("seed: compiler/seed/%s/%s holds an absolute path: %s"
                                % (triple, name, ", ".join(paths)))
            counts["seed files path-free"] = counts.get("seed files path-free", 0) + 1


def pinned_tree(commit, directory):
    """Extracts the sources the seed is emitted from, at `commit`, into
    `directory`; the error text, or "" once they are there."""
    wanted = ["std", "runtime", os.path.dirname(os.path.relpath(build.DRIVER_ENTRY, REPO))]
    for _, package in build.STAGE_PACKAGES:
        present = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (commit, package)], cwd=REPO,
                                 capture_output=True)
        if present.returncode == 0:
            wanted.append(package)
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)
    archive = directory + ".tar"
    r = subprocess.run(["git", "archive", "--format=tar", "-o", archive, commit] + wanted, cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return "git cannot archive the pinned commit %s: %s" % (commit, r.stderr.strip()[-300:])
    with tarfile.open(archive) as tar:
        tar.extractall(directory, filter="data")
    os.remove(archive)
    return ""


def check_reproduces(failures, counts, seed_triple=None):
    """The seed of `seed_triple` (the host's when None) emits every target's
    committed IR from the pinned tree."""
    commit = read_pin()
    if commit is None:
        failures.append("seed: %s names no commit; it holds one 40-digit commit id" % rel(PIN))
        return
    seed, why = build.build_seed(seed_triple)
    if seed is None:
        failures.append("seed: %s" % why)
        return
    tree = os.path.join(OUT, "pinned")
    why = pinned_tree(commit, tree)
    if why:
        failures.append("seed: %s" % why)
        return
    for triple in TARGETS:
        expected = expected_files(tree, triple)
        committed = build.seed_files(triple)
        if committed != expected:
            failures.append("seed: compiler/seed/%s/ holds %s; the pinned tree calls for %s"
                            % (triple, ", ".join(committed), ", ".join(expected)))
            continue
        for name in committed:
            emitted, why = emit(seed, tree, triple, name)
            if emitted is None:
                failures.append("seed: the seed does not emit compiler/seed/%s/%s: %s" % (triple, name, why))
                continue
            with lzma.open(os.path.join(build.SEED_DIR, triple, name)) as fh:
                if fh.read() != emitted:
                    failures.append("seed: the seed's .ll of the pinned commit is not compiler/seed/%s/%s"
                                    % (triple, name))
                    continue
            counts["seed files reproduced"] = counts.get("seed files reproduced", 0) + 1
    shutil.rmtree(tree, ignore_errors=True)


def check(seed_triple=None):
    """([failure], {count: n}): every target present, path-free, and
    reproduced by the seed of `seed_triple`."""
    failures = []
    counts = {}
    missing = [t for t in TARGETS if not os.path.exists(os.path.join(build.SEED_DIR, t, build.SEED_DRIVER))]
    if missing:
        return ["seed: no seed for %s; compiler/README.md, \"The seed\", says how one is written"
                % ", ".join(missing)], counts
    check_path_free(failures, counts)
    check_reproduces(failures, counts, seed_triple)
    return failures, counts


def tree_differs():
    """The paths under the seed's sources that differ from HEAD."""
    r = subprocess.run(["git", "status", "--porcelain", "--", "compiler", "std", "runtime",
                        ":(exclude)compiler/seed"], cwd=REPO, capture_output=True, text=True, check=True)
    return [line[3:] for line in r.stdout.splitlines()]


def write(targets, compiler=None):
    """Writes the seed of each of `targets` from `compiler` (Stage 1, built
    first, when None) and pins HEAD. Returns the error text, or ""."""
    differs = tree_differs()
    if differs:
        return "the pin names HEAD, and these differ from it: %s" % ", ".join(differs[:10])
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    if compiler is None:
        ok, output = build.build_stage1()
        if not ok:
            return "Stage 1 does not build: %s" % output[-600:]
        compiler = build.STAGE1
    for triple in targets:
        staging = os.path.join(OUT, "write", triple)
        shutil.rmtree(staging, ignore_errors=True)
        for name in expected_files(REPO, triple):
            emitted, why = emit(compiler, REPO, triple, name)
            if emitted is None:
                return "%s does not emit %s for %s: %s" % (rel(compiler), name, triple, why)
            paths = absolute_paths(emitted)
            if paths:
                return "%s's .ll for %s holds an absolute path: %s" % (name, triple, ", ".join(paths))
            path = os.path.join(staging, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(lzma.compress(emitted, format=lzma.FORMAT_XZ, preset=XZ_PRESET))
        destination = os.path.join(build.SEED_DIR, triple)
        shutil.rmtree(destination, ignore_errors=True)
        os.makedirs(build.SEED_DIR, exist_ok=True)
        shutil.move(staging, destination)
        print("seed: %s" % rel(destination))
    with open(PIN + ".tmp", "w", encoding="utf-8") as fh:
        fh.write("# The commit compiler/seed/'s IR was emitted from (compiler/tools/seed.py).\n%s\n" % head)
    os.replace(PIN + ".tmp", PIN)
    print("seed: %s names %s" % (rel(PIN), head))
    return ""


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="every target present, path-free, and reproduced by the seed")
    c.add_argument("--seed", metavar="TRIPLE", help="the target whose seed runs the check (the host's by default)")
    w = sub.add_parser("write", help="the seed of each --target, from Stage 1, pinned to HEAD")
    w.add_argument("--target", metavar="TRIPLE", action="append", required=True, choices=TARGETS)
    w.add_argument("--compiler", metavar="BINARY", help="the sawc2 that emits it (Stage 1 by default)")
    args = ap.parse_args(argv)
    if args.command == "write":
        why = write(args.target, args.compiler and os.path.abspath(args.compiler))
        if why:
            print("seed: FAILED: %s" % why)
            return 1
        return 0
    failures, counts = check(args.seed)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("seed check: %s%s" % ("FAIL (%d)" % len(failures) if failures else "ok", ": " + summary if summary else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

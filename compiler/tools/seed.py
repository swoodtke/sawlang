#!/usr/bin/env python3
"""The bootstrap seed: sawc2's own `.ll` per host target, which `build.py`
compiles into the compiler that builds Stage 1.

    python compiler/tools/seed.py check                         # path-free, and it reproduces itself
    python compiler/tools/seed.py check --seed TRIPLE           # the same, run by another target's seed
    python compiler/tools/seed.py write --target TRIPLE...      # a bump: emit, then publish
    python compiler/tools/seed.py emit --target TRIPLE...       # Stage 1's IR of HEAD, into .build/seed-write/
    python compiler/tools/seed.py publish --target TRIPLE...    # upload what emit wrote; the manifest, the pin

A target's seed is, compressed with xz, the driver's `.ll` as `sawc2 build
-O2 --emit-ll` writes it (`sawc2.ll.xz`), and each runtime source's as `sawc2
runtime --emit-ll` writes it (`runtime/DIR/NAME.ll.xz` for
`runtime/DIR/NAME.saw`). The files live on the blob host, each named by its
SHA-256: `compiler/seed/manifest.tsv` lists every target's files with their
SHA-256s and sizes, and `build.seed_blob` is the one way a file is had.
`compiler/seed/pin` names the commit the IR was emitted from. The C shim is
not in the seed: `build.py` compiles `runtime/shim.c` from the tree, so a
shim change that alters a seam the pinned runtime IR calls owes a bump.

`check`, which the fixpoint lane runs, requires:

- **every target**: each target of `runtime_table.HOSTS` has a seed, holding
  exactly the files its pinned tree's sources call for;
- **path-free**: no seed file's `.ll` holds an absolute path, so the IR is a
  function of the source and the target alone, whatever machine wrote it;
- **self-reproduction**: the seed `build.py` builds from the manifest's IR
  (the host's, or `--seed`'s) emits, for the pinned commit's tree, every
  target's IR byte for byte.

`emit` refuses a tree whose compiler, std or runtime differs from HEAD, since
the pin names the commit it emitted from. `publish` uploads each new file with
the blob host's upload key, fetches it back to check the host serves those
bytes, then rewrites the targets' manifest lines and the pin. A file whose IR
the manifest already holds keeps its line, so a new xz cannot churn it. The
Linux VM emits and this machine publishes (`tools/linux.py seed`): the VM has
no key. compiler/README.md, "The seed", is the bump procedure.
"""
import argparse
import hashlib
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build  # noqa: E402
import runtime_table  # noqa: E402

PIN = os.path.join(build.SEED_DIR, "pin")
TARGETS = tuple(target for target, _, _, _ in runtime_table.HOSTS)
OUT = os.path.join(build.BUILD_DIR, "seed-check")
# What `emit` writes, a directory per target holding its seed files and the
# commit they were emitted from, which `publish` uploads.
STAGING = os.path.join(build.BUILD_DIR, "seed-write")
STAGED_COMMIT = "commit"
EMIT_TIMEOUT = 1800
UPLOAD_TIMEOUT = 600
# xz's strongest preset: the IR is written once per bump and read on every
# cold build, and decompression costs the same at any preset.
XZ_PRESET = 9 | lzma.PRESET_EXTREME
# An absolute path: a `/` that starts a path rather than continuing a word or
# a relative path, then at least two segments.
ABSOLUTE_PATH = re.compile(rb"(?<![A-Za-z0-9_.~/-])/[A-Za-z0-9_.+-]+/[A-Za-z0-9_.+/-]*")
# The upload: rsync over ssh to an account whose key may only add a file, and
# silently keeps an existing name, which is why `publish` fetches each file
# back. Both paths are local to the machine that holds the key.
UPLOAD_DESTINATION = "blobs@blobs.sawlang.com:/"
UPLOAD_KEY_VARIABLE = "SAWLANG_BLOB_KEY"
UPLOAD_KEY_DEFAULT = os.path.join(REPO, ".claude", "blobs_upload_key")
KNOWN_HOSTS_VARIABLE = "SAWLANG_BLOB_KNOWN_HOSTS"
KNOWN_HOSTS_DEFAULT = os.path.join(REPO, ".claude", "linode_known_hosts")


def rel(path):
    return os.path.relpath(path, REPO)


def read_pin():
    """The pinned commit, or None when the pin file names none."""
    if not os.path.exists(PIN):
        return None
    with open(PIN, encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    return lines[0] if len(lines) == 1 and re.fullmatch(r"[0-9a-f]{40}", lines[0]) else None


def write_pin(commit):
    with open(PIN + ".tmp", "w", encoding="utf-8") as fh:
        fh.write("# The commit the seed's IR was emitted from (compiler/tools/seed.py).\n%s\n" % commit)
    os.replace(PIN + ".tmp", PIN)


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
    """What the seed of `triple` holds for the tree at `root`, in
    `build.seed_files`'s order."""
    return [build.SEED_DRIVER] + ["runtime/%s.ll.xz" % src[:-len(".saw")] for src in runtime_sources(root, triple)]


def emit_ir(binary, root, triple, name):
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


def seed_ir(entry):
    """The decompressed `.ll` of the seed file `entry`, through
    `build.seed_blob`; raises build.SeedError."""
    with lzma.open(build.seed_blob(entry)) as fh:
        return fh.read()


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
        for entry in build.seed_entries(triple):
            try:
                paths = absolute_paths(seed_ir(entry))
            except build.SeedError as e:
                failures.append("seed: %s" % e)
                continue
            if paths:
                failures.append("seed: seed file %s/%s holds an absolute path: %s"
                                % (triple, entry.name, ", ".join(paths)))
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
    seed IR from the pinned tree."""
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
        entries = build.seed_entries(triple)
        if [entry.name for entry in entries] != expected:
            failures.append("seed: %s's seed is %s; the pinned tree calls for %s"
                            % (triple, ", ".join(entry.name for entry in entries), ", ".join(expected)))
            continue
        for entry in entries:
            emitted, why = emit_ir(seed, tree, triple, entry.name)
            if emitted is None:
                failures.append("seed: the seed does not emit seed file %s/%s: %s" % (triple, entry.name, why))
                continue
            try:
                ir = seed_ir(entry)
            except build.SeedError as e:
                failures.append("seed: %s" % e)
                continue
            if ir != emitted:
                failures.append("seed: the seed's .ll of the pinned commit is not seed file %s/%s"
                                % (triple, entry.name))
                continue
            counts["seed files reproduced"] = counts.get("seed files reproduced", 0) + 1
    shutil.rmtree(tree, ignore_errors=True)


def check(seed_triple=None):
    """([failure], {count: n}): every target present, path-free, and
    reproduced by the seed of `seed_triple`."""
    failures = []
    counts = {}
    try:
        seeds = build.seed_manifest()
    except build.SeedError as e:
        return ["seed: %s" % e], counts
    missing = [t for t in TARGETS if not seeds.get(t)]
    if missing:
        return ["seed: %s names no seed for %s; compiler/README.md, \"The seed\", says how one is written"
                % (rel(build.SEED_MANIFEST), ", ".join(missing))], counts
    check_path_free(failures, counts)
    check_reproduces(failures, counts, seed_triple)
    return failures, counts


def tree_differs():
    """The paths under the seed's sources that differ from HEAD."""
    r = subprocess.run(["git", "status", "--porcelain", "--", "compiler", "std", "runtime",
                        ":(exclude)compiler/seed"], cwd=REPO, capture_output=True, text=True, check=True)
    return [line[3:] for line in r.stdout.splitlines()]


def emit(targets, compiler=None):
    """Writes the seed files of each of `targets` from `compiler` (Stage 1,
    built first, when None) into STAGING, with the commit they are of, HEAD.
    Returns the error text, or ""."""
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
        staging = os.path.join(STAGING, triple)
        partial = staging + ".partial"
        shutil.rmtree(partial, ignore_errors=True)
        for name in expected_files(REPO, triple):
            emitted, why = emit_ir(compiler, REPO, triple, name)
            if emitted is None:
                return "%s does not emit %s for %s: %s" % (rel(compiler), name, triple, why)
            paths = absolute_paths(emitted)
            if paths:
                return "%s's .ll for %s holds an absolute path: %s" % (name, triple, ", ".join(paths))
            path = os.path.join(partial, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(lzma.compress(emitted, format=lzma.FORMAT_XZ, preset=XZ_PRESET))
        with open(os.path.join(partial, STAGED_COMMIT), "w", encoding="utf-8") as fh:
            fh.write(head + "\n")
        shutil.rmtree(staging, ignore_errors=True)
        os.replace(partial, staging)
        print("seed: %s, emitted from %s" % (rel(staging), head))
    return ""


def staged(triple):
    """(commit, [(name, path)], "") for what `emit` wrote for `triple`, the
    files in `build.seed_files` order; (None, None, why) when it wrote none."""
    directory = os.path.join(STAGING, triple)
    try:
        with open(os.path.join(directory, STAGED_COMMIT), encoding="utf-8") as fh:
            commit = fh.read().strip()
    except FileNotFoundError:
        return None, None, "%s holds no emitted seed (`seed.py emit --target %s`)" % (rel(directory), triple)
    runtime = []
    for parent, subdirs, files in os.walk(os.path.join(directory, "runtime")):
        subdirs.sort()
        runtime += [os.path.relpath(os.path.join(parent, name), directory) for name in files
                    if name.endswith(".ll.xz")]
    names = [build.SEED_DRIVER] + sorted(runtime)
    if not os.path.exists(os.path.join(directory, build.SEED_DRIVER)):
        return None, None, "%s holds no %s" % (rel(directory), build.SEED_DRIVER)
    return commit, [(name, os.path.join(directory, name)) for name in names], ""


def upload_credentials():
    """(key, known_hosts, "") naming the upload key and the host's pinned
    key, or (None, None, why) when this machine has either missing."""
    found = []
    for variable, default, what in ((UPLOAD_KEY_VARIABLE, UPLOAD_KEY_DEFAULT, "the blob host's upload key"),
                                    (KNOWN_HOSTS_VARIABLE, KNOWN_HOSTS_DEFAULT, "the blob host's known_hosts")):
        path = os.environ.get(variable) or default
        if not os.path.isfile(path):
            return None, None, ("publishing uploads with %s, and %s is not a file: set %s to its path "
                                "(only the lead's machine holds it, in its main checkout's .claude/)"
                                % (what, path, variable))
        if any(c.isspace() for c in path):
            return None, None, "%s (%s) holds whitespace, which rsync's -e cannot carry" % (path, variable)
        found.append(path)
    return found[0], found[1], ""


def upload(files, key, known_hosts):
    """Uploads each (SeedFile, path) of `files` to the blob host under its
    SHA-256, then fetches each back through `build.seed_blob`. Returns the
    error text, or ""."""
    directory = os.path.join(STAGING, "upload")
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)
    named = []
    for entry, path in files:
        blob = os.path.join(directory, entry.sha256)
        shutil.copyfile(path, blob)
        # The host serves what rsync's -p carries, and openrsync has no --chmod.
        os.chmod(blob, 0o644)
        named.append(blob)
    ssh = "ssh -i %s -o IdentitiesOnly=yes -o UserKnownHostsFile=%s -o BatchMode=yes" % (key, known_hosts)
    r = subprocess.run(["rsync", "-p", "-e", ssh] + named + [UPLOAD_DESTINATION], capture_output=True, text=True,
                       timeout=UPLOAD_TIMEOUT)
    if r.returncode != 0:
        return "rsync to %s exited %d: %s" % (UPLOAD_DESTINATION, r.returncode, (r.stdout + r.stderr).strip()[-600:])
    for entry, _ in files:
        try:
            build.seed_blob(entry, fresh=True)
        except build.SeedError as e:
            return "the host does not serve what was uploaded: %s" % e
        print("seed: uploaded %s/%s as %s (%d bytes)" % (entry.triple, entry.name, entry.sha256, entry.size))
    shutil.rmtree(directory, ignore_errors=True)
    return ""


def publish(targets):
    """Uploads the seed files `emit` wrote for each of `targets`, then writes
    their manifest lines and pins the commit they were emitted from. A file
    whose IR the manifest's line already holds keeps that line. Returns the
    error text, or ""."""
    key, known_hosts, why = upload_credentials()
    if why:
        return why
    commits = {}
    files = {}
    for triple in targets:
        commit, names, why = staged(triple)
        if why:
            return why
        commits[triple] = commit
        files[triple] = names
    if len(set(commits.values())) != 1:
        return "the targets were emitted from different commits: %s" % ", ".join(
            "%s at %s" % (triple, commit) for triple, commit in sorted(commits.items()))
    try:
        seeds = build.seed_manifest()
    except build.SeedError as e:
        return str(e)
    uploads = {}
    for triple in targets:
        previous = {entry.name: entry for entry in seeds.get(triple, [])}
        entries = []
        for name, path in files[triple]:
            with open(path, "rb") as fh:
                data = fh.read()
            entry = build.SeedFile(triple, name, hashlib.sha256(data).hexdigest(), len(data))
            old = previous.get(name)
            try:
                if old is not None and old.sha256 != entry.sha256 and seed_ir(old) == lzma.decompress(data):
                    entry = old
            except build.SeedError as e:
                return "the manifest's %s/%s cannot be compared with the new one: %s" % (triple, name, e)
            if old is None or entry.sha256 != old.sha256:
                uploads.setdefault(entry.sha256, (entry, path))
            entries.append(entry)
        seeds[triple] = entries
    if uploads:
        why = upload(list(uploads.values()), key, known_hosts)
        if why:
            return why
    order = list(TARGETS) + sorted(t for t in seeds if t not in TARGETS)
    with open(build.SEED_MANIFEST + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(build.format_seed_manifest(seeds, order))
    os.replace(build.SEED_MANIFEST + ".tmp", build.SEED_MANIFEST)
    commit = next(iter(commits.values()))
    write_pin(commit)
    print("seed: %s lists %s; %d file(s) uploaded" % (rel(build.SEED_MANIFEST), ", ".join(targets), len(uploads)))
    print("seed: %s names %s" % (rel(PIN), commit))
    return ""


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="every target present, path-free, and reproduced by the seed")
    c.add_argument("--seed", metavar="TRIPLE", help="the target whose seed runs the check (the host's by default)")
    for name, what in (("write", "emit, then publish"),
                       ("emit", "the seed of each --target from Stage 1, of HEAD, into .build/seed-write/"),
                       ("publish", "upload what emit wrote for each --target; its manifest lines and the pin")):
        p = sub.add_parser(name, help=what)
        p.add_argument("--target", metavar="TRIPLE", action="append", required=True, choices=TARGETS)
        if name != "publish":
            p.add_argument("--compiler", metavar="BINARY", help="the sawc2 that emits it (Stage 1 by default)")
    args = ap.parse_args(argv)
    if args.command != "check":
        why = ""
        if args.command in ("write", "emit"):
            why = emit(args.target, args.compiler and os.path.abspath(args.compiler))
        if not why and args.command in ("write", "publish"):
            why = publish(args.target)
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

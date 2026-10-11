#!/usr/bin/env python3
"""The fixpoint lane: the compiler built by itself agrees with the one Stage 0
built, and building itself again changes nothing.

    python compiler/tests/fixpoint/fixpoint_lane.py

The numbering is the conventional one. Stage 0 (the frozen Python compiler)
builds Stage 1, `.build/sawc2`; Stage 1's `sawc2 build -O2` of its own driver,
against the new std, links Stage 2, `.build/sawc2-stage2`
(`compiler/tools/build.py` builds both); Stage 2 building itself is Stage 3.
The lane requires:

- **determinism**: the driver's `.ll` from Stage 1 is the same bytes built
  twice, and built from a copy of `compiler/` and `std/` in another directory;
- **the fixpoint**: Stage 2's `.ll` of the driver is Stage 1's, byte for byte,
  and Stage 3 links into Stage 2's bytes;
- **the lanes**: every `sawc2` invocation that `compiler/tests/run.py`'s
  sawc2-driven lanes make (the lex fixtures, the recognizer's token dumps,
  parse, resolve, typecheck, MIR, eval, std, borrowck, drops, mono and the run
  lane's builds) runs under Stage 1 and Stage 2 through `twin.py`, which hands
  the lane Stage 1's answer and records whether Stage 2's standard output,
  standard error and exit status are the same bytes.

An invocation whose outputs differ fails unless `mismatches.tsv` lists it
(`ARGUMENTS<TAB>REASON`, the arguments joined by single spaces) with the
adjudicated reason: SL:hazards' "oracle known wrong" discipline, so a
difference is never absorbed, only explained. A listed mismatch that no
longer occurs fails as stale. The lanes' own verdicts are run.py's to judge;
here only agreement counts.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, TESTS)

import build  # noqa: E402

OUT = os.path.join(REPO, ".build", "fixpoint-lane")
TWIN = os.path.join(HERE, "twin.py")
MISMATCHES = os.path.join(HERE, "mismatches.tsv")
LOG = os.path.join(OUT, "invocations.jsonl")
TIMEOUT = 1800

# The lanes of run.py that drive sawc2, in run.py's order.
LANES = ("golden", "grammar", "parser", "resolver", "typechecker", "mir", "eval", "std", "borrowck", "drops",
         "mono", "programs")


def rel(path):
    return os.path.relpath(path, REPO)


def driver_ir(binary, root):
    """The driver's `.ll` as `binary` writes it with `root` as the tree, and
    the seconds it took; None when it refused."""
    start = time.time()
    entry = os.path.join(root, "compiler", "driver", "src", "main.saw")
    r = subprocess.run([binary, "build", "--emit-ll", "--std-root", os.path.join(root, "std")]
                       + build.package_arguments(root)
                       + [entry], cwd=root, capture_output=True, timeout=TIMEOUT)
    seconds = time.time() - start
    if r.returncode != 0:
        return None, seconds, r.stdout.decode("utf-8", "replace")[:600]
    return r.stdout, seconds, ""


def build_stages(failures, counts):
    """Stage 0 builds Stage 1, which builds Stage 2. True when both linked."""
    start = time.time()
    ok, output = build.build_stage1()
    counts["seconds: Stage 0 builds Stage 1"] = round(time.time() - start)
    if not ok:
        failures.append("fixpoint: Stage 0 does not build Stage 1: %s" % output[:300])
        return False
    start = time.time()
    ok, output = build.build_stage2()
    counts["seconds: Stage 1 builds Stage 2 at -O2, or finds it cached"] = round(time.time() - start)
    if not ok:
        failures.append("fixpoint: %s" % output[:600])
        return False
    return True


def check_stage3(failures, counts):
    """Stage 2 builds Stage 3, which is Stage 2 byte for byte. The linker
    writes the output's name into the binary, so Stage 3 is linked under
    Stage 2's own name in a directory of its own."""
    stage3 = os.path.join(OUT, "stage3", os.path.basename(build.STAGE2))
    start = time.time()
    why = build.link_driver(build.STAGE2, stage3)
    counts["seconds: Stage 2 builds Stage 3 at -O2"] = round(time.time() - start)
    if why:
        failures.append("fixpoint: Stage 2 does not build Stage 3: %s" % why)
        return
    with open(build.STAGE2, "rb") as a, open(stage3, "rb") as b:
        if a.read() != b.read():
            failures.append("fixpoint: Stage 3 is not Stage 2 byte for byte")
            return
    counts["fixpoint binaries"] = 1


def check_driver_ir(failures, counts):
    """Determinism over two builds and two directories, and the IR fixpoint."""
    first, seconds, why = driver_ir(build.STAGE1, REPO)
    counts["seconds: Stage 1 writes the driver's .ll"] = round(seconds)
    if first is None:
        failures.append("fixpoint determinism: Stage 1 refuses its own driver: %s" % why)
        return
    second, _, _ = driver_ir(build.STAGE1, REPO)
    if second != first:
        failures.append("fixpoint determinism: two builds of the driver's .ll differ")
    elsewhere = os.path.join(OUT, "elsewhere")
    shutil.rmtree(elsewhere, ignore_errors=True)
    for part in ("compiler", "std"):
        shutil.copytree(os.path.join(REPO, part), os.path.join(elsewhere, part),
                        ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
    moved, _, why = driver_ir(build.STAGE1, elsewhere)
    if moved != first:
        failures.append("fixpoint determinism: the driver's .ll built in another directory differs%s"
                        % (": " + why if why else ""))
    counts["fixpoint driver .ll bytes"] = len(first)
    fixed, seconds, why = driver_ir(build.STAGE2, REPO)
    counts["seconds: Stage 2 writes the driver's .ll"] = round(seconds)
    if fixed != first:
        failures.append("fixpoint: Stage 2's .ll of the driver differs from Stage 1's%s"
                        % (": " + why if why else ""))


def replay_lanes(failures, counts):
    """Every sawc2 invocation of run.py's sawc2-driven lanes, under both
    binaries; returns the records the twin logged."""
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(LOG):
        os.remove(LOG)
    twin = os.path.join(OUT, "sawc2-twin")
    with open(twin, "w") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, TWIN))
    os.chmod(twin, 0o755)
    os.environ["FIXPOINT_REF"] = build.STAGE1
    os.environ["FIXPOINT_NEW"] = build.STAGE2
    os.environ["FIXPOINT_LOG"] = LOG
    real = build.SAWC2
    build.SAWC2 = twin
    try:
        import run as R
        lanes = R.Run()
        start = time.time()
        for name in LANES:
            getattr(R, "run_" + name)(lanes)
        counts["seconds: the lanes under both binaries"] = round(time.time() - start)
    finally:
        build.SAWC2 = real
    records = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
    return records


def read_mismatches(failures):
    known = {}
    with open(MISMATCHES, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 2 or not fields[1].strip():
                failures.append("fixpoint %s:%d: a mismatch is ARGUMENTS<TAB>REASON" % (rel(MISMATCHES), lineno))
                continue
            known[fields[0]] = fields[1]
    return known


def judge(failures, counts, records):
    known = read_mismatches(failures)
    seen = set()
    for record in records:
        key = " ".join(record["args"])
        counts["fixpoint invocations compared"] = counts.get("fixpoint invocations compared", 0) + 1
        if not record["differs"]:
            counts["fixpoint invocations agreeing"] = counts.get("fixpoint invocations agreeing", 0) + 1
            continue
        if key in known:
            seen.add(key)
            counts["fixpoint annotated mismatches"] = counts.get("fixpoint annotated mismatches", 0) + 1
            continue
        failures.append("fixpoint mismatch: sawc2 %s: %s" % (key[:300], "; ".join(record["differs"])[:600]))
    for key in sorted(set(known) - seen):
        failures.append("fixpoint: the annotated mismatch `%s` no longer occurs; remove its line" % key[:300])


def run():
    failures = []
    counts = {}
    if build_stages(failures, counts):
        check_driver_ir(failures, counts)
        check_stage3(failures, counts)
        records = replay_lanes(failures, counts)
        judge(failures, counts, records)
    return failures, counts


def main():
    start = time.time()
    failures, counts = run()
    counts["seconds: the whole lane"] = round(time.time() - start)
    for failure in failures:
        print(failure)
    summary = ", ".join("%s %s" % (n, key) for key, n in sorted(counts.items()))
    print("fixpoint lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

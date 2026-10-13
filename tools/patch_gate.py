#!/usr/bin/env python3
"""The per-patch gate: decide which suites a change needs, then run them.

    ./build.sh test [--changed-since REV | --diff FILE] [--dry-run]

`build.sh` bootstraps the venv and holds the suite lock around this script,
passing the time it waited for the lock in `SAW_GATE_LOCK_WAIT`. The
self-hosted compiler's tests always run. The fixpoint lane, the Python suite,
the freestanding suite, the full grammar corpus and the full astdiff run only
when a changed path is one they read (`SUITE_INPUTS`); without the full grammar
corpus or astdiff, each changed .saw file gets that check on its own
(`PER_FILE`). With no source of changed paths, or when
git cannot name them, everything runs. `--dry-run` prints the decision and runs
nothing.
"""
import argparse
import os
import subprocess
import sys
import time

from astdiff import NEW_COMPILER_CORPORA

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A change to the gate's own definition re-runs everything.
GATE_DEFINITION = ("build.sh", "tools/patch_gate.py", "tools/suite_lock.sh", ".sawtracker/")

# Paths each suite reads, as prefixes, taken from the two runners.
SUITE_INPUTS = {
    "python suite": (
        "sawc/",                    # the compiler it drives, std and runtime included
        "examples/",                # the corpus test_runner.py discovers
        "tests/cbor_vectors/",      # vector files examples read at run time
        "tests/float_vectors/",
        "test_runner.py",
        "tools/gate_jobs.py",       # its default worker count
        "tools/child_groups.py",    # which starts and ends each test's process group
    ),
    "freestanding": (
        "sawc/",
        "tests/freestanding/",      # cases, HAL stubs, packages
        "blade/",                   # the blade_target case builds Blade
        "libs/",                    # against toml, semver and imgformat
        "tools/freestanding_runner.py",
    ),
    "grammar corpus": (
        "GRAMMAR.md",               # the grammar it recognizes with
        "LANGUAGE_SPEC.md",         # the headings spec= names
        "compiler/tests/grammar/",  # the tools and corpus_expected.tsv
        "compiler/lex/",            # the lexer whose token dump it reads
        "compiler/driver/",         # sawc2, which prints that dump
        "compiler/tools/build.py",  # which builds sawc2
        "sawc/",                    # Stage 0, which builds sawc2, and the parser that classifies
    ),
    "fixpoint": (
        "compiler/",                # the compiler Stage 1 and Stage 2 are built from
        "std/",                     # the std Stage 1 builds Stage 2 against
        "sawc/",                    # Stage 0, which builds Stage 1, and the runtime both link
        "compiler/tests/fixpoint/", # the lane, twin.py and mismatches.tsv
        "compiler/tools/build.py",  # which builds both stages
        "tools/gate_jobs.py",       # how many invocations run at once
    ),
    "astdiff": (
        "sawc/lexer.py",            # the Python front end whose tree it dumps
        "sawc/parser/",
        "sawc/ast_nodes.py",
        "sawc/ast_dump.py",         # the canonical dump
        "tools/astdiff.py",         # the harness and its dumper
        "tools/dump_ast.py",
    ),
}

GRAMMAR_CORPUS = "compiler/tests/grammar/corpus.py"
ASTDIFF = "tools/astdiff.py"

# (name, command) in running order. The first always runs.
PARTS = (
    ("compiler tests", ["compiler/tests/run.py"]),
    ("fixpoint", ["compiler/tests/fixpoint/fixpoint_lane.py"]),
    ("python suite", ["test_runner.py"]),
    ("freestanding", ["tools/freestanding_runner.py"]),
    ("grammar corpus", [GRAMMAR_CORPUS]),
    ("astdiff", [ASTDIFF]),
)

# The parser corpus, whose case files corpus.py skips too.
PARSE_CORPUS = "compiler/tests/parse/"

# Checks of each changed .saw file on its own, for a patch the full part does
# not run on: (name, the full part, the corpora it leaves to others, command).
# The command takes the files. The parser corpus's case files belong to the
# parse lane, which the compiler tests run on every patch, and both new-syntax
# corpora are outside what the Python parser reads.
PER_FILE = (
    ("grammar: changed .saw files", "grammar corpus", (PARSE_CORPUS,), [GRAMMAR_CORPUS]),
    ("astdiff: changed .saw files", "astdiff", NEW_COMPILER_CORPORA, [ASTDIFF]),
)


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("`git %s` failed: %s" % (" ".join(args), r.stderr.strip()))
    return [line for line in r.stdout.splitlines() if line.strip()]


def changed_since(rev):
    """Every path that differs between `rev` and the working tree, untracked
    files included. Renames count as a deletion plus an addition, so a file
    moved out of a suite's inputs still re-runs that suite."""
    try:
        git("rev-parse", "--verify", "--quiet", rev + "^{commit}")
    except RuntimeError:
        raise RuntimeError("`%s` names no commit here" % rev)
    paths = set(git("diff", "--name-only", "--no-renames", rev))
    paths.update(git("ls-files", "--others", "--exclude-standard"))
    return paths


def changed_in_diff(path):
    """The paths a unified diff (as `git diff` writes it) touches, both sides."""
    paths = set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("diff --git "):
                parts = line.split()
                for side in parts[2:4]:
                    paths.add(_strip_side(side))
            elif line.startswith("--- ") or line.startswith("+++ "):
                side = line[4:].strip().split("\t")[0]
                if side != "/dev/null":
                    paths.add(_strip_side(side))
    return paths


def _strip_side(side):
    side = side.strip('"')
    return side[2:] if side[:2] in ("a/", "b/") else side


def plan(paths, source):
    """[(part name, run?, reason, command)] for the changed `paths` (None = unknown)."""
    decisions = [(PARTS[0][0], True, "always", PARTS[0][1])]
    for name, command in PARTS[1:]:
        if paths is None:
            decisions.append((name, True, "the changed paths are unknown: %s" % source, command))
            continue
        hit = _first_hit(paths, GATE_DEFINITION)
        if hit:
            decisions.append((name, True, "%s changes the gate itself" % hit, command))
            continue
        hit = _first_hit(paths, SUITE_INPUTS[name])
        if hit:
            decisions.append((name, True, "%s is one of its inputs" % hit, command))
        else:
            decisions.append((name, False, "no changed path is one of its inputs: %s"
                              % ", ".join(SUITE_INPUTS[name]), command))
    for entry in PER_FILE:
        decisions.append(_per_file(paths, decisions, *entry))
    return decisions


def _per_file(paths, decisions, name, full, elsewhere, command):
    """A PER_FILE check's decision, which the full part's run makes redundant."""
    if any(part == full and run for part, run, _, _ in decisions):
        return (name, False, "the full %s runs" % full, None)
    saw = sorted(p for p in paths if p.endswith(".saw") and not p.startswith(elsewhere))
    if not saw:
        return (name, False, "no .saw file changed outside %s" % ", ".join(elsewhere), None)
    shown = ", ".join(saw[:5]) + (", ..." if len(saw) > 5 else "")
    return (name, True, "%d changed: %s" % (len(saw), shown), command + saw)


def _first_hit(paths, prefixes):
    for p in sorted(paths):
        for prefix in prefixes:
            if p == prefix or (prefix.endswith("/") and p.startswith(prefix)):
                return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--changed-since", metavar="REV",
                        help="gate what changed between REV and the working tree")
    source.add_argument("--diff", metavar="FILE", help="gate the paths a patch file touches")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the decision and run nothing")
    args = ap.parse_args()

    paths = None
    if args.changed_since:
        how = "changed since %s" % args.changed_since
        try:
            paths = changed_since(args.changed_since)
        except RuntimeError as exc:
            how = str(exc)
    elif args.diff:
        how = "touched by %s" % args.diff
        paths = changed_in_diff(args.diff)
    else:
        how = "no --changed-since or --diff given"

    if paths is None:
        print("gate: changed paths: unknown (%s)" % how)
    else:
        print("gate: changed paths: %d, %s" % (len(paths), how))
    decisions = plan(paths, how)
    for name, run, reason, _ in decisions:
        print("gate: %s: %s (%s)" % (name, "run" if run else "skip", reason))
    if args.dry_run:
        return 0

    results = []
    tests_start = time.time()
    for name, run, _, command in decisions:
        if not run:
            results.append("%s skipped" % name)
            continue
        print("gate: ---- %s ----" % name, flush=True)
        start = time.time()
        rc = subprocess.run([sys.executable] + command, cwd=REPO).returncode
        took = duration(time.time() - start)
        results.append("%s %s (%s)" % (name, "passed" if rc == 0 else "FAILED, exit %d" % rc, took))
    print("gate: " + "; ".join(results))
    print("gate: time: %s; tests %s" % (lock_wait(), duration(time.time() - tests_start)))
    return 1 if any("FAILED" in r for r in results) else 0


def lock_wait():
    """The suite-lock wait build.sh measured, which the test time excludes."""
    seconds = os.environ.get("SAW_GATE_LOCK_WAIT", "")
    if not seconds.isdigit():
        return "suite-lock wait unknown (the lock was not taken by build.sh)"
    return "suite-lock wait %s" % duration(int(seconds))


def duration(seconds):
    s = int(round(seconds))
    if s >= 3600:
        return "%dh %dm %ds" % (s // 3600, s % 3600 // 60, s % 60)
    if s >= 60:
        return "%dm %ds" % (s // 60, s % 60)
    return "%ds" % s


if __name__ == "__main__":
    sys.exit(main())

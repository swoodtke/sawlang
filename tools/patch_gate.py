#!/usr/bin/env python3
"""The per-patch gate: decide which suites a change needs, then run them.

    ./build.sh test [--changed-since REV | --diff FILE] [--dry-run]

`build.sh` bootstraps the venv and holds the suite lock around this script. The
self-hosted compiler's tests always run. The Python suite, the freestanding
suite and the full grammar corpus run only when a changed path is one they read
(`SUITE_INPUTS`); otherwise each changed .saw file is checked against the
grammar's recorded verdicts on its own. With no source of changed paths, or when
git cannot name them, everything runs. `--dry-run` prints the decision and runs
nothing.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A change to the gate's own definition re-runs everything.
GATE_DEFINITION = ("build.sh", "tools/patch_gate.py", ".sawtracker/")

# Paths each suite reads, as prefixes, taken from the two runners.
SUITE_INPUTS = {
    "python suite": (
        "sawc/",                    # the compiler it drives, std and runtime included
        "examples/",                # the corpus test_runner.py discovers
        "tests/cbor_vectors/",      # vector files examples read at run time
        "tests/float_vectors/",
        "test_runner.py",
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
}

GRAMMAR_CORPUS = "compiler/tests/grammar/corpus.py"

# (name, command) in running order. The first always runs.
PARTS = (
    ("compiler tests", ["compiler/tests/run.py"]),
    ("python suite", ["test_runner.py"]),
    ("freestanding", ["tools/freestanding_runner.py"]),
    ("grammar corpus", [GRAMMAR_CORPUS]),
)

# Checks each changed .saw file against the recorded verdicts when the full
# grammar corpus does not run; its command takes the files.
CHANGED_SAW = "grammar: changed .saw files"


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
    decisions.append(_changed_saw(paths, decisions))
    return decisions


def _changed_saw(paths, decisions):
    """The per-file grammar check, which the full corpus run makes redundant."""
    if any(name == "grammar corpus" and run for name, run, _, _ in decisions):
        return (CHANGED_SAW, False, "the full grammar corpus runs", None)
    saw = sorted(p for p in paths if p.endswith(".saw"))
    if not saw:
        return (CHANGED_SAW, False, "no .saw file changed", None)
    shown = ", ".join(saw[:5]) + (", ..." if len(saw) > 5 else "")
    return (CHANGED_SAW, True, "%d changed: %s" % (len(saw), shown), [GRAMMAR_CORPUS] + saw)


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
    for name, run, _, command in decisions:
        if not run:
            results.append("%s skipped" % name)
            continue
        print("gate: ---- %s ----" % name, flush=True)
        rc = subprocess.run([sys.executable] + command, cwd=REPO).returncode
        results.append("%s %s" % (name, "passed" if rc == 0 else "FAILED (exit %d)" % rc))
    print("gate: " + "; ".join(results))
    return 1 if any("FAILED" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

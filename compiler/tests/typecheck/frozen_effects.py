#!/usr/bin/env python3
"""Exhaustiveness, discarded-`Result` and suspension verdicts: sawc2 typecheck
against the frozen compiler.

    python compiler/tests/typecheck/frozen_effects.py

A one-time check, kept runnable, beside `frozen_check.py`; nothing in `sawc/`
is edited, and the frozen compiler's answers are recorded, never the
definition. Three parts:

- **The sawc2 build.** The frozen compiler builds it, so every `match` in it is
  exhaustive and no `Result` in it is discarded by the frozen compiler's
  rules; sawc2 checks the same build, and the counts of what it checked are
  recorded beside its verdicts.
- **The corpus's refusal programs** whose expected error is a non-exhaustive
  match or a discarded `Result`: each must be refused by sawc2's matching rule.
- **A suspension sample**: every tracked corpus program that parks through
  `yield_now` and nothing outside the sync-only slice. The frozen compiler's
  coroutine transform decides which functions it frames (`--emit-frame-ledger`,
  a FRAME row with `boundary=yes`), and sawc2's phase 2 decides which may
  suspend (`--summaries`); the two are compared by function over the programs
  sawc2 checks with no refusal.
"""
import collections
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import build  # noqa: E402

CORPUS = os.path.join(REPO, "tests", "corpus")
SAWC = os.path.join(REPO, "sawc", "sawc.py")
OUTSIDE_SLICE = re.compile(r"\bspawn\b|TaskGroup|Channel|\bTask\.|\bsleep\(|__saw_drive")
EXPECTED = (("not exhaustive", "match.non-exhaustive"), ("exhaustive", "match.non-exhaustive"),
            ("silently discarded", "result.discarded"))


def rel(path):
    return os.path.relpath(path, REPO)


def sawc2(args):
    r = subprocess.run([build.SAWC2, "typecheck"] + args, cwd=REPO, capture_output=True,
                       text=True)
    return r.stdout


def records(output):
    out = {}
    current = None
    for line in output.split("\n"):
        if line.startswith("FILE\t"):
            current = line[len("FILE\t"):]
            out[current] = []
        elif current is not None and line:
            out[current].append(line)
    return out


def package_args():
    args = []
    for name, directory in build.STAGE_PACKAGES:
        args += ["--module-path", "%s=%s" % (name, directory)]
    return args


def check_build():
    """Counts of the `match` expressions and statement `Result`s sawc2 checks
    over the sawc2 build, and its refusals by the two rules."""
    entry = rel(build.DRIVER_ENTRY)
    out = sawc2(["--dump"] + package_args() + [entry])
    matches = 0
    module = None
    for line in out.split("\n"):
        if line.startswith("(Module "):
            module = line[len("(Module "):].strip()
        elif " Match " in line and module is not None and not module.startswith("std."):
            matches += 1
    refused = [l for l in out.split("\n") if l.startswith("ERROR\t")
               and ("\tmatch.non-exhaustive\t" in l or "\tresult.discarded\t" in l)]
    return matches, refused


def check_corpus_refusals():
    """(program, expected rule, rules sawc2 refused it by)."""
    rows = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.saw"))):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "EXPECT-ERROR" not in text and "EXPECT: error" not in text:
            continue
        wanted = None
        for needle, rule in EXPECTED:
            if needle in text.lower() and ("ERROR-CONTAINS" in text):
                for line in text.split("\n"):
                    if "ERROR-CONTAINS" in line and needle in line.lower():
                        wanted = rule
                        break
            if wanted:
                break
        if wanted is None:
            continue
        got = records(sawc2(["--check", rel(path)])).get(rel(path), [])
        rules = sorted({l.split("\t")[1] for l in got if l.startswith("ERROR\t")})
        rows.append((rel(path), wanted, rules))
    return rows


def frozen_frames(path):
    """{name: boundary} of the frames the frozen compiler's ledger records for
    the program's own modules: a free function by its name, a method as
    `Type.method`."""
    r = subprocess.run([sys.executable, SAWC, path, "--emit-frame-ledger"], cwd=REPO,
                       capture_output=True, text=True, timeout=300)
    frames = {}
    for line in r.stdout.split("\n"):
        if not line.startswith("FRAME "):
            continue
        fields = line.split("\t")
        key = fields[0][len("FRAME "):]
        attrs = dict(f.split("=", 1) for f in fields[1:] if "=" in f)
        home = attrs.get("home", "")
        if home in ("task", "channel", "net", "process", "signal", "taskgroup") or home.startswith("std"):
            continue
        kind = attrs.get("kind")
        # A generic template owns no frame; its instances are framed one by
        # one, so the function counts as framed when any instance is.
        framed = attrs.get("boundary") == "yes"
        if kind == "mono-instance":
            key = re.split(r"\$\d+\$", key)[0]
            framed = attrs.get("decision") == "framed"
        name = key.split("$m$")[0]
        if kind in ("method", "mono-instance") and "_" in name:
            owner, _, method = name.partition("_")
            name = "%s.%s" % (owner, method)
        frames[name] = frames.get(name, False) or framed
    return frames, r.returncode


def summary_name(identity):
    parts = identity.split(".")
    if len(parts) >= 2 and parts[-2][:1].isupper():
        return "%s.%s" % (parts[-2], parts[-1])
    return parts[-1]


def check_suspension():
    """Per-function verdicts over the sample."""
    sample = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.saw"))):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "yield_now" in text and not OUTSIDE_SLICE.search(text):
            if "EXPECT-ERROR" in text or "EXPECT: error" in text:
                continue
            sample.append(path)
    out = records(sawc2(["--check", "--summaries"] + [rel(p) for p in sample]))
    tally = collections.Counter()
    disagreements = []
    refused = collections.Counter()
    for path in sample:
        lines = out.get(rel(path), [])
        errors = [l for l in lines if l.startswith("ERROR\t")]
        if errors:
            refused[errors[0].split("\t")[1]] += 1
            continue
        tally["programs compared"] += 1
        mine = {}
        for l in lines:
            if l.startswith("SUMMARY\t"):
                _, identity, suspends, _sync = l.split("\t")
                mine[summary_name(identity)] = suspends != "never-suspends"
        frames, code = frozen_frames(path)
        if code != 0:
            tally["programs the frozen compiler rejects"] += 1
            continue
        for name, framed in sorted(frames.items()):
            if not framed:
                continue
            if name not in mine:
                tally["frozen frames sawc2 has no summary for"] += 1
                disagreements.append("%s: frozen frames `%s`, which sawc2 does not summarize"
                                     % (rel(path), name))
            elif mine[name]:
                tally["framed by the frozen compiler and may-suspend in sawc2"] += 1
            else:
                tally["framed by the frozen compiler, never-suspends in sawc2"] += 1
                disagreements.append("%s: frozen frames `%s`, sawc2 says it never suspends"
                                     % (rel(path), name))
        for name, suspends in sorted(mine.items()):
            if not suspends:
                continue
            if name not in frames:
                tally["may-suspend in sawc2, absent from the frozen ledger"] += 1
            elif not frames[name]:
                tally["may-suspend in sawc2, not framed by the frozen compiler"] += 1
                disagreements.append("%s: sawc2 says `%s` may suspend, the frozen ledger does not frame it"
                                     % (rel(path), name))
    return len(sample), tally, refused, disagreements


def main():
    matches, refused = check_build()
    print("sawc2 build: %d `match` expressions checked, %d refused by the two rules"
          % (matches, len(refused)))
    for line in refused:
        print("  " + line)
    rows = check_corpus_refusals()
    agree = sum(1 for _, want, got in rows if want in got)
    print("corpus refusal programs for the two rules: %d, refused by the expected rule: %d"
          % (len(rows), agree))
    for path, want, got in rows:
        mark = "ok" if want in got else "DIFFERS"
        print("  %s %s: expected %s, sawc2 %s" % (mark, path, want, ", ".join(got) or "nothing"))
    size, tally, refused_sample, disagreements = check_suspension()
    print("suspension sample: %d programs" % size)
    for key, n in sorted(tally.items()):
        print("  %s: %d" % (key, n))
    for key, n in refused_sample.most_common():
        print("  refused by sawc2 first as %s: %d" % (key, n))
    for line in disagreements:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""How much of tests/corpus/ typechecks, for information; nothing gates on it.

    python compiler/tests/typecheck/corpus_info.py

Each program at the top of tests/corpus/ is checked as an entry, in one
`sawc2 typecheck --check` process per set of package mappings. A program that
expects a refusal (an `EXPECT-ERROR` directive) is counted apart: checking it
clean says nothing. The rest are sorted into the ones that check with no
refusal and the ones refused, by the rule of their first refusal, resolve's or
typecheck's. A program the parser refuses has no tree to check, and is counted
apart too. Only signatures are checked so far (U6b1); bodies are not.
"""
import collections
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import build  # noqa: E402

CORPUS = os.path.join(REPO, "tests", "corpus")


def module_paths(path):
    """The `--module-path` mappings a program's COMPILE-FLAGS directive names."""
    flags = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("// COMPILE-FLAGS:"):
                words = line.split(":", 1)[1].split()
                for k, word in enumerate(words):
                    if word == "--module-path" and k + 1 < len(words):
                        mapping = words[k + 1].replace("{TESTDIR}", os.path.dirname(path))
                        name, _, directory = mapping.partition("=")
                        flags += ["--module-path",
                                  "%s=%s" % (name, os.path.relpath(directory, REPO))]
    return tuple(flags)


def first_refusals(rels, flags):
    """{path: the rule of its first refusal, or None} for one sawc2 process."""
    r = subprocess.run([build.SAWC2, "typecheck", "--check"] + list(flags) + rels, cwd=REPO,
                       capture_output=True, text=True)
    first = {}
    current = None
    for line in r.stdout.split("\n"):
        if line.startswith("FILE\t"):
            current = line[len("FILE\t"):]
            first[current] = None
        elif line.startswith("ERROR\t") and current is not None and first[current] is None:
            first[current] = line.split("\t")[1]
        elif line.startswith("INVARIANT\t"):
            INVARIANTS.append("%s: %s" % (current, line))
    return first


INVARIANTS = []


def main():
    entries = sorted(glob.glob(os.path.join(CORPUS, "*.saw")))
    rels = [os.path.relpath(p, REPO) for p in entries]
    groups = collections.defaultdict(list)
    for path, rel in zip(entries, rels):
        groups[module_paths(path)].append(rel)
    first = {}
    for flags, members in sorted(groups.items()):
        first.update(first_refusals(members, flags))
    clean = 0
    expected_refusals = 0
    parse_refused = 0
    rules = collections.Counter()
    for path, rel in zip(entries, rels):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        expects_error = "// EXPECT: error" in text or "// EXPECT-ERROR" in text
        rule = first.get(rel)
        if expects_error:
            expected_refusals += 1
        elif rule is None:
            clean += 1
        elif rule == "resolve.parse-refused":
            parse_refused += 1
        else:
            rules[rule] += 1
    total = len(entries) - expected_refusals
    print("tests/corpus: %d programs, %d expecting a refusal left out" % (len(entries),
                                                                       expected_refusals))
    print("signatures clean: %d of %d (%.1f%%)" % (clean, total, 100.0 * clean / max(total, 1)))
    print("the parser refuses: %d" % parse_refused)
    for rule, n in rules.most_common():
        print("refused first as %s: %d" % (rule, n))
    print("verifier problems: %d" % len(INVARIANTS))
    for line in INVARIANTS:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

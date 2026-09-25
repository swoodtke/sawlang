#!/usr/bin/env python3
"""The grammar corpus: every tracked .saw file's verdict against the record.

    python compiler/tests/grammar/corpus.py              the whole corpus
    python compiler/tests/grammar/corpus.py FILE...      these files only
    python compiler/tests/grammar/corpus.py --write      record the corpus

The record, corpus_expected.tsv, is a statement about GRAMMAR.md: it lists each
file the grammar refuses, with its verdict and a classified reason, and an
unlisted file must be accepted with exactly one tree. `a-removed` names the
removed productions whose enabling alone makes the file parse; otherwise
`a-error` means the frozen parser refuses the file too, and `c-conflict` that it
accepts what the grammar refuses, which a ruling explains. A file refused by a
rule the recognizer does not model yet is listed by hand as UNMODELLED, with the
reason `unmodelled: RULE`; the recognizer must accept it, and `--write` keeps
the row while it does. An ambiguous file, or a listed file that is gone, always
fails.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import extract  # noqa: E402
import recognize  # noqa: E402

REPO = extract.REPO
EXPECTED = os.path.join(HERE, "corpus_expected.tsv")
HEADER = "path\tverdict\treason"
FINDINGS = ("AMBIGUOUS", "NOTREE")
UNMODELLED = "UNMODELLED"
WRITE_HINT = ("if the change is intended, run compiler/tests/grammar/corpus.py --write "
              "and review the diff")


def corpus_paths():
    r = subprocess.run(["git", "ls-files", "-z", "*.saw"], cwd=REPO, capture_output=True,
                       check=True)
    return sorted(p for p in r.stdout.decode("utf-8").split("\0") if p)


def escape(text):
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def load_expected(path=EXPECTED):
    """{path: (verdict, reason)} and any malformed-line complaints."""
    rows, problems = {}, []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if not lines or lines[0] != HEADER:
        problems.append("%s: the first line must be %r" % (os.path.relpath(path, REPO), HEADER))
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = line.split("\t")
        if len(cells) != 3:
            problems.append("%s:%d: want 3 tab-separated cells" % (os.path.relpath(path, REPO), n))
        elif cells[1] == UNMODELLED and not cells[2].startswith("unmodelled: syntax."):
            problems.append("%s:%d: an %s row's reason is `unmodelled: RULE`"
                            % (os.path.relpath(path, REPO), n, UNMODELLED))
        elif cells[0] in rows:
            problems.append("%s:%d: %s is listed twice" % (os.path.relpath(path, REPO), n, cells[0]))
        else:
            rows[cells[0]] = (cells[1], cells[2])
    return rows, problems


class Classifier:
    """Explains one refusal: a removed form, an error test, or a conflict."""

    def __init__(self, model):
        self.model = model
        self.all_removed = recognize.Grammar(model, "all")
        self.removed = [p for p in model.productions if p.status == "removed" and p.nonterminal]
        self.single = {}

    def classify(self, path, verdict, detail):
        if recognize.check_file(self.all_removed, path)[0] == "OK":
            hits = [p.name for p in self.removed
                    if recognize.check_file(self._single(p.nonterminal), path)[0] == "OK"]
            if hits:
                return "a-removed: " + ", ".join(hits)
        cls = "c-conflict" if python_accepts(path) else "a-error"
        return "%s: %s" % (cls, escape(detail))

    def _single(self, nonterminal):
        if nonterminal not in self.single:
            self.single[nonterminal] = recognize.Grammar(self.model, {nonterminal})
        return self.single[nonterminal]


def python_accepts(path):
    """Whether the frozen compiler's lexer and parser take the file."""
    from lexer import Lexer
    from parser import Parser
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    try:
        lexer = Lexer(src)
        tokens = lexer.tokenize()
        Parser(tokens, source_file=path, doc_comments=lexer.doc_comments).parse()
    except Exception:  # noqa: BLE001 - any refusal, a crash included, is not acceptance
        return False
    return True


def run_worker():
    # The record holds repository-relative paths, and so does every message.
    os.chdir(REPO)
    classifier = None
    g = recognize.Grammar(extract.extract())
    for line in sys.stdin:
        path = line.rstrip("\n")
        verdict, detail = recognize.check_file(g, path, trees=True)
        reason = ""
        if verdict in FINDINGS:
            reason = "finding: " + escape(detail)
        elif verdict != "OK":
            classifier = classifier or Classifier(g.model)
            reason = classifier.classify(path, verdict, detail)
        sys.stdout.write(json.dumps([verdict, reason]) + "\n")
    return 0


def verdicts(paths, jobs):
    """{path: (verdict, reason)} for existing paths."""
    results = recognize.run_workers([os.path.abspath(__file__), "--worker"], paths, jobs)
    return {p: tuple(r) for p, r in zip(paths, results)}


def compare(paths, got, expected, gone=()):
    """Failure lines for `paths` (whose verdicts are in `got`) and `gone`."""
    failures = []
    for p in sorted(paths):
        verdict, reason = got[p]
        want = expected.get(p)
        if verdict in FINDINGS:
            failures.append("%s: %s (%s): a text the grammar accepts must have exactly one "
                            "tree after section 13, so this is a finding, not a verdict to "
                            "record" % (p, verdict, reason))
        elif want is None and verdict != "OK":
            failures.append("%s: %s (%s), but it is not listed, so it must be accepted; %s"
                            % (p, verdict, reason, WRITE_HINT))
        elif want is not None and want[0] == UNMODELLED:
            if verdict != "OK":
                failures.append("%s: %s (%s), but listed as refused by a rule the recognizer "
                                "does not model (%s); %s" % (p, verdict, reason, want[1],
                                                             WRITE_HINT))
        elif want is not None and verdict == "OK":
            failures.append("%s: accepted, but listed as %s (%s); %s"
                            % (p, want[0], want[1], WRITE_HINT))
        elif want is not None and (verdict, reason) != want:
            failures.append("%s: %s (%s), but listed as %s (%s); %s"
                            % (p, verdict, reason, want[0], want[1], WRITE_HINT))
    for p in sorted(gone):
        if p in expected:
            failures.append("%s: listed, but no such tracked .saw file; %s" % (p, WRITE_HINT))
    return failures


def write_expected(got, kept, path=EXPECTED):
    """Record each refused file, and each UNMODELLED row of `kept` whose file
    the recognizer still accepts."""
    rows = {p: vr for p, vr in got.items() if vr[0] != "OK"}
    for p, (v, r) in kept.items():
        if v == UNMODELLED and got.get(p, ("",))[0] == "OK":
            rows[p] = (v, r)
    lines = [HEADER] + ["%s\t%s\t%s" % (p, v, r) for p, (v, r) in sorted(rows.items())]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def summary(got, expected):
    counts = {}
    for path, (verdict, reason) in got.items():
        if verdict == "OK":
            unmodelled = expected.get(path, ("",))[0] == UNMODELLED
            key = "unmodelled" if unmodelled else "accepted"
        else:
            key = reason.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    return ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="repository-relative .saw paths")
    ap.add_argument("--write", action="store_true", help="record the whole corpus's verdicts")
    ap.add_argument("--jobs", type=int, default=recognize.default_jobs())
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    if args.worker:
        return run_worker()
    if args.write and args.files:
        ap.error("--write records the whole corpus, so it takes no files")
    tracked = corpus_paths()
    if args.files:
        present = [f for f in sorted(set(args.files)) if os.path.exists(os.path.join(REPO, f))]
        gone = sorted(set(args.files) - set(present))
    else:
        present, gone = tracked, []
    got = verdicts(present, args.jobs) if present else {}
    expected, failures = load_expected()
    if args.write:
        findings = compare([p for p in present if got[p][0] in FINDINGS], got, {})
        for f in failures + findings:
            print(f)
        if failures or findings:
            print("grammar corpus: nothing recorded: %d problem(s)" % len(failures + findings))
            return 1
        write_expected(got, expected)
        print("grammar corpus: recorded %s: %s"
              % (os.path.relpath(EXPECTED, REPO), summary(got, load_expected()[0])))
        return 0
    if not args.files:
        gone = sorted(set(expected) - set(tracked))
    failures += compare(present, got, expected, gone)
    for f in failures:
        print(f)
    print("grammar corpus: %s: %d file(s): %s"
          % ("FAIL (%d)" % len(failures) if failures else "ok", len(present),
             summary(got, expected)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The parse lane: `sawc2 parse` against the parser corpus, as far as the parser claims.

    python compiler/tests/parse_lane.py            run the lane and print its summary
    python compiler/tests/parse_lane.py --verbose  also list the cases not yet claimed,
                                                   and time the one sawc2 process

`compiler/parse/CLAIMS.tsv` lists the GRAMMAR.md alternatives and rules the
parser implements so far (SL-424, contract item 7). The lane runs one `sawc2
parse` process over every case of `compiler/tests/parse/` and every file of
`tests/corpus/`, then judges each case by its expectation:

- a generated, golden or dump-pin case, or a corpus file the grammar accepts,
  whose recognizer record uses claimed alternatives only, must be accepted with
  exactly its expected dump, a tree that keeps the arena's invariants, and a
  derivation record equal to the recognizer's;
- a negative case whose expected refusal is claimed must be refused, first, by
  that name, where `parse-error` accepts any refusal;
- every negative case, and every corpus file the grammar refuses, fails when
  the parser accepts it and every alternative of the parser's own derivation
  is claimed: the parser has claimed that ground and accepted what the
  recognizer refuses;
- the rest counts as not yet, never as a pass.

Each case's recognizer record is computed once and cached under a hash of the
case, GRAMMAR.md and the recognizer's own source. The lane also re-renders
every expected dump through `sawc2 parse --redump`, which must give it back
byte for byte, so the renderer is proven apart from the parser.
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(HERE)
REPO = os.path.dirname(COMPILER)
GRAMMAR_DIR = os.path.join(HERE, "grammar")
sys.path.insert(0, GRAMMAR_DIR)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402
import cases  # noqa: E402
import dump  # noqa: E402
import extract  # noqa: E402
import recognize  # noqa: E402

CLAIMS = os.path.join(COMPILER, "parse", "CLAIMS.tsv")
CLAIMS_HEADER = "claim\tunit"
PARSE_CORPUS = os.path.join(HERE, "parse")
CORPUS = os.path.join(REPO, "tests", "corpus")
WORK = os.path.join(REPO, ".build", "parse-lane")
RECORDS = os.path.join(WORK, "records.json")
PARSE_ERROR = cases.PARSE_ERROR
PARSES_AS = cases.PARSES_AS
SOURCE_FILE = "source-file"
REFUSAL_UNIT = "refusal-unit"
# The C3 shape of SL:hazards: a quote inside a `//` comment inside an
# interpolation, which must be refused end to end.
C3_TEXT = 'func main() { let s = "a {1 // comment: "\n}\n'
C3_RULE = "syntax.lex.unterminated-string"
# The lane's counts, as run.py's summary names them.
ACCEPTED = "parse lane cases accepted as expected"
REFUSED = "parse lane cases refused as expected"
NOT_YET = "parse lane cases not yet claimed"


class Case:
    """One text the parser is run on, and what it must make of it."""

    def __init__(self, origin, name, start, text, path, expect, detail):
        self.origin = origin      # generated, golden, dump, negative, corpus, pin
        self.name = name
        self.start = start
        self.text = text
        self.path = path          # the file sawc2 reads
        self.expect = expect      # "dump", "refuses", "parses-as" or "corpus"
        self.detail = detail      # the dump lines, or the refusal's name
        self.record = None        # the recognizer's alternatives, when it accepts
        self.verdict = None       # the recognizer's verdict, for a corpus file
        self.result = None        # the parser's Result

    @property
    def label(self):
        rel = os.path.relpath(self.path, REPO) if self.origin == "corpus" else self.origin
        return "%s %s" % (rel, self.name) if self.name else rel


class Result:
    """What `sawc2 parse` printed for one file."""

    def __init__(self):
        self.dump = []
        self.errors = []          # (id, position, message)
        self.alternatives = None  # a set, for an accepted file
        self.invariant = None

    @property
    def accepted(self):
        return not self.errors


# ---- claims -------------------------------------------------------------------

def claimable(model):
    """Every name a claim may carry: alternatives, rules and removed productions."""
    names = {a.effective_name for a in model.alternatives()}
    names |= set(model.rule_ids()) | set(model.lexical_rule_ids())
    names |= {p.name for p in model.productions if p.status == "removed"}
    return names


def load_claims(model, failures):
    with open(CLAIMS, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    rel = os.path.relpath(CLAIMS, REPO)
    if not lines or lines[0] != CLAIMS_HEADER:
        failures.append("claims %s: the first line must be %r" % (rel, CLAIMS_HEADER))
    known = claimable(model)
    claims = set()
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        name = line.split("\t")[0]
        if name not in known:
            failures.append("claims %s:%d: %s names no alternative, rule or removed production"
                            % (rel, n, name))
        elif name in claims:
            failures.append("claims %s:%d: %s is claimed twice" % (rel, n, name))
        claims.add(name)
    return claims


# ---- the cases ------------------------------------------------------------------

def expectations(path):
    """{case header: lines} of an expectation file."""
    out = {}
    current = None
    with open(path, encoding="utf-8") as fh:
        for line in fh.read().split("\n"):
            if cases.header_of(line) is not None:
                current = []
                out[line] = current
            elif current is not None:
                current.append(line)
    for lines in out.values():
        while lines and not lines[-1]:
            lines.pop()
    return out


def case_file(start, text):
    """The file under WORK/cases that holds `text`, written once per content."""
    digest = hashlib.sha256((start + "\0" + text).encode("utf-8")).hexdigest()[:20]
    path = os.path.join(WORK, "cases", digest + ".saw")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return path


def collect(failures):
    out = []
    for origin in ("generated", "golden"):
        for path in sorted(glob.glob(os.path.join(PARSE_CORPUS, origin, "*.saw"))):
            want = expectations(os.path.splitext(path)[0] + ".dump")
            for c in cases.read_cases(path):
                lines = want.get(c.header)
                if lines is None:
                    failures.append("parse lane: %s has no expectation for %s"
                                    % (os.path.relpath(path, REPO), c.header))
                    continue
                out.append(Case(origin, c.name, c.start, c.text, case_file(c.start, c.text),
                                "dump", lines))
    for path in sorted(glob.glob(os.path.join(PARSE_CORPUS, "dump", "*.saw"))):
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        with open(os.path.splitext(path)[0] + ".dump", encoding="utf-8") as fh:
            lines = fh.read().split("\n")[:-1]
        out.append(Case("dump", os.path.basename(path), SOURCE_FILE, text, path, "dump", lines))
    for path in sorted(glob.glob(os.path.join(PARSE_CORPUS, "negative", "*.saw"))):
        want = expectations(os.path.splitext(path)[0] + ".expect")
        for c in cases.read_cases(path):
            lines = want.get(c.header)
            if not lines:
                failures.append("parse lane: %s has no expectation for %s"
                                % (os.path.relpath(path, REPO), c.header))
                continue
            f = case_file(c.start, c.text)
            if lines[0] == PARSES_AS:
                out.append(Case("negative", c.name, c.start, c.text, f, "parses-as", lines[1:]))
            else:
                name = lines[0].split(" ")[1]
                out.append(Case("negative", c.name, c.start, c.text, f, "refuses", name))
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.saw"))):
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        out.append(Case("corpus", "", SOURCE_FILE, text, path, "corpus", None))
    out.append(Case("pin", "C3", SOURCE_FILE, C3_TEXT, case_file(SOURCE_FILE, C3_TEXT),
                    "refuses", C3_RULE))
    # A case file no case holds any longer is one an edited case left behind.
    kept = {c.path for c in out}
    for path in glob.glob(os.path.join(WORK, "cases", "*.saw")):
        if path not in kept:
            os.remove(path)
    return out


# ---- the recognizer's records, cached ---------------------------------------------

def salt():
    """A hash of everything a record depends on besides the case itself."""
    h = hashlib.sha256()
    for path in [extract.GRAMMAR] + sorted(glob.glob(os.path.join(GRAMMAR_DIR, "*.py"))):
        with open(path, "rb") as fh:
            h.update(path.encode("utf-8") + b"\0" + fh.read() + b"\0")
    return h.hexdigest()


def record_key(case):
    return hashlib.sha256((case.start + "\0" + case.text).encode("utf-8")).hexdigest()


def needs_record(case):
    return case.expect in ("dump", "parses-as", "corpus")


def load_records(cases_list):
    """Fill each case's record from the cache, computing what it lacks."""
    tag = salt()
    cache = {}
    if os.path.exists(RECORDS):
        with open(RECORDS, encoding="utf-8") as fh:
            stored = json.load(fh)
        if stored.get("salt") == tag:
            cache = stored["records"]
    todo = [c for c in cases_list if needs_record(c) and record_key(c) not in cache]
    if todo:
        jobs = ["%s\t%s\t%d" % (c.start, c.path, 1 if c.expect == "corpus" else 0) for c in todo]
        results = recognize.run_workers([os.path.abspath(__file__), "--worker"], jobs,
                                        recognize.default_jobs())
        for c, result in zip(todo, results):
            cache[record_key(c)] = result
    keep = {}
    for c in cases_list:
        if needs_record(c):
            entry = cache[record_key(c)]
            keep[record_key(c)] = entry
            c.verdict = entry["verdict"]
            c.record = set(entry["alternatives"]) if entry["verdict"] == "OK" else None
            if c.expect == "corpus" and entry["verdict"] == "OK":
                c.detail = entry["dump"]
    if todo or len(keep) != len(cache):
        os.makedirs(WORK, exist_ok=True)
        with open(RECORDS, "w", encoding="utf-8") as fh:
            json.dump({"salt": tag, "records": keep}, fh, sort_keys=True)
    return len(todo)


def run_worker():
    sys.setrecursionlimit(recognize.RECURSION_LIMIT)
    g = recognize.Grammar(extract.extract())
    for line in sys.stdin:
        start, path, want_dump = line.rstrip("\n").split("\t")
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        checked = recognize.check(g, text, trees=True, start=start)
        entry = {"verdict": checked.verdict, "alternatives": [], "dump": None}
        if checked.verdict == "OK":
            entry["alternatives"] = cases.alternatives(checked)
            if want_dump == "1":
                entry["dump"] = dump.source_dump(g, text, checked=checked, start=start)
        sys.stdout.write(json.dumps(entry) + "\n")
    return 0


# ---- running the parser ----------------------------------------------------------

def run_sawc2(args, inputs):
    """{path: body lines} of one `sawc2 parse` process over `inputs`, a list
    of (path, start), and how long it took."""
    os.makedirs(WORK, exist_ok=True)
    listing = os.path.join(WORK, "inputs.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        for path, start in inputs:
            fh.write(("--unit " if start == REFUSAL_UNIT else "") + path + "\n")
    began = time.monotonic()
    r = subprocess.run([build.SAWC2, "parse"] + args + ["@" + listing], capture_output=True)
    took = time.monotonic() - began
    out = r.stdout.decode("utf-8", "replace")
    if out.endswith("\n"):
        out = out[:-1]
    records = {}
    current = None
    for line in out.split("\n"):
        if line.startswith("FILE\t"):
            current = []
            records[line[5:]] = current
        elif current is not None:
            current.append(line)
    return records, took, r.returncode


def parse_result(lines):
    res = Result()
    for line in lines:
        if line.startswith("ERROR\t"):
            fields = line.split("\t")
            res.errors.append((fields[1], fields[2] if len(fields) > 2 else "",
                               fields[3] if len(fields) > 3 else ""))
        elif line.startswith("ALT"):
            res.alternatives = set(line.split("\t")[1:])
        elif line.startswith("INVARIANT\t"):
            res.invariant = line.split("\t", 1)[1]
        elif line:
            res.dump.append(line)
    return res


# ---- judging ------------------------------------------------------------------------

def first_difference(want, got):
    for n in range(max(len(want), len(got))):
        a = want[n] if n < len(want) else "<end>"
        b = got[n] if n < len(got) else "<end>"
        if a != b:
            return "dump line %d: expected %r, got %r" % (n + 1, a[:100], b[:100])
    return "equal"


def judge(case, claims, counts, failures, not_yet):
    res = case.result
    if res is None:
        failures.append("parse lane: %s: sawc2 printed no record" % case.label)
        return
    if res.invariant is not None:
        failures.append("parse lane: %s: the tree breaks an arena invariant: %s"
                        % (case.label, res.invariant))
    derivation_claimed = res.accepted and res.alternatives is not None \
        and res.alternatives <= claims
    if case.expect in ("dump", "parses-as") or (case.expect == "corpus" and case.verdict == "OK"):
        if not case.record <= claims:
            counts[NOT_YET] += 1
            not_yet.append("%s: unclaimed %s" % (case.label,
                                                 ", ".join(sorted(case.record - claims))))
            return
        if not res.accepted:
            failures.append("parse lane: %s: refused (%s at %s: %s), but its alternatives are "
                            "all claimed" % ((case.label,) + res.errors[0]))
            return
        if res.dump != case.detail:
            failures.append("parse lane: %s: %s" % (case.label,
                                                    first_difference(case.detail, res.dump)))
            return
        if res.alternatives != case.record:
            failures.append("parse lane: %s: the derivation record differs from the "
                            "recognizer's: missing %s, extra %s"
                            % (case.label, sorted(case.record - res.alternatives),
                               sorted(res.alternatives - case.record)))
            return
        counts[ACCEPTED] += 1
        return
    # A refused case: a negative, a pin, or a corpus file the grammar refuses.
    if res.accepted:
        if derivation_claimed:
            failures.append("parse lane: %s: accepted, and every alternative of its derivation "
                            "is claimed, but the recognizer refuses it%s"
                            % (case.label, " (%s)" % case.detail if case.detail else ""))
        else:
            counts[NOT_YET] += 1
            not_yet.append("%s: accepted outside the claims" % case.label)
        return
    want = case.detail if case.expect == "refuses" else PARSE_ERROR
    got = res.errors[0][0]
    if want == PARSE_ERROR or want in claims:
        if want != PARSE_ERROR and got != want:
            failures.append("parse lane: %s: refused first by %s at %s, expected %s"
                            % (case.label, got, res.errors[0][1], want))
            return
        counts[REFUSED] += 1
        return
    counts[NOT_YET] += 1
    not_yet.append("%s: its refusal %s is unclaimed (got %s)" % (case.label, want, got))


def synthetic(expect, detail, record, accepted, alternatives=(), dump_lines=(), error=None):
    case = Case("check", "", SOURCE_FILE, "", "", expect, detail)
    case.record = set(record) if record is not None else None
    case.verdict = "OK" if record is not None else "FAIL"
    res = Result()
    if accepted:
        res.alternatives = set(alternatives)
        res.dump = list(dump_lines)
    else:
        res.errors = [(error or PARSE_ERROR, "1:1", "")]
    case.result = res
    return case


def judge_checks():
    """The judge sees what it exists to see: (description, case, claims,
    whether it must fail)."""
    claims = {"a", "b"}
    rows = [
        ("an accepted negative inside the claims fails",
         synthetic("refuses", PARSE_ERROR, None, True, ["a"]), True),
        ("an accepted negative outside the claims is not yet",
         synthetic("refuses", PARSE_ERROR, None, True, ["a", "c"]), False),
        ("a claimed refusal refused by another name fails",
         synthetic("refuses", "a", None, False, error="b"), True),
        ("an unclaimed refusal is not yet",
         synthetic("refuses", "c", None, False, error="b"), False),
        ("a claimed case with another dump fails",
         synthetic("dump", ["(File)"], ["a"], True, ["a"], ["(File x)"]), True),
        ("a claimed case the parser refuses fails",
         synthetic("dump", ["(File)"], ["a"], False), True),
        ("a claimed case whose derivation record differs fails",
         synthetic("dump", ["(File)"], ["a"], True, ["a", "b"], ["(File)"]), True),
        ("a case outside the claims is not yet",
         synthetic("dump", ["(File)"], ["a", "c"], False), False),
    ]
    out = []
    for description, case, must_fail in rows:
        failures = []
        judge(case, claims, {ACCEPTED: 0, REFUSED: 0,
                             NOT_YET: 0}, failures, [])
        if bool(failures) != must_fail:
            out.append("parse lane judge: %s, but it %s" % (description,
                                                           "passes" if must_fail else "fails"))
    return out, len(rows)


def redump_check(all_cases, failures, counts):
    """Every expected dump, read back and rendered again, byte for byte."""
    files = sorted(glob.glob(os.path.join(PARSE_CORPUS, "*", "*.dump"))
                   + glob.glob(os.path.join(PARSE_CORPUS, "negative", "*.expect")))
    corpus_dumps = [c for c in all_cases if c.expect == "corpus" and c.detail]
    extra = os.path.join(WORK, "corpus.dump")
    with open(extra, "w", encoding="utf-8") as fh:
        fh.write("".join("\n".join(c.detail) + "\n" for c in corpus_dumps))
    files.append(extra)
    records, _, code = run_sawc2(["--redump"], [(f, SOURCE_FILE) for f in files])
    for f in files:
        with open(f, encoding="utf-8") as fh:
            want = fh.read()
        got = "\n".join(records.get(f, [])) if f in records else None
        rel = os.path.relpath(f, REPO)
        if got is None:
            failures.append("renderer differential %s: sawc2 printed no record" % rel)
        elif got != want:
            failures.append("renderer differential %s: %s"
                            % (rel, first_difference(want.split("\n"), got.split("\n"))))
    counts["re-rendered dump files"] = len(files)
    counts["re-rendered corpus dumps"] = len(corpus_dumps)
    if code != 0:
        failures.append("renderer differential: sawc2 exited %d" % code)


def run(verbose=False):
    """(failure lines, counts) for run.py."""
    failures = []
    model = extract.extract()
    claims = load_claims(model, failures)
    all_cases = collect(failures)
    computed = load_records(all_cases)
    records, took, code = run_sawc2(["--dump", "--alternatives"],
                                    [(c.path, c.start) for c in all_cases])
    if code not in (0, 1):
        failures.append("parse lane: sawc2 exited %d" % code)
    counts = {ACCEPTED: 0, REFUSED: 0, NOT_YET: 0}
    not_yet = []
    for c in all_cases:
        if c.path in records:
            c.result = parse_result(records[c.path])
        judge(c, claims, counts, failures, not_yet)
    redump_check(all_cases, failures, counts)
    judged, rows = judge_checks()
    failures += judged
    counts["parse lane judge checks"] = rows
    counts["parse lane cases"] = len(all_cases)
    counts["claims"] = len(claims)
    counts["recognizer records computed"] = computed
    if verbose:
        for line in not_yet:
            print("not yet: " + line)
        print("parse lane: one sawc2 process parsed %d files in %.2fs" % (len(all_cases), took))
    return failures, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true",
                    help="list the cases not yet claimed, and time the parse")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        return run_worker()
    ok, output = build.build_sawc2()
    if not ok:
        print("parse lane: sawc2 does not build: %s" % output.strip().split("\n")[-1])
        return 1
    failures, counts = run(args.verbose)
    for f in failures:
        print(f)
    summary = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    print("parse lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

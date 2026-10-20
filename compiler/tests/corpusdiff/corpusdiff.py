#!/usr/bin/env python3
"""The whole-corpus behavioural differential: every tests/corpus program built
and run by sawc2, compared with Stage 0's snapshot of its examples/ twin, and
put in one bucket under one key (SL-655). Its baseline is a regression gate
(SL-666).

    python compiler/tests/corpusdiff/corpusdiff.py check
    python compiler/tests/corpusdiff/corpusdiff.py snapshot [--reuse] [--jobs N] [PATH...]
    python compiler/tests/corpusdiff/corpusdiff.py run [--jobs N] [--no-build] [--baseline | --quick]
                                                       [--report FILE] [PATH...]
    python compiler/tests/corpusdiff/corpusdiff.py gate [--no-build]

`check` says whether the snapshot in stage0/ is whole: one record per corpus
program, each current with its twin. `snapshot` reruns Stage 0 and rewrites
it, for the PATHs named or the whole corpus; `--reuse` keeps every raw result
in .build/corpusdiff/ whose twin is unchanged, so an interrupted write resumes
and a grown corpus snapshots only what is new. `run` checks the snapshot,
builds sawc2 through compiler/tools/build.py (unless `--no-build`), then
measures, writes .build/corpusdiff/results.tsv and report.md, and prints the
report; `--baseline` rewrites corpus_diff.tsv from the run, and otherwise the
run is compared with it. `--quick` checks the whole snapshot but measures one
program per bucket and key of the baseline. `gate` is a whole run on the
gate's worker budget that fails when any program's verdict moved from
corpus_diff.tsv's. `snapshot` and `run` measure one program at a time unless
`--jobs` says otherwise, and none of the three takes the suite lock. README.md
has the buckets and the gate's rule.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
sys.path.insert(0, TESTS)

import oracle  # noqa: E402  (puts coro/, compiler/tools and tools/ on the path)
import build  # noqa: E402
import child_groups  # noqa: E402
import expect  # noqa: E402
import gate_jobs  # noqa: E402

REPO = oracle.REPO
CORPUS = oracle.CORPUS
EXAMPLES = oracle.EXAMPLES
SNAPSHOT = os.path.join(HERE, "stage0")
INDEX = os.path.join(SNAPSHOT, "index.tsv")
BASELINE = os.path.join(HERE, "corpus_diff.tsv")
ANNOTATIONS = os.path.join(HERE, "annotations.tsv")
OUT = os.path.join(REPO, ".build", "corpusdiff")
RAW = os.path.join(OUT, "stage0-raw")

RUN_KINDS = ("success", "panic")
INDEX_COLUMNS = ("path", "triple", "twin", "twin_sha", "expect", "build", "exit", "stdout", "stderr", "log",
                 "meets_expect", "error")
RESULT_COLUMNS = ("path", "bucket", "key", "detail")
ANNOTATION_COLUMNS = ("path", "kind", "reason")
ANNOTATION_KINDS = ("stage0-wrong", "nondeterministic")
BUCKETS = ("pass", "refused", "crash", "wrong", "link", "stage0-wrong", "nondeterministic", "slow")
QUICK_WITHOUT_BASELINE = 20
# The moves the gate prints; the report file holds them all.
GATE_LINES = 40

_XFAIL = re.compile(r"^//\s*XFAIL:\s*(.*)$")
_DIFFERS = re.compile(r"^// differs: (.+)$")
_PRINTS = re.compile(r"^// prints: (.*)$")
_KNOWN_WRONG = re.compile(r"oracle known wrong: (SL-\d+)")
_CITATION = re.compile(r"\b(DF-\d+[a-z]*|SL-\d+|SL:hazards [A-Z]+\d+)\b")
# A Saw panic's line: `panic at FILE:LINE: …`, or `panic: …` from the String
# layer, which has no location to give.
_PANIC = re.compile(r"^panic(?: at |: )[^\n]*$", re.M)


def rel(path):
    return os.path.relpath(path, REPO)


def flat(path):
    return os.path.splitext(path)[0].replace("/", "__")


def programs():
    """Every corpus program, as test_runner.py finds them under examples/:
    each .saw outside a `modules` directory not marked `EXPECT: skip`."""
    found = []
    for root, dirs, files in os.walk(CORPUS):
        dirs.sort()
        here = os.path.relpath(root, CORPUS)
        if "modules" in here.split(os.sep):
            dirs[:] = []
            continue
        for name in files:
            if name.endswith(".saw"):
                path = os.path.normpath(os.path.join(here, name))
                if expect.read(os.path.join(CORPUS, path)).expect != "skip":
                    found.append(path)
    return sorted(found)


def twin_sha(path):
    with open(os.path.join(EXAMPLES, path), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:12]


def record_path(path, triple):
    return os.path.join(SNAPSHOT, triple, os.path.splitext(path)[0] + ".stage0")


def read_index():
    return oracle.read_tsv(INDEX, INDEX_COLUMNS)


def load():
    """{path: Record} for every row of the index."""
    return {row["path"]: oracle.read_record(record_path(row["path"], row["triple"]), oracle.Record(row["path"]))
            for row in read_index()}


def summary(rec):
    """The index row a record determines, but for `twin_sha`."""
    if not rec.ran:
        exit_text = "-"
    else:
        exit_text = "timeout" if rec.exit is None else str(rec.exit)
    return {"path": rec.path, "triple": rec.triple, "twin": rec.twin, "expect": rec.expect, "build": rec.build,
            "exit": exit_text, "stdout": oracle.stream_summary(rec.stdout), "stderr": oracle.stream_summary(rec.stderr),
            "log": oracle.stream_summary(rec.log), "meets_expect": rec.meets_expect or "-",
            "error": rec.build_error or "-"}


# --- the wholeness check ------------------------------------------------------

def check():
    """(failures, counts): one row and one record per corpus program, each
    record the row it is in, and each row's twin unchanged since."""
    failures = []
    try:
        rows = read_index()
    except (OSError, ValueError) as e:
        return ["corpusdiff snapshot: no index: %s" % e], {}
    paths = [r["path"] for r in rows]
    if len(set(paths)) != len(paths):
        failures.append("corpusdiff snapshot: index.tsv names a program twice")
    corpus = programs()
    for path in sorted(set(corpus) - set(paths)):
        failures.append("corpusdiff snapshot: corpus program %s has no record: run `corpusdiff.py snapshot "
                        "--reuse %s`" % (path, path))
    for path in sorted(set(paths) - set(corpus)):
        failures.append("corpusdiff snapshot: %s is no corpus program" % path)
    expected = set()
    for row in rows:
        expected.add(os.path.normpath(record_path(row["path"], row["triple"])))
        if row["path"] not in corpus:
            continue
        try:
            got = summary(oracle.read_record(record_path(row["path"], row["triple"]), oracle.Record(row["path"])))
        except (OSError, ValueError, KeyError, IndexError) as e:
            failures.append("corpusdiff snapshot %s: unreadable: %s" % (row["path"], e))
            continue
        for column in INDEX_COLUMNS:
            if column != "twin_sha" and row[column] != got[column]:
                failures.append("corpusdiff snapshot %s: index.tsv has %s %s, the record %s"
                                % (row["path"], column, row[column], got[column]))
        if row["twin_sha"] != twin_sha(row["path"]):
            failures.append("corpusdiff snapshot %s: examples/%s has changed since its record was written"
                            % (row["path"], row["path"]))
        elif row["twin"] != oracle.twin_of(row["path"])[1]:
            failures.append("corpusdiff snapshot %s: the twin is %s now, %s in its record"
                            % (row["path"], oracle.twin_of(row["path"])[1], row["twin"]))
    files = [INDEX, BASELINE, ANNOTATIONS]
    for root, _, names in os.walk(SNAPSHOT):
        for name in names:
            path = os.path.normpath(os.path.join(root, name))
            if name.endswith(".stage0"):
                files.append(path)
                if path not in expected:
                    failures.append("corpusdiff snapshot: %s is in no row of index.tsv" % rel(path))
    for path in files:
        failures.extend(whitespace_problems(path))
    return failures, {"corpusdiff snapshot records": len(rows), "corpus programs": len(corpus)}


def whitespace_problems(path):
    """A line ending in whitespace, or a file ending in a blank line, which
    `git apply --whitespace=fix` would strip on the patch server."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as fh:
        data = fh.read()
    out = ["corpusdiff: %s:%d ends in whitespace" % (rel(path), k)
           for k, line in enumerate(data.split(b"\n"), 1) if line.endswith((b" ", b"\t", b"\r"))]
    if data.endswith(b"\n\n"):
        out.append("corpusdiff: %s ends in a blank line" % rel(path))
    return out


# --- writing the snapshot -----------------------------------------------------

def raw_path(path):
    return os.path.join(RAW, os.path.splitext(path)[0] + ".json")


def collect(path):
    """Stage 0's raw results for corpus program `path`, saved as they are
    made, so an interrupted write loses one program."""
    src, same = oracle.twin_of(path)
    d = expect.read(src)
    work = os.path.join(OUT, "stage0-work", flat(path))
    os.makedirs(work, exist_ok=True)
    binary = os.path.join(work, "bin")
    if os.path.exists(binary):
        os.remove(binary)
    start = time.monotonic()
    code, log = oracle.stage0(src, binary, d.flags)
    if code == 0 and d.expect == "docs":
        # `--emit-docs` writes the documentation to the `-o` file, and that
        # text is what an `EXPECT: docs` test is judged by.
        with open(binary, encoding="utf-8") as fh:
            log = fh.read() + log
    raw = {"path": path, "twin": same, "twin_sha": twin_sha(path), "expect": d.expect or "-",
           "build_exit": code, "build_seconds": round(time.monotonic() - start, 2), "log": oracle.unrooted(log),
           "runs": []}
    if code == 0 and d.expect in RUN_KINDS:
        for _ in range(oracle.RUNS):
            rc, out, err, seconds = oracle.run_binary(binary)
            raw["runs"].append({"exit": rc, "stdout": oracle.encode(out), "stderr": oracle.encode(err),
                                "seconds": round(seconds, 2)})
    target = raw_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target + ".tmp", "w") as fh:
        json.dump(raw, fh)
    os.replace(target + ".tmp", target)
    return raw


def cached(path):
    """The raw results saved for `path`, when its twin is unchanged since."""
    try:
        with open(raw_path(path)) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    return raw if raw.get("twin_sha") == twin_sha(path) else None


def render(raw, triple):
    """The record's lines for one program's raw results."""
    d = expect.read(os.path.join(EXAMPLES, raw["path"]))
    lines = ["program\t" + raw["path"], "triple\t" + triple, "twin\t" + raw["twin"], "expect\t" + raw["expect"]]
    code, log, kind = raw["build_exit"], raw["log"], raw["expect"]
    if code is None:
        lines.append("build\ttimeout")
    elif code == 0:
        lines.append("build\tok")
    else:
        error = oracle.naming_error(d, log) if kind == "error" else oracle.first_error(log)
        lines.append("build\trefused\t" + (error.strip() or "-"))
    if code == 0 and kind in RUN_KINDS:
        lines.extend(oracle.render_run(raw["runs"]))
    if kind in RUN_KINDS:
        meets = oracle.meets_expect(d, code == 0, raw["runs"])
    elif kind == "error":
        meets = oracle.refusal_meets_expect(d, 1 if code is None else code, log)
    elif code != 0:
        meets = "no: Stage 0 does not build it"
    elif kind == "docs":
        got = [l.strip() for l in log.split("\n") if l.strip() and not l.startswith("Compiled ")]
        meets = "yes" if got == [l.strip() for l in d.output if l.strip()] else "no: the documentation differs"
    else:
        meets = "yes"
    lines.append("meets_expect\t" + meets.replace("\t", " ").strip())
    if code != 0 or kind == "docs":
        lines.extend(oracle.render_log(log))
    return lines


def write_snapshot(args):
    corpus = programs()
    wanted = args.paths or corpus
    unknown = [p for p in wanted if p not in corpus]
    if unknown:
        raise SystemExit("corpusdiff: no corpus program %s" % ", ".join(unknown))
    triple = build.host_triple()
    raws = {}
    if args.reuse:
        raws = {p: r for p in corpus for r in [cached(p)] if r is not None}
    todo = [p for p in wanted if p not in raws]
    print("corpusdiff snapshot: Stage 0 over %d programs, %d at a time" % (len(todo), args.jobs), flush=True)
    start = time.monotonic()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for raw in pool.map(collect, todo):
            raws[raw["path"]] = raw
            done += 1
            if done % 100 == 0:
                print("corpusdiff snapshot: %d of %d, %.0fs" % (done, len(todo), time.monotonic() - start), flush=True)
    keep = {}
    if os.path.exists(INDEX):
        keep = {r["path"]: r for r in read_index() if r["path"] in corpus and r["path"] not in raws}
    rows = []
    for path in corpus:
        if path in keep:
            rows.append(keep[path])
            continue
        if path not in raws:
            continue
        out = record_path(path, triple)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(render(raws[path], triple)) + "\n")
        row = summary(oracle.read_record(out, oracle.Record(path)))
        row["twin_sha"] = raws[path]["twin_sha"]
        rows.append(row)
    listed = {os.path.normpath(record_path(r["path"], r["triple"])) for r in rows}
    for root, _, names in os.walk(SNAPSHOT):
        for name in names:
            path = os.path.normpath(os.path.join(root, name))
            if name.endswith(".stage0") and path not in listed:
                os.remove(path)
    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write("\t".join(INDEX_COLUMNS) + "\n")
        fh.write("".join("\t".join(r[c] for c in INDEX_COLUMNS) + "\n" for r in rows))
    seconds = sum(r["build_seconds"] + sum(x["seconds"] for x in r["runs"]) for p, r in raws.items() if p in todo)
    print("corpusdiff snapshot: %d records, %d written in %.0fs (%.0fs of Stage 0 and its runs)"
          % (len(rows), len(todo), time.monotonic() - start, seconds))
    return 0


# --- annotations ----------------------------------------------------------------

def read_annotations():
    """{path: (kind, reason)} from annotations.tsv."""
    if not os.path.exists(ANNOTATIONS):
        return {}
    rows = oracle.read_tsv(ANNOTATIONS, ANNOTATION_COLUMNS)
    out = {}
    for row in rows:
        if row["kind"] not in ANNOTATION_KINDS:
            raise SystemExit("corpusdiff: annotations.tsv: %s has kind %s, not one of %s"
                             % (row["path"], row["kind"], ", ".join(ANNOTATION_KINDS)))
        if row["kind"] == "stage0-wrong" and not _CITATION.search(row["reason"]):
            raise SystemExit("corpusdiff: annotations.tsv: %s is stage0-wrong with no DF, SL or SL:hazards "
                             "citation" % row["path"])
        out[row["path"]] = (row["kind"], row["reason"])
    return out


def header(src):
    lines = []
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line and not line.strip().startswith("//"):
                break
            lines.append(line)
    return lines


def known_wrong(path, annotations):
    """(citation, the lines sawc2 must print or None) when the program
    carries a known Stage 0 bug: an `XFAIL:` pin, the run lane's
    `// differs:` citing SL:hazards with its `// prints:` lines, an `oracle
    known wrong: SL-nnn`, or a `stage0-wrong` row of annotations.tsv."""
    lines = header(os.path.join(CORPUS, path))
    prints = [m.group(1) for m in map(_PRINTS.match, lines) if m] or None
    for line in lines:
        m = _XFAIL.match(line)
        if m:
            cite = _CITATION.search(m.group(1))
            return "XFAIL " + (cite.group(1) if cite else "uncited"), prints
        m = _DIFFERS.match(line)
        if m and "SL:hazards" in m.group(1):
            return "differs " + _CITATION.search(m.group(1)).group(1), prints
        m = _KNOWN_WRONG.search(line)
        if m:
            return "oracle known wrong " + m.group(1), prints
    kind, reason = annotations.get(path, (None, None))
    if kind == "stage0-wrong":
        return "annotated " + _CITATION.search(reason).group(1), prints
    return None


# --- measuring ------------------------------------------------------------------

_STAGES = {}
_STAGES_LOCK = threading.Lock()
# sawc2's stage commands in pipeline order; each runs every stage before it.
STAGE_COMMANDS = ("parse", "resolve", "typecheck", "mir", "eval", "borrowck", "drops", "mono", "coro")


def refusing_stage(src, flags, rule, where):
    """The stage that refuses `src` by `rule` at `where`: the stage of the
    rule when one stage's source spells it, else the first stage command
    whose check makes that refusal, `llvm` when none before the backend
    does."""
    stage = stage_of(rule)
    if "+" not in stage and stage != "?":
        return stage
    paths = [f for k, f in enumerate(flags) if k > 0 and flags[k - 1] == "--module-path"]
    args = [a for p in paths for a in ("--module-path", p)]
    for command in STAGE_COMMANDS:
        argv = [build.SAWC2, command, "--check"] + ([] if command == "parse" else ["--std-root", "std"] + args)
        try:
            r = subprocess.run(argv + [rel(src)], cwd=REPO, capture_output=True, text=True,
                               timeout=oracle.SAWC2_TIMEOUT)
        except subprocess.TimeoutExpired:
            return stage
        if any(line.split("\t")[1:3] == [rule, where] for line in r.stdout.split("\n")
               if line.startswith("ERROR\t")):
            return command
    return "llvm"


def stage_of(rule):
    """The compiler stage whose source spells `rule`, `+`-joined when several
    do, `?` when none."""
    # Measuring threads call this at once, and one reading a half-filled table
    # would key a refusal by the wrong stage (tools/test_patch_gate.py).
    with _STAGES_LOCK:
        if not _STAGES:
            compiler = os.path.join(REPO, "compiler")
            for name in sorted(os.listdir(compiler)):
                src = os.path.join(compiler, name, "src")
                if not os.path.isdir(src):
                    continue
                text = []
                for root, _, files in os.walk(src):
                    for f in files:
                        if f.endswith(".saw"):
                            with open(os.path.join(root, f), encoding="utf-8") as fh:
                                text.append(fh.read())
                _STAGES[name] = "\n".join(text)
    found = [name for name, text in _STAGES.items() if '"%s"' % rule in text]
    return "+".join(found) if found else "?"


_SOURCES = {}
_STD_NAMES = set()
_DECLARED = re.compile(r"\b(?:struct|enum|trait|func|type)\s+([A-Za-z_]\w*)")
_IDENT = re.compile(r"[A-Za-z_]\w*")


def std_names():
    """Every type, trait and function name std declares."""
    if not _STD_NAMES:
        for root, _, files in os.walk(os.path.join(REPO, "std")):
            for f in files:
                if f.endswith(".saw"):
                    with open(os.path.join(root, f), encoding="utf-8") as fh:
                        _STD_NAMES.update(_DECLARED.findall(fh.read()))
    return _STD_NAMES


def shape(text, path):
    """`text` with what is particular to program `path` made alike, for
    grouping messages by their shape: each backquoted name its source spells
    but std does not declare, since a std name says what is missing, and each
    number but an issue's."""
    if path not in _SOURCES:
        with open(os.path.join(CORPUS, path), encoding="utf-8") as fh:
            _SOURCES[path] = fh.read()
    source = _SOURCES[path]
    out = []
    for part in re.split(r"(`[^`]*`)", text):
        if len(part) >= 2 and part[0] == "`" == part[-1]:
            lead = _IDENT.search(part)
            own = part[1:-1] in source and not (lead and lead.group(0) in std_names())
            out.append("`…`" if own else part)
        else:
            out.append(re.sub(r"(?<!SL-)(?<!DF-)\b\d+\b", "N", part))
    return "".join(out)


def one_line(text, limit=200):
    return oracle.unrooted(text).replace("\t", " ").replace("\n", " ").strip()[:limit].rstrip() or "-"


def usage_flags(log):
    """The flags sawc2's usage text lists for `sawc2 build`."""
    flags = set()
    for line in log.split("\n"):
        if "sawc2 build" in line or (flags and line.startswith(" ")):
            flags.update(re.findall(r"(?<![\w-])(-{1,2}[A-Za-z][\w-]*)", line))
        elif flags:
            break
    return flags


def build_verdict(src, d, rec, code, found, log, wrong_refusal=False):
    """(bucket, key, detail) when the build decides the program's bucket,
    None when it built a program that is run. A refusal test whose refusal
    annotations.tsv marks wrong is judged as any other program is, so one
    sawc2 builds is run."""
    problems = oracle.invariants(log)
    if problems:
        return "crash", "INVARIANT", one_line(problems[0].split("\t")[-1])
    if d.expect == "error" and not wrong_refusal:
        stage0_error = (rec.build_error or "") if rec.expect == "error" else ""
        outcome, detail = oracle.judge_refusal(stage0_error, code, found)
        if outcome == "pass":
            message = next(m for r, _, m in found if r == detail)
            return "pass", "-", one_line("%s: %s" % (detail, message))
        if outcome == "accepted":
            return "wrong", "accepts a refusal test", one_line(stage0_error or "Stage 0 builds it too")
        if outcome == "other":
            return "wrong", "refused by another rule", one_line(detail)
        if outcome == "blocked":
            rule, where, message = next(e for e in found if e[0] in oracle.GAP_RULES)
            return "refused", "%s %s" % (refusing_stage(src, d.flags, rule, where), rule), one_line(message)
    if found:
        rule, where, message = found[0]
        return "refused", "%s %s" % (refusing_stage(src, d.flags, rule, where), rule), one_line(message)
    if code == 0:
        return None if d.expect in RUN_KINDS or wrong_refusal else ("pass", "-", "built")
    if code == 2 and log.startswith("usage:"):
        unknown = [f for f in oracle.sawc2_flags(d.flags) if f.startswith("-") and f not in usage_flags(log)]
        return "refused", "driver driver.usage", "sawc2 build takes no %s" % (" ".join(unknown) or "such arguments")
    if code == 2 and log.startswith("sawc2: unknown target"):
        # A target sawc2 describes no layout for is refused before anything is
        # checked, which is a gap in sawc2, not a fault.
        return "refused", "driver driver.unknown-target", one_line(log)
    panic = _PANIC.search(log)
    if code < 0 or panic:
        return "crash", "sawc2 %s" % (oracle.exit_text(code) if not panic else "panic"), \
            one_line(panic.group(0) if panic else log)
    link = oracle.comparable_link_error(log)
    lines = [l for l in link.split("\n") if l.strip()]
    errors = [l for l in lines if re.search(r"\berror\b|Undefined symbols|ld: ", l)]
    if errors:
        return "link", "clang or the link", one_line(errors[0])
    return "crash", "sawc2 exit %d" % code, one_line(lines[0] if lines else "no output")


def run_verdict(path, d, rec, code, stdout, stderr, annotations):
    """(bucket, key, detail) for a program sawc2 built and ran."""
    own = expect.judge(d, code, stdout, stderr)
    met = "sawc2 meets its directives" if own is None else "sawc2: " + own
    panicked = code == -signal.SIGABRT and _PANIC.search(stdout + stderr) is not None
    if code is not None and code < 0 and not panicked and code != rec.exit:
        return "crash", "run %s" % oracle.exit_text(code), one_line(stdout + stderr or "no output")
    if d.expect == "error":
        # A refusal test states no run, so the detail is what the run did.
        met = "sawc2 builds it, and its run " + (
            "panics: " + _PANIC.search(stdout + stderr).group(0) if panicked else "exits %s" % oracle.exit_text(code))
        met = one_line(met)
    known = known_wrong(path, annotations)
    if known is not None:
        cite, prints = known
        if prints is not None:
            met = "sawc2 prints the stated lines" if stdout.rstrip("\n").split("\n") == prints else \
                "sawc2 does not print the stated lines"
        return "stage0-wrong", cite, met
    if rec.expect != d.expect:
        return ("pass", "-", "judged by its own directives") if own is None else \
            ("wrong", "fails its own directives, whose EXPECT is not the twin's", one_line(own))
    if annotations.get(path, (None,))[0] == "nondeterministic":
        return ("pass", "-", "judged by its directives") if own is None else \
            ("wrong", "fails its directives (nondeterministic)", one_line(own))
    varies = [k for k in ("exit", "stdout", "stderr") if getattr(rec, k) == "varies"]
    if varies:
        return "nondeterministic", "Stage 0's %s varies" % " and ".join(varies), met
    if rec.build != "ok" or not rec.ran:
        return "stage0-wrong", "Stage 0 does not build it (unannotated)", met
    if rec.meets_expect != "yes":
        return "stage0-wrong", "Stage 0 fails its directives (unannotated)", one_line(rec.meets_expect)
    diff = oracle.compare_run(rec, code, stdout, stderr)
    if diff is None:
        return "pass", "-", "-"
    what, detail = diff
    if what == "exit" and panicked and not (isinstance(rec.exit, int) and rec.exit < 0):
        return "wrong", "sawc2's binary panics", one_line(_PANIC.search(stdout + stderr).group(0))
    return "wrong", "%s differs" % what, one_line(detail)


def measure(path, rec, annotations, scale=1):
    """One program's result: its bucket, key and detail, or `timeout` with
    the phase and seconds, and the seconds each phase took."""
    src = os.path.join(CORPUS, path)
    d = expect.read(src)
    binary = os.path.join(OUT, "bin", flat(path))
    if os.path.exists(binary):
        os.remove(binary)
    code, found, log, build_seconds = oracle.sawc2_build(src, binary, d.flags, oracle.SAWC2_TIMEOUT * scale)
    result = {"path": path, "build_seconds": build_seconds, "run_seconds": 0.0}
    if code is None:
        return dict(result, bucket="timeout", phase="build", seconds=build_seconds)
    wrong_refusal = annotations.get(path, (None,))[0] == "stage0-wrong"
    verdict = build_verdict(src, d, rec, code, found, log, wrong_refusal)
    if verdict is None:
        rc, out, err, run_seconds = oracle.run_binary(binary, oracle.RUN_TIMEOUT * scale)
        result["run_seconds"] = run_seconds
        if rc is None:
            return dict(result, bucket="timeout", phase="run", seconds=run_seconds)
        verdict = run_verdict(path, d, rec, rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                              annotations)
        if verdict[0] == "wrong":
            # A run that differs from Stage 0's is run again: one that differs
            # from itself says the program decides less than its output shows.
            again = oracle.run_binary(binary, oracle.RUN_TIMEOUT * scale)
            if again[:3] != (rc, out, err):
                verdict = ("nondeterministic", "sawc2's two runs differ", verdict[2])
    bucket, key, detail = verdict
    return dict(result, bucket=bucket, key=key, detail=detail)


def retried(first, path, rec, annotations):
    """A timed-out program's result after one more try at twice the
    timeouts: `slow` when it finishes, a hang when it does not."""
    again = measure(path, rec, annotations, scale=2)
    seconds = again["build_seconds"] + again["run_seconds"]
    if again["bucket"] == "timeout":
        return dict(again, bucket="crash", key="hang in %s" % again["phase"],
                    detail="timed out after %.0fs, and after %.0fs on a second try"
                           % (first["seconds"], again["seconds"]))
    return dict(again, bucket="slow", key="slow %s" % first["phase"],
                detail="timed out after %.0fs, finished in %.0fs on a second try: %s %s"
                       % (first["seconds"], seconds, again["bucket"], again["key"]),
                settled=(again["bucket"], again["key"], again["detail"]))


def settled(row):
    """A row as the baseline holds it: a `slow` program's verdict is the one
    its second try reached, since whether a run times out depends on the
    machine's load and not on sawc2."""
    if row.get("settled"):
        bucket, key, detail = row["settled"]
        return dict(row, bucket=bucket, key=key, detail=detail)
    return row


def commit():
    """(HEAD, the newest main commit in its history), as git names them."""
    def git(*args):
        r = subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    head = git("rev-parse", "HEAD")
    base = git("merge-base", "HEAD", "origin/main") or git("merge-base", "HEAD", "main")
    dirty = git("status", "--porcelain", "--untracked-files=no", "compiler", "std", "sawc")
    return head + (" (with uncommitted changes)" if dirty else ""), base


def quick_sample():
    """The programs the quick form measures: the first program under each
    bucket and key of corpus_diff.tsv, so every verdict the baseline holds is
    reached once; the first programs of the corpus when there is no
    baseline."""
    corpus = programs()
    if not os.path.exists(BASELINE):
        return corpus[:QUICK_WITHOUT_BASELINE]
    first = collections.OrderedDict()
    for row in oracle.read_tsv(BASELINE, RESULT_COLUMNS):
        if row["path"] in corpus:
            first.setdefault((row["bucket"], row["key"]), row["path"])
    return sorted(set(first.values()))


def measure_all(args):
    if args.baseline and (args.paths or args.quick):
        raise SystemExit("corpusdiff: --baseline is written from a run over the whole corpus only")
    if args.quick:
        failures, _ = check()
        args.paths = [] if failures else quick_sample()
    elif args.paths:
        rows = {r["path"]: r for r in read_index()}
        failures = ["corpusdiff snapshot %s: no current record" % p for p in args.paths
                    if p not in rows or rows[p]["twin_sha"] != twin_sha(p)]
    else:
        failures, _ = check()
    if failures:
        for f in failures[:20]:
            print(f)
        print("corpusdiff: the snapshot is not whole (%d problems), so nothing is measured" % len(failures))
        return 1
    if not args.no_build and not build.handed_down():
        ok, output = build.build_sawc2()
        if not ok:
            print(output)
            print("corpusdiff: sawc2 did not build")
            return 1
    records = load()
    annotations = read_annotations()
    paths = args.paths or sorted(records)
    unknown = [p for p in paths if p not in records]
    if unknown:
        raise SystemExit("corpusdiff: no record for %s" % ", ".join(unknown))
    head, base = commit()
    jobs = min(args.jobs, gate_jobs.jobs())
    print("corpusdiff: sawc2 over %d programs, %d at a time; HEAD %s, main %s" % (len(paths), jobs, head, base),
          flush=True)
    start = time.monotonic()
    lock = threading.Lock()
    done = [0]

    def one(path):
        result = measure(path, records[path], annotations)
        with lock:
            done[0] += 1
            if done[0] % 250 == 0:
                print("corpusdiff: %d of %d, %.0fs" % (done[0], len(paths), time.monotonic() - start), flush=True)
        return result

    results = {r["path"]: r for r in gate_jobs.map_ordered(one, paths, most=jobs)}
    late = [p for p in paths if results[p]["bucket"] == "timeout"]
    for path in late:
        results[path] = retried(results[path], path, records[path], annotations)
    wall = time.monotonic() - start
    rows = [results[p] for p in paths]
    os.makedirs(OUT, exist_ok=True)
    # A partial run writes files of its own, so it never overwrites the last
    # whole run's.
    suffix = "-partial" if args.paths else ""
    write_results(os.path.join(OUT, "results%s.tsv" % suffix), rows)
    if args.baseline:
        write_results(BASELINE, [settled(r) for r in rows])
    lines = report(rows, head, base, wall, records)
    if args.gate:
        found = regressions([settled(r) for r in rows], oracle.read_tsv(BASELINE, RESULT_COLUMNS))
        with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines + [""] + (found or ["No program moved."])) + "\n")
        print("\n".join(counts(rows, head, base, wall)))
        print("corpusdiff gate: the whole report is .build/corpusdiff/report.md")
        for line in found[:GATE_LINES]:
            print(line)
        if len(found) > GATE_LINES:
            print("... and %d more moves" % (len(found) - GATE_LINES))
        if found:
            print("corpusdiff gate: FAIL: %d program(s) moved from corpus_diff.tsv. A move the patch means is "
                  "recorded by `python compiler/tests/corpusdiff/corpusdiff.py run --baseline --jobs N` in the "
                  "same patch, its diff reviewed with the rest." % len(found))
            return 1
        print("corpusdiff gate: ok: all %d programs hold their baseline verdicts" % len(rows))
        return 0
    moved = against_baseline(rows) if not args.baseline and os.path.exists(BASELINE) else []
    text = "\n".join(lines + moved) + "\n"
    with open(args.report or os.path.join(OUT, "report%s.md" % suffix), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text, end="")
    return 0


def regressions(rows, baseline):
    """A line per program whose verdict moved from the baseline's: a new
    bucket or key, a new detail inside `stage0-wrong` (whose detail is the
    oracle's answer), a program the baseline lacks, and a baseline row
    naming no measured program. Improvements count too, so the baseline
    always says what main does."""
    old = {r["path"]: r for r in baseline}
    out = []
    for r in rows:
        was = old.pop(r["path"], None)
        if was is None:
            out.append("corpusdiff gate: %s is not in the baseline; it is now `%s %s`"
                       % (r["path"], r["bucket"], r["key"]))
        elif (was["bucket"], was["key"]) != (r["bucket"], r["key"]):
            out.append("corpusdiff gate: %s moved: `%s %s` -> `%s %s` (%s)"
                       % (r["path"], was["bucket"], was["key"], r["bucket"], r["key"], r["detail"]))
        elif r["bucket"] == "stage0-wrong" and was["detail"] != r["detail"]:
            out.append("corpusdiff gate: %s moved inside `stage0-wrong %s`: `%s` -> `%s`"
                       % (r["path"], r["key"], was["detail"], r["detail"]))
    for path in sorted(old):
        out.append("corpusdiff gate: %s is in the baseline but was not measured" % path)
    return out


def write_results(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(RESULT_COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(r[c] for c in RESULT_COLUMNS) + "\n")


# --- the report -----------------------------------------------------------------

# A gap rule's message names what is missing, so its details group as written;
# any other message groups by its shape.
_NAMED_DETAILS = oracle.GAP_RULES + ("driver.usage", "driver.unknown-target")
# A passing refusal test's detail: its rule, then the message.
_RULE_DETAIL = re.compile(r"^([a-z]+(?:\.[a-z-]+)+): ")


def counts(rows, head, base, wall):
    """The report's head, Markdown: what was measured, and the counts per
    bucket."""
    by_bucket = collections.Counter(r["bucket"] for r in rows)
    lines = ["# corpusdiff: %d corpus programs through sawc2, against Stage 0" % len(rows), "",
             "HEAD `%s`, main `%s`; %.0fs of sawc2 builds, %.0fs of runs, %.0fs wall." % (
                 head, base, sum(r["build_seconds"] for r in rows), sum(r["run_seconds"] for r in rows), wall), "",
             "| bucket | programs |", "|---|---:|"]
    for bucket in BUCKETS:
        lines.append("| %s | %d |" % (bucket, by_bucket.get(bucket, 0)))
    return lines


def report(rows, head, base, wall, records):
    """The report's lines, Markdown: the counts per bucket, then each
    bucket's keys by program count, three example paths each, and for each
    key its most common details."""
    lines = counts(rows, head, base, wall)
    # A refusal test passes on any rule that is no gap when the plan names
    # none, so the rules it passed on show how loose those passes are.
    refusals = collections.Counter(m.group(1) for r in rows if r["bucket"] == "pass"
                                   for m in [_RULE_DETAIL.match(r["detail"])] if m)
    if refusals:
        lines += ["", "## pass: the refusal tests' rules (%d)" % sum(refusals.values()), ""]
        ranked = sorted(refusals.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(", ".join("`%s` %d" % kv for kv in ranked[:20])
                     + ("" if len(ranked) <= 20 else ", and %d more rules" % (len(ranked) - 20)))
    for bucket in BUCKETS:
        mine = [r for r in rows if r["bucket"] == bucket]
        if not mine or bucket == "pass":
            continue
        lines += ["", "## %s (%d)" % (bucket, len(mine)), ""]
        keys = collections.Counter(r["key"] for r in mine)
        for key, n in sorted(keys.items(), key=lambda kv: (-kv[1], kv[0])):
            group = [r for r in mine if r["key"] == key]
            lines.append("- **`%s`**: %d (%s)" % (key, n, ", ".join("`%s`" % r["path"] for r in group[:3])))
            named = any(key.endswith(" " + rule) for rule in _NAMED_DETAILS)
            by_shape = collections.OrderedDict()
            for r in group:
                by_shape.setdefault(r["detail"] if named else shape(r["detail"], r["path"]), []).append(r)
            ranked = sorted(by_shape.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            for text, members in ranked[:8]:
                lines.append("  - %d: %s%s" % (len(members), text, "" if named else "  (`%s`)" % members[0]["path"]))
            if len(ranked) > 8:
                lines.append("  - and %d more details, %d programs"
                             % (len(ranked) - 8, sum(len(m) for _, m in ranked[8:])))
    kinds = collections.Counter((records[r["path"]].expect, r["bucket"]) for r in rows)
    lines += ["", "## by kind", "", "| twin's EXPECT | " + " | ".join(BUCKETS) + " |",
              "|---|" + "---:|" * len(BUCKETS)]
    for kind in sorted({k for k, _ in kinds}):
        lines.append("| %s | %s |" % (kind, " | ".join(str(kinds.get((kind, b), 0)) for b in BUCKETS)))
    return lines


def against_baseline(rows):
    """The lines saying which programs moved since corpus_diff.tsv."""
    old = {r["path"]: r for r in oracle.read_tsv(BASELINE, RESULT_COLUMNS)}
    moves = collections.Counter()
    for r in rows:
        before = old.get(r["path"])
        was = "%s %s" % (before["bucket"], before["key"]) if before else "new"
        now = "%s %s" % (r["bucket"], r["key"])
        if was != now:
            moves[(was, now)] += 1
    lines = ["", "## against corpus_diff.tsv", ""]
    if not moves:
        return lines + ["No program moved."]
    for (was, now), n in sorted(moves.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append("- %d: `%s` -> `%s`" % (n, was, now))
    return lines


def main():
    child_groups.install()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    snap = sub.add_parser("snapshot")
    snap.add_argument("--reuse", action="store_true")
    snap.add_argument("--jobs", type=int, default=1)
    snap.add_argument("paths", nargs="*")
    run = sub.add_parser("run")
    run.add_argument("--jobs", type=int, default=1)
    run.add_argument("--no-build", action="store_true")
    run.add_argument("--baseline", action="store_true")
    run.add_argument("--quick", action="store_true")
    run.add_argument("--report")
    run.add_argument("paths", nargs="*")
    gate = sub.add_parser("gate")
    gate.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.command == "snapshot":
        return write_snapshot(args)
    if args.command == "run":
        args.gate = False
        return measure_all(args)
    if args.command == "gate":
        args.gate, args.jobs, args.baseline, args.quick, args.paths, args.report = \
            True, gate_jobs.jobs(), False, False, [], None
        return measure_all(args)
    failures, counts = check()
    for failure in failures:
        print(failure)
    print("corpusdiff snapshot: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                          ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

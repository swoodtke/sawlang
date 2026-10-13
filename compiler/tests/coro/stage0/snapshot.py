#!/usr/bin/env python3
"""Stage 0's behaviour on the coroutine programs, recorded while Stage 0
exists, so the lanes that compare sawc2 with it outlive `sawc/` (SL:coroutines
§4, unit A0b).

    python compiler/tests/coro/stage0/snapshot.py            # check the snapshot is whole
    python compiler/tests/coro/stage0/snapshot.py --write    # rerun Stage 0, rewrite it
        [--programs LIST] [--refusals LIST] [--jobs N] [--reuse]

The programs are the rows of `index.tsv` and the refusal tests the rows of
`refusals.tsv`; `--programs` and `--refusals` name other lists, one corpus
path per line, for a first or a widened snapshot. Stage 0 compiles each
program's `examples/` twin, since a migrated corpus file need not be in its
grammar, and `twin` says whether the two files are the same. `--reuse` takes
Stage 0's raw results from the last write's `.build/coro-stage0/` instead of
recompiling, to change the format alone.

For each program and each triple in TRIPLES, `TRIPLE/PATH.stage0` holds the
frame layouts (`--emit-frame-layout`) and the backtrace table
(`--emit-bt-table`), or `layout same-as HOST` where both are line for line
the host triple's; for the host triple it also holds the run: exit status,
standard output and standard error, each line JSON-quoted so that no line ends
in whitespace. A run is made RUNS times, and a stream that differs between
runs is recorded as `varies`, with no lines, so two writes over an unchanged
tree give the same bytes. `index.tsv` has one row per program and triple, with
the counts its record determines; `TRIPLE/bt_exec.tsv` is the executor header
of the table, which is the same for every program. For each refusal test,
`refusals.tsv` says whether Stage 0's diagnostics hold the twin's
`EXPECT-ERROR-CONTAINS` texts and gives the error that names the limit, and
`refusals/PATH.stage0` holds the diagnostics whole.

Reading needs only this file: `load()` gives each record.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORO = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(CORO)))
CORPUS = os.path.join(REPO, "tests", "corpus")
EXAMPLES = os.path.join(REPO, "examples")
INDEX = os.path.join(HERE, "index.tsv")
REFUSALS = os.path.join(HERE, "refusals.tsv")
RAW = os.path.join(REPO, ".build", "coro-stage0")
FROZEN_SAWC = os.path.join(REPO, "sawc", "sawc.py")
sys.path.insert(0, CORO)
sys.path.append(os.path.join(REPO, "tools"))

import child_groups  # noqa: E402
import expect  # noqa: E402

# compiler/target's names. Stage 0 runs only the host's binary; the others
# are layout and table only.
TRIPLES = ("arm64-apple-darwin", "x86_64-unknown-linux-gnu")
RUNS = 2
RUN_TIMEOUT = 60
BUILD_TIMEOUT = 900

INDEX_COLUMNS = ("path", "triple", "twin", "expect", "build", "exit", "stdout", "stderr", "meets_expect",
                 "frames", "frame_bytes", "largest_frame", "bt_frames", "bt_states", "bt_bytes")
REFUSAL_COLUMNS = ("path", "twin", "exit", "meets_expect", "errors", "error")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ERROR = re.compile(r"^(?:error\b|\w+ error at )")


def rel(path):
    return os.path.relpath(path, REPO)


def target_name(raw):
    """compiler/target's name for a triple Stage 0 reports, which carries the
    host's OS version on Darwin."""
    return re.sub(r"^(\w+)-apple-(?:darwin|macosx)[\d.]*$", r"\1-apple-darwin", raw)


# --- reading ---------------------------------------------------------------

class Record:
    """One program on one triple, as `TRIPLE/PATH.stage0` holds it.

    `frames` maps a frame symbol to its size, alignment, fields and the rest
    of its layout; `bt` maps a symbol to its table entry, whose `states` are
    (line, child index or -1, child offset). `exit`, `stdout` and `stderr`
    are None on a triple that is not run; a stream that varies between runs
    is the string `varies`."""

    def __init__(self, path, triple):
        self.path = path
        self.triple = triple
        self.twin = None
        self.expect = None
        self.build = None
        self.exit = None
        self.ran = False
        self.meets_expect = None
        self.stdout = None
        self.stderr = None
        self.frames = {}
        self.frame_order = []
        self.bt = {}
        self.bt_order = []
        self.bt_bytes = None


def record_path(path, triple):
    return os.path.join(HERE, triple, os.path.splitext(path)[0] + ".stage0")


def read_record(path, triple):
    rec = Record(path, triple)
    streams = {}
    frame = None
    with open(record_path(path, triple), encoding="utf-8") as fh:
        for line in fh:
            fields = line.rstrip("\n").split("\t")
            kind = fields[0]
            if kind in ("twin", "expect", "build", "meets_expect"):
                setattr(rec, kind, fields[1])
            elif kind == "exit":
                rec.ran = True
                if fields[1] in ("timeout", "varies"):
                    rec.exit = None if fields[1] == "timeout" else "varies"
                else:
                    rec.exit = int(fields[1])
            elif kind in ("stdout", "stderr"):
                if fields[1] == "varies":
                    streams[kind] = "varies"
                else:
                    streams.setdefault(kind, []).append(json.loads(fields[1]))
            elif kind == "frame":
                frame = {"name": fields[2], "size": int(fields[3]), "align": int(fields[4]), "fields": []}
                frame.update(_pairs(fields[5:]))
                rec.frames[fields[1]] = frame
                rec.frame_order.append(fields[1])
            elif kind == "field":
                entry = {"name": fields[1], "kind": fields[2], "offset": int(fields[3]), "size": int(fields[4]),
                         "align": int(fields[5])}
                entry.update(_pairs(fields[6:]))
                frame["fields"].append(entry)
            elif kind == "bt":
                rec.bt_bytes = int(fields[1])
            elif kind == "btframe":
                rec.bt[fields[1]] = {"name": fields[2], "file": fields[3], "state_field": int(fields[4]),
                                     "states": [_state(s) for s in fields[5].split(" ")] if len(fields) > 5 else []}
                rec.bt_order.append(fields[1])
            elif kind == "layout" and fields[1] == "same-as":
                other = read_record(path, fields[2])
                for name in ("frames", "frame_order", "bt", "bt_order", "bt_bytes"):
                    setattr(rec, name, getattr(other, name))
    if rec.ran:
        rec.stdout = streams.get("stdout", "")
        rec.stderr = streams.get("stderr", "")
        for kind in ("stdout", "stderr"):
            value = getattr(rec, kind)
            if isinstance(value, list):
                setattr(rec, kind, "\n".join(value))
    return rec


def _pairs(tokens):
    out = {}
    for token in tokens:
        key, value = token.split("=", 1)
        out[key] = int(value) if re.fullmatch(r"-?\d+", value) else value
    return out


def _state(token):
    m = re.fullmatch(r"(\d+)(?:>(\d+)@(\d+))?", token)
    if m.group(2) is None:
        return int(m.group(1)), -1, 0
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def read_index():
    """The rows of index.tsv, as dicts by column."""
    return _read_tsv(INDEX, INDEX_COLUMNS)


def read_refusals():
    """The rows of refusals.tsv, as dicts by column."""
    return _read_tsv(REFUSALS, REFUSAL_COLUMNS)


def _read_tsv(path, columns):
    rows = []
    with open(path, encoding="utf-8") as fh:
        header = tuple(fh.readline().rstrip("\n").split("\t"))
        if header != columns:
            raise ValueError("%s: the header is %s, not %s" % (rel(path), header, columns))
        for line in fh:
            rows.append(dict(zip(columns, line.rstrip("\n").split("\t"))))
    return rows


def programs():
    """The snapshot's programs, as corpus paths in index order."""
    seen = []
    for row in read_index():
        if row["path"] not in seen:
            seen.append(row["path"])
    return seen


def load(triple=None):
    """{(path, triple): Record} for every row, or for every row of `triple`."""
    return {(row["path"], row["triple"]): read_record(row["path"], row["triple"])
            for row in read_index() if triple is None or row["triple"] == triple}


def summary(rec):
    """The index.tsv row a record determines."""
    sizes = [rec.frames[s]["size"] for s in rec.frame_order]
    if not rec.ran:
        exit_text = "-"
    else:
        exit_text = "timeout" if rec.exit is None else str(rec.exit)
    return {
        "path": rec.path,
        "triple": rec.triple,
        "twin": rec.twin,
        "expect": rec.expect,
        "build": rec.build,
        "exit": exit_text,
        "stdout": _stream_summary(rec.stdout),
        "stderr": _stream_summary(rec.stderr),
        "meets_expect": rec.meets_expect or "-",
        "frames": str(len(sizes)),
        "frame_bytes": str(sum(sizes)),
        "largest_frame": str(max(sizes) if sizes else 0),
        "bt_frames": str(len(rec.bt)),
        "bt_states": str(sum(len(b["states"]) for b in rec.bt.values())),
        "bt_bytes": "-" if rec.bt_bytes is None else str(rec.bt_bytes),
    }


def _stream_summary(text):
    """`-` for a stream not recorded, `varies`, or its byte count and the
    first 12 hex digits of its SHA-256."""
    if text is None:
        return "-"
    if text == "varies":
        return "varies"
    data = text.encode("utf-8", "surrogateescape")
    return "%d:%s" % (len(data), hashlib.sha256(data).hexdigest()[:12])


def check():
    """(failures, counts): every row's record against the row, every record
    in a row, and each triple's executor header present."""
    failures = []
    rows = read_index()
    keys = [(r["path"], r["triple"]) for r in rows]
    if len(set(keys)) != len(keys):
        failures.append("stage0 snapshot: index.tsv names a program twice on one triple")
    for row in rows:
        try:
            got = summary(read_record(row["path"], row["triple"]))
        except (OSError, ValueError, KeyError, IndexError, AttributeError) as e:
            failures.append("stage0 snapshot %s (%s): unreadable: %s" % (row["path"], row["triple"], e))
            continue
        for column in INDEX_COLUMNS:
            if row[column] != got[column]:
                failures.append("stage0 snapshot %s (%s): index.tsv has %s %s, the record %s"
                                % (row["path"], row["triple"], column, row[column], got[column]))
    expected = {os.path.normpath(record_path(p, t)) for p, t in keys}
    for triple in sorted({t for _, t in keys}):
        if not os.path.exists(os.path.join(HERE, triple, "bt_exec.tsv")):
            failures.append("stage0 snapshot: no %s/bt_exec.tsv" % triple)
        for root, _, names in os.walk(os.path.join(HERE, triple)):
            for name in names:
                path = os.path.normpath(os.path.join(root, name))
                if name.endswith(".stage0") and path not in expected:
                    failures.append("stage0 snapshot: %s is in no row of index.tsv" % rel(path))
    refusals = read_refusals()
    for row in refusals:
        if not os.path.exists(refusal_path(row["path"])):
            failures.append("stage0 snapshot: refusal test %s has no %s" % (row["path"],
                                                                          rel(refusal_path(row["path"]))))
    counts = {"stage0 snapshot programs": len(set(p for p, _ in keys)), "stage0 snapshot records": len(keys),
              "stage0 snapshot refusal tests": len(refusals)}
    return failures, counts


# --- writing ---------------------------------------------------------------

def read_list(path):
    """The corpus paths a list names: the first column of each line that is
    neither blank nor a `#` comment, a `top/` prefix meaning the corpus root."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            name = line.split("\t")[0].strip()
            out.append(name[len("top/"):] if name.startswith("top/") else name)
    return out


def stage0(src, out, args):
    """Stage 0 on `src`: (exit status, what it printed, colours removed)."""
    r = subprocess.run([sys.executable, FROZEN_SAWC, rel(src), "-o", out] + list(args), cwd=REPO,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode, _ANSI.sub("", r.stdout + r.stderr)


def run_binary(binary):
    """(exit status, or None on a timeout; stdout; stderr), run from the
    repository root as test_runner.py runs a program."""
    proc = child_groups.start([binary], cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=RUN_TIMEOUT)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        out, err = proc.communicate()
        return None, out, err
    finally:
        child_groups.forget(proc)


def errors(log):
    """The diagnostic lines of a Stage 0 log, each without its `error:`
    prefix or this checkout's path."""
    out = []
    for line in log.split("\n"):
        if _ERROR.match(line):
            text = line.split(": ", 1)[1].strip() if line.startswith("error") else line.strip()
            out.append(text.replace(REPO + os.sep, "").replace("\t", " "))
    return out


def first_error(log):
    found = errors(log)
    if found:
        return found[0]
    lines = [l for l in log.split("\n") if l.strip()]
    return (lines[-1] if lines else "no output").replace(REPO + os.sep, "").replace("\t", " ")


def twin_of(path):
    """(the examples/ twin's path, `same` or `differs`)."""
    src = os.path.join(EXAMPLES, path)
    if not os.path.exists(src):
        raise SystemExit("snapshot: %s has no twin under examples/" % path)
    with open(src, "rb") as a, open(os.path.join(CORPUS, path), "rb") as b:
        return src, "same" if a.read() == b.read() else "differs"


def collect_program(path, host, others):
    """Stage 0's raw results for corpus program `path`, as JSON-able data."""
    src, twin = twin_of(path)
    d = expect.read(src)
    work = os.path.join(RAW, "work", os.path.splitext(path)[0].replace("/", "__"))
    os.makedirs(work, exist_ok=True)
    raw = {"path": path, "twin": twin, "expect": d.expect or "-", "triples": {}}
    for triple in (host,) + others:
        target = [] if triple == host else ["--target", triple]
        entry = {}
        for flag, key in (("--emit-frame-layout", "layout"), ("--emit-bt-table", "bt")):
            out = os.path.join(work, "%s.%s.json" % (key, triple))
            code, log = stage0(src, out, [flag] + target + d.flags)
            if code != 0 or not os.path.exists(out):
                entry[key] = None
                entry[key + "_error"] = first_error(log)
            else:
                with open(out) as fh:
                    entry[key] = json.load(fh)
        raw["triples"][triple] = entry
    binary = os.path.join(work, "bin")
    code, log = stage0(src, binary, d.flags)
    raw["build"] = "ok" if code == 0 else "refused"
    raw["build_error"] = None if code == 0 else first_error(log)
    raw["runs"] = []
    if code == 0:
        for _ in range(RUNS):
            rc, out, err = run_binary(binary)
            raw["runs"].append({"exit": rc, "stdout": base64.b64encode(out).decode("ascii"),
                                "stderr": base64.b64encode(err).decode("ascii")})
    return raw


def collect_refusal(path):
    src, twin = twin_of(path)
    d = expect.read(src)
    work = os.path.join(RAW, "work", "refuse__" + os.path.splitext(path)[0].replace("/", "__"))
    os.makedirs(work, exist_ok=True)
    code, log = stage0(src, os.path.join(work, "bin"), d.flags)
    return {"path": path, "twin": twin, "exit": code, "errors": errors(log) if code else [],
            "first_error": first_error(log) if code else "-", "log": log.replace(REPO + os.sep, "")}


def refusal_row(raw):
    """A refusals.tsv row: whether Stage 0's diagnostics hold every
    `EXPECT-ERROR-CONTAINS` text of the twin, as test_runner.py asks of
    them, and the error that holds the first of them, or Stage 0's first
    error when none does."""
    d = expect.read(os.path.join(EXAMPLES, raw["path"]))
    found = raw["errors"]
    missing = [w for w in d.error_contains if w not in raw["log"]]
    if raw["exit"] == 0:
        meets = "no: Stage 0 builds it"
    elif missing:
        meets = "no: no error contains %r" % missing[0]
    else:
        meets = "yes"
    named = [e for e in found if d.error_contains and d.error_contains[0] in e]
    return [raw["path"], raw["twin"], str(raw["exit"]), meets.replace("\t", " "),
            str(len(found)), named[0] if named else raw["first_error"]]


def refusal_record(raw):
    """`refusals/PATH.stage0`: Stage 0's whole diagnostic output for a
    refusal test, each line JSON-quoted with its trailing whitespace and
    trailing blank lines dropped."""
    lines = [l.rstrip() for l in raw["log"].split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "".join("log\t%s\n" % _quote(l) for l in lines)


def refusal_path(path):
    return os.path.join(HERE, "refusals", os.path.splitext(path)[0] + ".stage0")


def read_refusal_log(path):
    """Stage 0's diagnostic output for refusal test `path`, as one string."""
    with open(refusal_path(path), encoding="utf-8") as fh:
        return "\n".join(json.loads(l.rstrip("\n").split("\t", 1)[1]) for l in fh)


def detect_host():
    """compiler/target's name for the triple Stage 0 builds for here."""
    hello = os.path.join(EXAMPLES, "hello.saw")
    out = os.path.join(RAW, "host.json")
    os.makedirs(RAW, exist_ok=True)
    code, log = stage0(hello, out, ["--emit-frame-layout"])
    if code != 0:
        raise SystemExit("snapshot: Stage 0 cannot report a layout for hello.saw: %s" % log[-300:])
    with open(out) as fh:
        return target_name(json.load(fh)["triple"])


def _decode(data):
    return base64.b64decode(data).decode("utf-8", "surrogateescape")


def _quote(text):
    """One stream line as JSON, readable UTF-8 where it is valid."""
    try:
        return json.dumps(text, ensure_ascii=False).encode("utf-8").decode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(text)


def render(raw, triple, host):
    """The record for `raw` on `triple` as (its header and run lines, its
    layout and table lines, its executor header or None)."""
    lines =["program\t" + raw["path"], "triple\t" + triple, "twin\t" + raw["twin"], "expect\t" + raw["expect"]]
    entry = raw["triples"][triple]
    if triple == host:
        lines.append("build\t" + raw["build"] + ("" if raw["build_error"] is None else "\t" + raw["build_error"]))
    else:
        lines.append("build\tnot-run")
    if triple == host and raw["build"] == "ok":
        runs = raw["runs"]
        codes = {r["exit"] for r in runs}
        lines.append("exit\t" + ("varies" if len(codes) > 1 else ("timeout" if runs[0]["exit"] is None
                                                                   else str(runs[0]["exit"]))))
        for stream in ("stdout", "stderr"):
            texts = {_decode(r[stream]) for r in runs}
            if len(texts) > 1:
                lines.append(stream + "\tvaries")
                continue
            text = texts.pop()
            if text:
                lines.extend(stream + "\t" + _quote(part) for part in text.split("\n"))
        lines.append("meets_expect\t" + raw["meets_expect"])
    head, lines = lines, []
    for key in ("layout", "bt"):
        if entry.get(key) is None:
            lines.append("%s_error\t%s" % (key, entry.get(key + "_error", "missing")))
    layout = entry.get("layout") or {"frames": {}}
    for symbol in sorted(layout["frames"]):
        f = layout["frames"][symbol]
        lines.append("\t".join(["frame", symbol, f["display_name"], str(f["size"]), str(f["align"]),
                                "states=%d" % f["states"], "own=%d" % f["own_bytes"], "sub=%d" % f["sub_bytes"],
                                "bt=%d" % f["bt_index"], "root=%d" % f["is_spawn_root"],
                                "method=%d" % f["is_method"], "agrees=%d" % f["layout_agrees"]]))
        for field in f["fields"]:
            extra = []
            if "callee" in field:
                extra.append("callee=" + field["callee"])
            if "live_state" in field:
                extra.append("live=%d" % field["live_state"])
            for key in sorted(set(field) - {"name", "kind", "offset", "size", "align", "callee", "live_state"}):
                extra.append("%s=%s" % (key, field[key]))
            lines.append("\t".join(["field", field["name"], field["kind"], str(field["offset"]),
                                    str(field["size"]), str(field["align"])] + extra))
    bt = entry.get("bt")
    exec_header = None
    if bt is not None:
        lines.append("bt\t%d\tstrtab=%d\tversion=%d\tword_bits=%d"
                     % (bt["bytes"], bt["strtab_bytes"], bt["version"], bt["word_bits"]))
        exec_header = bt["exec"]
        for f in bt["frames"]:
            states = " ".join(str(s["line"]) if s["child"] < 0 else "%d>%d@%d" % (s["line"], s["child"],
                                                                                  s["child_offset"])
                              for s in f["states"])
            lines.append("\t".join(["btframe", f["symbol"], f["name"], f["file"], str(f["state_field"])]
                                   + ([states] if states else [])))
    return head, lines, exec_header


def write(args):
    program_list = read_list(args.programs) if args.programs else programs()
    refusal_list = read_list(args.refusals) if args.refusals else [r["path"] for r in read_refusals()]
    host = detect_host()
    if host not in TRIPLES:
        raise SystemExit("snapshot: this host builds for %s, which TRIPLES does not name" % host)
    others = tuple(t for t in TRIPLES if t != host)
    cache = os.path.join(RAW, "raw.json")
    raws = {}
    if args.reuse and os.path.exists(cache):
        with open(cache) as fh:
            raws = json.load(fh)
    todo = [p for p in program_list if p not in raws.get("programs", {})]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        got = list(pool.map(lambda p: collect_program(p, host, others), todo))
        refused = list(pool.map(collect_refusal, [p for p in refusal_list
                                                  if "log" not in raws.get("refusals", {}).get(p, {})]))
    raws.setdefault("programs", {}).update({r["path"]: r for r in got})
    raws.setdefault("refusals", {}).update({r["path"]: r for r in refused})
    with open(cache, "w") as fh:
        json.dump(raws, fh)
    for triple in TRIPLES:
        shutil.rmtree(os.path.join(HERE, triple), ignore_errors=True)
    rows = []
    headers = {}
    for path in program_list:
        raw = raws["programs"][path]
        d = expect.read(os.path.join(EXAMPLES, path))
        verdicts = {expect.judge(d, r["exit"], _decode(r["stdout"]), _decode(r["stderr"])) for r in raw["runs"]}
        if raw["build"] != "ok":
            raw["meets_expect"] = "no: Stage 0 does not build it"
        elif verdicts == {None}:
            raw["meets_expect"] = "yes"
        else:
            raw["meets_expect"] = "no: " + sorted(v or "met on another run" for v in verdicts)[0].replace("\t", " ")
        host_body = None
        for triple in (host,) + others:
            head, body, header = render(raw, triple, host)
            if header is not None:
                headers.setdefault(triple, {}).setdefault(json.dumps(header, sort_keys=True), []).append(path)
            if triple == host:
                host_body = body
            elif body == host_body:
                body = ["layout\tsame-as\t" + host]
            out = record_path(path, triple)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(head + body) + "\n")
        for triple in TRIPLES:
            rows.append(summary(read_record(path, triple)))
    for triple, seen in headers.items():
        if len(seen) != 1:
            raise SystemExit("snapshot: the table's executor header differs between programs on %s: %s"
                             % (triple, "; ".join(v[0] for v in seen.values())))
        header = json.loads(next(iter(seen)))
        with open(os.path.join(HERE, triple, "bt_exec.tsv"), "w") as fh:
            fh.write("".join("%s\t%s\n" % (k, header[k]) for k in sorted(header)))
    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write("\t".join(INDEX_COLUMNS) + "\n")
        fh.write("".join("\t".join(r[c] for c in INDEX_COLUMNS) + "\n" for r in rows))
    with open(REFUSALS, "w", encoding="utf-8") as fh:
        fh.write("\t".join(REFUSAL_COLUMNS) + "\n")
        for path in refusal_list:
            fh.write("\t".join(refusal_row(raws["refusals"][path])) + "\n")
    shutil.rmtree(os.path.join(HERE, "refusals"), ignore_errors=True)
    for path in refusal_list:
        out = refusal_path(path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(refusal_record(raws["refusals"][path]))
    return 0


def main():
    child_groups.install()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--programs")
    parser.add_argument("--refusals")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    if args.write:
        return write(args)
    failures, counts = check()
    for failure in failures:
        print(failure)
    print("stage0 snapshot: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok",
                                       ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

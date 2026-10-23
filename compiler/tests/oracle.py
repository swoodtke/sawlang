#!/usr/bin/env python3
"""Stage 0's behaviour on a program, recorded as a snapshot record, and sawc2's
behaviour judged against it: the one format and the one comparison every lane
that holds sawc2 to Stage 0 shares (SL-655, SL-665). No lane runs Stage 0;
each reads its records, and only a snapshot's regeneration runs the v0
compiler, which `v0_compiler` finds.

A record is one file of tab-separated lines, each led by its kind:

    program       PATH                   the corpus path, or the repository path
    triple        TRIPLE                 compiler/target's name for it
    source        SHA                    the program's bytes the record was made from
    twin          same | differs         examples/PATH against tests/corpus/PATH
    expect        KIND                   the twin's `EXPECT:` directive
    build         ok | refused [ERROR] | timeout | not-run
    exit          N | timeout | varies   the run, for a build that is run
    stdout        "LINE" | varies        one line per line, JSON-quoted
    stderr        "LINE" | varies
    meets_expect  yes | no: WHY          whether Stage 0 meets the twin's directives
    log           "LINE"                 Stage 0's own output, when it is the result

A reader keeps the kinds it knows and passes the rest to its caller, which is
how the coroutine snapshot adds frame layouts. Every text is written with the
checkout's root removed, so two checkouts write the same bytes, and a stream
that differs between runs is `varies`, with no lines. A record with a
`source` line is stale once its program's bytes change, and `load_run`
refuses it then.

ENTRY POINTS
    read_record
    load_run
    render_run
    record_run
    sawc2_build
    run_binary
    judge_refusal
    compare_run
"""
import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
CORPUS = os.path.join(REPO, "tests", "corpus")
EXAMPLES = os.path.join(REPO, "examples")
for _path in (os.path.join(TESTS, "coro"), os.path.join(TESTS, "fixpoint"), os.path.join(COMPILER, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
if os.path.join(REPO, "tools") not in sys.path:
    sys.path.append(os.path.join(REPO, "tools"))

import build  # noqa: E402
import child_groups  # noqa: E402
import expect  # noqa: E402
import twin  # noqa: E402

RUNS = 2
RUN_TIMEOUT = 60
STAGE0_TIMEOUT = 900
SAWC2_TIMEOUT = 600

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_STAGE0_ERROR = re.compile(r"^(?:error\b|\w+ error at )")
_SAWC2_ERROR = re.compile(r"^ERROR\t(\S+)\t(\S+)\t(.*)$")
_SAWC2_INVARIANT = re.compile(r"^INVARIANT\t(.*)$")

# The refusals that say sawc2 lacks something, not that the program is wrong.
GAP_RULES = ("import.unknown-module", "name.undefined", "member.unknown", "slice.not-yet", "backend.not-yet",
             "mono.not-yet", "coro.not-yet", "driver.not-yet")

# The sawc2 rule SL:coroutines §3.3 names for a refusal Stage 0 makes, by a
# phrase of Stage 0's message; a test whose message matches none is judged
# by any rule that is not a gap.
PLAN_RULES = (
    ("suspending recursion is not allowed", "coro.suspending-cycle"),
    ("cannot suspend in an `@export` function", "export.suspends"),
    ("cannot suspend in `sync func`", "effect.sync"),
    ("cannot suspend in `deinit` context", "effect.sync"),
    ("cannot suspend in a `sync` closure context", "effect.sync"),
    ("cannot suspend in the `Copy` `copy()`", "effect.sync"),
    ("this closure body suspends", "effect.closure-suspends"),
    ("inside a CLOSURE BODY", "effect.closure-suspends"),
    ("dispatch through `any ", "effect.any-suspends"),
    ("which itself suspends", "coro.drive-in-suspending"),
    ("accepts no borrows", "spawn.borrow"),
    ("a task body may not be `Never`", "spawn.never-body"),
    ("so the task frame cannot cross to a worker thread", "coro.spawn-not-send"),
    ("into a multi-threaded `TaskGroup(threads: ...)`", "coro.spawn-not-send"),
    ("must construct `Alias` with `lends self`", "lends.path"),
)


def rel(path):
    return os.path.relpath(path, REPO)


def unrooted(text):
    """`text` with this checkout's root removed from every path in it."""
    return text.replace(REPO + os.sep, "")


def twin_of(path):
    """(the examples/ twin's path, `same` or `differs`) for corpus `path`."""
    src = os.path.join(EXAMPLES, path)
    if not os.path.exists(src):
        raise SystemExit("oracle: %s has no twin under examples/" % path)
    with open(src, "rb") as a, open(os.path.join(CORPUS, path), "rb") as b:
        return src, "same" if a.read() == b.read() else "differs"


# --- Stage 0 -----------------------------------------------------------------

# The checkout whose `sawc/sawc.py` is `sawc0`, the v0 compiler. This tree
# holds it until `sawc/` is deleted; then this one line names SAWLANG_V0_ROOT
# (SL-667).
V0_ROOT = REPO


def v0_root():
    """The checkout of `sawc0`, the v0 compiler: `V0_ROOT`, or an exit naming
    why it holds none. Every regeneration of a Stage 0 snapshot reaches Stage
    0 through here, and nothing else runs it.

    ENTRY POINTS
        v0_compiler
        v0_python
        stage0
        std_suspension.use_v0_checkout
        migrate/instrument.py
    """
    if not os.path.isfile(os.path.join(V0_ROOT, "sawc", "sawc.py")):
        raise SystemExit("oracle: %s holds no v0 compiler (sawc/sawc.py), and regenerating a Stage 0 "
                         "snapshot needs one" % V0_ROOT)
    return V0_ROOT


def v0_compiler():
    """The argv prefix that runs `sawc0`, with its checkout's venv. It is
    built here, not by the toolchain resolver, whose compiler is whichever
    one `sawc` names."""
    return [v0_python(), os.path.join(v0_root(), "sawc", "sawc.py")]


def v0_python():
    """The Python of the v0 compiler's checkout, its venv's where there is
    one, for an observer that runs its passes in-process."""
    venv_py = os.path.join(v0_root(), ".venv", "bin", "python")
    return venv_py if os.path.isfile(venv_py) else sys.executable


def stage0(src, out, args, timeout=STAGE0_TIMEOUT, cwd=REPO):
    """Stage 0 on `src`: (exit status, or None on a timeout; what it printed,
    colours removed)."""
    try:
        r = subprocess.run(v0_compiler() + [os.path.relpath(src, cwd), "-o", out] + list(args), cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return None, _ANSI.sub("", _text(e.stdout) + _text(e.stderr))
    return r.returncode, _ANSI.sub("", r.stdout + r.stderr)


def _text(data):
    if data is None:
        return ""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else data


def errors(log):
    """The diagnostic lines of a Stage 0 log, each without its `error:`
    prefix or this checkout's path."""
    out = []
    for line in log.split("\n"):
        if _STAGE0_ERROR.match(line):
            text = line.split(": ", 1)[1].strip() if line.startswith("error") else line.strip()
            out.append(unrooted(text).replace("\t", " "))
    return out


def first_error(log):
    found = errors(log)
    if found:
        return found[0]
    lines = [l for l in log.split("\n") if l.strip()]
    return unrooted(lines[-1] if lines else "no output").replace("\t", " ")


def run_binary(binary, timeout=RUN_TIMEOUT, cwd=REPO, arguments=()):
    """(exit status, or None on a timeout; stdout; stderr; seconds), run from
    `cwd`, the repository root as test_runner.py runs a program unless a lane
    runs its own elsewhere. A run that dies by a signal having written nothing
    is run once more, as test_runner.py does, since that is how a binary the
    kernel has not finished validating dies."""
    for attempt in (1, 2):
        start = time.monotonic()
        proc = child_groups.start([binary] + list(arguments), cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = proc.communicate(timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            child_groups.kill(proc)
            out, err = proc.communicate()
            code = None
        finally:
            child_groups.forget(proc)
        seconds = time.monotonic() - start
        if attempt == 1 and code is not None and code < 0 and not out and not err:
            continue
        return code, out, err, seconds


def quote(text):
    """One stream line as JSON, readable UTF-8 where it is valid."""
    try:
        return json.dumps(text, ensure_ascii=False).encode("utf-8").decode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(text)


def decode(data):
    return base64.b64decode(data).decode("utf-8", "surrogateescape")


def encode(data):
    return base64.b64encode(data).decode("ascii")


def render_run(runs):
    """The `exit`, `stdout` and `stderr` lines of Stage 0's runs, each a dict
    of `exit` (None on a timeout) and base64 `stdout` and `stderr`."""
    codes = {r["exit"] for r in runs}
    lines = ["exit\t" + ("varies" if len(codes) > 1 else ("timeout" if runs[0]["exit"] is None
                                                          else str(runs[0]["exit"])))]
    for stream in ("stdout", "stderr"):
        texts = {unrooted(decode(r[stream])) for r in runs}
        if len(texts) > 1:
            lines.append(stream + "\tvaries")
            continue
        text = texts.pop()
        if text:
            lines.extend(stream + "\t" + quote(part) for part in text.split("\n"))
    return lines


def render_log(log):
    """`log` lines: a compiler's whole output, each line JSON-quoted with its
    trailing whitespace and trailing blank lines dropped."""
    lines = [l.rstrip() for l in unrooted(log).split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return ["log\t" + quote(l) for l in lines]


def record_run(src, file, program, flags=(), cwd=REPO, arguments=(), timeout=RUN_TIMEOUT, data=None,
               runs=RUNS):
    """Stage 0 builds `src` with `flags` and runs the binary `runs` times
    (none for a build alone) from `cwd` with `arguments`; the record,
    `program` its path and `data` the bytes its `source` line holds (`src`'s
    own when None), is written to `file` and returned."""
    if data is None:
        with open(src, "rb") as fh:
            data = fh.read()
    binary = os.path.join(REPO, ".build", "stage0-records", rel(file).replace(os.sep, "__"))
    os.makedirs(os.path.dirname(binary), exist_ok=True)
    code, log = stage0(src, binary, flags)
    lines = ["program\t" + program, "triple\t" + build.host_triple(), "source\t" + source_sha(data)]
    if code != 0:
        lines.append("build\t" + ("timeout" if code is None else "refused\t" + first_error(log)))
    else:
        lines.append("build\tok")
        made = []
        for _ in range(runs):
            rc, out, err, _ = run_binary(binary, timeout, cwd, arguments)
            made.append({"exit": rc, "stdout": encode(out), "stderr": encode(err)})
        if made:
            lines.extend(render_run(made))
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return read_record(file, Record(program))


def meets_expect(d, build_ok, runs):
    """`yes`, or `no: WHY`, for a run program whose directives are `d`."""
    if not build_ok:
        return "no: Stage 0 does not build it"
    verdicts = {expect.judge(d, r["exit"], decode(r["stdout"]), decode(r["stderr"])) for r in runs}
    if verdicts == {None}:
        return "yes"
    return "no: " + sorted(v or "met on another run" for v in verdicts)[0].replace("\t", " ")


def refusal_meets_expect(d, code, log):
    """`yes`, or `no: WHY`, for a refusal test: whether Stage 0's diagnostics
    hold every `EXPECT-ERROR-CONTAINS` text, as test_runner.py asks."""
    missing = [w for w in d.error_contains if w not in unrooted(log)]
    if code == 0:
        return "no: Stage 0 builds it"
    if missing:
        return "no: no error contains %r" % missing[0]
    return "yes"


def naming_error(d, log):
    """The error that holds the first `EXPECT-ERROR-CONTAINS` text, or Stage
    0's first error when none does: the one a refusal is judged by."""
    found = errors(log)
    named = [e for e in found if d.error_contains and d.error_contains[0] in e]
    return named[0] if named else first_error(log)


# --- reading -------------------------------------------------------------------

class Record:
    """One program's record. `exit`, `stdout` and `stderr` are None when it
    was not run, and a stream that varied between runs is `varies`; `log` is
    None when the record holds no log."""

    def __init__(self, path):
        self.path = path
        self.triple = None
        self.source = None
        self.twin = None
        self.expect = None
        self.build = None
        self.build_error = None
        self.exit = None
        self.ran = False
        self.meets_expect = None
        self.stdout = None
        self.stderr = None
        self.log = None


def read_record(file, rec, other=None):
    """Fill `rec` from the record at `file`, handing each line of a kind this
    module does not know to `other(fields)`."""
    streams = {}
    log = []
    with open(file, encoding="utf-8") as fh:
        for line in fh:
            fields = line.rstrip("\n").split("\t")
            kind = fields[0]
            if kind == "program":
                rec.path = fields[1]
            elif kind in ("triple", "source", "twin", "expect", "meets_expect"):
                setattr(rec, kind, fields[1])
            elif kind == "build":
                rec.build = fields[1]
                rec.build_error = fields[2] if len(fields) > 2 else None
            elif kind == "exit":
                rec.ran = True
                if fields[1] == "timeout":
                    rec.exit = None
                elif fields[1] == "varies":
                    rec.exit = "varies"
                else:
                    rec.exit = int(fields[1])
            elif kind in ("stdout", "stderr"):
                if fields[1] == "varies":
                    streams[kind] = "varies"
                else:
                    streams.setdefault(kind, []).append(json.loads(fields[1]))
            elif kind == "log":
                log.append(json.loads(fields[1]))
            elif other is not None:
                other(fields)
    if rec.ran:
        for kind in ("stdout", "stderr"):
            value = streams.get(kind, "")
            setattr(rec, kind, "\n".join(value) if isinstance(value, list) else value)
    if log:
        rec.log = "\n".join(log)
    return rec


def source_sha(data):
    """The `source` line's value for a program's bytes."""
    return hashlib.sha256(data).hexdigest()[:16]


def record_file(directory, triple, name):
    """Where the snapshot in `directory` keeps the record of `name` on
    `triple`: a directory per triple, since Stage 0 builds for its host."""
    return os.path.join(directory, triple, name + ".stage0")


def load_run(directory, name, data, regenerate, other=None):
    """The record of `name` in the snapshot in `directory` for this host,
    held current with the program's bytes `data`: (Record, None), or (None,
    why there is none to compare with, naming `regenerate`, the command that
    records it with the v0 compiler)."""
    triple = build.host_triple()
    file = record_file(directory, triple, name)
    if not os.path.exists(file):
        return None, "no Stage 0 record for %s (%s); record it with `%s`" % (triple, rel(file), regenerate)
    rec = read_record(file, Record(name), other)
    if rec.triple != triple or rec.source != source_sha(data):
        return None, "%s is stale, made from other bytes; rerecord it with `%s`" % (rel(file), regenerate)
    return rec, None


def stale_records(directory, names):
    """The record files of the snapshot in `directory` that name no program
    of `names`, on any triple."""
    out = []
    for root, _, files in os.walk(directory):
        for f in sorted(files):
            if f.endswith(".stage0") and f[:-len(".stage0")] not in names:
                out.append(os.path.join(root, f))
    return sorted(out)


def stream_summary(text):
    """`-` for a stream not recorded, `varies`, or its byte count and the
    first 12 hex digits of its SHA-256."""
    if text is None:
        return "-"
    if text == "varies":
        return "varies"
    data = text.encode("utf-8", "surrogateescape")
    return "%d:%s" % (len(data), hashlib.sha256(data).hexdigest()[:12])


def read_tsv(path, columns):
    """The rows of a TSV whose header is `columns`, as dicts by column."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        header = tuple(fh.readline().rstrip("\n").split("\t"))
        if header != columns:
            raise ValueError("%s: the header is %s, not %s" % (rel(path), header, columns))
        for line in fh:
            rows.append(dict(zip(columns, line.rstrip("\n").split("\t"))))
    return rows


# --- sawc2 -------------------------------------------------------------------

# A `COMPILE-FLAGS` flag Stage 0 spells one way and `sawc2 build` another:
# Stage 0's runtime build is `sawc2 build --runtime`, which checks a runtime's
# source (`sawc2 runtime` builds one).
SAWC2_SPELLINGS = {"--runtime-build": "--runtime"}


def sawc2_flags(flags):
    """A program's `COMPILE-FLAGS` as `sawc2 build` spells them."""
    return [SAWC2_SPELLINGS.get(f, f) for f in flags]


def sawc2_build(src, out, flags, timeout=SAWC2_TIMEOUT):
    """`sawc2 build` of `src` against the new std: (exit status, or None on a
    timeout; [(rule, position, message)] of its refusals; what it printed;
    seconds)."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    start = time.monotonic()
    proc = child_groups.start([build.SAWC2, "build", "--std-root", "std"] + sawc2_flags(flags) + [rel(src), "-o", out],
                              cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        so, se = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        child_groups.kill(proc)
        so, se = proc.communicate()
        code = None
    finally:
        child_groups.forget(proc)
    so, se = _text(so), _text(se)
    found = [m.groups() for m in map(_SAWC2_ERROR.match, so.split("\n")) if m]
    return code, found, so + se, time.monotonic() - start


def invariants(log):
    """The `INVARIANT` lines of sawc2's output, each without its kind."""
    return [m.group(1) for m in map(_SAWC2_INVARIANT.match, log.split("\n")) if m]


def plan_rule(message):
    for phrase, rule in PLAN_RULES:
        if phrase in message:
            return rule
    return None


def judge_refusal(stage0_error, code, found):
    """(outcome, detail) for a refusal test whose Stage 0 error is
    `stage0_error`, after a sawc2 build that exited `code` with refusals
    `found`: `pass`, `accepted`, `blocked` (a gap rule refuses it), `other`
    (refused, not by the rule the plan names) or `crash`."""
    want = plan_rule(stage0_error)
    if code is None:
        return "crash", "sawc2 build timed out"
    if code == 0:
        return "accepted", ""
    if not found:
        return "crash", "sawc2 build exit %d with no ERROR line" % code
    gaps = [e for e in found if e[0] in GAP_RULES]
    if gaps:
        return "blocked", "%s %s" % (gaps[0][0], gaps[0][2])
    if want is not None and want not in [e[0] for e in found]:
        return "other", "%s, where the plan names %s" % (found[0][0], want)
    return "pass", found[0][0] if want is None else want


# --- comparing -----------------------------------------------------------------

_PANIC_AT = re.compile(r"panic at ([^:\n]+):(\d+):")


def comparable(text, path, same_twin):
    """A run's stream with what neither compiler's program decides made
    equal: the checkout's root, the corpus root (`examples/` for Stage 0's
    twin), and a `panic at FILE:LINE:` location outside the program, since
    each compiler's std is its own file. The program's own lines are kept
    only when the twin is the same file, as a migration may move them."""
    text = unrooted(text).replace("examples/", "tests/corpus/")
    own = os.path.basename(path)

    def location(m):
        if m.group(1) != own:
            return "panic at <std>:"
        return m.group(0) if same_twin else "panic at %s:?:" % own
    return _PANIC_AT.sub(location, text)


def compare_run(rec, code, stdout, stderr):
    """None when sawc2's run (exit `code`, the two streams as text) is Stage
    0's recorded run `rec`, or (what, detail): what is `exit`, `stdout` or
    `stderr`, the first that differs. A stream recorded as `varies` is not
    compared."""
    same = rec.twin == "same"
    if rec.exit != "varies" and code != rec.exit:
        return "exit", "sawc2 %s, Stage 0 %s" % (exit_text(code), exit_text(rec.exit))
    for name, got, want in (("stdout", stdout, rec.stdout), ("stderr", stderr, rec.stderr)):
        if want == "varies":
            continue
        a = comparable(got, rec.path, same).rstrip("\n")
        b = comparable(want, rec.path, same).rstrip("\n")
        if a != b:
            return name, first_difference(a, b)
    return None


def exit_text(code):
    if code is None:
        return "timeout"
    if isinstance(code, int) and code < 0:
        try:
            return signal.Signals(-code).name
        except ValueError:
            return "signal %d" % -code
    return str(code)


def first_difference(a, b):
    la, lb = a.split("\n"), b.split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: sawc2 %s, Stage 0 %s" % (k + 1, quote(x[:160]), quote(y[:160]))
    return "no line differs"


def comparable_link_error(log):
    """sawc2's link output with clang's temporary object names made equal
    (the fixpoint twin's rule)."""
    return twin.comparable_stderr(["build"], log.encode("utf-8", "replace")).decode("utf-8", "replace")

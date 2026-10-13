#!/usr/bin/env python3
"""How many of the coroutine programs sawc2 builds and passes, for
information; it gates nothing (SL:coroutines §3.2, unit A0b).

    python compiler/tests/coro/census.py [-v] [--gated]

The programs are the Stage 0 snapshot's (`stage0/index.tsv`): the corpus
programs Stage 0 frames at least one function for. Each is built by `sawc2
build` against the new std and, once it builds, run and judged by its own
`EXPECT` directives. The refusal tests are `stage0/refusals.tsv`'s: one passes
when sawc2 refuses it by the rule `PLAN_RULES` gives its Stage 0 message, or
by any rule when the plan names none, with no refusal from `GAP_RULES` beside
it.

A program is gated when its missing names include a std module, a type, or a
member of a type that no unit of the plan provides (`PLAN_MODULES`,
`PLAN_TYPES`, `PLAN_MEMBERS`); the rest is the plan-complete set, which the
plan closes on. Missing names come from sawc2's own refusals, so the set
moves as std grows: a name hidden behind a missing module surfaces once the
module exists. `-v` prints each program's outcome, `--gated` the gated
programs with the names that gate them.
"""
import argparse
import concurrent.futures
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
CORPUS = os.path.join(REPO, "tests", "corpus")
OUT = os.path.join(REPO, ".build", "coro-census")
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "stage0"))

import build  # noqa: E402
import expect  # noqa: E402
import snapshot  # noqa: E402

BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60

# The refusals that say sawc2 lacks something, not that the program is wrong.
GAP_RULES = ("import.unknown-module", "name.undefined", "member.unknown", "slice.not-yet", "backend.not-yet",
             "coro.not-yet")

# The std modules, types and members the plan's units provide (§1 and §4):
# the task surface, `Duration` and `Instant`, `std.channel`, `std.signal`, and
# `std.net`'s cooperative slice (A12b).
PLAN_MODULES = ("std.task", "std.taskgroup", "std.duration", "std.time", "std.channel", "std.signal", "std.net")
PLAN_TYPES = ("Task", "VoidTask", "TaskGroup", "Duration", "Instant", "Channel", "ChannelError", "Signal",
              "SignalWatch", "TcpStream", "TcpListener", "IoError", "IoErrorKind")
# A plan type not named here has every member in the plan.
PLAN_MEMBERS = {"TcpStream": ("pair", "read", "write"), "TcpListener": ("listen", "accept")}

# The sawc2 rule the plan names for a refusal Stage 0 makes, by a phrase of
# Stage 0's message (§3.3, "Language refusals"); a test whose message matches
# none is judged by any rule.
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
)

_ERROR = re.compile(r"^ERROR\t(\S+)\t(\S+)\t(.*)$")
_MODULE = re.compile(r"^no module `([^`]+)`")
_NAME = re.compile(r"^cannot find `([^`]+)` in scope$")
_MEMBER = re.compile(r"^`([^`]+)` has no (?:member|method) `([^`]+)`")


def rel(path):
    return os.path.relpath(path, REPO)


def plan_rule(message):
    for phrase, rule in PLAN_RULES:
        if phrase in message:
            return rule
    return None


def build_program(path):
    """(exit status, [(rule, position, message)], binary) for corpus program
    `path` under `sawc2 build`."""
    src = os.path.join(CORPUS, path)
    binary = os.path.join(OUT, os.path.splitext(path)[0].replace("/", "__"))
    os.makedirs(OUT, exist_ok=True)
    flags = expect.read(src).flags
    try:
        r = subprocess.run([build.SAWC2, "build", "--std-root", "std"] + flags + [rel(src), "-o", binary],
                           cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, [], binary
    errors = [m.groups() for m in map(_ERROR.match, r.stdout.split("\n")) if m]
    return r.returncode, errors, binary


def run_binary(binary):
    proc = subprocess.Popen([binary], cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=RUN_TIMEOUT)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.communicate()
        return None, b"", b""


def missing_names(errors):
    """The std modules, types and members sawc2's refusals say are missing,
    as `module std.x`, `type T` and `member T.m`. A free name is a type when
    it is capitalised and not an enum case written in a pattern (`case
    Value(_)`); a lower-case one is never counted, since any missing module
    may be where it comes from."""
    out = []
    for rule, where, message in errors:
        m = _MODULE.match(message) if rule == "import.unknown-module" else None
        if m:
            out.append("module " + m.group(1))
        m = _NAME.match(message) if rule == "name.undefined" else None
        if m and m.group(1)[:1].isupper() and not _in_case_pattern(where):
            out.append("type " + m.group(1))
        m = _MEMBER.match(message) if rule == "member.unknown" else None
        if m:
            out.append("member %s.%s" % (re.sub(r"<.*", "", m.group(1)).rsplit(".", 1)[-1], m.group(2)))
    return sorted(set(out))


def _in_case_pattern(where):
    """Whether the name at `where` (`PATH:LINE:COL`) follows `case ` on its
    line."""
    path, line, col = where.rsplit(":", 2)
    try:
        with open(os.path.join(REPO, path), encoding="utf-8") as fh:
            text = fh.read().split("\n")[int(line) - 1]
    except (OSError, IndexError):
        return False
    return text[:int(col) - 1].rstrip().endswith("case")


def outside_plan(name):
    kind, what = name.split(" ", 1)
    if kind == "module":
        return what not in PLAN_MODULES
    if kind == "type":
        return what not in PLAN_TYPES
    owner, member = what.rsplit(".", 1)
    if owner not in PLAN_TYPES:
        return True
    return owner in PLAN_MEMBERS and member not in PLAN_MEMBERS[owner]


def census_program(path):
    """(outcome, detail, gating names) for one coroutine program; the
    outcome is `pass`, `fail`, `refused` or `crash`."""
    code, errors, binary = build_program(path)
    gating = [n for n in missing_names(errors) if outside_plan(n)]
    if code is None:
        return "crash", "sawc2 build timed out", gating
    if errors:
        rule, where, message = errors[0]
        return "refused", "%s %s" % (rule, message), gating
    if code != 0:
        return "crash", "sawc2 build exit %d with no ERROR line" % code, gating
    rc, out, err = run_binary(binary)
    verdict = expect.judge(expect.read(os.path.join(CORPUS, path)), rc, out.decode("utf-8", "replace"),
                           err.decode("utf-8", "replace"))
    return ("pass", "", gating) if verdict is None else ("fail", verdict, gating)


def census_refusal(row):
    """(outcome, detail) for one refusal test: `pass`, `accepted`,
    `blocked` (a gap rule refuses it), `other` (refused, not by the rule the
    plan names) or `crash`."""
    code, errors, _ = build_program(row["path"])
    want = plan_rule(row["error"])
    if code is None:
        return "crash", "sawc2 build timed out"
    if code == 0:
        return "accepted", ""
    if not errors:
        return "crash", "sawc2 build exit %d with no ERROR line" % code
    gaps = [e for e in errors if e[0] in GAP_RULES]
    if gaps:
        return "blocked", "%s %s" % (gaps[0][0], gaps[0][2])
    if want is not None and want not in [e[0] for e in errors]:
        return "other", "%s, where the plan names %s" % (errors[0][0], want)
    return "pass", errors[0][0] if want is None else want


def tally(results):
    counts = {}
    for outcome in results:
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def census():
    """(program results by path, refusal results by path), each in the
    snapshot's order."""
    paths = snapshot.programs()
    refusals = snapshot.read_refusals()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        programs = list(pool.map(census_program, paths))
        refused = list(pool.map(census_refusal, refusals))
    return list(zip(paths, programs)), list(zip([r["path"] for r in refusals], refused))


def report(programs, refusals, verbose=False, gated=False):
    """The census's lines: a summary, then the first refusals over the
    plan-complete set; with `verbose` each program, with `gated` the gated
    list."""
    complete = [(p, r) for p, r in programs if not r[2]]
    gated_list = [(p, r) for p, r in programs if r[2]]
    by = tally(r[0] for _, r in programs)
    lines = ["coro census: %d of %d programs pass (%d plan-complete, %d of them passing; %d gated), %d of %d "
             "refusal tests pass"
             % (by.get("pass", 0), len(programs), len(complete), sum(1 for _, r in complete if r[0] == "pass"),
                len(gated_list), sum(1 for _, r in refusals if r[0] == "pass"), len(refusals))]
    lines.append("  programs: " + _counts(by))
    lines.append("  refusal tests: " + _counts(tally(r[0] for _, r in refusals)))
    first = tally(r[1].split(" ")[0] for _, r in complete if r[0] == "refused")
    if first:
        lines.append("  plan-complete programs refused first by: " + _counts(first))
    if verbose:
        for path, (outcome, detail, names) in programs:
            lines.append("  %s\t%s\t%s%s" % (path, outcome, detail, "\tgated by " + ", ".join(names) if names else ""))
        for path, (outcome, detail) in refusals:
            lines.append("  refusal %s\t%s\t%s" % (path, outcome, detail))
    if gated:
        for path, (_, _, names) in gated_list:
            lines.append("  gated %s\t%s" % (path, ", ".join(names)))
    return lines


def _counts(counts):
    return ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def run():
    """(failures, counts, lines) for compiler/tests/run.py: the snapshot must
    be whole, and the census itself is information only."""
    failures, counts = snapshot.check()
    programs, refusals = census()
    counts["coro census programs passing"] = sum(1 for _, r in programs if r[0] == "pass")
    counts["coro census refusal tests passing"] = sum(1 for _, r in refusals if r[0] == "pass")
    return failures, counts, report(programs, refusals)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-v", action="store_true", dest="verbose")
    parser.add_argument("--gated", action="store_true")
    args = parser.parse_args()
    programs, refusals = census()
    for line in report(programs, refusals, args.verbose, args.gated):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

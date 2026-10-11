#!/usr/bin/env python3
"""The run lane: each program here built by sawc2 against the new std and by
Stage 0 against its own, both binaries run, and their standard output and
exit status compared.

    python compiler/tests/run/run_lane.py            # check
    python compiler/tests/run/run_lane.py --write    # rewrite hello.ll
    python compiler/tests/run/run_lane.py NAME...    # just these programs

`compiler/tests/run.py` runs `run()`. Each `NAME.saw` is one case:

- a plain program passes when sawc2's binary, built at -O0 and again at -O2,
  prints the same bytes as Stage 0's and exits with the same status (a
  panic's abort included);
- a program whose first lines are `// due: REASON` and `// refuses: RULE at
  L:C` is one sawc2 cannot build yet: the lane requires `sawc2 build` to
  refuse it first there by that rule, and fails once it builds, so the lines
  come off when the slice reaches it; every rule the backend refuses by
  (`ll_rules` in `compiler/llvm/src/module.saw`) has a due program;
- a program with a `// differs: REASON` line is one whose output the two
  compilers may word differently, for the reason given (a panic raised inside
  std reports std's own file and line, and the two stds are different files):
  the lane compares the exit status and every line but a `panic at` line's
  location; when the reason cites an SL:hazards entry, a timing Stage 0 gets
  wrong, the program's `// prints: LINE` headers are the oracle instead:
  sawc2 must print exactly those lines, and Stage 0 the same lines in some
  other order, since such a hazard moves output and never adds or loses it;
- `hello.saw`'s `.ll`, as the compiler binary writes it, equals `hello.ll`
  byte for byte;
- `sawc2 build --target` refuses every target but the host, and links
  nothing.

Stage 0 is the oracle; a difference is a sawc2 bug until shown otherwise
(SL:architecture §5).
"""
import concurrent.futures
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

SCRIPT = os.path.join(COMPILER, "driver", "sawc2")
OUT = os.path.join(REPO, ".build", "run-lane")
RUN_TIMEOUT = 20
BUILD_TIMEOUT = 600

_DUE = re.compile(r"^// due: (.+)$")
_REFUSES = re.compile(r"^// refuses: (\S+) at (\d+:\d+)$")
_DIFFERS = re.compile(r"^// differs: (.+)$")
_HAZARD = re.compile(r"\bSL:hazards C\d+\b")
_PRINTS = re.compile(r"^// prints: (.*)$")
_PANIC = re.compile(r"^panic at [^:]+:\d+: ")
_RULE = re.compile(r'try! out\.push\("([^"]+)"\)')
RULES_SOURCE = os.path.join(COMPILER, "llvm", "src", "module.saw")
# The targets compiler/target describes; `sawc2 build` links for the host's.
TARGETS = ("arm64-apple-darwin", "x86_64-unknown-linux-gnu")


def rel(path):
    return os.path.relpath(path, REPO)


def headers(path):
    """(due reason, (rule, L:C) it is refused by, differs reason), each
    None when its line is absent."""
    due = refuses = differs = None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.startswith("//"):
                break
            m = _DUE.match(line)
            if m:
                due = m.group(1)
            m = _REFUSES.match(line)
            if m:
                refuses = (m.group(1), m.group(2))
            m = _DIFFERS.match(line)
            if m:
                differs = m.group(1)
    return due, refuses, differs


def stated_prints(path):
    """The output lines a program's `// prints:` headers state, in order."""
    lines = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.startswith("//"):
                break
            m = _PRINTS.match(line)
            if m:
                lines.append(m.group(1))
    return lines


def check_hazard(src, differs, out_new, out_old):
    """Failures for a program whose `// differs:` cites an SL:hazards entry:
    its `// prints:` lines are what sawc2 must print, and Stage 0 must print
    the same lines in another order."""
    stated = stated_prints(src)
    if not stated:
        return ["run %s: cites %s but states no `// prints:` lines" % (rel(src), _HAZARD.search(differs).group(0))]
    want = ("\n".join(stated) + "\n").encode("utf-8")
    failures = []
    if out_new != want:
        failures.append("run %s: sawc2 does not print the stated lines: %s"
                        % (rel(src), first_difference(out_new, want)))
    old_lines = out_old.decode("utf-8", "replace").split("\n")
    if old_lines and old_lines[-1] == "":
        old_lines = old_lines[:-1]
    if out_old == want:
        failures.append("run %s: Stage 0 prints the stated lines, so %s no longer shows here: drop the "
                        "`// differs:` line" % (rel(src), _HAZARD.search(differs).group(0)))
    elif sorted(old_lines) != sorted(stated):
        failures.append("run %s: Stage 0's output differs beyond the order %s moves: %s"
                        % (rel(src), _HAZARD.search(differs).group(0), first_difference(out_old, want)))
    return failures


def first_error(output):
    for line in output.split("\n"):
        if line.startswith("ERROR\t"):
            fields = line.split("\t")
            _, row, col = fields[2].rsplit(":", 2)
            return fields[1], "%s:%s" % (row, col)
    return None


def ll_rules():
    with open(RULES_SOURCE) as fh:
        text = fh.read()
    body = text[text.index("func ll_rules"):]
    body = body[:body.index("move out")]
    return _RULE.findall(body)


def build_new(src, speed="-O0"):
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(OUT, name + (".new" if speed == "-O0" else ".new" + speed[1:]))
    env = dict(os.environ)
    env["SAW_PYTHON"] = sys.executable
    r = subprocess.run([SCRIPT, "build", speed, "--std-root", "std", rel(src), "-o", out], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode == 0, out, (r.stdout + r.stderr).strip()


def build_old(src):
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(OUT, name + ".old")
    r = subprocess.run([sys.executable, build.FROZEN_SAWC, rel(src), "-o", out], cwd=REPO,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode == 0, out, (r.stdout + r.stderr).strip()


def execute(binary):
    try:
        r = subprocess.run([binary], cwd=OUT, capture_output=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, b""
    return r.returncode, r.stdout


def masked(stdout):
    """The output with each `panic at FILE:LINE: ` location removed."""
    lines = stdout.decode("utf-8", "replace").split("\n")
    return "\n".join(_PANIC.sub("panic at ?: ", line) for line in lines)


def first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: sawc2 %r, Stage 0 %r" % (k + 1, x, y)
    return "no line differs"


def check_case(src):
    """(failures, outcome) for one program; outcome is `pass`, `due` or `fail`."""
    due, refuses, differs = headers(src)
    ok_new, new, new_log = build_new(src)
    if due is not None:
        if ok_new:
            return ["run %s: due (%s), but sawc2 builds it now: remove the due lines" % (rel(src), due)], "fail"
        found = first_error(new_log)
        if refuses is None or found != refuses:
            return ["run %s: due, expected %s first, got %s"
                    % (rel(src), "a `// refuses: RULE at L:C` line" if refuses is None
                       else "%s at %s" % refuses, "nothing" if found is None else "%s at %s" % found)], "fail"
        return [], "due"
    if not ok_new:
        first = next((l for l in new_log.split("\n") if l.startswith(("ERROR", "INVARIANT"))), new_log[:300])
        return ["run %s: sawc2 does not build it: %s" % (rel(src), first)], "fail"
    ok_old, old, old_log = build_old(src)
    if not ok_old:
        return ["run %s: Stage 0 does not build it: %s" % (rel(src), old_log[-300:])], "fail"
    ok_fast, fast, fast_log = build_new(src, "-O2")
    if not ok_fast:
        return ["run %s: sawc2 does not build it at -O2: %s" % (rel(src), fast_log[:300])], "fail"
    code_old, out_old = execute(old)
    failures = []
    for speed, binary in (("-O0", new), ("-O2", fast)):
        code_new, out_new = execute(binary)
        where = "%s %s" % (rel(src), speed)
        if code_new is None or code_old is None:
            failures.append("run %s: a binary timed out" % where)
        elif code_new != code_old:
            failures.append("run %s: exit %d under sawc2, %d under Stage 0" % (where, code_new, code_old))
        if differs is not None and _HAZARD.search(differs):
            failures.extend("%s (%s)" % (f, speed) for f in check_hazard(src, differs, out_new, out_old))
        elif differs is not None:
            if masked(out_new) != masked(out_old):
                failures.append("run %s: output differs beyond a panic location: %s"
                                % (where, first_difference(out_new, out_old)))
        elif out_new != out_old:
            failures.append("run %s: output differs: %s" % (where, first_difference(out_new, out_old)))
    return failures, "fail" if failures else "pass"


def cases(names=None):
    found = sorted(glob.glob(os.path.join(HERE, "*.saw")))
    if names:
        found = [p for p in found if os.path.splitext(os.path.basename(p))[0] in names]
    return found


def check_pinned_ir(failures, counts, write):
    """hello.saw's `.ll`, as the compiler binary writes it for the default
    target, against hello.ll. The script's build names the host clang's own
    triple in the module, which is a fact about the host, so the pin reads the
    binary's output instead."""
    pinned = os.path.join(HERE, "hello.ll")
    r = subprocess.run([build.SAWC2, "build", "--std-root", "std", rel(os.path.join(HERE, "hello.saw"))],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run hello: sawc2 build wrote no .ll: %s" % r.stdout.strip()[:300])
        return
    text = r.stdout
    if write:
        with open(pinned, "w") as fh:
            fh.write(text)
        return
    if not os.path.exists(pinned):
        failures.append("run hello: no pinned %s" % rel(pinned))
        return
    with open(pinned) as fh:
        expected = fh.read()
    if expected != text:
        a = expected.split("\n")
        b = text.split("\n")
        k = next((i for i in range(max(len(a), len(b)))
                  if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), 0)
        failures.append("run hello: the .ll differs from %s at line %d" % (rel(pinned), k + 1))
    counts["run pinned .ll files"] = counts.get("run pinned .ll files", 0) + 1


def check_foreign_targets(failures, counts):
    """`sawc2 build --target T` for every target but the host is refused
    before anything links, and leaves no binary: the runtime objects are the
    host's, so a foreign triple would be linked into a host binary."""
    hello = os.path.join(HERE, "hello.saw")
    probe = os.path.join(OUT, "foreign")
    env = dict(os.environ)
    env["SAW_PYTHON"] = sys.executable
    refused = 0
    for triple in TARGETS:
        if os.path.exists(probe):
            os.remove(probe)
        r = subprocess.run([SCRIPT, "build", "--std-root", "std", "--target", triple, rel(hello), "-o", probe],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if r.returncode == 0:
            continue
        refused += 1
        if "is not this host" not in r.stderr or os.path.exists(probe):
            failures.append("run target %s: refused without saying it is not the host, or a binary was "
                            "written: %s" % (triple, (r.stdout + r.stderr).strip()[:300]))
    if refused != len(TARGETS) - 1:
        failures.append("run target: %d of %d targets refused; every one but the host should be"
                        % (refused, len(TARGETS)))
    counts["run foreign targets refused"] = refused


def run(names=None, write=False):
    os.makedirs(OUT, exist_ok=True)
    failures = []
    counts = {}
    srcs = cases(names)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check_case, srcs))
    dues = []
    covered = set()
    for src, (found, outcome) in zip(srcs, results):
        failures.extend(found)
        key = {"pass": "run programs matching Stage 0", "due": "run programs due",
               "fail": "run programs failing"}[outcome]
        counts[key] = counts.get(key, 0) + 1
        due, refuses, _ = headers(src)
        if outcome == "due":
            dues.append("%s (%s)" % (os.path.basename(src), due))
            covered.add(refuses[0])
    if not names:
        for rule in ll_rules():
            if rule not in covered:
                failures.append("run rule %s: no due program is refused by it" % rule)
        check_pinned_ir(failures, counts, write)
        check_foreign_targets(failures, counts)
    return failures, counts, dues


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    failures, counts, dues = run(names, "--write" in sys.argv[1:])
    for failure in failures:
        print(failure)
    for due in dues:
        print("due: %s" % due)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("run lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The run lane: each program here built by sawc2 against the new std and
run, and its standard output and exit status compared with Stage 0's recorded
run of it, built against its own std.

    python compiler/tests/run/run_lane.py            # check
    python compiler/tests/run/run_lane.py --write    # rewrite hello.ll and noalias.defines
    python compiler/tests/run/run_lane.py NAME...    # just these programs and probes
    python compiler/tests/run/run_lane.py --stage0 [NAME...]   # record Stage 0's runs
    python compiler/tests/run/run_lane.py --bench    # the timing report over bench/
    python compiler/tests/run/run_lane.py --target TRIPLE   # sawc2's side cross-built

`compiler/tests/run.py` runs `run()`. Each `NAME.saw` is one case:

- a plain program passes when sawc2's binary, built at -O0 and again at -O2,
  prints the same bytes as Stage 0's recorded run on standard output and on
  standard error, where a panic's message goes, and exits with the same
  status (a panic's abort included); the record is `stage0/HOST/NAME.stage0`,
  written by `--stage0` through the v0 compiler, and a program without one,
  or whose bytes changed since it was made, fails until it is rerecorded;
- a program whose first lines are `// due: REASON` and `// refuses: RULE at
  L:C` is one sawc2 cannot build yet: the lane requires `sawc2 build` to
  refuse it first there by that rule, and fails once it builds, so the lines
  come off when the slice reaches it; every rule the backend refuses by
  (`ll_rules` in `compiler/llvm/src/module.saw`) has a due program;
- a program with a `// differs: REASON` line is one whose output the two
  compilers may word differently, for the reason given (a panic raised inside
  std reports std's own file and line, and the two stds are different files):
  the lane compares the exit status and every line of both streams but a
  `panic at` line's location; when the reason cites an SL:hazards entry, a
  timing Stage 0 gets wrong, the program's `// prints: LINE` headers are the
  standard output's oracle instead:
  sawc2 must print exactly those lines, and Stage 0 the same lines in some
  other order, since such a hazard moves output and never adds or loses it;
- a build that links prints nothing: the runtime it links is built at the
  module's own target, so the linker has nothing to warn about;
- `hello.saw`'s `.ll`, as the compiler binary writes it, equals `hello.ll`
  byte for byte, and `runtime/host_macos/dirent.saw`'s, as `sawc2 runtime`
  writes it, `runtime_dirent.ll`;
- `noalias.saw`'s own `define` lines equal `noalias.defines`, and a sawc2
  built from a copy of the backend whose `noalias` funnel skips its
  cell-carrying test fails that comparison at the cell-carrying `&` parameter;
- every `define` in those two `.ll` files, and in `frame_pointers.saw`'s,
  carries `"frame-pointer"="non-leaf"`, so a function the backend writes
  outside its function attribute funnel is caught;
- `sawc2 build --target` links for the host and every target whose runtime
  `build.py --runtime` configured, and refuses every other target, linking
  nothing; with `--target TRIPLE` the lane builds sawc2's side of every
  program for TRIPLE (its runtime configured first) and holds it to Stage 0's
  host build, so a cross-built binary meets the host's expectations;
- `sawc2 runtime` writes the same bytes into two directories, and refuses a
  copy of the runtime that leaves a seam undefined or defines one twice;
- each `probes/NAME.saw` states in its leading comment lines how it is held
  (README.md, "Probes"): `// probe: stated` is built by sawc2 alone at its
  `// speeds:` with nothing printed and prints exactly its `// prints:` lines,
  `// probe: panics` prints them and then panics with its `// panics:` text,
  `// probe: link-fails` fails to link with each `// undefined:` symbol
  undefined, and `// ll defines:` and `// ll omits:` hold each build's `.ll`;
  a `// probe: custom` one is checked by its function in `CUSTOM_PROBES`, a
  `// probe: module` one is imported by another probe and never built alone,
  and a probe stating no kind, or a kind's lines wrongly, fails the lane;
- `probes/executable_path.saw`, the custom probe, built by sawc2 and run
  through a renamed symbolic link on `PATH` from another directory, prints its
  binary's real path;
- a generated accessor with a local live across its `lend` and 1100 `if`s
  after it, which Stage 0 cannot parse, is held as a stated probe to the `42`
  and `5` it prints;
- no record in `stage0/` names a program that is gone.

`--stage0` records Stage 0's runs of every program not due, or of the NAMEs,
for this host; `--bench` times each kernel of `bench/` under sawc2 at -O2 and
under Stage 0 and prints the report, which gates nothing. Those two run the v0
compiler (`oracle.v0_compiler`); the check never does, and the runner never
runs either.

Stage 0's recorded run is the oracle; a difference is a sawc2 bug until shown
otherwise (SL:architecture §5).
"""
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))
sys.path.insert(0, TESTS)
sys.path.append(os.path.join(REPO, "tools"))

import build  # noqa: E402
import gate_jobs  # noqa: E402
import oracle  # noqa: E402

OUT = os.path.join(REPO, ".build", "run-lane")
# Stage 0's recorded runs, one directory per host triple (README.md, "The
# oracle").
STAGE0 = os.path.join(HERE, "stage0")
# The target sawc2 builds the programs for, None for the host. The oracle is
# Stage 0's run on the host either way: the expected output is the same on
# every target, which is the claim a cross-built program is held to.
TARGET = None


def target_flags():
    return ["--target", TARGET] if TARGET else []


def set_target(triple):
    """Build sawc2's side for `triple` (None for the host), into a directory
    of its own so two targets' binaries never mix."""
    global TARGET, OUT
    TARGET = triple
    OUT = os.path.join(REPO, ".build", "run-lane" + ("-" + triple if triple else ""))
RUN_TIMEOUT = 20
BENCH_REPS = 5
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
TARGETS = ("arm64-apple-darwin", "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu")
# The target the pinned `.ll` files are written for.
PINNED_TARGET = "arm64-apple-darwin"


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
    the same lines in another order; `out_old` is None when Stage 0's order
    varied between its recorded runs, which the hazard allows."""
    stated = stated_prints(src)
    if not stated:
        return ["run %s: cites %s but states no `// prints:` lines" % (rel(src), _HAZARD.search(differs).group(0))]
    want = ("\n".join(stated) + "\n").encode("utf-8")
    failures = []
    if out_new != want:
        failures.append("run %s: sawc2 does not print the stated lines: %s"
                        % (rel(src), first_difference(out_new, want)))
    if out_old is None:
        return failures
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
    """sawc2's build of `src` at `speed`: whether it linked, the binary, and
    what it printed. The runtime it links is built at the module's own target,
    so a build that links prints nothing."""
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(OUT, name + (".new" if speed == "-O0" else ".new" + speed[1:]))
    r = subprocess.run([build.SAWC2, "build", speed, "--std-root", "std"] + target_flags() + [rel(src), "-o", out],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode == 0, out, (r.stdout + r.stderr).strip()


def stage0_command(names=()):
    return "python compiler/tests/run/run_lane.py --stage0" + "".join(" " + n for n in names)


_MODULE_IMPORT = re.compile(rb"^import modules\.(\w+)", re.M)


def program_data(src):
    """The bytes a program's Stage 0 record is made from: its source, then
    each `modules/NAME.saw` it imports."""
    with open(src, "rb") as fh:
        data = fh.read()
    for name in sorted(set(_MODULE_IMPORT.findall(data))):
        with open(os.path.join(HERE, "modules", name.decode("ascii") + ".saw"), "rb") as fh:
            data += b"\0" + name + b"\0" + fh.read()
    return data


def stage0_run(src):
    """Stage 0's recorded run of `src` on this host: (Record, None), or (None,
    why there is none)."""
    name = os.path.splitext(os.path.basename(src))[0]
    return oracle.load_run(STAGE0, name, program_data(src), stage0_command([name]))


def record_stage0(names=None):
    """Stage 0 builds each program that is not due and runs it as `execute`
    runs one, and its record replaces the one in `STAGE0`; over every program,
    a record naming none is removed. This and `bench` are the lane's only
    runs of Stage 0, both through the v0 compiler (`oracle.v0_compiler`)."""
    os.makedirs(OUT, exist_ok=True)
    triple = build.host_triple()
    srcs = [src for src in cases(names) if headers(src)[0] is None]

    def one(src):
        name = os.path.splitext(os.path.basename(src))[0]
        rec = oracle.record_run(src, oracle.record_file(STAGE0, triple, name), rel(src), cwd=OUT,
                                timeout=RUN_TIMEOUT, data=program_data(src))
        return "%s: build %s%s" % (name, rec.build, "" if rec.build != "ok" else ", exit %s" % rec.exit)
    for line in gate_jobs.map_ordered(one, srcs):
        print("run lane stage0 %s %s" % (triple, line))
    if not names:
        for path in oracle.stale_records(os.path.join(STAGE0, triple),
                                         {os.path.splitext(os.path.basename(s))[0] for s in srcs}):
            os.remove(path)
            print("run lane stage0: removed %s" % rel(path))
    return 0


def execute(binary):
    """(exit status, standard output, standard error), the status None on a
    timeout. A panic's message is on standard error, the program's prints on
    standard output."""
    try:
        r = subprocess.run([binary], cwd=OUT, capture_output=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, b"", b""
    return r.returncode, r.stdout, r.stderr


def lines_of(text):
    """`text`'s lines, without the empty one after a final line break."""
    if text == "":
        return []
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


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
    if new_log:
        return ["run %s: sawc2 builds it but prints: %s" % (rel(src), new_log[:300])], "fail"
    old, why = stage0_run(src)
    if old is None:
        return ["run %s: %s" % (rel(src), why)], "fail"
    if old.build != "ok":
        return ["run %s: Stage 0 does not build it: %s" % (rel(src), old.build_error or old.build)], "fail"
    ok_fast, fast, fast_log = build_new(src, "-O2")
    if not ok_fast:
        return ["run %s: sawc2 does not build it at -O2: %s" % (rel(src), fast_log[:300])], "fail"
    code_old = old.exit
    # The record holds the output with this checkout's root removed, so
    # sawc2's is compared the same way.
    out_old = None if old.stdout == "varies" else old.stdout.encode("utf-8", "surrogateescape")
    err_old = None if old.stderr == "varies" else old.stderr.encode("utf-8", "surrogateescape")
    failures = []
    for speed, binary in (("-O0", new), ("-O2", fast)):
        code_new, out_new, err_new = execute(binary)
        out_new = oracle.unrooted(out_new.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
        err_new = oracle.unrooted(err_new.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
        where = "%s %s" % (rel(src), speed)
        if code_new is None or code_old is None:
            failures.append("run %s: a binary timed out" % where)
        elif code_old != "varies" and code_new != code_old:
            failures.append("run %s: exit %d under sawc2, %d under Stage 0" % (where, code_new, code_old))
        if differs is not None and _HAZARD.search(differs):
            failures.extend("%s (%s)" % (f, speed) for f in check_hazard(src, differs, out_new, out_old))
        elif out_old is None:
            failures.append("run %s: Stage 0's output varies between runs, so it is no oracle: state the "
                            "output with `// prints:` lines and cite the hazard on a `// differs:` line" % where)
        elif differs is not None:
            if masked(out_new) != masked(out_old):
                failures.append("run %s: output differs beyond a panic location: %s"
                                % (where, first_difference(out_new, out_old)))
        elif out_new != out_old:
            failures.append("run %s: output differs: %s" % (where, first_difference(out_new, out_old)))
        # Standard error holds a panic's message, compared as the output is:
        # whole, or past each panic location under `// differs:`. An ordering
        # hazard moves only the prints, so it does not exempt this stream.
        if code_new is None:
            continue
        if err_old is None:
            failures.append("run %s: Stage 0's standard error varies between runs, so it is no oracle" % where)
        elif differs is not None:
            if masked(err_new) != masked(err_old):
                failures.append("run %s: standard error differs beyond a panic location: %s"
                                % (where, first_difference(err_new, err_old)))
        elif err_new != err_old:
            failures.append("run %s: standard error differs: %s" % (where, first_difference(err_new, err_old)))
    return failures, "fail" if failures else "pass"


def cases(names=None):
    found = sorted(glob.glob(os.path.join(HERE, "*.saw")))
    if names:
        found = [p for p in found if os.path.splitext(os.path.basename(p))[0] in names]
    return found


def check_pinned_ir(failures, counts, write):
    """hello.saw's `.ll`, as the compiler binary writes it for macOS, against
    hello.ll, and one runtime source's, as `sawc2 runtime` writes it, against
    runtime_dirent.ll. The target is named, so the pins hold on every host.
    Both, and frame_pointers.saw's, define every function keeping a frame
    pointer."""
    hello = check_pinned(failures, counts, write, "hello", os.path.join(HERE, "hello.ll"),
                         ["build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                          rel(os.path.join(HERE, "hello.saw"))])
    dirent = check_pinned(failures, counts, write, "runtime dirent", os.path.join(HERE, "runtime_dirent.ll"),
                          ["runtime", "--target", PINNED_TARGET, "--std-root", "std", "--emit-ll",
                           rel(os.path.join(build.RT_ROOT, "host_macos", "dirent.saw"))])
    r = subprocess.run([build.SAWC2, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        rel(os.path.join(HERE, "frame_pointers.saw"))], cwd=REPO, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run frame pointers: sawc2 wrote no .ll: %s" % r.stdout.strip()[:300])
    for what, text in (("hello", hello), ("runtime dirent", dirent),
                       ("frame pointers", r.stdout if r.returncode == 0 else None)):
        if text is not None:
            failures.extend(define_problems(what, text))
            counts["run .ll files whose defines keep frame pointers"] = (
                counts.get("run .ll files whose defines keep frame pointers", 0) + 1)


# The function attribute every define carries on every target sawc2 knows
# (`Target.frame_pointer` in compiler/target).
FRAME_POINTER = '"frame-pointer"="non-leaf"'
_GROUP = re.compile(r"^attributes #(\d+) = \{(.*)\}$")


def define_problems(what, text):
    """A failure per `define` in `text` whose attributes, after its parameter
    list, carry no `FRAME_POINTER`, itself or through an attribute group."""
    lines = text.split("\n")
    groups = {}
    for line in lines:
        m = _GROUP.match(line)
        if m:
            groups[m.group(1)] = m.group(2)
    problems = []
    defines = 0
    for k, line in enumerate(lines):
        if not line.startswith("define "):
            continue
        defines += 1
        # A quoted symbol may hold `)` and `#`, but the attributes after the
        # parameter list hold neither.
        tail = line[line.rindex(")") + 1:]
        attributes = tail + " " + " ".join(groups.get(n, "") for n in re.findall(r"#(\d+)", tail))
        if FRAME_POINTER not in attributes:
            problems.append("run %s: the define at .ll line %d keeps no frame pointer: %s"
                            % (what, k + 1, line[:200]))
    if defines == 0:
        problems.append("run %s: the .ll defines nothing" % what)
    return problems


def check_pinned(failures, counts, write, what, pinned, args):
    """Compares the `.ll` sawc2 writes for `args` with `pinned`, or rewrites
    `pinned` with it; returns the text, or None when sawc2 wrote none."""
    r = subprocess.run([build.SAWC2] + args, cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run %s: sawc2 wrote no .ll: %s" % (what, r.stdout.strip()[:300]))
        return None
    text = r.stdout
    if write:
        with open(pinned, "w") as fh:
            fh.write(text)
        return text
    if not os.path.exists(pinned):
        failures.append("run %s: no pinned %s" % (what, rel(pinned)))
        return text
    with open(pinned) as fh:
        expected = fh.read()
    if expected != text:
        a = expected.split("\n")
        b = text.split("\n")
        k = next((i for i in range(max(len(a), len(b)))
                  if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), 0)
        failures.append("run %s: the .ll differs from %s at line %d" % (what, rel(pinned), k + 1))
    counts["run pinned .ll files"] = counts.get("run pinned .ll files", 0) + 1
    return text


NOALIAS_SOURCE = os.path.join(HERE, "noalias.saw")
NOALIAS_PINNED = os.path.join(HERE, "noalias.defines")
_NOALIAS_DEFINE = re.compile(r'^define [^@]*@"saw (closure#\d+ of |drop glue )?noalias\.')
# The funnel's cell-carrying test, and the injection that answers it "no
# cell" for every shared reference.
NOALIAS_FUNNEL = "attributes.saw"
NOALIAS_CELL_TEST = "    if mono.dp.bc.mir.tc.is_cell_carrying(info.b) {\n"
NOALIAS_INJECTED = "    if false {\n"
# The parameter only the cell-carrying exemption keeps from `noalias`.
NOALIAS_CELL_ROW = '@"saw noalias.bump(gauge: &noalias.Gauge)"'


def noalias_defines(compiler):
    """noalias.saw's own `define` lines as `compiler` writes them for the
    pinned target: (the lines, or None and why). Naming the target keeps the
    pin one file on every host, and lets the injected copy, which has no
    runtime manifest beside it, emit at all."""
    r = subprocess.run([compiler, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        rel(NOALIAS_SOURCE)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()[:300]
    return [line for line in r.stdout.split("\n") if _NOALIAS_DEFINE.match(line)], ""


def check_noalias(failures, counts, write):
    """noalias.saw's `define` lines against noalias.defines, then the same
    check over a sawc2 whose `noalias` funnel ignores the cell-carrying test,
    which must fail at the cell-carrying shared reference."""
    lines, why = noalias_defines(build.SAWC2)
    if lines is None:
        failures.append("run noalias: sawc2 wrote no .ll: %s" % why)
        return
    text = "\n".join(lines) + "\n"
    if write:
        with open(NOALIAS_PINNED, "w") as fh:
            fh.write(text)
        return
    with open(NOALIAS_PINNED) as fh:
        expected = fh.read()
    if text != expected:
        changed = [line for line in lines if line + "\n" not in expected]
        failures.append("run noalias: the define lines differ from %s: %s"
                        % (rel(NOALIAS_PINNED), (changed or ["a line is missing"])[0][:200]))
        return
    counts["run pinned .ll files"] = counts.get("run pinned .ll files", 0) + 1
    copy = os.path.join(OUT, "noalias-inject")
    shutil.rmtree(copy, ignore_errors=True)
    try:
        llvm = os.path.join(copy, "llvm")
        shutil.copytree(os.path.join(COMPILER, "llvm", "src"), llvm)
        funnel = os.path.join(llvm, NOALIAS_FUNNEL)
        with open(funnel) as fh:
            source = fh.read()
        if source.count(NOALIAS_CELL_TEST) != 1:
            failures.append("run noalias: %s no longer holds the cell-carrying test %r to inject"
                            % (NOALIAS_FUNNEL, NOALIAS_CELL_TEST.strip()))
            return
        with open(funnel, "w") as fh:
            fh.write(source.replace(NOALIAS_CELL_TEST, NOALIAS_INJECTED))
        packages = []
        for name, path in build.STAGE_PACKAGES:
            packages += ["--module-path", "%s=%s" % (name, llvm if name == "sawllvm" else path)]
        injected = os.path.join(copy, "sawc2")
        r = subprocess.run([build.SAWC2, "build", "-O0", "--std-root", "std"] + packages
                           + [rel(build.DRIVER_ENTRY), "-o", injected], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("run noalias: the injected sawc2 does not build: %s"
                            % (r.stdout + r.stderr).strip()[:300])
            return
        lines, why = noalias_defines(injected)
        if lines is None:
            failures.append("run noalias: the injected sawc2 wrote no .ll: %s" % why)
            return
        caught = [line for line in lines if line + "\n" not in expected]
        if not any(NOALIAS_CELL_ROW in line and "noalias %p1" in line for line in caught):
            failures.append("run noalias: a funnel ignoring the cell-carrying test passes %s at %s"
                            % (rel(NOALIAS_PINNED), NOALIAS_CELL_ROW))
        counts["run noalias injections caught"] = counts.get("run noalias injections caught", 0) + 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


def build_runtime(directory, rt_root):
    """`sawc2 runtime` of the sources under `rt_root` into a fresh
    `directory`: (exit status, what it printed)."""
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)
    r = subprocess.run([build.SAWC2, "runtime", "--std-root", "std"] + target_flags()
                       + ["--rt-root", rel(rt_root), "--out", rel(directory)], cwd=REPO, capture_output=True,
                       text=True, timeout=BUILD_TIMEOUT)
    return r.returncode, (r.stdout + r.stderr).strip()


# Each defect a runtime source may carry, and the line `sawc2 runtime` must
# print for it: (source under runtime/, the text replaced, its replacement,
# the line).
RUNTIME_DEFECTS = (
    ("common/sleep.saw", '@export("__saw_rt_sleep_ns")\n', "",
     "sawc2 runtime: no runtime object defines `__saw_rt_sleep_ns`, which runtime/ABI.md lists"),
    ("%s/dirent.saw" % ("host_macos" if build.host_triple().endswith("-apple-darwin") else "host_linux"),
     '@export("__saw_rt_fs_dirent_name")', '@export("__saw_rt_fs_chdir")',
     "sawc2 runtime: `__saw_rt_fs_chdir` is defined by both"),
)


def check_runtime(failures, counts):
    """`sawc2 runtime` writes the same bytes into two directories, and refuses
    a runtime that leaves a seam undefined or defines one twice, naming it and
    printing no manifest."""
    first_dir = os.path.join(OUT, "runtime-a")
    second_dir = os.path.join(OUT, "runtime-b")
    rt = build.RT_ROOT
    code_a, log_a = build_runtime(first_dir, rt)
    code_b, log_b = build_runtime(second_dir, rt)
    if code_a != 0 or code_b != 0:
        failures.append("run runtime: sawc2 runtime fails: %s" % (log_a or log_b)[:300])
        return
    names = sorted(os.listdir(first_dir))
    if names != sorted(os.listdir(second_dir)):
        failures.append("run runtime: two builds write different files")
    for name in names:
        with open(os.path.join(first_dir, name), "rb") as a, open(os.path.join(second_dir, name), "rb") as b:
            if a.read() != b.read():
                failures.append("run runtime: %s differs between two builds" % name)
    counts["run runtime objects"] = sum(1 for n in names if n.endswith(".o"))
    for source, old, new, line in RUNTIME_DEFECTS:
        copy = os.path.join(OUT, "runtime-defect", "rt")
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
        shutil.copytree(rt, copy)
        path = os.path.join(copy, source)
        with open(path) as fh:
            text = fh.read()
        if old not in text:
            failures.append("run runtime: %s no longer holds %r to break" % (source, old))
            continue
        with open(path, "w") as fh:
            fh.write(text.replace(old, new, 1))
        code, log = build_runtime(os.path.join(OUT, "runtime-defect", "out"), copy)
        if code == 0 or line not in log or any(l.startswith("object ") for l in log.split("\n")):
            failures.append("run runtime: a runtime broken in %s is not refused with %r: %s"
                            % (source, line, log[:300]))
        counts["run runtime defects refused"] = counts.get("run runtime defects refused", 0) + 1


def check_foreign_targets(failures, counts):
    """`sawc2 build --target T` links for the host and for every target whose
    runtime manifest `build.py --runtime T` wrote beside sawc2, and every other
    target is refused before anything is written, saying it is not the host
    and has no runtime: a build never falls back to the host's objects."""
    hello = os.path.join(HERE, "hello.saw")
    probe = os.path.join(OUT, "foreign")
    host = build.host_triple()
    configured = [t for t in TARGETS if t == host or os.path.exists(build.runtime_manifest(t))]
    refused = 0
    for triple in TARGETS:
        for written in (probe, probe + ".ll"):
            if os.path.exists(written):
                os.remove(written)
        r = subprocess.run([build.SAWC2, "build", "--std-root", "std", "--target", triple, rel(hello), "-o",
                            probe], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()[:300]
        if triple in configured:
            if r.returncode != 0 or not os.path.exists(probe):
                failures.append("run target %s: configured, but sawc2 does not link for it: %s" % (triple, said))
            continue
        refused += 1
        if (r.returncode == 0 or "is not this host" not in r.stdout or "no runtime for it is configured"
                not in r.stdout or os.path.exists(probe) or os.path.exists(probe + ".ll")):
            failures.append("run target %s: not refused as unconfigured, or a file was written: %s"
                            % (triple, said))
    counts["run foreign targets refused"] = refused
    counts["run targets configured"] = len(configured)


def check_executable_path(failures, counts):
    """`Env.executable_path` names the real file however the program is
    started: `probes/executable_path.saw`, built by sawc2, is run by a bare
    name that a renamed relative symbolic link on `PATH` resolves, from
    another working directory, and must print its binary's real path. The
    expectation is the path itself, so no Stage 0 run is needed."""
    probe = os.path.join(HERE, "probes", "executable_path.saw")
    links = os.path.join(OUT, "probe-links")
    elsewhere = os.path.join(OUT, "probe-elsewhere")
    shutil.rmtree(links, ignore_errors=True)
    os.makedirs(links)
    os.makedirs(elsewhere, exist_ok=True)
    built = []
    new = os.path.join(OUT, "executable_path.new")
    r = subprocess.run([build.SAWC2, "build", "--std-root", "std"] + target_flags() + [rel(probe), "-o", new],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    built.append(("sawc2", r.returncode, new, (r.stdout + r.stderr).strip()))
    for who, code, binary, log in built:
        if code != 0:
            failures.append("run executable path: %s does not build the probe: %s" % (who, log[:300]))
            continue
        name = "renamed-probe-new"
        os.symlink(os.path.relpath(binary, links), os.path.join(links, name))
        env = dict(os.environ, PATH=links + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
        r = subprocess.run([name], cwd=elsewhere, env=env, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT)
        want = os.path.realpath(binary) + "\n"
        if r.returncode != 0 or r.stdout != want:
            failures.append("run executable path: %s's probe, run as `%s` through PATH, prints %r, not %r"
                            % (who, name, r.stdout[:300], want))
        counts["run executable paths resolved"] = counts.get("run executable paths resolved", 0) + 1


# The `if`s after the long accessor's `lend`: past the round count a capped
# dataflow over a join numbered below its arms stops at (SL-610).
LONG_ACCESSOR_IFS = 1100


def long_accessor_source(ifs):
    """An accessor whose local `a` is live across its `lend` and `ifs`
    sequential `if`s after it, and a caller; it prints `42` then `5`."""
    lines = ["// Generated by run_lane.py's check_long_accessor (SL-610).",
             "struct Grid {", "    cell: Int", "}", "", "extension Grid {",
             "    func at(&var self, i: Int) borrows -> &var Int {",
             "        let a = i + 41", "        lend self.cell", "        var t = 0"]
    for k in range(ifs):
        lines += ["        if t > %d {" % k, "            t = 1", "        }"]
    lines += ['        print("{}", a)', "    }", "}", "", "func main() {", "    var g = Grid(cell: 0)",
              "    borrow var c = g.at(1) {", "        c = 5", "    }", '    print("{}", g.cell)', "}"]
    return "\n".join(lines) + "\n"


PROBES = os.path.join(HERE, "probes")
# A probe's header lines, `// NAME: VALUE`, as README.md's "Probes" lists them.
_DIRECTIVE = re.compile(r"^// (probe|about|stage 0|speeds|prints|panics|undefined|ll defines|ll omits): ?(.*)$")
_ISSUE = re.compile(r"\(SL-\d+\)$")
SPEEDS = ("-O0", "-O1", "-O2", "-Os", "-Oz")
# The lines each kind of probe takes, each as (fewest, most), most None for
# any number. A line its kind does not list is refused, so no header states
# what the lane does not check.
_BUILT = {"probe": (1, 1), "about": (1, 1), "stage 0": (1, 1), "speeds": (1, 1),
          "ll defines": (0, None), "ll omits": (0, None)}
PROBE_LINES = {
    "stated": dict(_BUILT, prints=(1, None)),
    "panics": dict(_BUILT, prints=(0, None), panics=(1, 1)),
    "link-fails": dict(_BUILT, undefined=(1, None)),
    "custom": {"probe": (1, 1), "about": (1, 1)},
    "module": {"probe": (1, 1), "about": (1, 1)},
}
# The count each kind adds to for a probe that holds.
PROBE_COUNTS = {
    "stated": "run programs stating their output",
    "panics": "run programs stating their panic",
    "link-fails": "run programs failing to link as stated",
    "module": "run probe modules imported",
}
LL_COUNT = "run programs stating their .ll"


def probe_header(path):
    """A probe's header lines, {name: [value, ...]} in file order."""
    found = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.startswith("//"):
                break
            m = _DIRECTIVE.match(line)
            if m:
                found.setdefault(m.group(1), []).append(m.group(2))
    return found


def probe_problems(src, header):
    """Why `header` is no well-formed probe header; empty when it is one."""
    where = "run %s" % rel(src)
    kind = header.get("probe", [None])[0]
    if len(header.get("probe", [])) != 1 or kind not in PROBE_LINES:
        return ["%s: a probe states one `// probe: KIND` line, KIND one of %s"
                % (where, ", ".join(PROBE_LINES))]
    allowed = PROBE_LINES[kind]
    problems = ["%s: a %s probe takes no `// %s:` line" % (where, kind, name)
                for name in header if name not in allowed]
    for name, (fewest, most) in allowed.items():
        n = len(header.get(name, []))
        if n < fewest or (most is not None and n > most):
            problems.append("%s: a %s probe states %s `// %s:` line%s, not %d"
                            % (where, kind, "one" if most == 1 else "at least %d" % fewest, name,
                               "" if most == 1 else "s", n))
    about = header.get("about", [])
    if len(about) == 1 and not _ISSUE.search(about[0]):
        problems.append("%s: its `// about:` line ends with its issue, `(SL-N)`" % where)
    if "speeds" in header:
        speeds = header["speeds"][0].split()
        if not speeds or len(set(speeds)) != len(speeds) or any(s not in SPEEDS for s in speeds):
            problems.append("%s: `// speeds:` lists distinct levels of %s" % (where, " ".join(SPEEDS)))
    return problems


def ll_problems(where, ll, header):
    """Failures of the `.ll` at `ll` against the probe's `// ll defines:` and
    `// ll omits:` lines: each symbol defined, and each named nowhere."""
    defined = header.get("ll defines", [])
    omitted = header.get("ll omits", [])
    if not defined and not omitted:
        return []
    try:
        with open(ll) as fh:
            text = fh.read()
    except OSError as e:
        return ["%s: no `.ll` beside the binary: %s" % (where, e)]
    defines = [line for line in text.split("\n") if line.startswith("define ")]
    problems = ["%s: the `.ll` defines no `%s`" % (where, symbol) for symbol in defined
                if not any(spelled in line for line in defines
                           for spelled in ("@%s(" % symbol, '@"%s"(' % symbol))]
    problems += ["%s: the `.ll` names `%s`" % (where, symbol) for symbol in omitted if symbol in text]
    return problems


_DUMP_HEADER = re.compile(r"saw tasks: \d+ live \(as-of panic, unsynchronized\)$")
_DUMP_TASK = re.compile(r"  task group \d+ slot \d+ gen \d+ [a-z-]+$")
_DUMP_FRAME = re.compile(r"    at (\S+ in .+|<unknown frame>)$")


def panic_dump_ok(lines):
    """Whether `lines`, what a panic wrote after its own line, are nothing or
    the panic path's task dump: its header, then a line per task, each
    followed by its frame lines (SL-577)."""
    if not lines:
        return True
    if not _DUMP_HEADER.match(lines[0]):
        return False
    tasks = 0
    for k, line in enumerate(lines[1:]):
        if _DUMP_TASK.match(line):
            tasks += 1
        elif not (_DUMP_FRAME.match(line) and k > 0):
            return False
    return tasks > 0


def held_probe(src, header):
    """(failures, counts) for a probe of a kind its header states, built by
    sawc2 alone at each of its speeds. Each build is held whole, since a read
    of an uninitialised local can pass at one level and not another."""
    kind = header["probe"][0]
    name = os.path.splitext(os.path.basename(src))[0]
    failures = []
    ll_failures = []
    for speed in header["speeds"][0].split():
        where = "run %s %s" % (rel(src), speed)
        # build_new's naming; a refused build writes no `.ll`, so a stale one
        # must not stand in for it.
        ll = os.path.join(OUT, name + (".new" if speed == "-O0" else ".new" + speed[1:]) + ".ll")
        if os.path.exists(ll):
            os.remove(ll)
        ok, binary, log = build_new(src, speed)
        if kind == "link-fails":
            symbols = header["undefined"]
            if ok or first_error(log) is not None or "ndefined" not in log or any(s not in log for s in symbols):
                failures.append("%s: sawc2 %s, not a link failure naming %s undefined: %s"
                                % (where, "links it" if ok else "fails otherwise",
                                   ", ".join("`%s`" % s for s in symbols), log[:300]))
        elif not ok or log:
            failures.append("%s: sawc2 %s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                                  log[:300]))
            continue
        elif kind == "stated":
            want = "".join(line + "\n" for line in header["prints"]).encode()
            code, out, _ = execute(binary)
            if code != 0 or out != want:
                failures.append("%s: exit %s, prints %r, not %r" % (where, code, out[:300], want))
        else:
            want = header.get("prints", [])
            panic = header["panics"][0]
            code, out, err = execute(binary)
            printed = lines_of(masked(out))
            said = lines_of(masked(err))
            if code != -signal.SIGABRT or printed != want or not said or not panic_dump_ok(said[1:]) \
                    or not said[0].startswith("panic at ?: ") or panic not in said[0]:
                failures.append("%s: exit %s, prints %r and %r on standard error, not %r then a panic holding %r "
                                "on standard error" % (where, code, out[:300], err[:300], want, panic))
        ll_failures += ll_problems(where, ll, header)
    counts = {}
    if not failures:
        counts[PROBE_COUNTS[kind]] = 1
    if not ll_failures and (header.get("ll defines") or header.get("ll omits")):
        counts[LL_COUNT] = 1
    return failures + ll_failures, counts


def check_probe(src):
    """(failures, counts) for one probe whose kind is not `custom`."""
    header = probe_header(src)
    problems = probe_problems(src, header)
    if problems:
        return problems, {}
    if header["probe"][0] == "module":
        problems = module_problems(src)
        return problems, {} if problems else {PROBE_COUNTS["module"]: 1}
    return held_probe(src, header)


def module_problems(src):
    """A module probe is never built alone, so some other probe must import
    it, or nothing would build it at all."""
    name = os.path.splitext(os.path.basename(src))[0]
    imported = re.compile(r"^import %s\b" % re.escape(name), re.M)
    for other in probes():
        if other != src:
            with open(other) as fh:
                if imported.search(fh.read()):
                    return []
    return ["run %s: a module probe no other probe imports" % rel(src)]


def check_long_accessor(failures, counts):
    """An accessor's state record holds every local live across its `lend`
    however long the body after it is: the generated accessor, held as a
    stated probe, prints `42` then `5`."""
    src = os.path.join(OUT, "long_accessor.saw")
    with open(src, "w") as fh:
        fh.write(long_accessor_source(LONG_ACCESSOR_IFS))
    header = {"probe": ["stated"], "speeds": ["-O0 -O2"], "prints": ["42", "5"]}
    found, added = held_probe(src, header)
    failures.extend(found)
    for key, n in added.items():
        counts[key] = counts.get(key, 0) + n


# A line of `print_lines_stay_whole.saw` or `print_beside_a_panic.saw`: the
# thread's number, the line's, then 5000 bytes of `x`.
_WHOLE_LINE = re.compile(rb"^([12]) (\d+) x{5000}$")
# How often the stress probe runs at each level (SL-765's acceptance item).
PRINT_STRESS_RUNS = 50
PRINT_STRESS_LINES = 1000
PRINT_STRESS_SPEEDS = ("-O0", "-O2")


def check_print_lines(failures, counts):
    """Two threads' `print` lines are never split by each other: each run of
    `probes/print_lines_stay_whole.saw` writes, through a pipe, 1000 lines per
    thread longer than a pipe's atomic write, and each must come back whole,
    each thread's in its order. Interleaving is the operating system's, so no
    header line can state the output."""
    probe = os.path.join(PROBES, "print_lines_stay_whole.saw")
    for speed in PRINT_STRESS_SPEEDS:
        where = "run %s %s" % (rel(probe), speed)
        ok, binary, log = build_new(probe, speed)
        if not ok or log:
            failures.append("%s: sawc2 %s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                                  log[:300]))
            continue
        for k in range(PRINT_STRESS_RUNS):
            code, out, err = execute(binary)
            problem = None
            next_line = {b"1": 0, b"2": 0}
            for line in lines_of(out.decode("latin-1")):
                m = _WHOLE_LINE.match(line.encode("latin-1"))
                if m is None:
                    problem = "a split line %r" % line[:80]
                    break
                if int(m.group(2)) != next_line[m.group(1)]:
                    problem = "thread %s's line %s out of order" % (m.group(1).decode(), m.group(2).decode())
                    break
                next_line[m.group(1)] += 1
            if problem is None and (code != 0 or err or next_line != {b"1": PRINT_STRESS_LINES,
                                                                       b"2": PRINT_STRESS_LINES}):
                problem = "exit %s, %r on standard error, lines per thread %r" % (code, err[:200], next_line)
            if problem:
                failures.append("%s: run %d of %d: %s" % (where, k + 1, PRINT_STRESS_RUNS, problem))
                break
            counts["run print stress runs whole"] = counts.get("run print stress runs whole", 0) + 1


def check_print_beside_a_panic(failures, counts):
    """A thread printing in a loop never holds back another thread's panic:
    `probes/print_beside_a_panic.saw` ends by SIGABRT with its panic, first
    with both streams merged into a pipe the lane drains, where every printed
    line is whole and the panic arrives between lines, then with standard
    output a pipe nobody reads, where the printer blocks holding the output
    lock and the sink's bounded wait lets the panic out. The printer's line
    count is the scheduler's, so no header line can state the output."""
    probe = os.path.join(PROBES, "print_beside_a_panic.saw")
    panic = b"main gave up"
    for speed in ("-O0", "-O2"):
        where = "run %s %s" % (rel(probe), speed)
        ok, binary, log = build_new(probe, speed)
        if not ok or log:
            failures.append("%s: sawc2 %s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                                  log[:300]))
            continue
        try:
            r = subprocess.run([binary], cwd=OUT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            failures.append("%s: merged and drained, it did not end in %ds" % (where, RUN_TIMEOUT))
            continue
        lines = r.stdout.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        said = [line for line in lines if line.startswith(b"panic at ")]
        split = [line[:80] for line in lines if not line.startswith(b"panic at ") and not _WHOLE_LINE.match(line)]
        if r.returncode != -signal.SIGABRT or len(said) != 1 or panic not in said[0] or split:
            failures.append("%s: merged and drained, exit %s, panic lines %r, split lines %r"
                            % (where, r.returncode, said[:2], split[:2]))
            continue
        read_end, write_end = os.pipe()
        try:
            stalled = subprocess.Popen([binary], cwd=OUT, stdout=write_end, stderr=subprocess.PIPE)
            os.close(write_end)
            try:
                err = stalled.communicate(timeout=RUN_TIMEOUT)[1]
            except subprocess.TimeoutExpired:
                stalled.kill()
                stalled.communicate()
                failures.append("%s: with standard output stalled, it did not end in %ds" % (where, RUN_TIMEOUT))
                continue
        finally:
            os.close(read_end)
        if stalled.returncode != -signal.SIGABRT or panic not in err:
            failures.append("%s: with standard output stalled, exit %s, %r on standard error"
                            % (where, stalled.returncode, err[:300]))
            continue
        counts["run panics beside a printer"] = counts.get("run panics beside a printer", 0) + 1


# The custom probes, each checked by its own function. `executable_path.saw`
# is run through a renamed link on `PATH` from another directory, and what it
# must print is its binary's real path, which no header line can state. The
# two `print` probes' output is interleaved by the operating system.
CUSTOM_PROBES = {
    "executable_path.saw": check_executable_path,
    "print_lines_stay_whole.saw": check_print_lines,
    "print_beside_a_panic.saw": check_print_beside_a_panic,
}


def probes(names=None):
    found = sorted(glob.glob(os.path.join(PROBES, "*.saw")))
    if names:
        found = [p for p in found if os.path.splitext(os.path.basename(p))[0] in names]
    return found


def check_probes(failures, counts, names=None):
    """Every probe of `probes/`, found by the listing and held as its header
    states. A custom probe must have its check in `CUSTOM_PROBES`, and over
    the whole listing every entry there must be a custom probe."""
    srcs = probes(names)
    custom = [src for src in srcs if probe_header(src).get("probe") == ["custom"]]
    if not names:
        for base in CUSTOM_PROBES:
            if os.path.join(PROBES, base) not in custom:
                failures.append("run %s: `CUSTOM_PROBES` names it, but no such `// probe: custom` probe exists"
                                % rel(os.path.join(PROBES, base)))
    for found, added in gate_jobs.map_ordered(check_probe, [src for src in srcs if src not in custom]):
        failures.extend(found)
        for key, n in added.items():
            counts[key] = counts.get(key, 0) + n
    for src in custom:
        problems = probe_problems(src, probe_header(src))
        base = os.path.basename(src)
        if base not in CUSTOM_PROBES:
            problems.append("run %s: a custom probe whose check `CUSTOM_PROBES` does not name" % rel(src))
        if problems:
            failures.extend(problems)
            continue
        CUSTOM_PROBES[base](failures, counts)


def run(names=None, write=False):
    os.makedirs(OUT, exist_ok=True)
    failures = []
    counts = {}
    srcs = cases(names)
    results = gate_jobs.map_ordered(check_case, srcs)
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
        programs = {os.path.splitext(os.path.basename(s))[0] for s in srcs}
        for path in oracle.stale_records(STAGE0, programs):
            failures.append("run %s: a Stage 0 record of no program here; `%s` removes it"
                            % (rel(path), stage0_command()))
        for rule in ll_rules():
            if rule not in covered:
                failures.append("run rule %s: no due program is refused by it" % rule)
        check_pinned_ir(failures, counts, write)
        check_noalias(failures, counts, write)
        check_foreign_targets(failures, counts)
        check_runtime(failures, counts)
        check_long_accessor(failures, counts)
    check_probes(failures, counts, names)
    return failures, counts, dues


def best_time(binary, reps=BENCH_REPS):
    """The best wall time of `reps` runs after one warm-up, and the output."""
    execute(binary)
    best = None
    out = b""
    for _ in range(reps):
        start = time.perf_counter()
        _, out, _ = execute(binary)
        took = time.perf_counter() - start
        best = took if best is None or took < best else best
    return best, out


def bench():
    """The timing report: each kernel of `bench/` built by sawc2 at -O2 and
    by Stage 0, both run, their best times printed beside the ratio. Only a
    build that fails, or two outputs that differ, fails the report; a time
    never does, since it is only as good as the machine is quiet. A time is
    no record, so Stage 0 is run here, through the v0 compiler."""
    os.makedirs(OUT, exist_ok=True)
    failures = []
    print("%-12s %10s %10s %7s" % ("kernel", "Stage 0", "sawc2 -O2", "ratio"))
    for src in sorted(glob.glob(os.path.join(HERE, "bench", "*.saw"))):
        name = os.path.splitext(os.path.basename(src))[0]
        ok_new, new, new_log = build_new(src, "-O2")
        old = os.path.join(OUT, name + ".old")
        code, old_log = oracle.stage0(src, old, [], timeout=BUILD_TIMEOUT)
        ok_old = code == 0
        if not ok_new or not ok_old:
            failures.append("bench %s: %s does not build it: %s"
                            % (name, "sawc2" if not ok_new else "Stage 0", (new_log if not ok_new else old_log)[:300]))
            continue
        t_old, out_old = best_time(old)
        t_new, out_new = best_time(new)
        if out_new != out_old:
            failures.append("bench %s: output differs: %s" % (name, first_difference(out_new, out_old)))
        print("%-12s %9.4fs %9.4fs %6.2fx" % (name, t_old, t_new, t_new / t_old))
    for failure in failures:
        print(failure)
    return 1 if failures else 0


def main():
    args = sys.argv[1:]
    if "--target" in args:
        at = args.index("--target")
        if at + 1 >= len(args) or args[at + 1] not in TARGETS:
            print("run lane: --target is one of %s" % ", ".join(TARGETS))
            return 2
        set_target(args[at + 1])
        del args[at:at + 2]
    if "--bench" in args:
        return bench()
    names = [a for a in args if not a.startswith("-")]
    if "--stage0" in args:
        if TARGET:
            print("run lane: --stage0 records Stage 0's host runs, so it takes no --target")
            return 2
        return record_stage0(names)
    failures, counts, dues = run(names, "--write" in args)
    for failure in failures:
        print(failure)
    for due in dues:
        print("due: %s" % due)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("run lane: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

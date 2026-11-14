#!/usr/bin/env python3
"""The run lane: each program here built by sawc against the new std and
run, and its standard output and exit status compared with Stage 0's recorded
run of it, built against its own std.

    python compiler/tests/run/run_lane.py            # check
    python compiler/tests/run/run_lane.py --write    # rewrite hello.ll, noalias.defines, debug/debug_info.ll
    python compiler/tests/run/run_lane.py NAME...    # just these programs and probes
    python compiler/tests/run/run_lane.py --stage0 [NAME...]   # record Stage 0's runs
    python compiler/tests/run/run_lane.py --bench    # the timing report over bench/
    python compiler/tests/run/run_lane.py --target TRIPLE   # sawc's side cross-built

`compiler/tests/run.py` runs `run()`. Each `NAME.saw` is one case:

- a plain program passes when sawc's binary, built at -O0 and again at -O2,
  prints the same bytes as Stage 0's recorded run on standard output and on
  standard error, where a panic's message goes, and exits with the same
  status (a panic's abort included); the record is `stage0/HOST/NAME.stage0`,
  written by `--stage0` through the v0 compiler, and a program without one,
  or whose bytes changed since it was made, fails until it is rerecorded;
- a program whose first lines are `// due: REASON` and `// refuses: RULE at
  L:C` is one sawc cannot build yet: the lane requires `sawc build` to
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
  sawc must print exactly those lines, and Stage 0 the same lines in some
  other order, since such a hazard moves output and never adds or loses it;
- a build that links prints nothing, at -O0 and at -O2: the runtime it links
  is built at the module's own target, so the linker has nothing to warn
  about, and clang's warning that it ignores invalid debug info fails it;
- `hello.saw`'s `.ll`, as the compiler binary writes it with `-g0`, equals
  `hello.ll` byte for byte, and `runtime/host_macos/dirent.saw`'s, as `sawc
  runtime` writes it, `runtime_dirent.ll`;
- `debug/panic_lines.saw`'s `crash`, with its line tables and the metadata
  they reach renumbered, equals `debug/debug_info.ll`; and each of `debug/`'s
  programs, built at -O0 and -O2 and run, panics at a line every call into
  the failure funnel from that function symbolizes to, inlined or not
  (README.md, "Line tables");
- `noalias.saw`'s own `define` lines, written with `-g0`, equal `noalias.defines`, and a sawc
  built from a copy of the backend whose `noalias` funnel skips its
  cell-carrying test fails that comparison at the cell-carrying `&` parameter;
- every `define` in those two `.ll` files, and in `frame_pointers.saw`'s,
  carries `"frame-pointer"="non-leaf"`, so a function the backend writes
  outside its function attribute funnel is caught;
- `sawc build --target` links for the host and every target whose runtime
  `build.py --runtime` configured, and refuses every other target, linking
  nothing; with `--target TRIPLE` the lane builds sawc's side of every
  program for TRIPLE (its runtime configured first) and holds it to Stage 0's
  host build, so a cross-built binary meets the host's expectations;
- `sawc runtime` writes the same bytes into two directories, and refuses a
  copy of the runtime that leaves a seam undefined or defines one twice;
- each `riscv32/` probe's `.ll` for riscv32 and for xtensa holds an `i64`
  only where the value is 64 bits, and compiles to an object referencing the
  routines its width and atomics allow (`word32_ir.py`);
- std.numeric's Float methods are their LLVM intrinsic exactly where the
  target funnel's matrix says, and no target's object for them calls a C
  math library function at -O0 or -O2 (`float_lowering.py`);
- a freestanding object defines std's builtin routines weakly, a program's
  own export of one's name replaces std's, and no builtin routine reaches a
  call of itself at any level on each of the three bare-metal targets
  (`builtin_lowering.py`);
- each `probes/NAME.saw` states in its leading comment lines how it is held
  (README.md, "Probes"): `// probe: stated` is built by sawc alone at its
  `// speeds:` with nothing printed and prints exactly its `// prints:` lines,
  then exits with its `// exits:` status, 0 when it states none, with exactly
  its `// stderr:` lines on standard error when it states any,
  `// probe: panics` prints them and then panics with its `// panics:` text,
  `// probe: link-fails` fails to link with each `// undefined:` symbol
  undefined, `// ll defines:` and `// ll omits:` hold each build's `.ll`, a
  `// c helper: NAME.c` line links that C file of `probes/` into each build
  (and a `.c` file there no probe names fails the lane), and
  a stated probe's `// leaks: none` runs each build under `leaks --atExit`
  on macOS, which must report no leak;
  a `// probe: custom` one is checked by its function in `CUSTOM_PROBES`, a
  `// probe: module` one is imported by another probe and never built alone,
  and a probe stating no kind, or a kind's lines wrongly, fails the lane;
- `probes/executable_path.saw`, the custom probe, built by sawc and run
  through a renamed symbolic link on `PATH` from another directory, prints its
  binary's real path;
- with no `--std-root`, `sawc build` and `sawc runtime`, run from another
  directory, compile against the new std of the tree sawc was built in; a
  copy of sawc in a tree with no `std/`, and an explicit root holding no
  std, each refuse with exit status 2, naming the path;
- a generated accessor with a local live across its `lend` and 1100 `if`s
  after it, which Stage 0 cannot parse, is held as a stated probe to the `42`
  and `5` it prints;
- a generated `match` of 6,400 integer literal arms is held as a stated probe
  to the arm each of eight values takes and a sum weighing every value by its
  arm;
- each placed function or static of `section_function.saw`, `section_static.saw`
  and their `_unreached` twins is defined in the -O2 binary, whole-module and
  split (`check_placed_symbols`);
- no record in `stage0/` names a program that is gone.

`--stage0` records Stage 0's runs of every program not due, or of the NAMEs,
for this host; `--bench` times each kernel of `bench/` under sawc at -O2 and
under Stage 0 and prints the report, which gates nothing. Those two run the v0
compiler (`oracle.v0_compiler`); the check never does, and the runner never
runs either.

Stage 0's recorded run is the oracle; a difference is a sawc bug until shown
otherwise (SL:architecture §5).
"""
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
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

sys.path.insert(0, HERE)
import builtin_lowering  # noqa: E402
import float_lowering  # noqa: E402
import word32_ir  # noqa: E402

OUT = os.path.join(REPO, ".build", "run-lane")
# The object cache of one run of the lane (`run`).
OBJECT_CACHE = os.path.join(OUT, "object-cache-run")
# Stage 0's recorded runs, one directory per host triple (README.md, "The
# oracle").
STAGE0 = os.path.join(HERE, "stage0")
# The target sawc builds the programs for, None for the host. The oracle is
# Stage 0's run on the host either way: the expected output is the same on
# every target, which is the claim a cross-built program is held to.
TARGET = None


def target_flags():
    return ["--target", TARGET] if TARGET else []


def set_target(triple):
    """Build sawc's side for `triple` (None for the host), into a directory
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
# The targets compiler/target describes; `sawc build` links for the host's.
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
    its `// prints:` lines are what sawc must print, and Stage 0 must print
    the same lines in another order; `out_old` is None when Stage 0's order
    varied between its recorded runs, which the hazard allows."""
    stated = stated_prints(src)
    if not stated:
        return ["run %s: cites %s but states no `// prints:` lines" % (rel(src), _HAZARD.search(differs).group(0))]
    want = ("\n".join(stated) + "\n").encode("utf-8")
    failures = []
    if out_new != want:
        failures.append("run %s: sawc does not print the stated lines: %s"
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


def build_new(src, speed="-O0", helper=None):
    """sawc's build of `src` at `speed`: whether it linked, the binary, and
    what it printed. The runtime it links is built at the module's own target,
    so a build that links prints nothing. A probe's C helper, the path
    `helper`, is linked in beside it (`build_with_helper`)."""
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(OUT, name + (".new" if speed == "-O0" else ".new" + speed[1:]))
    if helper is not None:
        return build_with_helper(src, speed, helper, out)
    r = subprocess.run([build.SAWC, "build", speed, "--std-root", "std"] + target_flags() + [rel(src), "-o", out],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return r.returncode == 0, out, (r.stdout + r.stderr).strip()


def build_with_helper(src, speed, helper, out):
    """sawc's build of `src` at `speed` with the C file `helper` linked in,
    as `build_new` returns it. sawc writes the `.ll` (`--emit-ll`) into
    `OUT.ll`, where `sawc build` would. The clang the target's runtime
    manifest records (`choose_clang`'s choice) compiles the helper at -O2, so
    it reads the C convention as strictly as optimized C does, and links the
    two with the manifest's runtime objects and the libraries `sawc build`
    links (`build.link_module`'s line, at `speed`)."""
    triple = TARGET or build.host_triple()
    r = subprocess.run([build.SAWC, "build", speed, "--std-root", "std"] + target_flags()
                       + ["--emit-ll", rel(src)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0 or r.stderr.strip():
        return False, out, (r.stderr or r.stdout).strip()
    with open(out + ".ll", "w") as fh:
        fh.write(r.stdout)
    clang, objects = None, []
    with open(build.runtime_manifest(triple)) as fh:
        for line in fh.read().splitlines():
            if line.startswith("clang "):
                clang = line[len("clang "):]
            elif line.startswith("object "):
                objects.append(line[len("object "):])
    if clang is None:
        return False, out, "%s names no clang" % build.runtime_manifest(triple)
    clang_target = ["-target", build.clang_triple(triple)]
    helper_object = out + ".helper.o"
    c = subprocess.run([clang] + clang_target + ["-O2", "-c", helper, "-o", helper_object],
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if c.returncode != 0 or (c.stdout + c.stderr).strip():
        return False, out, "the C helper %s: %s" % (rel(helper), (c.stdout + c.stderr).strip())
    link = subprocess.run([clang] + clang_target + [speed, "-x", "ir", out + ".ll", "-x", "none"] + objects
                          + [helper_object] + build.link_libraries(triple) + ["-o", out],
                          capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    return link.returncode == 0, out, (link.stdout + link.stderr).strip()


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


def first_difference(a, b, names=("sawc", "Stage 0")):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for k in range(max(len(la), len(lb))):
        x = la[k] if k < len(la) else "<end>"
        y = lb[k] if k < len(lb) else "<end>"
        if x != y:
            return "line %d: %s %r, %s %r" % (k + 1, names[0], x, names[1], y)
    return "no line differs"


def output_difference(printed, expected):
    """Where what a program printed (bytes, or text) departs from what it
    should have, so a message never shows only a cut that may end before the
    difference: the first differing line, then both lengths."""
    if isinstance(printed, str):
        printed = printed.encode("utf-8")
    if isinstance(expected, str):
        expected = expected.encode("utf-8")
    return "%s (%d bytes printed, %d expected)" % (
        first_difference(printed, expected, ("printed", "expected")), len(printed), len(expected))


def check_case(src):
    """(failures, outcome) for one program; outcome is `pass`, `due` or `fail`."""
    due, refuses, differs = headers(src)
    ok_new, new, new_log = build_new(src)
    if due is not None:
        if ok_new:
            return ["run %s: due (%s), but sawc builds it now: remove the due lines" % (rel(src), due)], "fail"
        found = first_error(new_log)
        if refuses is None or found != refuses:
            return ["run %s: due, expected %s first, got %s"
                    % (rel(src), "a `// refuses: RULE at L:C` line" if refuses is None
                       else "%s at %s" % refuses, "nothing" if found is None else "%s at %s" % found)], "fail"
        return [], "due"
    if not ok_new:
        first = next((l for l in new_log.split("\n") if l.startswith(("ERROR", "INVARIANT"))), new_log[:300])
        return ["run %s: sawc does not build it: %s" % (rel(src), first)], "fail"
    if new_log:
        return ["run %s: sawc builds it but prints: %s" % (rel(src), new_log[:300])], "fail"
    old, why = stage0_run(src)
    if old is None:
        return ["run %s: %s" % (rel(src), why)], "fail"
    if old.build != "ok":
        return ["run %s: Stage 0 does not build it: %s" % (rel(src), old.build_error or old.build)], "fail"
    ok_fast, fast, fast_log = build_new(src, "-O2")
    if not ok_fast:
        return ["run %s: sawc does not build it at -O2: %s" % (rel(src), fast_log[:300])], "fail"
    if fast_log:
        return ["run %s: sawc builds it at -O2 but prints: %s" % (rel(src), fast_log[:300])], "fail"
    code_old = old.exit
    # The record holds the output with this checkout's root removed, so
    # sawc's is compared the same way.
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
            failures.append("run %s: exit %d under sawc, %d under Stage 0" % (where, code_new, code_old))
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
    hello.ll, and one runtime source's, as `sawc runtime` writes it, against
    runtime_dirent.ll. The target is named, so the pins hold on every host.
    Both, and frame_pointers.saw's, define every function keeping a frame
    pointer."""
    hello = check_pinned(failures, counts, write, "hello", os.path.join(HERE, "hello.ll"),
                         ["build", "-g0", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                          rel(os.path.join(HERE, "hello.saw"))])
    dirent = check_pinned(failures, counts, write, "runtime dirent", os.path.join(HERE, "runtime_dirent.ll"),
                          ["runtime", "--target", PINNED_TARGET, "--std-root", "std", "--emit-ll",
                           rel(os.path.join(build.RT_ROOT, "host_macos", "dirent.saw"))])
    r = subprocess.run([build.SAWC, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        rel(os.path.join(HERE, "frame_pointers.saw"))], cwd=REPO, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run frame pointers: sawc wrote no .ll: %s" % r.stdout.strip()[:300])
    for what, text in (("hello", hello), ("runtime dirent", dirent),
                       ("frame pointers", r.stdout if r.returncode == 0 else None)):
        if text is not None:
            failures.extend(define_problems(what, text))
            counts["run .ll files whose defines keep frame pointers"] = (
                counts.get("run .ll files whose defines keep frame pointers", 0) + 1)


# The function attribute every define carries on every target sawc knows
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
    """Compares the `.ll` sawc writes for `args` with `pinned`, or rewrites
    `pinned` with it; returns the text, or None when sawc wrote none."""
    r = subprocess.run([build.SAWC] + args, cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run %s: sawc wrote no .ll: %s" % (what, r.stdout.strip()[:300]))
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
    r = subprocess.run([compiler, "build", "-g0", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        rel(NOALIAS_SOURCE)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()[:300]
    return [line for line in r.stdout.split("\n") if _NOALIAS_DEFINE.match(line)], ""


def check_noalias(failures, counts, write):
    """noalias.saw's `define` lines against noalias.defines, then the same
    check over a sawc whose `noalias` funnel ignores the cell-carrying test,
    which must fail at the cell-carrying shared reference."""
    lines, why = noalias_defines(build.SAWC)
    if lines is None:
        failures.append("run noalias: sawc wrote no .ll: %s" % why)
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
        injected = os.path.join(copy, "sawc")
        r = subprocess.run([build.SAWC, "build", "-O0", "-g0", "--std-root", "std"] + packages
                           + [rel(build.DRIVER_ENTRY), "-o", injected], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("run noalias: the injected sawc does not build: %s"
                            % (r.stdout + r.stderr).strip()[:300])
            return
        lines, why = noalias_defines(injected)
        if lines is None:
            failures.append("run noalias: the injected sawc wrote no .ll: %s" % why)
            return
        caught = [line for line in lines if line + "\n" not in expected]
        if not any(NOALIAS_CELL_ROW in line and "noalias %p1" in line for line in caught):
            failures.append("run noalias: a funnel ignoring the cell-carrying test passes %s at %s"
                            % (rel(NOALIAS_PINNED), NOALIAS_CELL_ROW))
        counts["run noalias injections caught"] = counts.get("run noalias injections caught", 0) + 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


DEBUG = os.path.join(HERE, "debug")
DEBUG_PANIC = os.path.join(DEBUG, "panic_lines.saw")
DEBUG_CORO = os.path.join(DEBUG, "coro_lines.saw")
DEBUG_TRY = os.path.join(DEBUG, "try_lines.saw")
DEBUG_PINNED = os.path.join(DEBUG, "debug_info.ll")
# The function whose `!dbg` shape debug_info.ll pins, and the funnel helpers
# whose call sites the symbolization pins look up: the parts helper, and each
# error type's `try!` helper, which calls it.
DEBUG_FUNCTION = '@"saw panic_lines.crash(n: Int)"'
DEBUG_FAIL = "__saw_fail_parts"
DEBUG_TRY_FAIL = "saw try failure "
# The failure funnel's own helpers, written by the compiler with an artificial
# subprogram at line 0: a call from inside one is no source site.
_FUNNEL_HELPER = re.compile(r"^_*(?:saw_fail|" + DEBUG_TRY_FAIL + r")")
_METADATA_NODE = re.compile(r"^!(\d+) = (.*)$")
_METADATA_REFERENCE = re.compile(r"!(\d+)\b")
_PANIC_SITE = re.compile(r"^panic at ([^:\n]+):(\d+): ", re.M)
_DISASSEMBLED_FUNCTION = re.compile(r"^[0-9a-f]+ <(.+)>:$")
_DISASSEMBLED_CALL = re.compile(r"^\s*([0-9a-f]+):\s+(?:bl|call|callq)\s.*<_*(?:" + DEBUG_FAIL + "|"
                                + DEBUG_TRY_FAIL + r"[^>]*)>")
_ATOS_SITE = re.compile(r"\(([^()]+):(\d+)\)$")
_SYMBOLIZER_SITE = re.compile(r"^(.+):(\d+):\d+$")


def dbg_shape(text, symbol):
    """The define of `symbol` in the `.ll` `text`, then every metadata node it
    reaches, each renumbered by first use: the shape of one function's line
    tables, whatever the rest of the module numbers. None when `text` defines
    no `symbol`."""
    lines = text.split("\n")
    start = next((k for k, line in enumerate(lines) if line.startswith("define ") and symbol + "(" in line), None)
    if start is None:
        return None
    end = next(k for k in range(start, len(lines)) if lines[k] == "}")
    body = lines[start:end + 1]
    nodes = {}
    for line in lines:
        m = _METADATA_NODE.match(line)
        if m:
            nodes[int(m.group(1))] = m.group(2)
    order = {}
    pending = []

    def reach(line):
        for m in _METADATA_REFERENCE.finditer(line):
            n = int(m.group(1))
            if n not in order and n in nodes:
                order[n] = len(order)
                pending.append(n)

    for line in body:
        reach(line)
    k = 0
    while k < len(pending):
        reach(nodes[pending[k]])
        k += 1

    def renumbered(line):
        return _METADATA_REFERENCE.sub(lambda m: "!%d" % order.get(int(m.group(1)), int(m.group(1))), line)

    out = [renumbered(line) for line in body] + [""]
    out += ["!%d = %s" % (order[n], renumbered(nodes[n])) for n in pending]
    return "\n".join(out) + "\n"


def check_debug_shape(failures, counts, write):
    """panic_lines.saw's `crash`, as sawc writes it for the pinned target with
    its default line tables, against debug_info.ll (`dbg_shape`)."""
    r = subprocess.run([build.SAWC, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        rel(DEBUG_PANIC)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run line tables: sawc wrote no .ll: %s" % r.stdout.strip()[:300])
        return
    shape = dbg_shape(r.stdout, DEBUG_FUNCTION)
    if shape is None:
        failures.append("run line tables: the .ll defines no %s" % DEBUG_FUNCTION)
        return
    if write:
        with open(DEBUG_PINNED, "w") as fh:
            fh.write(shape)
        return
    if not os.path.exists(DEBUG_PINNED):
        failures.append("run line tables: no pinned %s" % rel(DEBUG_PINNED))
        return
    with open(DEBUG_PINNED) as fh:
        expected = fh.read()
    if shape != expected:
        a = expected.split("\n")
        b = shape.split("\n")
        k = next((i for i in range(max(len(a), len(b)))
                  if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), 0)
        failures.append("run line tables: %s's shape differs from %s at line %d: %s"
                        % (DEBUG_FUNCTION, rel(DEBUG_PINNED), k + 1, (b[k] if k < len(b) else "<end>")[:200]))
    counts["run pinned .ll files"] = counts.get("run pinned .ll files", 0) + 1


def manifest_clang(triple):
    """The clang the runtime manifest of `triple` names, or None."""
    with open(build.runtime_manifest(triple)) as fh:
        for line in fh.read().splitlines():
            if line.startswith("clang "):
                return line[len("clang "):]
    return None


def clang_tool(clang, name):
    """The program `clang` runs for the tool `name` (`-print-prog-name`)."""
    r = subprocess.run([clang, "-print-prog-name=" + name], capture_output=True, text=True)
    return r.stdout.strip() or name


def fail_calls(disassembler, binary):
    """The address of each call into DEBUG_FAIL or a `try!` helper, as
    `disassembler` reads `binary`, outside the funnel's own helpers."""
    r = subprocess.run([disassembler, "--disassemble", "--no-show-raw-insn", binary], capture_output=True,
                       text=True, timeout=BUILD_TIMEOUT)
    calls = []
    current = ""
    for line in r.stdout.splitlines():
        m = _DISASSEMBLED_FUNCTION.match(line)
        if m:
            current = m.group(1)
            continue
        m = _DISASSEMBLED_CALL.match(line)
        if m and not _FUNNEL_HELPER.match(current):
            calls.append(int(m.group(1), 16))
    return calls


def symbolized(triple, clang, binary, address):
    """(function, file base name, line) of the innermost frame the line
    tables give the instruction at `address` in `binary`, an inlined one
    included, or (None, None, what was printed). A call's own address, not
    the return address after it: the failure funnel's helpers never return, so
    the instruction after their call belongs to whatever follows."""
    if "-apple-" in build.clang_triple(triple):
        argv = ["atos", "-i", "-o", binary + ".dSYM", "-arch", triple.split("-")[0], "-l", "0x100000000",
                hex(address)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        first = (r.stdout.strip().split("\n") or [""])[0]
        m = _ATOS_SITE.search(first)
        function = first.split(" (in ")[0]
    else:
        argv = [clang_tool(clang, "llvm-symbolizer"), "--obj=" + binary, hex(address)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        lines = r.stdout.splitlines()
        m = _SYMBOLIZER_SITE.match(lines[1]) if len(lines) > 1 else None
        function = lines[0] if lines else ""
    if m is None:
        return None, None, (r.stdout + r.stderr).strip()[:300]
    return function, os.path.basename(m.group(1)), int(m.group(2))


def check_symbolization(failures, counts):
    """Each line-table program, built by sawc at -O0 and -O2 with its default
    line tables, prints nothing and panics. Then every call into the failure
    funnel whose innermost frame is in the program's file, wherever clang
    inlined it, symbolizes to the panic's own `FILE:LINE` in the function
    that panics, and there is one: through `atos` and the `.dSYM` on Mach-O,
    whose DWARF must verify, and through `llvm-symbolizer` on the executable
    elsewhere. coro_lines.saw's `step` is written as a resume function, whose
    lines are its source function's, and try_lines.saw's `claim` panics
    through its error type's `try!` helper."""
    triple = TARGET or build.host_triple()
    clang = manifest_clang(triple)
    mach_o = "-apple-" in build.clang_triple(triple)
    disassembler = "objdump" if mach_o else clang_tool(clang, "llvm-objdump")
    for src, function in ((DEBUG_PANIC, "panic_lines.crash(n: Int)"), (DEBUG_CORO, "coro_lines.step(n: Int)"),
                          (DEBUG_TRY, "try_lines.claim(n: Int)")):
        name = os.path.splitext(os.path.basename(src))[0]
        for speed in ("-O0", "-O2"):
            where = "run line tables %s %s" % (name, speed)
            binary = os.path.join(OUT, "%s.lines%s" % (name, speed[1:]))
            shutil.rmtree(binary + ".dSYM", ignore_errors=True)
            r = subprocess.run([build.SAWC, "build", speed, "--std-root", "std"] + target_flags()
                               + [rel(src), "-o", binary], cwd=REPO, capture_output=True, text=True,
                               timeout=BUILD_TIMEOUT)
            said = (r.stdout + r.stderr).strip()
            if r.returncode != 0 or said:
                failures.append("%s: sawc build exited %d and printed: %s" % (where, r.returncode, said[:300]))
                continue
            if mach_o:
                if os.path.exists(binary + ".o") or not os.path.isdir(binary + ".dSYM"):
                    failures.append("%s: wants %s.dSYM beside the binary and no object left" % (where, name))
                    continue
                v = subprocess.run(["dwarfdump", "--verify", binary + ".dSYM"], capture_output=True, text=True,
                                   timeout=BUILD_TIMEOUT)
                if v.returncode != 0 or "No errors." not in v.stdout:
                    failures.append("%s: dwarfdump --verify fails: %s" % (where, (v.stdout + v.stderr)[-300:]))
            _, _, err = execute(binary)
            site = _PANIC_SITE.search(err.decode("utf-8", "replace"))
            if site is None:
                failures.append("%s: no panic: %s" % (where, err[:200]))
                continue
            file, line = site.group(1), int(site.group(2))
            found = 0
            for address in fail_calls(disassembler, binary):
                got_function, got_file, got_line = symbolized(triple, clang, binary, address)
                if got_function is None:
                    failures.append("%s: the call at %s does not symbolize: %s" % (where, hex(address), got_line))
                    continue
                if got_file != file:
                    continue
                found += 1
                if got_line != line or function not in got_function:
                    failures.append("%s: the call at %s symbolizes to %s at %s:%d, the panic is in %s at %s:%d"
                                    % (where, hex(address), got_function, got_file, got_line, function, file, line))
            if found == 0:
                failures.append("%s: no call into %s or a `try!` helper symbolizes to %s"
                                % (where, DEBUG_FAIL, file))
            counts["run line-table symbolizations"] = counts.get("run line-table symbolizations", 0) + found


def build_runtime(directory, rt_root):
    """`sawc runtime` of the sources under `rt_root` into a fresh
    `directory`: (exit status, what it printed)."""
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory)
    r = subprocess.run([build.SAWC, "runtime", "--std-root", "std"] + target_flags()
                       + ["--rt-root", rel(rt_root), "--out", rel(directory)], cwd=REPO, capture_output=True,
                       text=True, timeout=BUILD_TIMEOUT)
    return r.returncode, (r.stdout + r.stderr).strip()


# Each defect a runtime source may carry, and the line `sawc runtime` must
# print for it: (source under runtime/, the text replaced, its replacement,
# the line).
RUNTIME_DEFECTS = (
    ("common/sleep.saw", '@export("__saw_rt_sleep_ns")\n', "",
     "sawc runtime: no runtime object defines `__saw_rt_sleep_ns`, which runtime/ABI.md lists"),
    ("%s/dirent.saw" % ("host_macos" if build.host_triple().endswith("-apple-darwin") else "host_linux"),
     '@export("__saw_rt_fs_dirent_name")', '@export("__saw_rt_fs_chdir")',
     "sawc runtime: `__saw_rt_fs_chdir` is defined by both"),
)


def check_runtime(failures, counts):
    """`sawc runtime` writes the same bytes into two directories, and refuses
    a runtime that leaves a seam undefined or defines one twice, naming it and
    printing no manifest."""
    first_dir = os.path.join(OUT, "runtime-a")
    second_dir = os.path.join(OUT, "runtime-b")
    rt = build.RT_ROOT
    code_a, log_a = build_runtime(first_dir, rt)
    code_b, log_b = build_runtime(second_dir, rt)
    if code_a != 0 or code_b != 0:
        failures.append("run runtime: sawc runtime fails: %s" % (log_a or log_b)[:300])
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
    """`sawc build --target T` links for the host and for every target whose
    runtime manifest `build.py --runtime T` wrote beside sawc, and every other
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
        r = subprocess.run([build.SAWC, "build", "--std-root", "std", "--target", triple, rel(hello), "-o",
                            probe], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()[:300]
        if triple in configured:
            if r.returncode != 0 or not os.path.exists(probe):
                failures.append("run target %s: configured, but sawc does not link for it: %s" % (triple, said))
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
    started: `probes/executable_path.saw`, built by sawc, is run by a bare
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
    r = subprocess.run([build.SAWC, "build", "--std-root", "std"] + target_flags() + [rel(probe), "-o", new],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    built.append(("sawc", r.returncode, new, (r.stdout + r.stderr).strip()))
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
            failures.append("run executable path: %s's probe, run as `%s` through PATH, exits %s and prints a "
                            "different output: %s" % (who, name, r.returncode, output_difference(r.stdout, want)))
        counts["run executable paths resolved"] = counts.get("run executable paths resolved", 0) + 1


# A program that builds against the new std alone: Stage 0's frozen `Path`
# has no `canonical`.
DEFAULT_STD_SOURCE = """import std.path.{Path}

func main() {
    match Path(s: ".").canonical() {
        case Ok(_) -> print("the new std"),
        case Err(e) -> print("canonical failed: {e}")
    }
}
"""


def stage_binary():
    """The stage binary itself, never a runner's wrapper around it (the
    fixpoint lane's twin is a script that runs both stages from theirs), for
    a check that copies the compiler somewhere else."""
    return build.STAGE1 if build.selected_stage() == 1 else build.STAGE2


def check_default_std_root(failures, counts):
    """With no `--std-root`, sawc compiles against the `std/` of the tree its
    binary was built in, from any working directory, `sawc runtime`
    included; a copy of the binary in a tree with no `std/` refuses naming the
    path it looked at, and so does an explicit root holding no std, each
    with exit status 2 (SL-818)."""
    work = os.path.join(OUT, "default-std")
    shutil.rmtree(work, ignore_errors=True)
    elsewhere = os.path.join(work, "elsewhere")
    os.makedirs(elsewhere)
    src = os.path.join(work, "main.saw")
    with open(src, "w") as fh:
        fh.write(DEFAULT_STD_SOURCE)
    exe = os.path.join(work, "main")
    r = subprocess.run([build.SAWC, "build"] + target_flags() + [src, "-o", exe], cwd=elsewhere,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run default std: a build from another directory with no --std-root fails: %s"
                        % (r.stdout + r.stderr).strip()[:300])
    else:
        code, out, _ = execute(exe)
        if code != 0 or out != b"the new std\n":
            failures.append("run default std: the program built with no --std-root exits %s: %s"
                            % (code, output_difference(out, b"the new std\n")))
    mem = os.path.join(build.RT_ROOT, "common", "mem.saw")
    r = subprocess.run([build.SAWC, "runtime", "--target", TARGET or build.host_triple(), "--emit-ll", mem],
                       cwd=elsewhere, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run default std: `sawc runtime --emit-ll` from another directory with no --std-root "
                        "fails: %s" % r.stdout.strip()[:300])
    nostd = os.path.join(work, "nostd")
    os.makedirs(os.path.join(nostd, ".build"))
    copy = os.path.join(nostd, ".build", os.path.basename(stage_binary()))
    shutil.copy2(stage_binary(), copy)
    want = "sawc resolve: no std at %s: " % os.path.join(os.path.realpath(nostd), "std")
    r = subprocess.run([copy, "resolve", "--check", src], cwd=elsewhere, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT)
    if r.returncode != 2 or not r.stdout.startswith(want):
        failures.append("run default std: a binary in a tree with no std/ exits %d printing %r, not 2 and %r"
                        % (r.returncode, r.stdout[:300], want))
    want = "sawc typecheck: --std-root %s holds no std: " % elsewhere
    r = subprocess.run([build.SAWC, "typecheck", "--check", "--std-root", elsewhere, src], cwd=elsewhere,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 2 or not r.stdout.startswith(want):
        failures.append("run default std: an explicit root holding no std exits %d printing %r, not 2 and %r"
                        % (r.returncode, r.stdout[:300], want))
    counts["run default std cases"] = 4


def check_default_output(failures, counts):
    """With no `-o`, sawc makes the `.build/` directory it chose and writes
    `.build/NAME` (`.build/NAME.o` for `-c`) there; a `.build` it cannot
    make is refused naming where the default output goes, and a regular file
    of that name fails at the first path under it (SL-1052)."""
    work = os.path.join(OUT, "default-output")
    shutil.rmtree(work, ignore_errors=True)
    fresh = os.path.join(work, "fresh")
    os.makedirs(fresh)
    shutil.copy2(os.path.join(HERE, "hello.saw"), os.path.join(fresh, "hello.saw"))
    r = subprocess.run([build.SAWC, "build"] + target_flags() + ["hello.saw"], cwd=fresh,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    exe = os.path.join(fresh, ".build", "hello")
    if r.returncode != 0 or not os.path.isfile(exe):
        failures.append("run default output: a build with no -o in a directory with no .build/ exits %d, "
                        "leaving %s: %s" % (r.returncode, "its output" if os.path.isfile(exe) else "no .build/hello",
                                            (r.stdout + r.stderr).strip()[:300]))
    else:
        code, out, _ = execute(exe)
        if code != 0 or out != b"hello, world\n":
            failures.append("run default output: .build/hello prints %r, exit %s" % (out[:200], code))
    obj = os.path.join(fresh, ".build", "hello.o")
    shutil.rmtree(os.path.join(fresh, ".build"), ignore_errors=True)
    r = subprocess.run([build.SAWC, "build", "-c"] + target_flags() + ["hello.saw"], cwd=fresh,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0 or not os.path.isfile(obj):
        failures.append("run default output: `-c` with no -o and no .build/ exits %d, leaving no .build/hello.o: %s"
                        % (r.returncode, (r.stdout + r.stderr).strip()[:300]))
    blocked = os.path.join(work, "blocked")
    os.makedirs(blocked)
    shutil.copy2(os.path.join(HERE, "hello.saw"), os.path.join(blocked, "hello.saw"))
    with open(os.path.join(blocked, ".build"), "w") as fh:
        fh.write("a file\n")
    # An existing file reads as an existing directory to the driver (std cannot
    # tell them apart), so the build fails at the first file it writes there.
    r = subprocess.run([build.SAWC, "build"] + target_flags() + ["hello.saw"], cwd=blocked,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 1 or ".build/hello" not in r.stdout + r.stderr or os.path.exists(
            os.path.join(blocked, ".build", "hello")):
        failures.append("run default output: a regular file named .build exits %d printing %r, not 1 naming a "
                        "path under .build" % (r.returncode, (r.stdout + r.stderr)[:300]))
    # A symbolic link to nothing is no directory and cannot be made one, so the
    # refusal names where the default output goes.
    dangling = os.path.join(work, "dangling")
    os.makedirs(dangling)
    shutil.copy2(os.path.join(HERE, "hello.saw"), os.path.join(dangling, "hello.saw"))
    os.symlink("nowhere", os.path.join(dangling, ".build"))
    r = subprocess.run([build.SAWC, "build"] + target_flags() + ["hello.saw"], cwd=dangling,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    want = "sawc build: cannot create .build: "
    if r.returncode != 1 or not r.stdout.startswith(want) or ", where the default output goes" not in r.stdout:
        failures.append("run default output: a .build that cannot be made exits %d printing %r, not 1 and %r..."
                        % (r.returncode, (r.stdout + r.stderr)[:300], want))
    # The directory is made when the build first writes under it, so a refused
    # program leaves none.
    refused = os.path.join(work, "refused")
    os.makedirs(refused)
    with open(os.path.join(refused, "bad.saw"), "w") as fh:
        fh.write('func main() {\n    let n: Int = "text"\n    print("{}", n)\n}\n')
    r = subprocess.run([build.SAWC, "build"] + target_flags() + ["bad.saw"], cwd=refused,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 1 or os.path.lexists(os.path.join(refused, ".build")):
        failures.append("run default output: a program the compiler refuses exits %d and leaves %s: %s"
                        % (r.returncode, ".build" if os.path.lexists(os.path.join(refused, ".build")) else "no .build",
                           (r.stdout + r.stderr).strip()[:300]))
    counts["run default output cases"] = 5


TIME_STAGES_SOURCE = """func main() {
    print("timed")
}
"""
# `sawc build --time-stages`' steps in pipeline order (compiler/lex/src/
# stagetime.saw), the ones every hosted build runs, and the ones only some do.
TIME_STAGES_ORDER = ("resolve", "typecheck", "asserts", "mir", "verify resolve", "verify typecheck", "verify mir",
                     "eval", "verify eval", "borrowck", "verify borrowck", "drops", "verify drops", "mono", "coro",
                     "coro lower", "verify coro", "llvm", "write ll", "clang", "link", "clang link", "dsymutil")
TIME_STAGES_ALWAYS = ("resolve", "typecheck", "asserts", "mir", "eval", "borrowck", "drops", "mono", "coro",
                      "coro lower", "llvm", "write ll")
# The steps only a computed layer runs.
TIME_STAGES_FRONT_STEPS = ("resolve", "typecheck", "asserts", "mir", "eval", "borrowck", "drops")
TIME_STAGES_LINE = re.compile(r"^time: ([a-z ]+) (\d+\.\d) ms$")
# A split build's lines ahead of the pipeline's: the split, then one per
# codegen unit, named by its unit and marked `cached` when its object came
# from the object cache, then the cache's own work when it has one
# (`driver_split_build`).
TIME_STAGES_SPLIT = re.compile(r"^time: split (\d+\.\d) ms$")
TIME_STAGES_UNIT = re.compile(r"^time: clang unit (\S+)( cached)? (\d+\.\d) ms$")
TIME_STAGES_CACHE = re.compile(r"^time: object cache (\d+\.\d) ms$")
# The front cache's lines, ahead of everything: std's cut loaded, or computed
# and then stored (`driver_front_cut`), then each later layer loaded or
# computed, and the copy that hands the computed ones to their store threads
# (`driver_front_chain`). The wait for those threads is reported when the
# command's front end is dropped, after a split build's units.
TIME_STAGES_FRONT = re.compile(r"^time: (front cache load|std front end|front cache store"
                               r"|front layer \S+ (?:loaded|computed)|front layers store) (\d+\.\d) ms$")
TIME_STAGES_JOIN = re.compile(r"^time: front layers join (\d+\.\d) ms$")


def check_time_stages(failures, counts):
    """`--time-stages` prints one `time: STEP MS ms` line per step that ran,
    in pipeline order, then `total`, on standard error after the build; the
    shape is checked and never the values, and the front end's own steps are
    there only when a layer is computed. A split build
    (`--codegen-units=module`) prints its `split` line and a line per
    unit's compile ahead of them. Without the flag the build writes
    nothing to either stream, and the `.ll` is the same bytes either way, so
    recording never changes what is compiled."""
    work = os.path.join(OUT, "time-stages")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    src = os.path.join(work, "main.saw")
    with open(src, "w") as fh:
        fh.write(TIME_STAGES_SOURCE)
    plain = os.path.join(work, "plain")
    timed = os.path.join(work, "timed")
    split = os.path.join(work, "split")
    first = subprocess.run([build.SAWC, "build", "-g0"] + target_flags() + [src, "-o", plain], cwd=work,
                           capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    # The second computes every layer, the third loads them all.
    second = subprocess.run([build.SAWC, "build", "-g0", "--time-stages", "--no-front-cache"] + target_flags()
                            + [src, "-o", timed],
                            cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    third = subprocess.run([build.SAWC, "build", "-g0", "--time-stages", "--codegen-units=module"] + target_flags()
                           + [src, "-o", split], cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if first.returncode != 0 or second.returncode != 0 or third.returncode != 0:
        failures.append("run time stages: the build fails (%d, %d, %d): %s"
                        % (first.returncode, second.returncode, third.returncode,
                           (first.stdout + first.stderr + second.stdout + second.stderr + third.stdout
                            + third.stderr).strip()[:300]))
        return
    if first.stdout + first.stderr != "":
        failures.append("run time stages: a build without the flag prints %r" % (first.stdout + first.stderr)[:300])
    for r in (second, third):
        if r.stdout != "":
            failures.append("run time stages: the flag adds %r to standard output" % r.stdout[:300])
    if time_stage_lines(failures, second.stderr, False) and time_stage_lines(failures, third.stderr, True):
        with open(plain + ".ll", "rb") as a, open(timed + ".ll", "rb") as b, open(split + ".ll", "rb") as c:
            ll = a.read()
            if ll != b.read():
                failures.append("run time stages: --time-stages changes the .ll sawc writes")
            if ll != c.read():
                failures.append("run time stages: --codegen-units=module changes the .ll sawc writes beside the build")
        counts["run time stages checked"] = 1


# A program whose two modules reach across each other the ways a split build
# must keep working (`check_codegen_units`): a static, a method, a generic at
# two types, a closure, a spawned task's frame, and one string literal in
# both.
CODEGEN_UNITS_MAIN = """import helper
import helper.{Tally}

func main() {
    var t = Tally(n: 1)
    t.add(by: helper.LIMIT)
    let pair = helper.twice(t.n)
    let words = helper.twice("unit")
    print("{} {} {} {}", pair.0, pair.1, words.0, words.1)
    print(helper.apply({ x in x * 3 }, 5))
    var group = TaskGroup()
    let h = group.spawn(helper.slow_square(6))
    print(h.join())
    print("unit")
}
"""
CODEGEN_UNITS_HELPER = """import std.task.{yield_now}

public static LIMIT: Int = 7

public struct Tally {
    n: Int
}

extension Tally {
    public func add(&var self, by: Int) {
        self.n = self.n + by
    }
}

public func twice<T: Copy>(x: T) -> (T, T) {
    (x, x)
}

public func apply(f: (Int) -> Int, x: Int) -> Int {
    f(x)
}

public func slow_square(n: Int) -> Int {
    yield_now()
    n * n
}

@export("codegen_units_export")
func exported_answer() -> Int {
    42
}
"""
# The `@export` the helper declares, which a split executable keeps a global
# symbol as a whole-module one does, whatever `--lto` says.
CODEGEN_UNITS_EXPORT = "codegen_units_export"
CODEGEN_UNITS_OUTPUT = b"8 8 unit unit\n15\n36\nunit\n"
# The split builds the pin makes beside the whole-module one: a speed, the
# `--lto` it names (None for the default) and its extra flags.
CODEGEN_UNITS_BUILDS = (("-O0", None, ["-g0"]), ("-O2", "none", ["-g0"]), ("-O2", "thin", ["-g0"]),
                        ("-O2", "full", ["-g0"]), ("-O2", "thin", ["-g"]))


def check_codegen_units(failures, counts):
    """`--codegen-units=module` builds the program it would build whole: one
    module per Saw module, compiled apart and linked at every `--lto`, with
    line tables and without, runs as the whole-module build does, keeps its
    `@export` a global symbol (under LTO on Mach-O, the only one), writes the
    same `.ll` beside it, and leaves no
    unit object behind; `-c` writes
    the one object, which links into the same program; `--emit-ll` ignores
    the flag; and a bad value, or `--lto` on a whole-module build, is a usage
    error."""
    work = os.path.join(OUT, "codegen-units")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    src = os.path.join(work, "main.saw")
    with open(src, "w") as fh:
        fh.write(CODEGEN_UNITS_MAIN)
    with open(os.path.join(work, "helper.saw"), "w") as fh:
        fh.write(CODEGEN_UNITS_HELPER)

    def sawc(args):
        return subprocess.run([build.SAWC, "build"] + target_flags() + args, cwd=work, capture_output=True,
                              text=True, timeout=BUILD_TIMEOUT)

    def ran(binary, where):
        code, out, err = execute(binary)
        if code != 0 or out != CODEGEN_UNITS_OUTPUT:
            failures.append("run codegen units: %s exits %s, not 0: %s"
                            % (where, code, output_difference(out, CODEGEN_UNITS_OUTPUT)))

    def left(binary, where):
        units = binary + ".units"
        stray = sorted(f for f in os.listdir(units) if not f.endswith(".ll")) if os.path.isdir(units) else ["?"]
        if stray:
            failures.append("run codegen units: %s leaves %r beside its units" % (where, stray))

    wholes = {}
    for speed, lines in sorted({(b[0], b[2][0]) for b in CODEGEN_UNITS_BUILDS}):
        whole = os.path.join(work, "whole%s%s" % (speed, lines))
        r = sawc([speed, lines, "--codegen-units=1", "main.saw", "-o", whole])
        if r.returncode != 0:
            failures.append("run codegen units: the whole-module %s %s build fails: %s"
                            % (speed, lines, (r.stdout + r.stderr).strip()[:300]))
            return
        ran(whole, "the whole-module %s %s build" % (speed, lines))
        with open(whole + ".ll", "rb") as fh:
            wholes[(speed, lines)] = fh.read()
    for speed, lto, extra in CODEGEN_UNITS_BUILDS:
        where = "the %s --lto=%s %s split build" % (speed, lto or "(default)", " ".join(extra))
        out = os.path.join(work, "split%s-%s%s" % (speed, lto or "default", extra[0]))
        r = sawc([speed] + extra + ["--codegen-units=module"] + (["--lto=" + lto] if lto else [])
                 + ["main.saw", "-o", out])
        if r.returncode != 0 or (r.stdout + r.stderr).strip():
            failures.append("run codegen units: %s %s: %s" % (where, "fails" if r.returncode else "prints",
                                                              (r.stdout + r.stderr).strip()[:300]))
            continue
        ran(out, where)
        left(out, where)
        symbols = subprocess.run(["nm", "-g", out], capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if not re.search(r"^\S+ T _?%s$" % CODEGEN_UNITS_EXPORT, symbols.stdout, re.M):
            failures.append("run codegen units: %s does not keep `%s` a global symbol"
                            % (where, CODEGEN_UNITS_EXPORT))
        # An LTO link keeps exactly the `@export`s global; on Mach-O, where
        # the export list binds the symbol table, nothing else is defined
        # global, the backtrace table and `main` included.
        defined = sorted(line.split()[-1] for line in symbols.stdout.splitlines() if len(line.split()) == 3)
        if lto in (None, "thin", "full") and speed != "-O0" and (TARGET or build.host_triple()).endswith("-darwin") \
                and defined != ["_" + CODEGEN_UNITS_EXPORT]:
            failures.append("run codegen units: %s keeps %r global, not only `%s`"
                            % (where, defined[:8], CODEGEN_UNITS_EXPORT))
        with open(out + ".ll", "rb") as fh:
            if fh.read() != wholes[(speed, extra[0])]:
                failures.append("run codegen units: %s writes a .ll the whole-module build does not" % where)
        if "-g" in extra and (TARGET or build.host_triple()).endswith("-darwin") and not os.path.isdir(out + ".dSYM"):
            failures.append("run codegen units: %s writes no .dSYM" % where)
    obj = os.path.join(work, "object.o")
    r = sawc(["-O2", "-g0", "-c", "--codegen-units=module", "main.saw", "-o", obj])
    if r.returncode != 0 or not os.path.isfile(obj):
        failures.append("run codegen units: the split -c build fails: %s" % (r.stdout + r.stderr).strip()[:300])
    else:
        left(os.path.join(work, "object.o"), "the split -c build")
        triple = TARGET or build.host_triple()
        clang, objects = None, []
        with open(build.runtime_manifest(triple)) as fh:
            for line in fh.read().splitlines():
                if line.startswith("clang "):
                    clang = line[len("clang "):]
                elif line.startswith("object "):
                    objects.append(line[len("object "):])
        linked = os.path.join(work, "object")
        link = subprocess.run([clang, "-target", build.clang_triple(triple), obj] + objects
                              + build.link_libraries(triple) + ["-o", linked], capture_output=True, text=True,
                              timeout=BUILD_TIMEOUT)
        if link.returncode != 0:
            failures.append("run codegen units: the split -c object does not link: %s"
                            % (link.stdout + link.stderr).strip()[:300])
        else:
            ran(linked, "the split -c object, linked")
    emitted = sawc(["-O2", "--emit-ll", "main.saw"])
    split_emitted = sawc(["-O2", "--codegen-units=module", "--emit-ll", "main.saw"])
    if emitted.returncode != 0 or emitted.stdout != split_emitted.stdout:
        failures.append("run codegen units: --codegen-units=module changes what --emit-ll writes")
    for args, why in ((["--codegen-units=2"], "--codegen-units=2"),
                      (["--codegen-units=1", "--lto=thin"], "--lto=thin on a whole-module build"),
                      (["--codegen-units=module", "--lto=fast"], "--lto=fast")):
        r = sawc(args + ["main.saw", "-o", os.path.join(work, "refused")])
        if r.returncode != 2 or "sawc build:" not in r.stdout:
            failures.append("run codegen units: %s exits %d, not 2 with the usage error: %s"
                            % (why, r.returncode, (r.stdout + r.stderr).strip()[:300]))
    counts["run codegen unit builds checked"] = len(CODEGEN_UNITS_BUILDS) + 1


# The edits `check_unit_stability` makes to CODEGEN_UNITS' program, each
# (file, text replaced, replacement, the edited module's name): a body, a new
# function and a new string literal in the helper, below its suspension point
# so the backtrace table, in the program unit, keeps its lines; a new closure
# signature and a new tuple and array type there, whose glue belongs to no
# module; and a new call from `main` to an instance it already reaches.
UNIT_STABILITY_EDITS = (
    ("helper.saw", "func exported_answer() -> Int {\n    42\n}\n",
     "func exported_answer() -> Int {\n    probe_length(\"unit stability\") * 0 + 42\n}\n\n"
     "func probe_length(text: String) -> Int {\n    text.len()\n}\n", "helper"),
    ("helper.saw", "func exported_answer() -> Int {\n    42\n}\n",
     "func exported_answer() -> Int {\n    let measure: (String) sync -> Int = { s in s.len() }\n"
     "    measure(\"unit\") * 0 + 42\n}\n", "helper"),
    ("helper.saw", "func exported_answer() -> Int {\n    42\n}\n",
     "func exported_answer() -> Int {\n    let pair = (\"unit\", [\"stability\"])\n"
     "    pair.1[0].len() * 0 + 42\n}\n", "helper"),
    ("main.saw", "    print(\"unit\")\n}\n",
     "    print(\"unit\")\n    let again = helper.twice(2)\n    print(\"{}\", again.0 + again.1)\n}\n", "main"),
)


def check_unit_stability(failures, counts):
    """An edit to one module of a split build changes that module's unit
    `.ll` and no other, with line tables and without: each unit's names and
    order are a function of its own module (SL-955). Units are paired and
    classed by tools/unit_stability.py's `compare_units`."""
    import unit_stability
    work = os.path.join(OUT, "unit-stability")
    shutil.rmtree(work, ignore_errors=True)
    sources = {"main.saw": CODEGEN_UNITS_MAIN, "helper.saw": CODEGEN_UNITS_HELPER}

    def units(name, edited, flags):
        root = os.path.join(work, name)
        os.makedirs(root, exist_ok=True)
        for path, text in sources.items():
            with open(os.path.join(root, path), "w") as fh:
                fh.write(edited.get(path, text))
        out = os.path.join(root, "program")
        r = subprocess.run([build.SAWC, "build", "-O0", "--codegen-units=module"] + flags + target_flags()
                           + ["main.saw", "-o", out], cwd=root, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("run unit stability: the %s build fails: %s" % (name, (r.stdout + r.stderr).strip()[:300]))
            return None
        found = {}
        for one in sorted(os.listdir(out + ".units")):
            if one.endswith(".ll"):
                with open(os.path.join(out + ".units", one)) as fh:
                    found[one] = fh.read()
        return found

    checked = 0
    for flags in ([], ["-g0"]):
        base = units("base" + "".join(flags), {}, flags)
        if base is None:
            return
        for n, (path, old, new, module) in enumerate(UNIT_STABILITY_EDITS):
            if sources[path].count(old) != 1:
                failures.append("run unit stability: the edit of %s does not apply once" % path)
                continue
            edited = units("edit%d%s" % (n, "".join(flags)), {path: sources[path].replace(old, new)}, flags)
            if edited is None:
                return
            rows = unit_stability.compare_units(base, edited, module)
            changed = [r for r in rows if r["kind"] != "same"]
            if len(changed) != 1 or not changed[0]["edited"]:
                failures.append("run unit stability: editing %s %s changes %s"
                                % (path, " ".join(flags) or "-g", ", ".join("%s (%s)" % (r["label"], r["kind"])
                                                                            for r in changed) or "no unit"))
            checked += 1
    counts["run unit stability edits checked"] = checked


def check_split_object(failures, counts):
    """A split ELF `-c` object binds every symbol as the whole-module one
    does, the backtrace table, the seams, the export and std's weak routines
    included, and keeps its units' own definitions local (its `main` among
    them), which `llvm-objcopy --localize-hidden` makes so; a record naming
    no llvm-objcopy refuses the split build, naming the tool. The refusal
    runs a copy of sawc beside a copy of the records with the line removed; a
    twin's wrapper has no records of its own beside it, so that part is left
    out under one (`under_twin`)."""
    probe = os.path.join(PROBES, FREESTANDING_PROBE)
    problem = bare_metal_record_problem(rel(probe))
    if problem:
        failures.append(problem)
        return
    work = os.path.join(OUT, "split-object")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    def build_object(sawc, units, out):
        return subprocess.run([sawc, "build", "--freestanding", "-O0", "--codegen-units=" + units, "--std-root", "std",
                               "--target", BARE_METAL_TARGET, rel(probe), "-o", out], cwd=REPO, capture_output=True,
                              text=True, timeout=BUILD_TIMEOUT)

    bound = {}
    for units in ("1", "module"):
        obj = os.path.join(work, "units-%s.o" % units)
        r = build_object(build.SAWC, units, obj)
        if r.returncode != 0:
            failures.append("run split object: the --codegen-units=%s object fails: %s"
                            % (units, (r.stdout + r.stderr).strip()[:300]))
            return
        symbols, why = object_symbols(obj, False)
        if symbols is None:
            failures.append("run split object: nm cannot read %s: %s" % (rel(obj), why))
            return
        bound[units] = {name: kind for name, kind in symbols.items() if not kind.islower()}
        if any(kind.isupper() for name, kind in symbols.items() if "main(" in name):
            failures.append("run split object: the --codegen-units=%s object's `main` is not local" % units)
    if bound["1"] != bound["module"]:
        changed = sorted(n for n in set(bound["1"]) | set(bound["module"]) if bound["1"].get(n) != bound["module"].get(n))
        failures.append("run split object: the split object binds %s otherwise than the whole-module one"
                        % ", ".join(changed[:6]))
    if under_twin():
        left_to_runpy(counts)
        counts["run split objects bound as whole ones"] = 1
        return
    copied = os.path.join(work, "sawc")
    shutil.copy(build.SAWC, copied)
    for path in glob.glob(os.path.join(os.path.dirname(os.path.realpath(build.SAWC)), "sawc-runtime*.txt")):
        with open(path) as fh:
            lines = [line for line in fh.read().splitlines(True) if not line.startswith("objcopy ")]
        with open(os.path.join(work, os.path.basename(path)), "w") as fh:
            fh.write("".join(lines))
    r = build_object(copied, "module", os.path.join(work, "refused.o"))
    if r.returncode == 0 or "llvm-objcopy" not in r.stdout + r.stderr:
        failures.append("run split object: with no llvm-objcopy recorded the split -c build exits %d: %s"
                        % (r.returncode, (r.stdout + r.stderr).strip()[:300]))
    counts["run split objects bound as whole ones"] = 1


def check_link_arguments(failures, counts):
    """In every clang run sawc makes, a `-x none` is followed by an input
    file: clang warns about one that ends the line, and a provider's link has
    no object to follow it. A copy of sawc runs beside a made-up record for a
    Linux target that is not this host's, whose clang is a stub that writes
    each argument list down and creates the `-o` file. The provider's link
    carries no `-x none`; a program's carries it right before the record's
    one object. A twin has no records beside it, so the whole check is left
    out under one (`NOT_UNDER_TWIN`)."""
    work = os.path.join(OUT, "link-arguments")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    triple = "x86_64-unknown-linux-gnu" if build.host_triple() == "aarch64-unknown-linux-gnu" \
        else "aarch64-unknown-linux-gnu"
    log = os.path.join(work, "clang.log")
    stub = os.path.join(work, "clang-stub")
    with open(stub, "w") as fh:
        fh.write('#!/bin/sh\necho "$*" >> "%s"\nwhile [ $# -gt 0 ]; do\n  if [ "$1" = -o ]; then : > "$2"; fi\n'
                 '  shift\ndone\n' % log)
    os.chmod(stub, 0o755)
    copied = os.path.join(work, "sawc")
    shutil.copy(build.SAWC, copied)
    for path in glob.glob(os.path.join(os.path.dirname(os.path.realpath(build.SAWC)), "sawc-runtime*.txt")):
        shutil.copy(path, os.path.join(work, os.path.basename(path)))
    part = os.path.join(work, "runtime-part.o")
    with open(part, "w") as fh:
        fh.write("not read\n")
    record = os.path.join(work, "sawc-runtime-%s.txt" % triple)
    cases = (("provider", ["--runtime", rel(os.path.join(PROBES, "runtime_provider.saw"))], ""),
             ("program", [rel(os.path.join(HERE, "hello.saw"))], "object %s\n" % part))
    for name, args, objects in cases:
        with open(record, "w") as fh:
            fh.write("target %s\nclang %s\n%s" % (triple, stub, objects))
        if os.path.exists(log):
            os.remove(log)
        r = subprocess.run([copied, "build", "--target", triple, "--codegen-units=1", "--std-root", "std"] + args
                           + ["-o", os.path.join(work, name)], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        if r.returncode != 0 or not os.path.exists(log):
            failures.append("run link arguments: the %s build exits %d with %s clang runs: %s"
                            % (name, r.returncode, "some" if os.path.exists(log) else "no",
                               (r.stdout + r.stderr).strip()[:300]))
            continue
        with open(log) as fh:
            runs = [line.split() for line in fh.read().splitlines()]
        for argv in runs:
            for k, arg in enumerate(argv):
                if arg == "-x" and argv[k + 1:k + 2] == ["none"] and (k + 2 >= len(argv) or argv[k + 2].startswith("-")):
                    failures.append("run link arguments: the %s build's clang line has a `-x none` with no input "
                                    "file after it: %s" % (name, " ".join(argv)))
        links = [argv for argv in runs if "-c" not in argv and "-o" in argv]
        has_none = [["-x", "none"] in [argv[k:k + 2] for k in range(len(argv))] for argv in links]
        if len(links) != 1:
            failures.append("run link arguments: the %s build ran clang %d times to link, not once: %s"
                            % (name, len(links), "; ".join(" ".join(a) for a in runs)))
        elif name == "provider" and has_none[0]:
            failures.append("run link arguments: the provider's link has a `-x none`: %s" % " ".join(links[0]))
        elif name == "program":
            argv = links[0]
            if ["-x", "none", part] not in [argv[k:k + 3] for k in range(len(argv))]:
                failures.append("run link arguments: the program's link has no `-x none` right before its object: %s"
                                % " ".join(argv))
    counts["run link argument lists checked"] = len(cases)


# The probes whose `@section` definitions must be defined in the optimized
# binary and sit in the section the probe names, each with the part of their
# symbols' names `nm` shows and how many such symbols there are: a placed
# function or static is kept through the optimizer and the link whether or not
# anything reaches it, whether or not the optimizer inlined or folded its
# readers, and a generic function's instance a call reaches is one.
PLACED_SYMBOL_PROBES = (("section_function_unreached.saw", "placed()", 1), ("section_static_unreached.saw", "TAGGED", 1),
                        ("section_function.saw", "placed()", 1), ("section_static.saw", "TAGGED", 1),
                        ("section_function_suspends.saw", "placed()", 1),
                        ("section_function_suspends_unreached.saw", "placed()", 1),
                        ("section_function_generic.saw", "placed", 2),
                        ("section_function_exported.saw", "exported_placed_function", 1),
                        ("section_static_exported.saw", "exported_placed_static", 1))


def symbol_sections(obj, mach_o):
    """{symbol name: section} of `obj` as `nm` lists them, a Mach-O section as
    `SEGMENT,section`, an ELF one by its name; (None, why) when `nm` cannot
    read it."""
    argv = ["nm", "-m", obj] if mach_o else ["nm", "-f", "sysv", obj]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()[:300]
    found = {}
    for line in r.stdout.splitlines():
        if mach_o:
            m = re.match(r"^[0-9a-fA-F]+ \(([^)]*)\) (?:private )?(?:non-)?external (.+)$", line)
            if m:
                found[m.group(2)] = m.group(1)
        else:
            fields = [f.strip() for f in line.split("|")]
            if len(fields) >= 7:
                found[fields[0]] = fields[6]
    return found, ""


def check_placed_symbols(failures, counts):
    """Each of `PLACED_SYMBOL_PROBES`, built at -O2 whole-module and with
    `--codegen-units=module`, defines each placed function or static in the
    binary, in the section its `@section` names."""
    work = os.path.join(OUT, "placed-symbols")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    mach_o = "-apple-" in build.clang_triple(TARGET or build.host_triple())
    for name, part, count in PLACED_SYMBOL_PROBES:
        with open(os.path.join(PROBES, name)) as fh:
            named = re.search(r'^@section\("([^"]+)"\)', fh.read(), re.M).group(1)
        # A Mach-O table shows a section as its segment and name alone.
        section = ",".join(named.split(",")[:2]) if mach_o else named
        for units in ("1", "module"):
            where = "run %s -O2 --codegen-units=%s" % (name, units)
            out = os.path.join(work, "%s-%s" % (os.path.splitext(name)[0], units))
            r = subprocess.run([build.SAWC, "build"] + target_flags() + ["-O2", "-g0", "--codegen-units=" + units,
                                                                         os.path.join(PROBES, name), "-o", out],
                               cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
            if r.returncode != 0:
                failures.append("%s: the build fails: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
                continue
            sections, why = symbol_sections(out, mach_o)
            if sections is None:
                failures.append("%s: nm cannot read the binary: %s" % (where, why))
                continue
            placed = {symbol: at for symbol, at in sections.items() if part in symbol}
            if len(placed) != count:
                failures.append("%s: the binary defines %d symbols naming `%s`, not %d"
                                % (where, len(placed), part, count))
            for symbol, at in sorted(placed.items()):
                if at != section:
                    failures.append("%s: `%s` is in section `%s`, not `%s`" % (where, symbol, at, section))
            counts["run placed symbols defined in their section at -O2"] = \
                counts.get("run placed symbols defined in their section at -O2", 0) + len(placed)


# An exported function and an exported static, each placed and referenced by
# nothing, beside the entry the link starts from: the vector-table shape.
EXPORTED_PLACED_LINK_SOURCE = """@export("exported_placed_function")
@section(".sawplaced_fn")
func placed_function() -> Int {
    7
}

@export("exported_placed_static")
@section(".sawplaced_static")
static PLACED_STATIC: Int = 7

@export("_start")
func start() {
}
"""
EXPORTED_PLACED_LINK_TARGET = "riscv32-unknown-none-elf"
EXPORTED_PLACED_LINK_SYMBOLS = ("exported_placed_function", "exported_placed_static")


def check_exported_placed_link(failures, counts):
    """An exported, placed function and static survive `ld.lld --gc-sections`
    when nothing references them: a freestanding riscv32 object linked from
    `_start` still defines both. It skips, saying so, when the target has no
    clang record or the clang has no `ld.lld` beside it."""
    where = "run exported placed link"
    skipped = "run exported placed link skipped"
    if not os.path.exists(build.runtime_manifest(EXPORTED_PLACED_LINK_TARGET)):
        counts["%s: no %s record" % (skipped, EXPORTED_PLACED_LINK_TARGET)] = 1
        return
    clang = manifest_clang(EXPORTED_PLACED_LINK_TARGET)
    linker = clang_tool(clang, "ld.lld") if clang else ""
    if not linker or not (os.path.isabs(linker) and os.path.exists(linker)):
        linker = shutil.which("ld.lld") if clang else None
    if not linker:
        counts["%s: no ld.lld beside the recorded clang or on PATH" % skipped] = 1
        return
    work = os.path.join(OUT, "exported-placed-link")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    source = os.path.join(work, "placed.saw")
    with open(source, "w") as fh:
        fh.write(EXPORTED_PLACED_LINK_SOURCE)
    for units in ("1", "module"):
        label = "%s --codegen-units=%s" % (where, units)
        obj = os.path.join(work, "placed-%s.o" % units)
        linked = os.path.join(work, "placed-%s.elf" % units)
        r = subprocess.run([build.SAWC, "build", "--freestanding", "--std-root", "std", "--target",
                            EXPORTED_PLACED_LINK_TARGET, "-O2", "-g0", "--codegen-units=" + units, source, "-o", obj],
                           cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if r.returncode != 0 or not os.path.exists(obj):
            failures.append("%s: the build fails: %s" % (label, (r.stdout + r.stderr).strip()[:300]))
            continue
        # The runtime seam is not linked in: its references stay undefined.
        r = subprocess.run([linker, "--gc-sections", "--unresolved-symbols=ignore-all", "-e", "_start", "-o", linked,
                            obj], capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("%s: ld.lld fails: %s" % (label, (r.stdout + r.stderr).strip()[:300]))
            continue
        r = subprocess.run([word32_ir.nm_tool(clang), linked], capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("%s: nm cannot read the linked file: %s" % (label, (r.stdout + r.stderr).strip()[:300]))
            continue
        defined = {line.split()[-1] for line in r.stdout.splitlines() if line.split()}
        for symbol in EXPORTED_PLACED_LINK_SYMBOLS:
            if symbol not in defined:
                failures.append("%s: the linked file does not define `%s`" % (label, symbol))
            else:
                counts["run exported placed definitions kept by --gc-sections"] = \
                    counts.get("run exported placed definitions kept by --gc-sections", 0) + 1


# The object cache's SHA-256 (compiler/driver/src/sha256.saw), driven through
# its public surface: each printed digest is of the parts of one message, fed
# in order, and SHA256_MESSAGES lists the same messages for hashlib.
SHA256_SOURCE = r"""import sawdriver.sha256.{Sha256}
import std.data.{Data}

func digest(parts: &Vector<String>) unsafe -> String {
    var hash = Sha256()
    var k = 0
    while k < parts.len() {
        hash.update(&parts[k])
        k = k + 1
    }
    hash.finish()
}

func repeated(text: String, times: Int) -> String {
    var out = StringBuilder()
    var k = 0
    while k < times {
        try! out.append(text)
        k = k + 1
    }
    out.build()
}

func main() unsafe {
    var empty: Vector<String> = [""]
    print(digest(&empty))
    var abc: Vector<String> = ["abc"]
    print(digest(&abc))
    var two_blocks: Vector<String> = ["abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"]
    print(digest(&two_blocks))
    var long: Vector<String> = ["abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu"]
    print(digest(&long))
    var million: Vector<String> = [repeated("aaaaaaaaaa", 100_000)]
    print(digest(&million))
    var lengths: Vector<Int> = [55, 56, 63, 64, 65, 119, 120]
    var k = 0
    while k < lengths.len() {
        var one: Vector<String> = [repeated("x", lengths[k])]
        print(digest(&one))
        k = k + 1
    }
    var parts: Vector<String> = [repeated("a", 63), "bb", repeated("c", 130), "", "d"]
    print(digest(&parts))
    var nul: Vector<String> = ["x", "a\0b", repeated("e", 70)]
    print(digest(&nul))
    var mixed = Sha256()
    let text = repeated("m", 70)
    mixed.update(&text)
    let bytes = try! repeated("n", 130).to_data()
    mixed.update(&bytes)
    let nothing = Data()
    mixed.update(&nothing)
    print(mixed.finish())
}
"""
SHA256_MESSAGES = ([b""], [b"abc"], [b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"],
                   [b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopq"
                    b"rsmnopqrstnopqrstu"], [b"a" * 1000000]) + tuple(
    [b"x" * n] for n in (55, 56, 63, 64, 65, 119, 120)) + (
    [b"a" * 63, b"bb", b"c" * 130, b"", b"d"], [b"x", b"a\0b", b"e" * 70], [b"m" * 70, b"n" * 130, b""])
# FIPS 180-4's own answers for its first five messages, which hold hashlib to
# the standard too.
SHA256_FIPS = ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
               "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
               "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1",
               "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")


def check_sha256(failures, counts):
    """The object cache's SHA-256 gives FIPS 180-4's digests, and hashlib's
    for messages fed in parts across block boundaries, at each padding length
    near a block's end, holding a NUL byte, and fed as `Data` beside text."""
    import hashlib
    work = os.path.join(OUT, "sha256")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    src = os.path.join(work, "main.saw")
    with open(src, "w") as fh:
        fh.write(SHA256_SOURCE)
    binary = os.path.join(work, "sha256")
    r = subprocess.run([build.SAWC, "build", "-O1", "-g0"] + target_flags()
                       + ["--module-path", "sawdriver=" + os.path.join(COMPILER, "driver", "src"), src, "-o", binary],
                       cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run sha256: the vector program fails to build: %s" % (r.stdout + r.stderr).strip()[:300])
        return
    code, out, _ = execute(binary)
    got = out.decode("utf-8", "replace").splitlines()
    wanted = [hashlib.sha256(b"".join(parts)).hexdigest() for parts in SHA256_MESSAGES]
    if list(SHA256_FIPS) != wanted[:len(SHA256_FIPS)]:
        failures.append("run sha256: hashlib disagrees with FIPS 180-4's vectors")
    if code != 0 or got != wanted:
        bad = [k for k in range(len(wanted)) if k >= len(got) or got[k] != wanted[k]]
        failures.append("run sha256: exit %s, and the digests of messages %r are not hashlib's" % (code, bad))
    counts["run sha256 vectors checked"] = len(wanted)


# A codegen unit's `--time-stages` line: compiled, or taken from the object
# cache.
OBJECT_CACHE_UNIT = re.compile(r"^time: clang unit (\S+)( cached)? \d+\.\d ms$", re.M)
# The clang a run of the object cache's pin names in place of the
# manifest's: it logs each run, then runs the real one.
OBJECT_CACHE_WRAPPER = """#!/bin/sh
printf '%%s\\n' "$*" >> "%s"
exec "%s" "$@"
"""


def check_object_cache(failures, counts):
    """A split build takes each unit's object from the object cache when the
    cache holds its key and runs no clang for it: the program is the same
    bytes, cold and warm, at -O0 and through ThinLTO's own cache. Each key
    input misses (the speed, the LTO mode, line tables, the unit's text, the
    environment clang reads, another clang); a damaged entry (its header, or
    one byte of its object at the same size) or an unreadable one is
    a warning, a compile and a fresh entry; builds sharing the cache at once
    all succeed while it rotates; a used entry moves to the newest generation
    and an unused one is evicted; and `--no-object-cache`,
    `SAWC_OBJECT_CACHE=off`, whole-module builds and sanitized ones touch no
    cache, while a bad setting is a usage error. Every cache here is a fresh
    directory of the pin's own."""
    work = os.path.join(OUT, "object-cache")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    with open(os.path.join(work, "main.saw"), "w") as fh:
        fh.write(CODEGEN_UNITS_MAIN)
    helper = os.path.join(work, "helper.saw")
    with open(helper, "w") as fh:
        fh.write(CODEGEN_UNITS_HELPER)
    cache = os.path.join(work, "cache")

    def environment(directory, extra=None):
        env = dict(os.environ)
        for name in ("SAWC_OBJECT_CACHE", "SAWC_CACHE_ENTRIES", "CCC_OVERRIDE_OPTIONS", "SAWC_CODEGEN_UNITS",
                     "SAWC_LTO"):
            env.pop(name, None)
        env["SAWC_CACHE_DIR"] = directory
        # The std front cache would make each directory too; it has a pin of
        # its own (`check_front_cache`).
        env["SAWC_FRONT_CACHE"] = "off"
        env.update(extra or {})
        return env

    def sawc(args, out, directory=cache, extra=None, binary=None):
        return subprocess.run([binary or build.SAWC, "build", "--time-stages", "--codegen-units=module"]
                              + target_flags() + args + ["main.saw", "-o", os.path.join(work, out)], cwd=work,
                              capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                              env=environment(directory, extra))

    def units(r, where):
        """{unit: cached?} of a build, or None once its failure is recorded."""
        if r.returncode != 0:
            failures.append("run object cache: %s fails: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
            return None
        if "sawc build: warning" in r.stderr:
            failures.append("run object cache: %s warns: %s" % (where, r.stderr.strip()[:300]))
        found = {m.group(1): bool(m.group(2)) for m in OBJECT_CACHE_UNIT.finditer(r.stderr)}
        if not found:
            failures.append("run object cache: %s reports no unit" % where)
            return None
        return found

    def expect(r, where, cached, out=None):
        """Every unit of the build cached, or none; its program runs."""
        found = units(r, where)
        if found is None:
            return None
        if set(found.values()) != {cached}:
            failures.append("run object cache: %s takes %s from the cache, not %s"
                            % (where, sorted(u for u, c in found.items() if c), "every unit" if cached else "none"))
        if out:
            code, stdout, _ = execute(os.path.join(work, out))
            if code != 0 or stdout != CODEGEN_UNITS_OUTPUT:
                failures.append("run object cache: %s's program exits %s: %s"
                                % (where, code, output_difference(stdout, CODEGEN_UNITS_OUTPUT)))
        return found

    def entries(directory=cache):
        """{generation: sorted entry names} of a cache."""
        objects = os.path.join(directory, "objects")
        if not os.path.isdir(objects):
            return {}
        return {g: sorted(os.listdir(os.path.join(objects, g))) for g in os.listdir(objects)}

    def read(name):
        with open(os.path.join(work, name), "rb") as fh:
            return fh.read()

    checked = 0
    # A hit reuses the object and the program is the same bytes; so it is
    # with line tables, whose debug map names the unit objects.
    def same_bytes(name, where, cold):
        """Whether the program `name` (and its line tables beside it) is the
        bytes `cold` holds, the cold build's; a Mach-O link signs an
        executable under its file name, so both builds write one path."""
        built = read(name)
        dsym = os.path.join(work, name + ".dSYM", "Contents", "Resources", "DWARF", name)
        lines = open(dsym, "rb").read() if os.path.exists(dsym) else b""
        if (built, lines) != cold:
            failures.append("run object cache: %s is not the cold build's bytes" % where)

    def keep(name):
        dsym = os.path.join(work, name + ".dSYM", "Contents", "Resources", "DWARF", name)
        return read(name), (open(dsym, "rb").read() if os.path.exists(dsym) else b"")

    for lines in ("-g0", "-g"):
        out = "program" + lines
        cold = expect(sawc(["-O0", lines], out), "the cold -O0 %s build" % lines, False, out)
        if cold is None:
            return
        kept = keep(out)
        warm = expect(sawc(["-O0", lines], out), "the warm -O0 %s build" % lines, True, out)
        if warm is None:
            return
        # Without line tables the link is not `-reproducible`, and ld64 then
        # stamps each executable with a fresh UUID, cache or no cache.
        if lines == "-g":
            same_bytes(out, "the warm -O0 %s build" % lines, kept)
        if sorted(cold) != sorted(warm):
            failures.append("run object cache: the warm build's units %r are not the cold one's" % sorted(warm))
        checked += 2
    stored = sum(len(names) for names in entries().values())
    if stored != len(cold) * 2:
        failures.append("run object cache: two cold builds of %d units store %d entries" % (len(cold), stored))
    # Each input of the key misses: the speed, the LTO mode, the environment
    # clang reads.
    expect(sawc(["-O1", "-g0"], "speed"), "an -O1 build after -O0's", False, "speed")
    expect(sawc(["-O2", "-g0", "--lto=none"], "lto"), "an -O2 --lto=none build", False, "lto")
    expect(sawc(["-O2", "-g0", "--lto=thin"], "lto"), "an -O2 --lto=thin build after --lto=none's", False, "lto")
    kept = keep("lto")
    expect(sawc(["-O2", "-g0", "--lto=thin"], "lto"), "a warm -O2 --lto=thin build", True, "lto")
    same_bytes("lto", "the warm ThinLTO build, through ThinLTO's cache,", kept)
    if not os.listdir(os.path.join(cache, "thinlto")):
        failures.append("run object cache: a ThinLTO link keeps nothing in %s" % rel(os.path.join(cache, "thinlto")))
    # `#` keeps clang from reporting the edit on standard error.
    expect(sawc(["-O0", "-g0"], "override", extra={"CCC_OVERRIDE_OPTIONS": "# +-O1"}),
           "a build under CCC_OVERRIDE_OPTIONS", False, "override")
    checked += 5
    # An edit to one module misses its unit and only it.
    path, old, new, module = UNIT_STABILITY_EDITS[0]
    with open(helper, "w") as fh:
        fh.write(CODEGEN_UNITS_HELPER.replace(old, new))
    edited = units(sawc(["-O0", "-g0"], "edited"), "the build after an edit to helper")
    with open(helper, "w") as fh:
        fh.write(CODEGEN_UNITS_HELPER)
    if edited is not None and sorted(u for u, c in edited.items() if not c) != [module]:
        failures.append("run object cache: an edit to helper compiles %r, not only `%s`"
                        % (sorted(u for u, c in edited.items() if not c), module))
    checked += 1
    # Another clang misses every unit, and a hit runs no clang at all: a copy
    # of sawc whose records name a clang that logs its runs.
    real_clang = manifest_clang(TARGET or build.host_triple())
    log = os.path.join(work, "clang.log")
    wrapper = os.path.join(work, "clang")
    with open(wrapper, "w") as fh:
        fh.write(OBJECT_CACHE_WRAPPER % (log, real_clang))
    os.chmod(wrapper, 0o755)
    copied = os.path.join(work, "sawc")
    shutil.copy(build.SAWC, copied)
    for record in glob.glob(os.path.join(os.path.dirname(os.path.realpath(build.SAWC)), "sawc-runtime*.txt")):
        with open(record) as fh:
            lines = [("clang %s\n" % wrapper) if line.startswith("clang ") else line
                     for line in fh.read().splitlines(True)]
        with open(os.path.join(work, os.path.basename(record)), "w") as fh:
            fh.write("".join(lines))
    std_root = ["--std-root", os.path.join(REPO, "std")]
    expect(sawc(std_root + ["-O0", "-g0"], "wrapped", binary=copied), "a build through another clang", False,
           "wrapped")
    with open(log, "w"):
        pass
    expect(sawc(std_root + ["-O0", "-g0"], "wrapped-warm", binary=copied), "a warm build through it", True,
           "wrapped-warm")
    with open(log) as fh:
        compiles = [line for line in fh.read().splitlines() if " -x ir " in line and "-###" not in line]
    if compiles:
        failures.append("run object cache: a warm build runs clang on %d unit(s): %s" % (len(compiles), compiles[0][:200]))
    checked += 2
    # A truncated entry, an unreadable one and one whose object has a byte
    # flipped at the same size, in a cache of one build's units: a warning
    # naming each, the three units compiled, and their entries stored again.
    repair = os.path.join(work, "repair")
    expect(sawc(["-O0", "-g0"], "unrepaired", repair), "the build filling a cache", False, "unrepaired")
    names = entries(repair).get("g1", [])
    if len(names) < 3:
        failures.append("run object cache: one build fills its cache's g1 with %r" % names)
        return
    truncated = os.path.join(repair, "objects", "g1", names[0])
    unreadable = os.path.join(repair, "objects", "g1", names[1])
    flipped = os.path.join(repair, "objects", "g1", names[2])
    with open(truncated, "rb") as fh:
        whole = fh.read()
    with open(truncated, "wb") as fh:
        fh.write(whole[:len(whole) // 2])
    os.chmod(unreadable, 0)
    with open(flipped, "rb") as fh:
        whole = bytearray(fh.read())
    body = whole.index(b"\n") + 1
    at = body + (len(whole) - body) // 2
    whole[at] ^= 0xFF
    with open(flipped, "wb") as fh:
        fh.write(bytes(whole))
    r = sawc(["-O0", "-g0"], "repaired", repair)
    if os.path.exists(unreadable):
        os.chmod(unreadable, 0o644)
    warned = r.stderr.splitlines()
    if r.returncode != 0 \
            or not any("is damaged: its first line" in w and names[0][:-2] in w for w in warned) \
            or not any("cannot read the object cache entry" in w and names[1][:-2] in w for w in warned) \
            or not any("is damaged: its object's SHA-256" in w and names[2][:-2] in w for w in warned):
        failures.append("run object cache: a truncated, an unreadable and a flipped entry exit %d warning %r"
                        % (r.returncode, r.stderr.strip()[:600]))
    else:
        code, stdout, _ = execute(os.path.join(work, "repaired"))
        compiled = [u for u, c in ((m.group(1), m.group(2)) for m in OBJECT_CACHE_UNIT.finditer(r.stderr)) if not c]
        if code != 0 or stdout != CODEGEN_UNITS_OUTPUT or len(compiled) != 3:
            failures.append("run object cache: past a truncated, an unreadable and a flipped entry the program exits "
                            "%s: %s, compiling %r" % (code, output_difference(stdout, CODEGEN_UNITS_OUTPUT), compiled))
        expect(sawc(["-O0", "-g0"], "after-repair", repair), "the build after the repair", True, "after-repair")
    checked += 3
    # The switches, and the builds no cache serves.
    for args, extra, why in ((["--no-object-cache"], None, "--no-object-cache"),
                             ([], {"SAWC_OBJECT_CACHE": "off"}, "SAWC_OBJECT_CACHE=off")):
        unused = os.path.join(work, "unused")
        r = sawc(["-O0", "-g0"] + args, "switched", unused, extra)
        found = expect(r, why, False, "switched")
        if found is not None and (os.path.exists(unused) or "object cache" in r.stderr):
            failures.append("run object cache: a build under %s uses a cache" % why)
        checked += 1
    whole = os.path.join(work, "whole-cache")
    r = subprocess.run([build.SAWC, "build", "--codegen-units=1", "-O0", "-g0"] + target_flags()
                       + ["main.saw", "-o", os.path.join(work, "whole")], cwd=work, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, env=environment(whole))
    if r.returncode != 0 or os.path.exists(whole):
        failures.append("run object cache: a whole-module build exits %d and %s a cache"
                        % (r.returncode, "makes" if os.path.exists(whole) else "makes no"))
    sanitized = os.path.join(work, "sanitized-cache")
    r = sawc(["-O0", "-g0", "--sanitize", "address"], "sanitized", sanitized)
    if r.returncode != 0 or os.path.exists(sanitized) or " cached " in r.stderr:
        failures.append("run object cache: a sanitized split build exits %d and %s a cache"
                        % (r.returncode, "uses" if os.path.exists(sanitized) else "uses no"))
    for extra, why in (({"SAWC_OBJECT_CACHE": "maybe"}, "SAWC_OBJECT_CACHE=maybe"),
                       ({"SAWC_CACHE_ENTRIES": "1"}, "SAWC_CACHE_ENTRIES=1")):
        r = sawc(["-O0", "-g0"], "refused", extra=extra)
        if r.returncode != 2 or "sawc build:" not in r.stdout:
            failures.append("run object cache: %s exits %d, not 2 with the usage error: %s"
                            % (why, r.returncode, (r.stdout + r.stderr).strip()[:300]))
    checked += 4
    # Generations: a used entry moves forward, an unused one is evicted.
    small = os.path.join(work, "generations")
    bound = {"SAWC_CACHE_ENTRIES": "4"}
    expect(sawc(["-O0", "-g0"], "gen-a", small, bound), "the first build into a small cache", False, "gen-a")
    after_first = entries(small)
    expect(sawc(["-O0", "-g0"], "gen-b", small, bound), "its rebuild", True, "gen-b")
    after_rebuild = entries(small)
    if sorted(after_first) != ["g1", "g2"] or after_first["g2"] or sorted(after_rebuild) != ["g2", "g3"] \
            or after_rebuild["g2"] != after_first["g1"] or after_rebuild["g3"]:
        failures.append("run object cache: a rebuild does not move its entries forward: %r, then %r"
                        % ({g: len(n) for g, n in after_first.items()}, {g: len(n) for g, n in after_rebuild.items()}))
    expect(sawc(["-O1", "-g0"], "gen-c", small, bound), "an -O1 build into it", False, "gen-c")
    expect(sawc(["-O2", "-g0", "--lto=none"], "gen-d", small, bound), "an -O2 build into it", False, "gen-d")
    expect(sawc(["-O0", "-g0"], "gen-e", small, bound), "the -O0 build after two rotations", False, "gen-e")
    if len(entries(small)) != 2:
        failures.append("run object cache: the small cache holds generations %r, not two" % sorted(entries(small)))
    checked += 5
    # Builds sharing one cache at once, rotating it as they go.
    shared = os.path.join(work, "shared")
    launches = []
    for k, speed in enumerate(("-O0", "-O1", "-O0", "-O1", "-O0", "-O1")):
        out = os.path.join(work, "shared%d" % k)
        launches.append(subprocess.Popen([build.SAWC, "build", "--codegen-units=module", speed, "-g0"] + target_flags()
                                         + ["main.saw", "-o", out], cwd=work, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, env=environment(shared, bound)))
    for k, proc in enumerate(launches):
        try:
            stdout, stderr = proc.communicate(timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            failures.append("run object cache: a concurrent build times out")
            continue
        code, printed, _ = execute(os.path.join(work, "shared%d" % k))
        if proc.returncode != 0 or (stdout + stderr).strip() or code != 0 or printed != CODEGEN_UNITS_OUTPUT:
            failures.append("run object cache: concurrent build %d exits %d (its program %s): %s"
                            % (k, proc.returncode, code, (stdout + stderr).strip()[:300]))
    checked += len(launches)
    counts["run object cache cases checked"] = checked


# A program the std front cache's pins refuse: its refusal record must be the
# same bytes whether std's cut is computed or loaded.
FRONT_CACHE_REFUSED = """func main() {
    let n: Int = "not a number"
    print(n)
}
"""
# A freestanding program's root, for the misses under another profile.
FRONT_CACHE_FREESTANDING = """@export("fs_main")
func fs_main() -> Int {
    7
}
"""


def front_cache_entries(directory, magic):
    """Every front cache entry under `directory` whose body, after the
    entry's own first line, starts with `magic`, by its path from there."""
    found = []
    for path in glob.glob(os.path.join(directory, "front", "g*", "*")):
        with open(path, "rb") as fh:
            fh.readline()
            head = fh.read(len(magic) + 1)
        if head == magic + b" ":
            found.append(os.path.relpath(path, directory))
    return sorted(found)


def front_cache_images(directory):
    """Every std image in the front cache under `directory`."""
    return front_cache_entries(directory, b"sawc-front")


def front_cache_parts(directory):
    """Every layer's part in the front cache under `directory`."""
    return front_cache_entries(directory, b"sawc-front-part")


def front_cache_environment(directory, extra=None):
    """The environment of a build on the std front cache at `directory`, the
    caches' own switches left out unless `extra` sets them."""
    env = dict(os.environ)
    for name in ("SAWC_FRONT_CACHE", "SAWC_OBJECT_CACHE", "SAWC_CACHE_ENTRIES", "SAWC_CODEGEN_UNITS", "SAWC_LTO"):
        env.pop(name, None)
    env["SAWC_CACHE_DIR"] = directory
    env.update(extra or {})
    return env


def check_front_cache(failures, counts):
    """Every front-end command starts from std's cut through drops, which the
    std front cache holds under its key (`driver_front_key`). A warm build
    loads it and computes no std layer: `--time-stages` reports
    `front cache load` and no `std front end`, a cold one both
    `std front end` and `front cache store`, and only a cold build, or a
    cold `--emit-ll`, reports `verify eval`, the evaluator's verifier over
    std that making the cut runs. The `.ll` and a refused
    program's record are the same bytes cold and warm. Each input of the key
    misses: an edited std file, another target, another feature set,
    `--freestanding`, `--runtime`, another binary and another spelling of the
    std root. A damaged, a truncated and a foreign entry each warn, are
    computed and stored again. `--no-front-cache` and `SAWC_FRONT_CACHE=off`
    leave the cache untouched, a bad value is a usage error, and six cold
    builds at once share one store. Every cache is a fresh directory of the
    pin's own."""
    work = os.path.join(OUT, "front-cache")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    for name, text in (("main.saw", TIME_STAGES_SOURCE), ("refused.saw", FRONT_CACHE_REFUSED),
                       ("free.saw", FRONT_CACHE_FREESTANDING)):
        with open(os.path.join(work, name), "w") as fh:
            fh.write(text)
    cache = os.path.join(work, "cache")
    checked = 0

    def sawc(args, directory=cache, extra=None, binary=None):
        return subprocess.run([binary or build.SAWC] + args, cwd=work, capture_output=True, text=True,
                              timeout=BUILD_TIMEOUT, env=front_cache_environment(directory, extra))

    def timed(args, where, want, directory=cache, extra=None, binary=None, refusal=False):
        """A `--time-stages` build of `args` whose cut is `want`, `load` or
        `store`, with no warning; its result, or None once a failure is
        recorded. With `refusal`, a refusal record is as good as a build:
        the cut is made before any program is refused."""
        r = sawc(["build", "--time-stages", "-g0"] + args, directory, extra, binary)
        lines = [line.split(" ")[1:4] for line in r.stderr.splitlines() if line.startswith("time: ")]
        loaded = ["front", "cache", "load"] in lines
        stored = ["front", "cache", "store"] in lines
        computed = ["std", "front", "end"] in lines
        refused = refusal and r.returncode == 1 and r.stdout.startswith("FILE\t")
        if r.returncode != 0 and not refused:
            failures.append("run front cache: %s fails: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
            return None
        if "warning" in r.stderr:
            failures.append("run front cache: %s warns: %s" % (where, r.stderr.strip()[:300]))
        if want == "load" and not (loaded and not stored and not computed):
            failures.append("run front cache: %s computes std's front end instead of loading it: %r"
                            % (where, r.stderr.strip()[:300]))
        if want == "store" and not (stored and computed and not loaded):
            failures.append("run front cache: %s loads std's front end instead of computing and storing it: %r"
                            % (where, r.stderr.strip()[:300]))
        return r

    # Hits, and equality: cold and warm, the program, the `.ll` and a
    # refused program's record.
    cold = timed(["main.saw", "-o", "cold"], "the cold build", "store")
    warm = timed(["main.saw", "-o", "warm"], "the warm build", "load")
    if cold is None or warm is None:
        return
    # Making the cut runs the evaluator's verifier over std, which only a
    # build that computes std's front end reports; a cut read back runs none.
    emitted = sawc(["build", "--time-stages", "--emit-ll", "main.saw"], os.path.join(work, "emit-cold"))
    for r, where, want in ((cold, "the cold build", True), (emitted, "a cold --emit-ll", True),
                           (warm, "the warm build", False)):
        if (re.search(r"^time: verify eval ", r.stderr, re.M) is not None) != want:
            failures.append("run front cache: %s %s `verify eval`: %r"
                            % (where, "reports no" if want else "reports", r.stderr.strip()[:300]))
    checked += 3
    for name in ("cold", "warm"):
        code, stdout, _ = execute(os.path.join(work, name))
        if code != 0 or stdout != b"timed\n":
            failures.append("run front cache: the %s build's program exits %s printing %r" % (name, code, stdout))
    if len(front_cache_images(cache)) != 1:
        failures.append("run front cache: a cold and a warm build store %r, not one image" % front_cache_images(cache))
    lls = [sawc(["build", "--emit-ll", "main.saw"], extra=extra) for extra in ({"SAWC_FRONT_CACHE": "off"}, None)]
    if lls[0].returncode != 0 or lls[0].stdout != lls[1].stdout or lls[1].returncode != 0:
        failures.append("run front cache: the warm --emit-ll is not the uncached one's bytes")
    refused = [sawc(["build", "refused.saw", "-o", "refused"], extra=extra)
               for extra in ({"SAWC_FRONT_CACHE": "off"}, None, None)]
    if refused[0].returncode != 1 or "ERROR\t" not in refused[0].stdout \
            or any((r.returncode, r.stdout, r.stderr) != (refused[0].returncode, refused[0].stdout, refused[0].stderr)
                   for r in refused[1:]):
        failures.append("run front cache: a refused program's record moves with the cache: %r"
                        % [(r.returncode, r.stdout[:200]) for r in refused])
    checked += 4
    # Each input of the key misses, and each miss stores an image of its own.
    copied_std = os.path.join(work, "std")
    shutil.copytree(os.path.join(REPO, "std"), copied_std)
    misses = (
        (["--std-root", copied_std, "main.saw", "-o", "copy"], "a build against a copy of std"),
        (["--std-root", os.path.join(work, ".", "std"), "main.saw", "-o", "spelled"],
         "a build against another spelling of that std root"),
        (["--emit-ll", "--target", "aarch64-unknown-none-elf", "free.saw"], "a build for another target"),
        (["--emit-ll", "--target", "aarch64-unknown-none-elf", "--target-features", "-neon,-fp-armv8", "free.saw"],
         "a build for another feature set"),
        (["--emit-ll", "--target", "aarch64-unknown-none-elf", "--freestanding", "--target-features",
          "+neon,+fp-armv8", "free.saw"], "a freestanding build"),
        (["--emit-ll", "--runtime", "free.saw"], "a runtime provider's build"),
    )
    before = len(front_cache_images(cache))
    for args, where in misses:
        timed(args, where, "store", refusal=True)
        timed(args, where + ", again", "load", refusal=True)
        checked += 2
    with open(os.path.join(copied_std, "vector.saw"), "a") as fh:
        fh.write("\n// An edit the std front cache must see.\n")
    timed(misses[0][0], "a build after an edit to the std copy", "store")
    checked += 1
    other = build.STAGE1 if os.path.realpath(build.SAWC) == os.path.realpath(build.STAGE2) else build.STAGE2
    if os.path.exists(other) and open(other, "rb").read() != open(build.SAWC, "rb").read():
        timed(["main.saw", "-o", "other"], "a build by the other stage", "store", binary=other)
        timed(["main.saw", "-o", "other"], "that stage's second build", "load", binary=other)
        checked += 2
    else:
        failures.append("run front cache: no other sawc binary to miss with (%s)" % rel(other))
    images = front_cache_images(cache)
    if len(images) != before + len(misses) + 2:
        failures.append("run front cache: %d misses store %d images, not one each"
                        % (len(misses) + 2, len(images) - before))
    # Damage: a byte flipped at the same size, a truncated entry and a foreign
    # one (another key's image under this key's name) each warn, compute std's
    # front end, and are stored again.
    repair = os.path.join(work, "repair")
    for how in ("flipped", "truncated", "foreign"):
        shutil.rmtree(repair, ignore_errors=True)
        if timed(["main.saw", "-o", "fill"], "the build filling a cache for a %s entry" % how, "store",
                 directory=repair) is None:
            continue
        entry = os.path.join(repair, front_cache_images(repair)[0])
        with open(entry, "rb") as fh:
            whole = bytearray(fh.read())
        if how == "flipped":
            whole[len(whole) // 2] ^= 0xFF
        elif how == "truncated":
            whole = whole[:len(whole) // 2]
        else:
            first = whole.index(b"\n")
            head = whole[:first].split(b" ")
            head[2] = b"0" * len(head[2])
            whole = bytearray(b" ".join(head)) + whole[first:]
        with open(entry, "wb") as fh:
            fh.write(bytes(whole))
        r = sawc(["build", "--time-stages", "-g0", "main.saw", "-o", "repaired"], repair)
        code, stdout, _ = execute(os.path.join(work, "repaired"))
        if r.returncode != 0 or "warning: the front cache entry" not in r.stderr or "is damaged" not in r.stderr \
                or "time: front cache store" not in r.stderr or code != 0 or stdout != b"timed\n":
            failures.append("run front cache: past a %s entry the build exits %d, its program %s, warning %r"
                            % (how, r.returncode, code, r.stderr.strip()[:400]))
        timed(["main.saw", "-o", "after"], "the build after a %s entry's repair" % how, "load", directory=repair)
        checked += 1
    # The switches leave the cache untouched, and a bad value is a usage error.
    unused = os.path.join(work, "unused")
    for args, extra, why in ((["--no-front-cache"], None, "--no-front-cache"),
                             ([], {"SAWC_FRONT_CACHE": "off"}, "SAWC_FRONT_CACHE=off")):
        for command in (["build", "-g0"] + args + ["main.saw", "-o", "switched"],
                        ["typecheck", "--check"] + args + ["main.saw"], ["coro", "--check"] + args + ["main.saw"]):
            r = sawc(command, unused, extra)
            if r.returncode != 0 or os.path.exists(unused) or r.stderr:
                failures.append("run front cache: `%s` under %s exits %d and %s the cache"
                                % (" ".join(command[:2]), why, r.returncode,
                                   "makes" if os.path.exists(unused) else "leaves"))
            checked += 1
    r = sawc(["build", "main.saw", "-o", "refused-usage"], extra={"SAWC_FRONT_CACHE": "maybe"})
    if r.returncode != 2 or "SAWC_FRONT_CACHE takes" not in r.stdout:
        failures.append("run front cache: SAWC_FRONT_CACHE=maybe exits %d, not 2 with the usage error: %s"
                        % (r.returncode, (r.stdout + r.stderr).strip()[:300]))
    checked += 1
    # Six cold builds at once share one store.
    shared = os.path.join(work, "shared")
    launches = [subprocess.Popen([build.SAWC, "build", "-g0", "main.saw", "-o", os.path.join(work, "shared%d" % k)],
                                 cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=front_cache_environment(shared)) for k in range(6)]
    for k, proc in enumerate(launches):
        try:
            stdout, stderr = proc.communicate(timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            failures.append("run front cache: a concurrent build times out")
            continue
        code, printed, _ = execute(os.path.join(work, "shared%d" % k))
        if proc.returncode != 0 or (stdout + stderr).strip() or code != 0 or printed != b"timed\n":
            failures.append("run front cache: concurrent build %d exits %d (its program %s): %s"
                            % (k, proc.returncode, code, (stdout + stderr).strip()[:300]))
    left = front_cache_images(shared)
    parts = front_cache_parts(shared)
    if len(left) != 1 or len(parts) != 1:
        failures.append("run front cache: six concurrent builds leave %r and %r, not one image and one part"
                        % (left, parts))
    checked += len(launches)
    counts["run front cache cases checked"] = checked


def front_cache_commands():
    """The commands the differential runs, each relative to the repository:
    every run program's `.ll`, Blade's and each of its and its libraries'
    test files', a refused program's record, each
    stage subcommand's dump of two programs and of the layered fixture,
    `fix --check`, `-W`'s warnings, a freestanding program's `.ll` and each
    builtin lowering program's, and a provider and a runtime source's."""
    commands = [["build", "--emit-ll", "--std-root", "std", rel(src)] for src in cases()]
    blade = []
    for name, directory in (("blade", "blade/src"), ("toml", "libs/toml/src"), ("semver", "libs/semver/src"),
                            ("imgformat", "libs/imgformat/src")):
        blade += ["--module-path", "%s=%s" % (name, directory)]
    commands.append(["build", "--emit-ll", "--std-root", "std"] + blade + ["blade/src/main.saw"])
    # The packages' test files, each an entry outside its package's sources
    # with every package a layer before it.
    for test in sorted(glob.glob(os.path.join(REPO, "blade", "tests", "*.saw"))
                       + glob.glob(os.path.join(REPO, "libs", "*", "tests", "*.saw"))):
        commands.append(["build", "--emit-ll", "--std-root", "std"] + blade + [rel(test)])
    commands.append(["build", "--emit-ll", "--std-root", "std", rel(os.path.join(OUT, "front-differential",
                                                                               "refused.saw"))])
    layered = layers_arguments(rel(LAYERS_DIR))
    for program in (["compiler/tests/run/traits.saw"], ["compiler/tests/run/task_spawn.saw"], layered):
        for stage in ("resolve", "typecheck", "mir", "eval", "borrowck", "drops", "mono", "coro"):
            commands.append([stage, "--dump", "--std-root", "std"] + program)
        commands.append(["coro", "--bt-table", "--std-root", "std"] + program)
        commands.append(["typecheck", "--check", "--notes", "--summaries", "-W", "borrow-prefix", "--std-root", "std"]
                        + program)
        commands.append(["fix", "--check", "--std-root", "std"] + program)
        commands.append(["build", "--emit-ll", "-W", "borrow-prefix", "--std-root", "std"] + program)
    free = rel(os.path.join(OUT, "front-differential", "free.saw"))
    for program in [free] + sorted(rel(p) for p in glob.glob(os.path.join(HERE, "lowering", "builtin_*.saw"))):
        commands.append(["build", "--emit-ll", "--freestanding", "--target", "riscv32-unknown-none-elf",
                         "--std-root", "std", program])
    commands.append(["build", "--emit-ll", "--runtime", "--std-root", "std", free])
    commands.append(["runtime", "--target", PINNED_TARGET, "--std-root", "std", "--emit-ll",
                     rel(os.path.join(build.RT_ROOT, "host_macos", "dirent.saw"))])
    return commands


def check_front_cache_differential(failures, counts):
    """A command prints the same bytes and exits the same with the front cache
    off, cold and warm: every command `front_cache_commands` names, cold on a
    cache of its own holding std's cut alone, so it computes and stores every
    later layer, under the verify switch, then warm on that cache, so it
    loads them."""
    work = os.path.join(OUT, "front-differential")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    for name, text in (("refused.saw", FRONT_CACHE_REFUSED), ("free.saw", FRONT_CACHE_FREESTANDING)):
        with open(os.path.join(work, name), "w") as fh:
            fh.write(text)
    filled = os.path.join(work, "std-cuts")
    commands = front_cache_commands()

    def one(args, directory, extra=None):
        r = subprocess.run([build.SAWC] + args, cwd=REPO, capture_output=True, timeout=BUILD_TIMEOUT,
                           env=front_cache_environment(directory, extra))
        return r.returncode, r.stdout, r.stderr

    # The fill: one command of each distinct std cut, in turn; then its
    # layers' parts are removed, leaving std's images.
    seen = set()
    for args in commands:
        cut = tuple(a for a in args if a.startswith("--target") or a in ("--freestanding", "--runtime")) + (args[0] == "runtime",)
        if cut not in seen:
            seen.add(cut)
            one(args, filled)
    for part in front_cache_parts(filled):
        os.remove(os.path.join(filled, part))
    # Each command's cache: the fill's entries, linked, since an entry is
    # only ever replaced by a rename and never written in place.
    caches = []
    for k in range(len(commands)):
        directory = os.path.join(work, "cache%d" % k)
        for entry in front_cache_images(filled):
            os.makedirs(os.path.dirname(os.path.join(directory, entry)), exist_ok=True)
            os.link(os.path.join(filled, entry), os.path.join(directory, entry))
        caches.append(directory)
    jobs = list(range(len(commands)))
    off = gate_jobs.map_ordered(lambda k: one(commands[k], caches[k], {"SAWC_FRONT_CACHE": "off"}), jobs)
    # The cold pass runs under the verify switch, so every layer a command
    # stores is rebuilt from its part and held to the state computed.
    cold = gate_jobs.map_ordered(lambda k: one(commands[k], caches[k], {"SAWC_FRONT_VERIFY": "1"}), jobs)
    warm = gate_jobs.map_ordered(lambda k: one(commands[k], caches[k]), jobs)
    for name, runs in (("cold", cold), ("warm", warm)):
        differ = [" ".join(args) for args, a, b in zip(commands, off, runs) if a != b]
        if differ:
            failures.append("run front cache differential: %d of %d commands print otherwise %s than uncached: %s"
                            % (len(differ), len(commands), name, "; ".join(differ[:5])))
    stored = sum(len(front_cache_parts(directory)) for directory in caches)
    if stored == 0:
        failures.append("run front cache differential: no command stores a layer")
    counts["run front cache differential commands"] = len(commands)
    counts["run front cache differential parts stored"] = stored


# The layered front-end fixture: two packages, `shapes` importing `geometry`,
# and an entry importing both, so a build has three layers after std's.
LAYERS_DIR = os.path.join(HERE, "layers")
LAYERS_OUTPUT = b"square at (1, 2) side 3\n(4, 5)\n(2, 4)\n[6]\n9\n"
LAYERS_NAMES = ("geometry", "shapes", "program")
# A field the fault pin builds a slicer without the marker of: the program
# layer's extensions rewrite a std type's member run, and `shapes`' rewrites
# `geometry`'s, below their watermarks.
LAYERS_FAULT_FIELD = "TcProgram.member_first"
LAYER_LINE = re.compile(r"^time: front layer (\S+) (loaded|computed) ", re.M)


def layers_tree(work, name="tree"):
    """A fresh copy of the layered fixture under `work`."""
    tree = os.path.join(work, name)
    shutil.rmtree(tree, ignore_errors=True)
    shutil.copytree(LAYERS_DIR, tree)
    return tree


def layers_arguments(tree, geometry=None):
    """The fixture's mappings and entry under `tree`; `geometry` spells that
    package's directory otherwise."""
    return ["--module-path", "geometry=" + (geometry or os.path.join(tree, "geometry")),
            "--module-path", "shapes=" + os.path.join(tree, "shapes"), os.path.join(tree, "main.saw")]


def blade_arguments():
    out = []
    for name, directory in (("blade", "blade/src"), ("toml", "libs/toml/src"), ("semver", "libs/semver/src"),
                            ("imgformat", "libs/imgformat/src")):
        out += ["--module-path", "%s=%s" % (name, os.path.join(REPO, directory))]
    return out + [os.path.join(REPO, "blade", "src", "main.saw")]


def append_line(path, text):
    with open(path, "a") as fh:
        fh.write(text)


def check_front_layers(failures, counts):
    """Each layer after std's, every `--module-path` package's in dependency
    order and then the entry's, is stored in the front cache under its chain
    key (`driver_layer_key`) and loaded by the longest prefix the cache holds.
    Over the layered fixture: a cold build computes every layer and a warm one
    loads every layer; an edit to one layer's files recomputes exactly it and
    the layers after it; a refused layer is never stored; each chain input
    misses (`--no-hidden-alloc`, another spelling of a package's directory,
    the tree moved, another std, an edited std, another binary); a damaged
    part warns and its layer and the later ones are computed and stored
    again; six cold builds at once share one store. The verify switch
    (`SAWC_FRONT_VERIFY=1`) passes over the fixture and Blade, printing what
    the uncached build prints, and fails with a slicer built without one
    marker (`front_parts.py --unmarked`)."""
    work = os.path.join(OUT, "front-layers")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    tree = layers_tree(work)
    cache = os.path.join(work, "cache")
    checked = 0

    def sawc(args, directory=cache, extra=None, binary=None):
        return subprocess.run([binary or build.SAWC] + args, cwd=work, capture_output=True, text=True,
                              timeout=BUILD_TIMEOUT, env=front_cache_environment(directory, extra))

    def layered(where, want, args=None, directory=cache, extra=None, binary=None, refused=False, warns=False):
        """A `--time-stages` build of the fixture whose layers are `want`, one
        state per layer in LAYERS_NAMES' order, and whose program prints
        LAYERS_OUTPUT; with `refused`, an `--emit-ll` refused with a record."""
        out = os.path.join(work, "layered")
        tail = args or layers_arguments(tree)
        command = ["build", "--time-stages", "-g0"] + (["--emit-ll"] if refused else []) + tail
        if not refused:
            command += ["-o", out]
        r = sawc(command, directory, extra, binary)
        nonlocal checked
        checked += 1
        if refused:
            if r.returncode != 1 or not r.stdout.startswith("FILE\t"):
                failures.append("run front layers: %s exits %d with no refusal record: %s"
                                % (where, r.returncode, r.stdout.strip()[:300]))
                return r
        elif r.returncode != 0:
            failures.append("run front layers: %s fails: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
            return None
        if ("warning" in r.stderr) != warns:
            failures.append("run front layers: %s %s: %r" % (where, "does not warn" if warns else "warns",
                                                             r.stderr.strip()[:300]))
        got = [state for _, state in LAYER_LINE.findall(r.stderr)]
        names = [name for name, _ in LAYER_LINE.findall(r.stderr)]
        if names != list(LAYERS_NAMES) or got != list(want):
            failures.append("run front layers: %s has its layers %r, not %r"
                            % (where, list(zip(names, got)), list(zip(LAYERS_NAMES, want))))
        if not refused:
            code, printed, _ = execute(out)
            if code != 0 or printed != LAYERS_OUTPUT:
                failures.append("run front layers: %s's program exits %s printing %r" % (where, code, printed))
        return r

    every = ("computed",) * 3
    held = ("loaded",) * 3
    layered("the cold build", every)
    layered("the warm build", held)
    if len(front_cache_parts(cache)) != 3:
        failures.append("run front layers: a cold build stores %d parts, not one per layer"
                        % len(front_cache_parts(cache)))
    for edited, want in (("shapes/lib.saw", ("loaded", "computed", "computed")),
                         ("main.saw", ("loaded", "loaded", "computed")),
                         ("geometry/lib.saw", every)):
        append_line(os.path.join(tree, edited), "\n// An edit the front cache must see.\n")
        layered("the build after an edit to %s" % edited, want)
        layered("the build after that one", held)
    # A refused layer, here `geometry` under `--no-hidden-alloc`, is never
    # stored, so a second refusal computes it again.
    for where in ("a --no-hidden-alloc build", "a second --no-hidden-alloc build"):
        layered(where, every, args=["--no-hidden-alloc"] + layers_arguments(tree), refused=True)
    spelled = os.path.join(tree, ".", "geometry")
    layered("a build spelling geometry's directory otherwise", every, args=layers_arguments(tree, spelled))
    layered("its second build", held, args=layers_arguments(tree, spelled))
    moved = layers_tree(work, "moved")
    layered("a build of the tree moved", every, args=layers_arguments(moved))
    copied_std = os.path.join(work, "std")
    shutil.copytree(os.path.join(REPO, "std"), copied_std)
    layered("a build against a copy of std", every, args=["--std-root", copied_std] + layers_arguments(tree))
    append_line(os.path.join(copied_std, "vector.saw"), "\n// An edit the front cache must see.\n")
    layered("a build after an edit to the std copy", every, args=["--std-root", copied_std] + layers_arguments(tree))
    other = build.STAGE1 if os.path.realpath(build.SAWC) == os.path.realpath(build.STAGE2) else build.STAGE2
    if os.path.exists(other) and open(other, "rb").read() != open(build.SAWC, "rb").read():
        layered("a build by the other stage", every, binary=other)
        layered("that stage's second build", held, binary=other)
    else:
        failures.append("run front layers: no other sawc binary to miss with (%s)" % rel(other))
    # Damage: each part of a full cache truncated in turn warns once, and
    # computes its layer and the later ones; across the three, each layer is
    # the first computed once. The build after stores them again.
    tree = layers_tree(work)
    firsts = []
    for k in range(3):
        repair = os.path.join(work, "repair")
        shutil.rmtree(repair, ignore_errors=True)
        if layered("the build filling a cache for damage", every, directory=repair) is None:
            continue
        parts = front_cache_parts(repair)
        if len(parts) != 3:
            failures.append("run front layers: the fill stores %d parts, not 3" % len(parts))
            continue
        entry = os.path.join(repair, parts[k])
        with open(entry, "rb") as fh:
            whole = fh.read()
        with open(entry, "wb") as fh:
            fh.write(whole[:len(whole) // 2])
        r = sawc(["build", "--time-stages", "-g0"] + layers_arguments(tree) + ["-o", os.path.join(work, "repaired")],
                 repair)
        states = LAYER_LINE.findall(r.stderr)
        computed = [name for name, state in states if state == "computed"]
        loaded = [name for name, state in states if state == "loaded"]
        if r.returncode != 0 or r.stderr.count("warning: the front cache entry") != 1 \
                or "computing the layer again" not in r.stderr or not computed \
                or [n for n, _ in states] != list(LAYERS_NAMES) or loaded + computed != list(LAYERS_NAMES):
            failures.append("run front layers: past a truncated part the build exits %d, its layers %r, warning %r"
                            % (r.returncode, states, r.stderr.strip()[:400]))
        elif computed:
            firsts.append(computed[0])
        layered("the build after a damaged part's repair", held, directory=repair)
        checked += 1
    if sorted(firsts) != sorted(LAYERS_NAMES):
        failures.append("run front layers: the three damaged parts recompute from %r, not once from each layer"
                        % firsts)
    # Six cold builds at once share one store.
    shared = os.path.join(work, "shared")
    launches = [subprocess.Popen([build.SAWC, "build", "-g0"] + layers_arguments(tree)
                                 + ["-o", os.path.join(work, "shared%d" % k)],
                                 cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=front_cache_environment(shared)) for k in range(6)]
    for k, proc in enumerate(launches):
        try:
            stdout, stderr = proc.communicate(timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            failures.append("run front layers: a concurrent build times out")
            continue
        code, printed, _ = execute(os.path.join(work, "shared%d" % k))
        if proc.returncode != 0 or (stdout + stderr).strip() or code != 0 or printed != LAYERS_OUTPUT:
            failures.append("run front layers: concurrent build %d exits %d (its program %s): %s"
                            % (k, proc.returncode, code, (stdout + stderr).strip()[:300]))
        checked += 1
    if len(front_cache_images(shared)) != 1 or len(front_cache_parts(shared)) != 3:
        failures.append("run front layers: six concurrent builds leave %r and %r, not one image and three parts"
                        % (front_cache_images(shared), front_cache_parts(shared)))
    checked += check_front_verify(failures, work, tree, sawc)
    counts["run front layers cases checked"] = checked


# The edit differential's probes: declarations a copy of the fixture holds in
# std (`once.saw`), in its middle layer (`shapes`) and in its entry, the
# entry calling each, and per probe set the three edits it is made with.
LAYERS_PROBE = """
public func {p}_body() -> Int {{
    1
}}

public func {p}_generic<T: Copy>(value: T) -> T {{
    value
}}

public func {p}_shape() -> Int {{
    3
}}
"""
LAYERS_PROBE_EDITS = (
    ("body-only", "    1\n", "    2\n"),
    ("generic-body", "    value\n", "    let kept = value\n    kept\n"),
    ("frame-or-summary", "_shape() -> Int {\n    3\n", "_shape() -> Int64 {\n    3\n"),
)
LAYERS_PROBE_CALLS = """
func probes() {{
    print("{{}} {{}} {{}}", {s}_body(), {s}_generic(4), {s}_shape())
    print("{{}} {{}} {{}}", {m}_body(), {m}_generic(true), {m}_shape())
    print("{{}} {{}} {{}}", entry_probe_body(), entry_probe_generic(5), entry_probe_shape())
}}
"""


# A package module no file imports, which refuses the program when loaded.
SCAN_UNIMPORTED = "// No module imports this one; loading it refuses the program.\n\n" \
                  "public func broken() -> Int {\n    \"not an Int\"\n}\n"
# Text only the line-shaped view of a file reads as an import: a string
# literal's second line, and a refusal case's body.
SCAN_TEXT_SHAPES = (
    ("a string literal",
     "\npublic func notes() -> String {\n    \"the first line\nimport geometry.extra\nthe last line\"\n}\n"),
    ("a refusal case's body",
     "\n@test(refuses: \"type.mismatch\") \"an import in a refusal body\"\nimport geometry.extra\n"
     "    let x: Int = \"s\"\n@test(end: refuses)\n"),
)


def check_front_scan_text(failures, counts):
    """The import scan reads a file's import declarations off its tokens: a
    line inside a string literal or a refusal case's body that reads
    `import geometry.extra` names no import, so the package layer never
    loads `geometry.extra`, a module no file imports and whose body refuses.
    Each shape builds, cold and warm, and prints the fixture's output and the
    uncached build's `.ll`."""
    work = os.path.join(OUT, "front-scan-text")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    checked = 0
    for what, text in SCAN_TEXT_SHAPES:
        tree = layers_tree(work, re.sub(r"[^a-z]+", "-", what).strip("-"))
        with open(os.path.join(tree, "geometry", "extra.saw"), "w") as fh:
            fh.write(SCAN_UNIMPORTED)
        append_line(os.path.join(tree, "geometry", "lib.saw"), text)
        cache = os.path.join(tree, "cache")
        runs = []
        for extra in ({"SAWC_FRONT_CACHE": "off"}, None, None):
            r = subprocess.run([build.SAWC, "build", "--emit-ll", "-g0"] + layers_arguments(tree), cwd=work,
                               capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                               env=front_cache_environment(cache, extra))
            runs.append((r.returncode, r.stdout, r.stderr))
        out = os.path.join(tree, "program")
        built = subprocess.run([build.SAWC, "build", "-g0"] + layers_arguments(tree) + ["-o", out], cwd=work,
                               capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                               env=front_cache_environment(cache))
        code, printed, _ = execute(out) if built.returncode == 0 else (None, b"", b"")
        if runs[0][0] != 0 or runs[1] != runs[0] or runs[2] != runs[0] or code != 0 or printed != LAYERS_OUTPUT:
            failures.append("run front scan: with `import geometry.extra` in %s the build exits %d off, %d cold "
                            "and %d warm, its program %s: %s" % (what, runs[0][0], runs[1][0], runs[2][0], code,
                                                                 (runs[0][1] + runs[0][2]).strip()[:300]))
        checked += 1
    counts["run front scan text shapes"] = checked


def check_front_shared_writers(failures, counts):
    """Two store threads of one command may write one key: `resolve --check`
    over two entries that share the fixture's packages, on a cold cache,
    stores the packages' layers from the first input's thread while the
    second input misses and stores them again. Each writer has a temporary
    name of its own, so every run succeeds with no warning and no temporary
    left, and the next command loads every layer."""
    work = os.path.join(OUT, "front-shared-writers")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    tree = layers_tree(work)
    second = os.path.join(tree, "second.saw")
    with open(second, "w") as fh:
        fh.write("import geometry.{Point}\nimport shapes.{Square}\n\nfunc main() {\n"
                 "    print(\"{}\", Square(corner: Point(x: 0, y: 0), side: 2))\n}\n")
    args = ["resolve", "--check"] + layers_arguments(tree) + [second]
    checked = 0
    for k in range(8):
        cache = os.path.join(work, "cache%d" % k)
        r = subprocess.run([build.SAWC] + args, cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                           env=front_cache_environment(cache))
        left = glob.glob(os.path.join(cache, "front", "g*", "*.tmp"))
        if r.returncode != 0 or r.stderr or left:
            failures.append("run front shared writers: round %d exits %d, leaves %r: %s"
                            % (k, r.returncode, left, (r.stdout + r.stderr).strip()[:300]))
            continue
        warm = subprocess.run([build.SAWC, "build", "--time-stages", "--emit-ll", "-g0"] + layers_arguments(tree),
                              cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                              env=front_cache_environment(cache))
        states = [state for name, state in LAYER_LINE.findall(warm.stderr) if name != "program"]
        if warm.returncode != 0 or "warning" in warm.stderr or states != ["loaded", "loaded"]:
            failures.append("run front shared writers: after round %d the packages' layers are %r: %s"
                            % (k, states, warm.stderr.strip()[:300]))
        checked += 1
    counts["run front shared writer rounds"] = checked


def check_front_layer_edits(failures, counts):
    """After an edit to std, to the fixture's middle layer or to its entry,
    each body-only, to a generic's body, or to a signature, a build warm on
    the cache the unedited tree filled loads the layers before the edit and
    computes the rest, and its `.ll` and the checker's notes and summaries are
    the bytes a cold build on an empty cache and an uncached one print; and
    so is the record of an entry edit the checker refuses."""
    work = os.path.join(OUT, "front-layer-edits")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    tree = os.path.join(work, "tree")
    std = os.path.join(work, "std")
    shutil.copytree(os.path.join(REPO, "std"), std)
    with open(os.path.join(std, "once.saw")) as fh:
        once = fh.read()
    with open(os.path.join(LAYERS_DIR, "shapes", "lib.saw")) as fh:
        shapes = fh.read()
    with open(os.path.join(LAYERS_DIR, "main.saw")) as fh:
        entry = fh.read()
    imports = ("import std.once.{std_probe_body, std_probe_generic, std_probe_shape}\n"
               "import shapes.{middle_probe_body, middle_probe_generic, middle_probe_shape}\n")
    entry_head, entry_main = entry.split("\nfunc main() {\n", 1)
    base = {
        "std": (os.path.join(std, "once.saw"), once + LAYERS_PROBE.format(p="std_probe")),
        "middle": (os.path.join(tree, "shapes", "lib.saw"), shapes + LAYERS_PROBE.format(p="middle_probe")),
        "entry": (os.path.join(tree, "main.saw"),
                  entry_head + "\n" + imports + LAYERS_PROBE.format(p="entry_probe").replace("public ", "")
                  + LAYERS_PROBE_CALLS.format(s="std_probe", m="middle_probe")
                  + "\nfunc main() {\n    probes()\n" + entry_main),
    }
    warm = os.path.join(work, "warm")
    args = ["--std-root", std] + layers_arguments(tree)
    commands = (["build", "--emit-ll"] + args, ["typecheck", "--check", "--notes", "--summaries"] + args)
    held = {"std": ("computed",) * 3, "middle": ("loaded", "computed", "computed"),
            "entry": ("loaded", "loaded", "computed")}
    checked = 0

    def restore():
        shutil.rmtree(tree, ignore_errors=True)
        shutil.copytree(LAYERS_DIR, tree)
        for path, text in base.values():
            with open(path, "w") as fh:
                fh.write(text)

    def run(command, directory, extra=None):
        r = subprocess.run([build.SAWC] + command, cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                           env=front_cache_environment(directory, extra))
        return r.returncode, r.stdout, r.stderr

    restore()
    for command in commands:
        filled = run(command, warm)
        if filled[0] != 0:
            failures.append("run front layer edits: the unedited tree's `%s` exits %d: %s"
                            % (command[0], filled[0], (filled[1] + filled[2]).strip()[:300]))
            return
    edits = [(where, kind, old, new) for where in ("std", "middle", "entry") for kind, old, new in LAYERS_PROBE_EDITS]
    edits.append(("entry", "a refused edit", "    probes()\n", "    probes()\n    let wrong: Bool = 1\n"))
    for where, kind, old, new in edits:
        restore()
        path, text = base[where]
        if where == "std":
            text = once + LAYERS_PROBE.format(p="std_probe").replace(old, new, 1)
        elif where == "middle":
            text = shapes + LAYERS_PROBE.format(p="middle_probe").replace(old, new, 1)
        elif old not in text:
            failures.append("run front layer edits: the %s edit's text is not in the entry" % kind)
            continue
        else:
            text = text.replace(old, new, 1)
        with open(path, "w") as fh:
            fh.write(text)
        cold = os.path.join(work, "cold")
        for command in commands:
            shutil.rmtree(cold, ignore_errors=True)
            off = run(command, cold, {"SAWC_FRONT_CACHE": "off"})
            fresh = run(command, cold)
            timed = command[:1] + ["--time-stages"] + command[1:] if command[0] == "build" else command
            loaded = run(timed, warm)
            if fresh != off or loaded[:2] != off[:2] or (command[0] != "build" and loaded != off):
                failures.append("run front layer edits: after a %s edit in %s, `%s` prints otherwise warm, cold "
                                "and uncached (exits %d, %d, %d)" % (kind, where, command[0], loaded[0], fresh[0],
                                                                      off[0]))
            if command[0] == "build":
                states = tuple(state for _, state in LAYER_LINE.findall(loaded[2]))
                if states != held[where]:
                    failures.append("run front layer edits: after a %s edit in %s the warm build's layers are %r, "
                                    "not %r" % (kind, where, states, held[where]))
                refused = kind == "a refused edit"
                if (off[0] != 0) != refused or (refused and not off[1].startswith("FILE\t")):
                    failures.append("run front layer edits: after a %s edit in %s the build exits %d: %s"
                                    % (kind, where, off[0], (off[1] + off[2]).strip()[:300]))
            checked += 1
    counts["run front layer edits checked"] = checked


def check_front_verify(failures, work, tree, sawc):
    """The verify switch over the fixture and Blade, each on a fresh cache:
    it passes and prints what the uncached build prints. Then the fault pin:
    sawc built with a slicer that leaves out LAYERS_FAULT_FIELD's marker
    fails the switch over the fixture. Returns the cases checked."""
    checked = 0
    for name, args in (("the layered fixture", layers_arguments(tree)), ("Blade", blade_arguments())):
        off = sawc(["build", "--emit-ll"] + args, extra={"SAWC_FRONT_CACHE": "off"})
        fresh = os.path.join(work, "verify-" + name.split()[-1].lower())
        shutil.rmtree(fresh, ignore_errors=True)
        verified = sawc(["build", "--emit-ll"] + args, fresh, {"SAWC_FRONT_VERIFY": "1"})
        if off.returncode != 0 or (verified.returncode, verified.stdout, verified.stderr) != (0, off.stdout, ""):
            failures.append("run front verify: over %s the switch exits %d, its .ll %s the uncached one's: %s"
                            % (name, verified.returncode, "is" if verified.stdout == off.stdout else "is not",
                               verified.stderr.strip()[:300]))
        checked += 1
    fault = os.path.join(work, "fault")
    shutil.rmtree(fault, ignore_errors=True)
    mono = os.path.join(fault, "mono")
    shutil.copytree(os.path.join(COMPILER, "mono", "src"), mono)
    r = subprocess.run([sys.executable, os.path.join(COMPILER, "tools", "front_parts.py"), "--unmarked",
                        LAYERS_FAULT_FIELD, "--out", os.path.join(mono, "frontparts.saw")],
                       cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run front verify: the faulty slicer is not written: %s" % (r.stdout + r.stderr).strip()[:300])
        return checked
    faulty = os.path.join(fault, "sawc")
    packages = []
    for name, path in build.STAGE_PACKAGES:
        packages += ["--module-path", "%s=%s" % (name, mono if name == "sawmono" else os.path.join(REPO, path))]
    r = subprocess.run([build.SAWC, "build", "-O0", "-g0", "--no-front-cache", "--std-root", "std"] + packages
                       + [rel(build.DRIVER_ENTRY), "-o", faulty], cwd=REPO, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("run front verify: sawc does not build with the faulty slicer: %s"
                        % (r.stdout + r.stderr).strip()[:300])
        return checked
    # The manifest the stages share, beside them: `build.SAWC` may be the
    # fixpoint lane's twin, which has none beside it.
    shutil.copy(os.path.join(os.path.dirname(build.STAGE2), build.RUNTIME_MANIFEST_NAME), fault)
    r = sawc(["build", "--emit-ll"] + layers_arguments(tree), os.path.join(fault, "cache"),
             {"SAWC_FRONT_VERIFY": "1"}, binary=faulty)
    if r.returncode == 0 or "front cache verify: the layer" not in r.stderr:
        failures.append("run front verify: with %s's marker left out the switch exits %d: %s"
                        % (LAYERS_FAULT_FIELD, r.returncode, r.stderr.strip()[:300]))
    return checked + 1


def time_stage_lines(failures, stderr, split):
    """Checks the `--time-stages` report `stderr`, a split build's when
    `split` (and then its split and unit lines lead it), and whether its
    shape held far enough to read the rest."""
    lines = stderr.splitlines()
    units = 0
    joins = [line for line in lines if TIME_STAGES_JOIN.match(line)]
    if len(joins) > 1:
        failures.append("run time stages: %d `front layers join` lines" % len(joins))
    lines = [line for line in lines if not TIME_STAGES_JOIN.match(line)]
    # The front end's layers, loaded from the front cache or computed and
    # stored there, come first; its steps run only when one is computed.
    computed = False
    while lines and TIME_STAGES_FRONT.match(lines[0]):
        computed = computed or lines[0].startswith("time: std front end") or " computed " in lines[0]
        lines = lines[1:]
    if lines and TIME_STAGES_SPLIT.match(lines[0]):
        lines = lines[1:]
        while lines and TIME_STAGES_UNIT.match(lines[0]):
            units += 1
            lines = lines[1:]
        if lines and TIME_STAGES_CACHE.match(lines[0]):
            lines = lines[1:]
        if units == 0:
            failures.append("run time stages: a split build's `split` line is followed by no unit's compile")
    if split and units == 0:
        failures.append("run time stages: a split build reports no `split` line and no unit's compile")
    seen = []
    for line in lines:
        m = TIME_STAGES_LINE.match(line)
        if m is None:
            failures.append("run time stages: a line is not `time: STEP MS ms`: %r" % line[:200])
        else:
            seen.append(m.group(1))
    if not seen or seen[-1] != "total":
        failures.append("run time stages: `total` is not the last line: %r" % seen)
        return False
    steps = seen[:-1]
    ranks = [TIME_STAGES_ORDER.index(s) if s in TIME_STAGES_ORDER else -1 for s in steps]
    if -1 in ranks or ranks != sorted(set(ranks)):
        failures.append("run time stages: the steps %r are not distinct and in pipeline order" % steps)
    for need in TIME_STAGES_ALWAYS:
        if need not in steps and (computed or need not in TIME_STAGES_FRONT_STEPS):
            failures.append("run time stages: no `%s` line in %r" % (need, steps))
        if need in steps and not computed and need in TIME_STAGES_FRONT_STEPS:
            failures.append("run time stages: a `%s` line with every layer loaded: %r" % (need, steps))
    if "clang link" not in steps and not ("clang" in steps and "link" in steps):
        failures.append("run time stages: no clang or link line in %r" % steps)
    return True


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
_DIRECTIVE = re.compile(
    r"^// (probe|about|stage 0|speeds|prints|exits|stderr|panics|undefined|ll defines|ll omits|leaks|c helper): ?(.*)$")
# A C helper's name: a `.c` file in `probes/` itself.
_C_HELPER = re.compile(r"^[A-Za-z0-9_]+\.c$")
_ISSUE = re.compile(r"\(SL-\d+\)$")
SPEEDS = ("-O0", "-O1", "-O2", "-Os", "-Oz")
# The lines each kind of probe takes, each as (fewest, most), most None for
# any number. A line its kind does not list is refused, so no header states
# what the lane does not check.
_BUILT = {"probe": (1, 1), "about": (1, 1), "stage 0": (1, 1), "speeds": (1, 1),
          "ll defines": (0, None), "ll omits": (0, None), "c helper": (0, 1)}
PROBE_LINES = {
    "stated": dict(_BUILT, prints=(0, None), exits=(0, 1), stderr=(0, None), leaks=(0, 1)),
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
LEAKS_COUNT = "run programs holding no leak"
LEAKS_SKIPPED = "run programs whose leak check is skipped off macOS"
# The leak checker: macOS's `leaks`, which runs the program to its exit and
# then reports every block no reference reaches.
LEAKS = "/usr/bin/leaks"
_LEAK_REPORT = re.compile(r"^Process \d+: (\d+) leaks? for (\d+) total leaked bytes\.$", re.M)


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
    if header.get("leaks", ["none"]) != ["none"]:
        problems.append("%s: `// leaks:` states `none`, the one leak count the lane holds a probe to" % where)
    exits = header.get("exits", ["0"])[0]
    if not re.match(r"^(0|[1-9][0-9]{0,2})$", exits) or int(exits) > 255:
        problems.append("%s: `// exits:` states a status, 0 to 255" % where)
    # A stated run states what it writes, on one stream or the other.
    if kind == "stated" and not header.get("prints") and not header.get("stderr"):
        problems.append("%s: a stated probe states at least one `// prints:` or `// stderr:` line" % where)
    about = header.get("about", [])
    if len(about) == 1 and not _ISSUE.search(about[0]):
        problems.append("%s: its `// about:` line ends with its issue, `(SL-N)`" % where)
    if "speeds" in header:
        speeds = header["speeds"][0].split()
        if not speeds or len(set(speeds)) != len(speeds) or any(s not in SPEEDS for s in speeds):
            problems.append("%s: `// speeds:` lists distinct levels of %s" % (where, " ".join(SPEEDS)))
    for named in header.get("c helper", []):
        if not _C_HELPER.match(named) or not os.path.isfile(os.path.join(PROBES, named)):
            problems.append("%s: `// c helper:` names a `.c` file in %s, not %r" % (where, rel(PROBES), named))
    return problems


def c_helper(header):
    """The path of the C helper a probe's `// c helper:` line names, or None."""
    named = header.get("c helper", [])
    return os.path.join(PROBES, named[0]) if named else None


def orphan_helpers():
    """Failures for each `.c` file of `probes/` no probe names as its C
    helper, which nothing would compile."""
    named = set()
    for src in probes():
        named.update(probe_header(src).get("c helper", []))
    return ["run %s: a C helper no probe's `// c helper:` line names" % rel(path)
            for path in sorted(glob.glob(os.path.join(PROBES, "*.c"))) if os.path.basename(path) not in named]


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
    lines = text.split("\n")
    defines = [line for line in lines if line.startswith("define ")]
    # A global is defined by a line that opens with its name and an `=`.
    globals_ = [line for line in lines if line.startswith("@")]
    problems = ["%s: the `.ll` defines no `%s`" % (where, symbol) for symbol in defined
                if not any(spelled in line for line in defines
                           for spelled in ("@%s(" % symbol, '@"%s"(' % symbol))
                and not any(line.startswith(spelled) for line in globals_
                            for spelled in ("@%s = " % symbol, '@"%s" = ' % symbol))]
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


def leak_problems(where, binary):
    """Failures of `binary` run under `leaks --atExit`: one unless it reports
    no leak. None off macOS, where the checker does not exist."""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run([LEAKS, "--atExit", "--", binary], cwd=OUT, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT * 3)
    except subprocess.TimeoutExpired:
        return ["%s: `leaks --atExit` did not finish" % where]
    m = _LEAK_REPORT.search(r.stdout)
    if m is None:
        return ["%s: `leaks --atExit` reports no leak count (exit %d): %s"
                % (where, r.returncode, (r.stdout + r.stderr)[-300:])]
    if m.group(1) != "0":
        return ["%s: `leaks --atExit` finds %s leaks of %s bytes" % (where, m.group(1), m.group(2))]
    return []


def held_probe(src, header):
    """(failures, counts) for a probe of a kind its header states, built by
    sawc alone at each of its speeds. Each build is held whole, since a read
    of an uninitialised local can pass at one level and not another."""
    kind = header["probe"][0]
    name = os.path.splitext(os.path.basename(src))[0]
    failures = []
    ll_failures = []
    leak_failures = []
    leaks_skipped = False
    for speed in header["speeds"][0].split():
        where = "run %s %s" % (rel(src), speed)
        # build_new's naming; a refused build writes no `.ll`, so a stale one
        # must not stand in for it.
        ll = os.path.join(OUT, name + (".new" if speed == "-O0" else ".new" + speed[1:]) + ".ll")
        if os.path.exists(ll):
            os.remove(ll)
        ok, binary, log = build_new(src, speed, c_helper(header))
        if kind == "link-fails":
            symbols = header["undefined"]
            if ok or first_error(log) is not None or "ndefined" not in log or any(s not in log for s in symbols):
                failures.append("%s: sawc %s, not a link failure naming %s undefined: %s"
                                % (where, "links it" if ok else "fails otherwise",
                                   ", ".join("`%s`" % s for s in symbols), log[:300]))
        elif not ok or log:
            failures.append("%s: sawc %s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                                  log[:300]))
            continue
        elif kind == "stated":
            want = "".join(line + "\n" for line in header.get("prints", [])).encode()
            status = int(header.get("exits", ["0"])[0])
            said = "".join(line + "\n" for line in header.get("stderr", [])).encode()
            code, out, err = execute(binary)
            if code != status or out != want:
                failures.append("%s: exit %s (expected %d); output: %s"
                                % (where, code, status, output_difference(out, want)))
            elif "stderr" in header and err != said:
                failures.append("%s: standard error differs: %s" % (where, output_difference(err, said)))
            elif "leaks" in header:
                found = leak_problems(where, binary)
                if found is None:
                    leaks_skipped = True
                else:
                    leak_failures += found
        else:
            want = header.get("prints", [])
            panic = header["panics"][0]
            code, out, err = execute(binary)
            printed = lines_of(masked(out))
            said = lines_of(masked(err))
            if code != -signal.SIGABRT or printed != want or not said or not panic_dump_ok(said[1:]) \
                    or not said[0].startswith("panic at ?: ") or panic not in said[0]:
                failures.append("%s: exit %s (expected %d); output: %s; %r on standard error, not a panic holding "
                                "%r" % (where, code, -signal.SIGABRT,
                                        output_difference(masked(out), "".join(line + "\n" for line in want)),
                                        err[:300], panic))
        ll_failures += ll_problems(where, ll, header)
    counts = {}
    if not failures:
        counts[PROBE_COUNTS[kind]] = 1
    if not ll_failures and (header.get("ll defines") or header.get("ll omits")):
        counts[LL_COUNT] = 1
    if "leaks" in header and not failures and not leak_failures:
        counts[LEAKS_SKIPPED if leaks_skipped else LEAKS_COUNT] = 1
    return failures + ll_failures + leak_failures, counts


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


DEEP_MATCH_ARMS = 6400
# The values whose arm the generated program prints one by one: both ends,
# the middle, and two that only the catch-all takes.
DEEP_MATCH_INPUTS = (0, 1, 2, 3199, 6398, 6399, 6400, -1)


def deep_match_arm(n):
    """The arm the generated `match` gives `n`: its last digit, or 10."""
    return n % 10 if 0 <= n < DEEP_MATCH_ARMS else 10


def deep_match_source(arms):
    """A `match` of `arms` integer literal arms and a catch-all, and a caller
    printing the arm of each of DEEP_MATCH_INPUTS, then every value from -2 to
    `arms + 1` weighed by its arm and summed, so a misplaced arm moves it."""
    lines = ["// Generated by run_lane.py's check_deep_match (SL-970).", "func arm(n: Int) -> Int {", "    match n {"]
    for start in range(0, arms, 16):
        lines.append("        " + " ".join("case %d -> %d," % (k, deep_match_arm(k))
                                           for k in range(start, min(start + 16, arms))))
    lines += ["        case _ -> 10", "    }", "}", "", "func main() {"]
    lines += ['    print("{}", arm(%d))' % n for n in DEEP_MATCH_INPUTS]
    lines += ["    var total = 0", "    for i in -2..%d {" % (arms + 2), "        total = total + i * arm(i)", "    }",
              '    print("{}", total)', "}"]
    return "\n".join(lines) + "\n"


def check_deep_match(failures, counts):
    """A `match` of thousands of literal arms builds, its false edges taking
    no compiler stack per arm, and each value takes its own arm: the generated
    program, held as a stated probe, prints each input's arm and the weighted
    sum."""
    src = os.path.join(OUT, "deep_match.saw")
    with open(src, "w") as fh:
        fh.write(deep_match_source(DEEP_MATCH_ARMS))
    prints = ["%d" % deep_match_arm(n) for n in DEEP_MATCH_INPUTS]
    prints.append("%d" % sum(i * deep_match_arm(i) for i in range(-2, DEEP_MATCH_ARMS + 2)))
    header = {"probe": ["stated"], "speeds": ["-O0 -O2"], "prints": prints}
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
            failures.append("%s: sawc %s: %s" % (where, "builds it but prints" if ok else "does not build it",
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
            failures.append("%s: sawc %s: %s" % (where, "builds it but prints" if ok else "does not build it",
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


# The lines of a `dump_tasks()` dump beyond a task's and a frame's: its
# header, the header when nothing is live, and a group it could not read.
_STDOUT_DUMP_HEADER = re.compile(r"saw tasks: (\d+) live \(unsynchronized snapshot\)$")
_STDOUT_DUMP_NONE = "saw tasks: none live"
_DUMP_NOT_READ = re.compile(r"  task group \d+ not read: busy on (another|this) thread$")
# How often each dump-churn probe runs at each level, and the tasks its `main`
# holds through every dump, by the function each is parked in.
DUMP_CHURN_RUNS = 10
DUMP_CHURN_HELD = 2
DUMP_CHURN_HELD_IN = " in held_for_the_dump"


def dump_churn_problem(out):
    """The first way a dump-churn probe's standard output breaks the dump's
    invariants, or None: it is dumps, then `quiescent` and one more dump,
    then `done`; each dump's header counts the task lines under it and names
    both tasks `main` holds; and the quiescent dump names those alone, with no
    group it could not read."""
    lines = lines_of(out)
    if not lines or lines[-1] != "done":
        return "it does not end with `done`"
    dumps = []
    quiescent = False
    current = None
    for line in lines[:-1]:
        m = _STDOUT_DUMP_HEADER.match(line)
        if m or line == _STDOUT_DUMP_NONE:
            current = {"count": int(m.group(1)) if m else 0, "tasks": [], "not_read": 0, "quiescent": quiescent}
            dumps.append(current)
            quiescent = False
        elif line == "quiescent":
            quiescent = True
            current = None
        elif current is not None and _DUMP_TASK.match(line):
            current["tasks"].append([])
        elif current is not None and current["tasks"] and _DUMP_FRAME.match(line):
            current["tasks"][-1].append(line)
        elif current is not None and _DUMP_NOT_READ.match(line):
            current["not_read"] += 1
        else:
            return "a line that is no dump's: %r" % line[:100]
    if not dumps or not dumps[-1]["quiescent"]:
        return "no dump follows `quiescent`"
    for k, dump in enumerate(dumps):
        held = sum(1 for frames in dump["tasks"] if any(DUMP_CHURN_HELD_IN in f for f in frames))
        if dump["count"] != len(dump["tasks"]):
            return "dump %d of %d counts %d live and prints %d task lines" % (k + 1, len(dumps), dump["count"],
                                                                             len(dump["tasks"]))
        if held != DUMP_CHURN_HELD:
            return "dump %d of %d names %d of the %d tasks `main` holds" % (k + 1, len(dumps), held,
                                                                           DUMP_CHURN_HELD)
    last = dumps[-1]
    if last["not_read"] or last["count"] != DUMP_CHURN_HELD:
        return "the quiescent dump prints %d tasks and %d groups not read" % (last["count"], last["not_read"])
    return None


def check_dump_beside_churn(name):
    """The check of dump-churn probe `name`: built at -O0 and -O2, each run
    `DUMP_CHURN_RUNS` times, every run exiting 0 with nothing on standard
    error and its dumps holding `dump_churn_problem`'s invariants. Which of
    the churned tasks a dump catches live is the scheduler's, so no header
    line can state the output."""
    def check(failures, counts):
        probe = os.path.join(PROBES, name)
        for speed in ("-O0", "-O2"):
            where = "run %s %s" % (rel(probe), speed)
            ok, binary, log = build_new(probe, speed)
            if not ok or log:
                failures.append("%s: sawc %s: %s" % (where, "builds it but prints" if ok else "does not build it",
                                                      log[:300]))
                continue
            for k in range(DUMP_CHURN_RUNS):
                code, out, err = execute(binary)
                problem = None
                if code != 0 or err:
                    problem = "exit %s, %r on standard error" % (code, err[:300])
                else:
                    problem = dump_churn_problem(out.decode("utf-8", "replace"))
                if problem:
                    failures.append("%s: run %d of %d: %s" % (where, k + 1, DUMP_CHURN_RUNS, problem))
                    break
                counts["run dumps beside churn holding their count"] = (
                    counts.get("run dumps beside churn holding their count", 0) + 1)
    return check


def check_leak_detection(failures, counts):
    """The leak check sees a leak: `probes/leaks_check_sees_a_leak.saw`, built
    at -O0, drops its only pointer to one `malloc`ed block, and `leak_problems`
    must report that one block, at whatever size the allocator rounds it to."""
    probe = os.path.join(PROBES, "leaks_check_sees_a_leak.saw")
    where = "run %s -O0" % rel(probe)
    ok, binary, log = build_new(probe, "-O0")
    if not ok or log:
        failures.append("%s: sawc %s: %s" % (where, "builds it but prints" if ok else "does not build it", log[:300]))
        return
    found = leak_problems(where, binary)
    if found is None:
        counts[LEAKS_SKIPPED] = counts.get(LEAKS_SKIPPED, 0) + 1
        return
    one = "%s: `leaks --atExit` finds 1 leaks of " % where
    if len(found) != 1 or not found[0].startswith(one):
        failures.append("%s: the leak check does not report the one lost block: %s"
                        % (where, "; ".join(found) if found else "it reports no leak"))
        return
    counts["run leak checks reporting a planted leak"] = 1


# What `sawc build -c` writes for `probes/object_output_linkage.saw`: the
# export's C symbol defined and external, the seam its overflow check reaches
# undefined, and nothing of a C entry, since the source has no `main`.
OBJECT_PROBE = "object_output_linkage.saw"
OBJECT_EXPORT = "probe_object_answer"
OBJECT_UNDEFINED = "__saw_rt_panic"
OBJECT_ABSENT = ("main", "__saw_rt_get_argc", "__saw_rt_get_argv")
# The function only Saw calls, which must stay internal: a local symbol, or
# none once -O2 inlines it.
OBJECT_INTERNAL = "helper"


def object_symbols(obj, mach_o):
    """`obj`'s symbols as `nm` lists them, {name: type letter}, a Mach-O
    name's leading underscore removed; (None, why) when `nm` cannot read it.
    A symbol sawc decorates may hold spaces, so a name is the rest of its
    line."""
    r = subprocess.run(["nm", obj], capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()[:300]
    symbols = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and re.match(r"^[0-9a-fA-F]{8,}$", parts[0]):
            parts = parts[1].split(None, 1)
        if len(parts) != 2:
            continue
        kind, name = parts
        if mach_o and name.startswith("_"):
            name = name[1:]
        symbols[name] = kind
    return symbols, ""


def check_object_output(failures, counts):
    """`sawc build -c` at -O0 and -O2, with an `-o` naming no `.o`: the object
    is written with `.o` appended and nothing at the name itself, sawc prints
    nothing, and `nm` reads the executable's linkage with no C entry
    (`OBJECT_*` above)."""
    probe = os.path.join(PROBES, OBJECT_PROBE)
    mach_o = "-apple-" in build.clang_triple(TARGET or build.host_triple())
    for speed in ("-O0", "-O2"):
        where = "run %s %s" % (rel(probe), speed)
        stem = os.path.join(OUT, "object_output" + speed[1:])
        for stale in (stem, stem + ".o"):
            if os.path.exists(stale):
                os.remove(stale)
        r = subprocess.run([build.SAWC, "build", "-c", speed, "--std-root", "std"] + target_flags()
                           + [rel(probe), "-o", stem], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode != 0 or said:
            failures.append("%s: sawc build -c %s: %s" % (where, "exits %d" % r.returncode if r.returncode
                                                          else "prints", said[:300]))
            continue
        if os.path.exists(stem) or not os.path.exists(stem + ".o"):
            failures.append("%s: `-o %s` names no `.o`, so the object is %s.o and nothing is written at %s"
                            % (where, rel(stem), rel(stem), rel(stem)))
            continue
        symbols, why = object_symbols(stem + ".o", mach_o)
        if symbols is None:
            failures.append("%s: nm cannot read the object: %s" % (where, why))
            continue
        problems = []
        if symbols.get(OBJECT_EXPORT) != "T":
            problems.append("`%s` is %s, not defined and external (T)"
                            % (OBJECT_EXPORT, symbols.get(OBJECT_EXPORT, "absent")))
        if symbols.get(OBJECT_UNDEFINED) != "U":
            problems.append("`%s` is %s, not undefined (U)"
                            % (OBJECT_UNDEFINED, symbols.get(OBJECT_UNDEFINED, "absent")))
        for name in OBJECT_ABSENT:
            if name in symbols:
                problems.append("`%s` is in the object (%s), which has no `main`" % (name, symbols[name]))
        internal = {name: kind for name, kind in symbols.items() if OBJECT_INTERNAL in name}
        for name, kind in internal.items():
            if not kind.islower():
                problems.append("`%s` is external (%s); only an export leaves the object" % (name, kind))
        if speed == "-O0" and not internal:
            problems.append("no `%s` symbol at -O0, where nothing inlines it" % OBJECT_INTERNAL)
        for problem in problems:
            failures.append("%s: %s" % (where, problem))
        if not problems:
            counts["run objects holding their linkage"] = counts.get("run objects holding their linkage", 0) + 1


# The bare-metal target `probes/bare_metal_object.saw` is built for: it has
# no runtime and no C library, so `-c` is the one build that writes anything,
# and the object is ELF64 AArch64 (`e_machine` EM_AARCH64) and relocatable.
BARE_METAL_PROBE = "bare_metal_object.saw"
BARE_METAL_TARGET = "aarch64-unknown-none-elf"
BARE_METAL_EXPORT = "probe_bare_metal_answer"
ELF_AARCH64 = 183
ELF_RELOCATABLE = 1


def elf_header_problem(path):
    """Why the file at `path` is no little-endian ELF64 AArch64 relocatable
    object, or ""."""
    with open(path, "rb") as fh:
        head = fh.read(20)
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return "it is not an ELF file"
    if head[4] != 2 or head[5] != 1:
        return "it is not little-endian ELF64 (class %d, data %d)" % (head[4], head[5])
    kind = int.from_bytes(head[16:18], "little")
    machine = int.from_bytes(head[18:20], "little")
    if kind != ELF_RELOCATABLE or machine != ELF_AARCH64:
        return "its e_type is %d and e_machine %d, not %d and %d" % (kind, machine, ELF_RELOCATABLE, ELF_AARCH64)
    return ""


def bare_metal_record_problem(what):
    """Why the bare-metal target's clang record is not beside the stages, or
    "": the stage build writes it (`build.configure_bare_metal_targets`), so
    no check here may be what makes it exist."""
    if os.path.exists(build.runtime_manifest(BARE_METAL_TARGET)):
        return ""
    return ("run %s: no %s beside the stages; the stage build writes it"
            % (what, rel(build.runtime_manifest(BARE_METAL_TARGET))))


def check_bare_metal_object(failures, counts):
    """The bare-metal target end to end: the stage build has recorded its
    clang; `sawc build -c --target aarch64-unknown-none-elf` at -O0 and -O2
    prints nothing and writes an ELF64 AArch64 relocatable object whose
    export `nm` reads defined and external; the same build without `-c` is
    refused with exit status 2, naming `-c`, before any file is written."""
    probe = os.path.join(PROBES, BARE_METAL_PROBE)
    problem = bare_metal_record_problem(rel(probe))
    if problem:
        failures.append(problem)
        return
    for speed in ("-O0", "-O2"):
        where = "run %s %s" % (rel(probe), speed)
        obj = os.path.join(OUT, "bare_metal" + speed[1:] + ".o")
        if os.path.exists(obj):
            os.remove(obj)
        r = subprocess.run([build.SAWC, "build", "-c", speed, "--std-root", "std", "--target", BARE_METAL_TARGET,
                            rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode != 0 or said or not os.path.exists(obj):
            failures.append("%s: sawc build -c --target %s exits %d: %s"
                            % (where, BARE_METAL_TARGET, r.returncode, said[:300]))
            continue
        problem = elf_header_problem(obj)
        if problem:
            failures.append("%s: the object %s" % (where, problem))
            continue
        symbols, why = object_symbols(obj, False)
        if symbols is None:
            failures.append("%s: nm cannot read the object: %s" % (where, why))
            continue
        if symbols.get(BARE_METAL_EXPORT) != "T":
            failures.append("%s: `%s` is %s, not defined and external (T)"
                            % (where, BARE_METAL_EXPORT, symbols.get(BARE_METAL_EXPORT, "absent")))
            continue
        counts["run bare-metal objects"] = counts.get("run bare-metal objects", 0) + 1
    where = "run %s (a link)" % rel(probe)
    out = os.path.join(OUT, "bare_metal_link")
    for stale in (out, out + ".ll"):
        if os.path.exists(stale):
            os.remove(stale)
    r = subprocess.run([build.SAWC, "build", "--std-root", "std", "--target", BARE_METAL_TARGET, rel(probe), "-o",
                        out], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    said = (r.stdout + r.stderr).strip()
    if (r.returncode != 2 or "bare-metal" not in said or "`-c`" not in said or os.path.exists(out)
            or os.path.exists(out + ".ll")):
        failures.append("%s: not refused with exit status 2 naming `-c` before writing anything: exit %d: %s"
                        % (where, r.returncode, said[:300]))
    else:
        counts["run bare-metal links refused"] = 1


# What `sawc build --freestanding` writes for `probes/freestanding_object.saw`
# on the bare-metal target: the export defined in a section of its own, the
# panic seam undefined, no C entry or argument accessors, and the file's
# `main` an ordinary internal function (the user's Q7 ruling).
FREESTANDING_PROBE = "freestanding_object.saw"
FREESTANDING_EXPORT = "probe_freestanding_entry"
FREESTANDING_DEFAULT_FEATURES = '"target-features"="-neon,-fp-armv8"'
FREESTANDING_EXPLICIT_FEATURES = "+neon,+fp-armv8"
FREESTANDING_MACH_O_RULE = "driver.freestanding-mach-o"


def elf_sections(path):
    """{name: size} of the ELF64 little-endian object at `path`'s sections."""
    with open(path, "rb") as fh:
        data = fh.read()
    shoff = int.from_bytes(data[0x28:0x30], "little")
    shentsize = int.from_bytes(data[0x3A:0x3C], "little")
    shnum = int.from_bytes(data[0x3C:0x3E], "little")
    shstrndx = int.from_bytes(data[0x3E:0x40], "little")

    def header(k):
        at = shoff + k * shentsize
        return (int.from_bytes(data[at:at + 4], "little"), int.from_bytes(data[at + 24:at + 32], "little"),
                int.from_bytes(data[at + 32:at + 40], "little"))
    _, names_at, _ = header(shstrndx)
    sections = {}
    for k in range(shnum):
        name, _, size = header(k)
        end = data.index(b"\0", names_at + name)
        sections[data[names_at + name:end].decode("utf-8", "replace")] = size
    return sections


def check_freestanding_object(failures, counts):
    """`sawc build --freestanding --target aarch64-unknown-none-elf` at -O0
    and -O2: an ELF64 AArch64 relocatable object, sawc printing nothing,
    with no C `main` and no argument accessors, the export `T` in its own
    `.text.` section and an empty `.text`, `__saw_rt_panic` undefined, and
    the file's `main` local (or inlined away at -O2). Then the attribute
    group's aarch64 default and an explicit list replacing it, and a Mach-O
    triple refused by an `ERROR` record, writing nothing."""
    probe = os.path.join(PROBES, FREESTANDING_PROBE)
    problem = bare_metal_record_problem(rel(probe))
    if problem:
        failures.append(problem)
        return
    for speed in ("-O0", "-O2"):
        where = "run %s %s" % (rel(probe), speed)
        obj = os.path.join(OUT, "freestanding" + speed[1:] + ".o")
        if os.path.exists(obj):
            os.remove(obj)
        r = subprocess.run([build.SAWC, "build", "--freestanding", speed, "--std-root", "std", "--target",
                            BARE_METAL_TARGET, rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode != 0 or said or not os.path.exists(obj):
            failures.append("%s: sawc build --freestanding exits %d: %s" % (where, r.returncode, said[:300]))
            continue
        problem = elf_header_problem(obj)
        if problem:
            failures.append("%s: the object %s" % (where, problem))
            continue
        symbols, why = object_symbols(obj, False)
        if symbols is None:
            failures.append("%s: nm cannot read the object: %s" % (where, why))
            continue
        problems = []
        if symbols.get(FREESTANDING_EXPORT) != "T":
            problems.append("`%s` is %s, not defined and external (T)"
                            % (FREESTANDING_EXPORT, symbols.get(FREESTANDING_EXPORT, "absent")))
        if symbols.get(OBJECT_UNDEFINED) != "U":
            problems.append("`%s` is %s, not undefined (U)"
                            % (OBJECT_UNDEFINED, symbols.get(OBJECT_UNDEFINED, "absent")))
        for name in OBJECT_ABSENT:
            if name in symbols:
                problems.append("`%s` is in a freestanding object (%s)" % (name, symbols[name]))
        mains = {name: kind for name, kind in symbols.items() if "main(" in name}
        for name, kind in mains.items():
            if not kind.islower():
                problems.append("`%s` is external (%s); a freestanding `main` is an ordinary function" % (name, kind))
        if speed == "-O0" and not mains:
            problems.append("no symbol for the file's `main` at -O0, where nothing inlines it")
        sections = elf_sections(obj)
        if ".text." + FREESTANDING_EXPORT not in sections:
            problems.append("no section `.text.%s`: the export is not in a section of its own" % FREESTANDING_EXPORT)
        if sections.get(".text", 0) != 0:
            problems.append("`.text` holds %d bytes; every function belongs in its own `.text.` section"
                            % sections[".text"])
        for problem in problems:
            failures.append("%s: %s" % (where, problem))
        if not problems:
            counts["run freestanding objects"] = counts.get("run freestanding objects", 0) + 1
    for flags, want, unwanted in (([], FREESTANDING_DEFAULT_FEATURES, None),
                                  (["--target-features", FREESTANDING_EXPLICIT_FEATURES],
                                   '"target-features"="%s"' % FREESTANDING_EXPLICIT_FEATURES,
                                   FREESTANDING_DEFAULT_FEATURES)):
        where = "run %s --emit-ll %s" % (rel(probe), " ".join(flags) or "(the default features)")
        r = subprocess.run([build.SAWC, "build", "--freestanding", "-g0", "--emit-ll", "--std-root", "std",
                            "--target", BARE_METAL_TARGET] + flags + [rel(probe)], cwd=REPO, capture_output=True,
                           text=True, timeout=BUILD_TIMEOUT)
        groups = [line for line in r.stdout.split("\n") if line.startswith("attributes #")]
        # A module defining a builtin routine carries the builtins' group
        # beside `#0`: the same attributes and "no-builtins" (SL-948).
        builtins = any(line.startswith("define ") and re.search(r"\)[^(]*#1\b", line)
                       for line in r.stdout.split("\n"))
        twin = [groups[0].replace("attributes #0 =", "attributes #1 =", 1).replace(" }", ' "no-builtins" }')
                ] if groups and builtins else []
        if (r.returncode != 0 or len(groups) < 1 or not groups[0].startswith("attributes #0 =")
                or groups[1:] != twin or want not in groups[0] or (unwanted and unwanted in groups[0])):
            failures.append("%s: exit %d, attribute groups %r, not one holding %s%s, and its \"no-builtins\" "
                            "twin when the module defines a builtin"
                            % (where, r.returncode, groups, want, " alone" if unwanted else ""))
        else:
            counts["run freestanding feature groups"] = counts.get("run freestanding feature groups", 0) + 1
    where = "run %s --target arm64-apple-darwin" % rel(probe)
    out = os.path.join(OUT, "freestanding_mach_o.o")
    for stale in (out, out + ".ll"):
        if os.path.exists(stale):
            os.remove(stale)
    r = subprocess.run([build.SAWC, "build", "--freestanding", "--std-root", "std", "--target", "arm64-apple-darwin",
                        rel(probe), "-o", out], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    records = [line.split("\t") for line in r.stdout.split("\n") if line.startswith("ERROR\t")]
    refused = [fields for fields in records if len(fields) == 4 and fields[1] == FREESTANDING_MACH_O_RULE]
    if (r.returncode != 1 or not refused or "cannot target the Mach-O triple" not in refused[0][3]
            or BARE_METAL_TARGET not in refused[0][3] or os.path.exists(out) or os.path.exists(out + ".ll")):
        failures.append("%s: not refused by a %s record naming %s, with nothing written: exit %d: %s"
                        % (where, FREESTANDING_MACH_O_RULE, BARE_METAL_TARGET, r.returncode,
                           (r.stdout + r.stderr).strip()[:300]))
    else:
        counts["run freestanding Mach-O refusals"] = 1


# The runtime provider probes: the seams `probes/runtime_provider.saw` defines
# itself, the line it prints through them, the libc symbol a freestanding
# build of it leaves to its link, and the seam its twin
# `runtime_provider_missing_seam.saw` leaves out.
PROVIDER_PROBE = "runtime_provider.saw"
PROVIDER_MISSING_PROBE = "runtime_provider_missing_seam.saw"
PROVIDER_SEAMS = ("__saw_rt_alloc", "__saw_rt_dealloc", "__saw_rt_write_line", "__saw_rt_panic",
                  "__saw_rt_last_raw_code")
PROVIDER_LINE = b"provided by the program\n"
PROVIDER_LIBC = "write"
PROVIDER_MISSING_SEAM = "__saw_rt_last_raw_code"
PROVIDER_RULE = "provider.undefined-seam"


def check_runtime_provider(failures, counts):
    """`probes/runtime_provider.saw` built with `--runtime`, and again with
    v0.18.0's `--runtime-provider`, at -O0 and -O2: sawc prints nothing, the
    binary defines each of `PROVIDER_SEAMS` itself and prints its line. Then
    `--freestanding --runtime` for the bare-metal target: an object exporting
    those seams with libc's `write` undefined. A bare-metal `--runtime` build
    with neither `-c` nor `--freestanding` is refused like any link for it,
    and `--runtime-build` is refused with exit status 2, naming `sawc
    runtime`."""
    probe = os.path.join(PROBES, PROVIDER_PROBE)
    mach_o = "-apple-" in build.clang_triple(TARGET or build.host_triple())
    for spelling in ("--runtime", "--runtime-provider"):
        for speed in ("-O0", "-O2"):
            where = "run %s %s %s" % (rel(probe), spelling, speed)
            binary = os.path.join(OUT, "provider" + spelling.replace("-", "_") + speed[1:])
            r = subprocess.run([build.SAWC, "build", spelling, speed, "--std-root", "std"] + target_flags()
                               + [rel(probe), "-o", binary], cwd=REPO, capture_output=True, text=True,
                               timeout=BUILD_TIMEOUT)
            said = (r.stdout + r.stderr).strip()
            if r.returncode != 0 or said:
                failures.append("%s: sawc exits %d: %s" % (where, r.returncode, said[:300]))
                continue
            symbols, why = object_symbols(binary, mach_o)
            if symbols is None:
                failures.append("%s: nm cannot read the binary: %s" % (where, why))
                continue
            missing = [seam for seam in PROVIDER_SEAMS if symbols.get(seam) != "T"]
            if missing:
                failures.append("%s: the binary does not define %s itself" % (where, ", ".join(missing)))
                continue
            code, out, _ = execute(binary)
            if code != 0 or out != PROVIDER_LINE:
                failures.append("%s: the binary exits %s, not 0: %s"
                                % (where, code, output_difference(out, PROVIDER_LINE)))
                continue
            counts["run runtime providers linked"] = counts.get("run runtime providers linked", 0) + 1
    problem = bare_metal_record_problem(rel(probe))
    if problem:
        failures.append(problem)
        return
    where = "run %s --freestanding --runtime" % rel(probe)
    obj = os.path.join(OUT, "provider_freestanding.o")
    r = subprocess.run([build.SAWC, "build", "--freestanding", "--runtime", "--std-root", "std", "--target",
                        BARE_METAL_TARGET, rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT)
    said = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or said or not os.path.exists(obj):
        failures.append("%s: sawc exits %d: %s" % (where, r.returncode, said[:300]))
    else:
        symbols, why = object_symbols(obj, False)
        if symbols is None:
            failures.append("%s: nm cannot read the object: %s" % (where, why))
        elif [seam for seam in PROVIDER_SEAMS if symbols.get(seam) != "T"] or symbols.get(PROVIDER_LIBC) != "U":
            failures.append("%s: the seams are %r and `%s` is %s, not each T and U"
                            % (where, {seam: symbols.get(seam) for seam in PROVIDER_SEAMS}, PROVIDER_LIBC,
                               symbols.get(PROVIDER_LIBC, "absent")))
        else:
            counts["run runtime providers linked"] = counts.get("run runtime providers linked", 0) + 1
    for flags, needle, what in ((["--runtime", "--target", BARE_METAL_TARGET], "`-c`", "a bare-metal link"),
                                (["--runtime-build"], "`sawc runtime`", "--runtime-build")):
        where = "run %s (%s)" % (rel(probe), what)
        out = os.path.join(OUT, "provider_refused")
        for stale in (out, out + ".ll"):
            if os.path.exists(stale):
                os.remove(stale)
        r = subprocess.run([build.SAWC, "build", "--std-root", "std"] + flags + [rel(probe), "-o", out], cwd=REPO,
                           capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode != 2 or needle not in said or os.path.exists(out) or os.path.exists(out + ".ll"):
            failures.append("%s: not refused with exit status 2 naming %s, nothing written: exit %d: %s"
                            % (where, needle, r.returncode, said[:300]))
        else:
            counts["run runtime provider refusals"] = counts.get("run runtime provider refusals", 0) + 1


def check_provider_missing_seam(failures, counts):
    """`probes/runtime_provider_missing_seam.saw`, a hosted provider that
    reaches `__saw_rt_last_raw_code` and defines it nowhere: `--runtime` is
    refused by a `provider.undefined-seam` record naming the seam, exit status
    1, with nothing written; `--runtime -c` writes the object, the seam left
    undefined for its link."""
    probe = os.path.join(PROBES, PROVIDER_MISSING_PROBE)
    where = "run %s --runtime" % rel(probe)
    out = os.path.join(OUT, "provider_missing")
    for stale in (out, out + ".ll", out + ".o"):
        if os.path.exists(stale):
            os.remove(stale)
    r = subprocess.run([build.SAWC, "build", "--runtime", "--std-root", "std"] + target_flags() + [rel(probe), "-o",
                        out], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    records = [line.split("\t") for line in r.stdout.split("\n") if line.startswith("ERROR\t")]
    named = [fields for fields in records if len(fields) == 4 and fields[1] == PROVIDER_RULE
             and ("`%s`" % PROVIDER_MISSING_SEAM) in fields[3]]
    if r.returncode != 1 or len(records) != 1 or not named or os.path.exists(out) or os.path.exists(out + ".ll"):
        failures.append("%s: not refused by one %s record naming %s, nothing written: exit %d: %s"
                        % (where, PROVIDER_RULE, PROVIDER_MISSING_SEAM, r.returncode,
                           (r.stdout + r.stderr).strip()[:300]))
        return
    where = "run %s --runtime -c" % rel(probe)
    r = subprocess.run([build.SAWC, "build", "--runtime", "-c", "--std-root", "std"] + target_flags()
                       + [rel(probe), "-o", out], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    said = (r.stdout + r.stderr).strip()
    mach_o = "-apple-" in build.clang_triple(TARGET or build.host_triple())
    symbols = object_symbols(out + ".o", mach_o)[0] if r.returncode == 0 and os.path.exists(out + ".o") else None
    if r.returncode != 0 or said or symbols is None or symbols.get(PROVIDER_MISSING_SEAM) != "U":
        failures.append("%s: not an object leaving %s undefined: exit %d: %s"
                        % (where, PROVIDER_MISSING_SEAM, r.returncode, said[:300]))
        return
    counts["run runtime provider refusals"] = counts.get("run runtime provider refusals", 0) + 1


# The cooperative-executor provider probes: a cooperative group built against
# `cooperative_executor_seams`, which defines no thread, pthread or offload
# seam, and its pool twin, refused naming the thread seam.
COOPERATIVE_PROBE = "cooperative_group_provider.saw"
POOL_REFUSED_PROBE = "pool_group_provider_refused.saw"
COOPERATIVE_LINE = b"joined 42\n"
COOPERATIVE_ABSENT_PREFIXES = ("__saw_rt_thread_spawn", "__saw_rt_thread_join", "__saw_rt_pthread_",
                               "__saw_rt_offload_")
POOL_REFUSED_SEAM = "__saw_rt_thread_spawn"


def check_cooperative_provider(failures, counts):
    """`probes/cooperative_group_provider.saw`, built with `--runtime
    --no-hidden-alloc` at -O0 and -O2: sawc prints nothing, which is the
    provider check finding every seam the program reaches defined, the
    binary names none of `COOPERATIVE_ABSENT_PREFIXES`, and it prints its
    line."""
    probe = os.path.join(PROBES, COOPERATIVE_PROBE)
    mach_o = "-apple-" in build.clang_triple(TARGET or build.host_triple())
    for speed in ("-O0", "-O2"):
        where = "run %s --runtime %s" % (rel(probe), speed)
        binary = os.path.join(OUT, "cooperative_provider" + speed[1:])
        r = subprocess.run([build.SAWC, "build", "--runtime", "--no-hidden-alloc", speed, "--std-root", "std"]
                           + target_flags() + [rel(probe), "-o", binary], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode != 0 or said:
            failures.append("%s: sawc exits %d: %s" % (where, r.returncode, said[:300]))
            continue
        symbols, why = object_symbols(binary, mach_o)
        if symbols is None:
            failures.append("%s: nm cannot read the binary: %s" % (where, why))
            continue
        named = sorted(s for s in symbols if s.startswith(COOPERATIVE_ABSENT_PREFIXES))
        if named:
            failures.append("%s: the binary names %s" % (where, ", ".join(named)))
            continue
        code, out, _ = execute(binary)
        if code != 0 or out != COOPERATIVE_LINE:
            failures.append("%s: the binary exits %s, not 0: %s"
                            % (where, code, output_difference(out, COOPERATIVE_LINE)))
            continue
        counts["run runtime providers linked"] = counts.get("run runtime providers linked", 0) + 1


def check_pool_provider_refused(failures, counts):
    """`probes/pool_group_provider_refused.saw`, a pool against the same
    provider: `--runtime --no-hidden-alloc` is refused with exit status 1,
    nothing written, every record a `provider.undefined-seam` one and one of
    them naming `POOL_REFUSED_SEAM`."""
    probe = os.path.join(PROBES, POOL_REFUSED_PROBE)
    where = "run %s --runtime" % rel(probe)
    out = os.path.join(OUT, "pool_provider_refused")
    for stale in (out, out + ".ll"):
        if os.path.exists(stale):
            os.remove(stale)
    r = subprocess.run([build.SAWC, "build", "--runtime", "--no-hidden-alloc", "--std-root", "std"] + target_flags()
                       + [rel(probe), "-o", out], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    records = [line.split("\t") for line in r.stdout.split("\n") if line.startswith("ERROR\t")]
    others = [fields for fields in records if len(fields) != 4 or fields[1] != PROVIDER_RULE]
    named = [fields for fields in records if len(fields) == 4 and ("`%s`" % POOL_REFUSED_SEAM) in fields[3]]
    if (r.returncode != 1 or not records or others or not named or os.path.exists(out)
            or os.path.exists(out + ".ll")):
        failures.append("%s: not refused by %s records, one naming %s, nothing written: exit %d: %s"
                        % (where, PROVIDER_RULE, POOL_REFUSED_SEAM, r.returncode,
                           (r.stdout + r.stderr).strip()[:300]))
        return
    counts["run runtime provider refusals"] = counts.get("run runtime provider refusals", 0) + 1


# A clang path `SAWC_CLANG` can name that no file is at.
MISSING_CLANG = "/nonexistent/saw-lane/clang"


def check_clang_choice(failures, counts):
    """`build.py`'s clang choice for the bare-metal target (`pick_clang`, which
    `choose_clang` caches): with no override it picks a clang that compiles IR
    for that triple, an override naming that clang is taken as named, and an
    override naming no executable is refused by name, with no fallback to the
    candidates. The stage build has written the target's record before any
    of this runs; `configure_target` then rewrites it: its `target` and
    `clang` lines, the `objcopy` line `choose_objcopy` finds, and no object,
    since it has no runtime. The candidates are
    each `clang-NN` on PATH, the newest first, then `clang`, then Homebrew's."""
    where = "run clang choice for %s" % BARE_METAL_TARGET
    problem = bare_metal_record_problem("clang choice for %s" % BARE_METAL_TARGET)
    if problem:
        failures.append(problem)
        return
    chosen, why = build.pick_clang(BARE_METAL_TARGET, None)
    if chosen is None or not build.clang_capable(chosen, BARE_METAL_TARGET):
        failures.append("%s: no capable clang is picked: %s" % (where, why))
        return
    named, why = build.pick_clang(BARE_METAL_TARGET, chosen)
    if named != os.path.abspath(chosen):
        failures.append("%s: SAWC_CLANG naming %s picks %s: %s" % (where, chosen, named, why))
    missing, why = build.pick_clang(BARE_METAL_TARGET, MISSING_CLANG)
    if missing is not None or ("SAWC_CLANG names %s" % MISSING_CLANG) not in why:
        failures.append("%s: SAWC_CLANG naming no executable picks %s, not a refusal naming it: %s"
                        % (where, missing, why))
    why = build.configure_target(BARE_METAL_TARGET)
    record = build.runtime_manifest(BARE_METAL_TARGET)
    lines = []
    if not why and os.path.exists(record):
        with open(record) as fh:
            lines = fh.read().splitlines()
    clang_lines = [line for line in lines if line.startswith("clang ")]
    if why or lines[:1] != ["target %s" % BARE_METAL_TARGET] or len(clang_lines) != 1 or any(
            line.startswith("object ") for line in lines):
        failures.append("%s: the record %s is %r, not its target, one clang and no object: %s"
                        % (where, rel(record), lines, why))
    objcopy = build.choose_objcopy(clang_lines[0][len("clang "):]) if clang_lines else None
    objcopy_lines = [line for line in lines if line.startswith("objcopy ")]
    if objcopy_lines != (["objcopy %s" % objcopy] if objcopy else []) or (objcopy and not os.path.exists(objcopy)):
        failures.append("%s: the record's llvm-objcopy lines are %r, not the one `choose_objcopy` finds (%s)"
                        % (where, objcopy_lines, objcopy))
    candidates = build.clang_candidates(BARE_METAL_TARGET)
    versioned = [re.match(r"^clang-(\d+)$", c) for c in candidates[:-2]]
    versions = [int(m.group(1)) for m in versioned if m]
    if (candidates[-2:] != ["clang", build.homebrew_clang()] or not all(versioned)
            or versions != sorted(versions, reverse=True)):
        failures.append("%s: the candidates are %r, not each clang-NN on PATH newest first, then clang, then %s"
                        % (where, candidates, build.homebrew_clang()))
    xtensa = build.clang_candidates(XTENSA_TARGET)
    if xtensa != build.espressif_clangs() + candidates:
        failures.append("%s: the candidates for %s are %r, not Espressif's clangs first, then the usual ones"
                        % (where, XTENSA_TARGET, xtensa))
    counts["run clang choices checked"] = 4


def tool_lines(out):
    """{name: path} of the `NAME PATH` lines `sawc tools` printed."""
    found = {}
    for line in out.splitlines():
        name, _, path = line.partition(" ")
        found[name] = path
    return found


def check_sawc_tools(failures, counts):
    """`sawc tools` prints the tools the records beside the binary name: for the
    host and for the bare-metal target, a `clang` line naming a file that exists, an
    `ld.lld` line only when that file sits beside the clang, and the record's
    `objcopy`. A copy of sawc beside the records without the Xtensa one is refused
    for that target with the text `sawc build` prints, and an unknown triple
    is refused as elsewhere."""
    where = "run sawc tools"
    problem = bare_metal_record_problem("sawc tools for %s" % BARE_METAL_TARGET)
    if problem:
        failures.append(problem)
        return
    for flags, label in (([], "the host"), (["--target", BARE_METAL_TARGET], BARE_METAL_TARGET)):
        r = subprocess.run([build.SAWC, "tools"] + flags, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        found = tool_lines(r.stdout)
        clang = found.get("clang", "")
        beside = os.path.join(os.path.dirname(clang), "ld.lld")
        if (r.returncode != 0 or r.stderr or not os.path.isfile(clang)
                or ("ld.lld" in found) != os.path.isfile(beside) or found.get("ld.lld", beside) != beside
                or not set(found) <= {"clang", "ld.lld", "objcopy"}
                or ("objcopy" in found and not os.path.isfile(found["objcopy"]))):
            failures.append("%s for %s exits %d with %r, not an existing clang, an ld.lld only beside it, and the "
                            "record's objcopy" % (where, label, r.returncode, r.stdout + r.stderr))
    unknown = subprocess.run([build.SAWC, "tools", "--target", "sawc-no-such-target"], capture_output=True, text=True,
                             timeout=BUILD_TIMEOUT)
    if unknown.returncode != 2 or unknown.stdout.strip() != "sawc: unknown target sawc-no-such-target":
        failures.append("%s for an unknown triple exits %d with %r" % (where, unknown.returncode, unknown.stdout))
    if under_twin():
        left_to_runpy(counts)
        counts["run sawc tools checks"] = 3
        return
    work = os.path.join(OUT, "sawc-tools")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    copied = os.path.join(work, "sawc")
    shutil.copy(build.SAWC, copied)
    missing = XTENSA_TARGET
    for path in glob.glob(os.path.join(os.path.dirname(os.path.realpath(build.SAWC)), "sawc-runtime*.txt")):
        if not os.path.basename(path).endswith("-%s.txt" % missing):
            shutil.copy(path, work)
    probe = os.path.join(PROBES, FREESTANDING_PROBE)
    refused = subprocess.run([copied, "tools", "--target", missing], capture_output=True, text=True,
                             timeout=BUILD_TIMEOUT)
    built = subprocess.run([copied, "build", "--freestanding", "--std-root", "std", "--target", missing, rel(probe),
                            "-o", os.path.join(work, "refused.o")], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
    said = refused.stdout.strip()
    if (refused.returncode != 1 or "has no clang configured" not in said
            or said.replace("sawc tools:", "sawc build:", 1) != built.stdout.strip()):
        failures.append("%s --target %s with no record exits %d with %r, not the text `sawc build` prints: %r"
                        % (where, missing, refused.returncode, said[:200], built.stdout.strip()[:200]))
    counts["run sawc tools checks"] = 4


# The Xtensa target is compiled by Espressif's clang alone, so a machine
# without one has no record and the build is refused, which the lane counts as
# a visible skip (SL-1067).
XTENSA_PROBE = "xtensa_object.saw"
XTENSA_TARGET = "xtensa-esp-unknown-elf"
XTENSA_EXPORT = "probe_xtensa_answer"
ELF_XTENSA = 94
XTENSA_GROUP = '"target-cpu"="esp32s3" "target-features"="-windowed,-fp,-loop,-mac16,-bool"'
XTENSA_SKIPPED = "run xtensa object skipped: no Espressif clang"


def check_xtensa_object(failures, counts):
    """`sawc build --freestanding --target xtensa-esp-unknown-elf` when the
    stage build recorded a clang for it: an ELF32 Xtensa relocatable object
    (`e_machine` 94) defining the export, and an `.ll` with the triple and the
    one attribute group naming `esp32s3` and the default features. With no
    record the build is refused with the "has no clang configured" text, and
    the lane says it skipped the rest."""
    probe = os.path.join(PROBES, XTENSA_PROBE)
    where = "run %s" % rel(probe)
    if not os.path.exists(build.runtime_manifest(XTENSA_TARGET)):
        obj = os.path.join(OUT, "xtensa_refused.o")
        r = subprocess.run([build.SAWC, "build", "--freestanding", "--std-root", "std", "--target", XTENSA_TARGET,
                            rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = (r.stdout + r.stderr).strip()
        if r.returncode == 0 or "has no clang configured" not in said or os.path.exists(obj):
            failures.append("%s: with no record for %s the build exits %d: %s"
                            % (where, XTENSA_TARGET, r.returncode, said[:300]))
        counts[XTENSA_SKIPPED] = 1
        return
    obj = os.path.join(OUT, "xtensa.o")
    if os.path.exists(obj):
        os.remove(obj)
    r = subprocess.run([build.SAWC, "build", "--freestanding", "--std-root", "std", "--target", XTENSA_TARGET,
                        rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    said = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or said or not os.path.exists(obj):
        failures.append("%s: sawc build --freestanding --target %s exits %d: %s"
                        % (where, XTENSA_TARGET, r.returncode, said[:300]))
        return
    with open(obj, "rb") as fh:
        head = fh.read(20)
    machine = int.from_bytes(head[18:20], "little")
    if head[:4] != b"\x7fELF" or head[4] != 1 or head[5] != 1 or machine != ELF_XTENSA:
        failures.append("%s: the object is not a little-endian ELF32 Xtensa file (class %d, machine %d)"
                        % (where, head[4] if len(head) > 4 else -1, machine))
        return
    symbols, why = object_symbols(obj, False)
    if symbols is None or symbols.get(XTENSA_EXPORT) != "T":
        failures.append("%s: `%s` is %s, not defined and external (T): %s"
                        % (where, XTENSA_EXPORT, (symbols or {}).get(XTENSA_EXPORT, "absent"), why))
        return
    r = subprocess.run([build.SAWC, "build", "--freestanding", "-g0", "--emit-ll", "--std-root", "std", "--target",
                        XTENSA_TARGET, rel(probe)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    lines = r.stdout.split("\n")
    groups = [line for line in lines if line.startswith("attributes #")]
    if (r.returncode != 0 or ('target triple = "%s"' % XTENSA_TARGET) not in lines or not groups
            or XTENSA_GROUP not in groups[0]):
        failures.append("%s --emit-ll: exit %d, attribute groups %r, not one holding %s"
                        % (where, r.returncode, groups, XTENSA_GROUP))
        return
    counts["run xtensa objects"] = 1


# The attribute group `probes/attribute_group_levels.saw`'s `.ll` ends with,
# for each set of flags: the frame pointer policy always, then the feature
# string, then the size level's attributes.
ATTRIBUTE_PROBE = "attribute_group_levels.saw"
ATTRIBUTE_GROUPS = (
    ([], 'attributes #0 = { "frame-pointer"="non-leaf" }'),
    (["-O2"], 'attributes #0 = { "frame-pointer"="non-leaf" }'),
    (["-Os"], 'attributes #0 = { "frame-pointer"="non-leaf" optsize }'),
    (["-Oz"], 'attributes #0 = { "frame-pointer"="non-leaf" optsize minsize }'),
    (["--target-features", "+foo,-bar"],
     'attributes #0 = { "frame-pointer"="non-leaf" "target-features"="+foo,-bar" }'),
    (["-Oz", "--target-features", "+foo,-bar"],
     'attributes #0 = { "frame-pointer"="non-leaf" "target-features"="+foo,-bar" optsize minsize }'),
)
# A feature string the IR cannot carry as written, refused as a usage error.
ATTRIBUTE_REFUSED = '+a"b'
# A feature string turning on `forced-atomics`, which has LLVM call `__sync_*`
# routines no environment supplies: refused as a usage error, and a later
# `-forced-atomics` turns it off again (SL-948).
FORCED_ATOMICS_REFUSED = "+m,+forced-atomics,+c"
FORCED_ATOMICS_OFF = "+m,+forced-atomics,-forced-atomics"
# A feature name no target's clang knows, and one known only to the other
# host architecture: each refused as a usage error by a build that runs
# clang, naming it; the host's own name builds (SL-995).
FEATURE_UNKNOWN = "+sawc-not-a-feature"
FEATURE_OWN = {"aarch64": "+neon", "arm64": "+neon", "x86_64": "+sse2"}
FEATURE_FOREIGN = {"aarch64": "+sse2", "arm64": "+sse2", "x86_64": "+neon"}


def check_attribute_groups(failures, counts):
    """`probes/attribute_group_levels.saw`'s `.ll` for the pinned target, at
    each `ATTRIBUTE_GROUPS` row: its one `attributes #0` line is the row's,
    and every define names a group carrying the frame pointer. A feature
    string holding a quote, or turning `forced-atomics` on, is refused with
    exit status 2."""
    probe = os.path.join(PROBES, ATTRIBUTE_PROBE)
    for flags, want in ATTRIBUTE_GROUPS:
        where = "run %s %s" % (rel(probe), " ".join(flags) or "(no flags)")
        r = subprocess.run([build.SAWC, "build", "-g0", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std"]
                           + flags + [rel(probe)], cwd=REPO, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        if r.returncode != 0:
            failures.append("%s: sawc wrote no .ll: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
            continue
        groups = [line for line in r.stdout.split("\n") if line.startswith("attributes #")]
        if groups != [want]:
            failures.append("%s: the attribute groups are %r, not [%r]" % (where, groups, want))
            continue
        problems = define_problems(where[len("run "):], r.stdout)
        failures.extend(problems)
        if not problems:
            counts["run attribute groups pinned"] = counts.get("run attribute groups pinned", 0) + 1
    where = "run %s --target-features %s" % (rel(probe), ATTRIBUTE_REFUSED)
    r = subprocess.run([build.SAWC, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                        "--target-features", ATTRIBUTE_REFUSED, rel(probe)], cwd=REPO, capture_output=True,
                       text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 2 or "attributes #" in r.stdout:
        failures.append("%s: exits %d, not 2 with nothing written: %s"
                        % (where, r.returncode, (r.stdout + r.stderr).strip()[:300]))
    else:
        counts["run attribute groups pinned"] = counts.get("run attribute groups pinned", 0) + 1
    for features, refused in ((FORCED_ATOMICS_REFUSED, True), (FORCED_ATOMICS_OFF, False)):
        where = "run %s --target-features %s" % (rel(probe), features)
        r = subprocess.run([build.SAWC, "build", "--emit-ll", "--target", PINNED_TARGET, "--std-root", "std",
                            "--target-features", features, rel(probe)], cwd=REPO, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        said = r.stdout + r.stderr
        if refused and (r.returncode != 2 or "attributes #" in r.stdout or "`forced-atomics`" not in said):
            failures.append("%s: exits %d, not 2 naming `forced-atomics` with nothing written: %s"
                            % (where, r.returncode, said.strip()[:300]))
        elif not refused and r.returncode != 0:
            failures.append("%s: exits %d, not 0: the last mention turns it off: %s"
                            % (where, r.returncode, said.strip()[:300]))
        else:
            counts["run attribute groups pinned"] = counts.get("run attribute groups pinned", 0) + 1
    triple = TARGET or build.host_triple()
    arch = triple.split("-")[0]
    obj = os.path.join(OUT, "attribute_group_levels_features.o")
    for features, refused in ((FEATURE_UNKNOWN, True), (FEATURE_FOREIGN[arch], True), (FEATURE_OWN[arch], False)):
        where = "run %s -c --target-features %s" % (rel(probe), features)
        if os.path.exists(obj):
            os.remove(obj)
        r = subprocess.run([build.SAWC, "build", "-c", "-g0", "--std-root", "std"] + target_flags()
                           + ["--target-features", features, rel(probe), "-o", obj], cwd=REPO,
                           capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        said = r.stdout + r.stderr
        if refused and (r.returncode != 2 or os.path.exists(obj) or ("`%s`" % features) not in said):
            failures.append("%s: exits %d, not 2 naming `%s` with no object: %s"
                            % (where, r.returncode, features, said.strip()[:300]))
        elif not refused and (r.returncode != 0 or not os.path.exists(obj)):
            failures.append("%s: exits %d, not 0 with an object: %s" % (where, r.returncode, said.strip()[:300]))
        else:
            counts["run attribute groups pinned"] = counts.get("run attribute groups pinned", 0) + 1


VOLATILE_PROBE = "memory_volatile_survives_optimization.saw"


def check_volatile_accesses(failures, counts):
    """`probes/memory_volatile_survives_optimization.saw`'s `.ll` for the
    host, as sawc writes it and after the host clang's -O2: each holds exactly
    four volatile loads and four volatile stores, two of each through a
    `Device` view and two through a field it projects, and the `Normal`
    view's accesses none (SL-914). The count is over the module, so
    whatever the optimizer inlines, a merged `Device` access or a volatile
    `Normal` one moves it."""
    probe = os.path.join(PROBES, VOLATILE_PROBE)
    triple = TARGET or build.host_triple()
    where = "run %s" % rel(probe)
    r = subprocess.run([build.SAWC, "build", "-g0", "--emit-ll", "--std-root", "std", rel(probe)], cwd=REPO,
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if r.returncode != 0:
        failures.append("%s: sawc wrote no .ll: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
        return
    clang = manifest_clang(triple)
    if clang is None:
        failures.append("%s: %s names no clang" % (where, build.runtime_manifest(triple)))
        return
    with tempfile.TemporaryDirectory() as tmp:
        written = os.path.join(tmp, "probe.ll")
        with open(written, "w") as fh:
            fh.write(r.stdout)
        o = subprocess.run([clang, "-target", build.clang_triple(triple), "-O2", "-S", "-emit-llvm", "-x", "ir",
                            written, "-o", "-"], capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    if o.returncode != 0:
        failures.append("%s: clang -O2 refused the .ll: %s" % (where, o.stderr.strip()[:300]))
        return
    for stage, text in (("as written", r.stdout), ("after -O2", o.stdout)):
        loads = len(re.findall(r"= load volatile i32, ptr ", text))
        stores = len(re.findall(r"\bstore volatile i32 ", text))
        if (loads, stores) != (4, 4):
            failures.append("%s: %s, the .ll holds %d volatile loads and %d volatile stores, not 4 and 4"
                            % (where, stage, loads, stores))
            return
    counts["run volatile accesses pinned"] = counts.get("run volatile accesses pinned", 0) + 1


# The custom probes, each checked by its own function. `executable_path.saw`
# is run through a renamed link on `PATH` from another directory, and what it
# must print is its binary's real path, which no header line can state. The
# two `print` probes' output is interleaved by the operating system, and the
# three dump-churn probes' dumps catch whatever the scheduler has left live.
# The leak probe's lost block is sized by the allocator. The two object probes
# are read with `nm` and the ELF header, and the attribute probe's `.ll` is
# written at several flag sets, none of which is a build and a run. The
# volatile probe's `.ll` is read before and after clang's optimizer. The
# provider probes are built with `--runtime`, which no header states, and the
# cooperative one's binary is read with `nm` for the seams it must not name.
CUSTOM_PROBES = {
    OBJECT_PROBE: check_object_output,
    ATTRIBUTE_PROBE: check_attribute_groups,
    VOLATILE_PROBE: check_volatile_accesses,
    BARE_METAL_PROBE: check_bare_metal_object,
    XTENSA_PROBE: check_xtensa_object,
    FREESTANDING_PROBE: check_freestanding_object,
    PROVIDER_PROBE: check_runtime_provider,
    PROVIDER_MISSING_PROBE: check_provider_missing_seam,
    COOPERATIVE_PROBE: check_cooperative_provider,
    POOL_REFUSED_PROBE: check_pool_provider_refused,
    "executable_path.saw": check_executable_path,
    "leaks_check_sees_a_leak.saw": check_leak_detection,
    "print_lines_stay_whole.saw": check_print_lines,
    "print_beside_a_panic.saw": check_print_beside_a_panic,
    "dump_tasks_beside_recycling_pool_workers.saw": check_dump_beside_churn(
        "dump_tasks_beside_recycling_pool_workers.saw"),
    "dump_tasks_beside_growing_groups.saw": check_dump_beside_churn("dump_tasks_beside_growing_groups.saw"),
    "dump_tasks_beside_pool_teardowns.saw": check_dump_beside_churn("dump_tasks_beside_pool_teardowns.saw"),
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
        failures.extend(orphan_helpers())
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


TWIN_COUNT = "run checks left to run.py's own run under the twin"


def under_twin():
    """Whether `build.SAWC` is a twin (`fixpoint/twin.py`, which the fixpoint
    lane and `parallel_order.py` put where a lane expects sawc): a wrapper
    that runs Stage 1 and Stage 2 on every call, both on the one cache
    directory, and is no binary with files of its own beside it. A check of
    the cache's bookkeeping or of such files has no verdict there; the run.py
    step run outside the twin judges it."""
    return "FIXPOINT_REF" in os.environ


def left_to_runpy(counts):
    counts[TWIN_COUNT] = counts.get(TWIN_COUNT, 0) + 1


# What `run` leaves out under the twin: (the check, whether all of it, why).
# A check left out in part tests `under_twin` itself, at that part.
NOT_UNDER_TWIN = (
    (check_split_object, False, "its last part copies the binary beside an edited runtime record, and the twin is "
                                "a wrapper with no record beside it"),
    (check_sawc_tools, False, "its refusal part copies the binary beside the records less one, for the same "
                              "reason"),
    (check_object_cache, True, "it counts one compiler's cache entries, and the twin writes two compilers' to one "
                               "cache"),
    (check_front_cache, True, "it counts one compiler's cache images and expects the other stage to miss them"),
    (check_front_layers, True, "it counts one compiler's cache parts and expects the other stage to miss them"),
    (check_link_arguments, True, "it copies the binary beside made-up runtime records, and the twin is a wrapper "
                                 "with no record beside it"),
)


def run_check(check, failures, counts):
    """`check`, unless the twin is in use and the table above leaves all of it
    out."""
    if under_twin() and any(check is left_out and whole for left_out, whole, _ in NOT_UNDER_TWIN):
        left_to_runpy(counts)
        return
    check(failures, counts)


def check_twin_table(failures, counts):
    """Under the twin, what was left out is what the table names: one count a
    row, so a check that leaves itself out without a row fails here."""
    if under_twin() and counts.get(TWIN_COUNT, 0) != len(NOT_UNDER_TWIN):
        failures.append("run lane: %d checks were left to run.py's own run under the twin, and NOT_UNDER_TWIN "
                        "names %d" % (counts.get(TWIN_COUNT, 0), len(NOT_UNDER_TWIN)))


def run(names=None, write=False):
    os.makedirs(OUT, exist_ok=True)
    # Every build the lane makes (its own pins, and every program, split under
    # `SAWC_CODEGEN_UNITS=module`) shares a cache of this run's own, never the
    # user's: std's front-end image and the split units' objects.
    shutil.rmtree(OBJECT_CACHE, ignore_errors=True)
    os.environ["SAWC_CACHE_DIR"] = OBJECT_CACHE
    os.environ["SAW_LANE_CACHE_DIR"] = OBJECT_CACHE
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
        check_debug_shape(failures, counts, write)
        check_symbolization(failures, counts)
        check_foreign_targets(failures, counts)
        check_clang_choice(failures, counts)
        check_sawc_tools(failures, counts)
        word32_ir.check(failures, counts)
        float_lowering.check(failures, counts)
        builtin_lowering.check(failures, counts)
        check_runtime(failures, counts)
        check_default_std_root(failures, counts)
        check_default_output(failures, counts)
        check_time_stages(failures, counts)
        check_codegen_units(failures, counts)
        check_unit_stability(failures, counts)
        check_split_object(failures, counts)
        check_placed_symbols(failures, counts)
        check_exported_placed_link(failures, counts)
        check_sha256(failures, counts)
        run_check(check_object_cache, failures, counts)
        run_check(check_front_cache, failures, counts)
        check_front_cache_differential(failures, counts)
        run_check(check_front_layers, failures, counts)
        check_front_layer_edits(failures, counts)
        check_front_scan_text(failures, counts)
        check_front_shared_writers(failures, counts)
        check_long_accessor(failures, counts)
        check_deep_match(failures, counts)
        run_check(check_link_arguments, failures, counts)
        check_twin_table(failures, counts)
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
    """The timing report: each kernel of `bench/` built by sawc at -O2 and
    by Stage 0, both run, their best times printed beside the ratio. Only a
    build that fails, or two outputs that differ, fails the report; a time
    never does, since it is only as good as the machine is quiet. A time is
    no record, so Stage 0 is run here, through the v0 compiler."""
    os.makedirs(OUT, exist_ok=True)
    failures = []
    print("%-12s %10s %10s %7s" % ("kernel", "Stage 0", "sawc -O2", "ratio"))
    for src in sorted(glob.glob(os.path.join(HERE, "bench", "*.saw"))):
        name = os.path.splitext(os.path.basename(src))[0]
        ok_new, new, new_log = build_new(src, "-O2")
        old = os.path.join(OUT, name + ".old")
        code, old_log = oracle.stage0(src, old, [], timeout=BUILD_TIMEOUT)
        ok_old = code == 0
        if not ok_new or not ok_old:
            failures.append("bench %s: %s does not build it: %s"
                            % (name, "sawc" if not ok_new else "Stage 0", (new_log if not ok_new else old_log)[:300]))
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

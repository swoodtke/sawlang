#!/usr/bin/env python3
"""The builtin check: a freestanding object defines std's builtin routines
weakly, and no builtin routine reaches itself (SL-948).

    python compiler/tests/run/builtin_lowering.py     # the check alone

`run_lane.run()` calls `check()`. Each program of `lowering/` it names is
built by `sawc build --freestanding` for riscv32 (`+m,+a,+c`) and aarch64, at
-O0, -O1, -O2, -Os and -Oz, and each object's relocations are read with
`llvm-objdump`:

- `builtin_uses.saw`'s object defines std's routines, each `W` (`STD_ROUTINES`:
  the memory routines on both arches, the 64-bit integer helpers on riscv32),
  and every function a routine reaches through relocations carries
  `"no-builtins"` in the object's `.ll`, is a machine-outlined fragment (whose
  relocations are followed), or is one of std's `__saw_fail_*` panic helpers,
  which a correct routine never calls; no routine reaches its own symbol;
- `builtin_memset_helper.saw` and `builtin_memmove_shift.saw`, a program's own
  `memset` and `memmove`, reach themselves at no level and are `W`, the
  object's one definition of the name, with std's other memory routines
  beside them: std's routine of the name yields (`TcProgram.export_unique`);
- `builtin_cross_module.saw`'s `memset` fills through another module's loop,
  which "no-builtins" does not reach: the routine reaches itself at exactly the
  levels `CROSS_MODULE_SELF_CALLS` pins;
- `builtin_memset_helper.saw`'s riscv32 -O2 module with its helper's
  "no-builtins" taken away is reported as reaching itself, so the check sees
  what it is for;
- `builtin_uses.saw` built for the host defines none of the routines, and
  `shift_checks.saw`'s -O0 module checks the variable shift's count and not the
  constant one's (`ll_constant_shift_count`).

A target whose clang record is absent because no clang here compiles IR for it
is skipped, and says why; a capable clang with no record fails.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

LOWERING = os.path.join(HERE, "lowering")
OUT = os.path.join(REPO, ".build", "builtin-lowering")
TIMEOUT = 600
LEVELS = ("-O0", "-O1", "-O2", "-Os", "-Oz")
# std's routines: the memory and integer names of sawc's builtin name set
# (`ll_builtin_symbol`, compiler/llvm/src/attributes.saw), which also holds the
# soft-float routines.
MEMORY = ("memcpy", "memset", "memmove")
INTEGER = ("__divdi3", "__moddi3", "__udivdi3", "__umoddi3", "__ashldi3", "__ashrdi3", "__lshrdi3")
# (triple, `--target-features` or None for the freestanding default, the
# routines std defines there).
ARCHES = (
    ("riscv32-unknown-none-elf", "+m,+a,+c", MEMORY + INTEGER),
    ("aarch64-unknown-none-elf", None, MEMORY),
)
STD_ROUTINES = {triple: routines for triple, _, routines in ARCHES}
# The levels at which `builtin_cross_module.saw`'s `memset` reaches itself:
# LLVM turns the imported loop into a `memset` call before inlining it, and
# neither arch's -O0 or -Oz inlines it.
CROSS_MODULE_SELF_CALLS = {
    "riscv32-unknown-none-elf": ("-O1", "-O2", "-Os"),
    "aarch64-unknown-none-elf": ("-O1", "-O2", "-Os"),
}

_FUNCTION = re.compile(r"^[0-9a-f]+ <(.*)>:$")
_RELOCATION = re.compile(r"\sR_\S+\s+(.+)$")
_OFFSET = re.compile(r"[+-]0x[0-9a-f]+$")
_DEFINE = re.compile(r'^define [^@]*@(?:"([^"]+)"|([\w.$]+))\(')
_GROUP = re.compile(r"^attributes #(\d+) = \{(.*)\}$")


def rel(path):
    return os.path.relpath(path, REPO)


def record_clang(triple):
    """(clang, skip, problem): the clang `triple`'s record beside the stages
    names, which `sawc build` compiles its objects with; else why the triple
    is skipped, when no clang compiles IR for it; else the problem, when one
    does and the stage build wrote no record naming it."""
    record = build.runtime_manifest(triple)
    if os.path.exists(record):
        with open(record) as fh:
            for line in fh:
                if line.startswith("clang "):
                    return line[len("clang "):].strip(), "", ""
    clang, why = build.pick_clang(triple, os.environ.get("SAWC_CLANG"))
    if clang is None:
        return None, why, ""
    return None, "", "%s compiles IR for %s, and no clang record %s is beside the stages" % (clang, triple, rel(record))


def llvm_tool(clang, name):
    """The LLVM tool `name` that reads `clang`'s objects: the one beside it,
    with its version suffix when it has one (`clang-19`, `llvm-objdump-19`),
    else one on PATH, else Homebrew's."""
    base = os.path.basename(clang)
    suffix = base[len("clang"):] if base.startswith("clang-") else ""
    for candidate in (os.path.join(os.path.dirname(clang), name + suffix),
                      os.path.join(os.path.dirname(clang), name)):
        if os.path.exists(candidate):
            return candidate
    found = shutil.which(name + suffix) or shutil.which(name)
    if found:
        return found
    beside = os.path.join(os.path.dirname(build.homebrew_clang()), name)
    return beside if os.path.exists(beside) else None


def sawc_object(program, triple, features, level, stem):
    """(the object, its `.ll`'s text, or None and why sawc wrote none)."""
    os.makedirs(OUT, exist_ok=True)
    obj = os.path.join(OUT, stem + ".o")
    cmd = [build.SAWC, "build", "--freestanding", "-g0", "--std-root", "std", "--target", triple, level]
    if features is not None:
        cmd += ["--target-features", features]
    r = subprocess.run(cmd + [rel(os.path.join(LOWERING, program)), "-o", obj], cwd=REPO, capture_output=True,
                       text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return None, None, "sawc writes no object: %s" % (r.stdout + r.stderr).strip()[:300]
    with open(obj + ".ll") as fh:
        return obj, fh.read(), None


def text_symbols(nm, obj):
    """{symbol: its nm letter} for each function the object defines."""
    out = subprocess.run([nm, obj], capture_output=True, text=True, timeout=TIMEOUT).stdout
    found = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] in "tTwW":
            found[parts[2]] = parts[1]
    return found


def call_graph(objdump, obj, functions):
    """{function: the functions its relocations name}. A relocation through a
    function's section (`.text.NAME`, aarch64's spelling of a local call) names
    that function; one naming data names nothing here."""
    dis = subprocess.run([objdump, "-dr", "--no-show-raw-insn", obj], capture_output=True, text=True,
                         timeout=TIMEOUT).stdout
    graph = {}
    current = None
    for line in dis.splitlines():
        found = _FUNCTION.match(line)
        if found:
            current = found.group(1)
            graph.setdefault(current, set())
            continue
        found = _RELOCATION.search(line)
        if not found or current is None:
            continue
        target = _OFFSET.sub("", found.group(1).strip())
        if target.startswith(".text."):
            target = target[len(".text."):]
        if target in functions:
            graph[current].add(target)
    return graph


def no_builtins(ll):
    """The functions the module's `.ll` defines with `"no-builtins"`."""
    groups = set()
    for line in ll.splitlines():
        found = _GROUP.match(line)
        if found and '"no-builtins"' in found.group(2):
            groups.add(found.group(1))
    marked = set()
    for line in ll.splitlines():
        found = _DEFINE.match(line)
        if not found:
            continue
        tail = line[line.rindex(")") + 1:]
        if '"no-builtins"' in tail or any(g in groups for g in re.findall(r"#(\d+)", tail)):
            marked.add(found.group(1) or found.group(2))
    return marked


def reach_problems(routine, graph, marked):
    """Why `routine` may reach a builtin call of itself: a function it reaches
    that carries no "no-builtins" and is neither machine-outlined nor a panic
    helper, or a path back to `routine`; empty when there is neither."""
    problems = []
    seen = {routine}
    pending = [(routine, [routine])]
    while pending:
        name, path = pending.pop()
        for callee in sorted(graph.get(name, ())):
            if callee == routine:
                problems.append("reaches itself: %s" % " -> ".join(path + [callee]))
                continue
            if callee in seen or callee.startswith("__saw_fail"):
                continue
            seen.add(callee)
            if not callee.startswith("OUTLINED_FUNCTION_") and callee not in marked:
                problems.append("reaches %s, which carries no \"no-builtins\": %s"
                                % (callee, " -> ".join(path + [callee])))
                continue
            pending.append((callee, path + [callee]))
    return problems


def read(tools, obj, ll):
    objdump, nm = tools
    symbols = text_symbols(nm, obj)
    return symbols, call_graph(objdump, obj, symbols), no_builtins(ll)


def check_std_routines(failures, counts, triple, features, tools, level):
    where = "run builtin lowering builtin_uses.saw %s %s" % (triple, level)
    obj, ll, why = sawc_object("builtin_uses.saw", triple, features, level, "uses_%s%s" % (triple, level))
    if obj is None:
        failures.append("%s: %s" % (where, why))
        return
    symbols, graph, marked = read(tools, obj, ll)
    for routine in sorted(set(MEMORY + INTEGER)):
        wanted = routine in STD_ROUTINES[triple]
        if not wanted:
            if routine in symbols:
                failures.append("%s: the object defines %s, which std defines only on a 32-bit word"
                                % (where, routine))
            continue
        if symbols.get(routine) != "W":
            failures.append("%s: %s is %r in the object, not a weak definition (W)"
                            % (where, routine, symbols.get(routine)))
            continue
        problems = reach_problems(routine, graph, marked)
        failures.extend("%s: %s %s" % (where, routine, p) for p in problems)
        if not problems:
            counts["run builtin lowering std routines checked"] = \
                counts.get("run builtin lowering std routines checked", 0) + 1


def self_calls(program, routine, triple, features, tools, level, stem):
    """(the routine's nm letter, its reach problems, the `.ll`, the object's
    function symbols), or a failure string in place of the first."""
    obj, ll, why = sawc_object(program, triple, features, level, stem)
    if obj is None:
        return why, None, None, None
    symbols, graph, marked = read(tools, obj, ll)
    return symbols.get(routine), reach_problems(routine, graph, marked), ll, symbols


def yield_problem(routine, ll, symbols, triple):
    """Why the program's `routine` is not the object's one definition of it,
    with std's other routines still beside it; None when it is. std's routine
    of that name yields to the program's (`TcProgram.export_unique`)."""
    defines = [found.group(1) or found.group(2) for found in map(_DEFINE.match, ll.splitlines()) if found]
    if defines.count(routine) != 1:
        return "the module defines %s %d times" % (routine, defines.count(routine))
    std_own = [name for name in defines if name.startswith("saw std.builtins.") and ("." + routine + "(") in name]
    if std_own:
        return "std's %s is still defined beside the program's: %s" % (routine, std_own[0])
    missing = [name for name in STD_ROUTINES[triple] if name != routine and symbols.get(name) != "W"]
    if missing:
        return "std's %s are not weak definitions beside it" % ", ".join(missing)
    return None


def check_program_routines(failures, counts, triple, features, tools, level):
    for program, routine in (("builtin_memset_helper.saw", "memset"), ("builtin_memmove_shift.saw", "memmove")):
        where = "run builtin lowering %s %s %s" % (program, triple, level)
        letter, problems, ll, symbols = self_calls(program, routine, triple, features, tools, level,
                                                   "%s_%s%s" % (routine, triple, level))
        if problems is None:
            failures.append("%s: %s" % (where, letter))
            continue
        yielded = yield_problem(routine, ll, symbols, triple)
        if letter != "W" or problems or yielded:
            failures.append("%s: %s is %r; %s" % (where, routine, letter,
                                                  "; ".join(problems + [yielded or ""]).strip("; ") or "no self-call"))
        else:
            counts["run builtin lowering program routines with no self-call"] = \
                counts.get("run builtin lowering program routines with no self-call", 0) + 1


def check_cross_module(failures, counts, triple, features, tools, level):
    where = "run builtin lowering builtin_cross_module.saw %s %s" % (triple, level)
    letter, problems, ll, _ = self_calls("builtin_cross_module.saw", "memset", triple, features, tools, level,
                                         "cross_%s%s" % (triple, level))
    if problems is None:
        failures.append("%s: %s" % (where, letter))
        return
    reaches = any(p.startswith("reaches itself") for p in problems)
    pinned = level in CROSS_MODULE_SELF_CALLS[triple]
    if reaches != pinned:
        failures.append("%s: memset %s itself, where CROSS_MODULE_SELF_CALLS says it %s"
                        % (where, "reaches" if reaches else "does not reach", "does" if pinned else "does not"))
        return
    if any('builtin_fill.fill' in name for name in no_builtins(ll)):
        failures.append("%s: the imported loop carries \"no-builtins\", which reaches only the routine's module"
                        % where)
        return
    counts["run builtin lowering cross-module cells pinned"] = \
        counts.get("run builtin lowering cross-module cells pinned", 0) + 1


def check_sees_a_self_call(failures, counts, clang, tools):
    """The check catches what it is for: `builtin_memset_helper.saw`'s riscv32
    -O2 module, its helper's "no-builtins" taken away and compiled as sawc
    compiles it, is reported as reaching itself."""
    triple, features, _ = ARCHES[0]
    where = "run builtin lowering: the injected helper without \"no-builtins\""
    obj, ll, why = sawc_object("builtin_memset_helper.saw", triple, features, "-O2", "injected_source")
    if obj is None:
        failures.append("%s: %s" % (where, why))
        return
    lines = []
    for line in ll.splitlines():
        if line.startswith("define ") and "fill_bytes" in line:
            line = re.sub(r"\)( .*)#1\b", r")\1#0", line)
        lines.append(line)
    injected = os.path.join(OUT, "injected.ll")
    with open(injected, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    injected_obj = os.path.join(OUT, "injected.o")
    c = subprocess.run([clang, "-c", "-target", build.clang_triple(triple), "-O2", "-ffunction-sections",
                        "-fdata-sections", "-fno-pic", "-x", "ir", injected, "-o", injected_obj],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if c.returncode != 0:
        failures.append("%s: %s does not compile it: %s" % (where, clang, (c.stdout + c.stderr).strip()[:300]))
        return
    symbols, graph, marked = read(tools, injected_obj, "\n".join(lines))
    problems = reach_problems("memset", graph, marked)
    if not any(p.startswith("reaches itself") for p in problems):
        failures.append("%s: is not reported as reaching itself (%s)" % (where, problems or "nothing reported"))
        return
    counts["run builtin lowering injected self-calls caught"] = \
        counts.get("run builtin lowering injected self-calls caught", 0) + 1


def check_hosted(failures, counts):
    """`builtin_uses.saw` for the host defines none of the routines: a hosted
    program takes them from the C library."""
    where = "run builtin lowering builtin_uses.saw hosted"
    r = subprocess.run([build.SAWC, "build", "-c", "--emit-ll", "-g0", "--std-root", "std",
                        rel(os.path.join(LOWERING, "builtin_uses.saw"))], cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
    if r.returncode != 0:
        failures.append("%s: sawc writes no module: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
        return
    defined = set()
    for line in r.stdout.splitlines():
        found = _DEFINE.match(line)
        if found and (found.group(1) or found.group(2)) in MEMORY + INTEGER:
            defined.add(found.group(1) or found.group(2))
    if defined or '"no-builtins"' in r.stdout:
        failures.append("%s: the module defines %s" % (where, ", ".join(sorted(defined)) or "a no-builtins group"))
        return
    counts["run builtin lowering hosted modules with no routine"] = \
        counts.get("run builtin lowering hosted modules with no routine", 0) + 1


def check_shift_checks(failures, counts, triple, features):
    """At -O0 the constant shift carries no range check and the variable one
    keeps its call to `__saw_fail_shift`."""
    where = "run builtin lowering shift_checks.saw %s -O0" % triple
    cmd = [build.SAWC, "build", "--emit-ll", "-g0", "--freestanding", "--std-root", "std", "--target", triple]
    if features is not None:
        cmd += ["--target-features", features]
    r = subprocess.run(cmd + ["-O0", rel(os.path.join(LOWERING, "shift_checks.saw"))], cwd=REPO,
                       capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        failures.append("%s: sawc writes no module: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
        return
    bodies = {}
    current = None
    for line in r.stdout.splitlines():
        found = _DEFINE.match(line)
        if found:
            current = found.group(1) or found.group(2)
            bodies[current] = []
        elif line == "}":
            current = None
        elif current is not None:
            bodies[current].append(line)
    checks = {name: sum("@__saw_fail_shift(" in line for line in bodies.get(name, ()))
              for name in ("shift_by_constant", "shift_by_variable")}
    if checks != {"shift_by_constant": 0, "shift_by_variable": 1}:
        failures.append("%s: the shift checks are %r, not none for the constant counts and one for the variable"
                        % (where, checks))
        return
    counts["run builtin lowering shift checks pinned"] = counts.get("run builtin lowering shift checks pinned", 0) + 1


def check(failures, counts):
    check_hosted(failures, counts)
    for triple, features, _ in ARCHES:
        check_shift_checks(failures, counts, triple, features)
        clang, skip, problem = record_clang(triple)
        if problem:
            failures.append("run builtin lowering: %s" % problem)
            continue
        if clang is None:
            counts["run builtin lowering targets skipped, no clang"] = \
                counts.get("run builtin lowering targets skipped, no clang", 0) + 1
            print("builtin lowering: %s not compiled: %s" % (triple, skip))
            continue
        tools = (llvm_tool(clang, "llvm-objdump"), llvm_tool(clang, "llvm-nm"))
        if None in tools:
            failures.append("run builtin lowering: no llvm-objdump or llvm-nm reads %s's objects (%s)"
                            % (triple, clang))
            continue
        for level in LEVELS:
            check_std_routines(failures, counts, triple, features, tools, level)
            check_program_routines(failures, counts, triple, features, tools, level)
            check_cross_module(failures, counts, triple, features, tools, level)
        if triple == ARCHES[0][0]:
            check_sees_a_self_call(failures, counts, clang, tools)


def main():
    failures = []
    counts = {}
    check(failures, counts)
    for key in sorted(counts):
        print("%s: %d" % (key, counts[key]))
    for failure in failures:
        print("FAIL " + failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

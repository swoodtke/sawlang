#!/usr/bin/env python3
"""The builtin check: a freestanding object defines std's builtin routines
weakly, and no builtin routine reaches itself (SL-948).

    python compiler/tests/run/builtin_lowering.py     # the check alone

`run_lane.run()` calls `check()`. Each program of `lowering/` it names is
built by `sawc build --freestanding` for riscv32 (`+m,+a,+c`), aarch64 and
Xtensa (ESP32-S3), at -O0, -O1, -O2, -Os and -Oz, and each object's relocations
are read with `llvm-readobj`, each resolved by the symbol it carries
(`readobj_graph`; on Xtensa a call loads its callee's address from a literal
pool, so a relocation naming a literal names the function the literal names).
An object whose graph has no edge fails: the reader sees none of its calls.

- `builtin_uses.saw`'s object defines std's routines, each `W` (`STD_ROUTINES`:
  the memory routines and the soft-float routines on every arch, none having
  an FP unit, and the 64-bit integer helpers on riscv32 and Xtensa), and every
  function a routine reaches through relocations carries `"no-builtins"` in
  the object's `.ll`, is a machine-outlined fragment (whose relocations are
  followed), or is one of std's `__saw_fail_*` panic helpers, which a correct
  routine never calls; no routine reaches its own symbol; and a soft-float
  routine reaches no soft-float routine at all, its own symbol included, and
  no `__saw_fail_*` helper, either of which means it used a Float operation
  or a checked one;
- `builtin_float_operation.saw`'s own `__muldf3`, written with a Float `+`, is
  reported as reaching `__adddf3` at -O0 and -O2 on every arch, so the check
  sees what it is for;
- `builtin_memset_helper.saw` and `builtin_memmove_shift.saw`, a program's own
  `memset` and `memmove`, reach themselves at no level and are `W`, the
  object's one definition of the name, with std's other memory routines
  beside them: std's routine of the name yields (`TcProgram.export_unique`);
- `builtin_cross_module.saw`'s `memset` fills through another module's loop,
  which "no-builtins" does not reach: the routine reaches itself at exactly the
  levels `CROSS_MODULE_SELF_CALLS` pins;
- `builtin_memset_helper.saw`'s riscv32 and Xtensa -O2 modules with its helper's
  "no-builtins" taken away are reported as reaching itself, so the check sees
  what it is for;
- `builtin_uses.saw` built for the host defines none of the routines, and
  `shift_checks.saw`'s -O0 module checks the variable shift's count and not the
  constant one's (`ll_constant_shift_count`);
- the soft-float routines, `std/builtins/float.saw` built for the host as a
  module of `softfloat/check.saw` at -O0 and -O2, give compiler-rt's result on
  every row of `softfloat/vectors.txt` (a NaN result any NaN), and a copy of
  the vectors with one result changed is reported as exactly one miss.

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
# std's routines: sawc's builtin name set (`ll_builtin_symbol`,
# compiler/llvm/src/attributes.saw).
MEMORY = ("memcpy", "memset", "memmove")
INTEGER = ("__divdi3", "__moddi3", "__udivdi3", "__umoddi3", "__ashldi3", "__ashrdi3", "__lshrdi3")
FLOAT = ("__adddf3", "__subdf3", "__muldf3", "__divdf3", "__eqdf2", "__nedf2", "__ltdf2", "__ledf2", "__gtdf2",
         "__gedf2", "__unorddf2", "__fixdfsi", "__fixdfdi", "__fixunsdfsi", "__fixunsdfdi", "__floatsidf",
         "__floatdidf", "__floatunsidf", "__floatundidf")
# (triple, `--target-features` or None for the freestanding default, the
# routines std defines there).
ARCHES = (
    ("riscv32-unknown-none-elf", "+m,+a,+c", MEMORY + INTEGER + FLOAT),
    ("aarch64-unknown-none-elf", None, MEMORY + FLOAT),
    ("xtensa-esp-unknown-elf", None, MEMORY + INTEGER + FLOAT),
)
XTENSA = "xtensa-esp-unknown-elf"
SOFTFLOAT = os.path.join(HERE, "softfloat")
FLOAT_MODULE = os.path.join(REPO, "std", "builtins", "float.saw")
STD_ROUTINES = {triple: routines for triple, _, routines in ARCHES}
# The levels at which `builtin_cross_module.saw`'s `memset` reaches itself:
# LLVM turns the imported loop into a `memset` call before inlining it, and
# no arch's -O0 or -Oz inlines it.
CROSS_MODULE_SELF_CALLS = {
    "riscv32-unknown-none-elf": ("-O1", "-O2", "-Os"),
    "aarch64-unknown-none-elf": ("-O1", "-O2", "-Os"),
    XTENSA: ("-O1", "-O2", "-Os"),
}

# A readobj dump's relocation run header, `Section (INDEX) .rela.NAME {`; a
# symbol's `Section: NAME (0xINDEX)`; a relocation's `Symbol: NAME (INDEX)`.
_READOBJ_APPLIES = re.compile(r"^Section \((\d+)\) .* \{$")
_READOBJ_SECTION = re.compile(r"^.* \((0x[0-9A-Fa-f]+)\)$")
_READOBJ_SYMBOL = re.compile(r"^.* \((\d+)\)$")
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


def call_graph(readobj, obj):
    """{function: the functions its relocations name} of object `obj`, read
    by `llvm-readobj` (`readobj_graph`)."""
    dump = subprocess.run([readobj, "--sections", "--symbols", "--relocations", "--expand-relocs", obj],
                          capture_output=True, text=True, timeout=TIMEOUT).stdout
    return readobj_graph(dump)


def readobj_blocks(dump):
    """(sections, symbols, relocations) of an `llvm-readobj --sections
    --symbols --relocations --expand-relocs` dump: each section and symbol a
    {field: value} in table order, and each relocation a (the section it
    applies to by index, {field: value})."""
    sections, symbols, relocations = [], [], []
    table = None
    block = None
    applies = None
    for line in dump.splitlines():
        text = line.strip()
        if text in ("Sections [", "Symbols [", "Relocations ["):
            table = text.split()[0]
            continue
        found = _READOBJ_APPLIES.match(text)
        if table == "Relocations" and found:
            applies = int(found.group(1))
            continue
        if text in ("Section {", "Symbol {", "Relocation {"):
            block = {}
            continue
        if text == "}" and block is not None:
            if table == "Sections":
                sections.append(block)
            elif table == "Symbols":
                symbols.append(block)
            elif table == "Relocations":
                relocations.append((applies, block))
            block = None
            continue
        if block is not None and ": " in text:
            key, value = text.split(": ", 1)
            block[key] = value
    return sections, symbols, relocations


def readobj_graph(dump):
    """{function: the functions its relocations name}, from a readobj dump.
    Each relocation is resolved by the symbol index it carries: to that
    function, or, through a section symbol (aarch64's spelling of a local
    call), to the function of that section at its addend. Local functions of
    one name from different codegen units, the machine outliner's
    `OUTLINED_FUNCTION_N`, so stay apart; such a name is keyed `NAME#INDEX`.
    A relocation naming data names nothing here."""
    sections, symbols, relocations = readobj_blocks(dump)
    info = {}
    for section in sections:
        info[int(section.get("Index", "-1"))] = int(section.get("Info", "0"))
    functions = []
    for index, symbol in enumerate(symbols):
        found = _READOBJ_SECTION.match(symbol.get("Section", ""))
        if symbol.get("Type", "").startswith("Function") and found and int(found.group(1), 16) != 0:
            functions.append((index, symbol["Name"].rsplit(" (", 1)[0], int(found.group(1), 16),
                              int(symbol.get("Value", "0"), 16), int(symbol.get("Size", "0"))))
    named = {}
    for _, name, _, _, _ in functions:
        named[name] = named.get(name, 0) + 1
    key = {index: (name if named[name] == 1 else "%s#%d" % (name, index)) for index, name, _, _, _ in functions}

    def at(section, offset, exact):
        for index, _, where, value, size in functions:
            if where == section and (offset == value if exact else value <= offset < value + max(size, 1)):
                return key[index]
        return None

    def resolve(relocation):
        """The function a relocation names, directly or through a section
        symbol and its addend; None for data."""
        found = _READOBJ_SYMBOL.match(relocation.get("Symbol", ""))
        if not found:
            return None
        index = int(found.group(1))
        if index in key:
            return key[index]
        symbol = symbols[index] if index < len(symbols) else {}
        section = _READOBJ_SECTION.match(symbol.get("Section", ""))
        if symbol.get("Type", "").startswith("Section") and section:
            return at(int(section.group(1), 16), int(relocation.get("Addend", "0"), 16), True)
        return None

    literal_sections = set()
    for section in sections:
        name = section.get("Name", "").rsplit(" (", 1)[0]
        if name == ".literal" or name.startswith(".literal."):
            literal_sections.add(int(section.get("Index", "-1")))
    literal = {}
    for applies, relocation in relocations:
        if info.get(applies, -1) in literal_sections:
            target = resolve(relocation)
            if target is not None:
                literal[(info[applies], int(relocation.get("Offset", "0"), 16))] = target

    graph = {name: set() for name in key.values()}
    for applies, relocation in relocations:
        caller = at(info.get(applies, -1), int(relocation.get("Offset", "0"), 16), False)
        if caller is None:
            continue
        target = resolve(relocation)
        found = _READOBJ_SYMBOL.match(relocation.get("Symbol", ""))
        if target is None and found:
            index = int(found.group(1))
            symbol = symbols[index] if index < len(symbols) else {}
            section = _READOBJ_SECTION.match(symbol.get("Section", ""))
            if symbol.get("Type", "").startswith("Section") and section:
                target = literal.get((int(section.group(1), 16), int(relocation.get("Addend", "0"), 16)))
        if target is not None:
            graph[caller].add(target)
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


def float_reach_problems(routine, graph):
    """Why soft-float `routine` may have used a Float operation or a checked
    one: a path to any soft-float routine, its own symbol included, or to a
    `__saw_fail_*` panic helper; empty when there is none."""
    problems = []
    seen = {routine}
    pending = [(routine, [routine])]
    while pending:
        name, path = pending.pop()
        for callee in sorted(graph.get(name, ())):
            if callee in FLOAT or callee.startswith("__saw_fail"):
                problems.append("reaches %s: %s" % (callee, " -> ".join(path + [callee])))
                continue
            if callee in seen:
                continue
            seen.add(callee)
            pending.append((callee, path + [callee]))
    return problems


def read(tools, obj, ll):
    readobj, nm = tools
    symbols = text_symbols(nm, obj)
    return symbols, call_graph(readobj, obj), no_builtins(ll)


def check_std_routines(failures, counts, triple, features, tools, level):
    where = "run builtin lowering builtin_uses.saw %s %s" % (triple, level)
    obj, ll, why = sawc_object("builtin_uses.saw", triple, features, level, "uses_%s%s" % (triple, level))
    if obj is None:
        failures.append("%s: %s" % (where, why))
        return
    symbols, graph, marked = read(tools, obj, ll)
    if not any(graph.values()):
        failures.append("%s: the reader sees none of the object's calls (its graph has no edge)" % where)
        return
    for routine in sorted(set(MEMORY + INTEGER + FLOAT)):
        wanted = routine in STD_ROUTINES[triple]
        if not wanted:
            if routine in symbols:
                failures.append("%s: the object defines %s, which std does not define for this target"
                                % (where, routine))
            continue
        if symbols.get(routine) != "W":
            failures.append("%s: %s is %r in the object, not a weak definition (W)"
                            % (where, routine, symbols.get(routine)))
            continue
        problems = reach_problems(routine, graph, marked)
        if routine in FLOAT:
            problems += float_reach_problems(routine, graph)
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


def check_sees_a_self_call(failures, counts, triple, features, clang, tools):
    """The check catches what it is for: `builtin_memset_helper.saw`'s -O2
    module for riscv32 and for Xtensa, its helper's "no-builtins" taken away
    and compiled as sawc compiles it, is reported as reaching itself."""
    where = "run builtin lowering: the injected helper without \"no-builtins\" %s" % triple
    obj, ll, why = sawc_object("builtin_memset_helper.saw", triple, features, "-O2", "injected_source_" + triple)
    if obj is None:
        failures.append("%s: %s" % (where, why))
        return
    lines = []
    for line in ll.splitlines():
        if line.startswith("define ") and "fill_bytes" in line:
            line = re.sub(r"\)( .*)#1\b", r")\1#0", line)
        lines.append(line)
    injected = os.path.join(OUT, "injected_%s.ll" % triple)
    with open(injected, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    injected_obj = os.path.join(OUT, "injected_%s.o" % triple)
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


def check_float_operation_seen(failures, counts, triple, features, tools, level):
    """The check catches what it is for: `builtin_float_operation.saw`'s own
    `__muldf3`, whose Float `+` LLVM lowers into a call of `__adddf3`, is
    reported as reaching it."""
    where = "run builtin lowering builtin_float_operation.saw %s %s" % (triple, level)
    obj, ll, why = sawc_object("builtin_float_operation.saw", triple, features, level,
                               "float_operation_%s%s" % (triple, level))
    if obj is None:
        failures.append("%s: %s" % (where, why))
        return
    symbols, graph, _ = read(tools, obj, ll)
    problems = float_reach_problems("__muldf3", graph)
    if not any(p.startswith("reaches __adddf3") for p in problems):
        failures.append("%s: the Float `+` in `__muldf3` is not reported as reaching __adddf3 (%s)"
                        % (where, problems or "nothing reported"))
        return
    counts["run builtin lowering Float operations caught"] = \
        counts.get("run builtin lowering Float operations caught", 0) + 1


def soft_float_check(failures, where, vectors, level, exe):
    """(misses, the summary line) of `softfloat/check.saw`'s binary `exe` run on
    `vectors`, or None after recording why it did not run."""
    r = subprocess.run([exe, vectors], cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    lines = r.stdout.strip().splitlines()
    found = re.match(r"soft-float vectors: \d+ lines, (\d+) results, (\d+) misses$", lines[-1] if lines else "")
    if found is None or int(found.group(1)) == 0 or r.returncode != (1 if int(found.group(2)) else 0):
        failures.append("%s %s: exit %d, %s" % (where, level, r.returncode,
                                               (r.stdout + r.stderr).strip()[-600:] or "no output"))
        return None
    return int(found.group(2)), lines[-1]


def check_soft_float_vectors(failures, counts):
    """The soft-float routines, built for the host, on every row of
    `softfloat/vectors.txt` at -O0 and -O2, and on a copy whose first `B`
    line's sum is changed, which is exactly one miss. std's file is copied
    under the build directory and mapped as package `softfloat`, since a path
    into std reaches std's files only as std's own modules."""
    where = "run builtin lowering softfloat/check.saw"
    module = os.path.join(OUT, "softfloat")
    os.makedirs(module, exist_ok=True)
    shutil.copyfile(FLOAT_MODULE, os.path.join(module, "float.saw"))
    vectors = os.path.join(SOFTFLOAT, "vectors.txt")
    with open(vectors) as fh:
        rows = fh.read().splitlines()
    first = next(k for k, line in enumerate(rows) if line.startswith("B "))
    fields = rows[first].split()
    fields[3] = "%016x" % (int(fields[3], 16) ^ 1)
    rows[first] = " ".join(fields)
    changed = os.path.join(OUT, "vectors_changed.txt")
    with open(changed, "w") as fh:
        fh.write("\n".join(rows) + "\n")
    for level in ("-O0", "-O2"):
        exe = os.path.join(OUT, "softfloat_check%s" % level)
        r = subprocess.run([build.SAWC, "build", level, "-g0", "--std-root", "std", "--module-path",
                            "softfloat=%s" % rel(module), rel(os.path.join(SOFTFLOAT, "check.saw")), "-o", exe],
                           cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            failures.append("%s %s: sawc builds nothing: %s" % (where, level, (r.stdout + r.stderr).strip()[:300]))
            continue
        clean = soft_float_check(failures, where, rel(vectors), level, exe)
        control = soft_float_check(failures, where + " on the changed copy", rel(changed), level, exe)
        if clean is None or control is None:
            continue
        if clean[0] != 0 or control[0] != 1:
            failures.append("%s %s: %d misses on the vectors and %d on the changed copy, not 0 and 1: %s"
                            % (where, level, clean[0], control[0], clean[1]))
            continue
        counts["run builtin lowering soft-float vector runs"] = \
            counts.get("run builtin lowering soft-float vector runs", 0) + 1


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
        if found and (found.group(1) or found.group(2)) in MEMORY + INTEGER + FLOAT:
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


# A readobj dump, cut to what `readobj_graph` reads, of a split object whose
# two codegen units each kept a local `OUTLINED_FUNCTION_1` in the one merged
# section: `__floatdidf` calls the second (section symbol, addend 0x20), which
# calls `helper`; only the first, another unit's, calls `__saw_fail_head`.
GRAPH_SAMPLE = """Sections [
  Section {
    Index: 1
    Name: .text.__floatdidf (1)
    Info: 0
  }
  Section {
    Index: 2
    Name: .rela.text.__floatdidf (2)
    Info: 1
  }
  Section {
    Index: 3
    Name: .text.OUTLINED_FUNCTION_1 (3)
    Info: 0
  }
  Section {
    Index: 4
    Name: .rela.text.OUTLINED_FUNCTION_1 (4)
    Info: 3
  }
]
Relocations [
  Section (2) .rela.text.__floatdidf {
    Relocation {
      Offset: 0x10
      Type: R_AARCH64_CALL26 (283)
      Symbol: .text.OUTLINED_FUNCTION_1 (1)
      Addend: 0x20
    }
  }
  Section (4) .rela.text.OUTLINED_FUNCTION_1 {
    Relocation {
      Offset: 0x1C
      Type: R_AARCH64_JUMP26 (282)
      Symbol: __saw_fail_head (5)
      Addend: 0x0
    }
    Relocation {
      Offset: 0x24
      Type: R_AARCH64_JUMP26 (282)
      Symbol: helper (6)
      Addend: 0x0
    }
  }
]
Symbols [
  Symbol {
    Name:  (0)
    Type: None (0x0)
    Section: Undefined (0x0)
  }
  Symbol {
    Name: .text.OUTLINED_FUNCTION_1 (5)
    Value: 0x0
    Type: Section (0x3)
    Section: .text.OUTLINED_FUNCTION_1 (0x3)
  }
  Symbol {
    Name: OUTLINED_FUNCTION_1 (6)
    Value: 0x0
    Size: 32
    Type: Function (0x2)
    Section: .text.OUTLINED_FUNCTION_1 (0x3)
  }
  Symbol {
    Name: OUTLINED_FUNCTION_1 (6)
    Value: 0x20
    Size: 8
    Type: Function (0x2)
    Section: .text.OUTLINED_FUNCTION_1 (0x3)
  }
  Symbol {
    Name: __floatdidf (7)
    Value: 0x0
    Size: 64
    Type: Function (0x2)
    Section: .text.__floatdidf (0x1)
  }
  Symbol {
    Name: __saw_fail_head (8)
    Value: 0x0
    Size: 16
    Type: Function (0x2)
    Section: .text.__saw_fail_head (0x5)
  }
  Symbol {
    Name: helper (9)
    Value: 0x0
    Size: 16
    Type: Function (0x2)
    Section: .text.helper (0x6)
  }
]
"""


# A readobj dump, cut to what `readobj_graph` reads, of an Xtensa object: a
# call is `l32r` of a literal, then `callx0`, so `caller`'s relocations name its
# `.literal.caller` section symbol at the literal's offset, and the literal
# words name `callee_a` (by symbol), `callee_b` (by section symbol) and, at
# offset 8, data.
XTENSA_SAMPLE = """Sections [
  Section {
    Index: 1
    Name: .text.caller (1)
    Info: 0
  }
  Section {
    Index: 2
    Name: .rela.text.caller (2)
    Info: 1
  }
  Section {
    Index: 3
    Name: .literal.caller (3)
    Info: 0
  }
  Section {
    Index: 4
    Name: .rela.literal.caller (4)
    Info: 3
  }
  Section {
    Index: 5
    Name: .text.callee_a (5)
    Info: 0
  }
  Section {
    Index: 6
    Name: .text.callee_b (6)
    Info: 0
  }
  Section {
    Index: 7
    Name: .rodata.table (7)
    Info: 0
  }
]
Relocations [
  Section (2) .rela.text.caller {
    Relocation {
      Offset: 0x5
      Type: R_XTENSA_SLOT0_OP (20)
      Symbol: .literal.caller (1)
      Addend: 0x0
    }
    Relocation {
      Offset: 0xB
      Type: R_XTENSA_SLOT0_OP (20)
      Symbol: .literal.caller (1)
      Addend: 0x4
    }
    Relocation {
      Offset: 0x11
      Type: R_XTENSA_SLOT0_OP (20)
      Symbol: .literal.caller (1)
      Addend: 0x8
    }
  }
  Section (4) .rela.literal.caller {
    Relocation {
      Offset: 0x0
      Type: R_XTENSA_32 (1)
      Symbol: callee_a (4)
      Addend: 0x0
    }
    Relocation {
      Offset: 0x4
      Type: R_XTENSA_32 (1)
      Symbol: .text.callee_b (2)
      Addend: 0x0
    }
    Relocation {
      Offset: 0x8
      Type: R_XTENSA_32 (1)
      Symbol: table (6)
      Addend: 0x0
    }
  }
]
Symbols [
  Symbol {
    Name:  (0)
    Type: None (0x0)
    Section: Undefined (0x0)
  }
  Symbol {
    Name: .literal.caller (1)
    Value: 0x0
    Type: Section (0x3)
    Section: .literal.caller (0x3)
  }
  Symbol {
    Name: .text.callee_b (2)
    Value: 0x0
    Type: Section (0x3)
    Section: .text.callee_b (0x6)
  }
  Symbol {
    Name: caller (3)
    Value: 0x0
    Size: 32
    Type: Function (0x2)
    Section: .text.caller (0x1)
  }
  Symbol {
    Name: callee_a (4)
    Value: 0x0
    Size: 8
    Type: Function (0x2)
    Section: .text.callee_a (0x5)
  }
  Symbol {
    Name: callee_b (5)
    Value: 0x0
    Size: 8
    Type: Function (0x2)
    Section: .text.callee_b (0x6)
  }
  Symbol {
    Name: table (6)
    Value: 0x0
    Size: 12
    Type: Object (0x1)
    Section: .rodata.table (0x7)
  }
]
"""


def check_graph_reading(failures, counts):
    """`readobj_graph` follows an Xtensa call through its literal: `XTENSA_SAMPLE`'s
    `caller` reaches `callee_a` and `callee_b`, and a literal naming data names
    nothing."""
    graph = readobj_graph(XTENSA_SAMPLE)
    want = {"caller": {"callee_a", "callee_b"}, "callee_a": set(), "callee_b": set()}
    if graph != want:
        failures.append("run builtin lowering: the recorded Xtensa object reads as %r, not %r" % (graph, want))
    else:
        counts["run builtin lowering literal-pool objects read by symbol"] = 1
    check_split_graph_reading(failures, counts)


def check_split_graph_reading(failures, counts):
    """`readobj_graph` keeps two units' same-named local fragments apart, so
    `GRAPH_SAMPLE`'s `__floatdidf` reaches `helper` and not another unit's
    `__saw_fail_head`, which the graph keyed by name alone would join."""
    graph = readobj_graph(GRAPH_SAMPLE)
    want = {"__floatdidf": {"OUTLINED_FUNCTION_1#3"}, "OUTLINED_FUNCTION_1#2": {"__saw_fail_head"},
            "OUTLINED_FUNCTION_1#3": {"helper"}, "__saw_fail_head": set(), "helper": set()}
    joined = {}
    for name, callees in graph.items():
        joined.setdefault(name.split("#")[0], set()).update(c.split("#")[0] for c in callees)
    if graph != want:
        failures.append("run builtin lowering: the recorded split object reads as %r, not %r" % (graph, want))
    elif float_reach_problems("__floatdidf", graph):
        failures.append("run builtin lowering: the recorded split object's __floatdidf reaches a panic helper")
    elif not float_reach_problems("__floatdidf", joined):
        failures.append("run builtin lowering: the recorded split object no longer joins its fragments by name")
    else:
        counts["run builtin lowering split objects read by symbol"] = 1


def check(failures, counts):
    check_graph_reading(failures, counts)
    check_hosted(failures, counts)
    check_soft_float_vectors(failures, counts)
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
        tools = (llvm_tool(clang, "llvm-readobj"), llvm_tool(clang, "llvm-nm"))
        if None in tools:
            failures.append("run builtin lowering: no llvm-readobj or llvm-nm reads %s's objects (%s)"
                            % (triple, clang))
            continue
        for level in LEVELS:
            check_std_routines(failures, counts, triple, features, tools, level)
            check_program_routines(failures, counts, triple, features, tools, level)
            check_cross_module(failures, counts, triple, features, tools, level)
        for level in ("-O0", "-O2"):
            check_float_operation_seen(failures, counts, triple, features, tools, level)
        if triple in (ARCHES[0][0], XTENSA):
            check_sees_a_self_call(failures, counts, triple, features, clang, tools)


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

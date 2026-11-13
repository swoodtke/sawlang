#!/usr/bin/env python3
"""The 32-bit word check: the backend's `.ll` for a 32-bit target holds a
64-bit integer only where the census says the value is 64 bits.

    python compiler/tests/run/word32_ir.py     # the check alone

`run_lane.run()` calls `check()`, which runs one row of `TARGETS` after the
other (riscv32, then xtensa). For each probe of `riscv32/`, built
`--emit-ll --freestanding --target TRIPLE` with each of the row's feature sets
(riscv32: `+m,-a,+c`, `+m,+a,+c` and no operand; xtensa: the target's defaults):

- a WORD probe (`word_*.saw`) uses no type wider than the word, so every
  `i64` in its module must be the enum tag carrier: a tag widened from its
  stored width (`zext iN %t to i64`), or a switch or a compare of such a
  widened tag (`ALLOWLIST`, each rule naming its census row);
- a WIDE probe (`wide_*.saw`) renders `Int64` and `UInt64` through the
  64-bit renderers, which take an i64 and return the word (spec, "An integer
  argument renders at its own width");
- every probe's module compiles for the target with a capable clang, and the
  object references no `__atomic_*_8` and no 64-bit division routine for a
  word probe, and exactly the row's atomic routines on a feature set without
  native atomics (riscv32 without `+a`, the atomics probe) and no atomic
  routine on one with them (xtensa always: its word atomics are inline);
- a row with an `allowed` set holds every undefined symbol of every probe's
  object to it (xtensa: the runtime seam alone, since no probe uses a
  `Float` or a 64-bit division);
- `sawc build --freestanding` for riscv32 writes the atomics probe as an
  ELF32 RISC-V relocatable object defining its export (the xtensa object has
  its own check in run_lane.py).

The clang is the one the target's record beside the stages names, which the
stage build writes from `build.pick_clang` (`SAWC_CLANG` overrides). For
riscv32, when no clang compiles IR for it there is no record, and the object
half is skipped and says why; a capable clang with no record fails; the `i64`
half always runs. Xtensa is compiled by Espressif's clang alone, and sawc
refuses the target with no record, so with none the whole row skips and says
so.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
from typing import NamedTuple, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
COMPILER = os.path.dirname(TESTS)
REPO = os.path.dirname(COMPILER)
sys.path.insert(0, os.path.join(COMPILER, "tools"))

import build  # noqa: E402

sys.path.insert(0, HERE)
import builtin_lowering  # noqa: E402

WORD_BYTES = 4
# Both targets read the same probes: they use nothing the word differs on.
PROBES = os.path.join(HERE, "riscv32")
ATOMICS_PROBE = "word_atomics.saw"
TIMEOUT = 600
# The probe `sawc build --freestanding` writes an object of, and its export.
OBJECT_PROBE = "word_atomics.saw"
OBJECT_EXPORT = "probe_atomics"
ELF_CLASS32 = 1
ELF_LITTLE = 1
ELF_RELOCATABLE = 1
ELF_RISCV = 243

RISCV32_TRIPLE = "riscv32-unknown-none-elf"
XTENSA_TRIPLE = "xtensa-esp-unknown-elf"
# Without the `A` extension, then with it, then with no operand at all: the
# default `+m,+a,+c` (`target_effective_features`) has it. A row's third field
# names the set whose module it must equal, or is None: the no-operand build
# is the `+m,+a,+c` build, attribute group and all.
NO_ATOMICS = ("--target-features", "+m,-a,+c")
WITH_ATOMICS = ("--target-features", "+m,+a,+c")
RISCV32_FEATURE_SETS = ((NO_ATOMICS, "-noa", None), (WITH_ATOMICS, "-a", None), ((), "-default", WITH_ATOMICS))
# Xtensa has one feature set, the target's own default (`-windowed,-fp,-loop,
# -mac16,-bool`): word atomics are inline `s32c1i`, and `Float` is soft-float.
XTENSA_FEATURE_SETS = (((), "", None),)

# The runtime seam: every `__saw_rt_*` function a probe's module declares and
# leaves to the runtime (runtime/ABI.md).
SEAM = frozenset(("__saw_rt_alloc", "__saw_rt_dealloc", "__saw_rt_last_raw_code", "__saw_rt_panic",
                  "__saw_rt_write_line"))


class Target(NamedTuple):
    """One row: a 32-bit target and what the word check holds it to."""
    label: str
    triple: str
    out: str
    feature_sets: tuple
    # The feature set without native atomics, or None when every set has them.
    no_atomics: Optional[tuple]
    # The `__atomic_*` routines a module references without native atomics.
    routines: frozenset
    # How the failure text names a feature set with native atomics.
    native_words: str
    # Every undefined symbol allowed of a probe's object, or None for no pin.
    allowed: Optional[frozenset]
    # Whether a missing record skips the whole row (Espressif's clang alone
    # compiles the target) rather than only the object half.
    record_only: bool
    object_label: str


def word_atomic_routines():
    """The `__atomic_*` routines a module can reference on a target without
    native atomics: one per atomic operation the backend lowers, at the
    word's width (spec, Profiles)."""
    return frozenset("__atomic_%s_%d" % (op, WORD_BYTES)
                     for op in ("load", "store", "fetch_add", "fetch_sub", "compare_exchange"))


TARGETS = (
    Target("riscv32", RISCV32_TRIPLE, os.path.join(REPO, ".build", "riscv32-ir"), RISCV32_FEATURE_SETS, NO_ATOMICS,
           word_atomic_routines(), "with `+a`", None, False, "riscv32 objects with the expected routines"),
    Target("xtensa", XTENSA_TRIPLE, os.path.join(REPO, ".build", "xtensa-ir"), XTENSA_FEATURE_SETS, None,
           frozenset(), "on a target with inline word atomics", SEAM, True,
           "xtensa objects with the expected routines"),
)

_TAG_WIDEN = re.compile(r"^\s*(%[\w.]+) = zext i(?:8|16|32) %[\w.]+ to i64$")
_TAG_SWITCH = re.compile(r"^\s*switch i64 (%[\w.]+), label %[\w.]+ \[(?:\s*i64 -?\d+, label %[\w.]+)*\s*\]$")
_TAG_COMPARE = re.compile(r"^\s*%[\w.]+ = icmp (?:eq|ne) i64 (%[\w.]+), (-?\d+|%[\w.]+)$")
_I64 = re.compile(r"\bi64\b")
_ATTACHMENT = re.compile(r"(?:, ![\w.]+ ![\w.]+)+$")
_DEFINE = re.compile(r"^define ")
_DIVISION = re.compile(r"^__(?:u?div|u?mod)di3$")

# The 64-bit integers a word probe's module may hold, each the census row
# that keeps it 64 bits (.build/scratch/p865/u6/census.tsv, SL-865).
ALLOWLIST = (
    ("a tag widened from its stored width", "compiler/llvm/src/places.saw:145 (tag_of)"),
    ("a switch on a widened tag", "compiler/llvm/src/calls.saw:120 (switch_term)"),
    ("a compare of a widened tag", "compiler/llvm/src/calls.saw:231 (and the tag compares beside it)"),
)


def rel(path):
    return os.path.relpath(path, REPO)


def std_builtin(target, symbol):
    """Whether `symbol`, a define's or a global's as `i64_problems` reads it,
    is one of std's builtin routines or a function or static of their
    modules, which a freestanding module defines and which work on 64-bit
    values by nature (`builtin_lowering.STD_ROUTINES`; SL-948)."""
    name = symbol.strip('"')
    return (name.startswith(("saw std.builtins.", "static std.builtins."))
            or name in builtin_lowering.STD_ROUTINES[target.triple])


_GLOBAL = re.compile(r'^@("[^"]+"|[\w.$]+) = ')


def i64_problems(target, where, ll):
    """Each line of `ll` spelling `i64` that no `ALLOWLIST` rule admits, read
    with its metadata attachments (`, !dbg !N`) left off, outside std's
    builtin routines (`std_builtin`)."""
    tags = set()
    problems = []
    function = "<module>"
    for line in ll.split("\n"):
        line = _ATTACHMENT.sub("", line)
        if _DEFINE.match(line):
            function = line.split("@", 1)[1].split("(", 1)[0] if "@" in line else line
            tags = set()
        if not _I64.search(line) or std_builtin(target, function):
            continue
        found = _GLOBAL.match(line)
        if found and std_builtin(target, found.group(1)):
            continue
        m = _TAG_WIDEN.match(line)
        if m:
            tags.add(m.group(1))
            continue
        m = _TAG_SWITCH.match(line)
        if m and m.group(1) in tags:
            continue
        m = _TAG_COMPARE.match(line)
        if m and m.group(1) in tags and (m.group(2) in tags or not m.group(2).startswith("%")):
            continue
        problems.append("%s: an i64 in %s that is no tag carrier: %s" % (where, function, line.strip()[:200]))
    return problems


def emit(target, probe, flags):
    """The `.ll` sawc writes for `probe` at the target with `flags`, or the
    refusal's text and None."""
    r = subprocess.run([build.SAWC, "build", "--emit-ll", "--freestanding", "--target", target.triple,
                        "--std-root", "std"] + list(flags) + [rel(probe)],
                       cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip(), None
    return "", r.stdout


def record_clang(target):
    """The clang the target's record beside the stages names, or None."""
    record = build.runtime_manifest(target.triple)
    if os.path.exists(record):
        with open(record) as fh:
            for line in fh:
                if line.startswith("clang "):
                    return line[len("clang "):].strip()
    return None


def target_clang(target):
    """(clang, skip, problem): the clang the target's record names, which
    `sawc build` compiles its objects with; else why the object half skips,
    when no clang compiles IR for the target; else the problem, when one does
    and the stage build wrote no record naming it. A `record_only` row has no
    problem: with no record its whole row skips."""
    clang = record_clang(target)
    if clang is not None:
        return clang, "", ""
    if target.record_only:
        return None, "no Espressif clang record", ""
    record = build.runtime_manifest(target.triple)
    clang, why = build.pick_clang(target.triple, os.environ.get("SAWC_CLANG"))
    if clang is None:
        return None, why, ""
    return None, "", "%s compiles IR for %s, and no clang record %s is beside the stages" % (
        clang, target.label, rel(record))


def nm_tool(clang):
    beside = os.path.join(os.path.dirname(clang), "llvm-nm")
    if os.path.exists(beside):
        return beside
    return shutil.which("llvm-nm") or "nm"


def undefined_symbols(target, clang, ll_path, obj):
    """The undefined symbols of `ll_path` compiled at -O0, or None and the
    compile's complaint."""
    r = subprocess.run([clang, "-c", "-target", target.triple, "-O0", "-x", "ir", ll_path, "-o", obj],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()
    r = subprocess.run([nm_tool(clang), "-u", obj], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return None, "nm cannot read %s: %s" % (obj, r.stderr.strip())
    return {line.split()[-1] for line in r.stdout.splitlines() if line.strip()}, ""


def symbol_problems(target, where, probe, flags, symbols):
    base = os.path.basename(probe)
    word = base.startswith("word_")
    atomics = {s for s in symbols if s.startswith("__atomic_")}
    divisions = {s for s in symbols if _DIVISION.match(s)}
    problems = []
    if word and any(s.endswith("_8") for s in atomics):
        problems.append("%s: a word atomic reaches an 8-byte routine: %s" % (where, sorted(atomics)))
    if word and divisions:
        problems.append("%s: rendering no wider than the word reaches a 64-bit division routine: %s"
                        % (where, sorted(divisions)))
    native = flags != target.no_atomics
    if base == ATOMICS_PROBE and not native and atomics != target.routines:
        problems.append("%s: the atomic routines referenced are %s, not exactly %s"
                        % (where, sorted(atomics), sorted(target.routines)))
    if native and atomics:
        problems.append("%s: %s an atomic routine is still referenced: %s" % (where, target.native_words, sorted(atomics)))
    if target.allowed is not None and symbols - target.allowed:
        problems.append("%s: undefined symbols outside the allowed set: %s" % (where, sorted(symbols - target.allowed)))
    return problems


def sawc_object_problems(target, clang):
    """`sawc build --freestanding --target riscv32-unknown-none-elf` writes,
    with the record's clang, an ELF32 little-endian RISC-V relocatable object
    defining the probe's export."""
    probe = os.path.join(PROBES, OBJECT_PROBE)
    where = "riscv32 object %s" % rel(probe)
    obj = os.path.join(target.out, "sawc-object.o")
    if os.path.exists(obj):
        os.remove(obj)
    r = subprocess.run([build.SAWC, "build", "--freestanding", "--target", target.triple, "--std-root", "std"]
                       + list(target.feature_sets[1][0]) + [rel(probe), "-o", obj], cwd=REPO, capture_output=True,
                       text=True, timeout=TIMEOUT)
    said = (r.stdout + r.stderr).strip()
    if r.returncode != 0 or said or not os.path.exists(obj):
        return ["%s: sawc build exits %d: %s" % (where, r.returncode, said[:300])]
    with open(obj, "rb") as fh:
        head = fh.read(20)
    kind = int.from_bytes(head[16:18], "little")
    machine = int.from_bytes(head[18:20], "little")
    if head[:4] != b"\x7fELF" or head[4] != ELF_CLASS32 or head[5] != ELF_LITTLE or kind != ELF_RELOCATABLE \
            or machine != ELF_RISCV:
        return ["%s: the object is not an ELF32 little-endian RISC-V relocatable file (header %r)"
                % (where, head.hex())]
    r = subprocess.run([nm_tool(clang), "-g", "--defined-only", obj], capture_output=True, text=True,
                       timeout=TIMEOUT)
    if r.returncode != 0 or not re.search(r"^\S+ T %s$" % OBJECT_EXPORT, r.stdout, re.M):
        return ["%s: `%s` is not defined and external: %s" % (where, OBJECT_EXPORT, (r.stdout + r.stderr)[:300])]
    return []


def wide_problems(where, ll):
    """A wide probe renders `Int64` and `UInt64` through the 64-bit renderers,
    each taking an i64 and returning its length as the word."""
    problems = []
    for name in ("__saw_render_int64", "__saw_render_uint64"):
        if not re.search(r"^define internal i32 @%s\(ptr %%out, i64 %%v\)" % name, ll, re.M):
            problems.append("%s: no `define internal i32 @%s(ptr %%out, i64 %%v)`" % (where, name))
    return problems


def check_target(target, failures, counts):
    os.makedirs(target.out, exist_ok=True)
    clang, why, problem = target_clang(target)
    if problem:
        failures.append("%s IR: %s" % (target.label, problem))
        return
    if clang is None and target.record_only:
        counts["%s IR checks skipped: %s" % (target.label, why)] = 1
        return
    probes = sorted(glob.glob(os.path.join(PROBES, "*.saw")))
    if not probes:
        failures.append("%s IR: no probe in %s" % (target.label, rel(PROBES)))
        return
    for probe in probes:
        stem = os.path.splitext(os.path.basename(probe))[0]
        modules = {}
        for flags, suffix, same_as in target.feature_sets:
            where = "%s IR %s %s" % (target.label, rel(probe), " ".join(flags))
            said, ll = emit(target, probe, flags)
            if ll is None:
                failures.append("%s: sawc refuses the module: %s" % (where, said[:300]))
                continue
            modules[flags] = ll
            if same_as is not None and ll != modules.get(same_as):
                failures.append("%s: the module is not the one built with `%s`" % (where, " ".join(same_as)))
            if stem.startswith("word_"):
                found = i64_problems(target, where, ll)
                failures.extend(found)
                if not found:
                    key = "%s word modules with only tag carriers at i64" % target.label
                    counts[key] = counts.get(key, 0) + 1
            else:
                found = wide_problems(where, ll)
                failures.extend(found)
                if not found:
                    key = "%s wide modules rendering through the 64-bit renderers" % target.label
                    counts[key] = counts.get(key, 0) + 1
            if clang is None:
                continue
            ll_path = os.path.join(target.out, "%s%s.ll" % (stem, suffix))
            with open(ll_path, "w") as fh:
                fh.write(ll)
            symbols, complaint = undefined_symbols(target, clang, ll_path, ll_path[:-3] + ".o")
            if symbols is None:
                failures.append("%s: clang refuses the module: %s" % (where, complaint[:300]))
                continue
            found = symbol_problems(target, where, probe, flags, symbols)
            failures.extend(found)
            if not found:
                counts[target.object_label] = counts.get(target.object_label, 0) + 1
    if clang is None:
        counts["%s object checks skipped, no RISC-V-capable clang: %s" % (target.label, why[:120])] = 1
        return
    if target.triple == RISCV32_TRIPLE:
        found = sawc_object_problems(target, clang)
        failures.extend(found)
        if not found:
            counts["riscv32 objects written by sawc build"] = 1


def check(failures, counts):
    for target in TARGETS:
        check_target(target, failures, counts)


def main():
    status = 0
    for target in TARGETS:
        failures = []
        counts = {}
        check_target(target, failures, counts)
        for failure in failures:
            print(failure)
        summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
        print("%s IR: %s: %s" % (target.label, "FAIL (%d)" % len(failures) if failures else "ok", summary))
        status |= 1 if failures else 0
    return status


if __name__ == "__main__":
    sys.exit(main())

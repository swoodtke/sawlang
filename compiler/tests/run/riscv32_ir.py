#!/usr/bin/env python3
"""The riscv32 word check: the backend's `.ll` for a 32-bit target holds a
64-bit integer only where the census says the value is 64 bits.

    python compiler/tests/run/riscv32_ir.py     # the check alone

`run_lane.run()` calls `check()`. For each probe of `riscv32/`, built
`--emit-ll --freestanding --target riscv32-unknown-none-elf`, with
`+m,-a,+c` and with `+m,+a,+c`:

- a WORD probe (`word_*.saw`) uses no type wider than the word, so every
  `i64` in its module must be the enum tag carrier: a tag widened from its
  stored width (`zext iN %t to i64`), or a switch or a compare of such a
  widened tag (`ALLOWLIST`, each rule naming its census row);
- a WIDE probe (`wide_*.saw`) renders `Int64` and `UInt64` through the
  64-bit renderers, which take an i64 and return the word (spec, "An integer
  argument renders at its own width");
- every probe's module compiles for riscv32 with a RISC-V-capable clang,
  and the object references no `__atomic_*_8` and no 64-bit division
  routine for a word probe, and exactly `atomic_routines()` without `+a` and
  no atomic routine with it for the atomics probe;
- `sawc build --freestanding` for riscv32 writes the atomics probe as an
  ELF32 RISC-V relocatable object defining its export.

The clang is the one the riscv32 record beside the stages names, which the
stage build writes from `build.pick_clang` (`SAWC_CLANG` overrides). When no
clang compiles IR for riscv32 there is no record, and the object half is
skipped and says why; a capable clang with no record fails. The `i64` half
always runs.
"""
import glob
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

TRIPLE = "riscv32-unknown-none-elf"
WORD_BYTES = 4
PROBES = os.path.join(HERE, "riscv32")
OUT = os.path.join(REPO, ".build", "riscv32-ir")
ATOMICS_PROBE = "word_atomics.saw"
# Without the `A` extension, then with it. `-a` is written out, since clang's
# own riscv32 default (`rv32imac`) has it.
NO_ATOMICS = ("--target-features", "+m,-a,+c")
FEATURE_SETS = (NO_ATOMICS, ("--target-features", "+m,+a,+c"))
TIMEOUT = 600
# The probe `sawc build --freestanding` writes an object of, and its export.
OBJECT_PROBE = "word_atomics.saw"
OBJECT_EXPORT = "probe_atomics"
ELF_CLASS32 = 1
ELF_LITTLE = 1
ELF_RELOCATABLE = 1
ELF_RISCV = 243

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


def atomic_routines():
    """The `__atomic_*` routines a module can reference on a target without
    native atomics: one per atomic operation the backend lowers, at the
    word's width (spec, Profiles)."""
    return {"__atomic_%s_%d" % (op, WORD_BYTES)
            for op in ("load", "store", "fetch_add", "fetch_sub", "compare_exchange")}


def rel(path):
    return os.path.relpath(path, REPO)


def i64_problems(where, ll):
    """Each line of `ll` spelling `i64` that no `ALLOWLIST` rule admits, read
    with its metadata attachments (`, !dbg !N`) left off."""
    tags = set()
    problems = []
    function = "<module>"
    for line in ll.split("\n"):
        line = _ATTACHMENT.sub("", line)
        if _DEFINE.match(line):
            function = line.split("@", 1)[1].split("(", 1)[0] if "@" in line else line
            tags = set()
        if not _I64.search(line):
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


def emit(probe, flags):
    """The `.ll` sawc writes for `probe` at riscv32 with `flags`, or the
    refusal's text and None."""
    r = subprocess.run([build.SAWC, "build", "--emit-ll", "--freestanding", "--target", TRIPLE, "--std-root", "std"]
                       + list(flags) + [rel(probe)], cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip(), None
    return "", r.stdout


def riscv_clang():
    """(clang, skip, problem): the clang the riscv32 record beside the stages
    names, which `sawc build` compiles riscv32 objects with; else why the
    object half skips, when no clang compiles IR for riscv32; else the
    problem, when one does and the stage build wrote no record naming it."""
    record = build.runtime_manifest(TRIPLE)
    if os.path.exists(record):
        with open(record) as fh:
            for line in fh:
                if line.startswith("clang "):
                    return line[len("clang "):].strip(), "", ""
    clang, why = build.pick_clang(TRIPLE, os.environ.get("SAWC_CLANG"))
    if clang is None:
        return None, why, ""
    return None, "", "%s compiles IR for riscv32, and no clang record %s is beside the stages" % (clang, rel(record))


def nm_tool(clang):
    beside = os.path.join(os.path.dirname(clang), "llvm-nm")
    if os.path.exists(beside):
        return beside
    return shutil.which("llvm-nm") or "nm"


def undefined_symbols(clang, ll_path, obj):
    """The undefined symbols of `ll_path` compiled at -O0, or None and the
    compile's complaint."""
    r = subprocess.run([clang, "-c", "-target", TRIPLE, "-O0", "-x", "ir", ll_path, "-o", obj],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip()
    r = subprocess.run([nm_tool(clang), "-u", obj], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        return None, "nm cannot read %s: %s" % (obj, r.stderr.strip())
    return {line.split()[-1] for line in r.stdout.splitlines() if line.strip()}, ""


def symbol_problems(where, probe, flags, symbols):
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
    native = flags != NO_ATOMICS
    if base == ATOMICS_PROBE and not native and atomics != atomic_routines():
        problems.append("%s: the atomic routines referenced are %s, not exactly %s"
                        % (where, sorted(atomics), sorted(atomic_routines())))
    if native and atomics:
        problems.append("%s: with `+a` an atomic routine is still referenced: %s" % (where, sorted(atomics)))
    return problems


def sawc_object_problems(clang):
    """`sawc build --freestanding --target riscv32-unknown-none-elf` writes,
    with the record's clang, an ELF32 little-endian RISC-V relocatable object
    defining the probe's export."""
    probe = os.path.join(PROBES, OBJECT_PROBE)
    where = "riscv32 object %s" % rel(probe)
    obj = os.path.join(OUT, "sawc-object.o")
    if os.path.exists(obj):
        os.remove(obj)
    r = subprocess.run([build.SAWC, "build", "--freestanding", "--target", TRIPLE, "--std-root", "std"]
                       + list(FEATURE_SETS[1]) + [rel(probe), "-o", obj], cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
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


def check(failures, counts):
    os.makedirs(OUT, exist_ok=True)
    clang, why, problem = riscv_clang()
    if problem:
        failures.append("riscv32 IR: " + problem)
        return
    probes = sorted(glob.glob(os.path.join(PROBES, "*.saw")))
    if not probes:
        failures.append("riscv32 IR: no probe in %s" % rel(PROBES))
        return
    for probe in probes:
        stem = os.path.splitext(os.path.basename(probe))[0]
        for flags in FEATURE_SETS:
            where = "riscv32 IR %s %s" % (rel(probe), " ".join(flags))
            said, ll = emit(probe, flags)
            if ll is None:
                failures.append("%s: sawc refuses the module: %s" % (where, said[:300]))
                continue
            if stem.startswith("word_"):
                found = i64_problems(where, ll)
                failures.extend(found)
                if not found:
                    counts["riscv32 word modules with only tag carriers at i64"] = (
                        counts.get("riscv32 word modules with only tag carriers at i64", 0) + 1)
            else:
                found = wide_problems(where, ll)
                failures.extend(found)
                if not found:
                    counts["riscv32 wide modules rendering through the 64-bit renderers"] = (
                        counts.get("riscv32 wide modules rendering through the 64-bit renderers", 0) + 1)
            if clang is None:
                continue
            ll_path = os.path.join(OUT, "%s%s.ll" % (stem, "-noa" if flags == NO_ATOMICS else "-a"))
            with open(ll_path, "w") as fh:
                fh.write(ll)
            symbols, complaint = undefined_symbols(clang, ll_path, ll_path[:-3] + ".o")
            if symbols is None:
                failures.append("%s: clang refuses the module: %s" % (where, complaint[:300]))
                continue
            found = symbol_problems(where, probe, flags, symbols)
            failures.extend(found)
            if not found:
                counts["riscv32 objects with the expected routines"] = (
                    counts.get("riscv32 objects with the expected routines", 0) + 1)
    if clang is None:
        counts["riscv32 object checks skipped, no RISC-V-capable clang: " + why[:120]] = 1
        return
    found = sawc_object_problems(clang)
    failures.extend(found)
    if not found:
        counts["riscv32 objects written by sawc build"] = 1


def main():
    failures = []
    counts = {}
    check(failures, counts)
    for failure in failures:
        print(failure)
    summary = ", ".join("%d %s" % (n, key) for key, n in sorted(counts.items()))
    print("riscv32 IR: %s: %s" % ("FAIL (%d)" % len(failures) if failures else "ok", summary))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

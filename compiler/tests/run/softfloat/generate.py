#!/usr/bin/env python3
"""Regenerate vectors.txt, the soft-float vectors, from compiler-rt itself.

    python compiler/tests/run/softfloat/generate.py

Builds oracle.c with the vendored compiler-rt (compiler-rt/ beside it, whose
README names the release) for the host, with `-D__SOFTFP__` so every
routine takes compiler-rt's integer-only path, the one it takes on a target
with no floating-point unit, and each routine renamed `crt_*` so the host's own
never answers. Then writes the oracle's output to vectors.txt and prints each
routine's checksum, the numbers tests/freestanding/cases/soft_float_vectors.saw
states (`checksums`, which tools/test_freestanding_runner.py also uses).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "compiler", "tools"))

import build  # noqa: E402

COMPILER_RT = os.path.join(HERE, "compiler-rt")
VECTORS = os.path.join(HERE, "vectors.txt")
OUT = os.path.join(REPO, ".build", "softfloat-oracle")
SOURCES = ("adddf3.c", "subdf3.c", "muldf3.c", "divdf3.c", "comparedf2.c", "fixdfsi.c", "fixdfdi.c",
           "fixunsdfsi.c", "fixunsdfdi.c", "floatsidf.c", "floatdidf.c", "floatunsidf.c", "floatundidf.c",
           "fp_mode.c")

# The routines, in the order checksums() reports them: a `B` line's six
# results after its operands, then an `F` line's four, then an `I` line's four.
BINARY = ("adddf3", "subdf3", "muldf3", "divdf3", "eqdf2", "nedf2", "ltdf2", "ledf2", "gtdf2", "gedf2",
          "unorddf2")
TO_INTEGER = ("fixdfsi", "fixdfdi", "fixunsdfsi", "fixunsdfdi")
TO_FLOAT = ("floatsidf", "floatdidf", "floatunsidf", "floatundidf")
ROUTINES = BINARY + TO_INTEGER + TO_FLOAT
# The routines whose result is a `Float`: a NaN result is any NaN.
FLOAT_RESULTS = frozenset(("adddf3", "subdf3", "muldf3", "divdf3") + TO_FLOAT)

MASK = (1 << 64) - 1
QNAN = 0x7FF8_0000_0000_0000
FNV_OFFSET = 0xCBF2_9CE4_8422_2325
FNV_PRIME = 0x100_0000_01B3


def is_nan(bits):
    return (bits & 0x7FFF_FFFF_FFFF_FFFF) > 0x7FF0_0000_0000_0000


def results(line):
    """{routine: result as a 64-bit word} for one vectors.txt line: a Float
    as its bits, an integer at its width extended to 64 bits."""
    fields = line.split()
    kind, values = fields[0], fields[1:]
    if kind == "B":
        words = [int(v, 16) for v in values[2:6]] + [int(v) & MASK for v in values[6:]]
        return dict(zip(BINARY, words))
    if kind == "F":
        return dict(zip(TO_INTEGER, [int(v) & MASK for v in values[1:]]))
    if kind == "I":
        return dict(zip(TO_FLOAT, [int(v, 16) for v in values[1:]]))
    raise ValueError("vectors.txt: unknown line kind %r" % kind)


def checksums(text):
    """{routine: its checksum}: FNV-1a over 64-bit words of the routine's
    results in line order, a NaN Float result counted as the quiet NaN, since
    its bits are unspecified."""
    sums = {name: FNV_OFFSET for name in ROUTINES}
    for line in text.splitlines():
        if not line.strip():
            continue
        for name, word in results(line).items():
            if name in FLOAT_RESULTS and is_nan(word):
                word = QNAN
            sums[name] = ((sums[name] ^ word) * FNV_PRIME) & MASK
    return sums


def main():
    clang, why = build.choose_clang(build.host_triple())
    if clang is None:
        print("generate: no clang for the host: %s" % why)
        return 1
    os.makedirs(OUT, exist_ok=True)
    renames = ["-D__%s=crt_%s" % (name, name) for name in ROUTINES]
    flags = ["-O2", "-D__SOFTFP__", "-ffp-contract=off", "-fno-builtin", "-I", COMPILER_RT] + renames
    objects = []
    for name in SOURCES:
        obj = os.path.join(OUT, name[:-2] + ".o")
        subprocess.run([clang, "-c"] + flags + [os.path.join(COMPILER_RT, name), "-o", obj], check=True)
        objects.append(obj)
    exe = os.path.join(OUT, "oracle")
    subprocess.run([clang, "-O2", os.path.join(HERE, "oracle.c")] + objects + ["-o", exe], check=True)
    text = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
    with open(VECTORS, "w") as fh:
        fh.write(text)
    print("generate: %s: %d lines" % (os.path.relpath(VECTORS, REPO), len(text.splitlines())))
    for name, value in checksums(text).items():
        print("    %-11s 0x%016X" % (name, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())

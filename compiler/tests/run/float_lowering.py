#!/usr/bin/env python3
"""The float-instruction check: where std.numeric's Float methods are their
LLVM intrinsic, and that no target's object calls a C math library for one.

    python compiler/tests/run/float_lowering.py     # the check alone

`run_lane.run()` calls `check()`. For each cell of the target funnel's
matrix (`target_float_instruction`, compiler/target/src/layout.saw), the
seven methods of `lowering/float_methods.saw` are emitted with `sawc build -c
--emit-ll` for that target and features, and:

- each method's definition is its intrinsic exactly where `CELLS` says, and
  its Saw body everywhere else (SL-944);
- the module, compiled at -O0 and at -O2 with the clang `build.choose_clang`
  picks for the target, references no C math library function and no
  `llvm.*` name, so a cell marked as an instruction whose intrinsic lowers to
  a libcall, or that the clang does not know, fails here;
- two injected modules, an intrinsic with no instruction behind it and one
  no LLVM knows, are each reported, so the refusal itself is pinned.

A target no clang here can compile for is skipped, and says why.
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

PROGRAM = os.path.join(HERE, "lowering", "float_methods.saw")
OUT = os.path.join(REPO, ".build", "float-lowering")
TIMEOUT = 600
METHODS = ("abs", "floor", "ceil", "round", "sqrt", "min", "max")
INTRINSICS = {"abs": "llvm.fabs.f64", "floor": "llvm.floor.f64", "ceil": "llvm.ceil.f64",
              "round": "llvm.round.f64", "sqrt": "llvm.sqrt.f64", "min": "llvm.minimumnum.f64",
              "max": "llvm.maximumnum.f64"}

# (triple, `--target-features` or None for the default, freestanding, the
# seven methods' answers in METHODS order: `i` the intrinsic, `s` the Saw
# body). The rows are compiler/target/tests/float_instructions.saw's.
CELLS = (
    ("arm64-apple-darwin", None, False, "iiiiiss"),
    ("aarch64-unknown-linux-gnu", None, False, "iiiiiss"),
    ("aarch64-unknown-none-elf", None, True, "issssss"),
    ("aarch64-unknown-none-elf", "+neon,+fp-armv8", True, "iiiiiss"),
    ("riscv32-unknown-none-elf", "+m,+a,+c", True, "issssss"),
    ("riscv32-unknown-none-elf", "+m,+a,+c,+f,+d", True, "isssiss"),
    ("riscv32-unknown-none-elf", "+m,+a,+c,+f,+d,+zfa", True, "iiiiiss"),
    ("x86_64-unknown-linux-gnu", None, False, "isssiss"),
    ("x86_64-unknown-linux-gnu", "+sse4.1", False, "iiiiiss"),
)

# What a math intrinsic lowers to when the target has no instruction for it:
# each C99 and IEEE 754-2019 function of the seven jobs, at every width.
_LIBM_BASES = ("fabs", "floor", "ceil", "round", "trunc", "rint", "nearbyint", "roundeven", "sqrt", "fmin", "fmax",
               "fminimum", "fmaximum", "fminimum_num", "fmaximum_num")
LIBM = frozenset(base + width for base in _LIBM_BASES for width in ("", "f", "l"))

_DEFINE = re.compile(r'^define [^@]*@"saw std\.numeric\.Float\.(\w+)\(')


def nm_tool(clang):
    beside = os.path.join(os.path.dirname(clang), "llvm-nm")
    if os.path.exists(beside):
        return beside
    return shutil.which("llvm-nm") or "nm"


def definitions(text):
    """Each std.numeric Float method's body lines in `text`, by name."""
    out = {}
    current = None
    for line in text.splitlines():
        found = _DEFINE.match(line)
        if found:
            current = found.group(1)
            out[current] = []
        elif line == "}":
            current = None
        elif current is not None:
            out[current].append(line)
    return out


def label(triple, features):
    return "%s [%s]" % (triple, features if features is not None else "default")


def check_cell(failures, counts, triple, features, freestanding, want):
    where = "run float lowering %s" % label(triple, features)
    cmd = [build.SAWC, "build", "-c", "--emit-ll", "-g0", "--std-root", "std", "--target", triple]
    if freestanding:
        cmd.append("--freestanding")
    if features is not None:
        cmd += ["--target-features", features]
    r = subprocess.run(cmd + [os.path.relpath(PROGRAM, REPO)], cwd=REPO, capture_output=True, text=True,
                       timeout=TIMEOUT)
    if r.returncode != 0:
        failures.append("%s: sawc writes no module: %s" % (where, (r.stdout + r.stderr).strip()[:300]))
        return
    bodies = definitions(r.stdout)
    got = ""
    for method in METHODS:
        body = bodies.get(method)
        if body is None:
            failures.append("%s: the module defines no `Float.%s`" % (where, method))
            return
        calls = [line for line in body if " call " in line]
        intrinsic = len(calls) == 1 and ("@%s(" % INTRINSICS[method]) in calls[0]
        got += "i" if intrinsic else "s"
    if got != want:
        failures.append("%s: the methods (%s) are %s, not %s (i: the intrinsic, s: the Saw body)"
                        % (where, " ".join(METHODS), got, want))
        return
    counts["run float lowering cells emitted"] = counts.get("run float lowering cells emitted", 0) + 1
    clang, why = build.choose_clang(triple)
    if clang is None:
        counts["run float lowering cells skipped, no clang"] = \
            counts.get("run float lowering cells skipped, no clang", 0) + 1
        print("float lowering: %s not compiled: %s" % (label(triple, features), why))
        return
    os.makedirs(OUT, exist_ok=True)
    stem = re.sub(r"[^\w]+", "_", label(triple, features))
    ll = os.path.join(OUT, stem + ".ll")
    with open(ll, "w") as fh:
        fh.write(r.stdout)
    for speed in ("-O0", "-O2"):
        problem, named = libm_calls(clang, triple, ll, os.path.join(OUT, stem + speed + ".o"), speed)
        if problem:
            failures.append("%s %s: %s" % (where, speed, problem))
        elif named:
            failures.append("%s %s: the object leaves %s undefined, a C math library function or an intrinsic "
                            "this clang does not know: an intrinsic the cell says is an instruction is not one "
                            "here" % (where, speed, ", ".join(named)))
        else:
            counts["run float lowering objects with no libm call"] = \
                counts.get("run float lowering objects with no libm call", 0) + 1


def libm_calls(clang, triple, ll, obj, speed):
    """(why the module at `ll` could not be read, or None; the C math library
    functions and `llvm.*` names its object for `triple` at `speed` leaves
    undefined). A clang that does not know an intrinsic compiles a call to
    it as a call to an external function of that name."""
    c = subprocess.run([clang, "-c", "-target", build.clang_triple(triple), speed, "-x", "ir", ll, "-o", obj],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if c.returncode != 0:
        return "%s does not compile the module: %s" % (clang, (c.stdout + c.stderr).strip()[:300]), []
    n = subprocess.run([nm_tool(clang), "-u", obj], capture_output=True, text=True, timeout=TIMEOUT)
    if n.returncode != 0:
        return "nm cannot read %s: %s" % (obj, n.stderr.strip()[:300]), []
    undefined = {line.split()[-1] for line in n.stdout.splitlines() if line.strip()}
    # Mach-O spells a C symbol with a leading underscore.
    names = {s[1:] if s.startswith("_") else s for s in undefined}
    return None, sorted(s for s in names if s in LIBM or s.startswith("llvm."))


# Two modules whose one function calls an intrinsic riscv32's base ISA has no
# instruction for, and what its object must be reported as leaving undefined:
# `llvm.floor.f64` lowers to a libcall, and a name no LLVM knows compiles to a
# call of that name, as `llvm.minimumnum.f64` does under clang 19.
_INJECTIONS = (("llvm.floor.f64", "floor"), ("llvm.saw.unknown.f64", "llvm.saw.unknown.f64"))
_INJECTED = """target triple = "riscv32-unknown-none-elf"

declare double @%s(double)

define double @injected(double %%a) {
  %%r = call double @%s(double %%a)
  ret double %%r
}
"""


def check_sees_a_libcall(failures, counts):
    """The check catches what it is for: each of `_INJECTIONS`, compiled for
    riscv32's base ISA, is reported by the name its object leaves undefined."""
    triple = "riscv32-unknown-none-elf"
    clang, why = build.choose_clang(triple)
    if clang is None:
        print("float lowering: the libcall injections are not compiled: %s" % why)
        return
    os.makedirs(OUT, exist_ok=True)
    for intrinsic, reported in _INJECTIONS:
        stem = os.path.join(OUT, "injected_" + re.sub(r"[^\w]+", "_", intrinsic))
        with open(stem + ".ll", "w") as fh:
            fh.write(_INJECTED % (intrinsic, intrinsic))
        problem, named = libm_calls(clang, triple, stem + ".ll", stem + ".o", "-O2")
        if problem or named != [reported]:
            failures.append("run float lowering: an injected `%s` on riscv32 with no `D` is not reported as "
                            "leaving `%s` undefined: %s" % (intrinsic, reported, problem or named))
            continue
        counts["run float lowering libcall injections caught"] = \
            counts.get("run float lowering libcall injections caught", 0) + 1


def check(failures, counts):
    for triple, features, freestanding, want in CELLS:
        check_cell(failures, counts, triple, features, freestanding, want)
    check_sees_a_libcall(failures, counts)


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

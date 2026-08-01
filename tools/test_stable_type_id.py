#!/usr/bin/env python3
"""Stable erased-error type-id acceptance test (design 87 item 2).

Design 72's downcasting type-id was a per-compilation MONOTONIC COUNTER memoized
by mangled name — correct within one whole-program build, but ORDER-DEPENDENT:
the same concrete type would get a DIFFERENT id in a build where it (or its
companion types) is declared in a different position. Two separately-compiled
units would therefore disagree on `is<T>()`/`take<T>()`.

Design 87 replaces it with a deterministic FNV-1a hash of the mangled type name,
so a type's id is a pure function of its NAME — identical in EVERY compilation.

This IR-level check (the .saw runner asserts behavior, not IR constants) compiles
two programs that both conform `Circle: Shape` but declare it in DIFFERENT
positions among DIFFERENT companion types, extracts the `type_id` baked into
`Circle`'s vtable from the unoptimized IR, and asserts:

  1. the two ids are IDENTICAL (order-independence — the old counter would give
     Circle id 1 in program A but id 3 in program B, and this test would fail);
  2. the id equals the FNV-1a 64-bit hash of Circle's mangled name (pins the
     scheme, so an accidental change to the hashing is caught).

Run from the repo root:  ./.venv/bin/python tools/test_stable_type_id.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SAWC = os.path.join(REPO, "sawc", "sawc.py")

# Circle declared FIRST, with one companion type.
PROGRAM_A = """\
trait Shape { func area(&self) -> Int }
struct Circle { r: Int }
struct Square { s: Int }
extension Circle: Shape { func area(&self) -> Int { self.r } }
extension Square: Shape { func area(&self) -> Int { self.s } }

func main() {
    let b = Box<any Shape>.make(Circle(r: 7))
    if b.is<Circle>() { print(1) }
    let b2 = Box<any Shape>.make(Square(s: 5))
    if b2.is<Square>() { print(2) }
}
"""

# Circle declared LAST, after two DIFFERENT companion types — a build order in
# which the old monotonic counter would assign Circle a different id than in A.
PROGRAM_B = """\
trait Shape { func area(&self) -> Int }
struct Triangle { t: Int }
struct Pentagon { p: Int }
struct Circle { r: Int }
extension Triangle: Shape { func area(&self) -> Int { self.t } }
extension Pentagon: Shape { func area(&self) -> Int { self.p } }
extension Circle: Shape { func area(&self) -> Int { self.r } }

func main() {
    let t = Box<any Shape>.make(Triangle(t: 1))
    if t.is<Triangle>() { print(1) }
    let p = Box<any Shape>.make(Pentagon(p: 2))
    if p.is<Pentagon>() { print(2) }
    let b = Box<any Shape>.make(Circle(r: 7))
    if b.is<Circle>() { print(3) }
}
"""

# FNV-1a 64-bit — must match sawc/codegen/existentials.py._type_id_for.
_FNV64_OFFSET_BASIS = 14695981039346656037
_FNV64_PRIME = 1099511628211
_FNV64_MASK = (1 << 64) - 1


def fnv1a64(s: str) -> int:
    h = _FNV64_OFFSET_BASIS
    for byte in s.encode("utf-8"):
        h = ((h ^ byte) * _FNV64_PRIME) & _FNV64_MASK
    return h


def emit_ir(program: str, tmp: str, name: str) -> str:
    src = os.path.join(tmp, f"{name}.saw")
    with open(src, "w") as f:
        f.write(program)
    out = os.path.join(tmp, name)
    r = subprocess.run(
        [PY, SAWC, src, "--emit-ir", "-O0", "-o", out],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: compiling {name}:\n{r.stdout}{r.stderr}")
        sys.exit(1)
    with open(out + ".ll") as f:
        return f.read()


def circle_type_id(ir: str, name: str) -> int:
    """The type_id baked into Circle's vtable: slot layout is
    `{ dtor*, i64 size, i64 align, i64 type_id, methods... }`, so the THIRD i64
    literal on the vtable global line is the id."""
    m = re.search(r'@"__vtable\$Circle\$Shape"\s*=\s*[^\n]*', ir)
    if not m:
        print(f"FAIL: no Circle vtable global in {name}'s IR")
        sys.exit(1)
    ints = re.findall(r'i64 (\d+)', m.group(0))
    if len(ints) < 3:
        print(f"FAIL: Circle vtable in {name} has too few i64 fields: {m.group(0)}")
        sys.exit(1)
    return int(ints[2])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        ir_a = emit_ir(PROGRAM_A, tmp, "prog_a")
        ir_b = emit_ir(PROGRAM_B, tmp, "prog_b")
        id_a = circle_type_id(ir_a, "prog_a")
        id_b = circle_type_id(ir_b, "prog_b")

    expected = fnv1a64("Circle")
    ok = True
    if id_a != id_b:
        print(f"FAIL: Circle's type-id is NOT stable across compiles: "
              f"program A = {id_a}, program B = {id_b} (order-dependent)")
        ok = False
    if id_a != expected:
        print(f"FAIL: Circle's type-id {id_a} != FNV-1a(\"Circle\") {expected} "
              f"(scheme drifted)")
        ok = False
    if ok:
        print(f"PASS: Circle type-id stable across two compiles = {id_a} "
              f"(= FNV-1a of the mangled name)")
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()

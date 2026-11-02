#!/usr/bin/env python3
"""Writes `float_methods.tsv`, the bit-pattern vectors of std.numeric's Float methods.

  float_methods_vectors.py            rewrite the file
  float_methods_vectors.py --check    exit 1 when the file differs from a rewrite

Each expected result is the host libm's (macOS arm64, called through ctypes),
held to an independent derivation of SL-944's rules first. The two differ only
where libm breaks the ruling, `fmin`/`fmax` beside a signalling NaN, and there
the ruling's result is written with a note. `probes/float_methods_vectors.saw`
checks every line against std at -O0 and -O2.
"""
import ctypes
import ctypes.util
import math
import os
import platform
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS = os.path.join(HERE, "float_methods.tsv")

SIGN = 0x8000_0000_0000_0000
EXPONENT = 0x7FF0_0000_0000_0000
QUIET = 0x0008_0000_0000_0000
MASK = (1 << 64) - 1
UNARY = ["abs", "floor", "ceil", "round", "sqrt"]
BINARY = ["min", "max"]
DRAWS = 2000
PAIR_DRAWS = 2000
HARD_ROOTS = 500
LIBM_NAME = {"abs": "fabs", "floor": "floor", "ceil": "ceil", "round": "round", "sqrt": "sqrt",
             "min": "fmin", "max": "fmax"}


def to_float(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def to_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def is_nan(bits):
    return (bits & ~SIGN & MASK) > EXPONENT


def is_snan(bits):
    return is_nan(bits) and bits & QUIET == 0


class SplitMix:
    """splitmix64: a fixed seed gives one sequence on every host."""

    def __init__(self, seed):
        self.state = seed

    def next(self):
        self.state = (self.state + 0x9E37_79B9_7F4A_7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58_476D_1CE4_E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D0_49BB_1331_11EB) & MASK
        return z ^ (z >> 31)


def edges():
    """The survey's 166 patterns: the specials, both ends of each binade
    class, the neighbours of 2^52 and 2^53, and every half up to 8.5."""
    out = [0x0000_0000_0000_0000, 0x8000_0000_0000_0000, 0x7FF0_0000_0000_0000, 0xFFF0_0000_0000_0000,
           0x7FF8_0000_0000_0000, 0xFFF8_0000_0000_0000, 0x7FF8_0000_0000_0123, 0xFFF8_0000_0000_0456,
           0x7FF0_0000_0000_0001, 0xFFF4_0000_0000_0789, 0x7FF7_FFFF_FFFF_FFFF, 0x7FFF_FFFF_FFFF_FFFF,
           0x0000_0000_0000_0001, 0x8000_0000_0000_0001, 0x000F_FFFF_FFFF_FFFF, 0x800F_FFFF_FFFF_FFFF,
           0x0010_0000_0000_0000, 0x8010_0000_0000_0000, 0x3FE0_0000_0000_0000, 0xBFE0_0000_0000_0000,
           0x3FF8_0000_0000_0000, 0xBFF8_0000_0000_0000, 0x4004_0000_0000_0000, 0xC004_0000_0000_0000,
           0x7FEF_FFFF_FFFF_FFFF, 0xFFEF_FFFF_FFFF_FFFF]
    for b in (0x432F_FFFF_FFFF_FFFE, 0x4330_0000_0000_0000, 0x4330_0000_0000_0001,
              0x433F_FFFF_FFFF_FFFF, 0x4340_0000_0000_0000, 0x4340_0000_0000_0001):
        out += [b, b | SIGN, b - 1, b + 1, (b - 1) | SIGN, (b + 1) | SIGN]
    out += [0x3FDF_FFFF_FFFF_FFFF, 0xBFDF_FFFF_FFFF_FFFF]
    for k in range(1, 18):
        h = to_bits(0.5 * k)
        out += [h, h - 1, h + 1, h | SIGN, (h - 1) | SIGN, (h + 1) | SIGN]
    return out


def draw(rng, mode):
    """Mode 0..3: a raw pattern; the exponent band 2^-4..2^59, where the
    rounding methods do their work; a subnormal; a half k/2 below 2^20,
    signed and nudged one pattern either way."""
    raw = rng.next()
    if mode == 0:
        return raw
    if mode == 1:
        e = 1023 - 4 + (raw >> 58)
        return (raw & 0x800F_FFFF_FFFF_FFFF) | (e << 52)
    if mode == 2:
        return raw & 0x800F_FFFF_FFFF_FFFF
    b = to_bits(0.5 * (raw >> 43))
    if raw & 1:
        b |= SIGN
    if raw & 2 and b not in (0, SIGN):
        b -= 1
    elif raw & 4:
        b += 1
    return b


def sqrt_hard_cases():
    """Inputs whose root lies within an ulp of a rounding midpoint: for a
    53-bit r, (2r + 1)^2 truncated to 53 bits and one ulp above it, scaled by
    an even power of two."""
    rng = random.Random(944)
    cases = []
    for _ in range(HARD_ROOTS):
        r = rng.randrange(1 << 52, 1 << 53)
        n = 4 * r * r + 4 * r + 1
        mant, e = (n >> 54, 0) if n < (1 << 107) else (n >> 55, 1)
        shift = 2 * rng.randrange(-500, 500)
        for m in (mant, mant + 1):
            field = 1023 + e + shift
            if m < (1 << 53) and 1 <= field <= 2046:
                cases.append((field << 52) | (m - (1 << 52)))
    return cases


def integral(x, toward):
    """x rounded to an integral value by `toward` (a function of the exact
    value), keeping the sign of a zero result."""
    if not math.isfinite(x) or x == 0.0:
        return x
    r = float(toward(x))
    return math.copysign(r, x) if r == 0.0 else r


def round_half_away(x):
    a = abs(x)
    whole = math.floor(a)
    up = whole + 1 if a - whole >= 0.5 else whole
    return up if x > 0 else -up


def correct_sqrt(x):
    """The correctly rounded root, by an integer square root: no float
    arithmetic touches the answer."""
    if math.isnan(x) or x == 0.0 or x == math.inf:
        return x
    if x < 0.0:
        return math.nan
    m, e = math.frexp(x)
    mant = int(m * (1 << 53))
    e -= 53
    if e % 2:
        mant <<= 1
        e -= 1
    scaled = mant << 120
    s = math.isqrt(scaled)
    exact = s * s == scaled
    shift = s.bit_length() - 53
    q = s >> shift
    rest = s & ((1 << shift) - 1)
    half = 1 << (shift - 1)
    if rest > half or (rest == half and not exact) or (rest == half and exact and q & 1):
        q += 1
    return math.ldexp(q, (e - 120) // 2 + shift)


def order_key(b):
    """Unsigned order of the keys is numeric order, -0 just below +0."""
    return (~b & MASK) if b & SIGN else (b | SIGN)


def ruled(method, a, b=None):
    """SL-944's result for `method` on patterns `a` (and `b`), as bits, or
    None where the ruling leaves the bits unspecified (a NaN result)."""
    if method == "abs":
        return a & ~SIGN & MASK
    if method in BINARY:
        if is_nan(a) and is_nan(b):
            return None
        if is_nan(a):
            return b
        if is_nan(b):
            return a
        smaller = order_key(a) <= order_key(b)
        return a if smaller == (method == "min") else b
    x = to_float(a)
    if method == "floor":
        r = integral(x, math.floor)
    elif method == "ceil":
        r = integral(x, math.ceil)
    elif method == "round":
        r = integral(x, round_half_away)
    else:
        r = correct_sqrt(x)
    return None if math.isnan(r) else to_bits(r)


def libm():
    path = ctypes.util.find_library("m")
    lib = ctypes.CDLL(path)
    functions = {}
    for method, name in LIBM_NAME.items():
        f = getattr(lib, name)
        f.restype = ctypes.c_double
        f.argtypes = [ctypes.c_double] * (2 if method in BINARY else 1)
        functions[method] = f
    return functions


def cases():
    """(method, operands) in file order."""
    base = edges()
    out = []
    for i, method in enumerate(UNARY):
        operands = list(base)
        rng = SplitMix(0x5EED_0000_0000_0944 + i)
        for k in range(DRAWS):
            operands.append(draw(rng, k % 4))
        if method == "sqrt":
            operands += sqrt_hard_cases()
        out += [(method, (a,)) for a in operands]
    specials = base[:26]
    partners = [0x0000_0000_0000_0000, 0x8000_0000_0000_0000, 0x3FF0_0000_0000_0000,
                0x7FF8_0000_0000_0000, 0x7FF0_0000_0000_0001]
    for i, method in enumerate(BINARY):
        pairs = [(a, b) for a in specials for b in specials]
        pairs += [(a, a) for a in base] + [(a, a ^ SIGN) for a in base]
        pairs += [(a, p) for a in base for p in partners] + [(p, a) for a in base for p in partners]
        rng = SplitMix(0x5EED_0000_0000_0A44 + i)
        for k in range(PAIR_DRAWS):
            a = draw(rng, k % 4)
            b = a ^ SIGN if k % 8 == 0 else a if k % 8 == 4 else draw(rng, k % 4)
            pairs.append((a, b))
        out += [(method, p) for p in pairs]
    return out


def render():
    """The file's text, or a SystemExit naming the first case where this
    host's libm breaks a rule the ruling does not override."""
    functions = libm()
    lines = ["# SL-944: std.numeric's Float methods, as IEEE 754 bit patterns.",
             "# Generated by float_methods_vectors.py from %s %s's libm; do not hand-edit."
             % (platform.system(), platform.machine()),
             "# METHOD<TAB>INPUT[<TAB>OTHER]<TAB>EXPECTED[<TAB>NOTE], each pattern 16 hex digits.",
             "# An EXPECTED NaN is checked as a NaN only: a NaN result's sign and payload are",
             "# unspecified. abs is exact, NaN included."]
    for method, operands in cases():
        got = to_bits(functions[method](*[to_float(o) for o in operands]))
        want = ruled(method, *operands)
        note = ""
        if want is None:
            if not is_nan(got):
                raise SystemExit("%s%s: libm gives %016X where the ruling gives a NaN"
                                 % (method, tuple("%016X" % o for o in operands), got))
            want = got
        elif want != got:
            if method in BINARY and any(is_snan(o) for o in operands):
                note = "\truling: libm gives %016X" % got
            else:
                raise SystemExit("%s%s: libm gives %016X where the ruling gives %016X"
                                 % (method, tuple("%016X" % o for o in operands), got, want))
        lines.append("\t".join([method] + ["%016X" % o for o in operands] + ["%016X" % want]) + note)
    return "\n".join(lines) + "\n"


def main():
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("float_methods_vectors.py: the vectors are macOS arm64's libm; this is %s %s"
                         % (platform.system(), platform.machine()))
    text = render()
    if "--check" in sys.argv[1:]:
        with open(VECTORS) as f:
            if f.read() != text:
                raise SystemExit("float_methods_vectors.py: %s differs from a rewrite" % VECTORS)
        print("float_methods_vectors.py: %s matches" % VECTORS)
        return
    with open(VECTORS, "w") as f:
        f.write(text)
    print("wrote %d cases to %s" % (text.count("\n") - 5, VECTORS))


main()

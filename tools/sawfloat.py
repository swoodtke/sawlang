#!/usr/bin/env python3
"""The Python half of the design-253 Float<->text contract.

`sawc/std/float.saw` holds Saw's shortest-round-trip formatter and its
correctly-rounded parser. This tool holds the ORACLE for both: CPython's own
`repr`/`float()` are correctly-rounded shortest-round-trip conversions, so the
golden vectors under `tests/float_vectors/` are two independent implementations
checked against each other rather than one implementation checked against
itself.

  tools/sawfloat.py gen       rewrite the golden vectors from the case table
  tools/sawfloat.py verify    check the committed vectors against CPython

`verify` is the gate (the `floatvectors` battery lane runs it, and
`examples/float_text_vectors.saw` runs the Saw side over the same files). It
regenerates every row from the case table and byte-compares — so a hand-edited
vector, a stale file, or a generator change nobody re-ran all fail here.

Determinism, per house rules: the PRNG is seeded with a fixed constant, every
set is emitted in sorted order, and nothing reads the clock. Running `gen`
twice produces byte-identical files.

## The files

`tests/float_vectors/shortest.tsv` — one row per double, TAB-separated:

    <16 hex digits of the IEEE 754 bit pattern>  <the shortest round-trip text>

Each row is BOTH directions of one value, which is what makes it a round-trip
vector rather than two half-tests: formatting the bits must produce exactly
that text, and parsing that text must produce exactly those bits.

`tests/float_vectors/parse.tsv` — parse-only rows, TAB-separated:

    <input text>  <16 hex digits>      the input parses to exactly these bits
    <input text>  reject               the input is not a number at all

These are the spellings a formatter never emits but a parser must read
(exponent forms, leading zeros, `+`, huge/tiny exponents that saturate to
infinity or zero, 800-digit inputs) plus the rejections.

## The text format (`shortest.tsv`'s second column)

Saw's `Float.to_string` produces exactly what CPython's `repr` produces, and
that is a deliberate choice rather than an accident of the oracle: repr is the
shortest string that round-trips, and its layout rules are the ones a reader
expects. Given the shortest digit string `d` and `decpt` (the value is
`0.d * 10**decpt`):

  * zero renders `0.0` / `-0.0`;
  * `decpt <= -4 or decpt > 16` renders in exponent form — one leading digit,
    a `.` and the rest only if there IS a rest, then `e`, a mandatory sign, and
    at least two exponent digits (`1e+16`, `5e-324`, `1.5e-07`);
  * otherwise fixed form, with `.0` appended when the digits run out at or
    before the point (`100.0`), and a `0.` + zero padding when the point is at
    or left of the first digit (`0.001`).

`_render` below is that rule, and `verify --rule` re-checks it against
`repr()` over the whole corpus, so the rule the Saw code implements is never
taken on trust.

Non-finite values are `nan` / `inf` / `-inf` (Saw-facing text, NOT JSON — see
`sawc/std/JSON.md` for what JSON does with them). They are in
`shortest.tsv` too: a NaN's bit pattern is not unique, so the row uses the
canonical quiet NaN and `parse.tsv` carries the other spellings.
"""

import argparse
import decimal
import math
import os
import random
import re
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DIR = os.path.join(REPO, "tests", "float_vectors")

SEED = 253
SHORTEST = "shortest.tsv"
PARSE = "parse.tsv"

QUIET_NAN = 0x7FF8000000000000
POS_INF = 0x7FF0000000000000
NEG_INF = 0xFFF0000000000000


# ---------------------------------------------------------------------------
# bits <-> double


def bits_of(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def double_of(b: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", b & 0xFFFFFFFFFFFFFFFF))[0]


# ---------------------------------------------------------------------------
# The text format


def _shortest_digits(x: float):
    """`(digits, decpt)` with `abs(x) == 0.<digits> * 10**decpt`.

    Read out of `repr` itself, which is where the shortest-ness comes from:
    this tool does not implement a shortest algorithm, it reads CPython's.
    """
    r = repr(abs(x))
    mant, _, exp = r.partition("e")
    exp = int(exp) if exp else 0
    ip, _, fp = mant.partition(".")
    raw = ip + fp
    stripped = raw.lstrip("0")
    lead_zeros = len(raw) - len(stripped)
    decpt = len(ip) + exp - lead_zeros
    digits = stripped.rstrip("0")
    if not digits:
        return "0", 1
    return digits, decpt


def _render(neg: bool, digits: str, decpt: int) -> str:
    sign = "-" if neg else ""
    if digits == "0":
        return sign + "0.0"
    if decpt <= -4 or decpt > 16:
        e = decpt - 1
        tail = digits[1:]
        mant = digits[0] + ("." + tail if tail else "")
        return "%s%se%s%02d" % (sign, mant, "+" if e >= 0 else "-", abs(e))
    if decpt <= 0:
        return sign + "0." + "0" * (-decpt) + digits
    if decpt >= len(digits):
        return sign + digits + "0" * (decpt - len(digits)) + ".0"
    return sign + digits[:decpt] + "." + digits[decpt:]


# ---------------------------------------------------------------------------
# Saw's own accepted grammar
#
# CPython's `float()` is the oracle for the VALUE of an accepted input, never
# for WHICH inputs are accepted: it takes leading and trailing whitespace,
# `infinity`, any casing of `NaN`, and PEP-515 underscores, none of which
# `String.to_float` does. So the grammar is written out here too, as a second
# implementation of the one `sawc/std/float.saw` documents:
#
#   float := sign? ( digits ('.' digits?)? | '.' digits ) ([eE] sign? digits)?
#          | sign? ('nan' | 'inf')
#
# Whole-string, no trimming, ASCII only — the same contract `to_int`/`to_uint`
# already keep.
_SAW_NUMBER = re.compile(
    r"\A[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_SAW_NONFINITE = re.compile(r"\A[+-]?(?:nan|inf)\Z")


def saw_accepts(text: str) -> bool:
    return bool(_SAW_NUMBER.match(text) or _SAW_NONFINITE.match(text))


def text_of(x: float) -> str:
    """The text Saw's `Float.to_string` must produce for `x`."""
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "-inf" if x < 0 else "inf"
    if x == 0.0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    digits, decpt = _shortest_digits(x)
    return _render(x < 0, digits, decpt)


# ---------------------------------------------------------------------------
# The case table


def _boundary_bits():
    """Every value a Float<->text implementation gets wrong first."""
    vals = [
        0.0, -0.0, 1.0, -1.0, 2.0, 0.5, 0.25, 10.0, 100.0, 1000.0,
        # the classic hard inputs
        5e-324,                      # min subnormal
        1e-323, 2e-323, 5e-323,
        2.2250738585072011e-308,     # the "PHP hang" value, just under min normal
        2.2250738585072012e-308,
        2.2250738585072013e-308,
        2.2250738585072014e-308,     # min normal
        1.7976931348623157e308,      # max finite
        1.7976931348623155e308,
        8.98846567431158e307,        # 2**1023
        4.9406564584124654e-324,
        0.1, 0.2, 0.3, 0.7, 0.1 + 0.2,
        1.0 / 3.0, 2.0 / 3.0, 1.0 / 7.0,
        3.141592653589793, 2.718281828459045,
        # the fixed/exponent switch, from both sides
        1e15, 1e16, 1e17, 1e-4, 1e-5,
        9999999999999998.0, 10000000000000002.0,
        # 2**53 and its neighbours: where integers stop being exact
        9007199254740992.0, 9007199254740994.0, 9007199254740991.0,
        4503599627370496.0, 4503599627370497.0,
        123456789012345678.0, 1234567890123456789.0,
        # values whose shortest form needs all 17 digits
        9.999999999999999e22, 1.7976931348623157e308,
        5.960464477539063e-8, 1.2345678901234567e-300,
        # Vern Paxson's / David Gay's stress values
        8.511030020275582e-1, 5.667626490120696e-1,
        6.9741824662999875e-2, 5.0216813883634694e-2,
        # exact powers of ten across the range
    ]
    for e in range(-323, 309):
        try:
            v = float("1e%d" % e)
        except (OverflowError, ValueError):
            continue
        if math.isinf(v):
            continue
        vals.append(v)
    # exact powers of two across the whole range, plus their neighbours
    for e in range(-1074, 1024):
        v = math.ldexp(1.0, e)
        if v == 0.0 or math.isinf(v):
            continue
        if e % 37 == 0 or abs(e) < 6 or e in (-1074, -1073, -1022, -1021, 1023, 1022):
            vals.append(v)
            vals.append(math.nextafter(v, math.inf))
            vals.append(math.nextafter(v, -math.inf))
    # neighbours of the powers of ten: the shortest algorithm's interval work
    for e in (-300, -100, -22, -10, -1, 0, 1, 10, 22, 100, 300):
        v = float("1e%d" % e)
        vals.append(math.nextafter(v, math.inf))
        vals.append(math.nextafter(v, -math.inf))
    bits = {bits_of(v) for v in vals}
    bits.update({QUIET_NAN, POS_INF, NEG_INF})
    return bits


def _random_bits(rng):
    """PRNG-seeded round-trip samples: uniform bit patterns (which land mostly
    in the extreme exponents), values near 1.0, and subnormals — three
    populations, because uniform-over-bits alone never produces a value a
    program would actually print."""
    out = set()
    while len(out) < 1200:
        b = rng.getrandbits(64)
        v = double_of(b)
        if math.isnan(v) or math.isinf(v):
            continue
        out.add(bits_of(v))          # normalizes nothing; keeps -0.0 distinct
    while len(out) < 1800:
        v = rng.uniform(-1e6, 1e6) * (10.0 ** rng.randint(-20, 20))
        if math.isinf(v):
            continue
        out.add(bits_of(v))
    while len(out) < 2000:
        # subnormals: a random mantissa with a zero exponent field
        out.add(rng.getrandbits(52) | (rng.getrandbits(1) << 63))
    return out


def shortest_rows():
    rng = random.Random(SEED)
    bits = _boundary_bits() | _random_bits(rng)
    rows = []
    for b in sorted(bits):
        rows.append((b, text_of(double_of(b))))
    return rows


def parse_rows():
    """Parse-only inputs: spellings the formatter never emits, and rejections."""
    rows = []

    def ok(text):
        rows.append((text, "%016X" % bits_of(float(text))))

    def rejects(text):
        rows.append((text, "reject"))

    # exponent spellings the formatter does not use
    for t in ["1e2", "1E2", "1e+2", "1e-2", "1.5e3", "-1.5E-3", "0e0", "0E10",
              "1e00", "1e000000000000000000005", "3e-5", "+1.5", "+2e3",
              "1.", "0.1", ".5", "+.5", "-.5", "00.5", "0000001", "1e-0",
              "12345678901234567890", "0.000000000000000000001",
              "1.0000000000000000000000000000000000000001",
              "2.2250738585072011e-308", "2.2250738585072012e-308",
              "7.2057594037927933e16", "9007199254740993",
              "1.7976931348623158e308", "0.5000000000000000277555756156289135",
              "1.000000000000000055511151231257827021181583404541015625"]:
        ok(t)
    # halfway cases: exactly representable ties, which round to even
    ok("9007199254740993.0")
    ok("9007199254740995.0")
    ok("0.500000000000000027755575615628913510590791702270507812500000")
    # overflow saturates to infinity, underflow to zero, with the sign kept
    for t in ["1e309", "-1e309", "1e400", "1e999999999", "-1e999999999",
              "1e-324", "1e-400", "-1e-400", "1e-999999999", "2.5e-324",
              "4.9e-324", "2.4e-324"]:
        ok(t)
    # a very long input: 800 digits, which is past every fast path
    long_digits = "1." + "9" * 800
    ok(long_digits)
    ok("0." + "0" * 320 + "5")
    ok("1" + "0" * 400 + "e-400")
    # --- inputs that FORCE the exact path -----------------------------------
    #
    # Eisel-Lemire declines on about one input in a hundred and fifty, so a
    # corpus of ordinary spellings exercises the exact decimal path barely at
    # all — and that path is where a rounding rule can be subtly wrong for
    # years. These rows go straight to it, three per sampled double:
    #
    #   * the double's OWN exact decimal expansion, which for a subnormal runs
    #     to some 750 digits and must read back as the value it expands;
    #   * the exact midpoint between it and its successor, which is a TIE and
    #     must round to even;
    #   * that midpoint with one more digit on the end, which is just past the
    #     tie and must round up whatever the parity says.
    rng = random.Random(SEED + 7)
    ctx = decimal.Context(prec=1200)
    seen = set()
    samples = []
    for _ in range(24):
        b = rng.getrandbits(63)          # positive finite, any magnitude
        x = double_of(b)
        if math.isnan(x) or math.isinf(x) or x == 0.0:
            continue
        samples.append(x)
    # …plus the places a rounding rule is most likely to be wrong.
    samples += [1.0, 2.0, 0.5, 5e-324, 2.2250738585072014e-308,
                1.7976931348623157e308, 9007199254740992.0, 1e22]
    for x in samples:
        if x in seen:
            continue
        seen.add(x)
        nxt = math.nextafter(x, math.inf)
        if math.isinf(nxt):
            continue
        exact = ctx.create_decimal(x)
        mid = ctx.divide(ctx.add(exact, ctx.create_decimal(nxt)),
                         decimal.Decimal(2))
        for text in ("{:f}".format(exact), "{:f}".format(mid),
                     "{:f}".format(mid) + "1"):
            if not saw_accepts(text):
                continue
            ok(text)

    # the non-finite spellings `to_string` produces
    rows.append(("nan", "%016X" % QUIET_NAN))
    rows.append(("inf", "%016X" % POS_INF))
    rows.append(("-inf", "%016X" % NEG_INF))
    rows.append(("+inf", "%016X" % POS_INF))
    # …and what is NOT a number. Several of these ARE accepted by CPython
    # (whitespace, `infinity`, `NaN`, PEP-515 underscores) and are rejected
    # here on purpose — `saw_accepts` above, not `float()`, is the authority
    # for which inputs Saw takes.
    for t in ["", " ", "  1", "1 ", "abc", ".", "-", "+", "e5", "1e", "1e+",
              "1e-", "--1", "1.2.3", "1,5", "0x1p3", "1_000", "nan(1)",
              "infinity", "NaN", "INF", "Inf", "1d5", "1 000", "0b101",
              "1e5.5", "５", "1.5f", "- 1"]:
        rejects(t)
    return rows


# ---------------------------------------------------------------------------
# The Ryu power-of-five tables, which live INSIDE `sawc/std/float.saw`
#
# A shortest-round-trip formatter is only as correct as its tables, and a
# mistyped hex digit in 1236 of them would show up as one wrong value in a
# hundred million rather than as a broken build. So the tables are GENERATED
# here, spliced into the Saw source between sentinel comments, and `verify`
# re-derives them and compares — a hand-edited digit fails the gate.

POW5_INV_BITCOUNT = 125
POW5_BITCOUNT = 125
POW5_INV_TABLE_SIZE = 292        # indices 0..290 are reached
POW5_TABLE_SIZE = 326            # indices 1..325 are reached

TABLE_BEGIN = ("// BEGIN GENERATED TABLES — regenerate with "
               "`tools/sawfloat.py tables`")
TABLE_END = "// END GENERATED TABLES"
FLOAT_SAW = os.path.join(REPO, "sawc", "std", "float.saw")


def _pow5bits(e: int) -> int:
    """ceil(log2(5^e)) for 0 <= e < 3529 — the same closed form the Saw side
    uses, so the table and the code that indexes it agree by construction."""
    return ((e * 1217359) >> 19) + 1


def pow5_inv_split(i: int) -> int:
    """`floor(2**(pow5bits(i) - 1 + 125) / 5**i) + 1`, 128 bits."""
    v = ((1 << (_pow5bits(i) - 1 + POW5_INV_BITCOUNT)) // (5 ** i)) + 1
    assert v < (1 << 128)
    return v


def pow5_split(i: int) -> int:
    """`5**i` shifted to 128 bits."""
    shift = _pow5bits(i) - POW5_BITCOUNT
    v = (5 ** i) >> shift if shift > 0 else (5 ** i) << (-shift)
    assert v < (1 << 128)
    return v


LEMIRE_MIN_Q = -342              # below it every input is zero
LEMIRE_MAX_Q = 308               # above it every input is infinite


def pow5_truncated(q: int) -> int:
    """5^q truncated to 128 bits — Eisel-Lemire's `power_of_five_128` entry.

    For a negative exponent the table holds `floor(2^k / 5^-q)` instead, which
    is the same thing read as a reciprocal: what the algorithm needs either way
    is 128 bits of 10^q's significand, and the ERROR BOUND that makes the
    method decidable is what the truncation direction is chosen for.
    """
    if q >= 0:
        v = 5 ** q
        b = v.bit_length()
        return v << (128 - b) if b <= 128 else v >> (b - 128)
    d = 5 ** (-q)
    v = (1 << (127 + d.bit_length())) // d
    while v.bit_length() > 128:
        v >>= 1
    assert v.bit_length() == 128, q
    return v


def _table_block(name: str, count: int, value_of, first: int = 0,
                 high_first: bool = False) -> list:
    """One `static NAME: [UInt64; 2*count] = [...]` declaration, two words per
    entry. Ryu's tables are (low, high) — the layout `mul[0]`/`mul[1]` has in
    its reference implementation — and Eisel-Lemire's is (high, low), which is
    the layout ITS reference uses. Each matches its own paper's indexing, so
    neither transcription has to remember a swap."""
    lines = ["static %s: [UInt64; %d] = [" % (name, count * 2)]
    for i in range(count):
        v = value_of(first + i)
        hi, lo = v >> 64, v & 0xFFFFFFFFFFFFFFFF
        pair = (hi, lo) if high_first else (lo, hi)
        lines.append("    0x%016X, 0x%016X,   // %d" % (pair[0], pair[1],
                                                        first + i))
    lines.append("]")
    return lines


def table_lines() -> list:
    lines = [TABLE_BEGIN, ""]
    lines += _table_block("FLOAT_POW5_INV_SPLIT", POW5_INV_TABLE_SIZE,
                          pow5_inv_split)
    lines.append("")
    lines += _table_block("FLOAT_POW5_SPLIT", POW5_TABLE_SIZE, pow5_split)
    lines.append("")
    lines += _table_block("FLOAT_POW5_TRUNCATED",
                          LEMIRE_MAX_Q - LEMIRE_MIN_Q + 1, pow5_truncated,
                          first=LEMIRE_MIN_Q, high_first=True)
    lines += ["", TABLE_END]
    return lines


def _splice(path, lines):
    with open(path, encoding="utf-8") as fh:
        src = fh.read().splitlines()
    try:
        start = src.index(TABLE_BEGIN)
        end = src.index(TABLE_END)
    except ValueError:
        print("%s: no `%s` / `%s` sentinel pair" % (path, TABLE_BEGIN, TABLE_END))
        return None
    return src[:start] + lines + src[end + 1:]


def cmd_tables():
    if not os.path.exists(FLOAT_SAW):
        print("missing %s" % FLOAT_SAW)
        return 1
    out = _splice(FLOAT_SAW, table_lines())
    if out is None:
        return 1
    with open(FLOAT_SAW, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    print("spliced %d table entries into %s"
          % (POW5_INV_TABLE_SIZE + POW5_TABLE_SIZE, FLOAT_SAW))
    return 0


def verify_tables():
    """The committed tables, re-derived. Returns a list of failures."""
    if not os.path.exists(FLOAT_SAW):
        return []                      # unit 1 has not landed the module yet
    with open(FLOAT_SAW, encoding="utf-8") as fh:
        src = fh.read().splitlines()
    if TABLE_BEGIN not in src:
        return ["%s carries no generated-table sentinel" % FLOAT_SAW]
    have = src[src.index(TABLE_BEGIN):src.index(TABLE_END) + 1]
    want = table_lines()
    if have == want:
        return []
    n = min(len(have), len(want))
    first = next((i for i in range(n) if have[i] != want[i]), n)
    return ["sawc/std/float.saw's generated tables differ from what "
            "tools/sawfloat.py derives, first at offset %d:\n    committed: "
            "%s\n    generated: %s\n  Re-run `tools/sawfloat.py tables`." % (
                first,
                have[first] if first < len(have) else "<end>",
                want[first] if first < len(want) else "<end>")]


# ---------------------------------------------------------------------------
# files


def _write(name, lines):
    os.makedirs(VECTOR_DIR, exist_ok=True)
    path = os.path.join(VECTOR_DIR, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _shortest_lines():
    lines = [
        "# design 253 — shortest round-trip vectors, generated by "
        "tools/sawfloat.py (seed %d)." % SEED,
        "# <IEEE 754 bits, 16 hex digits>TAB<the shortest round-trip text>",
        "# Both directions of one value: format(bits) is the text, and "
        "parse(text) is the bits.",
        "# Do not hand-edit — `tools/sawfloat.py verify` re-derives every row.",
    ]
    for b, text in shortest_rows():
        lines.append("%016X\t%s" % (b, text))
    return lines


def _parse_lines():
    lines = [
        "# design 253 — parse-only vectors, generated by tools/sawfloat.py.",
        "# <input text>TAB<IEEE 754 bits, 16 hex digits>   parses to those bits",
        "# <input text>TABreject                           is not a number",
        "# The spellings a formatter never emits. Round-trip pairs live in "
        "shortest.tsv.",
        "# Do not hand-edit — `tools/sawfloat.py verify` re-derives every row.",
    ]
    for text, want in parse_rows():
        lines.append("%s\t%s" % (text, want))
    return lines


def cmd_gen():
    a = _write(SHORTEST, _shortest_lines())
    b = _write(PARSE, _parse_lines())
    print("wrote %s (%d rows)" % (a, len(shortest_rows())))
    print("wrote %s (%d rows)" % (b, len(parse_rows())))
    return 0


def _read(name):
    path = os.path.join(VECTOR_DIR, name)
    if not os.path.exists(path):
        print("missing vector file: %s" % path)
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def cmd_verify(check_rule: bool):
    failures = verify_tables()

    for name, want_lines in ((SHORTEST, _shortest_lines()),
                             (PARSE, _parse_lines())):
        have = _read(name)
        if have is None:
            return 1
        if have != want_lines:
            n = min(len(have), len(want_lines))
            first = next((i for i in range(n) if have[i] != want_lines[i]), n)
            failures.append(
                "%s differs from what the case table generates, first at line "
                "%d:\n    committed: %s\n    generated: %s\n  (%d committed "
                "rows vs %d generated)\n  Re-run `tools/sawfloat.py gen` if the "
                "case table changed on purpose." % (
                    name, first + 1,
                    have[first] if first < len(have) else "<end of file>",
                    want_lines[first] if first < len(want_lines) else "<end of file>",
                    len(have), len(want_lines)))

    # Independent re-check: every shortest row round-trips through CPython, and
    # the text really is the SHORTEST such string. This is what makes the file
    # an oracle rather than a transcript of one function's output.
    for b, text in shortest_rows():
        x = double_of(b)
        if math.isnan(x):
            if text != "nan":
                failures.append("%016X: NaN rendered %r" % (b, text))
            continue
        if math.isinf(x):
            if text != ("-inf" if x < 0 else "inf"):
                failures.append("%016X: infinity rendered %r" % (b, text))
            continue
        if bits_of(float(text)) != b:
            failures.append("%016X: %r does not parse back to it" % (b, text))
            continue
        if x == 0.0:
            continue
        # Shortest, checked rather than assumed: no decimal with FEWER
        # significant digits lands on the same double. `repr` promises this,
        # and re-deriving it here is what makes the file an oracle for
        # "shortest" and not merely for "round-trips".
        digits, decpt = _shortest_digits(x)
        if len(digits) > 17:
            failures.append("%016X: %d significant digits" % (b, len(digits)))
        for keep in range(1, len(digits)):
            head = int(digits[:keep])
            for cand in (head, head + 1):
                short = "%de%d" % (cand, decpt - keep)
                try:
                    if bits_of(math.copysign(float(short), x)) == b:
                        failures.append(
                            "%016X: %r is not shortest — %s round-trips too"
                            % (b, text, short))
                except (ValueError, OverflowError):
                    pass

    for text, want in parse_rows():
        if "\t" in text or "\n" in text:
            failures.append("%r: a TAB or newline cannot travel in a TSV row"
                            % text)
            continue
        if want == "reject":
            if saw_accepts(text):
                failures.append("%r: marked reject, but Saw's grammar takes it"
                                % text)
            continue
        if not saw_accepts(text):
            failures.append("%r: expected to parse, but Saw's grammar refuses "
                            "it" % text)
            continue
        if text in ("nan", "inf", "-inf", "+inf"):
            continue
        if "%016X" % bits_of(float(text)) != want:
            failures.append("%r: expected bits %s, CPython says %016X"
                            % (text, want, bits_of(float(text))))

    if check_rule:
        rng = random.Random(SEED + 1)
        for _ in range(50000):
            x = double_of(rng.getrandbits(64))
            if math.isnan(x) or math.isinf(x):
                continue
            if text_of(x) != repr(x):
                failures.append("the documented render rule disagrees with "
                                "repr for %016X: %r vs %r"
                                % (bits_of(x), text_of(x), repr(x)))
                break

    if failures:
        for f in failures[:20]:
            print("FAIL: %s" % f)
        if len(failures) > 20:
            print("... and %d more" % (len(failures) - 20))
        return 1
    print("float vectors OK: %d round-trip rows, %d parse rows"
          % (len(shortest_rows()), len(parse_rows())))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen", help="rewrite the golden vectors")
    sub.add_parser("tables", help="splice the Ryu tables into sawc/std/float.saw")
    v = sub.add_parser("verify", help="check the committed vectors")
    v.add_argument("--rule", action="store_true",
                   help="also re-check the documented render rule against repr")
    args = ap.parse_args()
    if args.cmd == "gen":
        return cmd_gen()
    if args.cmd == "tables":
        return cmd_tables()
    if args.cmd == "verify":
        return cmd_verify(args.rule)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

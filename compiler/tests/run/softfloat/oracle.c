// The soft-float vectors' oracle: compiler-rt's own routines, the vendored
// sources under compiler-rt/ beside this file built for the host with
// `-D__SOFTFP__` (the integer-only path compiler-rt takes on a target with no
// floating-point unit) and each routine renamed `crt_*`, run on a fixed set
// of operands. generate.py builds it and writes its output to vectors.txt.
//
// The operands are an edge grid and fixed-seed SplitMix64 draws, in an order
// tests/freestanding/cases/soft_float_vectors.saw repeats exactly, since that
// case folds each routine's results into a checksum the runner holds equal to
// this file's. Three kinds of line, every number but a comparison's or a
// float-to-integer conversion's in hex:
//
//   B a b add sub mul div eq ne lt le gt ge unord
//   F a fixdfsi fixdfdi fixunsdfsi fixunsdfdi
//   I x floatsidf floatdidf floatunsidf floatundidf
//
// An `I` line's 32-bit routines take the low 32 bits of `x`.

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

// The routines take and return a `double`, which the host passes in its
// floating-point registers, so each is called through a `double` signature
// and its bits read back through a union.
typedef union { uint64_t bits; double value; } word;

#define BINARY(name) \
    static uint64_t name(uint64_t a, uint64_t b) { \
        double crt_##name(double, double); \
        word x = {.bits = a}, y = {.bits = b}, r; \
        r.value = crt_##name(x.value, y.value); \
        return r.bits; \
    }

#define COMPARE(name) \
    static int name(uint64_t a, uint64_t b) { \
        int crt_##name(double, double); \
        word x = {.bits = a}, y = {.bits = b}; \
        return crt_##name(x.value, y.value); \
    }

#define TO_INTEGER(name, type) \
    static type name(uint64_t a) { \
        type crt_##name(double); \
        word x = {.bits = a}; \
        return crt_##name(x.value); \
    }

#define TO_FLOAT(name, type) \
    static uint64_t name(type a) { \
        double crt_##name(type); \
        word r; \
        r.value = crt_##name(a); \
        return r.bits; \
    }

BINARY(adddf3)
BINARY(subdf3)
BINARY(muldf3)
BINARY(divdf3)
COMPARE(eqdf2)
COMPARE(nedf2)
COMPARE(ltdf2)
COMPARE(ledf2)
COMPARE(gtdf2)
COMPARE(gedf2)
COMPARE(unorddf2)
TO_INTEGER(fixdfsi, int32_t)
TO_INTEGER(fixdfdi, int64_t)
TO_INTEGER(fixunsdfsi, uint32_t)
TO_INTEGER(fixunsdfdi, uint64_t)
TO_FLOAT(floatsidf, int32_t)
TO_FLOAT(floatdidf, int64_t)
TO_FLOAT(floatunsidf, uint32_t)
TO_FLOAT(floatundidf, uint64_t)

#define SIGN 0x8000000000000000ull
#define ABS 0x7FFFFFFFFFFFFFFFull
#define SIGNIFICAND 0x000FFFFFFFFFFFFFull

static uint64_t state;

static uint64_t draw(void) {
    state += 0x9E3779B97F4A7C15ull;
    uint64_t z = state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

// Magnitudes every binary routine meets paired with each other, each at both
// signs: zeros, subnormals, the normal boundary, values around 1, the 2^52
// and 2^53 boundaries, the largest finite, infinity, quiet and signalling NaNs
// with payloads.
static const uint64_t EDGES[] = {
    0x0000000000000000ull, 0x0000000000000001ull, 0x0000000000000002ull, 0x0000000000000003ull,
    0x000FFFFFFFFFFFFFull, 0x0008000000000000ull, 0x0010000000000000ull, 0x0010000000000001ull,
    0x3FF0000000000000ull, 0x3FF0000000000001ull, 0x3FF8000000000000ull, 0x3FEFFFFFFFFFFFFFull,
    0x4330000000000000ull, 0x4340000000000000ull, 0x3CA0000000000000ull, 0x7FEFFFFFFFFFFFFFull,
    0x7FE0000000000000ull, 0x7FF0000000000000ull, 0x7FF8000000000000ull, 0x7FF8000000000042ull,
    0x7FF0000000000001ull, 0x7FF4000000000000ull, 0x4000000000000000ull, 0x3FE0000000000000ull,
};
#define EDGE_COUNT (sizeof EDGES / sizeof EDGES[0])

// Magnitudes the float-to-integer routines meet besides the edges: each side
// of 2^31, 2^32, 2^63 and 2^64, the halves around them, and the values where
// the shift turns from right to left.
static const uint64_t CONVERSION_EDGES[] = {
    0x41DFFFFFFFC00000ull, 0x41DFFFFFFFE00000ull, 0x41E0000000000000ull, 0x41E0000000100000ull,
    0x41EFFFFFFFE00000ull, 0x41F0000000000000ull, 0x43DFFFFFFFFFFFFFull, 0x43E0000000000000ull,
    0x43EFFFFFFFFFFFFFull, 0x43F0000000000000ull, 0x4330000000000001ull, 0x4320000000000001ull,
    0x41E0000000200000ull,
};
#define CONVERSION_EDGE_COUNT (sizeof CONVERSION_EDGES / sizeof CONVERSION_EDGES[0])

// Integers the integer-to-float routines meet, each also negated: the 32-bit
// bounds, the 2^53 boundary where rounding starts, ties to even below 2^54 and
// 2^64, and the top of each width.
static const uint64_t INTEGER_EDGES[] = {
    0x0000000000000000ull, 0x0000000000000001ull, 0x0000000000000002ull, 0x0000000000000003ull,
    0x000000007FFFFFFFull, 0x0000000080000000ull, 0x00000000FFFFFFFFull, 0x0000000100000000ull,
    0x001FFFFFFFFFFFFFull, 0x0020000000000000ull, 0x0020000000000001ull, 0x0020000000000002ull,
    0x0020000000000003ull, 0x0040000000000002ull, 0x0040000000000006ull, 0x7FFFFFFFFFFFFFFFull,
    0x8000000000000000ull, 0x8000000000000001ull, 0xFFFFFFFFFFFFFFFFull, 0xFFFFFFFFFFFFF800ull,
    0xFFFFFFFFFFFFFC00ull, 0xFFFFFFFFFFFFFBFFull, 0x8000000000000400ull, 0x8000000000000C00ull,
};
#define INTEGER_EDGE_COUNT (sizeof INTEGER_EDGES / sizeof INTEGER_EDGES[0])

// How many draws each kind of operand gets.
#define UNIFORM_DRAWS 300
#define NEAR_DRAWS 300
#define SHORT_DRAWS 300
#define TINY_DRAWS 200
#define TOP_DRAWS 200
#define UNDERFLOW_DRAWS 150
#define TO_INTEGER_DRAWS 1500
#define TO_FLOAT_DRAWS 1500

static void binary(uint64_t a, uint64_t b) {
    printf("B %016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64
           " %d %d %d %d %d %d %d\n", a, b, adddf3(a, b), subdf3(a, b), muldf3(a, b), divdf3(a, b),
           eqdf2(a, b), nedf2(a, b), ltdf2(a, b), ledf2(a, b), gtdf2(a, b), gedf2(a, b), unorddf2(a, b));
}

static void to_integer(uint64_t a) {
    printf("F %016" PRIx64 " %" PRId32 " %" PRId64 " %" PRIu32 " %" PRIu64 "\n", a, fixdfsi(a), fixdfdi(a),
           fixunsdfsi(a), fixunsdfdi(a));
}

static void to_float(uint64_t x) {
    printf("I %016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64 "\n", x,
           floatsidf((int32_t)(uint32_t)x), floatdidf((int64_t)x), floatunsidf((uint32_t)x), floatundidf(x));
}

// A value of biased exponent `exponent` (its low 11 bits), with a drawn sign
// and then a drawn significand.
static uint64_t operand(uint64_t exponent) {
    uint64_t sign = draw() & SIGN;
    uint64_t significand = draw() & SIGNIFICAND;
    return sign | ((exponent & 0x7FF) << 52) | significand;
}

// `value` with its significand cut to at most its top 26 bits, so that sums,
// products and quotients of two such values land on rounding ties and on
// results whose sticky bits alone decide the rounding.
static uint64_t shortened(uint64_t value) {
    uint64_t kept = draw() % 27;
    return value & ~((1ull << (52 - kept)) - 1);
}

static uint64_t short_operand(void) {
    uint64_t exponent = 1023 - 32 + draw() % 64;
    return shortened(operand(exponent));
}

// A pair whose product's exponent lands from 60 below the subnormal boundary
// to 5 above it, or, for a `quotient`, whose quotient's does. `cut` 1 shortens
// both operands; 2 shortens `a` and gives `b` the significand 1, so the
// product is `a` plus `a` 52 places lower, whose bits only the sticky bit
// carries once the result is shifted down.
static void underflowing(int quotient, int cut) {
    uint64_t e1 = 1 + draw() % 1023;
    uint64_t apart = draw() % 66;
    uint64_t e2 = quotient ? e1 + 1023 - 5 + apart : 1023 + 5 - e1 - apart;
    uint64_t a = operand(e1);
    uint64_t b = operand(e2);
    if (cut == 1) {
        a = shortened(a);
        b = shortened(b);
    }
    if (cut == 2) {
        a = shortened(a);
        b = (b & ~SIGNIFICAND) | 1;
    }
    binary(a, b);
}

int main(void) {
    state = 948;
    for (size_t i = 0; i < 2 * EDGE_COUNT; i++)
        for (size_t j = 0; j < 2 * EDGE_COUNT; j++)
            binary(EDGES[i / 2] | (i % 2 ? SIGN : 0), EDGES[j / 2] | (j % 2 ? SIGN : 0));
    for (int k = 0; k < UNIFORM_DRAWS; k++) {
        uint64_t a = draw();
        binary(a, draw());
    }
    // Exponents up to 65 apart, either sign: every alignment and cancellation.
    for (int k = 0; k < NEAR_DRAWS; k++) {
        uint64_t a = draw();
        uint64_t apart = (draw() % 66) << 52;
        uint64_t sign = draw() & SIGN;
        uint64_t low = draw() & 0xFF;
        binary(a, (((a & ABS) - apart) & ABS) ^ sign ^ low);
    }
    for (int k = 0; k < SHORT_DRAWS; k++) {
        uint64_t a = short_operand();
        binary(a, short_operand());
    }
    // Subnormal and tiny operands.
    for (int k = 0; k < TINY_DRAWS; k++) {
        uint64_t a = draw() & 0x801FFFFFFFFFFFFFull;
        binary(a, draw() & 0x801FFFFFFFFFFFFFull);
    }
    // Near the top, where rounding carries into infinity.
    for (int k = 0; k < TOP_DRAWS; k++) {
        uint64_t a = 0x7FE0000000000000ull | (draw() & 0x800FFFFFFFFFFFFFull);
        binary(a, 0x7C00000000000000ull | (draw() & 0x83FFFFFFFFFFFFFFull));
    }
    for (int k = 0; k < UNDERFLOW_DRAWS; k++) {
        underflowing(0, 0);
        underflowing(0, 1);
        underflowing(0, 2);
        underflowing(1, 0);
        underflowing(1, 1);
        underflowing(1, 2);
    }
    for (size_t i = 0; i < 2 * EDGE_COUNT; i++)
        to_integer(EDGES[i / 2] | (i % 2 ? SIGN : 0));
    for (size_t i = 0; i < 2 * CONVERSION_EDGE_COUNT; i++)
        to_integer(CONVERSION_EDGES[i / 2] | (i % 2 ? SIGN : 0));
    // Exponents from just below 1 to just past 2^64, so every shift is met.
    for (int k = 0; k < TO_INTEGER_DRAWS; k++) {
        uint64_t exponent = 1023 - 2 + draw() % 68;
        to_integer(operand(exponent));
    }
    for (size_t i = 0; i < 2 * INTEGER_EDGE_COUNT; i++)
        to_float(i % 2 ? 0 - INTEGER_EDGES[i / 2] : INTEGER_EDGES[i / 2]);
    // Every magnitude, either sign.
    for (int k = 0; k < TO_FLOAT_DRAWS; k++) {
        uint64_t bits = draw();
        uint64_t magnitude = bits >> (draw() % 64);
        uint64_t negate = draw() & 1;
        to_float(negate ? 0 - magnitude : magnitude);
    }
    return 0;
}

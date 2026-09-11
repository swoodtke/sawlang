# M12: checked String.to_uint intrinsic

Planned after Optional/Result integration. This is the next isolated dependency
for the unchanged lexer literal_fits helper; it does not compile std/string.saw.

## Source contract

Accept `string.to_uint()` and `string.to_uint(radix)` (ordered `radix:` label
also allowed) on the same receivers as the existing String intrinsics. Return
UInt?. Default radix is 10. Explicit radix is Int and valid from 2 through 36.
Snapshot a named receiver before evaluating the radix argument, preserving
existing String intrinsic argument-order semantics.

Parse the whole String byte sequence, with an optional leading ASCII plus.
Accept ASCII digits and letters A-Z/a-z for values 0..35. Reject empty/lone-plus,
minus, whitespace, separators, prefixes (unless their bytes are valid digits
in the requested radix), trailing junk, non-ASCII bytes and embedded NUL.
Invalid radix and overflow return None without a panic. Arbitrarily many leading
zeros remain valid. UInt64.max is valid, including above signed Int.max.

## IR and engine contract

Introduce StringToUInt with a=String slot, b=I64 radix slot, and dst beginning a
two-word [Bool,U64] range. Verifier checks this exact range and operand types.
Every path writes both tag and value; invalid parses write false and zero.
The frontend interns Optional<UInt> and assigns the corresponding logical type.

VM may use a small explicit byte parser returning UInt?; use UInt arithmetic
only after checking `acc <= (UInt.max - digit) / radix`. Check radix before the
division. Convert the valid UInt bit pattern into the VM's Int slot with a
truncating bit-preserving conversion. Do not use a signed numeric parser.

Native helper accepts the existing String pointer and i64 radix and returns
{i64,i64} tag/value. Use unsigned comparison and unsigned division for the same
precondition, then ordinary wrapping-defined LLVM multiply/add without nsw/nuw.
Validate the digit and radix before arithmetic. Reading the String uses its
stored byte length, never strlen. No allocation or libc parsing is needed.

## Validation

Table-driven source tests with explicit expected UInt/None results: bases
2/8/10/16/36, both letter cases, plus, invalid signs/radices/bytes, whitespace,
embedded NUL, empty, max-1/max/max+1 in several bases, leading zeros and receiver
snapshot mutation. Include the unchanged literal_fits function with boundaries
for 8/16/32/64-bit widths and all lexer radices. Direct IR checks reject invalid
destination/argument ranges. Full VM/native regression gate before commit.

# Design 253 — The Float↔Text Story

**Status: AUTHORED + DISPATCHED Aug 28 2026** (lead; user: "brief the
Float-text story and slot it at the head of the queue", behind the DF-270d
fix). Agent DF range: **DF-276a+**.

## The gap (recorded across three landings)

std has NO correct Float↔text conversion in either direction:
- `String.to_float()` exists but is DOCUMENTED as a naive non-correctly-
  rounded accumulation (parse only).
- No Float→text direction exists anywhere in std, "not even informally"
  (std.json unit 1's discovery). Float printing/interpolation rides
  whatever the compiler's print path does — the census (unit 0) records
  exactly what that is.
- Consumers waiting: `JsonValue.Number` is Int-only (the parked cell from
  the original pinned rule: integral-and-in-range -> Int, else Float);
  the serde seam has no `write_float`/`read_float` (that WIRE question
  stays a separate design — this brief builds the text layer it would
  need); any user program that wants `print("{}", 0.1)` to round-trip.

## The ruling this brief encodes (lead recommendation, standing doctrine)

**Pure Saw, both directions, correctly rounded.** Kernels and embedded are
first-class targets and freestanding concerns shape the stdlib — an FFI
strtod/snprintf bolt-on fails that test and touches the frozen rt seam
surface besides. This is a serious, well-trodden algorithmic project with
exact published solutions:
- **Formatting: shortest round-trip** (Ryū or an equivalent
  shortest-correct algorithm): the produced decimal string parses back to
  the identical bits, and is the shortest such string. Fixed-precision
  variants are OUT of v1 (OPEN list).
- **Parsing: correctly rounded** (Eisel-Lemire fast path with a
  slow-but-exact fallback for the cases it rejects — a big-decimal
  comparison path is acceptable for the fallback; it runs rarely). Every
  finite input maps to the nearest-even double; overflow to infinity and
  underflow to zero/subnormals per IEEE 754.
- Both directions live in ONE std module (unit 0 decides file placement
  beside the existing surfaces; `Float`-extension methods are the surface,
  see §Surface).

## The oracle (what makes this correctness-checkable without guessing)

The test harness is Python, and CPython's float repr/parse IS
correctly-rounded shortest round-trip. Unit 0 builds a VECTOR GENERATOR
(`tools/` or a test-side generator per existing harness conventions —
follow how existing tables in the tree are generated) that emits a
committed vector file: boundary cases (0, -0, subnormal min/max, FLT
boundaries, DBL_MAX, powers of two and their neighbors, halfway-rounding
cases, the classic hard cases — 5e-324, 2.2250738585072011e-308 and
friends), plus a few thousand PRNG-seeded round-trip samples (fixed seed,
committed output — determinism per house rules; no `Date.now()`-style
nondeterminism anywhere). Tests assert BIT-EXACT round trips both ways
against the vectors. A formatting or parsing result that differs from the
vector is a failure, never a tolerance.

## Surface

- `Float.to_string(&self) -> Result<String, AllocError>` (or the exact
  allocator-policy shape the census says sibling surfaces use) — shortest
  round-trip; `StringBuilder.append(value: Float)` renders the same text
  through the builder (allocation policy per the existing Int `append`);
  interpolation/print of a Float follows automatically if the print path
  routes through the builder (census confirms; if print has a separate
  float path, it is REPLACED, not duplicated).
- `String.to_float(&self) -> Float?` keeps its name and shape but becomes
  correctly rounded (its doc comment's apology is deleted); if its current
  signature differs, match the house accessor policy and record the
  change. The naive body is deleted, not kept as a fallback.
- Special values: `to_string` of NaN/infinities produces `nan`/`inf`/
  `-inf` (Saw-facing, NOT JSON — json's own rules unchanged); `to_float`
  accepts what `to_string` produces plus ordinary decimal/exponent forms;
  it does NOT accept hex floats in v1 (OPEN list).

## Units

0. CENSUS + VECTORS: every current Float↔text touchpoint (to_float's
   callers, the print/interpolation path for Float, any format-args
   handling) tabled; the vector generator + committed vectors land with
   the harness hookup proving a deliberately-wrong value fails.
1. FORMATTING (shortest round-trip) + builder/print integration + vector
   tests green.
2. PARSING (correctly rounded, fast path + exact fallback) + vector tests
   + fuzz-shaped grid (the generator's PRNG rows).
3. `JsonValue.Number` Float support: reopen the parked cell under the
   original pinned rule (lexically-integral-and-in-Int-range -> Int, else
   Float — ratified in the unit-1 queue record), JSON.md's OPEN list
   updated, round-trip tests through parse AND serialize (JSON emits the
   shortest form; `1e2` round-trips as value, not spelling). JSON's
   grammar rules unchanged: NaN/Infinity remain rejected on parse; a
   non-finite Float in a tree is `EncodeFault.Unsupported` on serialize.
4. Docs per design 125 (spec's Float section, skill, README) + tracker
   close in place.

## Obligations ledger

1. Funnels: ONE formatting routine and ONE parsing routine; every surface
   (to_string, builder append, print path, json) routes through them —
   docstrings name the consumers. 2. Consumer sweep: to_float's existing
   callers (census row per caller — behavior changes from wrong to right;
   any caller relying on the naive parse's quirks is a finding, not a
   compatibility target); the Float print path's current output changes
   corpus-wide — the suite's EXPECT-OUTPUT rows involving floats are the
   inventory, updated in the same commit as unit 1 with each delta listed
   in the report. 3. No conformance rows (numeric text conversion is not
   a claimed safety guarantee; the vectors are the correctness ledger).
   4. N/A — this is new capability, not a defect class.

## Unit 0 — the census (Aug 28, compile/run evidence)

### Is the algorithm expressible? Yes, with two cautions

`Float` IS IEEE 754 binary64 and the only float type — `LANGUAGE_SPEC.md:772`
and `sawc/codegen/types.py:123` (`TypeKind.FLOAT -> ir.DoubleType()`, one
site). `sizeof<Float>() == 8`.

**Float bits reinterpret works today and needs no compiler change.** The
shortest spelling is a pointer pun through the address of a local, and it
folds to a single LLVM `bitcast` at both `-O0` and the default pipeline:

```saw
func bits(f: Float) unsafe -> UInt64 { ((&f_local) as UnsafePointer<UInt64>)[0] }
```

`&` may be taken on an immutable `let` and may cross directly to the
differently-typed pointer. `unsafe` is required in the effect slot (design
130's trigger rule) and is not transitive, so the safe wrappers `Float.to_bits`
/ `Float.from(bits:)` are two lines each. sawc emits no TBAA metadata at all,
so no strict-aliasing hazard rides on this.

`UInt64` arithmetic is sound for the algorithms: `+ - * / % << >> & | ^ ~` and
all six comparisons are correct above 2^63 (`/`, `%`, `>>` lower unsigned), and
`&+ &- &*` wrap silently. The 64x64 -> 128 product needed by Eisel-Lemire is
expressible with 32-bit halves and PLAIN checked operators (no partial product
overflows 64 bits); it was verified against six independently-computed
expectations including `0xFFFF...FF^2 = (hi 0xFFFF...FE, lo 1)`.

**Caution 1 — `x << 64` PANICS** (`shift out of range`), while shifting bits
off the top does not. Every computed shift amount needs the `== 64` case
written out.

**Caution 2 — DF-270d bites the byte layer.** `Byte` is a distinct alias over
`UInt8`, and an ordered comparison on one lowers SIGNED, so `b > 48` is FALSE
for `b == 200`. `String.byte_at` returns `Byte`. The parser therefore widens
every byte to `Int` before comparing — which is what `string.saw`'s existing
`_ubyte_at` funnel already does — and never order-compares a `Byte`.

**There is no Int -> Float conversion in any spelling** (`Float.from(n)`,
`Float(n)`, `n as Float` all error). Not a blocker: both algorithms produce
IEEE *bits* and the construction goes through `Float.from(bits:)`. It does mean
no small-integer float fast path is writable, and `string.saw`'s ten-branch
`_digit_to_float` exists for exactly this reason.

### The Float -> text paths that exist today (all libc, and they disagree)

| Surface | Emitter | Mechanism |
|---|---|---|
| `print(f)` | `codegen/calls.py:1292-1298` | `printf("%f\n")` — 6 FRACTIONAL digits |
| `"{f}"` | `codegen/core.py:3380` `_value_to_string` FLOAT arm | `snprintf(buf, 64, "%g")` — 6 SIGNIFICANT digits |
| `print("{}", f)` | `calls.py:1068` `_render_argument` -> `_value_to_string` | `%g` |
| `panic`/`assert` args | `calls.py:1418`/`:1449` -> the same `_format_segments` | `%g` |
| `f.to_string()` | `core.py:3408` `_emit_to_string` -> `_value_to_string` | `%g` |
| `f.format(into:)` | `core.py:3458` `_emit_format` -> `_value_to_string` | `%g` |

So there are TWO renderings, and `_value_to_string`'s FLOAT arm is already the
chokepoint for five of the six — which is the funnel unit 1 replaces. No
`__saw_rt_*` seam and no `shim.c` body formats a float; `rt/ABI.md:93` only
records that `__saw_rt_write` must share stdio's buffer BECAUSE the float path
is still `printf`. `StringBuilder` has no `Float` overload
(`append` takes `String`/`Int`/`UInt`/`Byte`).

Nothing round-trips: `0.1 + 0.2` prints `0.3` in every spelling, `1.0` prints
`1.000000` or `1`, and `%g` emits `1e+21` — an exponent form Saw's own lexer
cannot read back (design 161 left the grammar with no exponent form).

**Latent bug the replacement closes**: the freestanding refusal of Float text
is written at only two of six positions (`typechecker/expressions.py:3755` for
`print(f)`, `:642` for format arguments). Interpolation, `to_string()` and
`format(into:)` compile clean under `--freestanding` and leave `U snprintf`
in the object.

### Consumer sweep (obligation 2)

`String.to_float`'s callers: `examples/string_to_float.saw` and
`devtools/dogfood/programs/llm_client.saw` (which also writes a float into a
JSON request body via `"{t}"` interpolation — a real shipped lossy site). No
caller depends on the naive parse's quirks; every one of them reads a value
that the correctly-rounded parse returns identically or more accurately.

The Float print path's output changes corpus-wide. The EXPECT-OUTPUT inventory
was built by compiling every candidate `.saw` with `--emit-ir` and searching
each program's own IR for the two format globals — not by grepping expected
output, which cannot tell `%g`'s `1` for `1.0` from an integer:

| File | Lines | Path |
|---|---|---|
| `examples/float_methods.saw` | 5-11 | `%f` |
| `examples/string_to_float.saw` | 6-15 | `%f` |
| `examples/variables.saw` | 4 | `%f` |
| `examples/compound_assign.saw` | 9 | `%f` |
| `examples/primitive_extension_self_is_its_own_type.saw` | 32 | `%f` |
| `examples/string_interpolation.saw` | 5 | `%g` |
| `examples/coro_ref_param_compound_assign.saw` | 14 | `%g` |
| `examples/number_literal_member_access.saw` | 9, 12 | `%g` (`to_string`) |
| `examples/tuple_index_member_access.saw` | 17 | `%g` |
| `examples/format_args_print.saw` | 11, 12 | `%g` (format args) |
| `examples/format_into_builtin_alloc_free.saw` | 16, 17 | `%g` (`format(into:)`) |

`blade/tests`, `libs/*/tests`, `sos/`, `examples/conformance/` and
`selfhost/` render no Float at all (the first two IR-verified, the last three
contain no `Float` token). Nothing anywhere pins what a NaN, an infinity or a
`-0.0` prints as.

### Rulings this unit took

- **The text format IS CPython's `repr`.** The brief names CPython as the
  oracle and its `nan`/`inf`/`-inf` spellings as the special values, so the
  layout rules come from the same place rather than being invented: shortest
  digits, exponent form when `decpt <= -4 || decpt > 16`, a trailing `.0` when
  the fixed form would otherwise end at the point, a mandatory exponent sign
  and at least two exponent digits. `tools/sawfloat.py`'s `_render` is that
  rule written out, and `verify --rule` re-checks it against `repr()` over
  50000 random doubles per run (40648 checked while deriving it, zero
  mismatches).
- **`Float.to_string()` returns a plain `String`, not `Result<String,
  AllocError>`.** The brief allowed "the exact allocator-policy shape the
  census says sibling surfaces use", and design 234 documents the whole String
  layer as one of the five panic boundaries "since every producer returns a
  plain `String`". A `Result` here would also collide with the shape the
  compiler already synthesizes for `f.to_string()`, which
  `examples/number_literal_member_access.saw` pins.
- **One module owns the whole story: `std.float`.** It declares
  `Float.to_string`, `Float.to_bits`, `Float.from(bits:)`,
  `String.to_float` and `StringBuilder.append(value: Float)`, with pointer
  comments left in `string.saw` and `stringbuilder.saw`. Declaring the two
  borrowed surfaces there rather than delegating from their own files is what
  keeps ONE routine per direction with no second public spelling invented to
  cross a file boundary.

### The vectors

`tools/sawfloat.py` (`gen` / `verify`), modelled on `tools/sawcbor.py`'s
two-independent-readers scheme. Seed 253, sets emitted sorted, no clock read;
`gen` twice is byte-identical.

- `tests/float_vectors/shortest.tsv` — 2897 rows, `<16 hex bits>TAB<text>`.
  One row is BOTH directions of one value. Boundary rows: 0/-0, the min
  subnormal and its neighbours, both sides of the min normal (including
  `2.2250738585072011e-308`), max finite, every exact power of ten in range,
  sampled powers of two across `2^-1074..2^1023` with both neighbours of each,
  both neighbours of eleven powers of ten, the 2^53 integer boundary, the
  fixed/exponent switch from both sides, and Paxson/Gay stress values. Random
  rows: 1200 uniform bit patterns, 600 realistic magnitudes, 200 subnormals.
- `tests/float_vectors/parse.tsv` — 82 rows, the spellings a formatter never
  emits (exponent forms, `+`, `.5`, `1.`, an 800-digit input, exponents that
  saturate to infinity or zero) and 28 rejections.

`verify` re-derives every row from the case table and byte-compares, THEN
re-checks each row independently: the text parses back to the bits, and no
decimal with fewer significant digits lands on the same double (so the file is
an oracle for "shortest", not a transcript). Rejections are judged against a
second implementation of Saw's OWN grammar, never against `float()`, which
takes whitespace, `infinity`, `NaN` and PEP-515 underscores that Saw does not.

Proof it fails on a wrong value: editing row 6's `5e-324` to `5.0e-324` gives
`FAIL: shortest.tsv differs ... first at line 6`, exit 1. The battery lane is
`floatvectors`.

## Gates

Compiler-tree branch (std + possibly the print path): per-commit full
suite + freestanding via the suite lock (SPLIT pattern, every step
foreground); terminal FULL battery. If unit 1 must touch compiler print
emission (census will say), that commit's scope note says exactly what
moved and reemit/irdet police it.

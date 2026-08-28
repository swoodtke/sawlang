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

## Gates

Compiler-tree branch (std + possibly the print path): per-commit full
suite + freestanding via the suite lock (SPLIT pattern, every step
foreground); terminal FULL battery. If unit 1 must touch compiler print
emission (census will say), that commit's scope note says exactly what
moved and reemit/irdet police it.

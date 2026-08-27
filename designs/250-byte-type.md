# Design 250 — `Byte`: the Byte Type (supersedes 244's target type)

**Status: AUTHORED Aug 27 2026; RULED IN PRINCIPLE same day** (user: "Byte is
the right approach. a UInt8 value is not a Byte, but a Byte is a UInt8 — by
design. everything that uses bytes should use Byte. this is what the strongly
typed aliases was designed for"). §5 is the ruling sheet for the riders;
DISPATCH WAITS on it. **Design 244 is SUPERSEDED IN TARGET, ABSORBED IN
SUBSTANCE**: its census of the String byte surface, its two-conversion-point
analysis and its funnel discipline all carry over — the destination type is
`Byte` instead of bare `UInt8`. **245 §6's `Byte` decline is OVERTURNED**
(annotation on the brief records why; the probes below falsified its cost
premise, and the user's append case falsified "prevents no bug class").

## 1. The ruling and the evidence

The type: `type Byte = UInt8`, a distinct alias with the language's standard
one-way flow — `Byte` degrades to `UInt8` implicitly (reads, comparisons,
masks, calls); the way IN is `Byte(...)` construction or a byte-producing
API. Lead probes, Aug 27 (`.build/scratch/probe_byte_alias{1,2,3}.saw`), all
on the UNMODIFIED compiler:

| cell | result |
|---|---|
| `Byte(65) < 100`, `b & 0x1F`, `let u: UInt8 = b` | all work — decoder math pays NO tax; outward flow covers operators and the literal adopts on the underlying side |
| `report(value: Int)` + `report(b: Byte)`; `report(65)` | `digits`, UNIQUELY — no ambiguity |
| `report(b)` with `b: Byte` | `byte` |
| bare `65` into a `Byte`-only parameter | clean refusal — a literal never becomes a `Byte` by accident |

That refusal is the design's engine: raw-byte semantics are UNREACHABLE
without a `Byte`-typed value, so the digits/byte overload pair that design
244 §4 had to reject on four grounds is simply CLEAN under `Byte` — the
width-flexible-literal ambiguity (ground 3), the silent type-flip switch
(ground 2), and the DF-242c/DF-269a escape-hatch bugs all lose their grip
because no integer value or literal crosses into `Byte` implicitly.

## 2. The surface (unit 0 is the census; this is the shape)

"Everything that uses bytes should use Byte." Byte-VALUED public surfaces
flip their element/value type `Int8`-or-`UInt8` -> `Byte`:

- **String**: `byte_at`, `bytes()`, the `index_of`-by-byte pair (see §4
  naming), plus 244's internal-statics table (`MINUS_SIGN` et al.).
- **StringBuilder**: the byte-append (see §4), fixed-mode byte plumbing per
  244's table.
- **Data**: subscript, `get`, `set`, byte-wise iteration — Data becomes THE
  byte buffer, "a container of `Byte`".
- **FixedBuf / fixedbuf**: same.
- **cbor + json**: the wire-facing byte reads/writes (`cbor.saw:709`'s
  `-> UInt8` accessor and family); module-internal lexical helpers follow.
- **std.net / std.file**: wherever a byte VALUE (not a buffer handle)
  crosses the public surface.
- STAYS `Int8` (C-char plumbing, per 244 §2 verbatim): `withCString`,
  `StringBuilder(bytes: UnsafePointer<Int8>, ...)`, `rebind`, the
  `memcpy`/`__saw_rt_*` extern edges. STAYS `UInt8`: nothing public — the
  underlying type remains the representation and the degradation target,
  and arithmetic RESULTS are naturally `UInt8` until stored back.
- **rt/ seams**: OUT OF SCOPE in v1 — rt/ABI.md freezes that contract;
  `Byte` is representationally identical but the seam SPELLINGS do not
  churn in this brief (§5 Q3 records the ruling to confirm).

The AGGREGATE rule that makes this coherent (the question 245 §6 never
reached): one-way flow is per-VALUE, so `Vector<Byte>` and `Vector<UInt8>`
are distinct — therefore the brief's line is that **byte BUFFERS are `Data`**
(whose element surface speaks `Byte`), `bytes()`-style views return the
byte-elemental container consistently, and the census enumerates every
in-tree `Vector<UInt8>`/`Vector<Int8>` to migrate or justify. No API may
end up making a caller convert a container elementwise.

## 3. Conversion points (244 §3, retargeted)

Same two funnels, `Byte(...)` where 244 spelled `as UInt8`:
- Read funnel (`byte_at`'s C-char `ptr[index]`, an `Int8`):
  `Byte(((raw as Int) & 0xFF) as UInt8)` — widen, mask, narrow, construct;
  free at runtime (the construction is typechecker-only).
- Write funnel (byte value meeting a C-char pointer): degrade
  (`b` flows to `UInt8`) then the checked reinterpret per 244's rule.
The deleted sign-correction helpers (string.saw's to-unsigned,
`_is_continuation`'s apology) stay deleted exactly as 244 planned.

## 4. Naming under `Byte` (244 §4, re-ruled by the type)

- `append_char` -> **`append(b: Byte)`** — the overload the user wanted all
  along, now sound: `append(65)` is digits uniquely; `append(Byte(65))` or
  any Byte-typed value is the raw write. Appending a byte's DIGITS is
  spelled by degrading on purpose: `append(b as UInt8)`... which flows to
  the `UInt(...)`/`Int` rendering overloads — the census confirms which
  spelling lands and the docs teach it.
- `index_of_char`/`last_index_of_char` -> **`index_of(b: Byte)` /
  `last_index_of(b: Byte)`** — the overload set a future String-needle
  search joins, per 244's reasoning, with the needle type now honest.
- `append_byte` as a NAME is dead — the type carries the word.
- 245's `Scalar` stays the character story; `Byte` and `Scalar` are the two
  halves "char" used to blur, now both nominal.

## 5. Ruling sheet (dispatch waits on these)

- **Q1 — annotated-let adoption.** `let b: Byte = 4` is refused today (the
  alias literal rule covers only Int/Float/Bool/String underlyings), so
  every byte constant is `Byte(4)` construction form. Options: (a) accept
  the constructor spelling as the cost of the discipline (zero language
  change; recommended for v1 — argument-position discrimination is
  untouched either way and the statics are one-time spellings); (b) extend
  annotated-slot adoption to aliases over fixed-width integers (a literal
  in a `Byte`-ANNOTATED slot adopts through to `UInt8` and range-checks
  there; argument positions still refuse) — a design-185-family amendment
  with its own small brief if wanted later. v1 proceeds under (a) unless
  ruled otherwise.
- **Q2 — where `Byte` lives.** Recommended: the prelude (core vocabulary
  the way `Duration` is — every byte API names it). Declared once in std's
  core; the census decides the exact file.
- **Q3 — rt seam scope.** Confirm rt/'s Saw sources keep their current
  spellings in v1 (the frozen-ABI argument above); a later brief may
  migrate rt internals when the seam contract is next reopened.
- **Q4 — `Data`'s mutation surface.** `Data.set(index, value)` and the CoW
  subscript take `Byte` (construction required at call sites feeding
  computed integers) — confirm, since this is where the one-way friction
  is most visible in real code.

## 6. Units (after the sheet)

0. CENSUS (agent): every public byte-valued surface + every in-tree
   `Vector<UInt8>`/`Vector<Int8>`/byte-static, tabled with its target
   spelling — the migration's row-by-row test plan (obligation 1: the
   census IS the matrix; the two conversion funnels are the chokepoints).
1. `Byte` lands in the prelude + the String/StringBuilder flip (244's
   scope, retargeted) + §4 overloads + tests incl. the probe cells as
   examples.
2. Data/FixedBuf flip + buffer-rule sweep.
3. cbor/json wire surfaces + remaining census rows; docs
   (spec/skill/README per design 125 — the spec's alias section gains the
   `Byte` exemplar, byte-vs-scalar passage updates).
Obligation 2 (behavioral flip): the census doubles as the consumer sweep —
every flipped signature's callers are enumerated by row; bare literals at
flipped parameters keep compiling only through §4's overload design, and
the suite + bootstrap (blade reads real bytes) police the rest.

## 7. Interactions

DF-242c / DF-269a: no longer load-bearing for this design (nothing here
depends on suffix or label disambiguation); they stay open as their own
bugs. DF-215c, DF-266a: unchanged. Design 209 (slices) and the String-needle
`index_of`: unaffected, later. The `Byte`/`Scalar` pair completes the
"char" split 245 started.

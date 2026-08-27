# Design 245 — `Scalar`: a Unicode scalar type for the String surface

**Status: SCOPING brief, authored Aug 27 out of the design-244 discussion.
BACKLOG — not scheduled. The user has endorsed the headline (`chars()` yields
a type that PRINTS as the character, Aug 27: "a nice usability win"); the §4
questions are unruled.** Independent of 244's byte flip (disjoint call
sites), but reads best beside its rider: bytes and scalars are the two
things "char" used to blur, and after both briefs the String surface says
which it means everywhere.

## 1. What is wrong with scalars-as-`Int`

The spec's current position (design 119): there is no Char type, a scalar is
just an `Int`. Three costs, each observed in tree:

- **A `chars()` loop prints NUMBERS.** `for ch in s.chars() { print("{ch}") }`
  writes `104 105` where every reader expects `h i` — interpolation and
  `print` render the `Int`. This is the usability win that motivates the
  brief.
- **Validity is a use-site Option, silently discardable.** `append_scalar
  (scalar: Int) -> Result<Int?, AllocError>` answers `None` for an invalid
  scalar (negative, surrogate, > U+10FFFF) — a soft refusal the caller can
  drop on the floor, and the tree already does: the design-215 client writes
  `let _ = try! b.append_scalar(scalar: ch)`, which would swallow an invalid
  scalar without a trace. "Never hide errors" says the invalid case should be
  unrepresentable or loud, not ignorable.
- **`Int` cannot say "scalar" in a signature.** A scalar, a count, an index
  and a byte offset all spell `Int`; only labels and docstrings separate
  them.

## 2. The type

A `Scalar` is an integer carrying the invariant 0..0x10FFFF excluding the
surrogate range — Rust's `char`, Swift's `Unicode.Scalar` (UTF-32's value
space). Construction is partial, reading is total — the design-145 raw-backed
idiom applied to a struct:

- `Scalar.from(_: Int) -> Scalar?` — the ONE place validity is checked.
- a total read back to `Int` (§4 decides the spelling).
- Conformances: `Equatable`, `Comparable`, `Hashable`, `Printable` — and
  Printable renders the CHARACTER, which is the point. Trivial Copy tier.

What it deliberately is NOT: a grapheme cluster (Swift's `Character`).
Grapheme segmentation drags Unicode tables into std against the
freestanding-first doctrine, and nothing in the tree asks for it. Strings
remain UTF-8 bytes and scalars; graphemes are a library's problem in a
future that wants one.

## 3. The surface changes

| declaration | today | becomes |
|---|---|---|
| `String.chars()` iterator | yields `Int` | yields `Scalar` |
| `StringBuilder.append_scalar(scalar: Int)` | `-> Result<Int?, AllocError>` (`None` = invalid) | `append(_: Scalar) -> Result<Void, AllocError>` — validity gone from the signature |

The `append(Scalar)` spelling is a deliberate contrast with 244's rider:
`append(UInt8)` was REJECTED because raw-byte append is a different operation
from the `append` family's "render as text" — but appending a scalar's UTF-8
IS rendering it, exactly as `append(Int)` renders digits. Same criterion,
opposite verdicts, both recorded.

Migration size (Aug 27 sweep): 21 `chars()` sites in 15 files, 17
`append_scalar` sites — small. The churn is not the cost; §4 is.

## 4. Open questions (the ruling surface)

1. **Scalar literals are near-mandatory, and their shape is the big
   question.** The same loops that print also COMPARE: the JSON escaper
   writes `if ch == 34`, and a bare integer literal cannot adopt a struct
   type, so without literal syntax that becomes `ch == Scalar.from(34)!` —
   unusable, and the migration would make working code worse. Options: a
   character literal (`'a'`, a lexer addition with its own escape/multi-scalar
   refusal rules), or blessing bare INTEGER literals to adopt `Scalar`
   context (no new syntax, but `ch == 34` then reads as magic). The brief
   leans literal; the ruling decides.
2. **Match patterns and ranges.** `case 'a'...'z'` over a `Scalar` follows
   directly from whichever literal form is chosen; deciding it here keeps the
   classifier idiom (`is_digit`-style code) writable without `as Int` exits.
3. **The total read-back spelling.** `s as Int` (does `as` extend to structs?
   today it is primitives and raw-backed enums) vs a member (`s.value`). The
   145 idiom suggests `as`; the grammar owns the answer.
4. **Prelude or `string.Scalar`?** Design 82's prelude is curated; `Scalar`
   is core vocabulary the way `Duration` is, but every addition is a ruling.
5. **Arithmetic: none.** Decoder/classifier math exits through the total read
   and comes back through `from` — `Scalar` itself gets no `+`/`-`. (A
   recommendation, listed so the ruling can overturn it.)
6. **The `Byte` twin, recommended NO** (same Aug-27 discussion, recorded here
   so it is not relitigated): Saw's `type` aliases are DISTINCT with one-way
   flow, so `type Byte = UInt8` is a newtype with no invariant to carry —
   every `UInt8` is a byte — taxing every literal comparison and every
   String/Data boundary while preventing no bug class. Go's transparent-alias
   flavor does not exist in the language and would be a new feature whose
   payoff is a synonym. One byte type: `UInt8`. (Contrast `Scalar`, which
   earns the newtype by its invariant — that contrast is the criterion.)

## 5. Ordering

After 244 lands (the surfaces are disjoint — 244 touches byte-typed sites,
this touches `chars()`/`append_scalar` sites — but 244 is queued and this is
not, and the rider vocabulary should settle first). Worth deciding relative
to design 209 (string slices) when this is pulled: a slice's `chars()` should
be born yielding whatever this brief rules.

# Design 245 — `Scalar`: a Unicode scalar type for the String surface

**Status: V1 RULED Aug 27 (user) and DISPATCHED — §6 is the landing scope.
The user pulled the core forward ("add scalars() -> Scalar and remove
.chars() now") and ruled the two gating questions: NO literals in v1 (the
total read `value()` and hoisted constants are the compare spellings;
literal syntax stays open), and Scalar is PRELUDE vocabulary. §4's remaining
questions (literal shape, match/range patterns) stay open for a later
unit.** Independent of 244's byte flip (disjoint call sites), but reads best
beside its rider: bytes and scalars are the two things "char" used to blur,
and after both briefs the String surface says which it means everywhere.

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
space). Construction is a FALLIBLE INIT, not a `from` factory (user, Aug 27:
`try?` already converts a Result to the Optional, so the factory would only
subtract the cause):

- `Scalar(_: Int) -> Result<Scalar, InvalidScalar>` — the ONE place validity
  is checked, and the error NAMES the cause (surrogate / out of range /
  negative) exactly as the Optional-init refusal's doctrine demands; a caller
  for whom absence is the answer writes `try? Scalar(x)`.
- a total read back to `Int` (§4 decides the spelling).
- Conformances: `Equatable`, `Comparable`, `Hashable`, `Printable` — and
  Printable renders the CHARACTER, which is the point. Trivial Copy tier.

(The design-145 `from(raw:) -> E?` idiom is NOT the model here and survives
only where it is structural: enums have no `init` at all, so the raw-backed
wire idiom keeps `from`. Everything with an init constructs through it —
the same collapse that retires `Box.make`, see the construction-doctrine
discussion of Aug 27.)

What it deliberately is NOT: a grapheme cluster (Swift's `Character`).
Grapheme segmentation drags Unicode tables into std against the
freestanding-first doctrine, and nothing in the tree asks for it. Strings
remain UTF-8 bytes and scalars; graphemes are a library's problem in a
future that wants one.

## 3. The surface changes

| declaration | today | becomes |
|---|---|---|
| `String.chars()` iterator | yields `Int` | **`scalars()`**, yields `Scalar` |
| `StringBuilder.append_scalar(scalar: Int)` | `-> Result<Int?, AllocError>` (`None` = invalid) | `append(_: Scalar) -> Result<Void, AllocError>` — validity gone from the signature |

The RENAME rides the type flip deliberately (user question, Aug 27: "will
`chars()` returning Scalars bite us when we introduce a grapheme Character?").
The return TYPE never bites — a grapheme view would be a different type over a
different segmentation, and a scalar iterator stays correct forever — but the
NAME does: Rust's `str::chars()` yields scalars and "my emoji came apart" is
its standing footgun, where Swift's `unicodeScalars` never misleads. The
migration already touches every `chars()` site for the element type, so
`scalars()` costs zero extra churn now and leaves `characters()`/`graphemes()`
unencumbered for a future grapheme view (still out of scope, §2).

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
   type, so without literal syntax that becomes `ch == try! Scalar(34)` —
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

~~After 244 lands~~ SUPERSEDED by the Aug-27 pull-forward: v1 dispatches
immediately (the surfaces are disjoint from both DF-215f's compiler fix and
244's byte sites, so nothing is waiting on it). Design 209 (string slices),
when built, is born with `scalars()` — there is no `chars()` left to
inherit.

## 6. The v1 landing (ruled Aug 27 — this is the dispatch scope)

**In:**

- `Scalar` in std, PRELUDE-registered (the prelude list + the `preludegate`
  lane move together): the §2 invariant, `init(value: Int) ->
  Result<Scalar, InvalidScalar>` (lenient labels make `try! Scalar(34)`
  legal), a total `value(&self) -> Int` read, `@synthesize`
  Equatable/Comparable/Hashable, hand-written Printable that renders the
  CHARACTER. `InvalidScalar` is an enum naming the cause (surrogate /
  out-of-range), Printable + Error.
- `String.scalars()` yielding `Scalar`; **`chars()` REMOVED — no alias, no
  deprecation window** (user, Aug 27: nothing char-named survives until a
  grapheme type exists to claim the word).
- `StringBuilder.append(_: Scalar) -> Result<Void, AllocError>` joins the
  append overload family (coherent per §3); `append_scalar` REMOVED with its
  ignorable invalid-`Option`.
- Consumer migration: every `chars()` site (21 in 15 files) and
  `append_scalar` site (17), std included. Compare sites read back
  (`ch.value() == 34`) or hoist a constant; sites are NOT contorted to dodge
  the missing literal — that gap is §4's open question, and honest
  `.value()` reads are the v1 idiom.
- Docs: the spec's access-views passage (bytes/scalars, the Scalar type,
  both removals), the saw-lang skill's string section, README if it names
  `chars()`.

**Out (later units, gated on the §4 rulings):** scalar literals, match/range
patterns over Scalar, any grapheme surface (§2's position stands).

**Gates:** the prelude-list edit makes this a compiler branch — full suite +
freestanding runner (both arches) per commit, full battery terminal.

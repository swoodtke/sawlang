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

## 5. Ruling sheet — ALL RESOLVED Aug 27 (user: "go - your recommendations
## are fine for all three"); DISPATCHED same day

Q1 = (a) constructor form for v1. Q2 = prelude. Q3 = rt out of v1 scope.
Q4 = the sink rule (below, resolved earlier the same day). RIDER ON Q4
(user, at the go): "all values returned from Data and its internal
representation should be Bytes" — Data is STRICT on the read side and in
its own internals (every element-typed internal field, local and helper in
data.saw speaks `Byte` where the element type is expressible; the raw
C-char/pointer plumbing stays per §2's stays-list), LAX only at the public
sink parameters per the sink rule.

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
- **Q4 — `Data`'s mutation surface: RESOLVED Aug 27 (user + probes).** The
  user's rule: `Data.set` accepts "either a UInt8 or a Byte — Data only
  deals with bytes, so it is not ambiguous." Probes
  (`.build/scratch/probe_byte_param.saw`, `probe_byte_tie.saw`) settle the
  spelling: a SINGLE `UInt8` parameter already accepts all three arrivals
  (`Byte` degrades in, bare literals adopt, `UInt8` passes), and the
  `UInt8`/`Byte` overload PAIR is REFUSED at declaration by the existing
  design-53/55 rule ("not just type aliases of the same underlying type") —
  the language forces the single-parameter design. A computed `Int` still
  pays the visible `as UInt8` at the boundary (no implicit narrowing), so
  bare integers cannot silently enter byte storage; only literals and
  byte-typed values pass. GENERALIZED as the brief's SINK RULE (amends §2's
  blanket flip): byte SOURCES return `Byte`; byte SINKS in single-semantics
  domains keep `UInt8` parameters (accepting `Byte` by degradation and
  literals by adoption) — `Data.set`, the CoW subscript, FixedBuf writes,
  the wire encoders' byte writes, and `String.index_of`'s byte needle (no
  digits sibling shares that name, so literals like `index_of(34)` stay
  legal); a `Byte`-TYPED parameter is reserved for DISCRIMINATION POINTS,
  where an integer-rendering sibling shares the name — `StringBuilder`'s
  `append` family is the case that exists.

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

## 8. CENSUS (unit 0, Aug 27) — the row-by-row test plan and consumer sweep

Built from three read-only sweeps plus lead probes on the unmodified compiler.
It doubles as obligation 1's matrix and obligation 2's consumer sweep.

### 8.1 Probe cells re-confirmed (unmodified compiler)

| cell | result |
|---|---|
| `Byte(65) < 100`, `b & 0x1F`, `let u: UInt8 = b`, `sink(b)` at a `UInt8` param | all work |
| `report(value: Int)` + `report(b: Byte)`; `report(65)` | `digits`, uniquely |
| bare `65` into a `Byte`-only parameter | ``argument `b` expects `Byte` but got `UInt8` `` |
| `let b: Byte = 4` | ``cannot assign `UInt8` to variable of type `Byte` `` (Q1's premise) |
| `static X: Byte = 45` | **WORKS** — a bare literal DOES adopt at a `static` of alias type |
| `static X: Byte = Byte(45)` | REFUSED: "must be initialized by a compile-time constant" |
| `[Byte; N]` field, `[Byte(0); N]` repeat literal, `UnsafePointer<Byte>`, `(&arr) as UnsafePointer<Int8>` | all work |
| `borrows -> Byte` over `[Byte; N]`; `b[i] = Byte(9)`; `b[i] = 9` | first two work, the literal write is REFUSED |
| `Int8.from(truncating: <Byte>)`, `<Byte> as Int`, `Optional<Byte>`, `Vector<Byte>`, interpolation | all work |
| `append(b as UInt8)` (§4's stated digits spelling) | **AMBIGUOUS** — see §8.6 errata |
| `Vector<Byte>` at a `Vector<UInt8>` parameter/return/field | **codegen ICE**; the `let` form silently succeeds — see DF-270b |

### 8.2 Where `Byte` lives

`sawc/builtin.saw`, `public type Byte = UInt8`. **Zero compiler change was
needed.** `builtin.saw` is exempt wholesale from design 204's identity
qualification, is loaded before every std file, is not an import-required
module, and is the only home that also works under `--runtime-build` (std is not
loaded there), which keeps a later rt migration open. `preludegate` needs no new
spec module-table row (builtin declares prelude vocabulary with no module) and
`stdtypes` is unaffected. `public` is REQUIRED — a private std alias gets the
identity `Byte$m$std_<leaf>` and is invisible.
`extension Byte { ... }` is refused ("cannot extend undefined struct"), so
`Byte` carries no methods and needs no file of its own.

### 8.3 String / StringBuilder (unit 1)

| site | today | target |
|---|---|---|
| `string.saw:46` `byte_at` | `-> Int8` | SOURCE `-> Byte`, **the READ FUNNEL** |
| `string.saw:124` `_is_whitespace(b:)` | `Int8` | `Byte`; the four `(N as Int8)` casts deleted |
| `string.saw:410/424` `index_of_char`/`last_index_of_char` | `Int8` param | RENAME `index_of`/`last_index_of`, needle `UInt8` (§5 Q4) |
| `string.saw:771` `_ubyte_at` | sign fold + widen | **the fold is deleted, the WIDENING SURVIVES** — the decoder assembles scalars at `Int` width (`(b0-224)*4096` does not fit a byte); 20 call sites unchanged |
| `string.saw:361/380` `(… as Int) & 255` | signed-era mask | mask deleted |
| `string.saw:492` `to_data` | `UInt8.from(truncating: byte_at(i))` | `data.push(self.byte_at(i))` |
| `string.saw:1057/1059` `StringBytes` | `Int8` | `Byte` |
| new `string.saw` `to_c_char(b: UInt8) -> Int8` | — | **the WRITE FUNNEL**, entry points named in its docstring: `_substring`, `to_uppercase`, `to_lowercase`, `replace`, `fromBytes`, `Vector<String>.join` |
| `stringbuilder.saw:22/28-30` statics | `Int8`/`Int` | `Byte` (literal form, §8.1) |
| `stringbuilder.saw:235` `append_char(c: Int8)` | — | **DISCRIMINATION**: `append(b: Byte)` |
| `stringbuilder.saw:299` `_is_continuation` | sign fold | fold deleted, param `Byte` |
| `stringbuilder.saw:305` `_place_char` | `Int8` | `Byte`, funnels through the new `_c_char` |
| `stringbuilder.saw:362` `_scalar_byte(u: Int)` | `-> Int8` | `-> Byte` |
| new `stringbuilder.saw` `_c_char(b: Byte) -> Int8` | — | **the WRITE FUNNEL** for this file: `_place`, `_place_char`, `_overflow`, `_mark_truncated` |
| `strlen`/`__saw_string_*`/`memcpy`/`withCString`/`StringBuilder(bytes:)`/`rebind`/`buffer` | `Int8` | STAYS (§2 stays-list) |

### 8.4 Data / FixedBuf (unit 2)

Sources -> `Byte`: `DataBuf.at`, `Data.get`, `Data.pop`, `DataIterator`'s
`type Item` + `next`, `FixedBuf.get`. Sinks stay `UInt8`: `Data.set`,
`Data.push`, `FixedBuf.set`. Internals speak `Byte` per the Q4 rider:
`DataBuf.store`, `Data._store_at`, the `UnsafePointer<Byte>` element views,
`FixedBuf.data: [Byte; N]`. C-char plumbing stays `Int8`: `DataBuf.buffer`,
`head`, `absorb`, `memcpy`, `append_bytes`, `byte_ptr`, `FixedBuf.ptr`.
`FixedStringBuilder.append_char` -> `append(b: Byte)` (a discrimination point:
`append(String)`/`append(Int)`/`append(UInt)` already share the name).

**`Data.[]` (data.saw:212) STAYS `UInt8`, and this is the one place the sink
rule and the strict-reads rider meet.** A `borrows -> T` has ONE `T` for the
read and the write, and §5 Q4 names "the CoW subscript" in the sink list. Probe:
under `borrows -> Byte`, `d[i] = 42` is refused (``cannot assign `UInt8` to
element of type `Byte` ``), which is live at `data_cow_value_semantics.saw:78`,
`data_place_shared_read.saw:66,73`. `get`/`pop`/iteration carry the strict read
side; `d[i]` keeps the spelling its four in-tree write sites depend on.

### 8.5 The aggregate rule — ZERO migrations owed

Tree-wide there are **five** `Vector<UInt8>`/`Vector<Int8>` occurrences, all in
`examples/`, and every one is a language-rule PIN whose point is the fixed-width
type (`assignment_target_adopts_fixed_width`, both `df165b_place_literal_*`,
conformance `W20`/`W23`). Flipping any of them would destroy the pin. There is
no `Vector<UInt8>` in `sawc/`, `blade/`, `libs/`, `devtools/`, `selfhost/` or
`sos/`: byte buffers are already `Data`. Every byte-typed `static`/fixed array
in the tree is an arena, a `.bss` region, an MMIO backing store or a C scratch
buffer — untyped memory, not a byte value stream — and stays.
**The aggregate wall was therefore never met in this migration**, which is
fortunate, because it is DF-270b rather than a clean refusal.

### 8.6 Errata against this brief, found by the census

1. **§4's digits spelling is wrong.** `append(b as UInt8)` is AMBIGUOUS —
   a `UInt8` matches `append(value: Int)` and `append(value: UInt)` equally, and
   that tie predates the byte overload. The working spelling is
   `append(b as Int)`. Pinned by `examples/errors/byte_digits_spelling_is_as_int.saw`.
2. **§4 vs §5 Q4 on the `index_of` needle.** §4 spells `index_of(b: Byte)`,
   §5 Q4 spells the `UInt8` sink and says literals stay legal. Q4 governs
   (it is the ruling sheet and explicitly amends the earlier text): the needle
   is `UInt8`, so `index_of(47)` compiles.
3. **§5 Q1's "constructor form" does not reach a `static`.** `static X: Byte =
   Byte(45)` is refused as a non-constant initializer; `static X: Byte = 45`
   works, because a bare literal DOES adopt at a `static` of alias type while it
   does not at an annotated `let`. The statics therefore flip with no ceremony.
   The `let`/`static` disagreement is DF-270a.
4. **244 §5's `sos/hal/arm64/kernel/lib.saw` row is a FALSE POSITIVE.** Those
   three sites are a GIC register-block `byte_at(base:line:) ->
   UnsafeMemory<UInt8, Device>` that shares only the spelling. `sos/` and
   `sawc/rt/` contain no `import std.string`/`std.data` at all, so nothing there
   breaks and **this branch does not touch `sos/`**.
5. **The one silent-flip site in the tree** was
   `examples/alloc_stringbuilder_reports_oom.saw:51` `c.append_char(100)` — the
   only `append_char` anywhere whose argument was a bare literal. Every other of
   ~107 sites carried an explicit `as Int8` / `Int8.from(truncating:)` / `to_i8`
   and broke loudly. It is now `c.append(Byte(100))`.
6. **§1's evidence table is INCOMPLETE, and one row of the design is HELD.**
   `Byte(65) < 100` works, but only because both sides are below 128: an ORDERED
   comparison whose LEFT operand is a distinct alias over an unsigned underlying
   is lowered SIGNED, so `Byte(255) <= Byte(127)` is `true` and
   `Byte(255) > Byte(127)` is `false` (DF-270d). It is one mechanism with a
   second, PRE-EXISTING face that needs no alias at all —
   `UInt.max.compare(&1)` answers `Less` — so `Comparable.compare()` is wrong
   on every unsigned integer today. Consequence for this brief: `std.cbor`'s
   `byte_at` and its UTF-8 boundary table STAY `UInt8`, because `utf8_width`
   and `compare_in` order the bytes they read and a `Byte` there makes the
   validator accept the malformed input it exists to reject (caught by
   `cbor169_vectors`, not by review). Everything design 250 did land is
   comparison-safe, verified by run rather than by reading: `to_uppercase`,
   `to_lowercase`, `trim` and the fixed builder's UTF-8 cut all behave on
   `"café"`, because each of their ordered tests happens to map identically
   under both lowerings. Pin: `examples/unsigned_ordered_comparison.saw`.
7. **`blade/src/lock.saw:114`'s manifest hash changes value once.** Its djb2
   folds `byte as Int`, which was a sign-extend and is now a zero-extend. No
   test pins a literal hash (every `blade/tests/lock_*` compares
   computed-against-computed), so the change is self-healing; `bootstrap` is the
   covering gate.

### 8.7 Consumers, tree-wide

| tree | rows |
|---|---|
| `sawc/std/path.saw` | 4 `last_index_of_char(N as Int8)` -> `last_index_of(N)`; 3 `byte_at(..) == (47 as Int8)` -> `== 47` |
| `sawc/std/process.saw` | `static EQUALS_BYTE: Int8` -> `Byte` |
| `sawc/std/json.saw` | `raw_char(c: Int8)` -> `raw_byte(b: UInt8)` (sink) + 10 call sites; `_hex_digit -> UInt8`; two sign folds deleted (`write_json_string`, `_ubyte_at`); 8 escape-decoder appends -> `append(Byte(N))`; the `byte_at`-straight-into-`append` site becomes `append(<Byte>)` |
| `sawc/std/fixedbuf.saw` | `append_char` -> `append(b: Byte)` |
| `sawc/std/net.saw`, `file.saw`, `env.saw`, `directory.saw`, `serde.saw` | no edit (pointers, raw backings, and `Int8.from(truncating:)` which projects an alias) |
| `libs/toml/src/lib.saw` | 2 `index_of_char(61 as Int8)` -> `index_of(61)` |
| `selfhost/lexer/src/lib.saw` | `ubyte`'s fold deleted; `to_i8 -> Int8` becomes `to_byte -> Byte`; 27 `append_char` sites |
| `selfhost/lexer/tests/*.saw` | 47 `append_char(N as Int8)` -> `append(Byte(N))` |
| `devtools/dogfood/programs/llm_client.saw` | ZERO edits (every comparison is a bare literal or `as Int`) |
| `devtools/dogfood/programs/w1_filesearch.saw` | `d.push(UInt8.from(truncating: b))` -> `d.push(b)` |
| `blade/src/lock.saw` | no edit; hash value changes (§8.6 #7) |
| `examples/` | 11 files; the discrimination site is §8.6 #5 |
| `examples/conformance/INDEX.md` | row A10's text names `append_char` |

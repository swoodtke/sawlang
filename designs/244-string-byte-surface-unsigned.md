# Design 244 — the String byte surface goes unsigned

**Status: RULED Aug 26 (user) — bytes are unsigned. QUEUED second, behind
DF-215f's fix. Not yet dispatched.** One open question rides it (the `*_char`
naming rider, §4), to be ruled before or at dispatch.

## 1. The ruling and why

`String.byte_at` and `bytes()` return `Int8`. That was never decided: design 38
says only "match `byte_at`'s existing return type", and the signedness is
inherited from the earliest String internals — the `UnsafePointer<Int8>` that
is C's `char`. Everything since has treated bytes as unsigned:

- `Data`'s subscript and `get` yield `UInt8`; `FixedBuf` likewise; cbor's own
  `Data` accessor (`cbor.saw:709`) is `-> UInt8`. The String layer is the one
  odd surface, so the language has two byte types for one concept depending on
  which container the byte came from.
- std pays a sign-correction tax at its own hot paths: `string.saw`'s UTF-8
  decoder carries an internal to-unsigned helper (`if raw < 0 { raw + 256 }`,
  ~line 772-778, with a comment explaining that a byte >= 0x80 sign-extends),
  and `stringbuilder.saw`'s `_is_continuation` (~line 301) carries the same
  correction with the same apology.
- The design-215 dogfood rewrite (the fresh-reader instrument) wrote
  `u8`-suffixed comparisons against `String.byte_at` ~25 times before the
  diagnostics taught it otherwise — the reader's expectation IS unsigned. Rust
  (`u8`), Swift (`UTF8View`'s `UInt8`) and Go (`byte` = `uint8`) all agree.
- The one property signedness offers — a byte >= 0x80 reads negative, a cheap
  non-ASCII test — is spelled `b >= 0x80` in the unsigned world, more legibly.
  In the signed world the unsigned spelling is not merely awkward but
  UNWRITABLE: `b >= 128` overflows the `Int8` literal.

So: **every value-level byte on the String surface becomes `UInt8`.** Raw
POINTERS stay `Int8` — `UnsafePointer<Int8>` is the C-char ABI at the FFI
boundary, and the line this brief draws is: pointers are C-shaped, values are
bytes.

## 2. The surface

Flips (value-level, all in the String layer):

| declaration | today | becomes |
|---|---|---|
| `String.byte_at(&self, Int) unsafe` | `-> Int8` | `-> UInt8` |
| `StringBytes.next(&var self)` (what `bytes()` iterates) | `-> Int8?` | `-> UInt8?` |
| `String.index_of_char(&self, c: Int8)` | `Int8` param | `UInt8` param |
| `String.last_index_of_char(&self, c: Int8)` | `Int8` param | `UInt8` param |
| `StringBuilder.append_char(&var self, c: Int8)` | `Int8` param | `UInt8` param |

plus the internal `Int8` byte statics (`MINUS_SIGN` etc.) and helpers beside
them. Stays `Int8` (C-char plumbing, out of scope on purpose):
`String.withCString` (`UnsafePointer<Int8>`), `StringBuilder(bytes:
UnsafePointer<Int8>, capacity:)` and `rebind`, the `memcpy`/
`__saw_string_from_bytes` externs.

Deleted outright by the flip: the `string.saw` to-unsigned helper and the
`_is_continuation` correction — the decoder's `b0 < 128` comparisons et al.
become directly valid on `UInt8` (and `>= 0x80` becomes writable).

## 3. The two conversion points

The whole signed/unsigned meeting is confined to where a byte VALUE meets a
C-char POINTER, both inside the String layer, and the checked-`as` rule is
why the spelling matters (a checked cast panics on the first byte >= 0x80 —
the `string.saw:492` comment already warns about exactly this, design 170):

- **Read funnel** (`byte_at`'s `ptr[index]`, an `Int8`):
  `(((raw as Int) & 0xFF)) as UInt8` — widen (always fits), mask, narrow
  (0..255 always fits). No panic is reachable.
- **Write funnel** (`append_char` storing a `UInt8` into the `Int8` buffer):
  `let v = c as Int; (if v >= 128 { v - 256 } else { v }) as Int8` — the
  inverse, no panic reachable.

Everything else in the tree compares and passes byte VALUES and never touches
a pointer, which is what makes the migration mechanical.

## 4. The naming rider (OPEN — wants a ruling at or before dispatch)

`index_of_char`, `last_index_of_char` and `append_char` are byte-typed but
named "char", and the language deliberately has no Char type (scalars are
`Int`). The doctrine is "APIs do the expected thing": a reader handed
`append_char(c: UInt8)` will pass a scalar and be wrong the moment it exceeds
one byte. RECOMMENDATION: rename to `index_of_byte` / `last_index_of_byte` /
`append_byte` in the same migration — ~83 call sites outside std already need
no edit for the type flip alone (bare literals adopt the new context), so the
rename is the only reason those sites would be touched; one migration beats
two. If the rename is declined, the type flip proceeds alone and the naming
question dies here with that ruling recorded.

## 5. Consumer sweep (obligation 2)

`byte_at`/`bytes()` call sites, whole tree, Aug 26 (~110 sites, 18 files):

| tree | files | sites | character |
|---|---|---|---|
| `sawc/std` (string, stringbuilder, path, process, net) | 5 | ~58 | flips with the surface; string.saw is 49 of them (its own decoder/scanner loops) |
| `sawc/std/cbor.saw` | 1 | 10 | its OWN `Data` accessor, already `UInt8` — untouched, and the convention's in-tree witness |
| `devtools/dogfood/programs/llm_client.saw` | 1 | 14 | bare-literal comparisons; adopt `UInt8` context with no edit (the `Data`-side `u8` suffixes are already right) |
| `sos/hal/arm64/kernel/lib.saw` | 1 | 3 | freestanding consumer — the flip TOUCHES sos/, so sos_runner joins the gate |
| `examples/` | 5 | ~25 | suite-covered; literal-context flips |

Who relies on SIGNEDNESS (the behavioral contract being flipped): only the two
internal corrections this brief deletes. The one external reliance ever
written — the Aug-12 llm_client stub's "a byte >= 0x80 reads negative keeps
continuation bytes out of the ASCII branches" — was replaced by the Aug-26
rewrite, which is sign-agnostic (all its comparisons are < 0x80). No other
consumer compares a String byte against a negative value or exploits
sign-extension; the sweep found no `< 0` test against a `byte_at` result
outside `string.saw`'s own deleted helper.

## 6. Ordering

Before design 209 (string slices): 209's brief names `byte_at` among the
primitives its view type re-exports, and landing 209 first would migrate the
same surface twice. After DF-215f's fix (user, Aug 26): a correctness bug
outranks a consistency flip.

## 7. Units and gates

- **Unit 0 — census + rows.** Enumerate every declaration and call site the
  flip touches (the §5 grid refreshed at dispatch), check
  `examples/conformance/INDEX.md` for rows naming the accessor surface (the
  accessor-rule rows cite `String.byte_at`'s bounds panic — semantics
  unchanged, text updated if it names `Int8`), and list the doc passages owed
  (§ unit 3).
- **Unit 1 — the std flip.** The §2 table, the §3 funnels, the two deletions,
  the internal statics; the rename rider if ruled. Full suite + freestanding
  (both arches) green.
- **Unit 2 — consumers.** sos hal, examples; llm_client should need zero edits
  (verify, don't assume). Oracle-dense and mechanical once unit 1 lands — the
  stale spellings all fail loudly (`Int8`/`UInt8` comparison is a type error).
- **Unit 3 — docs.** LANGUAGE_SPEC (the access-views passage — this supersedes
  the Aug-26 parenthetical patch, which taught the signed trap the flip now
  deletes), the saw-lang skill's string section, README if it names the
  surface. saw-docs voice.

Gates: std ships with the compiler, so this is a COMPILER-scoped branch —
per-commit full suite + `tools/freestanding_runner.py` (both arches); it
touches `sos/`, so sos_runner too. Terminal: the full battery.

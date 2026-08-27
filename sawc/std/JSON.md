# `std.json` — JSON over the `Encoder`/`Decoder` seam

This document is the contract for `sawc/std/json.saw`, on the same terms
`sawc/std/CBOR.md` is the contract for `sawc/std/cbor.saw`.

Base format: **JSON, RFC 8259**. `JsonEncoder` is an `Encoder`
(`std.serde`) and `JsonDecoder` is a `Decoder`, so any `Serialize`/
`Deserialize` value travels over them:

```saw
import std.json.{JsonEncoder, JsonDecoder}

var enc = JsonEncoder()
try entry.serialize(to: &var enc)
let text = try enc.finish()

var dec = try JsonDecoder.open(text: text)
let back = try LockEntry.deserialize(from: &var dec)
try dec.finish()   // rejects content left over after the value
```

## Status: Unit 2 only — there is no `JsonValue` tree

The brief that commissioned this file asked for two things: a `JsonValue`
data-model type (parse text to a tree, write a tree back to text) and this
`Encoder`/`Decoder` seam. **Only the seam shipped.** The tree needs a type
that holds itself — an array of `JsonValue`, an object mapping to
`JsonValue` — and that shape hits an internal compiler error today: a
struct or enum that reaches itself through a `Vector`/`Map`/`Box` type
argument, even indirectly (one level of `Box<Self>?` is enough), defeats
the codegen type-registration order. This reproduces on a plain,
non-generic, two-struct MUTUAL cycle too (`A` holding `Vector<B>`, `B`
holding `Vector<A>`) — it is not particular to self-reference. See the
finding filed against the tracker for the minimal repro and the mechanism.
Building `JsonValue` around that gap — a type-erased payload, an
`UnsafeMemory` cell, an index-into-a-side-table arena standing in for the
tree — would be exactly the kind of workaround this project's conduct
rules forbid, so the tree is deferred behind that compiler fix rather than
shipped in a shape nobody would choose on its own merits.

Practically: there is no `JsonValue.parse(text:)`, no
`JsonValue.to_json_string()`, no accessor surface (`get`/`at`/`as_int` and
so on). A caller that wants "parse arbitrary JSON into a tree and walk it"
has nothing here yet. A caller with a Saw type shaped like its JSON
document — the overwhelmingly common case for a wire format — reads and
writes it directly through `Serialize`/`Deserialize`, exactly as with
`std.cbor`.

## What a `Serialize` value becomes

| Saw | JSON |
|---|---|
| `UInt`, `UInt8`..`UInt64` | a JSON number, integral, via `write_uint`/`read_uint` |
| `Int`, `Int8`..`Int64` | a JSON number, integral, via `write_int`/`read_int` |
| `Bool` | `true` / `false` |
| absent `Optional` | `null` |
| present `Optional` | the payload's own encoding |
| `String` | a JSON string, fully escaped |
| `Vector<T>` | a JSON array of the element encoding |
| a struct | a JSON **array** of its stored fields, declaration order |
| a raw-backed enum | the case's raw value, as an integral JSON number |

A struct is an **array of fields, not an object of names** (design 169
decision 2 — the shape is format-agnostic and this file does not
reinterpret it for JSON's sake, exactly as `std.cbor` does not). If you
want JSON that reads like `{"port": 8080, ...}` for a human, this seam
does not produce it — that would need per-field names threaded through a
format-specific path the `Serialize`/`Deserialize` pair does not carry.

`Map<K, V>` has **no derived encoding** — the `@synthesize` field walk
does not cover it, in either format (see `sawc/std/serde.saw`'s doc
comment on `Serialize` for the exact list). Encode one by writing
`serialize`/`deserialize` by hand over `begin_map`/`begin_array` and the
scalar `write_*`/`read_*` calls; `examples/json_map_keys.saw` is the
worked example. A JSON object key is always a string by grammar, so a map
keyed by anything else has no representation: `EncodeFault.Unsupported`
on encode (reported the moment a non-`write_text` call lands at a key
position), and `DecodeFault.Malformed` on decode (the bytes are invalid
JSON regardless of which key type was intended — a key position that
isn't a `"` is rejected structurally, before any typed read is even
attempted).

**No `Float`.** Neither `write_float` nor `read_float` exists on the
`Encoder`/`Decoder` trait at all — this is the seam's own limit, not a
JSON-specific one, and `std.cbor` is under the identical restriction for
the identical reason (`Float` has no settled serialization story yet). A
`Serialize` value can never ask this encoder for one. Consequently
`read_int`/`read_uint` reject a fraction- or exponent-shaped JSON number
token as `DecodeFault.TypeMismatch` — it parses as a well-formed number,
just not an INTEGRAL one, which is the only shape either method can
produce.

**No byte strings.** `begin_bytes`/`write_byte` and their decode twins are
`EncodeFault.Unsupported` / `DecodeFault.Unsupported` unconditionally —
JSON has no binary type, and v1 invents no base64-style convention for
one (an explicit non-goal, not an oversight).

## Encoding

Compact: no inserted whitespace anywhere. Every control character (below
U+0020), `"` and `\` in a text string is escaped — the named short escapes
(`\n`, `\t`, `\"`, `\\`, `\/` is NOT written since `/` needs no escaping
on output, `\b`, `\f`, `\r`) where one exists, `\u00XX` otherwise; every
other byte is copied through unexamined, because the source is a Saw
`String` and a Saw `String` is always valid UTF-8 by construction — there
is nothing to re-validate on the way out.

## Decoding

Strict RFC 8259, and malformed input never panics — every rejection is
`Err(DecodeError)` naming the byte offset that stopped it:

- **Numbers**: no leading zero except a lone `0`, no leading `+`, a `.`
  must be followed by at least one digit, an exponent must have at least
  one digit. `read_uint`/`read_int` additionally reject a float-shaped
  token (`TypeMismatch`) and an integral token outside the target's range
  (`OutOfRange`).
- **Strings**: every control byte must be escaped (a raw one is
  `Malformed`); `\uXXXX` is validated including **surrogate-pair
  combination** — a high surrogate (`U+D800..U+DBFF`) must be followed
  immediately by `\uXXXX` naming a low surrogate (`U+DC00..U+DFFF`), and
  a lone or wrongly-paired surrogate on either side is `Malformed`.
- **Structure**: no trailing comma in an array or object, no comment, no
  `NaN`/`Infinity`, a nesting-depth limit (`TooDeep`, `max_depth`,
  default 64).
- **Duplicate object keys: last wins.** A pinned default, not an RFC
  requirement — RFC 8259 leaves the policy unspecified ("the behavior of
  software that receives such an object is unpredictable"). Flagged OPEN
  for the user's ruling; `std.cbor`'s DETERMINISTIC profile rejects a
  duplicate key outright, which was the other candidate.
- **One top-level value, checked from the far end.** Unlike
  `CborDecoder.open`, `JsonDecoder.open` does **not** pre-validate the
  whole input in one pass. A CBOR item declares its own length in its
  header, so CBOR can validate "exactly one top-level item, nothing
  malformed anywhere" before any typed read runs. A JSON container does
  not declare its length — it is only known once its closing bracket is
  found — so building that same up-front index would need exactly the
  self-referential shape `JsonValue` cannot have right now (a tree walk
  that isn't a tree). Instead: `begin_array`/`begin_map` discover their
  item count with a bounded, **iterative** lookahead (no native
  recursion, so a hostile depth is caught by `max_depth` before it can
  reach the call stack), every byte is still fully grammar-validated the
  moment a typed read visits it, and **trailing content after the
  top-level value is checked by calling `JsonDecoder.finish` once the
  value has been fully read** — not by `open`. Forgetting to call it
  means a decode that silently ignores whatever follows the value, which
  is why every example and every call site in this file calls it.

## Decoder limits

`JsonDecoder.open` takes `max_depth` (default 64) and `max_size` (default
16 MiB, checked immediately against the input length) as constructor
parameters, on `CborDecoder.open`'s terms — the caller knows what it is
reading. There is no `max_items` limit in v1 (`std.cbor` has one); the
size and depth limits already bound memory and stack use, and adding an
item-count budget on top is deferred.

## What is OPEN (not decided by this brief)

- Pretty-printing: no surface for it exists (compact-only, matching
  `std.cbor`'s "one spelling per value" discipline, though JSON's own
  history leans toward wanting one).
- Duplicate-key policy: pinned to last-wins above; needs ratification.
- The `JsonValue` tree itself, entirely: parse-to-DOM, DOM-to-text,
  accessor surface — blocked on the recursive-type compiler defect
  described above.
- Streaming/incremental parsing: not attempted.

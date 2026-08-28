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

For a single value there is a one-call form, `encode`:

```saw
import std.json

let text = try json.encode(&entry)
```

`std.cbor` declares an `encode` of its own. The two are separate modules and
so are the two names: the qualified spelling says which is meant, and a file
that takes both bare gets an ambiguity error at the call rather than one of
them silently. Reach for the two-step form above when several values share a
buffer or the nesting limit needs changing.

The matching `decode<T>(text:)` cannot be written yet, for the same reason
`std.cbor` has no `decode<T>` (DF-169e: a static trait requirement is not
callable on a type parameter). Read a value back through the type's own name,
as the first example does.

## Status: units 1-3 — `JsonValue` exists and serializes fully

The brief that commissioned this file asked for two things: a `JsonValue`
data-model type (parse text to a tree, write a tree back to text) and the
`Encoder`/`Decoder` seam above. Unit 2 shipped the seam first, deferred
behind the recursive-type compiler defect design 246 went on to fix; unit 1
landed `JsonValue` itself once that fix landed; unit 3 closed the one
serialization gap unit 1 shipped with (`Object`, below):

```saw
import std.json.{JsonValue}

let v = try JsonValue.parse(text: "\{\"port\":8080,\"tags\":[\"a\",\"b\"]}")
let port = v.as_object()!.get("port")!.as_int() ?? 0
let text = try v.to_json_string()   // every case, Object included
```

`JsonValue` is `enum JsonValue { case Null, case Bool(value: Bool),
case Number(value: Int), case Float(value: Float), case Text(value: String),
case Array(items: Vector<JsonValue>),
case Object(fields: Map<String, JsonValue>) }`, `ExplicitCopy` (design 251 —
`Map`/`Vector` gained a copy conformance for `Object`/`Array`'s payload to
lean on; `@synthesize`d, so `copy()` recurses through both). `Object` key
order is not preserved, matching `Map` everywhere else in std.

**Numbers take the pinned rule, both halves of it** (design 253 landed the
`Float` surface it was waiting on). A number token that is lexically integral
AND fits `Int`'s range is a `Number`; everything else — a fraction, an
exponent form, an integral token past `Int` — is a `Float`, correctly rounded
to the nearest double. The TOKEN decides, not the value: `1` is `Number(1)`
and `1.0` is `Float(1.0)`, which is what lets a document round trip through
the tree without a `1.0` quietly becoming an integer. The SPELLING is not
preserved (`1e2` comes back as `100.0`) — the tree holds values, not source
text. `as_int` and `as_float` read the two cases; there is no combined
`as_number`, because Saw has no `Int` -> `Float` conversion to widen the
integral case with.

A `Float` that is not finite has no JSON spelling, so `to_json_string`
reports `EncodeFault.Unsupported` rather than emitting `Infinity` or `NaN`.
The one way to get one out of `parse` is an exponent JSON accepts and IEEE
754 cannot hold (`1e400` saturates to an infinity), so the loss is reported
where the document would be written rather than where it was read.

`to_json_string` serializes every case now, `Object` included
(`Null`/`Bool`/`Number`/`Text`/`Array`/`Object`, nested arbitrarily deep in
any combination). Writing an `Object` needs its keys enumerated, and every
avenue to do that (`Map.keys`/`each`/`each_key`/`each_value`) has a closure
parameter that deliberately carries no `sync` (design 216, so a suspending
body composes) — which makes each of them a "maybe-suspending" API.
`JsonValue._write` is unavoidably self-recursive (an array/object element
may itself be an array or object), and a self-recursive function defined
under `sawc/std/` that also transitively reaches a maybe-suspending API used
to fail `sawc`'s own "builtins" pre-check with `internal compiler error:
builtins failed to type-check` / `cannot suspend in a sync closure
context` — even though the identical shape compiled and ran correctly as an
ordinary (non-`sawc/std/`) source file (DF-267d). Both `Array` and `Object`
now route their recursion through a visitor closure (`Vector.each` /
`Map.each`) rather than a direct self-call, which is the shape that clears
the builtins pre-check — see `_write`'s doc comment in `sawc/std/json.saw`
for the full mechanism and this unit's landing report for the repro.

Everything — `parse`, every accessor, the full round trip, the whole seam
above — works and is tested (`examples/json_value_*.saw`).

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

**No `Float` ON THE SEAM.** Neither `write_float` nor `read_float` exists on
the `Encoder`/`Decoder` trait — this is the seam's own limit, not a
JSON-specific one, and `std.cbor` is under the identical restriction for the
identical reason: what a `Float` looks like on a WIRE is a question design 253
deliberately left open, having settled only the TEXT question. A `Serialize`
value can never ask this encoder for one. Consequently `read_int`/`read_uint`
reject a fraction- or exponent-shaped JSON number token as
`DecodeFault.TypeMismatch` — it parses as a well-formed number, just not an
INTEGRAL one, which is the only shape either method can produce.

`JsonValue` is not bound by that: it reaches `JsonEncoder`'s own
`write_float` and `JsonDecoder`'s own `float_span`, neither of which is a
trait requirement. A tree is text in and text out, so nothing about it waits
on a wire encoding.

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
  Observed through `JsonValue` too now (`examples/json_value_structural_
  reject.saw`'s `duplicate_key_last_wins`).
- A combined `JsonValue.as_number() -> Float?` reading either number case,
  which needs an `Int` -> `Float` conversion the language does not have in
  any spelling. (`JsonValue.Number`'s `Float` half itself is CLOSED —
  design 253 landed it; see the status section above.)
- `max_items` parity with `CborDecoder`: `std.cbor`'s decoder has one, this
  one does not (see the decoder-limits section above) — scope-narrowed out
  of this brief, stays open.
- There is no combined `member(key:)`/`element(at:)` convenience accessor
  (DF-267c): `as_array`/`as_object` lend the whole container, and
  navigation composes through `Vector`/`Map`'s own accessors at the call
  site (`value.as_object()!.get("key")`). A hand-written `borrows`
  accessor cannot `lend` a place reached by indexing FURTHER into a
  `match`-bound payload (confirmed for both `Vector`'s unconditional `[]`
  and `Map`'s conditional `[]`/`get` — see this unit's landing report), so
  a single-call accessor doing the match-and-index in one body is not
  expressible today.
- Streaming/incremental parsing: not attempted.

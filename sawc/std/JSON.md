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

## Status: units 1 and 2 — `JsonValue` exists; `Object` does not serialize yet

The brief that commissioned this file asked for two things: a `JsonValue`
data-model type (parse text to a tree, write a tree back to text) and the
`Encoder`/`Decoder` seam above. Unit 2 shipped the seam first, deferred
behind the recursive-type compiler defect design 246 went on to fix; unit 1
lands `JsonValue` itself now that the fix has landed:

```saw
import std.json.{JsonValue}

let v = try JsonValue.parse(text: "\{\"port\":8080,\"tags\":[\"a\",\"b\"]}")
let port = v.as_object()!.get("port")!.as_int() ?? 0
let text = try v.to_json_string()   // Array/scalar trees only — see below
```

`JsonValue` is `enum JsonValue { case Null, case Bool(value: Bool),
case Number(value: Int), case Text(value: String),
case Array(items: Vector<JsonValue>),
case Object(fields: Map<String, JsonValue>) }`, `NoCopy` (a `Map` payload
has no `ExplicitCopy` conformance yet regardless of the recursion, so this
was never a choice). `Object` key order is not preserved, matching `Map`
everywhere else in std.

**Two things remain incomplete, both compiler-defect-shaped, both filed:**

- **Numbers are `Int`-only** — the pinned rule ("integral and in `Int`
  range -> `Number`, else `Float`") cannot be honored: std has no
  correctly-rounded `Float`<->text conversion (`String.to_float` is
  explicitly documented as a NOT-correctly-rounded naive accumulation, and
  there is no `Float`->text direction in std at all). A fraction-/
  exponent-shaped token, or an integral one outside `Int`'s range, is a
  decode error carrying `JsonDecoder.read_int`'s own fault
  (`TypeMismatch`/`OutOfRange`) rather than becoming a `Number(value:
  Float)`. Temporary, pending a correct `Float` parse/format surface in std.
- **`to_json_string` does not serialize `Object`** (`EncodeFault.Unsupported`)
  — `Null`/`Bool`/`Number`/`Text`/`Array` (nested arbitrarily, including
  arrays of arrays and arrays of objects) serialize fully, and `parse`
  builds a full `Object` (parsing only ever calls `Map.insert`, which the
  defect below does not touch). Writing an `Object` needs its keys
  enumerated, and every avenue to do that (`Map.keys`/`each`/`each_key`/
  `each_value`) has a closure parameter that deliberately carries no `sync`
  (design 216, so a suspending body composes) — which makes each of them a
  "maybe-suspending" API. `JsonValue._write` is unavoidably self-recursive
  (an array/object element may itself be an array or object), and a
  self-recursive function defined under `sawc/std/` that also transitively
  reaches a maybe-suspending API fails `sawc`'s own "builtins" pre-check
  with `internal compiler error: builtins failed to type-check` /
  `cannot suspend in a sync closure context` — even though the identical
  shape compiles and runs correctly as an ordinary (non-`sawc/std/`) source
  file. See `_write`'s doc comment in `sawc/std/json.saw` and this unit's
  landing report for the mechanism and a minimal repro. `Array`'s own
  recursion is unaffected (`Vector`'s plain `[]`/`len` are not
  closure-based).

Everything else — `parse`, every accessor, `Array` serialization, the
whole seam below — works and is tested (`examples/json_value_*.saw`).

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
  Observed through `JsonValue` too now (`examples/json_value_structural_
  reject.saw`'s `duplicate_key_last_wins`).
- `JsonValue.Number` is `Int`-only — no `Float` case — pending a correct
  `Float`<->text surface in std (see the status section above).
- `JsonValue.to_json_string` does not serialize `Object` (DF-267d) —
  pending a fix to the recursive-std-function-vs-maybe-suspending-API
  compiler defect (see the status section above; this unit's landing
  report has the repro).
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

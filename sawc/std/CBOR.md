# The `std.cbor` wire profile — FROZEN

This document is the contract between `sawc/std/cbor.saw` and
`tools/sawcbor.py`, in the same sense that `sawc/rt/ABI.md` is the contract
between the compiler and the runtime seams: the golden vectors under
`tests/cbor_vectors/` are checked against **this text**, not against whichever
implementation happened to be written first. A change here is a wire-format
change and breaks every stored blob.

Base format: **CBOR, RFC 8949**, restricted to its **deterministic encoding**
profile (§4.2.1). Any conforming CBOR reader (`cbor2.loads`, `cbor.me`, the RFC
8949 diagnostic notation) reads what `std.cbor` writes. The reverse does not
hold: `std.cbor` **rejects** CBOR that is well-formed but outside the profile,
because accepting two spellings of one value would make "the bytes are the
value" false, and that property is what the vectors test.

## Encoding rules

1. **Shortest form, always.** An unsigned value, a negative value, a string
   length, an array count and a map count each use the shortest of the five
   argument encodings that holds it: the value inlined in the additional-info
   bits (0..23), then `uint8` (24), `uint16` (25), `uint32` (26), `uint64` (27).
   Writing `0x1817` for 23 is a *decode* error (`NotCanonical`), not a
   tolerated alias.
2. **Definite lengths only.** Indefinite-length strings, arrays and maps
   (additional info 31) are never written and are **rejected on decode**
   (`Unsupported`). Every item declares its length up front.
3. **Canonical map key order.** Map keys are sorted by their **encoded bytes**,
   compared lexicographically as unsigned bytes (RFC 8949 §4.2.1's
   bytewise-lexicographic rule, not the older length-first §4.2.3 rule). A map
   whose keys arrive out of order is a decode error (`NotCanonical`).
   Duplicate keys are a decode error (`Malformed`).
4. **No floats.** Major type 7 values 25/26/27 (Float16/Float32/Float64) are
   **not written and rejected on decode** (`Unsupported`). This is a v1
   restriction and is recorded as such: the language's `Float` has no settled
   serialization story yet, and guessing one here would freeze the wrong
   answer into stored blobs. Half- and single-precision are out permanently
   under rule 1 anyway (they are shorter spellings of the same value).
5. **No tags in v1.** Major type 6 is not written and is rejected on decode
   (`Unsupported`). Tags are the extension point a later revision uses; nothing
   is spent on them now.
6. **Simple values.** Only `false` (0xf4), `true` (0xf5) and `null` (0xf6) are
   written. `undefined` (0xf7) and every other simple value are rejected
   (`Unsupported`) — `undefined` would be a second spelling of absence, and
   Saw's Optional has one.
7. **Text is valid UTF-8.** A text string (major type 3) whose payload is not
   well-formed UTF-8 is a decode error (`Malformed`). Byte strings (major type
   2) are arbitrary bytes.
8. **One top-level item.** Bytes remaining after the top-level item have been
   decoded are an error (`TrailingBytes`). A blob is one value, not a stream.

## What Saw values become

| Saw | CBOR |
|---|---|
| `UInt`, `UInt8`..`UInt64` | major 0 (unsigned) |
| `Int`, `Int8`..`Int64`, non-negative | major 0 (unsigned) |
| `Int`, `Int8`..`Int64`, negative | major 1 (negative, encoding `-1 - n`) |
| `Bool` | 0xf4 / 0xf5 |
| absent `Optional` | 0xf6 (null) |
| present `Optional` | the payload's own encoding |
| `String` | major 3 (text) |
| `Data` | major 2 (byte string) |
| `Vector<T>` | major 4 (array) of the element encoding |
| a struct | major 4 (array) of its stored fields, declaration order |
| a raw-backed enum | the case's raw value, as major 0 |

A struct is an **array of fields, not a map of names** (design 169 decision 2).
The shape is the contract: a consumer keys on the type, not on field names, so
nothing is spent encoding the names and the canonical map-key ordering rule
never has to be applied to a struct. Schema evolution is an explicit non-goal
in v1.

Signed and unsigned share major types 0 and 1, so a non-negative `Int` and a
`UInt` of the same value encode **identically**. That is deliberate — the value
is what is on the wire — and it means the *type* must be known to read a blob
back. `std.cbor` is a format for values whose shape both sides agree on ahead
of time.

## Decoder limits

The decoder takes its limits as constructor parameters rather than defaulting
them silently, because the caller knows what it is reading and the kernel
caller's answer is not the hosted caller's:

- **max depth** — how deeply arrays and maps may nest. Enforced with a counter
  checked *before* descending, so the limit is a real bound on recursion and
  cannot be exceeded even by one frame.
- **max size** — the largest input the decoder will look at, in bytes.
- **max items** — the total number of items the decoder will produce, counted
  across the whole blob, so a small input declaring a huge array cannot make
  the decoder allocate for it.

Every limit is reported as a `DecodeError` naming the byte offset it was hit
at. A decoder never panics on input, however malformed: that is the property
the fuzz-shaped rejection tests exist to hold.

## Vectors

`tests/cbor_vectors/` holds one `.cbor` blob per case plus a `.json` sidecar
describing the value. Both implementations must round-trip every vector
**byte-identically**: Saw encode → `cbor2` decode → `cbor2` re-encode → compare
bytes, and `cbor2` encode → Saw decode → Saw re-encode → compare bytes. The
`reject/` subdirectory holds blobs that must FAIL to decode, each paired with
the fault it must report.

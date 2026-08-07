# Design 169 — Serialize/Deserialize + std.cbor (RFC 8949)

**Status: BRIEFED (Aug 7, from the user's parser-port seam conversation);
decisions below marked [recommended] await user ratification. QUEUE: dispatches
after design 168 integrates (user: "after 168 part b lands"); eligible
concurrent with the post-168 wave (surfaces disjoint from 155/165/DF-163d);
MUST land before the parser-port brief on the rewrite track, which consumes
it.**

## The problem

The tree hand-rolls wire code everywhere it touches bytes: `blade/src/
sosimg.saw` (542 lines), `sos/imgformat/`, lock-file and toml handling. The
parser-port integration strategy (tracker, Aug 7) needs a language-neutral
binary AST interchange with a Python reader. And design 145 called raw-backed
enums "the wire idiom" without giving them a serialization story. One trait
pair + one standard format closes all three.

## Goal

`Serialize`/`Deserialize` in the trait vocabulary with `@synthesize`
structural derivation, format-agnostic over a writer/reader interface; and
`std.cbor` as the first concrete format — RFC 8949 CBOR restricted to its
DETERMINISTIC ENCODING profile (§4.2.1: shortest-form integers/lengths,
definite lengths only, canonical map-key order). Python side: a thin handler
over `cbor2` plus shared golden vectors. NOT invented notation — the format
survives contact with other tools (`cbor2.loads` inspects any blob; RFC 8949
diagnostic notation is the free text rendering for debugging).

## Units

1. **The trait pair + interfaces.** `Serialize { func serialize(&self, to:
   &var any Encoder) -> Result<Void, EncodeError> }`, `Deserialize { static
   func deserialize(from: &var any Decoder) -> Result<Self, DecodeError> }`
   (exact spellings per decision 2). Errors are Result, never sentinel or
   partial-object (never-hide-errors). Encoder writes into a CALLER-OWNED sink
   (StringBuilder-style growable AND FixedBuf fixed — `--no-hidden-alloc`
   kernels serialize into their own buffers); Decoder reads from a byte slice.
2. **`@synthesize` derivation.** Structural field walk in declaration order,
   same machinery as Hashable; hand-written bodies allowed for invariant-
   carrying types, same as every trait in the family. Raw-backed enums derive
   both directions from the 145 idiom (`e as UInt8` total out, `E.from(raw:)`
   partial in, absent case = DecodeError not panic). Conformance synthesis
   respects design-80 visibility (derivation runs in the defining module).
3. **`std.cbor`.** The deterministic-profile encoder + decoder in Saw:
   unsigned/negative ints, byte strings, text strings, arrays, maps, tags,
   bool/null, Float64 IF the Float64 decision (user pile) lands — else floats
   are a decode error in v1, recorded loudly. Import-required module, not
   prelude.
4. **Untrusted-input discipline.** Decoder limits are FIRST-CLASS constructor
   parameters, not afterthoughts: max depth, max total size, max item count;
   defaults chosen for hosted use, kernel callers pass their own. Malformed
   input is a DecodeError naming the byte offset — never a panic, never
   unbounded recursion (depth is a counter, not the call stack, OR the
   recursive decode is depth-checked before descent; decide in-unit and
   document).
5. **The Python handler + golden vectors.** `tools/sawcbor.py` (or module
   under tools/) over `cbor2`, enforcing the same deterministic profile on
   encode. `tests/cbor_vectors/` golden files that BOTH implementations must
   round-trip byte-identically — the lexdiff/astdiff discipline applied to
   serde; the vector suite is the cross-language contract alongside a frozen
   spec note (rt/ABI.md pattern) recording the profile restrictions.
6. **Migration proof, one site.** Re-express ONE existing hand-rolled wire
   surface (recommend: the sosimg CONFIG reader or a blade lock-file slice —
   smallest first, NOT the whole sosimg format) over the traits, as the
   dogfood gate. Full sosimg migration is future work, not this brief.

## Decisions (for user ratification)

1. **Format = CBOR RFC 8949 deterministic profile** [recommended] — over
   MessagePack (simpler spec but NO official canonical form — we would be
   re-specifying determinism ourselves) and over a bespoke "sawon" (a
   battle-tested RFC with an existing Python implementation beats inventing
   notation; the traits stay format-agnostic so a future format is additive).
2. **Struct encoding = array-of-fields in declaration order** [recommended],
   not map-with-names: exact-shape is the v1 contract (consumers key on the
   type's digest), arrays are smaller and canonically ordered by construction,
   and diagnostic notation still renders them inspectable. Map-keyed encoding
   with schema evolution is an explicit v1 NON-GOAL (revisit only if sawon-
   class interchange ever goes public-facing).
3. **Field visibility: synthesis serializes ALL stored fields including
   private ones** [recommended] — serialization is structural like Hashable;
   a type that must not expose a field writes its own body.
4. **The AST seam envelope (node-id high-water mark, compiler digest, format
   tag) is NOT part of this design** [recommended] — it layers over CBOR in
   the parser-port brief. std.cbor stays generic.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff, astdiff,
irdet --all, bootstrap, gmgate, sos_runner). Golden vectors round-trip
byte-identical from BOTH sides (Saw encode → cbor2 decode → cbor2 re-encode →
byte-compare, and the mirror). Decoder fuzz-shaped rejection tests (truncated,
over-depth, over-size, shortest-form violations REJECTED on decode per the
deterministic profile). DF-169x findings for every language pain hit.

## Explicitly out

Schema evolution / unknown-field tolerance; streaming/chunked decode;
indefinite-length items (the profile forbids them); Float16/32; a public
sawc flag surface; the whole-sosimg migration; the AST envelope (parser-port
brief); any typechecker special-casing beyond the synthesis walk.

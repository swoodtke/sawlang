# Design 169 — Serialize/Deserialize + std.cbor (RFC 8949)

**Status: PARTIALLY LANDED (Aug 7). Units 1, 2 and the PYTHON half of unit 5 are
built and gated on the design-169 worktree branch. Units 3, 4 and 6 are NOT
started and are deferred to a follow-up dispatch — "169 part 2" — whose
state-of-the-world is at the bottom of this file. All four decisions below were
implemented as recommended; nothing was renegotiated.**

## What landed

- **Unit 1 — the trait pair + the Encoder/Decoder seam.** `sawc/std/serde.saw`:
  `Serialize`, `Deserialize`, `Encoder`, `Decoder`, `EncodeError`/`EncodeFault`,
  `DecodeError`/`DecodeFault`. `deserialize` is a STATIC requirement returning
  `Self`, so `Deserialize` is a generic bound and never an existential.
  Prelude-visible, kept in the freestanding profile, absent under
  `--runtime-build`.
- **Unit 2 — `@synthesize` structural derivation**, both directions, covering
  the integer types, `Bool`, `String`, `Optional`, `Vector`, raw-backed enums
  (both directions, per decision 2 and design 145) and any nested conforming
  member. A member outside that set is a clean error naming the field.
- **Unit 5, Python half** — `tools/sawcbor.py` (an independent implementation of
  the profile over `cbor2`), `sawc/std/CBOR.md` (the frozen profile note, the
  rt/ABI.md pattern), and `tests/cbor_vectors/` with 32 accept + 19 reject
  blobs. `tools/sawcbor.py verify` is green today.

Commits, each with the full battery green: `ea13a3e` (DF-169a, the prerequisite
fix), `95f55c5` (unit 1), `defad53` (unit 2), `17fd67f` (unit 5 Python half).
Final tip battery: suite 1403/1403, lexdiff 0 mismatches, astdiff 0, `irdet
--all` 914 examples byte-identical, blade bootstrap ok, gmgate 0 failing,
sos_runner 11/11, `sawcbor.py verify` 32 accept + 19 reject.

Three decisions were forced by contact with the compiler and are worth carrying
forward:

1. **The vocabulary lives in `sawc/std/serde.saw`, not `builtin.saw`.**
   `--runtime-build` skips std entirely, so a `Printable` conformance in
   builtin.saw synthesizes design-56's `to_string` default body against a
   `StringBuilder` that is not loaded — eight errors inside builtin.saw itself.
   A std FILE is skipped there, kept freestanding, and — by staying out of
   `IMPORT_REQUIRED_STD_MODULES` — prelude-visible, which is also what makes a
   derived body's bare `Encoder`/`DecodeError` resolve however the user wrote
   their imports.
2. **Every serde signature is `sync`.** The derived `Vector` walk reads elements
   as PLACES, and a place window is a sync context (design 141), so the first
   build failed with "cannot suspend in a `sync` closure context". `sync` is the
   right contract rather than a workaround: serialization writes into a buffer,
   and the effect is what lets a value serialize inside a place window, under a
   `SpinLock`, or in a kernel. I/O happens on the buffer afterwards.
3. **Derived bodies are synthesized AST, not emitted IR.** The
   Equatable/Comparable/Hashable derivations emit IR from the field layout,
   which works because a hash is a fold over words. A serialize body is a chain
   of fallible calls whose failures propagate; emitting it as IR would mean
   re-implementing `try` in llvmlite. `sawc/typechecker/serde.py` builds real
   source and hands it to the ordinary front end.

Two compiler bugs were found and fixed on the way in (DF-169a, DF-169b — see the
tracker); the first was a hard blocker, since the brief's trait pair is
method-based and method arguments could not erase to `any Trait` at all.

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

## 169 part 2 — the deferred half (units 3, 4, 6)

Not started, deliberately: a half-built CBOR codec is worse than none, because
the vectors would start passing against an implementation that does not yet
enforce the profile. Whoever picks this up inherits a complete contract and a
complete seam.

**Where the hooks are.** The derivation mixin is `sawc/typechecker/serde.py`
(`SerdeMixin`), mixed into `TypeChecker` in `sawc/typechecker/core.py` and driven
by `_synthesize_serde_bodies(program)`, called in BOTH drivers right after
`_check_ord_hash_require_equatable()` — after every type is registered (the walk
needs a nested type's conformance and an enum's raw backing) and before body
checking (what it builds is ordinary source the checker then sees). The
derivation TRIGGER is in `registration.py::_register_extension`, beside the
Hashable block; it mints only a signature, copied from the trait's own AST via
`_serde_derived_signature` so the derived method's type is identical to the
requirement it satisfies. `Serialize`/`Deserialize` are deliberately NOT in
`_ENUM_DERIVABLE_TRAITS` — unlike equals/compare/hash they mint a real method
rather than being inlined at the call site, so enums must fall through to the
ordinary registration path.

**The decoder-limits design, already made (units 3 and 4 are ONE job).** The
limits are not a wrapper over a finished decoder. `CborDecoder` validates the
WHOLE input against `max_depth` / `max_size` / `max_items` in an up-front
structural scan driven by an EXPLICIT work stack; typed reads then run over
bytes already known to be well-formed. Depth is the stack's height, checked
BEFORE descending, so the decoder never recurses on input and a hostile blob
cannot reach the call stack at all. Build the scan first; the typed read surface
is straightforward once it exists. Limits are constructor parameters with hosted
defaults, per the brief.

**What the vectors expect.** `sawc/std/CBOR.md` is authoritative and frozen —
write the Saw codec to it, not to the RFC. `tests/cbor_vectors/accept/` holds 32
blobs with `.json` sidecars carrying the value, its hex, and its diagnostic
notation; `reject/` holds 19 blobs each paired with the `DecodeFault` it must
report (truncation, non-shortest-form integers at all four widths, indefinite
lengths, floats, tags, `undefined`, unsorted and duplicate map keys, trailing
bytes, bad UTF-8, a reserved additional-info value). `tools/sawcbor.py verify`
already checks all 51 against an independent `cbor2` reader; the Saw side needs
a harness that encodes the same case table and compares bytes, at which point
the round-trip is closed in both directions.

**Unit 6 should be the blade lock file, not sosimg** (which has a parked M1b
branch under it). `blade/src/lock.saw` is columnar today — five parallel
`Vector<String>` — and the CBOR shape is a `LockEntry { name, version, source,
loc, rev }` plus `Vector<LockEntry>`, which the unit-2 derivation already covers
end to end.

**One packaging note:** `std.cbor` is import-required, unlike `std.serde` — add
`"cbor"` to `IMPORT_REQUIRED_STD_MODULES` in `sawc/sawc.py`.

## Explicitly out

Schema evolution / unknown-field tolerance; streaming/chunked decode;
indefinite-length items (the profile forbids them); Float16/32; a public
sawc flag surface; the whole-sosimg migration; the AST envelope (parser-port
brief); any typechecker special-casing beyond the synthesis walk.

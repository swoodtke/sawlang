# Design 48 — Comparable + Hashable + HashMap (D14, DECIDED Jul 29)

**Ruling (user):** Hashable mirrors D2's Equatable model exactly;
Comparable is opt-in only.
- **Comparable** (requires Equatable): `Ordering` enum
  {Less, Equal, Greater}; `compare(&self, other: Self) -> Ordering`;
  `< <= > >=` desugar to compare(); builtin for integer types, Float
  (IEEE; NaN incomparable — document the operator behavior), String
  (byte-lexicographic = code-point order, documented); NO
  auto-conformance (field order is a semantic choice) — empty
  `extension T: Comparable {}` synthesizes lexicographic field-order /
  payload-order compare; custom compare overrides.
- **Hashable** (requires Equatable): trivial structs + payload-free
  enums auto-conform; empty extension synthesizes field/payload
  streaming; primitives + String builtin; **streaming Hasher**
  (FNV-1a default) — `hash(&self, h: &var Hasher)`; hash/== contract
  documented (rides Equatable).

## Items
1. Ordering enum + Comparable trait + operator desugar + builtins +
   synthesis (reuse the design-32 synthesis machinery — same shape).
2. Hashable + Hasher (FNV-1a) + auto/synthesis mirroring
   is_equatable's gating.
3. `Vector.sort()` (T: Comparable) + `sort_by(compare closure)` —
   non-escaping closure param; algorithm: insertion or merge — simple
   and correct first, note the choice (stability: document whatever
   ships).
4. `HashMap<K: Hashable + Equatable, V, A: Allocator = Global>` —
   open addressing or bucketed over Vector internals; grow at load
   factor; the existing Vector-backed `Map` STAYS as-is (migration/
   deprecation is a later user decision — note in tracker).
5. Blade's forcing case as a test: a Version struct with
   `extension Version: Comparable {}` sorted correctly (the semver
   shape).
6. Tests: operator desugar, synthesis (struct/enum), custom compare,
   non-Comparable `<` error, NaN behavior, sort incl. String keys +
   sort_by, HashMap insert/get/remove/grow/collision (force via tiny
   capacity or crafted keys), auto-Hashable gating errors.
7. Docs: spec sections for both traits + HashMap; CLAUDE.md.

## Hazards
Hash/== consistency (synthesis must stream exactly the fields == 
compares). Sort must not silently copy ExplicitCopy elements (probe
element handling; bound to T: Copy if extraction demands, per the
Vector.each precedent — report). Full suite per commit.

## Landed (Jul 29)
- **Comparable**: `Ordering {Less, Equal, Greater}` + `Comparable` trait in
  builtin.saw; `< <= > >=` desugar in codegen via `_emit_compare` (an i32
  Ordering tag) → `_ordering_to_bool`. Builtins: integer/Float direct
  three-way; String via a hand-written byte-lexicographic `String.compare`.
  Empty `extension T: Comparable {}` synthesizes lexicographic compare (struct
  field order; enum variant-tag order then payload), mirroring design-32's
  synthesis (a `is_derived_compare` Method, emitted memberwise in codegen).
  NO auto-conformance. "Requires Equatable" is a post-registration check
  (`_check_ord_hash_require_equatable`), satisfied by auto-Equatable POD types.
- **Hashable**: streaming `Hasher` (FNV-1a, `write_int`/`finish`) + `Hashable`
  trait. `x.hash(&var h)` is one codegen lowering point (`_emit_hash`): a real
  method (String, synthesized/custom struct) is called; a primitive / POD
  struct / payload-free enum is streamed inline. Auto/synthesis mirror
  `is_equatable` exactly (`is_hashable`). hash/== contract holds; Float
  normalizes ±0.0.
- **sort NEEDED a Copy bound.** `Vector.sort` is `<T: Comparable + Copy>`,
  `sort_by` is `<T: Copy>` — movement is byte-level `swap` (no copy), but
  comparison reads elements by value via `get`, exactly the Vector.each
  precedent. Added `Vector.swap_out` (move-out + placement-in) for HashMap.
  Insertion sort; stable.
- **HashMap collision scheme: OPEN ADDRESSING** (linear probing, tombstone
  deletion), power-of-two capacity, grow (double + rehash) at 3/4 load. Slots
  are a `HashSlot<K,V> {Empty, Tombstone, Occupied(key,value)}` enum so a fresh
  table is deinit-safe for owning keys/values; updates/removals `swap_out` the
  old slot (no leak/double-free). HashMap is NoCopy. Int + String keys tested.
- **TRACKER NOTE: the Vector-backed `Map` (std/map.saw) STAYS unchanged.**
  Migrating/deprecating it in favour of HashMap is a later user decision.
- Enabling fixes (kept): match on a generic enum now substitutes the
  monomorphization's type params (codegen/match.py); `&var self` method calls
  through a `&`/`&var` reference param deref once (codegen/calls.py); optional
  auto-wrap propagation handles expression-bodied match arms
  (typechecker/expressions.py).

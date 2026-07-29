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

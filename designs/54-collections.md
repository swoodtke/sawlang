# Design 54 — Collections family: Map unification, Set, collection literals (DECIDED Jul 29)

**Ruling (user):** the Vector-backed `Map` is **RETIRED** — `HashMap`
is renamed to `Map` and becomes THE dictionary type (closes the open
"Map deprecation timing" decision). `Set<T>` ships with **core +
algebra**. Collection literals keep the standing `{ }` syntax with
the **closure rule**: `{k: v, ...}` = map (colon lookahead), `{a, b,
...}` = set (comma lookahead), `{:}` = empty map; **`{}` and
`{single-expr}` ALWAYS mean closure/block** — empty/singleton
collections are spelled `Map<K, V>()`, `Set<T>()`, `Set.of(x)`.
Array literals become **context-driven**: `[1, 2, 3]` stays a
fixed-size array by default, but builds a `Vector` when the expected
type says so.

Sequencing: land AFTER 57 (which implements visitors/snapshots on the
hash container under its old name — 54 inherits them through the
rename) and after 53. Brief 57 was amended to skip old-Map iteration.

## Part 1 — Map unification
- Delete `sawc/std/map.saw` (the Vector-backed implementation).
  Rename `HashMap<K: Hashable + Equatable, V, A: Allocator = Global>`
  → `Map<...>` (file becomes the new map.saw; no `HashMap` alias
  left — pre-1.0, no users, clean break).
- Migrate: `hashmap_*` example tests (rename type, keep coverage);
  `map_simple` / `map_nocopy_value_construct` (retarget to the hash
  Map — the owning-key-safe slot enum already covers the NoCopy-value
  case); doc mentions (alloc.saw comment, spec, CLAUDE.md).
- Semantics notes for the spec: iteration order is UNSPECIFIED
  (deterministic output = sort `keys()` at the point of writing —
  String/Int are Comparable); keys require `Hashable + Equatable`
  (auto-conformance covers the trivial set); Map is NoCopy; the old
  Map's `copy()` is NOT carried over (an ExplicitCopy conformance is
  future work if a consumer demands it — note in tracker).
- 57's visitors (`each`/`each_key`/`each_value`) and snapshots
  (`keys()`/`values()`) arrive via the rename untouched.

## Part 2 — Set<T>
- `Set<T: Hashable + Equatable, A: Allocator = Global>`, NoCopy,
  in `sawc/std/set.saw`.
- Implementation: PREFER wrapping the hash Map with a zero-size unit
  value if the generics/layout machinery handles an empty payload
  cleanly (probe first — Void as a generic value arg may not work; a
  `struct Unit {}` may). If the wrapper fights the compiler, write
  the parallel open-addressing implementation reusing Hasher and the
  slot-enum pattern (Empty/Tombstone/Occupied(k)) — report the
  choice and why.
- Core API: `insert(v) -> Bool` (true if newly inserted),
  `remove(v) -> Bool`, `contains(v) -> Bool`, `len()`, `is_empty()`,
  `each(body: (T) -> Void)` visitor (same non-escaping + exclusivity
  discipline as 57's), `to_vector() -> Vector<T, A>` snapshot
  (`T: Copy`-family bound), init from `Vector<T>` (consumes/moves),
  `Set.of(v)` single-element factory (the singleton spelling; no
  variadics — design 55 overloads can add small arities later if
  wanted).
- Algebra (all borrow `&other`, return a NEW set; require `T: Copy`
  family for element duplication — report if the bound can be
  looser): `union(&other)`, `intersection(&other)`,
  `difference(&other)`, `is_subset(&other) -> Bool`,
  `is_superset(&other) -> Bool`.
- Order unspecified (same spec note as Map).

## Part 3 — collection literals
- Grammar (expression position, resolved by bounded lookahead — NO
  type feedback into the parser):
  - `{` … first expression … `:` → **map literal**
    `{k1: v1, k2: v2, ...}`; `{:}` → empty map.
  - `{` … first expression … `,` → **set literal** `{a, b, ...}`
    (two or more elements — comma is what disambiguates).
  - `{}` and `{expr}` (no colon, no comma) → **closure/block, always**
    (existing meaning unchanged — `{ $0 * 2 }`, `{ x in ... }`, and
    zero-param `{ expr }` closures keep parsing exactly as today).
    Empty/singleton collections: `Map<K, V>()`, `Set<T>()`,
    `Set.of(x)`. State the rule in ONE sentence in the spec.
  - `{ x in ... }` (closure param syntax) must stay unambiguous —
    the lookahead must treat `in` like the closure signal it is.
- Types: `{k: v, ...}` : `Map<K, V>` with K/V inferred from the
  elements (all keys one type, all values one type — mismatch is a
  clean error naming both); `{a, b}` : `Set<T>` likewise. K/T must
  satisfy Hashable + Equatable (same error as constructing the
  container). An expected type (annotation/param/return) of
  `Map<K, V, A>` / `Set<T, A>` type-checks the elements against it
  (custom allocator literals work); a conflicting expected type is
  an error — no other container conjures from `{ }`.
- Lowering: construct (reserve capacity for the element count if a
  with-capacity path exists) + `insert` per element in source order.
  Duplicate keys: LAST WINS (plain insert semantics — document; no
  compile-time duplicate detection in v1, even for literal-identical
  constant keys — note as possible lint later).
- Value-transfer: each element expression is consumed exactly as an
  `insert` argument would be (moves for owning types; the checkpoint
  sees n independent transfers).
- `{:}` needs an expected type or an immediate annotation to fix
  K/V (`let m: Map<String, Int> = {:}`); bare `let m = {:}` with no
  context is an error asking for an annotation.

## Part 4 — context-driven Vector literals
- `[a, b, c]` in a position whose EXPECTED type is `Vector<T, A>`
  (annotation, parameter, return, struct field init) lowers to a
  Vector construction + per-element push (reserve n first if
  available) instead of a fixed-size array. Element expressions
  type-check against T; moves work (NoCopy elements — mirror the
  array literal's move-in rules).
- `let v: Vector<Int> = []` — empty Vector via context: legal.
- NO expected type → fixed-size array literal, byte-for-byte
  unchanged (the whole existing array suite is the regression
  oracle).
- An expected type that is neither array nor Vector keeps today's
  error behavior.

## Items (suggested commit units)
1. Map unification (delete/rename/migrate/docs).
2. Set core (+ probe report on the wrapper-vs-parallel choice).
3. Set algebra.
4. Map/Set literals (parser lookahead + typecheck + lowering).
5. Vector-context array literals.
6. Docs: spec (one dictionary type; Set; literals incl. the closure
   rule sentence + `{:}`; Vector literals), CLAUDE.md (rewrite the
   "Dictionaries use { }" bullet to the full rule), tracker (incl.
   closing the Map-deprecation open decision).

## Tests (minimum)
Unification: renamed suite green (insert/get/remove/grow/collisions/
String keys), NoCopy-value construct, no `HashMap` name resolvable
(clean unknown-type error), 57's visitors/snapshots still green
post-rename. Set: insert/dup-insert Bool, remove/absent, contains,
each + mutation-during-each rejected, to_vector + sort for
deterministic assert, from-Vector consumes (use-after-move error
test), Set.of, union/intersection/difference contents,
subset/superset edges (empty set, self), non-Hashable element error.
Literals: map literal basics + nested values, `{:}` with annotation /
error without, set literal 2+ elements, `{}`/`{x}` still closures
(regression: existing closure suite untouched), `{ x in ... }`
unaffected, key-type mismatch error, value-type mismatch error,
duplicate-key last-wins, literal into param/return positions, custom
allocator via annotation, move semantics of owning elements
(use-after-move on a String moved into a literal). Vector literals:
annotation/param/return/field contexts, empty `[]`, NoCopy element
moves, no-context stays array (existing array suite green), non-
collection expected type error.

## Hazards
- The `{` lookahead sits on the hottest parse path (every block/
  closure) — keep it bounded (peek to the first `:`/`,`/`in`/`}`
  after one expression, no full backtracking) and benchmark-sanity
  check compile time on the biggest example.
- The rename is repo-wide mechanical churn — do it as ONE commit
  (delete + rename + migrate) so bisects stay clean, run the suite
  before and after.
- Set's algebra must not double-hash on insert-from-visit (compose
  from the internal probe path if the wrapper approach allows).
- Vector-context literals must not disturb array-literal type
  inference in `UnsafeMemory`/static contexts (design 46/41 arrays
  are load-bearing — their tests are the oracle).
Full suite per commit; zero xfails.

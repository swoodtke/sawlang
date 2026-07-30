# Design 57 — Blade enablers: map iteration, parsing, DF3, std.time, Int/Float extensions (N4/N5/N7, DECIDED Jul 29)

**Ruling (user):** the "Blade enablers" N-family ships as one brief.
Decisions: map iteration is **visitors + snapshots** (closure `each`
family as the primitive, `keys()`/`values()` snapshot Vectors as
convenience); parsing is **Optional methods on String** (`to_int() ->
Int?`, `to_float() -> Float?`); **DF3 adopted** — call-site T→T?
optional auto-wrap becomes language-wide (design 55 rule 1 keeps it
unambiguous under overloading); **std.time covers monotonic + wall
clock** (Instant/Duration on Int64 nanoseconds, plus
`unix_timestamp() -> Int64`).

Depends on: 55 (overloading — radix overload, rule-1 interaction),
56 (Printable — Duration's `{d}` output; NOT a hard blocker for the
rest if sequencing demands, but 56 is expected landed first).

## Part 1 — N4a: HashMap iteration
**Scope note (decided with design 54):** the Vector-backed `Map` is
being RETIRED — design 54 renames `HashMap` → `Map` and deletes the
old implementation. Do NOT build iteration for the old Map; implement
on `HashMap<K, V, A>` only (54 inherits it through the rename).
Saw's no-escape references mean an iterator object cannot borrow the
map — so iteration is NOT Iterator-protocol-over-a-borrow. Two forms:
- **Visitors (the primitive, zero-allocation):**
  - `func each(&self, body: (K, V) -> Void)` — non-escaping closure,
    same borrow discipline as `sort_by`/`withCString`. K/V passed to
    the closure by the cheapest legal form (see below).
  - `func each_key(&self, body: (K) -> Void)`
  - `func each_value(&self, body: (V) -> Void)`
  - Element passing: trivial/ImplicitCopy K/V pass by value;
    ExplicitCopy/NoCopy elements pass by reference (`&K`, `&V`) —
    pick ONE consistent rule the checker can enforce and document it
    in the brief report (if per-category dispatch is not cleanly
    expressible yet, `&K`/`&V` uniformly is the fallback — report
    which).
  - HashMap visitors skip Empty/Tombstone slots; Map visits in
    insertion (vector) order; HashMap order is unspecified (say so in
    the spec).
  - Law of Exclusivity: the map is borrowed shared for the whole
    visit; mutating the map inside its own `each` must be rejected
    statically (existing capture-exclusivity machinery — add a test).
- **Snapshots (the convenience):**
  - `func keys(&self) -> Vector<K, A>` and
    `func values(&self) -> Vector<V, A>` where the element is
    copyable (`K: Copy` bound on the extension, per the existing
    bounded-extension mechanism — same pattern as `Vector<T: Copy>:
    ExplicitCopy`). Built via the visitor internally.
  - No `entries()` snapshot in v1 (tuple-of-copies has containment
    wrinkles; visitors cover it) — note as deferred.
  - for-in works over the returned Vector through the existing
    Iterator machinery.

## Part 2 — N4b: string→number parsing
- `extension String`:
  - `func to_int(&self) -> Int?` — optional leading `-`/`+`, decimal
    digits, whole-string match (no trailing junk), overflow returns
    None (checked against platform Int width — use the existing
    overflow-panic-free building blocks, NOT a panicking path).
  - `func to_int(radix: Int) -> Int?` — overload (design 55); radix
    2..=36, digits 0-9a-zA-Z; no `0x` prefix handling (caller strips).
  - `func to_float(&self) -> Float?` — standard decimal form
    (`[+-]?digits[.digits][e[+-]digits]`), whole-string match. A
    simple strtod-equivalent via accumulation is acceptable for v1;
    perfect round-tripping is NOT required (note precision caveat in
    the report if the naive path is used).
- Empty string → None. Whitespace is NOT trimmed (caller trims —
  String.trim exists).

## Part 3 — DF3: call-site optional auto-wrap
- A `T` argument auto-wraps to a `T?` parameter at call boundaries —
  all four call forms (free/method/static/module-qualified), init
  calls, and enum-payload construction if cheap (report if payloads
  are deferred).
- Ordering: overload resolution FIRST (design 55 — rule 1 "exact
  beats optional-wrap" already anticipates this), then wrap injection
  at the argument-passing edge, then the design-30 return machinery
  untouched.
- Nesting: one level only (T → T?); no T → T?? chains; no wrapping
  through generic instantiation (a `T` argument to a generic `U`
  param where U := Int? does NOT wrap — explicit at generic
  boundaries; add the error test).
- Value-transfer checkpoint: the wrap consumes the argument exactly
  as an explicit construction would (move/copy rules unchanged).
- Update the DF3 ledger entry in designs/todo.md.

## Part 4 — N5: std.time (hosted-only)
- New `sawc/std/time.saw`, `import std.time`.
- `struct Duration { nanos: Int64 }` — fixed-width (riscv32-safe).
  Methods: `secs() -> Int64`, `millis() -> Int64`, `micros() ->
  Int64`, `nanos()`; static `from_millis(Int64)`, `from_secs(Int64)`.
  Conform to Equatable + Comparable (+ Printable once 56 is landed:
  human form like `1.42s` / `230ms` — pick sensible thresholds).
- `struct Instant` (opaque Int64 nanos since an arbitrary epoch):
  static `now() -> Instant` (CLOCK_MONOTONIC via clock_gettime — add
  the extern seam like existing file/process externs; macOS + Linux),
  `elapsed(&self) -> Duration`, `duration_since(earlier: Instant) ->
  Duration`.
- `func unix_timestamp() -> Int64` — wall-clock seconds since the
  Unix epoch (CLOCK_REALTIME), free function in the module.
- Hosted-only: it may allocate nothing, but it links libc —
  freestanding builds simply don't import it (same posture as
  std.process; note in spec).

## Part 5 — N7: built-in numeric extensions
- `extension Int` (new file or builtin.saw section — match how String
  landed): `abs() -> Int` (panics on Int.min, consistent with house
  overflow rules — document), `min(other: Int) -> Int`,
  `max(other: Int) -> Int`, `clamp(low: Int, high: Int) -> Int`,
  `pow(exp: Int) -> Int` (panics on overflow via checked mul; exp <
  0 panics "negative exponent"), `is_even()`, `is_odd()`,
  `signum() -> Int`.
- `extension Float`: `abs()`, `floor()`, `ceil()`, `round()`,
  `sqrt()`, `min(other:)`, `max(other:)` (IEEE NaN semantics —
  document; use LLVM intrinsics where natural).
- Survey pass: grep Blade + examples for hand-rolled versions of
  these and migrate the obvious ones.

## Part 6 — Blade dogfood (forcing consumer)
- TOML: `TomlValue` gains typed access `int_value() -> Int?` via
  `to_int()`; sections could move to HashMap + `each`/`keys()` where
  it simplifies — migrate at least ONE real Blade site to each new
  facility (map visitor or snapshot, to_int, DF3 wrap, a build/test
  timing line via std.time) and cover with blade tests.

## Items (suggested commit units)
1. N4a visitors + exclusivity test; snapshots.
2. N4b to_int/to_int(radix)/to_float.
3. DF3 call-site auto-wrap + ledger update.
4. N5 std.time + extern seam.
5. N7 Int/Float extensions + survey migration.
6. Blade dogfood + blade tests.
7. Docs: spec (Map/HashMap iteration + order guarantees, String
   parsing, optional auto-wrap at calls, std.time, numeric methods),
   CLAUDE.md, tracker.

## Tests (minimum)
each/each_key/each_value on Map + HashMap (incl. String keys, enum
values); mutate-inside-each rejected; keys()/values() snapshot +
for-in; snapshot on non-Copy element rejected; to_int
success/sign/junk/overflow/empty; radix overload (incl. rule-1
overload coexistence sanity); to_float forms + junk; DF3: wrap at
free/method/static/module call forms, None still passes, exact-vs-
optional overload picks exact (regression vs 55), no double-wrap, no
wrap through generic param (error), move semantics through wrap
(NoCopy payload); Instant/Duration monotonic non-negative elapsed,
Duration accessors + comparisons, from_millis round-trip,
unix_timestamp sanity (> some fixed past timestamp); Int abs/min/max/
clamp/pow (+ overflow panic, Int.min abs panic), Float
floor/ceil/round/sqrt/NaN; Blade tests.

## Hazards
- Visitor closures must NOT be escaping (checker already enforces —
  keep signatures non-escaping); exclusivity on self during each.
- to_int overflow path must be panic-free (build on wrapping ops or
  pre-checks; the house rule is panics are for BUGS, parse failure is
  data).
- DF3 touches the argument-passing edge every call goes through —
  the whole suite is the regression oracle; land it as its own
  commit.
- std.time externs: struct timespec layout differs macOS/Linux —
  keep the seam in C-shim style like existing externs (check how
  file.saw/process.saw handle platform variance) or use a
  saw_-prefixed runtime shim.
Full suite per commit; zero xfails.

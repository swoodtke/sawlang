# Design 63 — Patterns (T1d) + bounds checks (T1b) + distinct-type cast + named tuples (DECIDED Jul 30)

**Ruling (user):** the pre-Blade language cut. Distinct-type `as` cast
ships and **replaces `.value`** (which is removed from the spec's
planned list — the design-61 clean error's message should suggest the
cast). T1b dynamic bounds checks ship (always-on, house-rule panic).
T1d pattern completion ships WITH `let`/`var` tuple destructuring,
string literal patterns, AND **named tuple fields** (user chose to
include the full feature now; rules pinned below — Swift-compatible).

## Part 1 — distinct-type `as` cast (removes `.value`)
- `id as Int` where `id: UserId` (`type UserId = Int`): legal —
  resolve the operand through `_get_underlying_type` before the cast
  checker's kind match (chained aliases resolve fully: `type B = A`,
  `type A = Int`, `b as Int` works). Result type is the target.
- ONE-DIRECTIONAL: `42 as UserId` stays an error — `UserId(42)`
  initialization remains the sanctioned explicit form; the asymmetry
  is what makes distinct types worth having.
- Casting to a partially-resolved alias (`b as A`) — legal iff A is on
  b's alias chain toward the underlying (still "toward underlying").
  Casting between sibling aliases of the same underlying (`UserId as
  OrderId`) is an ERROR (would launder distinctness).
- Non-integer underlyings: same rule wherever the underlying kind is
  castable-to-itself (e.g. `type Flags = UInt8`); for struct/String
  underlyings `as` simply yields the underlying type view — v1 may
  restrict to primitive underlyings if aggregates complicate codegen
  (report if restricted; the alias→underlying implicit flow already
  covers those).
- Docs: spec type-alias section rewritten — `.value` planned-item
  REMOVED, `as` documented as THE explicit projection; update the
  design-61 error message to suggest `id as Int`.

## Part 2 — T1b: dynamic array bounds checks
- Fixed-array indexing with a non-constant index emits a bounds check:
  `0 <= i < N` (N is compile-time known) — else panic "index out of
  range" via the standard panic seam. ALWAYS ON, every profile, no
  disable flag (same posture as integer overflow, design 31).
- Constant-index compile error behavior unchanged. Tuple dynamic
  indexing: already bounds-relevant? (tuple indices are compile-time —
  verify nothing regressed). Vector/Map manage their own bounds —
  untouched.
- Negative index is caught by the same check (signed compare).
- Tests: read + write at [i] with i in range / == N / negative (panic
  message), loop-over-range regression (no perf-shaped surprises in
  interp_hot_loop-style tests), UnsafeMemory Normal-region indexing
  UNCHANGED (it is the explicit unsafe escape — verify it does NOT
  gain a check; design 46 tests are the oracle).

## Part 3 — T1d: pattern-matching completion
All patterns compose with existing enum-payload patterns and `_`.
- **Literal patterns:** integer (all int types incl. suffixed
  literals), Bool, String (byte-content equality — lowers to the
  builtin equals chain). `case 0 ->`, `case "build" ->`.
- **Range patterns:** `case 1..=9 ->` and `case 1..9 ->` (both range
  forms; same Int-typing rules as range expressions; endpoints are
  constant expressions).
- **Guards:** `case n if n < 0 ->` — guard runs after binding, arm
  taken only if true; falls through to later arms otherwise. Guards
  compose with every pattern form (`case (x, y) if x == y ->`).
- **Tuple destructuring in match arms:** `case (0, 0) ->`,
  `case (x, _) ->`, nested with literals/ranges/guards.
- **`let`/`var` destructuring:** `let (a, b) = pair`,
  `var (x, y) = point`, per-position `_` discard (`let (a, _) =` —
  closes design 53's deferred note; discard consumes/drops that
  component exactly like `let _`). Nested tuples destructure.
  Refutable patterns in `let` are ERRORS (no literals/ranges in let —
  only irrefutable binds/discards); `if let`/`guard let` stay the
  refutable-context forms (extending them to tuple patterns is IN
  scope: `if let (x, y) = maybe_pair { }` where the scrutinee is
  `(T, U)?`).
- **Exhaustiveness:** literal/range/guard arms NEVER prove
  exhaustiveness on open types — a wildcard or bare-binding arm stays
  required (clean diagnostic says so). EXCEPTIONS: `true` + `false`
  arms exhaust Bool; a closed integer RANGE COVER is NOT computed
  (v1 — always require fallback; note as future work). Guarded arms
  never count toward exhaustiveness (a guard can fail).
- **Move semantics:** binding an owning payload/component in an arm
  follows existing enum-match move rules; destructuring `let` moves
  each component out of the tuple (the tuple binding is consumed —
  value-transfer checkpoint sees per-component transfers; partial-
  move-on-tuple rules follow the existing L1 decision: destructure
  consumes the WHOLE tuple).

## Part 4 — named tuple fields (rules pinned — Swift-compatible)
- **Types:** `(x: Int, y: Int)` in type position (params, returns,
  fields, aliases). Field names + order + per-position types are all
  part of the type.
- **Compatibility:** a named tuple and a POSITIONAL tuple of the same
  shape are mutually compatible (labels are view-level; layout is the
  positional tuple's). Two named tuple types with the SAME shape but
  DIFFERENT names are NOT compatible (error names both). Same names
  same order same types = same type.
- **Literals:** `(x: 3, y: 4)`. All-or-nothing labeling — mixing
  labeled and unlabeled elements in one literal is an error. Label
  order in a literal must match the target type's order when a target
  type is known (no reordering in v1 — error suggests the order);
  with no expected type, the literal's own order defines its type.
- **Access:** `.x` by name (resolves to the position), and existing
  positional access (`.0`, `[0]`) keeps working on named tuples.
- **Patterns:** positional destructuring works on named tuples
  (`let (a, b) = p`). The NAMED pattern form (`let (x: a, y: b)`) is
  DEFERRED — note in spec, error if attempted.
- **Printable/Equatable/Hashable:** named tuples behave exactly as
  their positional shape (tuple equality exists today — verify; no
  new conformance surface).
- **Parser:** after `(`, `IDENT :` begins a named tuple literal/type
  (bounded lookahead; must not disturb call-site named arguments
  `f(x: 3)` — those are inside a CALL's parens — nor closure params,
  nor map literals `{k: v}`).
- The spec's "named tuple fields" planned marker flips to implemented;
  CLAUDE.md's key-differences list stays truthful.

## Items (suggested commit units)
1. Part 1 cast + tests (+ 61-error-message tweak).
2. Part 2 bounds checks + tests.
3. Part 3 patterns: literals/ranges/guards + tests.
4. Part 3 tuple destructuring (match, let/var, if-let/guard-let) +
   tests.
5. Part 4 named tuples + tests.
6. Docs (spec: type aliases, arrays, match section, tuples; CLAUDE.md;
   tracker: T1b + T1d + L16-followup + named-tuples closed, design 63
   landed).

## Tests (minimum)
Cast: alias→underlying (Int + a non-Int underlying), chained,
toward-underlying partial, sibling-alias error, reverse error,
suggestion in the .value error message. Bounds: in/at/over/negative,
write path, UnsafeMemory unchanged, existing array suite green.
Patterns: int/string/bool literals, suffixed-literal arm, both range
forms, boundary hits, guards (incl. guard-on-destructure and guard
fall-through order), tuple arms nested with payload-enum patterns,
exhaustiveness errors (missing fallback with literal arms; Bool
true/false exhausts; guarded-arm-doesn't-count), let/var destructure
(+ `_`, nested, owning components move — use-after-move on the tuple
after destructure), if-let tuple over Optional tuple, refutable-in-let
error. Named tuples: literal + type + .name access + positional access
interop, positional↔named flow both directions, different-names error,
mixed-labeling error, reorder error, named in return position
(minmax-style), named pattern form rejected cleanly, equality via
positional shape. Full suite regression per commit.

## Hazards
- Match lowering is shared with enum dispatch and the 52 CFG-walk
  coroutine transform (suspension in match arms is legal) — the
  coro_* families are regression oracles; a match-shape change that
  breaks resume-state mapping would be subtle.
- The `(` lookahead for named tuples sits beside call-argument and
  grouping parses — keep it bounded, closure/map-literal suites green.
- Bounds checks must not fire for constant in-range indices (no perf
  regression in the hot-loop tests) — constant-fold before emitting.
- String patterns must not retain/release-imbalance the scrutinee
  (equals is a borrow — refcount tests with owning scrutinee).
Full suite per commit; zero xfails.

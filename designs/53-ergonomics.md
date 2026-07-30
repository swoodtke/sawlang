# Design 53 — Ergonomics family (DECIDED Jul 29)

**Ruling (user):** the triaged nice-to-have ergonomics ship as one
brief. Decisions: default parameter values use **decl-site rejection**
against overloads (expanded call shapes must not collide — design
55's philosophy); default expressions are **arbitrary, evaluated
per-call** (no references to other parameters); `enumerate()` is
**concrete + closure** (`vec.enumerated()` for for-in + `each_indexed`
— no generic adapter bet); literal suffixes are **Rust-style with
optional underscore** (`255u8`, `0xFF_u8`, set: i8/i16/i32/i64/
u8/u16/u32/u64). Written while brief 56 was in flight; do not assume
56's Printable exists unless it landed first (it is expected to).

## Part 1 — default parameter values
- Grammar: `func f(x: Int, y: Int = <expr>)`. Defaulted params must
  be TRAILING (a non-defaulted param after a defaulted one is a
  parse/check error). Works on free functions, methods, and inits.
- Semantics: an omitted trailing argument is filled by evaluating the
  default expression AT THE CALL SITE, per call (fresh value each
  time — flows through the value-transfer checkpoint exactly like an
  explicit argument; a NoCopy default construction moves in cleanly).
- Default expressions: arbitrary expressions incl. calls; may NOT
  reference other parameters or `self`. Effects flow through
  naturally: a call that fills a suspending default makes the caller
  suspending; effect inference must record the edge (test with a
  sync-context violation).
- **Overloading interaction (design 55):** at declaration time,
  expand every signature into its reachable call shapes (full arity
  down to first-defaulted arity). Any shape collision with another
  overload's shape = declaration-site ambiguity error (same bucket
  as 55's identical-normalized-signature rejection). Call-site
  resolution then treats a defaulted candidate as matching any of
  its shapes — after decl-site rejection this stays unique; assert
  uniqueness anyway (55's machinery).
- Mangling: unchanged — one symbol per declaration (defaults are
  filled caller-side before the call, monomorphization unaffected).

## Part 2 — `..=` inclusive range + enumerate
- `a..=b`: inclusive range. A DEDICATED struct (e.g. RangeInclusive
  { current, last, done }) with its own Iterator conformance — do
  NOT desugar to `a..(b+1)` (overflows at `b == Int.max`; add the
  Int.max edge test, house rule: no phantom overflow panic).
  For-loop integration mirrors Range. `for i in 0..=5` yields 0..5
  inclusive. Empty when a > b.
- `vec.enumerated()`: concrete iterator yielding `(Int, T)` for
  for-in (mirror VectorIterator's shape/bounds; same Copy-family
  element rule as `each` — by-value elements, so `T: Copy`-family
  bound like the existing closure APIs).
- `vec.each_indexed(body: (Int, T) -> Void)`: closure twin, same
  non-escaping discipline as `each`.
- (Ranges get no enumerated — the index IS the value.)

## Part 3 — integer limits + literal suffixes
- Static constants `Int.max` / `Int.min` (platform-dependent values,
  one source of truth: the target word width from design 47), plus
  `.max`/`.min` on ALL fixed-width types (Int8…Int64, UInt8…UInt64,
  UInt).
- Literal suffixes: `255u8`, `1_000i32`, `0xFFFF_FFFF_FFFF_FFFFu64`,
  optional separating underscore (`255_u8` — at most one, directly
  before the suffix). Works on decimal/hex/binary/octal literals.
  A suffixed literal IS that fixed-width type (no platform-Int
  involvement — this closes design 47's riscv32 gap where a 64-bit
  constant was unwritable); range-checked against the suffix type at
  the literal (`256u8` = compile error). Float literals unaffected.

## Part 4 — `\u{...}` escapes
- In string literals: `\u{1F600}`, 1–6 hex digits. Must be a valid
  Unicode scalar (reject surrogates D800–DFFF and > 0x10FFFF at lex
  time — literals stay always-valid-UTF-8). Encodes to UTF-8 bytes
  in the literal. Interacts with interpolation escaping rules —
  add a `"{x} \u{2713}"` combined test.

## Part 5 — import aliasing
- `import std.io as sio` — module alias (only `sio` enters the
  namespace).
- `import std.io.{Read as R, Write}` — per-symbol alias inside
  selective imports.
- Aliases are purely local-namespace renames (no effect on mangling
  or the module graph). Collision checks: an alias colliding with an
  existing binding/import follows the existing import-collision
  rules (same errors, alias name used).

## Part 6 — static_assert
- `static_assert(<const-expr>, "message")` — legal at top level and
  in statement position. The condition must be compile-time
  evaluable: integer/bool literals, arithmetic/comparison/logical
  ops, `sizeof<T>`/`alignof<T>`, and references to const-initialized
  integer statics if the existing const machinery (statics/
  UnsafeMemory const-init) already evaluates them — REUSE that
  evaluator; do not build a second one. Failure = compile error
  carrying the message; success = zero codegen. Kernel motivation:
  register-block size checks (`static_assert(sizeof<UartRegs> ==
  0x1C, "UartRegs layout drift")`).

## Part 7 — use-before-init (PROBE FIRST)
- Probe: is a bare uninitialized local (`var x: Int` with no
  initializer) even accepted today? Write scratch probes (decl-only,
  read-before-assign, assign-then-read, branches).
  - If bare locals are rejected → the hazard is structurally
    impossible: document that in the spec (bindings always
    initialize) and close the ledger item.
  - If accepted → implement the error (definite-initialization on
    the CFG paths that exist; keep scope to locals) or, if that's
    disproportionate, downgrade the brief item to an xfail ledger
    test per brief-12 discipline and report.

## Part 8 — DF1: `let _` discard
- `_` in let/var position is a true discard: evaluates the RHS,
  consumes it (move semantics — the value-transfer checkpoint treats
  the discard as the final consumer), runs its deinit at end of the
  statement's temporaries (i.e., immediately, like an unused temp),
  creates NO binding (`_` is not readable; two `let _ =` in one
  scope are fine — DF1's original collision).
- `var _` = error (nothing to mutate). Do NOT extend to
  destructuring/params in this brief (no tuple-destructuring `let`
  exists yet); note as future work.

## Items (suggested commit units)
1. Default params (grammar, per-call eval, checkpoint/effects,
   decl-site shape expansion vs 55) + tests.
2. `..=` + enumerated()/each_indexed + tests.
3. Int.max/min family + literal suffixes + tests.
4. `\u{}` escapes + tests.
5. Import aliasing + tests.
6. static_assert + tests.
7. use-before-init probe → error/doc/ledger per verdict.
8. `let _` discard + tests.
9. Docs: spec sections for each; CLAUDE.md; tracker (incl. DF1
   ledger closed).

## Tests (minimum)
Defaults: basic fill, multiple defaults, per-call re-eval (counter
function as default — observable), NoCopy default move, non-trailing
error, shape-collision decl error, defaulted-vs-overload coexistence
(no collision case), suspending default in sync context error,
method + init defaults. Ranges: `..=` basics, empty (a > b), Int.max
upper bound no-panic, for-in + break value. enumerated(): values +
indices, empty vector, bounds; each_indexed exclusivity (mutating
vec inside = error). Limits/suffixes: Int.max/min platform sanity,
each fixed-width .max/.min, suffixed literal typing (assign to
exactly that type; mismatch error), out-of-range suffixed literal
error, hex+suffix, underscore forms, `255u8 + 1u8` overflow panics
at runtime (house rule unchanged). `\u{}`: BMP + astral + combined
with interpolation, surrogate/oversized rejected, malformed brace
forms rejected. Aliasing: module alias, symbol alias, alias
collision error, qualified use through alias. static_assert: passing
top-level + statement, failing with message, sizeof-based, non-const
expr rejected. `let _`: two discards same scope, NoCopy discard
deinits immediately (Deinit order observable), `_` read error,
`var _` error.

## Hazards
- Default params touch the SAME call-resolution chokepoint design 55
  just built — extend `_resolve_overload`'s shape matching, don't
  fork it. The 55 test suite is the regression oracle.
- `..=` must not silently reuse Range's `current < end` (off-by-one
  at Int.max); dedicated struct, dedicated tests.
- Suffix lexing must not break `0..5` range tokenization ambiguity
  handling (`0u8..5u8`? — decide tokenization; ranges over
  fixed-width ints may simply not be supported yet: Range is
  Int-typed. `0u8..5` should be a clean type error, not a lexer
  surprise).
- static_assert reuses the existing const evaluator — if that
  evaluator can't do an op the kernel needs (comparison over
  sizeof), extend IT, so statics/UnsafeMemory benefit too.
Full suite per commit; zero xfails.

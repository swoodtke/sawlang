# Design 56 — Trait default bodies + Printable + Error (N1–N3, DECIDED Jul 29)

**Ruling (user):** the "formatting & errors" N-family ships as one brief.
Decisions: trait is named **Printable** (NOT Display — user preference);
core method is the **streaming formatter** (`format(&self, into: &var
StringBuilder)`) with a default-body `to_string()` riding on it; **Error
refines Printable** (`trait Error: Printable {}`); erased errors go
**full** in v1 (`Result<T, Box<any Error>>` as a supported return type
with auto-erasure at the boundary); **no Debug trait** (deferred to its
own later design; `print()` on non-Printable types keeps today's
behavior).

## Part 1 — N1: trait default method bodies
- A trait method declared WITH a body is a default; conformers may
  omit it (inherit the default) or provide their own (override).
- A default body may call other trait methods (including required
  ones); calls dispatch to the CONFORMER's implementation. Compilation
  is monomorphized per conforming type (like generics today).
- Works through trait inheritance: single-extension conformance
  (`extension T: Child` satisfying Base + Child requirements, per
  `examples/trait_inheritance.saw`) also inherits defaults from base
  traits.
- Conformance checking updates: a missing method is an error ONLY if
  it has no default. Signature-mismatch rules unchanged for overrides.
- `any Trait` interaction (design 51): default methods get a vtable
  slot like required methods — the thunk points at the conformer's
  override if present, else at that type's monomorphized default.
  Object-safety rules (51) apply to defaults identically (a default
  body doesn't change the method's signature-based any-ability).
- Effects: a default body's effects are inferred per-conformer
  instantiation; a trait method declared `sync` must have a
  sync-compatible default body (checked once per instantiation, same
  as any other body).

## Part 2 — N2: Printable + user types in interpolation
- New std trait (prelude-visible, like Equatable/Comparable):
  ```saw
  trait Printable {
      func format(&self, into: &var StringBuilder)

      func to_string(&self) -> String {
          var b = StringBuilder()
          self.format(into: &var b)
          b.build()
      }
  }
  ```
  (`to_string` is the N1 dogfood — implement N1 first.)
- Builtin conformances: Int/UInt + all fixed-width integer types,
  Float, Bool, String (String.format appends itself). Keep the
  existing interpolation FAST PATHS for builtins (no regression in
  codegen for `"{n}"` where n: Int) — Printable conformance is for
  generic/`any` contexts and uniformity.
- String interpolation `"{expr}"`: if expr's type is a builtin, keep
  today's lowering. Otherwise REQUIRE Printable conformance and lower
  to `expr.format(into: &var <the interpolation builder>)` — one
  shared builder per interpolated string (streaming, no intermediate
  Strings). Non-Printable type in interpolation = clean compile error
  naming the type and the trait.
- `print(x)`: accept any Printable via the same lowering (builtins
  keep their fast path). Non-Printable stays whatever it is today.
- `T: Printable` generic bound grants `format`/`to_string` and
  interpolation of `T` values in generic bodies.
- NO auto-conformance and NO synthesis in this brief (unlike
  Equatable) — user types conform by hand. Synthesis is the deferred
  Debug design's territory.

## Part 3 — N3: Error trait + erased Results
- ```saw
  trait Error: Printable {}
  ```
  Both conformance spellings legal and tested: (a) one-shot
  `extension T: Error { func format(...) {...} }`; (b) split
  `extension T: Printable {...}` + empty `extension T: Error {}`.
- Object safety: Printable (and thus Error) must be any-able —
  `format` (&self + concrete &var param) and `to_string` (default,
  returns String by value) both pass the design-51 v1 rules. Assert
  this with tests (`&any Printable` dispatch, `Box<any Error>`).
- **Erased Results (the big item):** `Result<T, Box<any Error>>` is a
  supported function return type.
  - Returning a concrete error value `E: Error` from such a function
    auto-wraps to Err AND auto-erases (Box<any Error>.make + vtable)
    at the return boundary — extends the design-30 auto-wrap
    machinery; per design 55, overload resolution has already
    completed before this fires.
  - `try` on a callee returning `Result<U, Box<any Error>>` inside
    such a function propagates the box as-is (move, no re-box).
  - `try` on a callee returning `Result<U, ConcreteE>` inside such a
    function erases ConcreteE into a fresh box at the propagation
    edge.
  - `try { } catch` where the tried calls' error types include an
    erased box: `error` binds as `Box<any Error>`; `"{error}"`
    interpolates via the vtable format. Match-on-error with concrete
    cases is NOT required to work on an erased box in v1 (no downcast
    — note it as deferred: error downcasting needs a type-id design).
  - Box allocation on the error path uses Global. Freestanding note
    for the spec: erased errors are a hosted convenience; kernel code
    keeps concrete/union error types (no hidden allocation).
- Blade is the forcing consumer: migrate at least one real Blade
  error path (e.g. manifest parse errors) to `Result<T, Box<any
  Error>>` + `{error}` output as a dogfood test (blade/tests/).

## Items (suggested commit units)
1. N1 default bodies (checker + monomorphization + any-vtable +
   effects) + tests.
2. N2 Printable trait + builtin conformances + interpolation/print
   lowering + generic bound + tests.
3. N3 Error trait + object-safety tests + both conformance spellings.
4. N3 erased Results (auto-erase at return, try propagation/re-box,
   catch binding) + tests.
5. Blade dogfood migration + blade test.
6. Docs: spec (traits section: default bodies; new Printable section;
   error-handling section: Error + erased Results + freestanding
   note), CLAUDE.md, tracker.

## Tests (minimum)
Default body inherited / overridden / calling a required method /
through trait inheritance / sync default body + sync-violation error;
missing-method error still fires when no default. Printable: user
struct + enum in interpolation, nested (a Printable field formatted
inside a parent's format), to_string default, builtin fast-path
regression (existing interp tests stay green), non-Printable
interpolation error, generic `T: Printable` bound. Error: both
conformance spellings, `&any Printable` dispatch, `Box<any Error>`
make + print, erased Result end-to-end (concrete return auto-erase,
try re-box, try box passthrough, catch binding + interpolation),
sync/effect behavior through an erased error path. Blade dogfood.

## Hazards
- Interpolation lowering currently special-cases builtins — keep
  those paths byte-identical (the interp_hot_loop / interp_large_string
  perf tests are the oracle).
- Default bodies must go through the SAME conformance record the
  any-vtable builder reads, or `any` dispatch of a default will miss
  overrides.
- Auto-erase ordering: overload resolution (55) → auto-wrap (30) →
  erase; keep it a single well-commented sequence at the return
  checkpoint.
- `to_string` default allocates (StringBuilder) — fine hosted; do NOT
  conform kernel-facing types to Printable in std where it would drag
  Global into freestanding builds.
Full suite per commit; zero xfails.

# Design 170 — checked integer casts: `as` panics, `from(_) -> T?`, `from(truncating:)`

**Status: APPROVED (user, Aug 7 — the shape ratified in conversation: label-as-
operation, no boolean flags, no saturating in v1). QUEUE: dispatches after the
DF-163d agent integrates (shared typechecker/expressions.py surface); disjoint
from 169 and eligible concurrent with it post-168.**

## The problem

Narrowing `as` is the last silent value-corrupting operation in the language.
`let x = 1000; let y = x as UInt8` yields 232 today — codegen lowers narrowing
to a bare LLVM `trunc` (`codegen/operators.py:1376-1378`) and same-width
sign-flips are a no-op reinterpret, so `-1 as UInt8` is 255. Everything else in
Saw took the checked road: arithmetic overflow panics at FILE:LINE (122),
bounds/shift checks are always on, accessors ban silent clamps (130/136 era
rule), allocation panics or returns a `try_` Result (123). Casts behave like C.
Rust's silently-wrapping `as` is that community's acknowledged regret; Swift and
Zig both went checked-by-default.

## The design (ratified)

The accessor triple, applied to conversion — and `from` is already the
established partial-conversion vocabulary (design 145's `E.from(raw:)`):

1. **`x as UInt8` — direct form, CHECKED.** Panics when the value is
   unrepresentable in the target (range OR sign), `panic at FILE:LINE: cast to
   UInt8 out of range: {}` via the 137 alloc-free format path. Widening and
   in-range narrowing cost the same as today plus one compare-and-branch on the
   narrowing/sign-change edge — the overflow-check cost class. Widening emits
   exactly what it emits today (sext/zext, no check — total).
2. **`UInt8.from(x) -> UInt8?` — the partial twin.** None when unrepresentable,
   for when out-of-range is expected input, not a bug. Defined UNIFORMLY across
   integer source types (total pairs always return Some — uniformity beats
   cleverness, and generics can rely on the shape; the always-Some check folds).
3. **`UInt8.from(truncating: x) -> UInt8` — the deliberate wrap.** Total; keeps
   the low bits (mod 2^n): `UInt8.from(truncating: 1000)` = 232,
   `UInt8.from(truncating: -1)` = 255. Same-width = bit reinterpret. The label
   IS the operation (Swift's pattern; labels are overload identity per design
   55/93) — there is no boolean, hence no nonsense `truncate: false` corner. The
   cast-shaped sibling of the `&+`/`&-`/`&*` wrapping operators; spec documents
   them together.
4. **Compile-time constants out of range are a COMPILE ERROR**, not a runtime
   panic: `1000 as UInt8` with a foldable operand never survives to runtime
   (const_eval, design 148, already folds enough; the assert-literal precedent
   at const_eval.py:167 is the same policy). `0xFF as UInt8` stays legal and
   free. The same folding elides the runtime check wherever range is provable.

**Explicit non-goal: saturating.** Clamping is a value-domain policy (DSP/pixel
math), not a bit operation, and offering it as an escape from the checked cast
readmits plausible-looking corruption. If a real use case appears it is an
additive `from(saturating: x)` sibling — same pattern, still no booleans.

## Interactions (audit each, none expected to change)

- **Raw-backed enums (145):** `e as Backing` stays total/unchanged. Widening
  past the backing follows widening rules; narrowing BELOW the backing
  (`enum E: UInt16` value `as UInt8`) follows the new checked rule.
- **Distinct aliases (63):** projection resolves to the underlying first, then
  these integer rules apply — composition unchanged.
- **Pointer/address casts (42, unsafe surface):** untouched.
- **Float:** OUT OF SCOPE pending the Float64 decision (user pile); `Float`
  casts keep today's behavior, noted in the tracker if any exist.
- **Overload model:** `from(_)` and `from(truncating:)` are distinct identities
  by label (spec 283-317, 389); return types differ freely since resolution is
  argument-side only. No model change needed — this is a consumer of it.

## Units

1. **Codegen + typechecker:** the narrowing/sign-change check on `as`
   (panic path via 137 formatting), const_eval compile-error for provably
   out-of-range foldable operands, check elision where range is provable.
2. **The `from` family:** extension methods on every integer type (builtin
   surface beside `to_int`; intrinsic-backed as needed), both overloads, all
   source/target pairs. `--no-hidden-alloc` clean (no allocation on any path).
3. **Tree sweep:** triage every in-tree runtime narrowing (`as` on non-const
   operands) into provably-in-range (keep `as`) vs deliberate-wrap (becomes
   `from(truncating:)`). Literal casts stay untouched by construction.
4. **Docs:** spec (cast section + beside the wrapping operators), saw-lang
   skill, README one-liner (the safety pitch earns it). Tests: panic (with
   FILE:LINE assertion), Optional both arms, truncating known-answer incl.
   negative and same-width sign-flip, const compile-error, widening unchanged,
   enum-backing narrowing, alias composition.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff, astdiff,
irdet --all, bootstrap, gmgate, sos_runner). DF-170x findings for language
pain, fixed or filed, never worked around.

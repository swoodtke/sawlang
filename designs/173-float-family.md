# Design 173 — the Float family: Float32/Float64 for real

**Status: APPROVED direction (user, Aug 7 decision round: "implement the
family now" over fix-docs-only). The decisions below are the recommended
shapes, veto-able before dispatch. QUEUE: after 170 AND 171 integrate
(typechecker/codegen contention with both); unblocks CBOR floats
(169 part 2's recorded v1 gap).**

## The problem

`Float64` appears in LANGUAGE_SPEC but does not exist; the only floating
type is `Float`, and `let x: Float64 = 100.0` fails. Design 164's review
flagged it; the spec has carried the fiction since. Kernels increasingly
interact with FP state too (M1b: arm64 FP traps until FPEN; DF-162a just
made no-FP the freestanding aarch64 DEFAULT), so the family needs designing
against the freestanding story, not around it.

## Decisions (recommended, veto-able)

1. **`Float` becomes a distinct platform-width spelling? NO — `Float` IS
   `Float64`** (an alias, design-63 style, not a distinct type): platform-
   width floats are a C-ism with no upside; 64-bit is the default number.
   `Float32` is the explicit narrow type for wire formats, GPUs, and
   embedded FPUs.
2. **Literal defaulting mirrors integers:** an unsuffixed float literal
   adopts the expected type where one is in force (`let x: Float32 = 1.5`
   works), defaults to `Float64` otherwise. A literal that cannot be
   represented EXACTLY in the adopting type is a compile error, not a
   silent round (the 170 discipline applied to floats: `let x: Float32 =
   0.1` errors — spell the rounding explicitly if meant).
3. **Casts join 170's triple:** `f as Float32` / `f as Float64` widen/narrow
   with narrowing PANICKING on overflow-to-infinity (not on precision loss
   — precision loss is what float narrowing IS; only magnitude overflow
   panics). Float↔int: `i as Float64` exact-or-panic (53-bit rule),
   `f as Int` panics on NaN/infinity/out-of-range/fractional part —
   `Int.from(f)` Optional twin, `Int.from(truncating: f)` truncates toward
   zero (C semantics, named). No implicit conversions anywhere, per the
   overload model's foundation.
4. **Freestanding: floats are a TARGET-FEATURE-gated capability.** On a
   target whose features exclude FP (the new aarch64 freestanding default),
   NAMING a float type is a compile error pointing at `--target-features`
   — not a link error, not a trap. Hosted targets are unaffected.
5. **Equatable/Comparable/Hashable: total order via IEEE totalOrder for
   Comparable/Hashable; `==` is IEEE equality with the NaN documentation
   headline.** Map keys of NaN behave (totalOrder), `NaN == NaN` is false
   (IEEE), and the spec says both loudly.
6. **Printing:** shortest round-trip representation (Ryu-style), `{}`
   format args included, allocation-free via the 137 scratch path.

## Units

1. Types + literals + defaulting + the exact-representation check.
2. Arithmetic/comparison codegen + the trait conformances (decision 5).
3. Casts (decision 3) — coordinated with 170's landed machinery.
4. Target-feature gating (decision 4) incl. the freestanding error.
5. Printing (decision 6).
6. Docs: spec (fixing the fiction), skill, README; std audit for places
   that faked floats or documented their absence. Tracker: close the
   Float64 decision-pile item; note CBOR floats unblocked for 169 part 2.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff, astdiff,
Saw-irdet --all, bootstrap, gmgate, sos_runner both arches). Known-answer
tests for every cast edge (NaN, infinities, -0.0, 53-bit boundary, subnormal
narrowing) and a lexdiff/astdiff-visible literal corpus (161's float-literal
lexing rules already pin `1.0`-shape requirements).

## Explicitly out

Float16/BFloat16; SIMD/vector types; math library beyond operators
(sqrt/trig are a std design later); constexpr float folding beyond literal
adoption; changing DF-162a's no-FP freestanding default.

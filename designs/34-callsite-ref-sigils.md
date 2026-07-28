# Design Brief 34 — Call-site reference sigils: `&x` / `&var x`, validated

**Status: DECIDED (Jul 28, user) — implementation brief.** Source:
brief-10 report finding, tracker D7. Ruling: call sites mirror the
parameter's reference spelling — `&x` lends immutably to a `&T` param,
`&var x` lends mutably to a `&var T` param; mismatch in EITHER direction
is a compile error; `&var x` additionally requires `x` to be a `var`
binding. Completes the sigil symmetry: types (`&T`/`&var T`), receivers
(`&self`/`&var self`), captures (`[&v]`/`[&var v]`), and now call sites.

## Items

1. **Parser**: accept `&var expr` in call-argument position (function
   calls, method calls, init calls). `&var` outside a reference-argument
   or capture-list position stays an error.
2. **Typechecker validation** at the argument-checking sites (the same
   loops that run `_check_value_transfer` / exclusivity):
   - `&x` against `&var T` param → error: "parameter `s` is `&var
     String`; write `&var s`".
   - `&var x` against `&T` param → error: "parameter is `&String`;
     write `&s`".
   - `&var x` where `x` is a `let` binding → the existing
     immutable-binding error (verify it fires; add if missing).
   - Bare `x` against any reference param stays the existing error.
   Exclusivity accounting: read the mutability from the SIGIL now
   (should agree with the param type by construction after validation —
   assert, don't double-derive).
3. **Migration**: every existing call site passing `&x` to a `&var T`
   param (tests, examples, stdlib .saw files — stdlib methods take
   `&var self` implicitly and are unaffected; this is about explicit
   reference ARGUMENTS) flips to `&var x`. Mechanical; do it honestly
   file by file, no expected-output changes (behavior is identical).
4. **Tests**: acceptance (both sigils correct), the two mismatch errors,
   `&var` on a `let`, `&var` in a non-argument position error.
5. **Docs**: LANGUAGE_SPEC.md reference section + CLAUDE.md ("`&` at
   call site indicates variable may be mutated" sharpens to the
   two-sigil rule).

## Hazards
The migration touches many test files — no expected-output drift
allowed (pure syntax). Closure capture lists (brief 29, may land before
or after this) use the same spellings in a different position — keep
the parser paths separate; if 29 has landed, add one test mixing a
capture list and a `&var` call argument in one expression.

## Report back
Count of migrated call sites; mechanism + verification per item;
deviations; non-allowlisted commands.

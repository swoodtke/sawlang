# Design 205 — the platform pair converts by the book at transfers too

**Status: RULED Aug 10 (check-in) + AUTHORED; queue after 196/204 land.
Closes DF-195b and DF-195c — the last two SILENT integer conversions in
the language. `let b: Int8 = n` on an `Int` holding 300 prints 44;
`let i: Int = u` on `UInt.max` prints -1. Design 170 made every
narrowing and sign flip WRITTEN (`as` panics, `from` answers None,
`from(truncating:)` wraps); `_types_compatible`'s platform-`Int`/`UInt`
admission bypasses all three at transfer positions — a permission that
existed for bare-literal adoption, a job design 87's expected-type
propagation now does properly. Between two FIXED widths the same
transfer is already a clean error, so the hole is exactly the platform
pair. The ruling: both axes become ERRORS naming the three conversion
spellings — the transfer-position twin of design 195's operand rule.
Bare-literal adoption is UNTOUCHED.**

## Units

1. **Conformance rows FIRST (obligation 3).** The transfer-position
   matrix, mirroring 195's operator matrix: `let`/`var` init,
   assignment RHS, call argument, return, struct-field init, enum
   payload, array/tuple element, value-branch arm — each × (narrowing
   through platform Int; same-width sign flip; the LEGAL lossless
   widening control; the bare-literal adoption control). Reuse 195's
   W-row conventions; probe every cell before writing its expectation
   (some are already errors via the fixed-width rule — those become
   no-code-change rows).
2. **The fix.** Remove/narrow `_types_compatible`'s platform-pair
   admission so transfers take the same lossless-widening-only rule
   fixed widths already have; the error names both types and the three
   design-170 outs (`as` / `from` / `from(truncating:)`). One funnel —
   this is `_check_value_transfer` + `_widen_int_value` territory that
   195 u3 just consolidated; extend, don't duplicate (process rule 1;
   note DF-195e's two positions with no threaded source expression —
   closing them rides along if mechanical, else the finding stays open
   and says why).
3. **The consumer sweep (obligation 2 — this flips legal-today code).**
   Sweep examples/ + sawc/std + blade/ + libs/ + devtools/ + sos/ by
   COMPILE with the fix in (195's sweep found the corpus's mixed-width
   population small; the platform-pair population is the risk — std
   converts `Int` lengths into narrower wire fields in places). Record
   every site; each fix states the intended semantic (`as` when a
   violation is a bug, `from(truncating:)` when wrapping was meant,
   `from` + handling when input is untrusted). If the flush list
   exceeds ~30 sites, STOP and report before fixing — the ruling may
   want a second look at that scale.
4. **Pins + docs.** Flip
   `examples/int_narrowing_transfer_through_platform_int.saw` and
   `examples/int_sign_flip_transfer_through_platform_int.saw`
   (XFAIL DF-195b/c) to passing error tests; spec integer-conversion
   section gains the transfer rule (one paragraph: conversions are
   written EVERYWHERE, there is no position exemption); skill ownership
   bullet likewise. DF-195b/c close in the tracker.

## Gates

Per-unit commits, full tracked battery each; irdet --all (transfer
lowering); zero uncited xfails. The unit-3 sweep list is the review
surface.

## Explicitly out

Bare-literal adoption (unchanged, the carve-out both rulings preserve);
`as`/`from` semantics (design 170, untouched); float/integer mixing
(DF-195d closed as ruled — no adoption); operand positions (195 landed
them).

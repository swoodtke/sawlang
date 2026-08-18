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

## WORKED SOLUTION (lead, Aug 18 — built on main, verified, then REVERTED;
## reproduce these five edits as unit 2's starting point)

The mechanism was built and probed end-to-end on `edfda111`-era main. Five
edits, in dependency order — (b) and (c) are load-bearing prerequisites
discovered by the build, not optional companions:

**(a) `sawc/typechecker/types.py`, `_types_compatible` integer arm — THE
fix.** Same-kind only:
```python
        if a.kind in int_kinds and b.kind in int_kinds:
            return a.kind == b.kind
```
(was: `if a.kind in platform_int or b.kind in platform_int or a.kind ==
b.kind: return True / return False`). Comment should name what the
permission covered and the three design-170 outs.

**(b) `expressions.py` `visit_IntLiteral` — platform-`UInt` adoption.**
The funnel's case (1) already STAMPS a platform-`UInt` expectation
(`_int_range_for` answers INT/UINT target-width since DF-137d), but this
site honored `_FIXED_INT_RANGES` only, fell back to `Int`, and the compat
permission silently absorbed the mismatch. Without this, `var acc: UInt =
0` (three std sites) and `static BYTE_MASK: UInt = 255` break:
```python
            if rt is not None and (rt.kind in self._FIXED_INT_RANGES
                                   or rt.kind in self._PLATFORM_INT_KINDS):
                return SawType(rt.kind)
```
Also update `_apply_literal_expected_type`'s docstring — its "a platform
expectation leaves a literal at platform width" invariant is STALE prose.

**(c) `expressions.py` comparison arm — ordering bug unmasked.** The
`==`/`!=`/`<`/... arm runs a general `_types_compatible` PRE-CHECK before
design 195's `_check_operand_agreement` + `_adopt_bare_literal_operand`.
The old permission let integer pairs through to the agreement; strict, the
pre-check fires first with the worse message and refuses `probe >= 10` on
a `UInt`. Fix: integer pairs (both kinds in `_AGREEMENT_INT_KINDS`) skip
the pre-check entirely — agreement owns them.

**(d) `sawc/std/net.saw` `tcp_close` — the one real std bug**: `close(fd)`
passed platform `Int` to the `Int32` extern. `close(fd as Int32)`.

**(e) `statements.py` decl-site refusal — the ruled teaching hint** when
both sides are integer kinds: ``write the conversion: `as Int8` (panics
out of range), `Int8.from(...)` (answers None), or `Int8.from(truncating:
...)` (the deliberate wrap)``. Unit 2 should hoist this hint into a helper
the OTHER refusal sites (argument, return, field, assignment) call too.

**Verified green with (a)-(e):** std compiles; both pins refuse with the
ruled messages + hint; an 11-shape survivor probe (literal adoption at
fixed AND platform slots, negatives, arguments, written `as`, same-kind
transfers) all legal and correct.

**MEASURED BLAST RADIUS (the unit-3 stop-rule fires): 52 corpus
failures**, in three classes:
1. **The widening interaction — unit 2's REAL remaining work.** W12/W14/
   W15 (195's own value-branch rows) fail: `if a > 0 { 11 } else { 7i16 }`
   at `-> Int` errors "incompatible types: `Int` vs `Int16`". The
   value-branch/`??`/return LOSSLESS-WIDENING rule was partially
   implemented THROUGH the platform permission — the positional widening
   admission (`_check_value_transfer`/`_widen_int_value` territory) must
   be implemented on its own legs BEFORE (a) lands, or in the same unit.
   General assignability stays strict; widening is positional.
2. **Possible further adoption-entry gaps** — several data/cbor/alloc
   test failures not yet triaged; suspect post-hoc overload coercion and
   similar paths that leaned on the permission the way (b)/(c) did. Triage
   each: funnel gap (fix the path) vs class 3.
3. **True migrations** — tests that legitimately relied on silent
   platform laundering; each gets its written conversion with the intended
   semantic stated (the unit-3 protocol).

The full failing-test list is reproducible by applying (a)-(e) and running
the suite; 1966 passed / 52 failed on the Aug-18 tree.

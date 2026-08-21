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

## LANDING (Aug 21)

### What the units did

**Unit 1 — the matrix, as conformance rows W20-W24.** Fifteen transfer positions
(`let`, `var`, assignment RHS, call argument, return, struct field, enum payload,
fixed-array / tuple / `Vector` / `Map` / `Set` element, optional slot, default
parameter value, `static` initializer, the value-branch arm's home) × the four
conversion classes. W20 (narrowing) and W21 (sign flip) landed XFAIL against
DF-195b/c; W23 (bare-literal adoption) and W24 (two fixed widths, design 53's
no-code-change row) passed as authored. W22 — the lossless-widening control —
found **DF-205a**, filed with it.

**Unit 2 — the fix.** Five parts, in the order they had to happen:

1. **The positional widening, on its own legs (DF-205a).** Four transfer
   positions still widened by the TARGET's signedness — the implicit TAIL return
   (six fall-through `ret` sites passed no expression to `_coerce_ret_value`,
   where the explicit `return` passed `stmt.value`), a fixed-array LITERAL
   element, a tuple element and an optional payload. The array face was an ICE
   rather than a wrong answer: the literal took its LLVM element type off element
   0 instead of off the annotation, so `let a: [Int; 2] = [u, 0]` did not compile
   at all. One new codegen funnel, `_coerce_element_int`, plus the six threaded
   `final_expr`s.
2. **(a) `_types_compatible`'s integer arm is SAME-KIND ONLY.** Not directional:
   the relation recurses into invariant positions (a generic argument, a tuple
   element, an optional payload) where a `Vector<Int8>` must not be a
   `Vector<Int>`, so the widening admission cannot live here.
3. **The transfer funnel (obligation 1).** `_transfer_compatible(src, target)` is
   the one predicate every transfer position asks; its docstring names its entry
   points, and `_int_transfer_widens` is the admission itself (lossless, at least
   one side platform, target optionals peeled, aliases resolved on the SOURCE
   side only — resolving the target too would make `type MyInt = Int` reachable
   from a plain `Int`). `_int_conversion_hint` is the teaching hint, passed by
   every refusal site.
4. **(b)/(c) and their siblings.** Platform-`UInt` literal adoption in
   `visit_IntLiteral`; the comparison arm's pre-check skipped for integer pairs;
   the same skip at the three value-branch merges (`if`, `match`, `??`), which is
   what the worked solution's class 1 asked for — design 195 rule 2's merge owns
   an integer pair, admission and refusal both.
5. **(d)** std `net.saw`'s `close(fd as Int32)`.

**Unit 3 — the sweep.** See the migration list below.

**Unit 4 — pins + docs.** Both DF-195b/c pins flipped to passing error tests
(re-authored to assert the message AND the hint); LANGUAGE_SPEC's *Integer Width
Agreement* gained a third rule, "Plain transfers take the same rule"; the
saw-lang skill gained the matching bullet beside 195's two and a pointer from its
design-170 conversion bullet; README gained a "No integer conversion is silent"
bullet. DF-195b/c closed in place in the tracker, DF-205a with them.

### The unit-3 migration list — the review surface

The corpus failure count with (a)-(e) in and nothing else was **53** (the worked
solution measured 52 on the Aug-18 tree; the delta is unit 1's own three rows).
It split as the brief predicted, and the true-migration count came in far under
the ~30-site stop rule:

**Class 1 — the widening interaction (fixed at the path, no migrations).**
Resolved by the positional widening above and by the three value-branch pre-check
skips. W12/W14/W15 never regressed.

**Class 2 — adoption-entry gaps (46 of the 53; every one fixed at the path).**
Each was a position where design 87's expected-type stamp never ran, and the
closed permission had been absorbing the platform-`Int` literal that left behind.
Six paths, all now stamping BEFORE the argument is checked, like the paths that
already did:

| Path | Shape it broke | Fix |
|---|---|---|
| plain instance-method argument | `d.push(1)`, `small.put(3, 7)` | stamp added (the free-function, module-qualified and static-method paths already had it) |
| enum payload argument, both arms | `Wrap.Held(f: 42)` | the stamp ran POST-HOC, after the check — moved ahead of it |
| `borrows` accessor argument | `m.get(1)` on a `Map<Int8, V>` | stamp added in `places._check_window_args` |
| `UnsafeMemory.write(v)` | `reg.write(0x301)` in every driver | stamp added |
| `UnsafeMutableInterior<T>(v)` | `UnsafeMutableInterior<UInt8>(0)` | stamp added |
| overload candidate filter | design 55's `h(Int)` vs `h(Int8)` at `h(5)` | a bare literal / const is neutral against every integer parameter (the adoption reading, asked directly now); a typed argument fits only a lossless widening, and pays the exact-match penalty. Design 137's `Int`-vs-`UInt` exactness rides on top, restated for a pair general assignability no longer relates |
| a `type` ALIAS slot | `static ARENA: Region = [0; 8]` for a `type Region = [UInt8; 8]`; `let x: Small = 5` for a `type Small = Int8` | the funnel resolved no alias, so none of its shaping arms matched one. Only the OUTERMOST name is peeled (`_unalias_top`) — `_resolve_type_alias` also rewrites a struct's TYPE ARGUMENTS, and a `Vector<Handle>` must keep its argument |
| a SHIFT's shiftee | `static IRQ_CAUSE: UInt = 1 << 32`; `reg.write(1 << n)` for a runtime `n` (four sites in `sos/hal/arm64/kernel/lib.saw`) | `<<`/`>>` are the one operator whose operands are not peers — design 195 exempts the count — so the expectation forwards to the LEFT operand, exactly as it does through a unary minus. Design 235's const arm carries a foldable shift; this carries the rest, which is what makes the skill's documented "a shift passed DIRECTLY as the argument adopts" real adoption rather than a laundered mismatch |

Two more of the same shape, both about a value whose width is still undecided:
`_result_autowrap_ambiguous` (design 30 / DF-226e — a bare value at
`Result<Int32, Int8>` fits both payloads) now asks `_adopting_int_source` of the
EXPRESSION rather than reading the answer off the old permission; and the
`static` initializer check, whose arguments are written (declared, actual), asks
the integer question separately and in the right order rather than being swapped
outright — swapping it changed the ALIAS answer, which
`static_named_array_type_init` rides.

**Class 3 — true migrations: TWO sites in `examples/`, one in std.**

| Site | Written | Intended semantic |
|---|---|---|
| `examples/assignment_target_adopts_fixed_width.saw:144` — `nl = k` for a `let k: Int` into a `var nl: UInt32` | `nl = k as UInt32` | `as` — `k` is a program constant, so an out-of-range value would be a bug. The file's own comment asserted "a platform `Int` converts to and from any integer type by design", which was DF-195b/c; the comment is corrected in place and the row stays as the control beside the literal rows |
| `examples/funcpointer226_ffi_qsort.saw:40` — `sizeof<Int32>()` into C's `size_t` parameter (`UInt`) | `sizeof<Int32>() as UInt` | `as` — a type's size is never negative, so a value out of range would be a compiler bug |
| `sawc/std/net.saw` `tcp_close` — `close(fd)` passed a platform `Int` to an `Int32` extern | `close(fd as Int32)` | `as` — every fd in that file came out of a socket call that already answered an `Int32`. This is edit (d), and the one real bug the ruling was expected to surface |

No judgment calls: all three are `as`, and each is a value whose range is
guaranteed by the code that produced it rather than by input. Nothing wanted
`from(truncating:)` — no wrap was intended anywhere in the corpus — and nothing
wanted `from`, because no untrusted input reached a narrowing transfer.

**Class 4 — two DECLARATIONS corrected, which is not a conversion at all.**
`sos/tests/uart-echo-{ns16550,pl011}/src/main.saw` each held `var line = 0`
for a value `woke_on_line` answers as a `UInt` and `UART_IRQ` declares as a
`UInt`. The local was platform `Int` only because nothing annotated it, and the
old permission laundered the assignment; the fix is `var line: UInt = 0`, not a
written conversion. Nothing else under `sos/` needed anything: the GIC and
static-shift sites the first sos_runner pass reported were the shift
adoption-entry gap in the table above, closed at the path.

**Per-tree counts.** `examples/`: 2 migrations, 51 class-2 failures resolved at
the six paths. `sawc/std/`: 1 migration (`net.saw`). `sos/`: 2 declaration
corrections, 4 class-2 sites (one file). `blade/`, `libs/`, `devtools/`: zero —
the `bootstrap` and `gmgate` lanes compile and run all three and are green.

### DF-238a: what this fix does to it, and what it leaves

DF-238a was filed on main (design 238 unit 1) after this branch was cut, and its
entry records the composition deliberately: 238a is why a literal is still an
`Int` at a module-qualified call, DF-195b is why an `Int` could then land in a
`UInt8` with nothing said. Probed against this branch's compiler, with main's own
fixture:

```
qualcall.take_byte(300)      // was: compiles, callee receives 44
error: argument `b` expects `UInt8` but got `Int`
hint: write the conversion: `as UInt8` panics out of range, …
```

So the SILENCE is gone — which is the half design 205 owed — and the diagnostic
is still the wrong one: it names the argument, where the literal's own range
check would name the value and the type. DF-238a therefore STAYS OPEN and its
pin (`examples/qualified_call_literal_adopts_parameter_width.saw`) stays a
legitimate XFAIL: it asserts `integer literal 300 does not fit in \`UInt8\``,
which this branch does not produce. Its two CONTROLS (the qualified static
method and the qualified constructor) still compile — one error, not three.
Nothing to do here; recorded so the integrator does not read the surviving
XFAIL as a regression, and so whoever takes 238a knows the shape it now
presents in.

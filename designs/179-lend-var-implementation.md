# Design 179 — `#lend_var`: implementation

**Status: GO (user, Aug 7 evening). The SPEC is design 175's investigation
report (designs/175-lend-var-investigation.md — read it FIRST; its probe
matrix, architecture findings and worked Data.[] patch sketch are the
design). Both prerequisites are LANDED via design 176: DF-175a (a `&self`
method may not write its receiver) and DF-175b (shared windows lend
read-only, structurally). Naming settled: `#lend_var`, permission not
intent, the `&var`/`with_var_ref` family.**

## Units (from the report's own effort plan)

1. **The constant + fold**: `#lend_var` legal only inside a `borrows` body
   (clean error elsewhere); source-level duplication in `place_transform.py`
   (which already runs pre-typechecker) — an accessor MENTIONING the
   constant compiles as two specializations with the branch pruned; one
   that doesn't compiles ONCE exactly as today. The report's discovery
   holds: no mangler work (accessors are already multi-symbol per window
   result type); use-site retargeting hooks `place_uses._chain_is_exclusive`.
2. **Checker semantics per specialization**: the shared copy is checked as
   a genuinely non-mutating `&self` body (176's corrected rule applies);
   the var copy gets the exclusive receiver. A `&var self`-DECLARED
   accessor mentioning `#lend_var` is the redundancy error the report
   recommends.
3. **The Data.[] pilot lands for real**: gate under `if #lend_var`, the
   accessor returns to `&self`, `d[i]` reads work on `let` roots again;
   the three formerly-broken read sites (irdet same_bytes, both serde169
   encoders) get their natural `bytes[i]` spelling RESTORED as the proof;
   `get(i)` stays (DF-146j synonym — shared-`[]` and `get` now converge).
4. **Composition tests** from the report's matrix: conditional lends,
   epilogues per copy, LIFO nesting, match-arm payload lends, generic
   accessors, coro contexts, and the forwarded-inner-accessor pessimization
   pinned as documented behavior (always-exclusive; a finding, not a fix).
5. **DF-146k unlock probe (small, report if real)**: `#lend_var` may give
   Set its shared-only accessor for free — `if #lend_var { <compile-time
   reject> }`-shaped or a natural extension. PROBE and report only; the
   accessor itself is a user decision (146k stays open).
6. **Docs**: spec (places section — the constant, the two-specialization
   model, the Data example), skill (headline idiom), README one-liner;
   `--emit-docs` gains the flavor note ONLY if trivial, else DF-175c stays
   filed. Tracker: close DF-165c (the `_read`/`_modify` want — this IS the
   answer), note the three restored call sites.

## Gates

Per-unit commits, full battery each (suite zero uncited xfails, lexdiff,
astdiff, Saw-irdet --all, bootstrap, gmgate, sos both arches). The pilot
unit's battery is the real proof: Data's CoW value semantics tests
(data_cow_*) must stay green with `[]` back at `&self`. DF-179x findings,
fixed or filed, never worked around.

## Explicitly out

The Swift-style two-body split (rejected by the report); Set's accessor
decision (146k); `--emit-docs` overhaul; any DF-176a/b work (own rulings
pending).

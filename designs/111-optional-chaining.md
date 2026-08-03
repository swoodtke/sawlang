# Design 111 — full optional chaining (queued Aug 3, behind 110)

User request (Aug 3), on the back of the doc audit's discovery: `?.`
today supports ONLY single-hop struct FIELD access (`p?.x`). A method
hop (`p?.mag()`) errors "struct `Point` has no field `mag`", and a
multi-hop chain (`u?.profile?.bio`) errors "cannot access member of
non-struct type" (probed Aug 3). The docs were scoped to match
meanwhile (spec Optionals note, skill bullet, README "(illustrative)"
tag); this design makes the full form real:

```saw
let result = x.a()?.b?.c()
```

## Semantics (Swift-style; pinned)
1. `e?.field` and `e?.method(args)` are legal where `e: T?`. `None`
   short-circuits; `Some(v)` projects the field / calls the method on
   the payload.
2. Chains are arbitrary postfix sequences. Each OPTIONAL hop carries
   its own `?`; a non-optional intermediate uses plain `.`. Once a `?`
   short-circuits, the REST of the postfix chain is skipped (Swift
   binding: in `a?.b.c`, `b.c` applies only when `a` is non-None and
   `b` need not be optional).
3. The head may be any Optional-typed expression, including a call
   result: `x.a()?.b?.c()`.
4. FLATTENING: the chain's type is `U?` where `U` is the final
   segment's non-optional type; a final segment already yielding `U?`
   stays `U?` — `U??` is never produced.
5. Short-circuiting skips ALL later evaluation, including argument
   expressions of skipped method calls. This is a documented,
   deliberate carve-out of the left-to-right argument-evaluation rule
   (spec "Argument Evaluation Order") — the skip is observable and
   tested (side-effect counter).
6. `?.` on a non-Optional expression stays a clean error (no silent
   no-op).
7. Ownership: intermediate payloads are accessed IN PLACE (borrow, no
   copy, no consume — chaining an owned Optional does not consume it).
   A final FIELD projection copies the value (requires a copyable
   type, matching today's single-hop `p?.x` and `Vector.get`); a final
   METHOD hop returns its fresh result, unrestricted. A chain in
   statement position (result discarded) is fine.
8. Composition: the result is an ordinary Optional — `??`, `if let`,
   `guard let`, `!`, match all apply unchanged.
9. CHAINED ASSIGNMENT is IN scope (user decision, Aug 3):
   `x?.y = v` (and longer chains, `x?.a.b?.c = v`) writes through the
   chain iff every optional hop is non-None. Swift-matching rules,
   adapted to Saw:
   - The write targets the payload IN PLACE (this is the only
     conditional write-through spelling Saw has — `if let` binds a
     COPY of the payload, so unwrap-then-assign cannot write back).
   - Short-circuit skips the RHS entirely: in `x?.y = f()`, `f` is
     NOT called when the chain is None (same documented eval-order
     carve-out as reads; side-effect-counter test).
   - The RHS follows ordinary assignment transfer rules per the
     referent field's type — implicit copy where the tier allows,
     `move`/`.copy()` for ExplicitCopy, `move` for NoCopy — matching
     design 110's rule (the old field value deinits exactly once on
     the written path; nothing drops on the skipped path).
   - The assignment EXPRESSION has type `Void?`: `None` = skipped,
     wrapped unit = written. Statement position discards it silently
     (the common case). "Did it happen" is consumed via optional
     binding, NOT a `!= nil` comparison (un-Saw-like):
     `guard let _ = x?.y = v else { ... }`.
   - Mutability: the chain HEAD must be a mutable place (a `var`
     binding or `&var`-reachable path), checked like any assignment
     target; exclusivity applies to the written root path as usual.
10. RIDER: bless `_` as the bound pattern of `if let` / `guard let`
    (`if let _ = opt`, `guard let _ = opt else`) — evaluate + test the
    Optional, bind nothing, payload dropped immediately (the optional-
    binding twin of the statement discard `let _ =`). Needed to
    consume the `Void?` idiomatically; useful generally.
11. OUT of scope v1 (each stays a clean error, noted in docs): `?.`
    indexing; a SUSPENDING method inside a chain (read OR write side)
    keeps the existing buried-in-larger-expression clean error (coro
    transform, design 104 list) — bind the optional first and use
    `if let` + a statement call instead.

## Scope
1. Parser: generalize the OptionalChain postfix (expressions.py ~492)
   to method hops and arbitrary chain length (verify what already
   parses vs. what the typechecker rejects — the gap may be mostly
   typechecker/codegen).
2. Typechecker: type the chain per semantics 1-6 (per-hop payload
   projection, method resolution against the payload type incl.
   extension methods and trait methods, flattening, the final-hop
   copyable check for fields).
3. Codegen: lower to short-circuit control flow (test-and-branch per
   `?` hop over the existing Optional encoding); deinit discipline
   for mid-chain method-result temporaries (drop exactly once on both
   the taken and short-circuited paths).
4. Effects: a chain containing only sync hops is sync; a suspending
   method hop is rejected per semantics 11 (existing diagnostic —
   regression-test it).
5. Chained assignment (semantics 9): typecheck the write target
   through the chain (final hop must be a FIELD of the payload;
   mutability + exclusivity on the root path; RHS transfer rules);
   codegen the short-circuit write with RHS skip and deinit-once of
   the old field value on the written path. `Void?` result type;
   statement-position discard.
6. `_` optional-binding rider (semantics 10): parser + typechecker
   for `if let _ =` / `guard let _ =`; the design-100 shadowing rules
   are untouched (`_` binds nothing).
7. Tests: multi-hop fields; `?.method()` (incl. extension + trait
   default methods); mixed field/method chains; Optional-returning
   call head (`x.a()?...`); flattening (no `U??`, incl. final `U?`
   segment); None at EACH hop position; short-circuit side-effect
   skip (counter fn as a skipped call's argument); `??`/`if let` over
   a chain; statement-position chain; errors: `?.` on non-Optional,
   final NoCopy field projection, suspending method in a chain
   (existing diagnostic). Assignment: write lands (caller-visible);
   None at each hop skips write AND RHS (counter); `Void?` via
   `guard let _ =` and `if let _ =`; ExplicitCopy RHS without `move`
   rejected; old field value deinit-once on written path; head
   through a `let` binding rejected (immutable); exclusivity overlap
   on the written root rejected; statement-position discard silent.
   `_`-binding: over a plain Optional (both forms), payload deinit
   verified for a Deinit payload.
8. Docs: spec Optionals section (replace the Aug-3 single-hop note
   with the full rule — reads AND assignment, `Void?`, the eval-order
   carve-out); skill Optionals bullet; README drops "(illustrative)"
   from the chaining example; CLAUDE.md digest clause; tracker entry
   closed. ALSO (user request, Aug 3): state explicitly in spec +
   skill that CHAINS of suspending functions/methods are not
   supported — `foo().bar().a` requires every call in the chain to be
   sync (probed: "suspending call ... appears in a nested/expression
   position"); the blessed spelling is unchaining into `let`
   statements, each of which embeds at any control-flow depth. This
   is the general design-104 buried-suspension rule, but the docs
   should name the CHAIN case since it is the common way to hit it.

## Future work (recorded in todo.md at brief commit — do not re-add)
- Suspension mid-chain: supporting a suspending hop in a postfix or
  `?.` chain means lowering the chain to a resumable multi-state
  expression (frame-resident intermediates, short-circuit resume
  paths). Equivalent unchained spelling exists; only worth designing
  if the ergonomic pull proves real.

Bars: full suite zero xfails + bootstrap green per commit; per-unit
commits; linear history; no attribution trailers; foreground suites;
interruption-safe; new discoveries tracker-flagged, not scope-crept.
SEQUENCING: dispatch only after design 110 lands and integrates (one
agent at a time on main; this file stays untracked until then).

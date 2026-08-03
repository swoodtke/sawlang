# Design 110 — replacement assignment through `&var` references (queued Aug 3)

Found by the Aug-3 four-source doc audit. Today's rules are an island
of inconsistency: `x.field = v` through a `&var` function param WORKS
(including Deinit fields — the old String drops at a distance and a
new value installs through borrowed storage), and a closure's `&var`
param or `[&var]` capture permits plain `n = v` (the name is
registered at referent type, "reads/writes the referent directly"),
but whole-referent `x = v` through a function/method `&var` param is
rejected (`statements.py:1364-1370`). No design brief records a
rationale; the surviving principle ("a bare-name assignment never
writes caller storage") is already broken by closures. Concrete
expressivity hole: wholesale replacement of an opaque referent
(`String`, `Vector`) through a function ref is INEXPRESSIBLE — no
public fields to assign, `self = v` hits the same ban, `move` out is
banned. `Mutex<String>` payload replacement works only via the
closure path.

DECIDED (with user, Aug 3): unify PERMISSIVE — option C. A `&var T`
name behaves uniformly as "the caller's variable": whole-referent
assignment becomes legal through function/method reference
parameters, matching closures and Swift `inout`.

## Semantics
1. `x = v` where `x: &var T` is legal iff `v` type-checks exactly as
   it would against `var x: T = v` (same type rules as ordinary var
   assignment). The caller's binding is NEVER invalidated: the old
   value deinits exactly once, the new value installs in place, and
   the caller still owns a valid `T` afterward — replacement, not
   transfer.
2. The RHS goes through the ordinary value-transfer checkpoint, same
   as any var assignment: trivial/ImplicitCopy copy implicitly; an
   existing ExplicitCopy/NoCopy binding needs `move v` / `.copy()`;
   a fresh temporary (call result, literal, constructor) needs
   nothing. The `move` consumes the CALLEE's local — the caller's
   object is the thing being replaced and stays valid. (DECIDED with
   user Aug 3: RHS `move` is in scope.)
3. Unchanged bans (each keeps its current diagnostic): `move x` OUT of
   a reference (would invisibly invalidate the caller's object);
   `x = v` through an immutable `&T`; exclusivity (the assignment is a
   write access on the root path, covered by the existing check).
4. `&var self` methods: `self = v` becomes legal by the same rule
   (Swift mutating-self precedent). (DECIDED with user Aug 3: in
   scope; split to a follow-up only if codegen genuinely diverges.)
5. Drop order: deinit the old referent value, then store the new one —
   identical to existing var-reassignment and through-ref field-
   assignment behavior (no new panic-window semantics invented).
6. GENERIC referents are IN (probed Aug 3): `func f<T: Shape>(p: &var T)`
   may assign `p = v` where `v: T`. The abstract body checks the RHS
   against `T` (same transfer rules generic bodies already apply to
   `T`-typed values — `let w = v` compiles today for abstract T; `p = v`
   behaves identically); monomorphization makes every instantiation's
   referent a concrete sized type, so the store is ordinary. Note the
   type discipline this buys: inside the generic body the RHS must BE a
   `T` (another param, a T local, a T-returning call) — a callee can
   never smuggle in a different concrete Shape, which is exactly what
   the existential exclusion below prevents dynamically.
7. EXISTENTIAL referents are EXCLUDED (decided with user Aug 3): the
   referent of `x = v` must be a STATICALLY-KNOWN type — concrete or a
   type parameter. Only ERASED referents are out.
   Assignment through `&var any Trait` stays banned — behind erasure
   the caller's storage is a CONCRETE type (a `Circle`-sized frame
   slot, a `Circle`-typed binding after return), so a differently-
   typed store would corrupt the slot and break the caller's static
   type; the identical-type rule is statically unsatisfiable there.
   New SPECIFIC diagnostic (not the generic ban): the concrete type is
   erased — replace at the `Box<any Trait>` level instead. In-place
   mutation via `&var self` trait methods through `&var any Trait` is
   untouched (works today, probed). The payload-swap idiom that DOES
   work under this design: a `&var Box<any Trait>` referent is a
   sized concrete type, so `b = move Box<any Shape>.make(Square(...))`
   replaces the payload, caller's binding stays a valid
   `Box<any Shape>` throughout.

## Scope
1. Typechecker: narrow the REFERENCE rejection in
   `statements.py:1364-1370` to `&T` only; route `&var` whole-referent
   assignment through the normal assignment/checkpoint path against
   the referent type.
2. Codegen: load the reference's pointer, deinit the old value at the
   referent address, store the new value. Building blocks exist (var-
   reassignment drop; through-ref field-assignment addressing) — this
   is the whole-value case of machinery already shipped.
3. Composition surfaces (each needs a test, none expected to need new
   design): assignment through a FORWARDED ref (design 106 re-borrow,
   root-path exclusivity); through a ref held ACROSS A SUSPEND
   (design 88 frame-resident pointer — the write must land in the real
   caller slot); inside a driven/spawned body.
4. Closures: no behavior change (already permissive); the language
   rule becomes uniform.
5. FIX-ON-DISCOVERY rider (probed Aug 3): a BARE trait name behind a
   reference — `func x(p: &var Shape)` — is an ICE ("internal compiler
   error: Undefined struct: Shape"). Emit the clean unsized-trait
   error naming the fix (`&var any Shape`), same class as the existing
   `any`-placement diagnostics. Applies to `&T` position too.
6. Tests: replace Int/String (deinit-once verified)/Vector (`move`
   RHS) through a fn ref; reject through `&T`; reject `move` out of a
   ref (regression); ExplicitCopy RHS without `move` rejected;
   forwarded-ref and across-suspend replacement; `self = v`;
   exclusivity-overlap regression; `&var any Trait` assignment
   rejected with the new erased-type diagnostic; `&var Box<any Trait>`
   payload-swap WORKS; bare `&var Shape` param → clean error (was
   ICE); generic `<T: Bound>(p: &var T)` replacement `p = move v`
   instantiated at 2+ conforming types incl. a Deinit type
   (deinit-once verified), and a wrong-typed RHS in the generic body
   rejected abstractly.
6. Docs: spec §Reference Types + §Law of Exclusivity + Closures notes
   (REMOVE the function-vs-closure caveat added Aug 3; state the
   uniform rule); skill ownership section likewise; README example
   comment; tracker DECIDE item closed into this design.

Bars: full suite zero xfails + bootstrap green per commit; per-unit
commits; foreground suites; interruption-safe; skill self-review.
New discoveries briefed + tracker-flagged, not auto-dispatched.

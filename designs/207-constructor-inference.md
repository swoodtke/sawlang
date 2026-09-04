# Design 207 — constructors infer their type arguments

**AMENDMENT (Sep 4 2026): SCHEDULED by DF-294d's ruling** (sos SL-22 —
the un-wrappable generic static head exists because constructors write
the type twice; the user ruled "design 207 + interim doc"). The interim
spec/skill lines blessing the parenthesized-initializer wrap landed
Sep 4; this brief dispatches after the soundness pair integrates
(typechecker surface, serial). **ONE NEW CELL THE MOTIVATING CASE
DEMANDS, flagged for a ruling before dispatch:** the brief's matrix as
authored is ARGUMENT-driven, but sos's shape is
`static EVENTS: Slab<EventSlot, MAX_EVENTS> = Slab(...)` — an EMPTY
constructor whose arguments mention no type parameter, solvable only
from the ANNOTATED SLOT. The lead-recommended widening: the expected
type joins the solver as an inference source for constructors (the
slot's `T<Args>` unifies with the constructed type — exactly the
adoption shape bare literals already take at annotated slots; explicit
`<...>` still wins; a MISMATCH between slot and explicit args is the
ordinary transfer error, not a solver conflict). Without this cell, 207
deletes the doubled spelling only where an argument happens to name
every parameter, and SL-22's nine declarations keep their second
spelling.

**Status: RULED Aug 10 (user: "generic constructors should infer their
type arguments — anything we can accurately infer should be inferred")
+ AUTHORED; queue after 205 (typechecker inference machinery, serial
with typechecker briefs). Found by dogfood wave 1 (the limiter agent
hit it; the lead had hit the identical `Arc<Res>(value:)` friction the
same morning and routed around it without registering it — the
expert-blindness case the instrument exists to catch).**

## The ruling and its principle

`Arc(value: r)` where `r: Res` infers `Arc<Res>`; `Mutex(value: 0)`
infers `Mutex<Int>`. The design-93/105 solver already does exactly this
for generic free functions and methods — argument types (and closure
returns, labeled mapping, later-arg fixpoint, defaults driving
inference per 108) solve the type parameters, explicit `<...>` always
wins, underdetermined and conflicting are clean errors. Constructors
were simply never routed through it. The governing principle, recorded
for future briefs: **anything the compiler can ACCURATELY infer should
be inferred** — explicitness is reserved for places where inference
would guess (ambiguity, underdetermination), not used as ceremony.

## Units

1. **Conformance/examples first.** The inference matrix for
   constructor positions: struct `init` calls (`Arc(value: r)`),
   memberwise literals (`Pair(a: 1, b: "x")` for `Pair<A, B>`), nested
   (`Arc(value: Mutex(value: Stats(...)))` — the dogfood shape, each
   layer solving from the one below), generic ENUM case constructors
   (`Wrap.Some(v: 5)` where payloads determine every param),
   partial-explicit (`Pair<Int>(a: 1, b: "x")` pins A, infers B),
   default-type-param fill (design 37), default-VALUE-driven (108),
   and the clean-error rows: underdetermined (`Vector()` — no argument
   mentions T; error names the explicit spelling), conflicting, and
   bound-violating inferred args (109's checking applies to inferred
   ctor args identically).
2. **The routing.** Constructor call checking (struct init resolution,
   memberwise-literal checking, enum-variant construction) routes
   through the design-93/105 solver instead of demanding explicit
   arguments up front. Reuse the solver — no second inference engine
   (process rule 1: the solver's docstring gains the constructor entry
   points). Overload interaction: inits are an overload set already
   (design 55/95 keying) — inference runs per candidate exactly as 105
   does for functions, unique solve wins, ties are the ambiguity error.
3. **Consumer sweep (obligation 2 — additive, so expect zero breaks,
   but verify).** Nothing legal today becomes illegal (explicit args
   keep winning); the sweep is the suite + a check that no diagnostic
   TEXT regressed (several tests assert the "requires type arguments"
   error — those flip to inference-success or reword; each is examined,
   not blanket-updated).
4. **Docs.** Skill + spec inference sections: "generic type-argument
   inference" loses its functions-and-methods-only qualifier and gains
   the constructor examples + the underdetermined `Vector()` error;
   README's generics bullet updated. The dogfood doc-batch line about
   constructors NOT inferring is superseded before it lands — check the
   batch.

## Gates

Per-unit commits, full tracked battery each; irdet --all (inference
changes what monomorphizes — determinism is the check). Zero uncited
xfails. Any interaction with erased `Box<any Trait>` construction or
`Optional`/`Result` auto-wrap that the matrix reveals as ambiguous
STOPS and files rather than guessing.

## Explicitly out

Expected-type-DRIVEN inference (`let m: Mutex<Int> = Mutex(value: 0)`
already works via arguments; a future "target typing" step where the
ANNOTATION solves an otherwise-underdetermined constructor is its own
brief under the same principle — noted, not taken); variadic or
higher-kinded anything; `Box<any Trait>.make`'s erased spelling
(unchanged).

# Design 219 — generic tier requirements: inference, discharge, and the DF-217i ruling

**Status: WAVES A, B AND C LANDED (Aug 14 2026). This WAS the DF-217i fix, and
it has discharged design 218's gate — including the DF-217j enforcement
dependency stages 1-2 named.**

## The hole (evidence: sweep S1, 30 probes, `.build/scratch/sweep_absT/`)

A generic body is judged once with `T` abstract, abstract `T` answers every
tier question most-permissively, and nothing re-judges at instantiation
(monomorphization is codegen-side; the one mono re-check that exists deletes
its own errors, effects.py:509). Proven consequences: bind-twice at NoCopy =
3 deinits + use-after-free (DF-217i); `T: Copy` at ExplicitCopy = silent
bitwise copy, SIGTRAP (S1 row 9d — today's behavior is a MISCOMPILE, not a
semantic to preserve); nesting multiplies; generic methods identical; generic
COROUTINES pass the post-transform re-check vacuously (row p08a).

## The ruling (SIMPLIFIED per user, Aug 13 — binary inference, one rare explicit bound)

**Requirement inference is BINARY + call-site discharge rejection.** The body
is walked ONCE at definition time; per type parameter:

| body does | requirement | how it arises | satisfied by (DERIVED tier) |
|---|---|---|---|
| only moves `x` / never binds by value | move-only (bottom) | inferred | every tier incl. NoCopy |
| silently re-binds / by-value twice / place value-read | needs-implicit-copy | inferred | trivial, ImplicitCopy ONLY |
| spells `x.copy()` | explicit-copy | **NEVER inferred — requires a DECLARED `<T: ExplicitCopy>`**; `.copy()` on abstract `T` without it is a definition-time error ("declare T: ExplicitCopy") | ExplicitCopy, ImplicitCopy, trivial — `.copy()` lowers tier-correct (real copy / retain / bitwise) |

The middle rung is deliberately NOT in the inference: explicit copies get
explicit bounds — the tier that demands ceremony per use demands a visible
contract per signature, and it is expected to be RARE. **The legacy `T: Copy`
bound RETIRES from generic signatures** — it is the ambiguity (it admits
ExplicitCopy arguments into silently-copying bodies, which IS the 9d
miscompile). Existing `T: Copy` sites migrate to `ImplicitCopy` or
`ExplicitCopy` per what their body actually does; the consumer sweep produces
the migration list, and design 216's Vector rework (`&T` element closures)
deletes most of std's Copy bounds independently.

Bound discharge — the machinery that already runs per call site with good
anchored errors (S1 p09c) — checks the argument's DERIVED tier against the
requirement. `launder<Res>` dies AT THE CALL: "`launder` requires `T` to be
implicitly copyable (it binds `x` twice at LINE); `Res` is NoCopy". Best
attribution of every option considered: caller's line, the requirement, the
reason, the definition anchor. Zero per-instantiation checking cost for tier
rules; the S1 9d miscompile becomes a clean call-site refusal (a re-binding
body infers needs-implicit-copy, so an ExplicitCopy argument is REJECTED
rather than silently bitwise-copied; a body that spells `.copy()` accepts it).
The body's own spelling is the license — no redefinition of `Copy` needed.

## Tier-aware bounds (probe-found gap, `implicitcopy_bound_probe.saw`)

**Today `T: ImplicitCopy` rejects BOTH trivial `Int` AND an auto-ImplicitCopy
struct** (`Bag { s: String }` — which design 139 says IS ImplicitCopy with no
declaration owed). Bounds check DECLARED conformances; tiers are a separate
derivation; they have never met. Unit 1 unifies them: a tier-family bound is
satisfied by DERIVED tier — `T: ImplicitCopy` = tier ∈ {trivial,
ImplicitCopy}; `T: ExplicitCopy` = tier ∈ {trivial, ImplicitCopy,
ExplicitCopy}. (`T: Copy` retires from generic signatures per the simplified
ruling above; during migration it reads as whichever of the two its body
requires.) Consumer-sweep item: any overload resolution or conformance check
whose outcome changes when `Int`/auto-tier structs start satisfying
`ImplicitCopy`.

## THE API-STABILITY CALLOUT (user, Aug 13 — named behavior + mitigation)

Pure inference means EDITING A BODY can silently TIGHTEN its requirement —
a maintainer adds a second bind, and downstream callers at ExplicitCopy/
NoCopy types break with no signature change. This is why Rust refused
inferred bounds; Saw's doctrine (infer what is determined) admits them, but
the hazard is real and is hereby CALLED OUT as the design's known trade.

**The mitigation: the writer binds the parameter — `<T: ImplicitCopy>` as
the standard spelling, `<T: ExplicitCopy>` in the rare `.copy()` case — and
the declaration becomes the contract.** Where a bound is
declared, the compiler checks the BODY FITS WITHIN IT at definition time
(exceeding your declaration is a definition-time error with the design-146
doctrine message — "would be a copy for some instantiations and an alias for
others"); the requirement can then never drift without a visible signature
change. Where no bound is declared, the inferred requirement IS the contract,
surfaced in `--emit-docs` and in every call-site refusal. RULING WANTED at
dispatch: for MODULE-PUBLIC generics, declaration is (a) REQUIRED (hard
error: "public generic must declare its tier requirement") or (b) warned
(`-W inferred-generic-requirement`). Recommendation: (a) for public surface —
an API contract enforced only by an off-by-default warning is not a contract;
private/internal generics ride pure inference freely.

## THE VOCABULARY UNIT (RULED, user, Aug 13 — the tier system's final form)

Three words, one job each; `ImplicitCopy` and ExplicitCopy-the-TIER retire:

- **`Copy`** — THE silently-copyable tier (today's trivial + ImplicitCopy
  merged; bitwise-vs-retain stays a codegen detail). Auto-derived
  structurally (design 139 restated: all members Copy → Copy). A DECLARED
  conformance has two forms, both kept:
  - EMPTY (`extension P: Copy {}`) = an ASSERTION — compiles iff the members
    qualify, and keeps compiling only while they do: a type-level API
    contract mirroring this brief's declared-bound rule.
  - WITH a `copy()` body = THE RETAIN HOOK: codegen calls it at every silent
    transfer (`_emit_retain_at`, resources.py:807 — its comment already says
    "String/Arc/user type"). This is the mechanism `Arc`/`Channel` are BUILT
    ON, in visible stdlib Saw (arc.saw:137-165: atomic add copy, atomic
    sub + fence + drop-glue deinit) — NOT compiler magic, and retiring it
    would force refcounting INTO codegen, the opposite of design 218. It is
    also what lets users write their own Arc-alikes in ordinary Saw.
    **CONTRACT (user ruling): valid but a potential performance footgun —
    something to DECLARE AND DOCUMENT, not mechanically ban.** The trait
    docstring states the expected shape (cheap, infallible, `sync` — the
    retain shape); a heavy body is legal and its cost is the author's
    documented choice. LANGUAGE_SPEC + skill carry the warning prominently.
- **`NoCopy`** — unchanged: the declared opt-out making an otherwise-Copy
  type move-only; still the carrier for hand-written deinit bodies (131).
- **`ExplicitCopy`** — an ordinary synthesizable TRAIT (`copy(&self) ->
  Self`; `@synthesize` memberwise derivation survives character-for-
  character). Blanket-satisfied by every Copy type (`copy()` ≡ the silent
  copy), so `<T: ExplicitCopy>` means "duplicable, possibly with ceremony".
  The TIER dissolves into move-only; the transfer rule becomes one
  sentence — non-Copy values move; the refusal hints `.copy()` iff the
  conformance exists.

Census rows this adds to the consumer sweep: (a) every compiler site keyed
on the ExplicitCopy TIER beyond refusal+hint (suspects: the hint text,
`@synthesize` derivation, design-139 wrapper carrying, `_frame_read_policy`'s
'explicit' arm — each survives as a conformance lookup); (b) the corpus-wide
`ImplicitCopy` → `Copy` rename (declarations, spec, skill — mech batch);
(c) corpus types declaring ImplicitCopy WITH a hand-written `copy()` (known:
one test fixture); (d) **the `--no-hidden-alloc` question** — does an
inserted `copy()` that allocates count as a design-135 hidden allocation?
If not, that gate (or a `-W` category) is the natural soft-enforcement hook
for the performance contract — investigate, never ban. Note the knock-on
simplifications: the 216b stopgap's tier condition restates as "move-only",
`Slot`'s tier table loses a row, and the `&Self` brief's conformer updates
shrink.

## What this deliberately does not cover

- **DF-217j / DF-217k are declaration-level**, not body-level: the NoMove
  containment cascade and the unsafe-signature rule get the PER-INSTANCE
  DERIVATION EXTENSION (the copy-policy derivation, p04g, already runs per
  instance — wire the NoMove cascade and design-130 signature rule to the
  same machinery). Unit 3 here; no attribution problem (errors anchor at the
  instantiating type argument).
- **NoMove arguments** are mostly self-excluding (a by-value parameter
  cannot receive one) — covered by unit 3's cascade fix, not the lattice.
- **Unit 1.5's instance re-check stays as the BACKSTOP** (218's ruling):
  post-1.5 the re-check runs with errors real and is EXPECTED SILENT for
  tier rules — the Send-lane shape. It remains the net for rules outside
  the copy lattice and for transform output.

## Bonus: C07's funnel falls out

The 216b stopgap left row C07 open (generic body, comparison operator, NoCopy
instantiation) because the operand reaches `_check_binary_op` only as
abstract `T`, and pushing the rule into `_bound_satisfied` would wrongly
refuse `Map<Tag, V>` keys. Requirement inference dissolves the objection: a
body using `>` on `T` infers "requires non-consuming comparison", and
discharge refuses only a type whose comparison tree reaches a hand-written
consuming body (the 216b transitive query, evaluated at the concrete
argument) — `@synthesize`d conformers pass, Map's Copy-gated keys pass. C07
flips HERE (or at `other: &Self`, whichever lands first; coordinate).

## WAVE-B RIDER (user, Aug 13): prefix `*` deref as parser sugar

`*expr`, where `expr` is pointer-typed, desugars in the PARSER to the same
pointer-place production as `expr[0]` — one grammar arm (prefix position,
disambiguated like unary `-`), checked and lowered on the EXISTING place
path, nothing new in checker or codegen (the desugar-early principle; the
`[]` borrows-operator method is the precedent that operator-shaped places
are established machinery). NOT a general user-definable prefix operator —
that surface stays closed. Motivation: `ptr[0]` conflates array indexing
with single-pointee deref; std's sites are mostly single-object pointers,
where `*__recv` and `let v = move *val_slot` state the intent precisely
(the A2 move spelling composes: `move *ptr` is the fourth move-out family
member in its most readable form). Rides WAVE B because it touches the
same pointer-place code A2 reorganizes; costs both-lexer/parser parity
(lexdiff/astdiff gated) + spec grammar text; A2's conformance rows gain
the `*` spelling variants when it lands. All uses sit inside
`unsafe`-declared code, so the audience is the trusted base's authors.

## Units

0. Conformance rows FIRST (obligation 3): the S1 matrix rows (bind-twice,
   by-value-twice, 9d's ExplicitCopy shape, nested, generic-method,
   generic-coroutine) + the tier-aware-bound rows (Int and auto-tier Bag
   satisfy `ImplicitCopy`) + C07's flip shape. The DF-217i pin flips here.
1. Tier-aware bound satisfaction (+ its consumer sweep).
2. Requirement inference + discharge rejection + the definition-time
   coverage check. ONE funnel: discharge; the inference is its input
   (obligation 1 satisfied at the chokepoint that already exists).
3. The declaration-derivation extension (DF-217j, DF-217k).
4. The public-declaration rule (per the ruling taken at dispatch).

## CONSUMER SWEEP RUN (Aug 13 — full report `.build/scratch/sweep219/RESULTS.md`)

1900 files parsed, 358 generic decls, 24 Copy-family bounds (zero outside
std+examples), 271 generic references at non-Copy type args, 23 retain-hook
`copy()` bodies (not the 3 assumed — 21 are test fixtures), the rename
inventory counted (180 py / 156 saw / 88 doc mentions). Part 2d's
compat-sensitive set (Copy-bounded generics instantiated at ExplicitCopy) is
EMPTY in-tree. ~80% of the migration is mech-shaped. NEW FINDINGS
(lead-verified):
- **DF-217q — the `.copy()`-needs-a-bound gate covers only a BARE-`T`
  receiver.** `dup<T>(p: (T, Int)) { p.copy() }` compiles unbounded and
  double-frees at NoCopy (p9; live corpus instance df151i_tuple_copy.saw:205).
  The declared-`ExplicitCopy` rule must quantify over wrapper receivers —
  an obligation-1 position matrix ((T,Int), T?, [T;N], Vector<T>).
- **DF-217r — compiler-INSERTED `copy()` calls are invisible to the effect
  and alloc gates.** A suspending `copy()` runs inside a `sync`-DECLARED
  function (p13: three inserted calls, each `yield_now()`, no diagnostic —
  the sync guarantee is violated by code no source construct names), and an
  allocating `copy()` passes `--no-hidden-alloc` (p11). The retain-hook
  contract currently has NO mechanical enforcement anywhere; minimum fix:
  inserted calls join the effect census (a non-`sync` copy() on a Copy
  conformance should be refused at the CONFORMANCE), and the 135 gate learns
  the inserted-call category.
- **DF-217i EXTENDED:** the unbounded field-getter (`func get(&self) -> T
  { self.value }`) double-frees at NoCopy (p1) — a field-read position the
  bind-twice pin does not cover — and silently bitwise-copies at
  ExplicitCopy (p2).

**THREE JUDGMENT SITES BLOCK DISPATCH (rulings owed):**
1. **std's raw-pointer move idiom — RULED (user, Aug 13), two clauses.**
   Background: the concrete checkpoint judges `ptr[0] = v` and
   `let x = ptr[0]` as COPIES (refusing NoCopy; and there is NO move-out
   spelling for a pointer read — `move ptr[0]` is refused as a partial
   move, p7), while codegen already lowers them as moves (p5: one deinit).
   std's `pop`/`recv`/`join`/`swap` reads compile TODAY only because
   generic bodies are unchecked (DF-217i). The ruling:
   (a) **Pointer places are OWNERSHIP-NEUTRAL to the tier judgment and the
   inference** — the compiler stops asking a question the pointer erased
   the answer to; the exactly-once obligations belong to the design-130
   manual domain the enclosing `unsafe` declarations already mark.
   (b) **Non-Copy transfers through a pointer place must SPELL `move`,
   reads and stores alike** (user amendment): `let x = move buf[i]`
   becomes legal (a carve-out from the partial-move refusal SCOPED to
   UnsafePointer-rooted places — design 35 stays intact for safe places)
   and REQUIRED for owning-type value reads, with a fixit. This is
   declared intent enforced as a spelling rule, not a liveness proof —
   the same contract depth as `unsafe` itself; it restores read/store
   symmetry (stores already spell it) and makes `move <ptr-place>` the
   greppable census of manual transfer points the 218 review discipline
   wants. Census item for the implementer: verify each of the ~12 std
   pointer-read sites is a transfer (a value-read "peek" of an owning
   type would be DF-132a by definition — expect unanimous); std bodies
   then gain the `move` spelling in the same unit.
   **THE PLACE FRAMING (user, Aug 13 — how (b) is implemented and taught).**
   `ptr[i]` already IS a place in the checker's model (the copy-tier
   refusal on its value read is the place rule firing; the store is a
   place store). What blocks move-out is design 35 — and 35's real key is
   OCCUPANCY TRACKING: moving out of a place the language tracks leaves a
   hole its deinit would drop again, so every safe move-out is an
   occupancy-maintaining operation. Pointer places track nothing — that is
   what the manual domain means — so there is no invariant for a move-out
   to corrupt. Implement the carve-out IN THE PLACE MACHINERY, keyed on
   the root's kind (`TypeKind.POINTER` root → the design-35 refusal does
   not apply; the `move` spelling declares the transfer) — never as an
   expression-level special case. The move-out FAMILY, for the spec:
   `Optional.take` (tag keeps occupancy true), `Vector.swap_out` (the
   replacement does), `Slot.take` (the tag), `move ptr[i]` (the AUTHOR
   does, inside `unsafe`-declared code). Spec sentence: "every move out
   of a place either maintains its occupancy or happens where no
   occupancy is tracked — and the second kind is spelled `move` inside
   `unsafe` code."
2. **Design 146 vs 219 — RULED (user, Aug 13): 146 yields. Copy ≠
   ExplicitCopy at every silent position.** `_COPY_PROVING_BOUNDS` becomes
   the merged `Copy` alone: a silent place value read in a generic body is
   licensed only by the silent tier; an `ExplicitCopy` bound licenses only
   SPELLED `.copy()`. Container copyability at ceremony-tier elements is
   expressed where it belongs — as the CONTAINER'S OWN conformance: e.g.
   `Vector<T: ExplicitCopy>: ExplicitCopy`, whose body spells
   `buf[i].copy()` (which std's existing `Vector<T: Copy>: ExplicitCopy`
   conformance already does — its bound migrates class-(b) and
   `Vector<Vector<Int>>.copy()` keeps working, spelled at the call site).
   What retires is only the silent admission. Sequencing constraint
   stands: design 216's `&T`-closure rework lands WITH or BEFORE
   enforcement, so iteration at non-Copy elements moves to the borrow
   path (p8's `.each` shape) instead of breaking.
3. **The wrapper-receiver matrix — RATIFIED (user, Aug 13).** DF-217q's
   fix: the `.copy()`-needs-a-bound gate becomes ONE funnel computing the
   requirement recursively over composite receivers — `(T, Int)`, `T?`,
   `[T; N]`, `Vector<T>`, nested combinations — with p9's probe shapes as
   the obligation-1 row matrix its tests cover.

**THE DF-217r SYNC RULE — RATIFIED (user, Aug 13):** a `copy()` method on a
Copy conformance (declared or the retain-hook form) MUST be `sync`, checked
ONCE at the conformance declaration — refusing a suspending copy() where it
is declared, not where it is invisibly invoked. This is the mechanical half
of the declare-and-document contract: with it, compiler-inserted copy()
calls cannot violate a `sync` guarantee regardless of insertion site (p13's
hole closes at the root). The allocation half stays documentation +
optionally `-W` (the census row stands). Conformance row owed (obligation
3): a suspending copy() on a declared Copy conformance is refused with an
error naming the rule.
Secondary (implementer-note tier): `Map._find`'s unwritten key bound gets
written (`K: Copy` merged); the eleven `infer_overload*` test sites use the
bound as an overload DISCRIMINATOR and are updated as tests, not migrated.
Known false-positive class for unit 2: branch-exclusive double use
(`if a < b { b } else { a }`) — the inference must be flow-sensitive or it
over-tightens three corpus sites (named in the report).

Sequencing: before or with design 218 stages 1-2 (it is their gate); unit 3
also discharges 218's DF-217j dependency (the `Slot<TaskGroup>` refusal
becomes compiler-enforced).

## WAVE C LANDED (Aug 14) — the DF-217i fix

Requirement inference, call-site discharge, the two per-instance declaration
derivations and the public-declaration rule, in four commits on one worktree
branch, full suite green at each. Suite 1794/31 -> 1813/27: fourteen new
conformance rows, five pins flipped (DF-217i, DF-217j, DF-217k, DF-217q and
C07/DF-216b's seventh position).

- **C1** — the model, SIMPLER than the brief anticipated. Two rungs computed
  once at the definition (`move` / `copy`), discharged at each call against the
  argument's derived tier. **The move checker IS the inference**: an
  abstract-tier transfer of a whole owned binding marks it moved PROVISIONALLY,
  and design 15's dataflow — which has had branch merges, loop-carried
  detection and per-binding identity since it was written — decides. Nothing
  uses the binding again, it was a move; something does, it was a duplicate.
  That is why branch-exclusive use stays move-only without the new code knowing
  what an `if` is, and it is why the named false-positive class needed no
  special handling. A name-COUNTING rule was never viable. A PROJECTION read
  never gets the benefit of the doubt (no partial move exists), which is what
  catches the field getter the sweep added as DF-217i EXTENDED — a shape that
  mentions nothing twice.
  Four entry points, all pre-existing chokepoints; discharge is one funnel,
  DEFERRED to finalize because declaration order is not call order and because
  a requirement PROPAGATES (a fixpoint — S1 row 10's six deinits).
  The generic path also gained the RETURN transfer check it never had.
- **C2** — DF-217q's funnel, gated on the ABSTRACT tier, which is true exactly
  when the answer depends on the type argument. The recursive parameter walk
  covers the ratified matrix by construction. It found a second hole while its
  accept side was being written: the ARRAY arm's predicate is not bounds-aware,
  so `[T; 2]` under a declared `<T: ExplicitCopy>` was refused.
- **C3** — the two derivations. NoMove containment now derives per instance,
  through the same member-substitution the structural tier derivation uses; the
  DECLARED cascade stays the rule wherever a declaration site exists, and a
  generic container has none (`Wrap<T>` cannot say `NoMove` without pinning
  `Wrap<Int>`). Design 130's signature rule rides the discharge sites unchanged
  — it needs exactly the (callee, type arguments) pair C1 already collects.
  **This discharges design 218's DF-217j enforcement dependency:
  `Slot<TaskGroup>` is a compile error.**
- **C4 — the delegated ruling taken as HARD-REQUIRE**, and extended to `public`
  METHODS (design 80 makes members private-by-default, so the keyword is a
  deliberate publication). THE PUBLIC-GENERIC FIX LIST IS EMPTY: zero sites in
  `examples/` or std were newly refused, and the reason is structural — the
  public generic idiom is forwarding, and forwarding moves. What the rule DID
  find was a false positive of C1's own, live and invisible until a rule strong
  enough to error reached the position: the tail-expression transfer check runs
  after the body scope is popped, so std's `let result = body(...)` / `result`
  looked like a read out of storage it does not own. A warning would have
  printed that into the noise floor and std would have carried a wrong bound.
- **C5** — the Sync forcing row: NO FINDING. `Arc`'s `Send` derivation is
  conditioned on `T: Send + Sync` together, so a non-Sync payload makes the Arc
  non-Send and the MT frame gate refuses it; the generic twin is refused earlier
  by the concrete-type-arguments gate. The diagnostic says "not `Send`" where
  the fact is "not `Sync`" — recorded in row K31 as a wording paper-cut.
- **C07 CLOSED**, on C1's funnel rather than at `&Self`. The 216b stopgap's
  objection was that judging the type argument meant six bound-check sites
  rather than one funnel; wave C built the funnel, so the comparison rule became
  a SECOND requirement axis on the same table, discharged by running DF-216b's
  existing transitive walk on the concrete argument. The tier condition is
  untouched, so `@synthesize`d conformers and `Map`'s Copy-gated keys still
  pass. Row C12 stays open — it is a question about that tier condition, not
  about where the type is known.

Carried forward: the public-declaration rule is written for free functions and
`public` methods; an extension's OWN type parameters are judged when the
extension is, and a generic STRUCT's published surface is not separately gated.

## WAVE B LANDED (Aug 13)

The tier collapse and the vocabulary, in five units on one worktree branch,
full suite green at every commit. Wave C (requirement inference, call-site
discharge, declaration-derivation, the public-declaration rule) is untouched.

- **B1** — design 216's closure rework: `&T` elements, no copy bound.
- **B2** — the collapse itself: `Copy` is the merged silently-copyable tier
  (trivial + retain families) and only that; bounds ask the TIER rather than a
  declared conformance, so `T: Copy` stops rejecting `Int` and the auto-tier
  `Bag { s: String }`, and stops admitting an `ExplicitCopy` argument (S1 row
  9d). `ExplicitCopy`'s tier dissolves into move-only.
- **B3** — the trait declarations, the effect-matching rule, the bounds.

**THE EFFECT-MATCHING RULE — RULED (wave B, B3), the answer 218a ruling 10
deferred here, and it covers `Arc` and `UnsafeRef` alike: a conformer may be
STRICTER in its effect slot than the requirement, never looser.** An
`unsafe`-marked `copy(&self) -> Self` therefore satisfies the plain
requirement. Two reasons, and they are the same reason from two directions:
design 130 forces `unsafe` onto any function whose signature or body names an
unsafe-typed value, so refusing the marker would make the trait unimplementable
by exactly the types that need it (`UnsafeRef` holds a pointer); and the marker
describes the BODY's domain, not the contract the caller relies on, so a
conformer carrying one promises everything the requirement asked and more. This
is why `Arc.copy()` has always compiled — `_check_trait_conformance`
(registration.py) fires only in the REVERSE direction, a safe conformer of an
`unsafe` requirement, which stays refused (conformance row U26). The `sync`
axis reads identically: wave A's rule demands the stricter effect (`sync`) at a
copy-policy conformance, and a conformer that is `sync` where the requirement
did not ask is always fine. `extension UnsafeRef<T>: ExplicitCopy` is the
landed instance.
- **B4** — the WORD. `trait ImplicitCopy` deleted from `builtin.saw`; 166
  occurrences across 86 tracked `.saw` files renamed, plus 151 in `sawc/`'s own
  prose and ~120 across the docs. `Copy` did NOT gain `: Deinit` — the
  supertrait was never the machinery, and every predicate that named the
  copy-policy traits now routes through one funnel
  (`Namespace.declares_copy_tier` / `names_copy_tier`). The retired spelling is
  refused rather than aliased, since the name is now free for user code, and
  every unknown-trait diagnostic teaches the rename through one table
  (`_retired_trait_hint`). Pinned by
  `examples/errors/implicitcopy_renamed_to_copy.saw`.
- **B5** — prefix `*`, the pointer place, spelled.

Two rules the collapse DELETED are now deleted from the docs as well, not just
the compiler: `ImplicitCopy`/`ExplicitCopy` mutual exclusivity (declaring both
is legal and redundant — `examples/copy_traits_both_declared_legal.saw`
replaced the error test), and `T: Copy` admitting `ExplicitCopy` arguments.

Carried forward to wave C, unchanged by B4: the brief's "declared conformance
is an ASSERTION (empty)" form still requires `@synthesize`, exactly as the
`ImplicitCopy` spelling did — design 128's derivation gate is untouched here,
and relaxing it is declaration-derivation work.

# Design 219 — generic tier requirements: inference, discharge, and the DF-217i ruling

**Status: DIRECTION RULED (user, Aug 13 2026); brief authored same day; owes
its obligation-2 consumer sweep before dispatch. This IS the DF-217i fix
direction, and it gates design 218 stages 1-2.**

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

Obligation-2 consumer sweep BEFORE dispatch: every unbounded generic in the
corpus that would now infer above move-only (grep + compile census; S1's
evidence says std reads through Copy bounds already, but the sweep is the
proof), plus the `ImplicitCopy`-bound semantic change.

Sequencing: before or with design 218 stages 1-2 (it is their gate); unit 3
also discharges 218's DF-217j dependency (the `Slot<TaskGroup>` refusal
becomes compiler-enforced).

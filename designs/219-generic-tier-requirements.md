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

## The ruling

**Requirement inference on the copy lattice + call-site discharge rejection.**
The body is walked ONCE at definition time; per type parameter the compiler
computes the least upper bound of its demands:

| body does | inferred requirement | satisfied by (DERIVED tier) |
|---|---|---|
| only moves `x` (or never binds by value) | move-only (bottom) | every tier incl. NoCopy |
| spells `x.copy()` | needs-explicit-copy | ExplicitCopy, ImplicitCopy, trivial |
| silently re-binds / uses by value twice / place value-read | needs-implicit-copy | ImplicitCopy, trivial |

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
ImplicitCopy}; `T: Copy` = tier ∈ {trivial, ImplicitCopy, ExplicitCopy}
(unchanged in extension, now by derivation not declaration). Consumer-sweep
item: any overload resolution or conformance check whose outcome changes when
`Int`/auto-tier structs start satisfying `ImplicitCopy`.

## THE API-STABILITY CALLOUT (user, Aug 13 — named behavior + mitigation)

Pure inference means EDITING A BODY can silently TIGHTEN its requirement —
a maintainer adds a second bind, and downstream callers at ExplicitCopy/
NoCopy types break with no signature change. This is why Rust refused
inferred bounds; Saw's doctrine (infer what is determined) admits them, but
the hazard is real and is hereby CALLED OUT as the design's known trade.

**The mitigation: the writer binds the parameter — `<T: ImplicitCopy>` (or
`T: Copy`) — and the declaration becomes the contract.** Where a bound is
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

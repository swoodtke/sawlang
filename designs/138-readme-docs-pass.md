# Design 138 — the ALL-SOURCES docs consistency sweep

STATUS: APPROVED (user, Aug 5; SCOPE EXPANDED Aug 5 to every doc source).
Sequenced after 149 lands (user: docs sweep last, over the settled tree);
may run CONCURRENT with the parked-branch M1 adoption pass (disjoint
trees). Docs-only on main.

## Problem
Four documentation sources — LANGUAGE_SPEC.md, the saw-lang skill,
CLAUDE.md's orientation digest, and README.md — have each been edited by
a dozen-plus agents in ~48 hours. Each edit is locally fine; the likeliest
doc bug is now DRIFT BETWEEN SOURCES: a claim stated three ways, stale
sentences a later design falsified, terminology that diverged mid-week.

## Scope rule [user]
ALL FOUR sources are swept for CONSISTENCY and ACCURACY — every claim
true against current main, every feature described compatibly wherever it
appears, one terminology throughout (the Copy tiers, places/lend/window,
the unsafe model's terms, @synthesize, backed enums, the effect-slot
order). Each source KEEPS ITS OWN REGISTER: the spec stays authoritative
reference prose; the skill stays dense working-digest; CLAUDE.md stays a
lead-facing orientation digest (accuracy pass only — it is NOT a feature
list per the docs convention); **only README.md gets the saw-docs VOICE
pass** (de-LLM'd prose, audience structure, compiling examples).

## The work
LOAD THE saw-docs SKILL FIRST — it is the style contract for this brief;
apply its de-LLM'd prose rules and terminology/voice conventions
throughout. Then one structural+line pass over README.md:

- **Audience order.** The reader is deciding whether to pick Saw; the
  kernels/embedded-first positioning leads, with the safety/ergonomics
  story ("Rust safety + Swift ergonomics, no lifetimes, deterministic
  destruction") carried by SHOWN examples rather than adjective stacks.
- **One voice.** Merge the seven agents' appended sections into the
  document's structure (a feature belongs in its section, not in
  arrival order); kill duplicated claims; normalize terminology to the
  saw-lang/saw-docs vocabulary (e.g. one spelling for suspending/
  colorless, the Copy-family names, `@synthesize`, the unsafe model's
  terms as 130/136 define them).
- **Claims stay true.** The claims review burned us once; every claim the
  pass keeps or rewrites must hold on current main — where the tracker
  shows a bound (e.g. the op-budget's four bounds, design 127), the README
  claim carries the honest clause it already gained, in fewer words.
- **Every code example compiles.** Extract each README example to
  `.build/scratch/` and compile it against main; fix or replace any that
  do not (the newline-in-brackets rule and effect-slot spelling may have
  changed how examples should read). Examples use current idiomatic
  spellings (slot-position `unsafe`, `@synthesize`, `try_` twins,
  wrapped signatures where they help).
- **CLI/stdlib surface lists** stay in sync with `sawc.py --help` and the
  actual std modules (125 fixed these once; verify they are still exact).
- Length discipline: the pass should SHRINK the file or hold it flat —
  additions need a removal elsewhere.

## The cross-source method (added with the scope expansion)
Work claim-by-claim, not file-by-file: for each feature landed since 121,
find its statement in all four sources, verify against code/tests, and
reconcile — the spec's formulation is authoritative when sources disagree
and the code confirms it. Kill stale sentences (e.g. claims 133/146/147
have since made true or false), duplicated explanations that can point at
the spec instead, and README claims 125's lesson applies to (every kept
claim verifiable). Doc comments in std stay out of scope. If a claim is
wrong because the CODE is wrong, do not "fix" the doc to match the bug —
file a tracker line and keep the doc stating the intended truth with a
reference.

## Exit criteria
README reads in one voice end to end per saw-docs; all examples verified
compiling (list them in the commit message); no stale claims vs the
tracker; full suite still green (docs-only, but the gate battery runs per
policy — examples extracted as scratch, not committed tests).

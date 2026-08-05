# Design 138 — README cleanup pass (saw-docs voice)

STATUS: APPROVED (user, Aug 5). Sequenced LAST (after 135): every brief in
the current queue appends README content (133 mutex examples, 137 kernel
logging, 135 the flag); this pass sweeps once over the settled text.
Docs-only.

## Problem
README.md has accumulated feature updates from seven different agents in
~24 hours (125's catch-up, then 123/124/127/128/129/130 + the queue's
additions). Each edit is locally fine; the document as a whole has drifted
in voice, density, and structure — and it is the single most
audience-facing file in the repo.

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

## Explicitly out of scope
LANGUAGE_SPEC.md prose (its own sweep, another day); the saw-lang skill;
doc comments in std. If the pass finds a WRONG claim rooted in spec or
code, fix the README to the truth and file a tracker line for the source.

## Exit criteria
README reads in one voice end to end per saw-docs; all examples verified
compiling (list them in the commit message); no stale claims vs the
tracker; full suite still green (docs-only, but the gate battery runs per
policy — examples extracted as scratch, not committed tests).

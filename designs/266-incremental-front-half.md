# Design 266 — the incremental front half: an instance body belongs to the PROGRAM

**Status:** SCHEDULED Sep 4 2026 (user: "schedule DF-292c + DF-295a
one-design" — the go the tracker was holding for). Authored by the lead from
the two entries' fix-shape notes; both are consequences of one fact and this
design changes that fact. Closes DF-292c and DF-295a. Typechecker/driver
surface — serial with every typechecker brief; dispatches after design 207
integrates.

## The fact being changed

Today the front half (check + monomorphize) runs TWICE per driven compile:
the coroutine transform demands new instances, and the driver's answer
(`_prepare_codegen`'s two re-entry sites) is to run the whole front half
again and throw the first run away. Everything both findings measured is
downstream of that:

- **DF-292c**: the second pass cannot reuse the first pass's instances. The
  three-legged pincer (all live, all measured): a checked body RE-CHECKED
  double-wraps (`ResultOkWrap` ICE in std/channel.saw); carried UNCHECKED it
  has no effect node in pass 2's TypeChecker (DF-258a again); UN-checked
  first, the wraps cannot be peeled on the post-transform tree (DF-292a's
  ICE, same file). An instance body is a PASS's artifact — so nothing cached
  across passes can land. The prize measured before the revert: re-run copier
  calls 339 -> 16, re-run wall 0.772 -> 0.204 s, **-74%**; ~0.6 s of
  `substituting_copy` per driven compile is the standing cost.
- **DF-295a**: the effect edge out of a driven body names the TEMPLATE,
  because it was recorded at body-check time before any instance existed. A
  second pass re-records the same template edge; that is why census rows
  C1-C4 could only stop BUILDING (stage 4) and why T5's poly-candidate
  machinery and `_process_effect_monos`'s shell cannot delete — neutralize
  T5 and `sync_generic_instantiation_suspends` COMPILES (the design-70
  both-ways refusal lost, probed Sep 3).

**The design: there is no second pass.** The transform's synthesized
declarations are checked and monomorphized INTO the settled program —
admitted incrementally through one funnel — so instances exist before the
effect graph settles and every per-pass artifact question dissolves. 218
stage 4a's re-entrant, monotone `finalize_effects` (the 3-entry funnel) is
the piece that already exists and the seam to build on.

## What this rests on (the evidence base, not restated)

DF-292c's entry: the sweep proving both passes converge structurally (18,756
shared bodies, 0.95% differing only in `resolved_type` stamps — the rewrite
hazard is self-cancelling), the cost split (79% copy / 13% check), the
key-may-not-use-`node_id` lesson (mangler-read discriminators are the
pass-stable identity, DF-289c's), and the thread-not-global rule (`reemit`
compiles twice in one process). DF-295a's entry: the edge inventory, the C1
adoption that already landed, and the T5 neutralization probe that is this
design's sharpest acceptance test. Both entries move to the done file at
integration; the brief cites, the entries carry the evidence.

## Units

**U0 — the contract census + the acceptance matrix, before any change.**
- Instrument the current re-entry on the driven corpus (the DF-292c sweep
  tooling is the model): what does pass 2 GENUINELY add? (The cache probe
  said 16 of 339 copier calls; name them — transform-synthesized frames,
  resume methods, the demands their bodies make.)
- Inventory the effect edges that name templates today and the consumers
  that walk them (the driven closure, `_process_effect_monos`'s drains,
  T5's recorder sites) — this is the obligation-1 position matrix for U2.
- Freeze the acceptance matrix: (a) the design-70 both-ways case and its
  family (`-f generic,coro,place,poly` is the subset the Sep-3 probe used);
  (b) the never-silently-block guarantee rows — check
  examples/conformance/INDEX.md for the design-96/101/104 rows and update
  FIRST if any row's covering test touches the machinery (obligation 3);
  (c) driven-compile wall time on `coro_generic_driven_both.saw` (0.772 s
  re-run baseline) and suite CPU.

**U1 — the admission funnel.** ONE entry point (working name
`admit_declarations`) through which post-transform synthesized declarations
join the settled program: appended to the entry AST, checked by the SAME
TypeChecker (no fresh pass-2 instance), their generic demands monomorphized
into the existing registry/splice state, `finalize_effects` re-entered per
admission batch (it is monotone; that is what 218 stage 4a bought). The
docstring NAMES its callers (obligation 1). `_prepare_codegen`'s two
re-entry sites route through it; the whole-front-half re-run is deleted.
DEVELOPMENT SHADOW (the SAWC_MONO_SHADOW precedent, retired before the
terminal battery): an env-gated dual-run that also executes the old second
pass and diffs instance keys + effect conclusions across the driven corpus —
the 0.95%-structural-agreement sweep says the diff should be empty modulo
the known `resolved_type` stamps.

**U2 — effect edges name INSTANCES.** Recording moves to monomorphization
time: an edge out of a driven body targets the instance key, not the
template (the mangler-read discriminators are the identity — DF-289c,
DF-292c's lesson). The template-edge consumers from U0's matrix convert or
retire. THE REFUSAL IS THE TEST: `sync_generic_instantiation_suspends` must
still refuse with T5's machinery GONE — that is the probe that proved the
edge, not the node, is the problem. Both-ways instantiation (`run<Slow>`
suspends, `run<Fast>` does not) stays the key case.

**U3 — the deletions the design buys.** C1-C4's residual walks, T5's
poly-candidate deferral + four recorder sites, `_process_effect_monos`'s
shell (and its gsm loop, C3's input). Each deletion cites its census row;
the 218c spec's §7 ledger gets a dated amendment noting stage 5's rows
completed by this design (edit the spec's ledger, not the done files).

**U4 — measurement + the ledger.** Driven-compile wall before/after on the
U0 baseline; suite CPU delta; the -0.6 s prize confirmed or the miss
explained. `irdet --all` and `reemit` are per-compiler-commit gates here,
not just terminal — this design changes WHAT ORDER instances materialize
in, and whole-corpus determinism is the standing risk (design 141's
lesson). The thread-not-global rule holds: no module-global admission
state (`reemit` compiles twice in one process).

## Consumer sweep (obligation 2, lead, from the entries' own sweeps)

The behavioral contract is "one front half, incrementally extended" replacing
"two passes". Who relies on two passes: the pristine-capture timing (DF-292b
parked `resolved_type` for the snapshot's deepcopy — re-verify its window),
the C1 adoption's append-to-entry-AST assumption (it becomes the funnel's
job), SAWC-side env probes retired at 218/1.5 (SAWC_MONO_SHADOW is already
gone; the U1 shadow is new and also retired before landing), and the
`--emit-ids`/debug dumps that print per-pass state (verify they still mean
something). The DF-292c sweep already proved the two passes CONVERGE, which
is what makes single-pass semantics defensible: the program being settled
into is the one pass 2 would have rebuilt.

## Gates, sequencing, conduct

- Per-commit: full suite + freestanding + `irdet --all` + `reemit`.
  Terminal: FULL battery. Suite-lock split form.
- Staging is explicitly allowed: U1 may land with the shadow compare active
  in development and the old path deleted only after U2's matrix is green —
  but the SHADOW DOES NOT SHIP (retired before the terminal battery, like
  SAWC_MONO_SHADOW).
- A leg that cannot be made green STOPS and files with the probe — this
  design's whole evidence base is three attempted-and-reverted legs; a
  fourth reverted leg with its mechanism named is a successful unit.
- DF range at dispatch: lead assigns. Closes DF-292c + DF-295a in place.
  Version: compile-time only, no user-visible surface — no bump unless a
  diagnostic's position/wording changes user-visibly (examined at
  integration).

# Design 190 — the quality program: analysis and the four-brief plan

## CORRECTIONS (Aug 10 — read before citing this analysis)

The 191-194 builds falsified three of this document's claims. The
briefs still landed as designed because each agent probed before
building, which is the pattern worth keeping: this analysis's
PROBE-CONFIRMED claims all held, and all three failures were
GREP-SHAPED claims — read from code without a probe. Probe before
citing.

1. **DF-190b's diagnosis was wrong.** Not the coro spine walks skipping
   `TryCatchExpr`: a LABELED call (`compute(ok: true)`) parses as
   `StructInit` and is invisible to the transform's
   `isinstance(FunctionCall)` classifiers — the unlabeled shape inside
   the same `try/catch` compiled all along. Fixed in 193 u2. The
   try/catch-BLOCK half is a real, separate gap: DF-193a, ruling
   pending.
2. **The spawn capture-MODE gap is masked by design 16/29** (escaping
   closures cannot borrow-capture), not by "closures are never Send"
   (§ unit 6 below). Established by 193 u6's probe.
3. **The graft-straggler census was wrong in both directions**: three
   of the nine cited are declared fields of `SuspendNode` (a plain
   dataclass, not an AST node — the grep could not tell), and five real
   grafts were missed. Superseded by 194 u1's mechanized gate
   (`tools/test_ast_graft.py`), which is now the authority.

**Status: ANALYSIS COMPLETE (Aug 9), briefs 191-194 authored from it; the
process half (brief-template obligations) lands with this document. Source
data: the Aug-8 external review + safety audit, the findings ledger of
Aug 7-9 (~32 DFs), and three code censuses run Aug 9 (position-quantified
rules; ICE/contract debt; audit-promotion mechanics). Two census claims
were probe-CONFIRMED before filing (DF-190a, DF-190b below). The metric
throughout is LATENCY: the same bug caught at design review > at
introduction > at next build > on the user's machine.**

## The findings-vs-proposals matrix (Aug 7-9, ~32 findings)

By failure family: **position-incompleteness 14** (a rule enforced at k of
n grammar positions: DF-188a/b/f/j/k, DF-184a/c, DF-158a/b/d, DF-182a/b/d,
DF-186b, DF-187c...), **spec-gaps 5** (documented-unimplemented: DF-188g/h,
DF-188d, DF-182e...), **soundness holes 6** (silent UAF / lost write /
double-free: DF-188c-i, DF-189a-c, DF-186d, DF-184c), **invariant flips 3**
(feature A removed what B relied on: DF-182f the fork-bomb, DF-158e,
DF-184b), **traversal drift** (DF-187b's twelve disagreeing walks),
**doc drift 2** (DF-188i, DF-158c), **duplication 1** (DF-185a).

By what ACTUALLY caught them: agents-tripping-while-building 13, the
one-off audit 9, lead probes 4, gates (irdet/llvmlite/pin oracles) 4, the
user's machine 1 (the fork-bomb — the worst possible detector). Purpose-
built prevention caught almost nothing early because it mostly did not
exist. The two walk-the-doc drift tests that DO exist (prelude-gate,
abidoc) each police exactly their class — proof the pattern pays here.

By proposal (would-have-caught count → stage moved to):
- **Conformance suite (brief 191)**: 13 findings → caught at the landing
  of the offending design instead of days later.
- **Position matrix/funnel discipline (brief 193 + the process rules
  below)**: 14 findings → caught at DESIGN REVIEW, the earliest stage.
- **Fuzzer + diagnostics floor (brief 192)**: 9 ICE-faced findings →
  hours after introduction, continuously; DF-185a (hex enum literals
  crashing the parser) is the poster child.
- **Consumer sweep on contract flips (process rule)**: 3 findings incl.
  the fork-bomb → design time, at the cost of a grep and a paragraph.
- **gmgate concurrency sub-lane (brief 192)**: both confirmed silent
  UAFs (probes exiting 0) become instruction-level crashes.
- **Typed AST contract (brief 194)**: the DF-187b class; also de-risks
  the parser port.

## Census digests (full reports in the session record; citations verified)

**Positions census.** Of nine position-quantified rules: four are genuine
funnels (`_check_value_transfer` — 40 sites through one checkpoint;
`_check_call_exclusivity`; `_send_sync`; the unsafe-contact bracket) and
their residual gaps are all at positions that BYPASS the funnel entry.
The scattered rules are exactly the ones with 2-3 duplicate
implementations: the no-escape walk exists in THREE copies across parser
and typechecker with ~18 call sites; the std import gate covers 4
positions and misses every type-annotation position (DF-188k) — and the
natural funnel (`_resolve_type`) exists but needs a user-written-type
provenance bit; the const-eval NAME-stamping walk exists twice. New gaps
found by inspection, two probe-confirmed same day:
- **DF-190a (SOUNDNESS, CONFIRMED): match on an owned enum consumes it —
  and the checker never records the move.** Two sequential `match s` on
  one NoCopy enum compile silently and the payload deinits TWICE (probe:
  `deinit 7` printed twice, exit 0). Codegen marks the scrutinee moved
  (codegen/match.py); the typechecker binds payloads with no transfer
  checkpoint, no move-marking. Double-free class, trivially reachable.
  PIN: `examples/match_owned_enum_double_consume.saw`.
- **DF-190b (CAPABILITY + DIAGNOSTIC, CONFIRMED): a suspending callee
  inside `try ... catch` in a task body is rejected with a NONSENSE
  error** (``undefined struct `compute` `` — the DF-184a face); the
  identical sync shape compiles and runs. Root per the census: the coro
  spine walks do not descend TryCatchExpr (only `_uniq_walk` does). PIN:
  `examples/coro_try_catch_suspending.saw`.
- Also inspection-found, filed inside brief 193's units rather than as
  separate DFs: four tuple-holed hand walks alive after DF-187b (two of
  them exclusivity/place-legality: place_uses `_mentions_move` /
  `_escapes_control_flow` / `uncheck`, and the chain-assign exclusivity
  walk skipping tuple fields — `p?.f = Foo(a: move x)` invisible to the
  Law); exclusivity satellites (existential/type-param method calls
  never join an access set; plain-assign RHS unchecked while the chain
  spelling of the same statement IS); no-escape misses `static`,
  associated-type RHS, and generic-param DEFAULTS (the DF-163d shape by
  another route); `spawn {}` result and capture-mode Send gaps masked
  only by closures-never-Send; unsafe-contact misses bind-and-never-use
  pattern bindings and default-arg ordering; six trait/receiver
  positions bypass parse_type with six independent qualified-name
  parsers.

**ICE/contract census.** 94 bare `raise ValueError` in codegen (+3
other generics), all funnelling to sawc.py's catch-all that prints
`internal compiler error` with NO location; the TYPECHECKER IS ENTIRELY
UNWRAPPED (raw Python tracebacks). The two typechecker dispatch
fallthroughs silently skip unknown nodes where codegen raises. Both
codegen dispatches are single chokepoints and every node carries
line/column, so fallthroughs-raise + a current-node breadcrumb + a
typechecker wrapper is ~50 lines total. Design 126 already declared
79/89 stamped attributes as annotation fields; NINE grafted stragglers
crept back with no gate policing 126's own "zero grafts" exit
criterion. Duplicated must-agree logic: `_pointer_size_bits` identical
twice (comment admits it); `_pattern_binding_names` in THREE divergent
variants; **DF-190c (VERIFY, latent): `_make_specialization_key` HAS
diverged** — codegen's handles design-148 const-value args, the
typechecker's drops them to an empty key; needs a probe for whether a
const-generic specialization ever keys through the typechecker copy.

**Audit-promotion census.** 298 probes in gitignored scratch; ~60-70% of
rows already covered by this week's pins + pre-existing tests, ~50-60
trivially portable (the audit's results.json holds each row's actual
error line, so content assertions are scriptable), ~25-35 need rework
(expectations superseded by the 186-189 RULINGS, the 30 accept-mode
probes, three helper modules to relocate). test_runner needs ZERO code
changes (recursive discovery, {TESTDIR} modules, XFAIL policy all fit);
battery cost ~+10s. One optional nicety: an `EXPECT: compiles` mode.

## The four briefs, with expected payoffs

| brief | scope | cost | payoff (historical evidence) |
|---|---|---|---|
| 191 conformance suite | promote the audit to examples/conformance/, rulings-refreshed; unit-zero rows obligation | 1-2 sessions, ~+10s battery | 13/32 findings move to landing-time; the audit's 9-in-one-pass becomes every-pass |
| 192 diagnostics floor + oracles | fallthroughs raise, breadcrumb, typechecker wrapper; corpus-mutation fuzzer (traceback oracle); gmgate concurrency sub-lane | small + medium | 9 ICE-faced findings → hours; 2 silent UAF classes → loud; ends raw-traceback ICEs |
| 193 checker funnels | DF-190a/b first, then the census's ranked gap list: tuple-holed walks + shared child-walk module, exclusivity satellites, no-escape consolidation + position table, Send helper + spawn gaps, unsafe intake, std gate through _resolve_type | the big one — per-unit small/medium, ~189-sized total | 14 position findings' family gets funnels + matrices; closes 1 confirmed double-free + 1 capability gap + 4 live walk holes |
| 194 contract debt | declare the 9 stragglers + graft GATE (126's exit criterion, mechanized); DF-190c probe + spec-key dedup; pointer-size + pattern-binding dedup; staged getattr→field | small + small-medium + medium | the DF-187b class structurally; one latent must-agree bug; Pyright moves toward signal; de-risks the parser port |

Queue recommendation: 193 first (it closes confirmed soundness holes),
then 191 ∥ 192 (disjoint surfaces: test corpus vs sawc.py/tools), then
194. All four are parallel-safe with respect to each other EXCEPT 193/194
(both touch typechecker internals — keep serial).

## The process changes (land with this document, no dispatch)

Added to CLAUDE.md's design-brief workflow, binding on every future brief:
1. **Position rule ⇒ funnel or matrix.** A brief introducing or touching
   a rule that quantifies over "every position where X appears" either
   routes it through ONE chokepoint (and the funnel's docstring NAMES its
   entry points — the census shows funnels with named entries kept their
   gaps at the perimeter, scattered rules grew duplicates), or carries an
   explicit position matrix its tests cover row by row.
2. **Contract flip ⇒ consumer sweep.** A brief changing a BEHAVIORAL
   contract (blocking→cooperative, by-value→by-pointer, eager→lazy,
   flag semantics) owes a "who relies on the old behavior" survey —
   grep + one paragraph — before dispatch. (The fork-bomb rule.)
3. **Safety surface ⇒ conformance rows first.** A brief touching a
   safety guarantee adds/updates its examples/conformance/ rows as its
   FIRST unit (once 191 lands).

## Explicitly out

A Rust rewrite (standing decision — fix in place, self-host later); a
full property-based testing framework (the mutation fuzzer is the v1);
runner-integrated sanitizer modes beyond the gmgate lane (separate brief
if the lane pays); rewording all 94 ICE messages individually (obsoleted
by the breadcrumb).

# Design 270 — preserving the transfer decision through every lowering

**Unit C of SL-209** (the ownership-uniformity epic), filed as **SL-212**. Plan
step 5. Depends on units A (design 267, SL-210) and B (design 269, SL-211).

> **The number 270 is PROVISIONAL.** 269 was the highest brief when the branch
> opened; it is the lead's and the user's to confirm or renumber at
> integration.

## What this unit is for

Unit A recorded an explicit `TransferDecision` per transfer occurrence. Unit B
made the producer question total, so the decision is now made at every boundary
rather than at the ones a node-type list happened to cover. Both of those are
facts about **the tree the typechecker saw**.

Between that tree and the one codegen consumes, four passes rewrite bodies:
place lowering, generic specialization, closure conversion and the coroutine
transform. Unit D cannot delete codegen's second opinion
(`_transfer_needs_copy`) until the decision codegen would read is the decision
the checker made *about the code that is actually there*. So this unit answers
one question per pass — **does the decision survive, and if it does not, what
answers in its place?** — and turns the answer into a gate.

Design 267 stated the gap it was leaving:

> `deepcopy` gives a clone FRESH `node_id`s, so an instantiation's transfers are
> new occurrences with their own decisions rather than a template's reused.

That sentence is a *hope* about the monomorphizer, not a checked property, and
it says nothing at all about the coroutine transform. This unit measures both.

It is **behaviour-preserving**: the same programs compile, with the same
diagnostics and the same annotations. What changes is that a decision now says
what answers for it when it declines to answer itself, and a lane fails when a
lowering breaks the link.

## THE MEASUREMENT FIRST — what actually happens today

Every number below is from a compile of the stated fixture with the ledger read
back against a **structural** walk of the program handed to `run_codegen`. (A
walk over `__dict__` is wrong here and was the first thing that had to be fixed:
`resolved_symbol` back-pointers reach declarations that are not in the program
at all, so template bodies count as "live" and a monomorphized clone's stamps
look orphaned when they are not.)

Vocabulary used throughout:

* **live** — the decision's source `node_id` is a node of the final program.
* **orphan** — the decision's source node is not in the final program: some pass
  replaced or dropped it.
* **emitted body** — a `Function`/`Method` of the final program that is not a
  generic template (`is_mono_instance`, or no `type_params`).

### Pass 1 — generic specialization

`.build/scratch/c_generic_two.saw`: one template `hold<T>` with `let a = x` and
`let b = a`, instantiated at `Int` (trivial) and at a `Copy`-tier struct.
Decisions grouped by `(line, column, destination)`:

| Site | Template | Instance `hold$1$Int` | Instance `hold$1$Tag` |
|---|---|---|---|
| `4:5 let binding` | `deferred` tier=abstract pending=`('T',)` | `deferred` (§1c skip 4) | `deferred` (§1c skip 4) |
| `5:5 let binding` | `deferred` tier=abstract pending=`('T',)` | **`copy` tier=free** | **`copy` tier=implicit** |

**The mechanism is RE-DERIVATION, and it works.** `mono_copy.substituting_copy`
builds the clone with fresh `node_id`s, `materialize_instance` then runs
`_check_function` / `_check_method` over it, and the checkpoint files a decision
against the clone's own nodes. Row `5:5` is the proof: one template decision
that could not answer, two instance decisions that do, and they *differ from
each other* — `tier=free` for `Int`, `tier=implicit` for the struct. A carried
decision could not have produced two answers, and a reused one would have
carried the template's `SawType`s into a body where they are wrong.

So unit C does **not** carry keys across the specialization boundary, and the
brief records why rather than leaving it implied:

> A decision holds the tier, the source type and the target type **of the body
> it was made in**. At a template those are abstract. Copying the record onto a
> clone is exactly SL-212's forbidden shape — "blindly reuse decisions tied to
> an abstract type or another instance" — and it is the same reason design 267
> put the ledger outside the AST in the first place. What unit C owes here is
> not transport. It is **proof that re-derivation happened**, per instance,
> which is a thing nothing checked.

### Pass 2 — closure conversion

Measured on `examples/coro_closure_*.saw` (six files) plus
`coro_cross_module_*`, `coro_channel_*`, `coro_conditional_*`: every
`needs_copy`-stamped node in the final program carries a live decision, and
every one of those decisions says `copy`. Zero detachments across all twelve.

Closure conversion is not a separate AST pass: an ordinary closure's captures
are synthesized `Identifier`s that unit A already stamps with
`resolved_binding_id` inside `_check_closure`, and they reach the checkpoint at
entry point `closure capture` like any other source. The one place a capture is
genuinely *rebuilt* is inside the coroutine transform — the capture
materialization — and that is pass 4's second family, below.

### Pass 3 — place lowering

`transform_place_uses` runs before the coroutine transform, and the admission
re-runs it over the transform's own output (`admit_declarations` step 3), with
`uncheck_after=False`. Both runs are followed by a full re-check of the entry
module, so every place-lowered node is judged by the checkpoint afterwards.
Design 267 already named `place_uses._value_read_ok` as a **separate funnel**
that records no decision of its own; that remains true and remains unit B/E's,
not this unit's. What this unit adds is that the checkpoint's own `place_struct`
arm is now visible in the audit as a distinct source kind (`SOURCE_PLACE`), so
the two funnels' coverage can be differenced instead of argued.

### Pass 4 — the coroutine transform (the one with real holes)

`.build/scratch/c_driven_copy.saw`: a driven body with `Copy`-tier reads on both
sides of two suspensions. 75 decisions over 34 sites. The shape of the table is
the finding:

| Site | Decisions |
|---|---|
| `10:5 let binding` | `copy`[**orphan**], `copy`[**orphan**] — and **no live decision at all** |
| `12:14 tuple element` | `copy`[orphan], `copy`[orphan], `take`[orphan], **`take`[live]** |
| `12:17 tuple element` | `copy`[orphan], `copy`[orphan], **`deferred`[live]** |
| `0:0` (26 decisions, 7 destinations) | synthesized frame/drive bodies, all live |

Three separate facts are in there.

**4a. The transform MOVES a transfer to a different site.** `10:5`'s pre-transform
decision is orphaned and the post-transform tree has nothing at `10:5`; the work
now happens in the `resume` method's synthesized `field assignment`s at `0:0`.
That is correct — the local became a frame field — and it is why a
site-keyed audit is not merely imprecise but **unsound**: 26 of this fixture's
75 decisions sit at `0:0`, where every synthesized node in the frame collides
with every other.

**4b. The transform CHANGES the action at a site it keeps.** `12:14` goes
`copy` (pre-transform: an aliasing read of a local) → `take` (post-transform: the
frame hands its own reference over through the paired `__saw_forget`). This is
the transform exercising its documented authority, and it is the single most
important thing for unit D to be able to see: the answer codegen must execute is
the *second* one, and today nothing says so.

**4c. A frame read DEFERS, and its antecedent is unfindable.** `12:17`'s live
decision is `deferred`, reason *"a coroutine-frame read: the transform's own
bookkeeping settled it on the pre-transform AST"* — and the settlement it names
is one of the two orphaned `copy` records at the same site, reachable by nothing
but a line/column coincidence that 4a has already shown is not a key.

#### The deferral census — the whole of what is unresolved

Across the driven fixture, the live `deferred` decisions fall into exactly four
families, and the split is stable across the corpus:

| Family | Count | Owner | Discharged by |
|---|---:|---|---|
| §1c skip 5 — a substituted RETURN | 219 | mono instance | design 219 wave C, at the call sites |
| §1c skip 4 — a substituted by-value PARAM | 43 | mono instance | design 219 wave C, at the call sites |
| the abstract tier (`pending=('T',)`) | 24 | generic **template** | the instance's own re-derivation (pass 1) |
| `frame_place_read` | 2 | transform-synthesized `resume` | **nothing nameable** — 4c |

The first three are sound and each has a real discharge; what they lack is a
*written* one, so an auditor cannot tell a discharged deferral from an
unjudged boundary — which is the exact distinction design 267 exists to make,
one level up. The fourth is the hole.

#### 4d. The second frame-read family: there is no antecedent to find

`_read_field` (`coro_transform.py:1248`) has nine call sites and they are two
different operations wearing one name:

* **REWRITES** — five sites in `_rewrite_expr` and the receiver path, each
  holding the pre-transform node it is replacing. An antecedent exists.
* **SYNTHESES** — four sites in `_materialize_closure_captures`
  (`coro_transform.py:7859/7868/7877/7884`), which build a read **that no
  pre-transform expression ever was**: the transform is materializing an
  implicit capture as an explicit `let`, choosing `.copy()` / a `move_read` /
  an `owning_read` by asking `_frame_read_policy`. There is no earlier decision
  because there was no earlier transfer.

So the honest statement of 4c is not "the link is missing"; it is **"one family
has a link nobody recorded, and the other has no link because the transform is
the author"**. Both are stamped `frame_place_read`, both take the same deferral
arm, and today they are indistinguishable in the ledger. Design 218 stage 1's
`Slot` migration is the standing plan that retires the legacy encodings (a
`Slot` field's `take()`/`value()` is an ordinary method call the re-check judges
by the ordinary rules and stamps nothing) — at which point both families become
ordinary decisions. Unit C does not accelerate that migration; it makes the
residue **named and counted** so unit D knows exactly which reads codegen still
answers for, and the count falls as the migration proceeds.

## What this unit builds

### 1. `origin_node_id` — provenance across a CLONE, and only there

A declared annotation on `ASTNode` (design 126 R1, so the `astgraft` lane is
satisfied and `substitute_ast_types` sees it), holding the `node_id` of the node
this node was copied from. Stamped in exactly two places, which are the two
producers of a cloned node:

* `mono_copy._copy_node` — the substituting copier, the one funnel every
  specialization splice goes through (its own docstring already names its four
  entry points);
* `ASTNode.__deepcopy__` — every other clone, including the coroutine
  transform's eleven `_copy.deepcopy` sites and the trait-default duplication.

A clone of a clone records the **root** of its chain, not its immediate parent,
and that was a correction the build forced rather than a choice: an instance
body is cloned from a PRISTINE SNAPSHOT of its template, and the snapshot is
itself a copy that nothing ever type-checks. Naming the immediate parent pointed
every instance decision at a node no decision exists for — **1 of 2175 links
resolved**. Naming the root took it to **1919 of 2235**, the rest being
declarations this compile never checked (std, on a cache hit).

`coro_transform._read_field` OVERWRITES the field with the pre-transform node it
replaces, which is a better antecedent still: a node in the checked tree, in the
same body.

This is NOT decision transport. The decision is still re-derived; `origin_node_id`
is what lets the funnel **check** that it was, and check that the re-derived
answer is a resolution of the template's rather than an unrelated one.

### 2. The decision says what answers for it

`TransferDecision` gains two fields, both filled at the arm that decides:

* `antecedent: Optional[int]` — the NODE this decision's source descends from,
  read straight off `origin_node_id`. A **node id and not a full key**, which
  the first cut got wrong: a key pins the boundary as well as the source, and
  the transform legitimately reuses an author's node at a boundary of its own
  making (a local the author bound at `let binding` is read again at the frame's
  `field assignment`). Keying on the descendant's own context asked for a
  decision at a boundary that never existed, and P4 fired on a third of the
  coroutine corpus for it. The question the field answers is "which occurrence
  did my source come from", and that is node-level.
* `discharge: Optional[str]` — for a `deferred` action ONLY, the named place the
  answer lives. The set is CLOSED, and the funnel rejects a `deferred` decision
  that is not in it:

| `discharge` | Meaning | Side condition the funnel checks |
|---|---|---|
| `tier-requirement:<instance>.<param>` | design 219 wave C | the discharge names the instance and the parameter |
| `specialization:<params>` | the template's abstract arm | the owner body is a TEMPLATE, never an emitted one |
| `coro-frame-rewrite` | 4c — the pre-transform tree judged it | the antecedent's own decisions include a real ANSWER |
| `coro-frame-synthesis` | 4d — the transform is the author | no antecedent is claimed |
| `payload-read` | design 131 owns the rule | — |

`ACTION_DEFERRED` therefore stops being a shrug. Every one of the checkpoint's
deferral arms already knows which of the five it is; they just were not saying.

**THE REWRITE/SYNTHESIS CHOICE IS MADE FROM THE LEDGER, NOT FROM THE CALLER'S
CLAIM.** `_read_field` cannot tell an author's node from scaffolding an earlier
transform stage minted — both arrive at the same builder — so a caller-supplied
`origin` is a claim that may be false, and it was: the first cut had P4 firing
on a transform-internal temp whose "antecedent" was never judged. The ledger
gained a node index (`transfer_node_was_judged`) and the arm now asks it, so the
record states what is true. That moves P4's teeth from "does the antecedent
exist" to the stronger **the deferral chain GROUNDS OUT**: the settlement a
rewrite names must be a real answer and not another hand-off, because a chain of
deferrals that never reaches a judgment leaves codegen with nothing to honour.

**AND THE CHANGED ACTION IS RECORDED** (the second of the three coro holes). A
node carrying any transform mark — `frame_place_read`, `frame_move_read`,
`frame_owning_read`, `frame_slot_op` — carries that fact into whatever arm
judges it, applied once in the local `decide` recorder so no arm can drop it.
The sharpest case is a `move` of a frame-resident local: the author's `move x`
was decided `move`, and the frame read replacing it is decided `take`, because
the frame hands its own reference over through the paired `__saw_forget`. Both
answers are right for their own tree; without the note the second reads as the
first one lost, and P3 reported it as exactly that until the note existed.

### 3. THE FUNNEL — `sawc/typechecker/preservation.py`

One verification pass, one entry point (`audit_preservation(program, ledger)`),
whose docstring NAMES the four passes it covers and what it asserts about each
(obligation 1). It reads only the final program and the ledger — no second
enumeration of the nineteen entry points, which is the duplicate-rule failure
mode obligation 1 exists to prevent.

The four properties:

* **P1 — STAMP/DECISION RECONCILIATION.** Every node of the final program
  carrying `needs_copy` or `payload_needs_copy` has a live decision, and a
  `needs_copy` node's decision says `copy`. This is the property that catches a
  clone inheriting a stamp without inheriting a judgment: `_copy_node` copies
  `__dict__` wholesale, so a `needs_copy` **does** ride onto every clone, and if
  a future change ever skipped the instance check the stamp would be there with
  nothing behind it. Measured today: 0 detachments over the whole probe corpus.
* **P2 — NO UNEXPLAINED DEFERRAL IN AN EMITTED BODY.** Every live `deferred`
  decision names a `discharge` from the closed set above and satisfies its side
  condition. In particular `specialization:` may not appear in an emitted body
  at all — that is "the instance reused the template's answer", stated as a
  check.
* **P3 — SPECIALIZATION RESOLVES.** For every decision in a mono-instance body
  whose node carries an `origin_node_id`, the antecedent decision is looked up;
  if the antecedent was `deferred`/abstract the descendant must NOT be, and if
  the antecedent was concrete the descendant's action must agree. This is the
  "prove which happened" requirement, discharged by oracle rather than by prose.
* **P1b — EVERY CLONED OCCURRENCE, not every cloned body.** A node carrying an
  `origin_node_id` whose origin WAS judged is an occurrence the front half was
  supposed to re-derive, so its own decision must exist. Driven by the NODES,
  which is what survives a deleted decision. Two exclusions, both measured: a
  transform-SYNTHESIZED declaration (inside a frame the transform is the
  authority, fenced by name through P2/P4) and an INTRA-BODY duplication (the
  transform copies a node it already holds, so origin and clone share a
  declaration, where `mono_copy` always crosses declarations).
* **P1r — THE LOWERING OBLIGATION, read from the ledger.** A decision records
  the annotation it OBSERVED (`lowering`); the audit checks it is still there.
  Per obligation and BY NAME, so the two stamps stay separable.
* **P5 — THE ORIGIN UNIVERSE IS NOT SHRINKABLE.** Every node of an instance
  body carries `origin_node_id`, bar the auto-wraps the instance check inserts.
* **P4 — THE DEFERRAL CHAIN GROUNDS OUT.** A `coro-frame-rewrite` deferral must
  name an antecedent, the ledger must hold it, and that antecedent's own
  decisions must include a real ANSWER rather than another hand-off. A chain of
  deferrals that never reaches a judgment is the same hole one level deeper.

**THE SCOPE RULE IS PER DECLARATION, AND ITS EXCEPTION IS LOAD-BEARING.** A
declaration is in scope when THIS ledger holds a decision inside it — std's own
bodies are checked under a separate builtin typechecker and pickled, so a
file-level rule pulled them in and reported 15 of 20 stamps as detached when
nothing was. But a per-declaration rule is self-defeating on its own: a pass
that stopped checking instances would remove every decision from a clone and
thereby remove the clone from scope, so the audit would go quiet on exactly the
failure it exists for. **A mono instance is therefore always in scope**, and
P1 carries the extra rule that catches that case — an instance whose TEMPLATE
carries decisions (reached through `origin_node_id`) and which carries none was
materialized and never judged. The template is the oracle rather than "does this
body contain a transfer", because the second question would mean enumerating
boundaries a second time — the duplicate-rule shape obligation 1 refuses — and
because `Atomic.store` and a synthesized `deinit` genuinely have no transfer in
them and were reported as violations when it was asked the naive way.

**Where it runs.** `tools/test_transfer_decisions.py` (the `transferdecisions`
battery lane) grows a second half that drives the funnel over a corpus covering
the four passes, so the gate is cheap and always on. `SAW_TRANSFER_AUDIT=1`
prints the audit on **every** compile and `=strict` exits nonzero on a finding,
which is how the whole corpus is swept and how unit E will promote it to
mandatory. Off, it costs nothing: the module is not imported.

**NON-VACUITY IS PART OF THE GATE, not a claim about it.** A lane that checks
nothing passes as quietly as one that checks everything, so the audit's coverage
counters are themselves asserted: `stamps_checked`, `deferred_emitted`,
`antecedents`, `resolutions` and `coro_rewrites` must each be non-zero across
the corpus or the lane fails ON THE ZERO. That gate immediately earned its keep
— the four conformance rows produce no coroutine-frame REWRITE deferral between
them, so P4 was passing on an empty set, and `examples/coro_closure_capture_positions.saw`
(5 rewrites, 14 syntheses) joined the corpus because the floor said so.

**THE TEETH ARE DEMONSTRATED, per rule.** Three by breaking a preservation path
and reading the lane:

| Break | Rule that fires | What it reports |
|---|---|---|
| drop the `discharge` from the §1c skip-4 arm | P2 | ``a `deferred` decision at `call argument` names no discharge`` |
| hard-code the frame arm's `rewritten` to True | P4 | ``a `coro-frame-rewrite` deferral … carries no antecedent`` (4 sites) |
| skip `check()` in `monomorphize._run_body` | P1 | ``a monomorphized instance body carries NO transfer decision, while the template it was cloned from carries 9`` (5 sites) |

The third is the hazard this unit exists for, reported in the words of the
hazard.

**And four are PERMANENT NEGATIVE TESTS** (`check_audit_detects`), because a
detector that has only ever been shown to fire by hand is a claim, not a gate.
Each removes exactly one obligation from a compiled V91 and asserts the audit
reports it; each is reverted, and the program is re-audited clean afterwards so
the tests cannot measure their own residue:

1. every record for ONE live cloned occurrence, siblings intact, unstamped
   `take`/`move` — the r1 reviewer's own probe shape → **P1b**;
2. one mutation PER PRODUCER: for every (node kind, annotation) pair the
   obligation table holds, that annotation is cleared on such a node and
   **P1r** must fire. Seven pairs on V99, and the selector is the OBLIGATION
   TABLE — never `d.lowering`, which is the field whose absence was the r2
   defect, so a test keyed on it structurally could not find its own bug. The
   `ForceUnwrap` producer and an ordinary `needs_copy` transfer are additionally
   asserted present by name, so the class test cannot quietly stop covering the
   cases that earned it;
3. `origin_node_id` cleared on one node of an instance body → **P5**;
4. a direct assignment to either retain annotation anywhere in `sawc/` → the
   **one-writer gate**, which is what makes 2 exhaustive rather than merely
   broad.

Each was itself verified non-vacuous by neutering the rule it tests and watching
the negative test fail.

It is deliberately not made mandatory here. Unit E (SL-214) is "mandatory
pre-codegen transfer-decision verifier"; unit C builds the verifier's engine and
its corpus evidence, and leaves the mandate to the unit that owns it.

## The review's mechanism, and the sweep it earned (obligation 4)

Revision 1 drew `request-changes` on two demonstrated FALSE NEGATIVES — the
audit certifying programs it should flag — and they are one mechanism:

> **an audit rule that takes its obligations FROM the thing it is checking
> cannot see that thing removed.** Deleting the obligation deletes the check.

The two found faces. **P1 read the annotations**, so clearing a single
`payload_needs_copy` on a `try` removed the obligation from the audit's own
input: the audit stayed green while the emitted program stopped performing the
SL-211 Ok-path retain (`got 7` with no `copy 7`). **P1a read instances with no
surviving decision and P3 read the surviving decisions**, so deleting every
record for ONE live `NoneLiteral` in a monomorphized `init` — unstamped, `take`
at `struct field`, siblings intact — was invisible.

**The third review closed it as a CLASS.** Revision 2 recorded the retain
obligation on the DECISION (`TransferDecision.lowering`), which only the final
implicit-copy arm populates — so design 131's whole payload family was still
uncovered: `_check_payload_read` stamps `payload_needs_copy` on an `o!`, the
checkpoint files `delegated`/`payload-read`, and no obligation exists at all.
Clearing that one stamp dropped a real `Copy`-tier retain (`got 7` with no
`copy 7`) under a green audit. Patching that arm would have been the third patch
to one mechanism, with a fourth arm left to find.

So the obligation moved to where it cannot be missed: **THE SITE THAT STAMPS IS
THE SITE THAT RECORDS.** `_stamp_retain` is the one writer of `needs_copy` and
`payload_needs_copy`, it records the obligation as it writes (and retracts it
when a later pass decides no retain is owed — design 131's assign-never-
accumulate rule), and `tools/test_transfer_decisions.py` fails the build on a
direct assignment to either annotation anywhere in `sawc/`. A new producer
cannot stamp a retain without recording it, because it cannot stamp one at all
except through the funnel.

Seven producers now carry obligations, each with its own negative test:
`ForceUnwrap`, `NilCoalesce`, `IfLetExpr`, `GuardLetStatement`, `TryExpr`
(`payload_needs_copy`), and `Identifier` / `SelfExpr` (`needs_copy`).

Each is now paired with a rule driven from the side the erasure cannot reach:

| Reads | Emptied by | Paired with |
|---|---|---|
| P1 — the annotations | clearing a stamp | **P1r** — the `_stamp_retain` obligation table |
| P1a / P3 — surviving decisions | deleting a decision | **P1b** — the nodes of cloned bodies |
| P1b / P3 — `origin_node_id` | clearing an origin | **P5** — the origin universe itself |
| P4 — `discharge` | clearing a discharge | P2, which fires on a `deferred` with none |

**P5 is the third instance the sweep turned up**, and it is fenceable only
because the universe is knowable: `mono_copy` copies a template's body WHOLE, so
every node of an instance body must carry the stamp. Measured at 99.1% on two
fixtures — and the remaining 0.9% is not noise but exactly the auto-wrap family
(`OptionalWrap`, `ResultOkWrap`, `ResultErrWrap`, `ErasedErrWrap`), which the
instance CHECK inserts after the clone exists, so those nodes were never in the
template and correctly carry nothing.

**ONE RESIDUAL IS NAMED RATHER THAN PAPERED OVER.** Deleting the decision for an
UNSTAMPED transfer at a NON-cloned node is still not detected. P1b covers the
cloned case, P1r the stamped one; what is left has no independent oracle,
because "is this position a transfer?" is answered by the checkpoint's
entry-point list and duplicating that list inside the audit is precisely the
shape obligation 1 refuses. Unit E (SL-214) closes it by construction — a
verifier that RUNS the checkpoint enumerates the boundaries instead of guessing
them — and this module is the engine it promotes.

## A ledger needs RECENCY, not just revision

Building P1r surfaced a fact design 267 had not needed: `revision` records "the
last check is the answer" for ONE key, and a pass that MOVES an expression gives
one live node decisions under TWO keys. The coroutine transform does exactly
that — a `try` bound by a `let` becomes a call argument — so V91's node ends up
carrying a `copy` at `let binding` and a later `take` at `call argument`. Only
the second is the program's judgment, and reading the first as live demanded a
`payload_needs_copy` the program had correctly stopped owing (it fired twice on
unmodified source). `TransferDecision.sequence`, a per-compile write counter,
says which check was last ACROSS keys; the audit reads the operative decision
per node and nothing else.

## Why a funnel and not per-pass checks (obligation 1)

Each pass could have been given its own assertion at its own exit — and that is
how the AST contract was maintained before design 194, by hand, with a comment
saying so. The property here quantifies over "every transfer occurrence in the
program handed to codegen", which is a position-quantified rule, so it gets one
chokepoint: the audit runs once, on the finished program, and cannot be bypassed
by a pass that forgets to call it because it is not the passes that call it.

The docstring names place lowering, specialization, closure conversion and the
coroutine transform, and each of P1-P4 records which pass it is the fence for.

## Obligation 4 — the mechanism behind 4c/4d, and its siblings

The mechanism is **"a pass replaces a judged node with a node it judges
itself, and records the substitution nowhere"**. Its reach was enumerated and
probed rather than assumed:

| Position | Replaces a judged node? | Records it? | Verdict |
|---|---|---|---|
| `mono_copy._copy_node` | yes (template → clone) | no | **in scope** — `origin_node_id` |
| `ASTNode.__deepcopy__` | yes (11 coro-transform sites, trait defaults) | no | **in scope** — `origin_node_id` |
| `_read_field` REWRITE arm (5 sites) | yes (local read → frame read) | no | **in scope** — `coro-frame-rewrite` |
| `_read_field` SYNTHESIS arm (4 sites) | no — there was no node | n/a | **named** — `coro-frame-synthesis` |
| `transform_place_uses` | yes, but the admission re-checks after it | by re-check | not a hole |
| `_hoist_head_and_relinquish` / `_head_into_while_body` | MOVES a node, does not replace it | node identity survives | not a hole |
| `admit_declarations` step 2 | re-checks, does not rewrite | by re-check | not a hole |

The hoist family is the one worth stating explicitly because the dispatch note
flagged it: `_hoist_head_and_relinquish` lifts a head expression into a
preceding `let` and leaves an `Identifier` behind. The **hoisted node keeps its
identity** — it is the same object in a new parent — so its decision is not
detached; what is new is the `let binding` boundary the re-check then judges
afterwards, which is an ordinary decision like any other. Probed on
`c_driven_copy.saw`: every hoisted head's decision is live.

## Conformance rows (obligation 3 — written FIRST)

The guarantee this unit touches is **"the decision the checker made is the
decision codegen executes"**, per pass. Rows V93-V97, each with a sync row and a
driven twin where the coroutine transform is in play — unit B's round is the
precedent for that rule (its driven twin caught a face the sync matrix showed
clean).

| Row | Guarantee | Oracle |
|---|---|---|
| **V93** | a generic body's transfer is judged at the INSTANCE, not the template — two instantiations at two tiers each duplicate exactly right | `Arc.strong_count()` at the `Copy` instantiation, a printing `deinit` count at the move-only one |
| **V94** | the same transfers in a DRIVEN body behave as their sync twin | named-drop counts, sync vs `__saw_drive`, byte-identical |
| **V95** | a closure capture materialized by the transform releases exactly once, at every tier | printing `deinit`, `Copy`/`ExplicitCopy`/`NoCopy` rows |
| **V96** | a frame read that the transform judges itself does not double-pay — the `Copy` tier retains ONCE across a suspension | `Arc.strong_count()` either side of `__saw_suspend()` |
| **V97** | the specialization/transform composition: a generic body that is DRIVEN keeps both answers (instance tier + frame bookkeeping) | drop counts at two instantiations of one driven generic |

V96 is the row that would have caught a double-retain if the deferral's
antecedent were ever re-judged instead of honoured, which is the failure the
`frame_place_read` arm exists to prevent and which nothing pinned.

## Consumer sweep (obligation 2)

No behavioural contract flips. The two things that gain a consumer:

* `ACTION_DEFERRED` — previously "somebody else decides", now carrying a named
  `discharge`. Its only readers today are `tools/test_transfer_decisions.py`'s
  well-formedness table and this unit's funnel; unit D and unit E are the
  intended future ones. Nothing in the compiler branches on the action.
* `origin_node_id` — a new annotation. `substitute_ast_types` walks it (an
  `int`, no-op), `structural_fields` excludes it (so no child walker follows it),
  `_copy_node` overwrites it per clone. It never reaches codegen and never
  reaches the IR, which is what keeps `irdet` and `reemit` unaffected — both are
  gates for this unit regardless, since the audit runs inside the compile when
  the env switch is on and must not when it is off.

## Acceptance

* The funnel exists, is one entry point, and its docstring names the four passes.
* P1-P4 hold over the fixture corpus in the `transferdecisions` lane, and over
  the whole `examples/` corpus under `SAW_TRANSFER_AUDIT=1`.
* Every `deferred` decision carries a `discharge` from the closed set; adding a
  new deferral arm without one fails the lane.
* V93-V97 pass, sync and driven, with the counting oracles above.
* Behaviour-preserving: no diagnostic, annotation, accepted program or rejected
  program changes; `irdet --all` and `reemit` are unchanged.

## What this unit deliberately does NOT do

* Touch `_transfer_needs_copy`. Unit D.
* Make the audit mandatory before codegen. Unit E.
* Retire the legacy frame encodings so that `coro-frame-synthesis` disappears.
  That is design 218 stage 1's `Slot` migration, already in flight; this unit
  counts the residue so its progress is visible.
* Give the payload-read and place funnels decisions of their own. Unit B/E, as
  design 267 said.

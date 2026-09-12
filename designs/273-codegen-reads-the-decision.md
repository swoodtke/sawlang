# Design 273 — retiring codegen's independent ownership guesses

**Unit D of SL-209** (the ownership-uniformity epic), filed as **SL-213**. Plan
step 6. Batched with **SL-220**, **SL-267** and **SL-268**, the three
cleanup-and-registration findings the unit's own mechanism owns. Depends on
units A (design 267), B (design 269) and C (design 270).

> **The number 273 is PROVISIONAL.** 272 was the highest brief when the branch
> opened; it is the lead's and the user's to confirm or renumber at
> integration.

## What this unit is for

Units A through C made the front half answerable: decisions are recorded (267),
the producer question is total and gated (269), and the decision is provably
preserved to codegen (270). Unit D is the back half — codegen must stop
**re-answering** questions the checker already answered.

The epic named one target, `_transfer_needs_copy`. The census found that name
covers only half the problem, and that the half it covers is not retirable for
the reason the epic assumed. Both corrections are this unit's real content.

## THE CENSUS — 21 sites, and they are TWO questions, not one

Ownership at a transfer is two questions, and design 267 said so at the front
end: WHERE the value acquires a new owner, and HOW the expression produced it.
Codegen re-derives on **both** axes, and the two families have nothing in
common but their failure mode:

| Face | Question | Predicate | Reach | Symptom when wrong |
|---|---|---|---|---|
| **A** | does this transfer owe a RETAIN? | `_transfer_needs_copy` + four sites that bypass it | 12 sites | a duplicate that never retained — use-after-free, refcount underflow |
| **B** | does this value need a CLEANUP registered? | `_is_owned_temporary` | 10 sites through one predicate | a value nobody releases — a leak |

Face B is invisible from the anchor the epic named: `_transfer_needs_copy` has
never heard of it. That is the census's most useful single finding, and it is
where three of this unit's four batched issues live.

### Face B — one predicate, and it was the wrong list

`_is_owned_temporary` (`sawc/codegen/resources.py`) answered "does this
expression mint a fresh owned value?" with an isinstance list of eight node
classes. That is design 269's documented failure mode verbatim, one module
over: a node that mints a value and is not on the list answers False, and the
value leaks. The list had exactly the shape 269 replaced at the front end, and
nothing gated it.

**Measured at a member-access receiver, with a printing `deinit` on a NoCopy
type — one value built must give one `drop`:**

| Producer | Kind | Before | After |
|---|---|---|---|
| `plain(1).w` | BUILDS | `drop` | `drop` |
| `(try! made(2)).w` | PROJECTS → BUILDS | **leak** | `drop` |
| `maybe(3)!.w` | PROJECTS → BUILDS | **leak** | `drop` |
| `(move r).w` | OWN_ARM | **leak** | `drop` |
| `(if c { … } else { … }).w` | BRANCHES | **leak** | `drop` |
| `(match c { … }).w` | BRANCHES | **leak** | `drop` |
| `(maybe(7) ?? plain(70)).w` | BUILDS | **leak** | `drop` |
| `Res(w: 8).w` | BUILDS | `drop` | `drop` |
| `held.w` | READS | not registered | unchanged |
| `h.inner.w` | READS | not registered | unchanged |

**SL-220 filed two of those rows. Six were leaking.** `(move r).x`, both value
branches and `??` were unfiled siblings of one mechanism, which is what
obligation 4 predicts and why the fix targets the enumeration rather than the
symptom.

The predicate now reads `typechecker.producers.producer_kind` — the same total
classification the checkpoint asks, with a build gate that fails when a node
class is unclassified. The mapping is one line per kind and is written in the
docstring; only two entries are judgment rather than transcription:

* **PROJECTS recurses to its operand**, because the owner of the operand is the
  owner of the part — `(try! r).w` over a BOUND `r` must NOT register, and
  measured, it does not (the binding still drops it once). The exception is a
  payload the extraction itself duplicated, which design 131 records as
  `payload_needs_copy`; that one is the reader's.
* **BRANCHES registers**, because every arm is a transfer into the merged home
  (DF-299b) — a fresh arm hands over a temporary and an arm that READS a
  binding retains AT the arm. Measured at the `Copy` tier: the arm's `copy`
  printed and its release did not, a leak the NoCopy rows could not show.

### Face A — the named target, and why it does NOT come out

The epic's premise was that `_transfer_needs_copy`'s shape/tier tail is a second
opinion to be retired. **It is not, and the measurement is unambiguous.**

Inside a MONOMORPHIZED GENERIC BODY the checker files `deferred`, with
`discharge = tier-requirement:<instance>.<param>`: design 219 wave C discharges
the requirement at the CALL SITES, so no `needs_copy` is ever stamped on the
instance body's own nodes. The tail is the only answer there. Disabling it and
running `V32_copy_bound_is_tier_derived` leaves the program compiling and
**silently wrong** — its `Arc.strong_count()` oracle reads 6 where it must read
1. The arm census over the conformance corpus finds 36 such answers.

So this unit does **not** delete the tail. What it retires is the tail's
*stated justification*, which had gone stale in a way that would have led the
next reader to delete the wrong thing. It read "`self` and inner-block tails
aren't marked by the checkpoint" — true when written, **false since unit B**:
`SelfExpr` joined `PRODUCER_READS` (SL-218) and DF-299b's recursion stamps
inner-block arm tails, so both carve-outs now reach the `needs_copy` arm. The
docstring now names the real reason and the condition under which the tail can
go, which is unit E's ground.

The `place_value_read` and `frame_owning_read` arms stay for a reason of the
same shape and it is now written down: they answer for the two funnels that
record **no decision at all** (design 146's place read, design 270 §4c/4d's
coroutine frame, where the transform is the stated authority). There is nothing
to migrate onto until unit B/E gives those funnels decisions.

### The four sites that bypass the anchor — FILED, NOT FIXED

The census's sharpest finding is outside this unit's remit and is filed as
**SL-275**: four transfer boundaries decide the retain with an inline
`isinstance(value, Identifier)` of their own and never consult the checker —
`let _ = …`, a destructuring `let`, `x?.y = …`, and a struct literal's field.
The shape test agrees with the checker on a bare binding and disagrees on every
PROJECTION, so each duplicates without retaining. Three reproduce on this branch
as a **segfault**, a **SIGABRT** and a **use-after-free + SIGABRT**; at the
struct-field site the instrumented trace shows the checker stamping
`needs_copy=True` and filing `copy` while codegen answers False from its node
list. That is the whole SL-209 thesis in four lines.

They are not fixed here because they are not this unit's four batched findings,
and the dispatch rule is to stop and file rather than widen scope mid-unit.
SL-275 carries the matrix, the fix shape, and the obligations it owes (driven
twins, conformance rows, the tier axis) so it can be dispatched as written.

## The three batched findings

### SL-220 — a payload extracted from a fresh temporary

Closed by the Face B migration above; it was two rows of a six-row mechanism.
The filed repro now prints four values built and four released.

### SL-268 — a `[copy x]` capture into a non-escaping closure

The same class one boundary over, and design 267's inventory had already named
it: `[copy x]` is the one capture mode of three reaching no ownership funnel.
An ESCAPING closure was correct by accident of its lowering — a refcounted heap
env whose destructor releases every capture — while a NON-escaping one keeps a
STACK env with no destructor at all, so the duplicate was minted and dropped on
the floor. It is registered at the funnel now, and only for `copy`: the other
three modes own nothing there (`plain` takes no retain into a stack env, `move`
is DF-218h's deferred transfer the BODY performs, `ref`/`ref_var` store a
pointer).

**A body's TAIL had no statement context at all**, which is the position
SL-268's own repro is written at. `statement_temps` is None outside a statement,
so `_register_stmt_temp` silently registered nothing and a fix validated against
a `let` would have looked complete. The tail now opens a statement-shaped
extent, drained after the value is in hand — never before, since the tail's
result is read OUT of those temporaries. Only the OUTERMOST tail opens one; a
nested block's tail already runs inside a statement and is confined by design
94's existing mark.

### SL-267 — a driven capture duplicating twice: HALF closed

The half that changes the ANSWER is fixed. The transform materializes a
frame-resident local as a `let` for the closure to name, and that
materialization already duplicates; the author's own `[copy x]` spec was left
riding that local and duplicated it AGAIN, so a driven body ran the user's
`copy()` hook twice and — at a non-idempotent hook — computed a different value
from its sync twin (71 vs 72).

**THE MODE IS NOT RE-TYPED, and the review is why (r2).** Revision 1 removed the
second duplication by rewriting the spec's mode from `copy` to `move`, on the
reasoning that `move` is what the materialized local IS — a value this statement
just minted and nobody else holds. That reasoning was right about OWNERSHIP and
wrong about REUSE. A `move` capture into a NON-escaping env is DF-218h's
DEFERRED protocol: the env holds a pointer to the local plus its drop flag, the
body TAKES the value on its first run, and the occupancy flag panics on the
second — `closure body ran twice on \`move\` capture \`d\``, exit 134. An
authored `[copy x]` asks for a duplicate the closure OWNS; it is reusable by
construction, and no lowering may move it into the one-shot category.

So the mode stays what the author wrote and the spec carries **provenance**
instead: `CaptureSpec.materialized`, "the duplicate already exists". Codegen's
materialized arm skips the second duplication and *only* that, then decides
ownership for itself from the one question a capture's lifetime actually turns
on — **does the closure escape?**

* **Escaping** — the heap env outlives the materialized local, so the env must
  OWN the duplicate: the same transfer the `move` arm performs, reached without
  the mode, with the env destructor releasing once at closure teardown rather
  than per invocation.
* **Non-escaping** — the stack env cannot outlive the local, so the LOCAL keeps
  ownership and its own scope cleanup releases the duplicate exactly once. The
  env holds a bare alias, which is precisely what makes the body re-runnable.
  SL-268's `_register_stmt_temp` must not fire here for the same reason: the
  local is already a registered owner, and a second registration would be a
  double free rather than a leak fix.

Because the mode stays `copy`, `deferred_moves` — which keys on `move` — never
claims the capture, so the one-shot protocol is unreachable from this path by
construction rather than by a second guard. Sync and driven now agree on the
value and on the counts at one invocation and at two.

**THE MATERIALIZATION IS PER SPEC, and the second review is why (r3).** Revision
2 recorded the provenance on the spec and left the LOCAL keyed by the source's
NAME, which is how the materialization had always been keyed — `local = name`
for a written spec, and a `let` already in the accumulator is skipped. That is
correct for a capture that mints nothing, and wrong for one that mints a value:
two closure literals in ONE expression shared a single synthesized local while
BOTH specs said "already duplicated", so codegen skipped BOTH authored copies
and one duplicate reached two closures. The two faces are opposite and both
wrong:

* **Non-escaping** — an UNDERCOUNT. `both({ [copy d] in d.n }, { [copy d] in d.n })`
  ran `copy()` once where its sync twin ran it twice; the sum was wrong and a
  non-idempotent hook was observably skipped.
* **Escaping** — a DOUBLE FREE. Each heap env owns every capture it holds, so
  both envs owned the same duplicate and each released it at teardown: one
  `copy 20 -> 21` and `drop 21` TWICE. With an `Arc` payload the count went
  below what a still-live root holds — a read through the root came back from
  freed storage and the process died on `over-release of an Arc (refcount
  underflow)`, exit 134, in safe code.

So the local is per SPEC: each `copy` capture gets its own `__capN_<name>` and
the literal is renamed onto it, exactly as an implicit capture already was, and
the count of duplicates equals the count of captures at every multiplicity.
Deduplication survives for the modes that mint NOTHING (`[move x]`, `[&x]`,
`[x]`), where several literals sharing one binding is what should happen. The
mode still stays `copy` — r1's invariant is orthogonal to this one, and both
hold: **a capture's MODE says whether it is reusable, and the LITERAL that wrote
it says whose duplicate it is.**

Routing `[copy x]` through the rename surfaced **SL-282**, a defect of the
rename itself with no capture spec in it at all: `_rename_in_closure` walked the
body's identifier nodes — which reaches a NESTED literal's body — but rewrote
only the OUTER literal's capture bookkeeping, three lists of plain strings no
identifier rewrite can see. A nested closure went on declaring a capture of `t`
while its body read `__cap0_t`, and codegen built an env with no such binding:
`internal compiler error … Undefined variable: __cap0_t`, on a program whose
sync twin compiles. Reproducible on origin/main through the all-implicit shape
(`run({ run({ t.n }) })` in a driven body), so it is not new here — but it is
not separable either, since an authored `[copy t]` now takes that path, and
leaving it would mean this unit INTRODUCING the failure for a shape that worked.
One helper, `_rename_closure_bookkeeping`, now runs for every literal in the
subtree and for the outer one through the same code.

**The drop ORDER differs between the twins and that is the fix visible in the
output**: sync releases the duplicate first (it is the inner binding), while the
driven twin's materialized local keeps ownership and is released in the frame's
own teardown order. One `copy` and two `drop`s on both sides. V106 states it.

The half **V96 pins is not closed**, and the blocker is recorded on SL-267
rather than worked around: an implicit capture still pays one duplication in a
driven body and none in its sync twin. The escape answer is available at the
materialization (traced: `False` for the non-escaping row, `True` for the
control), but every spelling of a non-retaining read available today releases
the local somewhere — `move` hands it to DF-218h's deferred take, `plain` leaves
it cleanup-registered, `move_read` + `__saw_forget` is only sound if the frame
never reads the field again, and codegen's `borrowed_variables` marker is
closure-body scoped. Closing it needs the transform to materialize a NON-OWNING
local, or to skip materialization for a non-escaping closure entirely — a
brief-sized change to the capture seam with corpus-wide reach, adjacent to
design 218 stage 1's `Slot` migration. V96 keeps its XFAIL and its citation.

## Obligation 3 — conformance rows

* **V104** — a value no binding holds is released exactly once, whatever
  expression produced it. Driven by the TAXONOMY's kinds rather than by the six
  found shapes, so a seventh cannot appear silently; the two READS rows are the
  control in the opposite direction, where registering would be a double free.
  Sync and driven twins.
* **V105** — a `[copy x]` capture releases the duplicate it minted, at all four
  positions a non-escaping closure can be built in (the TAIL is the one a fix
  written against a `let` would miss). `copy()` BUMPS the value so each
  duplication is countable by value. C1/C2/C3 are the double-free controls:
  escaping, `[move]` at the same tier, `[move]` at NoCopy.
* **V106** — a written `[copy x]` capture duplicates once in a driven body,
  exactly as in its sync twin, at the ceremony tier (a different computed VALUE)
  and the silent one (an extra retain). Its header records that the implicit
  half stays pinned by V96, so the two rows do not read as covering one thing,
  and — since r2 — states that **every cell invokes exactly once**, which is the
  limit that let the r1 regression through.
* **V107** — a capture that is supposed to be REUSABLE survives repeated
  invocation, driven as sync. Four `[copy]` cells (non-escaping and escaping ×
  sync and driven) plus a plain and a borrow capture in a driven body, **every
  cell invoked TWICE**. Three oracles, because they fail differently: the
  `copy()` hook counts duplications, the printing `deinit` counts releases (an
  env releasing per invocation instead of once at teardown reads balanced in a
  one-call row), and the bumping `copy()` puts the answer in the SUM — 24 for a
  correct duplication, 26 for the pre-SL-267 double, and no answer at all for a
  one-shot.

* **V108** (r3) — every authored `[copy x]` capture owns its OWN duplicate,
  including when several captures name one source in one expression. Eight
  cells: the 2×2×2 grid (two literals × sync/driven × escaping/non-escaping),
  multiplicity THREE, V107's two-invocation dimension crossed with this one, the
  `Arc.strong_count()` memory-safety oracle (3 while both closures live, back to
  1 after, and a read that must still answer 7), and NESTED literals. The
  reviewer's three repros are also kept verbatim as their own regressions —
  `examples/two_copy_captures.saw`, `examples/two_escaping_copies.saw`,
  `examples/two_copy_arc.saw` — and the nested ICE as
  `examples/nested_closure_captures_frame_local.saw`.

**A SINGLE-INVOCATION MATRIX CANNOT SEE A ONE-SHOT**, and that is the row the r2
round earned. **A SINGLE-CAPTURE MATRIX CANNOT SEE A SHARED DUPLICATE**, and
that is V108. The invocation count is written into every row, and so, now, is
the capture count.

## Obligation 4 (r2) — the INVOCATION dimension, swept across the mode axis

The r1 regression was not a wrong answer; it was a **dimension no cell varied**.
Every capture row in the tree invoked its closure once, so "how many times may
this body run?" was untested at every mode, and a lowering that silently moved a
capture between the reusable and one-shot categories passed every gate. The
mechanism is "a matrix that fixes a dimension cannot see a defect in it", so the
sweep is over that dimension, at every mode, sync and driven, N=2:

| Capture | Env | Calls | Result |
|---|---|---|---|
| `[copy x]` | non-escaping | 2 | 24/24 sync/driven, 1 copy, 2 drops — **the regression, now fixed** |
| `[copy x]` | escaping | 2 | 24/24, byte-identical twins |
| implicit, trivial-cleanup type | non-escaping | 2 | 2/2 — never deferred (`_needs_cleanup` is False, so it misses the deferred gate) |
| implicit, cleanup-needing type | non-escaping | 2 | 14/14, balanced — the driven side pays V96's known extra copy and still re-runs |
| plain | non-escaping | 2 | 22/22 |
| borrow `[&x]` | non-escaping | 2 | 22/22 |
| `[move o]` | escaping | 2 | 14/14 — the env owns it for the closure's lifetime |
| **`[move o]`** | **non-escaping** | **2** | **PANICS, and must** — DF-218h's occupancy flag, exit 134. The control that keeps the one-shot category intact; re-probed to confirm r2 did not weaken it |

The last row is the point of the sweep rather than an exception to it: one-shot
is a real and intended category, so the bug was never "a capture panicked on its
second run" but "a capture the author wrote as reusable was put in that category
by a lowering". Both categories are now asserted.

Two observations recorded rather than filed. A `[&x]` borrow capture in a driven
body is materialized too, so the closure borrows the materialized duplicate
rather than the frame's field — counts balance and reads agree, and it is part of
V96's open half rather than a new finding. And the implicit-capture rows show the
deferred gate is reached only when the captured type needs cleanup, which is why
the implicit path never had the one-shot exposure the explicit one did.

## Obligation 4 (r3) — the MULTIPLICITY dimension

Same mechanism class as r1, one dimension over. r1 was "no cell varied the
invocation count"; r2 was **"no cell varied the number of captures naming one
source."** Every capture row in the tree — V96, V105, V106, V107 and the
examples corpus — has exactly one `[copy]` literal per statement, so
"deduplicated by source name" was indistinguishable from "one local per
capture", and a revision that made the two disagree passed every gate. The
mechanism is the dedup in `_materialize_closure_captures`, so the sweep is over
the count and the mix of captures naming one source, in one expression, at every
position the pair can be written in, sync and driven. Every cell run on BASE
(origin/main 5755f60b), on the r2 branch and on the fix.

| Cell | Base | r2 | Fixed |
|---|---|---|---|
| 2 literals, non-escaping (call args), driven | 44, both duplicates LEAKED (SL-268) | **1 copy, undercount** | 42 = sync, 2 copies, 2 drops |
| 2 literals, escaping (tuple), driven | 44 (SL-267's extra copy) | **1 copy, `drop 21` TWICE** | 42 = sync, byte-identical twins |
| 2 literals, escaping, `Arc` oracle | 3/3, root back to 1 | **2/2, root reads -1663492475164280740, `read 0`, refcount-underflow abort** | 3/3, root back to 1, `read 7` |
| THREE literals, non-escaping AND escaping, driven | — | — | 3 copies, 3 drops, = sync |
| 2 literals in a Vector LITERAL, driven | 44 | — | 42 = sync |
| 2 literals in the arms of a value `if`, driven | 32 (only one arm builds; the extra copy is the materialization's) | — | 31 = sync |
| 2 literals in a block `match` ARM, driven | 44 + leak | — | 42 = sync |
| 2 literals in a `match` SCRUTINEE, driven | **44, so the match took the wrong arm and answered 0 where sync answers 1** | — | 1 = sync |
| NESTED literals, both `[copy]`, driven | 3 copies + leak | — | 2 copies, 3 drops, = sync |
| NESTED literals, both IMPLICIT, driven | **ICE: `Undefined variable: __cap0_t`** | ICE | compiles, = sync (**SL-282**) |
| `[copy x]` beside `[move x]`, driven | 43 | — | 42 — residual is SL-281, below |
| `[copy x]` beside a PLAIN capture, driven | 60 = sync | — | 60 = sync |
| `[copy x]` beside a BORROW `[&x]`, driven | 80 = sync | — | 80 = sync |

Two findings, both isolated to a lone-capture repro before filing so that
neither is confused with multiplicity:

* **SL-281** (base defect, NOT fixed here) — the residual in the mixed
  `copy`+`move` cell is not multiplicity at all. A LONE `[move d]` capture of an
  `ExplicitCopy` frame local in a driven body runs the author's `copy()` hook,
  which its sync twin never runs, and the closure reads 21 where sync reads 20.
  The mechanism is the read-policy funnel choosing the ceremony-tier `.copy()`
  on the TIER alone, before the capture MODE is consulted — SL-267's mechanism
  one mode over, and not closable on the same terms (the NoCopy branch's
  `move_read` + `__saw_forget` empties a field the frame may read again, which
  is V96's open blocker). Byte-identical output from the base and the fixed
  compiler, so it is filed with its probe and its own sweep of the funnel's
  other modes.
* **SL-282** (base defect, fixed here because it is not separable) — the nested
  rename ICE, described in the SL-267 section above.

## Obligation 2 — consumer sweep

`_is_owned_temporary` is a behavioural contract that widened, so all seven of
its call sites were swept: a member-access object, a method-call receiver and a
field-call receiver, an expression STATEMENT, an `if let`/`guard let` scrutinee,
and a `match` scrutinee in both lowerings. One needed work — a statement-position
`if`/`match` is CONTROL FLOW, deliberately unannotated, so the value question is
now asked before `_expr_type`, which fails loud everywhere it IS a value.

Two duplicate node lists were found and removed rather than updated: the verbatim
copy of the predicate's list in `structs.py:_narrow_field_read` (both spellings
answered `None`, so it bought nothing and could only drift) and its now-unused
imports.

**Codegen imports `typechecker.producers` function-locally**, mirroring
`typechecker`'s own `from codegen.mangle import …`. The module is a pure
classification over node-local annotations — it holds no state and reads no
scope — which is what makes asking it from codegen answer the same question
about the same node.

**ONE SEAM FACT the taxonomy's gate cannot see, named rather than absorbed:**
codegen declares `Expression` subclasses of its own (`PreparedValue`, design
137) which live outside `ast_nodes` and so outside the gate's universe. Asking
the taxonomy from codegen widens that universe. Such a node is answered by name
with its reason — its value's lifetime is its builder's — and everything else
still reaches the taxonomy and is still LOUD when unclassified, which is the
property design 269 exists to hold.

## Acceptance

* Face B reads the checker's classification; the six leaking producer shapes
  release exactly once, and the two READS controls still do not double-free.
* SL-220 and SL-268 are closed, with V104/V105 as their regressions.
* SL-267's value-miscompile half is closed with V106; its counting half stays
  pinned by V96 with the blocker recorded.
* Every authored `[copy x]` capture owns one duplicate at every multiplicity
  (V108 plus the three filed repros), and SL-282's nested-rename ICE is closed
  with it.
* `_transfer_needs_copy` keeps its tail, with the measurement that says why and
  the condition under which it can go.
* The four bypassing sites are filed as SL-275 with a dispatchable matrix.

## What this unit deliberately did NOT do

* Delete `_transfer_needs_copy`'s isinstance tail. Measured load-bearing; gated
  on design 219 wave C's discharge materializing as an annotation.
* Fix SL-275's four sites. Outside the batch; filed with evidence.
* Fix SL-281's driven `[move x]` materialization. Broken on base, unchanged
  here, and blocked on the same capability V96's half is; filed with evidence.
* Close SL-267's implicit-capture half. Needs a capture-seam change.
* Give the place or coroutine-frame funnels decisions of their own. Unit B/E, as
  designs 267 and 270 both say.
* Make the preservation audit mandatory before codegen. Unit E (SL-214).

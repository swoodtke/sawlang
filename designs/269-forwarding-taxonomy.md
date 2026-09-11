# Design 269 — the forwarding and control-flow taxonomy

**Unit B of SL-209** (the ownership-uniformity epic), filed as **SL-211**. Plan
step 4. Closes **SL-79 (DF-305a)**, **SL-218** and **SL-219**.

> **The number 269 is PROVISIONAL.** 268 was the highest brief when the branch
> opened; it is the lead's and the user's to confirm or renumber at
> integration.

## What this unit is for

Design 267 (unit A) split ownership at a transfer into two questions and
recorded the answer to each: **WHERE** the value acquires a new owner (the
boundary — `_check_value_transfer`'s nineteen named entry points) and **HOW**
the expression produced it (the producer). It then reported, as its structural
finding, that the second question is answered by a shape that cannot be
audited:

> `_is_aliasing_expr` … answers it as a **node-type test over four classes**
> … plus two hand-added transparencies and one hand-added exclusion. That
> shape is the whole reason producers go missing.

This unit replaces the shape. The producer question becomes a **total
classification** over every node that can occupy a value position, with an
enumeration gate that fails the build when one is unclassified — and the three
findings the old shape was still hiding are closed by adding their members to
it, which is the only edit their fix needs once the funnel exists.

It is **not** behaviour-preserving, and it cannot be: each of the three
findings is a program that compiles today and must stop.

## Why this is one mechanism and not three bugs (obligation 4)

`_is_aliasing_expr` gates **every tier arm** of the checkpoint. A node that is
not on its list answers False, and the checkpoint then classifies the read as a
fresh owned temporary — so one missing member turns an aliasing read into a
transfer at every tier at once:

* `NoCopy` skips its refusal → **double free**;
* `ExplicitCopy` skips its refusal → **SIGABRT** (one buffer freed twice);
* `Copy` skips its `needs_copy` stamp → an **unretained second owner**, a
  refcount underflow.

That is why the fence is tier-blind, and it is why the Copy tier is the
dangerous one to test on: codegen's `_transfer_needs_copy` keeps an isinstance
list **of its own** and re-derives the retain there, so the tier a second
opinion can paper over looks correct while the two it cannot are fatal. SL-209's
thesis, visible in one program.

The mechanism has produced a finding roughly every two months for ten:

| Finding | Missing member | Symptom |
|---|---|---|
| design 131 | `ForceUnwrap` not transparent | hand-added |
| design 139 | `enum_variant_literal` wrongly aliasing | hand-excluded |
| DF-216a | synthesized call constructions skipped the checkpoint | — |
| DF-299a | forwarding `CastExpr` not transparent | double free |
| DF-288a | `SelfExpr` missing from the *borrowed-scrutinee* list — a SECOND list asking the same question | double free |
| **SL-218** | `SelfExpr` not in the aliasing set | double free (measured) |
| **SL-219** | `TryExpr` not transparent to its subject | triple free (measured) |
| **SL-79** | the four auto-wraps not transparent | double free (measured) |

Six of the eight are the same edit: somebody found a member and added it. A
seventh would have followed. The fix targets the enumeration, not the members.

## The producer taxonomy

`sawc/typechecker/producers.py`. Six kinds, each answering "what does a new
owner receive from this node?"

| Kind | Meaning | Members |
|---|---|---|
| `READS` | DENOTES storage an existing owner keeps | `Identifier`, `MemberAccess`¹, `ArrayIndex`, `TupleIndex`, **`SelfExpr`** |
| `PROJECTS` | names a PART of such storage; the node's own type transfers, the OPERAND answers the aliasing question | `ForceUnwrap`, `CastExpr`², **`TryExpr`** |
| `REWRAPS` | RE-TYPES its operand; the OPERAND's transfer is the one to judge | **`OptionalWrap`**, **`ResultOkWrap`**, **`ResultErrWrap`**, **`ErasedErrWrap`** |
| `BRANCHES` | one transfer PER ARM (DF-299b) | `IfExpr`, `IfLetExpr`, `MatchExpr`, `TryExpr`, `TryCatchExpr` |
| `BUILDS` | a fresh value the reader already owns | the 27 literals, calls, constructions and operators, plus the six with rules of their own (below) |
| `OWN_ARM` | states the ownership answer rather than producing a value | `MoveExpr`, `ReferenceExpr` |

¹ unless `enum_variant_literal` (design 139) — then `BUILDS`.
² only when `forwards_operand` (DF-299a) — otherwise `BUILDS`.

**`PROJECTS` and `REWRAPS` are two different transparencies, and collapsing
them would be wrong.** A projection hands back a *part* of the operand's
storage, so the value's type is the NODE's (`try r` yields a `Res`, not a
`Result<Res, Bad>`) and the diagnostic must name that type. A rewrap hands back
the *same* value under a wider type, so the transfer to judge is the OPERAND's,
at the operand's type, which is where the author's `move` goes. The old code
had one relation and used it for the first case only.

**`TryExpr` is in two buckets, deliberately.** It PROJECTS its Ok value out of
its subject and BRANCHES into its catch handler — two result sources with two
rules, which is exactly what SL-219 was: DF-299b's recursion judged the catch
arm and the comment beside it said the subject "is that expression's question",
and nothing ever asked it. The gate knows that one overlap by name and rejects
any other.

### The universe is not "the `Expression` subclasses"

Design 267's census enumerated the 45 `Expression` subclasses. That is the
wrong universe, and getting it wrong is its own version of the same bug: a
`Statement` carrying a `result_type` can sit in a value position too. Exactly
one does — **`ForLoop`**, whose `let n = for i in 0..3 { … }` spelling reaches
the checkpoint — and the gate found it within one suite run of the funnel
landing.

The gate (`tools/test_producer_taxonomy.py`) therefore enumerates
`Expression` subclasses **∪** every node declaring a `result_type`: **46**
classes, all classified. It also checks that the buckets are disjoint bar the
documented dual, hold only real nodes, answer through `producer_kind` for a
bare instance of each, and that the **two** walks which must see through the
same nodes — `_is_aliasing_expr` and `ownership._transfer_source_identity` —
both go through the funnel and neither keeps a node-type list of its own. Those
two walks were previously kept in step by hand, with a comment saying so.

### The census row design 267 missed, and why it is benign

`NilCoalesce` appears in **no** bucket of design 267's census — not in the
transparent list, the excluded list, the "not producers" list, or the missing
list. Probed on the unfixed tree: `let a = x ?? Res(w: 0)` over a NoCopy
binding is **refused**, by the payload rule. It is correct because both
sub-positions are judged at the `??` node's own check — the LEFT operand
through `_check_payload_read`, the DEFAULT operand as entry point 18 — so the
node itself is never a producer. It is `BUILDS`, with the reason written down.

Three more were probed rather than assumed: the optional-chain family is
refused by design 111's own final-field rule, `break <value>` out of a
`while { }` is refused at entry point 17, and `ErasedErrWrap` — the fourth
wrap, which SL-79 predicted but nobody had measured — **double frees**, at
exit 0, on a field source.

## The taxonomy matrix

Every row measured on the unfixed tree and again on the fixed one. `Res` is
`NoCopy` with a printing `deinit`; one value should give one `drop`.

### Rows that CHANGE — the three findings

| # | Position | Kind | Before | After |
|---|---|---|---|---|
| S1 | `self` → return (`func f(&self) -> Res { self }`) | READS | `drop` ×2 | refused |
| S2 | `self` → by-value argument | READS | `drop` ×2 | refused |
| S3 | `self` → `let` binding | READS | `drop` ×2 | refused |
| S4 | `self` → struct field | READS | `drop` ×2 | refused |
| S5 | `self` → tuple element | READS | `drop` ×2 | refused |
| S6 | `&var self` → return | READS | `drop` ×2 | refused |
| T1 | `try r` (propagating) | PROJECTS | `drop` ×3 | refused |
| T2 | `try! r` | PROJECTS | `drop` ×3 | refused |
| T3 | `try? r` | PROJECTS | `drop` ×3 | refused |
| T4 | `try r catch { … }` subject | PROJECTS | `drop` ×3 | refused |
| T5 | `try! h.r` (FIELD subject) | PROJECTS | `drop` ×3 | refused |
| W1 | named function tail → `OptionalWrap`, aliasing source | REWRAPS | `drop` ×2 | refused |
| W2 | named function tail → `ResultOkWrap`, aliasing source | REWRAPS | `drop` ×2 | refused |
| W3 | `return` → wrap, in a function/method | REWRAPS | `drop` ×2 | refused |
| W4 | `return` → wrap, in a CLOSURE (the SL-79 pin) | REWRAPS | `drop` ×2 | refused |
| W5 | tail → `ErasedErrWrap` (the erased Err side) | REWRAPS | `drop` ×2 | refused |
| W6 | tail → wrap, **OWNED** source (`func f(r: Res) -> Res? { r }`) | REWRAPS | `drop` ×1, sound | **refused** — the ruling, below |

### Rows that DO NOT change — the fence is narrow

| # | Position | Why it stays legal |
|---|---|---|
| N1 | `try f()` over a call result | a fresh temporary the reader already owns — DF-299a's line |
| N2 | `(try! make(n)).w` inline | same; asserts LEGALITY only (it leaks — SL-220, below) |
| N3 | `self` at the `Copy` tier | retains exactly once, as it always did |
| N4 | `self` at the trivial tier | a bitwise copy; no obligation on either side |
| N5 | a wrap around a fresh temporary | `take`, unchanged |
| N6 | `try move r`, `move self`-free `consumes` spellings | the consuming forms the refusals name |
| N7 | a value BRANCH arm | DF-299b's recursion, unchanged — the wrap peel runs ahead of it and they compose |
| N8 | `break <value>` | entry point 17, unchanged |
| N9 | a GENERIC body's forwarding | design 219 wave C counts per PATH; `-> T?` at an abstract `T` still defers |
| N10 | a place window's tail | design 264 / DF-169h's `is_place_window` carve-out, untouched |

### The tier axis

| Tier | S-rows | T-rows | W-rows |
|---|---|---|---|
| `NoCopy` | refused | refused | refused |
| `ExplicitCopy` | refused | refused | refused |
| `Copy` | retains **once** (regression guard) | retains once | retains once |
| trivial | bitwise, nothing stamped | bitwise | bitwise |
| abstract (generic) | deferred to specialization | deferred | deferred |

The `Copy` row is a **regression guard**, not a fix, and it is the row V80 and
V84 earned: codegen already re-derives the retain for a `SelfExpr` and for an
inner-block tail, so the risk this unit carries is a SECOND retain beside the
derived one. Counted with `Arc.strong_count()`.

## The SL-79 ruling

SL-79 filed the fix with a ruling attached, because making the checkpoint
transparent through a wrap also refuses row **W6** —
`func opt(r: Res) -> Res? { r }` — a shape that is sound today (at an owned
source the wrap really does transfer; codegen clears the source's drop flag).
The question it posed: which of two neighbours is right, given that

```saw-fragment
func plain(r: Res) -> Res  { r }     // refused: demands `move`
func opt(r: Res)   -> Res? { r }     // compiles, and moves implicitly
```

**Decided: the wrap is TRANSPARENT.** One rule, and the corpus migrates to
`move`. Three reasons, in order of weight:

1. **The alternative does not close the bug.** "The implicit move at a wrap is
   intended" would keep W6 legal, but W1-W5 double free at sources the frame
   does not own (a `&var` capture, a `&Holder` field), and no implicit-move
   reading makes those sound — they would need the aliasing test anyway, which
   is the transparency.
2. **It deletes a spelling difference nobody could explain.** The two functions
   above differ by one `?` and disagree about whether a move must be written.
3. **It is one rule, and one rule is auditable.** The peel happens at the
   checkpoint, not at the three wrap sites, so every present and future entry
   point gets it — obligation 1's funnel.

**The measured migration cost is ONE line.** Across `sawc/std/`, `blade/`,
`libs/`, `devtools/` and the 2477-test corpus, exactly one site relied on the
implicit move: `sawc/std/json.saw:1316`, `return v` → `return move v` in
`JsonValue.parse`. That is the whole cost of the ruling, and it is the strongest
argument for it — the shape the ruling was worried about is essentially
unwritten in practice.

## What each fix actually is

With the funnel in place, all three are table entries:

* **SL-218** — `SelfExpr` joins `PRODUCER_READS`.
* **SL-219** — `TryExpr` joins `PRODUCER_PROJECTS` (→ `expr`), and
  `_check_value_transfer` stops returning early for a `try` after judging its
  catch arm, so the Ok projection reaches the tier arms. The arm's decision
  rides in the `try`'s own `delegates`, and the Ok path's Copy-tier duplication
  is recorded as `payload_needs_copy` so it is paid AT THE EXTRACTION and never
  on the catch handler's path — see "The review's P1" below, which is the one
  thing revision 1 got wrong.
* **SL-79** — the four wraps join `PRODUCER_REWRAPS`, and the checkpoint PEELS
  a rewrap ahead of everything, including the branch recursion (a wrap may sit
  around a branch as well as inside its arms, which is what lets the two rules
  compose). This subsumes the arm-wrap peel `_value_branch_arm_results` has
  done since DF-289d.

The one structural edit is that every exit of `_check_value_transfer` now
returns through a local `decide(...)` recorder, so no arm can forget the
sub-decisions a two-source node has already filed.
`tools/test_transfer_decisions.py` was taught about it **and** made to prove
that `decide` itself files through `_decide_transfer` — accepting it without
that would have been a hole the size of design 267's property.

## The review's P1: a merged result's copy obligation is per PATH

Revision 1 stamped the Ok projection's duplication as a node-level
`needs_copy`. A `try` produces its value on up to TWO paths, so that put ONE
obligation on the MERGED result: the enclosing transfer copied whatever came
out of the phi. On the Ok path that is right; on the Err path of an inline
`catch` the value is the HANDLER's, already transferred (and so already copied)
by its own `_generate_block`. Two retains, one release — an owning `Copy` value
leaked. Measured: `try r catch { fallback }` read `strong_count()` 3 where base
reads 2.

**The fix is design 131's discipline, not a new one.** The obligation now rides
`payload_needs_copy`, whose whole contract is that the retain happens AT THE
EXTRACTION rather than at the enclosing transfer site — which for a `try` means
inside the Ok block. A path that never extracts a payload cannot pay for one,
by construction rather than by a second rule. That is the same annotation and
the same reason `ForceUnwrap` uses it. The tier judgment, the refusals and the
diagnostics are untouched, so SL-219's Ok-path retain and refusal are exactly
as they were — which the review specifically warned against dropping.

Codegen gained one funnel, `_try_ok_payload`, whose docstring names its four
entry points (the four `try` variants). The `_force_synthesized_result` path —
a collection literal's synthesized Result, which has no `try` node at all —
deliberately does NOT go through it.

### Why only `try`, and the sweep that says so (obligation 4)

The defect is a MECHANISM — an obligation stamped on a node whose value arrives
on more than one path — so every other merging construct was probed with the
same oracle. None shares it, and the reason is structural: a value branch
returns `delegated` from the checkpoint and is never itself stamped (DF-299b),
so its arms stamp their OWN nodes and the obligation is per path by
construction. `try` is the only node that falls THROUGH that recursion to the
producer path, because it is the only one whose second result source is of a
different KIND — which is precisely why it was the only one that broke.

| Construct | Paths merged | Copies observed | Verdict |
|---|---|---|---|
| value `if` | two arms | 1 | clean — arms stamp themselves |
| value `match` | two arms | 1 | clean |
| `try { } catch { }` (block), try path | body tail | 1 | clean |
| `try { } catch { }` (block), catch path | handler tail | 1 | clean |
| `try?` Ok | payload | 1 | fixed by the same change |
| `try?` Err | `None` | 0 | clean |
| `??` present | payload read | 1 | clean — design 131 owns it |
| `??` absent | default operand | 1 | clean — entry point 18 owns it |
| **`try … catch`, Err, aliasing subject** | handler | **2 → 1** | **the bug** |
| **`try … catch`, Err, aliasing subject, fresh handler** | handler | **1 → 0** | **the bug** |

### The driven twin was the wider half

In a suspending body the subject is a frame-resident place whose read carries
its own retain, so the node-level stamp was a second copy on the **Ok** path
too — the driven twin printed `copy` twice on BOTH outcomes where the sync
matrix shows the Ok path clean. A fix validated only against the sync rows
would have looked complete and left half the driven ones leaking. That is the
concrete argument for the sync-AND-driven rule, and it is why V91 carries both.

(A `Result` with a NoCopy payload held across a suspension is refused by design
146's place rule before this question arises, so the driven rows use a
Copy-tier error type deliberately.)

## Diagnostics

Three of them changed, each because the old wording named a spelling that does
not work:

* **a `self` source** — "use `move` to transfer ownership instead" was a dead
  end: a borrowed receiver has nothing to move. It now says so and names the
  two real outs, `consumes` (design 260) or a duplicable policy and
  `self.copy()` — which is the wording V86's pin asked for.
* **a `try` source** — the value refused is the PAYLOAD but the storage that
  owns it is the SUBJECT, so a bare "use `move`" names nothing. It now spells
  `try move r` — probed: it compiles, and releases the payload exactly once. A
  FIELD subject gets the other half, since `move h.r` is the no-partial-moves
  refusal.
* **an auto-wrapped tail** — the refusal now anchors on the TAIL EXPRESSION
  rather than the function's declaration line, because the peel recurses with
  the operand's position. That is the diagnostic wart dogfood wave 1 recorded,
  fixed incidentally for the wrapped case.

## Consumer sweep (obligation 2)

`_is_aliasing_expr` has three consumers besides the checkpoint, each swept:

| Consumer | Effect of the new members |
|---|---|
| `_check_payload_read` (types.py) | a wrap/`try`/`self` never appears as an optional SOURCE; no change measured |
| `consumes._check_consuming_receiver` | `self.finish()` on a consuming method now asks for `(move self).finish()` instead of being treated as a temporary receiver. Correct — `self` IS a binding the caller owns — and unreached by the corpus |
| `expressions._match_binding_aliases` (DF-288a) | `SelfExpr` has its OWN arm ahead of the aliasing test, so it is untouched. `match (try! r)` now reads as a borrowed scrutinee, which is the conservative and correct answer |

The third row is also the evidence for the mechanism claim: DF-288a had to
hand-add `SelfExpr` to a second list asking the same question, and left a
comment saying a receiver "reaches neither the aliasing set below nor a scope
lookup". That comment is now false, and the arm can stay as the narrower rule
it is.

## SL-220 — probed, and NOT closed here

SL-220 is the *opposite* error at the same boundary: `(try! f()).x` over a
**fresh temporary** extracts a payload nobody registers a cleanup for, so it
LEAKS. Measured again on the fixed tree (`b_try.saw`'s control row): `temp 6`
prints and `drop 6` never runs, unchanged.

**It does not move with this unit, and the mechanism says why.** This unit fixes
the PRODUCER question — "does this expression name storage somebody else owns?"
— and SL-220's producer answer is already correct: the subject IS a fresh
temporary, `take` / `adopt-temporary` is the right decision, and design 267's
ledger records exactly that. What is missing is on the CLEANUP side: the
extraction consumes the container and the payload is adopted by nobody, so no
cleanup is registered on any path. No change to the aliasing classification can
reach it, because the classification is not wrong. It belongs with unit D
(SL-213, codegen's half), which is where SL-220's own filing hypothesised it.
Confirmed by probe rather than left as a hypothesis.

## Staging

1. This brief.
2. The funnel: `producers.py`, its gate, `_is_aliasing_expr` and the identity
   walk rewired, the `decide` recorder — plus the three fixes, the three XFAIL
   markers removed, the conformance rows, and the one-line corpus migration.

**Obligation 3 is satisfied by V86 and V87**, which unit A wrote as cited XFAIL
pins BEFORE this unit existed, precisely so the rows would state the rule ahead
of the fix; they lose their markers here. V88-V90 land WITH the mechanism rather
than ahead of it, and the reason is worth stating rather than eliding: V88's
last row states a RULING this unit made (an owned source is refused too), and
V89/V90 are the tier guard and the control — neither has anything to assert
until the fence exists. A row written ahead of a decision that had not been
taken would have been a guess, not an obligation discharged.

## Acceptance

* The three pins flip from XFAIL to passing and their markers are removed in
  the landing that fixes them.
* Every value-position node class is classified; the gate fails if one is not.
* The matrix above is covered row by row, with sync AND driven twins where the
  coroutine transform is in play, at `NoCopy` (the refusals), `Copy` (the
  retain-exactly-once guard) and the controls.
* A copy obligation is never shared between the paths of a multi-path result:
  V91 covers all eight `try`/`catch` cells plus the driven twins, V92 clears
  every other merging construct with the same oracle.
* Behaviour beyond the three findings is preserved: the only corpus change is
  the one-line ruling migration, and one test fixture whose own unrelated
  ownership mistake the fix exposed.

# Design 267 — the ownership boundary inventory, and a structured decision per transfer

**Unit A of SL-209** (the ownership-uniformity epic), filed as **SL-210**.
Plan steps 2 and 3. Landed Sep 9 2026.

> **The number 267 is PROVISIONAL.** It was the next free slot when the branch
> opened (266 was the highest brief); it is the lead's and the user's to
> confirm or renumber at integration.

## What this unit is for

SL-209's thesis is that ownership is not currently a *property of a transfer*.
It is a side effect of two facts that happen to line up: a syntax handler
remembering to call `_check_value_transfer`, and codegen re-deriving an answer
of its own from expression SHAPE when the handler did not
(`_transfer_needs_copy`). Where they agree, the program is correct by
coincidence. Where they disagree, the compiler has two opinions and no way to
notice.

The blocker to fixing that is not the checker — it is that **the checker leaves
almost no evidence**. It reports an error, or it stamps `needs_copy`, or it
does neither, and "did neither" covers both *checked and nothing owed* and
*never reached*. Every later unit of the epic needs those apart: unit D cannot
retire codegen's second opinion without knowing which transfers the front end
actually decided, and unit E's verifier has nothing to verify.

So this unit does two things and no more:

1. **INVENTORY** every ownership boundary and every producer, mapped to its
   implementation site and its conformance tests (step 2, below).
2. **RECORD** an explicit decision at each one (step 3).

It is **behaviour-preserving**. Same programs accepted, same programs rejected,
same diagnostics, same annotations, byte-identical IR. Nothing reads the new
record yet — that is units B through E.

## Step 2 — the inventory

### The two questions, kept apart

The epic's framing is that ownership at a transfer is two questions, and the
compiler has historically conflated them into one predicate:

* **WHERE** does the value acquire a new owner? — the *boundary*. A binding, an
  assignment, an argument, a return, an aggregate element, a capture, a loop
  result.
* **HOW** does the expression produce the value? — the *producer*. Existing
  storage, a fresh construction, an explicit move, a borrow, or the forwarding
  of another expression's result.

`_is_aliasing_expr` answers the producer question, and it answers it as a
**node-type test over four classes** (`Identifier`, `MemberAccess`,
`ArrayIndex`, `TupleIndex`) plus two hand-added transparencies (`ForceUnwrap`,
design 131; a forwarding `CastExpr`, DF-299a) and one hand-added exclusion
(`enum_variant_literal`, design 139). That shape is the whole reason producers
go missing: a node that reads out of existing storage and is not on the list
answers False, and **every** tier arm is gated on it, so a miss silently
converts an aliasing read into a fresh temporary at every tier at once. Both of
this unit's findings (SL-218, SL-219) are members of that class, and so were
DF-216a and DF-299a before them.

### The rule table (source → transfer into an owned destination)

This is the model the checkpoint now implements explicitly and records per
occurrence. The `action` column is the ledger's own vocabulary.

| Producer | Action | Cleanup-state change | Where it is decided |
|---|---|---|---|
| Fresh owned temporary (call result, construction, literal) | `take` | destination adopts the temporary's obligation | the `not aliasing` arm, ahead of every tier test |
| Existing value at the trivial (`free`) tier | `copy` | none — no destructor exists on either side | the fall-through arm; **this is the row that used to leave no trace at all** |
| Existing value at the silent `Copy` tier | `copy` | source RETAINS its own; destination gets a fresh obligation | the `implicit` arm; stamps `needs_copy` |
| Existing value at `ExplicitCopy` / `NoCopy` | `refused` | none | the `explicit` / `nocopy` arms; the author writes `.copy()` (→ a fresh temporary, so `take`) or `move` |
| Borrowed storage (`&x`, `&var x`, an escaping closure lent into a non-escaping slot) | `borrow` | none — borrowing grants no ownership | the `ReferenceExpr` and closure-lend arms |
| Explicit `move` | `move` | source's obligation RETIRED | the `MoveExpr` arm; `_check_move_expr` records the moved-from state (design 15) |
| Diverging or absent source | `none` | none | the `expr is None` arm, and the `Never` arm ahead of the fresh-temporary classification |
| A value BRANCH | `delegated` | none | recursed per arm (DF-299b); the arms' own keys are in `delegates` |
| A generic body's abstract tier | `deferred` | none yet | design 219 wave C raises a requirement; `pending` names the type parameters |

**Partial moves and `NoMove` are untouched.** Reaching the common checkpoint
does not make a projection movable: `move p.x` is still the design-35 refusal
(decided in `_check_move_expr`, not here), a `NoMove` value still moves exactly
once into its home (design 188's fresh-journey rule, decided at the move), and
the source-identity walk records a projection AS a projection (`kind =
projection`, non-empty `path`) precisely so a later unit cannot lose that
distinction by looking at the root alone.

### The boundary × producer matrix

Every entry point of `_check_value_transfer`, taken mechanically from the AST
(41 external call sites, plus the self-recursion). The checkpoint's docstring
carries the same list, grouped identically — that is obligation 1's funnel
requirement, and the two are meant to be diffed against each other.

#### Bindings

| Boundary | Context string | Site | Conformance |
|---|---|---|---|
| `let` / `var` initializer | `let binding` | `statements.py:_check_let_statement` | V09, V10, V21, V25, V26 |
| the design-151 explicit discard | `discard \`let _\`` | `statements.py:_check_let_statement` | V18 |
| destructuring `let (a, b) = …` | `destructuring binding` | `statements.py:_check_destructuring_let` | K77 (discard order) |
| a parameter's DEFAULT VALUE | `default parameter value` | `statements.py:_check_parameter_defaults` | W20-W24 (design 205's transfer positions) |

#### Assignment

| Boundary | Context string | Site | Conformance |
|---|---|---|---|
| every assignment target kind | *names the target* | `statements.py:_check_assign_rhs` | R43-R44, V08 |
| `x?.y = v` | `optional-chain assignment` | `expressions.py:_check_optional_chain_assign` | — (design 111's chain rows) |

#### Arguments — one arm per call shape the resolver can take

| Boundary | Site | Conformance |
|---|---|---|
| plain call, planned/labeled path | `expressions.py:_check_function_call` (×3) | V14, C10 |
| overload set's chosen candidate | `expressions.py:_finish_overloaded_args` | V14 |
| method / field / existential / static / module-qualified call | `expressions.py:_check_method_call`, `_check_field_call`, `_check_existential_method_call`, `_check_static_method_call`, `_check_module_function_call` | V51-V55 (consuming receivers) |
| erased `Box<any Trait>.make` | `expressions.py:_check_erased_box_make` | — |

#### Returns and tails

| Boundary | Site | Conformance |
|---|---|---|
| explicit `return` | `statements.py:_check_return_statement` | V47 |
| a body's TAIL | `_check_no_copy_return` → `_check_function` / `_check_method` / `_check_closure` | V82-V85 |

#### Aggregate elements

| Boundary | Context string | Site | Conformance |
|---|---|---|---|
| struct field, `init` argument | `struct field`, `init argument` | `expressions.py:_check_struct_init`, `_check_module_struct_init` | V13, V19 |
| enum payload | `enum payload` | `expressions.py:_check_enum_init` | V20, C05 |
| tuple / array / repeat / map / set element | `tuple element`, `array element`, `map key`, `map value`, `set element` | `expressions.py:_check_tuple_literal`, `_check_array_literal`, `_check_repeat_literal`, `_check_map_literal`, `_check_set_literal` | V22, C06 |

#### Captures

The capture boundary has **three modes and only one of them reaches the
checkpoint**, which is a fact about the boundary rather than a gap:

| Mode | Where it is decided | Note |
|---|---|---|
| `[move x]` | `_check_move_expr` directly | a move IS the ownership answer; the moved-from state is recorded there |
| `[copy x]` | an inline `_is_no_copy_type` test | the explicit-duplication spelling; probed legal at `ExplicitCopy` (`[copy bag]` deep-copies and both stay live) |
| plain `[x]` | `_check_value_transfer`, context `closure capture` | V12, V48, V49, V69, V74 |

#### Loop results

| Boundary | Context string | Site | Conformance |
|---|---|---|---|
| `break <value>` — the home is the LOOP's merged result | `break value` | `statements.py:_check_break_statement` | V77-V79 |

#### Operands that own

| Boundary | Context string | Site | Conformance |
|---|---|---|---|
| the `??` DEFAULT operand | `the default operand of \`??\`` | `expressions.py:_check_nil_coalesce` | D04 |

### The boundaries that reach a DIFFERENT funnel

Ownership is **not** one funnel today. It is three, split by SOURCE SHAPE, and
the inventory's job is to say so rather than to imply a uniformity that does
not exist. This is the single most important structural finding of step 2, and
it is what unit E's verifier will have to reconcile.

| Funnel | Owns | Entry points |
|---|---|---|
| `_check_value_transfer` (`types.py:4372`) | whole-value transfers | the 19 above |
| `_check_payload_read` (`types.py:3513`) | payload extraction out of an optional — `o!`, the `??` LEFT operand, an `if let` / `guard let` / `while let` binding | `_check_if_let_expr`, `_check_nil_coalesce` (×2), `_check_guard_let_statement`, and `_check_value_transfer`'s own `ForceUnwrap` arm |
| `place_uses._value_read_ok` (design 146) | a value read out of a `borrows` accessor's lent storage | the place lowering |

They use the same tier oracle (`Namespace.copy_tier` / `read_policy`) and agree
on outcomes, and each guards against the others firing on one read
(`_check_payload_read` declines when `_reads_a_place`; `_check_value_transfer`
hands `ForceUnwrap` over rather than judging it). But three funnels is three
places for a position to go missing, and only one of them now records a
decision. **Unit A records the transfer funnel's decisions and marks the other
two `delegated`** — the honest statement of what is and is not covered. Making
the payload and place rules produce decisions of their own is unit B/E work and
is called out here as the first thing that has to happen before the verifier
can claim completeness.

### The boundaries that reach NO funnel — this unit's findings

Three, each filed with measured compile-and-run evidence, none fixed here
(this unit is behaviour-preserving and every one of these fixes changes which
programs compile):

| Finding | Boundary | Symptom | Mechanism |
|---|---|---|---|
| **SL-218** | a `self` receiver read, at every destination | double free at exit 0 (NoCopy), SIGABRT (ExplicitCopy), CORRECT on `Copy` | `SelfExpr` is not in `_ALIASING_EXPR_TYPES` |
| **SL-219** | a `try` / `try!` / `try?` / `try…catch` over a binding or field | triple free at exit 0 | `TryExpr` is neither in the aliasing set nor transparent through to its subject |
| **SL-220** | a payload extracted from a fresh temporary inline | LEAK — the payload's `deinit` never runs | the extraction's result is adopted by nobody and no cleanup is registered |

SL-218 and SL-219 are **one mechanism, two sub-classes** — a node that IS a
read and is not in the set, and a node that FORWARDS a read and is not
transparent. SL-220 is the *opposite* error at the same boundary as SL-219
(cleanup not registered, rather than the producer misclassified) and is
hypothesised to belong with unit D.

Pinned: `examples/conformance/V86_self_receiver_read_is_a_transfer.saw` and
`V87_try_subject_read_is_a_transfer.saw`, both XFAIL, both citing their issue.
SL-220 gets no pin — the program exits 0 with correct output, so it needs an
oracle a `deinit`-counting example cannot supply on its own; scoping that is
the issue's own first task.

### The producer census — why the list above is believed complete

All 45 `Expression` subclasses were checked against "does this read out of
existing owned storage, or forward something that does". The result:

* **In the set, correctly:** `Identifier`, `MemberAccess`, `ArrayIndex`,
  `TupleIndex`.
* **Transparent, correctly:** `ForceUnwrap` (design 131), a `forwards_operand`
  `CastExpr` (DF-299a), the five value-branch nodes (DF-299b), and the three
  arm-wrap nodes the branch recursion peels.
* **Correctly excluded** (each BUILDS a value): every literal,
  `StringInterpolation`, `FormatPlaceholder`, `BinaryOp`, `UnaryOp`,
  `FunctionCall`, `MethodCall`, `StructInit`, `EnumInit`, `TupleLiteral`,
  `ArrayLiteral`, `MapLiteral`, `SetLiteral`, `ClosureExpr`, `RangeExpr`,
  `NoneLiteral`, `SourceLocationLiteral`, `LendVarLiteral`, a building
  `CastExpr`, and `enum_variant_literal`-marked `MemberAccess`.
* **Handled by their own arms:** `MoveExpr`, `ReferenceExpr`.
* **MISSING:** `SelfExpr` (SL-218), `TryExpr` (SL-219), and the auto-wrap
  family `OptionalWrap` / `ResultOkWrap` / `ResultErrWrap` / `ErasedErrWrap`
  outside a branch arm — **already filed as SL-79 (DF-305a)** and owned by
  unit B, which is why this unit adds no fourth issue for it.
* **Not producers:** `OptionalChain` / `BindOptional` / `OptionalEvalExpr`
  carry design 111's own final-field copyability rule (probed: a move-only
  final projection is refused by name), `OptionalChainAssign` types `Void?`,
  and `WhileExpr`'s value arrives through `break`, which is checkpointed.

### Scope limit of the record, stated rather than papered over

std's own bodies are type-checked **once**, under a separate builtin
typechecker, and the result is pickled into the std cache. A side table keyed by
occurrence is empty on a cache hit, so **the ledger covers the entry module, the
user modules, and every instance materialized into them — not std's own
authored bodies**. That is not a defect of the table; it is where std's checking
happens. Unit E has to decide whether its verifier runs against the builtin
typechecker too.

## Step 3 — the structured decision

`sawc/typechecker/ownership.py`.

### Shape

```
TransferDecision
  key            (source node_id | None, destination context, line, column)
  action         take | copy | move | none | borrow | refused | delegated | deferred
  source         SourceIdentity(kind, binding_id, path, display)
  destination    the checkpoint's `context` string
  site           (source file, line, column)
  cleanup        none | adopt-temporary | retain-source | retire-source
  tier           the copy tier consulted, when one was
  source_type / target_type
  pending        type-parameter names whose specialization still owes the answer
  delegates      the sub-occurrence keys, for a value branch
  reason         prose naming WHICH rule decided it
  is_return
  revision       how many passes have decided this occurrence
```

`SourceIdentity` is the "stable identity, not spelling" requirement:
`binding_id` is `VariableInfo.binding_id`, the same identity design 15's move
dataflow keys on, so two same-named bindings in different scopes are two
sources and a rename is none. `path` is the projection walked off that root,
which is what keeps a whole-binding transfer distinguishable from a field read
— i.e. what keeps the partial-move rule visible to a later unit. `display` is
diagnostics only and no rule may read it.

**IDENTITY IS CAPTURED WHERE THE NAME RESOLVES, NOT WHERE THE TRANSFER IS
RECORDED** (the SL-210 review's first finding). The first cut looked the
spelling up in `current_scope` at record time, which is a different scope: the
ledger reaches a body's TAIL and a value branch's ARM results *after* their
scopes have popped. That missed (a local tail recorded `binding_id=None`, and a
`move` tail recorded `retire-source` naming no source at all) and, worse, a
shadowed arm resolved to its own SHADOWER — an id no consumer could tell from
the truth. The identity is now stamped as a declared `resolved_binding_id`
annotation at the three places a binding-naming node resolves —
`_check_identifier`, `_check_move_expr`, and the one synthesized capture
`Identifier` in `_check_closure`, which runs with the enclosing scope
deliberately restored — and `_transfer_root_id` only reads it back. This is the
same rule `resolved_static_symbol` follows and for the same reason: resolution
is scope-sensitive, so the answer must be recorded by the pass that had the
scope. `None` now means "not a local binding", never "not looked up".

That is an ANNOTATION rather than a ledger field because it is a property of
the EXPRESSION (which binding does this name mean?), not of the boundary — the
same altitude as `resolved_type`. The decision record stays a side table for
the reasons above; what moved onto the node is the one fact the node itself
answers.

### Why a side table, and why it is an OCCURRENCE record

Evaluating an expression and transferring its result are different operations,
so the decision may not ride the expression node: an annotation is a property of
the VALUE, a decision is a property of the BOUNDARY it crosses. The key is
therefore the boundary; the node id is in it only to NAME which occurrence,
which it can do because an AST node occupies exactly one operand slot.

Three properties follow from the table living outside the AST, and each is a
reason it is a table rather than an `annotation(...)` field:

* `dataclasses.fields()` does not see it — so the design-126 AST contract has
  nothing to declare (the `astgraft` lane is satisfied by construction) and
  `substitute_ast_types` has nothing to walk. A decision holds `SawType`s
  correct for the body it was made in, and a monomorphized clone must not
  inherit them.
* `deepcopy` gives a clone fresh `node_id`s, so an instantiation's transfers are
  new occurrences with their own decisions.
* it is per-compile, so nothing survives into a second compilation — which is
  what keeps the `reemit` and `irdet` byte-identity gates unaffected.

**Assign, never accumulate** (design 218 stage 1's rule at this table): the
front half runs more than once over one AST, so a later pass REPLACES an
earlier decision for the same occurrence and `revision` counts the passes. The
last check is the answer, exactly as for `payload_needs_copy`.

### What makes "checked" different from "unchecked"

The presence of a ledger entry, and nothing else. Every exit path of
`_check_value_transfer` returns `self._decide_transfer(...)`; there is no path
that reports nothing. That is enforced **statically** by
`tools/test_transfer_decisions.py`, which parses the function and fails on a
bare `return`, a `return` of anything that is not a recorded decision, or a
function that can fall off its end. A prose promise would rot at the next edit;
the parse will not.

### The sibling sweep on "resolved in the wrong scope" (obligation 4)

The review's first finding is a MECHANISM — a fact resolved against ambient
state that has moved on since the fact was knowable — so the ledger path was
swept for others. There are none left, and the reason is a clean line rather
than luck:

* The identity walk now reads only NODE-LOCAL facts, each stamped by the pass
  that owned the question: `node_id` (fixed at construction), `place_struct`,
  `unwrap`, `forwards_operand`, `enum_variant_literal`, and the new
  `resolved_binding_id`. No scope lookup remains in `ownership.py`.
* PROJECTIONS were the most likely sibling — `h.tag` in an arm tail is rooted
  at a binding whose scope has also popped — and they are covered by
  construction: the walk descends to the ROOT node, which carries its own
  stamp. Asserted, not assumed (`projection_tail_names_its_root`).
* The DESTRUCTURING path passes `stmt.value`, which is checked in the enclosing
  scope while that scope is still current, so it was never exposed.
* The two remaining pieces of ambient state a decision reads —
  `_transfer_source_file()` (`current_method` / `current_function`) and the
  abstract arm's `pending` (`current_type_params`) — are DECLARATION-scoped,
  and every `_check_value_transfer` call happens inside the declaration being
  checked. Block scopes pop mid-check; declaration state does not. That is the
  line: a fact keyed to the enclosing DECLARATION is stable across the whole
  window the ledger runs in, and a fact keyed to a BLOCK is not.

### Cost

+2.5% on a small compile (1.752s → 1.796s, 9 samples each), flat on a large one
(3.203s → 3.073s, within noise). ~9k decisions for a small program, ~23k across
the harness's ten fixtures.

## Acceptance

* Every successful ownership boundary carries an explicit decision, **including
  trivial copies** — the `free`-tier fall-through is now an explicit `copy`
  record, and the fresh-temporary path an explicit `take`.
* The inventory is checked in (this file) and maps each boundary and producer
  to its implementation site and its conformance tests.
* `_check_value_transfer`'s docstring names its 19 entry points (obligation 1).
* Conformance rows V86 and V87 were written before the refactor (obligation 3).
* Behaviour-preserving: no diagnostic, annotation, accepted program or rejected
  program changed.

## What this unit deliberately did NOT do

* Fix SL-218, SL-219 or SL-220. Each changes which programs compile and owes a
  corpus sweep and a tier-blindness argument (V62/V65's lesson: fence every
  tier, not only the owning ones).
* Touch `_transfer_needs_copy`. Codegen still holds its second opinion; that is
  unit D, and it now has explicit decisions to migrate onto.
* Give the payload-read or place funnels decisions of their own. Unit B/E.
* Add a verifier. Unit E — the ledger is what it will verify.

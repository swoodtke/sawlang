"""design 275 U2 — THE SHAPE TABLE. No silent decline, ever.

THE GUARANTEE (designs 96 / 101 / 104): a suspending call EMBEDS at any nesting
depth and control-flow position, or ERRORS cleanly — it never silently blocks.
Until this unit there was a THIRD outcome. A callee or a closure body the
discovery walk declined was lowered as a PLAIN CALL, and what happened next
depended on which face of the suspension it was: an io park reached codegen's
out-of-frame fallback and BLOCKED the cooperative executor's own OS thread
(SL-287, measured — not one timer tick fired for the whole block), and a
`yield_now()` was simply dropped (`__saw_drive_steps` reporting 0 where 1 was
owed, SL-316). Nothing said a word at compile time or at run time.

U1 made every one of those decisions VISIBLE — `FrameLedger` records a
`FrameRow` per callee and a `SiteRow` per suspension position, and
`--emit-frame-ledger` dumps both. U2 deletes the third outcome: for every SHAPE
a suspension can sit in, this table says SPLIT, HOIST, INLINE, EMBED or REFUSE,
and a shape the table does not classify is an INVARIANT FAILURE naming the AST
class — never a plain call.

THE FUNNEL (obligation 1). This module is the ONE chokepoint every
split / hoist / refuse decision goes through, and the census below names its
consumers. Before it, the same question was answered by a hand-written
`isinstance` chain in `_collect_calls`, a second one in `_hoist_container_heads`,
a third in `ast_walk.control_blocks`, and twenty-one refusal messages scattered
across `coro_transform.py` — which is how a container (`TryCatchExpr`, DF-193a)
and a container HEAD (design 224's `match` scrutinee, DF-224a) each came to be
skipped in silence by a walk that listed every OTHER one.

  | consumer | what it asks |
  |---|---|
  | `_FrameBuilder._collect_calls` | `container_of` — which blocks to descend, and the REFUSE row for one it must not |
  | `_FrameBuilder._collect_calls` (the invariant) | `unclassified_container` — a container class with no row, ICE naming it |
  | `_FrameBuilder._reject_buried_suspend_call` | `refusal_of` — THE message for a REFUSE row, anchored at the shape's introducer |
  | `_FrameBuilder._hoist_container_heads` | `HEADS` — every head slot design 224 lifts |
  | `coro_transform._verify_site_coverage` | `container_of` + `STATEMENTS` — totality check (a) |
  | `tools/test_coro_shapes.py` (the `corototality` lane) | the whole table, against `ast_walk.CONTAINER_KINDS` |

THE THREE DISPOSITIONS, and why five names rather than three. The brief's
vocabulary is SPLIT / HOIST / REFUSE, which is the right split for a shape that
CONTAINS a suspension. A shape that IS one needs two more names, because the
transform does two different things with it and the dump already spells them:
`INLINE` (a suspend primitive, a channel receive, a blocking-extern offload —
lowered into THIS frame) and `EMBED` (a callee frame embedded by value, design
44). Both are "the statement is already a state boundary"; keeping them apart is
what lets a SiteRow's outcome be read straight off the table.

CONTEXTS. A shape's disposition is not the whole answer: the same shape is
SPLIT in a driven body and REFUSE inside a closure literal. `disposition_in`
takes the six contexts `coro_ledger.CONTEXTS` names — the three a FRAME plays
(driven root, embedded, spawned) share one column, and the other three
(closure body, sync body, Thread body) are uniform refusals whose rejector is
named per row.
"""

from typing import NamedTuple, Optional

from ast_nodes import (ClosureExpr, ExpressionStatement, ForLoop,
                       GuardLetStatement, IfExpr, IfLetExpr, LetStatement,
                       MatchExpr, ReturnStatement, ScopedBlock, TryCatchExpr,
                       TryExpr, WhileExpr)


# --------------------------------------------------------------------------- #
# The dispositions
# --------------------------------------------------------------------------- #

SPLIT = "SPLIT"      # CFG-split into resume states by the named `_split_*`
HOIST = "HOIST"      # lifted to a driven statement by the named hoist (design 120/224)
INLINE = "INLINE"    # the suspension lowers into THIS frame (no callee frame)
EMBED = "EMBED"      # the callee's frame is embedded by value and driven (design 44)
REFUSE = "REFUSE"    # one rejector, one message, anchored at the shape's introducer

DISPOSITIONS = (SPLIT, HOIST, INLINE, EMBED, REFUSE)


class ShapeRow(NamedTuple):
    """One SHAPE: a syntactic slot a suspension can sit in, and its answer.

    `node` is the AST class name and `slot` the field — together they are the
    shape's NAME, which is what a conformance row and a SiteRow's reader can
    both say. `handler` names the routine that implements the disposition, so a
    reader of the table can go straight to it; `guard` names the stamp the
    transform must find before a SPLIT row applies (a `None` guard is
    unconditional). `reason` and `issue` belong to a REFUSE row and are what the
    one rejector renders.
    """
    node: str
    slot: str
    disposition: str
    handler: str
    guard: Optional[str] = None
    unguarded: Optional[str] = None     # SPLIT rows: why an unstamped one refuses
    reason: Optional[str] = None        # REFUSE rows: the message body
    issue: Optional[str] = None         # REFUSE rows: the tracker id pending it
    template: Optional[str] = None      # REFUSE rows: the exact text, `{name}`/`{what}`


# --------------------------------------------------------------------------- #
# CONTAINER BLOCKS — a suspension written inside a construct's own Block
# --------------------------------------------------------------------------- #
#
# Paired one-for-one with `ast_walk.CONTAINER_KINDS`, and `tools/test_coro_shapes.py`
# fails when the two lists diverge: a container nothing classifies is exactly
# the gap DF-193a and DF-224a were, and it must not be possible to add one
# without answering this table.

_IFLET_UNGUARDED = (
    "an `if let` / `guard let` whose binding the split preparation "
    "(`_mark_optional_binding_splits`) did not mint a frame field for cannot "
    "become a resume target — its binding exists nowhere else")

CONTAINERS = {
    IfExpr: ShapeRow("IfExpr", "then_branch/else_branch", SPLIT, "_split_if"),
    IfLetExpr: ShapeRow("IfLetExpr", "then_branch/else_branch", SPLIT,
                        "_split_if_let", guard="_coro_split",
                        unguarded=_IFLET_UNGUARDED),
    GuardLetStatement: ShapeRow("GuardLetStatement", "else_branch", SPLIT,
                                "_split_guard_let", guard="_coro_split",
                                unguarded=_IFLET_UNGUARDED),
    WhileExpr: ShapeRow("WhileExpr", "body", SPLIT, "_split_while"),
    # SL-317 (design 275 U3) gave the OTHER `for` its split, and it is the same
    # split: a spanning collection `for` is REWRITTEN into the `while let` it
    # denotes (`_normalize_collection_for`) — the iterator a `let` ahead of the
    # loop, the head a `next()` at the loop top — so `_split_while`'s
    # conditionless form and `_split_if_let`'s marked binding do the work, and
    # the iterator's residency in the frame is `_collect_frame_locals`'s. Design
    # 233 lowered `while let` to that same pair in the parser for the same
    # reason: the rules already existed, so the construct gets them by BEING
    # what it means rather than by a second copy. `_split_for` therefore serves
    # the RANGE form alone, and a collection `for` reaching it is an invariant
    # failure, not a refusal — which is what retiring `SPLIT_LIMITS` records.
    ForLoop: ShapeRow("ForLoop", "body", SPLIT,
                      "_split_for (range) / _normalize_collection_for "
                      "+ _split_while + _split_if_let (collection)"),
    MatchExpr: ShapeRow("MatchExpr", "arms[].body", SPLIT, "_split_match"),
    # SL-333: the `#lend_var` fold's selected branch. One block, always
    # entered, so the split is the simplest of the set — no condition to
    # evaluate, no branch, no merge. It carries a row because it OWNS A BLOCK
    # and the enumeration is total; a `borrows` body is `sync` (design 141's
    # v1 fence), so no suspension can sit in one today and the splitter is the
    # shape table's answer rather than a path the corpus walks.
    ScopedBlock: ShapeRow("ScopedBlock", "block", SPLIT,
                          "_split_scoped_block"),
    TryCatchExpr: ShapeRow("TryCatchExpr", "try_block/catch_block", SPLIT,
                           "_split_try_catch", guard="_is_split",
                           unguarded="a `try { } catch { }` that neither spans "
                                     "a suspension nor carries a jump out of an "
                                     "enclosing spanning loop lowers in place"),
    # SL-215 (design 275 U3) gave the INLINE `try EXPR catch { … }` its split,
    # and it is the block form's: an inline catch whose catch block SPANS a
    # suspension, or carries a `break`/`continue` for an enclosing spanning
    # loop, is REWRITTEN into `try { try EXPR } catch { … }`
    # (`_normalize_inline_catch`) ahead of every hoist and marking pass, at
    # every child position the write-side walk reaches (codex r3 #1 found the
    # call-argument, struct-field and map-entry positions walked past), so
    # `_split_try_catch` does the work and the two spellings agree. An inline
    # catch that reaches `_collect_calls` unrewritten is one the normalization
    # LEFT in place — its catch neither spans nor jumps, and its subject is
    # hoisted like any `try`'s (`_maybe_hoist_try` / the ANF hoist) — so the
    # row is unconditional: descending its catch block embeds and refuses
    # exactly what the enclosing walk would, and finds nothing there by
    # construction. This row was REFUSE pending SL-215 for one unit.
    TryExpr: ShapeRow("TryExpr", "catch_block", SPLIT,
                      "_normalize_inline_catch + _split_try_catch"),
    # The one REFUSE row. It names the issue that OWNS the missing split, so
    # the message an author reads is a pointer rather than a dead end.
    ClosureExpr: ShapeRow(
        "ClosureExpr", "body", REFUSE, "_reject_buried_suspend_call",
        reason="a closure body is not driven — it is called through a function "
               "value, and a suspension there has no frame to park in",
        issue="SL-316",
        # THE WORDING IS LOAD-BEARING and predates this table (design 223 unit
        # 3, widened by SL-306): three `examples/errors/` rows assert
        # `appears inside a CLOSURE BODY in driven `X``, and the message says
        # the limit the author can act on rather than naming two constructs
        # their program does not contain. Moved here rather than reworded, so
        # the table owns the text without the flip costing a diagnostic.
        template=(
            "coroutine transform: the suspending call {what} appears inside a "
            "CLOSURE BODY in driven `{name}`, and a closure body is not "
            "driven — its suspension has no frame to park in. Call it outside "
            "the closure and pass the result in, or move the whole closure "
            "body into a named function the driven body calls.")),
}


# --------------------------------------------------------------------------- #
# CONTAINER HEADS — the expression a construct evaluates outside all its blocks
# --------------------------------------------------------------------------- #
#
# design 224 (DF-224a): every one of these is HOISTED into a preceding driven
# `let` by `_hoist_container_heads`, and a head that still spans a suspension
# when `_collect_calls` runs is refused by `_reject_container_head` — never
# descended past, which is what left a `Channel.receive()` in a `match`
# scrutinee spinning at 100% CPU. Paired with `ast_walk.CONTAINER_HEADS`.

HEADS = {
    (IfExpr, "condition"): ShapeRow("IfExpr", "condition", HOIST,
                                    "_hoist_container_heads"),
    (WhileExpr, "condition"): ShapeRow("WhileExpr", "condition", HOIST,
                                       "_hoist_suspending_conditions"),
    (IfLetExpr, "optional_expr"): ShapeRow("IfLetExpr", "optional_expr", HOIST,
                                           "_hoist_container_heads"),
    (GuardLetStatement, "optional_expr"): ShapeRow(
        "GuardLetStatement", "optional_expr", HOIST, "_hoist_container_heads"),
    (ForLoop, "iterable"): ShapeRow("ForLoop", "iterable", HOIST,
                                    "_hoist_container_heads"),
    (MatchExpr, "matched_expr"): ShapeRow("MatchExpr", "matched_expr", HOIST,
                                          "_hoist_suspending_match"),
}


# --------------------------------------------------------------------------- #
# STATEMENT shapes — the suspension IS the statement
# --------------------------------------------------------------------------- #
#
# The three forms every classifier in `coro_transform.py` matches, spelled once
# here: `let x = <call>`, a bare `<call>` (or `let _ = <call>`), and — after
# design 83's tail normalization — `return <call>`. Which of INLINE and EMBED a
# row gets is decided by the CALLEE, not by the statement, so both live on the
# one row and `site_outcome` picks.

_BLOCKING_EXTERN_ROW = ShapeRow(
    "LetStatement", "value (blocking extern)", INLINE, "_emit_blk_call")

# The one cell of the context matrix a `Thread.spawn { }` body PERMITS rather
# than refuses (design 242 ruling 9) — see `disposition_in`.
BLOCKING_IN_THREAD_BODY = _BLOCKING_EXTERN_ROW

STATEMENTS = (
    ShapeRow("LetStatement", "value", EMBED, "_classify_call/_classify_method_call"),
    ShapeRow("ExpressionStatement", "expression", EMBED,
             "_classify_call/_classify_method_call"),
    ShapeRow("ReturnStatement", "value", EMBED,
             "_classify_call/_classify_method_call"),
    ShapeRow("ExpressionStatement", "expression (suspend primitive)", INLINE,
             "_suspend_to"),
    ShapeRow("LetStatement", "value (Channel.receive)", INLINE, "_emit_recv_call"),
    _BLOCKING_EXTERN_ROW,
)

_STATEMENT_SLOTS = {
    LetStatement: "value",
    ExpressionStatement: "expression",
    ReturnStatement: "value",
}


# --------------------------------------------------------------------------- #
# EXPRESSION shapes — design 224's matrix, one row
# --------------------------------------------------------------------------- #
#
# design 120 gave EVERY expression position an ANF hoist and design 224 widened
# it to container heads and container literals. One row rather than thirty,
# because the hoist is ONE pass with one rule (lift the suspending subexpression
# into a preceding driven `let`, preserving evaluation order and short-circuits)
# and the thirty positions are its input, not thirty decisions. A position the
# hoist cannot lift reaches `_reject_buried_suspend_call`, which is the same one
# rejector this table's REFUSE rows use.

EXPRESSIONS = ShapeRow("Expression", "any operand / argument / receiver / "
                                     "interpolation / short-circuit RHS",
                       HOIST, "_anf_hoist")


# --------------------------------------------------------------------------- #
# The read API
# --------------------------------------------------------------------------- #

class UnclassifiedShape(Exception):
    """A container the shape table has no row for hosts a suspension.

    An INVARIANT FAILURE, never a soft answer — the whole point of the table is
    that a NEW AST shape fails the coverage check until it is classified, rather
    than joining `_collect_calls`'s `isinstance` chain's silent fall-through.
    `sawc.py` reports it through `_report_ice`, so it reads as design 192 unit
    2's ordinary internal-compiler-error line with the AST class in it.
    """


def container_of(ctrl):
    """The row for the control-flow construct `ctrl`, or None when `ctrl` is not
    a container at all (a leaf statement, an ordinary expression).

    THE dispatch `_collect_calls` runs on. A `None` answer for a node that owns
    a `Block` is the invariant failure `unclassified_container` raises.
    """
    return CONTAINERS.get(type(ctrl))


def unclassified_container(ctrl, owns_blocks):
    """Raise when `ctrl` owns blocks and this table classifies nothing for it.

    `owns_blocks` is the caller's `ast_walk.control_blocks(...)` answer, passed
    in rather than recomputed so the two enumerations are compared rather than
    trusted: a construct `control_blocks` descends and this table does not name
    is precisely the gap the unit exists to close.
    """
    if not owns_blocks or type(ctrl) in CONTAINERS:
        return
    raise UnclassifiedShape(
        f"the coroutine shape table classifies no disposition for "
        f"`{type(ctrl).__name__}`, which owns a block a suspension was found "
        f"in. Every shape a suspension can sit in is SPLIT, HOIST, INLINE, "
        f"EMBED or REFUSE — a shape with no row is a coverage gap, never a "
        f"plain call (design 275 U2). Add its row to `sawc/coro_shapes.py`.")


def head_of(owner, field):
    """The row for one container HEAD slot, or None."""
    return HEADS.get((type(owner), field))


def statement_slot(stmt):
    """The field of `stmt` a top-level suspending call sits in, or None."""
    return _STATEMENT_SLOTS.get(type(stmt))


def refusal_of(row, name, what):
    """THE message a REFUSE row renders, anchored at the shape's introducer.

    ONE text per row, built here so the twenty-one scattered refusal messages
    the design-275 census counted cannot grow a twenty-second that words the
    same limit differently. `name` is the driven body's, `what` names the
    offending call the way the author wrote it. A row without a `template`
    gets the generic sentence, which names the shape, the reason and — when the
    missing capability has an owner — the issue that is pending it, so a
    refusal is a pointer rather than a dead end.
    """
    if row.template:
        return row.template.format(name=name, what=what)
    tail = (f" This is pending {row.issue}." if row.issue else "")
    return (f"coroutine transform: the suspending call {what} appears in a "
            f"`{row.node}` {row.slot} inside driven `{name}`, and {row.reason}."
            f"{tail}")


def unbuildable_message(name, callee, reason, issue=None):
    """THE message for a callee the ledger recorded as UNBUILDABLE — SL-287.

    The third outcome's own row. A callee whose frame discovery could not build
    used to be lowered as a PLAIN CALL from inside a driven body: the park then
    reached codegen's out-of-frame fallback and stopped the cooperative
    executor's own OS thread, or a `yield_now()` was dropped and the task never
    ceded. Neither said anything. The refusal names the callee AND the ledger's
    own recorded reason, because "no frame was built" without the why is the
    diagnostic that sent three previous readers to the wrong end of the
    pipeline.
    """
    tail = (f" This is pending {issue}." if issue else "")
    return (f"coroutine transform: the suspending call `{callee}(...)` inside "
            f"driven `{name}` has no coroutine frame to embed — {reason}. A "
            f"suspending call embeds or errors; it never silently blocks "
            f"(designs 96/101/104).{tail}")


def disposition_in(row, context):
    """The disposition of `row` in one of `coro_ledger.CONTEXTS`.

    The three FRAME roles — driven root, embedded, spawned — share the row's own
    answer: a frame is a frame, and design 44 embeds a callee's by value
    whichever role its caller plays. The other three are refusals and each names
    the rule that refuses it, so the matrix has a value in every cell rather
    than a blank the reader has to interpret.

    ONE CELL IS NOT A REFUSAL, and it is the exception design 242 ruling 9
    wrote: a `Thread.spawn { }` body may call a `blocking` extern, which runs as
    a PLAIN CALL there and blocks that thread on purpose (the reason to spawn
    one). It is not a shape exception — every shape in this table is refused in
    a thread body — it is a CAUSE exception, and `BLOCKING_IN_THREAD_BODY`
    records which row it lands on so the matrix does not quietly overstate the
    rule.
    """
    if context in ("driven root", "embedded", "spawned"):
        return row.disposition
    if context == "closure body":
        return REFUSE           # this table's ClosureExpr row
    if context == "sync body":
        return REFUSE           # the typechecker's `sync` check
    if context == "Thread body":
        if row is BLOCKING_IN_THREAD_BODY:
            # design 242 ruling 9: a plain call, blocking that thread.
            return INLINE
        return REFUSE
    raise UnclassifiedShape(
        f"the coroutine shape table knows no context `{context}` "
        f"(design 275 U2; the six are `coro_ledger.CONTEXTS`)")


def all_rows():
    """Every row, for the gate lane and for the dump's header."""
    return (tuple(CONTAINERS.values()) + tuple(HEADS.values())
            + tuple(STATEMENTS) + (EXPRESSIONS,) + PENDING_SL322)


# --------------------------------------------------------------------------- #
# The two CALL SHAPES design 44's by-value frame embedding cannot serve
# --------------------------------------------------------------------------- #
#
# design 275 §3 RULING 2 (user, Sep 18). Neither of these is a position — they
# are shapes of the CALLEE, and both are REFUSE for the same structural reason:
# a frame is a compile-time identity embedded BY VALUE in its caller's, and
# neither of these has one. An `any Trait` dispatch has a vtable word where the
# identity would be; a suspending CYCLE has no finite embedded size at all.
#
# They are rows here because the ruling is that the refusal is PENDING, not
# permanent: both need a heap-allocated frame with an indirect resume, which is
# one design and one carrier — SL-322 — so neither lands alone. The table
# records that, each message names it, and `tools/test_coro_shapes.py` fails if
# the row and the message stop agreeing.

PENDING_SL322 = (
    ShapeRow(
        "AnyTraitDispatch", "a suspending conformance body", REFUSE,
        "typechecker._report_existential_suspend_dispatch",
        reason="a frame is a compile-time identity and dynamic dispatch has "
               "only a vtable word, so the callee's frame cannot be embedded "
               "in the caller's",
        issue="SL-322"),
    ShapeRow(
        "SuspendingCycle", "a suspending-call cycle", REFUSE,
        "_analyze_nesting",
        reason="the flat-frame model embeds callee frames by value, so a cycle "
               "has no compile-time frame size",
        issue="SL-322"),
)

#: The two rows above, by the name a consumer renders from.
PENDING_DISPATCH, PENDING_RECURSION = PENDING_SL322


def pending_note(row):
    """The sentence a REFUSE row pending a design adds to its message.

    ONE spelling, so the K37 refusal and the suspending-recursion refusal cite
    the carrier identically — which is the whole of ruling 2's "the refusal
    naming it", and what a reader greps for when SL-322 lands.
    """
    return (f"This refusal is PENDING {row.issue}, the heap-allocated-frame "
            f"design: an existential dispatch of a suspending body and "
            f"suspending recursion both need a heap frame with an indirect "
            f"resume, so the two land together and neither alone.")


# --------------------------------------------------------------------------- #
# The sub-shapes a SPLIT routine has no split for
# --------------------------------------------------------------------------- #
#
# A SPLIT row says the container CAN become resume states, and for one container
# that was true of some of its spellings and not all. Recording the exception
# here rather than leaving it inside the routine is what kept the table honest:
# a reader of the `ForLoop` row learned the limit from the table, and the
# routine that raised named the same issue the row did. Each entry is
# `(node, sub-shape, issue, what it would take)`.
#
# EMPTY as of design 275 U3 (SL-317), and deliberately kept rather than deleted:
# the ONE entry it ever held was the collection `for`, and its emptiness is the
# statement that every SPLIT row now splits every spelling of its container.
# `tools/test_coro_shapes.py` reads it, so a new limit has a place to be
# declared instead of a `raise` inside a routine nothing enumerates.

SPLIT_LIMITS = ()

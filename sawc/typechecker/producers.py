"""The PRODUCER taxonomy — how an expression produces the value it hands on.

Design 269 (SL-211, unit B of the SL-209 ownership-uniformity epic).

THE PROBLEM THIS SOLVES. Design 267 split ownership at a transfer into two
questions: WHERE the value acquires a new owner (the boundary, which
`_check_value_transfer`'s entry-point list enumerates) and HOW the expression
produced it (the producer). The second question was answered by
`_is_aliasing_expr` as a NODE-TYPE TEST over an enumerated class list — four
classes, plus transparencies and exclusions added BY HAND as each missing one
was found. That shape has exactly one failure mode, and it produced every
finding in this family:

  * DF-216a — compiler-synthesized call constructions skipped the checkpoint;
  * DF-299a — a forwarding `CastExpr` was not transparent (hand-added);
  * design 131 — `ForceUnwrap` was not transparent (hand-added);
  * design 139 — `enum_variant_literal` was wrongly aliasing (hand-excluded);
  * DF-288a — `SelfExpr` had to be hand-added to the *borrowed-scrutinee* list,
    a SECOND list asking the same question;
  * SL-218 — `SelfExpr` is not in the aliasing set (double free);
  * SL-219 — `TryExpr` is not transparent to its subject (triple free);
  * SL-79 / DF-305a — the four auto-wraps are not transparent (double free).

A node that reads out of existing storage and is not on the list answers False,
and EVERY tier arm of the checkpoint is gated on that answer — so one missing
member silently converts an aliasing read into a fresh temporary at every tier
at once. NoCopy and ExplicitCopy skip their refusal (a double free) and the
`Copy` tier skips its `needs_copy` stamp (an unretained second owner, a
refcount underflow). The fence is TIER-BLIND for that reason.

THE FIX IS THE SHAPE, NOT THE MEMBERS. This module answers the producer
question as a TOTAL classification over every node that can occupy a VALUE
POSITION, and `tools/test_producer_taxonomy.py` fails the build when one is in
no bucket. A new expression form cannot be added without saying how it produces
a value — which is the SL-209 completion criterion ("a new expression form
cannot silently bypass ownership checking") reached, for this half, by
construction.

THE UNIVERSE IS NOT "THE `Expression` SUBCLASSES", and getting that wrong is
its own version of the same bug. It is every `Expression` subclass PLUS every
node declaring a `result_type` — which is what promotes a `Statement` into a
value position. Exactly one class is in the second group and not the first:
`ForLoop`, whose `let n = for i in 0..3 { ... }` spelling reaches the
checkpoint. Design 267's census enumerated the 45 `Expression` subclasses, so
it could not see that one; the gate enumerates the union.

THE FIVE KINDS. Each answers "what does a new owner receive from this node?"

  READS      — the node DENOTES storage an existing owner keeps. Transferring
               one leaves a live second owner behind, so this is exactly where
               move-discipline is enforced and where `Copy` must retain.
  PROJECTS   — the node names a PART of such storage: `o!`, a forwarding
               `r as Res`, the Ok payload of `try r`. The node's own type is
               the type transferred; the ALIASING answer comes from the
               operand, because the storage under it is what has an owner.
  REWRAPS    — the node RE-TYPES its operand without touching the value: the
               four auto-wraps the return/tail ladder inserts. The transfer to
               judge is the OPERAND's, at the operand's own type, which is
               where the author's `move` goes.
  BRANCHES   — the node's value is one of several arm results (DF-299b). One
               transfer PER ARM, judged where each arm is written.
  BUILDS     — a fresh value the reader already owns: a literal, a call
               result, a construction, an operator result.
  OWN_ARM    — `move x` and `&x` are answered by the checkpoint's own arms
               ahead of the producer question, because they state the
               ownership answer rather than producing a value.

ONE NODE IS IN TWO BUCKETS, DELIBERATELY. `TryExpr` PROJECTS its Ok value out
of its subject's storage AND BRANCHES into its catch handler; those are two
result sources with two different rules, which is the whole of SL-219 (the
catch arm was judged by DF-299b's recursion and the subject was not). The gate
knows about this one overlap by name and rejects any other.

TWO CLASSIFICATIONS ARE CONDITIONAL, and the condition is an annotation the
typechecker stamped, because only it can tell the two spellings apart:

  * `MemberAccess` READS, unless `enum_variant_literal` — `Slot.Empty` wears
    the same node type as `config.slot` but builds a value out of nothing
    (design 139);
  * `CastExpr` PROJECTS, unless it is not `forwards_operand` — an integer
    conversion, a raw enum tag and an address reinterpretation each BUILD a
    new scalar, which is what keeps this from taxing the unsafe-tier pointer
    idioms (DF-299a).

WHAT THIS MODULE IS NOT. It does not decide whether a transfer is legal — that
is the checkpoint's tier question, and it is asked only after this one is
answered. It holds no state and reads no scope; every input is the node and the
annotations already stamped on it, which is what lets the identity walk in
`ownership.py` share it (the two used to maintain parallel transparency lists
and had to be kept in step by hand).
"""

from typing import Callable, Dict, FrozenSet, Optional, Type

from ast_nodes import (
    ArrayIndex, ArrayLiteral, BinaryOp, BindOptional, BoolLiteral, CastExpr,
    ClosureExpr, EnumInit, ErasedErrWrap, Expression, FloatLiteral, ForLoop,
    ForceUnwrap, FormatPlaceholder, FunctionCall, Identifier, IfExpr,
    IfLetExpr, IntLiteral, LendsExpr, LendVarLiteral, MapLiteral, MatchExpr,
    MemberAccess,
    MethodCall, MoveExpr, NilCoalesce, NoneLiteral, OptionalChain,
    OptionalChainAssign, OptionalEvalExpr, OptionalWrap, RangeExpr,
    ReferenceExpr, ResultErrWrap, ResultOkWrap, ScopedBlock, SelfExpr,
    SetLiteral, SourceLocationLiteral, StringInterpolation, StringLiteral,
    StructInit, TryCatchExpr, TryExpr, TupleIndex, TupleLiteral, UnaryOp,
    WhileExpr,
)


# ---------------------------------------------------------------------------
# THE KINDS.
# ---------------------------------------------------------------------------

READS = 'reads'
PROJECTS = 'projects'
REWRAPS = 'rewraps'
BRANCHES = 'branches'
BUILDS = 'builds'
OWN_ARM = 'own-arm'

KINDS = (READS, PROJECTS, REWRAPS, BRANCHES, BUILDS, OWN_ARM)


# ---------------------------------------------------------------------------
# THE TABLE. Every `Expression` subclass appears in exactly one of these, with
# the single documented exception of `TryExpr` (PROJECTS + BRANCHES).
# `tools/test_producer_taxonomy.py` is what keeps that true.
# ---------------------------------------------------------------------------

#: Nodes that DENOTE storage an existing owner keeps.
#:
#: `SelfExpr` is here since SL-211. A `&self` / `&var self` receiver names
#: storage the CALLER owns — that is what a borrow IS — so handing `self` on by
#: value mints a second owner of one value. It was absent, so every by-value
#: transfer of `self` was judged a fresh temporary: a double free at exit 0 on
#: NoCopy, a SIGABRT on ExplicitCopy, and correct on `Copy` only because
#: codegen's `_transfer_needs_copy` carries `SelfExpr` in a list of its own.
PRODUCER_READS: FrozenSet[Type[Expression]] = frozenset({
    Identifier,
    MemberAccess,      # unless `enum_variant_literal` — see `producer_kind`
    ArrayIndex,
    TupleIndex,
    SelfExpr,
})

#: Nodes that name a PART of another expression's storage, mapped to the field
#: holding that expression. The node's own type is what transfers; the operand
#: is what answers the aliasing question.
#:
#: `TryExpr` is here since SL-211. `try r` extracts the Ok payload out of
#: storage `r` still owns, exactly as `o!` extracts an optional's payload — so
#: `try r` aliases iff `r` does, while `try f()` over a call result stays a
#: fresh temporary the reader already owns. That is the same line DF-299a drew
#: between a forwarding cast and a building one.
PRODUCER_PROJECTS: Dict[Type[Expression], str] = {
    ForceUnwrap: 'expr',
    CastExpr: 'expr',   # only when `forwards_operand` — see `producer_kind`
    TryExpr: 'expr',
}

#: Nodes the return/tail ladder inserts to RE-TYPE a value, mapped to the field
#: holding it. The transfer to judge is the operand's.
#:
#: All four are here since SL-211 (SL-79 / DF-305a). The checkpoint used to run
#: AFTER the wrap by a deliberate comment ("a wrapped value is a fresh temporary
#: (not aliasing)"), so it judged the synthesized node instead of the author's
#: expression and saw nothing. `ResultOkWrap.value` is None for design 92's
#: bare `return` in a `Result<Void, E>` body, which is a boundary with no
#: source expression rather than an absent wrap.
PRODUCER_REWRAPS: Dict[Type[Expression], str] = {
    OptionalWrap: 'value',
    ResultOkWrap: 'value',
    ResultErrWrap: 'value',
    ErasedErrWrap: 'value',
}

#: Nodes whose value is one of several arm results (DF-299b), AND WHERE THOSE
#: ARMS ARE. Design 195 rule 2 already says each arm of one of these is a
#: transfer into one merged home; this is that sentence's ownership half.
#:
#: ONE TABLE, TWO QUESTIONS, BECAUSE THEY ARE ONE FACT. Classifying a node as
#: BRANCHES and knowing which blocks carry its arm results were two
#: enumerations of the same shape set — this set here, and a hand-written
#: `isinstance` chain in `types.py::_value_branch_arm_results` — and SL-333's
#: `ScopedBlock` was added to the first and not the second. The taxonomy then
#: said "judge each arm" while the consumer answered `None`, so the transfer
#: checkpoint never reached the tail and a `NoCopy` binding yielded from a
#: selected `#lend_var` branch was copied silently (codex, SL-333.p1 r4). Both
#: gates stayed green throughout: `producertaxonomy` establishes that every
#: value-position node is CLASSIFIED and `transferdecisions` that every
#: decision reached is RECORDED, and neither is a claim that a given tail is
#: judged. Membership is DERIVED from this table below, so a new branching form
#: cannot be classified without saying where its arms live.
#:
#: Each entry maps the class to a function from the node to the blocks (or bare
#: expressions) whose results it forwards, or to `None` where this node is not
#: acting as a branch at all.
BRANCH_ARM_SOURCES: Dict[Type[Expression], Callable] = {
    IfExpr: lambda e: [e.then_branch, e.else_branch],
    IfLetExpr: lambda e: [e.then_branch, e.else_branch],
    MatchExpr: lambda e: [arm.body for arm in e.arms],
    # The CATCH handler only. A `try` is the one node in TWO producer buckets
    # (design 269): its catch handler is a branch ARM and its Ok value PROJECTS
    # out of the subject's storage, so the two are judged by two different
    # rules. `None` here means "not branching" — a `try` with no catch.
    TryExpr: lambda e: ([e.catch_block] if e.catch_block is not None else None),
    TryCatchExpr: lambda e: [e.try_block, e.catch_block],
    # SL-333: the `#lend_var` fold's selected branch — ONE arm, which is the
    # degenerate case of this bucket rather than a sixth kind. Its value is
    # its block's tail, and the transfer is judged where that tail is written,
    # which is exactly the answer the `if` branch it was folded out of already
    # gave.
    ScopedBlock: lambda e: [e.block],
}

PRODUCER_BRANCHES: FrozenSet[Type[Expression]] = frozenset(BRANCH_ARM_SOURCES)


def branch_arm_sources(expr: Expression):
    """The blocks whose results this value-branch node forwards, or None.

    THE ONE ANSWER, read by `types.py::_value_branch_arm_results` (which peels
    the auto-wraps and hands the checkpoint each arm result) and by nothing
    else. `None` means the node is not a value branch here — either it is not
    in the taxonomy at all, or it is a `try` with no catch handler.
    """
    source = BRANCH_ARM_SOURCES.get(type(expr))
    return None if source is None else source(expr)

#: Nodes the checkpoint answers ahead of the producer question, because they
#: STATE the ownership answer instead of producing a value.
PRODUCER_OWN_ARM: FrozenSet[Type[Expression]] = frozenset({
    MoveExpr,          # ownership transfers; `_check_move_expr` records it
    ReferenceExpr,     # a borrow grants no ownership
    # design 275 U3: `lends self` is a BORROW, on exactly the terms
    # `ReferenceExpr` is one — it grants no ownership, and the storage it names
    # belongs to the caller of the producer it is written in. It reaches a
    # transfer position only once (a borrowing struct's reference field), and
    # the origin rules in `typechecker/borrowing.py` are what judge it there.
    LendsExpr,
})

#: Nodes that produce a fresh value the reader already owns. Nothing is
#: duplicated by transferring one, which is why no tier arm refuses one.
#:
#: The last six earn their place by a rule of their own rather than by building
#: a value out of nothing, and each is recorded here so the census is auditable:
#:
#:   * `NilCoalesce` — `a ?? b` yields an owned value either way. Its LEFT
#:     operand is a payload read (`_check_payload_read`) and its DEFAULT operand
#:     is entry point 18 of the checkpoint, so both sub-positions are judged at
#:     the `??` node's own check and the result is the reader's. (Design 267's
#:     census omitted this class entirely; SL-211 probed it — a `??` over a
#:     NoCopy binding is refused, correctly, by the payload rule.)
#:   * `OptionalChain` / `BindOptional` / `OptionalEvalExpr` — design 111's own
#:     final-field copyability rule governs these, and refuses a move-only final
#:     projection by name.
#:   * `OptionalChainAssign` — types `Void?`; there is no value to transfer.
#:   * `WhileExpr` / `ForLoop` — a loop's value arrives through `break <value>`,
#:     which is entry point 17 of the checkpoint. `ForLoop` is the one node here
#:     that is NOT an `Expression` subclass: it is a `Statement` carrying a
#:     `result_type`, which is what lets `let n = for i in 0..3 { ... }` reach a
#:     transfer. Design 267's census enumerated the 45 `Expression` subclasses
#:     and so could not see it; the gate below enumerates the union instead,
#:     which is how SL-211 found it.
PRODUCER_BUILDS: FrozenSet[Type[Expression]] = frozenset({
    ForLoop,
    IntLiteral,
    FloatLiteral,
    BoolLiteral,
    StringLiteral,
    StringInterpolation,
    FormatPlaceholder,
    BinaryOp,
    UnaryOp,
    FunctionCall,
    MethodCall,
    StructInit,
    EnumInit,
    TupleLiteral,
    ArrayLiteral,
    MapLiteral,
    SetLiteral,
    ClosureExpr,
    RangeExpr,
    NoneLiteral,
    SourceLocationLiteral,
    LendVarLiteral,
    NilCoalesce,
    OptionalChain,
    BindOptional,
    OptionalEvalExpr,
    OptionalChainAssign,
    WhileExpr,
})

#: The ONE class deliberately in two buckets, named so the gate can tell a
#: designed overlap from an accident.
PRODUCER_DUAL_KIND: FrozenSet[Type[Expression]] = frozenset({TryExpr})


def producer_kind(expr: Optional[Expression]) -> Optional[str]:
    """Which kind of producer `expr` is, or None if it is not an expression.

    THE FUNNEL for the producer question (obligation 1). Its consumers:

      1. `TypeChecker._is_aliasing_expr` (`typechecker/types.py`) — the
         READS/PROJECTS/REWRAPS half, which every tier arm of
         `_check_value_transfer` is gated on, and which
         `_check_payload_read`, `consumes._check_consuming_receiver` and
         `_match_binding_aliases` reach through that one method.
      2. `TypeChecker._check_value_transfer` — the REWRAPS peel and the
         BRANCHES recursion, each of which hands the boundary on to the
         sub-occurrences rather than judging the node.
      3. `TransferRecorder._transfer_source_identity` (`ownership.py`) — the
         projection walk down to a root, which must see through exactly what
         this sees through or the ledger names the wrong source.

    `TryExpr` answers PROJECTS: its Ok value is the question every consumer
    above is asking. Its catch handler is a branch arm and is judged by the
    checkpoint's own `try` arm, which is the only caller that needs to know
    about the overlap.
    """
    if expr is None:
        return None
    cls = type(expr)
    if cls is MemberAccess:
        # design 139: `Slot.Empty` is a payload-free enum variant LITERAL. It
        # wears the same node type as `config.slot` but constructs a fresh
        # value out of nothing, so it is no more aliasing than a struct init.
        # Only the typechecker can tell the two spellings apart, which is why
        # this rides an annotation instead of a node type.
        return BUILDS if getattr(expr, 'enum_variant_literal', False) else READS
    if cls is CastExpr:
        # DF-299a: only the three arms of `_check_cast_expr` that hand the
        # OPERAND back are transparent. The arms that build a NEW value — an
        # integer conversion, a raw enum tag, an address reinterpretation — are
        # unstamped and BUILD.
        return PROJECTS if getattr(expr, 'forwards_operand', False) else BUILDS
    if cls in PRODUCER_READS:
        return READS
    if cls in PRODUCER_PROJECTS:
        return PROJECTS
    if cls in PRODUCER_REWRAPS:
        return REWRAPS
    if cls in PRODUCER_BRANCHES:
        return BRANCHES
    if cls in PRODUCER_OWN_ARM:
        return OWN_ARM
    if cls in PRODUCER_BUILDS:
        return BUILDS
    # Unreachable while `tools/test_producer_taxonomy.py` passes: every
    # `Expression` subclass is in a bucket. Answering BUILDS here would be the
    # old failure mode (a missing member reads as a fresh temporary and every
    # tier arm goes quiet), so an unclassified node is loud instead.
    raise AssertionError(
        f"expression class `{cls.__name__}` has no producer classification — "
        f"add it to a bucket in `typechecker/producers.py` (see the module "
        f"docstring for what each kind means)"
    )


def projected_operand(expr: Expression) -> Optional[Expression]:
    """The storage-bearing operand a PROJECTS node names a part of.

    Only meaningful once `producer_kind(expr)` has answered `PROJECTS`.
    """
    field = PRODUCER_PROJECTS.get(type(expr))
    return None if field is None else getattr(expr, field, None)


def rewrapped_operand(expr: Expression) -> Optional[Expression]:
    """The value a REWRAPS node re-types, or None when the wrap holds none.

    None is design 92's bare `return` in a `Result<Void, E>` body, which the
    checkpoint already handles as a boundary with no source expression. Only
    meaningful once `producer_kind(expr)` has answered `REWRAPS`.
    """
    field = PRODUCER_REWRAPS.get(type(expr))
    return None if field is None else getattr(expr, field, None)

"""Ownership TRANSFER DECISIONS — what the transfer checkpoint leaves behind.

Design 267 step 3 (SL-210, unit A of the SL-209 ownership-uniformity epic).

THE PROBLEM THIS SOLVES. `_check_value_transfer` used to answer a transfer in
two ways at once: it might report an error, and it might stamp
`expr.needs_copy = True`. Everything else — a trivial bitwise duplicate, a
fresh temporary taken whole, a `move`, a borrow that is not a transfer at all,
a judgment deliberately deferred to the generic template or to the coroutine
transform — left NO trace. So a false `needs_copy` was indistinguishable from a
transfer nothing ever checked, which is exactly the distinction every later
unit of the epic needs: codegen's second opinion cannot be retired
(`_transfer_needs_copy`, unit D) and a completeness verifier cannot exist
(unit E) while "checked, nothing owed" and "never checked" look the same.

THE RECORD. Every exit path of the checkpoint now produces a
`TransferDecision` and files it in a LEDGER on the typechecker. The decision
carries the five things the epic asks for:

  * the SOURCE, by stable identity — `VariableInfo.binding_id` plus a
    projection path, never the spelling (`SourceIdentity`);
  * the DESTINATION (the checkpoint's `context` string) and the diagnostic
    site (source file, line, column);
  * the ACTION — one of the eight below;
  * the required CLEANUP-STATE change;
  * any generic copy REQUIREMENT still awaiting specialization
    (`pending`, the type-parameter names the answer depends on).

WHY A SIDE TABLE, AND WHY IT IS AN OCCURRENCE RECORD RATHER THAN AN
ANNOTATION. Evaluating an expression and transferring its result are different
operations, so the decision may not ride the expression node: an annotation is
a property of the VALUE, and a decision is a property of the BOUNDARY the value
crosses. The ledger key is therefore the boundary —
`(source node_id, destination context, line, column)` — and the node_id is in
it only to NAME which occurrence, since an AST node occupies exactly one
operand slot and "the transfer whose source is node N at site S" is unique.

Three consequences follow from the table living outside the AST, and each one
is a reason it is a table:

  * `dataclasses.fields()` does not see it, so the design-126 AST contract has
    nothing to declare and `substitute_ast_types` has nothing to walk (a
    decision holds `SawType`s that are correct for the body they were made in,
    and a monomorphized clone must NOT inherit them);
  * `deepcopy` gives a clone FRESH node_ids, so an instantiation's transfers
    are new occurrences with their own decisions rather than a template's
    reused;
  * the std cache pickles the builtin AST and namespace, and a side table would
    be empty on a cache hit — which is honest here and is recorded as a SCOPE
    limit rather than papered over: std's own bodies are checked once, under
    the builtin typechecker, and the entry compile's ledger covers the entry
    module, the user modules and every instance materialized into them.

ASSIGN, NEVER ACCUMULATE (design 218 stage 1's rule, at this table). The front
half runs more than once over one AST — the coroutine transform rewrites and
the whole program is re-checked — so a later pass's decision REPLACES an
earlier one for the same occurrence, and `revision` counts how many times the
occurrence has been decided. The last check is the answer, exactly as it is for
`payload_needs_copy`.

BEHAVIOR. Recording changes nothing a program observes: no diagnostic moves, no
annotation is added or withheld, and no consumer reads the ledger yet. Unit A
is the record; units B-E are what read it.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ast_nodes import (
    ArrayIndex, Expression, ForceUnwrap, Identifier, MemberAccess,
    MoveExpr, ReferenceExpr, SawType, SelfExpr, TupleIndex,
)

from . import producers


# ---------------------------------------------------------------------------
# THE ACTION SET. The first four are design 267's rule table read straight off
# the issue; the last four are the arms the checkpoint demonstrably has, each
# named so that a reader auditing the ledger can tell a judgment from a
# hand-off.
# ---------------------------------------------------------------------------

#: A fresh owned temporary. Ownership transfers whole; no duplication is owed.
ACTION_TAKE = 'take'
#: An existing value duplicated through its type's copy operation. At the
#: `Copy` tier that is a retain and the checkpoint stamps `needs_copy`; at the
#: trivial tier it is the bitwise copy the ABI already performs and nothing is
#: stamped. Both are recorded, which is the acceptance criterion's "including
#: trivial copies".
ACTION_COPY = 'copy'
#: A spelled `move`. Ownership transfers and the source is retired.
ACTION_MOVE = 'move'
#: No value and no transfer — a diverging or absent source, or a source whose
#: type an earlier error left unknown.
ACTION_NONE = 'none'
#: The source is LENT, not transferred: a `&`/`&var` argument, or an escaping
#: closure forwarded into a non-escaping slot. Borrowing grants no ownership,
#: so there is nothing to duplicate and nothing to retire.
ACTION_BORROW = 'borrow'
#: An illegal transfer, refused HERE. The diagnostic is already reported; the
#: record exists so a refusal is not mistaken for an unchecked boundary.
ACTION_REFUSED = 'refused'
#: This node is not itself a transfer — it hands the boundary on to other
#: occurrences, whose keys are in `delegates` (a value branch's arms), or to
#: another checker that owns the rule (the design-131 payload read).
ACTION_DELEGATED = 'delegated'
#: Judged by a different layer, deliberately: the generic template's tier
#: requirement (design 218c §1c skips 4 and 5) or the coroutine transform's own
#: frame bookkeeping. `reason` names which.
ACTION_DEFERRED = 'deferred'

ACTIONS = (ACTION_TAKE, ACTION_COPY, ACTION_MOVE, ACTION_NONE, ACTION_BORROW,
           ACTION_REFUSED, ACTION_DELEGATED, ACTION_DEFERRED)


# ---------------------------------------------------------------------------
# THE CLEANUP-STATE CHANGE a decision requires. Recorded separately from the
# action because the two are not the same question: the action says what the
# destination gets, this says what has to happen to the SOURCE's and the
# destination's drop obligations for that to be sound.
# ---------------------------------------------------------------------------

#: Nothing changes. A borrow, a refusal, a trivial duplicate at a tier with no
#: destructor, a hand-off.
CLEANUP_NONE = 'none'
#: The destination adopts the temporary's existing obligation; the source had
#: none.
CLEANUP_ADOPT_TEMPORARY = 'adopt-temporary'
#: The source KEEPS its obligation and the destination gains a fresh one —
#: which is what the copy operation (a retain, a deep copy) creates.
CLEANUP_RETAIN_SOURCE = 'retain-source'
#: The source's obligation is cancelled and the destination takes it over.
CLEANUP_RETIRE_SOURCE = 'retire-source'


# ---------------------------------------------------------------------------
# HOW the source produces the value — the second of design 267's two
# questions, recorded per occurrence so the boundary/producer matrix in the
# inventory can be audited from the ledger rather than from prose.
# ---------------------------------------------------------------------------

SOURCE_NONE = 'none'              # there is no source expression
SOURCE_TEMPORARY = 'temporary'    # a call result, a construction, a literal
SOURCE_BINDING = 'binding'        # a whole named binding
SOURCE_PROJECTION = 'projection'  # a field/element/payload of some root
SOURCE_RECEIVER = 'receiver'      # `self` — storage the CALLER owns
SOURCE_PLACE = 'place'            # a `borrows` accessor's lent storage
SOURCE_REFERENCE = 'reference'    # a `&`/`&var` operand
SOURCE_UNKNOWN = 'unknown'        # a shape the walk below does not classify


@dataclass(frozen=True)
class SourceIdentity:
    """WHERE the transferred value comes from, by identity rather than spelling.

    `binding_id` is the root binding's `VariableInfo.binding_id` — the same
    identity design 15's move dataflow keys on, so two same-named bindings in
    different scopes are two sources and a rename is none. `path` is the
    projection walked off that root, outermost-last (`('inner', '0')` for
    `h.inner.0`), which is what distinguishes a whole-binding transfer from a
    field read the source keeps a copy of. `display` is for diagnostics ONLY
    and no rule may read it.
    """
    kind: str
    binding_id: Optional[int]
    path: Tuple[str, ...]
    display: str

    @property
    def is_whole_binding(self) -> bool:
        return self.kind == SOURCE_BINDING and not self.path


#: The occurrence key: (source node_id or None, destination context, line,
#: column). See the module docstring for why the node id names an occurrence
#: rather than annotating a node.
TransferKey = Tuple[Optional[int], str, int, int]


@dataclass(frozen=True, eq=False)
class TransferDecision:
    """One ownership boundary's explicit answer."""
    key: TransferKey
    action: str
    source: SourceIdentity
    destination: str
    site: Tuple[Optional[str], int, int]
    cleanup: str
    tier: Optional[str] = None
    source_type: Optional[SawType] = None
    target_type: Optional[SawType] = None
    pending: Tuple[str, ...] = ()
    delegates: Tuple[TransferKey, ...] = ()
    reason: str = ''
    is_return: bool = False
    revision: int = 1

    @property
    def duplicates(self) -> bool:
        """Does this decision leave TWO live owners behind?"""
        return self.action == ACTION_COPY

    @property
    def checked(self) -> bool:
        """A decision exists, so the boundary was checked. The whole point of
        the ledger: this is True for every entry, including the trivial copies
        and the take-temporaries that used to leave no trace at all, and the
        ABSENCE of an entry — not a false `needs_copy` — is what says a
        boundary was never checked."""
        return True


class OwnershipLedgerMixin:
    """The ledger `_check_value_transfer` files its decisions in.

    One instance per compile, on the typechecker, initialized by
    `_ownership_ledger_init` from `TypeChecker.__init__`. Read it through
    `transfer_decision`, `transfer_decisions` and `transfer_decision_stats`;
    nothing in the compiler writes to it except `_decide_transfer`.
    """

    def _ownership_ledger_init(self) -> None:
        # Keyed by occurrence; insertion-ordered, which makes a dump stable
        # for the same compile and is the only ordering property anything
        # relies on.
        self._transfer_ledger: Dict[TransferKey, TransferDecision] = {}

    # ------------------------------------------------------------------
    # Recording.
    # ------------------------------------------------------------------

    def _transfer_key(self, expr: Optional[Expression], context: str,
                      line: int, column: int) -> TransferKey:
        return (getattr(expr, 'node_id', None) if expr is not None else None,
                context, line, column)

    def _decide_transfer(self, expr: Optional[Expression], target_type,
                         context: str, line: int, column: int,
                         action: str, cleanup: str,
                         tier: Optional[str] = None,
                         source_type=None,
                         pending: Tuple[str, ...] = (),
                         delegates: Tuple[TransferKey, ...] = (),
                         reason: str = '',
                         is_return: bool = False) -> TransferDecision:
        """Build and file the decision for one transfer occurrence.

        THE ONE WRITER. Every exit path of `_check_value_transfer` returns
        through here, which is what makes "an occurrence with no entry was
        never checked" a sound reading of the table.
        """
        key = self._transfer_key(expr, context, line, column)
        previous = self._transfer_ledger.get(key)
        decision = TransferDecision(
            key=key,
            action=action,
            source=self._transfer_source_identity(expr),
            destination=context,
            site=(self._transfer_source_file(), line, column),
            cleanup=cleanup,
            tier=tier,
            source_type=source_type,
            target_type=target_type,
            pending=pending,
            delegates=delegates,
            reason=reason,
            is_return=is_return,
            revision=(previous.revision + 1) if previous is not None else 1,
        )
        # ASSIGN, not accumulate — see the module docstring.
        self._transfer_ledger[key] = decision
        return decision

    def _transfer_source_file(self) -> Optional[str]:
        for holder in (getattr(self, 'current_method', None),
                       getattr(self, 'current_function', None)):
            src = getattr(holder, 'source_file', None)
            if src:
                return src
        return None

    # ------------------------------------------------------------------
    # Source identity.
    # ------------------------------------------------------------------

    # The projection hops this walk sees through, and the marker each leaves
    # in the path. `!` and a FORWARDING cast are here for the same reason
    # `_is_aliasing_expr` sees through them: neither builds a value, so the
    # ROOT is what owns the storage (design 131 / DF-299a).
    _IDENTITY_DEPTH = 24

    def _transfer_source_identity(self, expr: Optional[Expression]
                                  ) -> SourceIdentity:
        """The stable identity of the storage `expr` reads from.

        Walks the projection chain down to a root and classifies the root. The
        walk deliberately mirrors `_is_aliasing_expr`'s transparency rules so
        the two never disagree about what the root of a read IS — but it is
        NOT the aliasing test and answers for every expression, including the
        fresh temporaries the aliasing test excludes.
        """
        if expr is None:
            return SourceIdentity(SOURCE_NONE, None, (), '')

        node = expr
        parts: List[str] = []
        for _ in range(self._IDENTITY_DEPTH):
            if getattr(node, 'place_struct', None) is not None:
                # A `borrows` accessor's lent storage. Stop HERE rather than
                # descending into the receiver: design 146 says a place borrow
                # charges its ROOT, and the accessor — not the projection under
                # it — is what names the storage.
                break
            if isinstance(node, MoveExpr):
                # `move x` NAMES `x`; the move is the ACTION, not a projection.
                # The node holds the root as a NAME plus an optional projected
                # lvalue (`move p.x`, the design-35 partial move the parser
                # accepts so the typechecker can refuse it by name), and
                # `unwrap` is the `move o!` spelling.
                if getattr(node, 'unwrap', False):
                    parts.append('!')
                if node.path is not None:
                    node = node.path
                    continue
                parts.reverse()
                path = tuple(parts)
                return SourceIdentity(
                    SOURCE_PROJECTION if path else SOURCE_BINDING,
                    self._transfer_root_id(node), path,
                    self._transfer_display(node.variable, path))
            kind = producers.producer_kind(node)
            if kind == producers.PROJECTS:
                # `o!`, a forwarding `r as Res`, `try r`. Each names a PART of
                # the operand's storage, so the ROOT is under it. `!` leaves a
                # marker in the path (it is a distinguishable projection of an
                # optional); a forwarding cast and a `try` leave none — a cast
                # projects nothing and a `try`'s payload has no field name.
                if isinstance(node, ForceUnwrap):
                    parts.append('!')
                node = producers.projected_operand(node)
                if node is None:
                    break
                continue
            if kind == producers.REWRAPS:
                # An auto-wrap RE-TYPES its operand, so the operand's root is
                # the source — which is what makes the ledger name `h.inner`
                # rather than `<temporary>` for `func f(h: &Holder) -> Res? {
                # h.inner }` (SL-79).
                node = producers.rewrapped_operand(node)
                if node is None:
                    break
                continue
            if isinstance(node, MemberAccess):
                if getattr(node, 'enum_variant_literal', False):
                    break        # `Slot.Empty` builds a value out of nothing
                parts.append(node.member)
                node = node.object
                continue
            if isinstance(node, TupleIndex):
                parts.append(str(node.index))
                node = node.tuple_expr
                continue
            if isinstance(node, ArrayIndex):
                parts.append('[]')
                node = node.array_expr
                continue
            break
        parts.reverse()
        path = tuple(parts)

        if getattr(node, 'place_struct', None) is not None:
            return SourceIdentity(SOURCE_PLACE, None, path,
                                  self._transfer_display('<place>', path))
        if isinstance(node, ReferenceExpr):
            return SourceIdentity(SOURCE_REFERENCE, None, path,
                                  self._transfer_display('&', path))
        if isinstance(node, SelfExpr):
            return SourceIdentity(SOURCE_RECEIVER, None, path,
                                  self._transfer_display('self', path))
        if isinstance(node, Identifier):
            root_id = self._transfer_root_id(node)
            kind = SOURCE_PROJECTION if path else SOURCE_BINDING
            return SourceIdentity(kind, root_id, path,
                                  self._transfer_display(node.name, path))
        if path:
            # A projection off a fresh temporary (`f().field`): the temporary
            # is the reader's already, so the ROOT is a temporary even though
            # a projection was walked.
            return SourceIdentity(SOURCE_TEMPORARY, None, path,
                                  self._transfer_display('<temporary>', path))
        return SourceIdentity(SOURCE_TEMPORARY, None, (), '<temporary>')

    def _transfer_root_id(self, node) -> Optional[int]:
        """The root binding's identity, READ off the node — never re-resolved.

        THE RULE (SL-210 review, and the whole point of the field): identity is
        captured where the name RESOLVES — `_check_identifier`,
        `_check_move_expr`, and the one synthesized capture Identifier in
        `_check_closure` — and this only reads it back. Looking the SPELLING up
        in `current_scope` here, which is what the first cut did, is resolution
        in the wrong scope: the ledger reaches a body's TAIL and a value
        branch's ARM results after their scopes have popped, so the lookup
        either missed (a local tail returned None, and a `move` tail recorded
        `retire-source` naming no source) or — the worse half — found an OUTER
        binding of the same name and reported a shadowed arm under its
        shadower's id, which no consumer could tell from the truth.

        None means "not a local binding" (a module `static`, a const generic
        parameter, a receiver, a fresh temporary, a name an earlier error
        poisoned). It never means "not looked up": both stamping sites assign
        on every path.
        """
        return getattr(node, 'resolved_binding_id', None)

    @staticmethod
    def _transfer_display(root: str, path: Tuple[str, ...]) -> str:
        out = root
        for step in path:
            out = f"{out}[…]" if step == '[]' else (
                f"{out}!" if step == '!' else f"{out}.{step}")
        return out

    # ------------------------------------------------------------------
    # Reading.
    # ------------------------------------------------------------------

    def transfer_decision(self, expr, context: str, line: int,
                          column: int) -> Optional[TransferDecision]:
        """The decision recorded for one occurrence, or None if the boundary
        was never checked. This is the distinction `needs_copy` could not
        make."""
        return self._transfer_ledger.get(
            self._transfer_key(expr, context, line, column))

    def transfer_decisions(self) -> List[TransferDecision]:
        """Every decision this compile recorded, in the order the checkpoint
        first reached each occurrence."""
        return list(self._transfer_ledger.values())

    def transfer_decision_stats(self) -> Dict[str, int]:
        """Decision counts per action, plus `total`. The audit harness's
        oracle (`tools/test_transfer_decisions.py`)."""
        stats = {a: 0 for a in ACTIONS}
        for decision in self._transfer_ledger.values():
            stats[decision.action] = stats.get(decision.action, 0) + 1
        stats['total'] = len(self._transfer_ledger)
        return stats

"""Consuming method receivers (design 260).

`func finish(&var self) consumes -> Report` declares a method whose exclusive
borrow of the receiver ENDS IN THE VALUE'S DEATH: the callee releases what
remains of the referent at body end, and the caller's binding is moved-from
past the call. The call site says so — `(move b).finish()` — so ownership is
visible on the page at both ends.

This module holds the three rules that are new, and nothing else. Everything
else design 260 promises falls out of machinery that already exists:

  * the NoMove refusal, use-after-consume, double-consume, the field/place
    receiver refusals and the Copy-tier retire all come from the caller's
    `move` taking `_check_move_expr`'s own axis (`expressions.py`), which is
    the move checkpoint this design routes through rather than beside
    (obligation 1; DF-216a's mechanism, N10 the standing warning);
  * the declaration pairings (`&self`, static, `init`, `borrows`) are refused
    at the parser, where the words are written;
  * the trait fences are refused at the requirement (parser) and at the
    conformance (`registration.py`).

THE FOUR RULES HERE, and the ONE entry point each:

0. `_check_consumes_containment` — the defining-module rule, called once per
   extension from `_register_extension` beside the orphan-rule check.

1. `_check_consuming_receiver` — THE call-site funnel. Every path that
   type-checks an instance method call against a resolved method symbol calls
   it exactly once, beside `_reject_var_self_call_on_shared_self` — the two
   sites are the same pair, because a `consumes` method is always a `&var self`
   method. Its entry points, all of them:
     - `_check_method_call` (expressions.py) — the plain instance-method call,
       concrete or generic receiver, `b.finish()` / `(move b).finish()`.
     - `_check_overloaded_method_call` (expressions.py) — the same call when
       the name carries an overload set.
   The two TRAIT-reaching call forms (`_check_type_param_method_call` through a
   bound, `_check_existential_method_call` through `any Trait`) are NOT entry
   points and need none: §4's fence refuses `consumes` on a requirement at the
   parser and on a conforming method at the conformance, so no consuming method
   is reachable through either. Anything else that ever grows a way to reach a
   method symbol with a receiver expression must call this: a consuming call
   that skips the funnel is a double free — the callee releases, and the
   caller's binding still owns.

2. `_consuming_field_move_ok` — design 260 §3's Option A carve-out, called
   from `_check_move_expr`'s partial-move refusal and nowhere else. It answers
   "is this `move self.<field>` the licensed one?" and, when the receiver type
   carries a HAND-WRITTEN `deinit`, refuses it with the E0509-analog message.

3. `_check_consumes_field_paths` — the every-path-or-no-path decision, run
   once per consuming body from `_check_method` after the body is checked. It
   stamps `Method.consumes_moved_fields`, which is what codegen's end-of-body
   release skips.
"""

from typing import List, Optional, Set, Tuple

from ast_nodes import (
    Argument, ASTNode, AssignStatement, Block, BreakStatement,
    CompoundAssignStatement, ContinueStatement, DestructuringLet, Expression,
    ExpressionStatement, ForLoop, GuardLetStatement, IfExpr,
    IfLetExpr, LetStatement, MatchExpr, MemberAccess, Method, MethodCall,
    MoveExpr, ReturnStatement, SelfExpr, Statement, TryCatchExpr,
    WhileExpr, expr_diverges,
)
from errors import ErrorKind


def _names_receiver(node) -> bool:
    """Does `node` name the METHOD RECEIVER, in either spelling?

    Two, because the whole program is re-checked after the coroutine transform
    and the transform rewrites a suspending method's `self` into the receiver
    lent through the frame's handle — `self.__recv.deref()`, where `self` is
    the FRAME. A rule written only in the source spelling would answer one way
    before the transform and the opposite way after it, which for design 260 §3
    means refusing a move it already licensed AND concluding the body moved
    nothing (putting the moved field back into the end-of-body sweep). Both
    spellings, one answer.
    """
    if isinstance(node, SelfExpr):
        return True
    if isinstance(node, MethodCall) and node.method_name == "deref":
        obj = node.object
        return (isinstance(obj, MemberAccess) and obj.member == "__recv"
                and isinstance(obj.object, SelfExpr))
    return False


def _consumes_field_of(node: Optional[Expression]) -> Optional[str]:
    """The receiver field a `move` extracts, or None if it extracts none.

    ONE hop, deliberately: `move self.a.b` reaches storage inside a field the
    receiver still owns, which the end-of-body release would then drop as a
    whole — so it stays the ordinary no-partial-moves refusal. The carve-out is
    per FIELD because the release is per field.
    """
    if not isinstance(node, MoveExpr):
        return None
    stamped = getattr(node, 'consumes_field', None)
    if stamped is not None:
        return stamped
    path = node.path
    if isinstance(path, MemberAccess) and _names_receiver(path.object):
        return path.member
    return None


class ConsumesMixin:
    """Design 260's three rules. See the module docstring for the entry points."""

    # ------------------------------------------------------------------
    # 0. The declaration: module containment.
    # ------------------------------------------------------------------

    def _check_consumes_containment(self, extension) -> None:
        """A `consumes` method belongs to the receiver type's DEFINING module.

        Design 260 §2, user-ratified Sep 1 and uniform — there is no
        deinit-presence special case. A consuming body OCCUPIES the
        hand-written deinit body's design-131 prefix slot for its endpoint, so
        declaring one overrides the type's teardown; that is the type author's
        privilege, exactly as the deinit itself is (a deinit rides the
        copy-policy conformance, which the orphan rule already pins to the
        defining module). Without this, a foreign
        `func leak(&var self) consumes {}` would suppress another module's
        cleanup contract — design 242's `Thread` fate panic included — with
        nothing on the page to say so.

        Called once per extension from `_register_extension`, beside the
        orphan-rule check whose containment this mirrors. Foreign modules keep
        the open pattern: a by-value free function, `consume(move obj)`.
        """
        consuming = [m for m in (extension.methods or [])
                     if getattr(m, 'is_consumes', False)]
        if not consuming or getattr(extension, 'is_synthesized', False):
            return
        ext_module = self._vis_module_for_source(
            getattr(extension, 'source_file', None))
        type_name = extension.struct_name
        type_sym = (self.namespace.lookup_struct(type_name)
                    or self.namespace.lookup_enum(type_name))
        type_module = getattr(type_sym, 'def_module', None) if type_sym else None
        if type_module is None or type_module == ext_module:
            return
        where = self._module_label(type_module)
        for m in consuming:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{m.name}` cannot be declared `consumes` here: a consuming "
                f"method replaces `{type_name}`'s teardown, and this module "
                f"does not define `{type_name}`",
                m.line, m.column,
                hint=f"declare it in `{where}` (which defines `{type_name}`) — "
                     f"overriding a type's teardown is the type author's "
                     f"privilege, the same containment its `deinit` has. From "
                     f"here, take the value by value in a free function "
                     f"instead (`consume(move obj)`)",
                source_file=getattr(extension, 'source_file', None)
            )

    # ------------------------------------------------------------------
    # 0b. The two fences a SUSPENDING consuming body meets.
    # ------------------------------------------------------------------

    def _check_consumes_suspending_fences(self, nodes) -> None:
        """Refuse the two shapes a suspending consuming body cannot honour.

        A suspending method's receiver does not live in the callee at all: the
        transform hoists it into the CALLER's coroutine frame, where the frame
        holds it in a slot and the frame's own release is what ends it. That
        release is decided per SLOT — whole value or nothing — and it runs on
        every teardown edge, cancellation included. Two consequences, each a
        clean v1 refusal rather than a silently wrong program:

        1. A FIELD MOVE cannot be honoured. The slot release cannot skip a
           field, and a cancellation point between the move and the body's end
           would need exactly the per-field drop flag design 260 §3 excludes —
           so the shape is refused rather than left to double-free or leak.
        2. A receiver type with a HAND-WRITTEN `deinit` cannot be honoured. The
           slot release runs the type's FULL deinit, so §2's replacement rule
           (the consuming body takes the deinit body's place) has nowhere to be
           applied.

        Everything else about a suspending consuming method works and is
        tested: the receiver is released exactly once, its remainder swept,
        driven or spawned. Called from `finalize_effects`, which is re-entrant
        (design 218c phase 3 settles the graph again after monomorphization) —
        so the funnel's `_effects_reported` ledger is what keeps a fence that
        fired on the first settling from firing again on the second.
        """
        if getattr(self, 'post_transform', False):
            return
        for method, struct_name, has_deinit in getattr(self, '_consumes_bodies', ()):
            node = nodes.get(method.node_id)
            if node is None or not node.suspends:
                continue
            if ('consumes-fence', method.node_id) in self._effects_reported:
                continue
            self._effects_reported.add(('consumes-fence', method.node_id))
            moved = tuple(getattr(method, 'consumes_moved_fields', ()) or ())
            if moved:
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"`{method.name}` moves field `{moved[0]}` out of `self` "
                    f"and also SUSPENDS — design 260 v1 does not support both "
                    f"in one method",
                    method.line, method.column,
                    hint="a suspending method's receiver lives in the caller's "
                         "coroutine frame, whose release is decided per slot "
                         "and cannot skip a field. Extract with "
                         f"`self.{moved[0]}.take()`, or split the extraction "
                         f"into a `sync` consuming method",
                    source_file=getattr(method, 'source_file', None))
            if has_deinit:
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"`{method.name}` is `consumes` on `{struct_name}`, which "
                    f"has a hand-written `deinit`, and it SUSPENDS — design 260 "
                    f"v1 does not support that combination",
                    method.line, method.column,
                    hint="a consuming body replaces the hand-written `deinit` "
                         "body for its endpoint, and a suspending receiver is "
                         "released by the caller's coroutine frame, which runs "
                         "the full deinit instead. Make the consuming method "
                         "`sync`, or drop the hand-written `deinit`",
                    source_file=getattr(method, 'source_file', None))

    def _struct_has_written_deinit(self, type_name: str) -> bool:
        """`_type_has_written_deinit` by NAME rather than by type."""
        sym = self.namespace.lookup_method(type_name, "deinit")
        return bool(sym is not None and not getattr(
            getattr(sym, 'ast_node', None), 'is_synthesized', False))

    # ------------------------------------------------------------------
    # 1. The call site.
    # ------------------------------------------------------------------

    def _check_consuming_receiver(self, expr: MethodCall, method_info) -> None:
        """Refuse a consuming call whose receiver is a binding with no `move`.

        THE funnel (see the module docstring for its entry points). Stamps
        `expr.is_consuming_call` so codegen knows the callee owns the release —
        a consuming call this never sees keeps the caller's release and double
        frees, which is why the entry points are named rather than left to
        whoever adds the next method-call path.

        The receiver's OWN transfer is not judged here: `move b` was already
        checked by `_check_move_expr` when the receiver expression was checked,
        which is where the NoMove refusal, the use-after-move error and the
        field/place partial-move refusals all live. This function adds exactly
        one thing — that the word be there.
        """
        if not getattr(method_info, 'is_consumes', False):
            return
        expr.is_consuming_call = True
        recv = expr.object
        if isinstance(recv, MoveExpr):
            return
        if not self._is_aliasing_expr(recv):
            # A TEMPORARY receiver (design 260 §2): `make_builder().finish()`,
            # `Mode.Fast.label()`. No binding to invalidate, and the temp was
            # already the callee's to end — so the fixit fires only for
            # bindings. The question is the transfer checkpoint's own ("does
            # this read out of storage somebody already owns?"), asked through
            # the same helper, so the two answers can never drift apart.
            # Codegen cannot re-ask it (an enum-variant literal wears a
            # MemberAccess), so the answer rides to it on the node.
            expr.consuming_temp_receiver = True
            return
        place = self._render_lvalue_path(recv)
        self._error(
            ErrorKind.CANNOT_COPY,
            f"`{expr.method_name}` consumes its receiver — write "
            f"`(move {place}).{expr.method_name}()`",
            expr.line, expr.column,
            hint=f"a consuming method ends the value it is called on, so the "
                 f"transfer is spelled at the call. `{place}` is moved-from "
                 f"afterwards (a `var` revives on reassignment)"
        )

    # ------------------------------------------------------------------
    # 2. Option A: `move self.<field>` inside a consuming body.
    # ------------------------------------------------------------------

    def _consuming_field_move_ok(self, expr: MoveExpr):
        """Design 260 §3: `move self.<field>` inside a consuming body.

        Returns `(handled, type)`: `(True, field_type)` when the carve-out
        applies and the move is legal, `(False, None)` to let
        `_check_move_expr` fall through to the ordinary no-partial-moves
        refusal. Called from there and nowhere else.

        The carve-out crosses BOTH standing bans it touches — no partial moves
        AND no move out of a reference — and is licensed by `consumes` alone:
        the referent is the callee's to END, the caller's binding is moved-from
        on return and releases nothing, so a partially-emptied receiver is
        never observable. Every other position keeps both bans, including a
        NON-consuming `&var self` method.

        IT APPLIES ON EVERY TYPE, hand-written `deinit` or not (design 260 §3.2
        as re-ruled Sep 1). The consuming body OCCUPIES that deinit body's
        design-131 prefix slot for this endpoint — the hand-written body does
        not run for a consumed receiver — so there is no black box left to
        observe a moved-out field, and the module containment rule
        (`_check_consumes_module`) is what keeps the privilege with the type's
        own author.
        """
        if getattr(expr, 'consumes_field', None) is not None:
            # ALREADY DECIDED on an earlier pass, and this test comes first on
            # purpose. After the coroutine transform the body no longer sits in
            # the consuming method at all — it is the frame's synthesized
            # `resume`, which carries no `consumes` of its own — so re-deriving
            # the answer would refuse a move the source pass licensed. The
            # stamp and the type it resolved to ride on the node.
            #
            # The PATH is still checked: after the transform it reads the
            # receiver through `self.__recv.deref()`, a `borrows` accessor whose
            # use has to be recognized here or `place_uses` will never lower it
            # and codegen meets a call to a method that does not exist.
            self._check_expression(expr.path)
            return True, expr.consumes_field_type
        method = getattr(self, 'current_method', None)
        if method is None or not getattr(method, 'is_consumes', False):
            return False, None
        field = _consumes_field_of(expr)
        if field is None:
            return False, None
        self_type = self._self_struct_type_for_consumes()
        if self_type is None:
            return False, None
        owner = self._consumes_type_name(self_type)
        fields = self.namespace.get_struct_fields(owner) or {}
        if field not in fields:
            return False, None
        expr.consumes_field = field
        expr.consumes_field_type = self._resolve_type(fields[field])
        moved = list(getattr(method, 'consumes_moved_fields', ()) or ())
        if field not in moved:
            moved.append(field)
            method.consumes_moved_fields = tuple(moved)
        return True, expr.consumes_field_type

    def _self_struct_type_for_consumes(self):
        """The receiver's type inside the consuming body being checked."""
        info = self.current_scope.lookup('self') if self.current_scope else None
        return info.type if info is not None else None

    def _consumes_type_name(self, t) -> Optional[str]:
        """The struct/enum name a receiver type carries, for a field lookup."""
        return getattr(t, 'struct_name', None) or getattr(t, 'enum_name', None)

    # ------------------------------------------------------------------
    # 3. The every-path-or-no-path decision.
    # ------------------------------------------------------------------

    def _check_consumes_field_paths(self, method: Method) -> None:
        """Design 260 §3: decide each moved field on EVERY path or NO path.

        Run once per consuming body, after the body is checked (so every
        `move self.<field>` has already passed `_consuming_field_move_ok`). The
        rule is PER FIELD and the fields are independent — two fields moved out
        into a tuple return is the intended idiom — so a CONDITIONAL SPLIT
        (field A on one branch, field B on the other) fails the test for BOTH
        and is refused by name. That is v1's excluded drop-flag shape.

        A DIVERGING path is exempt for the fields it never reaches, as in every
        liveness rule: `panic` and `return` on one branch decide nothing about
        what the other branch owns.

        Stamps `Method.consumes_moved_fields` with exactly the fields moved on
        every exit; codegen's end-of-body release drops the rest.
        """
        declared = list(getattr(method, 'consumes_moved_fields', ()) or ())
        if not declared:
            return
        if not self._consumes_scan_deep(method.body):
            # The body no longer CONTAINS the moves this stamp records, which
            # means the coroutine transform has moved them into the frame's
            # `resume` and left a driver here. The set was decided by the pass
            # that could see them; re-deciding it from a body with none would
            # answer "nothing moved" and put the moved field straight back into
            # the end-of-body sweep — a double free.
            return
        # Reset: the walk below decides the final set, and re-checking a body
        # (a monomorphized clone, the post-transform pass) must not accumulate.
        method.consumes_moved_fields = ()
        body_exits, body_falls = self._consumes_walk_block(
            method.body, frozenset(), declared)
        exits = body_exits + body_falls
        if not exits:
            # Every path diverges: nothing survives to be released, and no
            # field is owed on any exit.
            return
        moved_everywhere = set(exits[0])
        moved_anywhere: Set[str] = set()
        for e in exits:
            moved_everywhere &= set(e)
            moved_anywhere |= set(e)
        for field in declared:
            if field in moved_anywhere and field not in moved_everywhere:
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"field `{field}` is moved out of `self` on some paths of "
                    f"`{method.name}` but not others — a consuming body decides "
                    f"each field on EVERY path or NO path",
                    method.line, method.column,
                    hint=f"move `{field}` on every path that returns (a "
                         f"diverging path is exempt), or on none — the "
                         f"conditional shape is the one that would need "
                         f"runtime drop flags, which design 260 v1 excludes"
                )
        method.consumes_moved_fields = tuple(
            f for f in declared if f in moved_everywhere)

    # -- the structural walk ------------------------------------------------
    #
    # ONE contract throughout: a walk returns `(exits, falls)`. `exits` are the
    # sets at terminations that leave the METHOD (each `return`); `falls` are
    # the sets at edges that continue past this construct. Both are lists of
    # frozensets, and both are EMPTY where every path diverged — which is
    # exactly the liveness exemption a `panic`/`return` branch is owed. The
    # method's answer is `exits + falls` of its body.
    #
    # `falls` is a LIST rather than one joined set on purpose: two branches that
    # disagree about a field must reach the per-field test as two answers, not
    # as an intersection that hides the disagreement.
    #
    # A construct this walk does not MODEL is refused outright when it contains
    # a field move, so an unmodelled position is never mis-analyzed into
    # silence.

    def _consumes_walk_block(self, block: Optional[Block], moved: frozenset,
                             declared: List[str]):
        """A block: its statements, then its tail expression on each live edge."""
        if block is None:
            return [], [moved]
        exits, falls = self._consumes_walk_stmts(list(block.statements), moved,
                                                 declared)
        if block.final_expr is None:
            return exits, falls
        out_falls: List[frozenset] = []
        for fall in falls:
            sub_exits, sub_falls = self._consumes_walk_value(
                block.final_expr, fall, declared)
            exits.extend(sub_exits)
            out_falls.extend(sub_falls)
        return exits, out_falls

    def _consumes_walk_stmts(self, stmts: List[Statement], moved: frozenset,
                             declared: List[str]):
        """A statement list, threaded in order. Returns `(exits, falls)`."""
        exits: List[frozenset] = []
        falls = [moved]
        for stmt in stmts:
            if not falls:
                # Unreachable tail after a diverging statement: the ordinary
                # reachability rules already judged it.
                break
            next_falls: List[frozenset] = []
            for fall in falls:
                sub_exits, sub_falls = self._consumes_walk_stmt(
                    stmt, fall, declared)
                exits.extend(sub_exits)
                next_falls.extend(sub_falls)
            falls = next_falls
        return exits, falls

    def _consumes_walk_stmt(self, stmt: Statement, moved: frozenset,
                            declared: List[str]):
        """One statement. Returns `(exits, falls)`."""
        if isinstance(stmt, ReturnStatement):
            if stmt.value is not None:
                moved = self._consumes_expr_moves(stmt.value, moved, declared)
            return [moved], []
        if isinstance(stmt, (BreakStatement, ContinueStatement)):
            # A loop edge. `move self.<field>` inside a loop is refused below,
            # so nothing is in flight here; the local flow simply ends.
            return [], []
        if isinstance(stmt, ExpressionStatement):
            return self._consumes_walk_value(stmt.expression, moved, declared)
        if isinstance(stmt, (LetStatement, DestructuringLet, AssignStatement,
                             CompoundAssignStatement)):
            value = getattr(stmt, 'value', None)
            if value is not None:
                exits, falls = self._consumes_walk_value(value, moved, declared)
            else:
                exits, falls = [], [moved]
            target = getattr(stmt, 'target', None)
            if declared and isinstance(target, SelfExpr):
                # Whole-referent replacement (design 110) inside a body that
                # ALSO moves a field out. The old referent deinits WHOLE at the
                # assignment — hand-written body included, since it is not the
                # consumed endpoint — which would release a field the move
                # already handed away. The two are individually fine and only
                # the combination is not, so it is refused where they meet.
                self._error(
                    ErrorKind.CANNOT_COPY,
                    "`self = ...` and `move self.<field>` may not appear in "
                    "one consuming body (design 260 v1): the replacement "
                    "releases the OLD referent whole, including the field the "
                    "move handed away",
                    stmt.line, stmt.column,
                    hint="replace the whole receiver, or extract fields — not "
                         "both. `self.<field>.take()` mutates to a valid state "
                         "and composes with either"
                )
            if target is not None:
                falls = [self._consumes_expr_moves(target, f, declared)
                         for f in falls]
            return exits, falls
        if isinstance(stmt, (WhileExpr, ForLoop)):
            self._consumes_refuse_in(stmt, declared, "a loop body",
                                     "a loop runs its body more than once, so "
                                     "a field could be moved twice")
            return [], [moved]
        if isinstance(stmt, GuardLetStatement):
            self._consumes_refuse_in(stmt.optional_expr, declared,
                                     "a `guard let` subject", None)
            # The else branch must diverge, so it contributes no exit and can
            # move nothing that survives.
            self._consumes_refuse_in(stmt.else_branch, declared,
                                     "a `guard let` else branch", None)
            return [], [moved]
        # Anything this walk does not model.
        self._consumes_refuse_in(stmt, declared, "this position", None)
        return [], [moved]

    def _consumes_walk_value(self, expr: Expression, moved: frozenset,
                             declared: List[str]):
        """An expression evaluated for its value, branching ones included.

        The SAME routine serves statement position and tail position, which is
        what makes `if hot { move self.a } else { Tag(id: 0) }` decide the same
        way whether it is the body's tail or a statement in the middle.
        """
        if isinstance(expr, IfExpr):
            self._consumes_refuse_in(expr.condition, declared,
                                     "an `if` condition", None)
            branches = [self._consumes_walk_block(expr.then_branch, moved,
                                                  declared)]
            if expr.else_branch is not None:
                branches.append(self._consumes_walk_block(expr.else_branch,
                                                          moved, declared))
            else:
                # No else: falling past the `if` is its own edge.
                branches.append(([], [moved]))
            return self._consumes_join(branches)
        if isinstance(expr, MatchExpr):
            self._consumes_refuse_in(expr.matched_expr, declared,
                                     "a `match` scrutinee", None)
            branches = []
            for arm in expr.arms:
                body = arm.body
                if isinstance(body, Block):
                    branches.append(self._consumes_walk_block(body, moved,
                                                              declared))
                else:
                    branches.append(
                        self._consumes_walk_value(body, moved, declared))
            return self._consumes_join(branches)
        if isinstance(expr, (IfLetExpr, TryCatchExpr, WhileExpr)):
            self._consumes_refuse_in(expr, declared, "this position", None)
            return [], [moved]
        after = self._consumes_expr_moves(expr, moved, declared)
        if expr_diverges(expr):
            return [], []
        return [], [after]

    def _consumes_join(self, branches):
        """Join branch results: `(exits, falls)` over every branch.

        Branch fall-throughs are CONCATENATED, never intersected. Two branches
        that disagree about a field must reach the per-field test as two
        answers — intersecting them here would hide exactly the conditional
        split v1 refuses.
        """
        exits: List[frozenset] = []
        falls: List[frozenset] = []
        for sub_exits, sub_falls in branches:
            exits.extend(sub_exits)
            falls.extend(sub_falls)
        return exits, falls

    # -- expression-level move collection -----------------------------------

    def _consumes_expr_moves(self, expr: Optional[Expression], moved: frozenset,
                             declared: List[str]) -> frozenset:
        """Fold every `move self.<field>` reachable in one expression.

        Reports a second move of a field already gone, and a plain READ of one.
        A read after the move is a copy of storage nothing owns any more, which
        is the double free the all-paths rule exists to make impossible.
        """
        found = self._consumes_scan(expr)
        out = set(moved)
        for field, node in found['moves']:
            if field in out:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"field `{field}` was already moved out of `self`",
                    node.line, node.column,
                    hint="a consuming body moves each field at most once"
                )
            out.add(field)
        for field, node in found['reads']:
            if field in out and field in declared:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of `self.{field}` after it was moved out",
                    node.line, node.column,
                    hint="the field's value left with the move; read it before "
                         "moving, or bind it to a local first"
                )
        return frozenset(out)

    def _consumes_scan(self, expr: Optional[Expression]) -> dict:
        """Every `move self.<f>` and every `self.<f>` read inside `expr`.

        Walks the whole subtree EXCEPT nested blocks and closure bodies — a
        closure capture of a consumed receiver is refused where the capture
        rules already live, and a nested block belongs to the statement walk.
        """
        moves: List[Tuple[str, Expression]] = []
        reads: List[Tuple[str, Expression]] = []
        move_paths = set()

        def walk(node):
            if node is None or isinstance(node, (Block,)):
                return
            if isinstance(node, MoveExpr):
                field = _consumes_field_of(node)
                if field is not None:
                    moves.append((field, node))
                    move_paths.add(id(node.path))
                    return
            if isinstance(node, MemberAccess) and _names_receiver(node.object):
                if id(node) not in move_paths:
                    reads.append((node.member, node))
            for child in self._consumes_children(node):
                walk(child)

        walk(expr)
        return {'moves': moves, 'reads': reads}

    def _consumes_children(self, node):
        """The expression children of one node, blocks excluded."""
        from dataclasses import fields as dc_fields
        try:
            names = [f.name for f in dc_fields(node)]
        except TypeError:
            return []
        out = []
        for name in names:
            value = getattr(node, name, None)
            if isinstance(value, Expression) and not isinstance(value, Block):
                out.append(value)
            elif isinstance(value, list):
                for item in value:
                    inner = getattr(item, 'value', item)
                    if isinstance(inner, Expression) and not isinstance(inner, Block):
                        out.append(inner)
        return out

    def _consumes_refuse_in(self, node, declared: List[str], where: str,
                            why: Optional[str]) -> None:
        """Refuse a field move in a position this walk does not decide."""
        found = self._consumes_scan_deep(node)
        for field, m in found:
            reason = why or ("the rule decides each field on every path or "
                             "none, and this position is not one the check "
                             "can decide")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"`move self.{field}` is not supported in {where} "
                f"(design 260 v1): {reason}",
                m.line, m.column,
                hint="write the field move in the body's straight-line "
                     "statements, an `if`/`else`, or a `match` arm — or use "
                     f"`self.{field}.take()`, which needs no all-paths rule"
            )

    def _consumes_scan_deep(self, node) -> List[Tuple[str, Expression]]:
        """Every `move self.<f>` anywhere under `node`, blocks included."""
        found: List[Tuple[str, Expression]] = []
        seen = set()

        def walk(n):
            # `Argument` is a plain dataclass, not an ASTNode, but it is the
            # wrapper every call's operands sit behind — so walk it too.
            if not isinstance(n, (ASTNode, Argument)) or id(n) in seen:
                return
            seen.add(id(n))
            if isinstance(n, MoveExpr):
                field = _consumes_field_of(n)
                if field is not None:
                    found.append((field, n))
            from dataclasses import fields as dc_fields
            try:
                names = [f.name for f in dc_fields(n)]
            except TypeError:
                return
            for name in names:
                value = getattr(n, name, None)
                if isinstance(value, ASTNode):
                    walk(value)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

        walk(node)
        return found

"""The place transform: lowering `borrows` declarations (design 141).

`lend` is a SUSPENSION, not a return. A `borrows` function runs to its `lend`,
PAUSES there with its frame alive while the caller's window code runs, and then
RESUMES through whatever follows — the epilogue — before it finishes. `-> T`
names the type of the place it lends, not the type of a returned value.

That is exactly the shape of a scoped-borrow callback, so that is what a
borrows declaration lowers to:

    func [](&self, i: Int) borrows -> T {         func [](&self, i: Int,
        if i < 0 || i >= self.length {                    __window: (&var T) sync -> __R
            panic("...")                     =>          ) sync -> __R {
        }                                         if i < 0 || i >= self.length {
        lend self.buffer![i]                          panic("...")
    }                                             }
                                                  return __window(&var self.buffer![i])
                                              }

so the common case emits exactly what `with_ref` emits today: one direct call,
one stack frame, nothing dynamic. A conditional lend (`borrows -> T?`) takes a
second closure for the absent path, so `return None` becomes `return
__absent()` and the window simply never opens.

**The receiver goes by POINTER even when the author wrote `&self`** (design 146,
DF-146b). `lend self.cells[i]` becomes `__window(&var self.cells[i])`, and a
`&self` receiver arrives as a COPY -- so that `&var` would address the callee's
copy and an exclusive window's write would be thrown away. `place_self_by_pointer`
(read through `ast_nodes.self_by_pointer`) fixes that at the ABI, which is what
lets design 141 decision 3 hold: one body, both flavors, the use site choosing.
The polymorphism is confined to the `lend` -- its `&var` is marked `from_lend`
and is the single exception to the rule that a `&var` projection out of a `&self`
receiver is an error, so a field write or a stray `&var self.x` in the prologue
or epilogue is rejected exactly as it is in any other `&self` method.

**The epilogue and tail duplication.** Statements after the `lend` run when the
window closes, so the call cannot stay in return position:

    lend self.slot                                let __wr0 = __window(&var self.slot)
    self.dirty = true                    =>       self.dirty = true
                                                  return __wr0

The epilogue is the `lend`'s CONTINUATION — the rest of its block, then the
rest of each enclosing block — and it is spliced in at the lend site rather
than left where it was written. That keeps every prologue local in scope for
the epilogue that reads it (the lock-and-release shape), with no frame struct
and no state machine. Duplicating the tail is sound precisely because of the
coverage rule: a path that lends cannot reach another lend, so the tail belongs
to that one window.

**Tail position keeps the `return` off** (design 146, DF-146d). Where the block
being rewritten IS the accessor's result — the body itself, or a match arm in a
body-final match — the window call stays an EXPRESSION and the block yields it:

    match self.slots[i] {                         match self.slots[i] {
        case Filled(_, r) -> { lend r },   =>         case Filled(_, r) -> { __window(&var r) },
        case Empty -> { return None }                 case Empty -> { __absent() }
    }                                             }

That is not cosmetic. A `return` inside a match arm makes the USE-SITE lowering
refuse to move the match into a window (a window is a closure, so the `return`
would leave the window rather than the accessor) — and without the window the
scrutinee is read out as a VALUE, which is exactly what lending an enum payload
exists to avoid. An epilogue keeps the tail form too: the sequence simply ends
in `__wr` instead of returning it.

**`#lend_var`: one authored accessor, two specializations** (design 179). The
body cannot see which window flavor is coming, but the COMPILER can — every use
site's flavor is static. A body that names the constant is therefore emitted
TWICE, here, before the checker runs:

    func [](&self, i) borrows -> UInt8 {          func [](&self, i) borrows -> UInt8 {
        if #lend_var {                     =>        <bounds check>
            self.separate_if_shared()                lend ...
        }                                        }
        <bounds check>                           func __lend_var_[](&var self, i) borrows -> UInt8 {
        lend ...                                     self.separate_if_shared()
    }                                                <bounds check>
                                                     lend ...
                                                 }

The authored declaration keeps `&self` and folds the constant FALSE, so the
gate is gone from the tree before anything checks it and the copy is an
honestly non-mutating `&self` body a `let` root may call. The twin takes
`&var self`, folds TRUE, and keeps the gate; `place_uses` retargets an
exclusive use site at it, and the re-check that already follows the use-site
lowering checks the retarget like any other call.

Nothing here needs a per-specialization checking mode, because the
specialization set is {shared, exclusive} — fixed, and known with no caller
information. Nothing needs mangler work either: the accessor's symbol key is
the window's result type `__R` and the flavor was never part of it, so two
METHOD NAMES are two symbol families and `mangle_method` composes them as it
composes any other.

The transform runs BEFORE type checking, inside `parse_source`, so everything
downstream — registration, inference, monomorphization, codegen — sees an
ordinary generic method and needs to know nothing about places. The
parser-stage AST dump (`tools/dump_ast.py`) builds its own parser and so still
dumps the authored form, which is what a parser oracle should show.
"""

import copy
import dataclasses
from typing import List

from ast_nodes import (
    Argument, ArrayIndex, BinaryOp, Block, BoolLiteral, BreakStatement,
    ClosureExpr, ContinueStatement, ExpressionStatement, ForceUnwrap, ForLoop,
    FunctionCall, GuardLetStatement, Identifier, IfExpr, IfLetExpr,
    LendStatement, LendVarLiteral, LetStatement, MatchExpr, MemberAccess,
    MethodCall, NoneLiteral, Parameter, Program, ReferenceExpr, ReturnStatement,
    SawType, SelfExpr, TupleIndex, TypeKind, TypeParameter, UnaryOp, WhileExpr,
    structural_fields,
)
from errors import ErrorKind


# The synthesized names. Every one carries the reserved `__` prefix, so none can
# collide with a name the author could have written.
WINDOW_PARAM = "__window"
ABSENT_PARAM = "__absent"
RESULT_TYPE_PARAM = "__R"
_EPILOGUE_LOCAL = "__wr"
# The exclusive specialization's method name (design 179). A DISTINCT NAME is
# the whole of the mangling story: `mangle_method` composes the receiver's
# specialization with the method name, so two names are two symbol families and
# the mangler needs no new key component, no ordering decision, and no new
# determinism surface. The flavor was never part of the accessor's symbol key —
# that key is the window's result type `__R` — so nothing about it moves.
_VAR_TWIN_PREFIX = "__lend_var_"


def var_twin_name(method_name: str) -> str:
    """The exclusive specialization's name for an accessor named `method_name`."""
    return _VAR_TWIN_PREFIX + method_name

# How a path through a block leaves it.
_FALL, _LEND, _ABSENT, _DIVERGE = 'fall', 'lend', 'absent', 'diverge'


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def transform_places(program: Program, reporter, source_file: str = "") -> bool:
    """Lower every `borrows` declaration in `program`. Returns True if any was.

    Errors go to `reporter`; a declaration that fails validation is left
    un-lowered, so the type checker reports against the authored form rather
    than against a half-built rewrite.
    """
    tx = _PlaceTransform(reporter, source_file)
    tx.run(program)
    return tx.changed


class _PlaceTransform:
    def __init__(self, reporter, source_file: str):
        self.reporter = reporter
        self.source_file = source_file
        self.changed = False
        self._epilogue_counter = 0

    # -- traversal ---------------------------------------------------------

    def run(self, program: Program) -> None:
        for func in getattr(program, 'functions', []) or []:
            if getattr(func, 'is_borrows', False):
                if _mentions_lend_var(getattr(func, 'body', None)):
                    self._error(
                        func,
                        "`#lend_var` chooses between a SHARED and an EXCLUSIVE "
                        "receiver, so it belongs in an accessor that has one. "
                        "A free `borrows` function has no receiver to borrow "
                        "either way")
                    _fold_lend_var(func.body, False)
                self._lower(func, is_method=False)
        for ext in getattr(program, 'extensions', []) or []:
            twins = []
            for method in list(getattr(ext, 'methods', []) or []):
                if not getattr(method, 'is_borrows', False):
                    continue
                twin = self._specialize(method)
                self._lower(method, is_method=True)
                if twin is not None:
                    self._lower(twin, is_method=True)
                    twins.append(twin)
            if twins:
                ext.methods.extend(twins)
        # Inline `module X { ... }` bodies are separate Programs.
        for decl in getattr(program, 'module_decls', []) or []:
            body = getattr(decl, 'body', None)
            if body is not None:
                self.run(body)

    # -- `#lend_var`: the two specializations (design 179) ------------------

    def _specialize(self, decl):
        """Fold `#lend_var` and hand back the exclusive twin, or None.

        An accessor whose body never names the constant compiles ONCE, exactly
        as it did before — this returns None and nothing else happens, so the
        unflavored majority pays no code-size tax by construction.

        One that DOES name it compiles TWICE:

          * the authored declaration keeps its `&self` receiver and is folded
            with the constant FALSE. Whatever the constant gated is gone from
            the tree before the checker sees it, so the copy is checked as an
            ordinary non-mutating `&self` body by machinery that needs to know
            nothing about any of this — and a `let` root can call it;
          * a synthesized sibling under a reserved name takes `&var self` and is
            folded TRUE, keeping the gate. `place_uses` retargets an exclusive
            use site at it, and pass 2 re-checks the retarget honestly.

        The specialization set is fixed at {shared, exclusive} and known with no
        caller information at all — unlike a const generic, whose set is
        caller-derived — which is exactly why this can be a source-level
        duplication in a pass that already runs before the type checker rather
        than a per-specialization checking mode the checker does not have.
        """
        if not _mentions_lend_var(decl.body):
            return None
        if getattr(decl, 'self_mutable', False):
            # In a `&var self` accessor every use site is already exclusive, so
            # the constant is always true and the branch always live. A silently
            # always-true constant reads as a live decision, which would mislead
            # every later reader of the body.
            self._error(
                decl,
                "`#lend_var` is always true in a `&var self` accessor — every "
                "use site of one already borrows the receiver exclusively, so "
                "there is only one specialization and the constant decides "
                "nothing. Declare the receiver `&self` to get both")
            _fold_lend_var(decl.body, True)
            return None
        twin = copy.deepcopy(decl)
        twin.name = var_twin_name(decl.name)
        twin.self_mutable = True
        twin.place_var_twin = True
        twin.doc = None
        decl.place_lend_var = True
        _fold_lend_var(twin.body, True)
        _fold_lend_var(decl.body, False)
        return twin

    # -- lowering ----------------------------------------------------------

    def _lower(self, decl, is_method: bool) -> None:
        declared = decl.return_type
        place_optional = declared is not None and declared.kind == TypeKind.OPTIONAL
        if declared is None or declared.kind == TypeKind.VOID:
            self._error(decl,
                        "a `borrows` declaration must name the place it lends "
                        "— write `borrows -> T`. There is no such thing as a "
                        "window onto nothing")
            return
        inner = declared.inner_type if place_optional else declared
        if inner is None:
            self._error(decl, "a `borrows -> T?` declaration must name `T`")
            return

        if is_method and not self._validate_receiver(decl):
            return

        if not self._validate(decl, place_optional):
            return

        result_ty = SawType(TypeKind.TYPE_PARAM,
                            type_param_name=RESULT_TYPE_PARAM)

        # `__window` receives the place as `&var T` whatever the use site does
        # with it. Shared-versus-exclusive is a property of the USE SITE, not of
        # the declaration — one body serves both flavors — and it is settled by
        # the Law of Exclusivity where the window opens, not by this signature.
        window_ty = SawType(
            TypeKind.FUNCTION,
            param_types=[SawType(TypeKind.REFERENCE, inner_type=inner,
                                 reference_mutable=True)],
            func_return_type=result_ty,
            func_is_sync=True)
        params = list(decl.parameters) + [
            Parameter(name=WINDOW_PARAM, type=window_ty)]

        if place_optional:
            # The absent path of a conditional lend: no window opens, no
            # epilogue runs, and the caller decides what "absent" means (None
            # for a value read, a panic for a force-unwrap).
            params.append(Parameter(
                name=ABSENT_PARAM,
                type=SawType(TypeKind.FUNCTION, param_types=[],
                             func_return_type=result_ty, func_is_sync=True)))

        new_body = self._rewrite_block(decl.body, [], place_optional, tail=True)

        decl.parameters = params
        decl.type_params = list(decl.type_params or []) + [
            TypeParameter(name=RESULT_TYPE_PARAM, bounds=[], default=None,
                          line=decl.line, column=decl.column)]
        decl.return_type = result_ty
        decl.body = new_body
        # A place window may not span a suspension (v1 fence): the root stays
        # borrowed for the whole window, so yielding to the scheduler with one
        # open would let another task invalidate it. `sync` is the existing
        # machinery for exactly that, and it is what `with_ref` already uses.
        decl.is_sync = True
        decl.place_type = inner
        decl.place_optional = place_optional
        # The receiver travels as a POINTER from here on, whichever flavor the
        # author spelled (design 146, DF-146b): the place this body lends is
        # storage inside the receiver, and an exclusive window has to reach the
        # CALLER's storage to write through it. `self_by_pointer` is what codegen
        # consults; the checker still sees a plain `&self` body, so a field write
        # or a stray `&var self.x` in the prologue stays the error it always was.
        if is_method and not getattr(decl, 'is_static', False):
            decl.place_self_by_pointer = True
        self.changed = True

    # -- body rewrite ------------------------------------------------------

    def _rewrite_block(self, block: Block, cont: List, place_optional: bool,
                       tail: bool = False) -> Block:
        stmts = list(block.statements)
        if block.final_expr is not None:
            stmts.append(ExpressionStatement(
                expression=block.final_expr,
                line=block.final_expr.line,
                column=block.final_expr.column))

        out = []
        for j, stmt in enumerate(stmts):
            rest = stmts[j + 1:]
            # TAIL position: this block's value IS the accessor's result, so the
            # window call can stay an EXPRESSION rather than become a `return`.
            # That is what keeps a lending `match` free of `return` statements —
            # and the use-site lowering needs it free of them, because a window
            # is a closure and a `return` inside one would leave the window
            # rather than the accessor (design 146). A match whose arms are
            # expressions is matched WHERE IT SITS, which is the whole point of
            # lending an enum payload.
            # An EPILOGUE does not cost the tail form: the statements after the
            # `lend` run inside this block and the window's result is still the
            # block's value, so the sequence ends in `__wr` instead of
            # `return __wr`. Only a nested continuation (`cont`) forces the
            # return form, because then the value belongs to an enclosing block.
            at_tail = tail and not cont

            if isinstance(stmt, LendStatement):
                if at_tail:
                    seq, value = self._lend_tail(stmt, rest, place_optional)
                    out.extend(seq)
                    return _block_like(block, out, value)
                out.extend(self._lend_sequence(stmt, rest + cont, place_optional))
                return _block_like(block, out)

            if _is_return_none(stmt):
                absent = _call(ABSENT_PARAM, [], stmt)
                if at_tail:
                    return _block_like(block, out, absent)
                out.append(ReturnStatement(value=absent,
                                           line=stmt.line, column=stmt.column))
                return _block_like(block, out)

            if _contains(stmt, LendStatement):
                # A branch below lends, so everything after this statement is
                # the epilogue of those windows and moves into them.
                as_expr = (at_tail and not rest
                           and isinstance(_ctrl(stmt), MatchExpr))
                rewritten = self._rewrite_container(stmt, rest + cont,
                                                    place_optional, as_expr)
                if as_expr:
                    return _block_like(block, out, _ctrl(rewritten))
                out.append(rewritten)
                return _block_like(block, out)

            out.append(self._rewrite_absent_only(stmt, place_optional))

        return _block_like(block, out)

    def _rewrite_container(self, stmt, cont: List, place_optional: bool,
                           tail: bool = False):
        """Recurse into a control-flow statement that lends on some path."""
        ctrl = _ctrl(stmt)

        if isinstance(ctrl, (IfExpr, IfLetExpr)):
            ctrl.then_branch = self._rewrite_block(ctrl.then_branch, cont,
                                                   place_optional)
            if ctrl.else_branch is not None:
                ctrl.else_branch = self._rewrite_block(ctrl.else_branch, cont,
                                                       place_optional)
            return stmt

        if isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    arm.body = self._rewrite_block(arm.body, cont,
                                                   place_optional, tail)
            return stmt

        if isinstance(ctrl, GuardLetStatement):
            ctrl.else_branch = self._rewrite_block(ctrl.else_branch, cont,
                                                   place_optional)
            return stmt

        return stmt

    def _rewrite_absent_only(self, stmt, place_optional: bool):
        """Rewrite `return None` inside a statement that does not lend."""
        ctrl = stmt.expression if isinstance(stmt, ExpressionStatement) else stmt

        if isinstance(ctrl, (IfExpr, IfLetExpr)):
            ctrl.then_branch = self._rewrite_block(ctrl.then_branch, [],
                                                   place_optional)
            if ctrl.else_branch is not None:
                ctrl.else_branch = self._rewrite_block(ctrl.else_branch, [],
                                                       place_optional)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    arm.body = self._rewrite_block(arm.body, [], place_optional)
        elif isinstance(ctrl, GuardLetStatement):
            ctrl.else_branch = self._rewrite_block(ctrl.else_branch, [],
                                                  place_optional)
        elif isinstance(ctrl, (WhileExpr, ForLoop)):
            ctrl.body = self._rewrite_block(ctrl.body, [], place_optional)
        return stmt

    def _window_expr(self, stmt: LendStatement) -> FunctionCall:
        """`lend X` as the call that opens the window."""
        return _call(
            WINDOW_PARAM,
            [ReferenceExpr(expr=stmt.place, mutable=True,
                           in_argument_position=True, from_lend=True,
                           line=stmt.place.line, column=stmt.place.column)],
            stmt)

    def _lend_tail(self, stmt: LendStatement, epilogue: List,
                   place_optional: bool):
        """`lend X` in TAIL position: statements plus the block's value.

        Same shape as `_lend_sequence`, minus the `return` — which is the whole
        point, since a `return` in a match arm keeps the use-site lowering from
        matching the scrutinee where it sits.
        """
        window_call = self._window_expr(stmt)
        if not epilogue:
            return [], window_call
        name = f"{_EPILOGUE_LOCAL}{self._epilogue_counter}"
        self._epilogue_counter += 1
        seq = [LetStatement(name=name, type_annotation=None,
                            value=window_call, mutable=False,
                            line=stmt.line, column=stmt.column)]
        for s in epilogue:
            seq.append(self._rewrite_absent_only(copy.deepcopy(s),
                                                 place_optional))
        return seq, Identifier(name=name, line=stmt.line, column=stmt.column)

    def _lend_sequence(self, stmt: LendStatement, tail: List,
                       place_optional: bool) -> List:
        """`lend X` plus its epilogue, as ordinary statements."""
        window_call = self._window_expr(stmt)

        if not tail:
            # The overwhelmingly common shape: no epilogue, so the window call
            # stays in return position and the whole accessor is one call.
            return [ReturnStatement(value=window_call,
                                    line=stmt.line, column=stmt.column)]

        # An epilogue: hold the window's result, run the epilogue, hand the
        # result back. Deliberately NOT `move` — the binding's type is the
        # unbounded `__R`, and a plain return of a local at its last use is
        # already a transfer, so this stays sound for a NoCopy `__R` and legal
        # for a `Void` one.
        name = f"{_EPILOGUE_LOCAL}{self._epilogue_counter}"
        self._epilogue_counter += 1
        seq = [LetStatement(name=name, type_annotation=None,
                            value=window_call, mutable=False,
                            line=stmt.line, column=stmt.column)]
        for s in tail:
            seq.append(self._rewrite_absent_only(copy.deepcopy(s),
                                                 place_optional))
        seq.append(ReturnStatement(
            value=Identifier(name=name, line=stmt.line, column=stmt.column),
            line=stmt.line, column=stmt.column))
        return seq

    # -- validation --------------------------------------------------------

    def _validate_receiver(self, decl) -> bool:
        """A borrows METHOD lends storage out of its receiver, so it must borrow
        that receiver rather than take a copy of it (design 146, DF-146b)."""
        if getattr(decl, 'is_static', False) or getattr(decl, 'is_init', False):
            self._error(
                decl,
                "a `borrows` accessor lends storage out of a receiver, so it "
                "needs one — `init` builds a value and a static method has no "
                "receiver at all")
            return False
        params = list(decl.parameters or [])
        if not params or params[0].name != "self":
            self._error(
                decl,
                "a `borrows` accessor lends storage out of a receiver, so it "
                "needs one — declare it `func name(&self, ...) borrows -> T`")
            return False
        if not getattr(decl, 'self_is_reference', False):
            self._error(
                decl,
                "a `borrows` accessor must take its receiver BY REFERENCE — "
                "write `&self` (the receiver is then borrowed with each use "
                "site's window flavor) or `&var self` (every use site borrows "
                "it exclusively). A by-value `self` is a copy, and the place "
                "lent out of it would be gone before the window opened")
            return False
        return True

    def _validate(self, decl, place_optional: bool) -> bool:
        """The coverage rule. Returns True if the body may be lowered."""
        self._ok = True
        self._optional = place_optional
        self._lend_seen = False
        self._arms = []
        self._is_method = not getattr(decl, 'is_static', False) and bool(
            decl.parameters) and decl.parameters[0].name == "self"
        self._through_self = _bindings_reached_through_self(decl.body)
        outcome = self._walk_block(decl.body, in_loop=False)

        # A more specific diagnostic (a branch that forgets to lend, a `lend`
        # in a loop) already named the spot; the whole-body message would only
        # repeat it one indent out.
        if outcome == _FALL and self._ok:
            if self._lend_seen:
                self._error(
                    decl,
                    "not every path through this `borrows` body lends. Each "
                    "path must `lend` a place"
                    + (", `return None`, or diverge first" if place_optional
                       else " or diverge first — declare the place `-> T?` if "
                            "it can be absent"))
            else:
                self._error(
                    decl,
                    "a `borrows` body must `lend` a place — this one never "
                    "does. `borrows -> T` promises the caller a window onto "
                    "storage of type `T`, and without a `lend` there is "
                    "nothing to open it onto")
            self._ok = False
        return self._ok

    def _walk_block(self, block: Block, in_loop: bool) -> str:
        stmts = list(block.statements)
        if block.final_expr is not None:
            stmts.append(ExpressionStatement(
                expression=block.final_expr,
                line=block.final_expr.line,
                column=block.final_expr.column))

        outcome = _FALL
        for stmt in stmts:
            if outcome in (_LEND, _ABSENT):
                # The epilogue. It may not lend again (exactly-once) and may not
                # return: the window's result is already in hand and the body
                # ends when the epilogue does.
                self._reject_in_epilogue(stmt)
                continue
            if outcome == _DIVERGE:
                continue
            outcome = self._walk_stmt(stmt, in_loop)
        return outcome

    def _walk_stmt(self, stmt, in_loop: bool) -> str:
        if isinstance(stmt, LendStatement):
            if in_loop:
                self._error(
                    stmt,
                    "`lend` may not appear inside a loop — a loop would lend "
                    "more than once, and the first window's epilogue would "
                    "have to interleave with the second window's prologue. "
                    "Lend once, after the loop has chosen the place")
                self._ok = False
            if not _is_place_expr(stmt.place):
                self._error(
                    stmt.place,
                    "`lend` needs a PLACE — storage that already exists, such "
                    "as a field, an element or a deref. This expression builds "
                    "a temporary, which would be gone before the caller's "
                    "window opened")
                self._ok = False
            else:
                self._claim_payload_lend(stmt)
                self._check_rooted_in_receiver(stmt)
            self._lend_seen = True
            return _LEND

        if isinstance(stmt, ReturnStatement):
            return self._walk_return(stmt)

        if isinstance(stmt, (BreakStatement, ContinueStatement)):
            return _FALL

        ctrl = stmt.expression if isinstance(stmt, ExpressionStatement) else stmt

        if _diverges(ctrl):
            return _DIVERGE

        if isinstance(ctrl, (IfExpr, IfLetExpr)):
            then_out = self._walk_block(ctrl.then_branch, in_loop)
            if ctrl.else_branch is None:
                # A one-armed `if` always has the untaken path, which falls
                # through — so lending only inside it covers half the body.
                self._join_check(stmt, then_out, _FALL)
                return _FALL
            return self._join(stmt, then_out,
                              self._walk_block(ctrl.else_branch, in_loop))

        if isinstance(ctrl, GuardLetStatement):
            if self._walk_block(ctrl.else_branch, in_loop) == _LEND:
                self._error(
                    ctrl,
                    "a `guard` else branch may not `lend` — it runs on the "
                    "path where the guard FAILED, so the place it would lend "
                    "is the one the guard just proved absent")
                self._ok = False
            return _FALL

        if isinstance(ctrl, MatchExpr):
            outs = []
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._arms.append((ctrl, arm))
                    outs.append(self._walk_block(arm.body, in_loop))
                    self._arms.pop()
                elif _diverges(arm.body):
                    outs.append(_DIVERGE)
                else:
                    self._reject_lend_in_closure(arm)
                    outs.append(_FALL)
            if not outs:
                return _FALL
            joined = outs[0]
            for o in outs[1:]:
                joined = self._join(stmt, joined, o)
            return joined

        if isinstance(ctrl, (WhileExpr, ForLoop)):
            self._walk_block(ctrl.body, in_loop=True)
            return _FALL

        self._reject_lend_in_closure(stmt)
        return _FALL

    def _claim_payload_lend(self, stmt: LendStatement) -> None:
        """`lend v` where `v` is a MATCH-ARM binding: the place is an ENUM
        PAYLOAD (design 146, DF-146d).

        A match arm binds the payload, and design 146 already matches a place
        WHERE IT SITS — so `case Occupied(_, v) -> lend v` names storage the
        container still holds. The arm records which of its bindings was lent,
        and codegen writes that binding back into the scrutinee when the window
        closes. Copy-in/copy-out is indistinguishable from aliasing here: the
        window borrows the scrutinee's ROOT for its whole extent, so the Law of
        Exclusivity already freezes the enum — tag included — and nothing else
        can look at the slot while the payload is out. It is also the only
        spelling that keeps the lent pointer properly aligned, since an enum's
        payload is a byte array sitting behind a 4-byte tag.

        The scrutinee must therefore be storage reached THROUGH THE RECEIVER. A
        `match` on a value the body just built would lend a temporary that dies
        with the accessor, and the caller's write would go nowhere.
        """
        root = _place_root(stmt.place)
        if root is None:
            return
        for ctrl, arm in reversed(self._arms):
            if root not in (arm.bindings or []):
                continue
            if not _rooted_at_self(ctrl.matched_expr):
                self._error(
                    stmt.place,
                    f"`lend {root}` names the payload of a `match` on "
                    "something other than the receiver's own storage, so the "
                    "window would open onto a value that dies with this "
                    "accessor. Match on a field, an element, or another place "
                    "reached through `self` — the payload is then lent where "
                    "it sits")
                self._ok = False
                return
            lent = list(getattr(arm, 'lent_bindings', None) or [])
            if root not in lent:
                lent.append(root)
            arm.lent_bindings = lent
            return

    def _check_rooted_in_receiver(self, stmt: LendStatement) -> None:
        """The lent place must be storage reached through the RECEIVER
        (DF-188g, design 188 unit 3).

        `lend` pauses the accessor with its frame alive, so a window over an
        accessor-LOCAL addresses live storage and a READ through it is sound —
        which is exactly what made this quiet. The WRITE has nowhere to land:
        the slot dies when the accessor resumes, so `c.slot() = 99` compiled and
        was a silent no-op. The rule the spec already states for a match arm ("a
        payload of a value the body just BUILT dies with the accessor") is the
        same rule; it just was not applied to a plain `lend <local>`.

        RULED (user, Aug 9) in its NARROW form: an accessor's PARAMETER is
        refused too, even where the storage would outlive the window (a `&var`
        param). Widening later to an outlives-based rule stays compatible; the
        reverse migration would not.

        Two things are rooted in the receiver and are not `self.…` on their
        face. A MATCH-ARM binding is one — `_claim_payload_lend` has already
        proved that arm's scrutinee is receiver-rooted, and the payload is lent
        where it sits. An INDIRECTION out of the receiver is the other: `if let
        buf = self.buffer { lend buf[i] }` (std `Vector`) and `let bytes =
        self.byte_ptr() as UnsafePointer<UInt8>  lend bytes[i]` (std `Data`)
        both reach HEAP storage the receiver only points at, which no more dies
        with the accessor than a field does. The binding must be derived from
        the receiver AND the lend must project through it — `lend buf` on its
        own would hand out the frame's copy of the pointer.
        """
        if _rooted_at_self(stmt.place):
            return
        root = _place_root(stmt.place)
        if root is None:
            return
        for _ctrl_expr, arm in self._arms:
            if root in (arm.bindings or []):
                return                     # the payload lend, already judged
        if root in self._through_self and not isinstance(stmt.place, Identifier):
            return                         # an indirection out of the receiver
        if not self._is_method:
            # A free `borrows` function has no receiver to be rooted in, so
            # there is nothing it could lend. Say that rather than describing a
            # receiver the declaration does not have.
            self._error(
                stmt.place,
                f"`lend {root}` names storage this function owns, and a window "
                f"onto it would open on a frame that dies when the function "
                f"resumes. A `borrows` declaration lends storage its RECEIVER "
                f"already owns — declare it as a method (`func name(&self, ...) "
                f"borrows -> T`) and lend a place reached through `self`")
            self._ok = False
            return
        self._error(
            stmt.place,
            f"`lend {root}` is not rooted in the receiver: `{root}` is this "
            f"accessor's own local or parameter, so the window would open onto "
            f"storage that dies when the accessor resumes. A read through it "
            f"would work and a WRITE would silently go nowhere. A `borrows` "
            f"accessor lends storage the receiver already owns — lend a field, "
            f"an element, or another place reached through `self` (an "
            f"indirection the receiver holds counts: `if let buf = self.buffer "
            f"{{ lend buf[i] }}` lends the heap storage `self` points at). To "
            f"hand back a computed value, return it from an ordinary method "
            f"instead")
        self._ok = False

    def _walk_return(self, stmt: ReturnStatement) -> str:
        value = stmt.value
        if value is None:
            self._error(
                stmt,
                "a bare `return` in a `borrows` body ends the function without "
                "lending. Every path must `lend` a place"
                + (", or `return None` for the absent path" if self._optional
                   else ""))
            self._ok = False
            return _DIVERGE
        if isinstance(value, NoneLiteral):
            if not self._optional:
                self._error(
                    stmt,
                    "`return None` needs an optional place — declare the "
                    "accessor `borrows -> T?` and this becomes the absent path "
                    "of a conditional lend, where no window opens and no "
                    "epilogue runs. As declared, every path must lend")
                self._ok = False
                return _DIVERGE
            return _ABSENT
        self._error(
            stmt,
            "a `borrows` body returns no value — it LENDS a place. Write "
            "`lend <place>` instead of `return <value>`: `-> T` names the type "
            "of the place, not of a returned value")
        self._ok = False
        return _DIVERGE

    def _join(self, stmt, a: str, b: str) -> str:
        self._join_check(stmt, a, b)
        if a == b:
            return a
        outs = {a, b}
        if _FALL in outs:
            return _FALL
        if _DIVERGE in outs:
            return (outs - {_DIVERGE}).pop()
        return _LEND  # {lend, absent}: a conditional lend, which is the point

    def _join_check(self, stmt, a: str, b: str) -> None:
        if _LEND in (a, b) and _FALL in (a, b):
            self._error(
                stmt,
                "one branch here lends and the other falls through without "
                "lending. Every path through a `borrows` body lends exactly "
                "once"
                + (", returns None, or diverges" if self._optional
                   else " or diverges — declare the place `-> T?` if it can be "
                        "absent"))
            self._ok = False

    def _reject_in_epilogue(self, stmt) -> None:
        for node in _walk(stmt):
            if isinstance(node, LendStatement):
                self._error(
                    node,
                    "this path lends twice. A `borrows` body lends exactly "
                    "once per path: statements after the `lend` are the "
                    "EPILOGUE, which runs when the caller's window closes")
                self._ok = False
                return
            if isinstance(node, ReturnStatement):
                self._error(
                    node,
                    "a `return` may not appear after `lend` — the window's "
                    "result is already in hand, and the body finishes when the "
                    "epilogue does")
                self._ok = False
                return

    def _reject_lend_in_closure(self, node) -> None:
        for sub in _walk(node):
            if isinstance(sub, ClosureExpr):
                for inner in _walk(sub):
                    if isinstance(inner, LendStatement):
                        self._error(
                            inner,
                            "`lend` may not appear inside a closure — it "
                            "suspends the enclosing `borrows` function, and a "
                            "closure body is not that function")
                        self._ok = False
                        return

    # -- reporting ---------------------------------------------------------

    def _error(self, node, message: str) -> None:
        self.reporter.error(ErrorKind.TYPE_MISMATCH, message,
                            getattr(node, 'line', 0) or 0,
                            getattr(node, 'column', 0) or 1,
                            None, self.source_file)


# ---------------------------------------------------------------------------
# `#lend_var`: folding the constant (design 179)
# ---------------------------------------------------------------------------

def _mentions_lend_var(node) -> bool:
    return node is not None and _contains(node, LendVarLiteral)


def _fold_lend_var(block: Block, flavor: bool) -> None:
    """Fold `#lend_var` to `flavor` through `block`, PRUNING what it decides.

    Substituting the constant is not enough on its own. A branch left standing
    behind a `false` condition is still CHECKED, and the whole point of the
    shared specialization is that the copy-on-write gate — a `&var self` call
    inside a `&self` body — is not there to be checked. So the untaken branch
    has to leave no trace in the tree at all.

    An `if` STATEMENT whose condition folds to a constant is therefore REPLACED
    by the branch it takes, spliced into the enclosing statement list. That is
    also what makes a lending branch work (`if #lend_var { lend a } else
    { lend b }`): the coverage rule then sees one unconditional `lend`, which is
    the truth about the specialization it is looking at.

    Everywhere else the constant is an ordinary compile-time `Bool` —
    `let writing = #lend_var` folds and works — because pruning needs a
    statement list to splice into and an expression has none.
    """
    _fold_block(block, flavor)


def _fold_block(block: Block, flavor: bool) -> None:
    out = []
    for stmt in block.statements:
        out.extend(_fold_statement(stmt, flavor))
    # The TAIL is not in the statement list. A block's last expression statement
    # becomes its `final_expr`, so a gate written as the last thing in a body —
    # an EPILOGUE, which is exactly where one belongs — arrives here rather than
    # above, and pruning it means splicing the taken branch's statements out
    # plus adopting its own tail as this block's value. That preserves the
    # block's value exactly, so the splice is correct in expression position
    # too, not only in a `borrows` body.
    tail = block.final_expr
    while isinstance(tail, IfExpr):
        tail.condition = _fold_node(tail.condition, flavor)
        taken = _const_bool(tail.condition)
        if taken is None:
            break
        kept = tail.then_branch if taken else tail.else_branch
        if kept is None:
            tail = None
            break
        _fold_block(kept, flavor)
        out.extend(kept.statements)
        tail = kept.final_expr
    block.statements = out
    block.final_expr = _fold_node(tail, flavor) if tail is not None else None


def _fold_statement(stmt, flavor: bool) -> List:
    """One statement, folded — as a LIST, because a pruned `if` may vanish."""
    ctrl = _ctrl(stmt)
    if isinstance(ctrl, IfExpr):
        ctrl.condition = _fold_node(ctrl.condition, flavor)
        taken = _const_bool(ctrl.condition)
        if taken is not None:
            kept = ctrl.then_branch if taken else ctrl.else_branch
            if kept is None:
                return []
            _fold_block(kept, flavor)
            spliced = list(kept.statements)
            if kept.final_expr is not None:
                spliced.append(ExpressionStatement(
                    expression=kept.final_expr,
                    line=kept.final_expr.line,
                    column=kept.final_expr.column))
            return spliced
    return [_fold_node(stmt, flavor)]


def _fold_node(node, flavor: bool):
    """`node` with the constant folded and every nested block pruned."""
    if node is None or isinstance(node, SawType):
        return node
    if isinstance(node, LendVarLiteral):
        return BoolLiteral(value=flavor, line=node.line, column=node.column)
    if isinstance(node, Block):
        _fold_block(node, flavor)
        return node
    if not dataclasses.is_dataclass(node):
        return node
    for f in structural_fields(node):
        value = getattr(node, f.name, None)
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = (tuple(_fold_node(x, flavor) for x in item)
                            if isinstance(item, tuple)
                            else _fold_node(item, flavor))
        elif not isinstance(value, (str, bytes)):
            setattr(node, f.name, _fold_node(value, flavor))
    return node


def _const_bool(expr):
    """The compile-time `Bool` this condition folds to, or None.

    Only what the constant itself can decide: the bare literal, `not`, and the
    short-circuit operators whose LEFT side is already constant. A condition
    that still depends on the receiver stays a runtime condition in the
    specialization that keeps it — which is right, and is how
    `if #lend_var && self.shared` means "gate, but only when it is shared".
    """
    if isinstance(expr, BoolLiteral):
        return expr.value
    if isinstance(expr, UnaryOp) and expr.op == 'not':
        inner = _const_bool(expr.operand)
        return None if inner is None else (not inner)
    if isinstance(expr, BinaryOp) and expr.op in ('&&', '||'):
        left = _const_bool(expr.left)
        if left is None:
            return None
        if expr.op == '&&':
            return _const_bool(expr.right) if left else False
        return True if left else _const_bool(expr.right)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_like(block: Block, statements: List, final_expr=None) -> Block:
    return Block(statements=statements, final_expr=final_expr,
                 line=block.line, column=block.column)


def _ctrl(stmt):
    """The control-flow expression a statement carries, or the statement."""
    return stmt.expression if isinstance(stmt, ExpressionStatement) else stmt


def _call(name: str, args: List, at) -> FunctionCall:
    return FunctionCall(
        name=name,
        arguments=[Argument(value=a) for a in args],
        line=getattr(at, 'line', 0), column=getattr(at, 'column', 0))


def _is_return_none(stmt) -> bool:
    return isinstance(stmt, ReturnStatement) and isinstance(stmt.value,
                                                            NoneLiteral)


def _diverges(expr) -> bool:
    """True for an expression that never comes back — today, `panic(...)`.

    The accessor rule (design 130 r8) makes a borrows body on a safe type check
    its index in the prologue and panic out of range, so the panicking path has
    to count as covered without lending.
    """
    return (isinstance(expr, FunctionCall)
            and getattr(expr, 'name', None) in ('panic', 'unreachable'))


def _is_place_expr(expr) -> bool:
    """Syntactically, does this name storage rather than build a value?"""
    if isinstance(expr, ForceUnwrap):
        return _is_place_expr(expr.expr)
    return isinstance(expr, (Identifier, MemberAccess, ArrayIndex, TupleIndex,
                             SelfExpr))


def _place_root(expr):
    """The name a place expression is rooted at, or None for `self`/no root."""
    node = expr
    while node is not None:
        if isinstance(node, Identifier):
            return node.name
        if isinstance(node, MemberAccess):
            node = node.object
        elif isinstance(node, ArrayIndex):
            node = node.array_expr
        elif isinstance(node, TupleIndex):
            node = node.tuple_expr
        elif isinstance(node, ForceUnwrap):
            node = node.expr
        else:
            return None
    return None


def _bindings_reached_through_self(body) -> set:
    """Names bound, anywhere in `body`, from storage reached through `self`.

    The INDIRECTION half of design 188 unit 3's rooting rule: `if let buf =
    self.buffer` and `let bytes = self.byte_ptr() as UnsafePointer<UInt8>` both
    name storage the receiver points at, so a lend that PROJECTS through one is
    lending the receiver's own heap, not the accessor's frame. Collected over
    the whole body rather than per scope: erring toward accepting is right here,
    because the frame-storage cases this rule exists to catch (a computed local,
    a parameter) are never bound from the receiver at all.
    """
    names = set()
    for node in _walk(body):
        if isinstance(node, LetStatement):
            if _rooted_at_self(_through_casts(node.value)):
                names.add(node.name)
        elif isinstance(node, (IfLetExpr, GuardLetStatement)):
            if _rooted_at_self(_through_casts(node.optional_expr)):
                names.add(node.name)
    return names


def _through_casts(expr):
    """`expr` with any `as` casts peeled — a cast keeps the same storage."""
    from ast_nodes import CastExpr
    while isinstance(expr, CastExpr):
        expr = expr.expr
    return expr


def _rooted_at_self(expr) -> bool:
    """Is this scrutinee storage reached through the receiver?

    `self.slot`, `self.slots[i]`, `self.slots.get(i)!` — a field, an element,
    or another place hanging off `self`. A borrows accessor is entitled to lend
    out of its receiver and nothing else, so this is exactly the set of
    scrutinees whose payload survives the window.
    """
    node = expr
    while node is not None:
        if isinstance(node, SelfExpr):
            return True
        if isinstance(node, MemberAccess):
            node = node.object
        elif isinstance(node, MethodCall):
            node = node.object
        elif isinstance(node, ArrayIndex):
            node = node.array_expr
        elif isinstance(node, TupleIndex):
            node = node.tuple_expr
        elif isinstance(node, ForceUnwrap):
            node = node.expr
        else:
            return False
    return False


def _contains(node, kind) -> bool:
    return any(isinstance(n, kind) for n in _walk(node))


def _walk(node):
    """Every structural descendant of `node`, itself included.

    Uses `structural_fields`, so cross-pass annotations are not followed: an
    annotation may alias a node reachable elsewhere, which would make this
    visit the same `lend` twice.
    """
    stack = [node]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        if isinstance(cur, (list, tuple)):
            stack.extend(cur)
            continue
        if not dataclasses.is_dataclass(cur) or id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        for f in structural_fields(cur):
            stack.append(getattr(cur, f.name, None))

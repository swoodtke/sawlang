"""Place USE sites: synthesizing the window call (design 141, landed by 146).

`place_transform.py` lowers a `borrows` DECLARATION into a window-closure
method. This pass is the other half — it lowers the USES.

A place is not a value, and Saw gives it no spelling of its own: `&var` is legal
only as a call argument, so there is no way to hand storage out except by
calling something with it. That is exactly why `with_ref` takes a closure, and
it is why a use site becomes a closure call too:

    v[i].count += 1        =>   v.[](i, { __p0 in __p0.count += 1 })
    print(v[i].name)       =>   print(v.[](i, { __p0 in __p0.name }))
    f(&var v[i])           =>   v.[](i, { __p0 in f(&var __p0) })
    m["k"]!.items[2].on()  =>   m.[]("k", { __p0 in __p0.items.[](2,
                                    { __p1 in __p1.on() }) },
                                  { panic("...") })

**The window's extent is the smallest expression that turns the place back into
a value** — the chain suffix that follows it, or the whole call when the place
is handed over as a reference argument, or the whole statement when it is being
written to. That is the design-141 rule ("the smallest enclosing statement or
expression; for a reference argument, the call") read as a rewrite: whatever is
inside the closure runs while the window is open, and nothing else does.

**Multiple places in one call nest**, which is what makes their prologues run in
argument order and their epilogues run LIFO — the outermost window opens first
and closes last, for free, because that is what nesting means.

**`__R` comes from the typechecked tree.** The window closure's result type is
the type of the expression being replaced, which the checker already computed
and stamped as `resolved_type`. Passing it explicitly as the accessor's one
type argument means nothing here has to be inferred: a conditional lend's
present path (`{ __p in __p }`) and absent path (`{ None }`) agree because both
are checked against a pinned `__R`, and a bare payload auto-wraps into it.

**Value reads consult the copy policy** (design 131's table), because a value
read is where a place stops being storage: reading `let s = v[i]` out of an
ImplicitCopy element retains, and out of an ExplicitCopy/NoCopy element it is
the same clean error the rest of the language gives, naming the same ways out.

**The window's FLAVOR is decided here, per use site** (design 141 decision 3,
settled as DF-146b): a chain that only reads opens a shared window, a chain that
writes -- or hands the place over as `&var` -- opens an exclusive one, and both
come out of ONE `&self` declaration. The flavor rides on `place_window_exclusive`,
which the checker reads to demand a `var` root and to join the access set as a
mutable path; codegen gets the other half from `self_by_pointer`, which passes a
borrows accessor's receiver as storage rather than a copy. So `borrows` changes
what `&self` means -- the one place in Saw where that spelling is not
shared-only -- and everything else in the accessor's body stays ordinary `&self`
code.
"""

from ast_nodes import (
    Argument, ArrayIndex, ASTNode, AssignStatement, Block, BoolLiteral,
    BreakStatement, BindingPattern, ClosureExpr, ClosureParam,
    CompoundAssignStatement, ContinueStatement, ErasedErrWrap, Expression,
    ExpressionStatement, ForceUnwrap, ForLoop, FunctionCall, GuardLetStatement,
    Identifier, IfExpr, IfLetExpr, LetStatement, MatchArm, MatchExpr,
    MemberAccess, MethodCall, MoveExpr, NoneLiteral, OptionalChainAssign,
    OptionalEvalExpr, OptionalWrap, BindOptional,
    ReferenceExpr, ResultErrWrap, ResultOkWrap, ReturnStatement, SawType,
    SelfExpr, StringLiteral, TupleIndex, TypeKind, UnaryOp, structural_fields,
)
from errors import ErrorKind

WINDOW_LOCAL = "__p"


def is_place(node) -> bool:
    """Did the checker resolve this node to a `borrows` accessor?"""
    return getattr(node, 'place_struct', None) is not None and not getattr(
        node, 'place_lowered', False)


def transform_place_uses(programs, namespace, reporter) -> bool:
    """Lower every place use in `programs`. Returns True if any was."""
    tx = _PlaceUses(namespace, reporter)
    for program in programs:
        tx.run(program)
    if tx.changed:
        for program in programs:
            uncheck(program)
    return tx.changed


# =============================================================================
# Undoing the first check (design 146)
#
# Lowering a place use means the front half runs TWICE over one AST: the
# transform needs the checker's types to synthesize a window call, and the
# window call then needs checking. The second pass must see the program the
# AUTHOR wrote, not the one the first pass left behind — the checker rewrites
# as it goes, and its rewrites are not idempotent.
#
# Two kinds have to be undone. `OptionalWrap` is a node the checker INSERTS
# around a bare `T` bound to a `T?`; a second pass sees an already-optional
# initializer and judges it by different rules (`let y: OptInt = 100` stopped
# compiling, because `Int` flows into the distinct alias and `Int?` does not).
# And `resolved_type` is a per-pass conclusion: the first pass may stamp one
# under a monomorphization the second pass is not inside, which is how a
# generic body's `let result = body(n)` came back as the design-132 "binds
# nothing" error at an instantiation where `R` was Void.
#
# Everything the LOWERING itself stamped is left alone — those nodes are the
# transform's output, not the checker's leftovers.
# =============================================================================


def uncheck(node) -> None:
    """Strip the first check's own rewrites from `node`, in place."""
    if node is None or isinstance(node, SawType):
        return
    if isinstance(node, Block):
        node.statements = [_unchecked(s) for s in node.statements]
        node.final_expr = _unchecked(node.final_expr)
        return
    if not isinstance(node, (ASTNode, Argument, MatchArm)):
        return
    if isinstance(node, Expression) and not getattr(node, 'place_lowered', False):
        node.resolved_type = None
    for f in structural_fields(node):
        value = getattr(node, f.name, None)
        if isinstance(value, list):
            for i, item in enumerate(value):
                if _is_expr(item):
                    value[i] = _unchecked(item)
                else:
                    uncheck(item)
        elif _is_expr(value):
            setattr(node, f.name, _unchecked(value))
        else:
            uncheck(value)


def _unchecked(node):
    """`uncheck`, plus the unwrapping only an expression slot can do."""
    while (isinstance(node, _CHECKER_WRAPS)
           and not getattr(node, 'place_lowered', False)):
        node = node.value
    uncheck(node)
    return node


# The nodes the checker INSERTS around a value to fit it into its home: the
# `T -> T?` wrap and the three `Result` wraps (plain Ok/Err and the erasing
# Err). Every one is synthesized — no source spells them — so removing them
# restores exactly what the author wrote, and the next pass re-derives them.
_CHECKER_WRAPS = (OptionalWrap, ResultOkWrap, ResultErrWrap, ErasedErrWrap)


class _PlaceUses:
    def __init__(self, namespace, reporter):
        self.ns = namespace
        self.reporter = reporter
        self.changed = False
        self._counter = 0
        self._file = ""
        self._bounds = {}

    # -- traversal ---------------------------------------------------------

    def run(self, program) -> None:
        for func in getattr(program, 'functions', []) or []:
            self._decl(func)
        for ext in getattr(program, 'extensions', []) or []:
            for method in getattr(ext, 'methods', []) or []:
                self._decl(method, ext)
        for decl in getattr(program, 'module_decls', []) or []:
            body = getattr(decl, 'body', None)
            if body is not None:
                self.run(body)

    def _decl(self, decl, ext=None) -> None:
        body = getattr(decl, 'body', None)
        if body is None:
            return
        # A `borrows` body's own `lend` was already rewritten into
        # `__window(&var X)` by the declaration lowering; its place USES (an
        # accessor implemented over another accessor) are ordinary uses.
        self._file = getattr(decl, 'source_file', None) or ""
        self._bounds = self._collect_bounds(decl, ext)
        self._block(body)

    def _collect_bounds(self, decl, ext):
        """`{type parameter -> its declared trait bounds}` in scope for `decl`.

        A method's own parameters and its extension's are both in scope, and the
        method's win on a name collision — the same nesting the checker uses.
        This is what answers "does a bound prove this read may copy" without
        waiting for the instantiation (design 146, DF-146e rule 1).
        """
        bounds = {}
        for owner in (ext, decl):
            for tp in (getattr(owner, 'type_params', None) or []):
                bounds[tp.name] = set(getattr(tp, 'bounds', None) or [])
        return bounds

    def _block(self, block) -> None:
        block.statements = [self._stmt(s) for s in block.statements]
        if block.final_expr is not None:
            block.final_expr = self._value(block.final_expr)

    # -- statements --------------------------------------------------------

    def _stmt(self, stmt):
        if isinstance(stmt, ExpressionStatement) and isinstance(
                stmt.expression, OptionalChainAssign):
            lowered = self._chain_assign_window(stmt.expression, want='void')
            if lowered is not None:
                return ExpressionStatement(expression=lowered,
                                           line=stmt.line, column=stmt.column)
        if isinstance(stmt, (AssignStatement, CompoundAssignStatement)):
            return self._assignment(stmt)
        if isinstance(stmt, LetStatement):
            stmt.value = self._value(stmt.value)
            return stmt
        if isinstance(stmt, ReturnStatement):
            stmt.value = self._value(stmt.value)
            return stmt
        if isinstance(stmt, GuardLetStatement):
            presence = self._presence_condition(stmt.name, stmt.pattern,
                                                stmt.optional_expr)
            if presence is not None:
                # `guard let _ = p else { … }` asks only whether the place is
                # there, so it becomes the plain conditional it always meant.
                self._block(stmt.else_branch)
                return ExpressionStatement(
                    expression=IfExpr(
                        condition=UnaryOp(op="not", operand=presence,
                                          line=stmt.line, column=stmt.column),
                        then_branch=stmt.else_branch, else_branch=None,
                        line=stmt.line, column=stmt.column),
                    line=stmt.line, column=stmt.column)
            stmt.optional_expr = self._value(stmt.optional_expr)
            self._block(stmt.else_branch)
            return stmt
        if isinstance(stmt, ForLoop):
            stmt.iterable = self._value(stmt.iterable)
            self._block(stmt.body)
            return stmt
        if isinstance(stmt, ExpressionStatement):
            stmt.expression = self._value(stmt.expression)
            return stmt
        # A bare control-flow statement (an `if`/`while`/`match` written in
        # statement position parses as itself, not wrapped).
        return self._value(stmt)

    def _assignment(self, stmt):
        """`v[i] = x` / `v[i].n += 1`: the window is the whole statement.

        A write is the one shape whose extent is not an expression — there is no
        value to hand back, so `__R` is Void and the assignment itself becomes
        the window body.
        """
        stmt.value = self._value(stmt.value)
        place = self._chain_head(stmt.target)
        if place is None:
            self._recurse(stmt.target)
            return stmt
        name = self._fresh()
        stmt.target = self._replace_head(stmt.target, place, name)
        stmt = self._stmt(stmt)          # a nested place inside the same target
        body = Block(statements=[stmt], final_expr=None,
                     line=stmt.line, column=stmt.column)
        call = self._window_call(place, name, body,
                                 SawType(TypeKind.VOID),
                                 exclusive=True, absent='panic')
        return ExpressionStatement(expression=call, line=stmt.line,
                                   column=stmt.column)

    # -- expressions -------------------------------------------------------

    def _value(self, expr):
        """Lower every place use in `expr`, whose own result is a VALUE."""
        if expr is None:
            return None

        # A pattern that BINDS NOTHING never turns the place into a value
        # (DF-146f), so it is classified as a borrow before anything else.
        borrowed = self._borrow_read(expr)
        if borrowed is not None:
            return borrowed

        # A place handed over as a reference argument: the window spans the
        # whole call (design 141 — a Saw reference is call-scoped), and two of
        # them nest, which is what orders their epilogues LIFO.
        spanned = self._span_call(expr)
        if spanned is not None:
            return spanned

        place = self._chain_head(expr)
        if place is not None:
            return self._chain_window(expr, place)

        self._recurse(expr)
        return expr

    def _chain_window(self, expr, place):
        """`expr` is a postfix chain rooted at `place`."""
        result_type = getattr(expr, 'resolved_type', None)
        if result_type is None:
            # Not every checking path runs through the annotation chokepoint
            # (an `if let` subject is one), and a bare place read's result type
            # is exactly the place's own — optional when the lend is.
            result_type = self._place_read_type(expr, place)
        name = self._fresh()
        # Decide the FLAVOR first: `_replace_head` below rewrites the chain's
        # head into the window's parameter in place, and a rewritten chain no
        # longer reaches `place`, so a later reading of it would answer "shared"
        # for every use site. That is what let `let v` plus `v[0].bump()` open an
        # exclusive window with no error and join the access set as a shared
        # borrow.
        exclusive = self._chain_is_exclusive(expr, place)
        # `v.get(i)!` with NOTHING after it is a value read too — the `!` is how
        # the source promises the place is there, and what it hands back is the
        # element itself. A chain that continues PAST the `!` (`v.get(i)!.m()`)
        # is a borrow and stays one.
        unwrap_read = (isinstance(expr, ForceUnwrap) and expr.expr is place
                       and getattr(place, 'place_optional', False))
        if expr is place or unwrap_read:
            # The place stops being storage right here, so design 131's table
            # decides whether it may be read at all.
            if not self._value_read_ok(place):
                return expr
            body_expr = Identifier(name=name, line=place.line,
                                   column=place.column)
            # The read that turns the place back into a value. Codegen owes it
            # the container-slot duplication rule: the element stays in the
            # container, so an owning one must be retained here or the binding's
            # own drop releases storage the container still holds.
            body_expr.place_value_read = True
            if getattr(place, 'place_abstract_read', False):
                # Rule 2 (DF-146e): the tier is a property of the
                # INSTANTIATION, so the copy is emitted there — the same phase
                # that emits the drop. Deciding it here, on the written type,
                # is what left the two out of step.
                body_expr.place_abstract_read = True
            elem = getattr(place, 'place_elem_type', None)
            if (not unwrap_read and getattr(place, 'place_optional', False)
                    and elem is not None and elem.kind == TypeKind.OPTIONAL):
                # A conditional lend of an ALREADY-OPTIONAL element, e.g.
                # `Vector<String?>.get(i)`. The present path must yield
                # `Some(element)` — a real `U??` — but the auto-wrap will not
                # build one: flattening (design 111) exists precisely so a `U?`
                # never wraps into a `U??`. So say it outright; the absent path
                # is `None` at the same type and the two agree.
                body_expr = OptionalWrap(value=body_expr, target_type=result_type,
                                         line=place.line, column=place.column)
                body_expr.place_lowered = True
        else:
            body_expr = self._value(self._replace_head(expr, place, name))
        body = Block(statements=[], final_expr=body_expr,
                     line=expr.line, column=expr.column)
        return self._window_call(place, name, body, result_type,
                                 exclusive=exclusive,
                                 absent='none' if expr is place else 'panic')

    def _place_read_type(self, expr, place):
        """The type a bare read of this place yields."""
        elem = getattr(place, 'place_elem_type', None)
        if expr is not place:
            return elem      # the `!` already took the optional off
        return (SawType(TypeKind.OPTIONAL, inner_type=elem)
                if getattr(place, 'place_optional', False) else elem)

    # -- borrow-classified reads (DF-146f) ---------------------------------
    #
    # Design 131 made a payload read a PLACE and gave it the copy-tier table.
    # It classified every read the same way, so `if let _ = p` — a pattern that
    # binds nothing — was judged a VALUE read and a move-only place could not
    # even be asked whether it was there. Nothing is read: `_` takes no payload
    # out and a `case Empty` arm looks only at the discriminant. So a pattern
    # that binds nothing is a PRESENCE TEST, and a presence test is a BORROW —
    # legal for every tier, including a NoCopy element and an abstract
    # composite that demands a bound, because it emits no copy and no drop.
    #
    # Map's and Set's probe paths are exactly this shape (`_slot_state`,
    # `_key_eq`, `_key_at`), which is why the rule is written here in general
    # rather than special-cased in their files.

    def _borrow_read(self, expr):
        """`expr` re-lowered as a BORROW of its place, or None if it is not
        one of the binds-nothing shapes."""
        if isinstance(expr, IfLetExpr):
            presence = self._presence_condition(expr.name, expr.pattern,
                                                expr.optional_expr)
            if presence is None:
                return None
            self._block(expr.then_branch)
            if expr.else_branch is not None:
                self._block(expr.else_branch)
            return IfExpr(condition=presence, then_branch=expr.then_branch,
                          else_branch=expr.else_branch,
                          line=expr.line, column=expr.column)
        if isinstance(expr, MatchExpr):
            return self._borrow_match(expr)
        return None

    def _presence_condition(self, name, pattern, subject):
        """`if let _ = <place>` / `guard let _ = <place>` as a `Bool` question.

        The window's body is `true` and its absent path is `false`, so the place
        is never read out — and the then/else blocks stay exactly where the
        author wrote them, which a lowering that moved them INTO the window
        could not promise (a `return` inside one would return from the window).
        """
        if name != "_" or pattern is not None:
            return None
        if isinstance(subject, OptionalChainAssign):
            # `guard let _ = m[k]?.f = v` — the blessed way to consume a chain
            # assignment's `Void?` ("did it write"). The window's answer IS that
            # question, so it comes back as the Bool the caller is testing.
            return self._chain_assign_window(subject, want='bool')
        place = subject if is_place(subject) else None
        if place is None or not getattr(place, 'place_optional', False):
            return None
        body = Block(statements=[],
                     final_expr=BoolLiteral(value=True, line=place.line,
                                            column=place.column),
                     line=place.line, column=place.column)
        return self._window_call(place, self._fresh(), body,
                                 SawType(TypeKind.BOOL),
                                 exclusive=False, absent='false')

    def _borrow_match(self, expr):
        """`match <place> { … }`: the match moves INSIDE the window and reads
        the place where it sits.

        The discriminant is read through the borrow and an arm that binds binds
        THE PAYLOAD IN PLACE, so the copy-policy question is asked of that one
        binding rather than of the whole element — which is what lets a
        move-only element be matched at all, and what makes Map's and Set's
        probe paths cost nothing.

        Two shapes keep the ordinary value-read path. An arm body that leaves
        the enclosing function (`return`, `break`, `continue`) cannot move into
        a closure — it would leave the WINDOW instead. And an arm that MOVES
        one of its own bindings is destructuring the element rather than
        reading it, which a borrow cannot serve. Neither silently changes
        meaning: both keep the rules they had.
        """
        place = self._chain_head(expr.matched_expr)
        if place is None or expr.matched_expr is not place:
            return None
        if any(_escapes_control_flow(arm.body) or _arm_moves_binding(arm)
               for arm in expr.arms):
            return None
        result_type = getattr(expr, 'resolved_type', None)
        name = self._fresh()
        expr.matched_expr = Identifier(name=name, line=place.line,
                                       column=place.column)
        for arm in expr.arms:
            self._recurse(arm)
        body = Block(statements=[], final_expr=expr,
                     line=expr.line, column=expr.column)
        return self._window_call(place, name, body, result_type,
                                 exclusive=False, absent='panic')

    # -- chain assignment through a place head (DF-146o / DF-175d) ---------
    #
    # `m[k]?.field = v` composes two things that had never met: design 111's
    # chained assignment, which writes a payload field in place iff every hop is
    # non-None, and design 146's conditional lend, whose absent path opens no
    # window at all. They mean the same thing here — the head lends, an absent
    # head skips the write AND the RHS — so the composition is a window whose
    # BODY is the write:
    #
    #     m[k]?.field = v   =>   m.[](k, { __p0 in __p0.field = v }, { })
    #
    # The `?` is CONSUMED by the lowering, exactly as `!` is in `v.get(i)!.m()`:
    # it was the lend's own optionality, and inside the window the payload is
    # simply there. That is also why the head may not be read out as a value
    # first — the field write would land in the copy.
    #
    # The chain assignment types `Void?`, and Saw offers exactly two positions
    # for one: discard it in statement position, or consume "did it write" with
    # the `_`-blessed `if let`/`guard let`. Each gets the window result it
    # actually needs — Void for the first, Bool for the second — so no `Void?`
    # has to be synthesized at all.

    def _chain_assign_window(self, node, want):
        """`m[k]?.f = v` as a window call, or None if it is not that shape."""
        found = self._chain_assign_head(node)
        if found is None:
            return None
        place, bind = found
        name = self._fresh()
        node.value = self._value(node.value)
        target = self._replace_bind(node.target.expr, bind, name)
        write = AssignStatement(target=target, value=node.value,
                                line=node.line, column=node.column)
        # A nested place inside the rewritten target or the RHS.
        write = self._stmt(write)
        if want == 'bool':
            body = Block(statements=[write],
                         final_expr=BoolLiteral(value=True, line=node.line,
                                                column=node.column),
                         line=node.line, column=node.column)
            result_type = SawType(TypeKind.BOOL)
            absent = 'false'
        else:
            body = Block(statements=[write], final_expr=None,
                         line=node.line, column=node.column)
            result_type = SawType(TypeKind.VOID)
            absent = 'void'
        return self._window_call(place, name, body, result_type,
                                 exclusive=True, absent=absent)

    def _chain_assign_head(self, node):
        """`(place, bind_node)` when this chain assignment's ONLY optional hop is
        a conditional lend; None otherwise.

        v1 fence: a chain with a second `?` hop past the lend (`m[k]?.a?.b = v`)
        keeps design 111's existing behavior. The inner hop would need its own
        short-circuit inside the window, and the honest spelling for that today
        is to bind the lend first.
        """
        if not isinstance(node, OptionalChainAssign):
            return None
        target = node.target
        if not isinstance(target, OptionalEvalExpr):
            return None
        cur = target.expr
        if not isinstance(cur, MemberAccess):
            return None
        hops = 0
        while cur is not None:
            if isinstance(cur, MemberAccess):
                cur = cur.object
            elif isinstance(cur, BindOptional):
                hops += 1
                inner = cur.expr
                if is_place(inner) and getattr(inner, 'place_optional', False):
                    return (inner, cur) if hops == 1 else None
                cur = inner
            else:
                return None
        return None

    def _replace_bind(self, expr, bind, name):
        """`expr` with the `bind` hop swapped for the window's parameter."""
        if expr is bind:
            return Identifier(name=name, line=bind.line, column=bind.column)
        if isinstance(expr, MemberAccess):
            expr.object = self._replace_bind(expr.object, bind, name)
        return expr

    def _span_call(self, expr):
        """A call with `&place` / `&var place` arguments -> nested windows."""
        args = self._call_arguments(expr)
        if args is None:
            return None
        refs = [a for a in args
                if isinstance(a.value, ReferenceExpr)
                and self._chain_head(a.value.expr) is not None]
        if not refs:
            return None
        # Lower everything else in the call first, then wrap from the INSIDE
        # out so the leftmost argument's window is the outermost one.
        for a in args:
            if a not in refs:
                a.value = self._value(a.value)
        receiver = getattr(expr, 'object', None)
        if receiver is not None and not isinstance(expr, ArrayIndex):
            expr.object = self._value(receiver)

        result_type = getattr(expr, 'resolved_type', None)
        inner = expr
        for a in reversed(refs):
            ref = a.value
            place = self._chain_head(ref.expr)
            name = self._fresh()
            ref.expr = self._replace_head(ref.expr, place, name)
            body = Block(statements=[], final_expr=inner,
                         line=expr.line, column=expr.column)
            inner = self._window_call(place, name, body, result_type,
                                      exclusive=bool(ref.mutable),
                                      absent='panic')
        return inner

    # -- window synthesis --------------------------------------------------

    def _window_call(self, place, param_name, body, result_type, exclusive,
                     absent):
        """The accessor call that opens one window."""
        closure = ClosureExpr(
            parameters=[ClosureParam(name=param_name, line=place.line,
                                     column=place.column,
                                     place_shared_window=not exclusive)],
            body=body, line=place.line, column=place.column)
        args = [Argument(value=self._value(a)) for a in self._place_args(place)]
        args.append(Argument(value=closure))
        if getattr(place, 'place_optional', False):
            args.append(Argument(value=self._absent_closure(place, absent,
                                                            result_type)))
        result_type = (result_type if result_type is not None
                       else SawType(TypeKind.VOID))
        call = MethodCall(
            object=self._place_receiver(place),
            method_name=place.place_method,
            arguments=args,
            type_args=[result_type],
            line=place.line, column=place.column)
        call.place_lowered = True
        call.place_window_exclusive = exclusive
        call.resolved_type = result_type
        self.changed = True
        # The RECEIVER may itself be a place — `b[0][1]` is two windows, not
        # one. Wrapping this whole call in the outer window is what makes the
        # outer prologue run first and its epilogue run last (LIFO), because
        # that is simply what nesting means.
        outer = self._chain_head(call)
        if outer is not None:
            return self._chain_window(call, outer)
        return call

    def _absent_closure(self, place, kind, result_type):
        """The path where a conditional lend finds nothing to lend.

        No window opens and no epilogue runs — the caller decides what absence
        means. A value read of `T?` means `None`; a chain that reached THROUGH
        the place (`v.get(i)!.m()`, a write) has already promised the place is
        there, so absence is the force-unwrap's panic.
        """
        if kind == 'void':
            # A chain assignment discarded in statement position: absence means
            # the write simply did not happen, and there is no value to say so
            # with.
            return ClosureExpr(
                parameters=[], body=Block(statements=[], final_expr=None,
                                          line=place.line, column=place.column),
                line=place.line, column=place.column)
        if kind == 'none':
            body_expr = NoneLiteral(line=place.line, column=place.column)
        elif kind == 'false':
            # A presence test (DF-146f): absence IS the answer, not a failure.
            body_expr = BoolLiteral(value=False, line=place.line,
                                    column=place.column)
        else:
            body_expr = FunctionCall(
                name="panic",
                arguments=[Argument(value=StringLiteral(
                    value=(f"{place.place_struct}.{place.place_method}: "
                           f"no place to lend"),
                    line=place.line, column=place.column))],
                line=place.line, column=place.column)
        return ClosureExpr(
            parameters=[], body=Block(statements=[], final_expr=body_expr,
                                      line=place.line, column=place.column),
            line=place.line, column=place.column)

    def _place_receiver(self, place):
        return place.array_expr if isinstance(place, ArrayIndex) else place.object

    def _place_args(self, place):
        if isinstance(place, ArrayIndex):
            return [place.index]
        return [a.value for a in place.arguments]

    # -- policy ------------------------------------------------------------

    # The bounds that PROVE an abstract type may be duplicated. Each one gives
    # every satisfying type a copy the compiler can emit — bitwise for a trivial
    # one, a retain for ImplicitCopy, the type's own `copy()` for ExplicitCopy —
    # so the read is legal for EVERY instantiation and the emission can wait for
    # the instantiation to say which. Writing one of these is the author's
    # consent to duplication, which is what a concrete site spells `.copy()`.
    # An unbounded or `NoCopy`-bounded parameter proves nothing and is refused
    # in the generic body, before any instantiation exists (DF-123b: no
    # post-monomorphization errors).
    _COPY_PROVING_BOUNDS = frozenset({"Copy", "ImplicitCopy", "ExplicitCopy"})

    def _value_read_ok(self, place) -> bool:
        """design 131's table at the one point a place becomes a value."""
        elem = getattr(place, 'place_elem_type', None)
        tier = self.ns.copy_tier(elem) if elem is not None else 'free'
        if tier == 'abstract':
            return self._abstract_read_ok(place, elem)
        if tier in ('free', 'implicit'):
            return True
        rendered = f"{self._render(self._place_receiver(place))}"
        if isinstance(place, ArrayIndex):
            spelling = f"{rendered}[…]"
            borrow = f"`{spelling}.method()`"
        else:
            spelling = f"{rendered}.{place.place_method}(…)"
            borrow = (f"`{spelling}!.method()`"
                      if getattr(place, 'place_optional', False)
                      else f"`{spelling}.method()`")
        # Only name an escape hatch the receiver's type actually has. Vector
        # publishes both; a user type with a `[]` accessor may publish neither,
        # and pointing at a method that does not exist is worse than silence.
        outs = [f"{borrow} borrows through the window without taking the value "
                f"out"]
        if self.ns.lookup_method(place.place_struct, "with_ref") is not None:
            outs.append(f"`{rendered}.with_ref(…)` borrows it for a whole scope")
        if self.ns.lookup_method(place.place_struct, "swap_out") is not None:
            outs.append(f"`{rendered}.swap_out(…)` moves it out")
        hint = ", ".join(outs)
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`{spelling}` lends a place of type `{elem}`, which is "
            f"{'move-only' if tier == 'nocopy' else 'ExplicitCopy'} — reading "
            f"it out as a value would alias storage the container still owns",
            place.line, place.column or 1, hint, self._file)
        return False

    def _abstract_read_ok(self, place, elem) -> bool:
        """Rule 1 (DF-146e): a value read whose type mentions a type PARAMETER.

        `Slot<K>` has no tier of its own — its transfer class is whatever the
        instantiation's `K` turns out to be. Deciding that here, on the written
        type, is what broke: the structural join answered 'free' and emitted no
        copy, while the DROP was emitted per instantiation and was real, so
        every read over-released. The answer is not to guess but to ASK THE
        BOUNDS, in the generic body, once — legal for every instantiation or
        legal for none.
        """
        unproven = sorted(self._unproven_params(elem))
        if not unproven:
            place.place_abstract_read = True
            return True
        rendered = self._render(self._place_receiver(place))
        if isinstance(place, ArrayIndex):
            spelling = f"{rendered}[…]"
        else:
            spelling = f"{rendered}.{place.place_method}(…)"
        names = ", ".join(f"`{n}`" for n in unproven)
        one = unproven[0]
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`{spelling}` lends a place of type `{elem}`, whose copy policy "
            f"depends on the type parameter{'s' if len(unproven) > 1 else ''} "
            f"{names} — reading it out as a value would be a copy for some "
            f"instantiations and an alias for others",
            place.line, place.column or 1,
            f"bound the parameter so every instantiation can be copied "
            f"(`{one}: Copy`), or reach the place through a borrow — "
            f"`{spelling}.method()` reads it in place, and a pattern that binds "
            f"nothing (`case Empty`, `if let _ = …`) tests it without reading "
            f"it at all",
            self._file)
        return False

    def _unproven_params(self, saw_type, seen=None):
        """The type parameters in `saw_type` whose bounds do not prove a copy."""
        if saw_type is None:
            return set()
        if seen is None:
            seen = set()
        out = set()
        kind = saw_type.kind
        if kind == TypeKind.STRUCT and saw_type.struct_name is not None:
            name = saw_type.struct_name
            if self.ns.is_abstract_type_name(name):
                if not (self._bounds.get(name) or set()) & self._COPY_PROVING_BOUNDS:
                    out.add(name)
                return out
        for child in _type_children(saw_type):
            out |= self._unproven_params(child, seen)
        return out

    def _chain_is_exclusive(self, expr, place) -> bool:
        """Does this chain need an exclusive window? (Design 141 decision 3:
        the USE decides, never the declaration.)"""
        node = expr
        while node is not place:
            if isinstance(node, MethodCall):
                if getattr(node, 'place_window_exclusive', False):
                    # An already-lowered INNER window that writes. Windows nest
                    # (`b[0][1].count += 1` is two), and the write reaches the
                    # outer place's storage, so the outer window is exclusive
                    # too. Reading only `_method_mutates` here answered "shared"
                    # for every containing window: the outer borrow of `b` was
                    # joined as a shared one, and a `let` root would have taken
                    # the write. Harmless only because the window closure was
                    # `&var` regardless — which is the coupling DF-175b removed.
                    return True
                if self._method_mutates(node):
                    return True
                node = node.object
            elif isinstance(node, MemberAccess):
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

    def _method_mutates(self, call) -> bool:
        owner = _method_owner_name(getattr(call.object, 'resolved_type', None))
        if owner is None:
            return False
        info = self.ns.lookup_method(owner, call.method_name)
        return bool(info is not None and getattr(info, 'self_mutable', False))

    # -- chain plumbing ----------------------------------------------------

    def _chain_head(self, expr):
        """The place this postfix chain is rooted at, or None."""
        node = expr
        while node is not None:
            if is_place(node):
                return node
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
                return None
        return None

    def _replace_head(self, expr, place, name):
        """`expr` with `place` swapped for the window's parameter."""
        if expr is place:
            return Identifier(name=name, line=place.line, column=place.column)
        if (isinstance(expr, ForceUnwrap) and expr.expr is place
                and getattr(place, 'place_optional', False)):
            # `v.get(i)!.m()`: the `!` is how the source says "I promise the
            # place is there", and the window is where that promise is kept —
            # the present path opens it with the payload itself, the absent path
            # is the panic the `!` asked for. So the unwrap is CONSUMED here; the
            # window parameter is already `&var T`, and leaving the `!` on would
            # force-unwrap a non-optional.
            return Identifier(name=name, line=place.line, column=place.column)
        if isinstance(expr, MemberAccess):
            expr.object = self._replace_head(expr.object, place, name)
        elif isinstance(expr, MethodCall):
            expr.object = self._replace_head(expr.object, place, name)
        elif isinstance(expr, ArrayIndex):
            expr.array_expr = self._replace_head(expr.array_expr, place, name)
        elif isinstance(expr, TupleIndex):
            expr.tuple_expr = self._replace_head(expr.tuple_expr, place, name)
        elif isinstance(expr, ForceUnwrap):
            expr.expr = self._replace_head(expr.expr, place, name)
        return expr

    def _call_arguments(self, expr):
        if isinstance(expr, (FunctionCall, MethodCall)):
            return expr.arguments
        return None

    def _recurse(self, node) -> None:
        """Lower places in every structural child of a non-chain expression.

        Walks only the TREE — `ASTNode`s plus the two plain-dataclass carriers
        that hold expressions (`Argument`, `MatchArm`). A `SawType` is never
        entered: types reach back into namespace symbols, so following one walks
        out of the program and into the symbol graph.

        A list item may be a plain TUPLE rather than a node (DF-140g): two
        expression carriers pair their children with a name instead of holding
        them directly — `StructInit.field_inits` is `(field_name, value)` and
        `MapLiteral.entries` is `(key, value)`. A tuple is neither an
        `Expression` nor an `ASTNode`, so a walk that tests only those two steps
        straight over the expressions inside it, and a place in a struct-literal
        field or a map-literal entry reached codegen unlowered — an ICE
        ("Undefined method: `T.at`"), not a diagnostic.
        """
        if node is None or isinstance(node, SawType):
            return
        if isinstance(node, Block):
            self._block(node)
            return
        if not isinstance(node, (ASTNode, Argument, MatchArm)):
            return
        for f in structural_fields(node):
            value = getattr(node, f.name, None)
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if _is_expr(item):
                        value[i] = self._value(item)
                    elif isinstance(item, tuple):
                        value[i] = self._paired(item)
                    else:
                        self._recurse(item)
            elif _is_expr(value):
                setattr(node, f.name, self._value(value))
            else:
                self._recurse(value)

    def _paired(self, item: tuple) -> tuple:
        """Lower the expressions inside a `(name, expr)` / `(key, value)` pair.

        Rebuilt rather than mutated: a tuple is immutable, and the caller writes
        the replacement back into the list slot.
        """
        lowered = []
        for element in item:
            if _is_expr(element):
                lowered.append(self._value(element))
            else:
                # A name string, or a `SawType` — `_recurse` declines both.
                self._recurse(element)
                lowered.append(element)
        return tuple(lowered)

    # -- misc --------------------------------------------------------------

    def _fresh(self) -> str:
        name = f"{WINDOW_LOCAL}{self._counter}"
        self._counter += 1
        return name

    def _render(self, expr) -> str:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, SelfExpr):
            return "self"
        if isinstance(expr, MemberAccess):
            return f"{self._render(expr.object)}.{expr.member}"
        if isinstance(expr, MethodCall):
            return f"{self._render(expr.object)}.{expr.method_name}(…)"
        if isinstance(expr, ArrayIndex):
            return f"{self._render(expr.array_expr)}[…]"
        if isinstance(expr, ForceUnwrap):
            return f"{self._render(expr.expr)}!"
        return "<expr>"


def _is_expr(node) -> bool:
    return isinstance(node, Expression)


# Kinds whose methods are registered under their display name — the design-57
# extensible pseudo-structs. A `String` receiver is a STRUCT already.
_PRIMITIVE_METHOD_KINDS = frozenset({
    TypeKind.INT, TypeKind.UINT,
    TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
    TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
})


def _method_owner_name(saw_type):
    """The name a method on this type is registered under, or None.

    Enums carry method tables exactly as structs do (design 145), and the
    classifier below used to test `kind == STRUCT` — so a `&var self` method on
    an ENUM element answered "does not mutate" and its use site opened a SHARED
    window. The write still landed (the window is `&var` either way), which is
    why nothing caught it: `let frozen = build()` then `frozen[0].flip()`
    compiled and mutated an immutable root.
    """
    if saw_type is None:
        return None
    if saw_type.kind == TypeKind.STRUCT:
        return saw_type.struct_name
    if saw_type.kind == TypeKind.ENUM:
        return saw_type.enum_name
    if saw_type.kind in _PRIMITIVE_METHOD_KINDS:
        return str(saw_type)
    return None


def _arm_bindings(arm):
    """Every name this arm binds. A wildcard binds nothing from its position."""
    names = {b for b in (getattr(arm, 'bindings', None) or []) if b != "_"}
    _pattern_bindings(getattr(arm, 'pattern', None), names)
    return names


def _pattern_bindings(pattern, out) -> None:
    if pattern is None:
        return
    if isinstance(pattern, BindingPattern):
        if pattern.name != "_":
            out.add(pattern.name)
        return
    for attr in ('subpatterns', 'elements'):
        for sub in (getattr(pattern, attr, None) or []):
            _pattern_bindings(sub, out)


def _arm_moves_binding(arm) -> bool:
    """Does the arm `move` one of its own bindings out?

    That is destructuring, not reading: the payload leaves the element, which a
    window over storage the container still owns cannot serve.
    """
    names = _arm_bindings(arm)
    if not names:
        return False
    return _mentions_move(arm.body, names)


def _mentions_move(node, names) -> bool:
    if node is None or isinstance(node, SawType):
        return False
    if isinstance(node, MoveExpr) and getattr(node, 'variable', None) in names:
        return True
    if isinstance(node, Block):
        return (any(_mentions_move(s, names) for s in node.statements)
                or _mentions_move(node.final_expr, names))
    if not isinstance(node, (ASTNode, Argument, MatchArm)):
        return False
    for f in structural_fields(node):
        value = getattr(node, f.name, None)
        if isinstance(value, list):
            if any(_mentions_move(item, names) for item in value):
                return True
        elif _mentions_move(value, names):
            return True
    return False


def _escapes_control_flow(node) -> bool:
    """Does `node` contain a jump OUT of the expression it sits in?

    A window body is a closure, so a `return`/`break`/`continue` inside one
    would leave the WINDOW rather than the function that wrote it. Such a body
    stays on the ordinary path.
    """
    if node is None or isinstance(node, SawType):
        return False
    if isinstance(node, (ReturnStatement, BreakStatement, ContinueStatement,
                         GuardLetStatement)):
        return True
    if isinstance(node, Block):
        return (any(_escapes_control_flow(s) for s in node.statements)
                or _escapes_control_flow(node.final_expr))
    if isinstance(node, ClosureExpr):
        # A nested closure's own jumps belong to it, not to us.
        return False
    if not isinstance(node, (ASTNode, Argument, MatchArm)):
        return False
    for f in structural_fields(node):
        value = getattr(node, f.name, None)
        if isinstance(value, list):
            if any(_escapes_control_flow(item) for item in value):
                return True
        elif _escapes_control_flow(value):
            return True
    return False


def _type_children(saw_type):
    """Every type a `SawType` is built out of — arguments, payloads, elements.

    A type parameter can hide at any depth (`Vector<Slot<K>>`), and the search
    for one has no reason to know which shapes nest which.
    """
    for attr in ('inner_type', 'array_element_type', 'func_return_type'):
        child = getattr(saw_type, attr, None)
        if child is not None:
            yield child
    for attr in ('type_args', 'element_types', 'param_types'):
        for child in (getattr(saw_type, attr, None) or []):
            if child is not None:
                yield child

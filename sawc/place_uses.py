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
"""

from ast_nodes import (
    Argument, ArrayIndex, ASTNode, AssignStatement, Block, ClosureExpr,
    ClosureParam, CompoundAssignStatement, Expression, ExpressionStatement,
    ForceUnwrap, ForLoop, FunctionCall, GuardLetStatement, Identifier,
    LetStatement, MatchArm, MemberAccess, MethodCall, NoneLiteral,
    ReferenceExpr, ReturnStatement, SawType, StringLiteral, TupleIndex,
    TypeKind, structural_fields,
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
    return tx.changed


class _PlaceUses:
    def __init__(self, namespace, reporter):
        self.ns = namespace
        self.reporter = reporter
        self.changed = False
        self._counter = 0
        self._file = ""

    # -- traversal ---------------------------------------------------------

    def run(self, program) -> None:
        for func in getattr(program, 'functions', []) or []:
            self._decl(func)
        for ext in getattr(program, 'extensions', []) or []:
            for method in getattr(ext, 'methods', []) or []:
                self._decl(method)
        for decl in getattr(program, 'module_decls', []) or []:
            body = getattr(decl, 'body', None)
            if body is not None:
                self.run(body)

    def _decl(self, decl) -> None:
        body = getattr(decl, 'body', None)
        if body is None:
            return
        # A `borrows` body's own `lend` was already rewritten into
        # `__window(&var X)` by the declaration lowering; its place USES (an
        # accessor implemented over another accessor) are ordinary uses.
        self._file = getattr(decl, 'source_file', None) or ""
        self._block(body)

    def _block(self, block) -> None:
        block.statements = [self._stmt(s) for s in block.statements]
        if block.final_expr is not None:
            block.final_expr = self._value(block.final_expr)

    # -- statements --------------------------------------------------------

    def _stmt(self, stmt):
        if isinstance(stmt, (AssignStatement, CompoundAssignStatement)):
            return self._assignment(stmt)
        if isinstance(stmt, LetStatement):
            stmt.value = self._value(stmt.value)
            return stmt
        if isinstance(stmt, ReturnStatement):
            stmt.value = self._value(stmt.value)
            return stmt
        if isinstance(stmt, GuardLetStatement):
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
        if result_type is None and expr is place:
            # Not every checking path runs through the annotation chokepoint
            # (an `if let` subject is one), and a bare place read's result type
            # is exactly the place's own — optional when the lend is.
            elem = getattr(place, 'place_elem_type', None)
            result_type = (SawType(TypeKind.OPTIONAL, inner_type=elem)
                           if getattr(place, 'place_optional', False) else elem)
        name = self._fresh()
        if expr is place:
            # A bare value read: the place stops being storage right here, so
            # design 131's table decides whether it may be read at all.
            if not self._value_read_ok(place):
                return expr
            body_expr = Identifier(name=name, line=place.line,
                                   column=place.column)
        else:
            body_expr = self._value(self._replace_head(expr, place, name))
        body = Block(statements=[], final_expr=body_expr,
                     line=expr.line, column=expr.column)
        return self._window_call(place, name, body, result_type,
                                 exclusive=self._chain_is_exclusive(expr, place),
                                 absent='none' if expr is place else 'panic')

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

    def _exclusive_ok(self, place) -> bool:
        """Can this accessor lend an EXCLUSIVE window? (v1 fence.)

        Design 141 decision 3 wants one body to serve both flavors with the USE
        SITE picking. The compiler cannot honor that yet: a `&self` receiver is
        passed as a COPY, so `&var self.field` inside such a body writes to the
        copy — silently, today, for hand-written code too (DF-146b). Until that
        is settled, an exclusive window needs an accessor that took its receiver
        mutably, which is the honest half of the decision rather than a silent
        wrong answer.
        """
        info = self.ns.lookup_method(place.place_struct, place.place_method)
        if info is not None and getattr(info, 'self_mutable', False):
            return True
        spelling = (f"{self._render(self._place_receiver(place))}[…]"
                    if isinstance(place, ArrayIndex)
                    else f"{self._render(self._place_receiver(place))}"
                         f".{place.place_method}(…)")
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`{spelling}` opens an EXCLUSIVE window, but "
            f"`{place.place_struct}.{place.place_method}` takes `&self` — a "
            f"shared receiver cannot lend storage to write through",
            place.line, place.column or 1,
            f"declare the accessor `func {place.place_method}(&var self, …) "
            f"borrows -> T`; a `&self` accessor serves reads",
            self._file)
        return False

    def _conditional_ok(self, place) -> bool:
        """v1 fence: a conditional lend may be DECLARED but not yet USED.

        `borrows -> T?` needs the two window closures to agree on `__R`, and
        the absent one takes no parameters — which is the one shape whose
        result type does not survive to codegen (it arrives as Void and the
        `None` it returns has nothing to be a `None` OF). Rather than emit that
        as an internal error at the user, say so here. DF-146c.
        """
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`{place.place_struct}.{place.place_method}` lends CONDITIONALLY "
            f"(`borrows -> T?`), and calling a conditional lend is not "
            f"implemented yet — only unconditional `borrows -> T` accessors "
            f"can be used so far",
            place.line, place.column or 1,
            "declare the accessor `borrows -> T` and bounds-check in its "
            "prologue (panicking out of range), or reach the element with "
            "`with_ref`/`with_var_ref` until this lands",
            self._file)
        return False

    def _window_call(self, place, param_name, body, result_type, exclusive,
                     absent):
        """The accessor call that opens one window."""
        if exclusive and not self._exclusive_ok(place):
            exclusive = False
        if getattr(place, 'place_optional', False) and not self._conditional_ok(
                place):
            return place
        closure = ClosureExpr(
            parameters=[ClosureParam(name=param_name, line=place.line,
                                     column=place.column)],
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
        if kind == 'none':
            body_expr = NoneLiteral(line=place.line, column=place.column)
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

    def _value_read_ok(self, place) -> bool:
        """design 131's table at the one point a place becomes a value."""
        elem = getattr(place, 'place_elem_type', None)
        tier = self.ns.copy_tier(elem) if elem is not None else 'free'
        if tier in ('free', 'implicit'):
            return True
        rendered = f"{self._render(self._place_receiver(place))}"
        if isinstance(place, ArrayIndex):
            spelling = f"{rendered}[…]"
            hint = (f"`{rendered}.with_ref(…)` borrows it in place, "
                    f"`{rendered}.swap_out(…)` moves it out")
        else:
            spelling = f"{rendered}.{place.place_method}(…)"
            hint = (f"reach it in place — `{spelling}!.method()` borrows "
                    f"through the window without taking the value out")
        self.reporter.error(
            ErrorKind.TYPE_MISMATCH,
            f"`{spelling}` lends a place of type `{elem}`, which is "
            f"{'move-only' if tier == 'nocopy' else 'ExplicitCopy'} — reading "
            f"it out as a value would alias storage the container still owns",
            place.line, place.column or 1, hint, self._file)
        return False

    def _chain_is_exclusive(self, expr, place) -> bool:
        """Does this chain need an exclusive window? (Design 141 decision 3:
        the USE decides, never the declaration.)"""
        node = expr
        while node is not place:
            if isinstance(node, MethodCall):
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
        recv_t = getattr(call.object, 'resolved_type', None)
        if recv_t is None or recv_t.kind != TypeKind.STRUCT:
            return False
        info = self.ns.lookup_method(recv_t.struct_name, call.method_name)
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
                    else:
                        self._recurse(item)
            elif _is_expr(value):
                setattr(node, f.name, self._value(value))
            else:
                self._recurse(value)

    # -- misc --------------------------------------------------------------

    def _fresh(self) -> str:
        name = f"{WINDOW_LOCAL}{self._counter}"
        self._counter += 1
        return name

    def _render(self, expr) -> str:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccess):
            return f"{self._render(expr.object)}.{expr.member}"
        return "<expr>"


def _is_expr(node) -> bool:
    return isinstance(node, Expression)

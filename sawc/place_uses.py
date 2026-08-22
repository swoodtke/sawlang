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
Copy element retains, and out of an ExplicitCopy/NoCopy element it is
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

**And the flavor may pick the METHOD** (design 179). An accessor whose body
named `#lend_var` was emitted as two specializations by the declaration
lowering, so an exclusive use site is retargeted at the `&var self` twin here
and a shared one keeps the authored `&self` accessor. That works precisely
because this pass sits BETWEEN two full type checks: the retarget is written
after the first, and the second checks it as an ordinary call -- an immutable
root reaching the twin gets the plain "cannot open an exclusive place window on
immutable variable" diagnostic, with no new error text to author.
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
    SelfExpr, StringInterpolation, StringLiteral, TupleIndex, TypeKind, UnaryOp,
    structural_fields,
)
from ast_walk import child_nodes, map_nodes
from errors import ErrorKind
from place_transform import var_twin_name

WINDOW_LOCAL = "__p"

# "Inside the receiver, at a type this walk cannot name" — an enum payload,
# whose case decides its type but not where it lives. Storage, so the rule
# fires; opaque, so no further hop is taken through it.
_INLINE_OPAQUE = object()


def is_place(node) -> bool:
    """Did the checker resolve this node to a `borrows` accessor?"""
    return getattr(node, 'place_struct', None) is not None and not getattr(
        node, 'place_lowered', False)


def transform_place_uses(programs, namespace, reporter, uncheck_after=True) -> bool:
    """Lower every place use in `programs`. Returns True if any was.

    `uncheck_after` is False for the POST-TRANSFORM run (design 218 stage 1),
    where the only new place uses are the `Slot.value()` lends the coroutine
    transform just emitted. `uncheck` exists to restore what the AUTHOR wrote
    so the next check re-derives its own rewrites — and the transformed AST has
    no author. Its `self.__result = <Int>` store in a `-> Result<Int, E>` frame
    is wrapped `Ok` by the check that just ran, and stripping that wrap hands
    the next check a store it refuses outright ("cannot assign `Int` to field
    of type `Result<Int, IoError>?`"). The lowering's own output is stamped
    `place_lowered`, so leaving the tree checked costs nothing: a second
    lowering pass over it finds no place left to lower.
    """
    tx = _PlaceUses(namespace, reporter)
    for program in programs:
        tx.run(program)
    if tx.changed and uncheck_after:
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
    """Strip the first check's own rewrites from `node`, in place.

    One walk (`ast_walk.map_nodes`, design 193 unit 3), where this used to
    hand-roll its own recursion and stop at TUPLES — so a struct literal's
    `field_inits` kept both the checker's `resolved_type` stamps and its
    inserted wraps through the second check.
    """
    map_nodes(node, _uncheck_node)


def _uncheck_node(node):
    """The per-node rule: peel the checker's inserted wraps, then drop the
    per-pass `resolved_type`. Nodes the LOWERING stamped (`place_lowered`) are
    its own output, not the checker's leftovers, and are left alone."""
    while (isinstance(node, _CHECKER_WRAPS)
           and not getattr(node, 'place_lowered', False)
           and node.value is not None):
        node = node.value
    if isinstance(node, Expression) and not getattr(node, 'place_lowered', False):
        node.resolved_type = None
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
        # design 200: the receiver's type while lowering a PLAIN `&self` method
        # body, else None. Set per declaration by `_decl`.
        self._shared_self_type = None
        self._reported_windows = set()
        self._inline_cache = {}

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
        self._shared_self_type = self._plain_shared_receiver(decl, ext)
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

        # RENDERING a place keeps nothing either (DF-218i), so it is the second
        # borrow-classified shape.
        rendered = self._render_window(expr)
        if rendered is not None:
            return rendered

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
            body_expr = self._value(
                self._replace_head(expr, place, name,
                                   getattr(place, 'place_elem_type', None)))
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
        if place is None:
            return None
        if not getattr(place, 'place_optional', False):
            return self._presence_desugar(place)
        body = Block(statements=[],
                     final_expr=BoolLiteral(value=True, line=place.line,
                                            column=place.column),
                     line=place.line, column=place.column)
        return self._window_call(place, self._fresh(), body,
                                 SawType(TypeKind.BOOL),
                                 exclusive=False, absent='false')

    def _presence_desugar(self, place):
        """`if let _ = <unconditional lend of an optional-TYPED place>`.

        DF-218a. `Slot<T?>.value()` is `borrows -> T` at `T = Res?`: the lend is
        UNCONDITIONAL, so the place is there by construction and the optional
        the use site sees is the ELEMENT, not the lend's presence. The window
        above answers the lend's own question and has nothing to say about this
        one, so the read fell through to the value path and a move-only payload
        could not be presence-tested at all.

        The fix is design 218's ELABORATION PRINCIPLE rather than a fourth
        classification arm: rewrite to `<place>.is_some()`, which is core a
        programmer could have written, and let the ordinary chain machinery
        lower it. That machinery already borrows a place to call a method on it
        — `s.value().method()` is the escape hatch `_value_read_ok`'s own hint
        names — so the presence test becomes a `&self` tag read inside a shared
        window, tier-independent because the tag is not the payload. The node
        carries the PLACE's span, so a diagnostic still anchors at what the
        author wrote.

        Scoped deliberately. A CONDITIONAL lend keeps the window above: there
        the `?` IS the window's presence rather than a value, so the desugared
        spelling is not expressible at all — lowering `v.get(i).is_some()` puts
        the call inside the window, where the binding is the lent ELEMENT
        (``type `Res` has no method `is_some` ``). A plain optional value keeps
        design 111's `_` rider, which already releases a `move` scrutinee's
        payload exactly once (DF-217l). Both were probed at every tier before
        this was scoped.
        """
        elem = getattr(place, 'place_elem_type', None)
        if elem is None or elem.kind != TypeKind.OPTIONAL:
            return None
        call = MethodCall(object=place, method_name="is_some", arguments=[],
                          line=place.line, column=place.column)
        call.resolved_type = SawType(TypeKind.BOOL)
        return self._chain_window(call, place)

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
        chain_op = getattr(node, 'op', None)
        if chain_op is not None:
            # `m[k]?.f += v` (design 227 unit 4): the window's body is the
            # compound write, exactly as it is the plain one.
            write = CompoundAssignStatement(target=target, op=chain_op,
                                            value=node.value,
                                            line=node.line, column=node.column)
        else:
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

    # -- rendering operands (DF-218i) --------------------------------------
    #
    # Rendering a value hands it to `format(&self, into:)` and keeps nothing —
    # the same borrow `v[0].method()` already gets. The place system judged it a
    # VALUE READ instead, because a bare place read looks the same wherever it
    # sits, so `print("{v[0]}")` and `print(v[0])` on a move-only element were
    # ``lends a place of type `Res`, which is move-only`` while the two controls
    # beside them (a field read out of the place, a `&self` call on it) compiled.
    #
    # So a rendering operand joins the presence test as a borrow-classified
    # shape: the window's extent is the smallest RENDERING expression around it,
    # and inside that window the operand is the window's own binding — a `&T`,
    # which every rendering position already accepts.

    def _rendering_slots(self, expr):
        """Every RENDERING OPERAND of `expr`, as `(read, write)` pairs.

        THE description of what a rendering position is, and the only one — a
        second list written for a second caller is how a position goes missing.
        Its three entry points are the three places a value is rendered:

          * `StringInterpolation.expressions` — `"{x}"`, anywhere one is
            written (design 56).
          * a single-argument `print(x)` of a `Printable` (design 132 unit D).
          * the FORMAT ARGUMENTS of `print`/`panic`/`assert` — everything past
            the literal format string, and past `assert`'s condition ahead of
            it (design 137).

        A `FormatPlaceholder` sitting in the first list is not an operand and
        needs no filtering here: it roots no chain, so the caller's own
        place test declines it.
        """
        if isinstance(expr, StringInterpolation):
            parts = expr.expressions
            return [(lambda i=i: parts[i],
                     lambda v, i=i: parts.__setitem__(i, v))
                    for i in range(len(parts))]
        if not isinstance(expr, FunctionCall):
            return []
        args = expr.arguments
        if expr.name == "print":
            first = 0 if len(args) == 1 else 1
        elif expr.name == "panic":
            first = 1
        elif expr.name == "assert":
            first = 2
        else:
            return []
        return [(lambda a=a: a.value,
                 lambda v, a=a: setattr(a, 'value', v))
                for a in args[first:]]

    def _render_window(self, expr):
        """`expr` re-lowered with its rendering operands BORROWED, or None when
        no operand of it is a place the value-read table would refuse.

        Scoped to the refused reads on purpose. Where the tier permits the read,
        the ordinary chain window already lowers each operand on its own, and
        making a rendering position wrap its whole expression instead would pull
        every SIBLING operand inside the window with it — which is a capture,
        and for a sibling naming the window's own root a new refusal (DF-248a).
        A borrow is the better lowering of the two and this is where it is worth
        the wrap: it is the difference between compiling and not.
        """
        slots = self._rendering_slots(expr)
        if not slots:
            return None
        targets = []
        for read, write in slots:
            operand = read()
            place = self._chain_head(operand)
            if place is None:
                continue
            optional = bool(getattr(place, 'place_optional', False))
            # The two shapes that turn the place back into a value AT the
            # operand. A chain that continues past it (`"{v[0].n}"`) is already
            # a borrow, and a bare CONDITIONAL lend renders a `T?` rather than
            # the element, so neither is this rule's business.
            bare = (operand is place and not optional)
            unwrapped = (isinstance(operand, ForceUnwrap)
                         and operand.expr is place and optional)
            if not (bare or unwrapped):
                continue
            if not self._value_read_would_refuse(place):
                continue
            targets.append((write, place))
        if not targets:
            return None
        names = []
        for write, place in targets:
            name = self._fresh()
            names.append(name)
            write(self._window_head(name, place,
                                    getattr(place, 'place_elem_type', None)))
        # Everything else in the rendering expression — the other operands, an
        # `assert` condition — is lowered where it stands, now that the operands
        # this pass owns have been swapped out from under it.
        self._recurse(expr)
        result_type = getattr(expr, 'resolved_type', None)
        inner = expr
        for (write, place), name in reversed(list(zip(targets, names))):
            body = Block(statements=[], final_expr=inner,
                         line=expr.line, column=expr.column)
            inner = self._window_call(place, name, body, result_type,
                                      exclusive=False, absent='panic')
        return inner

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
        """The accessor call that opens one window.

        THE ONE CHOKEPOINT every window goes through, which is why design 200's
        receiver-copy check sits here rather than at each shape. Entry points:
        `_assignment` (a write), `_chain_window` (a read or a chain, and the
        nesting wrap this method makes of its own result), `_span_call` (a
        `&`/`&var` argument), `_chain_assign_window` (`m[k]?.f = v`),
        `_presence_condition` (`if let _ = …`) and `_borrow_match`.
        """
        if exclusive:
            self._reject_shared_self_window_write(place)
        closure = ClosureExpr(
            parameters=[ClosureParam(name=param_name, line=place.line,
                                     column=place.column,
                                     place_shared_window=not exclusive)],
            body=body, line=place.line, column=place.column)
        # DF-169h: the body is code the AUTHOR wrote in the enclosing scope, so
        # it captures by BORROW. The receiver's own root is the exception — see
        # `ClosureExpr.is_place_window`.
        closure.is_place_window = True
        closure.place_window_root = self._access_root(
            self._place_receiver(place))
        args = [Argument(value=self._value(a)) for a in self._place_args(place)]
        args.append(Argument(value=closure))
        if getattr(place, 'place_optional', False):
            args.append(Argument(value=self._absent_closure(place, absent,
                                                            result_type)))
        result_type = (result_type if result_type is not None
                       else SawType(TypeKind.VOID))
        call = MethodCall(
            object=self._place_receiver(place),
            method_name=self._flavored_method(place, exclusive),
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

    def _flavored_method(self, place, exclusive: bool) -> str:
        """The accessor this use site calls — the retarget of design 179.

        An accessor whose body named `#lend_var` was emitted as TWO methods by
        the declaration lowering: the authored `&self` one, folded shared, and a
        `&var self` twin under a reserved name, folded exclusive. This pass is
        the only thing that knows which flavor a use site opens, so it is the
        one that picks, and it picks by NAME — which is why the mangler, the
        docs and the diagnostics all keep working on the authored name.

        An accessor that never named the constant has no twin and is reached
        exactly as before, whichever flavor the use site opens.
        """
        method = place.place_method
        if not exclusive:
            return method
        twin = var_twin_name(method)
        if self.ns.lookup_method(place.place_struct, twin) is None:
            return method
        return twin

    def _place_receiver(self, place):
        return place.array_expr if isinstance(place, ArrayIndex) else place.object

    def _place_args(self, place):
        if isinstance(place, ArrayIndex):
            return [place.index]
        return [a.value for a in place.arguments]

    # -- policy ------------------------------------------------------------

    # The bounds that PROVE an abstract type may be duplicated SILENTLY — which
    # is what a place value read is. Each gives every satisfying type a copy the
    # compiler emits with nothing written at the read (bitwise for a trivial
    # instantiation, a retain for a refcounted one), so the read is legal for
    # EVERY instantiation and the emission can wait for the instantiation to say
    # which. An unbounded or `NoCopy`-bounded parameter proves nothing and is
    # refused in the generic body, before any instantiation exists (DF-123b: no
    # post-monomorphization errors).
    #
    # `ExplicitCopy` is NOT one of them (design 219, judgment site 2 — design 146
    # yields). It proves only that a copy EXISTS, not that one may happen
    # unwritten: admitting it here made `let e = v[i]` in a generic body lower to
    # the ceremony tier's silent duplicate, which is the same admission S1 row 9d
    # miscompiled at the bound. Container copyability at ceremony-tier elements
    # is expressed where it belongs — as the CONTAINER'S own conformance, whose
    # body spells `buf[i].copy()`.
    _COPY_PROVING_BOUNDS = frozenset({"Copy"})

    def _value_read_would_refuse(self, place) -> bool:
        """Would design 131's table refuse a value read of this place?

        `_value_read_ok`'s question without its diagnostic, for the classifiers
        that have to decide BEFORE the read is reached — a rendering operand is
        judged where the rendering sits, not where the place does, and asking
        the reporting form there would emit an error about a read that then
        never happens.
        """
        elem = getattr(place, 'place_elem_type', None)
        tier = self.ns.copy_tier(elem) if elem is not None else 'free'
        if tier == 'abstract':
            return bool(self._unproven_params(elem))
        return self.ns.read_policy(elem) not in ('trivial', 'retain')

    def _value_read_ok(self, place) -> bool:
        """design 131's table at the one point a place becomes a value.

        Asks `copy_tier` — the same oracle `Namespace.read_policy` derives the
        payload-read and match-consume answers from (design 193 unit 1) — and
        not the derived policy, because 'abstract' is answered HERE from the
        type parameter's bounds rather than by falling back to a bitwise read.
        """
        elem = getattr(place, 'place_elem_type', None)
        tier = self.ns.copy_tier(elem) if elem is not None else 'free'
        if tier == 'abstract':
            return self._abstract_read_ok(place, elem)
        if self.ns.read_policy(elem) in ('trivial', 'retain'):
            return True
        rendered = f"{self._render(self._place_receiver(place))}"
        spelling = self._place_spelling(place)
        borrow = (f"`{spelling}!.method()`"
                  if getattr(place, 'place_optional', False)
                  and not isinstance(place, ArrayIndex)
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
        spelling = self._place_spelling(place)
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

    # -- the receiver-copy write (design 200, DF-176c) ---------------------
    #
    # A plain `&self` receiver arrives BY VALUE. Design 176 refuses the three
    # spellings that write into such a copy — a direct field write, a `&var
    # self.field` projection, a `&var self` method call on `self` or on a field
    # of it — and this is the fourth: an EXCLUSIVE place window opened on
    # storage inside the receiver. `self.grid[0] += 100` opened its window on
    # the copy's `grid` and threw the write away when the method returned.
    #
    # The rule is judged HERE and not by `_reject_var_self_call_on_shared_self`
    # deliberately. The window call is synthesized: this pass picks the accessor
    # and its flavor, so the method rule would name a method the source never
    # wrote, and would refuse `lend self.inner[i]` — design 175's legitimate
    # forwarding, which is sound precisely because a borrows body's receiver
    # travels by pointer.
    #
    # Three things narrow it, and each is a row of design 200's conformance
    # family:
    #
    # - EXCLUSIVE windows only (M35's second half). A shared window lends the
    #   element read-only, so a read off a `&self` copy is honest.
    # - PLAIN method bodies only (M33, M34). Inside a `borrows` body the
    #   receiver travels by pointer, so the same write LANDS — the ratified half
    #   of DF-176c, with `#lend_var` there to keep it out of the shared
    #   specialization.
    # - INLINE storage only (M32). Where the accessor lends out of heap the
    #   receiver merely points at, the copy SHARES that storage and the write
    #   reaches the caller — the same carve-out design 176 draws for
    #   `self.rows[0].push(9)`.

    def _reject_shared_self_window_write(self, place) -> None:
        """An exclusive window on receiver-inline storage, in a `&self` body."""
        if self._shared_self_type is None:
            return
        if id(place) in self._reported_windows:
            return
        if self._self_inline_type(place) is None:
            return
        spelling = self._place_spelling(place)
        self.reporter.error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot write through a place window on storage reached through a "
            f"`&self` receiver: `self` is borrowed SHARED here, so "
            f"`{spelling}` opens its window on the callee's copy and the write "
            f"is discarded when the method returns",
            place.line, place.column or 1,
            "declare the method `&var self` to mutate through the receiver, or "
            "`borrows -> T` to lend the place and let each use site choose the "
            "window's flavor",
            self._file)
        # Windows NEST, and a nested write makes every containing window
        # exclusive too — so the enclosing ones would each report the same write
        # one hop out. One diagnostic per write: mark the chain this place hangs
        # off as spoken for.
        node = self._place_receiver(place)
        while node is not None:
            self._reported_windows.add(id(node))
            node = self._chain_down(node)

    def _plain_shared_receiver(self, decl, ext):
        """The receiver type of a PLAIN `&self` method — the one body shape
        where a window write reaches a copy — or None for anything else.

        `&var self` and a `borrows` body (the `#lend_var` twin included, which
        carries `self_mutable`) both borrow the receiver in a way that makes the
        write land, so neither is this rule's business.
        """
        if ext is None or decl is None:
            return None
        if getattr(decl, 'is_static', False) or getattr(decl, 'is_init', False):
            return None
        if getattr(decl, 'self_mutable', False) or getattr(
                decl, 'is_borrows', False):
            return None
        if not getattr(decl, 'self_is_reference', False):
            return None
        name = getattr(ext, 'struct_name', None)
        if name is None:
            return None
        args = list(getattr(ext, 'type_args', None) or [])
        if not args:
            # A generic extension: the parameters stand for themselves, so field
            # types keep the form the author wrote and the walk below reads them
            # exactly as it reads a concrete one. An `[T; N]` element is inline
            # whatever `T` is.
            args = [SawType(TypeKind.TYPE_PARAM, type_param_name=tp.name)
                    for tp in (getattr(ext, 'type_params', None) or [])]
        if self.ns.lookup_struct(name) is not None:
            return SawType(TypeKind.STRUCT, struct_name=name, type_args=args)
        if self.ns.lookup_enum(name) is not None:
            # An enum receiver has no fields, but it has a PAYLOAD — and an
            # accessor that lends one (`case Filled(r) -> lend r`) lends storage
            # inside the enum's own bytes exactly as a field would.
            return SawType(TypeKind.ENUM, enum_name=name, type_args=args)
        return None

    def _self_inline_type(self, expr):
        """The type of the storage `expr` names when it lives INSIDE the `&self`
        receiver's own value; None when it does not.

        The design-176 walk (`_self_storage_type`), reaching one hop it could
        not: a PLACE. An accessor continues the walk exactly when it lends
        receiver-inline storage itself, which is what makes the rule compose —
        `self.rows[0][0]` stops at the `Vector`, and a hand-written accessor
        over an `[T; N]` does not.
        """
        if expr is None:
            return None
        if isinstance(expr, SelfExpr):
            return self._shared_self_type
        if is_place(expr):
            receiver = self._self_inline_type(self._place_receiver(expr))
            if receiver is None or not self._lends_inline(
                    expr.place_struct, expr.place_method, receiver):
                return None
            return getattr(expr, 'place_elem_type', None) or _INLINE_OPAQUE
        if isinstance(expr, MemberAccess):
            return self._inline_hop(self._self_inline_type(expr.object),
                                    ('member', expr.member))
        if isinstance(expr, TupleIndex):
            return self._inline_hop(self._self_inline_type(expr.tuple_expr),
                                    ('tuple', expr.index))
        if isinstance(expr, ForceUnwrap):
            return self._inline_hop(self._self_inline_type(expr.expr),
                                    ('unwrap',))
        if isinstance(expr, ArrayIndex):
            return self._inline_hop(self._self_inline_type(expr.array_expr),
                                    ('index',))
        return None

    def _lends_inline(self, struct_name, method_name, receiver_type) -> bool:
        """Does this accessor lend storage inside its receiver's own bytes?

        `place_transform` recorded the SHAPE of each lending path; the types are
        this pass's to supply. One inline path is enough — a body that lends
        inline storage on any path can lose a write on that path.
        """
        if struct_name is None or method_name is None:
            return False
        key = (struct_name, method_name, str(receiver_type))
        cached = self._inline_cache.get(key)
        if cached is not None:
            return cached
        # A cycle can only arise through a type that reaches itself, which no
        # inline layout can; answering False breaks it without a special case.
        self._inline_cache[key] = False
        info = self.ns.lookup_method(struct_name, method_name)
        node = getattr(info, 'ast_node', None) if info is not None else None
        answer = False
        for path in (getattr(node, 'place_lend_paths', None) or ()):
            current = receiver_type
            for hop in path:
                current = self._inline_hop(current, hop)
                if current is None:
                    break
            else:
                answer = True
                break
        self._inline_cache[key] = answer
        return answer

    def _inline_hop(self, container, hop):
        """The type one hop yields, or None when the hop leaves the receiver's
        own storage — the type half of the shapes `place_transform` records."""
        if container is None or container is _INLINE_OPAQUE:
            return None
        container = self._resolve_alias(container)
        if container.kind == TypeKind.REFERENCE and container.inner_type:
            container = self._resolve_alias(container.inner_type)
        kind = hop[0]
        if kind == 'unwrap':
            return (container.inner_type
                    if container.kind == TypeKind.OPTIONAL else None)
        if kind == 'payload':
            # An enum's payload sits inside the enum's own bytes. Which case it
            # is decides its TYPE and not where it lives, so the walk stops here
            # rather than guessing one.
            return (_INLINE_OPAQUE
                    if container.kind == TypeKind.ENUM else None)
        if kind == 'tuple':
            if container.kind != TypeKind.TUPLE:
                return None
            elements = container.element_types or []
            index = hop[1]
            return (elements[index] if 0 <= index < len(elements) else None)
        if kind == 'member':
            return self._inline_field(container, hop[1])
        if kind == 'index':
            if container.kind == TypeKind.ARRAY:
                return container.array_element_type
            # Another accessor. It keeps the walk inside the receiver exactly
            # when IT lends inline — which is what makes std's containers the
            # carve-out and a hand-written array wrapper the refusal.
            if container.kind != TypeKind.STRUCT or not container.struct_name:
                return None
            if not self._lends_inline(container.struct_name, "[]", container):
                return None
            info = self.ns.lookup_method(container.struct_name, "[]")
            node = getattr(info, 'ast_node', None) if info is not None else None
            elem = getattr(node, 'place_type', None)
            return self._substituted(elem, container) or _INLINE_OPAQUE
        return None

    def _inline_field(self, container, name):
        """The declared type of one field, substituted for the instantiation."""
        if container.kind == TypeKind.TUPLE:
            names = container.tuple_field_names or []
            elements = container.element_types or []
            if name in names and len(names) == len(elements):
                return elements[names.index(name)]
            return None
        if container.kind != TypeKind.STRUCT or not container.struct_name:
            return None
        sym = self.ns.lookup_struct(container.struct_name)
        if sym is None or name not in (sym.fields or {}):
            return None
        return self._substituted(sym.fields[name], container)

    def _substituted(self, saw_type, container):
        """`saw_type` with the container's type arguments filled in."""
        if saw_type is None:
            return None
        name = container.struct_name or container.enum_name
        sym = (self.ns.lookup_struct(name) or self.ns.lookup_enum(name)
               if name else None)
        params = getattr(sym, 'type_params', None) if sym is not None else None
        args = container.type_args or []
        if not params or not args:
            return saw_type
        mapping = {tp.name: arg for tp, arg in zip(params, args)}
        return saw_type.substitute(mapping) if mapping else saw_type

    def _resolve_alias(self, saw_type):
        """`type R = Grid` names the same storage — resolve before judging it.

        Also normalizes the STRUCT-kinded spelling of an ENUM: a field's
        declared type reaches this pass as the parser left it, and an unknown
        capitalized name defaults to STRUCT, so an enum FIELD would answer "not
        an enum" to the payload hop.
        """
        seen = 0
        while (saw_type is not None and saw_type.kind == TypeKind.STRUCT
               and saw_type.struct_name and seen < 16):
            alias = self.ns.lookup_type_alias(saw_type.struct_name)
            target = getattr(alias, 'aliased_type', None) if alias else None
            if target is None:
                break
            saw_type = target
            seen += 1
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name
                and self.ns.lookup_struct(saw_type.struct_name) is None
                and self.ns.lookup_enum(saw_type.struct_name) is not None):
            return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name,
                           type_args=saw_type.type_args)
        return saw_type

    def _chain_down(self, node):
        """One step toward the root of a postfix chain, or None at the root.

        The one description of what a postfix chain is made of, shared by
        `_chain_head` (which stops at the first place) and the diagnostic
        suppression below (which marks the whole chain).
        """
        if isinstance(node, (MemberAccess, MethodCall)):
            return node.object
        if isinstance(node, ArrayIndex):
            return node.array_expr
        if isinstance(node, TupleIndex):
            return node.tuple_expr
        if isinstance(node, ForceUnwrap):
            return node.expr
        return None

    def _access_root(self, expr):
        """The NAME a postfix chain is rooted at (`self` for a receiver), or
        None when the chain bottoms out in something with no name — a call
        result, a literal.

        `_chain_down` already describes what a chain is made of; this is the
        one question that walk answers for the capture rule (DF-169h).
        """
        node = expr
        while node is not None:
            if isinstance(node, Identifier):
                return node.name
            if isinstance(node, SelfExpr):
                return "self"
            node = self._chain_down(node)
        return None

    def _place_spelling(self, place) -> str:
        """How a diagnostic writes this place: `v[…]` or `d.at(…)`."""
        rendered = self._render(self._place_receiver(place))
        if isinstance(place, ArrayIndex):
            return f"{rendered}[…]"
        return f"{rendered}.{place.place_method}(…)"

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
            node = self._chain_down(node)
        return None

    def _replace_head(self, expr, place, name, head_type=None):
        """`expr` with `place` swapped for the window's parameter.

        The substituted identifier carries `head_type` — the type the window
        binds it at — because the pass that would otherwise derive it may never
        look. A postfix chain whose head is a place can sit inside a design-210
        PRESERVED subtree: the coroutine transform reads a frame slot with
        `self.x.value()`, which is a lend, so an author's `x.m()` becomes a
        chain this window swallows. A preserved node answers for itself and is
        not descended into, so a head with no answer of its own is a head
        nobody ever answers for, and codegen meets an untyped receiver.
        Substituting WITH the answer keeps the subtree closed — the same
        obligation `coro_transform._answered` carries for its own grafts.

        Costs nothing on the ordinary path: `transform_place_uses` unchecks the
        tree it rewrote, which clears this stamp with every other, and the next
        check derives it again.
        """
        if expr is place:
            return self._window_head(name, place, head_type)
        if (isinstance(expr, ForceUnwrap) and expr.expr is place
                and getattr(place, 'place_optional', False)):
            # `v.get(i)!.m()`: the `!` is how the source says "I promise the
            # place is there", and the window is where that promise is kept —
            # the present path opens it with the payload itself, the absent path
            # is the panic the `!` asked for. So the unwrap is CONSUMED here; the
            # window parameter is already `&var T`, and leaving the `!` on would
            # force-unwrap a non-optional.
            return self._window_head(name, place, head_type)
        if isinstance(expr, MemberAccess):
            expr.object = self._replace_head(expr.object, place, name, head_type)
        elif isinstance(expr, MethodCall):
            expr.object = self._replace_head(expr.object, place, name, head_type)
        elif isinstance(expr, ArrayIndex):
            expr.array_expr = self._replace_head(expr.array_expr, place, name,
                                                 head_type)
        elif isinstance(expr, TupleIndex):
            expr.tuple_expr = self._replace_head(expr.tuple_expr, place, name,
                                                 head_type)
        elif isinstance(expr, ForceUnwrap):
            expr.expr = self._replace_head(expr.expr, place, name, head_type)
        return expr

    @staticmethod
    def _window_head(name, place, head_type):
        head = Identifier(name=name, line=place.line, column=place.column)
        head.resolved_type = head_type
        return head

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
        if isinstance(expr, TupleIndex):
            return f"{self._render(expr.tuple_expr)}.{expr.index}"
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
    """Does anything under `node` `move` one of `names`?

    On `ast_walk.child_nodes` (design 193 unit 3) — the hand-rolled version this
    replaced stopped at TUPLES, so `f(&var v[i], Wrap(inner: move v))` hid its
    move inside the struct literal's `field_inits` and the window took the
    move-free path.
    """
    if isinstance(node, MoveExpr) and getattr(node, 'variable', None) in names:
        return True
    return any(_mentions_move(child, names) for child in child_nodes(node))


def _escapes_control_flow(node) -> bool:
    """Does `node` contain a jump OUT of the expression it sits in?

    A window body is a closure, so a `return`/`break`/`continue` inside one
    would leave the WINDOW rather than the function that wrote it. Such a body
    stays on the ordinary path.

    On `ast_walk.child_nodes` (design 193 unit 3); the hand-rolled version
    stopped at TUPLES, so a jump written inside a struct-literal field was
    invisible.
    """
    if isinstance(node, (ReturnStatement, BreakStatement, ContinueStatement,
                         GuardLetStatement)):
        return True
    if isinstance(node, ClosureExpr):
        # A nested closure's own jumps belong to it, not to us.
        return False
    return any(_escapes_control_flow(child) for child in child_nodes(node))


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

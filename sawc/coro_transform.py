"""design 44 — the source-level coroutine transform.

Post-typecheck, pre-codegen AST rewrite. A function that is DRIVEN (reached from
a `__drive(...)` / `__drive_steps(...)` site — design 44's test-only executor
entry) is rewritten into an ordinary synthesized Saw struct (the *frame*: params
+ across-suspension locals + a state Int [+ drop-flag Bools + a result slot]) and
a `resume` method that dispatches on the state field and runs the body split at
`__suspend()` boundaries. Both are then compiled by the EXISTING codegen/deinit
machinery — nothing here emits IR.

Governing rules honoured (all decided upstream, do NOT re-open):
  * Colorless: which functions suspend is effect-inferred (design 22 graph).
  * The transform is OFF by construction for non-driven code — if a program has
    no `__drive` site, `transform_program` is never called (the pipeline skips
    it), so the whole existing suite takes the byte-identical path.
  * No forced destroy: there are no per-suspension-point destroy paths. Cleanup
    is normal control flow only; a frame dies by its own code reaching an exit.

Staging (this file grows across the brief's items):
  * v1 (landed): straight-line driven bodies over POD (Int/Bool/fixed-width)
    params, across-suspend locals, and result. State split at top-level
    `__suspend()`; the driver loops `resume` to Done.
  * later: cleanup-needing locals via frame-resident drop flags + flag-aware
    frame Deinit; nested driven calls embedded by value; suspending-recursion
    diagnostic; control flow (if/while/match) spanning a suspension.

`transform_program(program, typechecker)` mutates `program` in place and returns
True iff it changed anything (i.e. there were driven roots).
"""

import dataclasses
from ast_nodes import (
    ASTNode, Expression, Statement, Block, Argument,
    Identifier, MemberAccess, SelfExpr, IntLiteral, BoolLiteral, NoneLiteral,
    FunctionCall, MethodCall, BinaryOp, UnaryOp, EnumInit, ForceUnwrap,
    IfExpr, MatchExpr, MatchArm, WhileExpr, ReturnStatement,
    ExpressionStatement, LetStatement, AssignStatement, WhileExpr,
    Function, Struct, StructField, Enum, EnumVariant, Extension, Method,
    Parameter, SawType, TypeKind, Visibility,
)


class CoroTransformError(Exception):
    """A driven construct the v1 transform cannot yet express soundly. Surfaced
    as a compile error rather than a silent miscompile (hazard discipline)."""
    def __init__(self, message, line=0, column=0):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


# --------------------------------------------------------------------------- #
# small AST builders
# --------------------------------------------------------------------------- #

def _self_field(name, line=0, column=0):
    return MemberAccess(object=SelfExpr(line=line, column=column),
                        member=name, line=line, column=column)


def _int(n):
    return IntLiteral(value=n)


def _poll(variant):
    return EnumInit(enum_name="__Poll", variant_name=variant, arguments=[])


def _is_suspend_stmt(stmt):
    """True for a bare `__suspend()` statement — a state boundary."""
    return (isinstance(stmt, ExpressionStatement)
            and isinstance(stmt.expression, FunctionCall)
            and stmt.expression.name == "__suspend")


def _is_pod(saw_type):
    """Conservative POD test for the v1 transform: a type that needs no cleanup
    and can be zero-initialised in the frame's struct-init. Widened to
    cleanup-needing types once frame drop flags land."""
    if saw_type is None:
        return False
    return saw_type.kind in (
        TypeKind.INT, TypeKind.UINT, TypeKind.BOOL,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    )


def _zero_of(saw_type):
    if saw_type.kind == TypeKind.BOOL:
        return BoolLiteral(value=False)
    return _int(0)


def _opt(saw_type):
    """The optional type `T?` used to encode a cleanup-needing frame field."""
    return SawType(TypeKind.OPTIONAL, inner_type=saw_type)


# --------------------------------------------------------------------------- #
# identifier -> frame-field rewriting
# --------------------------------------------------------------------------- #
#
# `encmap` maps a frame-resident local/param name to its encoding:
#   "plain" — a POD field, read as `self.name`.
#   "opt"   — a cleanup-needing field encoded as `name: T?` (design 44: the
#             optional's None/Some tag IS the drop flag — None means dropped /
#             not-yet-live, Some means live; the frame's own optional cleanup
#             (brief 23) drops the inner value exactly once at frame death, and
#             nothing at all in the None state). Read as `self.name!`.

def _read_field(name, encoding, line=0, column=0):
    acc = _self_field(name, line, column)
    if encoding == "opt":
        return ForceUnwrap(expr=acc, line=line, column=column)
    return acc


def _rewrite_val(val, encmap):
    if isinstance(val, list):
        return [_rewrite_val(v, encmap) for v in val]
    if isinstance(val, tuple):
        return tuple(_rewrite_val(v, encmap) for v in val)
    if isinstance(val, Argument):
        val.value = _rewrite_node(val.value, encmap)
        return val
    if isinstance(val, ASTNode):
        return _rewrite_node(val, encmap)
    return val


def _rewrite_node(node, encmap):
    """Replace every `Identifier(name)` with its frame-field read for name in
    `encmap`, recursively over the AST. Function/struct/enum names live in plain
    string fields (FunctionCall.name, StructInit.struct_name, MemberAccess.member)
    and are untouched; only bare Identifier EXPRESSIONS are rewritten."""
    if isinstance(node, Identifier) and node.name in encmap:
        return _read_field(node.name, encmap[node.name], node.line, node.column)
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            setattr(node, f.name, _rewrite_val(getattr(node, f.name), encmap))
    return node


# --------------------------------------------------------------------------- #
# nesting / recursion analysis over the design-22 suspend graph
# --------------------------------------------------------------------------- #

def _node_display(key, nodes):
    n = nodes.get(key)
    if n is not None:
        return n.short.strip("`")
    if isinstance(key, tuple) and len(key) == 2:
        return key[1]
    return str(key)


def _find_suspending_cycle(start_key, nodes):
    """DFS the suspending-call graph from `start_key`; return the first cycle as a
    list of node keys (the repeated key closing it), or None. Only edges to
    nodes that themselves suspend are followed — a cycle here is *suspending*
    recursion, which the flat-frame (embed-by-value) model cannot size."""
    on_path = []
    on_set = set()
    visited = set()

    def dfs(key):
        if key in on_set:
            return on_path[on_path.index(key):] + [key]
        if key in visited:
            return None
        visited.add(key)
        node = nodes.get(key)
        if node is None:
            return None
        on_path.append(key)
        on_set.add(key)
        for e in node.edges:
            t = nodes.get(e.target)
            if t is None or not t.suspends:
                continue
            cyc = dfs(e.target)
            if cyc is not None:
                return cyc
        on_path.pop()
        on_set.discard(key)
        return None

    return dfs(start_key)


def _analyze_nesting(root_name, root_func, nodes):
    """Guard the two nesting cases the v1 transform must not miscompile:
      * suspending RECURSION -> a compile error naming the cycle (the flat-frame
        model embeds callee frames by value, so a cycle has no finite size);
      * any other nested SUSPENDING call -> rejected as not-yet-implemented,
        rather than silently running the callee eagerly (its __suspend would
        no-op). Non-suspending callees are fine and left untouched."""
    start = ("fn", root_name)
    cyc = _find_suspending_cycle(start, nodes)
    if cyc is not None:
        chain = " -> ".join(_node_display(k, nodes) for k in cyc)
        raise CoroTransformError(
            f"suspending recursion is not allowed: the suspending-call cycle "
            f"`{chain}` has no compile-time frame size (design 44 embeds callee "
            f"frames by value). Break the cycle or drive the inner call "
            f"separately.", root_func.line, root_func.column)
    node = nodes.get(start)
    if node is not None:
        for e in node.edges:
            t = nodes.get(e.target)
            if t is not None and t.suspends:
                callee = _node_display(e.target, nodes)
                raise CoroTransformError(
                    f"coroutine transform (v1): driven `{root_name}` makes a "
                    f"nested suspending call to `{callee}` (line {e.line}); "
                    f"embedding callee frames by value is a later item of "
                    f"design 44. Drive the inner call separately for now.",
                    root_func.line, root_func.column)


# --------------------------------------------------------------------------- #
# per-function transform
# --------------------------------------------------------------------------- #

class _FrameBuilder:
    def __init__(self, func: Function):
        self.func = func
        self.name = func.name
        self.frame_name = f"__Frame_{func.name}"
        self.ret = func.return_type or SawType(TypeKind.VOID)
        self.is_void = (self.ret.kind == TypeKind.VOID)

    def _collect_frame_locals(self):
        """v1 conservative-by-scope liveness: every top-level `let`/`var` in the
        function body has a lexical scope that spans the whole body (which
        contains the suspensions), so it is frame-resident. Locals in nested
        blocks are handled when nested control flow lands; for v1 straight-line
        bodies there are none."""
        locals_ = []  # (name, SawType)
        seen = set()
        for stmt in self.func.body.statements:
            if isinstance(stmt, LetStatement):
                t = stmt.type_annotation or getattr(stmt.value, 'resolved_type', None)
                if t is None:
                    raise CoroTransformError(
                        f"coroutine transform: local `{stmt.name}` in driven "
                        f"`{self.name}` has no resolved type", stmt.line, stmt.column)
                if stmt.name not in seen:
                    seen.add(stmt.name)
                    locals_.append((stmt.name, t))
        return locals_

    def build(self):
        func = self.func
        params = func.parameters
        frame_locals = self._collect_frame_locals()

        # Encoding per frame-resident name: POD -> "plain", cleanup-needing ->
        # "opt" (optional-encoded; the None/Some tag is the drop flag). The result
        # slot is encoded the same way and recorded on self.result_enc.
        encmap = {}
        for p in params:
            encmap[p.name] = "plain" if _is_pod(p.type) else "opt"
        for lname, lt in frame_locals:
            encmap[lname] = "plain" if _is_pod(lt) else "opt"
        self.result_enc = "plain" if (self.is_void or _is_pod(self.ret)) else "opt"

        # ---- frame struct ------------------------------------------------- #
        fields = []
        for p in params:
            ft = p.type if encmap[p.name] == "plain" else _opt(p.type)
            fields.append(StructField(name=p.name, type=ft))
        for lname, lt in frame_locals:
            ft = lt if encmap[lname] == "plain" else _opt(lt)
            fields.append(StructField(name=lname, type=ft))
        fields.append(StructField(name="__state", type=SawType(TypeKind.INT)))
        if not self.is_void:
            rt = self.ret if self.result_enc == "plain" else _opt(self.ret)
            fields.append(StructField(name="__result", type=rt))
        frame_struct = Struct(name=self.frame_name, fields=fields,
                              line=func.line, column=func.column,
                              source_file=getattr(func, 'source_file', ""))
        self.encmap = encmap
        frame_field_names = encmap

        # ---- state split -------------------------------------------------- #
        # Segments of top-level statements split at each `__suspend()`.
        segments = [[]]
        for stmt in func.body.statements:
            if _is_suspend_stmt(stmt):
                segments.append([])
            else:
                segments[-1].append(stmt)
        final_expr = func.body.final_expr

        # ---- resume method body ------------------------------------------- #
        resume_stmts = []
        n_states = len(segments)  # states 0 .. n_states-1; last is completion
        self._done_state = n_states
        for k, seg in enumerate(segments):
            # Lower the segment: `let`s of frame locals become field assignments,
            # identifiers become field reads, `return X` becomes the
            # end-of-coroutine sequence, and a conditional `move` of a frame-
            # resident local is rewritten to a field read plus a following
            # `__forget` (Part 0a: the frame drop-flag clear-without-drop).
            seg_stmts = self._lower_stmt_list(seg)
            if k < n_states - 1:
                # A suspending state: run the segment, advance, yield Pending.
                seg_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(k + 1)))
                seg_stmts.append(ReturnStatement(value=_poll("Pending")))
                resume_stmts.append(ExpressionStatement(
                    expression=IfExpr(
                        condition=BinaryOp(op="==", left=_self_field("__state"),
                                           right=_int(k)),
                        then_branch=Block(statements=seg_stmts, final_expr=None))))
            else:
                # The completion state: run the tail, store the result, mark done.
                resume_stmts.extend(seg_stmts)
                if not self.is_void and final_expr is not None:
                    tail_forgets = []
                    tail_val = self._rewrite_expr(final_expr, tail_forgets)
                    if tail_forgets:
                        raise CoroTransformError(
                            f"coroutine transform: `move` of a frame-resident "
                            f"local of driven `{self.name}` in tail-expression "
                            f"position is not supported; move it in a `return` "
                            f"statement instead", func.line, func.column)
                    resume_stmts.append(AssignStatement(
                        target=_self_field("__result"), value=tail_val))
                resume_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(n_states)))
                resume_stmts.append(ReturnStatement(value=_poll("Done")))

        resume = Method(
            name="resume",
            # Self type is the parser's VOID placeholder; registration fills it in
            # with the extension's struct type (`__Frame_<f>`).
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.ENUM, enum_name="__Poll"),
            body=Block(statements=resume_stmts, final_expr=None),
            self_mutable=True, self_is_reference=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        resume_ext = Extension(struct_name=self.frame_name, methods=[resume],
                              line=func.line, column=func.column,
                              source_file=getattr(func, 'source_file', ""))

        return frame_struct, resume_ext, params, frame_locals

    # -------------------------------------------------- frame-aware lowering
    #
    # `_lower_stmt_list` walks a statement list of the driven body and rewrites
    # it for the resume method. Per statement it:
    #   * turns a `let`/`var` of a frame-resident local into an assignment to the
    #     pre-declared `self.<name>` field;
    #   * rewrites identifier reads to `self.<field>` and a `move <frame local>`
    #     to the field read, recording opt-encoded moves so a `__forget(self.f)`
    #     is emitted right after the statement (Part 0a: the frame drop-flag
    #     clear-without-drop — the frame's own Deinit then skips the moved field);
    #   * turns `return X` into the end-of-coroutine sequence (store result, mark
    #     done, signal Done — normal-control-flow cleanup only, no forced destroy);
    #   * recurses into if/while/match blocks so a move (and its `__forget`) or a
    #     `return` lands on exactly the branch that executes it.

    def _forget_stmt(self, name):
        return ExpressionStatement(expression=FunctionCall(
            name="__forget", arguments=[Argument(name=None, value=_self_field(name))]))

    def _forgets(self, names):
        return [self._forget_stmt(n) for n in names]

    def _rewrite_expr(self, node, forgets):
        """Frame-aware expression rewrite: `Identifier(frame local)` ->
        `self.<field>` read; `move <frame local>` -> field read (+ record an
        opt-encoded move in `forgets`). Does NOT descend into control-flow blocks
        differently — callers process nested statement lists via
        `_lower_stmt_list` so forgets are scoped to the executing branch."""
        from ast_nodes import MoveExpr
        if isinstance(node, MoveExpr) and node.path is None and node.variable in self.encmap:
            name = node.variable
            enc = self.encmap[name]
            if enc == "opt":
                forgets.append(name)
            return _read_field(name, enc, getattr(node, 'line', 0),
                               getattr(node, 'column', 0))
        if isinstance(node, Identifier) and node.name in self.encmap:
            return _read_field(node.name, self.encmap[node.name], node.line, node.column)
        if isinstance(node, ASTNode):
            for f in dataclasses.fields(node):
                setattr(node, f.name,
                        self._rewrite_expr_val(getattr(node, f.name), forgets))
        return node

    def _rewrite_expr_val(self, val, forgets):
        if isinstance(val, list):
            return [self._rewrite_expr_val(v, forgets) for v in val]
        if isinstance(val, tuple):
            return tuple(self._rewrite_expr_val(v, forgets) for v in val)
        if isinstance(val, Argument):
            val.value = self._rewrite_expr(val.value, forgets)
            return val
        if isinstance(val, ASTNode):
            return self._rewrite_expr(val, forgets)
        return val

    def _lower_stmt_list(self, stmts):
        out = []
        for s in stmts:
            out.extend(self._lower_one(s))
        return out

    def _lower_one(self, s):
        if isinstance(s, ReturnStatement):
            forgets = []
            value = (self._rewrite_expr(s.value, forgets)
                     if s.value is not None else None)
            return self._done_seq(value, forgets)

        if isinstance(s, LetStatement):
            forgets = []
            value = self._rewrite_expr(s.value, forgets)
            if s.name in self.encmap:
                new = AssignStatement(
                    target=_self_field(s.name, s.line, s.column),
                    value=value, line=s.line, column=s.column)
            else:
                s.value = value
                new = s
            return [new] + self._forgets(forgets)

        if isinstance(s, AssignStatement):
            forgets = []
            s.target = self._rewrite_expr(s.target, forgets)
            s.value = self._rewrite_expr(s.value, forgets)
            return [s] + self._forgets(forgets)

        if isinstance(s, ExpressionStatement):
            e = s.expression
            if isinstance(e, IfExpr):
                forgets = []
                e.condition = self._rewrite_expr(e.condition, forgets)
                self._lower_block_in_place(e.then_branch)
                if e.else_branch is not None:
                    self._lower_block_in_place(e.else_branch)
                return [s] + self._forgets(forgets)
            if isinstance(e, WhileExpr):
                forgets = []
                if e.condition is not None:
                    e.condition = self._rewrite_expr(e.condition, forgets)
                self._lower_block_in_place(e.body)
                return [s] + self._forgets(forgets)
            if isinstance(e, MatchExpr):
                forgets = []
                e.matched_expr = self._rewrite_expr(e.matched_expr, forgets)
                for arm in e.arms:
                    if isinstance(arm.body, Block):
                        self._lower_block_in_place(arm.body)
                    else:
                        aforgets = []
                        arm.body = self._rewrite_expr(arm.body, aforgets)
                        # A bare-expression arm cannot host trailing forgets;
                        # moves there are unsupported (falls out only in tests
                        # that use block arms).
                        if aforgets:
                            raise CoroTransformError(
                                f"coroutine transform: `move` of a frame local in "
                                f"a bare match-arm expression of driven "
                                f"`{self.name}` is not supported; use a block arm",
                                self.func.line, self.func.column)
                return [s] + self._forgets(forgets)
            forgets = []
            s.expression = self._rewrite_expr(e, forgets)
            return [s] + self._forgets(forgets)

        # Fallback: generic rewrite (break/continue values, etc.).
        forgets = []
        ns = self._rewrite_expr(s, forgets)
        return [ns] + self._forgets(forgets)

    def _lower_block_in_place(self, block):
        block.statements = self._lower_stmt_list(block.statements)
        if block.final_expr is not None:
            fforgets = []
            block.final_expr = self._rewrite_expr(block.final_expr, fforgets)
            if fforgets:
                raise CoroTransformError(
                    f"coroutine transform: `move` of a frame local in a nested "
                    f"tail-expression of driven `{self.name}` is not supported; "
                    f"move it in a `return` statement instead",
                    self.func.line, self.func.column)

    def _done_seq(self, value, forgets):
        """End the coroutine at an explicit `return value`: store the result, run
        any drop-flag clears for locals moved into the result, mark done, signal
        Done. The result store loads the value first, so the following `__forget`
        clears the source flag without disturbing the moved value."""
        seq = []
        if value is not None and not self.is_void:
            seq.append(AssignStatement(target=_self_field("__result"), value=value))
        seq.extend(self._forgets(forgets))
        seq.append(AssignStatement(target=_self_field("__state"),
                                   value=_int(self._done_state)))
        seq.append(ReturnStatement(value=_poll("Done")))
        return seq


def _make_driver(fb: _FrameBuilder, mode, params, frame_locals):
    """Synthesize the driver function that steps a frame to completion.

    value: `func __drive_<f>(<params>) -> R { var __f = <frame>; loop resume; __f.__result }`
    steps: `func __drive_steps_<f>(<params>) -> Int { ...; count Pendings; __n }`
    """
    # Frame construction: params from the driver's own args (an opt-encoded param
    # auto-wraps T -> T? = Some, since it is live from the start); every other
    # field starts empty — POD locals/result zero-initialised (POD needs no
    # cleanup), cleanup-needing (opt) fields `None` (the drop flag: not-yet-live,
    # so the frame never drops a placeholder).
    field_inits = []
    for p in params:
        field_inits.append((p.name, Identifier(name=p.name)))
    for lname, lt in frame_locals:
        init = NoneLiteral() if fb.encmap[lname] == "opt" else _zero_of(lt)
        field_inits.append((lname, init))
    field_inits.append(("__state", _int(0)))
    if not fb.is_void:
        rinit = NoneLiteral() if fb.result_enc == "opt" else _zero_of(fb.ret)
        field_inits.append(("__result", rinit))

    from ast_nodes import StructInit
    frame_init = StructInit(struct_name=fb.frame_name, field_inits=field_inits)

    stmts = [LetStatement(name="__f", type_annotation=None, value=frame_init,
                          mutable=True)]

    resume_call = MethodCall(object=Identifier(name="__f"), method_name="resume",
                             arguments=[])
    done_flag_set = AssignStatement(target=Identifier(name="__done"),
                                    value=BoolLiteral(value=True))

    if mode == "steps":
        stmts.append(LetStatement(name="__n", type_annotation=None,
                                  value=_int(0), mutable=True))
        pending_body = Block(statements=[AssignStatement(
            target=Identifier(name="__n"),
            value=BinaryOp(op="+", left=Identifier(name="__n"), right=_int(1)))],
            final_expr=None)
    else:
        pending_body = Block(statements=[], final_expr=None)

    stmts.append(LetStatement(name="__done", type_annotation=None,
                              value=BoolLiteral(value=False), mutable=True))

    loop = WhileExpr(
        condition=UnaryOp(op="not", operand=Identifier(name="__done")),
        body=Block(statements=[ExpressionStatement(expression=MatchExpr(
            matched_expr=resume_call,
            arms=[
                MatchArm(variant_name="Pending", bindings=[], body=pending_body),
                MatchArm(variant_name="Done", bindings=[],
                         body=Block(statements=[done_flag_set], final_expr=None)),
            ]))], final_expr=None))
    stmts.append(ExpressionStatement(expression=loop))

    if mode == "steps":
        driver_name = f"__drive_steps_{fb.name}"
        ret = SawType(TypeKind.INT)
        final = Identifier(name="__n")
    else:
        driver_name = f"__drive_{fb.name}"
        ret = fb.ret
        result_acc = MemberAccess(object=Identifier(name="__f"), member="__result")
        # Reading the result CONSUMES the slot (opt-encoded: force-unwrap the
        # Some); an unconsumed result (e.g. driven only for its step count) stays
        # in the frame and is dropped once at frame death.
        final = ForceUnwrap(expr=result_acc) if fb.result_enc == "opt" else result_acc

    driver_params = [Parameter(name=p.name, type=p.type) for p in params]
    return Function(name=driver_name, parameters=driver_params, return_type=ret,
                    body=Block(statements=stmts, final_expr=final),
                    source_file=getattr(fb.func, 'source_file', ""))


# --------------------------------------------------------------------------- #
# drive-site rewriting
# --------------------------------------------------------------------------- #

def _rewrite_drive_sites(node, roots):
    """Rewrite `__drive(f(args))` -> `__drive_f(args)` and
    `__drive_steps(f(args))` -> `__drive_steps_f(args)` in place, everywhere."""
    if isinstance(node, FunctionCall) and node.name in ("__drive", "__drive_steps"):
        inner = node.arguments[0].value  # validated in the typechecker
        # Recurse into the inner arguments first (they may themselves contain
        # drive sites, though v1 tests do not nest drivers).
        for a in inner.arguments:
            _rewrite_val(a, set())  # no-op ident rewrite; keeps structure
        prefix = "__drive_steps_" if node.name == "__drive_steps" else "__drive_"
        node.name = prefix + inner.name
        node.arguments = inner.arguments
        return node
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            _rewrite_drive_fields(getattr(node, f.name), roots)
    return node


def _rewrite_drive_fields(val, roots):
    if isinstance(val, list):
        for i, v in enumerate(val):
            if isinstance(v, Argument):
                v.value = _rewrite_drive_sites(v.value, roots)
            elif isinstance(v, ASTNode):
                _rewrite_drive_sites(v, roots)
    elif isinstance(val, Argument):
        val.value = _rewrite_drive_sites(val.value, roots)
    elif isinstance(val, ASTNode):
        _rewrite_drive_sites(val, roots)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def transform_program(program, typechecker):
    roots = dict(getattr(typechecker, "_driven_roots", {}) or {})
    if not roots:
        return False

    funcs_by_name = {f.name: f for f in program.functions}

    new_structs = []
    new_enums = []
    new_extensions = []
    new_functions = []
    removed = set()

    # The Poll signal enum (once).
    poll_enum = Enum(name="__Poll", variants=[
        EnumVariant(name="Pending", associated_types=[]),
        EnumVariant(name="Done", associated_types=[]),
    ])
    new_enums.append(poll_enum)

    for root_name, modes in roots.items():
        func = funcs_by_name.get(root_name)
        if func is None:
            raise CoroTransformError(
                f"coroutine transform: driven function `{root_name}` not found "
                f"in the entry module (v1 supports driving entry-module free "
                f"functions only)")
        if func.type_params:
            raise CoroTransformError(
                f"coroutine transform (v1): driving generic function "
                f"`{root_name}` is not supported yet", func.line, func.column)
        _analyze_nesting(root_name, func, getattr(typechecker, "_suspend_nodes", {}))
        fb = _FrameBuilder(func)
        frame_struct, resume_ext, params, frame_locals = fb.build()
        new_structs.append(frame_struct)
        new_extensions.append(resume_ext)
        for mode in modes:
            new_functions.append(_make_driver(fb, mode, params, frame_locals))
        removed.add(root_name)

    # Rewrite all `__drive(...)` sites across the entry module's function and
    # method bodies to call the synthesized drivers.
    for f in program.functions:
        _rewrite_drive_sites(f.body, roots)
    for ext in program.extensions:
        for m in ext.methods:
            _rewrite_drive_sites(m.body, roots)

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True

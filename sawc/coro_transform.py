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
    IfExpr, MatchExpr, MatchArm, WhileExpr, ReturnStatement, ArrayIndex,
    CastExpr, ReferenceExpr,
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
    """Suspending RECURSION is a compile error naming the cycle: the flat-frame
    model embeds callee frames by value (Part 0b), so a suspending-call cycle has
    no compile-time frame size. Non-recursive nested suspending calls are now
    supported (embedded + driven); only a cycle is rejected."""
    start = ("fn", root_name)
    cyc = _find_suspending_cycle(start, nodes)
    if cyc is not None:
        chain = " -> ".join(_node_display(k, nodes) for k in cyc)
        raise CoroTransformError(
            f"suspending recursion is not allowed: the suspending-call cycle "
            f"`{chain}` has no compile-time frame size (design 44 embeds callee "
            f"frames by value). Break the cycle or drive the inner call "
            f"separately.", root_func.line, root_func.column)


# --------------------------------------------------------------------------- #
# per-function transform
# --------------------------------------------------------------------------- #

class _FrameBuilder:
    def __init__(self, func, struct_name=None):
        # `func` is a Function (free-function root) or a Method (driven method,
        # Part 0c). For a method, `struct_name` is the receiver struct: the frame
        # holds a `__recv: UnsafePointer<Struct>` pointer into the task root's
        # storage (D6: `&var self` may span suspensions under task confinement),
        # and the method body's `self` is rewritten to `self.__recv[0]`.
        self.func = func
        self.is_method = struct_name is not None
        self.struct_name = struct_name
        if self.is_method:
            self.name = f"{struct_name}_{func.name}"
            self.recv_type = SawType(TypeKind.POINTER,
                                     inner_type=SawType(TypeKind.STRUCT,
                                                        struct_name=struct_name))
        else:
            self.name = func.name
        self.frame_name = f"__Frame_{self.name}"
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

    # ------------------------------------------------------------------ #
    # Phase 1: layout. Compute the frame's fields (params + across-suspension
    # locals + embedded callee sub-frames for nested suspending calls + state
    # [+ result]) and build the frame struct. Runs for EVERY function in the
    # driven closure before any resume body is generated, so a caller can embed
    # a callee's fully-known frame by value (design 44's flat-frame model).
    # ------------------------------------------------------------------ #
    def prepare(self, suspends):
        self._suspends = suspends
        func = self.func
        # A method's `self` receiver is held as the `__recv` pointer, not a normal
        # param — drop it if the parser placed it in `parameters`.
        self.params = [p for p in func.parameters
                       if not (self.is_method and p.name == "self")]
        self.frame_locals = self._collect_frame_locals()

        # Nested suspending call sites (top-level statements only). Each embeds a
        # callee frame by value; `sub` names its field.
        self.calls = []
        for stmt in func.body.statements:
            info = self._classify_call(stmt)
            if info is not None:
                info['sub'] = f"__sub{len(self.calls)}"
                self.calls.append(info)
            else:
                self._reject_buried_suspend_call(stmt)

        encmap = {}
        for p in self.params:
            encmap[p.name] = "plain" if _is_pod(p.type) else "opt"
        for lname, lt in self.frame_locals:
            encmap[lname] = "plain" if _is_pod(lt) else "opt"
        self.result_enc = "plain" if (self.is_void or _is_pod(self.ret)) else "opt"
        self.encmap = encmap

        fields = []
        if self.is_method:
            fields.append(StructField(name="__recv", type=self.recv_type))
        for p in self.params:
            ft = p.type if encmap[p.name] == "plain" else _opt(p.type)
            fields.append(StructField(name=p.name, type=ft))
        for lname, lt in self.frame_locals:
            ft = lt if encmap[lname] == "plain" else _opt(lt)
            fields.append(StructField(name=lname, type=ft))
        for c in self.calls:
            fields.append(StructField(
                name=c['sub'],
                type=SawType(TypeKind.STRUCT, struct_name=f"__Frame_{c['callee']}")))
        fields.append(StructField(name="__state", type=SawType(TypeKind.INT)))
        if not self.is_void:
            rt = self.ret if self.result_enc == "plain" else _opt(self.ret)
            fields.append(StructField(name="__result", type=rt))
        self.frame_struct = Struct(name=self.frame_name, fields=fields,
                                   line=func.line, column=func.column,
                                   source_file=getattr(func, 'source_file', ""))
        return self.frame_struct

    def _classify_call(self, stmt):
        """If `stmt` is a top-level nested SUSPENDING call boundary, return
        {callee, args, target}; else None. Supported forms: `let x = g(args)` and
        a bare `g(args)` where `g` is a suspending free function in the driven
        closure."""
        if _is_suspend_stmt(stmt):
            return None
        fc = None
        target = None
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, FunctionCall):
            fc, target = stmt.value, stmt.name
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, FunctionCall)):
            fc = stmt.expression
        if fc is None or fc.name not in self._suspends:
            return None
        if getattr(fc, 'type_args', None):
            raise CoroTransformError(
                f"coroutine transform: nested suspending call to generic "
                f"`{fc.name}` from `{self.name}` is not supported "
                f"(effect-polymorphism, design 18 A5)", fc.line, fc.column)
        return {'callee': fc.name, 'args': list(fc.arguments), 'target': target}

    def _reject_buried_suspend_call(self, stmt):
        """A suspending call in a non-top-level position (inside a larger
        expression, an `if`/`while`/`match` branch, or a method-call receiver) is
        not expressible by the flat state split. Reject with a clear message
        rather than miscompile (the callee's __suspend would silently no-op)."""
        found = []

        def scan(n):
            if isinstance(n, FunctionCall) and n.name in self._suspends:
                found.append(n)
            if isinstance(n, MethodCall):
                mname = getattr(n, 'method_name', None)
                # Suspending method receiver handled by Part 0c on driving
                # methods, not here; leave method calls to that path.
            if isinstance(n, ASTNode):
                for f in dataclasses.fields(n):
                    v = getattr(n, f.name)
                    if isinstance(v, list):
                        for x in v:
                            if isinstance(x, Argument):
                                scan(x.value)
                            elif isinstance(x, ASTNode):
                                scan(x)
                    elif isinstance(v, Argument):
                        scan(v.value)
                    elif isinstance(v, ASTNode):
                        scan(v)

        scan(stmt)
        if found:
            g = found[0]
            raise CoroTransformError(
                f"coroutine transform: suspending call to `{g.name}` in `{self.name}` "
                f"appears in a nested/expression position; only a top-level "
                f"`let x = {g.name}(...)` or `{g.name}(...)` statement is supported",
                g.line, g.column)

    # ------------------------------------------------------------------ #
    # Phase 2: the resume state machine. Split the body at `__suspend()` and at
    # each nested suspending call; a plain suspend advances one state, a nested
    # call builds+drives its embedded sub-frame across the caller's own
    # suspensions before capturing the callee's result and advancing.
    # ------------------------------------------------------------------ #
    def build_resume(self, fbs):
        func = self.func
        segments = [[]]
        transitions = []  # ('suspend', None) | ('call', info) between segments
        call_idx = 0
        for stmt in func.body.statements:
            if _is_suspend_stmt(stmt):
                transitions.append(('suspend', None))
                segments.append([])
                continue
            if self._classify_call(stmt) is not None:
                # Reuse the prepared call record (it carries the sub-frame field
                # name `sub`), matched by body order.
                transitions.append(('call', self.calls[call_idx]))
                call_idx += 1
                segments.append([])
                continue
            segments[-1].append(stmt)
        final_expr = func.body.final_expr

        # The final completion segment sits at `final_state`; `done_state` is one
        # past it (the terminal marker written when the frame reports Done). A
        # `return` in any earlier segment jumps straight to done_state, so it must
        # be known before lowering any segment.
        final_state = sum(2 if kind == 'call' else 1 for kind, _ in transitions)
        self._done_state = final_state + 1

        resume_stmts = []
        state = 0
        for k, seg in enumerate(segments):
            seg_stmts = self._lower_stmt_list(seg)
            if k == len(segments) - 1:
                # Completion: run the tail, store the result, mark done.
                if not self.is_void and final_expr is not None:
                    tail_forgets = []
                    tail_val = self._rewrite_expr(final_expr, tail_forgets)
                    if tail_forgets:
                        raise CoroTransformError(
                            f"coroutine transform: `move` of a frame-resident "
                            f"local of `{self.name}` in tail-expression position "
                            f"is not supported; move it in a `return` statement",
                            func.line, func.column)
                    seg_stmts.append(AssignStatement(
                        target=_self_field("__result"), value=tail_val))
                seg_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(self._done_state)))
                seg_stmts.append(ReturnStatement(value=_poll("Done")))
                resume_stmts.append(self._state_if(state, seg_stmts))
                break

            kind, info = transitions[k]
            if kind == 'suspend':
                seg_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(state + 1)))
                seg_stmts.append(ReturnStatement(value=_poll("Pending")))
                resume_stmts.append(self._state_if(state, seg_stmts))
                state += 1
            else:  # nested suspending call
                drive_state = state + 1
                next_state = state + 2
                seg_stmts.extend(self._build_sub_frame(info, fbs))
                seg_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(drive_state)))
                seg_stmts.append(ReturnStatement(value=_poll("Pending")))
                resume_stmts.append(self._state_if(state, seg_stmts))
                resume_stmts.append(self._state_if(
                    drive_state, self._drive_sub(info, fbs, next_state)))
                state = next_state

        resume = Method(
            name="resume",
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
        return self.frame_struct, resume_ext

    def _state_if(self, state, stmts):
        return ExpressionStatement(expression=IfExpr(
            condition=BinaryOp(op="==", left=_self_field("__state"),
                               right=_int(state)),
            then_branch=Block(statements=stmts, final_expr=None)))

    def _build_sub_frame(self, info, fbs):
        """Construct the embedded callee frame from the call's arguments (the
        arrival state). Returns statements: `self.__subN = __Frame_g(args...)`
        plus any drop-flag clears for args moved out of the caller frame."""
        callee_fb = fbs[info['callee']]
        forgets = []
        arg_vals = []
        for i, a in enumerate(info['args']):
            arg_vals.append(self._rewrite_expr(a.value, forgets))
        init = _build_frame_init(callee_fb, arg_vals, fbs)
        out = [AssignStatement(target=_self_field(info['sub']), value=init)]
        out.extend(self._forgets(forgets))
        return out

    def _drive_sub(self, info, fbs, next_state):
        """The drive state for a nested call: resume the sub-frame; on Pending
        stay (return Pending); on Done capture the callee's result into the target
        local (moving it out of the sub-frame with a `__forget`) and advance."""
        callee_fb = fbs[info['callee']]
        sub = info['sub']
        done_body = []
        target = info['target']
        if target is not None and not callee_fb.is_void:
            res = MemberAccess(object=_self_field(sub), member="__result")
            if callee_fb.result_enc == "opt":
                res = ForceUnwrap(expr=res)
            done_body.append(AssignStatement(
                target=_self_field(target), value=res))
            if callee_fb.result_enc == "opt":
                done_body.append(ExpressionStatement(expression=FunctionCall(
                    name="__forget", arguments=[Argument(name=None,
                        value=MemberAccess(object=_self_field(sub),
                                           member="__result"))])))
        done_body.append(AssignStatement(
            target=_self_field("__state"), value=_int(next_state)))
        done_body.append(ReturnStatement(value=_poll("Pending")))

        resume_call = MethodCall(object=_self_field(sub), method_name="resume",
                                 arguments=[])
        match = MatchExpr(matched_expr=resume_call, arms=[
            MatchArm(variant_name="Pending", bindings=[], body=Block(
                statements=[ReturnStatement(value=_poll("Pending"))], final_expr=None)),
            MatchArm(variant_name="Done", bindings=[], body=Block(
                statements=done_body, final_expr=None)),
        ])
        return [ExpressionStatement(expression=match)]

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
        if self.is_method and isinstance(node, SelfExpr):
            # The method's `self` -> the receiver through the frame pointer:
            # `self.__recv[0]` (here `self` is the frame — resume's receiver).
            return ArrayIndex(
                array_expr=_self_field("__recv", node.line, node.column),
                index=_int(0), line=node.line, column=node.column)
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
        # A `__suspend()` reached HERE is nested inside control flow (an if/while/
        # match body) rather than at the function's top level. The state split is
        # over top-level statements only, so a nested suspension would silently
        # become a no-op (it would not actually suspend). Reject it honestly
        # rather than miscompile -- a suspension spanning a loop/branch needs a
        # CFG-based split (a later item; not built here).
        if _is_suspend_stmt(s):
            raise CoroTransformError(
                f"coroutine transform: a suspension inside nested control flow "
                f"(loop/if/match) in `{self.name}` is not supported; the state "
                f"split is over top-level statements only",
                getattr(s, 'line', self.func.line), getattr(s, 'column', 0))
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

        # A control-flow expression may appear as a bare statement (a user
        # `while`/`if`/`match`) or wrapped in an ExpressionStatement (driver-
        # generated). Handle both; lower nested blocks so a nested `return`,
        # `move`+`__forget`, or nested-suspension diagnostic reaches them.
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, (IfExpr, WhileExpr, MatchExpr)):
            e = ctrl
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

        # Fallback: a plain expression statement (`foo()`), a break/continue with
        # a value, etc. — rewrite in place, hosting any drop-flag clears after.
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


def _zeroed_value(enc, saw_type):
    """The empty initial value for a not-yet-live frame field: `None` for a
    cleanup-needing (opt-encoded) field — the drop flag reads not-live, so the
    frame never drops a placeholder — and a zero for a POD field (needs no
    cleanup)."""
    return NoneLiteral() if enc == "opt" else _zero_of(saw_type)


def _build_frame_init(fb: _FrameBuilder, param_values, fbs, recv_value=None):
    """A `StructInit` for `fb`'s frame: param fields from `param_values` (an
    opt-encoded param auto-wraps T -> Some), every local empty, every embedded
    callee sub-frame zero-initialised (a dead frame, rebuilt with real args when
    its call site is reached — the dead frame holds no live cleanup fields, so
    the rebuild's assignment drops nothing), state 0, result empty. For a method
    frame the receiver pointer `__recv` leads (Part 0c)."""
    from ast_nodes import StructInit
    field_inits = []
    if fb.is_method:
        field_inits.append(("__recv", recv_value))
    for i, p in enumerate(fb.params):
        field_inits.append((p.name, param_values[i]))
    for lname, lt in fb.frame_locals:
        field_inits.append((lname, _zeroed_value(fb.encmap[lname], lt)))
    for c in fb.calls:
        sub_fb = fbs[c['callee']]
        zvals = [_zeroed_value(sub_fb.encmap[p.name], p.type) for p in sub_fb.params]
        field_inits.append((c['sub'], _build_frame_init(sub_fb, zvals, fbs)))
    field_inits.append(("__state", _int(0)))
    if not fb.is_void:
        field_inits.append(("__result", _zeroed_value(fb.result_enc, fb.ret)))
    return StructInit(struct_name=fb.frame_name, field_inits=field_inits)


def _make_driver(fb: _FrameBuilder, mode, fbs):
    """Synthesize the driver function that steps a frame to completion.

    value: `func __drive_<f>(<params>) -> R { var __f = <frame>; loop resume; __f.__result }`
    steps: `func __drive_steps_<f>(<params>) -> Int { ...; count Pendings; __n }`
    """
    params = fb.params
    # A method driver takes the receiver first, as an `UnsafePointer<Struct>`
    # (design 42's `&T`->pointer bridge is what the drive site supplies).
    recv_value = Identifier(name="__recv") if fb.is_method else None
    frame_init = _build_frame_init(
        fb, [Identifier(name=p.name) for p in params], fbs, recv_value=recv_value)

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
    if fb.is_method:
        driver_params = [Parameter(name="__recv", type=fb.recv_type)] + driver_params
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
        prefix = "__drive_steps_" if node.name == "__drive_steps" else "__drive_"
        if isinstance(inner, MethodCall):
            # Part 0c: `__drive(recv.m(args))` -> `__drive_Struct_m((&var recv) as
            # UnsafePointer<Struct>, args)`. The receiver is passed as a raw
            # pointer into its own storage (design 42's &T->pointer bridge); the
            # frame mutates the caller's value through it (D6).
            recv_type = getattr(inner.object, 'resolved_type', None)
            struct_name = getattr(recv_type, 'struct_name', None)
            ptr_type = SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.STRUCT,
                                                  struct_name=struct_name))
            recv_ptr = CastExpr(
                expr=ReferenceExpr(expr=inner.object, mutable=False),
                target_type=ptr_type)
            node.name = f"{prefix}{struct_name}_{inner.method_name}"
            node.arguments = [Argument(name=None, value=recv_ptr)] + list(inner.arguments)
            return node
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

def _find_method(program, struct_name, method_name):
    """Locate a driven method's AST and the extension that owns it."""
    for ext in program.extensions:
        if getattr(ext, 'struct_name', None) != struct_name:
            continue
        for m in ext.methods:
            if m.name == method_name:
                return m, ext
    return None, None


def transform_program(program, typechecker):
    roots = dict(getattr(typechecker, "_driven_roots", {}) or {})
    method_roots = dict(getattr(typechecker, "_driven_method_roots", {}) or {})
    if not roots and not method_roots:
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

    nodes = getattr(typechecker, "_suspend_nodes", {})

    # The driven closure: every suspending entry-module free function reachable
    # from a driven root through suspending-call edges. Each becomes a frame +
    # resume method; a nested suspending call embeds the callee's frame by value
    # and drives it (Part 0b). Only the roots themselves also get __drive_*
    # drivers.
    closure = []
    seen = set()
    work = list(roots.keys())
    while work:
        n = work.pop()
        if n in seen:
            continue
        seen.add(n)
        func = funcs_by_name.get(n)
        if func is None:
            raise CoroTransformError(
                f"coroutine transform: suspending function `{n}` not found in the "
                f"entry module (driving supports entry-module free functions only)")
        if func.type_params:
            raise CoroTransformError(
                f"coroutine transform: transforming generic suspending function "
                f"`{n}` is not supported (effect-polymorphism, design 18 A5)",
                func.line, func.column)
        closure.append(n)
        node = nodes.get(("fn", n))
        if node is not None:
            for e in node.edges:
                t = nodes.get(e.target)
                if (t is not None and t.suspends
                        and isinstance(e.target, tuple) and e.target[0] == "fn"
                        and e.target[1] in funcs_by_name):
                    work.append(e.target[1])

    for root_name in roots:
        _analyze_nesting(root_name, funcs_by_name[root_name], nodes)

    # Phase 1: build every frame's layout (so a caller can embed a callee frame
    # by value). Phase 2: generate every resume state machine.
    suspends_set = set(closure)
    fbs = {n: _FrameBuilder(funcs_by_name[n]) for n in closure}
    for n in closure:
        new_structs.append(fbs[n].prepare(suspends_set))
    for n in closure:
        _, resume_ext = fbs[n].build_resume(fbs)
        new_extensions.append(resume_ext)
    for root_name, modes in roots.items():
        for mode in modes:
            new_functions.append(_make_driver(fbs[root_name], mode, fbs))
        removed.add(root_name)
    removed.update(closure)

    # Part 0c: driven suspending methods. Each becomes a frame that holds a
    # `__recv` pointer into the receiver's storage; the method body's `self` is
    # rewritten to `self.__recv[0]`. Driven directly (no method embedding yet).
    removed_methods = []  # (extension, method) to strip after generation
    for (struct_name, method_name), modes in method_roots.items():
        method_ast, ext = _find_method(program, struct_name, method_name)
        if method_ast is None:
            raise CoroTransformError(
                f"coroutine transform: driven method `{struct_name}.{method_name}` "
                f"not found in the entry module")
        if method_ast.type_params or getattr(ext, 'type_params', None):
            raise CoroTransformError(
                f"coroutine transform: driving generic method "
                f"`{struct_name}.{method_name}` is not supported "
                f"(effect-polymorphism, design 18 A5)",
                method_ast.line, method_ast.column)
        mfb = _FrameBuilder(method_ast, struct_name=struct_name)
        new_structs.append(mfb.prepare(suspends_set))
        _, resume_ext = mfb.build_resume(fbs)
        new_extensions.append(resume_ext)
        for mode in modes:
            new_functions.append(_make_driver(mfb, mode, fbs))
        removed_methods.append((ext, method_ast))

    # Rewrite all `__drive(...)` sites across the entry module's function and
    # method bodies to call the synthesized drivers.
    for f in program.functions:
        _rewrite_drive_sites(f.body, roots)
    for ext in program.extensions:
        for m in ext.methods:
            _rewrite_drive_sites(m.body, roots)

    # Strip driven methods from their extensions (replaced by frame + resume).
    for ext, method_ast in removed_methods:
        ext.methods = [m for m in ext.methods if m is not method_ast]

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True

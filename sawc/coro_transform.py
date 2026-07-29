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
    CastExpr, ReferenceExpr, RangeExpr, ForLoop, MoveExpr,
    BreakStatement, ContinueStatement,
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


# The suspension-boundary intrinsics: `__suspend` (test-only synthetic), and the
# real primitives `yield_now()` (immediately re-ready) and `sleep(ms)` (timed).
_SUSPEND_CALLS = ("__suspend", "yield_now", "sleep")


def _suspend_call_name(stmt):
    if (isinstance(stmt, ExpressionStatement)
            and isinstance(stmt.expression, FunctionCall)
            and stmt.expression.name in _SUSPEND_CALLS):
        return stmt.expression.name
    return None


def _is_suspend_stmt(stmt):
    """True for a bare suspension-point statement — a state boundary. Covers the
    synthetic `__suspend()` and the real `yield_now()`/`sleep(ms)` primitives."""
    return _suspend_call_name(stmt) is not None


def _wake_expr(stmt):
    """The wake reason a suspension carries, stored in the frame's `__wake` field
    and read by the executor after a Pending: milliseconds for `sleep(ms)`, else
    0 (`__suspend`/`yield_now` — immediately re-ready)."""
    fc = stmt.expression
    if fc.name == "sleep":
        return fc.arguments[0].value
    return _int(0)


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
    def __init__(self, func, struct_name=None, tc=None, force_opt_result=False):
        # design 52b item 2: a spawn-root frame forces its `__result` opt-encoded
        # even for a POD return, so `TaskHandle<T>` uniformly holds a
        # `UnsafePointer<T?>` and `join` takes the value with the same
        # force-unwrap + `__forget` handoff regardless of T.
        self.force_opt_result = force_opt_result
        # `func` is a Function (free-function root) or a Method (driven method,
        # Part 0c). For a method, `struct_name` is the receiver struct: the frame
        # holds a `__recv: UnsafePointer<Struct>` pointer into the task root's
        # storage (D6: `&var self` may span suspensions under task confinement),
        # and the method body's `self` is rewritten to `self.__recv[0]`.
        # `tc` is the typechecker (design 52 Part 0: needed to resolve match-arm
        # binding types when a suspension splits a `match` across states).
        self.func = func
        self._tc = tc
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
        """Conservative-by-scope liveness (design 52 Part 0): every local whose
        lexical scope SPANS a suspension is frame-resident. A block "spans a
        suspension" when it (transitively) contains a suspension point; every
        `let`/`var` directly declared in such a block, plus a suspending `for`'s
        loop variable + its synthesized end bound, plus the payload bindings of a
        suspending `match`, live across a state boundary and so become frame
        fields. Locals in scopes that do NOT span a suspension keep ordinary
        real-local codegen (they never cross a state boundary). Larger frames than
        a true live-range analysis, correct and simple."""
        locals_ = []  # (name, SawType)
        seen = set()

        def add(name, t, line=0, column=0):
            if t is None:
                raise CoroTransformError(
                    f"coroutine transform: local `{name}` in driven "
                    f"`{self.name}` has no resolved type", line, column)
            if name not in seen:
                seen.add(name)
                locals_.append((name, t))

        def walk_block(block):
            scope_spans = self._spans_suspension(block)
            for s in block.statements:
                walk_stmt(s, scope_spans)

        def walk_stmt(s, scope_spans):
            if isinstance(s, LetStatement):
                if scope_spans:
                    t = s.type_annotation or getattr(s.value, 'resolved_type', None)
                    add(s.name, t, s.line, s.column)
                return
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                walk_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    walk_block(ctrl.else_branch)
            elif isinstance(ctrl, WhileExpr):
                walk_block(ctrl.body)
            elif isinstance(ctrl, MatchExpr):
                if self._spans_suspension(ctrl):
                    for nm, t in self._match_binding_types(ctrl).items():
                        add(nm, t, ctrl.line, ctrl.column)
                for arm in ctrl.arms:
                    if isinstance(arm.body, Block):
                        walk_block(arm.body)
            elif isinstance(s, ForLoop):
                if self._spans_suspension(s):
                    add(s.variable, SawType(TypeKind.INT), s.line, s.column)
                    add(f"__end_{s.variable}", SawType(TypeKind.INT), s.line, s.column)
                walk_block(s.body)

        walk_block(self.func.body)
        return locals_

    # ------------------------------------------------------------------ #
    # suspension analysis over the body (CFG split decisions, design 52)
    # ------------------------------------------------------------------ #
    def _spans_suspension(self, node):
        """True if `node` (a Block/Statement/Expression subtree) transitively
        contains a suspension point: a suspend primitive (`__suspend`/`yield_now`/
        `sleep`) or a call to a suspending function in the driven closure. Decides
        whether a control-flow construct must be CFG-split into states or can be
        lowered in place unchanged."""
        found = [False]

        def scan(n):
            if found[0]:
                return
            if isinstance(n, FunctionCall) and (
                    n.name in _SUSPEND_CALLS or n.name in self._suspends):
                found[0] = True
                return
            if isinstance(n, ASTNode):
                for f in dataclasses.fields(n):
                    scan_val(getattr(n, f.name))

        def scan_val(v):
            if found[0]:
                return
            if isinstance(v, (list, tuple)):
                for x in v:
                    scan_val(x)
            elif isinstance(v, Argument):
                scan_val(v.value)
            elif isinstance(v, ASTNode):
                scan(v)

        scan(node)
        return found[0]

    def _match_binding_types(self, match_expr):
        """Resolve every arm binding of `match_expr` to its payload type, via the
        typechecker's enum info (the scrutinee's enum type was recorded on the
        node during checking). Used to give a suspending match's bindings a frame
        field type."""
        out = {}
        mt = getattr(match_expr, 'matched_enum_type', None)
        if mt is None or self._tc is None:
            return out
        einfo = self._tc.get_enum_info(mt.enum_name, from_type=mt)
        if einfo is None:
            return out
        mapping = {}
        if einfo.type_params and mt.type_args:
            for tp, ta in zip(einfo.type_params, mt.type_args):
                mapping[tp.name] = ta
        for arm in match_expr.arms:
            if arm.variant_name == "_" or arm.variant_name not in einfo.variants:
                continue
            vps = einfo.variants[arm.variant_name]
            if mapping:
                vps = [(nm, t.substitute(mapping)) for nm, t in vps]
            for bname, (_pn, ptype) in zip(arm.bindings, vps):
                if bname != "_":
                    out[bname] = ptype
        return out

    def _collect_calls(self):
        """Walk the whole body for nested suspending call sites (top-level OR
        inside control-flow bodies). Each embeds a callee frame by value; `sub`
        names its field. Keyed by statement identity so the CFG walk can recover a
        call's sub-frame field. A suspending call buried in an expression position
        (not a bare `let x = g(...)` / `g(...)` statement) is rejected honestly."""
        self.calls = []
        self.call_by_id = {}

        def visit_block(block):
            for s in block.statements:
                visit_stmt(s)

        def visit_stmt(s):
            info = self._classify_call(s)
            if info is not None:
                info['sub'] = f"__sub{len(self.calls)}"
                self.calls.append(info)
                self.call_by_id[id(s)] = info
                return
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                visit_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    visit_block(ctrl.else_branch)
            elif isinstance(ctrl, WhileExpr):
                visit_block(ctrl.body)
            elif isinstance(ctrl, MatchExpr):
                for arm in ctrl.arms:
                    if isinstance(arm.body, Block):
                        visit_block(arm.body)
            elif isinstance(s, ForLoop):
                visit_block(s.body)
            elif not _is_suspend_stmt(s):
                # A bare suspension-point statement is a legal state boundary; any
                # OTHER leaf holding a suspending call in an expression position is
                # not expressible and is rejected.
                self._reject_buried_suspend_call(s)

        visit_block(self.func.body)

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
        # Nested suspending call sites (whole body, incl. control-flow bodies).
        # Each embeds a callee frame by value; `sub` names its field. Must run
        # before local collection (both consult `self._suspends`).
        self._collect_calls()
        self.frame_locals = self._collect_frame_locals()

        encmap = {}
        for p in self.params:
            encmap[p.name] = "plain" if _is_pod(p.type) else "opt"
        for lname, lt in self.frame_locals:
            encmap[lname] = "plain" if _is_pod(lt) else "opt"
        if self.is_void:
            self.result_enc = "plain"
        elif self.force_opt_result or not _is_pod(self.ret):
            self.result_enc = "opt"
        else:
            self.result_enc = "plain"
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
        # The wake reason the frame communicates to the executor on a Pending
        # (design 45 item 4): 0 = ready (yield), >0 = sleep that many ms.
        fields.append(StructField(name="__wake", type=SawType(TypeKind.INT)))
        # design 52b item 3: the cooperative cancel word. `handle.cancel()` sets it
        # (through a `TaskHandle`'s raw pointer into this frame); task code reads it
        # via `cancelled()`, which the transform rewrites to `self.__cancel`. NO
        # forced destroy — the frame exits only through its own control flow.
        fields.append(StructField(name="__cancel", type=SawType(TypeKind.BOOL)))
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
            if isinstance(n, FunctionCall) and (
                    n.name in self._suspends or n.name in _SUSPEND_CALLS):
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
    # Phase 2: the resume state machine, built by a CFG walk (design 52 Part 0).
    #
    # The body lowers into a list of basic BLOCKS, each a state. The resume method
    # is an infinite `while { if __state == 0 {...}  if __state == 1 {...} ... }`
    # dispatch loop. Each block ends in a terminator:
    #   * suspend  — set __wake + __state = target; `return Pending`.
    #   * done     — store __result + __state = <done>; `return Done`.
    #   * goto     — set __state = target; `continue` (re-dispatch, same resume).
    #   * branch   — `if cond { __state = A } else { __state = B }`; `continue`.
    # Loop back-edges and branch merges are ordinary gotos, so a suspension INSIDE
    # a while/for/if/match body just terminates its block and resumes at the next
    # block — counted iterations survive across resumes because loop-carried
    # locals are frame-resident. Straight-line bodies produce one block per
    # segment exactly as the old top-level split did (backward compatible).
    # ------------------------------------------------------------------ #
    def build_resume(self, fbs):
        func = self.func
        self._fbs = fbs
        self._blocks = [[]]      # block 0 is the entry
        self._term = set()       # ids of blocks already terminated
        self._done_lits = []     # IntLiterals for the __state=<done> marker
        self.cur = 0

        self._lower_stmts(func.body.statements, loop_ctx=None)
        if self.cur not in self._term:
            fe = func.body.final_expr
            if fe is not None:
                forgets = []
                val = self._rewrite_expr(fe, forgets)
                if forgets:
                    raise CoroTransformError(
                        f"coroutine transform: `move` of a frame-resident local of "
                        f"`{self.name}` in tail-expression position is not "
                        f"supported; move it in a `return` statement",
                        func.line, func.column)
                self._done(val)
            else:
                self._done(None)

        # The done marker is one past the last block id: no `if __state == k`
        # matches it, so a stray re-dispatch after Done is inert (Done already
        # returned to the executor, which never resumes a completed frame).
        done_state = len(self._blocks)
        for lit in self._done_lits:
            lit.value = done_state

        if_chain = [self._state_if(k, self._blocks[k])
                    for k in range(len(self._blocks))]
        # A `while true` dispatch loop (a constant-true condition, NOT the
        # infinite `while {}` expression form, which would demand a break): each
        # block terminates with `return` (Pending/Done) or `continue` (re-dispatch
        # after a state change), so the loop only ever exits via a return.
        loop = ExpressionStatement(expression=WhileExpr(
            condition=BoolLiteral(value=True),
            body=Block(statements=if_chain, final_expr=None)))

        resume = Method(
            name="resume",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.ENUM, enum_name="__Poll"),
            body=Block(statements=[loop], final_expr=None),
            self_mutable=True, self_is_reference=True, is_sync=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # The `__wake read surface` of the Resumable protocol (design 52b item 1):
        # a `&self` accessor returning the frame's wake word, so the executor can
        # schedule an erased task without reaching into a concrete field.
        wake_reason = Method(
            name="__wake_reason",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=False)],
            return_type=SawType(TypeKind.INT),
            body=Block(statements=[], final_expr=_self_field("__wake")),
            self_mutable=False, self_is_reference=True, is_sync=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # Every frame conforms to the builtin `Resumable` trait (design 52b item
        # 1): the conformance is what lets a frame be erased into
        # `Box<any Resumable>` for the heterogeneous run queue. Concrete drives
        # (nested sub-frames, the entry executor, `__drive_*`) still bind `resume`
        # statically — conformance only synthesizes a vtable at an erasure site.
        resume_ext = Extension(struct_name=self.frame_name,
                               methods=[resume, wake_reason],
                               conformances=["Resumable"],
                               line=func.line, column=func.column,
                               source_file=getattr(func, 'source_file', ""))
        return self.frame_struct, resume_ext

    def _state_if(self, state, stmts):
        return ExpressionStatement(expression=IfExpr(
            condition=BinaryOp(op="==", left=_self_field("__state"),
                               right=_int(state)),
            then_branch=Block(statements=stmts, final_expr=None)))

    # ----------------------------------------------------- block plumbing
    def _new_block(self):
        self._blocks.append([])
        return len(self._blocks) - 1

    def _emit(self, stmts):
        if self.cur in self._term:
            return
        self._blocks[self.cur].extend(stmts)

    def _goto(self, target):
        """Unconditional edge: set the state word and re-dispatch in the same
        resume call (loop back-edge / branch merge)."""
        if self.cur in self._term:
            return
        self._blocks[self.cur].append(
            AssignStatement(target=_self_field("__state"), value=_int(target)))
        self._blocks[self.cur].append(ContinueStatement())
        self._term.add(self.cur)

    def _branch(self, cond, then_target, else_target):
        if self.cur in self._term:
            return
        self._blocks[self.cur].append(ExpressionStatement(expression=IfExpr(
            condition=cond,
            then_branch=Block(statements=[AssignStatement(
                target=_self_field("__state"), value=_int(then_target))],
                final_expr=None),
            else_branch=Block(statements=[AssignStatement(
                target=_self_field("__state"), value=_int(else_target))],
                final_expr=None))))
        self._blocks[self.cur].append(ContinueStatement())
        self._term.add(self.cur)

    def _suspend_to(self, wake, target):
        if self.cur in self._term:
            return
        self._blocks[self.cur].append(
            AssignStatement(target=_self_field("__wake"), value=wake))
        self._blocks[self.cur].append(
            AssignStatement(target=_self_field("__state"), value=_int(target)))
        self._blocks[self.cur].append(ReturnStatement(value=_poll("Pending")))
        self._term.add(self.cur)

    def _done(self, value, forgets=None):
        if self.cur in self._term:
            return
        self._blocks[self.cur].extend(self._done_seq(value, forgets or []))
        self._term.add(self.cur)

    # ----------------------------------------------------- the CFG walk
    def _lower_stmts(self, stmts, loop_ctx):
        for s in stmts:
            if self.cur in self._term:
                break  # unreachable tail after a return/break/continue
            self._lower_stmt(s, loop_ctx)

    def _lower_block(self, block, loop_ctx):
        self._lower_stmts(block.statements, loop_ctx)
        if block.final_expr is not None and self.cur not in self._term:
            # A branch/loop-body tail expression in statement position: run it for
            # its side effects (its value is discarded here).
            self._lower_stmt(
                ExpressionStatement(expression=block.final_expr), loop_ctx)

    def _lower_stmt(self, s, loop_ctx):
        # A suspension primitive: terminate this block, resume at a fresh one.
        if _is_suspend_stmt(s):
            wake = _wake_expr(s)
            nxt = self._new_block()
            self._suspend_to(wake, nxt)
            self.cur = nxt
            return
        # A nested suspending call: embed + drive the callee sub-frame.
        info = self.call_by_id.get(id(s))
        if info is not None:
            self._emit_nested_call(info, loop_ctx)
            return
        if isinstance(s, ReturnStatement):
            forgets = []
            value = (self._rewrite_expr(s.value, forgets)
                     if s.value is not None else None)
            self._done(value, forgets)
            return
        if isinstance(s, BreakStatement):
            if s.value is not None:
                raise CoroTransformError(
                    f"coroutine transform: `break` with a value out of a "
                    f"suspension-spanning loop in `{self.name}` is not supported",
                    s.line, s.column)
            if loop_ctx is None:
                raise CoroTransformError(
                    f"coroutine transform: `break` outside a loop in `{self.name}`",
                    s.line, s.column)
            self._goto(loop_ctx[1])
            return
        if isinstance(s, ContinueStatement):
            if loop_ctx is None:
                raise CoroTransformError(
                    f"coroutine transform: `continue` outside a loop in "
                    f"`{self.name}`", s.line, s.column)
            self._goto(loop_ctx[0])
            return

        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr) and self._spans_suspension(ctrl):
            self._split_if(ctrl, loop_ctx)
            return
        if isinstance(ctrl, WhileExpr) and self._spans_suspension(ctrl):
            self._split_while(ctrl, loop_ctx)
            return
        if isinstance(s, ForLoop) and self._spans_suspension(s):
            self._split_for(s, loop_ctx)
            return
        if isinstance(ctrl, MatchExpr) and self._spans_suspension(ctrl):
            self._split_match(ctrl, loop_ctx)
            return

        # Non-suspending statement (incl. non-spanning control flow): lower in
        # place — identifier→frame-field rewrites, drop-flag clears, returns→done.
        self._emit(self._lower_inplace(s))

    def _split_if(self, e, loop_ctx):
        forgets = []
        cond = self._rewrite_expr(e.condition, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` in the condition of a "
                f"suspension-spanning `if` in `{self.name}` is not supported",
                e.line, e.column)
        then_b = self._new_block()
        else_b = self._new_block() if e.else_branch is not None else None
        merge = self._new_block()
        self._branch(cond, then_b, else_b if else_b is not None else merge)
        self.cur = then_b
        self._lower_block(e.then_branch, loop_ctx)
        if self.cur not in self._term:
            self._goto(merge)
        if else_b is not None:
            self.cur = else_b
            self._lower_block(e.else_branch, loop_ctx)
            if self.cur not in self._term:
                self._goto(merge)
        self.cur = merge

    def _split_while(self, e, loop_ctx):
        if e.condition is not None:
            header = self._new_block()
            body_b = self._new_block()
            exit_b = self._new_block()
            self._goto(header)
            self.cur = header
            forgets = []
            cond = self._rewrite_expr(e.condition, forgets)
            if forgets:
                raise CoroTransformError(
                    f"coroutine transform: `move` in the condition of a "
                    f"suspension-spanning `while` in `{self.name}` is not "
                    f"supported", e.line, e.column)
            self._branch(cond, body_b, exit_b)
            self.cur = body_b
            self._lower_block(e.body, loop_ctx=(header, exit_b))
            if self.cur not in self._term:
                self._goto(header)
            self.cur = exit_b
        else:
            body_b = self._new_block()
            exit_b = self._new_block()
            self._goto(body_b)
            self.cur = body_b
            self._lower_block(e.body, loop_ctx=(body_b, exit_b))
            if self.cur not in self._term:
                self._goto(body_b)
            self.cur = exit_b

    def _split_for(self, s, loop_ctx):
        if not isinstance(s.iterable, RangeExpr):
            raise CoroTransformError(
                f"coroutine transform: a suspension inside a `for` over a "
                f"non-range iterable in `{self.name}` is not supported; "
                f"use a `while` loop", s.line, s.column)
        var = s.variable
        end_name = f"__end_{var}"
        lo_forgets, hi_forgets = [], []
        lo = self._rewrite_expr(s.iterable.start, lo_forgets)
        hi = self._rewrite_expr(s.iterable.end, hi_forgets)
        init = [AssignStatement(target=_self_field(var), value=lo),
                AssignStatement(target=_self_field(end_name), value=hi)]
        self._emit(init + self._forgets(lo_forgets) + self._forgets(hi_forgets))
        header = self._new_block()
        body_b = self._new_block()
        incr = self._new_block()
        exit_b = self._new_block()
        self._goto(header)
        self.cur = header
        cond = BinaryOp(op="<", left=_self_field(var),
                        right=_self_field(end_name))
        self._branch(cond, body_b, exit_b)
        self.cur = body_b
        self._lower_block(s.body, loop_ctx=(incr, exit_b))
        if self.cur not in self._term:
            self._goto(incr)
        self.cur = incr
        self._emit([AssignStatement(
            target=_self_field(var),
            value=BinaryOp(op="+", left=_self_field(var), right=_int(1)))])
        self._goto(header)
        self.cur = exit_b

    def _split_match(self, e, loop_ctx):
        forgets = []
        scrut = self._rewrite_expr(e.matched_expr, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` of the scrutinee of a "
                f"suspension-spanning `match` in `{self.name}` is not supported",
                e.line, e.column)
        merge = self._new_block()
        arm_entries = []
        new_arms = []
        for arm in e.arms:
            entry = self._new_block()
            arm_entries.append((arm, entry))
            dispatch = []
            for bname in arm.bindings:
                if bname == "_" or bname not in self.encmap:
                    continue
                # Carry the payload binding into its frame field, so the arm's
                # (separately-dispatched) entry block can read it after a suspend.
                dispatch.append(AssignStatement(
                    target=_self_field(bname), value=Identifier(name=bname)))
            dispatch.append(AssignStatement(
                target=_self_field("__state"), value=_int(entry)))
            new_arms.append(MatchArm(
                variant_name=arm.variant_name, bindings=list(arm.bindings),
                body=Block(statements=dispatch, final_expr=None)))
        self._emit([ExpressionStatement(expression=MatchExpr(
            matched_expr=scrut, arms=new_arms))])
        self._blocks[self.cur].append(ContinueStatement())
        self._term.add(self.cur)
        for arm, entry in arm_entries:
            self.cur = entry
            if isinstance(arm.body, Block):
                self._lower_block(arm.body, loop_ctx)
            else:
                self._lower_stmt(
                    ExpressionStatement(expression=arm.body), loop_ctx)
            if self.cur not in self._term:
                self._goto(merge)
        self.cur = merge

    def _emit_nested_call(self, info, loop_ctx):
        """Embed the callee frame (once) and drive it across the caller's own
        resumes: the drive block resumes the sub-frame; on Pending it propagates
        the callee's wake reason and returns Pending (staying in the drive block);
        on Done it captures the callee's result and re-dispatches past the call."""
        fbs = self._fbs
        callee_fb = fbs[info['callee']]
        sub = info['sub']
        target = info['target']
        self._emit(self._build_sub_frame(info, fbs))
        drive = self._new_block()
        self._goto(drive)
        after = self._new_block()
        done_body = []
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
            target=_self_field("__state"), value=_int(after)))
        pending_body = [
            AssignStatement(target=_self_field("__wake"),
                            value=MemberAccess(object=_self_field(sub),
                                               member="__wake")),
            ReturnStatement(value=_poll("Pending")),
        ]
        resume_call = MethodCall(object=_self_field(sub), method_name="resume",
                                 arguments=[])
        match = MatchExpr(matched_expr=resume_call, arms=[
            MatchArm(variant_name="Pending", bindings=[], body=Block(
                statements=pending_body, final_expr=None)),
            MatchArm(variant_name="Done", bindings=[], body=Block(
                statements=done_body, final_expr=None)),
        ])
        self._blocks[drive].append(ExpressionStatement(expression=match))
        self._blocks[drive].append(ContinueStatement())
        self._term.add(drive)
        self.cur = after

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

    # -------------------------------------------------- in-place lowering
    #
    # `_lower_inplace` rewrites a NON-suspending statement (or a non-spanning
    # control-flow construct) for the resume method without splitting states:
    #   * `let`/`var` of a frame-resident local -> assignment to `self.<name>`;
    #   * identifier reads -> `self.<field>`; a `move <frame local>` -> the field
    #     read plus a `__forget(self.f)` clearing the frame drop flag (Part 0a);
    #   * `return X` -> the end-of-coroutine done sequence;
    #   * nested non-spanning if/while/for/match blocks lowered in place.

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
        # design 52b item 3: `cancelled()` inside task code reads THIS frame's
        # cancel word. `self` in the resume method is the frame, so it lowers to
        # `self.__cancel` (observed cooperatively; NO forced destroy).
        if (isinstance(node, FunctionCall) and node.name == "cancelled"
                and not node.arguments):
            return _self_field("__cancel", getattr(node, 'line', 0),
                               getattr(node, 'column', 0))
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
            out.extend(self._lower_inplace(s))
        return out

    def _lower_inplace(self, s):
        # Reached only for a NON-spanning statement (the CFG walk splits every
        # suspension-spanning construct before it gets here), so a suspension in
        # this subtree would be a compiler bug — guard defensively.
        if _is_suspend_stmt(s):
            raise CoroTransformError(
                f"coroutine transform: internal error — suspension reached "
                f"in-place lowering in `{self.name}`",
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
        elif value is not None and self.is_void:
            # A void `return foo()` (foo void) still runs its side effects; there
            # is no result slot to store into.
            seq.append(ExpressionStatement(expression=value))
        seq.extend(self._forgets(forgets))
        done_lit = _int(0)  # patched to the done-state marker after CFG assembly
        self._done_lits.append(done_lit)
        seq.append(AssignStatement(target=_self_field("__state"), value=done_lit))
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
    field_inits.append(("__wake", _int(0)))
    field_inits.append(("__cancel", BoolLiteral(value=False)))
    if not fb.is_void:
        field_inits.append(("__result", _zeroed_value(fb.result_enc, fb.ret)))
    return StructInit(struct_name=fb.frame_name, field_inits=field_inits)


def _make_entry_executor(fb: _FrameBuilder, fbs):
    """Synthesize the entry executor that replaces a suspending `main` (design 45
    item 1). It builds main's frame and drives it to completion on a single
    cooperative run: each Pending consults the frame's `__wake` reason and, for a
    `sleep(ms)`, parks the thread that long (`__exec_sleep`) before resuming; a
    `yield_now` (wake 0) resumes at once. `main` may thus suspend with no
    user-visible executor.
    """
    frame_init = _build_frame_init(fb, [], fbs)
    stmts = [
        LetStatement(name="__f", type_annotation=None, value=frame_init, mutable=True),
        LetStatement(name="__done", type_annotation=None,
                     value=BoolLiteral(value=False), mutable=True),
    ]
    resume_call = MethodCall(object=Identifier(name="__f"), method_name="resume",
                             arguments=[])
    wake = MemberAccess(object=Identifier(name="__f"), member="__wake")
    pending_body = Block(statements=[ExpressionStatement(expression=IfExpr(
        condition=BinaryOp(op=">", left=wake, right=_int(0)),
        then_branch=Block(statements=[ExpressionStatement(expression=FunctionCall(
            name="__exec_sleep",
            arguments=[Argument(name=None, value=MemberAccess(
                object=Identifier(name="__f"), member="__wake"))]))],
            final_expr=None)))], final_expr=None)
    done_body = Block(statements=[AssignStatement(
        target=Identifier(name="__done"), value=BoolLiteral(value=True))],
        final_expr=None)
    loop = WhileExpr(
        condition=UnaryOp(op="not", operand=Identifier(name="__done")),
        body=Block(statements=[ExpressionStatement(expression=MatchExpr(
            matched_expr=resume_call, arms=[
                MatchArm(variant_name="Pending", bindings=[], body=pending_body),
                MatchArm(variant_name="Done", bindings=[], body=done_body),
            ]))], final_expr=None))
    stmts.append(ExpressionStatement(expression=loop))
    return Function(name="main", parameters=[], return_type=SawType(TypeKind.VOID),
                    body=Block(statements=stmts, final_expr=None),
                    source_file=getattr(fb.func, 'source_file', ""))


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
# spawn lowering (design 52b item 2)
# --------------------------------------------------------------------------- #

def _make_spawn_helper(fb: _FrameBuilder, fbs):
    """Synthesize `__spawn_<f>(__group, <params>) -> TaskHandle<T>`.

    Build f's frame from the params, erase it into a `Box<any Resumable>`, capture
    raw pointers to the boxed frame's `__result` / `__cancel` slots (stable while
    the box lives in the group's queue — the fat pointer's data word never moves),
    enqueue the box, and return the typed handle:

        func __spawn_f(__group: UnsafePointer<TaskGroup>, <params>) -> TaskHandle<T> {
            var __box = Box<any Resumable>.make(__Frame_f(<params>...))
            let __data = __box_data(&__box)
            let __fp   = __data as UnsafePointer<__Frame_f>
            let __rp   = (&__fp[0].__result) as UnsafePointer<T?>
            let __cp   = (&__fp[0].__cancel) as UnsafePointer<Bool>
            __group[0].__enqueue(move __box)
            TaskHandle<T>(result_ptr: __rp, cancel_ptr: __cp, group_ptr: __group)
        }

    The frame is a spawn root, so its `__result` is opt-encoded — `result_ptr` is
    `UnsafePointer<T?>` uniformly, and `join` takes with force-unwrap + `__forget`.
    """
    from ast_nodes import StructInit
    T = fb.ret
    params = fb.params
    frame_init = _build_frame_init(fb, [Identifier(name=p.name) for p in params], fbs)

    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    box_make = MethodCall(
        object=Identifier(name="Box", type_args=[box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=frame_init)])

    tg_ptr = SawType(TypeKind.POINTER,
                     inner_type=SawType(TypeKind.STRUCT, struct_name="TaskGroup"))
    frame_ptr = SawType(TypeKind.POINTER,
                        inner_type=SawType(TypeKind.STRUCT, struct_name=fb.frame_name))

    def _fp_field(name):
        return MemberAccess(
            object=ArrayIndex(array_expr=Identifier(name="__fp"), index=_int(0)),
            member=name)

    stmts = [
        LetStatement(name="__box", type_annotation=None, value=box_make, mutable=True),
        LetStatement(name="__data", type_annotation=None, mutable=False,
                     value=FunctionCall(name="__box_data", arguments=[Argument(
                         name=None, value=ReferenceExpr(
                             expr=Identifier(name="__box"), mutable=False))])),
        LetStatement(name="__fp", type_annotation=None, mutable=False,
                     value=CastExpr(expr=Identifier(name="__data"),
                                    target_type=frame_ptr)),
        LetStatement(name="__rp", type_annotation=None, mutable=False,
                     value=CastExpr(
                         expr=ReferenceExpr(expr=_fp_field("__result"), mutable=False),
                         target_type=SawType(TypeKind.POINTER, inner_type=_opt(T)))),
        LetStatement(name="__cp", type_annotation=None, mutable=False,
                     value=CastExpr(
                         expr=ReferenceExpr(expr=_fp_field("__cancel"), mutable=False),
                         target_type=SawType(TypeKind.POINTER,
                                             inner_type=SawType(TypeKind.BOOL)))),
        ExpressionStatement(expression=MethodCall(
            object=ArrayIndex(array_expr=Identifier(name="__group"), index=_int(0)),
            method_name="__enqueue",
            arguments=[Argument(name=None, value=MoveExpr(variable="__box", path=None))])),
    ]
    handle = StructInit(
        struct_name="TaskHandle", type_args=[T],
        field_inits=[("result_ptr", Identifier(name="__rp")),
                     ("cancel_ptr", Identifier(name="__cp")),
                     ("group_ptr", Identifier(name="__group"))])
    ret_type = SawType(TypeKind.STRUCT, struct_name="TaskHandle", type_args=[T])
    helper_params = [Parameter(name="__group", type=tg_ptr)] + \
                    [Parameter(name=p.name, type=p.type) for p in params]
    return Function(name=f"__spawn_{fb.name}", parameters=helper_params,
                    return_type=ret_type,
                    body=Block(statements=stmts, final_expr=handle),
                    source_file=getattr(fb.func, 'source_file', ""))


def _rewrite_spawn_sites(node):
    """Rewrite `group.spawn(f(args))` -> `__spawn_f((&group) as
    UnsafePointer<TaskGroup>, args...)` in place, everywhere. The site was stamped
    with `spawn_root` by the typechecker."""
    if (isinstance(node, MethodCall) and node.method_name == "spawn"
            and getattr(node, 'spawn_root', None)):
        root = node.spawn_root
        group = node.object
        inner = node.arguments[0].value  # the f(args) call
        tg_ptr = SawType(TypeKind.POINTER,
                         inner_type=SawType(TypeKind.STRUCT, struct_name="TaskGroup"))
        group_ptr = CastExpr(
            expr=ReferenceExpr(expr=group, mutable=False), target_type=tg_ptr)
        return FunctionCall(
            name=f"__spawn_{root}",
            arguments=[Argument(name=None, value=group_ptr)] + list(inner.arguments),
            line=node.line, column=node.column)
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            setattr(node, f.name, _rewrite_spawn_val(getattr(node, f.name)))
    return node


def _rewrite_spawn_val(val):
    if isinstance(val, list):
        return [_rewrite_spawn_val(v) for v in val]
    if isinstance(val, tuple):
        return tuple(_rewrite_spawn_val(v) for v in val)
    if isinstance(val, Argument):
        val.value = _rewrite_spawn_sites(val.value)
        return val
    if isinstance(val, ASTNode):
        return _rewrite_spawn_sites(val)
    return val


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
    spawn_roots = dict(getattr(typechecker, "_spawn_roots", {}) or {})
    funcs_by_name = {f.name: f for f in program.functions}
    # design 45 item 1: a suspending `main` is auto-wrapped in an entry executor.
    main_suspends = (getattr(typechecker, "_main_suspends", False)
                     and "main" in funcs_by_name)
    if not roots and not method_roots and not spawn_roots and not main_suspends:
        return False

    new_structs = []
    new_enums = []
    new_extensions = []
    new_functions = []
    removed = set()

    # The `__Poll` signal enum and the `Resumable` trait are declared in
    # builtin.saw (always in scope) — not synthesized here — so `Resumable` can
    # name `__Poll` and frames can conform to it for the erased run queue.
    nodes = getattr(typechecker, "_suspend_nodes", {})

    # The driven closure: every suspending entry-module free function reachable
    # from a driven root through suspending-call edges. Each becomes a frame +
    # resume method; a nested suspending call embeds the callee's frame by value
    # and drives it (Part 0b). Only the roots themselves also get __drive_*
    # drivers.
    closure = []
    seen = set()
    work = list(roots.keys()) + list(spawn_roots.keys())
    if main_suspends:
        work.append("main")
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
    fbs = {n: _FrameBuilder(funcs_by_name[n], tc=typechecker,
                            force_opt_result=(n in spawn_roots))
           for n in closure}
    for n in closure:
        new_structs.append(fbs[n].prepare(suspends_set))
    for n in closure:
        _, resume_ext = fbs[n].build_resume(fbs)
        new_extensions.append(resume_ext)
    for root_name, modes in roots.items():
        for mode in modes:
            new_functions.append(_make_driver(fbs[root_name], mode, fbs))
        removed.add(root_name)
    # design 52b item 2: each spawn root gets a `__spawn_<f>` helper that boxes
    # its frame, enqueues it on the group, and returns the typed handle.
    for root_name in spawn_roots:
        new_functions.append(_make_spawn_helper(fbs[root_name], fbs))
        removed.add(root_name)
    removed.update(closure)
    if main_suspends:
        # `main` keeps its name but becomes the entry executor driving its own
        # frame (not a __drive_* driver). It is in `removed` (the original body is
        # now __Frame_main.resume), so the executor is re-added under `main`.
        new_functions.append(_make_entry_executor(fbs["main"], fbs))

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
        mfb = _FrameBuilder(method_ast, struct_name=struct_name, tc=typechecker)
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

    # design 52b item 2: rewrite `group.spawn(f(args))` sites to the synthesized
    # `__spawn_<f>` helper. Done after driver rewriting so a `__drive`-inside-spawn
    # (there is none) would already be resolved; the two site kinds are disjoint.
    if spawn_roots:
        for f in program.functions:
            f.body = _rewrite_spawn_sites(f.body)
        for ext in program.extensions:
            for m in ext.methods:
                m.body = _rewrite_spawn_sites(m.body)

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

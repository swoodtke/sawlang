"""design 44 — the source-level coroutine transform.

Post-typecheck, pre-codegen AST rewrite. A function that is DRIVEN (reached from
a `__saw_drive(...)` / `__saw_drive_steps(...)` site — design 44's test-only executor
entry) is rewritten into an ordinary synthesized Saw struct (the *frame*: params
+ across-suspension locals + a state Int [+ drop-flag Bools + a result slot]) and
a `resume` method that dispatches on the state field and runs the body split at
`__saw_suspend()` boundaries. Both are then compiled by the EXISTING codegen/deinit
machinery — nothing here emits IR.

Governing rules honoured (all decided upstream, do NOT re-open):
  * Colorless: which functions suspend is effect-inferred (design 22 graph).
  * The transform is OFF by construction for non-driven code — if a program has
    no `__saw_drive` site, `transform_program` is never called (the pipeline skips
    it), so the whole existing suite takes the byte-identical path.
  * No forced destroy: there are no per-suspension-point destroy paths. Cleanup
    is normal control flow only; a frame dies by its own code reaching an exit.

Staging (this file grows across the brief's items):
  * v1 (landed): straight-line driven bodies over POD (Int/Bool/fixed-width)
    params, across-suspend locals, and result. State split at top-level
    `__saw_suspend()`; the driver loops `resume` to Done.
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
    FunctionCall, MethodCall, BinaryOp, UnaryOp, EnumInit, ForceUnwrap, IfLetExpr,
    IfExpr, MatchExpr, MatchArm, WhileExpr, ReturnStatement, ArrayIndex,
    CastExpr, ReferenceExpr, RangeExpr, ForLoop, MoveExpr,
    BreakStatement, ContinueStatement,
    ExpressionStatement, LetStatement, AssignStatement, WhileExpr,
    GuardLetStatement, TryExpr,
    Function, Struct, StructField, Enum, EnumVariant, Extension, Method,
    Parameter, SawType, TypeKind, Visibility, ClosureExpr, CaptureSpec,
    DestructuringLet, TuplePattern, BindingPattern, WildcardPattern, TupleIndex,
    EnumPattern,
)


class CoroTransformError(Exception):
    """A driven construct the v1 transform cannot yet express soundly. Surfaced
    as a compile error rather than a silent miscompile (hazard discipline).

    design 74 (A8): carries `source_file` so the surfacing site can anchor the
    diagnostic at the user's `file:line:col` (with a source-context snippet)
    instead of a bare message pointing nowhere."""
    def __init__(self, message, line=0, column=0, source_file=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.source_file = source_file


# --------------------------------------------------------------------------- #
# small AST builders
# --------------------------------------------------------------------------- #

class _FakeCall:
    """A lightweight stand-in carrying a `.name`/`.line`/`.column` for a rejected
    suspending call that is not a plain `FunctionCall` (e.g. a buried
    `ch.receive()`), so the shared diagnostic can name it uniformly."""
    def __init__(self, name, line, column):
        self.name = name
        self.line = line
        self.column = column


def _self_field(name, line=0, column=0):
    return MemberAccess(object=SelfExpr(line=line, column=column),
                        member=name, line=line, column=column)


def _int(n):
    return IntLiteral(value=n)


def _poll(variant):
    return EnumInit(enum_name="__Poll", variant_name=variant, arguments=[])


# The suspension-boundary intrinsics: `__saw_suspend` (test-only synthetic), and the
# real primitives `yield_now()` (immediately re-ready) and `sleep(ms)` (timed).
_SUSPEND_CALLS = ("__saw_suspend", "yield_now", "sleep", "__saw_io_park", "io_wait")

# design 76 (A4): the IO-park wake reason. A negative sentinel distinct from the
# `sleep(ms)` (>0) and yield/channel-retry (0) reasons: the executor parks in the
# reactor (kqueue/epoll) rather than sleeping or busy-requeuing.
IO_PARK_WAKE = -1


def _suspend_call_name(stmt):
    if (isinstance(stmt, ExpressionStatement)
            and isinstance(stmt.expression, FunctionCall)
            and stmt.expression.name in _SUSPEND_CALLS):
        return stmt.expression.name
    return None


def _is_suspend_stmt(stmt):
    """True for a bare suspension-point statement — a state boundary. Covers the
    synthetic `__saw_suspend()` and the real `yield_now()`/`sleep(ms)` primitives."""
    return _suspend_call_name(stmt) is not None


def _wake_expr(stmt):
    """The wake reason a suspension carries, stored in the frame's `__wake` field
    and read by the executor after a Pending: milliseconds for `sleep(ms)`, else
    0 (`__saw_suspend`/`yield_now` — immediately re-ready)."""
    fc = stmt.expression
    if fc.name == "sleep":
        return fc.arguments[0].value
    if fc.name == "__saw_io_park":
        return _int(IO_PARK_WAKE)
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


def _clear_escaping(t):
    """Return a copy of `t` normalized for use as a coroutine frame field type
    (design 77 item 4): `func_is_escaping` cleared and `func_is_sync` forced on
    every function type it contains.

    - escaping: a closure-typed frame field carries the ORIGINAL local's
      already-stamped escaping bit. The synthesized frame struct is re-registered
      through the normal front half, which re-stamps struct fields as escaping and
      reports "redundant `escaping`" when the marker is already present. Clearing
      the bit lets re-stamping set it cleanly (a frame field is a non-parameter,
      always-escaping position).
    - sync: a stored closure cannot itself be driven/suspend in this model
      (`yield_now` inside an un-driven closure body is a codegen no-op), so an
      indirect call to a frame closure field is sync-safe. Forcing the field type
      `sync` keeps the synthesized `sync resume` from tripping the effect
      checker's "call through a non-`sync` function value" rule.

    Fresh SawType, no shared mutation.
    """
    if t is None or not _contains_function(t):
        return t
    if t.kind == TypeKind.FUNCTION:
        return SawType(TypeKind.FUNCTION,
                       param_types=[_clear_escaping(p) for p in (t.param_types or [])],
                       func_return_type=_clear_escaping(t.func_return_type),
                       func_is_sync=True,
                       func_is_escaping=False)
    if t.kind == TypeKind.OPTIONAL and t.inner_type is not None:
        return SawType(TypeKind.OPTIONAL, inner_type=_clear_escaping(t.inner_type))
    if t.kind == TypeKind.ARRAY and t.array_element_type is not None:
        return SawType(TypeKind.ARRAY,
                       array_element_type=_clear_escaping(t.array_element_type),
                       array_size=t.array_size)
    if t.kind == TypeKind.TUPLE and t.element_types:
        return SawType(TypeKind.TUPLE,
                       element_types=[_clear_escaping(e) for e in t.element_types])
    return t


def _contains_function(t):
    """Whether `t` contains a function type (directly or nested in an
    Optional/array/tuple). Used to leave non-closure frame field types untouched."""
    if t is None:
        return False
    if t.kind == TypeKind.FUNCTION:
        return True
    if t.kind == TypeKind.OPTIONAL:
        return _contains_function(t.inner_type)
    if t.kind == TypeKind.ARRAY:
        return _contains_function(t.array_element_type)
    if t.kind == TypeKind.TUPLE:
        return any(_contains_function(e) for e in (t.element_types or []))
    return False


# Frame-field encodings (design 44 + 62):
#   "plain"    — POD field; field type == declared type; read `self.name`; zero-init.
#   "opt"      — cleanup-needing non-optional type `T`, encoded as `T?`; the
#                None/Some tag IS the drop flag; read `self.name!`; init None.
#   "self_opt" — a declared type that is ALREADY optional (`T?`); encoded as-is
#                (NOT `(T?)?` — that double-wrap miscompiles stores/reads). Its own
#                tag is the drop flag; read `self.name` (no unwrap); init None.
def _is_taskgroup(saw_type):
    return (saw_type is not None and saw_type.kind == TypeKind.STRUCT
            and saw_type.struct_name == "TaskGroup")


def _enc_of(saw_type):
    if _is_pod(saw_type):
        return "plain"
    # design 88 (D6): a reference-typed PARAM or LOCAL (`&T` / `&var T`) held
    # across a suspension becomes a frame-resident RAW POINTER into the referent's
    # storage — the exact `__recv` mechanism (design 45 0c) generalized from the
    # method receiver to any reference. The field is `UnsafePointer<T>`, a read of
    # the reference name is rewritten to a pointer deref `self.name[0]` (an lvalue
    # of the pointee type, so member access / mutation / method calls all work),
    # and the pointer never owns — no drop flag, exempt from cleanup. Sound only
    # for DRIVEN-in-place frames (referent outlives the drive); a SPAWNED frame
    # keeps rejecting references (confinement — the referent could be a dead
    # spawner-stack slot), enforced at the spawn lowering site.
    if saw_type is not None and saw_type.kind == TypeKind.REFERENCE:
        return "ref"
    # design 77 item 4: a closure frame field. Cleanup-needing like "opt" (the
    # None/Some tag is the drop flag; the env is released exactly once at frame
    # death), but a CALL to it (`f(args)`) is rewritten to an indirect field
    # call on `self.f!`, and a bare read to `self.f!` — the extra encoding tag
    # tells `_rewrite_expr` to do the call rewrite.
    if saw_type is not None and saw_type.kind == TypeKind.FUNCTION:
        return "opt_closure"
    if saw_type is not None and saw_type.kind == TypeKind.OPTIONAL:
        return "self_opt"
    # design 62 G1: a frame-resident `TaskGroup` is "plain"-encoded so `&group`
    # (needed by `group.spawn(...)`'s synthesized `&group` receiver, and by
    # `TaskHandle`'s raw pointer into the group) resolves to an ADDRESSABLE frame
    # field `self.group` — an opt-encoded `self.group!` is not addressable. Its
    # placeholder is a real empty `TaskGroup()` (always-valid: its Deinit drains 0
    # children), so a teardown before the user's `let group = TaskGroup()` runs is
    # still sound, and the user's assignment drops the empty placeholder cleanly.
    if _is_taskgroup(saw_type):
        return "plain"
    return "opt"


def _ref_ptr_type(ref_type):
    """The `UnsafePointer<T>` frame-field type for a reference `&T` / `&var T`
    (design 88). Pointer mutability mirrors the reference: a `&var T` frame field
    permits mutation through the deref; a `&T` field is read-only."""
    return SawType(TypeKind.POINTER, inner_type=ref_type.inner_type,
                   pointer_mutable=bool(ref_type.reference_mutable))


def _field_type(saw_type, enc):
    if enc == "ref":
        return _ref_ptr_type(saw_type)
    return _opt(saw_type) if enc in ("opt", "opt_closure") else saw_type


def _enc_unwraps(enc):
    return enc in ("opt", "opt_closure")


def _enc_cleanup(enc):
    """True for an encoding whose field carries a drop flag (None/Some): a move
    out must `__saw_forget` it, and its initial (not-yet-live) value is `None`."""
    return enc in ("opt", "self_opt", "opt_closure")


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
    if encoding in ("opt", "opt_closure"):
        return ForceUnwrap(expr=acc, line=line, column=column)
    if encoding == "ref":
        # design 88 (D6): the reference name reads through the frame's pointer
        # field — `self.name[0]` — yielding an lvalue of the pointee type. Member
        # access, compound-assignment mutation, and method calls on it all flow
        # normally (the identical `self.__recv[0]` receiver rewrite of design 45 0c).
        return ArrayIndex(array_expr=acc, index=_int(0), line=line, column=column)
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

def _method_frame_key(struct_name, method_name, resolved_symbol=None):
    """Canonical frame key for a driven/embedded suspending METHOD (design 95).

    THE one spot that decides a driven-method frame's identity. Two OVERLOADS of
    the same method name must get DISTINCT frames, so an overloaded suspending
    method is keyed by its design-55 resolved signature — the overload-mangled
    symbol (`Struct_write$OL$String`, carrying the `$OL$`/`$LB$` suffix) already
    composed by the typechecker: `mangled_symbol` on the method AST (definition
    side), `resolved_symbol` on the MethodCall (call site). A NON-overloaded
    method has no resolved symbol and keeps the plain `{struct}_{method}` key, so
    the common case (one signature per name) is byte-for-byte unchanged.
    """
    return resolved_symbol or f"{struct_name}_{method_name}"


class _FrameBuilder:
    def __init__(self, func, struct_name=None, tc=None, force_opt_result=False,
                 recv_saw_type=None):
        # design 52b item 2: a spawn-root frame forces its `__result` opt-encoded
        # even for a POD return, so `TaskHandle<T>` uniformly holds a
        # `UnsafePointer<T?>` and `join` takes the value with the same
        # force-unwrap + `__saw_forget` handoff regardless of T.
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
        # design 74 (A8): the user file this frame's function came from, so every
        # rejection this builder raises anchors at the user's source.
        self.src_file = getattr(func, 'source_file', None)
        self.is_method = struct_name is not None
        self.struct_name = struct_name
        if self.is_method:
            # design 95: an overloaded suspending method's frame is keyed by its
            # resolved signature (the `mangled_symbol` the typechecker stamped on
            # the method AST), so two `write` overloads get distinct frames; a
            # non-overloaded method keeps the plain `{struct}_{method}` name.
            self.name = _method_frame_key(
                struct_name, func.name, getattr(func, 'mangled_symbol', None))
            # design 74 (A5-rest, shape 2): a method on a GENERIC struct is driven
            # for a concrete receiver (`Holder<Int>`) — `recv_saw_type` carries the
            # instantiation so `__recv` points at the monomorphized struct codegen
            # produces. A plain method's receiver has no type args.
            pointee = recv_saw_type if recv_saw_type is not None else \
                SawType(TypeKind.STRUCT, struct_name=struct_name)
            self.recv_type = SawType(TypeKind.POINTER, inner_type=pointee)
        else:
            self.name = func.name
        self.frame_name = f"__Frame_{self.name}"
        self.ret = func.return_type or SawType(TypeKind.VOID)
        self.is_void = (self.ret.kind == TypeKind.VOID)

    # ------------------------------------------------------------------ #
    # design 62 G2: if-let / guard-let condition hoisting
    # ------------------------------------------------------------------ #
    def _hoist_suspending_conditions(self):
        """Rewrite every `if let x = f() { ... }` / `guard let x = f() else { ... }`
        whose condition is a PLAIN suspending free-function call into a preceding
        `let __hoistN = f()` (the already-supported nested-suspending-call-in-let)
        plus the binding over the temp. ONLY the plain-call form is hoisted — a
        `move` or other rejected condition shape is left untouched (do not
        accidentally legalize what design 52 Part 0 rejects)."""
        self._hoist_ctr = 0
        self._hoist_block(self.func.body)

    def _hoist_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._maybe_hoist(s))
        block.statements = new_stmts
        for s in block.statements:
            self._hoist_recurse(s)

    def _hoist_recurse(self, s):
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr):
            self._hoist_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_block(ctrl.else_branch)
        elif isinstance(ctrl, IfLetExpr):
            self._hoist_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_block(ctrl.else_branch)
        elif isinstance(ctrl, WhileExpr):
            self._hoist_block(ctrl.body)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._hoist_block(arm.body)
        elif isinstance(s, ForLoop):
            self._hoist_block(s.body)
        elif isinstance(s, GuardLetStatement):
            self._hoist_block(s.else_branch)

    def _maybe_hoist(self, s):
        """Return the replacement statement list for `s` (either `[s]` unchanged or
        `[let __hoistN = f(), s']` with `s'`'s condition rebound to the temp)."""
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        cond = None
        if isinstance(ctrl, IfLetExpr):
            cond = ctrl.optional_expr
        elif isinstance(s, GuardLetStatement):
            cond = s.optional_expr
        if cond is None:
            return [s]
        hoisted = self._hoist_cond(cond)
        if hoisted is None:
            return [s]
        let_stmt, ident = hoisted
        if isinstance(ctrl, IfLetExpr):
            ctrl.optional_expr = ident
        else:
            s.optional_expr = ident
        return [let_stmt, s]

    def _hoist_cond(self, cond):
        # Only the plain suspending free-function call form is hoistable.
        if (isinstance(cond, FunctionCall) and cond.name in self._suspends
                and not getattr(cond, 'type_args', None)):
            tmp = f"__hoist{self._hoist_ctr}"
            self._hoist_ctr += 1
            let_stmt = LetStatement(name=tmp, type_annotation=None, value=cond,
                                    mutable=False, line=cond.line, column=cond.column)
            ident = Identifier(name=tmp, line=cond.line, column=cond.column)
            # Carry the optional type so downstream typing of the temp field is
            # exact (its value's `resolved_type` is the callee's `T?`).
            ident.resolved_type = getattr(cond, 'resolved_type', None)
            return (let_stmt, ident)
        return None

    def _hoist_suspending_try(self):
        """design 92: rewrite `let x = try! recv.m(args)` (and `try`/`try?`, bare,
        or `return`-position) whose tried expression is a SUSPENDING call into a
        preceding driven temp plus a try over that temp:

            let __trycallN = recv.m(args)     # a plain nested-suspending call-in-let
            let x = try! __trycallN           # a try over an ordinary Result local

        Without this the tried call hides INSIDE a `TryExpr`, so `_classify_call`
        never sees a bare `MethodCall`/`FunctionCall` to embed+drive — the callee's
        internal `io_wait` park then fails to integrate with the executor (a
        parked read never yields to a runnable peer -> hang). The desugared shape
        is exactly the already-supported `let res = recv.m(); <use res>`."""
        self._try_ctr = 0
        self._hoist_try_block(self.func.body)

    def _hoist_try_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._maybe_hoist_try(s))
        block.statements = new_stmts
        for s in block.statements:
            self._hoist_try_recurse(s)

    def _hoist_try_recurse(self, s):
        """Descend into control-flow bodies with the TRY hoister (mirrors
        `_hoist_recurse`, which drives the condition hoister)."""
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr):
            self._hoist_try_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_try_block(ctrl.else_branch)
        elif isinstance(ctrl, IfLetExpr):
            self._hoist_try_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_try_block(ctrl.else_branch)
        elif isinstance(ctrl, WhileExpr):
            self._hoist_try_block(ctrl.body)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._hoist_try_block(arm.body)
        elif isinstance(s, ForLoop):
            self._hoist_try_block(s.body)
        elif isinstance(s, GuardLetStatement):
            self._hoist_try_block(s.else_branch)

    def _call_suspends_expr(self, e):
        """True if `e` is a suspending call — a free function in `_suspends` or a
        suspending method on a concrete struct receiver."""
        if isinstance(e, FunctionCall):
            return e.name in self._suspends and not getattr(e, 'type_args', None)
        if isinstance(e, MethodCall):
            return self._method_call_suspends(e)
        return False

    def _maybe_hoist_try(self, s):
        tnode = None
        if isinstance(s, LetStatement) and isinstance(s.value, TryExpr):
            tnode = s.value
        elif (isinstance(s, ExpressionStatement)
              and isinstance(s.expression, TryExpr)):
            tnode = s.expression
        elif isinstance(s, ReturnStatement) and isinstance(s.value, TryExpr):
            tnode = s.value
        if tnode is None or not self._call_suspends_expr(tnode.expr):
            return [s]
        inner = tnode.expr
        tmp = f"__trycall{self._try_ctr}"
        self._try_ctr += 1
        let_stmt = LetStatement(name=tmp, type_annotation=None, value=inner,
                                mutable=False, line=inner.line, column=inner.column)
        # The try now CONSUMES the temp via `move`: the tried Result owns its
        # payload (e.g. a NoCopy `TcpStream`/`Data` in the Ok), and try!/try/try?
        # transfer that payload OUT — so the temp must be forgotten, not dropped
        # again at scope/frame teardown (a double-close/double-free). `move`
        # reuses the existing move + drop-flag/__saw_forget machinery on both the
        # direct and coroutine-frame paths, instead of a try-specific special case.
        mv = MoveExpr(variable=tmp, line=inner.line, column=inner.column)
        # Carry the callee's Result type so the driven-call classification and the
        # try lowering both see the exact instantiation.
        mv.resolved_type = getattr(inner, 'resolved_type', None)
        tnode.expr = mv
        return [let_stmt, s]

    def _hoist_suspending_match(self):
        """design 96: rewrite a `match <suspending call> { ... }` whose SCRUTINEE
        is a suspending free-function or method call into a preceding driven temp:

            let __matchN = recv.m(args)   # ordinary nested-suspending-call-in-let
            match __matchN { ... }

        Mirrors the if-let/guard-let condition hoist and the try hoist. The temp
        is the already-supported `let res = recv.m(); match res {...}` shape (which
        the CFG walk drives), so the callee's internal park integrates with the
        executor instead of blocking the thread. Handles the bare-statement,
        `let x = match ...`, and `return match ...` positions, descending into
        control-flow bodies (incl. match arms)."""
        self._match_ctr = 0
        self._hoist_match_block(self.func.body)

    def _hoist_match_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._maybe_hoist_match(s))
        block.statements = new_stmts
        for s in block.statements:
            self._hoist_match_recurse(s)

    def _hoist_match_recurse(self, s):
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr):
            self._hoist_match_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_match_block(ctrl.else_branch)
        elif isinstance(ctrl, IfLetExpr):
            self._hoist_match_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._hoist_match_block(ctrl.else_branch)
        elif isinstance(ctrl, WhileExpr):
            self._hoist_match_block(ctrl.body)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._hoist_match_block(arm.body)
        elif isinstance(s, ForLoop):
            self._hoist_match_block(s.body)
        elif isinstance(s, GuardLetStatement):
            self._hoist_match_block(s.else_branch)

    def _maybe_hoist_match(self, s):
        m = None
        if isinstance(s, ExpressionStatement) and isinstance(s.expression, MatchExpr):
            m = s.expression
        elif isinstance(s, LetStatement) and isinstance(s.value, MatchExpr):
            m = s.value
        elif isinstance(s, ReturnStatement) and isinstance(s.value, MatchExpr):
            m = s.value
        if m is None or not self._call_suspends_expr(m.matched_expr):
            return [s]
        inner = m.matched_expr
        tmp = f"__match{self._match_ctr}"
        self._match_ctr += 1
        let_stmt = LetStatement(name=tmp, type_annotation=None, value=inner,
                                mutable=False, line=inner.line, column=inner.column)
        ident = Identifier(name=tmp, line=inner.line, column=inner.column)
        # Carry the callee's result type so the driven-call classification and the
        # match lowering both see the exact instantiation.
        ident.resolved_type = getattr(inner, 'resolved_type', None)
        m.matched_expr = ident
        return [let_stmt, s]

    # ------------------------------------------------------------------ #
    # design 104 item 1: CFG-split `if let`/`guard let` bodies that suspend
    # ------------------------------------------------------------------ #
    def _mark_optional_binding_splits(self):
        """Find every `if let`/`guard let` whose body spans a suspension and mark
        it `_coro_split` (so `_collect_frame_locals`, `_collect_calls`, and the CFG
        walk all treat it as a split point), renaming its binding to a fresh unique
        frame field. An `if let` splits when either branch spans; a `guard let`
        splits when its ENCLOSING block spans (the binding lives on into the rest of
        that block, which is what may cross the suspension)."""
        self._optbind_ctr = 0
        self._mark_ob_block(self.func.body)

    def _mark_ob_block(self, block):
        block_spans = self._spans_suspension(block)
        for s in block.statements:
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfLetExpr):
                then_spans = self._spans_suspension(ctrl.then_branch)
                else_spans = (ctrl.else_branch is not None
                              and self._spans_suspension(ctrl.else_branch))
                if then_spans or else_spans:
                    self._prep_ob_split(ctrl, ctrl.then_branch, [], None)
                self._mark_ob_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    self._mark_ob_block(ctrl.else_branch)
            elif isinstance(s, GuardLetStatement):
                if block_spans:
                    # The binding's scope is the REST of the enclosing block after
                    # this guard (statements + the block's trailing expression).
                    # Index by identity — dataclass `==` could match an earlier
                    # structurally-equal statement.
                    idx = next(i for i, st in enumerate(block.statements)
                               if st is s)
                    self._prep_ob_split(
                        s, None, block.statements[idx + 1:], block)
                self._mark_ob_block(s.else_branch)
            elif isinstance(ctrl, IfExpr):
                self._mark_ob_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    self._mark_ob_block(ctrl.else_branch)
            elif isinstance(ctrl, WhileExpr):
                self._mark_ob_block(ctrl.body)
            elif isinstance(ctrl, MatchExpr):
                for arm in ctrl.arms:
                    if isinstance(arm.body, Block):
                        self._mark_ob_block(arm.body)
            elif isinstance(s, ForLoop):
                self._mark_ob_block(s.body)

    def _prep_ob_split(self, node, scope_block, scope_stmts, scope_final_owner):
        """Mark `node` for CFG-splitting and rename its binding to a fresh unique
        name, rewriting the binding's uses in its scope (`scope_block` for an
        `if let` then-branch, or `scope_stmts` + the owner block's `final_expr` for
        a `guard let` continuation). A tuple-pattern binding across a suspension is
        not supported (rejected cleanly). A nested re-binding of the same name in
        the scope (a design-100 derived shadow) is likewise unsupported here and
        rejected, so no use is ever mis-renamed."""
        if getattr(node, 'pattern', None) is not None:
            kind = "if let" if isinstance(node, IfLetExpr) else "guard let"
            raise CoroTransformError(
                f"coroutine transform: a tuple-pattern `{kind}` whose body spans a "
                f"suspension in `{self.name}` is not supported; bind a single name "
                f"and destructure inside the body",
                node.line, node.column, source_file=self.src_file)
        old = node.name
        new = f"__ob{self._optbind_ctr}"
        self._optbind_ctr += 1
        scopes = []
        if scope_block is not None:
            scopes.append(scope_block)
        scopes.extend(scope_stmts)
        for sc in scopes:
            self._rename_binding_use(sc, old, new)
        if scope_final_owner is not None and scope_final_owner.final_expr is not None:
            self._rename_binding_use(scope_final_owner.final_expr, old, new)
        node.name = new
        node._coro_split = True

    def _rename_binding_use(self, node, old, new):
        """Rewrite every use of the identifier `old` to `new` in `node`'s subtree.
        Raises cleanly if the subtree RE-BINDS `old` (a nested let/var, pattern,
        loop var, closure param, or optional binding) — that scope shadow would make
        a blanket rename unsound, and design-100 makes it rare; a clean error beats a
        miscompile (the design-101 standing bar)."""
        def rebinds(n):
            if isinstance(n, LetStatement) and n.name == old:
                return True
            if isinstance(n, (IfLetExpr, GuardLetStatement)) and n.name == old:
                return True
            if isinstance(n, ForLoop) and n.variable == old:
                return True
            if isinstance(n, DestructuringLet):
                return old in self._pattern_binding_names(n.pattern)
            if isinstance(n, MatchArm):
                return (old in n.bindings
                        or old in self._pattern_binding_names(n.pattern))
            if isinstance(n, ClosureExpr):
                return any(p.name == old for p in getattr(n, 'parameters', []))
            return False

        def walk(n):
            if isinstance(n, Identifier) and n.name == old:
                n.name = new
                return
            if isinstance(n, MoveExpr) and n.variable == old:
                # Renames a bare `move old` AND a path-qualified `move old.field`;
                # fall through so any expressions in `path` are still walked.
                n.variable = new
            if isinstance(n, ASTNode):
                if rebinds(n):
                    raise CoroTransformError(
                        f"coroutine transform: re-binding `{old}` inside a "
                        f"suspension-spanning `if let`/`guard let` body in "
                        f"`{self.name}` is not supported; rename the inner binding",
                        getattr(n, 'line', 0) or 0, 0, source_file=self.src_file)
                for f in dataclasses.fields(n):
                    v = getattr(n, f.name)
                    if isinstance(v, list):
                        for x in v:
                            if isinstance(x, Argument):
                                walk(x.value)
                            elif isinstance(x, ASTNode):
                                walk(x)
                    elif isinstance(v, Argument):
                        walk(v.value)
                    elif isinstance(v, ASTNode):
                        walk(v)

        walk(node)

    def _optional_binding_type(self, node):
        """The inner type `T` of an `if let`/`guard let` binding over a `T?`
        scrutinee — the type of the frame field carrying it across a suspension."""
        ot = getattr(node.optional_expr, 'resolved_type', None)
        if ot is not None and ot.kind == TypeKind.OPTIONAL and ot.inner_type is not None:
            return ot.inner_type
        return None

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
            if isinstance(s, DestructuringLet):
                # `let (a, b) = expr` across a suspension (design 77 item 10):
                # each destructured binding is frame-resident. Its type comes from
                # the matching position of the source tuple's resolved type.
                if scope_spans:
                    src_t = getattr(s.value, 'resolved_type', None)
                    for name, bt in self._destructure_leaf_types(s.pattern, src_t):
                        add(name, bt, s.line, s.column)
                return
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                walk_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    walk_block(ctrl.else_branch)
            elif isinstance(ctrl, IfLetExpr):
                # design 104 item 1: a split `if let` binding survives the
                # dispatch→then-branch state transition, so it is frame-resident.
                if getattr(ctrl, '_coro_split', False):
                    add(ctrl.name, self._optional_binding_type(ctrl),
                        ctrl.line, ctrl.column)
                walk_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    walk_block(ctrl.else_branch)
            elif isinstance(s, GuardLetStatement):
                # design 104 item 1: a split `guard let` binding lives on into the
                # rest of the enclosing block (which crosses the suspension).
                if getattr(s, '_coro_split', False):
                    add(s.name, self._optional_binding_type(s), s.line, s.column)
                walk_block(s.else_branch)
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

    def _destructure_leaf_types(self, pattern, src_type):
        """Yield (binding_name, type) for each BindingPattern leaf of an
        irrefutable tuple pattern, pairing it with the matching position of the
        source tuple's type (design 77 item 10). Wildcards bind nothing.
        Positions with no known type (src_type missing/short) raise, mirroring
        the untyped-local guard."""
        out = []

        def walk(pat, t):
            if isinstance(pat, WildcardPattern):
                return
            if isinstance(pat, BindingPattern):
                if t is None:
                    raise CoroTransformError(
                        f"coroutine transform: destructured binding `{pat.name}` in "
                        f"driven `{self.name}` has no resolved type",
                        getattr(pat, 'line', self.func.line), 0)
                out.append((pat.name, t))
                return
            if isinstance(pat, TuplePattern):
                elems = t.element_types if (t is not None and t.kind == TypeKind.TUPLE
                                            and t.element_types) else None
                for i, sub in enumerate(pat.elements):
                    walk(sub, elems[i] if (elems is not None and i < len(elems)) else None)
                return
            raise CoroTransformError(
                f"coroutine transform: unsupported destructuring pattern in driven "
                f"`{self.name}` across a suspension", self.func.line, 0)

        walk(pattern, src_type)
        return out

    def _pattern_binding_names(self, pattern):
        """Every binding name introduced by a design-63 `MatchArm.pattern` — a bare
        `case n` (BindingPattern), a tuple pattern's leaves, or a nested enum
        pattern's subpatterns. Literal/range/wildcard patterns bind nothing.
        Used so a suspension-spanning `match` carries these bindings into frame
        fields exactly like the classic enum `arm.bindings` (design 101)."""
        if pattern is None:
            return []
        out = []

        def walk(pat):
            if isinstance(pat, BindingPattern):
                out.append(pat.name)
            elif isinstance(pat, TuplePattern):
                for sub in pat.elements:
                    walk(sub)
            elif isinstance(pat, EnumPattern):
                for sub in pat.subpatterns:
                    walk(sub)

        walk(pattern)
        return out

    def _destructure_assigns(self, pattern, base_expr, out, line, col):
        """Append `self.<leaf> = <base>.<i>...` assignments for each binding leaf
        of a tuple pattern (design 77 item 10). `base_expr` indexes into the
        source temp; nested tuple patterns recurse through `TupleIndex`."""
        if isinstance(pattern, TuplePattern):
            for i, sub in enumerate(pattern.elements):
                idx = TupleIndex(tuple_expr=base_expr, index=i, line=line, column=col)
                self._destructure_assigns(sub, idx, out, line, col)
            return
        if isinstance(pattern, BindingPattern):
            out.append(AssignStatement(
                target=_self_field(pattern.name, line, col),
                value=base_expr, line=line, column=col))
            return
        # WildcardPattern: bind nothing (the component is dropped; POD tuples in
        # v1 need no explicit drop).

    # ------------------------------------------------------------------ #
    # suspension analysis over the body (CFG split decisions, design 52)
    # ------------------------------------------------------------------ #
    def _spans_suspension(self, node):
        """True if `node` (a Block/Statement/Expression subtree) transitively
        contains a suspension point: a suspend primitive (`__saw_suspend`/`yield_now`/
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
            # design 103 (A6): a blocking-extern call is a suspension point (the
            # offload parks the task on the job's pipe), so a block containing one
            # spans a suspension — its locals become frame-resident and a
            # control-flow construct around it is CFG-split.
            if isinstance(n, FunctionCall) and self._is_blocking_extern(n.name):
                found[0] = True
                return
            # design 62 G3: a cooperative `ch.receive()` is a suspension point
            # (it lowers to a try_receive+yield_now loop), so a control-flow
            # construct containing one must be CFG-split.
            if isinstance(n, MethodCall) and getattr(n, 'is_chan_recv', False):
                found[0] = True
                return
            # design 84: a nested suspending METHOD call is a suspension point (its
            # frame is embedded + driven), so a control-flow construct containing one
            # must be CFG-split into states — otherwise it lowers in place and the
            # stripped method body is missing at codegen.
            if isinstance(n, MethodCall) and self._method_call_suspends(n):
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

    def _has_loop_ctrl(self, node):
        """design 96 (DF6): True if `node` contains a `break`/`continue` that
        targets the ENCLOSING loop — one NOT nested inside a deeper `while`/`for`
        within `node` (which would capture it). Such a construct, even when it does
        NOT itself span a suspension, must be CFG-SPLIT when it sits in a
        suspension-spanning loop: lowered in place it would keep a raw `break`/
        `continue`, which escapes the resume method's `while true` DISPATCH loop
        instead of the logical loop (a driven `while {} { ... if c { break } }`
        re-entered in a caller's loop then hangs). Splitting routes the jump to the
        loop's exit/header STATE via `loop_ctx`."""
        found = [False]

        def scan(n):
            if found[0]:
                return
            if isinstance(n, (BreakStatement, ContinueStatement)):
                found[0] = True
                return
            # A nested loop captures its own break/continue — do not descend.
            if isinstance(n, (WhileExpr, ForLoop)):
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

    def _normalize_suspending_tails(self):
        """design 83: normalize suspension-spanning trailing expressions.

        The parser lifts a block's last bare expression into `final_expr`. When
        that expression contains a suspension point (a `yield_now`/`sleep` or a
        call to a suspending function), it must go through the CFG walk — but the
        nested-call scan and lowering both key on STATEMENTS. Rewrite such a tail
        into a statement: one whose value is the function result becomes
        `return <expr>` (recursing through a tail `if`/`match` so every leaf
        returns); a discarded tail (loop body, mid-body block) becomes a bare
        expression statement. A non-suspending tail is left as `final_expr` for
        the existing `_rewrite_expr`/`_done` (function tail) or `_lower_block`
        discard (nested) fast path."""
        self._norm_block(self.func.body, tail=True)

    def _norm_block(self, block, tail, force=False):
        # Recurse into suspension-spanning control flow that appears as a
        # STATEMENT (its value is discarded → its inner blocks are non-tail).
        for s in block.statements:
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, (IfExpr, WhileExpr, MatchExpr, ForLoop)) \
                    and self._spans_suspension(ctrl):
                self._norm_ctrl(ctrl, tail=False)
        fe = block.final_expr
        if fe is None:
            return
        spanning = self._spans_suspension(fe)
        if tail:
            # `force` propagates result-flow into EVERY branch of a spanning tail
            # `if`/`match` — a non-spanning sibling branch (`else { 0 }`) must
            # still `return` its value, else `_lower_block` would discard it.
            if not spanning and not force:
                return
            if isinstance(fe, IfExpr) and fe.else_branch is not None:
                block.final_expr = None
                self._norm_block(fe.then_branch, tail=True, force=True)
                self._norm_block(fe.else_branch, tail=True, force=True)
                block.statements.append(ExpressionStatement(expression=fe))
            elif isinstance(fe, MatchExpr) and all(
                    isinstance(a.body, Block) for a in fe.arms):
                block.final_expr = None
                for arm in fe.arms:
                    self._norm_block(arm.body, tail=True, force=True)
                block.statements.append(ExpressionStatement(expression=fe))
            else:
                block.final_expr = None
                block.statements.append(ReturnStatement(
                    value=fe, line=getattr(fe, 'line', block.line),
                    column=getattr(fe, 'column', block.column)))
        else:
            if not spanning:
                return
            block.final_expr = None
            block.statements.append(ExpressionStatement(expression=fe))
            if isinstance(fe, (IfExpr, WhileExpr, MatchExpr, ForLoop)):
                self._norm_ctrl(fe, tail=False)

    def _norm_ctrl(self, node, tail):
        """Recurse into a control-flow expression's constituent blocks."""
        if isinstance(node, IfExpr):
            self._norm_block(node.then_branch, tail)
            if node.else_branch is not None:
                self._norm_block(node.else_branch, tail)
        elif isinstance(node, WhileExpr):
            self._norm_block(node.body, tail=False)
        elif isinstance(node, ForLoop):
            self._norm_block(node.body, tail=False)
        elif isinstance(node, MatchExpr):
            for arm in node.arms:
                if isinstance(arm.body, Block):
                    self._norm_block(arm.body, tail)

    def _collect_calls(self):
        """Walk the whole body for nested suspending call sites (top-level OR
        inside control-flow bodies). Each embeds a callee frame by value; `sub`
        names its field. Keyed by statement identity so the CFG walk can recover a
        call's sub-frame field. A suspending call buried in an expression position
        (not a bare `let x = g(...)` / `g(...)` statement) is rejected honestly."""
        self.calls = []
        self.call_by_id = {}
        # design 62 G3: cooperative `ch.receive()` call sites lowered INLINE (no
        # callee frame — the try_receive+yield_now loop runs against THIS frame).
        self.recv_calls = []
        self.recv_by_id = {}
        # design 103 (A6): blocking-extern call sites lowered to the offload
        # start -> io_wait(pipe fd) -> take sequence (no callee frame — the loop
        # runs against THIS frame, like a cooperative `receive()`).
        self.blk_calls = []
        self.blk_by_id = {}

        def visit_block(block):
            for s in block.statements:
                visit_stmt(s)

        def visit_stmt(s):
            rinfo = self._classify_recv(s)
            if rinfo is not None:
                rinfo['idx'] = len(self.recv_calls)
                self.recv_calls.append(rinfo)
                self.recv_by_id[id(s)] = rinfo
                return
            binfo = self._classify_blk(s)
            if binfo is not None:
                binfo['idx'] = len(self.blk_calls)
                self.blk_calls.append(binfo)
                self.blk_by_id[id(s)] = binfo
                return
            info = self._classify_call(s)
            if info is not None:
                info['sub'] = f"__sub{len(self.calls)}"
                self.calls.append(info)
                self.call_by_id[id(s)] = info
                return
            # design 74 (A5-rest, shape 1): a buried suspending METHOD call in a
            # driven body — reject cleanly (anchored, naming the workaround) rather
            # than lower it in place and trip a confusing sync-violation later.
            self._reject_suspending_method_call(s)
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                visit_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    visit_block(ctrl.else_branch)
            elif isinstance(ctrl, IfLetExpr) and getattr(ctrl, '_coro_split', False):
                # design 104 item 1: a split `if let` body is CFG-split — recurse so
                # nested suspending calls in the branches are embedded (not rejected).
                visit_block(ctrl.then_branch)
                if ctrl.else_branch is not None:
                    visit_block(ctrl.else_branch)
            elif isinstance(s, GuardLetStatement) and getattr(s, '_coro_split', False):
                # design 104 item 1: recurse into the split `guard let` else-branch;
                # the guard's continuation is visited by the enclosing block loop.
                visit_block(s.else_branch)
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
        # design 83: lift a suspension-spanning TRAILING expression (a block's
        # `final_expr`, where the parser parks the last bare expression) into an
        # explicit statement, so the nested-call scan and CFG walk both see it. A
        # value flowing to the function result becomes `return <expr>` (recursing
        # through a tail `if`/`match` so each leaf returns); a discarded tail (a
        # loop body, a mid-body block) becomes a bare expression statement.
        # Non-suspending tails keep the existing `final_expr` fast path untouched.
        #
        # design 101 (DF7): this MUST run FIRST — before the three wrapper hoists
        # below — because they each walk only `block.statements`, never
        # `block.final_expr`. A suspending call buried in a TRAILING `if`/`match`/
        # wrapper (e.g. `while going { ...; if c { let x = try! s.read() } }`,
        # where the `if` is the loop body's `final_expr`) would otherwise never be
        # statementized in time for the try/condition/match hoist to see it, slip
        # past `_collect_calls`'s classification AND every rejection, and lower as a
        # PLAIN blocking call — the silent DF7 miscompile. Normalizing first makes
        # every suspending call sit in statement position within some block, so the
        # wrapper hoists and the collect/reject walk are exhaustive by construction.
        self._normalize_suspending_tails()
        # design 62 G2: hoist a suspending call out of an `if let`/`guard let`
        # CONDITION into a preceding driven temp, BEFORE call/local collection —
        # the temp is then an ordinary nested-suspending-call-in-let and the
        # binding is over a non-spanning optional. Runs after `_suspends` is set.
        self._hoist_suspending_conditions()
        # design 92: hoist a suspending call out of a `try!`/`try`/`try?` wrapper
        # into a preceding driven temp, so a `try! recv.read()` in a spawned body
        # is embedded+driven (its internal park integrates with the executor)
        # rather than hiding inside a TryExpr the nested-call scan cannot see.
        self._hoist_suspending_try()
        # design 96: hoist a SUSPENDING call out of a `match <call> { ... }`
        # SCRUTINEE into a preceding driven temp (`let __matchN = <call>` +
        # `match __matchN`). Runs AFTER tail normalization so a trailing match is
        # already a statement. Without this the suspending scrutinee hides inside
        # the MatchExpr, `_collect_calls` never sees a bare call to embed+drive, and
        # the callee's internal `io_wait` park blocks the thread instead of yielding
        # — a `match stream.read() {...}` worker hangs (even at nesting depth 1).
        self._hoist_suspending_match()
        # design 104 item 1: an `if let`/`guard let` whose BODY spans a suspension
        # cannot be lowered in place (its branch must break across resume states).
        # Mark such bindings for CFG-splitting and rename each to a UNIQUE frame
        # field, rewriting its body uses — so the design-100 `if let x = x` shadow
        # (inner `x: T` vs the outer optional `x: T?`) never collides on one field.
        # Runs after the condition/try/match hoists (a suspending CONDITION is
        # already lifted to a temp) and before call/local collection.
        self._mark_optional_binding_splits()
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
            encmap[p.name] = _enc_of(p.type)
        for lname, lt in self.frame_locals:
            encmap[lname] = _enc_of(lt)
        if self.is_void:
            self.result_enc = "plain"
        elif self.force_opt_result:
            # A spawn root forces its result opt-encoded so the `TaskHandle<T>`
            # uniformly holds `UnsafePointer<T?>`, regardless of T.
            self.result_enc = "opt"
        else:
            self.result_enc = _enc_of(self.ret)
        self.encmap = encmap

        fields = []
        if self.is_method:
            fields.append(StructField(name="__recv", type=self.recv_type))
        for p in self.params:
            fields.append(StructField(name=p.name,
                                      type=_clear_escaping(_field_type(p.type, encmap[p.name]))))
        for lname, lt in self.frame_locals:
            fields.append(StructField(name=lname,
                                      type=_clear_escaping(_field_type(lt, encmap[lname]))))
        for c in self.calls:
            fields.append(StructField(
                name=c['sub'],
                type=SawType(TypeKind.STRUCT, struct_name=f"__Frame_{c['callee']}")))
        # design 62 G3: each inline cooperative `receive()` needs a frame-resident
        # `__haveN` completion flag (its loop spans a suspension). A bare (discarded)
        # receive also needs a `__rcvN` holder for the moved-out value (dropped once
        # at teardown); a `let v = ...` receive writes into the collected local `v`.
        for rc in self.recv_calls:
            fields.append(StructField(name=f"__have{rc['idx']}",
                                      type=SawType(TypeKind.BOOL)))
            if rc['target'] is None:
                fields.append(StructField(name=f"__rcv{rc['idx']}",
                                          type=_opt(rc['elem_type'])))
        # design 103 (A6): each offloaded blocking-extern call needs a frame-resident
        # `__blkjobN` handle (the job pointer as Int), held across the io_wait park
        # between start and take.
        for bc in self.blk_calls:
            fields.append(StructField(name=f"__blkjob{bc['idx']}",
                                      type=SawType(TypeKind.INT)))
        fields.append(StructField(name="__state", type=SawType(TypeKind.INT)))
        # The wake reason the frame communicates to the executor on a Pending
        # (design 45 item 4): 0 = ready (yield), >0 = sleep that many ms.
        fields.append(StructField(name="__wake", type=SawType(TypeKind.INT)))
        # design 91: the reactor wake-word ADDRESS to latch on an io readiness
        # event. For a driven ROOT frame it is `&self.__wake` (set on first resume);
        # a nested sub-frame inherits its parent's token (propagated at each drive),
        # so an `io_wait` buried in a sub-frame routes the wakeup to the TOP-LEVEL
        # frame's `__wake` word — the one the scheduler reads. 0 = not yet set.
        fields.append(StructField(name="__io_tok", type=SawType(TypeKind.INT)))
        # design 52b item 3: the cooperative cancel word. `handle.cancel()` sets it
        # (through a `TaskHandle`'s raw pointer into this frame); task code reads it
        # via `cancelled()`, which the transform rewrites to `self.__cancel`. NO
        # forced destroy — the frame exits only through its own control flow.
        fields.append(StructField(name="__cancel", type=SawType(TypeKind.BOOL)))
        if not self.is_void:
            fields.append(StructField(name="__result",
                                      type=_field_type(self.ret, self.result_enc)))
        self.frame_struct = Struct(name=self.frame_name, fields=fields,
                                   line=func.line, column=func.column,
                                   source_file=getattr(func, 'source_file', ""))
        return self.frame_struct

    def _classify_call(self, stmt):
        """If `stmt` is a top-level nested SUSPENDING call boundary, return
        {callee, args, target, ret}; else None. Supported forms: `let x = g(args)`
        (result → local `x`), a bare `g(args)` or `let _ = g(args)` (result
        discarded), and — after design-83 tail normalization — `return g(args)`
        (result → this frame's `__result`), where `g` is a suspending free
        function in the driven closure."""
        if _is_suspend_stmt(stmt):
            return None
        fc = None
        target = None
        is_ret = False
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, FunctionCall):
            fc = stmt.value
            # `let _ = g()` is a discard (design 53): there is no `_` frame field
            # to store into, so thread nothing (the sub-frame owns+drops its own
            # result exactly once at teardown).
            target = stmt.name if stmt.name != "_" else None
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, FunctionCall)):
            fc = stmt.expression
        elif (isinstance(stmt, ReturnStatement)
              and isinstance(stmt.value, FunctionCall)):
            fc = stmt.value
            is_ret = True
        if fc is None:
            # design 84: a nested suspending METHOD call (`let s = recv.accept()`,
            # bare `recv.write_all(...)`, or a tail `return recv.m(...)`). The callee
            # frame is a method frame (`__recv` points at the receiver's storage);
            # its key is `{struct}_{method}`, matching `_FrameBuilder.name`.
            return self._classify_method_call(stmt, target, is_ret)
        if fc.name not in self._suspends:
            return None
        if getattr(fc, 'type_args', None):
            # design 70 (A5): a TOP driven/spawned generic is monomorphized before
            # the transform, but a generic call NESTED inside another driven body
            # is not (it would need its instantiation embedded as a sub-frame).
            # A5-rest: hoist it to a top-level driven root, or make it non-generic.
            raise CoroTransformError(
                f"coroutine transform: a nested suspending call to a generic "
                f"function `{fc.name}` inside `{self.name}` is not yet supported "
                f"(design 70 A5-rest)", fc.line, fc.column)
        return {'callee': fc.name, 'args': list(fc.arguments), 'target': target,
                'ret': is_ret}

    def _classify_method_call(self, stmt, target, is_ret):
        """design 84: classify a nested suspending METHOD call boundary. Returns
        {callee: `{struct}_{method}`, args, target, ret, recv, recv_struct,
        recv_type_args, is_method} or None. Supported forms mirror the free-function
        ones (let-bound / bare-discard / tail-return); the RECEIVER must be a plain
        struct (a generic-struct receiver is left for `_reject_suspending_method_call`
        to reject cleanly — the frame's `__recv` pointee would need the instantiation)."""
        mc = None
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
            # `let x = recv.m()` threads the result into `x`; `let _ = recv.m()` is a
            # discard (no frame field to store into — the sub-frame drops its own
            # result once at teardown).
            target = stmt.name if stmt.name != "_" else None
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, MethodCall)):
            mc = stmt.expression
        elif isinstance(stmt, ReturnStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
        if mc is None or getattr(mc, 'is_chan_recv', False):
            return None
        susp = getattr(self._tc, '_suspending_methods_set', None) if self._tc else None
        if not susp:
            return None
        recv_type = getattr(mc.object, 'resolved_type', None)
        sname = getattr(recv_type, 'struct_name', None) if recv_type else None
        if sname is None or (sname, mc.method_name) not in susp:
            return None
        if getattr(recv_type, 'type_args', None):
            # A generic-struct receiver — not embedded here (rejected downstream).
            return None
        return {'callee': _method_frame_key(
                    sname, mc.method_name, getattr(mc, 'resolved_symbol', None)),
                'args': list(mc.arguments), 'target': target, 'ret': is_ret,
                'recv': mc.object, 'recv_struct': sname, 'is_method': True}

    def _classify_recv(self, stmt):
        """design 62 G3: if `stmt` is a top-level cooperative `ch.receive()`
        boundary, return {receiver, target, elem_type}; else None. Supported
        forms: `let v = ch.receive()` and a bare `ch.receive()` statement. The
        call lowers inline to the try_receive+yield_now loop (no callee frame)."""
        mc = None
        target = None
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, MethodCall):
            mc, target = stmt.value, stmt.name
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, MethodCall)):
            mc = stmt.expression
        if mc is None or not getattr(mc, 'is_chan_recv', False):
            return None
        elem_type = getattr(mc, 'resolved_type', None)
        if elem_type is None:
            raise CoroTransformError(
                f"coroutine transform: `receive()` in `{self.name}` has no "
                f"resolved element type", mc.line, mc.column)
        return {'receiver': mc.object, 'target': target, 'elem_type': elem_type}

    # ------------------------------------------------------------------ #
    # design 103 (A6): blocking-extern offload
    # ------------------------------------------------------------------ #
    def _blocking_extern_sym(self, name):
        """The FunctionSymbol for `name` if it is a registered `extern blocking
        func`, else None. Consulted so the transform can OFFLOAD a blocking FFI
        call (start a worker thread + park on its pipe) instead of leaving it a
        direct call that would trip the synthesized `resume`'s sync check."""
        tc = self._tc
        if tc is None:
            return None
        ns = (getattr(tc, "_entry_module_ns", None)
              or getattr(tc, "namespace", None))
        if ns is None:
            return None
        sym = ns.lookup_function(name)
        if sym is not None and getattr(sym, "is_blocking", False):
            return sym
        return None

    def _is_blocking_extern(self, name):
        return self._blocking_extern_sym(name) is not None

    def _check_blk_whitelist(self, fc):
        """v1 offload thunk is the C ABI `i64(i64)` — enforce a single `Int`
        parameter and an `Int` result (a subset of the design-58 extern whitelist).
        A wider signature is a clean anchored error (multi-arg / non-Int is future
        work), never a silent miscompile."""
        sym = self._blocking_extern_sym(fc.name)
        pts = list(getattr(sym, "param_types", []) or [])
        rt = getattr(sym, "return_type", None)
        ok = (len(pts) == 1 and pts[0] is not None and pts[0].kind == TypeKind.INT
              and rt is not None and rt.kind == TypeKind.INT)
        if not ok:
            raise CoroTransformError(
                f"coroutine transform: the blocking extern `{fc.name}` offloaded "
                f"from `{self.name}` must have the v1 signature `(Int) -> Int` "
                f"(the thread-per-call offload thunk is `i64(i64)`; multi-argument "
                f"and non-Int blocking externs are future work)",
                fc.line, fc.column, source_file=self.src_file)

    def _classify_blk(self, stmt):
        """design 103: if `stmt` is a top-level blocking-extern call boundary,
        return {call, target, ret}; else None. Supported forms mirror the nested
        free-function ones: `let x = slow(arg)` (result -> local `x`), a bare
        `slow(arg)` / `let _ = slow(arg)` (discard), and — after design-83 tail
        normalization — `return slow(arg)` (result -> this frame's `__result`).
        The call site desugars to start -> io_wait(pipe fd) -> take (see
        `_emit_blk_call`)."""
        fc = None
        target = None
        is_ret = False
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, FunctionCall):
            fc = stmt.value
            target = stmt.name if stmt.name != "_" else None
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, FunctionCall)):
            fc = stmt.expression
        elif (isinstance(stmt, ReturnStatement)
              and isinstance(stmt.value, FunctionCall)):
            fc = stmt.value
            is_ret = True
        if fc is None or not self._is_blocking_extern(fc.name):
            return None
        self._check_blk_whitelist(fc)
        return {'call': fc, 'target': target, 'ret': is_ret}

    def _method_call_suspends(self, mc):
        """design 84: True if `mc` is a call to a suspending method on a concrete
        (non-generic) struct receiver — the shape embedded as a nested method
        sub-frame."""
        if getattr(mc, 'is_chan_recv', False):
            return False
        susp = getattr(self._tc, '_suspending_methods_set', None) if self._tc else None
        if not susp:
            return False
        recv_type = getattr(mc.object, 'resolved_type', None)
        sname = getattr(recv_type, 'struct_name', None) if recv_type else None
        return sname is not None and (sname, mc.method_name) in susp

    def _suspending_method_call(self, stmt):
        """If `stmt` is a top-level `let x = recv.m(args)` / bare `recv.m(args)`
        whose method `m` on `recv`'s concrete struct type suspends, return the
        MethodCall; else None. Consults the transform's (struct, method) suspend set
        (design 74 shape 1)."""
        mc = None
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, MethodCall)):
            mc = stmt.expression
        if mc is None or getattr(mc, 'is_chan_recv', False):
            return None
        susp = getattr(self._tc, '_suspending_methods_set', None) if self._tc else None
        if not susp:
            return None
        recv_type = getattr(mc.object, 'resolved_type', None)
        sname = getattr(recv_type, 'struct_name', None) if recv_type else None
        if sname is not None and (sname, mc.method_name) in susp:
            return mc
        return None

    def _reject_suspending_method_call(self, stmt):
        mc = self._suspending_method_call(stmt)
        if mc is not None:
            recv_type = getattr(mc.object, 'resolved_type', None)
            sname = getattr(recv_type, 'struct_name', None) if recv_type else "?"
            raise CoroTransformError(
                f"coroutine transform: a buried suspending method call "
                f"`{sname}.{mc.method_name}(...)` inside driven `{self.name}` is not "
                f"yet supported (design 74 A5-rest, shape 1: method sub-frame "
                f"embedding). Drive the method directly with "
                f"`__saw_drive(recv.{mc.method_name}(...))`, or wrap the call in a "
                f"nested free function and call that.",
                mc.line, mc.column, source_file=self.src_file)

    def _reject_buried_suspend_call(self, stmt):
        """A suspending call in a position the flat state split cannot express —
        inside a larger expression, a method-call receiver, or a control-flow
        container that is NOT CFG-split (an `if let`/`guard let` branch, whose body
        is lowered in place, not split) — is rejected with a clear anchored message
        rather than miscompiled (the callee's park would silently no-op / block).

        design 101 (DF7 class): this is the LAST-RESORT catch for a suspending call
        that every hoist + the classify/split walk left un-embedded. It MUST see a
        suspending METHOD call, not only a free-function / channel `receive()` — a
        buried method call (e.g. `stream.read()` inside a `guard let ... else { }`
        or `if let ... { }` body) previously slipped through here and lowered as a
        PLAIN blocking call, the exact silent-blocking miscompile this design closes.
        The split-capable containers (`if`/`while`/`for`/`match`) never reach this
        method — `_collect_calls` recurses INTO them and classifies each nested call
        — so flagging method calls here rejects only genuinely inexpressible shapes."""
        found = []

        def scan(n):
            if isinstance(n, FunctionCall) and (
                    n.name in self._suspends or n.name in _SUSPEND_CALLS):
                found.append(("fn", n))
            # design 103 (A6): a blocking-extern call in a position the offload
            # desugar cannot occupy (buried in a larger expression, a `try!`, an
            # `if let`/`guard let` body). Reject cleanly, ANCHORED AT THE USER CALL
            # SITE — never let it fall through to lower as a direct call and trip the
            # synthesized `resume`'s sync check anchored at `__Frame_*.resume`.
            elif isinstance(n, FunctionCall) and self._is_blocking_extern(n.name):
                found.append(("blk", n))
            # design 62 G3: a cooperative `receive()` buried in an expression /
            # nested position (only a top-level `let v = ch.receive()` or bare
            # `ch.receive()` is supported) is rejected rather than miscompiled.
            elif isinstance(n, MethodCall) and getattr(n, 'is_chan_recv', False):
                found.append(("recv", _FakeCall("receive", n.line, n.column)))
            # design 101: a suspending METHOD call in a position no hoist lifted and
            # the CFG walk cannot split (an `if let`/`guard let` body). Reject with
            # the same workaround the top-level buried-method rejection names.
            elif isinstance(n, MethodCall) and self._method_call_suspends(n):
                found.append(("method", n))
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
            kind, g = found[0]
            if kind == "method":
                recv_type = getattr(g.object, 'resolved_type', None)
                sname = getattr(recv_type, 'struct_name', None) if recv_type else "?"
                raise CoroTransformError(
                    f"coroutine transform: a buried suspending method call "
                    f"`{sname}.{g.method_name}(...)` inside driven `{self.name}` "
                    f"appears in a control-flow branch the state split cannot express "
                    f"(an `if let`/`guard let` body). Restructure to a plain "
                    f"`if`/`else` or `match`, or drive the method directly.",
                    g.line, g.column, source_file=self.src_file)
            if kind == "blk":
                raise CoroTransformError(
                    f"coroutine transform: the blocking-extern call `{g.name}(...)` "
                    f"inside `{self.name}` appears in a nested/expression position "
                    f"the offload desugar cannot occupy; bind it to its own statement "
                    f"first (`let r = {g.name}(...)`), then use `r`",
                    g.line, g.column, source_file=self.src_file)
            raise CoroTransformError(
                f"coroutine transform: suspending call to `{g.name}` in `{self.name}` "
                f"appears in a nested/expression position; only a top-level "
                f"`let x = {g.name}(...)` or `{g.name}(...)` statement is supported",
                g.line, g.column, source_file=self.src_file)

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
        # design 77 item 4: the current statement's closure-capture materialization
        # `let`s (None outside a straight-line statement that can host them).
        self._cap_lets = None
        # design 77 item 10: fresh-temp counter for destructuring lowering.
        self._destr_ctr = 0
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

        # design 91: on the FIRST resume of a driven ROOT frame, latch this frame's
        # reactor token to its own `__wake`-word address. A nested sub-frame is
        # driven with `__io_tok` already set by its parent (propagated in the drive
        # block), so this leaves the inherited root token in place — an `io_wait`
        # anywhere in the call tree routes its wakeup to the root's `__wake` word.
        io_tok_init = ExpressionStatement(expression=IfExpr(
            condition=BinaryOp(op="==", left=_self_field("__io_tok"), right=_int(0)),
            then_branch=Block(statements=[AssignStatement(
                target=_self_field("__io_tok"),
                value=CastExpr(
                    expr=CastExpr(
                        expr=ReferenceExpr(expr=_self_field("__wake"), mutable=False),
                        target_type=SawType(kind=TypeKind.POINTER,
                                             inner_type=SawType(kind=TypeKind.INT),
                                             pointer_mutable=True)),
                    target_type=SawType(kind=TypeKind.INT)))],
                final_expr=None),
            else_branch=None))

        resume = Method(
            name="resume",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.ENUM, enum_name="__Poll"),
            body=Block(statements=[io_tok_init, loop], final_expr=None),
            self_mutable=True, self_is_reference=True, is_sync=True,
            is_synthesized=True,
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
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # design 102 item 2: the cooperative-cancel read surface — a `&self`
        # accessor returning the frame's `__cancel` word, so the scheduler can wake
        # an io-parked frame whose peer set the cancel flag (it then re-checks
        # `cancelled()` at its park-loop top and bails). Every frame has `__cancel`.
        is_cancelled = Method(
            name="__is_cancelled",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=False)],
            return_type=SawType(TypeKind.BOOL),
            body=Block(statements=[], final_expr=_self_field("__cancel")),
            self_mutable=False, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # Every frame conforms to the builtin `Resumable` trait (design 52b item
        # 1): the conformance is what lets a frame be erased into
        # `Box<any Resumable>` for the heterogeneous run queue. Concrete drives
        # (nested sub-frames, the entry executor, `__saw_drive_*`) still bind `resume`
        # statically — conformance only synthesizes a vtable at an erasure site.
        resume_ext = Extension(struct_name=self.frame_name,
                               methods=[resume, wake_reason, is_cancelled],
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
            forgets = []
            fc = s.expression
            # design 76 (A4): `io_wait(fd, dir)` is register-then-park sugar. Emit
            # the (non-suspending) reactor registration IN PLACE with `fd`/`dir`
            # rewritten to frame fields, then suspend with the IO-PARK wake reason.
            if fc.name == "io_wait":
                fd_a = self._rewrite_expr(fc.arguments[0].value, forgets)
                dir_a = self._rewrite_expr(fc.arguments[1].value, forgets)
                self._emit(self._forgets(forgets))
                # design 91: register with the TOP-LEVEL frame's `__wake`-word address
                # (`self.__io_tok`) as the reactor token, so a readiness event latches
                # exactly the wake word the scheduler reads — precise routing, not
                # wake-all. `__io_tok` is `&root.__wake`: a driven root sets it to
                # `&self.__wake` on first resume; a nested sub-frame inherits it from
                # its parent at each drive, so an `io_wait` buried in a sub-frame still
                # routes the wake to the root frame the scheduler schedules.
                self._emit([ExpressionStatement(expression=FunctionCall(
                    name="__saw_rt_reactor_register",
                    arguments=[Argument(name=None, value=fd_a),
                               Argument(name=None, value=dir_a),
                               Argument(name=None, value=_self_field("__io_tok"))]))])
                nxt = self._new_block()
                self._suspend_to(_int(IO_PARK_WAKE), nxt)
                self.cur = nxt
                return
            # The wake expression (e.g. `sleep(ms)`'s `ms`) is ordinary body code:
            # rewrite its identifiers to frame fields, so a NON-literal argument
            # (`sleep(delay)` where `delay` is a param/local) reads `self.delay`.
            wake = self._rewrite_expr(_wake_expr(s), forgets)
            nxt = self._new_block()
            self._emit(self._forgets(forgets))
            self._suspend_to(wake, nxt)
            self.cur = nxt
            return
        # design 62 G3: a cooperative `ch.receive()` — lower inline to the
        # try_receive+yield_now loop against this frame (no callee frame).
        rinfo = self.recv_by_id.get(id(s))
        if rinfo is not None:
            self._emit_recv_call(rinfo)
            return
        # design 103 (A6): a blocking-extern call — offload it to a worker thread
        # and park on the job's pipe (start -> io_wait -> take).
        binfo = self.blk_by_id.get(id(s))
        if binfo is not None:
            self._emit_blk_call(binfo)
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
        # design 96 (DF6): an if/match that carries a `break`/`continue` for the
        # enclosing spanning loop must be SPLIT even if it does not itself span a
        # suspension — otherwise the jump lowers in place and escapes the resume
        # dispatch loop (a `while` / `for` introduces its OWN loop scope, so its
        # inner break targets itself and needs no split for our sake).
        needs_ctrl_split = loop_ctx is not None and self._has_loop_ctrl(ctrl)
        # design 104 item 1: an `if let`/`guard let` whose body spans a suspension
        # was CFG-split (marked in `_mark_optional_binding_splits`).
        if isinstance(ctrl, IfLetExpr) and getattr(ctrl, '_coro_split', False):
            self._split_if_let(ctrl, loop_ctx)
            return
        if isinstance(s, GuardLetStatement) and getattr(s, '_coro_split', False):
            self._split_guard_let(s, loop_ctx)
            return
        if isinstance(ctrl, IfExpr) and (self._spans_suspension(ctrl)
                                         or needs_ctrl_split):
            self._split_if(ctrl, loop_ctx)
            return
        if isinstance(ctrl, WhileExpr) and self._spans_suspension(ctrl):
            self._split_while(ctrl, loop_ctx)
            return
        if isinstance(s, ForLoop) and self._spans_suspension(s):
            self._split_for(s, loop_ctx)
            return
        if isinstance(ctrl, MatchExpr) and (self._spans_suspension(ctrl)
                                            or needs_ctrl_split):
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

    def _optbind_dispatch(self, node, scrut, some_state, none_state):
        """design 104 item 1: emit the optional-binding dispatch as an ordinary
        `if let` whose branches ONLY set the resume state (codegen already lowers an
        `if let` over a `T?` correctly — this reuses that has-value test + unwrap
        instead of a synthesized Some/None match). On the value path the unwrapped
        binding is stored into its frame field so it survives the transition to the
        (separately-dispatched) body state; both paths set `__state` and re-dispatch."""
        bind = node.name
        some_body = []
        if bind in self.encmap:
            some_body.append(AssignStatement(
                target=_self_field(bind), value=Identifier(name=bind)))
        some_body.append(AssignStatement(
            target=_self_field("__state"), value=_int(some_state)))
        none_body = [AssignStatement(
            target=_self_field("__state"), value=_int(none_state))]
        dispatch = IfLetExpr(
            name=bind, optional_expr=scrut, mutable=node.mutable,
            then_branch=Block(statements=some_body, final_expr=None),
            else_branch=Block(statements=none_body, final_expr=None),
            line=node.line, column=node.column)
        self._emit([ExpressionStatement(expression=dispatch)])
        self._blocks[self.cur].append(ContinueStatement())
        self._term.add(self.cur)

    def _split_if_let(self, e, loop_ctx):
        forgets = []
        scrut = self._rewrite_expr(e.optional_expr, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` of the scrutinee of a "
                f"suspension-spanning `if let` in `{self.name}` is not supported",
                e.line, e.column)
        then_entry = self._new_block()
        else_entry = self._new_block() if e.else_branch is not None else None
        merge = self._new_block()
        self._optbind_dispatch(
            e, scrut, then_entry, else_entry if else_entry is not None else merge)
        self.cur = then_entry
        self._lower_block(e.then_branch, loop_ctx)
        if self.cur not in self._term:
            self._goto(merge)
        if else_entry is not None:
            self.cur = else_entry
            self._lower_block(e.else_branch, loop_ctx)
            if self.cur not in self._term:
                self._goto(merge)
        self.cur = merge

    def _split_guard_let(self, s, loop_ctx):
        forgets = []
        scrut = self._rewrite_expr(s.optional_expr, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` of the scrutinee of a "
                f"suspension-spanning `guard let` in `{self.name}` is not supported",
                s.line, s.column)
        none_entry = self._new_block()
        after = self._new_block()
        # Value path -> `after` (the guard's continuation, which the enclosing
        # statement loop lowers into `after` next); None path -> the else-branch,
        # which must diverge (return/break/continue) per guard semantics.
        self._optbind_dispatch(s, scrut, after, none_entry)
        self.cur = none_entry
        self._lower_block(s.else_branch, loop_ctx)
        if self.cur not in self._term:
            self._goto(after)
        self.cur = after

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
            # Carry every payload binding into its frame field, so the arm's
            # (separately-dispatched) entry block can read it after a suspend.
            # Bindings come from the classic enum form (`arm.bindings`) AND — for
            # design-63 patterns — from `arm.pattern` (a bare `case n`, a tuple, or
            # a nested enum pattern). The guard, if any, runs during dispatch and
            # reads these bindings as LOCALS (still in scope in the dispatch arm),
            # so it stays unrewritten — it is stored to the field only in the body.
            for bname in list(arm.bindings) + self._pattern_binding_names(arm.pattern):
                if bname == "_" or bname not in self.encmap:
                    continue
                dispatch.append(AssignStatement(
                    target=_self_field(bname), value=Identifier(name=bname)))
            dispatch.append(AssignStatement(
                target=_self_field("__state"), value=_int(entry)))
            # design 101: preserve `pattern` and `guard` on the regenerated dispatch
            # arm. Reconstructing from `variant_name`/`bindings` alone dropped the
            # design-63 literal/range/tuple `pattern` (and any `guard`), so a
            # suspension-spanning `match` over literal/range arms lost its pattern
            # info and codegen reported a spurious "match is not exhaustive" on the
            # synthesized arms (at 0:0). Carrying both through keeps the dispatch
            # match structurally identical to the source match's arm selection.
            new_arms.append(MatchArm(
                variant_name=arm.variant_name, bindings=list(arm.bindings),
                body=Block(statements=dispatch, final_expr=None),
                pattern=arm.pattern, guard=arm.guard))
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

    def _emit_blk_call(self, bc):
        """design 103 (A6): lower a blocking-extern call to the offload sequence,
        parking on the job's pipe like any socket read. The desugar is
        `self.__blkjobN = __saw_blk_start(slow(arg))` then a park loop
        `while __saw_blk_done(job) == 0 { io_wait(__saw_blk_pipe_fd(job), read) }` then
        `<target> = __saw_blk_take(job)` — start spawns the worker thread, the io_wait
        registers the job's readable pipe fd with the reactor (precise wake token +
        budget reset-on-park apply unchanged), and take joins the thread + frees the
        job. The park loop ALSO bails on `__cancel` (design 102 compose: a peer
        cancel writes the reactor self-pipe, which rouses this poll; the re-check
        exits the loop). The in-flight blocking call cannot be aborted, so take()
        still joins its thread on the cancel path — no leak, no data race."""
        idx = bc['idx']
        job = f"__blkjob{idx}"
        fc = bc['call']
        forgets = []
        inner_args = [Argument(name=None, value=self._rewrite_expr(a.value, forgets))
                      for a in fc.arguments]
        inner = FunctionCall(name=fc.name, arguments=inner_args,
                             line=fc.line, column=fc.column)
        start = FunctionCall(name="__saw_blk_start",
                             arguments=[Argument(name=None, value=inner)])
        self._emit(self._forgets(forgets))
        self._emit([AssignStatement(target=_self_field(job), value=start)])
        header = self._new_block()
        check = self._new_block()
        park = self._new_block()
        after = self._new_block()
        self._goto(header)
        # header: bail on a peer cancel (design 102), else fall to the done check.
        self.cur = header
        self._branch(_self_field("__cancel"), after, check)
        # check: the worker finished -> take; else park on the job's pipe.
        self.cur = check
        done = BinaryOp(op="!=", left=FunctionCall(
            name="__saw_blk_done",
            arguments=[Argument(name=None, value=_self_field(job))]), right=_int(0))
        self._branch(done, after, park)
        # park: register the readable pipe fd + suspend (io-park), retry on wake.
        self.cur = park
        fd = FunctionCall(name="__saw_blk_pipe_fd",
                          arguments=[Argument(name=None, value=_self_field(job))])
        self._emit([ExpressionStatement(expression=FunctionCall(
            name="__saw_rt_reactor_register",
            arguments=[Argument(name=None, value=fd),
                       Argument(name=None, value=_int(0)),
                       Argument(name=None, value=_self_field("__io_tok"))]))])
        self._suspend_to(_int(IO_PARK_WAKE), header)
        # after: take the result (joins the worker thread + frees the job).
        self.cur = after
        take = FunctionCall(name="__saw_blk_take",
                            arguments=[Argument(name=None, value=_self_field(job))])
        if bc['ret']:
            self._done(take)
        elif bc['target'] is not None:
            self._emit([AssignStatement(target=_self_field(bc['target']), value=take)])
        else:
            self._emit([ExpressionStatement(expression=take)])

    def _emit_recv_call(self, rc):
        """design 62 G3: lower a cooperative `ch.receive()` INLINE into the
        try_receive+yield_now loop, driven across the caller's own resumes. No
        callee frame — the loop is CFG-split exactly like a user `while` with a
        `yield_now` inside. On each visit: try a non-blocking `try_receive`; on a
        value, store it (into the `let v` target or a discard holder) and set the
        completion flag; on empty, suspend (wake 0 = channel-yield) and retry when
        the executor reschedules the task."""
        idx = rc['idx']
        have = f"__have{idx}"
        target = rc['target'] if rc['target'] is not None else f"__rcv{idx}"
        rv = f"__rv{idx}"
        recv_expr = self._rewrite_expr(rc['receiver'], [])
        # Reset the completion flag (a frame is one-shot per receive site, but keep
        # it explicit and re-entry-safe).
        self._emit([AssignStatement(target=_self_field(have),
                                    value=BoolLiteral(value=False))])
        header = self._new_block()
        body_b = self._new_block()
        yield_b = self._new_block()
        after = self._new_block()
        self._goto(header)
        # header: loop while not have; exit when a value has been received.
        self.cur = header
        self._branch(UnaryOp(op="not", operand=_self_field(have)), body_b, after)
        # body: non-blocking attempt. `if let __rv = <recv>.try_receive() { ... }`
        # is non-spanning (try_receive never suspends), lowered in place here.
        self.cur = body_b
        try_call = MethodCall(object=recv_expr, method_name="try_receive",
                              arguments=[])
        iflet = IfLetExpr(
            name=rv, optional_expr=try_call, mutable=False,
            then_branch=Block(statements=[
                AssignStatement(target=_self_field(target),
                                value=Identifier(name=rv)),
                AssignStatement(target=_self_field(have),
                                value=BoolLiteral(value=True)),
            ], final_expr=None),
            else_branch=None)
        self._emit([ExpressionStatement(expression=iflet)])
        # Got a value -> back to header (which exits); still empty -> suspend.
        self._branch(_self_field(have), header, yield_b)
        self.cur = yield_b
        self._suspend_to(_int(0), header)
        self.cur = after

    def _emit_nested_call(self, info, loop_ctx):
        """Embed the callee frame (once) and drive it across the caller's own
        resumes: the drive block resumes the sub-frame; on Pending it propagates
        the callee's wake reason and returns Pending (staying in the drive block);
        on Done it captures the callee's result and re-dispatches past the call."""
        fbs = self._fbs
        callee_fb = fbs[info['callee']]
        sub = info['sub']
        target = info['target']
        is_ret = info.get('ret', False)
        self._emit(self._build_sub_frame(info, fbs))
        drive = self._new_block()
        self._goto(drive)
        # A `return g(...)` tail (design 83) threads the callee's result into THIS
        # frame's `__result` and ends the coroutine; a `let x`/bare/discard call
        # stores (or drops) the result and re-dispatches past the call.
        after = None if is_ret else self._new_block()
        done_body = []
        if is_ret:
            if not callee_fb.is_void and not self.is_void:
                res = MemberAccess(object=_self_field(sub), member="__result")
                if _enc_unwraps(callee_fb.result_enc):
                    res = ForceUnwrap(expr=res)
                # Store first (loads the value), THEN clear the sub-frame's drop
                # flag so its teardown won't double-drop the moved-out result.
                done_body.append(AssignStatement(
                    target=_self_field("__result"), value=res))
                if _enc_cleanup(callee_fb.result_enc):
                    done_body.append(ExpressionStatement(expression=FunctionCall(
                        name="__saw_forget", arguments=[Argument(name=None,
                            value=MemberAccess(object=_self_field(sub),
                                               member="__result"))])))
            done_lit = _int(0)  # patched to the done-state marker after assembly
            self._done_lits.append(done_lit)
            done_body.append(AssignStatement(
                target=_self_field("__state"), value=done_lit))
            done_body.append(ReturnStatement(value=_poll("Done")))
        else:
            if target is not None and not callee_fb.is_void:
                res = MemberAccess(object=_self_field(sub), member="__result")
                if _enc_unwraps(callee_fb.result_enc):
                    res = ForceUnwrap(expr=res)
                done_body.append(AssignStatement(
                    target=_self_field(target), value=res))
                if _enc_cleanup(callee_fb.result_enc):
                    done_body.append(ExpressionStatement(expression=FunctionCall(
                        name="__saw_forget", arguments=[Argument(name=None,
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
        # design 91: hand the sub-frame THIS frame's reactor token (the root's
        # `__wake`-word address) before driving it, so an `io_wait` inside the
        # sub-frame routes its wakeup to the root frame the scheduler schedules.
        self._blocks[drive].append(AssignStatement(
            target=MemberAccess(object=_self_field(sub), member="__io_tok"),
            value=_self_field("__io_tok")))
        # design 102 item 2: propagate the cancel word down the frame chain the same
        # way. A peer cancels the ROOT frame (the one the handle points at); this
        # copy makes the flag visible to a `cancelled()` check inside the nested
        # (sub-frame) suspending method, so a task parked in `stream.read()` observes
        # the cancel at its park-loop top and bails.
        self._blocks[drive].append(AssignStatement(
            target=MemberAccess(object=_self_field(sub), member="__cancel"),
            value=_self_field("__cancel")))
        resume_call = MethodCall(object=_self_field(sub), method_name="resume",
                                 arguments=[])
        match = MatchExpr(matched_expr=resume_call, arms=[
            MatchArm(variant_name="Pending", bindings=[], body=Block(
                statements=pending_body, final_expr=None)),
            MatchArm(variant_name="Done", bindings=[], body=Block(
                statements=done_body, final_expr=None)),
        ])
        self._blocks[drive].append(ExpressionStatement(expression=match))
        if is_ret:
            # Both arms terminate (Pending returns, Done returns) — no fall-through
            # re-dispatch and no `after` block; the drive block IS the tail state.
            self._term.add(drive)
            self.cur = drive
        else:
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
            val = self._rewrite_expr(a.value, forgets)
            # design 88 (D6): a reference argument to a nested suspending callee is
            # seeded into the callee sub-frame's `UnsafePointer<T>` field as a raw
            # pointer into THIS (caller) frame's storage — the referent lives in the
            # task frame, so it outlives the sub-frame's drive. Cast `&var self.x`
            # -> `UnsafePointer<T>` to match the callee's "ref" field encoding.
            if i < len(callee_fb.params):
                pname = callee_fb.params[i].name
                if callee_fb.encmap.get(pname) == "ref":
                    val = CastExpr(expr=val,
                                   target_type=_ref_ptr_type(callee_fb.params[i].type))
            arg_vals.append(val)
        recv_value = None
        if info.get('is_method'):
            # design 84: the method frame's `__recv` is a pointer into the
            # receiver's storage. The receiver is a caller-frame local/param — after
            # rewrite it is `self.<field>` (POD) or `self.<field>!` (opt-encoded
            # owning value); `&(...)` is addressable in both (opt payload address).
            # The method BORROWS through the pointer (no ownership move): accept /
            # read / write_all take `&self`, so the caller frame stays the sole owner
            # and drops the value exactly once at frame death.
            recv_rewritten = self._rewrite_expr(info['recv'], [])
            recv_value = CastExpr(
                expr=ReferenceExpr(expr=recv_rewritten, mutable=False),
                target_type=callee_fb.recv_type)
        init = _build_frame_init(callee_fb, arg_vals, fbs, recv_value=recv_value)
        out = [AssignStatement(target=_self_field(info['sub']), value=init)]
        out.extend(self._forgets(forgets))
        return out

    # -------------------------------------------------- in-place lowering
    #
    # `_lower_inplace` rewrites a NON-suspending statement (or a non-spanning
    # control-flow construct) for the resume method without splitting states:
    #   * `let`/`var` of a frame-resident local -> assignment to `self.<name>`;
    #   * identifier reads -> `self.<field>`; a `move <frame local>` -> the field
    #     read plus a `__saw_forget(self.f)` clearing the frame drop flag (Part 0a);
    #   * `return X` -> the end-of-coroutine done sequence;
    #   * nested non-spanning if/while/for/match blocks lowered in place.

    def _forget_stmt(self, name):
        return ExpressionStatement(expression=FunctionCall(
            name="__saw_forget", arguments=[Argument(name=None, value=_self_field(name))]))

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
        # design 77 item 4: a CALL to a frame-resident closure local `f(args)` ->
        # an indirect field call `self.f(args)` (codegen force-unwraps the
        # opt-encoded field). The closure name lives in `FunctionCall.name` (a
        # plain string, invisible to the identifier rewrite), so intercept it
        # here. Arguments are rewritten normally.
        if (isinstance(node, FunctionCall)
                and self.encmap.get(node.name) == "opt_closure"):
            mc = MethodCall(
                object=SelfExpr(line=node.line, column=node.column),
                method_name=node.name,
                arguments=self._rewrite_expr_val(node.arguments, forgets),
                line=node.line, column=node.column)
            return mc
        # design 77 item 4: a CLOSURE created in the driven body may capture frame
        # locals (params / across-suspend locals). Its body runs as a SEPARATE
        # function with no `self`, so rewriting the captures to `self.<field>`
        # inside it is wrong. Instead materialize each captured frame local as a
        # real local (`let base = self.base!`) right before the closure and leave
        # the closure body untouched — codegen then captures the local by value
        # (retain for ImplicitCopy) exactly as for ordinary code.
        if isinstance(node, ClosureExpr):
            self._materialize_closure_captures(node)
            return node
        if self.is_method and isinstance(node, SelfExpr):
            # The method's `self` -> the receiver through the frame pointer:
            # `self.__recv[0]` (here `self` is the frame — resume's receiver).
            return ArrayIndex(
                array_expr=_self_field("__recv", node.line, node.column),
                index=_int(0), line=node.line, column=node.column)
        if isinstance(node, MoveExpr) and node.path is None and node.variable in self.encmap:
            name = node.variable
            enc = self.encmap[name]
            if _enc_cleanup(enc):
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

    def _closure_frame_free_names(self, cexpr):
        """Frame-resident names (in `encmap`) referenced by a closure — the
        captures that must be materialized as real locals before it (design 77
        item 4). Collects every `Identifier` in the closure subtree that is a
        frame local, minus the closure's own parameter names, plus any explicit
        `[move x]`/`[&var x]` capture-spec names."""
        params = {p.name for p in (cexpr.parameters or [])}
        found = []
        seen = set()

        def add(name):
            if name in self.encmap and name not in params and name not in seen:
                seen.add(name)
                found.append(name)

        def walk(n):
            if isinstance(n, Identifier):
                add(n.name)
                return
            if isinstance(n, list):
                for e in n:
                    walk(e)
                return
            if isinstance(n, tuple):
                for e in n:
                    walk(e)
                return
            if isinstance(n, Argument):
                walk(n.value)
                return
            if isinstance(n, ASTNode):
                for f in dataclasses.fields(n):
                    walk(getattr(n, f.name))

        walk(cexpr.body)
        # Explicit capture-spec names ([move x] / [&var x]) reference frame locals
        # by name too.
        for spec in (cexpr.capture_specs or []):
            nm = getattr(spec, 'name', None)
            if nm is not None:
                add(nm)
        return found

    def _materialize_closure_captures(self, cexpr):
        """Append `let <name> = <frame read>` bindings for the closure's captured
        frame locals to the current statement's capture-let accumulator, so the
        closure captures a real local by value. Rejected (clean, anchored) if a
        closure with frame captures appears in a position with no accumulator
        (e.g. a suspension-spanning condition)."""
        names = self._closure_frame_free_names(cexpr)
        if not names:
            return
        if self._cap_lets is None:
            raise CoroTransformError(
                f"coroutine transform: a closure capturing a frame-resident local "
                f"in this position of driven `{self.name}` is not supported; bind "
                f"the closure to a `let` in straight-line body code",
                getattr(cexpr, 'line', self.func.line),
                getattr(cexpr, 'column', 0))
        already = {ls.name for ls in self._cap_lets}
        line = getattr(cexpr, 'line', 0)
        col = getattr(cexpr, 'column', 0)
        spec_names = {s.name for s in (cexpr.capture_specs or [])}
        for name in names:
            # The closure takes ownership of the materialized copy via a `move`
            # capture (design 77 item 4). Crucial for a state-machine `resume`:
            # a persistent function-local holding an owning value (Arc/String)
            # would be dropped on EVERY resume re-entry — a double-free across
            # suspensions. `move` consumes the materialized local so it is NOT
            # scope-cleaned; the env owns the sole copy and releases it once at
            # frame death.
            if name not in spec_names:
                cexpr.capture_specs = list(cexpr.capture_specs or []) + [
                    CaptureSpec(name=name, mode="move", line=line, column=col)]
            if name in already:
                continue
            # `.copy()` makes the materialized local an INDEPENDENT owner: the
            # frame still owns its field, so reading it out for the closure to
            # capture must not steal the frame's reference (that would double-free
            # at teardown). `.copy()` retains an ImplicitCopy (Arc / String /
            # closure env), duplicates an ExplicitCopy, and is a bitwise copy for
            # a trivial type — the same read-out-of-storage discipline as
            # `Vector.get`. The `move` capture above then transfers this owned copy
            # into the env.
            read = MethodCall(
                object=_read_field(name, self.encmap[name], line, col),
                method_name="copy", arguments=[], line=line, column=col)
            self._cap_lets.append(LetStatement(
                name=name, type_annotation=None, value=read,
                mutable=False, line=line, column=col))

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

        if isinstance(s, DestructuringLet):
            # `let (a, b) = value` across a suspension (design 77 item 10): bind
            # the source tuple to a fresh straight-line temp, then assign each
            # frame-resident leaf `self.<name> = __t.<i>` (the assignment
            # auto-wraps an opt-encoded field to Some). Wildcards bind nothing.
            forgets = []
            value = self._rewrite_expr(s.value, forgets)
            tmp = f"__destr{self._destr_ctr}"
            self._destr_ctr += 1
            out = [LetStatement(name=tmp, type_annotation=None, value=value,
                                mutable=False, line=s.line, column=s.column)]
            base = Identifier(name=tmp, line=s.line, column=s.column)
            self._destructure_assigns(s.pattern, base, out, s.line, s.column)
            return out + self._forgets(forgets)

        if isinstance(s, LetStatement):
            forgets = []
            saved_cap, self._cap_lets = self._cap_lets, []
            value = self._rewrite_expr(s.value, forgets)
            cap_lets, self._cap_lets = self._cap_lets, saved_cap
            if s.name in self.encmap:
                new = AssignStatement(
                    target=_self_field(s.name, s.line, s.column),
                    value=value, line=s.line, column=s.column)
            else:
                s.value = value
                new = s
            return cap_lets + [new] + self._forgets(forgets)

        if isinstance(s, AssignStatement):
            forgets = []
            saved_cap, self._cap_lets = self._cap_lets, []
            s.target = self._rewrite_expr(s.target, forgets)
            s.value = self._rewrite_expr(s.value, forgets)
            cap_lets, self._cap_lets = self._cap_lets, saved_cap
            return cap_lets + [s] + self._forgets(forgets)

        # A control-flow expression may appear as a bare statement (a user
        # `while`/`if`/`match`) or wrapped in an ExpressionStatement (driver-
        # generated). Handle both; lower nested blocks so a nested `return`,
        # `move`+`__saw_forget`, or nested-suspension diagnostic reaches them.
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        # design 62 G2: a non-spanning `if let`/`guard let` (its suspending
        # condition, if any, was hoisted out in `prepare`). Rewrite the optional
        # expression and lower the branch blocks in place, so a `return` inside a
        # branch becomes the coroutine done-sequence (not a raw `return`).
        if isinstance(ctrl, IfLetExpr):
            forgets = []
            ctrl.optional_expr = self._rewrite_expr(ctrl.optional_expr, forgets)
            self._lower_block_in_place(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._lower_block_in_place(ctrl.else_branch)
            return [s] + self._forgets(forgets)
        if isinstance(s, GuardLetStatement):
            forgets = []
            s.optional_expr = self._rewrite_expr(s.optional_expr, forgets)
            self._lower_block_in_place(s.else_branch)
            return [s] + self._forgets(forgets)
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
        saved_cap, self._cap_lets = self._cap_lets, []
        ns = self._rewrite_expr(s, forgets)
        cap_lets, self._cap_lets = self._cap_lets, saved_cap
        return cap_lets + [ns] + self._forgets(forgets)

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
        Done. The result store loads the value first, so the following `__saw_forget`
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
    if _enc_cleanup(enc):
        return NoneLiteral()
    # design 88: a reference frame field (raw pointer) in the not-yet-live state
    # is a null pointer — a dead sub-frame's placeholder, rebuilt with the real
    # referent address when its call site is reached, so never dereferenced.
    if enc == "ref":
        return CastExpr(expr=_int(0), target_type=_ref_ptr_type(saw_type))
    # design 62 G1: a plain-encoded frame-resident TaskGroup placeholder is a real
    # empty group (not a zero word) — always safe to drop, overwritten by the
    # user's `let group = TaskGroup()`.
    if _is_taskgroup(saw_type):
        return FunctionCall(name="TaskGroup", arguments=[])
    return _zero_of(saw_type)


def _frame_param_arg(p):
    """The expression that seeds a driver/spawn param into the frame field.

    Rider (design 77 item 4 note): a driven/spawned function taking an OWNING
    value param (e.g. `Arc<T>`), moved in at the drive/spawn site, must transfer
    that ownership INTO the frame — otherwise the wrapper's param keeps its drop
    flag AND the frame drops its field, double-dropping the value (a real
    use-after-free on a refcounted payload). Passing the param as a `move`
    clears the wrapper param's drop responsibility so the frame is the sole
    owner (dropped exactly once at frame teardown). Reference params never own,
    so they stay a plain borrow-forward.
    """
    from ast_nodes import MoveExpr as _Move
    if getattr(p.type, 'kind', None) == TypeKind.REFERENCE:
        return Identifier(name=p.name)
    return _Move(variable=p.name, path=None)


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
        # design 84: a method sub-frame's `__recv` in the DEAD (zero-init) state is a
        # null pointer — the frame is rebuilt with the real receiver address when its
        # call site is reached, so this placeholder is never dereferenced.
        zrecv = (CastExpr(expr=_int(0), target_type=sub_fb.recv_type)
                 if sub_fb.is_method else None)
        field_inits.append((c['sub'],
                            _build_frame_init(sub_fb, zvals, fbs, recv_value=zrecv)))
    for rc in getattr(fb, 'recv_calls', []):
        field_inits.append((f"__have{rc['idx']}", BoolLiteral(value=False)))
        if rc['target'] is None:
            field_inits.append((f"__rcv{rc['idx']}", NoneLiteral()))
    # design 103 (A6): each offloaded blocking call's `__blkjobN` handle starts 0
    # (no job yet — start writes the real handle when the call site is reached).
    for bc in getattr(fb, 'blk_calls', []):
        field_inits.append((f"__blkjob{bc['idx']}", _int(0)))
    field_inits.append(("__state", _int(0)))
    field_inits.append(("__wake", _int(0)))
    field_inits.append(("__io_tok", _int(0)))   # design 91: reactor wake-word address
    field_inits.append(("__cancel", BoolLiteral(value=False)))
    if not fb.is_void:
        field_inits.append(("__result", _zeroed_value(fb.result_enc, fb.ret)))
    return StructInit(struct_name=fb.frame_name, field_inits=field_inits)


def _make_entry_executor(fb: _FrameBuilder, fbs):
    """Synthesize the entry executor that replaces a suspending `main` (design 45
    item 1). It builds main's frame and drives it to completion on a single
    cooperative run: each Pending consults the frame's `__wake` reason and, for a
    `sleep(ms)`, parks the thread that long (`__saw_exec_sleep`) before resuming; a
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
    # design 76 (A4): a single-frame entry executor. wake > 0 => sleep; wake < 0
    # (IO-park) => block in the reactor until an fd is ready (there is no other
    # task or timer to honour, so the poll timeout is infinite / -1); wake == 0
    # (yield) => resume at once.
    io_poll = Block(statements=[ExpressionStatement(expression=IfExpr(
        condition=BinaryOp(op="<", left=MemberAccess(
            object=Identifier(name="__f"), member="__wake"), right=_int(0)),
        then_branch=Block(statements=[ExpressionStatement(expression=FunctionCall(
            name="__saw_rt_reactor_poll",
            arguments=[Argument(name=None, value=_int(-1))]))],
            final_expr=None)))], final_expr=None)
    pending_body = Block(statements=[ExpressionStatement(expression=IfExpr(
        condition=BinaryOp(op=">", left=wake, right=_int(0)),
        then_branch=Block(statements=[ExpressionStatement(expression=FunctionCall(
            name="__saw_exec_sleep",
            arguments=[Argument(name=None, value=MemberAccess(
                object=Identifier(name="__f"), member="__wake"))]))],
            final_expr=None),
        else_branch=io_poll))], final_expr=None)
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
                    is_synthesized=True,
                    source_file=getattr(fb.func, 'source_file', ""))


def _make_ambient_entry_executor(fb: _FrameBuilder, fbs):
    """design 89: the entry executor for a suspending `main` in a program that ALSO
    uses the cooperative scheduler (spawns). Instead of the design-45 single-frame
    loop (which drives ONLY main's frame — parking the whole thread while a spawned
    sibling starves), main's frame is boxed erased and handed to the std ambient
    entry executor `__exec_run_root`, which enqueues it as the root member of the
    shared scheduler and drives main AND every task it spawns to completion. This is
    what makes a spawn run eagerly whenever main parks (the core design-89 fix). A
    suspending main with NO spawn keeps the lighter single-frame executor above."""
    frame_init = _build_frame_init(fb, [], fbs)
    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    box_make = MethodCall(
        object=Identifier(name="Box", type_args=[box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=frame_init)])
    call = FunctionCall(name="__exec_run_root",
                        arguments=[Argument(name=None, value=box_make)])
    return Function(name="main", parameters=[], return_type=SawType(TypeKind.VOID),
                    body=Block(statements=[ExpressionStatement(expression=call)],
                               final_expr=None),
                    is_synthesized=True,
                    source_file=getattr(fb.func, 'source_file', ""))


def _make_driver(fb: _FrameBuilder, mode, fbs):
    """Synthesize the driver function that steps a frame to completion.

    value: `func __saw_drive_<f>(<params>) -> R { var __f = <frame>; loop resume; __f.__result }`
    steps: `func __saw_drive_steps_<f>(<params>) -> Int { ...; count Pendings; __n }`
    """
    params = fb.params
    # A method driver takes the receiver first, as an `UnsafePointer<Struct>`
    # (design 42's `&T`->pointer bridge is what the drive site supplies).
    recv_value = Identifier(name="__recv") if fb.is_method else None
    frame_init = _build_frame_init(
        fb, [_frame_param_arg(p) for p in params], fbs, recv_value=recv_value)

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
        driver_name = f"__saw_drive_steps_{fb.name}"
        ret = SawType(TypeKind.INT)
        final = Identifier(name="__n")
    else:
        driver_name = f"__saw_drive_{fb.name}"
        ret = fb.ret
        if fb.is_void:
            # design 102 item 1: a `Void` driven body has no `__result` slot —
            # the driver just loops to completion and returns Void.
            final = None
        else:
            result_acc = MemberAccess(object=Identifier(name="__f"), member="__result")
            # Reading the result CONSUMES the slot (opt-encoded: force-unwrap the
            # Some); an unconsumed result (e.g. driven only for its step count) stays
            # in the frame and is dropped once at frame death.
            final = ForceUnwrap(expr=result_acc) if _enc_unwraps(fb.result_enc) else result_acc

    # design 88: a reference param flows through the driver AS a raw pointer (the
    # drive site casts `&var x` -> `UnsafePointer<T>`), seeding the frame's pointer
    # field directly. Its inner type follows the reference (mutability preserved).
    driver_params = [Parameter(name=p.name,
                               type=(_ref_ptr_type(p.type)
                                     if fb.encmap.get(p.name) == "ref" else p.type))
                     for p in params]
    if fb.is_method:
        driver_params = [Parameter(name="__recv", type=fb.recv_type)] + driver_params
    return Function(name=driver_name, parameters=driver_params, return_type=ret,
                    body=Block(statements=stmts, final_expr=final),
                    is_synthesized=True,
                    source_file=getattr(fb.func, 'source_file', ""))


# --------------------------------------------------------------------------- #
# spawn lowering (design 52b item 2)
# --------------------------------------------------------------------------- #

def _reject_spawn_frame_refs(fb: _FrameBuilder, fbs):
    """design 88 (D6 confinement crux). A DRIVEN-in-place frame may hold a
    reference across a suspension: the driver seeds a pointer into a referent on
    the LIVE caller stack that outlives the whole drive. A SPAWNED frame cannot
    hold a reference INTO ITS SPAWNER: it is boxed onto the group's run queue and
    resumed later (possibly on another thread), by which time a reference into the
    spawner's stack could dangle. So a reference PARAMETER (or across-suspend
    reference local) of the SPAWN ROOT is a hard error, for BOTH single- and
    multi-threaded groups (confinement, not merely Send).

    Only the ROOT's own params/locals are checked — NOT embedded callee
    sub-frames. A nested suspending call's reference argument is rewritten to
    `&self.<field>` (a pointer into the TASK frame, which the box keeps alive as
    long as the task runs), so a reference into a task-confined local is sound and
    stays allowed (`read_into(&var buf)` inside a spawned handler works). Since
    references cannot be stored in owned values / escape, a nested callee can only
    ever receive a pointer into the task frame once the root carries no reference
    param — which this check guarantees."""
    for p in fb.params:
        if fb.encmap.get(p.name) == "ref":
            raise CoroTransformError(
                f"cannot spawn `{fb.func.name}`: parameter `{p.name}` of type "
                f"`{p.type}` is a reference into the spawner held across a "
                f"suspension. A spawned task's frame outlives the call that created "
                f"it, so a reference into the spawner's stack could dangle — "
                f"references are confined to their own task (D6). Pass an owned "
                f"value (`move`), or share via `Arc`/`Mutex`/`Channel`. (Driving the "
                f"function in place with `__saw_drive` DOES allow a held reference; a "
                f"reference to a task-LOCAL inside the spawned body is also fine.)",
                getattr(p, 'line', 0) or fb.func.line,
                getattr(p, 'column', 0) or fb.func.column,
                source_file=fb.src_file)
    for (lname, lt) in fb.frame_locals:
        if fb.encmap.get(lname) == "ref":
            raise CoroTransformError(
                f"cannot spawn `{fb.func.name}`: local `{lname}` of type `{lt}` "
                f"is a reference held across a suspension. A spawned task's frame "
                f"outlives its spawner, so a held reference could dangle — "
                f"references are confined to their own task (D6).",
                fb.func.line, fb.func.column, source_file=fb.src_file)


def _check_spawn_frame_send(fb: _FrameBuilder, fbs, typechecker):
    """Send-on-frames gate (design 75 A2). A frame spawned into a multi-threaded
    `TaskGroup(threads: N)` is stolen between suspensions by different worker
    threads, so every value it carries across a suspension — its parameters and
    its across-suspend locals, plus those of every embedded callee sub-frame — must
    be `Send`. Reject the FIRST non-Send value, naming it and its type, anchored at
    the spawned function (design 74 A8). D6 confinement still holds (a frame runs on
    one thread at a time); Send is what makes the between-suspension hand-off safe.

    Uses the same structural `is_send` predicate as the 21b `spawn { }` capture
    audit — `UnsafePointer` (and anything containing one, e.g. a bare `Vector`)
    poisons; `Int`/`Bool`/`Float`/`String`/`Arc`/`Mutex`/`Channel` pass."""
    ns = (getattr(typechecker, "_entry_module_ns", None)
          or getattr(typechecker, "namespace", None))
    if ns is None:
        return
    seen = set()

    def _check(fbx):
        if fbx.name in seen:
            return
        seen.add(fbx.name)
        for p in fbx.params:
            if not ns.is_send(p.type):
                raise CoroTransformError(
                    f"cannot spawn `{fbx.func.name}` into a multi-threaded "
                    f"`TaskGroup(threads: ...)`: parameter `{p.name}` of type "
                    f"`{p.type}` is not `Send`, so the task frame cannot cross to a "
                    f"worker thread. Share thread-safe state via `Arc` (and `Mutex` "
                    f"for mutation) or a `Channel` instead of moving it in.",
                    getattr(p, 'line', 0) or fbx.func.line,
                    getattr(p, 'column', 0) or fbx.func.column,
                    source_file=fbx.src_file)
        for (lname, lt) in fbx.frame_locals:
            if not ns.is_send(lt):
                raise CoroTransformError(
                    f"cannot spawn `{fbx.func.name}` into a multi-threaded "
                    f"`TaskGroup(threads: ...)`: local `{lname}` of type `{lt}` is "
                    f"held across a suspension but is not `Send`, so the task frame "
                    f"cannot cross to a worker thread.",
                    fbx.func.line, fbx.func.column, source_file=fbx.src_file)
        for c in fbx.calls:
            callee = fbs.get(c['callee'])
            if callee is not None:
                _check(callee)

    _check(fb)
    # The ROOT's result travels worker -> main across the `join()` barrier, so it
    # too must be Send (a callee sub-frame's result stays on one thread — not checked).
    if not fb.is_void and not ns.is_send(fb.ret):
        raise CoroTransformError(
            f"cannot spawn `{fb.func.name}` into a multi-threaded "
            f"`TaskGroup(threads: ...)`: its result type `{fb.ret}` is not `Send`, so "
            f"the value cannot travel back from the worker thread to `join()`.",
            fb.func.line, fb.func.column, source_file=fb.src_file)


def _make_spawn_helper(fb: _FrameBuilder, fbs):
    """Synthesize `__spawn_<f>(__group, <params>) -> TaskHandle<T>`.

    Build f's frame from the params, erase it into a `Box<any Resumable>`, capture
    raw pointers to the boxed frame's `__result` / `__cancel` slots (stable while
    the box lives in the group's queue — the fat pointer's data word never moves),
    enqueue the box, and return the typed handle:

        func __spawn_f(__group: UnsafePointer<TaskGroup>, <params>) -> TaskHandle<T> {
            var __box = Box<any Resumable>.make(__Frame_f(<params>...))
            let __data = __saw_box_data(&__box)
            let __fp   = __data as UnsafePointer<__Frame_f>
            let __rp   = (&__fp[0].__result) as UnsafePointer<T?>
            let __cp   = (&__fp[0].__cancel) as UnsafePointer<Bool>
            __group[0].__enqueue(move __box)
            TaskHandle<T>(result_ptr: __rp, cancel_ptr: __cp, group_ptr: __group)
        }

    The frame is a spawn root, so its `__result` is opt-encoded — `result_ptr` is
    `UnsafePointer<T?>` uniformly, and `join` takes with force-unwrap + `__saw_forget`.
    """
    from ast_nodes import StructInit
    T = fb.ret
    params = fb.params
    frame_init = _build_frame_init(fb, [_frame_param_arg(p) for p in params], fbs)

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

    # design 102 item 1: a `Void` spawn body has no `__result` field, so the
    # handle captures no result pointer — only the cancel word + slot.
    stmts = [
        LetStatement(name="__box", type_annotation=None, value=box_make, mutable=True),
        LetStatement(name="__data", type_annotation=None, mutable=False,
                     value=FunctionCall(name="__saw_box_data", arguments=[Argument(
                         name=None, value=ReferenceExpr(
                             expr=Identifier(name="__box"), mutable=False))])),
        LetStatement(name="__fp", type_annotation=None, mutable=False,
                     value=CastExpr(expr=Identifier(name="__data"),
                                    target_type=frame_ptr)),
    ]
    if not fb.is_void:
        stmts.append(
            LetStatement(name="__rp", type_annotation=None, mutable=False,
                         value=CastExpr(
                             expr=ReferenceExpr(expr=_fp_field("__result"), mutable=False),
                             target_type=SawType(TypeKind.POINTER, inner_type=_opt(T)))))
    stmts.extend([
        LetStatement(name="__cp", type_annotation=None, mutable=False,
                     value=CastExpr(
                         expr=ReferenceExpr(expr=_fp_field("__cancel"), mutable=False),
                         target_type=SawType(TypeKind.POINTER,
                                             inner_type=SawType(TypeKind.BOOL)))),
        LetStatement(name="__slot", type_annotation=None, mutable=False,
                     value=MethodCall(
                         object=ArrayIndex(array_expr=Identifier(name="__group"), index=_int(0)),
                         method_name="__enqueue",
                         arguments=[Argument(name=None, value=MoveExpr(variable="__box", path=None))])),
    ])
    if fb.is_void:
        handle = StructInit(
            struct_name="VoidTaskHandle", type_args=None,
            field_inits=[("cancel_ptr", Identifier(name="__cp")),
                         ("group_ptr", Identifier(name="__group")),
                         ("slot", Identifier(name="__slot"))])
        ret_type = SawType(TypeKind.STRUCT, struct_name="VoidTaskHandle")
        helper_params = [Parameter(name="__group", type=tg_ptr)] + \
                        [Parameter(name=p.name, type=p.type) for p in params]
        return Function(name=f"__spawn_{fb.name}", parameters=helper_params,
                        return_type=ret_type,
                        body=Block(statements=stmts, final_expr=handle),
                        is_synthesized=True,
                        source_file=getattr(fb.func, 'source_file', ""))
    handle = StructInit(
        struct_name="TaskHandle", type_args=[T],
        field_inits=[("result_ptr", Identifier(name="__rp")),
                     ("cancel_ptr", Identifier(name="__cp")),
                     ("group_ptr", Identifier(name="__group")),
                     ("slot", Identifier(name="__slot"))])
    ret_type = SawType(TypeKind.STRUCT, struct_name="TaskHandle", type_args=[T])
    helper_params = [Parameter(name="__group", type=tg_ptr)] + \
                    [Parameter(name=p.name, type=p.type) for p in params]
    return Function(name=f"__spawn_{fb.name}", parameters=helper_params,
                    return_type=ret_type,
                    body=Block(statements=stmts, final_expr=handle),
                    is_synthesized=True,
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
        call = FunctionCall(
            name=f"__spawn_{root}",
            arguments=[Argument(name=None, value=group_ptr)] + list(inner.arguments),
            line=node.line, column=node.column)
        # Carry the handle type so a suspending spawner can type the frame-resident
        # `let h = ...` binding (conservative-by-scope liveness reads it).
        call.resolved_type = getattr(node, 'resolved_type', None)
        return call
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

def _ref_arg_to_ptr(arg):
    """design 88 (D6): a reference argument `&x` / `&var x` at a drive site is
    passed to the driver AS a raw pointer into the referent's storage (the same
    &T->pointer bridge the method receiver uses). The driver seeds the frame's
    `UnsafePointer<T>` field from it, and the frame reads/mutates the caller's
    value through it across suspensions. A non-reference argument is unchanged."""
    rt = getattr(arg.value, 'resolved_type', None)
    if rt is None or rt.kind != TypeKind.REFERENCE:
        return arg
    ptr_type = SawType(TypeKind.POINTER, inner_type=rt.inner_type,
                       pointer_mutable=bool(rt.reference_mutable))
    return Argument(name=arg.name,
                    value=CastExpr(expr=arg.value, target_type=ptr_type))


def _rewrite_drive_sites(node, roots):
    """Rewrite `__saw_drive(f(args))` -> `__saw_drive_f(args)` and
    `__saw_drive_steps(f(args))` -> `__saw_drive_steps_f(args)` in place, everywhere."""
    if isinstance(node, FunctionCall) and node.name in ("__saw_drive", "__saw_drive_steps"):
        inner = node.arguments[0].value  # validated in the typechecker
        prefix = "__saw_drive_steps_" if node.name == "__saw_drive_steps" else "__saw_drive_"
        if isinstance(inner, MethodCall):
            # Part 0c: `__saw_drive(recv.m(args))` -> `__saw_drive_Struct_m((&var recv) as
            # UnsafePointer<Struct>, args)`. The receiver is passed as a raw
            # pointer into its own storage (design 42's &T->pointer bridge); the
            # frame mutates the caller's value through it (D6).
            recv_type = getattr(inner.object, 'resolved_type', None)
            struct_name = getattr(recv_type, 'struct_name', None)
            # design 74 (A5-rest, shape 2): preserve the receiver's type args so a
            # generic-struct receiver (`Holder<Int>`) casts to
            # `UnsafePointer<Holder<Int>>` — matching the frame's `__recv` pointee.
            recv_args = getattr(recv_type, 'type_args', None)
            ptr_type = SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.STRUCT,
                                                  struct_name=struct_name,
                                                  type_args=recv_args))
            recv_ptr = CastExpr(
                expr=ReferenceExpr(expr=inner.object, mutable=False),
                target_type=ptr_type)
            # design 95: name the driver by the resolved-signature frame key so an
            # overloaded method's driver matches its frame.
            node.name = prefix + _method_frame_key(
                struct_name, inner.method_name,
                getattr(inner, 'resolved_symbol', None))
            node.arguments = ([Argument(name=None, value=recv_ptr)]
                              + [_ref_arg_to_ptr(a) for a in inner.arguments])
            return node
        node.name = prefix + inner.name
        node.arguments = [_ref_arg_to_ptr(a) for a in inner.arguments]
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

def _iter_method_calls(node):
    """Yield every MethodCall node in an AST subtree (used to structurally discover
    nested suspending method callees whose effect node the main typechecker lacks —
    design 84 cross-module std methods)."""
    if isinstance(node, MethodCall):
        yield node
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if isinstance(v, (list, tuple)):
                for x in v:
                    if isinstance(x, Argument):
                        yield from _iter_method_calls(x.value)
                    elif isinstance(x, ASTNode):
                        yield from _iter_method_calls(x)
            elif isinstance(v, Argument):
                yield from _iter_method_calls(v.value)
            elif isinstance(v, ASTNode):
                yield from _iter_method_calls(v)


def _inline_static_refs(val, const_statics):
    """Rewrite bare `Identifier(name)` -> a deep copy of the imported static's
    const initializer, in place, throughout an AST subtree. Used so an embedded
    imported (std) method body that names a module-private static (e.g.
    `INVALID_FD`) resolves after being spliced into the entry module, where the
    imported static is not visible. `const_statics` maps name -> initializer AST."""
    import copy as _copy

    def _rw(v):
        if isinstance(v, Identifier) and v.name in const_statics:
            return _copy.deepcopy(const_statics[v.name])
        if isinstance(v, list):
            return [_rw(x) for x in v]
        if isinstance(v, tuple):
            return tuple(_rw(x) for x in v)
        if isinstance(v, Argument):
            v.value = _rw(v.value)
            return v
        if isinstance(v, ASTNode):
            for f in dataclasses.fields(v):
                setattr(v, f.name, _rw(getattr(v, f.name)))
            return v
        return v

    _rw(val)


def _find_method(program, struct_name, method_name, method_symbol=None):
    """Locate a driven method's AST and the extension that owns it.

    design 95: when the method name is overloaded, `method_symbol` (the resolved
    overload-mangled symbol) selects the exact overload — a name-only match would
    return whichever overload was declared first."""
    for ext in program.extensions:
        if getattr(ext, 'struct_name', None) != struct_name:
            continue
        for m in ext.methods:
            if m.name != method_name:
                continue
            if method_symbol is not None and \
                    getattr(m, 'mangled_symbol', None) != method_symbol:
                continue
            return m, ext
    return None, None


def _promote_nested_generic_calls(program, funcs_by_name, seed_names, typechecker):
    """design 74 (A5-rest, shape 3). Walk every driven body (and, transitively, the
    bodies of the concrete instantiations it pulls in) for a NESTED suspending
    generic call in a drivable position — a top-level or control-flow-body
    `let x = g<Args>(...)` / bare `g<Args>(...)`. For each whose instantiation
    suspends, splice the concrete instantiation into the AST (so it becomes an
    ordinary concrete callee with its own frame) and rewrite the call site to the
    mangled symbol with no type args. The existing Part-0b sub-frame embedding then
    handles it exactly like a nested non-generic suspending call.

    Only suspending instantiations are promoted; a non-suspending generic call is
    left for codegen's normal monomorphization. Idempotent per mangled symbol."""
    from codegen.mangle import mangle_function
    nodes = getattr(typechecker, "_suspend_nodes", {})
    splice = getattr(typechecker, "_splice_fn_mono", None)
    resolve = getattr(typechecker, "_resolve_type", None)
    if splice is None:
        return set()
    # Resolve type args + splice under the entry module's symbol scope (the
    # namespace was reset after check_module returned).
    entry_ns = getattr(typechecker, "_entry_module_ns", None)
    saved_ns = getattr(typechecker, "namespace", None)
    if entry_ns is not None:
        typechecker.namespace = entry_ns

    def instantiation_suspends(mangled):
        node = nodes.get(("fn", mangled))
        return node is not None and node.suspends

    def maybe_promote(fc):
        """If `fc` is a suspending generic free-function call, splice + rewrite it.
        Returns the mangled name of a newly-reachable callee body to scan, or None."""
        if not isinstance(fc, FunctionCall) or not getattr(fc, 'type_args', None):
            return None
        args = fc.type_args
        if resolve is not None:
            args = [resolve(a) for a in args]
        mangled = mangle_function(fc.name, args)
        if not instantiation_suspends(mangled):
            return None
        # Splice the concrete instantiation (idempotent by namespace presence).
        if mangled not in funcs_by_name:
            clone = splice(program, fc.name, list(args), mangled)
            if not clone:
                # No pristine template captured for this generic (e.g. a std
                # template checked under the separate builtin typechecker). A
                # USER-module template — including one in ANOTHER user module —
                # IS captured (the pristine map spans every module in the
                # compilation unit, design 104 item 2), so cross-module user
                # generics splice here. Leave the rest to `_classify_call`.
                return None
            funcs_by_name[mangled] = clone
        fc.name = mangled
        fc.type_args = None
        return mangled

    def scan_call_stmt(s):
        """A drivable nested-call position mirrors `_classify_call`: a top-level
        `let x = g(...)` or bare `g(...)`."""
        fc = None
        if isinstance(s, LetStatement) and isinstance(s.value, FunctionCall):
            fc = s.value
        elif (isinstance(s, ExpressionStatement)
              and isinstance(s.expression, FunctionCall)):
            fc = s.expression
        if fc is not None:
            return maybe_promote(fc)
        return None

    def scan_block(block, out):
        for s in block.statements:
            promoted = scan_call_stmt(s)
            if promoted is not None:
                out.append(promoted)
                continue
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                scan_block(ctrl.then_branch, out)
                if ctrl.else_branch is not None:
                    scan_block(ctrl.else_branch, out)
            elif isinstance(ctrl, IfLetExpr):
                scan_block(ctrl.then_branch, out)
                if ctrl.else_branch is not None:
                    scan_block(ctrl.else_branch, out)
            elif isinstance(ctrl, WhileExpr):
                scan_block(ctrl.body, out)
            elif isinstance(ctrl, MatchExpr):
                for arm in ctrl.arms:
                    if isinstance(arm.body, Block):
                        scan_block(arm.body, out)
            elif isinstance(s, ForLoop):
                scan_block(s.body, out)
            elif isinstance(s, GuardLetStatement):
                scan_block(s.else_branch, out)

    worklist = list(seed_names)
    scanned = set()
    promoted_all = set()
    while worklist:
        name = worklist.pop()
        if name in scanned:
            continue
        scanned.add(name)
        func = funcs_by_name.get(name)
        if func is None or getattr(func, 'body', None) is None:
            continue
        newly = []
        scan_block(func.body, newly)
        for m in newly:
            promoted_all.add(m)
        worklist.extend(newly)
    if entry_ns is not None:
        typechecker.namespace = saved_ns
    return promoted_all


def transform_program(program, typechecker, imported_ast=None):
    roots = dict(getattr(typechecker, "_driven_roots", {}) or {})
    method_roots = dict(getattr(typechecker, "_driven_method_roots", {}) or {})
    spawn_roots = dict(getattr(typechecker, "_spawn_roots", {}) or {})
    mt_spawn_roots = set(getattr(typechecker, "_mt_spawn_roots", set()) or set())
    funcs_by_name = {f.name: f for f in program.functions}
    # design 84: a nested suspending method may be defined in an IMPORTED module
    # (std.net's TcpStream.read / TcpListener.accept), not the entry module. The
    # transform is otherwise entry-module-only, but a NON-generic method frame is
    # self-contained (its resume is a fresh state machine on the frame struct,
    # spliced into the entry AST), so it can be embedded cross-module. `merge_programs`
    # shares method AST objects (list concat), so `id(method)` still matches the
    # effect nodes. The ORIGINAL method stays in its module as harmless dead code
    # (its calls were all rewritten to the embedded drive). Generic-struct / method-
    # generic methods stay unsupported (rejected at the call site).
    _entry_ext_ids = {id(e) for e in program.extensions}
    _imported_exts = ([e for e in getattr(imported_ast, 'extensions', [])
                       if id(e) not in _entry_ext_ids] if imported_ast is not None else [])
    _all_exts = list(program.extensions) + _imported_exts
    # design 45 item 1: a suspending `main` is auto-wrapped in an entry executor.
    main_suspends = (getattr(typechecker, "_main_suspends", False)
                     and "main" in funcs_by_name)
    if not roots and not method_roots and not spawn_roots and not main_suspends:
        return False

    # design 52b item 2: rewrite `group.spawn(f(args))` -> `__spawn_<f>(&group,
    # args)` FIRST, before any frame is built, so a spawner that is ITSELF
    # transformed (a suspending `main` holding the group in its own frame) has its
    # spawn sites lowered to plain calls before its body becomes a resume method.
    # `__spawn_<f>` is non-suspending, so it never triggers a suspension split.
    if spawn_roots:
        for f in program.functions:
            f.body = _rewrite_spawn_sites(f.body)
        for ext in program.extensions:
            for m in ext.methods:
                m.body = _rewrite_spawn_sites(m.body)

    # design 74 (A5-rest, shape 1): the set of (struct, method) whose body suspends
    # — used to detect a BURIED suspending method call in a driven body and reject
    # it cleanly (a user-anchored message naming the workaround) instead of letting
    # it lower in place and trip a confusing sync-violation on the synthesized
    # resume. Full method sub-frame embedding (the Part-0b method twin) is the
    # eventual lift; until then this is the honest rejection.
    _nodes_for_methods = getattr(typechecker, "_suspend_nodes", {})
    suspending_methods = set(getattr(typechecker, "_std_suspending_methods", set()))
    for ext in _all_exts:
        sname = getattr(ext, 'struct_name', None)
        for m in ext.methods:
            node = _nodes_for_methods.get(id(m))
            if node is not None and node.suspends:
                suspending_methods.add((sname, m.name))
    typechecker._suspending_methods_set = suspending_methods

    new_structs = []
    new_enums = []
    new_extensions = []
    new_functions = []
    removed = set()

    # The `__Poll` signal enum and the `Resumable` trait are declared in
    # builtin.saw (always in scope) — not synthesized here — so `Resumable` can
    # name `__Poll` and frames can conform to it for the erased run queue.
    nodes = getattr(typechecker, "_suspend_nodes", {})

    # design 74 (A5-rest, shape 3): promote NESTED suspending generic calls inside
    # driven bodies to concrete spliced callees BEFORE the closure walk, rewriting
    # each `g<Args>(...)` call site to its mangled instantiation. Runs after the
    # effect fixpoint (we can consult per-instantiation `.suspends`), so a
    # suspending instantiation becomes an ordinary concrete callee the existing
    # Part-0b sub-frame embedding handles. Non-suspending generic calls are left
    # untouched (codegen monomorphizes them normally).
    seed_names = list(roots.keys()) + list(spawn_roots.keys())
    if main_suspends:
        seed_names.append("main")
    promoted = _promote_nested_generic_calls(
        program, funcs_by_name, seed_names, typechecker)

    # The driven closure: every suspending entry-module free function reachable
    # from a driven root through suspending-call edges. Each becomes a frame +
    # resume method; a nested suspending call embeds the callee's frame by value
    # and drives it (Part 0b). Only the roots themselves also get __saw_drive_*
    # drivers. Promoted nested-generic instantiations (shape 3) are seeded
    # directly — the effect edges reference the TEMPLATE, so the walk alone would
    # not reach them.
    # design 84: a nested suspending METHOD call embeds the callee METHOD's frame
    # (with a `__recv` pointer into the receiver's caller-frame storage). Effect
    # edges to a method are keyed by `id(Method)`, so map every method AST to its
    # (struct, method, extension) to follow those edges and build the frames.
    methods_by_id = {}
    # design 95: keyed by the resolved-signature FRAME KEY (not (struct, name)),
    # so two overloads of the same method name each map to their OWN AST — a
    # name-only key collapsed them (second overwrote first → mis-resolution).
    methods_by_key = {}   # frame_key -> id(method) — for the body scan
    for ext in _all_exts:
        sname = getattr(ext, 'struct_name', None)
        for m in ext.methods:
            methods_by_id[id(m)] = (sname, m, ext)
            methods_by_key[_method_frame_key(
                sname, m.name, getattr(m, 'mangled_symbol', None))] = id(m)
    # design 95: `method_roots` is keyed by the resolved-signature frame key.
    method_root_keys = set(method_roots.keys())
    _susp_methods_set = typechecker._suspending_methods_set

    def _scan_method_callees(body):
        """Enqueue every nested suspending METHOD call in `body` (a std method's
        effect node does not exist in the main typechecker, so the edge walk cannot
        reach it — discover it structurally instead). Returns (method-id) work items."""
        out = []
        for mc in _iter_method_calls(body):
            if getattr(mc, 'is_chan_recv', False):
                continue
            rt = getattr(mc.object, 'resolved_type', None)
            sn = getattr(rt, 'struct_name', None) if rt else None
            if sn is None or getattr(rt, 'type_args', None):
                continue
            if (sn, mc.method_name) in _susp_methods_set:
                # design 95: resolve the exact overload's frame via its resolved
                # signature so a call to `write(String)` finds the String frame,
                # not whichever `write` was registered last.
                mid = methods_by_key.get(_method_frame_key(
                    sn, mc.method_name, getattr(mc, 'resolved_symbol', None)))
                if mid is not None:
                    out.append(("method", mid))
        return out

    # design 96: the effect fixpoint cannot see suspension that arises SOLELY from
    # a nested std METHOD call — a std method's effect node is absent (the same gap
    # `_scan_method_callees` works around), so a call edge to it never propagates
    # `suspends`. A FREE function whose only suspension source is a buried
    # suspending method call is therefore left `suspends=False`; the edge-follow in
    # the closure walk below would SKIP the edge to it, its caller would emit a
    # PLAIN blocking call, and the buried park would wedge the whole single thread
    # (the design-96 hang at nesting depth >= 2 — a method call one or more free
    # frames below a root). Close the gap structurally: a free fn STRUCTURALLY
    # suspends if its body calls a suspending method directly (`_scan_method_callees`
    # non-empty), or reaches — through free-fn -> free-fn call edges — a fn that
    # does. Seed the edge-follow with this set so such fns join the closure, get
    # frames, and are embedded+driven (their internal park integrates with the
    # executor) instead of blocking the thread. Only ADDS genuinely-suspending fns
    # (`_scan_method_callees` never yields a non-suspending method), so no over-
    # inclusion; a fn the fixpoint already marks stays followed via `t.suspends`.
    structurally_susp_fns = set()
    for _fname, _f in funcs_by_name.items():
        if getattr(_f, 'type_params', None):
            continue
        if _scan_method_callees(_f.body):
            structurally_susp_fns.add(_fname)
    _susp_changed = True
    while _susp_changed:
        _susp_changed = False
        for _key, _nd in nodes.items():
            if not (isinstance(_key, tuple) and _key[0] == "fn"):
                continue
            _fname = _key[1]
            if _fname in structurally_susp_fns or _fname not in funcs_by_name:
                continue
            for _e in _nd.edges:
                _tgt = _e.target
                if (isinstance(_tgt, tuple) and _tgt[0] == "fn"
                        and _tgt[1] in structurally_susp_fns):
                    structurally_susp_fns.add(_fname)
                    _susp_changed = True
                    break

    closure = []
    method_closure = {}   # id(method) -> (struct_name, method_ast, extension)
    seen = set()
    work = [("fn", n) for n in (list(seed_names) + list(promoted))]
    while work:
        kind, key = work.pop()
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        if kind == "fn":
            func = funcs_by_name.get(key)
            if func is None:
                raise CoroTransformError(
                    f"coroutine transform: suspending function `{key}` not found in "
                    f"the entry module (driving supports entry-module free functions "
                    f"only)")
            if func.type_params:
                # design 74 (A5-rest, shape 3): a GENERIC template reached via an
                # effect edge (the edge references the template, not the
                # instantiation). Its SUSPENDING instantiations were promoted to
                # concrete spliced callees and seeded directly, so the template
                # itself needs no frame — skip it. A nested generic call the
                # promotion could NOT handle (e.g. cross-module, shape 4) keeps its
                # generic AST call and is rejected — with a workaround and a
                # user-anchored line — by `_classify_call` when its caller lowers.
                continue
            closure.append(key)
            work.extend(_scan_method_callees(func.body))
            node = nodes.get(("fn", key))
        else:  # a nested suspending method callee
            entry = methods_by_id.get(key)
            if entry is None:
                continue
            sname, mast, ext = entry
            fbkey = _method_frame_key(
                sname, mast.name, getattr(mast, 'mangled_symbol', None))
            # A method-level or generic-struct generic, or one already driven
            # directly (a method root), is not embedded here — the call site is
            # rejected cleanly by `_reject_suspending_method_call`.
            if (getattr(mast, 'type_params', None)
                    or getattr(ext, 'type_params', None)
                    or fbkey in method_root_keys):
                continue
            method_closure[key] = (sname, mast, ext)
            if getattr(mast, 'body', None) is not None:
                work.extend(_scan_method_callees(mast.body))
            node = nodes.get(id(mast))
        if node is not None:
            for e in node.edges:
                t = nodes.get(e.target)
                if t is None:
                    continue
                is_fn_edge = (isinstance(e.target, tuple) and e.target[0] == "fn"
                              and e.target[1] in funcs_by_name)
                # design 96: follow a free-fn edge whose target the fixpoint left
                # `suspends=False` but which STRUCTURALLY suspends via a buried
                # method call (see `structurally_susp_fns` above) — otherwise a
                # depth-2+ nested suspending method call is missed and its park
                # wedges the thread.
                if not t.suspends and not (
                        is_fn_edge and e.target[1] in structurally_susp_fns):
                    continue
                if is_fn_edge:
                    work.append(("fn", e.target[1]))
                elif isinstance(e.target, int) and e.target in methods_by_id:
                    work.append(("method", e.target))

    for root_name in roots:
        _analyze_nesting(root_name, funcs_by_name[root_name], nodes)

    # Phase 1: build every frame's layout (so a caller can embed a callee frame
    # by value). Phase 2: generate every resume state machine.
    suspends_set = set(closure)
    fbs = {n: _FrameBuilder(funcs_by_name[n], tc=typechecker,
                            force_opt_result=(n in spawn_roots))
           for n in closure}
    # design 84: frame builders for nested suspending method callees, keyed by
    # the resolved-signature frame key (design 95, matching `_FrameBuilder.name`)
    # so a nested method-call site resolves `fbs[callee]` and embeds the RIGHT
    # overload's `__Frame_...`.
    nested_method_fbs = []   # (key, extension, method_ast)
    for mid, (sname, mast, ext) in method_closure.items():
        fbkey = _method_frame_key(
            sname, mast.name, getattr(mast, 'mangled_symbol', None))
        if fbkey in fbs:
            continue
        fbs[fbkey] = _FrameBuilder(mast, struct_name=sname, tc=typechecker)
        nested_method_fbs.append((fbkey, ext, mast))
    # Prepare ALL layouts (fn + method) before generating any resume, so a caller
    # (fn or method) can embed a fully-known callee frame by value.
    for n in closure:
        new_structs.append(fbs[n].prepare(suspends_set))
    for fbkey, _ext, _mast in nested_method_fbs:
        new_structs.append(fbs[fbkey].prepare(suspends_set))
    for n in closure:
        _, resume_ext = fbs[n].build_resume(fbs)
        new_extensions.append(resume_ext)
    for fbkey, _ext, _mast in nested_method_fbs:
        _, resume_ext = fbs[fbkey].build_resume(fbs)
        new_extensions.append(resume_ext)
    for root_name, modes in roots.items():
        for mode in modes:
            new_functions.append(_make_driver(fbs[root_name], mode, fbs))
        removed.add(root_name)
    # design 52b item 2: each spawn root gets a `__spawn_<f>` helper that boxes
    # its frame, enqueues it on the group, and returns the typed handle.
    for root_name in spawn_roots:
        # design 88 (D6 confinement): a spawned frame may NOT hold a reference
        # across a suspension (the referent could outlive into a dead spawner
        # stack). Reject any reference param/across-suspend local — both group
        # kinds — BEFORE the Send gate (Send is the multi-thread hand-off rule;
        # confinement is the deeper single-thread-too rule).
        _reject_spawn_frame_refs(fbs[root_name], fbs)
        # design 75 (A2): a frame spawned into a multi-threaded group crosses OS
        # threads between suspensions — gate every across-suspend live value on Send.
        if root_name in mt_spawn_roots:
            _check_spawn_frame_send(fbs[root_name], fbs, typechecker)
        new_functions.append(_make_spawn_helper(fbs[root_name], fbs))
        removed.add(root_name)
    removed.update(closure)
    if main_suspends:
        # `main` keeps its name but becomes the entry executor driving its own
        # frame (not a __saw_drive_* driver). It is in `removed` (the original body is
        # now __Frame_main.resume), so the executor is re-added under `main`.
        # design 89: if the program ALSO spawns, route through the ambient scheduler
        # (main becomes the root member) so a spawned sibling runs whenever main
        # parks; otherwise keep the design-45 single-frame executor.
        if spawn_roots:
            new_functions.append(_make_ambient_entry_executor(fbs["main"], fbs))
        else:
            new_functions.append(_make_entry_executor(fbs["main"], fbs))

    # Part 0c: driven suspending methods. Each becomes a frame that holds a
    # `__recv` pointer into the receiver's storage; the method body's `self` is
    # rewritten to `self.__recv[0]`. Driven directly (no method embedding yet).
    removed_methods = []  # (extension, method) to strip after generation
    # design 84: an ENTRY-MODULE nested-embedded suspending method's original body
    # is replaced by its frame + resume — strip it. An IMPORTED (std) method stays
    # in its module as dead code (its call sites were rewritten to the embedded
    # drive; it re-parses fresh on the recursive pass anyway, so stripping the shared
    # object would not persist).
    for _fbkey, ext, mast in nested_method_fbs:
        if id(ext) in _entry_ext_ids:
            removed_methods.append((ext, mast))
    gsm = getattr(typechecker, "_driven_generic_struct_methods", {}) or {}
    for frame_key, info in method_roots.items():
        # design 95: `method_roots` is keyed by the resolved-signature frame key;
        # `info` carries the struct/method/overload-symbol/modes.
        struct_name = info['struct']
        method_name = info['method']
        method_symbol = info['symbol']
        modes = info['modes']
        # design 74 (A5-rest, shape 2): a driven method on a GENERIC struct is
        # monomorphized by the typechecker into a concrete clone (keyed by a
        # per-instantiation name) carrying the concrete receiver type. Use it
        # directly — it is NOT spliced onto an extension (its `self` is
        # `Holder<Int>`, unexpressible on a plain extension), so `_find_method`
        # won't see it. The frame's `__recv` points at `Holder<Int>`.
        gsm_entry = gsm.get((struct_name, method_name))
        if gsm_entry is not None:
            recv_saw_type, method_ast = gsm_entry
            if method_ast is None:
                raise CoroTransformError(
                    f"coroutine transform: driven generic-struct method "
                    f"`{struct_name}.{method_name}` was not monomorphized")
            mfb = _FrameBuilder(method_ast, struct_name=struct_name, tc=typechecker,
                                recv_saw_type=recv_saw_type)
            new_structs.append(mfb.prepare(suspends_set))
            _, resume_ext = mfb.build_resume(fbs)
            new_extensions.append(resume_ext)
            for mode in modes:
                new_functions.append(_make_driver(mfb, mode, fbs))
            continue
        # design 95: disambiguate an overloaded method by its resolved symbol.
        method_ast, ext = _find_method(program, struct_name, method_name,
                                       method_symbol)
        if method_ast is None:
            raise CoroTransformError(
                f"coroutine transform: driven method `{struct_name}.{method_name}` "
                f"not found in the entry module")
        if method_ast.type_params or getattr(ext, 'type_params', None):
            # A method-level generic method is monomorphized by the typechecker to a
            # concrete method before it reaches here, and a generic-struct method is
            # handled by the `gsm` table above. A template surviving to this point is
            # an unexpected shape — reject cleanly rather than miscompile.
            raise CoroTransformError(
                f"coroutine transform: driving a suspending method on a generic "
                f"struct (`{struct_name}.{method_name}`) is not yet supported "
                f"(design 74 A5-rest); monomorphize the receiver at the drive site",
                method_ast.line, method_ast.column,
                source_file=getattr(method_ast, 'source_file', None))
        mfb = _FrameBuilder(method_ast, struct_name=struct_name, tc=typechecker)
        new_structs.append(mfb.prepare(suspends_set))
        _, resume_ext = mfb.build_resume(fbs)
        new_extensions.append(resume_ext)
        for mode in modes:
            new_functions.append(_make_driver(mfb, mode, fbs))
        removed_methods.append((ext, method_ast))

    # Rewrite all `__saw_drive(...)` sites across the entry module's function and
    # method bodies to call the synthesized drivers.
    for f in program.functions:
        _rewrite_drive_sites(f.body, roots)
    for ext in program.extensions:
        for m in ext.methods:
            _rewrite_drive_sites(m.body, roots)


    # Strip driven methods from their extensions (replaced by frame + resume).
    for ext, method_ast in removed_methods:
        ext.methods = [m for m in ext.methods if m is not method_ast]

    # design 84/89: an embedded imported (std) method body may reference a
    # module-level `static` private to its own module (e.g. `TcpListener.accept`
    # names `INVALID_FD`). The transform splices that method into the ENTRY module,
    # which is then re-typechecked under the entry namespace — where the imported
    # static is NOT visible (imported free functions ARE, but statics are not; the
    # standing cross-module-static limitation). Statics are const-initialized, so
    # inline the referenced imported static's initializer at the reference sites in
    # the synthesized declarations. Only imported statics NOT shadowed by an
    # entry-module static of the same name are inlined, keeping this precise.
    if imported_ast is not None:
        entry_static_names = {s.name for s in program.statics}
        const_statics = {s.name: s.initializer
                         for s in getattr(imported_ast, 'statics', [])
                         if s.initializer is not None
                         and s.name not in entry_static_names}
        if const_statics:
            for decl in list(new_extensions) + list(new_functions) + list(new_structs):
                _inline_static_refs(decl, const_statics)

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True

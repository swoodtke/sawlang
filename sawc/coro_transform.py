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
    GuardLetStatement, TryExpr, TryCatchExpr,
    Function, Struct, StructField, Enum, EnumVariant, Extension, Method,
    Parameter, SawType, TypeKind, Visibility, ClosureExpr, CaptureSpec,
    DestructuringLet, TuplePattern, BindingPattern, WildcardPattern, TupleIndex,
    EnumPattern,
    StringInterpolation, ArrayLiteral, MapLiteral, SetLiteral, StructInit,
    TupleLiteral, NilCoalesce, OptionalChain, BindOptional,
    OptionalEvalExpr, OptionalChainAssign, OptionalWrap,
    structural_fields,
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


def _is_never_expr(expr) -> bool:
    """Does this expression DIVERGE — `panic(...)`, a `-> Never` call, a
    break-less `while {}` (design 177)?

    The typechecker stamps `Never` on all three, and a diverging expression
    produces no value: there is nothing to store into a frame's `__result`, and
    trying to store it hands codegen a Python `None` (DF-158a)."""
    t = getattr(expr, 'resolved_type', None)
    return t is not None and t.kind == TypeKind.NEVER


def _self_field(name, line=0, column=0):
    return MemberAccess(object=SelfExpr(line=line, column=column),
                        member=name, line=line, column=column)


def _int(n):
    return IntLiteral(value=n)


def _poll(variant):
    return EnumInit(enum_name="__Poll", variant_name=variant, arguments=[])


# The suspension-boundary intrinsics: `__saw_suspend` (test-only synthetic), and the
# real primitives `yield_now()` (immediately re-ready) and `sleep(d)` (timed).
_SUSPEND_CALLS = ("__saw_suspend", "yield_now", "sleep", "__saw_io_park", "io_wait")

# design 76 (A4): the IO-park wake reason. A negative sentinel distinct from the
# `sleep(d)` (>0) and yield/channel-retry (0) reasons: the executor parks in the
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
    and read by the executor after a Pending: NANOSECONDS for `sleep(d)`, else
    0 (`__saw_suspend`/`yield_now` — immediately re-ready).

    design 180: `sleep` takes a `Duration`, and the wake word is a plain Int, so
    the span is projected through `__saw_wake_nanos` (std/duration.saw) — which
    is also where the saturation at the executor's schedulable horizon is
    written down. The transformed AST is re-typechecked, so this is an ordinary
    call and needs no special handling downstream."""
    fc = stmt.expression
    if fc.name == "sleep":
        return FunctionCall(name="__saw_wake_nanos",
                            arguments=[Argument(name=None,
                                                value=fc.arguments[0].value)])
    if fc.name == "__saw_io_park":
        return _int(IO_PARK_WAKE)
    return _int(0)


# --------------------------------------------------------------------------- #
# design 127 — loop-backedge preemption (RC-3)
# --------------------------------------------------------------------------- #

# Iterations a driven/spawned frame may run between forced cooperative yields.
# Matches the design-89-c io op budget (`sawc/rt/common/op_budget.saw`): the two
# are the same fairness knob applied to the two ways a task can fail to cede —
# always-ready io ops (89-c, charged in std's io primitives against a
# process-global counter) and a pure-compute loop (127, charged here against a
# per-frame counter). Op-count, never a clock, so interleaving stays
# deterministic.
LOOP_BUDGET_DEFAULT = 128

# The synthesized per-frame iteration counter. A `__saw_`-prefixed name cannot
# collide with a user binding (the lexer reserves the prefix for the compiler),
# and it is an ordinary Int local, so the existing frame-local collection makes
# it a frame field with no special-casing anywhere downstream.
BUDGET_LOCAL = "__saw_loop_budget"

# --------------------------------------------------------------------------- #
# DF-151a — alpha-renaming support
# --------------------------------------------------------------------------- #

# Prefix for a binding `_uniquify_bindings` renamed. `__saw_`-prefixed names are
# reserved for the compiler by the lexer, so a renamed binding can never collide
# with a user one; the original name is kept as a suffix so the frame field, and
# any diagnostic naming it, still reads recognizably.
_UNIQ_PREFIX = "__saw_u"


def _pattern_binding_nodes(pattern):
    """Every `BindingPattern` LEAF of a pattern, in source order. Returns the
    nodes (not the names) so a caller can rename them in place. Literal, range
    and wildcard patterns bind nothing."""
    out = []

    def walk(pat):
        if isinstance(pat, BindingPattern):
            out.append(pat)
        elif isinstance(pat, TuplePattern):
            for sub in pat.elements:
                walk(sub)
        elif isinstance(pat, EnumPattern):
            for sub in pat.subpatterns:
                walk(sub)

    walk(pattern)
    return out


def _is_function_valued(let_stmt):
    """Does this `let` bind a callable? Only such a binding may appear as a
    `FunctionCall.name` (design 77 item 4), so only such a binding's rename has
    to reach call sites."""
    if isinstance(let_stmt.value, ClosureExpr):
        return True
    for t in (let_stmt.type_annotation,
              getattr(let_stmt.value, 'resolved_type', None)):
        if t is not None and t.kind == TypeKind.FUNCTION:
            return True
    return False


def _budget_check_stmts(budget, line, column):
    """The per-iteration check, spelled as ordinary Saw the rest of the transform
    already knows how to split:

        __saw_loop_budget = __saw_loop_budget &- 1
        if __saw_loop_budget <= 0 {
            __saw_loop_budget = <budget>
            yield_now()
        }

    The `yield_now()` carries wake reason 0 (ready), so the scheduler re-queues
    the task at the back of the run queue and round-robin continues — the same
    park path an explicit `yield_now()` takes, not a new one.

    The decrement is the WRAPPING `&-`: the counter is reset the moment it
    reaches 0, so it can never approach `Int.min`, and a checked `-` would spend
    an `llvm.ssub.with.overflow` plus a panic branch per iteration on a case that
    cannot arise."""
    def counter():
        return Identifier(name=BUDGET_LOCAL, line=line, column=column)

    dec = AssignStatement(
        target=counter(),
        value=BinaryOp(op="&-", left=counter(), right=_int(1),
                       line=line, column=column),
        line=line, column=column)
    reset = AssignStatement(target=counter(), value=_int(budget),
                            line=line, column=column)
    yielded = ExpressionStatement(
        expression=FunctionCall(name="yield_now", arguments=[],
                                line=line, column=column),
        line=line, column=column)
    check = ExpressionStatement(
        expression=IfExpr(
            condition=BinaryOp(op="<=", left=counter(), right=_int(0),
                               line=line, column=column),
            then_branch=Block(statements=[reset, yielded], final_expr=None),
            else_branch=None, line=line, column=column),
        line=line, column=column)
    return [dec, check]


def _instrument_loop_backedges(func, budget=LOOP_BUDGET_DEFAULT):
    """design 127 (RC-3): charge every loop iteration in `func`'s body against a
    frame-resident budget and force a cooperative yield when it runs out, so a
    pure-compute loop cannot starve its siblings on the single ambient scheduler.

    The check goes at the TOP of each loop body rather than after its last
    statement. Both spellings run once per iteration, but the top placement also
    covers a `continue` — a `while c { ...; continue }` would jump straight over
    a trailing check and never cede.

    Two subtrees are skipped, and both are documented bounds rather than
    oversights:

    * A CLOSURE body. It is not part of this frame's state machine, so a
      `yield_now()` there lowers to a codegen no-op and would buy nothing.
    * A `for` over a NON-RANGE iterable (`for x in v.iter()`), and everything
      nested inside it. `_split_for` can only state-split a range `for`; a
      suspension anywhere inside a collection `for` is a clean rejection
      (`use a `while` loop`). Instrumenting one would turn working programs into
      compile errors, so such a loop — and any loop nested in it — stays
      unpreempted. Rewrite the loop as a `while` over an index to get the check.

    Returns True when at least one loop was instrumented (the caller then knows
    the counter declaration was added). A loop-free body is left byte-identical.
    """
    found = []

    def visit_val(v):
        if isinstance(v, list):
            for item in v:
                visit_val(item)
        elif isinstance(v, ASTNode):
            visit(v)

    def visit(node):
        if isinstance(node, ClosureExpr):
            return
        if isinstance(node, ForLoop) and not isinstance(node.iterable, RangeExpr):
            return
        if isinstance(node, (WhileExpr, ForLoop)):
            found.append(node)
            node.body.statements[:0] = _budget_check_stmts(
                budget, node.line, node.column)
        for f in structural_fields(node):
            visit_val(getattr(node, f.name))

    visit(func.body)
    if not found:
        return False
    func.body.statements.insert(0, LetStatement(
        name=BUDGET_LOCAL, type_annotation=SawType(TypeKind.INT),
        value=_int(budget), mutable=True,
        line=func.line, column=func.column))
    return True


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

def _read_field(name, encoding, line=0, column=0, owning_read=False,
                move_read=False):
    """The rewritten read of frame field `name`.

    `owning_read` marks a read of the WHOLE binding that is not a `move` — the
    frame keeps the field (and its drop flag), so if the read lands in a transfer
    position the new owner must take its own reference. Codegen cannot see that
    through the `!`: `self.name!` is a ForceUnwrap, and the ownership checkpoint
    only recognizes bare place expressions (Identifier/MemberAccess/…), so the
    transfer took a non-retaining alias AND left the field's flag set. Before
    design 124 that stayed hidden — the frame outlived every reader — but with
    eager teardown the field is released at task completion and the alias
    dangles. `frame_owning_read` tells `_transfer_needs_copy` to apply the same
    read-out-of-storage discipline the closure-capture materialization already
    spells with `.copy()`. A `move` read does NOT carry it: that path records a
    `__saw_forget`, which transfers the frame's own reference instead.

    `move_read` marks the opposite case: the frame hands its own reference over
    through the paired `__saw_forget`, so the read is a transfer even for a
    NoCopy payload.

    EVERY node this returns is additionally stamped `frame_place_read` (design
    131). The transform rewrites a local into a projection of the frame — a
    MemberAccess, a `self.name!`, a pointer deref — and the language's place rule
    would then re-judge, as an ordinary read out of somebody else's storage, a
    read whose ownership the transform has ALREADY settled on the pre-transform
    AST (which the typechecker saw, and annotated, as the plain local it was).
    Judging it twice would double-retain an ImplicitCopy payload and reject a
    NoCopy one that the frame is legitimately moving out."""
    acc = _self_field(name, line, column)
    acc.frame_place_read = True
    if encoding in ("opt", "opt_closure"):
        fu = ForceUnwrap(expr=acc, line=line, column=column)
        fu.frame_place_read = True
        if owning_read:
            fu.frame_owning_read = True
        if move_read:
            fu.frame_move_read = True
        return fu
    if encoding == "ref":
        # design 88 (D6): the reference name reads through the frame's pointer
        # field — `self.name[0]` — yielding an lvalue of the pointee type. Member
        # access, compound-assignment mutation, and method calls on it all flow
        # normally (the identical `self.__recv[0]` receiver rewrite of design 45 0c).
        deref = ArrayIndex(array_expr=acc, index=_int(0), line=line, column=column)
        deref.frame_place_read = True
        return deref
    return acc


def _sub_result_read(sub: str, result_enc):
    """The read that moves a completed sub-frame's `__result` out of its slot.

    Paired at every call site with a `__saw_forget` on the same slot, which is
    what makes this a TRANSFER rather than a duplication: the sub-frame gives up
    its reference and this frame takes it. Stamped `frame_place_read` for the
    same reason every other frame projection is (design 131) — the ownership is
    already settled here, so the language's place rule must not re-judge it and
    charge a second retain.

    Design 139 is what made the omission visible. While `Result<T, E>` had no
    copy tier, an unstamped read of an owning result fell through to the
    catch-all 'retain' and codegen bumped a refcount the paired `__saw_forget`
    then dropped — a leak that no test could see. Once `Result<Data, IoError>`
    became move-only the same read turned into a hard error instead.
    """
    read = MemberAccess(object=_self_field(sub), member="__result")
    read.frame_place_read = True
    if _enc_unwraps(result_enc):
        read = ForceUnwrap(expr=read)
        read.frame_place_read = True
    return read


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
        for f in structural_fields(node):
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

def _method_call_owner(mc):
    """The name of the type whose method `mc` calls — the key half of a
    suspending method's frame identity — or None when the call is not a shape
    the transform can embed.

    DF-184a: there are TWO shapes, and only one of them used to be read here. An
    INSTANCE call carries its owner on the RECEIVER (`recv.m()`, so
    `mc.object.resolved_type.struct_name`); a STATIC one has no receiver at all,
    so the typechecker stamps the owner on the CALL. Keying off the receiver
    alone meant a suspending static method was never discovered, never embedded,
    and — for an entry-module one, whose original body IS stripped once the
    closure walk reaches it through the effect edge — left a call to a method
    that no longer existed.

    A GENERIC receiver is excluded from both shapes: a value with type args
    (`Holder<Int>`), or a type name written with them (`Vector<Int>.make()`).
    The frame's `__recv` pointee / the callee's mangling would need the
    instantiation, so the call site is rejected cleanly downstream instead.
    """
    rt = getattr(mc.object, 'resolved_type', None)
    sn = getattr(rt, 'struct_name', None) if rt else None
    if sn is not None:
        return None if getattr(rt, 'type_args', None) else sn
    if not getattr(mc, 'is_static_method_call', False):
        return None
    if getattr(mc.object, 'type_args', None):
        return None
    return getattr(mc, 'static_receiver', None)


def _method_call_is_static(mc):
    """DF-184a: True if `mc` is a STATIC method call — no receiver to embed, so
    its frame carries no `__recv` and its body has no `self` to rewrite."""
    return bool(getattr(mc, 'is_static_method_call', False))


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


def _cell_type(fb):
    """design 134: the group-owned cell type for a spawn-root frame —
    `__ResultCell<T>` for a value body, `__VoidCell` for a `Void` one (which has
    no result slot to carry). Both conform to `__TaskCell`, so the group holds
    them erased and the box teardown runs the right destructor."""
    if fb.is_void:
        return SawType(TypeKind.STRUCT, struct_name="__VoidCell")
    return SawType(TypeKind.STRUCT, struct_name="__ResultCell",
                   type_args=[fb.ret])


def _cell_ptr_type(fb):
    return SawType(TypeKind.POINTER, inner_type=_cell_type(fb))


def _body_arms_io(body):
    """True if `body` contains a literal `io_wait(fd, dir)` call (DF-134a).

    That call is the only thing that ARMS a reactor registration, and the
    registration carries a token pointing into the frame — so the frame that
    made it is the frame that must be able to drop it. A frame that only embeds
    a suspending callee arms nothing itself; the callee's frame owns its own.
    """
    found = [False]

    def scan(n):
        if found[0]:
            return
        if isinstance(n, FunctionCall) and n.name == "io_wait":
            found[0] = True
            return
        if isinstance(n, ASTNode):
            for f in structural_fields(n):
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

    scan(body)
    return found[0]


class _FrameBuilder:
    def __init__(self, func, struct_name=None, tc=None, is_spawn_root=False,
                 recv_saw_type=None):
        # design 52b item 2: a spawn-root frame forces its result opt-encoded
        # even for a POD return, so `TaskHandle<T>` uniformly holds a
        # `UnsafePointer<T?>` and `join` takes the value with the same
        # force-unwrap + `__saw_forget` handoff regardless of T.
        #
        # design 134: a spawn-root frame ALSO keeps neither the result nor the
        # cancel word itself. Both live in the group-owned cell the frame reaches
        # through `__cellp`, which is what lets the frame box be released the
        # moment the task completes: nothing outside the frame points INTO it.
        self.is_spawn_root = is_spawn_root
        self.force_opt_result = is_spawn_root
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
        # DF-184a: a STATIC method owns a frame exactly like an instance one —
        # same key, same display name, same embedding — but there is no receiver
        # to point at, so it carries no `__recv` field, its driver takes no
        # receiver argument, and there is no `self` in its body to rewrite.
        # `is_method` says "this frame belongs to a type"; `has_recv` says "this
        # frame reaches a receiver through a pointer", and those are no longer
        # the same question.
        self.is_static_method = bool(getattr(func, 'is_static', False))
        self.has_recv = self.is_method and not self.is_static_method
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
            self.recv_type = (SawType(TypeKind.POINTER, inner_type=pointee)
                              if self.has_recv else None)
        else:
            self.name = func.name
            self.recv_type = None
        self.frame_name = f"__Frame_{self.name}"
        # design 158: the name a logical backtrace frame PRINTS. The frame key is
        # a mangled monomorphization symbol; a reader wants the source spelling,
        # so a method reads `Struct.method` and a function reads its own name.
        self.display_name = (f"{struct_name}.{func.name}" if self.is_method
                             else func.name)
        # design 158: state index -> the SOURCE LINE a frame parked at that state
        # is logically stopped on. Filled during the CFG walk — `_suspend_to`
        # records the suspending statement's line against the state it resumes
        # into (which is the state a parked frame's `__state` word holds), and
        # `_emit_nested_call` records the CALL's line against the drive state.
        # Together those are exactly the two things a backtrace frame can be.
        self._state_lines = {}
        # The line the CFG walk is currently lowering, so a synthesized statement
        # (an ANF temp, a budget check) inherits the user line it came from
        # instead of reporting 0.
        self._cur_line = getattr(func, 'line', 0) or 0
        self.ret = func.return_type or SawType(TypeKind.VOID)
        self.is_void = (self.ret.kind == TypeKind.VOID)
        # DF-134a: does this frame ARM a reactor registration itself? Only a body
        # containing a literal `io_wait` does — a frame that merely embeds a
        # suspending callee never registers anything, and the callee's own frame
        # carries (and releases) its registration. Computed from the untouched
        # body, before any lowering rewrites the call away. Frames that answer
        # False get no `__io_fd`/`__io_dir` fields and no disarm in `__release`,
        # so non-IO code (every freestanding frame included) is byte-identical.
        self.arms_io = _body_arms_io(func.body)

    # ------------------------------------------------------------------ #
    # design 62 G2: if-let / guard-let condition hoisting
    # ------------------------------------------------------------------ #
    def _hoist_suspending_conditions(self):
        """Rewrite every `if let x = f() { ... }` / `guard let x = f() else { ... }`
        whose condition is a PLAIN suspending call into a preceding
        `let __hoistN = f()` (the already-supported nested-suspending-call-in-let)
        plus the binding over the temp. ONLY the plain-call form is hoisted — a
        `move` or other rejected condition shape is left untouched (do not
        accidentally legalize what design 52 Part 0 rejects).

        A suspending METHOD call counts (DF-182a). The condition is evaluated
        unconditionally, so lifting it above the binding preserves order exactly —
        which is why the design-96 match-scrutinee hoist and the design-92 try
        hoist have taken methods all along. This one had not, so
        `guard let out = cmd.output()` — the idiomatic way to consume an optional
        result — was the one unconditional expression position where a suspending
        method was rejected instead of driven."""
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
        # Only the plain suspending call form is hoistable — a free function or a
        # method on a concrete receiver (`_call_suspends_expr`, shared with the
        # match and try hoists).
        if self._call_suspends_expr(cond):
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
    # design 120: the general ANF hoist — suspension in expression position
    # ------------------------------------------------------------------ #
    #
    # The blessed manual workaround IS the transform: rewrite any statement whose
    # expression tree contains a BURIED suspending call (an argument, receiver,
    # operand, literal element, interpolation, or return/`try!` expression) into
    # evaluation-ordered temporaries — `let r = a().b().c()` becomes
    # `let __anf0 = a(); let __anf1 = __anf0.b(); let r = __anf1.c()` — so each
    # suspending call lands in a top-level `let __anfN = <call>` the EXISTING
    # design-96/101/104 embedding machinery drives unchanged. Only UNCONDITIONAL
    # positions are hoisted here (design 120 stage 1); conditional positions (the
    # RHS of `??`/`&&`/`||`, a value-position `if`/`match` arm, a `?.` tail) are
    # left opaque — they lower to the branch shape first (stage 2). A statement
    # with no buried suspend is returned untouched (zero codegen diff for sync
    # code). The narrow condition/match hoists ran already; the try hoist runs
    # AFTER, so a buried `try!` lifted here into a top-level `let __anfN = try! ...`
    # is desugared by design 92 next.

    # Expression nodes whose evaluation is (partly) CONDITIONAL — a suspend inside
    # one may not be hoisted above its guard. Opaque to the stage-1 hoist; the
    # stage-2 branch lowering handles them.
    _ANF_CONDITIONAL = (IfExpr, MatchExpr, NilCoalesce, OptionalChain,
                        BindOptional, OptionalEvalExpr, OptionalChainAssign,
                        ClosureExpr)

    def _anf_hoist(self):
        self._anf_ctr = 0
        self._anf_block(self.func.body)

    def _anf_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._anf_stmt(s))
        block.statements = new_stmts
        for s in block.statements:
            self._anf_recurse(s)

    def _anf_recurse(self, s):
        """Descend into control-flow bodies so a buried suspend inside a branch is
        hoisted within that branch's statement list (mirrors `_collect_calls`)."""
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr):
            self._anf_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._anf_block(ctrl.else_branch)
        elif isinstance(ctrl, IfLetExpr):
            self._anf_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._anf_block(ctrl.else_branch)
        elif isinstance(ctrl, WhileExpr):
            self._anf_block(ctrl.body)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._anf_block(arm.body)
        elif isinstance(s, ForLoop):
            self._anf_block(s.body)
        elif isinstance(s, GuardLetStatement):
            self._anf_block(s.else_branch)

    def _anf_stmt(self, s):
        """Hoist buried suspending calls out of a leaf statement's value
        expression into preceding `let __anfN = ...` temps (evaluation order),
        returning the replacement statement list. Control-flow statements are
        left for `_anf_recurse` to descend into (their condition/scrutinee is the
        narrow hoists' / CFG walk's job)."""
        out = []
        if isinstance(s, LetStatement):
            if isinstance(s.value, self._ANF_CONDITIONAL):
                return [s]
            s.value = self._anf(s.value, out, lift_self=False)
        elif isinstance(s, AssignStatement):
            if isinstance(s.value, self._ANF_CONDITIONAL):
                return [s]
            # An assignment RHS has no top-level supported form (unlike `let x =
            # call()` / `return call()`), so a suspending-call RHS is lifted too:
            # `x = s()` becomes `let __anfN = s(); x = __anfN`.
            s.value = self._anf(s.value, out, lift_self=True)
        elif isinstance(s, ReturnStatement):
            if s.value is not None and not isinstance(s.value, self._ANF_CONDITIONAL):
                s.value = self._anf(s.value, out, lift_self=False)
        elif isinstance(s, ExpressionStatement):
            e = s.expression
            # Control-flow expression statements are descended into by
            # `_anf_recurse`; only a plain value expression is hoisted here.
            if not isinstance(e, (IfExpr, WhileExpr, MatchExpr, IfLetExpr)):
                s.expression = self._anf(e, out, lift_self=False)
        return out + [s]

    def _anf(self, expr, out, lift_self):
        """Return a replacement for `expr`, appending `let __anfN = <subexpr>`
        hoist statements to `out` for each buried suspending call lifted (in
        evaluation order). `lift_self` asks: if `expr` is itself a suspending call
        node, lift it to a temp (a buried child position); a statement's DIRECT
        value passes `lift_self=False` so a top-level `let x = call()` stays put."""
        if expr is None or not isinstance(expr, ASTNode):
            return expr
        if not self._spans_suspension(expr):
            return expr
        # A conditional construct: leave opaque (stage 2 lowers it to branches).
        if isinstance(expr, self._ANF_CONDITIONAL):
            return expr
        # A `try!`/`try`/`try?` over a suspend: lift the WHOLE try as a unit, after
        # linearizing the tried call's own arguments/receiver. The design-92 try
        # hoist (runs next) desugars the resulting `let __anfN = try! <call>`.
        if isinstance(expr, TryExpr):
            self._anf_children(expr.expr, out)
            if lift_self:
                return self._anf_lift(expr, out)
            return expr
        # Otherwise linearize the unconditional children first (evaluation order),
        # then lift this node if it is itself a buried suspending call.
        self._anf_children(expr, out)
        if lift_self and self._is_suspending_call_node(expr):
            return self._anf_lift(expr, out)
        return expr

    def _anf_lift(self, expr, out):
        tmp = f"__anf{self._anf_ctr}"
        self._anf_ctr += 1
        line = getattr(expr, 'line', 0) or 0
        col = getattr(expr, 'column', 0) or 0
        out.append(LetStatement(name=tmp, type_annotation=None, value=expr,
                                mutable=False, line=line, column=col))
        ident = Identifier(name=tmp, line=line, column=col)
        # Carry the subexpression's resolved type so the temp is typed exactly
        # (frame-local typing, method-call classification, and codegen all read it).
        ident.resolved_type = getattr(expr, 'resolved_type', None)
        return ident

    def _anf_is_pure(self, expr):
        """Conservative purity for the evaluation-order hoist (DF-133a).

        A LEFT sibling of a hoisted suspending child only has to be lifted when
        its evaluation can be OBSERVED relative to the suspension that would
        otherwise run before it. The filter is deliberately coarse and errs
        toward hoisting: a literal, and a plain read of a name / field / tuple
        element / index, are exempt; anything containing a CALL or a `&var`
        borrow is not (design 147 unit C, user fork (i)).

        A `move v` operand stays exempt — retiring a binding is compile-time
        bookkeeping with nothing to observe, and lifting it would relocate the
        transfer checkpoint it carries.

        A closure LITERAL is exempt and is not descended into. Creating one runs
        none of its body, and binding it to a temp would change its escaping
        classification (design 16/29): a closure passed directly to a
        non-escaping parameter is non-escaping, while one bound to a `let` is
        not.
        """
        impure = [False]

        def scan(n):
            if impure[0]:
                return
            if isinstance(n, (FunctionCall, MethodCall, TryExpr)):
                impure[0] = True
                return
            if isinstance(n, ReferenceExpr) and n.mutable:
                impure[0] = True
                return
            if isinstance(n, ClosureExpr):
                return
            if isinstance(n, ASTNode):
                for f in structural_fields(n):
                    scan_val(getattr(n, f.name))

        def scan_val(v):
            if impure[0]:
                return
            if isinstance(v, (list, tuple)):
                for x in v:
                    scan_val(x)
            elif isinstance(v, Argument):
                scan_val(v.value)
            elif isinstance(v, ASTNode):
                scan(v)

        scan(expr)
        return not impure[0]

    def _uncond_children(self, expr):
        """The UNCONDITIONAL child expressions of `expr`, in evaluation order.

        Built by running `_map_uncond_children` with an identity mapper, so the
        set of positions and their order can never drift from the rewriting
        walk that follows it.
        """
        seen = []

        def collect(child):
            seen.append(child)
            return child

        self._map_uncond_children(expr, collect)
        return seen

    def _anf_children(self, expr, out):
        """Linearize `expr`'s UNCONDITIONAL child positions in evaluation order,
        replacing each with its hoisted form (a suspending-call child becomes a
        temp reference; a sync child is returned unchanged).

        DF-133a: lifting only the suspending children would REORDER the
        statement. A lifted child is evaluated in a `let __anfN = ...` ahead of
        the statement, while a sync sibling stays where it was written and is
        therefore evaluated after it — so `add(noisy(1), slow(3))` printed
        "slow" before "noisy", contradicting design 120's promise that a hoisted
        statement behaves like its hand-unchained spelling. Every side-effecting
        child to the LEFT of the last lifted one is therefore lifted as well, in
        source order, ahead of it. Children to the RIGHT need nothing: the
        residual expression still evaluates after every hoist.
        """
        children = self._uncond_children(expr)
        last_lift = -1
        for i, child in enumerate(children):
            if (isinstance(child, ASTNode)
                    and not isinstance(child, self._ANF_CONDITIONAL)
                    and self._spans_suspension(child)):
                last_lift = i

        pos = [0]

        def do(child):
            i = pos[0]
            pos[0] += 1
            if (i < last_lift and isinstance(child, ASTNode)
                    and not self._spans_suspension(child)
                    and not self._anf_is_pure(child)):
                # A side-effecting sibling written BEFORE the suspension: give it
                # its own temp so it runs first. `_anf_lift` stamps the temp with
                # this subexpression's own line/column, so a transfer checkpoint
                # or diagnostic on it is still reported where the author wrote it.
                return self._anf_lift(child, out)
            return self._anf(child, out, lift_self=True)

        def receiver_hook(obj):
            # A suspending method / channel `receive()` embeds its receiver as a
            # frame-resident value the sub-frame borrows through `&receiver` — that
            # needs an ADDRESSABLE location. A non-addressable receiver (a call,
            # binary op, …), even a SYNC one like `makeT(42).susp()`, is hoisted to
            # a temp so `&__anfN` is well-formed. A suspending receiver was already
            # lifted by `do` above (its temp is addressable).
            if self._is_suspending_call_node(expr) and not self._is_addressable(obj):
                return self._anf_lift(obj, out)
            return obj
        self._map_uncond_children(expr, do, receiver_hook=receiver_hook)

    def _map_uncond_children(self, expr, fn, receiver_hook=None):
        """Apply `fn` to each UNCONDITIONAL child expression position of `expr`,
        writing the result back, in EVALUATION ORDER.

        The RHS of `&&`/`||` is skipped: it is evaluated conditionally, so nothing
        may be lifted out of it (the stage-2 branch lowering owns that position).
        `receiver_hook`, when given, post-processes a method call's receiver right
        after `fn` and before the arguments, keeping the receiver's own hoists
        ahead of the arguments'.
        """
        if isinstance(expr, FunctionCall):
            for a in expr.arguments:
                a.value = fn(a.value)
        elif isinstance(expr, MethodCall):
            obj = fn(expr.object)
            if receiver_hook is not None:
                obj = receiver_hook(obj)
            expr.object = obj
            for a in expr.arguments:
                a.value = fn(a.value)
        elif isinstance(expr, BinaryOp):
            expr.left = fn(expr.left)
            if expr.op not in ("&&", "||", "and", "or"):
                expr.right = fn(expr.right)
        elif isinstance(expr, UnaryOp):
            expr.operand = fn(expr.operand)
        elif isinstance(expr, (ArrayLiteral, SetLiteral, TupleLiteral)):
            expr.elements = [fn(e) for e in expr.elements]
        elif isinstance(expr, MapLiteral):
            expr.entries = [(fn(k), fn(v)) for (k, v) in expr.entries]
        elif isinstance(expr, StructInit):
            expr.field_inits = [(n, fn(v)) for (n, v) in expr.field_inits]
        elif isinstance(expr, StringInterpolation):
            expr.expressions = [fn(e) for e in expr.expressions]
        elif isinstance(expr, MemberAccess):
            expr.object = fn(expr.object)
        elif isinstance(expr, TupleIndex):
            expr.tuple_expr = fn(expr.tuple_expr)
        elif isinstance(expr, ArrayIndex):
            expr.array_expr = fn(expr.array_expr)
            expr.index = fn(expr.index)
        elif isinstance(expr, ForceUnwrap):
            expr.expr = fn(expr.expr)
        elif isinstance(expr, CastExpr):
            expr.expr = fn(expr.expr)
        elif isinstance(expr, OptionalWrap):
            expr.value = fn(expr.value)
        elif isinstance(expr, TryExpr):
            # Only the stage-2 walk reaches a TryExpr here; `_anf` peels its
            # subject itself before this dispatch ever sees one.
            expr.expr = fn(expr.expr)

    def _is_suspending_call_node(self, expr):
        """True if `expr` is a suspending call node the transform can lift to a
        top-level temp: a suspending free-function call, a blocking-extern call, a
        suspending method call, or a cooperative channel `receive()`."""
        if isinstance(expr, FunctionCall):
            if getattr(expr, 'type_args', None):
                return False
            return (expr.name in self._suspends
                    or self._is_blocking_extern(expr.name))
        if isinstance(expr, MethodCall):
            return (getattr(expr, 'is_chan_recv', False)
                    or self._method_call_suspends(expr))
        return False

    def _is_addressable(self, expr):
        """True for an lvalue location the sub-frame's `&receiver` can point at —
        a bare name, a field/tuple projection, an index, or `self`. A call /
        operator / literal is a temporary and must be hoisted first."""
        return isinstance(expr, (Identifier, MemberAccess, ArrayIndex,
                                 SelfExpr, TupleIndex))

    # ------------------------------------------------------------------ #
    # design 120 stage 2: suspension in a CONDITIONAL expression position
    # ------------------------------------------------------------------ #
    #
    # A value-position `if`/`match`, a `??` RHS, and a `&&`/`||` RHS all evaluate
    # their spanning sub-expression CONDITIONALLY — a suspend there may not be
    # hoisted above the guard (pinned semantics 3). Lower each to the branch shape
    # FIRST (the design-104 CFG pattern: a value-position construct becomes a
    # statement-position `if`/`match` that assigns a result temp per arm), so the
    # suspend lands unconditionally inside one arm, where the stage-1 ANF hoist and
    # the existing CFG split handle it. The short-circuit skip is automatic: an arm
    # that is not taken never runs, so its suspending call (and its side effects)
    # never execute. Runs BEFORE the ANF hoist (which then lifts the arm-value
    # suspends) and BEFORE `_mark_optional_binding_splits` (which splits the
    # `if let` a `??` lowers to).

    def _is_value_conditional(self, e):
        if isinstance(e, (IfExpr, MatchExpr, NilCoalesce)):
            return True
        if isinstance(e, BinaryOp) and e.op in ("&&", "||", "and", "or"):
            return True
        # A `?.` chain (design 111) whose hop suspends: lowered to an `if let` here
        # so the suspending hop lands in the some-branch. A multi-hop chain is
        # peeled one hop at a time by `_vc_chain_prefix_hoist`.
        if isinstance(e, OptionalEvalExpr):
            return self._count_bindopts(e.expr) >= 1
        return False

    def _count_bindopts(self, spine):
        """Number of `?.` unwrap points (BindOptional) in an OptionalEvalExpr's
        receiver spine (not descending into call arguments — hops only nest through
        the receiver chain)."""
        n = 0
        node = spine
        while True:
            if isinstance(node, BindOptional):
                n += 1
                node = node.expr
            elif isinstance(node, MethodCall):
                node = node.object
            elif isinstance(node, (MemberAccess, ForceUnwrap)):
                node = node.expr if isinstance(node, ForceUnwrap) else node.object
            elif isinstance(node, (ArrayIndex, TupleIndex)):
                node = node.array_expr if isinstance(node, ArrayIndex) else node.tuple_expr
            else:
                return n

    def _outermost_bindopt(self, spine):
        """The LAST-evaluated `?.` hop of a chain — the BindOptional nearest the top
        of the receiver spine (the walk descends from the outermost postfix node)."""
        node = spine
        while True:
            if isinstance(node, BindOptional):
                return node
            if isinstance(node, MethodCall):
                node = node.object
            elif isinstance(node, MemberAccess):
                node = node.object
            elif isinstance(node, ForceUnwrap):
                node = node.expr
            elif isinstance(node, ArrayIndex):
                node = node.array_expr
            elif isinstance(node, TupleIndex):
                node = node.tuple_expr
            else:
                return None

    def _replace_bindopt(self, node, replacement, found):
        """Return `node` with its single BindOptional (the `?.` hop) replaced by
        `replacement`, recording the hop's receiver in `found`. Walks only the
        receiver spine."""
        if isinstance(node, BindOptional):
            found.append(node.expr)
            return replacement
        if isinstance(node, MethodCall):
            node.object = self._replace_bindopt(node.object, replacement, found)
            return node
        if isinstance(node, MemberAccess):
            node.object = self._replace_bindopt(node.object, replacement, found)
            return node
        if isinstance(node, ForceUnwrap):
            node.expr = self._replace_bindopt(node.expr, replacement, found)
            return node
        if isinstance(node, ArrayIndex):
            node.array_expr = self._replace_bindopt(node.array_expr, replacement, found)
            return node
        if isinstance(node, TupleIndex):
            node.tuple_expr = self._replace_bindopt(node.tuple_expr, replacement, found)
            return node
        return node

    def _lower_value_conditionals(self):
        self._vc_ctr = 0
        self._extra_frame_locals = []
        self._vc_block(self.func.body)

    def _vc_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._vc_stmt(s))
        block.statements = new_stmts
        for s in block.statements:
            self._vc_recurse(s)

    def _vc_recurse(self, s):
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, IfExpr):
            self._vc_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._vc_block(ctrl.else_branch)
        elif isinstance(ctrl, IfLetExpr):
            self._vc_block(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._vc_block(ctrl.else_branch)
        elif isinstance(ctrl, WhileExpr):
            self._vc_block(ctrl.body)
        elif isinstance(ctrl, MatchExpr):
            for arm in ctrl.arms:
                if isinstance(arm.body, Block):
                    self._vc_block(arm.body)
        elif isinstance(s, ForLoop):
            self._vc_block(s.body)
        elif isinstance(s, GuardLetStatement):
            self._vc_block(s.else_branch)

    # The sub-expression each value-conditional evaluates UNCONDITIONALLY before it
    # branches — the one position where a suspension is NOT skippable.
    _VC_HEAD_FIELD = {IfExpr: "condition", MatchExpr: "matched_expr",
                      NilCoalesce: "expr", BinaryOp: "left"}

    def _vc_hoist_to_temp(self, expr, out):
        """Emit `let __vchN = <expr>` (lowered in turn, so a conditional there gets
        the same treatment) and return an Identifier reading the temp."""
        tmp = f"__vch{self._vc_ctr}"
        self._vc_ctr += 1
        t = getattr(expr, 'resolved_type', None)
        line, col = getattr(expr, 'line', 0), getattr(expr, 'column', 0)
        self._extra_frame_locals.append((tmp, t))
        out.extend(self._vc_stmt(LetStatement(
            name=tmp, type_annotation=t, value=expr, mutable=True,
            line=line, column=col)))
        ref = Identifier(name=tmp, line=line, column=col)
        ref.resolved_type = t
        return ref

    def _vc_head_hoist(self, cond, out):
        """Lift a value-conditional nested in `cond`'s unconditional HEAD position
        into a preceding `let __vchN = <head>` (itself lowered, recursively), so
        composed conditionals nest as STATEMENTS rather than as an `if let` inside
        an `if let` — the shape the CFG split cannot express. `o?.tick() ?? -1` is
        the common one: the `?.` chain is the `??`'s LHS."""
        self._vc_chain_prefix_hoist(cond, out)
        field = self._VC_HEAD_FIELD.get(type(cond))
        if field is None:
            return
        setattr(cond, field, self._vc_lift_here(getattr(cond, field), out))

    # ------------------------------------------------------------------ #
    # design 133 unit B: a value-conditional BURIED in a larger expression
    # ------------------------------------------------------------------ #
    #
    # Design 120 lowered a suspension-spanning `??` / `&&` / `||` / value-position
    # `if`/`match` / `?.` only when the operator was the statement's WHOLE value.
    # One level down — `f(a ?? slow())`, `return 1 + (a ?? slow())`,
    # `not (a && slow())` — nothing lowered it, stage 1 left the conditional opaque
    # on purpose, and the suspension surfaced as the nested-position error
    # (DF-125a). The fix reuses the mechanism rather than extending it: hoist the
    # WHOLE conditional into its own `let __vchN = <conditional>` and read the temp
    # in its place. That is exactly the outermost form `_vc_stmt` already lowers, so
    # the guard survives — the RHS still runs only on the path that needs it, and
    # the arms' own suspends are handled by the branch shape as before. Nesting
    # recurses for free: `_vc_hoist_to_temp` re-enters `_vc_stmt`, and `_vc_block`
    # walks the branches the lowering produces.

    def _vc_lift_here(self, expr, out):
        """Lift `expr` itself when it is a suspension-spanning value-conditional,
        otherwise lift the ones buried inside it. Returns the replacement."""
        if not isinstance(expr, ASTNode) or not self._spans_suspension(expr):
            return expr
        if self._is_value_conditional(expr):
            return self._vc_hoist_to_temp(expr, out)
        self._vc_lift_nested(expr, out)
        return expr

    def _vc_lift_nested(self, root, out):
        """Replace every suspension-spanning value-conditional in a STRICT
        descendant position of `root` with a read of a preceding statement temp."""
        def visit(child):
            if not isinstance(child, ASTNode) or not self._spans_suspension(child):
                return child
            # A closure body is its own scope — never hoist a conditional out of one.
            if isinstance(child, ClosureExpr):
                return child
            if self._is_value_conditional(child):
                return self._vc_hoist_to_temp(child, out)
            self._map_uncond_children(child, visit)
            return child
        self._map_uncond_children(root, visit)

    # The value expression a leaf statement evaluates unconditionally, or None for
    # a statement whose value positions belong to another pass (control flow, an
    # optional-chain assignment, a `guard let` subject).
    def _vc_stmt_value(self, s):
        if isinstance(s, (LetStatement, AssignStatement)):
            return s.value
        if isinstance(s, ReturnStatement):
            return s.value
        if isinstance(s, ExpressionStatement):
            e = s.expression
            if isinstance(e, (IfExpr, WhileExpr, MatchExpr, IfLetExpr,
                              OptionalChainAssign)):
                return None
            return e
        return None

    def _vc_chain_prefix_hoist(self, cond, out):
        """Peel a MULTI-hop `?.` chain down to a single hop: everything left of the
        last hop becomes `let __vchN = <prefix chain>` (recursively peeled, and
        lowered too if it also suspends), leaving `__vchN?.<last hop>` — a
        single-hop chain `_cond_to_branch` turns into one `if let`. A prefix that
        does not suspend just stays an ordinary chain expression in its temp, so
        `a?.b?.susp()` short-circuits at `a` exactly as before."""
        if not isinstance(cond, OptionalEvalExpr):
            return
        if self._count_bindopts(cond.expr) <= 1:
            return
        bo = self._outermost_bindopt(cond.expr)
        prefix = OptionalEvalExpr(expr=bo.expr, line=getattr(bo, 'line', 0),
                                  column=getattr(bo, 'column', 0))
        t = getattr(bo.expr, 'resolved_type', None)
        if t is not None and t.kind != TypeKind.OPTIONAL:
            t = SawType(TypeKind.OPTIONAL, inner_type=t)
        prefix.resolved_type = t
        bo.expr = self._vc_hoist_to_temp(prefix, out)

    def _vc_stmt(self, s):
        """Rewrite a leaf statement whose value is a suspension-spanning
        value-position conditional into the branch shape assigning a result sink."""
        import copy as _copy
        if (isinstance(s, LetStatement) and self._is_value_conditional(s.value)
                and self._spans_suspension(s.value)):
            cond = s.value
            t = getattr(cond, 'resolved_type', None) or s.type_annotation
            self._extra_frame_locals.append((s.name, t))
            name = s.name
            line, col = s.line, s.column

            def sink(v):
                return AssignStatement(target=Identifier(name=name, line=line,
                                                         column=col),
                                       value=v, line=line, column=col)
            pre = []
            self._vc_head_hoist(cond, pre)
            return pre + [self._cond_to_branch(cond, sink)]
        if (isinstance(s, AssignStatement) and self._is_value_conditional(s.value)
                and self._spans_suspension(s.value)):
            cond = s.value
            tgt = s.target
            line, col = s.line, s.column

            def sink(v):
                return AssignStatement(target=_copy.deepcopy(tgt), value=v,
                                       line=line, column=col)
            pre = []
            self._vc_head_hoist(cond, pre)
            return pre + [self._cond_to_branch(cond, sink)]
        if (isinstance(s, ReturnStatement) and s.value is not None
                and self._is_value_conditional(s.value)
                and self._spans_suspension(s.value)):
            cond = s.value
            line, col = s.line, s.column

            def sink(v):
                return ReturnStatement(value=v, line=line, column=col)
            pre = []
            self._vc_head_hoist(cond, pre)
            return pre + [self._cond_to_branch(cond, sink)]
        # A chained assignment `x?.y = v` whose RHS suspends (design 111 +
        # design 120): lower to a None-guarded in-place write so the RHS runs only
        # when every hop is non-None. Statement-discard position (its `Void?`
        # result is dropped).
        if (isinstance(s, ExpressionStatement)
                and isinstance(s.expression, OptionalChainAssign)
                and self._spans_suspension(s.expression)):
            lowered = self._lower_optchain_assign(s.expression)
            if lowered is not None:
                return [lowered]
        # design 133 unit B (DF-125a): the statement's value is not itself a
        # conditional, but one is BURIED in it (`f(a ?? slow())`,
        # `return 1 + (a ?? slow())`, `not (a && slow())`). Lift each buried
        # conditional to its own preceding statement — the outermost form the
        # branches above lower — and read the temp in its place.
        root = self._vc_stmt_value(s)
        if root is not None and self._spans_suspension(root):
            pre = []
            self._vc_lift_nested(root, pre)
            if pre:
                return pre + [s]
        return [s]

    def _lower_optchain_assign(self, oca):
        """Lower `recv?.field = value` (single-hop, statement position) to a
        None-guarded read-modify-writeback:

            if let _ = recv {
                var __wpN = recv!           // copy the payload out
                __wpN.field = value         // mutate the copy (value may suspend)
                recv = __wpN                // write the whole payload back (Some)
            }

        Writing the payload out and back — rather than mutating `recv!.field`
        directly — keeps the mutation on a plain struct local, which the ANF hoist
        then splits around the suspending RHS as any other statement. On a None
        head the guard skips the write AND the RHS (short-circuit). Requires a
        COPYABLE payload (the `recv!` read); a NoCopy payload or a multi-hop chain
        is left un-lowered, so it still rejects cleanly — never a silent
        miscompile."""
        import copy as _copy
        line, col = oca.line, oca.column
        spine = oca.target.expr if isinstance(oca.target, OptionalEvalExpr) else None
        if spine is None or self._count_bindopts(spine) != 1:
            return None
        recv_probe = []
        self._replace_bindopt(_copy.deepcopy(spine), None, recv_probe)
        receiver = recv_probe[0]
        rt = getattr(receiver, 'resolved_type', None)
        if rt is None or rt.kind != TypeKind.OPTIONAL or rt.inner_type is None:
            return None
        payload_t = rt.inner_type
        wp = f"__wp{self._vc_ctr}"
        self._vc_ctr += 1

        def wp_ident():
            i = Identifier(name=wp, line=line, column=col)
            i.resolved_type = payload_t
            return i
        # var __wpN = recv!
        fu = ForceUnwrap(expr=_copy.deepcopy(receiver), line=line, column=col)
        fu.resolved_type = payload_t
        copy_out = LetStatement(name=wp, type_annotation=None, value=fu,
                                mutable=True, line=line, column=col)
        # __wpN.field... = value   (spine with the `?.` hop -> __wpN)
        write_target = self._replace_bindopt(spine, wp_ident(), [])
        mutate = AssignStatement(target=write_target, value=oca.value,
                                 line=line, column=col)
        # recv = OptionalWrap(__wpN)   (whole-payload writeback, auto-Some)
        writeback = AssignStatement(
            target=_copy.deepcopy(receiver),
            value=OptionalWrap(value=wp_ident(), target_type=rt,
                               line=line, column=col),
            line=line, column=col)
        guard = IfLetExpr(
            name="_", optional_expr=_copy.deepcopy(receiver), mutable=False,
            then_branch=Block(statements=[copy_out, mutate, writeback],
                              final_expr=None),
            else_branch=None, line=line, column=col)
        return ExpressionStatement(expression=guard)

    def _attach_sink_block(self, block, sink):
        """Replace a value-yielding block's tail with `sink(tail)`; a diverging
        block (no tail value — it returns/breaks) is left as-is."""
        if block.final_expr is not None:
            block.statements.append(sink(block.final_expr))
            block.final_expr = None

    def _cond_to_branch(self, cond, sink):
        if isinstance(cond, IfExpr):
            self._attach_sink_block(cond.then_branch, sink)
            if cond.else_branch is not None:
                self._attach_sink_block(cond.else_branch, sink)
            return ExpressionStatement(expression=cond)
        if isinstance(cond, MatchExpr):
            for arm in cond.arms:
                if isinstance(arm.body, Block):
                    self._attach_sink_block(arm.body, sink)
                else:
                    arm.body = Block(statements=[sink(arm.body)], final_expr=None)
            return ExpressionStatement(expression=cond)
        if isinstance(cond, NilCoalesce):
            # `a ?? b` -> `if let __vcN = a { sink(__vcN) } else { sink(b) }`; the
            # RHS `b` runs only on the None path, so its suspend/side-effects skip.
            tmp = f"__vc{self._vc_ctr}"
            self._vc_ctr += 1
            ot = getattr(cond.expr, 'resolved_type', None)
            inner = ot.inner_type if (ot is not None
                                      and ot.kind == TypeKind.OPTIONAL) else None
            bind = Identifier(name=tmp, line=cond.line, column=cond.column)
            bind.resolved_type = inner
            then_blk = Block(statements=[sink(bind)], final_expr=None)
            else_blk = Block(statements=[sink(cond.default)], final_expr=None)
            return ExpressionStatement(expression=IfLetExpr(
                name=tmp, optional_expr=cond.expr, mutable=False,
                then_branch=then_blk, else_branch=else_blk,
                line=cond.line, column=cond.column))
        if isinstance(cond, BinaryOp) and cond.op in ("&&", "||", "and", "or"):
            # `a && b` -> `if a { sink(b) } else { sink(false) }`
            # `a || b` -> `if a { sink(true) } else { sink(b) }`; the RHS `b` runs
            # only when `a` does not short-circuit, so its suspend/side-effects skip.
            if cond.op in ("&&", "and"):
                then_val, else_val = cond.right, BoolLiteral(value=False)
            else:
                then_val, else_val = BoolLiteral(value=True), cond.right
            then_blk = Block(statements=[sink(then_val)], final_expr=None)
            else_blk = Block(statements=[sink(else_val)], final_expr=None)
            return ExpressionStatement(expression=IfExpr(
                condition=cond.left, then_branch=then_blk, else_branch=else_blk,
                line=cond.line, column=cond.column))
        if isinstance(cond, OptionalEvalExpr):
            # A single-hop `?.` chain -> `if let __vcN = recv { sink(Some(spine))
            # } else { sink(None) }`; the suspending hop lives in the some-branch,
            # short-circuiting to None when the receiver is None.
            spine = cond.expr
            tmp = f"__vc{self._vc_ctr}"
            self._vc_ctr += 1
            bind = Identifier(name=tmp, line=cond.line, column=cond.column)
            found = []
            some_expr = self._replace_bindopt(spine, bind, found)
            receiver = found[0]
            rt = getattr(receiver, 'resolved_type', None)
            bind.resolved_type = (rt.inner_type if rt is not None
                                  and rt.kind == TypeKind.OPTIONAL else None)
            result_t = getattr(cond, 'resolved_type', None)
            # Flattening (design 111): a some-value that is already optional is not
            # re-wrapped (never `U??`); otherwise wrap the payload to `U?`.
            se_t = getattr(some_expr, 'resolved_type', None)
            if se_t is not None and se_t.kind == TypeKind.OPTIONAL:
                some_val = some_expr
            else:
                some_val = OptionalWrap(value=some_expr, target_type=result_t,
                                        line=cond.line, column=cond.column)
            none_val = NoneLiteral(line=cond.line, column=cond.column)
            none_val.resolved_type = result_t
            then_blk = Block(statements=[sink(some_val)], final_expr=None)
            else_blk = Block(statements=[sink(none_val)], final_expr=None)
            return ExpressionStatement(expression=IfLetExpr(
                name=tmp, optional_expr=receiver, mutable=False,
                then_branch=then_blk, else_branch=else_blk,
                line=cond.line, column=cond.column))
        # Unreachable: `_is_value_conditional` gates the callers.
        raise CoroTransformError(
            f"coroutine transform: unsupported value-position conditional in "
            f"`{self.name}`", getattr(cond, 'line', 0), getattr(cond, 'column', 0),
            source_file=self.src_file)

    # ------------------------------------------------------------------ #
    # DF-151a: one frame field per BINDING, not per NAME
    # ------------------------------------------------------------------ #
    def _uniquify_bindings(self):
        """Rename every binding whose source name is already taken by another
        binding in this body, so that a name IS a binding identity.

        Everything downstream keys on names: `_collect_frame_locals` dedups by
        name, the frame struct gets one field per name, and `_rewrite_expr`
        turns EVERY `Identifier` whose name is in `encmap` into a read of that
        field — with no idea which binding the identifier meant. Two distinct
        bindings sharing one name is therefore a miscompile in both directions
        (a nested `match` arm read the LATER local's still-zero field — DF-151a's
        `arm sees: 0`; an inner block's write leaked OUT into the outer field),
        or, when the two have different types, a bogus `cannot assign X to field
        of type Y` on a legal program.

        Scope-correct alpha-renaming fixes the class at its root rather than
        patching the shapes: an initializer is rewritten BEFORE its own binding
        enters scope, so a design-100/107 DERIVED shadow (`let data =
        parse(move data)`, `if let x = x`, `for n in n..n + 2`) still reads the
        OLD binding, and the new one gets its own field. Only a colliding name
        is renamed, so a body that reuses no name comes out byte-identical.

        Runs FIRST in `prepare`, ahead of every hoist — so the `__anfN`/`__obN`/
        `__matchN` temps those synthesize are unique by construction and need no
        part in this."""
        self._uniq_ctr = 0
        self._uniq_taken = {p.name for p in self.func.parameters}
        self._uniq_walk_block(self.func.body, [])

    def _uniq_fresh(self, name):
        while True:
            new = f"{_UNIQ_PREFIX}{self._uniq_ctr}_{name}"
            self._uniq_ctr += 1
            if new not in self._uniq_taken:
                return new

    def _uniq_bind(self, name, scope, callable_=False):
        """Introduce `name` into `scope`, renaming it when the name is already
        bound somewhere else in this body. Returns the effective name."""
        if name == "_" or name.startswith("__"):
            # `_` binds nothing, and a `__`-prefixed name is a compiler temp
            # (the lexer reserves the prefix) — unique already.
            return name
        if name in scope:
            # The parser fills a plain enum arm's `bindings` AND its `pattern`
            # with the same names; the second view reuses the first's mapping
            # rather than minting a second field.
            return scope[name][0]
        new = self._uniq_fresh(name) if name in self._uniq_taken else name
        self._uniq_taken.add(new)
        scope[name] = (new, callable_)
        return new

    @staticmethod
    def _uniq_lookup(scopes, name):
        for sc in reversed(scopes):
            if name in sc:
                return sc[name]
        return None

    def _uniq_walk_block(self, block, scopes):
        scope = {}
        inner = scopes + [scope]
        for s in block.statements:
            self._uniq_walk_stmt(s, inner, scope)
        if block.final_expr is not None:
            self._uniq_walk(block.final_expr, inner)

    def _uniq_walk_stmt(self, s, scopes, scope):
        """A statement that BINDS into its enclosing block's scope (its binding
        is visible to every later statement of that block) — everything else
        goes through the general walk."""
        if isinstance(s, LetStatement):
            self._uniq_walk(s.value, scopes)
            s.name = self._uniq_bind(s.name, scope,
                                     callable_=_is_function_valued(s))
            return
        if isinstance(s, DestructuringLet):
            self._uniq_walk(s.value, scopes)
            for pat in _pattern_binding_nodes(s.pattern):
                pat.name = self._uniq_bind(pat.name, scope)
            return
        if isinstance(s, GuardLetStatement):
            self._uniq_walk(s.optional_expr, scopes)
            # The else branch runs on the path where the binding does NOT
            # exist, so it is walked before the bind.
            self._uniq_walk_block(s.else_branch, scopes)
            if s.pattern is not None:
                for pat in _pattern_binding_nodes(s.pattern):
                    pat.name = self._uniq_bind(pat.name, scope)
            else:
                s.name = self._uniq_bind(s.name, scope)
            return
        self._uniq_walk(s, scopes)

    def _uniq_walk(self, node, scopes):
        if node is None:
            return
        if isinstance(node, (list, tuple)):
            for x in node:
                self._uniq_walk(x, scopes)
            return
        if isinstance(node, Argument):
            self._uniq_walk(node.value, scopes)
            return
        if not isinstance(node, ASTNode):
            return
        if isinstance(node, Identifier):
            hit = self._uniq_lookup(scopes, node.name)
            if hit is not None:
                node.name = hit[0]
            return
        if isinstance(node, MoveExpr):
            hit = self._uniq_lookup(scopes, node.variable)
            if hit is not None:
                node.variable = hit[0]
            self._uniq_walk(node.path, scopes)
            return
        if isinstance(node, Block):
            self._uniq_walk_block(node, scopes)
            return
        if isinstance(node, IfLetExpr):
            self._uniq_walk(node.optional_expr, scopes)
            bound = {}
            if node.pattern is not None:
                for pat in _pattern_binding_nodes(node.pattern):
                    pat.name = self._uniq_bind(pat.name, bound)
            else:
                node.name = self._uniq_bind(node.name, bound)
            self._uniq_walk_block(node.then_branch, scopes + [bound])
            if node.else_branch is not None:
                self._uniq_walk_block(node.else_branch, scopes)
            return
        if isinstance(node, MatchExpr):
            self._uniq_walk(node.matched_expr, scopes)
            for arm in node.arms:
                bound = {}
                arm.bindings = [self._uniq_bind(b, bound)
                                for b in (arm.bindings or [])]
                if arm.pattern is not None:
                    for pat in _pattern_binding_nodes(arm.pattern):
                        pat.name = self._uniq_bind(pat.name, bound)
                if arm.lent_bindings:
                    arm.lent_bindings = [
                        (bound[b][0] if b in bound else b)
                        for b in arm.lent_bindings]
                armscopes = scopes + [bound]
                self._uniq_walk(arm.guard, armscopes)
                self._uniq_walk(arm.body, armscopes)
            return
        if isinstance(node, ForLoop):
            self._uniq_walk(node.iterable, scopes)
            bound = {}
            node.variable = self._uniq_bind(node.variable, bound)
            self._uniq_walk_block(node.body, scopes + [bound])
            return
        if isinstance(node, ClosureExpr):
            # Capture specs and the typechecker's capture bookkeeping name
            # ENCLOSING bindings, so they resolve in the outer scopes.
            for spec in (node.capture_specs or []):
                hit = self._uniq_lookup(scopes, spec.name)
                if hit is not None:
                    spec.name = hit[0]
            if node.captures:
                node.captures = [
                    (self._uniq_lookup(scopes, c) or (c,))[0]
                    for c in node.captures]
            if node.capture_modes:
                node.capture_modes = {
                    (self._uniq_lookup(scopes, k) or (k,))[0]: v
                    for k, v in node.capture_modes.items()}
            bound = {}
            for p in (node.parameters or []):
                p.name = self._uniq_bind(p.name, bound)
            self._uniq_walk_block(node.body, scopes + [bound])
            return
        if isinstance(node, TryCatchExpr):
            self._uniq_walk_block(node.try_block, scopes)
            # The catch block binds `error` (or its explicit name) implicitly.
            # Shield it so an outer binding this pass renamed cannot capture it.
            err = node.error_binding or "error"
            self._uniq_walk_block(node.catch_block, scopes + [{err: (err, False)}])
            return
        if isinstance(node, TryExpr) and node.catch_block is not None:
            self._uniq_walk(node.expr, scopes)
            self._uniq_walk_block(node.catch_block,
                                  scopes + [{"error": ("error", False)}])
            return
        if isinstance(node, FunctionCall):
            # A call to a closure-typed LOCAL carries the binding's name in
            # `FunctionCall.name` (design 77 item 4) — a plain string the
            # Identifier case above never sees. Rename it too, but only for a
            # binding that actually holds a function, so an ordinary local
            # merely sharing a name with a top-level function is left alone.
            hit = self._uniq_lookup(scopes, node.name)
            if hit is not None and hit[1]:
                node.name = hit[0]
        for f in structural_fields(node):
            self._uniq_walk(getattr(node, f.name), scopes)

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
                for f in structural_fields(n):
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
        # design 120 stage 2: a value-position conditional lowered to branch form
        # replaced its `let x = <cond>` with a branch assigning `x` per arm, so the
        # normal `let` walk no longer sees `x`. It IS assigned across resume states
        # (different arms in different blocks) and read after, so it must be
        # frame-resident: fold in the temps the value-conditional lowering recorded.
        for name, t in getattr(self, '_extra_frame_locals', []):
            add(name, t, self.func.line, self.func.column)
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
                for f in structural_fields(n):
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
                for f in structural_fields(n):
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
            if isinstance(ctrl, (IfExpr, WhileExpr, MatchExpr, ForLoop, IfLetExpr)) \
                    and self._spans_suspension(ctrl):
                self._norm_ctrl(ctrl, tail=False)
        fe = block.final_expr
        if fe is None:
            return
        spanning = self._spans_suspension(fe)
        # DF-158b: a `Void` body has NO RESULT, so nothing in it is ever in tail
        # position in the sense this branch means — there is no value to carry
        # out. `func f() { yield_now() }` is the whole bug: the parser makes a
        # block's last expression its tail, this turned that tail into
        # `return yield_now()`, and a suspending call as a RETURN VALUE is a
        # nested/expression position the state split cannot express — so the
        # author got a message about a shape they did not write, and adding any
        # statement after the call made it compile. A discarded tail lowers
        # exactly as a statement would, which is what it is.
        if tail and self.is_void:
            tail = False
            force = False
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
            elif isinstance(fe, IfLetExpr) and fe.else_branch is not None:
                # DF-182b: a trailing `if let … { v } else { w }` in VALUE
                # position. Same shape as the `if`/`else` above — push the result
                # flow into both branches so every leaf returns, then leave the
                # binding as a statement for design 104 item 1 to CFG-split. An
                # `if let` tail with no `else` produces no value and falls to the
                # `return <expr>` case below, as it did before.
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
        if isinstance(node, (IfExpr, IfLetExpr)):
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
        names its field. Keyed by statement identity (`node_id`, design 126 R2 --
        which the ANF/try hoists' synthesized statements carry too, from the same
        global counter) so the CFG walk can recover a call's sub-frame field. A
        suspending call buried in an expression position (not a bare
        `let x = g(...)` / `g(...)` statement) is rejected honestly."""
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
                self.recv_by_id[s.node_id] = rinfo
                return
            binfo = self._classify_blk(s)
            if binfo is not None:
                binfo['idx'] = len(self.blk_calls)
                self.blk_calls.append(binfo)
                self.blk_by_id[s.node_id] = binfo
                return
            info = self._classify_call(s)
            if info is not None:
                info['sub'] = f"__sub{len(self.calls)}"
                self.calls.append(info)
                self.call_by_id[s.node_id] = info
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
        # DF-151a: give every binding in the body a name unique WITHIN it, so
        # each is its own frame field and each identifier read reaches the
        # binding it was written against. MUST run first: everything below keys
        # on names, and the temps the hoists synthesize are already unique.
        self._uniquify_bindings()
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
        # design 96: hoist a SUSPENDING call out of a `match <call> { ... }`
        # SCRUTINEE into a preceding driven temp (`let __matchN = <call>` +
        # `match __matchN`). Runs AFTER tail normalization so a trailing match is
        # already a statement. Without this the suspending scrutinee hides inside
        # the MatchExpr, `_collect_calls` never sees a bare call to embed+drive, and
        # the callee's internal `io_wait` park blocks the thread instead of yielding
        # — a `match stream.read() {...}` worker hangs (even at nesting depth 1).
        self._hoist_suspending_match()
        # design 120 stage 2: lower a suspension-spanning value-position
        # conditional (`let x = if c { s() } else { … }`, a value `match`, a `??`
        # RHS, a `&&`/`||` RHS) to the branch shape — a statement-position
        # `if`/`match` that assigns a result temp per arm — so a suspend that was
        # in a CONDITIONAL position lands unconditionally inside one arm. Runs
        # before the ANF hoist (which lifts the arm-value suspend) and before
        # `_mark_optional_binding_splits` (which splits the `if let` a `??` forms).
        self._lower_value_conditionals()
        # design 120: the general ANF hoist. Lift any BURIED suspending call (an
        # argument, receiver, operand, literal element, interpolation, or a `try!`
        # over a suspend) out of an unconditional expression position into
        # preceding evaluation-ordered `let __anfN = <call>` temps, so each
        # suspending call lands in a top-level statement the existing embedding
        # machinery drives. Runs AFTER the condition/match scrutinee hoists (so it
        # never double-processes a scrutinee they already lifted) and BEFORE the
        # try hoist (so a buried `try!` it lifts to `let __anfN = try! <call>` is
        # then desugared by design 92). Sync code is untouched.
        self._anf_hoist()
        # design 92: hoist a suspending call out of a `try!`/`try`/`try?` wrapper
        # into a preceding driven temp, so a `try! recv.read()` in a spawned body
        # is embedded+driven (its internal park integrates with the executor)
        # rather than hiding inside a TryExpr the nested-call scan cannot see.
        self._hoist_suspending_try()
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
                       if not (self.has_recv and p.name == "self")]
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
        if self.has_recv:
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
        # (design 45 item 4): 0 = ready (yield), >0 = sleep that many NANOSECONDS
        # (design 180 — the unit follows `Duration`, which is what `sleep` takes).
        fields.append(StructField(name="__wake", type=SawType(TypeKind.INT)))
        # design 91: the reactor wake-word ADDRESS to latch on an io readiness
        # event. For a driven ROOT frame it is `&self.__wake` (set on first resume);
        # a nested sub-frame inherits its parent's token (propagated at each drive),
        # so an `io_wait` buried in a sub-frame routes the wakeup to the TOP-LEVEL
        # frame's `__wake` word — the one the scheduler reads. 0 = not yet set.
        fields.append(StructField(name="__io_tok", type=SawType(TypeKind.INT)))
        if self.arms_io:
            # DF-134a: the LAST (fd, direction) this frame armed, so `__release`
            # can drop a registration the body left behind. -1 = nothing armed.
            fields.append(StructField(name="__io_fd", type=SawType(TypeKind.INT)))
            fields.append(StructField(name="__io_dir", type=SawType(TypeKind.INT)))
        if self.is_spawn_root:
            # design 134: a spawned frame carries a POINTER to its group-owned
            # cell instead of a cancel word and a result slot of its own. The
            # cell holds both, outlives the frame, and is what every `TaskHandle`
            # addresses — so a completed task's box can be released at once.
            fields.append(StructField(name="__cellp", type=_cell_ptr_type(self)))
        else:
            # design 52b item 3: the cooperative cancel word. Task code reads it
            # via `cancelled()`, which the transform rewrites to this field. NO
            # forced destroy — the frame exits only through its own control flow.
            # A spawned root reads its cell's word instead (design 134); a driven
            # frame and a nested sub-frame keep the word here, and a sub-frame
            # gets it copied down from its root at each drive.
            fields.append(StructField(name="__cancel", type=SawType(TypeKind.BOOL)))
            if not self.is_void:
                fields.append(StructField(name="__result",
                                          type=_field_type(self.ret, self.result_enc)))
        self.frame_struct = Struct(name=self.frame_name, fields=fields,
                                   line=func.line, column=func.column,
                                   source_file=getattr(func, 'source_file', ""))
        return self.frame_struct

    # ------------------------------------------------------- design 134 places
    # The result and the cancel word are FRAME fields for a driven frame and a
    # nested sub-frame, and CELL fields (reached through `__cellp`) for a spawn
    # root. Every read and write goes through these two helpers, so the rest of
    # the lowering never has to know which layout it is looking at.
    def _result_place(self, line=0, column=0):
        if self.is_spawn_root:
            return MemberAccess(
                object=ArrayIndex(array_expr=_self_field("__cellp", line, column),
                                  index=_int(0)),
                member="__result")
        return _self_field("__result", line, column)

    def _cancel_place(self, line=0, column=0):
        if self.is_spawn_root:
            return MemberAccess(
                object=ArrayIndex(array_expr=_self_field("__cellp", line, column),
                                  index=_int(0)),
                member="__cancel")
        return _self_field("__cancel", line, column)

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
                'ret': is_ret, 'line': getattr(fc, 'line', 0) or 0}

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
            # DF-184c: the result is THIS frame's, exactly as for a free-function
            # callee. `_classify_call` cannot have said so — its `return` branch
            # only matches a FunctionCall, so a method tail arrived here with
            # `is_ret` still False and was lowered as a bare DISCARD: the callee
            # ran, the frame's `__result` was never written, and `return
            # recv.m()` handed back a zeroed value.
            is_ret = True
        if mc is None or getattr(mc, 'is_chan_recv', False):
            return None
        susp = getattr(self._tc, '_suspending_methods_set', None) if self._tc else None
        if not susp:
            return None
        # DF-184a: `_method_call_owner` answers for a STATIC call too, whose
        # `recv` is None — the sub-frame it embeds has no `__recv` to seed.
        sname = _method_call_owner(mc)
        if sname is None or (sname, mc.method_name) not in susp:
            return None
        is_static = _method_call_is_static(mc)
        return {'callee': _method_frame_key(
                    sname, mc.method_name, getattr(mc, 'resolved_symbol', None)),
                'args': list(mc.arguments), 'target': target, 'ret': is_ret,
                'recv': None if is_static else mc.object, 'recv_struct': sname,
                'is_method': True, 'has_recv': not is_static,
                'line': getattr(mc, 'line', 0) or 0}

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
        # design 183 unit 2: no signature gate here. The marshallable set is the
        # C-ABI one, checked at the DECLARATION (typechecker), so an offloadable
        # extern is offloadable from every call site and an unmarshallable one is
        # refused before any call site is reached.
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
        sname = _method_call_owner(mc)
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
        sname = _method_call_owner(mc)
        if sname is not None and (sname, mc.method_name) in susp:
            return mc
        return None

    def _reject_suspending_method_call(self, stmt):
        mc = self._suspending_method_call(stmt)
        if mc is not None:
            sname = _method_call_owner(mc) or "?"
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
                for f in structural_fields(n):
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
                sname = _method_call_owner(g) or "?"
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
            if fe is None:
                self._done(None)
            else:
                forgets = []
                val = self._rewrite_expr(fe, forgets)
                # DF-182d: a tail `move local`. The tail expression IS the return
                # value, so the drop-flag clears it owes belong in the done
                # sequence, which is exactly where a `return move local` puts
                # them — `_done` has taken them all along, and this position used
                # to refuse instead of passing them on.
                self._done(val, forgets)

        # The done marker is one past the last block id: no `if __state == k`
        # matches it, so a stray re-dispatch after Done is inert (Done already
        # returned to the executor, which never resumes a completed frame).
        done_state = len(self._blocks)
        for lit in self._done_lits:
            lit.value = done_state
        # design 163 (measurement): hang the state-machine facts the frame-layout
        # report needs on the frame struct — the state count and, per embedded
        # sub-frame field, the single state in which it is live. Read-only; no
        # code generation consults it.
        self.frame_struct.coro_frame_info = {
            'states': done_state,
            'sub_states': {c['sub']: c.get('drive_state')
                           for c in self.calls},
            'is_spawn_root': self.is_spawn_root,
            'is_method': self.is_method,
            'source_file': getattr(func, 'source_file', "") or "",
            # design 158: the two halves a logical backtrace needs beside the
            # embedding tree above — the name to print and, per state, the line
            # a frame parked there is stopped on.
            'display_name': self.display_name,
            'state_lines': dict(self._state_lines),
        }

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
        # accessor returning this task's cancel word, so the scheduler can wake
        # an io-parked frame whose peer set the cancel flag (it then re-checks
        # `cancelled()` at its park-loop top and bails). Reads wherever the word
        # lives (design 134): the frame's own field, or the cell's through
        # `__cellp` for a spawn root. The executor only ever asks a NOT-done
        # frame, so the cell it reaches through is always still there.
        is_cancelled = Method(
            name="__is_cancelled",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=False)],
            return_type=SawType(TypeKind.BOOL),
            body=Block(statements=[], final_expr=self._cancel_place()),
            self_mutable=False, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # design 158: which entry of the in-binary backtrace table describes THIS
        # frame type. The literal is patched once every frame has been built and
        # the table order is fixed (`_assign_bt_indices`) — until then it reads
        # -1, which the walker treats as "no table entry" rather than as an
        # index. Reaching the index through the `Resumable` vtable is what lets
        # the in-process walker start from an erased `Box<any Resumable>` without
        # spending a word inside every frame.
        bt_lit = _int(-1)
        self._bt_desc_lit = bt_lit
        bt_desc = Method(
            name="__bt_desc",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=False)],
            return_type=SawType(TypeKind.INT),
            body=Block(statements=[], final_expr=bt_lit),
            self_mutable=False, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # design 124: the frame's end-of-scope teardown, called at every `return
        # Done` site so a completed task's owned values die WITH THE TASK rather
        # than with its group. Not part of the `Resumable` protocol — the frame
        # releases itself from inside `resume`, so the executor needs no new
        # method and the erased vtable is unchanged.
        release = Method(
            name="__release",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.VOID),
            body=Block(statements=self._release_seq(), final_expr=None),
            self_mutable=True, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # Every frame conforms to the builtin `Resumable` trait (design 52b item
        # 1): the conformance is what lets a frame be erased into
        # `Box<any Resumable>` for the heterogeneous run queue. Concrete drives
        # (nested sub-frames, the entry executor, `__saw_drive_*`) still bind `resume`
        # statically — conformance only synthesizes a vtable at an erasure site.
        resume_ext = Extension(struct_name=self.frame_name,
                               methods=[resume, wake_reason, is_cancelled,
                                        bt_desc, release],
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

    def _suspend_to(self, wake, target, line=None):
        if self.cur in self._term:
            return
        # design 158: a frame parked here holds `__state == target`, so the
        # suspending statement's line is what a backtrace prints for `target`.
        self._state_lines[target] = line or self._cur_line
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
        # design 158: track the user line the walk is on, so a suspension the
        # transform SYNTHESIZED (an ANF temp, a design-127 budget yield) reports
        # the statement it came from rather than 0.
        self._cur_line = getattr(s, 'line', 0) or self._cur_line
        # A suspension primitive: terminate this block, resume at a fresh one.
        if _is_suspend_stmt(s):
            forgets = []
            fc = s.expression
            self._cur_line = getattr(fc, 'line', 0) or self._cur_line
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
                # DF-134a: remember WHAT we armed, so `__release` can drop a
                # registration this body leaves behind (the cancellation exit that
                # forgets to disarm, with the fd escaping through the result — the
                # token would then point into a freed frame box). Recording the
                # pair in fields first, and registering FROM those fields, keeps
                # the arm and the later disarm describing the same thing.
                self._emit([
                    AssignStatement(target=_self_field("__io_fd"), value=fd_a),
                    AssignStatement(target=_self_field("__io_dir"), value=dir_a),
                ])
                self._emit([ExpressionStatement(expression=FunctionCall(
                    name="__saw_exec_io_register",
                    arguments=[Argument(name=None, value=_self_field("__io_fd")),
                               Argument(name=None, value=_self_field("__io_dir")),
                               Argument(name=None, value=_self_field("__io_tok"))]))])
                nxt = self._new_block()
                self._suspend_to(_int(IO_PARK_WAKE), nxt)
                self.cur = nxt
                return
            # The wake expression (e.g. `sleep(d)`'s span) is ordinary body code:
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
        rinfo = self.recv_by_id.get(s.node_id)
        if rinfo is not None:
            self._emit_recv_call(rinfo)
            return
        # design 103 (A6): a blocking-extern call — offload it to a worker thread
        # and park on the job's pipe (start -> io_wait -> take).
        binfo = self.blk_by_id.get(s.node_id)
        if binfo is not None:
            self._emit_blk_call(binfo)
            return
        # A nested suspending call: embed + drive the callee sub-frame.
        info = self.call_by_id.get(s.node_id)
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

    def _optbind_dispatch(self, node, scrut, some_state, none_state,
                          forgets=()):
        """design 104 item 1: emit the optional-binding dispatch as an ordinary
        `if let` whose branches ONLY set the resume state (codegen already lowers an
        `if let` over a `T?` correctly — this reuses that has-value test + unwrap
        instead of a synthesized Some/None match). On the value path the unwrapped
        binding is stored into its frame field so it survives the transition to the
        (separately-dispatched) body state; both paths set `__state` and re-dispatch.

        DF-182c: that store is a MOVE. The binding owns the payload the unwrap
        just produced and dies at the end of the dispatch arm, so handing the
        field a copy was wrong twice over — a NoCopy payload has no copy to give
        and was refused outright, and an ExplicitCopy one would have been
        dropped by both the field and the binding. Moving retires the binding
        with the value, which is what the field taking ownership means, and
        costs an ImplicitCopy payload one retain/release pair it never needed.

        `forgets` are the drop-flag clears a `move` SCRUTINEE owes (`if let r =
        move held`): the read has already happened by the time either branch
        runs, so the source field's flag is cleared on BOTH — the value left it
        either way."""
        bind = node.name
        some_body = []
        if bind in self.encmap:
            some_body.append(AssignStatement(
                target=_self_field(bind),
                value=MoveExpr(variable=bind, path=None,
                               line=node.line, column=node.column)))
        some_body.extend(self._forgets(forgets))
        some_body.append(AssignStatement(
            target=_self_field("__state"), value=_int(some_state)))
        none_body = list(self._forgets(forgets))
        none_body.append(AssignStatement(
            target=_self_field("__state"), value=_int(none_state)))
        dispatch = IfLetExpr(
            name=bind, optional_expr=scrut, mutable=node.mutable,
            then_branch=Block(statements=some_body, final_expr=None),
            else_branch=Block(statements=none_body, final_expr=None),
            line=node.line, column=node.column)
        self._emit([ExpressionStatement(expression=dispatch)])
        self._blocks[self.cur].append(ContinueStatement())
        self._term.add(self.cur)

    def _split_if_let(self, e, loop_ctx):
        # DF-182c: a `move` SCRUTINEE is supported now. `_rewrite_expr` records
        # the drop-flag clears the move owes; the dispatch runs them on both
        # branches and moves the unwrapped payload into its frame field.
        forgets = []
        scrut = self._rewrite_expr(e.optional_expr, forgets)
        then_entry = self._new_block()
        else_entry = self._new_block() if e.else_branch is not None else None
        merge = self._new_block()
        self._optbind_dispatch(
            e, scrut, then_entry, else_entry if else_entry is not None else merge,
            forgets)
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
        forgets = []                           # DF-182c — see `_split_if_let`
        scrut = self._rewrite_expr(s.optional_expr, forgets)
        none_entry = self._new_block()
        after = self._new_block()
        # Value path -> `after` (the guard's continuation, which the enclosing
        # statement loop lowers into `after` next); None path -> the else-branch,
        # which must diverge (return/break/continue) per guard semantics.
        self._optbind_dispatch(s, scrut, after, none_entry, forgets)
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
        self._cur_line = getattr(fc, 'line', 0) or self._cur_line   # design 158
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
        self._branch(self._cancel_place(), after, check)
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
            name="__saw_exec_io_register",
            arguments=[Argument(name=None, value=fd),
                       Argument(name=None, value=_int(0)),
                       Argument(name=None, value=_self_field("__io_tok"))]))])
        self._suspend_to(_int(IO_PARK_WAKE), header)
        # after: take the result (joins the worker thread + frees the job).
        self.cur = after
        take = FunctionCall(name="__saw_blk_take",
                            arguments=[Argument(name=None, value=_self_field(job))])
        # design 183 unit 2: the result is the EXTERN's, not an Int. Name the
        # extern on the intrinsic so the re-typecheck types `take` as its return
        # type and codegen marshals the job's one result word back into it.
        take.blk_extern = fc.name
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
        # design 163 (measurement): the ONE state in which this sub-frame is
        # live. Construction and the goto below happen in the same resume tick
        # (`_goto` is a state assignment + `continue`, never a suspension), and
        # the Done arm moves the result out and leaves for `after` — so the
        # child's storage is live exactly while `__state == drive`. Recorded so
        # `--emit-frame-layout` can report (and CHECK) the per-state live set
        # rather than assert it.
        info['drive_state'] = drive
        # design 158: while `__state == drive` this frame is logically INSIDE the
        # callee, so its backtrace line is the call site's — the same line a
        # native backtrace shows for a non-leaf frame.
        self._cur_line = info.get('line') or self._cur_line
        self._state_lines[drive] = self._cur_line
        self._goto(drive)
        # A `return g(...)` tail (design 83) threads the callee's result into THIS
        # frame's `__result` and ends the coroutine; a `let x`/bare/discard call
        # stores (or drops) the result and re-dispatches past the call.
        after = None if is_ret else self._new_block()
        done_body = []
        if is_ret:
            if not callee_fb.is_void and not self.is_void:
                res = _sub_result_read(sub, callee_fb.result_enc)
                # Store first (loads the value), THEN clear the sub-frame's drop
                # flag so its teardown won't double-drop the moved-out result.
                done_body.append(AssignStatement(
                    target=self._result_place(), value=res))
                if _enc_cleanup(callee_fb.result_enc):
                    done_body.append(ExpressionStatement(expression=FunctionCall(
                        name="__saw_forget", arguments=[Argument(name=None,
                            value=MemberAccess(object=_self_field(sub),
                                               member="__result"))])))
            # design 124: this is a `return g(...)` tail — the coroutine ends here,
            # so it is a Done exit like any other and owes the same eager release.
            done_body.append(self._release_call())
            done_lit = _int(0)  # patched to the done-state marker after assembly
            self._done_lits.append(done_lit)
            done_body.append(AssignStatement(
                target=_self_field("__state"), value=done_lit))
            done_body.append(ReturnStatement(value=_poll("Done")))
        else:
            if target is not None and not callee_fb.is_void:
                res = _sub_result_read(sub, callee_fb.result_enc)
                done_body.append(AssignStatement(
                    target=_self_field(target), value=res))
                if _enc_cleanup(callee_fb.result_enc):
                    done_body.append(ExpressionStatement(expression=FunctionCall(
                        name="__saw_forget", arguments=[Argument(name=None,
                            value=MemberAccess(object=_self_field(sub),
                                               member="__result"))])))
            elif (target is None and not callee_fb.is_void
                  and _enc_cleanup(callee_fb.result_enc)):
                # design 124: a DISCARDED nested result (`let _ = g()` / a bare
                # `g()` whose callee returns an owned value) has no target to move
                # into, so the sub-frame's `__result` used to sit live until the
                # whole frame was torn down. Clear the slot here instead — that IS
                # the drop, at the statement that discarded it, matching `let _ =`
                # everywhere else in the language.
                done_body.append(AssignStatement(
                    target=MemberAccess(object=_self_field(sub), member="__result"),
                    value=NoneLiteral()))
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
            value=self._cancel_place()))
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
        if info.get('has_recv'):
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
        # design 52b item 3: `cancelled()` inside task code reads THIS task's
        # cancel word (observed cooperatively; NO forced destroy) — the frame's
        # own field for a driven frame, the group-owned cell's for a spawned one
        # (design 134).
        if (isinstance(node, FunctionCall) and node.name == "cancelled"
                and not node.arguments):
            return self._cancel_place(getattr(node, 'line', 0),
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
        if self.has_recv and isinstance(node, SelfExpr):
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
            read = _read_field(name, enc, getattr(node, 'line', 0),
                               getattr(node, 'column', 0),
                               move_read=_enc_cleanup(enc))
            # design 131: `move o!` moved the binding AND projected the payload.
            # The `move` half is what the field read + `__saw_forget` above
            # express; re-apply the `!` so the expression still has the payload's
            # type. (A "self_opt"-encoded field reads as the whole `T?`, so
            # without this the unwrap would simply vanish.)
            if getattr(node, 'unwrap', False) and not isinstance(read, ForceUnwrap):
                read = ForceUnwrap(expr=read, line=getattr(node, 'line', 0),
                                   column=getattr(node, 'column', 0))
                read.frame_place_read = True
            return read
        if isinstance(node, Identifier) and node.name in self.encmap:
            return _read_field(node.name, self.encmap[node.name], node.line,
                               node.column, owning_read=True)
        if isinstance(node, ASTNode):
            for f in structural_fields(node):
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
                for f in structural_fields(n):
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

    def _result_store_value(self, value):
        """The expression to store into an OPT-ENCODED result slot.

        The slot is `T?` and the body produces a `T`; the encoding's `None` means
        "no result yet", which is what lets `join` take the value exactly once.
        When `T` is ITSELF an optional that reading is ambiguous for a bare
        `return None`: typed against the slot, the literal becomes the OUTER
        `None` — the not-yet state — and `join`'s `take()!` then force-unwraps
        nothing (DF-174b, the half that survived the store-shape fix). Say which
        layer it belongs to: a `None` of `T`, wrapped, so the slot reads "result
        present, and the result is None".

        Only this shape needs saying. A non-`None` value is already a `T` and the
        store's own one-layer fit wraps it.
        """
        if not _enc_unwraps(self.result_enc):
            return value
        if self.ret is None or self.ret.kind != TypeKind.OPTIONAL:
            return value
        if not isinstance(value, NoneLiteral):
            return value
        # `expected_type`, not `resolved_type`: the tree is re-checked after the
        # transform and the chokepoint would overwrite the latter.
        value.expected_type = self.ret
        return OptionalWrap(value=value, target_type=_opt(self.ret),
                            line=value.line, column=value.column)

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
        any drop-flag clears for locals moved into the result, release everything
        else the frame owns (design 124), mark done, signal Done. The result store
        loads the value first, so the following `__saw_forget` clears the source
        flag without disturbing the moved value."""
        seq = []
        if value is not None and (self.is_void or _is_never_expr(value)):
            # A void `return foo()` (foo void) still runs its side effects; there
            # is no result slot to store into.
            #
            # DF-158a: neither does a DIVERGING result expression. `func boom()
            # -> Int { sleep(...)  panic("x") }` has a result type but no result
            # — `panic` is `Never`, and so is a `-> Never` call or a
            # break-less `while {}` (design 177) — so the frame is dead at that
            # point and there is nothing to store. Storing it anyway handed
            # codegen a Python `None` and ICEd. The done sequence still follows,
            # unreachable behind the noreturn call, so the state machine keeps
            # exactly the shape a non-diverging tail gives it.
            seq.append(ExpressionStatement(expression=value))
        elif value is not None:
            seq.append(AssignStatement(target=self._result_place(),
                                       value=self._result_store_value(value)))
        seq.extend(self._forgets(forgets))
        seq.append(self._release_call())
        done_lit = _int(0)  # patched to the done-state marker after CFG assembly
        self._done_lits.append(done_lit)
        seq.append(AssignStatement(target=_self_field("__state"), value=done_lit))
        seq.append(ReturnStatement(value=_poll("Done")))
        return seq

    # ------------------------------------------------------------------ #
    # design 124: eager per-task teardown — a group is a SCOPE, not a
    # lifetime extender.
    #
    # A frame's params and across-suspend locals are struct FIELDS, so without
    # this they lived until the frame box itself was torn down — i.e. until the
    # owning TaskGroup's Deinit. That made a completed task's `TcpStream` (and
    # every other owned value) outlive the task by the whole life of the group:
    # the README's accept-loop server leaked one fd per served connection, and
    # the sibling reader/writer pattern deadlocked outright (the reader waited
    # for an EOF that only the writer's drop could produce, and that drop waited
    # on the reader).
    #
    # `__release` is the frame's end-of-scope teardown, emitted at EVERY exit the
    # state machine has (both `return Done` sites). It drops exactly what a
    # returning ordinary function would drop, in the same LIFO order, and keeps
    # exactly one thing alive: `__result`, which `join()` moves out (or which the
    # box teardown drops once at group teardown if nobody joins). The scheduler
    # words (`__state`/`__wake`/`__io_tok`/`__cancel`) also stay put — a handle
    # may still `cancel()` a completed task, and the reactor may still latch a
    # stale token into `__wake`, so those slots must remain addressable for the
    # frame's whole life.
    #
    # Clearing a drop-flagged field to `None` IS the drop (the None/Some tag is
    # the flag), which makes the release idempotent and makes the later memberwise
    # box teardown a no-op on the same field — no double drop.
    # ------------------------------------------------------------------ #
    def _release_call(self):
        return ExpressionStatement(expression=MethodCall(
            object=SelfExpr(), method_name="__release", arguments=[]))

    def _owned_frame_fields(self):
        """(name, encoding, declared type) for every frame field this frame OWNS,
        in declaration order. Excludes `__result` (survives to `join`/teardown),
        the non-owning `__recv`/reference pointers, the POD scheduler words, and
        the sub-frame fields (each sub-frame releases itself at ITS own Done — a
        parent can never complete while a sub-frame is mid-flight, since it is
        parked in the drive block until the callee reports Done)."""
        owned = []
        for p in self.params:
            owned.append((p.name, self.encmap[p.name], p.type))
        for lname, lt in self.frame_locals:
            owned.append((lname, self.encmap[lname], lt))
        # design 62 G3: a DISCARDED cooperative `receive()` parks its moved-out
        # value in a `__rcvN` holder (already `T?`-shaped, its own tag the flag).
        for rc in self.recv_calls:
            if rc['target'] is None:
                owned.append((f"__rcv{rc['idx']}", "self_opt", rc['elem_type']))
        return owned

    def _release_seq(self):
        """The body of `__release`: drop every owned field in reverse declaration
        order (LIFO, matching both ordinary scope exit and the struct teardown in
        codegen/resources.py)."""
        seq = []
        # DF-134a: drop a reactor registration this frame armed and never had
        # dropped. It runs FIRST, ahead of the field drops, so the fd is still
        # open and still ours: unregistering after the owning `TcpStream` field
        # closed it could disarm whatever reused the number. Idempotent at the
        # seam, so an already-fired one-shot costs one ENOENT.
        if self.arms_io:
            seq.append(ExpressionStatement(expression=IfExpr(
                condition=BinaryOp(op=">=", left=_self_field("__io_fd"),
                                   right=_int(0)),
                then_branch=Block(statements=[ExpressionStatement(
                    expression=FunctionCall(
                        name="io_unwait",
                        arguments=[
                            Argument(name=None, value=_self_field("__io_fd")),
                            Argument(name=None, value=_self_field("__io_dir")),
                        ]))], final_expr=None),
                else_branch=None)))
        for name, enc, t in reversed(self._owned_frame_fields()):
            if _enc_cleanup(enc):
                seq.append(AssignStatement(target=_self_field(name),
                                           value=NoneLiteral()))
            elif enc == "plain" and _is_taskgroup(t):
                # design 62 G1: a frame-resident TaskGroup is plain-encoded (it must
                # stay addressable for `group.spawn`'s `&group` receiver), so it has
                # no drop flag to clear. Overwrite it with the same always-valid
                # empty placeholder its zero-init uses: the assignment deinits the
                # old group — structured-joining ITS children first, exactly what
                # the task's own scope exit would have done — and installs a fresh
                # empty one that drops for free at box teardown.
                seq.append(AssignStatement(
                    target=_self_field(name),
                    value=FunctionCall(name="TaskGroup", arguments=[])))
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


def _build_frame_init(fb: _FrameBuilder, param_values, fbs, recv_value=None,
                      cellp_value=None):
    """A `StructInit` for `fb`'s frame: param fields from `param_values` (an
    opt-encoded param auto-wraps T -> Some), every local empty, every embedded
    callee sub-frame zero-initialised (a dead frame, rebuilt with real args when
    its call site is reached — the dead frame holds no live cleanup fields, so
    the rebuild's assignment drops nothing), state 0, result empty. For a method
    frame the receiver pointer `__recv` leads (Part 0c); for a spawn-root frame
    `cellp_value` is the address of the group-owned cell that carries the result
    and the cancel word in the frame's stead (design 134)."""
    from ast_nodes import StructInit
    field_inits = []
    if fb.has_recv:
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
                 if sub_fb.has_recv else None)
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
    if fb.arms_io:
        # DF-134a: nothing armed yet.
        field_inits.append(("__io_fd", _int(-1)))
        field_inits.append(("__io_dir", _int(0)))
    if fb.is_spawn_root:
        field_inits.append(("__cellp", cellp_value))
    else:
        field_inits.append(("__cancel", BoolLiteral(value=False)))
        if not fb.is_void:
            field_inits.append(("__result", _zeroed_value(fb.result_enc, fb.ret)))
    return StructInit(struct_name=fb.frame_name, field_inits=field_inits)


def _make_entry_executor(fb: _FrameBuilder, fbs):
    """Synthesize the entry executor that replaces a suspending `main` (design 45
    item 1). It builds main's frame and drives it to completion on a single
    cooperative run: each Pending consults the frame's `__wake` reason and, for a
    `sleep(d)`, parks that long (`__saw_exec_park`) before resuming; a
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
    # design 118 stage 2: the single-frame entry executor keeps its trivial
    # resume-until-done loop synthesized (the lead-pinned design-45 allocation-free
    # fast path — no box, no scheduler list), but the PARK POLICY is carved into the
    # Saw `__saw_exec_park(wake)` (std/taskgroup.saw): wake > 0 => sleep; wake < 0
    # (io-park) => block in the reactor until the fd is ready; wake == 0 (yield) =>
    # resume at once. After the carve this executor emits zero park body — only
    # `resume` + one `__saw_exec_park` call. (A monomorphized generic
    # `__saw_exec_run_single(box)` that removes even this loop is the DEFERRED
    # option recorded in ABI.md.)
    pending_body = Block(statements=[ExpressionStatement(expression=FunctionCall(
        name="__saw_exec_park",
        arguments=[Argument(name=None, value=MemberAccess(
            object=Identifier(name="__f"), member="__wake"))]))], final_expr=None)
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
    entry executor `__saw_exec_run_root`, which enqueues it as the root member of the
    shared scheduler and drives main AND every task it spawns to completion. This is
    what makes a spawn run eagerly whenever main parks (the core design-89 fix). A
    suspending main with NO spawn keeps the lighter single-frame executor above."""
    frame_init = _build_frame_init(fb, [], fbs)
    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    box_make = MethodCall(
        object=Identifier(name="Box", type_args=[box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=frame_init)])
    call = FunctionCall(name="__saw_exec_run_root",
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
    recv_value = Identifier(name="__recv") if fb.has_recv else None
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
            # Reading the result MOVES it out of the frame: `__f` is a
            # driver-local about to die, and the result is the one thing that
            # escapes it. Spelled as the sub-frame path spells the same
            # transfer — take the value, then `__saw_forget` the slot so the
            # frame's teardown does not release what the caller now owns.
            #
            # Design 139 is what forced the spelling. A retain would do for an
            # ImplicitCopy result (a bump the frame's own release then undoes),
            # and that is what used to happen; but once `Result<Int, Box<any
            # Error>>` became move-only there was no retain to reach for, and a
            # move is what this always was.
            read = MemberAccess(object=Identifier(name="__f"), member="__result")
            read.frame_place_read = True
            if _enc_unwraps(fb.result_enc):
                read = ForceUnwrap(expr=read)
                read.frame_place_read = True
            stmts.append(LetStatement(name="__res", type_annotation=None,
                                      value=read))
            if _enc_cleanup(fb.result_enc):
                slot = MemberAccess(object=Identifier(name="__f"),
                                    member="__result")
                slot.frame_place_read = True
                stmts.append(ExpressionStatement(expression=FunctionCall(
                    name="__saw_forget",
                    arguments=[Argument(name=None, value=slot)])))
            final = MoveExpr(variable="__res")

    # design 88: a reference param flows through the driver AS a raw pointer (the
    # drive site casts `&var x` -> `UnsafePointer<T>`), seeding the frame's pointer
    # field directly. Its inner type follows the reference (mutability preserved).
    driver_params = [Parameter(name=p.name,
                               type=(_ref_ptr_type(p.type)
                                     if fb.encmap.get(p.name) == "ref" else p.type))
                     for p in params]
    if fb.has_recv:
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


def _make_spawn_helper(fb: _FrameBuilder, fbs, helper_name=None):
    """Synthesize `__spawn_<f>(__group, <params>) -> TaskHandle<T>`.

    Allocate the task's CELL first (design 134), take the raw pointers to its
    result and cancel slots, build f's frame around the cell address, erase both
    into boxes, and hand them to the group together:

        func __spawn_f(__group: UnsafePointer<TaskGroup>, <params>) -> TaskHandle<T> {
            var __cbox  = Box<any __TaskCell>.make(__ResultCell<T>(__result: None,
                                                                   __cancel: false))
            let __cdata = __saw_box_data(&__cbox)
            let __cellp = __cdata as UnsafePointer<__ResultCell<T>>
            let __rp    = (&__cellp[0].__result) as UnsafePointer<T?>
            let __cp    = (&__cellp[0].__cancel) as UnsafePointer<Bool>
            var __box   = Box<any Resumable>.make(__Frame_f(<params>..., __cellp: __cellp))
            let __slot  = __group[0].__enqueue(move __box, move __cbox)
            let __gen   = __group[0].__gen_at(__slot)
            TaskHandle<T>(result_ptr: __rp, cancel_ptr: __cp, group_ptr: __group,
                          slot: __slot, generation: __gen)
        }

    Both pointers address the CELL, never the frame — that is the whole point of
    the design-134 split: the frame box can be released the instant the task
    completes, while the handle stays valid. The cell is a stable heap allocation
    inside its box in the group's queue (the fat pointer's data word never moves).
    The frame is a spawn root, so its result is opt-encoded — `result_ptr` is
    `UnsafePointer<T?>` uniformly, and `join` takes it with `Optional.take`.

    `helper_name` overrides the emitted name. It is set when `fb` is a
    DF-138a spawn-root trampoline (`f$spawnroot`), whose frame the helper boxes
    while the call sites still say `__spawn_f` — see `_make_spawn_trampoline`.
    """
    from ast_nodes import StructInit
    T = fb.ret
    params = fb.params
    helper_name = helper_name or f"__spawn_{fb.name}"

    cell_ptr = _cell_ptr_type(fb)
    # design 102 item 1: a `Void` task has no result slot, so its cell is the
    # bare `__VoidCell` and the handle captures only the cancel word + slot.
    if fb.is_void:
        cell_init = StructInit(struct_name="__VoidCell", type_args=None,
                               field_inits=[("__cancel", BoolLiteral(value=False))])
    else:
        cell_init = StructInit(
            struct_name="__ResultCell", type_args=[T],
            field_inits=[("__result", NoneLiteral()),
                         ("__cancel", BoolLiteral(value=False))])
    cell_box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="__TaskCell")
    cell_box_make = MethodCall(
        object=Identifier(name="Box", type_args=[cell_box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=cell_init)])

    def _cell_field(name):
        return MemberAccess(
            object=ArrayIndex(array_expr=Identifier(name="__cellp"), index=_int(0)),
            member=name)

    stmts = [
        LetStatement(name="__cbox", type_annotation=None, value=cell_box_make,
                     mutable=True),
        LetStatement(name="__cdata", type_annotation=None, mutable=False,
                     value=FunctionCall(name="__saw_box_data", arguments=[Argument(
                         name=None, value=ReferenceExpr(
                             expr=Identifier(name="__cbox"), mutable=False,
                             in_argument_position=True))])),
        LetStatement(name="__cellp", type_annotation=None, mutable=False,
                     value=CastExpr(expr=Identifier(name="__cdata"),
                                    target_type=cell_ptr)),
    ]
    if not fb.is_void:
        stmts.append(
            LetStatement(name="__rp", type_annotation=None, mutable=False,
                         value=CastExpr(
                             expr=ReferenceExpr(expr=_cell_field("__result"), mutable=False),
                             target_type=SawType(TypeKind.POINTER, inner_type=_opt(T)))))
    stmts.append(
        LetStatement(name="__cp", type_annotation=None, mutable=False,
                     value=CastExpr(
                         expr=ReferenceExpr(expr=_cell_field("__cancel"), mutable=False),
                         target_type=SawType(TypeKind.POINTER,
                                             inner_type=SawType(TypeKind.BOOL)))))

    frame_init = _build_frame_init(fb, [_frame_param_arg(p) for p in params], fbs,
                                   cellp_value=Identifier(name="__cellp"))
    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    box_make = MethodCall(
        object=Identifier(name="Box", type_args=[box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=frame_init)])

    tg_ptr = SawType(TypeKind.POINTER,
                     inner_type=SawType(TypeKind.STRUCT, struct_name="TaskGroup"))

    stmts.extend([
        LetStatement(name="__box", type_annotation=None, value=box_make, mutable=True),
        LetStatement(name="__slot", type_annotation=None, mutable=False,
                     value=MethodCall(
                         object=ArrayIndex(array_expr=Identifier(name="__group"), index=_int(0)),
                         method_name="__enqueue",
                         arguments=[
                             Argument(name=None, value=MoveExpr(variable="__box", path=None)),
                             Argument(name=None, value=MoveExpr(variable="__cbox", path=None))])),
        # design 134: the slot's generation completes the handle's identity, so a
        # handle outliving its task never addresses the task that replaced it.
        LetStatement(name="__gen", type_annotation=None, mutable=False,
                     value=MethodCall(
                         object=ArrayIndex(array_expr=Identifier(name="__group"), index=_int(0)),
                         method_name="__gen_at",
                         arguments=[Argument(name=None, value=Identifier(name="__slot"))])),
    ])
    if fb.is_void:
        handle = StructInit(
            struct_name="VoidTaskHandle", type_args=None,
            field_inits=[("cancel_ptr", Identifier(name="__cp")),
                         ("group_ptr", Identifier(name="__group")),
                         ("slot", Identifier(name="__slot")),
                         ("generation", Identifier(name="__gen"))])
        ret_type = SawType(TypeKind.STRUCT, struct_name="VoidTaskHandle")
        helper_params = [Parameter(name="__group", type=tg_ptr)] + \
                        [Parameter(name=p.name, type=p.type) for p in params]
        return Function(name=helper_name, parameters=helper_params,
                        return_type=ret_type,
                        body=Block(statements=stmts, final_expr=handle),
                        is_synthesized=True,
                        source_file=getattr(fb.func, 'source_file', ""))
    handle = StructInit(
        struct_name="TaskHandle", type_args=[T],
        field_inits=[("result_ptr", Identifier(name="__rp")),
                     ("cancel_ptr", Identifier(name="__cp")),
                     ("group_ptr", Identifier(name="__group")),
                     ("slot", Identifier(name="__slot")),
                     ("generation", Identifier(name="__gen"))])
    ret_type = SawType(TypeKind.STRUCT, struct_name="TaskHandle", type_args=[T])
    helper_params = [Parameter(name="__group", type=tg_ptr)] + \
                    [Parameter(name=p.name, type=p.type) for p in params]
    return Function(name=helper_name, parameters=helper_params,
                    return_type=ret_type,
                    body=Block(statements=stmts, final_expr=handle),
                    is_synthesized=True,
                    source_file=getattr(fb.func, 'source_file', ""))


def _make_spawn_trampoline(func, root_name):
    """DF-138a: the frame that lets ONE function serve BOTH task roles.

    A spawn root and a driven-or-embedded frame are two different protocols. A
    spawn root keeps its result and its cancel word in the group-owned CELL it
    reaches through `__cellp` (design 134), so the frame box can be released the
    instant the task completes; a driven root and an embedded sub-frame keep
    both IN the frame (`__result`/`__cancel`), because a sub-frame is copied its
    root's cancel word at every drive and hands its result up to its parent.
    One function means one `__Frame_<f>`, so a function that is spawned AND
    either driven in place or embedded as another frame's sub-frame cannot have
    a single layout serve both roles: the embedded instance would have no
    `__cancel` field to receive the copy and would write its result through a
    `__cellp` that points at nothing.

    Design 134 dodged this by rejecting the `__saw_drive`+spawn overlap, and the
    spawn+embed overlap was simply never considered — it crashed the second
    typecheck with a `None` field value (DF-138a). Rather than carry two layouts
    for one body, give the SPAWN role a frame of its very own:

        func f$spawnroot(<params of f>) -> T { return f(<params>) }

    `f$spawnroot` is the spawn root, so ITS frame carries `__cellp`; its single
    statement is the ordinary `return g(args)` tail the transform already lowers,
    which embeds `f`'s own `__Frame_f` as a sub-frame in the driven flavour —
    the same shape every other embedded callee has. The cancel word propagates
    down the chain and the result threads back up through the existing
    machinery, so neither protocol grows a special case and `f` keeps exactly
    one frame no matter how many other roles it plays.

    Built ONLY for a function that really has both roles. A spawn-only root is
    its own spawn frame as before and pays nothing — not a field, not a hop."""
    # Fresh `Parameter`s, not the originals: a frame builder renames what it owns,
    # and `f`'s own builder is looking at the same list. The spawn gates anchor at
    # `f`'s builder, so these carry no source position and owe none.
    params = [Parameter(name=p.name, type=p.type, is_reference=p.is_reference,
                        reference_mutable=p.reference_mutable)
              for p in func.parameters]
    call = FunctionCall(
        name=root_name,
        arguments=[Argument(name=None, value=_frame_param_arg(p)) for p in params],
        line=func.line, column=func.column)
    ret = func.return_type or SawType(TypeKind.VOID)
    # A `Void` body has no result to thread, so the bare-call form is the tail
    # (`return <void call>` is not a shape the classifier owes support for).
    if ret.kind == TypeKind.VOID:
        tail = ExpressionStatement(expression=call, line=func.line, column=func.column)
    else:
        tail = ReturnStatement(value=call, line=func.line, column=func.column)
    return Function(name=f"{root_name}$spawnroot", parameters=params,
                    return_type=func.return_type,
                    body=Block(statements=[tail], final_expr=None),
                    is_synthesized=True,
                    line=func.line, column=func.column,
                    source_file=getattr(func, 'source_file', ""))


def _rewrite_yield_intrinsic_calls(node):
    """Rewrite a QUALIFIED `task.yield_now()` into the bare intrinsic, in place,
    everywhere (DF-158d).

    The typechecker stamped `is_yield_intrinsic` on every call that resolves to
    std.task's design-114 wrapper — the wrapper is transparent by design, and a
    `MethodCall` node is the one spelling that could not say so on its own. One
    canonical `FunctionCall(name="yield_now")` afterwards means the split-point
    scan, the wake-reason table and the CFG walk all see the suspension they
    already know how to lower, with no second spelling to teach them.
    """
    if isinstance(node, MethodCall) and getattr(node, 'is_yield_intrinsic', False):
        return FunctionCall(name="yield_now", arguments=[],
                            line=node.line, column=node.column)
    if isinstance(node, ASTNode):
        for f in structural_fields(node):
            setattr(node, f.name, _rewrite_yield_val(getattr(node, f.name)))
    return node


def _rewrite_yield_val(val):
    if isinstance(val, list):
        return [_rewrite_yield_val(v) for v in val]
    if isinstance(val, tuple):
        return tuple(_rewrite_yield_val(v) for v in val)
    if isinstance(val, Argument):
        val.value = _rewrite_yield_intrinsic_calls(val.value)
        return val
    if isinstance(val, ASTNode):
        return _rewrite_yield_intrinsic_calls(val)
    return val


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
        for f in structural_fields(node):
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
            #
            # DF-184a: a STATIC method's frame has no `__recv`, so its driver
            # takes the arguments alone.
            if _method_call_is_static(inner):
                node.name = prefix + _method_frame_key(
                    _method_call_owner(inner), inner.method_name,
                    getattr(inner, 'resolved_symbol', None))
                node.arguments = [_ref_arg_to_ptr(a) for a in inner.arguments]
                return node
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
        for f in structural_fields(node):
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
        for f in structural_fields(node):
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


def _iter_function_calls(node):
    """Yield every FunctionCall node in an AST subtree. Used to find which spawn
    roots a body could also EMBED as a sub-frame (DF-138a): a suspending callee
    reaches `_collect_calls` only from a call written somewhere in the body, so
    this is a safe over-approximation of the embedded set — and an exact one in
    practice, since a suspending call the classifier cannot place is rejected
    rather than dropped."""
    if isinstance(node, FunctionCall):
        yield node
    if isinstance(node, ASTNode):
        for f in structural_fields(node):
            v = getattr(node, f.name)
            if isinstance(v, (list, tuple)):
                for x in v:
                    if isinstance(x, Argument):
                        yield from _iter_function_calls(x.value)
                    elif isinstance(x, ASTNode):
                        yield from _iter_function_calls(x)
            elif isinstance(v, Argument):
                yield from _iter_function_calls(v.value)
            elif isinstance(v, ASTNode):
                yield from _iter_function_calls(v)


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
            for f in structural_fields(v):
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
        `let x = g(...)`, a bare `g(...)`, or the design-83 tail `return g(...)`.

        The TAIL forms were missing until DF-138a's audit. `_classify_call`
        accepts `return g(args)`, so the call reached the embedding machinery as
        a still-generic call — which is rejected — but only AFTER the promotion
        had declined to splice its instantiation. What surfaced was neither: the
        template stayed a plain call in a body that had become a resume method,
        so the user got `cannot suspend in a sync func: __Frame_caller.resume`,
        naming a method the compiler had synthesized, about a `sync` region they
        had not written. `let r = g<A>(x); return r` compiled and `return g<A>(x)`
        did not."""
        fc = None
        if isinstance(s, LetStatement) and isinstance(s.value, FunctionCall):
            fc = s.value
        elif (isinstance(s, ExpressionStatement)
              and isinstance(s.expression, FunctionCall)):
            fc = s.expression
        elif isinstance(s, ReturnStatement) and isinstance(s.value, FunctionCall):
            fc = s.value
        if fc is not None:
            return maybe_promote(fc)
        return None

    def scan_block(block, out):
        # A block's last bare expression is parked in `final_expr`; design 83's
        # tail normalization turns a suspending one into `return <expr>`, but
        # that runs inside `prepare`, long after this walk. So reach it here too
        # — otherwise `func f() -> Int { g<A>(x) }` is the same missed promotion
        # as the `return` form, one line shorter.
        tail = getattr(block, 'final_expr', None)
        if isinstance(tail, FunctionCall):
            promoted = maybe_promote(tail)
            if promoted is not None:
                out.append(promoted)
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


def _assign_bt_indices(frame_structs, builders):
    """design 158: fix the backtrace table's frame ORDER and patch each frame's
    `__bt_desc` literal to its index.

    Ordered by frame NAME, not by construction order: the name is a property of
    the source, the construction order is a property of a work-list pop, and the
    table is compared byte-for-byte across runs by `irdet`. Runs once, after
    every frame in the program has been built, because an index is only
    meaningful against the whole table.
    """
    by_name = {}
    for fb in builders:
        by_name.setdefault(fb.frame_name, fb)
    named = sorted(s.name for s in frame_structs
                   if getattr(s, 'coro_frame_info', None) is not None)
    for index, name in enumerate(named):
        fb = by_name.get(name)
        if fb is None:
            continue
        fb.frame_struct.coro_frame_info['bt_index'] = index
        lit = getattr(fb, '_bt_desc_lit', None)
        if lit is not None:
            lit.value = index


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
    # shares method AST objects (list concat), so `method.node_id` still matches
    # the effect nodes. The ORIGINAL method stays in its module as harmless dead code
    # (its calls were all rewritten to the embedded drive). Generic-struct / method-
    # generic methods stay unsupported (rejected at the call site).
    _entry_ext_ids = {e.node_id for e in program.extensions}
    _imported_exts = ([e for e in getattr(imported_ast, 'extensions', [])
                       if e.node_id not in _entry_ext_ids] if imported_ast is not None else [])
    _all_exts = list(program.extensions) + _imported_exts
    # design 45 item 1: a suspending `main` is auto-wrapped in an entry executor.
    main_suspends = (getattr(typechecker, "_main_suspends", False)
                     and "main" in funcs_by_name)
    if not roots and not method_roots and not spawn_roots and not main_suspends:
        return False

    # DF-158d: canonicalize the design-114 yield WRAPPER to the intrinsic before
    # anything looks at a body. The qualified spelling `task.yield_now()` is a
    # `MethodCall`, which the split-point scan does not recognize as a
    # suspension point — so a callee whose only yield was written that way got
    # no frame, its caller embedded nothing, and the yield ran outside a frame
    # as a no-op. The typechecker marks the node; this makes every downstream
    # pass see the one spelling it already handles.
    for f in program.functions:
        f.body = _rewrite_yield_intrinsic_calls(f.body)
    for ext in _all_exts:
        for m in ext.methods:
            if getattr(m, 'body', None) is not None:
                m.body = _rewrite_yield_intrinsic_calls(m.body)

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
            node = _nodes_for_methods.get(m.node_id)
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
    # edges to a method are keyed by `Method.node_id`, so map every method AST to its
    # (struct, method, extension) to follow those edges and build the frames.
    methods_by_id = {}
    # design 95: keyed by the resolved-signature FRAME KEY (not (struct, name)),
    # so two overloads of the same method name each map to their OWN AST — a
    # name-only key collapsed them (second overwrote first → mis-resolution).
    methods_by_key = {}   # frame_key -> method.node_id — for the body scan
    for ext in _all_exts:
        sname = getattr(ext, 'struct_name', None)
        for m in ext.methods:
            methods_by_id[m.node_id] = (sname, m, ext)
            methods_by_key[_method_frame_key(
                sname, m.name, getattr(m, 'mangled_symbol', None))] = m.node_id
    _susp_methods_set = typechecker._suspending_methods_set

    def _scan_method_callees(body):
        """Enqueue every nested suspending METHOD call in `body` (a std method's
        effect node does not exist in the main typechecker, so the edge walk cannot
        reach it — discover it structurally instead). Returns (method-id) work items."""
        out = []
        for mc in _iter_method_calls(body):
            if getattr(mc, 'is_chan_recv', False):
                continue
            # DF-184a: a STATIC call is discovered here too. In std it is the ONLY
            # way it is discovered — an imported method has no effect node in the
            # entry typechecker — and a static call that went unfound compiled its
            # callee untransformed, so a `blocking` extern inside it lowered to a
            # NAKED call with no offload and no diagnostic.
            sn = _method_call_owner(mc)
            if sn is None:
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
    method_closure = {}   # method.node_id -> (struct_name, method_ast, extension)
    seen = set()
    # `promoted` is a SET of instantiation names, so iterating it directly puts
    # string-hash order — which Python randomizes per process — into the work
    # list, then into `closure`, then into `fbs`, and finally into the ORDER the
    # frame structs and their resume methods are emitted. Two runs of the same
    # compiler over the same source then produced different IR. That is exactly
    # the unpoliced hazard DF-126b warned about after design 126 R2 fixed two
    # other instances of it; sorting pins the order to the names themselves.
    work = [("fn", n) for n in (list(seed_names) + sorted(promoted))]
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
            # A method-level or generic-struct generic is not embedded here —
            # the call site is rejected cleanly by
            # `_reject_suspending_method_call`.
            #
            # A method ALREADY DRIVEN directly used to be skipped here too, on
            # the belief that the same rejection caught its call site. It does
            # not: `_classify_method_call` asks only whether the method
            # suspends, so the site was classified, embedded, and then died on
            # `fbs[<key>]` with a raw `KeyError` — the DF-138a crash with the
            # roles swapped. A driven method ROOT and an embedded method
            # sub-frame are the SAME frame (neither is a spawn root), so let it
            # join the closure and share one, exactly as a free function in both
            # roles already did.
            if (getattr(mast, 'type_params', None)
                    or getattr(ext, 'type_params', None)):
                continue
            method_closure[key] = (sname, mast, ext)
            if getattr(mast, 'body', None) is not None:
                work.extend(_scan_method_callees(mast.body))
            node = nodes.get(mast.node_id)
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

    # design 127 (RC-3): instrument every loop backedge in the bodies that are
    # about to become frames, BEFORE any layout is computed — the inserted
    # `yield_now()` is a real suspension point, so it must be in place when
    # `prepare` collects across-suspend locals and splits states. A body that
    # was sync run-to-completion becomes suspending here; that is the point.
    #
    # Scope v1 (per the brief): the ENTRY module's task bodies and the suspending
    # callees the transform embeds. Imported bodies are left alone — std's io
    # primitives already charge the design-89-c op budget in their own loops, and
    # a sync callee is not instrumented at all (a compute loop inside a
    # never-suspending helper stays unpreempted; documented in spec + skill).
    for n in closure:
        _instrument_loop_backedges(funcs_by_name[n])
    for mid, (_sname, mast, ext) in method_closure.items():
        if ext.node_id in _entry_ext_ids and getattr(mast, 'body', None) is not None:
            _instrument_loop_backedges(mast)

    # Phase 1: build every frame's layout (so a caller can embed a callee frame
    # by value). Phase 2: generate every resume state machine.
    suspends_set = set(closure)
    # DF-138a: which spawn roots ALSO play a non-spawn role — driven in place by
    # `__saw_drive`, or embedded as some other frame's sub-frame? Those two roles
    # want the frame-resident `__result`/`__cancel` layout; a spawn root wants the
    # group-owned cell it reaches through `__cellp`. One `__Frame_<f>` cannot be
    # both, so a dual-role function keeps the DRIVEN layout here and its spawn
    # role gets a trampoline frame of its own (`_make_spawn_trampoline`). Design
    # 134 rejected the `__saw_drive` half of this and never saw the embed half,
    # which crashed the transform's output on the second typecheck.
    #
    # The embedded set is read off the bodies the transform is about to lower.
    # `_rewrite_spawn_sites` already turned every `group.spawn(f(...))` into a
    # `__spawn_f(...)` call, so a spawn SITE never counts as an embedding.
    dual_role_spawn_roots = set()
    if spawn_roots:
        _role_bodies = [funcs_by_name[n].body for n in closure]
        _role_bodies += [m.body for (_s, m, _e) in method_closure.values()
                         if getattr(m, 'body', None) is not None]
        for _b in _role_bodies:
            for _fc in _iter_function_calls(_b):
                if _fc.name in spawn_roots:
                    dual_role_spawn_roots.add(_fc.name)
        dual_role_spawn_roots.update(n for n in spawn_roots if n in roots)
    fbs = {n: _FrameBuilder(funcs_by_name[n], tc=typechecker,
                            is_spawn_root=(n in spawn_roots
                                           and n not in dual_role_spawn_roots))
           for n in closure}
    # design 158: every builder this pass creates, in one list, so the backtrace
    # table's frame indices can be assigned once at the end (see
    # `_assign_bt_indices`). `fbs`/`spawn_fbs` share entries, so this is a list of
    # the DISTINCT builders, deduplicated there by frame name.
    all_builders = list(fbs.values())
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
        if ext.node_id not in _entry_ext_ids:
            # design 146: a frame builder REWRITES the body it is handed — it
            # hoists, ANF-normalizes and finally splits it into resume states —
            # and an imported method's body is std's own AST. That AST is now
            # reused across the front half's re-entry instead of being re-read
            # from disk, so the destruction no longer undoes itself: std would
            # go into the second pass carrying half a state machine (`self.off`
            # against a `TcpStream`, which has no such field). Build from a copy.
            # Nothing reads the original — the resume is spliced into the entry
            # AST and the call sites were rewritten to drive it — so the module
            # keeps the method the author wrote, as the note below intends.
            import copy as _copy
            mast = _copy.deepcopy(mast)
        fbs[fbkey] = _FrameBuilder(mast, struct_name=sname, tc=typechecker)
        all_builders.append(fbs[fbkey])
        nested_method_fbs.append((fbkey, ext, mast))
    # Prepare ALL layouts (fn + method) before generating any resume, so a caller
    # (fn or method) can embed a fully-known callee frame by value.
    for n in closure:
        new_structs.append(fbs[n].prepare(suspends_set))
    for fbkey, _ext, _mast in nested_method_fbs:
        new_structs.append(fbs[fbkey].prepare(suspends_set))
    # DF-138a: the spawn-side frame for each root. A single-role root IS its own
    # spawn frame; a dual-role one gets the `f$spawnroot` trampoline whose sole
    # statement embeds `__Frame_f` as a sub-frame. `spawn_roots` is a dict in
    # registration (source) order, so the emission order is deterministic.
    spawn_fbs = {}
    for n in spawn_roots:
        if n not in dual_role_spawn_roots:
            spawn_fbs[n] = fbs[n]
            continue
        tfb = _FrameBuilder(_make_spawn_trampoline(funcs_by_name[n], n),
                            tc=typechecker, is_spawn_root=True)
        spawn_fbs[n] = tfb
        all_builders.append(tfb)
        new_structs.append(tfb.prepare(suspends_set))
    for n in closure:
        _, resume_ext = fbs[n].build_resume(fbs)
        new_extensions.append(resume_ext)
    for fbkey, _ext, _mast in nested_method_fbs:
        _, resume_ext = fbs[fbkey].build_resume(fbs)
        new_extensions.append(resume_ext)
    for n in spawn_roots:
        if n in dual_role_spawn_roots:
            _, resume_ext = spawn_fbs[n].build_resume(fbs)
            new_extensions.append(resume_ext)
    for root_name, modes in roots.items():
        # `modes` is a SET (`_effect_record_driven`), so iterating it directly
        # puts per-process string-hash order into the order the `__saw_drive_*`
        # and `__saw_drive_steps_*` wrappers are emitted — the DF-126b
        # reproducible-build hazard again. Sorting pins it to the mode names.
        for mode in sorted(modes):
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
        # DF-138a: both gates above run against the ROOT FUNCTION's own builder —
        # its params, its across-suspend locals, its result type, anchored at its
        # source — whichever frame the helper ends up boxing. The trampoline
        # mirrors those params exactly, so nothing escapes the check.
        new_functions.append(_make_spawn_helper(
            spawn_fbs[root_name], fbs, helper_name=f"__spawn_{root_name}"))
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
    # in its module, unmodified (design 146 builds its frame from a copy), as dead
    # code: its call sites were rewritten to the embedded drive.
    for _fbkey, ext, mast in nested_method_fbs:
        if ext.node_id in _entry_ext_ids:
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
            _instrument_loop_backedges(method_ast)   # design 127
            mfb = _FrameBuilder(method_ast, struct_name=struct_name, tc=typechecker,
                                recv_saw_type=recv_saw_type)
            all_builders.append(mfb)
            new_structs.append(mfb.prepare(suspends_set))
            _, resume_ext = mfb.build_resume(fbs)
            new_extensions.append(resume_ext)
            for mode in sorted(modes):   # deterministic emission order
                new_functions.append(_make_driver(mfb, mode, fbs))
            continue
        if frame_key in fbs:
            # This method is ALSO embedded as some frame's sub-frame, so its
            # frame was built, prepared and resumed with the rest of the
            # closure. Emit only the drivers over that one frame: building a
            # second builder here would re-lower an already-lowered body, and
            # the body was stripped from its extension by `nested_method_fbs`
            # (entry-module methods only — an imported one stays put, so this
            # branch must not add it to `removed_methods` either).
            for mode in sorted(modes):   # deterministic emission order
                new_functions.append(_make_driver(fbs[frame_key], mode, fbs))
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
        if ext.node_id in _entry_ext_ids:
            _instrument_loop_backedges(method_ast)   # design 127
        mfb = _FrameBuilder(method_ast, struct_name=struct_name, tc=typechecker)
        all_builders.append(mfb)
        new_structs.append(mfb.prepare(suspends_set))
        _, resume_ext = mfb.build_resume(fbs)
        new_extensions.append(resume_ext)
        for mode in sorted(modes):   # deterministic emission order
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

    # design 158: every frame exists now, so the table order — and each frame's
    # `__bt_desc` answer — can be fixed.
    _assign_bt_indices(new_structs, all_builders)

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True

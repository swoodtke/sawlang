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


THE EMBED CONTRACT (design 210 unit 2) — what an imported declaration exports
============================================================================

Embedding an imported function into a driven frame means splicing its
already-checked body into the ENTRY module's AST. Design 210 rules that a
NON-GENERIC declaration's declaration-time annotations are SUFFICIENT for that
— the spliced body is never re-resolved — so this is the written-down list of
what "sufficient" covers, and the thing to check a new embed requirement
against. It is an IN-MEMORY interface today and deliberately kept
serializable: it is the same per-declaration shape a separate-compilation
module interface would need. Nothing here is serialized; that is explicitly
out of design 210.

SIX FAMILIES. Five ride the AST as DECLARED `annotation(...)` fields (design
126, gated by the `astgraft` lane — 813 declared attribute names across
`sawc/`, zero grafted writes); the sixth rides beside it, keyed by `node_id`.

1. RESOLVED EXPRESSION TYPES. `Expression.resolved_type` on every node
   (`_check_expression` is the one chokepoint that stamps it), plus the
   derived type records a later pass cannot recover without re-resolving:
   `resolved_type_identity` (design 144 — WHICH module's `Color`),
   `expected_type`, `autowrap_to_optional`, `matched_enum_type`,
   `matched_scrutinee_type`, `result_enum_type`, `error_type`/`error_types`,
   `vector_container_type`, `spawn_result_type`, `arc_forward_payload_type`,
   `box_forward_payload_type`, `um_scalar_type`, `place_elem_type`. The frame
   builder's own input is in this family too: the resolved type of every local
   it lifts into a field is what the frame struct is built out of.

2. RESOLVED CALLEE SYMBOLS AND DISPATCH DECISIONS. `resolved_symbol` on
   `FunctionCall` and `MethodCall` (design 95's overload answer), `arg_plan`,
   `resolved_init_params`, `resolved_field_inits`, `authored_callee`,
   `existential_dispatch`, `is_field_call`/`field_call_unwrap`,
   `array_builtin`, `is_static_method_call`/`static_receiver`,
   `resolved_module`/`resolved_module_symbol`/`resolved_static_name`/
   `resolved_struct_name`/`resolved_static_symbol`, `mangled_symbol`,
   `tuple_field_index`, `enum_raw_value`/`enum_from_raw`/`resolved_enum_init`,
   `alias_construction`, `as_function_call`, `type_args_inferred`,
   `const_param_name`/`const_static_value`/`const_static_reject`/
   `const_folded_value`,
   `int_limit`/`int_from`, `optional_take`, `optional_presence`, `cast_check`,
   `repeat_count`,
   `use_general_match`, the three `is_*_construct` markers,
   `interior_cell_ptr`, the erasure set (`erased_box_make`,
   `erased_downcast`, `erase_propagate`, `erase_concrete`, `erase_to_trait`,
   `to_pointer_cast`) and the `um_*` unsafe-memory set.

   THIS is the family DF-206e lost. Every one of these was answered in the
   callee's OWN module, and re-answering them under the entry module's
   namespace is what asks for `inner` in a scope where `inner` is not a name.

3. EFFECT AND SUSPENSION FACTS — what decides the state splits. On the AST:
   `MethodCall.is_chan_recv` (design 62 G3's inline lowering),
   `is_yield_intrinsic` (design 114's wrapper), `spawn_root`, `blk_extern`
   (design 103's offload), `GuardLetStatement._coro_split` /
   `IfLetExpr._coro_split`, `WhileExpr.diverges`. BESIDE the AST: the design-22
   effect graph (`typechecker._suspend_nodes`, keyed by `node_id` for a method
   and `("fn", name)` for a function), whose one answer is
   `effects.really_suspending`. The graph is the single family that is not an
   annotation, and it is keyed by `node_id` — per-declaration and serializable
   exactly as the AST is. It is CARRIED for a non-generic embed and RE-DERIVED
   for a generic instantiation, because designs 70/74 make effects depend on
   the type arguments.

4. PLACE AND COPY JUDGMENTS. `needs_copy` (the move checker's verdict at a
   transfer site), `payload_needs_copy` (design 131's optional-payload
   retain), `closure_lend`, `enum_variant_literal` (design 139),
   `place_value_read`/`place_abstract_read`, `MatchArm.lent_bindings`,
   `ReferenceExpr.from_lend`, and on the declaration
   `place_type`/`place_optional`/`place_lend_paths`/`place_self_by_pointer`/
   `place_lend_var`/`place_var_twin`. Place LOWERING runs before the transform
   and is not re-run on re-entry (`places_lowered=True`), so an embed consumes
   its output rather than reproducing it.

5. WHAT THE TRANSFORM STAMPS ITSELF — produced, not consumed. Every node the
   transform synthesizes for a mechanical rewrite carries the transform's own
   judgment instead of asking the language's: `frame_place_read` (design 131)
   and the `ForceUnwrap` pair `frame_owning_read`/`frame_move_read`. The
   transform is the AUTHORITY for what it synthesizes — one funnel, entry
   points named in its docstring.

6. NO-ESCAPE FACTS — carried by construction, stamped nowhere. `noescape.py`'s
   `first_reference_in` is a declaration-time REFUSAL with three entries
   (`parser/types.py`'s signature walk, `_first_laundered_reference`,
   `_first_reference_in_type` for an inferred closure return). A body that
   would let a reference escape does not compile, so an embed of a body that
   DID compile inherits the answer with nothing to carry. Design 88's
   spawn-frame confinement and design 201's task-borrow extent are checked
   against the FRAME the transform builds, not against the spliced body, so
   they are glue-side obligations rather than contract entries.

THE CLOSURE PROOF is the astgraft gate. A fact the embed needs but no class
declares would have to be a runtime graft; `tools/test_ast_graft.py` fails on
any attribute assignment in `sawc/` that no class declares, and
`substitute_ast_types` — the monomorphizer — walks `dataclasses.fields()`, so
an undeclared fact would additionally survive monomorphization stale. Anything
an embed turns out to need that is not in the six families above is a FINDING
against this schema, to be declared and listed here; never a graft.
"""

import dataclasses
from typing import NamedTuple, Optional
from ast_nodes import (
    ASTNode, Expression, Statement, Block, Argument,
    Identifier, MemberAccess, SelfExpr, IntLiteral, BoolLiteral, NoneLiteral,
    FunctionCall, MethodCall, BinaryOp, UnaryOp, EnumInit, ForceUnwrap, IfLetExpr,
    IfExpr, MatchExpr, MatchArm, WhileExpr, ReturnStatement, ArrayIndex,
    CastExpr, ReferenceExpr, RangeExpr, ForLoop, MoveExpr,
    BreakStatement, ContinueStatement,
    ExpressionStatement, LetStatement, AssignStatement, WhileExpr,
    CompoundAssignStatement,
    GuardLetStatement, TryExpr, TryCatchExpr,
    Function, Struct, StructField, Enum, EnumVariant, Extension, Method,
    Parameter, SawType, TypeKind, Visibility, ClosureExpr, CaptureSpec,
    DestructuringLet, TuplePattern, BindingPattern, WildcardPattern, TupleIndex,
    EnumPattern,
    StringInterpolation, ArrayLiteral, MapLiteral, SetLiteral, StructInit,
    TupleLiteral, NilCoalesce, OptionalChain, BindOptional,
    OptionalEvalExpr, OptionalChainAssign, OptionalWrap,
    ResultOkWrap, ResultErrWrap, ErasedErrWrap,
    structural_fields, expr_diverges,
)
from type_identity import type_identity as _type_identity
from ast_walk import (child_nodes, control_blocks, control_heads, map_nodes,
                      pattern_binding_names)


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


# DF-187b's one definition of "the children of a node" now lives in
# `ast_walk` — this file was where it was first written, and design 193 unit 3
# promoted it so the checker's walks share it. `_child_nodes` stays as the
# local name every call site below already uses.
_child_nodes = child_nodes


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

    The transform's door onto the one divergence predicate,
    `ast_nodes.expr_diverges` (design 228 leg 1). A diverging expression
    produces no value: there is nothing to store into a frame's `__result`, and
    trying to store it hands codegen a Python `None` (DF-158a)."""
    return expr_diverges(expr)


def _self_field(name, line=0, column=0):
    return MemberAccess(object=SelfExpr(line=line, column=column),
                        member=name, line=line, column=column)


def _int(n):
    return IntLiteral(value=n)


# The design-144 IDENTITY of `std.compiler.frame`'s `Poll`, not its spelling.
# Every reference below is SYNTHESIZED, so it must reach std's declaration
# whatever the module it lands in declares: a user `enum Poll` binds the
# spelling to its own identity, and a synthesized `return Pending` that went
# through name resolution would follow it into a type with no such variant.
# Computed rather than written out, so the mangling rule stays in one place.
POLL_IDENTITY = _type_identity("Poll", ("<std>", "compiler.frame"))


def _poll(variant):
    return EnumInit(enum_name=POLL_IDENTITY, variant_name=variant, arguments=[])


# The suspension-boundary intrinsics: `__saw_suspend` (test-only synthetic), and the
# real primitives `yield_now()` (immediately re-ready) and `sleep(d)` (timed).
_SUSPEND_CALLS = ("__saw_suspend", "yield_now", "sleep", "__saw_io_park", "io_wait",
                  "__saw_chan_park")

# design 76 (A4): the IO-park wake reason. A negative sentinel distinct from the
# `sleep(d)` (>0) and yield (0) reasons: the executor parks in the reactor
# (kqueue/epoll) rather than sleeping or busy-requeuing.
#
# design 230 extends the negative half rather than adding a field: EVERY value
# below -1 is a park on a READINESS WORD, spelled as that word's negated address,
# and the executor's rule is "resume when the word this frame named is nonzero".
# `__saw_chan_park(w)` is the suspension primitive that carries one; the word
# comes from `Channel.__park_word()`, so the wake reason names the channel and a
# send wakes exactly its own parked receivers. A readiness word is 8-aligned and
# never at address 0, so it can never collide with IO_PARK_WAKE.
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


def _stmt_positions(block):
    """Every STATEMENT POSITION in `block`, including the trailing expression the
    parser parked in `final_expr`.

    A block's last bare expression is a statement position in every way that
    matters to the lowering — `_lower_block` runs it for its side effects
    through `_lower_stmt`, exactly as it runs the statements before it — but it
    is not in `block.statements`, so a "spine" walk over that list alone walks
    straight past it. `_normalize_suspending_tails` hides how often that
    matters: it statementizes every tail that SPANS a suspension, so only a
    NON-spanning tail is ever left here for a later pass to miss. DF-233a is
    what that costs — a tail `if let … else { break }` in a suspending loop body
    is a non-spanning construct in a spanning loop, so the split marking never
    saw it and the raw `break` escaped the resume dispatch loop.

    ENTRY POINTS (obligation 1 — a funnel names its entries):
      * `_FrameBuilder._mark_ob_block` — the `if let`/`guard let` split marking.
      * `_FrameBuilder._collect_frame_locals` — the frame-field census, which
        owes a field to every binding the marking above split.
    Returned items are STATEMENTS or a bare `Expression`; both callers already
    unwrap with `s.expression if isinstance(s, ExpressionStatement) else s`, and
    `ast_walk.control_blocks` takes either.
    """
    out = list(block.statements)
    if block.final_expr is not None:
        out.append(block.final_expr)
    return out


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
    if fc.name == "__saw_chan_park":
        # design 230: the argument IS the wake reason — `Channel.__park_word()`
        # already hands back the negated address of the channel's readiness word.
        # Ordinary body code, so the caller rewrites its identifiers to frame
        # fields exactly as it does for `sleep`'s span.
        return fc.arguments[0].value
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

    def visit(node):
        if isinstance(node, ClosureExpr):
            return
        if isinstance(node, ForLoop) and not isinstance(node.iterable, RangeExpr):
            return
        if isinstance(node, (WhileExpr, ForLoop)):
            found.append(node)
            node.body.statements[:0] = _budget_check_stmts(
                budget, node.line, node.column)
        for c in _child_nodes(node):
            visit(c)

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
    # `Task`'s raw pointer into the group) resolves to an ADDRESSABLE frame
    # field `self.group` — an opt-encoded `self.group!` is not addressable. Its
    # placeholder is a real empty `TaskGroup()` (always-valid: its Deinit drains 0
    # children), so a teardown before the user's `let group = TaskGroup()` runs is
    # still sound, and the user's assignment drops the empty placeholder cleanly.
    if _is_taskgroup(saw_type):
        return "plain"
    return "opt"


# The type kinds that carry NOTHING to release, beyond the POD set `_is_pod`
# already names. `_enc_of` routes every one of them to the owning `opt`
# encoding, which is the right answer for STORAGE (a drop flag costs a word and
# the release is a no-op) and the wrong one for a residency DECISION — see
# `_type_owns`.
#
#   FLOAT     — a value, like the integers `_is_pod` lists; it is out of that
#               set only because the frame's zero-init has no float spelling.
#   POINTER   — an `UnsafePointer<T>` is a raw address. Non-owning BY DESIGN
#               (130): the frame never releases one, and the validity argument
#               is the marking rule's, not a destructor's.
#   REFERENCE — the `ref` encoding, a non-owning `UnsafeRef` handle (design 88).
#   VOID/NEVER/MODULE/CONST_VALUE — no runtime value at all.
_NON_OWNING_KINDS = (
    TypeKind.FLOAT, TypeKind.POINTER, TypeKind.REFERENCE,
    TypeKind.VOID, TypeKind.NEVER, TypeKind.MODULE, TypeKind.CONST_VALUE,
)


def _type_owns(saw_type):
    """Whether a value of `saw_type` OWNS something whose RELEASE ORDER a reader
    can observe. The residency question DF-218s asks, and deliberately NOT the
    same question as "does its frame field get a release shape".

    `_enc_owns` answers the second one, off the encoding, and is conservative on
    purpose: everything outside `_is_pod` gets the owning `opt` encoding, so a
    `Float` or an `UnsafePointer` field carries a drop flag whose release is a
    no-op. Conservatism is free there and is NOT free here — forcing residency
    on a local that owns nothing enlarges the frame for no ordering gain, and
    (measured: `examples/net_cancel_parked_mt.saw`) can make a frame that used
    to cross to an MT worker stop being `Send`, turning a working program into a
    diagnostic. So this reads the KIND, refusing exactly what cannot own.

    Conservative in the other direction still: a struct of two `Int`s owns
    nothing either, but answering that needs codegen's `_needs_cleanup` and its
    struct registry, and over-forcing a trivial struct costs frame bytes rather
    than correctness (a trivial struct is `Send` for the same reason it is
    trivial). A `TaskGroup` — `plain`-encoded for addressability, design 62 G1 —
    owns through its placeholder overwrite and is on the owning side."""
    if saw_type is None or saw_type.kind in _NON_OWNING_KINDS:
        return False
    return not _is_pod(saw_type)


def _stmts_terminate(stmts):
    """Whether a LOWERED statement list ends in a terminator — the shape
    `_lower_block_in_place` reads to decide whether a scope-end release is
    reachable. The transform's own done sequence ends in a `ReturnStatement`;
    a `break`/`continue` that survived in-place lowering is codegen's."""
    return bool(stmts) and isinstance(
        stmts[-1], (ReturnStatement, BreakStatement, ContinueStatement))


def _contains_return(node):
    """Whether `node`'s subtree contains a `return` OF THIS FUNCTION.

    A `ClosureExpr` body is cut off: a `return` there returns from the
    CLOSURE, and the enclosing block's locals are not on that edge at all.
    Every other nesting counts — a `return` inside an `if` inside a `match`
    arm inside a loop still leaves every scope between it and the body."""
    if node is None:
        return False
    if isinstance(node, ReturnStatement):
        return True
    if isinstance(node, ClosureExpr):
        return False
    for c in child_nodes(node):
        if _contains_return(c):
            return True
    return False


def _ref_ptr_type(ref_type):
    """The `UnsafePointer<T>` frame-field type for a reference `&T` / `&var T`
    (design 88). Pointer mutability mirrors the reference: a `&var T` frame field
    permits mutation through the deref; a `&T` field is read-only."""
    return SawType(TypeKind.POINTER, inner_type=ref_type.inner_type,
                   pointer_mutable=bool(ref_type.reference_mutable))


# --------------------------------------------------------------------------- #
# design 218 stage 1: the owning encodings become `Slot<T>`.
#
# `slot` / `slot_self` / `slot_closure` are the migrated forms of `opt` /
# `self_opt` / `opt_closure`: the field is a `Slot<T>` from
# `std.compiler.frame`, occupancy is the type's own business, and the four
# operations the transform needs — `put`, `take`, `value()`, `clear()` — are
# ordinary method calls the re-check judges like anybody else's. `slot_self`
# holds `Slot<T?>`: the local IS an optional, and it gets its own honest tag
# rather than punning one tag for optionality and liveness (218a ruling 6,
# the shape that hid DF-217b).
#
# Stage 2 adds the transform's own hoisted temps (census rows T1-T5). They are
# the migration's whole point: an ANF temp is the DF-217h family, where a
# consuming read and the drop-flag clear were two facts recorded in two places
# and the second one was missing. See `_TRANSFORM_CONSUMING_TEMPS`.
# --------------------------------------------------------------------------- #

# The design-144 IDENTITY of `std.compiler.frame`'s `Slot`, for the same reason
# `POLL_IDENTITY` above is: every reference here is SYNTHESIZED and must reach
# std's declaration whatever the module it lands in declares. `Slot` is the
# harder case — it is a name user programs use, and DF-218g is what happens
# when a bare-name reference meets a user `struct Slot` (silent capture) or a
# user `enum Slot` (`internal compiler error: Undefined enum: Slot`).
SLOT_STRUCT_NAME = _type_identity("Slot", ("<std>", "compiler.frame"))

# The same for `UnsafeRef` (design 218 stage 3), the frame's NON-owning handle:
# the method receiver `__recv` (census P1) and every `ref`-encoded local or
# parameter (census P2). Each was a bare `UnsafePointer<T>` whose validity
# argument lived in a comment; the handle carries it as a type instead, with
# design 130's marking rule as the obligation's carrier.
UNSAFEREF_STRUCT_NAME = _type_identity("UnsafeRef", ("<std>", "compiler.frame"))


def _unsaferef_type(pointee):
    """`UnsafeRef<pointee>` — the frame-field type of a receiver or a
    reference-encoded binding."""
    return SawType(TypeKind.STRUCT, struct_name=UNSAFEREF_STRUCT_NAME,
                   type_args=[pointee])


def _unsaferef_init(ptr_expr, pointee, line=0, column=0):
    """`UnsafeRef<pointee>(p: <ptr>)` — the one construction, at the one place
    the address is taken.

    The pointer expression is exactly what the field used to be seeded with
    (`&(<place>) as UnsafePointer<T>`, or a null cast for a dead sub-frame's
    placeholder), so the VERIFIED-unsafe crossing has not moved: it is the same
    cast, now wrapped in the handle that names what the transform is promising.

    ENTRY POINTS (obligation 1): `_build_frame_init` for `__recv` (every frame
    construction, dead placeholder included) AND for a spawn root's `__cellp`
    (design 222 unit 1), `_build_sub_frame` and `_make_driver` for the pointer it
    wraps, and `_zeroed_value`/`_seed_field` for a `ref`-encoded local or
    parameter."""
    return StructInit(
        struct_name=UNSAFEREF_STRUCT_NAME,
        type_args=[pointee],
        field_inits=[("p", ptr_expr)], line=line, column=column)


def _unsaferef_deref(place, saw_type, line=0, column=0):
    """`<place>.deref()` — the lend that replaces a raw `[0]` pointer read.

    A graft on the same terms `_slot_read`'s is (see its docstring): the method
    is public in `std.compiler.frame`, present in every driven program, and the
    read has to be RE-CHECKED rather than skipped, because the place lowering
    only sees an accessor the checker stamped `place_struct` on."""
    node = MethodCall(object=place, method_name="deref", arguments=[],
                      line=line, column=column)
    if saw_type is not None:
        node.resolved_type = saw_type
        node.frame_slot_op = True
    return node


_SLOT_ENC_OF_LEGACY = {"opt": "slot", "self_opt": "slot_self",
                       "opt_closure": "slot_closure"}

# The transform's own SINGLE-USE hoisted temps (design 218 stage 2, census rows
# T1-T4). Each is written once by the hoist that made it and read once, in the
# position the hoist lifted the expression out of — so its one read CONSUMES it,
# and the migrated spelling for that is `take()`.
#
# That is the whole of DF-217h. Today the read is a bare identifier, which
# lowers to an owning read that leaves the drop flag set, and nothing clears it
# afterwards: the value is released by the consumer AND again by the frame's
# teardown. `take()` is the read and the give-up in one method body, so the
# state "consumed but still flagged live" stops being representable.
#
# NOT on the list, and the distinction is load-bearing: `__vcN`, the payload
# binding a value-conditional's lowering makes (`a ?? b` becomes
# `if let __vcN = a`). That is an ordinary pattern binding whose store goes
# through `_store_binding_in_slot` and whose read follows the use site's own
# tier, exactly like a binding the author wrote. `__vchN` — the value-
# conditional HOIST temp, which shares its prefix — IS on the list, and the
# two are kept apart deliberately.
#
_TRANSFORM_CONSUMING_TEMPS = ("__anf", "__trycall", "__vch")


def _is_consuming_temp(name):
    """Whether `name` is one of the transform's single-use EXPRESSION temps,
    whose one read consumes it."""
    return isinstance(name, str) and name.startswith(_TRANSFORM_CONSUMING_TEMPS)


# The SCRUTINEE temps — census rows T1 and T3 — which stage 2 does NOT migrate.
# Their reader is an `if let` / `match` dispatch, and it consumes only when the
# BINDING it feeds does; the rest of the time the payload stays in the temp for
# teardown to drop. Neither answer is spellable on a slot today:
#
#   * `take()` where the binding does NOT consume moves the payload into a
#     binding whose scope is a CFG BLOCK the split reaches from another block,
#     and the cleanup that would drop it never runs there — measured, a clean
#     leak (`coro_iflet_suspending_deinit`'s 907 disappears);
#   * `value()` is refused outright for a move-only payload — ``lends a place
#     of type `Res?`, which is move-only`` — because a NAMED `if let` binding
#     over an optional-typed lend is a value read, which is the half of DF-218a
#     that its `_`-only desugar deliberately left open.
#
# So the row waits for two things that belong together: the named-binding form
# of the DF-218a desugar, and a split dispatch whose binding is frame-resident
# by construction rather than by the alloca happening to survive. The DF-210f
# forget stays exactly as it is for them, which is why it is not deleted here.
_SCRUTINEE_TEMPS = ("__hoist", "__match")


def _is_scrutinee_temp(name):
    return isinstance(name, str) and name.startswith(_SCRUTINEE_TEMPS)


def _slot_type(payload):
    """`Slot<payload>` — the frame-field type of a migrated owning encoding."""
    return SawType(TypeKind.STRUCT, struct_name=SLOT_STRUCT_NAME,
                   type_args=[payload])


def _enc_is_slot(enc):
    return enc in ("slot", "slot_self", "slot_closure")


# --------------------------------------------------------------------------- #
# THE DEFERRED CENSUS FAMILIES (design 218 stages 1-4)
# --------------------------------------------------------------------------- #
#
# A field that does NOT migrate to `Slot<T>` keeps the legacy drop-flag encoding
# — and with it the read-plus-`__saw_forget` pairing stage 4 exists to purge.
# The two facts are one fact, so they are decided in one place: `_deferred_family`
# answers WHICH family holds a field back, `_migrated_enc` turns that answer into
# an encoding, and `_FrameBuilder.prepare` records it per field so the forget
# funnel (`_forget_stmt`) can CITE it rather than a comment claiming it.
#
# Naming the family is what makes the purge auditable: an emission whose family
# is `None` is an UNCITED forget, which is the thing stage 4 promises does not
# exist (`tools/test_forget_purge.py` is the gate).
FAM_OPT_CLOSURE = "opt_closure"          # (a) a frame-resident closure
FAM_ADDRESSED = "address-taken"          # (b) `&x`, a nested receiver, a ref arg
FAM_VOID = "void-payload"                # (c) `Slot<Void>` is unbuildable
FAM_FIXED_ARRAY = "fixed-array"          # (d) `a[i] = v` addresses the element
FAM_WINDOW_MOVE = "window-move"          # (e) DF-218h
# (f) `rendering-operand` — RETIRED Aug 22 with DF-218i. The family existed
# because the place system judged a rendering operand a VALUE READ and refused a
# move-only element out of a lend; rendering is a borrow now (`place_uses`
# lowers the operand inside the window), so a rendered frame local migrates to
# `Slot<T>` like any other.
FAM_SCRUTINEE_TEMP = "scrutinee-temp"    # T1/T3 — the DF-210f forget lives here
FAM_SPAWN_CELL = "spawn-cell"            # the design-134 cell: TRUSTED, not deferred

DEFERRED_FAMILIES = (
    FAM_OPT_CLOSURE, FAM_ADDRESSED, FAM_VOID, FAM_FIXED_ARRAY,
    FAM_WINDOW_MOVE, FAM_SCRUTINEE_TEMP, FAM_SPAWN_CELL,
)

# design 221: the synthesized `main`-result -> exit-status mapping (Part C's
# table for the two `Result` shapes). Written by `sawc._synthesize_main_exit_funnel`
# whenever `main` returns a `Result`; called from the two places a `Result`
# main's value is turned into a status — the ambient frame's `_store_result`
# here, and codegen's `_emit_main_exit` for the sync and single-frame paths.
MAIN_EXIT_FUNNEL = "__saw_main_exit_code"

# design 221 unit B3: the std entry a NON-VOID ambient `main` rides. The void
# twin (`__saw_exec_run_root`) is unchanged and is still what a `Void` main uses.
EXEC_RUN_ROOT_STATUS = "__saw_exec_run_root_status"


def _deferred_family(name, enc, address_taken=(), saw_type=None,
                     move_arg_receivers=()):
    """Which deferred family holds this frame field back from `Slot<T>`, or
    `None` if it migrates. THE authority on the question — `_migrated_enc` turns
    this answer into an encoding and `_forget_stmt` cites it.

    Order matters only for the report: a field can qualify twice (an addressed
    closure), and the first answer is the one cited.

    Every owning field migrates except these, each held back by a mechanism a
    later brief owns, none by preference:

      * `opt_closure` — a frame-resident closure is CALLED, and the rewrite
        spells that as an indirect call on the field. A `Slot`'s occupant is
        reached by `value()`, and calling the result directly is not
        expressible (`self.f.value()()` parses as a tuple), so the migration
        owes a materialized local — which needs a statement slot the
        expression rewrite does not always have. A function-typed `__result` is
        held by the same rule, and its motivation does not reach: nothing calls
        a result field. It waits with the family rather than splitting it;
      * a local whose ADDRESS the transform takes — the receiver of a nested
        suspending method call (census P1) and a `ref` argument to a
        sub-frame (census S9's ref half, 218a ruling 7). Both seed a raw
        pointer INTO the local's storage, and a `Slot` has no addressable
        payload spelling: that pointer is exactly the `payload_ptr` 218a
        section 4 deferred;
      * a local a method call CONSUMES another local into — `v.push(move h)`
        (DF-218h). A slot read is a lend, so the call moves inside the window's
        closure, and a `move` of an ENCLOSING local from inside a closure body
        used to have no way to clear that local's drop flag: the checker refused
        it and every way of making it compile double-freed. THE DEFECT IS FIXED
        (DF-218h, ruled Aug 24 — a non-escaping closure's `move` capture
        transfers when the body runs), so this family is no longer BLOCKED; what
        holds it now is staging. Retiring it also migrates design 222 unit 1's
        raw cell write (`_cell_hop_raw`), which is a frame-layout change with
        its own corodiff/irdet surface, and that is the landing this row waits
        for;
      * a SCRUTINEE temp (`__hoistN` / `__matchN`) — see `_SCRUTINEE_TEMPS`.
        This is the one family whose forget is the TRANSFORM's own (DF-210f)
        rather than a rewritten `move`;
      * `Void` — `Slot<Void>` puts a `Void?` in a struct field, and a pointer
        to void is not a type llvmlite will build. A Void local carries nothing
        to release, so the slot buys nothing either;
      * a FIXED ARRAY — `a[i] = v` writes through the element's storage, which
        is addressing the local, the same class as the `&x` family. The write
        would land inside a `value()` window whose flavor the place system
        picks, and an array element assignment through a lend is the same
        addressability work."""
    if enc == "opt_closure":
        return FAM_OPT_CLOSURE
    if name in address_taken:
        return FAM_ADDRESSED
    if name in move_arg_receivers:
        return FAM_WINDOW_MOVE
    if _is_scrutinee_temp(name):
        return FAM_SCRUTINEE_TEMP
    if saw_type is None or saw_type.kind == TypeKind.VOID:
        # An unknown payload type is the same answer as `Void` for the same
        # reason: there is no `Slot<T>` to build. Neither carries anything to
        # release, so the legacy encoding costs nothing but its own bookkeeping.
        return FAM_VOID
    if saw_type.kind == TypeKind.ARRAY:
        return FAM_FIXED_ARRAY
    return None


def _migrated_enc(name, enc, address_taken=(), saw_type=None,
                  move_arg_receivers=()):
    """`(encoding, deferred family)` for a frame field, given the one `_enc_of`
    picked from its type: `Slot<T>` and `None`, unless `_deferred_family` (which
    carries the reasons) names a family that holds it back.

    The two come back TOGETHER because they are one decision. Stage 4's purge
    rests on it: a legacy encoding is exactly a field whose family is named, and
    `_forget_stmt` refuses to emit for a field with no name to cite."""
    fam = _deferred_family(name, enc, address_taken, saw_type,
                           move_arg_receivers)
    if fam is not None:
        return enc, fam
    return _SLOT_ENC_OF_LEGACY.get(enc, enc), None


def _collect_move_arg_receivers(node, out, seen=None):
    """Names used as the RECEIVER of a method call that CONSUMES an argument.

    The DF-218h family (see `_migrated_enc`). Conservative twice over: the
    receiver is taken by its place ROOT, so `pending.items.push(move h)`
    holds `pending` back as well, and the moved argument is not checked for
    whether it is itself a frame local (where the move would lower to a
    `take()` and be fine). A missed migration costs a legacy encoding; a missed
    EXCLUSION costs a program that stopped compiling.
    """
    if seen is None:
        seen = set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MethodCall):
        args = list(getattr(node, 'arguments', None) or [])
        if any(_contains_move(a.value) for a in args):
            root = _place_root_name(node.object)
            if root is not None:
                out.add(root)
    for sub in child_nodes(node):
        _collect_move_arg_receivers(sub, out, seen)


def _contains_move(node, depth=0):
    if node is None or depth > 64:
        return False
    if isinstance(node, MoveExpr):
        return True
    return any(_contains_move(sub, depth + 1) for sub in child_nodes(node))


def _place_root_name(expr):
    """The name of the binding a place expression is rooted at, or None.

    Used to find the locals whose storage the transform addresses: `&x`,
    `&x.field`, `&x[i]` all root at `x`, and it is `x`'s FIELD that has to stay
    addressable."""
    node = expr
    seen = 0
    while node is not None and seen < 32:
        seen += 1
        if isinstance(node, Identifier):
            return node.name
        for attr in ('object', 'expr', 'array_expr', 'tuple_expr', 'value'):
            child = getattr(node, attr, None)
            if isinstance(child, ASTNode):
                node = child
                break
        else:
            return None
    return None


def _slot_static(method, payload, args=(), line=0, column=0):
    """`Slot<payload>.<method>(args)` — the seeding calls `_build_frame_init`
    emits. The type argument is EXPLICIT because a static method on a generic
    type infers nothing from its argument or from the field it initializes."""
    return MethodCall(
        object=Identifier(name=SLOT_STRUCT_NAME, type_args=[payload],
                          line=line, column=column),
        method_name=method, arguments=list(args), line=line, column=column)


def _slot_op(place, method, args=(), line=0, column=0):
    """`<place>.<method>(args)` on a slot-typed place."""
    return MethodCall(object=place, method_name=method, arguments=list(args),
                      line=line, column=column)


def _slot_read(place, method, saw_type, line=0, column=0):
    """A slot READ — `self.x.value()` or `self.x.take()` — as a graft the embed
    contract admits (design 218 stage 1, design 210 unit 3).

    A read is the one slot operation that lands INSIDE a preserved subtree: the
    transform replaces the local `x` wherever the author wrote it, including in
    the middle of a call the declaration pass resolved in the callee's own
    module. `_answered` is the wrong tool for it — a pre-answered node is
    SKIPPED by the post-transform pass, and `value()` has to be checked to be
    lowered at all (the place lowering only sees an accessor the checker
    stamped `place_struct` on).

    So the read declares the other thing that makes a graft safe: it is
    RE-CHECKABLE ANYWHERE. It names the frame struct's own field and a public
    method of `std.compiler.frame`, both present in every driven program and
    neither private to anybody's module, so the entry namespace answers exactly
    what the callee's would. `frame_slot_op` is that claim, read by
    `_check_preserved_embed` (descend to it) and `_close_embed_marks` (do not
    re-open the spine above it).

    `saw_type` — the type of the LOCAL this read replaces, which is also what
    the operation returns — is stamped so the closedness walk finds an answer
    at the root. It does NOT come with `embed_preserved`: the answer is a
    convenience for the walk, and the checker overwrites it with its own.
    """
    node = _slot_op(place, method, line=line, column=column)
    if saw_type is not None:
        node.resolved_type = saw_type
        node.frame_slot_op = True
    return node


def _field_type(saw_type, enc):
    if enc == "ref":
        # design 218 stage 3 (census P2): the FIELD is the handle. The raw
        # pointer stays the PLUMBING — a driver parameter, a spawn helper's
        # parameter, the cast at a nested call's reference argument — so
        # `_ref_ptr_type` is still what those sites build and `_seed_field`
        # wraps it exactly once, where the frame is.
        return _unsaferef_type(saw_type.inner_type)
    if _enc_is_slot(enc):
        # `_clear_escaping` inside the wrapper: it walks Optional/array/tuple/
        # function shapes and would not see through the `Slot<...>` struct, and
        # a `slot_closure` payload still needs its escaping bit cleared and its
        # `sync` bit forced.
        return _slot_type(_clear_escaping(saw_type))
    return _opt(saw_type) if enc in ("opt", "opt_closure") else saw_type


def _enc_unwraps(enc):
    return enc in ("opt", "opt_closure")


def _enc_cleanup(enc):
    """True for a LEGACY encoding whose field carries a drop flag (None/Some):
    a move out must `__saw_forget` it, and its initial (not-yet-live) value is
    `None`. A `Slot` field answers False — it carries its occupancy itself, and
    `take`/`clear` are what move the tag."""
    return enc in ("opt", "self_opt", "opt_closure")


def _enc_owns(enc):
    """True for any encoding whose field OWNS its contents and therefore owes a
    release — the legacy drop-flag trio and the migrated slots alike."""
    return _enc_cleanup(enc) or _enc_is_slot(enc)


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

def _answered(node, saw_type):
    """Stamp a node the transform GRAFTED into a preserved subtree with its own
    answer, so the subtree stays closed (design 210 unit 3).

    The post-transform pass skips a preserved subtree WHOLESALE, so anything the
    transform splices into one has to arrive already typed — this is the one
    place that says so, and the reason every graft site funnels through it
    rather than assigning `resolved_type` in nine places. `saw_type` of None
    means the caller had no answer to give: the node is left plain, the subtree
    is re-opened by the ordinary pass, and `_assert_embed_closed` reports it.

    ENTRY POINTS (every graft into a preserved subtree; process rule 1):
      * `_read_field` — a frame-resident local/param read, in all four
        encodings. The bulk: this is `locals -> frame fields`.
      * `_sub_result_read` — an embedded sub-frame's `__result` move-out, which
        replaces the CALL whose value it carries.
      * `_FrameBuilder._anf_hoist` — the `Identifier(__anfN)` that replaces a
        hoisted suspending call in its original expression position.
      * `_FrameBuilder._rewrite_expr` — the `!` re-applied after `move o!`, and
        the materialized-capture local that replaces a frame name in a closure.
    """
    if saw_type is not None:
        node.resolved_type = saw_type
        node.embed_preserved = True
    return node


# --------------------------------------------------------------------------- #
# design 237: THE POSITION MARKS
# --------------------------------------------------------------------------- #
#
# An annotation the typechecker stamped on a child node ABOUT ITS POSITION
# rather than about the value it holds. The call-site auto-wrap is the whole
# family: `_check_argument_type` decides, at the argument edge, that a bare `T`
# handed to a `T?`/`Result<T, E>` parameter owes a wrapper, and records the
# answer on the ARGUMENT EXPRESSION because that is the node codegen has in
# hand when it materializes the value (`_maybe_autowrap_optional`).
#
# The transform SUBSTITUTES nodes into those positions — a hoisted call becomes
# `Identifier(__anfN)`, a frame-resident local becomes `self.x.take()` — and a
# fresh node carries none of it. That is invisible in ordinary code, because the
# post-transform pass re-derives every argument's wrap. It is NOT invisible in a
# DRIVEN body: design 210 marks the user's own call `embed_preserved` and the
# re-check skips that subtree WHOLESALE, so the answer that travelled with the
# node is the only answer there is. Dropping it emitted the raw payload into a
# wrapper-shaped parameter — `Type of #1 arg mismatch: {i1, i64} != i64` at the
# author's line (DF-224c, and its `Result` twin).
#
# THE RULE IS A TRANSFER, EXACTLY ONCE. The mark describes the POSITION, and
# after the substitution the old node no longer occupies it — it is the
# initializer of `let __anfN = ...`, which is a transfer site of its own and
# would apply the wrapper a SECOND time, into a temp typed for the unwrapped
# value. So `_substitute` moves the marks and clears the source, on the same
# transfers-exactly-once discipline the hoisted temp's ownership follows.
#
# WHAT IS NOT HERE, and why (the annotation set swept, obligation 4).
# `expected_type` is position-derived too, but its consumers are the
# typechecker's literal/collection-literal/const-fold paths and the transform
# never substitutes a LITERAL: a literal holds no suspension, so the hoist does
# not lift one, and `_anf_children`'s side-effecting-sibling lift exempts every
# pure node. Everything else on `Expression` describes the VALUE and belongs to
# the node that keeps holding it: `needs_copy` and `payload_needs_copy` (what
# this read owes its source — `_read_field`'s `frame_owning_read` is the
# transform's own answer for a frame read), `closure_lend` (a closure operand,
# never lifted), `place_value_read`/`place_abstract_read`,
# `enum_variant_literal`, `resolved_type_identity`, and the transform's own
# `frame_place_read`/`frame_move_read`/`embed_preserved`/`frame_slot_op`.
#
# The three are written out one by one rather than looped over a name table: a
# computed `setattr` is invisible to the astgraft gate, and a rule about which
# annotations move is exactly the kind of thing that gate exists to keep
# auditable.


def _substitute(old, new):
    """Return `new`, having MOVED `old`'s position marks onto it.

    THE ONE PLACE the transform puts a different node in a position an earlier
    pass already answered for. Everything the transform builds is unmarked by
    construction (`THE EMBED CONTRACT` family 5), so a substitution that does
    not come through here silently drops the answer.

    ENTRY POINTS (obligation 1 — a funnel names its entries), which together are
    every substitution the transform makes into a position it did not create:
      * `_FrameBuilder._anf_lift` — stage 1's `let __anfN = <expr>` temp, in
        every child position `_map_uncond_children` reaches (design 120)
      * `_FrameBuilder._vc_hoist_to_temp` — stage 2's `let __vchN = <cond>`
        temp for a value-position conditional (design 120 stage 2 / 133 unit B)
      * `_FrameBuilder._head_lift` — a container HEAD lifted to `let __headN`
        (design 224)
      * `_FrameBuilder._hoist_cond` — the `if let`/`guard let` subject (design
        62 G2) and `_maybe_hoist_match` — the `match` scrutinee (design 96)
      * `_FrameBuilder._maybe_hoist_try` — the `try!`/`try`/`try?` subject,
        which becomes a `move` of the temp (design 92)
      * `_FrameBuilder._rewrite_expr` — the frame rewrite's own exit: every
        local/param read that becomes a frame-field read, the receiver that
        becomes `self.__recv.deref()`, and the closure call that becomes an
        indirect field call
    """
    if new is old or not isinstance(old, Expression) or not isinstance(
            new, Expression):
        return new
    if old.autowrap_to_optional is not None:
        new.autowrap_to_optional = old.autowrap_to_optional
        old.autowrap_to_optional = None
    if old.autowrap_to_result is not None:
        new.autowrap_to_result = old.autowrap_to_result
        old.autowrap_to_result = None
    if old.autowrap_result_err:
        new.autowrap_result_err = True
        old.autowrap_result_err = False
    return new


def _read_field(name, encoding, line=0, column=0, owning_read=False,
                move_read=False, saw_type=None):
    """The rewritten read of frame field `name`.

    `saw_type` is design 210's half: the type of the LOCAL this read replaces.
    A frame read of `x` has exactly `x`'s type — the encoding wraps the FIELD,
    and the read unwraps back to the value — so the transform can answer for
    the node it just built instead of leaving it for the post-transform pass to
    re-derive. Stamped together with `embed_preserved`, which is what lets the
    enclosing preserved subtree be skipped WHOLESALE: a graft that carries its
    own answer needs no descent to find it. A caller with no type in hand passes
    None and the node is left for the ordinary pass, which is sound but re-opens
    the subtree — `_assert_embed_closed` reports any that do.

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
    NoCopy payload, and whoever the value lands in OWNS it. It is stamped on
    the returned node WHATEVER SHAPE that node has — the `self.x!` of an
    opt-encoded field, the bare `self.x` of a plain/self_opt one, the
    `self.x[0]` of a reference — because this function is the single place a
    frame read is built and a consumer downstream cannot recover the answer
    from the shape: the rewrite is what deleted the `MoveExpr` the source used
    to be. A consumer that asked the shape leaked a `self_opt` field's payload,
    which reads as a plain MemberAccess and so answered "not a move" to every
    test codegen had (DF-217b).

    ENTRY POINTS that ask for the move mark (process rule 1): the `MoveExpr`
    rewrite in `_rewrite_expr` is the only one — a `move` of a frame-resident
    binding, wherever the expression stands.

    EVERY node this returns is additionally stamped `frame_place_read` (design
    131). The transform rewrites a local into a projection of the frame — a
    MemberAccess, a `self.name!`, a pointer deref — and the language's place rule
    would then re-judge, as an ordinary read out of somebody else's storage, a
    read whose ownership the transform has ALREADY settled on the pre-transform
    AST (which the typechecker saw, and annotated, as the plain local it was).
    Judging it twice would double-retain a Copy payload and reject a
    NoCopy one that the frame is legitimately moving out.

    NONE OF THAT APPLIES TO A `Slot` FIELD (design 218 stage 1). A migrated
    field has exactly two reads — `take()`, which moves the payload out and
    empties the slot in one method body, and `value()`, which lends it as a
    place — and both are ordinary method calls the re-check judges by the
    ordinary rules. So the slot branch stamps NOTHING: no `frame_place_read`
    telling the transfer checkpoint to look away, no `frame_move_read` (M2,
    which deletes with this stage — a `take()` result is an owned temporary the
    existing predicate already answers correctly), and no `frame_owning_read`
    asking codegen for a retain the checker never saw. A tier-wrong choice
    between the two is a compile error on generated code, which is the whole
    point of the migration.
    """
    if _enc_is_slot(encoding):
        return _slot_read(_self_field(name, line, column),
                          "take" if move_read else "value",
                          saw_type, line=line, column=column)
    if encoding == "ref":
        # Census P2, the stage-3 form of design 88's reference field. The read
        # was `self.name[0]` under a `frame_place_read` mark; it is now the
        # handle's own lend, judged like `__recv`'s and like anybody else's
        # `borrows` accessor. A reference binding NEVER owns, so there is no
        # move/borrow distinction to make here — `deref()` serves both.
        return _unsaferef_deref(_self_field(name, line, column), saw_type,
                                line=line, column=column)

    # DEFERRED: opt_closure, address-taken, window-move, rendering-operand,
    # void-payload, fixed-array, scrutinee-temp — THE legacy read, so every
    # deferred family reaches it and it retires with the last of them (218a
    # section 6's M1/M3 row). M2 (`frame_move_read`) rides in the same block and
    # goes with them; it has no consumer of its own left to satisfy beyond
    # `_optional_binding_owns`, which a `take()` result already answers.
    def _marked(node):
        node.frame_place_read = True
        if move_read:
            node.frame_move_read = True
        return node

    acc = _self_field(name, line, column)
    _marked(acc)
    if saw_type is not None:
        # The FIELD's own type, which is the value's type wrapped in whatever
        # the encoding adds. Codegen reads this level directly for a write
        # target (`n += 1` through a `ref` field is `self.n[0]`, and the
        # compound-assign path asks the `self.n` in the middle for its type).
        acc.resolved_type = _field_type(saw_type, encoding)
    if encoding in ("opt", "opt_closure"):
        fu = _marked(ForceUnwrap(expr=acc, line=line, column=column))
        # DEFERRED: opt_closure, address-taken, window-move, rendering-operand,
        # void-payload, fixed-array, scrutinee-temp — M3, the retain codegen
        # supplies because the checkpoint never saw this read. Reached by every
        # family whose field is `opt`/`opt_closure`-encoded, the `__matchN`
        # temps among them (a `self_opt` one reads bare and skips this arm).
        if owning_read:
            fu.frame_owning_read = True
        return _answered(fu, saw_type)
    return _answered(acc, saw_type)


# The expression kinds whose check CONSULTS THE NAMESPACE — the ones whose
# answer depends on WHICH module is asking. Design 210 marks exactly these, and
# `THE EMBED CONTRACT`'s family 2 is their stored answers.
#
# Everything else an expression can be — an operator, a literal, a cast, an
# `if`, a `try` — is judged from the types of its children and needs no scope at
# all, so re-checking one after the splice asks the same question and gets the
# same answer. Marking those too would be strictly worse than useless: the
# post-transform pass ACCUMULATES context as it walks (a `try`'s error type is
# collected from the `try` expressions the walk passes), so skipping a node that
# never needed a namespace loses a fact for no gain — which is exactly what
# turned `let a = try compute(...)` into `cannot assign `Error` to field of type
# `Flaky?``, on a program whose error type had been known all along.
_EMBED_SCOPED_KINDS = (FunctionCall, MethodCall, Identifier, MemberAccess,
                       StructInit, EnumInit)


def _mark_embed_preserved(node):
    """Mark every already-resolved NAMESPACE-CONSULTING expression under `node`.

    Design 210's non-generic path, and the one place the mark is applied. Called
    by `_FrameBuilder.__init__` on the body it is about to lower, BEFORE it
    rewrites a single node — so the mark records exactly what the declaration
    typecheck produced, and everything the transform builds afterwards is
    unmarked by construction and gets typed as ordinary glue.

    The predicate is "pass 1 stamped a type here, and re-deriving it would need
    a scope". `_check_expression` is the one chokepoint that stamps
    `resolved_type`, so an expression carrying one was resolved in its OWN
    module's namespace — and for the kinds in `_EMBED_SCOPED_KINDS` that
    namespace is load-bearing, because the answer names a function, a method, a
    static, a module qualifier or a type that the ENTRY module may not be able
    to see. That is the whole of DF-206e.

    Idempotent, so a body driven twice (an entry-module function that is both a
    root and a sub-frame) marks the same nodes twice with the same result.

    Uniform across user modules and std, per the ruling: the splice does not
    care which module a non-generic body came from, so neither does this.

    Walks EVERY field, not just the structural ones — the one metadata walk in
    the transform that has to. `ArrayLiteral.repeat_count` (the `N` in `[v; N]`)
    is a declared ANNOTATION on purpose: it is compile-time-only, so the hoist
    must not lift it into a `let`. But it is also an expression the author wrote
    and the declaration pass resolved, and a module-private `static` named there
    is exactly as unresolvable after the splice as one named anywhere else. A
    structural-only walk left `[0; RESOLVE_MAX]` out of the contract. Marking is
    idempotent and stamps no structure, so covering annotations costs nothing;
    `seen` guards the aliasing an annotation is allowed to do.
    """
    _mark_embed_preserved_walk(node, set())


def _mark_embed_preserved_walk(node, seen):
    if id(node) in seen:
        return
    seen.add(id(node))
    for sub in _all_child_nodes(node):
        if (isinstance(sub, _EMBED_SCOPED_KINDS)
                and sub.resolved_type is not None):
            sub.embed_preserved = True
        _mark_embed_preserved_walk(sub, seen)


def _all_child_nodes(node):
    """`ast_walk.child_nodes` plus the ANNOTATION fields — every AST node
    reachable from `node`, however it is stored. Only `_mark_embed_preserved`
    wants this: every other walk in the transform is structural by design."""
    if isinstance(node, Argument):
        node = node.value
    if not isinstance(node, ASTNode):
        return
    for f in dataclasses.fields(node):
        val = getattr(node, f.name, None)
        stack = [val]
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                stack.extend(item)
            elif isinstance(item, Argument):
                stack.append(item.value)
            elif isinstance(item, ASTNode):
                yield item


def _is_type_name_base(parent, child):
    """True when `child` is the TYPE NAME or MODULE QUALIFIER that `parent` is
    written on, rather than a value expression of its own (DF-212b unit 2).

    `Cmd.Build`, `Int.max`, `Instant.now()`, `builder.Builder(...)`,
    `lib.Color.Red` — in every one of these the head is a NAME the member check
    consumes as part of one qualified reference. The checker's type-name arms
    all return before the value path (`obj_type = self._check_expression(
    expr.object)`), so the head is never visited as an expression and never
    stamped: `_check_expression` is the one place `resolved_type` is written.
    `_check_preserved_embed`'s docstring says the same thing from the other
    side — descending into such a head reports `undefined variable `builder``.

    THE PREDICATE IS THE ABSENCE ITSELF, deliberately, rather than a list of
    the ~10 family-2 markers the three type-name ladders stamp between them
    (`enum_variant_literal`, `int_limit`, `resolved_static_name`,
    `resolved_module`, `is_static_method_call`, `enum_from_raw`, `int_from`, …).
    A fourth copy of that disjunction would rot the way the first three
    already disagree — `_check_method_call`'s nested-base arm stamps nothing
    where `_check_member_access`'s stamps `resolved_type`. What holds without
    enumerating them: on a program that CHECKED, a head carrying no
    `resolved_type` under a parent that carries one is a head the value path
    never reached, because `visit_Identifier` returns None only for a name that
    is not defined — which is a compile error, not a subtree we ever reach.

    Sound for the wholesale skip because the head is never ASKED anything
    either: a preserved parent is answered from its own stored type and the
    pass does not descend (`_check_preserved_embed`). The head has no answer to
    give and no question to answer.
    """
    if not isinstance(child, (Identifier, MemberAccess)):
        return False
    if child.resolved_type is not None:
        return False
    if not isinstance(parent, (MemberAccess, MethodCall)):
        return False
    if parent.resolved_type is None:
        return False
    return child is parent.object


def _close_embed_marks(decls):
    """Reduce `embed_preserved` to the subtrees that are actually CLOSED — the
    targeted check at the splice boundary (design 210 unit 3).

    The post-transform pass skips a preserved subtree WHOLESALE (it must: a
    module qualifier inside one is an `Identifier` that was never independently
    resolvable, so descending reports `undefined variable `builder``). That is
    only sound where the subtree can answer for itself, so the mark has to mean
    "closed", not merely "was here before the transform ran". This pass makes it
    so, once, bottom-up, over the declarations the transform synthesized.

    A subtree is closed when every expression in it carries a `resolved_type`.
    Two things break that, and neither is an error:

      * a GRAFT the transform made without a type to give — `_answered(x, None)`.
        The enclosing expressions are un-marked here, so the ordinary pass
        re-checks them, and their still-closed children short-circuit. Only the
        spine back to the graft is re-resolved, which is exactly the old
        behaviour scoped down to where it is still needed.
      * a node kind the DECLARATION pass never stamps at all. There are a few —
        `StringInterpolation` and its `FormatPlaceholder`s among them — so
        "declaration-time annotated" is not yet the same as "fully annotated"
        (DF-210c). Those subtrees simply keep taking the ordinary path.

    The walk stops at a `frame_place_read`: that mark is the transform's own
    "this projection is mine" (design 131), and the projection's interior — the
    `SelfExpr` under a `self.x`, the `self.x` under a `self.x!` — is scaffolding
    built to a fixed shape whose ROOT carries the answer any reader wants.

    It stops at a `frame_slot_op` for the migrated half of the same reason
    (design 218 stage 1): `self.x.value()` is that projection in its new
    spelling, its interior is the same fixed scaffolding, and its root carries
    the type of the local it replaced. The difference from the old form is what
    happens NEXT — a slot read is re-checked rather than skipped, which
    `_check_preserved_embed` arranges — and it does not change this walk's
    question, which is only whether the spine ABOVE the graft still holds an
    answer. It does.

    Returns the number of marks cleared, for the `-v` line.
    """
    cleared = [0]

    def closed(node):
        if isinstance(node, Expression) and (node.frame_place_read
                                             or node.frame_slot_op):
            return True
        ok = True
        for sub in child_nodes(node):
            # DF-212b: a member access's TYPE-NAME head is not a value
            # expression, so its missing `resolved_type` is not an opening.
            # Judging it as one re-opened every subtree holding an enum-case
            # literal — `take(Cmd.Build)` in an embedded body lost its marks
            # and re-resolved `take` in a module that cannot see it.
            if _is_type_name_base(node, sub):
                continue
            # No short-circuit: every branch must be visited so its own marks
            # are cleared, not just the first one that fails.
            if not closed(sub):
                ok = False
        if isinstance(node, Expression):
            if node.resolved_type is None:
                ok = False
            if not ok and node.embed_preserved:
                node.embed_preserved = False
                cleared[0] += 1
        return ok

    for d in decls:
        closed(d)
    return cleared[0]


# --------------------------------------------------------------------------- #
# THE FORGET FUNNEL — census D1, and design 218 stage 4's purge
# --------------------------------------------------------------------------- #
#
# `__saw_forget(<place>)` clears an optional field's None/Some tag WITHOUT
# reading the payload. It is correct only when it is paired with exactly one
# prior consuming read, and DF-206f, DF-210f and DF-217h are three sites that
# got the pairing wrong. Stage 1 replaced the pair with `Slot.take()`, which is
# the read and the tag clear in ONE method body, so on a migrated field the
# state "consumed but still flagged live" is not representable.
#
# THE PURGE, exactly as stage 4 lands it. 218a section 9 wrote the exit
# criterion as "emission count hits ZERO", which pre-dates the deferred families
# stages 1-3 measured. The honest form, and what the gate checks:
#
#   * every `__saw_forget` this file emits goes through `_forget_call`, the only
#     EMISSION site in `sawc/` (the builtin's registration, its typecheck and
#     its lowering name it too — those are the consumer half);
#   * `_forget_call` will not emit without a FAMILY — one of `DEFERRED_FAMILIES`
#     — so an emission cites the deferral that kept its field on the legacy
#     encoding, and an emission on a MIGRATED field is a hard error;
#   * `tools/test_forget_purge.py` (the `forgetgate` battery lane) fails on any
#     other spelling and on any citation that is not a named family.
#
# There are FOUR call sites, and all four are the same shape — a field whose
# family is recorded, or a `__result` whose family is `result_defer_family`.
# They all retire together with the last deferred family; nothing else keeps
# them alive.
def _forget_call(place, family):
    """`__saw_forget(<place>)`, cited with the deferred family that owns it.

    ENTRY POINTS (obligation 1): `_FrameBuilder._forget_stmt` (every frame-field
    forget — the rewritten `move`, and the DF-210f scrutinee-temp clears in
    `_optbind_dispatch` and `_split_match`), and the three `__result` sites —
    `_emit_nested_call`'s two arms and `_make_driver`'s move-out."""
    if family not in DEFERRED_FAMILIES:
        raise CoroTransformError(
            f"internal: uncited `__saw_forget` (family {family!r} is not one "
            f"of design 218's deferred census families)")
    return ExpressionStatement(expression=FunctionCall(
        name="__saw_forget", arguments=[Argument(name=None, value=place)]))


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

    A MIGRATED result slot says all of that in one call: `take()` IS the
    transfer, and the sub-frame gives its claim up in the same method body the
    value leaves by. The paired `__saw_forget` at each call site goes with it.
    """
    if _enc_is_slot(result_enc):
        return _slot_op(MemberAccess(object=_self_field(sub), member="__result"),
                        "take")
    # DEFERRED: opt_closure, fixed-array — a CALLEE's legacy `__result`, so the
    # families are the ones a return TYPE can land in: a function type and a
    # fixed array (`examples/coro_result_array_and_closure.saw` covers both).
    # `spawn-cell` cannot reach here — a spawn root is never a nested callee
    # (a function that is both is a dual-role root, whose own frame is not
    # spawn-encoded).
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
        return _read_field(node.name, encmap[node.name], node.line, node.column,
                           saw_type=node.resolved_type)
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

class _MethodTarget(NamedTuple):
    """The answer `_suspending_method_target` gives. THREE values, not two."""
    kind: str                      # 'embed' | 'unsupported' | 'none'
    frame_key: Optional[str]       # 'embed' only — the frame this call embeds
    owner: Optional[str]           # the type the method belongs to, when known
    is_static: bool
    reason: Optional[str]          # 'unsupported' only — why it cannot be named

    @property
    def suspends(self):
        """Does this call SUSPEND? True for both answers that are not 'none' —
        an inexpressible suspending call is still a suspending call, and that
        is the whole of the bug this type exists to close."""
        return self.kind != 'none'


_NOT_SUSPENDING = _MethodTarget('none', None, None, False, None)


def _suspending_method_target(mc, tc):
    """THE call-site classifier for a suspending METHOD call (design 223 unit 1).

    Three-valued, and the third value is the point:

      * EMBED(frame_key)      — a suspending method whose frame this call site
                                can name and embed.
      * UNSUPPORTED(reason)   — a suspending method whose frame it CANNOT name.
                                The caller's job is to RAISE. It must never
                                degrade to a plain call: the callee's park would
                                run outside any frame, where `yield_now` is a
                                no-op, and the cooperative contract would be
                                silently dropped on a program that compiles,
                                runs and prints the right answer.
      * NOT_SUSPENDING        — not a suspending method call at all.

    This replaces `_method_call_owner`, whose single `None` meant BOTH of the
    last two — and all seven consumers below read it as the last one, which is
    how seven probed positions came to compile as plain sync calls (design 223's
    finding; DF-218k/l/m and DF-223a are four faces of it).

    ENTRY POINTS (every consumer; obligation 1 — this is the funnel):
      * `_FrameBuilder._classify_method_call` — the nested-embedding classifier.
        Embeds on EMBED; returns None on UNSUPPORTED so the rejection below
        fires at the same statement.
      * `_FrameBuilder._method_call_suspends` — "is this a suspension?", read by
        the expression-position hoists and by `_reject_buried_suspend_call`.
        True for EMBED *and* UNSUPPORTED.
      * `_FrameBuilder._suspending_method_call` — the statement-shaped twin,
        feeding the top-level rejector.
      * `_FrameBuilder._reject_suspending_method_call` — rejector 1 (a buried
        method call at statement level).
      * `_FrameBuilder._reject_buried_suspend_call` — rejector 2 (an expression
        position no hoist lifted).
      * `_rewrite_drive_sites` — `__saw_drive(recv.m(...))` -> the driver's
        name. The one entry point that does NOT ask this question and reads the
        owner off the call directly, deliberately: an EXPLICITLY driven method
        is a root, so it need not be in the suspending set at all (design 44's
        `__saw_drive` drives whatever it is handed), and asking "does this
        suspend?" there would answer about a different thing.
      * `transform_program._scan_method_callees` — the structural discovery of
        callee frames to build. Enqueues EMBED only: a frame it cannot name is
        a frame it cannot build, and the rejectors are what report that.

    WHAT IT READS. An INSTANCE call carries its owner on the RECEIVER's resolved
    type — `struct_name` for a struct and `enum_name` for an ENUM, which is the
    one-word half of DF-218l (design 145 gave enums extensions, design 74 gives
    methods frames, and this is where the two had not met). A STATIC call has no
    receiver, so the typechecker stamps `static_receiver` on the call (DF-184a).

    A GENERIC receiver or a method-level generic needs an INSTANTIATION to be
    named at all, and the instantiation is not something a classifier can
    conjure — `_promote_nested_generic_methods` builds it before any body is
    lowered and stamps the resulting frame key on the call. So a stamped call is
    EMBED whatever its type arguments look like, and an unstamped one whose
    receiver or call carries type arguments is UNSUPPORTED. That keeps ONE
    question here ("can I name this frame?") and leaves "can this frame be
    built?" where the building happens.
    """
    if getattr(mc, 'is_chan_recv', False):
        # design 62 G3: a cooperative `receive()` lowers INLINE — it suspends
        # and embeds nothing, so it is not this classifier's business.
        return _NOT_SUSPENDING
    susp = getattr(tc, '_suspending_methods_set', None) if tc is not None else None
    if not susp:
        return _NOT_SUSPENDING
    is_static = bool(getattr(mc, 'is_static_method_call', False))
    if is_static:
        owner = getattr(mc, 'static_receiver', None)
        recv_args = getattr(mc.object, 'type_args', None)
    else:
        rt = getattr(mc.object, 'resolved_type', None)
        owner = ((getattr(rt, 'struct_name', None)
                  or getattr(rt, 'enum_name', None)) if rt is not None else None)
        recv_args = getattr(rt, 'type_args', None) if rt is not None else None
    stamped = getattr(mc, 'coro_frame_key', None)
    if stamped is not None:
        return _MethodTarget('embed', stamped, owner, is_static, None)
    if owner is None:
        # No compile-time owner: an existential receiver, a type parameter, a
        # primitive. Nothing here can name a frame, and nothing here KNOWS
        # whether one is owed — the existential case is DF-223b, refused by the
        # typechecker at the dispatch, where the trait is in hand.
        return _NOT_SUSPENDING
    if (owner, mc.method_name) not in susp:
        return _NOT_SUSPENDING
    if recv_args or getattr(mc, 'type_args', None):
        # Un-nameable — but REFUSING is only right for a method that really
        # suspends. The suspending-method set is the conservative one: it holds
        # `Vector.map` and its siblings, which "suspend" solely by the rule that
        # a call through a non-`sync` function value might (design 206's
        # `really_suspending` excludes exactly those). Refusing on a merely
        # conservative answer would reject `v.map({ n in slow(n) })` — where
        # nothing in `map` itself suspends and the closure's own suspension is
        # lowered on its own terms — so a conservative-only generic call keeps
        # the pre-223 answer instead.
        really = (getattr(tc, '_really_suspending_methods_set', None)
                  if tc is not None else None) or set()
        if (owner, mc.method_name) not in really:
            return _NOT_SUSPENDING
        if recv_args:
            return _MethodTarget(
                'unsupported', None, owner, is_static,
                f"its receiver `{owner}<...>` is a generic instantiation this "
                f"call site could not be monomorphized for")
        return _MethodTarget(
            'unsupported', None, owner, is_static,
            f"it is a generic method (`{mc.method_name}<...>`) this call site "
            f"could not be monomorphized for")
    return _MethodTarget(
        'embed',
        _method_frame_key(owner, mc.method_name,
                          getattr(mc, 'resolved_symbol', None)),
        owner, is_static, None)


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
    """The RAW address of the cell — what the spawn helper derives from the
    box's data word and hands the frame constructor. The crossing lives here."""
    return SawType(TypeKind.POINTER, inner_type=_cell_type(fb))


def _cell_ref_type(fb):
    """The frame FIELD's type: `UnsafeRef<__ResultCell<T>>` (design 222 unit 1).

    Census S11/R8/P4 was the last bare `UnsafePointer` a frame stored, read with
    a bare `[0]` deref whose validity argument lived in a comment. It is the same
    argument `__recv` and the `ref` fields make — the referent outlives every
    deref, because the drive structure keeps it alive — so it gets the same
    carrier: one named handle type, one construction funnel, and design 130's
    marking rule holding the obligation.

    What the handle does NOT buy is safety. `UnsafeRef` is an `unsafe struct`
    because a handle to storage somebody else owns is not sound for every input,
    and design 130's own soundness argument ("a function with all-safe parameters
    must be sound for every input; a precondition is spelled as an unsafe-typed
    parameter") is what forbids the safe-wrapper-with-unsafe-accessors shape here
    — that would be `Vector`'s spelling for a type that, unlike `Vector`, does
    not own its referent. A genuinely safe cell needs SHARED OWNERSHIP (the cell
    behind an `Arc`), which is a redesign of task result delivery and not this
    unit's to make."""
    return _unsaferef_type(_cell_type(fb))


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
                 recv_saw_type=None, exit_status_root=False):
        # design 221 unit B3 (DF-220b): `main`'s frame under the AMBIENT
        # executor. It is a spawn root in the layout sense — its result and
        # cancel word live in a group-owned cell it reaches through `__cellp`,
        # because after erasure into a `Box<any Resumable>` nothing outside can
        # read a typed slot — and its result is the process EXIT STATUS, an
        # `Int`, whatever `main` was declared to return. The conversion happens
        # on the way into the slot (`_store_result`), which is why the cell is
        # always `__ResultCell<Int>` and std needs exactly one non-void root
        # entry rather than one per `main` shape.
        self.exit_status_root = exit_status_root
        is_spawn_root = is_spawn_root or exit_status_root
        # design 52b item 2: a spawn-root frame forces its result opt-encoded
        # even for a POD return, so `Task<T>` uniformly holds a
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
        # DF-210f: every SCRUTINEE TEMP this builder hoists, by name — the
        # condition hoist's `__hoistN` and the match hoist's `__matchN`. A hoist
        # temp holds a value the AUTHOR cannot name, so when the binding it
        # feeds CONSUMES the payload, the temp's slot has to give up its claim
        # on it or the frame frees the same buffer twice at teardown. Declared
        # here rather than in either hoister because both write it and they do
        # not run in a fixed order. Still live after design 218 stage 2: the
        # scrutinee temps are the one hoisted family that did NOT migrate, so
        # they keep the drop flag this rule pairs with (`_SCRUTINEE_TEMPS`).
        self._hoist_temps = set()
        # The `__vcN` payload bindings the value-conditional lowering makes,
        # under the `__obN` names the split rename gives them. Single-use, so
        # their read consumes — see `_prep_ob_split`.
        self._vc_ob_bindings = set()
        # design 218b: the scope map + the redefinition record, both written by
        # `_uniquify_bindings`; the scope STACK the CFG walk keeps while it
        # lowers. Declared here so a builder whose `prepare` was skipped answers
        # "no scopes" rather than raising.
        self._scope_binders = {}
        self._redefines = {}
        self._scope_stack = []
        # design 218b E-STMT: the hoisted temps each STATEMENT owns, as
        # `id(stmt) -> (stmt, [temp names])`, written where the ANF hoist lifts
        # them. A statement temp is a statement's, not a frame's.
        self._stmt_temps = {}
        # design 210: record what the DECLARATION typecheck already answered,
        # before this builder rewrites anything. Everything below — the hoists,
        # the state split, the frame-slot rewrites — then produces unmarked
        # nodes, which is exactly the glue the post-transform pass still types.
        # See `_mark_embed_preserved` and `THE EMBED CONTRACT` above.
        if getattr(func, 'body', None) is not None:
            _mark_embed_preserved(func.body)
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
            # design 218 stage 3 (census P1): the FIELD is an `UnsafeRef<T>`;
            # the raw pointer survives as the thing the handle is built over —
            # the drive-site cast, the driver's own parameter, and the dead
            # sub-frame's null placeholder. Two types because the crossing has
            # not moved: `recv_ptr_type` is where the address still lives, and
            # `recv_type` is what the frame stores.
            self.recv_ptr_type = (SawType(TypeKind.POINTER, inner_type=pointee)
                                  if self.has_recv else None)
            self.recv_pointee = pointee if self.has_recv else None
            self.recv_type = (_unsaferef_type(pointee)
                              if self.has_recv else None)
            # design 222 unit 2: the DRIVER's parameter type. The address still
            # crosses at the same place; what the CALLER writes is a reference.
            self.recv_ref_type = (SawType(TypeKind.REFERENCE, inner_type=pointee,
                                          reference_mutable=False)
                                  if self.has_recv else None)
        else:
            self.name = func.name
            self.recv_type = None
            self.recv_ptr_type = None
            self.recv_pointee = None
            self.recv_ref_type = None
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
        # design 221 unit B3: what `main` was DECLARED to return, kept so
        # `_store_result` knows whether the value crossing into the slot needs
        # the exit-code mapping. The slot itself is an `Int` from here on.
        self.main_declared_ret = None
        if exit_status_root:
            self.main_declared_ret = self.ret
            self.ret = SawType(TypeKind.INT)
            self.is_void = False
        # DF-134a: does this frame ARM a reactor registration itself? Only a body
        # containing a literal `io_wait` does — a frame that merely embeds a
        # suspending callee never registers anything, and the callee's own frame
        # carries (and releases) its registration. Computed from the untouched
        # body, before any lowering rewrites the call away. Frames that answer
        # False get no `__io_fd`/`__io_dir` fields and no disarm in `release`,
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
        # Every container kind, from the one enumeration (`ast_walk`): a hoist
        # is a plain descent — it rewrites a statement into two within the
        # block it already sits in — so there is no container it should stop at.
        for block in control_blocks(s):
            self._hoist_block(block)

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
        # The plain suspending-call form, of every kind: `_is_suspension_point`
        # is THE predicate (design 224), shared with the match and try hoists and
        # with the general ANF hoist. A subject that is not itself a call but
        # CONTAINS a suspension is the head hoist's (`_hoist_container_heads`).
        if self._is_suspension_point(cond):
            tmp = f"__hoist{self._hoist_ctr}"
            self._hoist_ctr += 1
            self._hoist_temps.add(tmp)          # DF-210f
            let_stmt = LetStatement(name=tmp, type_annotation=None, value=cond,
                                    mutable=False, line=cond.line, column=cond.column)
            ident = Identifier(name=tmp, line=cond.line, column=cond.column)
            # Carry the optional type so downstream typing of the temp field is
            # exact (its value's `resolved_type` is the callee's `T?`).
            ident.resolved_type = getattr(cond, 'resolved_type', None)
            return (let_stmt, _substitute(cond, ident))
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
        for block in control_blocks(s):
            self._hoist_try_block(block)

    def _maybe_hoist_try(self, s):
        tnode = None
        if isinstance(s, LetStatement) and isinstance(s.value, TryExpr):
            tnode = s.value
        elif (isinstance(s, ExpressionStatement)
              and isinstance(s.expression, TryExpr)):
            tnode = s.expression
        elif isinstance(s, ReturnStatement) and isinstance(s.value, TryExpr):
            tnode = s.value
        if tnode is None or not self._is_suspension_point(tnode.expr):
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
        tnode.expr = _substitute(inner, mv)
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
        for block in control_blocks(s):
            self._hoist_match_block(block)

    def _maybe_hoist_match(self, s):
        m = None
        if isinstance(s, ExpressionStatement) and isinstance(s.expression, MatchExpr):
            m = s.expression
        elif isinstance(s, LetStatement) and isinstance(s.value, MatchExpr):
            m = s.value
        elif isinstance(s, ReturnStatement) and isinstance(s.value, MatchExpr):
            m = s.value
        if m is None or not self._is_suspension_point(m.matched_expr):
            return [s]
        inner = m.matched_expr
        tmp = f"__match{self._match_ctr}"
        self._match_ctr += 1
        self._hoist_temps.add(tmp)          # DF-210f — see `_optbind_dispatch`
        let_stmt = LetStatement(name=tmp, type_annotation=None, value=inner,
                                mutable=False, line=inner.line, column=inner.column)
        ident = Identifier(name=tmp, line=inner.line, column=inner.column)
        # Carry the callee's result type so the driven-call classification and the
        # match lowering both see the exact instantiation.
        ident.resolved_type = getattr(inner, 'resolved_type', None)
        m.matched_expr = _substitute(inner, ident)
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

    # A statement-position CONTAINER, whose BLOCKS `_anf_recurse` descends into
    # and whose HEAD `_hoist_container_heads` already lifted (design 224). Never
    # entered as a value here; listed beside `_ANF_CONDITIONAL` so the one
    # opaque-value test below covers both reasons a value belongs to another
    # pass.
    _ANF_CONTAINER = (WhileExpr, IfLetExpr)
    _ANF_OPAQUE = _ANF_CONDITIONAL + _ANF_CONTAINER

    # THE STATEMENT ENTRY TABLE (design 237). Every LEAF statement class whose
    # value expression the ANF hoist enters, as `(class, field, lift_self)`:
    #
    #   * `lift_self=False` — a top-level suspending call in this slot is
    #     ALREADY a shape `_classify_call` embeds and drives (`let x = f()`,
    #     `return f()`, a bare `f()` statement), so only its CHILDREN linearize.
    #   * `lift_self=True` — the slot has no supported top-level form, so a
    #     suspending call there is lifted to its own `let __anfN = f()` first.
    #     `x = s()`, `n += s()` (design 224 G3) and `let (a, b) = pair()`
    #     (DF-217g) are the three.
    #
    # It is a TABLE rather than an if-chain because the set is the whole claim:
    # design 120 promises every expression position, and the hand-enumerated
    # version covered four of these six — `DestructuringLet` was simply absent,
    # which is the entirety of DF-217g. A statement class NOT here holds no
    # value the hoist owns: `break`/`continue` carry none, a container's head is
    # `control_heads`' (design 224), a `lend` place is storage the accessor
    # names rather than a value, and `guard let`'s subject is a head too.
    _ANF_STMT_ENTRIES = (
        (LetStatement, 'value', False),
        (DestructuringLet, 'value', True),
        (AssignStatement, 'value', True),
        (CompoundAssignStatement, 'value', True),
        (ReturnStatement, 'value', False),
        (ExpressionStatement, 'expression', False),
    )

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
        for block in control_blocks(s):
            self._anf_block(block)

    def _anf_stmt(self, s):
        """Hoist buried suspending calls out of a leaf statement's value
        expression into preceding `let __anfN = ...` temps (evaluation order),
        returning the replacement statement list.

        ONE entry set, `_ANF_STMT_ENTRIES` — read it for which statement
        classes reach the hoist and why nothing else does. A value another pass
        owns is skipped here: a CONDITIONAL construct is stage 2's
        (`_lower_value_conditionals` lowers it to branches first) and a
        statement-position CONTAINER is `_anf_recurse`'s blocks plus design
        224's heads."""
        out = []
        for cls, field, lift_self in self._ANF_STMT_ENTRIES:
            if not isinstance(s, cls):
                continue
            value = getattr(s, field)
            if value is None or isinstance(value, self._ANF_OPAQUE):
                break
            setattr(s, field, self._anf(value, out, lift_self=lift_self))
            break
        # design 218b E-STMT: remember which temps this statement owns, so the
        # CFG walk can release them where the statement ends. The temps were
        # lifted OUT of `s`, so `s` is the statement whose end they die at.
        if out:
            names = [t.name for t in out if isinstance(t, LetStatement)]
            if names:
                self._stmt_temps[id(s)] = (s, names)
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
        if lift_self and self._is_suspension_point(expr):
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
        return _substitute(expr, ident)

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
            if self._is_suspension_point(expr) and not self._is_addressable(obj):
                return self._anf_lift(obj, out)
            return obj
        self._map_uncond_children(expr, do, receiver_hook=receiver_hook)

    def _map_uncond_children(self, expr, fn, receiver_hook=None):
        """Apply `fn` to each UNCONDITIONAL child expression position of `expr`,
        writing the result back, in EVALUATION ORDER.

        THE CHILD-POSITION FUNNEL (design 120, closed by design 237). Design 120
        promises a suspending call embeds in ANY expression position, which is a
        position-quantified claim, so this dispatch is the ONE place the set of
        positions is written down and every entry below reaches the same set.

        ENTRY POINTS (obligation 1 — a funnel names its entries):
          * `_uncond_children` — the read-only view, built by running this with
            an identity mapper so the two can never drift
          * `_anf_children` — stage 1's linearizer (design 120), entered from
            `_anf` for every statement class in `_ANF_STMT_ENTRIES`
          * `_vc_lift_nested` — stage 2's buried-conditional lift (design 133
            unit B), which walks the same positions looking for `??`/`&&`/`||`/
            value-`if` instead of for calls

        The RHS of `&&`/`||` is skipped: it is evaluated conditionally, so nothing
        may be lifted out of it (the stage-2 branch lowering owns that position).
        `receiver_hook`, when given, post-processes a method call's receiver right
        after `fn` and before the arguments, keeping the receiver's own hoists
        ahead of the arguments'.

        A node type absent from this dispatch has NO unconditional children, and
        the three kinds that qualify are all leaves or somebody else's: a literal
        and a name hold no expression; `IfExpr`/`MatchExpr`/`NilCoalesce`/the
        optional-chain family/`TryCatchExpr`/`ClosureExpr` are CONDITIONAL
        (`_ANF_CONDITIONAL`, stage 2's); `WhileExpr`/`IfLetExpr`/`ForLoop` are
        statement-position containers whose head is `control_heads`' and whose
        blocks are the block walks'. `RangeExpr` is the one shape that is a head
        and never a value — `let r = 0..n` names no type — so `_head_lift` owns
        its endpoints and it is deliberately not here. `ArrayLiteral.repeat_count`
        is compile-time-only and must NOT be lifted (see its annotation).
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
        elif isinstance(expr, (ResultOkWrap, ResultErrWrap, ErasedErrWrap)):
            # design 237: the RESULT WRAP family, the `Optional` wrap's three
            # siblings. The typechecker INSERTS one of these around the value of
            # a `return`/tail/arm in a `Result`-returning function (design 30's
            # auto-wrap), so `return f()` at `-> Result<Int, E>` is not a
            # `FunctionCall` in the return slot at all — it is a wrap NODE over
            # one. Without this branch the walk stopped at the wrapper, the call
            # under it stayed buried, and `_collect_calls` refused a shape design
            # 120 says works: the bogus refusal S2 filed as "return f() under
            # Result auto-wrap".
            expr.value = fn(expr.value)
        elif isinstance(expr, TryExpr):
            # Only the stage-2 walk reaches a TryExpr here; `_anf` peels its
            # subject itself before this dispatch ever sees one.
            expr.expr = fn(expr.expr)

    def _is_suspension_point(self, expr):
        """THE question "is `expr` itself a suspension point?" — one definition,
        all four kinds the transform lowers: a suspending free-function call, a
        blocking-extern call (design 103's offload), a suspending METHOD call
        (design 84/223), and a cooperative channel `receive()` (design 62 G3).

        There were TWO of these (DF-224a's G2), and they disagreed: the one the
        narrow hoists asked omitted the channel receive and the blocking extern,
        while the one the general ANF hoist asked included both. So the shapes
        only a narrow hoist reaches — an `if let`/`guard let` subject, a `match`
        scrutinee, a `try!`/`try`/`try?` subject — were refused for a receive
        where they are perfectly expressible, and where design 104 had already
        CFG-split the binding they were not refused either: the receive lowered
        as a plain call whose `yield_now` no-ops, a 100%-CPU spin.

        A GENERIC free-function call answers False on purpose: its instantiation
        is not monomorphized at a nested position (design 70 A5-rest), and
        `_classify_call` raises for it by name rather than letting a hoist lift
        it into a temp nothing can drive.

        ENTRY POINTS (obligation 1 — a funnel names its entries):
          * `_hoist_cond` — the `if let`/`guard let` subject hoist (design 62 G2)
          * `_maybe_hoist_match` — the `match` scrutinee hoist (design 96)
          * `_maybe_hoist_try` — the `try!`/`try`/`try?` subject hoist (design 92)
          * `_anf` / `_anf_children` — the general expression-position hoist
            (design 120), including the receiver-addressability hook

        NOT an entry point, and deliberately: `_spans_suspension` asks the
        TRANSITIVE question ("does this subtree contain one?") and adds the
        suspend PRIMITIVES (`__saw_suspend`/`yield_now`/`sleep`), which are
        statements rather than values and so are never lifted to a temp.
        """
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
        # design 196 unit 3: a `try { } catch { }` in VALUE position. Two arms
        # and one result, exactly like the value `if` above — the arm selection
        # is an error edge rather than a condition, which changes nothing here.
        if isinstance(e, TryCatchExpr):
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
        for block in control_blocks(s):
            self._vc_block(block)

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
        return _substitute(expr, ref)

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
        if isinstance(s, (LetStatement, AssignStatement, DestructuringLet)):
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
        # design 224 (G3): a COMPOUND assignment's RHS. `n += (a ?? slow())` has
        # no branch shape of its own to lower into — a per-arm `n += …` would
        # read the target on each path — so the conditional is lifted whole to a
        # preceding temp and the operator applies to that. `_vc_lift_here` does
        # both cases: the value IS a conditional, or merely contains one.
        if (isinstance(s, CompoundAssignStatement) and s.value is not None
                and self._spans_suspension(s.value)):
            pre = []
            s.value = self._vc_lift_here(s.value, pre)
            if pre:
                return pre + [s]
            return [s]
        # design 237: a DESTRUCTURING let's RHS, on the compound assignment's
        # terms and for the same reason — `let (a, b) = <conditional>` has no
        # branch shape of its own to lower into, because the sink would have to
        # destructure per arm. Lifting the conditional whole to a preceding temp
        # leaves `let (a, b) = __vchN`, which is the shape the split already
        # lowers. `_vc_lift_here` does both cases: the value IS a conditional,
        # or merely contains one.
        if (isinstance(s, DestructuringLet) and s.value is not None
                and self._spans_suspension(s.value)):
            pre = []
            s.value = self._vc_lift_here(s.value, pre)
            if pre:
                return pre + [s]
            return [s]
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
        chain_op = getattr(oca, 'op', None)
        if chain_op is not None:
            # `x?.y += <suspending>` (design 227 unit 4): the mutation of the
            # copied-out payload is the compound one; everything else about the
            # None-guarded read-modify-writeback is unchanged.
            mutate = CompoundAssignStatement(target=write_target, op=chain_op,
                                             value=oca.value,
                                             line=line, column=col)
        else:
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
        if isinstance(cond, TryCatchExpr):
            # design 196 unit 3: `let r = try { … } catch { … }` becomes the
            # statement form with each arm's tail assigning the sink, which the
            # CFG split then lowers exactly as it lowers a written statement.
            self._attach_sink_block(cond.try_block, sink)
            self._attach_sink_block(cond.catch_block, sink)
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
    # design 224: the CONTAINER HEAD slots
    # ------------------------------------------------------------------ #
    #
    # A container's head is the expression it evaluates OUTSIDE every one of its
    # blocks (`ast_walk.control_heads` is the enumeration; `control_blocks` is
    # the other half). Every pass above walks blocks; none walked heads, so a
    # suspension in one was neither embedded nor refused — DF-224a's six
    # silent-hang cells, measured at 100% CPU because a `Channel.receive()`
    # lowered as a plain call spins in a `try_receive` + `yield_now` loop whose
    # `yield_now` has no frame to park in.
    #
    # FIVE of the six heads are evaluated ONCE, unconditionally, before the
    # container branches — which is precisely the `let x = <expr>` position the
    # existing machinery already drives. So the answer for them is a lift, and
    # the cells become WORKING rather than refusing. The sixth, a `while`
    # CONDITION, is evaluated before EVERY iteration, so a lift above the loop
    # would freeze it on the first answer; it is rewritten into the loop body
    # instead (see `_while_head_into_body`), which needs only `break` — machinery
    # the CFG walk has had since design 96.
    #
    # Runs AFTER `_lower_value_conditionals` (whose branch lowering MAKES
    # statement-position containers, and a value `if` with a suspending condition
    # produces one with a spanning head) and BEFORE `_anf_hoist` (which then
    # linearizes whatever the lifted `let` still buries). Each lifted `let` is
    # emitted THROUGH `_vc_stmt`, so a head that is itself a short-circuit
    # (`if a && slow()`) is lowered to the branch shape exactly as the same
    # expression in `let` position would be — the guard survives the lift.

    def _hoist_container_heads(self):
        """Lift every container HEAD the state machine cannot hold in place into
        a preceding driven statement.

        TWO reasons a head has to move, and they are the same reason twice — the
        head is evaluated OUTSIDE every block the container owns, so anything in
        it that needs a statement of its own has nowhere to be:

          1. It SPANS A SUSPENSION. The lift puts the suspension where the state
             split can express it (design 224).
          2. It carries a PROPAGATING `try` (DF-245d). `_lower_stmt` dispatches
             one to design 196 unit 3's error landing, and the landing wraps a
             STATEMENT — so a `try` left in a head is lowered inside the state,
             with its propagation target read off `resume() -> Poll`. That is
             the same failure DF-244a found under `return`, in both its faces:
             the typechecker's second pass names `Poll`, a type the author never
             wrote, or codegen reaches `_create_result_err_for_return` inside
             `resume` and ICEs.

        THE INVARIANT this establishes, which `_collect_calls` then checks: after
        this pass no statement-position container has a head that spans a
        suspension. A head that still does is refused there, never descended
        past."""
        self._head_ctr = 0
        self._head_block(self.func.body)

    def _head_block(self, block):
        new_stmts = []
        for s in block.statements:
            new_stmts.extend(self._head_stmt(s))
        block.statements = new_stmts
        for s in block.statements:
            for b in control_blocks(s):
                self._head_block(b)

    def _head_stmt(self, s):
        """Return the replacement statement list for `s`."""
        heads = [(owner, field) for (owner, field) in control_heads(s)
                 if self._head_must_move(getattr(owner, field))]
        if not heads:
            return [s]
        ctrl = s.expression if isinstance(s, ExpressionStatement) else s
        if isinstance(ctrl, WhileExpr):
            return [self._while_head_into_body(s, ctrl)]
        out = []
        for owner, field in heads:
            setattr(owner, field, self._head_lift(getattr(owner, field), out))
        # The lifts can themselves BE containers (`_vc_stmt` lowers a
        # short-circuit head into an `if`), whose own heads are this pass's job
        # too. Terminating: each round replaces a spanning head with a plain
        # name, and a `let`'s value is not a head.
        settled = []
        for st in out:
            settled.extend(self._head_stmt(st))
        return settled + [s]

    def _head_must_move(self, head) -> bool:
        """Whether `head` — a container's head expression — has to be lifted out
        of the head slot. The two clauses `_hoist_container_heads` documents.

        The `try` clause is DF-245d, and it is DF-244a's second half at the other
        position: `_norm_block` had to call a tail carrying a propagating `try`
        "spanning" for exactly this reason, because the lowering keys on
        STATEMENTS and the landing dispatch wraps one. A head is the one other
        place an expression sits outside every block its construct owns."""
        if head is None:
            return False
        return (self._spans_suspension(head)
                or self._has_propagating_try(head))

    def _head_lift(self, head, out):
        """Replace `head` with a read of a preceding `let __headN = <head>`,
        appending the statement(s) to `out`.

        A `for` RANGE is the one head that is not a value — `let r = 0..n` names
        no type — so its ENDPOINTS are lifted instead, in source order. A left
        endpoint that is merely side-effecting (not suspending) is lifted beside
        a suspending right one for DF-133a's reason: leaving it in place would
        move its evaluation AFTER the suspension the author wrote to its right.
        The endpoints ask `_head_must_move`, the same question the slot itself
        was selected by, so a `for i in 0..(try n())` is lifted for the `try`
        exactly as it is for a suspension (DF-245d).
        """
        if isinstance(head, RangeExpr):
            if self._head_must_move(head.end):
                if not self._anf_is_pure(head.start):
                    head.start = self._head_lift(head.start, out)
                head.end = self._head_lift(head.end, out)
            elif self._head_must_move(head.start):
                head.start = self._head_lift(head.start, out)
            return head
        tmp = f"__head{self._head_ctr}"
        self._head_ctr += 1
        # DF-210f: an optional-binding subject lifted here is read once, by the
        # dispatch `_optbind_dispatch` builds, exactly as the design-62 and
        # design-96 hoists' temps are.
        self._hoist_temps.add(tmp)
        line = getattr(head, 'line', 0) or 0
        col = getattr(head, 'column', 0) or 0
        t = getattr(head, 'resolved_type', None)
        out.extend(self._vc_stmt(LetStatement(
            name=tmp, type_annotation=None, value=head, mutable=False,
            line=line, column=col)))
        ident = Identifier(name=tmp, line=line, column=col)
        # Carry the head's own type so the temp's frame field is typed exactly
        # (frame-local typing, call classification and codegen all read it).
        ident.resolved_type = t
        return _substitute(head, ident)

    def _while_head_into_body(self, s, w):
        """Rewrite a `while <cond> { body }` whose CONDITION spans a suspension
        into the conditionless loop whose first act is to evaluate it:

            while {
                let __headN = <cond>
                if __headN { <body> } else { break }
            }

        The condition is evaluated once per iteration, where the author wrote
        it, so a `continue` in the body re-evaluates it (it jumps to the loop
        top, which is now the `let`) and a `break` in the body still leaves the
        loop. Lifting it to a preceding `let` — the answer for every other head
        — would evaluate it ONCE and run the loop on that answer forever.

        Nothing new is needed downstream: `_split_while` already lowers the
        conditionless form (design 52), `_split_if` already carries `loop_ctx`
        into both branches, and `break` has been a state goto since design 96.
        """
        cond = w.condition
        line = getattr(cond, 'line', 0) or 0
        col = getattr(cond, 'column', 0) or 0
        pre = []
        ident = self._head_lift(cond, pre)
        gate = IfExpr(
            condition=ident, then_branch=w.body,
            else_branch=Block(
                statements=[BreakStatement(line=line, column=col)],
                final_expr=None),
            line=line, column=col)
        w.condition = None
        w.body = Block(
            statements=pre + [ExpressionStatement(expression=gate,
                                                  line=line, column=col)],
            final_expr=None)
        return s

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
        # design 218b: the SCOPE MAP. `_uniq_walk_block` already reifies one
        # dict per block scope and throws it away; keeping it is what lets the
        # CFG walk emit a release at every scope EXIT (`_scope_release_seq`).
        # Keyed by `id(block)` with the block itself pinned in the value, so a
        # block that dies between `prepare` and lowering can never have its id
        # reused by a later one and answer for it.
        self._scope_binders = {}
        # design 107 same-scope redefinition: `let s = derive(move s)` mints a
        # SECOND binding, and the REPLACED one dies at the redefinition point
        # (codegen's `_drop_redefined_same_scope`). This is the one place the
        # transform knows it happened — the mint-on-collision arm of
        # `_uniq_bind` — so it records `id(stmt) -> (stmt, [replaced names])`
        # for the E-REDEF edge to consume.
        self._redefines = {}
        self._uniq_walk_block(self.func.body, [])

    def _uniq_fresh(self, name):
        while True:
            new = f"{_UNIQ_PREFIX}{self._uniq_ctr}_{name}"
            self._uniq_ctr += 1
            if new not in self._uniq_taken:
                return new

    def _uniq_bind(self, name, scope, callable_=False, second_view=False):
        """Introduce `name` into `scope`, renaming it when the name is already
        bound somewhere else in this body. Returns the effective name.

        `second_view=True` marks the ONE caller that is re-binding a name this
        same scope already holds because the parser gave it two views of one
        binding (a plain enum arm's `bindings` list AND its `pattern` carry the
        same names) — it reuses the first view's mapping rather than minting a
        second field. Every other caller mints: a name already in the SAME scope
        is a design-107 same-scope REDEFINITION (`let s = derive(move s)`), i.e.
        a second, distinct binding that owes a field of its own. Reusing there
        collapsed both onto one slot and double-freed the consumed original
        (DF-217a)."""
        if name == "_" or name.startswith("__"):
            # `_` binds nothing, and a `__`-prefixed name is a compiler temp
            # (the lexer reserves the prefix) — unique already.
            return name
        if second_view and name in scope:
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
        binders = []
        for s in block.statements:
            self._uniq_walk_stmt(s, inner, scope, binders)
        if block.final_expr is not None:
            self._uniq_walk(block.final_expr, inner)
        # The scope map's one write. A binder is any node carrying the binding's
        # EFFECTIVE name in a `.name` attribute — the statement itself for a
        # `let`/`guard let`, a pattern node per leaf for a destructuring `let`.
        # Nodes, not strings: `_mark_optional_binding_splits` RENAMES a split
        # `guard let`'s binding after this pass, and reading `.name` at emission
        # time follows that rename for free.
        self._scope_binders[id(block)] = (block, binders)

    def _note_redefinition(self, stmt, scope, name):
        """Record that `stmt`'s binding of `name` REPLACES a live same-scope
        binding (design 107), for the E-REDEF edge."""
        prior = scope.get(name)
        if prior is None:
            return
        entry = self._redefines.get(id(stmt))
        if entry is None or entry[0] is not stmt:
            entry = (stmt, [])
            self._redefines[id(stmt)] = entry
        entry[1].append(prior[0])

    def _uniq_walk_stmt(self, s, scopes, scope, binders):
        """A statement that BINDS into its enclosing block's scope (its binding
        is visible to every later statement of that block) — everything else
        goes through the general walk.

        `binders` accumulates this block's own bindings in DECLARATION order;
        `_scope_release_seq` walks it backwards, which is the LIFO order
        codegen's `_cleanup_scope` uses for a sync scope."""
        if isinstance(s, LetStatement):
            self._uniq_walk(s.value, scopes)
            self._note_redefinition(s, scope, s.name)
            s.name = self._uniq_bind(s.name, scope,
                                     callable_=_is_function_valued(s))
            binders.append(s)
            return
        if isinstance(s, DestructuringLet):
            self._uniq_walk(s.value, scopes)
            for pat in _pattern_binding_nodes(s.pattern):
                self._note_redefinition(s, scope, pat.name)
                pat.name = self._uniq_bind(pat.name, scope)
                binders.append(pat)
            return
        if isinstance(s, GuardLetStatement):
            self._uniq_walk(s.optional_expr, scopes)
            # The else branch runs on the path where the binding does NOT
            # exist, so it is walked before the bind.
            self._uniq_walk_block(s.else_branch, scopes)
            if s.pattern is not None:
                for pat in _pattern_binding_nodes(s.pattern):
                    pat.name = self._uniq_bind(pat.name, scope)
                    binders.append(pat)
            else:
                s.name = self._uniq_bind(s.name, scope)
                binders.append(s)
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
                        # The pattern is the SECOND view of the names
                        # `arm.bindings` just bound — one binding, one field.
                        pat.name = self._uniq_bind(pat.name, bound,
                                                   second_view=True)
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
            # The catch block binds `error` (or its explicit name) implicitly, so
            # it goes through `_uniq_bind` like any other binding: a SPLIT
            # try/catch carries the caught error in a frame FIELD named after
            # this binding (design 196 unit 3), and two catch blocks in one body
            # both spelling it `error` would then share one field. Binding it
            # here renames the second (and any user local that got there first),
            # and writing the result back into `error_binding` is what tells the
            # re-typecheck and codegen which name the catch scope defines.
            bound = {}
            node.error_binding = self._uniq_bind(node.error_binding or "error",
                                                 bound)
            self._uniq_walk_block(node.catch_block, scopes + [bound])
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
        """Find every `if let`/`guard let` that must be CFG-SPLIT and mark it
        `_coro_split` (so `_collect_frame_locals`, `_collect_calls`, and the CFG
        walk all treat it as a split point), renaming its binding to a fresh
        unique frame field.

        THE SPLIT PREDICATE — two clauses, and DF-233a was the second one
        missing:

          1. The binding's SCOPE crosses a state boundary. An `if let` splits
             when either branch spans a suspension; a `guard let` splits when
             its ENCLOSING block spans (the binding lives on into the rest of
             that block, which is what may cross the suspension).
          2. design 96 (DF6): the construct carries a `break`/`continue` for an
             ENCLOSING suspension-spanning loop. Lowered in place it keeps a raw
             `break`/`continue`, which escapes the resume method's `while true`
             DISPATCH loop instead of the logical loop. `_lower_stmt` already
             applies this clause to `if`, `match` and `try`/`catch`
             (`needs_ctrl_split`) — but those three CAN be split on the spot,
             while an `if let`/`guard let` cannot: its split needs the binding
             RENAMED to a frame field first, which only happens here. So the
             clause has to be decided in this pass, and until DF-233a it was
             not: `while true { if let x = f() { … } else { break } }` in a
             suspending body hung, and the `guard let`-`break` drain idiom hung
             wherever the guard's own block did not itself span.

        The DESCENT is a PLAIN one — the split decision above is per container,
        but "which blocks does this statement own" is not — so it takes
        `ast_walk.control_blocks` rather than a hand-rolled dispatch. The
        hand-rolled one it replaced listed six container kinds and missed
        `try`/`catch` (DF-233a again): an `if let` whose body spanned a
        suspension inside a `try` block was never marked, so the CFG walk did
        not descend into it and the suspension was REJECTED as a
        "nested/expression position" — a legal program refused."""
        self._optbind_ctr = 0
        self._mark_ob_block(self.func.body, False)

    def _mark_ob_block(self, block, in_spanning_loop):
        """`in_spanning_loop`: is this block inside a loop that spans a
        suspension AND owns the `break`/`continue` written here? A loop OWNS the
        jumps directly inside it, so each `while`/`for` re-decides the flag for
        its own body; every other container just passes it through."""
        block_spans = self._spans_suspension(block)
        for s in _stmt_positions(block):
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfLetExpr):
                then_spans = self._spans_suspension(ctrl.then_branch)
                else_spans = (ctrl.else_branch is not None
                              and self._spans_suspension(ctrl.else_branch))
                if (then_spans or else_spans
                        or (in_spanning_loop and self._has_loop_ctrl(ctrl))):
                    self._prep_ob_split(ctrl, ctrl.then_branch, [], None)
            elif isinstance(s, GuardLetStatement):
                if (block_spans
                        or (in_spanning_loop and self._has_loop_ctrl(s))):
                    # The binding's scope is the REST of the enclosing block after
                    # this guard (statements + the block's trailing expression).
                    # Index by identity — dataclass `==` could match an earlier
                    # structurally-equal statement.
                    idx = next(i for i, st in enumerate(block.statements)
                               if st is s)
                    self._prep_ob_split(
                        s, None, block.statements[idx + 1:], block)
            inner = (self._spans_suspension(ctrl)
                     if isinstance(ctrl, (WhileExpr, ForLoop))
                     else in_spanning_loop)
            for inner_block in control_blocks(s):
                self._mark_ob_block(inner_block, inner)

    def _prep_ob_split(self, node, scope_block, scope_stmts, scope_final_owner):
        """Mark `node` for CFG-splitting and rename its binding to a fresh unique
        name, rewriting the binding's uses in its scope (`scope_block` for an
        `if let` then-branch, or `scope_stmts` + the owner block's `final_expr` for
        a `guard let` continuation). A tuple-pattern binding across a suspension is
        not supported (rejected cleanly). A nested re-binding of the same name in
        the scope (a design-100 derived shadow) is likewise unsupported here and
        rejected, so no use is ever mis-renamed."""
        if getattr(node, 'pattern', None) is not None:
            # design 233: a `while let` lowers to an `if let`, so ask the node
            # which one the author wrote — the limit is inherited verbatim, and
            # the message has to name the construct on the line.
            if isinstance(node, IfLetExpr):
                kind = "while let" if node.while_let else "if let"
            else:
                kind = "guard let"
            raise CoroTransformError(
                f"coroutine transform: a tuple-pattern `{kind}` whose body spans a "
                f"suspension in `{self.name}` is not supported; bind a single name "
                f"and destructure inside the body",
                node.line, node.column, source_file=self.src_file)
        old = node.name
        new = f"__ob{self._optbind_ctr}"
        self._optbind_ctr += 1
        # Census T5 (design 218 stage 2): a `??` / `?.` lowering's payload
        # binding is single-use — the lowering built the `if let` and reads the
        # binding exactly once, in the sink it wrote — so its read CONSUMES it
        # like any other transform temp. The rename is what would otherwise
        # lose that: after it the name is `__obN`, indistinguishable from a
        # user's own `if let` binding, which is multi-use and reads by tier.
        if old.startswith("__vc") and not old.startswith("__vch"):
            self._vc_ob_bindings.add(new)
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
                # DF-187b: `_child_nodes` reaches a `StructInit`'s field values,
                # which the hand-rolled descent this replaced walked straight
                # past — so a struct literal naming the binding kept the OLD
                # name, and the re-check reported an undefined variable.
                for c in _child_nodes(n):
                    walk(c)

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
        a true live-range analysis, correct and simple.

        ONE residency rule is not about crossing a state boundary at all
        (DF-218s, ruled Aug 21): the OWNING locals of a block that
        (transitively) contains a `return` are frame-resident too, whether or
        not that block spans a suspension. Two release systems meet at a done
        exit — the frame's, emitted as statements, and codegen's
        `_cleanup_all_scopes`, which runs AT the lowered `return Poll.Done`,
        i.e. after every statement the transform can put in front of it — so a
        surviving real local can only be dropped AFTER the frame's fields, which
        inverts the sync twin's scope-LIFO order. Making those locals fields
        hands the whole ordering to ONE system, the scope walk
        (`_scope_release_seq` at E-RET), where LIFO is what it emits. OWNING
        only, because a trivial local's release is a no-op and its order is
        unobservable; RETURN-CONTAINING blocks only, because a local whose scope
        closes before every `return` is dropped by codegen at that scope's end,
        which is already the sync point."""
        locals_ = []  # (name, SawType)
        seen = set()
        body_spans = self._spans_suspension(self.func.body)

        def add(name, t, line=0, column=0):
            if t is None:
                raise CoroTransformError(
                    f"coroutine transform: local `{name}` in driven "
                    f"`{self.name}` has no resolved type", line, column)
            if name not in seen:
                seen.add(name)
                locals_.append((name, t))

        def walk_block(block, force=False):
            # `force` is set inside a SPLIT `try { } catch { }` (design 196 unit
            # 3). Every statement lowered there may be wrapped in its own
            # one-statement try/catch landing pad, and a `let` inside that
            # wrapper would be scoped to it — invisible to the statement after
            # it. A frame FIELD has no such scope, so the whole subtree of a
            # split try/catch is frame-resident by construction, exactly as if
            # its blocks spanned a suspension (which, taken together, they do:
            # the error edge is a state transition).
            scope_spans = force or self._spans_suspension(block)
            # DF-218s: the second residency reason (see the docstring). A block
            # that returns owes its OWNING `let`s a field so the ONE scope walk
            # orders them. Only a `let`/destructuring `let` is reachable this
            # way: a pattern binding (a `match` arm payload, a non-split `if
            # let`/`guard let`, a non-spanning `for`'s variable) has no store
            # into a field anywhere in the in-place lowering, so a field for one
            # would never be written.
            #
            # `body_spans` is the gate that keeps this to the bodies where the
            # problem EXISTS. The inversion needs two release systems at one
            # exit, so it needs at least one frame-resident scope — and a body
            # that suspends nowhere has none: every local is codegen's, and
            # `release()` has only params to drop. A SPAWN ROOT with no
            # suspension is exactly that body, and forcing residency there was
            # measured to break one (`net_cancel_parked_mt`: an
            # `UnsafePointer<Bool>` local made the frame non-`Send`).
            ret_scope = body_spans and _contains_return(block)
            # The TRAILING expression is a statement position too — and since
            # DF-233a the marking above can split an `if let` that sits in one,
            # which then owes a frame field exactly as a split statement one does.
            for s in _stmt_positions(block):
                walk_stmt(s, scope_spans, force, ret_scope)

        def walk_stmt(s, scope_spans, force=False, ret_scope=False):
            if isinstance(s, LetStatement):
                # DF-206a: `let _ = expr` is a DISCARD — it consumes the value and
                # drops it at the statement, so nothing about it crosses a state
                # boundary and it owes no field. Giving it one was worse than
                # wasteful: every discard in a body shared the ONE field named
                # `_`, so a second one of a different type was a bogus "cannot
                # assign `Int` to field of type `Data?`" on a legal program (the
                # `let _ = try! s.read()` / `let _ = h.join()` pair), and one of
                # the same type held its value alive until the frame died instead
                # of dropping it where it was written.
                # A THIRD residency reason, and it is `force`'s (above) at the
                # other landing site (DF-245d). A statement carrying a
                # propagating `try` is lowered behind a one-statement
                # `try { … } catch { … }` wrapper — `_emit_try_landing` inside a
                # split try/catch, `_emit_try_propagate` with no enclosing catch
                # — and a `let` inside that wrapper is SCOPED to it, invisible to
                # the statement after it. `force` says so for the whole subtree
                # of a split try/catch; the propagate site has no such marker, so
                # the binding asks for itself. A frame field has no scope, which
                # is the same repair.
                if s.name != "_":
                    t = s.type_annotation or getattr(s.value, 'resolved_type', None)
                    if (scope_spans or (ret_scope and _type_owns(t))
                            or self._has_propagating_try(s)):
                        add(s.name, t, s.line, s.column)
                return
            if isinstance(s, DestructuringLet):
                # `let (a, b) = expr` across a suspension (design 77 item 10):
                # each destructured binding is frame-resident. Its type comes from
                # the matching position of the source tuple's resolved type.
                if scope_spans or ret_scope:
                    src_t = getattr(s.value, 'resolved_type', None)
                    try:
                        leaves = self._destructure_leaf_types(s.pattern, src_t)
                    except CoroTransformError:
                        # A leaf with no resolved type is an error for a SPANNING
                        # scope — the field is owed there and a silent skip would
                        # miscompile. On the DF-218s path it is only an ordering
                        # refinement, so a shape whose leaf types are not known
                        # keeps ordinary real-local codegen rather than turning a
                        # working program into a diagnostic.
                        if scope_spans:
                            raise
                        leaves = []
                    for name, bt in leaves:
                        if scope_spans or _type_owns(bt):
                            add(name, bt, s.line, s.column)
                return
            ctrl = s.expression if isinstance(s, ExpressionStatement) else s
            if isinstance(ctrl, IfExpr):
                walk_block(ctrl.then_branch, force)
                if ctrl.else_branch is not None:
                    walk_block(ctrl.else_branch, force)
            elif isinstance(ctrl, IfLetExpr):
                # design 104 item 1: a split `if let` binding survives the
                # dispatch→then-branch state transition, so it is frame-resident.
                if getattr(ctrl, '_coro_split', False):
                    add(ctrl.name, self._optional_binding_type(ctrl),
                        ctrl.line, ctrl.column)
                walk_block(ctrl.then_branch, force)
                if ctrl.else_branch is not None:
                    walk_block(ctrl.else_branch, force)
            elif isinstance(s, GuardLetStatement):
                # design 104 item 1: a split `guard let` binding lives on into the
                # rest of the enclosing block (which crosses the suspension).
                if getattr(s, '_coro_split', False):
                    add(s.name, self._optional_binding_type(s), s.line, s.column)
                walk_block(s.else_branch, force)
            elif isinstance(ctrl, WhileExpr):
                walk_block(ctrl.body, force)
            elif isinstance(ctrl, MatchExpr):
                if self._spans_suspension(ctrl):
                    for nm, t in self._match_binding_types(ctrl).items():
                        add(nm, t, ctrl.line, ctrl.column)
                    # DF-196f: a design-63 arm PATTERN that binds the SCRUTINEE
                    # itself rather than an enum payload — the catch-all
                    # `case v ->`, and a tuple pattern over a tuple scrutinee.
                    # `_match_binding_types` reads the enum's variant payloads,
                    # so it answers nothing for those, and the binding got no
                    # frame field: the arm body is a separate state, so it read
                    # a name that no longer existed ("undefined variable `v`").
                    st = getattr(ctrl.matched_expr, 'resolved_type', None)
                    for arm in ctrl.arms:
                        for nm, bt in self._scrutinee_binding_types(
                                arm.pattern, st):
                            add(nm, bt, ctrl.line, ctrl.column)
                for arm in ctrl.arms:
                    if isinstance(arm.body, Block):
                        walk_block(arm.body, force)
            elif isinstance(s, ForLoop):
                if self._spans_suspension(s):
                    add(s.variable, SawType(TypeKind.INT), s.line, s.column)
                    add(f"__end_{s.variable}", SawType(TypeKind.INT), s.line, s.column)
                walk_block(s.body, force)
            elif isinstance(ctrl, TryCatchExpr):
                # design 196 unit 3: a SPLIT try/catch carries the caught error
                # from whichever state raised it into the catch's own state, so
                # the binding is frame-resident exactly like a split `if let`'s
                # — and everything under it is too (see `walk_block`'s `force`).
                split = self._splits_try_catch(ctrl)
                if split and ctrl.error_types:
                    add(ctrl.error_binding or "error", ctrl.error_type,
                        ctrl.line, ctrl.column)
                walk_block(ctrl.try_block, force or split)
                walk_block(ctrl.catch_block, force or split)

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

    def _scrutinee_binding_types(self, pattern, src_type):
        """`(name, type)` for each arm-pattern leaf that binds THE SCRUTINEE —
        the catch-all `case v ->`, and a tuple pattern's leaves paired with the
        scrutinee tuple's element types (DF-196f).

        Complements `_match_binding_types`, which reads an enum's variant
        PAYLOAD types and so answers nothing for these. Permissive by design,
        unlike `_destructure_leaf_types`: a match arm may hold literals, ranges
        and wildcards beside its bindings, and those bind nothing rather than
        being an error."""
        out = []

        def walk(pat, t):
            if isinstance(pat, BindingPattern):
                if t is not None:
                    out.append((pat.name, t))
                return
            if isinstance(pat, TuplePattern):
                elems = (t.element_types
                         if (t is not None and t.kind == TypeKind.TUPLE
                             and t.element_types) else None)
                for i, sub in enumerate(pat.elements):
                    walk(sub, elems[i] if (elems is not None
                                           and i < len(elems)) else None)

        walk(pattern, src_type)
        return out

    def _pattern_binding_names(self, pattern):
        """Every binding name a design-63 `MatchArm.pattern` introduces — see
        `ast_walk.pattern_binding_names`, the one definition of this walk. Used
        so a suspension-spanning `match` carries these bindings into frame
        fields exactly like the classic enum `arm.bindings` (design 101)."""
        return pattern_binding_names(pattern)

    def _destructure_temp_pattern(self, pattern, line, col):
        """A copy of `pattern` with every binding leaf renamed to a fresh temp,
        plus the `self.<leaf> = move <temp>` statements that follow it (DF-206b).

        Design 77 item 10 lowered `let (a, b) = v` as a source temp plus
        `self.a = __destr0.0` — a tuple-index READ, i.e. a COPY of the element.
        Right for the `(Int, Int)` tuples it was built for, wrong the moment an
        element OWNS anything: `let (a, b) = TcpStream.pair()` inside a driven
        body refused outright with "cannot copy value of type `TcpStream` which
        implements NoCopy", on a program the non-frame path compiles. There the
        source is a temporary and each component MOVES out (design 35 L1); the
        frame lowering turned that temporary into a named local and then read
        its elements, which is a different operation.

        So the components come out through the ordinary `DestructuringLet`
        instead, over an explicit `move` of the source temp — the spelling whose
        codegen transfers rather than retains, and which therefore says the same
        thing for a NoCopy element and a Copy one. The source temp
        itself still takes the value with whatever semantics the SOURCE
        EXPRESSION has (a frame-field read retains, a call result moves), so
        `let (a, b) = t` keeps `t` live and its own reference exactly as it does
        outside a frame. Wildcards keep their `_` and so keep the non-frame
        path's drop of a discarded component.
        """
        moves = []

        def rebuild(pat):
            if isinstance(pat, TuplePattern):
                return TuplePattern(
                    elements=[rebuild(p) for p in pat.elements],
                    line=pat.line, column=pat.column)
            if isinstance(pat, BindingPattern):
                tmp = f"__destr{self._destr_ctr}"
                self._destr_ctr += 1
                # Census S7: the leaf stores go through the store funnel, so a
                # migrated leaf is a `put` and an unmigrated one is the
                # assignment it always was.
                moves.append(self._store_field(
                    pat.name, MoveExpr(variable=tmp, line=line, column=col),
                    line, col))
                return BindingPattern(name=tmp, line=pat.line, column=pat.column)
            return pat

        return rebuild(pattern), moves

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

    def _splits_try_catch(self, e):
        """True when a `try { … } catch { … }` BLOCK has to become STATES rather
        than lower in place (design 196 unit 3).

        The catch arm is a resume target reachable from every `try` in the try
        body, so the moment ANY of it spans a suspension the catch has to be a
        state of its own: a suspension in the middle of the try body means the
        error edge leaves one state and lands in another, which no arrangement
        of basic blocks inside a single `if __state == N` region can express.
        Either side spanning is enough — a suspending catch body needs its own
        states just as much, and the try body's error edges then point at them.

        A try/catch with no suspension anywhere lowers in place exactly as
        before: one region, codegen's own catch context, nothing changed."""
        return self._spans_suspension(e)

    def _check_try_catch_splittable(self, e):
        """Refuse — cleanly, at the user's `try` — a split try/catch whose caught
        error the transform cannot carry in a frame field.

        ONE shape is refused: a try body raising TWO OR MORE distinct error
        types. The catch then binds the synthesized `_CatchError_<id>` UNION
        enum, and each error edge has to wrap its concrete error into the right
        variant on the way to the field. Codegen does that wrap for an in-place
        try/catch (`_wrap_error_in_union`), and the split lowering has no way to
        ask for it: it hands the error to the frame through an ordinary
        assignment, which is a type error against the union. Refused rather than
        guessed (design 196's STOP rule) — see DF-196b.

        Everything else about a split try/catch is expressible, so nothing else
        is refused here."""
        types = e.error_types or []
        if len(types) > 1:
            names = ", ".join(f"`{t}`" for t in types)
            raise CoroTransformError(
                f"coroutine transform: a `try {{ }} catch {{ }}` block that spans "
                f"a suspension in `{self.name}` may raise only ONE error type, "
                f"and this one raises {len(types)} ({names}); the catch would "
                f"bind a union the split lowering cannot build. Split it into one "
                f"`try`/`catch` per error type, or handle each call with an inline "
                f"`try <call> catch {{ ... }}`.",
                e.line, e.column, source_file=self.src_file)

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
            if isinstance(ctrl, (IfExpr, WhileExpr, MatchExpr, ForLoop, IfLetExpr,
                                 TryCatchExpr)) and self._spans_suspension(ctrl):
                self._norm_ctrl(ctrl, tail=False)
        fe = block.final_expr
        if fe is None:
            return
        # DF-244a: a tail carrying a PROPAGATING `try` is normalized into a
        # statement even when it holds no suspension of its own. The lowering
        # keys on statements, and `try`'s error edge needs the landing dispatch
        # in `_lower_stmt` — a tail left in `final_expr` is lowered by `_done`
        # with the `try` still inside the state machine, which is the same
        # in-place lowering the `return` branch used to do (see `_lower_stmt`).
        spanning = (self._spans_suspension(fe)
                    or self._has_propagating_try(fe))
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
            elif isinstance(fe, TryCatchExpr):
                # design 196 unit 3: a TRAILING `try { } catch { }` in value
                # position. Same shape as the `if`/`else` above — push the result
                # flow into both arms so every leaf returns, then leave it as a
                # statement for the CFG split. Without this the tail became
                # `return try { … } catch { … }` and the suspension inside it was
                # a buried call the split could not reach, so the author got a
                # rejection for a shape they had not written.
                block.final_expr = None
                self._norm_block(fe.try_block, tail=True, force=True)
                self._norm_block(fe.catch_block, tail=True, force=True)
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
        elif isinstance(node, TryCatchExpr):
            self._norm_block(node.try_block, tail)
            self._norm_block(node.catch_block, tail)

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
            # design 224 (G1): a container's HEAD — the expression it evaluates
            # outside every one of its blocks — is checked BEFORE the descent
            # into those blocks. `_hoist_container_heads` lifted every spanning
            # head into a preceding driven statement, so one that still spans
            # here is a position nothing can express, and saying so is the whole
            # point: this walk used to step straight past a head into the blocks,
            # and a `Channel.receive()` in a `match` scrutinee was then neither
            # embedded NOR refused. The enumeration lives in `ast_walk`
            # (`control_heads` / `CONTAINER_HEADS`) beside `control_blocks`, so a
            # new container cannot add a head this walk silently skips.
            for owner, field in control_heads(s):
                head = getattr(owner, field)
                if self._spans_suspension(head):
                    self._reject_container_head(head)
            # PER-CONTAINER semantics, so this one keeps its own dispatch rather
            # than `ast_walk.control_blocks`: an `if let`/`guard let` is
            # descended only when design 104 marked it `_coro_split`, and a
            # `try { … } catch { … }` only when it is being split into states
            # (design 196 unit 3). A container NOT listed here falls through to
            # the rejection below on purpose — a suspension the state machine
            # cannot express is refused, never silently blocked. See `ast_walk`'s
            # `CONTAINER_KINDS` for the full list this is choosing from.
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
            elif isinstance(ctrl, TryCatchExpr) and self._splits_try_catch(ctrl):
                self._check_try_catch_splittable(ctrl)
                visit_block(ctrl.try_block)
                visit_block(ctrl.catch_block)
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
        # DF-218n: `__saw_drive` in a body that itself suspends is refused HERE,
        # on the untouched body — every lowering below moves the site's argument
        # out of the shape `_rewrite_drive_sites` reads, and the ruling is a
        # clean refusal rather than nested-executor semantics.
        self._reject_drive_site()
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
        # design 224: lift a suspension-spanning CONTAINER HEAD — an `if`/`while`
        # condition, a `for` range, a `match` scrutinee, an `if let`/`guard let`
        # subject — into a preceding driven statement (a `while` condition moves
        # INTO the loop body instead, since it runs per iteration). Every pass
        # above walks a container's BLOCKS; none walked its head, so a suspension
        # there was neither embedded nor refused (DF-224a). Runs AFTER the
        # value-conditional lowering, whose branch shape MAKES statement-position
        # containers with spanning heads, and BEFORE the ANF hoist, which then
        # linearizes whatever the lifted `let` still buries.
        self._hoist_container_heads()
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

        # The locals the transform takes the ADDRESS of, which therefore keep an
        # addressable payload until stage 3's `UnsafeRef` lands. Collected from
        # the nested-call sites `_collect_calls` just found: the method
        # receiver (census P1) and every reference argument (census S9's ref
        # half). Conservative by design — a reference ARGUMENT is recognised by
        # its own `&` spelling rather than by the callee's encoding, which is
        # not known until every frame has been prepared.
        addressed = set()

        def _addressed_add(expr):
            root = _place_root_name(expr)
            if root is not None:
                addressed.add(root)

        def _scan_addressing(node, seen):
            if node is None or id(node) in seen:
                return
            seen.add(id(node))
            # `&x` / `&var x` ANYWHERE in the body: the reference is taken of
            # the local's storage, and after the rewrite that storage is the
            # frame's field.
            if isinstance(node, ReferenceExpr):
                _addressed_add(node.expr)
            # `p?.x = v` reaches its head as a mutable PATH, which a lend is
            # not.
            if isinstance(node, OptionalChainAssign):
                _addressed_add(getattr(node, 'target', None)
                               or getattr(node, 'chain', None))
            for sub in child_nodes(node):
                _scan_addressing(sub, seen)

        _scan_addressing(self.func.body, set())
        # The nested-call sites address two more things the scan above cannot
        # see, because the transform (not the source) is what takes them: a
        # suspending METHOD call's receiver becomes the callee frame's `__recv`
        # pointer, and a reference argument becomes its `ref` field.
        for c in self.calls:
            if c.get('has_recv') and c.get('recv') is not None:
                _addressed_add(c['recv'])
            for a in c.get('args', []):
                if isinstance(getattr(a, 'value', None), ReferenceExpr):
                    _addressed_add(a.value)
        self._address_taken = addressed
        # DF-218h: the locals a method call consumes another local into. See
        # `_migrated_enc` — a slot read is a lend, and a `move` inside the
        # window's closure has no drop flag it can reach.
        move_recvs = set()
        _collect_move_arg_receivers(self.func.body, move_recvs)
        encmap = {}
        # design 218 stage 4: the family that held a field back from `Slot<T>`,
        # recorded beside the encoding it produced. `_forget_stmt` reads it, so
        # every surviving `__saw_forget` names the deferral it belongs to
        # instead of a comment asserting one.
        defer_families = {}

        def _record(nm, base_enc, ty, movers=()):
            enc, fam = _migrated_enc(nm, base_enc, addressed, ty, movers)
            encmap[nm] = enc
            if fam is not None:
                defer_families[nm] = fam

        for p in self.params:
            self._reject_erased_reference_param(p)
            _record(p.name, _enc_of(p.type), p.type, move_recvs)
        for lname, lt in self.frame_locals:
            _record(lname, _enc_of(lt), lt, move_recvs)
        # design 62 G3: a DISCARDED cooperative `receive()` parks its value in a
        # `__rcvN` holder. Registered here so the ONE store funnel
        # (`_store_field`) can answer for it like any other owning field; no
        # source name can collide with it.
        for rc in self.recv_calls:
            if rc['target'] is None:
                _record(f"__rcv{rc['idx']}", _enc_of(rc['elem_type']),
                        rc['elem_type'])
        self.result_defer_family = None
        if self.is_void:
            self.result_enc = "plain"
        elif self.force_opt_result:
            # A spawn root forces its result opt-encoded so the `Task<T>`
            # uniformly holds `UnsafePointer<T?>`, regardless of T. That slot
            # lives in the group-owned CELL, not in the frame, and the cell is
            # on design 218's trusted list — so it keeps the legacy encoding.
            self.result_enc = "opt"
            self.result_defer_family = FAM_SPAWN_CELL
        else:
            # CENSUS ROWS R5/R6 (design 218 stage 2). What stopped them in
            # stage 1 was a language asymmetry rather than anything about
            # frames: a result store rides auto-wrap (`return v.len()` from a
            # `-> Result<Int, E>` body stores a bare `Int`), `put` takes its
            # value as a CALL ARGUMENT, and `Result` did not wrap there. It
            # does now (DF-218f), so the transform stays dumb — `put(v)` just
            # works — and `_sub_result_read` and the driver's move-out give up
            # their paired `__saw_forget` with the row.
            self.result_enc, self.result_defer_family = _migrated_enc(
                "__result", _enc_of(self.ret), addressed, self.ret, move_recvs)
        self.encmap = encmap
        self.defer_families = defer_families

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
                rcv = f"__rcv{rc['idx']}"
                fields.append(StructField(
                    name=rcv,
                    type=_field_type(rc['elem_type'], encmap[rcv])))
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
            # DF-134a: the LAST (fd, direction) this frame armed, so `release`
            # can drop a registration the body left behind. -1 = nothing armed.
            fields.append(StructField(name="__io_fd", type=SawType(TypeKind.INT)))
            fields.append(StructField(name="__io_dir", type=SawType(TypeKind.INT)))
        if self.is_spawn_root:
            # design 134: a spawned frame carries a POINTER to its group-owned
            # cell instead of a cancel word and a result slot of its own. The
            # cell holds both, outlives the frame, and is what every `Task`
            # addresses — so a completed task's box can be released at once.
            fields.append(StructField(name="__cellp", type=_cell_ref_type(self)))
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
                                   source_file=getattr(func, 'source_file', ""),
                                   is_synthesized=True)
        return self.frame_struct

    # ------------------------------------------------------- design 134 places
    # The result and the cancel word are FRAME fields for a driven frame and a
    # nested sub-frame, and CELL fields (reached through `__cellp`) for a spawn
    # root. Every read and write goes through these two helpers, so the rest of
    # the lowering never has to know which layout it is looking at.
    #
    # design 222 unit 1: the cell hop is `__cellp.deref()`, an ordinary `borrows`
    # accessor the place system judges, where it used to be a bare `[0]` on a raw
    # pointer. Every READ of the cell goes through it.
    def _cell_hop(self, line=0, column=0):
        return _unsaferef_deref(_self_field("__cellp", line, column),
                                _cell_type(self), line=line, column=column)

    def _cell_hop_raw(self, line=0, column=0):
        """The cell reached through the handle's OWN pointer, no window opened.

        DEFERRED: window-move (`FAM_WINDOW_MOVE`, DF-218h). The result WRITE
        cannot go through `deref()`, and the reason is the mechanism that defers
        that whole family rather than anything about the cell: a place window is
        lowered as a CLOSURE, so every enclosing local the assignment's RHS names
        was a by-value capture, and a move-only one was refused
        (``cannot copy value of type `Res` which implements NoCopy``, context
        `closure capture` — measured on `coro_iflet_suspending_deinit`,
        `coro_nested_iflet_struct_init` and `taskgroup_nested_ambient`). The
        value being stored is precisely the thing a frame's locals feed, so the
        write is the one cell operation that meets it every time. Both halves of
        that refusal have since been fixed — DF-169h made the window body borrow
        its enclosing bindings, DF-218h gave a moved one the deferred transfer —
        so what remains here is the staging, not the defect.

        Forwarding the handle's pointer is stage 3's own answer to the same shape
        (its finding (a): three sites that took `&` of a window forward
        `<handle>.p` instead — re-taking the address was never the right
        operation). `p` is public for exactly this. The write migrates when the
        window-move family does, in one landing with the rest of it."""
        return ArrayIndex(
            array_expr=MemberAccess(object=_self_field("__cellp", line, column),
                                    member="p"),
            index=_int(0))

    def _result_place(self, line=0, column=0):
        """The result slot — a WRITE target only (`_store_result` is its one
        caller; a driven root's own result leaves through `_read_frame_result`,
        which reads the frame field directly)."""
        if self.is_spawn_root:
            return MemberAccess(object=self._cell_hop_raw(line, column),
                                member="__result")
        return _self_field("__result", line, column)

    def _cancel_place(self, line=0, column=0):
        """The cancel word — READ everywhere it appears (`is_cancelled`, the
        cooperative-cancel branch, the copy-down to a sub-frame, and a rewritten
        `cancelled()`), so the cell hop is the checked window."""
        if self.is_spawn_root:
            return MemberAccess(object=self._cell_hop(line, column),
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
        ones (let-bound / bare-discard / tail-return).

        design 223: the RECEIVER question is `_suspending_method_target`'s, and
        an UNSUPPORTED answer returns None from HERE so the rejector at the same
        statement (`_reject_suspending_method_call`) raises. Returning None used
        to mean "not a suspending call" as well, which is what let the
        inexpressible shapes lower as plain calls."""
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
        if mc is None:
            return None
        # DF-184a: the classifier answers for a STATIC call too, whose `recv` is
        # None — the sub-frame it embeds has no `__recv` to seed.
        tgt = _suspending_method_target(mc, self._tc)
        if tgt.kind != 'embed':
            return None
        return {'callee': tgt.frame_key,
                'args': list(mc.arguments), 'target': target, 'ret': is_ret,
                'recv': None if tgt.is_static else mc.object,
                'recv_struct': tgt.owner,
                'is_method': True, 'has_recv': not tgt.is_static,
                'line': getattr(mc, 'line', 0) or 0}

    def _classify_recv(self, stmt):
        """design 62 G3: if `stmt` is a top-level cooperative `ch.receive()`
        boundary, return {receiver, target, elem_type, ret}; else None. Supported
        forms mirror the free-function and method classifiers': `let v =
        ch.receive()`, a bare `ch.receive()` / `let _ = ch.receive()` discard,
        and — after design-83 tail normalization — `return ch.receive()`, whose
        received value is this frame's `__result`. The call lowers inline to the
        try_receive+yield_now loop (no callee frame).

        DF-224a's G4 was that last arm's absence. `_classify_call` and
        `_classify_method_call` both take a `ReturnStatement` and this one did
        not, so `return ch.receive()` — the shape a `-> T` worker's tail
        normalizes INTO — fell past all three classifiers to the last-resort
        rejector and was refused as "a nested/expression position" for a
        statement that is not nested at all."""
        mc = None
        target = None
        is_ret = False
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
            # DF-206a, third classifier: `let _ = ch.receive()` is a DISCARD, so
            # it has no frame field to write into — the received value is
            # dropped at the statement. `_classify_call` and
            # `_classify_method_call` both guard `_` this way and this one did
            # not, which was invisible while a body whose only suspension was a
            # channel receive never became a frame at all (DF-203b). It does
            # now, and a `self._` store into a frame with no such field is a
            # post-transform type error.
            target = stmt.name if stmt.name != "_" else None
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, MethodCall)):
            mc = stmt.expression
        elif isinstance(stmt, ReturnStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
            is_ret = True
        if mc is None or not getattr(mc, 'is_chan_recv', False):
            return None
        elem_type = getattr(mc, 'resolved_type', None)
        if elem_type is None:
            raise CoroTransformError(
                f"coroutine transform: `receive()` in `{self.name}` has no "
                f"resolved element type", mc.line, mc.column)
        return {'receiver': mc.object, 'target': target, 'elem_type': elem_type,
                'ret': is_ret}

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
        """design 84 + 223: True if `mc` is a call to a suspending method — one
        this frame can EMBED, or one it cannot NAME. Both are suspensions, and
        the second is exactly what must not be answered `False`: the callers are
        the expression-position hoists and `_reject_buried_suspend_call`, so a
        `False` here is a suspension lowered in place as a plain call."""
        return _suspending_method_target(mc, self._tc).suspends

    def _suspending_method_call(self, stmt):
        """If `stmt` is a top-level `let x = recv.m(args)` / bare `recv.m(args)`
        whose method `m` suspends, return (MethodCall, target); else
        (None, None). The target carries WHY when the frame cannot be named, so
        the rejector can say so (design 223)."""
        mc = None
        if isinstance(stmt, LetStatement) and isinstance(stmt.value, MethodCall):
            mc = stmt.value
        elif (isinstance(stmt, ExpressionStatement)
              and isinstance(stmt.expression, MethodCall)):
            mc = stmt.expression
        if mc is None:
            return None, None
        tgt = _suspending_method_target(mc, self._tc)
        return (mc, tgt) if tgt.suspends else (None, None)

    def _reject_suspending_method_call(self, stmt):
        mc, tgt = self._suspending_method_call(stmt)
        if mc is not None:
            raise CoroTransformError(
                self._unembeddable_method_message(mc, tgt),
                mc.line, mc.column, source_file=self.src_file)

    def _unembeddable_method_message(self, mc, tgt):
        """THE message for a suspending method call this frame cannot embed.

        One text for both rejectors, because they refuse the same thing for the
        same reason and used to word it two ways. When the classifier said
        UNSUPPORTED it also said why, and that half is what design 223 added:
        before it, the inexpressible shapes never reached a rejector at all."""
        sname = (tgt.owner if tgt is not None and tgt.owner else "?")
        if tgt is not None and tgt.reason:
            return (f"coroutine transform: the suspending method call "
                    f"`{sname}.{mc.method_name}(...)` inside driven `{self.name}` "
                    f"cannot be embedded because {tgt.reason}. Drive the method "
                    f"directly with `__saw_drive(recv.{mc.method_name}(...))`, or "
                    f"wrap the call in a nested free function and call that.")
        return (f"coroutine transform: a buried suspending method call "
                f"`{sname}.{mc.method_name}(...)` inside driven `{self.name}` is not "
                f"yet supported (design 74 A5-rest, shape 1: method sub-frame "
                f"embedding). Drive the method directly with "
                f"`__saw_drive(recv.{mc.method_name}(...))`, or wrap the call in a "
                f"nested free function and call that.")

    def _reject_container_head(self, head):
        """A container HEAD that still spans a suspension when `_collect_calls`
        runs (design 224). `_hoist_container_heads` lifts every one it can, which
        is every one a `let` could host, so reaching here means the head is a
        shape no position expresses — and the ONE thing it must not do is fall
        through into the container's blocks, which is what left DF-224a's cells
        spinning.

        Delegates to `_reject_buried_suspend_call`, which anchors at the offending
        call and names its kind; the raise below is the honest floor for a head
        that spans by some measure that scan does not recognise."""
        self._reject_buried_suspend_call(head)
        raise CoroTransformError(
            f"coroutine transform: the head of this control-flow construct in "
            f"`{self.name}` contains a suspension the state split cannot "
            f"express; bind it to its own `let` before the construct and use "
            f"the binding",
            getattr(head, 'line', 0) or 0, getattr(head, 'column', 0) or 0,
            source_file=self.src_file)

    def _reject_drive_site(self):
        """A `__saw_drive` / `__saw_drive_steps` site in a body that ITSELF
        suspends — RULED a clean refusal (user, Aug 15; DF-218n).

        `__saw_drive` is design 44's test-only executor entry: it names a root
        and runs it to completion. A body holding one may also call a suspending
        function on its own account, which makes THIS body suspending too, so
        the transform rewrites it into a frame BEFORE `_rewrite_drive_sites`
        walks the program — and that rewrite has moved the drive site's argument
        out of the `FunctionCall` shape the rewrite reads. The compiler died
        `AttributeError: 'MemberAccess' object has no attribute 'name'`.

        The ruling refuses it instead of making both roots run: a nested drive
        would need non-ceding nested-executor semantics (fairness, op-budget
        bypass) designed for a spelling only tests write, and the refusal costs
        zero real programs because the body already suspends — which is the
        position where a suspending call embeds and needs no drive at all. That
        is what the diagnostic teaches.

        Runs at the TOP of `prepare`, on the untouched body: every function this
        transform turns into a frame passes through there, and the site's own
        line is still the author's. A body that does NOT suspend never builds a
        frame, so `__saw_drive` from a sync `main` is untouched.
        """
        for fc in _iter_function_calls(self.func.body):
            if fc.name not in ("__saw_drive", "__saw_drive_steps"):
                continue
            inner = fc.arguments[0].value if fc.arguments else None
            if isinstance(inner, MethodCall):
                spelling = f"{inner.method_name}(...)"
            elif isinstance(inner, FunctionCall):
                spelling = f"{inner.name}(...)"
            else:
                spelling = "the root"
            raise CoroTransformError(
                f"coroutine transform: `{fc.name}` may not appear in "
                f"`{self.display_name}`, which itself suspends. This body "
                f"already runs inside an executor, so `{spelling}` needs no "
                f"drive site — call it directly and the suspending call embeds "
                f"here (design 120).",
                getattr(fc, 'line', 0) or 0, getattr(fc, 'column', 0) or 0,
                source_file=self.src_file)

    def _reject_erased_reference_param(self, p):
        """A `&any Trait` parameter of a suspending function — refused HERE, at
        the parameter the author wrote (design 223 unit 3).

        design 88 gives a reference parameter a frame-resident handle
        (`UnsafeRef<T>`) so it can span a suspension, and `T` for an erased
        reference is `any Trait`, which is unsized: the synthesized field is
        `UnsafeRef<any Greeter>`, and the post-transform re-typecheck refuses it
        with design 51's ``any Greeter` is unsized and cannot be used by value
        here` — anchored at `0:0`, in a declaration the compiler wrote, about a
        rule the author did not break. Same limit, said at the parameter, with
        what to do instead.
        """
        pt = getattr(p, 'type', None)
        if (pt is None or getattr(pt, 'kind', None) != TypeKind.REFERENCE
                or pt.inner_type is None
                or pt.inner_type.kind != TypeKind.EXISTENTIAL):
            return
        tn = pt.inner_type.existential_trait or "Trait"
        raise CoroTransformError(
            f"coroutine transform: `{p.name}: &any {tn}` cannot be a parameter "
            f"of the suspending function `{self.display_name}`. A reference "
            f"that spans a suspension is held in the frame as a handle to its "
            f"referent (design 88), and an erased referent has no size for the "
            f"frame to name. Take an owned `Box<any {tn}>` instead, or make the "
            f"parameter a concrete type / a generic `<T: {tn}>`.",
            getattr(p, 'line', 0) or getattr(self.func, 'line', 0) or 0,
            getattr(p, 'column', 0) or 0,
            source_file=self.src_file)

    def _suspend_in_closure_message(self, what):
        """THE message for a suspension inside a CLOSURE LITERAL's body.

        design 223 unit 3. This shape used to be reported as "appears in a
        control-flow branch the state split cannot express (an `if let`/`guard
        let` body)" — a diagnostic naming two constructs the program does not
        contain, about a closure the author can see. The limit is real and
        documented (a closure body is not driven; LANGUAGE_SPEC's closure-body
        section), so this says THAT, with the two spellings that work.
        """
        return (f"coroutine transform: the suspending call {what} appears "
                f"inside a CLOSURE BODY in driven `{self.name}`, and a closure "
                f"body is not driven — its suspension has no frame to park in. "
                f"Call it outside the closure and pass the result in, or move "
                f"the whole closure body into a named function the driven body "
                f"calls.")

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

        def scan(n, in_closure=False):
            # design 223 unit 3: WHERE the offending call sits decides what the
            # author is told. A suspension inside a CLOSURE LITERAL's body is a
            # different shape from one in an `if let` branch — the closure body
            # is not driven at all (LANGUAGE_SPEC's closure-body limit) — and
            # telling its author to "restructure to a plain `if`/`else`" names a
            # construct that is not in their program.
            if isinstance(n, ClosureExpr):
                in_closure = True
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
                found.append(("method", n, in_closure))
            if isinstance(n, ASTNode):
                for c in _child_nodes(n):
                    scan(c, in_closure)

        scan(stmt)
        if found:
            entry = found[0]
            kind, g = entry[0], entry[1]
            if kind == "method":
                if entry[2]:
                    raise CoroTransformError(
                        self._suspend_in_closure_message(
                            f"`{_suspending_method_target(g, self._tc).owner or '?'}"
                            f".{g.method_name}(...)`"),
                        g.line, g.column, source_file=self.src_file)
                tgt = _suspending_method_target(g, self._tc)
                if tgt.kind == 'unsupported':
                    # design 223: the frame could not be NAMED, which is a
                    # different refusal from "this position cannot host one" —
                    # say which, or the author restructures a branch that was
                    # never the problem.
                    raise CoroTransformError(
                        self._unembeddable_method_message(g, tgt),
                        g.line, g.column, source_file=self.src_file)
                sname = tgt.owner or "?"
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
        # design 196 unit 4: fresh-name counter for a materialized closure
        # capture, so two closures in one block never declare one name twice.
        self._cap_ctr = 0
        # design 196 unit 3: the enclosing split `try { } catch { }`, as
        # (catch state, frame field the caught error travels in), or None.
        self._try_ctx = None
        self._tcland_ctr = 0
        self.cur = 0

        # design 218b: the FUNCTION-BODY scope. Pushed and never popped — the
        # body has exactly one fallthrough, the tail below, and that tail ends
        # in `_done`, whose E-RET walk releases this scope AFTER the result has
        # been stored. Releasing it here instead would clear the very local a
        # tail `move r` is handing back.
        self._scope_stack = []
        self._push_scope(self._block_scope_names(func.body))

        self._lower_stmts(func.body.statements, loop_ctx=None)
        if self.cur not in self._term:
            fe = func.body.final_expr
            if fe is None:
                self._done(None)
            else:
                forgets = []
                cap_lets, val = self._rewrite_hosting(fe, forgets)
                # DF-182d: a tail `move local`. The tail expression IS the return
                # value, so the drop-flag clears it owes belong in the done
                # sequence, which is exactly where a `return move local` puts
                # them — `_done` has taken them all along, and this position used
                # to refuse instead of passing them on.
                self._emit(cap_lets)
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
        #
        # THE VERIFIED-UNSAFE CORE ENTRY (design 222 unit 3). This is the ONE site
        # that emits it, and it stays a raw cast on purpose. What the address does
        # after this statement is outside every scope the checker has:
        #
        #   1. it leaves the type system as an INTEGER (`io_wait(fd, dir, tok)` ->
        #      `__saw_rt_reactor_register(r, fd, w, token: Int)`, frozen in
        #      rt/ABI.md) and is stored in KERNEL memory — a kqueue `udata`, an
        #      epoll `data.u64`;
        #   2. the WRITE side is the runtime's poll, which rebuilds a pointer from
        #      that integer with no provenance and stores through it
        #      (`rt_reactor_poll`: `let tokptr = ud as UnsafePointer<Int>;
        #      tokptr[0] = 0`), in another module, from another thread;
        #   3. it must stay valid for as long as the REGISTRATION does, which is
        #      not a lexical extent: the frame's box keeps the address stable
        #      (design 134), one-shot rearm keeps a fired event from re-firing, and
        #      DF-134a's `release` unregisters whatever an exiting frame left armed;
        #   4. in an MT group the store is unsynchronized against the executor's
        #      reads (the poll runs OUTSIDE the queue lock, by design — a bounded
        #      timeout plus a persistent latch word, so a fire that races a park is
        #      caught on the next scan).
        #
        # A WRAPPER IS AVAILABLE AND IS REFUSED. `wake_token(word: &var Int) unsafe
        # -> Int` compiles, and a caller of it needs no `unsafe` — probed
        # (`.build/scratch/u3_latch_probe.saw`), which is exactly the problem: the
        # obligation would vanish from every signature while the address still
        # escapes. An `UnsafeRef<Int>` field is the other candidate and is refused
        # for a different reason — the contract it states ("the referent outlives
        # every `deref()`") is not the obligation above, nobody derefs, and the
        # field must stay an `Int` to propagate down the frame chain and reach the
        # frozen seam. So the cast stays visible, `resume` is unconditionally
        # `unsafe` because of it, and the argument lives here and in design 218's
        # ratified list rather than in a type that would read as reviewed.
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
            return_type=SawType(TypeKind.ENUM, enum_name=POLL_IDENTITY),
            body=Block(statements=[io_tok_init, loop], final_expr=None),
            self_mutable=True, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # The `__wake read surface` of the Resumable protocol (design 52b item 1):
        # a `&self` accessor returning the frame's wake word, so the executor can
        # schedule an erased task without reaching into a concrete field.
        wake_reason = Method(
            name="wake_reason",
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
            name="is_cancelled",
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
            name="bt_desc",
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
        # than with its group. Since design 218 unit 1 it is a REQUIREMENT of
        # `Resumable` rather than a bare synthesized method, so the mechanism
        # has a name in the language and the invariant it rests on ("release
        # may run before deinit; deinit is a no-op afterwards") is written down
        # on the trait instead of living in this comment. The wiring is
        # unchanged: the frame still releases itself from inside `resume`, and
        # nothing dispatches through the vtable to reach it yet.
        release = Method(
            name="release",
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.VOID),
            body=Block(statements=self._release_seq(), final_expr=None),
            self_mutable=True, self_is_reference=True, is_sync=True,
            is_synthesized=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        # Every frame conforms to the `Resumable` trait (design 52b item 1;
        # `std.compiler.frame` since design 218 unit 1): the conformance is
        # what lets a frame be erased into
        # `Box<any Resumable>` for the heterogeneous run queue. Concrete drives
        # (nested sub-frames, the entry executor, `__saw_drive_*`) still bind `resume`
        # statically — conformance only synthesizes a vtable at an erasure site.
        # design 218 stage 3 (218a ruling 1): the honest `unsafe` declarations,
        # decided per method from what it touches. `resume` is unconditional —
        # the `__io_tok` latch above casts `&self.__wake` to an
        # `UnsafePointer<Int>` in EVERY frame. `is_cancelled` follows the cell:
        # a spawn root reads its cancel word through `__cellp`, a driven frame
        # reads its own field. `release` names every OWNED FIELD's type, so it
        # follows the field set. `wake_reason` and `bt_desc` read an `Int` and a
        # literal, in every frame there is.
        _declare_unsafe(resume, True)
        _declare_unsafe(wake_reason, False)
        _declare_unsafe(is_cancelled, self.is_spawn_root)
        _declare_unsafe(bt_desc, False)
        _declare_unsafe(release, _frame_fields_name_unsafe(self))
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

    # ------------------------------------------------------------------ #
    # THE FRAME-SLOT AUTHORITY (design 210 unit 3)
    # ------------------------------------------------------------------ #

    def _frame_slot_type(self, name):
        """The declared type of the frame slot `name` holds, or None.

        Reads the same `(name, type)` list the frame STRUCT's fields are built
        from, so the slot's type and the judgment made about it can never drift
        apart."""
        for lname, lt in self.frame_locals:
            if lname == name:
                return lt
        for p in self.params:
            if p.name == name:
                return p.type
        return None

    def _store_binding_in_slot(self, name, line=0, column=0):
        """THE store of a PATTERN BINDING into the frame slot made for it.

        A binding introduced by an `if let`, a `guard let` or a `match` arm is
        bound in the DISPATCH arm the transform emits and dies at the end of
        it, while the body that reads it runs in a separately-dispatched resume
        state. So the value has to cross into the frame — and how it crosses is
        decided by whether the binding OWNS what it holds, which is a copy-tier
        question with exactly one oracle in this compiler:
        `Namespace.read_policy` (design 193's funnel over design 131's read
        table and design 139's tiers).

          * 'nocopy' / 'explicit' — the payload read CONSUMED its source, so the
            binding owns the value outright. The frame takes it by `move`; an
            alias would be refused outright by the transfer checkpoint, which is
            how blade's `main` came to report `cannot copy value of type `Cli`
            which implements ExplicitCopy` at `FILE:0:0` on a program that
            writes no copy at all (DF-210a).
          * 'retain' / 'trivial' — the read did NOT consume: the source still
            owns its reference and the binding is a second view of it. The store
            is an ordinary transfer, and the checkpoint stamps the retain the
            tier calls for. Moving instead hands the frame a reference the
            binding never held, so the frame's release is one too many: the
            payload is destroyed while the original still points at it
            (DF-210b — this is what `if let` did for an `Arc` payload, and what
            `match` did NOT, which is why only one of the two was visibly
            broken).

        ENTRY POINTS — every position where a pattern binding crosses into a
        frame slot (process rule 1):
          * `_optbind_dispatch` — `if let` / `guard let` (design 104 item 1)
          * `_split_match` — every payload binding of every arm of a
            suspension-spanning `match` (designs 63 / 101)

        A THIRD position asks the same oracle for a different construct and so
        has its own entry point below rather than this one:
        `_materialize_closure_captures` reads a frame local OUT for a closure to
        capture. See `_frame_read_policy`, which both go through.

        A slot whose type is unknown keeps the conservative alias: the
        checkpoint then judges it exactly as it always has.

        Design 218 stage 1 changes what the store IS, not how it is decided:
        `put` takes its value BY VALUE, so the ordinary call-argument transfer
        checkpoint demands the tier-correct spelling and a wrong policy answer
        becomes a compile error on generated code rather than a silent alias.
        The branch below still picks the spelling; it no longer has to be
        trusted.
        """
        if self._slot_store_consumes(name):
            value = MoveExpr(variable=name, path=None, line=line, column=column)
        else:
            value = Identifier(name=name, line=line, column=column)
        return self._store_field(name, value, line, column)

    def _store_field(self, name, value, line=0, column=0):
        """THE write of a whole frame field — the one place a value crosses
        into frame storage under its own name.

        ENTRY POINTS (process rule 1): `_store_binding_in_slot` (pattern
        bindings), `_lower_inplace`'s `let` and whole-binding `assign` arms,
        `_split_for`'s range bounds, `_emit_recv_call`'s received value, and
        `_emit_nested_call`'s sub-frame result. A migrated field is written by
        `put`, whose replace semantics — drop the previous occupant if there
        was one — are exactly the optional-assign drop a rebound `var` used to
        get from the field's own tag."""
        if _enc_is_slot(self.encmap.get(name)):
            return ExpressionStatement(expression=_slot_op(
                _self_field(name, line, column), "put",
                [Argument(name=None, value=value)], line, column))
        return AssignStatement(target=_self_field(name, line, column),
                               value=value, line=line, column=column)

    def _slot_store_consumes(self, name) -> bool:
        """Does storing the binding `name` into its frame slot CONSUME the value?

        The decision procedure behind `_store_binding_in_slot`, split out because
        a second caller needs the same answer for a different reason: when the
        store consumes, whatever the payload was read OUT of has given it up, and
        a source the transform owns must be told so (DF-210f).

        `Namespace.read_policy` is the oracle (design 193's funnel over design
        131's read table and design 139's tiers): 'nocopy'/'explicit' consume,
        'retain'/'trivial' do not. Unknown answers "no", which is the
        conservative direction — an extra retain leaks at worst, while a
        wrongly-claimed consume double-frees.
        """
        return self._frame_read_policy(name) in ('nocopy', 'explicit')

    def _frame_read_policy(self, name):
        """`Namespace.read_policy` for the type of frame slot `name`, or None
        when the slot's type or the namespace is not available.

        THE ONE PLACE the transform asks the language what reading a value out
        of storage costs (design 193's funnel over design 131's read table and
        design 139's tiers). Its two callers want different things from the same
        answer, which is why the answer and not a boolean is what is shared:
        `_slot_store_consumes` asks whether a pattern binding's store into its
        slot consumes, and `_materialize_closure_captures` asks how to hand a
        frame local to a closure env. Every earlier bug in this area came from a
        caller deciding for itself — DF-210a/b were `_store_binding_in_slot`
        moving or copying unconditionally, and DF-217c was the closure
        materialization spelling `.copy()` on every tier, which is a compile
        error on a NoCopy value and on an AUTOMATIC-Copy struct (design
        159's tier owes no declaration, so it has no `copy` method to call).
        """
        slot_type = self._frame_slot_type(name)
        if slot_type is None or self._tc is None:
            return None
        # `check_module` resets `typechecker.namespace` on the way out, so the
        # entry module's own namespace is reached through the seam it stashed —
        # the same one `_promote_nested_generic_calls` re-installs.
        ns = (getattr(self._tc, '_entry_module_ns', None)
              or getattr(self._tc, 'namespace', None))
        if ns is None or not hasattr(ns, 'read_policy'):
            return None
        return ns.read_policy(slot_type)

    def _frame_slot_has_explicit_copy(self, name):
        """Does frame slot `name` hold a type that is duplicable only with a
        SPELLED `.copy()`?

        Design 219 folded the ExplicitCopy tier's READ POLICY into 'nocopy' —
        both refuse a silent duplicate, which is the only thing a read policy
        answers. `_materialize_closure_captures` needs the other half of the old
        answer (a `.copy()` exists, so the capture can take its own duplicate
        instead of moving the frame's), and that is a question about the type's
        CONFORMANCE, asked here.
        """
        slot_type = self._frame_slot_type(name)
        if slot_type is None or self._tc is None:
            return False
        ns = (getattr(self._tc, '_entry_module_ns', None)
              or getattr(self._tc, 'namespace', None))
        if ns is None or not hasattr(ns, 'copy_tier'):
            return False
        return ns.copy_tier(slot_type) == 'explicit'

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

    # ------------------------------------------------------------------ #
    # design 218b: SCOPE-END RELEASE — the funnel and its exit edges
    # ------------------------------------------------------------------ #
    #
    # A driven body's locals live in FRAME FIELDS, which outlived every scope
    # they were written in and died with the frame (DF-217p, 66 corodiff cells).
    # Deterministic destruction is unconditional, so a frame-resident local now
    # releases where its non-suspending twin releases it. "Release at every scope
    # exit" quantifies over positions, so it is a FUNNEL (obligation 1):
    # `_scope_release_seq` is the one emitter, and its entry points are exactly
    # the edges by which control leaves a scope.
    #
    #   E-FALL  fallthrough out of a lowered block — `_lower_block`, entered by
    #           `_split_if`, `_split_if_let`, `_split_guard_let`, `_split_while`,
    #           `_split_for`, `_split_match` and `_split_try_catch`
    #   E-BRK   `break`    — `_lower_stmt`, via `_scope_release_to_loop`
    #   E-CNT   `continue` — `_lower_stmt`, via `_scope_release_to_loop`
    #   E-RET   the done path — `_done_seq`, via `_scope_release_all`, ahead of
    #           the `release()` that stays as the backstop for what no scope
    #           owned (params, and any field on a path the walk cannot prove)
    #   E-REDEF a design-107 same-scope redefinition — `_lower_inplace`, via
    #           `_redefinition_release`, right after the replacing store
    #
    # A MISSED edge degrades to the old behavior (a late release, loud in the
    # corodiff lane as DEINIT-ORDER) and never to a double free: every shape
    # `_release_shape` emits is the idempotent tag-drop, and teardown drops iff
    # occupied.
    def _push_scope(self, names, loop_body=False):
        self._scope_stack.append((list(names), loop_body))

    def _pop_scope(self):
        self._scope_stack.pop()

    def _block_scope_names(self, block):
        """The frame-resident bindings `block`'s own statements introduce, in
        DECLARATION order, read off the scope map `_uniq_walk_block` built."""
        entry = self._scope_binders.get(id(block))
        if entry is None or entry[0] is not block:
            return []
        out = []
        for binder in entry[1]:
            name = getattr(binder, 'name', None)
            if name and name in self.encmap:
                out.append(name)
        return out

    def _scope_release_seq(self, names):
        """THE scope-end release: drop the scope's own bindings in reverse
        declaration order (LIFO), each in its encoding's shape.

        Entry points (process rule 1): `_lower_block` (E-FALL),
        `_scope_release_to_loop` (E-BRK / E-CNT) and `_scope_release_all`
        (E-RET). `_redefinition_release` is the fifth edge and releases ONE
        named binding rather than a scope, through the same
        `_release_shape`."""
        seq = []
        for name in reversed(names):
            seq.extend(self._release_shape(
                name, self.encmap.get(name), self._frame_slot_type(name)))
        return seq

    def _scope_release_to_loop(self):
        """E-BRK / E-CNT: every scope the jump exits, innermost first, out to
        and INCLUDING the loop body's — the transform's twin of codegen's
        `_cleanup_to_loop_boundary` (DF-218r)."""
        seq = []
        for names, is_loop_body in reversed(self._scope_stack):
            seq.extend(self._scope_release_seq(names))
            if is_loop_body:
                break
        return seq

    def _scope_release_all(self):
        """E-RET: every open scope, innermost first. Runs ahead of `release()`,
        which then finds those slots empty and drops only what no scope owned."""
        seq = []
        for names, _ in reversed(self._scope_stack):
            seq.extend(self._scope_release_seq(names))
        return seq

    def _redefinition_release(self, s):
        """E-REDEF: the binding a design-107 same-scope redefinition REPLACED
        dies at the redefinition point, after the replacing store — which is
        where codegen's `_drop_redefined_same_scope` drops the sync twin's.

        The two ENCODINGS split here. A frame-resident replaced binding is
        released by this method. One that stayed an ordinary local is codegen's
        to drop, and codegen matches it by NAME — which `_uniquify_bindings`
        has just made different from the replacing binding's, so the pairing is
        handed over explicitly on `coro_redefines`. Without it the two halves
        read as unrelated locals in every body the transform renames but does
        not make frame-resident, the plainest of which is a non-suspending
        SPAWN root."""
        entry = self._redefines.get(id(s))
        if entry is None or entry[0] is not s:
            return []
        seq = []
        line = getattr(s, 'line', 0) or 0
        col = getattr(s, 'column', 0) or 0
        local_names = []
        for name in reversed(entry[1]):
            if name in self.encmap:
                seq.extend(self._release_shape(
                    name, self.encmap.get(name), self._frame_slot_type(name),
                    line, col))
            else:
                local_names.append(name)
        if local_names and isinstance(s, LetStatement):
            # One `let` replaces at most one binding of its own name; a
            # destructuring `let`'s leaves keep their own statement and are not
            # reachable through this single-name hand-off.
            s.coro_redefines = local_names[0]
        return seq

    def _stmt_temp_release(self, s):
        """E-STMT: the temps the ANF hoist lifted OUT of statement `s` die at
        the end of `s`, where the sync twin drops a statement temporary
        (design 240 item 9's rule, on the driven side).

        Emitted for every temp, not only the non-consumed ones. A temp read by
        `take()` was emptied by that read and its clear is a no-op, and proving
        per temp which read it got would buy nothing over an idempotent
        tag-drop — 218b section 3 says as much.

        Entry points: `_lower_stmts` (the CFG walk) and `_lower_stmt_list`
        (in-place lowering), the two places a statement runs to completion."""
        entry = self._stmt_temps.get(id(s))
        if entry is None or entry[0] is not s:
            return []
        seq = []
        for name in reversed(entry[1]):
            seq.extend(self._release_shape(
                name, self.encmap.get(name), self._frame_slot_type(name)))
        return seq

    def _scrutinee_temp_release(self, node):
        """E-STMT, the scrutinee half (218b section 2c). A suspending `match`
        head or `if let`/`guard let` subject is hoisted into a frame temp that
        no scope owns — `FAM_SCRUTINEE_TEMP`, still on design 44's legacy
        encoding — so it lived to teardown. It dies at the construct's MERGE
        point instead, where the sync twin drops its statement temporary.

        The shape is the IDEMPOTENT tag-drop and must stay one: an arm whose
        binding CONSUMED the payload already cleared the tag through the
        DF-210f forget, so the release there is a no-op, and emitting an
        unconditional drop instead would free the payload twice. That forget
        SURVIVES; this closes the non-consuming half's timing. The family is
        narrowed in reach, not retired.

        E-ARM (DF-218w) is the second entry point, one position earlier: an arm
        that claims NOTHING of the scrutinee releases the temp at its own START,
        where the sync twin's inline drop sits. Both edges emit, and the merge
        one is the no-op behind an arm that already released — which is exactly
        what the idempotence above buys."""
        if not isinstance(node, Identifier):
            return []
        return self._scrutinee_temp_release_by_name(node.name)

    def _scrutinee_temp_release_by_name(self, name):
        """`_scrutinee_temp_release` by NAME, for the E-ARM callers.

        They emit AFTER `_rewrite_hosting` has replaced the scrutinee
        identifier with a field access, so the node is no longer there to read
        the name off; they capture the name first and come in here."""
        if name is None or name not in self._hoist_temps or name not in self.encmap:
            return []
        return self._release_shape(
            name, self.encmap.get(name), self._frame_slot_type(name))

    def _arm_claims_no_payload(self, arm):
        """Whether `arm` binds NOTHING of the scrutinee by name — every payload
        binding is `_`, and its design-63 `pattern` binds nothing either.

        The exact condition under which the hoisted scrutinee temp's release may
        move from the construct's merge point to the arm's START (DF-218w).
        Such an arm leaves the payload owned by the temp and aliased by NOBODY,
        which is what makes the early release safe. An arm that does bind by
        name is the opposite case and must keep the merge point: in the driven
        twin those bindings are not owners — a spanning arm stores each into its
        own frame field, a non-spanning one leaves it as a codegen pattern
        binding aliasing the payload the temp still holds — so releasing at the
        arm's start would free the value the binding still reads."""
        if any(b != "_" for b in (arm.bindings or ())):
            return False
        return not self._pattern_binding_names(getattr(arm, 'pattern', None))

    # ----------------------------------------------------- the CFG walk
    def _lower_stmts(self, stmts, loop_ctx):
        for s in stmts:
            if self.cur in self._term:
                break  # unreachable tail after a return/break/continue
            self._lower_stmt(s, loop_ctx)
            # E-STMT: the statement has run to completion on this path, so the
            # temps it owns die here. A statement that left by `return` /
            # `break` / `continue` released through that edge instead.
            if self.cur not in self._term:
                self._emit(self._stmt_temp_release(s))

    def _lower_block(self, block, loop_ctx, extra=(), loop_body=False):
        """Lower a block as its own SCOPE (design 218b).

        `extra` is the construct's own binding(s) — an `if let` payload, a
        `match` arm's payload bindings, a split `try/catch`'s caught error —
        which are declared BEFORE the block's statements and therefore die
        LAST, exactly as the sync twin's arm-scope entry does. `loop_body`
        marks the scope `break`/`continue` unwind to.
        """
        names = list(extra) + self._block_scope_names(block)
        self._push_scope(names, loop_body)
        try:
            self._lower_stmts(block.statements, loop_ctx)
            if block.final_expr is not None and self.cur not in self._term:
                # A branch/loop-body tail expression in statement position: run it
                # for its side effects (its value is discarded here).
                self._lower_stmt(
                    ExpressionStatement(expression=block.final_expr), loop_ctx)
            # E-FALL. A terminated block left by `return`/`break`/`continue`
            # released on its own edge; only the fallthrough is owed here.
            if self.cur not in self._term:
                self._emit(self._scope_release_seq(names))
        finally:
            self._pop_scope()

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
                # DF-134a: remember WHAT we armed, so `release` can drop a
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
        # DF-244a: a `return` carrying a PROPAGATING `try` falls through to the
        # try-landing dispatch at the bottom of this ladder, instead of lowering
        # in place here. It used to be taken by this branch first — so `return
        # try f()`, every expression shape nested in one (`return g(try f())`,
        # `return 1 + (try f())`, `return match try f() { … }`, `return a ?? try
        # f()`, `return (try f()).len()`) and a block TAIL, which lowers as a
        # return, all kept the `try` inside the state machine. The exact failure
        # the landing exists to prevent then came back: the typechecker's second
        # pass read the propagation target off `resume() -> Poll` and named a
        # type the author never wrote, or codegen reached
        # `_create_result_err_for_return` inside `resume` and ICEd. Binding the
        # same expression to a `let` first always worked, which is what made the
        # shape look like an expression-position rule rather than the one
        # statement kind it is. The dispatch has to stay BELOW the control-flow
        # ladder — a `while` whose body holds a propagating `try` is a loop to
        # split, not a statement to wrap — so the deferral is spelled here.
        if isinstance(s, ReturnStatement) and not self._has_propagating_try(s):
            forgets = []
            cap_lets = []
            value = None
            if s.value is not None:
                cap_lets, value = self._rewrite_hosting(s.value, forgets)
            self._emit(cap_lets)
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
            self._emit(self._scope_release_to_loop())     # E-BRK
            self._goto(loop_ctx[1])
            return
        if isinstance(s, ContinueStatement):
            if loop_ctx is None:
                raise CoroTransformError(
                    f"coroutine transform: `continue` outside a loop in "
                    f"`{self.name}`", s.line, s.column)
            self._emit(self._scope_release_to_loop())     # E-CNT
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
        if isinstance(ctrl, TryCatchExpr) and (self._splits_try_catch(ctrl)
                                               or needs_ctrl_split):
            self._split_try_catch(ctrl, loop_ctx)
            return

        # design 196 unit 3: a propagating `try` in a state-machine body. Its
        # error edge leaves this state — for the enclosing split try/catch's
        # catch state, or, with no enclosing catch, out of the coroutine
        # altogether through the frame's own done sequence. THE ONE DISPATCH for
        # a propagating `try`, reached by every statement kind that can carry
        # one: a bare expression statement, a `let`, an assignment — and, since
        # DF-244a, a `return` (which defers to it from its own branch above).
        if self._has_propagating_try(s):
            if self._try_ctx is not None:
                self._emit_try_landing(s)
            else:
                self._emit_try_propagate(s)
            return

        # Non-suspending statement (incl. non-spanning control flow): lower in
        # place — identifier→frame-field rewrites, drop-flag clears, returns→done.
        self._emit(self._lower_inplace(s))

    def _split_if(self, e, loop_ctx):
        forgets = []
        cap_lets, cond = self._rewrite_hosting(e.condition, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` in the condition of a "
                f"suspension-spanning `if` in `{self.name}` is not supported",
                e.line, e.column)
        self._emit(cap_lets)
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

        DF-182c: that store is a MOVE when the binding OWNS the payload — a
        NoCopy one has no copy to give and was refused outright, and an
        ExplicitCopy one would have been dropped by both the field and the
        binding. DF-210b narrows the "when": design 182 made the move
        UNCONDITIONAL, and for a payload whose read only RETAINS (the
        Copy tier — an `Arc`, a `String`) the binding never held a
        reference of its own to give, so the frame's release was one too many
        and the payload was destroyed while its source still pointed at it. The
        tier decides, through `_store_binding_in_slot` — the one authority both
        this and `_split_match` now go through.

        `forgets` are the drop-flag clears a `move` SCRUTINEE owes (`if let r =
        move held`): the read has already happened by the time either branch
        runs, so the source field's flag is cleared on BOTH — the value left it
        either way.

        DF-210f adds the clear the author did NOT write. When the scrutinee is a
        HOIST TEMP — the frame slot the transform makes for a suspending
        scrutinee, `guard let out = cmd.output()` — and the binding's store
        CONSUMES the payload, the temp has handed its value over and must give
        up its claim on it. Nothing said so: `forgets` was fed only by an
        explicit `move`, so the frame released the same buffer twice at
        teardown, once through the binding's slot and once through the temp's.
        That is DF-206f — a `Vector<String>` freed twice in
        `__Frame_main_release`, which is where irdet died after printing its
        answer. The author cannot write the `move` here, because the temp is not
        a name they have; the transform owns the temp, so the transform owes the
        clear.

        DESIGN 218 STAGE 2 DISSOLVES THAT RULE for a migrated temp. The
        scrutinee is `self.__hoistN.take()`, which empties the slot in the same
        method body the value leaves by, so there is no separate claim left to
        give up and nothing here to remember to do. The rule survives only for
        the encodings stage 2 did not migrate, and goes with the last of
        them."""
        bind = node.name
        some_body = []
        if bind in self.encmap:
            some_body.append(self._store_binding_in_slot(
                bind, node.line, node.column))
            src = getattr(node, 'optional_expr', None)
            if (self._slot_store_consumes(bind)
                    and isinstance(src, Identifier)
                    and src.name in self._hoist_temps
                    and src.name in self.encmap
                    and _enc_cleanup(self.encmap[src.name])
                    and src.name not in forgets):
                forgets = list(forgets) + [src.name]
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
        cap_lets, scrut = self._rewrite_hosting(e.optional_expr, forgets)
        self._emit(cap_lets)
        then_entry = self._new_block()
        else_entry = self._new_block() if e.else_branch is not None else None
        merge = self._new_block()
        self._optbind_dispatch(
            e, scrut, then_entry, else_entry if else_entry is not None else merge,
            forgets)
        self.cur = then_entry
        # SC6: the payload binding belongs to the THEN-branch's scope and dies
        # at its end, ahead of nothing and after the branch's own locals.
        self._lower_block(e.then_branch, loop_ctx,
                          extra=[e.name] if e.name in self.encmap else ())
        if self.cur not in self._term:
            self._goto(merge)
        if else_entry is not None:
            self.cur = else_entry
            self._lower_block(e.else_branch, loop_ctx)
            if self.cur not in self._term:
                self._goto(merge)
        self.cur = merge
        self._emit(self._scrutinee_temp_release(e.optional_expr))   # E-STMT/2c

    def _takes_temp(self, name):
        """Whether a read of frame field `name` is a `take()`.

        True for the transform's own SINGLE-USE temps once they are migrated:
        the ANF hoist's `__anfN`, the `try` hoist's `__trycallN`, the
        value-conditional hoist's `__vchN`, and the payload binding a `??`/`?.`
        lowering makes (`__vcN`, which the split rename turns into `__obN` —
        `_prep_ob_split` is what remembers). Each is written once and read once,
        in the position the lowering lifted an expression out of, so the read
        hands the value over and `take()` is that in one method body.

        False for everything else, including a user's own binding: a name the
        author wrote can be read more than once, and which of those reads
        consumes is the use site's own tier question."""
        enc = self.encmap.get(name)
        return bool(_enc_is_slot(enc)
                    and (_is_consuming_temp(name)
                         or name in self._vc_ob_bindings))

    def _split_guard_let(self, s, loop_ctx):
        forgets = []                           # DF-182c — see `_split_if_let`
        cap_lets, scrut = self._rewrite_hosting(s.optional_expr, forgets)
        self._emit(cap_lets)
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
        self._emit(self._scrutinee_temp_release(s.optional_expr))   # E-STMT/2c

    def _split_while(self, e, loop_ctx):
        if e.condition is not None:
            header = self._new_block()
            body_b = self._new_block()
            exit_b = self._new_block()
            self._goto(header)
            self.cur = header
            forgets = []
            cap_lets, cond = self._rewrite_hosting(e.condition, forgets)
            if forgets:
                raise CoroTransformError(
                    f"coroutine transform: `move` in the condition of a "
                    f"suspension-spanning `while` in `{self.name}` is not "
                    f"supported", e.line, e.column)
            self._emit(cap_lets)
            self._branch(cond, body_b, exit_b)
            self.cur = body_b
            self._lower_block(e.body, loop_ctx=(header, exit_b),
                              loop_body=True)
            if self.cur not in self._term:
                self._goto(header)
            self.cur = exit_b
        else:
            body_b = self._new_block()
            exit_b = self._new_block()
            self._goto(body_b)
            self.cur = body_b
            self._lower_block(e.body, loop_ctx=(body_b, exit_b),
                              loop_body=True)
            if self.cur not in self._term:
                self._goto(body_b)
            self.cur = exit_b

    def _split_for(self, s, loop_ctx):
        """State-split a range `for`, in BOTH range flavours (DF-225m).

        THE INDUCTION VARIABLE IS THE FRAME FIELD here — there is no `Range` /
        `RangeInclusive` iterator object in a driven body, because the loop's
        state has to survive a suspension as plain frame slots. So this method
        is the transform's own copy of builtin.saw's two `next()` bodies, and it
        owes the same two answers they give:

          * EXCLUSIVE `a..b` — header `i < end`, then `i = i + 1`. Unchanged;
            `i + 1` can reach `end` at most, so it never overflows.
          * INCLUSIVE `a..=b` — header `i <= end`, and the step is GUARDED:
            run the body, then `if i == end` leave the loop, else `i = i + 1`.

        The guard is design 53's `RangeInclusive` shape (yield `last`, latch
        `done`, never step past it) rather than the one-character `<=` fix,
        and it is not decoration: Saw's overflow checks are always on, so a
        `for i in 0..=Int.max` whose step ran unguarded would PANIC on the
        increment exactly where its sync twin terminates — trading DF-225m's
        silent wrong answer for a twin divergence at the boundary. Guarded, the
        step only runs when `i < end`, so `i + 1 <= end` always holds.

        Until this read `is_inclusive` the header was a hard-coded `<`, so
        every `for i in a..=b` in a driven body ran one iteration short and a
        single-iteration `3..=3` ran none at all — silently, since the sync
        twin of the same loop was right."""
        if not isinstance(s.iterable, RangeExpr):
            raise CoroTransformError(
                f"coroutine transform: a suspension inside a `for` over a "
                f"non-range iterable in `{self.name}` is not supported; "
                f"use a `while` loop", s.line, s.column)
        var = s.variable
        inclusive = bool(s.iterable.is_inclusive)
        end_name = f"__end_{var}"
        lo_forgets, hi_forgets = [], []
        lo_caps, lo = self._rewrite_hosting(s.iterable.start, lo_forgets)
        hi_caps, hi = self._rewrite_hosting(s.iterable.end, hi_forgets)
        init = [self._store_field(var, lo, s.line, s.column),
                self._store_field(end_name, hi, s.line, s.column)]
        self._emit(lo_caps + hi_caps + init
                   + self._forgets(lo_forgets) + self._forgets(hi_forgets))
        header = self._new_block()
        body_b = self._new_block()
        incr = self._new_block()
        exit_b = self._new_block()
        self._goto(header)
        self.cur = header
        cond = BinaryOp(op="<=" if inclusive else "<", left=_self_field(var),
                        right=_self_field(end_name))
        self._branch(cond, body_b, exit_b)
        self.cur = body_b
        self._lower_block(s.body, loop_ctx=(incr, exit_b), loop_body=True)
        if self.cur not in self._term:
            self._goto(incr)
        self.cur = incr
        if inclusive:
            # The last iteration leaves here, not through the header — so the
            # step below is unreachable at `i == end` and cannot overflow.
            step_b = self._new_block()
            self._branch(BinaryOp(op="==", left=_self_field(var),
                                  right=_self_field(end_name)),
                         exit_b, step_b)
            self.cur = step_b
        self._emit([AssignStatement(
            target=_self_field(var),
            value=BinaryOp(op="+", left=_self_field(var), right=_int(1)))])
        self._goto(header)
        self.cur = exit_b

    def _split_match(self, e, loop_ctx):
        forgets = []
        # E-ARM (DF-218w) reads the temp by NAME, so capture it before the
        # rewrite below turns the identifier into a field access.
        scrut_name = (e.matched_expr.name
                      if isinstance(e.matched_expr, Identifier) else None)
        cap_lets, scrut = self._rewrite_hosting(e.matched_expr, forgets)
        if forgets:
            raise CoroTransformError(
                f"coroutine transform: `move` of the scrutinee of a "
                f"suspension-spanning `match` in `{self.name}` is not supported",
                e.line, e.column)
        self._emit(cap_lets)
        merge = self._new_block()
        arm_entries = []
        new_arms = []
        for arm in e.arms:
            entry = self._new_block()
            arm_binds = []
            arm_entries.append((arm, entry, arm_binds))
            dispatch = []
            # Carry every payload binding into its frame field, so the arm's
            # (separately-dispatched) entry block can read it after a suspend.
            # Bindings come from the classic enum form (`arm.bindings`) AND — for
            # design-63 patterns — from `arm.pattern` (a bare `case n`, a tuple, or
            # a nested enum pattern). The guard, if any, runs during dispatch and
            # reads these bindings as LOCALS (still in scope in the dispatch arm),
            # so it stays unrewritten — it is stored to the field only in the body.
            #
            # DF-210a: the store goes through `_store_binding_in_slot`, the one
            # authority the `if let` twin uses too, so an OWNED payload crosses
            # by `move` instead of being refused. An alias of an ExplicitCopy
            # payload is what made blade's `main` report `cannot copy value of
            # type `Cli` which implements ExplicitCopy` at `FILE:0:0` on a
            # program that writes no copy at all.
            #
            # The two sources OVERLAP — an enum arm carries its payload names in
            # `arm.bindings` AND in a design-63 `pattern` — so the list is
            # deduplicated. It did not have to be while every store was an alias
            # (writing the field twice is idempotent); a MOVE emitted twice is
            # `use of moved variable`, reported on the compiler's own statement.
            _seen_binds = set()
            _consumed = False
            for bname in list(arm.bindings) + self._pattern_binding_names(arm.pattern):
                if bname == "_" or bname not in self.encmap or bname in _seen_binds:
                    continue
                _seen_binds.add(bname)
                arm_binds.append(bname)          # SC7: the arm scope's own
                dispatch.append(self._store_binding_in_slot(
                    bname, arm.line, arm.column))
                _consumed = _consumed or self._slot_store_consumes(bname)
            # DF-210f: the `if let` twin's rule, on the arm that actually took
            # the payload. An arm whose binding CONSUMED means the scrutinee has
            # given its value up, so a scrutinee the TRANSFORM hoisted must drop
            # its claim — otherwise the frame frees the same buffer twice at
            # teardown, once through the binding's slot and once through the
            # temp's. Per ARM, because only the arm that binds consumes.
            #
            # A MIGRATED temp needs none of it (design 218 stage 2): the
            # scrutinee is `self.__matchN.take()`, read once ahead of the
            # dispatch, so no arm can find a claim still standing. The per-arm
            # asymmetry — only the binding arm forgot — goes with it.
            if _consumed and isinstance(e.matched_expr, Identifier) \
                    and e.matched_expr.name in self._hoist_temps \
                    and e.matched_expr.name in self.encmap \
                    and _enc_cleanup(self.encmap[e.matched_expr.name]):
                dispatch.extend(self._forgets([e.matched_expr.name]))
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
        for arm, entry, arm_binds in arm_entries:
            self.cur = entry
            # E-ARM (DF-218w): an arm that claims no payload drops the temp
            # HERE, where the sync twin's inline drop at extraction sits. The
            # merge release below stays and is a no-op on this path.
            if self._arm_claims_no_payload(arm):
                self._emit(self._scrutinee_temp_release_by_name(scrut_name))
            if isinstance(arm.body, Block):
                self._lower_block(arm.body, loop_ctx, extra=arm_binds)
            else:
                # A BARE arm expression is not a block, so it has no scope of
                # its own — but the payload bindings still die at the arm's end.
                self._push_scope(arm_binds)
                try:
                    self._lower_stmt(
                        ExpressionStatement(expression=arm.body), loop_ctx)
                    if self.cur not in self._term:
                        self._emit(self._scope_release_seq(arm_binds))
                finally:
                    self._pop_scope()
            if self.cur not in self._term:
                self._goto(merge)
        self.cur = merge
        self._emit(self._scrutinee_temp_release(e.matched_expr))   # E-STMT/2c

    # ------------------------------------------- design 196 unit 3: try/catch
    def _split_try_catch(self, e, loop_ctx):
        """CFG-split a `try { … } catch { … }` BLOCK into states.

        The catch arm becomes a STATE of its own, reachable from every state the
        try body lowers into. The try body lowers with `_try_ctx` naming that
        state and the frame field the caught error travels in; each statement in
        it that holds a propagating `try` gets a landing pad (`_emit_try_landing`)
        whose job is exactly to fill that field and jump. Fall off the end of
        either arm and control reaches `merge`, which is what makes this the same
        diamond `_split_if` builds — the only new thing is that the second arm is
        entered from an error edge instead of a condition.

        `_try_ctx` is saved and restored around the TRY body only: a `try` written
        in the CATCH block propagates outward (to an enclosing try/catch, or to
        the caller), never back into this catch, so the catch lowers under the
        enclosing context — which is exactly what nesting means here."""
        catch_entry = self._new_block()
        merge = self._new_block()
        saved = self._try_ctx
        self._try_ctx = (catch_entry, e.error_binding or "error")
        self._lower_block(e.try_block, loop_ctx)
        self._try_ctx = saved
        if self.cur not in self._term:
            self._goto(merge)
        self.cur = catch_entry
        # SC10: the caught error binding is the catch scope's own, and clears at
        # the catch's end.
        err = e.error_binding or "error"
        self._lower_block(e.catch_block, loop_ctx,
                          extra=[err] if err in self.encmap else ())
        if self.cur not in self._term:
            self._goto(merge)
        self.cur = merge

    def _has_propagating_try(self, s):
        """True if `s` holds a bare propagating `try` — one whose error leaves
        the statement for the enclosing catch.

        `try!` and `try?` handle their own error and never leave the statement,
        and a `try` with an INLINE catch handles it on the spot; neither needs a
        landing pad. Two subtrees are not descended: a nested `try { } catch { }`
        block's TRY body (its errors belong to its own catch, and it lowers
        itself) and a closure body (its `try` propagates out of the closure)."""
        found = [False]

        def scan(n):
            if found[0]:
                return
            if isinstance(n, TryExpr):
                if n.variant == "propagate" and n.catch_block is None:
                    found[0] = True
                    return
            if isinstance(n, TryCatchExpr):
                scan(n.catch_block)
                return
            if isinstance(n, ClosureExpr):
                return
            if isinstance(n, ASTNode):
                for c in _child_nodes(n):
                    scan(c)

        scan(s)
        return found[0]

    def _emit_try_landing(self, s):
        """Lower one statement of a split try body behind its own error landing.

        The statement lowers in place exactly as it would anywhere else; what
        wraps it is a synthesized one-statement `try { <it> } catch { … }` whose
        catch does three things and nothing else — store the caught error into
        the try/catch's frame field, set `__state` to the catch's state, and
        `continue` the resume dispatch loop.

        Wrapping rather than open-coding the Ok/Err test is what keeps this
        honest about evaluation: codegen's own try lowering decides where the
        error edge leaves (a `try` buried in an argument list, two `try`s in one
        expression, a `try` inside a non-spanning `if` in the try body), and the
        landing only says where it lands. `continue` reaches the dispatch loop
        from inside the catch region, so the jump is a state transition and not a
        branch inside the state — which is the whole difficulty DF-193a named.

        The synthesized catch binds the raw error under its own `__tclandN` name
        so it cannot collide with the user's binding, which by then names a frame
        field."""
        catch_entry, err_field = self._try_ctx
        line = getattr(s, 'line', self.func.line)
        col = getattr(s, 'column', 0)
        raw = f"__tcland{self._tcland_ctr}"
        self._tcland_ctr += 1
        inner = self._lower_inplace(s)
        landing = Block(statements=[
            self._store_field(err_field,
                              Identifier(name=raw, line=line, column=col),
                              line, col),
            AssignStatement(target=_self_field("__state", line, col),
                            value=_int(catch_entry), line=line, column=col),
            ContinueStatement(line=line, column=col),
        ], final_expr=None, line=line, column=col)
        self._emit([ExpressionStatement(expression=TryCatchExpr(
            try_block=Block(statements=inner, final_expr=None,
                            line=line, column=col),
            catch_block=landing, error_binding=raw,
            line=line, column=col), line=line, column=col)])

    def _propagating_try_errors(self, s):
        """The error type of every propagating `try` in `s`, deduplicated by
        printed form (the same walk `_has_propagating_try` uses, so the two
        always agree about which `try`s are propagating).

        A ROUTED `try` (design 234 §3) counts as its TARGET type: the clause
        converts the error channel BEFORE propagation, so what reaches this
        frame's one error edge is the routed enum. That is what makes the
        routing clause a new tool for suspending code rather than a new
        restriction — two callees with different error types, both routed into
        one domain enum, are ONE type at the fence."""
        out = {}

        def scan(n):
            if isinstance(n, TryExpr):
                if n.variant == "propagate" and n.catch_block is None:
                    routed = getattr(n, 'route_target', None)
                    if routed is not None:
                        out.setdefault(str(routed), routed)
                    else:
                        rt = getattr(n, 'result_enum_type', None)
                        et = rt.unwrap_result_err() if (
                            rt is not None and rt.is_result()) else None
                        out.setdefault(str(et), et)
            if isinstance(n, TryCatchExpr):
                scan(n.catch_block)
                return
            if isinstance(n, ClosureExpr):
                return
            if isinstance(n, ASTNode):
                for c in _child_nodes(n):
                    scan(c)

        scan(s)
        return list(out.values())

    def _propagated_err_value(self, s, raw, line, col):
        """The `Result` this frame finishes with when a propagating `try` in `s`
        fails — the error `raw` names, wrapped for THIS function's return type.

        Two wraps, the same two the direct (non-coroutine) propagation path
        builds: the concrete `ResultErrWrap` when the callee's error type IS the
        one this function returns, and design 56's `ErasedErrWrap` when this
        function returns an erased `Result<T, Box<any Trait>>` and the callee's
        error is a concrete conformer (the re-box at the propagation edge).
        Anything else — two different concrete error types reaching one edge —
        is refused rather than guessed."""
        ret = self.ret
        if ret is None or not ret.is_result():
            raise CoroTransformError(
                f"coroutine transform: a propagating `try` in `{self.name}`, "
                f"whose body suspends, needs `{self.name}` to return a `Result`",
                line, col, source_file=self.src_file)
        fn_err = ret.unwrap_result_err()
        errs = self._propagating_try_errors(s)
        read = Identifier(name=raw, line=line, column=col)
        if len(errs) == 1 and errs[0] is not None and str(errs[0]) == str(fn_err):
            return ResultErrWrap(value=read, result_type=ret, line=line,
                                 column=col)
        ns = getattr(self._tc, 'namespace', None) if self._tc else None
        trait = ns._erased_trait_of(fn_err) if ns is not None else None
        if trait is not None and len(errs) == 1 and errs[0] is not None:
            return ErasedErrWrap(
                value=read, result_type=ret, concrete_err=errs[0],
                trait_name=trait,
                allocator=SawType(TypeKind.STRUCT, struct_name="GlobalAllocator"),
                line=line, column=col)
        names = ", ".join(f"`{e}`" for e in errs) or "none"
        raise CoroTransformError(
            f"coroutine transform: a statement in `{self.name}` propagates "
            f"{len(errs)} different error types with `try` ({names}) across a "
            f"suspension, and the frame carries ONE error out; give each `try` "
            f"its own statement, or handle them with `try <call> catch {{ ... }}`.",
            line, col, source_file=self.src_file)

    def _emit_try_propagate(self, s):
        """Lower one statement whose propagating `try` leaves the COROUTINE.

        With no enclosing `try { } catch { }`, a failing `try` returns the error
        from the function — and in a state machine "returning" means storing the
        Result into the frame's slot and answering `Done`, exactly as an explicit
        `return` does. The landing is `_done_seq` over the wrapped error, under
        the same one-statement `try { … } catch { … }` wrapper the in-block
        landing uses, so codegen's own try lowering keeps deciding where the
        error edge leaves and this only says where it goes.

        Before design 196 unit 3 the `try` survived the transform untouched and
        codegen tried to `ret` a Result out of a `resume` whose return type is
        `Poll` — which the typechecker caught as an error naming `Poll`, a
        type the author never wrote (DF-196d). So `try` was unusable in a task
        body: `try!` panicked, `try?` dropped the cause, and design 92's whole
        failable-returns-Result idiom had no concurrent spelling."""
        line = getattr(s, 'line', self.func.line)
        col = getattr(s, 'column', 0)
        raw = f"__tcland{self._tcland_ctr}"
        self._tcland_ctr += 1
        wrap = self._propagated_err_value(s, raw, line, col)
        inner = self._lower_inplace(s)
        landing = Block(statements=self._done_seq(wrap, []), final_expr=None,
                        line=line, column=col)
        self._emit([ExpressionStatement(expression=TryCatchExpr(
            try_block=Block(statements=inner, final_expr=None,
                            line=line, column=col),
            catch_block=landing, error_binding=raw,
            line=line, column=col), line=line, column=col)])

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
        blk_caps = []
        inner_args = []
        for a in fc.arguments:
            caps, v = self._rewrite_hosting(a.value, forgets)
            blk_caps.extend(caps)
            inner_args.append(Argument(name=None, value=v))
        inner = FunctionCall(name=fc.name, arguments=inner_args,
                             line=fc.line, column=fc.column)
        start = FunctionCall(name="__saw_blk_start",
                             arguments=[Argument(name=None, value=inner)])
        self._emit(blk_caps)
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
            self._emit([self._store_field(bc['target'], take)])
        else:
            self._emit([ExpressionStatement(expression=take)])

    def _emit_recv_call(self, rc):
        """design 62 G3: lower a cooperative `ch.receive()` INLINE into the
        try_receive+yield_now loop, driven across the caller's own resumes. No
        callee frame — the loop is CFG-split exactly like a user `while` with a
        `yield_now` inside. On each visit: try a non-blocking `try_receive`; on a
        value, store it (into the `let v` target or a discard holder) and set the
        completion flag; on empty, suspend (wake 0 = channel-yield) and retry when
        the executor reschedules the task.

        design 224 (G4): a `return ch.receive()` tail ends the coroutine with the
        received value as this frame's `__result`, exactly as a `return g(...)`
        free-function tail and a `return recv.m(...)` method tail already do.

        DF-230a: the loop TOP is a cancellation check, the std.net park-loop
        shape (design 102) — `Err(Cancelled)` is this receive's answer and the
        loop ends, so a cancelled consumer parked on a channel stops instead of
        waiting for a message no one will send. It is checked ahead of the queue
        read on purpose: a cancelled task takes no further message."""
        import copy as _copy
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
        cancel_b = self._new_block()
        body_b = self._new_block()
        yield_b = self._new_block()
        after = self._new_block()
        self._goto(header)
        # header: loop while not have; exit when an answer has been produced.
        self.cur = header
        self._branch(UnaryOp(op="not", operand=_self_field(have)),
                     cancel_b, after)
        # cancel check: a peer cancel is this receive's answer. Storing
        # `Err(Cancelled)` through the same funnel as the received value means
        # the holder, the `return` tail and the frame's teardown need no second
        # shape — the two answers have one type.
        self.cur = cancel_b
        cancel_arm = self._new_block()
        self._branch(self._cancel_place(), cancel_arm, body_b)
        self.cur = cancel_arm
        cancelled_call = MethodCall(object=_copy.deepcopy(recv_expr),
                                    method_name="__cancelled_result",
                                    arguments=[])
        self._emit([
            self._store_field(target, cancelled_call),
            AssignStatement(target=_self_field(have),
                            value=BoolLiteral(value=True)),
        ])
        self._goto(header)
        # body: non-blocking attempt. `if let __rv = <recv>.try_receive() { ... }`
        # is non-spanning (try_receive never suspends), lowered in place here.
        self.cur = body_b
        # design 230 unit C: the seam is `__try_receive_result`, whose Optional
        # carries a `Result<T, ChannelError>` — `Some(Ok(v))` for a message,
        # `Some(Err(Closed))` for a closed and drained channel, `None` only for
        # "empty and open", which is the one answer that means park. The lowering
        # is otherwise the `if let` + store it has always been: `elem_type` is
        # `receive()`'s return type, so the holder, the store funnel and the
        # `return` path all follow the seam without a special case.
        try_call = MethodCall(object=recv_expr,
                              method_name="__try_receive_result", arguments=[])
        # Census S10, and the migration's one FEATURE FLIP. The store used to
        # be a bare alias of the `if let` binding — it did not go through the
        # store funnel at all, so it was tier-BLIND, and the post-transform
        # re-check refused every ExplicitCopy/NoCopy channel element rather
        # than double-freeing it (218a ruling 11a; the wrong-noun diagnostic
        # is DF-218c). `put(move __rvN)` is the honest spelling: the binding
        # owns the received value and hands it to the slot, which is what makes
        # `Channel<Vector<Int>>` and NoCopy elements compile on the driven path
        # for the first time. Blocking `recv()` always worked.
        store = (self._store_field(
                     target, MoveExpr(variable=rv, path=None))
                 if _enc_is_slot(self.encmap.get(target))
                 else AssignStatement(target=_self_field(target),
                                      value=Identifier(name=rv)))
        iflet = IfLetExpr(
            name=rv, optional_expr=try_call, mutable=False,
            then_branch=Block(statements=[
                store,
                AssignStatement(target=_self_field(have),
                                value=BoolLiteral(value=True)),
            ], final_expr=None),
            else_branch=None)
        self._emit([ExpressionStatement(expression=iflet)])
        # Got a value -> back to header (which exits); still empty -> suspend.
        self._branch(_self_field(have), header, yield_b)
        self.cur = yield_b
        # design 230: PARK on the channel instead of yielding READY. The wake
        # reason is the negated address of this channel's readiness word, so the
        # executor leaves the task alone until a send publishes it — the inline
        # lowering and the reference body in `std/channel.saw` carry the same
        # suspension, which is what keeps the body honest as the effect-inference
        # source. Until 230 this was `_int(0)` and a sole waiter burned 100% of a
        # core (DQ-225n). A fresh copy of the receiver: `recv_expr` is already
        # placed in the `try_receive` call above, and an AST node may sit in one
        # place only.
        park_word = MethodCall(object=_copy.deepcopy(recv_expr),
                               method_name="__park_word", arguments=[])
        self._suspend_to(park_word, header)
        self.cur = after
        if rc['target'] is None and not (rc.get('ret') and not self.is_void):
            # E-STMT / row M4: a DISCARDED cooperative `receive()` parks its
            # moved-out value in the `__rcvN` holder, which design 62 G3 gave
            # to teardown. The receive statement is over here, so the value is
            # over too — the sync twin drops a discarded call's result at the
            # statement. (The `ret` arm below hands the value to `__result`
            # instead and must not clear it.)
            rcv = f"__rcv{idx}"
            self._emit(self._release_shape(
                rcv, self.encmap.get(rcv), self._frame_slot_type(rcv)))
        if rc.get('ret') and not self.is_void:
            # The value is in the `__rcvN` holder (a `return` names no target),
            # and this frame's result is what it is for. `move` hands the
            # holder's own reference over — the paired `__saw_forget` keeps the
            # frame's teardown from dropping it a second time — which is the
            # same transfer `return move v` of an owning local makes.
            forgets = []
            mv = MoveExpr(variable=target, path=None,
                          line=self._cur_line or 0, column=0)
            mv.resolved_type = rc['elem_type']
            cap_lets, value = self._rewrite_hosting(mv, forgets)
            self._emit(cap_lets)
            self._done(value, forgets)

    def _emit_nested_call(self, info, loop_ctx):
        """Embed the callee frame (once) and drive it across the caller's own
        resumes: the drive block resumes the sub-frame; on Pending it propagates
        the callee's wake reason and returns Pending (staying in the drive block);
        on Done it captures the callee's result and re-dispatches past the call."""
        fbs = self._fbs
        callee_fb = self._callee_fb(info)
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
                # Census R5. A migrated result gives its claim up inside
                # `take()`; the pair survives for the callee return types the
                # deferred families still hold back (measured: a fixed-array
                # return, a closure return).
                done_body.append(self._store_result(res))
                if _enc_cleanup(callee_fb.result_enc):
                    done_body.append(_forget_call(
                        MemberAccess(object=_self_field(sub), member="__result"),
                        callee_fb.result_defer_family))
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
                done_body.append(self._store_field(target, res))
                if _enc_cleanup(callee_fb.result_enc):
                    # Census R5, the non-tail arm — same pairing, same survivors.
                    done_body.append(_forget_call(
                        MemberAccess(object=_self_field(sub), member="__result"),
                        callee_fb.result_defer_family))
            elif (target is None and not callee_fb.is_void
                  and _enc_owns(callee_fb.result_enc)):
                # design 124: a DISCARDED nested result (`let _ = g()` / a bare
                # `g()` whose callee returns an owned value) has no target to move
                # into, so the sub-frame's `__result` used to sit live until the
                # whole frame was torn down. Clear the slot here instead — that IS
                # the drop, at the statement that discarded it, matching `let _ =`
                # everywhere else in the language.
                if _enc_is_slot(callee_fb.result_enc):
                    done_body.append(ExpressionStatement(expression=_slot_op(
                        MemberAccess(object=_self_field(sub),
                                     member="__result"), "clear")))
                else:
                    done_body.append(AssignStatement(
                        target=MemberAccess(object=_self_field(sub),
                                            member="__result"),
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

    def _callee_fb(self, info):
        """The frame builder this call site embeds, or a clean ANCHORED failure.

        design 223 unit 3. `fbs[info['callee']]` was a bare subscript, so a call
        the classifier said it could embed and the closure walk did not build a
        frame for surfaced as a raw Python `KeyError: 'Holder_wrap'` — no
        breadcrumb, no source anchor, no name for the shape (DF-223a). Units 1
        and 2 close the two ways that could happen; this is what the THIRD one
        will look like when it is found, and it names the invariant it broke so
        the next reader does not have to reconstruct it from a dict key.
        """
        fb = self._fbs.get(info['callee'])
        if fb is None:
            raise CoroTransformError(
                f"internal compiler error: the coroutine transform classified "
                f"this call as embeddable into `{self.name}` under the frame "
                f"key `{info['callee']}`, but no such frame was built. The "
                f"call-site classifier (`_suspending_method_target`) and the "
                f"closure walk that builds frames must agree on every key; "
                f"this is a compiler bug, not a problem with this code.",
                info.get('line', 0) or self._cur_line, 0,
                source_file=self.src_file)
        return fb

    def _build_sub_frame(self, info, fbs):
        """Construct the embedded callee frame from the call's arguments (the
        arrival state). Returns statements: `self.__subN = __Frame_g(args...)`
        plus any drop-flag clears for args moved out of the caller frame."""
        callee_fb = self._callee_fb(info)
        forgets = []
        arg_vals = []
        cap_lets = []
        for i, a in enumerate(info['args']):
            is_ref_param = (i < len(callee_fb.params)
                            and callee_fb.encmap.get(
                                callee_fb.params[i].name) == "ref")
            forwarded = (self._forwarded_ref_handle(a.value)
                         if is_ref_param else None)
            if forwarded is not None:
                arg_vals.append(_unsaferef_init(
                    forwarded, callee_fb.params[i].type.inner_type))
                continue
            caps, val = self._rewrite_hosting(a.value, forgets)
            cap_lets.extend(caps)
            # design 88 (D6): a reference argument to a nested suspending callee is
            # seeded into the callee sub-frame's field as a raw pointer into THIS
            # (caller) frame's storage — the referent lives in the task frame, so
            # it outlives the sub-frame's drive. Cast `&var self.x` ->
            # `UnsafePointer<T>`, which `_seed_field` then wraps in the handle.
            if i < len(callee_fb.params):
                pname = callee_fb.params[i].name
                if callee_fb.encmap.get(pname) == "ref":
                    val = _seed_field(
                        callee_fb, pname, callee_fb.params[i].type,
                        CastExpr(expr=val,
                                 target_type=_ref_ptr_type(
                                     callee_fb.params[i].type)))
                else:
                    # Census S8/S9's seeding half: an owning parameter arrives
                    # into a `Slot<T>` and is born holding its value. WHICH
                    # spelling the argument itself is — an owning read or a
                    # `take()` — is stage 2's question; this only says where it
                    # lands.
                    val = _seed_field(callee_fb, pname,
                                      callee_fb.params[i].type, val)
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
            recv_value = self._sub_frame_recv_ptr(info['recv'], callee_fb)
        init = _build_frame_init(callee_fb, arg_vals, fbs, recv_value=recv_value)
        out = list(cap_lets)
        out.append(AssignStatement(target=_self_field(info['sub']), value=init))
        out.extend(self._forgets(forgets))
        return out

    def _forwarded_ref_handle(self, arg):
        """The POINTER out of a caller-frame reference handle, when the argument
        is design 106's forwarding of one (`g(&var r)` where `r` is a `&var T`
        parameter this frame holds across a suspension) — else None.

        Same argument `_sub_frame_recv_ptr` makes for the receiver: `r` rewrites
        to `self.r.deref()`, and `&` of a place window is a value read the place
        system judges by the pointee's copy tier. The frame is holding the
        pointer already, so forwarding it costs no window and the callee gets
        the identical address either way.
        """
        if not isinstance(arg, ReferenceExpr):
            return None
        inner = arg.expr
        if not isinstance(inner, Identifier):
            return None
        if self.encmap.get(inner.name) != "ref":
            return None
        return MemberAccess(
            object=_self_field(inner.name, getattr(arg, 'line', 0),
                               getattr(arg, 'column', 0)),
            member="p", line=getattr(arg, 'line', 0),
            column=getattr(arg, 'column', 0))

    def _sub_frame_recv_ptr(self, recv, callee_fb):
        """The POINTER a nested suspending method call seeds its sub-frame's
        `__recv` with (design 84; census P1 in its stage-3 form).

        The receiver is a caller-frame local/param, and the address of one is
        `&(<rewritten place>) as UnsafePointer<T>` — the drive-site cast, in the
        one position the transform takes an address.

        EXCEPT when the receiver is already reached through a HANDLE this frame
        holds — the caller's own `self`, or a `ref`-encoded binding
        (`read_len(stream: &TcpStream)` calling `stream.read()`). Both rewrite
        to a `deref()` place window, and `&` of a window is a VALUE read the
        place system refuses for a move-only type: ``lends a place of type
        `Command`, which is move-only`` on std's `Command.run`, and the same for
        `TcpStream` two frames below a spawned server. Re-taking that address
        was never the right operation anyway — the frame is holding the pointer
        already, so the sub-frame is handed the SAME pointer rather than the
        address of a lend of it. Forwarding costs no window and asks the place
        system nothing.
        """
        handle = None
        if isinstance(recv, SelfExpr) and self.has_recv:
            handle = "__recv"
        elif (isinstance(recv, Identifier)
                and self.encmap.get(recv.name) == "ref"):
            handle = recv.name
        if handle is not None:
            line, col = getattr(recv, 'line', 0), getattr(recv, 'column', 0)
            # Cast so the callee's pointer MUTABILITY is the callee's business:
            # a `&T` binding's handle carries a read-only pointer, and the
            # receiver slot of a driven method frame is spelled without that
            # qualification.
            return CastExpr(
                expr=MemberAccess(object=_self_field(handle, line, col),
                                  member="p", line=line, column=col),
                target_type=callee_fb.recv_ptr_type)
        recv_rewritten = self._rewrite_expr(recv, [])
        return CastExpr(
            expr=ReferenceExpr(expr=recv_rewritten, mutable=False),
            target_type=callee_fb.recv_ptr_type)

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
        """A `__saw_forget` on frame field `name`, CITED with the family that
        kept the field off `Slot<T>` — the one entry the frame-field half of the
        purge has (see `_forget_call`).

        Raises if the field has no family, and that is the point: a forget on a
        MIGRATED field would be the mispairing the whole design exists to make
        unrepresentable, so the emission refuses rather than emitting one."""
        family = self.defer_families.get(name)
        if family is None:
            raise CoroTransformError(
                f"internal: `__saw_forget` on `{name}`, which is not held back "
                f"by any deferred census family (design 218 stage 4). A "
                f"migrated field gives its claim up in `take()`.",
                getattr(self.func, 'line', 0), getattr(self.func, 'column', 0),
                getattr(self.func, 'source_file', None))
        return _forget_call(_self_field(name), family)

    def _forgets(self, names):
        return [self._forget_stmt(n) for n in names]

    def _rewrite_expr(self, node, forgets):
        """Frame-aware expression rewrite: `Identifier(frame local)` ->
        `self.<field>` read; `move <frame local>` -> field read (+ record an
        opt-encoded move in `forgets`). Does NOT descend into control-flow blocks
        differently — callers process nested statement lists via
        `_lower_stmt_list` so forgets are scoped to the executing branch.

        The rewrite's ONE exit, so every node it puts in a position the source
        wrote goes through `_substitute` and inherits that position's marks
        (design 237). `_rewrite_expr_node` below is the dispatch; when it hands
        back the node it was given the carry is a no-op."""
        return _substitute(node, self._rewrite_expr_node(node, forgets))

    def _rewrite_expr_node(self, node, forgets):
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
        # (retain for Copy) exactly as for ordinary code.
        if isinstance(node, ClosureExpr):
            self._materialize_closure_captures(node)
            return node
        # DF-187c: a control-flow BODY reached through an EXPRESSION — a match
        # arm's block or a value `if`'s branch, as in `let v = match f() { case
        # Ok(x) -> x, case Err(_) -> { return None } }`. It is a statement list,
        # so a `return` in it owes the frame's done sequence. The generic
        # recursion below only rewrote its identifiers and left the `return`
        # raw, which lowered to a bare `ret <value>` out of a resume method
        # whose result type is `Poll`: invalid IR, caught by llvmlite rather
        # than by anything in the compiler. `_lower_inplace` handles the same
        # blocks when the construct IS the statement; doing it here covers every
        # expression position instead — a `let`'s value, an assignment's RHS, a
        # call argument. A CLOSURE returned just above, so a closure's body —
        # where `return` returns from the CLOSURE — never reaches this.
        if isinstance(node, Block):
            self._lower_block_in_place(node)
            return node
        if self.has_recv and isinstance(node, SelfExpr):
            # Census R4. The method's `self` -> the receiver LENT through the
            # frame's handle: `self.__recv.deref()` (here `self` is the frame —
            # resume's receiver).
            #
            # This was `self.__recv[0]` under a `frame_place_read` mark, which
            # is the transform asserting "ownership already settled here" about
            # a raw pointer read the checker could not judge. `deref()` is an
            # ordinary `borrows` accessor, so the whole postfix zoo the receiver
            # rewrite needs — field reads and writes, `&self` and `&var self`
            # method calls, nested place hops — is the places system doing what
            # it already does, judged rather than asserted.
            return _unsaferef_deref(
                _self_field("__recv", node.line, node.column),
                node.resolved_type, line=node.line, column=node.column)
        if isinstance(node, MoveExpr) and node.path is None and node.variable in self.encmap:
            name = node.variable
            enc = self.encmap[name]
            # Census D1: on a migrated field the `move` IS `take()`, which
            # empties the slot in the same method body the value leaves by —
            # so there is no separate flag clear to pair with, and no pairing
            # to get wrong (DF-206f / DF-210f / DF-217h were three sites that
            # mispaired exactly this).
            if _enc_cleanup(enc):
                forgets.append(name)
            read = _read_field(name, enc, getattr(node, 'line', 0),
                               getattr(node, 'column', 0),
                               move_read=_enc_owns(enc),
                               saw_type=node.resolved_type)
            # design 131: `move o!` moved the binding AND projected the payload.
            # The `move` half is what the field read + `__saw_forget` above
            # express; re-apply the `!` so the expression still has the payload's
            # type. (A "self_opt"-encoded field reads as the whole `T?`, so
            # without this the unwrap would simply vanish.)
            if getattr(node, 'unwrap', False) and not isinstance(read, ForceUnwrap):
                read = ForceUnwrap(expr=read, line=getattr(node, 'line', 0),
                                   column=getattr(node, 'column', 0))
                if not _enc_is_slot(enc):
                    # DEFERRED: opt_closure, address-taken, window-move,
                    # rendering-operand, void-payload, fixed-array,
                    # scrutinee-temp — the legacy `move o!`, whose `!` projects
                    # out of a field the checkpoint must not re-judge.
                    #
                    # The MIGRATED read needs no mark and no longer carries one:
                    # `self.o.take()` hands back an owned temporary, and design
                    # 131 already says a payload read out of a call result is
                    # the value being yours. Stage 4's citation gate is what
                    # found this one — it was the only stamp left on a migrated
                    # path, asserting past a rule that now answers correctly.
                    read.frame_place_read = True
                _answered(read, node.resolved_type)
            return read
        if (isinstance(node, ForceUnwrap) and isinstance(node.expr, Identifier)
                and self._takes_temp(node.expr.name)):
            # `__anfN!` — the ONE position where a consuming temp does not
            # take. Unwrapping projects the payload out of the optional and
            # leaves the optional itself as a temporary nobody registers: on the
            # PLAIN path codegen leaks exactly this shape (DF-217m, pinned), so
            # taking here would trade a late release for no release at all.
            # Borrowing keeps the payload in the slot, where the frame's own
            # `clear()` releases it exactly once.
            inner = node.expr
            node.expr = _substitute(inner, _read_field(
                inner.name, self.encmap[inner.name], inner.line, inner.column,
                owning_read=True, saw_type=inner.resolved_type))
            return node
        if isinstance(node, Identifier) and node.name in self.encmap:
            enc = self.encmap[node.name]
            # Census T1-T4 (design 218 stage 2): the transform's own single-use
            # temps are CONSUMED at their one read, so a migrated one reads as
            # `take()`. On a legacy encoding the answer is unchanged — the
            # bookkeeping there is the `__saw_forget` the hoisters register,
            # which is exactly what DF-217h shows nobody can be trusted to pair.
            if self._takes_temp(node.name):
                return _read_field(node.name, enc, node.line, node.column,
                                   move_read=True,
                                   saw_type=node.resolved_type)
            return _read_field(node.name, enc, node.line,
                               node.column, owning_read=True,
                               saw_type=node.resolved_type)
        if isinstance(node, ASTNode):
            for f in structural_fields(node):
                setattr(node, f.name,
                        self._rewrite_expr_val(getattr(node, f.name), forgets))
        return node

    def _rewrite_assign_target(self, target, forgets):
        """The rewrite of an assignment's TARGET, which is a write and not a read.

        Reassigning a WHOLE frame-resident binding of an owning type
        (`var out = "none"` … `out = "ok"` across a suspension) writes the FIELD,
        not the field's payload: the field is `T?` — the optional's tag is the
        binding's drop flag (design 44) — so the store is the same
        `self.out = <T>` an initializing `let` emits, which auto-wraps to `Some`
        and drops whatever the field held. Reading `out` yields `self.out!`, and
        rewriting the target the same way asked codegen to write THROUGH a
        `ForceUnwrap`: a leak of the old payload before design 176 made `!` an
        illegal assignment target, and since then a clean compile error on an
        ordinary program (DF-196a, fixed by design 196 unit 3).

        Only a bare whole-binding target changes. `out.field = v`, `out[i] = v`
        and every other projection still reads the binding to reach the storage
        under it, so they take the ordinary read rewrite — as does a `ref`-encoded
        binding, whose write really does go through the frame's pointer."""
        if isinstance(target, Identifier) and _enc_unwraps(
                self.encmap.get(target.name)):
            # DEFERRED: opt_closure, address-taken, window-move,
            # rendering-operand, void-payload, fixed-array, scrutinee-temp — the
            # `_enc_unwraps` guard is what confines this to legacy fields; a
            # migrated one takes the ordinary rewrite below, where `put`'s
            # by-value parameter is the checkpoint.
            acc = _self_field(target.name, target.line, target.column)
            acc.frame_place_read = True
            return acc
        return self._rewrite_expr(target, forgets)

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

    def _rewrite_hosting(self, expr, forgets):
        """`_rewrite_expr` with a capture-let accumulator installed. Returns
        `(cap_lets, rewritten)` — the `let`s go into the block AHEAD of whatever
        the caller emits for the expression itself.

        THE FUNNEL for design 77 item 4's closure-capture materialization, which
        is a POSITION-QUANTIFIED rule: a closure literal written in a driven body
        captures frame locals through `let <name> = self.<name>.copy()` bindings
        that must PRECEDE it, so every position that can host a preceding
        statement has to install the accumulator. `_lower_inplace` did it for a
        `let`, an assignment and a bare expression statement; everywhere else
        `_cap_lets` stayed None and the closure was refused with a hint naming a
        workaround that does not typecheck for a `sync`-closure parameter
        (DF-191a — no legal spelling at all for `shared.lock({ ... n ... })` in a
        spawned body).

        ENTRY POINTS (obligation 1 — a funnel names its entries):
          * `build_resume` — the body's TAIL expression, which is DF-191a's own
            shape: `func add(...) -> Int { shared.lock({ … }) }`.
          * `_lower_inplace` — `return`, a destructuring `let`, and the
            conditions/scrutinees of an in-place `if`/`while`/`match`/`if let`/
            `guard let`.
          * `_lower_block_in_place` — a nested block's tail expression.
          * `_split_if` / `_split_while` / `_split_for` / `_split_match` /
            `_split_if_let` / `_split_guard_let` — the condition, range bounds or
            scrutinee of a CFG-split construct, emitted into the block the branch
            terminates.
          * `_build_sub_frame` — the ARGUMENTS of a nested suspending call. Its
            receiver does not need one: a receiver is a frame local or param
            read, never a closure literal.
          * `_emit_blk_call` — the arguments of an offloaded blocking extern.

        Two positions keep a clean refusal, on purpose. A bare (non-block)
        `match` arm expression cannot host a statement at all, so it refuses a
        capture exactly as it refuses a `move`. A `while` CONDITION could host
        one, but the materialization would run ONCE ahead of a condition that
        runs every iteration, which is not what the closure means."""
        saved, self._cap_lets = self._cap_lets, []
        try:
            value = self._rewrite_expr(expr, forgets)
            return self._cap_lets, value
        finally:
            self._cap_lets = saved

    def _materialize_closure_captures(self, cexpr):
        """Append `let <name> = <frame read>` bindings for the closure's captured
        frame locals to the current statement's capture-let accumulator, so the
        closure captures a real local by value. Rejected (clean, anchored) if a
        closure with frame captures appears in a position with no accumulator
        (e.g. a suspension-spanning condition)."""
        names = self._closure_frame_free_names(cexpr)
        wants_recv = self.has_recv and _closure_names_self(cexpr)
        if not names and not wants_recv:
            return
        if self._cap_lets is None:
            raise CoroTransformError(
                f"coroutine transform: a closure capturing a frame-resident local "
                f"in this position of driven `{self.name}` is not supported; bind "
                f"the closure to a `let` in straight-line body code",
                getattr(cexpr, 'line', self.func.line),
                getattr(cexpr, 'column', 0))
        line = getattr(cexpr, 'line', 0)
        col = getattr(cexpr, 'column', 0)
        if wants_recv:
            self._materialize_receiver_capture(cexpr, line, col)
        spec_names = {s.name for s in (cexpr.capture_specs or [])}
        for name in names:
            # The closure takes ownership of the materialized copy via a `move`
            # capture (design 77 item 4). Crucial for a state-machine `resume`:
            # a persistent function-local holding an owning value (Arc/String)
            # would be dropped on EVERY resume re-entry — a double-free across
            # suspensions. `move` consumes the materialized local so it is NOT
            # scope-cleaned; the env owns the sole copy and releases it once at
            # frame death.
            #
            # The materialized local gets a FRESH name per closure, and the
            # closure is renamed onto it. Reusing the frame local's own name put
            # two `let n = self.n.copy()` in one block whenever two closures in
            # the same block captured `n` — "variable `n` is already defined in
            # this scope", and the `move` capture had consumed the first one
            # anyway (DF-196e). A user-WRITTEN capture spec (`[move n]`,
            # `[&var n]`) keeps its own name and its own meaning; only the
            # implicit capture the transform is adding here is renamed.
            if name in spec_names:
                local = name
            else:
                local = f"__cap{self._cap_ctr}_{name}"
                self._cap_ctr += 1
                _rename_in_closure(cexpr, name, local)
                cexpr.capture_specs = list(cexpr.capture_specs or []) + [
                    CaptureSpec(name=local, mode="move", line=line, column=col)]
            if any(isinstance(ls, LetStatement) and ls.name == local
                   for ls in self._cap_lets):
                continue
            # The materialized local must be an INDEPENDENT OWNER — the `move`
            # capture below transfers it into the env, and the env releases it
            # once at frame death. HOW a frame local yields one is a copy-tier
            # question, and it has exactly one oracle in this compiler:
            # `Namespace.read_policy`, reached through `_frame_read_policy` (the
            # same funnel `_store_binding_in_slot` asks for the store side).
            #
            # This spelled `.copy()` for every tier and called that "the same
            # read-out-of-storage discipline as `Vector.get`" — but it never
            # asked, and `.copy()` is not a method every tier HAS. On a NoCopy
            # local explicitly captured `[move r]` it was `type `Res` is not
            # Copy`, and on an AUTOMATIC-Copy struct (design 159: the
            # tier that owes no declaration, so it declares no `copy` either) it
            # was `type `Bag` is not Copy` — both on programs whose
            # non-suspending twins compile, both followed by a spurious `capture
            # of undefined variable` from the materialization that never
            # happened. DF-217c.
            enc = self.encmap[name]
            slot_type = self._frame_slot_type(name)
            policy = self._frame_read_policy(name)
            if policy == 'nocopy' and self._frame_slot_has_explicit_copy(name):
                # Duplicable, but only with ceremony: `.copy()` is the spelling
                # that gives the capture its own value and leaves the frame's
                # intact. (Design 219 folded this tier's READ POLICY into
                # 'nocopy'; the conformance is what still separates the two
                # here, so the branch is keyed on it rather than on the policy.)
                read = MethodCall(
                    object=_read_field(name, enc, line, col),
                    method_name="copy", arguments=[], line=line, column=col)
                forget = None
            elif policy == 'nocopy':
                # No copy exists, and the author wrote `move`: the FRAME hands
                # its own reference over. The paired `__saw_forget` is what
                # keeps that from being a double-free at teardown — exactly the
                # discipline `_rewrite_expr` uses for a `move` of a frame local
                # anywhere else.
                read = _read_field(name, enc, line, col,
                                   move_read=_enc_owns(enc),
                                   saw_type=slot_type)
                forget = self._forget_stmt(name) if _enc_cleanup(enc) else None
            elif policy in ('retain', 'trivial'):
                # The read does not consume: the frame keeps its field and the
                # capture takes its own reference. `frame_owning_read` is design
                # 124's mark for precisely that, and its own docstring names
                # this materialization as the discipline it generalizes.
                read = _read_field(name, enc, line, col, owning_read=True,
                                   saw_type=slot_type)
                forget = None
            else:
                # No answer at all: an unknown slot type keeps the behavior it
                # has always had.
                read = MethodCall(
                    object=_read_field(name, enc, line, col),
                    method_name="copy", arguments=[], line=line, column=col)
                forget = None
            self._cap_lets.append(LetStatement(
                name=local, type_annotation=None, value=read,
                mutable=False, line=line, column=col))
            if forget is not None:
                self._cap_lets.append(forget)

    def _materialize_receiver_capture(self, cexpr, line, col):
        """The RECEIVER arm of capture materialization — census R7, and the
        whole of DF-216g.

        A closure in a driven METHOD body may name `self`. Design 216 rules that
        capture a BORROW (a receiver IS a reference), which the sync lowering
        serves by capturing the receiver pointer into the env. In a driven body
        there is no receiver to point at: the resume method's `self` is the
        FRAME, and the real receiver is behind `__recv`. So the capture takes
        the one value that carries "borrow of the receiver" — a second handle:

            let __cap0_self = self.__recv.copy()
            run_int({ [move __cap0_self] in __cap0_self.deref().n + 1 })

        `copy()` exists for exactly this site. The frame KEEPS `__recv` for its
        later resumes, so the handle cannot be moved out of the field; it is
        DUPLICATED, visibly, through the one sanctioned spelling — `UnsafeRef`
        is `NoCopy` precisely so that duplication is never silent.

        MODE is the binding's mutability, which is what the place system reads
        when the body writes through the window (218a probes P3/P8/P8b): a
        `&self` method materializes a `let` and its writes are refused; a
        `&var self` method materializes a `var` and its writes persist. That is
        the same answer the PRE-transform check gave the same program through
        `_self_borrow_is_exclusive`, reached by a different mechanism — the
        sync twin's rule and the driven form's agree by construction rather
        than by two rules being kept in step.

        Every `SelfExpr` in the body — nested closures included — is rewritten
        to `<local>.deref()`, so `self.n` becomes `__cap0_self.deref().n` and
        the whole postfix zoo is the places system doing what it already does.
        A written `[&self]` / `[&var self]` spec is REPLACED by the value
        capture of the handle: the receiver borrow is what the handle IS, and
        there is no longer a name `self` for the spec to refer to.
        """
        def alloc():
            name = f"__cap{self._cap_ctr}_self"
            self._cap_ctr += 1
            return name

        mutable = bool(getattr(self.func, 'self_mutable', False))
        local = alloc()
        _replace_self_in_closure(cexpr, local, alloc, mutable)
        cexpr.capture_specs = [s for s in (cexpr.capture_specs or [])
                               if getattr(s, 'name', None) != 'self']
        cexpr.capture_specs.append(
            CaptureSpec(name=local, mode="move", line=line, column=col))
        self._cap_lets.append(LetStatement(
            name=local, type_annotation=None,
            value=MethodCall(object=_self_field("__recv", line, col),
                             method_name="copy", arguments=[],
                             line=line, column=col),
            mutable=mutable, line=line, column=col))

    def _lower_stmt_list(self, stmts):
        out = []
        for s in stmts:
            out.extend(self._lower_inplace(s))
            out.extend(self._stmt_temp_release(s))   # E-STMT
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
            cap_lets = []
            value = None
            if s.value is not None:
                cap_lets, value = self._rewrite_hosting(s.value, forgets)
            return cap_lets + self._done_seq(value, forgets)

        if isinstance(s, DestructuringLet):
            # `let (a, b) = value` across a suspension (design 77 item 10): bind
            # the source tuple to a fresh straight-line temp, destructure a
            # `move` of it into per-leaf temps with the ORDINARY lowering, then
            # move each temp into its frame-resident field (the assignment
            # auto-wraps an opt-encoded field to Some). See
            # `_destructure_temp_pattern` for why the original
            # `self.<leaf> = __t.<i>` read was the wrong operation (DF-206b).
            forgets = []
            cap_lets, value = self._rewrite_hosting(s.value, forgets)
            # DF-217o: if none of the destructured bindings are frame-resident,
            # keep the original destructuring let with the rewritten value.
            # A spawn root with no suspension has no frame fields for its
            # locals, and the temp-pattern rewrite would emit `self.a` accesses
            # that name a field nothing created.
            leaf_names = [n for n, _ in self._destructure_leaf_types(
                s.pattern, getattr(s.value, 'resolved_type', None))]
            if leaf_names and all(n not in self.encmap for n in leaf_names):
                s.value = value
                return cap_lets + [s] + self._forgets(forgets)
            src = f"__destrsrc{self._destr_ctr}"
            self._destr_ctr += 1
            out = list(cap_lets)
            out.append(LetStatement(name=src, type_annotation=None, value=value,
                                    mutable=False, line=s.line, column=s.column))
            temp_pattern, moves = self._destructure_temp_pattern(
                s.pattern, s.line, s.column)
            out.append(DestructuringLet(
                pattern=temp_pattern,
                value=MoveExpr(variable=src, line=s.line, column=s.column),
                mutable=False, line=s.line, column=s.column))
            out.extend(moves)
            # E-REDEF: a leaf that REPLACED a same-scope binding retires it here.
            out.extend(self._redefinition_release(s))
            return out + self._forgets(forgets)

        if isinstance(s, LetStatement):
            forgets = []
            cap_lets, value = self._rewrite_hosting(s.value, forgets)
            if s.name in self.encmap:
                new = self._store_field(s.name, value, s.line, s.column)
            else:
                s.value = value
                new = s
            # E-REDEF (design 218b): a design-107 same-scope redefinition retires
            # the REPLACED binding right here, AFTER the replacing store — the
            # initializer derives from the old value, so the drop cannot precede
            # it. Codegen's `_drop_redefined_same_scope` is the sync twin.
            return (cap_lets + [new] + self._redefinition_release(s)
                    + self._forgets(forgets))

        if isinstance(s, AssignStatement):
            forgets = []
            # The VALUE first: `out = out + "!"` reads the old binding, and the
            # target rewrite must not change what that read means.
            cap_lets, s.value = self._rewrite_hosting(s.value, forgets)
            # A whole-binding target on a MIGRATED field is not a write at all
            # any more, it is a `put` — which is why the DF-196a shape (writing
            # THROUGH a `!`) has no spelling here to get wrong.
            if (isinstance(s.target, Identifier)
                    and _enc_is_slot(self.encmap.get(s.target.name))):
                new = self._store_field(s.target.name, s.value,
                                        s.line, s.column)
                return cap_lets + [new] + self._forgets(forgets)
            s.target = self._rewrite_assign_target(s.target, forgets)
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
            # E-STMT / 2c — see the MatchExpr arm below.
            scrut_release = self._scrutinee_temp_release(ctrl.optional_expr)
            cap_lets, ctrl.optional_expr = self._rewrite_hosting(
                ctrl.optional_expr, forgets)
            self._lower_block_in_place(ctrl.then_branch)
            if ctrl.else_branch is not None:
                self._lower_block_in_place(ctrl.else_branch)
            return cap_lets + [s] + self._forgets(forgets) + scrut_release
        if isinstance(s, GuardLetStatement):
            forgets = []
            # A guard's binding outlives the statement, but the TEMP its
            # subject was hoisted into does not — the dispatch read it here.
            scrut_release = self._scrutinee_temp_release(s.optional_expr)
            cap_lets, s.optional_expr = self._rewrite_hosting(
                s.optional_expr, forgets)
            self._lower_block_in_place(s.else_branch)
            return cap_lets + [s] + self._forgets(forgets) + scrut_release
        if isinstance(ctrl, (IfExpr, WhileExpr, MatchExpr)):
            e = ctrl
            if isinstance(e, IfExpr):
                forgets = []
                cap_lets, e.condition = self._rewrite_hosting(e.condition, forgets)
                self._lower_block_in_place(e.then_branch)
                if e.else_branch is not None:
                    self._lower_block_in_place(e.else_branch)
                return cap_lets + [s] + self._forgets(forgets)
            if isinstance(e, WhileExpr):
                forgets = []
                cap_lets = []
                if e.condition is not None:
                    # A capture materialized here would run ONCE, ahead of the
                    # loop, while the condition runs every iteration — so a
                    # closure in a `while` condition keeps the clean refusal.
                    e.condition = self._rewrite_expr(e.condition, forgets)
                self._lower_block_in_place(e.body)
                return cap_lets + [s] + self._forgets(forgets)
            if isinstance(e, MatchExpr):
                forgets = []
                # E-STMT / 2c: read the scrutinee temp BEFORE the rewrite turns
                # the identifier into a field access. A match whose SCRUTINEE
                # was the only suspending thing in it lowers in place (the
                # construct itself spans nothing once the head is hoisted), so
                # this is where that shape's merge point is.
                scrut_name = (e.matched_expr.name
                              if isinstance(e.matched_expr, Identifier)
                              else None)
                scrut_release = self._scrutinee_temp_release(e.matched_expr)
                cap_lets, e.matched_expr = self._rewrite_hosting(
                    e.matched_expr, forgets)
                for arm in e.arms:
                    if isinstance(arm.body, Block):
                        self._lower_block_in_place(arm.body)
                        # E-ARM (DF-218w): an arm claiming no payload drops the
                        # temp at its START. PREPENDED after the body is
                        # lowered, not before — these statements already name
                        # the frame field, and running them back through the
                        # in-place lowering would rewrite an already-rewritten
                        # target. `scrut_release` above is a separate list of
                        # nodes, so no node is shared between two positions.
                        if self._arm_claims_no_payload(arm):
                            arm.body.statements = (
                                self._scrutinee_temp_release_by_name(scrut_name)
                                + arm.body.statements)
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
                return (cap_lets + [s] + self._forgets(forgets)
                        + scrut_release)

        # Fallback: a plain expression statement (`foo()`), a break/continue with
        # a value, etc. — rewrite in place, hosting any drop-flag clears after.
        forgets = []
        cap_lets, ns = self._rewrite_hosting(s, forgets)
        return cap_lets + [ns] + self._forgets(forgets)

    def _store_result(self, value):
        """The write of this frame's result — the one place a value crosses
        into `__result`.

        Two layouts hide behind it (design 134): a spawn root's result lives in
        the group-owned CELL, which is on design 218's trusted list and keeps
        the optional encoding, while a driven frame's and a sub-frame's is a
        field of its own and is a `Slot<T>` since stage 1. The migrated form
        also retires `_result_store_value`'s DF-174b wrinkle: `put` takes a
        `T`, so a `return None` from a `-> T?` body is a `None` of `T?` with
        nothing to disambiguate.

        Being the one place is also what lets the AMBIENT `main` frame convert
        (design 221 unit B3): its slot holds the process exit status, so a
        `Result`-returning `main` is mapped to an `Int` HERE, before the value
        reaches the group-owned cell — the cell then always carries a plain
        `Int` and std needs one non-void root entry rather than one per shape.
        """
        if (self.exit_status_root and self.main_declared_ret is not None
                and self.main_declared_ret.is_result()):
            value = FunctionCall(name=MAIN_EXIT_FUNNEL,
                                 arguments=[Argument(name=None, value=value)])
        if _enc_is_slot(self.result_enc):
            return ExpressionStatement(expression=_slot_op(
                _self_field("__result"), "put",
                [Argument(name=None, value=value)]))
        return AssignStatement(target=self._result_place(),
                               value=self._result_store_value(value))

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
        """Lower a NON-spanning block in place — and as its own SCOPE.

        The scope half is DF-218s's: once a block that returns owes its owning
        locals frame fields, those fields sit in blocks the CFG walk never
        splits, so the scope stack has to follow the in-place descent too.
        E-RET (`_scope_release_all`) then sees the same stack a split block
        would have given it, and E-FALL below closes the scope on the ordinary
        path — the sync twin's `_cleanup_scope`.

        Termination is syntactic here rather than the CFG walk's block-set: the
        lowering of a `return` ends in a `ReturnStatement`, and codegen's
        `_generate_block` stops at the first terminated statement, so an
        appended clear behind one is unreachable rather than ill-formed.

        A block with a VALUE (`final_expr`) takes no E-FALL: its value is
        computed after every statement, so a clear appended to the statement
        list would run BEFORE the expression that reads the binding. Such a
        block keeps today's timing (the release falls to `release()` at Done,
        one position late, never a leak) — and its `return` paths are ordered
        anyway, since E-RET walks this scope off the same stack."""
        names = self._block_scope_names(block)
        self._push_scope(names)
        try:
            self._lower_block_body_in_place(block)
            if (names and block.final_expr is None
                    and not _stmts_terminate(block.statements)):
                block.statements = (block.statements
                                    + self._scope_release_seq(names))   # E-FALL
        finally:
            self._pop_scope()

    def _lower_block_body_in_place(self, block):
        block.statements = self._lower_stmt_list(block.statements)
        if block.final_expr is not None:
            fforgets = []
            cap_lets, block.final_expr = self._rewrite_hosting(
                block.final_expr, fforgets)
            block.statements = block.statements + cap_lets
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
            seq.append(self._store_result(value))
        seq.extend(self._forgets(forgets))
        # E-RET (design 218b): every open scope releases here, innermost first,
        # AFTER the result store (so a `return move local` still has its value
        # to hand back) and AHEAD of `release()`. `release()` survives as the
        # backstop — it finds these slots empty and drops only what no scope
        # owned, which is the params plus any field on a path the scope walk
        # could not prove.
        #
        # This restores scope order among the FRAME's own fields. It cannot
        # order them against codegen's REAL locals (DF-218s): codegen's
        # `_cleanup_all_scopes` runs at the lowered `return Poll.Done`, i.e.
        # after every statement the transform is able to emit, so nothing put
        # here can land after a real local's drop.
        seq.extend(self._scope_release_all())
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
    # `release` is the frame's end-of-scope teardown, emitted at EVERY exit the
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
            object=SelfExpr(), method_name="release", arguments=[]))

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
        # value in a `__rcvN` holder, which owns it until teardown.
        for rc in self.recv_calls:
            if rc['target'] is None:
                rcv = f"__rcv{rc['idx']}"
                owned.append((rcv, self.encmap[rcv], rc['elem_type']))
        return owned

    def _release_seq(self):
        """The body of `release`: drop every owned field in reverse declaration
        order (LIFO, matching both ordinary scope exit and the struct teardown in
        codegen/resources.py).

        CENSUS D2/D3 (design 218 stage 4). D3 asked whether `release` survives
        the migration at all, and 218a's answer — ratified — is that it does:
        design 124 requires the drop to happen EAGERLY at Done, and structural
        deinit only covers box death, so the explicit early call stays. What
        migrated is the BODY. The migrated fields are one safe `clear()` each,
        the legacy assignment survives only for the fields a deferred family
        holds back (`_deferred_family`) and goes with the last of them, and the
        TaskGroup placeholder is not a deferral at all — a NoMove value's
        position is fixed at birth, so occupancy is structural and the overwrite
        IS the join (218a ruling 5)."""
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
            seq.extend(self._release_shape(name, enc, t))
        return seq

    def _release_shape(self, name, enc, t, line=0, column=0):
        """WHAT releasing frame field `name` IS, by its encoding — the one
        decision `_release_seq` (teardown) and `_scope_release_seq` (scope end)
        share, so the two can never drift apart about what a release means.
        They differ only in WHEN they run and over WHICH fields.

        Every shape here is IDEMPOTENT, which is what lets a scope-end clear, a
        `release()` at Done and the box's memberwise teardown all reach the same
        field and drop its payload exactly once between them (218a section 2's
        four-exit argument, conformance K28). A field this returns nothing for
        owns nothing to release."""
        if _enc_is_slot(enc):
            # design 218 census D2: the per-field body of `release` is one
            # safe call. `clear` drops the occupant if there is one and is
            # idempotent by the type, so the box's later memberwise
            # teardown stays a no-op by construction rather than by the
            # tag convention holding.
            return [ExpressionStatement(expression=_slot_op(
                _self_field(name, line, column), "clear",
                line=line, column=column))]
        if _enc_cleanup(enc):
            # The legacy drop-flag clear, for a field
            # `self.defer_families[name]` holds back. Design 44's
            # convention: writing `None` over the tag IS the drop, and the
            # box's later memberwise teardown finds nothing — which the
            # `Slot` branch above gets from the type instead of from the
            # convention holding at every site.
            #
            # Design 218b ruling 6: scope-end covers the deferred families in
            # exactly this spelling, so deterministic destruction is
            # unconditional rather than gated on the Slot migration finishing.
            # A family that later migrates changes the shape here and NOT the
            # place the release sits.
            return [AssignStatement(target=_self_field(name, line, column),
                                    value=NoneLiteral(),
                                    line=line, column=column)]
        if enc == "plain" and _is_taskgroup(t):
            # design 62 G1: a frame-resident TaskGroup is plain-encoded (it must
            # stay addressable for `group.spawn`'s `&group` receiver), so it has
            # no drop flag to clear. Overwrite it with the same always-valid
            # empty placeholder its zero-init uses: the assignment deinits the
            # old group — structured-joining ITS children first, exactly what
            # the task's own scope exit would have done — and installs a fresh
            # empty one that drops for free at box teardown.
            return [AssignStatement(
                target=_self_field(name, line, column),
                value=FunctionCall(name="TaskGroup", arguments=[]),
                line=line, column=column)]
        return []


def _declare_unsafe(decl, unsafe):
    """Give a SYNTHESIZED declaration its design-130 answer, and put it under
    the rule (design 218 stage 3, 218a ruling 1).

    E2 used to exempt the whole post-transform pass from the trigger rule
    because a resume body names `UnsafePointer` and had no declaration to mark.
    It has one now: the transform writes it, from what the declaration actually
    touches, and `unsafe_decl_checked` says the checker should hold it to that
    answer instead of waving it through as synthesized. A wrong answer is a
    compile error on generated code — which is the whole architecture, applied
    to the one rule that was still being skipped rather than satisfied.

    ENTRY POINTS (obligation 1): `_FrameBuilder.build` for the five `Resumable`
    methods, `_make_driver`, `_make_spawn_helper`, `_make_spawn_trampoline`,
    and the two entry executors — i.e. every declaration this file emits."""
    decl.is_unsafe = bool(unsafe)
    decl.unsafe_decl_checked = True
    return decl


def _names_unsafe_type(t, depth=0):
    """Whether `t`'s own tree names an unsafe type — design 130's question, asked
    from the transform, which has no typechecker to ask.

    Two answers make it up. A raw pointer is unsafe by construction. A STRUCT is
    unsafe when its name says so: design 130 REQUIRES an `unsafe struct` to be
    named `Unsafe*` and rejects the declaration otherwise, so the prefix is a
    sound over-approximation — it can only claim a plain `struct UnsafeDefaults`
    is unsafe, and a redundant `unsafe` on a generated declaration is legal
    ("a promise about the contract, not a lie"). Under-claiming is what would
    hurt, and the prefix cannot: every unsafe struct has it. Identity mangling
    appends a SUFFIX (`Foo$m$mod`), so it survives design 144 too.

    Struct FIELDS are not walked, matching `_first_unsafe_type`: unsafety is not
    transitive."""
    if t is None or depth > 12:
        return False
    kind = getattr(t, 'kind', None)
    if kind == TypeKind.POINTER:
        return True
    if kind == TypeKind.STRUCT and (t.struct_name or "").startswith("Unsafe"):
        return True
    for sub in (getattr(t, 'inner_type', None),
                getattr(t, 'array_element_type', None),
                getattr(t, 'func_return_type', None)):
        if _names_unsafe_type(sub, depth + 1):
            return True
    for group in ('type_args', 'element_types', 'param_types'):
        for sub in (getattr(t, group, None) or []):
            if _names_unsafe_type(sub, depth + 1):
                return True
    return False


def _frame_fields_name_unsafe(fb):
    """Whether `fb`'s own FIELD SET names an unsafe type.

    The question `release` has to answer: its body is one `clear()`/`= None` per
    owned field, so it names every field's type. A method frame's `__recv` is an
    `UnsafeRef`, a reference field is one too, a spawn root reaches its cell
    through a raw pointer — and a plain local can be unsafe-typed all by itself
    (`var p: UnsafePointer<Int8>` held across a suspension, an `UnsafeMmioReg`
    driver bound in a driven body)."""
    if fb.has_recv or getattr(fb, 'is_spawn_root', False):
        return True
    # A `ref`-encoded field is an `UnsafeRef` whatever its DECLARED type says:
    # the declaration is `&T`, which names nothing unsafe, and the ENCODING is
    # what turns it into a handle (and the driver's parameter into a raw
    # pointer). Ask the encoding, not the annotation.
    if any(enc == "ref" for enc in fb.encmap.values()):
        return True
    types = [p.type for p in fb.params]
    types += [t for (_, t) in fb.frame_locals]
    types.append(fb.ret)
    types += [rc['elem_type'] for rc in getattr(fb, 'recv_calls', [])]
    return any(_names_unsafe_type(t) for t in types)


def _frame_init_names_unsafe(fb, fbs, seen=None):
    """Whether CONSTRUCTING `fb`'s frame names an unsafe type, at any depth.

    Building a frame seeds every field AND every embedded sub-frame, so the
    walk is `_frame_fields_name_unsafe` over the whole tree: a dead sub-frame's
    receiver placeholder is a null pointer cast, its locals' empty `Slot<T>`
    seeds name their `T`, and either can be the unsafe one.

    This is what a declaration emitting `_build_frame_init` has to ask before it
    answers design 130 (`_declare_unsafe`). Cycles are impossible in a frame
    TREE but the guard is free and the map is keyed by name."""
    if seen is None:
        seen = set()
    if fb.name in seen:
        return False
    seen.add(fb.name)
    if _frame_fields_name_unsafe(fb):
        return True
    for c in fb.calls:
        sub = fbs.get(c['callee'])
        if sub is not None and _frame_init_names_unsafe(sub, fbs, seen):
            return True
    return False


def _closure_names_self(cexpr):
    """Whether a closure literal reaches the enclosing method's receiver —
    by naming `self` in its body (nested closures included, which are part of
    the same body tree) or by listing it in an explicit `[&self]` capture.

    The spec list is consulted for the same reason `_closure_frame_free_names`
    consults it: a capture named but not used still names the receiver, and the
    typechecker has already judged the spelling (design 218 section 4)."""
    found = [False]

    def rule(node):
        if isinstance(node, SelfExpr):
            found[0] = True
        return node

    map_nodes(cexpr.body, rule)
    if not found[0]:
        found[0] = any(getattr(s, 'name', None) == 'self'
                       for s in (cexpr.capture_specs or []))
    return found[0]


def _replace_self_in_closure(cexpr, local, alloc, mutable, seen=None):
    """Rewrite every `self` in a closure body to `<local>.deref()` — the
    receiver reached through the materialized handle (census R7).

    Not `_rename_in_closure`'s job: `self` is a `SelfExpr` node rather than a
    named binding, so the rename rules do not see it, and what replaces it is
    an expression rather than a name. The `deref()` carries no stamped type —
    the post-transform check derives it from the handle's own type argument,
    which is the receiver's.

    A NESTED closure naming `self` gets a handle OF ITS OWN, minted inside the
    enclosing closure's body and moved into the inner env:

        run_int({ [move __cap0_self] in
            let __cap1_self = __cap0_self.copy()
            run_int({ [move __cap1_self] in __cap1_self.deref().v.len() * 10 })
                + __cap0_self.deref().v.len() })

    It cannot share the outer one. `UnsafeRef` is `NoCopy`, so the inner
    closure's implicit capture of the outer handle is refused (``cannot copy
    value of type `UnsafeRef<Bag>` ``) and `[copy …]` is refused with it — the
    tier declaration is what makes duplication a written act, and `copy()` at a
    statement is where it gets written. The sync twin of this shape has always
    worked (`closure_captures_self.saw`'s `Bag.total`), so the driven form owes
    it too.

    `seen` keeps the recursion from re-processing a nested closure the walk
    then descends into again: by the time the outer rule reaches it, its own
    `self`s are already handles, and processing it twice would mint a second
    one per level."""
    if seen is None:
        seen = set()
    seen.add(id(cexpr))

    def rule(node):
        if isinstance(node, ClosureExpr):
            if id(node) not in seen and _closure_names_self(node):
                inner = alloc()
                _replace_self_in_closure(node, inner, alloc, mutable, seen)
                node.capture_specs = [
                    s for s in (node.capture_specs or [])
                    if getattr(s, 'name', None) != 'self']
                node.capture_specs.append(CaptureSpec(
                    name=inner, mode="move", line=node.line,
                    column=node.column))
                cexpr.body.statements.insert(0, LetStatement(
                    name=inner, type_annotation=None,
                    value=MethodCall(
                        object=Identifier(name=local, line=node.line,
                                          column=node.column),
                        method_name="copy", arguments=[],
                        line=node.line, column=node.column),
                    mutable=mutable, line=node.line, column=node.column))
            return node
        if isinstance(node, SelfExpr):
            return MethodCall(
                object=Identifier(name=local, line=node.line,
                                  column=node.column),
                method_name="deref", arguments=[],
                line=node.line, column=node.column)
        return node

    cexpr.body = map_nodes(cexpr.body, rule)
    if cexpr.captures:
        cexpr.captures = [c for c in cexpr.captures if c != 'self']
    if cexpr.capture_modes:
        cexpr.capture_modes.pop('self', None)


def _rename_in_closure(cexpr, old, new):
    """Rename every reference to the enclosing binding `old` inside a closure
    literal to `new` — its body's identifier reads, a `move` of it, a call to it
    when it is itself closure-valued, and the typechecker's capture bookkeeping.

    Safe as a flat rename because `_uniquify_bindings` has already made every
    binding in this body's tree unique by name, so no binding INSIDE the closure
    can be spelled `old` and shadow it. Used only for the capture the transform
    materializes for itself (design 196 unit 4)."""
    def rule(node):
        if isinstance(node, Identifier) and node.name == old:
            node.name = new
        elif isinstance(node, MoveExpr) and node.variable == old:
            node.variable = new
        elif isinstance(node, FunctionCall) and node.name == old:
            node.name = new
        return node

    map_nodes(cexpr.body, rule)
    for spec in (cexpr.capture_specs or []):
        if getattr(spec, 'name', None) == old:
            spec.name = new
    if cexpr.captures:
        cexpr.captures = [new if c == old else c for c in cexpr.captures]
    if cexpr.capture_modes and old in cexpr.capture_modes:
        cexpr.capture_modes[new] = cexpr.capture_modes.pop(old)


def _zeroed_value(enc, saw_type):
    """The empty initial value for a not-yet-live frame field: `None` for a
    cleanup-needing (opt-encoded) field — the drop flag reads not-live, so the
    frame never drops a placeholder — and a zero for a POD field (needs no
    cleanup).

    A migrated field says the same thing as a type rather than as a
    convention: `Slot<T>.empty()` IS the not-yet-live state, and its deinit
    drops nothing."""
    if _enc_is_slot(enc):
        return _slot_static("empty", _clear_escaping(saw_type))
    if _enc_cleanup(enc):
        return NoneLiteral()
    # design 88: a reference frame field in the not-yet-live state is a NULL
    # handle — a dead sub-frame's placeholder, rebuilt with the real referent
    # address when its call site is reached, so never dereferenced. The
    # placeholder is the same null cast it always was, wrapped like every other
    # construction of the handle (design 218 stage 3).
    if enc == "ref":
        return _unsaferef_init(
            CastExpr(expr=_int(0), target_type=_ref_ptr_type(saw_type)),
            saw_type.inner_type)
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
    owner (dropped exactly once at frame teardown).

    A REFERENCE param is where the address is taken (design 222 unit 2). The
    parameter is a `&T`/`&var T` now — the drive site hands the driver an
    ordinary reference and writes no pointer — so the driver forwards it
    (design 106) and casts, inside its own `unsafe`-declared body, into the
    pointer the frame's handle is built over. The crossing did not move; it
    moved INTO the generated declaration, out of the body somebody else wrote.
    """
    from ast_nodes import MoveExpr as _Move
    if getattr(p.type, 'kind', None) == TypeKind.REFERENCE:
        return CastExpr(
            expr=ReferenceExpr(expr=Identifier(name=p.name),
                               mutable=bool(p.type.reference_mutable),
                               in_argument_position=True),
            target_type=_ref_ptr_type(p.type))
    return _Move(variable=p.name, path=None)


def _seed_field(fb: _FrameBuilder, name, saw_type, value):
    """Wrap a frame field's ARRIVING value in whatever its encoding stores.

    A migrated field is born holding its value — `Slot<T>.of(<value>)` — which
    is the type's own answer to the "params start live, locals start empty"
    convention `_zeroed_value` used to spell as `None` for both.

    A `ref`-encoded field is the other half of the same idea and the opposite
    ownership story: the value ARRIVING is a raw pointer (a driver or spawn
    helper takes one, because the drive site is where `&var x` becomes an
    address), and the field wraps it into the non-owning handle.

    ENTRY POINTS (process rule 1): every construction of a frame with real
    arguments — `_make_driver`, `_make_spawn_helper`, `_build_sub_frame`."""
    enc = fb.encmap.get(name)
    if _enc_is_slot(enc):
        return _slot_static("of", _clear_escaping(saw_type),
                            [Argument(name=None, value=value)])
    if enc == "ref":
        return _unsaferef_init(value, saw_type.inner_type)
    return value


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
        # design 218 stage 3: callers hand a POINTER (the drive-site cast, the
        # driver's parameter, or a null placeholder) and the field wraps it
        # here — one construction site for every frame, so the handle can never
        # be built anywhere the pointer was not already being taken.
        field_inits.append(("__recv",
                            _unsaferef_init(recv_value, fb.recv_pointee)))
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
        zrecv = (CastExpr(expr=_int(0), target_type=sub_fb.recv_ptr_type)
                 if sub_fb.has_recv else None)
        field_inits.append((c['sub'],
                            _build_frame_init(sub_fb, zvals, fbs, recv_value=zrecv)))
    for rc in getattr(fb, 'recv_calls', []):
        field_inits.append((f"__have{rc['idx']}", BoolLiteral(value=False)))
        if rc['target'] is None:
            rcv = f"__rcv{rc['idx']}"
            field_inits.append((rcv, _zeroed_value(fb.encmap[rcv],
                                                   rc['elem_type'])))
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
        # design 222 unit 1: the cell address is wrapped into its handle HERE,
        # at the one place a frame is built — the same discipline `__recv` has
        # had since stage 3, so the handle can never be minted anywhere the
        # pointer was not already being taken.
        field_inits.append(("__cellp",
                            _unsaferef_init(cellp_value, _cell_type(fb))))
    else:
        field_inits.append(("__cancel", BoolLiteral(value=False)))
        if not fb.is_void:
            field_inits.append(("__result", _zeroed_value(fb.result_enc, fb.ret)))
    return StructInit(struct_name=fb.frame_name, field_inits=field_inits)


def _read_frame_result(fb: _FrameBuilder, stmts):
    """Move a completed root frame's result out of `__f`, and answer the
    expression that hands it on. `None` for a `Void` body.

    THE ONE PLACE a driven ROOT's result leaves its frame. Entry points:
    `_make_driver` (every non-main driven root — spawn helpers and drive sites
    reach a root through it) and `_make_entry_executor` (the synthesized `main`
    of a suspending program with no spawn). The AMBIENT executor is deliberately
    not one: its frame is erased into a `Box<any Resumable>` before anything can
    read a typed slot, so its result travels through the group-owned cell
    instead (design 221 unit B3).

    Appending to `stmts` rather than returning a block is what lets both callers
    keep their own frame-init and drive-loop preamble; the read must come after
    the loop, and there is nothing else to order.

    Reading the result MOVES it out of the frame: `__f` is a local about to die,
    and the result is the one thing that escapes it. Spelled as the sub-frame
    path spells the same transfer — take the value, then `__saw_forget` the slot
    so the frame's teardown does not release what the caller now owns.

    Design 139 is what forced the spelling. A retain would do for a Copy result
    (a bump the frame's own release then undoes), and that is what used to
    happen; but once `Result<Int, Box<any Error>>` became move-only there was no
    retain to reach for, and a move is what this always was.
    """
    if fb.is_void:
        # design 102 item 1: a `Void` driven body has no `__result` slot — the
        # caller just loops to completion and returns Void.
        return None
    # Census R6. On a migrated slot the read and the give-up are ONE call:
    # `take()` empties the slot as the value leaves it, so the `__saw_forget`
    # that used to follow has nothing left to do.
    if _enc_is_slot(fb.result_enc):
        read = _slot_op(MemberAccess(object=Identifier(name="__f"),
                                     member="__result"), "take")
        stmts.append(LetStatement(name="__res", type_annotation=None,
                                  value=read))
    else:
        # DEFERRED: opt_closure, fixed-array — a ROOT's legacy `__result`, the
        # same two return types the sub-frame path sees. `spawn-cell` cannot
        # reach here either: a spawn root's result lives in the cell and its
        # enqueue path has no driver.
        read = MemberAccess(object=Identifier(name="__f"), member="__result")
        read.frame_place_read = True
        if _enc_unwraps(fb.result_enc):
            read = ForceUnwrap(expr=read)
            read.frame_place_read = True
        stmts.append(LetStatement(name="__res", type_annotation=None,
                                  value=read))
        if _enc_cleanup(fb.result_enc):
            slot = MemberAccess(object=Identifier(name="__f"), member="__result")
            slot.frame_place_read = True
            stmts.append(_forget_call(slot, fb.result_defer_family))
    return MoveExpr(variable="__res")


def _make_entry_executor(fb: _FrameBuilder, fbs):
    """Synthesize the entry executor that replaces a suspending `main` (design 45
    item 1). It builds main's frame and drives it to completion on a single
    cooperative run: each Pending consults the frame's `__wake` reason and, for a
    `sleep(d)`, parks that long (`__saw_exec_park`) before resuming; a
    `yield_now` (wake 0) resumes at once. `main` may thus suspend with no
    user-visible executor.

    design 221 unit B2 (DF-220b): the executor RETURNS main's result. It used to
    declare itself `Void` whatever main returned, so the value reached the
    frame's `__result` slot and was dropped there — every driven program exited
    0. It is main's own frame and its own local, exactly the shape
    `_make_driver` reads, so it reads it through the same funnel.
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
    final = _read_frame_result(fb, stmts)
    return _declare_unsafe(
        Function(name="main", parameters=[],
                 return_type=SawType(TypeKind.VOID) if fb.is_void else fb.ret,
                 body=Block(statements=stmts, final_expr=final),
                 is_synthesized=True,
                 source_file=getattr(fb.func, 'source_file', "")),
        _frame_init_names_unsafe(fb, fbs))


def _make_ambient_entry_executor(fb: _FrameBuilder, fbs):
    """design 89: the entry executor for a suspending `main` in a program that ALSO
    uses the cooperative scheduler (spawns). Instead of the design-45 single-frame
    loop (which drives ONLY main's frame — parking the whole thread while a spawned
    sibling starves), main's frame is boxed erased and handed to the std ambient
    entry executor `__saw_exec_run_root`, which enqueues it as the root member of the
    shared scheduler and drives main AND every task it spawns to completion. This is
    what makes a spawn run eagerly whenever main parks (the core design-89 fix). A
    suspending main with NO spawn keeps the lighter single-frame executor above.

    design 221 unit B3 (DF-220b): a NON-VOID `main` also gets a CELL. Erasure is
    the whole difficulty — once the frame is a `Box<any Resumable>` its typed
    `__result` is unreachable — and a cell is the executor's existing answer to
    exactly that, since a spawned task's value has always travelled out through
    one. So this builds the group-owned cell here (the same four statements
    `_make_spawn_helper` builds), seeds the frame with its address, and hands
    both to `__saw_exec_run_root_status`, which enqueues them and reads the cell
    back out after quiescence — inside the group's lifetime, because the group's
    Deinit drops the cell on the way out.

    The cell is `__ResultCell<Int>` for every `main` shape: the frame stores the
    EXIT STATUS, converted on the way into the slot (`_store_result`). A `Void`
    main keeps the void path above, unchanged.
    """
    if not fb.exit_status_root:
        frame_init = _build_frame_init(fb, [], fbs)
        box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
        box_make = MethodCall(
            object=Identifier(name="Box", type_args=[box_ty]),
            method_name="make",
            arguments=[Argument(name=None, value=frame_init)])
        call = FunctionCall(name="__saw_exec_run_root",
                            arguments=[Argument(name=None, value=box_make)])
        return _declare_unsafe(
            Function(name="main", parameters=[], return_type=SawType(TypeKind.VOID),
                     body=Block(statements=[ExpressionStatement(expression=call)],
                                final_expr=None),
                     is_synthesized=True,
                     source_file=getattr(fb.func, 'source_file', "")),
            _frame_init_names_unsafe(fb, fbs))

    from ast_nodes import StructInit
    cell_ptr = _cell_ptr_type(fb)
    cell_init = StructInit(
        struct_name="__ResultCell", type_args=[fb.ret],
        field_inits=[("__result", NoneLiteral()),
                     ("__cancel", BoolLiteral(value=False))])
    cell_box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="__TaskCell")
    stmts = [
        LetStatement(name="__cbox", type_annotation=None, mutable=True,
                     value=MethodCall(
                         object=Identifier(name="Box", type_args=[cell_box_ty]),
                         method_name="make",
                         arguments=[Argument(name=None, value=cell_init)])),
        LetStatement(name="__cdata", type_annotation=None, mutable=False,
                     value=FunctionCall(name="__saw_box_data", arguments=[Argument(
                         name=None, value=ReferenceExpr(
                             expr=Identifier(name="__cbox"), mutable=False,
                             in_argument_position=True))])),
        LetStatement(name="__cellp", type_annotation=None, mutable=False,
                     value=CastExpr(expr=Identifier(name="__cdata"),
                                    target_type=cell_ptr)),
    ]
    frame_init = _build_frame_init(fb, [], fbs,
                                   cellp_value=Identifier(name="__cellp"))
    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    stmts.append(LetStatement(
        name="__box", type_annotation=None, mutable=True,
        value=MethodCall(object=Identifier(name="Box", type_args=[box_ty]),
                         method_name="make",
                         arguments=[Argument(name=None, value=frame_init)])))
    call = FunctionCall(name=EXEC_RUN_ROOT_STATUS, arguments=[
        Argument(name=None, value=MoveExpr(variable="__box", path=None)),
        Argument(name=None, value=MoveExpr(variable="__cbox", path=None)),
        Argument(name=None, value=Identifier(name="__cellp")),
    ])
    return _declare_unsafe(
        Function(name="main", parameters=[], return_type=fb.ret,
                 body=Block(statements=stmts, final_expr=call),
                 is_synthesized=True,
                 source_file=getattr(fb.func, 'source_file', "")),
        True)


def _make_driver(fb: _FrameBuilder, mode, fbs):
    """Synthesize the driver function that steps a frame to completion.

    value: `func __saw_drive_<f>(<params>) -> R { var __f = <frame>; loop resume; __f.__result }`
    steps: `func __saw_drive_steps_<f>(<params>) -> Int { ...; count Pendings; __n }`
    """
    params = fb.params
    # A method driver takes the receiver first, as a `&Struct` (design 222 unit
    # 2) — forwarded and cast here, so the frame's handle is built over the same
    # address it always was and the drive site names no pointer.
    recv_value = (CastExpr(expr=ReferenceExpr(expr=Identifier(name="__recv"),
                                              mutable=False,
                                              in_argument_position=True),
                           target_type=fb.recv_ptr_type)
                  if fb.has_recv else None)
    frame_init = _build_frame_init(
        fb, [_seed_field(fb, p.name, p.type, _frame_param_arg(p))
             for p in params], fbs, recv_value=recv_value)

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
        final = _read_frame_result(fb, stmts)

    # design 88, as design 222 unit 2 leaves it: a reference param flows through
    # the driver AS A REFERENCE. The drive site writes `&var x` and nothing more;
    # the driver forwards it and casts inside its own body, where the `unsafe`
    # declaration that owns the crossing already is.
    driver_params = [Parameter(name=p.name, type=p.type,
                               is_reference=(p.type.kind == TypeKind.REFERENCE),
                               reference_mutable=bool(
                                   p.type.kind == TypeKind.REFERENCE
                                   and p.type.reference_mutable))
                     for p in params]
    if fb.has_recv:
        # And the receiver likewise (design 222 unit 2). The drive site used to
        # splice `(&c) as UnsafeConstPointer<C>` into the CALLER's own body — a
        # pointer in a function whose author never wrote one, which is what kept
        # E2 alive after stage 3. It writes `&c` now; `recv_ref_type` is that
        # reference, `_build_frame_init` still gets the pointer, and the cast
        # between them happens here.
        driver_params = [Parameter(name="__recv", type=fb.recv_ref_type,
                                   is_reference=True, reference_mutable=False)
                         ] + driver_params
    # The driver names a raw pointer when its own signature does (a receiver, a
    # reference parameter the drive site addressed) — and also when merely
    # BUILDING the frame does, which reaches down the embedded call tree.
    return _declare_unsafe(
        Function(name=driver_name, parameters=driver_params, return_type=ret,
                 body=Block(statements=stmts, final_expr=final),
                 is_synthesized=True,
                 source_file=getattr(fb.func, 'source_file', "")),
        _frame_init_names_unsafe(fb, fbs))


# --------------------------------------------------------------------------- #
# spawn lowering (design 52b item 2)
# --------------------------------------------------------------------------- #

def _helper_param(fb: _FrameBuilder, p):
    """The `__spawn_<f>` helper's parameter for one of `f`'s parameters.

    A reference parameter travels to the helper AS A REFERENCE, exactly as it
    travels to a `__saw_drive_<f>` driver (design 88, design 201 in spawn
    position, design 222 unit 2 for the spelling): the spawn SITE writes
    `&var x`, the helper takes `&var T`, and `_frame_param_arg` does the crossing
    inside the helper's own `unsafe`-declared body. Everything else keeps its own
    type."""
    is_ref = getattr(p.type, 'kind', None) == TypeKind.REFERENCE
    return Parameter(name=p.name, type=p.type, is_reference=is_ref,
                     reference_mutable=bool(is_ref and p.type.reference_mutable))


def _reject_spawn_frame_refs(fb: _FrameBuilder, fbs):
    """design 88 (D6 confinement crux), as design 201 leaves it.

    A frame that holds a reference across a suspension holds a pointer into
    somebody else's storage, and the question is always whether that storage
    outlives the frame. For a DRIVEN-in-place frame it does by construction (the
    driver's own caller owns the referent and is parked on the drive). For a
    SPAWNED frame — boxed onto the group's run queue and resumed later — design
    88 answered "it cannot" and refused every reference PARAMETER at a spawn
    root. Design 201 replaces that blanket refusal with the EXTENT the
    typechecker now tracks: a `&`/`&var` argument at a spawn borrows its root for
    the TASK's life, the handle carries the borrow, `join()` releases it, and a
    root declared after the group is already refused by design 188's LIFO rule.
    So the spawner's storage provably outlives the task, and the parameter is
    sound in exactly the way a borrow capture (design 189) is.

    What still cannot be spawned is an across-suspend reference LOCAL: no source
    construct binds one today (`let r = &x` is refused), so this is a
    belt-and-braces gate on the frame layout rather than a user-facing rule.

    MULTI-THREADED groups are unaffected and refuse a reference parameter still —
    through `_check_spawn_frame_send` below, since a `&T` is not `Send`. That is
    the right refusal for the right reason: the hazard there is the thread
    crossing, not the extent.

    Only the ROOT's own locals are checked — NOT embedded callee sub-frames. A
    nested suspending call's reference argument is rewritten to `&self.<field>`
    (a pointer into the TASK frame, which the box keeps alive as long as the task
    runs), so a reference into a task-confined local is sound and stays allowed
    (`read_into(&var buf)` inside a spawned handler works)."""
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
            note = ns.send_check(p.type, "task frame parameter")
            if note is not None:
                raise CoroTransformError(
                    f"cannot spawn `{fbx.func.name}` into a multi-threaded "
                    f"`TaskGroup(threads: ...)`: parameter `{p.name}` of type "
                    f"`{p.type}` is not `Send`, so the task frame cannot cross to a "
                    f"worker thread. Share thread-safe state via `Arc` (and `Mutex` "
                    f"for mutation) or a `Channel` instead of moving it in." + note,
                    getattr(p, 'line', 0) or fbx.func.line,
                    getattr(p, 'column', 0) or fbx.func.column,
                    source_file=fbx.src_file)
        for (lname, lt) in fbx.frame_locals:
            note = ns.send_check(lt, "task frame local")
            if note is not None:
                raise CoroTransformError(
                    f"cannot spawn `{fbx.func.name}` into a multi-threaded "
                    f"`TaskGroup(threads: ...)`: local `{lname}` of type `{lt}` is "
                    f"held across a suspension but is not `Send`, so the task frame "
                    f"cannot cross to a worker thread." + note,
                    fbx.func.line, fbx.func.column, source_file=fbx.src_file)
        for c in fbx.calls:
            callee = fbs.get(c['callee'])
            if callee is not None:
                _check(callee)

    _check(fb)
    # The ROOT's result travels worker -> main across the `join()` barrier, so it
    # too must be Send (a callee sub-frame's result stays on one thread — not checked).
    ret_note = None if fb.is_void else ns.send_check(fb.ret, "task frame result")
    if ret_note is not None:
        raise CoroTransformError(
            f"cannot spawn `{fb.func.name}` into a multi-threaded "
            f"`TaskGroup(threads: ...)`: its result type `{fb.ret}` is not `Send`, so "
            f"the value cannot travel back from the worker thread to `join()`."
            + ret_note,
            fb.func.line, fb.func.column, source_file=fb.src_file)


def _make_spawn_helper(fb: _FrameBuilder, fbs, helper_name=None):
    """Synthesize `__spawn_<f>(__group, <params>) -> Task<T>`.

    Allocate the task's CELL first (design 134), take the raw pointers to its
    result and cancel slots, build f's frame around the cell address, erase both
    into boxes, and hand them to the group together:

        func __spawn_f(__group: &TaskGroup, <params>) unsafe -> Task<T> {
            let __gp    = (&__group) as UnsafePointer<TaskGroup>
            var __cbox  = Box<any __TaskCell>.make(__ResultCell<T>(__result: None,
                                                                   __cancel: false))
            let __cdata = __saw_box_data(&__cbox)
            let __cellp = __cdata as UnsafePointer<__ResultCell<T>>
            let __rp    = (&__cellp[0].__result) as UnsafePointer<T?>
            let __cp    = (&__cellp[0].__cancel) as UnsafePointer<Bool>
            var __box   = Box<any Resumable>.make(__Frame_f(<params>..., __cellp: __cellp))
            let __slot  = __gp[0].__enqueue(move __box, move __cbox)
            let __gen   = __gp[0].__gen_at(__slot)
            Task<T>(result_ptr: __rp, cancel_ptr: __cp, group_ptr: __gp,
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

    tg_ptr = SawType(TypeKind.POINTER,
                     inner_type=SawType(TypeKind.STRUCT, struct_name="TaskGroup"))
    tg_ref = SawType(TypeKind.REFERENCE,
                     inner_type=SawType(TypeKind.STRUCT, struct_name="TaskGroup"),
                     reference_mutable=False)

    stmts = [
        # design 222 unit 2: the helper's `__group` is a REFERENCE now (the spawn
        # site writes `&group` and no cast), so the pointer the enqueue and the
        # handle need is derived HERE, in the one declaration that says `unsafe`
        # about it. Forwarding a received reference is design 106's ordinary
        # spelling; the address is the same one the site used to take.
        LetStatement(name="__gp", type_annotation=None, mutable=False,
                     value=CastExpr(
                         expr=ReferenceExpr(expr=Identifier(name="__group"),
                                            mutable=False,
                                            in_argument_position=True),
                         target_type=tg_ptr)),
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

    frame_init = _build_frame_init(
        fb, [_seed_field(fb, p.name, p.type, _frame_param_arg(p))
             for p in params], fbs,
        cellp_value=Identifier(name="__cellp"))
    box_ty = SawType(TypeKind.EXISTENTIAL, existential_trait="Resumable")
    box_make = MethodCall(
        object=Identifier(name="Box", type_args=[box_ty]),
        method_name="make",
        arguments=[Argument(name=None, value=frame_init)])

    stmts.extend([
        LetStatement(name="__box", type_annotation=None, value=box_make, mutable=True),
        LetStatement(name="__slot", type_annotation=None, mutable=False,
                     value=MethodCall(
                         object=ArrayIndex(array_expr=Identifier(name="__gp"), index=_int(0)),
                         method_name="__enqueue",
                         arguments=[
                             Argument(name=None, value=MoveExpr(variable="__box", path=None)),
                             Argument(name=None, value=MoveExpr(variable="__cbox", path=None))])),
        # design 134: the slot's generation completes the handle's identity, so a
        # handle outliving its task never addresses the task that replaced it.
        LetStatement(name="__gen", type_annotation=None, mutable=False,
                     value=MethodCall(
                         object=ArrayIndex(array_expr=Identifier(name="__gp"), index=_int(0)),
                         method_name="__gen_at",
                         arguments=[Argument(name=None, value=Identifier(name="__slot"))])),
    ])
    if fb.is_void:
        handle = StructInit(
            struct_name="VoidTask", type_args=None,
            field_inits=[("cancel_ptr", Identifier(name="__cp")),
                         ("group_ptr", Identifier(name="__gp")),
                         ("slot", Identifier(name="__slot")),
                         ("generation", Identifier(name="__gen"))])
        ret_type = SawType(TypeKind.STRUCT, struct_name="VoidTask")
        helper_params = [Parameter(name="__group", type=tg_ref,
                                   is_reference=True,
                                   reference_mutable=False)] + \
                        [_helper_param(fb, p) for p in params]
        # The helper hands the cell's `__cancel` address to the handle and casts
        # its group reference to the pointer the queue wants: unsafe by body in
        # every shape (the trusted design-134 cell plumbing).
        return _declare_unsafe(
            Function(name=helper_name, parameters=helper_params,
                     return_type=ret_type,
                     body=Block(statements=stmts, final_expr=handle),
                     is_synthesized=True,
                     source_file=getattr(fb.func, 'source_file', "")), True)
    handle = StructInit(
        struct_name="Task", type_args=[T],
        field_inits=[("result_ptr", Identifier(name="__rp")),
                     ("cancel_ptr", Identifier(name="__cp")),
                     ("group_ptr", Identifier(name="__gp")),
                     ("slot", Identifier(name="__slot")),
                     ("generation", Identifier(name="__gen"))])
    ret_type = SawType(TypeKind.STRUCT, struct_name="Task", type_args=[T])
    helper_params = [Parameter(name="__group", type=tg_ref,
                               is_reference=True, reference_mutable=False)] + \
                    [_helper_param(fb, p) for p in params]
    return _declare_unsafe(
        Function(name=helper_name, parameters=helper_params,
                 return_type=ret_type,
                 body=Block(statements=stmts, final_expr=handle),
                 is_synthesized=True,
                 source_file=getattr(fb.func, 'source_file', "")), True)


def _trampoline_arg(p):
    """The expression `f$spawnroot` passes for one of `f`'s parameters.

    The trampoline's body is ORDINARY SAW that the post-transform typecheck reads
    (`return f(<args>)`), so a REFERENCE parameter is forwarded the way design 106
    spells forwarding — `f(&var m)` — and not as a bare name. That is what makes
    the embedded sub-frame's argument a `ReferenceExpr` the frame rewrite turns
    into `&(self.m[0])`, i.e. the address the trampoline was handed. Passing the
    bare name instead handed `_build_sub_frame` the DEREF to cast, so the callee
    frame's pointer field was seeded with the referent's VALUE — probe J of
    design 201: a segfault the moment the task read through it.

    Everything else is a `move`, for the reason `_frame_param_arg` gives."""
    from ast_nodes import MoveExpr as _Move
    if getattr(p.type, 'kind', None) == TypeKind.REFERENCE:
        return ReferenceExpr(expr=Identifier(name=p.name),
                             mutable=bool(p.type.reference_mutable),
                             in_argument_position=True)
    return _Move(variable=p.name, path=None)


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
        arguments=[Argument(name=None, value=_trampoline_arg(p)) for p in params],
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


# --------------------------------------------------------------------------- #
# the canonicalization passes — one tree-rewriter, three rules
#
# Each pass below normalizes ONE alternate spelling into the single form the
# rest of the transform knows, so no downstream walk has to learn a second one.
# They share `ast_walk.map_nodes`, the WRITE-side twin of `child_nodes`: same
# coverage (every structural field, through any nesting of lists and tuples and
# through the `Argument` wrapper), with each visited node replaced in its parent
# slot. Three hand-rolled copies of this recursion is exactly the shape DF-187b
# found disagreeing about tuples.
# --------------------------------------------------------------------------- #

_rewrite_nodes = map_nodes


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
    return _rewrite_nodes(node, _yield_intrinsic_rule)


def _yield_intrinsic_rule(node):
    if isinstance(node, MethodCall) and getattr(node, 'is_yield_intrinsic', False):
        return FunctionCall(name="yield_now", arguments=[],
                            line=node.line, column=node.column)
    return node


def _rewrite_labeled_calls(node):
    """Rewrite a FULLY-LABELED call back into a `FunctionCall`, everywhere.

    `f(a: 1)` is syntactically a struct literal, so the parser builds a
    `StructInit` and the typechecker reinterprets it as a call, recording the
    equivalent `FunctionCall` in `as_function_call` (design 66). Every
    suspending-call classifier in this file — the narrow hoists, the ANF hoist,
    the split-point scan, the CFG walk — asks `isinstance(e, FunctionCall)`, so
    a labeled call was invisible to ALL of them: `let a = compute(ok: true)` in
    a task body was never driven, and once the transform replaced `compute`
    with its frame the leftover struct-init spelling had nothing left to
    resolve against — ``undefined struct `compute` `` at a line the user wrote
    a call on (DF-190b). Canonicalizing here rather than teaching each
    classifier a second spelling is the same trade the yield rewrite above
    makes, and it runs FIRST so even the spawn rewrite below reads a uniform
    call shape out of `group.spawn(worker(n: 1))`.
    """
    return _rewrite_nodes(node, _labeled_call_rule)


def _labeled_call_rule(node):
    if isinstance(node, StructInit):
        as_call = getattr(node, 'as_function_call', None)
        if as_call is not None:
            # The reinterpretation is checked THROUGH the struct-init node, so
            # the resolved type landed there and not on the call it delegated
            # to. Frame-local typing and the driven-call classification both
            # read it off the value expression, so carry it over.
            if getattr(as_call, 'resolved_type', None) is None:
                as_call.resolved_type = getattr(node, 'resolved_type', None)
            return as_call
    return node


def _spawn_site_rule(node):
    """Rewrite `group.spawn(f(args))` -> `__spawn_f(&group, args...)`. The site
    was stamped with `spawn_root` by the typechecker.

    design 222 unit 2: the group crosses as a REFERENCE. This one site was 158 of
    the 166 files unit 0 measured under E2 — every program that spawns a task got
    `(&group) as UnsafeConstPointer<TaskGroup>` spliced into the body it wrote,
    and then owed an `unsafe` declaration for a pointer nobody typed. `&group` is
    what the author would have written; `__spawn_<f>` takes it and does the
    crossing in its own `unsafe`-declared body."""
    if (isinstance(node, MethodCall) and node.method_name == "spawn"
            and getattr(node, 'spawn_root', None)):
        root = node.spawn_root
        group = node.object
        inner = node.arguments[0].value  # the f(args) call
        group_ptr = ReferenceExpr(expr=group, mutable=False,
                                  in_argument_position=True)
        call = FunctionCall(
            name=f"__spawn_{root}",
            arguments=([Argument(name=None, value=group_ptr)]
                       + [_ref_arg_to_ptr(a) for a in inner.arguments]),
            line=node.line, column=node.column)
        # Carry the handle type so a suspending spawner can type the frame-resident
        # `let h = ...` binding (conservative-by-scope liveness reads it).
        call.resolved_type = getattr(node, 'resolved_type', None)
        return call
    return node


def _rewrite_spawn_sites(node):
    """Rewrite every `group.spawn(f(args))` under `node` (see `_spawn_site_rule`)."""
    return _rewrite_nodes(node, _spawn_site_rule)


# --------------------------------------------------------------------------- #
# drive-site rewriting
# --------------------------------------------------------------------------- #

def _ref_arg_to_ptr(arg):
    """design 88 (D6): a reference argument `&x` / `&var x` at a drive or spawn
    site travels to the driver/helper AS A REFERENCE — unchanged, design 222
    unit 2.

    It used to be cast to a raw pointer HERE, in the caller's own body, which is
    census row C of unit 0's inventory: the third construction that made a plain
    `func main()` name an `UnsafePointer` its author never wrote. The cast now
    lives in the generated declaration (`_frame_param_arg`), which says `unsafe`
    and is held to it. Kept as a named identity so the two rewrite sites keep
    reading as one decision, and so this docstring has somewhere to live."""
    return arg


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
                    getattr(inner, 'static_receiver', None), inner.method_name,
                    getattr(inner, 'resolved_symbol', None))
                node.arguments = [_ref_arg_to_ptr(a) for a in inner.arguments]
                return node
            recv_type = getattr(inner.object, 'resolved_type', None)
            struct_name = getattr(recv_type, 'struct_name', None)
            # design 222 unit 2: the receiver is passed as an ORDINARY REFERENCE.
            # This site is 10 of unit 0's 166 E2 files — `(&c) as
            # UnsafeConstPointer<C>` spliced into a body whose author wrote no
            # pointer — and the reference is the spelling that says the same
            # thing in a language the author already writes. The driver
            # (`_make_driver`) does the crossing, in a declaration that carries
            # the `unsafe` marker for it.
            recv_ptr = ReferenceExpr(expr=inner.object, mutable=False,
                                     in_argument_position=True)
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
        # A drive site is rewritten IN PLACE (the `FunctionCall` keeps its
        # identity and swaps its name and arguments), so nothing needs writing
        # back — which is what lets this share `_child_nodes` with the read-only
        # walks and pick up their tuple reach (DF-187b).
        for c in _child_nodes(node):
            _rewrite_drive_sites(c, roots)
    return node


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
        for c in _child_nodes(node):
            yield from _iter_method_calls(c)


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
        for c in _child_nodes(node):
            yield from _iter_function_calls(c)


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


def _called_function_names(decl, out):
    """Every free-function name `decl`'s body CALLS, added to `out`."""
    body = getattr(decl, 'body', None)
    if body is None:
        return out
    seen = set()
    stack = [body]
    while stack:
        node = stack.pop()
        if not isinstance(node, ASTNode) or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, FunctionCall):
            out.add(node.name)
        stack.extend(_all_child_nodes(node))
    return out


def _names_a_consumed_call(decl, consumed):
    """Does `decl`'s body CALL any of `consumed` by name?"""
    return bool(_called_function_names(decl, set()) & consumed)


def _consume_method_templates_naming(program, consumed, required_by_conformance):
    """The METHOD half of consumption symmetry (DF-218e's sweep row).

    A GENERIC method template survives its extension for the same reason a
    generic free-function template survives `program.functions` — the transform
    works on the concrete instantiations — and its body names the consumed
    callee just as loudly. The post-transform re-check walks extensions too, so
    the error is identical and arrives even when the method is never driven.

    It leaves through the ONE strip funnel, so a method an extension's own
    conformance requires is REFUSED here exactly as design 223 unit 2 refuses
    it (removing it would make the extension stop implementing its trait —
    DF-218k). Such a method keeps the old diagnostic; it is the residue this
    cannot reach.

    Returns the names consumed, so the caller's fixpoint can keep going."""
    gone = []
    for ext in getattr(program, 'extensions', []) or []:
        for m in list(getattr(ext, 'methods', []) or []):
            if not getattr(m, 'type_params', None):
                continue
            if not _names_a_consumed_call(m, consumed):
                continue
            if _strip_driven_method(ext, m, required_by_conformance):
                name = getattr(m, 'name', None)
                if name:
                    gone.append(name)
    return gone


def _consume_templates_naming_removed(program, removed, readded,
                                      required_by_conformance=frozenset(),
                                      extra_decls=()):
    """CONSUMPTION SYMMETRY (design 218b section 4, ruling 5 — DF-218e).

    A suspending callee is CONSUMED by the transform: it becomes a frame plus a
    driver and its plain body leaves `program.functions`. A NON-generic caller is
    consumed for the same reason, so nothing is left naming it. A GENERIC caller
    is not — `_promote_nested_generic_calls` splices the CONCRETE instantiations
    beside the un-transformed TEMPLATE, and the template's body still calls the
    consumed callee. The post-transform re-check then typechecks that template
    and reports ``undefined function `mk` `` at the author's own line, plus an
    undefined-variable cascade for the binding it feeds.

    So the template is consumed too, and the rule is the non-generic one stated
    generally: a body the transform replaced with a frame is removed, and so is a
    template every instantiation of which it would have replaced. Sound because
    every instantiation of such a template is UNCONDITIONALLY suspending (the
    callee it names is concrete and suspending, so effect inference suspends
    every instantiation), every driven use was already promoted to a concrete
    function before the transform ran, and no sync instantiation can therefore
    exist for codegen's late monomorphization to ask for. A template that
    suspends only CONDITIONALLY — through a type-parameter method — names no
    consumed callee and is untouched, so its sync instantiations stay reachable.

    Runs to a FIXPOINT: consuming one template can leave a second one naming it
    (a generic root whose nested callee is itself generic).

    `readded` is the set of names the transform puts BACK under their own name —
    a suspending `main` becomes its own entry executor — which are therefore not
    consumed at all."""
    consumed = set(removed) - set(readded)
    if not consumed:
        return
    templates = {f.name: f for f in program.functions
                 if getattr(f, 'type_params', None) and f.name not in removed}
    changed = True
    while changed:
        changed = False
        live = _names_the_survivors_call(program, removed, extra_decls)
        for name, decl in list(templates.items()):
            if name in live:
                # SOMETHING STILL CALLS IT, so consuming it would trade a
                # re-check error for a codegen one. The shape that reaches
                # here is a nested generic call the promotion DECLINED — a
                # template that suspends unconditionally without calling a
                # type-parameter method has no instantiation effect node, so
                # `_promote_nested_generic_calls` leaves the call naming the
                # template and codegen's late monomorphization is what serves
                # it. That is a known limit (drive such a generic directly),
                # and this rule does not get to make it worse.
                continue
            if _names_a_consumed_call(decl, consumed):
                removed.add(name)
                consumed.add(name)
                del templates[name]
                changed = True
        for name in _consume_method_templates_naming(
                program, consumed, required_by_conformance):
            if name not in consumed:
                consumed.add(name)
                changed = True


def _names_the_survivors_call(program, removed, extra_decls):
    """Every function name the program will still CALL after the splice — the
    surviving free functions, every extension method, and the declarations the
    transform is about to add (the frames and drivers, which is where a
    promoted call site ends up)."""
    live = set()
    for f in program.functions:
        if f.name not in removed:
            _called_function_names(f, live)
    for decl in extra_decls:
        _called_function_names(decl, live)
        for m in getattr(decl, 'methods', []) or []:
            _called_function_names(m, live)
    for ext in getattr(program, 'extensions', []) or []:
        for m in getattr(ext, 'methods', []) or []:
            _called_function_names(m, live)
    return live


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
            for inner in control_blocks(s):
                scan_block(inner, out)

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


def _conformance_required_names(all_traits):
    """{trait name -> the method names it declares}, read off the AST.

    Off the AST rather than through `get_trait_info` because the namespace is
    reset by the time the transform runs, and a trait declaration is a plain
    list of signatures — nothing here needs resolution. Every declared name
    counts, DEFAULT-BODIED ones included: a conformance that OVERRIDES a
    defaulted requirement and then has its override removed silently falls back
    to the default, which is a wrong answer rather than a diagnostic.
    """
    out = {}
    for t in all_traits:
        names = out.setdefault(_type_identity_of_trait(t), set())
        names.update(m.name for m in (getattr(t, 'methods', None) or []))
        # `t.name` too: an extension's `conformances` hold the name as WRITTEN,
        # and design 144's identity is a separate string.
        out.setdefault(t.name, set()).update(names)
    return out


def _type_identity_of_trait(t):
    return getattr(t, 'type_identity', "") or t.name


def _strip_driven_method(ext, mast, required_by_conformance):
    """THE one place a transformed method leaves its extension (design 223 M3).

    A driven or embedded method's body is REWRITTEN IN PLACE by its frame
    builder — hoisted, ANF-normalized, and finally replaced by a resume state
    machine — so the method the extension still holds is not the method the
    author wrote, and it has to go. Except that removing it can break the
    extension's own declaration: the program is re-typechecked after the
    transform, and an `extension Person: Greeter` with no `greet` left in it
    does not implement `Greeter`. That is DF-218k, reported at the extension,
    about a method plainly written there.

    So the strip REFUSES to remove a method the extension's conformances
    require. The caller pairs that refusal with the other half — building the
    frame from a COPY, which is exactly what an IMPORTED method has always
    done — so the extension keeps the method the author wrote and the frame
    gets its own AST to destroy. Entry-module and cross-module converge on one
    answer: the original method stays, as dead code its call sites no longer
    reach.

    Returns True if the method was removed.
    """
    if _method_is_conformance_required(ext, mast, required_by_conformance):
        return False
    ext.methods = [m for m in ext.methods if m is not mast]
    return True


def _method_is_conformance_required(ext, mast, required_by_conformance):
    """Does one of `ext`'s declared trait conformances name `mast`?"""
    name = getattr(mast, 'name', None)
    if name is None:
        return False
    for tname in (getattr(ext, 'conformances', None) or []):
        if name in required_by_conformance.get(tname, ()):
            return True
    return False


def _promote_nested_generic_methods(program, funcs_by_name, seed_names, all_exts,
                                    susp_methods, really_susp_methods,
                                    typechecker):
    """design 223 unit 1: give the EMBEDDED position the instantiation the DRIVE
    position already gets.

    `__saw_drive(b.describe())` on a `Box2<String>` works because the
    typechecker monomorphizes the method for the concrete receiver AT THE DRIVE
    SITE (`_drive_generic_struct_method`) and hands the transform a
    per-instantiation clone plus the concrete receiver type. The same call
    reached from a body that is already a frame had no such site, so there was
    no clone, no frame key, and — before this brief — no diagnostic either: the
    call fell out of the classifier and lowered as a plain sync call (DF-218m).
    A method-level generic on a concrete struct had the mirror-image hole, and
    failed louder (DF-223a's raw `KeyError`), because its RECEIVER was nameable
    and only its method was not.

    So this walks every body a driven root can reach and, for each suspending
    method call whose frame needs an instantiation to be named, builds that
    instantiation and STAMPS the resulting frame key on the call. It is the
    method twin of `_promote_nested_generic_calls` (design 74 shape 3) and runs
    beside it, before any body is lowered.

    Returns {frame_key: (owner, clone, extension, concrete receiver SawType)}
    for the GENERIC-STRUCT clones, which live nowhere in the AST — they are not
    spliceable onto a plain extension, since their `self` is `Box2<String>` — so
    the caller registers them with the method tables itself. A method-level
    generic's clone IS spliced onto its own extension by `_build_method_mono`,
    exactly as the drive path splices it, and needs nothing here.

    What it does NOT do is decide whether the instantiation suspends: that
    answer comes from `susp_methods`, which is keyed by the TEMPLATE. A method
    whose template suspends is treated as suspending at every instantiation —
    over-approximating in the safe direction, and the same answer both rejectors
    have always used.
    """
    from codegen.mangle import mangle_named
    out = {}
    pristine_gs = getattr(typechecker, '_pristine_generic_struct_methods', None) or {}
    pristine_m = getattr(typechecker, '_pristine_generic_methods', None) or {}
    if not pristine_gs and not pristine_m:
        return out
    # Resolve + register under the entry module's symbol scope: the namespace was
    # reset after `check_module` returned, exactly as for the free-function twin.
    entry_ns = getattr(typechecker, "_entry_module_ns", None)
    saved_ns = getattr(typechecker, "namespace", None)
    if entry_ns is not None:
        typechecker.namespace = entry_ns

    methods_by_owner = {}
    for ext in all_exts:
        sname = getattr(ext, 'struct_name', None)
        for m in ext.methods:
            methods_by_owner.setdefault((sname, m.name), (m, ext))

    def resolved_args_of(type_args):
        out_args = []
        for a in type_args or []:
            try:
                out_args.append(typechecker._resolve_type(a))
            except Exception:
                out_args.append(a)
        return out_args

    def promote_generic_struct(mc, owner, recv_args):
        entry = pristine_gs.get((owner, mc.method_name))
        if entry is None:
            return None
        pristine, ext = entry
        method_tps = getattr(pristine, 'type_params', None) or []
        method_args = resolved_args_of(mc.type_args) if method_tps else []
        if len(method_args) != len(method_tps):
            return None
        struct_args = list(recv_args)
        mono_name = mangle_named(mc.method_name, struct_args + method_args)
        concrete_recv = SawType(TypeKind.STRUCT, struct_name=owner,
                                type_args=struct_args)
        typechecker._effect_queue_generic_struct_method_mono(
            owner, mc.method_name, struct_args, method_args, mono_name,
            concrete_recv)
        typechecker._build_generic_struct_method_mono(
            owner, mc.method_name, struct_args, method_args, mono_name)
        recv_type, clone = typechecker._driven_generic_struct_methods.get(
            (owner, mono_name), (None, None))
        if clone is None:
            return None
        key = _method_frame_key(owner, mono_name,
                                getattr(clone, 'mangled_symbol', None))
        out[key] = (owner, clone, ext, recv_type or concrete_recv)
        mc.coro_frame_key = key
        return clone

    def promote_generic_method(mc, owner):
        entry = pristine_m.get((owner, mc.method_name))
        if entry is None:
            return None
        _pristine, ext = entry
        args = resolved_args_of(mc.type_args)
        mono_name = mangle_named(mc.method_name, args)
        typechecker._build_method_mono(owner, mc.method_name, args, mono_name)
        clone = next((m for m in ext.methods
                      if getattr(m, 'name', None) == mono_name), None)
        if clone is None:
            return None
        mc.coro_frame_key = _method_frame_key(
            owner, mono_name, getattr(clone, 'mangled_symbol', None))
        return clone

    def scan(body, enqueue):
        for mc in _iter_method_calls(body):
            if getattr(mc, 'is_chan_recv', False) or mc.coro_frame_key is not None:
                continue
            if getattr(mc, 'is_static_method_call', False):
                owner = getattr(mc, 'static_receiver', None)
                recv_args = getattr(mc.object, 'type_args', None)
            else:
                rt = getattr(mc.object, 'resolved_type', None)
                owner = ((getattr(rt, 'struct_name', None)
                          or getattr(rt, 'enum_name', None))
                         if rt is not None else None)
                recv_args = getattr(rt, 'type_args', None) if rt is not None else None
            if owner is None or (owner, mc.method_name) not in susp_methods:
                continue
            if recv_args or getattr(mc, 'type_args', None):
                # Only a method that REALLY suspends earns an instantiation.
                # `Vector.map` is in the suspending set by the conservative
                # closure-call rule alone; monomorphizing it would put a frame
                # around a body that suspends nothing.
                if (owner, mc.method_name) not in really_susp_methods:
                    continue
                clone = (promote_generic_struct(mc, owner, recv_args)
                         if recv_args else promote_generic_method(mc, owner))
            else:
                # Nameable as it stands — follow it, so a generic call BELOW an
                # ordinary suspending method is promoted too (the depth the
                # free-function twin reaches only through its own promotions).
                found = methods_by_owner.get((owner, mc.method_name))
                clone = found[0] if found is not None else None
            if clone is not None and getattr(clone, 'body', None) is not None:
                enqueue(clone.body)
        for fc in _iter_function_calls(body):
            callee = funcs_by_name.get(fc.name)
            if callee is not None and getattr(callee, 'body', None) is not None:
                enqueue(callee.body)

    seen_bodies = set()
    work = []

    def enqueue(body):
        if id(body) not in seen_bodies:
            seen_bodies.add(id(body))
            work.append(body)

    for name in seed_names:
        f = funcs_by_name.get(name)
        if f is not None and getattr(f, 'body', None) is not None:
            enqueue(f.body)
    while work:
        scan(work.pop(), enqueue)

    if entry_ns is not None:
        typechecker.namespace = saved_ns
    return out


def _assign_bt_indices(frame_structs, builders):
    """design 158: fix the backtrace table's frame ORDER and patch each frame's
    `bt_desc` literal to its index.

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
    # design 223 unit 2: what the strip may NOT remove. Every trait in the
    # compilation unit, by the two names an extension's `conformances` list can
    # hold — see `_conformance_required_names`.
    _required_by_conformance = _conformance_required_names(
        list(getattr(program, 'traits', None) or [])
        + list(getattr(imported_ast, 'traits', None) or []))
    _imported_exts = ([e for e in getattr(imported_ast, 'extensions', [])
                       if e.node_id not in _entry_ext_ids] if imported_ast is not None else [])
    _all_exts = list(program.extensions) + _imported_exts
    # design 45 item 1: a suspending `main` is auto-wrapped in an entry executor.
    main_suspends = (getattr(typechecker, "_main_suspends", False)
                     and "main" in funcs_by_name)
    if not roots and not method_roots and not spawn_roots and not main_suspends:
        return False

    # DF-190b: canonicalize a FULLY-LABELED call (`f(a: 1)`, a `StructInit` by
    # parse) back into the `FunctionCall` the typechecker already resolved it
    # to, before anything looks at a body. Every classifier below tests for a
    # `FunctionCall`, so this spelling was invisible to all of them — see
    # `_rewrite_labeled_calls`. Runs FIRST: the yield and spawn rewrites below
    # read call shapes too.
    for f in program.functions:
        f.body = _rewrite_labeled_calls(f.body)
    for ext in _all_exts:
        for m in ext.methods:
            if getattr(m, 'body', None) is not None:
                m.body = _rewrite_labeled_calls(m.body)

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
    # design 223: the same census, asked design 206's SHARPER question — does
    # this method REALLY suspend (reach a cooperative primitive), or does it only
    # "suspend" by the conservative rule that a call through a non-`sync`
    # function value might? The two sets differ on `Vector.map` and friends, and
    # the difference decides whether an un-nameable call site is REFUSED or left
    # exactly as it was: refusing on a conservative answer would reject a
    # perfectly ordinary `v.map({ ... })`.
    from typechecker.effects import really_suspending as _really_suspending
    from type_identity import std_leaf as _std_leaf
    _really = _really_suspending(_nodes_for_methods)
    really_suspending_methods = set()
    # DF-206d, probed live by design 223's cell K. `_std_suspending_methods` is
    # a set of NAME PAIRS — std bodies belong to a different typechecker, so
    # their effect nodes are absent from this graph and a name is all that
    # crosses. A user `extension TcpStream { func read(&self) -> Int }` that
    # suspends nothing therefore matched std's `("TcpStream", "read")` and was
    # compiled into a coroutine frame: a state machine, a heap frame and a drive
    # loop around a body that returns `self.n + 1`.
    #
    # A method's OWN effect answer outranks a name that agrees with std's. So
    # the pairs a NON-std extension declares and this graph judges are collected
    # here, and a std-seeded pair is dropped when every declaration of it is one
    # of those and says "no". If std ALSO declares the pair (the user extended
    # `Map`, say, and std's own `Map` extension is in the compilation unit) the
    # seed stays — std's answer is the one this graph cannot compute, and
    # keeping it is the conservative direction.
    _answered_locally = {}
    _declared_by_std = set()
    for ext in _all_exts:
        sname = getattr(ext, 'struct_name', None)
        is_std = _std_leaf(getattr(ext, 'source_file', None)) is not None
        for m in ext.methods:
            node = _nodes_for_methods.get(m.node_id)
            if node is not None and node.suspends:
                suspending_methods.add((sname, m.name))
            if _really.get(m.node_id):
                really_suspending_methods.add((sname, m.name))
            if is_std:
                _declared_by_std.add((sname, m.name))
            elif node is not None:
                _answered_locally[(sname, m.name)] = (
                    _answered_locally.get((sname, m.name), False)
                    or node.suspends)
    for _pair, _suspends in _answered_locally.items():
        if not _suspends and _pair not in _declared_by_std:
            suspending_methods.discard(_pair)
    typechecker._suspending_methods_set = suspending_methods
    typechecker._really_suspending_methods_set = really_suspending_methods

    new_structs = []
    new_enums = []
    new_extensions = []
    new_functions = []
    removed = set()

    # The `Poll` signal enum and the `Resumable` trait are declared in
    # std/compiler/frame.saw (design 218 unit 1) — not synthesized here — and
    # sawc.py's `COMPILER_EMITTED_STD_SYMBOLS` carve-out keeps both compiled in
    # even when that module is not imported, so `Resumable` can name `Poll` and
    # frames can conform to it for the erased run queue.
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
    # design 223 unit 1: the METHOD twin of that promotion. A suspending method
    # whose frame identity needs an instantiation — one on a generic struct, or
    # a method-level generic — gets that instantiation built here and its frame
    # key stamped on the call, so `_suspending_method_target` can NAME it. What
    # is not promoted stays UNSUPPORTED and is refused at the call site; what is
    # promoted on a GENERIC STRUCT lives in no extension (its `self` is
    # `Box2<String>`), so it is registered with the method tables below.
    promoted_methods = _promote_nested_generic_methods(
        program, funcs_by_name, seed_names, _all_exts, suspending_methods,
        really_suspending_methods, typechecker)

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
    # design 223: a promoted GENERIC-STRUCT instantiation is a method AST that
    # sits in no `ext.methods` list, so the loop above cannot see it. Register it
    # under the frame key the call sites were stamped with — the same key
    # `_scan_method_callees` will ask for — and remember its concrete receiver
    # type, which is the one thing its frame builder needs that a plain method's
    # does not.
    gsm_recv_types = {}
    for _key, (_owner, _clone, _ext, _recv_type) in promoted_methods.items():
        methods_by_id[_clone.node_id] = (_owner, _clone, _ext)
        methods_by_key[_key] = _clone.node_id
        gsm_recv_types[_key] = _recv_type

    def _scan_method_callees(body):
        """Enqueue every nested suspending METHOD call in `body` (a std method's
        effect node does not exist in the main typechecker, so the edge walk cannot
        reach it — discover it structurally instead). Returns (method-id) work items."""
        out = []
        for mc in _iter_method_calls(body):
            # DF-184a: a STATIC call is discovered here too. In std it is the ONLY
            # way it is discovered — an imported method has no effect node in the
            # entry typechecker — and a static call that went unfound compiled its
            # callee untransformed, so a `blocking` extern inside it lowered to a
            # NAKED call with no offload and no diagnostic.
            #
            # design 223: EMBED only. A frame this walk cannot name is a frame it
            # cannot build; the two rejectors are what report that, anchored at
            # the user's call site, and enqueueing nothing here is what routes it
            # to them instead of to a `KeyError` three phases later.
            #
            # design 95: the frame key resolves the exact overload via its
            # resolved signature, so a call to `write(String)` finds the String
            # frame and not whichever `write` was registered last.
            tgt = _suspending_method_target(mc, typechecker)
            if tgt.kind != 'embed':
                continue
            mid = methods_by_key.get(tgt.frame_key)
            if mid is not None:
                out.append(("method", mid))
        return out

    def _body_has_chan_recv(body):
        """Does `body` contain a cooperative `Channel.receive()` (design 62 G3)?

        The twin of `_scan_method_callees` for the ONE suspending method call
        that embeds no frame — a receive is lowered inline into the calling
        frame, so it is a suspension with nothing to enqueue. Kept separate
        because the two callers want different answers: the closure WALK wants
        frames to build, the structural-suspension SEED wants to know whether
        the body suspends at all.
        """
        for mc in _iter_method_calls(body):
            if getattr(mc, 'is_chan_recv', False):
                return True
        return False

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
    #
    # design 206: `_scan_method_callees` answers "which callee FRAMES does this
    # body embed", and this seed asks "does this body suspend at all" — two
    # questions, and a channel `receive()` answers them differently. It embeds
    # nothing (design 62 G3 lowers it INLINE, so the scan skips it, correctly)
    # and it suspends absolutely (its loop is `try_receive` + `yield_now`). One
    # scan served both, so `acquire(ch)` — a helper whose ONLY suspension is a
    # receive — was left out of the closure, got no frame, and its `receive()`
    # compiled to the library body whose `yield_now` is a NO-OP outside a frame:
    # an infinite spin, DF-203b. Unit 2 made the effect FIXPOINT answer this
    # correctly too; the two routes agree now rather than one covering for the
    # other, which is the point of asking each its own question.
    structurally_susp_fns = set()
    for _fname, _f in funcs_by_name.items():
        if getattr(_f, 'type_params', None):
            continue
        if _scan_method_callees(_f.body) or _body_has_chan_recv(_f.body):
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
            #
            # design 223 (M2, and it lands in the SAME commit as M1): this skip
            # keys on the METHOD/EXTENSION's `type_params` while the call-site
            # classifier keys on the RECEIVER, and the misalignment is why one
            # hole showed four symptoms — an ICE, a silent sync call, a raw
            # `KeyError` and a wrong-shaped diagnostic, depending on which end
            # noticed first. Fixing the call site alone converts the silent
            # cells into `KeyError`s (probed). The aligned rule: skip a TEMPLATE,
            # which is what has no frame of its own; a monomorphized instance is
            # exactly what `_promote_nested_generic_methods` built so that the
            # call site COULD name it, so it is never skipped here.
            if (not getattr(mast, 'is_mono_instance', False)
                    and (getattr(mast, 'type_params', None)
                         or getattr(ext, 'type_params', None))):
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
    # design 221 unit B3: a suspending `main` that ALSO spawns rides the ambient
    # executor, which erases its frame into a `Box<any Resumable>` — so a
    # non-Void `main` needs the cell layout to get its result back out. Decided
    # here, where the builder is made, because the layout is what changes.
    _exit_status_main = (main_suspends and bool(spawn_roots)
                         and "main" in closure
                         and (funcs_by_name["main"].return_type is not None)
                         and funcs_by_name["main"].return_type.kind != TypeKind.VOID)
    fbs = {n: _FrameBuilder(funcs_by_name[n], tc=typechecker,
                            is_spawn_root=(n in spawn_roots
                                           and n not in dual_role_spawn_roots),
                            exit_status_root=(n == "main" and _exit_status_main))
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
        # design 223 unit 2: the copy is owed for a SECOND reason, and the two
        # are one rule. `_strip_driven_method` refuses to remove a method the
        # extension's conformances require, so that method stays in the AST —
        # and a frame built from it in place would leave a half-lowered state
        # machine where the author's `greet` used to be.
        if ((ext.node_id not in _entry_ext_ids
             or _method_is_conformance_required(ext, mast,
                                                _required_by_conformance))
                and fbkey not in gsm_recv_types):
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
        # design 223: a promoted generic-struct instantiation carries the
        # CONCRETE receiver type its frame's `__recv` must point at
        # (`Box2<String>`, not `Box2`) — the same thing the drive-root path
        # reads out of the `gsm` table below. Everything else about the frame is
        # an ordinary method's.
        fbs[fbkey] = _FrameBuilder(mast, struct_name=sname, tc=typechecker,
                                   recv_saw_type=gsm_recv_types.get(fbkey))
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
        if _method_is_conformance_required(ext, method_ast,
                                           _required_by_conformance):
            # design 223 unit 2: the DRIVE-ROOT face of the same rule. The frame
            # builder rewrites the body it is handed, and this one has to stay
            # in its extension for the conformance to keep holding — so it gets
            # its own copy, exactly as an imported method does.
            import copy as _copy
            method_ast = _copy.deepcopy(method_ast)
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


    # Strip driven methods from their extensions (replaced by frame + resume) —
    # through the ONE funnel that knows when a strip would break the extension's
    # own declaration (design 223 unit 2 / DF-218k).
    for ext, method_ast in removed_methods:
        _strip_driven_method(ext, method_ast, _required_by_conformance)

    # design 84/89: an embedded imported method body may reference a module-level
    # `static` private to its own module (`TcpListener.accept` names
    # `INVALID_FD`). The transform splices that method into the ENTRY module,
    # which is then re-typechecked under the entry namespace — where the imported
    # static is NOT visible. Statics are const-initialized, so inline the
    # referenced static's initializer at the reference sites in the synthesized
    # declarations. Only imported statics NOT shadowed by an entry-module static
    # of the same name are inlined, keeping this precise.
    #
    # design 210 unit 5: this reads `imported_ast.statics`, which is the MERGED
    # AST — every module's, not std's — so the mechanism was already uniform and
    # only its comment said "std". What was std-only is gone from the checker
    # (`_decl_is_foreign_splice`). Note the scope: this rewrites the SYNTHESIZED
    # declarations, so a const-position reference the structural walk cannot
    # reach (`ArrayLiteral.repeat_count`) is covered by the preserve marking
    # instead — see `_all_child_nodes` and conformance row K25.
    if imported_ast is not None:
        entry_static_names = {s.name for s in program.statics}
        const_statics = {s.name: s.initializer
                         for s in getattr(imported_ast, 'statics', [])
                         if s.initializer is not None
                         and s.name not in entry_static_names}
        if const_statics:
            for decl in list(new_extensions) + list(new_functions) + list(new_structs):
                _inline_static_refs(decl, const_statics)

    # design 210 unit 3: the splice boundary. Reduce the preserved marks to the
    # subtrees that can actually answer for themselves, BEFORE the post-transform
    # pass is told it may skip them.
    _close_embed_marks(list(new_extensions) + list(new_functions))

    # design 158: every frame exists now, so the table order — and each frame's
    # `bt_desc` answer — can be fixed.
    _assign_bt_indices(new_structs, all_builders)

    # DF-218e: consumption symmetry — a generic TEMPLATE naming a consumed
    # callee is consumed with it.
    _consume_templates_naming_removed(
        program, removed, {f.name for f in new_functions},
        _required_by_conformance,
        extra_decls=list(new_functions) + list(new_extensions))

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True

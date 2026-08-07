"""
Expression checking methods for the Saw type checker.

This module provides mixin methods for checking all expression types including
literals, operators, function calls, method calls, closures, and more.

Usage:
    class TypeChecker(ExpressionsMixin, ...):
        pass
"""

from typing import Optional, Dict, List
from types import SimpleNamespace as _SandboxNode
from ast_nodes import (
    Expression, IntLiteral, FloatLiteral, BoolLiteral, StringLiteral,
    StringInterpolation, FormatPlaceholder,
    Identifier, BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr,
    FunctionCall, IfExpr, IfLetExpr, TupleLiteral, TupleIndex,
    ArrayLiteral, MapLiteral, SetLiteral, ArrayIndex, MemberAccess, StructInit, NoneLiteral,
    ForceUnwrap, NilCoalesce, OptionalChain, BindOptional, OptionalEvalExpr,
    OptionalChainAssign, MethodCall, SelfExpr,
    SourceLocationLiteral,
    EnumInit, MatchExpr, WhileExpr, RangeExpr, ForLoop, ClosureExpr,
    TryExpr, TryCatchExpr,
    Block, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    CompoundAssignStatement, GuardLetStatement, BreakStatement,
    SawType, TypeKind,
    ResultOkWrap, ResultErrWrap, OptionalWrap,
    Pattern, WildcardPattern, BindingPattern, LiteralPattern,
    RangePattern, TuplePattern, EnumPattern,
    Argument, ASTNode, MatchArm, structural_fields,
)
from errors import ErrorKind
from const_eval import const_eval, ConstEvalError
from namespace import Visibility, EnumSymbol

# Sentinel: a length that IS a compile-time constant but whose value belongs to
# an instantiation rather than to this (abstract) pass — `[v; N]` inside a
# generic body (design 148). Distinct from None, which means "not constant".
_ABSTRACT_COUNT = object()


class ExpressionsMixin:
    """Mixin providing expression checking methods for TypeChecker."""

    def _check_expression(self, expr: Expression) -> Optional[SawType]:
        """Check an expression and return its type.

        This is the single chokepoint through which every expression is
        checked. It stamps the computed type onto ``expr.resolved_type`` so
        codegen can consume it (see ``CodeGenerator._expr_type``) instead of
        re-inferring types with a weaker, divergent engine.

        Ordering rule -- "later contextual annotation wins": a few callers
        annotate *contextually* after this returns (e.g.
        ``_propagate_optional_type`` pushes an expected optional type down into
        ``None`` literals). Those run after the child's ``_check_expression``
        has already returned and stamped here, so their more-specific
        annotation overwrites the generic one stamped below. Never re-check a
        node after contextually annotating it, or the generic stamp would win.
        """
        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            return None
        result = visitor(expr)
        if result is not None:
            expr.resolved_type = result
            # design 130 rule 3: an expression whose VALUE has an unsafe type is
            # the function naming/binding one. A closure literal is skipped —
            # `_check_closure` decides which domain its body's contact belongs to
            # (design 136), and its own function type names the unsafe parameter
            # by construction, which the slot it is passed to already declares.
            if not isinstance(expr, ClosureExpr):
                self._note_unsafe_contact(
                    result, expr, "its body names a value of unsafe type")
            # design 149 unit d: on a target with no atomic instruction, naming a
            # `SpinLock` is refused. Guarded on the target so the ordinary case
            # is one boolean test.
            if not self._atomics_native:
                self._check_spinlock_target(result, expr)
        return result

    # ===== Expression Visitor Methods =====

    # Design 53: a suffixed integer literal IS its fixed-width type.
    _SUFFIX_TYPE_KINDS = {
        'i8': TypeKind.INT8, 'i16': TypeKind.INT16,
        'i32': TypeKind.INT32, 'i64': TypeKind.INT64,
        'u8': TypeKind.UINT8, 'u16': TypeKind.UINT16,
        'u32': TypeKind.UINT32, 'u64': TypeKind.UINT64,
    }

    # Design 53: type names carrying `.max`/`.min` integer limits → their kind.
    _INT_LIMIT_TYPE_KINDS = {
        'Int': TypeKind.INT, 'UInt': TypeKind.UINT,
        'Int8': TypeKind.INT8, 'Int16': TypeKind.INT16,
        'Int32': TypeKind.INT32, 'Int64': TypeKind.INT64,
        'UInt8': TypeKind.UINT8, 'UInt16': TypeKind.UINT16,
        'UInt32': TypeKind.UINT32, 'UInt64': TypeKind.UINT64,
    }

    def _check_alias_construction(self, expr, alias_info) -> Optional[SawType]:
        """`UserId(42)` — build a value of a distinct `type` alias (design 63).

        The flow rule is deliberately one-way: an alias value projects toward
        its underlying freely (implicitly, or with `as`), and nothing flows
        back on its own. This is the sanctioned way back, and that it is a
        CONSTRUCTION rather than a cast is the whole point — `42 as UserId` is
        an error precisely because widening authority over a value should read
        as making one, at the site that makes it.

        The argument is checked against the underlying type with that type
        pushed down as the expectation, so a bare literal adopts it and is
        range-checked there (design 87). That is what makes an alias over a
        FIXED-WIDTH underlying constructible at all: `type Handle = UInt` had
        no spelling before this, since an annotated `let` only accepts an
        underlying that is one of the four primitive kinds.

        Representationally this is a no-op — an alias IS its underlying — so
        codegen compiles the operand and nothing else.
        """
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{expr.name}` is a type alias and is constructed from "
                f"exactly one value, but {len(expr.arguments)} were given",
                expr.line, expr.column,
                hint=f"write `{expr.name}(<{self._resolve_type_alias(SawType(TypeKind.STRUCT, struct_name=expr.name))}>)`"
            )
            return None
        arg = expr.arguments[0]
        if arg.name:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}` is a type alias and takes one unlabeled value, "
                f"but the argument is labeled `{arg.name}`",
                arg.value.line, arg.value.column,
                hint="a type alias has no fields to name — drop the label"
            )
            return None

        alias_type = SawType(TypeKind.STRUCT, struct_name=expr.name)
        underlying = self._resolve_type_alias(alias_type)
        self._apply_literal_expected_type(arg.value, underlying)
        arg_type = self._check_expression(arg.value)
        if arg_type is None:
            return None
        # The value must be one the underlying accepts. `allow_literal_to_distinct`
        # is NOT passed: the operand is being converted to the underlying here,
        # not to another alias, so the ordinary rule is the right one.
        if not self._types_compatible(arg_type, underlying):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}` is a type alias for `{underlying}` and cannot "
                f"be built from `{arg_type}`",
                arg.value.line, arg.value.column
            )
            return None
        expr.alias_construction = expr.name
        return alias_type

    def _stamp_enum_raw_value(self, expr, enum_info) -> None:
        """Record a raw-backed enum case's tag value on the access node.

        A case of an enum that DECLARED a backing denotes a fixed number — that
        is what design 145 unit B2 means by pinning the values, and it is why
        `e as UInt8` is total. Recording it here is what lets the constant
        evaluator fold `SysOp.Shutdown as UInt`, so a `static_assert` can pin a
        wire table against the enum that defines it rather than against a
        transcribed copy of its numbers.

        An UNBACKED enum stamps nothing: its ordinals are the compiler's
        business and reordering its cases must stay a free edit, so its cases
        are deliberately not constants anything may read.
        """
        raw_values = getattr(enum_info, 'raw_values', None)
        if raw_values:
            value = raw_values.get(expr.member)
            if value is not None:
                expr.enum_raw_value = value

    def visit_IntLiteral(self, expr: IntLiteral) -> Optional[SawType]:
        suffix = getattr(expr, 'suffix', None)
        if suffix is not None:
            return SawType(self._SUFFIX_TYPE_KINDS[suffix])
        # Design 87: a bare integer literal that flows into a FIXED-WIDTH slot
        # adopts that type. The expectation (and the range check) is pushed down
        # by the central `_apply_literal_expected_type` propagation
        # (let/param/field/return/compound-assign/collection/tuple/if-match-arm),
        # so this ONE site types the literal uniformly at every position. No
        # fixed-width expectation ⇒ platform `Int` (the load-bearing invariant:
        # `let x = 5` and `Int`/`Int` arithmetic are unchanged).
        expected = getattr(expr, 'expected_type', None)
        if expected is not None:
            rt = self._resolve_type(expected)
            if rt is not None and rt.kind in self._FIXED_INT_RANGES:
                return SawType(rt.kind)
        return SawType(TypeKind.INT)

    def visit_FloatLiteral(self, expr: FloatLiteral) -> Optional[SawType]:
        return SawType(TypeKind.FLOAT)

    def visit_BoolLiteral(self, expr: BoolLiteral) -> Optional[SawType]:
        return SawType(TypeKind.BOOL)

    def visit_StringLiteral(self, expr: StringLiteral) -> Optional[SawType]:
        return SawType(TypeKind.STRING)

    def visit_SourceLocationLiteral(self, expr: SourceLocationLiteral) -> Optional[SawType]:
        """Resolve a `#file` / `#line` / `#function` literal at its DEFINITION
        site (design 98). Filled exactly ONCE and frozen — a second visit (the
        post-coroutine-transform re-check, where `current_function`/`current_
        method` may be a synthesized frame method) must NOT re-resolve, so
        `#line`/`#function` inside a suspending body report the ORIGINAL source,
        not the transformed frame's line/name."""
        import os
        if expr.resolved_kind is None:
            if expr.kind == 'line':
                expr.resolved_kind = 'int'
                expr.resolved_int = getattr(expr, 'line', 0) or 0
            elif expr.kind == 'file':
                expr.resolved_kind = 'string'
                expr.resolved_str = self._source_location_file(expr)
            else:  # 'function'
                expr.resolved_kind = 'string'
                expr.resolved_str = self._source_location_function()
        return SawType(TypeKind.INT if expr.resolved_kind == 'int'
                       else TypeKind.STRING)

    def _source_location_file(self, expr: SourceLocationLiteral) -> str:
        """The source BASENAME for `#file` — matches the design-69 panic prefix
        (`os.path.basename` of the file the token appears in). Falls back to the
        enclosing declaration's file, then the entry file."""
        import os
        src = getattr(expr, 'source_file', None) or self._get_current_source_file()
        if not src:
            src = getattr(self, '_di_source_path', None) or \
                getattr(getattr(self, 'reporter', None), 'source_path', None)
        return os.path.basename(src) if src else "<unknown>.saw"

    def _source_location_function(self) -> str:
        """The bare enclosing function/method name for `#function` (design 98):
        `method.name` (e.g. `mag`, `init`) with NO struct qualifier, or the free
        function name (`main`); module scope -> `<module>`."""
        if self.current_method is not None:
            return getattr(self.current_method, 'name', None) or "<module>"
        if self.current_function is not None:
            return getattr(self.current_function, 'name', None) or "<module>"
        return "<module>"

    # The types `print` and string interpolation render without a `Printable`
    # conformance. Everything else has to have one; design 132 unit D routes both
    # sites through `_check_renderable_operand` so they agree.
    _RENDERABLE_BUILTIN_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
    })

    # The platform-width integer pair, for the overload-ranking signedness
    # tiebreak below.
    _PLATFORM_INT_KINDS = frozenset({TypeKind.INT, TypeKind.UINT})

    def _check_renderable_operand(self, expr_type, sub_expr, verb: str,
                                  where: str = "") -> bool:
        """Whether a value of `expr_type` can be rendered, reporting if not.

        `print(o)` on an `Int?` used to reach codegen and die there with
        `internal compiler error: Cannot print type: {i1, i64}`, while
        interpolating the same value already gave the clean not-`Printable`
        error (DF-128d / DF-129a, found independently by two agents). Both
        callers now ask the same question, so `print(v.get(0))` — the easy way
        to meet this by accident, since `Vector.get` returns `T?` — is a
        diagnostic rather than a crash.
        """
        if expr_type.kind in self._RENDERABLE_BUILTIN_KINDS:
            return True
        # A `T: Printable` bound satisfies this inside a generic body.
        if self._bound_satisfied(expr_type, "Printable"):
            return True
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"{verb} value of type `{expr_type}`{where}: it is not `Printable`",
            getattr(sub_expr, 'line', 0), getattr(sub_expr, 'column', 0),
            hint=f"conform it with `extension {self._type_display_name(expr_type)}: Printable {{ ... }}`")
        return False

    def visit_StringInterpolation(self, expr: StringInterpolation) -> Optional[SawType]:
        """Type check string interpolation expressions (design 56).

        Builtin types (integers, Float, Bool, String) keep the existing fast
        lowering. Any other type must be Printable: it is streamed into the
        interpolation builder via its `format`/`to_string`. A non-Printable type
        is a clean error naming the type and the trait."""
        for sub_expr in expr.expressions:
            # design 137: an empty `{}` is a FORMAT PLACEHOLDER, filled from a
            # call's argument list. Reaching here means the string is not the
            # format argument of one, so there is no value to put in it.
            if isinstance(sub_expr, FormatPlaceholder):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`{}` is a format placeholder and needs an argument to fill it",
                    sub_expr.line, sub_expr.column,
                    hint="pass a value for it — `print(\"x = {}\", x)` — or name "
                         "the value in the braces (`\"x = {x}\"`); write `\\{\\}` "
                         "for literal braces")
                return None
            expr_type = self._check_expression(sub_expr)
            if expr_type is None:
                return None
            if not self._check_renderable_operand(
                    expr_type, sub_expr, "cannot interpolate", " in a string"):
                return None
        # design 135: interpolation builds a fresh heap String out of pieces the
        # source never asked to store. The ban is uniform — a `panic`/`assert`
        # message is no exception, because the allocator being out is exactly
        # when a panic has to work.
        if expr.expressions and self._hidden_alloc_gate():
            self._hidden_alloc_error(
                "string interpolation allocates a String",
                expr.line, expr.column,
                hint="pass the values as format arguments instead — "
                     "`print(\"x = {}\", x)`, `panic(\"out of {}\", what)` — or "
                     "assemble the text in a fixed-capacity `StringBuilder`; a "
                     "message with nothing interpolated into it is an interned "
                     "literal and costs nothing")
        return SawType(TypeKind.STRING)

    def _format_placeholder_count(self, fmt_expr):
        """How many `{}` slots a format-string argument has, or None if the
        expression cannot be one.

        A plain `StringLiteral` has none (it is a complete message). A
        `StringInterpolation` may carry placeholders, real `{expr}` pieces, or
        both — the caller decides what to allow. Anything else (a String-typed
        variable, a call result) is not a format string: its placeholders could
        not be counted at compile time, which is the whole point of checking
        arity here rather than at runtime.
        """
        if isinstance(fmt_expr, StringLiteral):
            return 0
        if isinstance(fmt_expr, StringInterpolation):
            return sum(1 for e in fmt_expr.expressions
                       if isinstance(e, FormatPlaceholder))
        return None

    def _check_format_call(self, name: str, expr, value_args,
                           fmt_index: int = 0) -> None:
        """Check a `print`/`panic`/`assert` call that supplies format arguments.

        Design 137. The format string must be a LITERAL so `{}` slots can be
        counted at compile time: a mismatch between slots and arguments is an
        error here, never a runtime surprise, and there are no varargs to
        type-erase — each argument keeps its own type and is rendered through
        its own `Printable.format`. `fmt_index` is 1 for `assert`, whose Bool
        condition comes first.
        """
        fmt_expr = expr.arguments[fmt_index].value
        count = self._format_placeholder_count(fmt_expr)

        if count is None:
            self._check_expression(fmt_expr)
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{name}` with format arguments needs a literal format string",
                fmt_expr.line, fmt_expr.column,
                hint="the `{}` slots are counted at compile time, so the format "
                     "string cannot be a variable")
            for arg in value_args:
                self._check_expression(arg.value)
            return

        # Mixing a real `{expr}` interpolation into a format string would build
        # a heap String for the format string itself, which is exactly what this
        # path exists to avoid — and it reads ambiguously besides.
        if isinstance(fmt_expr, StringInterpolation):
            for piece in fmt_expr.expressions:
                if not isinstance(piece, FormatPlaceholder):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{name}` format string mixes `{{...}}` interpolation "
                        f"with `{{}}` placeholders",
                        piece.line, piece.column,
                        hint="use `{}` for every slot and pass the values as "
                             "arguments; an interpolated format string would "
                             "allocate, which is what this spelling avoids")
                    for arg in value_args:
                        self._check_expression(arg.value)
                    return

        if count != len(value_args):
            slots = "1 placeholder" if count == 1 else f"{count} placeholders"
            given = ("1 argument" if len(value_args) == 1
                     else f"{len(value_args)} arguments")
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{name}` format string has {slots} but {given} "
                f"{'was' if len(value_args) == 1 else 'were'} given",
                expr.line, expr.column,
                hint="every `{}` takes exactly one argument, by position")

        for arg in value_args:
            if arg.name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{name}` format arguments are positional and take no label",
                    arg.value.line, arg.value.column)
            arg_type = self._check_expression(arg.value)
            if arg_type is None:
                continue
            if self.freestanding and arg_type.kind == TypeKind.FLOAT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "Float formatting requires the hosted profile; "
                    "freestanding formatting supports integers, Bool, and String only",
                    arg.value.line, arg.value.column)
                continue
            self._check_renderable_operand(arg_type, arg.value, "cannot format")

    def _type_display_name(self, saw_type: SawType) -> str:
        """A bare type name for diagnostics (struct/enum name, else the type)."""
        if saw_type is None:
            return "T"
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            return saw_type.struct_name
        if saw_type.kind == TypeKind.ENUM and saw_type.enum_name:
            return saw_type.enum_name
        return str(saw_type)

    def visit_Identifier(self, expr: Identifier) -> Optional[SawType]:
        return self._check_identifier(expr)

    def visit_BinaryOp(self, expr: BinaryOp) -> Optional[SawType]:
        return self._check_binary_op(expr)

    def visit_UnaryOp(self, expr: UnaryOp) -> Optional[SawType]:
        return self._check_unary_op(expr)

    def visit_MoveExpr(self, expr: MoveExpr) -> Optional[SawType]:
        return self._check_move_expr(expr)

    def visit_ReferenceExpr(self, expr: ReferenceExpr) -> Optional[SawType]:
        return self._check_reference_expr(expr)

    def visit_CastExpr(self, expr: CastExpr) -> Optional[SawType]:
        return self._check_cast_expr(expr)

    def visit_ResultOkWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted Ok wrap (design 92).

        These wraps are synthesized during the FIRST typecheck, then the
        coroutine transform rewrites bare identifiers inside `expr.value` into
        fresh frame-field `MemberAccess` nodes that carry NO `resolved_type`. The
        pipeline re-typechecks the transformed AST, so this visitor MUST descend
        into `expr.value` to re-annotate it — without it a Result-returning
        suspending method that returns a frame-resident value (`return move buf`,
        `TcpStream(fd: cfd as Int32)`) reaches codegen with an unannotated node
        and ICEs."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'result_type', None)

    def visit_ResultErrWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted Err wrap — see visit_ResultOkWrap."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'result_type', None)

    def visit_OptionalWrap(self, expr) -> Optional[SawType]:
        """Re-check an already-inserted `T -> T?` wrap — see visit_ResultOkWrap.

        The Result wraps got this visitor when the coroutine transform started
        re-checking its own output; the optional wrap needs it for the same
        reason and had simply never been re-checked before. Without it the node
        types as None, which becomes `Void` at the nearest block tail — and a
        window closure whose tail wraps a place read (`{ __p in __p }` against
        `-> T?`) then arrives at the argument check as `(&var T) -> Void`."""
        if expr.value is not None:
            self._check_expression(expr.value)
        return getattr(expr, 'target_type', None)

    def visit_FunctionCall(self, expr: FunctionCall) -> Optional[SawType]:
        return self._check_function_call(expr)

    def visit_IfExpr(self, expr: IfExpr) -> Optional[SawType]:
        return self._check_if_expr(expr)

    def visit_IfLetExpr(self, expr: IfLetExpr) -> Optional[SawType]:
        return self._check_if_let_expr(expr)

    def visit_TupleLiteral(self, expr: TupleLiteral) -> Optional[SawType]:
        return self._check_tuple_literal(expr)

    def visit_TupleIndex(self, expr: TupleIndex) -> Optional[SawType]:
        return self._check_tuple_index(expr)

    def visit_ArrayLiteral(self, expr: ArrayLiteral) -> Optional[SawType]:
        return self._check_array_literal(expr)

    def visit_MapLiteral(self, expr: MapLiteral) -> Optional[SawType]:
        return self._check_map_literal(expr)

    def visit_SetLiteral(self, expr: SetLiteral) -> Optional[SawType]:
        return self._check_set_literal(expr)

    def visit_ArrayIndex(self, expr: ArrayIndex) -> Optional[SawType]:
        return self._check_array_index(expr)

    def visit_MemberAccess(self, expr: MemberAccess) -> Optional[SawType]:
        return self._check_member_access(expr)

    def visit_StructInit(self, expr: StructInit) -> Optional[SawType]:
        return self._check_struct_init(expr)

    def visit_NoneLiteral(self, expr: NoneLiteral) -> Optional[SawType]:
        return self._check_none_literal(expr)

    def visit_ForceUnwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        return self._check_force_unwrap(expr)

    def visit_NilCoalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        return self._check_nil_coalesce(expr)

    def visit_OptionalChain(self, expr: OptionalChain) -> Optional[SawType]:
        return self._check_optional_chain(expr)

    def visit_BindOptional(self, expr: BindOptional) -> Optional[SawType]:
        return self._check_bind_optional(expr)

    def visit_OptionalEvalExpr(self, expr: OptionalEvalExpr) -> Optional[SawType]:
        return self._check_optional_eval(expr)

    def visit_OptionalChainAssign(self, expr: OptionalChainAssign) -> Optional[SawType]:
        return self._check_optional_chain_assign(expr)

    def visit_MethodCall(self, expr: MethodCall) -> Optional[SawType]:
        return self._check_method_call(expr)

    def visit_SelfExpr(self, expr: SelfExpr) -> Optional[SawType]:
        return self._check_self_expr(expr)

    def visit_EnumInit(self, expr: EnumInit) -> Optional[SawType]:
        return self._check_enum_init(expr)

    def visit_MatchExpr(self, expr: MatchExpr) -> Optional[SawType]:
        return self._check_match_expr(expr)

    def visit_WhileExpr(self, expr: WhileExpr) -> Optional[SawType]:
        return self._check_while_expr_as_expression(expr)

    def visit_RangeExpr(self, expr: RangeExpr) -> Optional[SawType]:
        return self._check_range_expr(expr)

    def visit_ForLoop(self, expr: ForLoop) -> Optional[SawType]:
        return self._check_for_loop_as_expression(expr)

    def visit_ClosureExpr(self, expr: ClosureExpr) -> Optional[SawType]:
        return self._check_closure(expr)

    def visit_TryExpr(self, expr: TryExpr) -> Optional[SawType]:
        return self._check_try_expr(expr)

    def visit_TryCatchExpr(self, expr: TryCatchExpr) -> Optional[SawType]:
        return self._check_try_catch_expr(expr)

    def _check_identifier(self, expr: Identifier) -> Optional[SawType]:
        """Check an identifier reference.

        For reference types (&T or &var T), this auto-dereferences and returns
        the inner type T. This provides implicit dereference semantics.
        """
        var_info = self.current_scope.lookup(expr.name)
        if not var_info:
            # A const generic parameter reads as a plain value of its declared
            # type (design 148) — `N` in a `FixedBuf<const N: Int>` body IS an
            # Int, with a different one per instantiation. It shadows nothing
            # and is never assignable, so it is resolved before the static
            # lookup and never enters a scope.
            const_type = self._const_param_types().get(expr.name)
            if const_type is not None:
                expr.const_param_name = expr.name
                return const_type
            # Module-level static (design 41): read like an immutable binding.
            static_sym = self.namespace.get_static(
                expr.name, self._accessor_vis_module())
            if static_sym is not None and self.namespace.is_accessible(expr.name):
                # DF-140f: resolution happens HERE, against this module's own
                # namespace, so this is the only place that knows WHICH
                # same-named private static was meant. Stamp its codegen symbol
                # — codegen works from one merged namespace and could not tell
                # two module-private `PT_LOAD`s apart on its own.
                if static_sym.mangled_name:
                    expr.resolved_static_symbol = static_sym.mangled_name
                # design 149: naming an `unsafe static var` is unsafe contact,
                # whatever its type. Recorded here rather than from the type,
                # because the unsafety is the declaration's, not the type's.
                if getattr(static_sym, 'is_var', False):
                    self._note_unsafe_static_contact(expr.name, expr)
                return static_sym.type
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.name}`",
                expr.line, expr.column
            )
            return None

        # Use-after-move: the binding was moved-from on some path reaching here.
        move_info = self._binding_move_info(var_info)
        if move_info is not None:
            _, move_line, _ = move_info
            self._error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.name}`",
                expr.line, expr.column,
                hint=f"value was moved at line {move_line} and can no longer be used"
            )
            return None

        # Auto-dereference reference types
        if var_info.type.kind == TypeKind.REFERENCE:
            return var_info.type.inner_type

        return var_info.type

    def _check_move_expr(self, expr: MoveExpr) -> Optional[SawType]:
        """Check a move expression.

        Records the source binding as moved-from (design 15). This runs for
        every `move x` regardless of the enclosing transfer site, so call
        arguments, struct-field inits, enum payloads, array/tuple elements and
        returns all mark the move uniformly. A double-move is caught here
        because the second `move` sees the binding already moved-from.
        """
        # Partial move (`move p.x`, `move p.x.y`, `move arr[i]`): forbidden on
        # every struct (design 35). Only whole bindings are movable. Reject with
        # a diagnostic naming the field/element and its base.
        if expr.path is not None:
            # design 131: `move h.s!` is still a partial move — the payload sits
            # inside a field, and retiring it would leave `h` half-owned. The
            # field-safe consuming read is `h.s.take()`.
            hint = ("move the whole value (`move " + expr.variable + "`) or "
                    "restructure so the piece is its own binding")
            if expr.unwrap:
                hint = (f"`move` at an optional projection retires the whole "
                        f"BINDING, which a field cannot do; use "
                        f"`{self._render_lvalue_path(expr.path)}.take()` to move "
                        f"the payload out and leave `None` behind")
            self._error(
                ErrorKind.CANNOT_COPY,
                self._partial_move_message(expr.path),
                expr.line, expr.column,
                hint=hint
            )
            return None

        var_info = self.current_scope.lookup(expr.variable)
        if not var_info:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.variable}`",
                expr.line, expr.column
            )
            return None

        # Use-after-move / double-move: the binding was already moved-from.
        move_info = self._binding_move_info(var_info)
        if move_info is not None:
            _, move_line, _ = move_info
            self._error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.variable}`",
                expr.line, expr.column,
                hint=f"value was already moved at line {move_line} and can no longer be used"
            )
            return None

        # Disallow moving out of references - this would leave the referent invalid
        if var_info.type.kind == TypeKind.REFERENCE:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot move out of reference `{expr.variable}`",
                expr.line, expr.column,
                hint="references cannot have their contents moved out"
            )
            return None

        # Record the move against the binding's identity.
        self._mark_binding_moved(var_info, expr.variable, expr.line, expr.column)

        # design 131: `move o!` transfers the binding and yields the PAYLOAD.
        # The binding is retired whole — no husk, no writeback — so the only
        # extra work here is unwrapping the result type.
        if expr.unwrap:
            if var_info.type.kind != TypeKind.OPTIONAL:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot force unwrap non-optional type `{var_info.type}`",
                    expr.line, expr.column,
                    hint=f"`move {expr.variable}!` is the payload-yielding move; "
                         f"`{expr.variable}` is not an optional, so write "
                         f"`move {expr.variable}`"
                )
                return var_info.type
            return var_info.type.inner_type

        return var_info.type

    def _partial_move_message(self, path: Expression) -> str:
        """Diagnostic for a forbidden partial move, naming the piece and base."""
        if isinstance(path, MemberAccess):
            base = self._render_lvalue_path(path.object)
            return f"cannot move out of field `{path.member}` of `{base}`"
        if isinstance(path, TupleIndex):
            base = self._render_lvalue_path(path.tuple_expr)
            return f"cannot move out of tuple element `{path.index}` of `{base}`"
        if isinstance(path, ArrayIndex):
            base = self._render_lvalue_path(path.array_expr)
            idx = self._render_index(path.index)
            return f"cannot move out of element `[{idx}]` of `{base}`"
        return f"cannot move out of `{self._render_lvalue_path(path)}`"

    def _check_reference_expr(self, expr: ReferenceExpr) -> Optional[SawType]:
        """Check a reference expression: &expr or &var expr.

        References can only be taken to lvalues (variables, fields, array elements).
        For mutable references (&var), the target must be mutable.
        """
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        # A reference is only meaningful as a call argument (design 34, DF-163d):
        # references cannot be stored, returned, or bound to a variable. The
        # parser marks argument-position references (the place transform marks
        # the `&var` it builds out of a `lend`, which is the implicit lend a
        # `borrows` accessor makes); a reference anywhere else is rejected here.
        #
        # The one other blessed position is the operand of a cast to
        # `UnsafePointer<T>`/`UnsafeConstPointer<T>` (DF-163f) — the only
        # address-of the language has, and a crossing into the unsafe tier
        # rather than an escape: what survives the expression is a pointer, and
        # design 130's signature effect fences it from there.
        if not expr.in_argument_position and not expr.to_pointer_cast:
            sigil = "&var" if expr.mutable else "&"
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{sigil}` here is not a call argument, and references in Saw "
                f"are PARAMETERS ONLY — a reference borrows storage for the "
                f"duration of one call and may not escape it (designs 88/106; "
                f"the Law of Exclusivity is statically sound only because every "
                f"live reference belongs to a call still on the stack)",
                expr.line, expr.column,
                hint=f"a reference cannot be stored or bound: pass it straight "
                     f"to a `{sigil}` parameter, or — to hand out storage a "
                     f"value already owns — declare a `borrows` accessor "
                     f"(`... borrows -> T` with `lend`, design 141), which "
                     f"lends the place for a window rather than letting a "
                     f"pointer out"
            )
            # Recover as the reference type the author wrote, so one misplaced
            # `&` yields one message instead of dragging an "undefined variable"
            # cascade behind it.
            return SawType(TypeKind.REFERENCE, inner_type=inner_type,
                           reference_mutable=expr.mutable)

        # References can only be taken to lvalues
        if not self._is_lvalue(expr.expr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "can only take reference to a variable, field, or array element",
                expr.line, expr.column,
                hint="references require an addressable location"
            )
            return None

        # For &var, check that the target is mutable
        if expr.mutable:
            if isinstance(expr.expr, Identifier):
                var_info = self.current_scope.lookup(expr.expr.name)
                # An immutable static rejects `&var STATIC` (design 41; an
                # `&STATIC` shared lend is fine). Statics are not in scope, so a
                # None var_info that names a static is the signal. An
                # `unsafe static var` (design 149) lends `&var` like any mutable
                # binding — naming it already made this function `unsafe`.
                static_sym = (self.namespace.get_static(
                    expr.expr.name, self._accessor_vis_module())
                    if var_info is None else None)
                if static_sym is not None and not getattr(static_sym, 'is_var', False):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot take mutable reference `&var` to static `{expr.expr.name}`: "
                        f"statics are immutable",
                        expr.line, expr.column,
                        hint="pass `&{0}` for a shared read, use an interior-"
                             "synchronized type (`Atomic<Int>`, `SpinLock<T>`), or "
                             "declare it `unsafe static var`".format(expr.expr.name)
                    )
                    return None
                # A `&var T` reference parameter is already a mutable borrow, so
                # re-borrowing it (`&var ref` — forwarding it to another `&var`
                # parameter, e.g. nested `Printable.format(into:)`, design 56) is
                # sound even though the binding itself is not a `var`.
                is_mut_ref_binding = (var_info is not None
                                      and var_info.type is not None
                                      and var_info.type.kind == TypeKind.REFERENCE
                                      and var_info.type.reference_mutable)
                # An IMMUTABLE reference binding (`r: &T`) is a shared borrow;
                # forwarding it as `&var` would silently UPGRADE it (design 106
                # forbids this — `&var` forwarding requires an incoming `&var`).
                # Give a forwarding-specific diagnostic rather than the generic
                # "declare with var" (the referent is not the caller's to re-var).
                is_imm_ref_binding = (var_info is not None
                                      and var_info.type is not None
                                      and var_info.type.kind == TypeKind.REFERENCE
                                      and not var_info.type.reference_mutable)
                if is_imm_ref_binding:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot forward `&` reference `{expr.expr.name}` as `&var`: "
                        f"a shared `&` reference cannot be upgraded to `&var`",
                        expr.line, expr.column,
                        hint="take the parameter as `&var T` to forward it mutably, "
                             f"or forward it as `&{expr.expr.name}`"
                    )
                    return None
                # The `&var` the place transform builds out of a `lend` is
                # exempt (design 146, DF-146d). `lend` names a PLACE, and the
                # transform has already proved this one is storage — the new
                # case being a match-arm binding, which the checker registers
                # immutable because a match ordinarily binds a copy. Here the
                # arm is matching a place WHERE IT SITS, so the binding names
                # the enum's own payload and the window writes back through it.
                from_lend = getattr(expr, 'from_lend', False)
                if (var_info and not var_info.mutable and not is_mut_ref_binding
                        and not from_lend):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot take mutable reference to immutable variable `{expr.expr.name}`",
                        expr.line, expr.column,
                        hint="declare with `var` to make it mutable"
                    )
                    return None
            elif isinstance(expr.expr, SelfExpr):
                # In a `&var self` method the receiver is itself a mutable
                # reference binding, so re-borrowing the WHOLE self (`&var self` —
                # forwarding the receiver onward, design 106) is sound, mirroring
                # the `&var ref` param re-borrow above. `self`'s VariableInfo is
                # always registered `mutable=False` (self-mutability lives on the
                # method, not the binding), so consult the enclosing method's
                # `self_mutable`. A `&self` method's receiver is a shared borrow —
                # `&var self` is rejected.
                cm = getattr(self, "current_method", None)
                self_is_mut = cm is not None and getattr(cm, "self_mutable", False)
                if not self_is_mut:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot take mutable reference to immutable `self`",
                        expr.line, expr.column,
                        hint="use `&var self` in method signature to make self mutable"
                    )
                    return None
            elif self._projects_from_self(expr.expr):
                # A `&self` receiver arrives BY VALUE, so a `&var` projection out
                # of it addresses the callee's own copy: the write compiles, runs,
                # and is thrown away with the copy (DF-146b — live in the tree
                # from the first `&self` method until design 146 closed it).
                # Design 106 already refuses to upgrade a `&` PARAMETER to `&var`;
                # this is the same rule reaching the receiver it never covered.
                #
                # The one exception is the `&var` the place transform builds out
                # of a `lend`: a borrows accessor's receiver travels by pointer
                # exactly so its window can write through, and that reference is
                # marked `from_lend`.
                cm = getattr(self, "current_method", None)
                self_is_mut = cm is not None and getattr(cm, "self_mutable", False)
                if not self_is_mut and not getattr(expr, 'from_lend', False):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot take a mutable reference into a `&self` "
                        "receiver: `self` is borrowed SHARED here, so `&var "
                        "self....` would hand out a mutable reference to a copy "
                        "and the write would be lost",
                        expr.line, expr.column,
                        hint="declare the method `&var self` to mutate through "
                             "the receiver, or `borrows -> T` to lend the place "
                             "and let each use site choose the window's flavor"
                    )
                    return None

        # Return reference type
        return SawType(TypeKind.REFERENCE, inner_type=inner_type, reference_mutable=expr.mutable)

    def _projects_from_self(self, expr: Expression) -> bool:
        """Is this lvalue a projection rooted at `self` — `self.a`, `self.a[i]`,
        `self.t.0`, `self.opt!` — rather than storage reached some other way?

        A projection through a local (`if let buf = self.buffer  &var buf[i]`)
        is NOT one: the local holds a pointer value, and the storage it addresses
        is the heap's, not the receiver's copy.
        """
        node = expr
        while node is not None:
            if isinstance(node, SelfExpr):
                return True
            if isinstance(node, MemberAccess):
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

    def _is_lvalue(self, expr: Expression) -> bool:
        """Check if an expression is an lvalue (can have its address taken)."""
        # The payload of a force-unwrapped optional lvalue is itself an lvalue: its
        # address is the optional's payload slot (`&(opt!)` -> a pointer into the
        # stored value, guarded by a None-check). This lets a borrowed method
        # receiver held in an opt-encoded coroutine frame field be addressed
        # (design 84 nested suspending method embedding), and is a natural general
        # extension for taking a reference into an optional's contents.
        if isinstance(expr, ForceUnwrap):
            return self._is_lvalue(expr.expr)
        # A PLACE is storage by definition (design 141): `v.first()` and
        # `v.get(i)!` name an element the container already holds, so `&var`
        # into one is exactly as addressable as `&var v[i]`. The use-site
        # lowering turns the whole call into a window that spans it. The
        # annotation is stamped by `_check_place_use`, which has already run on
        # this node — `_check_reference_expr` checks the operand first.
        if getattr(expr, 'place_struct', None) is not None:
            return True
        # A TUPLE INDEX is storage on the same terms a struct field is
        # (DF-151j): `&var t.0` lends the element slot, so a `&var` callee
        # mutates the tuple's own element rather than a spilled copy.
        return isinstance(
            expr, (Identifier, MemberAccess, ArrayIndex, SelfExpr, TupleIndex))

    def _stamp_int_cast(self, expr: CastExpr, src_type: SawType,
                        to_type: SawType) -> bool:
        """Decide an integer cast's runtime check, or reject a constant operand
        that could not survive it (design 170).

        `x as UInt8` is CHECKED: a value the target cannot represent — by range
        or by sign — panics rather than silently becoming a different number.
        Narrowing `as` was the last silent value-corrupting operation in a
        language where arithmetic overflow, bounds, shifts and allocation
        failure all trap, so it joins them.

        Three outcomes, and the cost is the point of separating them:

        * TOTAL pair -> nothing stamped. Widening emits exactly what it emitted
          before: every source value has a target representation, so a check
          could only ever be true.
        * FOLDABLE operand -> the answer is known now. In range, nothing is
          stamped and the cast is free; out of range, this is a COMPILE ERROR
          rather than a program that builds and then aborts on its first run.
          `const_eval` is the same evaluator `static_assert` and `[T; N]` use
          (its own out-of-range rule at `const_eval.py:167` set this policy),
          so a folded cast and its runtime twin can never disagree.
        * anything else -> `cast_check`, one compare-and-branch on the
          narrowing/sign-change edge. That is the overflow-check cost class,
          and the optimizer still deletes it wherever it can prove the range
          itself.

        `src_type` is the operand type AFTER design-63 alias resolution and
        after a raw-backed enum has been reduced to its backing, so this reads
        real numeric kinds. Returns True when an error was reported.
        """
        from const_eval import CAST_INT_KINDS, const_eval, ConstEvalError
        src = CAST_INT_KINDS.get(src_type.kind)
        dst = CAST_INT_KINDS.get(to_type.kind)
        if src is None or dst is None:
            return False
        width = self.platform_int_width
        src_bits = src[0] or width
        dst_bits = dst[0] or width
        src_signed, dst_signed = src[1], dst[1]

        # Total: strictly wider and no sign the target cannot express, or the
        # identity. Signed -> unsigned is never total (a negative has no
        # unsigned image at any width), and same-width sign changes are not
        # either (`-1 as UInt8`, `UInt64.max as Int64`).
        if dst_bits > src_bits and (dst_signed or not src_signed):
            return False
        if dst_bits == src_bits and dst_signed == src_signed:
            return False

        lo = -(1 << (dst_bits - 1)) if dst_signed else 0
        hi = ((1 << (dst_bits - 1)) - 1) if dst_signed else (1 << dst_bits) - 1
        try:
            value = const_eval(expr.expr, env=self._const_param_env(),
                               width=width)
        except ConstEvalError:
            value = None
        if isinstance(value, bool):
            value = None
        if isinstance(value, int):
            if lo <= value <= hi:
                return False
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{value}` is not representable as `{to_type}`, so this cast "
                f"would always panic",
                expr.line, expr.column,
                hint=f"`{to_type}` holds {lo} through {hi}; write "
                     f"`{to_type}.from(truncating: ...)` to keep the low bits, "
                     f"or `{to_type}.from(...)` to get `None` instead"
            )
            return True
        expr.cast_check = True
        return False

    def _check_int_from(self, expr) -> Optional[SawType]:
        """`T.from(x) -> T?` and `T.from(truncating: x) -> T` (design 170).

        The two siblings of the checked cast, completing the accessor triple the
        rest of the language already follows: `as` traps, `from` returns the
        `None`, `from(truncating:)` does the thing you asked for on purpose.

        `from(_)` is defined UNIFORMLY across every integer source, total pairs
        included — `Int.from(x: Int8)` is always `Some`. Uniformity beats
        cleverness here: a generic body may rely on the shape existing for
        whatever `T` it is instantiated at, and the always-true check folds to
        nothing, so the uniformity is free.

        `from(truncating:)` keeps the low bits — the value mod 2^n. The LABEL is
        the operation (design 55/93 make labels overload identity), which is why
        there is no boolean parameter and therefore no nonsense
        `truncate: false` corner to define. It is the cast-shaped sibling of the
        `&+`/`&-`/`&*` wrapping operators.

        Neither one const-errors on an out-of-range constant the way `as` does:
        answering out-of-range IS what these are for.
        """
        target_kind = self._INT_LIMIT_TYPE_KINDS[expr.object.name]
        to_type = SawType(target_kind)
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{to_type}.from` takes exactly one argument, "
                f"got {len(expr.arguments)}",
                expr.line, expr.column,
                hint=f"`{to_type}.from(x)` yields `{to_type}?`; "
                     f"`{to_type}.from(truncating: x)` keeps the low bits"
            )
            return None
        arg = expr.arguments[0]
        label = getattr(arg, 'name', None)
        if label is not None and label != "truncating":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{to_type}.from` has no argument labeled `{label}`",
                expr.line, expr.column,
                hint=f"write `{to_type}.from(x)` for the checked conversion "
                     f"(`{to_type}?`), or `{to_type}.from(truncating: x)` to "
                     f"keep the low bits"
            )
            return None
        # No expectation is pushed onto the argument: `UInt8.from(300)` must be
        # the `None` this exists to produce, not a range error at the literal.
        from_type = self._check_expression(arg.value)
        if from_type is None:
            return None
        # Design 63: an alias projects toward its underlying first, then the
        # integer rules apply — the same order `as` uses.
        if from_type.is_struct() and self.get_type_alias_info(from_type.struct_name):
            from_type = self._get_underlying_type(from_type)
        from const_eval import CAST_INT_KINDS
        src = CAST_INT_KINDS.get(from_type.kind)
        if src is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{to_type}.from` expects an integer, got `{from_type}`",
                expr.line, expr.column,
                hint="a raw-backed enum converts with `e as Backing` and back "
                     "with `E.from(raw:)`" if from_type.kind == TypeKind.ENUM
                     else None
            )
            return None
        truncating = label == "truncating"
        expr.int_from = (target_kind, truncating, src[1])
        if truncating:
            return to_type
        return SawType(TypeKind.OPTIONAL, inner_type=to_type)

    def _check_cast_expr(self, expr: CastExpr) -> Optional[SawType]:
        """Check a type cast expression: expr as Type"""
        # DF-163f: `(&x) as UnsafePointer<T>` is the sanctioned crossing into the
        # unsafe tier, and the only address-of Saw has — std and the runtime take
        # the address of a local, a static or `self` this way, and the chained
        # `(&self) as UnsafePointer<TaskGroup> as Int` is the token idiom. The
        # cast hands lifetime responsibility to that tier: the value produced is
        # a POINTER, so no reference survives the expression, and design 130's
        # signature effect is what fences it from there on. This is the node that
        # knows the parent, so it marks the operand before the reference rule
        # below sees it. Read off the type AS WRITTEN (an alias for a pointer
        # type is not blessed) so a bad target type is still reported once.
        if (isinstance(expr.expr, ReferenceExpr)
                and expr.target_type is not None
                and expr.target_type.kind == TypeKind.POINTER):
            expr.expr.to_pointer_cast = True
        from_type = self._check_expression(expr.expr)
        if from_type is None:
            return None
        to_type = self._resolve_type(expr.target_type)
        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        # Distinct-type projection (design 63): a value of a distinct `type`
        # alias may be cast TOWARD its underlying type. This is the sanctioned
        # explicit projection (it replaces the never-implemented `.value`).
        # ONE-DIRECTIONAL: `42 as UserId` stays an error (the reverse never
        # matches here — a primitive `from_type` is not an alias). We walk the
        # operand's alias chain toward the underlying:
        #   - if `to_type` is an alias ON that chain (a partial projection like
        #     `b as A` where `type B = A`), the cast is legal, result = to_type;
        #   - otherwise resolve `from_type` to its underlying and fall through to
        #     the normal kind-based rules with that underlying (so `id as Int`
        #     and `id as Int8` are ordinary integer casts, while a sibling alias
        #     `UserId as OrderId` finds no matching rule and errors).
        if from_type.is_struct() and self.get_type_alias_info(from_type.struct_name):
            # Walk the UNRESOLVED immediate targets so intermediate aliases stay
            # visible (`aliased_type` collapses the whole chain to the underlying).
            # This yields the set of distinct aliases strictly BELOW `from_type`
            # on its definition chain — a target in that set is a legal partial
            # projection; a sibling alias (same underlying, not on the chain) is
            # not, and reverse casts never reach here.
            ancestor_alias_names = self._alias_ancestor_names(from_type)
            # Partial projection: target is a distinct alias on the chain.
            if (to_type.is_struct() and to_type.struct_name in ancestor_alias_names):
                return to_type
            # Full projection: continue the kind-match against the underlying.
            from_type = self._get_underlying_type(from_type)
        # Raw-backed enum -> its backing integer (design 145 unit B2). TOTAL in
        # this direction: the enum IS its tag, so every value has an answer.
        # Only a DECLARED backing makes an enum castable — an ordinary enum's
        # ordinals are the compiler's business and reordering its cases must
        # stay a free edit. The inverse is partial and spelled `E.from(raw:)`.
        if from_type.kind == TypeKind.ENUM and to_type.kind in int_kinds:
            enum_info = self.get_enum_info(from_type.enum_name)
            raw_type = getattr(enum_info, 'raw_type', None) if enum_info else None
            if raw_type is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"enum `{from_type.enum_name}` has no backing type, so it "
                    f"cannot be cast to `{to_type}`",
                    expr.line, expr.column,
                    hint=f"declare one (`enum {from_type.enum_name}: {to_type} "
                         f"{{ case A = 0, ... }}`) to pin the case values; "
                         f"without it the tag values are not part of the type"
                )
                return None
            # Design 170: the enum IS its tag, so the cast is total AT THE
            # BACKING WIDTH and stays exactly as free as it was. Narrowing
            # BELOW the backing (`enum E: UInt16` value `as UInt8`) is an
            # ordinary integer narrowing and takes the ordinary check.
            if self._stamp_int_cast(expr, raw_type, to_type):
                return None
            return to_type
        if from_type.kind in int_kinds and to_type.kind == TypeKind.ENUM:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot cast `{from_type}` to enum `{to_type.enum_name}`: not "
                f"every value names a case",
                expr.line, expr.column,
                hint=f"use `{to_type.enum_name}.from(raw: ...)`, which returns "
                     f"an optional — an unrecognized value is data, not a trap"
            )
            return None
        if from_type.kind in int_kinds and to_type.kind in int_kinds:
            # Design 170. `from_type` is already past the design-63 alias walk
            # above, so an alias projection resolves FIRST and then takes the
            # integer rules — composition unchanged.
            if self._stamp_int_cast(expr, from_type, to_type):
                return None
            return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.POINTER:
            return to_type
        # Reference -> raw pointer (design 42, slab regions): a `&T` immutable lend
        # (notably `&STATIC_ARRAY`) reinterpreted as an `UnsafePointer<...>` to the
        # referent's storage. Both are addresses at the LLVM level; the cast is the
        # explicit, unsafe bridge that lets a static region feed a slab allocator.
        if from_type.kind == TypeKind.REFERENCE and to_type.kind == TypeKind.POINTER:
            return to_type
        # Pointer <-> Int address round-trip (design 42, slab free-list): a slab
        # threads freed-chunk ADDRESSES through an `Atomic<Int>`, so it must turn a
        # raw pointer into its integer address (`ptr as Int`) and back
        # (`addr as UnsafePointer<Int8>`). Standard unsafe ptrtoint/inttoptr.
        if from_type.kind == TypeKind.POINTER and to_type.kind in int_kinds:
            return to_type
        if from_type.kind in int_kinds and to_type.kind == TypeKind.POINTER:
            return to_type
        if from_type.kind == TypeKind.STRING and to_type.kind == TypeKind.POINTER:
            if to_type.inner_type and to_type.inner_type.kind == TypeKind.INT8:
                return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.STRING:
            if from_type.inner_type and from_type.inner_type.kind == TypeKind.INT8:
                return to_type
        # Distinct-alias projection to a non-integer primitive / String / struct
        # underlying (design 63): after resolving the operand's alias above,
        # an identity-kind cast is a legal reinterpretation (same layout). Int
        # identity is already covered by the integer rule; this handles
        # `type Name = String; n as String` and struct-underlying aliases.
        if from_type.kind == to_type.kind and from_type.kind in (
                TypeKind.STRING, TypeKind.FLOAT, TypeKind.BOOL):
            return to_type
        if (from_type.kind == to_type.kind == TypeKind.STRUCT
                and from_type.struct_name == to_type.struct_name):
            return to_type
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"cannot cast `{from_type}` to `{to_type}`",
            expr.line, expr.column
        )
        return None

    def _check_binary_op(self, expr: BinaryOp) -> Optional[SawType]:
        """Check a binary operation."""
        left_type = self._check_expression(expr.left)
        right_type = self._check_expression(expr.right)
        if left_type is None or right_type is None:
            return None
        left_underlying = self._get_underlying_type(left_type)
        right_underlying = self._get_underlying_type(right_type)
        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        if expr.op in ['+', '-', '*', '/']:
            if expr.op in ['+', '-'] and left_underlying.kind == TypeKind.POINTER:
                if right_underlying.kind in int_kinds:
                    # Element-stride pointer arithmetic. The result is a raw
                    # pointer, so the design-130 trigger rule marks the enclosing
                    # function at the `_check_expression` chokepoint.
                    return left_type
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"pointer arithmetic requires integer offset, got `{right_type}`",
                        expr.line, expr.column
                    )
                    return None
            elif left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                fw = self._fixed_width_binop_type(expr, left_type, right_type)
                if fw is not None:
                    return fw
                if left_underlying.kind == right_underlying.kind:
                    return left_type
                return left_type
            elif left_underlying.kind in (int_kinds | {TypeKind.FLOAT}) and \
                 right_underlying.kind in (int_kinds | {TypeKind.FLOAT}):
                return SawType(TypeKind.FLOAT)
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` cannot be applied to `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == '%':
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                fw = self._fixed_width_binop_type(expr, left_type, right_type)
                if fw is not None:
                    return fw
                return left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `%` requires integer operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&+', '&-', '&*']:
            # Wrapping arithmetic (design 31): integer operands only. Float (and
            # everything else, including pointers) is rejected -- wraparound is
            # only defined for two's-complement integers.
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                return left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"wrapping operator `{expr.op}` requires integer operands, "
                    f"got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&', '|', '^', '<<', '>>']:
            # Bitwise AND/OR/XOR and shifts (design 50): integer operands only
            # (Bool uses `&&`/`||`; Float and everything else is rejected). The
            # result takes the left operand's type — for `>>` that also fixes the
            # arithmetic-vs-logical choice (signed left → arithmetic shift).
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                return left_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires integer operands, "
                    f"got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&&', '||']:
            if left_underlying.kind == TypeKind.BOOL and right_underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires Bool operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['==', '!=', '<', '>', '<=', '>=']:
            if not self._types_compatible(left_type, right_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare `{left_type}` with `{right_type}`",
                    expr.line, expr.column
                )
                return SawType(TypeKind.BOOL)
            # design 77 item 9: a bare integer literal compared against a
            # fixed-width operand adopts that operand's type (codegen already
            # coerces it), so range-check it here — otherwise `fd < 200` for
            # `fd: Int8` silently compared against the wrapped value -56. Extends
            # the design-65 fixed-width-literal range check to comparison
            # operands; a no-op unless one side is a bare literal and the other a
            # fixed-width integer.
            self._check_fixed_width_literal(expr.right, left_type,
                                            getattr(expr.right, 'line', expr.line),
                                            getattr(expr.right, 'column', expr.column))
            self._check_fixed_width_literal(expr.left, right_type,
                                            getattr(expr.left, 'line', expr.line),
                                            getattr(expr.left, 'column', expr.column))
            # Equatable gating (design 32): `==`/`!=` require the operand type to
            # conform to Equatable. Primitives and String conform builtin;
            # trivial (POD) structs and payload-free enums auto-conform;
            # everything else opts in with `extension T: Equatable {}`. A
            # `T: Equatable` bound satisfies this inside a generic body.
            if expr.op in ['==', '!='] and not self._bound_satisfied(left_type, "Equatable"):
                type_params = getattr(self, 'current_type_params', {})
                if left_type.kind == TypeKind.STRUCT and left_type.struct_name in type_params:
                    hint = f"add an `Equatable` bound: `<{left_type.struct_name}: Equatable>`"
                elif left_type.kind == TypeKind.STRUCT:
                    hint = f"add `extension {left_type.struct_name}: Equatable {{}}`"
                elif left_type.kind == TypeKind.ENUM:
                    hint = f"add `extension {left_type.enum_name}: Equatable {{}}`"
                else:
                    hint = None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare values of type `{left_type}` with `{expr.op}`: "
                    f"`{left_type}` does not conform to `Equatable`",
                    expr.line, expr.column,
                    hint=hint
                )
            # Comparable gating (design 48): `< <= > >=` desugar to `compare()`.
            # Integer types and Float are ordered directly (Float keeps IEEE/NaN
            # semantics); raw pointers keep their historical address ordering;
            # String and user types require Comparable (builtin for String, opt-in
            # `extension T: Comparable {}` for structs/enums). A `T: Comparable`
            # bound satisfies this inside a generic body.
            if expr.op in ['<', '>', '<=', '>=']:
                lu = self._get_underlying_type(left_type)
                numeric = int_kinds | {TypeKind.FLOAT}
                if lu.kind not in numeric and lu.kind != TypeKind.POINTER:
                    if not self._bound_satisfied(left_type, "Comparable"):
                        type_params = getattr(self, 'current_type_params', {})
                        if left_type.kind == TypeKind.STRUCT and left_type.struct_name in type_params:
                            hint = f"add a `Comparable` bound: `<{left_type.struct_name}: Comparable>`"
                        elif left_type.kind == TypeKind.STRUCT:
                            hint = f"add `extension {left_type.struct_name}: Comparable {{}}`"
                        elif left_type.kind == TypeKind.ENUM:
                            hint = f"add `extension {left_type.enum_name}: Comparable {{}}`"
                        else:
                            hint = None
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot order values of type `{left_type}` with "
                            f"`{expr.op}`: `{left_type}` does not conform to "
                            f"`Comparable`",
                            expr.line, expr.column,
                            hint=hint
                        )
            return SawType(TypeKind.BOOL)
        return None

    def _check_unary_op(self, expr: UnaryOp) -> Optional[SawType]:
        """Check a unary operation."""
        operand_type = self._check_expression(expr.operand)
        if operand_type is None:
            return None
        underlying = self._get_underlying_type(operand_type)
        if expr.op == '-':
            # Unary negation (design 77 item 8): signed integers (platform `Int`
            # + fixed-width `Int8`..`Int64`) and `Float`. Negating a fixed-width
            # signed int is checked-overflow at codegen exactly like `Int`
            # (`-Int8.min` panics). Unsigned negation is a type error (there is no
            # negative unsigned value).
            signed_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16,
                            TypeKind.INT32, TypeKind.INT64}
            unsigned_kinds = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16,
                              TypeKind.UINT32, TypeKind.UINT64}
            if underlying.kind in signed_kinds or underlying.kind == TypeKind.FLOAT:
                # A negated fixed-width integer LITERAL folds to the negated
                # constant at codegen (design 77 item 8); range-check that folded
                # value here so `-128i8` (= Int8.min) is legal but `-200i8` is a
                # clean error rather than a silent codegen truncation.
                if (isinstance(expr.operand, IntLiteral)
                        and underlying.kind in self._FIXED_INT_RANGES):
                    lo, hi = self._FIXED_INT_RANGES[underlying.kind]
                    neg = -expr.operand.value
                    if not (lo <= neg <= hi):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"integer literal {neg} does not fit in "
                            f"`{operand_type}` (range {lo}..={hi})",
                            expr.line, expr.column)
                        return None
                return operand_type
            elif underlying.kind in unsigned_kinds:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to unsigned `{operand_type}` "
                    f"(an unsigned integer has no negation)",
                    expr.line, expr.column
                )
                return None
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == 'not':
            if underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `not` requires Bool operand, got `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == '~':
            # Bitwise complement (design 50): integer-only. `not` is the Bool
            # logical negation; `~` flips all bits of an integer.
            int_kinds = {
                TypeKind.INT, TypeKind.UINT,
                TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
            }
            if underlying.kind in int_kinds:
                return operand_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `~` requires an integer operand, got `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        return None

    def _restore_authored_callee(self, node, attr: str) -> None:
        """Put the AUTHORED callee name and type arguments back on `node`.

        Driving and spawning a generic REWRITE the call in place: the callee
        becomes the monomorphized symbol and the type arguments are cleared, so
        the coroutine transform sees an ordinary non-generic call. That rewrite
        is not idempotent, and the front half runs more than once over the same
        AST — the place lowering re-enters over the tree it just checked
        (design 146). A second pass would look up `settle$1$Int`, the name the
        FIRST pass wrote, and find no such method.

        So the authored form is recorded the first time and restored on every
        later pass, which then re-derives exactly the same symbol.
        """
        saved = getattr(node, '_authored_callee', None)
        if saved is None:
            node._authored_callee = (getattr(node, attr),
                                     getattr(node, 'type_args', None))
        else:
            setattr(node, attr, saved[0])
            node.type_args = saved[1]

    def _restore_authored_call(self, node) -> None:
        """`_restore_authored_callee` for a call of either shape."""
        from ast_nodes import MethodCall as _MC
        self._restore_authored_callee(
            node, 'method_name' if isinstance(node, _MC) else 'name')

    def _drive_generic_method(self, inner, struct_name, mode, expr):
        """design 70 (A5): drive a generic (method-level type params) suspending
        method. Monomorphize the method to a concrete method keyed by the mangled
        symbol, register + splice it onto the receiver's extension, record it a
        driven-method root, and rewrite the call so the coroutine transform's
        Part-0c method driving sees an ordinary non-generic method."""
        self._restore_authored_callee(inner, 'method_name')
        resolved_args = [self._resolve_type(a) for a in inner.type_args]
        if not all(self._is_concrete_type(a) for a in resolved_args):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}(...)` of a generic method requires concrete type "
                f"arguments", inner.line, inner.column)
            return
        from codegen.mangle import mangle_named
        mono_name = mangle_named(inner.method_name, resolved_args)
        if not self._effect_queue_method_mono(struct_name, inner.method_name,
                                              resolved_args, mono_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"driving generic method `{struct_name}.{inner.method_name}` is not "
                f"supported (its template could not be monomorphized for effect "
                f"inference)", inner.line, inner.column)
            return
        self._effect_record_driven_method(struct_name, mono_name, mode)
        inner.method_name = mono_name
        inner.type_args = None

    def _drive_generic_struct_method(self, inner, struct_name, recv_type, mode, expr):
        """design 74 (A5-rest, shape 2): drive a suspending method on a GENERIC
        struct for a concrete receiver (`__saw_drive(b.run())`, `b: Holder<Int>`).
        Monomorphize the method over the struct's type params (T->Int), queue the
        clone+re-check for effect harvest, record the concrete driven-method root,
        and rewrite the call so the coroutine transform's Part-0c method driving
        sees an ordinary non-generic method (keyed by a per-instantiation name)."""
        self._restore_authored_callee(inner, 'method_name')
        struct_sym = self.namespace.lookup_struct(struct_name)
        tps = struct_sym.type_params or []
        resolved_args = [self._resolve_type(a) for a in (recv_type.type_args or [])]
        if len(resolved_args) != len(tps) or not all(
                self._is_concrete_type(a) for a in resolved_args):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{expr.name}(...)` of a method on generic struct `{struct_name}` "
                f"requires a fully concrete receiver", inner.line, inner.column)
            return
        entry = self._pristine_generic_struct_methods.get(
            (struct_name, inner.method_name))
        if entry is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"driving suspending method `{struct_name}.{inner.method_name}` on a "
                f"generic struct is not supported (its template could not be found "
                f"for monomorphization; design 74 A5-rest)",
                inner.line, inner.column)
            return
        pristine, _ext = entry
        # design 104 item 3: a method that is BOTH struct-generic (`Dual<T>`) AND
        # method-generic (`mix<U>`). Resolve the method's OWN type args from the call
        # and key the frame by BOTH instantiations (design 95's resolved-signature
        # keying, extended with the method's type args) — so 2 struct × 2 method
        # instantiations produce 4 distinct frames.
        method_tps = getattr(pristine, 'type_params', None) or []
        method_args = []
        if method_tps:
            if not inner.type_args or len(inner.type_args) != len(method_tps):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"driving generic method `{struct_name}.{inner.method_name}` "
                    f"requires {len(method_tps)} concrete method type argument(s)",
                    inner.line, inner.column)
                return
            method_args = [self._resolve_type(a) for a in inner.type_args]
            if not all(self._is_concrete_type(a) for a in method_args):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{struct_name}.{inner.method_name}<...>` requires concrete "
                    f"method type arguments", inner.line, inner.column)
                return
        from codegen.mangle import mangle_named
        # Encode both the struct's and the method's type args, so each
        # (struct instantiation, method instantiation) pair gets a distinct frame.
        mono_name = mangle_named(inner.method_name, resolved_args + method_args)
        # Carry the concrete receiver type (`Holder<Int>`) so the frame's `__recv`
        # points at the monomorphized struct codegen produces for it.
        concrete_recv = SawType(TypeKind.STRUCT, struct_name=struct_name,
                                type_args=resolved_args)
        self._effect_queue_generic_struct_method_mono(
            struct_name, inner.method_name, resolved_args, method_args, mono_name,
            concrete_recv)
        self._effect_record_driven_method(struct_name, mono_name, mode)
        inner.method_name = mono_name
        inner.type_args = None

    def _check_spawn(self, expr: FunctionCall) -> Optional[SawType]:
        """Type-check the `spawn { ... }` intrinsic (design 21 item 5).

        `spawn` takes exactly one no-parameter closure and returns `Task<T>`,
        where `T` is the closure's result type. The closure escapes (it runs on
        another thread that outlives the call), so it is lowered with a heap env
        (E1). Every captured value's type must be `Send`: the capture audit walks
        `closure.captures`, resolves each name's type in the enclosing scope, and
        rejects the first non-`Send` capture, naming the capture and its type.
        """
        if len(expr.arguments) != 1 or not isinstance(expr.arguments[0].value, ClosureExpr):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`spawn` takes exactly one closure argument: `spawn { ... }`",
                expr.line, expr.column
            )
            return None
        closure = expr.arguments[0].value
        if closure.parameters or closure.shorthand_param_count:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`spawn`'s closure takes no parameters",
                closure.line, closure.column
            )
        # Check the body as an escaping closure (heap env, move-only-capture
        # rejection). Not a `sync` context: task bodies may suspend under a
        # future cooperative engine.
        ctype = self._check_closure(closure, expected_type=None,
                                    as_call_argument=True, force_escape=True)
        result_type = SawType(TypeKind.VOID)
        if ctype is not None and ctype.kind == TypeKind.FUNCTION:
            result_type = ctype.func_return_type or SawType(TypeKind.VOID)
        # Send capture-audit: every captured value must be safe to transfer to
        # the task thread. Resolve each capture's type and reject the first that
        # is not Send, naming the capture and its type.
        for cap_name in closure.captures:
            cap_info = self.current_scope.lookup(cap_name)
            if cap_info is None:
                continue
            if not self.namespace.is_send(cap_info.type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot `spawn`: captured `{cap_name}` of type "
                    f"`{cap_info.type}` is not `Send`",
                    closure.line, closure.column,
                    hint="only Send values may cross to another task; share via "
                         "`Arc` (and `Mutex` for mutation)"
                )
                break
        expr.spawn_result_type = result_type
        return SawType(TypeKind.STRUCT, struct_name="Task", type_args=[result_type])

    # ======================================================================
    # Overload resolution (design 55)
    # ======================================================================

    def _overload_cand_offset(self, cand, is_method: bool) -> int:
        """Parameter offset for a candidate: methods skip the `self` slot unless
        the candidate is static/init; free functions never skip."""
        if is_method and not (cand.is_static or cand.is_init):
            return 1
        return 0

    def _format_arg_types(self, arg_types) -> str:
        return ", ".join("<closure>" if at is None else str(at) for at in arg_types)

    def _format_overload_candidate(self, name: str, cand, is_method: bool) -> str:
        offset = self._overload_cand_offset(cand, is_method)
        ps = cand.param_types[offset:]
        ns = cand.param_names[offset:] if cand.param_names else []
        prefix = "<T> " if cand.type_params else ""
        # Design 66: show the labeled form (`name(label: Type, ...)`) so an
        # ambiguity diagnostic tells the user which labels disambiguate.
        parts = []
        for i, p in enumerate(ps):
            nm = ns[i] if i < len(ns) else None
            parts.append(f"{nm}: {p}" if nm else f"{p}")
        return f"{prefix}{name}(" + ", ".join(parts) + ")"

    def _resolve_overload(self, display_name, candidates, arg_types,
                          has_type_args, is_method, line, column, arguments,
                          expr=None, base_subst=None):
        """Select the unique matching overload for a call (design 55 + 66 + 105).

        `arg_types[i] is None` marks a closure argument, which is neutral for
        matching (the closure-arg rule: resolve on the non-closure arguments;
        if candidates still tie and differ only in closure-param types they stay
        tied and yield the ambiguity error below).

        Design 66 LABEL FILTER runs FIRST: a candidate is eliminated if the
        call's labels cannot bind under the binding rule (unknown label, backward
        binding, missing forward-skip, arity). Surviving candidates then face the
        design-55 exact-type matching + tie-breaks, in order:
          1. exact beats optional-wrap (fewest implicit `T -> T?` wraps wins);
          2. resolution precedes Result/Optional auto-wrap (raw argument types);
          3. concrete beats generic (a concrete overload that matches wins over
             any generic candidate — design 55's exact-match model is untouched).
        Design 105: when NO concrete (or explicit-type-arg generic) candidate
        matches, generic candidates are tried by PER-CANDIDATE inference (each in
        its own sandbox); exactly one solving-and-type-matching candidate is
        picked (its solved type args stamped onto `expr.type_args`), two or more
        raise a clean ambiguity error listing the solving candidates + their
        solved type args, and zero falls through to the no-match diagnostic.
        Returns `(chosen FunctionSymbol, binding_mapping)`; the mapping is the
        per-source-argument logical parameter index for the winner (used to align
        argument checks and stamp `arg_plan`). Returns `(None, None)` after a
        no-match or ambiguity diagnostic listing the candidates in LABELED form.
        """
        n = len(arg_types)
        matches = []  # (candidate, wrap_penalty, is_generic, mapping)
        infer_cands = []  # design 105: generic candidates to try by inference
        for cand in candidates:
            is_generic = bool(cand.type_params)
            if has_type_args and not is_generic:
                continue
            offset = self._overload_cand_offset(cand, is_method)
            cparams = cand.param_types[offset:]
            cnames = list(cand.param_names[offset:]) if cand.param_names else []
            defaults = cand.default_values[offset:] if cand.default_values else []
            # LABEL FILTER (design 66): the labels + arity must bind. This also
            # subsumes the old arity gate for positional calls.
            mapping, berr = self._compute_binding(cnames, defaults, arguments)
            if berr is not None:
                continue
            # A generic overload with no explicit type args is a design-105
            # inference candidate (deferred; tried only if no concrete match).
            if is_generic and not has_type_args:
                infer_cands.append((cand, mapping, offset))
                continue
            tp_names = {tp.name for tp in (cand.type_params or [])}
            ok = True
            penalty = 0
            for i in range(n):
                p = mapping[i]
                pt = cparams[p] if p < len(cparams) else None
                at = arg_types[i]
                is_gp = pt is not None and (
                    pt.kind == TypeKind.TYPE_PARAM
                    or (pt.kind == TypeKind.STRUCT and pt.struct_name in tp_names))
                if is_gp or at is None or pt is None:
                    continue  # generic slot / closure arg: neutral
                if not self._types_compatible(at, pt):
                    # design 51 + DF-169a: a `&concrete` argument fits a
                    # `&any Trait` slot when the concrete conforms. Candidate
                    # selection has to know that, or an overload set holding an
                    # existential parameter matches nothing and the erasure the
                    # argument pass would have performed is never reached.
                    if not self._erasure_compatible(at, pt):
                        ok = False
                        break
                    # An exact concrete overload outranks the erasing one, the
                    # same way an exact type outranks an optional wrap.
                    penalty += 1
                    continue
                if pt.is_optional() and not at.is_optional():
                    penalty += 1  # exact-vs-optional-wrap discriminator
                elif (at.kind in self._PLATFORM_INT_KINDS
                        and pt.kind in self._PLATFORM_INT_KINDS
                        and at.kind != pt.kind):
                    # Design 137: between platform `Int` and platform `UInt`, the
                    # EXACT one wins. The two are mutually compatible (design 53,
                    # so an unsuffixed literal can initialize either), which left
                    # `f(Int)` and `f(UInt)` tied at EVERY call site — including
                    # `f(someInt)`, where one is an exact match — and reported
                    # "ambiguous call" instead of picking. The pair was
                    # unwritable; `StringBuilder.append` needs both, because the
                    # signed overload cannot represent the top half of `UInt`.
                    #
                    # Deliberately narrow. A bare literal's WIDTH stays flexible,
                    # so `h(Int)` vs `h(Int8)` called `h(5)` is still the design-55
                    # ambiguity error (`overload_call_ambiguous_error`): 5 really
                    # could be either, and signedness is the only axis on which
                    # the argument type is already committed.
                    penalty += 1
            if ok:
                matches.append((cand, penalty, is_generic, mapping))
        if not matches:
            # Design 105: no concrete/explicit match — try generic inference per
            # candidate (each fully sandboxed, so a candidate that fails to solve
            # leaves zero residue). Requires the call node to run the solver.
            if infer_cands and expr is not None:
                solved = []  # (candidate, mapping, solved_type_args)
                for cand, mapping, offset in infer_cands:
                    targs = self._try_infer_overload_candidate(
                        cand, expr, mapping, offset, base_subst or {}, arg_types)
                    if targs is not None:
                        solved.append((cand, mapping, targs))
                if len(solved) == 1:
                    cand, mapping, targs = solved[0]
                    expr.type_args = targs
                    # Mark as INFERRED so a re-check (spawn/drive/coro re-typecheck)
                    # re-runs inference instead of mistaking these for explicit
                    # call-site type args (which would mis-resolve the overload).
                    expr.type_args_inferred = True
                    return cand, mapping
                if len(solved) >= 2:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"ambiguous call to `{display_name}`: type-argument "
                        f"inference matches multiple generic overloads "
                        f"({self._format_arg_types(arg_types)})",
                        line, column,
                        hint="give explicit type arguments or labels to select "
                             "one; matching: " + "; ".join(
                                 self._format_overload_candidate(
                                     display_name, c, is_method)
                                 + " with "
                                 + self._format_solved_type_args(c, ta)
                                 for c, _m, ta in solved))
                    return None, None
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no overload of `{display_name}` matches the argument types "
                f"({self._format_arg_types(arg_types)})",
                line, column,
                hint="candidates: " + "; ".join(
                    self._format_overload_candidate(display_name, c, is_method)
                    for c in candidates)
            )
            return None, None
        minpen = min(m[1] for m in matches)
        matches = [m for m in matches if m[1] == minpen]
        if any(not m[2] for m in matches):
            matches = [m for m in matches if not m[2]]  # concrete beats generic
        if len(matches) == 1:
            return matches[0][0], matches[0][3]
        # Same-type different-label overloads under a POSITIONAL call tie here;
        # the labeled forms in the hint tell the user how to disambiguate.
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"ambiguous call to `{display_name}`: multiple overloads match the "
            f"argument types ({self._format_arg_types(arg_types)})",
            line, column,
            hint="matching candidates: " + "; ".join(
                self._format_overload_candidate(display_name, m[0], is_method)
                for m in matches)
        )
        return None, None

    def _try_infer_overload_candidate(self, cand, expr, mapping, offset,
                                      base_subst, arg_types):
        """Design 105: try to solve one generic overload candidate's own type
        arguments by inference (silently). Returns the solved type-argument list
        (one per `cand.type_params`) if inference succeeds AND every known actual
        argument type-matches the substituted parameter, else None. Fully
        sandboxed by `_solve_call_type_args`, so a failed attempt leaves no
        residue (moves / mono queues / effect edges roll back)."""
        abstract_params = cand.param_types[offset:]
        full = self._solve_call_type_args(
            cand.type_params, abstract_params, expr,
            mapping if mapping is not None else None,
            base_subst, None, "", expr.line, expr.column, silent=True,
            known_arg_types=arg_types,
            default_values=(cand.default_values[offset:]
                            if cand.default_values else None))
        if full is None:
            return None
        # Type-match: each KNOWN actual argument must be compatible with its
        # solved parameter (a closure arg is None here — it drove the solve).
        for i, at in enumerate(arg_types):
            if at is None:
                continue
            p = mapping[i] if mapping is not None else i
            if p >= len(abstract_params):
                return None
            pt = abstract_params[p].substitute(full)
            if not self._arg_type_ok(None, at, pt):
                return None
        return [full[tp.name] for tp in cand.type_params]

    def _format_solved_type_args(self, cand, type_args) -> str:
        """Render a candidate's solved type arguments as `<T=Int, U=String>` for
        the design-105 overload-ambiguity diagnostic."""
        parts = [f"{tp.name}={ta}"
                 for tp, ta in zip(cand.type_params or [], type_args or [])]
        return "<" + ", ".join(parts) + ">"

    def _arg_type_ok(self, arg_value, arg_type, expected_type, allow_wrap=True):
        """Argument-position type check with DF3 call-site optional auto-wrap
        (design 57). Returns True if a value of `arg_type` may be passed where
        `expected_type` is wanted, recording a one-level `T -> T?` wrap on
        `arg_value` (an AST node) when that is what makes it compatible — so
        codegen constructs `Some(x)` at the argument edge.

        Ordering: this runs AFTER overload resolution (design 55 rule 1 already
        preferred an exact match over an optional-wrap), then injects the wrap
        at the argument-passing edge (the design-30 return machinery is
        untouched). Only ONE level (`T -> T?`, never `T -> T??`). `allow_wrap`
        is False at a generic-instantiation boundary: a bare type parameter that
        substitutes to an optional does NOT auto-wrap — wrapping must be explicit
        there.
        """
        # Clear any wrap decided by an earlier candidate before deciding again.
        # (`autowrap_to_optional` is a declared field since design 126 R1, so the
        # old `hasattr` guard here was always true -- it read as conditional but
        # never was.)
        if arg_value is not None:
            arg_value.autowrap_to_optional = None
        if arg_type is None or expected_type is None:
            return True
        # A bare `None` argument to an optional parameter: annotate the literal
        # with the concrete optional type so codegen can build the None value
        # (call-argument None was previously untyped — same fix struct-field
        # init already applies).
        if arg_type.is_none_literal():
            if expected_type.is_optional() and arg_value is not None:
                arg_value.resolved_type = expected_type
            return self._types_compatible(arg_type, expected_type)
        # Not the wrap case (expected is non-optional, or the argument is itself
        # already optional): defer to ordinary compatibility, no wrap.
        if not (expected_type.is_optional() and not arg_type.is_optional()):
            return self._types_compatible(arg_type, expected_type)
        # Here: `expected` is optional and `arg` is a bare (non-optional) value —
        # a candidate one-level `T -> T?` auto-wrap (DF3, design 57).
        inner = expected_type.inner_type
        if inner is None or inner.is_optional():
            return False  # would be a >1-level wrap (e.g. Int -> Int??): reject
        if arg_type.kind == TypeKind.NEVER:
            return True   # a diverging expression fits any home
        if not self._types_compatible(arg_type, inner):
            return False
        if not allow_wrap:
            return False  # no auto-wrap across a generic-instantiation boundary
        if arg_value is not None:
            arg_value.autowrap_to_optional = expected_type
        return True

    def _df3_allow_wrap(self, declared_type, tp_names=None):
        """DF3: auto-wrap is disallowed when the parameter's optional-ness comes
        from substituting a generic type parameter (design 57 — explicit at
        generic boundaries). Returns False iff the DECLARED (pre-substitution)
        parameter type is a bare type-parameter reference."""
        if declared_type is None:
            return True
        if declared_type.kind == TypeKind.TYPE_PARAM:
            return False
        if (declared_type.kind == TypeKind.STRUCT and tp_names
                and declared_type.struct_name in tp_names):
            return False
        return True

    def _has_explicit_type_args(self, expr) -> bool:
        """Design 105: whether the call carries EXPLICIT (user-written) type args.
        Type args stamped by inference are marked `type_args_inferred` so a
        re-check (spawn/drive/coro re-typecheck) re-infers rather than treating
        the inferred args as an explicit-generic overload selection."""
        return bool(getattr(expr, 'type_args', None)) and not getattr(
            expr, 'type_args_inferred', False)

    def _call_has_labels(self, expr) -> bool:
        """Whether the call carries at least one labeled argument (design 66).
        Positional-only calls take the byte-identical legacy path everywhere;
        the labeled binding machinery engages only when this is True."""
        return any(getattr(a, 'name', None) is not None for a in expr.arguments)

    def _compute_binding(self, param_names, default_values, arguments):
        """Design 66 argument binding, no diagnostics. `param_names`/
        `default_values` are LOGICAL (self already stripped for methods).

        Arguments bind LEFT TO RIGHT: a positional argument binds the next
        unbound parameter; a labeled argument binds the parameter it names,
        provided that parameter sits AT or AFTER the next unbound position and
        every parameter skipped forward over it carries a default. No backward
        binding, no reordering. Returns `(mapping, err)` where `mapping[i]` is
        the logical parameter index bound by source argument `i`, and `err` is
        None on success or `(kind, code, detail, arg_index)` describing the
        first binding failure (`arg_index` is None for a trailing missing
        parameter). Codes: 'too_many', 'unknown', 'duplicate', 'backward',
        'missing'."""
        n = len(param_names)
        dvals = default_values or []
        has_default = [(i < len(dvals) and dvals[i] is not None) for i in range(n)]
        next_pos = 0
        mapping = []
        bound = set()
        for ai, arg in enumerate(arguments):
            if getattr(arg, 'name', None) is None:
                if next_pos >= n:
                    return (None, ('too_many', 'too_many', None, ai))
                mapping.append(next_pos)
                bound.add(next_pos)
                next_pos += 1
            else:
                if arg.name not in param_names:
                    return (None, ('unknown', 'unknown', arg.name, ai))
                target = param_names.index(arg.name)
                if target in bound:
                    return (None, ('duplicate', 'duplicate', arg.name, ai))
                if target < next_pos:
                    return (None, ('backward', 'backward', arg.name, ai))
                for k in range(next_pos, target):
                    if not has_default[k]:
                        return (None, ('missing', 'missing', param_names[k], ai))
                mapping.append(target)
                bound.add(target)
                next_pos = target + 1
        for k in range(n):
            if k not in bound and not has_default[k]:
                return (None, ('missing', 'missing', param_names[k], None))
        return (mapping, None)

    def _bind_args(self, expr, param_names, default_values, display_name):
        """Design 66 binding with call-site diagnostics. Returns `mapping`
        (source-arg index -> logical parameter index) and stamps `expr.arg_plan`
        (a list over logical parameters: the source-arg index that binds each,
        or None for a default-filled parameter) for codegen. Returns None after
        reporting the binding error. Only called for calls that carry a label."""
        mapping, err = self._compute_binding(param_names, default_values, expr.arguments)
        if err is not None:
            _, code, detail, ai = err
            if ai is not None and ai < len(expr.arguments):
                node = expr.arguments[ai].value
                line, col = node.line, node.column
            else:
                line, col = expr.line, expr.column
            if code == 'too_many':
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{display_name}` was given more arguments than it has parameters",
                    line, col)
            elif code == 'unknown':
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{display_name}` has no parameter named `{detail}`",
                    line, col)
            elif code == 'duplicate':
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"argument `{detail}` specified more than once",
                    line, col)
            elif code == 'backward':
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"labeled argument `{detail}` cannot bind backward; "
                    f"arguments bind left to right",
                    line, col,
                    hint="labels may skip forward only over parameters with defaults")
            else:  # missing
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"missing argument for parameter `{detail}`",
                    line, col)
            return None
        plan = [None] * len(param_names)
        for ai, p in enumerate(mapping):
            plan[p] = ai
        expr.arg_plan = plan
        return mapping

    def _stamp_overload_plan(self, expr, logical_param_names, mapping):
        """Design 66: for a LABELED overloaded call, stamp `expr.arg_plan` (a list
        over the winner's logical parameters: source-arg index or None for a
        default-filled slot) so codegen interleaves mid-skipped defaults. A
        positional overloaded call keeps `arg_plan` unset (legacy codegen path)."""
        if mapping is None or not self._call_has_labels(expr):
            return
        plan = [None] * len(logical_param_names)
        for ai, p in enumerate(mapping):
            if p < len(plan):
                plan[p] = ai
        expr.arg_plan = plan

    def _aligned_call_meta(self, expr, mapping, param_types, param_names):
        """Return (param_types, param_names) positionally aligned to the source
        arguments for the exclusivity check. With no labels (`mapping is None`)
        this is the identity — the legacy positional alignment. With labels the
        binding may reorder/skip, so each source argument's parameter type/name
        is looked up through `mapping`."""
        if mapping is None:
            return param_types, param_names
        pt = list(param_types) if param_types is not None else []
        pn = list(param_names) if param_names is not None else []
        aligned_types = [pt[p] if p < len(pt) else None for p in mapping]
        aligned_names = [pn[p] if p < len(pn) else None for p in mapping]
        return aligned_types, aligned_names

    def _overload_arg_types(self, expr):
        """Type-check the non-closure arguments once (recording moves/effects a
        single time) and return the list of argument types, with `None` in each
        closure slot (deferred until the expected type is known)."""
        arg_types = []
        for arg in expr.arguments:
            if isinstance(arg.value, ClosureExpr):
                arg_types.append(None)
            else:
                arg_types.append(self._check_expression(arg.value))
        return arg_types

    def _finish_overloaded_args(self, expr, param_types, arg_types, mapping=None):
        """Shared tail for a resolved overloaded call: check each argument
        against its resolved parameter type (closures inferred now) and run the
        value-transfer chokepoint exactly once per argument. `param_types` is the
        winner's LOGICAL parameter list; `mapping[i]` (design 66) is the logical
        parameter index bound by source argument `i` — identity when the call is
        positional."""
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected = param_types[p] if p < len(param_types) else None
            if isinstance(arg.value, ClosureExpr):
                at = self._check_closure(arg.value, expected, as_call_argument=True)
            else:
                at = arg_types[i]
            if self._try_existential_arg_coercion(arg, at, expected):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif (at is not None and expected is not None
                    and not self._arg_type_ok(arg.value, at, expected)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected}` but got `{at}`",
                    arg.value.line, arg.value.column
                )
            # Design 87: a bare literal adopts the resolved param's fixed-width
            # type (+ range check). Overload args are checked before the winner
            # is known, so this coerces POST-HOC (restamps the leaf's type).
            self._apply_literal_expected_type(arg.value, expected)
            self._check_value_transfer(arg.value, expected, "call argument",
                                       arg.value.line, arg.value.column)

    # ---------------------------------------------------------------- design 93
    # Generic type-argument inference. `v.map({ $0.to_string() })` solves the
    # method's own `<U>` from the closure's inferred return type; a free function
    # `wrap(x)` solves `<T>` from the argument type. Explicit `<...>` is always
    # allowed and wins; a partial explicit prefix pins its leading params and the
    # rest are inferred. Inference NEVER guesses: an underdetermined or
    # conflicting parameter is a clean error naming the parameter and suggesting
    # explicit arguments. The solved arguments are stamped back onto the call node
    # (`expr.type_args`) so codegen + the coroutine transform monomorphize an
    # inferred call byte-identically to an explicit one.
    def _infer_tp_name(self, t, names):
        """If `t` is a bare reference to a type parameter in `names`, its name."""
        if t is None:
            return None
        if t.kind == TypeKind.TYPE_PARAM and t.type_param_name in names:
            return t.type_param_name
        if (t.kind == TypeKind.STRUCT and not t.type_args
                and t.struct_name in names):
            return t.struct_name
        return None

    def _infer_types_equal(self, a, b) -> bool:
        """Structural equality used to detect a conflicting inference for one
        parameter (two different concrete solutions)."""
        try:
            return (self._type_key(self._resolve_type(a))
                    == self._type_key(self._resolve_type(b)))
        except Exception:
            return self._type_key(a) == self._type_key(b)

    def _unify_infer(self, pattern, actual, names, out):
        """Structurally match abstract `pattern` (which may mention parameter
        `names`) against concrete `actual`, recording solutions in `out`
        (name -> SawType). A parameter bound twice to unequal types records a
        conflict under `out['__conflict__']`. Best-effort: an unconstrained
        position is simply skipped (never an error here)."""
        if pattern is None or actual is None:
            return
        nm = self._infer_tp_name(pattern, names)
        if nm is not None:
            prev = out.get(nm)
            if prev is None:
                out[nm] = actual
            elif not self._infer_types_equal(prev, actual):
                out.setdefault('__conflict__', {})[nm] = (prev, actual)
            return
        pk = pattern.kind
        if pk == TypeKind.FUNCTION and actual.kind == TypeKind.FUNCTION:
            for pp, ap in zip(pattern.param_types or [], actual.param_types or []):
                self._unify_infer(pp, ap, names, out)
            self._unify_infer(pattern.func_return_type, actual.func_return_type,
                              names, out)
            return
        if pk == TypeKind.OPTIONAL:
            # A bare argument auto-wraps to the optional parameter (design 30), so
            # a non-optional actual constrains the payload directly (`f(5)` into
            # `f(x: T?)` solves `T = Int`). A `None` actual carries no type.
            if actual.kind == TypeKind.OPTIONAL:
                inner = actual.inner_type
            elif actual.is_none_literal():
                inner = None
            else:
                inner = actual
            self._unify_infer(pattern.inner_type, inner, names, out)
            return
        if pk in (TypeKind.REFERENCE, TypeKind.POINTER):
            inner = actual.inner_type if actual.kind == pk else None
            self._unify_infer(pattern.inner_type, inner, names, out)
            return
        if pk == TypeKind.ARRAY:
            inner = (actual.array_element_type
                     if actual.kind == TypeKind.ARRAY else None)
            self._unify_infer(pattern.array_element_type, inner, names, out)
            # design 148 — the one inference case for a const parameter: a
            # `[T; N]` PARAMETER binds `N` from the argument's length, so
            # `func sum(xs: [Int; N]) -> Int` is callable on a `[Int; 4]`
            # without writing `<4>`. Only a length that is exactly the bare
            # parameter name participates; arithmetic (`[T; N + 1]`) is not
            # solved backwards, which would need a real constraint solver
            # rather than the structural matcher this is.
            if (actual.kind == TypeKind.ARRAY
                    and actual.array_size is not None
                    and pattern.array_size is None):
                se = pattern.array_size_expr
                if isinstance(se, Identifier) and se.name in names:
                    bound = SawType(TypeKind.CONST_VALUE,
                                    const_value=actual.array_size)
                    prev = out.get(se.name)
                    if prev is None:
                        out[se.name] = bound
                    elif not self._infer_types_equal(prev, bound):
                        out.setdefault('__conflict__', {})[se.name] = (prev, bound)
            return
        if pk == TypeKind.TUPLE and actual.kind == TypeKind.TUPLE:
            for pe, ae in zip(pattern.element_types or [],
                              actual.element_types or []):
                self._unify_infer(pe, ae, names, out)
            return
        if pk in (TypeKind.STRUCT, TypeKind.ENUM) and pattern.type_args:
            a_args = actual.type_args or []
            for i, pa in enumerate(pattern.type_args):
                aa = a_args[i] if i < len(a_args) else None
                self._unify_infer(pa, aa, names, out)
            return

    def _infer_snapshot(self):
        """Capture the mutable typechecker state the inference pre-pass touches so
        its trial argument checks (which discover argument types) can be rolled
        back — the real argument-checking loop runs downstream. A throwaway
        suspend node (key=None) catches effect edges recorded at the enclosing
        node level; per-instantiation queues are truncated on restore."""
        snap = (dict(self.moved_bindings), self.current_scope,
                len(self._suspend_stack), len(self._poly_call_edges),
                len(self._pending_mono), len(self._pending_method_mono),
                len(self._pending_generic_struct_method_mono),
                set(self._mono_built))
        self._suspend_stack.append(_SandboxNode(key=None, edges=[], direct=[]))
        return snap

    def _infer_restore(self, snap):
        (moved, scope, stack_n, poly_n, pm_n, pmm_n, pgm_n, mono_built) = snap
        self.moved_bindings = moved
        self.current_scope = scope
        del self._suspend_stack[stack_n:]
        del self._poly_call_edges[poly_n:]
        del self._pending_mono[pm_n:]
        del self._pending_method_mono[pmm_n:]
        del self._pending_generic_struct_method_mono[pgm_n:]
        self._mono_built = mono_built

    def _infer_label_mapping(self, expr, logical_param_names, default_values):
        """Design 105: for a LABELED call, the source-arg -> logical-parameter
        binding (design 66) so inference pairs each argument with the parameter
        it actually names. Returns None (positional identity) when the call has
        no labels or the binding fails (the real binding check downstream emits
        the diagnostic)."""
        if not self._call_has_labels(expr):
            return None
        mapping, err = self._compute_binding(
            logical_param_names, default_values, expr.arguments)
        return None if err is not None else mapping

    def _solve_call_type_args(self, type_params, abstract_params, expr, mapping,
                              base_subst, provided_type_args, what, line, column,
                              silent=False, known_arg_types=None,
                              default_values=None):
        """Infer this call's own generic type arguments (design 93 + 105).

        `abstract_params` are the callee's LOGICAL parameter types (receiver
        excluded), which may mention both the enclosing struct's type params
        (already concrete in `base_subst`) and this call's own `type_params`.
        Returns a complete substitution map (base_subst ∪ solved own params) or
        `None` after emitting a diagnostic. Leading `provided_type_args` pin their
        parameters explicitly (a partial prefix is allowed; explicit wins).

        `known_arg_types`, when given (the overload path already type-checked the
        arguments once), supplies each non-closure argument's type so the solver
        does NOT re-check it — avoiding a double `move`/effect record on the real
        state (the sandbox rolls back only what it touches).

        Design 105: `mapping` (source-arg index -> logical parameter index, or
        None for positional identity) makes inference honor labeled/out-of-order
        calls — arguments are paired with parameters BY LABEL before unification.
        A LATER argument that pins a parameter an earlier one gates is solved by
        the FIXPOINT (repeat passes until no new solution; bounded by param
        count; closures still solved after non-closure args each pass). `silent`
        suppresses the failure diagnostics so an overload candidate can be tried
        without emitting an error when it does not solve."""
        own = list(type_params)
        own_names = {tp.name for tp in own}
        out: Dict[str, SawType] = {}
        for tp, ta in zip(own, provided_type_args or []):
            out[tp.name] = self._resolve_type(ta)
        remaining = own_names - set(out.keys())
        if not remaining:
            return {**base_subst, **out}

        snap = self._infer_snapshot()
        try:
            # Fixpoint over the argument list (design 105): each pass runs the
            # non-closure args then the closures; a parameter gated by an argument
            # to its RIGHT is picked up on the next pass once that argument's own
            # parameters are known. Bounded by the parameter count — every pass
            # that changes anything solves at least one new name.
            max_passes = max(1, len(own))
            for _ in range(max_passes):
                before = len(out)
                # Phase 1: non-closure arguments pin the parameters they mention.
                # Unify against `base_subst` only (NOT the growing `out`) so two
                # arguments binding one parameter to unequal types still record a
                # conflict rather than silently comparing concrete-vs-concrete.
                for i, arg in enumerate(expr.arguments):
                    if isinstance(arg.value, ClosureExpr):
                        continue
                    p = mapping[i] if mapping is not None else i
                    if p >= len(abstract_params):
                        continue
                    if known_arg_types is not None:
                        at = known_arg_types[i]
                    else:
                        at = self._check_expression(arg.value)
                    if at is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          at, remaining, out)
                # Phase 2: closures. Their parameter types are now concrete (from
                # the struct and from already-solved params); the inferred RETURN
                # type solves any remaining parameter (`map<U>`'s `U`).
                for i, arg in enumerate(expr.arguments):
                    if not isinstance(arg.value, ClosureExpr):
                        continue
                    p = mapping[i] if mapping is not None else i
                    if p >= len(abstract_params):
                        continue
                    expected = abstract_params[p].substitute({**base_subst, **out})
                    ct = self._check_closure(arg.value, expected,
                                             as_call_argument=True)
                    if ct is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          ct, remaining, out)
                if '__conflict__' in out or len(out) == before:
                    break
            # Design 108: a parameter with a DEFAULT VALUE that is OMITTED at this
            # call drives inference from the default's OWN type when the parameter
            # it types is otherwise undetermined — `f(1)` with `b: T = 0` infers
            # `T = Int`. Consulted only AFTER argument-driven solving (a supplied
            # argument always wins), and only for a still-unsolved name, so it is
            # the last resort before the underdetermined error. The trial check is
            # inside the inference snapshot, so the default's moves/effects roll
            # back (they already tainted the callee at its declaration).
            if default_values and '__conflict__' not in out and (own_names - set(out.keys())):
                bound = (set(mapping) if mapping is not None
                         else set(range(len(expr.arguments))))
                for p, dv in enumerate(default_values):
                    if dv is None or p in bound or p >= len(abstract_params):
                        continue
                    if not (own_names - set(out.keys())):
                        break
                    dt = self._check_expression(dv)
                    if dt is not None:
                        self._unify_infer(abstract_params[p].substitute(base_subst),
                                          dt, remaining, out)
        finally:
            self._infer_restore(snap)

        conflict = out.pop('__conflict__', None)
        if conflict:
            if silent:
                return None
            nm = sorted(conflict.keys())[0]
            a, b = conflict[nm]
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot infer type argument `{nm}` for {what}: it is required to "
                f"be both `{a}` and `{b}`",
                line, column,
                hint=f"give the type argument(s) explicitly")
            return None
        for tp in own:
            if tp.name in out:
                continue
            if tp.default is not None:
                out[tp.name] = self._resolve_type(tp.default)
            else:
                if silent:
                    return None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot infer type argument `{tp.name}` for {what}",
                    line, column,
                    hint=f"give the type argument(s) explicitly, "
                         f"e.g. `{what.split('`')[1] if '`' in what else '...'}"
                         f"<{tp.name}=...>`")
                return None
        return {**base_subst, **out}

    def _check_generic_call_defaults(self, expr, func_info, instantiated_param_types,
                                     mapping):
        """Design 108: validate each OMITTED default-valued parameter of a generic
        call against its INSTANTIATED parameter type.

        The design-53 declaration-time check runs against the abstract type
        parameter and is a no-op for a generic function, so a
        `func f<T>(a: Int, b: T = 0)` never has its `0` checked against a concrete
        `T` until a call fixes `T`. This is that check, anchored at the CALL: it
        turns the former `list index out of range` codegen ICE (a call emitted
        with too few args, or a non-coercible literal materialized at the wrong
        LLVM type) into a clean, actionable diagnostic. A bare integer literal
        default follows Saw's literal rules — it adopts an integer instantiation
        (range-checked) and is rejected against a non-integer one (a bare `0` does
        not become a `Float`). Side-effect-free: the default's own moves/effects
        already tainted the callee at its declaration, so a non-literal default's
        trial check is sandboxed."""
        dvals = func_info.default_values or []
        if not any(dv is not None for dv in dvals):
            return
        bound = (set(mapping) if mapping is not None
                 else set(range(len(expr.arguments))))
        for p, dv in enumerate(dvals):
            if dv is None or p in bound or p >= len(instantiated_param_types):
                continue
            expected = instantiated_param_types[p]
            if expected is None:
                continue
            pname = (func_info.param_names[p]
                     if p < len(func_info.param_names) else f"#{p}")
            rt = self._resolve_type(expected)
            ut = self._get_underlying_type(rt) if rt is not None else None
            # Bare integer literal (the `b: T = 0` case): adopt an integer
            # instantiation with a range check; reject a non-integer one.
            if isinstance(dv, IntLiteral) and getattr(dv, 'suffix', None) is None:
                if ut is not None and ut.kind in self._FIXED_INT_RANGES:
                    lo, hi = self._FIXED_INT_RANGES[ut.kind]
                    if not (lo <= dv.value <= hi):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"default value {dv.value} for parameter `{pname}` does "
                            f"not fit `{expected}` (range {lo}..={hi})",
                            expr.line, expr.column,
                            hint="the default is checked against the instantiated "
                                 "type at this call")
                    continue
                if ut is not None and ut.kind in (TypeKind.INT, TypeKind.UINT):
                    continue
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"default value for parameter `{pname}` has type `Int` but the "
                    f"parameter is instantiated as `{expected}` at this call",
                    expr.line, expr.column,
                    hint="a bare integer literal does not adopt a non-integer type; "
                         "pass the argument explicitly here")
                continue
            # General default: sandbox the trial type check (no move/effect leak).
            snap = self._infer_snapshot()
            try:
                dt = self._check_expression(dv)
            finally:
                self._infer_restore(snap)
            if dt is not None and not self._arg_type_ok(None, dt, rt, allow_wrap=False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"default value for parameter `{pname}` has type `{dt}` but the "
                    f"parameter is instantiated as `{expected}` at this call",
                    expr.line, expr.column,
                    hint="the default is checked against the instantiated type at "
                         "this call")

    def _check_type_param_bounds(self, type_params, type_map, line, column):
        """Verify each parameter's concrete binding in `type_map` satisfies the
        parameter's trait bounds, naming the concrete (possibly inferred) type in
        the failure. Mirrors the free-function bound checks; used by the generic
        METHOD path (both explicit and inferred), which previously did none."""
        for tp in type_params:
            resolved_arg = type_map.get(tp.name)
            if resolved_arg is None:
                continue
            concrete_name = None
            if resolved_arg.kind == TypeKind.STRUCT:
                concrete_name = resolved_arg.struct_name
            elif resolved_arg.kind == TypeKind.ENUM:
                concrete_name = resolved_arg.enum_name
            in_scope_param = (resolved_arg.kind == TypeKind.STRUCT
                              and resolved_arg.struct_name
                              in getattr(self, 'current_type_params', {}))
            for bound in tp.bounds:
                if bound == "Copy":
                    ok = self._type_satisfies_copy_bound(resolved_arg)
                else:
                    if bound not in ("Send", "Sync") and self.get_trait_info(bound) is None:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{bound}` in type parameter bound",
                            line, column)
                        continue
                    ok = self._bound_satisfied(resolved_arg, bound)
                if ok:
                    if concrete_name and not in_scope_param:
                        for an, at in self.namespace.get_type_assignments(
                                concrete_name, bound).items():
                            type_map[an] = at
                    continue
                if bound == "Copy":
                    hint = ("use a trivially-copyable type, or one implementing "
                            "ImplicitCopy/ExplicitCopy")
                elif in_scope_param:
                    hint = (f"add the bound to the enclosing signature: "
                            f"`<{resolved_arg.struct_name}: {bound}>`")
                elif concrete_name:
                    hint = f"add `extension {concrete_name}: {bound} {{ ... }}`"
                else:
                    hint = None
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                    line, column, hint=hint)

    def _check_overloaded_function_call(self, expr, candidates):
        """Resolve and check a call to an overloaded free function (design 55).
        Design 105: a generic overload may be selected by type-argument
        inference when no concrete candidate matches."""
        arg_types = self._overload_arg_types(expr)
        func_info, mapping = self._resolve_overload(
            expr.name, candidates, arg_types, self._has_explicit_type_args(expr),
            is_method=False, line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst={})
        if func_info is None:
            return None
        # Concrete overload: stamp its codegen symbol so codegen calls the right
        # definition. A generic overload keeps type-argument instantiation naming
        # (routed through the normal generic path), so it is left unstamped.
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        self._stamp_overload_plan(expr, func_info.param_names, mapping)
        # Single chokepoint: the effect edge is recorded to the RESOLVED callee.
        self._effect_call_function(func_info, expr.name, expr.line)
        if func_info.type_params:
            type_map = {}
            for tp, ta in zip(func_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            # Design 105: inferred (or explicit) type args are bound-checked.
            self._check_type_param_bounds(
                func_info.type_params, type_map, expr.line, expr.column)
            # design 70 (A5): record the deferred poly-call edge so a suspending
            # instantiation taints the caller / drives (mirrors the singleton
            # generic path), only when the args are fully concrete.
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a)
                   for a in resolved_args):
                self._effect_record_poly_call(
                    expr.name, resolved_args, f"`{expr.name}`", expr.line)
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = (func_info.return_type.substitute(type_map)
                           if func_info.return_type else func_info.return_type)
            # Design 108: an omitted default on the winning generic overload is
            # checked against its instantiated type here too (mirrors the singleton
            # generic path), so `g<Float>(1)` selecting a `b: T = 0` overload is a
            # clean error rather than a codegen ICE.
            self._check_generic_call_defaults(expr, func_info, param_types, mapping)
        else:
            param_types = func_info.param_types
            return_type = func_info.return_type
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_overloaded_method_call(self, expr, struct_name, candidates,
                                      obj_type, type_subst):
        """Resolve and check a call to an overloaded instance method (design 55).

        Mirrors the singleton method tail but resolves the callee first and
        checks each argument exactly once (so a `move`/mutating argument is not
        double-processed). Design 105: a generic method overload may be selected
        by type-argument inference (the struct's own type substitution
        `type_subst` seeds the solve as the base substitution)."""
        arg_types = self._overload_arg_types(expr)
        method_info, mapping = self._resolve_overload(
            f"{struct_name}.{expr.method_name}", candidates, arg_types,
            self._has_explicit_type_args(expr), is_method=True,
            line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst=type_subst or {})
        if method_info is None:
            return None
        if method_info.mangled_name:
            expr.resolved_symbol = method_info.mangled_name
        offset = self._overload_cand_offset(method_info, is_method=True)
        self._stamp_overload_plan(expr, method_info.param_names[offset:], mapping)
        # Single chokepoint: effect edge to the resolved method.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        # Fold the method's OWN generic type params (inferred or explicit) into
        # the substitution alongside the struct's args (design 105).
        full_subst = dict(type_subst) if type_subst else {}
        if method_info.type_params:
            for tp, ta in zip(method_info.type_params, expr.type_args or []):
                full_subst[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                method_info.type_params, full_subst, expr.line, expr.column)
        param_types = method_info.param_types[offset:]
        if full_subst:
            param_types = [t.substitute(full_subst) if t is not None else t
                           for t in param_types]
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        # `&var self` method may not be called on an immutable binding (L11).
        if getattr(method_info, "self_mutable", False) and not method_info.is_init:
            imm_root = self._assign_target_immutable_struct_root(expr.object)
            if imm_root is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot call `&var self` method `{expr.method_name}` on "
                    f"immutable variable `{imm_root}`",
                    expr.line, expr.column,
                    hint="consider using `var` instead of `let` to make it mutable",
                )
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, method_info.param_names[offset:])
        self._check_call_exclusivity(
            [a.value for a in expr.arguments], aligned_types,
            receiver=expr.object if not method_info.is_init else None,
            receiver_mutable=method_info.self_mutable,
            param_names=aligned_names,
        )
        return_type = method_info.return_type
        if full_subst and return_type is not None:
            return_type = return_type.substitute(full_subst)
        return return_type

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call."""
        # Atomic construction (design 41 item 4): `Atomic(<int>)`. A compiler-
        # known positional construction — the general struct-init path requires
        # named arguments, so intercept it here. v1 supports Atomic<Int> only.
        if expr.name == "Atomic" and not expr.type_args:
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`Atomic(...)` takes exactly one positional Int argument",
                    expr.line, expr.column
                )
                return None
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None and self._get_underlying_type(arg_type).kind != TypeKind.INT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`Atomic(...)` expects an Int, got `{arg_type}`",
                    expr.line, expr.column
                )
            expr.is_atomic_construct = True
            return SawType(TypeKind.STRUCT, struct_name="Atomic",
                           type_args=[SawType(TypeKind.INT)])

        # UnsafeMemory construction (design 46): `UnsafeMemory(<int>)` — a
        # compiler-known one-word wrapper over a fixed address. Like Atomic it is
        # positional, so intercept before the named struct-init path. The `T`/
        # `Use` come from the surrounding declared type (a static's annotation),
        # so a bare construction yields an un-parameterized `UnsafeMemory` that is
        # compatible with any `UnsafeMemory<T, Use>` target (the struct-arg
        # comparison treats an empty arg list as "matches any instantiation").
        # Explicit `UnsafeMemory<T, Use>(<int>)` is also accepted.
        if expr.name == "UnsafeMemory":
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`UnsafeMemory(...)` takes exactly one positional Int address",
                    expr.line, expr.column
                )
                return None
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None and self._get_underlying_type(arg_type).kind not in (
                    TypeKind.INT, TypeKind.UINT):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`UnsafeMemory(...)` expects an Int address, got `{arg_type}`",
                    expr.line, expr.column
                )
            expr.is_unsafe_mem_construct = True
            if expr.type_args:
                resolved = [self._resolve_type(t) for t in expr.type_args]
                result = SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                                 type_args=resolved)
                self._validate_unsafe_memory_type(result, expr.line, expr.column)
                return result
            return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory")

        if expr.name == "print":
            # design 137: `print(fmt, a, b)` renders each argument through its
            # own `Printable.format` into the `{}` slots. Monomorphized, not
            # varargs: arity is checked here against the literal format string.
            if len(expr.arguments) > 1:
                self._check_format_call("print", expr, expr.arguments[1:])
                return SawType(TypeKind.VOID)
            for arg in expr.arguments:
                arg_type = self._check_expression(arg.value)
                # Freestanding has no dtoa: Float printing requires the hosted
                # profile (see design 20 item 2/4).
                if (self.freestanding and arg_type is not None
                        and arg_type.kind == TypeKind.FLOAT):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "Float formatting requires the hosted profile; "
                        "freestanding `print` supports integers, Bool, and String only",
                        arg.value.line, arg.value.column
                    )
                # design 132 unit D: the same renderability question interpolation
                # asks. Codegen can lower a builtin or a Printable `to_string()`
                # and nothing else, so anything else was an ICE here (DF-128d /
                # DF-129a).
                elif arg_type is not None:
                    self._check_renderable_operand(arg_type, arg.value,
                                                   "cannot print")
                    # design 135: a builtin argument formats into stack scratch,
                    # but a user `Printable` is rendered through the `to_string()`
                    # the compiler synthesizes here — an owned String the program
                    # never asked for. `print("{}", v)` streams the same bytes
                    # through the value's own `format` and allocates nothing.
                    if (self._hidden_alloc_gate()
                            and self._get_underlying_type(arg_type).kind
                            not in self._RENDERABLE_BUILTIN_KINDS):
                        self._hidden_alloc_error(
                            f"`print` renders `{arg_type}` through `to_string()`, "
                            f"which allocates a String",
                            arg.value.line, arg.value.column,
                            hint="write `print(\"{}\", value)` — the "
                                 "format-argument spelling streams the value "
                                 "through its own `format` into stack scratch")
            return SawType(TypeKind.VOID)
        if expr.name == "panic":
            # design 49 item 1: panic(message: String) -> Never. Emits `message`
            # (plus a newline) through the saw_panic seam and does not return.
            # Its type is NEVER (the bottom type): control never continues past
            # it, so a function body ending in `panic(...)` needs no return value
            # and the value is assignable to any expected type.
            if len(expr.arguments) > 1:
                # design 137: `panic("out of {}", what)` assembles the message
                # in stack scratch, so a panic can still say what happened with
                # the allocator refusing everything.
                self._check_format_call("panic", expr, expr.arguments[1:])
            elif len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`panic` takes a String message, optionally followed by "
                    "format arguments for its `{}` placeholders",
                    expr.line, expr.column
                )
            else:
                msg_type = self._check_expression(expr.arguments[0].value)
                if (msg_type is not None
                        and self._get_underlying_type(msg_type).kind != TypeKind.STRING):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`panic` expects a String message, got `{msg_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
            return SawType(TypeKind.NEVER)
        if expr.name == "assert":
            # design 49 item 2: assert(cond: Bool, message: String). A no-op when
            # `cond` is true; on false it panics with
            # "assertion failed: {message} (line N)" through the same seam (the
            # call-site line N is available on the AST node, so it is included).
            # `debug_assert` is deferred — there is no build-profile split yet.
            if len(expr.arguments) > 2:
                # design 137: `assert(ok, "want {} got {}", a, b)` — the message
                # is assembled only on the failing branch, and only then.
                cond_type = self._check_expression(expr.arguments[0].value)
                if (cond_type is not None
                        and self._get_underlying_type(cond_type).kind != TypeKind.BOOL):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a Bool condition, got `{cond_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
                self._check_format_call("assert", expr, expr.arguments[2:],
                                        fmt_index=1)
            elif len(expr.arguments) != 2 or any(a.name is not None for a in expr.arguments):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`assert` takes a Bool condition and a String message, "
                    "optionally followed by format arguments for its `{}` "
                    "placeholders",
                    expr.line, expr.column
                )
            else:
                cond_type = self._check_expression(expr.arguments[0].value)
                if (cond_type is not None
                        and self._get_underlying_type(cond_type).kind != TypeKind.BOOL):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a Bool condition, got `{cond_type}`",
                        expr.arguments[0].value.line, expr.arguments[0].value.column
                    )
                msg_type = self._check_expression(expr.arguments[1].value)
                if (msg_type is not None
                        and self._get_underlying_type(msg_type).kind != TypeKind.STRING):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`assert` expects a String message, got `{msg_type}`",
                        expr.arguments[1].value.line, expr.arguments[1].value.column
                    )
            return SawType(TypeKind.VOID)
        if expr.name in ("__saw_test_suspend", "__saw_suspend"):
            # design 22: `__saw_test_suspend` — compiler-known synthetic suspension
            # point, effect-only (feeds the suspendability inference; codegen is a
            # no-op; NO state-machine transform — that is design-22's scope guard).
            # design 44: `__saw_suspend` — the coroutine-transform state boundary. It
            # is ALSO an effect source, but inside a DRIVEN function (reached from
            # a `__saw_drive` site) the transform splits the body at it. Outside any
            # driven closure it lowers to the same no-op, so a lone `__saw_suspend`
            # behaves exactly like `__saw_test_suspend` (effect-suspending, runs).
            # Both take no arguments and return Void.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{expr.name}` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            self._effect_direct_source(expr.name, expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "yield_now":
            # design 45 item 4: cooperative yield — a real suspension point that
            # hands control back to the executor and is immediately re-ready. Like
            # `__saw_suspend`, it is an effect source and a transform state boundary,
            # but it carries a "ready" wake reason (the executor reschedules it at
            # once). Takes no arguments; returns Void.
            #
            # design 114: the bare `yield_now` name is a stdlib-INTERNAL intrinsic.
            # std bodies (channel/net/taskgroup — checked with `_checking_builtins`)
            # and synthesized coro output reach it directly. User code reaches the
            # yield only through std.task's `public func yield_now()` wrapper, which
            # is un-gated by `import std.task` (its name then sits in
            # `directly_accessible`); a call to that wrapper lands HERE with the
            # name accessible, so it lowers to the exact same intrinsic (no extra
            # frame — the wrapper is transparent). A bare, un-imported use is a clean
            # error naming the replacement.
            # `--runtime-build` (design 113b) loads NO std, so std.task does not
            # exist to import — the bare intrinsic stays reachable there (a seam
            # body that suspends is caught by the separate `@export`-suspend rule).
            if not (getattr(self, '_checking_builtins', False)
                    or getattr(self, 'runtime_build', False)
                    or self._in_synthesized_context()
                    or "yield_now" in self.namespace.directly_accessible):
                self._error(
                    ErrorKind.UNDEFINED_FUNCTION,
                    "`yield_now` is a stdlib-internal cooperative-yield intrinsic "
                    "and cannot be called bare",
                    expr.line, expr.column,
                    hint="add `import std.task` and call its public `yield_now()`")
                return SawType(TypeKind.VOID)
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`yield_now` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            self._effect_direct_source("yield_now", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_io_park":
            # design 76 (A4): the IO reactor's suspension boundary. Like
            # `yield_now`, a suspension point + transform state boundary, but it
            # carries an IO-PARK wake reason (a negative sentinel): the executor
            # parks in the reactor (kqueue/epoll) until an fd is ready rather than
            # busy-requeuing. Emitted only inside std/net.saw's would-block loops;
            # reached as a plain call (no executor) it is a no-op. No arguments.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_io_park` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            self._effect_direct_source("__saw_io_park", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "io_wait":
            # design 76 (A4): the user-facing IO suspension point. `io_wait(fd,
            # write)` registers `fd` with the reactor for read (write==0) or write
            # (write==1) interest and parks the task until the fd is ready. A real
            # suspension source (so callers suspend and a suspending `main` gets the
            # entry executor). Two Int args; returns Void.
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`io_wait` takes exactly two positional Int arguments "
                    f"(fd, write), but {len(expr.arguments)} were given",
                    expr.line, expr.column)
            else:
                for a in expr.arguments:
                    at = self._check_expression(a.value)
                    if at is not None and self._get_underlying_type(at).kind != TypeKind.INT:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`io_wait` expects Int arguments, got `{at}`",
                            expr.line, expr.column)
            self._effect_direct_source("io_wait", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "io_unwait":
            # DF-134a: the inverse of `io_wait` — drop the readiness interest
            # `io_wait(fd, write)` armed. NOT a suspension source: it neither
            # parks nor yields, so a `sync` caller may use it and a park loop can
            # call it on the way out of its cancellation exit. Two Int args,
            # returns Void. Idempotent at the seam, so calling it when nothing is
            # armed is well defined.
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`io_unwait` takes exactly two positional Int arguments "
                    f"(fd, write), but {len(expr.arguments)} were given",
                    expr.line, expr.column)
            else:
                for a in expr.arguments:
                    at = self._check_expression(a.value)
                    if at is not None and self._get_underlying_type(at).kind != TypeKind.INT:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`io_unwait` expects Int arguments, got `{at}`",
                            expr.line, expr.column)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_blk_start":
            # design 103 (A6): the blocking-extern offload START intrinsic, emitted
            # by the coro transform. Its argument is syntactically a call to the
            # blocking extern (`slow(arg)`), but the offload does NOT call it inline —
            # it hands the extern's ADDRESS + the arg to the runtime thread. So we
            # type-check only the inner argument expressions and deliberately do NOT
            # record the blocking suspension effect (the real suspension is the
            # `io_wait` the transform emits between start and take, which keeps the
            # synthesized `resume` method suspension-free of the blocking source).
            # Returns the job handle as an Int. Compiler-generated only.
            if len(expr.arguments) == 1:
                inner = expr.arguments[0].value
                for a in getattr(inner, 'arguments', []):
                    self._check_expression(a.value)
            return SawType(TypeKind.INT)
        if expr.name in ("__saw_blk_done", "__saw_blk_pipe_fd", "__saw_blk_take"):
            # design 103 (A6): the offload done-poll / pipe-fd / join+take intrinsics.
            # Each takes the job handle (Int) and returns an Int (a flag, an fd, or —
            # for `__saw_blk_take` — the v1 `(Int) -> Int` extern's result). None is a
            # suspension source. Compiler-generated only.
            if len(expr.arguments) == 1:
                self._check_expression(expr.arguments[0].value)
            return SawType(TypeKind.INT)
        if expr.name == "sleep":
            # design 45 item 4: cooperative timed wait — a suspension point that
            # carries a "sleep for N ms" wake reason. The executor sleeps that long
            # (the simplest correct hosted timer) before resuming. Takes one Int
            # (milliseconds); returns Void.
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sleep` takes exactly one positional Int argument "
                    f"(milliseconds)", expr.line, expr.column)
            else:
                ms_type = self._check_expression(expr.arguments[0].value)
                if ms_type is not None and self._get_underlying_type(ms_type).kind != TypeKind.INT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`sleep` expects an Int (milliseconds), got `{ms_type}`",
                        expr.line, expr.column)
            self._effect_direct_source("sleep", expr.line)
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_box_data":
            # design 52b item 2: extract the data word (i8*) of a `Box<any T>` fat
            # pointer — the address of the erased heap payload. The synthesized
            # `__spawn_<f>` uses it to point a `TaskHandle` at the boxed frame's
            # `__result` / `__cancel` slots. Compiler-generated only; the argument
            # is a reference to the box. NOT a suspension source.
            if len(expr.arguments) == 1:
                self._check_expression(expr.arguments[0].value)
            return SawType(TypeKind.POINTER,
                           inner_type=SawType(TypeKind.INT8))
        if expr.name == "cancelled":
            # design 52b item 3: read the CURRENT task's cooperative cancel flag.
            # Inside a driven/spawned body the coro transform rewrites this to the
            # frame's `__cancel` word; outside any frame it lowers to `false` (no
            # task to cancel). Takes no arguments; returns Bool; NOT a suspension
            # source (a cancel check must be callable in any context).
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`cancelled` takes no arguments, but {len(expr.arguments)} "
                    f"were given", expr.line, expr.column)
            return SawType(TypeKind.BOOL)
        if expr.name in ("__saw_drive", "__saw_drive_steps"):
            # design 44: the test-only executor entry. `__saw_drive(f(args))` creates
            # a frame for the suspending call `f(args)`, drives it to completion,
            # and yields f's result; `__saw_drive_steps(f(args))` yields the number of
            # suspensions observed (an Int). It ABSORBS the callee's suspension —
            # the enclosing function does NOT become suspending — which is how a
            # non-suspending `main` can drive a coroutine with no executor yet.
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`{expr.name}(...)` takes exactly one positional argument: a "
                    f"call to a suspending function",
                    expr.line, expr.column
                )
                return None
            inner = expr.arguments[0].value
            from ast_nodes import FunctionCall as _FC, MethodCall as _MC
            if not isinstance(inner, (_FC, _MC)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{expr.name}(...)` expects a direct call to a suspending "
                    f"function or method, e.g. `{expr.name}(work())` or "
                    f"`{expr.name}(obj.step())`",
                    expr.line, expr.column
                )
                return None
            mode = "value" if expr.name == "__saw_drive" else "steps"
            # Before anything reads the callee: put the AUTHORED name back if an
            # earlier pass over this same AST already monomorphized it.
            self._restore_authored_call(inner)
            # Type-check the inner call inside an absorbing scope so its suspend
            # edge does not taint the caller. This also stamps inner.resolved_type
            # and validates the argument types.
            sentinel = self._effect_absorb_scope()
            inner_type = self._check_expression(inner)
            self._effect_unabsorb(sentinel)
            if isinstance(inner, _MC):
                # design 45 Part 0c: driving a suspending method. The receiver's
                # struct type names the driven-method root; the transform builds a
                # frame holding a `__recv` pointer into the receiver's storage.
                recv_type = getattr(inner.object, 'resolved_type', None)
                struct_name = getattr(recv_type, 'struct_name', None) if recv_type else None
                if struct_name is None:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.name}(...)` on a method requires a concrete struct "
                        f"receiver", expr.line, expr.column)
                    return inner_type if inner_type is not None else SawType(TypeKind.VOID)
                # design 70 (A5): a generic method (its own type params) is
                # monomorphized to a concrete method before frame synthesis.
                # design 74 (A5-rest, shape 2): a method on a GENERIC struct
                # (`Holder<T>`) driven for a concrete receiver `Holder<Int>` is
                # monomorphized over the STRUCT's type params so the frame's
                # `__recv` gets a concrete layout.
                struct_sym = self.namespace.lookup_struct(struct_name)
                struct_is_generic = (
                    struct_sym is not None and bool(struct_sym.type_params)
                    and bool(getattr(recv_type, 'type_args', None)))
                # design 104 item 3: a method that is BOTH struct-generic and
                # method-generic routes to the generic-STRUCT path (it monomorphizes
                # over the struct's type params AND the method's own type args). Only
                # a method-generic method on a NON-generic struct takes the
                # method-only path.
                if getattr(inner, 'type_args', None) and not struct_is_generic:
                    self._drive_generic_method(inner, struct_name, mode, expr)
                elif struct_is_generic:
                    self._drive_generic_struct_method(
                        inner, struct_name, recv_type, mode, expr)
                else:
                    # design 95: pass the resolved-signature symbol so an
                    # overloaded suspending method driven directly keys its own frame.
                    self._effect_record_driven_method(
                        struct_name, inner.method_name, mode,
                        resolved_symbol=getattr(inner, 'resolved_symbol', None))
            else:
                # design 70 (A5): driving a generic free function. Monomorphize the
                # instantiation to a concrete function keyed by the mangled symbol,
                # record it as the driven root, and rewrite the inner call so the
                # coroutine transform sees an ordinary non-generic call.
                if getattr(inner, 'type_args', None):
                    resolved_args = [self._resolve_type(a) for a in inner.type_args]
                    if not all(self._is_concrete_type(a) for a in resolved_args):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`{expr.name}(...)` of a generic function requires "
                            f"concrete type arguments (cannot drive an instantiation "
                            f"whose type arguments are themselves type parameters)",
                            inner.line, inner.column)
                    else:
                        # Design 105: drive from the resolved overload's `$OL$`
                        # base template when present (generic overload), else the
                        # plain name (lone generic).
                        tmpl = getattr(inner, 'resolved_symbol', None) or inner.name
                        mangled = self._effect_queue_fn_mono(tmpl, resolved_args)
                        self._effect_record_driven(mangled, mode)
                        inner.name = mangled
                        inner.type_args = None
                else:
                    self._effect_record_driven(inner.name, mode)
            if expr.name == "__saw_drive_steps":
                return SawType(TypeKind.INT)
            return inner_type if inner_type is not None else SawType(TypeKind.VOID)
        if expr.name == "spawn":
            return self._check_spawn(expr)
        if expr.name == "sizeof":
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sizeof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`sizeof` requires exactly one type argument: sizeof<T>()",
                    expr.line, expr.column
                )
                return None
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)
        if expr.name == "alignof":
            # Sibling of sizeof<T>(): the ABI alignment (in bytes) of type T for
            # the compilation target. Same plumbing — a typechecker special-case
            # that validates arity/type-arg and yields Int; codegen lowers it via
            # llvmlite target data. Used by alloc-layer stdlib (Vector) to request
            # correctly-aligned buffers from the allocator instead of a hardcoded
            # constant.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`alignof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`alignof` requires exactly one type argument: alignof<T>()",
                    expr.line, expr.column
                )
                return None
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)
        if expr.name == "__saw_deinit_in_place":
            # Compiler-internal drop intrinsic for stdlib container code: run the
            # cleanup (drop glue) for the value at an UnsafePointer<T>, in place.
            # Manual `deinit()` calls are banned language-wide; this escape hatch
            # is gated to `deinit` method bodies so a container (Vector/Map) can
            # release its live elements before freeing its buffer, and cannot be
            # used as a general user-facing manual-deinit unlock.
            cur = getattr(self, 'current_method', None)
            if cur is None or getattr(cur, 'name', None) != "deinit":
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`__saw_deinit_in_place` is a compiler-internal intrinsic usable "
                    "only inside a `deinit` method body",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_deinit_in_place` takes exactly one pointer argument, but "
                    f"{len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            arg_type = self._check_expression(expr.arguments[0].value)
            if arg_type is not None:
                arg_underlying = self._get_underlying_type(arg_type)
                if arg_underlying.kind != TypeKind.POINTER:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`__saw_deinit_in_place` expects an `UnsafePointer<T>` argument, "
                        f"got `{arg_type}`",
                        expr.line, expr.column
                    )
            return SawType(TypeKind.VOID)
        if expr.name == "__saw_forget":
            # design 45 (Part 0a): compiler-internal clear-without-drop for an
            # optional lvalue. Overwrites the optional's `is_some` discriminant to
            # None WITHOUT running the inner value's drop glue — the frame-resident
            # drop-flag clear that a conditional `move` of a cleanup-needing frame
            # local needs (assignment can't express it, since assigning None drops
            # the old inner). Generated only by the coroutine transform; never
            # user-facing (no diagnostic surface required beyond arity). No effect
            # source: clearing a flag never suspends.
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__saw_forget` takes exactly one argument, but "
                    f"{len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            self._check_expression(expr.arguments[0].value)
            return SawType(TypeKind.VOID)
        var_info = self.current_scope.lookup(expr.name)
        if var_info and var_info.type.kind == TypeKind.FUNCTION:
            func_type = var_info.type
            # Design 66: closure/function-value types are STRUCTURAL — they carry
            # no parameter names, so a labeled call through one has nothing to
            # bind to.
            if self._call_has_labels(expr):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"labeled arguments are not allowed when calling through the "
                    f"closure value `{expr.name}` (closure types are structural)",
                    expr.line, expr.column)
                return func_type.func_return_type or SawType(TypeKind.VOID)
            # design 22: a call through a function-typed value. If the value's
            # type is not `sync`, the caller conservatively suspends.
            self._effect_indirect_call(func_type, expr.line)
            param_types = func_type.param_types or []
            return_type = func_type.func_return_type or SawType(TypeKind.VOID)
            if len(expr.arguments) != len(param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"closure takes {len(param_types)} argument(s), but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type
            for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
                if isinstance(arg.value, ClosureExpr):
                    arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
                else:
                    self._apply_literal_expected_type(arg.value, expected_type)
                    arg_type = self._check_expression(arg.value)
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
                # Design 87: literal fixed-width adoption + range check ran in the
                # `_apply_literal_expected_type` propagation above (before the arg
                # check) — the per-position range check here is subsumed.
                self._check_value_transfer(arg.value, expected_type, "call argument",
                                           arg.value.line, arg.value.column)
            self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
            return return_type
        # Overloading (design 55): a name with 2+ visible overloads resolves
        # through the exact-match resolver, which then feeds the SAME downstream
        # machinery (value-transfer checkpoint, effect edges, exclusivity) with
        # the resolved callee.
        overloads = self.namespace.lookup_function_overloads(expr.name)
        if len(overloads) > 1 and self.namespace.is_accessible(expr.name):
            return self._check_overloaded_function_call(expr, overloads)
        # Prelude discipline (design 82 Part B): a bare call to a non-prelude std
        # free function not imported here errors with an import hint.
        if (expr.name in getattr(self, '_std_symbol_file', {})
                and self._std_name_gated(expr.name, expr.line, expr.column)):
            return None
        func_info = self.get_function_info(expr.name)
        if func_info and not self.namespace.is_accessible(expr.name):
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"function `{expr.name}` is not directly accessible",
                expr.line, expr.column,
                hint=f"use qualified access (e.g., `module_name.{expr.name}`) or import it directly"
            )
            return None
        if not func_info:
            # Check if function exists in any imported module (not directly accessible)
            from namespace import SymbolKind
            for module_name, module_sym in self.namespace.modules.items():
                if module_sym.namespace:
                    sym = module_sym.namespace.lookup_function(expr.name)
                    if sym and sym.visibility == Visibility.PUBLIC:
                        self._error(
                            ErrorKind.UNDEFINED_FUNCTION,
                            f"function `{expr.name}` is not directly accessible",
                            expr.line, expr.column,
                            hint=f"use qualified access (e.g., `{module_name}.{expr.name}`) or import it directly"
                        )
                        return None
            # `UserId(42)` — the explicit crossing INTO a distinct alias
            # (design 63). Checked before the struct branch below because an
            # alias name is resolved by its own lookup, not by struct info.
            alias_info = self.get_type_alias_info(expr.name)
            if alias_info is not None:
                return self._check_alias_construction(expr, alias_info)
            if self.get_struct_info(expr.name) and self.namespace.is_accessible(expr.name):
                from ast_nodes import StructInit, Argument
                field_inits = []
                for arg in expr.arguments:
                    if arg.name:
                        field_inits.append((arg.name, arg.value))
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"struct initialization requires named arguments",
                            arg.value.line, arg.value.column
                        )
                        return None
                struct_init = StructInit(
                    struct_name=expr.name,
                    field_inits=field_inits,
                    type_args=expr.type_args,
                    line=expr.line,
                    column=expr.column
                )
                result = self._check_struct_init(struct_init)
                expr.resolved_init_params = struct_init.resolved_init_params
                # Design 53: a matched init may have appended default-valued named
                # arguments; carry the augmented field-init list to codegen, which
                # otherwise rebuilds it from the (possibly empty) argument list.
                expr.resolved_field_inits = struct_init.field_inits
                # Design 144: `_check_struct_init` canonicalized the name it was
                # handed; carry that identity to codegen, which otherwise routes
                # `Bag()` by the written name and finds no layout under it.
                expr.resolved_type_identity = struct_init.struct_name
                return result
            # `A()` — constructing a value of an in-scope type parameter (design
            # 37). The allocator model relies on this: inside `Vector<T, A>`, the
            # container writes `A().alloc(...)` and monomorphization lowers `A`
            # to the concrete zero-sized allocator (`Global`, `LoudAlloc`), so
            # the construction becomes a direct zero-size placeholder and the
            # `.alloc`/`.dealloc` calls dispatch statically. The value's type is
            # the type parameter itself, kept abstract for the body check; a
            # trait method on it resolves through the parameter's bounds
            # (`_check_type_param_method_call`).
            type_params = getattr(self, 'current_type_params', {})
            if expr.name in type_params:
                if expr.arguments:
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"constructing a value of type parameter `{expr.name}` "
                        f"takes no arguments",
                        expr.line, expr.column
                    )
                return SawType(TypeKind.STRUCT, struct_name=expr.name)
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"undefined function `{expr.name}`",
                expr.line, expr.column
            )
            return None
        # design 53: an aliased selective import (`import m.{add as plus}`)
        # registers a symbol carrying its real codegen name in `mangled_name`;
        # stamp it so codegen calls the real definition, not the alias.
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        # design 22: record the call edge in the suspend graph (blocking externs
        # are a direct suspension source; other calls are edges to their node).
        self._effect_call_function(func_info, expr.name, expr.line)
        if func_info.type_params:
            # design 93: infer omitted type arguments from the argument types
            # (a partial explicit prefix pins its parameters, the rest infer).
            # Explicit-and-complete keeps the exact legacy path below.
            if len(expr.type_args or []) < len(func_info.type_params):
                # Design 105: map arguments to parameters BY LABEL before
                # unification, so a labeled/out-of-order call infers correctly.
                infer_mapping = self._infer_label_mapping(
                    expr, func_info.param_names, func_info.default_values)
                full = self._solve_call_type_args(
                    func_info.type_params, func_info.param_types, expr,
                    infer_mapping, {}, expr.type_args, f"function `{expr.name}`",
                    expr.line, expr.column,
                    default_values=func_info.default_values)
                if full is None:
                    return None
                expr.type_args = [full[tp.name] for tp in func_info.type_params]
            if len(expr.type_args) != len(func_info.type_params):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` expects {len(func_info.type_params)} type argument(s), "
                    f"but {len(expr.type_args)} were given",
                    expr.line, expr.column
                )
                return None
            type_map: Dict[str, SawType] = {}
            for type_param, type_arg in zip(func_info.type_params, expr.type_args):
                resolved_arg = self._resolve_type(type_arg)
                type_map[type_param.name] = resolved_arg
                for bound in type_param.bounds:
                    if self.get_trait_info(bound) is None:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{bound}` in type parameter bound",
                            expr.line, expr.column
                        )
                        continue
                    concrete_type_name = None
                    if resolved_arg.kind == TypeKind.STRUCT:
                        concrete_type_name = resolved_arg.struct_name
                    elif resolved_arg.kind == TypeKind.ENUM:
                        concrete_type_name = resolved_arg.enum_name
                    if bound == "Copy":
                        # The umbrella Copy bound is satisfied structurally:
                        # trivially-copyable types and ImplicitCopy/ExplicitCopy
                        # conformers all qualify without declaring `: Copy`.
                        if not self._type_satisfies_copy_bound(resolved_arg):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `Copy` bound",
                                expr.line, expr.column,
                                hint="use a trivially-copyable type, or one implementing ImplicitCopy/ExplicitCopy"
                            )
                    elif bound in ("Send", "Sync"):
                        # Send/Sync are structural marker traits (design 21 item 1),
                        # never explicit conformances. `_bound_satisfied` also honors
                        # an abstract type parameter's own declared bounds.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column,
                                hint="Send/Sync are derived structurally; a field or payload of this type is not "
                                     + bound
                            )
                    elif bound == "Equatable":
                        # Equatable is structural (design 32): primitives + String,
                        # trivial (POD) structs and payload-free enums, plus any
                        # declared conformer all satisfy it without a registered
                        # conformance record.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `Equatable` bound",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: Equatable {{}}`"
                                     if concrete_type_name else None
                            )
                    elif (resolved_arg.kind == TypeKind.STRUCT
                          and resolved_arg.struct_name
                          in getattr(self, 'current_type_params', {})):
                        # The callee's bound is applied to an ABSTRACT type
                        # parameter of the enclosing generic (`inner<T>(w)` inside
                        # `middle<T: Seed>`). It is satisfied exactly when the
                        # caller's own declared bounds carry it — a bounds-
                        # environment lookup; we cannot resolve `T` structurally
                        # here (design 77 item 2).
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type parameter `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column,
                                hint=f"add the bound to the enclosing signature: "
                                     f"`<{resolved_arg.struct_name}: {bound}>`"
                            )
                    elif concrete_type_name:
                        # DF-150b: ask the query that WALKS imported modules.
                        # `get_conformances` reads only this namespace's own
                        # table, so a conformance declared in the module that
                        # defines the type was invisible unless an import had
                        # copied it in — which the glob and selective forms do
                        # and a qualifier binding does not. Design 142 makes a
                        # conformance coherent program-wide and visible wherever
                        # the type and the trait are, so the import form must not
                        # decide the answer. The inference path beside this one
                        # already used the walking query (`_bound_satisfied`).
                        if not self.namespace.type_conforms_to(
                                concrete_type_name, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not implement trait `{bound}`",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: {bound} {{ ... }}`"
                            )
                        else:
                            type_assigns = self.namespace.get_type_assignments(concrete_type_name, bound)
                            for assoc_name, assoc_type in type_assigns.items():
                                type_map[assoc_name] = assoc_type
                    else:
                        # Design 109: a type argument with no struct/enum name to
                        # key a conformance by — a primitive, tuple, Optional,
                        # closure, or existential — was previously left UNCHECKED
                        # for the non-structural / user-trait bounds (silent accept
                        # of an invalid program). Route it through the same
                        # `_bound_satisfied` / conformance registry the trait-method
                        # dispatch and the generic-method path use: a structural
                        # trait (Comparable/Hashable/Printable) is satisfied where
                        # the primitive structurally conforms; a user trait is
                        # satisfied only via a registered `extension Int: T`.
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not satisfy the `{bound}` bound",
                                expr.line, expr.column)
            # design 70 (A5): record a deferred effect edge to this instantiation.
            # Materialized at finalize only if `expr.name`'s template is
            # effect-polymorphic (calls a method on a type-param receiver), so an
            # instantiation whose concrete `T` suspends taints its caller / trips a
            # sync context, while ordinary generic calls stay untouched. Only when
            # the concrete args are fully resolved (not themselves type params of an
            # enclosing generic — that call is re-inferred when the OUTER template
            # is instantiated).
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a) for a in resolved_args):
                self._effect_record_poly_call(
                    expr.name, resolved_args, f"`{expr.name}`", expr.line)
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = func_info.return_type.substitute(type_map)
        else:
            if expr.type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` is not generic but was called with type arguments",
                    expr.line, expr.column
                )
            param_types = func_info.param_types
            return_type = func_info.return_type
        # Default parameter values (design 53): an omitted trailing argument is
        # filled at the call site, so a call may provide between `required` and
        # `len(param_types)` arguments.
        dvals = func_info.default_values or []
        has_defaults = any(dv is not None for dv in dvals)
        required = (sum(1 for dv in dvals if dv is None) if has_defaults
                    else len(param_types))
        # Design 66: labeled arguments bind by the binding rule (which also
        # validates arity/missing/too-many); positional-only calls keep the
        # exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels and func_info.is_variadic:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"labeled arguments are not supported on variadic function "
                f"`{expr.name}`", expr.line, expr.column)
            return return_type
        if has_labels:
            mapping = self._bind_args(expr, func_info.param_names, dvals, expr.name)
            if mapping is None:
                return return_type
        else:
            mapping = None
            if func_info.is_variadic:
                if len(expr.arguments) < len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes at least {len(param_types)} argument(s), "
                        f"but {len(expr.arguments)} were given",
                        expr.line, expr.column
                    )
                    return return_type
            elif has_defaults:
                if len(expr.arguments) < required or len(expr.arguments) > len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes between {required} and "
                        f"{len(param_types)} argument(s), but {len(expr.arguments)} "
                        f"were given",
                        expr.line, expr.column
                    )
                    return return_type
            else:
                if len(expr.arguments) != len(param_types):
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"function `{expr.name}` takes {len(param_types)} argument(s), "
                        f"but {len(expr.arguments)} were given",
                        expr.line, expr.column
                    )
                    return return_type
        # Design 108: for a GENERIC call, an OMITTED default-valued parameter must
        # have its default expression fit the INSTANTIATED parameter type. The
        # declaration-time check (design 53) ran against the abstract `T` and was
        # skipped, so this is the only place the default is validated per call —
        # `f<Float>(1)` with `b: T = 0` is a clean anchored error (a bare integer
        # literal does not adopt Float), never a codegen ICE.
        if func_info.type_params:
            self._check_generic_call_defaults(expr, func_info, param_types, mapping)
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected_type = param_types[p] if p < len(param_types) else None
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                self._apply_literal_expected_type(arg.value, expected_type)
                arg_type = self._check_expression(arg.value)
            declared = (func_info.param_types[p]
                        if p < len(func_info.param_types) else None)
            allow_wrap = self._df3_allow_wrap(
                declared, {tp.name for tp in (func_info.type_params or [])})
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and expected_type is not None and not self._arg_type_ok(
                    arg.value, arg_type, expected_type, allow_wrap):
                param_name = func_info.param_names[p]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            # Design 87: literal fixed-width adoption + range check ran in the
            # `_apply_literal_expected_type` propagation above — subsumed here.
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Variadic extra arguments have no declared parameter type to check
        # against, but must still flow through the chokepoint so codegen sees
        # their resolved_type annotations. (Variadic calls are never labeled.)
        if mapping is None:
            for arg in expr.arguments[len(param_types):]:
                self._check_expression(arg.value)
                self._check_value_transfer(arg.value, None, "call argument",
                                           arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_if_expr(self, expr: IfExpr) -> Optional[SawType]:
        """Check an if expression."""
        cond_type = self._check_expression(expr.condition)
        if cond_type and cond_type.kind != TypeKind.BOOL:
            if cond_type.kind != TypeKind.INT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"condition must be `Bool`, got `{cond_type}`",
                    expr.line, expr.column
                )
        # Move dataflow (design 15 rule 6): check both branches from the same
        # entry state, then union-merge, excluding branches that diverge.
        entry_moves = self._snapshot_moves()
        then_type = self._check_block(expr.then_branch)
        then_state = self._snapshot_moves()
        then_diverges = self._block_has_early_exit(expr.then_branch)
        self.moved_bindings = dict(entry_moves)
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            else_state = self._snapshot_moves()
            else_diverges = self._block_has_early_exit(expr.else_branch)
        else:
            # An absent else contributes the entry state (no new moves).
            else_state = dict(entry_moves)
            else_diverges = False
        self.moved_bindings = self._merge_move_branches(
            entry_moves,
            [(then_state, then_diverges), (else_state, else_diverges)])

        if expr.else_branch:
            # design 49: a diverging branch (`panic(...)`, type NEVER) contributes
            # no value to the merge — the `if` takes the other branch's type.
            if then_type is not None and then_type.kind == TypeKind.NEVER:
                return else_type
            if else_type is not None and else_type.kind == TypeKind.NEVER:
                return then_type
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                # Check if branches could be Result auto-wrapped
                expected_return = None
                if self.current_method:
                    expected_return = self._resolve_type(self.current_method.return_type)
                elif self.current_function:
                    expected_return = self._resolve_type(self.current_function.return_type)

                if expected_return and expected_return.is_result():
                    ok_type = expected_return.type_args[0] if expected_return.type_args else None
                    err_type = expected_return.type_args[1] if expected_return.type_args and len(expected_return.type_args) > 1 else None

                    # Check if branches match Ok and Err types
                    then_is_ok = ok_type and self._types_compatible(then_type, ok_type)
                    then_is_err = err_type and self._types_compatible(then_type, err_type)
                    else_is_ok = ok_type and self._types_compatible(else_type, ok_type)
                    else_is_err = err_type and self._types_compatible(else_type, err_type)

                    if (then_is_ok or then_is_err) and (else_is_ok or else_is_err):
                        # Wrap branch final expressions in ResultOkWrap/ResultErrWrap
                        if expr.then_branch.final_expr:
                            if then_is_ok:
                                expr.then_branch.final_expr = ResultOkWrap(
                                    value=expr.then_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.then_branch.final_expr.line,
                                    column=expr.then_branch.final_expr.column
                                )
                            elif then_is_err:
                                expr.then_branch.final_expr = ResultErrWrap(
                                    value=expr.then_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.then_branch.final_expr.line,
                                    column=expr.then_branch.final_expr.column
                                )
                        if expr.else_branch.final_expr:
                            if else_is_ok:
                                expr.else_branch.final_expr = ResultOkWrap(
                                    value=expr.else_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.else_branch.final_expr.line,
                                    column=expr.else_branch.final_expr.column
                                )
                            elif else_is_err:
                                expr.else_branch.final_expr = ResultErrWrap(
                                    value=expr.else_branch.final_expr,
                                    result_type=expected_return,
                                    line=expr.else_branch.final_expr.line,
                                    column=expr.else_branch.final_expr.column
                                )
                        return expected_return

                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if` and `else` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )
            if then_type and else_type:
                if else_type.is_none_literal() and not then_type.is_optional():
                    result_type = then_type.wrap_optional()
                    self._annotate_none_in_block(expr.else_branch, result_type)
                    # Wrap the then branch in OptionalWrap
                    if expr.then_branch.final_expr:
                        expr.then_branch.final_expr = OptionalWrap(
                            value=expr.then_branch.final_expr,
                            target_type=result_type,
                            line=expr.then_branch.final_expr.line,
                            column=expr.then_branch.final_expr.column
                        )
                    return result_type
                if else_type.is_none_literal() and then_type.is_optional():
                    self._annotate_none_in_block(expr.else_branch, then_type)
                    return then_type
                if then_type.is_none_literal() and not else_type.is_optional():
                    result_type = else_type.wrap_optional()
                    self._annotate_none_in_block(expr.then_branch, result_type)
                    # Wrap the else branch in OptionalWrap
                    if expr.else_branch.final_expr:
                        expr.else_branch.final_expr = OptionalWrap(
                            value=expr.else_branch.final_expr,
                            target_type=result_type,
                            line=expr.else_branch.final_expr.line,
                            column=expr.else_branch.final_expr.column
                        )
                    return result_type
                if then_type.is_none_literal() and else_type.is_optional():
                    self._annotate_none_in_block(expr.then_branch, else_type)
                    return else_type
                # Wrap T branch in Optional if other branch is T?
                if else_type.is_optional() and not then_type.is_optional():
                    if expr.then_branch.final_expr:
                        expr.then_branch.final_expr = OptionalWrap(
                            value=expr.then_branch.final_expr,
                            target_type=else_type,
                            line=expr.then_branch.final_expr.line,
                            column=expr.then_branch.final_expr.column
                        )
                    return else_type
                if then_type.is_optional() and not else_type.is_optional():
                    if expr.else_branch.final_expr:
                        expr.else_branch.final_expr = OptionalWrap(
                            value=expr.else_branch.final_expr,
                            target_type=then_type,
                            line=expr.else_branch.final_expr.line,
                            column=expr.else_branch.final_expr.column
                        )
                    return then_type
            return then_type or else_type
        else:
            return then_type

    def _check_if_let_expr(self, expr: IfLetExpr) -> Optional[SawType]:
        """Check an if let/var expression for optional binding."""
        from .core import VariableInfo, Scope
        optional_type = self._check_expression(expr.optional_expr)
        if optional_type is None:
            return None
        if optional_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"'if let' requires an optional type, got `{optional_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = optional_type.inner_type
        if inner_type is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                expr.line, expr.column
            )
            return None
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        if expr.pattern is not None:
            # Design 100: tuple-pattern bindings BIND (no per-binding derive) —
            # a shadow of an enclosing binding is a flat error.
            for nm, nl, nc in self._pattern_binding_names(expr.pattern):
                self._check_shadowing(nm, None, nl, nc, site="pattern")
            # Tuple pattern over an Optional tuple (design 63).
            self._bind_optional_pattern(expr.pattern, inner_type, expr.mutable,
                                        expr.line, expr.column)
        else:
            # Design 100: `if let x = x` (scrutinee mentions the shadowed
            # enclosing binding) stays legal by the main rule; a non-deriving
            # single-name shadow is an error.
            self._check_shadowing(expr.name, expr.optional_expr,
                                  expr.line, expr.column, site="binding")
            # Design 111 rider: `if let _ = opt` evaluates + tests the Optional but
            # BINDS NOTHING (the payload drops immediately at codegen). This is the
            # idiomatic way to consume a `Void?` (`if let _ = x?.y = v`).
            if expr.name != "_":
                self.current_scope.define(
                    expr.name,
                    VariableInfo(inner_type, expr.mutable, expr.line, expr.column)
                )
                # design 131: the binding is a VALUE READ of the payload. Out of
                # a place the scrutinee keeps, that read follows the copy policy
                # — retain for ImplicitCopy, refused for ExplicitCopy/NoCopy
                # (`if let a = move o` is the consuming form). A fresh temporary
                # scrutinee already handed its payload over and is unchanged.
                self._check_payload_read(expr.optional_expr, inner_type, expr,
                                         "an `if let` binding",
                                         expr.line, expr.column)
        # Move dataflow (design 15 rule 6): branches merge as union of the
        # non-diverging paths, from a shared entry state.
        entry_moves = self._snapshot_moves()
        then_type = self._check_block(expr.then_branch)
        then_state = self._snapshot_moves()
        then_diverges = self._block_has_early_exit(expr.then_branch)
        self.current_scope = old_scope
        self.moved_bindings = dict(entry_moves)
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            else_state = self._snapshot_moves()
            else_diverges = self._block_has_early_exit(expr.else_branch)
        else:
            else_state = dict(entry_moves)
            else_diverges = False
        self.moved_bindings = self._merge_move_branches(
            entry_moves,
            [(then_state, then_diverges), (else_state, else_diverges)])
        if expr.else_branch:
            # design 49: a diverging branch (`panic(...)`, type NEVER) takes the
            # other branch's type.
            if then_type is not None and then_type.kind == TypeKind.NEVER:
                return else_type
            if else_type is not None and else_type.kind == TypeKind.NEVER:
                return then_type
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if let` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )
            if then_type and else_type:
                if else_type.is_none_literal() and not then_type.is_optional():
                    result_type = then_type.wrap_optional()
                    self._annotate_none_in_block(expr.else_branch, result_type)
                    return result_type
                if else_type.is_none_literal() and then_type.is_optional():
                    self._annotate_none_in_block(expr.else_branch, then_type)
                    return then_type
                if then_type.is_none_literal() and not else_type.is_optional():
                    result_type = else_type.wrap_optional()
                    self._annotate_none_in_block(expr.then_branch, result_type)
                    return result_type
                if then_type.is_none_literal() and else_type.is_optional():
                    self._annotate_none_in_block(expr.then_branch, else_type)
                    return else_type
            return then_type or else_type
        else:
            return then_type

    def _check_tuple_literal(self, expr: TupleLiteral) -> Optional[SawType]:
        """Check a tuple literal (design 63: carries field labels for a named
        tuple literal `(x: 3, y: 4)`).

        DF-151l: when the context DECLARED a tuple type, its element types are
        what the elements are checked against — the same job the array literal's
        `arr_elem` does (DF-151e), through the same `_element_fits` helper, so
        the one-level `T -> T?` auto-wrap is recorded on the element. Without it
        the literal took each element's own type, so an annotated `(Int?, Int)`
        never reached its elements: a bare `None` stayed untyped (`inner_type=
        None`, an ICE at the codegen None literal) and a bare `Int` was stored
        UNWRAPPED, laying the tuple out `{i64, i64}` while the storage and every
        read believed `{{i1,i64}, i64}` — an ICE on the first read.
        """
        expected = getattr(expr, 'expected_type', None)
        declared = None
        if (expected is not None and expected.kind == TypeKind.TUPLE
                and expected.element_types
                and len(expected.element_types) == len(expr.elements)):
            declared = expected.element_types

        element_types = []
        for i, element in enumerate(expr.elements):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            target = declared[i] if declared is not None else elem_type
            if declared is not None and not self._element_fits(element, elem_type,
                                                               target):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple element {i} has type `{elem_type}`, expected "
                    f"`{target}`",
                    element.line, element.column
                )
                return None
            element_types.append(target)
            self._check_value_transfer(element, target, "tuple element",
                                       element.line, element.column)
        field_names = getattr(expr, 'field_names', None)
        if declared is not None and expected.tuple_field_names:
            # A declared named tuple keeps its labels even when the literal was
            # written positionally (`let p: (x: Int, y: Int) = (1, 2)`).
            field_names = field_names or expected.tuple_field_names
        return SawType(TypeKind.TUPLE, element_types=element_types,
                       tuple_field_names=field_names)

    def _check_tuple_index(self, expr: TupleIndex) -> Optional[SawType]:
        """Check tuple indexing."""
        tuple_type = self._check_expression(expr.tuple_expr)
        if tuple_type is None:
            return None
        if tuple_type.kind != TypeKind.TUPLE:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into non-tuple type `{tuple_type}`",
                expr.line, expr.column
            )
            return None
        if tuple_type.element_types is None:
            return None
        if expr.index < 0 or expr.index >= len(tuple_type.element_types):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"tuple index {expr.index} out of range for tuple with {len(tuple_type.element_types)} elements",
                expr.line, expr.column
            )
            return None
        return tuple_type.element_types[expr.index]

    def _check_array_literal(self, expr: ArrayLiteral) -> Optional[SawType]:
        """Check an array literal and infer its type.

        Design 54 Part 4: when the EXPECTED type (stamped by a binding
        annotation / parameter / return / struct field) is `Vector<T, A>`, the
        literal builds a Vector (per-element push) instead of a fixed-size
        array. With no expected type it stays a fixed-size array, byte-for-byte
        as before."""
        expected = getattr(expr, 'expected_type', None)
        vec_elem = None
        arr_elem = None
        if (expected is not None and expected.kind == TypeKind.STRUCT
                and expected.struct_name == "Vector" and expected.type_args):
            vec_elem = expected.type_args[0]
        elif (expected is not None and expected.kind == TypeKind.ARRAY
                and expected.array_element_type is not None):
            # The ANNOTATED element type is the one the elements are checked
            # against — the same job `vec_elem` does for a Vector (DF-151e).
            # Without it the literal took its element type from element 0 alone,
            # so `[T?; N]` never reached its elements: a `None` stayed untyped
            # (`inner_type=None`, an ICE at the codegen None literal) and a bare
            # `T` was stored UNWRAPPED, laying the value out `[T x N]` while the
            # storage, the element drop and every read believed `[{i1,T} x N]`.
            arr_elem = expected.array_element_type

        if expr.repeat_count is not None:
            return self._check_repeat_literal(expr, vec_elem, expected, arr_elem)

        if len(expr.elements) == 0:
            if vec_elem is not None:
                # Empty Vector via context: `let v: Vector<Int> = []`.
                expr.vector_container_type = expected
                return expected
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot infer type of empty array literal; use explicit type annotation",
                expr.line, expr.column
            )
            return None

        # Element unification target: the DECLARED element type when the context
        # named one (a Vector's `T`, or a fixed array's), otherwise inferred from
        # the first element.
        declared_elem = vec_elem if vec_elem is not None else arr_elem
        first_type = self._check_expression(expr.elements[0])
        if first_type is None:
            return None
        target = declared_elem if declared_elem is not None else first_type
        if vec_elem is not None and not self._element_fits(expr.elements[0],
                                                           first_type, vec_elem):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"vector literal element 0 has type `{first_type}`, expected `{vec_elem}`",
                expr.elements[0].line, expr.elements[0].column)
            return None
        if arr_elem is not None and not self._element_fits(expr.elements[0],
                                                           first_type, arr_elem):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"array element 0 has type `{first_type}`, expected `{arr_elem}`",
                expr.elements[0].line, expr.elements[0].column)
            return None
        self._check_value_transfer(expr.elements[0], target, "array element",
                                   expr.elements[0].line, expr.elements[0].column)
        for i, element in enumerate(expr.elements[1:], start=1):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            if not self._element_fits(element, elem_type, target):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element {i} has type `{elem_type}`, expected `{target}`",
                    element.line, element.column
                )
                return None
            self._check_value_transfer(element, target, "array element",
                                       element.line, element.column)
        if vec_elem is not None:
            expr.vector_container_type = expected
            return expected
        return SawType(TypeKind.ARRAY, array_element_type=target,
                       array_size=len(expr.elements))

    def _element_fits(self, element, elem_type, target) -> bool:
        """Whether a collection-literal element of `elem_type` may occupy a
        `target` slot, recording the one-level `T -> T?` auto-wrap on the element
        when that is what makes it fit (DF-151e).

        An element position is a transfer into a declared slot, exactly like a
        call argument or a struct-literal field, so it gets the same rule: a bare
        `None` takes the slot's payload type and a bare `T` records the wrap that
        codegen builds `Some(x)` from. `target` is the element's own type when
        nothing declared one, in which case there is nothing to wrap and this is
        the plain compatibility test it always was.
        """
        if target is not None and target.is_optional():
            return self._arg_type_ok(element, elem_type, target)
        return self._types_compatible(elem_type, target)

    def _check_repeat_literal(self, expr: ArrayLiteral, vec_elem, expected,
                              arr_elem=None):
        """Check a repeat literal `[v; N]` — N copies of one value (design 148).

        `[0; 256]` is what finally spells a zero stack buffer; before it, the
        only way to write one was 256 literal zeros, which is why the panic
        scratch buffer had to be allocated by the compiler rather than in Saw
        (DF-137b).
        """
        # A repeat literal is a FIXED array. `let v: Vector<Int> = [0; 8]` would
        # have to mean "a Vector of 8 zeros", which is `Vector` construction and
        # not a literal at all — refusing it by name beats silently building an
        # 8-element fixed array where a Vector was annotated.
        if vec_elem is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a repeat literal `[v; N]` builds a fixed array, not a "
                f"`{expected}`",
                expr.line, expr.column,
                hint="drop the annotation to get `[T; N]`, or build the vector "
                     "with a loop of `push`")
            return None

        value = expr.elements[0]
        elem_type = self._check_expression(value)
        if elem_type is None:
            return None
        if arr_elem is not None:
            # The annotated element type wins, so `[None; 4]` and `[7; 4]` both
            # reach an `[Int?; 4]` slot: the first gets its payload type, the
            # second records the `T -> T?` wrap (DF-151e). The copy-tier check
            # below then asks about `T?`, which design 139 says carries `T`'s
            # tier — so a `[v; 3]` of a Vector is refused whether or not the
            # annotation wrapped it in an optional.
            if not self._element_fits(value, elem_type, arr_elem):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element 0 has type `{elem_type}`, expected "
                    f"`{arr_elem}`",
                    value.line, value.column)
                return None
            elem_type = arr_elem

        count = self._const_count(expr.repeat_count, "repeat count")
        if count is None:
            return None
        if count is _ABSTRACT_COUNT:
            # A `[v; N]` inside a generic body: constant, but its value belongs
            # to the instantiation. The length rides along as an expression and
            # every instantiation folds its own. The copy-policy check below
            # still applies — the body has to be correct for every N.
            if not (self._is_trivially_copyable(elem_type)
                    or self._is_implicit_copy_type(elem_type)):
                count = 2       # force the refusal below to fire
            else:
                self._check_value_transfer(value, elem_type, "array element",
                                           value.line, value.column)
                return SawType(TypeKind.ARRAY, array_element_type=elem_type,
                               array_size_expr=expr.repeat_count)
        if count < 0:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"repeat count is negative (`{count}`)",
                expr.repeat_count.line, expr.repeat_count.column,
                hint="an array length counts elements, so it starts at 0")
            return None

        # Every copy is a copy. A trivially-copyable element is duplicated
        # bitwise and an ImplicitCopy one retains N times, both of which the
        # value's own transfer checkpoint below accounts for. An ExplicitCopy or
        # NoCopy element cannot be: `move v` transfers ONE value and there is no
        # spelling for "and N-1 more", so the literal is refused by name rather
        # than quietly aliasing the same buffer N times.
        # "Copies are free" is a question about the TIER, so it goes to design
        # 139's oracle rather than to a conformance lookup (design 159). The
        # conformance-based predicate could not see the UNDECLARED ImplicitCopy
        # tier, so `[p; 3]` on a `struct P { name: String }` was refused with a
        # diagnostic that called `P` ExplicitCopy — a policy it does not have
        # and could not be given, since such a struct is exempt from declaring
        # one at all.
        if count > 1 and self.namespace.copy_tier(elem_type) not in ('free',
                                                                    'implicit'):
            if self._is_abstract_type_param(elem_type):
                # An opaque type parameter has no copy policy — it has whatever
                # its instantiation brings, and no bound expresses "copies are
                # free": `Copy` admits ExplicitCopy, and `ImplicitCopy` excludes
                # the POD types that are freer still. So the element type is
                # concrete in v1 (DF-148a), and the message says that rather
                # than naming a policy the parameter does not have.
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"a repeat literal needs an element type whose copies are "
                    f"free, and the type parameter `{elem_type}` is not known "
                    f"to be one",
                    value.line, value.column,
                    hint="v1 repeats a CONCRETE element (`[0; N]`, `[\"\"; N]`) "
                         "— no bound yet says `T` copies for free, so a generic "
                         "element cannot be repeated")
                return None
            if self._is_no_copy_type(elem_type):
                policy, hint = "NoCopy", (
                    "a NoCopy value has exactly one owner, so there is nothing "
                    "to repeat — build the array element by element, moving a "
                    "separate value into each slot")
            else:
                policy, hint = "ExplicitCopy", (
                    "an ExplicitCopy value duplicates only where you write "
                    "`.copy()` — build the array element by element so each "
                    "copy is spelled out")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"a repeat literal needs a freely copyable element, and "
                f"`{elem_type}` is {policy}",
                value.line, value.column, hint=hint)
            return None

        self._check_value_transfer(value, elem_type, "array element",
                                   value.line, value.column)
        return SawType(TypeKind.ARRAY, array_element_type=elem_type,
                       array_size=count)

    def _const_count(self, expr, what: str):
        """Evaluate a compile-time count/length.

        Returns the integer, `_ABSTRACT_COUNT` for an expression that IS
        constant but whose value belongs to an instantiation (`[v; N]` inside a
        generic body), or None having reported why it is not constant at all.

        The one evaluator (`const_eval.py`) answers here, in `static_assert`,
        and in an array length, so the three can never disagree about what a
        constant is. The typechecker passes no layout oracle — it knows the word
        width but not struct layout — so `sizeof<T>()` in a length is rejected
        by name here and folded later, in codegen, where the layout exists.
        """
        # Type-check it first: that surfaces an ordinary type error in the
        # count (and stamps the `Int.max` annotation the evaluator reads)
        # before the constant question is asked.
        if self._check_expression(expr) is None:
            return None
        # Const parameters in scope are constants with no value here — a generic
        # body is checked once, abstractly, and the values arrive per
        # instantiation. Probing with a stand-in separates "not a constant" from
        # "a constant this pass cannot see", which are different answers.
        probe = dict.fromkeys(self._const_param_types().keys(), 1)
        probe.update(self._const_param_env())
        try:
            value = const_eval(expr, env=probe, width=self.platform_int_width)
        except ConstEvalError as e:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} is not a compile-time constant: {e.what} is not "
                f"allowed here",
                e.line or expr.line, e.column or expr.column,
                hint="a length is fixed at compile time — use a literal, a "
                     "const generic parameter, or arithmetic over them")
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} must be an integer",
                expr.line, expr.column)
            return None
        if self._mentions_const_param(expr):
            return _ABSTRACT_COUNT
        return value

    def _is_abstract_type_param(self, t) -> bool:
        """Whether `t` is an in-scope generic type parameter rather than a
        concrete type — a name the parser left as STRUCT, or a TYPE_PARAM."""
        if t is None:
            return False
        if t.kind == TypeKind.TYPE_PARAM:
            return True
        params = getattr(self, 'current_type_params', None) or {}
        return t.kind == TypeKind.STRUCT and t.struct_name in params

    def _mentions_const_param(self, expr) -> bool:
        """Whether a constant expression reads a const generic parameter."""
        names = self._const_param_types()
        if not names:
            return False
        from ast_nodes import Identifier as _Id, UnaryOp as _U, BinaryOp as _B
        if isinstance(expr, _Id):
            return expr.name in names
        if isinstance(expr, _U):
            return self._mentions_const_param(expr.operand)
        if isinstance(expr, _B):
            return (self._mentions_const_param(expr.left)
                    or self._mentions_const_param(expr.right))
        return False

    def _const_param_env(self):
        """The const generic parameters in scope, as name -> VALUE.

        Always empty in the typechecker: a generic body is checked once,
        abstractly, so no instantiation's values are in force. Codegen has the
        twin that is populated (design 148). The method exists so every constant
        position asks the same question in the same way.
        """
        return getattr(self, 'current_const_params', None) or {}

    def _const_param_types(self):
        """The const generic parameters in scope, as name -> declared type."""
        return getattr(self, 'current_const_param_types', None) or {}

    def _check_map_literal(self, expr: MapLiteral) -> Optional[SawType]:
        """Check a map literal `{k: v, ...}` / `{:}` (design 54 Part 3).

        K/V are inferred from the entries, or taken from an expected
        `Map<K, V, A>` type (annotation/param/return/field) which also allows a
        custom allocator. `{:}` requires an expected type."""
        expected = getattr(expr, 'expected_type', None)
        exp_map = (expected if (expected is not None and expected.kind == TypeKind.STRUCT
                                and expected.struct_name == "Map") else None)
        if expected is not None and exp_map is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a map literal cannot initialize a value of type `{expected}`",
                expr.line, expr.column)
            return None

        exp_k = exp_map.type_args[0] if (exp_map and len(exp_map.type_args) >= 1) else None
        exp_v = exp_map.type_args[1] if (exp_map and len(exp_map.type_args) >= 2) else None

        if len(expr.entries) == 0:
            # `{:}` — the empty map needs an expected type to fix K/V.
            if exp_map is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "cannot infer the type of the empty map literal `{:}`; "
                    "add a type annotation (e.g. `let m: Map<String, Int> = {:}`)",
                    expr.line, expr.column)
                return None
            self._check_map_key_bounds(exp_k, expr)
            expr.resolved_type = exp_map
            return exp_map

        key_type = exp_k
        val_type = exp_v
        for i, (k_expr, v_expr) in enumerate(expr.entries):
            kt = self._check_expression(k_expr)
            vt = self._check_expression(v_expr)
            if kt is None or vt is None:
                return None
            if key_type is None:
                key_type = kt
            elif not self._types_compatible(kt, key_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"map key {i} has type `{kt}`, expected `{key_type}` "
                    f"(all keys in a map literal must share one type)",
                    k_expr.line, k_expr.column)
                return None
            if val_type is None:
                val_type = vt
            elif not self._types_compatible(vt, val_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"map value {i} has type `{vt}`, expected `{val_type}` "
                    f"(all values in a map literal must share one type)",
                    v_expr.line, v_expr.column)
                return None

        self._check_map_key_bounds(key_type, expr)
        container = exp_map if exp_map is not None else SawType(
            TypeKind.STRUCT, struct_name="Map", type_args=[key_type, val_type])
        # Each entry is consumed exactly as an `insert(k, v)` argument would be
        # (moves for owning values); the checkpoint sees N independent transfers.
        eff_k = exp_k if exp_k is not None else key_type
        eff_v = exp_v if exp_v is not None else val_type
        for (k_expr, v_expr) in expr.entries:
            self._check_value_transfer(k_expr, eff_k, "map key",
                                       k_expr.line, k_expr.column)
            self._check_value_transfer(v_expr, eff_v, "map value",
                                       v_expr.line, v_expr.column)
        expr.resolved_type = container
        return container

    def _check_set_literal(self, expr: SetLiteral) -> Optional[SawType]:
        """Check a set literal `{a, b, ...}` (design 54 Part 3)."""
        expected = getattr(expr, 'expected_type', None)
        exp_set = (expected if (expected is not None and expected.kind == TypeKind.STRUCT
                                and expected.struct_name == "Set") else None)
        if expected is not None and exp_set is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"a set literal cannot initialize a value of type `{expected}`",
                expr.line, expr.column)
            return None
        exp_t = exp_set.type_args[0] if (exp_set and len(exp_set.type_args) >= 1) else None

        elem_type = exp_t
        for i, e_expr in enumerate(expr.elements):
            et = self._check_expression(e_expr)
            if et is None:
                return None
            if elem_type is None:
                elem_type = et
            elif not self._types_compatible(et, elem_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"set element {i} has type `{et}`, expected `{elem_type}` "
                    f"(all elements in a set literal must share one type)",
                    e_expr.line, e_expr.column)
                return None

        self._check_map_key_bounds(elem_type, expr, what="set element")

        container = exp_set if exp_set is not None else SawType(
            TypeKind.STRUCT, struct_name="Set", type_args=[elem_type])
        eff_t = exp_t if exp_t is not None else elem_type
        for e_expr in expr.elements:
            self._check_value_transfer(e_expr, eff_t, "set element",
                                       e_expr.line, e_expr.column)
        expr.resolved_type = container
        return container

    def _apply_literal_expected_type(self, value_expr, expected_type):
        """Central expected-type propagation for literals (designs 54 + 87).

        Pushes a resolved expected type down onto a literal-bearing subexpression
        BEFORE it is checked. Two jobs, one recursive pass:

        - COLLECTION shaping (design 54): a Map/Set/Vector expectation lets an
          array/map/set literal pick K/V/T, honor a custom allocator, or build a
          Vector rather than a fixed array.
        - FIXED-WIDTH INT adoption (design 87): a bare integer literal flowing
          into a fixed-width int slot (`Int8`..`UInt64`) adopts that type and is
          range-checked AT the literal (in `visit_IntLiteral`) — uniformly, at
          every slot that calls this (let/param/field/return/compound-assign/…),
          THROUGH the "transparent" constructs that forward a value unchanged:
          unary minus, if/match/block arm results, and array/tuple/map/set
          element positions.

        A platform `Int`/`UInt` (or non-integer) expectation leaves a literal at
        platform width — the load-bearing INVARIANT. No-op for anything else.
        """
        if expected_type is None or value_expr is None:
            return
        rt = self._resolve_type(expected_type)
        if rt is None:
            return

        # (1) Bare integer literal → adopt a fixed-width expectation, range-check
        #     it AT the literal, and stamp the fixed-width type. Stamping here (not
        #     only via visit_IntLiteral) covers the POST-HOC sites — overloaded
        #     call args are checked before the winning param type is known, then
        #     coerced through this method — as well as the before-check slots.
        if isinstance(value_expr, IntLiteral):
            _rng = (self._int_range_for(rt.kind)
                    if getattr(value_expr, 'suffix', None) is None else None)
            if _rng is not None:
                value_expr.expected_type = rt
                lo, hi = _rng
                if not (lo <= value_expr.value <= hi):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"integer literal {value_expr.value} does not fit in "
                        f"`{expected_type}` (range {lo}..={hi})",
                        getattr(value_expr, 'line', 0),
                        getattr(value_expr, 'column', 0))
                value_expr.resolved_type = SawType(rt.kind)
            return

        # (2) Unary minus of a literal: the fixed-width expectation carries
        #     through to the operand (`let x: Int8 = -5`). The range check runs on
        #     the FOLDED (negated) value — a bare magnitude like Int32.min's
        #     2147483648 is in range only once negated (design 77 item 8) — so it
        #     is handled here rather than via the plain-literal recursion.
        if isinstance(value_expr, UnaryOp) and value_expr.op == '-':
            operand = value_expr.operand
            _rng = (self._int_range_for(rt.kind)
                    if (isinstance(operand, IntLiteral)
                        and getattr(operand, 'suffix', None) is None) else None)
            if _rng is not None:
                operand.expected_type = rt
                lo, hi = _rng
                if not (lo <= -operand.value <= hi):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"integer literal -{operand.value} does not fit in "
                        f"`{expected_type}` (range {lo}..={hi})",
                        getattr(operand, 'line', 0), getattr(operand, 'column', 0))
                operand.resolved_type = SawType(rt.kind)
            else:
                self._apply_literal_expected_type(operand, rt)
            return

        # (3) if / match / block whose arm results merge to the expected type.
        if isinstance(value_expr, IfExpr):
            self._apply_literal_expected_type(
                getattr(value_expr.then_branch, 'final_expr', None), rt)
            if value_expr.else_branch is not None:
                self._apply_literal_expected_type(
                    getattr(value_expr.else_branch, 'final_expr', None), rt)
            return
        if isinstance(value_expr, MatchExpr):
            for arm in value_expr.arms:
                self._apply_literal_expected_type(arm.body, rt)
            return
        if isinstance(value_expr, Block):
            self._apply_literal_expected_type(
                getattr(value_expr, 'final_expr', None), rt)
            return

        # (4) Tuple literal into a tuple type: element-wise. Keep the tuple
        #     expectation on the literal, not only its element types —
        #     `_check_tuple_literal` reads it to check each element against the
        #     DECLARED element type rather than taking the element's own
        #     (DF-151l). This is the same stamp the ARRAY branch below makes,
        #     and what makes nesting work: a `((Int?, Int), Int)` annotation
        #     reaches the inner literal through this recursion.
        if isinstance(value_expr, TupleLiteral) and rt.kind == TypeKind.TUPLE:
            value_expr.expected_type = rt
            elem_types = rt.element_types or []
            if len(elem_types) == len(value_expr.elements):
                for e, et in zip(value_expr.elements, elem_types):
                    self._apply_literal_expected_type(e, et)
            return

        # (5) Array literal into `[IntN; M]` or `Vector<IntN, A>`: propagate the
        #     element type (and, for a Vector, keep the collection expectation).
        if isinstance(value_expr, ArrayLiteral):
            elem_t = None
            if rt.kind == TypeKind.ARRAY:
                # Keep the array expectation on the literal, not just its
                # element type: `_check_array_literal` reads it to check the
                # elements against the DECLARED element type rather than
                # inferring one from element 0 (DF-151e). Stamping it here is
                # what makes nesting work — a `[[Int?; 2]; 2]` annotation
                # reaches the inner literals through this same recursion.
                value_expr.expected_type = rt
                elem_t = rt.array_element_type
            elif (rt.kind == TypeKind.STRUCT and rt.struct_name == "Vector"
                    and rt.type_args):
                value_expr.expected_type = rt
                elem_t = rt.type_args[0]
            if elem_t is not None:
                for e in value_expr.elements:
                    self._apply_literal_expected_type(e, elem_t)
            return

        # (6) Map / Set literal: keep the collection expectation (design 54) and
        #     push K/V/T down to element literals (design 87).
        if isinstance(value_expr, MapLiteral):
            if rt.kind == TypeKind.STRUCT:
                value_expr.expected_type = rt
                if rt.struct_name == "Map" and len(rt.type_args) >= 2:
                    for (k_expr, v_expr) in value_expr.entries:
                        self._apply_literal_expected_type(k_expr, rt.type_args[0])
                        self._apply_literal_expected_type(v_expr, rt.type_args[1])
            return
        if isinstance(value_expr, SetLiteral):
            if rt.kind == TypeKind.STRUCT:
                value_expr.expected_type = rt
                if rt.struct_name == "Set" and rt.type_args:
                    for e in value_expr.elements:
                        self._apply_literal_expected_type(e, rt.type_args[0])
            return

    def _key_copyable_reason(self, key_type):
        """Return None if `key_type` may be a Map/Set KEY, else a short reason it
        cannot (design 65 followup, L19). A key is probed by COPY (hash / compare
        / slot inspection), so it must be copyable-with-retain in a balanced way:
        a trivial/POD type (bitwise, no deinit), an ImplicitCopy type (refcount
        bump), or an ExplicitCopy type (deep copy + symmetric deinit) all balance.
        A NoCopy type, or a `Deinit` type with no copy conformance (move-only,
        no refcount to retain), cannot — its probe copies would run the deinit and
        miscount / double-free. VALUES are unaffected (never probe-copied)."""
        if key_type is None:
            return None
        # An opaque generic type parameter is not concretely known here; the
        # concrete instantiation is checked at the user's call site.
        if (key_type.kind == TypeKind.STRUCT
                and key_type.struct_name in (getattr(self, 'current_type_params', {}) or {})):
            return None
        if (self._is_trivially_copyable(key_type)
                or self._is_implicit_copy_type(key_type)
                or self._is_explicit_copy_type(key_type)):
            return None
        if self._is_no_copy_type(key_type):
            return "is NoCopy"
        return "owns a Deinit without a copy (it is move-only, not retainable)"

    def _check_map_key_copyable(self, key_type, expr, what="map key"):
        reason = self._key_copyable_reason(key_type)
        if reason is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{what} type `{key_type}` must be copyable (trivial, ImplicitCopy, "
                f"or ExplicitCopy with retain semantics): `{key_type}` {reason}",
                expr.line, expr.column)

    def _check_map_key_bounds(self, key_type, expr, what="map key"):
        """A map key / set element type must be Hashable + Equatable (design
        54, same bound as constructing the container) AND copyable-with-retain
        (design 65 followup: the container probes keys by copy)."""
        if key_type is None:
            return
        for bound in ("Hashable", "Equatable"):
            if not self._bound_satisfied(key_type, bound):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} type `{key_type}` must be `{bound}` "
                    f"(map keys and set elements require Hashable + Equatable)",
                    expr.line, expr.column)
                return
        self._check_map_key_copyable(key_type, expr, what)

    def _check_array_index(self, expr: ArrayIndex) -> Optional[SawType]:
        """Check array or tuple indexing with [index] syntax."""
        container_type = self._check_expression(expr.array_expr)
        if container_type is None:
            return None
        # design 46: index projection through a `UnsafeMemory<[E; N], Use>`
        # region yields `UnsafeMemory<E, Use>` at base + i*stride (no load).
        if self._is_unsafe_memory(container_type):
            return self._check_um_index_projection(expr, container_type)
        # design 141: a struct may declare `func [](...) borrows -> T`, which
        # makes `v[i]` a PLACE. Intercept before the Int-index rule below — an
        # accessor's parameter is whatever it declared (`Map.[]` takes a key),
        # and its own checking happens against that declaration.
        if container_type.kind == TypeKind.STRUCT:
            place = self._check_place_index(expr, container_type)
            if place is not None:
                return place
        index_type = self._check_expression(expr.index)
        if index_type is None:
            return None
        index_underlying = self._get_underlying_type(index_type)
        if index_underlying.kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column
            )
            return None
        if container_type.kind == TypeKind.ARRAY:
            # Reject out-of-range compile-time constant indices, mirroring the
            # tuple-index path below. Dynamic indices stay unchecked.
            if isinstance(expr.index, IntLiteral) and container_type.array_size is not None:
                if expr.index.value < 0 or expr.index.value >= container_type.array_size:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"array index {expr.index.value} out of range for array with "
                        f"{container_type.array_size} elements",
                        expr.line, expr.column
                    )
                    return None
            return container_type.array_element_type
        elif container_type.kind == TypeKind.TUPLE:
            if not isinstance(expr.index, IntLiteral):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "tuple index must be a compile-time constant",
                    expr.index.line, expr.index.column
                )
                return None
            index = expr.index.value
            if container_type.element_types is None:
                return None
            if index < 0 or index >= len(container_type.element_types):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple index {index} out of range for tuple with {len(container_type.element_types)} elements",
                    expr.line, expr.column
                )
                return None
            return container_type.element_types[index]
        elif container_type.kind == TypeKind.POINTER:
            # Raw-pointer deref. Reaching a pointer to index it already marked
            # the enclosing function under the design-130 trigger rule, so the
            # deref itself carries no separate obligation.
            return container_type.inner_type
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into type `{container_type}`",
                expr.line, expr.column
            )
            return None

    # =====================================================================
    # UnsafeMemory<T, Use> — typed memory at a fixed address (design 46)
    # =====================================================================

    # Types that a Device register view may `read()`/`write()`: whole-struct and
    # whole-array access is forbidden (multi-register access is never atomic).
    _UM_SCALAR_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT, TypeKind.BOOL, TypeKind.FLOAT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    })

    def _is_unsafe_memory(self, t: Optional[SawType]) -> bool:
        return (t is not None and t.kind == TypeKind.STRUCT
                and t.struct_name == "UnsafeMemory")

    def _um_view_and_use(self, t: SawType):
        """(viewed-type T, Use-marker) for a `UnsafeMemory<T, Use>`; (None, None)
        if the type is not fully parameterized."""
        args = t.type_args or []
        if len(args) < 2:
            return (None, None)
        return (args[0], args[1])

    def _um_use_name(self, use: Optional[SawType]) -> Optional[str]:
        if use is not None and use.kind == TypeKind.STRUCT:
            return use.struct_name
        return None

    def _um_unwrap_marker(self, view: SawType):
        """Peel a `ReadOnly<T>`/`WriteOnly<T>` field marker off a projected view,
        returning `(inner_scalar_type, mode)` with mode in {'ro','wo','rw'}."""
        if (view is not None and view.kind == TypeKind.STRUCT
                and view.struct_name in ("ReadOnly", "WriteOnly")
                and view.type_args):
            mode = 'ro' if view.struct_name == "ReadOnly" else 'wo'
            return (view.type_args[0], mode)
        return (view, 'rw')

    def _um_is_scalar(self, t: SawType) -> bool:
        return t is not None and t.kind in self._UM_SCALAR_KINDS

    def _validate_unsafe_memory_type(self, t: SawType, line: int, column: int) -> bool:
        """Enforce the shape `UnsafeMemory<T, Use>` with `Use` an EXPLICIT intent
        marker (`Device` or `Normal`) — no default (design 46)."""
        args = t.type_args or []
        if len(args) != 2:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`UnsafeMemory` takes exactly two type arguments: the viewed type "
                "and the intent marker `Device` or `Normal`",
                line, column,
                hint="the intent marker is EXPLICIT — write `UnsafeMemory<T, Device>` "
                     "or `UnsafeMemory<T, Normal>`"
            )
            return False
        use_name = self._um_use_name(args[1])
        if use_name not in ("Device", "Normal"):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"the intent marker of `UnsafeMemory` must be `Device` or `Normal`, "
                f"got `{args[1]}`",
                line, column,
                hint="`Device` = volatile register block; `Normal` = plain RAM region"
            )
            return False
        return True

    def _check_um_projection(self, expr: MemberAccess, um_type: SawType) -> Optional[SawType]:
        """Project `UM<Struct, Use>.field` -> `UM<Field, Use>` (design 46)."""
        view, use = self._um_view_and_use(um_type)
        if view is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot project through an under-specified `UnsafeMemory` type",
                expr.line, expr.column)
            return None
        if view.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access field `{expr.member}` — the memory views `{view}`, "
                f"not a struct",
                expr.line, expr.column)
            return None
        struct_info = self.get_struct_info(view.struct_name, from_type=view)
        if struct_info is None or expr.member not in struct_info.fields:
            avail = ', '.join(struct_info.field_order) if struct_info else ''
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{view.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {avail}" if avail else None)
            return None
        field_type = self._resolve_type(struct_info.fields[expr.member])
        expr.um_projection = True
        return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                       type_args=[field_type, use])

    def _check_um_index_projection(self, expr: ArrayIndex, um_type: SawType) -> Optional[SawType]:
        """Project `UM<[E; N], Use>[i]` -> `UM<E, Use>` (design 46)."""
        view, use = self._um_view_and_use(um_type)
        index_type = self._check_expression(expr.index)
        if index_type is not None and self._get_underlying_type(index_type).kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column)
            return None
        if view is None or view.kind != TypeKind.ARRAY:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index a `UnsafeMemory` view of non-array type `{view}`",
                expr.line, expr.column)
            return None
        if (isinstance(expr.index, IntLiteral) and view.array_size is not None
                and (expr.index.value < 0 or expr.index.value >= view.array_size)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"array index {expr.index.value} out of range for region with "
                f"{view.array_size} elements",
                expr.line, expr.column)
            return None
        expr.um_projection = True
        return SawType(TypeKind.STRUCT, struct_name="UnsafeMemory",
                       type_args=[view.array_element_type, use])

    def _check_um_method(self, expr: MethodCall, um_type: SawType) -> Optional[SawType]:
        """Check a `read`/`write`/`ptr`/`len`/`end` accessor on `UnsafeMemory`."""
        view, use = self._um_view_and_use(um_type)
        use_name = self._um_use_name(use)
        method = expr.method_name
        if view is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot access an under-specified `UnsafeMemory` value",
                expr.line, expr.column)
            return None
        expr.um_volatile = (use_name == "Device")

        if method in ("read", "write"):
            inner, mode = self._um_unwrap_marker(view)
            if use_name == "Device":
                if not self._um_is_scalar(inner):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Device memory has no whole-`{view}` access — multi-register "
                        f"access is never atomic; project a scalar register field",
                        expr.line, expr.column,
                        hint="access one register at a time (`REGS.field.read()`)")
                    return None
                if method == "read" and mode == 'wo':
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot `read()` a `WriteOnly` register",
                        expr.line, expr.column)
                    return None
                if method == "write" and mode == 'ro':
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot `write()` a `ReadOnly` register",
                        expr.line, expr.column)
                    return None
            else:
                # Normal: plain access; whole-struct / element allowed. Markers
                # are a Device-only concept, so the inner type is the view itself.
                inner = view
            expr.um_method = method
            expr.um_scalar_type = inner
            if method == "read":
                if len(expr.arguments) != 0:
                    self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                                "`read()` takes no arguments", expr.line, expr.column)
                    return None
                return inner
            # write(v)
            if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
                self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                            "`write(v)` takes exactly one positional argument",
                            expr.line, expr.column)
                return None
            val_type = self._check_expression(expr.arguments[0].value)
            if val_type is not None and not self._types_compatible(val_type, inner):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`write` expects `{inner}`, got `{val_type}`",
                    expr.line, expr.column)
            return SawType(TypeKind.VOID)

        # Region accessors — Normal only.
        if method in ("ptr", "len", "end"):
            if use_name != "Normal":
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{method}()` is a `Normal` region accessor; it is not available "
                    f"on `Device` memory",
                    expr.line, expr.column,
                    hint="Device registers are accessed with `read()`/`write()`")
                return None
            if len(expr.arguments) != 0:
                self._error(ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"`{method}()` takes no arguments", expr.line, expr.column)
                return None
            expr.um_method = method
            if method == "ptr":
                return SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.INT8), pointer_mutable=True)
            if method == "end":
                return SawType(TypeKind.POINTER,
                               inner_type=SawType(TypeKind.INT8), pointer_mutable=True)
            # len(): region byte length
            if view.kind != TypeKind.ARRAY:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`len()` needs an array region view, got `{view}`",
                    expr.line, expr.column)
                return None
            return SawType(TypeKind.INT)

        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"`UnsafeMemory` has no method `{method}`",
            expr.line, expr.column,
            hint="Device: `read()`/`write(v)`; Normal: also `ptr()`/`len()`/`end()`")
        return None

    def _check_field_visible(self, struct_info, field_name: str,
                             type_name: str, expr) -> None:
        """Member visibility gate (design 80): a struct field is private-by-default
        outside its defining module. Compiler-synthesized access is exempt by
        provenance — the gate enforces SOURCE-level access only.

        Provenance comes from the enclosing function alone. There was also a
        per-node `synthesized_access` flag tested here, but nothing in the
        compiler ever set it (design 126 R1 removed it): it read as a second
        exemption route and was always False."""
        if self._in_synthesized_context():
            return
        def_module = getattr(struct_info, 'def_module', ())
        fv = getattr(struct_info, 'field_visibility', None) or {}
        vis = fv.get(field_name, Visibility.PRIVATE)
        if not self._member_gate_allows(def_module, vis):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"field `{field_name}` of struct `{type_name}` is {self._vis_word(vis)} "
                f"and not accessible from this module",
                expr.line, expr.column,
                hint=f"mark it `public` in the declaration of `{type_name}` to expose it")

    def _check_method_visible(self, struct_name: str, method_name: str,
                              method_info, expr) -> None:
        """Member visibility gate (design 80) for an extension method / init /
        static. Private-by-default outside the defining module; a method that
        satisfies a conformed trait's requirement is always callable (trait
        dispatch). A synthesized enclosing function is exempt by provenance."""
        if method_info is None:
            return
        if self._in_synthesized_context():
            return
        if getattr(method_info, 'satisfies_trait', False):
            return
        def_module = getattr(method_info, 'def_module', ())
        vis = getattr(method_info, 'visibility', Visibility.PRIVATE)
        if not self._member_gate_allows(def_module, vis):
            kind = "initializer" if getattr(method_info, 'is_init', False) else \
                   ("static method" if getattr(method_info, 'is_static', False)
                    else "method")
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{kind} `{method_name}` of `{struct_name}` is {self._vis_word(vis)} "
                f"and not accessible from this module",
                expr.line, expr.column,
                hint=f"mark it `public` in the extension of `{struct_name}` to expose it")

    def _check_member_access(self, expr: MemberAccess) -> Optional[SawType]:
        """Check member access for struct fields, enum variants, or module symbols."""
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
            # Design 40 item 3 (L6): this recursion bypasses the
            # `_check_expression` chokepoint, so the nested module-qualified
            # object node would otherwise reach codegen without a
            # `resolved_type`. Stamp it here (the module member-access checker)
            # so signedness/type-driven lowering never falls back for these.
            if obj_type is not None:
                expr.object.resolved_type = obj_type
            if obj_type and obj_type.kind == TypeKind.MODULE:
                inner_module_sym = getattr(expr.object, 'resolved_module_symbol', None)
                if inner_module_sym and inner_module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = inner_module_sym.namespace.resolve(
                        expr.member, check_visibility=True, accessor_module=()
                    )
                    if symbol is None:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"module `{obj_type.module_name}` has no symbol `{expr.member}`",
                            expr.line, expr.column
                        )
                        return None
                    if symbol.kind == SymbolKind.STRUCT:
                        # Design 144: carry the identity, not the spelling.
                        _id = getattr(symbol, 'type_identity', "") or expr.member
                        expr.resolved_struct_name = _id
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.STRUCT, struct_name=_id, symbol=symbol)
                    elif symbol.kind == SymbolKind.ENUM:
                        _id = getattr(symbol, 'type_identity', "") or expr.member
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.ENUM, enum_name=_id, symbol=symbol)
                    elif symbol.kind == SymbolKind.FUNCTION:
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.FUNCTION,
                                     param_types=symbol.param_types,
                                     func_return_type=symbol.return_type)
                    elif symbol.kind == SymbolKind.MODULE:
                        expr.resolved_module_symbol = symbol
                        return SawType(TypeKind.MODULE, module_name=expr.member)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot use `{expr.member}` as an expression",
                            expr.line, expr.column
                        )
                        return None
            elif obj_type and obj_type.kind == TypeKind.ENUM:
                # Handle module-qualified enum variant access: lib.Color.Red
                enum_info = self.get_enum_info(obj_type.enum_name, from_type=obj_type)
                if enum_info:
                    type_args = obj_type.type_args
                    if expr.member in enum_info.variants:
                        variant_params = enum_info.variants[expr.member]
                        if len(variant_params) == 0:
                            # Constructs a value rather than reading one out of
                            # storage — see the unqualified path (design 139).
                            expr.enum_variant_literal = True
                            self._stamp_enum_raw_value(expr, enum_info)
                            _eid = self._sym_identity(enum_info,
                                                      obj_type.enum_name)
                            expr.resolved_type_identity = _eid
                            result = SawType(TypeKind.ENUM, enum_name=_eid, type_args=type_args, symbol=enum_info)
                            # Preserve module resolution info for codegen
                            if getattr(expr.object, 'resolved_module', None) is not None:
                                expr.resolved_module = expr.object.resolved_module
                            return result
                        else:
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"variant `{expr.member}` has associated values and must be called like `{obj_type.enum_name}.{expr.member}(...)`",
                                expr.line, expr.column
                            )
                            return None
                    else:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"enum `{obj_type.enum_name}` has no variant `{expr.member}`",
                            expr.line, expr.column
                        )
                        return None
        if isinstance(expr.object, Identifier):
            # Design 53: integer limits `Int.max` / `Int.min` and `.max`/`.min`
            # on every fixed-width type. The result has the named integer type;
            # the platform-`Int` bounds are materialized at codegen (target word).
            limit_kind = self._INT_LIMIT_TYPE_KINDS.get(expr.object.name)
            if limit_kind is not None and expr.member in ("max", "min"):
                expr.int_limit = (expr.object.name, expr.member)
                return SawType(limit_kind)

            # Design 150 pin 4: a value binding of this name wins; the qualifier
            # is consulted last.
            module_sym = self._module_qualifier(expr.object.name)
            if module_sym and module_sym.namespace:
                from namespace import SymbolKind
                symbol = module_sym.namespace.resolve(
                    expr.member, check_visibility=True, accessor_module=()
                )
                if symbol is None:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"module `{expr.object.name}` has no symbol `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None
                if symbol.kind == SymbolKind.STATIC:
                    # Module-qualified static read (design 41): `mod.NAME`. Codegen
                    # resolves the same static in the merged namespace by simple
                    # name, so tag the member for it and read like a binding.
                    expr.resolved_static_name = expr.member
                    expr.resolved_module = expr.object.name
                    # design 149: naming an `unsafe static var` is unsafe
                    # contact through the qualified spelling too.
                    if getattr(symbol, 'is_var', False):
                        self._note_unsafe_static_contact(
                            f"{expr.object.name}.{expr.member}", expr)
                    return symbol.type
                if symbol.kind == SymbolKind.STRUCT:
                    # Design 144: carry the identity, not the spelling.
                    _id = getattr(symbol, 'type_identity', "") or expr.member
                    expr.resolved_struct_name = _id
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.STRUCT, struct_name=_id, symbol=symbol)
                elif symbol.kind == SymbolKind.ENUM:
                    _id = getattr(symbol, 'type_identity', "") or expr.member
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.ENUM, enum_name=_id, symbol=symbol)
                elif symbol.kind == SymbolKind.FUNCTION:
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.FUNCTION,
                                 param_types=symbol.param_types,
                                 func_return_type=symbol.return_type)
                elif symbol.kind == SymbolKind.MODULE:
                    expr.resolved_module_symbol = symbol
                    return SawType(TypeKind.MODULE, module_name=expr.member)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot use `{expr.member}` as an expression",
                        expr.line, expr.column
                    )
                    return None
            enum_info = self.get_enum_info(expr.object.name)
            if enum_info:
                type_args = expr.object.type_args
                if enum_info.type_params:
                    if not type_args:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"generic enum `{expr.object.name}` requires type arguments",
                            expr.line, expr.column,
                            hint=f"use `{expr.object.name}<...>.{expr.member}`"
                        )
                    elif len(type_args) != len(enum_info.type_params):
                        self._error(
                            ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"expected {len(enum_info.type_params)} type argument(s), got {len(type_args)}",
                            expr.line, expr.column
                        )
                if expr.member in enum_info.variants:
                    variant_params = enum_info.variants[expr.member]
                    if len(variant_params) == 0:
                        # A payload-free variant CONSTRUCTS a value; it does not
                        # read one out of storage (design 139).
                        expr.enum_variant_literal = True
                        self._stamp_enum_raw_value(expr, enum_info)
                        expr.resolved_type_identity = self._sym_identity(
                            enum_info, expr.object.name)
                        return SawType(TypeKind.ENUM,
                                       enum_name=expr.resolved_type_identity,
                                       type_args=type_args, symbol=enum_info)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"variant `{expr.member}` has associated values and must be called like `{expr.object.name}.{expr.member}(...)`",
                            expr.line, expr.column
                        )
                        return None
                else:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"enum `{expr.object.name}` has no variant `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None
        # Named-tuple field access (design 63): `p.x` resolves to the position of
        # `x` in the tuple's label list, returning that element's type. Positional
        # `.0` / `[0]` keep working via the tuple-index path.
        obj_resolved = self._resolve_type_alias(obj_type)
        if (obj_resolved.kind == TypeKind.TUPLE and obj_resolved.tuple_field_names
                and expr.member in obj_resolved.tuple_field_names):
            idx = obj_resolved.tuple_field_names.index(expr.member)
            expr.tuple_field_index = idx  # stamp for codegen
            return obj_resolved.element_types[idx]
        # A distinct `type` over a non-struct underlying (e.g. `type MyInt = Int`)
        # has no fields, and the `.value` underlying-accessor is not a language
        # feature (the spec labels it planned/illustrative, ledger L16). Accessing
        # a member on one used to reach codegen and ICE ("Cannot find field ...
        # in struct with type i64"); emit a clean typechecker error instead. (A
        # distinct alias of a struct falls through to the normal field check.)
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name is not None:
            alias_sym = self.get_type_alias_info(obj_type.struct_name)
            if alias_sym is not None:
                underlying = self._resolve_type_alias(obj_type)
                if underlying is None or underlying.kind != TypeKind.STRUCT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot access member `{expr.member}` on the distinct "
                        f"type `{obj_type.struct_name}`: it has no fields and there "
                        f"is no `.value` accessor — a distinct type flows to its "
                        f"underlying type implicitly (use it directly), or project "
                        f"it explicitly with a cast like `x as {underlying}`",
                        expr.line, expr.column,
                    )
                    return None
        # design 46: member access on `UnsafeMemory<Struct, Use>` PROJECTS to
        # `UnsafeMemory<Field, Use>` at base + compile-time offset — the shared
        # projection engine. No memory is loaded.
        if self._is_unsafe_memory(obj_type):
            return self._check_um_projection(expr, obj_type)
        if obj_type.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if obj_type.struct_name is None:
            return None
        struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            # Design 150 pin 4: name the shadowing declaration when one took the
            # qualifier this projection was reaching for.
            shadow = self._qualifier_shadow_hint(expr.object, expr.member)
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{obj_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=shadow or
                     f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        self._check_field_visible(struct_info, expr.member,
                                  obj_type.struct_name, expr)
        # Resolve the field type (e.g., convert STRUCT to ENUM if needed).
        field_type = struct_info.fields[expr.member]
        # design 74 (A5-rest, shape 2): if the receiver is a concrete instantiation
        # of a GENERIC struct but `struct_info` is the generic symbol (its fields
        # carry the abstract `T`), substitute the struct's type params with the
        # receiver's type args so `self.value` on a `Holder<Int>` resolves to `Int`.
        # Normal instantiations carry a monomorphized symbol (concrete fields, no
        # type_params) and skip this.
        tps = getattr(struct_info, 'type_params', None)
        if tps and getattr(obj_type, 'type_args', None):
            type_map = {tp.name: arg for tp, arg in zip(tps, obj_type.type_args)}
            if type_map:
                field_type = field_type.substitute(type_map)
        return self._resolve_type(field_type)

    def _check_init_field_value(self, value, expected_type: Optional[SawType]) -> Optional[SawType]:
        """Type-check a struct-init field/init-argument value.

        When the field/parameter type is a function type and the value is a
        closure literal, infer the closure's parameter types from that expected
        type — mirroring the call-argument path in `_check_field_call`
        (`{ $0 * 2 }` gets its `$0: Int` from the field's `(Int) -> ...`). A
        closure stored in a struct field escapes its creating frame, so it is
        NOT treated as a direct call argument (`as_call_argument` stays False),
        which correctly routes it through escaping-closure heap-env handling.
        """
        if (isinstance(value, ClosureExpr) and expected_type is not None
                and expected_type.kind == TypeKind.FUNCTION):
            return self._check_closure(value, expected_type)
        # design 54: a collection/array literal in a struct field gets the field
        # type as its expected type (build a Vector/Map/Set, custom allocator).
        self._apply_literal_expected_type(value, expected_type)
        return self._check_expression(value)

    def _fill_or_report_type_args(self, provided, type_params, what, line, column):
        """Design 37 — validate type-argument arity, filling omitted trailing
        arguments from their declared defaults.

        Returns the fully-applied argument list (length == len(type_params)), or
        None after reporting a precise arity error. `what` is a noun phrase such
        as ``struct `Vector` ``. Too many args, or too few with no default on a
        missing trailing parameter, are the two error cases of design 37 item 1.
        """
        n = len(type_params)
        provided = list(provided or [])
        if len(provided) == n:
            return self._finish_type_args(provided, type_params, what, line, column)
        if len(provided) > n:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"{what} expected {n} type argument(s), got {len(provided)}",
                line, column
            )
            return None
        # Fewer than declared: every omitted trailing parameter must have a
        # default. Defaults are resolved (and thus themselves default-filled).
        missing = type_params[len(provided):]
        if all(getattr(tp, 'default', None) is not None for tp in missing):
            filled = list(provided)
            for tp in missing:
                filled.append(self._resolve_type(tp.default))
            return self._finish_type_args(filled, type_params, what, line, column)
        if not provided:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"generic {what} requires type arguments",
                line, column,
            )
            return None
        first_no_default = next(
            tp for tp in missing if getattr(tp, 'default', None) is None)
        self._error(
            ErrorKind.WRONG_ARGUMENT_COUNT,
            f"{what} expected {n} type argument(s), got {len(provided)} "
            f"(type parameter `{first_no_default.name}` has no default)",
            line, column
        )
        return None

    def _finish_type_args(self, args, type_params, what, line, column):
        """Canonicalize a fully-applied argument list (design 148).

        This is the chokepoint every reference site funnels through, so it is
        where a const argument written as ARITHMETIC becomes a number:
        `Ring<2 * 128>` and `Ring<256>` have to be the same instantiation, and
        they are only if the value is folded before anything mangles or
        monomorphizes it — the same rule design 37 applies to defaults.
        """
        folded = [self._fold_const_arg(a) for a in args]
        self._check_const_arg_kinds(folded, type_params, what, line, column)
        return folded

    def _fold_const_arg(self, arg):
        """Give a CONST_VALUE argument its integer, if it does not have one."""
        if (arg is None or arg.kind != TypeKind.CONST_VALUE
                or arg.const_value is not None):
            return arg
        value = self._try_const_value(arg.array_size_expr)
        if value is None:
            return arg
        import dataclasses
        return dataclasses.replace(arg, const_value=value)

    def _check_const_arg_kinds(self, args, type_params, what, line, column):
        """A const parameter takes a VALUE and a type parameter takes a TYPE.

        Written as its own check (design 148) because the two mistakes read as
        nothing else otherwise: `FixedBuf<Int>` would fail as an undefined
        length somewhere inside the type, and `Vector<4>` as an undefined type
        named `4`. Both are one confusion — the two parameter kinds look alike
        at a use site — so both name the parameter and what it wants.
        """
        for tp, arg in zip(type_params, args):
            if arg is None:
                continue
            is_const_param = getattr(tp, 'is_const', False)
            is_value = arg.kind == TypeKind.CONST_VALUE
            if is_const_param and not is_value:
                # A bare name is how a const parameter is FORWARDED from an
                # enclosing generic (`FixedBuf<N>` inside `extension
                # FixedBuf<N>`), so a name that is one in scope is correct here.
                if (arg.kind == TypeKind.STRUCT
                        and arg.struct_name in self._const_param_types()):
                    continue
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} takes a VALUE for the const parameter "
                    f"`{tp.name}`, and `{arg}` is a type",
                    line, column,
                    hint=f"write a compile-time integer — `{tp.name}` is "
                         f"declared `const {tp.name}: {tp.const_type}`")
            elif is_value and not is_const_param:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{what} takes a TYPE for the parameter `{tp.name}`, and "
                    f"`{arg}` is a value",
                    line, column,
                    hint=f"declare it `const {tp.name}: Int` to take a value")

    _FIXED_INT_RANGES = {
        TypeKind.INT8: (-(1 << 7), (1 << 7) - 1),
        TypeKind.INT16: (-(1 << 15), (1 << 15) - 1),
        TypeKind.INT32: (-(1 << 31), (1 << 31) - 1),
        TypeKind.INT64: (-(1 << 63), (1 << 63) - 1),
        TypeKind.UINT8: (0, (1 << 8) - 1),
        TypeKind.UINT16: (0, (1 << 16) - 1),
        TypeKind.UINT32: (0, (1 << 32) - 1),
        TypeKind.UINT64: (0, (1 << 64) - 1),
    }

    def _int_range_for(self, kind):
        """The inclusive literal range for an integer TypeKind, or None.

        DF-137d / DF-140a: platform `Int`/`UInt` are POINTER-WIDTH (design 47),
        so their range is a fact about the effective target rather than a
        constant. `0x80000000` fits a 64-bit `Int` and does not fit a 32-bit one,
        and until this was checked the riscv32 spelling silently wrapped to
        -2147483648 — on the profile where an address constant at or above
        0x8000_0000 is the most ordinary thing a kernel writes.
        """
        fixed = self._FIXED_INT_RANGES.get(kind)
        if fixed is not None:
            return fixed
        w = getattr(self, 'platform_int_width', 64)
        if kind == TypeKind.INT:
            return (-(1 << (w - 1)), (1 << (w - 1)) - 1)
        if kind == TypeKind.UINT:
            return (0, (1 << w) - 1)
        return None

    def _fixed_width_binop_type(self, expr, left_type, right_type):
        """Arithmetic (`+ - * / %`) mixing a BARE integer literal with a
        fixed-width integer operand: the literal adopts the fixed-width type, so
        the result is that type (not platform `Int`) and codegen materializes the
        literal at that width (design 77 item 9 extended from comparison to
        arithmetic position; the design-81-run rider). Range-checks the literal
        (`b + 999` for `b: Int32` past the width is a clean error). Both operand
        orders. Returns the fixed-width type, or None when the rule does not apply
        (e.g. Int/Int, or two fixed-width operands — those keep the existing
        behavior)."""
        lu = self._get_underlying_type(left_type)
        ru = self._get_underlying_type(right_type)
        left_lit = (isinstance(expr.left, IntLiteral)
                    and getattr(expr.left, 'suffix', None) is None)
        right_lit = (isinstance(expr.right, IntLiteral)
                     and getattr(expr.right, 'suffix', None) is None)
        # A bare literal + a fixed-width operand -> the fixed-width type. If BOTH
        # are bare literals neither is fixed-width, so this never fires there.
        if right_lit and lu.kind in self._FIXED_INT_RANGES:
            self._check_fixed_width_literal(
                expr.right, left_type,
                getattr(expr.right, 'line', expr.line),
                getattr(expr.right, 'column', expr.column))
            return left_type
        if left_lit and ru.kind in self._FIXED_INT_RANGES:
            self._check_fixed_width_literal(
                expr.left, right_type,
                getattr(expr.left, 'line', expr.line),
                getattr(expr.left, 'column', expr.column))
            return right_type
        return None

    def _check_fixed_width_literal(self, value_expr, expected_type, line, column):
        """Reject a bare integer literal that does not fit a fixed-width integer
        target (design 65 followup). A literal adopts the field's type exactly, so
        `Rec(tag: 999)` with `tag: Int8` is a clean range error here rather than a
        codegen ICE. Suffixed literals are already range-checked at lex time.

        DF-137d / DF-140a: platform `Int`/`UInt` are checked here too now, against
        the EFFECTIVE target's pointer width — they used to be skipped entirely,
        so a literal too large for a 32-bit `Int` wrapped in silence."""
        if not isinstance(value_expr, IntLiteral) or getattr(value_expr, 'suffix', None):
            return
        rt = self._resolve_type(expected_type) if expected_type is not None else None
        rng = self._int_range_for(rt.kind) if rt is not None else None
        if rng is None:
            return
        lo, hi = rng
        if not (lo <= value_expr.value <= hi):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {value_expr.value} does not fit in "
                f"`{expected_type}` (range {lo}..={hi})",
                line, column)

    def _reinterpret_struct_init_as_call(self, expr: StructInit):
        """Design 66: if `expr.struct_name` names a FUNCTION (free or overloaded),
        build the equivalent fully-labeled `FunctionCall` from the struct-init's
        field inits so a labeled call `f(a: 1, b: 2)` — which the parser routes
        to StructInit — resolves as a call. Returns the FunctionCall, or None
        when the name is not a callable function."""
        name = expr.struct_name
        # The name must be callable-but-not-a-struct: a free/overloaded function,
        # an in-scope binding (a closure value), or a constructible type param.
        # A genuinely-unknown name keeps the "undefined struct" diagnostic.
        is_callable = (
            (self.get_function_info(name) is not None
             or len(self.namespace.lookup_function_overloads(name)) >= 1)
            and self.namespace.is_accessible(name)
        ) or (self.current_scope.lookup(name) is not None) \
          or (name in getattr(self, 'current_type_params', {}))
        if not is_callable:
            return None
        from ast_nodes import FunctionCall as _FC, Argument as _Arg, ReferenceExpr as _Ref
        args = []
        for (n, v) in expr.field_inits:
            # A `&`/`&var` value is only legal in argument position (design 34);
            # struct-init parsing did not mark it, so mark it now that we know
            # this is a call.
            if isinstance(v, _Ref):
                v.in_argument_position = True
            args.append(_Arg(value=v, name=n))
        fc = _FC(name=name, arguments=args, type_args=expr.type_args,
                 line=expr.line, column=expr.column)
        return fc

    def _check_struct_init(self, expr: StructInit) -> Optional[SawType]:
        """Check struct initialization with parameter-based resolution."""
        # Prelude discipline (design 82 Part B): a bare `IoError(...)` /
        # `Data(...)` for a non-prelude std type not imported here is rejected
        # with an import hint (unless it is a labeled call to a function — that
        # reinterpretation still happens below when the name is not a std type).
        if (expr.struct_name in getattr(self, '_std_symbol_file', {})
                and self._std_name_gated(expr.struct_name, expr.line, expr.column)):
            return None
        struct_info = self.get_struct_info(expr.struct_name)
        if struct_info is None:
            # Design 66: `name(label: value, ...)` is syntactically identical to
            # struct init; the parser eagerly builds a StructInit. When the name
            # is actually a FUNCTION (not a struct), this is a fully-labeled
            # function call — reinterpret it as one and delegate. Codegen reads
            # `expr.as_function_call` to emit the call instead of a struct build.
            fc = self._reinterpret_struct_init_as_call(expr)
            if fc is not None:
                expr.as_function_call = fc
                return self._check_function_call(fc)
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None
        # Design 144: `StructInit.struct_name` is a type REFERENCE, so from here
        # on it names the resolved type's identity — codegen builds the layout
        # it was handed rather than re-resolving `Header` against a merged
        # namespace where two of them live.
        expr.struct_name = (getattr(struct_info, 'type_identity', "")
                            or expr.struct_name)
        type_mapping: Dict[str, SawType] = {}
        if struct_info.type_params:
            filled_args = self._fill_or_report_type_args(
                expr.type_args, struct_info.type_params,
                f"struct `{expr.struct_name}`", expr.line, expr.column)
            if filled_args is not None:
                # Canonicalize the node's type args to the fully-applied form
                # (design 37) so codegen mangles the same identity the
                # typechecker validated — `Vector<Int>` and `Vector<Int, Global>`
                # share one monomorphization.
                expr.type_args = filled_args
                for type_param, type_arg in zip(struct_info.type_params, filled_args):
                    resolved_arg = self._resolve_type(type_arg)
                    type_mapping[type_param.name] = type_arg
                    # Enforce the struct's declared type-param bounds at
                    # construction (e.g. `Channel<T: Send>` requires a Send `T`),
                    # so a non-conforming instantiation is rejected here rather
                    # than surfacing as a missing monomorphization in codegen.
                    for bound in getattr(type_param, 'bounds', None) or []:
                        if self.get_trait_info(bound) is None:
                            continue  # unknown trait name reported elsewhere
                        if not self._bound_satisfied(resolved_arg, bound):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type argument `{resolved_arg}` does not satisfy "
                                f"bound `{type_param.name}: {bound}` on struct "
                                f"`{expr.struct_name}`",
                                expr.line, expr.column
                            )
        # design 65 (L19): a Map/Set KEY must be copyable-with-retain — the
        # container probes keys by copy (hash / compare / slot inspection), which
        # a NoCopy or move-only-Deinit key cannot balance. Checked here at
        # construction; VALUES are unaffected. Set delegates to Map internally,
        # but this fires at the user-facing `Set<T>()` site; the internal
        # `Map<T, SetMark>` in set.saw is checked with a GENERIC T and passes.
        if expr.struct_name in ("Map", "Set") and expr.type_args:
            self._check_map_key_copyable(
                self._resolve_type(expr.type_args[0]), expr,
                "map key" if expr.struct_name == "Map" else "set element")
        provided_params = {field_name for field_name, _ in expr.field_inits}
        field_names = set(struct_info.fields.keys())
        matches_fields = provided_params == field_names
        matching_inits = []
        # An init matches when the provided named arguments are a subset of its
        # parameters and every omitted parameter carries a default value
        # (design 53). With no defaults this reduces to the exact-set match.
        def _init_matches(method_info):
            init_names = list(method_info.param_names)
            if not provided_params.issubset(set(init_names)):
                return False
            dv = method_info.default_values or []
            name_to_default = dict(zip(init_names, dv))
            return all(name_to_default.get(n) is not None
                       for n in init_names if n not in provided_params)
        # Check for init methods in both methods dict (legacy) and init_methods list (namespace)
        for method_name, method_info in struct_info.methods.items():
            if method_info.is_init and _init_matches(method_info):
                matching_inits.append(method_info)
        # Also check init_methods list (for StructSymbol from namespace)
        if hasattr(struct_info, 'init_methods'):
            for method_info in struct_info.init_methods:
                if _init_matches(method_info):
                    matching_inits.append(method_info)
        total_matches = (1 if matches_fields else 0) + len(matching_inits)
        if total_matches == 0:
            # Collect available init methods from both methods dict and init_methods list
            available_inits = [m.param_names for m in struct_info.methods.values() if m.is_init]
            if hasattr(struct_info, 'init_methods'):
                available_inits.extend([m.param_names for m in struct_info.init_methods])
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{expr.struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {available_inits}" if available_inits else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args, symbol=struct_info)
        elif total_matches > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{expr.struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args, symbol=struct_info)
        if matches_fields:
            # Member visibility (design 80): memberwise struct-literal construction
            # cross-module requires ALL fields visible (else use a visible init).
            # Runs after the design-66 function-call reinterpretation above, so it
            # only fires for a genuine struct literal. (`_check_field_visible`
            # itself exempts a synthesized enclosing function.)
            for _fname in struct_info.field_order:
                self._check_field_visible(struct_info, _fname,
                                          expr.struct_name, expr)
            expr.resolved_init_params = None
            for field_name, field_value in expr.field_inits:
                declared_type = struct_info.fields[field_name]
                expected_type = declared_type
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                if expected_type.kind == TypeKind.OPTIONAL and isinstance(field_value, NoneLiteral):
                    field_value.resolved_type = expected_type
                allow_wrap = self._df3_allow_wrap(
                    declared_type, set(type_mapping.keys()) if type_mapping else None)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type, allow_wrap):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "struct field",
                                           field_value.line, field_value.column)
        else:
            method_info = matching_inits[0]
            # Member visibility (design 80): gate a custom initializer cross-module.
            self._check_method_visible(expr.struct_name, "init", method_info, expr)
            # Design 53: fill omitted init parameters from their defaults by
            # appending them as named arguments, so the argument loop and codegen
            # see a complete set (evaluated per call, like an explicit argument).
            provided_now = {fn for fn, _ in expr.field_inits}
            _dv = method_info.default_values or []
            _n2d = dict(zip(method_info.param_names, _dv))
            for pname in method_info.param_names:
                if pname not in provided_now and _n2d.get(pname) is not None:
                    expr.field_inits.append((pname, _n2d[pname]))
            expr.resolved_init_params = method_info.param_names
            # design 24 item 3: a custom `init` runs user code — record the
            # suspend-graph edge to it.
            self._effect_call_method(
                method_info, f"`{expr.struct_name}.init`", expr.line)
            init_values = []
            init_param_types = []
            init_param_names = []
            for field_name, field_value in expr.field_inits:
                param_idx = method_info.param_names.index(field_name)
                declared_type = method_info.param_types[param_idx]
                expected_type = declared_type
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                allow_wrap = self._df3_allow_wrap(
                    declared_type, set(type_mapping.keys()) if type_mapping else None)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type, allow_wrap):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"parameter `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "init argument",
                                           field_value.line, field_value.column)
                init_values.append(field_value)
                init_param_types.append(expected_type)
                init_param_names.append(field_name)
            self._check_call_exclusivity(init_values, init_param_types,
                                         param_names=init_param_names)
        return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args, symbol=struct_info)

    def _check_none_literal(self, expr: NoneLiteral) -> Optional[SawType]:
        """Check None literal - returns a special 'None' type that can unify with any T?."""
        return SawType(TypeKind.OPTIONAL, inner_type=None)

    def _propagate_optional_type(self, expr: Expression, expected_type: SawType):
        """Propagate expected optional type to None literals in an expression tree."""
        if expr is None:
            return
        if isinstance(expr, NoneLiteral):
            expr.resolved_type = expected_type
        elif isinstance(expr, IfExpr):
            if expr.then_branch and expr.then_branch.final_expr:
                self._propagate_optional_type(expr.then_branch.final_expr, expected_type)
            if expr.else_branch and expr.else_branch.final_expr:
                self._propagate_optional_type(expr.else_branch.final_expr, expected_type)
        elif isinstance(expr, IfLetExpr):
            if expr.then_branch and expr.then_branch.final_expr:
                self._propagate_optional_type(expr.then_branch.final_expr, expected_type)
            if expr.else_branch and expr.else_branch.final_expr:
                self._propagate_optional_type(expr.else_branch.final_expr, expected_type)
        elif isinstance(expr, MatchExpr):
            for arm in expr.arms:
                body = arm.body
                if body is None:
                    continue
                # A match arm body is either a Block (propagate into its tail) or
                # a bare expression (propagate directly) — e.g. `case Occupied(k,v)
                # -> v` in an optional-returning function (design 48).
                if isinstance(body, Block):
                    if body.final_expr:
                        self._propagate_optional_type(body.final_expr, expected_type)
                else:
                    self._propagate_optional_type(body, expected_type)
        elif isinstance(expr, Block):
            if expr.final_expr:
                self._propagate_optional_type(expr.final_expr, expected_type)

    def _annotate_none_in_block(self, block: Block, resolved_type: SawType):
        """Annotate any NoneLiteral in the block's final expression with its resolved type."""
        if block.final_expr is not None:
            self._propagate_optional_type(block.final_expr, resolved_type)

    def _annotate_none_in_expr(self, expr: Expression, resolved_type: SawType):
        """Recursively find and annotate NoneLiteral nodes with their resolved type."""
        self._propagate_optional_type(expr, resolved_type)

    def _check_force_unwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        """Check force unwrap: expr! - unwraps T? to T."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None
        if inner_type.kind == TypeKind.STRUCT and self.get_type_alias_info(inner_type.struct_name):
            underlying = self._get_underlying_type(inner_type)
            if underlying.kind == TypeKind.OPTIONAL:
                return underlying.inner_type
        if inner_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot force unwrap non-optional type `{inner_type}`",
                expr.line, expr.column
            )
            return inner_type
        return inner_type.inner_type

    def _check_optional_take(self, expr: MethodCall,
                             opt_type: SawType) -> Optional[SawType]:
        """Check `o.take()` — `Optional.take(&var self) -> T?` (design 131).

        The runtime consuming read: it writes `None` into the place and returns
        what was there, owned. Because the write is a real store rather than a
        static retirement, it reaches places `move` cannot — above all a struct
        FIELD, where no-partial-moves forbids `move h.s` and design 131's
        `move h.s!` with it.

        Checked like any `&var self` method: the receiver must be a mutable
        place, and its path joins the enclosing call's exclusivity entries.
        """
        if expr.arguments:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`take()` takes no arguments, got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None
        if not self._is_lvalue(expr.object):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`take()` needs a place to write `None` back into",
                expr.line, expr.column,
                hint="call it on a variable, field, or element — the payload of "
                     "a temporary is already yours, so read it with `!`"
            )
            return None
        imm_root = self._assign_target_immutable_struct_root(expr.object)
        if imm_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot call `take()` on immutable variable `{imm_root}`: "
                f"it writes `None` back into the place",
                expr.line, expr.column,
                hint="consider using `var` instead of `let` to make it mutable",
            )
        # Mark for codegen and for the enclosing call's exclusivity sweep: a
        # by-value argument that TAKES is a mutable access to its receiver path.
        expr.optional_take = True
        self._check_call_exclusivity([], [], receiver=expr.object,
                                     receiver_mutable=True)
        return opt_type

    def _check_nil_coalesce(self, expr: NilCoalesce) -> Optional[SawType]:
        """Check nil coalescing: expr ?? default - returns T."""
        opt_type = self._check_expression(expr.expr)
        default_type = self._check_expression(expr.default)
        if opt_type is None or default_type is None:
            return default_type
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"left side of `??` must be optional, got `{opt_type}`",
                expr.line, expr.column
            )
            return opt_type
        if opt_type.inner_type and not self._types_compatible(opt_type.inner_type, default_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"optional inner type `{opt_type.inner_type}` does not match default type `{default_type}`",
                expr.line, expr.column
            )
        # design 131: `a ?? b` always yields an owned value, so BOTH arms are
        # transfers. The left arm extracts a payload out of `a` and takes the
        # place rule; the right arm is an ordinary transfer that had never been
        # checkpointed at all — so `let s = opt ?? other` used to alias `other`
        # and double-free it.
        self._check_payload_read(expr.expr, opt_type.inner_type, expr,
                                 "the result of `??`", expr.line, expr.column)
        self._check_value_transfer(expr.default, opt_type.inner_type,
                                   "the default operand of `??`",
                                   expr.default.line, expr.default.column)
        return default_type

    def _check_optional_chain(self, expr: OptionalChain) -> Optional[SawType]:
        """Check optional chaining: expr?.member - returns U?."""
        opt_type = self._check_expression(expr.expr)
        if opt_type is None:
            return None
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = opt_type.inner_type
        if inner_type is None:
            return None
        if inner_type.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{inner_type}`",
                expr.line, expr.column
            )
            return None
        struct_info = self.get_struct_info(inner_type.struct_name)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{inner_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        field_type = struct_info.fields[expr.member]
        return SawType(TypeKind.OPTIONAL, inner_type=field_type)

    # ------------------------------------------------------------------ #
    # Design 111 — full optional chaining. A `?.` hop is a BindOptional node
    # (unwrap-or-short-circuit); the maximal postfix run is an OptionalEvalExpr
    # (flatten to `U?`); `x?.y = v` is an OptionalChainAssign (`Void?`).
    # ------------------------------------------------------------------ #
    def _check_bind_optional(self, expr: BindOptional) -> Optional[SawType]:
        """A `?.` unwrap point: the receiver must be `Optional<U>`; the hop yields
        the payload `U` (the object the following segment projects/calls). `None`
        short-circuits the enclosing chain at codegen — here it is a pure type
        projection."""
        opt_type = self._check_expression(expr.expr)
        if opt_type is None:
            return None
        if opt_type.kind != TypeKind.OPTIONAL:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = opt_type.inner_type
        if inner_type is None:
            return None
        return self._resolve_type(inner_type)

    def _check_optional_eval(self, expr: OptionalEvalExpr) -> Optional[SawType]:
        """The whole optional chain. Type the spine, then flatten to `U?` — an
        already-optional final segment stays `U?`, never `U??`. A final FIELD
        projection copies its value, so it must be freely copyable; a final METHOD
        result is a fresh owned value and is unrestricted."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None
        if isinstance(expr.expr, MemberAccess):
            self._check_chain_final_field_copyable(expr.expr, inner_type)
        if inner_type.kind == TypeKind.OPTIONAL:
            return inner_type
        return SawType(TypeKind.OPTIONAL, inner_type=inner_type)

    def _check_chain_final_field_copyable(self, member: MemberAccess,
                                          field_type: SawType) -> None:
        """A final `?...field` projection reads the field out BY VALUE (there is no
        `.copy()`/`move` spelling inside a chain), so the field must be freely
        copyable — trivially copyable or ImplicitCopy. A move-only field (NoCopy,
        an owning Deinit type, or ExplicitCopy) is rejected (matching
        `Vector.get`'s copyable-element rule)."""
        if self._chain_field_freely_copyable(field_type):
            return
        detail = "ExplicitCopy" if self._is_explicit_copy_type(field_type) \
            else "move-only (NoCopy / owns a resource)"
        self._error(
            ErrorKind.CANNOT_COPY,
            f"cannot project field `{member.member}` of type `{field_type}` "
            f"through an optional chain: it is {detail}, and a chain projection "
            f"copies the value by value",
            member.line, member.column,
            hint="bind the optional first (`if let x = opt`) and move/`.copy()` "
                 "the field out, or end the chain in a method that returns a value")

    def _chain_field_freely_copyable(self, t: SawType) -> bool:
        """Whether a final-projection field type can be read out by value with no
        `move`/`.copy()` — trivially copyable or ImplicitCopy at the leaves,
        recursing through Optional / tuple / array wrappers (so an `Optional<Point>`
        or `String?` final field is fine, an owning/NoCopy/ExplicitCopy one is
        not)."""
        if t is None:
            return True
        t = self._resolve_type_alias(t)
        if t.kind == TypeKind.OPTIONAL:
            return self._chain_field_freely_copyable(t.inner_type)
        if t.kind == TypeKind.TUPLE:
            return all(self._chain_field_freely_copyable(e)
                       for e in (t.element_types or []))
        if t.kind == TypeKind.ARRAY:
            return self._chain_field_freely_copyable(t.array_element_type)
        if self._is_no_copy_type(t) or self._is_explicit_copy_type(t):
            return False
        if self._is_implicit_copy_type(t):
            return True
        return self._is_trivially_copyable(t)

    def _check_optional_chain_assign(self, expr: OptionalChainAssign) -> Optional[SawType]:
        """`x?.y = v` (design 111). Writes the RHS through the chain into the
        payload FIELD in place iff every optional hop is non-None; the RHS is
        skipped entirely on short-circuit (codegen). Types to `Void?` — `None` =
        skipped, `Some(unit)` = written."""
        target = expr.target
        if not isinstance(target, OptionalEvalExpr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "the left-hand side of this assignment is not an optional chain",
                expr.line, expr.column)
            return None
        spine = target.expr
        if not isinstance(spine, MemberAccess):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "an optional-chain assignment must target a field of the payload "
                "(the final segment must be `.field`, not a method call)",
                expr.line, expr.column)
            return None
        # Type the target field (also type-checks + stamps the whole chain, and
        # verifies the field exists and is visible for writing).
        field_type = self._check_expression(spine)
        if field_type is None:
            return None
        # Mutability: the chain head must be a mutable place (a `var` or a
        # `&var`-reachable path). Exclusivity: the written root must not overlap a
        # borrow in the RHS.
        root_path = self._build_access_path(spine)
        self._check_chain_assign_head_mutable(spine, root_path, expr)
        self._check_chain_assign_exclusivity(root_path, expr.value, expr)
        # RHS follows ordinary assignment transfer rules against the field type,
        # including optional-None propagation onto a bare `None` RHS.
        value_type = self._check_expression(expr.value)
        field_resolved = self._resolve_type_alias(field_type)
        if (value_type and value_type.is_none_literal()
                and field_resolved.is_optional()):
            self._propagate_optional_type(expr.value, field_resolved)
            value_type = field_resolved
        if value_type and not self._types_compatible(value_type, field_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to field of type `{field_type}`",
                expr.line, expr.column)
        self._check_value_transfer(expr.value, field_type,
                                   "optional-chain assignment",
                                   expr.line, expr.column)
        return SawType(TypeKind.OPTIONAL, inner_type=SawType(TypeKind.VOID))

    def _chain_assign_root(self, spine):
        """Walk a chain-assignment target to its ROOT node, transparent through
        MemberAccess/BindOptional/OptionalEvalExpr/tuple/index projections."""
        node = spine
        while True:
            if isinstance(node, MemberAccess):
                node = node.object
            elif isinstance(node, (BindOptional, OptionalEvalExpr)):
                node = node.expr
            elif isinstance(node, TupleIndex):
                node = node.tuple_expr
            elif isinstance(node, ArrayIndex):
                node = node.array_expr
            else:
                return node

    def _check_chain_assign_head_mutable(self, spine, root_path, expr) -> None:
        """The head of a chain assignment must be an assignable, mutable place."""
        root = self._chain_assign_root(spine)
        if isinstance(root, SelfExpr):
            return  # governed by `&var self`, like an ordinary field write
        if not isinstance(root, Identifier):
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                "the head of an optional-chain assignment must be a mutable "
                "variable or a `&var`-reachable path",
                expr.line, expr.column)
            return
        root_static = (self.namespace.get_static(root.name,
                                                 self._accessor_vis_module())
                       if self.current_scope.lookup(root.name) is None else None)
        if root_static is not None and not getattr(root_static, 'is_var', False):
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign through optional chain rooted at the immutable "
                f"static `{root.name}`",
                expr.line, expr.column)
            return
        info = self.current_scope.lookup(root.name)
        if info is None:
            return
        if info.mutable:
            return
        # A `&var` reference param is a mutable path; a `&` or plain `let` is not.
        if (info.type is not None and info.type.kind == TypeKind.REFERENCE
                and info.type.reference_mutable):
            return
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot assign through optional chain: `{root.name}` is not mutable",
            expr.line, expr.column,
            hint="consider using `var` instead of `let` to make it mutable")

    def _check_chain_assign_exclusivity(self, root_path, value, expr) -> None:
        """Law of Exclusivity on the written root path: the chain assignment is a
        write of the root, so the RHS may not also borrow (`&`/`&var`) or `move`
        an overlapping path."""
        if root_path is None:
            return
        import dataclasses
        stack = [value]
        # `id()` is correct here and is NOT the identity design 126 R2 removed:
        # this is a within-one-traversal cycle guard over physical objects, it
        # never outlives the call, and it must treat two equal-but-distinct nodes
        # as distinct.
        seen = set()
        while stack:
            cur = stack.pop()
            if cur is None or id(cur) in seen:
                continue
            seen.add(id(cur))
            if isinstance(cur, ClosureExpr):
                continue  # a closure's captures are its own access domain
            other = None
            if isinstance(cur, ReferenceExpr):
                other = self._build_access_path(cur.expr)
            elif isinstance(cur, MoveExpr):
                other = (cur.variable, ())
            if other is not None and self._paths_overlap(root_path, other):
                self._error(
                    ErrorKind.EXCLUSIVITY_VIOLATION,
                    f"exclusive access violation: `{root_path[0]}` is written by "
                    f"this optional-chain assignment while also being accessed in "
                    f"the right-hand side",
                    expr.line, expr.column)
                return
            if dataclasses.is_dataclass(cur) and not isinstance(cur, type):
                for f in dataclasses.fields(cur):
                    v = getattr(cur, f.name, None)
                    if dataclasses.is_dataclass(v) and not isinstance(v, type):
                        stack.append(v)
                    elif isinstance(v, (list, tuple)):
                        for it in v:
                            if isinstance(it, Argument):
                                stack.append(it.value)
                            elif dataclasses.is_dataclass(it) and not isinstance(it, type):
                                stack.append(it)

    def _make_specialization_key(self, type_args: List[SawType]) -> tuple:
        """Convert type arguments to a specialization key tuple."""
        if not type_args:
            return ()
        key_parts = []
        for t in type_args:
            if t.kind == TypeKind.STRING:
                key_parts.append("String")
            elif t.kind == TypeKind.INT:
                key_parts.append("Int")
            elif t.kind == TypeKind.UINT:
                key_parts.append("UInt")
            elif t.kind == TypeKind.FLOAT:
                key_parts.append("Float")
            elif t.kind == TypeKind.BOOL:
                key_parts.append("Bool")
            elif t.kind == TypeKind.INT8:
                key_parts.append("Int8")
            elif t.kind == TypeKind.INT16:
                key_parts.append("Int16")
            elif t.kind == TypeKind.INT32:
                key_parts.append("Int32")
            elif t.kind == TypeKind.INT64:
                key_parts.append("Int64")
            elif t.kind == TypeKind.UINT8:
                key_parts.append("UInt8")
            elif t.kind == TypeKind.UINT16:
                key_parts.append("UInt16")
            elif t.kind == TypeKind.UINT32:
                key_parts.append("UInt32")
            elif t.kind == TypeKind.UINT64:
                key_parts.append("UInt64")
            elif t.kind == TypeKind.STRUCT and t.struct_name:
                key_parts.append(t.struct_name)
            else:
                # Unknown type, can't match specialization
                return ()
        return tuple(key_parts)

    def _name_to_type(self, name: str) -> SawType:
        """Convert a type name string to a SawType."""
        type_mapping = {
            'Int': SawType(TypeKind.INT),
            'UInt': SawType(TypeKind.UINT),
            'Float': SawType(TypeKind.FLOAT),
            'Bool': SawType(TypeKind.BOOL),
            'String': SawType(TypeKind.STRING),
            'Int8': SawType(TypeKind.INT8),
            'Int16': SawType(TypeKind.INT16),
            'Int32': SawType(TypeKind.INT32),
            'Int64': SawType(TypeKind.INT64),
            'UInt8': SawType(TypeKind.UINT8),
            'UInt16': SawType(TypeKind.UINT16),
            'UInt32': SawType(TypeKind.UINT32),
            'UInt64': SawType(TypeKind.UINT64),
        }
        if name in type_mapping:
            return type_mapping[name]
        # Check if it's a user-defined struct
        struct_info = self.namespace.lookup_struct(name)
        if struct_info:
            return SawType(TypeKind.STRUCT,
                           struct_name=self._sym_identity(struct_info, name),
                           symbol=struct_info)
        # Check if it's an enum
        enum_info = self.namespace.lookup_enum(name)
        if enum_info:
            return SawType(TypeKind.ENUM,
                           enum_name=self._sym_identity(enum_info, name),
                           symbol=enum_info)
        # Fallback to STRUCT type
        return SawType(TypeKind.STRUCT, struct_name=name)

    def _lookup_method(self, struct_info, method_name: str, type_args: List[SawType] = None):
        """Look up a method, checking specialized extensions first.

        Extension scoping (design 142): a method whose defining module is out of
        scope here does not exist here. What a file can see is its own
        extensions, its direct imports', and the receiver type's own — never a
        transitive dependency's."""
        # First, check if there's a specialized extension matching the type args
        if type_args and struct_info.specialized_methods:
            spec_key = self._make_specialization_key(type_args)
            if spec_key in struct_info.specialized_methods:
                specialized = struct_info.specialized_methods[spec_key]
                sm = specialized.get(method_name)
                if sm is not None and self._ext_scope_allows(sm, struct_info):
                    return sm

        # Fall back to generic methods
        m = struct_info.methods.get(method_name)
        if m is not None:
            if self._ext_scope_allows(m, struct_info):
                return m
            # `methods` keeps the FIRST-registered overload as the
            # representative, and registration order follows the topological
            # module order — so an out-of-scope module's extension can occupy the
            # slot while this file's own is right behind it in the overload list.
            for cand in struct_info.method_overloads.get(method_name, []):
                if self._ext_scope_allows(cand, struct_info):
                    return cand

        return None

    def _scoped_method_overloads(self, struct_name: str, method_name: str,
                                 struct_info) -> List:
        """The overloads of `method_name` this file may see (design 142)."""
        return [s for s in self.namespace.lookup_method_overloads(
                    struct_name, method_name)
                if self._ext_scope_allows(s, struct_info)]

    def _out_of_scope_method_modules(self, struct_info, method_name: str,
                                     type_args: List[SawType] = None) -> List[str]:
        """The modules that define `method_name` on this type but are not in
        scope here (design 142) — what the "no method" diagnostic names so the
        reader learns which import to add rather than concluding the method does
        not exist."""
        candidates = list(struct_info.method_overloads.get(method_name, []))
        m = struct_info.methods.get(method_name)
        if m is not None and m not in candidates:
            candidates.append(m)
        if type_args and struct_info.specialized_methods:
            spec_key = self._make_specialization_key(type_args)
            spec = struct_info.specialized_methods.get(spec_key) or {}
            if method_name in spec:
                candidates.append(spec[method_name])
        labels = []
        for sym in candidates:
            if self._ext_scope_allows(sym, struct_info):
                continue
            label = self._module_label(getattr(sym, 'def_module', ()) or ())
            if label not in labels:
                labels.append(label)
        return sorted(labels)

    def _first_cross_module_method_clash(self, overloads):
        """Two in-scope extension methods from DIFFERENT modules that no
        tie-break rule could separate (design 142).

        Declaring both is legal — neither module need know the other exists, and
        under the old global registry the loser was simply shadowed. It is the
        call site that cannot choose, so that is where the error belongs, naming
        both defining modules."""
        shaped = []
        for sym in overloads:
            off = 0 if sym.is_init else 1
            shaped.append((sym, self._overload_shape_keys(
                sym.param_types[off:], sym.type_params,
                (sym.default_values[off:] if sym.default_values else []),
                sym.param_names[off:])))
        for i in range(len(shaped)):
            for j in range(i + 1, len(shaped)):
                a, keys_a = shaped[i]
                b, keys_b = shaped[j]
                if not (keys_a & keys_b):
                    continue
                if (getattr(a, 'def_module', ()) or ()) != (getattr(b, 'def_module', ()) or ()):
                    return (a, b)
        return None

    # Generic bounds that grant `.copy()` in an abstract generic body.
    _COPY_BOUND_NAMES = frozenset({"Copy", "ImplicitCopy", "ExplicitCopy"})

    def _bound_satisfied(self, concrete: SawType, bound: str) -> bool:
        """Whether `concrete` satisfies a single type-param `bound`.

        Concrete types defer to the shared namespace helper (so the typechecker
        and codegen agree). An *abstract* type parameter still in scope is
        satisfied only by its own declared bounds: inside a generic body we
        cannot resolve it structurally, so `Vector<K>.copy()` is legal exactly
        when `K` itself carries a `Copy`-family bound.
        """
        type_params = getattr(self, 'current_type_params', {})
        if concrete.kind == TypeKind.STRUCT and concrete.struct_name in type_params:
            param_bounds = type_params.get(concrete.struct_name) or []
            if bound in param_bounds:
                return True
            if bound == "Copy":
                return any(b in self._COPY_BOUND_NAMES for b in param_bounds)
            return False
        return self.namespace.type_satisfies_bound(concrete, bound)

    def _unmet_extension_bound(self, method_info, type_subst):
        """If a bounded-extension method is unavailable for this instantiation,
        return the first unmet (param_name, bound, concrete_type); else None.
        """
        bounds = getattr(method_info, 'extension_bounds', None)
        if not bounds:
            return None
        for param_name, param_bounds in bounds.items():
            concrete = type_subst.get(param_name)
            if concrete is None:
                continue
            for bound in param_bounds:
                if not self._bound_satisfied(concrete, bound):
                    return (param_name, bound, concrete)
        return None

    def _check_copy_call(self, expr: MethodCall, obj_type: SawType):
        """Handle a `.copy()` receiver. Returns (handled, result_type).

        handled=False means the receiver has a real copy() method
        (ImplicitCopy/ExplicitCopy) and normal method dispatch should proceed.
        handled=True means this call was fully resolved here (trivial auto-Copy,
        a `T: Copy`-family bound, or a diagnostic on a non-Copy receiver).
        """
        type_params = getattr(self, 'current_type_params', {})

        # Receiver is an opaque generic type parameter: allow .copy() only under
        # a Copy-family bound; the result is the type parameter itself.
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            bounds = type_params.get(obj_type.struct_name) or []
            if any(b in self._COPY_BOUND_NAMES for b in bounds):
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"cannot call `.copy()` on value of unbounded type parameter `{obj_type.struct_name}`",
                expr.line, expr.column,
                hint=f"add a `Copy` bound: `<{obj_type.struct_name}: Copy>`"
            )
            return True, None

        # Concrete type carrying a real copy() method (declared via a copy trait
        # or an ordinary user method): fall through to normal method dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, "copy", obj_type.type_args) is not None:
                return False, None
        elif obj_type.kind == TypeKind.STRING:
            struct_info = self.get_struct_info("String")
            if struct_info and self._lookup_method(struct_info, "copy") is not None:
                return False, None

        # Trivially copyable (POD / primitive): .copy() is a bitwise copy.
        if self._is_trivially_copyable(obj_type):
            expr.resolved_type = obj_type
            return True, obj_type

        # A fixed array `[T; N]` is copyable iff its element type is (design 33).
        # `.copy()` duplicates it per element in index order; the result has the
        # same array type. (`[trivial; N]` was already handled above.)
        if obj_type.kind == TypeKind.ARRAY:
            if self.namespace.type_satisfies_copy_bound(obj_type):
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; its element type is not copyable",
                expr.line, expr.column,
                hint="use a copyable element type, or `move` to transfer the array"
            )
            return True, None

        # An enum that DECLARED a copying policy (design 139) has a derived
        # payload-deep `copy`, emitted inline by codegen — enums carry no method
        # symbols, so there is nothing for the dispatch above to have found.
        if obj_type.kind == TypeKind.ENUM and obj_type.enum_name:
            if self.namespace.declared_copy_tier(obj_type.enum_name) in ('implicit', 'explicit'):
                expr.resolved_type = obj_type
                return True, obj_type

        # An `Optional<T>` is copyable exactly when its payload is (design 139):
        # the wrapper's tier IS the payload's, so `.copy()` exists precisely
        # where the tier provides one. `None` copies to `None`, `Some` to `Some`
        # of the payload's own copy. This used to be rejected outright, which
        # left `move` as the only way to transfer a `Vector<Int>?` — a wrapper
        # that was somehow less capable than the thing it wrapped.
        if obj_type.kind == TypeKind.OPTIONAL:
            if self.namespace.copy_tier(obj_type) != 'nocopy':
                expr.resolved_type = obj_type
                return True, obj_type
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; its payload type is move-only",
                expr.line, expr.column,
                hint="use `move` to transfer the optional, or `.take()` to move "
                     "the payload out in place"
            )
            return True, None

        # A TUPLE is the third wrapper design 139 names, and it gets the rule the
        # other two already had: the tuple carries its strongest element's tier,
        # so `.copy()` exists precisely where that tier provides one. Each element
        # copies at ITS own tier (a `String` retains, a `Vector<Int>` deep-copies),
        # which is what `_emit_tuple_deep_copy` in codegen already does.
        #
        # Without this arm the tuple was the one wrapper the rule named that never
        # got the method, and the two diagnostics contradicted each other: a plain
        # `let u = t` on an ExplicitCopy tuple was refused with "use .copy() for an
        # explicit deep copy", and `t.copy()` was refused with "not Copy" — while
        # `copy_tier` reported that same tuple as 'explicit', exactly the tier the
        # second message said it required. An ExplicitCopy tuple was move-only in
        # practice (DF-151i).
        #
        # Gated the way the optional above is gated rather than on the array's
        # `type_satisfies_copy_bound`: only a move-only element withholds the
        # method, so a tuple mentioning a type PARAMETER stays callable inside a
        # generic body and settles at the instantiation, matching `T?.copy()`.
        if obj_type.kind == TypeKind.TUPLE:
            if self.namespace.copy_tier(obj_type) != 'nocopy':
                expr.resolved_type = obj_type
                return True, obj_type
            offender = next(
                ((i, e) for i, e in enumerate(obj_type.element_types or [])
                 if self.namespace.copy_tier(e) == 'nocopy'),
                None
            )
            where = (f"element {offender[0]} of type `{offender[1]}` is NoCopy"
                     if offender is not None else "an element type is NoCopy")
            self._error(
                ErrorKind.CANNOT_COPY,
                f"type `{obj_type}` is not Copy; {where}",
                expr.line, expr.column,
                hint="use `move` to transfer the tuple, which a destructuring "
                     "`let (a, b) = move t` can then take apart"
            )
            return True, None

        # Anything else is not Copy.
        self._error(
            ErrorKind.CANNOT_COPY,
            f"type `{obj_type}` is not Copy; `.copy()` requires a trivially-copyable, "
            f"ImplicitCopy, or ExplicitCopy type",
            expr.line, expr.column
        )
        return True, None

    def _resolve_arc_forward(self, expr: MethodCall, payload_type: Optional[SawType],
                             through: str = "Arc"):
        """Resolve a wrapper payload-method forward (design 21b E2 for Arc,
        design 42 item 1 for Box — `through` names the wrapper for diagnostics).

        Returns `(payload_method_info, payload_type_subst)` if `expr.method_name`
        is an immutable `&self` method on the payload struct `T`; the string
        `"rejected"` if it is a `&var self` method (reported here as an error);
        or `None` if there is no such method (the caller then falls through to
        the ordinary "no method on the wrapper" diagnostic).
        """
        if payload_type is None or payload_type.kind != TypeKind.STRUCT:
            return None
        p_info = self.get_struct_info(payload_type.struct_name, from_type=payload_type)
        if p_info is None:
            return None
        m = self._lookup_method(p_info, expr.method_name, payload_type.type_args)
        if m is None:
            return None
        if getattr(m, "self_mutable", False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `&var self` method `{expr.method_name}` through `{through}` "
                f"— aliased mutation of a shared value is not allowed",
                expr.line, expr.column,
                hint="wrap the payload in a `Mutex` and mutate it inside `lock`"
            )
            return "rejected"
        subst: Dict[str, SawType] = {}
        if p_info.type_params and payload_type.type_args:
            for tp, ta in zip(p_info.type_params, payload_type.type_args):
                subst[tp.name] = ta
        return (m, subst)

    def _check_hash_call(self, expr: MethodCall, obj_type: SawType):
        """Handle a `.hash(&h)` receiver (design 48). Returns (handled, result).

        handled=False means the receiver has a real `hash` method (String, or a
        struct with a synthesized/custom hash) and normal dispatch should
        proceed. handled=True means this call was resolved here: a Hashable
        primitive or auto-conforming (POD struct / payload-free enum) receiver,
        whose `hash` is emitted inline by codegen. A generic type parameter is
        left to the bound-aware resolver.
        """
        type_params = getattr(self, 'current_type_params', {})
        # Opaque generic `T`: leave to the bound-aware resolver (it finds `hash`
        # on a `Hashable` bound).
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return False, None
        # Concrete type carrying a real `hash` method: normal dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, "hash", obj_type.type_args) is not None:
                return False, None
        elif obj_type.kind == TypeKind.STRING:
            struct_info = self.get_struct_info("String")
            if struct_info and self._lookup_method(struct_info, "hash") is not None:
                return False, None
        # No real method: the receiver must be Hashable (primitive / POD struct /
        # payload-free enum). Otherwise fall through to the normal (error) path.
        if not self._bound_satisfied(obj_type, "Hashable"):
            return False, None
        # Validate the `&var Hasher` argument.
        arg_type = self._check_expression(expr.arguments[0].value)
        ok = (arg_type is not None and arg_type.kind == TypeKind.REFERENCE
              and arg_type.inner_type is not None
              and arg_type.inner_type.kind == TypeKind.STRUCT
              and arg_type.inner_type.struct_name == "Hasher")
        if not ok:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`hash` expects a `&var Hasher` argument, got `{arg_type}`",
                expr.line, expr.column,
                hint="pass a mutable reference to a Hasher: `x.hash(&h)`"
            )
        expr.resolved_type = SawType(TypeKind.VOID)
        return True, SawType(TypeKind.VOID)

    def _check_printable_call(self, expr: MethodCall, obj_type: SawType):
        """Handle `.to_string()` / `.format(into:)` (design 56). Returns
        (handled, result). handled=False means the receiver has a real method
        (a Printable user struct) or is a generic `T` — normal / bound resolution
        proceeds. handled=True means a builtin receiver was resolved inline."""
        mname = expr.method_name
        type_params = getattr(self, 'current_type_params', {})
        # Opaque generic `T`: leave to the bound-aware resolver.
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return False, None
        # Concrete struct/enum carrying a real method: normal dispatch.
        if obj_type.kind == TypeKind.STRUCT:
            struct_info = self.get_struct_info(obj_type.struct_name, from_type=obj_type)
            if struct_info and self._lookup_method(struct_info, mname, obj_type.type_args) is not None:
                return False, None
        # Builtin (primitive / String) receiver: must be Printable, resolved here.
        if obj_type.kind not in (TypeKind.STRUCT, TypeKind.ENUM, TypeKind.STRING) \
                or (obj_type.kind == TypeKind.STRING):
            pass  # primitives / String handled below
        if not self.namespace.is_printable(obj_type):
            return False, None
        if mname == "to_string":
            if len(expr.arguments) != 0:
                return False, None
            expr.resolved_type = SawType(TypeKind.STRING)
            return True, SawType(TypeKind.STRING)
        # format(into: &var StringBuilder)
        if len(expr.arguments) != 1:
            return False, None
        arg_type = self._check_expression(expr.arguments[0].value)
        ok = (arg_type is not None and arg_type.kind == TypeKind.REFERENCE
              and arg_type.inner_type is not None
              and arg_type.inner_type.kind == TypeKind.STRUCT
              and arg_type.inner_type.struct_name == "StringBuilder")
        if not ok:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`format` expects a `&var StringBuilder` argument, got `{arg_type}`",
                expr.line, expr.column,
                hint="pass a mutable reference to a StringBuilder: `x.format(into: &var b)`"
            )
        expr.resolved_type = SawType(TypeKind.VOID)
        return True, SawType(TypeKind.VOID)

    def _check_type_param_method_call(self, expr: MethodCall, obj_type: SawType,
                                      bounds) -> Optional[SawType]:
        """Resolve `x.method()` where `x` has opaque generic type `T` (design 24
        item 1).

        The method must be provided by one of `T`'s declared trait bounds. Found
        in a bound's trait: check the argument count against that signature,
        check the argument expressions (stamping their annotations), and yield
        the trait method's declared return type — which may be an associated
        type and therefore stays abstract. Provided by no bound: a compile error
        naming the method and the bounds (an unbounded `T` names an empty set).

        Deep argument-type compatibility is *deferred*: a trait method signature
        may mention associated types or the trait's own type parameters, which
        stay abstract in this body, so a concrete-vs-abstract comparison here
        would produce false positives. Argument *count* is decidable and checked.

        A trait method has no analyzable body, so it contributes no suspend edge
        — a conservative non-suspending leaf, matching how opaque/imported
        callees are treated (design 22 §5).
        """
        tp_name = obj_type.struct_name
        for bound in bounds:
            trait = self.get_trait_info(bound)
            if trait is None:
                # A `Copy`-family / `Send` / `Sync` marker bound with no user
                # methods; it grants no callable method here (`.copy()` under a
                # Copy bound is handled earlier, in `_check_copy_call`).
                continue
            method_sym = trait.methods.get(expr.method_name)
            if method_sym is None:
                continue
            # `param_names` excludes the `self` receiver (which `param_types`
            # carries as a placeholder at index 0), so it is the arity to match.
            expected = len(method_sym.param_names)
            if len(expr.arguments) != expected:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes {expected} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            for arg in expr.arguments:
                if isinstance(arg.value, ClosureExpr):
                    self._check_closure(arg.value, None, as_call_argument=True)
                else:
                    self._check_expression(arg.value)
            # design 70 (A5): a method call on a type-PARAMETER receiver makes the
            # enclosing body effect-polymorphic — its suspendability depends on the
            # concrete `T`. A trait method contributes no edge here (abstract body),
            # so instead we flag the body; a call to it with concrete type args then
            # re-infers effects on the instantiation.
            self._effect_mark_poly()
            if method_sym.return_type is None:
                return SawType(TypeKind.VOID)
            return self._resolve_type(method_sym.return_type)
        # Not provided by any of `T`'s bounds (or `T` is unbounded).
        bound_list = ", ".join(bounds) if bounds else ""
        if bounds:
            hint = (f"none of `{tp_name}`'s bounds ({bound_list}) declare a "
                    f"method `{expr.method_name}`")
        else:
            hint = (f"`{tp_name}` is unbounded; add a trait bound whose trait "
                    f"declares `{expr.method_name}` (e.g. `<{tp_name}: SomeTrait>`)")
        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"type parameter `{tp_name}` has no method `{expr.method_name}`; "
            f"its bounds are [{bound_list}]",
            expr.line, expr.column,
            hint=hint
        )
        return None

    def _check_field_call(self, expr: MethodCall, func_type: SawType) -> Optional[SawType]:
        """Check a call through a function-typed struct field: `obj.field(args)`
        (design 24 item 3).

        This is an indirect call. Suspendability follows the field's type: a
        non-`sync` function-typed field conservatively marks the caller
        suspending (`_effect_indirect_call`), exactly like a call through a
        function-typed local or parameter. The node is flagged for codegen so it
        lowers to a field load + closure invocation rather than method dispatch.
        """
        # design 22/24: indirect call — non-`sync` field type => caller suspends.
        self._effect_indirect_call(func_type, expr.line)
        expr.is_field_call = True  # consumed by codegen
        param_types = func_type.param_types or []
        return_type = func_type.func_return_type or SawType(TypeKind.VOID)
        # Design 66: a function-typed field is a STRUCTURAL closure type — no
        # parameter names to label against.
        if self._call_has_labels(expr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"labeled arguments are not allowed when calling through the "
                f"function-typed field `{expr.method_name}` (closure types are "
                f"structural)", expr.line, expr.column)
            return return_type
        if len(expr.arguments) != len(param_types):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"field `{expr.method_name}` is a function taking {len(param_types)} "
                f"argument(s), but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return return_type
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                arg_type = self._check_expression(arg.value)
            if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
        return return_type

    # ---- design 51: `any Trait` existential dispatch, construction, coercion ----

    def _existential_receiver_trait(self, obj_type):
        """If `obj_type` names an erased receiver, return its trait name, else
        None. Accepts `any T`, `&any T`, and `Box<any T, A>`."""
        if obj_type is None:
            return None
        if obj_type.kind == TypeKind.EXISTENTIAL:
            return obj_type.existential_trait
        if (obj_type.kind == TypeKind.REFERENCE and obj_type.inner_type is not None
                and obj_type.inner_type.kind == TypeKind.EXISTENTIAL):
            return obj_type.inner_type.existential_trait
        if (obj_type.kind == TypeKind.STRUCT and obj_type.struct_name == "Box"
                and obj_type.type_args
                and obj_type.type_args[0].kind == TypeKind.EXISTENTIAL):
            return obj_type.type_args[0].existential_trait
        return None

    def _check_existential_method_call(self, expr, obj_type, trait_name):
        """Type-check dynamic dispatch through an erased receiver: resolve the
        method against the trait signature, check arguments, and propagate the
        trait method's declared effect (a non-`sync` method suspends, like an
        indirect call; a `sync` method stays sync-callable through `any`)."""
        # Erased-box downcasting (design 72): `b.is<T>()` / `b.take<T>()` on an
        # owned `Box<any Trait>`, disambiguated by the explicit type argument.
        if (expr.method_name in ("is", "take")
                and getattr(expr, 'type_args', None)
                and obj_type.kind == TypeKind.STRUCT
                and obj_type.struct_name == "Box"):
            return self._check_erased_downcast(expr, obj_type, trait_name)

        trait = self.get_trait_info(trait_name)
        if trait is None:
            self._error(ErrorKind.UNKNOWN_TYPE,
                        f"unknown trait `{trait_name}`", expr.line, expr.column)
            return None
        tmethod = trait.methods.get(expr.method_name)
        if tmethod is None:
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"trait `{trait_name}` has no method `{expr.method_name}` to "
                f"dispatch through `any {trait_name}`",
                expr.line, expr.column)
            return None
        # Arg count (param_types[0] is the VOID self placeholder).
        expected = (tmethod.param_types or [])[1:]
        if len(expr.arguments) != len(expected):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{trait_name}.{expr.method_name}` takes {len(expected)} "
                f"argument(s), but {len(expr.arguments)} were given",
                expr.line, expr.column)
            return tmethod.return_type
        for i, arg in enumerate(expr.arguments):
            arg_type = self._check_expression(arg.value)
            if (arg_type is not None and expected[i] is not None
                    and not self._types_compatible(arg_type, expected[i])):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected[i]}` but got `{arg_type}`",
                    arg.value.line, arg.value.column)
            self._check_value_transfer(arg.value, expected[i], "call argument",
                                       arg.value.line, arg.value.column)
        # Effect propagation: the call carries the TRAIT signature's effect.
        if not getattr(tmethod, 'is_sync', False):
            self._effect_direct_source(
                f"a call through `any {trait_name}` dispatch", expr.line)
        expr.existential_dispatch = trait_name
        return tmethod.return_type

    def _check_erased_downcast(self, expr, box_type, trait_name):
        """Type-check erased-box downcasting (design 72 v1).

        `b.is<T>()` -> `Bool` (a borrow: the box stays live). `b.take<T>()` -> `T?`
        and CONSUMES the box (the receiver binding is marked moved; on a runtime
        id miss the box drops and the result is `None`; `is<T>()` first lets a
        caller branch without consuming). `T` is given explicitly (no inference)
        and must be a concrete type conforming to the erased trait. Catch-side
        match-on-concrete sugar is out of scope (future)."""
        op = expr.method_name
        result_ty = (SawType(TypeKind.BOOL) if op == "is" else None)
        type_args = expr.type_args or []
        if len(type_args) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{op}<T>()` requires exactly one explicit type argument",
                expr.line, expr.column)
            return result_ty
        if len(expr.arguments) != 0:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{op}<T>()` takes no value arguments",
                expr.line, expr.column)
        target = self._resolve_type(type_args[0])
        conc_name = None
        if target.kind == TypeKind.STRUCT:
            conc_name = target.struct_name
        elif target.kind == TypeKind.STRING:
            conc_name = "String"
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{target}` is not a concrete type conforming to `{trait_name}`, "
                f"so it cannot be a downcast target for `{op}<T>()`",
                expr.line, expr.column,
                hint="the type argument must be a concrete conforming type")
            return SawType(TypeKind.OPTIONAL, inner_type=target) if op == "take" else result_ty
        expr.erased_downcast = {
            'op': op,
            'target': target,
            'box_type': box_type,
            'trait': trait_name,
        }
        if op == "is":
            return SawType(TypeKind.BOOL)
        # `take` consumes the box — mark the receiver binding moved (like a move),
        # so a later use is a use-after-move error and scope teardown skips it.
        if isinstance(expr.object, Identifier):
            var_info = self.current_scope.lookup(expr.object.name)
            if var_info is not None:
                if self._binding_move_info(var_info) is not None:
                    _, move_line, _ = self._binding_move_info(var_info)
                    self._error(
                        ErrorKind.USE_AFTER_MOVE,
                        f"use of moved variable `{expr.object.name}`",
                        expr.line, expr.column,
                        hint=f"value was already moved at line {move_line}")
                else:
                    self._mark_binding_moved(var_info, expr.object.name,
                                             expr.line, expr.column)
        return SawType(TypeKind.OPTIONAL, inner_type=target)

    def _check_erased_box_make(self, expr, existential_type):
        """`Box<any Trait>.make(v)` built erased-directly (design 51): the concrete
        `v` must conform to the trait; the result is `Box<any Trait, A>`."""
        trait_name = existential_type.existential_trait
        # Object safety of the erased trait (this construction site is not a
        # declared signature, so it was not covered by the signature-level pass).
        self._check_object_safety(trait_name, expr.line, expr.column)

        if expr.method_name == "try_make":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`Box<any Trait>.try_make(...)` is not yet supported — use "
                "`Box<any Trait>.make(...)` (the fallible erased factory is deferred)",
                expr.line, expr.column)
            return None

        # Allocator: the second type arg, or Global by default.
        type_args = [self._resolve_type(t) for t in (expr.object.type_args or [])]
        type_args = self._append_default_type_args("Box", type_args)
        allocator = type_args[1] if len(type_args) > 1 else SawType(
            TypeKind.STRUCT, struct_name="GlobalAllocator")

        if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`Box<any Trait>.make(...)` takes exactly one positional value",
                expr.line, expr.column)
            return None

        concrete = self._check_expression(expr.arguments[0].value)
        box_result = SawType(TypeKind.STRUCT, struct_name="Box",
                             type_args=[existential_type, allocator])
        if concrete is None:
            return box_result
        conc_name = None
        if concrete.kind == TypeKind.STRUCT:
            conc_name = concrete.struct_name
        elif concrete.kind == TypeKind.STRING:
            conc_name = "String"
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{concrete}` does not conform to `{trait_name}`, so it cannot be "
                f"erased into `Box<any {trait_name}>`",
                expr.arguments[0].value.line, expr.arguments[0].value.column)
            return box_result
        # The value is MOVED into the box (consumed).
        self._check_value_transfer(expr.arguments[0].value, concrete,
                                   "call argument",
                                   expr.arguments[0].value.line,
                                   expr.arguments[0].value.column)
        expr.erased_box_make = {
            'trait': trait_name,
            'concrete': concrete,
            'allocator': allocator,
            'try_make': False,
        }
        return box_result

    def _check_taskgroup_spawn(self, expr, group_type):
        """`group.spawn(f(args))` (design 52b item 2). Validate the argument is a
        direct call to a free function, record `f` a spawn root (so the coro
        transform builds its frame + `Resumable` conformance + a `__spawn_<f>`
        helper), and yield `TaskHandle<T>` with `T` = f's return type. Absorbs the
        callee's suspension — spawning enqueues; it does not itself suspend — so
        the enclosing function does not become suspending merely by spawning."""
        if len(expr.arguments) != 1 or expr.arguments[0].name is not None:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                "`group.spawn(...)` takes exactly one positional argument: a call "
                "to the function to run as a task, e.g. `group.spawn(worker(n))`",
                expr.line, expr.column)
            return None
        inner = expr.arguments[0].value
        if not isinstance(inner, FunctionCall):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`group.spawn(...)` expects a direct call to a free function, "
                "e.g. `group.spawn(worker(n))`",
                expr.line, expr.column)
            return None
        # Before anything reads the callee: put the AUTHORED name back if an
        # earlier pass over this same AST already monomorphized it.
        self._restore_authored_call(inner)
        # Check the inner call inside an absorbing scope so its suspension does not
        # taint the spawning function; this also validates the argument types and
        # stamps `inner.resolved_type`.
        sentinel = self._effect_absorb_scope()
        inner_type = self._check_expression(inner)
        self._effect_unabsorb(sentinel)
        result_type = inner_type if inner_type is not None else SawType(TypeKind.VOID)
        # design 70 (A5): spawning a generic function monomorphizes the
        # instantiation to a concrete function (keyed by the mangled symbol) and
        # spawns THAT, so the coroutine transform's frame + `__spawn_<f>` synthesis
        # sees an ordinary non-generic function.
        # Design 105: a generic OVERLOAD resolved by inference carries its distinct
        # `$OL$` base in `resolved_symbol`; monomorphize from THAT template so the
        # right overload is instantiated (plain `inner.name` maps ambiguously).
        spawn_name = getattr(inner, 'resolved_symbol', None) or inner.name
        if getattr(inner, 'type_args', None):
            resolved_args = [self._resolve_type(a) for a in inner.type_args]
            if not all(self._is_concrete_type(a) for a in resolved_args):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`group.spawn(...)` of a generic function requires concrete "
                    f"type arguments", expr.line, expr.column)
                return None
            spawn_name = self._effect_queue_fn_mono(spawn_name, resolved_args)
            inner.name = spawn_name
            inner.type_args = None
        self._effect_record_spawn(spawn_name, result_type)
        # design 75 (A2): if the receiver group was built multi-threaded
        # (`TaskGroup(threads: N)`), record this spawn root so the coroutine
        # transform gates its frame on `Send` (it may cross to a worker thread).
        if isinstance(expr.object, Identifier):
            recv_info = self.current_scope.lookup(expr.object.name)
            if recv_info is not None and getattr(recv_info, 'is_mt_group', False):
                self._mt_spawn_roots.add(spawn_name)
        expr.spawn_root = spawn_name
        # design 102 item 1: a `Void` spawn body carries no result slot, so it
        # yields a `VoidTaskHandle` (no `result_ptr`) rather than `TaskHandle<Void>`
        # — join drives to completion and returns, with nothing to take.
        if result_type.kind == TypeKind.VOID:
            handle_type = SawType(TypeKind.STRUCT, struct_name="VoidTaskHandle")
        else:
            handle_type = SawType(TypeKind.STRUCT, struct_name="TaskHandle",
                                  type_args=[result_type])
        # Stamp the handle type so the transform's `__spawn_<f>` rewrite can carry
        # it onto the replacement call (needed when a suspending spawner makes the
        # `let h = group.spawn(...)` binding frame-resident and must type it).
        expr.resolved_type = handle_type
        return handle_type

    def _erasure_compatible(self, at, pt):
        """Whether `&concrete` (or an already-erased `&any T`) fits a `&any T`
        slot (design 51). Used by overload CANDIDATE SELECTION, which runs before
        `_try_existential_arg_coercion` gets to perform the erasure."""
        if (at is None or pt is None
                or pt.kind != TypeKind.REFERENCE or at.kind != TypeKind.REFERENCE
                or pt.inner_type is None or at.inner_type is None
                or pt.inner_type.kind != TypeKind.EXISTENTIAL):
            return False
        if pt.reference_mutable and not at.reference_mutable:
            return False
        trait_name = pt.inner_type.existential_trait
        inner = at.inner_type
        if inner.kind == TypeKind.EXISTENTIAL:
            return inner.existential_trait == trait_name
        conc_name = inner.struct_name if inner.kind == TypeKind.STRUCT else (
            "String" if inner.kind == TypeKind.STRING else None)
        return (conc_name is not None
                and self.namespace.type_conforms_to(conc_name, trait_name))

    def _try_existential_arg_coercion(self, arg, arg_type, expected_type):
        """Coerce `&concrete -> &any Trait` at a call boundary (design 51). Returns
        True if this argument slot is an existential-reference target (whether the
        coercion succeeded or a conformance error was reported), so the caller
        skips the generic type-mismatch path."""
        if (expected_type is None or expected_type.kind != TypeKind.REFERENCE
                or expected_type.inner_type is None
                or expected_type.inner_type.kind != TypeKind.EXISTENTIAL):
            return False
        trait_name = expected_type.inner_type.existential_trait
        if arg_type is None:
            return True
        if arg_type.kind != TypeKind.REFERENCE or arg_type.inner_type is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"expected `&any {trait_name}`; pass a reference to a conforming "
                f"value (e.g. `&value`)",
                arg.value.line, arg.value.column)
            return True
        # `&var any` needs a `&var` borrow; `&any` accepts either.
        if expected_type.reference_mutable and not arg_type.reference_mutable:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`&var any {trait_name}` requires a mutable borrow (`&var value`)",
                arg.value.line, arg.value.column)
            return True
        # Already erased: forwarding a received `&any T` / `&var any T` onward as a
        # re-borrow (design 106). There is nothing to erase — the fat pointer is
        # passed through — so accept it here rather than treating the existential
        # as a "concrete" type that fails the conformance lookup below.
        if arg_type.inner_type.kind == TypeKind.EXISTENTIAL:
            if arg_type.inner_type.existential_trait != trait_name:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"expected `&any {trait_name}` but got "
                    f"`&any {arg_type.inner_type.existential_trait}`",
                    arg.value.line, arg.value.column)
            return True
        conc = arg_type.inner_type
        conc_name = conc.struct_name if conc.kind == TypeKind.STRUCT else (
            "String" if conc.kind == TypeKind.STRING else None)
        if conc_name is None or not self.namespace.type_conforms_to(conc_name, trait_name):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{conc}` does not conform to `{trait_name}`, so `&{conc}` cannot "
                f"be erased to `&any {trait_name}`",
                arg.value.line, arg.value.column)
            return True
        arg.value.erase_to_trait = trait_name
        arg.value.erase_concrete = conc
        return True

    def _check_array_method(self, expr: MethodCall, arr_type: SawType) -> Optional[SawType]:
        """Builtin members on a fixed array `[T; N]` (design 72 L12/M1).

        `.len()` — the compile-time constant length N as an `Int` (no arguments).
        `.swap(i, j)` — the M1 escape hatch: a bounds-checked in-place swap of two
        elements (mirrors `Vector.swap`), so a dynamic-index exclusivity conflict
        can be sidestepped without copying elements. `swap` mutates, so the
        receiver must be a mutable binding. No other methods exist on array types
        (user extensions on array types are a parse-level rejection)."""
        if expr.method_name == "len":
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    "`len` takes no arguments",
                    expr.line, expr.column)
            expr.array_builtin = "len"
            result = SawType(TypeKind.INT)
            expr.resolved_type = result
            return result
        if expr.method_name == "swap":
            # `swap` mutates in place — reject an immutable-array receiver.
            recv = expr.object
            if isinstance(recv, Identifier):
                info = self.current_scope.lookup(recv.name)
                is_var_ref = (info is not None and info.type is not None
                              and info.type.kind == TypeKind.REFERENCE
                              and info.type.reference_mutable)
                if info is not None and not info.mutable and not is_var_ref:
                    self._error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot call `swap` on immutable array `{recv.name}`",
                        expr.line, expr.column,
                        hint="consider using `var` instead of `let` to make it mutable")
            if len(expr.arguments) != 2:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`swap` takes two index arguments, got {len(expr.arguments)}",
                    expr.line, expr.column)
                result = SawType(TypeKind.VOID)
                expr.resolved_type = result
                return result
            for arg in expr.arguments:
                at = self._check_expression(arg.value)
                if at is not None and at.kind != TypeKind.INT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`swap` index must be `Int`, got `{at}`",
                        expr.line, expr.column)
                # Reject out-of-range compile-time constant indices, mirroring
                # `a[const]`. Dynamic indices get a runtime bounds check in codegen.
                if (isinstance(arg.value, IntLiteral)
                        and arr_type.array_size is not None
                        and (arg.value.value < 0
                             or arg.value.value >= arr_type.array_size)):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`swap` index {arg.value.value} out of range for array "
                        f"with {arr_type.array_size} elements",
                        expr.line, expr.column)
            expr.array_builtin = "swap"
            result = SawType(TypeKind.VOID)
            expr.resolved_type = result
            return result
        self._error(
            ErrorKind.UNDEFINED_FUNCTION,
            f"fixed array `{arr_type}` has no method `{expr.method_name}`",
            expr.line, expr.column,
            hint="only `.len()` and `.swap(i, j)` are available on arrays; "
                 "user extensions on array types are not supported")
        return None

    def _check_enum_from_raw(self, expr, enum_info) -> Optional[SawType]:
        """Check `E.from(raw: <int>)` on a raw-backed enum (design 145 unit B2).

        The total direction is the `as` cast; this is the partial inverse, so it
        yields `E?`. Returning an optional rather than trapping is the point:
        the caller is usually decoding bytes it did not write, and an
        unrecognized tag is a fact about the input, not a bug in the program.
        It is a LOOKUP, not a constructor — unit B's no-inits-on-enums rule
        stands."""
        # Design 144: the identity, so a backed enum's `from(raw:)` reaches its
        # OWN tag table when two modules each declare one.
        enum_name = self._sym_identity(enum_info, expr.object.name)
        raw_type = enum_info.raw_type
        if len(expr.arguments) != 1:
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{enum_name}.from` takes exactly one argument, "
                f"got {len(expr.arguments)}",
                expr.line, expr.column,
                hint=f"call it as `{enum_name}.from(raw: <{raw_type}>)`"
            )
            return None
        arg = expr.arguments[0]
        label = getattr(arg, 'name', None)
        if label is not None and label != "raw":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{enum_name}.from` takes its argument labeled `raw`, "
                f"got `{label}`",
                expr.line, expr.column
            )
            return None
        arg_type = self._check_expression(arg.value)
        if arg_type is None:
            return None
        if not self._types_compatible(raw_type, arg_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{enum_name}.from` expects `{raw_type}` (the enum's backing "
                f"type), got `{arg_type}`",
                expr.line, expr.column
            )
            return None
        # Stamp for codegen: this lowers to a tag lookup, not a call.
        expr.enum_from_raw = enum_name
        return SawType(TypeKind.OPTIONAL,
                       inner_type=SawType(TypeKind.ENUM, enum_name=enum_name))

    def _check_method_call(self, expr: MethodCall) -> Optional[SawType]:
        """Check a method call, static method call, enum initialization, or module function call."""
        # design 51: erased-direct `Box<any Trait>.make(v)` — intercept before the
        # normal generic Box static-factory path (which would substitute the
        # unsized `any Trait` for `T` and reject the concrete argument).
        if (isinstance(expr.object, Identifier) and expr.object.name == "Box"
                and getattr(expr.object, 'type_args', None)
                and expr.object.type_args[0].kind == TypeKind.EXISTENTIAL
                and expr.method_name in ("make", "try_make")):
            return self._check_erased_box_make(expr, expr.object.type_args[0])
        # design 52b item 2: `group.spawn(f(args))` on a TaskGroup receiver. Peek
        # the receiver type (a bare identifier / member — the group local) and
        # route to the spawn handler, which records the spawn root and yields
        # `TaskHandle<T>`. Distinct from the 21b `spawn { closure }` FunctionCall.
        if expr.method_name == "spawn" and isinstance(
                expr.object, (Identifier, MemberAccess)):
            recv_t = self._check_expression(expr.object)
            if (recv_t is not None and recv_t.kind == TypeKind.STRUCT
                    and recv_t.struct_name == "TaskGroup"):
                return self._check_taskgroup_spawn(expr, recv_t)
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
            # Handle static method calls on module-qualified structs: module.Struct.method()
            if obj_type and obj_type.kind == TypeKind.STRUCT:
                struct_name = obj_type.struct_name
                struct_info = self.get_struct_info(struct_name, from_type=obj_type)
                if struct_info and expr.method_name in struct_info.methods:
                    method_info = struct_info.methods[expr.method_name]
                    if method_info.is_static:
                        return self._check_static_method_call(expr, struct_name, struct_info, method_info)
                    elif method_info.is_init:
                        # design 27 item 3: an `init` reached through the
                        # member-access form (`pkg.Struct.init(...)`) is not the
                        # supported call syntax — custom initializers are invoked
                        # as `pkg.Struct(...)` (which flows through
                        # `_check_module_struct_init`). In practice this branch is
                        # unreachable: `init` is a keyword so it never parses as a
                        # method name, and init symbols live in `init_methods`, not
                        # the `methods` dict. Emit a clean diagnostic rather than
                        # calling into a nonexistent handler if it is ever reached.
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot call initializer of `{struct_name}` this way",
                            expr.line, expr.column,
                            hint=f"construct it directly as `{struct_name}(...)`"
                        )
                        return SawType(TypeKind.STRUCT, struct_name=struct_name,
                                       symbol=struct_info)
            # Handle module-qualified enum variant construction: lib.Color.Custom(r: 1, g: 2, b: 3)
            if obj_type and obj_type.kind == TypeKind.ENUM:
                enum_info = self.get_enum_info(obj_type.enum_name, from_type=obj_type)
                if enum_info and expr.method_name in enum_info.variants:
                    enum_init = EnumInit(
                        enum_name=obj_type.enum_name,
                        variant_name=expr.method_name,
                        arguments=expr.arguments,
                        type_args=obj_type.type_args,
                        enum_symbol=enum_info,  # Pass symbol for module-qualified lookup
                        line=expr.line,
                        column=expr.column
                    )
                    # Attach to AST so codegen can use it
                    expr.resolved_enum_init = enum_init
                    return self._check_enum_init(enum_init)
            if obj_type and obj_type.kind == TypeKind.MODULE:
                inner_module_sym = getattr(expr.object, 'resolved_module_symbol', None)
                if inner_module_sym and inner_module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = inner_module_sym.namespace.resolve(
                        expr.method_name,
                        check_visibility=True,
                        accessor_module=self.namespace.module_path
                    )
                    if symbol is None:
                        self._error(
                            ErrorKind.UNDEFINED_FUNCTION,
                            f"module `{obj_type.module_name}` has no function `{expr.method_name}`",
                            expr.line, expr.column
                        )
                        return None
                    if symbol.kind == SymbolKind.FUNCTION:
                        # Overloading (design 55): resolve against the module's
                        # overload set when it has 2+ members.
                        mo = inner_module_sym.namespace.lookup_function_overloads(
                            expr.method_name)
                        if len(mo) > 1:
                            return self._check_overloaded_module_function_call(expr, mo)
                        # Use the symbol directly - it's already a FunctionSymbol
                        return self._check_module_function_call(expr, symbol)
                    elif symbol.kind == SymbolKind.STRUCT:
                        # For module-qualified struct init, check using the symbol directly
                        return self._check_module_struct_init(expr, symbol)
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"`{expr.method_name}` is not callable",
                            expr.line, expr.column
                        )
                        return None
        if isinstance(expr.object, Identifier):
            # Design 150 pin 4: a value binding of this name wins; the qualifier
            # is consulted last.
            module_sym = self._module_qualifier(expr.object.name)
            if module_sym and module_sym.namespace:
                from namespace import SymbolKind
                symbol = module_sym.namespace.resolve(
                    expr.method_name,
                    check_visibility=True,
                    accessor_module=self.namespace.module_path
                )
                if symbol is None:
                    self._error(
                        ErrorKind.UNDEFINED_FUNCTION,
                        f"module `{expr.object.name}` has no function `{expr.method_name}`",
                        expr.line, expr.column
                    )
                    return None
                if symbol.kind == SymbolKind.FUNCTION:
                    # Overloading (design 55): resolve against the module's
                    # overload set when it has 2+ members.
                    mo = module_sym.namespace.lookup_function_overloads(
                        expr.method_name)
                    if len(mo) > 1:
                        return self._check_overloaded_module_function_call(expr, mo)
                    # Use the symbol directly - it's already a FunctionSymbol
                    return self._check_module_function_call(expr, symbol)
                elif symbol.kind == SymbolKind.STRUCT:
                    # For module-qualified struct init, check using the symbol directly
                    return self._check_module_struct_init(expr, symbol)
                elif symbol.kind == SymbolKind.ENUM:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"use `{expr.object.name}.{expr.method_name}.Variant(...)` to create enum values",
                        expr.line, expr.column
                    )
                    return None
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.method_name}` is not callable",
                        expr.line, expr.column
                    )
                    return None
        if isinstance(expr.object, Identifier):
            # Prelude discipline (design 82 Part B): a bare `TcpStream.connect(...)`
            # on a non-prelude std type not imported here errors with an import
            # hint, before it resolves to the hidden static method.
            if (expr.object.name in getattr(self, '_std_symbol_file', {})
                    and self._std_name_gated(
                        expr.object.name, expr.line, expr.column)):
                return None
            struct_info = self.get_struct_info(expr.object.name)
            if struct_info:
                struct_name = expr.object.name
                if expr.method_name in struct_info.methods:
                    method_info = struct_info.methods[expr.method_name]
                    if method_info.is_static:
                        # Overloading (design 55): resolve among static overloads.
                        so = self.namespace.lookup_method_overloads(
                            struct_name, expr.method_name)
                        if len(so) > 1:
                            return self._check_overloaded_static_method_call(
                                expr, struct_name, struct_info, so)
                        return self._check_static_method_call(expr, struct_name, struct_info, method_info)
        if isinstance(expr.object, Identifier) and self.get_enum_info(expr.object.name):
            # Design 145: a STATIC method on the enum gets first refusal —
            # otherwise `SysError.from(raw: b)` is read as a variant named
            # `from` and reported as "enum has no variant". A case always wins a
            # name clash: cases are the enum's own vocabulary, and a static
            # method is the newcomer.
            enum_info = self.get_enum_info(expr.object.name)
            if (expr.method_name not in enum_info.variants
                    and expr.method_name in enum_info.methods):
                static_info = enum_info.methods[expr.method_name]
                if static_info.is_static:
                    enum_name = expr.object.name
                    so = self.namespace.lookup_method_overloads(
                        enum_name, expr.method_name)
                    if len(so) > 1:
                        return self._check_overloaded_static_method_call(
                            expr, enum_name, enum_info, so)
                    return self._check_static_method_call(
                        expr, enum_name, enum_info, static_info)
            # Design 145 unit B2: the synthesized inverse of the `as` cast.
            # `E.from(raw: u)` is a LOOKUP, not a constructor — an unrecognized
            # value is DATA (a bad wire byte), never a trap, so it returns `E?`
            # and `None` means "no case has that value". Ranks below a case name
            # and below a user-written static of the same name.
            if (expr.method_name == "from"
                    and expr.method_name not in enum_info.variants
                    and expr.method_name not in enum_info.methods
                    and getattr(enum_info, 'raw_type', None) is not None):
                return self._check_enum_from_raw(expr, enum_info)
            expr.resolved_type_identity = self._sym_identity(
                enum_info, expr.object.name)
            enum_init = EnumInit(
                enum_name=expr.resolved_type_identity,
                variant_name=expr.method_name,
                arguments=expr.arguments,
                type_args=expr.object.type_args,
                line=expr.line,
                column=expr.column
            )
            return self._check_enum_init(enum_init)
        # Design 170: `UInt8.from(x)` / `UInt8.from(truncating: x)`. An integer
        # type name is not a value, so this must be answered before the receiver
        # is checked as an expression — otherwise it reports `undefined variable
        # UInt8` and the real call never resolves.
        if (isinstance(expr.object, Identifier)
                and expr.method_name == "from"
                and expr.object.name in self._INT_LIMIT_TYPE_KINDS):
            return self._check_int_from(expr)
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None

        # design 51: dynamic dispatch through an erased receiver (`any T`,
        # `&any T`, or `Box<any T>`) — resolve against the trait signature.
        recv_trait = self._existential_receiver_trait(obj_type)
        if recv_trait is not None:
            return self._check_existential_method_call(expr, obj_type, recv_trait)

        # design 46: accessors on `UnsafeMemory<T, Use>` — `read()`/`write(v)`
        # (Device: volatile, scalar-only, RO/WO gated) and the Normal region
        # accessors `ptr()`/`len()`/`end()`.
        if self._is_unsafe_memory(obj_type):
            return self._check_um_method(expr, obj_type)

        # `.copy()` — the umbrella Copy operation. Handles auto-Copy of trivial
        # types and `.copy()` through a `T: Copy`-family bound. Types that carry
        # a real copy() method (ImplicitCopy/ExplicitCopy) fall through to normal
        # method dispatch.
        if expr.method_name == "copy" and len(expr.arguments) == 0:
            handled, result = self._check_copy_call(expr, obj_type)
            if handled:
                return result

        # `.hash(&h)` — the Hashable streaming operation (design 48). A receiver
        # with a real `hash` method (String, or a struct with a synthesized /
        # custom hash) dispatches normally; a primitive or an auto-conforming
        # (POD struct / payload-free enum) receiver is resolved here.
        if expr.method_name == "hash" and len(expr.arguments) == 1:
            handled, result = self._check_hash_call(expr, obj_type)
            if handled:
                return result

        # `.to_string()` / `.format(into:)` — the Printable operations (design 56).
        # A user struct conforming to Printable carries real methods (its
        # hand-written `format` and its synthesized `to_string`) and dispatches
        # normally; a builtin (primitive / String) receiver is resolved here and
        # emitted inline by codegen. A generic `T` is left to the bound resolver.
        if (expr.method_name in ("to_string", "format")):
            handled, result = self._check_printable_call(expr, obj_type)
            if handled:
                return result

        # Bound-aware method resolution on an opaque generic type parameter
        # (design 24 item 1). Inside a generic body, `x.method()` where `x: T`
        # resolves against the methods declared by T's trait bounds; a method
        # found in a bound's trait is checked against that signature (associated
        # types stay abstract), and a method found in no bound is an error naming
        # the method and the bounds. `.copy()` under a `Copy`-family bound was
        # already resolved above.
        type_params = getattr(self, 'current_type_params', {})
        if obj_type.kind == TypeKind.STRUCT and obj_type.struct_name in type_params:
            return self._check_type_param_method_call(
                expr, obj_type, type_params[obj_type.struct_name])

        # Builtin members on a fixed array `[T; N]` (design 72 L12/M1). User
        # extensions on array types are unsupported (a parse-level rejection);
        # the whole surface is `.len()` and `.swap(i, j)`. `.copy()` was already
        # routed above through the Copy machinery.
        if obj_type.kind == TypeKind.ARRAY:
            return self._check_array_method(expr, obj_type)

        # `o.take()` — the consuming payload read (design 131). Swaps `None` into
        # the place and hands the payload back owned, so it works on any
        # `&var`-reachable place INCLUDING a FIELD, which is the move-out that
        # no-partial-moves otherwise forbids.
        if (obj_type.kind == TypeKind.OPTIONAL
                and expr.method_name == "take"
                and not getattr(expr, 'type_args', None)):
            return self._check_optional_take(expr, obj_type)

        _prim_ext_name = {
            TypeKind.STRING: "String",
            TypeKind.INT: "Int",
            TypeKind.FLOAT: "Float",
        }.get(obj_type.kind)
        if _prim_ext_name is not None:
            # Method on a primitive pseudo-struct (design 57: String/Int/Float).
            struct_name = _prim_ext_name
            struct_info = self.get_struct_info(struct_name)
        elif obj_type.kind == TypeKind.STRUCT:
            struct_name = obj_type.struct_name
            struct_info = self.get_struct_info(struct_name, from_type=obj_type)
            if struct_info is None and self.get_enum_info(struct_name) is not None:
                # A bare type name parses STRUCT-kinded; a reference parameter
                # (`l: &Level`) can reach here still carrying that kind for what
                # is really an enum. Codegen re-tags the same way (design 61).
                # Without this the receiver resolves to nothing and the call
                # types as None with no diagnostic at all.
                struct_info = self.get_enum_info(struct_name)
        elif obj_type.kind == TypeKind.ENUM:
            # Design 145: enums carry methods on the same terms as structs, and
            # `EnumSymbol` carries the same method tables, so everything below
            # (lookup, the design-80 gate, the design-55 overload resolver, the
            # design-142 ambiguity check) works against it unchanged.
            struct_name = obj_type.enum_name
            struct_info = self.get_enum_info(struct_name)
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call method on non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if struct_name is None or struct_info is None:
            return None
        type_subst: Dict[str, SawType] = {}
        if struct_info.type_params and obj_type.type_args:
            for type_param, type_arg in zip(struct_info.type_params, obj_type.type_args):
                type_subst[type_param.name] = type_arg

        # Look up method - first check specialized extensions, then generic
        method_info = self._lookup_method(struct_info, expr.method_name, obj_type.type_args)
        # Member visibility (design 80): gate a directly-resolved instance method
        # (before the Arc/Box payload-forward fallbacks, which are a separate
        # mechanism keyed on the payload type's own access).
        if method_info is not None:
            self._check_method_visible(struct_name, expr.method_name, method_info, expr)
        # Overloading (design 55): a method name with 2+ overloads on this struct
        # resolves through the exact-match resolver (before effect edges are
        # recorded), then feeds the shared downstream machinery.
        if method_info is not None:
            method_overloads = self._scoped_method_overloads(
                struct_name, expr.method_name, struct_info)
            if len(method_overloads) > 1:
                # Design 142: two visible extensions of one type may share a name
                # (they resolve by the ordinary overload rules), but a
                # signature-identical pair from two modules is unresolvable here.
                clash = self._first_cross_module_method_clash(method_overloads)
                if clash is not None:
                    a, b = clash
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"ambiguous method `{expr.method_name}` on `{struct_name}`: "
                        f"`{self._module_label(a.def_module)}` and "
                        f"`{self._module_label(b.def_module)}` both extend it with "
                        f"an indistinguishable signature",
                        expr.line, expr.column,
                        hint="import only one of the two modules here, or move the "
                             "call into a file that sees a single definition")
                    return None
                return self._check_overloaded_method_call(
                    expr, struct_name, method_overloads, obj_type, type_subst)
            # Design 142: a method can carry a module-discriminated codegen
            # symbol while only ONE of its overloads is visible here — the other
            # lives in a module this file does not import. The overload path
            # never runs, so stamp the resolved symbol ourselves; without it
            # codegen would mangle the plain name and find no definition.
            if getattr(method_info, 'mangled_name', ''):
                expr.resolved_symbol = method_info.mangled_name
        # Arc payload access via method forwarding (design 21b E2). When a method
        # is not found on `Arc<T>` itself but exists on the payload `T` with an
        # immutable `&self` receiver, forward the call to the payload through an
        # immutable borrow of the control block's payload slot. This is sound: a
        # live strong reference pins the payload, so a shared read cannot dangle.
        # A `&var self` payload method is REJECTED — aliased mutation through a
        # shared `Arc` is exactly what `Mutex` exists to make safe.
        if method_info is None and struct_name == "Arc" and obj_type.type_args:
            fwd = self._resolve_arc_forward(expr, obj_type.type_args[0])
            if fwd == "rejected":
                return None
            if fwd is not None:
                method_info, type_subst = fwd
                expr.arc_forward_payload_type = obj_type.type_args[0]
        # Box payload forwarding (design 42 item 1): same mechanism as Arc — an
        # immutable `&self` payload method is callable through the Box, borrowing
        # the heap `T` at `ptr[0]`; a `&var self` payload method is REJECTED. The
        # payload is the FIRST type arg (`Box<T, A>`); `A` is the allocator.
        if method_info is None and struct_name == "Box" and obj_type.type_args:
            fwd = self._resolve_arc_forward(expr, obj_type.type_args[0], through="Box")
            if fwd == "rejected":
                return None
            if fwd is not None:
                method_info, type_subst = fwd
                expr.box_forward_payload_type = obj_type.type_args[0]
        if method_info is None:
            # A call through a function-typed struct field: `obj.field(args)`
            # where `field: (…) -> …` (design 24 item 3). Treated as an indirect
            # call; the field's type drives suspendability — a non-`sync` field
            # type conservatively suspends the caller.
            fields = getattr(struct_info, 'fields', None)
            field_type = fields.get(expr.method_name) if fields else None
            if field_type is not None:
                if type_subst:
                    field_type = field_type.substitute(type_subst)
                if field_type.kind == TypeKind.FUNCTION:
                    return self._check_field_call(expr, field_type)
                # design 77 item 4: an opt-encoded closure frame field
                # (`f: (()->Int)?` on a synthesized `__Frame_*` struct) is called
                # through `self.f` — force-unwrap to the closure and dispatch as an
                # indirect field call. Restricted to frame structs so a user's
                # optional-closure field keeps its current (non-callable) meaning.
                if (field_type.kind == TypeKind.OPTIONAL
                        and field_type.inner_type is not None
                        and field_type.inner_type.kind == TypeKind.FUNCTION
                        and struct_name.startswith("__Frame_")):
                    expr.field_call_unwrap = True
                    return self._check_field_call(expr, field_type.inner_type)
            # Design 142: the method may exist, just not here. Name the module
            # that defines it and the import that would bring it into scope —
            # otherwise the reader concludes the method is missing and writes a
            # second copy of it.
            unimported = self._out_of_scope_method_modules(
                struct_info, expr.method_name, obj_type.type_args)
            if unimported:
                mods = ", ".join(f"`{m}`" for m in unimported)
                one = unimported[0]
                self._error(
                    ErrorKind.UNDEFINED_FUNCTION,
                    f"type `{struct_name}` has no method `{expr.method_name}` "
                    f"in scope here",
                    expr.line, expr.column,
                    hint=f"{mods} extends `{struct_name}` with `{expr.method_name}`, "
                         f"but this file does not import it — add `import {one}`"
                )
                return None
            # Collect available methods from both generic and specialized,
            # excluding any this file cannot see.
            available = [n for n, sym in struct_info.methods.items()
                         if self._ext_scope_allows(sym, struct_info)]
            if obj_type.type_args:
                spec_key = self._make_specialization_key(obj_type.type_args)
                if spec_key in struct_info.specialized_methods:
                    available.extend(
                        n for n, sym in struct_info.specialized_methods[spec_key].items()
                        if self._ext_scope_allows(sym, struct_info))
            # Design 150 pin 4: a shadowed module qualifier explains this call
            # far better than a method list does.
            shadow = self._qualifier_shadow_hint(expr.object, expr.method_name)
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{struct_name}` has no method `{expr.method_name}`",
                expr.line, expr.column,
                hint=shadow or (
                    f"available methods: {', '.join(sorted(set(available)))}"
                    if available else "no methods defined")
            )
            return None
        # Conditional conformance: a method declared in a bounded extension
        # (`extension Vector<T: Copy>`) does not exist for an instantiation whose
        # type args fail the bound. Diagnose the call by naming the unmet bound.
        unmet = self._unmet_extension_bound(method_info, type_subst)
        if unmet is not None:
            param_name, bound, concrete = unmet
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{obj_type}` has no method `{expr.method_name}`: "
                f"requires `{param_name}: {bound}`, and `{concrete}` does not conform",
                expr.line, expr.column,
                hint=f"`{expr.method_name}` is only available when `{param_name}` satisfies `{bound}`"
            )
            return None
        if expr.method_name == "deinit":
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `deinit` manually; it is called automatically when the value goes out of scope",
                expr.line, expr.column,
                hint="use a nested scope or `move` to transfer ownership if you need early cleanup"
            )
            return None
        # design 141: a named `borrows` accessor (`v.get(i)`, `v.first()`) hands
        # out a PLACE. Its window closures are compiler-added trailing
        # parameters, so the ordinary arity path below would count them against
        # the author; place checking owns the call from here.
        if (self._place_accessor_node(method_info) is not None
                and not getattr(expr, 'place_lowered', False)):
            return self._check_place_use(
                expr, method_info, struct_name, obj_type, expr.method_name,
                [a.value for a in expr.arguments])
        # Method-level generic type parameters (brief 36): fold the call-site type
        # arguments (`v.map<Int>(...)`) into the substitution map alongside the
        # struct's own args, so param/return types mentioning the method's own
        # params (`(T) -> U`, `-> Vector<U>`) resolve concretely. Design 93: an
        # omitted (or partially-omitted) argument list is INFERRED from the
        # argument types — a bare `v.map({ $0.to_string() })` solves `U` from the
        # closure's inferred return. Explicit-and-complete wins unchanged.
        method_type_params = method_info.type_params or []
        provided_type_args = expr.type_args or []
        if method_type_params:
            if len(provided_type_args) > len(method_type_params):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` expects {len(method_type_params)} "
                    f"type argument(s), got {len(provided_type_args)}",
                    expr.line, expr.column
                )
            elif len(provided_type_args) < len(method_type_params):
                off = 1 if not method_info.is_init else 0
                # Design 105: label-map before unification (logical param names
                # exclude the receiver `self`).
                infer_mapping = self._infer_label_mapping(
                    expr, method_info.param_names[off:],
                    (method_info.default_values[off:]
                     if method_info.default_values else None))
                full = self._solve_call_type_args(
                    method_type_params, method_info.param_types[off:], expr,
                    infer_mapping, type_subst, provided_type_args,
                    f"method `{expr.method_name}`", expr.line, expr.column,
                    default_values=(method_info.default_values[off:]
                                    if method_info.default_values else None))
                if full is None:
                    return None
                expr.type_args = [full[tp.name] for tp in method_type_params]
                for tp in method_type_params:
                    type_subst[tp.name] = full[tp.name]
                self._check_type_param_bounds(
                    method_type_params, type_subst, expr.line, expr.column)
            else:
                for tp, ta in zip(method_type_params, provided_type_args):
                    type_subst[tp.name] = self._resolve_type(ta)
                self._check_type_param_bounds(
                    method_type_params, type_subst, expr.line, expr.column)
        elif provided_type_args:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"method `{expr.method_name}` is not generic but was called with "
                f"type arguments",
                expr.line, expr.column
            )
        # design 22: record the call edge to the resolved method's suspend node.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        param_offset = 1 if not method_info.is_init else 0
        total_params = len(method_info.param_types) - param_offset
        defaults_for_params = method_info.default_values[param_offset:] if method_info.default_values else []
        required_count = sum(1 for dv in defaults_for_params if dv is None) if defaults_for_params else total_params
        logical_names = method_info.param_names[param_offset:]
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, logical_names, defaults_for_params,
                                      expr.method_name)
            if mapping is None:
                return method_info.return_type
        else:
            mapping = None
            if len(expr.arguments) < required_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes at least {required_count} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
            if len(expr.arguments) > total_params:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` takes at most {total_params} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            declared_type = method_info.param_types[p + param_offset]
            expected_type = declared_type
            if type_subst:
                expected_type = expected_type.substitute(type_subst)
            allow_wrap = self._df3_allow_wrap(
                declared_type, set(type_subst.keys()) if type_subst else None)
            # Closure arguments infer their parameter types from the expected
            # function type and may carry reference params (e.g. Mutex.lock).
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                arg_type = self._check_expression(arg.value)
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                param_name = method_info.param_names[p + param_offset]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Design 40 item 6 (L11): a `&var self` method mutates its receiver, so
        # it may not be called on an immutable `let` (or `&`) binding — the same
        # rule as a `p.x = ...` field write. (`init` builds a fresh value; not a
        # receiver mutation.)
        # design 141: an EXCLUSIVE place window borrows its root mutably even
        # though the accessor declares `&self` — one body serves both flavors,
        # and the use site picks. So `let v` plus `v[0].n = 1` is the same
        # immutable-binding error a `&var self` method would give.
        window_exclusive = getattr(expr, 'place_window_exclusive', False)
        if ((getattr(method_info, "self_mutable", False) or window_exclusive)
                and not method_info.is_init):
            imm_root = self._assign_target_immutable_struct_root(expr.object)
            if imm_root is not None:
                what = (f"open an exclusive place window on"
                        if window_exclusive
                        else f"call `&var self` method `{expr.method_name}` on")
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot {what} immutable variable `{imm_root}`",
                    expr.line, expr.column,
                    hint="consider using `var` instead of `let` to make it mutable",
                )
        # Exclusivity: the receiver of a `var self` method is a mutable path;
        # its parameter types (excluding self) align with the arguments.
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, method_info.param_types[param_offset:], logical_names)
        self._check_call_exclusivity(
            [a.value for a in expr.arguments],
            aligned_types,
            receiver=expr.object if not method_info.is_init else None,
            receiver_mutable=method_info.self_mutable or window_exclusive,
            param_names=aligned_names,
        )
        return_type = method_info.return_type
        if type_subst:
            return_type = return_type.substitute(type_subst)
        # design 62 G3: mark a cooperative `Channel.receive()` call so the coro
        # transform lowers the call site INLINE into the try_receive+yield_now loop
        # (the method itself is never monomorphized). Its `receive` body reaches
        # `yield_now`, so the effect edge recorded above already taints the caller.
        if struct_name == "Channel" and expr.method_name == "receive":
            expr.is_chan_recv = True
        return return_type

    def _check_overloaded_module_function_call(self, expr, candidates):
        """Resolve and check a module-qualified call to an overloaded function
        (design 55). Modules are merged at codegen, so the resolved overload's
        stamped symbol is a plain global — routed via expr.resolved_symbol."""
        arg_types = self._overload_arg_types(expr)
        func_info, mapping = self._resolve_overload(
            expr.method_name, candidates, arg_types,
            self._has_explicit_type_args(expr),
            is_method=False, line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst={})
        if func_info is None:
            return None
        if func_info.mangled_name:
            expr.resolved_symbol = func_info.mangled_name
        self._stamp_overload_plan(expr, func_info.param_names, mapping)
        self._effect_call_function(func_info, expr.method_name, expr.line)
        param_types = func_info.param_types
        return_type = func_info.return_type
        # Design 105: a generic module-function overload selected by inference.
        if func_info.type_params:
            type_map = {}
            for tp, ta in zip(func_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                func_info.type_params, type_map, expr.line, expr.column)
            resolved_args = [type_map.get(tp.name) for tp in func_info.type_params]
            if all(a is not None and self._is_concrete_type(a)
                   for a in resolved_args):
                self._effect_record_poly_call(
                    expr.method_name, resolved_args,
                    f"`{expr.method_name}`", expr.line)
            param_types = [t.substitute(type_map) for t in param_types]
            if return_type is not None:
                return_type = return_type.substitute(type_map)
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        return return_type

    def _check_overloaded_static_method_call(self, expr, struct_name,
                                             struct_info, candidates):
        """Resolve and check an overloaded static method call (design 55):
        `StructName.method(args)` with 2+ static overloads."""
        arg_types = self._overload_arg_types(expr)
        # Build the struct type-param -> concrete map from the receiver's type
        # args (default-filled), as _check_static_method_call does, so a factory
        # whose parameters mention the struct's type params checks concretely.
        # Computed BEFORE resolution so it seeds design-105 inference (base subst).
        obj_type_args = getattr(expr.object, 'type_args', None)
        struct_type_params = getattr(struct_info, 'type_params', None)
        type_map = {}
        if obj_type_args and struct_type_params:
            resolved_args = [self._resolve_type(ta) for ta in obj_type_args]
            resolved_args = self._append_default_type_args(struct_name, resolved_args)
            for tp, ta in zip(struct_type_params, resolved_args):
                type_map[tp.name] = ta
        method_info, mapping = self._resolve_overload(
            f"{struct_name}.{expr.method_name}", candidates, arg_types,
            self._has_explicit_type_args(expr), is_method=True,
            line=expr.line, column=expr.column,
            arguments=expr.arguments, expr=expr, base_subst=dict(type_map))
        if method_info is None:
            return None
        if method_info.mangled_name:
            expr.resolved_symbol = method_info.mangled_name
        self._stamp_overload_plan(expr, method_info.param_names, mapping)
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        # Fold the static method's OWN generic type params (design 105) into the
        # substitution alongside the struct's args.
        if method_info.type_params:
            for tp, ta in zip(method_info.type_params, expr.type_args or []):
                type_map[tp.name] = self._resolve_type(ta)
            self._check_type_param_bounds(
                method_info.type_params, type_map, expr.line, expr.column)
        param_types = method_info.param_types  # static: no self slot
        if type_map:
            param_types = [t.substitute(type_map) if t is not None else t
                           for t in param_types]
        self._finish_overloaded_args(expr, param_types, arg_types, mapping)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping if self._call_has_labels(expr) else None,
            param_types, method_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments], aligned_types,
                                     param_names=aligned_names)
        ret = method_info.return_type
        if ret is not None and type_map:
            ret = ret.substitute(type_map)
        return ret

    def _check_module_function_call(self, expr: MethodCall, func_info) -> Optional[SawType]:
        """Check a module function call: ModuleName.function(args)"""
        # design 24 item 3: record the suspend-graph edge for a module-qualified
        # call. In the whole-program (single-file) path the callee's node is
        # registered under its name and the edge connects; a cross-module callee
        # into a separately-checked module resolves to no node and is a
        # non-suspending leaf (design 22 §5), which is safe today.
        self._effect_call_function(func_info, expr.method_name, expr.line)
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity check and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, list(func_info.param_names),
                                      func_info.default_values, expr.method_name)
            if mapping is None:
                return func_info.return_type
        else:
            mapping = None
            if len(expr.arguments) != len(func_info.param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"function `{expr.method_name}` takes {len(func_info.param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return func_info.return_type
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            expected_type = func_info.param_types[p] if p < len(func_info.param_types) else None
            arg_type = self._check_expression(arg.value)
            allow_wrap = self._df3_allow_wrap(
                expected_type, {tp.name for tp in (func_info.type_params or [])})
            if arg_type and expected_type is not None and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{func_info.param_names[p]}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, func_info.param_types, func_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     aligned_types, param_names=aligned_names)
        return func_info.return_type

    def _check_module_struct_init(self, expr: MethodCall, struct_sym) -> Optional[SawType]:
        """Check a module-qualified struct initialization: ModuleName.StructName(args)

        Uses the struct symbol directly instead of looking up by name.
        """
        struct_name = expr.method_name
        # Design 144: `mod.Point(...)` resolved through the module's namespace,
        # so the identity is known HERE. Stamp it for codegen and build every
        # returned type from it — the bare `Point` would be re-resolved against
        # the merged namespace, which is exactly what this design removes.
        identity = getattr(struct_sym, 'type_identity', "") or struct_name
        expr.resolved_type_identity = identity
        # Build field inits from arguments
        field_inits = [(arg.name, arg.value) for arg in expr.arguments if arg.name]
        if all(arg.name is None for arg in expr.arguments):
            # Positional arguments - use symbol's field_order
            field_inits = []
            for arg, field_name in zip(expr.arguments, struct_sym.field_order):
                field_inits.append((field_name, arg.value))

        provided_params = {field_name for field_name, _ in field_inits}
        field_names = set(struct_sym.fields.keys())
        matches_fields = provided_params == field_names

        # Check for matching init methods
        matching_inits = []
        for method_name, method_info in struct_sym.methods.items():
            if method_info.is_init:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
                    matching_inits.append(method_info)
        # Also check init_methods list
        for method_info in struct_sym.init_methods:
            init_param_names = set(method_info.param_names)
            if provided_params == init_param_names:
                matching_inits.append(method_info)

        total_matches = (1 if matches_fields else 0) + len(matching_inits)
        if total_matches == 0:
            available_inits = [m.param_names for m in struct_sym.methods.values() if m.is_init]
            available_inits.extend([m.param_names for m in struct_sym.init_methods])
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {available_inits}" if available_inits else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym)
        elif total_matches > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym)

        if matches_fields:
            # Member visibility (design 80): cross-module memberwise construction
            # of a module-qualified struct requires all fields visible.
            for _fname in struct_sym.field_order:
                self._check_field_visible(struct_sym, _fname, struct_name, expr)
            # Field initialization
            # design 27 item 3: record "field init, no custom init" so codegen
            # builds the struct memberwise rather than dispatching to an init.
            expr.resolved_init_params = None
            for field_name, field_value in field_inits:
                expected_type = struct_sym.fields[field_name]
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "struct field",
                                           field_value.line, field_value.column)
        else:
            # Custom init method
            method_info = matching_inits[0]
            # Member visibility (design 80): gate a module-qualified custom init.
            self._check_method_visible(struct_name, "init", method_info, expr)
            # design 27 item 3: record which init matched so codegen dispatches to
            # the custom initializer (the module path previously left this unset,
            # so a module-qualified custom init silently fell through to a zeroed
            # memberwise build).
            expr.resolved_init_params = method_info.param_names
            # design 24 item 3: record the suspend-graph edge to the custom init.
            self._effect_call_method(
                method_info, f"`{struct_name}.init`", expr.line)
            init_values = []
            init_param_types = []
            for field_name, field_value in field_inits:
                param_idx = method_info.param_names.index(field_name)
                expected_type = method_info.param_types[param_idx]
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._arg_type_ok(field_value, actual_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument `{field_name}` expects `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "init argument",
                                           field_value.line, field_value.column)
                init_values.append(field_value)
                init_param_types.append(expected_type)
            self._check_call_exclusivity(init_values, init_param_types)

        return SawType(TypeKind.STRUCT, struct_name=identity, symbol=struct_sym)

    def _check_static_method_call(self, expr: MethodCall, struct_name: str,
                                   struct_info, method_info) -> Optional[SawType]:
        """Check a static method call: StructName.method(args)"""
        # Design 144: the receiver type's identity is what its method symbols
        # are mangled against, so codegen must dispatch on it rather than on
        # the name written at the call site.
        expr.resolved_type_identity = self._sym_identity(struct_info, struct_name)
        # Member visibility (design 80): gate the static method cross-module.
        self._check_method_visible(struct_name, expr.method_name, method_info, expr)
        # design 24 item 3: record the suspend-graph edge to the static method.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        required_count = sum(1 for dv in method_info.default_values if dv is None)
        # Design 66: labeled arguments bind by the binding rule; positional-only
        # calls keep the exact legacy arity checks and identity binding.
        has_labels = self._call_has_labels(expr)
        if has_labels:
            mapping = self._bind_args(expr, list(method_info.param_names),
                                      method_info.default_values,
                                      f"{struct_name}.{expr.method_name}")
            if mapping is None:
                return method_info.return_type
        else:
            mapping = None
            if len(expr.arguments) < required_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"static method `{struct_name}.{expr.method_name}` takes at least {required_count} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
            if len(expr.arguments) > len(method_info.param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"static method `{struct_name}.{expr.method_name}` takes at most {len(method_info.param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return method_info.return_type
        # Build the struct type-param -> concrete-arg map from the receiver's
        # explicit type args (default-filled, design 37), so a static factory
        # whose PARAMETERS mention the struct's type params — `Box<Int>.make(v: T)`
        # — checks `v` against the concrete `Int`, not the abstract `T`. Vector's
        # `try_with_capacity(n: Int)` has no such param and is unaffected.
        obj_type_args = getattr(expr.object, 'type_args', None)
        struct_type_params = getattr(struct_info, 'type_params', None)
        type_map = {}
        if obj_type_args and struct_type_params:
            resolved_args = [self._resolve_type(ta) for ta in obj_type_args]
            resolved_args = self._append_default_type_args(struct_name, resolved_args)
            for tp, ta in zip(struct_type_params, resolved_args):
                type_map[tp.name] = ta
        for i, arg in enumerate(expr.arguments):
            p = mapping[i] if mapping is not None else i
            declared_type = method_info.param_types[p]
            expected_type = declared_type
            if expected_type is not None and type_map:
                expected_type = expected_type.substitute(type_map)
            if not isinstance(arg.value, ClosureExpr):
                self._apply_literal_expected_type(arg.value, expected_type)
            arg_type = self._check_expression(arg.value)
            allow_wrap = self._df3_allow_wrap(
                declared_type, set(type_map.keys()) if type_map else None)
            if self._try_existential_arg_coercion(arg, arg_type, expected_type):
                pass  # `&concrete -> &any Trait` erasure (or its error) handled
            elif arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type, allow_wrap):
                param_name = method_info.param_names[p]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        aligned_types, aligned_names = self._aligned_call_meta(
            expr, mapping, method_info.param_types, method_info.param_names)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     aligned_types,
                                     param_names=aligned_names)
        # For a static factory on a GENERIC struct called with explicit type
        # args (`Vector<Int>.try_with_capacity(...)`), substitute the struct's
        # type params into the return type so the caller sees the concrete
        # instantiation (`Result<Vector<Int>, AllocError>`). Without this the
        # return type keeps the generic `T`, and a `match` on the result can't
        # resolve its monomorphized enum. Positional map: the struct's type
        # params line up with the type args on the call's object.
        # Substitute the same map into the return type so the caller sees the
        # concrete instantiation (`Result<Vector<Int, Global>, AllocError>`,
        # `Box<Int, Global>`) rather than the abstract `T`/`A` — needed so a
        # `match` resolves its monomorphized enum and the extracted value finds
        # its methods (design 37 default-fill already applied when building the map).
        ret = method_info.return_type
        if ret is not None and type_map:
            ret = ret.substitute(type_map)
        return ret

    def _check_self_expr(self, expr: SelfExpr) -> Optional[SawType]:
        """Check 'self' keyword usage."""
        if self.current_method is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' can only be used inside methods",
                expr.line, expr.column
            )
            return None
        var_info = self.current_scope.lookup("self")
        if not var_info:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' not found in method scope",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_enum_init(self, expr: EnumInit) -> Optional[SawType]:
        """Check enum variant initialization."""
        # Use direct symbol if available (for module-qualified enums)
        enum_info = expr.enum_symbol if expr.enum_symbol else self.get_enum_info(expr.enum_name)
        if enum_info is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined enum `{expr.enum_name}`",
                expr.line, expr.column
            )
            return None
        # Design 144: an enum reference carries its identity onward, exactly
        # like a struct one — a backed enum's `as` and `from(raw:)` both key on
        # it, so a private `enum Header` in two modules stays two enums with
        # two tag tables.
        expr.enum_name = (getattr(enum_info, 'type_identity', "")
                          or expr.enum_name)
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params:
            if not expr.type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic enum `{expr.enum_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.enum_name}<...>.{expr.variant_name}(...)`"
                )
            elif len(expr.type_args) != len(enum_info.type_params):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(enum_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                for type_param, type_arg in zip(enum_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg
        if expr.variant_name not in enum_info.variants:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"enum `{expr.enum_name}` has no variant `{expr.variant_name}`",
                expr.line, expr.column
            )
            return None
        expected_params = enum_info.variants[expr.variant_name]
        if type_mapping:
            expected_params = [(name, typ.substitute(type_mapping))
                               for name, typ in expected_params]
        if len(expr.arguments) != len(expected_params):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"variant `{expr.variant_name}` expects {len(expected_params)} arguments, got {len(expr.arguments)}",
                expr.line, expr.column
            )
            return None
        expected_dict = {name: typ for name, typ in expected_params}
        expected_list = expected_params
        for i, arg in enumerate(expr.arguments):
            if arg.is_named:
                if arg.name not in expected_dict:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"variant `{expr.variant_name}` has no parameter named `{arg.name}`",
                        expr.line, expr.column
                    )
                    continue
                arg_type = self._check_expression(arg.value)
                expected_type = expected_dict[arg.name]
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{arg.name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
                # Design 87: adopt a fixed-width payload type + range check
                # (post-hoc: the payload arg is checked before this point).
                self._apply_literal_expected_type(arg.value, expected_type)
                self._check_value_transfer(arg.value, expected_type, "enum payload",
                                           arg.value.line, arg.value.column)
            else:
                if i >= len(expected_list):
                    continue
                param_name, expected_type = expected_list[i]
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._arg_type_ok(arg.value, arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{param_name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
                # Design 87: adopt a fixed-width payload type + range check
                # (post-hoc: the payload arg is checked before this point).
                self._apply_literal_expected_type(arg.value, expected_type)
                self._check_value_transfer(arg.value, expected_type, "enum payload",
                                           arg.value.line, arg.value.column)
        return SawType(TypeKind.ENUM, enum_name=expr.enum_name, type_args=expr.type_args, symbol=enum_info)

    def _check_match_expr(self, expr: MatchExpr) -> Optional[SawType]:
        """Check match expression."""
        from .core import VariableInfo, Scope
        matched_type = self._check_expression(expr.matched_expr)
        if matched_type is None:
            return None
        # Normalize a STRUCT-kind user enum (or Result) to its ENUM form. A
        # generic function's declared return type (e.g. `Result<T, E>`) is stored
        # unresolved, so a call like `wrapOk<Int, Int>(7)` yields a STRUCT-kind
        # `Result<Int, Int>`; the concrete-consumer path resolves it at binding
        # time, but a direct `match` at the call site must resolve it here too
        # (brief 36, L7).
        matched_type = self._resolve_type(matched_type)
        # design 63 T1d: route value/tuple scrutinees, and any match using guards
        # or literal/range/tuple patterns, through the general pattern checker.
        # Classic enum-variant/wildcard matches keep the switch path untouched.
        if self._match_needs_general(expr, matched_type):
            return self._check_match_general(expr, matched_type)
        if matched_type.kind != TypeKind.ENUM or matched_type.enum_name is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"match expression requires an enum type, got `{matched_type}`",
                expr.line, expr.column
            )
            return None

        # Store the matched type for codegen (avoids needing to match by LLVM type)
        expr.matched_enum_type = matched_type

        enum_info = self.get_enum_info(matched_type.enum_name, from_type=matched_type)
        if enum_info is None:
            return None
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params and matched_type.type_args:
            for type_param, type_arg in zip(enum_info.type_params, matched_type.type_args):
                type_mapping[type_param.name] = type_arg
        arm_types = []
        matched_variants = set()
        has_wildcard = False
        # Move dataflow (design 15 rule 6): every arm is a branch from the same
        # entry state; after the (exhaustive) match a binding is may-moved if any
        # non-diverging arm moved it.
        entry_moves = self._snapshot_moves()
        arm_move_states = []
        for arm in expr.arms:
            if arm.variant_name == "_":
                has_wildcard = True
                if arm.bindings:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "wildcard pattern `_` cannot have bindings",
                        arm.line, arm.column
                    )
                self.moved_bindings = dict(entry_moves)
                if isinstance(arm.body, Block):
                    arm_type = self._check_block(arm.body)
                else:
                    arm_type = self._check_expression(arm.body)
                arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
                arm_types.append(arm_type)
                continue
            if arm.variant_name not in enum_info.variants:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"enum `{matched_type.enum_name}` has no variant `{arm.variant_name}`",
                    arm.line, arm.column
                )
                continue
            matched_variants.add(arm.variant_name)
            variant_params = enum_info.variants[arm.variant_name]
            if type_mapping:
                variant_params = [(name, typ.substitute(type_mapping))
                                  for name, typ in variant_params]
            if len(arm.bindings) != len(variant_params):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"variant `{arm.variant_name}` has {len(variant_params)} associated values, got {len(arm.bindings)} bindings",
                    arm.line, arm.column
                )
                continue
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)
            self.moved_bindings = dict(entry_moves)
            for binding_name, (_, param_type) in zip(arm.bindings, variant_params):
                # Skip wildcard bindings - they don't create variables
                if binding_name == '_':
                    continue
                # Design 100: a variant-pattern binding BINDS (it does not
                # compare) — shadowing an enclosing binding is a flat error.
                self._check_shadowing(binding_name, None, arm.line, arm.column,
                                      site="pattern")
                var_info = VariableInfo(
                    type=param_type,
                    mutable=False,
                    line=arm.line,
                    column=arm.column
                )
                if not self.current_scope.define(binding_name, var_info):
                    self._error(
                        ErrorKind.DUPLICATE_VARIABLE,
                        f"binding `{binding_name}` is already defined in this scope",
                        arm.line, arm.column
                    )
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)
            arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
            arm_types.append(arm_type)
            self.current_scope = old_scope
        # Merge arm move-states (excluding diverging arms). If no arm produced a
        # state (all were error arms), fall back to the entry state.
        if arm_move_states:
            self.moved_bindings = self._merge_move_branches(entry_moves, arm_move_states)
        else:
            self.moved_bindings = dict(entry_moves)
        if not has_wildcard:
            all_variants = set(enum_info.variants.keys())
            missing_variants = all_variants - matched_variants
            if missing_variants:
                missing_list = ", ".join(f"`{v}`" for v in sorted(missing_variants))
                self._error(
                    ErrorKind.NON_EXHAUSTIVE_MATCH,
                    f"match is not exhaustive, missing variants: {missing_list}",
                    expr.line, expr.column,
                    hint="add missing cases or use `case _ ->` as a default"
                )
        return self._reconcile_match_arm_types(expr, arm_types)

    @staticmethod
    def _arm_yields_no_value(arm_type: Optional[SawType]) -> bool:
        """True when a match arm contributes NO value to the match's result.

        Divergence reaches this function under TWO spellings, and DF-140e was
        conflating them:

        * an arm typed NEVER — a `panic(...)` expression arm (design 49);
        * an arm whose BLOCK has no final expression because every path already
          left the function (`case Ok(v) -> { ...; return }`), which
          `_check_block` reports as a plain `None`.

        Both terminate their basic block, so neither reaches the phi at the
        match's merge. Treating the second as "the arm's type", rather than as
        "no value", made the whole match type NEVER whenever such an arm came
        first — and a NEVER body is compatible with every return type, so the
        Result/Err (or Optional) auto-wrap was skipped and the surviving arm's
        value was returned RAW. `_reconcile_optional_arms` already used this
        convention; the loops below now agree with it.
        """
        return arm_type is None or arm_type.kind == TypeKind.NEVER

    def _reconcile_match_arm_types(self, expr: MatchExpr, arm_types) -> Optional[SawType]:
        """Compute a match expression's result type from its arm types, honoring
        NEVER arms (design 49) and Result auto-wrap. Shared by the enum-switch
        path and the general pattern path (design 63)."""
        if not arm_types:
            return None
        # design 49 + DF-140e: an arm that yields no value (a diverging
        # `panic(...)`, or a block whose every path returned) contributes
        # nothing to the match's type — skip such arms when computing the common
        # arm type. If NO arm yields a value, the whole match is NEVER.
        result_type = None
        for at in arm_types:
            if self._arm_yields_no_value(at):
                continue
            result_type = at
            break
        if result_type is None:
            return SawType(TypeKind.NEVER)

        # DF10: arms mixing an optional (`T?` / `None`) with a bare `T` must ALL
        # become `T?`. Left alone the compatibility loop below either reconciles
        # to the bare `T` (so codegen mixes a bare `ptr` from the value arm with a
        # `{i1, ptr}` from the `None` arm in one phi -> LLVM verifier error) or
        # errors outright. Detect the optional target, then wrap each bare,
        # non-None arm in `OptionalWrap` so the match yields a homogeneous `T?`
        # value — the exact mirror of the Result auto-wrap below.
        opt_reconciled = self._reconcile_optional_arms(expr, arm_types)
        if opt_reconciled is not None:
            return opt_reconciled

        for arm_type in arm_types:
            if self._arm_yields_no_value(arm_type):
                continue
            if not self._types_compatible(result_type, arm_type):
                # Check if arms could be Result auto-wrapped
                # If we're in a function returning Result<T, E> and arms return T and E,
                # they're compatible (will be auto-wrapped later)
                expected_return = None
                if self.current_method:
                    expected_return = self._resolve_type(self.current_method.return_type)
                elif self.current_function:
                    expected_return = self._resolve_type(self.current_function.return_type)

                if expected_return and expected_return.is_result():
                    ok_type = expected_return.type_args[0] if expected_return.type_args else None
                    err_type = expected_return.type_args[1] if expected_return.type_args and len(expected_return.type_args) > 1 else None
                    # Check if one arm is Ok type and the other is Err type
                    types_for_result = all(
                        self._arm_yields_no_value(at) or
                        (ok_type and self._types_compatible(at, ok_type)) or
                        (err_type and self._types_compatible(at, err_type))
                        for at in arm_types
                    )
                    if types_for_result:
                        # Wrap arm bodies in ResultOkWrap/ResultErrWrap
                        for i, (arm, arm_type) in enumerate(zip(expr.arms, arm_types)):
                            # An arm that yields no value — a `panic(...)`
                            # (design 49) or a block that already returned
                            # (DF-140e) — has nothing to wrap.
                            if self._arm_yields_no_value(arm_type):
                                continue
                            if ok_type and self._types_compatible(arm_type, ok_type):
                                # Wrap the arm body in ResultOkWrap
                                if isinstance(arm.body, Block) and arm.body.final_expr:
                                    arm.body.final_expr = ResultOkWrap(
                                        value=arm.body.final_expr,
                                        result_type=expected_return,
                                        line=arm.body.final_expr.line,
                                        column=arm.body.final_expr.column
                                    )
                                else:
                                    arm.body = ResultOkWrap(
                                        value=arm.body,
                                        result_type=expected_return,
                                        line=arm.body.line,
                                        column=arm.body.column
                                    )
                            elif err_type and self._types_compatible(arm_type, err_type):
                                # Wrap the arm body in ResultErrWrap
                                if isinstance(arm.body, Block) and arm.body.final_expr:
                                    arm.body.final_expr = ResultErrWrap(
                                        value=arm.body.final_expr,
                                        result_type=expected_return,
                                        line=arm.body.final_expr.line,
                                        column=arm.body.final_expr.column
                                    )
                                else:
                                    arm.body = ResultErrWrap(
                                        value=arm.body,
                                        result_type=expected_return,
                                        line=arm.body.line,
                                        column=arm.body.column
                                    )
                        return expected_return

                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"match arms have incompatible types: `{result_type}` and `{arm_type}`",
                    expr.line, expr.column
                )
                return None
        return result_type

    def _reconcile_optional_arms(self, expr: MatchExpr, arm_types) -> Optional[SawType]:
        """DF10: reconcile match arms that mix `T?`/`None` with a bare `T` to a
        single `T?`, wrapping each bare non-None arm in `OptionalWrap`.

        Returns the reconciled `T?` type when the arms are such a mix (and every
        arm is the optional, a `None` literal, or the inner `T`); otherwise None,
        leaving the caller's normal reconciliation/Result-wrap path in charge.
        """
        # The optional target: an explicit `T?` arm, else `Optional<T>` inferred
        # from a `None` literal arm plus a concrete bare arm.
        inner = None
        for at in arm_types:
            if at is not None and at.kind != TypeKind.NEVER and at.is_optional():
                inner = at.inner_type
                break
        if inner is None:
            has_none = any(at is not None and at.kind != TypeKind.NEVER
                           and at.is_none_literal() for at in arm_types)
            if not has_none:
                return None
            for at in arm_types:
                if (at is not None and at.kind != TypeKind.NEVER
                        and not at.is_none_literal() and not at.is_optional()):
                    inner = at
                    break
        if inner is None:
            return None

        # Only reconcile when EVERY non-never arm is the optional, a None literal,
        # or the inner `T` — otherwise this isn't a clean optional mix; let the
        # normal path report the incompatibility.
        def _fits(at):
            return (at is None or at.kind == TypeKind.NEVER or at.is_optional()
                    or at.is_none_literal() or self._types_compatible(at, inner))
        if not all(_fits(at) for at in arm_types):
            return None

        opt_target = SawType(TypeKind.OPTIONAL, inner_type=inner)
        for arm, at in zip(expr.arms, arm_types):
            if (at is None or at.kind == TypeKind.NEVER
                    or at.is_optional() or at.is_none_literal()):
                continue
            # Wrap the bare-`T` arm body (or its block tail) into `Some(...)`.
            if isinstance(arm.body, Block) and arm.body.final_expr is not None:
                arm.body.final_expr = OptionalWrap(
                    value=arm.body.final_expr, target_type=opt_target,
                    line=arm.body.final_expr.line, column=arm.body.final_expr.column)
            else:
                arm.body = OptionalWrap(
                    value=arm.body, target_type=opt_target,
                    line=arm.body.line, column=arm.body.column)
        return opt_target

    # ===== General pattern match (design 63 T1d) =====

    _INT_PATTERN_KINDS = {
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    }

    def _match_needs_general(self, expr: MatchExpr, matched_type: SawType) -> bool:
        """True when a match must use the general pattern checker rather than the
        classic enum switch: a non-enum scrutinee, or an enum scrutinee whose
        arms use guards / literal / range / tuple / bare-binding patterns."""
        underlying = self._get_underlying_type(matched_type)
        if underlying.kind != TypeKind.ENUM:
            return True
        for arm in expr.arms:
            if arm.guard is not None:
                return True
            p = arm.pattern
            if p is None or isinstance(p, WildcardPattern):
                continue
            if isinstance(p, EnumPattern):
                if all(isinstance(s, (BindingPattern, WildcardPattern))
                       for s in p.subpatterns):
                    continue
                return True
            return True
        return False

    def _pattern_is_irrefutable(self, pattern) -> bool:
        """True when a pattern always matches (binds only): a wildcard, a bare
        binding, or a tuple of irrefutable elements. Used for exhaustiveness (an
        irrefutable arm is a fallback) and for `let`/`var` destructuring (only
        irrefutable patterns are allowed there)."""
        if isinstance(pattern, (WildcardPattern, BindingPattern)):
            return True
        if isinstance(pattern, TuplePattern):
            return all(self._pattern_is_irrefutable(e) for e in pattern.elements)
        return False

    def _bind_optional_pattern(self, pattern, inner_type, mutable, line, column):
        """Validate + bind an irrefutable tuple pattern against the unwrapped
        inner type of an `if let`/`guard let` over an Optional tuple (design 63)."""
        if not self._pattern_is_irrefutable(pattern):
            self._error(ErrorKind.TYPE_MISMATCH,
                        "`if let`/`guard let` tuple pattern must be irrefutable "
                        "(bindings, `_`, nested tuples)", line, column)
            return
        it = self._resolve_type_alias(inner_type) if inner_type is not None else None
        if it is None or it.kind != TypeKind.TUPLE or not it.element_types:
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"tuple pattern requires an optional tuple scrutinee, got "
                        f"`{inner_type}?`", line, column)
            return
        if len(pattern.elements) != len(it.element_types):
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"tuple pattern has {len(pattern.elements)} elements but the "
                        f"optional's value has {len(it.element_types)}", line, column)
            return
        self._define_irrefutable_bindings(pattern, inner_type, mutable)

    def _pattern_enum_variants(self, expected_type: SawType):
        """Return {variant_name: [(param_name, param_type), ...]} for an enum or
        Optional scrutinee, or None if the type is not variant-matchable."""
        et = self._resolve_type(expected_type)
        if et.kind == TypeKind.OPTIONAL:
            inner = et.inner_type or SawType(TypeKind.VOID)
            return {"Some": [("value", inner)], "None": []}
        if et.kind == TypeKind.ENUM and et.enum_name is not None:
            enum_info = self.get_enum_info(et.enum_name, from_type=et)
            if enum_info is None:
                return None
            type_mapping = {}
            if enum_info.type_params and et.type_args:
                for tp, ta in zip(enum_info.type_params, et.type_args):
                    type_mapping[tp.name] = ta
            variants = {}
            for vname, params in enum_info.variants.items():
                if type_mapping:
                    params = [(n, t.substitute(type_mapping)) for n, t in params]
                variants[vname] = params
            return variants
        return None

    def _check_pattern(self, pattern, expected_type: SawType):
        """Validate a pattern against the scrutinee (sub)type and define its
        bindings in the current scope."""
        from .core import VariableInfo
        underlying = self._get_underlying_type(expected_type)
        if isinstance(pattern, WildcardPattern):
            return
        if isinstance(pattern, BindingPattern):
            # Design 100: a pattern binding BINDS (it does not compare) —
            # shadowing an enclosing binding is a flat error.
            self._check_shadowing(pattern.name, None, pattern.line,
                                  pattern.column, site="pattern")
            var_info = VariableInfo(type=expected_type, mutable=False,
                                    line=pattern.line, column=pattern.column)
            if not self.current_scope.define(pattern.name, var_info):
                self._error(ErrorKind.DUPLICATE_VARIABLE,
                            f"binding `{pattern.name}` is already defined in this scope",
                            pattern.line, pattern.column)
            return
        if isinstance(pattern, LiteralPattern):
            lit_type = self._check_expression(pattern.value)
            if lit_type is not None:
                lu = self._get_underlying_type(lit_type)
                ok = False
                if lu.kind in self._INT_PATTERN_KINDS and underlying.kind in self._INT_PATTERN_KINDS:
                    ok = True
                elif lu.kind == underlying.kind and lu.kind in (TypeKind.STRING, TypeKind.BOOL):
                    ok = True
                if not ok:
                    self._error(ErrorKind.TYPE_MISMATCH,
                                f"literal pattern of type `{lit_type}` cannot match "
                                f"scrutinee of type `{expected_type}`",
                                pattern.line, pattern.column)
            return
        if isinstance(pattern, RangePattern):
            if underlying.kind not in self._INT_PATTERN_KINDS:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"range pattern requires an integer scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
            self._check_expression(pattern.start)
            self._check_expression(pattern.end)
            return
        if isinstance(pattern, TuplePattern):
            if underlying.kind != TypeKind.TUPLE or not underlying.element_types:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"tuple pattern requires a tuple scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
                return
            if len(pattern.elements) != len(underlying.element_types):
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"tuple pattern has {len(pattern.elements)} elements but "
                            f"scrutinee has {len(underlying.element_types)}",
                            pattern.line, pattern.column)
                return
            for sub, et in zip(pattern.elements, underlying.element_types):
                self._check_pattern(sub, et)
            return
        if isinstance(pattern, EnumPattern):
            variants = self._pattern_enum_variants(expected_type)
            if variants is None:
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"variant pattern `{pattern.variant_name}` requires an enum "
                            f"scrutinee, got `{expected_type}`",
                            pattern.line, pattern.column)
                return
            if pattern.variant_name not in variants:
                self._error(ErrorKind.UNDEFINED_VARIABLE,
                            f"no variant `{pattern.variant_name}` on `{expected_type}`",
                            pattern.line, pattern.column)
                return
            params = variants[pattern.variant_name]
            if len(pattern.subpatterns) != len(params):
                self._error(ErrorKind.TYPE_MISMATCH,
                            f"variant `{pattern.variant_name}` has {len(params)} "
                            f"associated values, got {len(pattern.subpatterns)}",
                            pattern.line, pattern.column)
                return
            for sub, (_pn, pt) in zip(pattern.subpatterns, params):
                self._check_pattern(sub, pt)
            return

    def _check_match_general(self, expr: MatchExpr, matched_type: SawType) -> Optional[SawType]:
        """Type check a value/tuple/guarded match (design 63 T1d)."""
        from .core import VariableInfo, Scope
        # Flag + scrutinee type for the codegen general path.
        expr.use_general_match = True
        expr.matched_scrutinee_type = matched_type
        underlying = self._get_underlying_type(matched_type)
        arm_types = []
        entry_moves = self._snapshot_moves()
        arm_move_states = []
        has_catchall = False
        bool_true = False
        bool_false = False
        covered_variants = set()  # unguarded, fully-irrefutable variant arms
        for arm in expr.arms:
            p = arm.pattern
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)
            self.moved_bindings = dict(entry_moves)
            if p is not None:
                self._check_pattern(p, matched_type)
            if arm.guard is not None:
                gtype = self._check_expression(arm.guard)
                if gtype is not None and self._get_underlying_type(gtype).kind != TypeKind.BOOL:
                    self._error(ErrorKind.TYPE_MISMATCH,
                                f"match guard must be `Bool`, got `{gtype}`",
                                arm.line, arm.column)
            # Catch-all / Bool-coverage tracking (unguarded arms only — a guard
            # can fail, so a guarded arm never proves exhaustiveness).
            if arm.guard is None:
                if self._pattern_is_irrefutable(p):
                    has_catchall = True
                elif isinstance(p, LiteralPattern) and isinstance(p.value, BoolLiteral):
                    if p.value.value:
                        bool_true = True
                    else:
                        bool_false = True
                elif (isinstance(p, EnumPattern)
                      and all(self._pattern_is_irrefutable(s) for s in p.subpatterns)):
                    # A variant arm with only irrefutable payload sub-bindings
                    # fully covers that variant (enum-variant exhaustiveness on
                    # the general path — lets a guarded enum match stay exhaustive
                    # via variant coverage without a redundant `case _`).
                    covered_variants.add(p.variant_name)
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)
            arm_move_states.append((self._snapshot_moves(), self._arm_diverges(arm.body)))
            arm_types.append(arm_type)
            self.current_scope = old_scope
        if arm_move_states:
            self.moved_bindings = self._merge_move_branches(entry_moves, arm_move_states)
        else:
            self.moved_bindings = dict(entry_moves)
        # Exhaustiveness (design 63): literal/range/guard arms never prove it on an
        # open type — a wildcard or bare-binding arm is required. EXCEPTIONS: a
        # Bool scrutinee covered by both `true` and `false`; a closed integer
        # range-cover is NOT computed in v1 (always require a fallback).
        bool_exhausts = (underlying.kind == TypeKind.BOOL and bool_true and bool_false)
        # Enum / Optional exhaustiveness: all variants covered by unguarded,
        # fully-irrefutable variant arms.
        enum_exhausts = False
        if underlying.kind in (TypeKind.ENUM, TypeKind.OPTIONAL):
            variants = self._pattern_enum_variants(matched_type)
            if variants is not None and set(variants.keys()) <= covered_variants:
                enum_exhausts = True
        if not has_catchall and not bool_exhausts and not enum_exhausts:
            self._error(
                ErrorKind.NON_EXHAUSTIVE_MATCH,
                "match is not exhaustive: literal, range, and guarded arms do not "
                "prove exhaustiveness",
                expr.line, expr.column,
                hint="add a `case _ ->` (or a bare-binding) fallback arm",
            )
        return self._reconcile_match_arm_types(expr, arm_types)

    def _first_reference_in_type(self, t: Optional[SawType]) -> Optional[SawType]:
        """The first reference reachable from `t` without entering a function
        type, or None — the typechecker's copy of the design-163a walk.

        A nested function type is where references belong (`(&T) sync -> R` is
        the `with_ref` callback), so the walk stops there; everything else a type
        can be built out of is searched, since `(Int, &Int)` and `&Int?` escape
        the pointer exactly as well as a bare `&Int`.
        """
        if t is None:
            return None
        if t.kind == TypeKind.REFERENCE:
            return t
        if t.kind == TypeKind.FUNCTION:
            return None
        parts = []
        if t.kind == TypeKind.OPTIONAL:
            parts.append(t.inner_type)
        if t.kind == TypeKind.ARRAY:
            parts.append(t.array_element_type)
        parts.extend(t.element_types or [])
        parts.extend(t.type_args or [])
        for p in parts:
            hit = self._first_reference_in_type(p)
            if hit is not None:
                return hit
        return None

    def _reject_reference_closure_return(self, expr: ClosureExpr,
                                         return_type: SawType) -> SawType:
        """A closure's INFERRED return type may not name a reference (DF-163d).

        Every other return position is refused at the declaration (design 163a),
        which reads the type as WRITTEN. A closure literal writes none, so
        `{ &x }` slipped through and typed `() -> &Int` — a pointer to `x` handed
        out past the call that created it, exactly what design 163a closed for
        named functions. Recovers as the VALUE type so one mistake yields one
        message instead of a cascade.
        """
        found = self._first_reference_in_type(return_type)
        if found is None:
            return return_type
        value = found.inner_type if found.inner_type is not None else "T"
        tail = getattr(expr.body, 'final_expr', None)
        line = tail.line if tail is not None else expr.line
        column = tail.column if tail is not None else expr.column
        if found is return_type:
            names_it = "is a reference"
        else:
            names_it = f"names a reference (`{found}`)"
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"a closure may not return a reference: this body's value has type "
            f"`{return_type}`, which {names_it}, and references in Saw are "
            f"PARAMETERS ONLY — a reference borrows storage for the duration of "
            f"one call and may not escape it (designs 88/106; the Law of "
            f"Exclusivity is statically sound only because every live reference "
            f"belongs to a call still on the stack)",
            line, column,
            hint=f"yield the value instead (drop the `&`, so the closure returns "
                 f"`{value}`), or — to hand out storage something already owns — "
                 f"declare a `borrows` accessor (`... borrows -> {value}` with "
                 f"`lend`, design 141), which lends the place for a window "
                 f"rather than letting a pointer out")
        return found.inner_type if found is return_type else return_type

    def _check_closure(self, expr: ClosureExpr, expected_type: Optional[SawType] = None,
                        as_call_argument: bool = False,
                        force_escape: bool = False) -> Optional[SawType]:
        """Type check a closure expression.

        `as_call_argument` is True only when the closure literal appears directly
        as an argument of the call it is passed to. A closure whose signature has
        reference parameters (`&`/`&var`) is NON-STORABLE (design 21 item 3): it
        may only appear in that position; binding/returning/capturing it is a
        conservative error until full non-escaping closures land.
        """
        from .core import VariableInfo, Scope
        outer_scope = self.current_scope
        self.current_scope = Scope(parent=outer_scope)
        # design 132 unit A: everything the body can WRITE lives at or below this
        # scope. A name that resolves past it came in by value capture, and the
        # env copy makes such a write unobservable — `_capture_write_root` reads
        # this stack to reject it (DF-122a).
        self._closure_scopes.append(self.current_scope)
        # A closure captures by value, so its body has its own function-local
        # move state (design 15); restore the enclosing state on exit.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}
        # design 22: analyze the closure body as its own suspend-graph node. If
        # its target type is a `sync` function type (e.g. `Mutex.lock`'s param),
        # the closure is a sync context checked transitively suspension-free.
        self._effect_enter_closure(expr, expected_type)
        # design 130 q3: a closure that never names an unsafe type is SAFE even
        # when passed into an unsafe function — `v.with_ref(0) { e in e + 1 }`
        # sees only `&T`, and that is what keeps the reviewed wrappers usable from
        # safe code. Where an unsafe value genuinely IS handed to a closure, the
        # closure's parameter type names it. The body is checked against a fresh
        # contact slot; the verdict at the bottom of this function decides which
        # domain that contact belongs to (design 136).
        saved_unsafe_contact = self._unsafe_contact
        self._unsafe_contact = None

        # Bracketed capture list (design 16/29). Borrow captures (`&`/`&var`) are
        # legal ONLY in a closure literal passed directly to a NON-escaping
        # parameter — they lower to pointers into the enclosing frame, sound only
        # because the closure cannot outlive the call. A borrow capture defines a
        # shadowing binding in the closure scope: the name reads/writes the
        # referent, mutable iff `&var`. Value captures (`move`/`copy`/plain) are
        # handled after the body (routed through the value-transfer checkpoint).
        spec_by_name = {}
        target_escaping = bool(expected_type is not None
                               and expected_type.kind == TypeKind.FUNCTION
                               and getattr(expected_type, 'func_is_escaping', False))
        borrow_ok = as_call_argument and not force_escape and not target_escaping
        for spec in (expr.capture_specs or []):
            if spec.name in spec_by_name:
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,
                    f"capture `{spec.name}` listed more than once",
                    spec.line, spec.column)
            spec_by_name[spec.name] = spec
            outer_info = outer_scope.lookup(spec.name)
            if outer_info is None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"capture of undefined variable `{spec.name}`",
                    spec.line, spec.column)
                continue
            if spec.mode in ('ref', 'ref_var'):
                if not borrow_ok:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"borrow capture `&{'var ' if spec.mode == 'ref_var' else ''}"
                        f"{spec.name}` is legal only in a closure passed directly to a "
                        f"non-escaping parameter",
                        spec.line, spec.column,
                        hint="an escaping closure outlives the frame, so it cannot "
                             "borrow it — capture by value (`move`/`copy`) instead")
                    # Fall through and bind it anyway. Recovering as the author
                    # WROTE it keeps this the only complaint about the name; the
                    # design-132 capture-write rule would otherwise fire a second
                    # time on every mutation in the body and bury the real error.
                referent = outer_info.type
                if referent is not None and referent.kind == TypeKind.REFERENCE:
                    referent = referent.inner_type
                self.current_scope.define(spec.name, VariableInfo(
                    referent, spec.mode == 'ref_var', spec.line, spec.column))

        param_types = []
        has_reference_params = False
        if expr.parameters:
            for i, param in enumerate(expr.parameters):
                expected_param = None
                if expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        expected_param = expected_params[i]
                if getattr(param, 'is_reference', False):
                    # Reference-capture param: the bound name has the underlying
                    # type T; the closure's parameter type is `&T` / `&var T`.
                    has_reference_params = True
                    inner = None
                    if param.type_annotation:
                        inner = self._resolve_type(param.type_annotation)
                    elif expected_param is not None:
                        if expected_param.kind in (TypeKind.REFERENCE, TypeKind.POINTER):
                            inner = expected_param.inner_type
                        else:
                            inner = expected_param
                    if inner is None:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Cannot infer type for reference parameter `{param.name}`. "
                            f"Add a type annotation: `&{'var ' if param.reference_mutable else ''}{param.name}: Type`",
                            param.line, param.column
                        )
                        inner = SawType(TypeKind.INT)
                    param_type = SawType(TypeKind.REFERENCE, inner_type=inner,
                                         reference_mutable=param.reference_mutable)
                    param_types.append(param_type)
                    # Design 100: a closure parameter shadowing an enclosing
                    # local (or module static) is a flat error.
                    self._check_shadowing(param.name, None, param.line,
                                          param.column, site="param")
                    # The name reads/writes the referent directly; mutable iff &var.
                    self.current_scope.define(param.name, VariableInfo(
                        inner, param.reference_mutable, param.line, param.column))
                    continue
                if param.type_annotation:
                    param_type = self._resolve_type(param.type_annotation)
                elif expected_param is not None:
                    param_type = expected_param
                elif expected_type and expected_type.kind == TypeKind.FUNCTION:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Closure has more parameters than expected function type",
                        param.line, param.column
                    )
                    param_type = SawType(TypeKind.INT)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for closure parameter `{param.name}`. Add type annotation: `{param.name}: Type`",
                        param.line, param.column
                    )
                    param_type = SawType(TypeKind.INT)
                param_types.append(param_type)
                # Design 100: a closure parameter shadowing an enclosing local
                # (or module static) is a flat error.
                self._check_shadowing(param.name, None, param.line,
                                      param.column, site="param")
                self.current_scope.define(param.name, VariableInfo(param_type, False, param.line, param.column))
        elif expr.shorthand_param_count > 0:
            for i in range(expr.shorthand_param_count):
                if expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        param_type = expected_params[i]
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure uses `${i}` but expected function type only has {len(expected_params)} parameters",
                            expr.line, expr.column
                        )
                        param_type = SawType(TypeKind.INT)
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"Cannot infer type for shorthand parameter `${i}`. Use named parameters with type annotations.",
                        expr.line, expr.column
                    )
                    param_type = SawType(TypeKind.INT)
                param_types.append(param_type)
                self.current_scope.define(f"${i}", VariableInfo(param_type, False, expr.line, expr.column))
        return_type = self._check_block(expr.body)
        if return_type is None:
            return_type = SawType(TypeKind.VOID)
        # A closure may not RETURN a reference (DF-163d). Design 163a refuses a
        # written `-> &T` at every declaration that has one, and a closure
        # literal writes no return type at all — inference is the only place the
        # rule can be applied, so it is applied here. `{ &x }` is the shape:
        # it types `() -> &Int` and hands a pointer to `x` out past the call
        # that made it. The `with_ref` identity closure `{ e in e }` is NOT this
        # case — reading a reference binding yields the VALUE, so it infers `T`.
        return_type = self._reject_reference_closure_return(expr, return_type)
        # A closure passed to a known function type takes its RETURN CONTEXT from
        # that type, the same way a function body takes it from its signature —
        # so a bare `None` in tail position learns what it is a `None` OF. The
        # shape that needed it is the absent path of a conditional lend, `{ None }`
        # checked against `() sync -> T?` (design 141/146, DF-146c): without the
        # pin the optional reached codegen with no inner type at all.
        expected_ret = (expected_type.func_return_type
                        if expected_type is not None
                        and expected_type.kind == TypeKind.FUNCTION else None)
        if expected_ret is not None and expected_ret.kind == TypeKind.TYPE_PARAM:
            expected_ret = None          # unsolved `U` — nothing to pin against
        if expected_ret is not None and return_type.kind == TypeKind.NEVER:
            # A body that never comes back satisfies any expected result type,
            # and the SIGNATURE is what codegen emits — so a `{ panic(...) }`
            # closure in an `-> Int` slot must be an `-> Int` function that
            # happens never to return. This is the absent path of a conditional
            # lend reached through a force-unwrap (`v.get(i)!.m()`), where the
            # `!`'s promise becomes the panic.
            return_type = expected_ret
        elif (expected_ret is not None
                and expected_ret.kind == TypeKind.OPTIONAL
                and expected_ret.inner_type is not None):
            self._propagate_optional_type(expr.body, expected_ret)
            if (return_type.kind == TypeKind.OPTIONAL
                    and return_type.inner_type is None):
                return_type = expected_ret
            elif (not return_type.is_optional()
                    and return_type.kind not in (TypeKind.VOID, TypeKind.NEVER)
                    and expr.body.final_expr is not None):
                # A tail value where an optional is expected AUTO-WRAPS, exactly
                # as it does in a function body — `{ __p in __p }` against
                # `(&var T) sync -> T?` is the present path of a conditional
                # lend, and the wrap is what makes it a `Some` place read.
                expr.body.final_expr = OptionalWrap(
                    value=expr.body.final_expr, target_type=expected_ret,
                    line=expr.body.final_expr.line,
                    column=expr.body.final_expr.column)
                return_type = expected_ret
        captures = self._analyze_closure_captures(expr.body, outer_scope)
        # An explicitly-listed capture is captured even if the body scan missed
        # it (e.g. a borrow named for its side of an exclusivity check). Preserve
        # body-scan order, then append listed-but-unseen names.
        for spec in (expr.capture_specs or []):
            if spec.name not in captures and outer_scope.lookup(spec.name):
                captures.append(spec.name)
        expr.captures = captures
        expr.has_reference_params = has_reference_params
        # Record each capture's effective mode for codegen (design 16/29): listed
        # names take their declared mode; everything else is `plain`.
        expr.capture_modes = {
            name: (spec_by_name[name].mode if name in spec_by_name else 'plain')
            for name in captures
        }
        # Escape analysis (design 21b E1): a closure used in value position (bound
        # to a let/var, returned, stored, or a struct field) outlives the frame
        # that built it, so its environment must be heap-allocated with captured
        # values transferred in per the transfer rules. A closure consumed
        # directly as a call argument to an ordinary function (e.g. Mutex.lock's
        # `sync` closure) does NOT escape — the callee runs it before returning,
        # so a stack env is sound and cheaper. Reference-param closures are
        # forced to be call arguments (checked below) and never escape. `spawn`
        # is the exception: it is a call argument yet the task outlives the call,
        # so the spawn handler passes force_escape=True.
        expr.escapes = force_escape or (
            (not as_call_argument) and (not has_reference_params))
        # design 135: an escaping closure with captures heap-allocates its
        # refcounted environment (design 73), and the literal says nothing about
        # it. A capture-LESS escaping closure is just a code pointer, so it stays
        # legal — the check follows codegen's own condition exactly. `spawn`'s
        # closure is excluded: it escapes only because `spawn` was written, and
        # a call that starts a task is an allocation the source named.
        if (expr.escapes and captures and not force_escape
                and self._hidden_alloc_gate()):
            self._hidden_alloc_error(
                "an escaping closure heap-allocates its captured environment",
                expr.line, expr.column,
                hint="pass the closure straight to the call that runs it (a "
                     "non-escaping closure keeps its environment on the stack), "
                     "drop the captures and take the values as parameters, or "
                     "hold the shared state in an explicit `Box`/`Arc` so the "
                     "allocation is written down")
        self.current_scope = outer_scope
        self._closure_scopes.pop()
        self.moved_bindings = saved_moves
        # Route every VALUE capture (mode plain/move/copy) through the shared
        # value-transfer checkpoint, in the OUTER scope so `move` records the
        # source binding as moved-from (design 03/15/16/29). Borrow captures
        # (ref/ref_var) are not transfers and are skipped. This makes capture
        # rules literally the call-argument rules: plain capture of a
        # NoCopy/ExplicitCopy is an error (demand `move`/`copy`); ImplicitCopy is
        # retained; trivial is copied bitwise; `move`/`copy` are explicit.
        for cap_name in captures:
            mode = expr.capture_modes.get(cap_name, 'plain')
            if mode in ('ref', 'ref_var'):
                continue
            cap_info = outer_scope.lookup(cap_name)
            if cap_info is None:
                continue
            ctype = cap_info.type
            # Forwarding rule (design 16/29 item 5): a non-escaping closure value
            # (e.g. a non-escaping closure PARAMETER) may not be captured by an
            # escaping closure — its own captures could borrow a frame that dies
            # before the escaping closure runs. Genuinely-escaping function
            # values are fine.
            if (expr.escapes and ctype is not None
                    and ctype.kind == TypeKind.FUNCTION
                    and not getattr(ctype, 'func_is_escaping', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot capture non-escaping closure `{cap_name}` in an "
                    f"escaping closure",
                    expr.line, expr.column,
                    hint="an escaping closure outlives the frame; only call a "
                         "non-escaping closure or forward it as a non-escaping argument")
                continue
            if mode == 'move':
                mv = MoveExpr(variable=cap_name, line=expr.line, column=expr.column)
                self._check_move_expr(mv)
                continue
            if mode == 'copy':
                if self._is_no_copy_type(ctype):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot `copy` capture `{cap_name}`: type `{ctype}` "
                        f"implements NoCopy",
                        expr.line, expr.column,
                        hint="use `move {}` to transfer ownership".format(cap_name))
                continue
            # Plain capture: an escaping env must own its captures, so move-only
            # types are rejected; a non-escaping stack env borrows the frame, so
            # a plain capture there is also just a read — but for uniform,
            # explicit semantics we apply the same rule everywhere.
            ident = Identifier(name=cap_name, line=expr.line, column=expr.column)
            ident.resolved_type = ctype
            self._check_value_transfer(ident, ctype, "closure capture",
                                       expr.line, expr.column)
        # A closure with reference parameters is non-storable: legal only as a
        # direct call argument (design 21 item 3). Reject any other position.
        if has_reference_params and not as_call_argument:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "a closure with reference (`&`/`&var`) parameters may only be passed "
                "directly as a call argument; it cannot be bound, returned, or captured",
                expr.line, expr.column,
                hint="call the function that takes it inline, e.g. `m.lock { &var x in ... }`"
            )
        # The closure's own verdict, before the enclosing function's state is
        # restored (design 136).
        #
        # Its TYPE says `unsafe` exactly when its SIGNATURE names an unsafe type,
        # like any other function type — a closure has no effect slot to write,
        # so there is nothing else the bit could come from. That is the
        # `with_raw` shape: the callee hands an unsafe value in, and the slot it
        # was passed to already declared as much.
        #
        # Contact the BODY makes beyond that signature belongs to the ENCLOSING
        # function, which is what "a closure inherits its enclosing function's
        # unsafe domain" means in the checker. The value can only have arrived by
        # capture (the enclosing body bound it) or from a binding written inside
        # the enclosing body, so the enclosing declaration is where a reviewer
        # reads it — and the honest spelling for an unsafe closure in a safe
        # function is to declare that function `unsafe`, or to hoist the work
        # into a named one. Propagating the contact gets exactly that diagnostic
        # from `_exit_unsafe_scope`, naming the enclosing declaration.
        signature_is_unsafe = (
            any(self._type_tree_has_unsafe(pt) for pt in param_types)
            or self._type_tree_has_unsafe(return_type))
        contact = self._unsafe_contact
        self._unsafe_contact = saved_unsafe_contact
        if (contact is not None and not signature_is_unsafe
                and self._unsafe_contact is None):
            self._unsafe_contact = contact
        result_type = SawType(TypeKind.FUNCTION, param_types=param_types,
                              func_return_type=return_type,
                              func_is_unsafe=signature_is_unsafe,
                              func_is_escaping=expr.escapes)
        # Record the resolved signature so codegen lowers parameter/return types
        # (including reference params) accurately rather than guessing. The
        # escaping bit rides along so codegen treats an escaping closure binding as
        # an owning value with drop glue (design 71).
        expr.resolved_type = result_type
        self._effect_exit()
        return result_type

    def _analyze_closure_captures(self, body: Block, outer_scope) -> List[str]:
        """Find every variable from an enclosing scope used in the closure body.

        Walks the full expression/statement tree — control flow (if/if-let/
        while/for/match), operators, calls, casts, and nested closures included —
        so a name used anywhere inside the body (e.g. only within a `while` loop,
        which the old analyzer missed) is detected. Nested closures are recursed
        into as well: a name they reference that resolves in an enclosing scope is
        a transitive capture of this closure too. A name is a capture iff it
        resolves in `outer_scope`; the closure's own params/locals do not.

        The accumulator is an insertion-ordered dict, NOT a set: the returned
        order becomes the closure environment's field order in the emitted IR, so
        iterating a set of names made the compiler emit different IR for the same
        source on every run (Python randomizes string hashing per process). Order
        is first-use order in the body (design 126 R2).
        """
        used_names = {}

        def collect_names(expr):
            if expr is None:
                return
            if isinstance(expr, Identifier):
                used_names[expr.name] = None
            elif isinstance(expr, BinaryOp):
                collect_names(expr.left)
                collect_names(expr.right)
            elif isinstance(expr, UnaryOp):
                collect_names(expr.operand)
            elif isinstance(expr, MoveExpr):
                used_names[expr.variable] = None
            elif isinstance(expr, ReferenceExpr):
                collect_names(expr.expr)
            elif isinstance(expr, CastExpr):
                collect_names(expr.expr)
            elif isinstance(expr, FunctionCall):
                # `f(x)` where `f` is an enclosing closure-typed binding is a
                # capture of `f` (the final `outer_scope.lookup` filter drops
                # top-level function names, which are not locals).
                used_names[expr.name] = None
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, MethodCall):
                collect_names(expr.object)
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, IfExpr):
                collect_names(expr.condition)
                collect_block(expr.then_branch)
                if expr.else_branch:
                    collect_block(expr.else_branch)
            elif isinstance(expr, IfLetExpr):
                collect_names(expr.optional_expr)
                collect_block(expr.then_branch)
                if expr.else_branch:
                    collect_block(expr.else_branch)
            elif isinstance(expr, WhileExpr):
                collect_names(expr.condition)
                collect_block(expr.body)
            elif isinstance(expr, ForLoop):
                collect_names(expr.iterable)
                collect_block(expr.body)
            elif isinstance(expr, MatchExpr):
                collect_names(expr.matched_expr)
                for arm in expr.arms:
                    # An arm body is a Block as often as it is an expression,
                    # and a guard is ordinary code too. Scanning only the
                    # expression form left a name used inside `case A -> { n }`
                    # uncaptured, and the closure ICE'd on it at codegen.
                    if arm.guard is not None:
                        collect_names(arm.guard)
                    if isinstance(arm.body, Block):
                        collect_block(arm.body)
                    else:
                        collect_names(arm.body)
            elif isinstance(expr, RangeExpr):
                collect_names(expr.start)
                collect_names(expr.end)
            elif isinstance(expr, TupleLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, TupleIndex):
                collect_names(expr.tuple_expr)
            elif isinstance(expr, ArrayLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayIndex):
                collect_names(expr.array_expr)
                collect_names(expr.index)
            elif isinstance(expr, MemberAccess):
                collect_names(expr.object)
            elif isinstance(expr, StructInit):
                for _fname, fval in expr.field_inits:
                    collect_names(fval)
            elif isinstance(expr, EnumInit):
                for arg in expr.arguments:
                    collect_names(arg.value)
            elif isinstance(expr, ForceUnwrap):
                collect_names(expr.expr)
            elif isinstance(expr, NilCoalesce):
                collect_names(expr.expr)
                collect_names(expr.default)
            elif isinstance(expr, OptionalChain):
                collect_names(expr.expr)
            elif isinstance(expr, ClosureExpr):
                # Recurse so a name the nested closure pulls from an enclosing
                # frame is captured here too; its own params/locals won't resolve
                # in outer_scope and are filtered out below.
                collect_block(expr.body)
            else:
                # Everything the cases above do not name. A hand-written walker
                # over an open set of node kinds silently misses the ones nobody
                # thought of, and a MISS here is not a wrong answer but a
                # codegen failure: `{ x in "n={n}" }` never captured `n` (no
                # `StringInterpolation` case) and died with "Undefined variable:
                # n". So the tail is a STRUCTURAL walk, which cannot be
                # incomplete. The cases above stay because each says something
                # the structure does not — a bare name IS a use, a `move`'s
                # subject is a plain string, a call's callee may be a captured
                # closure binding, and a nested closure's parameters are not
                # uses at all.
                collect_structural(expr)

        def collect_structural(node):
            """Walk NODE'S CHILDREN. Never re-dispatches `node` itself, which is
            what keeps the mutual recursion with `collect_names` finite."""
            if node is None or isinstance(node, (SawType, str)):
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    collect_child(item)
                return
            if isinstance(node, Block):
                collect_block(node)
                return
            if not isinstance(node, (ASTNode, Argument, MatchArm)):
                return
            for f in structural_fields(node):
                collect_child(getattr(node, f.name, None))

        def collect_child(value):
            if isinstance(value, Expression):
                collect_names(value)
            else:
                collect_structural(value)

        def collect_block(block):
            if block is None:
                return
            for stmt in block.statements:
                if isinstance(stmt, ExpressionStatement):
                    collect_names(stmt.expression)
                elif isinstance(stmt, LetStatement):
                    collect_names(stmt.value)
                elif isinstance(stmt, AssignStatement):
                    collect_names(stmt.value)
                    collect_names(stmt.target)
                elif isinstance(stmt, CompoundAssignStatement):
                    collect_names(stmt.value)
                    collect_names(stmt.target)
                elif isinstance(stmt, ReturnStatement):
                    if stmt.value:
                        collect_names(stmt.value)
                elif isinstance(stmt, GuardLetStatement):
                    collect_names(stmt.optional_expr)
                    collect_block(stmt.else_branch)
                elif isinstance(stmt, BreakStatement):
                    if stmt.value:
                        collect_names(stmt.value)
                elif isinstance(stmt, (WhileExpr, ForLoop)):
                    collect_names(stmt)
                else:
                    # Any other statement — a bare `if`/`match`, a `lend`, a
                    # `try` — through the same structural tail.
                    collect_structural(stmt)
            if block.final_expr:
                collect_names(block.final_expr)

        collect_block(body)
        captures = []
        for name in used_names:
            if outer_scope.lookup(name):
                captures.append(name)
        return captures

    # ===== Try Expression Checking =====

    def _check_try_expr(self, expr: TryExpr) -> Optional[SawType]:
        """Check a try expression: try expr, try? expr, or try! expr.

        - try expr: Unwraps Ok, propagates Err (function must return Result<_, E>)
        - try? expr: Converts Result<T, E> to T? (returns None on Err)
        - try! expr: Unwraps Ok, panics on Err (like force unwrap)
        """
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        # Must be a Result<T, E>
        if not inner_type.is_result():
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try` requires a Result type, got `{inner_type}`",
                expr.line, expr.column
            )
            return None

        # Record the CONCRETE Result type for codegen. A generic call's declared
        # return type (e.g. `Result<T, E>`) arrives as a STRUCT-kind
        # `Result<Int, Int>`; resolve it to its ENUM form so codegen can select
        # the right monomorphized instantiation by NAME. Without this, the try
        # codegen falls back to matching by LLVM layout, which is ambiguous:
        # `Result<Int, Int>` and `Result<String, E>` share the identical
        # `{ i32, [8 x i8] }` layout, so the wrong Ok/Err payload type would be
        # used (extracting an Int as a String pointer -> crash). Mirrors the
        # `match` path's `matched_enum_type` annotation (brief 36, L7).
        expr.result_enum_type = self._resolve_type(inner_type)

        ok_type = inner_type.unwrap_result_ok()
        err_type = inner_type.unwrap_result_err()

        if expr.variant == "optional":
            # try? returns T?
            return SawType(TypeKind.OPTIONAL, inner_type=ok_type)

        elif expr.variant == "force":
            # try! returns T (panics on Err)
            return ok_type

        else:  # "propagate"
            # If there's an inline catch block, check it
            if expr.catch_block:
                return self._check_try_with_catch(expr, ok_type, err_type)

            # Otherwise, try expr propagates - function must return Result<_, E>
            self._validate_error_propagation(err_type, expr.line, expr.column, expr)
            return ok_type

    def _validate_error_propagation(self, err_type: SawType, line: int, column: int, expr=None):
        """Validate that error can be propagated from current function or to enclosing catch."""
        # If we're inside a try-catch block, errors go to the catch block
        if self.in_try_catch_block:
            # Track the error type for the enclosing try-catch
            if hasattr(self, '_try_catch_error_types') and self._try_catch_error_types is not None:
                self._try_catch_error_types.append(err_type)
            return  # OK - error will be caught by enclosing try-catch

        # Get expected return type from current function/method
        expected_return = None
        if self.current_function:
            expected_return = self.current_function.return_type
        elif self.current_method:
            expected_return = self.current_method.return_type

        if expected_return is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`try` can only propagate errors from functions/methods",
                line, column
            )
            return

        if not expected_return.is_result():
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`try` cannot propagate errors from a function returning `{expected_return}` (must return Result)",
                line, column,
                hint="use `try?` to convert to optional, or `try!` to force unwrap, or add a `catch` block"
            )
            return

        expected_err = expected_return.unwrap_result_err()
        if self._types_compatible(err_type, expected_err):
            return  # passthrough (includes an already-erased box == box)
        # Erased Result (design 56): the function returns `Result<_, Box<any
        # Trait>>` and this callee's error is a concrete conformer — re-box it at
        # the propagation edge. Stamp the erasure for codegen.
        trait = self.namespace._erased_trait_of(expected_err)
        if trait is not None and self._can_erase_to(err_type, trait):
            if expr is not None:
                expr.erase_propagate = {
                    'trait': trait,
                    'concrete': err_type,
                    'allocator': SawType(TypeKind.STRUCT, struct_name="GlobalAllocator"),
                }
            return
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"cannot propagate error of type `{err_type}` from function returning `Result<_, {expected_err}>`",
            line, column
        )

    def _check_try_with_catch(self, expr: TryExpr, ok_type: SawType, err_type: SawType) -> Optional[SawType]:
        """Check try expression with inline catch block."""
        from .core import VariableInfo, Scope

        # Create scope for catch block with 'error' binding
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add implicit 'error' variable with the error type
        self.current_scope.define(
            "error",
            VariableInfo(
                type=err_type,
                mutable=False,
                line=expr.catch_block.line,
                column=expr.catch_block.column
            )
        )

        # Check catch block
        catch_type = self._check_block(expr.catch_block)
        self.current_scope = old_scope

        # Types must be compatible (catch must return same type as ok_type)
        if catch_type and not self._types_compatible(catch_type, ok_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"catch block returns `{catch_type}` but try expression expects `{ok_type}`",
                expr.catch_block.line, expr.catch_block.column
            )

        return ok_type

    def _check_try_catch_expr(self, expr: TryCatchExpr) -> Optional[SawType]:
        """Check a try-catch block expression: try { ... } catch { ... }"""
        from .core import VariableInfo, Scope

        # Set flag so try expressions know they're inside a try-catch
        old_in_try_catch = self.in_try_catch_block
        self.in_try_catch_block = True

        # Track error types from try expressions in this block
        old_try_catch_error_types = getattr(self, '_try_catch_error_types', None)
        self._try_catch_error_types = []

        # Check try block
        try_type = self._check_block(expr.try_block)

        # Collect unique error types
        error_types = self._try_catch_error_types
        unique_error_types = []
        for err_type in error_types:
            # Check if we already have this type
            is_dup = False
            for existing in unique_error_types:
                if self._types_compatible(err_type, existing):
                    is_dup = True
                    break
            if not is_dup:
                unique_error_types.append(err_type)

        # Determine the error type for the catch block
        if len(unique_error_types) == 0:
            error_type = SawType(TypeKind.STRUCT, struct_name="Error")  # Fallback
        elif len(unique_error_types) == 1:
            error_type = unique_error_types[0]  # Single error type
        else:
            # Multiple error types - create a union enum
            error_type = self._create_error_union_type(unique_error_types, expr)

        # Store the error type on the expression for codegen
        expr.error_type = error_type
        expr.error_types = unique_error_types

        # Restore tracking
        self._try_catch_error_types = old_try_catch_error_types

        # Restore flag before checking catch (catch is not inside try-catch context)
        self.in_try_catch_block = old_in_try_catch

        # Create scope for catch block with 'error' binding
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add implicit 'error' variable with the actual error type
        error_name = expr.error_binding or "error"
        self.current_scope.define(
            error_name,
            VariableInfo(
                type=error_type,
                mutable=False,
                line=expr.catch_block.line,
                column=expr.catch_block.column
            )
        )

        # Check catch block
        catch_type = self._check_block(expr.catch_block)
        self.current_scope = old_scope

        # Types must be compatible
        if try_type and catch_type and not self._types_compatible(try_type, catch_type):
            # Allow optional wrapping - if one returns T and other returns T?, wrap
            if try_type.is_optional() and not catch_type.is_optional():
                pass  # catch_type will be wrapped
            elif catch_type.is_optional() and not try_type.is_optional():
                pass  # try_type will be wrapped
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"try and catch blocks have incompatible types: `{try_type}` vs `{catch_type}`",
                    expr.line, expr.column
                )

        return try_type or catch_type

    def _create_error_union_type(self, error_types: List[SawType], expr) -> SawType:
        """Create a union enum type for multiple error types.

        Creates an enum like:
            enum _CatchError_123 {
                case ParseError(value: ParseError),
                case IoError(value: IoError)
            }

        This allows using match in the catch block to differentiate errors.
        """
        # Create unique name based on expression id
        # Named from the node's stable id, not its address (design 126 R2): this
        # name reaches codegen and the emitted type table, so deriving it from
        # `id()` made the compiler's output differ run to run for any program
        # using a multi-error `try`/`catch`.
        union_name = f"_CatchError_{expr.node_id}"

        # Build variants - each error type becomes a variant with 'value' field
        variants = {}
        variant_order = []
        for err_type in error_types:
            # Get variant name from the type
            if err_type.kind == TypeKind.STRUCT:
                variant_name = err_type.struct_name
            elif err_type.kind == TypeKind.ENUM:
                variant_name = err_type.enum_name
            else:
                variant_name = str(err_type)

            variants[variant_name] = [("value", err_type)]
            variant_order.append(variant_name)

        # Register the enum in namespace
        union_enum = EnumSymbol(
            variants=variants,
            variant_order=variant_order,
            type_params=[],
            visibility=Visibility.PRIVATE
        )
        self.namespace.register_enum(union_name, union_enum)

        return SawType(TypeKind.ENUM, enum_name=union_name, symbol=union_enum)

"""
Expression checking methods for the Saw type checker.

This module provides mixin methods for checking all expression types including
literals, operators, function calls, method calls, closures, and more.

Usage:
    class TypeChecker(ExpressionsMixin, ...):
        pass
"""

from typing import Optional, Dict, List
from ast_nodes import (
    Expression, IntLiteral, FloatLiteral, BoolLiteral, StringLiteral,
    StringInterpolation, Identifier, BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr,
    FunctionCall, IfExpr, IfLetExpr, TupleLiteral, TupleIndex,
    ArrayLiteral, ArrayIndex, MemberAccess, StructInit, NoneLiteral,
    ForceUnwrap, NilCoalesce, OptionalChain, MethodCall, SelfExpr,
    EnumInit, MatchExpr, WhileExpr, RangeExpr, ForLoop, ClosureExpr,
    TryExpr, TryCatchExpr,
    Block, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    CompoundAssignStatement, GuardLetStatement, BreakStatement,
    SawType, TypeKind,
    ResultOkWrap, ResultErrWrap, OptionalWrap
)
from errors import ErrorKind
from namespace import Visibility, EnumSymbol


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
        return result

    # ===== Expression Visitor Methods =====

    def visit_IntLiteral(self, expr: IntLiteral) -> Optional[SawType]:
        return SawType(TypeKind.INT)

    def visit_FloatLiteral(self, expr: FloatLiteral) -> Optional[SawType]:
        return SawType(TypeKind.FLOAT)

    def visit_BoolLiteral(self, expr: BoolLiteral) -> Optional[SawType]:
        return SawType(TypeKind.BOOL)

    def visit_StringLiteral(self, expr: StringLiteral) -> Optional[SawType]:
        return SawType(TypeKind.STRING)

    def visit_StringInterpolation(self, expr: StringInterpolation) -> Optional[SawType]:
        """Type check string interpolation expressions."""
        allowed_kinds = {
            TypeKind.INT, TypeKind.UINT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        for sub_expr in expr.expressions:
            expr_type = self._check_expression(sub_expr)
            if expr_type is None:
                return None
            if expr_type.kind not in allowed_kinds:
                self.error(f"Cannot interpolate type '{expr_type}' in string; only primitive types are allowed", sub_expr)
                return None
        return SawType(TypeKind.STRING)

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
            self._error(
                ErrorKind.CANNOT_COPY,
                self._partial_move_message(expr.path),
                expr.line, expr.column,
                hint="move the whole value (`move " + expr.variable + "`) or "
                     "restructure so the piece is its own binding"
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

        # A `&var` reference is only meaningful as a call argument (design 34):
        # references cannot be stored, returned, or bound to a variable. The
        # parser marks argument-position references; a `&var` anywhere else is
        # rejected here.
        if expr.mutable and not expr.in_argument_position:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "`&var` is only allowed as a call argument",
                expr.line, expr.column,
                hint="a mutable reference cannot be stored or bound; pass it "
                     "directly to a `&var` parameter"
            )
            return None

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
                if var_info and not var_info.mutable:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot take mutable reference to immutable variable `{expr.expr.name}`",
                        expr.line, expr.column,
                        hint="declare with `var` to make it mutable"
                    )
                    return None
            elif isinstance(expr.expr, SelfExpr):
                # In a method, check if self is mutable
                self_info = self.current_scope.lookup("self")
                if self_info and not self_info.mutable:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "cannot take mutable reference to immutable `self`",
                        expr.line, expr.column,
                        hint="use `&var self` in method signature to make self mutable"
                    )
                    return None

        # Return reference type
        return SawType(TypeKind.REFERENCE, inner_type=inner_type, reference_mutable=expr.mutable)

    def _is_lvalue(self, expr: Expression) -> bool:
        """Check if an expression is an lvalue (can have its address taken)."""
        return isinstance(expr, (Identifier, MemberAccess, ArrayIndex, SelfExpr))

    def _check_cast_expr(self, expr: CastExpr) -> Optional[SawType]:
        """Check a type cast expression: expr as Type"""
        from_type = self._check_expression(expr.expr)
        if from_type is None:
            return None
        to_type = self._resolve_type(expr.target_type)
        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        if from_type.kind in int_kinds and to_type.kind in int_kinds:
            return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.POINTER:
            return to_type
        if from_type.kind == TypeKind.STRING and to_type.kind == TypeKind.POINTER:
            if to_type.inner_type and to_type.inner_type.kind == TypeKind.INT8:
                return to_type
        if from_type.kind == TypeKind.POINTER and to_type.kind == TypeKind.STRING:
            if from_type.inner_type and from_type.inner_type.kind == TypeKind.INT8:
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
                    return left_type
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"pointer arithmetic requires integer offset, got `{right_type}`",
                        expr.line, expr.column
                    )
                    return None
            elif left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
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
            if left_type.kind == TypeKind.ENUM or right_type.kind == TypeKind.ENUM:
                if expr.op in ['<', '>', '<=', '>=']:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"enum types do not support ordering operators (`{expr.op}`), only `==` and `!=`",
                        expr.line, expr.column
                    )
                    return None
            if not self._types_compatible(left_type, right_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare `{left_type}` with `{right_type}`",
                    expr.line, expr.column
                )
                return SawType(TypeKind.BOOL)
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
            return SawType(TypeKind.BOOL)
        return None

    def _check_unary_op(self, expr: UnaryOp) -> Optional[SawType]:
        """Check a unary operation."""
        operand_type = self._check_expression(expr.operand)
        if operand_type is None:
            return None
        underlying = self._get_underlying_type(operand_type)
        if expr.op == '-':
            if underlying.kind in [TypeKind.INT, TypeKind.FLOAT]:
                return operand_type
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
        return None

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

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call."""
        if expr.name == "print":
            if len(expr.arguments) > 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`print` takes 0 or 1 arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
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
            return SawType(TypeKind.VOID)
        if expr.name == "__test_suspend":
            # design 22: compiler-known synthetic suspension point. Typechecked
            # as a suspension SOURCE (feeds the effect system); codegen lowers it
            # to a no-op so programs still run. Takes no arguments, returns Void.
            if len(expr.arguments) != 0:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__test_suspend` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            self._effect_direct_source("__test_suspend", expr.line)
            return SawType(TypeKind.VOID)
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
        if expr.name == "__deinit_in_place":
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
                    "`__deinit_in_place` is a compiler-internal intrinsic usable "
                    "only inside a `deinit` method body",
                    expr.line, expr.column
                )
                return SawType(TypeKind.VOID)
            if len(expr.arguments) != 1:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`__deinit_in_place` takes exactly one pointer argument, but "
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
                        f"`__deinit_in_place` expects an `UnsafePointer<T>` argument, "
                        f"got `{arg_type}`",
                        expr.line, expr.column
                    )
            return SawType(TypeKind.VOID)
        var_info = self.current_scope.lookup(expr.name)
        if var_info and var_info.type.kind == TypeKind.FUNCTION:
            func_type = var_info.type
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
                    arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
                self._check_value_transfer(arg.value, expected_type, "call argument",
                                           arg.value.line, arg.value.column)
            self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
            return return_type
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
                if hasattr(struct_init, 'resolved_init_params'):
                    expr.resolved_init_params = struct_init.resolved_init_params
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
        # design 22: record the call edge in the suspend graph (blocking externs
        # are a direct suspension source; other calls are edges to their node).
        self._effect_call_function(func_info, expr.name, expr.line)
        if func_info.type_params:
            if not expr.type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic function `{expr.name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.name}<Type>(...)`"
                )
                return None
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
                    elif concrete_type_name:
                        conformances = self.namespace.get_conformances(concrete_type_name)
                        if bound not in conformances:
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
        if func_info.is_variadic:
            if len(expr.arguments) < len(param_types):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"function `{expr.name}` takes at least {len(param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
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
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                arg_type = self._check_expression(arg.value)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = func_info.param_names[i]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Variadic extra arguments have no declared parameter type to check
        # against, but must still flow through the chokepoint so codegen sees
        # their resolved_type annotations.
        for arg in expr.arguments[len(param_types):]:
            self._check_expression(arg.value)
            self._check_value_transfer(arg.value, None, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments], param_types,
                                     param_names=func_info.param_names)
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
        self.current_scope.define(
            expr.name,
            VariableInfo(inner_type, expr.mutable, expr.line, expr.column)
        )
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
        """Check a tuple literal."""
        element_types = []
        for element in expr.elements:
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            element_types.append(elem_type)
            self._check_value_transfer(element, elem_type, "tuple element",
                                       element.line, element.column)
        return SawType(TypeKind.TUPLE, element_types=element_types)

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
        """Check an array literal and infer its type."""
        if len(expr.elements) == 0:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "cannot infer type of empty array literal; use explicit type annotation",
                expr.line, expr.column
            )
            return None
        first_type = self._check_expression(expr.elements[0])
        if first_type is None:
            return None
        self._check_value_transfer(expr.elements[0], first_type, "array element",
                                   expr.elements[0].line, expr.elements[0].column)
        for i, element in enumerate(expr.elements[1:], start=1):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            if not self._types_compatible(elem_type, first_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element {i} has type `{elem_type}`, expected `{first_type}`",
                    element.line, element.column
                )
                return None
            self._check_value_transfer(element, first_type, "array element",
                                       element.line, element.column)
        return SawType(TypeKind.ARRAY, array_element_type=first_type, array_size=len(expr.elements))

    def _check_array_index(self, expr: ArrayIndex) -> Optional[SawType]:
        """Check array or tuple indexing with [index] syntax."""
        container_type = self._check_expression(expr.array_expr)
        if container_type is None:
            return None
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
            return container_type.inner_type
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into type `{container_type}`",
                expr.line, expr.column
            )
            return None

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
                        expr.resolved_struct_name = expr.member
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.STRUCT, struct_name=expr.member, symbol=symbol)
                    elif symbol.kind == SymbolKind.ENUM:
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.ENUM, enum_name=expr.member, symbol=symbol)
                    elif symbol.kind == SymbolKind.FUNCTION:
                        expr.resolved_function_name = expr.member
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
                            result = SawType(TypeKind.ENUM, enum_name=obj_type.enum_name, type_args=type_args, symbol=enum_info)
                            # Preserve module resolution info for codegen
                            if hasattr(expr.object, 'resolved_module'):
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
            module_sym = self.namespace.modules.get(expr.object.name)
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
                if symbol.kind == SymbolKind.STRUCT:
                    expr.resolved_struct_name = expr.member
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.STRUCT, struct_name=expr.member, symbol=symbol)
                elif symbol.kind == SymbolKind.ENUM:
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.ENUM, enum_name=expr.member, symbol=symbol)
                elif symbol.kind == SymbolKind.FUNCTION:
                    expr.resolved_function_name = expr.member
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
                        return SawType(TypeKind.ENUM, enum_name=expr.object.name, type_args=type_args, symbol=enum_info)
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
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{obj_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        # Resolve the field type (e.g., convert STRUCT to ENUM if needed)
        return self._resolve_type(struct_info.fields[expr.member])

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
            return provided
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
            return filled
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

    def _check_struct_init(self, expr: StructInit) -> Optional[SawType]:
        """Check struct initialization with parameter-based resolution."""
        struct_info = self.get_struct_info(expr.struct_name)
        if struct_info is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None
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
        provided_params = {field_name for field_name, _ in expr.field_inits}
        field_names = set(struct_info.fields.keys())
        matches_fields = provided_params == field_names
        matching_inits = []
        # Check for init methods in both methods dict (legacy) and init_methods list (namespace)
        for method_name, method_info in struct_info.methods.items():
            if method_info.is_init:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
                    matching_inits.append(method_info)
        # Also check init_methods list (for StructSymbol from namespace)
        if hasattr(struct_info, 'init_methods'):
            for method_info in struct_info.init_methods:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
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
            expr.resolved_init_params = None
            for field_name, field_value in expr.field_inits:
                expected_type = struct_info.fields[field_name]
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                if expected_type.kind == TypeKind.OPTIONAL and isinstance(field_value, NoneLiteral):
                    field_value.resolved_type = expected_type
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
                self._check_value_transfer(field_value, expected_type, "struct field",
                                           field_value.line, field_value.column)
        else:
            method_info = matching_inits[0]
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
                expected_type = method_info.param_types[param_idx]
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._types_compatible(actual_type, expected_type):
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
                if arm.body and arm.body.final_expr:
                    self._propagate_optional_type(arm.body.final_expr, expected_type)
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
            return SawType(TypeKind.STRUCT, struct_name=name, symbol=struct_info)
        # Check if it's an enum
        enum_info = self.namespace.lookup_enum(name)
        if enum_info:
            return SawType(TypeKind.ENUM, enum_name=name, symbol=enum_info)
        # Fallback to STRUCT type
        return SawType(TypeKind.STRUCT, struct_name=name)

    def _lookup_method(self, struct_info, method_name: str, type_args: List[SawType] = None):
        """Look up a method, checking specialized extensions first."""
        # First, check if there's a specialized extension matching the type args
        if type_args and struct_info.specialized_methods:
            spec_key = self._make_specialization_key(type_args)
            if spec_key in struct_info.specialized_methods:
                specialized = struct_info.specialized_methods[spec_key]
                if method_name in specialized:
                    return specialized[method_name]

        # Fall back to generic methods
        if method_name in struct_info.methods:
            return struct_info.methods[method_name]

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

        # Anything else is not Copy.
        self._error(
            ErrorKind.CANNOT_COPY,
            f"type `{obj_type}` is not Copy; `.copy()` requires a trivially-copyable, "
            f"ImplicitCopy, or ExplicitCopy type",
            expr.line, expr.column
        )
        return True, None

    def _resolve_arc_forward(self, expr: MethodCall, payload_type: Optional[SawType]):
        """Resolve an `Arc<T>` payload-method forward (design 21b E2).

        Returns `(payload_method_info, payload_type_subst)` if `expr.method_name`
        is an immutable `&self` method on the payload struct `T`; the string
        `"rejected"` if it is a `&var self` method (reported here as an error);
        or `None` if there is no such method (the caller then falls through to
        the ordinary "no method on Arc" diagnostic).
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
                f"cannot call `&var self` method `{expr.method_name}` through `Arc` "
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
            if arg_type and not self._types_compatible(arg_type, expected_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments], param_types)
        return return_type

    def _check_method_call(self, expr: MethodCall) -> Optional[SawType]:
        """Check a method call, static method call, enum initialization, or module function call."""
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
            module_sym = self.namespace.modules.get(expr.object.name)
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
            struct_info = self.get_struct_info(expr.object.name)
            if struct_info:
                struct_name = expr.object.name
                if expr.method_name in struct_info.methods:
                    method_info = struct_info.methods[expr.method_name]
                    if method_info.is_static:
                        return self._check_static_method_call(expr, struct_name, struct_info, method_info)
        if isinstance(expr.object, Identifier) and self.get_enum_info(expr.object.name):
            enum_init = EnumInit(
                enum_name=expr.object.name,
                variant_name=expr.method_name,
                arguments=expr.arguments,
                type_args=expr.object.type_args,
                line=expr.line,
                column=expr.column
            )
            return self._check_enum_init(enum_init)
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None

        # `.copy()` — the umbrella Copy operation. Handles auto-Copy of trivial
        # types and `.copy()` through a `T: Copy`-family bound. Types that carry
        # a real copy() method (ImplicitCopy/ExplicitCopy) fall through to normal
        # method dispatch.
        if expr.method_name == "copy" and len(expr.arguments) == 0:
            handled, result = self._check_copy_call(expr, obj_type)
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

        if obj_type.kind == TypeKind.STRING:
            struct_name = "String"
            struct_info = self.get_struct_info(struct_name)
        elif obj_type.kind == TypeKind.STRUCT:
            struct_name = obj_type.struct_name
            struct_info = self.get_struct_info(struct_name, from_type=obj_type)
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
            # Collect available methods from both generic and specialized
            available = list(struct_info.methods.keys())
            if obj_type.type_args:
                spec_key = self._make_specialization_key(obj_type.type_args)
                if spec_key in struct_info.specialized_methods:
                    available.extend(struct_info.specialized_methods[spec_key].keys())
            self._error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{struct_name}` has no method `{expr.method_name}`",
                expr.line, expr.column,
                hint=f"available methods: {', '.join(sorted(set(available)))}" if available else "no methods defined"
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
        # Method-level generic type parameters (brief 36): fold the explicit
        # call-site type arguments (`v.map<Int>(...)`) into the substitution map
        # alongside the struct's own args, so param/return types mentioning the
        # method's own params (`(T) -> U`, `-> Vector<U>`) resolve concretely.
        # Inference is out of scope: a generic method REQUIRES explicit type
        # args, and a non-generic method REJECTS them.
        method_type_params = method_info.type_params or []
        provided_type_args = expr.type_args or []
        if method_type_params:
            if not provided_type_args:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic method `{expr.method_name}` requires explicit type "
                    f"argument(s) (e.g. `{expr.method_name}<...>`); type inference "
                    f"is not yet supported",
                    expr.line, expr.column
                )
            elif len(provided_type_args) != len(method_type_params):
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{expr.method_name}` expects {len(method_type_params)} "
                    f"type argument(s), got {len(provided_type_args)}",
                    expr.line, expr.column
                )
            else:
                for tp, ta in zip(method_type_params, provided_type_args):
                    type_subst[tp.name] = self._resolve_type(ta)
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
            expected_type = method_info.param_types[i + param_offset]
            if type_subst:
                expected_type = expected_type.substitute(type_subst)
            # Closure arguments infer their parameter types from the expected
            # function type and may carry reference params (e.g. Mutex.lock).
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type, as_call_argument=True)
            else:
                arg_type = self._check_expression(arg.value)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = method_info.param_names[i + param_offset]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        # Exclusivity: the receiver of a `var self` method is a mutable path;
        # its parameter types (excluding self) align with the arguments.
        self._check_call_exclusivity(
            [a.value for a in expr.arguments],
            method_info.param_types[param_offset:],
            receiver=expr.object if not method_info.is_init else None,
            receiver_mutable=method_info.self_mutable,
            param_names=method_info.param_names[param_offset:],
        )
        return_type = method_info.return_type
        if type_subst:
            return_type = return_type.substitute(type_subst)
        return return_type

    def _check_module_function_call(self, expr: MethodCall, func_info) -> Optional[SawType]:
        """Check a module function call: ModuleName.function(args)"""
        # design 24 item 3: record the suspend-graph edge for a module-qualified
        # call. In the whole-program (single-file) path the callee's node is
        # registered under its name and the edge connects; a cross-module callee
        # into a separately-checked module resolves to no node and is a
        # non-suspending leaf (design 22 §5), which is safe today.
        self._effect_call_function(func_info, expr.method_name, expr.line)
        if len(expr.arguments) != len(func_info.param_types):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"function `{expr.method_name}` takes {len(func_info.param_types)} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return func_info.return_type
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, func_info.param_types)):
            arg_type = self._check_expression(arg.value)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     func_info.param_types)
        return func_info.return_type

    def _check_module_struct_init(self, expr: MethodCall, struct_sym) -> Optional[SawType]:
        """Check a module-qualified struct initialization: ModuleName.StructName(args)

        Uses the struct symbol directly instead of looking up by name.
        """
        struct_name = expr.method_name
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
            return SawType(TypeKind.STRUCT, struct_name=struct_name, symbol=struct_sym)
        elif total_matches > 1:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=struct_name, symbol=struct_sym)

        if matches_fields:
            # Field initialization
            # design 27 item 3: record "field init, no custom init" so codegen
            # builds the struct memberwise rather than dispatching to an init.
            expr.resolved_init_params = None
            for field_name, field_value in field_inits:
                expected_type = struct_sym.fields[field_name]
                actual_type = self._check_init_field_value(field_value, expected_type)
                if actual_type and not self._types_compatible(actual_type, expected_type):
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
                if actual_type and not self._types_compatible(actual_type, expected_type):
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

        return SawType(TypeKind.STRUCT, struct_name=struct_name, symbol=struct_sym)

    def _check_static_method_call(self, expr: MethodCall, struct_name: str,
                                   struct_info, method_info) -> Optional[SawType]:
        """Check a static method call: StructName.method(args)"""
        # design 24 item 3: record the suspend-graph edge to the static method.
        self._effect_call_method(
            method_info, f"`{struct_name}.{expr.method_name}`", expr.line)
        required_count = sum(1 for dv in method_info.default_values if dv is None)
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
        for i, arg in enumerate(expr.arguments):
            arg_type = self._check_expression(arg.value)
            expected_type = method_info.param_types[i]
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = method_info.param_names[i]
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
            self._check_value_transfer(arg.value, expected_type, "call argument",
                                       arg.value.line, arg.value.column)
        self._check_call_exclusivity([a.value for a in expr.arguments],
                                     method_info.param_types,
                                     param_names=method_info.param_names)
        # For a static factory on a GENERIC struct called with explicit type
        # args (`Vector<Int>.try_with_capacity(...)`), substitute the struct's
        # type params into the return type so the caller sees the concrete
        # instantiation (`Result<Vector<Int>, AllocError>`). Without this the
        # return type keeps the generic `T`, and a `match` on the result can't
        # resolve its monomorphized enum. Positional map: the struct's type
        # params line up with the type args on the call's object.
        ret = method_info.return_type
        obj_type_args = getattr(expr.object, 'type_args', None)
        struct_type_params = getattr(struct_info, 'type_params', None)
        if ret is not None and obj_type_args and struct_type_params:
            # Default-fill the receiver's type args first (design 37), so
            # `Vector<Int>.try_with_capacity(...)` binds A=Global and the return
            # type resolves to `Result<Vector<Int, Global>, AllocError>` rather
            # than leaving the allocator parameter abstract (which would leave
            # the extracted vector unable to find `push`).
            resolved_args = [self._resolve_type(ta) for ta in obj_type_args]
            resolved_args = self._append_default_type_args(struct_name, resolved_args)
            type_map = {}
            for tp, ta in zip(struct_type_params, resolved_args):
                type_map[tp.name] = ta
            if type_map:
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
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{arg.name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
                self._check_value_transfer(arg.value, expected_type, "enum payload",
                                           arg.value.line, arg.value.column)
            else:
                if i >= len(expected_list):
                    continue
                param_name, expected_type = expected_list[i]
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{param_name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
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
        if not arm_types:
            return None
        result_type = arm_types[0]
        for arm_type in arm_types[1:]:
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
                        (ok_type and self._types_compatible(at, ok_type)) or
                        (err_type and self._types_compatible(at, err_type))
                        for at in arm_types
                    )
                    if types_for_result:
                        # Wrap arm bodies in ResultOkWrap/ResultErrWrap
                        for i, (arm, arm_type) in enumerate(zip(expr.arms, arm_types)):
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
        # A closure captures by value, so its body has its own function-local
        # move state (design 15); restore the enclosing state on exit.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}
        # design 22: analyze the closure body as its own suspend-graph node. If
        # its target type is a `sync` function type (e.g. `Mutex.lock`'s param),
        # the closure is a sync context checked transitively suspension-free.
        self._effect_enter_closure(expr, expected_type)

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
                    continue
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
        self.current_scope = outer_scope
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
        result_type = SawType(TypeKind.FUNCTION, param_types=param_types,
                              func_return_type=return_type)
        # Record the resolved signature so codegen lowers parameter/return types
        # (including reference params) accurately rather than guessing.
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
        """
        used_names = set()

        def collect_names(expr):
            if expr is None:
                return
            if isinstance(expr, Identifier):
                used_names.add(expr.name)
            elif isinstance(expr, BinaryOp):
                collect_names(expr.left)
                collect_names(expr.right)
            elif isinstance(expr, UnaryOp):
                collect_names(expr.operand)
            elif isinstance(expr, MoveExpr):
                used_names.add(expr.variable)
            elif isinstance(expr, ReferenceExpr):
                collect_names(expr.expr)
            elif isinstance(expr, CastExpr):
                collect_names(expr.expr)
            elif isinstance(expr, FunctionCall):
                # `f(x)` where `f` is an enclosing closure-typed binding is a
                # capture of `f` (the final `outer_scope.lookup` filter drops
                # top-level function names, which are not locals).
                used_names.add(expr.name)
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
            self._validate_error_propagation(err_type, expr.line, expr.column)
            return ok_type

    def _validate_error_propagation(self, err_type: SawType, line: int, column: int):
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
        if not self._types_compatible(err_type, expected_err):
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
        union_name = f"_CatchError_{id(expr)}"

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

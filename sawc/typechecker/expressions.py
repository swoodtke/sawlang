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
    StringInterpolation, Identifier, BinaryOp, UnaryOp, MoveExpr, CastExpr,
    FunctionCall, IfExpr, IfLetExpr, TupleLiteral, TupleIndex,
    ArrayLiteral, ArrayIndex, MemberAccess, StructInit, NoneLiteral,
    ForceUnwrap, NilCoalesce, OptionalChain, MethodCall, SelfExpr,
    EnumInit, MatchExpr, WhileExpr, RangeExpr, ForLoop, ClosureExpr,
    Block, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    SawType, TypeKind
)
from errors import ErrorKind


class ExpressionsMixin:
    """Mixin providing expression checking methods for TypeChecker."""

    def _check_expression(self, expr: Expression) -> Optional[SawType]:
        """Check an expression and return its type."""
        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            return None
        return visitor(expr)

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
            TypeKind.INT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
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

    def _check_identifier(self, expr: Identifier) -> Optional[SawType]:
        """Check an identifier reference."""
        if expr.name in self.moved_variables:
            self.reporter.error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.name}`",
                expr.line, expr.column,
                hint="value was moved and can no longer be used"
            )
            return None
        var_info = self.current_scope.lookup(expr.name)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.name}`",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_move_expr(self, expr: MoveExpr) -> Optional[SawType]:
        """Check a move expression."""
        if expr.variable in self.moved_variables:
            self.reporter.error(
                ErrorKind.USE_AFTER_MOVE,
                f"use of moved variable `{expr.variable}`",
                expr.line, expr.column,
                hint="value was already moved and can no longer be used"
            )
            return None
        var_info = self.current_scope.lookup(expr.variable)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.variable}`",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_cast_expr(self, expr: CastExpr) -> Optional[SawType]:
        """Check a type cast expression: expr as Type"""
        from_type = self._check_expression(expr.expr)
        if from_type is None:
            return None
        to_type = self._resolve_type(expr.target_type)
        int_kinds = {
            TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
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
        self.reporter.error(
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
            TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }
        if expr.op in ['+', '-', '*', '/']:
            if expr.op in ['+', '-'] and left_underlying.kind == TypeKind.POINTER:
                if right_underlying.kind in int_kinds:
                    return left_type
                else:
                    self.reporter.error(
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
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` cannot be applied to `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == '%':
            if left_underlying.kind in int_kinds and right_underlying.kind in int_kinds:
                return left_type
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `%` requires integer operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['&&', '||']:
            if left_underlying.kind == TypeKind.BOOL and right_underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` requires Bool operands, got `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op in ['==', '!=', '<', '>', '<=', '>=']:
            if left_type.kind == TypeKind.ENUM or right_type.kind == TypeKind.ENUM:
                if expr.op in ['<', '>', '<=', '>=']:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"enum types do not support ordering operators (`{expr.op}`), only `==` and `!=`",
                        expr.line, expr.column
                    )
                    return None
            if not self._types_compatible(left_type, right_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot compare `{left_type}` with `{right_type}`",
                    expr.line, expr.column
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
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        elif expr.op == 'not':
            if underlying.kind == TypeKind.BOOL:
                return SawType(TypeKind.BOOL)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `not` requires Bool operand, got `{operand_type}`",
                    expr.line, expr.column
                )
                return None
        return None

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call."""
        from .core import FunctionInfo
        if expr.name == "print":
            if len(expr.arguments) > 1:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`print` takes 0 or 1 arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            for arg in expr.arguments:
                self._check_expression(arg.value)
            return SawType(TypeKind.VOID)
        if expr.name == "sizeof":
            if len(expr.arguments) != 0:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`sizeof` takes no arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            if not expr.type_args or len(expr.type_args) != 1:
                self.reporter.error(
                    ErrorKind.TYPE_ERROR,
                    "`sizeof` requires exactly one type argument: sizeof<T>()",
                    expr.line, expr.column
                )
                return None
            resolved_type = self._resolve_type(expr.type_args[0])
            if resolved_type is None:
                return None
            return SawType(TypeKind.INT)
        var_info = self.current_scope.lookup(expr.name)
        if var_info and var_info.type.kind == TypeKind.FUNCTION:
            func_type = var_info.type
            param_types = func_type.param_types or []
            return_type = func_type.func_return_type or SawType(TypeKind.VOID)
            if len(expr.arguments) != len(param_types):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"closure takes {len(param_types)} argument(s), but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type
            for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
                if isinstance(arg.value, ClosureExpr):
                    arg_type = self._check_closure(arg.value, expected_type)
                else:
                    arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
            return return_type
        func_info = self.functions.get(expr.name)
        if func_info and not self.namespace.is_accessible(expr.name):
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"function `{expr.name}` is not directly accessible",
                expr.line, expr.column,
                hint=f"use qualified access (e.g., `module_name.{expr.name}`) or import it directly"
            )
            return None
        if not func_info:
            if expr.name in self.structs and self.namespace.is_accessible(expr.name):
                from ast_nodes import StructInit, Argument
                field_inits = []
                for arg in expr.arguments:
                    if arg.name:
                        field_inits.append((arg.name, arg.value))
                    else:
                        self.reporter.error(
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
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"undefined function `{expr.name}`",
                expr.line, expr.column
            )
            return None
        if func_info.type_params:
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic function `{expr.name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.name}<Type>(...)`"
                )
                return None
            if len(expr.type_args) != len(func_info.type_params):
                self.reporter.error(
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
                    if bound not in self.interfaces:
                        self.reporter.error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown interface `{bound}` in type parameter bound",
                            expr.line, expr.column
                        )
                        continue
                    concrete_type_name = None
                    if resolved_arg.kind == TypeKind.STRUCT:
                        concrete_type_name = resolved_arg.struct_name
                    elif resolved_arg.kind == TypeKind.ENUM:
                        concrete_type_name = resolved_arg.enum_name
                    if concrete_type_name:
                        conformances = self.type_conformances.get(concrete_type_name, [])
                        if bound not in conformances:
                            self.reporter.error(
                                ErrorKind.TYPE_MISMATCH,
                                f"type `{resolved_arg}` does not implement interface `{bound}`",
                                expr.line, expr.column,
                                hint=f"add `extension {concrete_type_name}: {bound} {{ ... }}`"
                            )
                        else:
                            type_assigns = self.type_assignments.get((concrete_type_name, bound), {})
                            for assoc_name, assoc_type in type_assigns.items():
                                type_map[assoc_name] = assoc_type
            param_types = [t.substitute(type_map) for t in func_info.param_types]
            return_type = func_info.return_type.substitute(type_map)
        else:
            if expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{expr.name}` is not generic but was called with type arguments",
                    expr.line, expr.column
                )
            param_types = func_info.param_types
            return_type = func_info.return_type
        if func_info.is_variadic:
            if len(expr.arguments) < len(param_types):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"function `{expr.name}` takes at least {len(param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type
        else:
            if len(expr.arguments) != len(param_types):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"function `{expr.name}` takes {len(param_types)} argument(s), "
                    f"but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
                return return_type
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, param_types)):
            if isinstance(arg.value, ClosureExpr):
                arg_type = self._check_closure(arg.value, expected_type)
            else:
                arg_type = self._check_expression(arg.value)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = func_info.param_names[i]
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
        return return_type

    def _check_if_expr(self, expr: IfExpr) -> Optional[SawType]:
        """Check an if expression."""
        cond_type = self._check_expression(expr.condition)
        if cond_type and cond_type.kind != TypeKind.BOOL:
            if cond_type.kind != TypeKind.INT:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"condition must be `Bool`, got `{cond_type}`",
                    expr.line, expr.column
                )
        then_type = self._check_block(expr.then_branch)
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if` and `else` branches have incompatible types: `{then_type}` vs `{else_type}`",
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

    def _check_if_let_expr(self, expr: IfLetExpr) -> Optional[SawType]:
        """Check an if let/var expression for optional binding."""
        from .core import VariableInfo, Scope
        optional_type = self._check_expression(expr.optional_expr)
        if optional_type is None:
            return None
        if optional_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"'if let' requires an optional type, got `{optional_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = optional_type.inner_type
        if inner_type is None:
            self.reporter.error(
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
        then_type = self._check_block(expr.then_branch)
        self.current_scope = old_scope
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
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
        return SawType(TypeKind.TUPLE, element_types=element_types)

    def _check_tuple_index(self, expr: TupleIndex) -> Optional[SawType]:
        """Check tuple indexing."""
        tuple_type = self._check_expression(expr.tuple_expr)
        if tuple_type is None:
            return None
        if tuple_type.kind != TypeKind.TUPLE:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into non-tuple type `{tuple_type}`",
                expr.line, expr.column
            )
            return None
        if tuple_type.element_types is None:
            return None
        if expr.index < 0 or expr.index >= len(tuple_type.element_types):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"tuple index {expr.index} out of range for tuple with {len(tuple_type.element_types)} elements",
                expr.line, expr.column
            )
            return None
        return tuple_type.element_types[expr.index]

    def _check_array_literal(self, expr: ArrayLiteral) -> Optional[SawType]:
        """Check an array literal and infer its type."""
        if len(expr.elements) == 0:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                "cannot infer type of empty array literal; use explicit type annotation",
                expr.line, expr.column
            )
            return None
        first_type = self._check_expression(expr.elements[0])
        if first_type is None:
            return None
        for i, element in enumerate(expr.elements[1:], start=1):
            elem_type = self._check_expression(element)
            if elem_type is None:
                return None
            if not self._types_compatible(elem_type, first_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"array element {i} has type `{elem_type}`, expected `{first_type}`",
                    element.line, element.column
                )
                return None
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
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"index must be Int, got `{index_type}`",
                expr.index.line, expr.index.column
            )
            return None
        if container_type.kind == TypeKind.ARRAY:
            return container_type.array_element_type
        elif container_type.kind == TypeKind.TUPLE:
            if not isinstance(expr.index, IntLiteral):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    "tuple index must be a compile-time constant",
                    expr.index.line, expr.index.column
                )
                return None
            index = expr.index.value
            if container_type.element_types is None:
                return None
            if index < 0 or index >= len(container_type.element_types):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple index {index} out of range for tuple with {len(container_type.element_types)} elements",
                    expr.line, expr.column
                )
                return None
            return container_type.element_types[index]
        elif container_type.kind == TypeKind.POINTER:
            return container_type.inner_type
        else:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot index into type `{container_type}`",
                expr.line, expr.column
            )
            return None

    def _check_member_access(self, expr: MemberAccess) -> Optional[SawType]:
        """Check member access for struct fields, enum variants, or module symbols."""
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
            if obj_type and obj_type.kind == TypeKind.MODULE:
                inner_module_sym = getattr(expr.object, 'resolved_module_symbol', None)
                if inner_module_sym and inner_module_sym.namespace:
                    from namespace import SymbolKind
                    symbol = inner_module_sym.namespace.resolve(
                        expr.member, check_visibility=True, accessor_module=()
                    )
                    if symbol is None:
                        self.reporter.error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"module `{obj_type.module_name}` has no symbol `{expr.member}`",
                            expr.line, expr.column
                        )
                        return None
                    if symbol.kind == SymbolKind.STRUCT:
                        expr.resolved_struct_name = expr.member
                        expr.resolved_module = obj_type.module_name
                        return SawType(TypeKind.STRUCT, struct_name=expr.member)
                    elif symbol.kind == SymbolKind.ENUM:
                        return SawType(TypeKind.ENUM, enum_name=expr.member)
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
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot use `{expr.member}` as an expression",
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
                    self.reporter.error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"module `{expr.object.name}` has no symbol `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None
                if symbol.kind == SymbolKind.STRUCT:
                    expr.resolved_struct_name = expr.member
                    expr.resolved_module = expr.object.name
                    return SawType(TypeKind.STRUCT, struct_name=expr.member)
                elif symbol.kind == SymbolKind.ENUM:
                    return SawType(TypeKind.ENUM, enum_name=expr.member)
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
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot use `{expr.member}` as an expression",
                        expr.line, expr.column
                    )
                    return None
            if expr.object.name in self.enums:
                enum_info = self.enums[expr.object.name]
                type_args = expr.object.type_args
                if enum_info.type_params:
                    if not type_args:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"generic enum `{expr.object.name}` requires type arguments",
                            expr.line, expr.column,
                            hint=f"use `{expr.object.name}<...>.{expr.member}`"
                        )
                    elif len(type_args) != len(enum_info.type_params):
                        self.reporter.error(
                            ErrorKind.WRONG_ARGUMENT_COUNT,
                            f"expected {len(enum_info.type_params)} type argument(s), got {len(type_args)}",
                            expr.line, expr.column
                        )
                if expr.member in enum_info.variants:
                    variant_params = enum_info.variants[expr.member]
                    if len(variant_params) == 0:
                        return SawType(TypeKind.ENUM, enum_name=expr.object.name, type_args=type_args)
                    else:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"variant `{expr.member}` has associated values and must be called like `{expr.object.name}.{expr.member}(...)`",
                            expr.line, expr.column
                        )
                        return None
                else:
                    self.reporter.error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"enum `{expr.object.name}` has no variant `{expr.member}`",
                        expr.line, expr.column
                    )
                    return None
        obj_type = self._check_expression(expr.object)
        if obj_type is None:
            return None
        if obj_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if obj_type.struct_name is None:
            return None
        struct_info = self.structs.get(obj_type.struct_name)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{obj_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        return struct_info.fields[expr.member]

    def _check_struct_init(self, expr: StructInit) -> Optional[SawType]:
        """Check struct initialization with parameter-based resolution."""
        struct_info = self.structs.get(expr.struct_name)
        if struct_info is None:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None
        type_mapping: Dict[str, SawType] = {}
        if struct_info.type_params:
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic struct `{expr.struct_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.struct_name}<...>(...)`"
                )
            elif len(expr.type_args) != len(struct_info.type_params):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(struct_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                for type_param, type_arg in zip(struct_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg
        provided_params = {field_name for field_name, _ in expr.field_inits}
        field_names = set(struct_info.fields.keys())
        matches_fields = provided_params == field_names
        matching_inits = []
        for method_name, method_info in struct_info.methods.items():
            if method_info.is_init:
                init_param_names = set(method_info.param_names)
                if provided_params == init_param_names:
                    matching_inits.append(method_info)
        total_matches = (1 if matches_fields else 0) + len(matching_inits)
        if total_matches == 0:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"no matching initializer for `{expr.struct_name}` with parameters: {', '.join(sorted(provided_params))}",
                expr.line, expr.column,
                hint=f"field init expects: {', '.join(sorted(field_names))}" +
                     (f"; available init methods: {[m.param_names for m in struct_info.methods.values() if m.is_init]}" if any(m.is_init for m in struct_info.methods.values()) else "")
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)
        elif total_matches > 1:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"ambiguous initializer for `{expr.struct_name}` - matches both field initialization and custom init",
                expr.line, expr.column,
                hint="use different parameter names in init method to disambiguate"
            )
            return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)
        if matches_fields:
            expr.resolved_init_params = None
            for field_name, field_value in expr.field_inits:
                expected_type = struct_info.fields[field_name]
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_expression(field_value)
                if expected_type.kind == TypeKind.OPTIONAL and isinstance(field_value, NoneLiteral):
                    field_value.resolved_type = expected_type
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
        else:
            method_info = matching_inits[0]
            expr.resolved_init_params = method_info.param_names
            for field_name, field_value in expr.field_inits:
                param_idx = method_info.param_names.index(field_name)
                expected_type = method_info.param_types[param_idx]
                if type_mapping:
                    expected_type = expected_type.substitute(type_mapping)
                actual_type = self._check_expression(field_value)
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"parameter `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )
        return SawType(TypeKind.STRUCT, struct_name=expr.struct_name, type_args=expr.type_args)

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
        if inner_type.kind == TypeKind.STRUCT and inner_type.struct_name in self.type_aliases:
            underlying = self._get_underlying_type(inner_type)
            if underlying.kind == TypeKind.OPTIONAL:
                return underlying.inner_type
        if inner_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
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
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"left side of `??` must be optional, got `{opt_type}`",
                expr.line, expr.column
            )
            return opt_type
        if opt_type.inner_type and not self._types_compatible(opt_type.inner_type, default_type):
            self.reporter.error(
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
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot use optional chaining on non-optional type `{opt_type}`",
                expr.line, expr.column
            )
            return None
        inner_type = opt_type.inner_type
        if inner_type is None:
            return None
        if inner_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{inner_type}`",
                expr.line, expr.column
            )
            return None
        struct_info = self.structs.get(inner_type.struct_name)
        if struct_info is None:
            return None
        if expr.member not in struct_info.fields:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{inner_type.struct_name}` has no field `{expr.member}`",
                expr.line, expr.column,
                hint=f"available fields: {', '.join(struct_info.field_order)}"
            )
            return None
        field_type = struct_info.fields[expr.member]
        return SawType(TypeKind.OPTIONAL, inner_type=field_type)

    def _check_method_call(self, expr: MethodCall) -> Optional[SawType]:
        """Check a method call, static method call, enum initialization, or module function call."""
        from .core import FunctionInfo, MethodInfo
        if isinstance(expr.object, MemberAccess):
            obj_type = self._check_member_access(expr.object)
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
                        self.reporter.error(
                            ErrorKind.UNDEFINED_FUNCTION,
                            f"module `{obj_type.module_name}` has no function `{expr.method_name}`",
                            expr.line, expr.column
                        )
                        return None
                    if symbol.kind == SymbolKind.FUNCTION:
                        func_info = self.functions.get(expr.method_name)
                        if func_info:
                            return self._check_module_function_call(expr, func_info)
                        else:
                            self.reporter.error(
                                ErrorKind.UNDEFINED_FUNCTION,
                                f"function `{expr.method_name}` not found",
                                expr.line, expr.column
                            )
                            return None
                    elif symbol.kind == SymbolKind.STRUCT:
                        struct_init = StructInit(
                            struct_name=expr.method_name,
                            field_inits=[(arg.name, arg.value) for arg in expr.arguments if arg.name],
                            type_args=None,
                            line=expr.line,
                            column=expr.column
                        )
                        if all(arg.name is None for arg in expr.arguments):
                            struct_info = self.structs.get(expr.method_name)
                            if struct_info:
                                field_inits = []
                                for arg, field_name in zip(expr.arguments, struct_info.field_order):
                                    field_inits.append((field_name, arg.value))
                                struct_init.field_inits = field_inits
                        return self._check_struct_init(struct_init)
                    else:
                        self.reporter.error(
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
                    self.reporter.error(
                        ErrorKind.UNDEFINED_FUNCTION,
                        f"module `{expr.object.name}` has no function `{expr.method_name}`",
                        expr.line, expr.column
                    )
                    return None
                if symbol.kind == SymbolKind.FUNCTION:
                    func_info = self.functions.get(expr.method_name)
                    if func_info:
                        return self._check_module_function_call(expr, func_info)
                    else:
                        self.reporter.error(
                            ErrorKind.UNDEFINED_FUNCTION,
                            f"function `{expr.method_name}` not found",
                            expr.line, expr.column
                        )
                        return None
                elif symbol.kind == SymbolKind.STRUCT:
                    struct_init = StructInit(
                        struct_name=expr.method_name,
                        field_inits=[(arg.name, arg.value) for arg in expr.arguments if arg.name],
                        type_args=None,
                        line=expr.line,
                        column=expr.column
                    )
                    if all(arg.name is None for arg in expr.arguments):
                        struct_info = self.structs.get(expr.method_name)
                        if struct_info:
                            field_inits = []
                            for arg, field_name in zip(expr.arguments, struct_info.field_order):
                                field_inits.append((field_name, arg.value))
                            struct_init.field_inits = field_inits
                    return self._check_struct_init(struct_init)
                elif symbol.kind == SymbolKind.ENUM:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"use `{expr.object.name}.{expr.method_name}.Variant(...)` to create enum values",
                        expr.line, expr.column
                    )
                    return None
                else:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{expr.method_name}` is not callable",
                        expr.line, expr.column
                    )
                    return None
        if isinstance(expr.object, Identifier) and expr.object.name in self.structs:
            struct_name = expr.object.name
            struct_info = self.structs[struct_name]
            if expr.method_name in struct_info.methods:
                method_info = struct_info.methods[expr.method_name]
                if method_info.is_static:
                    return self._check_static_method_call(expr, struct_name, struct_info, method_info)
        if isinstance(expr.object, Identifier) and expr.object.name in self.enums:
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
        if obj_type.kind == TypeKind.STRING:
            struct_name = "String"
        elif obj_type.kind == TypeKind.STRUCT:
            struct_name = obj_type.struct_name
        else:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call method on non-struct type `{obj_type}`",
                expr.line, expr.column
            )
            return None
        if struct_name is None:
            return None
        struct_info = self.structs.get(struct_name)
        if struct_info is None:
            return None
        type_subst: Dict[str, SawType] = {}
        if struct_info.type_params and obj_type.type_args:
            for type_param, type_arg in zip(struct_info.type_params, obj_type.type_args):
                type_subst[type_param.name] = type_arg
        if expr.method_name not in struct_info.methods:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"type `{struct_name}` has no method `{expr.method_name}`",
                expr.line, expr.column,
                hint=f"available methods: {', '.join(struct_info.methods.keys())}" if struct_info.methods else "no methods defined"
            )
            return None
        method_info = struct_info.methods[expr.method_name]
        if expr.method_name == "deinit":
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot call `deinit` manually; it is called automatically when the value goes out of scope",
                expr.line, expr.column,
                hint="use a nested scope or `move` to transfer ownership if you need early cleanup"
            )
            return None
        param_offset = 1 if not method_info.is_init else 0
        total_params = len(method_info.param_types) - param_offset
        defaults_for_params = method_info.default_values[param_offset:] if method_info.default_values else []
        required_count = sum(1 for dv in defaults_for_params if dv is None) if defaults_for_params else total_params
        if len(expr.arguments) < required_count:
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"method `{expr.method_name}` takes at least {required_count} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return method_info.return_type
        if len(expr.arguments) > total_params:
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"method `{expr.method_name}` takes at most {total_params} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return method_info.return_type
        for i, arg in enumerate(expr.arguments):
            arg_type = self._check_expression(arg.value)
            expected_type = method_info.param_types[i + param_offset]
            if type_subst:
                expected_type = expected_type.substitute(type_subst)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = method_info.param_names[i + param_offset]
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
        return_type = method_info.return_type
        if type_subst:
            return_type = return_type.substitute(type_subst)
        return return_type

    def _check_module_function_call(self, expr: MethodCall, func_info) -> Optional[SawType]:
        """Check a module function call: ModuleName.function(args)"""
        if len(expr.arguments) != len(func_info.param_types):
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"function `{expr.method_name}` takes {len(func_info.param_types)} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return func_info.return_type
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, func_info.param_types)):
            arg_type = self._check_expression(arg.value)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument {i + 1} expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
        return func_info.return_type

    def _check_static_method_call(self, expr: MethodCall, struct_name: str,
                                   struct_info, method_info) -> Optional[SawType]:
        """Check a static method call: StructName.method(args)"""
        required_count = sum(1 for dv in method_info.default_values if dv is None)
        if len(expr.arguments) < required_count:
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"static method `{struct_name}.{expr.method_name}` takes at least {required_count} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return method_info.return_type
        if len(expr.arguments) > len(method_info.param_types):
            self.reporter.error(
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
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.value.line, arg.value.column
                )
        return method_info.return_type

    def _check_self_expr(self, expr: SelfExpr) -> Optional[SawType]:
        """Check 'self' keyword usage."""
        if self.current_method is None:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' can only be used inside methods",
                expr.line, expr.column
            )
            return None
        var_info = self.current_scope.lookup("self")
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                "'self' not found in method scope",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_enum_init(self, expr: EnumInit) -> Optional[SawType]:
        """Check enum variant initialization."""
        if expr.enum_name not in self.enums:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined enum `{expr.enum_name}`",
                expr.line, expr.column
            )
            return None
        enum_info = self.enums[expr.enum_name]
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params:
            if not expr.type_args:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"generic enum `{expr.enum_name}` requires type arguments",
                    expr.line, expr.column,
                    hint=f"use `{expr.enum_name}<...>.{expr.variant_name}(...)`"
                )
            elif len(expr.type_args) != len(enum_info.type_params):
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"expected {len(enum_info.type_params)} type argument(s), got {len(expr.type_args)}",
                    expr.line, expr.column
                )
            else:
                for type_param, type_arg in zip(enum_info.type_params, expr.type_args):
                    type_mapping[type_param.name] = type_arg
        if expr.variant_name not in enum_info.variants:
            self.reporter.error(
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
            self.reporter.error(
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
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"variant `{expr.variant_name}` has no parameter named `{arg.name}`",
                        expr.line, expr.column
                    )
                    continue
                arg_type = self._check_expression(arg.value)
                expected_type = expected_dict[arg.name]
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{arg.name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
            else:
                if i >= len(expected_list):
                    continue
                param_name, expected_type = expected_list[i]
                arg_type = self._check_expression(arg.value)
                if arg_type and not self._types_compatible(arg_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected type `{expected_type}` for parameter `{param_name}`, got `{arg_type}`",
                        arg.value.line, arg.value.column
                    )
        return SawType(TypeKind.ENUM, enum_name=expr.enum_name, type_args=expr.type_args)

    def _check_match_expr(self, expr: MatchExpr) -> Optional[SawType]:
        """Check match expression."""
        from .core import VariableInfo, Scope
        matched_type = self._check_expression(expr.matched_expr)
        if matched_type is None:
            return None
        if matched_type.kind != TypeKind.ENUM or matched_type.enum_name is None:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"match expression requires an enum type, got `{matched_type}`",
                expr.line, expr.column
            )
            return None
        enum_info = self.enums.get(matched_type.enum_name)
        if enum_info is None:
            return None
        type_mapping: Dict[str, SawType] = {}
        if enum_info.type_params and matched_type.type_args:
            for type_param, type_arg in zip(enum_info.type_params, matched_type.type_args):
                type_mapping[type_param.name] = type_arg
        arm_types = []
        matched_variants = set()
        has_wildcard = False
        for arm in expr.arms:
            if arm.variant_name == "_":
                has_wildcard = True
                if arm.bindings:
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        "wildcard pattern `_` cannot have bindings",
                        arm.line, arm.column
                    )
                if isinstance(arm.body, Block):
                    arm_type = self._check_block(arm.body)
                else:
                    arm_type = self._check_expression(arm.body)
                arm_types.append(arm_type)
                continue
            if arm.variant_name not in enum_info.variants:
                self.reporter.error(
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
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"variant `{arm.variant_name}` has {len(variant_params)} associated values, got {len(arm.bindings)} bindings",
                    arm.line, arm.column
                )
                continue
            old_scope = self.current_scope
            self.current_scope = Scope(parent=old_scope)
            for binding_name, (_, param_type) in zip(arm.bindings, variant_params):
                var_info = VariableInfo(
                    type=param_type,
                    mutable=False,
                    line=arm.line,
                    column=arm.column
                )
                if not self.current_scope.define(binding_name, var_info):
                    self.reporter.error(
                        ErrorKind.DUPLICATE_VARIABLE,
                        f"binding `{binding_name}` is already defined in this scope",
                        arm.line, arm.column
                    )
            if isinstance(arm.body, Block):
                arm_type = self._check_block(arm.body)
            else:
                arm_type = self._check_expression(arm.body)
            arm_types.append(arm_type)
            self.current_scope = old_scope
        if not has_wildcard:
            all_variants = set(enum_info.variants.keys())
            missing_variants = all_variants - matched_variants
            if missing_variants:
                missing_list = ", ".join(f"`{v}`" for v in sorted(missing_variants))
                self.reporter.error(
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
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"match arms have incompatible types: `{result_type}` and `{arm_type}`",
                    expr.line, expr.column
                )
                return None
        return result_type

    def _check_closure(self, expr: ClosureExpr, expected_type: Optional[SawType] = None) -> Optional[SawType]:
        """Type check a closure expression."""
        from .core import VariableInfo, Scope
        outer_scope = self.current_scope
        self.current_scope = Scope(parent=outer_scope)
        param_types = []
        if expr.parameters:
            for i, param in enumerate(expr.parameters):
                if param.type_annotation:
                    param_type = self._resolve_type(param.type_annotation)
                elif expected_type and expected_type.kind == TypeKind.FUNCTION:
                    expected_params = expected_type.param_types or []
                    if i < len(expected_params):
                        param_type = expected_params[i]
                    else:
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure has more parameters than expected function type",
                            param.line, param.column
                        )
                        param_type = SawType(TypeKind.INT)
                else:
                    self.reporter.error(
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
                        self.reporter.error(
                            ErrorKind.TYPE_MISMATCH,
                            f"Closure uses `${i}` but expected function type only has {len(expected_params)} parameters",
                            expr.line, expr.column
                        )
                        param_type = SawType(TypeKind.INT)
                else:
                    self.reporter.error(
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
        expr.captures = captures
        self.current_scope = outer_scope
        return SawType(TypeKind.FUNCTION, param_types=param_types, func_return_type=return_type)

    def _analyze_closure_captures(self, body: Block, outer_scope) -> List[str]:
        """Find all variables from outer scope that are used in the closure body."""
        captures = []
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
            elif isinstance(expr, FunctionCall):
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
            elif isinstance(expr, TupleLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayLiteral):
                for elem in expr.elements:
                    collect_names(elem)
            elif isinstance(expr, ArrayIndex):
                collect_names(expr.array_expr)
                collect_names(expr.index)
            elif isinstance(expr, MemberAccess):
                collect_names(expr.object)
            elif isinstance(expr, ForceUnwrap):
                collect_names(expr.expr)
            elif isinstance(expr, NilCoalesce):
                collect_names(expr.expr)
                collect_names(expr.default)
            elif isinstance(expr, OptionalChain):
                collect_names(expr.expr)
            elif isinstance(expr, ClosureExpr):
                pass

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
                elif isinstance(stmt, ReturnStatement):
                    if stmt.value:
                        collect_names(stmt.value)
            if block.final_expr:
                collect_names(block.final_expr)

        collect_block(body)
        for name in used_names:
            var_info = outer_scope.lookup(name)
            if var_info:
                captures.append(name)
        return captures

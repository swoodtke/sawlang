"""
Saw Language Type Checker
Performs type checking and semantic analysis on the AST.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    BinaryOp, UnaryOp, FunctionCall, IfExpr,
    SawType, TypeKind, Parameter
)
from errors import ErrorReporter, ErrorKind


@dataclass
class VariableInfo:
    """Information about a variable in scope."""
    type: SawType
    mutable: bool
    line: int
    column: int


@dataclass
class FunctionInfo:
    """Information about a function."""
    param_types: List[SawType]
    return_type: SawType
    param_names: List[str]


class Scope:
    """A lexical scope containing variable bindings."""

    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.variables: Dict[str, VariableInfo] = {}

    def define(self, name: str, info: VariableInfo) -> bool:
        """Define a variable in this scope. Returns False if already defined."""
        if name in self.variables:
            return False
        self.variables[name] = info
        return True

    def lookup(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable, checking parent scopes."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[VariableInfo]:
        """Look up a variable only in this scope."""
        return self.variables.get(name)


class TypeChecker:
    """Type checks a Saw program."""

    def __init__(self, reporter: ErrorReporter):
        self.reporter = reporter
        self.functions: Dict[str, FunctionInfo] = {}
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None

        # Register built-in functions
        self._register_builtins()

    def _register_builtins(self):
        """Register built-in functions."""
        # print can take any single argument
        # We'll handle it specially in check_function_call
        pass

    def check(self, program: Program) -> bool:
        """Type check the entire program. Returns True if no errors."""
        # First pass: collect function signatures
        for func in program.functions:
            self._register_function(func)

        # Check for main function
        if "main" not in self.functions:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                "no `main` function found",
                1, 1,
                hint="add a `fn main() { }` function as the entry point"
            )

        # Second pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        return not self.reporter.has_errors()

    def _register_function(self, func: Function):
        """Register a function signature."""
        if func.name in self.functions:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{func.name}` is defined multiple times",
                func.line, func.column
            )
            return

        param_types = [p.type for p in func.parameters]
        param_names = [p.name for p in func.parameters]
        info = FunctionInfo(param_types, func.return_type, param_names)
        self.functions[func.name] = info

    def _check_function(self, func: Function):
        """Type check a function body."""
        self.current_function = func

        # Create new scope for function
        self.current_scope = Scope()

        # Add parameters to scope
        for param in func.parameters:
            info = VariableInfo(param.type, mutable=False, line=func.line, column=func.column)
            self.current_scope.define(param.name, info)

        # Check body
        body_type = self._check_block(func.body)

        # Check return type matches
        if func.return_type.kind != TypeKind.VOID:
            if body_type is None:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{func.return_type}` but body has no value",
                    func.line, func.column
                )
            elif not self._types_compatible(body_type, func.return_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{func.return_type}` but returns `{body_type}`",
                    func.line, func.column
                )

        self.current_function = None

    def _check_block(self, block: Block) -> Optional[SawType]:
        """Check a block and return its type (from final expression)."""
        # Create new scope for block
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        for stmt in block.statements:
            self._check_statement(stmt)

        result_type = None
        if block.final_expr is not None:
            result_type = self._check_expression(block.final_expr)

        # Restore scope
        self.current_scope = old_scope

        return result_type

    def _check_statement(self, stmt: Statement):
        """Check a statement."""
        if isinstance(stmt, LetStatement):
            self._check_let_statement(stmt)
        elif isinstance(stmt, AssignStatement):
            self._check_assign_statement(stmt)
        elif isinstance(stmt, ReturnStatement):
            self._check_return_statement(stmt)
        elif isinstance(stmt, ExpressionStatement):
            self._check_expression(stmt.expression)

    def _check_let_statement(self, stmt: LetStatement):
        """Check a let/var statement."""
        # Check for duplicate in current scope
        existing = self.current_scope.lookup_local(stmt.name)
        if existing:
            self.reporter.error(
                ErrorKind.DUPLICATE_VARIABLE,
                f"variable `{stmt.name}` is already defined in this scope",
                stmt.line, stmt.column,
                hint=f"previous definition was at line {existing.line}"
            )
            return

        # Infer or check type
        value_type = self._check_expression(stmt.value)

        if stmt.type_annotation:
            if not self._types_compatible(value_type, stmt.type_annotation):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to variable of type `{stmt.type_annotation}`",
                    stmt.line, stmt.column
                )
            var_type = stmt.type_annotation
        else:
            var_type = value_type

        # Add to scope
        if var_type:
            info = VariableInfo(var_type, stmt.mutable, stmt.line, stmt.column)
            self.current_scope.define(stmt.name, info)

    def _check_assign_statement(self, stmt: AssignStatement):
        """Check an assignment statement."""
        # Look up variable
        var_info = self.current_scope.lookup(stmt.name)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{stmt.name}`",
                stmt.line, stmt.column
            )
            return

        # Check mutability
        if not var_info.mutable:
            self.reporter.error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign to immutable variable `{stmt.name}`",
                stmt.line, stmt.column,
                hint="consider using `var` instead of `let` to make it mutable"
            )

        # Check type
        value_type = self._check_expression(stmt.value)
        if value_type and not self._types_compatible(value_type, var_info.type):
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to variable of type `{var_info.type}`",
                stmt.line, stmt.column
            )

    def _check_return_statement(self, stmt: ReturnStatement):
        """Check a return statement."""
        if self.current_function is None:
            return

        expected = self.current_function.return_type

        if stmt.value is None:
            if expected.kind != TypeKind.VOID:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function should return `{expected}` but return has no value",
                    stmt.line, stmt.column
                )
        else:
            value_type = self._check_expression(stmt.value)
            if value_type and expected.kind == TypeKind.VOID:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function returns void but return has a value of type `{value_type}`",
                    stmt.line, stmt.column
                )
            elif value_type and not self._types_compatible(value_type, expected):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"expected return type `{expected}` but got `{value_type}`",
                    stmt.line, stmt.column
                )

    def _check_expression(self, expr: Expression) -> Optional[SawType]:
        """Check an expression and return its type."""
        if isinstance(expr, IntLiteral):
            return SawType(TypeKind.INT)

        elif isinstance(expr, FloatLiteral):
            return SawType(TypeKind.FLOAT)

        elif isinstance(expr, BoolLiteral):
            return SawType(TypeKind.BOOL)

        elif isinstance(expr, StringLiteral):
            return SawType(TypeKind.STRING)

        elif isinstance(expr, Identifier):
            return self._check_identifier(expr)

        elif isinstance(expr, BinaryOp):
            return self._check_binary_op(expr)

        elif isinstance(expr, UnaryOp):
            return self._check_unary_op(expr)

        elif isinstance(expr, FunctionCall):
            return self._check_function_call(expr)

        elif isinstance(expr, IfExpr):
            return self._check_if_expr(expr)

        return None

    def _check_identifier(self, expr: Identifier) -> Optional[SawType]:
        """Check an identifier reference."""
        var_info = self.current_scope.lookup(expr.name)
        if not var_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"undefined variable `{expr.name}`",
                expr.line, expr.column
            )
            return None
        return var_info.type

    def _check_binary_op(self, expr: BinaryOp) -> Optional[SawType]:
        """Check a binary operation."""
        left_type = self._check_expression(expr.left)
        right_type = self._check_expression(expr.right)

        if left_type is None or right_type is None:
            return None

        # Arithmetic operators
        if expr.op in ['+', '-', '*', '/']:
            if left_type.kind == TypeKind.INT and right_type.kind == TypeKind.INT:
                return SawType(TypeKind.INT)
            elif left_type.kind in [TypeKind.INT, TypeKind.FLOAT] and \
                 right_type.kind in [TypeKind.INT, TypeKind.FLOAT]:
                return SawType(TypeKind.FLOAT)
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{expr.op}` cannot be applied to `{left_type}` and `{right_type}`",
                    expr.line, expr.column
                )
                return None

        # Comparison operators
        elif expr.op in ['==', '!=', '<', '>', '<=', '>=']:
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

        if expr.op == '-':
            if operand_type.kind in [TypeKind.INT, TypeKind.FLOAT]:
                return operand_type
            else:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `-` cannot be applied to `{operand_type}`",
                    expr.line, expr.column
                )
                return None

        return None

    def _check_function_call(self, expr: FunctionCall) -> Optional[SawType]:
        """Check a function call."""
        # Handle built-in print specially
        if expr.name == "print":
            if len(expr.arguments) > 1:
                self.reporter.error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"`print` takes 0 or 1 arguments, but {len(expr.arguments)} were given",
                    expr.line, expr.column
                )
            # Check argument type (print accepts any type)
            for arg in expr.arguments:
                self._check_expression(arg)
            return SawType(TypeKind.VOID)

        # Look up function
        func_info = self.functions.get(expr.name)
        if not func_info:
            self.reporter.error(
                ErrorKind.UNDEFINED_FUNCTION,
                f"undefined function `{expr.name}`",
                expr.line, expr.column
            )
            return None

        # Check argument count
        if len(expr.arguments) != len(func_info.param_types):
            self.reporter.error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"function `{expr.name}` takes {len(func_info.param_types)} argument(s), "
                f"but {len(expr.arguments)} were given",
                expr.line, expr.column
            )
            return func_info.return_type

        # Check argument types
        for i, (arg, expected_type) in enumerate(zip(expr.arguments, func_info.param_types)):
            arg_type = self._check_expression(arg)
            if arg_type and not self._types_compatible(arg_type, expected_type):
                param_name = func_info.param_names[i]
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{param_name}` expects `{expected_type}` but got `{arg_type}`",
                    arg.line, arg.column
                )

        return func_info.return_type

    def _check_if_expr(self, expr: IfExpr) -> Optional[SawType]:
        """Check an if expression."""
        cond_type = self._check_expression(expr.condition)

        if cond_type and cond_type.kind != TypeKind.BOOL:
            # Allow int as condition (truthy/falsy)
            if cond_type.kind != TypeKind.INT:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"condition must be `Bool`, got `{cond_type}`",
                    expr.line, expr.column
                )

        then_type = self._check_block(expr.then_branch)

        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)

            # If both branches have values, they must match
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if` and `else` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )

            return then_type or else_type
        else:
            return then_type

    def _types_compatible(self, a: Optional[SawType], b: Optional[SawType]) -> bool:
        """Check if two types are compatible."""
        if a is None or b is None:
            return True  # Assume compatible if we couldn't determine types
        return a.kind == b.kind

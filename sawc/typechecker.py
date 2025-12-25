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
    BinaryOp, UnaryOp, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    GuardLetStatement,
    Struct, StructField,
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


@dataclass
class StructInfo:
    """Information about a struct."""
    name: str
    fields: Dict[str, SawType]  # field_name -> type
    field_order: List[str]  # preserve declaration order


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
        self.structs: Dict[str, StructInfo] = {}
        self.functions: Dict[str, FunctionInfo] = {}
        self.current_scope: Scope = Scope()
        self.current_function: Optional[Function] = None
        # Track return statements found in current function
        self.found_return_with_value: bool = False

        # Register built-in functions
        self._register_builtins()

    def _register_builtins(self):
        """Register built-in functions."""
        # print can take any single argument
        # We'll handle it specially in check_function_call
        pass

    def check(self, program: Program) -> bool:
        """Type check the entire program. Returns True if no errors."""
        # First pass: collect struct definitions
        for struct in program.structs:
            self._register_struct(struct)

        # Second pass: collect function signatures
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

        # Third pass: type check function bodies
        for func in program.functions:
            self._check_function(func)

        return not self.reporter.has_errors()

    def _register_struct(self, struct: Struct):
        """Register a struct definition."""
        if struct.name in self.structs:
            self.reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,  # We can reuse this error kind
                f"struct `{struct.name}` is defined multiple times",
                struct.line, struct.column
            )
            return

        # Check for duplicate fields
        fields = {}
        field_order = []
        seen_fields = set()

        for field in struct.fields:
            if field.name in seen_fields:
                self.reporter.error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"field `{field.name}` is defined multiple times in struct `{struct.name}`",
                    struct.line, struct.column
                )
            else:
                seen_fields.add(field.name)
                fields[field.name] = field.type
                field_order.append(field.name)

        self.structs[struct.name] = StructInfo(
            name=struct.name,
            fields=fields,
            field_order=field_order
        )

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
        self.found_return_with_value = False  # Reset for each function

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
            # Function can return a value via either:
            # 1. An explicit return statement (found_return_with_value)
            # 2. A final expression in the body (body_type)
            if body_type is None and not self.found_return_with_value:
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{func.return_type}` but body has no value",
                    func.line, func.column
                )
            elif body_type is not None and not self._types_compatible(body_type, func.return_type):
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
        elif isinstance(stmt, GuardLetStatement):
            self._check_guard_let_statement(stmt)
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

    def _check_guard_let_statement(self, stmt: GuardLetStatement):
        """Check a guard let/var statement for optional binding."""
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

        # Check the optional expression
        optional_type = self._check_expression(stmt.optional_expr)

        if optional_type is None:
            return

        # Must be an optional type
        if optional_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"'guard let' requires an optional type, got `{optional_type}`",
                stmt.line, stmt.column
            )
            return

        # Get the unwrapped type
        inner_type = optional_type.inner_type
        if inner_type is None:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                stmt.line, stmt.column
            )
            return

        # Check the else branch (should contain early exit)
        # Create a temporary scope for the else branch
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        self._check_block(stmt.else_branch)
        self.current_scope = old_scope

        # TODO: Verify else branch has early exit (return, break, continue)
        # For now, we trust the programmer

        # Add the bound variable to the current (outer) scope
        # This is the key difference from if-let: the variable is available after the guard
        info = VariableInfo(inner_type, stmt.mutable, stmt.line, stmt.column)
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
            else:
                # Mark that we found a valid return statement with a value
                self.found_return_with_value = True

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

        elif isinstance(expr, IfLetExpr):
            return self._check_if_let_expr(expr)

        elif isinstance(expr, TupleLiteral):
            return self._check_tuple_literal(expr)

        elif isinstance(expr, TupleIndex):
            return self._check_tuple_index(expr)

        elif isinstance(expr, MemberAccess):
            return self._check_member_access(expr)

        elif isinstance(expr, StructInit):
            return self._check_struct_init(expr)

        elif isinstance(expr, NoneLiteral):
            return self._check_none_literal(expr)

        elif isinstance(expr, ForceUnwrap):
            return self._check_force_unwrap(expr)

        elif isinstance(expr, NilCoalesce):
            return self._check_nil_coalesce(expr)

        elif isinstance(expr, OptionalChain):
            return self._check_optional_chain(expr)

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

    def _check_if_let_expr(self, expr: IfLetExpr) -> Optional[SawType]:
        """Check an if let/var expression for optional binding."""
        # Check the optional expression
        optional_type = self._check_expression(expr.optional_expr)

        if optional_type is None:
            return None

        # Must be an optional type
        if optional_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"'if let' requires an optional type, got `{optional_type}`",
                expr.line, expr.column
            )
            return None

        # For 'if var', the source optional must be mutable (we'd need to track this)
        # For now, we'll allow it - the reference semantics will be enforced at codegen

        # Get the unwrapped type
        inner_type = optional_type.inner_type
        if inner_type is None:
            # None literal with unknown type - treat as void or error
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                expr.line, expr.column
            )
            return None

        # Create new scope for then branch with the bound variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        self.current_scope.define(
            expr.name,
            VariableInfo(inner_type, expr.mutable, expr.line, expr.column)
        )

        then_type = self._check_block(expr.then_branch)

        self.current_scope = old_scope

        # Check else branch if present
        else_type = None
        if expr.else_branch:
            else_type = self._check_block(expr.else_branch)

            # If both branches have values, they must match
            if then_type and else_type and not self._types_compatible(then_type, else_type):
                self.reporter.error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`if let` branches have incompatible types: `{then_type}` vs `{else_type}`",
                    expr.line, expr.column
                )

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

    def _check_member_access(self, expr: MemberAccess) -> Optional[SawType]:
        """Check member access for struct fields."""
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
            # This shouldn't happen if type checking is working correctly
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
        """Check struct initialization."""
        # Check if struct exists
        struct_info = self.structs.get(expr.struct_name)
        if struct_info is None:
            self.reporter.error(
                ErrorKind.UNDEFINED_VARIABLE,  # Could add UNDEFINED_STRUCT
                f"undefined struct `{expr.struct_name}`",
                expr.line, expr.column
            )
            return None

        # Check that all fields are initialized
        provided_fields = {field_name for field_name, _ in expr.field_inits}
        required_fields = set(struct_info.fields.keys())

        missing = required_fields - provided_fields
        if missing:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{expr.struct_name}` is missing fields: {', '.join(sorted(missing))}",
                expr.line, expr.column
            )

        # Check for extra fields
        extra = provided_fields - required_fields
        if extra:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"struct `{expr.struct_name}` has no fields: {', '.join(sorted(extra))}",
                expr.line, expr.column
            )

        # Check field types
        for field_name, field_value in expr.field_inits:
            if field_name in struct_info.fields:
                expected_type = struct_info.fields[field_name]
                actual_type = self._check_expression(field_value)
                if actual_type and not self._types_compatible(actual_type, expected_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"field `{field_name}` expects type `{expected_type}` but got `{actual_type}`",
                        expr.line, expr.column
                    )

        return SawType(TypeKind.STRUCT, struct_name=expr.struct_name)

    def _check_none_literal(self, expr: NoneLiteral) -> Optional[SawType]:
        """Check None literal - returns a special 'None' type that can unify with any T?."""
        # None has a special type that's compatible with any optional
        return SawType(TypeKind.OPTIONAL, inner_type=None)

    def _check_force_unwrap(self, expr: ForceUnwrap) -> Optional[SawType]:
        """Check force unwrap: expr! - unwraps T? to T."""
        inner_type = self._check_expression(expr.expr)
        if inner_type is None:
            return None

        if inner_type.kind != TypeKind.OPTIONAL:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot force unwrap non-optional type `{inner_type}`",
                expr.line, expr.column
            )
            return inner_type  # Return original type to continue checking

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

        # Check that the inner type matches the default type
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

        # Check that inner type is a struct
        if inner_type.kind != TypeKind.STRUCT:
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot access member of non-struct type `{inner_type}`",
                expr.line, expr.column
            )
            return None

        # Look up the field
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

        # Return the field type wrapped in optional
        field_type = struct_info.fields[expr.member]
        return SawType(TypeKind.OPTIONAL, inner_type=field_type)

    def _types_compatible(self, a: Optional[SawType], b: Optional[SawType]) -> bool:
        """Check if two types are compatible."""
        if a is None or b is None:
            return True  # Assume compatible if we couldn't determine types

        # None literal (OPTIONAL with inner_type=None) is compatible with any optional
        if a.kind == TypeKind.OPTIONAL and a.inner_type is None and b.kind == TypeKind.OPTIONAL:
            return True
        if b.kind == TypeKind.OPTIONAL and b.inner_type is None and a.kind == TypeKind.OPTIONAL:
            return True

        # Allow implicit wrapping: T is compatible with T?
        if b.kind == TypeKind.OPTIONAL and b.inner_type is not None:
            if self._types_compatible(a, b.inner_type):
                return True

        if a.kind != b.kind:
            return False

        # For tuple types, check element types match
        if a.kind == TypeKind.TUPLE:
            if a.element_types is None or b.element_types is None:
                return True
            if len(a.element_types) != len(b.element_types):
                return False
            return all(self._types_compatible(at, bt)
                      for at, bt in zip(a.element_types, b.element_types))

        # For struct types, check struct names match
        if a.kind == TypeKind.STRUCT:
            return a.struct_name == b.struct_name

        # For optional types, check inner types match
        if a.kind == TypeKind.OPTIONAL:
            if a.inner_type is None or b.inner_type is None:
                return True
            return self._types_compatible(a.inner_type, b.inner_type)

        return True

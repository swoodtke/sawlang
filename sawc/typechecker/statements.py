"""
Statement checking methods for the Saw type checker.

This module provides mixin methods for checking statements, blocks, functions,
methods, and control flow (while loops, for loops, break, continue, return).

Usage:
    class TypeChecker(StatementsMixin, ...):
        pass
"""

from typing import Optional, Dict
from ast_nodes import (
    Extension, Method, Function, Block, Statement,
    LetStatement, AssignStatement, CompoundAssignStatement, ReturnStatement, GuardLetStatement,
    BreakStatement, ContinueStatement, ExpressionStatement,
    WhileExpr, ForLoop, RangeExpr,
    Identifier, MemberAccess, ArrayIndex, MoveExpr, IntLiteral,
    SawType, TypeKind,
    ResultOkWrap, ResultErrWrap, OptionalWrap
)
from errors import ErrorKind


class StatementsMixin:
    """Mixin providing statement checking methods for TypeChecker.

    These methods check statement-level constructs including variable bindings,
    assignments, control flow, and function/method bodies.

    Methods:
        _check_extension: Type check all methods in an extension
        _check_method: Type check a method body
        _check_function: Type check a function body
        _check_block: Check a block and return its type
        _check_statement: Check a statement (dispatch)
        _check_let_statement: Check let/var variable binding
        _check_guard_let_statement: Check guard let/var for optional binding
        _check_assign_statement: Check assignment statement
        _check_return_statement: Check return statement
        _check_while_expr: Check while loop as statement
        _check_while_expr_as_expression: Check while loop as expression
        _check_for_loop: Check for loop as statement
        _check_for_loop_as_expression: Check for loop as expression
        _get_iterator_item_type: Get Item type for Iterator implementors
        _check_range_expr: Check range expression (start..end)
        _check_break_statement: Check break statement
        _check_continue_statement: Check continue statement
    """

    def _check_extension(self, extension: Extension):
        """Type check all methods in an extension."""
        # Check if this is a specialized extension (e.g., extension Vector<String>)
        specialization_key = self._get_specialization_key(extension)

        # Build type substitution map for specialized extensions
        type_subst = {}
        if specialization_key:
            # Get the struct's type params to map them to the specialized types
            struct_info = self.get_struct_info(extension.struct_name)
            if struct_info and struct_info.type_params:
                for i, type_param in enumerate(struct_info.type_params):
                    if i < len(specialization_key):
                        # Convert the specialization key name to a SawType
                        type_name = specialization_key[i]
                        type_subst[type_param.name] = self._name_to_type(type_name)

        # For a fully-generic extension (not a specialization), expose its type
        # parameters and their bounds to the method bodies, so that e.g. a
        # `<T: Copy>` bound grants `.copy()` on a value of type T inside the body.
        prev_type_params = getattr(self, 'current_type_params', {})
        self.current_type_params = dict(prev_type_params)
        if not specialization_key:
            for tp in extension.type_params:
                self.current_type_params[tp.name] = tp.bounds

        try:
            for method in extension.methods:
                self._check_method(extension.struct_name, method, type_subst)
        finally:
            self.current_type_params = prev_type_params

    def _check_method(self, struct_name: str, method: Method, type_subst: Dict[str, SawType] = None):
        """Type check a method body.

        Args:
            struct_name: The name of the struct this method belongs to
            method: The method AST node
            type_subst: Optional type substitution map for specialized extensions
                       (e.g., {"T": String} for extension Vector<String>)
        """
        from .core import VariableInfo, Scope

        # A compiler-derived memberwise copy() has no user-written body to check;
        # its signature is already registered and codegen emits the body with
        # full knowledge of each field's copy tier. Skip body checking.
        if getattr(method, 'is_derived_copy', False):
            return

        self.current_method = method
        self.found_return_with_value = False
        self.current_type_subst = type_subst or {}

        # design 22: analyze this method body as a suspend-graph node (a `deinit`
        # body and a `sync func` method are sync contexts).
        self._effect_enter_method(struct_name, method)

        # Move state is function-local (design 15): fresh per method body.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}

        # Create new scope for method
        self.current_scope = Scope()

        # Determine the Self type for this extension
        if struct_name == "String":
            self_type = SawType(TypeKind.STRING)
        else:
            # For specialized extensions, include the type args in self_type
            if type_subst:
                type_args = list(type_subst.values())
                self_type = SawType(TypeKind.STRUCT, struct_name=struct_name, type_args=type_args)
            else:
                self_type = SawType(TypeKind.STRUCT, struct_name=struct_name)

        # Add parameters to scope
        for param in method.parameters:
            # Resolve Self type to concrete type
            param_type = param.type
            # 'self' parameter has VOID as placeholder - replace with actual Self type
            if param.name == "self" or param_type.kind == TypeKind.SELF:
                param_type = self_type
            info = VariableInfo(param_type, mutable=False, line=method.line, column=method.column)
            self.current_scope.define(param.name, info)

        # Determine expected return type first (needed for None propagation)
        expected_return = method.return_type
        # Resolve Self in return type
        if expected_return.kind == TypeKind.SELF:
            expected_return = self_type
        if method.is_init:
            expected_return = self_type

        # Check body
        body_type = self._check_block(method.body)

        # Propagate expected type to body for None annotation
        if expected_return.is_optional() and method.body.final_expr:
            self._propagate_optional_type(method.body.final_expr, expected_return)

        if expected_return.kind != TypeKind.VOID:
            if body_type is None and not self.found_return_with_value:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method.name}` should return `{expected_return}` but body has no value",
                    method.line, method.column
                )
            elif body_type is not None and not self._types_compatible(body_type, expected_return):
                # Check for Result auto-wrapping on final expression
                if expected_return.is_result() and method.body.final_expr:
                    ok_type = expected_return.unwrap_result_ok()
                    err_type = expected_return.unwrap_result_err()

                    if body_type.is_result():
                        # Already a Result but types don't match
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"method `{method.name}` should return `{expected_return}` but returns `{body_type}`",
                            method.line, method.column
                        )
                    elif self._result_autowrap_ambiguous(
                            expected_return, body_type, f"method `{method.name}`",
                            method.line, method.column):
                        pass  # design 30: ambiguity reported; no wrap
                    elif self._types_compatible(body_type, ok_type):
                        # Wrap in ResultOkWrap
                        method.body.final_expr = ResultOkWrap(
                            value=method.body.final_expr,
                            result_type=expected_return,
                            line=method.body.final_expr.line,
                            column=method.body.final_expr.column
                        )
                    elif self._types_compatible(body_type, err_type):
                        # Wrap in ResultErrWrap
                        method.body.final_expr = ResultErrWrap(
                            value=method.body.final_expr,
                            result_type=expected_return,
                            line=method.body.final_expr.line,
                            column=method.body.final_expr.column
                        )
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"method `{method.name}` should return `{expected_return}` but returns `{body_type}` "
                            f"(doesn't match Ok type `{ok_type}` or Err type `{err_type}`)",
                            method.line, method.column
                        )
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method.name}` should return `{expected_return}` but returns `{body_type}`",
                        method.line, method.column
                    )
            elif body_type is not None and method.body.final_expr:
                # Types are compatible - check if we need Optional wrapping
                if expected_return.is_optional() and not body_type.is_optional() and not body_type.is_none_literal():
                    method.body.final_expr = OptionalWrap(
                        value=method.body.final_expr,
                        target_type=expected_return,
                        line=method.body.final_expr.line,
                        column=method.body.final_expr.column
                    )

        # Check NoCopy return - must use move for variable references
        # Check both the return type and the inner type if optional
        check_type = expected_return
        if expected_return.is_optional() and expected_return.inner_type:
            check_type = expected_return.inner_type
        self._check_no_copy_return(check_type, method.body.final_expr,
                                    f"method `{method.name}`", method.line, method.column)

        self._effect_exit()
        self.current_method = None
        self.moved_bindings = saved_moves

    def _reconcile_return_type(self, func, resolved_return_type, body_type):
        """Reconcile a function body's type against its declared return type.

        Reports a mismatch, and applies Result/Optional auto-wrapping to the
        final expression where the declared return type is a concrete
        Result/Optional. Shared by the ordinary path and the generic-body
        decidable path (design 24 item 2).
        """
        if resolved_return_type.kind == TypeKind.VOID:
            return
        # Function can return a value via either:
        # 1. An explicit return statement (found_return_with_value)
        # 2. A final expression in the body (body_type)
        if body_type is None and not self.found_return_with_value:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"function `{func.name}` should return `{resolved_return_type}` but body has no value",
                func.line, func.column
            )
        elif body_type is not None and not self._types_compatible(body_type, resolved_return_type):
            # Check for Result auto-wrapping on final expression
            if resolved_return_type.is_result() and func.body.final_expr:
                ok_type = resolved_return_type.unwrap_result_ok()
                err_type = resolved_return_type.unwrap_result_err()

                if body_type.is_result():
                    # Already a Result but types don't match
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"function `{func.name}` should return `{resolved_return_type}` but returns `{body_type}`",
                        func.line, func.column
                    )
                elif self._result_autowrap_ambiguous(
                        resolved_return_type, body_type, f"function `{func.name}`",
                        func.line, func.column):
                    pass  # design 30: ambiguity reported; no wrap
                elif self._types_compatible(body_type, ok_type):
                    # Wrap in ResultOkWrap
                    func.body.final_expr = ResultOkWrap(
                        value=func.body.final_expr,
                        result_type=resolved_return_type,
                        line=func.body.final_expr.line,
                        column=func.body.final_expr.column
                    )
                elif self._types_compatible(body_type, err_type):
                    # Wrap in ResultErrWrap
                    func.body.final_expr = ResultErrWrap(
                        value=func.body.final_expr,
                        result_type=resolved_return_type,
                        line=func.body.final_expr.line,
                        column=func.body.final_expr.column
                    )
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"function `{func.name}` should return `{resolved_return_type}` but returns `{body_type}` "
                        f"(doesn't match Ok type `{ok_type}` or Err type `{err_type}`)",
                        func.line, func.column
                    )
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function `{func.name}` should return `{resolved_return_type}` but returns `{body_type}`",
                    func.line, func.column
                )
        elif body_type is not None and func.body.final_expr:
            # Types are compatible - check if we need Optional wrapping
            if resolved_return_type.is_optional() and not body_type.is_optional() and not body_type.is_none_literal():
                func.body.final_expr = OptionalWrap(
                    value=func.body.final_expr,
                    target_type=resolved_return_type,
                    line=func.body.final_expr.line,
                    column=func.body.final_expr.column
                )

    def _result_autowrap_ambiguous(self, expected, value_type, context_desc, line, column) -> bool:
        """Design 30 Ruling 1: reject an ambiguous bare-value Result auto-wrap.

        When a bare value is returned from a function declared to return a
        concrete `Result<T, E>` whose Ok and Err types BOTH accept the value —
        the `T == E` case — auto-wrap can't tell which variant is meant. Rather
        than silently defaulting to Ok (the pre-design-30 behavior), report the
        ambiguity and demand the explicit variant.

        Returns True (having emitted the error) when the wrap is ambiguous; the
        caller must then skip auto-wrapping. Returns False otherwise.

        Note on generics: in an abstract generic body the declared `Result<T, E>`
        has distinct opaque type parameters T and E, which are not compatible
        with each other, so a `T`-typed value matches only Ok — no ambiguity.
        The per-parameter wrap decision therefore monomorphizes consistently even
        when an instantiation makes `T == E` (brief 24).
        """
        ok_type = expected.unwrap_result_ok()
        err_type = expected.unwrap_result_err()
        if ok_type is None or err_type is None:
            return False
        if not (self._types_compatible(value_type, ok_type)
                and self._types_compatible(value_type, err_type)):
            return False
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"ambiguous Result auto-wrap: {context_desc} returns `{value_type}`, "
            f"but `{expected}` has the same Ok and Err type, so a bare `return` "
            f"can't tell which variant you mean; write the explicit "
            f"`{expected}.Ok(value: ...)` or `{expected}.Err(error: ...)`",
            line, column
        )
        return True

    def _return_type_is_decidable(self, resolved_return_type, body_type) -> bool:
        """Design 24 item 2 decidability rule.

        A generic body's return type can be reconciled abstractly ONLY when both
        the declared return type and the body's produced type are fully concrete
        — i.e. neither mentions an in-scope type parameter nor an unresolved
        associated type. If either is abstract, the outcome depends on the
        concrete instantiation (e.g. `-> T` returning a `T`, or `-> Int`
        returning a `T` that might monomorphize to `Int`), so it is deferred to
        monomorphization. This is what keeps the check conservative: it never
        errors where the answer genuinely can't be decided without a concrete
        instantiation.
        """
        if not self._is_concrete_type(resolved_return_type):
            return False
        if body_type is not None and not self._is_concrete_type(body_type):
            return False
        return True

    def _is_concrete_type(self, t) -> bool:
        """Whether `t` mentions no in-scope type parameter and no unresolved
        associated-type name — i.e. it is fully decidable without a concrete
        instantiation (design 24 item 2)."""
        if t is None:
            return False
        type_params = getattr(self, 'current_type_params', {})
        kind = t.kind
        # Result<...> (parsed as STRUCT/ENUM named "Result"): concrete iff all
        # type arguments are concrete.
        if t.is_result():
            return all(self._is_concrete_type(a) for a in (t.type_args or []))
        if kind == TypeKind.STRUCT:
            name = t.struct_name
            if name in type_params:
                return False
            # A STRUCT-kind name that resolves to no struct is an associated
            # type / unresolved placeholder — abstract.
            if self.get_struct_info(name, from_type=t) is None:
                return False
            return all(self._is_concrete_type(a) for a in (t.type_args or []))
        if kind == TypeKind.ENUM:
            return all(self._is_concrete_type(a) for a in (t.type_args or []))
        if kind == TypeKind.OPTIONAL:
            return t.inner_type is None or self._is_concrete_type(t.inner_type)
        if kind == TypeKind.TUPLE:
            return all(self._is_concrete_type(e) for e in (t.element_types or []))
        if kind == TypeKind.ARRAY:
            return (t.array_element_type is None
                    or self._is_concrete_type(t.array_element_type))
        if kind == TypeKind.FUNCTION:
            if not all(self._is_concrete_type(p) for p in (t.param_types or [])):
                return False
            return (t.func_return_type is None
                    or self._is_concrete_type(t.func_return_type))
        # Primitives (INT/FLOAT/BOOL/STRING/VOID) and anything else are concrete.
        return True

    def _check_function(self, func: Function):
        """Type check a function body.

        Generic function bodies are checked *abstractly*: their type parameters
        stay opaque (an unresolved `T`), the body is checked once (surfacing
        body-level errors such as undefined variables or type mismatches on
        concrete types, and stamping resolved_type annotations that codegen
        consumes after substituting the monomorphization bindings), but the
        final return-type reconciliation (mismatch errors and Result/Optional
        auto-wrapping) is deferred. That reconciliation can't be decided against
        opaque type parameters / associated types without a concrete
        instantiation, so forcing it here would produce false positives; it is
        left as looseness for a follow-up (see designs/02-typed-ast.md sec. 2).
        """
        from .core import VariableInfo, Scope
        is_generic = bool(func.type_params)

        self.current_function = func
        self.found_return_with_value = False  # Reset for each function

        # design 22: analyze this function body as a suspend-graph node (a
        # `sync func` is a sync context). Generic bodies are analyzed abstractly,
        # matching how they are type-checked.
        self._effect_enter_function(func)

        # Move state is function-local (design 15): a fresh empty state per body,
        # restored on exit so a nested check (e.g. an inline module) can't leak.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}

        # Track type parameters as opaque for the duration of this body. Their
        # bounds are recorded so future bound-aware method/trait lookups can use
        # them; today lookups on an opaque type parameter stay conservative.
        prev_type_params = getattr(self, 'current_type_params', {})
        self.current_type_params = dict(prev_type_params)
        for tp in func.type_params:
            self.current_type_params[tp.name] = tp.bounds

        # Create new scope for function
        self.current_scope = Scope()

        # Add parameters to scope (resolve types first)
        for param in func.parameters:
            resolved_type = self._resolve_type(param.type)
            info = VariableInfo(resolved_type, mutable=False, line=func.line, column=func.column)
            self.current_scope.define(param.name, info)

        # Resolve return type first (needed for None propagation)
        resolved_return_type = self._resolve_type(func.return_type)

        # Check body (stamps annotations at the _check_expression chokepoint)
        body_type = self._check_block(func.body)

        if is_generic:
            # Abstract check complete: annotations produced and body-level errors
            # surfaced. Reconcile the return type only where DECIDABLE against
            # opaque type parameters (design 24 item 2). See
            # `_return_type_is_decidable` for the rule: both the declared and the
            # body's type must be fully concrete (mention no type parameter and
            # no unresolved associated type). A concrete mismatch then errors and
            # a concrete Result/Optional-of-concrete return auto-wraps, exactly
            # as in the non-generic path. Anything mentioning a type parameter or
            # associated type is deferred to monomorphization — a
            # concrete-vs-abstract comparison here (e.g. `-> T`, `-> Item`) would
            # be a false positive against the generic suite (the oracle).
            if self._return_type_is_decidable(resolved_return_type, body_type):
                if resolved_return_type.is_optional() and func.body.final_expr:
                    self._propagate_optional_type(func.body.final_expr, resolved_return_type)
                self._reconcile_return_type(func, resolved_return_type, body_type)
            self.current_type_params = prev_type_params
            self._effect_exit()
            self.current_function = None
            self.moved_bindings = saved_moves
            return

        # Propagate expected type to body for None annotation
        if resolved_return_type.is_optional() and func.body.final_expr:
            self._propagate_optional_type(func.body.final_expr, resolved_return_type)

        # Check return type matches (and apply Result/Optional auto-wrapping).
        self._reconcile_return_type(func, resolved_return_type, body_type)

        # Check NoCopy return - must use move for variable references
        # Check both the return type and the inner type if optional
        check_type = resolved_return_type
        if resolved_return_type.is_optional() and resolved_return_type.inner_type:
            check_type = resolved_return_type.inner_type
        self._check_no_copy_return(check_type, func.body.final_expr,
                                    f"function `{func.name}`", func.line, func.column)

        self.current_type_params = prev_type_params
        self._effect_exit()
        self.current_function = None
        self.moved_bindings = saved_moves

    def _check_block(self, block: Block) -> Optional[SawType]:
        """Check a block and return its type (from final expression)."""
        from .core import Scope
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
        # Handle dual-purpose nodes (Expressions used as Statements)
        if isinstance(stmt, WhileExpr):
            self._check_while_expr(stmt)
            return
        if isinstance(stmt, ForLoop):
            self._check_for_loop(stmt)
            return

        # Visitor dispatch for all other statements
        method_name = f'visit_{stmt.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor:
            visitor(stmt)

    # ===== Statement Visitor Methods =====

    def visit_LetStatement(self, stmt: LetStatement):
        self._check_let_statement(stmt)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._check_assign_statement(stmt)

    def visit_CompoundAssignStatement(self, stmt: CompoundAssignStatement):
        self._check_compound_assign_statement(stmt)

    def visit_ReturnStatement(self, stmt: ReturnStatement):
        self._check_return_statement(stmt)

    def visit_GuardLetStatement(self, stmt: GuardLetStatement):
        self._check_guard_let_statement(stmt)

    def visit_BreakStatement(self, stmt: BreakStatement):
        self._check_break_statement(stmt)

    def visit_ContinueStatement(self, stmt: ContinueStatement):
        self._check_continue_statement(stmt)

    def visit_ExpressionStatement(self, stmt: ExpressionStatement):
        self._check_expression(stmt.expression)

    def _check_let_statement(self, stmt: LetStatement):
        """Check a let/var statement."""
        from .core import VariableInfo
        # Check for duplicate in current scope
        existing = self.current_scope.lookup_local(stmt.name)
        if existing:
            self._error(
                ErrorKind.DUPLICATE_VARIABLE,
                f"variable `{stmt.name}` is already defined in this scope",
                stmt.line, stmt.column,
                hint=f"previous definition was at line {existing.line}"
            )
            return

        # Infer or check type
        value_type = self._check_expression(stmt.value)

        if stmt.type_annotation:
            # Resolve type aliases in the annotation
            resolved_type = self._resolve_type(stmt.type_annotation)
            # allow_literal_to_distinct=True because let/var initialization allows primitives to
            # initialize distinct types (e.g., `let x: MyInt = 21`)
            if not self._types_compatible(value_type, resolved_type, allow_literal_to_distinct=True):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to variable of type `{stmt.type_annotation}`",
                    stmt.line, stmt.column
                )
            # Check integer literal range for fixed-width types
            if isinstance(stmt.value, IntLiteral):
                self._check_integer_literal_range(stmt.value, resolved_type)
            # Resolve type alias to check underlying type structure (for Optional wrapping)
            underlying_type = self._resolve_type_alias(resolved_type)
            # Propagate expected type to None literals
            if value_type and value_type.is_none_literal() and underlying_type.is_optional():
                self._propagate_optional_type(stmt.value, underlying_type)
            # Wrap T in Optional if assigning to T?
            elif value_type and underlying_type.is_optional() and not value_type.is_optional():
                stmt.value = OptionalWrap(
                    value=stmt.value,
                    target_type=underlying_type,
                    line=stmt.value.line,
                    column=stmt.value.column
                )
            var_type = resolved_type
        else:
            var_type = value_type

        # Value-transfer checkpoint: enforce NoCopy move-discipline and mark
        # ImplicitCopy sites for codegen (replaces the old inline NoCopy check).
        self._check_value_transfer(stmt.value, var_type, "let binding",
                                   stmt.line, stmt.column)

        # Add to scope
        if var_type:
            info = VariableInfo(var_type, stmt.mutable, stmt.line, stmt.column)
            self.current_scope.define(stmt.name, info)

    def _check_guard_let_statement(self, stmt: GuardLetStatement):
        """Check a guard let/var statement for optional binding."""
        from .core import VariableInfo, Scope
        # Check for duplicate in current scope
        existing = self.current_scope.lookup_local(stmt.name)
        if existing:
            self._error(
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
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"'guard let' requires an optional type, got `{optional_type}`",
                stmt.line, stmt.column
            )
            return

        # Get the unwrapped type
        inner_type = optional_type.inner_type
        if inner_type is None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot determine type of bound variable from None literal",
                stmt.line, stmt.column
            )
            return

        # Check the else branch (should contain early exit)
        # Create a temporary scope for the else branch
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        # Move dataflow (design 15 rule 6): the else branch diverges (it must
        # exit the scope), so any moves it performs do NOT reach the
        # fall-through path. Snapshot before, restore after when it diverges --
        # this is what lets `guard let x = ... else { consume(move v); return }`
        # leave `v` usable on the guarded path.
        entry_moves = self._snapshot_moves()
        self._check_block(stmt.else_branch)
        self.current_scope = old_scope

        # Verify else branch has early exit (return, break, continue)
        if self._block_has_early_exit(stmt.else_branch):
            self.moved_bindings = entry_moves
        if not self._block_has_early_exit(stmt.else_branch):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "'guard' else block must exit the scope (return, break, or continue)",
                stmt.line, stmt.column,
                hint="add 'return', 'break', or 'continue' to the else block"
            )

        # Add the bound variable to the current (outer) scope
        # This is the key difference from if-let: the variable is available after the guard
        info = VariableInfo(inner_type, stmt.mutable, stmt.line, stmt.column)
        self.current_scope.define(stmt.name, info)

    def _check_assign_statement(self, stmt: AssignStatement):
        """Check an assignment statement."""
        # Handle both simple variable assignment and field assignment
        if isinstance(stmt.target, Identifier):
            # Simple variable assignment: x = value
            var_info = self.current_scope.lookup(stmt.target.name)
            if not var_info:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"undefined variable `{stmt.target.name}`",
                    stmt.line, stmt.column
                )
                return

            # Disallow replacement assignment through references
            # References can only be modified via compound assignment (+=, -=, etc.)
            # or by calling mutating methods
            if var_info.type.kind == TypeKind.REFERENCE:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot assign through reference `{stmt.target.name}`",
                    stmt.line, stmt.column,
                    hint="use compound assignment (+=, -=, etc.) or mutating methods instead"
                )
                return

            # Check mutability
            if not var_info.mutable:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot assign to immutable variable `{stmt.target.name}`",
                    stmt.line, stmt.column,
                    hint="consider using `var` instead of `let` to make it mutable"
                )

            # Check type
            value_type = self._check_expression(stmt.value)
            if value_type and not self._types_compatible(value_type, var_info.type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to variable of type `{var_info.type}`",
                    stmt.line, stmt.column
                )

            # Value-transfer checkpoint: enforce NoCopy move-discipline and mark
            # ImplicitCopy sites for codegen. The RHS was already type-checked
            # above, so a moved var appearing in its own revival RHS is rejected
            # before we clear the target's moved-state.
            self._check_value_transfer(stmt.value, var_info.type, "assignment",
                                       stmt.line, stmt.column)
            # Revival by assignment (design 15 rule 3): assigning a fresh value
            # to a moved binding clears its moved-state.
            self._revive_binding(var_info)

        elif isinstance(stmt.target, MemberAccess):
            # Field assignment: obj.field = value
            obj_type = self._check_expression(stmt.target.object)
            if not obj_type:
                return

            # Must be a struct type
            if obj_type.kind != TypeKind.STRUCT:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot access field on non-struct type `{obj_type}`",
                    stmt.target.line, stmt.target.column
                )
                return

            # Check if field exists
            struct_info = self.get_struct_info(obj_type.struct_name)
            if not struct_info:
                return

            if stmt.target.member not in struct_info.fields:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"struct `{obj_type.struct_name}` has no field `{stmt.target.member}`",
                    stmt.target.line, stmt.target.column
                )
                return

            field_type = struct_info.fields[stmt.target.member]

            # Check value type
            value_type = self._check_expression(stmt.value)
            if value_type and not self._types_compatible(value_type, field_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to field of type `{field_type}`",
                    stmt.line, stmt.column
                )
            self._check_value_transfer(stmt.value, field_type, "field assignment",
                                       stmt.line, stmt.column)

        elif isinstance(stmt.target, ArrayIndex):
            # Array or pointer element assignment: arr[i] = value or ptr[i] = value
            container_type = self._check_expression(stmt.target.array_expr)
            if not container_type:
                return

            # Must be an array or pointer type
            if container_type.kind == TypeKind.ARRAY:
                element_type = container_type.array_element_type
                # For arrays, check binding mutability
                if isinstance(stmt.target.array_expr, Identifier):
                    var_info = self.current_scope.lookup(stmt.target.array_expr.name)
                    if var_info and not var_info.mutable:
                        self._error(
                            ErrorKind.IMMUTABLE_ASSIGNMENT,
                            f"cannot assign to element of immutable array `{stmt.target.array_expr.name}`",
                            stmt.line, stmt.column,
                            hint="consider using `var` instead of `let` to make it mutable"
                        )
            elif container_type.kind == TypeKind.POINTER:
                # For pointers, check pointer mutability (UnsafePointer vs UnsafeConstPointer)
                if not container_type.pointer_mutable:
                    self._error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot write through UnsafeConstPointer (use UnsafePointer for mutable access)",
                        stmt.line, stmt.column
                    )
                    return
                element_type = container_type.inner_type
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot index into type `{container_type}`",
                    stmt.target.line, stmt.target.column
                )
                return

            # Check index type
            index_type = self._check_expression(stmt.target.index)
            if index_type:
                index_underlying = self._get_underlying_type(index_type)
                if index_underlying.kind != TypeKind.INT:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"index must be Int, got `{index_type}`",
                        stmt.target.index.line, stmt.target.index.column
                    )

            # Check value type matches element type
            value_type = self._check_expression(stmt.value)
            if value_type and element_type:
                if not self._types_compatible(value_type, element_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot assign `{value_type}` to element of type `{element_type}`",
                        stmt.line, stmt.column
                    )
            self._check_value_transfer(stmt.value, element_type, "element assignment",
                                       stmt.line, stmt.column)

        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "invalid assignment target",
                stmt.line, stmt.column
            )

    def _check_compound_assign_statement(self, stmt: CompoundAssignStatement):
        """Check a compound assignment statement (+=, -=, *=, /=, %=).

        Compound assignment is allowed on:
        - Mutable variables (var x)
        - Mutable reference parameters (&var T)
        - Mutable struct fields (if the struct binding is mutable)
        - Mutable array elements (if the array binding is mutable)
        """
        # Get target type
        target_type = self._check_expression(stmt.target)
        if target_type is None:
            return

        # Get value type
        value_type = self._check_expression(stmt.value)
        if value_type is None:
            return

        # Check mutability based on target kind
        if isinstance(stmt.target, Identifier):
            var_info = self.current_scope.lookup(stmt.target.name)
            if not var_info:
                return

            # Check if it's a mutable reference or mutable variable
            is_mutable_ref = (var_info.type.kind == TypeKind.REFERENCE and
                             var_info.type.reference_mutable)
            if not var_info.mutable and not is_mutable_ref:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot use compound assignment on immutable variable `{stmt.target.name}`",
                    stmt.line, stmt.column,
                    hint="consider using `var` instead of `let` to make it mutable"
                )
                return

            # For references, use the inner type for operator checking
            if var_info.type.kind == TypeKind.REFERENCE:
                target_type = var_info.type.inner_type

        elif isinstance(stmt.target, MemberAccess):
            # Check if base object is mutable
            if isinstance(stmt.target.object, Identifier):
                base_info = self.current_scope.lookup(stmt.target.object.name)
                if base_info and not base_info.mutable:
                    # Check if it's a mutable reference
                    is_mutable_ref = (base_info.type.kind == TypeKind.REFERENCE and
                                     base_info.type.reference_mutable)
                    if not is_mutable_ref:
                        self._error(
                            ErrorKind.IMMUTABLE_ASSIGNMENT,
                            f"cannot use compound assignment on field of immutable variable `{stmt.target.object.name}`",
                            stmt.line, stmt.column
                        )
                        return

        elif isinstance(stmt.target, ArrayIndex):
            # Check if array is mutable
            if isinstance(stmt.target.array_expr, Identifier):
                arr_info = self.current_scope.lookup(stmt.target.array_expr.name)
                if arr_info and not arr_info.mutable:
                    is_mutable_ref = (arr_info.type.kind == TypeKind.REFERENCE and
                                     arr_info.type.reference_mutable)
                    if not is_mutable_ref:
                        self._error(
                            ErrorKind.IMMUTABLE_ASSIGNMENT,
                            f"cannot use compound assignment on element of immutable array `{stmt.target.array_expr.name}`",
                            stmt.line, stmt.column
                        )
                        return

        # Check that operator is valid for the types
        target_underlying = self._get_underlying_type(target_type)
        value_underlying = self._get_underlying_type(value_type)

        int_kinds = {
            TypeKind.INT, TypeKind.UINT,
            TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
            TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64
        }

        if stmt.op in ['+', '-', '*', '/']:
            # These work on integers and floats
            if target_underlying.kind in int_kinds and value_underlying.kind in int_kinds:
                pass  # OK
            elif target_underlying.kind == TypeKind.FLOAT and value_underlying.kind in (int_kinds | {TypeKind.FLOAT}):
                pass  # OK
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{stmt.op}=` cannot be applied to `{target_type}` and `{value_type}`",
                    stmt.line, stmt.column
                )
        elif stmt.op == '%':
            # Modulo only works on integers
            if target_underlying.kind in int_kinds and value_underlying.kind in int_kinds:
                pass  # OK
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `%=` requires integer operands, got `{target_type}` and `{value_type}`",
                    stmt.line, stmt.column
                )

    def _check_return_statement(self, stmt: ReturnStatement):
        """Check a return statement."""
        # Get expected return type from either function or method context
        if self.current_function is not None:
            expected = self.current_function.return_type
        elif self.current_method is not None:
            expected = self.current_method.return_type
        else:
            return

        if stmt.value is None:
            if expected.kind != TypeKind.VOID:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function should return `{expected}` but return has no value",
                    stmt.line, stmt.column
                )
        else:
            value_type = self._check_expression(stmt.value)
            if value_type and expected.kind == TypeKind.VOID:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function returns void but return has a value of type `{value_type}`",
                    stmt.line, stmt.column
                )
            elif value_type and not self._types_compatible(value_type, expected):
                # Check for Result auto-wrapping
                if expected.is_result() and value_type:
                    ok_type = expected.unwrap_result_ok()
                    err_type = expected.unwrap_result_err()

                    # Already a Result - no wrapping needed (but types don't match)
                    if value_type.is_result():
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"expected return type `{expected}` but got `{value_type}`",
                            stmt.line, stmt.column
                        )
                    # design 30: bare value fits both Ok and Err (T == E) - ambiguous
                    elif self._result_autowrap_ambiguous(
                            expected, value_type, "function", stmt.line, stmt.column):
                        # ambiguity reported; treat as a value-return so we don't
                        # also emit a misleading "body has no value" cascade.
                        self.found_return_with_value = True
                    # Value matches T - wrap in ResultOkWrap
                    elif self._types_compatible(value_type, ok_type):
                        stmt.value = ResultOkWrap(
                            value=stmt.value,
                            result_type=expected,
                            line=stmt.value.line,
                            column=stmt.value.column
                        )
                        self.found_return_with_value = True
                    # Value matches E - wrap in ResultErrWrap
                    elif self._types_compatible(value_type, err_type):
                        stmt.value = ResultErrWrap(
                            value=stmt.value,
                            result_type=expected,
                            line=stmt.value.line,
                            column=stmt.value.column
                        )
                        self.found_return_with_value = True
                    else:
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"expected return type `{expected}` but got `{value_type}` "
                            f"(doesn't match Ok type `{ok_type}` or Err type `{err_type}`)",
                            stmt.line, stmt.column
                        )
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"expected return type `{expected}` but got `{value_type}`",
                        stmt.line, stmt.column
                    )
            else:
                # Mark that we found a valid return statement with a value
                self.found_return_with_value = True
                # Annotate None literals with the expected type
                if value_type and value_type.is_none_literal() and expected.is_optional():
                    self._annotate_none_in_expr(stmt.value, expected)
                # Wrap T in Optional if returning from T?-returning function
                elif value_type and expected.is_optional() and not value_type.is_optional():
                    stmt.value = OptionalWrap(
                        value=stmt.value,
                        target_type=expected,
                        line=stmt.value.line,
                        column=stmt.value.column
                    )

            # Value-transfer checkpoint for explicit `return x`: unifies the
            # NoCopy move-discipline / ImplicitCopy copy rules with the implicit
            # tail-return path. Runs after any Result/Optional wrapping above so
            # a wrapped value is a fresh temporary (not aliasing).
            context_name = "function"
            if self.current_function is not None:
                context_name = f"function `{self.current_function.name}`"
            elif self.current_method is not None:
                context_name = f"method `{self.current_method.name}`"
            self._check_value_transfer(stmt.value, expected, context_name,
                                       stmt.line, stmt.column, is_return=True)

    def _check_while_expr(self, stmt: WhileExpr):
        """Check a while loop used as a statement (no return value expected)."""
        # If condition is present, it must be a Bool
        if stmt.condition:
            cond_type = self._check_expression(stmt.condition)
            if cond_type and cond_type.kind != TypeKind.BOOL:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"while condition must be Bool, got `{cond_type}`",
                    stmt.line, stmt.column
                )

        # Check body with increased loop depth but NO break type tracking
        # (statements don't need to return values)
        self.loop_depth += 1
        self._check_loop_body(stmt.body, self.current_scope)
        self.loop_depth -= 1

    def _check_while_expr_as_expression(self, expr: WhileExpr) -> Optional[SawType]:
        """Check a while loop expression and return its type."""
        # If condition is present, it must be a Bool
        if expr.condition:
            cond_type = self._check_expression(expr.condition)
            if cond_type and cond_type.kind != TypeKind.BOOL:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"while condition must be Bool, got `{cond_type}`",
                    expr.line, expr.column
                )

        is_infinite = expr.condition is None

        # Push loop info onto stack: (break_type, is_infinite, has_break)
        # break_type will be determined by the first break statement
        self.loop_break_info.append((None, is_infinite, False))

        # Check body with increased loop depth
        self.loop_depth += 1
        self._check_loop_body(expr.body, self.current_scope)
        self.loop_depth -= 1

        # Pop loop info and determine return type
        break_type, _, has_break = self.loop_break_info.pop()

        if is_infinite:
            # Infinite loop: must have at least one break with value
            if not has_break:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "infinite while loop used as expression must have at least one `break` statement",
                    expr.line, expr.column
                )
                return None
            if break_type is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "infinite while loop used as expression must `break` with a value",
                    expr.line, expr.column
                )
                return None
            # Return the break type directly (non-optional)
            expr.result_type = break_type
            return break_type
        else:
            # Conditional loop: returns Optional<break_type>
            if break_type is None:
                # No breaks with values, returns Void
                expr.result_type = SawType(TypeKind.VOID)
                return SawType(TypeKind.VOID)
            # Wrap break type in Optional
            result = SawType(TypeKind.OPTIONAL, inner_type=break_type)
            expr.result_type = result
            return result

    def _check_for_loop(self, stmt: ForLoop):
        """Check a for loop statement."""
        from .core import VariableInfo, Scope
        # Check the iterable expression
        iterable_type = self._check_expression(stmt.iterable)

        # Determine the loop variable type based on the iterable
        loop_var_type: Optional[SawType] = None

        if isinstance(stmt.iterable, RangeExpr):
            # Range expression - loop variable is Int
            loop_var_type = SawType(TypeKind.INT)
        else:
            # Check if the type implements Iterator interface
            loop_var_type = self._get_iterator_item_type(iterable_type, stmt.line, stmt.column)
            if loop_var_type is None:
                loop_var_type = SawType(TypeKind.INT)  # Default to Int on error

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add loop variable to scope (immutable by default)
        self.current_scope.define(
            stmt.variable,
            VariableInfo(loop_var_type, mutable=False, line=stmt.line, column=stmt.column)
        )

        # Check body with increased loop depth. Pass old_scope (before the loop
        # variable is bound) so moving the freshly-bound loop variable each
        # iteration is not flagged as a cross-iteration move.
        self.loop_depth += 1
        self._check_loop_body(stmt.body, old_scope)
        self.loop_depth -= 1

        # Restore scope
        self.current_scope = old_scope

    def _check_for_loop_as_expression(self, expr: ForLoop) -> Optional[SawType]:
        """Check a for loop expression and return its type (Optional<T> from break values)."""
        from .core import VariableInfo, Scope
        # Check the iterable expression
        iterable_type = self._check_expression(expr.iterable)

        # Determine the loop variable type based on the iterable
        loop_var_type: Optional[SawType] = None

        if isinstance(expr.iterable, RangeExpr):
            # Range expression - loop variable is Int
            loop_var_type = SawType(TypeKind.INT)
        else:
            # Check if the type implements Iterator interface
            loop_var_type = self._get_iterator_item_type(iterable_type, expr.line, expr.column)
            if loop_var_type is None:
                loop_var_type = SawType(TypeKind.INT)  # Default to Int on error

        # For loops are always conditional (have a finite range), so return Optional<T>
        # Push loop info onto stack: (break_type, is_infinite=False, has_break)
        self.loop_break_info.append((None, False, False))

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Add loop variable to scope (immutable by default)
        self.current_scope.define(
            expr.variable,
            VariableInfo(loop_var_type, mutable=False, line=expr.line, column=expr.column)
        )

        # Check body with increased loop depth. Pass old_scope (before the loop
        # variable is bound) so moving the freshly-bound loop variable each
        # iteration is not flagged as a cross-iteration move.
        self.loop_depth += 1
        self._check_loop_body(expr.body, old_scope)
        self.loop_depth -= 1

        # Restore scope
        self.current_scope = old_scope

        # Pop loop info and determine return type
        break_type, _, has_break = self.loop_break_info.pop()

        # For loops are conditional, so return Optional<break_type>
        if break_type is None:
            # No breaks with values, returns Void
            expr.result_type = SawType(TypeKind.VOID)
            return SawType(TypeKind.VOID)
        # Wrap break type in Optional
        result = SawType(TypeKind.OPTIONAL, inner_type=break_type)
        expr.result_type = result
        return result

    def _get_iterator_item_type(self, iterable_type: Optional[SawType], line: int, column: int) -> Optional[SawType]:
        """Get the Item type for a type that implements Iterator interface.

        Returns None if the type doesn't implement Iterator, and reports an error.
        """
        if iterable_type is None:
            return None

        # The type must be a struct
        if iterable_type.kind != TypeKind.STRUCT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"for loop requires an Iterator, got `{iterable_type}`",
                line, column,
                hint="use `for i in start..end {{ ... }}` for range iteration"
            )
            return None

        type_name = iterable_type.struct_name

        # Check if the type conforms to Iterator
        if not self.namespace.type_conforms_to(type_name, "Iterator"):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"type `{type_name}` does not implement Iterator",
                line, column,
                hint="add `extension {}: Iterator {{ type Item = ...; func next(var self) -> Item? {{ ... }} }}`".format(type_name)
            )
            return None

        # Get the Item associated type
        type_assigns = self.namespace.get_type_assignments(type_name, "Iterator")
        if "Item" not in type_assigns:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"Iterator implementation for `{type_name}` is missing associated type `Item`",
                line, column
            )
            return None

        item_type = type_assigns["Item"]

        # Substitute type parameters if the iterator type has type arguments
        if iterable_type.type_args:
            struct_info = self.get_struct_info(type_name)
            if struct_info and struct_info.type_params:
                # Build substitution map: type_param_name -> actual_type
                type_subst = {}
                for i, param in enumerate(struct_info.type_params):
                    if i < len(iterable_type.type_args):
                        type_subst[param.name] = iterable_type.type_args[i]
                # Apply substitution to Item type
                item_type = item_type.substitute(type_subst)

        return item_type

    def _check_range_expr(self, expr: RangeExpr) -> Optional[SawType]:
        """Check a range expression: start..end"""
        start_type = self._check_expression(expr.start)
        end_type = self._check_expression(expr.end)

        if start_type is None or end_type is None:
            return None

        # Both start and end must be Int
        if start_type.kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"range start must be Int, got `{start_type}`",
                expr.line, expr.column
            )

        if end_type.kind != TypeKind.INT:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"range end must be Int, got `{end_type}`",
                expr.line, expr.column
            )

        # Return a special "Range" type - for now just use VOID as placeholder
        # The for loop handles ranges specially
        return SawType(TypeKind.VOID)

    def _check_break_statement(self, stmt: BreakStatement):
        """Check a break statement."""
        if self.loop_depth == 0:
            self._error(
                ErrorKind.INVALID_BREAK_CONTINUE,
                "`break` can only be used inside a loop",
                stmt.line, stmt.column
            )
            return

        # Type check the break value if present
        value_type = None
        if stmt.value:
            value_type = self._check_expression(stmt.value)

        # Update loop break info if we're tracking it
        if self.loop_break_info:
            existing_type, is_infinite, _ = self.loop_break_info[-1]

            # Mark that we found a break
            self.loop_break_info[-1] = (existing_type or value_type, is_infinite, True)

            # If there's an existing break type, validate compatibility
            if existing_type and value_type:
                if not self._types_compatible(value_type, existing_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"break value type `{value_type}` incompatible with expected type `{existing_type}`",
                        stmt.line, stmt.column
                    )
            elif not existing_type and value_type:
                # First break with a value sets the type
                self.loop_break_info[-1] = (value_type, is_infinite, True)

    def _check_continue_statement(self, stmt: ContinueStatement):
        """Check a continue statement."""
        if self.loop_depth == 0:
            self._error(
                ErrorKind.INVALID_BREAK_CONTINUE,
                "`continue` can only be used inside a loop",
                stmt.line, stmt.column
            )

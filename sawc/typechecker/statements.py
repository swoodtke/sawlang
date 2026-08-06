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
    Identifier, MemberAccess, ArrayIndex, TupleIndex, MoveExpr, IntLiteral,
    FunctionCall, StructInit, SelfExpr, ClosureExpr,
    SawType, TypeKind,
    ResultOkWrap, ResultErrWrap, OptionalWrap,
    WildcardPattern, BindingPattern, TuplePattern,
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

    def _annotation_has_module_qualifier(self, t: SawType) -> bool:
        """Whether `t` (recursively) names a module-qualified type — a STRUCT/
        ENUM whose name contains a `.` (e.g. `shapes.Point`, `Vector<a.B>`).

        Used to gate the L18 resolve+write-back: a dotted name is always a real
        module qualification (an abstract type param / Self never contains a dot),
        so this can't disturb generic-abstract or Self annotations."""
        if t is None:
            return False
        if t.kind == TypeKind.STRUCT and t.struct_name and '.' in t.struct_name:
            return True
        if t.kind == TypeKind.ENUM and t.enum_name and '.' in t.enum_name:
            return True
        for sub in (t.type_args or []):
            if self._annotation_has_module_qualifier(sub):
                return True
        if getattr(t, 'inner_type', None) is not None and \
                self._annotation_has_module_qualifier(t.inner_type):
            return True
        for sub in (getattr(t, 'element_types', None) or []):
            if self._annotation_has_module_qualifier(sub):
                return True
        return False

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
        # A compiler-derived memberwise equals() (design 32) likewise has no
        # user body; codegen emits it field-by-field.
        if getattr(method, 'is_derived_equals', False):
            return
        # Compiler-derived lexicographic compare() / field-streaming hash()
        # (design 48): no user body; codegen emits them from the field layout.
        if getattr(method, 'is_derived_compare', False):
            return
        if getattr(method, 'is_derived_hash', False):
            return

        self.current_method = method
        self.found_return_with_value = False
        self.current_type_subst = type_subst or {}

        # design 82 Part B: a std-sourced method body reaches std internals by
        # construction — check it permissively (see _check_function).
        _saved_aaa = self.namespace.allow_all_access
        _saved_cb = getattr(self, '_checking_builtins', False)
        if self._decl_is_std_sourced(method):
            self.namespace.allow_all_access = True
            self._checking_builtins = True

        # Method-level generic type params (brief 36) join the type-param scope
        # for this body, so `U` in `func map<U>(...)` is a known abstract type
        # param inside the body (brief-24 abstract body checking then covers it
        # exactly like a struct/extension type param). Restored below.
        prev_method_type_params = getattr(self, 'current_type_params', {})
        self.current_type_params = dict(prev_method_type_params)
        for tp in (method.type_params or []):
            self.current_type_params[tp.name] = tp.bounds

        # design 22: analyze this method body as a suspend-graph node (a `deinit`
        # body and a `sync func` method are sync contexts).
        self._effect_enter_method(struct_name, method)

        # Move state is function-local (design 15): fresh per method body.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}

        # Create new scope for method
        self.current_scope = Scope()

        # Determine the Self type for this extension
        _prim_self = self._primitive_ext_self_type(struct_name)
        if _prim_self is not None:
            self_type = _prim_self
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
            # L18 (design 68): a module-qualified annotation (`p: shapes.Point`)
            # must be resolved to its simple name — otherwise the binding carries
            # the dotted `struct_name`, member access on it fails to resolve, and
            # codegen later ICEs. Resolve+write-back only when a qualifier is
            # actually present so generic/abstract param types are untouched.
            elif self._annotation_has_module_qualifier(param_type):
                param_type = self._resolve_type(param_type)
                param.type = param_type
            # Design 100: a method parameter shadowing a module-level `static`
            # is a flat error (`self` never collides with a static).
            if param.name != "self":
                self._check_shadowing(param.name, None, method.line,
                                      method.column, site="param")
            info = VariableInfo(param_type, mutable=False, line=method.line, column=method.column)
            self.current_scope.define(param.name, info)

        # Default parameter values (design 53): checked in isolation (no access
        # to other params / self), with this method's suspend node active. The
        # per-parameter concreteness guard skips the type check for any abstract
        # (`T`-typed) parameter, so a generic extension checked abstractly is safe.
        self._check_parameter_defaults(
            method.parameters, bool(method.type_params), self_type)

        # L18: strip a module qualifier from the return annotation too, writing it
        # back so codegen reads the simple name (e.g. `-> shapes.Point`).
        if self._annotation_has_module_qualifier(method.return_type):
            method.return_type = self._resolve_type(method.return_type)

        # Determine expected return type first (needed for None propagation)
        expected_return = method.return_type
        # Resolve Self in return type
        if expected_return.kind == TypeKind.SELF:
            expected_return = self_type
        if method.is_init:
            expected_return = self_type

        # design 130 trigger rule (3). `self` is deliberately NOT counted: a
        # struct holding an unsafe FIELD is itself a safe type (rule 4), so
        # receiving one is not contact — reaching THROUGH it for the field is,
        # and the body check catches exactly that. This is the granularity that
        # separates `Vector.pop` from `Vector.push`.
        saved_unsafe_contact = self._enter_unsafe_scope(
            method,
            [self._resolve_type(p.type) for p in method.parameters
             if p.name != "self" and p.type.kind != TypeKind.SELF],
            self._resolve_type(expected_return))

        # design 54: collection/array literal in return position.
        if expected_return is not None:
            resolved_ret = self._resolve_type(expected_return)
            self._stamp_return_literal_types(method.body, resolved_ret)

        # Check body
        body_type = self._check_block(method.body)

        # Propagate expected type to body for None annotation
        if expected_return.is_optional() and method.body.final_expr:
            self._propagate_optional_type(method.body.final_expr, expected_return)

        # A bare integer literal in tail-return position adopts a fixed-width
        # return type + range-checks via `_stamp_return_literal_types` (which ran
        # the central `_apply_literal_expected_type` propagation before the block
        # check, above) — design 87 subsumes the old per-position range check.

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
                    elif (self._erased_err_target(expected_return) is not None
                          and self._can_erase_to(
                              body_type, self._erased_err_target(expected_return))):
                        # Erased Result (design 56): box + Err-wrap a concrete error.
                        method.body.final_expr = self._make_erased_err_wrap(
                            method.body.final_expr, expected_return, body_type,
                            self._erased_err_target(expected_return))
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
            elif body_type is not None and method.body.final_expr and body_type.kind != TypeKind.NEVER:
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
        self.current_type_params = prev_method_type_params
        self._exit_unsafe_scope(
            method, saved_unsafe_contact,
            "init" if method.is_init else "method",
            f"{struct_name}.{method.name}" if struct_name else method.name,
            fixit=("init(...) unsafe" if method.is_init
                   else f"func {method.name}(...) unsafe"))
        self.namespace.allow_all_access = _saved_aaa
        self._checking_builtins = _saved_cb

    def _erased_err_target(self, result_type):
        """If `result_type` is `Result<T, Box<any Trait>>` (an erased Result,
        design 56), return the erased trait name; else None."""
        if result_type is None or not result_type.is_result():
            return None
        err = result_type.unwrap_result_err()
        return self.namespace._erased_trait_of(err) if err is not None else None

    def _can_erase_to(self, body_type, trait_name) -> bool:
        """Whether a concrete `body_type` conforms to `trait_name` and so may be
        erased into a `Box<any Trait>` at a return / propagation edge."""
        if body_type is None:
            return False
        if body_type.kind == TypeKind.STRUCT:
            name = body_type.struct_name
        elif body_type.kind == TypeKind.ENUM:
            name = body_type.enum_name
        else:
            return False
        return self.namespace.type_conforms_to(name, trait_name)

    def _make_erased_err_wrap(self, value_expr, result_type, body_type, trait_name):
        """Build an ErasedErrWrap: a concrete `E: <trait>` returned from an erased
        Result is boxed (Global) and wrapped as Err (design 56)."""
        from ast_nodes import ErasedErrWrap
        return ErasedErrWrap(
            value=value_expr,
            result_type=result_type,
            concrete_err=body_type,
            trait_name=trait_name,
            allocator=SawType(TypeKind.STRUCT, struct_name="GlobalAllocator"),
            line=getattr(value_expr, 'line', 0),
            column=getattr(value_expr, 'column', 0),
        )

    def _reconcile_return_type(self, func, resolved_return_type, body_type):
        """Reconcile a function body's type against its declared return type.

        Reports a mismatch, and applies Result/Optional auto-wrapping to the
        final expression where the declared return type is a concrete
        Result/Optional. Shared by the ordinary path and the generic-body
        decidable path (design 24 item 2).
        """
        if resolved_return_type.kind == TypeKind.VOID:
            return
        # A bare literal in tail-return position adopts + range-checks the
        # fixed-width return type through `_stamp_return_literal_types` (central
        # design-87 propagation, run before the body check) — the old per-position
        # range check here is subsumed.
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
                elif (self._erased_err_target(resolved_return_type) is not None
                      and self._can_erase_to(
                          body_type, self._erased_err_target(resolved_return_type))):
                    # Erased Result (design 56): a concrete `E: Error` is boxed
                    # and Err-wrapped at the return boundary (resolution 55 ->
                    # auto-wrap 30 -> ERASE 56, one sequence).
                    func.body.final_expr = self._make_erased_err_wrap(
                        func.body.final_expr, resolved_return_type, body_type,
                        self._erased_err_target(resolved_return_type))
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
        elif body_type is not None and func.body.final_expr and body_type.kind != TypeKind.NEVER:
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

    def _check_parameter_defaults(self, parameters, is_generic, self_type=None):
        """Design 53: type-check each trailing default-parameter expression in
        ISOLATION. An empty local scope is installed so a default may reference
        only module-level items (statics, free functions) — a reference to
        another parameter or to `self` resolves to `undefined variable`/`self
        outside a method`, which is exactly the "no other-param/self refs" rule.

        The default is checked against its parameter's declared type and run
        through the value-transfer checkpoint, like an explicit argument, so a
        NoCopy default construction moves in cleanly. This runs with the
        enclosing function/method's suspend node active: a suspending default
        therefore taints the callee, and a `sync` caller that fills it is
        diagnosed. The type check is skipped for a parameter whose declared type
        is not yet concrete (a generic body checked abstractly)."""
        from .core import Scope
        if not any(p.default_value is not None for p in parameters):
            return
        saved_scope = self.current_scope
        saved_moves = dict(self.moved_bindings)
        self.current_scope = Scope()
        try:
            for p in parameters:
                if p.name == "self" or p.default_value is None:
                    continue
                pt = p.type
                if pt is not None and pt.kind == TypeKind.SELF and self_type is not None:
                    pt = self_type
                expected = self._resolve_type(pt) if pt is not None else None
                # Design 87: a bare default-value literal adopts the parameter's
                # fixed-width int type (+ range check) before it is checked, so an
                # out-of-range default (`x: Int8 = 200`) is a clean error and the
                # spliced default materializes at the right width at call sites.
                self._apply_literal_expected_type(p.default_value, expected)
                at = self._check_expression(p.default_value)
                if (at is not None and expected is not None
                        and not is_generic and self._is_concrete_type(expected)
                        and not self._arg_type_ok(p.default_value, at, expected)):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"default value for parameter `{p.name}` has type `{at}` "
                        f"but the parameter is declared `{expected}`",
                        p.default_value.line, p.default_value.column,
                        hint="a default value may reference only module-level "
                             "items, never another parameter or `self`"
                    )
                self._check_value_transfer(
                    p.default_value, expected, "default parameter value",
                    p.default_value.line, p.default_value.column)
        finally:
            self.current_scope = saved_scope
            self.moved_bindings = saved_moves

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

        # design 82 Part B: a std-sourced body (e.g. a suspending std method
        # spliced into the entry AST by the coro transform) reaches std internals
        # by construction — check it permissively, like the builtin check.
        _saved_aaa = self.namespace.allow_all_access
        _saved_cb = getattr(self, '_checking_builtins', False)
        if self._decl_is_std_sourced(func):
            self.namespace.allow_all_access = True
            self._checking_builtins = True

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

        # Default parameter values (design 53): checked in isolation with this
        # function's suspend node active (so a suspending default taints callers).
        self._check_parameter_defaults(func.parameters, is_generic)

        # Create new scope for function
        self.current_scope = Scope()

        # Add parameters to scope (resolve types first)
        for param in func.parameters:
            resolved_type = self._resolve_type(param.type)
            # Design 100: a function parameter shadowing a module-level `static`
            # is a flat error (a bare use would otherwise resolve to the param).
            self._check_shadowing(param.name, None, func.line, func.column,
                                  site="param")
            info = VariableInfo(resolved_type, mutable=False, line=func.line, column=func.column)
            self.current_scope.define(param.name, info)

        # Resolve return type first (needed for None propagation)
        resolved_return_type = self._resolve_type(func.return_type)

        # design 130 trigger rule (3): does the body or signature touch an
        # unsafe type without the declaration saying so?
        saved_unsafe_contact = self._enter_unsafe_scope(
            func, [self._resolve_type(p.type) for p in func.parameters],
            resolved_return_type)

        # design 54: a collection/array literal in return position (tail or a
        # top-level `return`) gets the return type as its expected type.
        self._stamp_return_literal_types(func.body, resolved_return_type)

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
            self._exit_unsafe_scope(func, saved_unsafe_contact,
                                    "function", func.name)
            self.namespace.allow_all_access = _saved_aaa
            self._checking_builtins = _saved_cb
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
        self._exit_unsafe_scope(func, saved_unsafe_contact, "function", func.name)
        self.namespace.allow_all_access = _saved_aaa
        self._checking_builtins = _saved_cb

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

    def visit_StaticAssert(self, stmt):
        self._check_static_assert(stmt)

    def _check_static_assert(self, stmt):
        """Design 53: walk the condition so its expression annotations (e.g. the
        `Int.max` limit tag, `sizeof<T>` type args) are stamped for the codegen
        const evaluator, and surface any type error in it. The value itself is
        evaluated at codegen (where target layout is authoritative)."""
        cond_type = self._check_expression(stmt.condition)
        if (cond_type is not None and cond_type.kind
                not in (TypeKind.BOOL, TypeKind.INT)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`static_assert` condition must be `Bool`, got `{cond_type}`",
                stmt.line, stmt.column)

    def visit_LetStatement(self, stmt: LetStatement):
        self._check_let_statement(stmt)

    def visit_DestructuringLet(self, stmt):
        self._check_destructuring_let(stmt)

    def _check_destructuring_let(self, stmt):
        """Check `let (a, b) = pair` / `var (x, y) = point` (design 63 T1d).

        The pattern must be irrefutable (a tuple of bindings / wildcards / nested
        irrefutable tuples); the RHS must be a matching tuple. Destructuring
        consumes the whole source tuple (design 35 L1) and moves each component
        out into its binding; a per-position `_` discards that component."""
        value_type = self._check_expression(stmt.value)
        if value_type is None:
            return
        vt = self._resolve_type_alias(value_type)
        # Refutable patterns are illegal in an irrefutable binding.
        if not self._pattern_is_irrefutable(stmt.pattern):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "refutable pattern in `let`/`var`: only bindings, `_`, and nested "
                "tuples are allowed (literals/ranges/variants require `match`/`if let`)",
                stmt.line, stmt.column)
            return
        if vt.kind != TypeKind.TUPLE or not vt.element_types:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot destructure non-tuple value of type `{value_type}`",
                stmt.line, stmt.column)
            return
        if len(stmt.pattern.elements) != len(vt.element_types):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"tuple pattern has {len(stmt.pattern.elements)} elements but value "
                f"has {len(vt.element_types)}",
                stmt.line, stmt.column)
            return
        # Value-transfer checkpoint: the whole tuple is consumed here.
        self._check_value_transfer(stmt.value, value_type,
                                   "destructuring binding", stmt.line, stmt.column)
        # Design 100: a destructuring `let`/`var` is still a `let` — each bound
        # name may shadow only if the RHS mentions it (a visible refinement).
        for nm, nl, nc in self._pattern_binding_names(stmt.pattern):
            self._check_shadowing(nm, stmt.value, nl, nc, site="binding")
        self._define_irrefutable_bindings(stmt.pattern, value_type, stmt.mutable)

    def _pattern_binding_names(self, pattern):
        """Flatten an irrefutable/tuple/enum pattern to its (name, line, column)
        bindings (design 100). Wildcards bind nothing."""
        out = []
        if isinstance(pattern, BindingPattern):
            out.append((pattern.name, pattern.line, pattern.column))
        elif isinstance(pattern, TuplePattern):
            for e in pattern.elements:
                out.extend(self._pattern_binding_names(e))
        else:
            subs = getattr(pattern, 'subpatterns', None)
            if subs:
                for e in subs:
                    out.extend(self._pattern_binding_names(e))
        return out

    def _define_irrefutable_bindings(self, pattern, expected_type, mutable):
        """Define the bindings of an irrefutable pattern in the current scope."""
        from .core import VariableInfo
        if isinstance(pattern, WildcardPattern):
            return
        if isinstance(pattern, BindingPattern):
            info = VariableInfo(expected_type, mutable, pattern.line, pattern.column)
            if not self.current_scope.define(pattern.name, info):
                self._error(ErrorKind.DUPLICATE_VARIABLE,
                            f"variable `{pattern.name}` is already defined in this scope",
                            pattern.line, pattern.column)
            return
        if isinstance(pattern, TuplePattern):
            et = self._resolve_type_alias(expected_type)
            elems = et.element_types or []
            for sub, t in zip(pattern.elements, elems):
                self._define_irrefutable_bindings(sub, t, mutable)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._check_assign_statement(stmt)

    def visit_CompoundAssignStatement(self, stmt: CompoundAssignStatement):
        self._check_compound_assign_statement(stmt)

    def visit_ReturnStatement(self, stmt: ReturnStatement):
        self._check_return_statement(stmt)

    def visit_LendStatement(self, stmt):
        self._check_lend_statement(stmt)

    def visit_GuardLetStatement(self, stmt: GuardLetStatement):
        self._check_guard_let_statement(stmt)

    def visit_BreakStatement(self, stmt: BreakStatement):
        self._check_break_statement(stmt)

    def visit_ContinueStatement(self, stmt: ContinueStatement):
        self._check_continue_statement(stmt)

    def visit_ExpressionStatement(self, stmt: ExpressionStatement):
        # Design 122 unit D: a closure LITERAL alone in statement position is
        # never called and its value is discarded, so every statement inside it
        # silently does not run. Because `{ ... }` is always a closure (the
        # collection-literal rule), that is what a reader writing a bare block
        # for an anonymous scope gets — the one place the language quietly did
        # nothing. It is now an error naming both fixes.
        if isinstance(stmt.expression, ClosureExpr):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "closure literal is never called: `{ ... }` in statement "
                "position builds a closure and discards it, so its body does "
                "not run",
                stmt.expression.line, stmt.expression.column,
                hint="call it — `{ ... }()` — or bind it (`let f = { ... }`). "
                     "`{ ... }` is always a closure in Saw; there is no bare "
                     "block statement"
            )
            return
        self._check_expression(stmt.expression)

    def _stamp_return_literal_types(self, body, return_type):
        """Stamp `return_type` as the expected type on any collection/array
        literal in return position (design 54): the block's tail expression and
        every top-level `return <literal>`. Nested branches self-infer."""
        if body is None or return_type is None:
            return
        if getattr(body, 'final_expr', None) is not None:
            self._apply_literal_expected_type(body.final_expr, return_type)
        for stmt in getattr(body, 'statements', []):
            if isinstance(stmt, ReturnStatement) and stmt.value is not None:
                self._apply_literal_expected_type(stmt.value, return_type)

    # ------------------------------------------------------------------ #
    # Design 100 — shadowing is an error unless the new binding derives from
    # the one it shadows.
    #
    # A binding shadows when its name would ALSO resolve to a lexically
    # enclosing binding (a local/param/capture in a parent scope, or an
    # accessible module `static`). Such a shadow is legal ONLY when it is a
    # visible REFINEMENT of the old value:
    #   * main-rule sites (let/var, single-name if-let/guard-let) carry an
    #     initializer expression — a shadow is legal exactly when that
    #     initializer MENTIONS the shadowed name (any use — bare, `move x`,
    #     `x.copy()`, `f(x)`, nested — is the author's statement of intent).
    #   * flat sites (match / tuple if-let / guard-let PATTERN bindings,
    #     function params vs module statics, closure params vs enclosing
    #     locals) have no initializer to prove intent, so a shadow is always
    #     an error (patterns BIND, they do not compare — the classic footgun).
    # Same-scope redefinition stays the pre-existing DUPLICATE_VARIABLE error;
    # functions/structs/enums/traits and prelude/std names are NOT bindings
    # for this rule.
    # ------------------------------------------------------------------ #
    def _shadowed_binding_pos(self, name: str):
        """(line, column) of an ENCLOSING binding `name` would resolve to from
        the current scope's PARENT chain (or an accessible module `static`), or
        None. The current scope's own locals are excluded — a same-scope clash
        is the separate DUPLICATE_VARIABLE error, not a shadow."""
        scope = getattr(self.current_scope, 'parent', None)
        while scope is not None:
            vi = scope.lookup_local(name)
            if vi is not None:
                return (vi.line, vi.column)
            scope = scope.parent
        static_sym = self.namespace.get_static(name, self._accessor_vis_module())
        if static_sym is not None and self.namespace.is_accessible(name):
            return (static_sym.line, static_sym.column)
        return None

    def _init_mentions_name(self, node, name: str) -> bool:
        """Does the (already type-checked) initializer expression `node` contain
        any use of `name` — a bare `Identifier`, `move name`, or the same nested
        anywhere (`name.copy()`, `f(name)`, interpolation, ...)? Because the
        initializer is checked BEFORE the shadowing binding is defined, such a
        use resolves to the shadowed binding, so its presence proves intent."""
        import dataclasses
        # Within-one-walk cycle guard over physical nodes; see design 126 R2 --
        # this is not identity that outlives the traversal.
        seen = set()
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur is None or id(cur) in seen:
                continue
            if isinstance(cur, Identifier):
                if cur.name == name:
                    return True
                continue
            if isinstance(cur, MoveExpr) and cur.variable == name:
                return True
            if dataclasses.is_dataclass(cur) and not isinstance(cur, type):
                seen.add(id(cur))
                for f in dataclasses.fields(cur):
                    v = getattr(cur, f.name, None)
                    if dataclasses.is_dataclass(v) and not isinstance(v, type):
                        stack.append(v)
                    elif isinstance(v, (list, tuple)):
                        for it in v:
                            if dataclasses.is_dataclass(it) and not isinstance(it, type):
                                stack.append(it)
                            elif isinstance(it, (list, tuple)):
                                for sub in it:
                                    if (dataclasses.is_dataclass(sub)
                                            and not isinstance(sub, type)):
                                        stack.append(sub)
        return False

    def _binding_decl_location(self, line: int, column: int) -> str:
        """Render an enclosing binding's declaration site as `FILE:L:C` (the
        shadowed binding is always in the current source file — an enclosing
        local/param, or a module static of this module)."""
        import os
        sf = self._get_current_source_file()
        base = os.path.basename(sf) if sf else "<input>"
        return f"{base}:{line}:{column}"

    def _check_shadowing(self, name: str, init_expr, line: int, column: int,
                         *, site: str = "binding"):
        """Design 100 shadow check. Call at a binding-introduction site whose
        SAME-scope collision has already been ruled out. `site` is one of:
          * "binding" — a let/var or single-name if-let/guard-let: legal iff
            `init_expr` MENTIONS the shadowed name (a visible refinement).
          * "pattern" — a match / tuple if-let/guard-let pattern binding: flat
            error (patterns bind, they do not compare).
          * "param"   — a function/closure parameter: flat error (rename only).
        """
        if name == "_":
            return
        pos = self._shadowed_binding_pos(name)
        if pos is None:
            return
        if site == "binding" and init_expr is not None \
                and self._init_mentions_name(init_expr, name):
            return  # a visible refinement — legal
        where = self._binding_decl_location(pos[0], pos[1])
        if site == "pattern":
            hint = (f"patterns bind new variables, they do not compare against "
                    f"`{name}` — rename the binding")
        elif site == "param":
            hint = (f"rename the parameter — a parameter cannot derive from the "
                    f"binding it would shadow")
        else:
            hint = (f"rename it, or derive it from the original (e.g. "
                    f"`let {name} = parse(move {name})`) to make the "
                    f"redefinition explicit")
        self._error(
            ErrorKind.DUPLICATE_VARIABLE,
            f"`{name}` shadows the binding declared at {where}",
            line, column, hint=hint)

    def _check_let_statement(self, stmt: LetStatement):
        """Check a let/var statement."""
        from .core import VariableInfo
        # `let _ = expr` is a true discard (design 53 / DF1): it evaluates the
        # RHS, consumes it (the value-transfer checkpoint treats the discard as
        # the final consumer, so a NoCopy source needs `move`), and binds NOTHING
        # — `_` is unreadable and two `let _` in one scope never collide.
        if stmt.name == "_":
            value_type = self._check_expression(stmt.value)
            if stmt.type_annotation:
                resolved = self._resolve_type(stmt.type_annotation)
                if (value_type is not None and not self._types_compatible(
                        value_type, resolved, allow_literal_to_distinct=True)):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot discard `{value_type}` as `{stmt.type_annotation}`",
                        stmt.line, stmt.column)
            self._check_value_transfer(stmt.value, value_type, "discard `let _`",
                                       stmt.line, stmt.column)
            return

        # Same-scope redefinition (design 107): a prior binding of this name in
        # the CURRENT scope. Legal ONLY when the new binding DERIVES from it (its
        # initializer mentions the name) — `var data = read(); let data =
        # parse(move data)`; a non-deriving redefinition stays the pre-existing
        # duplicate-definition error. The decision is deferred until AFTER the
        # initializer is checked (below), so its bare/`move` uses resolve to the
        # OLD binding (the new one is not in scope yet).
        existing = self.current_scope.lookup_local(stmt.name)

        # Design 54: a collection/array literal RHS gets the annotation as its
        # expected type (K/V/T inference, custom allocator, Vector-vs-array)
        # BEFORE it is checked.
        if stmt.type_annotation is not None:
            self._apply_literal_expected_type(
                stmt.value, self._resolve_type(stmt.type_annotation))

        # Infer or check type
        value_type = self._check_expression(stmt.value)

        # Design 122 unit D: binding a `Void` expression produces no value, so
        # there is nothing to name. It used to type-check and then ICE in codegen
        # on `alloca(void)` with an empty reason; it is a plain type error.
        if value_type is not None and value_type.kind == TypeKind.VOID:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot bind `{stmt.name}` to an expression of type `Void` "
                f"— it produces no value",
                stmt.line, stmt.column,
                hint="call it as a statement on its own line, or write "
                     "`let _ = ...` if the point is to evaluate it and discard"
            )
            return

        # Design 107: rule on the same-scope redefinition now that the
        # initializer is checked. A derived redefinition REPLACES the old binding
        # (its own mutability); a non-deriving one is the duplicate error
        # (message unchanged). Only ADDS legality — no migration.
        if existing is not None and not self._init_mentions_name(stmt.value,
                                                                 stmt.name):
            self._error(
                ErrorKind.DUPLICATE_VARIABLE,
                f"variable `{stmt.name}` is already defined in this scope",
                stmt.line, stmt.column,
                hint=f"previous definition was at line {existing.line}"
            )
            return

        # Design 100: a let/var that shadows an ENCLOSING binding is legal only
        # when its initializer mentions the shadowed name (a visible refinement).
        # Checked AFTER the initializer so its bare uses resolved to the outer
        # binding (the new binding is not in scope yet). (A same-scope
        # redefinition was already ruled on just above; this covers a parent
        # scope, so the two never double-report.)
        self._check_shadowing(stmt.name, stmt.value, stmt.line, stmt.column,
                              site="binding")

        if stmt.type_annotation:
            # Resolve type aliases in the annotation
            resolved_type = self._resolve_type(stmt.type_annotation)
            # Write the resolved (module-qualifier-stripped) type back onto the AST
            # so codegen reads `Point`, not the dotted `shapes.Point` it cannot
            # look up — the binding's cleanup/copy classification uses this
            # annotation, so a qualified owning type would otherwise miss its
            # deinit (L18, design 68).
            stmt.type_annotation = resolved_type
            # A binding annotation is a non-parameter role (design 16/29): a
            # closure type there is escaping; the `escaping` marker is redundant.
            self._stamp_escaping_roles(resolved_type, is_param=False,
                                       report_at=(stmt.line, stmt.column))
            # Enforce the `any Trait` unsized discipline + object safety on the
            # binding annotation (design 51): a bare `let x: any Shape` is
            # rejected; `let b: Box<any Shape>` is fine.
            self._validate_existential_type(resolved_type, stmt.line, stmt.column)
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
            # design 75 (A2): flag a binding initialized as a MULTI-THREADED group
            # (`TaskGroup(threads: N)`), so a later `group.spawn(...)` into it can
            # turn on the Send-on-frames gate. The default `TaskGroup()` (and any
            # other construction) is single-threaded — gate skipped, byte-identical.
            if self._is_multithreaded_taskgroup_init(stmt.value):
                info.is_mt_group = True
            # A derived same-scope redefinition (design 107) REPLACES the old
            # binding — overwrite it directly (`define` no-ops on a name already
            # present). The fresh VariableInfo carries a new identity, so the new
            # binding starts with clean move state (`moved_bindings` keys by id).
            self.current_scope.variables[stmt.name] = info

    def _is_multithreaded_taskgroup_init(self, value) -> bool:
        """True if `value` is a `TaskGroup(threads: ...)` construction (design 75).
        The `threads:` label is the opt-in to multi-threaded execution. A custom
        init call resolves to a `StructInit` (`[resolved: init(threads)]`); a raw
        `FunctionCall` form is handled too for robustness."""
        if isinstance(value, StructInit) and value.struct_name == "TaskGroup":
            return any(fi[0] == "threads" for fi in (value.field_inits or []))
        if isinstance(value, FunctionCall) and value.name == "TaskGroup":
            return any(a.name == "threads" for a in value.arguments)
        return False

    def _check_guard_let_statement(self, stmt: GuardLetStatement):
        """Check a guard let/var statement for optional binding."""
        from .core import VariableInfo, Scope
        # Check for duplicate in current scope (single-name form only; `_` binds
        # nothing — design 111 rider — so it never collides).
        if stmt.pattern is None and stmt.name != "_":
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

        # Add the bound variable(s) to the current (outer) scope.
        # This is the key difference from if-let: the binding is available after
        # the guard on the fall-through path.
        if stmt.pattern is not None:
            # Design 100: tuple-pattern bindings BIND (no per-binding derive) —
            # a shadow of an enclosing binding is a flat error.
            for nm, nl, nc in self._pattern_binding_names(stmt.pattern):
                self._check_shadowing(nm, None, nl, nc, site="pattern")
            self._bind_optional_pattern(stmt.pattern, inner_type, stmt.mutable,
                                        stmt.line, stmt.column)
        else:
            # Design 100: `guard let x = x` (scrutinee mentions the shadowed
            # enclosing binding) stays legal by the main rule; a non-deriving
            # single-name shadow is an error.
            self._check_shadowing(stmt.name, stmt.optional_expr,
                                  stmt.line, stmt.column, site="binding")
            # Design 111 rider: `guard let _ = opt else { ... }` tests the Optional
            # and binds nothing (the payload drops immediately at codegen) — the
            # idiomatic way to consume a `Void?` optional-chain-assignment result.
            if stmt.name != "_":
                info = VariableInfo(inner_type, stmt.mutable, stmt.line, stmt.column)
                self.current_scope.define(stmt.name, info)
                # design 131: same value-read row as `if let` — see
                # `_check_payload_read`.
                self._check_payload_read(stmt.optional_expr, inner_type, stmt,
                                         "a `guard let` binding",
                                         stmt.line, stmt.column)

    def _assign_target_immutable_array(self, target):
        """If an lvalue chain indexes into an immutable fixed array, return that
        array's name; else None.

        Walks down through MemberAccess/ArrayIndex nodes. The first index into a
        `let`-bound fixed array (identifier container) is the offending write —
        mirrors the bare `a[0] = x` element-mutability rule so a field reached
        through such an element (`a[0].v = x`) is rejected the same way.
        """
        expr = target
        while True:
            if isinstance(expr, MemberAccess):
                expr = expr.object
            elif isinstance(expr, ArrayIndex):
                container = expr.array_expr
                if isinstance(container, Identifier):
                    info = self.current_scope.lookup(container.name)
                    if (info is not None and not info.mutable
                            and info.type is not None
                            and info.type.kind == TypeKind.ARRAY):
                        return container.name
                expr = container
            else:
                return None

    def _assign_target_immutable_struct_root(self, target):
        """Design 40 item 6 (L11): if a field-assignment lvalue is a chain of
        MemberAccess reaching a `let`-bound (immutable, non-`&var`) variable,
        return that variable's name; else None.

        Assigning to a field through an immutable binding
        (`let p = Point(...); p.x = 5`, nested `p.inner.x = 5`) is rejected
        just like element assignment on a `let` array. The walk stops at the
        first non-MemberAccess node: a `self` receiver (SelfExpr) is governed by
        `&self`/`&var self`, and an array-element base is handled by the array
        rule — neither is a `let`-binding question.
        """
        expr = target
        while isinstance(expr, MemberAccess):
            expr = expr.object
        if isinstance(expr, Identifier):
            info = self.current_scope.lookup(expr.name)
            if info is None or info.mutable:
                return None
            # A `&var` reference parameter is a mutable path to the callee's
            # value; an immutable `&` reference (or a plain `let`) is not.
            if (info.type is not None and info.type.kind == TypeKind.REFERENCE
                    and info.type.reference_mutable):
                return None
            return expr.name
        return None

    def _assign_target_static_root(self, target) -> Optional[str]:
        """If an assignment target's root is a module-level static, return its
        name; else None. Statics are immutable (design 41): a whole/field/element
        write to one is rejected."""
        node = target
        while True:
            if isinstance(node, Identifier):
                if (self.current_scope.lookup(node.name) is None
                        and self.namespace.get_static(
                            node.name, self._accessor_vis_module()) is not None):
                    return node.name
                return None
            if isinstance(node, MemberAccess):
                node = node.object
            elif isinstance(node, ArrayIndex):
                node = node.array_expr
            elif isinstance(node, TupleIndex):
                node = node.tuple_expr
            else:
                return None

    def _capture_write_root(self, target) -> Optional[str]:
        """If an assignment target writes into a closure's BY-VALUE capture,
        return that capture's name; else None (design 132 unit A / DF-122a).

        A closure's environment is an env of VALUES: at body entry every
        plain/`move`/`copy` capture is loaded out of the env into a fresh local,
        so a write lands on a per-call copy and is discarded when the call
        returns. Designs 71/73 ratify that env as immutable and its sharing
        (`let g = f` is a refcount bump) as semantically invisible, so making
        such a write persist is a new capture mode, not a fix — the write itself
        is what has to go.

        A name resolving inside the closure's own scope chain (its params, its
        locals, and a `&`/`&var` BORROW capture, which is defined right in the
        closure scope) is not a value capture and is untouched. Neither is a
        capture whose TYPE is a reference: the env copies the POINTER, so the
        write still reaches the caller's value. Otherwise the target must stay
        inside the captured value's own storage for the write to be lost — field
        and tuple hops and fixed-array elements do, while an index into a
        heap-backed container (`Vector`) goes through a pointer the copy shares
        and DOES persist, so those are left alone.
        """
        if not self._closure_scopes or getattr(self, 'post_transform', False):
            return None
        # Peel the target to its root binding, remembering the hops on the way
        # so we can tell an in-storage write from one that goes through a
        # pointer the env copy shares with the original.
        hops = []
        node = target
        while not isinstance(node, Identifier):
            if isinstance(node, MemberAccess):
                hops.append(node)
                node = node.object
            elif isinstance(node, TupleIndex):
                hops.append(node)
                node = node.tuple_expr
            elif isinstance(node, ArrayIndex):
                hops.append(node)
                node = node.array_expr
            else:
                return None
        name = node.name

        closure_scope = self._closure_scopes[-1]
        scope = self.current_scope
        while True:
            if scope.lookup_local(name) is not None:
                return None          # a local, a param, or a borrow capture
            if scope is closure_scope or scope.parent is None:
                break
            scope = scope.parent

        info = self.current_scope.lookup(name)
        if info is None or info.type is None:
            return None              # undefined: a different diagnostic owns it
        current = info.type
        if current.kind == TypeKind.REFERENCE:
            return None              # the copied pointer still addresses the referent

        for hop in reversed(hops):
            current = self._resolve_type_alias(current)
            if isinstance(hop, MemberAccess):
                if current.kind != TypeKind.STRUCT or current.struct_name is None:
                    return None
                struct_info = self.get_struct_info(current.struct_name)
                if struct_info is None or hop.member not in struct_info.fields:
                    return None
                current = struct_info.fields[hop.member]
            elif isinstance(hop, TupleIndex):
                elems = current.element_types or []
                if current.kind != TypeKind.TUPLE or hop.index >= len(elems):
                    return None
                current = elems[hop.index]
            else:  # ArrayIndex
                if current.kind != TypeKind.ARRAY:
                    return None      # a heap-backed container: the write persists
                current = current.array_element_type
            if current is None:
                return None
        return name

    def _reject_capture_write(self, target, line, column) -> bool:
        """Report a write to a by-value closure capture. True iff one was found."""
        name = self._capture_write_root(target)
        if name is None:
            return False
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot assign to `{name}`: it is captured by value, so the write "
            f"would be discarded when the closure returns",
            line, column,
            hint=f"capture it by borrow — `{{ [&var {name}] ... }}`, legal in a "
                 f"closure passed directly to a non-escaping parameter — or, for "
                 f"a closure that outlives the frame, share the state through an "
                 f"`Arc<Mutex<T>>`")
        return True

    def _check_assign_statement(self, stmt: AssignStatement):
        """Check an assignment statement."""
        # Statics are immutable (design 41): reject any write whose root is a
        # static — whole (`S = x`), field (`S.f = x`), or element (`S[i] = x`).
        # The rule keys on assignment; interior-mutable METHOD calls
        # (`S.fetch_add(1)`) are the sanctioned mutation path and are untouched.
        static_root = self._assign_target_static_root(stmt.target)
        if static_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign to static `{static_root}`: statics are immutable",
                stmt.line, stmt.column,
                hint="use an interior-synchronized type (e.g. `Atomic<Int>`) and "
                     "mutate through its methods"
            )
            return

        # A write to a by-value closure capture is discarded (design 132 unit A).
        if self._reject_capture_write(stmt.target, stmt.line, stmt.column):
            return

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

            # Replacement assignment through a reference (design 110).
            if var_info.type.kind == TypeKind.REFERENCE:
                self._check_ref_replacement_assign(
                    stmt, var_info.type, stmt.target.name)
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
            # Propagate an optional VARIABLE type onto a `None` RHS (mirrors the
            # let/return/field paths) so the None literal carries its inner type.
            var_resolved = self._resolve_type_alias(var_info.type)
            if (value_type and value_type.is_none_literal()
                    and var_resolved.is_optional()):
                self._propagate_optional_type(stmt.value, var_resolved)
                value_type = var_resolved
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
            # Mutability: assigning through a `let` array element
            # (`a[0].v = x`, `a[i].inner.v = x`) is rejected exactly like a bare
            # `a[0] = x` element write (design 39 item 1).
            imm_array = self._assign_target_immutable_array(stmt.target)
            if imm_array is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot assign to element of immutable array `{imm_array}`",
                    stmt.line, stmt.column,
                    hint="consider using `var` instead of `let` to make it mutable"
                )
            else:
                # Design 40 item 6 (L11): field assignment through an immutable
                # `let` (or `&`) binding is rejected, mirroring the array rule.
                imm_root = self._assign_target_immutable_struct_root(stmt.target)
                if imm_root is not None:
                    self._error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot assign to field of immutable variable `{imm_root}`",
                        stmt.line, stmt.column,
                        hint="consider using `var` instead of `let` to make it mutable"
                    )

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

            # Member visibility (design 80): a field WRITE goes through the same
            # gate as a read — this is the headline case (corrupting a private std
            # invariant like `Vector.length` from user code is now rejected).
            self._check_field_visible(struct_info, stmt.target.member,
                                      obj_type.struct_name, stmt.target)

            field_type = struct_info.fields[stmt.target.member]
            # A field WRITE resolves its type exactly like a field READ does
            # (`_check_member_access`): when the receiver is a concrete
            # instantiation of a GENERIC struct, `struct_info` is the generic
            # symbol whose fields still carry the abstract `T`, so substitute the
            # receiver's type args. Without this, `h.slot = 5` on a `Holder<Int>`
            # was rejected as "cannot assign `Int` to field of type `T?`" — every
            # field of a generic struct was effectively write-only-through-init.
            tps = getattr(struct_info, 'type_params', None)
            if tps and getattr(obj_type, 'type_args', None):
                type_map = {tp.name: arg
                            for tp, arg in zip(tps, obj_type.type_args)}
                if type_map:
                    field_type = field_type.substitute(type_map)

            # Check value type
            value_type = self._check_expression(stmt.value)
            # Propagate an optional FIELD type onto a `None` RHS so the None
            # literal carries its inner type (mirrors the let/return paths). This
            # matters for the coro transform's `self.__result = None` store into an
            # optional-encoded result field, re-checked after the transform.
            field_resolved = self._resolve_type_alias(field_type)
            if (value_type and value_type.is_none_literal()
                    and field_resolved.is_optional()):
                self._propagate_optional_type(stmt.value, field_resolved)
                value_type = field_resolved
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

        elif isinstance(stmt.target, SelfExpr):
            # Whole-receiver replacement `self = v` in a `&var self` method
            # (design 110, Swift mutating-self precedent).
            self._check_self_replacement_assign(stmt)

        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "invalid assignment target",
                stmt.line, stmt.column
            )

    def _check_ref_replacement_assign(self, stmt: AssignStatement,
                                      ref_type: SawType, name: str):
        """Design 110: whole-referent replacement `x = v` through a reference
        parameter `x`. Legal only through `&var T` (a mutable reference) whose
        referent is a STATICALLY-KNOWN type — concrete or a type parameter. The
        caller's binding is never invalidated: the RHS goes through the ordinary
        value-transfer checkpoint against the referent type, the old referent
        value deinits, and the new value installs in place (codegen)."""
        # Assignment through an immutable `&T` stays banned (its own diagnostic).
        if not ref_type.reference_mutable:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign through immutable reference `{name}`",
                stmt.line, stmt.column,
                hint="an immutable `&` reference is read-only; take `&var` to "
                     "replace the referent, or use a mutating method"
            )
            return
        referent = ref_type.inner_type
        # Erased referents are EXCLUDED (design 110 item 7): behind `&var any
        # Trait` the caller's storage is a CONCRETE type, so a differently-typed
        # store would corrupt the slot — the identical-type rule is statically
        # unsatisfiable. Point the user at the sized `Box<any Trait>` level.
        if referent is not None and referent.kind == TypeKind.EXISTENTIAL:
            tn = referent.existential_trait
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot replace the referent of `&var any {tn}` `{name}`: the "
                f"concrete type behind the erasure is unknown",
                stmt.line, stmt.column,
                hint=f"a differently-typed value would corrupt the caller's "
                     f"slot — replace at the `Box<any {tn}>` level instead "
                     f"(a `&var Box<any {tn}>` referent CAN be reassigned)"
            )
            return
        self._check_replacement_rhs(stmt, referent)

    def _check_self_replacement_assign(self, stmt: AssignStatement):
        """Design 110: `self = v` inside a `&var self` method. Rejected in a
        `&self` (immutable) method with the existing self-mutability diagnostic;
        otherwise routed through the normal replacement checkpoint against the
        receiver's (Self) type."""
        method = self.current_method
        self_mutable = method is not None and getattr(method, "self_mutable", False)
        if not self_mutable:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                "cannot assign to `self`: the receiver is immutable",
                stmt.line, stmt.column,
                hint="use `&var self` in the method signature to replace `self`"
            )
            return
        self_info = self.current_scope.lookup("self")
        referent = self_info.type if self_info is not None else None
        self._check_replacement_rhs(stmt, referent)

    def _check_replacement_rhs(self, stmt: AssignStatement, referent):
        """Shared tail for design-110 replacement assignment: type-check the RHS
        against the (sized) referent type exactly as an ordinary var assignment
        would, then run the value-transfer checkpoint. `move v` (of a callee
        local) and `.copy()` follow the ordinary transfer rules; the caller's
        object is the thing being replaced and stays valid."""
        value_type = self._check_expression(stmt.value)
        if referent is None:
            return
        # Propagate an optional referent type onto a bare `None` RHS (mirrors the
        # var/field paths) so the None literal carries its inner type.
        referent_resolved = self._resolve_type_alias(referent)
        if (value_type and value_type.is_none_literal()
                and referent_resolved.is_optional()):
            self._propagate_optional_type(stmt.value, referent_resolved)
            value_type = referent_resolved
        if value_type and not self._types_compatible(value_type, referent):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to referent of type `{referent}`",
                stmt.line, stmt.column
            )
        self._check_value_transfer(stmt.value, referent, "assignment",
                                   stmt.line, stmt.column)

    def _check_compound_assign_statement(self, stmt: CompoundAssignStatement):
        """Check a compound assignment statement (+=, -=, *=, /=, %=).

        Compound assignment is allowed on:
        - Mutable variables (var x)
        - Mutable reference parameters (&var T)
        - Mutable struct fields (if the struct binding is mutable)
        - Mutable array elements (if the array binding is mutable)
        """
        # Statics are immutable (design 41): `S += 1` and friends are rejected
        # for the same reason as a plain assignment.
        static_root = self._assign_target_static_root(stmt.target)
        if static_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign to static `{static_root}`: statics are immutable",
                stmt.line, stmt.column,
                hint="use an interior-synchronized type (e.g. `Atomic<Int>`) and "
                     "mutate through its methods"
            )
            return

        # `n += 1` on a by-value capture is the same discarded write.
        if self._reject_capture_write(stmt.target, stmt.line, stmt.column):
            return

        # Get target type
        target_type = self._check_expression(stmt.target)
        if target_type is None:
            return

        # Design 87: a bare RHS literal adopts the target's fixed-width int type
        # (`x += 1` for `x: Int8`) BEFORE it is checked — else the checked-arith
        # intrinsic sees the i8 target against an i64 literal and ICEs. A `&var
        # IntN` target unwraps to its inner type first.
        eff_target = target_type
        if (eff_target.kind == TypeKind.REFERENCE
                and eff_target.inner_type is not None):
            eff_target = eff_target.inner_type
        self._apply_literal_expected_type(stmt.value, eff_target)

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
        elif stmt.op in ['&', '|', '^', '<<', '>>']:
            # Bitwise compound assignments (design 50): integer operands only.
            if target_underlying.kind in int_kinds and value_underlying.kind in int_kinds:
                pass  # OK
            else:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"operator `{stmt.op}=` requires integer operands, got `{target_type}` and `{value_type}`",
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
            resolved_exp = self._resolve_type(expected)
            ok_of = resolved_exp.unwrap_result_ok() if resolved_exp.is_result() else None
            if ok_of is not None and ok_of.kind == TypeKind.VOID:
                # design 92: a bare `return` in a `Result<Void, E>` function is
                # the honest Ok(Void) — the successful, value-less completion of
                # a fallible-but-dataless op (net write, remove, mkdir, ...).
                stmt.value = ResultOkWrap(
                    value=None,
                    result_type=resolved_exp,
                    line=stmt.line,
                    column=stmt.column
                )
                self.found_return_with_value = True
            elif expected.kind != TypeKind.VOID:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"function should return `{expected}` but return has no value",
                    stmt.line, stmt.column
                )
        else:
            # Design 87: a bare literal (or if/match arm result) adopts a
            # fixed-width return type and is range-checked at the literal.
            self._apply_literal_expected_type(stmt.value, self._resolve_type(expected))
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
                    elif (self._erased_err_target(expected) is not None
                          and self._can_erase_to(
                              value_type, self._erased_err_target(expected))):
                        # Erased Result (design 56): box + Err-wrap a concrete error
                        # at an explicit `return E`.
                        stmt.value = self._make_erased_err_wrap(
                            stmt.value, expected, value_type,
                            self._erased_err_target(expected))
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

        # Stash the loop variable's type for codegen: an OWNING loop variable (a
        # retained element yielded by a custom iterator) must be released at the
        # end of each iteration unless it was moved out (design 65).
        stmt.element_type = loop_var_type

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Design 107 item 2: a for-loop variable joins the design-100
        # mentions-rule with the SEQUENCE expression as the initializer analog —
        # `for x in x.lines()` (the sequence references the shadowed name) is a
        # legal refinement; `for x in ys` under an outer `x` is a rename error.
        # An enclosing LOOP VAR is an enclosing binding, so a nested inner loop
        # reusing the name non-derived errors the same way. Checked with the loop
        # scope active so the shadowed binding is found on the parent chain.
        self._check_shadowing(stmt.variable, stmt.iterable, stmt.line,
                              stmt.column, site="binding")

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

        # Stash for codegen (design 65): release an owning loop variable per
        # iteration unless it is moved out.
        expr.element_type = loop_var_type

        # For loops are always conditional (have a finite range), so return Optional<T>
        # Push loop info onto stack: (break_type, is_infinite=False, has_break)
        self.loop_break_info.append((None, False, False))

        # Create new scope for loop body with loop variable
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)

        # Design 107 item 2: the for-loop variable joins the mentions-rule with
        # the SEQUENCE expression as the initializer analog (see _check_for_loop).
        self._check_shadowing(expr.variable, expr.iterable, expr.line,
                              expr.column, site="binding")

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

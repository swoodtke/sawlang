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
    ForceUnwrap,
    FunctionCall, StructInit, SelfExpr, ClosureExpr,
    IfExpr, IfLetExpr, MatchExpr, MethodCall,
    SawType, TypeKind,
    ResultOkWrap, ResultErrWrap, OptionalWrap,
    WildcardPattern, BindingPattern, TuplePattern,
)
from errors import ErrorKind


def _statement_diverges(stmt) -> bool:
    """Does control never continue PAST this statement (design 177)?

    One shape today: the conditionless `while { ... }` that nothing breaks out
    of. `panic(...)` is the other diverging construct, but it is an expression,
    so it arrives as a block's `final_expr` and is typed `Never` there.
    """
    return isinstance(stmt, WhileExpr) and stmt.diverges


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
        prev_const_params = self._enter_const_params(
            [] if specialization_key else extension.type_params)
        if not specialization_key:
            for tp in extension.type_params:
                self.current_type_params[tp.name] = tp.bounds

        try:
            for method in extension.methods:
                self._check_method(extension.struct_name, method, type_subst)
        finally:
            self.current_type_params = prev_type_params
            self.current_const_param_types = prev_const_params

    def _enter_const_params(self, type_params):
        """Bring a declaration's const VALUE parameters into scope (design 148).

        Returns the previous mapping, for the caller to restore. Types only —
        a generic body is checked once, abstractly, so `N` has a type here and
        never a value; the values arrive per instantiation, in codegen.
        """
        prev = getattr(self, 'current_const_param_types', {})
        self.current_const_param_types = dict(prev)
        for tp in (type_params or []):
            if getattr(tp, 'is_const', False):
                self.current_const_param_types[tp.name] = tp.const_type
        return prev

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
        prev_method_const_params = self._enter_const_params(method.type_params)
        for tp in (method.type_params or []):
            self.current_type_params[tp.name] = tp.bounds

        # design 22: analyze this method body as a suspend-graph node (a `deinit`
        # body and a `sync func` method are sync contexts).
        self._effect_enter_method(struct_name, method)

        # Move state is function-local (design 15): fresh per method body.
        saved_moves = self.moved_bindings
        self.moved_bindings = {}
        # So are task-capture borrows (design 189): a group is a scope, and a
        # method body is checked with none of its caller's open.
        saved_borrows, saved_pending = self._task_borrows, self._pending_task_borrows
        self._task_borrows, self._pending_task_borrows = [], []

        # Create new scope for method
        self.current_scope = Scope()

        # Determine the Self type for this extension. Design 145: an enum
        # receiver must be ENUM-kinded here or `match self` inside the body sees
        # a struct with no variants.
        _prim_self = self._primitive_ext_self_type(struct_name)
        if _prim_self is not None:
            self_type = _prim_self
        else:
            # For specialized extensions, include the type args in self_type
            type_args = list(type_subst.values()) if type_subst else None
            if (self.namespace.has_enum(struct_name)
                    and not self.namespace.has_struct(struct_name)):
                # `_ext_self_type` fills a generic enum's own type params when
                # the extension is not specialized (design 145).
                self_type = self._ext_self_type(struct_name, type_args)
            else:
                self_type = SawType(TypeKind.STRUCT, struct_name=struct_name,
                                    type_args=type_args)

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
            # codegen later ICEs. The WRITE-BACK stays conditional on a qualifier
            # actually being present, so generic/abstract param types are left as
            # the extension declared them.
            elif self._annotation_has_module_qualifier(param_type):
                param_type = self._resolve_type(param_type)
                param.type = param_type
            else:
                # The BINDING resolves either way (DF-140h). The parser gives any
                # bare named type a STRUCT kind, and only resolution knows which
                # names are enums — so without this an `r: Right` parameter
                # entered the body scope STRUCT-kinded and every enum-shaped
                # operation on it failed: `r as UInt` on a backed enum reported
                # "cannot cast `Right` to `UInt`" (design 145's cast looks for
                # ENUM kind), with a bogus "body has no value" behind it.
                # A plain function has always resolved here; an extension method
                # only did so for a qualified annotation, which is why the same
                # parameter worked in a free function and not in a method.
                param_type = self._resolve_type(param_type)
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

        if expected_return.kind == TypeKind.VOID:
            # Design 151: a `Void` method's tail expression is discarded.
            self._check_result_discard(getattr(method.body, 'final_expr', None))

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
                        # DF-140d: see through the Ok-payload optional first.
                        _payload = self._prepare_ok_payload(
                            method.body.final_expr, body_type, ok_type)
                        method.body.final_expr = ResultOkWrap(
                            value=_payload,
                            result_type=expected_return,
                            line=_payload.line,
                            column=_payload.column
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
        self._task_borrows, self._pending_task_borrows = saved_borrows, saved_pending
        self.current_type_params = prev_method_type_params
        self.current_const_param_types = prev_method_const_params
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
            # Design 151: a `Void` function's tail expression is discarded.
            self._check_result_discard(
                getattr(getattr(func, 'body', None), 'final_expr', None))
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
                    # DF-140d: see through the Ok-payload optional (bare `None`
                    # stamped, bare `T` wrapped in `Some`) before the Result wrap.
                    _payload = self._prepare_ok_payload(
                        func.body.final_expr, body_type, ok_type)
                    func.body.final_expr = ResultOkWrap(
                        value=_payload,
                        result_type=resolved_return_type,
                        line=_payload.line,
                        column=_payload.column
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

    def _wrap_optional_tail(self, func, resolved_return_type, body_type):
        """The `-> T?` tail auto-wrap, for a generic body whose return type the
        decidability rule defers (DF-174a).

        Only the wrap: a mismatch stays deferred to monomorphization, which is
        what decidability is for. A bare `None` tail is stamped instead, exactly
        as the concrete path stamps it.
        """
        tail = getattr(func.body, 'final_expr', None)
        if tail is None or body_type is None:
            return
        if not resolved_return_type.is_optional():
            return
        if body_type.is_none_literal():
            self._propagate_optional_type(tail, resolved_return_type)
            return
        if body_type.is_optional() or body_type.kind == TypeKind.NEVER:
            return
        func.body.final_expr = OptionalWrap(
            value=tail, target_type=resolved_return_type,
            line=tail.line, column=tail.column)

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
        # Task-capture borrows are function-local for the same reason (189).
        saved_borrows, saved_pending = self._task_borrows, self._pending_task_borrows
        self._task_borrows, self._pending_task_borrows = [], []

        # Track type parameters as opaque for the duration of this body. Their
        # bounds are recorded so future bound-aware method/trait lookups can use
        # them; today lookups on an opaque type parameter stay conservative.
        prev_type_params = getattr(self, 'current_type_params', {})
        self.current_type_params = dict(prev_type_params)
        prev_const_params = self._enter_const_params(func.type_params)
        for tp in func.type_params:
            self.current_type_params[tp.name] = tp.bounds

        # Default parameter values (design 53): checked in isolation with this
        # function's suspend node active (so a suspending default taints callers).
        #
        # A default is part of the SIGNATURE, so unsafe contact inside one
        # belongs to this function — but the defaults are checked out here,
        # before `_enter_unsafe_scope` below clears the slot, so any contact
        # they recorded was thrown away (design 193 unit 7). Hold it across the
        # boundary rather than moving the check: a default is checked in the
        # OUTER scope on purpose (it may not name a parameter).
        outer_contact, self._unsafe_contact = self._unsafe_contact, None
        self._check_parameter_defaults(func.parameters, is_generic)
        default_contact = self._unsafe_contact
        self._unsafe_contact = outer_contact

        # Create new scope for function
        self.current_scope = Scope()

        # Add parameters to scope (resolve types first)
        for param in func.parameters:
            resolved_type = self._resolve_type(param.type)
            # DF-140c: a module-qualified parameter type that did not resolve is
            # reported HERE, at the signature, instead of surfacing as whatever
            # the unusable parameter breaks further down.
            self._check_qualified_type_resolves(
                resolved_type, f"parameter `{param.name}`",
                func.line, func.column,
                source_file=getattr(func, 'source_file', None))
            self._check_type_name_resolves(
                resolved_type, f"parameter `{param.name}`",
                func.line, func.column,
                source_file=getattr(func, 'source_file', None))
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
        if self._unsafe_contact is None and default_contact is not None:
            self._unsafe_contact = default_contact

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
            else:
                # DF-174a. Decidability governs whether a MISMATCH can be judged
                # abstractly, and rightly defers that to monomorphization. The
                # OPTIONAL auto-wrap is a different question and is decidable
                # here: a declared `-> T?` is an optional at every instantiation
                # and a tail expression that is not itself optional is its
                # payload at every instantiation, so exactly one wrap is correct
                # for all of them — including `T = Int?`, where `Int?` wraps once
                # into `Int??`. Skipping it emitted `ret i64` against a
                # `{ i1, i64 }` result and only the LLVM verifier objected; what
                # it was catching was a missing wrap that would otherwise be a
                # type-confused read. The `return x` spelling of the same
                # function always wrapped (it never consulted decidability), and
                # so did the non-generic tail — this is the one path that did
                # not.
                self._wrap_optional_tail(func, resolved_return_type, body_type)
            self.current_type_params = prev_type_params
            self.current_const_param_types = prev_const_params
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
        self.current_const_param_types = prev_const_params
        self._effect_exit()
        self.current_function = None
        self.moved_bindings = saved_moves
        self._task_borrows, self._pending_task_borrows = saved_borrows, saved_pending
        self._exit_unsafe_scope(func, saved_unsafe_contact, "function", func.name)
        self.namespace.allow_all_access = _saved_aaa
        self._checking_builtins = _saved_cb

    def _check_block(self, block: Block) -> Optional[SawType]:
        """Check a block and return its type (from final expression)."""
        from .core import Scope
        # Create new scope for block
        old_scope = self.current_scope
        self.current_scope = Scope(parent=old_scope)
        # design 189: the borrows live on the way IN. A join that happens only
        # inside this block does not release for the code AFTER it — the other
        # path never joined — so anything that was live here comes back below.
        entry_borrows = list(self._task_borrows)

        for stmt in block.statements:
            self._check_statement(stmt)

        result_type = None
        if block.final_expr is not None:
            result_type = self._check_expression(block.final_expr)
        elif block.statements and _statement_diverges(block.statements[-1]):
            # Design 177: a block whose last STATEMENT is a diverging
            # `while { ... }` produces no value AND cannot fall out of its end,
            # which is the bottom type. A trailing `panic(...)` reaches the same
            # conclusion through `final_expr` (a call is an expression); a `while`
            # is a statement, so it needs this arm to say the same thing. It is
            # what makes `func spin() -> Never { while { } }` satisfy its
            # declaration, and what types a diverging `match`/`if` arm block.
            result_type = SawType(TypeKind.NEVER)

        # design 189: release what the groups declared here carried, and restore
        # what was live on the way in but joined only inside this block.
        self._close_task_borrow_scope(self.current_scope, entry_borrows)

        # Restore scope
        self.current_scope = old_scope

        return result_type

    def _check_statement(self, stmt: Statement):
        """Check a statement."""
        # design 189: only the statement that CONTAINS a spawn may claim the
        # borrows it opened, so the pending list never survives a statement
        # boundary. A `group.spawn(f())` written as a statement of its own
        # leaves them unclaimed, which is what "releases at group death" means.
        self._pending_task_borrows = []
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
        evaluated at codegen (where target layout is authoritative).

        DF-172j stamps the module statics the condition names in the same
        breath, for the same reason: one evaluator answers in all four
        const-required positions, so a `static REGION_SIZE` that is an array
        length must also be assertable about."""
        with self._const_position():
            cond_type = self._check_expression(stmt.condition)
        self._stamp_const_names(stmt.condition)
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
        self._check_result_discard(stmt.expression)

    # ------------------------------------------------------------------ #
    # Design 151 — discarding a `Result` is a compile error.
    #
    # A `Result` nothing consumes was the last silent drop in the language:
    # `stream.write(data)` as a bare statement threw the write's failure away
    # with no diagnostic, against the standing never-hide-errors principle and
    # design 131's rule that no status is ignorable. Every position where the
    # checker computes a value and no construct reads it routes through
    # `_check_result_discard`:
    #
    #   * an expression statement -- a bare call, and a statement-position
    #     `if` / `if let` / `match` / `try` (the parser wraps all of those in
    #     `ExpressionStatement`, so there is one site, not four);
    #   * a `Void` function or method body's tail expression (the parser turns
    #     a block's LAST expression statement into `final_expr`, so the common
    #     `func f() { g() }` shape lands here, not above);
    #   * a loop body's tail expression (`while`/`for` bodies yield only via
    #     `break v`, so the tail is dropped unconditionally);
    #   * a `guard let ... else { }` block's tail.
    #
    # Result ONLY: Optionals and everything else stay freely discardable. The
    # explicit discard is `let _ = expr`, which is checked nowhere here -- it
    # is the escape hatch the diagnostic names.
    # ------------------------------------------------------------------ #
    _RESULT_DISCARD_MAX_DEPTH = 32

    def _is_result_typed(self, node) -> bool:
        """Does this already-checked expression node carry a `Result` type?

        Resolves through a `type R = Result<...>` alias, so a named result type
        is a Result for this rule too.
        """
        t = getattr(node, 'resolved_type', None)
        if t is None:
            return False
        t = self._resolve_type_alias(t)
        return bool(t is not None and t.is_result())

    def _result_discard_culprits(self, expr):
        """The innermost expressions actually PRODUCING a discarded Result.

        A statement-position `if`/`if let`/`match` only FORWARDS its branches'
        values, so anchoring the diagnostic on the `if` would name a line that
        has nothing wrong with it. Descend through those forwarding constructs
        to the branch tails that produce the value; every other expression is
        its own culprit. A branch that diverges (`panic(...)`, type `Never`)
        contributes nothing, so it drops out naturally.

        A compiler-inserted `ResultOkWrap`/`ResultErrWrap` is skipped: the
        author wrote a non-Result there and the return-type auto-wrap made it
        one, so "you discarded a Result" would describe code nobody wrote.
        """
        out = []
        seen = set()

        def visit(node, depth):
            # Within-one-walk cycle guard over physical nodes (design 126 R2).
            if node is None or id(node) in seen or depth > self._RESULT_DISCARD_MAX_DEPTH:
                return
            seen.add(id(node))
            if isinstance(node, (ResultOkWrap, ResultErrWrap)):
                return
            if isinstance(node, (IfExpr, IfLetExpr)):
                visit(getattr(node.then_branch, 'final_expr', None), depth + 1)
                if node.else_branch is not None:
                    visit(getattr(node.else_branch, 'final_expr', None), depth + 1)
                return
            if isinstance(node, MatchExpr):
                for arm in node.arms:
                    body = arm.body
                    visit(body.final_expr if isinstance(body, Block) else body,
                          depth + 1)
                return
            if self._is_result_typed(node):
                out.append(node)

        visit(expr, 0)
        return out

    def _result_producer_name(self, node) -> str:
        """How the diagnostic refers to the expression that produced the
        Result -- its call name where there is one, else a generic phrase."""
        if isinstance(node, FunctionCall):
            return f"result of `{node.name}`"
        if isinstance(node, MethodCall):
            return f"result of `{node.method_name}`"
        return "this expression's result"

    def _check_result_discard(self, expr):
        """Design 151: report every `Result` this discarded expression drops."""
        if expr is None:
            return
        for node in self._result_discard_culprits(expr):
            t = self._resolve_type_alias(node.resolved_type)
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"{self._result_producer_name(node)} is `{t}` and is silently "
                f"discarded",
                node.line, node.column,
                hint="handle it — `match` it, `try`/`try!`/`try?` it, or "
                     "return it — or write `let _ = ...` to discard it "
                     "explicitly"
            )

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
        # Design 150 section 4b: the first `-W` category. A binding that takes a
        # module qualifier's name is LEGAL (pin 4 makes qualifiers weak), so this
        # is a warning and an opt-in one — but it is worth flagging early,
        # because the cost is invisible until a later line reaches for `time.`
        # and finds an Instant.
        self._warn_shadowed_qualifier(name, line, column)
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
        # A `T -> T?` wrap this check INSERTED on an earlier pass over the same
        # AST (the place lowering and the coroutine transform both re-enter the
        # front half). It is not idempotent as a premise: the wrap is decided
        # below by comparing the initializer's type to the annotation, and on a
        # second pass the initializer is already optional — so `let y: OptInt =
        # 100` stopped being a literal flowing into a distinct alias and became
        # an `Int?` that does not flow there at all. Peel it and decide again.
        while isinstance(stmt.value, OptionalWrap):
            stmt.value = stmt.value.value
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
            # DF-174d: a written name with type arguments that resolves to
            # nothing is reported HERE, as an unknown type, rather than as a
            # mismatch against the opaque nominal it used to become.
            self._check_type_name_resolves(
                resolved_type, f"the annotation of `{stmt.name}`",
                stmt.line, stmt.column)
            # DF-172k: an annotation is the one `[T; N]` position codegen never
            # sees, so its length is checked here or nowhere.
            self._check_declared_array_lengths(
                resolved_type, f"the annotation of `{stmt.name}`",
                stmt.line, stmt.column)
            # A binding annotation is a non-parameter role (design 16/29): a
            # closure type there is escaping; the `escaping` marker is redundant.
            self._stamp_escaping_roles(resolved_type, is_param=False,
                                       report_at=(stmt.line, stmt.column))
            # Enforce the `any Trait` unsized discipline + object safety on the
            # binding annotation (design 51): a bare `let x: any Shape` is
            # rejected; `let b: Box<any Shape>` is fine.
            self._validate_existential_type(resolved_type, stmt.line, stmt.column)
            # design 188 unit 1: and the no-escape walk with aliases resolved —
            # `let v: Vector<R>` for a `type R = &Int` is the generic-argument
            # rule reached through a binding annotation (DF-188b, audit R41).
            self._reject_laundered_reference(
                stmt.type_annotation, f"the annotation of `{stmt.name}`",
                stmt.line, stmt.column)
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
            # design 189: `let h = group.spawn(...)` — this binding is the
            # handle that carries the borrows the spawn just opened, and
            # `h.join()` is where they are released.
            self._bind_task_borrow_handle(info, stmt.name)

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
        # Design 151: a `guard let ... else { }` block's tail is discarded.
        self._check_result_discard(stmt.else_branch.final_expr)
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

        Walks down through MemberAccess/TupleIndex/ArrayIndex nodes. The first
        index into a `let`-bound fixed array (identifier container) is the
        offending write — mirrors the bare `a[0] = x` element-mutability rule so
        a field reached through such an element (`a[0].v = x`) is rejected the
        same way.
        """
        expr = target
        while True:
            if isinstance(expr, MemberAccess):
                expr = expr.object
            elif isinstance(expr, TupleIndex):
                expr = expr.tuple_expr
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
        MemberAccess/TupleIndex hops reaching a `let`-bound (immutable,
        non-`&var`) variable, return that variable's name; else None.

        Assigning to a field through an immutable binding
        (`let p = Point(...); p.x = 5`, nested `p.inner.x = 5`) is rejected
        just like element assignment on a `let` array. A TUPLE hop is one of
        these: `let t = (v, 7)` then `t.0 = fresh` or `t.0.push(x)` is the same
        write through the same `let` (DF-151j — the walk stopped at the tuple
        projection, so both went unchecked). The walk stops at the first other
        node: a `self` receiver (SelfExpr) is governed by `&self`/`&var self`,
        and an array-element base is handled by the array rule — neither is a
        `let`-binding question.
        """
        expr = target
        while True:
            if isinstance(expr, MemberAccess):
                expr = expr.object
            elif isinstance(expr, TupleIndex):
                expr = expr.tuple_expr
            else:
                break
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

    def _reject_shared_self_write(self, target, line, column, compound=False):
        """DF-175a: a WRITE into the receiver of a plain `&self` method.

        Design 146 states the rule — a field write in a `&self` body is an
        error, the prologue and epilogue of a `borrows` body included — but only
        the `&var self.<field>` PROJECTION form was ever enforced
        (`_check_reference_expr`). The DIRECT write went through, and it went
        through two different ways:

        - in a PLAIN `&self` method the receiver arrives BY VALUE, so
          `self.hits = self.hits + 1` landed in the callee's copy and was
          silently discarded — the DF-146b bug class through the door that fix
          did not cover;
        - in a `&self` BORROWS body the receiver travels by POINTER
          (`place_self_by_pointer`, which is what lets an exclusive window write
          through), so the same write LANDED: a pure read through a shared
          window mutated an immutable root, and `let` immutability stopped
          holding.

        One rule closes both. The walk is `_projects_from_self`, the same one
        the projection check uses, so `self.f = v`, `self.a.b = v`,
        `self.t.0 = v`, `self.cells[i] = v` and `self.opt! = v` all answer
        alike — and so do their compound forms.

        Returns True (and reports) when the write is rejected.
        """
        # `self = v` is design 110's whole-receiver replacement and has its own
        # diagnostic in `_check_self_replacement_assign`.
        if isinstance(target, SelfExpr):
            return False
        if not self._writes_into_self_storage(target):
            return False
        method = getattr(self, 'current_method', None)
        if method is None or getattr(method, 'self_mutable', False):
            return False
        verb = "use compound assignment on" if compound else "assign to"
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot {verb} storage reached through a `&self` receiver: "
            f"`self` is borrowed SHARED here, so the write either lands in a "
            f"copy that is discarded when the method returns or mutates a "
            f"value the caller holds immutably",
            line, column,
            hint="declare the method `&var self` to mutate through the "
                 "receiver, or `borrows -> T` to lend the place and let each "
                 "use site choose the window's flavor"
        )
        return True

    def _reject_var_self_call_on_shared_self(self, expr, method_info) -> bool:
        """A `&var self` method called on `self` — or on a FIELD of it — from
        a `&self` body.

        The second and third forms DF-175a named, and the half design 176 unit
        13 did not close: it scoped itself to the direct WRITE, so the mutation
        spelled as a method call went through — in a plain `&self` method as a
        silent no-op, and in a `&self` BORROWS body (where the receiver travels
        by pointer) as a real mutation of a `let` root through a window the use
        site opened SHARED. Both reproduce with no `#lend_var` anywhere; design
        179's shared specialization is only as trustworthy as this rule.

        TWO RECEIVER FORMS, one rule:

        - `self.reset()` (DF-179b, design 179 unit 2) — the receiver is `self`
          ITSELF, and a `&var self` method takes the WHOLE receiver
          exclusively, which is the one thing `&self` promises not to do. No
          carve-out is possible or wanted.
        - `self.cells.push(9)` (DF-176b) — the receiver is storage INSIDE the
          receiver's own value, so the push runs against the `&self` copy's
          `Vector` header and the caller sees no new element. Worse than a
          vanishing field write, because the copy and the original share a
          buffer: a push that does not reallocate writes into storage the
          caller owns while the caller's `length` stays behind.

        Which storage is "inside" is `_writes_into_self_storage`'s question,
        asked of the RECEIVER instead of a write target — so `self.cells[i]`
        (a heap element the copy shares) and `self.cancel_ptr[0]` (a pointee)
        answer alike for a call and for an assignment.

        There is no interior-mutability exemption on top of that walk any more;
        see the note below `_is_interior_mutable_type`'s former home. The calls
        it existed for — `self.n.fetch_add(1)`, a `SpinLock` field's `lock` —
        are `&self` methods and were never refused by this rule to begin with.
        """
        from ast_nodes import SelfExpr as _SelfExpr
        if not getattr(method_info, "self_mutable", False):
            return False
        if getattr(method_info, "is_init", False):
            return False
        method = getattr(self, 'current_method', None)
        if method is None or getattr(method, 'self_mutable', False):
            return False
        # A window call the PLACE lowering synthesized is not a call anyone
        # wrote: `place_uses` picks the accessor and its flavor by the design
        # 141/146 rules, and a `lend self.inner[i]` that forwards another
        # accessor's place legitimately reaches the inner `&var self`
        # specialization (design 175's composition case — the receiver of a
        # borrows body travels by pointer, so nothing is lost). Judging those
        # by the rule below would reject the forwarding shape by the NAME of a
        # method the source never mentions. The place window has its own
        # unclosed half of this bug — DF-176c — which wants its own ruling.
        if getattr(expr, 'place_lowered', False):
            return False
        receiver = getattr(expr, 'object', None)
        if isinstance(receiver, _SelfExpr):
            what = "a `&self` receiver"
        else:
            field_type = self._self_storage_type(receiver)
            if field_type is None:
                return False
            what = "storage reached through a `&self` receiver"
        if getattr(method, 'is_borrows', False) or getattr(
                method, 'place_type', None) is not None:
            hint = ("declare the accessor `&var self` — every use site then "
                    "borrows the receiver exclusively, reads included — or "
                    "gate the mutation on `#lend_var` so it runs only in the "
                    "exclusive specialization")
        else:
            hint = ("declare the method `&var self` to mutate through the "
                    "receiver, or `borrows -> T` to lend the place and let "
                    "each use site choose the window's flavor")
        self._error(
            ErrorKind.IMMUTABLE_ASSIGNMENT,
            f"cannot call `&var self` method `{expr.method_name}` on "
            f"{what}: `self` is borrowed SHARED here, so the mutation either "
            f"lands in a copy that is discarded when the method returns or "
            f"mutates a value the caller holds immutably",
            expr.line, expr.column, hint=hint)
        return True

    # DESIGN 186: the interior-mutability EXEMPTION is gone, list and all.
    #
    # `_INTERIOR_MUTABLE_TYPES = {Atomic, SpinLock, UnsafeMemory}` used to let a
    # `&var self` method on a field of one of those be called from a `&self`
    # body. Re-derived against the property, it turned out to protect nothing:
    # every blessed call in std, blade, libs and the kernel is a `&self` method
    # — `fetch_add`, `load`, `lock`, `try_lock`, and `UnsafeMemory`'s intercepted
    # accessors, which never reach method resolution at all — so the rule below
    # never fired for any of them, then or now.
    #
    # Widening it to the cell-carrying property was the tempting move and is the
    # one design 186 rules OUT. A `&var self` method takes the WHOLE receiver
    # exclusively, sibling fields included, which is the one thing `&self`
    # promises not to do; that a cell-carrying receiver arrives by pointer means
    # the write LANDS, not that the exclusivity claim is honest. The refusal is
    # about the second half of its own message — "mutates a value the caller
    # holds immutably" — and it is right for `SpinLock` exactly as it is right
    # for a user wrapper.
    #
    # What a cell-carrying type gets instead is the thing it actually needs:
    # `&self` methods that WRITE, which is what the cell is for. Pinned by
    # `examples/errors/interior_cell_wrapper_var_self.saw`.

    def _writes_into_self_storage(self, target) -> bool:
        """Does this lvalue name storage INSIDE the receiver's own value?

        The predicate half of `_self_storage_type` — see there for the rule.
        """
        return self._self_storage_type(target) is not None

    def _self_storage_type(self, target):
        """The TYPE of storage inside the receiver's own value, or None.

        The distinction that matters for DF-175a is where the bytes live, not
        what the expression is rooted at. A struct FIELD, a nested field, a
        tuple element, an optional payload and a FIXED-array element are all
        inside the receiver — a `&self` copy takes them with it, so a write
        there is the vanishing (or, by pointer, the sound-breaking) one.

        Storage reached through an INDIRECTION is not: `self.cancel_ptr[0]`
        writes the pointee, which lives in a task cell the group owns, and
        `self.buffer![i]` writes a heap block the copy merely shares. Those are
        exactly the writes std's handle types make on purpose, and the reason
        this walk tracks TYPES rather than reusing `_projects_from_self`'s
        purely syntactic one — an `ArrayIndex` continues the walk only when its
        container is an inline `[T; N]`.

        Bare `self` yields the RECEIVER's own type: the walk took no hop, so
        the storage in hand is the whole receiver. Callers that must tell that
        case apart (DF-176b's field form does) test for `SelfExpr` first.
        """
        hops = []
        node = target
        while True:
            if isinstance(node, SelfExpr):
                break
            if isinstance(node, MemberAccess):
                hops.append(node)
                node = node.object
            elif isinstance(node, TupleIndex):
                hops.append(node)
                node = node.tuple_expr
            elif isinstance(node, ForceUnwrap):
                hops.append(node)
                node = node.expr
            elif isinstance(node, ArrayIndex):
                hops.append(node)
                node = node.array_expr
            else:
                return None

        self_info = self.current_scope.lookup("self")
        current = self_info.type if self_info is not None else None
        for hop in reversed(hops):
            current = self._hop_type(current, hop)
            if current is None:
                return None
        return current

    def _hop_type(self, container, hop):
        """The type one lvalue hop yields, or None when the hop leaves the
        receiver's own storage (or cannot be resolved without side effects)."""
        if container is None:
            return None
        container = self._resolve_type_alias(container)
        if container.kind == TypeKind.REFERENCE and container.inner_type:
            container = self._resolve_type_alias(container.inner_type)

        if isinstance(hop, ForceUnwrap):
            return (container.inner_type
                    if container.kind == TypeKind.OPTIONAL else None)

        if isinstance(hop, ArrayIndex):
            # Only an inline fixed array keeps the walk inside the receiver.
            return (container.array_element_type
                    if container.kind == TypeKind.ARRAY else None)

        if isinstance(hop, TupleIndex):
            if container.kind != TypeKind.TUPLE:
                return None
            elements = container.element_types or []
            if hop.index < 0 or hop.index >= len(elements):
                return None
            return elements[hop.index]

        # MemberAccess: a struct field, or a named-tuple element by label.
        if container.kind == TypeKind.TUPLE:
            names = container.tuple_field_names or []
            elements = container.element_types or []
            if hop.member in names and len(names) == len(elements):
                return elements[names.index(hop.member)]
            return None
        if container.kind != TypeKind.STRUCT or not container.struct_name:
            return None
        struct_info = self.get_struct_info(container.struct_name)
        if struct_info is None or hop.member not in struct_info.fields:
            return None
        field_type = struct_info.fields[hop.member]
        tps = getattr(struct_info, 'type_params', None)
        if tps and getattr(container, 'type_args', None):
            type_map = {tp.name: arg
                        for tp, arg in zip(tps, container.type_args)}
            if type_map:
                field_type = field_type.substitute(type_map)
        return field_type

    def _assign_target_static_root(self, target) -> Optional[str]:
        """If an assignment target's root is an IMMUTABLE module-level static,
        return its name; else None.

        An immutable static rejects a whole/field/element write (design 41). An
        `unsafe static var` (design 149) is what a write is FOR, so it is not
        reported here — naming it already made the writing function `unsafe`
        through the trigger rule, which is where the review happens.
        """
        node = target
        while True:
            if isinstance(node, Identifier):
                if self.current_scope.lookup(node.name) is not None:
                    return None
                sym = self.namespace.get_static(
                    node.name, self._accessor_vis_module())
                if sym is not None and not getattr(sym, 'is_var', False):
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

    def _mutable_static_symbol(self, name: str):
        """The StaticSymbol for `name` if it is an `unsafe static var` visible
        here and not shadowed by a local binding; else None (design 149)."""
        if self.current_scope.lookup(name) is not None:
            return None
        sym = self.namespace.get_static(name, self._accessor_vis_module())
        if sym is None or not getattr(sym, 'is_var', False):
            return None
        return sym

    def _check_static_var_assign(self, stmt, static_sym) -> None:
        """Check `MUTABLE_STATIC = value` (design 149 unit a).

        Naming the static is what makes the writing function `unsafe`, so the
        contact is recorded here — the target of an assignment does not go
        through the identifier read path that records it everywhere else.
        """
        target_type = static_sym.type
        # Codegen reads the place's type off the node (a static has no entry in
        # its variable tables) and its symbol off the same stamp every read site
        # writes.
        stmt.target.resolved_type = target_type
        if static_sym.mangled_name:
            stmt.target.resolved_static_symbol = static_sym.mangled_name
        self._note_unsafe_static_contact(stmt.target.name, stmt.target)
        self._apply_literal_expected_type(stmt.value, target_type)
        value_type = self._check_expression(stmt.value)
        resolved = self._resolve_type_alias(target_type) if target_type else None
        if (value_type is not None and resolved is not None
                and value_type.is_none_literal() and resolved.is_optional()):
            self._propagate_optional_type(stmt.value, resolved)
            value_type = resolved
        if (value_type is not None and target_type is not None
                and not self._types_compatible(value_type, target_type)):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to static "
                f"`{stmt.target.name}` of type `{target_type}`",
                stmt.line, stmt.column
            )
        self._check_value_transfer(stmt.value, target_type, "assignment",
                                   stmt.line, stmt.column)

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

    def _check_task_borrow_write(self, target, line: int, column: int) -> None:
        """Refuse a write whose root a spawned task is borrowing (design 189).

        The root is what a capture charges, so `p.field = v` and `v[i] = x`
        collide with a borrow of `p`/`v` exactly as a whole-binding write does —
        the same "a place borrow charges its ROOT" rule design 146 wrote for
        windows, read over the task's extent.
        """
        if not self._task_borrows:
            return
        path = self._build_access_path(target)
        if path is None:
            return
        borrow = self._task_borrow_for_name(path[0], writes=True)
        if borrow is not None:
            self._report_task_borrow(borrow, 'write', line, column,
                                     root=path[0])

    def _check_assign_statement(self, stmt: AssignStatement):
        """Check an assignment statement."""
        # An immutable static rejects any write whose root is it — whole
        # (`S = x`), field (`S.f = x`), or element (`S[i] = x`) (design 41). The
        # rule keys on assignment; interior-mutable METHOD calls
        # (`S.fetch_add(1)`) are the sanctioned mutation path and are untouched.
        static_root = self._assign_target_static_root(stmt.target)
        if static_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign to static `{static_root}`: statics are immutable",
                stmt.line, stmt.column,
                hint="use an interior-synchronized type (`Atomic<Int>`, "
                     "`SpinLock<T>`) and mutate through its methods, or declare "
                     "it `unsafe static var` and own the serialization argument"
            )
            return

        # design 149: a whole-value write to an `unsafe static var`. A static is
        # not a scope binding, so the Identifier path below would call it
        # undefined; and the write needs no destruction of the old value, which
        # is what v1's trivially-destructible restriction buys.
        if isinstance(stmt.target, Identifier):
            mutable_static = self._mutable_static_symbol(stmt.target.name)
            if mutable_static is not None:
                self._check_static_var_assign(stmt, mutable_static)
                return

        # A write to a by-value closure capture is discarded (design 132 unit A).
        if self._reject_capture_write(stmt.target, stmt.line, stmt.column):
            return

        # A write through a `&self` receiver is discarded, or worse (DF-175a).
        if self._reject_shared_self_write(stmt.target, stmt.line, stmt.column):
            return

        # design 189: writing a root a spawned task borrows — shared or
        # exclusive, since a writer excludes both. Asked before the target's
        # subexpressions are checked so the diagnostic names the WRITE rather
        # than the read of the path it happens to walk through.
        self._check_task_borrow_write(stmt.target, stmt.line, stmt.column)

        # design 193 unit 4: the Law of Exclusivity between the written path and
        # the right-hand side, asked ONCE here rather than in each of the target
        # shapes below. The optional-chain spelling of the same statement has
        # been asking it since design 111.
        self._check_assign_rhs_exclusivity(stmt)

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

            # NAMED-TUPLE element write `pair.x = v` (DF-151j). The label names a
            # position, so this is the whole-element write `pair.0 = v` under its
            # other spelling — not a struct field, which is why it used to die on
            # the non-struct error below with no way to say what the author meant.
            obj_resolved = self._resolve_type_alias(obj_type)
            if (obj_resolved.kind == TypeKind.TUPLE
                    and obj_resolved.tuple_field_names
                    and stmt.target.member in obj_resolved.tuple_field_names
                    and obj_resolved.element_types):
                idx = obj_resolved.tuple_field_names.index(stmt.target.member)
                stmt.target.tuple_field_index = idx  # stamp for codegen
                self._check_tuple_element_assign(
                    stmt, obj_resolved.element_types[idx])
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

        elif isinstance(stmt.target, TupleIndex):
            # WHOLE-ELEMENT TUPLE WRITE `t.0 = fresh` (DF-151j). A tuple index is
            # a place like a struct field, so it takes the same mutability
            # questions in the same order — an immutable array element on the
            # way down, then an immutable `let`/`&` root — before the value side.
            imm_array = self._assign_target_immutable_array(stmt.target)
            if imm_array is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot assign to element of immutable array `{imm_array}`",
                    stmt.line, stmt.column,
                    hint="consider using `var` instead of `let` to make it mutable"
                )
            else:
                imm_root = self._assign_target_immutable_struct_root(stmt.target)
                if imm_root is not None:
                    self._error(
                        ErrorKind.IMMUTABLE_ASSIGNMENT,
                        f"cannot assign to element of immutable variable `{imm_root}`",
                        stmt.line, stmt.column,
                        hint="consider using `var` instead of `let` to make it mutable"
                    )

            tuple_type = self._check_expression(stmt.target.tuple_expr)
            if not tuple_type:
                return
            tuple_resolved = self._resolve_type_alias(tuple_type)
            if tuple_resolved.kind != TypeKind.TUPLE:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot index into non-tuple type `{tuple_type}`",
                    stmt.target.line, stmt.target.column
                )
                return
            elements = tuple_resolved.element_types or []
            if stmt.target.index < 0 or stmt.target.index >= len(elements):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"tuple index {stmt.target.index} out of range for tuple "
                    f"with {len(elements)} elements",
                    stmt.target.line, stmt.target.column
                )
                return
            self._check_tuple_element_assign(stmt, elements[stmt.target.index])

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
                # design 141: `v[i] = x` through a `[]` borrows accessor is the
                # WHOLE-ELEMENT write. The place names the element's storage, so
                # the assignment happens inside an exclusive window and replaces
                # the element in place — set semantics, and the overwritten
                # element deinits exactly once.
                place_type = None
                if container_type.kind == TypeKind.STRUCT:
                    place_type = self._check_place_index(stmt.target,
                                                         container_type)
                if place_type is None:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot index into type `{container_type}`",
                        stmt.target.line, stmt.target.column
                    )
                    return
                # `_check_place_use` returns the place's type — `T`, or `T?`
                # when the accessor lends CONDITIONALLY — and stamps the
                # element type it lends either way. Reading the return value and
                # stripping an optional off it confuses the two: on a
                # `Vector<Int?>` the lend is unconditional and `Int?` IS the
                # element, so the strip made the write expect an `Int` and say
                # so (DF-174e: ``cannot assign `Int?` to element of type
                # `Int` ``, naming a type the container does not have — while
                # `v.set(i, value)` accepted the same value). The stamp answers
                # the question directly.
                element_type = getattr(stmt.target, 'place_elem_type', None)
                if element_type is None:
                    element_type = place_type

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

            # Check value type matches element type. The element type is an
            # EXPECTED type for the value, so a bare literal adopts its width
            # here exactly as it does at a `let`, a parameter or a plain
            # assignment (DF-165b). Without this an `v[i] = 7` into a
            # `Vector<UInt8>` left the literal at platform `Int` and reached
            # codegen as a `store i64` into an `i8*` — an internal compiler
            # error on a line with nothing wrong with it, and no range check on
            # the literal either.
            self._apply_literal_expected_type(stmt.value, element_type)
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

        elif isinstance(stmt.target, (ForceUnwrap, MethodCall)):
            # design 176: the two PLACE spellings on the write side.
            # `m[k]! = v` (DF-146n) writes the whole value through a forced
            # conditional lend and panics on an absent key; `c.slot(1) = 99`
            # (DF-175d) is the same write through a NAMED accessor. Both are the
            # element write `v[i] = fresh` already was, reached by another
            # spelling — the use-site lowering turns each into an exclusive
            # window over the place and the assignment becomes the window's body.
            self._check_place_target_assign(stmt)

        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "invalid assignment target",
                stmt.line, stmt.column
            )

    def _check_place_target_assign(self, stmt: AssignStatement):
        """`m[k]! = v` / `c.slot(i) = v`: a whole-value write through a place.

        The target must BE a place — checking it is what stamps the accessor
        annotations the use-site lowering reads. Anything else that parses here
        (`f() = 1`, `o! = 1` on a plain optional local) is refused by name.
        """
        target = stmt.target
        subject = target.expr if isinstance(target, ForceUnwrap) else target
        self._check_expression(subject)
        if not getattr(subject, 'place_struct', None):
            if isinstance(target, ForceUnwrap):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    "`!` is an assignment target only on a place — a `borrows` "
                    "accessor's conditional lend, such as `m[k]! = v`",
                    stmt.line, stmt.column,
                    hint="to replace the payload of an ordinary optional, "
                         "assign the optional itself (`o = v` wraps)")
            else:
                name = getattr(target, 'method_name', 'that call')
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{name}` does not lend a place, so it cannot be assigned to",
                    stmt.line, stmt.column,
                    hint="declare it `borrows -> T` to lend storage the caller "
                         "may write through")
            return
        if isinstance(target, ForceUnwrap) and not getattr(
                subject, 'place_optional', False):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                "this accessor always lends, so there is nothing for `!` to "
                "unwrap — write the assignment without it",
                stmt.line, stmt.column)
            return
        element_type = getattr(subject, 'place_elem_type', None)
        # Root mutability is not asked here. The write opens an EXCLUSIVE window,
        # the use-site lowering stamps that on the synthesized accessor call, and
        # the re-check refuses an immutable root by name — the same path
        # `v[i] = fresh` already takes.
        self._apply_literal_expected_type(stmt.value, element_type)
        value_type = self._check_expression(stmt.value)
        if value_type is not None and element_type is not None:
            if not self._types_compatible(value_type, element_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot assign `{value_type}` to place of type "
                    f"`{element_type}`",
                    stmt.line, stmt.column)
        self._check_value_transfer(stmt.value, element_type, "place assignment",
                                   stmt.line, stmt.column)

    def _check_tuple_element_assign(self, stmt: AssignStatement,
                                    element_type: SawType):
        """Value side of a whole-element tuple write (DF-151j) — `t.0 = fresh`
        and its named spelling `pair.x = fresh`.

        The same three steps the field path takes: propagate the element's
        optional type onto a bare `None` RHS so the literal carries its inner
        type, check assignability, and take the ordinary value-transfer
        checkpoint against the ELEMENT's type (so an ExplicitCopy/NoCopy RHS
        must `move`/`.copy()` exactly as it must into a field). The overwritten
        element's drop is codegen's half: the slot always holds a live value, so
        the old element deinits exactly once before the new one lands.
        """
        stmt.target.resolved_type = element_type
        value_type = self._check_expression(stmt.value)
        elem_resolved = self._resolve_type_alias(element_type)
        if (value_type and value_type.is_none_literal()
                and elem_resolved.is_optional()):
            self._propagate_optional_type(stmt.value, elem_resolved)
            value_type = elem_resolved
        if value_type and not self._types_compatible(value_type, element_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot assign `{value_type}` to tuple element of type "
                f"`{element_type}`",
                stmt.line, stmt.column
            )
        self._check_value_transfer(stmt.value, element_type,
                                   "tuple element assignment",
                                   stmt.line, stmt.column)

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
        # An immutable static rejects `S += 1` and friends for the same reason as
        # a plain assignment (design 41). An `unsafe static var` takes one.
        static_root = self._assign_target_static_root(stmt.target)
        if static_root is not None:
            self._error(
                ErrorKind.IMMUTABLE_ASSIGNMENT,
                f"cannot assign to static `{static_root}`: statics are immutable",
                stmt.line, stmt.column,
                hint="use an interior-synchronized type (`Atomic<Int>`, "
                     "`SpinLock<T>`) and mutate through its methods, or declare "
                     "it `unsafe static var` and own the serialization argument"
            )
            return

        # `n += 1` on a by-value capture is the same discarded write.
        if self._reject_capture_write(stmt.target, stmt.line, stmt.column):
            return

        # `self.hits += 1` in a `&self` method is the same discarded write
        # (DF-175a) — the plain-assignment form asks the same question.
        if self._reject_shared_self_write(stmt.target, stmt.line, stmt.column,
                                          compound=True):
            return

        # design 189: `n += 1` is a write of `n` like any other.
        self._check_task_borrow_write(stmt.target, stmt.line, stmt.column)

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
            # Check that the chain's ROOT binding is mutable. This used to look
            # only at an Identifier base, so a hop of any kind hid the question:
            # `p.inner.x += 1` and — once a tuple index became a place —
            # `t.0.n += 1` on a `let` root went unchecked (DF-151j). The walk is
            # the one plain assignment already uses, so `p.inner.x += 1` and
            # `p.inner.x = v` now agree.
            imm_root = self._assign_target_immutable_struct_root(stmt.target)
            if imm_root is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot use compound assignment on field of immutable variable `{imm_root}`",
                    stmt.line, stmt.column
                )
                return

        elif isinstance(stmt.target, TupleIndex):
            # `t.0 += 1` — the same root question a field compound assignment
            # asks (DF-151j).
            imm_root = self._assign_target_immutable_struct_root(stmt.target)
            if imm_root is not None:
                self._error(
                    ErrorKind.IMMUTABLE_ASSIGNMENT,
                    f"cannot use compound assignment on element of immutable variable `{imm_root}`",
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
            elif (value_type is not None and value_type.is_none_literal()
                  and self._resolve_type(expected).is_result()):
                # DF-140d: a bare `None` is compatible with EVERY type by the
                # none-literal rule, so `not _types_compatible(...)` was False and
                # the auto-wrap chain below never ran at all — codegen then met a
                # raw None where a Result was expected ("None literal has no type
                # information"). Route it explicitly.
                _res = self._resolve_type(expected)
                _ok = _res.unwrap_result_ok()
                if _ok is not None and _ok.is_optional():
                    _payload = self._prepare_ok_payload(stmt.value, value_type, _ok)
                    stmt.value = ResultOkWrap(
                        value=_payload, result_type=_res,
                        line=_payload.line, column=_payload.column)
                    self.found_return_with_value = True
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"cannot return `None` from a function returning "
                        f"`{expected}`: its Ok type `{_ok}` is not an optional",
                        stmt.line, stmt.column,
                        hint="return an `Err(...)` for the failure case, or "
                             "declare the Ok type as an optional"
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
                        # DF-140d: `Result<T?, E>` needs the payload wrapped into
                        # the Optional FIRST — a bare `None` stamped with the Ok
                        # type, a bare `T` wrapped in `Some` — or the Result wrap
                        # receives something the wrong shape and ICEs.
                        _payload = self._prepare_ok_payload(
                            stmt.value, value_type, ok_type)
                        stmt.value = ResultOkWrap(
                            value=_payload,
                            result_type=expected,
                            line=_payload.line,
                            column=_payload.column
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

        # A statement-position loop yields no value, but it still has to know
        # whether anything BREAKS out of it: design 177 makes a conditionless
        # loop that nothing breaks out of a diverging expression. Pushing an
        # entry also keeps a `break` in this loop from being attributed to an
        # enclosing expression-position loop — every `break` writes to
        # `loop_break_info[-1]`, so without a frame of its own an inner
        # statement loop's break would set the OUTER loop's break type.
        is_infinite = stmt.condition is None
        self.loop_break_info.append((None, is_infinite, False))
        self.loop_depth += 1
        self._check_loop_body(stmt.body, self.current_scope)
        self.loop_depth -= 1
        _, _, has_break = self.loop_break_info.pop()
        stmt.diverges = is_infinite and not has_break

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
            # Design 177: nothing breaks out of a conditionless loop, so control
            # never takes its exit edge — the loop DIVERGES. It types `Never`,
            # the same bottom type `panic(...)` produces, which is what lets a
            # `-> Never` function body be one (and satisfies any other declared
            # return type, since Never flows to everything). The `while true
            # { ... }` spelling is deliberately excluded: it carries a condition,
            # so it takes the conditional path below and keeps its old typing.
            if not has_break:
                expr.diverges = True
                never = SawType(TypeKind.NEVER)
                expr.result_type = never
                return never
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

"""
Resource management utilities for the Saw code generator.

This module provides mixin methods for handling resource cleanup, including:
- Determining cleanup behavior for types (Deinit, ImplicitCopy, NoCopy)
- Generating deinit calls for proper destruction
- Generating copy calls for ImplicitCopy types
- Managing scope-based cleanup for deterministic resource management

Usage:
    class CodeGenerator(ResourcesMixin, ...):
        pass
"""

from typing import Optional, List
from ast_nodes import SawType, TypeKind, MoveExpr, Identifier, MemberAccess


class ResourcesMixin:
    """Mixin providing resource management methods for CodeGenerator.

    Methods:
        _get_type_name_for_conformance: Get canonical name for interface lookup
        _get_cleanup_behavior: Determine how a type should be cleaned up
        _needs_cleanup: Check if a type requires cleanup
        _generate_deinit_call: Generate deinit() call for a variable
        _generate_copy: Generate copy() call for ImplicitCopy types
        _needs_copy_for_struct_init: Check if struct field init needs copy
        _cleanup_scope: Clean up variables in a scope
        _cleanup_all_scopes: Clean up all scopes (for early return)
    """

    def _get_type_name_for_conformance(self, saw_type: SawType) -> Optional[str]:
        """Get the type name for conformance lookup.

        Returns the canonical name used to look up interface conformances.
        For generic instantiations, includes mangled type arguments.
        """
        if saw_type.kind == TypeKind.STRUCT:
            if saw_type.type_args:
                # Generic instantiation: Box<Int> -> Box$Int
                args = "_".join(self._get_type_name_for_conformance(arg) or "unknown"
                               for arg in saw_type.type_args)
                return f"{saw_type.struct_name}${args}"
            return saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                args = "_".join(self._get_type_name_for_conformance(arg) or "unknown"
                               for arg in saw_type.type_args)
                return f"{saw_type.enum_name}${args}"
            return saw_type.enum_name
        return None

    def _get_cleanup_behavior(self, saw_type: SawType) -> str:
        """Determine cleanup behavior for a type.

        Returns one of:
        - 'none': No special cleanup needed (plain types)
        - 'deinit': Type implements Deinit (or ExplicitCopy, which has a deinit
          and is never implicitly copied), call deinit() on drop
        - 'implicit_copy': Type implements ImplicitCopy, call copy() on copy
        - 'no_copy': Type implements NoCopy, cannot be copied

        Results are cached in self.type_cleanup_behavior.
        """
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return "none"

        # Check cache
        if type_name in self.type_cleanup_behavior:
            return self.type_cleanup_behavior[type_name]

        # Check conformances (use namespace)
        conformances = self.namespace.get_conformances(type_name)

        if "NoCopy" in conformances:
            behavior = "no_copy"
        elif "ImplicitCopy" in conformances:
            behavior = "implicit_copy"
        elif "ExplicitCopy" in conformances:
            # ExplicitCopy has a deinit and is never implicitly copied (the
            # typechecker enforces `move`/`.copy()` at transfer sites), so for
            # codegen it behaves like a plain Deinit type: run deinit on drop.
            behavior = "deinit"
        elif "Deinit" in conformances:
            behavior = "deinit"
        else:
            behavior = "none"

        self.type_cleanup_behavior[type_name] = behavior
        return behavior

    def _needs_cleanup(self, saw_type: SawType) -> bool:
        """Check if a type needs cleanup (implements Deinit, ImplicitCopy, or NoCopy)."""
        return self._get_cleanup_behavior(saw_type) != "none"

    def _generate_deinit_call(self, var_name: str, saw_type: SawType):
        """Generate a call to deinit() for a variable.

        Called during scope cleanup for types that implement Deinit.
        The deinit method receives a pointer to the variable (var self).
        """
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return

        deinit_method_name = self._mangle_method_name(type_name, "deinit")

        if deinit_method_name not in self.functions:
            # No deinit method found - this shouldn't happen if type tracking is correct
            return

        deinit_fn = self.functions[deinit_method_name]
        var_ptr = self.variables.get(var_name)
        if var_ptr is None:
            return

        # deinit takes var self (pointer)
        self.builder.call(deinit_fn, [var_ptr])

    def _generate_copy(self, value, saw_type: SawType):
        """Generate a copy of a value, calling copy() for ImplicitCopy types.

        Returns the copied value (which may be the original for non-ImplicitCopy types).

        For ImplicitCopy types, calls the copy(self) -> Self method.
        For regular types, returns the original value (bitwise copy).
        For NoCopy types, raises an error (should be caught by typechecker).
        """
        behavior = self._get_cleanup_behavior(saw_type)

        if behavior == "no_copy":
            # NoCopy types cannot be copied - this should be caught by typechecker
            raise ValueError(f"Cannot copy NoCopy type: {saw_type}")

        if behavior != "implicit_copy":
            # Regular types just use the value as-is (bitwise copy)
            return value

        # ImplicitCopy: call the copy() method
        type_name = self._get_type_name_for_conformance(saw_type)
        if type_name is None:
            return value

        copy_method_name = self._mangle_method_name(type_name, "copy")

        if copy_method_name not in self.functions:
            # No copy method found - fall back to bitwise copy
            return value

        copy_fn = self.functions[copy_method_name]

        # copy(self) takes self by value (immutable), returns Self
        return self.builder.call(copy_fn, [value], name="copy_result")

    def _gen_transfer_value(self, value_expr):
        """Generate a value being transferred into a new home (call argument,
        return value, aggregate element), honoring the typechecker's
        `needs_copy` annotation.

        The value-transfer checkpoint marks `expr.needs_copy = True` on any
        ImplicitCopy value read out of an existing binding, so codegen invokes
        `copy()` uniformly at every transfer site instead of re-deciding per
        site.
        """
        value = self._generate_expression(value_expr)
        if getattr(value_expr, 'needs_copy', False):
            value = self._generate_copy(value, self._expr_type(value_expr))
        return value

    def _needs_copy_for_struct_init(self, value_expr, field_type: SawType) -> bool:
        """Check if a value expression needs copy() called during struct initialization.

        We need to call copy() when:
        1. The field type implements ImplicitCopy
        2. The value comes from an existing variable (Identifier) or field access (MemberAccess)

        We don't need copy() for:
        - Fresh struct/enum construction (new values don't need copying)
        - Literals (they don't have existing ownership)
        - Move expressions (ownership is transferred)
        """
        # Check if the field type implements ImplicitCopy
        behavior = self._get_cleanup_behavior(field_type)
        if behavior != "implicit_copy":
            return False

        # Check if the value comes from an existing binding that needs copying

        if isinstance(value_expr, MoveExpr):
            # Move expressions transfer ownership, no copy needed
            return False

        if isinstance(value_expr, Identifier):
            # Identifier refers to an existing variable - needs copy
            return True

        if isinstance(value_expr, MemberAccess):
            # Member access (e.g., self.field) - needs copy
            return True

        # Fresh construction (struct init, enum init, literals) doesn't need copy
        return False

    def _cleanup_scope(self, scope_vars: List[tuple[str, SawType]]):
        """Generate cleanup code for all variables in a scope.

        Variables are cleaned up in reverse declaration order to ensure
        proper destruction semantics (LIFO). Moved variables are skipped
        since their ownership has been transferred.
        """
        for var_name, saw_type in reversed(scope_vars):
            # Skip moved variables - ownership has been transferred
            if var_name in self.moved_variables:
                continue
            if var_name in self.variables:
                self._generate_deinit_call(var_name, saw_type)

    def _cleanup_all_scopes(self):
        """Generate cleanup code for all scopes (for early return).

        Called before return statements to ensure all in-scope variables
        are properly cleaned up.
        """
        for scope_vars in reversed(self.cleanup_stack):
            self._cleanup_scope(scope_vars)

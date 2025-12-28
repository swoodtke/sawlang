"""
Type utility methods for the Saw type checker.

This module provides mixin methods for type resolution, compatibility checking,
and resource management interface detection (NoCopy, CustomCopy, Deinit).

Usage:
    class TypeChecker(TypeUtilsMixin, ...):
        pass
"""

from typing import Optional
from ast_nodes import (
    SawType, TypeKind,
    Expression, Identifier, MoveExpr, IntLiteral, Block
)
from errors import ErrorKind


class TypeUtilsMixin:
    """Mixin providing type utility methods for TypeChecker.

    Methods:
        _resolve_type_alias: Resolve type aliases in a SawType
        _resolve_type: Resolve user-defined types (enums parsed as structs)
        _get_underlying_type: Get underlying primitive type for distinct types
        _types_compatible: Check if two types are compatible
        _is_no_copy_type: Check if type implements NoCopy
        _is_custom_copy_type: Check if type implements CustomCopy
        _is_deinit_type: Check if type implements Deinit
        _check_no_copy_return: Validate NoCopy types are moved when returned
        _check_integer_literal_range: Validate integer literal fits target type
        _check_no_copy_containment: Check structs with NoCopy fields implement NoCopy
        _check_custom_copy_containment: Check structs with CustomCopy fields implement CustomCopy
        _check_deinit_containment: Check structs with Deinit fields implement Deinit
    """

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve any type aliases in a SawType."""
        if saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type alias
            if saw_type.struct_name in self.type_aliases:
                return self.type_aliases[saw_type.struct_name]
            # Recursively resolve type_args
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
            return saw_type
        elif saw_type.kind == TypeKind.OPTIONAL:
            if saw_type.inner_type:
                resolved_inner = self._resolve_type_alias(saw_type.inner_type)
                return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
            return saw_type
        elif saw_type.kind == TypeKind.TUPLE:
            if saw_type.element_types:
                resolved_elems = [self._resolve_type_alias(t) for t in saw_type.element_types]
                return SawType(TypeKind.TUPLE, element_types=resolved_elems)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
            return saw_type
        else:
            return saw_type

    def _resolve_type(self, saw_type: SawType) -> SawType:
        """Resolve user-defined types (ENUMs parsed as STRUCT). Does NOT resolve type aliases."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Check if this is actually an enum (NOT a type alias - those stay as STRUCT)
            if saw_type.struct_name in self.enums:
                return SawType(TypeKind.ENUM, enum_name=saw_type.struct_name)
            # Recursively resolve type args
            if saw_type.type_args:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=saw_type.struct_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            # Recursively resolve optional inner types
            resolved_inner = self._resolve_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            # Recursively resolve tuple element types
            resolved_elements = [self._resolve_type(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elements)
        elif saw_type.kind == TypeKind.ENUM and saw_type.type_args:
            # Recursively resolve enum type args
            resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Recursively resolve function param and return types
            resolved_params = [self._resolve_type(t) for t in (saw_type.param_types or [])]
            resolved_return = self._resolve_type(saw_type.func_return_type) if saw_type.func_return_type else None
            return SawType(TypeKind.FUNCTION, param_types=resolved_params, func_return_type=resolved_return)
        return saw_type

    def _get_underlying_type(self, saw_type: SawType) -> SawType:
        """Get the underlying primitive type for a type (resolves type aliases).
        Used for checking if operations are valid on distinct types."""
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            # Resolve type alias to underlying type
            if saw_type.struct_name in self.type_aliases:
                return self._get_underlying_type(self.type_aliases[saw_type.struct_name])
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            resolved_inner = self._get_underlying_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        return saw_type

    def _types_compatible(self, a: Optional[SawType], b: Optional[SawType],
                          allow_literal_to_distinct: bool = False) -> bool:
        """Check if two types are compatible.

        Args:
            a: The source type (what we have)
            b: The target type (what we expect)
            allow_literal_to_distinct: If True, allows primitive types to initialize distinct types.
                                       Only pass True for let/var initialization context.
        """
        if a is None or b is None:
            return True  # Assume compatible if we couldn't determine types

        # None literal is compatible with any optional
        if a.is_none_literal() and b.is_optional():
            return True
        if b.is_none_literal() and a.is_optional():
            return True

        # None literal is compatible with any type that can be wrapped in optional
        # This allows: if cond { value } else { None } to work
        if b.is_none_literal() or a.is_none_literal():
            return True

        # Allow implicit wrapping: T is compatible with T?
        if b.is_optional() and not a.is_optional():
            if self._types_compatible(a, b.unwrap_optional(), allow_literal_to_distinct):
                return True

        # Check if b is a distinct type (STRUCT with name in type_aliases)
        if b.is_struct() and b.struct_name in self.type_aliases:
            # Allow primitive types to initialize distinct type wrappers
            # Only in initialization context (allow_literal_to_distinct=True)
            if allow_literal_to_distinct:
                underlying = self._get_underlying_type(b)
                if a.is_primitive():
                    if a.kind == underlying.kind:
                        return True
                    # Also handle distinct optional types: OptInt = Int?
                    # Allow Int to be implicitly wrapped into OptInt
                    if underlying.is_optional() and underlying.inner_type:
                        if a.kind == underlying.inner_type.kind:
                            return True
            # Always allow if 'a' is the same distinct type
            if a.is_struct() and a.struct_name == b.struct_name:
                return True

        # Allow integer literal (INT) to be compatible with any integer type
        # This enables: let x: Int8 = 42
        int_kinds = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                     TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
        if a.kind in int_kinds and b.kind in int_kinds:
            return True

        # Allow String to be passed where UnsafePointer<Int8> is expected (for FFI)
        # Saw strings are null-terminated C strings internally
        if (a.kind == TypeKind.STRING and
            b.kind == TypeKind.POINTER and
            b.inner_type and b.inner_type.kind == TypeKind.INT8):
            return True

        if a.kind != b.kind:
            return False

        # For tuple types, check element types match
        if a.is_tuple():
            if a.element_types is None or b.element_types is None:
                return True
            if len(a.element_types) != len(b.element_types):
                return False
            return all(self._types_compatible(at, bt)
                      for at, bt in zip(a.element_types, b.element_types))

        # For struct types, check struct names match
        if a.is_struct():
            if a.struct_name == b.struct_name:
                return True
            # Check if b is an interface that a conforms to
            if b.struct_name in self.interfaces:
                # a must be a struct that conforms to interface b
                if a.struct_name in self.type_conformances:
                    return b.struct_name in self.type_conformances[a.struct_name]
            return False

        # For enum types, check enum names match
        if a.is_enum():
            return a.enum_name == b.enum_name

        # For optional types, check inner types match
        if a.is_optional():
            if a.inner_type is None or b.inner_type is None:
                return True
            return self._types_compatible(a.inner_type, b.inner_type)

        # For function types, check param types and return type match
        if a.is_function():
            a_params = a.param_types or []
            b_params = b.param_types or []
            if len(a_params) != len(b_params):
                return False
            for ap, bp in zip(a_params, b_params):
                if not self._types_compatible(ap, bp):
                    return False
            return self._types_compatible(a.func_return_type, b.func_return_type)

        return True

    def _is_no_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements NoCopy (cannot be copied)."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to NoCopy
        conformances = self.type_conformances.get(type_name, [])
        return "NoCopy" in conformances

    def _is_custom_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements CustomCopy."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to CustomCopy
        conformances = self.type_conformances.get(type_name, [])
        return "CustomCopy" in conformances

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/CustomCopy)."""
        if saw_type is None:
            return False

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name

        if type_name is None:
            return False

        # Check if type conforms to Deinit (directly or via NoCopy/CustomCopy)
        conformances = self.type_conformances.get(type_name, [])
        # NoCopy and CustomCopy both inherit from Deinit
        return "Deinit" in conformances or "NoCopy" in conformances or "CustomCopy" in conformances

    def _check_no_copy_return(self, return_type: SawType, final_expr: Optional[Expression],
                               context_name: str, line: int, column: int):
        """Check that NoCopy types are moved when returned, not copied.

        If a function/method returns a NoCopy type and the return expression
        is a variable reference, it must be wrapped in `move` to avoid
        implicit copying followed by deinit of the original.
        """
        if final_expr is None:
            return

        # Check if return type is NoCopy
        if not self._is_no_copy_type(return_type):
            return

        # If the expression is a MoveExpr, that's fine
        if isinstance(final_expr, MoveExpr):
            return

        # If the expression is an Identifier (variable reference), it needs move
        if isinstance(final_expr, Identifier):
            self.reporter.error(
                ErrorKind.CANNOT_COPY,
                f"cannot return NoCopy type `{return_type}` without `move` in {context_name}",
                line, column,
                hint=f"use `move {final_expr.name}` to transfer ownership"
            )

    def _check_integer_literal_range(self, literal: IntLiteral, target_type: SawType):
        """Check if an integer literal fits in the target fixed-width integer type."""
        # Define ranges for each fixed-width integer type
        ranges = {
            TypeKind.INT8: (-128, 127),
            TypeKind.INT16: (-32768, 32767),
            TypeKind.INT32: (-2147483648, 2147483647),
            TypeKind.INT64: (-9223372036854775808, 9223372036854775807),
            TypeKind.UINT8: (0, 255),
            TypeKind.UINT16: (0, 65535),
            TypeKind.UINT32: (0, 4294967295),
            TypeKind.UINT64: (0, 18446744073709551615),
        }

        if target_type.kind not in ranges:
            return  # Not a fixed-width type, no range check needed

        min_val, max_val = ranges[target_type.kind]
        if literal.value < min_val or literal.value > max_val:
            type_name = target_type.kind.name
            self.reporter.error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {literal.value} out of range for {type_name} ({min_val} to {max_val})",
                literal.line, literal.column
            )

    def _check_no_copy_containment(self):
        """Check that structs containing NoCopy fields also implement NoCopy."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements NoCopy
            if struct_name in self.type_conformances:
                if "NoCopy" in self.type_conformances[struct_name]:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_no_copy_type(field_type):
                    self.reporter.error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains NoCopy field `{field_name}` of type `{field_type}` but does not implement NoCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: NoCopy {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_custom_copy_containment(self):
        """Check that structs containing CustomCopy fields also implement CustomCopy."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements CustomCopy or NoCopy
            # (NoCopy types can contain CustomCopy fields since they can't be copied anyway)
            if struct_name in self.type_conformances:
                conformances = self.type_conformances[struct_name]
                if "CustomCopy" in conformances or "NoCopy" in conformances:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_custom_copy_type(field_type):
                    self.reporter.error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains CustomCopy field `{field_name}` of type `{field_type}` but does not implement CustomCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: CustomCopy {{ func copy(self) -> {struct_name} {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_deinit_containment(self):
        """Check that structs containing Deinit fields also implement Deinit."""
        for struct_name, struct_info in self.structs.items():
            # Skip if struct already implements Deinit (or NoCopy/CustomCopy which imply Deinit)
            if struct_name in self.type_conformances:
                conformances = self.type_conformances[struct_name]
                if "Deinit" in conformances or "NoCopy" in conformances or "CustomCopy" in conformances:
                    continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_deinit_type(field_type):
                    self.reporter.error(
                        ErrorKind.TYPE_MISMATCH,
                        f"struct `{struct_name}` contains Deinit field `{field_name}` of type `{field_type}` but does not implement Deinit",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: Deinit {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

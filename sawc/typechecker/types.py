"""
Type utility methods for the Saw type checker.

This module provides mixin methods for type resolution, compatibility checking,
and resource management trait detection (NoCopy, ImplicitCopy, Deinit).

Usage:
    class TypeChecker(TypeUtilsMixin, ...):
        pass
"""

from typing import Optional, Tuple
from ast_nodes import (
    SawType, TypeKind,
    Expression, Identifier, MoveExpr, ReferenceExpr, IntLiteral, Block,
    MemberAccess, ArrayIndex, TupleIndex
)
from errors import ErrorKind
from namespace import (
    SymbolKind, StructSymbol, EnumSymbol, FunctionSymbol, TraitSymbol, TypeAliasSymbol
)


class TypeUtilsMixin:
    """Mixin providing type utility methods for TypeChecker.

    Methods:
        get_struct_info: Lookup struct info via namespace
        get_enum_info: Lookup enum info via namespace
        get_function_info: Lookup function info via namespace
        get_trait_info: Lookup trait info via namespace
        _resolve_type_alias: Resolve type aliases in a SawType
        _resolve_type: Resolve user-defined types (enums parsed as structs)
        _get_underlying_type: Get underlying primitive type for distinct types
        _types_compatible: Check if two types are compatible
        _is_no_copy_type: Check if type implements NoCopy
        _is_implicit_copy_type: Check if type implements ImplicitCopy
        _is_deinit_type: Check if type implements Deinit
        _check_no_copy_return: Validate NoCopy types are moved when returned
        _check_integer_literal_range: Validate integer literal fits target type
        _check_no_copy_containment: Check structs with NoCopy fields implement NoCopy
        _check_implicit_copy_containment: Check structs with ImplicitCopy fields implement ImplicitCopy
        _check_deinit_containment: Check structs with Deinit fields implement Deinit
    """

    # =========================================================================
    # Namespace Lookup Helpers
    # =========================================================================

    def get_struct_info(self, name: str, qualified_path: str = None, from_type: 'SawType' = None) -> Optional[StructSymbol]:
        """Lookup struct info via namespace, supporting qualified names.

        Args:
            name: Simple struct name (e.g., "Point")
            qualified_path: Optional module-qualified path (e.g., "toml.TomlDoc")
            from_type: Optional SawType that may contain a direct symbol reference

        Returns:
            StructSymbol if found, None otherwise
        """
        # First check if the type has a direct symbol reference (for module-qualified types)
        if from_type is not None:
            symbol = getattr(from_type, 'symbol', None)
            if symbol and symbol.kind == SymbolKind.STRUCT:
                return symbol
        if qualified_path:
            # Module-qualified lookup: "toml.TomlDoc"
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.STRUCT:
                return symbol
        # Local lookup
        result = self.namespace.lookup_struct(name)
        if result:
            return result
        # Search imported modules (for types that lost symbol during substitution)
        for module_sym in self.namespace.modules.values():
            if module_sym.namespace:
                struct_sym = module_sym.namespace.lookup_struct(name)
                if struct_sym:
                    return struct_sym
        return None

    def get_enum_info(self, name: str, qualified_path: str = None, from_type: 'SawType' = None) -> Optional[EnumSymbol]:
        """Lookup enum info via namespace, supporting qualified names.

        Args:
            name: Simple enum name (e.g., "Color")
            qualified_path: Optional module-qualified path (e.g., "colors.Color")
            from_type: Optional SawType that may contain a direct symbol reference

        Returns:
            EnumSymbol if found, None otherwise
        """
        # First check if the type has a direct symbol reference (for module-qualified types)
        if from_type is not None:
            symbol = getattr(from_type, 'symbol', None)
            if symbol and symbol.kind == SymbolKind.ENUM:
                return symbol
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.ENUM:
                return symbol
        # Local lookup
        result = self.namespace.lookup_enum(name)
        if result:
            return result
        # Search imported modules (for types that lost symbol during substitution)
        for module_sym in self.namespace.modules.values():
            if module_sym.namespace:
                enum_sym = module_sym.namespace.lookup_enum(name)
                if enum_sym:
                    return enum_sym
        return None

    def get_function_info(self, name: str, qualified_path: str = None) -> Optional[FunctionSymbol]:
        """Lookup function info via namespace, supporting qualified names.

        Args:
            name: Simple function name (e.g., "main")
            qualified_path: Optional module-qualified path (e.g., "utils.helper")

        Returns:
            FunctionSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.FUNCTION:
                return symbol
        return self.namespace.lookup_function(name)

    def get_trait_info(self, name: str, qualified_path: str = None) -> Optional[TraitSymbol]:
        """Lookup trait info via namespace, supporting qualified names.

        Args:
            name: Simple trait name (e.g., "Iterator")
            qualified_path: Optional module-qualified path (e.g., "traits.Iterator")

        Returns:
            TraitSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.TRAIT:
                return symbol
        return self.namespace.lookup_trait(name)

    def get_type_alias_info(self, name: str, qualified_path: str = None) -> Optional[TypeAliasSymbol]:
        """Lookup type alias info via namespace, supporting qualified names.

        Args:
            name: Simple type alias name (e.g., "MyInt")
            qualified_path: Optional module-qualified path

        Returns:
            TypeAliasSymbol if found, None otherwise
        """
        if qualified_path:
            symbol = self.namespace.resolve(qualified_path, check_access=False)
            if symbol and symbol.kind == SymbolKind.TYPE_ALIAS:
                return symbol
        return self.namespace.lookup_type_alias(name)

    def get_method_info(self, struct_name: str, method_name: str,
                        spec_key: Tuple[str, ...] = None) -> Optional[FunctionSymbol]:
        """Lookup method info via namespace, supporting specialized methods.

        Args:
            struct_name: The struct name (e.g., "Point")
            method_name: The method name (e.g., "distance")
            spec_key: Optional tuple of type args for specialized methods

        Returns:
            FunctionSymbol if found, None otherwise
        """
        # First check specialized methods if a spec_key is provided
        if spec_key:
            specialized = self.namespace.lookup_specialized_method(struct_name, spec_key, method_name)
            if specialized:
                return specialized
        # Fall back to regular method lookup
        return self.namespace.lookup_method(struct_name, method_name)

    # =========================================================================
    # Type Resolution Methods
    # =========================================================================

    def _resolve_type_alias(self, saw_type: SawType) -> SawType:
        """Resolve any type aliases in a SawType."""
        if saw_type.kind == TypeKind.STRUCT:
            # Check if this is actually a type alias
            alias_sym = self.get_type_alias_info(saw_type.struct_name)
            if alias_sym:
                return alias_sym.aliased_type
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
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args, symbol=saw_type.symbol)
            return saw_type
        else:
            return saw_type

    def _resolve_type(self, saw_type: SawType) -> SawType:
        """Resolve user-defined types (ENUMs parsed as STRUCT).

        NOTE: Does NOT resolve type aliases because `type X = Y` creates a distinct type
        in Saw, not a transparent alias. Use _resolve_type_alias() when you need to
        check the underlying type structure (e.g., to check if something is Optional).
        """
        if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name:
            struct_name = saw_type.struct_name

            # Handle module-qualified types (e.g., lib.Point, mod.lib.Color)
            if '.' in struct_name:
                parts = struct_name.split('.')
                simple_name = parts[-1]
                module_parts = parts[:-1]

                # Walk the module path to find the final namespace
                current_ns = self.namespace
                for part in module_parts:
                    module_sym = current_ns.modules.get(part)
                    if module_sym and module_sym.namespace:
                        current_ns = module_sym.namespace
                    else:
                        current_ns = None
                        break

                if current_ns:
                    symbol = current_ns.resolve(
                        simple_name, check_visibility=True, accessor_module=self.namespace.module_path
                    )
                    if symbol:
                        resolved_args = [self._resolve_type(t) for t in saw_type.type_args] if saw_type.type_args else None
                        if symbol.kind == SymbolKind.STRUCT:
                            return SawType(TypeKind.STRUCT, struct_name=simple_name, type_args=resolved_args, symbol=symbol)
                        elif symbol.kind == SymbolKind.ENUM:
                            return SawType(TypeKind.ENUM, enum_name=simple_name, type_args=resolved_args, symbol=symbol)

            # Check if this is actually an enum (NOT a type alias - those stay as STRUCT)
            # Use get_enum_info which searches imported modules
            enum_symbol = self.get_enum_info(struct_name, from_type=saw_type)
            if enum_symbol:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args] if saw_type.type_args else None
                return SawType(TypeKind.ENUM, enum_name=struct_name, type_args=resolved_args, symbol=enum_symbol)
            # Recursively resolve type args
            if saw_type.type_args:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=struct_name, type_args=resolved_args)
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
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args, symbol=saw_type.symbol)
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
            alias_sym = self.get_type_alias_info(saw_type.struct_name)
            if alias_sym:
                return self._get_underlying_type(alias_sym.aliased_type)
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

        # Allow type alias to implicitly convert to its underlying type
        # e.g., UserId -> Int is allowed, but Int -> UserId is not (except for literals)
        # Also handles chained aliases: SuperInt -> MyInt -> BaseInt -> Int
        if a.is_struct() and self.get_type_alias_info(a.struct_name):
            underlying_a = self._resolve_type_alias(a)
            # If b is also a type alias, check if they resolve to the same underlying type
            if b.is_struct() and self.get_type_alias_info(b.struct_name):
                underlying_b = self._resolve_type_alias(b)
                if self._types_compatible(underlying_a, underlying_b, allow_literal_to_distinct):
                    return True
            # Otherwise check if a's underlying type is compatible with b
            if self._types_compatible(underlying_a, b, allow_literal_to_distinct):
                return True

        # Check if b is a distinct type (STRUCT with name in type_aliases)
        if b.is_struct() and self.get_type_alias_info(b.struct_name):
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
        int_kinds = {TypeKind.INT, TypeKind.UINT,
                     TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                     TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
        if a.kind in int_kinds and b.kind in int_kinds:
            return True

        # Allow String to be passed where UnsafePointer<Int8> is expected (for FFI)
        # Saw strings are null-terminated C strings internally
        if (a.kind == TypeKind.STRING and
            b.kind == TypeKind.POINTER and
            b.inner_type and b.inner_type.kind == TypeKind.INT8):
            return True

        # Handle generic enums which can be parsed as STRUCT but typed as ENUM
        # (Parser creates GenericEnum<T> as STRUCT, typechecker returns ENUM)
        a_name = a.enum_name if a.kind == TypeKind.ENUM else (a.struct_name if a.kind == TypeKind.STRUCT else None)
        b_name = b.enum_name if b.kind == TypeKind.ENUM else (b.struct_name if b.kind == TypeKind.STRUCT else None)
        if a_name and b_name and a_name == b_name:
            # Same named type - check if it's an enum and compare type arguments
            if self.namespace.has_enum(a_name):
                a_args = a.type_args or []
                b_args = b.type_args or []
                if len(a_args) != len(b_args):
                    return False
                if len(a_args) == 0:
                    return True  # Non-generic enum, names match
                return all(self._types_compatible(at, bt)
                          for at, bt in zip(a_args, b_args))

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
            # Check if b is a trait that a conforms to
            if self.namespace.has_trait(b.struct_name):
                # a must be a struct that conforms to trait b
                return self.namespace.type_conforms_to(a.struct_name, b.struct_name)
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
        return self.namespace.type_conforms_to(type_name, "NoCopy")

    def _is_implicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements ImplicitCopy."""
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

        # Check if type conforms to ImplicitCopy
        return self.namespace.type_conforms_to(type_name, "ImplicitCopy")

    def _is_explicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements ExplicitCopy (move-only, deep .copy())."""
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

        # Check if type conforms to ExplicitCopy
        return self.namespace.type_conforms_to(type_name, "ExplicitCopy")

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/ImplicitCopy/ExplicitCopy)."""
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

        # Check if type conforms to Deinit (directly or via NoCopy/ImplicitCopy/ExplicitCopy)
        # NoCopy, ImplicitCopy and ExplicitCopy all inherit from Deinit
        return (self.namespace.type_conforms_to(type_name, "Deinit") or
                self.namespace.type_conforms_to(type_name, "NoCopy") or
                self.namespace.type_conforms_to(type_name, "ImplicitCopy") or
                self.namespace.type_conforms_to(type_name, "ExplicitCopy"))

    # Expression kinds that read a value out of *existing* owned storage,
    # as opposed to producing a freshly constructed temporary. Transferring
    # one of these leaves a live second owner behind, so these are exactly the
    # sites where NoCopy move-discipline must be enforced and ImplicitCopy
    # `copy()` must be inserted. A struct/enum init, call result, or literal is
    # a fresh temporary and is *not* aliasing.
    _ALIASING_EXPR_TYPES = (Identifier, MemberAccess, ArrayIndex, TupleIndex)

    def _is_aliasing_expr(self, expr: Expression) -> bool:
        """True if `expr` reads a value out of existing owned storage."""
        return isinstance(expr, self._ALIASING_EXPR_TYPES)

    def _check_value_transfer(self, expr: Optional[Expression], target_type: Optional[SawType],
                              context: str, line: int, column: int,
                              is_return: bool = False, track_move: bool = False):
        """Single checkpoint every copy/move site funnels through.

        Every site where a value is copied or moved into a new home (let/var
        initializers, assignment RHS, call arguments, returns, struct-field
        initializers, array/tuple elements, enum payloads) routes through here.
        It enforces NoCopy move-discipline and marks ImplicitCopy sites so codegen
        inserts `copy()` uniformly.

        Behavior by the source expression and its resolved type:
        - `move x`: ownership transfers; a transfer is neither a copy nor a
          NoCopy violation, so it is always accepted. The source binding is
          recorded as moved-from only when `track_move` is set (see below).
        - by-reference argument (`&x` / `&var x`): NOT a transfer; skipped.
        - NoCopy type read from an existing binding (identifier / field access /
          index): an error -- it must be `move`d. A fresh temporary is fine.
        - ImplicitCopy type read from an existing binding: annotated
          `expr.needs_copy = True` for codegen. A fresh temporary is fine.
        - anything else: no-op.

        `track_move` is only set by the sites that already recorded moved-from
        state before this checkpoint existed (let/var and assignment). The
        moved-variable set is a single flat set with no per-scope/branch
        lifetime, so recording moves at *every* transfer site (e.g. call
        arguments) would spuriously poison later same-named bindings across
        functions. Extending use-after-move to the new sites needs real
        dataflow analysis, which is explicitly out of scope for this package
        (see designs/03-value-transfer-checkpoint.md); the gap is noted there.
        """
        if expr is None:
            return

        # `move x` transfers ownership; a move is never a copy/NoCopy violation.
        if isinstance(expr, MoveExpr):
            if track_move:
                self.moved_variables.add(expr.variable)
            return

        # `&x` / `&var x` bind to a by-reference parameter; the callee mutates
        # the caller's value in place -- no transfer, no copy.
        if isinstance(expr, ReferenceExpr):
            return

        src_type = getattr(expr, 'resolved_type', None) or target_type
        if src_type is None:
            return

        if self._is_no_copy_type(src_type):
            if self._is_aliasing_expr(expr):
                if is_return:
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot return NoCopy type `{src_type}` without `move` in {context}",
                        line, column,
                        hint="use `move` to transfer ownership instead"
                    )
                else:
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot copy value of type `{src_type}` which implements NoCopy",
                        line, column,
                        hint="use `move` to transfer ownership instead"
                    )
        elif self._is_explicit_copy_type(src_type):
            # ExplicitCopy gets the same move-required treatment as NoCopy:
            # the compiler never implicitly duplicates it. Duplication must be a
            # visible `.copy()`; a plain transfer must be a `move`.
            if self._is_aliasing_expr(expr):
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"cannot copy value of type `{src_type}` which implements ExplicitCopy",
                    line, column,
                    hint="use .copy() for an explicit deep copy, or `move` to transfer ownership"
                )
        elif self._is_implicit_copy_type(src_type):
            if self._is_aliasing_expr(expr):
                expr.needs_copy = True

    def _check_no_copy_return(self, return_type: SawType, final_expr: Optional[Expression],
                               context_name: str, line: int, column: int):
        """Validate an implicit tail return of a NoCopy type uses `move`.

        Thin wrapper delegating to the shared value-transfer checkpoint so that
        implicit tail returns and explicit `return x` statements enforce the
        same rule.
        """
        self._check_value_transfer(final_expr, return_type, context_name,
                                    line, column, is_return=True)

    def _check_integer_literal_range(self, literal: IntLiteral, target_type: SawType):
        """Check if an integer literal fits in the target fixed-width integer type."""
        # Define ranges for each integer type
        # INT and UINT are system-width (64-bit on most platforms)
        ranges = {
            TypeKind.INT: (-9223372036854775808, 9223372036854775807),
            TypeKind.UINT: (0, 18446744073709551615),
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
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"integer literal {literal.value} out of range for {type_name} ({min_val} to {max_val})",
                literal.line, literal.column
            )

    def _check_no_copy_containment(self):
        """Check that structs containing NoCopy fields also implement NoCopy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already implements NoCopy
            if self.namespace.type_conforms_to(struct_name, "NoCopy"):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_no_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains NoCopy field `{field_name}` of type `{field_type}` but does not implement NoCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: NoCopy {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_implicit_copy_containment(self):
        """Check that structs containing ImplicitCopy fields also implement a copy policy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already declares a copy policy or NoCopy.
            # (NoCopy types can contain ImplicitCopy fields since they can't be
            # copied anyway; an ExplicitCopy struct copies the field explicitly
            # in its own copy().)
            if (self.namespace.type_conforms_to(struct_name, "ImplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_implicit_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains ImplicitCopy field `{field_name}` of type `{field_type}` but does not implement ImplicitCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: ImplicitCopy {{ func copy(self) -> {struct_name} {{ ... }} }}`"
                    )
                    break  # Only report once per struct

    def _check_explicit_copy_containment(self):
        """Check that structs containing ExplicitCopy fields declare ExplicitCopy or NoCopy."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already declares ExplicitCopy or NoCopy.
            # (NoCopy types can contain ExplicitCopy fields since they can't be
            # copied anyway.) ImplicitCopy is NOT sufficient: an ExplicitCopy
            # field cannot be cheaply/implicitly duplicated.
            if (self.namespace.type_conforms_to(struct_name, "ExplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "NoCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_explicit_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"struct `{struct_name}` contains ExplicitCopy field `{field_name}` of type `{field_type}` but does not implement ExplicitCopy",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: ExplicitCopy {{ func copy(self) -> {struct_name} {{ ... }} }}` or make it NoCopy"
                    )
                    break  # Only report once per struct

    def _check_copy_trait_exclusivity(self):
        """ImplicitCopy and ExplicitCopy are mutually exclusive on one type."""
        for struct_name in self.namespace.structs:
            if (self.namespace.type_conforms_to(struct_name, "ImplicitCopy") and
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy")):
                struct_info = self.namespace.structs[struct_name]
                self._error(
                    ErrorKind.CANNOT_COPY,
                    f"type `{struct_name}` cannot implement both ImplicitCopy and ExplicitCopy",
                    struct_info.line, struct_info.column,
                    hint="pick one copy policy: ImplicitCopy (cheap, auto-invoked) or ExplicitCopy (deep, explicit `.copy()`)"
                )

    def _check_derivable_copy(self):
        """A struct with a compiler-derived memberwise copy() cannot contain a
        NoCopy field: NoCopy values can never be duplicated, so the member cannot
        be copied. Runs after all conformances are registered so field copy tiers
        are known regardless of declaration order."""
        for struct_name in self._derived_copy_structs:
            struct_info = self.namespace.structs.get(struct_name)
            if struct_info is None:
                continue
            for field_name, field_type in struct_info.fields.items():
                if self._is_no_copy_type(field_type):
                    self._error(
                        ErrorKind.CANNOT_COPY,
                        f"cannot derive copy() for `{struct_name}`: field `{field_name}` "
                        f"of type `{field_type}` implements NoCopy and cannot be copied",
                        struct_info.line, struct_info.column,
                        hint="give the field a copyable type, or write copy() by hand"
                    )

    def _check_deinit_containment(self):
        """Check that structs containing Deinit fields also implement Deinit."""
        for struct_name, struct_info in self.namespace.structs.items():
            # Skip if struct already implements Deinit (or NoCopy/ImplicitCopy/ExplicitCopy which imply Deinit)
            if (self.namespace.type_conforms_to(struct_name, "Deinit") or
                self.namespace.type_conforms_to(struct_name, "NoCopy") or
                self.namespace.type_conforms_to(struct_name, "ImplicitCopy") or
                self.namespace.type_conforms_to(struct_name, "ExplicitCopy")):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                if self._is_deinit_type(field_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"struct `{struct_name}` contains Deinit field `{field_name}` of type `{field_type}` but does not implement Deinit",
                        struct_info.line, struct_info.column,
                        hint=f"add `extension {struct_name}: Deinit {{ func deinit(var self) {{ ... }} }}`"
                    )
                    break  # Only report once per struct

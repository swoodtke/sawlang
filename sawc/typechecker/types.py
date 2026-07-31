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
    SawType, TypeKind, Visibility,
    Expression, Identifier, MoveExpr, ReferenceExpr, IntLiteral, Block,
    MemberAccess, ArrayIndex, TupleIndex, SelfExpr, ClosureExpr
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
        # Search imported modules (for types that lost symbol during
        # substitution). Design 40 item 1 (L3): honor visibility — a private
        # struct of another module is not a candidate — and flag a name
        # exported by two different modules as an ambiguity instead of
        # resolving it silently by dict order.
        return self._cross_module_lookup('struct', name,
                                         lambda ns: ns.lookup_struct(name))

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
        # Search imported modules (for types that lost symbol during
        # substitution). Design 40 item 1 (L3): visibility-honoring,
        # ambiguity-detecting fallback — see get_struct_info.
        return self._cross_module_lookup('enum', name,
                                         lambda ns: ns.lookup_enum(name))

    def _cross_module_lookup(self, category, name, lookup):
        """Visibility-honoring cross-module fallback for a bare type name.

        Scans imported module namespaces for `name`, keeping only symbols
        that are not PRIVATE (a private symbol of another module is invisible
        to the importer). Distinct definitions in two different modules are an
        unresolvable ambiguity — the bare use cannot pick one — so we report
        it (mirroring the merge-time collision diagnostic of design 26)
        instead of resolving by dict order. Builtins, which every module
        namespace shares by reference, dedup by object identity so re-seeing
        the same symbol object across modules is not a collision.
        """
        matches = []  # list of (module_name, symbol)
        for module_name, module_sym in self.namespace.modules.items():
            if not module_sym.namespace:
                continue
            sym = lookup(module_sym.namespace)
            if sym is None or getattr(sym, 'visibility', None) == Visibility.PRIVATE:
                continue
            # Dedup shared objects (builtins) by identity.
            if any(sym is existing for _, existing in matches):
                continue
            matches.append((module_name, sym))
        if not matches:
            return None
        if len(matches) >= 2:
            reported = getattr(self, '_reported_xmod_ambiguities', None)
            if reported is None:
                reported = set()
                self._reported_xmod_ambiguities = reported
            key = (category, name)
            if key not in reported:
                reported.add(key)
                src1, src2 = matches[0][0], matches[1][0]
                self.reporter.error(
                    ErrorKind.UNKNOWN_TYPE,
                    f"ambiguous {category} `{name}`: defined in both "
                    f"`{src1}` and `{src2}`",
                    1, 1,
                    hint=f"qualify the use (e.g. `{src1}.{name}`), or import "
                         f"`{name}` from a single module",
                )
        return matches[0][1]

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
    # design 51: `any Trait` existential validation
    #
    # Two rules, both checked on DECLARED types (signatures, fields, bindings):
    #   1. Unsized discipline: `any Trait` is legal ONLY as the pointee of a
    #      reference (`&any Trait`) or the first type argument of `Box`
    #      (`Box<any Trait, A>`). Anywhere else it is rejected with a clean
    #      message — erased values live only behind explicit ownership.
    #   2. Object safety (v1): the trait must be dispatchable — not a marker
    #      (no methods), no associated types, and no method that takes/returns
    #      `Self` by value (the Copy family) or is generic. The `&var self`
    #      RECEIVER is always fine: it is not a `Self`-by-value parameter (the
    #      receiver slot is a VOID placeholder in `param_types`), so a mutating
    #      trait method is any-able (the future `Resumable` executor consumer).
    # =========================================================================

    # Compiler-known non-dispatchable marker traits: erasing them to `any` has
    # nothing to call. Send/Sync are structural markers; NoCopy is a pure marker
    # whose only resolved method is the inherited `deinit` (not a dispatch
    # surface); Copy/ImplicitCopy/ExplicitCopy are Self-by-value anyway.
    _EXISTENTIAL_MARKER_TRAITS = {"Send", "Sync", "NoCopy"}

    def _validate_existential_type(self, t: Optional[SawType], line: int,
                                   column: int, slot_ok: bool = False):
        """Recursively enforce design 51's unsized discipline + object safety.

        `slot_ok` is True exactly at the two positions where an erased value is
        legal: the immediate pointee of a reference and `Box`'s first type arg.
        """
        if t is None:
            return
        kind = t.kind
        if kind == TypeKind.EXISTENTIAL:
            if not slot_ok:
                tn = t.existential_trait
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`any {tn}` is unsized and cannot be used by value here",
                    line, column,
                    hint=f"an erased value is legal only behind explicit "
                         f"ownership: `&any {tn}` (borrowed) or `Box<any {tn}>` "
                         f"(owned) — design 51")
                return
            self._check_object_safety(t.existential_trait, line, column)
            return
        if kind == TypeKind.REFERENCE:
            self._validate_existential_type(t.inner_type, line, column, slot_ok=True)
            return
        if kind == TypeKind.STRUCT:
            is_box = (t.struct_name == "Box")
            for i, a in enumerate(t.type_args or []):
                self._validate_existential_type(
                    a, line, column, slot_ok=(is_box and i == 0))
            return
        if kind == TypeKind.OPTIONAL:
            self._validate_existential_type(t.inner_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.POINTER:
            self._validate_existential_type(t.inner_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.ARRAY:
            self._validate_existential_type(
                t.array_element_type, line, column, slot_ok=False)
            return
        if kind == TypeKind.TUPLE:
            for e in (t.element_types or []):
                self._validate_existential_type(e, line, column, slot_ok=False)
            return
        if kind == TypeKind.ENUM:
            for a in (t.type_args or []):
                self._validate_existential_type(a, line, column, slot_ok=False)
            return
        if kind == TypeKind.FUNCTION:
            for p in (t.param_types or []):
                self._validate_existential_type(p, line, column, slot_ok=False)
            self._validate_existential_type(
                t.func_return_type, line, column, slot_ok=False)
            return

    def _check_object_safety(self, trait_name: str, line: int, column: int):
        """Diagnose why `any Trait` is (not) object-safe. Reported once per trait
        name to avoid duplicate diagnostics across many use sites."""
        reported = getattr(self, "_obj_safety_reported", None)
        if reported is None:
            reported = set()
            self._obj_safety_reported = reported

        simple = trait_name.split('.')[-1]
        trait = self.get_trait_info(simple, qualified_path=trait_name)
        if trait is None:
            trait = self.get_trait_info(simple)
        if trait is None:
            if trait_name not in reported:
                reported.add(trait_name)
                self._error(
                    ErrorKind.UNKNOWN_TYPE,
                    f"unknown trait `{trait_name}` in `any {trait_name}`",
                    line, column)
            return

        if trait.name in reported:
            return

        def fail(msg, hint=None):
            reported.add(trait.name)
            self._error(ErrorKind.TYPE_MISMATCH,
                        f"cannot form `any {trait_name}`: {msg}", line, column,
                        hint=hint)

        # Marker / non-dispatchable.
        if trait.name in self._EXISTENTIAL_MARKER_TRAITS or len(trait.methods) == 0:
            fail(f"`{trait.name}` is a marker trait with no methods to dispatch",
                 hint="only a trait with instance methods can be erased to `any`")
            return

        # Associated types (pinning `any T<Item = ...>` is deferred).
        if trait.associated_types:
            fail(f"`{trait.name}` has an associated type "
                 f"`{trait.associated_types[0]}` — `any` over a trait with "
                 f"associated types is not yet supported")
            return

        # Per-method safety: Self-by-value params/returns, generic methods.
        for mname, m in trait.methods.items():
            rt = m.return_type
            if rt is not None and rt.kind == TypeKind.SELF:
                fail(f"method `{mname}` returns `Self` by value "
                     f"(Self-by-value signatures, including the Copy family, are "
                     f"not object-safe)")
                return
            for pt in (m.param_types or []):
                if pt is not None and pt.kind == TypeKind.SELF:
                    fail(f"method `{mname}` takes `Self` by value "
                         f"(Self-by-value parameters are not object-safe)")
                    return
            if getattr(m, "type_params", None):
                fail(f"method `{mname}` is generic — generic methods are not "
                     f"object-safe")
                return

    def _validate_existentials_in_program(self, program):
        """Signature-level pass: validate every declared `any Trait` occurrence in
        struct fields, enum payloads, function/method signatures, and trait
        method signatures. Binding annotations are validated in the statement
        checker. Runs after trait registration so object safety can be judged."""
        for struct in getattr(program, 'structs', []):
            for field in struct.fields:
                self._validate_existential_type(
                    field.type, getattr(field, 'line', struct.line),
                    getattr(field, 'column', struct.column))
        for enum in getattr(program, 'enums', []):
            for variant in enum.variants:
                for payload in (variant.associated_types or []):
                    pt = payload[1] if isinstance(payload, tuple) else payload
                    self._validate_existential_type(pt, enum.line, enum.column)
        for func in getattr(program, 'functions', []):
            self._validate_function_signature_existentials(func)
        for ext in getattr(program, 'extensions', []):
            for method in ext.methods:
                self._validate_function_signature_existentials(method)
        for trait in getattr(program, 'traits', []):
            for tm in trait.methods:
                for p in tm.parameters:
                    self._validate_existential_type(
                        getattr(p, 'type', None), tm.line, tm.column)
                self._validate_existential_type(
                    tm.return_type, tm.line, tm.column)

    def _validate_function_signature_existentials(self, fn):
        line = getattr(fn, 'line', 0)
        column = getattr(fn, 'column', 0)
        for p in getattr(fn, 'parameters', []):
            self._validate_existential_type(getattr(p, 'type', None), line, column)
        self._validate_existential_type(
            getattr(fn, 'return_type', None), line, column)

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
                return SawType(TypeKind.TUPLE, element_types=resolved_elems,
                               tuple_field_names=saw_type.tuple_field_names)
            return saw_type
        elif saw_type.kind == TypeKind.ENUM:
            if saw_type.type_args:
                resolved_args = [self._resolve_type_alias(t) for t in saw_type.type_args]
                return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args, symbol=saw_type.symbol)
            return saw_type
        else:
            return saw_type

    def _append_default_type_args(self, name: str, args, is_enum: bool = False):
        """Design 37 — canonical default-type-parameter fill.

        Given the type arguments written at a reference site for a named
        struct/enum, append the declared DEFAULTS for any omitted trailing type
        parameters, so `Vector<Int>` canonicalizes to `Vector<Int, Global>`
        BEFORE the type is ever used for identity/mangling. This is the single
        identity rule: because every resolution path funnels through here,
        `Vector<Int>` and `Vector<Int, Global>` collapse to one type, one
        mangled name, one monomorphized struct — they can never diverge.

        Total and non-diagnostic: if a missing trailing parameter has no default
        the arg list is left under-applied (the arity error is raised at the
        construction/annotation check, not here). Defaults referencing an
        earlier parameter are not supported — every default in the stdlib is a
        ground type (`Global`); such a default is resolved as written.
        """
        info = self.get_enum_info(name) if is_enum else self.get_struct_info(name)
        params = getattr(info, 'type_params', None) if info is not None else None
        if not params or len(args) >= len(params):
            return args
        filled = list(args)
        for i in range(len(args), len(params)):
            default = getattr(params[i], 'default', None)
            if default is None:
                break
            filled.append(self._resolve_type(default))
        return filled

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
                            if resolved_args:
                                resolved_args = self._append_default_type_args(simple_name, resolved_args)
                            return SawType(TypeKind.STRUCT, struct_name=simple_name, type_args=resolved_args, symbol=symbol)
                        elif symbol.kind == SymbolKind.ENUM:
                            if resolved_args:
                                resolved_args = self._append_default_type_args(simple_name, resolved_args, is_enum=True)
                            return SawType(TypeKind.ENUM, enum_name=simple_name, type_args=resolved_args, symbol=symbol)

            # Check if this is actually an enum (NOT a type alias - those stay as STRUCT)
            # Use get_enum_info which searches imported modules
            enum_symbol = self.get_enum_info(struct_name, from_type=saw_type)
            if enum_symbol:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args] if saw_type.type_args else None
                if resolved_args:
                    resolved_args = self._append_default_type_args(struct_name, resolved_args, is_enum=True)
                return SawType(TypeKind.ENUM, enum_name=struct_name, type_args=resolved_args, symbol=enum_symbol)
            # Recursively resolve type args
            if saw_type.type_args:
                resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
                # Design 37: fill omitted trailing type args from their defaults
                # (`Vector<Int>` -> `Vector<Int, Global>`) so the canonical
                # identity is fixed at resolution time.
                resolved_args = self._append_default_type_args(struct_name, resolved_args)
                return SawType(TypeKind.STRUCT, struct_name=struct_name, type_args=resolved_args)
        elif saw_type.kind == TypeKind.OPTIONAL and saw_type.inner_type:
            # Recursively resolve optional inner types
            resolved_inner = self._resolve_type(saw_type.inner_type)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif saw_type.kind == TypeKind.TUPLE and saw_type.element_types:
            # Recursively resolve tuple element types
            resolved_elements = [self._resolve_type(t) for t in saw_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elements,
                           tuple_field_names=saw_type.tuple_field_names)
        elif saw_type.kind == TypeKind.ENUM and saw_type.type_args:
            # Recursively resolve enum type args
            resolved_args = [self._resolve_type(t) for t in saw_type.type_args]
            resolved_args = self._append_default_type_args(saw_type.enum_name, resolved_args, is_enum=True)
            return SawType(TypeKind.ENUM, enum_name=saw_type.enum_name, type_args=resolved_args, symbol=saw_type.symbol)
        elif saw_type.kind == TypeKind.FUNCTION:
            # Recursively resolve function param and return types
            resolved_params = [self._resolve_type(t) for t in (saw_type.param_types or [])]
            resolved_return = self._resolve_type(saw_type.func_return_type) if saw_type.func_return_type else None
            return SawType(TypeKind.FUNCTION, param_types=resolved_params, func_return_type=resolved_return, func_is_sync=saw_type.func_is_sync, func_is_escaping=saw_type.func_is_escaping)
        return saw_type

    def _stamp_escaping_roles(self, t: Optional[SawType], is_param: bool = False,
                              report_at=None):
        """Stamp function types with their escaping bit by syntactic role (design
        16/29).

        A function type in PARAMETER position is non-escaping by default (the
        `escaping` marker in its post-parameter slot opts in — the parser already
        set the bit). A function type in ANY OTHER role — struct field, enum
        payload, function return, let/var binding annotation, or nested inside a
        container in those roles — is IMPLICITLY escaping: the value it names
        outlives the current call, so it must be safe to store. Writing the
        marker in a non-parameter role is redundant and reported once via
        `report_at=(line, column)`.

        Called on declared types at registration/binding time so that every
        VALUE carries the correct bit and the variance check in
        `_check_value_transfer` reads it directly.
        """
        if t is None:
            return t
        if t.kind == TypeKind.FUNCTION:
            if not is_param:
                if t.func_is_escaping and report_at is not None:
                    line, col = report_at
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        "redundant `escaping` — closure types outside parameter "
                        "position are always escaping",
                        line, col
                    )
                t.func_is_escaping = True
            for p in (t.param_types or []):
                self._stamp_escaping_roles(p, is_param=True, report_at=report_at)
            self._stamp_escaping_roles(t.func_return_type, is_param=False,
                                       report_at=report_at)
        elif t.kind == TypeKind.OPTIONAL:
            self._stamp_escaping_roles(t.inner_type, is_param=False, report_at=report_at)
        elif t.kind == TypeKind.TUPLE:
            for e in (t.element_types or []):
                self._stamp_escaping_roles(e, is_param=False, report_at=report_at)
        elif t.kind == TypeKind.ARRAY:
            self._stamp_escaping_roles(t.array_element_type, is_param=False, report_at=report_at)
        elif t.kind in (TypeKind.STRUCT, TypeKind.ENUM):
            for a in (t.type_args or []):
                self._stamp_escaping_roles(a, is_param=False, report_at=report_at)
        return t

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

        # A diverging expression has the bottom type NEVER (design 49): it never
        # produces a value, so it is assignable into any expected home.
        if a.kind == TypeKind.NEVER:
            return True

        # None literal is compatible with any optional
        if a.is_none_literal() and b.is_optional():
            return True
        if b.is_none_literal() and a.is_optional():
            return True

        # None literal is compatible with any type that can be wrapped in optional
        # This allows: if cond { value } else { None } to work
        if b.is_none_literal() or a.is_none_literal():
            return True

        # Reference target `&T` / `&var T`: accept a matching reference, or an
        # UnsafePointer<T> (the stdlib bridges a raw payload pointer into a
        # scoped reference closure argument, e.g. Mutex.lock's `body(payload)`).
        # Both lower to a pointer, so this is representation-safe.
        if b.kind == TypeKind.REFERENCE and a.kind in (TypeKind.REFERENCE, TypeKind.POINTER):
            ai, bi = a.inner_type, b.inner_type
            if ai is None or bi is None:
                return True
            if self._types_compatible(ai, bi, allow_literal_to_distinct):
                return True
            return str(ai) == str(bi)

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

        # Integer compatibility. A platform `Int`/`UInt` (which is also the type
        # of an UNSUFFIXED integer literal) coerces to/from any integer type —
        # this enables `let x: Int8 = 42`. But two DISTINCT fixed-width kinds do
        # NOT implicitly convert (design 53): a suffixed literal `5u16` assigned
        # to an `Int8` is a type error; explicit `as` is required. Same-kind is
        # always compatible.
        platform_int = {TypeKind.INT, TypeKind.UINT}
        fixed_int = {TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
                     TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}
        int_kinds = platform_int | fixed_int
        if a.kind in int_kinds and b.kind in int_kinds:
            if a.kind in platform_int or b.kind in platform_int or a.kind == b.kind:
                return True
            return False

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
            if not all(self._types_compatible(at, bt)
                       for at, bt in zip(a.element_types, b.element_types)):
                return False
            # Named-tuple label rule (design 63): a named and a POSITIONAL tuple
            # of the same shape are mutually compatible (labels are a view over
            # the positional layout). Two NAMED tuples must agree on names AND
            # order; a mismatch (different names, or a reorder) is incompatible.
            an = a.tuple_field_names
            bn = b.tuple_field_names
            if an is not None and bn is not None:
                return list(an) == list(bn)
            return True

        # For struct types, check struct names match
        if a.is_struct():
            if a.struct_name == b.struct_name:
                # Same named struct — when BOTH sides carry type arguments they
                # must match. This is the D4 cross-heap-unrepresentable property
                # (design 37): a `Vector<Int, LoudAlloc>` is NOT compatible with
                # a `Vector<Int>` (= `Vector<Int, Global>`) because the allocator
                # type parameter differs. Both operands are default-filled here
                # (the comparison chokepoint), so a site that supplied a raw
                # `Vector<Int>` — an unresolved field/return annotation — still
                # compares equal to a resolved `Vector<Int, Global>` value: the
                # canonical identity holds regardless of which paths ran. A bare
                # named type on either side (a trait's `Self` resolved to the
                # plain struct name, or an abstract receiver with no applied
                # args) matches any instantiation, preserving conformance/Self.
                a_args = self._append_default_type_args(a.struct_name, a.type_args or [])
                b_args = self._append_default_type_args(b.struct_name, b.type_args or [])
                if a_args and b_args:
                    if len(a_args) != len(b_args):
                        return False
                    return all(self._types_compatible(at, bt)
                               for at, bt in zip(a_args, b_args))
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

    def _array_base_kind(self, saw_type: SawType):
        """Peel nested fixed-array layers and return the base element's TypeKind
        (design 33). `[[String; 2]; 3]` -> STRING; a non-array type returns its
        own kind. Used to extend the scalar-String containment exemption to
        arrays of String."""
        node = saw_type
        while node is not None and node.kind == TypeKind.ARRAY:
            node = node.array_element_type
        return node.kind if node is not None else None

    def _is_no_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements NoCopy (cannot be copied)."""
        if saw_type is None:
            return False

        # An escaping closure value (design 71) is move-only: it may own a heap
        # environment (the captures it took ownership of), and a bitwise copy would
        # alias that env — a double free when both copies drop. So an escaping
        # function VALUE read from an existing binding must be `move`d, exactly like
        # any NoCopy resource. A non-escaping closure borrows the frame and owns
        # nothing, so it stays freely forwardable. (A capture-less escaping closure
        # is technically copyable, but the type cannot distinguish it from an owning
        # one; move-only is the sound conservative choice. Closure struct FIELDS are
        # excluded from the NoCopy CONTAINMENT check so capture-less-closure structs
        # stay copyable — see `_check_no_copy_containment`.)
        if saw_type.kind == TypeKind.FUNCTION:
            return bool(getattr(saw_type, 'func_is_escaping', False))

        # A fixed array `[T; N]` inherits T's copy class (design 33): it is
        # NoCopy iff its element type is.
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_no_copy_type(saw_type.array_element_type)

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

        # A fixed array `[T; N]` inherits T's copy class (design 33): it is
        # ImplicitCopy iff its element type is (per-element implicit copy).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_implicit_copy_type(saw_type.array_element_type)

        # Get the type name for conformance lookup
        type_name = None
        if saw_type.kind == TypeKind.STRUCT:
            type_name = saw_type.struct_name
        elif saw_type.kind == TypeKind.ENUM:
            type_name = saw_type.enum_name
        elif saw_type.kind == TypeKind.STRING:
            # String is a compiler-known refcounted ImplicitCopy type.
            type_name = "String"

        if type_name is None:
            return False

        # Check if type conforms to ImplicitCopy
        return self.namespace.type_conforms_to(type_name, "ImplicitCopy")

    def _is_explicit_copy_type(self, saw_type: SawType) -> bool:
        """Check if a type implements ExplicitCopy (move-only, deep .copy())."""
        if saw_type is None:
            return False

        # A fixed array `[T; N]` inherits T's copy class (design 33): it is
        # ExplicitCopy iff its element type is (move by default, `.copy()`
        # duplicates per element).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_explicit_copy_type(saw_type.array_element_type)

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

    def _is_trivially_copyable(self, saw_type: SawType) -> bool:
        """A type is trivially copyable iff it can be duplicated bitwise: all
        fields are trivially copyable, and it declares no resource trait
        (Deinit / NoCopy / ImplicitCopy / ExplicitCopy). Such types auto-satisfy
        `Copy`; `.copy()` on them lowers to a bitwise copy.

        The structural logic lives on the namespace (`Namespace.is_trivially_copyable`)
        so codegen's bounded-extension gating uses the exact same rule. Here we
        only add the typechecker-local guard: an opaque generic type parameter
        currently in scope is never known to be trivial.
        """
        if (saw_type is not None and saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name in getattr(self, 'current_type_params', {})):
            return False
        return self.namespace.is_trivially_copyable(saw_type)

    def _type_satisfies_copy_bound(self, saw_type: SawType) -> bool:
        """Whether a concrete type satisfies the umbrella `Copy` bound:
        trivially copyable, or declaring ImplicitCopy / ExplicitCopy (or Copy).

        Delegates to the shared namespace helper so codegen agrees.
        """
        return self.namespace.type_satisfies_copy_bound(saw_type)

    def _is_deinit_type(self, saw_type: SawType) -> bool:
        """Check if a type implements Deinit (directly or through NoCopy/ImplicitCopy/ExplicitCopy)."""
        if saw_type is None:
            return False

        # A fixed array `[T; N]` needs element destruction iff its element type
        # does (design 33).
        if saw_type.kind == TypeKind.ARRAY:
            return self._is_deinit_type(saw_type.array_element_type)

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

    # ------------------------------------------------------------------
    # Per-function, scope-aware may-move state (design 15).
    #
    # State is a dict keyed by id(VariableInfo) -> (var_info, name, line, col).
    # The binding's VariableInfo is its identity: same-named bindings in
    # different functions or shadowing scopes are distinct objects, so they
    # never interact (the flat-set bug from brief 03). A snapshot is a plain
    # dict copy; branch merges union the surviving branch end-states.
    # ------------------------------------------------------------------

    def _binding_move_info(self, var_info):
        """Return (name, line, col) if this binding is moved-from, else None."""
        entry = self.moved_bindings.get(id(var_info))
        if entry is None:
            return None
        _, name, line, col = entry
        return name, line, col

    def _is_binding_moved(self, var_info) -> bool:
        return id(var_info) in self.moved_bindings

    def _mark_binding_moved(self, var_info, name: str, line: int, column: int):
        self.moved_bindings[id(var_info)] = (var_info, name, line, column)

    def _revive_binding(self, var_info):
        """Clear moved-state for a binding (revival by assignment)."""
        self.moved_bindings.pop(id(var_info), None)

    def _snapshot_moves(self) -> dict:
        return dict(self.moved_bindings)

    def _merge_move_branches(self, entry: dict, branches: list) -> dict:
        """Union-merge branch end-states, excluding diverged branches.

        `branches` is a list of (end_state_dict, diverges_bool). A binding is
        may-moved after the construct if ANY non-diverging branch left it moved.
        If every branch diverges (code after is unreachable), fall back to the
        pre-construct entry state.
        """
        contributing = [st for st, diverges in branches if not diverges]
        if not contributing:
            return dict(entry)
        merged: dict = {}
        for st in contributing:
            merged.update(st)
        return merged

    def _check_value_transfer(self, expr: Optional[Expression], target_type: Optional[SawType],
                              context: str, line: int, column: int,
                              is_return: bool = False):
        """Single checkpoint every copy/move site funnels through.

        Every site where a value is copied or moved into a new home (let/var
        initializers, assignment RHS, call arguments, returns, struct-field
        initializers, array/tuple elements, enum payloads) routes through here.
        It enforces NoCopy move-discipline and marks ImplicitCopy sites so codegen
        inserts `copy()` uniformly.

        Behavior by the source expression and its resolved type:
        - `move x`: ownership transfers; a transfer is neither a copy nor a
          NoCopy violation, so it is always accepted. The source binding's
          moved-from state is recorded in `_check_move_expr` (design 15), which
          runs for every `move` regardless of the enclosing transfer site.
        - by-reference argument (`&x` / `&var x`): NOT a transfer; skipped.
        - NoCopy type read from an existing binding (identifier / field access /
          index): an error -- it must be `move`d. A fresh temporary is fine.
        - ImplicitCopy type read from an existing binding: annotated
          `expr.needs_copy = True` for codegen. A fresh temporary is fine.
        - anything else: no-op.
        """
        if expr is None:
            return

        # design 24 item 3 (the `sync` boundary): a `sync` function type accepts
        # only a `sync` value. A closure LITERAL is exempt — it is effect-checked
        # in the sync context it is passed into (`_effect_enter_closure` reads the
        # expected type's `sync` flag). Any OTHER function value (a stored or
        # forwarded function, a non-`sync` function-typed field) is rejected at
        # the boundary unless its own type is `sync`, because it could suspend and
        # a `sync` context must be transitively suspension-free.
        if (target_type is not None and target_type.kind == TypeKind.FUNCTION
                and getattr(target_type, 'func_is_sync', False)
                and not isinstance(expr, ClosureExpr)):
            src = getattr(expr, 'resolved_type', None)
            if (src is not None and src.kind == TypeKind.FUNCTION
                    and not getattr(src, 'func_is_sync', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot pass a non-`sync` function value where a `{target_type}` "
                    f"is expected",
                    line, column,
                    hint="pass a `sync`-typed function value or a closure literal "
                         "that is checked suspension-free"
                )

        # design 16/29 escaping variance: a non-escaping function VALUE may not
        # flow into an escaping slot. non-escaping <: escaping (the SAFE
        # direction is escaping-value → non-escaping-slot: the callee promises
        # not to store it). The error direction is non-escaping-value → escaping
        # slot: the callee may store a value whose captures borrow a frame that
        # will die. A closure LITERAL is exempt — it is lowered to match the slot
        # (an escaping heap env when the target is escaping); only a stored/
        # forwarded function value (e.g. a non-escaping closure PARAM) is gated.
        # The target's escaping bit is set at its declaration site: closure
        # parameters default non-escaping, every other role (field, return,
        # binding) is stamped escaping by `_stamp_escaping_roles`.
        if (target_type is not None and target_type.kind == TypeKind.FUNCTION
                and getattr(target_type, 'func_is_escaping', False)
                and not isinstance(expr, ClosureExpr)):
            src = getattr(expr, 'resolved_type', None)
            if (src is not None and src.kind == TypeKind.FUNCTION
                    and not getattr(src, 'func_is_escaping', False)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot store or forward a non-escaping closure into an "
                    f"escaping `{target_type}` slot ({context})",
                    line, column,
                    hint="a non-escaping closure's captures may borrow the "
                         "enclosing frame; only call it or pass it as another "
                         "non-escaping argument"
                )

        # `move x` transfers ownership; a move is never a copy/NoCopy violation.
        # Moved-from recording happens in `_check_move_expr` (design 15).
        if isinstance(expr, MoveExpr):
            return

        # `&x` / `&var x` bind to a by-reference parameter; the callee mutates
        # the caller's value in place -- no transfer, no copy.
        if isinstance(expr, ReferenceExpr):
            return

        src_type = getattr(expr, 'resolved_type', None) or target_type
        if src_type is None:
            return

        # An escaping closure forwarded into a NON-escaping (borrowing) slot is a
        # LEND, not an ownership transfer (design 71 / design 16/29 variance): the
        # callee promises not to store it, so the caller keeps ownership and drops
        # it once. No `move` required — the closure's move-only discipline applies
        # only when it flows into an OWNING (escaping) slot (binding / field /
        # return / escaping param / container element).
        if (src_type.kind == TypeKind.FUNCTION
                and getattr(src_type, 'func_is_escaping', False)
                and target_type is not None
                and target_type.kind == TypeKind.FUNCTION
                and not getattr(target_type, 'func_is_escaping', False)):
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
        elif self.namespace.is_implicit_copy_enum(src_type):
            # An enum can't DECLARE ImplicitCopy, so its copy tier is structural
            # (design 06): an enum carrying an owning `String`/`Arc` payload copies
            # by RETAINING that payload. Marking the transfer `needs_copy` makes
            # codegen bump the refcount; without it the enum was bitwise-copied yet
            # still released its payload at every drop -> double free (DF12). Kept
            # out of `_is_implicit_copy_type` so it does NOT force a containing
            # struct to opt into ImplicitCopy (an owning-enum field is compiler-
            # handled, exactly like a `String` field).
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

    # ------------------------------------------------------------------
    # Static exclusivity check for by-reference arguments (design 08/10).
    #
    # Law of exclusivity -- "many readers XOR one writer", per call: an access
    # path passed mutably (`&var x`, or the receiver of a `var self` method)
    # must be disjoint from every OTHER by-reference path in the same call.
    # Immutable `&` paths may overlap each other freely (unobservable with no
    # writer). A `move` argument may not alias any reference argument.
    #
    # References cannot escape in Saw (no reference fields/returns, closures
    # capture by value), so every live reference was created at some call
    # expression on the stack. Aliasing therefore reduces to per-call-site
    # path disjointness plus forwarding -- and forwarding is covered because a
    # callee's `var` params are distinct storage unless the caller aliased
    # them, which the caller's own call-site check rejects. Hence fully static.
    # ------------------------------------------------------------------

    # Sentinel for an array index that is not a compile-time constant.
    _DYNAMIC_INDEX = object()

    def _build_access_path(self, expr: Expression):
        """Build an access path (root, projections) from an lvalue expression.

        root is a local/param name or 'self'. Each projection is one of
        ('field', name), ('tuple', int), or ('index', const_int | _DYNAMIC_INDEX).
        Returns None for a non-path expression (call result, literal, etc.) --
        those cannot legally appear under `&`/`&var` (rejected earlier by the
        lvalue check in `_check_reference_expr`).
        """
        projections = []
        node = expr
        while True:
            if isinstance(node, Identifier):
                projections.reverse()
                return (node.name, tuple(projections))
            if isinstance(node, SelfExpr):
                projections.reverse()
                return ('self', tuple(projections))
            if isinstance(node, MemberAccess):
                projections.append(('field', node.member))
                node = node.object
            elif isinstance(node, TupleIndex):
                projections.append(('tuple', node.index))
                node = node.tuple_expr
            elif isinstance(node, ArrayIndex):
                if isinstance(node.index, IntLiteral):
                    projections.append(('index', node.index.value))
                else:
                    projections.append(('index', self._DYNAMIC_INDEX))
                node = node.array_expr
            else:
                return None

    def _paths_overlap(self, a, b) -> bool:
        """Two access paths overlap iff they may denote overlapping storage.

        Different roots -> disjoint. Same root: walk projections in parallel;
        differing fields / tuple indices / differing *constant* array indices at
        the same position -> disjoint; a DYNAMIC index at a position overlaps
        anything there (conservative). Running out of projections on either side
        (one is a prefix of the other) -> overlap.

        Only ever consulted for pairs where at least one side is mutable/moved,
        so the dynamic-index conservatism applies exactly where the decision
        requires it.
        """
        root_a, proj_a = a
        root_b, proj_b = b
        if root_a != root_b:
            return False
        for pa, pb in zip(proj_a, proj_b):
            if pa[0] != pb[0]:
                # Different projection kinds on the same root cannot denote the
                # same storage.
                return False
            if pa[0] == 'index':
                ia, ib = pa[1], pb[1]
                if ia is self._DYNAMIC_INDEX or ib is self._DYNAMIC_INDEX:
                    continue
                if ia != ib:
                    return False
            else:
                if pa[1] != pb[1]:
                    return False
        return True

    def _render_lvalue_path(self, expr: Expression) -> str:
        """Render an lvalue expression as a source-like path (for diagnostics)."""
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, SelfExpr):
            return 'self'
        if isinstance(expr, MemberAccess):
            return f"{self._render_lvalue_path(expr.object)}.{expr.member}"
        if isinstance(expr, TupleIndex):
            return f"{self._render_lvalue_path(expr.tuple_expr)}.{expr.index}"
        if isinstance(expr, ArrayIndex):
            return f"{self._render_lvalue_path(expr.array_expr)}[{self._render_index(expr.index)}]"
        return "<expr>"

    def _render_index(self, expr: Expression) -> str:
        if isinstance(expr, IntLiteral):
            return str(expr.value)
        if isinstance(expr, Identifier):
            return expr.name
        return "…"

    def _check_reference_sigils(self, values, param_types, param_names=None):
        """Validate each reference argument's sigil against its parameter (design 34).

        Call sites mirror the parameter's reference spelling: `&x` lends to a
        `&T` parameter, `&var x` lends to a `&var T` parameter. A mismatch in
        EITHER direction is a compile error. `values` are the argument value
        expressions; `param_types` is positionally aligned; `param_names`
        (optional) names the parameter in the diagnostic when available.
        """
        if not param_types:
            return
        for i, value in enumerate(values):
            if not isinstance(value, ReferenceExpr):
                continue
            if i >= len(param_types):
                continue
            ptype = param_types[i]
            if ptype is None or ptype.kind != TypeKind.REFERENCE:
                # Bare `&`/`&var` against a by-value parameter is a plain type
                # mismatch, already reported by the caller's compatibility check.
                continue
            name = param_names[i] if param_names and i < len(param_names) else None
            named = f"parameter `{name}` is " if name else "parameter is "
            rendered = self._render_lvalue_path(value.expr)
            if ptype.reference_mutable and not value.mutable:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{named}`&var {ptype.inner_type}`; write `&var {rendered}`",
                    value.line, value.column,
                    hint="call sites mirror the parameter's reference spelling"
                )
            elif not ptype.reference_mutable and value.mutable:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"{named}`&{ptype.inner_type}`; write `&{rendered}`",
                    value.line, value.column,
                    hint="call sites mirror the parameter's reference spelling"
                )

    def _check_call_exclusivity(self, values, param_types=None,
                                receiver: Optional[Expression] = None,
                                receiver_mutable: bool = False,
                                param_names=None):
        """Enforce the law of exclusivity across one call's by-reference paths.

        `values` are the argument value expressions; `param_types` (optional,
        positionally aligned). `receiver`/`receiver_mutable` describe a method
        receiver: the receiver of a `var self` method is a mutable path.

        Reference-argument sigils are validated first (design 34): after that,
        each `&`/`&var` argument's mutability is read straight from its sigil,
        which agrees with the parameter by construction.

        By-value arguments are NOT collected -- snapshot semantics (the copy
        happens at call setup), which is what makes a by-value argument that
        overlaps a `&var` well-defined.
        """
        # Validate that each reference argument's sigil matches its parameter.
        self._check_reference_sigils(values, param_types, param_names)
        # Each entry: (kind, path, name_expr, line, column) where kind is one of
        # 'mut', 'imm', 'moved'. name_expr renders the offending path.
        entries = []

        # A method receiver is always a borrow (`&self`/`&var self` -- the parser
        # requires it; static/init calls pass receiver=None). Collect it either
        # way: a `var self` receiver is a mutable path, and an immutable `&self`
        # receiver is a live shared read for the call's duration, so aliasing it
        # with a `&var` argument (`c.read(&var c)`) is an exclusivity violation.
        if receiver is not None:
            path = self._build_access_path(receiver)
            if path is not None:
                entries.append(('mut' if receiver_mutable else 'imm', path,
                                receiver, receiver.line, receiver.column))

        if param_types is None:
            param_types = []
        for i, value in enumerate(values):
            if isinstance(value, ReferenceExpr):
                path = self._build_access_path(value.expr)
                if path is None:
                    continue
                # Mutability comes from the sigil; `_check_reference_sigils` has
                # already ensured it agrees with the parameter (design 34).
                is_mut = bool(value.mutable)
                entries.append(('mut' if is_mut else 'imm', path, value.expr,
                                value.line, value.column))
            elif isinstance(value, MoveExpr):
                entries.append(('moved', (value.variable, ()), value,
                                value.line, value.column))
            elif isinstance(value, ClosureExpr):
                # design 16/29 item 4: the borrow captures of a non-escaping
                # closure argument are hidden reference parameters of THIS call,
                # so they join the access set — checked pairwise against the
                # receiver, the other arguments, and the other closures' captures.
                # `v.each { [&var v] in ... }` (mutably capturing the iterated
                # collection) collides with the `&self` receiver and is rejected;
                # a disjoint `[&total]` is fine.
                for spec in (getattr(value, 'capture_specs', None) or []):
                    if spec.mode not in ('ref', 'ref_var'):
                        continue
                    name_expr = Identifier(name=spec.name, line=spec.line,
                                           column=spec.column)
                    path = self._build_access_path(name_expr)
                    if path is None:
                        continue
                    entries.append(('mut' if spec.mode == 'ref_var' else 'imm',
                                    path, name_expr, spec.line, spec.column))

        n = len(entries)
        for i in range(n):
            ki, pi, ei, li, ci = entries[i]
            for j in range(i + 1, n):
                kj, pj, ej, lj, cj = entries[j]
                if ki == 'imm' and kj == 'imm':
                    continue
                if not self._paths_overlap(pi, pj):
                    continue
                moved_side = None
                if ki == 'moved' and kj != 'moved':
                    moved_side = (ei, li, ci)
                elif kj == 'moved' and ki != 'moved':
                    moved_side = (ej, lj, cj)
                if moved_side is not None:
                    m_expr, m_line, m_col = moved_side
                    self._error(
                        ErrorKind.EXCLUSIVITY_VIOLATION,
                        f"cannot `move` `{self._render_move(m_expr)}` while it is "
                        f"also passed by reference in the same call",
                        m_line, m_col,
                        hint="a moved value cannot alias a reference argument in the same call"
                    )
                    continue
                if ki == 'moved' and kj == 'moved':
                    # Two moves of overlapping storage -- outside this brief's
                    # scope (no reference involved); leave to move analysis.
                    continue
                # At least one side is mutable and it overlaps another path.
                if ki == 'mut':
                    m_expr, m_line, m_col = ei, li, ci
                else:
                    m_expr, m_line, m_col = ej, lj, cj
                self._error(
                    ErrorKind.EXCLUSIVITY_VIOLATION,
                    f"exclusive access violation: `{self._render_lvalue_path(m_expr)}` "
                    f"is passed as `&var` while also being accessed in the same call",
                    m_line, m_col,
                    hint="disjoint access paths are allowed (e.g. `&var p.x` with `&p.y`); "
                         "give the mutable reference exclusive access"
                )

    def _render_move(self, expr: Expression) -> str:
        if isinstance(expr, MoveExpr):
            return expr.variable
        return self._render_lvalue_path(expr)

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
            # design 62 G1: compiler-synthesized coroutine frames are never copied
            # (constructed, resumed by `&var`, dropped in place), so a NoCopy field
            # such as a frame-resident `TaskGroup` is sound without a NoCopy
            # conformance. (Their owning fields are torn down memberwise.)
            if struct_name.startswith("__Frame_"):
                continue
            # Skip if struct already implements NoCopy
            if self.namespace.type_conforms_to(struct_name, "NoCopy"):
                continue

            # Check each field
            for field_name, field_type in struct_info.fields.items():
                # A closure FIELD does not force the struct NoCopy (design 71): a
                # capture-less closure is genuinely copyable, and its declared field
                # type cannot say whether a stored value owns an env. (An owning
                # closure stored in a copyable struct that is THEN copied is a
                # documented residual gap — it needs value-flow, not type, analysis.)
                if field_type is not None and field_type.kind == TypeKind.FUNCTION:
                    continue
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
                # String is a compiler-known ImplicitCopy value type; unlike a
                # user Rc it does not force containing structs to opt in (a plain
                # struct holding a String keeps the pre-refcount behavior:
                # bitwise field, no imposed copy/deinit policy). A fixed array of
                # String is exempt on the same footing (design 33): its per-element
                # retain/release is compiler-handled, so a `[String; N]` field does
                # not force a policy any more than a scalar `String` field does.
                if self._array_base_kind(field_type) == TypeKind.STRING:
                    continue
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

    def _check_derivable_equals(self):
        """A struct/enum with a compiler-derived `==` (design 32) requires every
        field / payload to be Equatable, so the memberwise / payload-deep
        comparison is well-defined. Reports the first non-conforming member.
        Runs after all conformances are registered so field Equatable status is
        known regardless of declaration order."""
        for type_name in self._derived_equals_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_equatable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `==` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Equatable`",
                            struct_info.line, struct_info.column,
                            hint="give the field an Equatable type, or write "
                                 "`equals` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_equatable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `==` for `{type_name}`: payload "
                                f"`{field_name}` of variant `{variant_name}` has "
                                f"type `{field_type}` which does not conform to "
                                f"`Equatable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload an Equatable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_derivable_compare(self):
        """A struct/enum with a compiler-derived `compare` (design 48) requires
        every field / payload to be Comparable, so the lexicographic comparison
        is well-defined. Reports the first non-conforming member. Runs after all
        conformances are registered."""
        for type_name in self._derived_compare_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_comparable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `compare` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Comparable`",
                            struct_info.line, struct_info.column,
                            hint="give the field a Comparable type, or write "
                                 "`compare` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_comparable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `compare` for `{type_name}`: "
                                f"payload `{field_name}` of variant "
                                f"`{variant_name}` has type `{field_type}` which "
                                f"does not conform to `Comparable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload a Comparable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_derivable_hash(self):
        """A struct/enum with a compiler-derived `hash` (design 48) requires
        every field / payload to be Hashable. Reports the first non-conforming
        member. Runs after all conformances are registered."""
        for type_name in self._derived_hash_types:
            struct_info = self.namespace.structs.get(type_name)
            if struct_info is not None:
                for field_name, field_type in struct_info.fields.items():
                    if not self.namespace.is_hashable(field_type):
                        self._error(
                            ErrorKind.TYPE_MISMATCH,
                            f"cannot derive `hash` for `{type_name}`: field "
                            f"`{field_name}` of type `{field_type}` does not "
                            f"conform to `Hashable`",
                            struct_info.line, struct_info.column,
                            hint="give the field a Hashable type, or write "
                                 "`hash` by hand"
                        )
                        break
                continue
            enum_info = self.namespace.enums.get(type_name)
            if enum_info is not None:
                done = False
                for variant_name, fields in enum_info.variants.items():
                    for field_name, field_type in fields:
                        if not self.namespace.is_hashable(field_type):
                            self._error(
                                ErrorKind.TYPE_MISMATCH,
                                f"cannot derive `hash` for `{type_name}`: payload "
                                f"`{field_name}` of variant `{variant_name}` has "
                                f"type `{field_type}` which does not conform to "
                                f"`Hashable`",
                                enum_info.ast_node.line if enum_info.ast_node else 0,
                                enum_info.ast_node.column if enum_info.ast_node else 0,
                                hint="give the payload a Hashable type"
                            )
                            done = True
                            break
                    if done:
                        break

    def _check_ord_hash_require_equatable(self):
        """Comparable and Hashable both REQUIRE Equatable (design 48): a type
        that conforms to either must already be Equatable, so `==` and the
        `compare`/`hash` results agree. Runs after all conformances are
        registered so auto-Equatable (POD) types satisfy the requirement without
        a redundant `extension T: Equatable {}`."""
        from ast_nodes import SawType, TypeKind

        def _type_of(name: str):
            if name in self.namespace.structs:
                return SawType(TypeKind.STRUCT, struct_name=name)
            if name in self.namespace.enums:
                return SawType(TypeKind.ENUM, enum_name=name)
            return None

        for type_name, trait in (
            [(n, "Comparable") for n in self._comparable_types]
            + [(n, "Hashable") for n in self._hashable_types]
        ):
            st = _type_of(type_name)
            if st is None:
                continue
            if not self.namespace.is_equatable(st):
                loc = self.namespace.structs.get(type_name) or self.namespace.enums.get(type_name)
                line = getattr(loc, 'line', 0)
                column = getattr(loc, 'column', 0)
                if line == 0 and getattr(loc, 'ast_node', None) is not None:
                    line, column = loc.ast_node.line, loc.ast_node.column
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"`{type_name}` conforms to `{trait}` but not to `Equatable`: "
                    f"`{trait}` requires `Equatable`",
                    line, column,
                    hint=f"add `extension {type_name}: Equatable {{}}`"
                )

    def _check_deinit_containment(self):
        """Check that structs containing Deinit fields also implement Deinit."""
        for struct_name, struct_info in self.namespace.structs.items():
            # design 44/62: compiler-synthesized coroutine frames (`__Frame_*`) are
            # exempt — their owning fields (opt-encoded locals, embedded sub-frames,
            # and a design-62 G1 frame-resident `TaskGroup`) are torn down by the
            # transform/codegen memberwise drop at the frame's own drop sites, not
            # via a user Deinit conformance.
            if struct_name.startswith("__Frame_"):
                continue
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

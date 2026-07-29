"""
Registration methods for the Saw type checker.

This module provides mixin methods for registering type definitions, structs,
enums, traits, functions, and extensions during the first pass of type checking.

Usage:
    class TypeChecker(RegistrationMixin, ...):
        pass
"""

from typing import Dict
from ast_nodes import (
    TypeDefinition, Struct, Enum, Trait, Function, Extension, Method, Parameter,
    SawType, TypeKind, Visibility,
    Block, ReturnStatement, BreakStatement, ContinueStatement, IfExpr
)
from errors import ErrorKind
from namespace import (
    SymbolKind, FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol,
    TypeAliasSymbol, TraitMethodSymbol
)


class RegistrationMixin:
    """Mixin providing registration methods for TypeChecker.

    These methods are used in the first pass of type checking to collect
    all type definitions before checking function/method bodies.

    Methods:
        _register_builtins: Register built-in functions and types
        _block_has_early_exit: Check if a block definitely exits early
        _register_type_definition: Register a type alias
        _register_struct: Register a struct definition
        _register_enum: Register an enum definition
        _register_trait: Register a trait definition
        _register_function: Register a function signature
        _register_extern_function: Register an external (FFI) function
        _register_extension: Register methods from an extension
        _check_trait_conformance: Verify type implements trait
        _types_compatible_for_trait: Check type compatibility for traits
        _resolve_trait_type: Resolve Self and associated types in trait
    """

    def _register_builtins(self):
        """Register built-in functions."""
        # print can take any single argument
        # We'll handle it specially in check_function_call
        #
        # Note: Built-in traits (Deinit, ImplicitCopy, NoCopy) are defined
        # in builtin.saw and loaded automatically by the compiler.

        # Register String as a pseudo-struct so it can be extended
        # String is a primitive type (i8*) but we want to add methods to it
        self.namespace.register_struct("String", StructSymbol(
            fields={},
            field_order=[],
            line=0,
            column=0
        ))

        # String is a compiler-known refcounted value type: ImplicitCopy (a copy
        # is a refcount bump) + Deinit (release, free at zero). The copy/deinit
        # bodies are IR-level runtime helpers emitted by codegen, so the
        # conformance is registered here rather than declared in stdlib. This
        # drives value-transfer copy() insertion and scope-exit cleanup.
        self.namespace.register_conformance("String", "ImplicitCopy")
        self.namespace.register_conformance("String", "Deinit")
        # String is Equatable builtin (design 32): content equality via the
        # hand-written `String.equals` in std/string.saw; `==` on String lowers
        # to a call to it (fixing the old pointer-identity comparison, S4).
        self.namespace.register_conformance("String", "Equatable")

        # Register Result<T, E> as a built-in generic enum
        from ast_nodes import TypeParameter

        result_type_params = [
            TypeParameter(name="T", line=0, column=0),
            TypeParameter(name="E", line=0, column=0)
        ]
        self.namespace.register_enum("Result", EnumSymbol(
            variants={
                "Ok": [("value", SawType(TypeKind.TYPE_PARAM, type_param_name="T"))],
                "Err": [("error", SawType(TypeKind.TYPE_PARAM, type_param_name="E"))]
            },
            variant_order=["Ok", "Err"],
            type_params=result_type_params
        ))

        # Register Error trait for error types
        self.namespace.register_trait("Error", TraitSymbol(
            name="Error",
            methods={
                "message": TraitMethodSymbol(
                    name="message",
                    param_types=[SawType(TypeKind.SELF)],
                    return_type=SawType(TypeKind.STRING),
                    param_names=["self"],
                    self_mutable=False,
                    self_is_reference=True
                )
            },
            associated_types=[],
            parent_traits=[]
        ))

    def _block_has_early_exit(self, block: Block) -> bool:
        """Check if a block definitely exits early (return, break, continue).

        This checks if the block cannot fall through to the next statement.
        A block has an early exit if:
        - It contains a return/break/continue at the top level
        - It ends with an if-else where both branches have early exits
        """
        for stmt in block.statements:
            if isinstance(stmt, (ReturnStatement, BreakStatement, ContinueStatement)):
                return True
            # Check if-else: both branches must have early exits
            if isinstance(stmt, IfExpr) and stmt.else_branch:
                then_exits = self._block_has_early_exit(stmt.then_branch)
                else_exits = self._block_has_early_exit(stmt.else_branch)
                if then_exits and else_exits:
                    return True
        return False

    def _check_loop_body(self, body: Block, outer_scope):
        """Check a loop body with may-repeat move semantics (design 15 rule 7).

        Conservative (shipped) rule: a binding declared OUTSIDE the loop that is
        moved inside the body and NOT definitely reassigned before the body ends
        would be moved-from again on the next iteration -- a use-after-move
        across iterations. Each such binding is flagged at its move site. A move
        followed by a definite reassignment (revival) inside the body is fine:
        the revived binding is not moved at body end, so it is not flagged.

        `outer_scope` is the scope enclosing the loop (for a `for` loop this is
        the scope BEFORE the loop variable is bound, so moving the freshly-bound
        loop variable each iteration is not flagged). After the loop the move
        state is reset to the pre-loop state, since the loop may run zero times.
        """
        entry_moves = self._snapshot_moves()
        outer_ids = set()
        scope = outer_scope
        while scope is not None:
            for var_info in scope.variables.values():
                outer_ids.add(id(var_info))
            scope = scope.parent

        self._check_block(body)

        for key, (var_info, name, move_line, move_col) in list(self.moved_bindings.items()):
            if key in entry_moves:
                continue  # already moved before the loop -- caught elsewhere
            if key in outer_ids:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of moved variable `{name}` across loop iterations",
                    move_line, move_col,
                    hint="a binding moved inside a loop is moved-from on the next "
                         "iteration; reassign it before the loop body ends, or move a fresh value"
                )

        # The loop may execute zero times, so after it we are back to the
        # pre-loop state (any real cross-iteration move was flagged above).
        self.moved_bindings = entry_moves

    def _arm_diverges(self, body) -> bool:
        """True if a match-arm body definitely exits the enclosing scope.

        Used by the move-dataflow merge (design 15 rule 6): a diverging arm
        does not contribute to the may-moved union. A block body reuses
        `_block_has_early_exit`; a bare statement body (return/break/continue)
        diverges directly; a plain expression body does not.
        """
        if isinstance(body, Block):
            return self._block_has_early_exit(body)
        return isinstance(body, (ReturnStatement, BreakStatement, ContinueStatement))

    def _register_type_definition(self, type_def: TypeDefinition):
        """Register a type definition (type alias)."""
        if self.get_type_alias_info(type_def.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"type `{type_def.name}` is defined multiple times",
                type_def.line, type_def.column
            )
            return

        # Resolve the defined type (it might reference other type aliases)
        resolved_type = self._resolve_type_alias(type_def.defined_type)
        self.namespace.register_type_alias(type_def.name, TypeAliasSymbol(
            aliased_type=resolved_type,
            visibility=getattr(type_def, 'visibility', Visibility.PRIVATE)
        ))

    def _register_struct(self, struct: Struct):
        """Register a struct definition."""
        if self.namespace.has_struct(struct.name):
            self._error(
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
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"field `{field.name}` is defined multiple times in struct `{struct.name}`",
                    struct.line, struct.column
                )
            else:
                seen_fields.add(field.name)
                # A closure-typed field is escaping (design 16/29): the struct
                # value can outlive any call, so a stored closure must be safe to
                # store. Stamp the bit; writing `escaping` here is redundant.
                self._stamp_escaping_roles(
                    field.type, is_param=False,
                    report_at=(getattr(field, 'line', struct.line),
                               getattr(field, 'column', struct.column)))
                fields[field.name] = field.type
                field_order.append(field.name)

        self.namespace.register_struct(struct.name, StructSymbol(
            fields=fields,
            field_order=field_order,
            type_params=struct.type_params,
            visibility=getattr(struct, 'visibility', Visibility.PRIVATE),
            line=struct.line,
            column=struct.column,
            ast_node=struct if struct.type_params else None
        ))

    def _register_enum(self, enum: Enum):
        """Register an enum definition."""
        if self.namespace.has_enum(enum.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,  # Reuse this error kind
                f"enum `{enum.name}` is defined multiple times",
                enum.line, enum.column
            )
            return

        if self.namespace.has_struct(enum.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"enum `{enum.name}` conflicts with existing struct name",
                enum.line, enum.column
            )
            return

        # Check for duplicate variants
        variants = {}
        variant_order = []
        seen_variants = set()

        for variant in enum.variants:
            if variant.name in seen_variants:
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"variant `{variant.name}` is defined multiple times in enum `{enum.name}`",
                    enum.line, enum.column
                )
            else:
                seen_variants.add(variant.name)
                # Enum payloads are escaping roles (design 16/29), like fields.
                for _payload in (variant.associated_types or []):
                    _pt = _payload[1] if isinstance(_payload, tuple) else _payload
                    self._stamp_escaping_roles(
                        _pt, is_param=False, report_at=(enum.line, enum.column))
                variants[variant.name] = variant.associated_types
                variant_order.append(variant.name)

        # Register in namespace only
        self.namespace.register_enum(enum.name, EnumSymbol(
            variants=variants,
            variant_order=variant_order,
            type_params=enum.type_params,
            visibility=getattr(enum, 'visibility', Visibility.PRIVATE),
            ast_node=enum if enum.type_params else None
        ))

    def _register_trait(self, trait: Trait):
        """Register a trait definition with inheritance support."""
        if self.namespace.has_trait(trait.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"trait `{trait.name}` is defined multiple times",
                trait.line, trait.column
            )
            return

        # Validate and collect inherited methods from parent traits
        inherited_methods = {}
        inherited_assoc_types = []
        for parent_name in trait.parent_traits:
            parent_info = self.get_trait_info(parent_name)
            if parent_info is None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"unknown parent trait `{parent_name}`",
                    trait.line, trait.column
                )
                continue
            # Inherit all methods from parent (already TraitMethodSymbol)
            for method_name, method_sym in parent_info.methods.items():
                inherited_methods[method_name] = method_sym
            # Inherit associated types
            for assoc_type in parent_info.associated_types:
                if assoc_type not in inherited_assoc_types:
                    inherited_assoc_types.append(assoc_type)

        # Build method symbol map from this trait's own methods
        methods = dict(inherited_methods)  # Start with inherited
        for method in trait.methods:
            # Collect parameter info (excluding self placeholder type)
            param_names = []
            param_types = []

            for param in method.parameters:
                if param.name == "self":
                    # self has the type of the implementing type (handled during conformance)
                    param_types.append(SawType(TypeKind.VOID))  # Placeholder
                else:
                    param_names.append(param.name)
                    param_types.append(param.type)

            methods[method.name] = TraitMethodSymbol(
                name=method.name,
                param_types=param_types,
                return_type=method.return_type,
                param_names=param_names,
                self_mutable=method.self_mutable,
                self_is_reference=method.self_is_reference
            )

        # Collect associated type names (own + inherited)
        assoc_type_names = list(inherited_assoc_types)
        for at in trait.associated_types:
            if at.name not in assoc_type_names:
                assoc_type_names.append(at.name)

        self.namespace.register_trait(trait.name, TraitSymbol(
            name=trait.name,
            methods=methods,
            associated_types=assoc_type_names,
            parent_traits=trait.parent_traits,
            visibility=getattr(trait, 'visibility', Visibility.PRIVATE)
        ))

    def _register_function(self, func: Function):
        """Register a function signature."""
        if self.namespace.has_function(func.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{func.name}` is defined multiple times",
                func.line, func.column
            )
            return

        # For generic functions, don't resolve types yet (they may contain type params)
        if func.type_params:
            param_types = [p.type for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            return_type = func.return_type
        else:
            # Resolve types before registering
            param_types = [self._resolve_type(p.type) for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            return_type = self._resolve_type(func.return_type)
            # Escaping roles (design 16/29): parameter closure types default
            # non-escaping; the return type is an escaping role.
            for _pt in param_types:
                self._stamp_escaping_roles(_pt, is_param=True,
                                           report_at=(func.line, func.column))
            self._stamp_escaping_roles(return_type, is_param=False,
                                       report_at=(func.line, func.column))
            # Update AST with resolved type for codegen
            func.return_type = return_type

        self.namespace.register_function(func.name, FunctionSymbol(
            param_types=param_types,
            param_names=param_names,
            return_type=return_type,
            type_params=func.type_params,
            visibility=getattr(func, 'visibility', Visibility.PRIVATE),
            is_sync=getattr(func, 'is_sync', False),
            ast_node=func if func.type_params else None
        ))

    def _register_extern_function(self, extern_func):
        """Register an external (FFI) function signature."""
        # Resolve types for extern functions
        param_types = [self._resolve_type(p.type) for p in extern_func.parameters]
        param_names = [p.name for p in extern_func.parameters]
        resolved_return_type = self._resolve_type(extern_func.return_type)

        existing = self.get_function_info(extern_func.name)
        if existing is not None:
            # Allow duplicate extern declarations with the same signature
            # This enables library code (like std/) to declare externs that
            # user code may also declare
            if (existing.param_types == param_types and
                existing.return_type == resolved_return_type):
                return  # Same signature, allow it
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{extern_func.name}` is defined multiple times with different signatures",
                extern_func.line, extern_func.column
            )
            return

        self.namespace.register_function(extern_func.name, FunctionSymbol(
            param_types=param_types,
            param_names=param_names,
            return_type=resolved_return_type,
            is_variadic=extern_func.is_variadic,
            is_blocking=getattr(extern_func, 'is_blocking', False)
        ))

    # Built-in type names that indicate specialization when used in extension type params
    BUILTIN_TYPE_NAMES = {
        'Int', 'UInt', 'Float', 'Bool', 'String',
        'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
    }

    def _is_known_type(self, name: str) -> bool:
        """Check if a name refers to a known type (built-in or user-defined)."""
        return (name in self.BUILTIN_TYPE_NAMES or
                self.namespace.has_struct(name) or
                self.namespace.has_enum(name) or
                self.get_type_alias_info(name) is not None)

    def _get_specialization_key(self, extension: Extension) -> tuple:
        """Check if extension is a specialization and return the type args key.

        Returns tuple of type arg names if specialized (e.g., ("String",)),
        or empty tuple if it's a generic extension.
        """
        if not extension.type_params:
            return ()

        # Check if any type param is actually a known type (specialization)
        type_args = []
        for tp in extension.type_params:
            if self._is_known_type(tp.name):
                type_args.append(tp.name)
            else:
                # If any param is NOT a known type, this is a generic extension
                return ()

        # Design 37: pad omitted trailing parameters with the struct's declared
        # defaults so `extension Vector<String>` keys as `("String", "Global")`,
        # matching a lookup on the fully-applied `Vector<String, Global>`.
        struct_info = self.get_struct_info(extension.struct_name)
        params = getattr(struct_info, 'type_params', None) if struct_info else None
        if params and len(type_args) < len(params):
            for i in range(len(type_args), len(params)):
                default = getattr(params[i], 'default', None)
                if (default is None or default.kind != TypeKind.STRUCT
                        or default.struct_name is None):
                    break
                type_args.append(default.struct_name)

        return tuple(type_args)

    def _register_enum_equatable_extension(self, extension: Extension):
        """Register an `extension E: Equatable {}` on an enum (design 32).

        Enums don't carry methods today, so the only extension supported on one
        is an empty Equatable opt-in: it registers the conformance and records
        the enum for payload-deep `==` (synthesized inline by codegen). A custom
        `equals`, other conformances, or type assignments are rejected here.
        """
        enum_name = extension.struct_name
        if (extension.conformances != ["Equatable"] or extension.methods
                or extension.type_assignments):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot extend enum `{enum_name}`: only an empty "
                f"`extension {enum_name}: Equatable {{}}` is supported",
                extension.line, extension.column,
                hint="enums support Equatable opt-in (payload-deep `==`); other "
                     "methods and conformances on enums are not available"
            )
            return
        self.namespace.register_conformance(enum_name, "Equatable")
        self._derived_equals_types.add(enum_name)

    def _register_extension(self, extension: Extension):
        """Register methods from an extension."""
        # Enum Equatable opt-in (design 32): intercept before the struct lookup
        # so `extension Color: Equatable {}` doesn't hit "undefined struct".
        if self.get_enum_info(extension.struct_name) is not None:
            self._register_enum_equatable_extension(extension)
            return

        # Verify the struct exists (check namespace)
        struct_info = self.get_struct_info(extension.struct_name)
        if struct_info is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"cannot extend undefined struct `{extension.struct_name}`",
                extension.line, extension.column
            )
            return

        # Memberwise `copy()` derivation: a struct declaring ImplicitCopy or
        # ExplicitCopy without a hand-written `copy` gets a compiler-synthesized
        # memberwise copy. We only register its signature here (so conformance
        # passes and callers type-check `.copy()`); the body is skipped by the
        # typechecker and emitted memberwise by codegen, where every field's
        # copy tier is known regardless of declaration order. Structs needing
        # derivation are recorded for a post-registration NoCopy-field check.
        declares_copy_policy = ("ImplicitCopy" in extension.conformances or
                                "ExplicitCopy" in extension.conformances)
        has_copy_method = any(not m.is_init and m.name == "copy"
                              for m in extension.methods)
        if declares_copy_policy and not has_copy_method:
            synthesized = Method(
                name="copy",
                parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                      is_reference=True)],
                return_type=SawType(TypeKind.SELF),
                body=Block(statements=[], final_expr=None,
                           line=extension.line, column=extension.column),
                self_mutable=False,
                self_is_reference=True,
                is_derived_copy=True,
                line=extension.line,
                column=extension.column,
            )
            extension.methods.append(synthesized)
            self._derived_copy_structs.add(extension.struct_name)

        # Memberwise `equals()` synthesis (design 32): a struct declaring
        # Equatable without a hand-written `equals` gets a compiler-synthesized
        # memberwise `==`. Register the signature here so conformance passes and
        # `.equals()` type-checks; the body is skipped by the typechecker and
        # emitted memberwise by codegen. Runs BEFORE the conformance
        # "missing methods" check below, so an empty body does not error.
        declares_equatable = "Equatable" in extension.conformances
        has_equals_method = any(not m.is_init and m.name == "equals"
                                for m in extension.methods)
        if declares_equatable and not has_equals_method:
            synth_eq = Method(
                name="equals",
                parameters=[
                    Parameter(name="self", type=SawType(TypeKind.VOID),
                              is_reference=True),
                    Parameter(name="other", type=SawType(TypeKind.SELF),
                              is_reference=False),
                ],
                return_type=SawType(TypeKind.BOOL),
                body=Block(statements=[], final_expr=None,
                           line=extension.line, column=extension.column),
                self_mutable=False,
                self_is_reference=True,
                is_derived_equals=True,
                line=extension.line,
                column=extension.column,
            )
            extension.methods.append(synth_eq)
            self._derived_equals_types.add(extension.struct_name)

        # Check if this is a specialized extension (e.g., extension Vector<String>)
        specialization_key = self._get_specialization_key(extension)
        is_specialized = len(specialization_key) > 0

        # Conditional-conformance bounds: methods declared in a bounded extension
        # (e.g. `extension Vector<T: Copy>`) only exist for instantiations whose
        # type args satisfy the bounds. Record the bounds on each method symbol so
        # a call on an unsatisfying instantiation (Vector<File>.copy()) is caught.
        extension_bounds = {tp.name: list(tp.bounds)
                            for tp in extension.type_params if tp.bounds}

        # Get the target method dict for duplicate checking (from namespace StructSymbol)
        if is_specialized:
            target_methods = struct_info.specialized_methods.get(specialization_key, {})
        else:
            target_methods = struct_info.methods

        for method in extension.methods:
            # For init methods, allow multiple with different parameter signatures
            # Use parameter names in the key to distinguish them
            if method.is_init:
                param_names = tuple(p.name for p in method.parameters)
                method_key = f"init:{','.join(param_names)}"
            else:
                method_key = method.name

            # Check for duplicate methods in target dict
            if method_key in target_methods:
                if method.is_init:
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"init method with parameters ({', '.join(p.name for p in method.parameters)}) is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                else:
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"method `{method.name}` is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                continue

            # For instance methods (not init and not static), validate 'self' parameter
            self_mutable = False
            if not method.is_init and not method.is_static:
                if len(method.parameters) == 0:
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"method `{method.name}` must have 'self' as first parameter",
                        method.line, method.column
                    )
                    continue

                first_param = method.parameters[0]
                if first_param.name != "self":
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"first parameter of method must be named 'self', got `{first_param.name}`",
                        method.line, method.column
                    )
                    continue

                # Get self mutability from the method's AST node
                self_mutable = method.self_mutable

                # Fill in the self parameter type (if it's the placeholder VOID from parser)
                expected_self_type = SawType(TypeKind.STRUCT, struct_name=extension.struct_name)
                if first_param.type.kind == TypeKind.VOID:
                    # Replace placeholder with actual type
                    first_param.type = expected_self_type
                elif not self._types_compatible(first_param.type, expected_self_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"'self' parameter must have type `{extension.struct_name}`, got `{first_param.type}`",
                        method.line, method.column
                    )

            # For init methods, check parameter names don't conflict with field names
            if method.is_init:
                param_names_set = {p.name for p in method.parameters}
                field_names_set = set(struct_info.fields.keys())
                if param_names_set == field_names_set:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"init method parameters match field names exactly - this is ambiguous with field initialization",
                        method.line, method.column,
                        hint="use different parameter names to distinguish from field init"
                    )

            # Register method
            # Determine the Self type for this extension
            if extension.struct_name == "String":
                self_type = SawType(TypeKind.STRING)
            else:
                self_type = SawType(TypeKind.STRUCT, struct_name=extension.struct_name)

            # Resolve Self types in parameter types
            # Note: 'self' parameter has VOID as placeholder from parser
            param_types = []
            for p in method.parameters:
                if p.name == "self" or p.type.kind == TypeKind.SELF:
                    param_types.append(self_type)
                else:
                    # Resolve type aliases and enum types
                    param_types.append(self._resolve_type(p.type))
            param_names = [p.name for p in method.parameters]

            # For init methods, override return type to be the struct type
            # For non-init methods, resolve Self in return type
            return_type = method.return_type
            if return_type.kind == TypeKind.SELF:
                return_type = self_type
            elif method.is_init:
                return_type = self_type
            else:
                # Resolve enum types (e.g., Result<T, E>) that are parsed as STRUCT
                return_type = self._resolve_type(return_type)

            # Escaping roles (design 16/29): method parameter closure types
            # default non-escaping; return type is an escaping role.
            for _pt in param_types:
                self._stamp_escaping_roles(_pt, is_param=True,
                                           report_at=(method.line, method.column))
            self._stamp_escaping_roles(return_type, is_param=False,
                                       report_at=(method.line, method.column))

            # Collect default values for parameters
            default_values = [p.default_value for p in method.parameters]

            # Register in namespace
            method_symbol = FunctionSymbol(
                kind=SymbolKind.METHOD,
                param_types=param_types,
                param_names=param_names,
                return_type=return_type,
                # Method-level generic type params (brief 36): the `U` in
                # `func map<U>(...)`, distinct from the extension's own params.
                type_params=method.type_params,
                default_values=default_values,
                is_static=method.is_static,
                is_init=method.is_init,
                self_mutable=self_mutable,
                self_is_reference=method.self_is_reference,
                extension_bounds=extension_bounds,
                ast_node=method
            )
            if method.is_init:
                self.namespace.register_init_method(extension.struct_name, method_symbol)
            elif is_specialized:
                # Register specialized method with type specialization key
                self.namespace.register_specialized_method(
                    extension.struct_name, specialization_key, method.name, method_symbol)
            else:
                self.namespace.register_method(extension.struct_name, method.name, method_symbol)

        # Collect type assignments once (shared across all trait conformances)
        local_assignments: Dict[str, SawType] = {}
        for type_assign in extension.type_assignments:
            local_assignments[type_assign.name] = type_assign.assigned_type

        # Check trait conformances
        for trait_name in extension.conformances:
            # Send/Sync are structurally auto-derived marker traits (design 21
            # item 1): explicit conformance is never accepted (no unsafe-impl
            # story in v1). Reject with a clear message and skip registration.
            if trait_name in ("Send", "Sync"):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot explicitly implement `{trait_name}`: it is a marker trait "
                    f"derived structurally by the compiler",
                    extension.line, extension.column,
                    hint=f"remove `: {trait_name}` - a type is {trait_name} automatically "
                         f"iff all its fields are"
                )
                continue
            # Handle module-qualified trait names (e.g., "lib.Describable")
            if '.' in trait_name:
                # Module-qualified: look up in module namespace
                parts = trait_name.rsplit('.', 1)
                module_name, simple_trait_name = parts[0], parts[1]
                module_sym = self.namespace.modules.get(module_name)
                if module_sym and module_sym.namespace:
                    trait_info = module_sym.namespace.resolve(
                        simple_trait_name, check_visibility=True, accessor_module=self.namespace.module_path
                    )
                    if trait_info is None or trait_info.kind != SymbolKind.TRAIT:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{trait_name}`",
                            extension.line, extension.column
                        )
                        continue
                else:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"unknown module `{module_name}` in trait `{trait_name}`",
                        extension.line, extension.column
                    )
                    continue
            else:
                trait_info = self.get_trait_info(trait_name)
                if trait_info is None:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"unknown trait `{trait_name}`",
                        extension.line, extension.column
                    )
                    continue

            # Register conformance in namespace FIRST (so _check_trait_conformance can read it)
            self.namespace.register_conformance(extension.struct_name, trait_name, local_assignments)

            self._check_trait_conformance(extension.struct_name, trait_info, struct_info, extension)

    def _check_trait_conformance(self, type_name: str, trait_info, struct_info, extension: Extension):
        """Check that a type conforms to a trait by implementing all required methods."""
        for method_name, trait_method in trait_info.methods.items():
            if method_name not in struct_info.methods:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not implement required method `{method_name}` from trait `{trait_info.name}`",
                    extension.line, extension.column
                )
                continue

            impl_method = struct_info.methods[method_name]

            # Check self mutability matches
            if trait_method.self_mutable != impl_method.self_mutable:
                if trait_method.self_mutable:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should have `var self` to conform to trait `{trait_info.name}`",
                        extension.line, extension.column
                    )
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should have immutable `self` to conform to trait `{trait_info.name}`",
                        extension.line, extension.column
                    )

            # Check return type matches (allow Self and associated types -> concrete types)
            if not self._types_compatible_for_trait(trait_method.return_type, impl_method.return_type,
                                                         type_name, trait_info.name):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method_name}` has return type `{impl_method.return_type}` but trait `{trait_info.name}` expects `{trait_method.return_type}`",
                    extension.line, extension.column
                )

            # Check parameter count (excluding self)
            trait_param_count = len(trait_method.param_types) - 1  # Exclude self placeholder
            impl_param_count = len(impl_method.param_types) - 1    # Exclude self
            if trait_param_count != impl_param_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{method_name}` takes {impl_param_count} parameter(s) but trait `{trait_info.name}` expects {trait_param_count}",
                    extension.line, extension.column
                )

        # Check that all required associated types are provided
        type_assigns = self.namespace.get_type_assignments(type_name, trait_info.name)
        for assoc_type_name in trait_info.associated_types:
            if assoc_type_name not in type_assigns:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not provide required associated type `{assoc_type_name}` from trait `{trait_info.name}`",
                    extension.line, extension.column,
                    hint=f"add `type {assoc_type_name} = SomeType` to the extension"
                )

    def _types_compatible_for_trait(self, trait_type: SawType, impl_type: SawType,
                                         self_type_name: str, trait_name: str = None) -> bool:
        """Check if implementation type matches trait type, with Self and associated type substitution."""
        # Resolve the trait type by substituting Self and associated types
        resolved_trait_type = self._resolve_trait_type(trait_type, self_type_name, trait_name)
        return self._types_compatible(resolved_trait_type, impl_type)

    def _resolve_trait_type(self, trait_type: SawType, self_type_name: str,
                                  trait_name: str = None) -> SawType:
        """Resolve Self and associated types in a trait type."""
        # Handle Self type (TypeKind.SELF)
        if trait_type.kind == TypeKind.SELF:
            # Special case: String is a primitive type, not a struct
            if self_type_name == "String":
                return SawType(TypeKind.STRING)
            return SawType(TypeKind.STRUCT, struct_name=self_type_name)
        if trait_type.kind == TypeKind.STRUCT and trait_type.struct_name:
            # Handle associated types
            if trait_name:
                type_assigns = self.namespace.get_type_assignments(self_type_name, trait_name)
                if trait_type.struct_name in type_assigns:
                    return type_assigns[trait_type.struct_name]
            # Recursively resolve type args
            if trait_type.type_args:
                resolved_args = [self._resolve_trait_type(t, self_type_name, trait_name)
                                 for t in trait_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=trait_type.struct_name, type_args=resolved_args)
        elif trait_type.kind == TypeKind.OPTIONAL and trait_type.inner_type:
            resolved_inner = self._resolve_trait_type(trait_type.inner_type, self_type_name, trait_name)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif trait_type.kind == TypeKind.TUPLE and trait_type.element_types:
            resolved_elems = [self._resolve_trait_type(t, self_type_name, trait_name)
                              for t in trait_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elems)
        elif trait_type.kind == TypeKind.ENUM and trait_type.type_args:
            resolved_args = [self._resolve_trait_type(t, self_type_name, trait_name)
                             for t in trait_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=trait_type.enum_name, type_args=resolved_args, symbol=trait_type.symbol)
        return trait_type

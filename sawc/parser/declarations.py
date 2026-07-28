"""
Declaration parsing methods for the Saw parser.

This module provides mixin methods for parsing top-level declarations including
functions, structs, enums, traits, extensions, extern blocks, and methods.

Usage:
    class Parser(DeclarationsMixin, ...):
        pass
"""

from typing import List, Optional, Tuple, Union
from lexer import TokenType
from ast_nodes import (
    Function, Parameter, Struct, StructField,
    Enum, EnumVariant,
    Trait, TraitMethod, AssociatedType,
    Extension, Method, TypeAssignment, TypeDefinition,
    ExternBlock, ExternFunction,
    SawType, TypeKind, Visibility, TypeParameter
)


class DeclarationsMixin:
    """Mixin providing declaration parsing methods for Parser."""

    def _parse_qualified_name(self, error_msg: str) -> str:
        """Parse a potentially module-qualified name like 'Trait' or 'module.Trait'."""
        token = self.expect(TokenType.IDENT, error_msg)
        name = token.value
        # Check for module qualification (e.g., lib.Describable)
        while self.match(TokenType.DOT):
            self.advance()
            next_token = self.expect(TokenType.IDENT, f"Expected identifier after '.' in {name}")
            name = f"{name}.{next_token.value}"
        return name

    def parse_function(self, visibility: Visibility = Visibility.PRIVATE) -> Function:
        start = self.current()
        # `sync func ...` (design 22): the body is a checked suspension-free
        # effect context. The `sync` keyword precedes `func`.
        is_sync = False
        if self.match(TokenType.SYNC):
            is_sync = True
            self.advance()
        self.expect(TokenType.FUNC)

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.expect(TokenType.LPAREN)
        parameters, _, _ = self.parse_parameters()  # Ignore self_mutable/self_is_reference for regular functions
        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = SawType(TypeKind.VOID)
        if self.match(TokenType.ARROW):
            self.advance()
            return_type = self.parse_type()

        self.skip_newlines()
        body = self.parse_block()

        return Function(
            name=name,
            parameters=parameters,
            return_type=return_type,
            body=body,
            type_params=type_params,
            visibility=visibility,
            is_sync=is_sync,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_struct(self, visibility: Visibility = Visibility.PRIVATE) -> Struct:
        """Parse a struct declaration: struct Name { field: Type } or struct Box<T> { value: T }"""
        start = self.current()
        self.expect(TokenType.STRUCT)

        name_token = self.expect(TokenType.IDENT, "Expected struct name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        fields = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            field_name_token = self.expect(TokenType.IDENT, "Expected field name")
            self.expect(TokenType.COLON, "Expected ':' after field name")
            field_type = self.parse_type()
            fields.append(StructField(name=field_name_token.value, type=field_type))

            self.skip_newlines()
            # Allow optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Struct(
            name=name,
            fields=fields,
            type_params=type_params,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_enum(self, visibility: Visibility = Visibility.PRIVATE) -> Enum:
        """Parse an enum declaration: enum Name { case Variant1 } or enum Option<T> { case Some(value: T) }"""
        start = self.current()
        self.expect(TokenType.ENUM)

        name_token = self.expect(TokenType.IDENT, "Expected enum name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        variants = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            self.expect(TokenType.CASE, "Expected 'case' keyword for enum variant")

            variant_name_token = self.expect(TokenType.IDENT, "Expected variant name")
            variant_name = variant_name_token.value

            # Parse optional associated values: (name: Type, ...)
            associated_types = []
            if self.match(TokenType.LPAREN):
                self.advance()
                if not self.match(TokenType.RPAREN):
                    # Parse first parameter
                    param_name = self.expect(TokenType.IDENT, "Expected parameter name").value
                    self.expect(TokenType.COLON, "Expected ':' after parameter name")
                    param_type = self.parse_type()
                    associated_types.append((param_name, param_type))

                    # Parse additional parameters
                    while self.match(TokenType.COMMA):
                        self.advance()
                        param_name = self.expect(TokenType.IDENT, "Expected parameter name").value
                        self.expect(TokenType.COLON, "Expected ':' after parameter name")
                        param_type = self.parse_type()
                        associated_types.append((param_name, param_type))

                self.expect(TokenType.RPAREN)

            variants.append(EnumVariant(name=variant_name, associated_types=associated_types))

            self.skip_newlines()
            # Allow optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Enum(
            name=name,
            variants=variants,
            type_params=type_params,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_trait(self, visibility: Visibility = Visibility.PRIVATE) -> Trait:
        """Parse trait declaration: trait ImplicitCopy: Deinit { func copy(self) -> Self }"""
        start = self.current()
        self.expect(TokenType.TRAIT)

        name_token = self.expect(TokenType.IDENT, "Expected trait name")
        name = name_token.value

        # Parse optional type parameters
        type_params = self.parse_type_params()

        # Parse optional parent traits: `: ParentTrait, AnotherTrait`
        parent_traits = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first parent trait
            parent_token = self.expect(TokenType.IDENT, "Expected parent trait name")
            parent_traits.append(parent_token.value)
            # Parse additional parent traits (comma-separated)
            while self.match(TokenType.COMMA):
                self.advance()
                parent_token = self.expect(TokenType.IDENT, "Expected parent trait name")
                parent_traits.append(parent_token.value)

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        methods = []
        associated_types = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            if self.match(TokenType.TYPE):
                # Parse associated type: type Item
                assoc_type = self.parse_associated_type()
                associated_types.append(assoc_type)
            elif self.match(TokenType.FUNC):
                method = self.parse_trait_method()
                methods.append(method)
            else:
                self.error(f"Expected 'type' or 'func' in trait, got {self.current().type.name}")
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Trait(
            name=name,
            methods=methods,
            associated_types=associated_types,
            type_params=type_params,
            parent_traits=parent_traits,
            visibility=visibility,
            line=start.line,
            column=start.column
        )

    def parse_associated_type(self) -> AssociatedType:
        """Parse associated type declaration: type Item"""
        start = self.current()
        self.expect(TokenType.TYPE)

        name_token = self.expect(TokenType.IDENT, "Expected associated type name")

        return AssociatedType(
            name=name_token.value,
            line=start.line,
            column=start.column
        )

    def parse_trait_method(self) -> TraitMethod:
        """Parse method signature in trait: func name(&self, params...) -> Type"""
        start = self.current()
        self.expect(TokenType.FUNC, "Expected 'func' in trait method")

        name_token = self.expect(TokenType.IDENT, "Expected method name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, self_mutable, self_is_reference = self.parse_parameters()
        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = SawType(TypeKind.VOID)
        if self.match(TokenType.ARROW):
            self.advance()
            return_type = self.parse_type()

        return TraitMethod(
            name=name,
            parameters=parameters,
            return_type=return_type,
            self_mutable=self_mutable,
            self_is_reference=self_is_reference,
            line=start.line,
            column=start.column
        )

    def parse_extension(self, visibility: Visibility = Visibility.PRIVATE) -> Extension:
        """Parse extension declaration: extension Box<T>: Trait { type Item = Int; func... }

        For generic extensions like `extension Vector<T>`, the typechecker will determine
        that T is not a known type and treat it as a type parameter.
        For specialized extensions like `extension Vector<String>`, String is a known type
        so it's treated as a type argument (specialization).
        """
        start = self.current()
        self.expect(TokenType.EXTENSION)

        # Accept identifiers (type names like String, Int, Vector are all identifiers now)
        if self.match(TokenType.IDENT):
            name_token = self.advance()
            struct_name = name_token.value
        else:
            self.error("Expected type name after 'extension'")

        # Parse optional type parameters or type arguments: <T, U> or <String, Int>
        # We parse as type_params first (existing behavior), but also try to parse as types.
        # The typechecker will determine which interpretation is correct based on namespace lookup.
        type_params = []
        type_args = []

        if self.match(TokenType.LT):
            # Try to parse - could be type params (T, U) or type args (String, Int)
            # We use a hybrid approach: parse with bounds support for type params
            type_params = self.parse_type_params()

        # Parse optional trait conformances: `: Trait1, Trait2` or `: module.Trait`
        conformances = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first trait name (may be module-qualified: lib.Trait)
            trait_name = self._parse_qualified_name("Expected trait name after ':'")
            conformances.append(trait_name)
            # Parse additional traits
            while self.match(TokenType.COMMA):
                self.advance()
                trait_name = self._parse_qualified_name("Expected trait name after ','")
                conformances.append(trait_name)

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        methods = []
        type_assignments = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            if self.match(TokenType.TYPE):
                # Parse type assignment: type Item = Int
                type_assign = self.parse_type_assignment()
                type_assignments.append(type_assign)
            elif self.match(TokenType.FUNC, TokenType.INIT):
                method = self.parse_method()
                methods.append(method)
            else:
                self.error(f"Expected 'type', 'func', or 'init' in extension, got {self.current().type.name}")
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Extension(
            struct_name=struct_name,
            methods=methods,
            type_params=type_params,
            conformances=conformances,
            type_assignments=type_assignments,
            visibility=visibility,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_type_assignment(self) -> TypeAssignment:
        """Parse type assignment: type Item = Int"""
        start = self.current()
        self.expect(TokenType.TYPE)

        name_token = self.expect(TokenType.IDENT, "Expected associated type name")
        self.expect(TokenType.ASSIGN, "Expected '=' after associated type name")
        assigned_type = self.parse_type()

        return TypeAssignment(
            name=name_token.value,
            assigned_type=assigned_type,
            line=start.line,
            column=start.column
        )

    def parse_type_definition(self, visibility: Visibility = Visibility.PRIVATE) -> TypeDefinition:
        """Parse top-level type definition: type MyInt = Int"""
        start = self.current()
        self.expect(TokenType.TYPE)

        name_token = self.expect(TokenType.IDENT, "Expected type name")
        self.expect(TokenType.ASSIGN, "Expected '=' after type name")
        defined_type = self.parse_type()

        return TypeDefinition(
            name=name_token.value,
            defined_type=defined_type,
            visibility=visibility,
            line=start.line,
            column=start.column
        )

    def parse_extern_block(self) -> ExternBlock:
        """Parse extern "C" { func declarations... }"""
        start = self.current()
        self.expect(TokenType.EXTERN)

        # Expect ABI string (only "C" supported for now)
        abi_token = self.expect(TokenType.STRING, "Expected ABI string after 'extern'")
        abi = abi_token.value
        if abi != "C":
            self.error(f"Unsupported ABI: '{abi}' (only 'C' is supported)")

        self.skip_newlines()
        self.expect(TokenType.LBRACE)
        self.skip_newlines()

        functions = []
        while not self.match(TokenType.RBRACE, TokenType.EOF):
            functions.append(self.parse_extern_function())
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return ExternBlock(
            abi=abi,
            functions=functions,
            line=start.line,
            column=start.column
        )

    def parse_extern_function(self) -> ExternFunction:
        """Parse external function declaration: [blocking] func name(params, ...) -> ReturnType"""
        start = self.current()
        # `extern blocking func` (design 18/22): an unbounded FFI call, treated
        # as a suspension source. `blocking` is a soft keyword valid only here.
        is_blocking = False
        if self.match_ident("blocking"):
            is_blocking = True
            self.advance()
        self.expect(TokenType.FUNC, "Expected 'func' in extern block")

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, _, _ = self.parse_parameters()

        # Check for variadic marker (...)
        is_variadic = False
        if self.match(TokenType.ELLIPSIS):
            is_variadic = True
            self.advance()
        elif self.match(TokenType.COMMA):
            # Handle: func open(path: P, flags: I, ...) case
            self.advance()
            if self.match(TokenType.ELLIPSIS):
                is_variadic = True
                self.advance()

        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = SawType(TypeKind.VOID)
        if self.match(TokenType.ARROW):
            self.advance()
            return_type = self.parse_type()

        return ExternFunction(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_variadic=is_variadic,
            is_blocking=is_blocking,
            line=start.line,
            column=start.column
        )

    def parse_method(self) -> Method:
        """Parse method definition: func name(&self, ...) -> Type { ... }
           or init method: init(...) { ... }"""
        start = self.current()

        # Check if it's an init method
        is_init = False
        if self.match(TokenType.INIT):
            is_init = True
            name = "init"
            self.advance()
        elif self.match(TokenType.FUNC):
            self.advance()
            name_token = self.expect(TokenType.IDENT, "Expected method name")
            name = name_token.value
        else:
            self.error("Expected 'func' or 'init' in extension")

        self.expect(TokenType.LPAREN)
        parameters, self_mutable, self_is_reference, is_static = self.parse_method_parameters()
        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = SawType(TypeKind.VOID)
        if self.match(TokenType.ARROW):
            self.advance()
            return_type = self.parse_type()

        self.skip_newlines()
        body = self.parse_block()

        return Method(
            name=name,
            parameters=parameters,
            return_type=return_type,
            body=body,
            is_init=is_init,
            self_mutable=self_mutable,
            self_is_reference=self_is_reference,
            is_static=is_static,
            line=start.line,
            column=start.column,
            source_file=self.source_file
        )

    def parse_method_parameters(self):
        """Parse method parameters. Returns (params, self_mutable, self_is_reference, is_static).

        - is_static is True if no 'self' parameter is present (static method)
        - self_mutable is True if '&var self' is used
        - self_is_reference is True if '&self' or '&var self' is used
        """
        params, self_mutable, self_is_reference = self.parse_parameters()

        # Check if this is a static method (no self parameter)
        is_static = True
        if params and params[0].name == 'self':
            is_static = False

        return params, self_mutable, self_is_reference, is_static

    def parse_parameters(self):
        """Parse parameters. Returns (params, self_mutable, self_is_reference).

        - self_mutable is True if '&var self' is used
        - self_is_reference is True if '&self' or '&var self' is used
        """
        params = []
        self_mutable = False
        self_is_reference = False

        if self.match(TokenType.RPAREN):
            return params, self_mutable, self_is_reference

        while True:
            # Check for '&' before parameter (for reference parameters and &self/&var self)
            is_ref = False
            is_var = False

            if self.match(TokenType.AMPERSAND):
                is_ref = True
                self.advance()
                # Check for &var (mutable reference)
                if self.match(TokenType.VAR):
                    is_var = True
                    self.advance()
            elif self.match(TokenType.VAR):
                # Legacy: 'var self' - treat as deprecated, convert to &var self
                is_var = True
                is_ref = True  # Implied reference
                self.advance()

            # Allow both IDENT and SELF as parameter names (for method self parameter)
            if self.match(TokenType.IDENT, TokenType.SELF):
                name_token = self.advance()
            else:
                self.error("Expected parameter name")

            # Special case: 'self' doesn't need type annotation (type is inferred from extension)
            if name_token.value == "self":
                if not is_ref:
                    self.error("'self' must be a reference: use '&self' or '&var self'")
                if len(params) != 0:
                    self.error("'self' can only be the first parameter")
                self_mutable = is_var
                self_is_reference = True
                # Create a placeholder type - will be filled in by type checker
                param_type = SawType(TypeKind.VOID)  # Placeholder
                params.append(Parameter(
                    name=name_token.value,
                    type=param_type,
                    is_reference=True,
                    reference_mutable=is_var
                ))
            else:
                # Regular parameter - reference is indicated by type annotation, not prefix
                if is_ref:
                    self.error("Use reference type annotation (e.g., 'x: &Int') instead of '&x'")
                self.expect(TokenType.COLON, "Expected ':' after parameter name")
                param_type = self.parse_type()

                # Check if the type is a reference type
                param_is_ref = param_type.kind == TypeKind.REFERENCE
                param_ref_mut = param_is_ref and param_type.reference_mutable

                # Check for default value: param: Type = expr
                default_value = None
                if self.match(TokenType.ASSIGN):
                    self.advance()  # consume '='
                    default_value = self.parse_expression()

                params.append(Parameter(
                    name=name_token.value,
                    type=param_type,
                    default_value=default_value,
                    is_reference=param_is_ref,
                    reference_mutable=param_ref_mut
                ))

            if not self.match(TokenType.COMMA):
                break
            self.advance()  # consume comma

            # Check for variadic marker (...) - stop parsing parameters
            if self.match(TokenType.ELLIPSIS):
                break

        return params, self_mutable, self_is_reference

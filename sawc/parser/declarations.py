"""
Declaration parsing methods for the Saw parser.

This module provides mixin methods for parsing top-level declarations including
functions, structs, enums, interfaces, extensions, extern blocks, and methods.

Usage:
    class Parser(DeclarationsMixin, ...):
        pass
"""

from typing import List, Optional
from lexer import TokenType
from ast_nodes import (
    Function, Parameter, Struct, StructField,
    Enum, EnumVariant,
    Interface, InterfaceMethod, AssociatedType,
    Extension, Method, TypeAssignment, TypeDefinition,
    ExternBlock, ExternFunction,
    SawType, TypeKind, Visibility
)


class DeclarationsMixin:
    """Mixin providing declaration parsing methods for Parser."""

    def parse_function(self, visibility: Visibility = Visibility.PRIVATE) -> Function:
        start = self.current()
        self.expect(TokenType.FUNC)

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        self.expect(TokenType.LPAREN)
        parameters, _ = self.parse_parameters()  # Ignore self_mutable for regular functions
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
            line=start.line,
            column=start.column
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
            column=start.column
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
            column=start.column
        )

    def parse_interface(self, visibility: Visibility = Visibility.PRIVATE) -> Interface:
        """Parse interface declaration: interface CustomCopy: Deinit { func copy(self) -> Self }"""
        start = self.current()
        self.expect(TokenType.INTERFACE)

        name_token = self.expect(TokenType.IDENT, "Expected interface name")
        name = name_token.value

        # Parse optional type parameters
        type_params = self.parse_type_params()

        # Parse optional parent interfaces: `: ParentInterface, AnotherInterface`
        parent_interfaces = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first parent interface
            parent_token = self.expect(TokenType.IDENT, "Expected parent interface name")
            parent_interfaces.append(parent_token.value)
            # Parse additional parent interfaces (comma-separated)
            while self.match(TokenType.COMMA):
                self.advance()
                parent_token = self.expect(TokenType.IDENT, "Expected parent interface name")
                parent_interfaces.append(parent_token.value)

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
                method = self.parse_interface_method()
                methods.append(method)
            else:
                self.error(f"Expected 'type' or 'func' in interface, got {self.current().type.name}")
            self.skip_newlines()

        self.expect(TokenType.RBRACE)

        return Interface(
            name=name,
            methods=methods,
            associated_types=associated_types,
            type_params=type_params,
            parent_interfaces=parent_interfaces,
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

    def parse_interface_method(self) -> InterfaceMethod:
        """Parse method signature in interface: func name(self, params...) -> Type"""
        start = self.current()
        self.expect(TokenType.FUNC, "Expected 'func' in interface method")

        name_token = self.expect(TokenType.IDENT, "Expected method name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, self_mutable = self.parse_parameters()
        self.expect(TokenType.RPAREN)

        # Return type (optional, defaults to void)
        return_type = SawType(TypeKind.VOID)
        if self.match(TokenType.ARROW):
            self.advance()
            return_type = self.parse_type()

        return InterfaceMethod(
            name=name,
            parameters=parameters,
            return_type=return_type,
            self_mutable=self_mutable,
            line=start.line,
            column=start.column
        )

    def parse_extension(self, visibility: Visibility = Visibility.PRIVATE) -> Extension:
        """Parse extension declaration: extension Box<T>: Interface { type Item = Int; func... }"""
        start = self.current()
        self.expect(TokenType.EXTENSION)

        # Accept identifiers or built-in type names (String, Int, etc.)
        if self.match(TokenType.IDENT):
            name_token = self.advance()
            struct_name = name_token.value
        elif self.match(TokenType.STRING_TYPE):
            self.advance()
            struct_name = "String"
        else:
            self.error("Expected type name after 'extension'")

        # Parse optional type parameters: <T, U>
        type_params = self.parse_type_params()

        # Parse optional interface conformances: `: Interface1, Interface2`
        conformances = []
        if self.match(TokenType.COLON):
            self.advance()
            # Parse first interface name
            iface_token = self.expect(TokenType.IDENT, "Expected interface name after ':'")
            conformances.append(iface_token.value)
            # Parse additional interfaces
            while self.match(TokenType.COMMA):
                self.advance()
                iface_token = self.expect(TokenType.IDENT, "Expected interface name after ','")
                conformances.append(iface_token.value)

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
            column=start.column
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
        """Parse external function declaration: func name(params, ...) -> ReturnType"""
        start = self.current()
        self.expect(TokenType.FUNC, "Expected 'func' in extern block")

        name_token = self.expect(TokenType.IDENT, "Expected function name")
        name = name_token.value

        self.expect(TokenType.LPAREN)
        parameters, _ = self.parse_parameters()

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
            line=start.line,
            column=start.column
        )

    def parse_method(self) -> Method:
        """Parse method definition: func name(self, ...) -> Type { ... }
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
        parameters, self_mutable, is_static = self.parse_method_parameters()
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
            is_static=is_static,
            line=start.line,
            column=start.column
        )

    def parse_method_parameters(self):
        """Parse method parameters. Returns (params, self_mutable, is_static).

        - is_static is True if no 'self' parameter is present (static method)
        - self_mutable is True if 'var self' is used
        """
        params, self_mutable = self.parse_parameters()

        # Check if this is a static method (no self parameter)
        is_static = True
        if params and params[0].name == 'self':
            is_static = False

        return params, self_mutable, is_static

    def parse_parameters(self):
        """Parse parameters. Returns (params, self_mutable) where self_mutable is True if first param is 'var self'."""
        params = []
        self_mutable = False

        if self.match(TokenType.RPAREN):
            return params, self_mutable

        while True:
            # Check for 'var' before parameter name (only valid for 'self')
            is_var = False
            if self.match(TokenType.VAR):
                is_var = True
                self.advance()

            # Allow both IDENT and SELF as parameter names (for method self parameter)
            if self.match(TokenType.IDENT, TokenType.SELF):
                name_token = self.advance()
            else:
                self.error("Expected parameter name")

            # Special case: 'self' doesn't need type annotation (type is inferred from extension)
            if name_token.value == "self":
                if is_var:
                    # This is the first parameter and it's 'var self'
                    if len(params) != 0:
                        self.error("'var' can only be used with the first 'self' parameter")
                    self_mutable = True
                # Create a placeholder type - will be filled in by type checker
                param_type = SawType(TypeKind.VOID)  # Placeholder
                params.append(Parameter(name=name_token.value, type=param_type))
            else:
                if is_var:
                    self.error("'var' can only be used with 'self' parameter")
                self.expect(TokenType.COLON, "Expected ':' after parameter name")
                param_type = self.parse_type()

                # Check for default value: param: Type = expr
                default_value = None
                if self.match(TokenType.ASSIGN):
                    self.advance()  # consume '='
                    default_value = self.parse_expression()

                params.append(Parameter(name=name_token.value, type=param_type, default_value=default_value))

            if not self.match(TokenType.COMMA):
                break
            self.advance()  # consume comma

            # Check for variadic marker (...) - stop parsing parameters
            if self.match(TokenType.ELLIPSIS):
                break

        return params, self_mutable
